"""The four-step pricing rule across every rate-selection branch."""
import pytest

from test_helpers import (
    api_client,
    create_booking_payload,
    make_advisor_headers,
    new_client,
    new_consortium,
    new_split_schedule,
    new_supplier,
    setup_active_advisor,
    validate_success,
)

STANDARD_TIERS = [
    {"tier_level": 1, "min_production_cents": 0, "advisor_pct": 0.70},
    {"tier_level": 2, "min_production_cents": 5_000_000, "advisor_pct": 0.80},
]
FLAT_FEE_TIERS = [{"min_share_cents": 0, "fee_pct": 0.05}]


def _rate_matrix_scenario():
    """A co-member advisor holding accreditations with two preferred suppliers."""
    schedule = new_split_schedule(
        name="Standard 2026",
        tiers=STANDARD_TIERS,
        platform_fee_tiers=FLAT_FEE_TIERS,
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
        probation_chargeback_threshold=5,
    )
    cobalt = new_supplier(
        name="Cobalt Rail",
        accreditation_scheme="TIDS",
        base_commission_pct=0.10,
        preferred_override_commission_pct=0.15,
        rate_ceiling_pct=0.152,
        max_commission_per_booking_cents=9_000_000,
        remit_terms_days=30,
        consortium_id=consortium["id"],
        program_status="PREFERRED",
        probation_chargeback_threshold=5,
    )
    ctx = setup_active_advisor(
        state="NY",
        legal_name="Dana Reyes",
        email="dana.reyes@example.com",
        consortium_id=consortium["id"],
        schedule=schedule,
        suppliers=[aurora, cobalt],
    )
    client = new_client(
        ctx["advisor"]["id"],
        full_name="Nadia Okoye",
        home_state_code="NY",
        max_concurrent_trips=6,
    )
    return {
        "advisor": ctx["advisor"],
        "client": client,
        "aurora": aurora,
        "cobalt": cobalt,
    }


def _submit(scenario, supplier, channel, gross_sale_cents, start, end):
    payload = create_booking_payload(
        scenario["advisor"]["id"],
        supplier["id"],
        scenario["client"]["id"],
        channel=channel,
        payment_method="MERCHANT_DIRECT",
        gross_sale_cents=gross_sale_cents,
        travel_start_date=start,
        travel_end_date=end,
    )
    return validate_success(
        api_client.create_booking(payload, make_advisor_headers(scenario["advisor"]["id"])),
        201,
    )


def test_preferred_override_and_consortium_bonus_stack_for_a_co_member():
    """PRD §3.5: "When the supplier's `program_status` is `PREFERRED`, the supplier's
    `consortium_id` is not null, and that `consortium_id` equals the advisor's
    `consortium_id`, the base rate is the supplier's
    `preferred_override_commission_pct`."

    Design: Difficulty/combinatorial_formula/expected_commission_mode_a_rate_selection_matrix
    """
    scenario = _rate_matrix_scenario()

    booking = _submit(
        scenario, scenario["aurora"], "CONSORTIUM", 1_000_000, "2026-10-01", "2026-10-10"
    )

    assert booking["commissionable_base_cents"] == 1_000_000
    assert booking["applied_commission_rate"] == pytest.approx(0.16)
    assert booking["expected_commission_cents"] == 160_000


def test_channel_bonus_is_zero_on_supplier_direct_and_five_thousandths_on_the_host_tool():
    """PRD §3.5: "Otherwise, when the `channel` is `INTERNAL_TOOL`, the bonus is five
    thousandths — a flat half a percentage point granted for keeping the reservation
    on the host's own booking tool."

    Design: Difficulty/combinatorial_formula/expected_commission_mode_a_rate_selection_matrix
    """
    scenario = _rate_matrix_scenario()

    direct = _submit(
        scenario, scenario["aurora"], "SUPPLIER_DIRECT", 1_000_000, "2026-10-11", "2026-10-20"
    )
    internal = _submit(
        scenario, scenario["aurora"], "INTERNAL_TOOL", 1_000_000, "2026-10-21", "2026-10-30"
    )

    assert direct["applied_commission_rate"] == pytest.approx(0.15)
    assert direct["expected_commission_cents"] == 150_000
    assert internal["applied_commission_rate"] == pytest.approx(0.155)
    assert internal["expected_commission_cents"] == 155_000


def test_rate_ceiling_binds_before_the_per_booking_cash_cap():
    """PRD §3.5: "The raw amount is `commissionable_base_cents` multiplied by that
    effective rate; it is rounded half up to whole cents, and
    `expected_commission_cents` is then the lesser of that rounded amount and the
    supplier's `max_commission_per_booking_cents`."

    Design: Difficulty/combinatorial_formula/expected_commission_mode_a_rate_selection_matrix
    """
    scenario = _rate_matrix_scenario()

    capped = _submit(
        scenario, scenario["aurora"], "CONSORTIUM", 5_000_000, "2026-11-01", "2026-11-10"
    )
    ceilinged = _submit(
        scenario, scenario["cobalt"], "CONSORTIUM", 1_000_000, "2026-11-11", "2026-11-20"
    )

    assert capped["applied_commission_rate"] == pytest.approx(0.16)
    assert capped["expected_commission_cents"] == 500_000
    assert ceilinged["applied_commission_rate"] == pytest.approx(0.152)
    assert ceilinged["expected_commission_cents"] == 152_000
