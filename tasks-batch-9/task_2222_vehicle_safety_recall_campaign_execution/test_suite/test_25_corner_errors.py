"""
Error identity: each collection's own existence code, the two body references of a
parts allocation, the two uniqueness keys, and the three domain refusals that are
reported before the rules that would otherwise fire on the same field.
"""

from test_helpers import (
    AdjudicationDecision,
    ApiErrorId,
    CampaignStatus,
    FilingStatus,
    FilingType,
    NON_EXISTENT_UUID,
    RegionCode,
    RemedyStatus,
    RiskSeverity,
    SaleStatus,
    factories as f,
    fixtures as fx,
    get_success_data,
    make_dealer_service_manager_headers,
    read_list,
    validate_error,
)
from test_helpers.test_users import (
    CLAIMS_AUDITOR,
    COMPLIANCE_OFFICER_1,
    OPERATIONS_MANAGER,
    SAFETY_ENGINEER_1,
)


def test_unknown_affected_vehicle_id_reports_the_population_row_code(api):
    """
    A population row is addressed by its own id, not by a VIN, so an unresolvable
    affected-vehicle id answers with its own code rather than the build-record one.

    PRD §2.7: "**Path-identifier existence**, in this precedence: campaign
    (`ERR_CAMPAIGN_NOT_FOUND`), vehicle (`ERR_VEHICLE_NOT_FOUND`), affected-vehicle
    row (`ERR_AFFECTED_VEHICLE_NOT_FOUND`), notification wave
    (`ERR_WAVE_NOT_FOUND`), parts allocation (`ERR_ALLOCATION_NOT_FOUND`), repair
    claim (`ERR_CLAIM_NOT_FOUND`), owner reimbursement request
    (`ERR_REIMBURSEMENT_NOT_FOUND`)."

    Design: Corner/errors/unknown_affected_vehicle_id_returns_affected_vehicle_not_found
    """
    fx.set_clock(api, "2026-08-03T09:00:00Z")

    validate_error(
        api.get_affected_vehicle(NON_EXISTENT_UUID, COMPLIANCE_OFFICER_1),
        ApiErrorId.AFFECTED_VEHICLE_NOT_FOUND,
        404,
    )


def test_releasing_an_unknown_wave_is_a_not_found_not_a_state_conflict(api):
    """
    Existence is resolved in the second band, well ahead of any status rule, so
    releasing a wave that does not exist is a 404 and never a 409.

    PRD §2.7: "Identifiers in a path are resolved strictly left to right, and the
    first identifier that resolves to nothing determines the response."

    PRD §2.7: "**Path-identifier existence**, in this precedence: campaign
    (`ERR_CAMPAIGN_NOT_FOUND`), vehicle (`ERR_VEHICLE_NOT_FOUND`), affected-vehicle
    row (`ERR_AFFECTED_VEHICLE_NOT_FOUND`), notification wave
    (`ERR_WAVE_NOT_FOUND`), parts allocation (`ERR_ALLOCATION_NOT_FOUND`), repair
    claim (`ERR_CLAIM_NOT_FOUND`), owner reimbursement request
    (`ERR_REIMBURSEMENT_NOT_FOUND`)."

    Design: Corner/errors/unknown_wave_id_returns_wave_not_found
    """
    fx.set_clock(api, "2026-08-03T09:00:00Z")

    validate_error(
        api.release_wave(NON_EXISTENT_UUID, {}, OPERATIONS_MANAGER),
        ApiErrorId.WAVE_NOT_FOUND,
        404,
    )


def test_unknown_allocation_id_reports_the_allocation_code(api):
    """
    The allocation collection carries its own existence code, distinct from the wave
    code that guards the neighbouring paths.

    PRD §2.7: "**Path-identifier existence**, in this precedence: campaign
    (`ERR_CAMPAIGN_NOT_FOUND`), vehicle (`ERR_VEHICLE_NOT_FOUND`), affected-vehicle
    row (`ERR_AFFECTED_VEHICLE_NOT_FOUND`), notification wave
    (`ERR_WAVE_NOT_FOUND`), parts allocation (`ERR_ALLOCATION_NOT_FOUND`), repair
    claim (`ERR_CLAIM_NOT_FOUND`), owner reimbursement request
    (`ERR_REIMBURSEMENT_NOT_FOUND`)."

    Design: Corner/errors/unknown_allocation_id_returns_allocation_not_found
    """
    fx.set_clock(api, "2026-08-03T09:00:00Z")

    validate_error(
        api.get_parts_allocation(NON_EXISTENT_UUID, OPERATIONS_MANAGER),
        ApiErrorId.ALLOCATION_NOT_FOUND,
        404,
    )


def test_auditing_an_unknown_claim_is_a_not_found(api):
    """
    Auditing a claim that does not exist is refused on existence, ahead of the
    claim-status rule that guards the same action.

    PRD §2.7: "**Path-identifier existence**, in this precedence: campaign
    (`ERR_CAMPAIGN_NOT_FOUND`), vehicle (`ERR_VEHICLE_NOT_FOUND`), affected-vehicle
    row (`ERR_AFFECTED_VEHICLE_NOT_FOUND`), notification wave
    (`ERR_WAVE_NOT_FOUND`), parts allocation (`ERR_ALLOCATION_NOT_FOUND`), repair
    claim (`ERR_CLAIM_NOT_FOUND`), owner reimbursement request
    (`ERR_REIMBURSEMENT_NOT_FOUND`)."

    Design: Corner/errors/unknown_claim_id_returns_claim_not_found
    """
    fx.set_clock(api, "2026-08-03T09:00:00Z")

    validate_error(
        api.audit_repair_claim(NON_EXISTENT_UUID, f.audit_payload(), CLAIMS_AUDITOR),
        ApiErrorId.CLAIM_NOT_FOUND,
        404,
    )


def test_adjudicating_an_unknown_reimbursement_is_a_not_found(api):
    """
    The reimbursement-specific 404 answers ahead of the reimbursement-state 409,
    proving the existence band runs first on this path too.

    PRD §2.7: "**Path-identifier existence**, in this precedence: campaign
    (`ERR_CAMPAIGN_NOT_FOUND`), vehicle (`ERR_VEHICLE_NOT_FOUND`), affected-vehicle
    row (`ERR_AFFECTED_VEHICLE_NOT_FOUND`), notification wave
    (`ERR_WAVE_NOT_FOUND`), parts allocation (`ERR_ALLOCATION_NOT_FOUND`), repair
    claim (`ERR_CLAIM_NOT_FOUND`), owner reimbursement request
    (`ERR_REIMBURSEMENT_NOT_FOUND`)."

    Design: Corner/errors/unknown_reimbursement_id_returns_reimbursement_not_found
    """
    fx.set_clock(api, "2026-08-03T09:00:00Z")

    validate_error(
        api.adjudicate_owner_reimbursement(
            NON_EXISTENT_UUID,
            f.adjudicate_payload(
                decision=AdjudicationDecision.DENY,
                denial_reason="Probe against a non-existent request",
            ),
            CLAIMS_AUDITOR,
        ),
        ApiErrorId.REIMBURSEMENT_NOT_FOUND,
        404,
    )


def test_allocation_naming_an_unknown_dealer_reports_the_dealer_code(api):
    """
    The body carries a real remedy part with its current version token and a dealer id
    that matches no row: body references are resolved before the version comparison,
    so the answer is a 404 on the dealer and not a 412 on the part.

    PRD §2.7: "**Body-referenced existence** — a `dealer_id` that resolves to nothing
    yields `ERR_DEALER_NOT_FOUND`, a `labor_operation_id` yields
    `ERR_LABOR_OP_NOT_FOUND`, a `remedy_part_id` yields `ERR_PART_NOT_FOUND`, a
    `vehicle_id` yields `ERR_VEHICLE_NOT_FOUND`, an `affected_vehicle_id` yields
    `ERR_AFFECTED_VEHICLE_NOT_FOUND`, and a body `campaign_id` yields
    `ERR_CAMPAIGN_NOT_FOUND`."

    Design: Corner/errors/allocation_naming_an_unknown_dealer_returns_dealer_not_found
    """
    state = fx.filed_campaign(api, campaign={"campaign_number": "26V-330"})
    part = fx.add_remedy_part(
        api, state["campaign_id"], part_number="P-88330", total_procured_qty=100
    )

    response = api.create_parts_allocation(
        f.parts_allocation_payload(
            part["id"], NON_EXISTENT_UUID, part["version"], requested_qty=2
        ),
        OPERATIONS_MANAGER,
    )
    validate_error(response, ApiErrorId.DEALER_NOT_FOUND, 404)

    assert fx.read_part(api, state["campaign_id"], "P-88330")["unallocated_qty"] == 100


def test_allocation_naming_an_unknown_part_reports_the_part_code(api):
    """
    The mirror image of the dealer probe: a real ACTIVE dealer with an unknown
    `remedy_part_id` yields the part-specific 404, keeping the two body references
    independently diagnosable.

    PRD §2.7: "**Body-referenced existence** — a `dealer_id` that resolves to nothing
    yields `ERR_DEALER_NOT_FOUND`, a `labor_operation_id` yields
    `ERR_LABOR_OP_NOT_FOUND`, a `remedy_part_id` yields `ERR_PART_NOT_FOUND`, a
    `vehicle_id` yields `ERR_VEHICLE_NOT_FOUND`, an `affected_vehicle_id` yields
    `ERR_AFFECTED_VEHICLE_NOT_FOUND`, and a body `campaign_id` yields
    `ERR_CAMPAIGN_NOT_FOUND`."

    Design: Corner/errors/allocation_naming_an_unknown_part_returns_part_not_found
    """
    state = fx.filed_campaign(api, campaign={"campaign_number": "26V-331"})
    part = fx.add_remedy_part(
        api, state["campaign_id"], part_number="P-88331", total_procured_qty=100
    )
    dealer = fx.create_dealer(api)

    response = api.create_parts_allocation(
        f.parts_allocation_payload(
            NON_EXISTENT_UUID, dealer["id"], part["version"], requested_qty=2
        ),
        OPERATIONS_MANAGER,
    )
    validate_error(response, ApiErrorId.PART_NOT_FOUND, 404)

    read_list(
        api.list_parts_allocations(OPERATIONS_MANAGER, {"dealer_id": dealer["id"]}),
        expected_total=0,
    )


def test_reusing_a_campaign_number_is_a_duplicate(api):
    """
    Uniqueness rests on the campaign number alone, so a second file that differs in
    both defect type and description is still refused, and the first file is left
    untouched in DRAFT.

    PRD §3.1: "Campaign numbers are unique across the whole system, and a repeat is
    rejected with `ERR_DUPLICATE_CAMPAIGN_NUMBER`."

    Design: Corner/errors/reusing_a_campaign_number_returns_duplicate_campaign_number
    """
    fx.draft_campaign(api, campaign_number="26V-332")

    response = api.create_campaign(
        f.campaign_payload(
            campaign_number="26V-332",
            defect_type="NONCOMPLIANCE",
            defect_description="Label does not meet the standard",
            risk_severity=None,
        ),
        SAFETY_ENGINEER_1,
    )
    validate_error(response, ApiErrorId.DUPLICATE_CAMPAIGN_NUMBER, 409)

    read_list(
        api.list_campaigns(SAFETY_ENGINEER_1, {"campaign_status": CampaignStatus.DRAFT}),
        expected_total=1,
    )


def test_reusing_a_vin_is_a_duplicate(api):
    """
    The build record is keyed by VIN across the whole fleet rather than per campaign,
    so a second ingest with the same VIN but a different plant, build date and part
    number is still a duplicate, and the stored record keeps its original data.

    PRD §3.2: "A `RecallOperationsManager` ingests a vehicle with a 17-character
    `vin` that is unique across all build records (a repeat is `ERR_DUPLICATE_VIN`)"

    Design: Corner/errors/reusing_a_vin_returns_duplicate_vin
    """
    fx.set_clock(api, "2026-08-03T09:00:00Z")
    first = fx.create_vehicle(api, vin="1HGCM82633A004352")

    response = api.create_vehicle(
        f.vehicle_payload(
            vin="1HGCM82633A004352",
            plant_code="PLT2",
            model_code="MDLB",
            model_year=2025,
            production_date="2025-01-09",
            suspect_part_number=2500,
            region_code=RegionCode.WE,
            sale_status=SaleStatus.IN_DEALER_STOCK,
        ),
        OPERATIONS_MANAGER,
    )
    validate_error(response, ApiErrorId.DUPLICATE_VIN, 409)

    stored = get_success_data(api.get_vehicle(first["id"], OPERATIONS_MANAGER))
    assert stored["plant_code"] == "PLT1"
    assert stored["model_year"] == 2024
    assert stored["region_code"] == RegionCode.NE


def test_superseding_a_draft_campaign_is_refused(api):
    """
    A file that has not yet reached a defect determination has nothing to supersede,
    so the predecessor pointer is refused: the successor is never created and the
    DRAFT predecessor keeps its status.

    PRD §3.1: "The target must be a real campaign whose `campaign_status` is not
    `DRAFT`, `CLOSED` or `SUPERSEDED` — a draft has not yet been determined and so
    has nothing to supersede, and the two terminal states are already closed out —
    and any of those three yields `ERR_SUPERSEDED_CAMPAIGN_INVALID`."

    Design: Corner/errors/superseding_a_draft_campaign_returns_superseded_campaign_invalid
    """
    predecessor = fx.draft_campaign(api, campaign_number="26V-333")

    response = api.create_campaign(
        f.campaign_payload(
            campaign_number="26V-334",
            defect_description="Expanded inflator population",
            supersedes_campaign_id=predecessor["campaign_id"],
            risk_severity=None,
        ),
        SAFETY_ENGINEER_1,
    )
    validate_error(response, ApiErrorId.SUPERSEDED_CAMPAIGN_INVALID, 422)

    assert fx.read_campaign(api, predecessor["campaign_id"])["campaign_status"] == (
        CampaignStatus.DRAFT
    )
    read_list(
        api.list_campaigns(
            SAFETY_ENGINEER_1, {"supersedes_campaign_id": predecessor["campaign_id"]}
        ),
        expected_total=0,
    )


def test_claim_naming_an_unknown_labor_operation_reports_the_labor_op_code(api):
    """
    The affected-vehicle row and the dealer both resolve, so the only unresolvable
    body reference is the labor operation, and it answers as a 404 rather than as the
    effectivity refusal that guards the same field later.

    PRD §2.7: "**Body-referenced existence** — a `dealer_id` that resolves to nothing
    yields `ERR_DEALER_NOT_FOUND`, a `labor_operation_id` yields
    `ERR_LABOR_OP_NOT_FOUND`, a `remedy_part_id` yields `ERR_PART_NOT_FOUND`, a
    `vehicle_id` yields `ERR_VEHICLE_NOT_FOUND`, an `affected_vehicle_id` yields
    `ERR_AFFECTED_VEHICLE_NOT_FOUND`, and a body `campaign_id` yields
    `ERR_CAMPAIGN_NOT_FOUND`."

    Design: Corner/errors/claim_naming_an_unknown_labor_operation_returns_labor_op_not_found
    """
    state = fx.filed_campaign(api, campaign={"campaign_number": "26V-335"})
    dealer = fx.create_dealer(api)
    row = fx.find_affected_vehicle(api, state["campaign_id"], state["vehicle_id"])

    response = api.create_repair_claim(
        f.repair_claim_payload(
            row["id"],
            dealer["id"],
            NON_EXISTENT_UUID,
            repair_date="2026-08-03",
            claimed_labor_hours=1.10,
            parts_used_qty=1,
        ),
        make_dealer_service_manager_headers(dealer["id"]),
    )
    validate_error(response, ApiErrorId.LABOR_OP_NOT_FOUND, 404)

    read_list(
        api.list_repair_claims(CLAIMS_AUDITOR, {"campaign_id": state["campaign_id"]}),
        expected_total=0,
    )


def test_amendment_for_an_unreported_period_is_refused(api):
    """
    An amendment is period-scoped: the campaign does hold a SUBMITTED quarterly
    report, but for the previous quarter, so amending an unreported period is refused
    and the reported quarter stays SUBMITTED rather than being marked amended.

    PRD §3.3: "It requires an existing `QUARTERLY` filing for the campaign with the
    same `report_period` and status `SUBMITTED`; without one, the request is rejected
    with `ERR_NO_QUARTERLY_FILING_TO_AMEND`."

    Design: Corner/errors/amendment_for_an_unreported_period_returns_no_quarterly_filing_to_amend
    """
    state = fx.monitored_campaign(
        api,
        report_period="2026Q3",
        scheduled_mail_date="2026-08-03",
        vehicles=[
            {
                "vin": "1HGCM82633A004352",
                "production_date": "2024-03-15",
                "suspect_part_number": 1500,
                "owner_name": "Ann Vega",
            },
            {
                "vin": "1HGCM82633A004353",
                "production_date": "2024-03-16",
                "suspect_part_number": 1501,
                "owner_name": "Ben Ito",
            },
        ],
        requested_qty=2,
        campaign={"campaign_number": "26V-336", "risk_severity": RiskSeverity.LOW},
        labor_operation={"labor_op_code": "R336-01"},
        remedy_part={"part_number": "P-88336", "total_procured_qty": 100},
    )

    response = api.create_filing(
        state["campaign_id"],
        f.amendment_filing_payload(
            report_period="2026Q4", narrative="Correcting the completion figures"
        ),
        COMPLIANCE_OFFICER_1,
    )
    validate_error(response, ApiErrorId.NO_QUARTERLY_FILING_TO_AMEND, 422)

    read_list(
        api.list_filings(
            state["campaign_id"], COMPLIANCE_OFFICER_1, {"filing_type": FilingType.AMENDMENT}
        ),
        expected_total=0,
    )
    quarterly, _ = read_list(
        api.list_filings(
            state["campaign_id"], COMPLIANCE_OFFICER_1, {"report_period": "2026Q3"}
        ),
        expected_total=1,
    )
    assert quarterly[0]["status"] == FilingStatus.SUBMITTED

    campaign = fx.read_campaign(api, state["campaign_id"])
    assert campaign["campaign_status"] == CampaignStatus.MONITORING
    assert campaign["quarterly_filing_count"] == 1
    assert campaign["remedy_status"] == RemedyStatus.REMEDY_RELEASED
