"""Declared transitions, refused transitions and terminal states.

Every record in the programme that has a lifecycle is walked here: the plan that
activates once, the candidate that can be deferred and re-admitted but never
re-decided after withdrawal, the engagement whose two axes start together and end
together, the document that is signed exactly once, the target that is excluded
for good, the tester whose clearance cycles, the grant that is provisioned once
and settled once, and the alert whose branch is chosen by the clock.
"""

from test_helpers import (
    advance_clock,
    assert_engagement_axes,
    assert_error_id,
    assert_exact_int,
    assert_hour_ledger,
    assert_instant_equals,
    assert_page,
    assert_score,
    assert_severity,
    build_scenario,
    compliance_officer_headers,
    created_data,
    factories,
    find_alert_for_finding,
    report_finding,
    success_data,
)
from test_helpers.api_errors import (
    ERR_ALERT_ALREADY_ACKNOWLEDGED,
    ERR_ASSIGNMENT_STATE_INVALID,
    ERR_ENGAGEMENT_ALREADY_TERMINATED,
    ERR_ENGAGEMENT_NOT_SUSPENDED,
    ERR_INVALID_EXECUTION_TRANSITION,
    ERR_PLAN_NOT_DRAFT,
    ERR_ROE_ALREADY_SIGNED,
    ERR_ROE_NOT_MODIFIABLE,
    ERR_SCOPE_ITEM_NOT_PENDING,
    ERR_TARGET_NOT_ACTIVE,
    ERR_TESTER_STATE_INVALID,
)
from test_helpers.constants import (
    T_FIELDWORK_DAY,
    T_PROGRAMME_OPEN,
    WINDOW_START,
)
from test_helpers.test_users import CO_ALT_USER_ID, CO_USER_ID, PM_USER_ID

WITHDRAWAL_NOTE = "Asset is being decommissioned this quarter"
DEFERRAL_NOTE = "Waiting for the vendor patch window"
READMISSION_NOTE = "Patch window confirmed"
EXCLUSION_REASON = "Owner pulled the host from the test population"
TERMINATION_REASON = "Legal counsel withdrew the authorization"
PAUSE_REASON = "Production incident on the payments cluster"
RESUME_NOTE = "Incident closed, testing may continue"
PORTAL_EXCLUSION_REASON = "Partner declined the portal test this cycle"
SIGN_NOTE = "Authorized for FY2026 window"
T_NEXT_DAY = "2026-09-02T00:00:00Z"
T_DAY_THREE = "2026-09-03T00:00:00Z"


def _propose_candidate(client, scenario):
    """Propose the scenario's asset into its DRAFT plan without deciding it."""
    return created_data(
        client.create_scope_item(
            factories.scope_item_payload(
                scenario["plan_id"], scenario["asset_id"], scenario["plan"]["version"]
            )
        )
    )


def _decide(client, scope_item_id, decision, note, headers=None):
    """Record a scope decision and return the raw response for either outcome."""
    return client.decide_scope_item(
        scope_item_id, factories.decision_payload(decision, note=note), headers=headers
    )


class TestPlanAndCandidateLifecycles:
    """The plan activates once, and a candidate's decisions are not replayable."""

    def test_activating_an_active_plan_is_refused_and_does_not_re_version_it(self, client):
        """Activation is a one-way DRAFT to ACTIVE move, not an idempotent refresh.

        PRD: "Activating the plan moves it `DRAFT` → `ACTIVE` and is a `ProgramManager` action."
        PRD: "The plan must be `DRAFT` (`ERR_PLAN_NOT_DRAFT`, 409) — for scope-item creation, scope decisions, prioritization-mode switching and plan activation."
        PRD: "It is the value clients echo back on the writes described in §2.7, and the specification is explicit about which operations advance it: proposing a scope candidate, deciding a scope candidate, switching a plan's prioritization mode, activating a plan and creating an engagement all bump the plan's `version`; starting, completing, reporting or closing fieldwork, emergency-stopping, resuming, signing the rules of engagement, filing a finding, requesting an assignment and provisioning or revoking access all bump the engagement's `version`."

        Design: Corner/state_machines/activating_an_already_active_plan_is_rejected
        """
        scenario = build_scenario(client, stage="plan_active")
        activated = scenario["plan"]
        assert activated["status"] == "ACTIVE", (
            f"status: expected ACTIVE, got {activated['status']}"
        )
        assert_score(activated["coverage_score"], 100.00, "coverage_score")
        assert_exact_int(activated["version"], 4, "plan version after activation")

        response = client.activate_test_plan(scenario["plan_id"])

        assert_error_id(response, ERR_PLAN_NOT_DRAFT)
        assert response.status_code == 409, (
            f"expected HTTP 409 for a second activation, got {response.status_code}"
        )
        plan = success_data(client.get_test_plan(scenario["plan_id"]))
        assert plan["status"] == "ACTIVE"
        assert_exact_int(plan["version"], 4, "plan version after the refusal")

    def test_a_withdrawn_candidate_accepts_no_further_decision(self, client):
        """WITHDRAWN is terminal, and the candidate rule answers before the plan rule.

        PRD: "Withdrawing moves a candidate at `PROPOSED` or `DEFERRED` to `WITHDRAWN`, sets its `priority_rank` to null, and likewise triggers a renumbering of the remainder."
        PRD: "`WITHDRAWN` is terminal: a withdrawn candidate accepts no further decision."
        PRD: "Every decision requires the plan to still be at `DRAFT`, and requires the candidate to be at `PROPOSED` or `DEFERRED`; a consumed or withdrawn candidate is beyond decision."

        Design: Corner/state_machines/decision_on_a_withdrawn_scope_item_is_rejected
        """
        scenario = build_scenario(client, stage="plan")
        candidate = _propose_candidate(client, scenario)
        withdrawn = success_data(
            _decide(client, candidate["id"], "WITHDRAW", WITHDRAWAL_NOTE)
        )
        assert withdrawn["status"] == "WITHDRAWN", (
            f"status: expected WITHDRAWN, got {withdrawn['status']}"
        )
        assert withdrawn["priority_rank"] is None, (
            f"priority_rank: expected null once withdrawn, got {withdrawn['priority_rank']}"
        )

        response = _decide(
            client,
            candidate["id"],
            "APPROVE",
            "Reinstating",
            headers=compliance_officer_headers(),
        )

        assert_error_id(response, ERR_SCOPE_ITEM_NOT_PENDING)
        assert response.status_code == 409, (
            f"expected HTTP 409 for a decided candidate, got {response.status_code}"
        )
        assert (
            success_data(client.get_scope_item(candidate["id"]))["status"] == "WITHDRAWN"
        )
        assert success_data(client.get_test_plan(scenario["plan_id"]))["status"] == "DRAFT", (
            "the plan is still DRAFT, so the plan-status rule is not what refused"
        )

    def test_a_deferred_candidate_can_be_readmitted_and_regains_its_rank(self, client):
        """DEFERRED is a way station: the score survives and the rank comes back.

        PRD: "Deferring moves a candidate `PROPOSED` → `DEFERRED`, records the supplied `note` in `decision_note`, and drops the candidate out of the ranked population — which means the remaining proposed and approved candidates are renumbered so their ranks stay contiguous."
        PRD: "Approving moves a candidate `PROPOSED` → `APPROVED`, or `DEFERRED` → `APPROVED` for a candidate that was previously set aside — the deferral loop deliberately allows a candidate to be re-admitted without recreating the row."
        PRD: "Approval then recomputes the plan's coverage and advances the plan's `version`."

        Design: Corner/state_machines/deferred_scope_item_can_still_be_approved_later
        """
        scenario = build_scenario(client, stage="plan")
        candidate = _propose_candidate(client, scenario)
        assert_exact_int(candidate["priority_rank"], 1, "priority_rank at proposal")

        deferred = success_data(_decide(client, candidate["id"], "DEFER", DEFERRAL_NOTE))
        readmitted = success_data(
            _decide(
                client,
                candidate["id"],
                "APPROVE",
                READMISSION_NOTE,
                headers=compliance_officer_headers(),
            )
        )

        assert deferred["status"] == "DEFERRED", (
            f"status: expected DEFERRED, got {deferred['status']}"
        )
        assert deferred["priority_rank"] is None, (
            f"priority_rank: expected null while deferred, got {deferred['priority_rank']}"
        )
        assert deferred["decision_note"] == DEFERRAL_NOTE, (
            f"decision_note: expected the deferral note, got {deferred['decision_note']}"
        )
        assert readmitted["status"] == "APPROVED", (
            f"status: expected APPROVED, got {readmitted['status']}"
        )
        assert_exact_int(readmitted["priority_rank"], 1, "priority_rank after readmission")
        assert_score(readmitted["priority_score"], 89.80, "priority_score")
        plan = success_data(client.get_test_plan(scenario["plan_id"]))
        assert_exact_int(plan["version"], 4, "plan version after two decisions")
        assert_score(plan["coverage_score"], 100.00, "coverage_score")


class TestEngagementOpeningAndAuthorization:
    """The two axes open together, and each guard speaks for its own axis."""

    def test_a_chartered_engagement_opens_on_both_axes_and_consumes_its_candidate(
        self, client
    ):
        """One response carries both initial states, an empty ledger and a consumed candidate.

        PRD: "The new engagement opens with `execution_state` at `PLANNED` and `authorization_state` at `ROE_PENDING`, with a null `suspension_reason` and with both `provisional_assurance_score` and `final_assurance_score` null."
        PRD: "Its hour ledger opens with `hours_reserved` at 0, `hours_consumed` at 0 and `hours_available` equal to the full `hours_allocated`."
        PRD: "The scope item moves `APPROVED` → `CONSUMED`, which both records that the plan's intent has been acted on and releases the plan-and-asset uniqueness slot so a follow-up candidate for the same asset may be proposed later."

        Design: Corner/state_machines/new_engagement_starts_planned_and_roe_pending_and_consumes_its_scope_item
        """
        scenario = build_scenario(client, stage="plan_active")

        engagement = created_data(
            client.create_engagement(
                factories.engagement_payload(scenario["plan_id"], scenario["scope_item_id"])
            )
        )

        assert_engagement_axes(
            engagement, execution_state="PLANNED", authorization_state="ROE_PENDING"
        )
        assert_hour_ledger(engagement, allocated=80, reserved=0, consumed=0, available=80)
        assert engagement["suspension_reason"] is None, (
            f"suspension_reason: expected null, got {engagement['suspension_reason']}"
        )
        assert engagement["provisional_assurance_score"] is None, (
            "provisional_assurance_score is stamped only when fieldwork completes"
        )
        assert engagement["final_assurance_score"] is None, (
            "final_assurance_score is stamped only when the engagement ends"
        )
        candidate = success_data(client.get_scope_item(scenario["scope_item_id"]))
        assert candidate["status"] == "CONSUMED", (
            f"status: expected CONSUMED, got {candidate['status']}"
        )
        assert candidate["priority_rank"] is None, (
            f"priority_rank: expected null once consumed, got {candidate['priority_rank']}"
        )

    def test_completing_fieldwork_that_never_started_is_a_transition_error(self, client):
        """COMPLETE_FIELDWORK is declared only from EXECUTING, so the transition rule answers.

        PRD: "An execution action that is not the one declared for the engagement's current execution state — closing something that is still executing, starting something already reported — is refused with `ERR_INVALID_EXECUTION_TRANSITION`."
        PRD: "Completing fieldwork moves the engagement `EXECUTING` → `FIELDWORK_COMPLETE` and may be issued by a `ProgramManager` or a `Tester`; it is blocked while any alert of the engagement is still `RAISED`."

        Design: Corner/state_machines/complete_fieldwork_before_start_is_rejected
        """
        scenario = build_scenario(client, stage="engagement")

        response = client.drive_execution(scenario["engagement_id"], "COMPLETE_FIELDWORK")

        assert_error_id(response, ERR_INVALID_EXECUTION_TRANSITION)
        assert response.status_code == 409, (
            f"expected HTTP 409 for an undeclared action, got {response.status_code}"
        )
        engagement = success_data(client.get_engagement(scenario["engagement_id"]))
        assert_engagement_axes(
            engagement, execution_state="PLANNED", authorization_state="ROE_PENDING"
        )
        assert engagement["provisional_assurance_score"] is None, (
            "a refused completion must not stamp an assurance score"
        )

    def test_the_document_is_counter_signed_exactly_once(self, client):
        """A second officer cannot overwrite the first signature.

        PRD: "The document must still be at `DRAFT`, or the signature is refused with `ERR_ROE_ALREADY_SIGNED`."
        PRD: "On success the document moves `DRAFT` → `SIGNED`, `signed_by_user_id` is stamped from `X-User-ID` and `signed_at` from the current instant, and — the cross-record effect that matters most — the engagement's authorization axis moves `ROE_PENDING` → `AUTHORIZED`."
        PRD: "The server stamps `drafted_by_user_id` from `X-User-ID`, opens the document at `DRAFT` status, and sets `active_target_count` to 0."

        Design: Corner/state_machines/signing_an_already_signed_document_is_rejected
        """
        scenario = build_scenario(client, stage="roe_signed")
        signed = scenario["roe"]
        assert signed["status"] == "SIGNED", f"status: expected SIGNED, got {signed['status']}"
        assert signed["drafted_by_user_id"] == PM_USER_ID
        assert signed["signed_by_user_id"] == CO_USER_ID
        assert_instant_equals(signed["signed_at"], T_PROGRAMME_OPEN, "signed_at")
        assert_exact_int(signed["active_target_count"], 1, "active_target_count")

        response = client.sign_rules_of_engagement(
            scenario["roe_id"],
            signature_note="Second signature",
            headers=compliance_officer_headers(CO_ALT_USER_ID),
        )

        assert_error_id(response, ERR_ROE_ALREADY_SIGNED)
        assert response.status_code == 409, (
            f"expected HTTP 409 for a second signature, got {response.status_code}"
        )
        document = success_data(client.get_rules_of_engagement(scenario["roe_id"]))
        assert document["signed_by_user_id"] == CO_USER_ID, (
            f"signed_by_user_id: expected {CO_USER_ID}, got {document['signed_by_user_id']}"
        )
        assert_instant_equals(document["signed_at"], T_PROGRAMME_OPEN, "signed_at")

    def test_an_excluded_target_cannot_be_excluded_again(self, client):
        """EXCLUDED is terminal, and the counter does not fall below zero.

        PRD: "Exclusion moves the target `ACTIVE` → `EXCLUDED`, stamps the supplied text into `exclusion_reason`, decrements the document's `active_target_count`, and advances the document's `version`."
        PRD: "`EXCLUDED` is terminal — an excluded target is never revived, not even by resuming a suspended engagement."
        PRD: "Each target records `cooldown_hours`, resolved from the asset's class: an `APPLICATION` asset needs no buffer at all, a `CLOUD` asset needs half a day of quiet on each side, and a `NETWORK` asset needs a full day on each side."

        Design: Corner/state_machines/excluding_an_already_excluded_target_is_rejected
        """
        scenario = build_scenario(client, stage="roe_signed", roe={"exclusions": ["/admin/*"]})
        assert scenario["target"]["state"] == "ACTIVE", (
            f"state: expected ACTIVE, got {scenario['target']['state']}"
        )
        assert_exact_int(scenario["target"]["cooldown_hours"], 0, "cooldown_hours")

        excluded = success_data(
            client.exclude_authorized_target(
                scenario["target_id"],
                EXCLUSION_REASON,
                headers=compliance_officer_headers(),
            )
        )
        assert excluded["state"] == "EXCLUDED", (
            f"state: expected EXCLUDED, got {excluded['state']}"
        )
        assert excluded["exclusion_reason"] == EXCLUSION_REASON
        after_first = success_data(client.get_rules_of_engagement(scenario["roe_id"]))
        assert_exact_int(after_first["active_target_count"], 0, "active_target_count")

        response = client.exclude_authorized_target(scenario["target_id"], "Second attempt")

        assert_error_id(response, ERR_TARGET_NOT_ACTIVE)
        assert response.status_code == 409, (
            f"expected HTTP 409 for a second exclusion, got {response.status_code}"
        )
        document = success_data(client.get_rules_of_engagement(scenario["roe_id"]))
        assert_exact_int(document["active_target_count"], 0, "active_target_count")
        target = success_data(client.get_authorized_target(scenario["target_id"]))
        assert target["exclusion_reason"] == EXCLUSION_REASON, (
            "the refused exclusion must not overwrite the recorded reason"
        )


class TestStoppingAndResuming:
    """PAUSE is a cycle, TERMINATE is a lockdown, and neither is idempotent."""

    def test_resuming_an_engagement_that_was_never_paused_is_refused(self, client):
        """The resume guard reads the authorization axis, and a refusal is not a write.

        PRD: "Resumption requires the authorization axis to be `SUSPENDED` and the execution axis not to be `CLOSED` (`ERR_ENGAGEMENT_NOT_SUSPENDED`, 409)."
        PRD: "It requires the authorization axis to be `SUSPENDED` and the execution axis not to be `CLOSED`, and anything else is refused with `ERR_ENGAGEMENT_NOT_SUSPENDED`."

        Design: Corner/state_machines/resuming_an_engagement_that_was_never_suspended_is_rejected
        """
        scenario = build_scenario(client, stage="roe_signed")
        before = success_data(client.get_engagement(scenario["engagement_id"]))
        assert_engagement_axes(before, authorization_state="AUTHORIZED")
        assert_exact_int(before["version"], 2, "version")

        response = client.resume_engagement(
            scenario["engagement_id"], resume_note="Nothing to resume"
        )

        assert_error_id(response, ERR_ENGAGEMENT_NOT_SUSPENDED)
        assert response.status_code == 409, (
            f"expected HTTP 409 for an unpaused engagement, got {response.status_code}"
        )
        after = success_data(client.get_engagement(scenario["engagement_id"]))
        assert_engagement_axes(after, authorization_state="AUTHORIZED")
        assert_exact_int(after["version"], before["version"], "version")

    def test_termination_closes_both_axes_and_refuses_a_second_stop(self, client):
        """One call locks the authorization axis, the execution axis, the document and the plan.

        PRD: "It records the `reason` in `suspension_reason`, moves the authorization axis to `TERMINATED`, moves the rules-of-engagement document to `REVOKED`, and moves **every** target of that document to `SUSPENDED` regardless of which ones were active."
        PRD: "It then forces the execution axis to `CLOSED` and stamps `final_assurance_score`, and it evaluates the plan bubble-up exactly as an ordinary close would."
        PRD: "An emergency stop requires the authorization axis to be `AUTHORIZED` or `SUSPENDED` (`ERR_ENGAGEMENT_ALREADY_TERMINATED`, 409); an already-terminated engagement cannot be stopped again."
        PRD: "There is no operation that closes a plan directly: the plan moves `ACTIVE` → `CLOSED` when the bubble-up condition holds — the plan has at least one engagement, and every engagement of the plan has reached `CLOSED` on its execution axis."

        Design: Corner/state_machines/terminated_engagement_closes_both_axes_and_refuses_a_second_stop
        """
        scenario = build_scenario(client, stage="roe_signed")

        stopped = success_data(
            client.emergency_stop(
                scenario["engagement_id"],
                "TERMINATE",
                TERMINATION_REASON,
                headers=compliance_officer_headers(),
            )
        )

        assert_engagement_axes(
            stopped, execution_state="CLOSED", authorization_state="TERMINATED"
        )
        assert stopped["suspension_reason"] == TERMINATION_REASON, (
            f"suspension_reason: expected the stop reason, got {stopped['suspension_reason']}"
        )
        assert_score(stopped["final_assurance_score"], 100.00, "final_assurance_score")
        assert stopped["provisional_assurance_score"] is None, (
            "the provisional variant is stamped only by COMPLETE_FIELDWORK"
        )
        assert_exact_int(stopped["version"], 3, "version")
        document = success_data(client.get_rules_of_engagement(scenario["roe_id"]))
        assert document["status"] == "REVOKED", (
            f"document status: expected REVOKED, got {document['status']}"
        )
        assert_exact_int(document["active_target_count"], 0, "active_target_count")
        target = success_data(client.get_authorized_target(scenario["target_id"]))
        assert target["state"] == "SUSPENDED", (
            f"target state: expected SUSPENDED, got {target['state']}"
        )
        assert target["exclusion_reason"] is None, (
            "suspension is not exclusion, so no exclusion_reason is recorded"
        )
        plan = success_data(client.get_test_plan(scenario["plan_id"]))
        assert plan["status"] == "CLOSED", f"plan status: expected CLOSED, got {plan['status']}"
        # Proposing the candidate, deciding it, activating the plan, chartering the
        # engagement and this bubble-up close are the five mutations that follow
        # creation at version 1.
        assert_exact_int(plan["version"], 6, "plan version")

        second = client.emergency_stop(
            scenario["engagement_id"],
            "PAUSE",
            "Trying to stop it again",
            headers=compliance_officer_headers(),
        )

        assert_error_id(second, ERR_ENGAGEMENT_ALREADY_TERMINATED)
        assert second.status_code == 409, (
            f"expected HTTP 409 for a second stop, got {second.status_code}"
        )

    def test_a_revoked_document_accepts_no_further_target(self, client):
        """The frozen-document rule answers ahead of the suspension and collision rules.

        PRD: "Target creation and target exclusion require the parent document to be `DRAFT` or `SIGNED` (`ERR_ROE_NOT_MODIFIABLE`, 409); a `SUSPENDED` or `REVOKED` document is frozen."

        Design: Corner/state_machines/target_creation_on_a_revoked_document_is_rejected
        """
        scenario = build_scenario(
            client,
            stage="roe_signed",
            roe={"allowed_techniques": ["SQLI", "XSS"]},
            target={"window_end": "2026-09-10T23:59:59Z"},
        )
        stopped = success_data(
            client.emergency_stop(
                scenario["engagement_id"],
                "TERMINATE",
                TERMINATION_REASON,
                headers=compliance_officer_headers(),
            )
        )
        assert_engagement_axes(stopped, authorization_state="TERMINATED")

        response = client.create_authorized_target(
            factories.authorized_target_payload(
                scenario["roe_id"],
                scenario["asset_id"],
                window_start="2026-09-20T00:00:00Z",
                window_end="2026-09-25T23:59:59Z",
                technique_allowlist=["XSS"],
            )
        )

        assert_error_id(response, ERR_ROE_NOT_MODIFIABLE)
        assert response.status_code == 409, (
            f"expected HTTP 409 for a frozen document, got {response.status_code}"
        )
        document = success_data(client.get_rules_of_engagement(scenario["roe_id"]))
        assert_exact_int(document["active_target_count"], 0, "active_target_count")


class TestRosterClearanceCycle:
    """A clearance is declared from two states only, and re-stamping is refused."""

    def test_re_clearing_an_available_tester_is_refused_and_keeps_the_first_instant(
        self, client
    ):
        """The second CLEARED finds AVAILABLE, which the transition does not declare.

        PRD: "A background-check result of `CLEARED` requires the tester to be `PENDING_CLEARANCE` or `SUSPENDED`, while a result of `FLAGGED` or `EXPIRED` requires the tester to be `AVAILABLE` or `ASSIGNED` (`ERR_TESTER_STATE_INVALID`, 409)."
        PRD: "On success the result is written to `background_check_status`, `background_check_at` is stamped with the current instant, and `availability_state` advances `PENDING_CLEARANCE` → `AVAILABLE` (or `SUSPENDED` → `AVAILABLE`, which is how a re-cleared tester rejoins the roster)."

        Design: Corner/state_machines/clearing_a_tester_who_is_already_available_is_rejected
        """
        advance_clock(client, T_PROGRAMME_OPEN)
        tester = created_data(
            client.create_tester(
                factories.tester_payload(
                    full_name="Dana Ruiz", certifications=["OSCP", "CISSP"]
                )
            )
        )
        assert tester["availability_state"] == "PENDING_CLEARANCE", (
            f"availability_state: expected PENDING_CLEARANCE, got "
            f"{tester['availability_state']}"
        )
        assert tester["background_check_status"] == "PENDING", (
            f"background_check_status: expected PENDING, got "
            f"{tester['background_check_status']}"
        )
        assert tester["background_check_at"] is None, (
            f"background_check_at: expected null, got {tester['background_check_at']}"
        )
        cleared = success_data(
            client.record_background_check(
                tester["id"], "CLEARED", headers=compliance_officer_headers()
            )
        )
        assert cleared["availability_state"] == "AVAILABLE", (
            f"availability_state: expected AVAILABLE, got {cleared['availability_state']}"
        )
        assert cleared["background_check_status"] == "CLEARED"
        assert_instant_equals(
            cleared["background_check_at"], T_PROGRAMME_OPEN, "background_check_at"
        )
        advance_clock(client, T_NEXT_DAY)

        response = client.record_background_check(
            tester["id"], "CLEARED", headers=compliance_officer_headers()
        )

        assert_error_id(response, ERR_TESTER_STATE_INVALID)
        assert response.status_code == 409, (
            f"expected HTTP 409 for a re-clearance, got {response.status_code}"
        )
        reread = success_data(client.get_tester(tester["id"]))
        assert reread["availability_state"] == "AVAILABLE"
        assert_instant_equals(
            reread["background_check_at"], T_PROGRAMME_OPEN, "background_check_at"
        )


T_ALERT_DEADLINE = "2026-09-08T11:00:00Z"
T_ONE_SECOND_LATE = "2026-09-08T11:00:01Z"
CONTAINMENT_ACTION = "Refund endpoint taken out of the load balancer pool"
LATE_CONTAINMENT_ACTION = "Refund endpoint pulled from the pool"
CLOSING_CONTAINMENT_ACTION = "Patch shipped and validated by the SOC"
INTERNET_CRITICAL = {
    "title": "Unauthenticated SQL injection in the refund endpoint",
    "reproduction_steps": (
        "1. POST /refunds with id=1 OR 1=1 2. observe the full refund ledger in the response"
    ),
    "business_impact_narrative": (
        "An unauthenticated attacker can enumerate and alter refund records"
    ),
    "technical_base_score": 8.0,
    "exposure_class": "INTERNET",
    "root_cause_theme": "INPUT_VALIDATION",
}


def _internet_critical_alert(client):
    """Report an internet-facing CRITICAL finding at 10:00 and return its alert."""
    scenario = build_scenario(client, stage="executing")
    advance_clock(client, T_FIELDWORK_DAY)
    finding = report_finding(client, scenario, **INTERNET_CRITICAL)
    assert_severity(finding, score=9.90, band="CRITICAL")
    alert = find_alert_for_finding(client, finding["id"])
    assert alert is not None, "a CRITICAL finding must raise exactly one alert"
    return scenario, finding, alert


class TestCriticalAlertBranches:
    """The clock picks the branch, and ACKNOWLEDGED accepts nothing further."""

    def test_an_acknowledgement_exactly_on_the_deadline_is_on_time_and_happens_once(
        self, client
    ):
        """The deadline instant is inclusive, and a second acknowledgement is refused.

        PRD: "Its `ack_deadline_at` is `raised_at` advanced by a window that depends on the finding's `exposure_class`: an internet-facing critical finding must be acknowledged within one hour, that is 60 minutes, while a partner-facing or internal critical finding is allowed four hours, that is 240 minutes."
        PRD: "Acknowledging a `RAISED` alert at or before its `ack_deadline_at` moves it `RAISED` → `ACKNOWLEDGED`, stamps `acknowledged_at` with the current instant and `acknowledged_by_user_id` from `X-User-ID`, records the `containment_action`, and leaves `escalation_level` at 1 — an acknowledgement landing exactly on the deadline instant still counts as on time."
        PRD: "An alert already sitting at `ACKNOWLEDGED` accepts no further acknowledgement and is refused with `ERR_ALERT_ALREADY_ACKNOWLEDGED`."

        Design: Corner/state_machines/acknowledging_an_alert_twice_is_rejected
        """
        _scenario, _finding, alert = _internet_critical_alert(client)
        assert alert["state"] == "RAISED", f"state: expected RAISED, got {alert['state']}"
        assert_exact_int(alert["escalation_level"], 1, "escalation_level")
        assert_instant_equals(alert["ack_deadline_at"], T_ALERT_DEADLINE, "ack_deadline_at")
        advance_clock(client, T_ALERT_DEADLINE)

        acknowledged = success_data(
            client.acknowledge_critical_alert(alert["id"], CONTAINMENT_ACTION)
        )

        assert acknowledged["state"] == "ACKNOWLEDGED", (
            f"state: expected ACKNOWLEDGED, got {acknowledged['state']}"
        )
        assert_exact_int(acknowledged["escalation_level"], 1, "escalation_level")
        assert acknowledged["acknowledged_by_user_id"] == PM_USER_ID, (
            f"acknowledged_by_user_id: expected {PM_USER_ID}, "
            f"got {acknowledged['acknowledged_by_user_id']}"
        )
        assert_instant_equals(
            acknowledged["acknowledged_at"], T_ALERT_DEADLINE, "acknowledged_at"
        )
        assert acknowledged["containment_action"] == CONTAINMENT_ACTION

        second = client.acknowledge_critical_alert(
            alert["id"], "Second containment attempt", headers=compliance_officer_headers()
        )

        assert_error_id(second, ERR_ALERT_ALREADY_ACKNOWLEDGED)
        assert second.status_code == 409, (
            f"expected HTTP 409 for a second acknowledgement, got {second.status_code}"
        )
        reread = success_data(client.get_critical_alert(alert["id"]))
        assert reread["state"] == "ACKNOWLEDGED"
        assert_exact_int(reread["escalation_level"], 1, "escalation_level")
        assert reread["containment_action"] == CONTAINMENT_ACTION, (
            "the refused acknowledgement must not overwrite the containment narrative"
        )

    def test_one_second_late_escalates_and_the_closure_keeps_level_two(self, client):
        """The divergent branch is permanent: closing an escalation does not reset it.

        PRD: "Acknowledging a `RAISED` alert strictly after its `ack_deadline_at` moves it `RAISED` → `ESCALATED` instead, stamping the same `acknowledged_at` and `acknowledged_by_user_id` but setting `escalation_level` to 2."
        PRD: "An escalation is not the end of the matter: a `ComplianceOfficer` may acknowledge a second time to close it out, which moves the alert `ESCALATED` → `ACKNOWLEDGED`, updates `containment_action` with the newly supplied text, and leaves `escalation_level` at 2 as the permanent record that the deadline was missed."
        PRD: "The alert record references the finding through `finding_id`, stamps `raised_at` with the same instant as the finding's `discovered_at`, opens at `RAISED` state with `escalation_level` at 1, and leaves `acknowledged_at`, `acknowledged_by_user_id` and `containment_action` null."

        Design: Corner/state_machines/acknowledgement_one_second_late_escalates_then_closes_at_level_two
        """
        _scenario, _finding, alert = _internet_critical_alert(client)
        assert_instant_equals(alert["raised_at"], T_FIELDWORK_DAY, "raised_at")
        assert_instant_equals(alert["ack_deadline_at"], T_ALERT_DEADLINE, "ack_deadline_at")
        advance_clock(client, T_ONE_SECOND_LATE)

        escalated = success_data(
            client.acknowledge_critical_alert(alert["id"], LATE_CONTAINMENT_ACTION)
        )

        assert escalated["state"] == "ESCALATED", (
            f"state: expected ESCALATED one second past the deadline, "
            f"got {escalated['state']}"
        )
        assert_exact_int(escalated["escalation_level"], 2, "escalation_level")
        assert escalated["acknowledged_by_user_id"] == PM_USER_ID
        assert_instant_equals(
            escalated["acknowledged_at"], T_ONE_SECOND_LATE, "acknowledged_at"
        )

        closed = success_data(
            client.acknowledge_critical_alert(
                alert["id"],
                CLOSING_CONTAINMENT_ACTION,
                headers=compliance_officer_headers(),
            )
        )

        assert closed["state"] == "ACKNOWLEDGED", (
            f"state: expected ACKNOWLEDGED, got {closed['state']}"
        )
        assert_exact_int(closed["escalation_level"], 2, "escalation_level")
        assert closed["acknowledged_by_user_id"] == PM_USER_ID, (
            "closing an escalation does not overwrite the first acknowledger, got "
            f"{closed['acknowledged_by_user_id']}"
        )
        assert closed["containment_action"] == CLOSING_CONTAINMENT_ACTION, (
            f"containment_action: expected the closing narrative, "
            f"got {closed['containment_action']}"
        )


T_FLAG_DAY = "2026-09-06T00:00:00Z"
T_RECLEAR_DAY = "2026-09-07T00:00:00Z"
INTERVAL_END = "2026-09-20T00:00:00Z"


def _booking_provisioned_on_day_two(client):
    """Book a 40-hour grant over 09-05..09-20 and provision it on 2026-09-02."""
    scenario = build_scenario(
        client,
        stage="assignment",
        pre_assignment_clock=None,
        assignment={"interval_start": WINDOW_START, "interval_end": INTERVAL_END},
    )
    assert scenario["assignment"]["access_state"] == "REQUESTED", (
        f"access_state: expected REQUESTED, got {scenario['assignment']['access_state']}"
    )
    assert scenario["assignment"]["provisioned_at"] is None, (
        f"provisioned_at: expected null before provisioning, "
        f"got {scenario['assignment']['provisioned_at']}"
    )
    advance_clock(client, T_NEXT_DAY)
    scenario["assignment"] = success_data(
        client.set_access(scenario["assignment_id"], "PROVISION")
    )
    assert scenario["assignment"]["access_state"] == "PROVISIONED", (
        f"access_state: expected PROVISIONED, got {scenario['assignment']['access_state']}"
    )
    assert_instant_equals(
        scenario["assignment"]["provisioned_at"], T_NEXT_DAY, "provisioned_at"
    )
    return scenario


class TestAccessGrantLifecycle:
    """A grant is provisioned once, settled once, and never restored."""

    def test_provisioning_the_same_grant_twice_is_refused(self, client):
        """The second call finds PROVISIONED, so nothing is re-stamped or double-counted.

        PRD: "Access provisioning requires the assignment to be `REQUESTED`, and revocation requires it to be `REQUESTED` or `PROVISIONED` (`ERR_ASSIGNMENT_STATE_INVALID`, 409)."
        PRD: "On success the assignment moves `REQUESTED` → `PROVISIONED`, `provisioned_at` is stamped with the current instant, the tester's `active_assignment_count` is incremented, and the tester's `availability_state` moves `AVAILABLE` → `ASSIGNED` (a tester already at `ASSIGNED` stays there, since the state reflects "holds at least one live grant" rather than a count)."

        Design: Corner/state_machines/provisioning_the_same_assignment_twice_is_rejected
        """
        scenario = _booking_provisioned_on_day_two(client)
        advance_clock(client, T_DAY_THREE)

        response = client.set_access(scenario["assignment_id"], "PROVISION")

        assert_error_id(response, ERR_ASSIGNMENT_STATE_INVALID)
        assert response.status_code == 409, (
            f"expected HTTP 409 for a second provisioning, got {response.status_code}"
        )
        assignment = success_data(client.get_tester_assignment(scenario["assignment_id"]))
        assert assignment["access_state"] == "PROVISIONED"
        assert_instant_equals(assignment["provisioned_at"], T_NEXT_DAY, "provisioned_at")
        tester = success_data(client.get_tester(scenario["tester_id"]))
        assert_exact_int(tester["active_assignment_count"], 1, "active_assignment_count")
        assert tester["availability_state"] == "ASSIGNED", (
            f"availability_state: expected ASSIGNED, got {tester['availability_state']}"
        )

    def test_a_flag_settles_the_live_grant_and_a_reclearance_does_not_restore_it(
        self, client
    ):
        """The flag reaches into the ledger, and the roster cycle leaves the grant revoked.

        PRD: "It requires the tester to be at `AVAILABLE` or `ASSIGNED`, writes the supplied result into `background_check_status`, stamps `background_check_at`, and drives `availability_state` `AVAILABLE` → `SUSPENDED` (an `ASSIGNED` tester likewise lands at `SUSPENDED`)."
        PRD: "It then reaches across into live work: every assignment of this tester that is currently provisioned is revoked, each revocation settling its hours against its own engagement's ledger exactly as §3.5 describes, and `active_assignment_count` is reset to 0."
        PRD: "The baseline is the later of the assignment's `interval_start` and its `provisioned_at`; the effective end is the earlier of its `revoked_at` and its `interval_end`; the elapsed duration is the effective end minus the baseline expressed in hours, floored at 0 so a revocation that lands before the baseline yields nothing."
        PRD: "`REVOKED` is a terminal access state: a revoked grant is never restored, and re-admitting the tester means booking and provisioning again from scratch."

        Design: Corner/state_machines/flagged_background_check_revokes_live_access_and_a_reclear_returns_the_tester
        """
        scenario = _booking_provisioned_on_day_two(client)
        before = success_data(client.get_engagement(scenario["engagement_id"]))
        assert_hour_ledger(before, allocated=80, reserved=40, consumed=0, available=40)
        advance_clock(client, T_FLAG_DAY)

        flagged = success_data(
            client.record_background_check(
                scenario["tester_id"], "FLAGGED", headers=compliance_officer_headers()
            )
        )

        assert flagged["availability_state"] == "SUSPENDED", (
            f"availability_state: expected SUSPENDED, got {flagged['availability_state']}"
        )
        assert flagged["background_check_status"] == "FLAGGED"
        assert_exact_int(flagged["active_assignment_count"], 0, "active_assignment_count")
        revoked = success_data(client.get_tester_assignment(scenario["assignment_id"]))
        assert revoked["access_state"] == "REVOKED", (
            f"access_state: expected REVOKED, got {revoked['access_state']}"
        )
        assert_instant_equals(revoked["revoked_at"], T_FLAG_DAY, "revoked_at")
        assert_exact_int(revoked["settled_hours"], 24, "settled_hours")
        after = success_data(client.get_engagement(scenario["engagement_id"]))
        assert_hour_ledger(after, allocated=80, reserved=0, consumed=24, available=56)
        advance_clock(client, T_RECLEAR_DAY)

        recleared = success_data(
            client.record_background_check(
                scenario["tester_id"], "CLEARED", headers=compliance_officer_headers()
            )
        )

        assert recleared["availability_state"] == "AVAILABLE", (
            f"availability_state: expected AVAILABLE, got {recleared['availability_state']}"
        )
        assert recleared["background_check_status"] == "CLEARED"
        assert_instant_equals(
            recleared["background_check_at"], T_RECLEAR_DAY, "background_check_at"
        )
        assert_exact_int(recleared["active_assignment_count"], 0, "active_assignment_count")
        still_revoked = success_data(client.get_tester_assignment(scenario["assignment_id"]))
        assert still_revoked["access_state"] == "REVOKED", (
            "re-clearing the tester must not resurrect the revoked grant, got "
            f"{still_revoked['access_state']}"
        )


class TestPauseAndResumeCascadeConditionally:
    """A pause suspends what is live; a resume revives only what it suspended."""

    def test_resume_revives_the_suspended_target_and_leaves_the_excluded_one_out(
        self, client
    ):
        """The cascade is conditional on each child's own state, in both directions.

        PRD: "Because that document is suspended, each of its targets in `ACTIVE` state moves to `SUSPENDED`, and the document's `active_target_count` is decremented once per target moved."
        PRD: "Resumption moves the authorization axis `SUSPENDED` → `AUTHORIZED`, clears `suspension_reason` back to null, moves the rules-of-engagement document `SUSPENDED` → `SIGNED`, and moves each of that document's targets in `SUSPENDED` state back to `ACTIVE`, incrementing `active_target_count` once per target revived."
        PRD: "`EXCLUDED` is terminal — an excluded target is never revived, not even by resuming a suspended engagement."

        Design: Corner/state_machines/resume_revives_suspended_targets_but_leaves_excluded_ones_excluded
        """
        scenario = build_scenario(
            client,
            stage="roe",
            roe={"allowed_techniques": ["SQLI", "AUTHZ_BYPASS"]},
        )
        partner_portal = created_data(
            client.create_asset(factories.partner_portal_asset_payload())
        )
        target_a = created_data(
            client.create_authorized_target(
                factories.authorized_target_payload(
                    scenario["roe_id"], scenario["asset_id"], technique_allowlist=["SQLI"]
                )
            )
        )
        target_b = created_data(
            client.create_authorized_target(
                factories.authorized_target_payload(
                    scenario["roe_id"],
                    partner_portal["id"],
                    technique_allowlist=["AUTHZ_BYPASS"],
                )
            )
        )
        signed = success_data(
            client.sign_rules_of_engagement(scenario["roe_id"], signature_note=SIGN_NOTE)
        )
        assert_exact_int(signed["active_target_count"], 2, "active_target_count at signature")
        excluded = success_data(
            client.exclude_authorized_target(
                target_b["id"],
                PORTAL_EXCLUSION_REASON,
                headers=compliance_officer_headers(),
            )
        )
        assert excluded["state"] == "EXCLUDED", (
            f"state: expected EXCLUDED before the pause, got {excluded['state']}"
        )

        paused = success_data(
            client.emergency_stop(
                scenario["engagement_id"],
                "PAUSE",
                PAUSE_REASON,
                headers=compliance_officer_headers(),
            )
        )
        assert_engagement_axes(paused, authorization_state="SUSPENDED")
        assert paused["suspension_reason"] == PAUSE_REASON, (
            f"suspension_reason: expected the pause reason, got {paused['suspension_reason']}"
        )
        rows, _meta = assert_page(
            client.list_authorized_targets(
                params={"roe_id": scenario["roe_id"], "state": "SUSPENDED"},
                headers=compliance_officer_headers(),
            ),
            total_count=1,
            has_more=False,
            row_count=1,
        )
        assert rows[0]["id"] == target_a["id"], (
            "only the target that was ACTIVE at pause time is suspended by the cascade"
        )

        resumed = success_data(
            client.resume_engagement(scenario["engagement_id"], resume_note=RESUME_NOTE)
        )

        assert_engagement_axes(resumed, authorization_state="AUTHORIZED")
        assert resumed["suspension_reason"] is None, (
            f"suspension_reason: expected null after the resume, "
            f"got {resumed['suspension_reason']}"
        )
        revived = success_data(client.get_authorized_target(target_a["id"]))
        assert revived["state"] == "ACTIVE", (
            f"target A state: expected ACTIVE, got {revived['state']}"
        )
        left_out = success_data(client.get_authorized_target(target_b["id"]))
        assert left_out["state"] == "EXCLUDED", (
            f"target B state: expected EXCLUDED, got {left_out['state']}"
        )
        assert left_out["exclusion_reason"] == PORTAL_EXCLUSION_REASON, (
            f"exclusion_reason: expected the recorded reason, "
            f"got {left_out['exclusion_reason']}"
        )
        document = success_data(client.get_rules_of_engagement(scenario["roe_id"]))
        assert document["status"] == "SIGNED", (
            f"document status: expected SIGNED, got {document['status']}"
        )
        assert_exact_int(document["active_target_count"], 1, "active_target_count")
