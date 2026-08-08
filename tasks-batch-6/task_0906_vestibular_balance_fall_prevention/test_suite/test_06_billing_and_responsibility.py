"""Attendance/billing dimensions, copay rounding, estimated vs billed
responsibility, and the two compensating invariants."""
from test_helpers import (
    validate_success, get_success_data,
    TEST_USERS,
    setup_plan_with_approved_auth, schedule_session,
)

INTAKE = TEST_USERS["intake_headers"]
SUPER = TEST_USERS["supervisor_headers"]


# --- A2: dual_variant_calc / estimated_vs_billed_responsibility_on_care_plan --

def test_estimated_responsibility_on_authorization_approve(api):
    """PRD §3.4: "computes the plan's forward-looking
    estimated_patient_responsibility_cents as the plan's target_visits multiplied
    by the per-visit copay, where the per-visit copay is the authorization's
    allowed_amount_cents multiplied by its coinsurance_pct, rounded half-up to
    whole cents."

    Design: Difficulty/dual_variant_calc/estimated_vs_billed_responsibility_on_care_plan
    """
    ctx = setup_plan_with_approved_auth(
        api, auth_overrides={"visits_authorized": 5, "allowed_amount_cents": 15000,
                             "coinsurance_pct": 0.20})
    plan = get_success_data(api.get_care_plan(ctx["care_plan"]["id"], INTAKE))
    # HIGH plan target_visits 12 * round_half_up(15000*0.20)=3000 -> 36000
    assert plan["estimated_patient_responsibility_cents"] == 36000


def test_billed_responsibility_diverges_from_estimate(api):
    """PRD §3.6: "The running patient_responsibility_cents is always the sum of the
    per-session copay_cents over the plan's sessions whose billing_status is
    BILLED." PRD §3.6: "This billed total diverges from the estimate of §3.4
    whenever the number of delivered visits differs from the plan's target_visits."

    Design: Difficulty/dual_variant_calc/estimated_vs_billed_responsibility_on_care_plan
    """
    ctx = setup_plan_with_approved_auth(
        api, auth_overrides={"visits_authorized": 5, "allowed_amount_cents": 15000,
                             "coinsurance_pct": 0.20})
    s = schedule_session(api, ctx, scheduled_start="2026-06-01T10:00:00Z",
                         scheduled_end="2026-06-01T11:00:00Z")
    validate_success(api.attend_session(s["id"], ctx["clinician_headers"]), 200)
    plan = get_success_data(api.get_care_plan(ctx["care_plan"]["id"], INTAKE))
    assert plan["patient_responsibility_cents"] == 3000
    assert plan["estimated_patient_responsibility_cents"] != plan["patient_responsibility_cents"]


# --- A4: combinatorial_formula / copay_round_per_session_then_sum_mode_b ------

def test_session_copay_rounds_half_up_per_session(api):
    """PRD §2.4: "Wherever a copay is derived from a payer allowed amount and a
    coinsurance fraction, the product is rounded to the nearest whole cent using
    the round-half-up convention (a value exactly halfway between two cents rounds
    up)."

    Design: Difficulty/combinatorial_formula/copay_round_per_session_then_sum_mode_b
    """
    ctx = setup_plan_with_approved_auth(
        api, auth_overrides={"visits_authorized": 5, "allowed_amount_cents": 3333,
                             "coinsurance_pct": 0.20})
    s = schedule_session(api, ctx, scheduled_start="2026-06-01T10:00:00Z",
                         scheduled_end="2026-06-01T11:00:00Z")
    attended = validate_success(api.attend_session(s["id"], ctx["clinician_headers"]), 200)
    # round_half_up(3333 * 0.20) = round_half_up(666.6) = 667
    assert attended["copay_cents"] == 667


def test_patient_responsibility_rounds_per_session_then_sums(api):
    """PRD §3.6: "Each session's copay is rounded to whole cents when it is stamped
    at attend time, and the running total adds those already-rounded integers -
    copays are rounded per session first and only then summed."

    Design: Difficulty/combinatorial_formula/copay_round_per_session_then_sum_mode_b
    """
    ctx = setup_plan_with_approved_auth(
        api, auth_overrides={"visits_authorized": 5, "allowed_amount_cents": 3333,
                             "coinsurance_pct": 0.20})
    s1 = schedule_session(api, ctx, scheduled_start="2026-06-01T10:00:00Z",
                          scheduled_end="2026-06-01T11:00:00Z")
    s2 = schedule_session(api, ctx, scheduled_start="2026-06-01T11:15:00Z",
                          scheduled_end="2026-06-01T12:15:00Z")
    s3 = schedule_session(api, ctx, scheduled_start="2026-06-01T12:30:00Z",
                          scheduled_end="2026-06-01T13:30:00Z")
    for s in (s1, s2, s3):
        validate_success(api.attend_session(s["id"], ctx["clinician_headers"]), 200)
    plan = get_success_data(api.get_care_plan(ctx["care_plan"]["id"], INTAKE))
    # 667 * 3 = 2001 (round-per-session-then-sum); sum-then-round would give 2000
    assert plan["patient_responsibility_cents"] == 2001


# --- A6: non_linear_state_machine / session_attendance_billing_parallel ------

def test_attend_then_cancel_evolves_both_dimensions(api):
    """PRD §3.6: "An ATTENDED session may also be cancelled as a compensating
    action: its attendance_status becomes CANCELLED, its billing_status becomes
    REVERSED, the stamped copay_cents is subtracted back out of the plan's
    patient_responsibility_cents".

    Design: Difficulty/non_linear_state_machine/session_attendance_billing_parallel
    """
    ctx = setup_plan_with_approved_auth(
        api, auth_overrides={"allowed_amount_cents": 15000, "coinsurance_pct": 0.20})
    s = schedule_session(api, ctx, scheduled_start="2026-06-01T10:00:00Z",
                         scheduled_end="2026-06-01T11:00:00Z")
    validate_success(api.attend_session(s["id"], ctx["clinician_headers"]), 200)
    cancelled = validate_success(api.cancel_session(s["id"], SUPER), 200)
    assert cancelled["attendance_status"] == "CANCELLED"
    assert cancelled["billing_status"] == "REVERSED"


def test_attend_sets_attended_and_billed_independently(api):
    """PRD §3.6: "When the owning `Clinician` marks a `SCHEDULED` session attended,
    its `attendance_status` becomes `ATTENDED` and, on the billing dimension, its
    `billing_status` becomes `BILLED`."

    Design: Difficulty/non_linear_state_machine/session_attendance_billing_parallel
    """
    ctx = setup_plan_with_approved_auth(
        api, auth_overrides={"allowed_amount_cents": 15000, "coinsurance_pct": 0.20})
    s = schedule_session(api, ctx, scheduled_start="2026-06-01T10:00:00Z",
                         scheduled_end="2026-06-01T11:00:00Z")
    attended = validate_success(api.attend_session(s["id"], ctx["clinician_headers"]), 200)
    assert attended["attendance_status"] == "ATTENDED"
    assert attended["billing_status"] == "BILLED"


# --- A17: compensating_invariant / visit_pool_conserved_on_schedule_then_cancel

def test_schedule_then_cancel_releases_reserved_visit(api):
    """PRD §2.6: "whenever a session is cancelled the counter is recomputed
    downward." PRD §3.6: "A SCHEDULED session may be cancelled: its
    attendance_status becomes CANCELLED and its authorization's visits_used is
    recomputed downward, releasing the reservation".

    Design: Difficulty/compensating_invariant/visit_pool_conserved_on_schedule_then_cancel
    """
    ctx = setup_plan_with_approved_auth(api)
    s = schedule_session(api, ctx, scheduled_start="2026-06-01T10:00:00Z",
                         scheduled_end="2026-06-01T11:00:00Z")
    validate_success(api.cancel_session(s["id"], INTAKE), 200)
    auth = get_success_data(api.get_authorization(ctx["authorization"]["id"], INTAKE))
    assert auth["visits_used"] == 0


def test_cancelled_scheduled_session_status(api):
    """PRD §3.6: "A SCHEDULED session may be cancelled: its attendance_status
    becomes CANCELLED ... because such a session was never billed, no billing
    reversal occurs."

    Design: Difficulty/compensating_invariant/visit_pool_conserved_on_schedule_then_cancel
    """
    ctx = setup_plan_with_approved_auth(api)
    s = schedule_session(api, ctx, scheduled_start="2026-06-01T10:00:00Z",
                         scheduled_end="2026-06-01T11:00:00Z")
    cancelled = validate_success(api.cancel_session(s["id"], INTAKE), 200)
    assert cancelled["attendance_status"] == "CANCELLED"
    assert cancelled["billing_status"] == "UNBILLED"


# --- A18: compensating_invariant / patient_responsibility_conserved_on_attend_then_cancel

def test_attend_then_cancel_zeroes_patient_responsibility(api):
    """PRD §3.6: "its `billing_status` becomes `REVERSED`, the stamped `copay_cents`
    is subtracted back out of the plan's `patient_responsibility_cents`, and its
    authorization's `visits_used` is recomputed downward."

    Design: Difficulty/compensating_invariant/patient_responsibility_conserved_on_attend_then_cancel
    """
    ctx = setup_plan_with_approved_auth(
        api, auth_overrides={"allowed_amount_cents": 15000, "coinsurance_pct": 0.20})
    s = schedule_session(api, ctx, scheduled_start="2026-06-01T10:00:00Z",
                         scheduled_end="2026-06-01T11:00:00Z")
    validate_success(api.attend_session(s["id"], ctx["clinician_headers"]), 200)
    validate_success(api.cancel_session(s["id"], SUPER), 200)
    plan = get_success_data(api.get_care_plan(ctx["care_plan"]["id"], INTAKE))
    assert plan["patient_responsibility_cents"] == 0


def test_attend_stamps_copay_then_reverse_on_cancel(api):
    """PRD §3.6: "At that moment the system stamps `copay_cents` as the session
    authorization's `allowed_amount_cents` multiplied by its `coinsurance_pct`,
    rounded half-up to whole cents". PRD §3.6: "its `billing_status` becomes
    `REVERSED`".

    Design: Difficulty/compensating_invariant/patient_responsibility_conserved_on_attend_then_cancel
    """
    ctx = setup_plan_with_approved_auth(
        api, auth_overrides={"allowed_amount_cents": 15000, "coinsurance_pct": 0.20})
    s = schedule_session(api, ctx, scheduled_start="2026-06-01T10:00:00Z",
                         scheduled_end="2026-06-01T11:00:00Z")
    attended = validate_success(api.attend_session(s["id"], ctx["clinician_headers"]), 200)
    assert attended["copay_cents"] == 3000
    cancelled = validate_success(api.cancel_session(s["id"], SUPER), 200)
    assert cancelled["billing_status"] == "REVERSED"
    assert cancelled["copay_cents"] == 3000
