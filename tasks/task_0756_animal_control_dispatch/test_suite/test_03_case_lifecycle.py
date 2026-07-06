"""Case opening, investigation risk scoring, resolution, reopening, closure."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    TEST_USERS, make_field_officer_headers,
    open_case, investigating_case, substantiated_case, issue_citation,
    make_complaint, make_officer,
    create_case_payload, create_note_payload,
    assert_investigation_note,
)

SUPERVISOR = TEST_USERS["supervisor_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]

# A DOG/BITE complaint scores 50 * 1.2 = 60.00, so a BITE case built on it has
# provisional risk 40 + 0.5*60 = 70.00 and final risk 70 + 20 = 90.00.
BITE_COMPLAINT = {"animal_type": "DOG", "complaint_type": "BITE"}


# ==========================================================================
# Difficulty: dual_variant_calc / case_risk_provisional_vs_final
# ==========================================================================
def test_provisional_risk_on_investigate_is_70(api):
    """PRD 3.4: "The provisional score sums a type weight — 40 for a bite case,
    35 for dangerous-dog, 30 for cruelty, and 10 for stray — with a severity
    component equal to the linked complaint's severity_score multiplied by 0.5
    and rounded half up to two decimal places, and then clamps the result to the
    range 0 through 100."

    Design: Difficulty/dual_variant_calc/case_risk_provisional_vs_final
    """
    ctx = investigating_case(api, case_type="BITE", complaint_overrides=BITE_COMPLAINT)
    assert ctx["case"]["risk_score"] == pytest.approx(70.00, abs=0.01)


def test_final_risk_on_substantiate_adds_bonus_to_90(api):
    """PRD 3.4: "Resolving as substantiated advances the case from
    UNDER_INVESTIGATION to SUBSTANTIATED, stamps substantiated_at from the
    logical clock, and sets the final risk_score: the same type weight plus the
    same half-severity component, plus a substantiation bonus of 20 points, the
    whole clamped to 0 through 100."

    Design: Difficulty/dual_variant_calc/case_risk_provisional_vs_final
    """
    ctx = substantiated_case(api, case_type="BITE", complaint_overrides=BITE_COMPLAINT)
    assert ctx["case"]["status"] == "SUBSTANTIATED"
    assert ctx["case"]["risk_score"] == pytest.approx(90.00, abs=0.01)


# ==========================================================================
# Difficulty: non_linear_state_machine / case_cyclic_reopen_after_substantiated
# ==========================================================================
def test_reopen_substantiated_case_recomputes_provisional(api):
    """PRD 3.4: "a Supervisor may reopen it, driving it from SUBSTANTIATED back
    to UNDER_INVESTIGATION. Reopening clears substantiated_at (setting it back to
    null) and recomputes the provisional risk_score exactly as the initial
    investigate transition does."

    Design: Difficulty/non_linear_state_machine/case_cyclic_reopen_after_substantiated
    """
    ctx = substantiated_case(api, case_type="BITE", complaint_overrides=BITE_COMPLAINT)
    reopened = validate_success(api.investigate_case(ctx["case"]["id"], SUPERVISOR))
    assert reopened["status"] == "UNDER_INVESTIGATION"
    assert reopened["substantiated_at"] is None
    assert reopened["risk_score"] == pytest.approx(70.00, abs=0.01)


def test_reopen_clears_substantiated_at(api):
    """PRD 3.4: "Resolving as substantiated advances the case from
    UNDER_INVESTIGATION to SUBSTANTIATED, stamps substantiated_at from the
    logical clock, and sets the final risk_score: the same type weight plus the
    same half-severity component, plus a substantiation bonus of 20 points, the
    whole clamped to 0 through 100." PRD 3.4: "Reopening clears substantiated_at
    (setting it back to null) and recomputes the provisional risk_score exactly
    as the initial investigate transition does."

    Design: Difficulty/non_linear_state_machine/case_cyclic_reopen_after_substantiated
    """
    ctx = substantiated_case(api, case_type="BITE", complaint_overrides=BITE_COMPLAINT)
    assert ctx["case"]["substantiated_at"] is not None
    reopened = validate_success(api.investigate_case(ctx["case"]["id"], SUPERVISOR))
    assert reopened["substantiated_at"] is None


# ==========================================================================
# Difficulty: cross_entity_state_dependency / case_close_blocked_by_issued_citation
# ==========================================================================
def test_close_blocked_by_issued_citation(api):
    """PRD 3.8: "it may not close while any citation on it remains in ISSUED
    (ERR_OUTSTANDING_CITATIONS)."

    Design: Difficulty/cross_entity_state_dependency/case_close_blocked_by_issued_citation
    """
    ctx = investigating_case(api, case_type="STRAY")
    issue_citation(api, ctx["case"]["id"], violation_code="UNLICENSED", issued_to_ref="OWNER-2")
    validate_success(api.resolve_case(ctx["case"]["id"], {"resolution": "SUBSTANTIATED"}, SUPERVISOR))
    resp = api.close_case(ctx["case"]["id"], SUPERVISOR)
    validate_error(resp, ApiErrorId.ERR_OUTSTANDING_CITATIONS)


def test_close_blocked_by_citation_leaves_case_substantiated(api):
    """PRD 3.8: "A case may be closed only from SUBSTANTIATED or UNFOUNDED." PRD
    3.8: "it may not close while any citation on it remains in ISSUED
    (ERR_OUTSTANDING_CITATIONS)."

    Design: Difficulty/cross_entity_state_dependency/case_close_blocked_by_issued_citation
    """
    ctx = investigating_case(api, case_type="STRAY")
    issue_citation(api, ctx["case"]["id"], violation_code="UNLICENSED", issued_to_ref="OWNER-2")
    validate_success(api.resolve_case(ctx["case"]["id"], {"resolution": "SUBSTANTIATED"}, SUPERVISOR))
    validate_error(api.close_case(ctx["case"]["id"], SUPERVISOR), ApiErrorId.ERR_OUTSTANDING_CITATIONS)
    case_after = validate_success(api.get_case(ctx["case"]["id"], SUPERVISOR))
    assert case_after["status"] == "SUBSTANTIATED"


# ==========================================================================
# Corner: state_machines
# ==========================================================================
def test_close_open_case_is_invalid_state(api):
    """PRD 3.8: "A case may be closed only from SUBSTANTIATED or UNFOUNDED."

    Design: Corner/state_machines/close_open_case_returns_invalid_state
    """
    ctx = open_case(api, case_type="STRAY")
    resp = api.close_case(ctx["case"]["id"], SUPERVISOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ==========================================================================
# Corner: entities
# ==========================================================================
def test_investigation_note_is_immutable_without_version(api):
    """PRD 2.4: "An InvestigationNote is an append-only, immutable audit record:
    it carries only id and created_at. It has no updated_at and no version,
    because once written it is never modified."

    Design: Corner/entities/investigation_note_immutable_no_version
    """
    ctx = open_case(api, case_type="CRUELTY")
    resp = api.add_note(ctx["case"]["id"], create_note_payload(
        note_type="OBSERVATION", body="Animal appears healthy."), SUPERVISOR)
    note = validate_success(resp, expected_status=201)
    assert_investigation_note(note)
    assert note["case_id"] == ctx["case"]["id"]
    assert "version" not in note, "immutable note must not carry version"
    assert "updated_at" not in note, "immutable note must not carry updated_at"


# ==========================================================================
# Corner: endpoints (listing / pagination)
# ==========================================================================
def test_cases_list_pagination_defaults(api):
    """PRD 2.3: "The limit parameter caps the number of items returned; it
    defaults to 10, with a minimum of 1 and a maximum of 100." PRD 2.3: "where
    total_count is the number of matching rows before pagination and has_more
    indicates whether rows remain beyond the current page."

    Design: Corner/endpoints/cases_list_pagination_defaults
    """
    officer = make_officer(api, name="PG Ofc", badge_number="PGB1")
    c1 = make_complaint(api, reporter_name="PG1", complaint_type="STRAY")
    c2 = make_complaint(api, reporter_name="PG2", complaint_type="STRAY")
    validate_success(api.create_case(create_case_payload(c1["id"], officer["id"], "STRAY"), SUPERVISOR), 201)
    validate_success(api.create_case(create_case_payload(c2["id"], officer["id"], "CRUELTY"), SUPERVISOR), 201)
    data, meta = validate_paginated(api.list_cases(DISPATCHER))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert len(data) == 2


# ==========================================================================
# Corner: rbac
# ==========================================================================
def test_field_officer_cannot_close_case(api):
    """PRD 3.8: "Closing a case is a Supervisor-only act and the terminal step in
    a case's life." PRD 2.1: "When the headers are well-formed but the named role
    is not permitted to perform the requested operation, the request is rejected
    with ERR_UNAUTHORIZED."

    Design: Corner/rbac/fieldofficer_cannot_close_case
    """
    ctx = open_case(api, case_type="STRAY")
    resp = api.close_case(ctx["case"]["id"], make_field_officer_headers(ctx["officer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
