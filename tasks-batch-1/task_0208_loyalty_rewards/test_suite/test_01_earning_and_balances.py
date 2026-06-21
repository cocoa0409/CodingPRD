"""Earning points, tier qualification, and derived member balances.

Covers the earn pricing engine (single trailing floor over four factors), the
qualifying-points contribution (base spend only), the trailing-window tier
evaluation, and the available-vs-projected dual-variant balance.
"""
from test_helpers import (
    TEST_USERS,
    get_success_data,
    set_clock,
    setup_program,
    setup_member_with_points,
    register_member,
    post_purchase,
    get_member,
    create_promotion_payload,
    STANDARD_SILVER_GOLD,
    STANDARD_GOLD,
    api_client,
)

ADMIN = TEST_USERS["program_admin_headers"]


# ---------------------------------------------------------------------------
# Combinatorial earn formula — MODE (a): four factors, single trailing floor
# ---------------------------------------------------------------------------
def test_earn_four_factor_floor_gold_with_promo(api):
    """PRD 3.3: "These four factors are multiplied together at full real precision and the floor is taken exactly once at the very end to yield the integer `earned_points`; no intermediate multiplier is ever rounded."

    GOLD member (1.5) under a 2.0 promotion spending 12345c earns
    floor((12345/100) * 1.0 * 1.5 * 2.0) = floor(370.35) = 370.

    Design: Difficulty/combinatorial_formula/earn_points_four_input_nested_multipliers_mode_a
    """
    base = setup_program(tiers=STANDARD_SILVER_GOLD)
    prog = base["program"]
    promo = get_success_data(api.create_promotion(
        prog["id"],
        create_promotion_payload(prog["id"], name="DBL", bonus_multiplier=2.0,
                                 starts_at="2026-06-01T00:00:00Z",
                                 ends_at="2026-07-01T00:00:00Z", min_eligible_cents=0),
        ADMIN))
    set_clock("2026-05-01T00:00:00Z")
    member = register_member(prog["id"])
    # Drive the member to GOLD: qualifying 5000 via 500000c.
    post_purchase(member["id"], 500000)
    set_clock("2026-06-15T00:00:00Z")
    get_success_data(api.refresh_promotions(prog["id"], ADMIN))

    pe = get_success_data(api.create_purchase_event(
        {"member_id": member["id"], "eligible_amount_cents": 12345}, ADMIN))

    assert pe["earned_points"] == 370, f"Expected 370, got {pe['earned_points']}"
    assert pe["applied_promotion_id"] == promo["id"], \
        f"Expected promotion {promo['id']} applied, got {pe['applied_promotion_id']}"


def test_earn_applied_promotion_id_recorded(api):
    """PRD 3.10: "its `bonus_multiplier` becomes the promotion multiplier in the earn calculation of Section 3.3, and its id is recorded on the purchase's `applied_promotion_id`."

    Design: Difficulty/combinatorial_formula/earn_points_four_input_nested_multipliers_mode_a
    """
    base = setup_program(tiers=STANDARD_SILVER_GOLD)
    prog = base["program"]
    promo = get_success_data(api.create_promotion(
        prog["id"],
        create_promotion_payload(prog["id"], name="DBL", bonus_multiplier=2.0,
                                 starts_at="2026-06-01T00:00:00Z",
                                 ends_at="2026-07-01T00:00:00Z", min_eligible_cents=0),
        ADMIN))
    set_clock("2026-05-01T00:00:00Z")
    member = register_member(prog["id"])
    post_purchase(member["id"], 500000)
    set_clock("2026-06-15T00:00:00Z")
    get_success_data(api.refresh_promotions(prog["id"], ADMIN))

    pe = get_success_data(api.create_purchase_event(
        {"member_id": member["id"], "eligible_amount_cents": 12345}, ADMIN))
    assert pe["applied_promotion_id"] == promo["id"]


# ---------------------------------------------------------------------------
# Earn at STANDARD, no promo (corner: correct result + floor)
# ---------------------------------------------------------------------------
def test_earn_standard_no_promo_floor(api):
    """PRD 3.3: "These four factors are multiplied together at full real precision and the floor is taken exactly once at the very end to yield the integer `earned_points`; no intermediate multiplier is ever rounded."

    STANDARD member (1.0), no promo, spending 49999c earns floor(499.99) = 499.

    Design: Corner/calculations/earn_at_standard_no_promo_correct
    """
    s = setup_program(tiers=[{"code": "STANDARD", "qualify_threshold": 0,
                              "earn_multiplier": 1.0, "transfer_ratio": 0.5, "rank": 0}])
    member = register_member(s["program"]["id"])
    pe = get_success_data(api.create_purchase_event(
        {"member_id": member["id"], "eligible_amount_cents": 49999}, ADMIN))
    assert pe["earned_points"] == 499, f"Expected 499, got {pe['earned_points']}"


# ---------------------------------------------------------------------------
# Computed fields are server-computed (corner)
# ---------------------------------------------------------------------------
def test_purchase_computed_fields_server_side(api):
    """PRD 3.3: "The `qualifying_points` of a purchase measure base spend only: they are the eligible dollars (eligible cents divided by 100) multiplied by the program's `base_earn_rate`, with the floor taken once — and they deliberately exclude both the tier multiplier and the promotion multiplier."

    STANDARD member spending 10000c earns 100 and qualifies 100.

    Design: Corner/entities/purchase_event_computed_fields_ignore_client_input
    """
    s = setup_program()
    member = register_member(s["program"]["id"])
    pe = get_success_data(api.create_purchase_event(
        {"member_id": member["id"], "eligible_amount_cents": 10000}, ADMIN))
    assert pe["earned_points"] == 100, f"Expected earned 100, got {pe['earned_points']}"
    assert pe["qualifying_points"] == 100, f"Expected qualifying 100, got {pe['qualifying_points']}"


# ---------------------------------------------------------------------------
# Tier evaluation boundary — exactly threshold qualifies (GOLD at 5000)
# ---------------------------------------------------------------------------
def test_tier_qualifies_at_exactly_gold_threshold(api):
    """PRD 3.4: "The comparison is inclusive: a member whose window total exactly equals a tier's `qualify_threshold` qualifies for that tier."

    Spending 500000c yields qualifying_points_window == 5000, exactly GOLD's
    threshold, so current_tier_code resolves to GOLD.

    Design: Difficulty/boundary_precision_check/tier_qualifies_at_exactly_threshold_gold_5000
    """
    base = setup_program(tiers=STANDARD_SILVER_GOLD, clock="2026-01-10T00:00:00Z")
    member = register_member(base["program"]["id"])
    post_purchase(member["id"], 500000)
    member = get_member(member["id"])
    assert member["qualifying_points_window"] == 5000, \
        f"Expected 5000, got {member['qualifying_points_window']}"
    assert member["current_tier_code"] == "GOLD", \
        f"Expected GOLD, got {member['current_tier_code']}"


def test_tier_stays_silver_just_below_gold_threshold(api):
    """PRD 3.4: "The member's `current_tier_code` is then the `code` of the tier with the highest `rank` whose `qualify_threshold` is at or below the member's `qualifying_points_window`."

    Spending 499900c yields qualifying_points_window == 4999, one below GOLD's
    threshold, so the member stays SILVER (highest rank tier whose threshold <= 4999).

    Design: Difficulty/boundary_precision_check/tier_qualifies_at_exactly_threshold_gold_5000
    """
    base = setup_program(tiers=STANDARD_SILVER_GOLD, clock="2026-01-10T00:00:00Z")
    member = register_member(base["program"]["id"])
    post_purchase(member["id"], 499900)
    member = get_member(member["id"])
    assert member["qualifying_points_window"] == 4999, \
        f"Expected 4999, got {member['qualifying_points_window']}"
    assert member["current_tier_code"] == "SILVER", \
        f"Expected SILVER, got {member['current_tier_code']}"


# ---------------------------------------------------------------------------
# Dual-variant balance — available vs projected diverge on unswept-expired lot
# ---------------------------------------------------------------------------
def test_available_vs_projected_balance_diverge(api):
    """PRD 2.5: "A member's `available_points` is the sum of the `remaining_points`
    of every one of that member's `PointsLot` records that is in the `ACTIVE`
    status. A member's `projected_points` is the same sum minus the
    `remaining_points` of those `ACTIVE` lots whose `expires_at` is at or before the
    current clock time — that is, lots that are past expiry but have not yet been
    swept."

    Lot of 600 (created 2026-01-15, expires 2027-01-15) is past expiry but unswept
    at clock 2027-02-01; lot of 300 (created 2026-02-15) is still live. Without a
    sweep, available counts both (900) while projected excludes the expired one (300).

    Design: Difficulty/dual_variant_calc/member_available_vs_projected_balance_diverge
    """
    base = setup_program(clock="2026-01-15T00:00:00Z")
    member = register_member(base["program"]["id"])
    post_purchase(member["id"], 60000)   # 600-point lot, created 2026-01-15
    set_clock("2026-02-15T00:00:00Z")
    post_purchase(member["id"], 30000)   # 300-point lot, created 2026-02-15
    set_clock("2027-02-01T00:00:00Z")    # 600-lot past expiry, 300-lot live; no sweep

    member = get_member(member["id"])
    assert member["available_points"] == 900, \
        f"Expected available 900, got {member['available_points']}"
    assert member["projected_points"] == 300, \
        f"Expected projected 300, got {member['projected_points']}"
    assert member["available_points"] != member["projected_points"]


def test_available_counts_unswept_expired_lot(api):
    """PRD 2.5: "A member's `available_points` is the sum of the `remaining_points` of every one of that member's `PointsLot` records that is in the `ACTIVE` status."

    An ACTIVE lot past its expires_at but not yet swept still contributes to
    available_points (it is only excluded from projected_points). With a single
    600-point lot past expiry and unswept, available_points remains 600.

    Design: Difficulty/dual_variant_calc/member_available_vs_projected_balance_diverge
    """
    base = setup_program(clock="2026-01-15T00:00:00Z")
    member = register_member(base["program"]["id"])
    post_purchase(member["id"], 60000)   # 600-point lot
    set_clock("2027-02-01T00:00:00Z")    # past expiry, unswept

    member = get_member(member["id"])
    assert member["available_points"] == 600, \
        f"Expected available 600 (unswept lot still counts), got {member['available_points']}"
    assert member["projected_points"] == 0, \
        f"Expected projected 0 (lot past expiry excluded), got {member['projected_points']}"


# ---------------------------------------------------------------------------
# Immediate consistency (corner)
# ---------------------------------------------------------------------------
def test_balance_visible_immediately_after_purchase(api):
    """PRD 2.5: "All four of these computed quantities, together with `current_tier_code`, are recomputed whenever a ledger mutation occurs and are also refreshed when a member is read."

    After a 60000c purchase the member's available_points (600) is observable on
    the very next read.

    Design: Corner/consistency_model/immediate_consistency_balance_visible_in_same_flow
    """
    base = setup_program()
    member = register_member(base["program"]["id"])
    post_purchase(member["id"], 60000)
    member = get_member(member["id"])
    assert member["available_points"] == 600, \
        f"Expected 600, got {member['available_points']}"


# ---------------------------------------------------------------------------
# Qualifying window excludes non-purchase grants (corner)
# ---------------------------------------------------------------------------
def test_qualifying_window_excludes_birthday_grant(api):
    """PRD 2.5: "A member's `qualifying_points_window` is the sum of the `qualifying_points` of that member's `EARN_PURCHASE` ledger rows whose `created_at` falls within the trailing qualifying window (Section 3.4)."

    A 100000c purchase contributes qualifying 1000; a birthday grant (qualifying 0)
    raises available_points to 1200 but leaves qualifying_points_window at 1000.

    Design: Corner/cross_cutting_complexity_layers/derived_qualifying_window_excludes_birthday_grant
    """
    base = setup_program(clock="2026-03-10T00:00:00Z")
    member = register_member(base["program"]["id"])
    post_purchase(member["id"], 100000)
    get_success_data(api.birthday_grant(member["id"], ADMIN))
    member = get_member(member["id"])
    assert member["qualifying_points_window"] == 1000, \
        f"Expected qualifying 1000, got {member['qualifying_points_window']}"
    assert member["available_points"] == 1200, \
        f"Expected available 1200, got {member['available_points']}"
