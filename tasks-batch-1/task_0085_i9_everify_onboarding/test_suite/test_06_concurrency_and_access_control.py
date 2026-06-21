"""Optimistic concurrency on onboarding mutations, role-based access control,
segregation of duties, the compliance override, and pagination bounds.

Covers corner sections cross_cutting_complexity_layers (OCC), rbac, errors, and
the override endpoint instance.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    build_user_headers,
    create_onboarding, present_document, attest_section1, complete_section2,
    set_clock, get_backing_form, api_client,
    make_hr_reviewer_headers, make_compliance_officer_headers,
)
from test_helpers import fixtures as fx

HR = TEST_USERS["hr_reviewer_headers"]
CO = TEST_USERS["compliance_officer_headers"]
OP = TEST_USERS["everify_operator_headers"]


# ===========================================================================
# Queue B — corner: cross_cutting (optimistic concurrency)
# ===========================================================================
def test_section2_complete_with_stale_version_rejected(api):
    """PRD §2.7: "the request must carry `expected_onboarding_version` equal to the target onboarding's current `version`. If another reviewer has already completed Section 2 — legitimately accepting a documentary set and superseding the other presented documents — the onboarding's `version` will have advanced past what the current reviewer last read, so their view of which documents are still `PRESENTED` is stale, and the completion is rejected with `ERR_STALE_ONBOARDING_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_section2_complete
    """
    ob = create_onboarding(employee_full_name="Oc Cc", employee_email="oc@x.com",
                           requires_everify=False)
    doc = present_document(ob["id"], list_category="LIST_A", document_title="US_PASSPORT",
                           document_number="OC", expiration_date="2030-01-01T00:00:00Z")
    ob_v1 = attest_section1(ob["id"])
    # An override (by a different officer) advances the onboarding version.
    officer = make_compliance_officer_headers("officer-2")
    fx.get_success_data(api.override_onboarding(ob["id"], {"override_reason": "bump version"}, officer))
    # The stale section2-complete carries the pre-override version.
    resp = api.section2_complete(
        ob["id"], {"document_ids": [doc["id"]], "expected_onboarding_version": ob_v1["version"]}, HR)
    validate_error(resp, ApiErrorId.ERR_STALE_ONBOARDING_VERSION.value, 412)


def test_section2_complete_with_correct_version_increments_by_one(api):
    """PRD §2.7: "the request must carry `expected_onboarding_version` equal to the target onboarding's current `version`."
    PRD §2.4: "`version`** — a system-managed integer that begins at creation and increments by one on every mutation."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_succeeds_and_increments
    """
    ob = create_onboarding(employee_full_name="Ok Vc", employee_email="ok@x.com",
                           requires_everify=False)
    doc = present_document(ob["id"], list_category="LIST_A", document_title="US_PASSPORT",
                           document_number="OK", expiration_date="2030-01-01T00:00:00Z")
    ob_v1 = attest_section1(ob["id"])
    data = complete_section2(ob["id"], [doc["id"]], ob_v1["version"])
    assert data["status"] == "SECTION2_COMPLETE"
    assert data["version"] == ob_v1["version"] + 1, "Section 2 must bump version by exactly 1"


# ===========================================================================
# Queue B — corner: rbac
# ===========================================================================
def test_everify_operator_cannot_complete_section2(api):
    """PRD §2.1: "When a role is authenticated but is not permitted to perform the requested operation under the access matrix described throughout §3 and tabulated in §4, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: "POST | `/onboardings/{id}/section2-complete` | Complete Section 2 by accepting a sufficient documentary set | HRReviewer"

    Design: Corner/rbac/everify_operator_cannot_complete_section2
    """
    ob = create_onboarding(employee_full_name="Rb Ac", employee_email="rb@x.com",
                           requires_everify=False)
    doc = present_document(ob["id"], list_category="LIST_A", document_title="US_PASSPORT",
                           document_number="RB", expiration_date="2030-01-01T00:00:00Z")
    ob_v1 = attest_section1(ob["id"])
    resp = api.section2_complete(
        ob["id"], {"document_ids": [doc["id"]], "expected_onboarding_version": ob_v1["version"]}, OP)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


def test_hr_reviewer_cannot_submit_everify_case(api):
    """PRD §2.1: "When a role is authenticated but is not permitted to perform the requested operation under the access matrix described throughout §3 and tabulated in §4, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: "POST | `/everify-cases` | Submit an E-Verify case for a Section-2-complete onboarding | EVerifyOperator"

    Design: Corner/rbac/hr_reviewer_cannot_submit_everify_case
    """
    ob_s2, form, _doc = fx.onboarding_through_section2(
        doc_overrides={"document_number": "HP"},
        employee_full_name="Hr Op", employee_email="hr@x.com", requires_everify=True,
    )
    resp = api.create_everify_case(
        {"onboarding_id": ob_s2["id"], "i9_form_id": form["id"],
         "expected_onboarding_version": ob_s2["version"]}, HR)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


def test_unauthenticated_mutation_returns_unauthenticated(api):
    """PRD §2.1: "On any mutating endpoint, a request that omits either header, or whose `X-User-Role` is not one of these three known roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/unauthenticated_mutation_returns_unauthenticated
    """
    anon = {"X-User-ID": "ghost", "X-User-Role": "Intruder", "Content-Type": "application/json"}
    resp = api.create_onboarding(
        {"employee_full_name": "Un Au", "employee_email": "un@x.com",
         "citizenship_status": "US_CITIZEN", "hire_date": "2026-06-01T00:00:00Z"}, anon)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


def test_segregation_of_duties_override_by_section2_reviewer_denied(api):
    """PRD §2.1: "The `ComplianceOfficer` who applies an override on an onboarding must not be the same `X-User-ID` that completed Section 2 on that onboarding's `I9Form` (the value captured in `section2_reviewer_id`). A violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/segregation_of_duties_override_by_section2_reviewer_denied
    """
    dual_hr = make_hr_reviewer_headers("dual-1")
    ob = fx.get_success_data(api.create_onboarding(
        {"employee_full_name": "So Dt", "employee_email": "so@x.com",
         "citizenship_status": "US_CITIZEN", "hire_date": "2026-06-01T00:00:00Z",
         "requires_everify": False}, dual_hr))
    doc = fx.get_success_data(api.create_identity_document(
        {"onboarding_id": ob["id"], "list_category": "LIST_A", "document_title": "US_PASSPORT",
         "document_number": "SP", "expiration_date": "2030-01-01T00:00:00Z"}, dual_hr))
    ob_v1 = fx.get_success_data(api.section1_attest(ob["id"], {}, dual_hr))
    fx.get_success_data(api.section2_complete(
        ob["id"], {"document_ids": [doc["id"]],
                   "expected_onboarding_version": ob_v1["version"]}, dual_hr))
    # Same X-User-ID 'dual-1' now acts as ComplianceOfficer to override.
    dual_co = make_compliance_officer_headers("dual-1")
    resp = api.override_onboarding(ob["id"], {"override_reason": "self-override attempt"}, dual_co)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)


# ===========================================================================
# Queue B — corner: endpoints (override clears overdue)
# ===========================================================================
def test_override_clears_overdue_flag(api):
    """PRD §3.5: "It carries an `override_reason` and force-clears the latched compliance posture — setting `is_overdue` back to false and accepting a late posture under a recorded justification — then appends an `AuditEntry` with action `OVERRIDE_APPLIED` and increments the onboarding's `version` by one."

    Design: Corner/endpoints/override_clears_overdue_flag
    """
    ob = create_onboarding(employee_full_name="Ov Rd", employee_email="ov@x.com",
                           requires_everify=False)
    set_clock("2026-06-10T09:00:00Z")  # past the 2026-06-04 deadline -> overdue latches
    officer = make_compliance_officer_headers("officer-1")
    data = fx.get_success_data(api.override_onboarding(
        ob["id"], {"override_reason": "documented good-faith delay"}, officer))
    assert data["is_overdue"] is False, "override must clear is_overdue"


# ===========================================================================
# Queue B — corner: errors (pagination bounds)
# ===========================================================================
def test_pagination_limit_above_max_returns_validation_pagination(api):
    """PRD §2.3: "The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100."
    PRD §2.3: "A `limit` or `offset` outside these bounds is rejected with `ERR_VALIDATION_PAGINATION` (HTTP 400)."

    Design: Corner/errors/pagination_out_of_bounds_returns_validation_pagination
    """
    resp = api.list_onboardings(HR, params={"limit": 101})
    validate_error(resp, ApiErrorId.ERR_VALIDATION_PAGINATION.value, 400)
