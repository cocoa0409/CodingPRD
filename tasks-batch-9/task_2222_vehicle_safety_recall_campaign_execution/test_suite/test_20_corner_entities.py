"""
Entity-level contract: creation echoes, declared defaults, computed counters,
system-stamped identity, pagination metadata and body-id resolution.
"""

from test_helpers import (
    AllocationStatus,
    ApiErrorId,
    CampaignStatus,
    NON_EXISTENT_UUID,
    OutreachChannel,
    OutreachOutcome,
    RemedyStatus,
    assert_common_fields,
    assert_dealer,
    assert_outreach_attempt,
    assert_remedy_part,
    assert_vehicle,
    factories as f,
    fixtures as fx,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_dealer_service_manager_headers,
    read_list,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import (
    CLAIMS_AUDITOR,
    COMPLIANCE_OFFICER_1,
    OPERATIONS_MANAGER,
    SAFETY_ENGINEER_1,
)

FULL_BUILD_RECORD = {
    "vin": "1HGCM82633A004352",
    "plant_code": "PLT1",
    "model_code": "MDLA",
    "model_year": 2024,
    "production_date": "2024-03-15",
    "suspect_part_number": 1500,
    "region_code": "NE",
    "sale_status": "IN_DEALER_STOCK",
    "in_service_date": "2024-05-02",
    "owner_name": "Ann Vega",
    "owner_address_valid": True,
}


def test_build_record_creation_echoes_every_supplied_attribute(api):
    """
    A build record is a standalone aggregate: it is accepted against an empty
    database with no campaign in sight, and every ingested attribute comes back
    unchanged with the server-managed hold at false.

    PRD §3.2: "A `RecallOperationsManager` ingests a vehicle with a 17-character
    `vin` that is unique across all build records (a repeat is
    `ERR_DUPLICATE_VIN`), the `plant_code` and `model_code` of the assembly, the
    `model_year`, the `production_date` on which it was built, the
    `suspect_part_number` sequence number of the installed suspect part, and a
    `region_code` of `NE`, `SE`, `MW` or `WE` derived from the owner's address."

    PRD §3.2: "`stop_sale_hold` is server-managed and starts false."

    Design: Corner/entities/vehicle_creation_returns_201_with_all_input_fields_persisted
    """
    fx.set_clock(api, "2026-08-03T09:00:00Z")

    vehicle = validate_success(
        api.create_vehicle(f.vehicle_payload(**FULL_BUILD_RECORD), OPERATIONS_MANAGER), 201
    )
    assert_vehicle(vehicle)

    for field, expected in FULL_BUILD_RECORD.items():
        assert vehicle[field] == expected, field
    assert vehicle["stop_sale_hold"] is False


def test_campaign_read_returns_the_counters_the_population_run_wrote(api):
    """
    Reading a campaign is a pure retrieval: it hands back the two counters the
    matching pass already persisted without re-running the match.

    PRD §3.2: "The run then refreshes the campaign's `affected_vehicle_count` to
    the total number of affected-vehicle rows in any status, sets
    `recall_population_count` to that total minus the number of rows in
    `REMOVED_FROM_POPULATION`, recomputes `completion_rate_pct`, increments the
    campaign's `version` by 1, and refreshes every rule's
    `matched_vehicle_count`."

    Design: Corner/entities/campaign_retrieval_returns_stored_population_counters
    """
    state = fx.campaign_with_population(
        api,
        campaign={"campaign_number": "26V-110", "defect_description": "Inflator may rupture"},
        vehicles=[
            {"vin": "1HGCM82633A004352", "production_date": "2024-03-15", "suspect_part_number": 1500},
            {"vin": "1HGCM82633A004353", "production_date": "2024-03-16", "suspect_part_number": 1501},
        ],
    )

    campaign = validate_success(api.get_campaign(state["campaign_id"], CLAIMS_AUDITOR), 200)

    assert campaign["campaign_number"] == "26V-110"
    assert campaign["affected_vehicle_count"] == 2
    assert campaign["recall_population_count"] == 2
    assert campaign["remedied_count"] == 0
    assert campaign["completion_rate_pct"] == 0.00
    assert campaign["campaign_status"] == CampaignStatus.DEFECT_DETERMINED
    assert campaign["remedy_status"] == RemedyStatus.REMEDY_UNDER_DEVELOPMENT


def test_campaign_listing_reports_the_prepagination_total_on_every_page(api):
    """
    Two pages over three campaigns: each page echoes its own `limit` and `offset`
    but the same `total_count` of 3, and `has_more` flips only on the last page.

    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope, where `total_count` is the
    number of records matching the filters before pagination is applied and
    `has_more` indicates whether records remain beyond the current page."

    Design: Corner/entities/campaign_listing_paginates_with_total_count_and_has_more
    """
    fx.set_clock(api, "2026-08-03T09:00:00Z")
    for number, defect_type, description in (
        ("26V-121", "SAFETY_DEFECT", "Inflator may rupture"),
        ("26V-122", "NONCOMPLIANCE", "Lamp intensity below standard"),
        ("26V-123", "SAFETY_DEFECT", "Brake hose abrasion"),
    ):
        fx.create_campaign(
            api, campaign_number=number, defect_type=defect_type, defect_description=description
        )

    first, first_meta = validate_paginated(
        api.list_campaigns(COMPLIANCE_OFFICER_1, {"limit": 2, "offset": 0})
    )
    assert len(first) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert first_meta["has_more"] is True

    second, second_meta = validate_paginated(
        api.list_campaigns(COMPLIANCE_OFFICER_1, {"limit": 2, "offset": 2})
    )
    assert len(second) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["limit"] == 2
    assert second_meta["offset"] == 2
    assert second_meta["has_more"] is False


def test_campaign_read_with_an_unused_uuid_is_a_not_found(api):
    """
    A well-formed but unused UUID in the path is resolved before anything else, so
    the answer is a 404 rather than an empty body.

    PRD §2.7: "Identifiers in a path are resolved strictly left to right, and the
    first identifier that resolves to nothing determines the response."

    PRD §2.7: "**Path-identifier existence**, in this precedence: campaign
    (`ERR_CAMPAIGN_NOT_FOUND`), vehicle (`ERR_VEHICLE_NOT_FOUND`),
    affected-vehicle row (`ERR_AFFECTED_VEHICLE_NOT_FOUND`), notification wave
    (`ERR_WAVE_NOT_FOUND`), parts allocation (`ERR_ALLOCATION_NOT_FOUND`), repair
    claim (`ERR_CLAIM_NOT_FOUND`), owner reimbursement request
    (`ERR_REIMBURSEMENT_NOT_FOUND`)."

    Design: Corner/entities/campaign_retrieval_with_unknown_id_returns_not_found
    """
    fx.set_clock(api, "2026-08-03T09:00:00Z")

    validate_error(
        api.get_campaign(NON_EXISTENT_UUID, SAFETY_ENGINEER_1),
        ApiErrorId.CAMPAIGN_NOT_FOUND,
        404,
    )


def test_build_record_without_a_vin_is_a_shape_error(api):
    """
    `vin` has no default, so omitting it fails the payload-shape band before any
    domain lookup happens, and no build record is stored.

    PRD §2.7: "**Payload shape** — required fields present, enum values drawn from
    their declared sets, constrained numbers positive, dates and instants
    parsable, pagination parameters in range — `ERR_INVALID_REQUEST`."

    Design: Corner/entities/vehicle_creation_missing_required_vin_is_rejected
    """
    fx.set_clock(api, "2026-08-03T09:00:00Z")

    response = api.create_vehicle(
        {
            "plant_code": "PLT1",
            "model_code": "MDLA",
            "model_year": 2024,
            "production_date": "2024-03-15",
            "suspect_part_number": 1500,
            "region_code": "NE",
        },
        OPERATIONS_MANAGER,
    )
    validate_error(response, ApiErrorId.INVALID_REQUEST, 400)


def test_campaign_creation_applies_its_declared_defaults(api):
    """
    With `risk_severity` and `supersedes_campaign_id` omitted, the campaign comes
    back MODERATE / DRAFT / REMEDY_UNDER_DEVELOPMENT with a perfect effectiveness
    score and every counter at zero — defaults, not nulls.

    PRD §3.1: "A `risk_severity` of `HIGH`, `MODERATE` or `LOW` may be supplied;
    when it is omitted the campaign is treated as `MODERATE`."

    PRD §3.1: "The new file starts in `campaign_status` `DRAFT` with
    `remedy_status` `REMEDY_UNDER_DEVELOPMENT`, `stop_sale_flag` and
    `do_not_drive_flag` both false, `remedy_revision_count` and
    `quarterly_filing_count` at 0, `reimbursement_obligation_cents` at 0,
    `completion_rate_pct` at 0.00, and `remedy_effectiveness_score` at 100.00"

    Design: Corner/entities/campaign_creation_omitting_optional_fields_applies_declared_defaults
    """
    fx.set_clock(api, "2026-08-03T09:00:00Z")

    campaign = validate_success(
        api.create_campaign(
            {
                "campaign_number": "26V-130",
                "defect_type": "SAFETY_DEFECT",
                "defect_description": "Inflator may rupture",
            },
            SAFETY_ENGINEER_1,
        ),
        201,
    )

    assert campaign["risk_severity"] == "MODERATE"
    assert campaign["campaign_status"] == CampaignStatus.DRAFT
    assert campaign["remedy_status"] == RemedyStatus.REMEDY_UNDER_DEVELOPMENT
    assert campaign["remedy_effectiveness_score"] == 100.00
    assert campaign["completion_rate_pct"] == 0.00
    assert campaign["days_late"] == 0
    assert campaign["late_filing_flag"] is False
    assert campaign["stop_sale_flag"] is False
    assert campaign["do_not_drive_flag"] is False
    assert campaign["remedy_revision_count"] == 0
    assert campaign["quarterly_filing_count"] == 0
    assert campaign["open_followup_wave_count"] == 0
    assert campaign["reimbursement_obligation_cents"] == 0
    assert campaign["supersedes_campaign_id"] is None


def test_remedy_part_pool_starts_fully_unallocated(api):
    """
    `unallocated_qty` is computed from `total_procured_qty` rather than supplied,
    `consumed_qty` starts at zero, and an omitted `lead_time_days` falls back to
    thirty.

    PRD §3.5: "On registration `unallocated_qty` is initialised to the full
    `total_procured_qty` and `consumed_qty` starts at 0."

    PRD §3.5: "and optionally a supplier `lead_time_days` for planning, which
    defaults to 30 days when omitted."

    Design: Corner/entities/remedy_part_creation_computes_unallocated_qty_from_total_procured
    """
    state = fx.draft_campaign(api, campaign_number="26V-140")

    part = validate_success(
        api.create_remedy_part(
            state["campaign_id"],
            {"part_number": "P-88123", "unit_cost": 21.90, "total_procured_qty": 100},
            SAFETY_ENGINEER_1,
        ),
        201,
    )
    assert_remedy_part(part)

    assert part["total_procured_qty"] == 100
    assert part["unallocated_qty"] == 100
    assert part["consumed_qty"] == 0
    assert part["lead_time_days"] == 30
    assert part["campaign_id"] == state["campaign_id"]
    assert part["unit_cost"] == 21.90


def test_dealer_creation_is_stamped_with_system_identity(api):
    """
    The caller supplies none of the identity fields: the server mints the id and
    both timestamps and opens the record at version 1, ACTIVE and unsuspended.

    PRD §2.4: "Every persisted record exposes an `id`, which is a server-minted
    UUID carrying no type prefix, and a `created_at` timestamp formatted as an ISO
    8601 UTC instant with three fractional digits."

    PRD §3.5: "A dealer's `status` starts `ACTIVE` and can be moved to `SUSPENDED`
    with a `suspension_reason`"

    Design: Corner/entities/dealer_creation_stamps_system_id_timestamps_and_version
    """
    fx.set_clock(api, "2026-08-03T09:00:00Z")

    dealer = validate_success(
        api.create_dealer(
            {
                "dealer_code": "D-NE-01",
                "name": "Vega Motors",
                "region_code": "NE",
                "labor_rate_per_hour": 138.74,
                "monthly_repair_capacity": 40,
            },
            OPERATIONS_MANAGER,
        ),
        201,
    )
    assert_dealer(dealer)
    assert_common_fields(dealer, versioned=True)

    assert is_valid_uuid(dealer["id"])
    assert dealer["version"] == 1
    assert is_iso8601_timestamp(dealer["created_at"])
    assert is_iso8601_timestamp(dealer["updated_at"])
    assert dealer["status"] == "ACTIVE"
    assert dealer["suspension_reason"] is None


def test_population_rule_whose_window_is_empty_is_refused(api):
    """
    The build window is half-open, so a start equal to the end describes a window
    no build can occupy; it is refused rather than stored.

    PRD §3.2: "A rule whose `production_start_date` is not strictly earlier than
    its `production_end_date` is rejected with `ERR_INVALID_DATE_RANGE`."

    Design: Corner/entities/population_rule_with_equal_start_and_end_dates_is_rejected
    """
    state = fx.draft_campaign(api, campaign_number="26V-150")

    response = api.create_population_rule(
        state["campaign_id"],
        f.population_rule_payload(
            production_start_date="2024-03-01", production_end_date="2024-03-01"
        ),
        SAFETY_ENGINEER_1,
    )
    validate_error(response, ApiErrorId.INVALID_DATE_RANGE, 422)

    read_list(
        api.list_population_rules(state["campaign_id"], SAFETY_ENGINEER_1), expected_total=0
    )


def test_outreach_attempt_is_an_immutable_audit_entry(api):
    """
    The logged attempt reports its channel, outcome, sequence number and clock
    stamp, and carries neither `updated_at` nor `version` — there is nothing to
    mutate on it.

    PRD §2.4: "Outreach attempts are the single exception: an outreach attempt is
    an immutable audit entry, so it carries only `id` and `created_at`, and neither
    `updated_at` nor `version` is present on it at all."

    PRD §3.8: "Each attempt records `attempt_number` as one more than the number
    of prior attempts on the same row, and `attempted_at` from the logical clock;
    the row's `outreach_attempt_count` increments accordingly."

    Design: Corner/entities/outreach_attempt_is_immutable_with_no_version_field
    """
    state = fx.campaign_with_population(
        api, campaign={"campaign_number": "26V-160", "defect_description": "Inflator may rupture"}
    )
    row = fx.find_affected_vehicle(api, state["campaign_id"], state["vehicle_id"])
    fx.log_outreach(
        api,
        row["id"],
        channel=OutreachChannel.PHONE,
        outcome=OutreachOutcome.NO_RESPONSE,
        note="Left voicemail",
    )

    attempts, _ = read_list(
        api.list_outreach_attempts(row["id"], CLAIMS_AUDITOR), expected_total=1
    )
    attempt = attempts[0]
    assert_outreach_attempt(attempt)

    assert attempt["attempt_number"] == 1
    assert attempt["channel"] == OutreachChannel.PHONE
    assert attempt["outcome"] == OutreachOutcome.NO_RESPONSE
    assert attempt["affected_vehicle_id"] == row["id"]
    assert is_iso8601_timestamp(attempt["attempted_at"])
    assert "version" not in attempt
    assert "updated_at" not in attempt


def test_reimbursement_naming_an_unknown_vehicle_is_a_body_id_not_found(api):
    """
    A `vehicle_id` in the request body that resolves to nothing is answered in the
    body-referenced-existence band, ahead of the in-population check and of any
    reimbursement arithmetic.

    PRD §2.7: "**Body-referenced existence** — a `dealer_id` that resolves to
    nothing yields `ERR_DEALER_NOT_FOUND`, a `labor_operation_id` yields
    `ERR_LABOR_OP_NOT_FOUND`, a `remedy_part_id` yields `ERR_PART_NOT_FOUND`, a
    `vehicle_id` yields `ERR_VEHICLE_NOT_FOUND`, an `affected_vehicle_id` yields
    `ERR_AFFECTED_VEHICLE_NOT_FOUND`, and a body `campaign_id` yields
    `ERR_CAMPAIGN_NOT_FOUND`."

    Design: Corner/entities/owner_reimbursement_with_unknown_vehicle_returns_vehicle_not_found
    """
    state = fx.campaign_with_population(
        api, campaign={"campaign_number": "26V-170", "defect_description": "Inflator may rupture"}
    )

    response = api.create_owner_reimbursement(
        f.owner_reimbursement_payload(
            state["campaign_id"],
            NON_EXISTENT_UUID,
            invoice_date="2026-07-15",
            invoice_amount=412.75,
            labor_hours_claimed=1.30,
        ),
        OPERATIONS_MANAGER,
    )
    validate_error(response, ApiErrorId.VEHICLE_NOT_FOUND, 404)

    read_list(
        api.list_owner_reimbursements(
            OPERATIONS_MANAGER, {"campaign_id": state["campaign_id"]}
        ),
        expected_total=0,
    )


def test_claim_naming_another_campaigns_labor_operation_is_a_cross_campaign_mix(api):
    """
    The foreign labor operation's window does contain the repair date, so the
    temporal band passes and the cross-campaign integrity rule is what fires.

    PRD §3.7: "The dealer, the labor operation and the affected-vehicle row must
    all belong to the same campaign; a mix across campaigns is rejected with
    `ERR_PART_CAMPAIGN_MISMATCH`."

    Design: Corner/entities/repair_claim_naming_another_campaigns_labor_operation_is_rejected
    """
    other = fx.create_campaign(
        api,
        campaign_number="26V-181",
        defect_type="NONCOMPLIANCE",
        defect_description="Lamp intensity below standard",
    )
    foreign_operation = fx.add_labor_operation(
        api,
        other["id"],
        labor_op_code="R181-01",
        description="Replace headlamp assembly",
        flat_hours=1.10,
        effective_from="2026-08-01",
        effective_to="2027-12-31",
    )

    state = fx.campaign_with_allocation(
        api,
        requested_qty=1,
        campaign={"campaign_number": "26V-180", "defect_description": "Inflator may rupture"},
        labor_operation={"labor_op_code": "R180-01"},
        remedy_part={"part_number": "P-88180"},
        narrative="Part 573 defect information report for 26V-180",
    )
    row = fx.find_affected_vehicle(api, state["campaign_id"], state["vehicle_id"])

    response = api.create_repair_claim(
        f.repair_claim_payload(
            row["id"],
            state["dealer_id"],
            foreign_operation["id"],
            repair_date="2026-08-03",
            claimed_labor_hours=1.10,
            parts_used_qty=1,
        ),
        make_dealer_service_manager_headers(state["dealer_id"]),
    )
    validate_error(response, ApiErrorId.PART_CAMPAIGN_MISMATCH, 422)

    read_list(
        api.list_repair_claims(CLAIMS_AUDITOR, {"campaign_id": state["campaign_id"]}),
        expected_total=0,
    )

    allocations, _ = read_list(
        api.list_parts_allocations(OPERATIONS_MANAGER, {"campaign_id": state["campaign_id"]}),
        expected_total=1,
    )
    assert allocations[0]["status"] == AllocationStatus.ALLOCATED
    assert allocations[0]["consumed_qty"] == 0
