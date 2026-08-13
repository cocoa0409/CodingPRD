"""Help-desk inquiries, specialist referrals, SLA, and performance scores."""
import pytest

from test_helpers import (ApiErrorId, create_specialist,
                          create_and_open_cycle, get_success_data,
                          log_inquiry, make_specialist_headers,
                          make_volunteer_headers, set_clock,
                          setup_cycle_with_active_volunteer,
                          setup_staffed_help_desk_shift,
                          setup_triaged_inquiry, triage_inquiry,
                          validate_error, validate_paginated, validate_success)
from test_helpers import TEST_USERS

COORD = TEST_USERS["coordinator_headers"]


class TestInquiryLoggingGates:
    def test_inquiry_logged_outside_shift_window_returns_409(self, api):
        """PRD §3.5: "The logical clock must sit inside the shift window, at
        or after `start_time` and strictly before `end_time`; logging outside
        the window fails with `ERR_OUTSIDE_SHIFT_WINDOW`."

        Design: Corner/errors/inquiry_logged_outside_shift_window_returns_409
        """
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        shift = setup_staffed_help_desk_shift(
            cycle["id"], vol["id"], start_time="2026-08-10T09:00:00Z",
            end_time="2026-08-10T12:00:00Z")
        # Clock remains at the 2026-08-01 default, before the window.
        resp = api.create_inquiry(
            shift["id"],
            {"volunteer_id": vol["id"], "subject": "Early question",
             "contact_name": "R1", "details": "before window"},
            make_volunteer_headers(vol["id"]))
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_SHIFT_WINDOW)

    def test_inquiry_on_outreach_shift_returns_409(self, api):
        """PRD §3.5: "Creating an `Inquiry` under a shift requires the
        shift's `kind` to be `HELP_DESK` (otherwise
        `ERR_SHIFT_KIND_NOT_HELP_DESK`)"

        Design: Corner/errors/inquiry_on_outreach_shift_returns_409
        """
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        shift = setup_staffed_help_desk_shift(
            cycle["id"], vol["id"], kind="OUTREACH", location="Fair",
            start_time="2026-08-15T10:00:00Z",
            end_time="2026-08-15T14:00:00Z", capacity=4,
            clock_in_window="2026-08-15T11:00:00Z")
        resp = api.create_inquiry(
            shift["id"],
            {"volunteer_id": vol["id"], "subject": "Fair question",
             "contact_name": "R1", "details": "at booth"},
            make_volunteer_headers(vol["id"]))
        validate_error(resp, ApiErrorId.ERR_SHIFT_KIND_NOT_HELP_DESK)

    def test_inquiry_without_signup_returns_409(self, api):
        """PRD §3.5: "requires the logging volunteer — identified by the
        payload's `volunteer_id`, which must match the caller's `X-User-ID`
        — to hold a `SIGNED_UP` or `COMPLETED` signup on that shift
        (otherwise `ERR_NO_SHIFT_SIGNUP`)."

        Design: Corner/state_machines/inquiry_without_signup_returns_409
        """
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        from test_helpers import create_shift
        shift = create_shift(cycle["id"],
                             start_time="2026-08-05T09:00:00Z",
                             end_time="2026-08-05T12:00:00Z")
        set_clock("2026-08-05T10:00:00Z")
        resp = api.create_inquiry(
            shift["id"],
            {"volunteer_id": vol["id"], "subject": "Walk-in question",
             "contact_name": "R1", "details": "no signup"},
            make_volunteer_headers(vol["id"]))
        validate_error(resp, ApiErrorId.ERR_NO_SHIFT_SIGNUP)

    def test_inquiry_wrong_state_errors(self, api):
        """PRD §3.5: "A coordinator triages a `LOGGED` inquiry (otherwise
        `ERR_INQUIRY_NOT_LOGGED`) by setting its `category`"
        PRD §3.5: "the logging volunteer — and only that volunteer, enforced
        by ownership (`ERR_NOT_RESOURCE_OWNER`) — answers a `TRIAGED` inquiry
        (otherwise `ERR_INQUIRY_NOT_TRIAGED`) with `answer_text`, moving it
        `TRIAGED → CLOSED`"

        Design: Corner/state_machines/inquiry_wrong_state_errors
        """
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        shift = setup_staffed_help_desk_shift(
            cycle["id"], vol["id"], clock_in_window="2026-08-05T10:00:00Z")
        inq = log_inquiry(shift["id"], vol["id"], subject="Tomato wilt",
                          details="wilting")
        triage_inquiry(inq["id"], "PLANT_DISEASE")
        resp = api.triage_inquiry(inq["id"], {"category": "SOIL"}, COORD)
        validate_error(resp, ApiErrorId.ERR_INQUIRY_NOT_LOGGED)

        get_success_data(api.answer_inquiry(
            inq["id"], {"answer_text": "fusarium; remove"},
            make_volunteer_headers(vol["id"])))
        resp = api.answer_inquiry(inq["id"], {"answer_text": "second answer"},
                                  make_volunteer_headers(vol["id"]))
        validate_error(resp, ApiErrorId.ERR_INQUIRY_NOT_TRIAGED)
        after = get_success_data(api.get_inquiry(inq["id"], COORD))
        assert after["category"] == "PLANT_DISEASE"

    def test_inquiry_follow_up_self_reference_listing(self, api):
        """PRD §3.5: "That window check is waived for follow-ups: an inquiry
        carrying `follow_up_of_id` continues an earlier inquiry, which must
        already be `CLOSED` (otherwise `ERR_FOLLOW_UP_TARGET_NOT_CLOSED`)."
        PRD §3.5: "The inquiry list may be filtered by `shift_id`,
        `volunteer_id`, `status`, `category`, and `follow_up_of_id`."

        Design: Corner/entities/inquiry_follow_up_self_reference_listing
        """
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        shift = setup_staffed_help_desk_shift(
            cycle["id"], vol["id"], clock_in_window="2026-08-05T10:00:00Z")
        inq1 = log_inquiry(shift["id"], vol["id"], subject="Tomato wilt",
                           details="wilting")
        triage_inquiry(inq1["id"], "PLANT_DISEASE")
        get_success_data(api.answer_inquiry(
            inq1["id"], {"answer_text": "Likely fusarium; remove plant"},
            make_volunteer_headers(vol["id"])))
        set_clock("2026-08-12T09:00:00Z")  # outside the original window

        resp = api.create_inquiry(
            shift["id"],
            {"volunteer_id": vol["id"], "subject": "Tomato wilt follow-up",
             "contact_name": "R1", "details": "spread to second plant",
             "follow_up_of_id": inq1["id"]},
            make_volunteer_headers(vol["id"]))
        inq2 = validate_success(resp, expected_status=201)
        assert inq2["status"] == "LOGGED"
        assert inq2["follow_up_of_id"] == inq1["id"]

        data, meta = validate_paginated(api.list_inquiries(
            COORD, params={"follow_up_of_id": inq1["id"]}))
        assert len(data) == 1
        assert data[0]["id"] == inq2["id"]
        inq1_after = get_success_data(api.get_inquiry(inq1["id"], COORD))
        assert inq1_after["status"] == "CLOSED"
        assert inq1_after["resolution"] == "ANSWERED_AT_DESK"

    def test_follow_up_on_unclosed_inquiry_returns_409(self, api):
        """PRD §3.5: "That window check is waived for follow-ups: an inquiry
        carrying `follow_up_of_id` continues an earlier inquiry, which must
        already be `CLOSED` (otherwise `ERR_FOLLOW_UP_TARGET_NOT_CLOSED`)."

        Design: Corner/errors/follow_up_on_unclosed_inquiry_returns_409
        """
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        shift, inq1 = setup_triaged_inquiry(cycle["id"], vol["id"],
                                            category="PLANT_DISEASE")
        resp = api.create_inquiry(
            shift["id"],
            {"volunteer_id": vol["id"], "subject": "wilt follow-up",
             "contact_name": "R1", "details": "spread",
             "follow_up_of_id": inq1["id"]},
            make_volunteer_headers(vol["id"]))
        validate_error(resp, ApiErrorId.ERR_FOLLOW_UP_TARGET_NOT_CLOSED)


class TestReferralCreation:
    def test_referral_requires_inquiry_triaged_error(self, api):
        """PRD §3.5: "A coordinator creates a `DiagnosisReferral` on a
        `TRIAGED` inquiry — referral requires triage, so an untriaged inquiry
        fails with `ERR_INQUIRY_NOT_TRIAGED`"

        Design: Difficulty/cross_entity_state_dependency/referral_requires_inquiry_triaged
        """
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        spec = create_specialist()
        shift = setup_staffed_help_desk_shift(
            cycle["id"], vol["id"], clock_in_window="2026-08-05T10:00:00Z")
        inq = log_inquiry(shift["id"], vol["id"])
        resp = api.create_referral(inq["id"], {"specialist_id": spec["id"]},
                                   COORD)
        validate_error(resp, ApiErrorId.ERR_INQUIRY_NOT_TRIAGED)

    def test_referral_requires_inquiry_triaged_inquiry_unchanged(self, api):
        """PRD §3.5: "A new inquiry starts `LOGGED` with `category` unset,
        `resolution` `NONE`, `answer_text` and `resolved_at` null, and
        `follow_up_of_id` absent unless supplied."
        PRD §3.5: "A coordinator creates a `DiagnosisReferral` on a `TRIAGED`
        inquiry — referral requires triage, so an untriaged inquiry fails
        with `ERR_INQUIRY_NOT_TRIAGED`"

        Design: Difficulty/cross_entity_state_dependency/referral_requires_inquiry_triaged
        """
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        spec = create_specialist()
        shift = setup_staffed_help_desk_shift(
            cycle["id"], vol["id"], clock_in_window="2026-08-05T10:00:00Z")
        inq = log_inquiry(shift["id"], vol["id"])
        api.create_referral(inq["id"], {"specialist_id": spec["id"]}, COORD)
        after = get_success_data(api.get_inquiry(inq["id"], COORD))
        assert after["status"] == "LOGGED"

    def test_explicit_referral_specialty_mismatch_returns_409(self, api):
        """PRD §3.5: "An explicit specialist must have `open_referral_count`
        below their `max_concurrent_referrals` (otherwise
        `ERR_SPECIALIST_AT_CAPACITY`) and a `specialty` equal to the
        inquiry's `category` or `GENERAL` (otherwise
        `ERR_SPECIALTY_MISMATCH`)."

        Design: Corner/errors/explicit_referral_specialty_mismatch_returns_409
        """
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        s1 = create_specialist(name="Dr. Soil", specialty="SOIL",
                               max_concurrent_referrals=5)
        _shift, inq = setup_triaged_inquiry(cycle["id"], vol["id"],
                                            category="PEST")
        resp = api.create_referral(inq["id"], {"specialist_id": s1["id"]},
                                   COORD)
        validate_error(resp, ApiErrorId.ERR_SPECIALTY_MISMATCH)

    def test_no_specialist_in_pool_returns_409(self, api):
        """PRD §3.5: "Specialty matching is two-tiered: first only
        specialists whose `specialty` equals the inquiry's `category` are
        considered; if that pool is empty, specialists with `specialty`
        `GENERAL` are considered as a fallback; if both pools are empty,
        creation fails with `ERR_NO_SPECIALIST_AVAILABLE`."

        Design: Corner/errors/no_specialist_in_pool_returns_409
        """
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        create_specialist(name="Dr. Soil", specialty="SOIL",
                          max_concurrent_referrals=5)
        _shift, inq = setup_triaged_inquiry(cycle["id"], vol["id"],
                                            category="PEST")
        resp = api.create_referral(inq["id"], {}, COORD)
        validate_error(resp, ApiErrorId.ERR_NO_SPECIALIST_AVAILABLE)
        after = get_success_data(api.get_inquiry(inq["id"], COORD))
        assert after["status"] == "TRIAGED"

    def test_specialist_capacity_beats_specialty_match(self, api):
        """PRD §2.9: "... (10) uniqueness, capacity, and overlap conflicts —
        the duplicate, fullness, conflict, and limit error families; (11)
        clock and window rules ...; and (12) cross-entity reference
        consistency — `ERR_SPECIALTY_MISMATCH`, ..."

        Design: Difficulty/priority_pair_validation_conflict/specialist_capacity_beats_specialty_match
        """
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        s1 = create_specialist(name="Dr. Soil", specialty="SOIL",
                               max_concurrent_referrals=1)
        shift, inq1 = setup_triaged_inquiry(cycle["id"], vol["id"],
                                            category="SOIL")
        ref1 = get_success_data(api.create_referral(inq1["id"], {}, COORD))
        assert ref1["specialist_id"] == s1["id"]  # S1 now at 1/1
        inq2 = log_inquiry(shift["id"], vol["id"], subject="Aphids",
                           contact_name="Resident Two",
                           details="Gray cluster on kale")
        triage_inquiry(inq2["id"], "PEST")
        # Explicit pick of S1: at capacity (tier 10) AND mismatched (tier 12).
        resp = api.create_referral(inq2["id"], {"specialist_id": s1["id"]},
                                   COORD)
        validate_error(resp, ApiErrorId.ERR_SPECIALIST_AT_CAPACITY)

    def test_specialist_capacity_beats_specialty_match_control_mismatch(
            self, api):
        """PRD §3.5: "An explicit specialist must have `open_referral_count`
        below their `max_concurrent_referrals` (otherwise
        `ERR_SPECIALIST_AT_CAPACITY`) and a `specialty` equal to the
        inquiry's `category` or `GENERAL` (otherwise
        `ERR_SPECIALTY_MISMATCH`)."

        Design: Difficulty/priority_pair_validation_conflict/specialist_capacity_beats_specialty_match
        """
        # Control leg of the same pair: the specialist is specialty-
        # mismatched but has spare capacity, so tier 10 passes and tier 12
        # surfaces ERR_SPECIALTY_MISMATCH.
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        s1 = create_specialist(name="Dr. Soil", specialty="SOIL",
                               max_concurrent_referrals=5)
        _shift, inq = setup_triaged_inquiry(cycle["id"], vol["id"],
                                            category="PEST")
        resp = api.create_referral(inq["id"], {"specialist_id": s1["id"]},
                                   COORD)
        validate_error(resp, ApiErrorId.ERR_SPECIALTY_MISMATCH)

    def test_second_referral_on_referred_inquiry_returns_409(self, api):
        """PRD §3.5: "an inquiry may have at most one referral in `OPEN`,
        `IN_REVIEW`, or `RETURNED` status at a time; a second attempt fails
        with `ERR_REFERRAL_ALREADY_OPEN`, because a `RETURNED` referral must
        be reassigned rather than replaced."

        Design: Corner/errors/second_referral_on_referred_inquiry_returns_409
        """
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        create_specialist()
        _shift, inq = setup_triaged_inquiry(cycle["id"], vol["id"])
        get_success_data(api.create_referral(inq["id"], {}, COORD))
        resp = api.create_referral(inq["id"], {}, COORD)
        validate_error(resp, ApiErrorId.ERR_REFERRAL_ALREADY_OPEN)
        data, _meta = validate_paginated(api.list_referrals(
            COORD, params={"inquiry_id": inq["id"]}))
        assert len(data) == 1

    def test_referral_auto_select_least_open_then_created_at(self, api):
        """PRD §3.5: "Ranking is by `open_referral_count` ascending, then
        `rolling_score` descending, then `created_at` ascending, and the
        top-ranked specialist is assigned."

        Design: Corner/cross_cutting_complexity_layers/referral_auto_select_least_open_then_created_at
        """
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        s1 = create_specialist(name="Dr. Pest One")
        s2 = create_specialist(name="Dr. Pest Two")
        shift = setup_staffed_help_desk_shift(
            cycle["id"], vol["id"], clock_in_window="2026-08-05T10:00:00Z")
        inqs = []
        for i in range(3):
            inq = log_inquiry(shift["id"], vol["id"], subject=f"Q{i+1}",
                              contact_name=f"R{i+1}", details=f"d{i+1}")
            triage_inquiry(inq["id"], "PEST")
            inqs.append(inq)
        r1 = get_success_data(api.create_referral(inqs[0]["id"], {}, COORD))
        r2 = get_success_data(api.create_referral(inqs[1]["id"], {}, COORD))
        r3 = get_success_data(api.create_referral(inqs[2]["id"], {}, COORD))
        # 0/0 tie -> created first; then S2 has 0 < 1; then 1/1 -> S1.
        assert r1["specialist_id"] == s1["id"]
        assert r2["specialist_id"] == s2["id"]
        assert r3["specialist_id"] == s1["id"]


class TestReferralWorkLoop:
    def test_referral_wrong_state_errors(self, api):
        """PRD §3.5: "Answering requires `IN_REVIEW` (otherwise
        `ERR_REFERRAL_NOT_IN_REVIEW`) and the same ownership check"
        PRD §3.5: "A coordinator then reassignment-loops the referral
        `RETURNED → OPEN` — valid only from `RETURNED` (otherwise
        `ERR_REFERRAL_NOT_RETURNED`)"
        PRD §3.5: "Starting review requires the referral to be `OPEN`
        (otherwise `ERR_REFERRAL_NOT_OPEN`) and the caller to be the assignee
        (`ERR_NOT_RESOURCE_OWNER`), moving it `OPEN → IN_REVIEW`."

        Design: Corner/state_machines/referral_wrong_state_errors
        """
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        s1 = create_specialist()
        _shift, inq = setup_triaged_inquiry(cycle["id"], vol["id"])
        ref = get_success_data(api.create_referral(inq["id"], {}, COORD))
        assert ref["specialist_id"] == s1["id"]
        s1_hdrs = make_specialist_headers(s1["id"])

        resp = api.answer_referral(ref["id"], {"diagnosis_text": "premature"},
                                   s1_hdrs)
        validate_error(resp, ApiErrorId.ERR_REFERRAL_NOT_IN_REVIEW)

        resp = api.reassign_referral(ref["id"], {}, COORD)
        validate_error(resp, ApiErrorId.ERR_REFERRAL_NOT_RETURNED)

        get_success_data(api.start_review(ref["id"], s1_hdrs))
        resp = api.start_review(ref["id"], s1_hdrs)
        validate_error(resp, ApiErrorId.ERR_REFERRAL_NOT_OPEN)
        after = get_success_data(api.get_referral(ref["id"], COORD))
        assert after["status"] == "IN_REVIEW"

    def test_referral_return_reassign_loop_assignee_sequence(self, api):
        """PRD §3.5: "On reassignment, the referral's `last_specialist_id` is
        removed from the candidate pool before ranking."
        PRD §3.5: "Ranking is by `open_referral_count` ascending, then
        `rolling_score` descending, then `created_at` ascending, and the
        top-ranked specialist is assigned."

        Design: Difficulty/non_linear_state_machine/referral_return_reassign_loop
        """
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        s1 = create_specialist(name="Dr. Pest One", max_concurrent_referrals=2)
        s2 = create_specialist(name="Dr. Pest Two", max_concurrent_referrals=2)
        _shift, inq = setup_triaged_inquiry(cycle["id"], vol["id"])

        ref = get_success_data(api.create_referral(inq["id"], {}, COORD))
        assert ref["specialist_id"] == s1["id"]  # 0/0 tie -> created_at ASC
        s1_hdrs = make_specialist_headers(s1["id"])
        get_success_data(api.start_review(ref["id"], s1_hdrs))
        get_success_data(api.return_referral(
            ref["id"], {"return_reason": "needs soil context"}, s1_hdrs))
        reassigned = get_success_data(api.reassign_referral(ref["id"], {},
                                                            COORD))
        assert reassigned["specialist_id"] == s2["id"]

    def test_referral_return_reassign_loop_terminal_answer(self, api):
        """PRD §3.5: "Answering moves the referral to `ANSWERED`, its
        terminal state, cascades the inquiry `REFERRED → CLOSED` with
        `resolution` `SPECIALIST_DIAGNOSIS` and `resolved_at` stamped"
        PRD §3.5: "Reassignment increments the new assignee's
        `open_referral_count`, increments `reassignment_count`, and refreshes
        `due_at` to the logical clock plus forty-eight hours — a fresh SLA
        per reassignment."

        Design: Difficulty/non_linear_state_machine/referral_return_reassign_loop
        """
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        s1 = create_specialist(name="Dr. Pest One", max_concurrent_referrals=2)
        s2 = create_specialist(name="Dr. Pest Two", max_concurrent_referrals=2)
        _shift, inq = setup_triaged_inquiry(cycle["id"], vol["id"])
        ref = get_success_data(api.create_referral(inq["id"], {}, COORD))
        get_success_data(api.start_review(
            ref["id"], make_specialist_headers(s1["id"])))
        get_success_data(api.return_referral(
            ref["id"], {"return_reason": "needs soil context"},
            make_specialist_headers(s1["id"])))
        get_success_data(api.reassign_referral(ref["id"], {}, COORD))
        s2_hdrs = make_specialist_headers(s2["id"])
        get_success_data(api.start_review(ref["id"], s2_hdrs))
        answered = get_success_data(api.answer_referral(
            ref["id"], {"diagnosis_text": "Cucumber beetle; row cover"},
            s2_hdrs))
        assert answered["status"] == "ANSWERED"
        assert answered["reassignment_count"] == 1
        assert answered["answered_by_specialist_id"] == s2["id"]

        inq_after = get_success_data(api.get_inquiry(inq["id"], COORD))
        assert inq_after["status"] == "CLOSED"
        assert inq_after["resolution"] == "SPECIALIST_DIAGNOSIS"

        s1_after = get_success_data(api.get_specialist(s1["id"], COORD))
        assert s1_after["returned_count"] == 1
        assert s1_after["open_referral_count"] == 0
        s2_after = get_success_data(api.get_specialist(s2["id"], COORD))
        assert s2_after["answered_count"] == 1
        assert s2_after["open_referral_count"] == 0

    def test_specialist_open_count_conservation_assign_answer_return(
            self, api):
        """PRD §3.5: "Creation moves the inquiry `TRIAGED → REFERRED`,
        increments the assignee's `open_referral_count` by one"
        PRD §3.5: "decrements the specialist's `open_referral_count`, and
        increments `answered_count`."
        PRD §3.5: "the server stamps `returned_at` and
        `returned_by_specialist_id`, decrements `open_referral_count`,
        increments `returned_count`, copies the assignee into
        `last_specialist_id`, clears `specialist_id` to null, moves the
        referral to `RETURNED`, and recomputes both scores."

        Design: Difficulty/compensating_invariant/specialist_open_count_conservation_assign_answer_return
        """
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        s1 = create_specialist(name="Dr. Pest One")
        s2 = create_specialist(name="Dr. Pest Two")
        shift = setup_staffed_help_desk_shift(
            cycle["id"], vol["id"], clock_in_window="2026-08-05T10:00:00Z")
        inq1 = log_inquiry(shift["id"], vol["id"], subject="Aphids",
                           contact_name="R1", details="kale")
        inq2 = log_inquiry(shift["id"], vol["id"], subject="Borer",
                           contact_name="R2", details="squash")
        triage_inquiry(inq1["id"], "PEST")
        triage_inquiry(inq2["id"], "PEST")

        ref1 = get_success_data(api.create_referral(inq1["id"], {}, COORD))
        assert ref1["specialist_id"] == s1["id"]
        s1_hdrs = make_specialist_headers(s1["id"])
        get_success_data(api.start_review(ref1["id"], s1_hdrs))
        get_success_data(api.answer_referral(
            ref1["id"], {"diagnosis_text": "blast with water"}, s1_hdrs))

        ref2 = get_success_data(api.create_referral(inq2["id"], {}, COORD))
        # After the answer, both pools tie at 0 open -> created_at ASC.
        assert ref2["specialist_id"] == s1["id"]
        get_success_data(api.start_review(ref2["id"], s1_hdrs))
        get_success_data(api.return_referral(
            ref2["id"], {"return_reason": "ambiguous photo"}, s1_hdrs))
        reassigned = get_success_data(api.reassign_referral(ref2["id"], {},
                                                            COORD))
        # Reassign pool excludes the returning specialist S1.
        assert reassigned["specialist_id"] == s2["id"]

        s1_after = get_success_data(api.get_specialist(s1["id"], COORD))
        assert s1_after["open_referral_count"] == 0
        assert s1_after["answered_count"] == 1
        assert s1_after["returned_count"] == 1
        s2_after = get_success_data(api.get_specialist(s2["id"], COORD))
        assert s2_after["open_referral_count"] == 1

    def test_specialist_open_count_global_invariant(self, api):
        """PRD §2.10: "Derived fields — a cycle's `accepted_count` and
        `enrolled_count`, a shift's `filled_count`, a specialist's
        `open_referral_count`, `answered_count`, `late_referral_count`, and
        `returned_count`, a record's provisional and official totals, and a
        volunteer's recognition fields — are recomputed on every triggering
        event rather than accumulated loosely, so a read always reflects the
        full event history."

        Design: Difficulty/compensating_invariant/specialist_open_count_conservation_assign_answer_return
        """
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        s1 = create_specialist(name="Dr. Pest One")
        s2 = create_specialist(name="Dr. Pest Two")
        shift = setup_staffed_help_desk_shift(
            cycle["id"], vol["id"], clock_in_window="2026-08-05T10:00:00Z")
        inq1 = log_inquiry(shift["id"], vol["id"], subject="Aphids",
                           contact_name="R1", details="kale")
        inq2 = log_inquiry(shift["id"], vol["id"], subject="Borer",
                           contact_name="R2", details="squash")
        triage_inquiry(inq1["id"], "PEST")
        triage_inquiry(inq2["id"], "PEST")
        ref1 = get_success_data(api.create_referral(inq1["id"], {}, COORD))
        s1_hdrs = make_specialist_headers(s1["id"])
        get_success_data(api.start_review(ref1["id"], s1_hdrs))
        get_success_data(api.answer_referral(
            ref1["id"], {"diagnosis_text": "blast with water"}, s1_hdrs))
        ref2 = get_success_data(api.create_referral(inq2["id"], {}, COORD))
        get_success_data(api.start_review(ref2["id"], s1_hdrs))
        get_success_data(api.return_referral(
            ref2["id"], {"return_reason": "ambiguous photo"}, s1_hdrs))
        get_success_data(api.reassign_referral(ref2["id"], {}, COORD))

        s1_after = get_success_data(api.get_specialist(s1["id"], COORD))
        s2_after = get_success_data(api.get_specialist(s2["id"], COORD))
        open_refs, _meta = validate_paginated(api.list_referrals(
            COORD, params={"status": "OPEN"}))
        in_review_refs, _meta2 = validate_paginated(api.list_referrals(
            COORD, params={"status": "IN_REVIEW"}))
        live = len(open_refs) + len(in_review_refs)
        assert s1_after["open_referral_count"] + \
            s2_after["open_referral_count"] == live


class TestReferralSlaBoundary:
    def test_referral_sla_due_at_exact_equality_on_time(self, api):
        """PRD §3.5: "An answer is late when `answered_at` is strictly later
        than `due_at` — an answer exactly at `due_at` is on time — and a late
        answer also increments `late_referral_count`."
        PRD §3.5: "sets the referral's `due_at` to the logical clock plus
        forty-eight hours"

        Design: Difficulty/boundary_precision_check/referral_sla_due_at_exact_equality
        """
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        spec = create_specialist()
        _shift, inq = setup_triaged_inquiry(cycle["id"], vol["id"])
        ref = get_success_data(api.create_referral(inq["id"], {}, COORD))
        # Created at 2026-08-05T10:00:00Z -> due exactly 48h later.
        assert ref["due_at"] == "2026-08-07T10:00:00Z"
        get_success_data(api.start_review(
            ref["id"], make_specialist_headers(spec["id"])))
        set_clock("2026-08-07T10:00:00Z")
        get_success_data(api.answer_referral(
            ref["id"], {"diagnosis_text": "Blast with water"},
            make_specialist_headers(spec["id"])))
        spec_after = get_success_data(api.get_specialist(spec["id"], COORD))
        assert spec_after["late_referral_count"] == 0

    def test_referral_sla_one_second_late_counts(self, api):
        """PRD §3.5: "An answer is late when `answered_at` is strictly later
        than `due_at` — an answer exactly at `due_at` is on time — and a late
        answer also increments `late_referral_count`."

        Design: Difficulty/boundary_precision_check/referral_sla_due_at_exact_equality
        """
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        spec = create_specialist()
        _shift, inq = setup_triaged_inquiry(cycle["id"], vol["id"])
        ref = get_success_data(api.create_referral(inq["id"], {}, COORD))
        get_success_data(api.start_review(
            ref["id"], make_specialist_headers(spec["id"])))
        set_clock("2026-08-07T10:00:01Z")  # one second past due_at
        get_success_data(api.answer_referral(
            ref["id"], {"diagnosis_text": "Slit stem, remove borer"},
            make_specialist_headers(spec["id"])))
        spec_after = get_success_data(api.get_specialist(spec["id"], COORD))
        assert spec_after["answered_count"] == 1
        assert spec_after["late_referral_count"] == 1


class TestSpecialistPerformanceWindows:
    def test_specialist_score_rolling_vs_lifetime_counters(self, api):
        """PRD §3.5: "the server stamps `answered_at` from the logical clock
        and `answered_by_specialist_id` with the assignee, decrements the
        specialist's `open_referral_count`, and increments `answered_count`."
        PRD §3.5: "the server stamps `returned_at` and
        `returned_by_specialist_id`, decrements `open_referral_count`,
        increments `returned_count`"

        Design: Difficulty/dual_variant_calc/specialist_score_rolling_vs_lifetime
        """
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        spec = create_specialist()
        shift1 = setup_staffed_help_desk_shift(
            cycle["id"], vol["id"],
            start_time="2026-08-05T09:00:00Z",
            end_time="2026-08-05T12:00:00Z",
            clock_in_window="2026-08-05T10:00:00Z")
        # R1: answered late (2026-08-07T10:00:01Z > due 2026-08-07T10:00:00Z)
        inq1 = log_inquiry(shift1["id"], vol["id"],
                           subject="Cucumber beetles",
                           contact_name="Resident One",
                           details="Striped beetles on cucurbits")
        triage_inquiry(inq1["id"], "PEST")
        ref1 = get_success_data(api.create_referral(inq1["id"], {}, COORD))
        get_success_data(api.start_review(
            ref1["id"], make_specialist_headers(spec["id"])))
        # R2: returned on 2026-08-06
        shift2 = setup_staffed_help_desk_shift(
            cycle["id"], vol["id"],
            start_time="2026-08-06T09:00:00Z",
            end_time="2026-08-06T12:00:00Z")
        set_clock("2026-08-06T10:00:00Z")
        inq2 = log_inquiry(shift2["id"], vol["id"], subject="Aphids on kale",
                           contact_name="Resident Two",
                           details="Gray aphid cluster")
        triage_inquiry(inq2["id"], "PEST")
        ref2 = get_success_data(api.create_referral(inq2["id"], {}, COORD))
        get_success_data(api.start_review(
            ref2["id"], make_specialist_headers(spec["id"])))
        get_success_data(api.return_referral(
            ref2["id"], {"return_reason": "needs lab culture"},
            make_specialist_headers(spec["id"])))
        set_clock("2026-08-07T10:00:01Z")
        get_success_data(api.answer_referral(
            ref1["id"], {"diagnosis_text": "Cucumber beetle; use row cover"},
            make_specialist_headers(spec["id"])))
        # R3: answered on time at 2026-11-20
        # (setup_staffed_help_desk_shift already signs the volunteer up;
        # the helper's internal signup runs while the clock is at
        # 2026-08-07T10:00:01Z, strictly before the shift start, per §3.4.)
        shift3 = setup_staffed_help_desk_shift(
            cycle["id"], vol["id"],
            start_time="2026-11-20T09:00:00Z",
            end_time="2026-11-20T12:00:00Z")
        set_clock("2026-11-20T08:00:00Z")
        set_clock("2026-11-20T10:00:00Z")
        inq3 = log_inquiry(shift3["id"], vol["id"], subject="Boxwood psyllid",
                           contact_name="Resident Three",
                           details="Cupped leaves")
        triage_inquiry(inq3["id"], "PEST")
        ref3 = get_success_data(api.create_referral(inq3["id"], {}, COORD))
        get_success_data(api.start_review(
            ref3["id"], make_specialist_headers(spec["id"])))
        set_clock("2026-11-20T11:00:00Z")
        get_success_data(api.answer_referral(
            ref3["id"], {"diagnosis_text": "Boxwood psyllid; prune tips"},
            make_specialist_headers(spec["id"])))

        spec_after = get_success_data(api.get_specialist(spec["id"], COORD))
        assert spec_after["answered_count"] == 2
        assert spec_after["late_referral_count"] == 1
        assert spec_after["returned_count"] == 1

    def test_specialist_score_rolling_vs_lifetime_scores(self, api):
        """PRD §3.5: "Each late event costs five points and each return costs
        three. The lifetime variant, exposed as `lifetime_score`, penalizes
        events over all time; the rolling variant, exposed as
        `rolling_score`, penalizes only events whose resolution timestamp
        falls on or after the instant exactly ninety days before the current
        logical clock"

        Design: Difficulty/dual_variant_calc/specialist_score_rolling_vs_lifetime
        """
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        spec = create_specialist()
        shift1 = setup_staffed_help_desk_shift(
            cycle["id"], vol["id"],
            start_time="2026-08-05T09:00:00Z",
            end_time="2026-08-05T12:00:00Z",
            clock_in_window="2026-08-05T10:00:00Z")
        inq1 = log_inquiry(shift1["id"], vol["id"],
                           subject="Cucumber beetles",
                           contact_name="Resident One",
                           details="Striped beetles on cucurbits")
        triage_inquiry(inq1["id"], "PEST")
        ref1 = get_success_data(api.create_referral(inq1["id"], {}, COORD))
        get_success_data(api.start_review(
            ref1["id"], make_specialist_headers(spec["id"])))
        shift2 = setup_staffed_help_desk_shift(
            cycle["id"], vol["id"],
            start_time="2026-08-06T09:00:00Z",
            end_time="2026-08-06T12:00:00Z")
        set_clock("2026-08-06T10:00:00Z")
        inq2 = log_inquiry(shift2["id"], vol["id"], subject="Aphids on kale",
                           contact_name="Resident Two",
                           details="Gray aphid cluster")
        triage_inquiry(inq2["id"], "PEST")
        ref2 = get_success_data(api.create_referral(inq2["id"], {}, COORD))
        get_success_data(api.start_review(
            ref2["id"], make_specialist_headers(spec["id"])))
        get_success_data(api.return_referral(
            ref2["id"], {"return_reason": "needs lab culture"},
            make_specialist_headers(spec["id"])))
        set_clock("2026-08-07T10:00:01Z")
        get_success_data(api.answer_referral(
            ref1["id"], {"diagnosis_text": "Cucumber beetle; use row cover"},
            make_specialist_headers(spec["id"])))
        shift3 = setup_staffed_help_desk_shift(
            cycle["id"], vol["id"],
            start_time="2026-11-20T09:00:00Z",
            end_time="2026-11-20T12:00:00Z")
        # NOTE: setup_staffed_help_desk_shift already signed the volunteer up
        # (at the then-current clock, strictly before the shift start, per
        # §3.4); a second sign_up here would be a duplicate.
        set_clock("2026-11-20T08:00:00Z")
        set_clock("2026-11-20T10:00:00Z")
        inq3 = log_inquiry(shift3["id"], vol["id"], subject="Boxwood psyllid",
                           contact_name="Resident Three",
                           details="Cupped leaves")
        triage_inquiry(inq3["id"], "PEST")
        ref3 = get_success_data(api.create_referral(inq3["id"], {}, COORD))
        get_success_data(api.start_review(
            ref3["id"], make_specialist_headers(spec["id"])))
        set_clock("2026-11-20T11:00:00Z")
        get_success_data(api.answer_referral(
            ref3["id"], {"diagnosis_text": "Boxwood psyllid; prune tips"},
            make_specialist_headers(spec["id"])))

        spec_after = get_success_data(api.get_specialist(spec["id"], COORD))
        # Rolling (90 days back from 2026-11-20T11:00:00Z): the August late
        # answer and return fall outside the window -> no penalty.
        assert spec_after["rolling_score"] == 100
        # Lifetime: 100 - 5*1 late - 3*1 returned = 92.
        assert spec_after["lifetime_score"] == 92
        assert spec_after["rolling_score"] != spec_after["lifetime_score"]
