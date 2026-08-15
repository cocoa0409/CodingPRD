"""Moonlighting requests: headroom check with pinned evaluation order, the
standing gate at approval, half-open interval overlap, clock-driven
transitions, prorated weekly attribution, and the invalid-transition matrix
(PRD §3.6)."""
from test_helpers import (
    PD, ApiClient, ApiErrorId, approx2, assert_duty_summary,
    complete_remediation_plan, create_moonlighting_payload, make_moonlighting,
    make_remediation_plan, make_rolling_window_logs, resident_headers,
    set_clock, setup_program_with_active_resident, validate_error,
    validate_success,
)


def _request(api, req_id):
    return validate_success(api.get_moonlighting(req_id, PD))


class TestHeadroomEvaluationOrder:
    def _setup(self, api):
        """Resident with 16 ATTESTED 19.75h logs, 4 per ISO week over
        2026-08-03..2026-08-28 (total 316.00h; rolling projected base 79.00);
        clock pinned at 2026-08-28 (window = weeks of Aug 3..Aug 24)."""
        s = setup_program_with_active_resident(approved_positions=4)
        resident = s["resident"]
        set_clock("2026-08-28T12:00:00Z")
        make_rolling_window_logs(resident, hours=19.75)
        return s, resident

    def test_first_request_approved_at_exactly_80(self, api: ApiClient):
        """PRD §3.6: "first, compute the resident's rolling projected average
        (the projected variant of §3.5, which counts `SUBMITTED` logs and
        attributes hours from requests in `APPROVED`, `ACTIVE`, or `COMPLETED`)
        over the four ISO weeks ending with the current clock week, excluding
        the candidate request itself; second, add the candidate's
        `hours_per_week` to that base exactly once; third, approve only if the
        resulting decision value is less than or equal to 80.00 — equality
        passes, anything greater is rejected."

        Design: Difficulty/combinatorial_formula/moonlighting_headroom_candidate_evaluation_order
        """
        _, resident = self._setup(api)
        r1 = make_moonlighting(resident, type="INTERNAL", site_name="Metro ICU",
                               start_date="2026-08-17", end_date="2026-09-01",
                               hours_per_week=1.00, submit=True)
        # base 316.00/4 = 79.00 + candidate 1.00 == 80.00 <= 80.00: passes.
        approved = validate_success(api.approve_moonlighting(r1["id"], PD))
        assert approved["status"] == "APPROVED"

    def test_second_request_fails_because_first_feeds_the_base(self, api: ApiClient):
        """PRD §3.6: "first, compute the resident's rolling projected average
        (the projected variant of §3.5, which counts `SUBMITTED` logs and
        attributes hours from requests in `APPROVED`, `ACTIVE`, or `COMPLETED`)
        over the four ISO weeks ending with the current clock week, excluding
        the candidate request itself; second, add the candidate's
        `hours_per_week` to that base exactly once".
        PRD §3.5: "Moonlighting attribution adds, for each of the resident's
        moonlighting requests in `APPROVED`, `ACTIVE`, or `COMPLETED` status
        whose half-open date range intersects the week".

        Design: Difficulty/combinatorial_formula/moonlighting_headroom_candidate_evaluation_order
        """
        _, resident = self._setup(api)
        r1 = make_moonlighting(resident, type="INTERNAL", site_name="Metro ICU",
                               start_date="2026-08-17", end_date="2026-09-01",
                               hours_per_week=1.00, submit=True)
        validate_success(api.approve_moonlighting(r1["id"], PD))
        # R1 now feeds the base: (316 + 1.00 + 1.00)/4 = 79.50.
        summary = validate_success(
            api.get_duty_hour_summary(resident["id"], "2026-08-24", PD))
        assert_duty_summary(summary, resident["id"])
        assert summary["rolling_4wk_avg_official"] == approx2(79.50)

        r2 = make_moonlighting(resident, start_date="2026-09-01",
                               end_date="2026-10-01", hours_per_week=1.00,
                               submit=True)
        # base 79.50 + candidate 1.00 = 80.50 > 80.00.
        resp = api.approve_moonlighting(r2["id"], PD)
        validate_error(resp, ApiErrorId.ERR_PROJECTED_HOURS_EXCEED_80)
        assert _request(api, r2["id"])["status"] == "SUBMITTED"


class TestApproveRequiresGoodStanding:
    def _setup(self, api):
        s = setup_program_with_active_resident()
        resident = s["resident"]
        req = make_moonlighting(resident, start_date="2026-09-01",
                                end_date="2026-10-01", hours_per_week=4.00,
                                submit=True)
        return resident, req

    def test_standing_change_between_create_and_approve_blocks(self, api: ApiClient):
        """PRD §3.6: "the resident's standing must still be `GOOD_STANDING`
        (`ERR_STANDING_BLOCKS_MOONLIGHTING`) — note that a standing change
        between creation and approval is caught here" and "Requests merely
        `SUBMITTED` are left `SUBMITTED` by the sweep — but they can no longer
        be approved, because the standing gate at approval blocks them."

        Design: Difficulty/cross_entity_state_dependency/moonlighting_approve_requires_good_standing
        """
        resident, req = self._setup(api)
        make_remediation_plan(resident["id"], goals="Professionalism coaching")

        resp = api.approve_moonlighting(req["id"], PD)
        validate_error(resp, ApiErrorId.ERR_STANDING_BLOCKS_MOONLIGHTING)
        assert resp.status_code == 403
        assert _request(api, req["id"])["status"] == "SUBMITTED"

    def test_approve_succeeds_after_standing_restored(self, api: ApiClient):
        """PRD §3.6: "Approval re-runs the gates in pipeline order: the request
        must be `SUBMITTED` (`ERR_MOONLIGHTING_NOT_APPROVABLE`, HTTP 409); the
        resident's standing must still be `GOOD_STANDING`
        (`ERR_STANDING_BLOCKS_MOONLIGHTING`)".

        Design: Difficulty/cross_entity_state_dependency/moonlighting_approve_requires_good_standing
        """
        resident, req = self._setup(api)
        plan = make_remediation_plan(resident["id"],
                                     goals="Professionalism coaching")
        complete_remediation_plan(plan["id"], "SUCCESS")
        assert validate_success(api.get_resident(resident["id"], PD))[
            "standing_status"] == "GOOD_STANDING"
        approved = validate_success(api.approve_moonlighting(req["id"], PD))
        assert approved["status"] == "APPROVED"


class TestHalfOpenOverlap:
    def _setup(self, api):
        s = setup_program_with_active_resident()
        resident = s["resident"]
        make_moonlighting(resident, start_date="2026-09-01",
                          end_date="2026-10-01", hours_per_week=3.00,
                          site_name="Clinic A", approve=True)
        return resident

    def test_partially_overlapping_request_rejected(self, api: ApiClient):
        """PRD §3.6: "The range must not overlap any other request of the same
        resident in `SUBMITTED`, `APPROVED`, or `ACTIVE` status
        (`ERR_MOONLIGHTING_OVERLAP`, HTTP 409)".

        Design: Difficulty/resource_temporal_overlap/moonlighting_half_open_interval_overlap
        """
        resident = self._setup(api)
        resp = api.create_moonlighting(
            create_moonlighting_payload(resident["id"], site_name="Clinic B",
                                        start_date="2026-09-15",
                                        end_date="2026-11-01",
                                        hours_per_week=2.00),
            resident_headers(resident))
        validate_error(resp, ApiErrorId.ERR_MOONLIGHTING_OVERLAP)
        assert resp.status_code == 409

    def test_adjacent_request_is_not_an_overlap(self, api: ApiClient):
        """PRD §3.6: "because ranges are half-open, an existing request whose
        `end_date` equals the new request's `start_date` (or vice versa) is
        adjacent, not overlapping, and is allowed."

        Design: Difficulty/resource_temporal_overlap/moonlighting_half_open_interval_overlap
        """
        resident = self._setup(api)
        created = validate_success(api.create_moonlighting(
            create_moonlighting_payload(resident["id"], site_name="Clinic C",
                                        start_date="2026-10-01",
                                        end_date="2026-11-01",
                                        hours_per_week=2.00),
            resident_headers(resident)), expected_status=201)
        assert created["status"] == "DRAFT"


class TestClockDrivenTransitions:
    def test_approved_active_completed_follow_the_logical_clock(self, api: ApiClient):
        """PRD §2.4: "advancing the clock fires time-driven moonlighting
        transitions: an `APPROVED` moonlighting request whose `start_date` has
        been reached (and whose `end_date` has not) becomes `ACTIVE`, and any
        `APPROVED` or `ACTIVE` request whose `end_date` has been reached or
        passed becomes `COMPLETED` (§3.6)."
        PRD §2.4: "It maintains a logical clock whose value, before any client
        sets it, reads exactly `2026-08-01T00:00:00Z`."

        Design: Corner/state_machines/moonlighting_clock_driven_transitions
        """
        s = setup_program_with_active_resident()
        resident = s["resident"]
        req = make_moonlighting(resident, type="INTERNAL", site_name="Metro ICU",
                                start_date="2026-08-03", end_date="2026-09-01",
                                hours_per_week=4.00, approve=True)
        # The clock still reads the pinned default 2026-08-01 < start_date.
        assert _request(api, req["id"])["status"] == "APPROVED"

        set_clock("2026-08-10T00:00:00Z")   # inside [start, end)
        assert _request(api, req["id"])["status"] == "ACTIVE"

        set_clock("2026-09-02T00:00:00Z")   # >= end_date
        assert _request(api, req["id"])["status"] == "COMPLETED"


class TestDenyAndWithdraw:
    def test_deny_and_withdraw_paths(self, api: ApiClient):
        """PRD §3.6: "Denial moves a `SUBMITTED` request to `DENIED` (from any
        other status, `ERR_MOONLIGHTING_NOT_DENIABLE`, HTTP 409) and records
        the supplied `denial_reason` as the request's `decision_reason`.
        Withdrawal is the resident's own action from `DRAFT` or `SUBMITTED`
        (otherwise `ERR_MOONLIGHTING_NOT_WITHDRAWABLE`, HTTP 409) and moves the
        request to `WITHDRAWN`."

        Design: Corner/state_machines/moonlighting_deny_and_withdraw_paths
        """
        s = setup_program_with_active_resident()
        resident = s["resident"]
        req_a = make_moonlighting(resident, site_name="Clinic A",
                                  start_date="2026-09-01", end_date="2026-10-01",
                                  submit=True)
        req_b = make_moonlighting(resident, type="INTERNAL",
                                  site_name="Metro ICU",
                                  start_date="2026-10-01", end_date="2026-11-01")

        denied = validate_success(api.deny_moonlighting(
            req_a["id"], {"denial_reason": "Insufficient supervision coverage"},
            PD))
        assert denied["status"] == "DENIED"
        assert denied["decision_reason"] == "Insufficient supervision coverage"

        withdrawn = validate_success(
            api.withdraw_moonlighting(req_b["id"], resident_headers(resident)))
        assert withdrawn["status"] == "WITHDRAWN"

        # Neither terminal request attributes hours (only APPROVED / ACTIVE /
        # COMPLETED do, PRD §3.5).
        summary = validate_success(
            api.get_duty_hour_summary(resident["id"], "2026-09-07", PD))
        assert_duty_summary(summary, resident["id"])
        assert summary["attributed_moonlighting_hours"] == approx2(0.00)


class TestInvalidTransitions:
    def test_moonlighting_invalid_from_matrix(self, api: ApiClient):
        """PRD §3.6: "The resident submits a `DRAFT` request — from any other
        status, `ERR_MOONLIGHTING_NOT_SUBMITTABLE` (HTTP 409)"; "the request
        must be `SUBMITTED` (`ERR_MOONLIGHTING_NOT_APPROVABLE`, HTTP 409)";
        "Denial moves a `SUBMITTED` request to `DENIED` (from any other status,
        `ERR_MOONLIGHTING_NOT_DENIABLE`, HTTP 409)"; "Withdrawal is the
        resident's own action from `DRAFT` or `SUBMITTED` (otherwise
        `ERR_MOONLIGHTING_NOT_WITHDRAWABLE`, HTTP 409)"; "Revocation is the
        `ProgramDirector`'s action on an `APPROVED` or `ACTIVE` request (from
        any other status, `ERR_MOONLIGHTING_NOT_REVOKABLE`, HTTP 409)".

        Design: Corner/errors/moonlighting_invalid_transition_errors
        """
        s = setup_program_with_active_resident()
        resident = s["resident"]
        req_a = make_moonlighting(resident, site_name="Clinic A",
                                  start_date="2026-09-01", end_date="2026-10-01")
        req_b = make_moonlighting(resident, type="INTERNAL",
                                  site_name="Metro ICU",
                                  start_date="2026-10-01", end_date="2026-11-01",
                                  approve=True)

        resp = api.approve_moonlighting(req_a["id"], PD)
        validate_error(resp, ApiErrorId.ERR_MOONLIGHTING_NOT_APPROVABLE)
        resp = api.deny_moonlighting(req_a["id"], {"denial_reason": "premature"}, PD)
        validate_error(resp, ApiErrorId.ERR_MOONLIGHTING_NOT_DENIABLE)
        resp = api.revoke_moonlighting(req_a["id"],
                                       {"revocation_reason": "premature"}, PD)
        validate_error(resp, ApiErrorId.ERR_MOONLIGHTING_NOT_REVOKABLE)

        submitted = validate_success(
            api.submit_moonlighting(req_a["id"], resident_headers(resident)))
        assert submitted["status"] == "SUBMITTED"
        resp = api.submit_moonlighting(req_a["id"], resident_headers(resident))
        validate_error(resp, ApiErrorId.ERR_MOONLIGHTING_NOT_SUBMITTABLE)

        resp = api.withdraw_moonlighting(req_b["id"], resident_headers(resident))
        validate_error(resp, ApiErrorId.ERR_MOONLIGHTING_NOT_WITHDRAWABLE)

        assert _request(api, req_a["id"])["status"] == "SUBMITTED"
        assert _request(api, req_b["id"])["status"] == "APPROVED"


class TestDateRangeValidation:
    def test_start_not_before_end_rejected(self, api: ApiClient):
        """PRD §3.6: "The `start_date` must be strictly before the `end_date`
        (`ERR_INVALID_DATE_RANGE`, HTTP 422)."

        Design: Corner/validations/moonlighting_invalid_date_range_rejected
        """
        s = setup_program_with_active_resident()
        resident = s["resident"]
        resp = api.create_moonlighting(
            create_moonlighting_payload(resident["id"], start_date="2026-10-01",
                                        end_date="2026-09-01"),
            resident_headers(resident))
        validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE)
        assert resp.status_code == 422


class TestAttributionProration:
    def test_weekly_attribution_prorated_by_overlap_days(self, api: ApiClient):
        """PRD §3.5: "Moonlighting attribution adds, for each of the resident's
        moonlighting requests in `APPROVED`, `ACTIVE`, or `COMPLETED` status
        whose half-open date range intersects the week, the request's
        `hours_per_week` multiplied by the number of calendar days of the range
        falling inside the week (one to seven) divided by seven — each
        request's weekly contribution rounded half-up to 2 decimal places
        before any summing."

        Design: Corner/calculations/moonlighting_attribution_proration
        """
        s = setup_program_with_active_resident()
        resident = s["resident"]
        # [2026-08-05, 2026-08-20) at 7.00 h/wk.
        make_moonlighting(resident, type="INTERNAL", site_name="Metro ICU",
                          start_date="2026-08-05", end_date="2026-08-20",
                          hours_per_week=7.00, approve=True)

        w1 = validate_success(
            api.get_duty_hour_summary(resident["id"], "2026-08-03", PD))
        assert w1["attributed_moonlighting_hours"] == approx2(5.00)  # 5/7 days
        w2 = validate_success(
            api.get_duty_hour_summary(resident["id"], "2026-08-10", PD))
        assert w2["attributed_moonlighting_hours"] == approx2(7.00)  # full week
        w3 = validate_success(
            api.get_duty_hour_summary(resident["id"], "2026-08-17", PD))
        assert w3["attributed_moonlighting_hours"] == approx2(3.00)  # 3/7 days
        assert w3["official_hours"] == approx2(3.00)  # attribution alone


class TestRoleGate:
    def test_resident_cannot_approve_own_request(self, api: ApiClient):
        """PRD §2.1: "an attempt to perform an action outside the caller's
        designated role is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."
        PRD §3.6: "Decision authority sits with the `ProgramDirector`."

        Design: Corner/rbac/resident_cannot_approve_moonlighting
        """
        s = setup_program_with_active_resident()
        resident = s["resident"]
        req = make_moonlighting(resident, submit=True)
        resp = api.approve_moonlighting(req["id"], resident_headers(resident))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        assert resp.status_code == 403
        assert _request(api, req["id"])["status"] == "SUBMITTED"
