"""Transitive cascade chains from a single trigger (adverse event, unsafe lab review)."""
from test_helpers import (
    api_client, get_success_data, TEST_USERS,
    create_clinician, create_reviewed_panel, create_refill,
    setup_plan_with_prescription, get_plan, get_prescription, get_refill,
    create_adverse_event_payload, make_clinician_headers, make_patient_headers,
)

ADMIN = TEST_USERS["clinic_admin_headers"]


def _setup_severe_ready():
    """ACTIVE plan (clinician1 owner) + ISSUED prescription + one PENDING refill +
    a REPORTED adverse event; a second clinician available to triage."""
    ctx = setup_plan_with_prescription()
    refill = create_refill(ctx)
    ctx["refill_id"] = refill["id"]
    reviewer = create_clinician()
    ctx["reviewer_headers"] = make_clinician_headers(reviewer["id"])
    event = get_success_data(api_client.create_adverse_event(
        create_adverse_event_payload(ctx["patient_id"], ctx["plan_id"], description="chest pain"),
        make_patient_headers(ctx["patient_id"]),
    ))
    ctx["ae_id"] = event["id"]
    return ctx


def test_severe_triage_suspends_plan(api):
    """PRD §3.7: "A `SEVERE` triage sets the event's `severity` to `SEVERE`, moves it to
    `SEVERE_ESCALATED`, and suspends the implicated plan (cascade link 1 into §3.5's
    suspension chain), which then revokes the plan's prescriptions and cancels their
    pending refills."

    Design: Difficulty/transitive_cascade/severe_adverse_event_depth3_cascade
    """
    ctx = _setup_severe_ready()
    event = get_success_data(api.triage_adverse_event(ctx["ae_id"], {"severity": "SEVERE"}, ctx["reviewer_headers"]))
    assert event["status"] == "SEVERE_ESCALATED"
    assert get_plan(ctx["plan_id"])["status"] == "SUSPENDED"


def test_severe_triage_revokes_prescription_and_cancels_refill(api):
    """PRD §3.7: "which then revokes the plan's prescriptions and cancels their pending
    refills."
    PRD §3.5: "every issued or suspended controlled-substance prescription linked to
    the plan is revoked — which itself cascades to cancel that prescription's pending
    refills".

    Design: Difficulty/transitive_cascade/severe_adverse_event_depth3_cascade
    """
    ctx = _setup_severe_ready()
    get_success_data(api.triage_adverse_event(ctx["ae_id"], {"severity": "SEVERE"}, ctx["reviewer_headers"]))
    assert get_prescription(ctx["rx_id"])["status"] == "REVOKED"
    assert get_refill(ctx["refill_id"])["status"] == "CANCELLED"


def _setup_unsafe_review(api):
    """ACTIVE plan + ISSUED prescription; return (ctx, reviewed unsafe panel)."""
    ctx = setup_plan_with_prescription()
    panel = create_reviewed_panel(
        ctx["patient_id"], ctx["clinician_id"], panel_type="MONITORING",
        results={"total_testosterone_ng_dl": 500, "psa_ng_ml": 1.5, "hematocrit_pct": 56.0, "drawn_at": "2026-04-28T09:00:00Z"},
    )
    return ctx, panel


def test_unsafe_review_holds_plan(api):
    """PRD §3.3: "a panel is unsafe when its `hematocrit_pct` is at or above 54.0, or
    its `psa_ng_ml` is at or above 4.0."
    PRD §3.3: "When a reviewed panel is unsafe and the patient has a treatment plan
    currently in the `ACTIVE` state, the system moves that plan from `ACTIVE` to
    `MONITORING_HOLD` (cascade link 1)."

    Design: Difficulty/transitive_cascade/lab_review_unsafe_depth2_cascade
    """
    ctx, panel = _setup_unsafe_review(api)
    assert panel["is_unsafe"] is True
    assert get_plan(ctx["plan_id"])["status"] == "MONITORING_HOLD"


def test_unsafe_review_suspends_prescription(api):
    """PRD §3.3: "That hold, in turn, suspends the plan's issued controlled-substance
    prescription, as described in §3.5 and §3.6."

    Design: Difficulty/transitive_cascade/lab_review_unsafe_depth2_cascade
    """
    ctx, _ = _setup_unsafe_review(api)
    assert get_prescription(ctx["rx_id"])["status"] == "SUSPENDED"
