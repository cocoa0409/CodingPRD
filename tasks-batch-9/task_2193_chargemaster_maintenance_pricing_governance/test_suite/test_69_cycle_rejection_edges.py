"""Every rejection edge of the code-update pair: empty, wrong-state, unresolvable and ambiguous."""
from test_helpers import (
    api_client, validate_error, ApiErrorId, factories,
    setup_base, create_active_item, create_cycle, create_entry, cycle_lifecycle,
    disposition_entry, read_cycle, read_entry, read_item, read_facility, set_clock,
    ANALYST, APPROVER, COMPLIANCE,
)

MERCY = dict(
    facility_overrides={
        "name": "Mercy General", "cms_certification_number": "CCN-2193-CYCERR",
        "rounding_mode": "NEAREST_CENT", "aggregate_markup_limit_bp": 40000,
    },
    revenue_code_overrides={
        "code": "0300", "description": "Laboratory - general", "requires_hcpcs": False,
        "allowed_code_types": ["CPT", "HCPCS", "REV_ONLY", "CDM_INTERNAL"],
        "pricing_class": "PROCEDURE", "status": "ACTIVE",
    },
    department_overrides={"name": "Cardiac Cath Lab", "cost_center_code": "CC-100",
                         "allowed_revenue_code_values": []},
    price_rule_overrides={"effective_from": "2026-01-01T00:00:00Z"},
)
PRICING = dict(cost_basis_cents=100000, medicare_rate_cents=50000,
               market_p75_cents=900000, effective_from="2026-09-01T00:00:00Z")


def _lifecycle_error(cycle_id, action, headers, error_id, status):
    validate_error(
        api_client.code_update_cycle_lifecycle(cycle_id, {"action": action}, headers),
        error_id, status,
    )


def _map_error(entry_id, error_id, status):
    validate_error(
        api_client.disposition_code_update_entry(entry_id, {"action": "MAP"}, ANALYST),
        error_id, status,
    )


def test_the_cycle_rejects_an_empty_start_a_loaded_map_an_unmapped_approval_and_a_cancelled_restart():
    """PRD §3.7: "`LOADED → MAPPING`, the analyst's start-mapping action, requires that `entry_count` be
    at least 1 — a cycle with no entries cannot start mapping, and the attempt is
    `ERR_CYCLE_HAS_NO_ENTRIES` (422)."
    PRD §3.7: "Each `PENDING` entry is then dispositioned by the analyst as either a map or a defer, both
    of which require the cycle to be in `MAPPING` (`ERR_INVALID_CYCLE_STATE`) and the entry itself to be
    in `PENDING` (`ERR_INVALID_ENTRY_STATE`, 409)."
    PRD §3.7: "Unless the entry's `action` is `ADD`, exactly one `ChargeItem` in the cycle's facility must
    have `code_value` equal to the entry's `old_code_value` with `lifecycle_status` in `ACTIVE`,
    `INACTIVE` or `APPROVED`: zero matches is `ERR_CROSSWALK_TARGET_NOT_FOUND` (404) and more than one is
    `ERR_CROSSWALK_TARGET_AMBIGUOUS` (409)."
    PRD §3.7: "Cancellation sets `status` to `CANCELLED` and transitions every entry whose `status` is
    `PENDING` or `MAPPED` to `DEFERRED` with `defer_reason` set to `'CYCLE_CANCELLED'`, then re-derives
    the facility's posture — the second derivation rule no longer holds for this cycle — with
    `Facility.version` advancing by 1."
    PRD §3.7: "Entries are added by the analyst while the cycle is in `LOADED` or `MAPPING`; adding an
    entry to a cycle past `MAPPING` is `ERR_INVALID_CYCLE_STATE` (409)."

    Design: Corner/errors/cycle_lifecycle_rejects_empty_unmapped_ambiguous_and_terminal_transitions
    """
    set_clock("2026-09-01T00:00:00Z")
    base = setup_base(**MERCY)
    facility_id = base["facility"]["id"]
    create_active_item(base, cdm_number="CDM-1001", description="CARDIAC CATH BASIC",
                       code_type="CPT", code_value="93458", **PRICING)
    twin_one = create_active_item(base, cdm_number="CDM-1002", description="CARDIAC CATH COMPLEX",
                                 code_type="CPT", code_value="93460", **PRICING)
    twin_two = create_active_item(base, cdm_number="CDM-1003", description="CARDIAC CATH REPEAT",
                                 code_type="CPT", code_value="93460", **PRICING)

    cycle = create_cycle(facility_id, cycle_year=2027, code_set="CPT")
    assert cycle["status"] == "LOADED"
    assert cycle["entry_count"] == 0

    _lifecycle_error(cycle["id"], "START_MAPPING", ANALYST,
                     ApiErrorId.ERR_CYCLE_HAS_NO_ENTRIES.value, 422)

    missing = create_entry(cycle["id"], "REVISE", old_code_value="93999",
                           new_code_value="93999A")
    assert missing["status"] == "PENDING", "entries may be added while the cycle is LOADED"

    _map_error(missing["id"], ApiErrorId.ERR_INVALID_CYCLE_STATE.value, 409)

    mapping = cycle_lifecycle(cycle["id"], "START_MAPPING")
    assert mapping["status"] == "MAPPING"
    assert read_facility(facility_id)["chargemaster_posture"] == "RESTRICTED"

    _map_error(missing["id"], ApiErrorId.ERR_CROSSWALK_TARGET_NOT_FOUND.value, 404)

    ambiguous = create_entry(cycle["id"], "REVISE", old_code_value="93460",
                             new_code_value="93460A")
    _map_error(ambiguous["id"], ApiErrorId.ERR_CROSSWALK_TARGET_AMBIGUOUS.value, 409)

    deferred = disposition_entry(missing["id"], "DEFER",
                                 defer_reason="No local item carries 93999")
    assert deferred["status"] == "DEFERRED"
    assert deferred["defer_reason"] == "No local item carries 93999"

    _map_error(missing["id"], ApiErrorId.ERR_INVALID_ENTRY_STATE.value, 409)

    second_deferred = disposition_entry(ambiguous["id"], "DEFER",
                                        defer_reason="Ambiguous target pending CDM cleanup")
    assert second_deferred["status"] == "DEFERRED"
    assert read_cycle(cycle["id"])["unmapped_entry_count"] == 0

    _lifecycle_error(cycle["id"], "APPROVE_CROSSWALK", APPROVER,
                     ApiErrorId.ERR_CYCLE_HAS_NO_MAPPED_ENTRIES.value, 422)
    _lifecycle_error(cycle["id"], "ACTIVATE", COMPLIANCE,
                     ApiErrorId.ERR_INVALID_CYCLE_STATE.value, 409)

    cancelled = cycle_lifecycle(cycle["id"], "CANCEL", COMPLIANCE)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["applied_entry_count"] == 0

    _lifecycle_error(cycle["id"], "START_MAPPING", ANALYST,
                     ApiErrorId.ERR_INVALID_CYCLE_STATE.value, 409)
    validate_error(
        api_client.create_code_update_entry(
            cycle["id"],
            factories.create_code_update_entry_payload("ADD", new_code_value="0001U"),
            ANALYST),
        ApiErrorId.ERR_INVALID_CYCLE_STATE.value, 409,
    )

    final = read_cycle(cycle["id"])
    assert final["entry_count"] == 2, "the rejected entry creation stored nothing"
    for entry_id in (missing["id"], ambiguous["id"]):
        entry = read_entry(entry_id)
        assert entry["status"] == "DEFERRED"
        assert entry["target_charge_item_id"] is None

    assert read_item(twin_one["id"])["code_value"] == "93460", "no crosswalk was ever applied"
    assert read_item(twin_two["id"])["code_value"] == "93460"
    facility = read_facility(facility_id)
    assert facility["chargemaster_posture"] == "OPEN", "CANCEL releases the mapping blackout"
    assert facility["active_item_count"] == 3
    assert facility["aggregate_gross_charge_cents"] == 720000
