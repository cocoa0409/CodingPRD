"""Rounding is the last step, and the two non-cost-plus methods still meet the floor and the cap."""
from test_helpers import (
    api_client, validate_success,
    setup_base, create_item, reprice_item, read_item, read_facility, set_clock,
    ANALYST,
)


def _read_rule(rule_id: str) -> dict:
    return validate_success(api_client.get_price_rule(rule_id, ANALYST), 200)


def _scope(code: str, ccn: str, facility_extra=None, price_rule_overrides=None) -> dict:
    facility_overrides = {"name": f"Hospital {ccn}", "cms_certification_number": ccn}
    facility_overrides.update(facility_extra or {})
    return setup_base(
        facility_overrides=facility_overrides,
        revenue_code_overrides={
            "code": code, "description": "Laboratory - general", "requires_hcpcs": False,
            "allowed_code_types": ["CPT", "HCPCS", "REV_ONLY", "CDM_INTERNAL"],
            "pricing_class": "PROCEDURE", "status": "ACTIVE",
        },
        department_overrides={
            "name": "Cardiac Cath Lab", "cost_center_code": "CC-4100",
            "allowed_revenue_code_values": [],
        },
        price_rule_overrides={
            "effective_from": "2026-01-01T00:00:00Z", **(price_rule_overrides or {})
        },
    )


PROBE = dict(
    description="ROUNDING PROBE", code_type="CPT", code_value="93458",
    cost_basis_cents=33333, medicare_rate_cents=10000, market_p75_cents=96982,
    effective_from="2026-09-01T00:00:00Z",
)


def test_rounding_runs_last_and_may_legitimately_exceed_the_market_cap():
    """PRD §3.2: "*Step three — the facility's rounding mode is applied exactly once, last.* Under
    `NEAREST_CENT` the constrained amount stands unchanged. Under `NEAREST_DOLLAR` the amount is
    divided by 100, rounded half up to a whole number of dollars, and multiplied back by 100. Under
    `PSYCHOLOGICAL_99` the amount is divided by 100, rounded *up* to the next whole dollar,
    multiplied by 100, and then reduced by one cent — so every price ends in 99 cents."
    PRD §3.2: "The cap is the item's `market_p75_cents` multiplied by `market_cap_multiple_bp`,
    divided by 10000, rounded half up."
    PRD §3.1: "`rounding_mode` defaults to `NEAREST_DOLLAR` and may instead be `NEAREST_CENT` or
    `PSYCHOLOGICAL_99`; it controls the final rounding step of every gross-charge computation."

    Design: Corner/calculations/rounding_mode_is_applied_once_after_the_cap_not_before_it
    """
    set_clock("2026-09-01T00:00:00Z")
    psych = _scope("0300", "CCN-2193-PSYCH",
                   facility_extra={"rounding_mode": "PSYCHOLOGICAL_99",
                                   "aggregate_markup_limit_bp": 40000})
    dollar = _scope("0301", "CCN-2193-DOLLAR")
    assert read_facility(dollar["facility"]["id"])["rounding_mode"] == "NEAREST_DOLLAR", (
        "the facility that omitted the field inherits the default"
    )

    item_p = create_item(psych, cdm_number="CDM-1001", **PROBE)
    item_d = create_item(dollar, cdm_number="CDM-1001", **PROBE)

    priced_p = reprice_item(item_p["id"])
    assert priced_p["gross_charge_cents"] == 106699, (
        "the constrained 106666 is rounded up to 106700 and reduced by one cent, "
        "which legitimately exceeds the 106680 cap because rounding is the last step"
    )
    priced_d = reprice_item(item_d["id"])
    assert priced_d["gross_charge_cents"] == 106700, (
        "the same constrained 106666 rounded half up to whole dollars"
    )

    stored_p = read_item(item_p["id"])
    stored_d = read_item(item_d["id"])
    assert stored_p["price_conflict"] is False, "the 12000 floor sits far below the 106680 cap"
    assert stored_d["price_conflict"] is False
    assert stored_p["version"] == 2, "one create plus one reprice"
    assert stored_d["version"] == 2


def test_medicare_multiple_ignores_the_cost_basis_and_rounds_half_up():
    """PRD §3.2: "Under `MEDICARE_MULTIPLE`, the base is the item's `medicare_rate_cents` multiplied
    by the rule's `min_medicare_multiple_bp`, divided by 10000, rounded half up."
    PRD §3.2: "The base is raised to the floor if it is below it — the larger of base and floor is
    taken — and the result is then lowered to the cap if it is above it — the smaller of that
    intermediate value and the cap is taken."
    PRD §3.2: "Each rule exposes `applied_item_count`, the number of charge items whose
    `applied_price_rule_id` names it."

    Design: Corner/calculations/medicare_multiple_method_ignores_cost_basis_and_rounds_half_up_at_the_half_cent
    """
    set_clock("2026-09-01T00:00:00Z")
    base = _scope(
        "0300", "CCN-2193-MEDMULT",
        facility_extra={"rounding_mode": "NEAREST_CENT", "aggregate_markup_limit_bp": 40000},
        price_rule_overrides={
            "pricing_method": "MEDICARE_MULTIPLE",
            "min_medicare_multiple_bp": 15000,
            "market_cap_multiple_bp": 11000,
        },
    )
    rule = base["price_rule"]
    assert rule["pricing_method"] == "MEDICARE_MULTIPLE"

    item = create_item(
        base, cdm_number="CDM-1001", description="MEDICARE MULTIPLE PROBE",
        code_type="CPT", code_value="93458", cost_basis_cents=999999,
        medicare_rate_cents=12345, market_p75_cents=900000,
        effective_from="2026-09-01T00:00:00Z",
    )
    priced = reprice_item(item["id"])
    assert priced["gross_charge_cents"] == 18518, (
        "12345 times 15000 over 10000 is 18517.5, which rounds half up rather than truncating"
    )

    stored = read_item(item["id"])
    assert stored["gross_charge_cents"] == 18518
    assert stored["cost_basis_cents"] == 999999, "the cost basis had no influence at all"
    assert stored["applied_price_rule_id"] == rule["id"]
    assert stored["price_conflict"] is False, "base and floor are identical, so neither binds"
    assert stored["price_status"] == "PRICED_CURRENT"
    assert _read_rule(rule["id"])["applied_item_count"] == 1


def test_one_flat_fee_yields_two_prices_because_the_bounds_are_per_item():
    """PRD §3.2: "Under `FLAT_FEE`, the base is the rule's `flat_fee_cents` exactly."
    PRD §3.2: "`flat_fee_cents` holds the charge used verbatim under `FLAT_FEE` pricing and is null
    otherwise."
    PRD §3.2: "The order is pinned and it matters: when the floor exceeds the cap, the cap wins, and
    the item's `price_conflict` flag is set to true (it is false by default and whenever the floor is
    at or below the cap)."

    Design: Corner/calculations/flat_fee_method_is_lifted_by_the_medicare_floor_and_crushed_by_the_market_cap
    """
    set_clock("2026-09-01T00:00:00Z")
    base = _scope(
        "0300", "CCN-2193-FLATFEE",
        facility_extra={"rounding_mode": "NEAREST_CENT", "aggregate_markup_limit_bp": 40000},
        price_rule_overrides={
            "pricing_method": "FLAT_FEE",
            "flat_fee_cents": 50000,
            "min_medicare_multiple_bp": 12000,
            "market_cap_multiple_bp": 11000,
        },
    )
    rule = base["price_rule"]
    assert rule["flat_fee_cents"] == 50000

    item_low = create_item(
        base, cdm_number="CDM-1001", description="FLOOR LIFTED FLAT FEE",
        code_type="CPT", code_value="93458", cost_basis_cents=100000,
        medicare_rate_cents=60000, market_p75_cents=900000,
        effective_from="2026-09-01T00:00:00Z",
    )
    item_high = create_item(
        base, cdm_number="CDM-1002", description="CAP CRUSHED FLAT FEE",
        code_type="CPT", code_value="93459", cost_basis_cents=100000,
        medicare_rate_cents=1000, market_p75_cents=30000,
        effective_from="2026-09-01T00:00:00Z",
    )

    priced_low = reprice_item(item_low["id"])
    assert priced_low["gross_charge_cents"] == 72000, (
        "the 50000 flat fee is lifted to the 72000 Medicare floor"
    )
    assert priced_low["price_conflict"] is False

    priced_high = reprice_item(item_high["id"])
    assert priced_high["gross_charge_cents"] == 33000, (
        "the 50000 flat fee is crushed to the 33000 market cap"
    )
    assert priced_high["price_conflict"] is False, "the 1200 floor is under the 33000 cap"

    assert priced_low["gross_charge_cents"] != priced_high["gross_charge_cents"], (
        "one rule, two prices: the flat fee is never returned verbatim here"
    )
    assert _read_rule(rule["id"])["flat_fee_cents"] == 50000
    assert _read_rule(rule["id"])["applied_item_count"] == 2
    assert read_item(item_low["id"])["price_status"] == "PRICED_CURRENT"
    assert read_item(item_high["id"])["price_status"] == "PRICED_CURRENT"
