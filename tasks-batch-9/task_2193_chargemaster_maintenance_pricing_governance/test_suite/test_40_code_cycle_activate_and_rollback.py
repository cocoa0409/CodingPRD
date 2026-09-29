"""Cycle activation applies the inflated carry price; rollback compensates it exactly."""
from test_helpers import (
    setup_base, create_revenue_code, create_price_rule, create_active_item,
    create_cycle, create_entry, disposition_entry, cycle_lifecycle,
    read_cycle, read_entry, read_item, read_facility, set_clock,
    APPROVER,
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
    price_rule_overrides={"effective_from": "2026-01-01T00:00:00Z"},
)

ITEM = dict(
    cdm_number="CDM-1001", description="CARDIAC CATH BASIC",
    code_type="CPT", code_value="93458", cost_basis_cents=100000,
    medicare_rate_cents=50000, market_p75_cents=900000,
    effective_from="2026-09-01T00:00:00Z",
)


def _setup():
    """A CROSSWALK_APPROVED cycle whose single MAPPED entry moves CDM-1001 onto revenue code 0301."""
    set_clock("2026-09-01T00:00:00Z")
    base = setup_base(**MERCY)
    rc301 = create_revenue_code(
        code="0301", description="Laboratory - chemistry", requires_hcpcs=False,
        allowed_code_types=["CPT", "HCPCS", "REV_ONLY", "CDM_INTERNAL"],
        pricing_class="PROCEDURE",
    )
    rule301 = create_price_rule(
        base["facility"]["id"], rc301["id"], effective_from="2026-01-01T00:00:00Z",
    )
    item = create_active_item(base, **ITEM)
    assert item["version"] == 5 and item["gross_charge_cents"] == 240000

    cycle = create_cycle(base["facility"]["id"], cycle_year=2027, code_set="CPT")
    assert cycle["cost_inflator_bp"] == 10300
    entry = create_entry(
        cycle["id"], "CROSSWALK", old_code_value="93458", new_code_value="93459",
        new_revenue_code_id=rc301["id"],
    )
    cycle_lifecycle(cycle["id"], "START_MAPPING")
    entry = disposition_entry(entry["id"], "MAP")
    cycle_lifecycle(cycle["id"], "APPROVE_CROSSWALK", APPROVER)

    base.update(rc301=rc301, rule301=rule301, item=item, cycle=cycle, entry=entry)
    return base


def test_activation_snapshots_first_then_applies_the_inflated_carry_price():
    """PRD §3.7: "On success the cycle first snapshots the facility's state *before any child is
    mutated*: `pre_activation_active_item_count` takes the facility's `active_item_count` and
    `pre_activation_aggregate_gross_charge_cents` takes its `aggregate_gross_charge_cents`."
    PRD §3.7: "Only when the revenue code genuinely changes is the price rebuilt, and then in a
    pinned order. First the target item's `cost_basis_cents` is multiplied by the cycle's
    `cost_inflator_bp`, divided by 10000, and rounded half up to whole cents. Then the full
    gross-charge computation of §3.2 is run against the target item as if its cost basis were that
    inflated amount and its revenue code were the entry's `new_revenue_code_id`, selecting the price
    rule that applies to the **new** revenue code at map time."
    PRD §3.7: "Second, each applied entry mutates its target item: for `CROSSWALK` and `REVISE`, the
    item's `code_value` takes `new_code_value`, its `revenue_code_id` takes `new_revenue_code_id`
    when that field is non-null, its `gross_charge_cents` takes the entry's
    `carried_gross_charge_cents`, and its `price_status` moves to `PRICE_STALE`"

    Design: Corner/state_machines/code_update_cycle_activate_applies_mapped_entry_with_inflated_carry_price
    """
    base = _setup()
    assert base["entry"]["carried_gross_charge_cents"] == 247200, (
        "cost 100000 inflated to 103000 sits in the 24000bp band of revenue code 0301's rule, "
        "and neither the 60000 floor nor the 990000 cap binds"
    )

    activated = cycle_lifecycle(base["cycle"]["id"], "ACTIVATE",
                                note="Annual CPT cycle activated")
    assert activated["status"] == "ACTIVATED"
    assert activated["pre_activation_active_item_count"] == 1
    assert activated["pre_activation_aggregate_gross_charge_cents"] == 240000, (
        "the snapshot is the pre-cascade aggregate, not the post-apply 247200"
    )
    assert activated["activated_at"].startswith("2026-09-01T00:00:00")
    assert read_cycle(base["cycle"]["id"])["version"] == 6

    entry = read_entry(base["entry"]["id"])
    assert entry["status"] == "APPLIED"
    assert entry["prior_code_value"] == "93458"
    assert entry["prior_revenue_code_id"] == base["revenue_code"]["id"]
    assert entry["prior_gross_charge_cents"] == 240000
    assert entry["prior_lifecycle_status"] == "ACTIVE"
    assert entry["version"] == 3

    item = read_item(base["item"]["id"])
    assert item["code_value"] == "93459"
    assert item["revenue_code_id"] == base["rc301"]["id"]
    assert item["gross_charge_cents"] == 247200
    assert item["price_status"] == "PRICE_STALE"
    assert item["lifecycle_status"] == "ACTIVE"
    assert item["last_code_cycle_id"] == base["cycle"]["id"]
    assert item["version"] == 6

    facility = read_facility(base["facility"]["id"])
    assert facility["aggregate_gross_charge_cents"] == 247200
    assert facility["aggregate_markup_ratio_bp"] == 24720, "247200 * 10000 / 100000"
    assert facility["stale_price_item_count"] == 1
    assert facility["chargemaster_posture"] == "OPEN"
    assert facility["transparency_status"] == "NEEDS_REFRESH"


def test_rollback_restores_the_snapshots_and_conserves_the_facility_census():
    """PRD §3.7: "Rollback walks every entry whose `status` is `APPLIED` **in order of `created_at`
    descending** — the exact reverse of the apply order — and restores its target item verbatim from
    the snapshots: `code_value` from `prior_code_value`, `revenue_code_id` from
    `prior_revenue_code_id`, `gross_charge_cents` from `prior_gross_charge_cents`,
    `lifecycle_status` from `prior_lifecycle_status`, `price_status` set to `PRICE_STALE`, and
    `last_code_cycle_id` cleared to null, with each item's `version` advancing by 1."
    PRD §3.7: "The facility's aggregates are then recomputed, and the conservation invariant must
    hold: `active_item_count` equals `pre_activation_active_item_count` and
    `aggregate_gross_charge_cents` equals `pre_activation_aggregate_gross_charge_cents`."
    PRD §3.7: "Each entry transitions `APPLIED → REVERTED`, which requires that its
    `prior_code_value` be non-null, and advances its own `version` by 1. `REVERTED` is terminal for
    an entry."

    Design: Corner/state_machines/code_update_cycle_rollback_reverts_entry_and_conserves_facility_aggregates
    """
    base = _setup()
    cycle_lifecycle(base["cycle"]["id"], "ACTIVATE")
    assert read_item(base["item"]["id"])["gross_charge_cents"] == 247200

    rolled_back = cycle_lifecycle(base["cycle"]["id"], "ROLL_BACK",
                                  note="Payer rejected the new code set")
    assert rolled_back["status"] == "ROLLED_BACK"
    assert rolled_back["rolled_back_at"].startswith("2026-09-01T00:00:00")
    assert rolled_back["version"] == 7

    entry = read_entry(base["entry"]["id"])
    assert entry["status"] == "REVERTED"
    assert entry["version"] == 4

    item = read_item(base["item"]["id"])
    assert item["code_value"] == "93458"
    assert item["revenue_code_id"] == base["revenue_code"]["id"]
    assert item["gross_charge_cents"] == 240000
    assert item["lifecycle_status"] == "ACTIVE"
    assert item["price_status"] == "PRICE_STALE", (
        "rollback never restores PRICED_CURRENT; the price must be rebuilt explicitly"
    )
    assert item["last_code_cycle_id"] is None
    assert item["version"] == 7

    facility = read_facility(base["facility"]["id"])
    assert facility["active_item_count"] == rolled_back["pre_activation_active_item_count"] == 1
    assert (
        facility["aggregate_gross_charge_cents"]
        == rolled_back["pre_activation_aggregate_gross_charge_cents"]
        == 240000
    ), "the conservation invariant closes the loop exactly"
    assert facility["aggregate_cost_basis_cents"] == 100000
    assert facility["aggregate_markup_ratio_bp"] == 24000
    assert facility["stale_price_item_count"] == 1
    assert facility["chargemaster_posture"] == "OPEN"
