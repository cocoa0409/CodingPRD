"""Two deep cascades that must land whole inside a single request.

An emergency pause reaches from the engagement's authorization axis all the way
down to the tester's availability, six links away, and no link can fire without
the one above it. A closure sign-off runs a different five-link chain from the
verification to the asset's exposure posture, and its last link only fires
because the link before it drove the critical count to exactly zero.
"""

from test_helpers.assertions import (
    assert_asset_posture,
    assert_engagement_axes,
    assert_exact_int,
    assert_hour_ledger,
    assert_instant_equals,
    assert_risk_ledger,
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
from test_helpers.test_users import compliance_officer_headers

T_REMEDIATION_OPENED = "2026-09-08T12:00:00Z"
T_VERIFICATION = "2026-09-20T11:00:00Z"
T_SIGN_OFF = "2026-09-20T12:00:00Z"
PAUSE_REASON = "Production incident opened by the SOC"


def _engagement_under_way(client):
    """An engagement mid-fieldwork with one provisioned lead tester."""
    scenario = build_scenario(
        client,
        roe={"exclusions": ["prod-db-01"], "allowed_techniques": ["SQLI", "XSS"]},
        target={"technique_allowlist": ["SQLI"]},
    )
    advance_clock(client, T_FIELDWORK_DAY)
    return scenario


class TestEmergencyPauseCascade:
    """One pause, six dependent links, ending at the tester's availability."""

    def test_the_baseline_shows_the_tester_holding_one_live_grant(self, client):
        """Before the pause the tester is assigned and counts exactly one live grant,
        which is what makes the last link of the cascade observable.

        PRD: "On success the assignment moves `REQUESTED` → `PROVISIONED`, `provisioned_at` is stamped with the current instant, the tester's `active_assignment_count` is incremented, and the tester's `availability_state` moves `AVAILABLE` → `ASSIGNED` (a tester already at `ASSIGNED` stays there, since the state reflects "holds at least one live grant" rather than a count)."

        Design: Difficulty/transitive_cascade/emergency_pause_cascade_reaches_tester_availability_through_six_links
        """
        scenario = _engagement_under_way(client)

        tester = success_data(client.get_tester(scenario["tester_id"]))
        assert tester["availability_state"] == "ASSIGNED"
        assert_exact_int(tester["active_assignment_count"], 1, "active_assignment_count")

    def test_the_pause_suspends_authorization_while_fieldwork_stays_executing(self, client):
        """Link 1: the authorization axis drops and records why, and the execution axis
        keeps running because the work is paused rather than rewound.

        PRD: "Invoking the stop supplies a `stop_code` of either `PAUSE` or `TERMINATE` and a mandatory `reason`, which is recorded in the engagement's `suspension_reason`."

        PRD: "Crucially, **the execution axis is untouched**: an engagement that was `EXECUTING` remains `EXECUTING` while suspended."

        Design: Difficulty/transitive_cascade/emergency_pause_cascade_reaches_tester_availability_through_six_links
        """
        scenario = _engagement_under_way(client)

        paused = success_data(
            client.emergency_stop(
                scenario["engagement_id"],
                "PAUSE",
                PAUSE_REASON,
                headers=compliance_officer_headers(),
            )
        )

        assert_engagement_axes(
            paused, execution_state="EXECUTING", authorization_state="SUSPENDED"
        )
        assert paused["suspension_reason"] == PAUSE_REASON

    def test_the_document_and_its_only_target_follow_the_engagement_down(self, client):
        """Links 2 and 3: the signed document suspends, its active target suspends with
        it, and the document's active-target tally falls to zero.

        PRD: "Because the engagement is now suspended, its rules-of-engagement document moves `SIGNED` → `SUSPENDED`."

        PRD: "Because that document is suspended, each of its targets in `ACTIVE` state moves to `SUSPENDED`, and the document's `active_target_count` is decremented once per target moved."

        Design: Difficulty/transitive_cascade/emergency_pause_cascade_reaches_tester_availability_through_six_links
        """
        scenario = _engagement_under_way(client)

        success_data(
            client.emergency_stop(
                scenario["engagement_id"],
                "PAUSE",
                PAUSE_REASON,
                headers=compliance_officer_headers(),
            )
        )

        roe = success_data(client.get_rules_of_engagement(scenario["roe_id"]))
        assert roe["status"] == "SUSPENDED"
        assert_exact_int(roe["active_target_count"], 0, "active_target_count")

        target = success_data(client.get_authorized_target(scenario["target_id"]))
        assert target["state"] == "SUSPENDED"

    def test_the_intersecting_grant_is_revoked_and_settles_the_hours_it_held(self, client):
        """Links 4 and 5: the grant covering the suspended target is revoked at the pause
        instant and settles 25 hours — 09:00 on the 7th to 10:00 on the 8th.

        PRD: "Because those targets are suspended, every assignment of this engagement whose `access_state` is `PROVISIONED` and whose `granted_asset_ids` intersect the suspended targets' assets moves to `REVOKED`."

        PRD: "The baseline is the later of the assignment's `interval_start` and its `provisioned_at`; the effective end is the earlier of its `revoked_at` and its `interval_end`; the elapsed duration is the effective end minus the baseline expressed in hours, floored at 0 so a revocation that lands before the baseline yields nothing."

        Design: Difficulty/transitive_cascade/emergency_pause_cascade_reaches_tester_availability_through_six_links
        """
        scenario = _engagement_under_way(client)

        paused = success_data(
            client.emergency_stop(
                scenario["engagement_id"],
                "PAUSE",
                PAUSE_REASON,
                headers=compliance_officer_headers(),
            )
        )

        assignment = success_data(client.get_tester_assignment(scenario["assignment_id"]))
        assert assignment["access_state"] == "REVOKED"
        assert_instant_equals(assignment["revoked_at"], T_FIELDWORK_DAY, "revoked_at")
        assert_exact_int(assignment["settled_hours"], 25, "settled_hours")
        assert_hour_ledger(paused, allocated=80, reserved=0, consumed=25, available=55)

    def test_the_tester_becomes_available_again_once_the_count_reaches_zero(self, client):
        """Link 6: the decremented count reaches zero, so the tester rejoins the roster.

        PRD: "And because a tester's live-assignment count may have reached 0, that tester moves `ASSIGNED` → `AVAILABLE`."

        Design: Difficulty/transitive_cascade/emergency_pause_cascade_reaches_tester_availability_through_six_links
        """
        scenario = _engagement_under_way(client)

        success_data(
            client.emergency_stop(
                scenario["engagement_id"],
                "PAUSE",
                PAUSE_REASON,
                headers=compliance_officer_headers(),
            )
        )

        tester = success_data(client.get_tester(scenario["tester_id"]))
        assert_exact_int(tester["active_assignment_count"], 0, "active_assignment_count")
        assert tester["availability_state"] == "AVAILABLE"


def _verification_awaiting_sign_off(client):
    """Carry one critical finding all the way to a passed evidence-only retest."""
    scenario = build_scenario(
        client,
        roe={"exclusions": ["prod-db-01"], "allowed_techniques": ["AUTHZ_BYPASS"]},
        target={"technique_allowlist": ["AUTHZ_BYPASS"]},
    )
    advance_clock(client, T_FIELDWORK_DAY)
    finding = report_finding(client, scenario)
    accept_finding(client, finding["id"])

    advance_clock(client, T_REMEDIATION_OPENED)
    remediation = open_remediation(client, finding["id"], validation_requirement="EVIDENCE_ONLY")
    submit_evidence(client, remediation["id"])

    advance_clock(client, T_VERIFICATION)
    verification = open_retest(client, remediation["id"])

    advance_clock(client, T_SIGN_OFF)
    return scenario, finding, remediation, verification


class TestClosureSignOffCascade:
    """One signature, five dependent links, ending at the asset's exposure posture."""

    def test_the_asset_is_elevated_while_its_critical_finding_stays_open(self, client):
        """The baseline the cascade has to undo: one open finding, one of them critical,
        nothing remediated yet.

        PRD: "An asset sitting at `MONITORED` or `CLEARED` moves to `ELEVATED` the moment a newly rated `CRITICAL` finding pushes its critical count to at least 1."

        PRD: "Those three counters have precise definitions the server must keep true at all times: `open_finding_count` is the number of findings on this asset whose status is none of `CLOSED`, `DUPLICATE` or `RISK_ACCEPTED`; `open_critical_finding_count` is the number of those open findings whose severity band is `CRITICAL`; and `remediated_finding_count` is the number of findings on this asset that have reached `CLOSED`."

        Design: Difficulty/transitive_cascade/closure_signoff_cascade_clears_asset_exposure_through_five_links
        """
        scenario = build_scenario(
            client,
            roe={"exclusions": ["prod-db-01"], "allowed_techniques": ["AUTHZ_BYPASS"]},
            target={"technique_allowlist": ["AUTHZ_BYPASS"]},
        )
        advance_clock(client, T_FIELDWORK_DAY)
        report_finding(client, scenario)

        asset = success_data(client.get_asset(scenario["asset_id"]))
        assert_asset_posture(
            asset,
            exposure_state="ELEVATED",
            open_findings=1,
            open_critical=1,
            remediated=0,
            last_cleared_at=None,
        )

    def test_the_verification_records_how_late_it_landed(self, client):
        """Due at noon on the 15th and verified at 11:00 on the 20th is four whole days
        late, the partial fifth day being discarded.

        PRD: "It also records lateness in `days_late`: the server takes `verified_at` minus the remediation's `due_at`, expresses the difference in whole days discarding any partial day, and floors the result at 0 — a verification recorded on or before the due instant reports 0 days late."

        Design: Difficulty/transitive_cascade/closure_signoff_cascade_clears_asset_exposure_through_five_links
        """
        _scenario, _finding, remediation, verification = _verification_awaiting_sign_off(client)

        assert_instant_equals(remediation["due_at"], "2026-09-15T12:00:00Z", "due_at")
        assert_exact_int(verification["days_late"], 4, "days_late")

    def test_the_signature_closes_the_verification_the_remediation_and_the_finding(
        self, client
    ):
        """Links 1, 2 and 3: the signature stamps the signer and the instant, and both
        records below it reach their terminal states in the same request.

        PRD: "On success the verification moves `VERIFIED` → `SIGNED_OFF`, stamping `signed_off_by_user_id` from the header, `signed_off_at` from the current instant, and the supplied `closure_note`."

        PRD: "Because the remediation is closed, its finding moves `RETEST_PASSED` → `CLOSED` with `closed_at` stamped from the current instant."

        Design: Difficulty/transitive_cascade/closure_signoff_cascade_clears_asset_exposure_through_five_links
        """
        _scenario, finding, remediation, verification = _verification_awaiting_sign_off(client)

        signed = success_data(
            client.sign_off_retest_verification(
                verification["id"], "Tenant scoping verified on every refund path"
            )
        )

        assert signed["state"] == "SIGNED_OFF"
        assert signed["signed_off_by_user_id"] == "co-1"
        assert_instant_equals(signed["signed_off_at"], T_SIGN_OFF, "signed_off_at")
        assert signed["closure_note"] == "Tenant scoping verified on every refund path"

        assert success_data(client.get_remediation(remediation["id"]))["status"] == "CLOSED"
        closed_finding = success_data(client.get_finding(finding["id"]))
        assert closed_finding["status"] == "CLOSED"
        assert_instant_equals(closed_finding["closed_at"], T_SIGN_OFF, "closed_at")

    def test_the_closed_points_change_bucket_and_the_asset_counters_follow(self, client):
        """Link 4: the 40 points move from open to closed without the total moving, and
        the asset's counters move with them.

        PRD: "Because the finding is closed, the plan's ledger subtracts its points from `open_risk_points` and adds them to `closed_risk_points`, the asset's `open_finding_count` is decremented, the asset's `remediated_finding_count` is incremented, and for a `CRITICAL` finding the asset's `open_critical_finding_count` is decremented as well."

        Design: Difficulty/transitive_cascade/closure_signoff_cascade_clears_asset_exposure_through_five_links
        """
        scenario, _finding, _remediation, verification = _verification_awaiting_sign_off(client)

        success_data(
            client.sign_off_retest_verification(
                verification["id"], "Tenant scoping verified on every refund path"
            )
        )

        plan = success_data(client.get_test_plan(scenario["plan_id"]))
        assert_risk_ledger(plan, total=40, open_points=0, closed=40, accepted=0, duplicate=0)

        asset = success_data(client.get_asset(scenario["asset_id"]))
        assert_asset_posture(asset, open_findings=0, open_critical=0, remediated=1)

    def test_the_asset_clears_because_the_critical_count_reached_zero(self, client):
        """Link 5, which only fires because link 4 emptied the critical count.

        PRD: "And because that critical count may now have reached 0, the asset moves `ELEVATED` → `CLEARED` with `last_cleared_at` stamped from the current instant."

        Design: Difficulty/transitive_cascade/closure_signoff_cascade_clears_asset_exposure_through_five_links
        """
        scenario, _finding, _remediation, verification = _verification_awaiting_sign_off(client)

        success_data(
            client.sign_off_retest_verification(
                verification["id"], "Tenant scoping verified on every refund path"
            )
        )

        asset = success_data(client.get_asset(scenario["asset_id"]))
        assert_asset_posture(
            asset, exposure_state="CLEARED", open_critical=0, last_cleared_at=T_SIGN_OFF
        )
