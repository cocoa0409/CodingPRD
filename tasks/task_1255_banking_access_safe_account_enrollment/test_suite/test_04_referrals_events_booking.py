"""Participant documentation, referral intake, event scheduling, and the
booking lifecycle (book / unbook / cancel / capacity / roster)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, make_institution_officer_headers,
    create_participant_payload, create_event_payload,
    create_participant, update_documents, create_referral,
    referral_docs_complete, book_referral,
    setup_certified_institution, setup_documented_participant,
    setup_referral_docs_complete, setup_event_with_referrals,
    create_event, set_clock, run_ops_epoch,
)

ADMIN = TEST_USERS["coalition_admin_headers"]
NAV = TEST_USERS["agency_navigator_headers"]


class TestDocumentation:
    def test_docs_complete_flips_true_after_documents_patch(self, api):
        """PRD §3.3: "The `docs_complete` flag becomes true exactly when the participant holds at least one identity document — `STATE_ID`, `MATRICULA_CONSULAR`, `MUNICIPAL_ID`, or `FOREIGN_PASSPORT` — in `VERIFIED` status and also holds a `VERIFIED` `PROOF_OF_ADDRESS`."
        PRD §3.4: "Otherwise, if `docs_complete` is true, the stage is `DOCS_READY`."

        Design: Corner/entities/participant_docs_complete_computed
        """
        p = create_participant(id_documents=[
            {"doc_type": "MATRICULA_CONSULAR", "status": "SUBMITTED"},
            {"doc_type": "PROOF_OF_ADDRESS", "status": "VERIFIED"},
        ])
        assert p["docs_complete"] is False, "identity doc only SUBMITTED"

        updated = update_documents(p["id"], [
            {"doc_type": "MATRICULA_CONSULAR", "status": "VERIFIED"},
            {"doc_type": "PROOF_OF_ADDRESS", "status": "VERIFIED"},
        ])
        assert updated["docs_complete"] is True
        assert updated["pipeline_stage"] == "DOCS_READY", (
            "recomputed on the same response — immediate consistency"
        )

    def test_docs_complete_gate_blocks_referral_advance(self, api):
        """PRD §3.5: "Before booking, the referral must have been advanced from `DOCS_PENDING` to `DOCS_COMPLETE` via the docs-complete capability, which requires the referral to be `DOCS_PENDING` (`ERR_INVALID_STATE` otherwise) and the participant's `docs_complete` to be true — a participant still missing verified documents yields `ERR_DOCS_INCOMPLETE`."

        Design: Corner/validations/docs_complete_requires_verified_docs
        """
        p = create_participant(id_documents=[
            {"doc_type": "MATRICULA_CONSULAR", "status": "SUBMITTED"},
            {"doc_type": "PROOF_OF_ADDRESS", "status": "VERIFIED"},
        ])
        ref = create_referral(p["id"])
        resp = api.referral_docs_complete(ref["id"], NAV)
        validate_error(resp, ApiErrorId.ERR_DOCS_INCOMPLETE)
        referral = get_success_data(api.get_referral(ref["id"], NAV))
        assert referral["status"] == "DOCS_PENDING"


class TestReferralIntake:
    def test_referral_starts_docs_pending_and_moves_pipeline(self, api):
        """PRD §3.3: "A new referral lands in `DOCS_PENDING`, and the participant's `pipeline_stage` is recomputed."
        PRD §3.4: "Otherwise, if any referral is `DOCS_PENDING` or `DOCS_COMPLETE`, the stage is `REFERRED`."

        Design: Corner/state_machines/referral_initial_state_docs_pending
        """
        p = create_participant()
        resp = api.create_referral(
            {"participant_id": p["id"], "created_via": "NAVIGATOR"}, NAV
        )
        data = validate_success(resp, 201)
        assert data["status"] == "DOCS_PENDING"
        assert data.get("booked_event_id") is None
        participant = get_success_data(api.get_participant(p["id"], NAV))
        assert participant["pipeline_stage"] == "REFERRED"


class TestEventWindows:
    def test_window_conflict_same_venue_only(self, api):
        """PRD §3.5: "Two events at the same institution and `venue_code` may not overlap: a new event conflicts with an existing `SCHEDULED` event when the new `starts_at` falls before the existing `ends_at` and the existing `starts_at` falls before the new `ends_at`, surfacing `ERR_EVENT_WINDOW_CONFLICT`; because windows are half-open, adjacency — one event's `starts_at` exactly equal to another's `ends_at` — does not conflict."

        Design: Corner/validations/event_window_conflict_same_venue_only
        """
        ctx = setup_certified_institution()
        inst_id = ctx["institution"]["id"]
        create_event(inst_id, venue_code="BR-1",
                     starts_at="2026-05-10T09:00:00Z", ends_at="2026-05-10T13:00:00Z")

        adjacent = api.create_account_opening_event(
            create_event_payload(inst_id, venue_code="BR-1",
                                 starts_at="2026-05-10T13:00:00Z",
                                 ends_at="2026-05-10T17:00:00Z"),
            make_institution_officer_headers(inst_id),
        )
        validate_success(adjacent, 201)  # adjacency allowed (half-open)

        overlap = api.create_account_opening_event(
            create_event_payload(inst_id, venue_code="BR-1",
                                 starts_at="2026-05-10T12:00:00Z",
                                 ends_at="2026-05-10T15:00:00Z"),
            make_institution_officer_headers(inst_id),
        )
        validate_error(overlap, ApiErrorId.ERR_EVENT_WINDOW_CONFLICT)

        other_venue = api.create_account_opening_event(
            create_event_payload(inst_id, venue_code="BR-2",
                                 starts_at="2026-05-10T12:00:00Z",
                                 ends_at="2026-05-10T15:00:00Z"),
            make_institution_officer_headers(inst_id),
        )
        validate_success(other_venue, 201)  # overlap scope includes venue_code


class TestEventRbac:
    def test_officer_cannot_create_event_for_other_institution(self, api):
        """PRD §3.5: "An `InstitutionOfficer` schedules an **AccountOpeningEvent** by supplying the `institution_id` of their own institution — a mismatch between the acting officer's identity and the supplied `institution_id` is rejected with `ERR_UNAUTHORIZED_ROLE`"
        PRD §2.1: "When `X-User-Role` is `InstitutionOfficer`, `X-User-ID` is the `id` of the acting `PartnerInstitution`; any ownership check on a resource that references an institution compares the resource's `institution_id` field to `X-User-ID`."

        Design: Corner/rbac/officer_cannot_create_event_for_other_institution
        """
        a = setup_certified_institution(legal_name="Harbor CU")
        b = setup_certified_institution(legal_name="Metro Bank", charter_type="BANK",
                                        standard_code="BO-2026-B")
        resp = api.create_account_opening_event(
            create_event_payload(b["institution"]["id"]),
            make_institution_officer_headers(a["institution"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        _, meta = validate_paginated(
            api.list_account_opening_events(
                ADMIN, params={"institution_id": b["institution"]["id"]}
            )
        )
        assert meta["total_count"] == 0, "no event row may be created for institution B"


class TestBooking:
    def test_book_from_docs_pending_rejected(self, api):
        """PRD §3.5: "The booking itself requires the referral to be `DOCS_COMPLETE`, the target event to be `SCHEDULED` (`ERR_EVENT_NOT_BOOKABLE` otherwise), the event's institution to be `CERTIFIED` (`ERR_INSTITUTION_NOT_CERTIFIED` otherwise), and the event to have a free seat"
        PRD §2.10: "State-machine legality is fifth — a target resource not in a state from which the requested transition exists surfaces `ERR_INVALID_STATE`."

        Design: Corner/state_machines/book_from_docs_pending_rejected
        """
        ctx = setup_certified_institution()
        event = create_event(ctx["institution"]["id"])
        p = create_participant()  # no verified docs; referral stays DOCS_PENDING
        ref = create_referral(p["id"])

        resp = api.book_referral(ref["id"], {"event_id": event["id"]}, NAV)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        event_after = get_success_data(api.get_account_opening_event(event["id"], ADMIN))
        assert event_after["booked_count"] == 0, "no seat is consumed"

    def test_book_to_cancelled_event_rejected(self, api):
        """PRD §3.5: "The booking itself requires the referral to be `DOCS_COMPLETE`, the target event to be `SCHEDULED` (`ERR_EVENT_NOT_BOOKABLE` otherwise), the event's institution to be `CERTIFIED` (`ERR_INSTITUTION_NOT_CERTIFIED` otherwise), and the event to have a free seat"

        Design: Corner/errors/book_to_cancelled_event_rejected
        """
        ctx = setup_certified_institution()
        inst_id = ctx["institution"]["id"]
        event = create_event(inst_id)
        get_success_data(api.cancel_account_opening_event(
            event["id"], make_institution_officer_headers(inst_id)
        ))
        pr = setup_referral_docs_complete()

        resp = api.book_referral(pr["referral"]["id"], {"event_id": event["id"]}, NAV)
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_BOOKABLE)
        referral = get_success_data(api.get_referral(pr["referral"]["id"], NAV))
        assert referral["status"] == "DOCS_COMPLETE"
        assert referral.get("booked_event_id") is None

    def test_third_booking_at_capacity_rejected(self, api):
        """PRD §3.5: "admission requires `booked_count` strictly below `capacity`, and a booking attempted when `booked_count` equals `capacity` is rejected with `ERR_EVENT_FULL`."

        Design: Corner/cross_cutting_layers/event_full_boundary_third_booking_rejected
        """
        ctx = setup_event_with_referrals(num_participants=3, capacity=2)
        event_id = ctx["event"]["id"]
        r1, r2, r3 = [r["id"] for r in ctx["referrals"]]

        book_referral(r1, event_id)
        book_referral(r2, event_id)
        resp = api.book_referral(r3, {"event_id": event_id}, NAV)
        validate_error(resp, ApiErrorId.ERR_EVENT_FULL)

        event = get_success_data(api.get_account_opening_event(event_id, ADMIN))
        assert event["booked_count"] == 2
        referral3 = get_success_data(api.get_referral(r3, NAV))
        assert referral3["status"] == "DOCS_COMPLETE"


class TestEventSeatConservation:
    def test_two_bookings_fill_event_exactly(self, api):
        """PRD §2.8: "Second, event seats are conserved: an event's `booked_count` plus its remaining seats always equals `capacity`, and a book followed by an unbook restores `booked_count` exactly."
        PRD §3.5: "A successful booking records the event on the referral's `booked_event_id`, increments the event's `booked_count` by one, and recomputes the participant's `pipeline_stage`."

        Design: Difficulty/compensating_invariant/event_seats_book_unbook_conserved
        """
        ctx = setup_event_with_referrals(num_participants=2, capacity=2)
        event_id = ctx["event"]["id"]
        r1, r2 = [r["id"] for r in ctx["referrals"]]

        book_referral(r1, event_id)
        book_referral(r2, event_id)
        event = get_success_data(api.get_account_opening_event(event_id, ADMIN))
        assert event["booked_count"] == 2, "booked_count == capacity fills the event"

        api.unbook_referral(r1, NAV)
        event = get_success_data(api.get_account_opening_event(event_id, ADMIN))
        assert event["booked_count"] == 1, "unbook restores exactly one seat"

    def test_unbook_restores_roster_and_referral_states(self, api):
        """PRD §3.5: "Unbooking reverses the act — the referral returns from `BOOKED` to `DOCS_COMPLETE` (any other starting status yields `ERR_INVALID_STATE`), `booked_event_id` is cleared, the event's `booked_count` is decremented so the seat is restored, and the pipeline stage is recomputed."
        PRD §3.5: "An event's roster — the referrals whose `booked_event_id` names the event — is retrievable by coalition staff, the hosting officer, and navigators."

        Design: Difficulty/compensating_invariant/event_seats_book_unbook_conserved
        """
        ctx = setup_event_with_referrals(num_participants=2, capacity=2)
        event_id = ctx["event"]["id"]
        r1, r2 = [r["id"] for r in ctx["referrals"]]
        book_referral(r1, event_id)
        book_referral(r2, event_id)
        api.unbook_referral(r1, NAV)

        roster, meta = validate_paginated(
            api.list_event_referrals(event_id, make_institution_officer_headers(
                ctx["institution"]["id"]))
        )
        assert len(roster) == 1 and roster[0]["id"] == r2
        assert roster[0]["status"] == "BOOKED"
        assert get_success_data(api.get_referral(r1, NAV))["status"] == "DOCS_COMPLETE"
        assert get_success_data(api.get_referral(r2, NAV))["status"] == "BOOKED"


class TestEventRoster:
    def test_roster_lists_currently_booked_referrals(self, api):
        """PRD §3.5: "An event's roster — the referrals whose `booked_event_id` names the event — is retrievable by coalition staff, the hosting officer, and navigators."

        Design: Corner/endpoints/event_roster_subresource_lists_booked
        """
        ctx = setup_event_with_referrals(num_participants=1, capacity=2)
        ref = ctx["referrals"][0]
        book_referral(ref["id"], ctx["event"]["id"])

        roster, meta = validate_paginated(
            api.list_event_referrals(
                ctx["event"]["id"],
                make_institution_officer_headers(ctx["institution"]["id"]),
            )
        )
        assert meta["total_count"] == 1
        assert roster[0]["id"] == ref["id"]
        assert roster[0]["status"] == "BOOKED"


class TestEventLifecycle:
    def test_second_cancel_rejected(self, api):
        """PRD §3.5: "An officer of the hosting institution may cancel a `SCHEDULED` event; an officer of any other institution is rejected with `ERR_UNAUTHORIZED_ROLE`, and a cancellation attempted on a non-`SCHEDULED` event is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/cancel_cancelled_event_returns_invalid_state
        """
        ctx = setup_certified_institution()
        inst_id = ctx["institution"]["id"]
        event = create_event(inst_id)
        officer = make_institution_officer_headers(inst_id)
        get_success_data(api.cancel_account_opening_event(event["id"], officer))

        resp = api.cancel_account_opening_event(event["id"], officer)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)  # CANCELLED is terminal

    def test_event_auto_completes_via_ops_epoch(self, api):
        """PRD §3.5: "Alternatively, when the ops epoch finds a `SCHEDULED` event whose `ends_at` the logical clock has passed, the event moves to `COMPLETED` and the same per-referral release runs for any remaining `BOOKED` referrals."
        PRD §2.5: "The epoch returns a summary object with integer counts `checkpoints_evaluated`, `certifications_lapsed`, `events_completed`, and `follow_ups_due`."

        Design: Corner/state_machines/event_auto_complete_via_ops_epoch
        """
        ctx = setup_certified_institution()
        event = create_event(ctx["institution"]["id"])  # window 2026-05-10 09:00-13:00
        set_clock("2026-05-11T00:00:00Z")

        summary = run_ops_epoch()
        assert summary["events_completed"] == 1
        event_after = get_success_data(api.get_account_opening_event(event["id"], ADMIN))
        assert event_after["status"] == "COMPLETED"
