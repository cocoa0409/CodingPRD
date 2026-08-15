"""Staffing call-back: PENDING fork, cancel compensation, pool boundaries,
selection ranking, clock expiry, ownership, and the demobilization cascade."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_callback,
    assert_callback_request,
    assert_timestamp_instant,
    create_callback_eligible_staff,
    create_callback_request_payload,
    create_explicit_callback,
    create_incident,
    create_staff_member,
    make_on_call_staff_headers,
    set_clock,
    setup_incident_with_activated_site,
    validate_error,
    validate_paginated,
    validate_success,
)

IC = TEST_USERS["incident_commander_headers"]
PC = TEST_USERS["planning_chief_headers"]
OCS = TEST_USERS["on_call_staff_headers"]


def _incident_and_staff(score=50, department="EMERGENCY", **staff_overrides):
    staff = create_callback_eligible_staff(score=score, department=department,
                                           **staff_overrides)
    incident = create_incident(incident_type="HUMAN")
    return incident, staff


class TestRespondFork:
    def test_accept_branch_increments_committed_count(self, api):
        """PRD §3.5: "Acceptance moves `PENDING` → `ACCEPTED`, stamps
        `responded_at`, and increases the incident's `committed_staff_count` by
        one as the count is rederived."

        Design: Difficulty/non_linear_state_machine/callback_request_fork_accept_vs_decline
        """
        incident, s1 = _incident_and_staff(score=50)
        cb1 = create_explicit_callback(incident["id"], s1["id"])

        accepted = accept_callback(cb1["id"], s1["id"])
        assert_callback_request(accepted)
        assert accepted["status"] == "ACCEPTED"
        assert accepted["responded_at"] is not None

        inc = validate_success(api.get_incident(incident["id"], PC))
        assert inc["committed_staff_count"] == 1

    def test_decline_branch_leaves_committed_count_unchanged(self, api):
        """PRD §3.5: "Declining moves `PENDING` → `DECLINED`, stamps
        `responded_at`, and leaves the count unchanged."
        PRD §3.5: "`committed_staff_count` is always the count of the incident's
        call-back requests currently in `ACCEPTED` — requests that are `PENDING`,
        `DECLINED`, `EXPIRED`, `CANCELLED`, or `COMPLETED` never contribute."

        Design: Difficulty/non_linear_state_machine/callback_request_fork_accept_vs_decline
        """
        incident, s2 = _incident_and_staff(score=40)
        cb2 = create_explicit_callback(incident["id"], s2["id"])

        declined = validate_success(
            api.respond_callback_request(
                cb2["id"], {"outcome": "DECLINE"}, make_on_call_staff_headers(s2["id"])
            )
        )
        assert declined["status"] == "DECLINED"
        assert declined["responded_at"] is not None

        inc = validate_success(api.get_incident(incident["id"], PC))
        assert inc["committed_staff_count"] == 0


class TestCancelCompensation:
    def test_cancel_accepted_request_compensates_committed_count(self, api):
        """PRD §3.5: "A `PlanningChief` may cancel a `PENDING` or `ACCEPTED`
        request, optionally recording a `reason`; cancelling an `ACCEPTED` request
        compensates by decreasing `committed_staff_count` by one, returning it to
        its pre-accept value."

        Design: Difficulty/transitive_cascade/callback_cancel_compensates_committed_count
        """
        incident, s1 = _incident_and_staff(score=10, department="NURSING")
        cb1 = create_explicit_callback(incident["id"], s1["id"])
        accept_callback(cb1["id"], s1["id"])

        cancelled = validate_success(api.cancel_callback_request(cb1["id"], PC))
        assert cancelled["status"] == "CANCELLED"

        inc = validate_success(api.get_incident(incident["id"], PC))
        assert inc["committed_staff_count"] == 0, (
            "the compensation fired because the cancelled request was ACCEPTED"
        )

    def test_cancel_pending_request_leaves_count_untouched(self, api):
        """PRD §3.5: "A `PlanningChief` may cancel a `PENDING` or `ACCEPTED`
        request, optionally recording a `reason`; cancelling an `ACCEPTED` request
        compensates by decreasing `committed_staff_count` by one, returning it to
        its pre-accept value."
        PRD §3.5: "`committed_staff_count` is always the count of the incident's
        call-back requests currently in `ACCEPTED` — requests that are `PENDING`,
        `DECLINED`, `EXPIRED`, `CANCELLED`, or `COMPLETED` never contribute."

        Design: Difficulty/transitive_cascade/callback_cancel_compensates_committed_count
        """
        incident, s1 = _incident_and_staff(score=10, department="NURSING")
        cb1 = create_explicit_callback(incident["id"], s1["id"])

        cancelled = validate_success(api.cancel_callback_request(cb1["id"], PC))
        assert cancelled["status"] == "CANCELLED"
        inc = validate_success(api.get_incident(incident["id"], PC))
        assert inc["committed_staff_count"] == 0


class TestCommittedHeadcountConservation:
    def test_accept_then_cancel_conserves_committed_headcount(self, api):
        """PRD §3.5: "Acceptance moves `PENDING` → `ACCEPTED`, stamps
        `responded_at`, and increases the incident's `committed_staff_count` by
        one as the count is rederived."
        PRD §3.5: "cancelling an `ACCEPTED` request compensates by decreasing
        `committed_staff_count` by one, returning it to its pre-accept value."

        Design: Difficulty/compensating_invariant/callback_accept_then_cancel_conserves_committed_headcount
        """
        incident, s1 = _incident_and_staff(score=5, department="ICU")
        cb1 = create_explicit_callback(incident["id"], s1["id"])

        before = validate_success(api.get_incident(incident["id"], PC))
        assert before["committed_staff_count"] == 0

        accept_callback(cb1["id"], s1["id"])
        mid = validate_success(api.get_incident(incident["id"], PC))
        assert mid["committed_staff_count"] == 1, "accept incremented the count"

        validate_success(api.cancel_callback_request(cb1["id"], PC))
        after = validate_success(api.get_incident(incident["id"], PC))
        assert after["committed_staff_count"] == before["committed_staff_count"], (
            "cancel compensated: no drift in committed_staff_count"
        )

    def test_partial_cancel_conserves_remaining_accepts(self, api):
        """PRD §3.5: "`committed_staff_count` is always the count of the incident's
        call-back requests currently in `ACCEPTED` — requests that are `PENDING`,
        `DECLINED`, `EXPIRED`, `CANCELLED`, or `COMPLETED` never contribute."

        Design: Difficulty/compensating_invariant/callback_accept_then_cancel_conserves_committed_headcount
        """
        incident = create_incident(incident_type="HUMAN")
        s1 = create_callback_eligible_staff(score=5, department="ICU")
        s2 = create_callback_eligible_staff(score=6, department="ICU")
        cb1 = create_explicit_callback(incident["id"], s1["id"])
        cb2 = create_explicit_callback(incident["id"], s2["id"])
        accept_callback(cb1["id"], s1["id"])
        accept_callback(cb2["id"], s2["id"])

        mid = validate_success(api.get_incident(incident["id"], PC))
        assert mid["committed_staff_count"] == 2

        validate_success(api.cancel_callback_request(cb1["id"], PC))
        after = validate_success(api.get_incident(incident["id"], PC))
        assert after["committed_staff_count"] == 1, (
            "only the cancelled acceptance is compensated"
        )


class TestAutoSelectPoolBoundary:
    def _three_eligible_staff(self):
        s1 = create_callback_eligible_staff(score=30, full_name="S One",
                                            badge_number="B-301")
        s2 = create_callback_eligible_staff(score=20, full_name="S Two",
                                            badge_number="B-302")
        s3 = create_callback_eligible_staff(score=10, full_name="S Three",
                                            badge_number="B-303")
        return s1, s2, s3

    def test_pool_overflow_rejected_atomically(self, api):
        """PRD §3.5: "When the pool is smaller than `auto_select_count`, the create
        is rejected with `ERR_INSUFFICIENT_CALLBACK_POOL` and nothing is created —
        the check is atomic."
        PRD §3.5: "The call-back list supports optional `incident_id`,
        `staff_member_id`, and `status` filters."

        Design: Difficulty/boundary_precision_check/callback_pool_exact_fit_then_overflow
        """
        self._three_eligible_staff()
        incident = create_incident(incident_name="MCI-pool", incident_type="HUMAN")

        resp = api.create_callback_request(
            create_callback_request_payload(incident["id"], auto_select_count=4), PC
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CALLBACK_POOL)

        rows, meta = validate_paginated(
            api.list_callback_requests(PC, params={"incident_id": incident["id"]})
        )
        assert meta["total_count"] == 0, "the failed create wrote no requests"

    def test_pool_exact_fit_creates_all_in_rank_order(self, api):
        """PRD §3.5: "Auto-select mode instead names `auto_select_count` and
        optionally a `required_department`; the server builds the eligible pool —
        members who are active, call-back eligible, in the required department when
        one is given, and holding no `PENDING` or `ACCEPTED` request for this
        incident — ranks it by `callback_seniority_score` from highest to lowest,
        ties broken by the member's `created_at` from earliest to latest and then
        by `badge_number` in ascending order, and creates requests for the
        top-ranked members."
        PRD §3.5: "The create response is always an array, ordered by selection
        rank."

        Design: Difficulty/boundary_precision_check/callback_pool_exact_fit_then_overflow
        """
        s1, s2, s3 = self._three_eligible_staff()
        incident = create_incident(incident_name="MCI-pool", incident_type="HUMAN")

        data = validate_success(
            api.create_callback_request(
                create_callback_request_payload(incident["id"], auto_select_count=3), PC
            ),
            expected_status=201,
        )
        assert len(data) == 3, "count == pool size is allowed"
        assert [r["staff_member_id"] for r in data] == [s1["id"], s2["id"], s3["id"]], (
            "selection order is callback_seniority_score DESC"
        )


class TestClockExpiry:
    def test_callback_request_clock_sweep_expires_pending(self, api):
        """PRD §2.5: "Setting the clock triggers two sweeps. Every call-back
        request still in `PENDING` whose `expires_at` lies strictly before the new
        clock time transitions to `EXPIRED`".
        PRD §3.5: "On each created request, `response_window_hours` defaults to 2
        when omitted, and `expires_at` is the request's creation time plus that
        many hours."

        Design: Corner/state_machines/callback_request_clock_sweep_expires_pending
        """
        incident, s1 = _incident_and_staff(score=5, department="ICU")
        cb1 = create_explicit_callback(incident["id"], s1["id"],
                                       response_window_hours=2)
        assert_timestamp_instant(cb1["expires_at"], "2026-08-01T02:00:00Z")
        # created at the 2026-08-01T00:00:00Z startup clock plus two hours

        report = set_clock("2026-08-01T02:00:01Z")
        assert report["swept_callbacks"] == 1

        reread = validate_success(api.get_callback_request(cb1["id"], PC))
        assert reread["status"] == "EXPIRED"


class TestDemobilizeCascade:
    def test_incident_demobilize_transitions_callbacks_and_sites(self, api):
        """PRD §3.4: "First, every call-back request of this incident still
        `PENDING` transitions to `EXPIRED`, and every one `ACCEPTED` transitions to
        `COMPLETED` — the duty tour ends — with `committed_staff_count` rederived
        accordingly. Second, every alternate care site `ACTIVATED` in service of
        this incident demobilizes per §3.7".

        Design: Corner/state_machines/incident_demobilize_transitions_callbacks_and_sites
        """
        incident, site = setup_incident_with_activated_site(
            bed_capacity=30, incident_overrides={"incident_name": "MCI-demob"}
        )
        s1 = create_callback_eligible_staff(score=60, department="ICU")
        s2 = create_callback_eligible_staff(score=55, department="ICU")
        cb1 = create_explicit_callback(incident["id"], s1["id"])
        cb2 = create_explicit_callback(incident["id"], s2["id"])
        accept_callback(cb2["id"], s2["id"])

        demobilized = validate_success(api.demobilize_incident(incident["id"], IC))
        assert demobilized["status"] == "DEACTIVATED"

        r1 = validate_success(api.get_callback_request(cb1["id"], PC))
        assert r1["status"] == "EXPIRED", "PENDING branch of the cascade"
        r2 = validate_success(api.get_callback_request(cb2["id"], PC))
        assert r2["status"] == "COMPLETED", "ACCEPTED branch of the cascade"

        site_after = validate_success(api.get_alternate_care_site(site["id"], IC))
        assert site_after["status"] == "DEMOBILIZED"
        assert site_after["activated_incident_id"] is None

        inc_after = validate_success(api.get_incident(incident["id"], IC))
        assert inc_after["committed_staff_count"] == 0


class TestCreateValidation:
    def test_duplicate_callback_rejected(self, api):
        """PRD §3.5: "Explicit mode names a `staff_member_id`; the member must be
        both `is_active` and `callback_eligible` (`ERR_STAFF_NOT_CALLBACK_ELIGIBLE`),
        and must not already hold a `PENDING` or `ACCEPTED` request for this
        incident (`ERR_DUPLICATE_CALLBACK`)."

        Design: Corner/validations/duplicate_callback_rejected
        """
        incident, s1 = _incident_and_staff(score=5, department="ICU")
        create_explicit_callback(incident["id"], s1["id"])
        resp = api.create_callback_request(
            create_callback_request_payload(incident["id"], staff_member_id=s1["id"]), PC
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CALLBACK)

    def test_callback_create_both_modes_rejected(self, api):
        """PRD §3.5: "A create carrying both modes, or neither, is rejected with
        `ERR_INVALID_REQUEST`."

        Design: Corner/validations/callback_create_both_modes_rejected
        """
        incident, s1 = _incident_and_staff(score=5, department="ICU")
        resp = api.create_callback_request(
            create_callback_request_payload(
                incident["id"], staff_member_id=s1["id"], auto_select_count=2
            ),
            PC,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_explicit_callback_ineligible_staff_rejected(self, api):
        """PRD §3.5: "Explicit mode names a `staff_member_id`; the member must be
        both `is_active` and `callback_eligible` (`ERR_STAFF_NOT_CALLBACK_ELIGIBLE`)".
        PRD §3.5: "`callback_eligible`, defaulting to false, marks whether the
        member may receive surge call-backs".

        Design: Corner/validations/explicit_callback_ineligible_staff_rejected
        """
        s1 = create_staff_member(full_name="J Ten", department="ICU")
        assert s1["callback_eligible"] is False
        incident = create_incident(incident_name="MCI-inelig", incident_type="HUMAN")
        resp = api.create_callback_request(
            create_callback_request_payload(incident["id"], staff_member_id=s1["id"]), PC
        )
        validate_error(resp, ApiErrorId.ERR_STAFF_NOT_CALLBACK_ELIGIBLE)


class TestOwnershipAndRoles:
    def test_callback_respond_by_other_staff_rejected(self, api):
        """PRD §2.7: "A related ownership rule guards the call-back desk:
        responding to a call-back request requires the responder's `X-User-ID` to
        equal the request's `staff_member_id`; anyone else is rejected with
        `ERR_NOT_CALLBACK_OWNER` (HTTP 403)."

        Design: Corner/rbac/callback_respond_by_other_staff_rejected
        """
        incident, s1 = _incident_and_staff(score=5, department="ICU",
                                           full_name="Owner")
        s2 = create_callback_eligible_staff(score=4, department="ICU",
                                            full_name="Other")
        cb1 = create_explicit_callback(incident["id"], s1["id"])

        resp = api.respond_callback_request(
            cb1["id"], {"outcome": "ACCEPT"}, make_on_call_staff_headers(s2["id"])
        )
        validate_error(resp, ApiErrorId.ERR_NOT_CALLBACK_OWNER)
        reread = validate_success(api.get_callback_request(cb1["id"], PC))
        assert reread["status"] == "PENDING"

    def test_rbac_oncall_staff_cannot_create_callbacks(self, api):
        """PRD §2.1: "A request that is authenticated but whose role is not
        authorized for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)."
        PRD §4: "POST | `/emergency/callback-requests` | Create call-back
        request(s), explicit or auto-select | PlanningChief".

        Design: Corner/rbac/rbac_oncall_staff_cannot_create_callbacks
        """
        incident = create_incident(incident_name="MCI-rbac", incident_type="HUMAN")
        resp = api.create_callback_request(
            create_callback_request_payload(incident["id"], auto_select_count=1), OCS
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestResponseShape:
    def test_callback_creation_returns_array_in_both_modes(self, api):
        """PRD §3.5: "The create response is always an array, ordered by selection
        rank."
        PRD §3.5: "On each created request, `response_window_hours` defaults to 2
        when omitted, and `expires_at` is the request's creation time plus that
        many hours."
        PRD §3.5: "Requests open in `PENDING`."

        Design: Corner/endpoints/callback_creation_returns_array_in_both_modes
        """
        incident, s1 = _incident_and_staff(score=5, department="ICU")
        resp = api.create_callback_request(
            create_callback_request_payload(incident["id"], staff_member_id=s1["id"]), PC
        )
        body = resp.json()
        assert resp.status_code == 201
        assert body["response_type"] == "array", "even explicit mode returns an array"
        data = validate_success(resp, expected_status=201)
        assert len(data) == 1
        assert_callback_request(data[0])
        assert data[0]["staff_member_id"] == s1["id"]
        assert data[0]["status"] == "PENDING"
        assert data[0]["response_window_hours"] == 2, "default response window"


class TestAutoSelectRanking:
    def test_auto_select_ranking_seniority_then_badge_tiebreak(self, api):
        """PRD §3.5: "Auto-select mode instead names `auto_select_count` and
        optionally a `required_department`; the server builds the eligible pool —
        members who are active, call-back eligible, in the required department when
        one is given, and holding no `PENDING` or `ACCEPTED` request for this
        incident — ranks it by `callback_seniority_score` from highest to lowest,
        ties broken by the member's `created_at` from earliest to latest and then
        by `badge_number` in ascending order, and creates requests for the
        top-ranked members."

        Design: Corner/cross_cutting_layers/auto_select_ranking_seniority_then_badge_tiebreak
        """
        s1 = create_callback_eligible_staff(score=90, full_name="Tie A",
                                            badge_number="B-001")
        s2 = create_callback_eligible_staff(score=90, full_name="Tie B",
                                            badge_number="B-002")
        s3 = create_callback_eligible_staff(score=80, full_name="Low",
                                            badge_number="B-003")
        incident = create_incident(incident_name="MCI-rank", incident_type="HUMAN")

        data = validate_success(
            api.create_callback_request(
                create_callback_request_payload(incident["id"], auto_select_count=2), PC
            ),
            expected_status=201,
        )
        assert len(data) == 2
        assert data[0]["staff_member_id"] == s1["id"], (
            "score-90 tie broken by badge_number ASC: B-001 before B-002"
        )
        assert data[1]["staff_member_id"] == s2["id"]
        assert s3["id"] not in [r["staff_member_id"] for r in data], (
            "the score-80 member is not selected"
        )

    def test_auto_select_excludes_staff_with_open_callback(self, api):
        """PRD §3.5: "the server builds the eligible pool — members who are active,
        call-back eligible, in the required department when one is given, and
        holding no `PENDING` or `ACCEPTED` request for this incident".

        Design: Corner/cross_cutting_layers/auto_select_excludes_staff_with_open_callback
        """
        s1 = create_callback_eligible_staff(score=90, full_name="Busy",
                                            badge_number="B-011")
        s2 = create_callback_eligible_staff(score=80, full_name="Free",
                                            badge_number="B-012")
        incident = create_incident(incident_name="MCI-excl", incident_type="HUMAN")
        create_explicit_callback(incident["id"], s1["id"])

        data = validate_success(
            api.create_callback_request(
                create_callback_request_payload(incident["id"], auto_select_count=1), PC
            ),
            expected_status=201,
        )
        assert len(data) == 1
        assert data[0]["staff_member_id"] == s2["id"], (
            "the top-ranked member is skipped because of the open PENDING request"
        )
