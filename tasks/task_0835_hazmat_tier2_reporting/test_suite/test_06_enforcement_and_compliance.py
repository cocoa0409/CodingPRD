"""Enforcement cascades, cross-entity gating, validation precedence, and case lifecycle."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    create_permit_payload,
    make_regulator_headers,
    make_facility_operator_headers,
    register_facility,
    issue_permit,
    create_ehs_chemical,
    report_release,
    declare_inventory,
    upload_sds,
    create_draft_filing,
    get_facility,
    find_facility_cases,
    find_facility_permits,
    open_manual_case,
    open_case_in_review,
    create_completed_inspection,
    setup_facility_with_draft_filing,
    setup_submitted_filing,
    setup_under_review_filing,
    api_client,
)


def _rq_case(fac_id):
    cases = find_facility_cases(fac_id)
    matches = [c for c in cases if c["origin"] == "RELEASE_RQ_EXCEEDED"]
    assert matches, "expected an auto-opened RELEASE_RQ_EXCEEDED case"
    return matches[0]


def _setup_release_cascade():
    facility = register_facility()
    fac_id = facility["id"]
    permit = issue_permit(fac_id, permit_type="OPERATING",
                          issued_date="2026-01-01T00:00:00Z", expiry_date="2027-01-01T00:00:00Z")
    chemical = create_ehs_chemical(rq_lbs=50, tpq_lbs=500)
    release = report_release(fac_id, chemical["id"], release_datetime="2026-02-15T00:00:00Z",
                             quantity_released_lbs=100, medium="AIR")
    return facility, permit, chemical, release


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / release_rq_to_case_to_enforcement_to_permit_suspend
# ---------------------------------------------------------------------------
def test_rq_release_forces_enforcement_and_opens_high_case(api):
    """PRD §3.5: "First, a compliance case is opened with `origin`
    `RELEASE_RQ_EXCEEDED`, `severity` `HIGH`, and `origin_ref` set to this release's
    `id`, and the release's `origin_case_opened` flag is set to `true`. Second,
    because that new case is a `HIGH`-severity case, the facility's
    `compliance_posture` is forced to `ENFORCEMENT`."

    Design: Difficulty/transitive_cascade/release_rq_to_case_to_enforcement_to_permit_suspend
    """
    facility, permit, chemical, release = _setup_release_cascade()
    fac_id = facility["id"]
    facility_read = get_facility(fac_id)
    assert facility_read["compliance_posture"] == "ENFORCEMENT"
    case = _rq_case(fac_id)
    assert case["origin"] == "RELEASE_RQ_EXCEEDED"
    assert case["severity"] == "HIGH"


def test_rq_release_suspends_active_permits(api):
    """PRD §3.5: "Third, because the facility has entered `ENFORCEMENT`, every one of
    its permits currently in `ACTIVE` status is moved to `SUSPENDED`."
    PRD §3.5: "`exceeds_rq` is set to `true` exactly when `quantity_released_lbs`
    reaches or exceeds the chemical's `rq_lbs`."

    Design: Difficulty/transitive_cascade/release_rq_to_case_to_enforcement_to_permit_suspend
    """
    facility, permit, chemical, release = _setup_release_cascade()
    fac_id = facility["id"]
    assert release["exceeds_rq"] is True
    permits = find_facility_permits(fac_id)
    suspended = [p for p in permits if p["id"] == permit["id"]]
    assert suspended and suspended[0]["status"] == "SUSPENDED"


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / inspection_fail_to_case_to_deficient
# ---------------------------------------------------------------------------
def test_failed_inspection_opens_medium_case(api):
    """PRD §3.6: "A `result` of `FAIL` moves the inspection to `FAILED`, sets its
    `result` to `FAIL`, and records `findings_count` from the supplied
    `findings_count` in the payload; it then opens a compliance case with `origin`
    `INSPECTION_FAILED`, `severity` `MEDIUM`, and `origin_ref` set to this
    inspection's `id`, and forces the facility's `compliance_posture` to `DEFICIENT`
    unless the facility is already in `ENFORCEMENT`."

    Design: Difficulty/transitive_cascade/inspection_fail_to_case_to_deficient
    """
    facility = register_facility()
    fac_id = facility["id"]
    insp = create_completed_inspection(fac_id, result="FAIL", findings_count=3,
                                       inspector_id="INSP-9", scheduled_date="2026-04-01T09:00:00Z")
    assert insp["status"] == "FAILED"
    cases = find_facility_cases(fac_id)
    matches = [c for c in cases if c["origin"] == "INSPECTION_FAILED"]
    assert matches, "expected an auto-opened INSPECTION_FAILED case"
    assert matches[0]["severity"] == "MEDIUM"


def test_failed_inspection_sets_posture_deficient(api):
    """PRD §3.6: "it then opens a compliance case with `origin` `INSPECTION_FAILED`,
    `severity` `MEDIUM`, and `origin_ref` set to this inspection's `id`, and forces
    the facility's `compliance_posture` to `DEFICIENT` unless the facility is already
    in `ENFORCEMENT`."

    Design: Difficulty/transitive_cascade/inspection_fail_to_case_to_deficient
    """
    facility = register_facility()
    fac_id = facility["id"]
    create_completed_inspection(fac_id, result="FAIL", findings_count=3,
                                inspector_id="INSP-9", scheduled_date="2026-04-01T09:00:00Z")
    facility_read = get_facility(fac_id)
    assert facility_read["compliance_posture"] == "DEFICIENT"


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / case_resolve_state_beats_business_constraint
# ---------------------------------------------------------------------------
def test_resolve_open_case_returns_state_error_over_inspection(api):
    """PRD §2.9: "then the state-transition check that the target resource is in a
    state permitting the requested action (the `ERR_*_NOT_*` and
    `ERR_RELEASE_INVALID_STAGE` family, HTTP 409). Business-safety, referential,
    temporal, cross-entity, and fiscal checks described in §3 run after those
    structural checks."

    Design: Difficulty/priority_pair_validation_conflict/case_resolve_state_beats_business_constraint
    """
    facility = register_facility()
    fac_id = facility["id"]
    case = open_manual_case(fac_id, severity="LOW")  # OPEN, never moved to UNDER_REVIEW
    create_completed_inspection(fac_id, result="FAIL", findings_count=2,
                                inspector_id="INSP-3", scheduled_date="2026-04-10T09:00:00Z")
    resp = api.resolve_compliance_case(case["id"], {"penalty_cents": 0}, make_regulator_headers())
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_UNDER_REVIEW.value)


def test_resolve_open_case_state_check_preempts_cross_entity(api):
    """PRD §2.9: "then the state-transition check that the target resource is in a
    state permitting the requested action (the `ERR_*_NOT_*` and
    `ERR_RELEASE_INVALID_STAGE` family, HTTP 409). Business-safety, referential,
    temporal, cross-entity, and fiscal checks described in §3 run after those
    structural checks."

    Design: Difficulty/priority_pair_validation_conflict/case_resolve_state_beats_business_constraint
    """
    facility = register_facility()
    fac_id = facility["id"]
    case = open_manual_case(fac_id, severity="LOW")
    create_completed_inspection(fac_id, result="FAIL", findings_count=2,
                                inspector_id="INSP-3", scheduled_date="2026-04-10T09:00:00Z")
    resp = api.resolve_compliance_case(case["id"], {"penalty_cents": 0}, make_regulator_headers())
    error_data = validate_error(resp, ApiErrorId.ERR_CASE_NOT_UNDER_REVIEW.value)
    # The structural state check pre-empts the cross-entity inspection check.
    assert error_data["error_id"] != ApiErrorId.ERR_UNRESOLVED_INSPECTION.value


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / permit_issue_temporal_beats_fiscal
# ---------------------------------------------------------------------------
def _setup_overlap_and_outstanding():
    facility = register_facility()
    fac_id = facility["id"]
    # Issue the first permit while the facility still owes nothing.
    issue_permit(fac_id, permit_type="OPERATING",
                 issued_date="2026-01-01T00:00:00Z", expiry_date="2027-01-01T00:00:00Z")
    chemical = create_ehs_chemical(rq_lbs=5000, tpq_lbs=100)
    declare_inventory(fac_id, chemical["id"], reporting_year=2025, max_daily_amount_lbs=200,
                      average_daily_amount_lbs=150, days_on_site=300, storage_type="CYLINDER")
    upload_sds(fac_id, chemical["id"], facility["version"])
    filing = create_draft_filing(fac_id, reporting_year=2025)
    get_success_data(api_client.submit_tier_ii_filing(filing["id"], make_facility_operator_headers(fac_id)))
    return facility


def test_permit_overlap_reported_over_outstanding_fees(api):
    """PRD §2.9: "Business-safety, referential, temporal, cross-entity, and fiscal
    checks described in §3 run after those structural checks."
    PRD §3.6: "it may not overlap the interval of an existing permit of the same
    `permit_type` on the same facility; an overlap is rejected with
    `ERR_PERMIT_PERIOD_OVERLAP`."

    Design: Difficulty/priority_pair_validation_conflict/permit_issue_temporal_beats_fiscal
    """
    facility = _setup_overlap_and_outstanding()
    fac_id = facility["id"]
    payload = create_permit_payload(
        fac_id, permit_type="OPERATING",
        issued_date="2026-06-01T00:00:00Z", expiry_date="2026-12-01T00:00:00Z",
    )
    resp = api.create_permit(payload, make_regulator_headers())
    validate_error(resp, ApiErrorId.ERR_PERMIT_PERIOD_OVERLAP.value)


def test_permit_temporal_check_preempts_fiscal_check(api):
    """PRD §2.9: "Business-safety, referential, temporal, cross-entity, and fiscal
    checks described in §3 run after those structural checks."
    PRD §3.6: "a permit may be issued only when the facility owes nothing: if the
    facility's `total_outstanding_fee_cents` is greater than zero, issuance is blocked
    with `ERR_OUTSTANDING_FEES` (HTTP 402)."

    Design: Difficulty/priority_pair_validation_conflict/permit_issue_temporal_beats_fiscal
    """
    facility = _setup_overlap_and_outstanding()
    fac_id = facility["id"]
    payload = create_permit_payload(
        fac_id, permit_type="OPERATING",
        issued_date="2026-06-01T00:00:00Z", expiry_date="2026-12-01T00:00:00Z",
    )
    resp = api.create_permit(payload, make_regulator_headers())
    error_data = validate_error(resp, ApiErrorId.ERR_PERMIT_PERIOD_OVERLAP.value)
    # Temporal overlap is reported ahead of the fiscal outstanding-fees check.
    assert error_data["error_id"] != ApiErrorId.ERR_OUTSTANDING_FEES.value


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / filing_submit_depends_on_facility_posture
# ---------------------------------------------------------------------------
def test_submit_blocked_while_facility_under_enforcement(api):
    """PRD §3.4: "Fourth, the facility must not be under enforcement — if its
    `compliance_posture` is `ENFORCEMENT`, the submission is rejected with
    `ERR_FACILITY_UNDER_ENFORCEMENT`."

    Design: Difficulty/cross_entity_state_dependency/filing_submit_depends_on_facility_posture
    """
    ctx = setup_facility_with_draft_filing(rq_lbs=10)
    fac_id = ctx["facility"]["id"]
    # An RQ-exceeding release drives the facility into ENFORCEMENT before submit.
    report_release(fac_id, ctx["chemical"]["id"], release_datetime="2026-02-20T00:00:00Z",
                   quantity_released_lbs=100, medium="AIR")
    resp = api.submit_tier_ii_filing(ctx["filing"]["id"], make_facility_operator_headers(fac_id))
    validate_error(resp, ApiErrorId.ERR_FACILITY_UNDER_ENFORCEMENT.value)


def test_submit_succeeds_when_facility_not_under_enforcement(api):
    """PRD §3.4: "Fourth, the facility must not be under enforcement — if its
    `compliance_posture` is `ENFORCEMENT`, the submission is rejected with
    `ERR_FACILITY_UNDER_ENFORCEMENT`."

    Design: Difficulty/cross_entity_state_dependency/filing_submit_depends_on_facility_posture
    """
    ctx = setup_facility_with_draft_filing(rq_lbs=10)
    fac_id = ctx["facility"]["id"]
    # No release -> posture stays COMPLIANT -> the enforcement gate does not fire.
    resp = api.submit_tier_ii_filing(ctx["filing"]["id"], make_facility_operator_headers(fac_id))
    data = validate_success(resp, expected_status=200)
    assert data["status"] == "SUBMITTED"


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / case_resolve_depends_on_inspection_passed
# ---------------------------------------------------------------------------
def test_resolve_blocked_while_latest_inspection_failed(api):
    """PRD §3.6: "A regulator resolves a case from `UNDER_REVIEW` (else
    `ERR_CASE_NOT_UNDER_REVIEW`), optionally supplying a `penalty_cents` recorded on
    the case; resolution is additionally gated on the facility's most recent
    inspection having `PASSED` — if the latest inspection is anything else,
    resolution is blocked with `ERR_UNRESOLVED_INSPECTION`."

    Design: Difficulty/cross_entity_state_dependency/case_resolve_depends_on_inspection_passed
    """
    facility = register_facility()
    fac_id = facility["id"]
    case = open_case_in_review(fac_id, severity="LOW")  # OPEN -> UNDER_REVIEW
    create_completed_inspection(fac_id, result="FAIL", findings_count=1,
                                inspector_id="INSP-4", scheduled_date="2026-04-05T09:00:00Z")
    resp = api.resolve_compliance_case(case["id"], {"penalty_cents": 5000}, make_regulator_headers())
    validate_error(resp, ApiErrorId.ERR_UNRESOLVED_INSPECTION.value)


def test_resolve_succeeds_when_latest_inspection_passed(api):
    """PRD §3.6: "resolution is additionally gated on the facility's most recent
    inspection having `PASSED` — if the latest inspection is anything else,
    resolution is blocked with `ERR_UNRESOLVED_INSPECTION`."

    Design: Difficulty/cross_entity_state_dependency/case_resolve_depends_on_inspection_passed
    """
    facility = register_facility()
    fac_id = facility["id"]
    case = open_case_in_review(fac_id, severity="LOW")
    create_completed_inspection(fac_id, result="PASS",
                                inspector_id="INSP-4", scheduled_date="2026-04-05T09:00:00Z")
    resp = api.resolve_compliance_case(case["id"], {"penalty_cents": 5000}, make_regulator_headers())
    data = validate_success(resp, expected_status=200)
    assert data["status"] == "RESOLVED"


# ---------------------------------------------------------------------------
# Corner: state_machines / case_review_twice_returns_case_not_open
# ---------------------------------------------------------------------------
def test_review_case_already_under_review_rejected(api):
    """PRD §3.6: "A regulator moves a case into review, valid only from `OPEN` (else
    `ERR_CASE_NOT_OPEN`)."

    Design: Corner/state_machines/case_review_twice_returns_case_not_open
    """
    facility = register_facility()
    fac_id = facility["id"]
    case = open_case_in_review(fac_id, severity="LOW")  # already UNDER_REVIEW
    resp = api.review_compliance_case(case["id"], make_regulator_headers())
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_OPEN.value)


# ---------------------------------------------------------------------------
# Corner: validations / permit_issue_outstanding_fees_returns_402
# ---------------------------------------------------------------------------
def test_permit_issue_blocked_by_outstanding_fees(api):
    """PRD §3.6: "a permit may be issued only when the facility owes nothing: if the
    facility's `total_outstanding_fee_cents` is greater than zero, issuance is blocked
    with `ERR_OUTSTANDING_FEES` (HTTP 402)."

    Design: Corner/validations/permit_issue_outstanding_fees_returns_402
    """
    ctx = setup_submitted_filing()
    fac_id = ctx["facility"]["id"]
    payload = create_permit_payload(
        fac_id, permit_type="STORAGE",
        issued_date="2026-01-01T00:00:00Z", expiry_date="2027-01-01T00:00:00Z", fee_cents=10000,
    )
    resp = api.create_permit(payload, make_regulator_headers())
    validate_error(resp, ApiErrorId.ERR_OUTSTANDING_FEES.value)


# ---------------------------------------------------------------------------
# Corner: cross_cutting / permit_reinstated_on_enforcement_case_resolve
# ---------------------------------------------------------------------------
def test_resolving_enforcement_case_reinstates_suspended_permit(api):
    """PRD §3.6: "Resolving a case recomputes the facility's `open_case_count` and
    `compliance_posture`; and if that recomputation takes the facility out of
    `ENFORCEMENT`, every one of its `SUSPENDED` permits is reinstated to `ACTIVE` as a
    compensating action mirroring the suspension cascade of §3.5."

    Design: Corner/cross_cutting/permit_reinstated_on_enforcement_case_resolve
    """
    facility = register_facility()
    fac_id = facility["id"]
    permit = issue_permit(fac_id, permit_type="OPERATING",
                          issued_date="2026-01-01T00:00:00Z", expiry_date="2027-01-01T00:00:00Z")
    create_completed_inspection(fac_id, result="PASS",
                                inspector_id="INSP-C9", scheduled_date="2026-02-01T09:00:00Z")
    chemical = create_ehs_chemical(rq_lbs=50, tpq_lbs=500)
    report_release(fac_id, chemical["id"], release_datetime="2026-02-20T00:00:00Z",
                   quantity_released_lbs=100, medium="AIR")  # -> ENFORCEMENT, permit SUSPENDED
    case = _rq_case(fac_id)
    validate_success(api.review_compliance_case(case["id"], make_regulator_headers()))
    validate_success(api.resolve_compliance_case(case["id"], {"penalty_cents": 5000}, make_regulator_headers()))
    facility_read = get_facility(fac_id)
    assert facility_read["compliance_posture"] == "COMPLIANT"
    permits = find_facility_permits(fac_id)
    reinstated = [p for p in permits if p["id"] == permit["id"]]
    assert reinstated and reinstated[0]["status"] == "ACTIVE"
