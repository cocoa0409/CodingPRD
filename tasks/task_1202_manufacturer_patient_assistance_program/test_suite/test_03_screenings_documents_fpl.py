"""Eligibility screening: schema validation, document gates, FPL computation,
the revision loop, and the staleness sweep (PRD §2.5, §3.2, §3.8)."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_document,
    assert_screening,
    create_patient_payload,
    create_screening_payload,
    fixtures as fx,
    make_case_worker_headers,
    make_patient_headers,
    make_prescriber_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def _program_and_patient(**kwargs):
    ctx = fx.setup_program_with_period(**kwargs)
    patient = fx.create_patient_record()
    return ctx, patient


def test_patient_missing_state_code_returns_400():
    """PRD §3.2: "A `CaseWorker` or `ProgramAdministrator` registers a **Patient**
    with `full_name`, `date_of_birth`, and a two-letter `state_code`"
    PRD §2.7: "Required fields present, types match, enum values valid, date
    ranges sane" ... "(`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/patient_creation_missing_required_returns_400
    """
    payload = {"full_name": "No State", "date_of_birth": "1990-01-01"}
    resp = api_client.create_patient(payload, fx.CW)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_ytd_basis_missing_months_returns_400():
    """PRD §3.2: "the income evidence matching the basis: `ytd_income_cents`
    together with `ytd_months_elapsed` (1 through 12) when the basis is
    `YTD_ANNUALIZED`, or `prior_year_income_cents` when the basis is
    `PRIOR_YEAR`." and "Supplying a conditional field for the wrong basis or
    status, or omitting one that applies, fails schema validation as
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/screening_conditional_input_missing_returns_400
    """
    ctx, patient = _program_and_patient()
    payload = create_screening_payload(
        patient["id"], ctx["program"]["id"],
        income_basis="YTD_ANNUALIZED", ytd_income_cents=2000000)
    payload.pop("prior_year_income_cents", None)
    payload.pop("ytd_months_elapsed", None)
    resp = api_client.create_screening(payload, make_patient_headers(patient["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_invalid_insurance_status_returns_400():
    """PRD §3.2: "an `insurance_status` of `UNINSURED`, `UNDERINSURED`,
    `INSURED_COMMERCIAL`, `MEDICARE`, or `MEDICAID`"
    PRD §2.7: "Required fields present, types match, enum values valid, date
    ranges sane" ... "(`ERR_INVALID_REQUEST`)."

    Design: Corner/validations/screening_invalid_enum_returns_400
    """
    ctx, patient = _program_and_patient()
    payload = create_screening_payload(patient["id"], ctx["program"]["id"],
                                       insurance_status="PARTIAL")
    resp = api_client.create_screening(payload, make_patient_headers(patient["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_verify_draft_screening_rejected():
    """PRD §3.2: "Verifying a screening requires it to be `SUBMITTED` (otherwise
    `ERR_SCREENING_NOT_SUBMITTED`)"

    Design: Corner/state_machines/screening_verify_from_draft_rejected
    """
    ctx, patient = _program_and_patient()
    screening = fx.create_screening_record(patient["id"], ctx["program"]["id"])
    resp = api_client.decide_screening(screening["id"], {"decision": "VERIFIED"}, fx.CW)
    validate_error(resp, ApiErrorId.ERR_SCREENING_NOT_SUBMITTED, expected_status=409)
    current = validate_success(api_client.get_screening(screening["id"], fx.CW))
    assert current["status"] == "DRAFT"


def test_submit_without_identity_document_rejected():
    """PRD §3.2: "the required documentary evidence is present: at least one
    uploaded document of type `PROOF_OF_INCOME` and at least one of type
    `IDENTITY` in every case, plus at least one of type `INSURANCE_VERIFICATION`
    whenever the insurance status is anything other than `UNINSURED`. A
    submission lacking any required document type is rejected with
    `ERR_DOCUMENTS_INCOMPLETE`."

    Design: Corner/state_machines/screening_submit_incomplete_docs_rejected
    """
    ctx, patient = _program_and_patient()
    screening = fx.create_screening_record(patient["id"], ctx["program"]["id"])
    fx.upload_document_record(screening["id"], patient["id"], "PROOF_OF_INCOME")
    resp = api_client.submit_screening(screening["id"], make_patient_headers(patient["id"]))
    validate_error(resp, ApiErrorId.ERR_DOCUMENTS_INCOMPLETE, expected_status=409)
    current = validate_success(api_client.get_screening(screening["id"], fx.CW))
    assert current["status"] == "DRAFT"


def test_verify_with_pending_document_rejected():
    """PRD §3.2: "requires every uploaded document to be `ACCEPTED` (otherwise
    `ERR_DOCUMENTS_NOT_ACCEPTED` — documents themselves are reviewed individually
    from `PENDING` to `ACCEPTED` or `REJECTED` by a `CaseWorker`, with a
    non-`PENDING` document rejected as `ERR_DOCUMENT_NOT_PENDING` and an optional
    `review_note` stored when supplied)"

    Design: Corner/state_machines/screening_verify_with_pending_doc_rejected
    """
    ctx, patient = _program_and_patient()
    screening = fx.create_screening_record(patient["id"], ctx["program"]["id"])
    poi = fx.upload_document_record(screening["id"], patient["id"], "PROOF_OF_INCOME")
    fx.upload_document_record(screening["id"], patient["id"], "IDENTITY")
    fx.accept_document(poi["id"])
    fx.submit_screening_record(screening["id"], patient["id"])
    resp = api_client.decide_screening(screening["id"], {"decision": "VERIFIED"}, fx.CW)
    validate_error(resp, ApiErrorId.ERR_DOCUMENTS_NOT_ACCEPTED, expected_status=409)
    current = validate_success(api_client.get_screening(screening["id"], fx.CW))
    assert current["status"] == "SUBMITTED"


def _dual_basis_screenings():
    """One patient with two SUBMITTED screenings for the same program:
    YTD_ANNUALIZED 2000000 over 4 months and PRIOR_YEAR 6300000."""
    ctx, patient = _program_and_patient()
    scr_ytd = fx.setup_submitted_screening(
        patient["id"], ctx["program"]["id"],
        income_basis="YTD_ANNUALIZED", ytd_income_cents=2000000,
        ytd_months_elapsed=4, insurance_status="UNINSURED")
    scr_py = fx.setup_submitted_screening(
        patient["id"], ctx["program"]["id"],
        income_basis="PRIOR_YEAR", prior_year_income_cents=6300000,
        insurance_status="UNINSURED")
    return ctx, patient, scr_ytd, scr_py


def test_ytd_basis_projects_annualized_run_rate():
    """PRD §3.2: "under `YTD_ANNUALIZED`, the year-to-date income is divided by
    the months elapsed, multiplied by 12, and rounded half up to whole cents — a
    projection that makes a mid-year raise produce a higher annualized figure
    than the prior-year tax return for the same patient; under `PRIOR_YEAR`, the
    filed prior-year total is used verbatim with no projection, so identical
    household data can be eligible under one basis and ineligible under the
    other."

    Design: Difficulty/dual_variant_calc/income_basis_variant_divergence
    """
    _, _, scr_ytd, _ = _dual_basis_screenings()
    assert scr_ytd["annualized_income_cents"] == 6000000, "2000000 / 4 months x 12"
    assert scr_ytd["fpl_percent"] == "383.39", "6000000 x 100 / 1565000 rounded half up"
    decided = validate_success(api_client.decide_screening(
        scr_ytd["id"], {"decision": "VERIFIED"}, fx.CW))
    assert decided["status"] == "VERIFIED", "383.39 <= 400.00 inclusive threshold"


def test_prior_year_basis_can_diverge_to_ineligible():
    """PRD §3.2: "under `PRIOR_YEAR`, the filed prior-year total is used verbatim
    with no projection, so identical household data can be eligible under one
    basis and ineligible under the other." and "requires the computed
    determination to be `ELIGIBLE` (otherwise `ERR_PATIENT_INELIGIBLE`,
    HTTP 422)."

    Design: Difficulty/dual_variant_calc/income_basis_variant_divergence
    """
    _, _, _, scr_py = _dual_basis_screenings()
    assert scr_py["fpl_percent"] == "402.56", "6300000 x 100 / 1565000 rounded half up"
    resp = api_client.decide_screening(scr_py["id"], {"decision": "VERIFIED"}, fx.CW)
    validate_error(resp, ApiErrorId.ERR_PATIENT_INELIGIBLE, expected_status=422)


def _boundary_screening(income_cents):
    ctx, patient = _program_and_patient()
    return fx.setup_submitted_screening(
        patient["id"], ctx["program"]["id"],
        income_basis="PRIOR_YEAR", prior_year_income_cents=income_cents,
        insurance_status="UNINSURED")


def test_fpl_exactly_400_is_eligible():
    """PRD §3.2: "an `UNINSURED` patient is `ELIGIBLE` if and only if
    `fpl_percent` is at most 400.00, inclusive" and "The `fpl_percent` is the
    annualized income multiplied by 100, divided by `fpl_limit_cents`, and
    rounded half up to two decimal places."

    Design: Difficulty/boundary_precision_check/fpl_exactly_400_eligible_boundary
    """
    screening = _boundary_screening(6260000)
    assert screening["fpl_percent"] == "400.00", "6260000 x 100 / 1565000 is exactly 400.00"
    decided = validate_success(api_client.decide_screening(
        screening["id"], {"decision": "VERIFIED"}, fx.CW))
    assert decided["status"] == "VERIFIED", "the 400.00 boundary is inclusive"
    assert decided["eligibility_determination"] == "ELIGIBLE"


def test_fpl_just_above_400_is_ineligible():
    """PRD §3.2: "an `UNINSURED` patient is `ELIGIBLE` if and only if
    `fpl_percent` is at most 400.00, inclusive" and "requires the computed
    determination to be `ELIGIBLE` (otherwise `ERR_PATIENT_INELIGIBLE`,
    HTTP 422)."

    Design: Difficulty/boundary_precision_check/fpl_exactly_400_eligible_boundary
    """
    screening = _boundary_screening(6261000)
    assert screening["fpl_percent"] == "400.06", "6261000 x 100 / 1565000 rounds to 400.06"
    resp = api_client.decide_screening(screening["id"], {"decision": "VERIFIED"}, fx.CW)
    validate_error(resp, ApiErrorId.ERR_PATIENT_INELIGIBLE, expected_status=422)


def test_fpl_household_four_at_500_boundary():
    """PRD §3.2: "The Federal Poverty Level limit for the household,
    `fpl_limit_cents`, is 1,565,000 cents (the base figure for a household of
    one) plus 550,000 cents for each additional household member beyond the
    first." and "an `UNDERINSURED` patient is `ELIGIBLE` if and only if
    `fpl_percent` is at most 500.00, inclusive, and `insurance_coverage_pct` is
    below `'1.00'`"

    Design: Corner/calculations/fpl_household4_constants_applied
    """
    ctx, patient = _program_and_patient()
    screening = fx.setup_submitted_screening(
        patient["id"], ctx["program"]["id"],
        household_size=4, income_basis="PRIOR_YEAR",
        prior_year_income_cents=16075000, insurance_status="UNDERINSURED",
        insurance_coverage_pct="0.60")
    assert screening["fpl_limit_cents"] == 3215000, "1565000 + 3 x 550000"
    assert screening["fpl_percent"] == "500.00", "16075000 x 100 / 3215000 is exactly 500.00"
    decided = validate_success(api_client.decide_screening(
        screening["id"], {"decision": "VERIFIED"}, fx.CW))
    assert decided["status"] == "VERIFIED", "500.00 <= 500.00 inclusive for UNDERINSURED"


def test_fpl_limit_scales_with_household_size():
    """PRD §3.2: "The Federal Poverty Level limit for the household,
    `fpl_limit_cents`, is 1,565,000 cents (the base figure for a household of
    one) plus 550,000 cents for each additional household member beyond the
    first." and "The `fpl_percent` is the annualized income multiplied by 100,
    divided by `fpl_limit_cents`, and rounded half up to two decimal places."

    Design: Difficulty/combinatorial_formula/benefit_cap_nested_min_conditional
    """
    ctx, patient = _program_and_patient()
    screening = fx.setup_verified_screening(
        patient["id"], ctx["program"]["id"],
        household_size=4, income_basis="PRIOR_YEAR",
        prior_year_income_cents=8000000, insurance_status="UNDERINSURED",
        insurance_coverage_pct="0.60")
    assert_screening(screening)
    assert screening["fpl_limit_cents"] == 3215000
    assert screening["fpl_percent"] == "248.83", "8000000 x 100 / 3215000 rounds to 248.83"


def test_benefit_cap_scales_by_underinsured_coverage():
    """PRD §3.3: "the base cap is the smaller of `max_annual_benefit_cents` and
    that product axis; and, when the backing screening's insurance status is
    `UNDERINSURED`, the base cap is multiplied by one minus the screening's
    `insurance_coverage_pct` and rounded half up to whole cents — otherwise the
    base cap stands unchanged."

    Design: Difficulty/combinatorial_formula/benefit_cap_nested_min_conditional
    """
    ctx = fx.setup_under_review_application(
        screening_overrides={
            "household_size": 4, "income_basis": "PRIOR_YEAR",
            "prior_year_income_cents": 8000000, "insurance_status": "UNDERINSURED",
            "insurance_coverage_pct": "0.60"})
    decided = validate_success(api_client.decide_application(
        ctx["application"]["id"], {"decision": "APPROVED"},
        make_case_worker_headers(ctx["reviewer"])))
    enrollment = validate_success(api_client.get_enrollment(decided["enrollment_id"], fx.CW))
    assert enrollment["benefit_cap_cents"] == 360000, (
        "min(900000, 100 x 10000) x (1 - 0.60) = 360000")


def test_revision_cycle_status_sequence():
    """PRD §3.2: "the owning patient may return a `REJECTED` screening to `DRAFT`
    through the revision loop — any other source state is rejected with
    `ERR_SCREENING_NOT_REJECTED`."

    Design: Difficulty/non_linear_state_machine/screening_revision_cycle
    """
    ctx, patient = _program_and_patient()
    screening = fx.setup_submitted_screening(patient["id"], ctx["program"]["id"])
    rejected = validate_success(api_client.decide_screening(
        screening["id"], {"decision": "REJECTED",
                          "rejection_reason": "income documentation blurry"}, fx.CW))
    assert rejected["status"] == "REJECTED"

    back_to_draft = validate_success(api_client.revise_screening(
        screening["id"], make_patient_headers(patient["id"])))
    assert back_to_draft["status"] == "DRAFT", "the cycle edge returns to DRAFT"

    resubmitted = validate_success(api_client.submit_screening(
        screening["id"], make_patient_headers(patient["id"])))
    assert resubmitted["status"] == "SUBMITTED"

    verified = validate_success(api_client.decide_screening(
        screening["id"], {"decision": "VERIFIED"}, fx.CW))
    assert verified["status"] == "VERIFIED"
    assert verified["eligibility_determination"] == "ELIGIBLE"


def test_revision_cycle_retains_documents():
    """PRD §3.2: "Revision clears `verified_at` but retains previously uploaded
    documents with their statuses, letting the patient replace only what failed
    and resubmit."

    Design: Difficulty/non_linear_state_machine/screening_revision_cycle
    """
    ctx, patient = _program_and_patient()
    screening = fx.setup_submitted_screening(patient["id"], ctx["program"]["id"])
    validate_success(api_client.decide_screening(
        screening["id"], {"decision": "REJECTED", "rejection_reason": "blurry scans"}, fx.CW))
    validate_success(api_client.revise_screening(
        screening["id"], make_patient_headers(patient["id"])))

    docs, meta = validate_paginated(api_client.list_screening_documents(screening["id"], fx.CW))
    assert meta["total_count"] == 2, "both previously uploaded documents survive the cycle"
    for doc in docs:
        assert_document(doc)
        assert doc["status"] == "ACCEPTED", "documents retain their ACCEPTED status"

    resubmitted = validate_success(api_client.submit_screening(
        screening["id"], make_patient_headers(patient["id"])))
    assert resubmitted["status"] == "SUBMITTED", (
        "resubmit succeeds with no new uploads — the retained documents satisfy the gate")


def test_screening_stale_sweep_boundary():
    """PRD §2.5: "A screening remains usable while today is on or before the
    verified date plus the program's `screening_validity_days`."
    PRD §3.8: "First, every `VERIFIED` screening whose validity date has passed —
    today strictly after the `verified_at` date plus `screening_validity_days` —
    becomes `STALE`."

    Design: Corner/state_machines/screening_stale_sweep
    """
    ctx, patient = _program_and_patient()
    screening = fx.setup_verified_screening(patient["id"], ctx["program"]["id"])

    fx.set_clock("2026-07-30T00:00:00Z")  # verified 2026-05-01 + 90 days: last usable day
    sweep_30 = fx.run_sweep()
    assert screening["id"] not in sweep_30["staled_screening_ids"], (
        "on the inclusive last valid day the screening is not staled")
    current = validate_success(api_client.get_screening(screening["id"], fx.CW))
    assert current["status"] == "VERIFIED"

    fx.set_clock("2026-07-31T00:00:00Z")
    sweep_31 = fx.run_sweep()
    assert screening["id"] in sweep_31["staled_screening_ids"]
    current = validate_success(api_client.get_screening(screening["id"], fx.CW))
    assert current["status"] == "STALE"


def test_stale_screening_blocks_application():
    """PRD §3.3: "The screening must be `VERIFIED` (`ERR_SCREENING_NOT_VERIFIED`
    otherwise) and still within its validity window (`ERR_SCREENING_STALE`
    otherwise)."

    Design: Corner/validations/stale_screening_blocks_application_solo
    """
    ctx, patient = _program_and_patient()
    screening = fx.setup_verified_screening(patient["id"], ctx["program"]["id"])
    fx.set_clock("2026-08-01T00:00:00Z")  # past verified 2026-05-01 + 90 days; no sweep run
    stored = validate_success(api_client.get_screening(screening["id"], fx.CW))
    assert stored["status"] == "VERIFIED", "without a sweep the stored status is untouched"

    resp = api_client.create_application(
        {"patient_id": patient["id"], "program_id": ctx["program"]["id"],
         "screening_id": screening["id"]},
        make_patient_headers(patient["id"]))
    validate_error(resp, ApiErrorId.ERR_SCREENING_STALE, expected_status=409)


def test_prescriber_cannot_decide_screening():
    """PRD §3.2: "A `CaseWorker` then renders the verification decision."
    PRD §2.1: "A request whose role is valid but not permitted on the target
    endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/validations/prescriber_cannot_decide_screening
    """
    ctx, patient = _program_and_patient()
    prescriber = fx.create_prescriber_record(full_name="Dr. Pam Pell", npi_number="1234567890")
    screening = fx.setup_submitted_screening(patient["id"], ctx["program"]["id"])
    resp = api_client.decide_screening(
        screening["id"], {"decision": "VERIFIED"}, make_prescriber_headers(prescriber["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
    current = validate_success(api_client.get_screening(screening["id"], fx.CW))
    assert current["status"] == "SUBMITTED"


def test_patient_cannot_review_documents():
    """PRD §3.2: "documents themselves are reviewed individually from `PENDING`
    to `ACCEPTED` or `REJECTED` by a `CaseWorker`"
    PRD §2.1: "A request whose role is valid but not permitted on the target
    endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/validations/patient_cannot_review_documents
    """
    ctx, patient = _program_and_patient()
    screening = fx.create_screening_record(patient["id"], ctx["program"]["id"])
    doc = fx.upload_document_record(screening["id"], patient["id"], "PROOF_OF_INCOME")
    resp = api_client.review_document(
        doc["id"], {"decision": "ACCEPTED"}, make_patient_headers(patient["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
    docs, _meta = validate_paginated(api_client.list_screening_documents(screening["id"], fx.CW))
    assert docs[0]["status"] == "PENDING", "the rejected review leaves the document PENDING"
