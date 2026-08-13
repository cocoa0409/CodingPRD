"""Solicitation pipeline: send/revise revision cycle, donor cooldown
half-open window, item receipt gating, and the fixed startup clock."""
from test_helpers import (
    ADMIN,
    NON_EXISTENT_UUID,
    PO,
    ApiErrorId,
    api_client,
    assert_solicitation,
    attach_item,
    create_bundle,
    create_donor,
    create_event,
    create_pledged_solicitation,
    create_solicitation,
    get_success_data,
    publish_bundle,
    record_solicitation_outcome,
    revise_solicitation_payload,
    send_solicitation,
    setup_valued_item,
    validate_error,
    validate_success,
)


def _event_with_solicitation():
    """Event in SOLICITING with one donor and one DRAFT solicitation."""
    event = create_event()
    api_client.advance_gala_event(event["id"], ADMIN)  # SOLICITING
    donor = create_donor()
    sol = create_solicitation(donor["id"], event["id"])
    return event, donor, sol


class TestSolicitationRevisionCycle:

    def test_send_then_revise_pulls_back_to_revised(self):
        """PRD section 3.2: "Sending, performed by a `ProcurementOfficer`,
        moves a solicitation from `DRAFT`, `REVISED`, or `STALLED` to `SENT`
        and stamps `last_sent_at` with the logical clock's current instant;
        until the first send, `last_sent_at` is null." PRD section 3.2:
        "revision by a `ProcurementOfficer` pulls a `SENT` solicitation back
        to `REVISED`, replacing `ask_description` and `ask_estimate_cents`
        with the payload values."

        Design: Difficulty/non_linear_state_machine/solicitation_revision_cycle
        """
        _event, _donor, sol = _event_with_solicitation()
        assert sol["status"] == "DRAFT"
        assert sol["last_sent_at"] is None

        sent = validate_success(api_client.send_solicitation(sol["id"], PO))
        assert_solicitation(sent)
        assert sent["status"] == "SENT"
        assert sent["last_sent_at"] == "2026-08-01T00:00:00Z", \
            "first send stamps the fixed startup clock instant"

        revised = validate_success(api_client.revise_solicitation(
            sol["id"],
            revise_solicitation_payload(
                ask_description="Weekend cabin + dinner",
                ask_estimate_cents=95000),
            PO,
        ))
        assert revised["status"] == "REVISED", "cycle back"
        assert revised["ask_description"] == "Weekend cabin + dinner"
        assert revised["ask_estimate_cents"] == 95000

    def test_resend_rearms_last_sent_and_loop_exits_to_pledged(self):
        """PRD section 3.2: "The loop from `SENT` to `REVISED` and back to
        `SENT` is a genuine cycle — each re-send refreshes `last_sent_at`
        and thereby re-arms the donor cooldown." PRD section 3.2: "Against
        a `SENT` solicitation, `PLEDGED` moves it to `PLEDGED`"

        Design: Difficulty/non_linear_state_machine/solicitation_revision_cycle
        """
        _event, _donor, sol = _event_with_solicitation()
        send_solicitation(sol["id"])
        api_client.revise_solicitation(
            sol["id"], revise_solicitation_payload(), PO)
        validate_success(api_client.set_clock(
            {"to_iso8601": "2026-08-20T00:00:00Z"}, ADMIN))

        resent = validate_success(api_client.send_solicitation(sol["id"], PO))
        assert resent["status"] == "SENT"
        assert resent["last_sent_at"] == "2026-08-20T00:00:00Z", \
            "re-send refreshes last_sent_at from the moved clock"

        pledged = validate_success(
            api_client.record_solicitation_response(
                sol["id"], {"outcome": "PLEDGED"}, PO))
        assert pledged["status"] == "PLEDGED", \
            "loop exits to the forward path"


class TestDonorSolicitationCooldown:

    def _event_with_sent_solicitation(self):
        event = create_event()
        api_client.advance_gala_event(event["id"], ADMIN)  # SOLICITING
        donor = create_donor()
        sol1 = create_solicitation(donor["id"], event["id"],
                                   ask_description="First ask")
        sent = send_solicitation(sol1["id"])
        return event, donor, sent

    def test_second_solicitation_inside_cooldown_rejected(self):
        """PRD section 3.2: "for a given donor and event, if any *other*
        solicitation has a `last_sent_at` such that the current instant
        falls at or after that `last_sent_at` and strictly before that
        `last_sent_at` plus the event's `solicitation_cooldown_days` — a
        half-open window — the create or send is rejected with
        `ERR_SOLICITATION_COOLDOWN`."

        Design: Difficulty/resource_temporal_overlap/donor_solicitation_cooldown_window
        """
        event, donor, sent = self._event_with_sent_solicitation()
        assert sent["last_sent_at"] == "2026-08-01T00:00:00Z"

        resp = api_client.create_solicitation(
            {
                "donor_id": donor["id"],
                "gala_event_id": event["id"],
                "ask_description": "Second ask too soon",
                "ask_estimate_cents": 25000,
            },
            PO,
        )
        validate_error(resp, ApiErrorId.ERR_SOLICITATION_COOLDOWN)

    def test_second_solicitation_at_cooldown_expiry_allowed(self):
        """PRD section 3.2: "for a given donor and event, if any *other*
        solicitation has a `last_sent_at` such that the current instant
        falls at or after that `last_sent_at` and strictly before that
        `last_sent_at` plus the event's `solicitation_cooldown_days` — a
        half-open window — the create or send is rejected with
        `ERR_SOLICITATION_COOLDOWN`."

        Design: Difficulty/resource_temporal_overlap/donor_solicitation_cooldown_window
        """
        event, donor, _sent = self._event_with_sent_solicitation()
        # last_sent 2026-08-01 + 30 days = window closes at 2026-08-31.
        validate_success(api_client.set_clock(
            {"to_iso8601": "2026-08-31T00:00:00Z"}, ADMIN))
        resp = api_client.create_solicitation(
            {
                "donor_id": donor["id"],
                "gala_event_id": event["id"],
                "ask_description": "Second ask after cooldown",
                "ask_estimate_cents": 25000,
            },
            PO,
        )
        data = validate_success(resp, expected_status=201)
        assert_solicitation(data)
        assert data["donor_id"] == donor["id"]


class TestTerminalAndReceiptGates:

    def test_send_withdrawn_solicitation_rejected(self):
        """PRD section 3.2: "The terminal states are `DECLINED`,
        `WITHDRAWN`, and `FULFILLED`". PRD section 2.8: "the target
        entity's state machine permits the requested transition; otherwise
        `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/send_withdrawn_solicitation_rejected
        """
        _event, _donor, sol = _event_with_solicitation()
        record_solicitation_outcome(sol["id"], "WITHDRAWN")

        resp = api_client.send_solicitation(sol["id"], PO)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        after = get_success_data(api_client.get_solicitation(sol["id"], PO))
        assert after["status"] == "WITHDRAWN"
        assert after["last_sent_at"] is None, \
            "a solicitation never sent keeps last_sent_at null"

    def test_item_receipt_requires_pledged_solicitation(self):
        """PRD section 3.3: "Receipt requires the solicitation's event to
        be in `SOLICITING` or `CATALOGING` (`ERR_EVENT_PHASE_FORBIDDEN`
        otherwise) and the solicitation itself to be `PLEDGED`
        (`ERR_SOLICITATION_NOT_PLEDGED` otherwise)." PRD section 3.3: "in
        the same transaction the solicitation moves from `PLEDGED` to
        `FULFILLED`."

        Design: Corner/validations/item_receipt_requires_pledged_solicitation
        """
        event = create_event()
        api_client.advance_gala_event(event["id"], ADMIN)  # SOLICITING
        donor = create_donor()
        sol = create_solicitation(donor["id"], event["id"])
        send_solicitation(sol["id"])

        early = api_client.create_item(
            {
                "solicitation_id": sol["id"],
                "title": "Early",
                "description": "x",
                "kind": "PHYSICAL",
            },
            PO,
        )
        validate_error(early, ApiErrorId.ERR_SOLICITATION_NOT_PLEDGED)

        record_solicitation_outcome(sol["id"], "PLEDGED")
        item_resp = api_client.create_item(
            {
                "solicitation_id": sol["id"],
                "title": "On time",
                "description": "x",
                "kind": "PHYSICAL",
            },
            PO,
        )
        item = validate_success(item_resp, expected_status=201)
        assert item["status"] == "RECEIVED"
        assert item["donor_id"] == donor["id"]
        assert item["gala_event_id"] == event["id"]
        assert item["bundle_id"] is None
        assert item["current_fmv_cents"] is None
        assert item["disclosure_tier"] is None

        sol_after = get_success_data(
            api_client.get_solicitation(sol["id"], PO))
        assert sol_after["status"] == "FULFILLED", \
            "receipt cascades the solicitation to FULFILLED"


class TestExistenceBeatsPhase:

    def _bidding_open_event_with_spare_pledge(self):
        """Event taken to BIDDING_OPEN with one published bundle (built
        from the first donor's item) plus a second donor's solicitation
        that was sent and pledged while the event was still SOLICITING and
        remains PLEDGED at trigger time."""
        event = create_event()
        api_client.advance_gala_event(event["id"], ADMIN)  # SOLICITING
        part = setup_valued_item(event["id"], 30000, title="Vase")
        donor2 = create_donor()
        spare = create_pledged_solicitation(donor2["id"], event["id"],
                                            ask_description="Late lot")
        api_client.advance_gala_event(event["id"], ADMIN)  # CATALOGING
        bundle = create_bundle(event["id"], title="Vase")
        attach_item(bundle["id"], part["item"]["id"])
        publish_bundle(bundle["id"])
        api_client.advance_gala_event(event["id"], ADMIN)  # BIDDING_OPEN
        return event, spare

    def test_item_receipt_nonexistent_solicitation_returns_not_found(self):
        """PRD section 2.8: "Every request is evaluated against a single
        ordered cascade of checks; a failure at any step short-circuits the
        rest, so the error a client receives identifies the earliest failing
        category." PRD section 2.8: "path identifiers and body foreign-key
        references all exist, validated left to right; otherwise
        `ERR_NOT_FOUND` (HTTP 404)."

        Design: Difficulty/priority_pair_validation_conflict/existence_beats_state_on_item_receipt
        """
        self._bidding_open_event_with_spare_pledge()
        resp = api_client.create_item(
            {
                "solicitation_id": NON_EXISTENT_UUID,
                "title": "Ghost",
                "description": "Nope",
                "kind": "PHYSICAL",
            },
            PO,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_item_receipt_wrong_phase_returns_phase_error(self):
        """PRD section 2.8: "the event's current phase permits the
        operation (solicitation sends and item receipts need `SOLICITING`
        or `CATALOGING`; bids need `BIDDING_OPEN`; gala settings updates
        need `DRAFT`, `SOLICITING`, or `CATALOGING`); otherwise
        `ERR_EVENT_PHASE_FORBIDDEN` (HTTP 409)." PRD section 3.3:
        "Receipt requires the solicitation's event to be in `SOLICITING` or
        `CATALOGING` (`ERR_EVENT_PHASE_FORBIDDEN` otherwise)"

        Design: Difficulty/priority_pair_validation_conflict/existence_beats_state_on_item_receipt
        """
        _event, spare = self._bidding_open_event_with_spare_pledge()
        resp = api_client.create_item(
            {
                "solicitation_id": spare["id"],
                "title": "Too late",
                "description": "x",
                "kind": "PHYSICAL",
            },
            PO,
        )
        validate_error(resp, ApiErrorId.ERR_EVENT_PHASE_FORBIDDEN)


class TestLogicalClockDefault:

    def test_clock_default_is_fixed_startup_instant(self):
        """PRD section 2.5: "At startup the clock reads exactly
        `2026-08-01T00:00:00Z`; before any administrative call it continues
        to read that default and never falls back to wall-clock time."
        PRD section 3.2: "stamps `last_sent_at` with the logical clock's
        current instant"

        Design: Corner/cross_cutting_complexity_layers/clock_default_is_fixed_startup_instant
        """
        _event, _donor, sol = _event_with_solicitation()
        sent = validate_success(api_client.send_solicitation(sol["id"], PO))
        assert sent["last_sent_at"] == "2026-08-01T00:00:00Z", \
            "no clock call made: fixed startup instant, not wall clock"
