"""Cancelling a mapping cycle defers every live entry and releases the facility's posture."""
from test_helpers import (
    setup_base, create_approved_item, create_cycle, create_entry, disposition_entry,
    cycle_lifecycle, read_cycle, read_entry, read_item, read_facility, set_clock,
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


def test_cancellation_defers_the_mapped_and_the_pending_entry_alike():
    """PRD §3.7: "Cancellation sets `status` to `CANCELLED` and transitions every entry whose
    `status` is `PENDING` or `MAPPED` to `DEFERRED` with `defer_reason` set to `'CYCLE_CANCELLED'`,
    then re-derives the facility's posture — the second derivation rule no longer holds for this
    cycle — with `Facility.version` advancing by 1."
    PRD §3.7: "When a mapped entry's target item transitions `INACTIVE → ARCHIVED`, or when the
    owning cycle is cancelled, the entry moves to `DEFERRED` with `defer_reason` set to
    `'TARGET_ARCHIVED'` or `'CYCLE_CANCELLED'` respectively, its `target_charge_item_id` cleared to
    null, its `version` advanced by 1, and the cycle's `unmapped_entry_count` recomputed"
    PRD §3.7: "On success the cycle's `status` becomes `MAPPING`, and re-deriving the facility's
    posture yields `RESTRICTED` by rule 2 unless a transparency file is holding it at `FROZEN`;
    `Facility.version` advances by 1."

    Design: Corner/state_machines/code_update_cycle_cancel_defers_both_pending_and_mapped_entries
    """
    set_clock("2026-09-01T00:00:00Z")
    base = setup_base(**MERCY)
    item = create_approved_item(
        base, cdm_number="CDM-1001", description="CARDIAC CATH BASIC",
        code_type="CPT", code_value="93458", cost_basis_cents=100000,
        medicare_rate_cents=50000, market_p75_cents=900000,
        effective_from="2026-09-01T00:00:00Z",
    )
    assert item["lifecycle_status"] == "APPROVED"
    assert item["gross_charge_cents"] == 240000
    assert read_facility(base["facility"]["id"])["aggregate_gross_charge_cents"] == 0, (
        "an APPROVED item is not yet part of any aggregate"
    )

    cycle = create_cycle(base["facility"]["id"], cycle_year=2027, code_set="CPT")
    revise = create_entry(cycle["id"], "REVISE", old_code_value="93458",
                          new_code_value="93460")
    add = create_entry(cycle["id"], "ADD", old_code_value=None, new_code_value="93999")

    mapping = cycle_lifecycle(cycle["id"], "START_MAPPING")
    assert mapping["status"] == "MAPPING"
    assert read_facility(base["facility"]["id"])["chargemaster_posture"] == "RESTRICTED"

    revise = disposition_entry(revise["id"], "MAP")
    assert revise["status"] == "MAPPED"
    assert revise["target_charge_item_id"] == item["id"]
    assert revise["carried_gross_charge_cents"] == 240000, (
        "a pure code substitution carries the price forward untouched"
    )
    assert read_entry(add["id"])["status"] == "PENDING"

    cancelled = cycle_lifecycle(cycle["id"], "CANCEL", note="Cycle withdrawn by CMS")
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["unmapped_entry_count"] == 0, "no entry is awaiting disposition any more"
    assert read_cycle(cycle["id"])["version"] == 6

    deferred_revise = read_entry(revise["id"])
    assert deferred_revise["status"] == "DEFERRED"
    assert deferred_revise["defer_reason"] == "CYCLE_CANCELLED"
    assert deferred_revise["target_charge_item_id"] is None
    assert deferred_revise["version"] == 3

    deferred_add = read_entry(add["id"])
    assert deferred_add["status"] == "DEFERRED"
    assert deferred_add["defer_reason"] == "CYCLE_CANCELLED"
    assert deferred_add["version"] == 2

    assert read_facility(base["facility"]["id"])["chargemaster_posture"] == "OPEN", (
        "the cancelled cycle no longer satisfies the second derivation rule"
    )
    untouched = read_item(item["id"])
    assert untouched["code_value"] == "93458", "nothing ever applied to the item"
    assert untouched["gross_charge_cents"] == 240000
