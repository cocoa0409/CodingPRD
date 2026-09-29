"""Two state machines that are not ladders.

An engagement carries two parallel axes, and a pause-and-resume round trip on the
authorization axis must leave the execution axis exactly where it was. A
remediation, by contrast, is a cycle: rejected and partially validated retests
push it back to ASSIGNED again and again, and only the partial lap moves the
deadline.
"""

from test_helpers import factories
from test_helpers.assertions import (
    assert_engagement_axes,
    assert_exact_int,
    assert_hour_ledger,
    assert_instant_equals,
    assert_risk_ledger,
    assert_score,
    created_data,
    success_data,
)
from test_helpers.constants import T_FIELDWORK_DAY
from test_helpers.fixtures import (
    accept_finding,
    advance_clock,
    build_scenario,
    open_remediation,
    open_retest,
    report_finding,
    submit_evidence,
)
from test_helpers.test_users import make_tester_headers

T_FIELDWORK_DONE = "2026-09-09T09:00:00Z"
T_REMEDIATION_OPENED = "2026-09-08T12:00:00Z"


def _fieldwork_complete_engagement(client):
    """Run an engagement all the way to FIELDWORK_COMPLETE with no findings filed."""
    scenario = build_scenario(
        client,
        roe={"exclusions": ["prod-db-01"], "allowed_techniques": ["SQLI", "XSS"]},
        target={"technique_allowlist": ["SQLI"]},
    )
    advance_clock(client, T_FIELDWORK_DONE)
    scenario["engagement"] = success_data(
        client.drive_execution(scenario["engagement_id"], "COMPLETE_FIELDWORK")
    )
    return scenario


class TestEngagementAxesMoveIndependently:
    """A pause and a resume drive the authorization axis and nothing else."""

    def test_a_pause_leaves_the_execution_axis_at_fieldwork_complete(self, client):
        """The authorization axis drops to SUSPENDED while the execution axis keeps the
        FIELDWORK_COMPLETE it reached, and the provisional score stays stamped.

        PRD: "A `PAUSE` is reversible and moves the authorization axis `AUTHORIZED` → `SUSPENDED`, then runs a six-link cascade."

        PRD: "Crucially, **the execution axis is untouched**: an engagement that was `EXECUTING` remains `EXECUTING` while suspended."

        Design: Difficulty/non_linear_state_machine/engagement_authorization_and_execution_axes_move_independently
        """
        scenario = _fieldwork_complete_engagement(client)
        assert_score(
            scenario["engagement"]["provisional_assurance_score"],
            100.00,
            "provisional_assurance_score",
        )

        paused = success_data(
            client.emergency_stop(
                scenario["engagement_id"], "PAUSE", "Client change freeze declared"
            )
        )

        assert_engagement_axes(
            paused, execution_state="FIELDWORK_COMPLETE", authorization_state="SUSPENDED"
        )
        assert paused["suspension_reason"] == "Client change freeze declared"
        assert_score(
            paused["provisional_assurance_score"], 100.00, "provisional_assurance_score"
        )
        assert_hour_ledger(paused, allocated=80, reserved=0, consumed=40, available=40)

    def test_the_pause_cascade_suspends_the_document_its_target_and_the_access_grant(
        self, client
    ):
        """The document, its only target and the provisioned grant all move in the same
        request, and the grant settles the 40 hours it had reserved.

        PRD: "Because the engagement is now suspended, its rules-of-engagement document moves `SIGNED` → `SUSPENDED`."

        PRD: "Because those targets are suspended, every assignment of this engagement whose `access_state` is `PROVISIONED` and whose `granted_asset_ids` intersect the suspended targets' assets moves to `REVOKED`."

        PRD: "That elapsed figure is rounded **up** to the next whole hour, and `settled_hours` is the smaller of that rounded figure and the assignment's `requested_hours` — a tester can never consume more hours than were reserved for them, however long the interval ran."

        Design: Difficulty/non_linear_state_machine/engagement_authorization_and_execution_axes_move_independently
        """
        scenario = _fieldwork_complete_engagement(client)

        success_data(
            client.emergency_stop(
                scenario["engagement_id"], "PAUSE", "Client change freeze declared"
            )
        )

        roe = success_data(client.get_rules_of_engagement(scenario["roe_id"]))
        assert roe["status"] == "SUSPENDED"
        assert_exact_int(roe["active_target_count"], 0, "active_target_count")

        target = success_data(client.get_authorized_target(scenario["target_id"]))
        assert target["state"] == "SUSPENDED"

        assignment = success_data(client.get_tester_assignment(scenario["assignment_id"]))
        assert assignment["access_state"] == "REVOKED"
        assert_exact_int(assignment["settled_hours"], 40, "settled_hours")

    def test_resuming_recovers_the_authorization_axis_but_not_the_access_grant(self, client):
        """Resumption revives the document and the target, clears the suspension reason
        and leaves the execution axis untouched, but the revoked grant stays revoked.

        PRD: "Resumption moves the authorization axis `SUSPENDED` → `AUTHORIZED`, clears `suspension_reason` back to null, moves the rules-of-engagement document `SUSPENDED` → `SIGNED`, and moves each of that document's targets in `SUSPENDED` state back to `ACTIVE`, incrementing `active_target_count` once per target revived."

        PRD: "Revoked assignments are likewise **not** restored: access must be requested and provisioned again from scratch, because a revocation already settled hours that cannot be un-settled."

        Design: Difficulty/non_linear_state_machine/engagement_authorization_and_execution_axes_move_independently
        """
        scenario = _fieldwork_complete_engagement(client)
        success_data(
            client.emergency_stop(
                scenario["engagement_id"], "PAUSE", "Client change freeze declared"
            )
        )

        resumed = success_data(
            client.resume_engagement(scenario["engagement_id"], resume_note="Freeze lifted")
        )

        assert_engagement_axes(
            resumed, execution_state="FIELDWORK_COMPLETE", authorization_state="AUTHORIZED"
        )
        assert resumed["suspension_reason"] is None

        roe = success_data(client.get_rules_of_engagement(scenario["roe_id"]))
        assert roe["status"] == "SIGNED"
        assert_exact_int(roe["active_target_count"], 1, "active_target_count")

        target = success_data(client.get_authorized_target(scenario["target_id"]))
        assert target["state"] == "ACTIVE"

        assignment = success_data(client.get_tester_assignment(scenario["assignment_id"]))
        assert assignment["access_state"] == "REVOKED"

    def test_the_engagement_still_reports_after_the_suspension_round_trip(self, client):
        """FIELDWORK_COMPLETE survived the round trip, so the REPORT leg is still open.

        PRD: "Moving to reported takes the engagement `FIELDWORK_COMPLETE` → `REPORTED` and is a `ProgramManager` act, blocked while any finding of the engagement is still at `REPORTED` status."

        Design: Difficulty/non_linear_state_machine/engagement_authorization_and_execution_axes_move_independently
        """
        scenario = _fieldwork_complete_engagement(client)
        success_data(
            client.emergency_stop(
                scenario["engagement_id"], "PAUSE", "Client change freeze declared"
            )
        )
        success_data(
            client.resume_engagement(scenario["engagement_id"], resume_note="Freeze lifted")
        )

        reported = success_data(client.drive_execution(scenario["engagement_id"], "REPORT"))

        assert_engagement_axes(
            reported, execution_state="REPORTED", authorization_state="AUTHORIZED"
        )
        assert_score(
            reported["provisional_assurance_score"], 100.00, "provisional_assurance_score"
        )


def _remediation_with_an_independent_verifier(client):
    """Open a remediation on a critical finding and staff a second tester to retest it."""
    scenario = build_scenario(
        client,
        roe={
            "exclusions": ["prod-db-01"],
            "allowed_techniques": ["SQLI", "XSS", "AUTHZ_BYPASS"],
        },
        target={"technique_allowlist": ["AUTHZ_BYPASS"]},
    )

    verifier = created_data(client.create_tester(factories.second_tester_payload()))
    success_data(client.record_background_check(verifier["id"], "CLEARED"))
    verifier_headers = make_tester_headers(verifier["id"])

    advance_clock(client, T_FIELDWORK_DAY)
    finding = report_finding(client, scenario)
    accept_finding(client, finding["id"])

    advance_clock(client, T_REMEDIATION_OPENED)
    remediation = open_remediation(client, finding["id"])
    submit_evidence(client, remediation["id"], "s3://evidence/rem1/attempt-1.diff")
    return scenario, finding, remediation, verifier_headers


def _fail_the_retest(client, remediation_id, headers):
    return open_retest(
        client,
        remediation_id,
        headers=headers,
        evidence_uri="s3://evidence/rem1/retest-1.har",
        outcome="FAIL",
        residual_note="Tenant scoping still missing on the batch path",
    )


def _partially_verify_the_retest(client, remediation_id, headers):
    return open_retest(
        client,
        remediation_id,
        headers=headers,
        evidence_uri="s3://evidence/rem1/retest-2.har",
        outcome="PARTIAL",
        residual_note="Interactive path fixed, batch path pending",
    )


def _pass_the_retest(client, remediation_id, headers):
    return open_retest(
        client,
        remediation_id,
        headers=headers,
        evidence_uri="s3://evidence/rem1/retest-3.har",
        outcome="PASS",
    )


class TestRejectedRetestCyclesRemediation:
    """The remediation walks ASSIGNED → SUBMITTED → back again, twice."""

    def test_the_critical_severity_default_sets_the_first_deadline(self, client):
        """A CRITICAL finding on a SOC2 asset keeps its seven days, and the deadline
        inherits the time of day the remediation was opened at.

        PRD: "The severity default gives a `CRITICAL` finding one week — 7 days — a `HIGH` finding 30 days, a `MEDIUM` finding 60 days and a `LOW` finding 120 days."

        PRD: "`due_at` is the creation instant advanced by `sla_days` whole days, so it shares the time-of-day component of the moment the remediation was assigned."

        Design: Difficulty/non_linear_state_machine/rejected_retest_cycles_remediation_back_through_assigned_twice
        """
        _scenario, _finding, remediation, _headers = _remediation_with_an_independent_verifier(
            client
        )

        assert_exact_int(remediation["sla_days"], 7, "sla_days")
        assert_instant_equals(remediation["due_at"], "2026-09-15T12:00:00Z", "due_at")

    def test_a_failed_retest_reopens_the_remediation_and_clears_the_evidence(self, client):
        """The rejection and the re-opening land in one request, the evidence pointer is
        wiped, the deadline does not move and no extension is consumed.

        PRD: "A `FAIL` moves the remediation `SUBMITTED` → `REJECTED` and the finding `REMEDIATION_SUBMITTED` → `RETEST_FAILED`, and then immediately re-opens both: the remediation returns to `ASSIGNED` with its `evidence_uri` and `submitted_at` cleared, and the finding returns to `REMEDIATION_ASSIGNED`, ready for another attempt."

        Design: Difficulty/non_linear_state_machine/rejected_retest_cycles_remediation_back_through_assigned_twice
        """
        _scenario, finding, remediation, headers = _remediation_with_an_independent_verifier(
            client
        )

        verification = _fail_the_retest(client, remediation["id"], headers)
        assert verification["outcome"] == "FAIL"

        reopened = success_data(client.get_remediation(remediation["id"]))
        assert reopened["status"] == "ASSIGNED"
        assert reopened["evidence_uri"] is None
        assert reopened["submitted_at"] is None
        assert_instant_equals(reopened["due_at"], "2026-09-15T12:00:00Z", "due_at")
        assert_exact_int(reopened["extension_count"], 0, "extension_count")

        assert success_data(client.get_finding(finding["id"]))["status"] == (
            "REMEDIATION_ASSIGNED"
        )

    def test_resubmitting_supersedes_the_verification_of_the_earlier_bundle(self, client):
        """The second lap starts at SUBMITTED again and retires the first verification.

        PRD: "Submission carries the finding along, moving it `REMEDIATION_ASSIGNED` → `REMEDIATION_SUBMITTED`, and it also tidies history: every earlier verification of this remediation that is still sitting at `VERIFIED` state is moved to `SUPERSEDED`, so only the verification of the latest evidence bundle can ever be signed off."

        Design: Difficulty/non_linear_state_machine/rejected_retest_cycles_remediation_back_through_assigned_twice
        """
        _scenario, _finding, remediation, headers = _remediation_with_an_independent_verifier(
            client
        )
        first = _fail_the_retest(client, remediation["id"], headers)

        resubmitted = submit_evidence(
            client, remediation["id"], "s3://evidence/rem1/attempt-2.diff"
        )

        assert resubmitted["status"] == "SUBMITTED"
        retired = success_data(client.get_retest_verification(first["id"]))
        assert retired["state"] == "SUPERSEDED"

    def test_a_partial_retest_grants_a_fortnight_without_spending_an_extension(self, client):
        """The partial lap pushes the deadline out by exactly 14 days and leaves the
        extension counter at zero.

        PRD: "A `PARTIAL` does everything a `FAIL` does — moving the remediation `SUBMITTED` → `PARTIALLY_VALIDATED`, the finding to `RETEST_FAILED`, and then both back to `ASSIGNED` and `REMEDIATION_ASSIGNED` with the evidence pointer and submission instant cleared — and adds one thing: the remediation's `due_at` is pushed forward by a fortnight, that is 14 days, as a grace allowance for the work that was demonstrably partly done, and `extension_count` is deliberately **not** incremented, so a partial credit never consumes one of the owner's two extensions."

        Design: Difficulty/non_linear_state_machine/rejected_retest_cycles_remediation_back_through_assigned_twice
        """
        _scenario, _finding, remediation, headers = _remediation_with_an_independent_verifier(
            client
        )
        _fail_the_retest(client, remediation["id"], headers)
        submit_evidence(client, remediation["id"], "s3://evidence/rem1/attempt-2.diff")

        _partially_verify_the_retest(client, remediation["id"], headers)

        graced = success_data(client.get_remediation(remediation["id"]))
        assert graced["status"] == "ASSIGNED"
        assert_instant_equals(graced["due_at"], "2026-09-29T12:00:00Z", "due_at")
        assert_exact_int(graced["extension_count"], 0, "extension_count")

    def test_the_third_lap_passes_and_validates_the_remediation(self, client):
        """After two rejected laps a passing retest validates the work, on time.

        PRD: "A `PASS` moves the remediation `SUBMITTED` → `VALIDATED` and the finding `REMEDIATION_SUBMITTED` → `RETEST_PASSED`; nothing moves in the risk ledger yet, because the finding is not closed until it is signed off."

        PRD: "It also records lateness in `days_late`: the server takes `verified_at` minus the remediation's `due_at`, expresses the difference in whole days discarding any partial day, and floors the result at 0 — a verification recorded on or before the due instant reports 0 days late."

        Design: Difficulty/non_linear_state_machine/rejected_retest_cycles_remediation_back_through_assigned_twice
        """
        _scenario, finding, remediation, headers = _remediation_with_an_independent_verifier(
            client
        )
        _fail_the_retest(client, remediation["id"], headers)
        submit_evidence(client, remediation["id"], "s3://evidence/rem1/attempt-2.diff")
        _partially_verify_the_retest(client, remediation["id"], headers)
        submit_evidence(client, remediation["id"], "s3://evidence/rem1/attempt-3.diff")

        passing = _pass_the_retest(client, remediation["id"], headers)

        assert passing["state"] == "VERIFIED"
        assert_exact_int(passing["days_late"], 0, "days_late")
        assert success_data(client.get_remediation(remediation["id"]))["status"] == "VALIDATED"
        assert success_data(client.get_finding(finding["id"]))["status"] == "RETEST_PASSED"

    def test_the_plan_risk_ledger_is_untouched_by_the_whole_cycle(self, client):
        """The finding stayed open through both laps, so its 40 points never moved bucket.

        PRD: "A `PASS` moves the remediation `SUBMITTED` → `VALIDATED` and the finding `REMEDIATION_SUBMITTED` → `RETEST_PASSED`; nothing moves in the risk ledger yet, because the finding is not closed until it is signed off."

        Design: Difficulty/non_linear_state_machine/rejected_retest_cycles_remediation_back_through_assigned_twice
        """
        scenario, _finding, remediation, headers = _remediation_with_an_independent_verifier(
            client
        )

        opening = success_data(client.get_test_plan(scenario["plan_id"]))
        assert_risk_ledger(opening, total=40, open_points=40, closed=0)

        _fail_the_retest(client, remediation["id"], headers)
        submit_evidence(client, remediation["id"], "s3://evidence/rem1/attempt-2.diff")
        _partially_verify_the_retest(client, remediation["id"], headers)
        submit_evidence(client, remediation["id"], "s3://evidence/rem1/attempt-3.diff")
        _pass_the_retest(client, remediation["id"], headers)

        closing = success_data(client.get_test_plan(scenario["plan_id"]))
        assert_risk_ledger(closing, total=40, open_points=40, closed=0)
