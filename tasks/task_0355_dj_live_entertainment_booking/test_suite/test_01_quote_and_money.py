"""Quote assembly, deposit, travel fee, overtime, and cancellation-fee money math.

Covers Difficulty queue rules dual_variant_calc, combinatorial_formula (calc
branches), boundary_precision_check (overtime), and the corner calculations
section, all of which exercise PRD §2.5 / §3.4 / §3.7 / §3.9 monetary contracts.
"""
import pytest

from test_helpers import (
    validate_success,
    fixtures as fx,
    api_client,
)
from test_helpers.test_users import make_client_headers

AGENT = fx.AGENT
ADMIN = fx.ADMIN


# =====================================================================
# Difficulty/dual_variant_calc
# =====================================================================
def test_quote_provisional_versus_final_total_diverge_by_overtime(api):
    """PRD §3.4: "Overtime is deliberately excluded from the quote — it is realized
    only when the set is actually performed."
    PRD §3.7: "The final grand total, stored as `final_total_cents`, is the quote
    total plus the overtime charge"

    Design: Difficulty/dual_variant_calc/quote_provisional_vs_final_total_diverge_on_booking
    """
    cat = fx.setup_charged_catalogue()
    bk = fx.create_booking(cat, event_zone_id=cat["zevent_id"], miles=20,
                           event_start_utc="2026-08-01T20:00:00Z", contracted_set_minutes=120)
    held = fx.hold_booking(bk["id"])
    issued = fx.issue_contract(bk["id"], held["version"])
    ct_id = fx.get_first_contract_id(bk["id"])
    fx.sign_contract(ct_id, cat["cli_id"])
    dep = fx.create_payment(bk["id"], kind="DEPOSIT", amount_cents=81000)
    fx.capture_payment(dep["id"])
    fx.set_clock("2026-08-01T20:00:00Z")
    fx.api_client.start_set(bk["id"], AGENT)

    resp = api.complete_set(bk["id"], 150, AGENT)
    data = validate_success(resp)

    assert data["quote_total_cents"] == 324000, data["quote_total_cents"]
    assert data["overtime_cents"] == 6000, data["overtime_cents"]
    assert data["final_total_cents"] == 330000, data["final_total_cents"]
    assert data["final_total_cents"] - data["quote_total_cents"] == 6000


def test_final_total_recomputes_balance_after_overtime(api):
    """PRD §3.7: "The final grand total, stored as `final_total_cents`, is the quote
    total plus the overtime charge, and the `balance_due_cents` is recomputed as that
    final total minus `amount_paid_cents`."

    Design: Difficulty/dual_variant_calc/quote_provisional_vs_final_total_diverge_on_booking
    """
    cat = fx.setup_charged_catalogue()
    cat2, confirmed, ct_id, dep = fx.create_confirmed_booking(
        cat, deposit_cents=81000, event_zone_id=cat["zevent_id"], miles=20,
        event_start_utc="2026-08-01T20:00:00Z", contracted_set_minutes=120,
    )
    performed = fx.advance_to_performed(confirmed["id"], actual_set_minutes=150)

    # deposit 81000 captured; final 330000 -> balance 330000 - 81000
    assert performed["final_total_cents"] == 330000, performed["final_total_cents"]
    assert performed["amount_paid_cents"] == 81000, performed["amount_paid_cents"]
    assert performed["balance_due_cents"] == 249000, performed["balance_due_cents"]


def test_travel_fee_waived_in_home_zone_versus_charged_in_event_zone(api):
    """PRD §3.4: "If the event zone equals the performer's home zone — that is,
    `event_zone_id` equals the performer's `home_zone_id` — the travel fee is exactly
    0 regardless of mileage or any surge multiplier; this home-zone waiver
    short-circuits the entire travel computation."
    PRD §3.4: "Otherwise, the raw travel amount is the event zone's
    `base_travel_fee_cents` plus its `per_mile_fee_cents` multiplied by
    `event_miles_from_home`. That raw amount is then multiplied by the event zone's
    `surge_multiplier_bps`, divided by 10000, and rounded half up to whole cents to
    yield the travel fee."

    Design: Difficulty/dual_variant_calc/travel_fee_waiver_vs_charged_diverge_on_zone
    """
    cat = fx.setup_charged_catalogue()
    bk_home = fx.create_booking(cat, event_zone_id=cat["zhome_id"], miles=20,
                                event_start_utc="2026-08-01T20:00:00Z")
    held_home = fx.hold_booking(bk_home["id"])
    assert held_home["quote_total_cents"] == 300000, held_home["quote_total_cents"]

    bk_event = fx.create_booking(cat, event_zone_id=cat["zevent_id"], miles=20,
                                 event_start_utc="2026-09-05T20:00:00Z")
    resp = api.hold_booking(bk_event["id"], AGENT)
    held_event = validate_success(resp)

    assert held_event["quote_total_cents"] == 324000, held_event["quote_total_cents"]
    assert held_event["quote_total_cents"] - held_home["quote_total_cents"] == 24000


# =====================================================================
# Difficulty/combinatorial_formula (calc branches)
# =====================================================================
def test_home_zone_waiver_ignores_mileage_and_surge(api):
    """PRD §3.4: "If the event zone equals the performer's home zone — that is,
    `event_zone_id` equals the performer's `home_zone_id` — the travel fee is exactly
    0 regardless of mileage or any surge multiplier; this home-zone waiver
    short-circuits the entire travel computation."

    Design: Difficulty/dual_variant_calc/travel_fee_waiver_vs_charged_diverge_on_zone
    """
    cat = fx.setup_home_catalogue()
    bk = fx.create_booking(cat, event_zone_id=cat["zhome_id"], miles=500,
                           event_start_utc="2026-08-01T20:00:00Z", contracted_set_minutes=120)
    resp = api.hold_booking(bk["id"], AGENT)
    held = validate_success(resp)
    # set 200000 + package 50000, travel waived despite 500 miles -> 250000
    assert held["quote_total_cents"] == 250000, held["quote_total_cents"]


def test_quote_combines_set_package_equipment_and_surged_travel(api):
    """PRD §3.4: "First, the performer's `base_set_rate_cents` is taken as the set
    rate. Second, the package's `flat_package_fee_cents` is added. Third, the
    equipment fee is computed as the sum of `unit_fee_cents` across every equipment
    line item whose `package_id` matches the booking's package — this sum is evaluated
    before travel is added. Fourth, the travel fee is added."
    PRD §3.4: "The required deposit is computed at the same hold step. It equals the
    quote total multiplied by the package's `deposit_pct_bps`, divided by 10000, and
    rounded half up to whole cents, and is stored as `deposit_required_cents`."

    Design: Difficulty/combinatorial_formula/quote_total_mode_a_nonlinear_threshold_branch
    """
    cat = fx.setup_charged_catalogue()
    bk = fx.create_booking(cat, event_zone_id=cat["zevent_id"], miles=20,
                           event_start_utc="2026-08-01T20:00:00Z", contracted_set_minutes=120)
    resp = api.hold_booking(bk["id"], AGENT)
    data = validate_success(resp)

    assert data["quote_total_cents"] == 324000, data["quote_total_cents"]
    assert data["deposit_required_cents"] == 81000, data["deposit_required_cents"]


def test_quote_excludes_overtime_at_hold(api):
    """PRD §3.4: "Overtime is deliberately excluded from the quote — it is realized
    only when the set is actually performed."

    Design: Difficulty/combinatorial_formula/quote_total_mode_a_nonlinear_threshold_branch
    """
    cat = fx.setup_charged_catalogue()
    bk = fx.create_booking(cat, event_zone_id=cat["zevent_id"], miles=20,
                           event_start_utc="2026-08-01T20:00:00Z", contracted_set_minutes=120)
    resp = api.hold_booking(bk["id"], AGENT)
    data = validate_success(resp)
    assert data["quote_total_cents"] == 324000, data["quote_total_cents"]
    assert data["overtime_cents"] == 0, data["overtime_cents"]


def test_cancellation_fee_applies_lead_tier_then_confirmed_surcharge_in_order(api):
    """PRD §3.9: "When the lead time is 30 days or more, the fee is 10% of the quote
    total"
    PRD §3.9: "A booking that is in `CONFIRMED` at the moment of cancellation carries
    an additional surcharge of 10 percentage points added to whichever lead-time tier
    applies, with the combined fee capped at 100% of the quote total. The resulting
    cancellation fee in cents is the quote total multiplied by the applicable fraction
    in basis points, divided by 10000, and rounded half up to whole cents; it is stored
    as `cancellation_fee_cents`."

    Design: Difficulty/combinatorial_formula/cancellation_fee_mode_c_ordered_tier_then_surcharge
    """
    cat = fx.setup_charged_catalogue()
    # lead 48 days from 2026-06-14 to 2026-08-01 -> 10% tier; CONFIRMED -> +10pp = 20%
    cat2, confirmed, ct_id, dep = fx.create_confirmed_booking(
        cat, deposit_cents=81000, event_zone_id=cat["zevent_id"], miles=20,
        event_start_utc="2026-08-01T20:00:00Z",
    )
    resp = api.cancel_booking(confirmed["id"], AGENT)
    data = validate_success(resp)

    assert data["status"] == "CANCELLED"
    assert data["cancellation_fee_cents"] == 64800, data["cancellation_fee_cents"]


def test_cancellation_confirmed_surcharge_capped_at_full_quote(api):
    """PRD §3.9: "and when it is fewer than 7 days — including an event that has already
    passed — the fee is 100%."
    PRD §3.9: "A booking that is in `CONFIRMED` at the moment of cancellation carries an
    additional surcharge of 10 percentage points added to whichever lead-time tier
    applies, with the combined fee capped at 100% of the quote total."

    Design: Difficulty/combinatorial_formula/cancellation_fee_mode_c_ordered_tier_then_surcharge
    """
    cat = fx.setup_home_catalogue()
    # CONFIRMED booking; then move clock to within 7 days of the event (100% tier),
    # CONFIRMED surcharge +10pp -> capped at 100% of quote 250000.
    cat2, confirmed, ct_id, dep = fx.create_confirmed_booking(cat, deposit_cents=62500,
                                                              contracted_set_minutes=120)
    fx.set_clock("2026-07-30T00:00:00Z")  # 2 days before event -> <7 day tier
    resp = api.cancel_booking(confirmed["id"], AGENT)
    data = validate_success(resp)
    assert data["status"] == "CANCELLED"
    assert data["cancellation_fee_cents"] == 250000, data["cancellation_fee_cents"]


# =====================================================================
# Difficulty/boundary_precision_check (overtime boundary)
# =====================================================================
def test_overtime_zero_at_exactly_contracted_minutes(api):
    """PRD §3.7: "so zero extra minutes bill zero blocks, exactly the contracted
    length bills zero blocks, and a single minute over the contracted length bills one
    full block."

    Design: Difficulty/boundary_precision_check/overtime_zero_at_exactly_contracted_minutes
    """
    cat = fx.setup_home_catalogue()
    cat2, confirmed, ct_id, dep = fx.create_confirmed_booking(cat, deposit_cents=62500,
                                                              contracted_set_minutes=120)
    performed = fx.advance_to_performed(confirmed["id"], actual_set_minutes=120)

    assert performed["overtime_cents"] == 0, performed["overtime_cents"]
    assert performed["quote_total_cents"] == 250000, performed["quote_total_cents"]
    assert performed["final_total_cents"] == 250000, performed["final_total_cents"]


def test_overtime_one_started_block_for_partial_extra(api):
    """PRD §3.7: "Those extra minutes are billed per started 15-minute block — the
    number of blocks is the extra minutes divided by 15 and rounded up to the next
    whole block, so zero extra minutes bill zero blocks, exactly the contracted length
    bills zero blocks, and a single minute over the contracted length bills one full
    block."

    Design: Difficulty/boundary_precision_check/overtime_zero_at_exactly_contracted_minutes
    """
    cat = fx.setup_home_catalogue()
    cat2, confirmed, ct_id, dep = fx.create_confirmed_booking(cat, deposit_cents=62500,
                                                              contracted_set_minutes=120)
    # 130 actual vs 120 contracted -> 10 extra -> ceil(10/15) == 1 block -> 3000
    performed = fx.advance_to_performed(confirmed["id"], actual_set_minutes=130)
    assert performed["overtime_cents"] == 3000, performed["overtime_cents"]
    assert performed["final_total_cents"] == 253000, performed["final_total_cents"]


# =====================================================================
# Corner/calculations
# =====================================================================
def test_deposit_required_rounds_quote_times_deposit_pct(api):
    """PRD §3.4: "The required deposit is computed at the same hold step. It equals
    the quote total multiplied by the package's `deposit_pct_bps`, divided by 10000,
    and rounded half up to whole cents, and is stored as `deposit_required_cents`."

    Design: Corner/calculations/deposit_required_rounding_correct
    """
    cat, held = fx.create_held_booking(contracted_set_minutes=120)

    assert held["quote_total_cents"] == 250000, held["quote_total_cents"]
    assert held["deposit_required_cents"] == 62500, held["deposit_required_cents"]


def test_overtime_one_extra_minute_bills_one_block(api):
    """PRD §3.7: "Those extra minutes are billed per started 15-minute block — the
    number of blocks is the extra minutes divided by 15 and rounded up to the next
    whole block, so zero extra minutes bill zero blocks, exactly the contracted length
    bills zero blocks, and a single minute over the contracted length bills one full
    block. The overtime charge, stored as `overtime_cents`, is the number of blocks
    multiplied by the performer's `overtime_rate_cents_per_15min`."

    Design: Corner/calculations/overtime_one_extra_minute_bills_one_block
    """
    cat = fx.setup_home_catalogue()
    cat2, confirmed, ct_id, dep = fx.create_confirmed_booking(cat, deposit_cents=62500,
                                                              contracted_set_minutes=120)
    performed = fx.advance_to_performed(confirmed["id"], actual_set_minutes=121)

    assert performed["overtime_cents"] == 3000, performed["overtime_cents"]
    assert performed["final_total_cents"] == 253000, performed["final_total_cents"]


def test_cancellation_tier_25pct_at_lead_20_days_on_hold(api):
    """PRD §3.9: "when it is at least 14 days but fewer than 30, the fee is 25%"
    PRD §3.9: "The lead time in whole days is the difference between the event start
    and the current clock, expressed in whole UTC days by taking the total seconds
    between them and dividing by 86400 with the fractional part discarded."

    Design: Corner/calculations/cancellation_tier_25pct_at_lead_20_days
    """
    fx.set_clock("2026-07-12T00:00:00Z")
    zhome = fx.create_home_zone()
    pkg = fx.create_package()
    perf = fx.create_performer(zhome["id"])
    cli = fx.create_client()
    cat = {"zhome_id": zhome["id"], "pkg_id": pkg["id"], "perf_id": perf["id"],
           "cli_id": cli["id"]}
    bk = fx.create_booking(cat, event_zone_id=zhome["id"],
                           event_start_utc="2026-08-01T20:00:00Z", contracted_set_minutes=120)
    fx.hold_booking(bk["id"])

    resp = api.cancel_booking(bk["id"], AGENT)
    data = validate_success(resp)

    assert data["cancellation_fee_cents"] == 62500, data["cancellation_fee_cents"]
    assert data["status"] == "CANCELLED"


def test_equipment_sum_drives_quote(api):
    """PRD §3.4: "the equipment fee is computed as the sum of `unit_fee_cents` across
    every equipment line item whose `package_id` matches the booking's package — this
    sum is evaluated before travel is added."

    Design: Corner/calculations/equipment_sum_drives_quote
    """
    cat = fx.setup_home_catalogue(with_equipment=True)
    bk = fx.create_booking(cat, event_zone_id=cat["zhome_id"],
                           event_start_utc="2026-08-01T20:00:00Z", contracted_set_minutes=120)
    resp = api.hold_booking(bk["id"], AGENT)
    data = validate_success(resp)

    assert data["quote_total_cents"] == 300000, data["quote_total_cents"]


# =====================================================================
# Corner/cross_cutting_complexity_layers (rate_threshold_triggers)
# =====================================================================
def test_cancellation_tier_50pct_at_lead_10_days_on_hold(api):
    """PRD §3.9: "when it is at least 7 days but fewer than 14, the fee is 50%"

    Design: Corner/cross_cutting_complexity_layers/cancellation_tier_50pct_at_lead_10_days
    """
    fx.set_clock("2026-07-22T20:00:00Z")
    zhome = fx.create_home_zone()
    pkg = fx.create_package()
    perf = fx.create_performer(zhome["id"])
    cli = fx.create_client()
    cat = {"zhome_id": zhome["id"], "pkg_id": pkg["id"], "perf_id": perf["id"],
           "cli_id": cli["id"]}
    bk = fx.create_booking(cat, event_zone_id=zhome["id"],
                           event_start_utc="2026-08-01T20:00:00Z", contracted_set_minutes=120)
    fx.hold_booking(bk["id"])

    resp = api.cancel_booking(bk["id"], AGENT)
    data = validate_success(resp)

    assert data["cancellation_fee_cents"] == 125000, data["cancellation_fee_cents"]


# =====================================================================
# Corner/consistency_model (immediate)
# =====================================================================
def test_hold_response_carries_freshly_computed_totals(api):
    """PRD §3.3: "When all of these pass, the hold computes the provisional grand
    total (described in 3.4), derives the required deposit, sets `balance_due_cents` to
    the quote total minus whatever has already been paid"

    Design: Corner/consistency_model/hold_computes_totals_in_same_response
    """
    cat = fx.setup_charged_catalogue()
    bk = fx.create_booking(cat, event_zone_id=cat["zevent_id"], miles=20,
                           event_start_utc="2026-08-01T20:00:00Z", contracted_set_minutes=120)
    resp = api.hold_booking(bk["id"], AGENT)
    data = validate_success(resp)

    assert data["quote_total_cents"] == 324000, data["quote_total_cents"]
    assert data["deposit_required_cents"] == 81000, data["deposit_required_cents"]
