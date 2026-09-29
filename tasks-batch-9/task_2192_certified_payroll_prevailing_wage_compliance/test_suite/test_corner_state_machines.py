"""State-machine corners: valid moves, guards, terminal states and cascades."""
from test_helpers import (
    ApiErrorId,
    build_active_determination,
    build_assignment,
    build_contractor,
    build_determination,
    build_interview,
    build_portal,
    build_project,
    build_rate,
    build_submission,
    compliant_paid_line,
    get_success_data,
    setup_accepted_submission,
    setup_env,
    setup_proposed_contractor_with_invited_tier,
    validate_error,
    validate_success,
)

WEEK = "2026-08-01T00:00:00.000Z"
ONE_RATE = [{"fringe_hourly_rate_cents": 2000}]


def test_a_draft_determination_with_one_rate_row_activates(api, portal_admin_headers):
    """DRAFT to ACTIVE, rate_count 1, no expiry, and version 3 after create-rate-activate.

    PRD 3.1: "Activation by a `PortalAdmin` moves a determination `DRAFT → ACTIVE`. The
    determination must currently be `DRAFT` and must carry at least one rate row". PRD 3.1:
    "Each rate row added advances the owning determination's `rate_count` by one and its
    `version` by one." PRD 3.1: "When activation succeeds it sets `status` to `ACTIVE` and
    advances the determination's `version` by one."

    Design: Corner/state_machines/activate_determination_moves_draft_to_active
    """
    determination = build_determination(api, effective_date="2026-01-01T00:00:00.000Z")
    build_rate(api, determination["id"])
    resp = api.activate_wage_determination(determination["id"], portal_admin_headers, {})
    activated = get_success_data(resp)
    validate_success(resp, expected_status=200)
    assert activated["status"] == "ACTIVE"
    assert activated["rate_count"] == 1
    assert activated["expiry_date"] is None
    assert activated["version"] == 3


def test_a_determination_with_an_empty_schedule_cannot_activate(api, portal_admin_headers):
    """rate_count 0 blocks activation independently of the from-state, and the row stays DRAFT.

    PRD 3.1: "The determination must currently be `DRAFT` and must carry at least one rate row;
    a determination whose `rate_count` is still 0 cannot be activated, and both failures report
    `ERR_INVALID_DETERMINATION_STATE`."

    Design: Corner/state_machines/activate_determination_without_rate_rows_is_refused
    """
    determination = build_determination(api, effective_date="2026-01-01T00:00:00.000Z")
    resp = api.activate_wage_determination(determination["id"], portal_admin_headers, {})
    validate_error(resp, ApiErrorId.ERR_INVALID_DETERMINATION_STATE.value, expected_status=409)

    unchanged = get_success_data(
        api.get_wage_determination(determination["id"], portal_admin_headers)
    )
    assert unchanged["status"] == "DRAFT"
    assert unchanged["rate_count"] == 0


def test_a_supersede_stamps_the_predecessor_and_repoints_the_awarded_project(
    api, portal_admin_headers
):
    """One activation writes the predecessor's expiry, its successor link and the project's FK.

    PRD 3.1: "the same act drives that predecessor `ACTIVE → SUPERSEDED`: the predecessor's
    `status` becomes `SUPERSEDED`, its `superseded_by_id` is set to the successor's `id`, its
    `expiry_date` is overwritten with the successor's `effective_date`, and its `version`
    advances by one." PRD 3.1: "every project whose `wage_determination_id` points at the
    superseded determination and whose `status` is still `AWARDED` is re-pointed to the value of
    `superseded_by_id`, with that project's `version` advancing by one".

    Design: Corner/state_machines/superseding_activation_stamps_predecessor_and_repoints_awarded_project
    """
    portal = build_portal(api)
    wd_a, _rates = build_active_determination(
        api, rates=ONE_RATE, effective_date="2026-01-01T00:00:00.000Z"
    )
    project = build_project(api, wd_a["id"], portal["id"])
    assert project["status"] == "AWARDED"

    wd_b = build_determination(api, effective_date="2026-06-01T00:00:00.000Z")
    build_rate(api, wd_b["id"], base_hourly_rate_cents=5200, fringe_hourly_rate_cents=2100)
    resp = api.activate_wage_determination(
        wd_b["id"], portal_admin_headers, {"supersedes_determination_id": wd_a["id"]}
    )
    successor = get_success_data(resp)
    validate_success(resp, expected_status=200)
    assert successor["status"] == "ACTIVE"

    predecessor = get_success_data(api.get_wage_determination(wd_a["id"], portal_admin_headers))
    assert predecessor["status"] == "SUPERSEDED"
    assert predecessor["expiry_date"] == "2026-06-01T00:00:00.000Z"
    assert predecessor["superseded_by_id"] == wd_b["id"]

    repointed = get_success_data(api.get_project(project["id"], portal_admin_headers))
    assert repointed["wage_determination_id"] == wd_b["id"]
    assert repointed["status"] == "AWARDED"


def test_accepting_a_draft_payroll_is_refused(api, officer_headers, portal_admin_headers):
    """ACCEPT is declared only out of UNDER_REVIEW, so a DRAFT filing answers 409 unchanged.

    PRD 3.8: "From `UNDER_REVIEW` the officer has two exits. Acceptance advances the axis
    `UNDER_REVIEW → ACCEPTED` and requires no payload". PRD 2.8 rung 8: "State legality: the
    target resource must currently sit in a state the requested transition declares as a
    from-state. The identifier depends on the resource: `ERR_INVALID_SUBMISSION_STATE`".

    Design: Corner/state_machines/accept_a_draft_payroll_submission_is_rejected
    """
    env = setup_env(api, rates=ONE_RATE)
    submission = build_submission(api, env, week_ending_date=WEEK)
    resp = api.accept_payroll_submission(submission["id"], officer_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_SUBMISSION_STATE.value, expected_status=409)

    unchanged = get_success_data(api.get_payroll_submission(submission["id"], portal_admin_headers))
    assert unchanged["workflow_status"] == "DRAFT"
    assert unchanged["compliance_status"] == "UNVERIFIED"
    assert unchanged["accepted_by_user_id"] is None
    assignment = get_success_data(
        api.get_contract_assignment(env["assignment"]["id"], portal_admin_headers)
    )
    assert float(assignment["cumulative_certified_hours"]) == 0.00


def test_a_new_tier_is_born_invited_with_zeroed_ledgers(api):
    """Creation alone never implies participation: the prime tier starts INVITED at tier 0.

    PRD 3.4: "A newly created tier sits at `status` `INVITED` with `version` 1 and all its
    ledgers at zero." PRD 3.4: "The prime contractor's tier omits `upper_tier_assignment_id`
    entirely and receives a computed `tier` of 0".

    Design: Corner/state_machines/new_contract_assignment_starts_in_invited
    """
    portal = build_portal(api)
    determination, _rates = build_active_determination(api, rates=ONE_RATE)
    contractor = build_contractor(api, legal_name="Acme Electric")
    project = build_project(api, determination["id"], portal["id"])
    tier = build_assignment(api, project["id"], contractor["id"])
    assert tier["status"] == "INVITED"
    assert tier["tier"] == 0
    assert float(tier["cumulative_certified_hours"]) == 0.00
    assert tier["cumulative_restitution_cents"] == 0
    assert tier["open_finding_count"] == 0
    assert tier["version"] == 1


def test_a_superseded_determination_can_never_be_activated_again(api, portal_admin_headers):
    """SUPERSEDED is terminal, and the refusal leaves the retired row's stamps untouched.

    PRD 3.1: "`SUPERSEDED` is terminal — a determination never leaves it." PRD 3.1: "The
    determination must currently be `DRAFT` ... and both failures report
    `ERR_INVALID_DETERMINATION_STATE`."

    Design: Corner/state_machines/superseded_determination_cannot_be_activated_again
    """
    wd_a, _rates = build_active_determination(
        api, rates=ONE_RATE, effective_date="2026-01-01T00:00:00.000Z"
    )
    wd_b = build_determination(api, effective_date="2026-06-01T00:00:00.000Z")
    build_rate(api, wd_b["id"])
    get_success_data(
        api.activate_wage_determination(
            wd_b["id"], portal_admin_headers, {"supersedes_determination_id": wd_a["id"]}
        )
    )

    resp = api.activate_wage_determination(wd_a["id"], portal_admin_headers, {})
    validate_error(resp, ApiErrorId.ERR_INVALID_DETERMINATION_STATE.value, expected_status=409)

    retired = get_success_data(api.get_wage_determination(wd_a["id"], portal_admin_headers))
    assert retired["status"] == "SUPERSEDED"
    assert retired["superseded_by_id"] == wd_b["id"]
    successor = get_success_data(api.get_wage_determination(wd_b["id"], portal_admin_headers))
    assert successor["status"] == "ACTIVE"


def test_activating_an_already_active_tier_a_second_time_is_refused(api, portal_admin_headers):
    """The endpoint is not idempotent: the second call finds ACTIVE and does not move version.

    PRD 3.4: "Activating a tier is a `PortalAdmin` action that moves it `INVITED → ACTIVE`. The
    tier must currently be `INVITED`". PRD 3.4: "a request against a tier that is not
    `SUSPENDED` fails with `ERR_INVALID_ASSIGNMENT_STATE`."

    Design: Corner/state_machines/activating_an_already_active_tier_twice_is_refused
    """
    env = setup_env(api, rates=ONE_RATE, activate_project=False)
    assert env["assignment"]["status"] == "ACTIVE"
    assert env["assignment"]["version"] == 2

    resp = api.activate_contract_assignment(env["assignment"]["id"], portal_admin_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_ASSIGNMENT_STATE.value, expected_status=409)

    unchanged = get_success_data(
        api.get_contract_assignment(env["assignment"]["id"], portal_admin_headers)
    )
    assert unchanged["status"] == "ACTIVE"
    assert unchanged["version"] == 2


def test_a_debarment_proposal_can_be_restored_to_clear(api, cruz_headers, portal_admin_headers):
    """PROPOSED to CLEAR is a legal round trip and it does not rewrite the risk score.

    PRD 3.11: "Supplying a `to_status` and a `reason`, the auditor either debars a contractor
    that is currently `PROPOSED`, moving it `PROPOSED → DEBARRED`, or restores that contractor
    to `CLEAR`. ... A `to_status` of `CLEAR` performs the restoration, which is the same
    `PROPOSED → CLEAR` transition the risk score can trigger on its own." PRD 3.11: "That
    `CLEAR → PROPOSED → CLEAR` cycle may be traversed repeatedly by the same firm." PRD 3.11:
    "Debarment risk is the running summary of a contractor's exposure, recomputed whenever a
    finding is created, whenever a finding changes status, whenever a restitution payment is
    disbursed or reversed, and whenever the logical clock is moved".

    Design: Corner/state_machines/debarment_proposal_can_be_withdrawn_back_to_clear
    """
    state = setup_proposed_contractor_with_invited_tier(api)
    assert state["contractor"]["debarment_status"] == "PROPOSED"
    assert state["contractor"]["debarment_risk_score"] == 70

    resp = api.decide_debarment(
        state["contractor"]["id"],
        {"to_status": "CLEAR", "reason": "Referral withdrawn; records reconciled."},
        cruz_headers,
    )
    restored = get_success_data(resp)
    validate_success(resp, expected_status=200)
    assert restored["debarment_status"] == "CLEAR"

    read_back = get_success_data(api.get_contractor(state["contractor"]["id"], portal_admin_headers))
    assert read_back["debarment_status"] == "CLEAR"
    # The decision is not one of the declared re-scoring triggers, so the score is untouched.
    assert read_back["debarment_risk_score"] == 70


def test_a_project_cannot_go_active_while_its_only_tier_is_invited(api, portal_admin_headers):
    """The AWARDED to ACTIVE guard reads the tier's state, not the project's own fields.

    PRD 3.4: "Once at least one tier-0 assignment on the project is `ACTIVE`, a `PortalAdmin`
    may advance the project `AWARDED → ACTIVE` by supplying a `to_status` of `ACTIVE`. An
    advance attempted while no prime tier is active, or from any status other than `AWARDED`, is
    refused with `ERR_INVALID_PROJECT_STATUS_TRANSITION`."

    Design: Corner/state_machines/project_cannot_go_active_while_the_prime_tier_is_only_invited
    """
    portal = build_portal(api)
    determination, _rates = build_active_determination(api, rates=ONE_RATE)
    contractor = build_contractor(api, legal_name="Acme Electric")
    project = build_project(api, determination["id"], portal["id"])
    tier = build_assignment(api, project["id"], contractor["id"])

    resp = api.set_project_status(project["id"], {"to_status": "ACTIVE"}, portal_admin_headers)
    validate_error(
        resp, ApiErrorId.ERR_INVALID_PROJECT_STATUS_TRANSITION.value, expected_status=409
    )
    assert get_success_data(api.get_project(project["id"], portal_admin_headers))["status"] == (
        "AWARDED"
    )
    assert get_success_data(
        api.get_contract_assignment(tier["id"], portal_admin_headers)
    )["status"] == "INVITED"


def _accepted_week_with_scheduled_interview(api):
    """An ACCEPTED 40h week at 5000+2000 and a SCHEDULED interview inside its covered week."""
    env, submission, rows = setup_accepted_submission(
        api,
        lines=[compliant_paid_line(fringe_cash_paid_cents=2000)],
        week_ending_date=WEEK,
        rates=ONE_RATE,
    )
    interview = build_interview(
        api, env, rows[0]["worker_id"],
        "2026-07-29T15:00:00.000Z", "2026-07-29T17:00:00.000Z",
    )
    assert interview["status"] == "SCHEDULED"
    return env, submission, rows[0]["worker_id"], interview


def test_a_discrepant_interview_mints_a_misclassification_finding(api, cruz_headers):
    """One conduct call writes the interview, the worker, a new finding and the payroll's axis.

    PRD 3.9: "It writes the same three observation fields, moves the interview `SCHEDULED →
    CONDUCTED_DISCREPANT`, advances the worker's `interview_count` by one, and advances the
    interview's `version` by one — and then does strictly more. It auto-creates a finding whose
    `project_id` is the interview's project, whose `payroll_submission_id` is the compared
    submission, whose `worker_id` is the interviewed worker, whose `source_interview_id` is this
    interview, whose `finding_type` is `MISCLASSIFICATION`, whose `severity` is `MAJOR`, whose
    `restitution_required_cents` is 0, and whose `status` is `OPEN`."

    Design: Corner/state_machines/discrepant_interview_auto_raises_a_misclassification_finding
    """
    env, submission, worker_id, interview = _accepted_week_with_scheduled_interview(api)
    resp = api.conduct_interview(
        interview["id"],
        {"observed_classification_code": "ELEC-INSIDE-JW", "observed_hourly_rate_cents": 6000},
        cruz_headers,
    )
    conducted = get_success_data(resp)
    validate_success(resp, expected_status=200)
    assert conducted["status"] == "CONDUCTED_DISCREPANT"
    assert conducted["compared_submission_id"] == submission["id"]

    assert get_success_data(api.get_worker(worker_id, cruz_headers))["interview_count"] == 1

    findings = get_success_data(
        api.list_findings(cruz_headers, params={"payroll_submission_id": submission["id"]})
    )
    assert len(findings) == 1
    finding = findings[0]
    assert finding["finding_type"] == "MISCLASSIFICATION"
    assert finding["severity"] == "MAJOR"
    assert finding["restitution_required_cents"] == 0
    assert finding["status"] == "OPEN"
    assert finding["source_interview_id"] == interview["id"]
    assert finding["worker_id"] == worker_id

    cited = get_success_data(api.get_payroll_submission(submission["id"], cruz_headers))
    assert cited["compliance_status"] == "DEFICIENT"
    assert cited["workflow_status"] == "ACCEPTED"
    project = get_success_data(api.get_project(env["project"]["id"], cruz_headers))
    assert project["open_finding_count"] == 1
    assert project["posture"] == "OPEN"
    contractor = get_success_data(api.get_contractor(env["contractor"]["id"], cruz_headers))
    assert contractor["debarment_risk_score"] == 15
    assert contractor["debarment_status"] == "CLEAR"


def test_a_matched_interview_raises_nothing_and_leaves_the_axis_alone(api, cruz_headers):
    """The same endpoint skips the whole finding cascade when the observation agrees.

    PRD 3.9: "The **matched** branch is taken when the compared submission carries a payroll
    line for the interviewed worker whose `classification_code` equals the
    `observed_classification_code` and whose `base_rate_paid_cents` is greater than or equal to
    the `observed_hourly_rate_cents`. It writes `observed_classification_code`,
    `observed_hourly_rate_cents` and `compared_submission_id`, moves the interview `SCHEDULED →
    CONDUCTED_MATCHED`, advances the worker's `interview_count` by one, and advances the
    interview's `version` by one. It raises no finding and leaves the compared submission's
    compliance axis exactly where it was."

    Design: Corner/state_machines/matched_interview_raises_no_finding_and_leaves_compliance_alone
    """
    env, submission, worker_id, interview = _accepted_week_with_scheduled_interview(api)
    resp = api.conduct_interview(
        interview["id"],
        {"observed_classification_code": "ELEC-INSIDE-JW", "observed_hourly_rate_cents": 5000},
        cruz_headers,
    )
    conducted = get_success_data(resp)
    validate_success(resp, expected_status=200)
    assert conducted["status"] == "CONDUCTED_MATCHED"
    assert conducted["compared_submission_id"] == submission["id"]

    assert get_success_data(api.get_worker(worker_id, cruz_headers))["interview_count"] == 1

    listed = api.list_findings(cruz_headers, params={"payroll_submission_id": submission["id"]})
    assert get_success_data(listed) == []
    assert listed.json()["meta"]["total_count"] == 0

    cited = get_success_data(api.get_payroll_submission(submission["id"], cruz_headers))
    assert cited["compliance_status"] == "COMPLIANT"
    project = get_success_data(api.get_project(env["project"]["id"], cruz_headers))
    assert project["open_finding_count"] == 0
    assert project["posture"] == "OPEN"
    contractor = get_success_data(api.get_contractor(env["contractor"]["id"], cruz_headers))
    assert contractor["debarment_risk_score"] == 0
