"""Resource creation, defaults, required/typed fields, FK integrity, computed
fields, listing envelope, and ledger immutability.

Queue B (corner) — section entities.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    TEST_USERS, ApiErrorId, NON_EXISTENT_UUID,
    create_payer_payload, create_patient_payload, create_policy_payload,
    create_encounter_payload, create_charge_payload,
    create_active_policy, create_encounter, create_payer, create_patient,
    create_policy, add_charge,
    setup_partially_paid_statement, payment_payload,
)
from test_helpers import api_client as _api

REGISTRAR = TEST_USERS["registrar_headers"]
BILLING = TEST_USERS["billing_headers"]


# ---------------------------------------------------------------------------
# create_payer_returns_201_with_all_fields
# ---------------------------------------------------------------------------
def test_create_payer_applies_defaults(api):
    """PRD §3.1: "timely_filing_days, an integer between 1 and 365 defaulting to 90, is the
    number of days after discharge within which a claim must reach the payer;
    appeal_window_days, an integer between 1 and 180 defaulting to 30, is the number of days
    after a denial within which an appeal may be filed; and active, a boolean defaulting to
    true, indicates whether the payer is currently accepting new claims."

    Design: Corner/entities/create_payer_returns_201_with_all_fields
    """
    resp = api.create_payer(create_payer_payload(name="Acme Health", payer_type="COMMERCIAL"), REGISTRAR)
    data = validate_success(resp, expected_status=201)
    assert data["timely_filing_days"] == 90
    assert data["appeal_window_days"] == 30
    assert data["active"] is True


# ---------------------------------------------------------------------------
# get_patient_not_found_returns_404
# ---------------------------------------------------------------------------
def test_get_patient_not_found(api):
    """PRD §2.6: "the first identifier in the path that does not resolve to an existing
    resource yields ERR_NOT_FOUND (HTTP 404)."

    Design: Corner/entities/get_patient_not_found_returns_404
    """
    resp = api.get_patient(NON_EXISTENT_UUID, REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)


# ---------------------------------------------------------------------------
# create_insurance_policy_missing_required_field_returns_400
# ---------------------------------------------------------------------------
def test_create_policy_missing_deductible_returns_400(api):
    """PRD §2.7: "the request body itself is validated - required fields present, correct
    types, and enum values within their allowed sets - with violations yielding
    ERR_INVALID_REQUEST (400)."
    PRD §3.1: "three monetary terms: deductible_cents, the annual individual deductible the
    patient must meet before coinsurance applies (an integer of at least 0)".

    Design: Corner/entities/create_insurance_policy_missing_required_field_returns_400
    """
    payer = create_payer(active=True)
    patient = create_patient()
    payload = {
        "patient_id": patient["id"], "payer_id": payer["id"], "member_number": "M-100",
        "plan_year": 2026, "coinsurance_pct": 0.20, "oop_max_cents": 500000,
    }  # deductible_cents omitted
    resp = api.create_policy(payload, REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)


# ---------------------------------------------------------------------------
# create_insurance_policy_invalid_enum_payer_type_is_on_payer_not_policy
# ---------------------------------------------------------------------------
def test_create_payer_invalid_payer_type_enum_returns_400(api):
    """PRD §2.7: "enum values within their allowed sets - with violations yielding
    ERR_INVALID_REQUEST (400)."
    PRD §3.1: "a payer_type, which must be one of COMMERCIAL, MEDICARE, MEDICAID, or SELF_PAY."

    Design: Corner/entities/create_insurance_policy_invalid_enum_payer_type_is_on_payer_not_policy
    """
    resp = api.create_payer({"name": "Acme Health", "payer_type": "BOGUS"}, REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)


# ---------------------------------------------------------------------------
# oop_max_below_deductible_returns_422
# ---------------------------------------------------------------------------
def test_oop_max_below_deductible_returns_422(api):
    """PRD §3.1: "A coinsurance_pct outside the 0.0-1.0 range, or an oop_max_cents that is
    less than deductible_cents, is rejected with ERR_VALIDATION_OUT_OF_RANGE."

    Design: Corner/entities/oop_max_below_deductible_returns_422
    """
    payer = create_payer(active=True)
    patient = create_patient()
    payload = create_policy_payload(
        patient["id"], payer["id"], member_number="M-101",
        deductible_cents=100000, coinsurance_pct=0.20, oop_max_cents=50000,
    )
    resp = api.create_policy(payload, REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_VALIDATION_OUT_OF_RANGE.value, expected_status=422)


# ---------------------------------------------------------------------------
# charge_amount_is_computed_units_times_price_input_ignored
# ---------------------------------------------------------------------------
def test_charge_amount_is_units_times_unit_price(api):
    """PRD §3.3: "The server computes the charge's amount_cents as units multiplied by
    unit_price_cents".
    PRD §3.3: "the encounter's total_charges_cents is recomputed as the exact sum of
    amount_cents across that encounter's charges whose status is POSTED".

    units=3, unit_price_cents=5000 => amount_cents 15000; encounter total 15000.

    Design: Corner/entities/charge_amount_is_computed_units_times_price_input_ignored
    """
    payer, patient, policy = create_active_policy()
    encounter = create_encounter(patient["id"], policy["id"])
    resp = api.create_charge(
        encounter["id"], create_charge_payload(cpt_code="70450", units=3, unit_price_cents=5000),
        REGISTRAR,
    )
    data = validate_success(resp, expected_status=201)
    assert data["amount_cents"] == 15000, f"amount should be 15000, got {data['amount_cents']}"
    enc = validate_success(api.get_encounter(encounter["id"], REGISTRAR))
    assert enc["total_charges_cents"] == 15000


# ---------------------------------------------------------------------------
# encounter_patient_fk_not_found_returns_404
# ---------------------------------------------------------------------------
def test_encounter_patient_fk_not_found_returns_404(api):
    """PRD §2.6: "any foreign key supplied in a request body ... must reference an existing
    record; a body reference that does not resolve yields ERR_REFERENCE_NOT_FOUND (HTTP 404)."

    Design: Corner/entities/encounter_patient_fk_not_found_returns_404
    """
    resp = api.create_encounter(
        {"patient_id": NON_EXISTENT_UUID, "admission_at": "2026-03-01T09:00:00Z"}, REGISTRAR
    )
    validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value, expected_status=404)


# ---------------------------------------------------------------------------
# list_encounters_paginated_envelope
# ---------------------------------------------------------------------------
def test_list_encounters_paginated_envelope(api):
    """PRD §2.3: "The pagination envelope fields limit, offset, total_count, and has_more are
    reported inside meta: total_count is the count of all records matching the query before
    pagination, and has_more is true when records remain beyond the current page."

    Design: Corner/entities/list_encounters_paginated_envelope
    """
    patient = create_patient()
    create_encounter(patient["id"])
    resp = api.list_encounters(REGISTRAR, params={"limit": 10, "offset": 0})
    data, meta = validate_paginated(resp)
    assert "total_count" in meta and "has_more" in meta
    assert meta["total_count"] >= 1


# ---------------------------------------------------------------------------
# payment_immutable_no_version_field
# ---------------------------------------------------------------------------
def test_payment_has_no_version_field(api):
    """PRD §2.4: "Two resources are immutable ledger entries once written - Payment and
    WriteOff - and these carry only id and created_at; they have no updated_at and no version
    field at all."

    Design: Corner/entities/payment_immutable_no_version_field
    """
    payer, patient, policy, encounter, coding, claim, statement = setup_partially_paid_statement(
        allowed_amount_cents=200000, deductible_cents=100000, coinsurance_pct=0.20, oop_max_cents=500000,
    )
    resp = api.post_payment(statement["id"], payment_payload(50000), BILLING)
    data = validate_success(resp, expected_status=201)
    assert "id" in data and "created_at" in data
    assert "version" not in data, "Payment must not carry a version field"
    assert "updated_at" not in data, "Payment must not carry an updated_at field"
