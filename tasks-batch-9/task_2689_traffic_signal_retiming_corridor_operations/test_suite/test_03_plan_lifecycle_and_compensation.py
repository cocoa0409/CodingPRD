"""Timing plan axes, the certification gate ladder, and the return compensation."""
from test_helpers import ApiErrorId, api_client, validate_error
from test_helpers.fixtures import (
    CANONICAL_PLAN,
    CANONICAL_SPLITS,
    CANONICAL_SPLITS_PED_SHORT,
    INDEPENDENT_REVIEWER,
    REVIEWER_ID,
    certify_plan,
    coordinate_project,
    patch_intersection,
    read_intersection,
    read_ped_checks,
    read_plan,
    read_splits,
    return_plan,
    setup_canonical_coordinated_plan,
    setup_submitted_plan,
    submit_plan,
    waive_check,
)

CANONICAL = {"plan_overrides": dict(CANONICAL_PLAN), "splits": CANONICAL_SPLITS}


def test_waiver_moves_the_compliance_axis_while_the_workflow_axis_holds_still():
    """Waiving the only failing check turns the plan WAIVED but leaves it COORDINATED.

    PRD §3.7: "A `CertifyingEngineer` may **waive** a check, moving its `result`
    `FAIL → WAIVED`, and must supply a `waiver_justification` in writing; the
    server records that text and stamps `waived_by_user_id` with the acting
    `X-User-ID`." and "After a waiver is applied, if the plan no longer holds any
    check whose `result` is `FAIL`, the plan's `ped_compliance_state` becomes
    `WAIVED` and the plan's own `version` is incremented."

    Design: Difficulty/non_linear_state_machine/timing_plan_ped_axis_waiver_advances_while_status_axis_stands_still
    """
    ctx = setup_canonical_coordinated_plan(splits=CANONICAL_SPLITS_PED_SHORT)
    plan_id = ctx["plan"]["id"]
    checks = read_ped_checks(plan_id)
    assert len(checks) == 1
    assert float(checks[0]["required_ped_clear_sec"]) == 17.8
    assert float(checks[0]["provided_ped_clear_sec"]) == 17.7
    assert checks[0]["result"] == "FAIL"
    assert checks[0]["failure_reason"] == "PED_CLEAR_SHORT"

    waived = waive_check(checks[0]["id"])
    assert waived["result"] == "WAIVED"
    assert waived["waived_by_user_id"] == REVIEWER_ID

    plan = read_plan(plan_id)
    assert plan["status"] == "COORDINATED"
    assert plan["ped_compliance_state"] == "WAIVED"


def test_workflow_axis_travels_twice_while_the_compliance_axis_stays_waived():
    """Submit then certify move `status` twice and never touch `ped_compliance_state`.

    PRD §3.7: "the compliance axis can travel `NON_COMPLIANT → WAIVED` while the
    workflow axis stands perfectly still at `COORDINATED`, and — as the next
    subsection shows — the workflow axis can travel `SUBMITTED → CERTIFIED`
    without the compliance axis moving at all." PRD §3.8: "Certification moves
    the plan `SUBMITTED → CERTIFIED`, writes the acting `X-User-ID` into
    `certified_by_user_id`, and increments the plan's `version`."

    Design: Difficulty/non_linear_state_machine/timing_plan_ped_axis_waiver_advances_while_status_axis_stands_still
    """
    ctx = setup_canonical_coordinated_plan(splits=CANONICAL_SPLITS_PED_SHORT)
    plan_id = ctx["plan"]["id"]
    waive_check(read_ped_checks(plan_id)[0]["id"])

    submitted = submit_plan(plan_id)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["ped_compliance_state"] == "WAIVED"

    certified = certify_plan(plan_id)
    assert certified["status"] == "CERTIFIED"
    assert certified["ped_compliance_state"] == "WAIVED"
    assert certified["certified_by_user_id"] == REVIEWER_ID
    assert certified["return_count"] == 0


def test_certify_state_gate_is_reported_ahead_of_the_posture_gate():
    """With both gates violated the plan-state failure is the one that surfaces.

    PRD §3.8: "The reviewing `CertifyingEngineer` must not be the plan's author,
    must find the plan in `SUBMITTED` — otherwise `ERR_PLAN_NOT_SUBMITTED` — and
    must find the plan's intersection in a posture other than `BLOCKED`, since
    certifying timing for an intersection the central system cannot even reach,
    or whose detection has failed outright, is refused with
    `ERR_POSTURE_BLOCKS_CERTIFICATION`."

    Design: Difficulty/priority_pair_validation_conflict/certify_state_gate_priority_40_beats_posture_gate_priority_55_rejected
    """
    ctx = setup_canonical_coordinated_plan()
    plan_id = ctx["plan"]["id"]
    intersection_id = ctx["intersections"][0]["id"]
    assert read_intersection(intersection_id)["operational_posture"] == "READY"

    blocked = patch_intersection(intersection_id, detection_status="FAILED")
    assert blocked["operational_posture"] == "BLOCKED"

    # The plan is COORDINATED, not SUBMITTED, and the intersection is BLOCKED.
    validate_error(
        api_client.certify_timing_plan(plan_id, INDEPENDENT_REVIEWER),
        ApiErrorId.ERR_PLAN_NOT_SUBMITTED.value,
    )
    assert read_plan(plan_id)["status"] == "COORDINATED"


def test_repairing_only_the_state_gate_exposes_the_posture_gate():
    """Once the plan is SUBMITTED the same call reports the posture failure instead.

    PRD §3.8: "must find the plan in `SUBMITTED` — otherwise
    `ERR_PLAN_NOT_SUBMITTED` — and must find the plan's intersection in a posture
    other than `BLOCKED` ... refused with `ERR_POSTURE_BLOCKS_CERTIFICATION`."

    Design: Difficulty/priority_pair_validation_conflict/certify_state_gate_priority_40_beats_posture_gate_priority_55_rejected
    """
    ctx = setup_canonical_coordinated_plan()
    plan_id = ctx["plan"]["id"]
    intersection_id = ctx["intersections"][0]["id"]

    patch_intersection(intersection_id, detection_status="FAILED")
    validate_error(
        api_client.certify_timing_plan(plan_id, INDEPENDENT_REVIEWER),
        ApiErrorId.ERR_PLAN_NOT_SUBMITTED.value,
    )

    patch_intersection(intersection_id, detection_status="FULL")
    assert submit_plan(plan_id)["status"] == "SUBMITTED"
    patch_intersection(intersection_id, detection_status="FAILED")

    validate_error(
        api_client.certify_timing_plan(plan_id, INDEPENDENT_REVIEWER),
        ApiErrorId.ERR_POSTURE_BLOCKS_CERTIFICATION.value,
    )

    after = read_plan(plan_id)
    assert after["status"] == "SUBMITTED"
    assert after["certified_by_user_id"] is None


def test_certification_is_refused_while_the_intersection_is_blocked():
    """Nothing about the plan changes; the other entity's derived state decides.

    PRD §3.8: "must find the plan's intersection in a posture other than
    `BLOCKED`, since certifying timing for an intersection the central system
    cannot even reach, or whose detection has failed outright, is refused with
    `ERR_POSTURE_BLOCKS_CERTIFICATION`."

    Design: Difficulty/cross_entity_state_dependency/timing_plan_certification_depends_on_intersection_operational_posture
    """
    ctx = setup_submitted_plan(**CANONICAL)
    plan_id = ctx["plan"]["id"]
    assert ctx["plan"]["status"] == "SUBMITTED"

    blocked = patch_intersection(ctx["intersections"][0]["id"], detection_status="FAILED")
    assert blocked["operational_posture"] == "BLOCKED"

    validate_error(
        api_client.certify_timing_plan(plan_id, INDEPENDENT_REVIEWER),
        ApiErrorId.ERR_POSTURE_BLOCKS_CERTIFICATION.value,
    )
    assert read_plan(plan_id)["status"] == "SUBMITTED"


def test_a_restricted_intersection_may_still_be_certified():
    """The gate admits any posture that is not BLOCKED, so RESTRICTED passes it.

    PRD §3.8: "Note that a `RESTRICTED` intersection may be certified; only
    `BLOCKED` bars it." PRD §2.10: "Otherwise, if communication is
    `INTERMITTENT`, or detection is `PARTIAL` or `NONE`, the posture is
    `RESTRICTED`."

    Design: Difficulty/cross_entity_state_dependency/timing_plan_certification_depends_on_intersection_operational_posture
    """
    ctx = setup_submitted_plan(**CANONICAL)
    plan_id = ctx["plan"]["id"]
    intersection_id = ctx["intersections"][0]["id"]

    patch_intersection(intersection_id, detection_status="FAILED")
    validate_error(
        api_client.certify_timing_plan(plan_id, INDEPENDENT_REVIEWER),
        ApiErrorId.ERR_POSTURE_BLOCKS_CERTIFICATION.value,
    )

    relaxed = patch_intersection(intersection_id, detection_status="PARTIAL")
    assert relaxed["operational_posture"] == "RESTRICTED"

    certified = certify_plan(plan_id)
    assert certified["status"] == "CERTIFIED"
    assert certified["certified_by_user_id"] == REVIEWER_ID

    # Certification alone deploys nothing, so the intersection is not retimed.
    intersection = read_intersection(intersection_id)
    assert intersection["detection_status"] == "PARTIAL"
    assert intersection["last_retimed_at"] is None


def test_return_restores_every_phase_split_second_by_second():
    """The return undoes the whole pipeline, per phase and not merely in total.

    PRD §3.8: "The plan then moves `SUBMITTED → DRAFT` and every write the
    coordination pipeline made to it is undone: `cycle_length_sec` is restored
    from `drafted_cycle_length_sec`; every phase split's `effective_split_sec` is
    restored to its own `split_sec`, processed in `phase_number` ascending order;
    `offset_sec` returns to 0; `ped_compliance_state` returns to `PENDING`;
    `effective_split_total_sec` is restored to `drafted_split_total_sec`; and
    every pedestrian compliance check belonging to the plan is **deleted**
    outright". PRD §2.12: "once a timing plan has left `DRAFT`, the sum of its
    phases' effective splits equals its operating cycle length exactly, with no
    drift."

    Design: Difficulty/compensating_invariant/plan_return_conserves_split_seconds_against_the_drafted_total
    """
    ctx = setup_submitted_plan(**CANONICAL)
    plan_id = ctx["plan"]["id"]

    forward = read_plan(plan_id)
    assert forward["cycle_length_sec"] == 105
    assert forward["drafted_cycle_length_sec"] == 90
    assert forward["drafted_split_total_sec"] == 86
    assert forward["effective_split_total_sec"] == 105
    assert forward["return_count"] == 0
    assert {s["phase_number"]: s["effective_split_sec"] for s in read_splits(plan_id)} == {
        1: 26, 2: 25, 4: 27, 6: 27
    }

    returned = return_plan(plan_id, reason="Offset needs re-checking against the master clock")
    assert returned["status"] == "DRAFT"
    assert returned["return_count"] == 1
    assert returned["cycle_length_sec"] == 90
    assert returned["offset_sec"] == 0
    assert returned["ped_compliance_state"] == "PENDING"
    assert returned["effective_split_total_sec"] == 86
    assert returned["drafted_split_total_sec"] == 86

    splits = read_splits(plan_id)
    assert [s["phase_number"] for s in splits] == [1, 2, 4, 6]
    for split in splits:
        assert split["effective_split_sec"] == split["split_sec"]
    assert {s["phase_number"]: s["effective_split_sec"] for s in splits} == {
        1: 21, 2: 21, 4: 22, 6: 22
    }
    assert sum(s["effective_split_sec"] for s in splits) == 86
    assert read_ped_checks(plan_id) == []


def test_the_pipeline_replays_identically_after_a_return():
    """No hidden residue survives the compensation, so coordination is reproducible.

    PRD §3.8: "The split-second invariant must hold with zero drift after a
    return: the plan is byte-for-byte back in the state a fresh draft would be
    in." PRD §3.6: "`drafted_cycle_length_sec` is deliberately left alone — it is
    the memory of what the engineer asked for, and the return and reopen
    compensations described later restore `cycle_length_sec` from it."

    Design: Difficulty/compensating_invariant/plan_return_conserves_split_seconds_against_the_drafted_total
    """
    ctx = setup_submitted_plan(**CANONICAL)
    plan_id = ctx["plan"]["id"]
    return_plan(plan_id, reason="Rebuild the splits from the drafted intent")
    assert read_plan(plan_id)["status"] == "DRAFT"

    coordinate_project(ctx["project"]["id"])

    replayed = read_plan(plan_id)
    assert replayed["status"] == "COORDINATED"
    assert replayed["cycle_length_sec"] == 105
    assert replayed["drafted_cycle_length_sec"] == 90
    assert replayed["drafted_split_total_sec"] == 86
    assert replayed["effective_split_total_sec"] == 105
    assert {s["phase_number"]: s["effective_split_sec"] for s in read_splits(plan_id)} == {
        1: 26, 2: 25, 4: 27, 6: 27
    }
    assert len(read_ped_checks(plan_id)) == 1
