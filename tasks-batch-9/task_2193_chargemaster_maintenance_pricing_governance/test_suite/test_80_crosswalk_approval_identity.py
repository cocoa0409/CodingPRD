"""The cycle-level segregation of duties: one mapped entry is enough to bar the mapper."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, ApiErrorId, factories,
    setup_base, create_active_item, create_cycle, create_entry, disposition_entry,
    cycle_lifecycle, read_cycle, read_entry, read_facility, set_clock,
    make_analyst_headers, make_approver_headers, make_manager_headers,
    ANALYST, ANALYST2, ANALYST2_USER_ID, APPROVER2, APPROVER2_USER_ID, CONTRACT,
    MANAGER_USER_ID,
)

MERCY = dict(
    facility_overrides={
        "name": "Mercy General", "cms_certification_number": "CCN-2193-XWALKSOD",
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
DUAL_USER_ID = "user-dual-2"
DUAL_ANALYST = make_analyst_headers(DUAL_USER_ID)
DUAL_APPROVER = make_approver_headers(DUAL_USER_ID)


def test_the_mapper_of_a_single_entry_cannot_approve_that_cycle_but_may_approve_another():
    """PRD §3.7: "And `X-User-ID` must differ from the `mapped_by_user_id` recorded on *every* entry of the
    cycle, otherwise `ERR_SEGREGATION_OF_DUTIES` (409)."
    PRD §3.7: "On success `target_charge_item_id` records the resolved item, `mapped_by_user_id` records
    `X-User-ID`, `carried_gross_charge_cents` is computed as described next, `status` becomes `MAPPED`, and
    the cycle's `unmapped_entry_count` is recomputed with `CodeUpdateCycle.version` advancing by 1."
    PRD §3.7: "On success `status` becomes `CROSSWALK_APPROVED`; the facility's posture remains
    `RESTRICTED`, since the derivation's second rule covers `CROSSWALK_APPROVED` just as it covers
    `MAPPING`."
    PRD §3.7: "The triple `(facility_id, code_set, cycle_year)` must be unique; a collision is
    `ERR_DUPLICATE_KEY`."
    PRD §4: "| POST | `/chargemaster/code-update-cycles/{cycle_id}/lifecycle` | Drive the cycle state
    machine (`START_MAPPING`, `APPROVE_CROSSWALK`, `ACTIVATE`, `ROLL_BACK`, `CANCEL`). |
    RevenueIntegrityAnalyst, PricingCommitteeApprover, ComplianceOfficer |"
    PRD §4: "| POST | `/chargemaster/code-update-entries/{entry_id}/disposition` | Map or defer a pending
    entry (`MAP`, `DEFER`). | RevenueIntegrityAnalyst |"
    PRD §4: "| POST | `/chargemaster/code-update-cycles` | Load an annual CPT/HCPCS code update cycle for a
    facility. | RevenueIntegrityAnalyst |"

    Design: Corner/rbac/crosswalk_approval_rejects_the_analyst_who_mapped_the_entries_and_every_non_owning_role
    """
    set_clock("2026-09-01T00:00:00Z")
    base = setup_base(**MERCY)
    facility_id = base["facility"]["id"]
    first = create_active_item(base, cdm_number="CDM-1001", description="CARDIAC CATH BASIC",
                              code_type="CPT", code_value="93458", **PRICING)
    second = create_active_item(base, cdm_number="CDM-2002", description="CARDIAC CATH COMPLEX",
                               code_type="CPT", code_value="93460", **PRICING)
    third = create_active_item(base, cdm_number="CDM-3003", description="DRUG ADMIN SUPPLY",
                               code_type="HCPCS", code_value="C9999", **PRICING)
    assert [first["gross_charge_cents"], second["gross_charge_cents"],
            third["gross_charge_cents"]] == [240000, 240000, 240000]

    cpt_cycle = create_cycle(facility_id, cycle_year=2027, code_set="CPT")
    entry_one = create_entry(cpt_cycle["id"], "REVISE", old_code_value="93458",
                             new_code_value="93458A")
    entry_two = create_entry(cpt_cycle["id"], "REVISE", old_code_value="93460",
                             new_code_value="93460A")
    assert cycle_lifecycle(cpt_cycle["id"], "START_MAPPING")["status"] == "MAPPING"

    hcpcs_cycle = create_cycle(facility_id, cycle_year=2027, code_set="HCPCS")
    entry_three = create_entry(hcpcs_cycle["id"], "REVISE", old_code_value="C9999",
                               new_code_value="C9998")
    assert cycle_lifecycle(hcpcs_cycle["id"], "START_MAPPING")["status"] == "MAPPING", (
        "the triple (facility, code_set, cycle_year) differs, so a second cycle is legal"
    )

    mapped_one = disposition_entry(entry_one["id"], "MAP", DUAL_ANALYST)
    assert mapped_one["status"] == "MAPPED"
    assert mapped_one["mapped_by_user_id"] == DUAL_USER_ID
    assert mapped_one["target_charge_item_id"] == first["id"]
    mapped_two = disposition_entry(entry_two["id"], "MAP", ANALYST2)
    assert mapped_two["status"] == "MAPPED"
    assert mapped_two["mapped_by_user_id"] == ANALYST2_USER_ID
    mapped_three = disposition_entry(entry_three["id"], "MAP",
                                     make_analyst_headers("user-analyst-9"))
    assert mapped_three["status"] == "MAPPED"
    assert mapped_three["mapped_by_user_id"] == "user-analyst-9"
    assert read_cycle(cpt_cycle["id"])["unmapped_entry_count"] == 0

    validate_error(
        api_client.code_update_cycle_lifecycle(
            cpt_cycle["id"], {"action": "APPROVE_CROSSWALK"}, DUAL_APPROVER),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 409,
    )
    assert read_cycle(cpt_cycle["id"])["status"] == "MAPPING", (
        "mapping only one of the two entries is still enough to bar the approval"
    )

    other = validate_success(api_client.code_update_cycle_lifecycle(
        hcpcs_cycle["id"], {"action": "APPROVE_CROSSWALK"}, DUAL_APPROVER), 200)
    assert other["status"] == "CROSSWALK_APPROVED", (
        "the very same identity approves the cycle whose only entry another analyst mapped"
    )

    validate_error(
        api_client.code_update_cycle_lifecycle(
            cpt_cycle["id"], {"action": "APPROVE_CROSSWALK"}, CONTRACT),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403,
    )
    manager = make_manager_headers(MANAGER_USER_ID)
    validate_error(
        api_client.disposition_code_update_entry(
            entry_one["id"], {"action": "MAP"}, manager),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403,
    )
    validate_error(
        api_client.create_code_update_cycle(
            factories.create_code_update_cycle_payload(facility_id, cycle_year=2028,
                                                       code_set="CPT"), manager),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403,
    )

    approved = validate_success(api_client.code_update_cycle_lifecycle(
        cpt_cycle["id"], {"action": "APPROVE_CROSSWALK"}, APPROVER2), 200)
    assert approved["status"] == "CROSSWALK_APPROVED", (
        "an approver who mapped nothing closes the crosswalk"
    )
    assert APPROVER2_USER_ID != DUAL_USER_ID
    assert read_entry(entry_one["id"])["status"] == "MAPPED", (
        "the refused manager disposition left the entry exactly as the analyst mapped it"
    )
    assert read_entry(entry_one["id"])["mapped_by_user_id"] == DUAL_USER_ID
    assert read_facility(facility_id)["chargemaster_posture"] == "RESTRICTED", (
        "CROSSWALK_APPROVED holds the posture where MAPPING left it"
    )
    rows, meta = validate_paginated(
        api_client.list_code_update_cycles(ANALYST, {"facility_id": facility_id}))
    assert meta["total_count"] == 2, (
        "the 2028 cycle the manager tried to load was never created"
    )
    assert {row["status"] for row in rows} == {"CROSSWALK_APPROVED"}
