"""Abandonment sweep cascade and the collections-debt booking gate.

Covers the depth-3 abandonment cascade (storage -> share -> invoice ->
customer strike), the COLLECTIONS invoice blocking new bookings, and the
validation-order pair where the temporal lead-time rule beats the fiscal
outstanding-balance rule.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_share,
    book_and_confirm,
    create_and_submit_cut_sheet,
    create_appointment_payload,
    create_capacity_day,
    create_customer,
    earn_no_show_strike,
    finalize_split,
    get_customer,
    get_share,
    get_share_invoice,
    get_share_storage_record,
    get_success_data,
    make_customer_headers,
    process_animal_to_hanging,
    set_logical_clock,
    setup_customer_with_collections,
    start_and_complete_fabrication,
    validate_error,
    validate_success,
)

OP = TEST_USERS["operator_headers"]


def _setup_abandonment_scenario(api):
    """c1 carries one strike from a 2026-08-15 no-show, then books a HOG job
    under the elevated deposit, completes fabrication with ready_at
    2026-08-18, and the clock advances to 2026-09-09 (days_stored 22 > 21).
    The sweep has NOT yet run."""
    c1 = create_customer("Ann Orr", "555-0101", "ann@x.com")
    # Strike 1 (ELEVATED_DEPOSIT afterwards). Clock ends at 2026-08-15.
    earn_no_show_strike(c1["id"], "2026-08-15", species="BEEF", head_count=1)
    # Second job: booked 14+ days out from the current clock (2026-08-15).
    day = create_capacity_day("2026-08-29", 1)
    appointment, animals = book_and_confirm(c1["id"], day["id"], "HOG", 1)
    # Elevated quote for HOG 1 head: est hanging 280 * 0.75 = 210 lb ->
    # tiered 17000 + 10*75 = 17750; + slaughter 6000 = 23750; half = 11875.
    assert appointment["deposit_amount_cents"] == 11875
    animal = process_animal_to_hanging(animals[0]["id"], "TAG-B1", 280.0, 200.0)
    share = add_share(animal["id"], c1["id"], 1.0, as_customer_id=c1["id"])
    finalize_split(animal["id"])
    create_and_submit_cut_sheet(share["id"], c1["id"])
    set_logical_clock("2026-08-18T00:00:00Z")  # weighed 08-15 + 3 days
    start_and_complete_fabrication(animal["id"])
    set_logical_clock("2026-09-09T00:00:00Z")  # 22 days stored
    return c1, share


class TestAbandonmentCascade:
    def test_abandonment_cascades_storage_share_invoice(self, api):
        """PRD §3.8: "When a storage record's `days_stored` exceeds 21 — from
        the 22nd day after `ready_at` onward — the record is swept to
        `ABANDONED`. The abandonment cascades in a fixed chain: the share
        moves from `READY` to `FORFEITED`; that forfeiture drives the share's
        invoice, whether `OPEN` or `PARTIALLY_PAID`, into `COLLECTIONS` with
        `surcharge_cents` set to 5000 cents and the total recomputed".

        Design: Difficulty/transitive_cascade/abandonment_cascade_storage_to_customer_block
        """
        c1, share = _setup_abandonment_scenario(api)
        record = get_share_storage_record(share["id"])
        sweep = get_success_data(api.run_daily(OP))
        assert record["id"] in sweep["abandoned_storage_ids"]
        record_after = get_share_storage_record(share["id"])
        assert record_after["status"] == "ABANDONED"
        assert get_share(share["id"])["status"] == "FORFEITED"
        invoice = get_share_invoice(share["id"])
        assert invoice["status"] == "COLLECTIONS"
        assert invoice["surcharge_cents"] == 5000

    def test_abandonment_charges_strike_and_blocks_customer(self, api):
        """PRD §3.8: "the invoice entering collections charges the owning
        customer's `no_show_strikes` by one, recomputing their standing so a
        second strike of any kind blocks them from further bookings."
        PRD §3.1: "two or more strikes yields `BLOCKED`."

        Design: Difficulty/transitive_cascade/abandonment_cascade_storage_to_customer_block
        """
        c1, share = _setup_abandonment_scenario(api)
        assert get_customer(c1["id"])["no_show_strikes"] == 1
        get_success_data(api.run_daily(OP))
        customer_after = get_customer(c1["id"])
        assert customer_after["no_show_strikes"] == 2
        assert customer_after["status"] == "BLOCKED"


class TestCollectionsBookingGate:
    def test_collections_invoice_blocks_booking(self, api):
        """PRD §3.1: "a customer with any invoice sitting in `COLLECTIONS`
        must settle that abandoned-meat debt before booking again, else
        `ERR_OUTSTANDING_BALANCE`."

        The target day is 15 days out (lead rule satisfied) and has room; the
        customer carries one strike (ELEVATED, not BLOCKED), so only the
        fiscal gate can fire.

        Design: Corner/validations/collections_invoice_blocks_booking
        """
        scenario = setup_customer_with_collections()
        customer = scenario["customer"]
        assert customer["status"] == "ELEVATED_DEPOSIT"
        assert scenario["invoice"]["status"] == "COLLECTIONS"
        day = create_capacity_day("2026-09-10", 1)  # 15 days past 2026-08-26
        resp = api.create_appointment(
            create_appointment_payload(customer["id"], day["id"], "BEEF", 1),
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OUTSTANDING_BALANCE,
                       expected_status=402)


class TestPriorityPair:
    def test_lead_time_fires_before_collections_gate(self, api):
        """PRD §2.8: "then the temporal window rules (lead time, minimum hang,
        premature no-show), then referential completeness (missing cut sheets,
        unapproved labels), and finally the fiscal checks
        (`ERR_OUTSTANDING_BALANCE`, `ERR_DEPOSIT_INSUFFICIENT`,
        `ERR_INVOICE_NOT_PAID`)."

        The customer carries a COLLECTIONS invoice (fiscal) and the target
        day is only 9 days out (temporal); the temporal rule is reported.

        Design: Difficulty/priority_pair_validation_conflict/booking_lead_time_beats_outstanding_balance
        """
        scenario = setup_customer_with_collections()  # clock ends 2026-08-26
        customer = scenario["customer"]
        day = create_capacity_day("2026-09-04", 1)  # only 9 days out
        resp = api.create_appointment(
            create_appointment_payload(customer["id"], day["id"], "BEEF", 1),
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_LEAD_TIME_TOO_SHORT,
                       expected_status=422)

    def test_rejected_booking_creates_no_appointment(self, api):
        """PRD §2.8: "the server evaluates them in a fixed order so the
        reported error is deterministic ... then the temporal window rules
        (lead time, minimum hang, premature no-show) ... and finally the
        fiscal checks". A request rejected at the temporal tier is never
        persisted, so the customer's appointment history is unchanged.

        Design: Difficulty/priority_pair_validation_conflict/booking_lead_time_beats_outstanding_balance
        """
        scenario = setup_customer_with_collections()  # clock ends 2026-08-26
        customer = scenario["customer"]
        day = create_capacity_day("2026-09-04", 1)  # only 9 days out
        resp = api.create_appointment(
            create_appointment_payload(customer["id"], day["id"], "BEEF", 1),
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_LEAD_TIME_TOO_SHORT,
                       expected_status=422)
        data = get_success_data(
            api.list_appointments(OP, params={"customer_id": customer["id"]})
        )
        assert len(data) == 1, (
            "the rejected booking must not add an appointment; only the "
            "original HOG job exists"
        )
        assert data[0]["species"] == "HOG"
