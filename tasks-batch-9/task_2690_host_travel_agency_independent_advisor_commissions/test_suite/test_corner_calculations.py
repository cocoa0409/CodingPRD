"""Pricing constants, rounding direction, input-set filtering and claim aging."""
import pytest

from test_helpers import (
    cancel_booking,
    confirm_booking,
    file_claim,
    mark_traveled,
    new_booking,
    new_client,
    new_split_schedule,
    new_supplier,
    read_advisor,
    read_booking,
    read_claim,
    read_supplier,
    set_clock,
    setup_active_advisor,
)

STANDARD_TIERS = [
    {"tier_level": 1, "min_production_cents": 0, "advisor_pct": 0.70},
    {"tier_level": 2, "min_production_cents": 5_000_000, "advisor_pct": 0.80},
]
FLAT_FEE_TIERS = [{"min_share_cents": 0, "fee_pct": 0.05}]

MERIDIAN = {
    "name": "Meridian Air",
    "accreditation_scheme": "ARC",
    "base_commission_pct": 0.10,
    "preferred_override_commission_pct": 0.12,
    "rate_ceiling_pct": 0.20,
    "max_commission_per_booking_cents": 9_000_000,
    "remit_terms_days": 30,
}
CABO_RAIL = {
    "name": "Cabo Rail",
    "accreditation_scheme": "IATA",
    "base_commission_pct": 0.10,
    "preferred_override_commission_pct": 0.12,
    "rate_ceiling_pct": 0.10,
    "max_commission_per_booking_cents": 9_000_000,
    "remit_terms_days": 45,
}


def _standard_schedule():
    return new_split_schedule(
        name="Standard 2026",
        tiers=STANDARD_TIERS,
        platform_fee_tiers=FLAT_FEE_TIERS,
        chargeback_retention_pct=0.10,
    )


def _advisor_accredited_with(*suppliers):
    ctx = setup_active_advisor(
        state="NY",
        legal_name="Dana Reyes",
        email="dana.reyes@example.com",
        schedule=_standard_schedule(),
        suppliers=list(suppliers),
    )
    client = new_client(
        ctx["advisor"]["id"],
        full_name="Nadia Okoye",
        home_state_code="NY",
        max_concurrent_trips=4,
    )
    return ctx["advisor"], client


def test_the_internal_tool_bonus_is_added_and_then_clamped_by_the_ceiling():
    """PRD §3.5: "Otherwise, when the `channel` is `INTERNAL_TOOL`, the bonus is five
    thousandths — a flat half a percentage point granted for keeping the reservation on the
    host's own booking tool."

    Design: Corner/calculations/corner_internal_tool_bonus_constant_and_rate_ceiling_clamp
    """
    meridian = new_supplier(**MERIDIAN)
    cabo = new_supplier(**CABO_RAIL)
    advisor, client = _advisor_accredited_with(meridian, cabo)

    bonused = new_booking(
        advisor["id"],
        meridian["id"],
        client["id"],
        channel="INTERNAL_TOOL",
        payment_method="MERCHANT_DIRECT",
        gross_sale_cents=1_000_000,
        travel_start_date="2026-10-01",
        travel_end_date="2026-10-10",
    )
    clamped = new_booking(
        advisor["id"],
        cabo["id"],
        client["id"],
        channel="INTERNAL_TOOL",
        payment_method="MERCHANT_DIRECT",
        gross_sale_cents=1_000_000,
        travel_start_date="2026-10-11",
        travel_end_date="2026-10-20",
    )

    assert bonused["applied_commission_rate"] == pytest.approx(0.105)
    assert bonused["expected_commission_cents"] == 105_000
    assert clamped["applied_commission_rate"] == pytest.approx(0.10)
    assert clamped["expected_commission_cents"] == 100_000

    assert bonused["commissionable_base_cents"] == 1_000_000
    assert clamped["commissionable_base_cents"] == 1_000_000
    assert read_advisor(advisor["id"])["production_ytd_provisional_cents"] == 205_000


def test_a_raw_half_cent_rounds_up_while_a_shade_less_rounds_down():
    """PRD §3.5: "The raw amount is `commissionable_base_cents` multiplied by that effective
    rate; it is rounded half up to whole cents, and `expected_commission_cents` is then the
    lesser of that rounded amount and the supplier's `max_commission_per_booking_cents`."

    Design: Corner/calculations/corner_round_half_up_on_expected_commission_half_cent
    """
    supplier = new_supplier(**MERIDIAN)
    advisor, client = _advisor_accredited_with(supplier)

    rounded_up = new_booking(
        advisor["id"],
        supplier["id"],
        client["id"],
        channel="SUPPLIER_DIRECT",
        payment_method="MERCHANT_DIRECT",
        gross_sale_cents=1_000_005,
        travel_start_date="2026-10-01",
        travel_end_date="2026-10-10",
    )
    rounded_down = new_booking(
        advisor["id"],
        supplier["id"],
        client["id"],
        channel="SUPPLIER_DIRECT",
        payment_method="MERCHANT_DIRECT",
        gross_sale_cents=1_000_004,
        travel_start_date="2026-10-11",
        travel_end_date="2026-10-20",
    )

    assert rounded_up["expected_commission_cents"] == 100_001
    assert rounded_down["expected_commission_cents"] == 100_000
    assert rounded_up["applied_commission_rate"] == pytest.approx(0.10)
    assert rounded_down["applied_commission_rate"] == pytest.approx(0.10)
    assert read_advisor(advisor["id"])["production_ytd_provisional_cents"] == 200_001


def test_a_written_off_booking_leaves_the_provisional_set():
    """PRD §3.5: "Taking the calendar year of the current logical clock, with the year's
    first instant inclusive and the next year's first instant exclusive, the provisional set
    comprises this advisor's bookings whose `booking_status` is `SUBMITTED`, `CONFIRMED` or
    `TRAVELED`, whose `commission_status` is neither `CHARGED_BACK` nor `WRITTEN_OFF`, and
    whose `travel_start_date` falls inside that year window."

    Design: Corner/calculations/corner_provisional_production_excludes_written_off_bookings
    """
    supplier = new_supplier(**MERIDIAN)
    advisor, client = _advisor_accredited_with(supplier)

    def _confirmed(gross, start, end):
        booking = new_booking(
            advisor["id"],
            supplier["id"],
            client["id"],
            channel="SUPPLIER_DIRECT",
            payment_method="MERCHANT_DIRECT",
            gross_sale_cents=gross,
            travel_start_date=start,
            travel_end_date=end,
        )
        return confirm_booking(booking["id"], supplier["id"])

    kept = _confirmed(2_000_000, "2026-10-01", "2026-10-10")
    doomed = _confirmed(1_000_000, "2026-10-11", "2026-10-20")
    assert read_advisor(advisor["id"])["production_ytd_provisional_cents"] == 300_000
    assert kept["commission_status"] == "EXPECTED"
    assert doomed["commission_status"] == "EXPECTED"
    assert read_supplier(supplier["id"])["total_outstanding_cents"] == 0

    cancelled = cancel_booking(doomed["id"], advisor["id"], "CLIENT_INITIATED")
    assert cancelled["commission_status"] == "WRITTEN_OFF"
    assert cancelled["booking_status"] == "CANCELLED"

    after = read_advisor(advisor["id"])
    assert after["production_ytd_provisional_cents"] == 200_000
    assert after["production_ytd_final_cents"] == 0

    survivor = read_booking(kept["id"])
    assert survivor["commission_status"] == "EXPECTED"
    assert survivor["expected_commission_cents"] == 200_000
    assert read_supplier(supplier["id"])["total_outstanding_cents"] == 0


def test_claim_escalation_flips_exactly_on_its_two_day_thresholds():
    """PRD §3.7: "Aging is not reset by a new round: `aging_days` is the floored whole count
    of UTC days from the claim's `created_at` to the logical clock and is unaffected by
    `round_count`, and `escalation_level` is `NORMAL` below sixty days, `ESCALATED` from sixty
    days up to but not including one hundred and twenty, and `CRITICAL` at one hundred and
    twenty days or more — so an age of 59 is still `NORMAL`, 60 is `ESCALATED`, 119 is
    `ESCALATED` and 120 is `CRITICAL`."

    Design: Corner/calculations/corner_claim_escalation_threshold_days
    """
    supplier = new_supplier(**MERIDIAN)
    advisor, client = _advisor_accredited_with(supplier)
    booking = new_booking(
        advisor["id"],
        supplier["id"],
        client["id"],
        channel="SUPPLIER_DIRECT",
        payment_method="MERCHANT_DIRECT",
        gross_sale_cents=1_000_000,
        travel_start_date="2026-05-01",
        travel_end_date="2026-05-10",
    )
    confirm_booking(booking["id"], supplier["id"])
    mark_traveled(booking["id"])

    claim = file_claim(booking["id"], advisor["id"], 100_000)
    assert claim["aging_days"] == 0
    assert claim["escalation_level"] == "NORMAL"
    assert claim["round_count"] == 1
    assert read_booking(booking["id"])["commission_status"] == "CLAIMED"

    refreshed = set_clock("2026-09-29T00:00:00Z")
    assert refreshed["refreshed_claim_count"] == 1
    at_59 = read_claim(claim["id"])
    assert at_59["aging_days"] == 59
    assert at_59["escalation_level"] == "NORMAL"

    set_clock("2026-09-30T00:00:00Z")
    at_60 = read_claim(claim["id"])
    assert at_60["aging_days"] == 60
    assert at_60["escalation_level"] == "ESCALATED"

    set_clock("2026-11-28T00:00:00Z")
    at_119 = read_claim(claim["id"])
    assert at_119["aging_days"] == 119
    assert at_119["escalation_level"] == "ESCALATED"

    set_clock("2026-11-29T00:00:00Z")
    at_120 = read_claim(claim["id"])
    assert at_120["aging_days"] == 120
    assert at_120["escalation_level"] == "CRITICAL"
    assert at_120["status"] == "SUBMITTED"
