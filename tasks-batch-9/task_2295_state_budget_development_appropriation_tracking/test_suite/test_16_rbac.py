"""Authentication, the role matrix, agency scoping and the transfer duty-separation surface."""

from datetime import datetime, timezone

from test_helpers import (
    ApiErrorId,
    fixtures,
    make_agency_officer_headers,
    make_director_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

DOH = {"agency_code": "DOH", "name": "Department of Health", "agency_type": "EXECUTIVE"}
DOT = {"agency_code": "DOT", "name": "Department of Transportation", "agency_type": "EXECUTIVE"}


class TestEveryRoleOwnsItsExclusiveOperations:
    def test_one_lifecycle_walk_exercises_all_six_roles_without_a_single_role_refusal(
        self,
        api,
        system_admin_headers,
        budget_analyst_headers,
        budget_director_headers,
        legislative_fiscal_officer_headers,
        state_controller_headers,
    ):
        """PRD §2.1: "`SystemAdmin` is the statewide financial-system operator: it registers agencies and budget cycles and owns the logical clock."
        PRD §2.1: "`BudgetAnalyst` is budget-office staff who review requests, record revenue forecasts and federal grants, build recommendations, reduction scenarios and allotments."
        PRD §2.1: "`BudgetDirector` adopts forecasts, drives cycle phases, certifies balance, approves recommendations, allotments and transfers, and grants emergency appropriations; a director may also prepare work, in which case separation of duties blocks that same director from approving it."
        PRD §2.1: "`LegislativeFiscalOfficer` introduces appropriation line items, records committee action, and enacts the bill."
        PRD §2.1: "`StateController` releases and recalls cash, executes and reverses transfers, voids charges, freezes and unfreezes cash, and closes the fiscal year."
        PRD §2.12: "The acting role appears in the endpoint's authorised list — otherwise `ERR_FORBIDDEN_ROLE` (403). Applies to every endpoint."
        PRD §3.4: "When `committee_balance_cents` is greater than zero, the line moves `PENDING → ENACTED`: `enacted_amount_cents` is frozen at `committee_balance_cents`, `available_authority_cents` and `available_cash_cents` are recomputed, and the row's `version` increments by 1."
        PRD §3.5: "The ceiling is the smallest of the four limits."
        PRD §3.5: "On success `released_cents` on the allotment becomes `computed_release_cents`, and the cascade of §2.10 runs: the appropriation recomputes `released_cents` and `available_cash_cents` and moves its cash dimension; the cycle recomputes `total_released_cents`, `cash_utilization_pct`, and `cash_posture`; and a posture that has become `CONSTRAINED` sets `release_hold` to true on every appropriation of that cycle whose `fund_type` is `GENERAL` and whose `cash_status` is `UNRELEASED`."
        PRD §2.6: "A `SystemAdmin` moves the clock by supplying `to_iso8601`, and the response reports the new instant as `current_utc`."

        Design: Corner/rbac/each_role_can_perform_its_own_exclusive_operation
        """
        agency = validate_success(api.create_agency(DOH, system_admin_headers), 201)
        cycle = validate_success(
            api.create_budget_cycle(
                {
                    "fiscal_year": 2027,
                    "fiscal_year_start_date": "2026-07-01",
                    "reserve_balance_cents": 500_000_000,
                    "constitutional_reserve_pct": 0.05,
                },
                system_admin_headers,
            ),
            201,
        )
        cycle_id = cycle["id"]

        request = validate_success(
            api.create_agency_request(
                {
                    "budget_cycle_id": cycle_id,
                    "agency_id": agency["id"],
                    "base_budget_cents": 1_000_000_000,
                },
                make_agency_officer_headers(agency["id"]),
            ),
            201,
        )
        assert request["status"] == "DRAFT"

        forecast = validate_success(
            api.create_revenue_forecast(
                {
                    "budget_cycle_id": cycle_id,
                    "source_code": "SALES_TAX",
                    "fund_type": "GENERAL",
                    "forecast_round": "CONSENSUS_SPRING",
                    "amount_cents": 10_000_000_000,
                    "effective_from": "2026-07-01T00:00:00Z",
                    "effective_to": "2027-07-01T00:00:00Z",
                    "expected_budget_cycle_version": cycle["version"],
                },
                budget_analyst_headers,
            ),
            201,
        )
        adopted = validate_success(
            api.adopt_revenue_forecast(forecast["id"], budget_director_headers, {}), 200
        )
        assert adopted["status"] == "ADOPTED"

        validate_success(
            api.advance_cycle_phase(
                cycle_id, {"to_phase": "EXECUTIVE_PREP"}, budget_director_headers
            ),
            200,
        )
        validate_success(api.certify_cycle_balance(cycle_id, budget_director_headers, {}), 200)
        validate_success(
            api.advance_cycle_phase(cycle_id, {"to_phase": "LEGISLATIVE"}, budget_director_headers),
            200,
        )

        appropriation = validate_success(
            api.create_appropriation(
                {
                    "budget_cycle_id": cycle_id,
                    "agency_id": agency["id"],
                    "fund_type": "GENERAL",
                    "program_code": "P100",
                    "introduced_amount_cents": 2_000_000_000,
                },
                legislative_fiscal_officer_headers,
            ),
            201,
        )
        validate_success(
            api.create_committee_action(
                {
                    "appropriation_id": appropriation["id"],
                    "chamber": "HOUSE",
                    "committee_name": "Appropriations",
                    "action_type": "INCREASE",
                    "amount_cents": 100_000_000,
                    "sequence_number": 1,
                },
                legislative_fiscal_officer_headers,
            ),
            201,
        )
        enacted = validate_success(
            api.enact_appropriation(appropriation["id"], legislative_fiscal_officer_headers), 200
        )
        assert enacted["authority_status"] == "ENACTED"
        assert enacted["enacted_amount_cents"] == 2_100_000_000

        validate_success(
            api.advance_cycle_phase(cycle_id, {"to_phase": "ENACTED"}, budget_director_headers), 200
        )
        validate_success(
            api.advance_cycle_phase(cycle_id, {"to_phase": "EXECUTION"}, budget_director_headers),
            200,
        )

        allotment = validate_success(
            api.create_allotment(
                {
                    "appropriation_id": appropriation["id"],
                    "quarter": 1,
                    "requested_cents": 400_000_000,
                },
                budget_analyst_headers,
            ),
            201,
        )
        prepared = validate_success(
            api.prepare_allotment(allotment["id"], budget_analyst_headers), 200
        )
        assert prepared["computed_release_cents"] == 400_000_000
        approved = validate_success(
            api.approve_allotment(allotment["id"], budget_director_headers), 200
        )
        assert approved["status"] == "APPROVED"
        released = validate_success(
            api.release_allotment(allotment["id"], state_controller_headers), 200
        )
        assert released["status"] == "RELEASED"
        assert released["released_cents"] == 400_000_000

        clock = validate_success(
            api.set_current_utc({"to_iso8601": "2026-09-15T00:00:00Z"}, system_admin_headers), 200
        )
        # PRD §2.6 pins the value reported ("the response reports the new instant as
        # `current_utc`") but never its rendering, so the instant is compared rather
        # than the literal string.
        assert datetime.fromisoformat(
            clock["current_utc"].replace("Z", "+00:00")
        ) == datetime(2026, 9, 15, tzinfo=timezone.utc)


class TestExclusiveOperationsAreClosedToOtherRoles:
    def test_five_wrong_role_writes_are_refused_before_the_body_is_examined(
        self,
        api,
        system_admin_headers,
        agency_officer_headers,
        budget_analyst_headers,
        budget_director_headers,
        legislative_fiscal_officer_headers,
        state_controller_headers,
    ):
        """PRD §2.12: "The acting role appears in the endpoint's authorised list — otherwise `ERR_FORBIDDEN_ROLE` (403). Applies to every endpoint."
        PRD §2.1: "If the headers are well formed but the declared role is not among the roles authorised for the endpoint being called, the rejection is `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §2.12: "Monetary and count fields respect their sign rules: an `amount_cents` that its entity requires to be positive is greater than zero, a `CommitteeAction` carries `amount_cents` equal to zero for `RESTORE` and `STRIKE` and greater than zero for `SET`, `INCREASE`, and `DECREASE`, and `quarter` lies between 1 and 4 inclusive — otherwise `ERR_INVALID_AMOUNT` (422)."
        PRD §2.12: "When more than one rule could reject a request, the outcome is determined by a single global ladder, evaluated top to bottom; the first rule that fails produces the response and no later rule is consulted."
        PRD §2.1: "Every role, including `AgencyBudgetOfficer`, may call every read endpoint."
        PRD §2.12: "Code uniqueness holds: `agency_code` is unique across agencies, `fiscal_year` is unique across cycles, and `program_code` is unique within a `budget_cycle_id` and `agency_id` pair — otherwise `ERR_DUPLICATE_CODE` (409)."

        Design: Corner/rbac/cross_role_exclusive_operations_are_forbidden_for_other_roles
        """
        agency = fixtures.register_agency(**DOH)
        cycle = fixtures.open_budget_cycle()
        cycle_id = cycle["id"]

        validate_error(
            api.create_budget_cycle(
                {
                    "fiscal_year": 2028,
                    "fiscal_year_start_date": "2027-07-01",
                    "reserve_balance_cents": 500_000_000,
                },
                agency_officer_headers,
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
            403,
        )
        validate_error(
            api.create_agency(DOT, budget_director_headers),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
            403,
        )
        validate_error(
            api.create_appropriation(
                {
                    "budget_cycle_id": cycle_id,
                    "agency_id": agency["id"],
                    "fund_type": "GENERAL",
                    "program_code": "P100",
                    "introduced_amount_cents": 0,
                },
                budget_analyst_headers,
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
            403,
        )
        validate_error(
            api.create_revenue_forecast(
                {
                    "budget_cycle_id": cycle_id,
                    "source_code": "SALES_TAX",
                    "fund_type": "GENERAL",
                    "forecast_round": "CONSENSUS_SPRING",
                    "amount_cents": 0,
                    "effective_from": "2026-07-01T00:00:00Z",
                    "effective_to": "2027-07-01T00:00:00Z",
                    "expected_budget_cycle_version": cycle["version"],
                },
                legislative_fiscal_officer_headers,
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
            403,
        )
        validate_error(
            api.advance_cycle_phase(
                cycle_id, {"to_phase": "EXECUTIVE_PREP"}, state_controller_headers
            ),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
            403,
        )

        _appropriations, appropriation_meta = validate_paginated(
            api.list_appropriations(budget_analyst_headers, {"budget_cycle_id": cycle_id})
        )
        assert appropriation_meta["total_count"] == 0
        _forecasts, forecast_meta = validate_paginated(
            api.list_cycle_revenue_forecasts(cycle_id, budget_analyst_headers)
        )
        assert forecast_meta["total_count"] == 0

        validate_success(api.create_agency(DOT, system_admin_headers), 201)
        validate_success(
            api.create_budget_cycle(
                {
                    "fiscal_year": 2028,
                    "fiscal_year_start_date": "2027-07-01",
                    "reserve_balance_cents": 500_000_000,
                },
                system_admin_headers,
            ),
            201,
        )

        read = validate_success(api.get_budget_cycle(cycle_id, state_controller_headers), 200)
        assert read["phase"] == "DEVELOPMENT"


class TestSharedReadEndpoints:
    def test_all_six_roles_read_the_same_row_including_a_foreign_agency_officer(
        self,
        api,
        system_admin_headers,
        budget_analyst_headers,
        budget_director_headers,
        legislative_fiscal_officer_headers,
        state_controller_headers,
    ):
        """PRD §2.1: "Every role, including `AgencyBudgetOfficer`, may call every read endpoint."
        PRD §2.12: "For `AgencyBudgetOfficer`, `X-User-ID` equals the agency reached from the target row, directly or through the referenced `AgencyRequest`, `Appropriation`, or `FederalGrant` — otherwise `ERR_AGENCY_SCOPE_VIOLATION` (403). Applies to exactly six operations: `POST /fiscal/agency-requests`, `POST /fiscal/agency-requests/{id}/submit`, `POST /fiscal/decision-packages`, `POST /fiscal/performance-measures`, `POST /fiscal/expenditures`, and `POST /fiscal/match-commitments`."
        PRD §3.1: "Each agency also carries a derived `federal_compliance_flag`, which starts at `CLEAR`; the rules that move it to `AT_RISK` or `DEFICIENT` are described in §3.8."
        PRD §4: "Operations that act on an existing resource — every state transition, every recomputation, every read — return `200 OK`."

        Design: Corner/rbac/every_role_can_read_through_the_shared_get_endpoints
        """
        first = fixtures.register_agency(**DOH)
        second = fixtures.register_agency(**DOT)

        payloads = []
        for headers in (
            system_admin_headers,
            make_agency_officer_headers(second["id"]),
            budget_analyst_headers,
            budget_director_headers,
            legislative_fiscal_officer_headers,
            state_controller_headers,
        ):
            payloads.append(validate_success(api.get_agency(first["id"], headers), 200))

        assert len(payloads) == 6
        assert all(payload == payloads[0] for payload in payloads)
        assert payloads[0]["agency_code"] == "DOH"
        assert payloads[0]["federal_compliance_flag"] == "CLEAR"


class TestAuthenticationOutranksAuthorisation:
    def test_a_request_without_a_role_header_is_unauthenticated_on_reads_writes_and_bad_bodies(
        self, api, anonymous_headers, system_admin_headers
    ):
        """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the acting official, and `X-User-Role`, declaring the capacity in which they act."
        PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the six roles enumerated below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.12: "Headers present and `X-User-Role` is one of the six declared roles — otherwise `ERR_UNAUTHENTICATED` (401). Applies to every endpoint."
        PRD §2.12: "The body is well formed — required fields present, enum members legal, integer fields integral, `limit` within 1 to 100 and `offset` at least 0 — otherwise `ERR_INVALID_REQUEST` (400). Applies to every endpoint."
        PRD §2.12: "When more than one rule could reject a request, the outcome is determined by a single global ladder, evaluated top to bottom; the first rule that fails produces the response and no later rule is consulted."

        Design: Corner/rbac/missing_role_header_returns_unauthenticated_before_the_role_check
        """
        agency = fixtures.register_agency(**DOH)
        well_formed = {
            "fiscal_year": 2027,
            "fiscal_year_start_date": "2026-07-01",
            "reserve_balance_cents": 500_000_000,
        }

        validate_error(
            api.create_budget_cycle(well_formed, anonymous_headers),
            ApiErrorId.ERR_UNAUTHENTICATED,
            401,
        )
        validate_error(
            api.get_agency(agency["id"], anonymous_headers),
            ApiErrorId.ERR_UNAUTHENTICATED,
            401,
        )
        validate_error(
            api.create_budget_cycle(
                {
                    "fiscal_year": "not-a-year",
                    "fiscal_year_start_date": "2026-07-01",
                    "reserve_balance_cents": 500_000_000,
                },
                anonymous_headers,
            ),
            ApiErrorId.ERR_UNAUTHENTICATED,
            401,
        )

        created = validate_success(
            api.create_budget_cycle(well_formed, system_admin_headers), 201
        )
        assert created["fiscal_year"] == 2027


class TestTransferSelfApproval:
    @staticmethod
    def _transfer_proposed_by_a_director():
        ctx = fixtures.setup_transfer_pair(source_cents=1_000_000_000, target_cents=1_000_000_000)
        ctx["transfer"] = fixtures.propose_transfer(
            ctx["source"]["id"],
            ctx["target"]["id"],
            make_director_headers("dir-1"),
            amount_cents=100_000_000,
            transfer_type="INTRA_AGENCY",
            justification="realign program funding",
        )
        return ctx

    def test_the_proposing_director_is_refused_while_a_second_director_approves(self, api):
        """PRD §2.9: "Three approval actions compare the acting `X-User-ID` against the identifier recorded when the row was prepared or proposed, and reject the approval when they are equal, with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
        PRD §2.9: "Approving an allotment compares against its `prepared_by_user_id`; approving an executive recommendation compares against its `prepared_by_user_id`; approving a budget transfer compares against its `proposed_by_user_id`."
        PRD §3.6: "Approval moves the transfer `PROPOSED → APPROVED`; it requires the row to be in `PROPOSED`, the acting `X-User-ID` to differ from `proposed_by_user_id`, the source appropriation's `authority_status` to be `ENACTED`, and `amount_cents` to be within the source's `available_authority_cents`; it writes `approved_by_user_id` and increments the transfer's `version` by 1, and it touches no ledger figure whatsoever."
        PRD §3.6: "A proposed transfer is created in `PROPOSED` with `proposed_by_user_id` set to the acting identifier, `approved_by_user_id` and `decision_reason` null, and it increments the source appropriation's `version` by 1."

        Design: Corner/rbac/transfer_approval_by_its_own_proposer_is_rejected
        """
        ctx = self._transfer_proposed_by_a_director()
        transfer_id = ctx["transfer"]["id"]
        assert ctx["transfer"]["status"] == "PROPOSED"
        assert ctx["transfer"]["proposed_by_user_id"] == "dir-1"
        assert ctx["transfer"]["approved_by_user_id"] is None

        validate_error(
            api.approve_budget_transfer(transfer_id, make_director_headers("dir-1")),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
            403,
        )
        rows, _meta = validate_paginated(
            api.list_appropriation_budget_transfers(
                ctx["source"]["id"], make_director_headers("dir-1")
            )
        )
        refused = next(row for row in rows if row["id"] == transfer_id)
        assert refused["status"] == "PROPOSED"
        assert refused["approved_by_user_id"] is None

        approved = validate_success(
            api.approve_budget_transfer(transfer_id, make_director_headers("dir-2")), 200
        )
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == "dir-2"
        assert approved["proposed_by_user_id"] == "dir-1"

        assert fixtures.read_appropriation(ctx["source"]["id"])["transfers_out_cents"] == 0
        assert fixtures.read_appropriation(ctx["target"]["id"])["transfers_in_cents"] == 0


class TestAgencyOfficerPeerIsolation:
    @staticmethod
    def _two_agencies_and_one_draft_request():
        ctx = fixtures.setup_development_cycle(agencies=(DOH, DOT))
        ctx["owner_id"] = ctx["agencies"]["DOH"]["id"]
        ctx["stranger_id"] = ctx["agencies"]["DOT"]["id"]
        ctx["request"] = fixtures.create_draft_request(
            ctx["cycle"]["id"], ctx["owner_id"], base_budget_cents=1_000_000_000
        )
        return ctx

    def test_a_foreign_officer_is_refused_on_every_scoped_write_the_owner_may_perform(self, api):
        """PRD §2.1: "That comparison is transitive: an officer acting on an `AgencyRequest`, an `Appropriation`, a `DecisionPackage`, a `PerformanceMeasure`, an `Expenditure`, or a `MatchCommitment` is checked against the `agency_id` reached by following that row's chain to its owning agency, and a mismatch is rejected with `ERR_AGENCY_SCOPE_VIOLATION` (HTTP 403)."
        PRD §2.12: "For `AgencyBudgetOfficer`, `X-User-ID` equals the agency reached from the target row, directly or through the referenced `AgencyRequest`, `Appropriation`, or `FederalGrant` — otherwise `ERR_AGENCY_SCOPE_VIOLATION` (403). Applies to exactly six operations: `POST /fiscal/agency-requests`, `POST /fiscal/agency-requests/{id}/submit`, `POST /fiscal/decision-packages`, `POST /fiscal/performance-measures`, `POST /fiscal/expenditures`, and `POST /fiscal/match-commitments`."
        PRD §3.2: "The officer's `X-User-ID` must equal the `agency_id` supplied."
        PRD §3.2: "An agency may hold at most one request per cycle; a second attempt is rejected with `ERR_DUPLICATE_AGENCY_REQUEST`."
        PRD §3.2: "Submission moves the request `DRAFT → SUBMITTED`."
        PRD §3.2: "Submission recomputes `total_request_cents` and increments the request's `version` by 1."

        Design: Corner/rbac/agency_officer_cannot_act_for_another_agency
        """
        ctx = self._two_agencies_and_one_draft_request()
        request_id = ctx["request"]["id"]
        owner = make_agency_officer_headers(ctx["owner_id"])
        stranger = make_agency_officer_headers(ctx["stranger_id"])
        package_body = {
            "agency_request_id": request_id,
            "package_type": "TECHNICAL",
            "priority_rank": 1,
            "amount_cents": 300_000_000,
        }

        validate_error(
            api.create_agency_request(
                {
                    "budget_cycle_id": ctx["cycle"]["id"],
                    "agency_id": ctx["owner_id"],
                    "base_budget_cents": 1_200_000_000,
                },
                stranger,
            ),
            ApiErrorId.ERR_AGENCY_SCOPE_VIOLATION,
            403,
        )
        validate_error(
            api.create_decision_package(package_body, stranger),
            ApiErrorId.ERR_AGENCY_SCOPE_VIOLATION,
            403,
        )
        validate_error(
            api.submit_agency_request(request_id, stranger),
            ApiErrorId.ERR_AGENCY_SCOPE_VIOLATION,
            403,
        )
        assert fixtures.read_agency_request(request_id)["status"] == "DRAFT"

        validate_success(api.create_decision_package(package_body, owner), 201)
        submitted = validate_success(api.submit_agency_request(request_id, owner), 200)
        assert submitted["status"] == "SUBMITTED"
        assert submitted["total_request_cents"] == 1_300_000_000
