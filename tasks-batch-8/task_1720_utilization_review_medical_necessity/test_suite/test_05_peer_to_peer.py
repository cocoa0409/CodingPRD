"""Peer-to-peer conferences on adverse determinations: scheduling window,
advisor calendar clearance, reschedule cap, lazy expiry, and the overturn
restoration cascade (PRD §2.1, §3.3, §3.5)."""
from test_helpers import (
    APPEAL_DEADLINE,
    DENIAL_DECIDED_AT,
    P2P_WINDOW_DEADLINE,
    ApiErrorId,
    TEST_USERS,
    assert_p2p_conference,
    assert_timestamp_instant_equal,
    complete_p2p_payload,
    create_p2p_payload,
    deny_auth,
    get_auth,
    get_case,
    get_conference,
    get_denial,
    make_advisor_headers,
    make_attending_headers,
    make_auth,
    make_case,
    make_conference,
    make_payer,
    make_physician,
    make_advisor,
    reschedule_p2p_payload,
    set_clock,
    setup_denied_auth,
    setup_p2p_scheduled,
    setup_submitted_auth,
    validate_error,
    validate_paginated,
    validate_success,
)

NURSE = TEST_USERS["ur_nurse_headers"]
PAYER_REVIEWER = TEST_USERS["payer_reviewer_headers"]
CASE_MANAGER = TEST_USERS["case_manager_headers"]


def _two_denied_cases_sharing_advisor(api):
    """Two Medicare cases, each with an authorization denied at
    2026-08-02T12:00:00Z, both attended by the same physician and sharing
    one advisor's calendar."""
    set_clock(DENIAL_DECIDED_AT)
    payer = make_payer()
    attending = make_physician()
    advisor = make_advisor()
    case_a = make_case(payer["id"], attending["id"], patient_mrn="MRN-OV1")
    auth_a = deny_auth(make_auth(case_a["id"])["id"])
    case_b = make_case(payer["id"], attending["id"], patient_mrn="MRN-OV2")
    auth_b = deny_auth(make_auth(case_b["id"])["id"])
    return {"payer": payer, "attending": attending, "advisor": advisor,
            "case_a": case_a, "auth_a": auth_a,
            "case_b": case_b, "auth_b": auth_b}


class TestSchedulingWindow:
    def test_p2p_create_at_exact_window_deadline(self, api):
        """PRD §3.5: "At scheduling, both the logical now and the `scheduled_start_at` must fall at or before that deadline; a violation is `ERR_P2P_WINDOW_EXPIRED`."
        PRD §2.11: "Temporal comparisons against deadlines and windows are inclusive: submission at exactly the deadline instant is on time."

        Design: Difficulty/boundary_precision_check/p2p_window_exact_deadline
        """
        ctx = setup_denied_auth(patient_mrn="MRN-WA")
        set_clock(P2P_WINDOW_DEADLINE)  # denial at 2026-08-02T12:00Z + 72h
        conf = validate_success(api.create_p2p_conference(
            ctx["auth"]["id"],
            create_p2p_payload(ctx["advisor"]["id"],
                               "2026-08-05T11:30:00Z", "2026-08-05T12:00:00Z"),
            make_attending_headers(ctx["attending"]["id"])),
            expected_status=201)
        assert_p2p_conference(conf)
        assert conf["status"] == "SCHEDULED"
        assert_timestamp_instant_equal(conf["window_deadline_at"],
                                       P2P_WINDOW_DEADLINE,
                                       "window_deadline_at")

    def test_p2p_create_one_second_past_window_rejected(self, api):
        """PRD §3.5: "At scheduling, both the logical now and the `scheduled_start_at` must fall at or before that deadline; a violation is `ERR_P2P_WINDOW_EXPIRED`."

        Design: Difficulty/boundary_precision_check/p2p_window_exact_deadline
        """
        ctx = setup_denied_auth(patient_mrn="MRN-WB")
        set_clock("2026-08-05T12:00:01Z")  # one second past the deadline
        resp = api.create_p2p_conference(
            ctx["auth"]["id"],
            create_p2p_payload(ctx["advisor"]["id"],
                               "2026-08-05T11:30:00Z", "2026-08-05T12:00:00Z"),
            make_attending_headers(ctx["attending"]["id"]))
        validate_error(resp, ApiErrorId.ERR_P2P_WINDOW_EXPIRED,
                       expected_status=422)

    def test_p2p_window_deadline_computed_at_schedule(self, api):
        """PRD §3.5: "The conference's `window_deadline_at` is computed as the denied request's `decided_at` (of the `DENIED` transition) plus the payer's `p2p_window_hours`."
        PRD §3.3: "The denial's `appeal_deadline_at` is computed as `denied_at` plus the payer's `appeal_deadline_days` and is immutable thereafter — peer-to-peer scheduling does not extend it."

        Design: Corner/complexity_layers/p2p_window_deadline_computed_at_schedule
        """
        ctx = setup_denied_auth(patient_mrn="MRN-SCH")
        conf = make_conference(ctx["auth"]["id"], ctx["advisor"]["id"],
                               ctx["attending"]["id"])
        # decided_at 2026-08-02T12:00:00Z + 72h
        assert_timestamp_instant_equal(conf["window_deadline_at"],
                                       P2P_WINDOW_DEADLINE,
                                       "window_deadline_at")
        denial = get_denial(ctx["denial"]["id"])
        # denied_at 2026-08-02T12:00:00Z + 60 days
        assert_timestamp_instant_equal(denial["appeal_deadline_at"],
                                       APPEAL_DEADLINE,
                                       "appeal_deadline_at")
        assert denial["status"] == "P2P_SCHEDULED"


class TestAdvisorCalendarClearance:
    def test_advisor_calendar_14_minute_gap_rejected(self, api):
        """PRD §3.5: "The advisor's calendar is protected by a buffered-overlap rule: the new conference must leave at least 15 minutes of clearance on both sides from every `SCHEDULED` conference of the same advisor — exactly 15 minutes is allowed — and a conflict is rejected with `ERR_SCHEDULING_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/advisor_calendar_buffer_overlap
        """
        ctx = _two_denied_cases_sharing_advisor(api)
        make_conference(ctx["auth_a"]["id"], ctx["advisor"]["id"],
                        ctx["attending"]["id"],
                        "2026-08-03T10:00:00Z", "2026-08-03T10:30:00Z")
        # 10:44 leaves only a 14-minute gap after the 10:30 end.
        resp = api.create_p2p_conference(
            ctx["auth_b"]["id"],
            create_p2p_payload(ctx["advisor"]["id"],
                               "2026-08-03T10:44:00Z", "2026-08-03T11:14:00Z"),
            make_attending_headers(ctx["attending"]["id"]))
        validate_error(resp, ApiErrorId.ERR_SCHEDULING_OVERLAP,
                       expected_status=409)

    def test_advisor_calendar_15_minute_gap_allowed(self, api):
        """PRD §3.5: "The advisor's calendar is protected by a buffered-overlap rule: the new conference must leave at least 15 minutes of clearance on both sides from every `SCHEDULED` conference of the same advisor — exactly 15 minutes is allowed — and a conflict is rejected with `ERR_SCHEDULING_OVERLAP`."
        PRD §3.1: "one lists every peer-to-peer conference in which the physician serves as advisor or attendee, ordered by `scheduled_start_at` ascending and then `created_at` ascending"

        Design: Difficulty/resource_temporal_overlap/advisor_calendar_buffer_overlap
        """
        ctx = _two_denied_cases_sharing_advisor(api)
        conf_a = make_conference(ctx["auth_a"]["id"], ctx["advisor"]["id"],
                                 ctx["attending"]["id"],
                                 "2026-08-03T10:00:00Z", "2026-08-03T10:30:00Z")
        # 10:45 leaves exactly 15 minutes of clearance — allowed.
        conf_b = validate_success(api.create_p2p_conference(
            ctx["auth_b"]["id"],
            create_p2p_payload(ctx["advisor"]["id"],
                               "2026-08-03T10:45:00Z", "2026-08-03T11:15:00Z"),
            make_attending_headers(ctx["attending"]["id"])),
            expected_status=201)
        assert conf_b["status"] == "SCHEDULED"

        calendar, meta = validate_paginated(
            api.list_physician_conferences(ctx["advisor"]["id"], CASE_MANAGER))
        assert meta["total_count"] == 2
        assert [c["id"] for c in calendar] == [conf_a["id"], conf_b["id"]], (
            "the advisor calendar lists both conferences by scheduled_start_at")


class TestEligibilityAndOwnership:
    def test_p2p_create_requires_denied_auth(self, api):
        """PRD §3.5: "The parent authorization must be in `DENIED` status; otherwise `ERR_P2P_NOT_ELIGIBLE`."

        Design: Corner/validations/p2p_create_requires_denied_auth
        """
        ctx = setup_submitted_auth(with_advisor=True, patient_mrn="MRN-NEL")
        resp = api.create_p2p_conference(
            ctx["auth"]["id"],
            create_p2p_payload(ctx["advisor"]["id"],
                               "2026-08-03T10:00:00Z", "2026-08-03T10:30:00Z"),
            make_attending_headers(ctx["attending"]["id"]))
        validate_error(resp, ApiErrorId.ERR_P2P_NOT_ELIGIBLE,
                       expected_status=409)

    def test_p2p_create_by_non_attending_rejected(self, api):
        """PRD §2.1: "On those endpoints, the caller's `X-User-ID` must equal the parent case's `attending_physician_id`; a mismatch is rejected with `ERR_NOT_CASE_ATTENDING`."

        Design: Corner/validations/p2p_create_by_non_attending_rejected
        """
        ctx = setup_denied_auth(patient_mrn="MRN-OWN")
        other = make_physician(full_name="Dr. Other", specialty="Cardiology")
        resp = api.create_p2p_conference(
            ctx["auth"]["id"],
            create_p2p_payload(ctx["advisor"]["id"],
                               "2026-08-03T10:00:00Z", "2026-08-03T10:30:00Z"),
            make_attending_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_CASE_ATTENDING,
                       expected_status=403)

    def test_p2p_advisor_must_be_advisor(self, api):
        """PRD §3.5: "The payload names the `advisor_physician_id`, which must resolve to a `Physician` whose `is_advisor` flag is true (`ERR_NOT_PHYSICIAN_ADVISOR` otherwise), plus the `scheduled_start_at` and `scheduled_end_at`."

        Design: Corner/validations/p2p_advisor_must_be_advisor
        """
        ctx = setup_denied_auth(patient_mrn="MRN-NAD")
        plain = make_physician(full_name="Dr. Plain", specialty="Family Medicine",
                               is_advisor=False)
        resp = api.create_p2p_conference(
            ctx["auth"]["id"],
            create_p2p_payload(plain["id"],
                               "2026-08-03T10:00:00Z", "2026-08-03T10:30:00Z"),
            make_attending_headers(ctx["attending"]["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_PHYSICIAN_ADVISOR,
                       expected_status=422)


class TestRescheduleCap:
    def test_p2p_third_reschedule_rejected(self, api):
        """PRD §3.5: "The attending may reschedule — a self-loop that keeps the conference `SCHEDULED` — subject to three guards: `reschedule_count` must be below the hard cap of 2 (at the cap, `ERR_P2P_RESCHEDULE_LIMIT`); the window check re-applies against the new start (`ERR_P2P_WINDOW_EXPIRED`); and the advisor-calendar clearance check re-applies (`ERR_SCHEDULING_OVERLAP`)."

        Design: Corner/validations/p2p_third_reschedule_rejected
        """
        ctx = setup_p2p_scheduled(patient_mrn="MRN-RL")
        conf = ctx["conference"]
        for start, end in (("2026-08-03T11:00:00Z", "2026-08-03T11:30:00Z"),
                           ("2026-08-03T13:00:00Z", "2026-08-03T13:30:00Z")):
            moved = validate_success(api.reschedule_p2p(
                conf["id"], reschedule_p2p_payload(start, end),
                make_attending_headers(ctx["attending"]["id"])))
            assert moved["status"] == "SCHEDULED"
        assert moved["reschedule_count"] == 2

        resp = api.reschedule_p2p(
            conf["id"],
            reschedule_p2p_payload("2026-08-04T10:00:00Z",
                                   "2026-08-04T10:30:00Z"),
            make_attending_headers(ctx["attending"]["id"]))
        validate_error(resp, ApiErrorId.ERR_P2P_RESCHEDULE_LIMIT,
                       expected_status=409)
        current = get_conference(conf["id"])
        assert current["reschedule_count"] == 2
        assert current["status"] == "SCHEDULED"


class TestCancelAndExpiry:
    def test_p2p_schedule_then_scheduled_keeps_appeal_deadline(self, api):
        """PRD §3.5: "A successfully scheduled conference is born `SCHEDULED` with `reschedule_count` 0 and `outcome` `NONE`; the linked denial case moves from `OPEN` to `P2P_SCHEDULED` with its `appeal_deadline_at` unchanged; and `P2P_SCHEDULED` is appended to the audit trail."
        PRD §3.3: "The denial's `appeal_deadline_at` is computed as `denied_at` plus the payer's `appeal_deadline_days` and is immutable thereafter — peer-to-peer scheduling does not extend it."

        Design: Difficulty/compensating_invariant/p2p_schedule_cancel_conserves_appeal_deadline
        """
        ctx = setup_denied_auth(patient_mrn="MRN-INV2A")
        denial = ctx["denial"]
        assert_timestamp_instant_equal(denial["appeal_deadline_at"],
                                       APPEAL_DEADLINE,
                                       "appeal_deadline_at")
        assert denial["status"] == "OPEN"

        make_conference(ctx["auth"]["id"], ctx["advisor"]["id"],
                        ctx["attending"]["id"])
        scheduled = get_denial(denial["id"])
        assert scheduled["status"] == "P2P_SCHEDULED"
        # Scheduling a peer-to-peer must not toll the appeal deadline.
        assert_timestamp_instant_equal(scheduled["appeal_deadline_at"],
                                       APPEAL_DEADLINE,
                                       "appeal_deadline_at after scheduling")

    def test_p2p_cancel_restores_open_and_conserves_deadline(self, api):
        """PRD §3.5: "The attending may instead cancel outright: the conference moves to terminal `CANCELLED`, the linked denial returns from `P2P_SCHEDULED` to `OPEN` with its appeal deadline conserved — the schedule-then-cancel pair is a compensating invariant that never extends the clock — and `P2P_CANCELLED` is appended."

        Design: Difficulty/compensating_invariant/p2p_schedule_cancel_conserves_appeal_deadline
        """
        ctx = setup_p2p_scheduled(patient_mrn="MRN-INV2B")
        cancelled = validate_success(api.cancel_p2p(
            ctx["conference"]["id"], {},
            make_attending_headers(ctx["attending"]["id"])))
        assert cancelled["status"] == "CANCELLED"

        denial = get_denial(ctx["denial"]["id"])
        assert denial["status"] == "OPEN"
        # The schedule+cancel pair leaves the deadline instant unchanged.
        assert_timestamp_instant_equal(denial["appeal_deadline_at"],
                                       APPEAL_DEADLINE,
                                       "appeal_deadline_at after cancel")

    def test_p2p_lazy_expiry_materializes_on_read(self, api):
        """PRD §3.5: "`EXPIRED` is materialized lazily whenever the conference is read or mutated while logical now exceeds the deadline. Expiration behaves like cancellation for the denial — the linked case returns to `OPEN` with the deadline unchanged — and appends `P2P_EXPIRED`."

        Design: Corner/state_machines/p2p_lazy_expiry_materializes_on_read
        """
        ctx = setup_p2p_scheduled(patient_mrn="MRN-EXP")
        set_clock("2026-08-06T00:00:00Z")  # past the 2026-08-05T12:00Z deadline

        conf = validate_success(
            api.get_p2p_conference(ctx["conference"]["id"], NURSE))
        assert conf["status"] == "EXPIRED", (
            "reading after window_deadline_at materializes EXPIRED")

        denial = get_denial(ctx["denial"]["id"])
        assert denial["status"] == "OPEN"
        assert_timestamp_instant_equal(denial["appeal_deadline_at"],
                                       APPEAL_DEADLINE,
                                       "appeal_deadline_at after expiry")


class TestCompletion:
    def test_p2p_complete_overturn_restores_auth(self, api):
        """PRD §3.5: "An `OVERTURNED` outcome fires the full restoration cascade: the linked authorization request moves from `DENIED` back to `APPROVED`, with a certified interval appended at the case frontier — starting at the highest existing certified end on the case and extending for the `certified_day_count` supplied in the completion payload; the linked denial case resolves to `RESOLVED_OVERTURNED` (from either `OPEN` or `P2P_SCHEDULED`), appending `DENIAL_OVERTURNED` for the denial's own resolution; the case's `auth_status` returns to `AUTHORIZED`; the certified counters are recomputed; the case `version` increments; and `P2P_COMPLETED` is appended."

        Design: Corner/state_machines/p2p_complete_overturn_restores_auth
        """
        ctx = setup_p2p_scheduled(patient_mrn="MRN-P2PO")
        set_clock("2026-08-03T10:25:00Z")  # inside the scheduled 10:00-10:30
        completed = validate_success(api.complete_p2p(
            ctx["conference"]["id"],
            complete_p2p_payload("OVERTURNED", certified_day_count=3),
            make_advisor_headers(ctx["advisor"]["id"])))
        assert completed["status"] == "COMPLETED"
        assert completed["outcome"] == "OVERTURNED"

        auth = get_auth(ctx["auth"]["id"])
        assert auth["status"] == "APPROVED"
        assert auth["certified_day_start"] == 1
        assert auth["certified_day_end"] == 4, (
            "the frontier append grants the 3 restored days as [1, 4)")

        denial = get_denial(ctx["denial"]["id"])
        assert denial["status"] == "RESOLVED_OVERTURNED"

        case = get_case(ctx["case"]["id"])
        assert case["auth_status"] == "AUTHORIZED"
        assert case["certified_day_count"] == 3

    def test_physician_conference_calendar_reverse_list(self, api):
        """PRD §3.1: "one lists every peer-to-peer conference in which the physician serves as advisor or attendee, ordered by `scheduled_start_at` ascending and then `created_at` ascending"

        Design: Corner/endpoints/physician_conference_calendar_reverse_list
        """
        ctx = setup_p2p_scheduled(patient_mrn="MRN-CAL")
        calendar, meta = validate_paginated(
            api.list_physician_conferences(ctx["advisor"]["id"], CASE_MANAGER))
        assert meta["total_count"] == 1 and len(calendar) == 1
        assert_p2p_conference(calendar[0])
        assert calendar[0]["id"] == ctx["conference"]["id"]
        assert calendar[0]["advisor_physician_id"] == ctx["advisor"]["id"]
