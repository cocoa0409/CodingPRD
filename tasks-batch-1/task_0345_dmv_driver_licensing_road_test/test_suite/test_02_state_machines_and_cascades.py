"""Non-linear state machines and transitive cascades.

Queue A (Difficulty): non_linear_state_machine, transitive_cascade.
"""
from test_helpers import (
    validate_success,
    get_success_data,
    make_clerk_headers,
    make_officer_headers,
    create_cdl_endorsement_payload,
    pass_knowledge_test,
    create_driver_record,
    setup_served_suspension,
    active_record_with_medical_card,
    suspend_active_record,
    get_first_suspension,
    capture_fee,
    get_record_version,
)

CLERK = make_clerk_headers("clerk-1")
OFFICER = make_officer_headers("officer-1")


# ===========================================================================
# non_linear_state_machine / driver_record_suspension_reinstatement_cycle
# ===========================================================================
def test_suspension_reinstatement_cycle_returns_record_to_active(api):
    """PRD §3.7: "On success the suspension moves SERVED → LIFTED_BY_REINSTATEMENT,
    the record's licensing_status returns from SUSPENDED to ACTIVE closing the
    cycle, `prior_suspension_count` is recomputed (and now includes this
    suspension), and the record's version increments by one."

    Design: Difficulty/non_linear_state_machine/driver_record_suspension_reinstatement_cycle
    """
    ctx = setup_served_suspension(full_name="Eve Cycle", opaque_user_id="exu-5")
    record, suspension = ctx["record"], ctx["suspension"]
    capture_fee(record["id"], "REINSTATEMENT", 18813)
    version = get_record_version(record["id"])
    validate_success(
        api.reinstate_suspension(
            suspension["id"], {"expected_driver_record_version": version}, CLERK,
        ),
        200,
    )
    rec = validate_success(api.get_driver_record(record["id"], CLERK), 200)
    assert rec["licensing_status"] == "ACTIVE"
    assert rec["prior_suspension_count"] == 1, f"got {rec['prior_suspension_count']}"
    susp = validate_success(api.get_suspension(suspension["id"], CLERK), 200)
    assert susp["status"] == "LIFTED_BY_REINSTATEMENT"


def test_reinstatement_increments_prior_suspension_count(api):
    """PRD §3.7: "The prior_suspension_count is the count of this record's
    suspensions in either SERVED or LIFTED_BY_REINSTATEMENT status; it feeds both
    the suspension-duration multiplier and the revocation threshold."
    PRD §3.7: "`prior_suspension_count` is recomputed (and now includes this
    suspension)."

    The setup advances the clock so the suspension is SERVED before reinstatement;
    per PRD §3.7 a SERVED suspension already counts, so prior_suspension_count == 1
    both before reinstatement (SERVED) and after (LIFTED_BY_REINSTATEMENT) — the
    reinstatement keeps the suspension in a counted status across the transition.

    Design: Difficulty/non_linear_state_machine/driver_record_suspension_reinstatement_cycle
    """
    ctx = setup_served_suspension(full_name="Eve Cycle 2", opaque_user_id="exu-5b")
    record, suspension = ctx["record"], ctx["suspension"]
    rec_before = validate_success(api.get_driver_record(record["id"], CLERK), 200)
    # The SERVED suspension already counts (PRD §3.7).
    assert rec_before["prior_suspension_count"] == 1
    capture_fee(record["id"], "REINSTATEMENT", 18813)
    version = get_record_version(record["id"])
    validate_success(
        api.reinstate_suspension(
            suspension["id"], {"expected_driver_record_version": version}, CLERK,
        ),
        200,
    )
    rec_after = validate_success(api.get_driver_record(record["id"], CLERK), 200)
    assert rec_after["prior_suspension_count"] == 1


# ===========================================================================
# non_linear_state_machine / knowledge_test_fail_reschedule_revert_loop
# ===========================================================================
def test_knowledge_test_fail_then_reschedule_reverts_to_scheduled(api):
    """PRD §3.3: "if score_pct falls below 80, it transitions SCHEDULED → FAILED."
    PRD §3.3: "A successful reschedule returns the test to SCHEDULED and clears
    the prior correct_answers and score_pct."

    31/40 = 77.5% -> FAILED; reschedule to a later period -> SCHEDULED again.

    Design: Difficulty/non_linear_state_machine/knowledge_test_fail_reschedule_revert_loop
    """
    record = create_driver_record(full_name="Finn Retry", date_of_birth="1990-01-01")
    kt = get_success_data(
        api.create_knowledge_test({"driver_record_id": record["id"], "scheduled_period": 0}, _proctor())
    )
    graded = validate_success(api.grade_knowledge_test(kt["id"], {"correct_answers": 31}, _proctor()), 200)
    assert graded["score_pct"] == 77.5, f"got {graded['score_pct']}"
    assert graded["status"] == "FAILED"
    rescheduled = validate_success(
        api.reschedule_knowledge_test(kt["id"], {"scheduled_period": 7}, _proctor()), 200,
    )
    assert rescheduled["status"] == "SCHEDULED"
    assert rescheduled["scheduled_period"] == 7


def test_knowledge_reschedule_clears_score_pct(api):
    """PRD §3.3: "A successful reschedule returns the test to SCHEDULED and clears
    the prior correct_answers and score_pct."
    PRD §3.3: "The score percentage score_pct is computed as correct_answers
    divided by total_questions, multiplied by 100, rounded half up to two decimal
    places, and is stored on the test."

    After a failing grade stores score_pct 77.5, rescheduling clears it back to
    SCHEDULED — the revert loop SCHEDULED -> FAILED -> SCHEDULED.

    Design: Difficulty/non_linear_state_machine/knowledge_test_fail_reschedule_revert_loop
    """
    record = create_driver_record(full_name="Finn Retry 2", date_of_birth="1990-01-01")
    kt = get_success_data(
        api.create_knowledge_test({"driver_record_id": record["id"], "scheduled_period": 0}, _proctor())
    )
    graded = validate_success(api.grade_knowledge_test(kt["id"], {"correct_answers": 31}, _proctor()), 200)
    assert graded["status"] == "FAILED"
    rescheduled = validate_success(
        api.reschedule_knowledge_test(kt["id"], {"scheduled_period": 7}, _proctor()), 200,
    )
    assert rescheduled["status"] == "SCHEDULED"
    assert rescheduled.get("score_pct") in (None, 0, 0.0), \
        f"score_pct should be cleared, got {rescheduled.get('score_pct')}"


# ===========================================================================
# transitive_cascade / medical_expiry_cascades_downgrade_then_endorsement_suspend
# ===========================================================================
def test_medical_expiry_cascades_downgrade_and_endorsement_suspend(api):
    """PRD §3.8: "When the clock advances and a record that previously had
    cdl_status of ACTIVE is left with no VALID medical card covering the current
    period, the system moves cdl_status from ACTIVE to MEDICALLY_DOWNGRADED and
    cascades every endorsement in `GRANTED` status to `SUSPENDED`."
    PRD §3.8: "On clock advance, a VALID card whose valid_through_period is now
    strictly less than the current period expires to EXPIRED."

    Depth-3: clock advance -> card EXPIRED -> cdl_status MEDICALLY_DOWNGRADED ->
    GRANTED endorsement SUSPENDED.

    Design: Difficulty/transitive_cascade/medical_expiry_cascades_downgrade_then_endorsement_suspend
    """
    ctx = active_record_with_medical_card(
        valid_through_period=5, license_class="A", opaque_user_id="exu-cas",
        full_name="Gail Med",
    )
    record = ctx["record"]
    endorsement = get_success_data(
        api.create_cdl_endorsement(
            create_cdl_endorsement_payload(record["id"], endorsement_code="P"), CLERK,
        )
    )
    # Sanity: track is ACTIVE before the lapse.
    rec0 = validate_success(api.get_driver_record(record["id"], CLERK), 200)
    assert rec0["cdl_status"] == "ACTIVE"
    api.advance_clock(6, OFFICER)
    rec = validate_success(api.get_driver_record(record["id"], CLERK), 200)
    assert rec["cdl_status"] == "MEDICALLY_DOWNGRADED", f"got {rec['cdl_status']}"
    cards = _list(api.list_record_cdl_endorsements(record["id"], CLERK))
    end = [e for e in cards if e["id"] == endorsement["id"]][0]
    assert end["status"] == "SUSPENDED", f"got {end['status']}"


def test_medical_expiry_expires_card_as_first_hop(api):
    """PRD §3.8: "On clock advance, a VALID card whose valid_through_period is now
    strictly less than the current period expires to EXPIRED."
    PRD §3.8: "the system moves cdl_status from ACTIVE to MEDICALLY_DOWNGRADED and
    cascades every endorsement in `GRANTED` status to `SUSPENDED`."

    The medical card itself moves to EXPIRED (hop 1) once the clock passes its
    valid_through_period, the cause of the downstream downgrade.

    Design: Difficulty/transitive_cascade/medical_expiry_cascades_downgrade_then_endorsement_suspend
    """
    ctx = active_record_with_medical_card(
        valid_through_period=5, license_class="A", opaque_user_id="exu-cas2",
        full_name="Gail Med 2",
    )
    record = ctx["record"]
    get_success_data(
        api.create_cdl_endorsement(
            create_cdl_endorsement_payload(record["id"], endorsement_code="P"), CLERK,
        )
    )
    api.advance_clock(6, OFFICER)
    cards = _list(api.list_record_medical_cards(record["id"], CLERK))
    assert cards[0]["status"] == "EXPIRED", f"got {cards[0]['status']}"


# ===========================================================================
# transitive_cascade / violation_cascades_suspension_open_and_status_flip
# ===========================================================================
def test_violation_opens_suspension_and_flips_status(api):
    """PRD §3.7: "If, after the recompute, the record's point_balance reaches at
    least the suspension threshold of 12 and its licensing_status is ACTIVE, the
    system opens a suspension in the same operation and flips licensing_status
    from ACTIVE to SUSPENDED."
    PRD §3.7: "a snapshot of at least 12 but under 16 yields 30 days."

    Posting a 12-point violation drives point_balance to 12 (hop 1), which opens a
    Suspension with duration_days 30 and flips the record SUSPENDED (hop 2).

    Design: Difficulty/transitive_cascade/violation_cascades_suspension_open_and_status_flip
    """
    from test_helpers import active_licensed_record
    ctx = active_licensed_record(full_name="Hank Susp", opaque_user_id="exu-6")
    record = ctx["record"]
    suspend_active_record(record["id"], points=12, occurred_period=0)
    rec = validate_success(api.get_driver_record(record["id"], CLERK), 200)
    assert rec["point_balance"] == 12, f"got {rec['point_balance']}"
    assert rec["licensing_status"] == "SUSPENDED"
    susp = get_first_suspension(record["id"])
    assert susp["duration_days"] == 30, f"got {susp['duration_days']}"


def test_violation_below_threshold_does_not_suspend(api):
    """PRD §3.7: "If, after the recompute, the record's point_balance reaches at
    least the suspension threshold of 12 and its licensing_status is ACTIVE, the
    system opens a suspension in the same operation and flips licensing_status
    from ACTIVE to SUSPENDED."

    A single 11-point violation leaves point_balance below 12, so no suspension
    opens and the record stays ACTIVE — confirming the threshold gates the cascade.

    Design: Difficulty/transitive_cascade/violation_cascades_suspension_open_and_status_flip
    """
    from test_helpers import active_licensed_record
    ctx = active_licensed_record(full_name="Hank NoSusp", opaque_user_id="exu-6b")
    record = ctx["record"]
    suspend_active_record(record["id"], points=11, occurred_period=0)
    rec = validate_success(api.get_driver_record(record["id"], CLERK), 200)
    assert rec["point_balance"] == 11
    assert rec["licensing_status"] == "ACTIVE"


# --- helpers -------------------------------------------------------------
def _proctor():
    from test_helpers import make_proctor_headers
    return make_proctor_headers("kp-1")


def _list(resp):
    data = get_success_data(resp)
    return data if isinstance(data, list) else data.get("data", data)
