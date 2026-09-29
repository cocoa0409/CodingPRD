"""Loops and independent dimensions inside the state machines."""

from test_helpers import (
    COORDINATOR,
    SURVEYOR,
    SURVEYOR_BETA,
    SURVEYOR_BETA_USER_ID,
    add_finding,
    api_client,
    correction_decision_payload,
    correction_submission_payload,
    decide_assessment,
    enroll_pt,
    get_success_data,
    issue_survey,
    open_survey,
    pt_investigation_decision_payload,
    pt_investigation_payload,
    read_assessment,
    read_deficiency,
    read_inspection,
    read_operator,
    read_pt_enrollment,
    read_pt_event,
    read_site,
    register_pt_event,
    run_oversight,
    score_pt_event,
    set_clock,
    setup_competent_operator,
    setup_covered_site,
    setup_site_with_director,
    submit_assessment,
)

# ─── operator_regains_competency_while_access_stays_locked_out ──────


def _lapsed_operator_awaiting_a_second_decision():
    """An operator lapsed by the October sweep, with a fresh assessment SUBMITTED."""
    env = setup_competent_operator(
        certificate_overrides={"certificate_number": "45D2243006"},
        site_overrides={
            "name": "Urgent Care POCT",
            "department_code": "DEPT-150",
            "complexity_scope": "WAIVED",
        },
        assessment_overrides={"expires_at": "2026-09-15"},
    )
    set_clock("2026-10-01T00:00:00Z")
    run_oversight(note="October epoch")
    env["lapsed"] = read_operator(env["subject"]["id"])
    env["second_assessment"] = submit_assessment(
        env["subject"]["id"], env["assessor"]["id"],
        assessment_type="ANNUAL",
        effective_date="2026-10-01", expires_at="2027-10-01",
    )
    return env


def test_the_sweep_freezes_fourteen_grace_days_for_a_non_physician_operator():
    """A medical assistant at an OPEN site gets 14 days and a 2026-09-29 deadline.

    PRD 3.9: "For every operator whose `access_status` is not `DEACTIVATED`, walked
    by `created_at` ascending then `hire_date` ascending then `full_name` ascending,
    compute a base grace of 30 days when `role_title` is `PHYSICIAN` and 14 days for
    every other `role_title`. Then compute a posture penalty from the phase-0
    snapshot of that operator's site: no penalty when the snapshot was `OPEN`, one
    week when it was `RESTRICTED`, and two weeks when it was `SUSPENDED`."

    Design: Difficulty/non_linear_state_machine/operator_regains_competency_while_access_stays_locked_out
    """
    env = _lapsed_operator_awaiting_a_second_decision()

    lapsed = env["lapsed"]
    assert lapsed["current_grace_days"] == 14
    assert lapsed["lapse_deadline"] == "2026-09-29"
    assert lapsed["competency_status"] == "LAPSED"
    assert lapsed["access_status"] == "LOCKED_OUT"
    assert lapsed["lockout_reason"] == "COMPETENCY_LAPSED"


def test_approval_restores_competency_and_leaves_the_access_dimension_locked():
    """The two dimensions of one operator row advance on different triggers.

    PRD 3.3: "Approval touches the access dimension not at all: an operator sitting
    at `LOCKED_OUT` stays `LOCKED_OUT` and keeps their existing `lockout_reason`,
    competent but still barred from the instrument."

    Design: Difficulty/non_linear_state_machine/operator_regains_competency_while_access_stays_locked_out
    """
    env = _lapsed_operator_awaiting_a_second_decision()

    approved = decide_assessment(
        env["second_assessment"]["id"], "APPROVE", env["director_headers"],
        note="Re-assessed after lapse",
    )

    operator = read_operator(env["subject"]["id"])
    assert approved["status"] == "APPROVED"
    assert operator["competency_status"] == "COMPETENT"
    assert operator["access_status"] == "LOCKED_OUT"
    assert operator["lockout_reason"] == "COMPETENCY_LAPSED"
    assert operator["competency_expires_at"] == "2027-10-01"
    assert operator["consecutive_rejection_count"] == 0


def test_the_earlier_approval_survives_and_the_operator_is_still_counted_as_locked():
    """The superseded window stays APPROVED and the site still counts the lock-out.

    PRD 2.11: "`locked_out_operator_count` counts the site's operators whose
    `access_status` is `LOCKED_OUT`, and `lapsed_or_locked_operator_count` counts
    those whose `competency_status` is `LAPSED` **or** whose `access_status` is
    `LOCKED_OUT` — an operator satisfying both conditions is counted once."

    Design: Difficulty/non_linear_state_machine/operator_regains_competency_while_access_stays_locked_out
    """
    env = _lapsed_operator_awaiting_a_second_decision()

    decide_assessment(
        env["second_assessment"]["id"], "APPROVE", env["director_headers"],
    )

    site = read_site(env["site"]["id"])
    assert read_assessment(env["assessment"]["id"])["status"] == "APPROVED"
    assert site["total_operator_count"] == 3
    assert site["locked_out_operator_count"] == 1
    assert site["lapsed_or_locked_operator_count"] == 1


# ─── deficiency_correction_rejection_cycle_then_close ───────────────


def _finding_on_its_second_plan_of_correction():
    """One STANDARD_LEVEL finding rejected once and resubmitted."""
    _certificate, site, _coverage = setup_covered_site(
        certificate_overrides={"certificate_number": "45D2243007"},
        site_overrides={
            "name": "Oncology POCT",
            "department_code": "DEPT-160",
            "complexity_scope": "WAIVED",
        },
    )
    inspection = open_survey(
        site["id"], SURVEYOR,
        inspection_type="BIENNIAL_SURVEY", scheduled_date="2026-08-01",
    )
    finding = add_finding(
        inspection["id"], SURVEYOR,
        category="RESULT_REPORTING", severity="STANDARD_LEVEL",
        description="Manual results posted without second-person review",
        correction_due_date="2026-09-30",
    )
    inspection = issue_survey(inspection["id"], SURVEYOR, issued_on="2026-08-01")
    get_success_data(
        api_client.submit_correction(
            finding["id"],
            correction_submission_payload(
                correction_narrative="Second-person review checklist added",
                evidence_ref="EV-RR-001",
            ),
            COORDINATOR,
        )
    )
    rejected = get_success_data(
        api_client.decide_correction(
            finding["id"],
            correction_decision_payload(
                "REJECT", note="No evidence of staff attestation"
            ),
            SURVEYOR_BETA,
        )
    )
    resubmitted = get_success_data(
        api_client.submit_correction(
            finding["id"],
            correction_submission_payload(
                correction_narrative=(
                    "Checklist plus signed attestations for all 12 operators"
                ),
                evidence_ref="EV-RR-002",
            ),
            COORDINATOR,
        )
    )
    return site, inspection, finding, rejected, resubmitted


def test_a_rejected_plan_returns_the_finding_to_the_correction_loop():
    """Rejection leaves the round at 1; the resubmission raises it to 2.

    PRD 3.8: "**Rejection** moves the finding `CORRECTION_SUBMITTED →
    CORRECTION_REJECTED` and leaves the weight ledger untouched; the finding
    re-enters the correction loop, so `OPEN → CORRECTION_SUBMITTED →
    CORRECTION_REJECTED → CORRECTION_SUBMITTED → … → CLOSED` is a legitimate
    history."

    Design: Difficulty/non_linear_state_machine/deficiency_correction_rejection_cycle_then_close_bubbles_inspection
    """
    _site, _inspection, _finding, rejected, resubmitted = (
        _finding_on_its_second_plan_of_correction()
    )

    assert rejected["status"] == "CORRECTION_REJECTED"
    assert rejected["correction_round"] == 1
    assert resubmitted["status"] == "CORRECTION_SUBMITTED"
    assert resubmitted["correction_round"] == 2


def test_accepting_the_second_plan_closes_the_finding_and_bubbles_the_survey():
    """With every finding terminal the survey itself moves to CLOSED.

    PRD 3.8: "Acceptance also bubbles upward: when every finding of the survey has
    reached `CLOSED` or `VOIDED`, the survey itself moves `DEFICIENCIES_ISSUED →
    CLOSED`, at which point the survey's contribution to the site's weight ledger
    is back to where it was before issuance."

    Design: Difficulty/non_linear_state_machine/deficiency_correction_rejection_cycle_then_close_bubbles_inspection
    """
    _site, inspection, finding, _rejected, _resubmitted = (
        _finding_on_its_second_plan_of_correction()
    )

    closed = get_success_data(
        api_client.decide_correction(
            finding["id"],
            correction_decision_payload("ACCEPT", note="Attestations verified"),
            SURVEYOR_BETA,
        )
    )

    assert closed["status"] == "CLOSED"
    assert closed["correction_round"] == 2
    assert closed["closed_by_user_id"] == SURVEYOR_BETA_USER_ID
    read_back = read_inspection(inspection["id"])
    assert read_back["status"] == "CLOSED"
    assert read_back["issued_weight_total"] == 3.00


def test_closing_the_only_finding_empties_the_weight_ledger():
    """Acceptance subtracts the weight and returns the site to a perfect score.

    PRD 3.8: "**Acceptance** moves the finding `CORRECTION_SUBMITTED → CLOSED`,
    records `closed_by_user_id`, subtracts the finding's `weight` from the site's
    `open_deficiency_weight`, re-derives the posture and recomputes the site's
    `inspection_readiness_score`."

    Design: Difficulty/non_linear_state_machine/deficiency_correction_rejection_cycle_then_close_bubbles_inspection
    """
    site, _inspection, finding, _rejected, _resubmitted = (
        _finding_on_its_second_plan_of_correction()
    )

    get_success_data(
        api_client.decide_correction(
            finding["id"], correction_decision_payload("ACCEPT"), SURVEYOR_BETA,
        )
    )

    read_back = read_site(site["id"])
    assert read_back["open_deficiency_weight"] == 0.00
    assert read_back["oversight_posture"] == "OPEN"
    assert read_back["inspection_readiness_score"] == 100.00
    assert read_deficiency(finding["id"])["status"] == "CLOSED"


# ─── pt_investigation_reject_cycle_then_accept ──────────────────────


def _event_on_its_second_investigation():
    """A single failed shipment whose first investigation was rejected."""
    env = setup_site_with_director(
        certificate_overrides={"certificate_number": "45D2243008"},
        site_overrides={
            "name": "Pediatrics POCT",
            "department_code": "DEPT-170",
            "complexity_scope": "WAIVED",
        },
        director_overrides={"full_name": "Dr Nils Haas"},
    )
    env["enrollment"] = enroll_pt(env["site"]["id"], analyte="GLUCOSE")
    event = register_pt_event(env["enrollment"]["id"], 1, due_date="2026-08-10")
    env["graded"] = score_pt_event(event["id"], 60.00)
    env["event"] = event
    get_success_data(
        api_client.submit_pt_investigation(
            event["id"],
            pt_investigation_payload(
                root_cause="Control material stored above 8 C",
                corrective_action="Relocated controls to the monitored fridge",
            ),
            COORDINATOR,
        )
    )
    env["rejected"] = get_success_data(
        api_client.decide_pt_investigation(
            event["id"],
            pt_investigation_decision_payload(
                "REJECT", note="Root cause does not explain the analytic bias"
            ),
            env["director_headers"],
        )
    )
    env["resubmitted"] = get_success_data(
        api_client.submit_pt_investigation(
            event["id"],
            pt_investigation_payload(
                root_cause="Pipette out of calibration",
                corrective_action="Pipette recalibrated and operators requalified",
            ),
            COORDINATOR,
        )
    )
    return env


def test_one_failure_of_the_last_three_opens_an_investigation_without_locking():
    """A single miss takes the investigation branch, not the unsuccessful branch.

    PRD 3.7: "**Investigation open.** When the outcome is `FAIL` and
    `fail_count_last_three` is below 2, the event moves `PENDING →
    INVESTIGATION_OPEN` with `outcome` of `FAIL` and `graded_on` recorded. The
    site's `pt_unsuccessful_count` rises by one and its
    `inspection_readiness_score` is recomputed. **No instrument is locked and the
    enrolment stays `ENROLLED`** — this is a single miss that must be explained, not
    a loss of testing privileges."

    Design: Difficulty/non_linear_state_machine/pt_investigation_reject_cycle_then_accept_clears_unsuccessful_count
    """
    env = _event_on_its_second_investigation()

    assert env["graded"]["outcome"] == "FAIL"
    assert env["graded"]["status"] == "INVESTIGATION_OPEN"
    assert read_pt_enrollment(env["enrollment"]["id"])["status"] == "ENROLLED"


def test_a_rejected_investigation_reopens_the_loop_without_raising_the_round():
    """Rejection returns the event to INVESTIGATION_OPEN at round 1; refiling makes 2.

    PRD 3.7: "**Rejection** moves the event back to `INVESTIGATION_OPEN`, retaining
    the submitted `root_cause` and `corrective_action` for the audit trail, and the
    event re-enters the investigation loop — `INVESTIGATION_SUBMITTED →
    INVESTIGATION_OPEN → INVESTIGATION_SUBMITTED` may repeat as many times as the
    director requires."

    Design: Difficulty/non_linear_state_machine/pt_investigation_reject_cycle_then_accept_clears_unsuccessful_count
    """
    env = _event_on_its_second_investigation()

    assert env["rejected"]["status"] == "INVESTIGATION_OPEN"
    assert env["rejected"]["investigation_round"] == 1
    assert env["resubmitted"]["status"] == "INVESTIGATION_SUBMITTED"
    assert env["resubmitted"]["investigation_round"] == 2


def test_accepting_the_second_investigation_clears_the_unsuccessful_count():
    """Acceptance is terminal and returns the site to a perfect readiness score.

    PRD 3.7: "**Acceptance** moves it to `INVESTIGATION_ACCEPTED`, a terminal state;
    the site's `pt_unsuccessful_count` drops by one and its
    `inspection_readiness_score` is recomputed."

    Design: Difficulty/non_linear_state_machine/pt_investigation_reject_cycle_then_accept_clears_unsuccessful_count
    """
    env = _event_on_its_second_investigation()

    get_success_data(
        api_client.decide_pt_investigation(
            env["event"]["id"],
            pt_investigation_decision_payload(
                "ACCEPT", note="Calibration records verified"
            ),
            env["director_headers"],
        )
    )

    event = read_pt_event(env["event"]["id"])
    enrollment = read_pt_enrollment(env["enrollment"]["id"])
    site = read_site(env["site"]["id"])
    assert event["status"] == "INVESTIGATION_ACCEPTED"
    assert event["investigation_round"] == 2
    assert enrollment["status"] == "ENROLLED"
    assert enrollment["fail_count_last_three"] == 1
    assert enrollment["graded_event_count"] == 1
    assert site["pt_unsuccessful_count"] == 0
    assert site["inspection_readiness_score"] == 100.00
