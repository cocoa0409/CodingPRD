"""Access plan (exception) requests: resubmit cycle, decide gates, excuse windows (PRD §3.8)."""
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_access_plan_request_payload, create_evaluation_payload,
    set_clock, create_evaluation, finalize_evaluation, get_deficiency,
    get_evaluation, create_request_for_deficiency, submit_request, decide_request,
    setup_open_deficiency, create_provider, create_location, create_listing,
    publish_listing,
)

NM = TEST_USERS["network_manager_headers"]
REG = TEST_USERS["regulator_headers"]


class TestAccessPlanDeniedResubmitCycle:
    def _setup(self):
        ctx = setup_open_deficiency(county_fips="06013", measurement_period="E1")
        set_clock("2026-06-15T00:00:00Z")
        req = create_request_for_deficiency(
            ctx["deficiency"], remedy_summary="Contract two dermatologists")
        return ctx, req

    def test_denied_request_resubmits_through_the_cycle(self, api):
        """PRD §3.8: "A request in `DRAFT` or `DENIED` may be submitted to the
        regulator; submission from any other status is rejected with
        `ERR_REQUEST_NOT_SUBMITTABLE`. A resubmission from `DENIED` resets `decided_at`
        to null and increments `version`."
        PRD §3.8: "A `decision` of `DENIED` simply stamps `decided_at` and increments
        `version`; the request may later be resubmitted."

        Design: Difficulty/non_linear_state_machine/access_plan_denied_resubmit_cycle
        """
        _ctx, req = self._setup()
        st1 = submit_request(req["id"])
        assert st1["status"] == "SUBMITTED"
        denied = decide_request(req["id"], "DENIED", notes="insufficient remedy detail")
        assert denied["status"] == "DENIED"
        assert denied["decided_at"] is not None
        resubmitted = submit_request(req["id"])
        assert resubmitted["status"] == "SUBMITTED", "DENIED -> SUBMITTED cycle traversed"
        assert resubmitted["decided_at"] is None, "resubmission resets decided_at to null"
        assert resubmitted["version"] == denied["version"] + 1

    def test_approval_after_resubmit_excuses_deficiency(self, api):
        """PRD §3.8: "The deficiency transitions from `OPEN` to `EXCUSED`. Its
        outstanding penalty is reversed: `reversed_penalty_cents` increases by the prior
        outstanding amount, driving `outstanding_penalty_cents` to zero, and the
        deficiency's `version` increments."

        Design: Difficulty/non_linear_state_machine/access_plan_denied_resubmit_cycle
        """
        ctx, req = self._setup()
        submit_request(req["id"])
        decide_request(req["id"], "DENIED", notes="insufficient remedy detail")
        submit_request(req["id"])
        approved = decide_request(req["id"], "APPROVED", notes="revised plan accepted")
        assert approved["status"] == "APPROVED"
        deficiency = get_deficiency(ctx["deficiency"]["id"])
        assert deficiency["status"] == "EXCUSED"
        assert deficiency["outstanding_penalty_cents"] == 0


class TestDecideRequiresDeficiencyOpen:
    def _setup_closed_deficiency_with_submitted_request(self):
        ctx = setup_open_deficiency(county_fips="06035", measurement_period="E1")
        req = create_request_for_deficiency(ctx["deficiency"], remedy_summary="recruiting plan")
        submit_request(req["id"])
        provider = create_provider(legal_name="Derm 27", specialty="DERMATOLOGY")
        location = create_location(provider["id"], ctx["region"]["id"],
                                   address_line="27 Palm Ave", avg_travel_minutes=20,
                                   avg_travel_miles=10)
        publish_listing(create_listing(provider["id"], location["id"],
                                       specialty="DERMATOLOGY", display_name="Derm 27",
                                       phone="555-0127")["id"])
        ev2 = create_evaluation(measurement_period="E2", period_start_date="2026-06-12",
                                period_end_date="2026-06-21")
        finalize_evaluation(ev2["id"])
        return ctx, req

    def test_compliant_finalize_closes_the_deficiency(self, api):
        """PRD §3.7: "A sibling branch handles the compliant side: each pair that came
        out `COMPLIANT` and has an existing `OPEN` or `EXCUSED` deficiency has that
        deficiency transitioned to `CLOSED` with `closed_date` set to `period_end_date`
        and `version` incremented."

        Design: Difficulty/cross_entity_state_dependency/decide_requires_deficiency_open
        """
        ctx, _req = self._setup_closed_deficiency_with_submitted_request()
        deficiency = get_deficiency(ctx["deficiency"]["id"])
        assert deficiency["status"] == "CLOSED"
        assert deficiency["closed_date"] == "2026-06-21"

    def test_decide_on_closed_deficiency_rejected(self, api):
        """PRD §3.8: "A `decision` of `APPROVED` enforces two additional preconditions:
        the parent deficiency must currently be `OPEN` (else `ERR_DEFICIENCY_NOT_OPEN`),
        and the requested excuse window — interpreted as a closed interval, so touching
        endpoints count as overlap — must not overlap any other `APPROVED` request's
        window for the same deficiency (else `ERR_EXCUSE_WINDOW_OVERLAP`)."

        Design: Difficulty/cross_entity_state_dependency/decide_requires_deficiency_open
        """
        ctx, req = self._setup_closed_deficiency_with_submitted_request()
        resp = api.decide_access_plan_request(req["id"], {"decision": "APPROVED"}, REG)
        validate_error(resp, ApiErrorId.ERR_DEFICIENCY_NOT_OPEN)


class TestExcuseWindowClosedInterval:
    def _setup_reopened_with_approved_window(self):
        """D OPEN (accrual 149985); R1 [07-01, 07-31] approved -> EXCUSED; E2
        (06-12..08-15) reopens D because the excuse lapses before period end."""
        ctx = setup_open_deficiency(county_fips="06037", measurement_period="E1")
        set_clock("2026-06-15T00:00:00Z")
        r1 = create_request_for_deficiency(
            ctx["deficiency"], remedy_summary="locum tenens",
            excuse_start_date="2026-07-01", excuse_through_date="2026-07-31")
        submit_request(r1["id"])
        decide_request(r1["id"], "APPROVED")
        ev2 = create_evaluation(measurement_period="E2", period_start_date="2026-06-12",
                                period_end_date="2026-08-15")
        finalize_evaluation(ev2["id"])
        return ctx, r1, ev2

    def test_reopen_accrues_the_uncovered_tail(self, api):
        """PRD §3.7: "If an `EXCUSED` one exists whose `excuse_through_date` falls
        before `period_end_date`, the excuse has lapsed and the record reopens —
        `EXCUSED` → `OPEN` — with the new accrual window running from the later of
        `period_start_date` and `excuse_through_date` through `period_end_date`."
        PRD §3.7: "The accrual window's length in whole calendar days is the difference
        between `accrual_window_end` and `accrual_window_start`."

        Design: Difficulty/resource_temporal_overlap/access_plan_excuse_closed_interval_touching_overlaps
        """
        ctx, _r1, _ev2 = self._setup_reopened_with_approved_window()
        deficiency = get_deficiency(ctx["deficiency"]["id"])
        assert deficiency["status"] == "OPEN", "excuse lapsed before period end -> reopen"
        # tail window max(06-12, 07-31) .. 08-15 = 15 days; 9999 * 15 * 1.5 = 224977.5
        assert deficiency["last_accrual_cents"] == 224978
        assert deficiency["outstanding_penalty_cents"] == 224978

    def test_touching_window_overlaps_but_gap_approves(self, api):
        """PRD §3.8: "A `decision` of `APPROVED` enforces two additional preconditions:
        the parent deficiency must currently be `OPEN` (else `ERR_DEFICIENCY_NOT_OPEN`),
        and the requested excuse window — interpreted as a closed interval, so touching
        endpoints count as overlap — must not overlap any other `APPROVED` request's
        window for the same deficiency (else `ERR_EXCUSE_WINDOW_OVERLAP`)."

        Design: Difficulty/resource_temporal_overlap/access_plan_excuse_closed_interval_touching_overlaps
        """
        ctx, _r1, _ev2 = self._setup_reopened_with_approved_window()
        deficiency = get_deficiency(ctx["deficiency"]["id"])
        r2 = validate_success(api.create_access_plan_request(
            deficiency["id"],
            create_access_plan_request_payload(
                deficiency["version"], remedy_summary="extension touching prior window",
                excuse_start_date="2026-07-31", excuse_through_date="2026-08-31"), NM),
            expected_status=201)
        submit_request(r2["id"])
        overlap = api.decide_access_plan_request(r2["id"], {"decision": "APPROVED"}, REG)
        validate_error(overlap, ApiErrorId.ERR_EXCUSE_WINDOW_OVERLAP)
        deficiency = get_deficiency(deficiency["id"])
        r3 = validate_success(api.create_access_plan_request(
            deficiency["id"],
            create_access_plan_request_payload(
                deficiency["version"], remedy_summary="clean extension",
                excuse_start_date="2026-08-01", excuse_through_date="2026-08-31"), NM),
            expected_status=201)
        submit_request(r3["id"])
        approved = validate_success(api.decide_access_plan_request(
            r3["id"], {"decision": "APPROVED"}, REG))
        assert approved["status"] == "APPROVED", "08-01 > 07-31 leaves no shared day"


class TestApprovalConservesPenalty:
    def _setup(self):
        ctx = setup_open_deficiency(county_fips="06041", measurement_period="E1")
        set_clock("2026-06-15T00:00:00Z")
        req = create_request_for_deficiency(
            ctx["deficiency"], remedy_summary="full coverage plan",
            excuse_start_date="2026-06-15", excuse_through_date="2026-08-31")
        return ctx, req

    def test_approval_reverses_exactly_the_outstanding_amount(self, api):
        """PRD §3.7: "The invariant `outstanding_penalty_cents` equals
        `accrued_penalty_cents` minus `reversed_penalty_cents` holds at all times."
        PRD §3.8: "Its outstanding penalty is reversed: `reversed_penalty_cents`
        increases by the prior outstanding amount, driving `outstanding_penalty_cents`
        to zero, and the deficiency's `version` increments."

        Design: Difficulty/compensating_invariant/access_plan_approval_conserves_penalty_outstanding
        """
        ctx, req = self._setup()
        before = get_deficiency(ctx["deficiency"]["id"])
        assert before["accrued_penalty_cents"] == 149985
        assert before["outstanding_penalty_cents"] == 149985
        submit_request(req["id"])
        decide_request(req["id"], "APPROVED")
        after = get_deficiency(ctx["deficiency"]["id"])
        assert after["status"] == "EXCUSED"
        assert after["accrued_penalty_cents"] == 149985, "accrued is unchanged by approval"
        assert after["reversed_penalty_cents"] == 149985
        assert after["outstanding_penalty_cents"] == 0
        assert (after["outstanding_penalty_cents"]
                == after["accrued_penalty_cents"] - after["reversed_penalty_cents"]), (
            "outstanding == accrued - reversed after approval")

    def test_evaluation_rollup_decremented_by_reversed_amount(self, api):
        """PRD §3.8: "The owning evaluation's `total_penalty_cents` is decremented by
        the same reversed amount."

        Design: Difficulty/compensating_invariant/access_plan_approval_conserves_penalty_outstanding
        """
        ctx, req = self._setup()
        assert get_evaluation(ctx["evaluation"]["id"])["total_penalty_cents"] == 149985
        submit_request(req["id"])
        decide_request(req["id"], "APPROVED")
        after = get_evaluation(ctx["evaluation"]["id"])
        assert after["total_penalty_cents"] == 0, "149985 reversed -> rollup 149985 -> 0"


class TestAccessPlanStateErrors:
    def test_access_plan_submit_and_decide_state_errors(self, api):
        """PRD §3.8: "A `Regulator` decides a `SUBMITTED` request (else
        `ERR_REQUEST_NOT_DECIDABLE`)."
        PRD §3.8: "A request in `DRAFT` or `DENIED` may be submitted to the regulator;
        submission from any other status is rejected with
        `ERR_REQUEST_NOT_SUBMITTABLE`."

        Design: Corner/errors/access_plan_submit_and_decide_state_errors
        """
        ctx = setup_open_deficiency(county_fips="06091", measurement_period="E1")
        req = create_request_for_deficiency(ctx["deficiency"], remedy_summary="plan")
        decide_draft = api.decide_access_plan_request(req["id"], {"decision": "APPROVED"}, REG)
        validate_error(decide_draft, ApiErrorId.ERR_REQUEST_NOT_DECIDABLE)
        submit_request(req["id"])
        double_submit = api.submit_access_plan_request(req["id"], NM)
        validate_error(double_submit, ApiErrorId.ERR_REQUEST_NOT_SUBMITTABLE)

    def test_excuse_window_invalid_order_rejected(self, api):
        """PRD §3.8: "The window's end must be on or after its start, and the start must
        not be before the current clock date; violations yield
        `ERR_EXCUSE_WINDOW_INVALID`."

        Design: Corner/errors/excuse_window_invalid_order_rejected
        """
        ctx = setup_open_deficiency(county_fips="06093", measurement_period="E1")
        deficiency = get_deficiency(ctx["deficiency"]["id"])
        resp = api.create_access_plan_request(
            deficiency["id"],
            create_access_plan_request_payload(
                deficiency["version"], remedy_summary="bad window",
                excuse_start_date="2026-07-31", excuse_through_date="2026-07-01"), NM)
        validate_error(resp, ApiErrorId.ERR_EXCUSE_WINDOW_INVALID)

    def test_occ_stale_deficiency_version_and_supersede(self, api):
        """PRD §2.6: "A request to create an `AccessPlanRequest` on a `DeficiencyRecord`
        must carry `expected_deficiency_version` matching the deficiency's current
        `version`; mismatch yields `ERR_STALE_DEFICIENCY_VERSION` (HTTP 412)."
        PRD §3.8: "When a new request is created on a deficiency that already has a
        `DRAFT` request, the older draft transitions to `SUPERSEDED` (its `version`
        incrementing) and the new request receives `submission_seq` equal to one more
        than the maximum `submission_seq` over the deficiency's existing requests — the
        first request on a deficiency gets `submission_seq` 1."

        Design: Corner/complexity_layers/occ_stale_deficiency_version_and_supersede
        """
        ctx = setup_open_deficiency(county_fips="06123", measurement_period="E1")
        deficiency = get_deficiency(ctx["deficiency"]["id"])
        r1 = validate_success(api.create_access_plan_request(
            deficiency["id"],
            create_access_plan_request_payload(deficiency["version"], remedy_summary="R1"),
            NM), expected_status=201)
        assert r1["submission_seq"] == 1
        stale = api.create_access_plan_request(
            deficiency["id"],
            create_access_plan_request_payload(
                deficiency["version"], remedy_summary="R2 stale",
                excuse_start_date="2026-08-01", excuse_through_date="2026-08-31"), NM)
        validate_error(stale, ApiErrorId.ERR_STALE_DEFICIENCY_VERSION)
        fresh = get_deficiency(deficiency["id"])
        r2 = validate_success(api.create_access_plan_request(
            deficiency["id"],
            create_access_plan_request_payload(
                fresh["version"], remedy_summary="R2 fresh",
                excuse_start_date="2026-08-01", excuse_through_date="2026-08-31"), NM),
            expected_status=201)
        assert r2["submission_seq"] == 2
        r1_after = validate_success(api.get_access_plan_request(r1["id"], NM))
        assert r1_after["status"] == "SUPERSEDED"

    def test_networkmanager_cannot_decide_access_plan_forbidden(self, api):
        """PRD §2.1: "A request whose role is not listed on the endpoint's
        authorized-role set is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: "POST /network/access-plan-requests/{id}/decide — Regulator decision
        (approve or deny) — Regulator".

        Design: Corner/rbac/networkmanager_cannot_decide_access_plan_forbidden
        """
        ctx = setup_open_deficiency(county_fips="06109", measurement_period="E1")
        req = create_request_for_deficiency(ctx["deficiency"], remedy_summary="plan")
        submit_request(req["id"])
        resp = api.decide_access_plan_request(req["id"], {"decision": "APPROVED"}, NM)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
