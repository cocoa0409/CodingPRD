"""Validation precedence and access control: state-before-referential and
temporal-before-fiscal precedence on the two multi-fault requests, role-based
denial, segregation of duties, and the unknown-role authentication gate.

Translates queue A (priority_pair_validation_conflict/add_property_state_beats_referential,
report_submit_temporal_beats_fiscal) and queue B (rbac denial, SoD, unauthenticated).
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, factories as f, fixtures, build_user_headers,
)
from test_helpers.test_users import (
    make_holder_headers, make_owner_headers, make_examiner_headers, make_approver_headers,
)


# ---------------------------------------------------------------------------
# Difficulty/priority_pair_validation_conflict/add_property_state_beats_referential
# ---------------------------------------------------------------------------
def _active_property_and_nv_report(api):
    """ACTIVE (never-evaluated) property with escheat_state CA + a DRAFT NV report.
    The add-property request violates both the state rule (ACTIVE not reportable) and the
    referential rule (CA != NV)."""
    holder = fixtures.create_holder(api)
    hh = make_holder_headers(holder["id"])
    pt = fixtures.create_property_type(api, code="MO02", dormancy_basis="ISSUANCE")
    prop = validate_success(api.create_property(f.create_property_payload(
        holder["id"], pt["id"], owner_last_known_state="CA", amount_cents=50000,
        last_activity_date="2020-01-01T00:00:00Z", issue_date="2020-01-01T00:00:00Z"), hh), 201)
    report = validate_success(api.create_report(f.create_report_payload(holder["id"], "NV", 2026), hh), 201)
    return hh, prop, report


def test_add_property_state_error_beats_referential(api):
    """PRD §2.12: "State validity is checked fourth: if the target resource is not in a state
    from which the requested transition is defined, the request is rejected with
    ERR_INVALID_STATE (HTTP 409). Only after these universal gates pass does the system evaluate
    the endpoint-specific business rules described in Section 3".

    The ACTIVE property fails the fourth-gate state check before the escheat-state business rule
    is reached, so the returned error is ERR_INVALID_STATE, not ERR_ESCHEAT_STATE_MISMATCH.

    Design: Difficulty/priority_pair_validation_conflict/add_property_state_beats_referential
    """
    hh, prop, report = _active_property_and_nv_report(api)
    validate_error(api.add_property(report["id"], f.add_property_payload(prop["id"], report["version"]), hh),
                   ApiErrorId.ERR_INVALID_STATE.value)


def test_add_property_state_conflict_attaches_nothing(api):
    """PRD §2.9: "If that value does not equal the report's current version, the request is
    rejected ... and no property is attached." — and equally, a request rejected at the state
    gate attaches nothing.
    PRD §3.4: "The report's property_count is simply the number of properties currently attached."

    Design: Difficulty/priority_pair_validation_conflict/add_property_state_beats_referential
    """
    hh, prop, report = _active_property_and_nv_report(api)
    validate_error(api.add_property(report["id"], f.add_property_payload(prop["id"], report["version"]), hh),
                   ApiErrorId.ERR_INVALID_STATE.value)
    after = validate_success(api.get_report(report["id"], hh), 200)
    assert after["property_count"] == 0


# ---------------------------------------------------------------------------
# Difficulty/priority_pair_validation_conflict/report_submit_temporal_beats_fiscal
# ---------------------------------------------------------------------------
def _report_with_incomplete_dd(api):
    """DRAFT CA report with a due-diligence property attached only 9 days after its notice
    (60-day window unmet); submitting with a wrong declared total violates both the temporal
    and the fiscal gate."""
    return fixtures.setup_draft_report_with_property(
        api, due_diligence=True, dd_min_days=60, dormancy_basis="LAST_ACTIVITY",
        interest_bearing=False, amount_cents=50000, clock="2026-05-10T00:00:00Z")


def test_submit_temporal_error_beats_fiscal(api):
    """PRD §3.4: "Second, for every attached property whose type requires due diligence, the
    elapsed time from that property's earliest due-diligence notice sent_at to the current
    logical clock, measured in days, must be at least the property type's due_diligence_min_days;
    if any such property has not completed its waiting window, submission is rejected with
    ERR_DUE_DILIGENCE_INCOMPLETE (HTTP 422). Third, the submitted declared_total_cents must equal
    the report's computed total_remitted_cents; a mismatch is rejected with
    ERR_REMITTANCE_MISMATCH (HTTP 422)."

    The due-diligence check is stated second and the remittance check third, so when both fail
    the second (temporal) error is returned.

    Design: Difficulty/priority_pair_validation_conflict/report_submit_temporal_beats_fiscal
    """
    ctx = _report_with_incomplete_dd(api)
    hh = ctx["holder_headers"]
    validate_error(api.submit_report(ctx["report_id"], {"declared_total_cents": 999}, hh),
                   ApiErrorId.ERR_DUE_DILIGENCE_INCOMPLETE.value)


def test_submit_temporal_conflict_leaves_report_draft(api):
    """PRD §3.4: "Submitting a report moves it from DRAFT to SUBMITTED and stamps submitted_at
    with the current logical-clock instant." — a rejected submit performs no such transition.
    PRD §3.4: "if any such property has not completed its waiting window, submission is rejected
    with ERR_DUE_DILIGENCE_INCOMPLETE (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/report_submit_temporal_beats_fiscal
    """
    ctx = _report_with_incomplete_dd(api)
    hh = ctx["holder_headers"]
    validate_error(api.submit_report(ctx["report_id"], {"declared_total_cents": 999}, hh),
                   ApiErrorId.ERR_DUE_DILIGENCE_INCOMPLETE.value)
    after = validate_success(api.get_report(ctx["report_id"], hh), 200)
    assert after["status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Corner/rbac/owner_cannot_examine_claim
# ---------------------------------------------------------------------------
def test_owner_cannot_examine_claim(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not permitted to
    invoke the requested operation, the request is rejected with ERR_UNAUTHORIZED (HTTP 403)."
    PRD §4: POST /claims/{id}/examine is authorized for StateExaminer only.

    An Owner calling examine is rejected; the claim stays FILED.

    Design: Corner/rbac/owner_cannot_examine_claim
    """
    ctx = fixtures.escheat_property(api, amount_cents=50000, interest_bearing=False,
                                    dormancy_basis="ISSUANCE", pt_code="MO02",
                                    clock="2026-07-15T00:00:00Z")
    owner = fixtures.create_owner(api)
    oh = make_owner_headers(owner["id"])
    claim = validate_success(api.create_claim(
        f.create_claim_payload(ctx["property"]["id"], owner["id"], "OWNER"), oh), 201)
    validate_error(api.examine_claim(claim["id"], oh), ApiErrorId.ERR_UNAUTHORIZED.value)
    after = validate_success(api.get_claim(claim["id"], make_examiner_headers()), 200)
    assert after["status"] == "FILED"


# ---------------------------------------------------------------------------
# Corner/rbac/examiner_cannot_approve_own_examined_claim_sod
# ---------------------------------------------------------------------------
def test_approver_equal_to_examiner_rejected_sod(api):
    """PRD §2.10: "Later, when a StateApprover approves or pays that claim, the acting operator's
    X-User-ID must differ from the recorded examiner_user_id. If they are equal, the operation is
    rejected with ERR_SOD_VIOLATION (HTTP 403)."

    A claim examined by operator 'shared-1' cannot be approved by 'shared-1'; it stays UNDER_REVIEW.

    Design: Corner/rbac/examiner_cannot_approve_own_examined_claim_sod
    """
    ctx = fixtures.escheat_property(api, amount_cents=50000, interest_bearing=False,
                                    dormancy_basis="ISSUANCE", pt_code="MO02",
                                    clock="2026-07-15T00:00:00Z")
    owner = fixtures.create_owner(api)
    oh = make_owner_headers(owner["id"])
    claim = validate_success(api.create_claim(
        f.create_claim_payload(ctx["property"]["id"], owner["id"], "OWNER"), oh), 201)
    validate_success(api.examine_claim(claim["id"], make_examiner_headers("shared-1")), 200)
    validate_error(api.approve_claim(claim["id"], make_approver_headers("shared-1")),
                   ApiErrorId.ERR_SOD_VIOLATION.value)
    after = validate_success(api.get_claim(claim["id"], make_examiner_headers()), 200)
    assert after["status"] == "UNDER_REVIEW"


# ---------------------------------------------------------------------------
# Corner/rbac/missing_auth_headers_returns_unauthenticated
# ---------------------------------------------------------------------------
def test_unknown_role_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or presenting an X-User-Role that is not one
    of the recognized roles, is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    nobody = build_user_headers("nobody-1", "Nobody")
    validate_error(api.create_holder(f.create_holder_payload(), nobody),
                   ApiErrorId.ERR_UNAUTHENTICATED.value)
