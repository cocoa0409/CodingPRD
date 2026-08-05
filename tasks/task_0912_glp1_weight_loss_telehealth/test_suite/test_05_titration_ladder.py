"""Climbing and descending the titration ladder."""

from test_helpers import (
    assert_same_instant,
    assert_titration_step,
    due_titration_step,
    file_check_in,
    make_provider_headers,
    platform_admin_headers,
    read_prescription,
    register_clinician,
    resolve_check_in,
    set_clock,
    setup_active_prescription,
    triage_check_in,
    validate_error,
    validate_paginated,
    validate_success,
)


def _escalate(api, scenario, step_id, payload=None):
    return api.escalate_titration_step(
        step_id, payload or {}, make_provider_headers(scenario["clinician"]["id"])
    )


def test_escalation_at_twenty_seven_whole_days_is_refused(api):
    """PRD §3.5: "**Interval.** The elapsed time since the prescription's
    `last_dose_change_at`, taken in whole days by dividing the difference in
    seconds by 86,400 and discarding the remainder, must reach the required
    interval. The requirement is normally 28 days, but it stretches to 42 days
    whenever the prescription's `severity_index_since_dose_change` has reached 4 or
    more — a member who has been struggling since their last increase waits half
    again as long. In both cases the comparison is inclusive: elapsed days *equal
    to* the requirement are sufficient. A shortfall is refused with
    `ERR_TITRATION_INTERVAL_NOT_MET` (409)."

    Design: Difficulty/boundary_precision_check/titration_interval_exactly_twenty_eight_days_permits_escalation
    """
    scenario = setup_active_prescription(
        patient={"email": "tao@example.com", "full_name": "Tao Lin"}
    )
    set_clock("2026-06-28T00:00:00Z")

    response = _escalate(api, scenario, scenario["step"]["id"])

    validate_error(response, "ERR_TITRATION_INTERVAL_NOT_MET")
    unchanged = validate_success(
        api.get_titration_step(scenario["step"]["id"], platform_admin_headers())
    )
    assert unchanged["status"] == "DUE"


def test_escalation_at_exactly_twenty_eight_whole_days_succeeds(api):
    """PRD §3.5: "In both cases the comparison is inclusive: elapsed days *equal
    to* the requirement are sufficient."
    PRD §3.5: "A successful escalation moves the rung `DUE → ADMINISTERED`, sets
    its `administered_at` to the clock and records the `second_signer_provider_id`
    when one was supplied."
    PRD §3.5: "For `SEMAGLUTIDE` the ladder runs 0.25 mg at rung 1, 0.5 mg at rung
    2, 1.0 mg at rung 3, 1.7 mg at rung 4 and 2.4 mg at rung 5."

    Design: Difficulty/boundary_precision_check/titration_interval_exactly_twenty_eight_days_permits_escalation
    """
    scenario = setup_active_prescription(
        patient={"email": "tao2@example.com", "full_name": "Tao Lin"}
    )
    set_clock("2026-06-29T00:00:00Z")

    stepped = validate_success(_escalate(api, scenario, scenario["step"]["id"]))

    assert_titration_step(stepped)
    assert stepped["status"] == "ADMINISTERED"
    prescription = read_prescription(
        scenario["prescription"]["id"], scenario["clinician"]["id"]
    )
    assert prescription["dose_level"] == 2
    assert prescription["dose_mg"] == 0.5


def test_planning_date_permits_an_escalation_the_tolerability_gate_refuses(api):
    """PRD §3.5: "Whenever a rung row is created, it is set to that rung's
    `created_at` plus 28 days, flat, ignoring the member's side-effect history
    entirely."
    PRD §3.5: "The rule that actually decides whether an escalation may proceed is
    stricter and reads history, so an escalation can legitimately be refused on a
    date that `earliest_escalation_at` already permits."
    PRD §3.8: "Only the since-last-dose-change index feeds the titration interval
    rule; reaching 4 on that index is what stretches the wait from 28 days to 42."

    Design: Difficulty/dual_variant_calc/titration_planning_date_versus_tolerability_gate
    """
    scenario = setup_active_prescription(
        patient={"email": "bo@example.com", "full_name": "Bo Lane"}
    )
    assert_same_instant(
        scenario["step"]["earliest_escalation_at"],
        "2026-06-29T00:00:00Z",
        "earliest_escalation_at",
    )

    set_clock("2026-06-05T00:00:00Z")
    check_in = file_check_in(
        scenario["patient"]["id"],
        scenario["prescription"]["id"],
        nausea_score=2,
        vomiting_score=1,
        dehydration_flag=False,
    )
    triaged = triage_check_in(check_in["id"], scenario["clinician"]["id"])
    assert triaged["severity_score"] == 4
    assert triaged["status"] == "CLEARED"
    prescription = read_prescription(
        scenario["prescription"]["id"], scenario["clinician"]["id"]
    )
    assert prescription["severity_index_since_dose_change"] == 4

    set_clock("2026-06-29T00:00:00Z")
    response = _escalate(api, scenario, scenario["step"]["id"])

    validate_error(response, "ERR_TITRATION_INTERVAL_NOT_MET")


def test_tolerability_stretched_interval_admits_the_escalation_at_forty_two_days(api):
    """PRD §3.5: "The requirement is normally 28 days, but it stretches to 42 days
    whenever the prescription's `severity_index_since_dose_change` has reached 4 or
    more — a member who has been struggling since their last increase waits half
    again as long."
    PRD §3.5: "On the prescription it increments `dose_level` by one, re-reads
    `dose_mg` from the ladder table at the new level, and sets
    `last_dose_change_at` to the clock."

    Design: Difficulty/dual_variant_calc/titration_planning_date_versus_tolerability_gate
    """
    scenario = setup_active_prescription(
        patient={"email": "bo2@example.com", "full_name": "Bo Lane"}
    )
    set_clock("2026-06-05T00:00:00Z")
    check_in = file_check_in(
        scenario["patient"]["id"],
        scenario["prescription"]["id"],
        nausea_score=2,
        vomiting_score=1,
    )
    triage_check_in(check_in["id"], scenario["clinician"]["id"])

    set_clock("2026-07-13T00:00:00Z")
    stepped = validate_success(_escalate(api, scenario, scenario["step"]["id"]))

    assert stepped["status"] == "ADMINISTERED"
    prescription = read_prescription(
        scenario["prescription"]["id"], scenario["clinician"]["id"]
    )
    assert prescription["dose_level"] == 2
    assert prescription["dose_mg"] == 0.5


def test_escalate_branch_advances_the_ladder_and_opens_a_successor_rung(api):
    """PRD §3.5: "A successful escalation moves the rung `DUE → ADMINISTERED`, sets
    its `administered_at` to the clock and records the `second_signer_provider_id`
    when one was supplied."
    PRD §3.5: "Finally it creates the next rung in `DUE` status with `step_number`
    one greater, at the new `dose_level` and `dose_mg`, and with
    `earliest_escalation_at` set to the clock plus 28 days."

    Design: Difficulty/non_linear_state_machine/titration_step_three_way_fork_escalate_reduce_hold
    """
    scenario = setup_active_prescription(
        patient={"email": "ivy@example.com", "full_name": "Ivy Sun"}
    )
    set_clock("2026-06-29T00:00:00Z")

    administered = validate_success(_escalate(api, scenario, scenario["step"]["id"]))

    assert administered["status"] == "ADMINISTERED"
    assert_same_instant(
        administered["administered_at"], "2026-06-29T00:00:00Z", "administered_at"
    )

    successor = due_titration_step(
        scenario["prescription"]["id"], scenario["clinician"]["id"]
    )
    assert successor["step_number"] == scenario["step"]["step_number"] + 1
    assert successor["dose_level"] == 2
    assert successor["dose_mg"] == 0.5
    assert_same_instant(
        successor["earliest_escalation_at"],
        "2026-07-27T00:00:00Z",
        "earliest_escalation_at",
    )


def test_reduce_and_hold_branches_diverge_on_successor_creation(api):
    """PRD §3.5: "A successful reduction sets the rung's `administered_at` to the
    clock, decrements the prescription's `dose_level` by one, re-reads `dose_mg` at
    the reduced level, sets `last_dose_change_at` to the clock, and creates the
    next rung in `DUE` status at the reduced level with `earliest_escalation_at`
    set to the clock plus 28 days."
    PRD §3.5: "This moves the rung `DUE → HELD` and sets `hold_reason` to
    `PROVIDER_HOLD`. It is permitted while the governing prescription is either
    `ACTIVE` or `HELD`. No `dose_level` change occurs, no `last_dose_change_at` is
    written, and no new rung is created."

    Design: Difficulty/non_linear_state_machine/titration_step_three_way_fork_escalate_reduce_hold
    """
    scenario = setup_active_prescription(
        patient={"email": "ivy2@example.com", "full_name": "Ivy Sun"}
    )
    provider_headers = make_provider_headers(scenario["clinician"]["id"])
    set_clock("2026-06-29T00:00:00Z")
    validate_success(_escalate(api, scenario, scenario["step"]["id"]))

    second_rung = due_titration_step(
        scenario["prescription"]["id"], scenario["clinician"]["id"]
    )
    reduced = validate_success(
        api.reduce_titration_step(second_rung["id"], {}, provider_headers)
    )
    assert reduced["status"] == "REDUCED"
    assert reduced["dose_level"] == 2

    third_rung = due_titration_step(
        scenario["prescription"]["id"], scenario["clinician"]["id"]
    )
    assert third_rung["dose_level"] == 1

    held = validate_success(
        api.hold_titration_step(third_rung["id"], {}, provider_headers)
    )
    assert held["status"] == "HELD"
    assert held["hold_reason"] == "PROVIDER_HOLD"

    rows, meta = validate_paginated(
        api.list_titration_steps(
            platform_admin_headers(),
            params={"prescription_id": scenario["prescription"]["id"]},
        )
    )
    assert meta["total_count"] == 3, "the hold branch creates no successor rung"

    prescription = read_prescription(
        scenario["prescription"]["id"], scenario["clinician"]["id"]
    )
    assert prescription["dose_level"] == 1
    assert prescription["dose_mg"] == 0.25
    assert_same_instant(
        prescription["last_dose_change_at"],
        "2026-06-29T00:00:00Z",
        "last_dose_change_at",
    )


def test_high_dose_escalation_demands_a_second_signer_who_is_not_the_prescriber(api):
    """PRD §3.5: "**Second signer present.** The target level is the current
    `dose_level` plus one. If the target level is 4 or 5, a
    `second_signer_provider_id` must be supplied; its absence is refused with
    `ERR_SECOND_SIGNER_REQUIRED` (422)."
    PRD §3.5: "**Second signer admissible.** When a second signer is supplied, it
    must differ from the prescription's `prescriber_provider_id`, must name a
    practitioner whose `provider_type` is `CLINICIAN`, and must name one whose
    `status` is `ACTIVE`. Any of those three failing is refused with
    `ERR_SECOND_SIGNER_CONFLICT` (403)."

    Design: Corner/validations/second_signer_rules_and_max_dose_along_the_full_ladder
    """
    scenario = setup_active_prescription(
        patient={"email": "val1@example.com", "full_name": "Val One"}
    )
    co_signer = register_clinician(full_name="Dr Ola Finn")
    prescriber = scenario["clinician"]["id"]

    set_clock("2026-06-29T00:00:00Z")
    validate_success(_escalate(api, scenario, scenario["step"]["id"]))
    rung_two = due_titration_step(scenario["prescription"]["id"], prescriber)
    set_clock("2026-07-27T00:00:00Z")
    validate_success(_escalate(api, scenario, rung_two["id"]))
    rung_three = due_titration_step(scenario["prescription"]["id"], prescriber)
    set_clock("2026-08-24T00:00:00Z")

    validate_error(
        _escalate(api, scenario, rung_three["id"]), "ERR_SECOND_SIGNER_REQUIRED"
    )
    validate_error(
        _escalate(api, scenario, rung_three["id"], {"second_signer_provider_id": prescriber}),
        "ERR_SECOND_SIGNER_CONFLICT",
    )

    signed = validate_success(
        _escalate(
            api, scenario, rung_three["id"], {"second_signer_provider_id": co_signer["id"]}
        )
    )
    assert signed["second_signer_provider_id"] == co_signer["id"]

    prescription = read_prescription(scenario["prescription"]["id"], prescriber)
    assert prescription["dose_level"] == 4
    assert prescription["dose_mg"] == 1.7


def test_ladder_ceiling_refuses_any_escalation_beyond_rung_five(api):
    """PRD §3.5: "**Ladder ceiling.** If the prescription's `dose_level` is already
    5, there is no rung above it and the request is refused with
    `ERR_TITRATION_MAX_DOSE_REACHED` (422). Equivalently, escalation requires the
    current `dose_level` to be strictly less than 5."
    PRD §3.5: "For `SEMAGLUTIDE` the ladder runs 0.25 mg at rung 1, 0.5 mg at rung
    2, 1.0 mg at rung 3, 1.7 mg at rung 4 and 2.4 mg at rung 5."

    Design: Corner/validations/second_signer_rules_and_max_dose_along_the_full_ladder
    """
    scenario = setup_active_prescription(
        patient={"email": "val1b@example.com", "full_name": "Val One B"}
    )
    co_signer = register_clinician(full_name="Dr Ola Finn")
    prescriber = scenario["clinician"]["id"]
    rung = scenario["step"]

    for moment, level in (
        ("2026-06-29T00:00:00Z", 2),
        ("2026-07-27T00:00:00Z", 3),
        ("2026-08-24T00:00:00Z", 4),
        ("2026-09-21T00:00:00Z", 5),
    ):
        set_clock(moment)
        payload = {"second_signer_provider_id": co_signer["id"]} if level >= 4 else {}
        validate_success(_escalate(api, scenario, rung["id"], payload))
        rung = due_titration_step(scenario["prescription"]["id"], prescriber)

    topped = read_prescription(scenario["prescription"]["id"], prescriber)
    assert topped["dose_level"] == 5
    assert topped["dose_mg"] == 2.4

    set_clock("2026-10-19T00:00:00Z")
    refused = _escalate(
        api, scenario, rung["id"], {"second_signer_provider_id": co_signer["id"]}
    )
    validate_error(refused, "ERR_TITRATION_MAX_DOSE_REACHED")


def test_open_escalated_check_in_blocks_the_escalation(api):
    """PRD §3.5: "**No open escalation.** If any check-in for that prescription is
    still in `ESCALATED` status, the request is refused with
    `ERR_OPEN_ESCALATED_CHECK_IN` (409)."
    PRD §3.8: "A score of 7 or 8 raises the flag and stops there: the report sits
    `ESCALATED`, the prescription stays `ACTIVE`, and nothing else moves — but
    while that report remains open, the escalation gate of §3.5 will refuse any
    dose increase."

    Design: Difficulty/cross_entity_state_dependency/escalation_blocked_by_open_escalated_check_in
    """
    scenario = setup_active_prescription(
        patient={"email": "yuri@example.com", "full_name": "Yuri Salas"}
    )
    set_clock("2026-06-05T00:00:00Z")
    check_in = file_check_in(
        scenario["patient"]["id"],
        scenario["prescription"]["id"],
        nausea_score=3,
        vomiting_score=2,
    )
    triaged = triage_check_in(check_in["id"], scenario["clinician"]["id"])
    assert triaged["severity_score"] == 7
    assert triaged["status"] == "ESCALATED"

    set_clock("2026-07-13T00:00:00Z")
    refused = _escalate(api, scenario, scenario["step"]["id"])

    validate_error(refused, "ERR_OPEN_ESCALATED_CHECK_IN")
    prescription = read_prescription(
        scenario["prescription"]["id"], scenario["clinician"]["id"]
    )
    assert prescription["clinical_status"] == "ACTIVE", (
        "a score of 7 raises the flag without freezing the therapy"
    )


def test_resolving_the_escalation_unblocks_the_ladder(api):
    """PRD §3.8: "**Resolution** unwinds it. A `Provider` closes an escalation,
    moving the report `ESCALATED → RESOLVED` and setting `resolved_at` to the
    clock."
    PRD §3.5: "It then recomputes **both** severity indices against the current
    clock; because the since-last-dose-change window's baseline has just moved to
    now, `severity_index_since_dose_change` necessarily resets to zero, while
    `severity_index_rolling` is recomputed over its own thirty-day window and may
    well stay high."

    Design: Difficulty/cross_entity_state_dependency/escalation_blocked_by_open_escalated_check_in
    """
    scenario = setup_active_prescription(
        patient={"email": "yuri2@example.com", "full_name": "Yuri Salas"}
    )
    set_clock("2026-06-05T00:00:00Z")
    check_in = file_check_in(
        scenario["patient"]["id"],
        scenario["prescription"]["id"],
        nausea_score=3,
        vomiting_score=2,
    )
    triage_check_in(check_in["id"], scenario["clinician"]["id"])

    set_clock("2026-07-13T00:00:00Z")
    validate_error(
        _escalate(api, scenario, scenario["step"]["id"]), "ERR_OPEN_ESCALATED_CHECK_IN"
    )

    resolved = resolve_check_in(check_in["id"], scenario["clinician"]["id"])
    assert resolved["status"] == "RESOLVED"

    stepped = validate_success(_escalate(api, scenario, scenario["step"]["id"]))
    assert stepped["status"] == "ADMINISTERED"

    prescription = read_prescription(
        scenario["prescription"]["id"], scenario["clinician"]["id"]
    )
    assert prescription["dose_level"] == 2
    assert prescription["severity_index_since_dose_change"] == 0
