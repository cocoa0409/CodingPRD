"""Incidents: assessment math, dispute loop, settlement cascades, SoD."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    register_carrier,
    register_escort,
    read_escort,
    set_clock,
    get_job,
    get_assignment,
    get_incident,
    setup_booked_job,
    setup_delivered_rear_job,
    advance_to_cleared,
    advance_to_scheduled,
    advance_to_en_route,
    advance_to_delivered,
    offer_and_accept,
    add_permit,
    issue_permit,
    offer_assignment,
    accept_assignment,
    report_incident,
    assess_incident,
    settle_incident,
    dispute_incident,
    make_carrier_rep_headers,
    make_escort_operator_headers,
    api_client,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
SAFETY = TEST_USERS["safety_manager_headers"]
FINANCE = TEST_USERS["finance_manager_headers"]


def test_first_assessment_zero_share_after_deductible(api):
    """PRD §3.7: "`assessed_amount_cents` is the lesser of the claimed amount
    and a liability cap of 25,000,000 cents; and `escort_share_cents` is the
    assessed amount multiplied by the fault-share percentage and divided by
    100, rounded half up to a whole cent, then reduced by the 50,000-cent
    escort deductible, with the result floored at zero."
    PRD §3.7: "The owning `CarrierRep` disputes an `ASSESSED` incident,
    optionally with a `reason`, moving it to `DISPUTED`"

    Design: Difficulty/non_linear_state_machine/incident_dispute_reassessment_cycle
    """
    bundle = setup_delivered_rear_job(deliver_at="2026-08-10T10:00:00Z", escort_name="Lone Star Escort")
    asg = bundle["assignments"][0]
    inc = report_incident(
        bundle["job"]["id"],
        incident_type="CARGO_DAMAGE",
        description="Load shifted on bridge strike avoidance maneuver",
        claimed_amount_cents=200000,
        assignment_id=asg["id"],
    )

    assessed = assess_incident(inc["id"], 25)
    assert assessed["incident_status"] == "ASSESSED"
    assert assessed["assessed_amount_cents"] == 200000
    assert assessed["escort_share_cents"] == 0, "max(0, round(200000 x 0.25) - 50000)"

    disputed = dispute_incident(inc["id"], bundle["carrier"])
    assert disputed["incident_status"] == "DISPUTED"


def test_reassessment_replaces_amounts_and_settle_applies_latest(api):
    """PRD §3.7: "Re-assessment after a dispute recomputes both amounts from
    the newly supplied fault share and replaces the prior figures entirely —
    the latest assessment wins."
    PRD §3.7: "a fault share of at least 50 percent subtracts 35 points from
    the escort's `reliability_score`"

    Design: Difficulty/non_linear_state_machine/incident_dispute_reassessment_cycle
    """
    bundle = setup_delivered_rear_job(deliver_at="2026-08-10T10:00:00Z", escort_name="Lone Star Escort")
    asg = bundle["assignments"][0]
    inc = report_incident(
        bundle["job"]["id"],
        incident_type="CARGO_DAMAGE",
        description="Load shifted",
        claimed_amount_cents=200000,
        assignment_id=asg["id"],
    )
    assess_incident(inc["id"], 25)
    dispute_incident(inc["id"], bundle["carrier"])

    reassessed = assess_incident(inc["id"], 60)
    assert reassessed["incident_status"] == "ASSESSED", "the loop returns to ASSESSED"
    assert reassessed["escort_share_cents"] == 70000, (
        "max(0, 120000 - 50000): replaced, not added to the disputed 0"
    )

    settled = settle_incident(inc["id"])
    assert settled["incident_status"] == "SETTLED"
    esc = read_escort(bundle["escort"]["id"])
    assert esc["reliability_score"] == 65, "latest pct 60 >= 50 -> -35; the disputed 25% never applied"
    assert esc["escort_status"] == "ACTIVE"


def _setup_suspension_cascade():
    """Escort E COMPLETED on delivered job A and ACCEPTED (REAR) on SCHEDULED
    job B; two REPORTED incidents on A tied to A's assignment."""
    carrier = register_carrier(10_000_000, "Red River Transport")
    esc = register_escort(("TX",), "Risky Rider")

    bundle_a = setup_booked_job(carrier, load_description="Job A vessel")
    bundle_a["escort"] = esc
    advance_to_cleared(bundle_a, permit_kwargs={"permit_number": "TX-P-6"})
    asg_a = offer_and_accept(bundle_a, esc, "REAR")
    advance_to_scheduled(bundle_a)
    advance_to_en_route(bundle_a, "2026-08-10T09:00:00Z")
    advance_to_delivered(bundle_a, "2026-08-10T13:00:00Z", checkin_at="2026-08-10T12:00:00Z")

    bundle_b = setup_booked_job(
        carrier,
        load_description="Job B silo",
        distance_miles=60,
        window_start_at="2026-08-12T09:00:00Z",
        window_end_at="2026-08-12T12:00:00Z",
        planned_entry_at="2026-08-12T09:00:00Z",
        planned_exit_at="2026-08-12T12:00:00Z",
        clock_base="2026-08-10T13:00:00Z",
    )
    bundle_b["escort"] = esc
    advance_to_cleared(
        bundle_b,
        permit_kwargs={
            "permit_number": "TX-P-7",
            "valid_from": "2026-08-11T00:00:00Z",
            "valid_until": "2026-08-14T00:00:00Z",
        },
    )
    asg_b = offer_and_accept(bundle_b, esc, "REAR")
    advance_to_scheduled(bundle_b)

    inc1 = report_incident(
        bundle_a["job"]["id"], description="Mailbox clipped",
        claimed_amount_cents=100000, assignment_id=asg_a["id"],
    )
    inc2 = report_incident(
        bundle_a["job"]["id"], description="Fence post damaged",
        claimed_amount_cents=100000, assignment_id=asg_a["id"],
    )
    return {"carrier": carrier, "esc": esc, "a": bundle_a, "b": bundle_b,
            "asg_a": asg_a, "asg_b": asg_b, "inc1": inc1, "inc2": inc2}


def test_settle_penalties_can_auto_suspend_escort(api):
    """PRD §3.7: "a fault share of at least 50 percent subtracts 35 points from
    the escort's `reliability_score`; a fault share between 1 and 49 percent
    inclusive subtracts 10 points; a fault share of 0 subtracts nothing. The
    score is clamped between 0 and 100. If the penalized score falls below 40,
    the escort is automatically moved to `SUSPENDED`"

    Design: Difficulty/transitive_cascade/incident_settle_suspension_release_demote
    """
    ctx = _setup_suspension_cascade()
    esc_id = ctx["esc"]["id"]

    assess_incident(ctx["inc1"]["id"], 60)
    settle_incident(ctx["inc1"]["id"])
    esc = read_escort(esc_id)
    assert esc["reliability_score"] == 65, "100 - 35"
    assert esc["escort_status"] == "ACTIVE", "65 >= 40 floor"

    assess_incident(ctx["inc2"]["id"], 60)
    settle_incident(ctx["inc2"]["id"])
    esc = read_escort(esc_id)
    assert esc["reliability_score"] == 30, "65 - 35"
    assert esc["escort_status"] == "SUSPENDED", "30 < 40: the settle auto-suspends the escort"


def test_suspension_releases_assignment_and_demotes_scheduled_job(api):
    """PRD §3.7: "If the penalized score falls below 40, the escort is
    automatically moved to `SUSPENDED`, and the full suspension cascade of §3.1
    follows in the same operation: the escort's `ACCEPTED` assignments are
    released with `release_cause` `ESCORT_SUSPENDED` and the count decremented
    per release, and any `SCHEDULED` job losing a required position is demoted
    to `CLEARED`."

    Design: Difficulty/transitive_cascade/incident_settle_suspension_release_demote
    """
    ctx = _setup_suspension_cascade()
    for inc in (ctx["inc1"], ctx["inc2"]):
        assess_incident(inc["id"], 60)
        settle_incident(inc["id"])

    asg_b = get_assignment(ctx["asg_b"]["id"])
    assert asg_b["assignment_status"] == "RELEASED"
    assert asg_b["release_cause"] == "ESCORT_SUSPENDED", (
        "the suspension — not the settle — released the other job's assignment"
    )
    job_b = get_job(ctx["b"]["job"]["id"])
    assert job_b["job_status"] == "CLEARED", (
        "the release demoted the SCHEDULED job whose REAR position became uncovered"
    )
    assert get_incident(ctx["inc1"]["id"])["escort_share_cents"] == 10000
    assert get_incident(ctx["inc2"]["id"])["escort_share_cents"] == 10000


def test_liability_cap_and_deductible(api):
    """PRD §3.7: "`assessed_amount_cents` is the lesser of the claimed amount
    and a liability cap of 25,000,000 cents; and `escort_share_cents` is the
    assessed amount multiplied by the fault-share percentage and divided by
    100, rounded half up to a whole cent, then reduced by the 50,000-cent
    escort deductible, with the result floored at zero."

    Design: Corner/calculations/liability_cap_and_deductible
    """
    bundle = setup_delivered_rear_job(deliver_at="2026-08-10T10:00:00Z", escort_name="Rider Cap")
    asg = bundle["assignments"][0]
    carrier = bundle["carrier"]
    inc = report_incident(
        bundle["job"]["id"],
        incident_type="PROPERTY_DAMAGE",
        description="Overpass strike",
        claimed_amount_cents=30000000,
        assignment_id=asg["id"],
        reporter_user_id=carrier["id"],
        reporter_role="CarrierRep",
    )
    assessed = assess_incident(inc["id"], 100)
    assert assessed["assessed_amount_cents"] == 25000000, "cap applied, not the claimed 30000000"
    assert assessed["escort_share_cents"] == 24950000, "max(0, 25000000 - 50000)"

    settle_incident(inc["id"])
    esc = read_escort(bundle["escort"]["id"])
    assert esc["reliability_score"] == 65, "pct 100 >= 50 -> -35"
    assert esc["escort_status"] == "ACTIVE"


def test_partial_fault_penalty_and_zero_share(api):
    """PRD §3.7: "a fault share between 1 and 49 percent inclusive subtracts 10
    points; a fault share of 0 subtracts nothing."
    PRD §3.7: "then reduced by the 50,000-cent escort deductible, with the
    result floored at zero."

    Design: Corner/calculations/partial_fault_penalty_and_zero_share
    """
    bundle = setup_delivered_rear_job(deliver_at="2026-08-10T10:00:00Z", escort_name="Rider P")
    asg = bundle["assignments"][0]
    esc_id = bundle["escort"]["id"]
    inc = report_incident(
        bundle["job"]["id"],
        incident_type="TRAFFIC_VIOLATION",
        description="Speeding",
        claimed_amount_cents=100000,
        assignment_id=asg["id"],
        reporter_user_id=esc_id,
        reporter_role="EscortOperator",
    )
    assessed = assess_incident(inc["id"], 30)
    assert assessed["assessed_amount_cents"] == 100000
    assert assessed["escort_share_cents"] == 0, "max(0, 30000 - 50000)"

    settle_incident(inc["id"])
    esc = read_escort(esc_id)
    assert esc["reliability_score"] == 90, "partial band 1..49 -> -10"
    assert esc["escort_status"] == "ACTIVE"
    assert esc["active_assignment_count"] == 0, "no assignments released by a non-suspending settle"


def test_incident_state_gates_rejected(api):
    """PRD §3.7: "The owning `CarrierRep` disputes an `ASSESSED` incident,
    optionally with a `reason`, moving it to `DISPUTED`; any other status is
    rejected with `ERR_INCIDENT_INVALID_STATE`. A `DISPUTED` incident cannot be
    settled directly — settlement is permitted only from `ASSESSED`, and the
    attempt is rejected with `ERR_INCIDENT_INVALID_STATE` — so a disputed
    incident must first be re-assessed, looping back through `ASSESSED` before
    it can close."

    Design: Corner/state_machines/incident_state_gates_rejected
    """
    bundle = setup_delivered_rear_job(deliver_at="2026-08-10T10:00:00Z", escort_name="Rider I")
    asg = bundle["assignments"][0]
    inc = report_incident(
        bundle["job"]["id"],
        incident_type="TRAFFIC_VIOLATION",
        description="Rolling stop",
        claimed_amount_cents=5000,
        assignment_id=asg["id"],
    )

    resp = api.dispute_incident(inc["id"], make_carrier_rep_headers(bundle["carrier"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INCIDENT_INVALID_STATE)

    assessed = assess_incident(inc["id"], 10)
    assert assessed["incident_status"] == "ASSESSED"
    disputed = dispute_incident(inc["id"], bundle["carrier"])
    assert disputed["incident_status"] == "DISPUTED"

    resp2 = api.settle_incident(inc["id"], FINANCE)
    validate_error(resp2, ApiErrorId.ERR_INCIDENT_INVALID_STATE)
    assert get_incident(inc["id"])["incident_status"] == "DISPUTED"


def test_sod_incident_assess_by_reporter_forbidden(api):
    """PRD §3.7: "Assessment belongs to a `SafetyManager` or a `Dispatcher`,
    but never to the reporter: segregation of duties requires the assessor's
    `X-User-ID` to differ from the incident's `reporter_user_id`, and a
    violation is rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/sod_incident_assess_by_reporter_forbidden
    """
    bundle = setup_delivered_rear_job(deliver_at="2026-08-10T10:00:00Z", escort_name="Rider S")
    inc = report_incident(
        bundle["job"]["id"],
        incident_type="PROPERTY_DAMAGE",
        description="Curb strike",
        claimed_amount_cents=8000,
        reporter_user_id="disp-1",
        reporter_role="Dispatcher",
    )

    # Same person, even though Dispatcher is an allowed assess role.
    resp = api.assess_incident(
        inc["id"],
        {"escort_fault_share_pct": 10},
        {"X-User-ID": "disp-1", "X-User-Role": "Dispatcher", "Content-Type": "application/json"},
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    assessed = assess_incident(inc["id"], 10, assessor_user_id="sm-1")
    assert assessed["incident_status"] == "ASSESSED"
    assert assessed["assessed_amount_cents"] == 8000


def test_incident_assignment_foreign_job_rejected(api):
    """PRD §2.8: "An `assignment_id` that exists but belongs to a leg of a
    different job is not a not-found case; it is rejected with
    `ERR_INVALID_REQUEST`."

    Design: Corner/validations/incident_assignment_foreign_job_rejected
    """
    carrier = register_carrier(10_000_000, "Foreign Ref Co")
    esc_a = register_escort(("TX",), "Rider FA")
    bundle_a = setup_booked_job(carrier, load_description="A")
    asg_a = offer_assignment(bundle_a["leg"]["id"], "REAR", esc_a["id"])

    bundle_b = setup_delivered_rear_job(
        escort_name="Rider FB",
        depart_at="2026-08-11T09:00:00Z",
        deliver_at="2026-08-11T10:00:00Z",
    )

    resp = api.create_incident(
        bundle_b["job"]["id"],
        {
            "incident_type": "PROPERTY_DAMAGE",
            "description": "wrong link",
            "claimed_amount_cents": 1000,
            "assignment_id": asg_a["id"],
        },
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    rows, meta = validate_paginated(api.list_job_incidents(bundle_b["job"]["id"], DISPATCHER))
    assert rows == [] and meta["total_count"] == 0


def test_escort_reinstate_active_rejected(api):
    """PRD §3.1: "Reinstatement by a `SafetyManager` is permitted only while
    the escort is `SUSPENDED` (again `ERR_ESCORT_INVALID_STATE` otherwise) and
    returns the escort to `ACTIVE`"

    Design: Corner/state_machines/escort_reinstate_active_rejected
    """
    esc = register_escort(("TX",), "Already Active")
    resp = api.reinstate_escort(esc["id"], SAFETY)
    validate_error(resp, ApiErrorId.ERR_ESCORT_INVALID_STATE)
    row = read_escort(esc["id"])
    assert row["escort_status"] == "ACTIVE"
    assert row["reliability_score"] == 100
