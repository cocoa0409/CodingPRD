"""Unsold-item disposition: the donor reconsideration cycle, rollover
targeting, terminal lockdown, donor ownership, and the reconciliation
gate chain."""
from test_helpers import (
    ADMIN,
    FO,
    ApiErrorId,
    api_client,
    create_donor,
    create_event,
    get_success_data,
    make_donor_headers,
    pay_invoice_in_full,
    setup_sold_scenario,
    setup_unsold_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestDispositionReconsiderationCycle:

    def test_donor_decline_resets_decision(self):
        """PRD section 3.9: "Responding with `accept` false instead
        returns the disposition from `DONOR_NOTIFIED` to `PROPOSED`,
        clearing `decision` and `target_gala_event_id` back to null so the
        committee may reconsider." PRD section 3.9: "A successful decision
        moves the disposition from `PROPOSED` to `DONOR_NOTIFIED`."

        Design: Difficulty/non_linear_state_machine/disposition_reconsideration_cycle
        """
        ctx = setup_unsold_scenario(fmv_cents=40000)
        disposition = ctx["dispositions"][0]
        donor = ctx["donors"][0]

        decided = validate_success(api_client.decide_disposition(
            disposition["id"], {"decision": "RETURN_TO_DONOR"}, ADMIN))
        assert decided["status"] == "DONOR_NOTIFIED"
        assert decided["decision"] == "RETURN_TO_DONOR"

        declined = validate_success(api_client.respond_to_disposition(
            disposition["id"], {"accept": False},
            make_donor_headers(donor["id"])))
        assert declined["status"] == "PROPOSED", "cycle reset"
        assert declined["decision"] is None
        assert declined["target_gala_event_id"] is None

    def test_reconsidered_discard_executes_and_bubbles(self):
        """PRD section 3.9: "Under `DISCARD`, the item moves from
        `UNSOLD` to `DISCARDED` and its acknowledgment is left unchanged,
        remaining issuable, since the gift was completed even though the
        item was not." PRD section 3.9: "When every member item's latest
        disposition has reached `EXECUTED`, the unsold bundle bubbles up
        from `UNSOLD` to `DISPOSITIONED`."

        Design: Difficulty/non_linear_state_machine/disposition_reconsideration_cycle
        """
        ctx = setup_unsold_scenario(fmv_cents=40000)
        disposition = ctx["dispositions"][0]
        donor = ctx["donors"][0]
        item_id = ctx["items"][0]["id"]

        validate_success(api_client.decide_disposition(
            disposition["id"], {"decision": "RETURN_TO_DONOR"}, ADMIN))
        validate_success(api_client.respond_to_disposition(
            disposition["id"], {"accept": False},
            make_donor_headers(donor["id"])))

        redecided = validate_success(api_client.decide_disposition(
            disposition["id"], {"decision": "DISCARD"}, ADMIN))
        assert redecided["status"] == "DONOR_NOTIFIED"

        executed = validate_success(api_client.respond_to_disposition(
            disposition["id"], {"accept": True},
            make_donor_headers(donor["id"])))
        assert executed["status"] == "EXECUTED"

        item = get_success_data(api_client.get_item(item_id, ADMIN))
        assert item["status"] == "DISCARDED"

        acks, _m = validate_paginated(api_client.list_acknowledgments(
            FO, params={"item_id": item_id}))
        assert len(acks) == 1
        assert acks[0]["status"] == "PENDING", \
            "DISCARD keeps the gift acknowledgment issuable"

        bundle = get_success_data(
            api_client.get_bundle(ctx["bundle"]["id"], ADMIN))
        assert bundle["status"] == "DISPOSITIONED", \
            "bubble-up: all member item dispositions EXECUTED"


class TestReconcileGate:

    def _settlement_event_with_unpaid_invoice(self):
        ctx = setup_sold_scenario(fmv_cents=40000, bid_amount=50000)
        advanced = api_client.advance_gala_event(ctx["event"]["id"], ADMIN)
        settlement = get_success_data(advanced)
        assert settlement["status"] == "SETTLEMENT"
        return ctx

    def test_reconcile_blocked_by_unpaid_invoice(self):
        """PRD section 3.9: "It is blocked with `ERR_RECONCILE_BLOCKED`
        unless all three of the following hold: every invoice of the event
        has `payment_status` in `PAID`, `REFUNDED`, or `WRITTEN_OFF`;
        every invoice whose `payment_status` is `PAID` has
        `fulfillment_status` in `FULFILLED` or `EXPIRED`; and every
        disposition of the event has reached `EXECUTED`."

        Design: Difficulty/cross_entity_state_dependency/reconcile_gated_on_open_invoices
        """
        ctx = self._settlement_event_with_unpaid_invoice()
        resp = api_client.reconcile_gala_event(ctx["event"]["id"], FO)
        validate_error(resp, ApiErrorId.ERR_RECONCILE_BLOCKED)

        after = get_success_data(
            api_client.get_gala_event(ctx["event"]["id"], ADMIN))
        assert after["status"] == "SETTLEMENT", \
            "rejected reconcile leaves the event in SETTLEMENT"

    def test_reconcile_succeeds_after_gates_met(self):
        """PRD section 3.1: "The final step out of `SETTLEMENT` is not an
        advance but a reconciliation performed by a `FinanceOfficer`,
        moving the event to `RECONCILED` — the terminal state — only when
        the gates of §3.9 hold; a blocked reconciliation is rejected with
        `ERR_RECONCILE_BLOCKED`."

        Design: Difficulty/cross_entity_state_dependency/reconcile_gated_on_open_invoices
        """
        ctx = self._settlement_event_with_unpaid_invoice()
        pay_invoice_in_full(ctx["invoice"], ctx["bidder"]["id"])
        validate_success(
            api_client.fulfill_invoice(ctx["invoice"]["id"], ADMIN))

        reconciled = validate_success(
            api_client.reconcile_gala_event(ctx["event"]["id"], FO))
        assert reconciled["status"] == "RECONCILED"


class TestRolloverDecision:

    def test_rollover_decide_requires_valid_target(self):
        """PRD section 3.9: "a `ROLLOVER` decision additionally requires a
        `target_gala_event_id` that exists, differs from the source event,
        and is in `DRAFT`, `SOLICITING`, or `CATALOGING` — a missing,
        identical, or wrong-phase target is rejected with
        `ERR_ROLLOVER_TARGET_INVALID`." PRD section 3.9: "Under
        `ROLLOVER`, the item's `gala_event_id` is rewritten to the target
        event, its `bundle_id` is nulled, and its status re-enters
        `VALUED` under the target event, ready to be bundled anew; the
        original acknowledgment is voided and a new `PENDING`
        acknowledgment is created under the target event carrying the
        item's current fair market value."

        Design: Corner/validations/rollover_decide_without_target_rejected
        """
        ctx = setup_unsold_scenario(fmv_cents=40000)
        disposition = ctx["dispositions"][0]
        donor = ctx["donors"][0]
        item_id = ctx["items"][0]["id"]

        target = create_event()
        api_client.advance_gala_event(target["id"], ADMIN)  # SOLICITING

        missing = api_client.decide_disposition(
            disposition["id"], {"decision": "ROLLOVER"}, ADMIN)
        validate_error(missing, ApiErrorId.ERR_ROLLOVER_TARGET_INVALID)

        decided = validate_success(api_client.decide_disposition(
            disposition["id"],
            {"decision": "ROLLOVER",
             "target_gala_event_id": target["id"]}, ADMIN))
        assert decided["status"] == "DONOR_NOTIFIED"

        executed = validate_success(api_client.respond_to_disposition(
            disposition["id"], {"accept": True},
            make_donor_headers(donor["id"])))
        assert executed["status"] == "EXECUTED"

        item = get_success_data(api_client.get_item(item_id, ADMIN))
        assert item["gala_event_id"] == target["id"]
        assert item["status"] == "VALUED"
        assert item["bundle_id"] is None

        voided, _m = validate_paginated(api_client.list_acknowledgments(
            FO, params={"item_id": item_id, "status": "VOIDED"}))
        assert len(voided) == 1, "original acknowledgment voided"
        pending, _m2 = validate_paginated(api_client.list_acknowledgments(
            FO, params={"item_id": item_id, "status": "PENDING"}))
        assert len(pending) == 1
        assert pending[0]["gala_event_id"] == target["id"]
        assert pending[0]["fmv_cents"] == 40000


class TestDispositionTerminalLockdown:

    def test_disposition_terminal_lockdown_after_executed(self):
        """PRD section 3.9: "Deciding against a disposition not in
        `PROPOSED` — or recording a donor response against one not in
        `DONOR_NOTIFIED` — is rejected with `ERR_DISPOSITION_FORBIDDEN`."
        PRD section 3.9: "Under `RETURN_TO_DONOR`, the item moves from
        `UNSOLD` to `RETURNED_TO_DONOR`"

        Design: Corner/state_machines/disposition_terminal_lockdown_after_executed
        """
        ctx = setup_unsold_scenario(fmv_cents=40000)
        disposition = ctx["dispositions"][0]
        donor = ctx["donors"][0]

        validate_success(api_client.decide_disposition(
            disposition["id"], {"decision": "RETURN_TO_DONOR"}, ADMIN))
        validate_success(api_client.respond_to_disposition(
            disposition["id"], {"accept": True},
            make_donor_headers(donor["id"])))

        again = api_client.respond_to_disposition(
            disposition["id"], {"accept": False},
            make_donor_headers(donor["id"]))
        validate_error(again, ApiErrorId.ERR_DISPOSITION_FORBIDDEN)

        redecide = api_client.decide_disposition(
            disposition["id"], {"decision": "DISCARD"}, ADMIN)
        validate_error(redecide, ApiErrorId.ERR_DISPOSITION_FORBIDDEN)

        item = get_success_data(
            api_client.get_item(ctx["items"][0]["id"], ADMIN))
        assert item["status"] == "RETURNED_TO_DONOR"

        disp = get_success_data(
            api_client.get_disposition(disposition["id"], ADMIN))
        assert disp["status"] == "EXECUTED"


class TestDonorOwnership:

    def test_non_owner_donor_cannot_respond_disposition(self):
        """PRD section 3.9: "The acting `Donor`'s `X-User-ID` must equal
        the disposition's `donor_id` (`ERR_OWNERSHIP_VIOLATION`
        otherwise)." PRD section 2.1: "When `X-User-Role` is `Donor`,
        `X-User-ID` is the `id` of the acting `Donor`; ownership checks on
        a disposition compare the disposition's `donor_id` to
        `X-User-ID`."

        Design: Corner/rbac/non_owner_donor_cannot_respond_disposition
        """
        ctx = setup_unsold_scenario(fmv_cents=40000)
        disposition = ctx["dispositions"][0]
        other_donor = create_donor()

        validate_success(api_client.decide_disposition(
            disposition["id"], {"decision": "DISCARD"}, ADMIN))

        resp = api_client.respond_to_disposition(
            disposition["id"], {"accept": True},
            make_donor_headers(other_donor["id"]))
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_VIOLATION)

        disp = get_success_data(
            api_client.get_disposition(disposition["id"], ADMIN))
        assert disp["status"] == "DONOR_NOTIFIED", \
            "rejected response leaves the disposition untouched"


class TestReconcileSuccess:

    def test_reconcile_success_reaches_reconciled(self):
        """PRD section 3.1: "The final step out of `SETTLEMENT` is not an
        advance but a reconciliation performed by a `FinanceOfficer`,
        moving the event to `RECONCILED` — the terminal state — only when
        the gates of §3.9 hold". PRD section 2.10: "when an invoice's
        fulfillment completes or expires, its `SOLD` bundle advances to
        `SETTLED`"

        Design: Corner/errors/reconcile_success_reaches_reconciled
        """
        ctx = setup_sold_scenario(fmv_cents=40000, bid_amount=50000)
        pay_invoice_in_full(ctx["invoice"], ctx["bidder"]["id"])
        validate_success(
            api_client.fulfill_invoice(ctx["invoice"]["id"], ADMIN))
        api_client.advance_gala_event(ctx["event"]["id"],
                                      ADMIN)  # SETTLEMENT

        bundle = get_success_data(
            api_client.get_bundle(ctx["bundle"]["id"], ADMIN))
        assert bundle["status"] == "SETTLED", \
            "PAID + FULFILLED bubble-up"

        reconciled = validate_success(
            api_client.reconcile_gala_event(ctx["event"]["id"], FO))
        assert reconciled["status"] == "RECONCILED"
