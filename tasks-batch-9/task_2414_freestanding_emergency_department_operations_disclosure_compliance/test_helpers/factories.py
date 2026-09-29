"""Request-payload builders.

Every builder produces a payload that satisfies the request-shape step of the
validation ladder by default and accepts keyword overrides so a test can break
exactly one field.  Passing ``None`` for an optional field drops it from the
payload entirely, which is how a test exercises "field omitted" as distinct from
"field present and null".
"""

from .constants import (
    CANONICAL_ANCILLARY_LINES,
    TEST_DEFAULTS,
)

_OMIT = object()


def _compose(base: dict, overrides: dict) -> dict:
    """Apply overrides, dropping any key whose override is the ``_OMIT`` sentinel."""
    payload = dict(base)
    for key, value in overrides.items():
        if value is _OMIT:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


def make_facility_payload(**overrides) -> dict:
    """PRD 3.1: name, state_code, license_category, scope arrays and capacity."""
    return _compose(
        {
            "name": TEST_DEFAULTS["FACILITY_NAME"],
            "state_code": TEST_DEFAULTS["STATE_CODE"],
            "license_category": "INDEPENDENT_FREESTANDING_ED",
            "license_status": "ACTIVE",
            "observation_bed_count": 2,
            "imaging_scope": ["XRAY", "CT", "ULTRASOUND", "MRI"],
            "lab_scope": ["CBC", "CHEMISTRY", "TROPONIN", "BLOOD_CULTURE"],
            "pharmacy_scope_tier": "EMERGENCY_ONLY",
            "max_concurrent_physicians": 2,
        },
        overrides,
    )


def make_facility_update_payload(expected_facility_version: int, **overrides) -> dict:
    """PRD 2.5 and 3.1: a partial update always carrying expected_facility_version."""
    return _compose(
        {"expected_facility_version": expected_facility_version}, overrides
    )


def make_template_payload(**overrides) -> dict:
    """PRD 3.2: the drafted disclosure language."""
    return _compose(
        {
            "version_label": "V1",
            "facility_fee_cents": TEST_DEFAULTS["TEMPLATE_FACILITY_FEE_CENTS"],
            "observation_hourly_cents": TEST_DEFAULTS[
                "TEMPLATE_OBSERVATION_HOURLY_CENTS"
            ],
            "network_status_statement": "OUT_OF_NETWORK_ALL_PLANS",
            "required_signage_elements": [
                "LICENSE_CATEGORY_SIGN",
                "FEE_DISCLOSURE_SIGN",
                "NETWORK_STATUS_SIGN",
                "NOT_A_URGENT_CARE_SIGN",
            ],
        },
        overrides,
    )


def make_publish_payload(expected_facility_version: int, **overrides) -> dict:
    """PRD 2.5: publication carries the owning facility's expected version."""
    return _compose(
        {"expected_facility_version": expected_facility_version}, overrides
    )


def make_signage_attestation_payload(**overrides) -> dict:
    """PRD 3.1: the elements the compliance officer certifies are physically posted."""
    return _compose(
        {
            "attested_elements": [
                "LICENSE_CATEGORY_SIGN",
                "FEE_DISCLOSURE_SIGN",
                "NETWORK_STATUS_SIGN",
                "NOT_A_URGENT_CARE_SIGN",
            ],
            "attestation_note": "All four placards verified on the wall.",
        },
        overrides,
    )


def make_payer_contract_payload(**overrides) -> dict:
    """PRD 3.3: the whole vocabulary the settlement engine needs."""
    return _compose(
        {
            "payer_name": TEST_DEFAULTS["PAYER_NAME"],
            "network_status": "OUT_OF_NETWORK",
            "qualifying_payment_amount_cents": TEST_DEFAULTS["QPA_CENTS"],
            "in_network_coinsurance_rate": TEST_DEFAULTS["COINSURANCE_RATE"],
            "in_network_deductible_remaining_cents": TEST_DEFAULTS[
                "DEDUCTIBLE_REMAINING_CENTS"
            ],
            "state_protection_regime": "FEDERAL_NSA_ONLY",
            "effective_start_date": TEST_DEFAULTS["CONTRACT_START"],
            "effective_end_date": TEST_DEFAULTS["CONTRACT_END"],
        },
        overrides,
    )


def make_physician_shift_payload(**overrides) -> dict:
    """PRD 3.4: a coverage block given as a half-open interval."""
    return _compose(
        {
            "clinician_user_id": "doc-a",
            "role_type": "PHYSICIAN",
            "board_certified": True,
            "start_utc": "2026-08-03T08:00:00Z",
            "end_utc": "2026-08-03T16:00:00Z",
        },
        overrides,
    )


def make_volume_forecast_payload(**overrides) -> dict:
    """PRD 3.4: the period, the history window and the forecasting method."""
    return _compose(
        {
            "period_start_date": "2026-08-01",
            "period_days": 7,
            "historical_daily_volumes": [22, 19, 26, 31, 18, 24, 29],
            "method": "TRAILING_MEAN",
        },
        overrides,
    )


def make_transfer_agreement_payload(**overrides) -> dict:
    """PRD 3.5: a receiving-hospital arrangement and its inclusive date window."""
    return _compose(
        {
            "destination_hospital_name": TEST_DEFAULTS["DESTINATION_HOSPITAL"],
            "service_line": "CARDIAC",
            "capability_tier": 3,
            "accepts_unstable": True,
            "effective_start_date": TEST_DEFAULTS["CONTRACT_START"],
            "effective_end_date": TEST_DEFAULTS["CONTRACT_END"],
        },
        overrides,
    )


def make_ambulance_mou_payload(**overrides) -> dict:
    """PRD 3.5: the carrier commitment and its half-open coverage window."""
    return _compose(
        {
            "carrier_name": TEST_DEFAULTS["CARRIER_NAME"],
            "level_of_care": "CRITICAL_CARE",
            "coverage_start_at": TEST_DEFAULTS["MOU_COVERAGE_START"],
            "coverage_end_at": TEST_DEFAULTS["MOU_COVERAGE_END"],
            "units_committed": 2,
        },
        overrides,
    )


def make_encounter_payload(**overrides) -> dict:
    """PRD 3.6: the three inputs a registration clerk supplies."""
    return _compose(
        {
            "patient_reference": "PT-1001",
            "acuity_level": 3,
            "presenting_service_line": "CARDIAC",
        },
        overrides,
    )


def make_disclosure_decision_payload(decision: str = "ACKNOWLEDGED", **overrides) -> dict:
    """PRD 3.6: the patient's answer, with an optional waiver reason."""
    return _compose({"decision": decision}, overrides)


def make_begin_mse_payload(**overrides) -> dict:
    """PRD 3.7: beginning the screening accepts an optional screening note."""
    return _compose({}, overrides)


def make_complete_mse_payload(stabilization_status: str = "STABLE", **overrides) -> dict:
    """PRD 3.7: completion requires a stabilization finding of STABLE or UNSTABLE."""
    return _compose({"stabilization_status": stabilization_status}, overrides)


def make_observation_payload(**overrides) -> dict:
    """PRD 3.7: observation admission accepts an optional plan note."""
    return _compose({}, overrides)


def make_discharge_payload(**overrides) -> dict:
    """PRD 3.7: discharge accepts an optional instruction acknowledgement."""
    return _compose({}, overrides)


def make_ancillary_order_payload(
    category: str = "IMAGING", code: str = "CT", quantity: int = 1, **overrides
) -> dict:
    """PRD 3.7: category, code and quantity, the code belonging to the category."""
    return _compose(
        {"category": category, "code": code, "quantity": quantity}, overrides
    )


def make_ancillary_resolve_payload(outcome: str = "RESULTED", **overrides) -> dict:
    """PRD 3.7: resolution fixes whether the line is money."""
    return _compose({"outcome": outcome}, overrides)


def canonical_ancillary_line_payloads() -> list:
    """The CT x2, TROPONIN x2, ANALGESIC x1 bundle the settlement narrative works."""
    return [dict(line) for line in CANONICAL_ANCILLARY_LINES]


def make_transfer_order_payload(
    transfer_agreement_id: str,
    ambulance_mou_id: str,
    expected_encounter_version: int,
    **overrides,
) -> dict:
    """PRD 3.8: the two referenced arrangements, the token and the certification."""
    return _compose(
        {
            "expected_encounter_version": expected_encounter_version,
            "transfer_agreement_id": transfer_agreement_id,
            "ambulance_mou_id": ambulance_mou_id,
            "clinical_benefit_certified": True,
        },
        overrides,
    )


def make_transfer_accept_payload(**overrides) -> dict:
    """PRD 3.8: acceptance accepts an optional accepting-clinician note."""
    return _compose({}, overrides)


def make_transfer_decline_payload(decline_reason: str = "CAPACITY", **overrides) -> dict:
    """PRD 3.8: declining requires CAPACITY, CAPABILITY or INSURANCE."""
    return _compose({"decline_reason": decline_reason}, overrides)


def make_transfer_complete_payload(**overrides) -> dict:
    """PRD 3.8: completion accepts an optional arrival confirmation note."""
    return _compose({}, overrides)


def make_claim_payload(payer_contract_id: str, **overrides) -> dict:
    """PRD 3.9: a claim names the payer contract it is billed under."""
    return _compose({"payer_contract_id": payer_contract_id}, overrides)


def make_adjudicate_payload(**overrides) -> dict:
    """PRD 3.9: adjudication accepts an optional adjudication note."""
    return _compose({}, overrides)


def make_dispute_case_payload(**overrides) -> dict:
    """PRD 3.9: opening a dispute accepts an optional dispute note."""
    return _compose({}, overrides)


def make_offer_payload(offer_cents: int, **overrides) -> dict:
    """PRD 3.9: one offer-submission capability, walked by two roles."""
    return _compose({"offer_cents": offer_cents}, overrides)


def make_initiate_idr_payload(**overrides) -> dict:
    """PRD 3.9: escalation names the certified entity that will decide the matter."""
    return _compose({"certified_entity_name": "Certified IDRE Alpha"}, overrides)


def make_award_payload(award_cents: int, **overrides) -> dict:
    """PRD 3.9: the award figure, bounded by what the parties themselves last said."""
    return _compose({"award_cents": award_cents}, overrides)


def make_withdraw_payload(**overrides) -> dict:
    """PRD 3.9: withdrawal requires a withdrawal reason."""
    return _compose(
        {"withdrawal_reason": "The certified entity vacated the determination."},
        overrides,
    )
