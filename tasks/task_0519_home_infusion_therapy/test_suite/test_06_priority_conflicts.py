"""Validation precedence: which error wins when more than one check could fail.

Translates Queue A (Difficulty) rule: priority_pair_validation_conflict. Each test
constructs a request where the higher-priority check is the one PRD pins as the
returned error.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_visiting_nurse_headers,
    fixtures,
)

PHARM = TEST_USERS["pharmacist_headers"]
MD = TEST_USERS["medical_director_headers"]
BILLER = TEST_USERS["biller_headers"]

VANCO_NONSPEC = {
    "therapy_category": "AMINOGLYCOSIDE_OR_VANCO",
    "vial_size_mg": 1000,
    "awp_per_vial_cents": 4250,
    "is_specialty": False,
}
PA_PLAN = {
    "per_diem_rate_cents": {"AMINOGLYCOSIDE_OR_VANCO": 12500},
    "awp_discount_pct": 0.18,
    "coinsurance_pct": 0.20,
    "deductible_remaining_cents": 30000,
    "oop_max_remaining_cents": 50000,
}


# === priority_pair_validation_conflict / forbidden_role_beats_invalid_state_on_adjudicate ===
def test_forbidden_role_preempts_invalid_state_on_adjudicate(api):
    """PRD 2.8: "The order is: ... (2) authorization of the role (`ERR_FORBIDDEN_ROLE`);
    ... and (5) state legality, i.e. the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`, HTTP 409)."
    PRD 2.1: "When the headers are present but the named role is not permitted to invoke the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Difficulty/priority_pair_validation_conflict/forbidden_role_beats_invalid_state_on_adjudicate
    """
    # ACTIVE order (not ON_HOLD) with a low-severity REPORTED adverse event.
    ctx = fixtures.setup_active_order_with_completed_visits(
        num_completed=1, scheduled_days=5,
        drug_overrides=VANCO_NONSPEC, plan_overrides=PA_PLAN,
        order_overrides={"daily_dose_mg": 2000},
    )
    nurse = ctx["nurse"]
    # grade2 react1 vital0 => score 5, no hold; order stays ACTIVE
    ae = fixtures.report_adverse_event(
        ctx["order"]["id"], nurse_id=nurse["id"],
        severity_grade=2, reaction_count=1, vital_instability=0,
    )
    assert ae["severity_score"] == 5
    order = validate_success(api.get_order(ctx["order"]["id"], PHARM))
    assert order["status"] == "ACTIVE", "order must NOT be ON_HOLD for this pairing"
    # Biller (forbidden role) adjudicates: role check (priority 2) precedes state check.
    resp = api.adjudicate_adverse_event(ae["id"], {"disposition": "RESUME"}, BILLER)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_authorized_role_on_non_held_order_hits_state_error(api):
    """PRD 3.10: "Adjudication is permitted only while the event is `REPORTED` and the order is `ON_HOLD`."
    PRD 2.8: "(5) state legality ... (ERR_INVALID_STATE, HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/forbidden_role_beats_invalid_state_on_adjudicate
    """
    # Same construction but the correct MedicalDirector role; with the order ACTIVE
    # (not ON_HOLD) the state check is the next failure, isolating it from the role check.
    ctx = fixtures.setup_active_order_with_completed_visits(
        num_completed=1, scheduled_days=5,
        drug_overrides=VANCO_NONSPEC, plan_overrides=PA_PLAN,
        order_overrides={"daily_dose_mg": 2000},
    )
    nurse = ctx["nurse"]
    ae = fixtures.report_adverse_event(
        ctx["order"]["id"], nurse_id=nurse["id"],
        severity_grade=2, reaction_count=1, vital_instability=0,
    )
    order = validate_success(api.get_order(ctx["order"]["id"], PHARM))
    assert order["status"] == "ACTIVE"
    resp = api.adjudicate_adverse_event(ae["id"], {"disposition": "RESUME"}, MD)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# === priority_pair_validation_conflict / segregation_of_duties_beats_lab_overdue_pairing ===
def test_self_reported_adjudication_blocked_by_segregation_of_duties(api):
    """PRD 3.10: "the adjudicating operator's `X-User-ID` must differ from the event's `reported_by_user_id`: the clinician who reported a reaction may not be the one who clears the hold it caused. An attempt to adjudicate an event one personally reported is rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_beats_lab_overdue_pairing
    """
    # Trough-monitored order held by an AE the MedicalDirector md-001 personally
    # reported; md-001 then attempts to adjudicate it. Segregation of duties fires.
    ctx = fixtures.setup_order_on_hold_via_ae(
        scheduled_days=5,
        severity_grade=3, reaction_count=2, vital_instability=1,
        drug_overrides={**VANCO_NONSPEC, "requires_trough_lab": True},
        plan_overrides=PA_PLAN,
        reporter="md",
    )
    assert ctx["order"]["status"] == "ON_HOLD"
    ae_id = ctx["adverse_event"]["id"]
    # md-001 is the reporter (TEST_USERS medical_director_headers carries md-001)
    resp = api.adjudicate_adverse_event(ae_id, {"disposition": "RESUME"}, MD)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


def test_different_director_can_adjudicate_self_report_barred_only_for_reporter(api):
    """PRD 3.10: "the adjudicating operator's `X-User-ID` must differ from the event's `reported_by_user_id ... This is why the `VisitingNurse` identity is entity-backed"

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_beats_lab_overdue_pairing
    """
    # Event reported by the nurse; a MedicalDirector (different identity) clears it.
    ctx = fixtures.setup_order_on_hold_via_ae(
        scheduled_days=5,
        severity_grade=3, reaction_count=2, vital_instability=1,
        drug_overrides={**VANCO_NONSPEC, "requires_trough_lab": True},
        plan_overrides=PA_PLAN,
        reporter="nurse",
    )
    ae_id = ctx["adverse_event"]["id"]
    resp = api.adjudicate_adverse_event(ae_id, {"disposition": "RESUME"}, MD)
    data = validate_success(resp)
    assert data["status"] == "ADJUDICATED"
