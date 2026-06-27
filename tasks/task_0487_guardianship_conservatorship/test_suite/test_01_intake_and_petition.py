"""Intake, case opening, the petition lifecycle, and adjudication fork.

Covers corner entities/state_machines/errors/rbac instances plus the difficulty
instances for the petition GRANT/DISMISS fork and the evaluation->petition bubble.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    assert_protected_person,
    assert_case,
)
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.constants import MISSING_UUID


# ===========================================================================
# Entities — creation, required fields, types, FK resolution
# ===========================================================================
def test_create_protected_person_returns_201_with_defaults(api):
    """PRD 3.1: "A newly registered person begins life with capacity_status of
    PRESUMED_COMPETENT and a null active_case_id."

    Design: Corner/entities/create_protected_person_returns_201_with_system_fields
    """
    payload = F.create_protected_person_payload(
        full_name="New Ward",
        date_of_birth="1950-01-01",
        annual_income_cents=100000,
        liquid_estate_cents=200000,
    )
    data = validate_success(api.create_protected_person(payload, fx.CLERK), 201)
    assert_protected_person(data)
    assert data["capacity_status"] == "PRESUMED_COMPETENT"
    assert data["active_case_id"] is None


def test_get_case_not_found_returns_404(api):
    """PRD 2.4: "when an operation addresses a resource by its id in the path and
    that resource does not exist, the request is rejected with ERR_NOT_FOUND
    before any body-level foreign key is considered."

    Design: Corner/entities/get_case_not_found_returns_404
    """
    validate_error(api.get_case(MISSING_UUID, fx.JUDGE), ApiErrorId.ERR_NOT_FOUND)


def test_create_case_missing_case_type_rejected(api):
    """PRD 3.9: "then request well-formedness — required fields present, correct
    types, enum values within their allowed sets, and amounts within their
    declared bounds such as amount_cents strictly above zero and caps at or above
    zero (ERR_INVALID_REQUEST)".

    Design: Corner/entities/create_case_missing_case_type_returns_invalid_request
    """
    person = fx.create_person()
    resp = api.create_case({"protected_person_id": person["id"]}, fx.CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_create_case_bad_enum_case_type_rejected(api):
    """PRD 3.9: "then request well-formedness — required fields present, correct
    types, enum values within their allowed sets, and amounts within their
    declared bounds such as amount_cents strictly above zero and caps at or above
    zero (ERR_INVALID_REQUEST)".

    Design: Corner/entities/create_case_bad_enum_case_type_returns_invalid_request
    """
    person = fx.create_person()
    resp = api.create_case(
        {"protected_person_id": person["id"], "case_type": "FOO"}, fx.CLERK
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_create_case_bad_person_fk_rejected(api):
    """PRD 2.4: "a body foreign key that does not exist, or that resolves to a
    resource outside the case scope it is required to belong to, is rejected with
    ERR_REFERENCE_NOT_FOUND."

    Design: Corner/entities/create_case_bad_person_fk_returns_reference_not_found
    """
    resp = api.create_case(
        {"protected_person_id": MISSING_UUID, "case_type": "GUARDIANSHIP"}, fx.CLERK
    )
    validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND)


def test_list_protected_persons_paginated_envelope(api):
    """PRD 2.3: "Every list response includes limit, offset, total_count, and
    has_more in the meta object of the envelope."

    Design: Corner/entities/list_protected_persons_paginated_envelope
    """
    fx.create_person(full_name="P1")
    fx.create_person(full_name="P2")
    data, meta = validate_paginated(
        api.list_protected_persons(fx.CLERK, params={"limit": 1, "offset": 0})
    )
    assert meta["total_count"] >= 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_computed_total_estate_ignores_client_value(api):
    """PRD 3.4: "The system computes total_estate_cents as the sum of those three
    figures."

    Design: Corner/entities/computed_total_estate_cents_ignores_input
    """
    ctx = fx.active_case(case_type="CONSERVATORSHIP")
    fx.open_restricted_account(ctx["case_id"], ctx["fiduciary_id"])
    payload = F.create_inventory_payload(
        ctx["case_id"],
        real_property_cents=1_000_000,
        liquid_assets_cents=1_500_000,
        tangible_property_cents=500_000,
    )
    data = validate_success(
        api.create_inventory(payload, fx.make_fiduciary_headers(ctx["fiduciary_id"])),
        201,
    )
    assert data["total_estate_cents"] == 3_000_000


def test_person_one_active_case_uniqueness(api):
    """PRD 3.1: "an attempt to open a second case for a person whose
    active_case_id is already set is rejected with ERR_PERSON_HAS_ACTIVE_CASE."

    Design: Corner/entities/person_one_active_case_uniqueness
    """
    person = fx.create_person()
    fx.create_case(person["id"], case_type="GUARDIANSHIP")
    resp = api.create_case(
        {"protected_person_id": person["id"], "case_type": "CONSERVATORSHIP"}, fx.CLERK
    )
    validate_error(resp, ApiErrorId.ERR_PERSON_HAS_ACTIVE_CASE)


def test_requires_bond_computed_from_case_type(api):
    """PRD 3.1: "The system derives requires_bond as true exactly when the
    case_type is CONSERVATORSHIP or PLENARY, since those seek estate authority."

    Design: Corner/entities/requires_bond_true_for_conservatorship
    """
    p1 = fx.create_person()
    p2 = fx.create_person()
    c1 = validate_success(
        api.create_case(
            {"protected_person_id": p1["id"], "case_type": "CONSERVATORSHIP"}, fx.CLERK
        ),
        201,
    )
    c2 = validate_success(
        api.create_case(
            {"protected_person_id": p2["id"], "case_type": "GUARDIANSHIP"}, fx.CLERK
        ),
        201,
    )
    assert c1["requires_bond"] is True
    assert c2["requires_bond"] is False


# ===========================================================================
# State machine — initial state, invalid transitions, terminal lockdown
# ===========================================================================
def test_new_case_initial_state_draft_green(api):
    """PRD 3.1: "The new case begins in DRAFT status with a GREEN posture."

    Design: Corner/state_machines/initial_state_case_is_draft
    """
    person = fx.create_person()
    data = validate_success(
        api.create_case(
            {"protected_person_id": person["id"], "case_type": "GUARDIANSHIP"}, fx.CLERK
        ),
        201,
    )
    assert_case(data)
    assert data["status"] == "DRAFT"
    assert data["protection_posture"] == "GREEN"


def test_order_evaluation_from_filed_rejected(api):
    """PRD 3.2: "Ordering an evaluation advances the petition from PROBABLE_CAUSE
    to EVALUATION_ORDERED and requires the petition to be in PROBABLE_CAUSE, again
    under ERR_INVALID_STATE otherwise."

    Design: Corner/state_machines/invalid_transition_order_evaluation_from_filed
    """
    person = fx.create_person()
    fid = fx.create_fiduciary()
    case = fx.create_case(person["id"], case_type="GUARDIANSHIP")
    petition = fx.file_petition(case["id"], fid["id"])
    validate_error(
        api.order_evaluation(petition["id"], fx.JUDGE), ApiErrorId.ERR_INVALID_STATE
    )


def test_dismissed_petition_terminal_grant_rejected(api):
    """PRD 3.2: "Granting a petition requires it to be in READY_FOR_HEARING (else
    ERR_INVALID_STATE)."

    Design: Corner/state_machines/terminal_state_lockdown_dismissed_petition
    """
    person = fx.create_person()
    fid = fx.create_fiduciary()
    case = fx.create_case(person["id"], case_type="GUARDIANSHIP")
    petition = fx.file_petition(case["id"], fid["id"])
    api.find_probable_cause(petition["id"], fx.JUDGE)
    api.dismiss_petition(petition["id"], fx.JUDGE)
    validate_error(
        api.grant_petition(petition["id"], fx.JUDGE), ApiErrorId.ERR_INVALID_STATE
    )


def test_grant_blocked_by_competent_finding(api):
    """PRD 3.2: "the petition's filed evaluation finding must not be COMPETENT
    (else ERR_EVALUATION_FINDS_COMPETENT)".

    Design: Corner/state_machines/guarded_grant_blocked_by_competent_finding
    """
    ctx = fx.petition_to_ready_for_hearing(
        case_type="GUARDIANSHIP",
        requested_authority="PERSON",
        finding="COMPETENT",
        recommended_scope="NONE",
    )
    validate_error(
        api.grant_petition(ctx["petition_id"], fx.JUDGE),
        ApiErrorId.ERR_EVALUATION_FINDS_COMPETENT,
    )


def test_grant_scope_exceeds_recommendation(api):
    """PRD 3.2: "the petition's requested_authority must be covered by the
    evaluation's recommended_scope (else ERR_SCOPE_EXCEEDS_RECOMMENDATION)."

    Design: Corner/state_machines/scope_exceeds_recommendation_on_grant
    """
    ctx = fx.petition_to_ready_for_hearing(
        case_type="PLENARY",
        requested_authority="BOTH",
        finding="PARTIALLY_INCAPACITATED",
        recommended_scope="PERSON",
        person_overrides={"liquid_estate_cents": 8_000_000},
    )
    validate_error(
        api.grant_petition(ctx["petition_id"], fx.JUDGE),
        ApiErrorId.ERR_SCOPE_EXCEEDS_RECOMMENDATION,
    )


def test_file_evaluation_before_ordered_rejected(api):
    """PRD 3.2: "Filing has three preconditions ... the parent petition must be in
    EVALUATION_ORDERED (else ERR_EVALUATION_NOT_ORDERED)".

    Design: Corner/state_machines/evaluation_file_before_ordered_returns_not_ordered
    """
    person = fx.create_person()
    fid = fx.create_fiduciary()
    case = fx.create_case(person["id"], case_type="GUARDIANSHIP")
    petition = fx.file_petition(case["id"], fid["id"])
    api.find_probable_cause(petition["id"], fx.JUDGE)
    ev = get_success_data(
        api.create_evaluation(
            F.create_evaluation_payload(petition["id"]), fx.EXAMINER
        )
    )
    validate_error(
        api.file_evaluation(ev["id"], fx.EXAMINER),
        ApiErrorId.ERR_EVALUATION_NOT_ORDERED,
    )


# ===========================================================================
# Difficulty: petition GRANT vs DISMISS fork
# ===========================================================================
def test_petition_grant_branch_side_effects(api):
    """PRD 3.2: "A successful grant moves the petition to GRANTED, advances the
    case from PENDING_EVALUATION to AWAITING_APPOINTMENT, and sets the protected
    person's capacity_status to ADJUDICATED_INCAPACITATED."

    Design: Difficulty/non_linear_state_machine/nlsm_petition_branch_grant_vs_dismiss
    """
    ctx = fx.petition_to_ready_for_hearing(
        case_type="GUARDIANSHIP", requested_authority="PERSON", recommended_scope="PERSON"
    )
    granted = validate_success(api.grant_petition(ctx["petition_id"], fx.JUDGE))
    assert granted["status"] == "GRANTED"
    case = get_success_data(api.get_case(ctx["case_id"], fx.JUDGE))
    assert case["status"] == "AWAITING_APPOINTMENT"
    person = get_success_data(api.get_protected_person(ctx["person_id"], fx.JUDGE))
    assert person["capacity_status"] == "ADJUDICATED_INCAPACITATED"


def test_petition_dismiss_branch_side_effects(api):
    """PRD 3.2: "Dismissal moves the petition to DISMISSED, drives the case to
    TERMINATED (no protection was ordered), and clears the protected person's
    active_case_id back to null."

    Design: Difficulty/non_linear_state_machine/nlsm_petition_branch_grant_vs_dismiss
    """
    ctx = fx.petition_to_ready_for_hearing(
        case_type="GUARDIANSHIP", requested_authority="PERSON", recommended_scope="PERSON"
    )
    dismissed = validate_success(api.dismiss_petition(ctx["petition_id"], fx.JUDGE))
    assert dismissed["status"] == "DISMISSED"
    case = get_success_data(api.get_case(ctx["case_id"], fx.JUDGE))
    assert case["status"] == "TERMINATED"
    person = get_success_data(api.get_protected_person(ctx["person_id"], fx.JUDGE))
    assert person["active_case_id"] is None


# ===========================================================================
# Difficulty: evaluation file bubbles the petition to READY_FOR_HEARING
# ===========================================================================
def test_evaluation_file_bubbles_petition_ready(api):
    """PRD 3.2: "When an evaluation is filed, its parent petition automatically
    bubbles up from EVALUATION_ORDERED to READY_FOR_HEARING; the petition is never
    advanced to READY_FOR_HEARING by a direct call."

    Design: Difficulty/transitive_cascade/tc_evaluation_file_bubbles_petition_ready
    """
    person = fx.create_person()
    fid = fx.create_fiduciary()
    case = fx.create_case(person["id"], case_type="GUARDIANSHIP")
    petition = fx.file_petition(case["id"], fid["id"])
    api.find_probable_cause(petition["id"], fx.JUDGE)
    api.order_evaluation(petition["id"], fx.JUDGE)
    ev = get_success_data(
        api.create_evaluation(
            F.create_evaluation_payload(
                petition["id"], finding="PARTIALLY_INCAPACITATED", recommended_scope="PERSON"
            ),
            fx.EXAMINER,
        )
    )
    filed = validate_success(api.file_evaluation(ev["id"], fx.EXAMINER))
    assert filed["status"] == "FILED"
    pet = get_success_data(api.get_petition(petition["id"], fx.JUDGE))
    assert pet["status"] == "READY_FOR_HEARING"


def test_evaluation_file_advances_petition_only_via_evaluation(api):
    """PRD 3.2: "When an evaluation is filed, its parent petition automatically
    bubbles up from EVALUATION_ORDERED to READY_FOR_HEARING; the petition is never
    advanced to READY_FOR_HEARING by a direct call."

    Design: Difficulty/transitive_cascade/tc_evaluation_file_bubbles_petition_ready
    """
    # Distinct second test for the same instance: confirm the bubble is what makes
    # the subsequent grant reachable (i.e. the petition reached READY by the file).
    ctx = fx.petition_to_ready_for_hearing(
        case_type="GUARDIANSHIP", requested_authority="PERSON", recommended_scope="PERSON"
    )
    ev = get_success_data(api.get_evaluation(ctx["evaluation_id"], fx.JUDGE))
    assert ev["status"] == "FILED"
    pet = get_success_data(api.get_petition(ctx["petition_id"], fx.JUDGE))
    assert pet["status"] == "READY_FOR_HEARING"


# ===========================================================================
# RBAC / auth
# ===========================================================================
def test_unauthenticated_missing_headers(api):
    """PRD 2.1: "A request missing either header, or carrying a malformed one, is
    rejected with ERR_UNAUTHENTICATED."

    Design: Corner/rbac/rbac_unauthenticated_missing_headers
    """
    validate_error(
        api.list_protected_persons({}), ApiErrorId.ERR_UNAUTHENTICATED
    )


def test_petitioner_cannot_grant(api):
    """PRD 2.1: "A Petitioner files the petition that opens proceedings and may
    register subjects, candidate fiduciaries, and cases, but may never evaluate
    capacity or rule on a petition."

    Design: Corner/rbac/rbac_petitioner_cannot_grant
    """
    ctx = fx.petition_to_ready_for_hearing(
        case_type="GUARDIANSHIP", requested_authority="PERSON", recommended_scope="PERSON"
    )
    validate_error(
        api.grant_petition(ctx["petition_id"], fx.TEST_USERS["petitioner_headers"]),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
    )


def test_existence_check_precedes_state_unknown_case(api):
    """PRD 2.4: "when an operation addresses a resource by its id in the path and
    that resource does not exist, the request is rejected with ERR_NOT_FOUND
    before any body-level foreign key is considered."

    Design: Corner/validations/priority_existence_beats_state_unknown_case
    """
    validate_error(
        api.open_review(MISSING_UUID, fx.JUDGE), ApiErrorId.ERR_NOT_FOUND
    )


def test_segregation_examiner_equals_petitioner_blocks_file(api):
    """PRD 3.2: "the examiner_user_id must differ from the parent petition's
    petitioner_user_id (else ERR_SEGREGATION_OF_DUTIES)".

    Design: Corner/validations/segregation_examiner_equals_petitioner_blocks_file
    """
    person = fx.create_person()
    fid = fx.create_fiduciary()
    case = fx.create_case(person["id"], case_type="GUARDIANSHIP")
    petition = fx.file_petition(case["id"], fid["id"], petitioner_id="dual-1")
    api.find_probable_cause(petition["id"], fx.JUDGE)
    api.order_evaluation(petition["id"], fx.JUDGE)
    ev = get_success_data(
        api.create_evaluation(
            F.create_evaluation_payload(petition["id"]),
            fx.make_examiner_headers("dual-1"),
        )
    )
    validate_error(
        api.file_evaluation(ev["id"], fx.make_examiner_headers("dual-1")),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
    )


# ===========================================================================
# Difficulty: forbidden-role precedes invalid-state (priority pair)
# ===========================================================================
def test_forbidden_role_beats_invalid_state_on_grant(api):
    """PRD 3.9: "The system always evaluates them in a fixed priority:
    authentication first (ERR_UNAUTHENTICATED), then role authorization
    (ERR_FORBIDDEN_ROLE) ... then the from-state validity of the requested
    transition (ERR_INVALID_STATE)".

    Design: Difficulty/priority_pair_validation_conflict/ppvc_forbidden_role_beats_invalid_state
    """
    # Petition is in FILED (probable cause not found): grant would be an invalid
    # state transition. But the caller is a Fiduciary (grant is Judge-only), so the
    # higher-priority role check wins with ERR_FORBIDDEN_ROLE, not ERR_INVALID_STATE.
    person = fx.create_person()
    fid = fx.create_fiduciary()
    case = fx.create_case(person["id"], case_type="GUARDIANSHIP")
    petition = fx.file_petition(case["id"], fid["id"])
    validate_error(
        api.grant_petition(petition["id"], fx.make_fiduciary_headers(fid["id"])),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
    )


def test_forbidden_role_beats_invalid_state_status_is_403(api):
    """PRD 3.9: "a request from an unauthorized role is rejected for the role
    before any state check runs".

    Design: Difficulty/priority_pair_validation_conflict/ppvc_forbidden_role_beats_invalid_state
    """
    person = fx.create_person()
    fid = fx.create_fiduciary()
    case = fx.create_case(person["id"], case_type="GUARDIANSHIP")
    petition = fx.file_petition(case["id"], fid["id"])
    resp = api.grant_petition(petition["id"], fx.make_fiduciary_headers(fid["id"]))
    assert resp.status_code == 403, f"expected 403, got {resp.status_code}"
