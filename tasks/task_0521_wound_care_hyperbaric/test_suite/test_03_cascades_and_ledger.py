"""Cascade and conserved-quantity (ledger) tests. Pinned to PRD §3.9, §3.5,
§3.8, §3.6.
"""
import pytest

from test_helpers import (
    validate_success,
    fixtures, factories,
    make_wound_clinician_headers, make_hyperbaric_tech_headers,
)


# =============================================================================
# transitive_cascade — depth-4 from acute transfer (queue A)
# =============================================================================

def test_acute_transfer_cascades_patient_plan_session_chamber(api):
    """PRD §3.9: "Initiating a transfer cascades through the patient and plan:
    the patient moves from IN_CARE to TRANSFERRED; the patient's ACTIVE treatment
    plan is suspended to SUSPENDED; that plan's SCHEDULED HBO sessions are
    cancelled to CANCELLED; and each cancelled session decrements its chamber's
    occupied_slot_count by one."
    A single INITIATE drives Patient=TRANSFERRED -> plan=SUSPENDED ->
    session=CANCELLED -> chamber occupied_slot_count 1 -> 0.

    Design: Difficulty/transitive_cascade/acute_transfer_depth4_cascade_to_chamber
    """
    base = fixtures.setup_active_covered_plan_with_chamber(mrn="M7")
    ht_id = base["ht_id"]
    sess = fixtures.schedule_hbo_session(base["plan_id"], base["chamber_id"], ht_id)
    # precondition: chamber occupied
    chamber = validate_success(api.get_chamber(base["chamber_id"], fixtures.INTAKE))
    assert chamber["occupied_slot_count"] == 1

    fixtures.initiate_transfer(base["patient_id"])

    patient = validate_success(api.get_patient(base["patient_id"], fixtures.INTAKE))
    assert patient["status"] == "TRANSFERRED"
    plan = validate_success(api.get_treatment_plan(
        base["plan_id"], make_wound_clinician_headers(base["wc_id"])))
    assert plan["status"] == "SUSPENDED"
    session = validate_success(api.get_hbo_session(sess["id"], fixtures.INTAKE))
    assert session["status"] == "CANCELLED"
    chamber = validate_success(api.get_chamber(base["chamber_id"], fixtures.INTAKE))
    assert chamber["occupied_slot_count"] == 0


def test_acute_transfer_cascade_intermediate_plan_suspended(api):
    """PRD §3.9: "the patient's ACTIVE treatment plan is suspended to SUSPENDED".
    The plan reached via the transfer cascade is observably SUSPENDED (not the
    only assertion — this isolates the middle hop).

    Design: Difficulty/transitive_cascade/acute_transfer_depth4_cascade_to_chamber
    """
    base = fixtures.setup_active_covered_plan_with_chamber(mrn="M7b")
    fixtures.schedule_hbo_session(base["plan_id"], base["chamber_id"], base["ht_id"])
    fixtures.initiate_transfer(base["patient_id"])
    plan = validate_success(api.get_treatment_plan(
        base["plan_id"], make_wound_clinician_headers(base["wc_id"])))
    assert plan["status"] == "SUSPENDED"


# =============================================================================
# transitive_cascade — depth-3 from prior-auth deny (queue A)
# =============================================================================

def _plan_with_submitted_order_then_pending_auth(api, mrn):
    """DRAFT plan; one SUBMITTED supply order (153c); one SUBMITTED auth pending.
    Returns (base, order_id, auth_id)."""
    base = fixtures.setup_draft_plan(budget_cents=100000, mrn=mrn, accept_into_care=False)
    order = fixtures.submit_supply_order(base["plan_id"], base["wc_id"],
                                         line_items=factories.THREE_LINES_153)
    auth = validate_success(api.create_prior_authorization(
        factories.create_prior_authorization_payload(
            base["plan_id"], requested_hbo_sessions=2), fixtures.PAYER), 201)
    return base, order["id"], auth["id"]


def test_prior_auth_deny_cascades_coverage_and_supply_rejection(api):
    """PRD §3.5: "Denying moves the authorization to DENIED and cascades: the
    plan's coverage_status flips to NOT_COVERED; every one of the plan's supply
    orders still in SUBMITTED status is rejected, transitioning each to REJECTED;
    each such rejection credits its covered_cents back out of the plan's
    provisional_covered_cents".
    Deny drives auth=DENIED -> coverage=NOT_COVERED -> order=REJECTED ->
    provisional_covered_cents credited back to 0.

    Design: Difficulty/transitive_cascade/prior_auth_deny_depth3_cascade_to_supply
    """
    base, order_id, auth_id = _plan_with_submitted_order_then_pending_auth(api, "M8")
    denied = validate_success(api.deny_prior_authorization(auth_id, fixtures.PAYER))
    assert denied["status"] == "DENIED"
    wc_headers = make_wound_clinician_headers(base["wc_id"])
    plan = validate_success(api.get_treatment_plan(base["plan_id"], wc_headers))
    assert plan["coverage_status"] == "NOT_COVERED"
    order = validate_success(api.get_supply_order(order_id, wc_headers))
    assert order["status"] == "REJECTED"
    assert plan["provisional_covered_cents"] == 0, \
        f"expected 0 after credit-back, got {plan['provisional_covered_cents']}"


def test_prior_auth_deny_sets_coverage_not_covered(api):
    """PRD §3.5: "Denying moves the authorization to DENIED and cascades: the
    plan's coverage_status flips to NOT_COVERED".
    Isolates the first cascade hop: coverage flips to NOT_COVERED on deny.

    Design: Difficulty/transitive_cascade/prior_auth_deny_depth3_cascade_to_supply
    """
    base, order_id, auth_id = _plan_with_submitted_order_then_pending_auth(api, "M8b")
    validate_success(api.deny_prior_authorization(auth_id, fixtures.PAYER))
    plan = validate_success(api.get_treatment_plan(
        base["plan_id"], make_wound_clinician_headers(base["wc_id"])))
    assert plan["coverage_status"] == "NOT_COVERED"


# =============================================================================
# compensating_invariant — conserved quantities (queue A)
# =============================================================================

def test_chamber_slot_conserved_schedule_then_cancel(api):
    """PRD §3.8: "On a successful schedule, the chamber's occupied_slot_count is
    incremented by one". PRD §3.8: "cancellation releases the chamber slot by
    decrementing occupied_slot_count by one".
    Scheduling then cancelling one session returns occupied_slot_count to 0 with
    no drift.

    Design: Difficulty/compensating_invariant/chamber_slot_conserved_on_schedule_then_cancel
    """
    base = fixtures.setup_active_covered_plan_with_chamber(mrn="M17")
    ht_id = base["ht_id"]
    sess = fixtures.schedule_hbo_session(base["plan_id"], base["chamber_id"], ht_id)
    chamber = validate_success(api.get_chamber(base["chamber_id"], fixtures.INTAKE))
    assert chamber["occupied_slot_count"] == 1
    cancelled = validate_success(api.cancel_hbo_session(
        sess["id"], make_hyperbaric_tech_headers(ht_id)))
    assert cancelled["status"] == "CANCELLED"
    chamber = validate_success(api.get_chamber(base["chamber_id"], fixtures.INTAKE))
    assert chamber["occupied_slot_count"] == 0


def test_supply_budget_conserved_submit_then_reject(api):
    """PRD §3.6: "The plan's provisional_covered_cents therefore always equals
    the sum of covered_cents across that plan's supply orders whose status is
    SUBMITTED or APPROVED." PRD §3.6: "A PayerLiaison may reject a SUBMITTED
    order, moving it to REJECTED and crediting its covered_cents back out of the
    plan's provisional_covered_cents".
    Submitting (+153) then rejecting (-153) a supply order returns
    provisional_covered_cents to 0 with no drift.

    Design: Difficulty/compensating_invariant/supply_budget_conserved_on_submit_then_reject
    """
    base = fixtures.setup_draft_plan(budget_cents=100000, mrn="M18", accept_into_care=False)
    order = fixtures.submit_supply_order(base["plan_id"], base["wc_id"],
                                         line_items=factories.THREE_LINES_153,
                                         supply_kind="SKIN_GRAFT")
    wc_headers = make_wound_clinician_headers(base["wc_id"])
    plan = validate_success(api.get_treatment_plan(base["plan_id"], wc_headers))
    assert plan["provisional_covered_cents"] == 153
    rejected = validate_success(api.reject_supply_order(order["id"], fixtures.PAYER))
    assert rejected["status"] == "REJECTED"
    plan = validate_success(api.get_treatment_plan(base["plan_id"], wc_headers))
    assert plan["provisional_covered_cents"] == 0, \
        f"expected 0 after credit-back, got {plan['provisional_covered_cents']}"


def test_chamber_slot_conserved_schedule_then_complete_then_cancel_second(api):
    """PRD §3.8: "On a successful schedule, the chamber's occupied_slot_count is
    incremented by one". PRD §3.8: "Completion persists the supplied
    dive_log_entries, moves the session to COMPLETED, decrements the chamber's
    occupied_slot_count by one". PRD §3.8: "cancellation releases the chamber
    slot by decrementing occupied_slot_count by one".
    Two sessions push the count to 2; completing one and cancelling the other
    both release their slots, returning occupied_slot_count to 0 with no drift.

    Design: Difficulty/compensating_invariant/chamber_slot_conserved_on_schedule_then_cancel
    """
    base = fixtures.setup_active_covered_plan_with_chamber(mrn="M17b")
    ht_id = base["ht_id"]
    s1 = fixtures.schedule_hbo_session(base["plan_id"], base["chamber_id"], ht_id,
                                       window_start="2026-05-02T09:00:00Z",
                                       window_end="2026-05-02T10:00:00Z")
    s2 = fixtures.schedule_hbo_session(base["plan_id"], base["chamber_id"], ht_id,
                                       window_start="2026-05-02T11:00:00Z",
                                       window_end="2026-05-02T12:00:00Z")
    chamber = validate_success(api.get_chamber(base["chamber_id"], fixtures.INTAKE))
    assert chamber["occupied_slot_count"] == 2
    fixtures.complete_hbo_session(s1["id"], ht_id)
    validate_success(api.cancel_hbo_session(s2["id"], make_hyperbaric_tech_headers(ht_id)))
    chamber = validate_success(api.get_chamber(base["chamber_id"], fixtures.INTAKE))
    assert chamber["occupied_slot_count"] == 0


def test_supply_budget_conserved_submit_then_cancel(api):
    """PRD §3.6: "a WoundClinician may cancel a SUBMITTED order, moving it to
    CANCELLED and likewise crediting its covered_cents back out of
    provisional_covered_cents." PRD §3.6: "The plan's provisional_covered_cents
    therefore always equals the sum of covered_cents across that plan's supply
    orders whose status is SUBMITTED or APPROVED."
    Submitting (+153) then cancelling (-153) returns provisional_covered_cents to
    0 with no drift.

    Design: Difficulty/compensating_invariant/supply_budget_conserved_on_submit_then_reject
    """
    base = fixtures.setup_draft_plan(budget_cents=100000, mrn="M18b", accept_into_care=False)
    order = fixtures.submit_supply_order(base["plan_id"], base["wc_id"],
                                         line_items=factories.THREE_LINES_153)
    wc_headers = make_wound_clinician_headers(base["wc_id"])
    plan = validate_success(api.get_treatment_plan(base["plan_id"], wc_headers))
    assert plan["provisional_covered_cents"] == 153
    cancelled = validate_success(api.cancel_supply_order(order["id"], wc_headers))
    assert cancelled["status"] == "CANCELLED"
    plan = validate_success(api.get_treatment_plan(base["plan_id"], wc_headers))
    assert plan["provisional_covered_cents"] == 0, \
        f"expected 0 after credit-back, got {plan['provisional_covered_cents']}"
