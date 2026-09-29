"""Shape assertions for the thirteen resource kinds.

PRD 2.4 splits the resource kinds into twelve that carry ``created_at``,
``updated_at`` and ``version`` and one — ``ComplianceLedgerEntry`` — that carries
only ``id`` and ``created_at``.  ``assert_identity_fields`` covers the twelve;
``assert_ledger_entry_shape`` covers the thirteenth and additionally asserts the
*absence* of the two fields the append-only ledger must not grow.
"""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

# PRD 2.4: the twelve kinds that carry created_at, updated_at and version.
VERSIONED_RESOURCE_KINDS = (
    "Facility",
    "DisclosureTemplate",
    "PayerContract",
    "PhysicianShift",
    "VolumeForecast",
    "Encounter",
    "AncillaryOrder",
    "TransferAgreement",
    "AmbulanceMOU",
    "TransferOrder",
    "Claim",
    "DisputeCase",
)


def assert_uuid_id(entity: dict) -> None:
    """PRD 2.4: every resource carries a server-minted UUID with no type prefix."""
    assert "id" in entity, f"resource is missing its id: {entity}"
    assert is_valid_uuid(entity["id"]), f"id is not a bare UUID: {entity['id']!r}"


def assert_identity_fields(entity: dict, expected_version: int | None = None) -> None:
    """Assert the identity block PRD 2.4 gives the twelve versioned resource kinds."""
    assert_uuid_id(entity)
    for field in ("created_at", "updated_at"):
        assert field in entity, f"resource is missing {field}: {entity}"
        assert is_iso8601_timestamp(
            entity[field]
        ), f"{field} is not an ISO 8601 UTC timestamp: {entity[field]!r}"
    assert isinstance(entity.get("version"), int), (
        f"version must be an integer, got {entity.get('version')!r}"
    )
    assert entity["version"] >= 1, "version is 1 when the row is created"
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


def assert_fields_present(entity: dict, fields) -> None:
    missing = [field for field in fields if field not in entity]
    assert not missing, f"resource is missing fields {missing}: {sorted(entity)}"


def assert_facility_shape(facility: dict) -> None:
    """PRD 3.1: the fields a facility carries, derived and supplied alike."""
    assert_identity_fields(facility)
    assert_fields_present(
        facility,
        (
            "name",
            "state_code",
            "license_category",
            "license_status",
            "observation_bed_count",
            "observation_beds_occupied",
            "imaging_scope",
            "lab_scope",
            "pharmacy_scope_tier",
            "max_concurrent_physicians",
            "signage_attestation_status",
            "signage_attested_at",
            "signage_expires_at",
            "signage_attested_by_user_id",
            "current_published_template_id",
            "open_compliance_defect_count",
            "compliance_posture",
            "restricted_service_codes",
            "ambulance_units_committed_total",
            "ambulance_units_reserved_total",
            "transfer_capacity_state",
            "coverage_deficit_flag",
        ),
    )


def assert_disclosure_template_shape(template: dict) -> None:
    """PRD 3.2: a template's drafted language plus its publication stamps."""
    assert_identity_fields(template)
    assert_fields_present(
        template,
        (
            "facility_id",
            "version_label",
            "supersedes_version_label",
            "facility_fee_cents",
            "observation_hourly_cents",
            "network_status_statement",
            "required_signage_elements",
            "status",
            "published_at",
            "published_by_user_id",
        ),
    )


def assert_payer_contract_shape(contract: dict) -> None:
    """PRD 3.3: the settlement vocabulary plus the two derived fields."""
    assert_identity_fields(contract)
    assert_fields_present(
        contract,
        (
            "facility_id",
            "payer_name",
            "network_status",
            "qualifying_payment_amount_cents",
            "in_network_coinsurance_rate",
            "in_network_deductible_remaining_cents",
            "state_protection_regime",
            "effective_start_date",
            "effective_end_date",
            "status",
            "idr_eligible",
        ),
    )


def assert_physician_shift_shape(shift: dict) -> None:
    """PRD 3.4: a coverage block and its rounded duration."""
    assert_identity_fields(shift)
    assert_fields_present(
        shift,
        (
            "facility_id",
            "clinician_user_id",
            "role_type",
            "board_certified",
            "start_utc",
            "end_utc",
            "duration_hours",
        ),
    )


def assert_volume_forecast_shape(forecast: dict) -> None:
    """PRD 3.4: the forecast inputs, the derived requirement and the reconciliation."""
    assert_identity_fields(forecast)
    assert_fields_present(
        forecast,
        (
            "facility_id",
            "period_start_date",
            "period_days",
            "historical_daily_volumes",
            "method",
            "forecast_basis",
            "forecast_daily_volume",
            "required_physician_hours_per_day",
            "required_physician_hours_total",
            "required_board_certified_hours_total",
            "scheduled_physician_hours",
            "coverage_deficit_hours",
            "status",
            "escalated_by_posture",
        ),
    )


def assert_transfer_agreement_shape(agreement: dict) -> None:
    """PRD 3.5: a standing receiving-hospital arrangement with a derived status."""
    assert_identity_fields(agreement)
    assert_fields_present(
        agreement,
        (
            "facility_id",
            "destination_hospital_name",
            "service_line",
            "capability_tier",
            "accepts_unstable",
            "effective_start_date",
            "effective_end_date",
            "status",
        ),
    )


def assert_ambulance_mou_shape(mou: dict) -> None:
    """PRD 3.5: the carrier commitment and its four derived unit fields."""
    assert_identity_fields(mou)
    assert_fields_present(
        mou,
        (
            "facility_id",
            "carrier_name",
            "level_of_care",
            "coverage_start_at",
            "coverage_end_at",
            "units_committed",
            "units_reserved",
            "units_available",
            "saturation_state",
            "status",
        ),
    )


def assert_encounter_shape(encounter: dict) -> None:
    """PRD 3.6: the two independent state dimensions on one registration row."""
    assert_identity_fields(encounter)
    assert_fields_present(
        encounter,
        (
            "facility_id",
            "patient_reference",
            "acuity_level",
            "presenting_service_line",
            "pinned_disclosure_template_id",
            "clinical_state",
            "disclosure_state",
            "arrival_at",
            "registered_by_user_id",
            "mse_start_deadline_at",
            "mse_timeliness",
            "mse_started_at",
            "mse_completed_at",
            "mse_physician_user_id",
            "stabilization_status",
            "observation_bed_held",
            "observation_started_at",
            "declined_transfer_count",
            "disclosed_estimate_cents",
            "disclosure_decided_by_user_id",
        ),
    )


def assert_ancillary_order_shape(order: dict) -> None:
    """PRD 3.7: a priced ancillary line and its resolution status."""
    assert_identity_fields(order)
    assert_fields_present(
        order,
        (
            "encounter_id",
            "category",
            "code",
            "quantity",
            "unit_charge_cents",
            "line_total_cents",
            "status",
        ),
    )


def assert_transfer_order_shape(order: dict) -> None:
    """PRD 3.8: the transfer order, its reservation and its round index."""
    assert_identity_fields(order)
    assert_fields_present(
        order,
        (
            "encounter_id",
            "transfer_agreement_id",
            "ambulance_mou_id",
            "clinical_benefit_certified",
            "certifying_physician_user_id",
            "requested_at",
            "reserved_unit_count",
            "round_index",
            "status",
            "decline_reason",
        ),
    )


def assert_claim_shape(claim: dict) -> None:
    """PRD 3.9: the frozen billed figures, the settlement and the pre-award snapshots."""
    assert_identity_fields(claim)
    assert_fields_present(
        claim,
        (
            "encounter_id",
            "payer_contract_id",
            "billed_facility_fee_cents",
            "billed_ancillary_cents",
            "billed_total_cents",
            "protection_variant",
            "allowed_amount_cents",
            "plan_paid_cents",
            "patient_responsibility_cents",
            "balance_bill_amount_cents",
            "written_off_cents",
            "pre_award_allowed_cents",
            "pre_award_plan_paid_cents",
            "pre_award_patient_responsibility_cents",
            "pre_award_written_off_cents",
            "negotiation_rounds_used",
            "status",
        ),
    )


def assert_dispute_case_shape(case: dict) -> None:
    """PRD 3.9: the negotiation cycle's state and the award it may carry."""
    assert_identity_fields(case)
    assert_fields_present(
        case,
        (
            "claim_id",
            "status",
            "round_index",
            "initiated_by_user_id",
            "last_offer_cents",
            "last_counteroffer_cents",
            "last_offer_by_user_id",
            "idr_award_cents",
            "awarded_at",
        ),
    )


def assert_ledger_entry_shape(entry: dict) -> None:
    """PRD 2.4: a ComplianceLedgerEntry carries only ``id`` and ``created_at``.

    The same paragraph is emphatic that the entry has **no** ``updated_at`` and
    **no** ``version``, because the ledger is append-only and an entry is never
    modified after it is written, so their absence is asserted here.
    """
    assert_uuid_id(entry)
    assert "created_at" in entry, f"ledger entry is missing created_at: {entry}"
    assert is_iso8601_timestamp(
        entry["created_at"]
    ), f"created_at is not an ISO 8601 UTC timestamp: {entry['created_at']!r}"
    assert "updated_at" not in entry, (
        "a ComplianceLedgerEntry has no updated_at, because the ledger is append-only"
    )
    assert "version" not in entry, (
        "a ComplianceLedgerEntry has no version, because the ledger is append-only"
    )
    assert_fields_present(
        entry,
        (
            "facility_id",
            "event_type",
            "severity",
            "subject_type",
            "subject_id",
            "detail",
            "recorded_at",
            "defect_counted",
        ),
    )


def assert_coverage_summary_shape(summary: dict) -> None:
    """PRD 3.4: the sixteen figures the reconciled coverage read reports."""
    assert_fields_present(
        summary,
        (
            "facility_id",
            "compliance_posture",
            "selected_volume_forecast_id",
            "forecast_basis",
            "forecast_method",
            "required_physician_hours_per_day",
            "required_physician_hours_total",
            "required_board_certified_hours_total",
            "scheduled_physician_hours",
            "board_certified_hours",
            "coverage_deficit_hours",
            "coverage_compliant",
            "coverage_deficit_flag",
            "observation_bed_count",
            "observation_beds_occupied",
            "ambulance_units_available",
        ),
    )
