"""Every refusal code the contract declares, raised at the rung that owns it."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    fixtures as fx,
    parse_instant,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import (
    change_order_payload,
    change_order_decision_payload,
    disclosure_payload,
    disclosure_response_payload,
    field_event_payload,
    soil_sample_payload,
    trust_fund_claim_payload,
    work_order_payload,
)
from test_helpers.test_users import (
    COMPLIANCE_OFFICER,
    FIELD_TECHNICIAN,
    LSP_DRAFTER,
    LSP_SIGNER,
    PROJECT_COORDINATOR,
    headers_without_identity,
    make_homeowner_headers,
)


class TestReferenceResolution:
    def test_each_single_resource_read_names_its_own_entity_in_the_404(self, api):
        """PRD §2.6: "A path identifier that does not resolve yields `ERR_PROPERTY_NOT_FOUND`, `ERR_TANK_PROJECT_NOT_FOUND`, `ERR_DISCLOSURE_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_CREW_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`, `ERR_LABORATORY_NOT_FOUND`, `ERR_SOIL_SAMPLE_NOT_FOUND`, `ERR_CHANGE_ORDER_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_NFA_LETTER_NOT_FOUND` or `ERR_INSURANCE_NOTIFICATION_NOT_FOUND` as appropriate."
        PRD §2.6: "Both are resolved before any business rule runs, and both produce the 404 that names the entity that failed to resolve."

        Design: Corner/errors/read_endpoints_with_unknown_path_id_return_entity_specific_not_found
        """
        reads = [
            (api.get_disclosure, ApiErrorId.ERR_DISCLOSURE_NOT_FOUND),
            (api.get_permit, ApiErrorId.ERR_PERMIT_NOT_FOUND),
            (api.get_crew, ApiErrorId.ERR_CREW_NOT_FOUND),
            (api.get_work_order, ApiErrorId.ERR_WORK_ORDER_NOT_FOUND),
            (api.get_laboratory, ApiErrorId.ERR_LABORATORY_NOT_FOUND),
            (api.get_soil_sample, ApiErrorId.ERR_SOIL_SAMPLE_NOT_FOUND),
            (api.get_change_order, ApiErrorId.ERR_CHANGE_ORDER_NOT_FOUND),
            (api.get_trust_fund_claim, ApiErrorId.ERR_CLAIM_NOT_FOUND),
            (api.get_nfa_letter, ApiErrorId.ERR_NFA_LETTER_NOT_FOUND),
            (
                api.get_insurance_notification,
                ApiErrorId.ERR_INSURANCE_NOTIFICATION_NOT_FOUND,
            ),
        ]
        for read, expected in reads:
            response = read(NON_EXISTENT_UUID, COMPLIANCE_OFFICER)
            validate_error(response, expected.value, 404)


class TestAuthenticationAndAuthorization:
    def test_a_caller_with_no_role_header_is_stopped_before_the_lookup(self, api):
        """PRD §2.1: "If either header is absent, or if `X-User-Role` carries any value outside those six, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.11: "1. **Header and role authentication** — `ERR_UNAUTHENTICATED` (401). Applies to every endpoint."

        Design: Corner/errors/request_with_no_role_header_is_unauthenticated
        """
        response = api.get_tank_project(NON_EXISTENT_UUID, headers_without_identity())
        error_id = validate_error(
            response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401
        )["error_id"]
        assert error_id != ApiErrorId.ERR_TANK_PROJECT_NOT_FOUND.value, (
            "authentication precedes existence, so the unresolvable path id in the "
            f"request must never surface, got {error_id}"
        )

    def test_a_technician_filing_a_permit_is_refused_before_the_body_is_read(self, api):
        """PRD §2.1: "If both headers are well formed but the named role does not appear in the authorized-role list for the endpoint being addressed (see §4), the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
        PRD §2.11: "2. **Endpoint role authorization** — `ERR_ROLE_NOT_PERMITTED` (403). Applies to every endpoint."

        Design: Corner/errors/field_technician_filing_a_permit_is_forbidden
        """
        ctx = fx.project_at_surveyed()

        response = api.create_permit(
            {"tank_project_id": ctx["project"]["id"]}, FIELD_TECHNICIAN
        )
        error_id = validate_error(
            response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403
        )["error_id"]
        assert error_id != ApiErrorId.ERR_INVALID_REQUEST.value, (
            "role authorization runs before body validation, so the missing "
            f"permit_type must never be reported, got {error_id}"
        )

        _, meta = validate_paginated(
            api.list_permits(
                PROJECT_COORDINATOR,
                params={"tank_project_id": ctx["project"]["id"]},
            )
        )
        assert meta["total_count"] == 0, (
            f"no permit row was written, got {meta['total_count']}"
        )

    def test_pagination_outside_the_declared_window_is_refused(self, api):
        """PRD §2.3: "Every collection read accepts two optional query parameters. `limit` defaults to 10, may be no smaller than 1, and may be no larger than 100. `offset` defaults to 0 and may be no smaller than 0. A `limit` below 1 or above 100, or a negative `offset`, is rejected with `ERR_INVALID_PAGINATION` (HTTP 422)."
        PRD §2.11: "7. **Pagination bounds** — `ERR_INVALID_PAGINATION` (422). Applies to every list endpoint."

        Design: Corner/errors/pagination_limit_zero_and_negative_offset_are_rejected
        """
        below_the_window = api.list_tank_projects(
            PROJECT_COORDINATOR, params={"limit": 0, "offset": 0}
        )
        validate_error(
            below_the_window, ApiErrorId.ERR_INVALID_PAGINATION.value, 422
        )

        negative_offset = api.list_soil_samples(
            PROJECT_COORDINATOR, params={"limit": 10, "offset": -1}
        )
        validate_error(negative_offset, ApiErrorId.ERR_INVALID_PAGINATION.value, 422)


class TestSchedulingRefusals:
    def test_an_unjustified_divergence_from_the_recommendation_is_refused(self, api):
        """PRD §3.4: "First, when the requested `method` differs from the project's `recommended_method`, the scheduler is overriding a computed regulatory recommendation and must justify it: `method_override_reason` is required in that case, and its absence is refused with `ERR_METHOD_OVERRIDE_REASON_REQUIRED`."
        PRD §2.11: "12. **Referential integrity of optional links and reason fields**, in this internal order: `ERR_SUPERSEDE_TARGET_INVALID` (409), `ERR_RETEST_TARGET_INVALID` (409), then `ERR_METHOD_OVERRIDE_REASON_REQUIRED` (422)."

        Design: Corner/errors/work_order_method_divergence_without_reason_is_rejected
        """
        ctx = fx.project_at_surveyed()
        crew = fx.create_crew(crew_name="Crew No Reason")

        assert ctx["project"]["recommended_method"] == "REMOVAL", (
            "the survey under test must recommend removal, got "
            f"{ctx['project']['recommended_method']}"
        )

        response = api.create_work_order(
            work_order_payload(
                ctx["project"]["id"], crew["id"], method="ABANDONMENT_IN_PLACE"
            ),
            PROJECT_COORDINATOR,
        )
        validate_error(
            response, ApiErrorId.ERR_METHOD_OVERRIDE_REASON_REQUIRED.value, 422
        )

        _, meta = validate_paginated(
            api.list_work_orders(
                PROJECT_COORDINATOR,
                params={"tank_project_id": ctx["project"]["id"]},
            )
        )
        assert meta["total_count"] == 0, (
            f"the refused booking was never written, got {meta['total_count']}"
        )

    def test_a_second_live_booking_on_the_same_project_is_refused(self, api):
        """PRD §3.4: "Second, a project may have at most one live work order: if the project already has a work order whose `field_status` is `SCHEDULED`, `MOBILIZED` or `IN_PROGRESS`, the new booking is refused with `ERR_WORK_ORDER_ALREADY_OPEN`."
        PRD §2.11: "15. **Uniqueness and quota constraints**, in this internal order: `ERR_DUPLICATE_DISCLOSURE` (409), `ERR_WORK_ORDER_ALREADY_OPEN` (409), `ERR_DUPLICATE_FINAL_CLAIM` (409), then `ERR_INFO_REQUEST_LIMIT_REACHED` (409)."

        Design: Corner/errors/second_open_work_order_on_the_same_project_is_rejected
        """
        ctx = fx.project_at_surveyed()
        crew_a = fx.create_crew(crew_name="Crew Already Open A")
        crew_b = fx.create_crew(crew_name="Crew Already Open B")
        first = fx.create_work_order(ctx["project"]["id"], crew_a["id"])

        response = api.create_work_order(
            work_order_payload(
                ctx["project"]["id"],
                crew_b["id"],
                scheduled_start_at="2026-08-20T13:00:00Z",
                scheduled_end_at="2026-08-20T21:00:00Z",
            ),
            PROJECT_COORDINATOR,
        )
        error_id = validate_error(
            response, ApiErrorId.ERR_WORK_ORDER_ALREADY_OPEN.value, 409
        )["error_id"]
        assert error_id != ApiErrorId.ERR_CREW_BOOKING_CONFLICT.value, (
            "the second booking names a different crew, so no calendar collision is "
            f"possible, got {error_id}"
        )

        assert fx.read_work_order(first["id"])["field_status"] == "SCHEDULED", (
            "the standing booking is untouched by the refusal"
        )
        _, meta = validate_paginated(
            api.list_work_orders(
                PROJECT_COORDINATOR,
                params={"tank_project_id": ctx["project"]["id"]},
            )
        )
        assert meta["total_count"] == 1, (
            f"the project still holds exactly one booking, got {meta['total_count']}"
        )


class TestDisclosureRefusals:
    def test_a_second_outstanding_notice_of_the_same_kind_is_refused(self, api):
        """PRD §3.2: "Only one notice of a given kind may be outstanding on a project at a time: attempting to send a second `SWEEP_FINDINGS` notice while an earlier one is still `PENDING` is refused with `ERR_DUPLICATE_DISCLOSURE`."
        PRD §3.2: "The notice is created in `PENDING` with `sent_at` stamped from the logical clock and `expires_at` derived as three days later — the response window is 72 hours."

        Design: Corner/errors/second_pending_sweep_disclosure_is_rejected
        """
        ctx = fx.project_at_surveyed()
        first = fx.create_disclosure(
            ctx["project"]["id"], disclosure_kind="SWEEP_FINDINGS"
        )
        assert parse_instant(first["expires_at"]) == parse_instant(
            "2026-08-06T08:00:00Z"
        ), (
            "72 hours after 2026-08-03T08:00:00Z is 2026-08-06T08:00:00Z, got "
            f"{first['expires_at']}"
        )

        response = api.create_disclosure(
            disclosure_payload(
                ctx["project"]["id"], disclosure_kind="SWEEP_FINDINGS"
            ),
            PROJECT_COORDINATOR,
        )
        validate_error(response, ApiErrorId.ERR_DUPLICATE_DISCLOSURE.value, 409)

        assert fx.read_disclosure(first["id"])["status"] == "PENDING", (
            "the outstanding notice is unchanged by the refusal"
        )
        _, meta = validate_paginated(
            api.list_disclosures(
                PROJECT_COORDINATOR,
                params={"tank_project_id": ctx["project"]["id"]},
            )
        )
        assert meta["total_count"] == 1, (
            f"the project keeps exactly one notice, got {meta['total_count']}"
        )

    def test_a_response_one_second_past_the_window_expires_the_notice(self, api):
        """PRD §3.2: "Expiry is evaluated **first**, at the very start of the response, and it is a write. If the logical clock has passed `expires_at` while the notice was still `PENDING`, the server transitions the notice `PENDING → EXPIRED`, persists that transition, and only then rejects the incoming response with `ERR_DISCLOSURE_EXPIRED`."
        PRD §3.2: "The homeowner who replies one minute late therefore finds their notice permanently expired rather than merely refused, and a fresh notice must be sent."

        Design: Corner/errors/homeowner_response_after_the_disclosure_window_is_rejected
        """
        ctx = fx.project_at_surveyed()
        notice = fx.create_disclosure(
            ctx["project"]["id"], disclosure_kind="SWEEP_FINDINGS"
        )
        assert parse_instant(notice["expires_at"]) == parse_instant(
            "2026-08-06T08:00:00Z"
        ), (
            "the window closes 72 hours after the notice was sent, got "
            f"{notice['expires_at']}"
        )

        fx.set_clock("2026-08-06T08:00:01Z")
        response = api.respond_to_disclosure(
            notice["id"],
            disclosure_response_payload(),
            make_homeowner_headers(ctx["property"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_DISCLOSURE_EXPIRED.value, 409)

        stored = fx.read_disclosure(notice["id"])
        assert stored["status"] == "EXPIRED", (
            "the lapse is persisted before the refusal, got "
            f"{stored['status']}"
        )
        assert stored["responded_at"] is None, (
            f"the late answer is not recorded, got {stored['responded_at']}"
        )
        assert fx.read_project(ctx["project"]["id"])["status"] == "SURVEYED", (
            "the project never passed the disclosure gate"
        )


class TestClosureRefusals:
    #: The first draft is needed for a closing that the clock will later pass.
    EARLY_CLOSING_DATE = "2026-08-10T00:00:00Z"
    AFTER_THE_CLOSING = "2026-08-11T00:00:00Z"
    LATER_CLOSING_DATE = "2026-09-15T00:00:00Z"

    def test_three_issuance_attempts_isolate_three_different_closure_gates(self, api):
        """PRD §3.9: "Issuance is a **second** `LicensedSiteProfessional`'s act, and it carries five preconditions: the letter must be in `DRAFT`; the project must be in `CLEARED`; the project's `nfa_blockers` must be empty, failing which the attempt is refused with `ERR_NFA_BLOCKED`; the acting `X-User-ID` must differ from `drafted_by_user_id`, failing which the attempt is refused with `ERR_SEGREGATION_OF_DUTIES`; and the letter's `closing_date` must be at or after the current logical instant, failing which the attempt is refused with `ERR_CLOSING_DATE_IN_PAST` — a letter cannot be issued for a closing that has already happened."
        PRD §3.3: "The permit transitions `ISSUED → REVOKED`, the reason is stored, and two cascades fire."
        PRD §3.9: "`PERMIT_REVOKED` is present whenever the project has at least one `MUNICIPAL_DECOMMISSION` permit whose `status` is `REVOKED` or `EXPIRED`."

        Design: Corner/errors/nfa_issuance_rejected_for_same_signer_then_stale_closing_date_then_blockers
        """
        ctx = fx.project_cleared()
        assert ctx["project"]["nfa_blockers"] == [], (
            "the project must start with nothing standing in the way, got "
            f"{ctx['project']['nfa_blockers']}"
        )
        first_letter = fx.draft_nfa_letter(
            ctx["project"]["id"], closing_date=self.EARLY_CLOSING_DATE
        )

        same_signer = api.issue_nfa_letter(first_letter["id"], LSP_DRAFTER)
        validate_error(
            same_signer, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403
        )

        fx.set_clock(self.AFTER_THE_CLOSING)
        stale_closing = api.issue_nfa_letter(first_letter["id"], LSP_SIGNER)
        validate_error(stale_closing, ApiErrorId.ERR_CLOSING_DATE_IN_PAST.value, 422)

        fx.decide_permit(
            ctx["municipal_permit"]["id"],
            "REVOKED",
            revocation_reason="municipal audit reopened the decommissioning file",
        )
        second_letter = fx.draft_nfa_letter(
            ctx["project"]["id"], closing_date=self.LATER_CLOSING_DATE
        )
        blocked = api.issue_nfa_letter(second_letter["id"], LSP_SIGNER)
        validate_error(blocked, ApiErrorId.ERR_NFA_BLOCKED.value, 409)

        project = fx.read_project(ctx["project"]["id"])
        assert project["nfa_blockers"] == ["PERMIT_REVOKED"], (
            f"the revocation is the only obstacle, got {project['nfa_blockers']}"
        )
        assert project["status"] == "CLEARED", (
            f"no refused issuance moves the project, got {project['status']}"
        )
        assert fx.read_nfa_letter(first_letter["id"])["status"] == "DRAFT", (
            "the first draft was never signed"
        )
        assert fx.read_nfa_letter(second_letter["id"])["status"] == "DRAFT", (
            "the second draft was never signed either"
        )
        assert fx.read_permit(ctx["municipal_permit"]["id"])["status"] == "REVOKED", (
            "the stop-work order stands"
        )


class TestSamplingRefusals:
    def test_a_retest_pointing_at_a_merely_resulted_aliquot_is_refused(self, api):
        """PRD §3.6: "Supplying `retest_of_sample_id` declares that this aliquot re-tests an earlier one that was thrown out; the named row must belong to the same project and must be in `INVALIDATED`, and any other target is refused with `ERR_RETEST_TARGET_INVALID`."
        PRD §3.6: "A retest that lands a good result is what clears the invalidated-sample blocker described in §3.9."

        Design: Corner/errors/retest_pointing_at_a_resulted_sample_is_rejected
        """
        ctx = fx.project_at_sampling()
        first = fx.collect_sample_at_lab(
            ctx, sample_point="CONFIRMATION_FLOOR", depth_inches=84
        )
        fx.collect_sample_at_lab(ctx, sample_point="NORTH_SIDEWALL", depth_inches=72)

        resulted = fx.report_result(first["id"], ctx["laboratory"]["id"], 120.0, 0.05)
        assert resulted["status"] == "RESULTED", (
            f"the target row must be merely resulted, got {resulted['status']}"
        )

        response = api.create_soil_sample(
            soil_sample_payload(
                ctx["project"]["id"],
                ctx["work_order"]["id"],
                ctx["laboratory"]["id"],
                sample_point="SOUTH_SIDEWALL",
                depth_inches=84,
                retest_of_sample_id=first["id"],
            ),
            FIELD_TECHNICIAN,
        )
        validate_error(response, ApiErrorId.ERR_RETEST_TARGET_INVALID.value, 409)

        assert fx.read_project(ctx["project"]["id"])["status"] == "SAMPLING", (
            "the second aliquot is still pending, so no state gate can mask the rule"
        )
        _, meta = validate_paginated(
            api.list_soil_samples(
                FIELD_TECHNICIAN,
                params={"tank_project_id": ctx["project"]["id"]},
            )
        )
        assert meta["total_count"] == 2, (
            f"the refused retest was never written, got {meta['total_count']}"
        )


class TestPermitLapseRefusals:
    #: The municipal permit is issued here, so it lapses 180 days later.
    MUNICIPAL_EXPIRY = "2027-01-30T08:00:00Z"
    FIRE_NOTICE_FILED_AT = "2026-09-01T08:00:00Z"
    ARRIVAL_INSTANT = "2027-02-01T08:00:00Z"

    def test_mobilizing_after_the_permit_lapses_yields_two_different_codes(self, api):
        """PRD §3.4: "And it requires the project's `MUNICIPAL_DECOMMISSION` permit to be in `ISSUED`, failing which the refusal is `ERR_PERMIT_NOT_ISSUED`, and to be unexpired, failing which the permit is first flipped to `EXPIRED` as described in §3.3 and the refusal is `ERR_PERMIT_EXPIRED`."
        PRD §3.3: "If the project's `MUNICIPAL_DECOMMISSION` permit is `ISSUED` but the logical clock has passed its `expires_at`, the server writes the transition `ISSUED → EXPIRED` and persists it, then rejects the mobilization with `ERR_PERMIT_EXPIRED`."
        PRD §3.3: "On success the permit transitions `SUBMITTED → ISSUED`, `issued_at` is stamped from the logical clock, and `expires_at` is derived as exactly 180 days after issuance, after which the permit lapses."

        Design: Corner/errors/mobilize_after_municipal_permit_expiry_is_rejected_twice_with_different_codes
        """
        ctx = fx.project_at_disclosed()
        municipal = fx.create_permit(
            ctx["project"]["id"], "MUNICIPAL_DECOMMISSION"
        )
        municipal = fx.decide_permit(municipal["id"], "ISSUED")
        assert parse_instant(municipal["expires_at"]) == parse_instant(
            self.MUNICIPAL_EXPIRY
        ), (
            "180 days after 2026-08-03T08:00:00Z is 2027-01-30T08:00:00Z, got "
            f"{municipal['expires_at']}"
        )

        crew = fx.create_crew(crew_name="Crew Permit Lapse")
        work_order = fx.create_work_order(
            ctx["project"]["id"],
            crew["id"],
            scheduled_start_at="2027-02-01T13:00:00Z",
            scheduled_end_at="2027-02-01T21:00:00Z",
        )

        fx.set_clock(self.FIRE_NOTICE_FILED_AT)
        fire_notice = fx.create_permit(
            ctx["project"]["id"], "FIRE_MARSHAL_NOTIFICATION"
        )
        fire_notice = fx.decide_permit(fire_notice["id"], "ISSUED")
        assert parse_instant(fire_notice["notice_effective_at"]) == parse_instant(
            "2026-09-03T08:00:00Z"
        ), (
            "48 hours after issuance is 2026-09-03T08:00:00Z, got "
            f"{fire_notice['notice_effective_at']}"
        )
        assert parse_instant(fire_notice["expires_at"]) == parse_instant(
            "2027-02-28T08:00:00Z"
        ), (
            "180 days after issuance is 2027-02-28T08:00:00Z, got "
            f"{fire_notice['expires_at']}"
        )

        fx.set_clock(self.ARRIVAL_INSTANT)
        lapsed = api.create_field_event(
            work_order["id"], field_event_payload("MOBILIZE"), FIELD_TECHNICIAN
        )
        validate_error(lapsed, ApiErrorId.ERR_PERMIT_EXPIRED.value, 409)

        retry = api.create_field_event(
            work_order["id"], field_event_payload("MOBILIZE"), FIELD_TECHNICIAN
        )
        validate_error(retry, ApiErrorId.ERR_PERMIT_NOT_ISSUED.value, 409)

        assert fx.read_permit(municipal["id"])["status"] == "EXPIRED", (
            "the lapse is written before the first refusal, which is what changes the "
            "code the retry sees"
        )
        assert fx.read_permit(fire_notice["id"])["status"] == "ISSUED", (
            "the fire-marshal notice is still in force"
        )
        assert fx.read_work_order(work_order["id"])["field_status"] == "SCHEDULED", (
            "the crew never lawfully arrived"
        )
        assert fx.read_project(ctx["project"]["id"])["status"] == "PERMITTED", (
            "the project waits where the municipal issuance left it"
        )


class TestFiscalCeilingRefusals:
    def test_a_supersede_target_that_was_rejected_and_an_over_ceiling_approval_are_refused(
        self, api
    ):
        """PRD §3.7: "A change order may also carry `supersedes_change_order_id`, naming an already-approved change order on the same project that this one replaces; a target on another project, or one whose `status` is anything other than `APPROVED`, is refused with `ERR_SUPERSEDE_TARGET_INVALID`."
        PRD §3.7: "The ceiling test is computed prospectively: take the project's `baseline_scope_cubic_yards`, add the `additional_cubic_yards` of every change order that would be in `APPROVED` status once this approval and any supersession it triggers have been applied, and require the total to be at or below the project's `excavation_limit_cubic_yards`. A total exceeding the ceiling is refused with `ERR_EXCAVATION_LIMIT_EXCEEDED`; a total landing exactly on it is permitted."
        PRD §2.11: "14. **Fiscal ceilings**, in this internal order: `ERR_EXCAVATION_LIMIT_EXCEEDED` (409), then `ERR_CLAIM_NOT_ELIGIBLE` (409)."

        Design: Corner/errors/supersede_of_a_rejected_row_then_over_limit_approval_are_rejected
        """
        ctx = fx.project_remediation_active_gross()
        assert ctx["project"]["contamination_class"] == "GROSS", (
            f"the project under test must be scoping remediation, got "
            f"{ctx['project']['contamination_class']}"
        )
        assert ctx["project"]["remediation_started"] is True, (
            "the remediation latch must be set"
        )

        rejected = fx.submitted_change_order(ctx, 3.0, 1000)
        fx.decide_change_order(
            rejected["id"],
            "REJECTED",
            decision_note="scope not substantiated by the sidewall grid",
        )

        version = fx.project_version(ctx["project"]["id"])
        bad_supersede = api.create_change_order(
            change_order_payload(
                ctx["project"]["id"],
                version,
                additional_cubic_yards=2.0,
                unit_rate_cents=1000,
                supersedes_change_order_id=rejected["id"],
            ),
            LSP_DRAFTER,
        )
        validate_error(
            bad_supersede, ApiErrorId.ERR_SUPERSEDE_TARGET_INVALID.value, 409
        )

        over_ceiling = fx.submitted_change_order(ctx, 50.0, 1000, expected_project_version=version)
        decision = api.decide_change_order(
            over_ceiling["id"], change_order_decision_payload("APPROVED"), COMPLIANCE_OFFICER
        )
        validate_error(
            decision, ApiErrorId.ERR_EXCAVATION_LIMIT_EXCEEDED.value, 409
        )

        assert fx.read_change_order(rejected["id"])["status"] == "REJECTED", (
            "the rejected row is terminal and unchanged"
        )
        stored = fx.read_change_order(over_ceiling["id"])
        assert stored["status"] == "SUBMITTED", (
            f"a refused approval leaves the row awaiting a decision, got {stored['status']}"
        )
        assert stored["line_amount_cents"] is None, (
            "the line amount is computed only on a successful approval, got "
            f"{stored['line_amount_cents']}"
        )

        project = fx.read_project(ctx["project"]["id"])
        assert project["approved_scope_cubic_yards"] == pytest.approx(8.0, abs=0.01), (
            "the scope stays at the baseline, got "
            f"{project['approved_scope_cubic_yards']}"
        )
        assert project["remediation_cost_cents"] == 185000, (
            "with no approved line the cost is the bare mobilization charge, got "
            f"{project['remediation_cost_cents']}"
        )


class TestClaimRefusals:
    #: Gross costs below the New Jersey deductible, so nothing is reimbursable.
    UNDER_THE_DEDUCTIBLE = 40000
    FINAL_CLAIM_CENTS = 900000
    SECOND_FINAL_CLAIM_CENTS = 500000

    def test_a_zero_value_claim_and_then_a_second_close_out_claim_are_refused(
        self, api
    ):
        """PRD §3.9: "Under `PRELIMINARY_ESTIMATE`, the cap is applied to the gross figure first and the deductible is then subtracted from the already-capped figure: take the capped figure less `deductible_cents`, floor that difference at zero, and subtract `admin_fee_cents`."
        PRD §3.9: "A project may hold at most one `FINAL_SETTLEMENT` claim whose `status` is neither `DENIED` nor `WITHDRAWN`; a second is refused with `ERR_DUPLICATE_FINAL_CLAIM`."
        PRD §3.9: "Every `PRELIMINARY_ESTIMATE` claim on the same project whose `status` is `DRAFT`, `SUBMITTED`, `UNDER_REVIEW` or `INFO_REQUESTED` is transitioned to `WITHDRAWN`, and the code `SUPERSEDED_BY_FINAL_SETTLEMENT` is appended to that claim's `eligibility_findings`."

        Design: Corner/errors/zero_eligibility_submission_then_second_final_claim_are_rejected
        """
        ctx = fx.project_cleared()
        assert ctx["project"]["status"] == "CLEARED", (
            f"the project state gate must be satisfied, got {ctx['project']['status']}"
        )

        interim = fx.create_claim(
            ctx["project"]["id"], claimed_costs_cents=self.UNDER_THE_DEDUCTIBLE
        )
        assert interim["deductible_cents"] == 50000, (
            f"New Jersey's deductible is 50,000 cents, got {interim['deductible_cents']}"
        )
        assert interim["admin_fee_cents"] == 1400, (
            "three and a half percent of 40,000 cents is 1400, got "
            f"{interim['admin_fee_cents']}"
        )
        assert interim["eligible_amount_cents"] == 0, (
            "40,000 capped, less the 50,000 deductible, floors at zero, got "
            f"{interim['eligible_amount_cents']}"
        )

        not_eligible = api.submit_trust_fund_claim(interim["id"], COMPLIANCE_OFFICER)
        validate_error(not_eligible, ApiErrorId.ERR_CLAIM_NOT_ELIGIBLE.value, 409)

        final = validate_success(
            api.create_trust_fund_claim(
                trust_fund_claim_payload(
                    ctx["project"]["id"],
                    fx.project_version(ctx["project"]["id"]),
                    variant="FINAL_SETTLEMENT",
                    claimed_costs_cents=self.FINAL_CLAIM_CENTS,
                ),
                COMPLIANCE_OFFICER,
            ),
            201,
        )
        assert final["eligible_amount_cents"] == 818500, (
            "900,000 less the 50,000 deductible, capped at 4,000,000, less the "
            f"31,500 fee is 818,500, got {final['eligible_amount_cents']}"
        )
        assert fx.read_claim(interim["id"])["status"] == "WITHDRAWN", (
            "the close-out application withdraws the interim row"
        )

        duplicate = api.create_trust_fund_claim(
            trust_fund_claim_payload(
                ctx["project"]["id"],
                fx.project_version(ctx["project"]["id"]),
                variant="FINAL_SETTLEMENT",
                claimed_costs_cents=self.SECOND_FINAL_CLAIM_CENTS,
            ),
            COMPLIANCE_OFFICER,
        )
        validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_FINAL_CLAIM.value, 409)

        assert fx.read_claim(final["id"])["status"] == "DRAFT", (
            "the standing close-out application is untouched by the refusal"
        )
