"""Two calculations that must diverge on identical inputs: the two production
bases, and the two chargeback reversal variants."""
from test_helpers import (
    api_client,
    cancel_booking_payload,
    commission_receipt_payload,
    confirm_booking,
    make_advisor_headers,
    make_supplier_portal_headers,
    new_client,
    new_consortium,
    new_split_schedule,
    new_supplier,
    new_booking,
    read_advisor,
    read_booking,
    record_receipt,
    set_clock,
    setup_active_advisor,
    calculate_run,
    open_run,
    post_run,
    validate_success,
)

# The logical clock starts at 2026-08-01T00:00:00Z (PRD §2.5). Remittances are
# recorded after the clock has been moved to the instant they are dated, so a
# receipt is never earlier than the booking it pays for.
REMIT_CLOCK = "2026-10-05T00:00:00Z"
REMIT_DATE = "2026-10-05"
REMIT_PERIOD = "2026-10"

THREE_RUNG_TIERS = [
    {"tier_level": 1, "min_production_cents": 0, "advisor_pct": 0.70},
    {"tier_level": 2, "min_production_cents": 5_000_000, "advisor_pct": 0.80},
    {"tier_level": 3, "min_production_cents": 15_000_000, "advisor_pct": 0.90},
]
TWO_RUNG_FEE_TIERS = [
    {"min_share_cents": 0, "fee_pct": 0.05},
    {"min_share_cents": 1_000_000, "fee_pct": 0.03},
]


def _reference_data(probation_chargeback_threshold=2):
    """One schedule, one consortium and the two suppliers the scenarios use."""
    schedule = new_split_schedule(
        name="Standard 2026",
        tiers=THREE_RUNG_TIERS,
        platform_fee_tiers=TWO_RUNG_FEE_TIERS,
        chargeback_retention_pct=0.10,
    )
    consortium = new_consortium(
        name="Voyager Alliance",
        membership_fee_cents=5_000_000,
        marketing_fund_accrual_pct=0.02,
        consortium_channel_bonus_pct=0.01,
    )
    aurora = new_supplier(
        name="Aurora Cruises",
        accreditation_scheme="CLIA",
        base_commission_pct=0.10,
        preferred_override_commission_pct=0.15,
        rate_ceiling_pct=0.18,
        max_commission_per_booking_cents=500_000,
        remit_terms_days=30,
        consortium_id=consortium["id"],
        program_status="PREFERRED",
        probation_chargeback_threshold=probation_chargeback_threshold,
    )
    meridian = new_supplier(
        name="Meridian Air",
        accreditation_scheme="ARC",
        base_commission_pct=0.10,
        preferred_override_commission_pct=0.12,
        rate_ceiling_pct=0.20,
        max_commission_per_booking_cents=9_000_000,
        remit_terms_days=30,
    )
    return schedule, consortium, aurora, meridian


def _co_member_advisor(schedule, consortium, suppliers):
    ctx = setup_active_advisor(
        state="NY",
        legal_name="Dana Reyes",
        email="dana.reyes@example.com",
        consortium_id=consortium["id"],
        schedule=schedule,
        suppliers=suppliers,
        agreement_overrides={"effective_date": "2026-01-01", "post_departure_advisor_pct": 0.50},
    )
    client = new_client(
        ctx["advisor"]["id"],
        full_name="Nadia Okoye",
        home_state_code="NY",
        ownership_mode="ADVISOR_OWNED",
        max_concurrent_trips=4,
    )
    ctx["client"] = client
    return ctx


def _dual_basis_scenario():
    """A paid-but-short cruise booking and an unconfirmed air booking."""
    schedule, consortium, aurora, meridian = _reference_data()
    ctx = _co_member_advisor(schedule, consortium, [aurora, meridian])
    advisor, client = ctx["advisor"], ctx["client"]
    cruise = new_booking(
        advisor["id"],
        aurora["id"],
        client["id"],
        channel="CONSORTIUM",
        payment_method="MERCHANT_DIRECT",
        gross_sale_cents=1_000_000,
        travel_start_date="2026-06-01",
        travel_end_date="2026-06-10",
    )
    cruise = confirm_booking(cruise["id"], aurora["id"])
    air = new_booking(
        advisor["id"],
        meridian["id"],
        client["id"],
        channel="SUPPLIER_DIRECT",
        payment_method="MERCHANT_DIRECT",
        gross_sale_cents=60_000_000,
        travel_start_date="2026-09-01",
        travel_end_date="2026-09-10",
    )
    return {
        "advisor": advisor,
        "client": client,
        "aurora": aurora,
        "meridian": meridian,
        "cruise": cruise,
        "air": air,
    }


def test_short_payment_leaves_the_two_production_bases_on_different_tiers():
    """PRD §2.10: "Both are calendar-year-to-date figures, both are stored on the
    advisor row, and each drives its own split tier — `production_ytd_provisional_cents`
    drives `split_tier_provisional`, and `production_ytd_final_cents` drives
    `split_tier_final`."

    Design: Difficulty/dual_variant_calc/production_ytd_provisional_vs_final_diverge_by_tier
    """
    scenario = _dual_basis_scenario()
    set_clock(REMIT_CLOCK)

    validate_success(
        api_client.record_commission_receipt(
            scenario["cruise"]["id"],
            commission_receipt_payload(120_000, REMIT_DATE),
            make_supplier_portal_headers(scenario["aurora"]["id"]),
        )
    )

    advisor = read_advisor(scenario["advisor"]["id"])
    assert advisor["production_ytd_provisional_cents"] == 6_160_000
    assert advisor["split_tier_provisional"] == 2
    assert advisor["production_ytd_final_cents"] == 120_000
    assert advisor["split_tier_final"] == 1


def test_remittance_records_the_shortfall_without_disturbing_the_expected_amount():
    """PRD §3.7: "On success `received_commission_cents` takes the remitted amount,
    `commission_received_on` takes the `received_on` instant, `shortfall_cents`
    becomes `expected_commission_cents` less `received_commission_cents` — a figure
    that is zero before any receipt is recorded and never negative, since the receipt
    can never exceed the expectation — and the money axis advances `EXPECTED` to
    `RECEIVED`."

    Design: Difficulty/dual_variant_calc/production_ytd_provisional_vs_final_diverge_by_tier
    """
    scenario = _dual_basis_scenario()
    set_clock(REMIT_CLOCK)

    paid = validate_success(
        api_client.record_commission_receipt(
            scenario["cruise"]["id"],
            commission_receipt_payload(120_000, REMIT_DATE),
            make_supplier_portal_headers(scenario["aurora"]["id"]),
        )
    )

    assert paid["expected_commission_cents"] == 160_000
    assert paid["received_commission_cents"] == 120_000
    assert paid["shortfall_cents"] == 40_000
    assert paid["commission_status"] == "RECEIVED"

    air = read_booking(scenario["air"]["id"])
    assert air["expected_commission_cents"] == 6_000_000
    assert air["received_commission_cents"] == 0
    assert air["commission_status"] == "PENDING"


def _settled_pair_scenario():
    """Two identical settled cruise bookings under one advisor, ready to cancel."""
    schedule, consortium, aurora, _meridian = _reference_data(
        probation_chargeback_threshold=5
    )
    ctx = _co_member_advisor(schedule, consortium, [aurora])
    advisor, client = ctx["advisor"], ctx["client"]
    windows = (("2026-06-01", "2026-06-10"), ("2026-06-11", "2026-06-20"))
    bookings = []
    for start, end in windows:
        booking = new_booking(
            advisor["id"],
            aurora["id"],
            client["id"],
            channel="CONSORTIUM",
            payment_method="MERCHANT_DIRECT",
            gross_sale_cents=1_000_000,
            travel_start_date=start,
            travel_end_date=end,
        )
        bookings.append(confirm_booking(booking["id"], aurora["id"]))
    set_clock(REMIT_CLOCK)
    for booking in bookings:
        record_receipt(booking["id"], aurora["id"], 160_000, REMIT_DATE)
    run = open_run(REMIT_PERIOD)
    calculate_run(run["id"], "ctrl-1")
    post_run(run["id"], "ctrl-2")
    return {
        "advisor": advisor,
        "aurora": aurora,
        "first": read_booking(bookings[0]["id"]),
        "second": read_booking(bookings[1]["id"]),
    }


def test_client_initiated_cancellation_claws_back_the_entire_settled_share():
    """PRD §3.6: "Where the reason is `CLIENT_INITIATED` or `ADVISOR_ERROR`, the full
    settled share is clawed back: `chargeback_amount_cents` is set to exactly the
    booking's `settled_share_cents`."

    Design: Difficulty/dual_variant_calc/chargeback_gross_reversal_vs_net_of_retention_diverge
    """
    scenario = _settled_pair_scenario()
    assert scenario["first"]["settled_share_cents"] == 112_000

    cancelled = validate_success(
        api_client.cancel_booking(
            scenario["first"]["id"],
            cancel_booking_payload("CLIENT_INITIATED"),
            make_advisor_headers(scenario["advisor"]["id"]),
        )
    )

    assert cancelled["booking_status"] == "CANCELLED"
    assert cancelled["commission_status"] == "CHARGED_BACK"
    assert cancelled["chargeback_amount_cents"] == 112_000
    assert cancelled["settled_share_cents"] == 112_000


def test_supplier_initiated_cancellation_leaves_the_advisor_a_tenth_of_the_share():
    """PRD §3.6: "Where the reason is `SUPPLIER_INITIATED`, the advisor keeps a
    retention: `chargeback_amount_cents` is the booking's `settled_share_cents`
    multiplied by one minus the `chargeback_retention_pct` of the schedule reached
    through the booking's pinned `agreement_id`, rounded half up to whole cents."

    Design: Difficulty/dual_variant_calc/chargeback_gross_reversal_vs_net_of_retention_diverge
    """
    scenario = _settled_pair_scenario()
    assert scenario["second"]["settled_share_cents"] == 112_000

    gross_reversal = validate_success(
        api_client.cancel_booking(
            scenario["first"]["id"],
            cancel_booking_payload("CLIENT_INITIATED"),
            make_advisor_headers(scenario["advisor"]["id"]),
        )
    )
    net_reversal = validate_success(
        api_client.cancel_booking(
            scenario["second"]["id"],
            cancel_booking_payload("SUPPLIER_INITIATED"),
            make_advisor_headers(scenario["advisor"]["id"]),
        )
    )

    assert net_reversal["chargeback_amount_cents"] == 100_800
    assert net_reversal["settled_share_cents"] == 112_000
    assert net_reversal["commission_status"] == "CHARGED_BACK"
    assert (
        gross_reversal["chargeback_amount_cents"]
        - net_reversal["chargeback_amount_cents"]
        == 11_200
    )
