"""Adherence PDC (realized vs projected, band boundary) and subscription
membership (supersede, stale-version OCC, cancel cascade).

Difficulty: adherence_realized_vs_projected_pdc_diverge, pdc_080_at_risk_boundary.
Corner: subscription_supersede_prior_marks_it_superseded,
subscription_create_stale_patient_version_returns_412,
subscription_cancel_cascade_suspends_active_prescription.
"""
from test_helpers import (
    ApiErrorId,
    validate_success, validate_error, get_success_data,
    create_subscription_payload,
    register_patient, create_subscription,
    setup_active_prescription, add_fulfilled_refill, request_refill,
    set_clock, make_patient_headers, billing_admin_headers,
)


# ---------------------------------------------------------------------------
# Adherence PDC: realized vs projected divergence (difficulty)
# ---------------------------------------------------------------------------
def _adherence_care_plan(api, *, with_pending):
    set_clock(api, "2026-06-01T00:00:00Z")
    ctx = setup_active_prescription(api, rx_overrides={
        "hrt_type": "ESTROGEN_ORAL", "days_supply_per_fill": 24,
        "total_refills_authorized": 3, "coverage_days": 90, "refill_price_cents": 18000})
    add_fulfilled_refill(api, ctx)
    if with_pending:
        request_refill(api, ctx)
    set_clock(api, "2026-07-01T00:00:00Z")
    care_plan = get_success_data(api.get_care_plan(ctx["care_plan_id"], ctx["provider_headers"]))
    return care_plan


def test_realized_pdc_counts_only_fulfilled_refills(api):
    """PRD §3.6: "The realized supply is the sum of days_supply across the
    prescription's FULFILLED refills. ... realized_pdc is the smaller of the
    realized supply and elapsed days, divided by elapsed days, rounded half up to
    4 decimals."

    Design: Difficulty/dual_variant_calc/adherence_realized_vs_projected_pdc_diverge
    """
    care_plan = _adherence_care_plan(api, with_pending=True)
    # realized supply 24, elapsed 30 -> 24/30 = 0.8
    assert round(care_plan["realized_pdc"], 4) == 0.8, \
        f"expected realized_pdc 0.8, got {care_plan['realized_pdc']}"


def test_projected_pdc_counts_pending_refills(api):
    """PRD §3.6: "the projected figure additionally counts pending refills as if
    they will each be fulfilled at the full days_supply_per_fill, and so diverges
    from realized whenever a pending refill exists."

    Design: Difficulty/dual_variant_calc/adherence_realized_vs_projected_pdc_diverge
    """
    care_plan = _adherence_care_plan(api, with_pending=True)
    # projected supply 24 + 24 = 48, capped by elapsed 30 -> 30/30 = 1.0
    assert round(care_plan["projected_pdc"], 4) == 1.0, \
        f"expected projected_pdc 1.0, got {care_plan['projected_pdc']}"
    assert round(care_plan["projected_pdc"], 4) != round(care_plan["realized_pdc"], 4), \
        "projected must diverge from realized when a pending refill exists"


# ---------------------------------------------------------------------------
# Adherence band boundary at 0.80 (difficulty)
# ---------------------------------------------------------------------------
def test_pdc_080_is_realized_value(api):
    """PRD §3.6: "realized_pdc is the smaller of the realized supply and elapsed
    days, divided by elapsed days, rounded half up to 4 decimals."

    Design: Difficulty/boundary_precision_check/pdc_080_at_risk_boundary
    """
    care_plan = _adherence_care_plan(api, with_pending=False)
    assert round(care_plan["realized_pdc"], 4) == 0.8, \
        f"expected realized_pdc 0.8, got {care_plan['realized_pdc']}"


def test_pdc_080_bands_as_at_risk(api):
    """PRD §3.6: "The adherence_status band is read off realized_pdc: below 0.80
    it is NON_ADHERENT; from 0.80 up to but not including 0.90 it is AT_RISK; at
    0.90 or above it is ADHERENT. The 0.80 floor is inclusive on the AT_RISK
    side and the 0.90 floor is inclusive on the ADHERENT side."

    Design: Difficulty/boundary_precision_check/pdc_080_at_risk_boundary
    """
    care_plan = _adherence_care_plan(api, with_pending=False)
    assert care_plan["adherence_status"] == "AT_RISK", \
        f"realized_pdc 0.80 must band as AT_RISK, got {care_plan['adherence_status']}"


# ---------------------------------------------------------------------------
# Subscription supersede (corner, optimistic concurrency)
# ---------------------------------------------------------------------------
def test_new_subscription_supersedes_prior(api):
    """PRD §3.7: "Creating a new subscription supersedes the patient's prior
    membership: any existing subscription of that patient in ACTIVE or PAST_DUE
    transitions to SUPERSEDED, and the patient's version is incremented by 1."

    Design: Corner/cross_cutting_complexity_layers/subscription_supersede_prior_marks_it_superseded
    """
    patient = register_patient(api)
    ph = make_patient_headers(patient["id"])
    sub1 = create_subscription(api, patient["id"], patient["version"], plan_tier="ESSENTIAL")
    patient_v2 = get_success_data(api.get_patient(patient["id"], ph))
    sub2 = create_subscription(api, patient["id"], patient_v2["version"], plan_tier="PLUS")
    assert sub2["status"] == "ACTIVE", f"new subscription must be ACTIVE, got {sub2['status']}"
    sub1_after = get_success_data(api.get_subscription(sub1["id"], ph))
    assert sub1_after["status"] == "SUPERSEDED", \
        f"prior subscription must be SUPERSEDED, got {sub1_after['status']}"


def test_subscription_create_with_stale_version_returns_412(api):
    """PRD §2.6: "If they do not match — because a newer subscription has already
    superseded the prior one and advanced the patient's version since the client
    last read it — the create is rejected with ERR_STALE_PATIENT_VERSION (HTTP
    412), preventing the client from acting on a stale view of the patient's
    membership."

    Design: Corner/cross_cutting_complexity_layers/subscription_create_stale_patient_version_returns_412
    """
    patient = register_patient(api)
    ph = make_patient_headers(patient["id"])
    create_subscription(api, patient["id"], patient["version"], plan_tier="ESSENTIAL")
    # Second create still carries the pre-supersede version.
    resp = api.create_subscription(
        create_subscription_payload(patient_id=patient["id"], plan_tier="PLUS",
                                    expected_patient_version=patient["version"]), ph)
    validate_error(resp, ApiErrorId.ERR_STALE_PATIENT_VERSION)


# ---------------------------------------------------------------------------
# Subscription cancel cascade suspends active prescription (corner)
# ---------------------------------------------------------------------------
def test_subscription_cancel_suspends_active_prescription(api):
    """PRD §3.7: "Cancellation cascades to therapy: every ACTIVE prescription
    belonging to that patient is suspended (ACTIVE → SUSPENDED), and each such
    suspension appends a system-authored SUSPENSION_NOTICE to that prescription's
    care plan."

    Design: Corner/state_machines/subscription_cancel_cascade_suspends_active_prescription
    """
    ctx = setup_active_prescription(api)
    ph = ctx["patient_headers"]
    patient_now = get_success_data(api.get_patient(ctx["patient"]["id"], ph))
    sub = create_subscription(api, ctx["patient"]["id"], patient_now["version"],
                              plan_tier="ESSENTIAL")
    cancelled = validate_success(api.cancel_subscription(sub["id"], ph))
    assert cancelled["status"] == "CANCELLED", f"expected CANCELLED, got {cancelled['status']}"
    rx_after = get_success_data(api.get_prescription(ctx["prescription"]["id"],
                                                     ctx["provider_headers"]))
    assert rx_after["status"] == "SUSPENDED", \
        f"active prescription must be SUSPENDED, got {rx_after['status']}"
    data, _ = _paginate(api.list_care_plan_messages(ctx["care_plan_id"], ctx["provider_headers"]))
    assert any(m["message_type"] == "SUSPENSION_NOTICE" for m in data), \
        "a SUSPENSION_NOTICE care-plan message must be appended"


def _paginate(resp):
    from test_helpers import validate_paginated
    return validate_paginated(resp)
