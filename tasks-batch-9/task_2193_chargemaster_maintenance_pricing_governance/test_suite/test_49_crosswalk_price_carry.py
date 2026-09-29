"""The carry inflates the cost basis before tier selection, and only when the code truly moves."""
from test_helpers import (
    setup_base, create_revenue_code, create_price_rule, create_approved_item,
    create_active_item, create_cycle, create_entry, disposition_entry, cycle_lifecycle,
    read_cycle, read_entry, read_item, read_facility, set_clock,
    ANALYST_USER_ID,
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


def test_the_inflated_cost_basis_crosses_a_tier_boundary_the_raw_cost_would_not():
    """PRD §3.7: "Only when the revenue code genuinely changes is the price rebuilt, and then in a
    pinned order. First the target item's `cost_basis_cents` is multiplied by the cycle's
    `cost_inflator_bp`, divided by 10000, and rounded half up to whole cents. Then the full
    gross-charge computation of §3.2 is run against the target item as if its cost basis were that
    inflated amount and its revenue code were the entry's `new_revenue_code_id`, selecting the price
    rule that applies to the **new** revenue code at map time. Because the inflation is rounded
    *before* tier selection, an inflated cost basis can cross a markup tier boundary and pick up a
    different `markup_bp` than the pre-inflation cost would have; inflating the resulting charge
    instead of the cost basis produces a different number and is wrong."
    PRD §3.7: "an optional `cost_inflator_bp` defaulting to 10300 basis points — a three percent cost
    inflation applied when a crosswalk also moves the revenue code."
    PRD §3.7: "On success `target_charge_item_id` records the resolved item, `mapped_by_user_id`
    records `X-User-ID`, `carried_gross_charge_cents` is computed as described next, `status` becomes
    `MAPPED`, and the cycle's `unmapped_entry_count` is recomputed with `CodeUpdateCycle.version`
    advancing by 1."

    Design: Corner/calculations/crosswalk_carry_inflates_cost_first_so_the_inflated_basis_crosses_a_markup_tier
    """
    set_clock("2026-09-01T00:00:00Z")
    base = setup_base(**MERCY)
    rc301 = create_revenue_code(
        code="0301", description="Laboratory - chemistry", requires_hcpcs=False,
        allowed_code_types=["CPT", "HCPCS", "REV_ONLY", "CDM_INTERNAL"],
        pricing_class="PROCEDURE",
    )
    create_price_rule(base["facility"]["id"], rc301["id"],
                      effective_from="2026-01-01T00:00:00Z")

    item = create_approved_item(
        base, cdm_number="CDM-1001", description="PATHOLOGY SPECIMEN",
        code_type="CPT", code_value="88301", cost_basis_cents=48544,
        medicare_rate_cents=10000, market_p75_cents=900000,
        effective_from="2026-09-01T00:00:00Z",
    )
    assert item["gross_charge_cents"] == 155341, "48544 of cost sits in the 32000 bp band"

    cycle = create_cycle(base["facility"]["id"], cycle_year=2027, code_set="CPT")
    assert cycle["cost_inflator_bp"] == 10300, "the default three percent inflation"
    entry = create_entry(cycle["id"], "CROSSWALK", old_code_value="88301",
                         new_code_value="88302", new_revenue_code_id=rc301["id"])
    cycle_lifecycle(cycle["id"], "START_MAPPING")

    mapped = disposition_entry(entry["id"], "MAP")
    assert mapped["carried_gross_charge_cents"] == 120000, (
        "48544 inflated to 50000 lands exactly on the second tier, giving 50000 at 24000 bp; "
        "inflating the 155341 charge would have given 160001 instead"
    )
    assert mapped["target_charge_item_id"] == item["id"]
    assert mapped["status"] == "MAPPED"
    assert mapped["mapped_by_user_id"] == ANALYST_USER_ID
    assert read_entry(entry["id"])["version"] == 2

    stored_cycle = read_cycle(cycle["id"])
    assert stored_cycle["unmapped_entry_count"] == 0
    assert stored_cycle["entry_count"] == 1
    assert stored_cycle["status"] == "MAPPING"
    assert stored_cycle["version"] == 4, "create, entry, start mapping, map"

    untouched = read_item(item["id"])
    assert untouched["gross_charge_cents"] == 155341, "the carry is not applied until ACTIVATE"
    assert untouched["revenue_code_id"] == base["revenue_code"]["id"]
    assert untouched["version"] == 4, "create, reprice, submit, approve"
    assert read_facility(base["facility"]["id"])["chargemaster_posture"] == "RESTRICTED"


def test_delete_and_pure_substitution_carry_the_existing_charge_verbatim():
    """PRD §3.7: "When the entry's `action` is `DELETE`, the carry is the target item's current
    `gross_charge_cents` unchanged — the item will simply be deactivated at apply time. When
    `new_revenue_code_id` is null, or when it names the same revenue code the item already has, the
    carry is again the target item's current `gross_charge_cents`: a pure code substitution carries
    the price forward."
    PRD §3.7: "Unless the entry's `action` is `ADD`, exactly one `ChargeItem` in the cycle's facility
    must have `code_value` equal to the entry's `old_code_value` with `lifecycle_status` in `ACTIVE`,
    `INACTIVE` or `APPROVED`: zero matches is `ERR_CROSSWALK_TARGET_NOT_FOUND` (404) and more than
    one is `ERR_CROSSWALK_TARGET_AMBIGUOUS` (409)."
    PRD §3.7: "An entry is created in `PENDING`; the cycle's `entry_count` and
    `unmapped_entry_count` are recomputed and `CodeUpdateCycle.version` advances by 1."

    Design: Corner/calculations/crosswalk_carry_ignores_the_inflator_on_delete_and_on_pure_code_substitution
    """
    set_clock("2026-09-01T00:00:00Z")
    base = setup_base(**MERCY)
    item_a = create_active_item(
        base, cdm_number="CDM-1001", description="PATHOLOGY SPECIMEN",
        code_type="CPT", code_value="88301", cost_basis_cents=100000,
        medicare_rate_cents=50000, market_p75_cents=900000,
        effective_from="2026-09-01T00:00:00Z",
    )
    item_b = create_approved_item(
        base, cdm_number="CDM-1002", description="CARDIAC CATH BASIC",
        code_type="CPT", code_value="93458", cost_basis_cents=60000,
        medicare_rate_cents=20000, market_p75_cents=900000,
        effective_from="2026-09-01T00:00:00Z",
    )
    item_c = create_approved_item(
        base, cdm_number="CDM-1003", description="OFFICE VISIT EXTENDED",
        code_type="CPT", code_value="12345", cost_basis_cents=70000,
        medicare_rate_cents=10000, market_p75_cents=900000,
        effective_from="2026-09-01T00:00:00Z",
    )
    assert item_a["gross_charge_cents"] == 240000
    assert item_b["gross_charge_cents"] == 144000
    assert item_c["gross_charge_cents"] == 168000

    cycle = create_cycle(base["facility"]["id"], cycle_year=2027, code_set="CPT",
                         cost_inflator_bp=12000)
    entry_delete = create_entry(cycle["id"], "DELETE", old_code_value="88301",
                               new_code_value=None)
    entry_revise = create_entry(cycle["id"], "REVISE", old_code_value="93458",
                               new_code_value="93459")
    entry_same = create_entry(cycle["id"], "CROSSWALK", old_code_value="12345",
                             new_code_value="12346",
                             new_revenue_code_id=base["revenue_code"]["id"])
    cycle_lifecycle(cycle["id"], "START_MAPPING")

    carried_delete = disposition_entry(entry_delete["id"], "MAP")
    carried_revise = disposition_entry(entry_revise["id"], "MAP")
    carried_same = disposition_entry(entry_same["id"], "MAP")
    assert carried_delete["carried_gross_charge_cents"] == 240000, (
        "a DELETE carry never inflates; 288000 would be the inflated answer"
    )
    assert carried_revise["carried_gross_charge_cents"] == 144000, (
        "a null new_revenue_code_id is a pure code substitution"
    )
    assert carried_same["carried_gross_charge_cents"] == 168000, (
        "naming the revenue code the item already has is not a genuine change"
    )
    assert carried_delete["target_charge_item_id"] == item_a["id"]
    assert carried_revise["target_charge_item_id"] == item_b["id"]
    assert carried_same["target_charge_item_id"] == item_c["id"]
    for entry in (carried_delete, carried_revise, carried_same):
        assert entry["status"] == "MAPPED"

    stored_cycle = read_cycle(cycle["id"])
    assert stored_cycle["cost_inflator_bp"] == 12000, "an exaggerated inflator that never applied"
    assert stored_cycle["entry_count"] == 3
    assert stored_cycle["unmapped_entry_count"] == 0
    assert stored_cycle["version"] == 8, "create, three entries, start mapping, three maps"
    assert read_facility(base["facility"]["id"])["aggregate_gross_charge_cents"] == 240000, (
        "only item A is ACTIVE, and mapping mutates no item"
    )
