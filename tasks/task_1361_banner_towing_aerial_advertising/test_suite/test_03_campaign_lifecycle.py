"""Campaign lifecycle: booking gate, credit hold, pagination, OCC on book,
the schedule-driven IN_FLIGHT lift, and invoice-gated completion."""
from test_helpers import (
    ApiErrorId,
    assert_campaign,
    book_campaign,
    book_slot_in,
    create_base,
    create_client,
    create_campaign,
    file_flight_log,
    issue_invoice,
    make_client_headers,
    schedule_slot,
    setup_operation,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN, FINANCE


class TestCampaignBookingGate:

    def test_book_campaign_without_booked_slots_rejected(self, api):
        """PRD §3.2: "Booking a campaign is the client's act of committing: it
        requires at least one child slot already in `BOOKED` status and
        requires `expected_campaign_version` per §2.10". PRD §2.7: "the
        from-state check, which rejects a transition the resource's current
        state does not permit with `ERR_INVALID_STATE` (HTTP 409)".

        Design: Corner/state_machines/campaign_draft_book_without_slots_rejected
        """
        create_base(code="KNOS", name="No Slots Field")
        client = create_client(legal_name="NoSlots Co", billing_email="n@x.com")
        campaign = create_campaign(client["id"], name="Empty Campaign")
        resp = api.book_campaign(
            campaign["id"],
            {"expected_campaign_version": campaign["version"]},
            make_client_headers(client["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_credit_hold_blocks_campaign_creation(self, api,
                                                  finance_officer_headers):
        """PRD §3.2: "A client under a credit hold cannot start new work:
        creating a campaign while `credit_hold` is true is rejected with
        `ERR_CLIENT_CREDIT_HOLD` (HTTP 402)".

        Design: Corner/errors/error_client_credit_hold_blocks_campaign_creation
        """
        create_base(code="KCRD", name="Credit Field")
        client = create_client(legal_name="Held Co", billing_email="h@x.com")
        resp = api.set_credit_hold(client["id"], {"credit_hold": True},
                                   finance_officer_headers)
        validate_success(resp, expected_status=200)
        resp = api.create_campaign(client["id"], {"name": "Blocked"},
                                   make_client_headers(client["id"]))
        validate_error(resp, ApiErrorId.ERR_CLIENT_CREDIT_HOLD,
                       expected_status=402)

    def test_book_with_stale_campaign_version_rejected(self, api):
        """PRD §2.10: "Campaign booking requires the request to carry
        `expected_campaign_version` holding the campaign's current `version`;
        if another writer has advanced the campaign's version since the client
        last read it — for example by adding a flight slot — the booking is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.5: "the campaign's own `version` advances by one — which is
        precisely why the campaign-booking OCC guard of §2.10 exists."

        Design: Corner/cross_cutting_layers/occ_stale_campaign_version_on_book
        """
        sc = setup_operation(base_code="KOCC")
        campaign = sc["campaign"]
        stale_version = campaign["version"]
        book_slot_in(sc, planned_start="2026-08-13T15:00:00Z",
                     planned_duration_hours=1)
        resp = api.book_campaign(
            campaign["id"], {"expected_campaign_version": stale_version},
            make_client_headers(sc["client"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


class TestCampaignListing:

    def test_list_campaigns_paginated_envelope(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned:
        it defaults to 10, with a minimum of 1 and a maximum of 100. The
        `offset` parameter skips a number of items from the front of the
        result set and defaults to 0. Every list response includes `limit`,
        `offset`, `total_count`, and `has_more` in the `meta` object of the
        envelope." PRD §2.2: "The `response_type` is either "object" for a
        single resource or "array" for a list of resources."

        Design: Corner/endpoints/list_campaigns_returns_paginated_envelope
        """
        create_base(code="KLST", name="List Field")
        client = create_client(legal_name="Listy Co", billing_email="l@x.com")
        create_campaign(client["id"], name="C1")
        create_campaign(client["id"], name="C2")
        resp = api.list_campaigns(client["id"], ADMIN)
        data, meta = validate_paginated(resp)
        assert isinstance(data, list) and len(data) == 2
        assert meta["limit"] == 10, f"default limit must be 10, got {meta['limit']}"
        assert meta["offset"] == 0
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        for campaign in data:
            assert_campaign(campaign)


class TestCampaignAutomaticProgression:

    def test_first_schedule_lifts_campaign_to_in_flight(self, api):
        """PRD §3.6: "The first scheduling under a `BOOKED` campaign pushes
        the campaign itself into `IN_FLIGHT` automatically, per §2.11."

        Design: Corner/state_machines/schedule_booked_slot_transitions_and_campaign_state_lifts
        """
        sc = setup_operation(base_code="KLFT")
        slot = book_slot_in(sc, planned_start="2026-08-13T15:00:00Z",
                            planned_duration_hours=1)
        book_campaign(sc["campaign"]["id"], sc["client"]["id"])
        schedule_slot(slot["id"])
        data = validate_success(api.get_campaign(sc["campaign"]["id"], ADMIN),
                                expected_status=200)
        assert data["status"] == "IN_FLIGHT", (
            f"campaign must lift to IN_FLIGHT on first schedule, "
            f"got {data['status']}"
        )

    def test_campaign_completes_when_invoice_paid(self, api):
        """PRD §3.2: "once every child slot sits in a terminal state (`FLOWN`,
        `CANCELLED_CLIENT`, `CANCELLED_WEATHER`, or `CANCELLED_TFR`) and every
        invoice issued for the campaign is `PAID` or `VOID`, the campaign
        completes itself to `COMPLETE`."

        Two slots: S1 flies, the invoice covering it is issued (ISSUED) while
        S2 is still BOOKED, then S2 flies — with an unsettled invoice on file
        the campaign stays IN_FLIGHT; settling it to PAID completes the
        campaign.

        Design: Difficulty/cross_entity_state_dependency/campaign_complete_requires_all_slots_terminal_and_invoices_settled
        """
        sc = setup_operation(base_code="KCP1")
        s1 = book_slot_in(sc, planned_start="2026-08-13T14:00:00Z",
                          planned_duration_hours=1)
        s2 = book_slot_in(sc, planned_start="2026-08-13T16:00:00Z",
                          planned_duration_hours=1)
        book_campaign(sc["campaign"]["id"], sc["client"]["id"])
        schedule_slot(s1["id"])
        file_flight_log(s1["id"], hobbs_out=100.0, hobbs_in=101.0)
        invoice = issue_invoice(sc["campaign"]["id"])
        schedule_slot(s2["id"])
        file_flight_log(s2["id"], hobbs_out=200.0, hobbs_in=201.0)
        after_terminal = validate_success(
            api.get_campaign(sc["campaign"]["id"], ADMIN), expected_status=200)
        assert after_terminal["status"] == "IN_FLIGHT", (
            f"invoice still ISSUED, campaign must stay IN_FLIGHT, "
            f"got {after_terminal['status']}"
        )
        validate_success(api.mark_invoice_paid(invoice["id"], FINANCE),
                         expected_status=200)
        after_paid = validate_success(
            api.get_campaign(sc["campaign"]["id"], ADMIN), expected_status=200)
        assert after_paid["status"] == "COMPLETE", (
            f"all slots terminal and invoice PAID, campaign must complete, "
            f"got {after_paid['status']}"
        )

    def test_campaign_completes_when_invoice_voided(self, api):
        """PRD §3.2: "once every child slot sits in a terminal state (`FLOWN`,
        `CANCELLED_CLIENT`, `CANCELLED_WEATHER`, or `CANCELLED_TFR`) and every
        invoice issued for the campaign is `PAID` or `VOID`, the campaign
        completes itself to `COMPLETE`."
        PRD §3.8: "Voiding an invoice is the compensating action: the invoice
        moves to `VOID`".

        A VOID invoice counts as settled, so voiding the outstanding invoice
        of a fully-terminal campaign also completes it.

        Design: Difficulty/cross_entity_state_dependency/campaign_complete_requires_all_slots_terminal_and_invoices_settled
        """
        sc = setup_operation(base_code="KCP2")
        s1 = book_slot_in(sc, planned_start="2026-08-13T14:00:00Z",
                          planned_duration_hours=1)
        s2 = book_slot_in(sc, planned_start="2026-08-13T16:00:00Z",
                          planned_duration_hours=1)
        book_campaign(sc["campaign"]["id"], sc["client"]["id"])
        schedule_slot(s1["id"])
        file_flight_log(s1["id"], hobbs_out=100.0, hobbs_in=101.0)
        invoice = issue_invoice(sc["campaign"]["id"])
        schedule_slot(s2["id"])
        file_flight_log(s2["id"], hobbs_out=200.0, hobbs_in=201.0)
        after_terminal = validate_success(
            api.get_campaign(sc["campaign"]["id"], ADMIN), expected_status=200)
        assert after_terminal["status"] == "IN_FLIGHT", (
            f"invoice still ISSUED, campaign must stay IN_FLIGHT, "
            f"got {after_terminal['status']}"
        )
        validate_success(api.void_invoice(invoice["id"], FINANCE),
                         expected_status=200)
        after_void = validate_success(
            api.get_campaign(sc["campaign"]["id"], ADMIN), expected_status=200)
        assert after_void["status"] == "COMPLETE", (
            f"all slots terminal and invoice VOID, campaign must complete, "
            f"got {after_void['status']}"
        )
