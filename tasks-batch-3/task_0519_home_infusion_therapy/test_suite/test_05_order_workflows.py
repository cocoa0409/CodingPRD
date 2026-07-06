"""Order lifecycle workflows: the hold/resume cycle, the prior-auth fork, cross-entity
release dependency, the visit-complete order-state guard, and threshold boundaries.

Translates Queue A (Difficulty) rules: non_linear_state_machine,
cross_entity_state_dependency, boundary_precision_check.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_visiting_nurse_headers,
    fixtures,
    factories as F,
)

PHARM = TEST_USERS["pharmacist_headers"]
AUTH = TEST_USERS["auth_specialist_headers"]
MD = TEST_USERS["medical_director_headers"]
WAREHOUSE = TEST_USERS["warehouse_clerk_headers"]

VANCO_DRUG = {
    "therapy_category": "AMINOGLYCOSIDE_OR_VANCO",
    "vial_size_mg": 1000,
    "awp_per_vial_cents": 4250,
    "lot_total_vials": 100,
}
PA_PLAN = {
    "per_diem_rate_cents": {"AMINOGLYCOSIDE_OR_VANCO": 12500},
    "awp_discount_pct": 0.18,
    "coinsurance_pct": 0.20,
    "deductible_remaining_cents": 30000,
    "oop_max_remaining_cents": 50000,
}


# === non_linear_state_machine / order_hold_resume_cycle_active_to_onhold_to_active ===
def test_adverse_event_hold_drives_active_order_to_on_hold(api):
    """PRD 3.9: "an order in `RELEASED` or `ACTIVE` is driven to `ON_HOLD` with its `hold_reason` set to `ADVERSE_EVENT`."

    Design: Difficulty/non_linear_state_machine/order_hold_resume_cycle_active_to_onhold_to_active
    """
    ctx = fixtures.setup_order_on_hold_via_ae(
        scheduled_days=5,
        severity_grade=3, reaction_count=2, vital_instability=1,
        drug_overrides={**VANCO_DRUG, "is_specialty": False},
        plan_overrides=PA_PLAN,
    )
    assert ctx["order"]["status"] == "ON_HOLD"
    assert ctx["order"]["hold_reason"] == "ADVERSE_EVENT"


def test_resume_adjudication_returns_order_to_active_and_clears_hold(api):
    """PRD 3.10: "A `disposition` of `RESUME` moves the order from `ON_HOLD` back to `ACTIVE`, clears its `hold_reason` to null, and marks the event `ADJUDICATED`."

    Design: Difficulty/non_linear_state_machine/order_hold_resume_cycle_active_to_onhold_to_active
    """
    ctx = fixtures.setup_order_on_hold_via_ae(
        scheduled_days=5,
        severity_grade=3, reaction_count=2, vital_instability=1,
        drug_overrides={**VANCO_DRUG, "is_specialty": False},
        plan_overrides=PA_PLAN,
    )
    ae_id = ctx["adverse_event"]["id"]
    # Reported by the nurse; the MedicalDirector (a different identity) may resume.
    resp = api.adjudicate_adverse_event(ae_id, {"disposition": "RESUME"}, MD)
    validate_success(resp)
    order = validate_success(api.get_order(ctx["order"]["id"], MD))
    assert order["status"] == "ACTIVE"
    assert order["hold_reason"] is None
    ae = validate_success(api.get_adverse_event(ae_id, MD))
    assert ae["status"] == "ADJUDICATED"


# === non_linear_state_machine / prior_auth_branching_fork_approve_vs_deny_compound ===
def test_prior_auth_deny_discontinues_order_and_cancels_kits(api):
    """PRD 3.3: "Denial moves `SUBMITTED` to `DENIED` and cascades in the opposite direction: the order is driven from `PENDING_AUTH` to `DISCONTINUED`, and as part of that same cascade every supply kit for that order still in `PICKING` is moved to `CANCELLED`."

    Design: Difficulty/non_linear_state_machine/prior_auth_branching_fork_approve_vs_deny_compound
    """
    ctx = fixtures.setup_pending_auth_order(
        drug_overrides={**VANCO_DRUG}, plan_overrides=PA_PLAN
    )
    kit = validate_success(
        api.create_supply_kit(
            F.create_supply_kit_payload(
                order_id=ctx["order"]["id"], kit_type="START_OF_CARE", line_count=5
            ),
            WAREHOUSE,
        ),
        expected_status=201,
    )
    assert ctx["order"]["status"] == "PENDING_AUTH"
    assert ctx["auth"]["status"] == "SUBMITTED"
    validate_success(api.deny_prior_auth(ctx["auth"]["id"], AUTH))
    auth = validate_success(api.get_prior_auth(ctx["auth"]["id"], AUTH))
    assert auth["status"] == "DENIED"
    order = validate_success(api.get_order(ctx["order"]["id"], PHARM))
    assert order["status"] == "DISCONTINUED"
    kit = validate_success(api.get_supply_kit(kit["id"], WAREHOUSE))
    assert kit["status"] == "CANCELLED"


def test_prior_auth_approve_releases_order(api):
    """PRD 3.3: "On approval the authorization moves `SUBMITTED` to `APPROVED`, the `approved_units` are set from the approval request body, and the order is cascaded from `PENDING_AUTH` to `RELEASED` in the same request"

    Design: Difficulty/non_linear_state_machine/prior_auth_branching_fork_approve_vs_deny_compound
    """
    ctx = fixtures.setup_pending_auth_order(
        drug_overrides={**VANCO_DRUG}, plan_overrides=PA_PLAN
    )
    validate_success(
        api.approve_prior_auth(ctx["auth"]["id"], {"approved_units": 10}, AUTH)
    )
    auth = validate_success(api.get_prior_auth(ctx["auth"]["id"], AUTH))
    assert auth["status"] == "APPROVED"
    order = validate_success(api.get_order(ctx["order"]["id"], PHARM))
    assert order["status"] == "RELEASED"


# === cross_entity_state_dependency / order_release_depends_on_prior_auth_approved ===
def test_submitted_auth_leaves_order_in_pending_auth(api):
    """PRD 3.3: "A specialty order may never reach `RELEASED` without an approved authorization."
    PRD 3.3: "Approval requires that the referenced order is itself still `PENDING_AUTH`. On approval ... the order is cascaded from `PENDING_AUTH` to `RELEASED` in the same request"

    Design: Difficulty/cross_entity_state_dependency/order_release_depends_on_prior_auth_approved
    """
    ctx = fixtures.setup_pending_auth_order(
        drug_overrides={**VANCO_DRUG}, plan_overrides=PA_PLAN
    )
    # before approval, a SUBMITTED auth does not release the order
    assert ctx["order"]["status"] == "PENDING_AUTH"
    validate_success(
        api.approve_prior_auth(ctx["auth"]["id"], {"approved_units": 10}, AUTH)
    )
    order = validate_success(api.get_order(ctx["order"]["id"], PHARM))
    assert order["status"] == "RELEASED", "release is driven only by the linked auth reaching APPROVED"


def test_order_release_only_after_auth_approved(api):
    """PRD 3.3: "If the drug's `is_specialty` is true, the order moves from `DRAFT` to `PENDING_AUTH`, signaling that payer authorization is required before therapy may proceed."

    Design: Difficulty/cross_entity_state_dependency/order_release_depends_on_prior_auth_approved
    """
    ctx = fixtures.setup_pending_auth_order(
        drug_overrides={**VANCO_DRUG}, plan_overrides=PA_PLAN
    )
    order_before = validate_success(api.get_order(ctx["order"]["id"], PHARM))
    assert order_before["status"] == "PENDING_AUTH"
    auth = validate_success(api.get_prior_auth(ctx["auth"]["id"], AUTH))
    assert auth["status"] == "SUBMITTED"


# === cross_entity_state_dependency / visit_complete_depends_on_order_released_or_active ===
def test_visit_complete_blocked_when_order_on_hold(api):
    """PRD 3.7: "The visit must be `SCHEDULED` and its order must be in `RELEASED` or `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/visit_complete_depends_on_order_released_or_active
    """
    # Order ACTIVE via first visit; a second visit is scheduled with a past start_at so
    # the hold cascade (which only misses FUTURE visits) leaves it SCHEDULED. Then an AE
    # holds the order, and completing the still-SCHEDULED visit must fail on order state.
    ctx = fixtures.setup_released_nonspecialty_order(
        drug_overrides={**VANCO_DRUG, "is_specialty": False},
        plan_overrides=PA_PLAN,
        order_overrides={"daily_dose_mg": 2000, "scheduled_days": 5},
        clock="2026-06-09T00:00:00Z",
    )
    nurse = fixtures.add_nurse(ctx)
    nid = nurse["id"]
    v1 = fixtures.schedule_visit(
        ctx["order"]["id"], nid, start_at="2026-06-10T09:00:00Z", duration_min=120
    )
    v2 = fixtures.schedule_visit(
        ctx["order"]["id"], nid, start_at="2026-06-08T08:00:00Z", duration_min=60
    )
    fixtures.complete_visit(v1["id"], nid)
    # high-severity AE holds the ACTIVE order
    fixtures.report_adverse_event(
        ctx["order"]["id"], nurse_id=nid, visit_id=v1["id"],
        severity_grade=3, reaction_count=2, vital_instability=1,
    )
    order = validate_success(api.get_order(ctx["order"]["id"], PHARM))
    assert order["status"] == "ON_HOLD"
    v2_now = validate_success(api.get_visit(v2["id"], make_visiting_nurse_headers(nid)))
    assert v2_now["status"] == "SCHEDULED", "past-dated visit not swept by the future-only hold cascade"
    resp = api.complete_visit(v2["id"], make_visiting_nurse_headers(nid))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_visit_complete_allowed_when_order_released(api):
    """PRD 3.7: "The visit must be `SCHEDULED` and its order must be in `RELEASED` or `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/visit_complete_depends_on_order_released_or_active
    """
    ctx = fixtures.setup_released_nonspecialty_order(
        drug_overrides={**VANCO_DRUG, "is_specialty": False},
        plan_overrides=PA_PLAN,
        order_overrides={"daily_dose_mg": 2000, "scheduled_days": 5},
    )
    nurse = fixtures.add_nurse(ctx)
    v1 = fixtures.schedule_visit(
        ctx["order"]["id"], nurse["id"], start_at="2026-06-10T09:00:00Z", duration_min=120
    )
    resp = api.complete_visit(v1["id"], make_visiting_nurse_headers(nurse["id"]))
    data = validate_success(resp)
    assert data["status"] == "COMPLETED"


# === boundary_precision_check / ae_severity_threshold_seven_inclusive_holds ===
def test_ae_severity_exactly_seven_holds_order(api):
    """PRD 3.9: "When this `severity_score` reaches or exceeds the auto-hold threshold of 7, the reporting cascade automatically holds the order: an order in `RELEASED` or `ACTIVE` is driven to `ON_HOLD` with its `hold_reason` set to `ADVERSE_EVENT`."

    Design: Difficulty/boundary_precision_check/ae_severity_threshold_seven_inclusive_holds
    """
    # RELEASED specialty order, no visits; grade3 react1 vital0 => score 7 (>=7 holds)
    ctx = fixtures.setup_released_nonspecialty_order(
        drug_overrides={**VANCO_DRUG, "is_specialty": False},
        plan_overrides=PA_PLAN,
        order_overrides={"daily_dose_mg": 2000, "scheduled_days": 5},
    )
    ae = fixtures.report_adverse_event(
        ctx["order"]["id"], reporter_headers=MD,
        severity_grade=3, reaction_count=1, vital_instability=0,
    )
    assert ae["severity_score"] == 7
    order = validate_success(api.get_order(ctx["order"]["id"], PHARM))
    assert order["status"] == "ON_HOLD", "score 7 (>=7 inclusive) must hold"
    assert order["hold_reason"] == "ADVERSE_EVENT"


def test_ae_severity_six_does_not_hold_order(api):
    """PRD 3.9: "When this `severity_score` reaches or exceeds the auto-hold threshold of 7, the reporting cascade automatically holds the order:"

    Design: Difficulty/boundary_precision_check/ae_severity_threshold_seven_inclusive_holds
    """
    # grade2 react2 vital0 => score 6, just below the >= boundary, no hold
    ctx = fixtures.setup_released_nonspecialty_order(
        drug_overrides={**VANCO_DRUG, "is_specialty": False},
        plan_overrides=PA_PLAN,
        order_overrides={"daily_dose_mg": 2000, "scheduled_days": 5},
    )
    ae = fixtures.report_adverse_event(
        ctx["order"]["id"], reporter_headers=MD,
        severity_grade=2, reaction_count=2, vital_instability=0,
    )
    assert ae["severity_score"] == 6
    order = validate_success(api.get_order(ctx["order"]["id"], PHARM))
    assert order["status"] == "RELEASED", "score 6 < 7 must not hold"


# === boundary_precision_check / complete_order_administered_days_equals_scheduled_zero_remaining ===
def test_complete_order_at_administered_equals_scheduled_succeeds(api):
    """PRD 3.12: "a `Pharmacist` may move an order from `ACTIVE` to `COMPLETED` only when its `administered_days` are at least its `scheduled_days`"

    Design: Difficulty/boundary_precision_check/complete_order_administered_days_equals_scheduled_zero_remaining
    """
    # scheduled_days=2, exactly 2 visits completed => administered_days==2 (equality)
    ctx = fixtures.setup_active_order_with_completed_visits(
        num_completed=2,
        scheduled_days=2,
        drug_overrides={"therapy_category": "ANTI_INFECTIVE", "vial_size_mg": 1000, "awp_per_vial_cents": 2000},
        plan_overrides={"per_diem_rate_cents": {"ANTI_INFECTIVE": 12500}},
        order_overrides={"daily_dose_mg": 1000},
    )
    order = validate_success(api.get_order(ctx["order"]["id"], PHARM))
    assert order["administered_days"] == 2 and order["scheduled_days"] == 2
    resp = api.complete_order(ctx["order"]["id"], PHARM)
    data = validate_success(resp)
    assert data["status"] == "COMPLETED", "equality satisfies the at-least condition"


def test_complete_order_below_scheduled_rejected(api):
    """PRD 3.12: "attempting to complete an order whose administered days still fall short of its scheduled days is rejected with `ERR_THERAPY_INCOMPLETE`."

    Design: Difficulty/boundary_precision_check/complete_order_administered_days_equals_scheduled_zero_remaining
    """
    # scheduled_days=2, only 1 visit completed => administered_days==1 < 2
    ctx = fixtures.setup_active_order_with_completed_visits(
        num_completed=1,
        scheduled_days=2,
        drug_overrides={"therapy_category": "ANTI_INFECTIVE", "vial_size_mg": 1000, "awp_per_vial_cents": 2000},
        plan_overrides={"per_diem_rate_cents": {"ANTI_INFECTIVE": 12500}},
        order_overrides={"daily_dose_mg": 1000},
    )
    resp = api.complete_order(ctx["order"]["id"], PHARM)
    validate_error(resp, ApiErrorId.ERR_THERAPY_INCOMPLETE.value)
