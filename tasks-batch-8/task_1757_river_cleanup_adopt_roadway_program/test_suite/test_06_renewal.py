"""Renewal lifecycle: happy-path roll-forward and denial expiry (PRD §3.8)."""
from test_helpers import (
    brief_event,
    complete_event,
    create_adult_waiver,
    create_event,
    get_agreement,
    make_coordinator_headers,
    make_group_leader_headers,
    set_clock,
    setup_active_agreement,
    validate_success,
)

COORD = make_coordinator_headers()


class TestRenewalApproval:
    def test_renewal_approval_rolls_term_forward(self, api):
        """PRD §3.8: "An approved renewal rolls the term forward:
        `term_start_date` becomes the old `term_end_date`, `term_end_date`
        becomes the new start plus 24 months, `renewal_count` increments,
        `standing` resets to `NOT_EVALUATED`, and the rolling window counter is
        recomputed, returning the agreement to `ACTIVE`."

        Design: Corner/state_machines/renewal_approval_rolls_term_forward
        """
        group, segment, agreement = setup_active_agreement()
        w1 = create_adult_waiver(agreement["id"], group["id"], name="Ada Adult",
                                 dob="1990-05-01")
        # Window 1 completions (2026-08-01 .. 2027-08-01).
        w1_events = []
        for day in ("2026-09-10", "2026-10-10", "2027-01-10"):
            ev = create_event(agreement["id"], group["id"], scheduled_date=day,
                              expected_volunteers=3)
            brief_event(ev["id"], group["id"], [w1["id"]])
            w1_events.append((day, ev["id"]))
        # Window 2 completions (2027-08-01 .. 2028-08-01).
        w2_events = []
        for day in ("2027-09-05", "2028-01-10", "2028-03-05", "2028-04-20"):
            ev = create_event(agreement["id"], group["id"], scheduled_date=day,
                              expected_volunteers=3)
            w2_events.append((day, ev["id"]))

        for day, eid in w1_events:
            set_clock(f"{day}T10:00:00Z")
            complete_event(eid, group["id"])

        # w1 expired 2027-08-01; sign a second adult before W2 briefings.
        set_clock("2027-09-05T09:00:00Z")
        w2 = create_adult_waiver(agreement["id"], group["id"], name="Ben Adult",
                                 dob="1988-03-15")
        for day, eid in w2_events:
            brief_event(eid, group["id"], [w2["id"]])
        for day, eid in w2_events:
            set_clock(f"{day}T10:00:00Z")
            complete_event(eid, group["id"])

        set_clock("2028-05-10T09:00:00Z")
        gl = make_group_leader_headers(group["id"])
        rr = validate_success(api.renewal_request(agreement["id"], gl), 200)
        assert rr["status"] == "RENEWAL_REVIEW"

        fin = validate_success(
            api.renewal_decision(
                agreement["id"], {"decision": "APPROVE", "note": "excellent record"},
                COORD), 200)
        assert fin["status"] == "ACTIVE"
        assert fin["term_start_date"] == "2028-08-01"
        assert fin["term_end_date"] == "2030-08-01"
        assert fin["renewal_count"] == 1
        assert fin["standing"] == "NOT_EVALUATED"

    def test_renewal_approval_resets_standing(self, api):
        """PRD §3.8: "`renewal_count` increments, `standing` resets to
        `NOT_EVALUATED`, and the rolling window counter is recomputed,
        returning the agreement to `ACTIVE`."

        Design: Corner/state_machines/renewal_approval_rolls_term_forward
        """
        group, segment, agreement = setup_active_agreement()
        w1 = create_adult_waiver(agreement["id"], group["id"], name="Ada Adult",
                                 dob="1990-05-01")
        days_w1 = ("2026-09-10", "2026-10-10", "2027-01-10")
        days_w2 = ("2027-09-05", "2028-01-10", "2028-03-05", "2028-04-20")
        w1_ids = []
        w2_ids = []
        for day in days_w1:
            ev = create_event(agreement["id"], group["id"], scheduled_date=day,
                              expected_volunteers=3)
            brief_event(ev["id"], group["id"], [w1["id"]])
            w1_ids.append((day, ev["id"]))
        for day in days_w2:
            ev = create_event(agreement["id"], group["id"], scheduled_date=day,
                              expected_volunteers=3)
            w2_ids.append((day, ev["id"]))

        for day, eid in w1_ids:
            set_clock(f"{day}T10:00:00Z")
            complete_event(eid, group["id"])

        # w1 expired 2027-08-01; sign a second adult before W2 briefings.
        set_clock("2027-09-05T09:00:00Z")
        w2 = create_adult_waiver(agreement["id"], group["id"], name="Ben Adult",
                                 dob="1988-03-15")
        for day, eid in w2_ids:
            brief_event(eid, group["id"], [w2["id"]])
        for day, eid in w2_ids:
            set_clock(f"{day}T10:00:00Z")
            complete_event(eid, group["id"])

        set_clock("2028-05-10T09:00:00Z")
        gl = make_group_leader_headers(group["id"])
        validate_success(api.renewal_request(agreement["id"], gl), 200)
        fin = validate_success(
            api.renewal_decision(agreement["id"], {"decision": "APPROVE"}, COORD), 200)
        assert fin["status"] == "ACTIVE"
        assert fin["renewal_count"] == 1
        assert fin["standing"] == "NOT_EVALUATED"


class TestRenewalDenial:
    def test_renewal_denial_expires_agreement_and_frees_segment(self, api):
        """PRD §3.8: "Denial moves the agreement to `EXPIRED`, returns the
        segment to `AVAILABLE`, and removes any installed sign."

        Design: Corner/state_machines/renewal_denial_expires_agreement_and_frees_segment
        """
        group, segment, agreement = setup_active_agreement()
        w1 = create_adult_waiver(agreement["id"], group["id"], name="Ada Adult",
                                 dob="1990-05-01")
        events = []
        for day in ("2028-04-01", "2028-04-15", "2028-05-01"):
            ev = create_event(agreement["id"], group["id"], scheduled_date=day,
                              expected_volunteers=3)
            brief_event(ev["id"], group["id"], [w1["id"]])
            events.append((day, ev["id"]))
        for day, eid in events:
            set_clock(f"{day}T10:00:00Z")
            complete_event(eid, group["id"])

        set_clock("2028-05-10T09:00:00Z")
        gl = make_group_leader_headers(group["id"])
        validate_success(api.renewal_request(agreement["id"], gl), 200)
        fin = validate_success(
            api.renewal_decision(
                agreement["id"],
                {"decision": "DENY", "note": "area re-programmed"}, COORD), 200)
        assert fin["status"] == "EXPIRED"
        seg = validate_success(api.get_segment(segment["id"], COORD), 200)
        assert seg["status"] == "AVAILABLE"

    def test_renewal_denial_moves_agreement_to_terminal(self, api):
        """PRD §3.8: "Denial moves the agreement to `EXPIRED`, returns the
        segment to `AVAILABLE`, and removes any installed sign."
        PRD §3.2: "an agreement already in a terminal state refuses with
        `ERR_AGREEMENT_TERMINAL`."

        Design: Corner/state_machines/renewal_denial_expires_agreement_and_frees_segment
        """
        from test_helpers import ApiErrorId, validate_error

        group, segment, agreement = setup_active_agreement()
        w1 = create_adult_waiver(agreement["id"], group["id"], name="Ada Adult",
                                 dob="1990-05-01")
        events = []
        for day in ("2028-04-01", "2028-04-15", "2028-05-01"):
            ev = create_event(agreement["id"], group["id"], scheduled_date=day,
                              expected_volunteers=3)
            brief_event(ev["id"], group["id"], [w1["id"]])
            events.append((day, ev["id"]))
        for day, eid in events:
            set_clock(f"{day}T10:00:00Z")
            complete_event(eid, group["id"])

        set_clock("2028-05-10T09:00:00Z")
        gl = make_group_leader_headers(group["id"])
        validate_success(api.renewal_request(agreement["id"], gl), 200)
        fin = validate_success(
            api.renewal_decision(agreement["id"], {"decision": "DENY"}, COORD), 200)
        assert fin["status"] == "EXPIRED"
        # Terminal lockdown: terminate after EXPIRED refuses.
        resp = api.terminate_agreement(agreement["id"], {}, COORD)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_TERMINAL)
