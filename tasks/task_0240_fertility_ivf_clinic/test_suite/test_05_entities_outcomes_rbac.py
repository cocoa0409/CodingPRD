"""Entity CRUD basics, computed medication line totals, the utilization-rate
metric (zero and non-zero), pagination, the monotonic-clock rule, and RBAC.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
)
import test_helpers.factories as f
import test_helpers.fixtures as fx
from test_helpers.constants import MISSING_FK_UUID

ADMIN = TEST_USERS["clinic_admin_headers"]
NURSE = TEST_USERS["nurse_headers"]
EMBRYO = TEST_USERS["embryologist_headers"]
BILLING = TEST_USERS["billing_specialist_headers"]
NONEXISTENT_UUID = "00000000-0000-4000-8000-000000000000"


# ===========================================================================
# Queue B — entities
# ===========================================================================
def test_create_patient_returns_201_with_defaults():
    """PRD 3.1: "Patients are registered by a `ClinicAdmin` or a `Nurse` with a
    `full_name`, a `date_of_birth` ... and an optional `insurance_package_id` ...; a
    patient begins `ACTIVE`..." PRD 2.4: "an integer `version` that begins at its initial
    value and increments by one on every mutation."

    Design: Corner/entities/create_patient_returns_201_with_all_fields
    """
    cid = fx.create_clinic(name="Ent Clinic")["id"]
    resp = api_client.create_patient(cid, f.create_patient_payload(full_name="New Pat"), ADMIN)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "ACTIVE"
    assert data["version"] == 1


def test_get_patient_nonexistent_returns_not_found():
    """PRD 2.6: "Only then is the second path identifier resolved — the patient, cycle,
    appointment, ... — each yielding its own not-found error (`ERR_PATIENT_NOT_FOUND`,
    ... ) all carrying HTTP 404."

    Design: Corner/entities/get_patient_nonexistent_returns_not_found
    """
    cid = fx.create_clinic(name="NF Clinic")["id"]
    resp = api_client.get_patient(cid, NONEXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_PATIENT_NOT_FOUND.value)


def test_create_medication_missing_required_field_rejected():
    """PRD 3.3: "Each order names the parent cycle via `treatment_cycle_id` and carries
    a `drug_name`, a `start_day_offset` and `end_day_offset` ..., a `daily_dose_units`
    (a positive integer), and a `unit_price_cents` (a non-negative per-unit cost)."
    PRD 2.6: "payload well-formedness (`ERR_VALIDATION` — missing required fields, wrong
    types, invalid enum members, or out-of-domain integers ...)."

    Design: Corner/entities/create_medication_missing_required_field_rejected
    """
    ctx = fx.setup_cycle_in_stim(name="Req Clinic", required_for=["CYCLE_START"])
    cid, cyc = ctx["clinic"]["id"], ctx["cycle"]["id"]
    payload = {
        "treatment_cycle_id": cyc, "drug_name": "Gonal-F",
        "start_day_offset": 0, "end_day_offset": 4, "unit_price_cents": 100,
    }  # daily_dose_units omitted
    resp = api_client.create_medication(cid, payload, NURSE)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_medication_line_total_computed_from_inputs():
    """PRD 3.3: "the system computes the order's `line_total_cents`: the number of days
    the order spans, multiplied by `daily_dose_units`, multiplied by `unit_price_cents`.
    The number of days is the inclusive span of the offset range — the end offset minus
    the start offset, plus one..."

    Design: Corner/entities/medication_line_total_computed_from_inputs
    """
    ctx = fx.setup_cycle_in_stim(name="Calc Clinic", required_for=["CYCLE_START"])
    cid, cyc = ctx["clinic"]["id"], ctx["cycle"]["id"]
    res = validate_success(api_client.create_medication(
        cid, f.create_medication_payload(cyc, drug_name="Gonal-F", start_day_offset=0,
                                         end_day_offset=4, daily_dose_units=300, unit_price_cents=100),
        NURSE), expected_status=201)
    assert res["line_total_cents"] == 150000


def test_create_cycle_invalid_donor_fk_returns_not_found():
    """PRD 2.6: "any foreign-key field carried in a request body must reference an
    existing in-clinic resource: `insurance_package_id`, `donor_profile_id`,
    `surrogate_profile_id`, `consent_form_id`, and `cryo_tank_id` are each resolved this
    way, and a dangling reference yields the corresponding not-found error."

    Design: Corner/entities/create_cycle_invalid_donor_fk_returns_not_found
    """
    cid = fx.create_clinic(name="FK Clinic")["id"]
    pat = fx.create_patient(cid)["id"]
    resp = api_client.create_cycle(cid, f.create_cycle_payload(pat, donor_profile_id=MISSING_FK_UUID), NURSE)
    validate_error(resp, ApiErrorId.ERR_DONOR_NOT_FOUND.value)


# ===========================================================================
# Queue A — boundary_precision_check / utilization_rate_zero_denominator_edge
# ===========================================================================
def test_utilization_rate_zero_denominator():
    """PRD 3.8: "If the cycle's `oocytes_retrieved` is zero, the rate is exactly 0.0..."

    Design: Difficulty/boundary_precision_check/utilization_rate_zero_denominator_edge
    """
    cid = fx.create_clinic(name="Zero Clinic")["id"]
    pat = fx.create_patient(cid)["id"]
    cyc = fx.create_cycle(cid, pat)["id"]
    res = validate_success(api_client.create_outcome(
        cid, f.create_outcome_payload(cyc, pregnancy_test_result="INCONCLUSIVE"), NURSE), expected_status=201)
    assert res["utilization_rate"] == 0.0


def test_utilization_rate_zero_cycle_oocytes_unchanged():
    """PRD 3.8: "At creation the report computes the cycle's `utilization_rate`, the
    fraction of retrieved oocytes that were fertilized. If the cycle's `oocytes_retrieved`
    is zero, the rate is exactly 0.0..."

    Design: Difficulty/boundary_precision_check/utilization_rate_zero_denominator_edge
    """
    cid = fx.create_clinic(name="Zero Clinic 2")["id"]
    pat = fx.create_patient(cid)["id"]
    cyc = fx.create_cycle(cid, pat)["id"]
    validate_success(api_client.create_outcome(
        cid, f.create_outcome_payload(cyc, pregnancy_test_result="INCONCLUSIVE"), NURSE), expected_status=201)
    cur = get_success_data(api_client.get_cycle(cid, cyc, NURSE))
    assert cur["oocytes_retrieved"] == 0


# ===========================================================================
# Queue B — calculations / utilization_rate_nonzero
# ===========================================================================
def test_utilization_rate_nonzero_rounded():
    """PRD 3.8: "otherwise it is the cycle's `embryos_fertilized` divided by its
    `oocytes_retrieved`, rounded half up to four decimal places."

    Design: Corner/calculations/utilization_rate_nonzero
    """
    ctx = fx.setup_cycle_in_fertilization(name="Util Clinic",
                                          required_for=["CYCLE_START", "RETRIEVAL"],
                                          oocytes_retrieved=12, embryos_fertilized=5)
    cid, cyc = ctx["clinic"]["id"], ctx["cycle"]["id"]
    res = validate_success(api_client.create_outcome(
        cid, f.create_outcome_payload(cyc, pregnancy_test_result="POSITIVE"), NURSE), expected_status=201)
    assert res["utilization_rate"] == 0.4167


# ===========================================================================
# Queue B — endpoints / list_medications_filtered_by_cycle_paginated
# ===========================================================================
def test_list_medications_filtered_by_cycle_paginated():
    """PRD 2.3: "Paginated list responses include the following fields in the `meta`
    object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/list_medications_filtered_by_cycle_paginated
    """
    ctx = fx.setup_cycle_in_stim(name="List Clinic", required_for=["CYCLE_START"])
    cid, cyc = ctx["clinic"]["id"], ctx["cycle"]["id"]
    get_success_data(api_client.create_medication(
        cid, f.create_medication_payload(cyc, drug_name="Gonal-F", start_day_offset=0,
                                         end_day_offset=4, daily_dose_units=300, unit_price_cents=100), NURSE))
    get_success_data(api_client.create_medication(
        cid, f.create_medication_payload(cyc, drug_name="Menopur", start_day_offset=0,
                                         end_day_offset=2, daily_dose_units=75, unit_price_cents=200), NURSE))
    resp = api_client.list_medications(cid, NURSE, params={"treatment_cycle_id": cyc, "limit": 10, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert len(data) == 2


# ===========================================================================
# Queue B — errors / clock_not_monotonic_rejected
# ===========================================================================
def test_clock_not_monotonic_rejected():
    """PRD 2.5: "The clock is monotonic non-decreasing: an attempt to set it to a
    timestamp earlier than the clinic's current `current_clock_utc` is rejected with
    `ERR_CLOCK_NOT_MONOTONIC`."

    Design: Corner/errors/clock_not_monotonic_rejected
    """
    cid = fx.create_clinic(name="Clock Clinic")["id"]
    fx.set_clock(cid, "2026-06-10T00:00:00.000Z")
    resp = api_client.set_clock(f.set_clock_payload(cid, "2026-06-01T00:00:00.000Z"), ADMIN)
    validate_error(resp, ApiErrorId.ERR_CLOCK_NOT_MONOTONIC.value)


# ===========================================================================
# Queue B — rbac
# ===========================================================================
def test_nurse_cannot_settle_billing():
    """PRD 2.1: "If the headers are well-formed but the declared role is not permitted to
    perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD 2.1: "`BillingSpecialist` owns the cycle's billing axis: insurance estimate,
    settlement, and write-off."

    Design: Corner/rbac/nurse_cannot_settle_billing
    """
    cid = fx.create_clinic(name="RBAC Clinic A")["id"]
    pkg = fx.create_package(cid, name="R Pkg", base_price_cents=100000, coverage_pct=0.5,
                            lifetime_coverage_cap_cents=100000)["id"]
    pat = fx.create_patient(cid, insurance_package_id=pkg)["id"]
    fx.setup_patient_with_consent(cid, pat, required_for=["CYCLE_START", "RETRIEVAL", "TRANSFER"])
    cyc = fx.create_cycle(cid, pat)["id"]
    get_success_data(api_client.start_stim(cid, cyc, NURSE))
    get_success_data(api_client.estimate_billing(cid, cyc, BILLING))
    get_success_data(api_client.retrieve(cid, cyc, {"oocytes_retrieved": 4}, NURSE))
    get_success_data(api_client.fertilize(cid, cyc, {"embryos_fertilized": 2}, EMBRYO))
    get_success_data(api_client.transfer(cid, cyc, EMBRYO))
    get_success_data(api_client.create_outcome(cid, f.create_outcome_payload(cyc), NURSE))
    get_success_data(api_client.complete_cycle(cid, cyc, NURSE))
    v = get_success_data(api_client.get_cycle(cid, cyc, NURSE))["version"]
    resp = api_client.settle_billing(cid, cyc, {"expected_cycle_version": v}, NURSE)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_embryologist_cannot_create_cycle():
    """PRD 2.1: "If the headers are well-formed but the declared role is not permitted to
    perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/embryologist_cannot_create_cycle
    """
    cid = fx.create_clinic(name="RBAC Clinic B")["id"]
    pat = fx.create_patient(cid)["id"]
    resp = api_client.create_cycle(cid, f.create_cycle_payload(pat), EMBRYO)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_missing_auth_header_rejected():
    """PRD 2.1: "If either header is missing or malformed, the request is rejected with
    `ERR_MISSING_AUTH_CONTEXT`."

    Design: Corner/rbac/missing_auth_header_rejected
    """
    cid = fx.create_clinic(name="Auth Clinic")["id"]
    resp = api_client.list_patients(cid, headers={})
    validate_error(resp, ApiErrorId.ERR_MISSING_AUTH_CONTEXT.value)
