"""The three pinned steps of the gross-charge computation, boundary by boundary."""
from test_helpers import (
    api_client, validate_success,
    setup_base, create_price_rule, create_item, reprice_item, read_item,
    read_facility, set_clock,
    ANALYST,
)

MERCY = dict(
    facility_overrides={
        "name": "Mercy General", "cms_certification_number": "CCN-2193-MERCY",
        "rounding_mode": "NEAREST_CENT", "aggregate_markup_limit_bp": 40000,
    },
    revenue_code_overrides={
        "code": "0300", "description": "Laboratory - general", "requires_hcpcs": False,
        "allowed_code_types": ["CPT", "HCPCS", "REV_ONLY", "CDM_INTERNAL"],
        "pricing_class": "PROCEDURE", "status": "ACTIVE",
    },
    department_overrides={
        "name": "Cardiac Cath Lab", "cost_center_code": "CC-4100",
        "allowed_revenue_code_values": [],
    },
)


def _read_rule(rule_id: str) -> dict:
    return validate_success(api_client.get_price_rule(rule_id, ANALYST), 200)


def test_the_abutting_rule_takes_over_at_the_exclusive_end_instant():
    """PRD §3.2: "Effectivity is half-open: `effective_from` is the inclusive start and
    `effective_to` the exclusive end, with null meaning open-ended."
    PRD §3.2: "The candidate set is every `PriceRule` whose `facility_id` matches the item's
    facility, whose `revenue_code_id` matches the item's revenue code, whose `status` is `ACTIVE`,
    whose `effective_from` is at or before the logical now, and whose `effective_to` is either null
    or strictly later than the logical now."
    PRD §3.2: "Because the intervals are half-open, an existing rule whose `effective_to` equals the
    new rule's `effective_from` abuts rather than overlaps and is entirely legal."

    Design: Corner/calculations/price_rule_selector_half_open_interval_switches_rule_at_the_abutting_instant
    """
    set_clock("2026-09-30T00:00:00Z")
    base = setup_base(
        price_rule_overrides={
            "effective_from": "2026-01-01T00:00:00Z",
            "effective_to": "2026-10-01T00:00:00Z",
        },
        **MERCY,
    )
    rule_a = base["price_rule"]
    rule_b = create_price_rule(
        base["facility"]["id"], base["revenue_code"]["id"],
        effective_from="2026-10-01T00:00:00Z", effective_to=None,
        markup_tiers=[{"min_cost_basis_cents": 0, "markup_bp": 30000}],
    )
    assert rule_b["status"] == "ACTIVE", "an abutting interval is accepted, not an overlap"

    item = create_item(
        base, cdm_number="CDM-1001", description="CARDIAC CATH BASIC",
        code_type="CPT", code_value="93458", cost_basis_cents=100000,
        medicare_rate_cents=50000, market_p75_cents=900000,
        effective_from="2026-09-30T00:00:00Z",
    )

    before = reprice_item(item["id"])
    assert before["gross_charge_cents"] == 240000, "the 24000 bp band of rule A on a 100000 cost"
    assert before["applied_price_rule_id"] == rule_a["id"]

    set_clock("2026-10-01T00:00:00Z")
    after = reprice_item(item["id"])
    assert after["gross_charge_cents"] == 300000, "rule B's single 30000 bp tier"
    assert after["applied_price_rule_id"] == rule_b["id"], (
        "at exactly the exclusive end instant rule A is no longer a candidate"
    )

    stored = read_item(item["id"])
    assert stored["gross_charge_cents"] == 300000
    assert stored["prior_gross_charge_cents"] == 240000
    assert stored["applied_price_rule_id"] == rule_b["id"]
    assert stored["price_status"] == "PRICED_CURRENT"
    assert stored["price_conflict"] is False
    assert stored["version"] == 3, "one create plus two reprices"

    assert _read_rule(rule_a["id"])["status"] == "ACTIVE", (
        "expiring by the clock is not the same as being superseded"
    )
    assert _read_rule(rule_a["id"])["applied_item_count"] == 0
    assert _read_rule(rule_b["id"])["applied_item_count"] == 1


def test_tier_thresholds_are_inclusive_so_one_more_cent_lowers_the_charge():
    """PRD §3.2: "Under `COST_PLUS_MARKUP`, the applicable tier is the last tier in the ascending
    `markup_tiers` array whose `min_cost_basis_cents` is at or below the item's `cost_basis_cents` —
    the boundary is inclusive, so a cost basis exactly equal to a tier's threshold selects *that*
    tier rather than the one below it — and the base is the item's `cost_basis_cents` multiplied by
    the selected tier's `markup_bp`, divided by 10000, rounded half up."
    PRD §3.2: "When `markup_tiers` is omitted the rule adopts the standard three-band ladder: a
    3.20-times markup (32000 basis points) from zero cost, stepping down to 2.40 times (24000 basis
    points) once the cost basis reaches 500 dollars, and to 1.80 times (18000 basis points) once it
    reaches 2,500 dollars."
    PRD §3.2: "Under `NEAREST_CENT` the constrained amount stands unchanged."

    Design: Corner/calculations/gross_charge_tier_boundaries_are_inclusive_at_50000_and_250000
    """
    set_clock("2026-09-01T00:00:00Z")
    base = setup_base(
        price_rule_overrides={"effective_from": "2026-01-01T00:00:00Z"}, **MERCY
    )
    default_rule = _read_rule(base["price_rule"]["id"])
    assert default_rule["min_medicare_multiple_bp"] == 12000
    assert default_rule["market_cap_multiple_bp"] == 11000

    costs = {"a": 49999, "b": 50000, "c": 249999, "d": 250000}
    items = {}
    for index, (key, cost) in enumerate(costs.items()):
        items[key] = create_item(
            base, cdm_number=f"CDM-200{index}", description=f"TIER PROBE {key.upper()}",
            code_type="CDM_INTERNAL", code_value=f"PROBE-{key.upper()}",
            cost_basis_cents=cost, medicare_rate_cents=10000, market_p75_cents=900000,
            effective_from="2026-09-01T00:00:00Z",
        )

    grosses = {key: reprice_item(item["id"])["gross_charge_cents"]
               for key, item in items.items()}
    assert grosses["a"] == 159997, "49999 sits below the threshold, so 32000 bp applies"
    assert grosses["b"] == 120000, "50000 exactly reaches the second band at 24000 bp"
    assert grosses["c"] == 599998, "249999 is still in the 24000 bp band"
    assert grosses["d"] == 450000, "250000 exactly reaches the third band at 18000 bp"
    assert grosses["b"] < grosses["a"] and grosses["d"] < grosses["c"], (
        "one extra cent of cost lowers the gross charge at both inclusive boundaries"
    )

    assert read_item(items["a"]["id"])["price_conflict"] is False
    assert read_item(items["b"]["id"])["price_conflict"] is False
    assert read_item(items["c"]["id"])["price_status"] == "PRICED_CURRENT"
    assert read_item(items["d"]["id"])["price_status"] == "PRICED_CURRENT"

    facility = read_facility(base["facility"]["id"])
    assert facility["active_item_count"] == 0, "pricing a DRAFT item joins no aggregate"
    assert facility["aggregate_gross_charge_cents"] == 0


def test_the_cap_beats_the_floor_and_only_that_case_flags_a_conflict():
    """PRD §3.2: "The base is raised to the floor if it is below it — the larger of base and floor is
    taken — and the result is then lowered to the cap if it is above it — the smaller of that
    intermediate value and the cap is taken. The order is pinned and it matters: when the floor
    exceeds the cap, the cap wins, and the item's `price_conflict` flag is set to true (it is false
    by default and whenever the floor is at or below the cap). Applying the cap first and the floor
    second would yield the floor amount instead and is wrong."
    PRD §3.2: "The floor is the item's `medicare_rate_cents` multiplied by
    `min_medicare_multiple_bp`, divided by 10000, rounded half up. The cap is the item's
    `market_p75_cents` multiplied by `market_cap_multiple_bp`, divided by 10000, rounded half up."

    Design: Corner/calculations/gross_charge_medicare_floor_above_market_cap_lets_the_cap_win_and_flags_conflict
    """
    set_clock("2026-09-01T00:00:00Z")
    base = setup_base(
        price_rule_overrides={"effective_from": "2026-01-01T00:00:00Z"}, **MERCY
    )
    conflict = create_item(
        base, cdm_number="CDM-3001", description="CONFLICTED PROCEDURE",
        code_type="CPT", code_value="93458", cost_basis_cents=100000,
        medicare_rate_cents=1000000, market_p75_cents=100000,
        effective_from="2026-09-01T00:00:00Z",
    )
    control = create_item(
        base, cdm_number="CDM-3002", description="FLOOR LIFTED PROCEDURE",
        code_type="CPT", code_value="93459", cost_basis_cents=50000,
        medicare_rate_cents=200000, market_p75_cents=900000,
        effective_from="2026-09-01T00:00:00Z",
    )

    priced_conflict = reprice_item(conflict["id"])
    assert priced_conflict["gross_charge_cents"] == 110000, (
        "base 240000 is lifted to the 1200000 floor and then crushed to the 110000 cap"
    )
    assert priced_conflict["price_conflict"] is True

    priced_control = reprice_item(control["id"])
    assert priced_control["gross_charge_cents"] == 240000, (
        "base 120000 is lifted to the 240000 floor, which sits under the 990000 cap"
    )
    assert priced_control["price_conflict"] is False, (
        "the flag tracks floor above cap, not merely a binding floor"
    )

    stored = read_item(conflict["id"])
    assert stored["gross_charge_cents"] == 110000, (
        "cap-first ordering would have returned the 1200000 floor"
    )
    assert stored["applied_price_rule_id"] == base["price_rule"]["id"]
    assert stored["price_status"] == "PRICED_CURRENT"
    assert read_item(control["id"])["price_conflict"] is False
