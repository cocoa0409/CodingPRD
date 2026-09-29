"""The mutual standoff: a pending crosswalk blocks the item, an approved request blocks the cycle."""
from test_helpers import (
    api_client, validate_error, ApiErrorId,
    setup_base, create_approved_item, create_cycle, create_entry, disposition_entry,
    cycle_lifecycle, read_cycle, read_entry, read_item, read_facility,
    create_change_request, review_change_request, approve_change_request,
    implement_change_request, set_clock,
    ANALYST, APPROVER, COMPLIANCE,
)

MERCY = dict(
    facility_overrides={
        "name": "Mercy General", "cms_certification_number": "CCN-2193-STANDOFF",
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


def test_a_mapped_entry_blocks_the_item_while_an_approved_request_blocks_the_cycle():
    """PRD §3.3: "And no `CodeUpdateEntry` whose `target_charge_item_id` names this item may sit in
    `MAPPED` status inside a cycle that has reached `CROSSWALK_APPROVED`, otherwise
    `ERR_ITEM_PENDING_CODE_UPDATE` (409) — an item about to be rewritten by an approved crosswalk must
    not be activated under its old code first."
    PRD §3.7: "Two preconditions apply: the facility must not be `FROZEN` — no transparency file may be
    sitting in `BUILDING` or `VALIDATED` — otherwise `ERR_FACILITY_FROZEN` (409); and no `ChangeRequest`
    in `APPROVED` status may target any item referenced by a `MAPPED` entry of this cycle, otherwise
    `ERR_ITEM_HAS_OPEN_REQUEST` (409)."
    PRD §3.7: "When `new_revenue_code_id` is null, or when it names the same revenue code the item
    already has, the carry is again the target item's current `gross_charge_cents`: a pure code
    substitution carries the price forward."
    PRD §3.7: "First, every entry whose `status` is `MAPPED` is processed **in order of `created_at`
    ascending**, transitions `MAPPED → APPLIED`, and snapshots four values from its target item for later
    rollback: `prior_code_value` from the item's `code_value`, `prior_revenue_code_id` from its
    `revenue_code_id`, `prior_gross_charge_cents` from its `gross_charge_cents`, and
    `prior_lifecycle_status` from its `lifecycle_status`; each entry's `version` advances by 1."
    PRD §3.7: "Second, each applied entry mutates its target item: for `CROSSWALK` and `REVISE`, the
    item's `code_value` takes `new_code_value`, its `revenue_code_id` takes `new_revenue_code_id` when
    that field is non-null, its `gross_charge_cents` takes the entry's `carried_gross_charge_cents`, and
    its `price_status` moves to `PRICE_STALE`; for `DELETE`, the item's `lifecycle_status` moves to
    `INACTIVE`."

    Design: Corner/errors/activation_rejected_while_a_crosswalk_is_pending_and_cycle_activation_rejected_by_an_approved_request
    """
    set_clock("2026-09-01T00:00:00Z")
    base = setup_base(**MERCY)
    facility_id = base["facility"]["id"]
    item = create_approved_item(base, cdm_number="CDM-1003", description="CT ABDOMEN CONTRAST",
                                code_type="CPT", code_value="93470", cost_basis_cents=100000,
                                medicare_rate_cents=50000, market_p75_cents=900000,
                                effective_from="2026-09-01T00:00:00Z")
    assert item["lifecycle_status"] == "APPROVED"
    assert item["price_status"] == "PRICED_CURRENT"
    assert item["gross_charge_cents"] == 240000
    assert item["version"] == 4, "create, reprice, submit, approve"

    cycle = create_cycle(facility_id, cycle_year=2027, code_set="CPT")
    entry = create_entry(cycle["id"], "REVISE", old_code_value="93470",
                         new_code_value="93470A")
    cycle_lifecycle(cycle["id"], "START_MAPPING")
    mapped = disposition_entry(entry["id"], "MAP")
    assert mapped["status"] == "MAPPED"
    assert mapped["target_charge_item_id"] == item["id"], (
        "the APPROVED item is a legal crosswalk target"
    )
    assert mapped["carried_gross_charge_cents"] == 240000, (
        "a null new_revenue_code_id carries the price forward unchanged"
    )
    approved_cycle = cycle_lifecycle(cycle["id"], "APPROVE_CROSSWALK", APPROVER)
    assert approved_cycle["status"] == "CROSSWALK_APPROVED"
    assert read_facility(facility_id)["chargemaster_posture"] == "RESTRICTED"

    validate_error(
        api_client.charge_item_lifecycle(item["id"], {"action": "ACTIVATE"}, APPROVER),
        ApiErrorId.ERR_ITEM_PENDING_CODE_UPDATE.value, 409,
    )

    request = create_change_request(base, item["id"], "PRICE_CHANGE",
                                    justification="Contrast supply cost increase for imaging",
                                    proposed_cost_basis_cents=150000)
    assert request["projected_gross_charge_cents"] == 360000, (
        "cost 150000 sits in the 50000 tier at 24000 bp, inside the 60000 floor and 990000 cap"
    )
    assert review_change_request(request["id"], ANALYST,
                                 decision_note="Invoice verified")["status"] == "UNDER_REVIEW"
    approved_request = approve_change_request(request["id"], 4, APPROVER,
                                              decision_note="Approved")
    assert approved_request["status"] == "APPROVED"
    assert approved_request["pinned_charge_item_version"] == 5, "the pin is the post-bump version"

    validate_error(
        api_client.code_update_cycle_lifecycle(cycle["id"], {"action": "ACTIVATE"}, COMPLIANCE),
        ApiErrorId.ERR_ITEM_HAS_OPEN_REQUEST.value, 409,
    )
    assert read_cycle(cycle["id"])["status"] == "CROSSWALK_APPROVED", "the refusal changed nothing"

    implemented = implement_change_request(request["id"],
                                          implementation_note="Applying approved cost basis")
    assert implemented["status"] == "IMPLEMENTED"
    after_implement = read_item(item["id"])
    assert after_implement["cost_basis_cents"] == 150000
    assert after_implement["gross_charge_cents"] == 360000
    assert after_implement["price_status"] == "PRICED_CURRENT"

    activated = cycle_lifecycle(cycle["id"], "ACTIVATE", COMPLIANCE)
    assert activated["status"] == "ACTIVATED", "the request no longer blocks the cycle"
    assert activated["applied_entry_count"] == 1

    applied_entry = read_entry(entry["id"])
    assert applied_entry["status"] == "APPLIED"
    assert applied_entry["prior_code_value"] == "93470"
    assert applied_entry["prior_gross_charge_cents"] == 360000, (
        "the rollback snapshot is taken at activation, after the implementation"
    )
    assert applied_entry["prior_lifecycle_status"] == "APPROVED"

    final = read_item(item["id"])
    assert final["code_value"] == "93470A"
    assert final["gross_charge_cents"] == 240000, (
        "the carry frozen at map time overwrites the freshly implemented 360000"
    )
    assert final["price_status"] == "PRICE_STALE"
    assert final["last_code_cycle_id"] == cycle["id"]

    facility = read_facility(facility_id)
    assert facility["active_item_count"] == 0
    assert facility["stale_price_item_count"] == 0, "the stale item is APPROVED, never ACTIVE"
    assert facility["chargemaster_posture"] == "OPEN", (
        "the cycle has left the MAPPING / CROSSWALK_APPROVED window"
    )
