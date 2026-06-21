"""Validation priority conflicts, cross-entity state gates, segregation of duties,
business-constraint violations, RBAC denial, authentication, and the stale-version
OCC negative.

Difficulty queue: priority_pair_validation_conflict, cross_entity_state_dependency.
Corner queue: validations, rbac, errors sections.
"""
from test_helpers import (
    api_client,
    make_adjudicator_headers,
    make_agent_headers,
    make_applicant_headers,
    pay_payload,
    submit_payload,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx


# ════════════════════════════════════════════════════════════════════════
# Difficulty/priority_pair_validation_conflict/state_beats_business_fiscal_on_begin_verification
# ════════════════════════════════════════════════════════════════════════
def test_begin_verification_on_draft_returns_invalid_state_not_fee_unpaid(api):
    """PRD §2.9: validation order is "Transition definedness — the target resource
    is in a state from which the requested transition is defined; otherwise
    ERR_INVALID_STATE" (priority 5) before "Fee paid before verification —
    ERR_FEE_UNPAID" (priority 16). A DRAFT application (wrong state) with an unpaid
    fee yields the state error.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_business_fiscal_on_begin_verification
    """
    facility = fx.create_facility()
    agent = fx.create_agent(facility["id"])
    applicant = fx.create_applicant()
    application = fx.create_application(applicant["id"], application_type="NEW", product_type="BOOK")
    res = api.begin_verification(application["id"], make_agent_headers(agent["id"]))
    validate_error(res, "ERR_INVALID_STATE")


def test_begin_verification_state_check_precedes_fee_check_explicit(api):
    """PRD §2.9: "Across the transition endpoints, this ordering means existence is
    checked before state, state is checked before segregation-of-duties, and the
    fiscal and concurrency checks come after the structural ones." A DRAFT
    application never surfaces ERR_FEE_UNPAID.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_business_fiscal_on_begin_verification
    """
    facility = fx.create_facility()
    agent = fx.create_agent(facility["id"])
    applicant = fx.create_applicant()
    application = fx.create_application(applicant["id"], application_type="NEW", product_type="BOOK")
    res = api.begin_verification(application["id"], make_agent_headers(agent["id"]))
    body = res.json()
    assert body["data"]["error_id"] == "ERR_INVALID_STATE"
    assert body["data"]["error_id"] != "ERR_FEE_UNPAID"


# ════════════════════════════════════════════════════════════════════════
# Difficulty/priority_pair_validation_conflict/sod_safety_beats_state_terminal_on_adjudicate
# ════════════════════════════════════════════════════════════════════════
def _adjudicating_same_person_agent_and_adjudicator(api):
    """Drive a NEW BOOK application to ADJUDICATING where the SAME X-User-ID is
    registered as both the AcceptanceAgent who verified and the acting Adjudicator.
    Returns (ctx, shared_person_id)."""
    facility = fx.create_facility()
    agent = fx.create_agent(facility["id"], name="Dual Person")
    # Register an adjudicator too, but adjudicate using the AGENT's id as X-User-ID,
    # which is the same person who verified the documents.
    fx.create_adjudicator(name="Dual Person")
    ctx = fx.paid_application(application_type="NEW", product_type="BOOK")
    appl_id = ctx["applicant"]["id"]
    app_id = ctx["application"]["id"]
    validate_success(api.begin_verification(app_id, make_agent_headers(agent["id"])), 200)
    fx.accept_document(ctx["docs"]["IDENTITY"][0]["id"], agent["id"])
    fx.accept_document(ctx["docs"]["CITIZENSHIP"][0]["id"], agent["id"])
    return ctx, agent["id"]


def test_adjudicate_by_verifying_person_returns_sod_violation(api):
    """PRD §3.9: "Approving and rejecting are both guarded by the segregation-of-
    duties rule: the acting adjudicator's underlying person must differ from the
    application's assigned_acceptance_agent_id; a violation is rejected with
    ERR_SOD_VIOLATION."

    Design: Difficulty/priority_pair_validation_conflict/sod_safety_beats_state_terminal_on_adjudicate
    """
    ctx, person_id = _adjudicating_same_person_agent_and_adjudicator(api)
    app_id = ctx["application"]["id"]
    # Adjudicate with the same person who verified (X-User-ID == assigned agent id).
    res = api.adjudicate(app_id, {"decision": "APPROVE"}, make_adjudicator_headers(person_id))
    validate_error(res, "ERR_SOD_VIOLATION")


def test_sod_violation_blocks_approve_in_adjudicating(api):
    """PRD §2.1: "the segregation-of-duties check compares the acting adjudicator's
    identity against the application's assigned_acceptance_agent_id so that the same
    person cannot both verify and adjudicate."

    Design: Difficulty/priority_pair_validation_conflict/sod_safety_beats_state_terminal_on_adjudicate
    """
    ctx, person_id = _adjudicating_same_person_agent_and_adjudicator(api)
    app_id = ctx["application"]["id"]
    appl_id = ctx["applicant"]["id"]
    res = api.adjudicate(app_id, {"decision": "APPROVE"}, make_adjudicator_headers(person_id))
    validate_error(res, "ERR_SOD_VIOLATION")
    # The application remains in ADJUDICATING; the approve did not take effect.
    app = validate_success(api.get_application(app_id, make_applicant_headers(appl_id)), 200)
    assert app["status"] == "ADJUDICATING"


# ════════════════════════════════════════════════════════════════════════
# Difficulty/cross_entity_state_dependency/begin_verification_requires_feeassessment_paid
# ════════════════════════════════════════════════════════════════════════
def test_begin_verification_requires_fee_paid(api):
    """PRD §3.6: begin verification "is permitted only when the application is
    SUBMITTED (otherwise ERR_INVALID_STATE) and the application's fee assessment has
    payment_status equal to PAID (otherwise ERR_FEE_UNPAID)."

    Design: Difficulty/cross_entity_state_dependency/begin_verification_requires_feeassessment_paid
    """
    facility = fx.create_facility()
    agent = fx.create_agent(facility["id"])
    ctx = fx.submitted_application(application_type="NEW", product_type="BOOK")
    # Fee is UNPAID (submitted, never paid).
    res = api.begin_verification(ctx["application"]["id"], make_agent_headers(agent["id"]))
    validate_error(res, "ERR_FEE_UNPAID")


def test_begin_verification_succeeds_once_fee_paid(api):
    """PRD §3.6: begin verification requires "the application's fee assessment has
    payment_status equal to PAID (otherwise ERR_FEE_UNPAID). The acting agent is
    pinned onto the application as its assigned_acceptance_agent_id".

    Design: Difficulty/cross_entity_state_dependency/begin_verification_requires_feeassessment_paid
    """
    facility = fx.create_facility()
    agent = fx.create_agent(facility["id"])
    ctx = fx.paid_application(application_type="NEW", product_type="BOOK")
    started = validate_success(
        api.begin_verification(ctx["application"]["id"], make_agent_headers(agent["id"])), 200)
    assert started["status"] == "IN_VERIFICATION"


# ════════════════════════════════════════════════════════════════════════
# Difficulty/cross_entity_state_dependency/document_verify_requires_parent_application_in_verification
# ════════════════════════════════════════════════════════════════════════
def test_verify_document_requires_parent_in_verification(api):
    """PRD §3.6: "Verification is permitted only when the document is PENDING, the
    parent application is IN_VERIFICATION, and the acting agent is the application's
    assigned_acceptance_agent_id".

    Design: Difficulty/cross_entity_state_dependency/document_verify_requires_parent_application_in_verification
    """
    # Submitted + paid but begin-verification NOT called: app is SUBMITTED.
    ctx = fx.paid_application(application_type="NEW", product_type="BOOK")
    facility = fx.create_facility()
    agent = fx.create_agent(facility["id"])
    id_doc = ctx["docs"]["IDENTITY"][0]
    res = api.verify_document(id_doc["id"], {"outcome": "ACCEPT"}, make_agent_headers(agent["id"]))
    validate_error(res, "ERR_INVALID_STATE")


def test_verify_document_succeeds_when_parent_in_verification(api):
    """PRD §3.6: "While the application is IN_VERIFICATION, the assigned agent
    verifies each document. A document verification supplies an outcome and moves
    the document from PENDING to either ACCEPTED or REJECTED."

    Design: Difficulty/cross_entity_state_dependency/document_verify_requires_parent_application_in_verification
    """
    ctx = fx.in_verification_application(application_type="NEW", product_type="BOOK")
    agent_id = ctx["agent"]["id"]
    id_doc = ctx["docs"]["IDENTITY"][0]
    updated = validate_success(
        api.verify_document(id_doc["id"], {"outcome": "ACCEPT"}, make_agent_headers(agent_id)), 200)
    assert updated["verification_status"] == "ACCEPTED"


# ════════════════════════════════════════════════════════════════════════
# Corner/validations/pay_fee_amount_mismatch_rejected
# ════════════════════════════════════════════════════════════════════════
def test_pay_fee_with_wrong_amount_rejected(api):
    """PRD §3.5: "The tendered amount must exactly equal the assessment's
    total_due_cents; any other amount is rejected with ERR_PAYMENT_AMOUNT_MISMATCH."

    Design: Corner/validations/pay_fee_amount_mismatch_rejected
    """
    ctx = fx.submitted_application(application_type="NEW", product_type="BOOK")
    appl_id = ctx["applicant"]["id"]
    fee = ctx["fee"]
    res = api.pay_fee_assessment(fee["id"], pay_payload(fee["total_due_cents"] - 100),
                                 make_applicant_headers(appl_id))
    validate_error(res, "ERR_PAYMENT_AMOUNT_MISMATCH")


# ════════════════════════════════════════════════════════════════════════
# Corner/validations/submit_without_pass_photo_rejected
# ════════════════════════════════════════════════════════════════════════
def test_submit_without_pass_photo_rejected(api):
    """PRD §3.3: "there must be at least one photo on the application whose
    validation_result is PASS (a FAIL photo cannot satisfy this), failing which the
    submit is rejected with ERR_PHOTO_INVALID".

    Design: Corner/validations/submit_without_pass_photo_rejected
    """
    applicant = fx.create_applicant()
    application = fx.create_application(applicant["id"], application_type="NEW", product_type="BOOK")
    appl_id = applicant["id"]
    # A single FAIL photo (background not white).
    fx.add_photo(application["id"], appl_id, background_is_white=False)
    fx.add_document(application["id"], appl_id, doc_category="IDENTITY", doc_kind="DRIVERS_LICENSE")
    fx.add_document(application["id"], appl_id, doc_category="CITIZENSHIP", doc_kind="BIRTH_CERTIFICATE")
    res = api.submit_application(application["id"], submit_payload(application["version"]),
                                make_applicant_headers(appl_id))
    validate_error(res, "ERR_PHOTO_INVALID")


# ════════════════════════════════════════════════════════════════════════
# Corner/validations/minor_submit_without_guardian_consent_rejected
# ════════════════════════════════════════════════════════════════════════
def test_minor_submit_without_guardian_consent_rejected(api):
    """PRD §3.3: "for a MINOR application there must exist a supporting document with
    doc_category GUARDIAN_CONSENT and the primary applicant must have a non-null
    guardian_applicant_id, failing which the submit is rejected with
    ERR_GUARDIAN_CONSENT_REQUIRED".

    Design: Corner/validations/minor_submit_without_guardian_consent_rejected
    """
    fx.set_clock("2026-06-01T10:00:00Z")
    guardian = fx.create_applicant(date_of_birth="1985-01-01")
    minor = fx.create_applicant(date_of_birth="2015-01-01", guardian_applicant_id=guardian["id"])
    application = fx.create_application(minor["id"], application_type="MINOR", product_type="BOOK")
    fx.add_photo(application["id"], minor["id"])  # PASS photo, but no guardian-consent doc
    res = api.submit_application(application["id"], submit_payload(application["version"]),
                                make_applicant_headers(minor["id"]))
    validate_error(res, "ERR_GUARDIAN_CONSENT_REQUIRED")


# ════════════════════════════════════════════════════════════════════════
# Corner/validations/name_change_submit_without_evidence_rejected
# ════════════════════════════════════════════════════════════════════════
def test_name_change_submit_without_evidence_rejected(api):
    """PRD §3.3: "if name_change_requested is true there must exist a supporting
    document with doc_category NAME_CHANGE_EVIDENCE, failing which the submit is
    rejected with ERR_NAME_CHANGE_EVIDENCE_REQUIRED."

    Design: Corner/validations/name_change_submit_without_evidence_rejected
    """
    applicant = fx.create_applicant(date_of_birth="1985-01-01")
    application = fx.create_application(applicant["id"], application_type="RENEWAL",
                                        product_type="BOOK", name_change_requested=True,
                                        prior_name="Old Name")
    appl_id = applicant["id"]
    fx.add_photo(application["id"], appl_id)  # PASS photo, but no name-change evidence
    res = api.submit_application(application["id"], submit_payload(application["version"]),
                                make_applicant_headers(appl_id))
    validate_error(res, "ERR_NAME_CHANGE_EVIDENCE_REQUIRED")


# ════════════════════════════════════════════════════════════════════════
# Corner/validations/appointment_end_not_after_start_rejected
# ════════════════════════════════════════════════════════════════════════
def test_appointment_end_equal_start_rejected(api):
    """PRD §3.7: "The end_utc must be strictly after start_utc; otherwise the booking
    is rejected with ERR_INVALID_INTERVAL."

    Design: Corner/validations/appointment_end_not_after_start_rejected
    """
    facility = fx.create_facility()
    ctx = fx.submitted_application(application_type="NEW", product_type="BOOK")
    appl_id = ctx["applicant"]["id"]
    app_id = ctx["application"]["id"]
    version = fx.current_version(app_id, appl_id)
    res = api.create_appointment({
        "application_id": app_id, "resource_kind": "ACCEPTANCE_FACILITY",
        "facility_id": facility["id"], "start_utc": "2026-06-09T09:00:00Z",
        "end_utc": "2026-06-09T09:00:00Z", "expected_application_version": version,
    }, make_applicant_headers(appl_id))
    validate_error(res, "ERR_INVALID_INTERVAL")


# ════════════════════════════════════════════════════════════════════════
# Corner/validations/duplicate_urgent_appointment_rejected
# ════════════════════════════════════════════════════════════════════════
def test_second_urgent_appointment_rejected(api):
    """PRD §3.7: "an application may hold at most one BOOKED urgent-travel-counter
    appointment at any time, and an attempt to book a second while one is still
    BOOKED is rejected with ERR_DUPLICATE_URGENT_APPOINTMENT."

    Design: Corner/validations/duplicate_urgent_appointment_rejected
    """
    fx.set_clock("2026-06-01T10:00:00Z")
    counter1 = fx.create_counter(cleanup_buffer_minutes=15)
    counter2 = fx.create_counter(cleanup_buffer_minutes=15)
    ctx = fx.submitted_application(application_type="NEW", product_type="BOOK")
    appl_id = ctx["applicant"]["id"]
    app_id = ctx["application"]["id"]
    fx.book_counter_appointment(app_id, appl_id, counter1["id"],
                                "2026-06-09T09:00:00Z", "2026-06-09T09:30:00Z",
                                ctx["application"]["version"])
    version = fx.current_version(app_id, appl_id)
    res = api.create_appointment({
        "application_id": app_id, "resource_kind": "URGENT_TRAVEL_COUNTER",
        "counter_id": counter2["id"], "start_utc": "2026-06-09T11:00:00Z",
        "end_utc": "2026-06-09T11:30:00Z", "expected_application_version": version,
    }, make_applicant_headers(appl_id))
    validate_error(res, "ERR_DUPLICATE_URGENT_APPOINTMENT")


# ════════════════════════════════════════════════════════════════════════
# Corner/errors/error_stale_version_on_submit_explicit_412
# ════════════════════════════════════════════════════════════════════════
def test_submit_with_stale_version_rejected_412(api):
    """PRD §2.7: "If expected_application_version does not equal the application's
    current version at the time the server processes the request, the operation is
    rejected with ERR_STALE_VERSION (HTTP 412) and no change is made." PRD §2.7: the
    second guarded operation is "submitting an application".

    Design: Corner/errors/error_stale_version_on_submit_explicit_412
    """
    applicant = fx.create_applicant(date_of_birth="1985-01-01")
    application = fx.create_application(applicant["id"], application_type="RENEWAL",
                                        product_type="BOOK", name_change_requested=True,
                                        prior_name="Old")
    appl_id = applicant["id"]
    fx.add_photo(application["id"], appl_id)
    fx.add_document(application["id"], appl_id, doc_category="NAME_CHANGE_EVIDENCE",
                    doc_kind="MARRIAGE_CERTIFICATE")
    # Submit with a version one less than the current version → stale.
    res = api.submit_application(application["id"],
                                submit_payload(application["version"] - 1),
                                make_applicant_headers(appl_id))
    validate_error(res, "ERR_STALE_VERSION")


# ════════════════════════════════════════════════════════════════════════
# Corner/rbac/missing_auth_headers_unauthenticated
# ════════════════════════════════════════════════════════════════════════
def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "Every request, with two explicit exceptions noted below, must be
    authenticated through two mandatory HTTP headers: X-User-ID ... and X-User-Role
    .... If either header is missing or malformed, the request is rejected with
    ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    applicant = fx.create_applicant()
    application = fx.create_application(applicant["id"], application_type="NEW", product_type="BOOK")
    # No X-User-ID / X-User-Role headers on this read.
    res = api.get_application(application["id"], headers={})
    validate_error(res, "ERR_UNAUTHENTICATED")


# ════════════════════════════════════════════════════════════════════════
# Corner/rbac/applicant_cannot_adjudicate_forbidden
# ════════════════════════════════════════════════════════════════════════
def test_applicant_cannot_adjudicate_forbidden(api):
    """PRD §2.1: "A role attempting an operation it is not authorized for is rejected
    with ERR_FORBIDDEN (HTTP 403)." PRD §4: POST /applications/{id}/adjudicate is
    authorized for Adjudicator only.

    Design: Corner/rbac/applicant_cannot_adjudicate_forbidden
    """
    applicant = fx.create_applicant()
    application = fx.create_application(applicant["id"], application_type="NEW", product_type="BOOK")
    res = api.adjudicate(application["id"], {"decision": "APPROVE"},
                         make_applicant_headers(applicant["id"]))
    validate_error(res, "ERR_FORBIDDEN")


# ════════════════════════════════════════════════════════════════════════
# Corner/rbac/acceptance_agent_cannot_create_facility_forbidden
# ════════════════════════════════════════════════════════════════════════
def test_acceptance_agent_cannot_create_facility_forbidden(api):
    """PRD §2.1: "A role attempting an operation it is not authorized for is rejected
    with ERR_FORBIDDEN (HTTP 403)." PRD §4: POST /acceptance-facilities is authorized
    for Adjudicator only.

    Design: Corner/rbac/acceptance_agent_cannot_create_facility_forbidden
    """
    facility = fx.create_facility()
    agent = fx.create_agent(facility["id"])
    res = api.create_acceptance_facility({"name": "Rogue Facility", "state_code": "NY"},
                                         make_agent_headers(agent["id"]))
    validate_error(res, "ERR_FORBIDDEN")


# ════════════════════════════════════════════════════════════════════════
# Corner/rbac/agent_verify_doc_on_unassigned_application_sod
# ════════════════════════════════════════════════════════════════════════
def test_agent_verify_doc_on_unassigned_application_sod(api):
    """PRD §3.6: "an agent who is not the assigned agent — including one who never
    began verification on this application — is rejected with ERR_SOD_VIOLATION."

    Design: Corner/rbac/agent_verify_doc_on_unassigned_application_sod
    """
    facility = fx.create_facility()
    agent_a = fx.create_agent(facility["id"], name="Agent A")
    agent_b = fx.create_agent(facility["id"], name="Agent B")
    ctx = fx.paid_application(application_type="NEW", product_type="BOOK")
    appl_id = ctx["applicant"]["id"]
    app_id = ctx["application"]["id"]
    # Agent A begins verification (assigned), Agent B attempts to verify.
    validate_success(api.begin_verification(app_id, make_agent_headers(agent_a["id"])), 200)
    id_doc = ctx["docs"]["IDENTITY"][0]
    res = api.verify_document(id_doc["id"], {"outcome": "ACCEPT"}, make_agent_headers(agent_b["id"]))
    validate_error(res, "ERR_SOD_VIOLATION")
