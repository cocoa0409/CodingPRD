"""Member charge and guest funding at check-in.

The member charge is a per-line round-then-sum aggregation (PRD §3.4); guest
funding is an order-sensitive waterfall (PRD §3.3). Day-pass entry charges the
snapshotted, undiscounted pass price. Covers queue-A combinatorial_formula
instances and queue-B calculation/computed-field corners.
"""
from test_helpers import (
    validate_success,
    get_success_data,
    api_client,
    TEST_USERS,
    fixtures,
)

ADMIN = TEST_USERS["network_admin_headers"]


# ─── Queue A: combinatorial_formula — member charge per-line rounding ────────
def test_member_charge_per_line_round_then_sum_gold(api):
    """PRD §3.4: "Because each line is rounded before summing, the total can
    differ from rounding a single combined figure — for example two `GOLD`-discounted
    guest lines that each round 1505 cents at 0.90 to 1355 sum to 2710, whereas
    discounting the combined 3010 would yield 2709; the per-line order is what the
    system uses."
    PRD §3.4: "The first line is the overage line: when `entry_mode` is `OVERAGE`,
    it is the plan's `overage_charge_cents` multiplied by the discount and rounded
    half-up to whole cents; otherwise it is zero."

    A GOLD member, OVERAGE primary (overage 5000*0.9=4500) plus two GUEST_CHARGE
    guests (each round((2500+1505)*0.9)=round(3604.5)=3605): 4500+3605+3605=11710.

    Design: Difficulty/combinatorial_formula/cf_member_charge_per_line_rounding_order
    """
    plan, lounge, member, card = fixtures.setup_plan_lounge_member(
        plan_overrides={
            "tier": "STANDARD",
            "included_visits_per_year": 0,
            "included_guest_visits_per_year": 0,
            "overage_charge_cents": 5000,
            "guest_charge_cents": 2500,
            "min_card_status": "BASIC",
        },
        lounge_overrides={"airport_code": "ORD", "capacity": 30, "guest_fee_cents": 1505},
        card_overrides={"card_status": "GOLD"},
    )
    visit = fixtures.open_hold(
        lounge["id"], member_id=member["id"], guest_count=2, guest_names=["A", "B"]
    )
    checked_in = fixtures.check_in(visit["id"], lounge["id"])
    assert checked_in["member_charge_cents"] == 11710, checked_in
    assert checked_in["member_charge_cents"] != 11709, "per-line round-then-sum is pinned"


def test_guest_funding_waterfall_split_point(api):
    """PRD §3.3: "Walking the guests in order, the first `guest_allotment_consumed`
    of them are funded from allotment and the rest are charged: each guest's
    `funded_by` is set to `GUEST_ALLOTMENT` for those covered and `GUEST_CHARGE`
    for those beyond the split point."
    PRD §3.4: "for each guest whose `funded_by` is `GUEST_CHARGE`, that guest's
    `charge_cents` is the sum of the plan's `guest_charge_cents` and the lounge's
    `guest_fee_cents`, multiplied by the discount and rounded half-up; for each
    guest whose `funded_by` is `GUEST_ALLOTMENT`, only the lounge's `guest_fee_cents`
    applies (the plan guest charge is waived), multiplied by the discount and
    rounded half-up; the guest total is the sum of those already-rounded per-guest
    charges."

    included_guest_visits 1, two guests, non-GOLD: guest[0]=GUEST_ALLOTMENT
    (charge=fee 1000), guest[1]=GUEST_CHARGE (charge=2500+1000=3500).

    Design: Difficulty/combinatorial_formula/cf_guest_funding_waterfall_minmax
    """
    plan, lounge, member, card = fixtures.setup_plan_lounge_member(
        plan_overrides={
            "tier": "PRESTIGE",
            "included_visits_per_year": 10,
            "included_guest_visits_per_year": 1,
            "guest_charge_cents": 2500,
            "min_card_status": "BASIC",
        },
        lounge_overrides={"airport_code": "DEN", "capacity": 30, "guest_fee_cents": 1000},
        card_overrides={"card_status": "SILVER"},
    )
    visit = fixtures.open_hold(
        lounge["id"], member_id=member["id"], guest_count=2, guest_names=["First", "Second"]
    )
    checked_in = fixtures.check_in(visit["id"], lounge["id"])
    guests = get_success_data(
        api_client.list_guests(ADMIN, params={"visit_id": visit["id"]})
    )
    assert guests[0]["funded_by"] == "GUEST_ALLOTMENT", guests
    assert guests[1]["funded_by"] == "GUEST_CHARGE", guests
    assert guests[0]["charge_cents"] == 1000, guests[0]
    assert guests[1]["charge_cents"] == 3500, guests[1]
    assert checked_in["member_charge_cents"] == 4500, checked_in


# ─── Queue B: calculations / computed fields ─────────────────────────────────
def test_day_pass_entry_charge_equals_undiscounted_price(api):
    """PRD §3.4: "The third line is the day-pass line: when `entry_mode` is
    `DAY_PASS`, it is the day pass's already-snapshotted `price_cents`, which is
    not discounted; otherwise it is zero."

    Design: Corner/calculations/calc_daypass_entry_member_charge_equals_price
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    plan = fixtures.create_plan(
        tier="STANDARD", included_visits_per_year=0, included_guest_visits_per_year=0
    )
    lounge = fixtures.create_lounge(airport_code="ATL", capacity=10, day_pass_price_cents=4000)
    member = fixtures.create_member(plan["id"])
    day_pass = fixtures.purchase_day_pass_for_member(lounge["id"], member["id"])
    visit = fixtures.open_hold(
        lounge["id"], member_id=member["id"], day_pass_id=day_pass["id"]
    )
    assert visit["entry_mode"] == "DAY_PASS", visit
    checked_in = fixtures.check_in(visit["id"], lounge["id"])
    assert checked_in["member_charge_cents"] == 4000, checked_in


def test_allotment_primary_no_guests_zero_charge(api):
    """PRD §3.4: "The first line is the overage line: when `entry_mode` is
    `OVERAGE`, it is the plan's `overage_charge_cents` multiplied by the discount
    and rounded half-up to whole cents; otherwise it is zero."

    An ALLOTMENT primary with no guests has a zero overage line, no guest total,
    and no day-pass line, so member_charge_cents is 0.

    Design: Corner/calculations/calc_allotment_primary_zero_charge
    """
    plan, lounge, member, card = fixtures.setup_plan_lounge_member(
        plan_overrides={"included_visits_per_year": 10},
        lounge_overrides={"airport_code": "SLC", "capacity": 10},
    )
    visit = fixtures.open_hold(lounge["id"], member_id=member["id"])
    checked_in = fixtures.check_in(visit["id"], lounge["id"])
    assert checked_in["member_charge_cents"] == 0, checked_in


def test_occupant_count_computed_from_guest_count(api):
    """PRD §3.3: "the visit's `occupant_count` is one plus the guest count — the
    seats the visit occupies."

    Design: Corner/entities/entity_visit_computed_occupant_count_ignores_input
    """
    plan, lounge, member, card = fixtures.setup_plan_lounge_member(
        plan_overrides={"included_visits_per_year": 10},
        lounge_overrides={"airport_code": "LAX", "capacity": 10},
    )
    visit = fixtures.open_hold(
        lounge["id"], member_id=member["id"], guest_count=2, guest_names=["A", "B"]
    )
    assert visit["occupant_count"] == 3, visit
    assert visit["entry_mode"] == "ALLOTMENT", visit


def test_visit_guest_count_defaults_to_zero(api):
    """PRD §3.3: "The number of accompanying guests is given by `guest_count`
    (defaulting to 0, at least 0), and their names are supplied in `guest_names`
    in the order they will be funded; the visit's `occupant_count` is one plus the
    guest count — the seats the visit occupies."

    Design: Corner/entities/entity_visit_guest_count_default_zero
    """
    plan, lounge, member, card = fixtures.setup_plan_lounge_member(
        plan_overrides={"included_visits_per_year": 10},
        lounge_overrides={"airport_code": "SEA", "capacity": 10},
    )
    # Omit guest_count entirely so the server default applies.
    fresh_v = fixtures.get_lounge(lounge["id"])["version"]
    resp = api_client.create_visit(
        {"member_id": member["id"], "lounge_id": lounge["id"], "expected_lounge_version": fresh_v},
        ADMIN,
    )
    visit = validate_success(resp, expected_status=201)
    assert visit["guest_count"] == 0, visit
    assert visit["occupant_count"] == 1, visit


# ─── Queue A second-coverage: combinatorial_formula ──────────────────────────
def test_member_charge_no_discount_passthrough_non_gold(api):
    """PRD §3.4: "The discount multiplier is 0.90 when the member's active card has
    `card_status` `GOLD`, and 1.0 otherwise."
    PRD §3.4: "The first line is the overage line: when `entry_mode` is `OVERAGE`,
    it is the plan's `overage_charge_cents` multiplied by the discount and rounded
    half-up to whole cents; otherwise it is zero."

    A non-GOLD member (disc 1.0), OVERAGE primary 5000 + two GUEST_CHARGE guests at
    (2500+1505)=4005 each: 5000+4005+4005=13010, no rounding applied.

    Design: Difficulty/combinatorial_formula/cf_member_charge_per_line_rounding_order
    """
    plan, lounge, member, card = fixtures.setup_plan_lounge_member(
        plan_overrides={
            "tier": "STANDARD", "included_visits_per_year": 0,
            "included_guest_visits_per_year": 0, "overage_charge_cents": 5000,
            "guest_charge_cents": 2500, "min_card_status": "BASIC",
        },
        lounge_overrides={"airport_code": "PHX", "capacity": 30, "guest_fee_cents": 1505},
        card_overrides={"card_status": "SILVER"},
    )
    visit = fixtures.open_hold(
        lounge["id"], member_id=member["id"], guest_count=2, guest_names=["A", "B"]
    )
    checked_in = fixtures.check_in(visit["id"], lounge["id"])
    assert checked_in["member_charge_cents"] == 13010, checked_in


def test_guest_funding_zero_allotment_all_charged(api):
    """PRD §3.3: "when the remaining allotment is zero — because it was already
    exhausted or the plan grants none — every guest is `GUEST_CHARGE`."
    PRD §3.4: "for each guest whose `funded_by` is `GUEST_CHARGE`, that guest's
    `charge_cents` is the sum of the plan's `guest_charge_cents` and the lounge's
    `guest_fee_cents`, multiplied by the discount and rounded half-up..."

    Plan grants 0 guest visits, two guests, non-GOLD: both GUEST_CHARGE at
    2500+1000=3500 each; member_charge_cents (ALLOTMENT primary) == 7000.

    Design: Difficulty/combinatorial_formula/cf_guest_funding_waterfall_minmax
    """
    plan, lounge, member, card = fixtures.setup_plan_lounge_member(
        plan_overrides={
            "tier": "PRESTIGE", "included_visits_per_year": 10,
            "included_guest_visits_per_year": 0, "guest_charge_cents": 2500,
            "min_card_status": "BASIC",
        },
        lounge_overrides={"airport_code": "DEN", "capacity": 30, "guest_fee_cents": 1000},
        card_overrides={"card_status": "SILVER"},
    )
    visit = fixtures.open_hold(
        lounge["id"], member_id=member["id"], guest_count=2, guest_names=["First", "Second"]
    )
    checked_in = fixtures.check_in(visit["id"], lounge["id"])
    guests = get_success_data(
        api_client.list_guests(ADMIN, params={"visit_id": visit["id"]})
    )
    assert guests[0]["funded_by"] == "GUEST_CHARGE", guests
    assert guests[1]["funded_by"] == "GUEST_CHARGE", guests
    assert guests[0]["charge_cents"] == 3500, guests[0]
    assert guests[1]["charge_cents"] == 3500, guests[1]
    assert checked_in["member_charge_cents"] == 7000, checked_in
