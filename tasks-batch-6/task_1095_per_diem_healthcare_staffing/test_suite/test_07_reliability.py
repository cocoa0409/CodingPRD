"""Reliability scoring: the provisional-vs-adjudicated divergence, cancellation
tiers, age decay, and the overturn that reinstates a suspended clinician.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    make_scheduler_headers,
    make_clinician_headers,
    fixtures as fx,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


def _setup_confirmed_then_advance(shift_start, shift_end, cancel_clock, **kwargs):
    """Confirmed assignment, then advance the clock to `cancel_clock`. Returns
    (fac_id, cl_id, assignment)."""
    bundle = fx.setup_confirmed_assignment(
        shift_overrides={"scheduled_start": shift_start, "scheduled_end": shift_end}, **kwargs
    )
    fx.set_clock(cancel_clock)
    return bundle["facility"]["id"], bundle["clinician"]["id"], bundle["assignment"]


def _setup_suspended_two_noshows():
    fx.set_clock("2026-06-01T00:00:00Z")
    fac = fx.new_facility(name="Dunmore", unit_capacity=2)
    fx.add_rate_card(fac["id"])
    cl = fx.new_clinician(full_name="Eve Nakamura", email="eve.nakamura@example.com")
    fx.add_verified_credential(cl["id"])
    fac_id, cl_id = fac["id"], cl["id"]
    order = fx.new_order(fac_id, headcount=2)
    s1 = fx.add_shift(order["id"], fac_id, scheduled_start="2026-06-08T07:00:00Z", scheduled_end="2026-06-08T19:00:00Z")
    s2 = fx.add_shift(order["id"], fac_id, scheduled_start="2026-06-09T07:00:00Z", scheduled_end="2026-06-09T15:00:00Z")
    c1 = fx.place_claim(s1["id"], cl_id)
    a1 = fx.award(s1["id"], fac_id, claim_id=c1["id"])
    fx.confirm(a1["id"], cl_id)
    c2 = fx.place_claim(s2["id"], cl_id)
    a2 = fx.award(s2["id"], fac_id, claim_id=c2["id"])
    fx.confirm(a2["id"], cl_id)
    fx.set_clock("2026-06-09T15:30:00Z")
    fx.no_show(a1["id"], fac_id, note="absent")
    fx.no_show(a2["id"], fac_id, note="absent again")
    return fac_id, cl_id, a1["id"], a2["id"]


# --------------------------------------------------------------------------- #
# Corner
# --------------------------------------------------------------------------- #
def test_overturned_no_show_reinstates_suspended_clinician(api):
    """PRD 3.7: "A decision of `OVERTURNED` moves the event `PENDING → OVERTURNED`,
    records `adjudicated_at`, and recomputes reliability with that event now excluded
    from both variants, so the provisional score returns exactly to its pre-event value
    and any suspension the event caused is reversed."

    Design: Corner/state_machines/overturned_no_show_reinstates_suspended_clinician
    """
    fac_id, cl_id, a1_id, a2_id = _setup_suspended_two_noshows()
    before = validate_success(api.get_clinician(cl_id, OFFICER), 200)
    assert before["provisional_reliability_score"] == 40 and before["status"] == "SUSPENDED"
    events = validate_success(api.list_assignment_reliability_events(a2_id, OFFICER), 200)
    adj = validate_success(api.adjudicate_event(events[0]["id"], {"decision": "OVERTURNED"}, OFFICER), 200)
    assert adj["adjudication_status"] == "OVERTURNED"
    after = validate_success(api.get_clinician(cl_id, OFFICER), 200)
    assert after["provisional_reliability_score"] == 70
    assert after["reliability_score"] == 100
    assert after["status"] == "ACTIVE"
    assert after["no_show_count"] == 0


def test_cancellation_at_exactly_seventy_two_hours_is_free(api):
    """PRD 3.5: "if the lead is at least 72 hours, no reliability event is recorded at
    all".
    PRD 3.5: "These boundaries fall on the cheaper side: a lead of exactly 72.00 hours
    is free, exactly 24.00 hours is the 5-point tier, and 23.99 hours is the 15-point
    tier."

    Design: Corner/calculations/cancellation_at_exactly_seventy_two_hours_is_free
    """
    fac_id, cl_id, asg = _setup_confirmed_then_advance(
        "2026-06-11T06:30:00Z", "2026-06-11T18:30:00Z", "2026-06-08T06:30:00Z",
        facility_overrides={"name": "Mistral"},
    )
    cancelled = validate_success(
        api.cancel_assignment(asg["id"], {"reason": "cancelled exactly three days out"},
                              make_clinician_headers(cl_id)), 200)
    assert cancelled["cancellation_lead_hours"] == 72.00
    assert cancelled["work_status"] == "CANCELLED_BY_CLINICIAN"
    events, meta = validate_paginated(api.list_clinician_reliability_events(cl_id, OFFICER))
    assert meta["total_count"] == 0
    clinician = validate_success(api.get_clinician(cl_id, ADMIN), 200)
    assert clinician["provisional_reliability_score"] == 100 and clinician["reliability_score"] == 100


def test_cancellation_at_exactly_twenty_four_hours_is_late_five_points(api):
    """PRD 3.5: "if the lead is at least 24 hours but under 72, a `LATE_CANCELLATION`
    penalty event worth 5 points is appended in `PENDING`".

    Design: Corner/calculations/cancellation_at_exactly_twenty_four_hours_is_late_five_points
    """
    fac_id, cl_id, asg = _setup_confirmed_then_advance(
        "2026-06-11T06:30:00Z", "2026-06-11T18:30:00Z", "2026-06-10T06:30:00Z",
        facility_overrides={"name": "Nightjar"},
    )
    cancelled = validate_success(
        api.cancel_assignment(asg["id"], {"reason": "sick, one day out"}, make_clinician_headers(cl_id)), 200)
    assert cancelled["cancellation_lead_hours"] == 24.00
    assert cancelled["pay_status"] == "WAIVED"
    events = validate_success(api.list_assignment_reliability_events(asg["id"], OFFICER), 200)
    assert len(events) == 1
    ev = events[0]
    assert ev["event_type"] == "LATE_CANCELLATION"
    assert ev["penalty_points"] == 5 and ev["credit_points"] == 0
    assert ev["adjudication_status"] == "PENDING"
    clinician = validate_success(api.get_clinician(cl_id, ADMIN), 200)
    assert clinician["provisional_reliability_score"] == 95
    assert clinician["reliability_score"] == 100
    assert clinician["status"] == "ACTIVE"


def test_reliability_decay_tier_two_weight_after_forty_days(api):
    """PRD 3.7: "An event aged 30 days or fewer carries full weight 1.0; aged 60 days
    or fewer, weight 0.6; aged 90 days or fewer, weight 0.3; older than 90 days, it is
    excluded entirely."

    Design: Corner/calculations/reliability_decay_tier_two_weight_after_forty_days
    """
    bundle = fx.setup_confirmed_assignment(
        facility_overrides={"name": "Oriole"},
        clinician_overrides={"full_name": "Nor Halvorsen", "email": "nor.halvorsen@example.com"},
        cred_overrides={"expires_on": "2028-01-01T00:00:00Z"},
    )
    fac_id, cl_id, asg = bundle["facility"]["id"], bundle["clinician"]["id"], bundle["assignment"]
    fx.set_clock("2026-06-08T08:00:00Z")
    fx.no_show(asg["id"], fac_id, note="absent")
    events = validate_success(api.list_assignment_reliability_events(asg["id"], OFFICER), 200)
    fx.set_clock("2026-07-18T08:00:00Z")  # exactly 40 days after the event
    adj = validate_success(api.adjudicate_event(events[0]["id"], {"decision": "CONFIRMED"}, OFFICER), 200)
    assert adj["adjudication_status"] == "CONFIRMED"
    clinician = validate_success(api.get_clinician(cl_id, OFFICER), 200)
    assert clinician["reliability_score"] == 82
    assert clinician["provisional_reliability_score"] == 82
    assert clinician["no_show_count"] == 1
    assert clinician["status"] == "ACTIVE"


# --------------------------------------------------------------------------- #
# Difficulty: provisional vs adjudicated reliability diverges on a pending no-show
# --------------------------------------------------------------------------- #
def _setup_single_no_show():
    bundle = fx.setup_confirmed_assignment(
        facility_overrides={"name": "Saint Ives", "unit_name": "MedSurg"},
        clinician_overrides={"full_name": "Ben Ortiz", "email": "ben.ortiz@example.com"},
    )
    fac_id, cl_id, asg = bundle["facility"]["id"], bundle["clinician"]["id"], bundle["assignment"]
    fx.set_clock("2026-06-08T08:00:00Z")
    result = validate_success(
        fx.api_client.no_show_assignment(asg["id"], {"note": "did not arrive on unit"}, fx.make_verifier_headers(fac_id)), 200)
    return fac_id, cl_id, asg["id"], bundle["shift"]["id"], result


def test_pending_no_show_diverges_provisional_from_adjudicated(api):
    """PRD 3.7: "The provisional variant, written to `provisional_reliability_score`,
    counts both `PENDING` and `CONFIRMED` events, so a freshly recorded, still-pending
    no-show immediately depresses it. Immediately after a first no-show on an otherwise
    clean clinician, the adjudicated score reads 100 and the provisional score reads
    70."

    Design: Difficulty/dual_variant_calc/provisional_vs_adjudicated_reliability_diverges_on_pending_no_show
    """
    fac_id, cl_id, asg_id, shift_id, result = _setup_single_no_show()
    clinician = validate_success(api.get_clinician(cl_id, OFFICER), 200)
    assert clinician["reliability_score"] == 100
    assert clinician["provisional_reliability_score"] == 70
    assert clinician["status"] == "ACTIVE"
    assert clinician["no_show_count"] == 0


def test_pending_no_show_cascade_side_effects(api):
    """PRD 3.5: "The no-show cascade sets `work_status` to `NO_SHOW` and `pay_status`
    to `WAIVED`; appends a `NO_SHOW` penalty event worth 30 points in `PENDING`".
    PRD 3.7: "Penalty events (`LATE_CANCELLATION`, `VERY_LATE_CANCELLATION`, `NO_SHOW`)
    are appended in `PENDING`".

    Design: Difficulty/dual_variant_calc/provisional_vs_adjudicated_reliability_diverges_on_pending_no_show
    """
    fac_id, cl_id, asg_id, shift_id, result = _setup_single_no_show()
    assert result["work_status"] == "NO_SHOW"
    assert result["pay_status"] == "WAIVED"
    shift = validate_success(api.get_shift(shift_id, make_scheduler_headers(fac_id)), 200)
    assert shift["status"] == "OPEN"
    events = validate_success(api.list_clinician_reliability_events(cl_id, OFFICER), 200)
    assert len(events) == 1
    ev = events[0]
    assert ev["event_type"] == "NO_SHOW"
    assert ev["penalty_points"] == 30 and ev["credit_points"] == 0
    assert ev["adjudication_status"] == "PENDING"
