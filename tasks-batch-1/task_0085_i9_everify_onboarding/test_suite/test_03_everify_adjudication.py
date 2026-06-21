"""E-Verify case lifecycle: SUBMITTED fork-join, TNC contest/refer/authorize,
final-nonconfirmation cascade to onboarding termination, and the referral window.

Covers difficulty rules non_linear_state_machine (E-Verify branch),
transitive_cascade (final-nonconfirm branch), resource_temporal_overlap (referral
window), and corner state_machine / validation instances.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_onboarding, present_document, attest_section1, complete_section2,
    set_clock, get_backing_form, submit_everify_case, api_client,
)
from test_helpers import fixtures as fx

HR = TEST_USERS["hr_reviewer_headers"]
OP = TEST_USERS["everify_operator_headers"]
CO = TEST_USERS["compliance_officer_headers"]


def _through_section2_everify(name_seed, **ob_overrides):
    """Local helper: onboarding through Section 2 with a List A passport, requires_everify
    True, returning (onboarding_after_section2, form)."""
    ob_overrides.setdefault("requires_everify", True)
    ob = create_onboarding(employee_full_name=name_seed, employee_email=f"{name_seed}@x.com",
                           **ob_overrides)
    form = get_backing_form(ob["id"])
    doc = present_document(ob["id"], list_category="LIST_A", document_title="US_PASSPORT",
                           document_number=f"{name_seed}P", expiration_date="2030-01-01T00:00:00Z")
    ob_v1 = attest_section1(ob["id"])
    ob_v2 = complete_section2(ob["id"], [doc["id"]], ob_v1["version"])
    return ob_v2, form


# ===========================================================================
# Queue A — non_linear_state_machine (E-Verify TNC -> refer -> authorize)
# ===========================================================================
def test_tnc_branch_refer_then_authorize_reaches_employment_authorized(api):
    """PRD §3.4: "From `REFERRED`, a subsequent `AUTHORIZED` result moves the case to `EMPLOYMENT_AUTHORIZED` and cascades the onboarding from `EVERIFY_PENDING` to `AUTHORIZED`, appending an `AuditEntry` with action `AUTHORIZED_AFTER_REFERRAL`"
    PRD §3.4: "The employee's contest of a Tentative Nonconfirmation is recorded as a referral by an `EVerifyOperator`, moving the case from `TNC_ISSUED` to `REFERRED`."

    Design: Difficulty/non_linear_state_machine/everify_tnc_branch_refer_then_authorize
    """
    ob_s2, form = _through_section2_everify("Edro")
    case = submit_everify_case(ob_s2["id"], form["id"], ob_s2["version"])
    fx.get_success_data(api.everify_result(case["id"], {"result": "TNC", "agency": "DHS"}, OP))
    fx.get_success_data(api.everify_refer(case["id"], {}, OP))
    data = validate_success(api.everify_result(case["id"], {"result": "AUTHORIZED"}, OP))
    assert data["status"] == "EMPLOYMENT_AUTHORIZED"
    ob_after = validate_success(api.get_onboarding(ob_s2["id"], OP))
    assert ob_after["status"] == "AUTHORIZED"


def test_tnc_issued_sets_tnc_type_and_holds_onboarding_pending(api):
    """PRD §3.4: "From `SUBMITTED`, a `TNC` result moves the case to `TNC_ISSUED`: the system sets `tnc_type` to `SSA_TNC` or `DHS_TNC` according to the agency, stamps `tnc_issued_at` to the clock, and computes `referral_deadline` as `tnc_issued_at` plus 10 federal-government business days; an `AuditEntry` with action `TNC_ISSUED` is appended, and the onboarding stays in `EVERIFY_PENDING` throughout TNC handling."

    Design: Difficulty/non_linear_state_machine/everify_tnc_branch_refer_then_authorize
    """
    ob_s2, form = _through_section2_everify("Edro2")
    case = submit_everify_case(ob_s2["id"], form["id"], ob_s2["version"])
    data = validate_success(api.everify_result(case["id"], {"result": "TNC", "agency": "SSA"}, OP))
    assert data["status"] == "TNC_ISSUED"
    assert data["tnc_type"] == "SSA_TNC"
    ob_after = validate_success(api.get_onboarding(ob_s2["id"], OP))
    assert ob_after["status"] == "EVERIFY_PENDING", "onboarding stays EVERIFY_PENDING during TNC"


# ===========================================================================
# Queue A — transitive_cascade (final nonconfirmation depth-3)
# ===========================================================================
def test_referral_lapse_cascades_case_and_onboarding_to_termination(api):
    """PRD §3.4: "From `TNC_ISSUED`, the case reaches `FINAL_NONCONFIRMATION` either by an explicit `NO_ACTION` close or automatically when the clock crosses `referral_deadline` with no referral on record; in both cases the onboarding cascades from `EVERIFY_PENDING` to `TERMINATED_NONCONFIRMED` and an `AuditEntry` with action `FINAL_NONCONFIRMATION` is appended."

    Design: Difficulty/transitive_cascade/everify_final_nonconfirm_cascade_to_termination
    """
    ob_s2, form = _through_section2_everify("Guha")
    case = submit_everify_case(ob_s2["id"], form["id"], ob_s2["version"])
    set_clock("2026-06-10T12:00:00Z")
    fx.get_success_data(api.everify_result(case["id"], {"result": "TNC", "agency": "SSA"}, OP))
    set_clock("2026-06-26T09:00:00Z")
    ob_after = fx.get_success_data(api.advance_lifecycle(ob_s2["id"], {}, OP))

    case_after = validate_success(api.get_everify_case(case["id"], OP))
    assert case_after["status"] == "FINAL_NONCONFIRMATION"
    assert ob_after["status"] == "TERMINATED_NONCONFIRMED"


def test_final_nonconfirmation_appends_audit_entry(api):
    """PRD §3.4: "in both cases the onboarding cascades from `EVERIFY_PENDING` to `TERMINATED_NONCONFIRMED` and an `AuditEntry` with action `FINAL_NONCONFIRMATION` is appended."

    Design: Difficulty/transitive_cascade/everify_final_nonconfirm_cascade_to_termination
    """
    ob_s2, form = _through_section2_everify("Guha2")
    case = submit_everify_case(ob_s2["id"], form["id"], ob_s2["version"])
    set_clock("2026-06-10T12:00:00Z")
    fx.get_success_data(api.everify_result(case["id"], {"result": "TNC", "agency": "SSA"}, OP))
    set_clock("2026-06-26T09:00:00Z")
    fx.get_success_data(api.advance_lifecycle(ob_s2["id"], {}, OP))

    body = api.list_audit_entries(CO, params={"onboarding_id": ob_s2["id"]}).json()
    actions = [e["action"] for e in body["data"]]
    assert "FINAL_NONCONFIRMATION" in actions, f"expected FINAL_NONCONFIRMATION audit, got {actions}"


# ===========================================================================
# Queue A — resource_temporal_overlap (referral window strict boundary)
# ===========================================================================
def test_referral_after_deadline_is_rejected(api):
    """PRD §3.4: "A referral is timely only when the clock is at or before `referral_deadline`; a referral attempted after that deadline has passed is rejected with `ERR_REFERRAL_WINDOW_CLOSED`."

    Design: Difficulty/resource_temporal_overlap/tnc_referral_window_strict_boundary
    """
    ob_s2, form = _through_section2_everify("Quvi")
    case = submit_everify_case(ob_s2["id"], form["id"], ob_s2["version"])
    set_clock("2026-06-10T12:00:00Z")
    fx.get_success_data(api.everify_result(case["id"], {"result": "TNC", "agency": "DHS"}, OP))
    set_clock("2026-06-26T09:00:00Z")
    resp = api.everify_refer(case["id"], {}, OP)
    validate_error(resp, ApiErrorId.ERR_REFERRAL_WINDOW_CLOSED.value, 422)


def test_referral_within_window_succeeds(api):
    """PRD §3.4: "A referral is timely only when the clock is at or before `referral_deadline`"
    PRD §3.4: "moving the case from `TNC_ISSUED` to `REFERRED`."

    Design: Difficulty/resource_temporal_overlap/tnc_referral_window_strict_boundary
    """
    ob_s2, form = _through_section2_everify("Quvi2")
    case = submit_everify_case(ob_s2["id"], form["id"], ob_s2["version"])
    set_clock("2026-06-10T12:00:00Z")
    fx.get_success_data(api.everify_result(case["id"], {"result": "TNC", "agency": "DHS"}, OP))
    data = validate_success(api.everify_refer(case["id"], {}, OP))
    assert data["status"] == "REFERRED"


# ===========================================================================
# Queue B — corner: state_machines (E-Verify side effects / preconditions)
# ===========================================================================
def test_everify_authorized_bubbles_onboarding_to_authorized(api):
    """PRD §3.4: "From `SUBMITTED`, an `AUTHORIZED` result moves the case to `EMPLOYMENT_AUTHORIZED` and cascades the onboarding from `EVERIFY_PENDING` to `AUTHORIZED`, appending an `AuditEntry` with action `AUTHORIZED`."

    Design: Corner/state_machines/everify_result_authorized_bubbles_onboarding_to_authorized
    """
    ob_s2, form = _through_section2_everify("Buup")
    case = submit_everify_case(ob_s2["id"], form["id"], ob_s2["version"])
    data = validate_success(api.everify_result(case["id"], {"result": "AUTHORIZED"}, OP))
    assert data["status"] == "EMPLOYMENT_AUTHORIZED"
    ob_after = validate_success(api.get_onboarding(ob_s2["id"], OP))
    assert ob_after["status"] == "AUTHORIZED"


def test_refer_from_submitted_without_tnc_returns_invalid_state(api):
    """PRD §3.4: "The employee's contest of a Tentative Nonconfirmation is recorded as a referral by an `EVerifyOperator`, moving the case from `TNC_ISSUED` to `REFERRED`."
    PRD §3.4: "A result recorded against a case not in the required state is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/refer_from_submitted_without_tnc_returns_invalid_state
    """
    ob_s2, form = _through_section2_everify("Notnc")
    case = submit_everify_case(ob_s2["id"], form["id"], ob_s2["version"])
    resp = api.everify_refer(case["id"], {}, OP)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


# ===========================================================================
# Queue B — corner: validations (late reason, duplicate case)
# ===========================================================================
def test_late_everify_submission_without_reason_returns_late_reason_required(api):
    """PRD §3.4: "The case is `was_late` exactly when `submitted_at` is strictly after `everify_deadline`. A late submission must carry a non-empty `late_reason`; a late case without one is rejected with `ERR_LATE_REASON_REQUIRED`."

    Design: Corner/validations/everify_late_submission_without_reason_returns_late_reason_required
    """
    ob_s2, form = _through_section2_everify("Late")
    set_clock("2026-06-10T09:00:00Z")
    resp = api.create_everify_case(
        {"onboarding_id": ob_s2["id"], "i9_form_id": form["id"],
         "expected_onboarding_version": ob_s2["version"]}, OP)
    validate_error(resp, ApiErrorId.ERR_LATE_REASON_REQUIRED.value, 422)


def test_duplicate_everify_case_returns_case_exists(api):
    """PRD §3.4: "A submission is refused with `ERR_EVERIFY_CASE_EXISTS` when any other non-terminal case — one whose status is not `EMPLOYMENT_AUTHORIZED` and not `FINAL_NONCONFIRMATION` — already exists for this onboarding; this duplicate guard additionally catches a second create while the onboarding is still in `SECTION2_COMPLETE`."

    Design: Corner/validations/duplicate_everify_case_returns_case_exists
    """
    ob_s2, form = _through_section2_everify("Dupl")
    submit_everify_case(ob_s2["id"], form["id"], ob_s2["version"])
    # observe the advanced version (onboarding moved to EVERIFY_PENDING, version bumped)
    ob_now = validate_success(api.get_onboarding(ob_s2["id"], OP))
    resp = api.create_everify_case(
        {"onboarding_id": ob_s2["id"], "i9_form_id": form["id"],
         "expected_onboarding_version": ob_now["version"]}, OP)
    validate_error(resp, ApiErrorId.ERR_EVERIFY_CASE_EXISTS.value, 409)


# ===========================================================================
# Queue B — corner: cross_cutting (everify deadline boundary, on-time)
# ===========================================================================
def test_everify_submission_exactly_at_deadline_is_on_time(api):
    """PRD §3.4: "The case is `was_late` exactly when `submitted_at` is strictly after `everify_deadline`."
    PRD §3.4: "computes `everify_deadline`, which equals the backing onboarding's `section2_deadline`"

    Design: Corner/cross_cutting_complexity_layers/everify_deadline_recomputed_on_late_threshold
    """
    ob_s2, form = _through_section2_everify("Thre")
    set_clock("2026-06-04T23:59:59.999Z")
    case = submit_everify_case(ob_s2["id"], form["id"], ob_s2["version"])
    assert case["was_late"] is False, "submitting exactly at the deadline is on time"
