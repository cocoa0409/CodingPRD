"""Dormancy sweeps, escheat records and the program reporting snapshot."""

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_escheat_record,
    attach_receipt,
    create_active_program,
    create_consumer_claimant,
    create_dealer_claimant,
    create_published_offer,
    deny_claim,
    make_consumer_headers,
    make_dealer_headers,
    open_claim,
    read_claim,
    read_payout,
    read_program,
    read_program_report,
    read_virtual_card,
    set_clock,
    setup_issued_card,
    setup_released_payout,
    validate_paginated,
    validate_receipt,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
PROCESSOR = TEST_USERS["claims_processor_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]


# --------------------------------------------------------------------------- #
# A check payout at exactly the dormancy limit
# --------------------------------------------------------------------------- #

def _released_check_awaiting_dormancy(jurisdiction="DE", mailing_state="TX"):
    return setup_released_payout(
        method="CHECK",
        check_number="CHK-9001",
        program_overrides={"name": "Escheat Program", "escheat_jurisdiction": jurisdiction},
        budget_total_cents=1000000,
        offer_overrides={"name": "Escheat Offer"},
        claimant_overrides={
            "legal_name": "Dormant Dealer",
            "email": "d@dorm.example",
            "mailing_state": mailing_state,
        },
        serial_number="SN-ESC-1",
    )


def test_check_payout_at_exactly_one_hundred_eighty_days_is_escheated(api):
    """PRD §3.9: "For a payout whose `method` is `CHECK`, the dormancy anchor is its
    `released_at`, the dormancy limit is 180 days, and the amount at stake is the
    payout's `net_cents`."
    PRD §3.9: "In both cases the elapsed whole days from the anchor to the logical
    clock are computed, and the payout is dormant when that figure is at or above
    its limit — at exactly the limit it is already dormant."

    Design: Difficulty/boundary_precision_check/check_dormancy_at_exactly_180_days_is_escheated
    """
    ctx = _released_check_awaiting_dormancy()
    set_clock("2027-01-06T00:00:00Z")

    records = validate_success(api.run_escheat_sweep(ctx["program"]["id"], ADMIN))
    assert len(records) == 1
    record = records[0]
    assert_escheat_record(record)
    assert record["dormancy_days"] == 180
    assert record["amount_cents"] == 1450
    assert record["jurisdiction"] == "TX"

    assert read_payout(ctx["payout"]["id"])["status"] == "ESCHEATED"
    assert read_claim(ctx["claim"]["id"])["payment_status"] == "ESCHEATED"


def test_escheat_reversal_returns_the_gross_while_the_record_captures_the_net(api):
    """PRD §3.9: "A ledger row of type `ESCHEAT_REVERSAL` is appended whose
    `amount_cents` is the claim's `final_rebate_cents`, which simultaneously lowers
    `committed_cents` and raises `escheat_recovered_cents`."
    PRD §3.9: "Note the deliberate asymmetry here and honour it: the escheat record
    captures the *net* amount actually surrendered (or the card's remaining
    balance), while the ledger reversal returns the *gross* committed amount, so
    that the program's `available_cents` comes back to exactly its pre-commitment
    value."

    Design: Difficulty/boundary_precision_check/check_dormancy_at_exactly_180_days_is_escheated
    """
    ctx = _released_check_awaiting_dormancy()
    set_clock("2027-01-06T00:00:00Z")

    records = validate_success(api.run_escheat_sweep(ctx["program"]["id"], ADMIN))
    assert records[0]["amount_cents"] == 1450

    program = read_program(ctx["program"]["id"])
    assert program["escheat_recovered_cents"] == 1600
    assert program["committed_cents"] == 0


def test_sweep_one_day_short_of_dormancy_returns_an_empty_array(api):
    """PRD §3.9: "A `ProgramAdmin` runs an escheat sweep over a program, and the
    sweep returns the records it created — an empty array when nothing was dormant,
    which is a successful outcome and never an error."

    Design: Corner/cross_cutting_complexity_layers/escheat_sweep_with_no_dormant_payout_returns_empty_array
    """
    ctx = setup_released_payout(
        method="CHECK",
        check_number="CHK-8888",
        program_overrides={"name": "Almost Dormant Program", "escheat_jurisdiction": "DE"},
        budget_total_cents=1000000,
        offer_overrides={"name": "Almost Dormant Offer"},
        claimant_overrides={
            "legal_name": "Almost Dealer",
            "email": "ad@ad.example",
            "mailing_state": "TX",
        },
        serial_number="SN-AD-1",
    )
    set_clock("2027-01-05T00:00:00Z")

    records = validate_success(api.run_escheat_sweep(ctx["program"]["id"], ADMIN))
    assert records == []

    assert read_payout(ctx["payout"]["id"])["status"] == "RELEASED"
    assert read_claim(ctx["claim"]["id"])["payment_status"] == "PAID"
    _, meta = validate_paginated(
        api.list_escheat_records(ADMIN, params={"program_id": ctx["program"]["id"]})
    )
    assert meta["total_count"] == 0
    assert read_program(ctx["program"]["id"])["escheat_recovered_cents"] == 0


def test_a_cleared_check_is_never_swept(api):
    """PRD §3.9: "The sweep walks the program's payouts in a single pass ordered by
    `released_at` ascending and then by `created_at` ascending, never by
    identifier, and considers only payouts currently in `RELEASED`. Payouts in
    `CLEARED`, `VOIDED`, `PENDING` or `REISSUE_PENDING` are never swept."

    Design: Corner/cross_cutting_complexity_layers/cleared_check_is_never_swept_by_escheat
    """
    ctx = setup_released_payout(
        method="CHECK",
        check_number="CHK-6000",
        program_overrides={"name": "Cleared Check Program", "escheat_jurisdiction": "DE"},
        budget_total_cents=1000000,
        offer_overrides={"name": "Cleared Check Offer"},
        claimant_overrides={
            "legal_name": "Cleared Dealer",
            "email": "cl@cl.example",
            "mailing_state": "TX",
        },
        serial_number="SN-CL-1",
    )
    set_clock("2026-07-20T00:00:00Z")
    validate_success(api.clear_payout(ctx["payout"]["id"], FINANCE))
    set_clock("2027-01-06T00:00:00Z")

    records = validate_success(api.run_escheat_sweep(ctx["program"]["id"], ADMIN))
    assert records == []

    assert read_payout(ctx["payout"]["id"])["status"] == "CLEARED"
    assert read_claim(ctx["claim"]["id"])["payment_status"] == "PAID"
    program = read_program(ctx["program"]["id"])
    assert program["committed_cents"] == 1600
    assert program["paid_cents"] == 1450


def test_card_dormancy_uses_last_activity_and_the_remaining_balance(api):
    """PRD §3.9: "For a payout whose `method` is `VIRTUAL_CARD`, the anchor is
    instead the `last_activity_at` of the card carrying that payout's identifier,
    the limit is 90 days, and the amount at stake is the card's
    `remaining_balance_cents`."
    PRD §3.9: "Any virtual card of that payout — in `ISSUED`, `ACTIVATED` or
    `PARTIALLY_USED` — moves to the terminal `ESCHEATED` state with its
    `remaining_balance_cents` set to zero."

    Design: Corner/calculations/card_dormancy_uses_last_activity_anchor_and_remaining_balance
    """
    ctx = setup_issued_card(
        program_overrides={"name": "Card Escheat Program"},
        budget_total_cents=1000000,
        offer_overrides={"name": "Card Escheat Offer"},
        claimant_overrides={
            "legal_name": "Dormant Consumer",
            "email": "dc@dc.example",
            "mailing_state": "FL",
        },
        serial_number="SN-CDR-1",
    )
    set_clock("2026-07-20T00:00:00Z")
    validate_success(api.activate_virtual_card(ctx["card"]["id"], ctx["headers"]))
    validate_success(
        api.spend_virtual_card(
            ctx["card"]["id"],
            {"amount_cents": 1000, "merchant_name": "Hardware Depot"},
            ctx["headers"],
        )
    )
    set_clock("2026-10-18T00:00:00Z")

    records = validate_success(api.run_escheat_sweep(ctx["program"]["id"], ADMIN))
    assert len(records) == 1
    assert records[0]["dormancy_days"] == 90
    assert records[0]["amount_cents"] == 1450
    assert records[0]["jurisdiction"] == "FL"

    card = read_virtual_card(ctx["card"]["id"])
    assert card["status"] == "ESCHEATED"
    assert card["remaining_balance_cents"] == 0
    assert read_payout(ctx["payout"]["id"])["status"] == "ESCHEATED"
    assert read_claim(ctx["claim"]["id"])["payment_status"] == "ESCHEATED"


def test_program_report_counts_claims_by_channel_and_status(api):
    """PRD §3.9: "A program's reporting snapshot echoes its `program_id` and
    reports, over every claim whose offer belongs to that program:
    `claims_submitted` as the count of claims with a non-null `submitted_at`;
    `claims_approved`, `claims_denied` and `claims_revoked` as the counts of claims
    currently in `APPROVED`, `DENIED` and `REVOKED` respectively;
    `dealer_claim_count` and `consumer_claim_count` as the counts of those
    submitted claims whose claimant's `type` is `DEALER` and `CONSUMER`
    respectively; `approved_rebate_cents` as the sum of `final_rebate_cents` over
    the approved claims; and `escheated_cents` as the sum of `amount_cents` over
    every escheat record belonging to the program."
    PRD §3.9: "Finally, `offer_breakdown` carries one row per offer of the program,
    ordered by `effective_start_date` ascending and then by `created_at` ascending
    — never by identifier — each row carrying that offer's `offer_id`, its
    `active_claim_count` and its own `approved_rebate_cents`."

    Design: Corner/calculations/program_report_counts_by_channel_and_status
    """
    set_clock("2026-07-10T00:00:00Z")
    program = create_active_program(name="Report Program", budget_total_cents=100000000)
    dealer_offer = create_published_offer(
        program["id"], name="Report Dealer Offer", channel="DEALER", sku_scope="TOOLS"
    )
    consumer_offer = create_published_offer(
        program["id"],
        name="Report Consumer Offer",
        channel="CONSUMER",
        sku_scope="APPLIANCE",
    )
    dealer = create_dealer_claimant(legal_name="Report Dealer", email="rd@rd.example")
    consumer = create_consumer_claimant(legal_name="Report Consumer", email="rc@rc.example")

    dealer_claim = open_claim(dealer_offer["id"], dealer)
    dealer_receipt = attach_receipt(
        dealer_claim["id"],
        dealer,
        serial_number="SN-RPT-D",
        lines=[{"sku": "TOOLS-A", "quantity": 10, "unit_price_cents": 1000}],
    )
    validate_success(api_client.submit_claim(dealer_claim["id"], make_dealer_headers(dealer["id"])))
    validate_success(api_client.review_claim(dealer_claim["id"], PROCESSOR))
    validate_receipt(dealer_receipt["id"])
    validate_success(api_client.approve_claim(dealer_claim["id"], PROCESSOR))

    consumer_claim = open_claim(consumer_offer["id"], consumer)
    attach_receipt(
        consumer_claim["id"],
        consumer,
        serial_number="SN-RPT-C",
        retailer_name="MegaMart",
        lines=[{"sku": "APPLIANCE-X", "quantity": 1, "unit_price_cents": 5000}],
    )
    validate_success(
        api_client.submit_claim(consumer_claim["id"], make_consumer_headers(consumer["id"]))
    )
    validate_success(api_client.review_claim(consumer_claim["id"], PROCESSOR))
    deny_claim(consumer_claim["id"], reason_code="NOT_ELIGIBLE_SKU")

    report = read_program_report(program["id"])
    assert report["claims_submitted"] == 2
    assert report["claims_approved"] == 1
    assert report["claims_denied"] == 1
    assert report["claims_revoked"] == 0
    assert report["dealer_claim_count"] == 1
    assert report["consumer_claim_count"] == 1
    assert report["approved_rebate_cents"] == 800
    assert report["escheated_cents"] == 0
    assert report["committed_cents"] == 800
    assert len(report["offer_breakdown"]) == 2
    assert report["offer_breakdown"][0]["offer_id"] == dealer_offer["id"]
    assert consumer_offer["id"] in {row["offer_id"] for row in report["offer_breakdown"]}
