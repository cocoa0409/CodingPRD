"""The facility census pair is conserved across a code-cycle ACTIVATE and its ROLL_BACK."""
from test_helpers import (
    setup_base, create_revenue_code, create_price_rule, create_active_item,
    create_cycle, create_entry, cycle_lifecycle, disposition_entry,
    read_cycle, read_entry, read_item, read_facility, set_clock,
    STANDARD_TIERS,
)

RC2_TIERS = [
    {"min_cost_basis_cents": 0, "markup_bp": 30000},
    {"min_cost_basis_cents": 50000, "markup_bp": 22000},
    {"min_cost_basis_cents": 250000, "markup_bp": 16000},
]
RULE_BOUNDS = dict(min_medicare_multiple_bp=10000, market_cap_multiple_bp=20000,
                   effective_from="2026-08-01T00:00:00Z")


def _setup():
    """Two ACTIVE CPT items on revenue code 0300, and a CROSSWALK_APPROVED 2027 cycle holding
    a CROSSWALK of 70450 onto revenue code 0301 plus a DELETE of 80053."""
    set_clock("2026-08-01T00:00:00Z")
    base = setup_base(
        facility_overrides={
            "name": "St Vitus Medical Center",
            "cms_certification_number": "CCN-2193-CYCLE",
            "rounding_mode": "NEAREST_CENT",
            "aggregate_markup_limit_bp": 40000,
        },
        revenue_code_overrides={
            "code": "0300", "description": "Laboratory - general", "requires_hcpcs": False,
            "allowed_code_types": ["CPT", "HCPCS", "REV_ONLY", "CDM_INTERNAL"],
            "pricing_class": "PROCEDURE", "status": "ACTIVE",
        },
        department_overrides={"name": "Clinical Laboratory", "cost_center_code": "CC-0300"},
        price_rule_overrides={
            "pricing_method": "COST_PLUS_MARKUP", "markup_tiers": STANDARD_TIERS,
            **RULE_BOUNDS
        },
        manager_user_id="dept_mgr_1",
    )
    rc2 = create_revenue_code(
        code="0301", description="Laboratory - chemistry", requires_hcpcs=False,
        allowed_code_types=["CPT", "HCPCS", "REV_ONLY", "CDM_INTERNAL"],
        pricing_class="PROCEDURE", status="ACTIVE",
    )
    rule2 = create_price_rule(
        base["facility"]["id"], rc2["id"],
        pricing_method="COST_PLUS_MARKUP", markup_tiers=RC2_TIERS, **RULE_BOUNDS
    )
    i1 = create_active_item(
        base, cdm_number="CDM-7001", description="Cardiac catheterization left heart",
        code_type="CPT", code_value="70450", cost_basis_cents=240000,
        medicare_rate_cents=60000, market_p75_cents=900000,
        effective_from="2026-08-01T00:00:00Z",
    )
    i2 = create_active_item(
        base, cdm_number="CDM-7002", description="Comprehensive metabolic panel",
        code_type="CPT", code_value="80053", cost_basis_cents=40000,
        medicare_rate_cents=10000, market_p75_cents=200000,
        effective_from="2026-08-01T00:00:00Z",
    )
    cycle = create_cycle(base["facility"]["id"], cycle_year=2027, code_set="CPT",
                         cost_inflator_bp=11000)
    e1 = create_entry(cycle["id"], "CROSSWALK", old_code_value="70450",
                      new_code_value="70460", new_revenue_code_id=rc2["id"])
    e2 = create_entry(cycle["id"], "DELETE", old_code_value="80053", new_code_value=None)
    cycle_lifecycle(cycle["id"], "START_MAPPING")
    base.update({
        "revenue_code_2": rc2, "price_rule_2": rule2, "i1": i1, "i2": i2,
        "e1": disposition_entry(e1["id"], "MAP"),
        "e2": disposition_entry(e2["id"], "MAP"),
        "cycle": cycle_lifecycle(cycle["id"], "APPROVE_CROSSWALK"),
    })
    return base


def test_activation_snapshots_the_census_pair_then_moves_it():
    """PRD §3.7: "Only when the revenue code genuinely changes is the price rebuilt, and then in
    a pinned order. First the target item's `cost_basis_cents` is multiplied by the cycle's
    `cost_inflator_bp`, divided by 10000, and rounded half up to whole cents."
    PRD §3.7: "Because the inflation is rounded *before* tier selection, an inflated cost basis
    can cross a markup tier boundary and pick up a different `markup_bp` than the pre-inflation
    cost would have; inflating the resulting charge instead of the cost basis produces a
    different number and is wrong."
    PRD §3.7: "On success the cycle first snapshots the facility's state *before any child is
    mutated*: `pre_activation_active_item_count` takes the facility's `active_item_count` and
    `pre_activation_aggregate_gross_charge_cents` takes its `aggregate_gross_charge_cents`."
    PRD §3.7: "Second, each applied entry mutates its target item: for `CROSSWALK` and `REVISE`,
    the item's `code_value` takes `new_code_value`, its `revenue_code_id` takes
    `new_revenue_code_id` when that field is non-null, its `gross_charge_cents` takes the entry's
    `carried_gross_charge_cents`, and its `price_status` moves to `PRICE_STALE`; for `DELETE`, the
    item's `lifecycle_status` moves to `INACTIVE`."

    Design: Difficulty/compensating_invariant/compensating_invariant__facility_active_census_and_aggregate_gross_conserved_across_cycle_activate_then_rollback
    """
    s = _setup()
    assert read_item(s["i1"]["id"])["gross_charge_cents"] == 576000, (
        "240000 cents of cost in revenue code 0300's 24000bp tier"
    )
    assert read_item(s["i2"]["id"])["gross_charge_cents"] == 128000
    before = read_facility(s["facility"]["id"])
    assert before["active_item_count"] == 2
    assert before["aggregate_gross_charge_cents"] == 704000
    assert s["e1"]["carried_gross_charge_cents"] == 422400, (
        "240000 inflated by 11000bp is 264000, which lands in revenue code 0301's "
        "250000/16000 tier: 264000 * 1.6 = 422400"
    )
    assert s["e2"]["carried_gross_charge_cents"] == 128000, (
        "a DELETE carries the target's price unchanged"
    )

    activated = cycle_lifecycle(s["cycle"]["id"], "ACTIVATE",
                                note="apply the 2027 CPT crosswalk")
    assert activated["status"] == "ACTIVATED"
    assert activated["pre_activation_active_item_count"] == 2
    assert activated["pre_activation_aggregate_gross_charge_cents"] == 704000

    i1 = read_item(s["i1"]["id"])
    assert i1["code_value"] == "70460"
    assert i1["revenue_code_id"] == s["revenue_code_2"]["id"]
    assert i1["gross_charge_cents"] == 422400
    assert i1["price_status"] == "PRICE_STALE"
    assert read_item(s["i2"]["id"])["lifecycle_status"] == "INACTIVE"

    after = read_facility(s["facility"]["id"])
    assert after["active_item_count"] == 1
    assert after["aggregate_gross_charge_cents"] == 422400

    e1 = read_entry(s["e1"]["id"])
    assert e1["status"] == "APPLIED"
    assert e1["prior_gross_charge_cents"] == 576000
    assert e1["prior_code_value"] == "70450"
    assert e1["prior_revenue_code_id"] == s["revenue_code"]["id"]
    e2 = read_entry(s["e2"]["id"])
    assert e2["status"] == "APPLIED"
    assert e2["prior_lifecycle_status"] == "ACTIVE"


def test_rollback_restores_the_census_pair_to_the_pre_activation_snapshot():
    """PRD §3.7: "Rollback walks every entry whose `status` is `APPLIED` **in order of
    `created_at` descending** — the exact reverse of the apply order — and restores its target
    item verbatim from the snapshots: `code_value` from `prior_code_value`, `revenue_code_id` from
    `prior_revenue_code_id`, `gross_charge_cents` from `prior_gross_charge_cents`,
    `lifecycle_status` from `prior_lifecycle_status`, `price_status` set to `PRICE_STALE`, and
    `last_code_cycle_id` cleared to null, with each item's `version` advancing by 1."
    PRD §3.7: "The facility's aggregates are then recomputed, and the conservation invariant must
    hold: `active_item_count` equals `pre_activation_active_item_count` and
    `aggregate_gross_charge_cents` equals `pre_activation_aggregate_gross_charge_cents`."
    PRD §3.7: "Each entry transitions `APPLIED → REVERTED`, which requires that its
    `prior_code_value` be non-null, and advances its own `version` by 1."
    PRD §2.11: "`stale_price_item_count` (the number of its charge items that are simultaneously
    `ACTIVE` in the lifecycle dimension and `PRICE_STALE` in the pricing dimension)"

    Design: Difficulty/compensating_invariant/compensating_invariant__facility_active_census_and_aggregate_gross_conserved_across_cycle_activate_then_rollback
    """
    s = _setup()
    cycle_lifecycle(s["cycle"]["id"], "ACTIVATE", note="apply the 2027 CPT crosswalk")
    rolled_back = cycle_lifecycle(
        s["cycle"]["id"], "ROLL_BACK",
        note="vendor file was wrong; compensate the activation",
    )
    assert rolled_back["status"] == "ROLLED_BACK"

    facility = read_facility(s["facility"]["id"])
    assert facility["active_item_count"] == rolled_back["pre_activation_active_item_count"] == 2
    assert (
        facility["aggregate_gross_charge_cents"]
        == rolled_back["pre_activation_aggregate_gross_charge_cents"] == 704000
    ), "the census pair is restored to exactly its pre-activation value"

    i1 = read_item(s["i1"]["id"])
    assert i1["code_value"] == "70450"
    assert i1["revenue_code_id"] == s["revenue_code"]["id"]
    assert i1["gross_charge_cents"] == 576000
    assert i1["lifecycle_status"] == "ACTIVE"
    assert i1["last_code_cycle_id"] is None
    i2 = read_item(s["i2"]["id"])
    assert i2["lifecycle_status"] == "ACTIVE"
    assert i2["gross_charge_cents"] == 128000

    assert read_entry(s["e1"]["id"])["status"] == "REVERTED"
    assert read_entry(s["e2"]["id"])["status"] == "REVERTED"

    assert facility["stale_price_item_count"] == 2, (
        "rollback sets price_status to PRICE_STALE on both restored ACTIVE items"
    )
    assert facility["chargemaster_posture"] == "OPEN", (
        "two stale items are short of the five that would restrict the posture, and the cycle "
        "is no longer in MAPPING or CROSSWALK_APPROVED"
    )
