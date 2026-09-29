"""Rejection rules: which code fires, and which rule outranks which on the same body."""

from test_helpers import (
    ApiErrorId,
    fixtures,
    make_agency_officer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

DOH = {"agency_code": "DOH", "name": "Department of Health", "agency_type": "EXECUTIVE"}
DOT = {"agency_code": "DOT", "name": "Department of Transportation", "agency_type": "EXECUTIVE"}


class TestSignRulesOutrankNothingAboveShape:
    def test_a_zero_amount_clears_the_shape_check_and_fails_the_sign_check(self, api):
        """PRD §2.12: "Monetary and count fields respect their sign rules: an `amount_cents` that its entity requires to be positive is greater than zero, a `CommitteeAction` carries `amount_cents` equal to zero for `RESTORE` and `STRIKE` and greater than zero for `SET`, `INCREASE`, and `DECREASE`, and `quarter` lies between 1 and 4 inclusive — otherwise `ERR_INVALID_AMOUNT` (422)."
        PRD §3.2: "An `AgencyBudgetOfficer` opens the agency's ask by creating a request carrying `budget_cycle_id`, `agency_id`, and `base_budget_cents` — the continuation budget needed to keep current services, which must be strictly greater than zero."
        PRD §3.2: "A package carries `agency_request_id`, a `package_type` of `EXPANSION`, `REDUCTION`, `TECHNICAL`, or `FEDERAL_MATCH`, a `priority_rank` of at least 1 that is unique within the request (lower rank is funded first), and an `amount_cents` strictly greater than zero which is always a positive magnitude — for a `REDUCTION` package it is the magnitude of savings offered, not a negative number."
        PRD §3.2: "A request is created in `DRAFT` with `revision_count` at 0, `last_return_reason` null, and `total_request_cents` equal to `base_budget_cents`."

        Design: Corner/validations/zero_monetary_amounts_return_invalid_amount_not_invalid_request
        """
        ctx = fixtures.setup_development_cycle(agencies=(DOT,))
        cycle_id = ctx["cycle"]["id"]
        agency_id = ctx["agency"]["id"]
        officer = make_agency_officer_headers(agency_id)

        validate_error(
            api.create_agency_request(
                {"budget_cycle_id": cycle_id, "agency_id": agency_id, "base_budget_cents": 0},
                officer,
            ),
            ApiErrorId.ERR_INVALID_AMOUNT,
            422,
        )
        _rows, empty_meta = validate_paginated(
            api.list_agency_requests(officer, {"budget_cycle_id": cycle_id})
        )
        assert empty_meta["total_count"] == 0

        request = validate_success(
            api.create_agency_request(
                {
                    "budget_cycle_id": cycle_id,
                    "agency_id": agency_id,
                    "base_budget_cents": 1_000_000_000,
                },
                officer,
            ),
            201,
        )

        validate_error(
            api.create_decision_package(
                {
                    "agency_request_id": request["id"],
                    "package_type": "TECHNICAL",
                    "priority_rank": 1,
                    "amount_cents": 0,
                },
                officer,
            ),
            ApiErrorId.ERR_INVALID_AMOUNT,
            422,
        )

        stored = fixtures.read_agency_request(request["id"])
        assert stored["total_request_cents"] == 1_000_000_000
        _packages, package_meta = validate_paginated(
            api.list_decision_packages(officer, {"agency_request_id": request["id"]})
        )
        assert package_meta["total_count"] == 0


class TestPerformanceTargetStrictness:
    @staticmethod
    def _draft_request_with_a_bare_expansion_package():
        ctx = fixtures.setup_development_cycle(agencies=(DOT,))
        _request, packages = fixtures.setup_request_with_packages(
            ctx["cycle"]["id"],
            ctx["agency"]["id"],
            base_budget_cents=1_000_000_000,
            packages=(
                {"package_type": "EXPANSION", "priority_rank": 1, "amount_cents": 400_000_000},
            ),
        )
        ctx["package"] = packages[0]
        return ctx

    def test_only_a_strictly_greater_target_is_accepted(self, api, budget_analyst_headers):
        """PRD §3.2: "A measure carries `decision_package_id`, a `measure_code` of 1 to 32 characters, a `unit` of `COUNT`, `PERCENT`, `DAYS`, or `DOLLARS`, a `baseline_value` of at least zero describing current measured performance, and a `target_value` describing the performance promised if the package is funded."
        PRD §3.2: "The target must be strictly greater than the baseline; equal or lower values are rejected with `ERR_PERFORMANCE_TARGET_INVALID`."
        PRD §2.12: "A performance measure's `target_value` is strictly greater than its `baseline_value` — otherwise `ERR_PERFORMANCE_TARGET_INVALID` (422). Applies to `POST /fiscal/performance-measures` only."
        PRD §3.2: "Measures are immutable once written and can be listed per package."

        Design: Corner/validations/performance_measure_with_target_not_above_baseline_is_rejected
        """
        ctx = self._draft_request_with_a_bare_expansion_package()
        package_id = ctx["package"]["id"]
        officer = make_agency_officer_headers(ctx["agency"]["id"])

        def measure(target_value):
            return {
                "decision_package_id": package_id,
                "measure_code": "LANE_MILES",
                "unit": "COUNT",
                "baseline_value": 100,
                "target_value": target_value,
            }

        validate_error(
            api.create_performance_measure(measure(100), officer),
            ApiErrorId.ERR_PERFORMANCE_TARGET_INVALID,
            422,
        )
        validate_error(
            api.create_performance_measure(measure(99), officer),
            ApiErrorId.ERR_PERFORMANCE_TARGET_INVALID,
            422,
        )
        validate_success(api.create_performance_measure(measure(101), officer), 201)

        rows, meta = validate_paginated(
            api.list_package_performance_measures(package_id, budget_analyst_headers)
        )
        assert len(rows) == 1
        assert meta["total_count"] == 1
        assert rows[0]["target_value"] == 101


class TestDependencyRecommendOrder:
    @staticmethod
    def _accepted_request_with_a_dependent_pair():
        ctx = fixtures.setup_development_cycle(agencies=(DOT,))
        agency_id = ctx["agency"]["id"]
        request = fixtures.create_draft_request(
            ctx["cycle"]["id"], agency_id, base_budget_cents=1_000_000_000
        )
        prerequisite = fixtures.attach_package(
            request["id"],
            agency_id,
            package_type="TECHNICAL",
            priority_rank=1,
            amount_cents=300_000_000,
        )
        dependent = fixtures.attach_package(
            request["id"],
            agency_id,
            package_type="TECHNICAL",
            priority_rank=2,
            amount_cents=200_000_000,
            depends_on_package_id=prerequisite["id"],
        )
        fixtures.submit_request(request["id"], agency_id)
        fixtures.begin_review(request["id"])
        ctx["request"] = fixtures.accept_request(request["id"])
        ctx["prerequisite"] = prerequisite
        ctx["dependent"] = dependent
        return ctx

    def test_a_proposed_prerequisite_is_legal_at_create_and_illegal_at_recommend(
        self, api, budget_analyst_headers
    ):
        """PRD §2.12: "A supplied `depends_on_package_id` points at a package of the same `agency_request_id` whose status is not `DEFERRED` — otherwise `ERR_DEPENDENCY_DEFERRED` (422). Applies to `POST /fiscal/decision-packages`."
        PRD §2.12: "On recommend, the prerequisite named by `depends_on_package_id` has status `RECOMMENDED` — otherwise `ERR_DEPENDENCY_NOT_RECOMMENDED` (422). Applies to `POST /fiscal/decision-packages/{id}/recommend`."
        PRD §3.2: "An optional `depends_on_package_id` names a prerequisite package of the same request that must be recommended before this one can be; it defaults to null for an independent package, and if it names a package that is currently `DEFERRED` the creation is rejected with `ERR_DEPENDENCY_DEFERRED`."
        PRD §3.2: "Take every package of the request whose status is either `PROPOSED` or `RECOMMENDED`; packages in `DEFERRED` are excluded entirely."

        Design: Corner/validations/package_recommend_with_a_still_proposed_prerequisite_is_rejected
        """
        ctx = self._accepted_request_with_a_dependent_pair()
        request_id = ctx["request"]["id"]
        assert ctx["request"]["total_request_cents"] == 1_500_000_000

        validate_error(
            api.recommend_decision_package(ctx["dependent"]["id"], budget_analyst_headers),
            ApiErrorId.ERR_DEPENDENCY_NOT_RECOMMENDED,
            422,
        )
        assert (
            validate_success(
                api.get_decision_package(ctx["dependent"]["id"], budget_analyst_headers), 200
            )["status"]
            == "PROPOSED"
        )
        assert fixtures.read_agency_request(request_id)["total_request_cents"] == 1_500_000_000

        first = validate_success(
            api.recommend_decision_package(ctx["prerequisite"]["id"], budget_analyst_headers), 200
        )
        assert first["status"] == "RECOMMENDED"

        second = validate_success(
            api.recommend_decision_package(ctx["dependent"]["id"], budget_analyst_headers), 200
        )
        assert second["status"] == "RECOMMENDED"
        assert fixtures.read_agency_request(request_id)["total_request_cents"] == 1_500_000_000


class TestRecommendationMembershipPriority:
    @staticmethod
    def _two_agencies_with_one_recommended_and_one_proposed_package():
        # PRD §3.3: "Advancing `DEVELOPMENT → EXECUTIVE_PREP` requires the cycle to be in
        # `DEVELOPMENT` and at least one forecast of the cycle to have reached `ADOPTED`",
        # so the cycle carries an adopted forecast before the advance below.
        ctx = fixtures.setup_development_cycle(agencies=(DOH, DOT), adopt_revenue=True)
        cycle_id = ctx["cycle"]["id"]
        home = ctx["agencies"]["DOH"]
        foreign = ctx["agencies"]["DOT"]

        home_request, home_packages = fixtures.setup_accepted_request(
            cycle_id,
            home["id"],
            base_budget_cents=1_000_000_000,
            packages=(
                {"package_type": "TECHNICAL", "priority_rank": 1, "amount_cents": 300_000_000},
            ),
        )
        foreign_request, foreign_packages = fixtures.setup_accepted_request(
            cycle_id,
            foreign["id"],
            base_budget_cents=1_000_000_000,
            packages=(
                {"package_type": "TECHNICAL", "priority_rank": 1, "amount_cents": 200_000_000},
            ),
        )
        fixtures.advance_phase(cycle_id, "EXECUTIVE_PREP")
        fixtures.recommend_package(home_packages[0]["id"])

        ctx["home_request"] = home_request
        ctx["home_package"] = home_packages[0]
        ctx["foreign_request"] = foreign_request
        ctx["foreign_package"] = foreign_packages[0]
        return ctx

    def test_the_not_recommended_check_outranks_the_request_mismatch_check(
        self, api, budget_analyst_headers
    ):
        """PRD §2.12: "Every member of `recommended_package_ids` has status `RECOMMENDED` — otherwise `ERR_PACKAGE_NOT_RECOMMENDED` (422). Applies to `POST /fiscal/executive-recommendations`."
        PRD §2.12: "Every member of `recommended_package_ids` belongs to the same `agency_request_id` as the recommendation — otherwise `ERR_PACKAGE_REQUEST_MISMATCH` (422). Applies to `POST /fiscal/executive-recommendations`. Note that this sits *below* the recommended-status check, so a foreign package that is also not recommended reports `ERR_PACKAGE_NOT_RECOMMENDED`."
        PRD §3.3: "Every package named must currently be in `RECOMMENDED`, otherwise `ERR_PACKAGE_NOT_RECOMMENDED`, and must belong to the same request as the recommendation, otherwise `ERR_PACKAGE_REQUEST_MISMATCH`."
        PRD §3.3: "Sum the `amount_cents` of the named packages whose `package_type` is `EXPANSION`, `TECHNICAL`, or `FEDERAL_MATCH`; sum the `amount_cents` of the named packages whose `package_type` is `REDUCTION`; then `recommended_amount_cents` is `recommended_base_cents` plus the first sum minus the second."
        PRD §3.3: "The new row is created in `PREPARED` with `prepared_by_user_id` set to the acting `X-User-ID` and `approved_by_user_id` null."

        Design: Corner/validations/recommendation_package_membership_checks_fire_in_priority_order
        """
        ctx = self._two_agencies_with_one_recommended_and_one_proposed_package()
        request_id = ctx["home_request"]["id"]

        def payload(package_ids):
            return {
                "agency_request_id": request_id,
                "recommended_base_cents": 1_000_000_000,
                "recommended_package_ids": package_ids,
                "policy_priority": "EDUCATION",
                "expected_agency_request_version": fixtures.request_version(request_id),
            }

        both = [ctx["home_package"]["id"], ctx["foreign_package"]["id"]]
        validate_error(
            api.create_executive_recommendation(payload(both), budget_analyst_headers),
            ApiErrorId.ERR_PACKAGE_NOT_RECOMMENDED,
            422,
        )

        fixtures.recommend_package(ctx["foreign_package"]["id"])
        validate_error(
            api.create_executive_recommendation(payload(both), budget_analyst_headers),
            ApiErrorId.ERR_PACKAGE_REQUEST_MISMATCH,
            422,
        )

        _rows, empty_meta = validate_paginated(
            api.list_request_executive_recommendations(request_id, budget_analyst_headers)
        )
        assert empty_meta["total_count"] == 0

        prepared = validate_success(
            api.create_executive_recommendation(
                payload([ctx["home_package"]["id"]]), budget_analyst_headers
            ),
            201,
        )
        assert prepared["status"] == "PREPARED"
        assert prepared["recommended_amount_cents"] == 1_300_000_000


class TestExpenditureQuarterGate:
    @staticmethod
    def _enacted_line_with_no_released_cash():
        ctx = fixtures.setup_execution_cycle()
        assert ctx["appropriation"]["released_cents"] == 0
        return ctx

    def test_a_future_quarter_is_a_temporal_refusal_and_the_open_quarter_fails_on_cash(self, api):
        """PRD §3.7: "The charge's `quarter` must equal the current cycle quarter derived from the logical clock: an earlier quarter is `ERR_QUARTER_CLOSED` and a later one is `ERR_QUARTER_NOT_OPEN`."
        PRD §2.12: "The target quarter is not still in the future — otherwise `ERR_QUARTER_NOT_OPEN` (409). Applies to two operations: `POST /fiscal/allotments/{id}/release` and `POST /fiscal/expenditures`. Release demands exact equality with the current cycle quarter; an expenditure's `quarter` may not exceed it."
        PRD §2.12: "The charge fits within the appropriation's `available_cash_cents` — otherwise `ERR_INSUFFICIENT_CASH_RELEASED` (422). Applies to `POST /fiscal/expenditures` and to `POST /fiscal/allotments/{id}/recall`, where it guards a recall from pushing released cash below what has already been spent."
        PRD §3.7: "The **cash basis**, `available_cash_cents`, is `released_cents` minus `expended_cents`."
        PRD §2.6: "At startup the logical clock reads exactly `2026-08-01T00:00:00Z`; until an operator moves it, that is the current instant, and the server never falls back to the host's real time."

        Design: Corner/validations/expenditure_for_a_later_quarter_returns_quarter_not_open
        """
        ctx = self._enacted_line_with_no_released_cash()
        appropriation_id = ctx["appropriation"]["id"]
        officer = make_agency_officer_headers(ctx["agency"]["id"])

        def charge(quarter, vendor_reference):
            return {
                "appropriation_id": appropriation_id,
                "quarter": quarter,
                "amount_cents": 100_000_000,
                "object_code": "OC100",
                "vendor_reference": vendor_reference,
            }

        validate_error(
            api.create_expenditure(charge(2, "INV-FUTURE"), officer),
            ApiErrorId.ERR_QUARTER_NOT_OPEN,
            409,
        )
        validate_error(
            api.create_expenditure(charge(1, "INV-NOW"), officer),
            ApiErrorId.ERR_INSUFFICIENT_CASH_RELEASED,
            422,
        )
        validate_error(
            api.create_expenditure(charge(5, "INV-BAD"), officer),
            ApiErrorId.ERR_INVALID_AMOUNT,
            422,
        )

        assert fixtures.read_appropriation(appropriation_id)["expended_cents"] == 0
        _rows, meta = validate_paginated(
            api.list_appropriation_expenditures(appropriation_id, officer)
        )
        assert meta["total_count"] == 0


class TestCommitteeSequenceUniquenessScope:
    @staticmethod
    def _two_pending_lines_one_carrying_sequence_one():
        ctx = fixtures.setup_legislative_cycle(
            appropriations=(
                {
                    "fund_type": "GENERAL",
                    "program_code": "P100",
                    "introduced_amount_cents": 2_000_000_000,
                    "enact": False,
                },
                {
                    "fund_type": "GENERAL",
                    "program_code": "P200",
                    "introduced_amount_cents": 1_000_000_000,
                    "enact": False,
                },
            )
        )
        fixtures.record_committee_action(
            ctx["appropriations"]["P100"]["id"],
            chamber="HOUSE",
            committee_name="Appropriations",
            action_type="INCREASE",
            amount_cents=500_000_000,
            sequence_number=1,
        )
        return ctx

    def test_the_sequence_number_is_unique_per_line_not_across_the_cycle(
        self, api, legislative_fiscal_officer_headers
    ):
        """PRD §3.4: "Each action names the `appropriation_id` it acts on, the `chamber` that acted (`HOUSE`, `SENATE`, or `CONFERENCE`), a `committee_name` of 1 to 120 characters, an `action_type`, an `amount_cents`, and a `sequence_number` of at least 1 that must be unique within the appropriation — gaps in the sequence are perfectly legal, duplicates are rejected with `ERR_ACTION_SEQUENCE_DUPLICATE`."
        PRD §2.12: "`sequence_number` is not already used by another committee action of the same appropriation — otherwise `ERR_ACTION_SEQUENCE_DUPLICATE` (409). Applies to `POST /fiscal/committee-actions`."
        PRD §3.4: "When the replay completes, the appropriation's `committee_balance_cents` is the final balance; with no actions at all it equals `introduced_amount_cents`."

        Design: Corner/validations/duplicate_committee_action_sequence_number_is_rejected
        """
        ctx = self._two_pending_lines_one_carrying_sequence_one()
        first_id = ctx["appropriations"]["P100"]["id"]
        second_id = ctx["appropriations"]["P200"]["id"]

        def action(appropriation_id):
            return {
                "appropriation_id": appropriation_id,
                "chamber": "SENATE",
                "committee_name": "Finance",
                "action_type": "DECREASE",
                "amount_cents": 100_000_000,
                "sequence_number": 1,
            }

        validate_error(
            api.create_committee_action(action(first_id), legislative_fiscal_officer_headers),
            ApiErrorId.ERR_ACTION_SEQUENCE_DUPLICATE,
            409,
        )
        assert (
            fixtures.read_appropriation(first_id)["committee_balance_cents"] == 2_500_000_000
        )

        sibling = validate_success(
            api.create_committee_action(action(second_id), legislative_fiscal_officer_headers),
            201,
        )
        assert sibling["running_balance_cents"] == 900_000_000
        assert fixtures.read_appropriation(second_id)["committee_balance_cents"] == 900_000_000


class TestAgencyRequestCompositeUniqueness:
    def test_one_request_per_agency_per_cycle_and_no_more(self, api, budget_analyst_headers):
        """PRD §3.2: "An agency may hold at most one request per cycle; a second attempt is rejected with `ERR_DUPLICATE_AGENCY_REQUEST`."
        PRD §2.12: "The agency has no other request in the same `budget_cycle_id` — otherwise `ERR_DUPLICATE_AGENCY_REQUEST` (409). Applies to `POST /fiscal/agency-requests`."
        PRD §3.2: "Requests can be listed with optional `budget_cycle_id`, `agency_id`, and `status` filters."

        Design: Corner/validations/second_agency_request_for_the_same_agency_and_cycle_is_rejected
        """
        ctx = fixtures.setup_development_cycle(agencies=(DOH, DOT))
        first_cycle = ctx["cycle"]["id"]
        home = ctx["agencies"]["DOH"]["id"]
        other = ctx["agencies"]["DOT"]["id"]
        second_cycle = fixtures.open_budget_cycle(
            fiscal_year=2028, fiscal_year_start_date="2027-07-01"
        )["id"]

        original = fixtures.create_draft_request(
            first_cycle, home, base_budget_cents=1_000_000_000
        )

        validate_error(
            api.create_agency_request(
                {
                    "budget_cycle_id": first_cycle,
                    "agency_id": home,
                    "base_budget_cents": 1_200_000_000,
                },
                make_agency_officer_headers(home),
            ),
            ApiErrorId.ERR_DUPLICATE_AGENCY_REQUEST,
            409,
        )
        validate_success(
            api.create_agency_request(
                {
                    "budget_cycle_id": second_cycle,
                    "agency_id": home,
                    "base_budget_cents": 1_200_000_000,
                },
                make_agency_officer_headers(home),
            ),
            201,
        )
        validate_success(
            api.create_agency_request(
                {
                    "budget_cycle_id": first_cycle,
                    "agency_id": other,
                    "base_budget_cents": 900_000_000,
                },
                make_agency_officer_headers(other),
            ),
            201,
        )

        _rows, meta = validate_paginated(
            api.list_agency_requests(budget_analyst_headers, {"budget_cycle_id": first_cycle})
        )
        assert meta["total_count"] == 2
        assert fixtures.read_agency_request(original["id"])["base_budget_cents"] == 1_000_000_000


class TestTransferProposalRuleOrder:
    @staticmethod
    def _three_enacted_lines_across_two_agencies():
        return fixtures.setup_execution_cycle(
            agencies=(DOH, DOT),
            appropriations=(
                {
                    "fund_type": "GENERAL",
                    "program_code": "P100",
                    "introduced_amount_cents": 1_000_000_000,
                    "agency_code": "DOH",
                },
                {
                    "fund_type": "DEDICATED",
                    "program_code": "P300",
                    "introduced_amount_cents": 1_000_000_000,
                    "agency_code": "DOH",
                },
                {
                    "fund_type": "GENERAL",
                    "program_code": "P200",
                    "introduced_amount_cents": 1_000_000_000,
                    "agency_code": "DOT",
                },
            ),
        )

    def test_the_four_structural_rules_fire_in_ascending_priority_up_to_the_cap_boundary(
        self, api, budget_analyst_headers
    ):
        """PRD §3.6: "The two appropriations must differ, otherwise `ERR_TRANSFER_SAME_APPROPRIATION`. They must share the same `fund_type`, otherwise `ERR_TRANSFER_FUND_TYPE_MISMATCH`. The `transfer_type` must match the agency relationship — `INTRA_AGENCY` demands that both rows carry the same `agency_id`, `INTER_AGENCY` demands that they differ — otherwise `ERR_TRANSFER_TYPE_MISMATCH`. And the amount must respect the statutory transfer cap: it may not exceed ten percent of the source line's `enacted_amount_cents`, that cap being rounded half up to the cent, otherwise `ERR_TRANSFER_EXCEEDS_AUTHORITY_CAP`."
        PRD §3.6: "A proposed transfer is created in `PROPOSED` with `proposed_by_user_id` set to the acting identifier, `approved_by_user_id` and `decision_reason` null, and it increments the source appropriation's `version` by 1."
        PRD §3.6: "Approval moves the transfer `PROPOSED → APPROVED`; it requires the row to be in `PROPOSED`, the acting `X-User-ID` to differ from `proposed_by_user_id`, the source appropriation's `authority_status` to be `ENACTED`, and `amount_cents` to be within the source's `available_authority_cents`; it writes `approved_by_user_id` and increments the transfer's `version` by 1, and it touches no ledger figure whatsoever."
        PRD §3.6: "Execution is the `StateController`'s act and is the only point at which authority actually moves."

        Design: Corner/validations/transfer_proposal_endpoint_rules_are_checked_in_ascending_priority
        """
        ctx = self._three_enacted_lines_across_two_agencies()
        source_id = ctx["appropriations"]["P100"]["id"]
        dedicated_id = ctx["appropriations"]["P300"]["id"]
        foreign_id = ctx["appropriations"]["P200"]["id"]

        def payload(target_id, amount_cents, transfer_type, justification):
            return {
                "source_appropriation_id": source_id,
                "target_appropriation_id": target_id,
                "amount_cents": amount_cents,
                "transfer_type": transfer_type,
                "justification": justification,
                "expected_source_appropriation_version": fixtures.appropriation_version(source_id),
            }

        validate_error(
            api.create_budget_transfer(
                payload(source_id, 50_000_000, "INTRA_AGENCY", "self transfer"),
                budget_analyst_headers,
            ),
            ApiErrorId.ERR_TRANSFER_SAME_APPROPRIATION,
            422,
        )
        validate_error(
            api.create_budget_transfer(
                payload(dedicated_id, 50_000_000, "INTRA_AGENCY", "cross fund"),
                budget_analyst_headers,
            ),
            ApiErrorId.ERR_TRANSFER_FUND_TYPE_MISMATCH,
            422,
        )
        validate_error(
            api.create_budget_transfer(
                payload(foreign_id, 50_000_000, "INTRA_AGENCY", "mislabelled"),
                budget_analyst_headers,
            ),
            ApiErrorId.ERR_TRANSFER_TYPE_MISMATCH,
            422,
        )
        validate_error(
            api.create_budget_transfer(
                payload(foreign_id, 100_000_001, "INTER_AGENCY", "one cent over cap"),
                budget_analyst_headers,
            ),
            ApiErrorId.ERR_TRANSFER_EXCEEDS_AUTHORITY_CAP,
            422,
        )

        rows, meta = validate_paginated(
            api.list_appropriation_budget_transfers(source_id, budget_analyst_headers)
        )
        assert meta["total_count"] == 0
        assert rows == []

        proposed = validate_success(
            api.create_budget_transfer(
                payload(foreign_id, 100_000_000, "INTER_AGENCY", "exactly at cap"),
                budget_analyst_headers,
            ),
            201,
        )
        assert proposed["status"] == "PROPOSED"
        assert proposed["amount_cents"] == 100_000_000
        assert fixtures.read_appropriation(source_id)["transfers_out_cents"] == 0
