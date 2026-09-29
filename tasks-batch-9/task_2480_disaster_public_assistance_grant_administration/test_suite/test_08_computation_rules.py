"""Computed outcomes: rule cascades that stop at the first failure, threshold
comparisons that are boundary exact, ordered allocation, and the two closeout
reconciliation policies.
"""
import pytest

from test_helpers import (
    AUDITOR_USER_ID,
    SECOND_GRANTS_OFFICER_USER_ID,
    TEST_USERS,
    cost_review,
    create_applicant,
    create_contract,
    create_cost_line_item,
    create_damage_site,
    create_disaster,
    create_equipment_resource,
    create_facility,
    create_insurance_policy,
    create_labor_resource,
    create_project,
    determine_eligibility,
    get_applicant,
    get_contract,
    get_disaster,
    get_force_account_resource,
    get_insurance_policy,
    get_project,
    make_applicant_agent_headers,
    make_auditor_headers,
    make_grants_officer_headers,
    make_specialist_headers,
    obligate_project,
    record_settlement,
    request_closeout,
    review_cost_line_item,
    review_procurement,
    screen_facility,
    set_clock,
    submit_project,
    validate_paginated,
    validate_success,
)

READER = TEST_USERS["admin_headers"]


def _deobligations_for_project(api, project_id):
    """Every determination recorded against one project, read back through the
    collection endpoint and narrowed on the row's own `project_id`."""
    rows, _meta = validate_paginated(api.list_deobligations(READER))
    return [row for row in rows if row["project_id"] == project_id]


# ---------------------------------------------------------------------------
# Facility screening: the first failing rule decides the recorded reason
# ---------------------------------------------------------------------------
def test_facility_screening_first_failing_rule_decides_the_reason(api):
    """PRD §3.2: "The rules are evaluated in exactly this order and the **first**
    failure decides both the outcome and the `screening_failure_reason` recorded
    on the row:"
    PRD §3.2: "If `legal_responsibility_documented` is false, the facility is
    `INELIGIBLE` with reason `LEGAL_RESPONSIBILITY_NOT_DOCUMENTED`."
    PRD §3.2: "Otherwise, if `in_active_use` is false, the facility is
    `INELIGIBLE` with reason `NOT_IN_ACTIVE_USE`."
    PRD §3.2: "Whichever branch fires, `screened_at` is stamped with the logical
    clock and the facility's `version` increments by 1; the `PENDING → ELIGIBLE`
    branch additionally clears `screening_failure_reason` to null, and the
    `PENDING → INELIGIBLE` branch sets it to the first failed rule's code."

    Design: Corner/calculations/facility_screening_first_failing_rule_decides_the_reason
    """
    set_clock("2026-07-01T00:00:00Z")
    disaster = create_disaster(declaration_number="DR-4956")
    applicant = create_applicant(
        disaster["id"],
        name="City of Harborview",
        applicant_type="LOCAL_GOVERNMENT",
        population_served=120_000,
    )
    facility_a = create_facility(
        applicant["id"],
        name="Shuttered Annex",
        facility_type="BUILDING_EQUIPMENT",
        ownership="PUBLIC",
        legal_responsibility_documented=False,
        in_active_use=False,
    )
    facility_b = create_facility(
        applicant["id"],
        name="Mothballed Depot",
        facility_type="BUILDING_EQUIPMENT",
        ownership="PUBLIC",
        in_active_use=False,
    )

    screened_a = validate_success(
        api.screen_facility(facility_a["id"], make_specialist_headers())
    )
    screened_b = validate_success(
        api.screen_facility(facility_b["id"], make_specialist_headers())
    )

    assert screened_a["eligibility_status"] == "INELIGIBLE", (
        f"Expected INELIGIBLE, got {screened_a['eligibility_status']} for the facility "
        "failing both documentation and active use"
    )
    assert screened_a["screening_failure_reason"] == "LEGAL_RESPONSIBILITY_NOT_DOCUMENTED", (
        "Rule 1 outranks rule 2: expected LEGAL_RESPONSIBILITY_NOT_DOCUMENTED, got "
        f"{screened_a['screening_failure_reason']}"
    )
    assert screened_b["eligibility_status"] == "INELIGIBLE", (
        f"Expected INELIGIBLE, got {screened_b['eligibility_status']}"
    )
    assert screened_b["screening_failure_reason"] == "NOT_IN_ACTIVE_USE", (
        f"Expected NOT_IN_ACTIVE_USE, got {screened_b['screening_failure_reason']}"
    )
    for screened in (screened_a, screened_b):
        assert screened["screened_at"].startswith("2026-07-01T00:00:00"), (
            f"Expected screened_at stamped from the logical clock, got {screened['screened_at']}"
        )
        assert screened["version"] == 2, (
            f"Expected version 2 after screening, got {screened['version']}"
        )


# ---------------------------------------------------------------------------
# Facility screening: the three nonprofit-only rules in their fixed order
# ---------------------------------------------------------------------------
def test_pnp_screening_ownership_then_tax_exempt_then_service_cascade(api):
    """PRD §3.2: "Otherwise, if the owning applicant's `applicant_type` is
    `PRIVATE_NONPROFIT`, three nonprofit-only rules run in their own fixed
    order: if `ownership` is anything other than `PNP_OWNED`, the facility is
    `INELIGIBLE` with reason `PNP_MUST_OWN_FACILITY`; else if the applicant's
    `tax_exempt_letter_on_file` is false, the facility is `INELIGIBLE` with
    reason `TAX_EXEMPT_DOCUMENTATION_MISSING`; else if the applicant's
    `pnp_service_type` is `NON_ELIGIBLE`, the facility is `INELIGIBLE` with
    reason `PNP_SERVICE_NOT_ELIGIBLE`."
    PRD §3.2: "Otherwise the facility is `ELIGIBLE` and
    `screening_failure_reason` is null."

    Design: Corner/calculations/pnp_screening_ownership_then_tax_exempt_then_service_cascade
    """
    set_clock("2026-07-01T00:00:00Z")
    disaster = create_disaster(declaration_number="DR-4957")

    pnp_a = create_applicant(
        disaster["id"],
        name="Harborview Free Clinic",
        applicant_type="PRIVATE_NONPROFIT",
        population_served=8_000,
        pnp_service_type="CRITICAL",
        tax_exempt_letter_on_file=False,
    )
    facility_a = create_facility(
        pnp_a["id"], name="Clinic Wing", facility_type="BUILDING_EQUIPMENT", ownership="PUBLIC"
    )
    pnp_b = create_applicant(
        disaster["id"],
        name="Riverside Food Bank",
        applicant_type="PRIVATE_NONPROFIT",
        population_served=5_000,
        pnp_service_type="CRITICAL",
        tax_exempt_letter_on_file=False,
    )
    facility_b = create_facility(
        pnp_b["id"],
        name="Food Bank Warehouse",
        facility_type="BUILDING_EQUIPMENT",
        ownership="PNP_OWNED",
    )
    pnp_c = create_applicant(
        disaster["id"],
        name="Harborview Yacht Club",
        applicant_type="PRIVATE_NONPROFIT",
        population_served=900,
        pnp_service_type="NON_ELIGIBLE",
        tax_exempt_letter_on_file=True,
    )
    facility_c = create_facility(
        pnp_c["id"], name="Club House", facility_type="BUILDING_EQUIPMENT", ownership="PNP_OWNED"
    )
    pnp_d = create_applicant(
        disaster["id"],
        name="Harborview Volunteer Fire",
        applicant_type="PRIVATE_NONPROFIT",
        population_served=12_000,
        pnp_service_type="CRITICAL",
        tax_exempt_letter_on_file=True,
    )
    facility_d = create_facility(
        pnp_d["id"], name="Fire Station 2", facility_type="BUILDING_EQUIPMENT", ownership="PNP_OWNED"
    )
    lg_e = create_applicant(
        disaster["id"],
        name="City of Harborview",
        applicant_type="LOCAL_GOVERNMENT",
        population_served=120_000,
    )
    facility_e = create_facility(
        lg_e["id"], name="Leased Motor Pool", facility_type="BUILDING_EQUIPMENT", ownership="LEASED"
    )

    screened_a = validate_success(
        api.screen_facility(facility_a["id"], make_specialist_headers())
    )
    screened_b = validate_success(
        api.screen_facility(facility_b["id"], make_specialist_headers())
    )
    screened_c = validate_success(
        api.screen_facility(facility_c["id"], make_specialist_headers())
    )
    screened_d = validate_success(
        api.screen_facility(facility_d["id"], make_specialist_headers())
    )
    screened_e = validate_success(
        api.screen_facility(facility_e["id"], make_specialist_headers())
    )

    assert screened_a["eligibility_status"] == "INELIGIBLE", (
        f"Expected INELIGIBLE, got {screened_a['eligibility_status']}"
    )
    assert screened_a["screening_failure_reason"] == "PNP_MUST_OWN_FACILITY", (
        "Ownership outranks the tax-exempt letter: expected PNP_MUST_OWN_FACILITY, got "
        f"{screened_a['screening_failure_reason']}"
    )
    assert screened_b["eligibility_status"] == "INELIGIBLE", (
        f"Expected INELIGIBLE, got {screened_b['eligibility_status']}"
    )
    assert screened_b["screening_failure_reason"] == "TAX_EXEMPT_DOCUMENTATION_MISSING", (
        f"Expected TAX_EXEMPT_DOCUMENTATION_MISSING, got {screened_b['screening_failure_reason']}"
    )
    assert screened_c["eligibility_status"] == "INELIGIBLE", (
        f"Expected INELIGIBLE, got {screened_c['eligibility_status']}"
    )
    assert screened_c["screening_failure_reason"] == "PNP_SERVICE_NOT_ELIGIBLE", (
        f"Expected PNP_SERVICE_NOT_ELIGIBLE, got {screened_c['screening_failure_reason']}"
    )
    assert screened_d["eligibility_status"] == "ELIGIBLE", (
        f"Expected ELIGIBLE, got {screened_d['eligibility_status']}"
    )
    assert screened_d["screening_failure_reason"] is None, (
        f"Expected a null reason on the eligible branch, got {screened_d['screening_failure_reason']}"
    )
    assert screened_e["eligibility_status"] == "ELIGIBLE", (
        "A LEASED facility of a LOCAL_GOVERNMENT applicant never reaches the nonprofit rules, "
        f"got {screened_e['eligibility_status']}"
    )
    assert screened_e["screening_failure_reason"] is None, (
        f"Expected a null reason, got {screened_e['screening_failure_reason']}"
    )


# ---------------------------------------------------------------------------
# Procurement compliance: threshold comparisons are boundary exact
# ---------------------------------------------------------------------------
def test_procurement_review_threshold_comparisons_are_boundary_exact(api):
    """PRD §3.4: "A `contract_type` of `COST_PLUS_PERCENTAGE_OF_COST` is
    categorically forbidden: `NONCOMPLIANT` with reason
    `PROHIBITED_CONTRACT_TYPE`."
    PRD §3.4: "Otherwise, a `TIME_AND_MATERIALS` award whose
    `award_amount_cents` is **strictly greater** than the small-purchase ceiling
    of 2,500,000 cents — twenty-five thousand dollars — is `NONCOMPLIANT` with
    reason `TIME_AND_MATERIALS_CEILING_EXCEEDED`."
    PRD §3.4: "An award of exactly twenty-five thousand dollars passes this
    rule."
    PRD §3.4: "Otherwise, if `award_amount_cents` is **at or above** the
    simplified acquisition threshold of 25,000,000 cents — two hundred fifty
    thousand dollars — two competition rules apply in their own order."
    PRD §3.4: "A `NONCOMPETITIVE` award whose
    `sole_source_justification_on_file` is false is `NONCOMPLIANT` with reason
    `SOLE_SOURCE_UNJUSTIFIED`."
    PRD §3.4: "Otherwise, a `SEALED_BID` or `COMPETITIVE_PROPOSAL` award that
    either was not `advertised` or received fewer than two responsive bids is
    `NONCOMPLIANT` with reason `INADEQUATE_COMPETITION`."
    PRD §3.4: "Otherwise, if `award_amount_cents` is **at or above** the
    small-purchase ceiling of twenty-five thousand dollars and
    `debarment_check_completed` is false, the contract is `NONCOMPLIANT` with
    reason `DEBARMENT_CHECK_MISSING`."
    PRD §3.4: "Otherwise the contract is `COMPLIANT` and `noncompliance_reason`
    is null."
    PRD §3.4: "Either outcome increments the contract's `version` by 1."

    Design: Corner/calculations/procurement_review_threshold_comparisons_are_boundary_exact
    """
    set_clock("2026-07-01T00:00:00Z")
    disaster = create_disaster(declaration_number="DR-4958")
    applicant = create_applicant(
        disaster["id"],
        name="City of Harborview",
        applicant_type="LOCAL_GOVERNMENT",
        population_served=120_000,
    )

    def contract(**fields):
        payload = {
            "vendor_name": "Harbor Civil Works LLC",
            "awarded_at": "2026-06-15T00:00:00Z",
            "advertised": False,
            "bids_received": 0,
            "sole_source_justification_on_file": False,
            "debarment_check_completed": False,
        }
        payload.update(fields)
        return create_contract(applicant["id"], **payload)

    c1 = contract(
        vendor_name="Percent Plus LLC",
        contract_type="COST_PLUS_PERCENTAGE_OF_COST",
        award_amount_cents=1_000_000,
        debarment_check_completed=True,
    )
    c2 = contract(
        vendor_name="Hourly Haulers",
        contract_type="TIME_AND_MATERIALS",
        award_amount_cents=2_500_001,
        debarment_check_completed=True,
    )
    c3 = contract(
        vendor_name="Hourly Haulers",
        contract_type="TIME_AND_MATERIALS",
        award_amount_cents=2_500_000,
        debarment_check_completed=True,
    )
    c4 = contract(
        vendor_name="Bayline Builders",
        contract_type="SEALED_BID",
        award_amount_cents=25_000_000,
        advertised=True,
        bids_received=1,
        debarment_check_completed=True,
    )
    c5 = contract(
        vendor_name="Bayline Builders",
        contract_type="SEALED_BID",
        award_amount_cents=24_999_999,
        advertised=False,
        bids_received=1,
        debarment_check_completed=True,
    )
    c6 = contract(
        vendor_name="Sole Source Systems",
        contract_type="NONCOMPETITIVE",
        award_amount_cents=25_000_000,
        sole_source_justification_on_file=False,
        debarment_check_completed=True,
    )
    c7 = contract(
        vendor_name="Quick Supply Co",
        contract_type="SMALL_PURCHASE",
        award_amount_cents=2_500_000,
        debarment_check_completed=False,
    )
    c8 = contract(
        vendor_name="Quick Supply Co",
        contract_type="SMALL_PURCHASE",
        award_amount_cents=2_499_999,
        debarment_check_completed=False,
    )

    reviewed = {}
    for label, row in (
        ("c1", c1), ("c2", c2), ("c3", c3), ("c4", c4),
        ("c5", c5), ("c6", c6), ("c7", c7), ("c8", c8),
    ):
        reviewed[label] = validate_success(
            api.review_procurement(row["id"], make_specialist_headers())
        )

    expected = {
        "c1": ("NONCOMPLIANT", "PROHIBITED_CONTRACT_TYPE"),
        "c2": ("NONCOMPLIANT", "TIME_AND_MATERIALS_CEILING_EXCEEDED"),
        "c3": ("COMPLIANT", None),
        "c4": ("NONCOMPLIANT", "INADEQUATE_COMPETITION"),
        "c5": ("COMPLIANT", None),
        "c6": ("NONCOMPLIANT", "SOLE_SOURCE_UNJUSTIFIED"),
        "c7": ("NONCOMPLIANT", "DEBARMENT_CHECK_MISSING"),
        "c8": ("COMPLIANT", None),
    }
    for label, (status, reason) in expected.items():
        row = reviewed[label]
        assert row["procurement_status"] == status, (
            f"Expected {label} procurement_status {status}, got {row['procurement_status']}"
        )
        assert row["noncompliance_reason"] == reason, (
            f"Expected {label} noncompliance_reason {reason}, got {row['noncompliance_reason']}"
        )
        assert row["version"] == 2, (
            f"Expected {label} version 2 after review, got {row['version']}"
        )


# ---------------------------------------------------------------------------
# Force account equipment: the applied rate is the lesser of the two rates
# ---------------------------------------------------------------------------
def test_equipment_rate_is_the_lesser_of_published_and_schedule(api):
    """PRD §3.5: "A **force account equipment** line applies the lesser-of rule:
    the applied rate is the smaller of the resource's
    `published_hourly_rate_cents` and its `schedule_hourly_rate_cents`, and the
    computed cost is `equipment_hours` multiplied by that applied rate, rounded
    half up to whole cents."
    PRD §3.5: "When the applicant's published rate is strictly greater than the
    state schedule rate — that is, when the lesser-of rule actually bit — the
    reduction reason is `LESSER_OF_RATE_APPLIED`; otherwise it is
    `CLAIM_EXCEEDS_COMPUTED_COST`."
    PRD §3.5: "The `review_status` is then `ALLOWED` when `eligible_cents`
    equals `claimed_cents`, `DISALLOWED` when `eligible_cents` is 0, and
    `PARTIALLY_ALLOWED` in between; the equality test comes first, so a line
    claiming nothing and computing nothing lands in `ALLOWED`."
    PRD §3.5: "`disallowance_reason` is null on an `ALLOWED` outcome and
    otherwise carries the reduction reason pinned by the branch."

    Design: Corner/calculations/equipment_rate_is_the_lesser_of_published_and_schedule
    """
    set_clock("2026-07-01T00:00:00Z")
    disaster = create_disaster(declaration_number="DR-4959")
    applicant = create_applicant(
        disaster["id"],
        name="City of Harborview",
        applicant_type="LOCAL_GOVERNMENT",
        population_served=120_000,
    )
    determine_eligibility(
        applicant["id"], "ELIGIBLE", "Local government inside the declared area"
    )
    facility = create_facility(
        applicant["id"],
        name="Riverside Pump Station",
        facility_type="WATER_CONTROL",
        ownership="PUBLIC",
    )
    screen_facility(facility["id"])
    project = create_project(
        applicant["id"],
        facility["id"],
        category="C",
        title="Debris channel clearing",
        scope_of_work="Clear the outfall channel with owned equipment",
        estimated_repair_cost_cents=200_000,
    )
    resource_x = create_equipment_resource(
        applicant["id"],
        label="Excavator 320",
        equipment_code="8015",
        published_hourly_rate_cents=4_000,
        schedule_hourly_rate_cents=3_400,
    )
    resource_y = create_equipment_resource(
        applicant["id"],
        label="Dump Truck 12yd",
        equipment_code="8801",
        published_hourly_rate_cents=3_000,
        schedule_hourly_rate_cents=3_400,
    )
    line_x = create_cost_line_item(
        project["id"],
        applicant["id"],
        cost_type="FORCE_ACCOUNT_EQUIPMENT",
        force_account_resource_id=resource_x["id"],
        claimed_cents=40_000,
        equipment_hours=10,
        work_start_at="2026-06-12T08:00:00Z",
        work_end_at="2026-06-12T18:00:00Z",
    )
    line_y = create_cost_line_item(
        project["id"],
        applicant["id"],
        cost_type="FORCE_ACCOUNT_EQUIPMENT",
        force_account_resource_id=resource_y["id"],
        claimed_cents=30_000,
        equipment_hours=10,
        work_start_at="2026-06-12T08:00:00Z",
        work_end_at="2026-06-12T18:00:00Z",
    )

    reviewed_x = validate_success(
        api.review_cost_line_item(line_x["id"], make_specialist_headers())
    )
    reviewed_y = validate_success(
        api.review_cost_line_item(line_y["id"], make_specialist_headers())
    )

    assert reviewed_x["eligible_cents"] == 34_000, (
        f"Expected 34000 cents on the lesser schedule rate, got {reviewed_x['eligible_cents']}"
    )
    assert reviewed_x["review_status"] == "PARTIALLY_ALLOWED", (
        f"Expected PARTIALLY_ALLOWED, got {reviewed_x['review_status']}"
    )
    assert reviewed_x["disallowance_reason"] == "LESSER_OF_RATE_APPLIED", (
        f"Expected LESSER_OF_RATE_APPLIED, got {reviewed_x['disallowance_reason']}"
    )
    assert reviewed_y["eligible_cents"] == 30_000, (
        f"Expected 30000 cents on the lesser published rate, got {reviewed_y['eligible_cents']}"
    )
    assert reviewed_y["review_status"] == "ALLOWED", (
        f"Expected ALLOWED, got {reviewed_y['review_status']}"
    )
    assert reviewed_y["disallowance_reason"] is None, (
        f"Expected a null reason on ALLOWED, got {reviewed_y['disallowance_reason']}"
    )
    assert get_force_account_resource(resource_x["id"])["charged_hours_total"] == 10, (
        "Expected charged_hours_total 10 on the excavator after review"
    )
    assert get_force_account_resource(resource_y["id"])["charged_hours_total"] == 10, (
        "Expected charged_hours_total 10 on the dump truck after review"
    )


# ---------------------------------------------------------------------------
# Contract lines: the award ceiling is consumed in created_at order
# ---------------------------------------------------------------------------
def test_contract_award_ceiling_consumed_in_created_at_order(api):
    """PRD §3.5: "Otherwise the system totals the `eligible_cents` of the
    contract's *other* lines whose `review_status` is `ALLOWED` or
    `PARTIALLY_ALLOWED` **and whose `created_at` is strictly earlier than this
    line's `created_at`** — creation order, never identifier order, is what
    consumes the ceiling."
    PRD §3.5: "The remaining headroom is the contract's `award_amount_cents`
    less that already-allowed total, floored at 0, and the computed cost is the
    lesser of the line's `claimed_cents` and that headroom."
    PRD §3.5: "When the headroom is smaller than the claim the reduction reason
    is `CONTRACT_AWARD_CEILING_REACHED`; otherwise it is
    `CLAIM_EXCEEDS_COMPUTED_COST`."
    PRD §3.4: "A new contract sits in `procurement_status` `PENDING_REVIEW` with
    `noncompliance_reason` null and `allowed_cost_total_cents` 0, the last of
    which accumulates the `eligible_cents` of every cost line item on the
    contract whose `review_status` is `ALLOWED` or `PARTIALLY_ALLOWED`."

    Design: Corner/calculations/contract_award_ceiling_consumed_in_created_at_order
    """
    set_clock("2026-07-01T00:00:00Z")
    disaster = create_disaster(declaration_number="DR-4960")
    applicant = create_applicant(
        disaster["id"],
        name="City of Harborview",
        applicant_type="LOCAL_GOVERNMENT",
        population_served=120_000,
    )
    determine_eligibility(
        applicant["id"], "ELIGIBLE", "Local government inside the declared area"
    )
    facility = create_facility(
        applicant["id"],
        name="Riverside Pump Station",
        facility_type="WATER_CONTROL",
        ownership="PUBLIC",
    )
    screen_facility(facility["id"])
    project = create_project(
        applicant["id"],
        facility["id"],
        category="C",
        title="Contracted intake repair",
        scope_of_work="Contractor rebuilds the intake structure",
        estimated_repair_cost_cents=3_300_000,
    )
    contract = create_contract(
        applicant["id"],
        vendor_name="Bayline Contractors",
        contract_type="SMALL_PURCHASE",
        award_amount_cents=2_500_000,
        awarded_at="2026-06-11T00:00:00Z",
        advertised=False,
        bids_received=0,
        debarment_check_completed=True,
    )
    contract = review_procurement(contract["id"])
    assert contract["procurement_status"] == "COMPLIANT", (
        f"Setup expected a COMPLIANT contract, got {contract['procurement_status']}"
    )

    # The lines are created one after another, each under a distinct logical
    # clock instant, so their creation order is unambiguous.
    line_1 = create_cost_line_item(
        project["id"],
        applicant["id"],
        cost_type="CONTRACT",
        contract_id=contract["id"],
        claimed_cents=2_000_000,
        work_start_at="2026-06-12T08:00:00Z",
        work_end_at="2026-06-12T17:00:00Z",
    )
    set_clock("2026-07-02T00:00:00Z")
    line_2 = create_cost_line_item(
        project["id"],
        applicant["id"],
        cost_type="CONTRACT",
        contract_id=contract["id"],
        claimed_cents=1_000_000,
        work_start_at="2026-06-13T08:00:00Z",
        work_end_at="2026-06-13T17:00:00Z",
    )
    set_clock("2026-07-03T00:00:00Z")
    line_3 = create_cost_line_item(
        project["id"],
        applicant["id"],
        cost_type="CONTRACT",
        contract_id=contract["id"],
        claimed_cents=300_000,
        work_start_at="2026-06-14T08:00:00Z",
        work_end_at="2026-06-14T17:00:00Z",
    )

    reviewed_1 = validate_success(
        api.review_cost_line_item(line_1["id"], make_specialist_headers())
    )
    reviewed_2 = validate_success(
        api.review_cost_line_item(line_2["id"], make_specialist_headers())
    )
    reviewed_3 = validate_success(
        api.review_cost_line_item(line_3["id"], make_specialist_headers())
    )

    assert reviewed_1["eligible_cents"] == 2_000_000, (
        f"Expected 2000000 on the first line, got {reviewed_1['eligible_cents']}"
    )
    assert reviewed_1["review_status"] == "ALLOWED", (
        f"Expected ALLOWED, got {reviewed_1['review_status']}"
    )
    assert reviewed_1["disallowance_reason"] is None, (
        f"Expected a null reason on ALLOWED, got {reviewed_1['disallowance_reason']}"
    )
    assert reviewed_2["eligible_cents"] == 500_000, (
        f"Expected 500000 on the headroom left by the first line, got {reviewed_2['eligible_cents']}"
    )
    assert reviewed_2["review_status"] == "PARTIALLY_ALLOWED", (
        f"Expected PARTIALLY_ALLOWED, got {reviewed_2['review_status']}"
    )
    assert reviewed_2["disallowance_reason"] == "CONTRACT_AWARD_CEILING_REACHED", (
        f"Expected CONTRACT_AWARD_CEILING_REACHED, got {reviewed_2['disallowance_reason']}"
    )
    assert reviewed_3["eligible_cents"] == 0, (
        f"Expected 0 on an exhausted ceiling, got {reviewed_3['eligible_cents']}"
    )
    assert reviewed_3["review_status"] == "DISALLOWED", (
        f"Expected DISALLOWED, got {reviewed_3['review_status']}"
    )
    assert reviewed_3["disallowance_reason"] == "CONTRACT_AWARD_CEILING_REACHED", (
        f"Expected CONTRACT_AWARD_CEILING_REACHED, got {reviewed_3['disallowance_reason']}"
    )
    assert get_contract(contract["id"])["allowed_cost_total_cents"] == 2_500_000, (
        "Expected allowed_cost_total_cents 2500000 after all three reviews"
    )


# ---------------------------------------------------------------------------
# The per-capita indicator crosses at exactly 189 cents and floors the ratio
# ---------------------------------------------------------------------------
def test_per_capita_indicator_crosses_at_exactly_189_cents(api):
    """PRD §3.2: "`total_validated_loss_cents` becomes the sum of
    `validated_loss_cents` across that set, which is 0 when the set is empty;
    because it is a plain sum, no ordering or tie-break matters."
    PRD §3.2: "`per_capita_impact_cents` becomes `total_validated_loss_cents`
    divided by the declaration's `population`, truncated downward to a whole
    number of cents."
    PRD §3.2: "`indicator_met` becomes true when `per_capita_impact_cents` is at
    least the statewide per-capita indicator of 189 cents — one dollar and
    eighty-nine cents of validated loss per resident — and false otherwise."
    PRD §3.2: "`REPORTED → VALIDATED` requires a supplied `validated_loss_cents`
    of at least 0, writes it onto the site, sets `validation_status` to
    `VALIDATED`, and then refreshes the declaration-level indicator,
    incrementing both the site's `version` and the declaration's `version` by
    1."

    Design: Corner/calculations/per_capita_indicator_crosses_at_exactly_189_cents
    """
    set_clock("2026-07-01T00:00:00Z")
    disaster = create_disaster(declaration_number="DR-4961", population=10_000)
    applicant = create_applicant(
        disaster["id"],
        name="City of Harborview",
        applicant_type="LOCAL_GOVERNMENT",
        population_served=10_000,
    )
    facility = create_facility(
        applicant["id"],
        name="Riverside Pump Station",
        facility_type="WATER_CONTROL",
        ownership="PUBLIC",
    )
    site_1 = create_damage_site(
        facility["id"],
        applicant["id"],
        category="C",
        reported_loss_cents=1_880_000,
        damage_observed_at="2026-06-12T09:00:00Z",
    )
    site_2 = create_damage_site(
        facility["id"],
        applicant["id"],
        category="C",
        reported_loss_cents=10_000,
        damage_observed_at="2026-06-13T09:00:00Z",
    )
    site_3 = create_damage_site(
        facility["id"],
        applicant["id"],
        category="C",
        reported_loss_cents=5_000,
        damage_observed_at="2026-06-14T09:00:00Z",
    )

    validate_success(
        api.validate_damage_site(
            site_1["id"],
            {"decision": "VALIDATE", "validated_loss_cents": 1_880_000},
            make_specialist_headers(),
        )
    )
    after_first = get_disaster(disaster["id"])
    assert after_first["total_validated_loss_cents"] == 1_880_000, (
        f"Expected 1880000, got {after_first['total_validated_loss_cents']}"
    )
    assert after_first["per_capita_impact_cents"] == 188, (
        f"Expected 188 cents per capita, got {after_first['per_capita_impact_cents']}"
    )
    assert after_first["indicator_met"] is False, (
        "188 cents is below the 189-cent indicator, so indicator_met must be false"
    )

    validate_success(
        api.validate_damage_site(
            site_2["id"],
            {"decision": "VALIDATE", "validated_loss_cents": 10_000},
            make_specialist_headers(),
        )
    )
    after_second = get_disaster(disaster["id"])
    assert after_second["total_validated_loss_cents"] == 1_890_000, (
        f"Expected 1890000, got {after_second['total_validated_loss_cents']}"
    )
    assert after_second["per_capita_impact_cents"] == 189, (
        f"Expected 189 cents per capita, got {after_second['per_capita_impact_cents']}"
    )
    assert after_second["indicator_met"] is True, (
        "Exactly 189 cents meets the indicator, so indicator_met must be true"
    )

    validate_success(
        api.validate_damage_site(
            site_3["id"],
            {"decision": "VALIDATE", "validated_loss_cents": 5_000},
            make_specialist_headers(),
        )
    )
    after_third = get_disaster(disaster["id"])
    assert after_third["total_validated_loss_cents"] == 1_895_000, (
        f"Expected 1895000, got {after_third['total_validated_loss_cents']}"
    )
    assert after_third["per_capita_impact_cents"] == 189, (
        "189.5 cents per capita must truncate downward to 189, got "
        f"{after_third['per_capita_impact_cents']}"
    )
    assert after_third["indicator_met"] is True, (
        "Expected indicator_met to stay true"
    )
    assert after_third["version"] == 4, (
        f"Expected declaration version 4 after three validations, got {after_third['version']}"
    )


# ---------------------------------------------------------------------------
# Insurance waterfall: category order, then created_at, then the leftovers
# ---------------------------------------------------------------------------
def test_insurance_settlement_waterfall_fills_by_category_then_created_at(api):
    """PRD §3.6: "Candidates are visited in ascending work `category` order — `A`
    before `B` before `C` before `D` before `E` before `F` before `G` — and
    within a category in ascending `created_at` order; the row identifier is
    never an ordering key."
    PRD §3.6: "For each candidate in turn, the room remaining on that project is
    its `repair_eligible_cents` less whatever `settlement_allocated_cents` it has
    already absorbed, floored at 0; the amount taken is the lesser of the
    available balance and that room; the project's `settlement_allocated_cents`
    rises by the amount taken; the project's `insurance_reduction_cents` is reset
    to the greater of its `anticipated_insurance_cents` and its new
    `settlement_allocated_cents`; and the available balance falls by the amount
    taken."
    PRD §3.6: "When the walk is finished, the policy's `allocated_cents` is the
    settlement amount less whatever balance remains, and its `unallocated_cents`
    is that remaining balance — proceeds with nowhere to go simply stay on the
    policy."
    PRD §3.6: "The shortfall is the project's `federal_share_obligated_cents`
    less its `deobligated_cents` less that recomputed share; when the shortfall
    is positive, the system immediately creates a deobligation determination on
    that project with `reason` `INSURANCE_DOB`, an `amount_cents` equal to the
    shortfall, a `status` of `PROPOSED`, and `determined_by_user_id` set to the
    acting officer's `X-User-ID`."
    PRD §3.6: "Candidates in `UNDER_REVIEW`, `RFI_ISSUED` or `VALIDATED` absorb
    proceeds and have their `insurance_reduction_cents` raised, but generate no
    determination — there is nothing obligated yet to reduce."

    Design: Corner/calculations/insurance_settlement_waterfall_fills_by_category_then_created_at
    """
    set_clock("2026-07-01T00:00:00Z")
    disaster = create_disaster(declaration_number="DR-4962")
    applicant = create_applicant(
        disaster["id"],
        name="City of Harborview",
        applicant_type="LOCAL_GOVERNMENT",
        population_served=120_000,
    )
    determine_eligibility(
        applicant["id"], "ELIGIBLE", "Local government inside the declared area"
    )
    facility = create_facility(
        applicant["id"],
        name="Riverside Pump Station",
        facility_type="WATER_CONTROL",
        ownership="PUBLIC",
    )
    screen_facility(facility["id"])

    # The category-B project is created first and obligated; the category-C
    # project follows and stops at VALIDATED.
    project_b = create_project(
        applicant["id"],
        facility["id"],
        category="B",
        title="Emergency protective measures",
        scope_of_work="Sandbagging and emergency pumping",
        estimated_repair_cost_cents=4_000_000,
    )
    submit_project(project_b["id"], applicant["id"])
    line_b = create_cost_line_item(
        project_b["id"],
        applicant["id"],
        cost_type="MATERIALS",
        claimed_cents=4_000_000,
        work_start_at="2026-06-12T08:00:00Z",
        work_end_at="2026-06-12T17:00:00Z",
    )
    review_cost_line_item(line_b["id"])
    cost_review(project_b["id"], "VALIDATE")
    project_b = obligate_project(project_b["id"])
    assert project_b["federal_share_obligated_cents"] == 3_000_000, (
        f"Setup expected 3000000 obligated, got {project_b['federal_share_obligated_cents']}"
    )

    project_c = create_project(
        applicant["id"],
        facility["id"],
        category="C",
        title="Pump house roof repair",
        scope_of_work="Replace the pump house roof deck",
        estimated_repair_cost_cents=1_000_000,
    )
    submit_project(project_c["id"], applicant["id"])
    line_c = create_cost_line_item(
        project_c["id"],
        applicant["id"],
        cost_type="MATERIALS",
        claimed_cents=1_000_000,
        work_start_at="2026-06-13T08:00:00Z",
        work_end_at="2026-06-13T17:00:00Z",
    )
    review_cost_line_item(line_c["id"])
    cost_review(project_c["id"], "VALIDATE")

    policy = create_insurance_policy(
        facility["id"],
        applicant["id"],
        insurer_name="Gulf Mutual",
        policy_type="PROPERTY",
        coverage_limit_cents=6_000_000,
        deductible_cents=0,
        effective_start_at="2026-01-01T00:00:00Z",
        effective_end_at="2026-12-31T00:00:00Z",
    )

    settled = validate_success(
        api.record_settlement(
            policy["id"],
            {"settlement_amount_cents": 5_500_000, "settled_at": "2026-06-30T00:00:00Z"},
            make_grants_officer_headers(SECOND_GRANTS_OFFICER_USER_ID),
        )
    )

    assert settled["settlement_amount_cents"] == 5_500_000, (
        f"Expected 5500000 recorded, got {settled['settlement_amount_cents']}"
    )
    assert settled["allocated_cents"] == 5_000_000, (
        f"Expected 5000000 allocated across the two projects, got {settled['allocated_cents']}"
    )
    assert settled["unallocated_cents"] == 500_000, (
        f"Expected 500000 left on the policy, got {settled['unallocated_cents']}"
    )

    after_b = get_project(project_b["id"])
    after_c = get_project(project_c["id"])
    assert after_b["settlement_allocated_cents"] == 4_000_000, (
        "The category-B project fills to its room first, expected 4000000, got "
        f"{after_b['settlement_allocated_cents']}"
    )
    assert after_b["insurance_reduction_cents"] == 4_000_000, (
        f"Expected insurance_reduction_cents 4000000, got {after_b['insurance_reduction_cents']}"
    )
    assert after_c["settlement_allocated_cents"] == 1_000_000, (
        f"Expected 1000000 on the category-C project, got {after_c['settlement_allocated_cents']}"
    )
    assert after_c["insurance_reduction_cents"] == 1_000_000, (
        f"Expected insurance_reduction_cents 1000000, got {after_c['insurance_reduction_cents']}"
    )
    assert after_b["federal_share_obligated_cents"] == 3_000_000, (
        "The obligated share is never rewritten by the waterfall, got "
        f"{after_b['federal_share_obligated_cents']}"
    )
    assert after_b["pending_deobligation_cents"] == 3_000_000, (
        f"Expected pending_deobligation_cents 3000000, got {after_b['pending_deobligation_cents']}"
    )

    determinations_b = _deobligations_for_project(api, project_b["id"])
    assert len(determinations_b) == 1, (
        f"Expected exactly one determination on the obligated project, got {len(determinations_b)}"
    )
    determination = determinations_b[0]
    assert determination["reason"] == "INSURANCE_DOB", (
        f"Expected reason INSURANCE_DOB, got {determination['reason']}"
    )
    assert determination["amount_cents"] == 3_000_000, (
        f"Expected amount_cents 3000000, got {determination['amount_cents']}"
    )
    assert determination["status"] == "PROPOSED", (
        f"Expected status PROPOSED, got {determination['status']}"
    )
    assert determination["determined_by_user_id"] == SECOND_GRANTS_OFFICER_USER_ID, (
        "Expected the acting officer stamped on the determination, got "
        f"{determination['determined_by_user_id']}"
    )
    assert _deobligations_for_project(api, project_c["id"]) == [], (
        "A VALIDATED project absorbs proceeds but must not spawn a determination"
    )

    after_applicant = get_applicant(applicant["id"])
    assert after_applicant["pending_deobligation_cents"] == 3_000_000, (
        f"Expected applicant pending 3000000, got {after_applicant['pending_deobligation_cents']}"
    )
    assert after_applicant["drawdown_status"] == "SUSPENDED", (
        f"Expected SUSPENDED, got {after_applicant['drawdown_status']}"
    )
    assert get_disaster(disaster["id"])["suspended_applicant_count"] == 1, (
        "Expected suspended_applicant_count 1 on the declaration"
    )
    assert get_insurance_policy(policy["id"])["unallocated_cents"] == 500_000, (
        "Expected the leftover proceeds to stay on the policy"
    )


# ---------------------------------------------------------------------------
# Quarter derivation, the grace window and the inclusive due boundary
# ---------------------------------------------------------------------------
def test_quarter_derivation_grace_window_and_inclusive_due_boundary(api):
    """PRD §3.8: "`period_start_at` is the first instant of that quarter of that
    year in UTC; `period_end_at` is the first instant of the following quarter,
    and because the period is half-open that end instant belongs to the next
    quarter rather than this one; and `due_at` is `period_end_at` plus the
    reporting grace period of thirty days."
    PRD §3.8: "When an applicant files a report directly, its status is decided
    on the spot: `SUBMITTED` when the logical clock is at or before `due_at`,
    and `LATE` when the clock is past `due_at`, with `submitted_at` stamped from
    the clock either way."
    PRD §2.5: "Because reporting periods are half-open, the quarter `2026-Q2`
    spans `2026-04-01T00:00:00Z` up to but not including `2026-07-01T00:00:00Z`,
    and `2026-Q3` starts exactly where `2026-Q2` ended; the two are adjacent and
    never overlap."
    PRD §2.5: "Deadline comparisons are inclusive: a clock instant exactly equal
    to `due_at` is on time, and a clock instant exactly equal to
    `appeal_deadline_at` is inside the appeal window."

    Design: Corner/calculations/quarter_derivation_grace_window_and_inclusive_due_boundary
    """
    set_clock("2026-07-31T00:00:00Z")
    disaster = create_disaster(declaration_number="DR-4963")
    applicant_a = create_applicant(
        disaster["id"],
        name="City of Harborview",
        applicant_type="LOCAL_GOVERNMENT",
        population_served=120_000,
    )
    applicant_b = create_applicant(
        disaster["id"],
        name="Coastal Bend Tribe",
        applicant_type="TRIBE",
        population_served=9_000,
    )

    report_a2 = validate_success(
        api.create_progress_report(
            {
                "applicant_id": applicant_a["id"],
                "quarter_label": "2026-Q2",
                "expenditures_to_date_cents": 250_000,
                "pct_complete": 40,
            },
            make_applicant_agent_headers(applicant_a["id"]),
        ),
        201,
    )
    set_clock("2026-08-01T00:00:00Z")
    report_b2 = validate_success(
        api.create_progress_report(
            {
                "applicant_id": applicant_b["id"],
                "quarter_label": "2026-Q2",
                "expenditures_to_date_cents": 100_000,
                "pct_complete": 20,
            },
            make_applicant_agent_headers(applicant_b["id"]),
        ),
        201,
    )
    report_a3 = validate_success(
        api.create_progress_report(
            {
                "applicant_id": applicant_a["id"],
                "quarter_label": "2026-Q3",
                "expenditures_to_date_cents": 400_000,
                "pct_complete": 65,
            },
            make_applicant_agent_headers(applicant_a["id"]),
        ),
        201,
    )

    assert report_a2["period_start_at"].startswith("2026-04-01T00:00:00"), (
        f"Expected 2026-Q2 to start at 2026-04-01T00:00:00Z, got {report_a2['period_start_at']}"
    )
    assert report_a2["period_end_at"].startswith("2026-07-01T00:00:00"), (
        f"Expected 2026-Q2 to end at 2026-07-01T00:00:00Z, got {report_a2['period_end_at']}"
    )
    assert report_a2["due_at"].startswith("2026-07-31T00:00:00"), (
        f"Expected due_at thirty days after the period end, got {report_a2['due_at']}"
    )
    assert report_a2["status"] == "SUBMITTED", (
        f"A clock exactly at due_at is on time, expected SUBMITTED, got {report_a2['status']}"
    )
    assert report_a2["submitted_at"].startswith("2026-07-31T00:00:00"), (
        f"Expected submitted_at stamped from the clock, got {report_a2['submitted_at']}"
    )

    assert report_b2["period_start_at"].startswith("2026-04-01T00:00:00"), (
        f"Expected the same derived window for 2026-Q2, got {report_b2['period_start_at']}"
    )
    assert report_b2["period_end_at"].startswith("2026-07-01T00:00:00"), (
        f"Expected the same derived window for 2026-Q2, got {report_b2['period_end_at']}"
    )
    assert report_b2["due_at"].startswith("2026-07-31T00:00:00"), (
        f"Expected the same due_at for 2026-Q2, got {report_b2['due_at']}"
    )
    assert report_b2["status"] == "LATE", (
        f"A clock one day past due_at is LATE, got {report_b2['status']}"
    )
    assert report_b2["submitted_at"].startswith("2026-08-01T00:00:00"), (
        f"Expected submitted_at stamped from the clock, got {report_b2['submitted_at']}"
    )

    assert report_a3["period_start_at"].startswith("2026-07-01T00:00:00"), (
        "2026-Q3 must start exactly where 2026-Q2 ended, got "
        f"{report_a3['period_start_at']}"
    )
    assert report_a3["period_end_at"].startswith("2026-10-01T00:00:00"), (
        f"Expected 2026-Q3 to end at 2026-10-01T00:00:00Z, got {report_a3['period_end_at']}"
    )
    assert report_a3["due_at"].startswith("2026-10-31T00:00:00"), (
        f"Expected due_at 2026-10-31T00:00:00Z, got {report_a3['due_at']}"
    )
    assert report_a3["status"] == "SUBMITTED", (
        f"Expected SUBMITTED well before due_at, got {report_a3['status']}"
    )

    after_a = get_applicant(applicant_a["id"])
    assert after_a["delinquent_report_count"] == 0, (
        f"Expected delinquent_report_count 0, got {after_a['delinquent_report_count']}"
    )
    assert after_a["drawdown_status"] == "ACTIVE", (
        f"Expected ACTIVE, got {after_a['drawdown_status']}"
    )


# ---------------------------------------------------------------------------
# Closeout: a SMALL project is never reconciled against actuals
# ---------------------------------------------------------------------------
def test_closeout_small_project_is_never_reconciled_against_actuals(api):
    """PRD §3.9: "A **`SMALL`** project is funded on its estimate and is never
    reconciled against actuals: `federal_share_final_cents` is set equal to
    `federal_share_obligated_cents`, `closeout_variance_cents` is set to 0, and
    **no** determination is created no matter how far the documented actuals
    fell below the estimate."
    PRD §3.9: "`eligible_cost_final_cents` is therefore the documented repair
    basis less the actual settlement allocation, floored at 0, plus the frozen
    mitigation component."
    PRD §3.9: "Its insurance offset is the project's
    `settlement_allocated_cents`, that is, **actual proceeds only**;
    `anticipated_insurance_cents` is deliberately ignored here, which is the
    whole point of having two variants."

    Design: Corner/calculations/closeout_small_project_is_never_reconciled_against_actuals
    """
    set_clock("2026-07-01T00:00:00Z")
    disaster = create_disaster(declaration_number="DR-4964")
    applicant = create_applicant(
        disaster["id"],
        name="City of Harborview",
        applicant_type="LOCAL_GOVERNMENT",
        population_served=120_000,
    )
    determine_eligibility(
        applicant["id"], "ELIGIBLE", "Local government inside the declared area"
    )
    facility = create_facility(
        applicant["id"],
        name="Riverside Pump Station",
        facility_type="WATER_CONTROL",
        ownership="PUBLIC",
    )
    screen_facility(facility["id"])
    project = create_project(
        applicant["id"],
        facility["id"],
        category="C",
        title="Culvert replacement",
        scope_of_work="Replace two collapsed culverts",
        estimated_repair_cost_cents=1_500_000,
    )
    submit_project(project["id"], applicant["id"])
    line = create_cost_line_item(
        project["id"],
        applicant["id"],
        cost_type="MATERIALS",
        claimed_cents=1_500_000,
        work_start_at="2026-06-12T08:00:00Z",
        work_end_at="2026-06-12T17:00:00Z",
    )
    review_cost_line_item(line["id"])
    project = cost_review(project["id"], "VALIDATE")
    assert project["size_class"] == "SMALL", (
        f"Setup expected a SMALL project, got {project['size_class']}"
    )
    project = obligate_project(project["id"])
    assert project["federal_share_obligated_cents"] == 1_125_000, (
        f"Setup expected 1125000 obligated, got {project['federal_share_obligated_cents']}"
    )
    policy = create_insurance_policy(
        facility["id"],
        applicant["id"],
        insurer_name="Gulf Mutual",
        policy_type="PROPERTY",
        coverage_limit_cents=1_000_000,
        deductible_cents=0,
        effective_start_at="2026-01-01T00:00:00Z",
        effective_end_at="2026-12-31T00:00:00Z",
    )
    record_settlement(
        policy["id"], 400_000, "2026-06-30T00:00:00Z", SECOND_GRANTS_OFFICER_USER_ID
    )

    after_settlement = get_project(project["id"])
    assert after_settlement["settlement_allocated_cents"] == 400_000, (
        f"Expected 400000 allocated, got {after_settlement['settlement_allocated_cents']}"
    )
    assert after_settlement["insurance_reduction_cents"] == 400_000, (
        f"Expected insurance_reduction_cents 400000, got "
        f"{after_settlement['insurance_reduction_cents']}"
    )
    assert after_settlement["pending_deobligation_cents"] == 300_000, (
        "Expected the waterfall shortfall of 300000 proposed, got "
        f"{after_settlement['pending_deobligation_cents']}"
    )

    requested = validate_success(
        api.request_closeout(project["id"], make_applicant_agent_headers(applicant["id"]))
    )
    assert requested["eligible_cost_final_cents"] == 1_100_000, (
        f"Expected eligible_cost_final_cents 1100000, got {requested['eligible_cost_final_cents']}"
    )
    assert requested["status"] == "CLOSEOUT_REQUESTED", (
        f"Expected CLOSEOUT_REQUESTED, got {requested['status']}"
    )

    closed = validate_success(
        api.certify_closeout(
            project["id"],
            {"audit_finding": "Documented costs agree with the approved scope"},
            make_auditor_headers(),
        )
    )
    assert closed["status"] == "CLOSED", f"Expected CLOSED, got {closed['status']}"
    assert closed["federal_share_final_cents"] == 1_125_000, (
        "A SMALL project closes on its obligation, expected 1125000, got "
        f"{closed['federal_share_final_cents']}"
    )
    assert closed["closeout_variance_cents"] == 0, (
        f"Expected closeout_variance_cents 0, got {closed['closeout_variance_cents']}"
    )

    determinations = _deobligations_for_project(api, project["id"])
    assert len(determinations) == 1, (
        "Expected only the insurance determination on the project, got "
        f"{len(determinations)}"
    )
    assert all(row["reason"] != "CLOSEOUT_UNDERRUN" for row in determinations), (
        "A SMALL project must never produce a CLOSEOUT_UNDERRUN determination"
    )


# ---------------------------------------------------------------------------
# Closeout: a LARGE project's positive variance is recorded and nothing more
# ---------------------------------------------------------------------------
def test_closeout_large_project_positive_variance_is_recorded_only(api):
    """PRD §3.7: "If that reviewed set is empty — a project validated on its
    estimate alone, with no documented costs yet — `repair_eligible_cents` falls
    back to the project's `estimated_repair_cost_cents`; this fallback is the
    pinned behaviour, not an error condition."
    PRD §3.9: "A **`LARGE`** project is reconciled: the net final figure is
    `eligible_cost_final_cents` less `mitigation_approved_cents`, floored at 0;
    `federal_share_final_cents` is that net final figure multiplied by the
    declaration's `federal_cost_share_pct` and rounded half up to whole cents,
    **plus separately** `mitigation_approved_cents` multiplied by the same share
    and rounded half up to whole cents — the identical per-component rounding
    order used at obligation, so that an unchanged basis reconciles to exactly
    the obligated figure."
    PRD §3.9: "`closeout_variance_cents` is `federal_share_final_cents` less
    `federal_share_obligated_cents`."
    PRD §3.9: "A positive variance is recorded and nothing more: closeout never
    obligates additional money."

    Design: Corner/calculations/closeout_large_project_positive_variance_is_recorded_only
    """
    set_clock("2026-07-01T00:00:00Z")
    disaster = create_disaster(declaration_number="DR-4965")
    applicant = create_applicant(
        disaster["id"],
        name="City of Harborview",
        applicant_type="LOCAL_GOVERNMENT",
        population_served=120_000,
    )
    determine_eligibility(
        applicant["id"], "ELIGIBLE", "Local government inside the declared area"
    )
    facility = create_facility(
        applicant["id"],
        name="Riverside Pump Station",
        facility_type="WATER_CONTROL",
        ownership="PUBLIC",
    )
    screen_facility(facility["id"])
    project = create_project(
        applicant["id"],
        facility["id"],
        category="C",
        title="Pump station intake rebuild",
        scope_of_work="Rebuild intake structure and control panel",
        estimated_repair_cost_cents=5_000_000,
    )
    submit_project(project["id"], applicant["id"])

    reviewed = cost_review(project["id"], "VALIDATE")
    assert reviewed["repair_eligible_cents"] == 5_000_000, (
        "An empty reviewed set falls back to the estimate, expected 5000000, got "
        f"{reviewed['repair_eligible_cents']}"
    )
    assert reviewed["size_class"] == "LARGE", (
        f"Expected LARGE, got {reviewed['size_class']}"
    )

    obligated = obligate_project(project["id"])
    assert obligated["federal_share_obligated_cents"] == 3_750_000, (
        f"Expected 3750000 obligated, got {obligated['federal_share_obligated_cents']}"
    )

    line = create_cost_line_item(
        project["id"],
        applicant["id"],
        cost_type="MATERIALS",
        claimed_cents=5_200_000,
        work_start_at="2026-06-12T08:00:00Z",
        work_end_at="2026-06-12T17:00:00Z",
    )
    review_cost_line_item(line["id"])

    requested = validate_success(
        api.request_closeout(project["id"], make_applicant_agent_headers(applicant["id"]))
    )
    assert requested["eligible_cost_final_cents"] == 5_200_000, (
        f"Expected eligible_cost_final_cents 5200000, got {requested['eligible_cost_final_cents']}"
    )

    closed = validate_success(
        api.certify_closeout(
            project["id"],
            {"audit_finding": "Actual costs exceeded the approved estimate"},
            make_auditor_headers(),
        )
    )
    assert closed["federal_share_final_cents"] == 3_900_000, (
        f"Expected federal_share_final_cents 3900000, got {closed['federal_share_final_cents']}"
    )
    assert closed["closeout_variance_cents"] == 150_000, (
        f"Expected closeout_variance_cents 150000, got {closed['closeout_variance_cents']}"
    )
    assert closed["status"] == "CLOSED", f"Expected CLOSED, got {closed['status']}"
    assert closed["deobligated_cents"] == 0, (
        f"Expected deobligated_cents 0, got {closed['deobligated_cents']}"
    )
    assert _deobligations_for_project(api, project["id"]) == [], (
        "Closeout never obligates more money, so no determination may exist"
    )
    assert get_applicant(applicant["id"])["total_obligated_cents"] == 3_750_000, (
        "The positive variance is recorded, not funded, so the ledger stays at 3750000"
    )


# ---------------------------------------------------------------------------
# Closeout: a LARGE project's underrun spawns a CLOSEOUT_UNDERRUN determination
# ---------------------------------------------------------------------------
def test_closeout_large_project_underrun_creates_closeout_deobligation(api):
    """PRD §3.9: "A **`LARGE`** project is reconciled: the net final figure is
    `eligible_cost_final_cents` less `mitigation_approved_cents`, floored at 0;
    `federal_share_final_cents` is that net final figure multiplied by the
    declaration's `federal_cost_share_pct` and rounded half up to whole cents,
    **plus separately** `mitigation_approved_cents` multiplied by the same share
    and rounded half up to whole cents — the identical per-component rounding
    order used at obligation, so that an unchanged basis reconciles to exactly
    the obligated figure."
    PRD §3.9: "A negative variance is an underrun, and the system immediately
    creates a determination on the project with `reason` `CLOSEOUT_UNDERRUN`, an
    `amount_cents` equal to the magnitude of that negative variance, `status`
    `PROPOSED`, and `determined_by_user_id` set to the certifying auditor's
    `X-User-ID`."
    PRD §3.9: "Because that determination exists, the project's
    `pending_deobligation_cents` and the applicant's
    `pending_deobligation_cents` are recomputed; because the applicant's pending
    figure is now above 0, `drawdown_status` becomes `SUSPENDED` and the
    declaration's `suspended_applicant_count` is recomputed."

    Design: Corner/calculations/closeout_large_project_underrun_creates_closeout_deobligation
    """
    set_clock("2026-07-01T00:00:00Z")
    disaster = create_disaster(declaration_number="DR-4966")
    applicant = create_applicant(
        disaster["id"],
        name="City of Harborview",
        applicant_type="LOCAL_GOVERNMENT",
        population_served=120_000,
    )
    determine_eligibility(
        applicant["id"], "ELIGIBLE", "Local government inside the declared area"
    )
    facility = create_facility(
        applicant["id"],
        name="Riverside Pump Station",
        facility_type="WATER_CONTROL",
        ownership="PUBLIC",
    )
    screen_facility(facility["id"])
    project = create_project(
        applicant["id"],
        facility["id"],
        category="C",
        title="Levee segment reconstruction",
        scope_of_work="Reconstruct 400 metres of levee crown",
        estimated_repair_cost_cents=20_000_000,
    )
    submit_project(project["id"], applicant["id"])
    cost_review(project["id"], "VALIDATE")
    obligate_project(project["id"])
    line = create_cost_line_item(
        project["id"],
        applicant["id"],
        cost_type="MATERIALS",
        claimed_cents=16_000_000,
        work_start_at="2026-06-12T08:00:00Z",
        work_end_at="2026-06-12T17:00:00Z",
    )
    review_cost_line_item(line["id"])
    before = request_closeout(project["id"], applicant["id"])
    assert before["federal_share_obligated_cents"] == 15_000_000, (
        f"Setup expected 15000000 obligated, got {before['federal_share_obligated_cents']}"
    )
    assert before["eligible_cost_final_cents"] == 16_000_000, (
        f"Setup expected eligible_cost_final_cents 16000000, got "
        f"{before['eligible_cost_final_cents']}"
    )

    closed = validate_success(
        api.certify_closeout(
            project["id"],
            {"audit_finding": "Documented actuals fell short of the approved estimate"},
            make_auditor_headers(),
        )
    )

    assert closed["federal_share_final_cents"] == 12_000_000, (
        f"Expected federal_share_final_cents 12000000, got {closed['federal_share_final_cents']}"
    )
    assert closed["closeout_variance_cents"] == -3_000_000, (
        f"Expected closeout_variance_cents -3000000, got {closed['closeout_variance_cents']}"
    )
    assert closed["status"] == "CLOSED", f"Expected CLOSED, got {closed['status']}"
    assert closed["pending_deobligation_cents"] == 3_000_000, (
        f"Expected pending_deobligation_cents 3000000, got {closed['pending_deobligation_cents']}"
    )

    determinations = _deobligations_for_project(api, project["id"])
    assert len(determinations) == 1, (
        f"Expected exactly one determination, got {len(determinations)}"
    )
    determination = determinations[0]
    assert determination["reason"] == "CLOSEOUT_UNDERRUN", (
        f"Expected reason CLOSEOUT_UNDERRUN, got {determination['reason']}"
    )
    assert determination["amount_cents"] == 3_000_000, (
        f"Expected amount_cents 3000000, got {determination['amount_cents']}"
    )
    assert determination["status"] == "PROPOSED", (
        f"Expected status PROPOSED, got {determination['status']}"
    )
    assert determination["determined_by_user_id"] == AUDITOR_USER_ID, (
        "Expected the certifying auditor stamped on the determination, got "
        f"{determination['determined_by_user_id']}"
    )

    after_applicant = get_applicant(applicant["id"])
    assert after_applicant["pending_deobligation_cents"] == 3_000_000, (
        f"Expected applicant pending 3000000, got {after_applicant['pending_deobligation_cents']}"
    )
    assert after_applicant["drawdown_status"] == "SUSPENDED", (
        f"Expected SUSPENDED, got {after_applicant['drawdown_status']}"
    )
    assert after_applicant["total_obligated_cents"] == 15_000_000, (
        "A PROPOSED determination does not reduce the obligation, got "
        f"{after_applicant['total_obligated_cents']}"
    )
    assert get_disaster(disaster["id"])["suspended_applicant_count"] == 1, (
        "Expected suspended_applicant_count 1 on the declaration"
    )


# ---------------------------------------------------------------------------
# Cost review: the repair basis excludes DISALLOWED lines
# ---------------------------------------------------------------------------
def test_project_review_basis_excludes_disallowed_lines(api):
    """PRD §3.7: "The system totals the `eligible_cents` of every cost line item
    on the project whose `review_status` is `ALLOWED` or `PARTIALLY_ALLOWED`,
    and `repair_eligible_cents` becomes that total."
    PRD §3.7: "`DISALLOWED` lines contribute nothing, and no `SUBMITTED` line
    can exist at this point."
    PRD §3.7: "The order is: take `repair_eligible_cents` as step one fixed it;
    classify `size_class` from that repair basis **with mitigation excluded**;
    read the cap percentage from the class, which is 20 percent for `SMALL` and
    15 percent for `LARGE`; and set `mitigation_approved_cents` to the lesser of
    the project's `mitigation_requested_cents` and the repair basis multiplied by
    the cap percentage, truncated downward to whole cents."
    PRD §3.5: "When the resource's `employee_type` is `PERMANENT` **and** the
    project's `work_type` is `EMERGENCY`, the billable straight-time hours are
    forced to zero — a permanent employee's regular salary is not a disaster
    cost for emergency work, only the premium for working extra hours is — and
    the reduction reason is pinned to
    `STRAIGHT_TIME_NOT_ELIGIBLE_FOR_EMERGENCY_WORK`."

    Design: Corner/calculations/project_review_basis_excludes_disallowed_lines
    """
    set_clock("2026-07-01T00:00:00Z")
    disaster = create_disaster(declaration_number="DR-4967")
    applicant = create_applicant(
        disaster["id"],
        name="City of Harborview",
        applicant_type="LOCAL_GOVERNMENT",
        population_served=120_000,
    )
    determine_eligibility(
        applicant["id"], "ELIGIBLE", "Local government inside the declared area"
    )
    facility = create_facility(
        applicant["id"],
        name="Riverside Pump Station",
        facility_type="WATER_CONTROL",
        ownership="PUBLIC",
    )
    screen_facility(facility["id"])
    project = create_project(
        applicant["id"],
        facility["id"],
        category="A",
        title="Debris removal",
        scope_of_work="Remove storm debris from public rights of way",
        estimated_repair_cost_cents=3_000_000,
        mitigation_requested_cents=600_000,
    )
    submit_project(project["id"], applicant["id"])
    line_1 = create_cost_line_item(
        project["id"],
        applicant["id"],
        cost_type="MATERIALS",
        claimed_cents=3_000_000,
        work_start_at="2026-06-12T08:00:00Z",
        work_end_at="2026-06-12T17:00:00Z",
    )
    resource = create_labor_resource(
        applicant["id"],
        label="Street crew lead",
        employee_type="PERMANENT",
        base_hourly_rate_cents=5_000,
        fringe_benefit_pct=0.3,
    )
    line_2 = create_cost_line_item(
        project["id"],
        applicant["id"],
        cost_type="FORCE_ACCOUNT_LABOR",
        force_account_resource_id=resource["id"],
        claimed_cents=800_000,
        straight_time_hours=10,
        overtime_hours=0,
        work_start_at="2026-06-13T08:00:00Z",
        work_end_at="2026-06-13T18:00:00Z",
    )
    review_cost_line_item(line_1["id"])
    reviewed_2 = review_cost_line_item(line_2["id"])

    assert reviewed_2["review_status"] == "DISALLOWED", (
        f"Expected DISALLOWED on emergency straight time, got {reviewed_2['review_status']}"
    )
    assert reviewed_2["eligible_cents"] == 0, (
        f"Expected eligible_cents 0, got {reviewed_2['eligible_cents']}"
    )
    assert reviewed_2["disallowance_reason"] == "STRAIGHT_TIME_NOT_ELIGIBLE_FOR_EMERGENCY_WORK", (
        "Expected STRAIGHT_TIME_NOT_ELIGIBLE_FOR_EMERGENCY_WORK, got "
        f"{reviewed_2['disallowance_reason']}"
    )

    validated = validate_success(
        api.cost_review(project["id"], {"decision": "VALIDATE"}, make_specialist_headers())
    )

    assert validated["repair_eligible_cents"] == 3_000_000, (
        "The disallowed line contributes nothing, expected 3000000, got "
        f"{validated['repair_eligible_cents']}"
    )
    assert validated["size_class"] == "SMALL", (
        f"Expected SMALL below the 4000000 threshold, got {validated['size_class']}"
    )
    assert validated["mitigation_approved_cents"] == 600_000, (
        f"Expected mitigation_approved_cents 600000, got {validated['mitigation_approved_cents']}"
    )
    assert validated["anticipated_insurance_cents"] == 0, (
        f"Expected anticipated_insurance_cents 0, got {validated['anticipated_insurance_cents']}"
    )
    assert validated["insurance_reduction_cents"] == 0, (
        f"Expected insurance_reduction_cents 0, got {validated['insurance_reduction_cents']}"
    )
    assert validated["status"] == "VALIDATED", (
        f"Expected VALIDATED, got {validated['status']}"
    )


# ---------------------------------------------------------------------------
# The SCREENING risk variant: every facility counts, and the flood gap is
# all-or-nothing
# ---------------------------------------------------------------------------
def test_screening_risk_score_counts_every_facility_and_the_flood_gap(api):
    """PRD §3.1: "Three point components are weighted and summed: the
    applicant-type component at 30 percent, a second component at 30 percent,
    and a third component at 40 percent, with the weighted sum rounded half up
    to two decimal places."
    PRD §3.1: "The applicant-type component is a fixed point value read from the
    `applicant_type`: 20 points for `LOCAL_GOVERNMENT`, 30 for `TRIBE`, 10 for
    `STATE_AGENCY` and 60 for `PRIVATE_NONPROFIT`."
    PRD §3.1: "The resulting score maps to a tier: at least 60 points is `HIGH`,
    at least 30 but below 60 is `MEDIUM`, and anything below 30 is `LOW`."
    PRD §3.1: "The second component awards 10 points for every facility
    registered to the applicant, counted regardless of each facility's own
    `eligibility_status`, and is then capped at 100 points — so an applicant
    with ten or more facilities scores the maximum."
    PRD §3.1: "The third component is all-or-nothing: it is 100 points when the
    applicant owns at least one facility whose `flood_zone` is true and on which
    no insurance policy of `policy_type` `FLOOD` exists at all, and 0 points
    otherwise."

    Design: Corner/calculations/screening_risk_score_counts_every_facility_and_the_flood_gap
    """
    set_clock("2026-07-01T00:00:00Z")
    disaster = create_disaster(declaration_number="DR-4968")
    applicant_t = create_applicant(
        disaster["id"],
        name="Coastal Bend Tribe",
        applicant_type="TRIBE",
        population_served=9_000,
    )
    create_facility(
        applicant_t["id"],
        name="Tribal Admin Building",
        facility_type="BUILDING_EQUIPMENT",
        ownership="PUBLIC",
    )
    create_facility(
        applicant_t["id"],
        name="Tribal Water Plant",
        facility_type="WATER_CONTROL",
        ownership="PUBLIC",
    )
    facility_t3 = create_facility(
        applicant_t["id"],
        name="Riverfront Community Hall",
        facility_type="BUILDING_EQUIPMENT",
        ownership="PUBLIC",
        flood_zone=True,
    )
    create_insurance_policy(
        facility_t3["id"],
        applicant_t["id"],
        insurer_name="Gulf Mutual",
        policy_type="PROPERTY",
        coverage_limit_cents=1_000_000,
        deductible_cents=0,
        effective_start_at="2026-01-01T00:00:00Z",
        effective_end_at="2026-12-31T00:00:00Z",
    )
    applicant_n = create_applicant(
        disaster["id"],
        name="Harborview Volunteer Fire",
        applicant_type="PRIVATE_NONPROFIT",
        population_served=12_000,
        pnp_service_type="CRITICAL",
        tax_exempt_letter_on_file=True,
    )

    scored_t = validate_success(
        api.determine_eligibility(
            applicant_t["id"],
            {
                "decision": "ELIGIBLE",
                "rationale": "Federally recognised tribe inside the declared area",
            },
            make_specialist_headers(),
        )
    )
    scored_n = validate_success(
        api.determine_eligibility(
            applicant_n["id"],
            {"decision": "ELIGIBLE", "rationale": "Critical-service private nonprofit"},
            make_specialist_headers(),
        )
    )

    assert scored_t["risk_score_screening"] == pytest.approx(58.00, abs=0.005), (
        f"Expected risk_score_screening 58.00, got {scored_t['risk_score_screening']}"
    )
    assert scored_t["risk_tier"] == "MEDIUM", (
        f"Expected MEDIUM for a score of 58.00, got {scored_t['risk_tier']}"
    )
    assert scored_t["risk_score_monitoring"] is None, (
        f"Expected risk_score_monitoring null, got {scored_t['risk_score_monitoring']}"
    )
    assert scored_t["monitoring_scored_at"] is None, (
        f"Expected monitoring_scored_at null, got {scored_t['monitoring_scored_at']}"
    )
    assert scored_n["risk_score_screening"] == pytest.approx(18.00, abs=0.005), (
        f"Expected risk_score_screening 18.00 with no facilities, got "
        f"{scored_n['risk_score_screening']}"
    )
    assert scored_n["risk_tier"] == "LOW", (
        f"Expected LOW for a score of 18.00, got {scored_n['risk_tier']}"
    )
    for scored in (scored_t, scored_n):
        assert scored["eligibility_status"] == "ELIGIBLE", (
            f"Expected ELIGIBLE, got {scored['eligibility_status']}"
        )
        assert scored["monitoring_status"] == "STANDARD", (
            f"Expected STANDARD, got {scored['monitoring_status']}"
        )
        assert scored["drawdown_status"] == "ACTIVE", (
            f"Expected ACTIVE, got {scored['drawdown_status']}"
        )
