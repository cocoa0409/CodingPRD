"""Validation precedence pairs, cross-entity state dependencies, and onboarding
state-machine guards (initial state, invalid transitions, terminal lockdown).

Covers difficulty rules priority_pair_validation_conflict and
cross_entity_state_dependency, plus corner state-machine instances.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_onboarding, present_document, attest_section1, complete_section2,
    set_clock, get_backing_form, api_client,
)
from test_helpers import fixtures as fx

HR = TEST_USERS["hr_reviewer_headers"]
CO = TEST_USERS["compliance_officer_headers"]
OP = TEST_USERS["everify_operator_headers"]


# ===========================================================================
# Queue A — priority_pair_validation_conflict
# ===========================================================================
def test_combination_invalid_beats_expired_document(api):
    """PRD §2.8: "the documentary-combination rule (`ERR_DOCUMENT_COMBINATION_INVALID`, 422); document/authorization expiry (`ERR_DOCUMENT_EXPIRED`, 422)"
    PRD §2.8: "A check that ranks earlier is decided before any later check runs"

    Design: Difficulty/priority_pair_validation_conflict/combination_invalid_beats_expired_document
    """
    ob = create_onboarding(employee_full_name="Iv Lo", employee_email="iv@x.com",
                           requires_everify=False)
    b1 = present_document(ob["id"], list_category="LIST_B", document_title="DRIVERS_LICENSE",
                          document_number="B1", expiration_date="2020-01-01T00:00:00Z")
    b2 = present_document(ob["id"], list_category="LIST_B", document_title="SCHOOL_ID",
                          document_number="B2", expiration_date="2030-01-01T00:00:00Z")
    ob_v1 = attest_section1(ob["id"])
    resp = api.section2_complete(
        ob["id"], {"document_ids": [b1["id"], b2["id"]],
                   "expected_onboarding_version": ob_v1["version"]}, HR)
    validate_error(resp, ApiErrorId.ERR_DOCUMENT_COMBINATION_INVALID.value, 422)


def test_invalid_state_beats_document_not_owned(api):
    """PRD §2.8: "the target resource being in a state from which the requested transition is defined (`ERR_INVALID_STATE`, 409); the no-duplicate-E-Verify-case guard (`ERR_EVERIFY_CASE_EXISTS`, 409); document ownership on Section 2 (`ERR_DOCUMENT_NOT_OWNED`, 422)"
    PRD §2.8: "A check that ranks earlier is decided before any later check runs"

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_document_not_owned
    """
    ob_a = create_onboarding(employee_full_name="Jo Ka", employee_email="jo@x.com",
                             requires_everify=False)
    ob_b = create_onboarding(employee_full_name="Ka Mo", employee_email="ka@x.com",
                             requires_everify=False)
    doc_foreign = present_document(ob_b["id"], list_category="LIST_A",
                                   document_title="US_PASSPORT", document_number="FP",
                                   expiration_date="2030-01-01T00:00:00Z")
    # ob_a is still CREATED (no Section 1): the state guard fires before ownership.
    resp = api.section2_complete(
        ob_a["id"], {"document_ids": [doc_foreign["id"]],
                     "expected_onboarding_version": ob_a["version"]}, HR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_combination_invalid_beats_expired_two_list_a(api):
    """PRD §2.8: "the documentary-combination rule (`ERR_DOCUMENT_COMBINATION_INVALID`, 422); document/authorization expiry (`ERR_DOCUMENT_EXPIRED`, 422)"
    PRD §3.3: "Any other cardinality — zero documents, two List A documents, a lone List B, a List B with two List C documents, and so on — is rejected with `ERR_DOCUMENT_COMBINATION_INVALID`; there is no partial credit."

    Design: Difficulty/priority_pair_validation_conflict/combination_invalid_beats_expired_document
    """
    ob = create_onboarding(employee_full_name="Iv Lo2", employee_email="iv2@x.com",
                           requires_everify=False)
    a1 = present_document(ob["id"], list_category="LIST_A", document_title="US_PASSPORT",
                          document_number="A1", expiration_date="2020-01-01T00:00:00Z")  # expired
    a2 = present_document(ob["id"], list_category="LIST_A", document_title="PERMANENT_RESIDENT_CARD",
                          document_number="A2", expiration_date="2030-01-01T00:00:00Z")
    ob_v1 = attest_section1(ob["id"])
    # Two List A documents is an invalid combination; one is also expired. Combination wins.
    resp = api.section2_complete(
        ob["id"], {"document_ids": [a1["id"], a2["id"]],
                   "expected_onboarding_version": ob_v1["version"]}, HR)
    validate_error(resp, ApiErrorId.ERR_DOCUMENT_COMBINATION_INVALID.value, 422)


def test_invalid_state_beats_document_not_owned_from_section2_complete(api):
    """PRD §2.8: "the target resource being in a state from which the requested transition is defined (`ERR_INVALID_STATE`, 409); the no-duplicate-E-Verify-case guard (`ERR_EVERIFY_CASE_EXISTS`, 409); document ownership on Section 2 (`ERR_DOCUMENT_NOT_OWNED`, 422)"
    PRD §2.8: "A check that ranks earlier is decided before any later check runs"

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_document_not_owned
    """
    # ob_a already completed Section 2 (now SECTION2_COMPLETE), so a re-complete is an
    # invalid-state transition; pair it with a foreign document so ownership would also fail.
    ob_a, _form_a, _doc_a = fx.onboarding_through_section2(
        doc_overrides={"document_number": "SA"},
        employee_full_name="St Al", employee_email="stal@x.com", requires_everify=False,
    )
    ob_b = create_onboarding(employee_full_name="St Bl", employee_email="stbl@x.com",
                             requires_everify=False)
    doc_foreign = present_document(ob_b["id"], list_category="LIST_A",
                                   document_title="US_PASSPORT", document_number="SB",
                                   expiration_date="2030-01-01T00:00:00Z")
    resp = api.section2_complete(
        ob_a["id"], {"document_ids": [doc_foreign["id"]],
                     "expected_onboarding_version": ob_a["version"]}, HR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


# ===========================================================================
# Queue A — cross_entity_state_dependency
# ===========================================================================
def test_everify_case_requires_onboarding_section2_complete(api):
    """PRD §3.4: "The case may be created when the backing onboarding is in `SECTION2_COMPLETE` (the state machine also tolerates an onboarding already in `EVERIFY_PENDING` only so that the duplicate-case guard, rather than the state guard, is what rejects a second attempt)."
    PRD §2.8: "the target resource being in a state from which the requested transition is defined (`ERR_INVALID_STATE`, 409)"

    Design: Difficulty/cross_entity_state_dependency/everify_case_requires_onboarding_section2_complete
    """
    ob = create_onboarding(employee_full_name="No Ra", employee_email="no@x.com",
                           requires_everify=True)
    form = get_backing_form(ob["id"])
    ob_v1 = attest_section1(ob["id"])  # onboarding now SECTION1_COMPLETE, not SECTION2_COMPLETE
    resp = api.create_everify_case(
        {"onboarding_id": ob["id"], "i9_form_id": form["id"],
         "expected_onboarding_version": ob_v1["version"]}, OP)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_section3_requires_onboarding_reverification_due(api):
    """PRD §3.6: "The transition is permitted only when the onboarding is in `REVERIFICATION_DUE`, or it is rejected with `ERR_INVALID_STATE`"

    Design: Difficulty/cross_entity_state_dependency/section3_reverify_requires_onboarding_reverification_due
    """
    ob_auth, form, _wa, _doc = fx.authorized_non_everify_with_auth(
        auth_valid_until="2027-09-30T00:00:00Z",
        employee_full_name="Op Su", employee_email="op@x.com",
        work_auth_expiration="2027-09-30T00:00:00Z",
    )
    # Onboarding is AUTHORIZED (not yet REVERIFICATION_DUE); Section 3 attempted early.
    wa2 = fx.get_success_data(api.create_work_authorization(
        {"onboarding_id": ob_auth["id"], "auth_type": "EAD",
         "valid_from": "2027-09-30T00:00:00Z", "valid_until": "2030-09-30T00:00:00Z"}, HR))
    resp = api.create_section3(
        form["id"], {"work_authorization_id": wa2["id"],
                     "reverification_reason": "EXPIRING_AUTH",
                     "new_expiration_date": "2030-09-30T00:00:00Z"}, HR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_everify_case_from_created_onboarding_rejected(api):
    """PRD §3.4: "The case may be created when the backing onboarding is in `SECTION2_COMPLETE` (the state machine also tolerates an onboarding already in `EVERIFY_PENDING` only so that the duplicate-case guard, rather than the state guard, is what rejects a second attempt)."
    PRD §2.8: "the target resource being in a state from which the requested transition is defined (`ERR_INVALID_STATE`, 409)"

    Design: Difficulty/cross_entity_state_dependency/everify_case_requires_onboarding_section2_complete
    """
    ob = create_onboarding(employee_full_name="No Ra2", employee_email="no2@x.com",
                           requires_everify=True)
    form = get_backing_form(ob["id"])
    # Onboarding still in CREATED (no Section 1, no Section 2).
    resp = api.create_everify_case(
        {"onboarding_id": ob["id"], "i9_form_id": form["id"],
         "expected_onboarding_version": ob["version"]}, OP)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_section3_from_created_onboarding_rejected(api):
    """PRD §3.6: "The transition is permitted only when the onboarding is in `REVERIFICATION_DUE`, or it is rejected with `ERR_INVALID_STATE`"

    Design: Difficulty/cross_entity_state_dependency/section3_reverify_requires_onboarding_reverification_due
    """
    ob = create_onboarding(employee_full_name="Op Su2", employee_email="op2@x.com",
                           citizenship_status="ALIEN_AUTHORIZED",
                           work_auth_expiration="2030-09-30T00:00:00Z", requires_everify=False)
    form = get_backing_form(ob["id"])
    wa = fx.get_success_data(api.create_work_authorization(
        {"onboarding_id": ob["id"], "auth_type": "EAD",
         "valid_from": "2026-01-01T00:00:00Z", "valid_until": "2030-09-30T00:00:00Z"}, HR))
    # Onboarding still CREATED (never authorized, not REVERIFICATION_DUE).
    resp = api.create_section3(
        form["id"], {"work_authorization_id": wa["id"],
                     "reverification_reason": "EXPIRING_AUTH",
                     "new_expiration_date": "2030-09-30T00:00:00Z"}, HR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


# ===========================================================================
# Queue B — corner: state_machines (initial / invalid / terminal)
# ===========================================================================
def test_new_onboarding_starts_in_created(api):
    """PRD §3.1: "At creation the onboarding enters `CREATED` status"

    Design: Corner/state_machines/new_onboarding_starts_in_created
    """
    ob = validate_success(api.create_onboarding(
        {"employee_full_name": "In It", "employee_email": "in@x.com",
         "citizenship_status": "US_CITIZEN", "hire_date": "2026-06-01T00:00:00Z"}, HR), 201)
    assert ob["status"] == "CREATED"


def test_reattest_section1_when_already_complete_returns_invalid_state(api):
    """PRD §3.1: "Section 1 attestation is performed by an `HRReviewer` and is the transition that takes the onboarding from `CREATED` to `SECTION1_COMPLETE`. It is permitted only when the onboarding is currently in `CREATED`; otherwise it is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/section1_attest_from_already_section1_complete_returns_invalid_state
    """
    ob = create_onboarding(employee_full_name="Re At", employee_email="re@x.com",
                           requires_everify=False)
    attest_section1(ob["id"])
    resp = api.section1_attest(ob["id"], {}, HR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_finalize_on_already_authorized_returns_invalid_state(api):
    """PRD §3.5: "when `requires_everify` is false and the onboarding is in `SECTION2_COMPLETE`, finalization moves it to `AUTHORIZED`, appends an `AuditEntry` with action `AUTHORIZED_NO_EVERIFY`, and increments the onboarding's `version` by one. Finalization from any other state is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/finalize_from_authorized_terminal_returns_invalid_state
    """
    ob_s2, _form, _doc = fx.onboarding_through_section2(
        doc_overrides={"document_number": "TP"},
        employee_full_name="Te Rm", employee_email="te@x.com", requires_everify=False,
    )
    fx.get_success_data(api.finalize_onboarding(ob_s2["id"], {}, CO))
    resp = api.finalize_onboarding(ob_s2["id"], {}, CO)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
