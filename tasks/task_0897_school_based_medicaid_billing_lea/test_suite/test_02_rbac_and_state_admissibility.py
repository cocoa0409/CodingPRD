"""Segregation-of-duties (RBAC) denials and invalid-state-transition corners."""
from test_helpers import (
    TEST_USERS, ApiErrorId,
    validate_error, get_success_data,
    make_service_provider_headers,
    set_clock, create_student, create_provider, create_credential, create_authorization,
    create_consent, create_documented_log, create_draft_claim,
    setup_closed_quarter_half_ratio, create_settlement,
    create_quarter_with_coded_moments,
    api_client,
)

MC = TEST_USERS["medicaid_coordinator_headers"]
BC = TEST_USERS["billing_coordinator_headers"]
SR = TEST_USERS["state_reviewer_headers"]


def test_service_provider_cannot_verify_service_log(api):
    """PRD §3.4: "A separate BillingCoordinator performs encounter capture by
    verifying the documented log — the two steps are segregated across roles by
    design."
    PRD §2.1: "When the headers are well-formed but the named role is not
    permitted to perform the requested operation, the request is rejected with
    ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/service_provider_cannot_verify_service_log
    """
    set_clock("2026-03-15T00:00:00Z")
    student = create_student()
    provider = create_provider()
    create_credential(provider["id"])
    auth = create_authorization(student["id"])
    create_consent(student["id"])
    log = create_documented_log(auth["id"], provider["id"], student["id"])

    resp = api.verify_service_log(log["id"], make_service_provider_headers(provider["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    assert get_success_data(api.get_service_log(log["id"], MC))["status"] == "DOCUMENTED"


def test_billing_coordinator_cannot_adjudicate_claim(api):
    """PRD §3.5: "A StateReviewer adjudicates a submitted claim by supplying an
    outcome of APPROVE or DENY."
    PRD §2.1: "When the headers are well-formed but the named role is not
    permitted to perform the requested operation, the request is rejected with
    ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/billing_coordinator_cannot_adjudicate_claim
    """
    student = create_student()
    claim = create_draft_claim(student["id"])
    resp = api.adjudicate_claim(claim["id"], {"outcome": "APPROVE"}, BC)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    assert get_success_data(api.get_claim(claim["id"], MC))["status"] == "DRAFT"


def test_service_log_document_by_non_owner_returns_forbidden(api):
    """PRD §2.1: "For the two operations a ServiceProvider self-performs — creating
    a service log and documenting it, and responding to a sampled moment — the
    caller's X-User-ID must equal the provider_id on the resource. When it does
    not, the request is rejected with ERR_NOT_RESOURCE_OWNER (HTTP 403)."

    Design: Corner/rbac/service_log_document_by_non_owner_returns_forbidden
    """
    set_clock("2026-03-15T00:00:00Z")
    student = create_student()
    provider_a = create_provider(npi="NPI-C15A")
    provider_b = create_provider(npi="NPI-C15B")
    create_credential(provider_a["id"])
    auth = create_authorization(student["id"])
    create_consent(student["id"])
    log = get_success_data(api.create_service_log({
        "iep_authorization_id": auth["id"], "provider_id": provider_a["id"],
        "student_id": student["id"], "service_date": "2026-03-01",
        "start_time": "2026-03-01T09:00:00Z", "end_time": "2026-03-01T09:40:00Z",
        "delivered_minutes": 40}, make_service_provider_headers(provider_a["id"])))

    resp = api.document_service_log(
        log["id"], {"documentation_note": "intruder"}, make_service_provider_headers(provider_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)


def test_consent_grant_when_already_granted_invalid_state(api):
    """PRD §3.1: "Granting a pending consent moves it to GRANTED and stamps
    granted_date with the current clock."
    PRD §2.5: "State admissibility — the target resource is in a state from which
    the requested transition is allowed, else ERR_INVALID_STATE."

    Design: Corner/state_machines/consent_grant_when_already_granted_invalid_state
    """
    student = create_student()
    consent = create_consent(student["id"], grant=True)
    resp = api.grant_consent(consent["id"], MC)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_success_data(api.get_consent(consent["id"], MC))["status"] == "GRANTED"


def test_cost_settlement_settle_before_certify_invalid_state(api):
    """PRD §3.8: "The MedicaidCoordinator certifies a calculated settlement,
    advancing it from CALCULATED to CERTIFIED, and a StateReviewer then settles
    the certified settlement, advancing it from CERTIFIED to the terminal
    SETTLED."
    PRD §2.5: "State admissibility — the target resource is in a state from which
    the requested transition is allowed, else ERR_INVALID_STATE."

    Design: Corner/state_machines/cost_settlement_settle_before_certify_invalid_state
    """
    q = setup_closed_quarter_half_ratio(fiscal_quarter="2026-Q4")
    settlement = create_settlement(q["quarter_id"], q["quarter_version"], interim_paid_cents=0)
    resp = api.settle_settlement(settlement["id"], SR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_success_data(api.get_settlement(settlement["id"], MC))["status"] == "CALCULATED"


def test_moment_respond_when_already_coded_invalid_state(api):
    """PRD §3.7: "The sampled provider responds to the moment by recording a
    free-text activity_response, which advances it from GENERATED to RESPONDED".
    PRD §2.5: "State admissibility — the target resource is in a state from which
    the requested transition is allowed, else ERR_INVALID_STATE."

    Design: Corner/state_machines/moment_respond_when_already_coded_invalid_state
    """
    info = create_quarter_with_coded_moments(["DIRECT_MEDICAL"], fiscal_quarter="2027-Q1")
    moment = info["moments"][0]
    resp = api.respond_moment(
        moment["id"], {"activity_response": "again"},
        make_service_provider_headers(info["provider_id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
