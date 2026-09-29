"""Refusals: which complaint the programme voices when several rules are broken at once.

Every test here drives one endpoint into a refusal, proves the exact error the
ladder in the specification demands, proves the refused write changed nothing,
and then repairs the request so the same call succeeds.
"""

from test_helpers import (
    accept_finding,
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
    engagement_version,
    factories,
    find_alert_for_finding,
    make_tester_headers,
    open_remediation,
    program_manager_headers,
    report_finding,
    submit_evidence,
    success_data,
    read_plan_version,
)
from test_helpers.api_errors import (
    ERR_ASSET_NOT_GRANTED,
    ERR_BELOW_RISK_THRESHOLD,
    ERR_CLEARANCE_EXPIRED,
    ERR_DUPLICATE_CHAIN_NOT_ALLOWED,
    ERR_DUPLICATE_SCOPE_ITEM,
    ERR_DUPLICATE_SELF_REFERENCE,
    ERR_EMPTY_SCOPE_SELECTION,
    ERR_EXTENSION_LIMIT_REACHED,
    ERR_GRANT_EXCEEDS_AUTHORIZED_SCOPE,
    ERR_INTERVAL_OUTSIDE_WINDOW,
    ERR_INVALID_PAGINATION,
    ERR_LEAD_QUALIFICATION_NOT_MET,
    ERR_NO_AUTHORIZED_TARGETS,
    ERR_NO_OPEN_TESTING_WINDOW,
    ERR_OUTSIDE_TESTING_WINDOW,
    ERR_PLAN_ENGAGEMENT_LIMIT_REACHED,
    ERR_RESIDUAL_NOTE_REQUIRED,
    ERR_SOD_ROE_SIGNER_CONFLICT,
    ERR_SOD_VERIFIER_CONFLICT,
    ERR_TECHNIQUE_NOT_ALLOWED,
    ERR_TESTER_NOT_ASSIGNED,
    ERR_UNACKNOWLEDGED_CRITICAL_ALERT,
    ERR_VERIFIER_ROLE_NOT_PERMITTED,
    ERR_WINDOW_OUTSIDE_ENGAGEMENT,
)
from test_helpers.constants import (
    T_FIELDWORK_DAY,
    T_PROGRAMME_OPEN,
    WINDOW_END,
    WINDOW_START,
)
from test_helpers.test_users import CO_ALT_USER_ID, CO_USER_ID

# --- instants used by the temporal refusals ---------------------------------
T_CLEARANCE_INSTANT = "2026-09-08T09:00:00Z"
T_FIELDWORK_OPENING = "2026-09-08T09:00:00Z"
T_HALF_HOUR_LATER = "2026-09-08T09:30:00Z"
T_ALERT_DEADLINE = "2026-09-08T10:00:00Z"
T_TARGET_CLOSING = "2026-09-06T00:00:00Z"
LATE_CLEARANCE_EXPIRY = "2027-06-30T00:00:00Z"
TARGET_WINDOW_END = "2026-09-10T00:00:00Z"
BOOKING_INTERVAL_END = "2026-09-20T00:00:00Z"

# --- notes and free text ----------------------------------------------------
OVERRIDE_NOTE = "Accepted by the CISO despite the appetite threshold"
DEFERRAL_NOTE = "Waiting for the release freeze to lift"
WITHDRAWAL_NOTE = "Superseded"
SIGN_NOTE = "Independent review complete"
DRAFTER_SIGN_NOTE = "Signed by the drafter"
CONTAINMENT_ACTION = "Admin console removed from the internet edge"
RESIDUAL_NOTE = "The authorization check is still missing on the batch endpoint"

# --- finding shapes ---------------------------------------------------------
INTERNET_CRITICAL = {
    "title": "Unauthenticated console exposed at the internet edge",
    "reproduction_steps": "1. Browse to /admin 2. Observe the unauthenticated console",
    "business_impact_narrative": "Full administrative takeover of the payments estate",
    "technical_base_score": 8.0,
    "exposure_class": "INTERNET",
    "root_cause_theme": "ACCESS_CONTROL",
}
PARTNER_MEDIUM = {
    "title": "Session replay after logout",
    "reproduction_steps": "1. Replay the session 2. Observe the bypass",
    "business_impact_narrative": "Session hijack",
    "technical_base_score": 6.0,
    "exposure_class": "PARTNER",
    "root_cause_theme": "ACCESS_CONTROL",
}
PORTAL_IDOR = {
    "title": "Portal IDOR",
    "reproduction_steps": "1. Change the account id 2. Read another tenant",
    "business_impact_narrative": "Cross-tenant data read",
    "technical_base_score": 6.0,
    "exposure_class": "PARTNER",
    "root_cause_theme": "ACCESS_CONTROL",
}
LOW_RISK_MEDIUM = {
    "title": "Verbose error page on the refund form",
    "reproduction_steps": "1. Submit a malformed refund 2. Read the stack trace",
    "business_impact_narrative": "Internal paths leak to partners",
    "technical_base_score": 3.5,
    "exposure_class": "PARTNER",
    "root_cause_theme": "SECRETS_HANDLING",
}


def _propose(client, plan_id, asset_id, justification, hours=60):
    """Propose one candidate, re-reading the plan version immediately beforehand."""
    return client.create_scope_item(
        factories.scope_item_payload(
            plan_id,
            asset_id,
            read_plan_version(client, plan_id),
            justification=justification,
            requested_engagement_hours=hours,
        )
    )


def _decide(client, scope_item_id, decision, note=None, override_note=None):
    """Send one scope decision and hand back the raw response for inspection."""
    return client.decide_scope_item(
        scope_item_id,
        factories.decision_payload(decision, note=note, override_note=override_note),
    )


def _book(client, scenario, tester_id, **overrides):
    """Request one access grant on the scenario's engagement, versioned fresh."""
    version = overrides.pop(
        "expected_engagement_version",
        engagement_version(client, scenario["engagement_id"]),
    )
    granted = overrides.pop("granted_asset_ids", [scenario["asset_id"]])
    return client.create_tester_assignment(
        factories.tester_assignment_payload(
            scenario["engagement_id"], tester_id, version, granted, **overrides
        )
    )


def _report_as(client, scenario, tester_id, asset_id, shape):
    """File one finding as the named tester, threading the engagement version freshly."""
    payload = factories.finding_payload(
        scenario["engagement_id"],
        asset_id,
        engagement_version(client, scenario["engagement_id"]),
        **shape,
    )
    return client.create_finding(payload, make_tester_headers(tester_id))


def _register_cleared_tester(client, **overrides):
    """Register a tester and clear their background check in one step."""
    tester = created_data(client.create_tester(factories.tester_payload(**overrides)))
    return success_data(client.record_background_check(tester["id"], "CLEARED"))


class TestListingBounds:
    """The pagination contract is checked before any record is read."""

    def test_limit_and_offset_outside_the_declared_range_are_refused(self, client, admin):
        """A limit of 101, a limit of 0 and a negative offset are all refused, while limit 100 pages.

        PRD: "`limit` controls page size: it defaults to 10 when omitted, its minimum accepted value is 1 and its maximum accepted value is 100."
        PRD: "A `limit` outside the range 1 through 100 inclusive, or a negative `offset`, is rejected with `ERR_INVALID_PAGINATION` and HTTP 400."

        Design: Corner/validations/list_pagination_outside_the_declared_range_is_rejected
        """
        asset = created_data(client.create_asset(factories.asset_payload()))

        assert_error_id(
            client.list_assets(params={"limit": 101, "offset": 0}, headers=admin),
            ERR_INVALID_PAGINATION,
        )
        assert_error_id(
            client.list_assets(params={"limit": 0, "offset": 0}, headers=admin),
            ERR_INVALID_PAGINATION,
        )
        assert_error_id(
            client.list_assets(params={"limit": 10, "offset": -1}, headers=admin),
            ERR_INVALID_PAGINATION,
        )

        rows, _ = assert_page(
            client.list_assets(params={"limit": 100, "offset": 0}, headers=admin),
            total_count=1,
            has_more=False,
            row_count=1,
            limit=100,
            offset=0,
        )
        assert rows[0]["id"] == asset["id"], (
            f"first row: expected {asset['id']}, got {rows[0]['id']}"
        )


class TestScopeAdmissionGuards:
    """Proposing, approving and activating each carry a refusal of their own."""

    def test_a_second_live_candidate_for_the_same_asset_is_refused(self, client):
        """A duplicate proposal is refused while the first row is live, and accepted once it is withdrawn.

        PRD: "No competing scope item for the same plan-and-asset pair may hold `PROPOSED` or `APPROVED` status (`ERR_DUPLICATE_SCOPE_ITEM`, 409); no competing rules-of-engagement document for the same engagement may hold `DRAFT`, `SIGNED` or `SUSPENDED` status (`ERR_ROE_ALREADY_EXISTS`, 409); no competing remediation on the same finding may hold any status other than `CLOSED` (`ERR_REMEDIATION_ALREADY_EXISTS`, 409)."
        PRD: "Withdrawing moves a candidate at `PROPOSED` or `DEFERRED` to `WITHDRAWN`, sets its `priority_rank` to null, and likewise triggers a renumbering of the remainder."

        Design: Corner/validations/a_second_live_scope_item_for_the_same_asset_is_rejected
        """
        scenario = build_scenario(client, stage="plan")
        plan_id, asset_id = scenario["plan_id"], scenario["asset_id"]

        first = created_data(
            _propose(client, plan_id, asset_id, "Payments coverage", hours=120)
        )
        assert first["status"] == "PROPOSED", (
            f"status: expected PROPOSED, got {first['status']}"
        )

        assert_error_id(
            _propose(client, plan_id, asset_id, "Duplicate proposal"),
            ERR_DUPLICATE_SCOPE_ITEM,
        )

        withdrawn = success_data(
            _decide(client, first["id"], "WITHDRAW", note=WITHDRAWAL_NOTE)
        )
        assert withdrawn["status"] == "WITHDRAWN", (
            f"status: expected WITHDRAWN, got {withdrawn['status']}"
        )
        assert withdrawn["priority_rank"] is None, (
            f"priority_rank: expected null, got {withdrawn['priority_rank']}"
        )

        second = created_data(
            _propose(client, plan_id, asset_id, "Re-proposed after withdrawal")
        )
        assert second["id"] != first["id"], "the re-proposal must be a new candidate row"
        assert second["status"] == "PROPOSED", (
            f"status: expected PROPOSED, got {second['status']}"
        )
        assert_exact_int(second["priority_rank"], 1, "priority_rank")

        rows, _ = assert_page(
            client.list_scope_items(
                params={"test_plan_id": plan_id, "asset_id": asset_id, "limit": 100}
            ),
            total_count=2,
        )
        live = [row for row in rows if row["status"] in ("PROPOSED", "APPROVED")]
        assert len(live) == 1, f"live candidates for the asset: expected 1, got {len(live)}"

    def test_a_below_threshold_candidate_needs_an_override_note_to_be_approved(self, client):
        """A zero-appetite plan refuses a plain-note approval and records the override note it demands.

        PRD: "Approval carries one extra condition: if the candidate's `below_threshold_flag` is true, meaning it scored strictly below the plan's `admission_threshold`, then `override_note` must be present and non-blank, and its absence is refused with `ERR_BELOW_RISK_THRESHOLD`."
        PRD: "The note the server records in `decision_note` is the `override_note` when one was supplied, and otherwise the plain `note`."

        Design: Corner/validations/approving_a_below_threshold_candidate_needs_an_override_note
        """
        scenario = build_scenario(client, stage="plan", plan={"risk_appetite_score": 0})
        plan = scenario["plan"]
        assert_exact_int(plan["admission_threshold"], 100, "admission_threshold")

        candidate = created_data(
            _propose(client, plan["id"], scenario["asset_id"], "Payments coverage", hours=120)
        )
        assert_score(candidate["priority_score"], 89.80, "priority_score")
        assert candidate["below_threshold_flag"] is True, (
            f"below_threshold_flag: expected True, got {candidate['below_threshold_flag']}"
        )

        assert_error_id(
            _decide(client, candidate["id"], "APPROVE", note="Worth testing anyway"),
            ERR_BELOW_RISK_THRESHOLD,
        )
        untouched = success_data(client.get_scope_item(candidate["id"]))
        assert untouched["status"] == "PROPOSED", (
            f"status: expected PROPOSED, got {untouched['status']}"
        )

        approved = success_data(
            _decide(client, candidate["id"], "APPROVE", override_note=OVERRIDE_NOTE)
        )
        assert approved["status"] == "APPROVED", (
            f"status: expected APPROVED, got {approved['status']}"
        )
        assert approved["decision_note"] == OVERRIDE_NOTE, (
            f"decision_note: expected {OVERRIDE_NOTE}, got {approved['decision_note']}"
        )

    def test_activating_a_plan_whose_only_candidate_is_deferred_reports_the_empty_selection(
        self, client
    ):
        """Deferring the only candidate breaks both activation rules, and the empty selection speaks first.

        PRD: "Checks are evaluated in the following order, and the first one that fails ends the request."
        PRD: "It first requires that at least one candidate of the plan is `APPROVED`, refusing an empty selection with `ERR_EMPTY_SCOPE_SELECTION`."
        PRD: "It then recomputes `coverage_score` from scratch and requires the recomputed value to be at least 60.00 percent, refusing anything lower with `ERR_COVERAGE_BELOW_MINIMUM` — a plan sitting at exactly 60.00 activates."

        Design: Corner/validations/activating_a_plan_whose_only_candidate_is_deferred_is_rejected
        """
        scenario = build_scenario(client, stage="plan")
        plan_id = scenario["plan_id"]

        candidate = created_data(
            _propose(client, plan_id, scenario["asset_id"], "Payments coverage", hours=120)
        )
        deferred = success_data(_decide(client, candidate["id"], "DEFER", note=DEFERRAL_NOTE))
        assert deferred["status"] == "DEFERRED", (
            f"status: expected DEFERRED, got {deferred['status']}"
        )
        assert deferred["priority_rank"] is None, (
            f"priority_rank: expected null, got {deferred['priority_rank']}"
        )

        before = success_data(client.get_test_plan(plan_id))
        assert_score(before["coverage_score"], 0.00, "coverage_score")

        assert_error_id(client.activate_test_plan(plan_id), ERR_EMPTY_SCOPE_SELECTION)

        after = success_data(client.get_test_plan(plan_id))
        assert after["status"] == "DRAFT", f"status: expected DRAFT, got {after['status']}"
        assert_exact_int(after["version"], before["version"], "version")


class TestPlanFiscalCaps:
    """The plan's declared engagement count is a hard cap, checked last of all."""

    def test_a_second_engagement_beyond_the_declared_count_is_refused(self, client):
        """A one-engagement plan refuses the second charter and leaves its second candidate approved.

        PRD: "The plan must also have room: if the number of engagements already chartered under the plan has reached `planned_engagement_count`, the request is refused with `ERR_PLAN_ENGAGEMENT_LIMIT_REACHED`."
        PRD: "The scope item moves `APPROVED` → `CONSUMED`, which both records that the plan's intent has been acted on and releases the plan-and-asset uniqueness slot so a follow-up candidate for the same asset may be proposed later."

        Design: Corner/validations/creating_more_engagements_than_the_plan_declared_is_rejected
        """
        scenario = build_scenario(client, stage="plan", plan={"planned_engagement_count": 1})
        plan_id = scenario["plan_id"]
        asset_b = created_data(client.create_asset(factories.partner_portal_asset_payload()))

        candidate_a = created_data(
            _propose(client, plan_id, scenario["asset_id"], "Payments coverage", hours=120)
        )
        success_data(_decide(client, candidate_a["id"], "APPROVE", note="In scope"))
        candidate_b = created_data(
            _propose(client, plan_id, asset_b["id"], "Partner portal coverage", hours=60)
        )
        success_data(_decide(client, candidate_b["id"], "APPROVE", note="In scope"))

        activated = success_data(client.activate_test_plan(plan_id))
        assert activated["status"] == "ACTIVE", (
            f"status: expected ACTIVE, got {activated['status']}"
        )
        assert_score(activated["coverage_score"], 100.00, "coverage_score")

        created_data(
            client.create_engagement(
                factories.engagement_payload(plan_id, candidate_a["id"])
            )
        )

        assert_error_id(
            client.create_engagement(
                factories.engagement_payload(
                    plan_id, candidate_b["id"], hours_allocated=40
                )
            ),
            ERR_PLAN_ENGAGEMENT_LIMIT_REACHED,
        )

        untouched = success_data(client.get_scope_item(candidate_b["id"]))
        assert untouched["status"] == "APPROVED", (
            f"status: expected APPROVED, got {untouched['status']}"
        )
        assert_exact_int(untouched["priority_rank"], 1, "priority_rank")


class TestAuthorizationDocumentGuards:
    """Targets narrow the document, and the signature is what authorizes testing."""

    def test_a_target_technique_outside_the_document_allowlist_is_refused(self, client):
        """A superset allowlist and an empty allowlist are both refused; the proper subset opens a target.

        PRD: "A target names its `roe_id` and the `asset_id` it authorises, carries its own inclusive `window_start` and inclusive `window_end` (again, the end strictly after the start), and narrows permission further with `technique_allowlist` — a non-empty list that must be a subset of the parent document's `allowed_techniques`, since a target can never permit a technique the engagement itself does not allow."
        PRD: "A technique outside that set, or an empty list, is refused with `ERR_TECHNIQUE_NOT_ALLOWED`."
        PRD: "On acceptance the target opens at `ACTIVE` state with a null `exclusion_reason`, the parent document's `active_target_count` is incremented, and the document's `version` advances."

        Design: Corner/validations/a_target_technique_outside_the_document_allowlist_is_rejected
        """
        scenario = build_scenario(
            client, stage="roe", roe={"allowed_techniques": ["SQLI", "XSS"]}
        )
        roe_id, asset_id = scenario["roe_id"], scenario["asset_id"]

        def attempt(allowlist):
            return client.create_authorized_target(
                factories.authorized_target_payload(
                    roe_id,
                    asset_id,
                    window_end=TARGET_WINDOW_END,
                    technique_allowlist=allowlist,
                )
            )

        assert_error_id(attempt(["SQLI", "PHISHING"]), ERR_TECHNIQUE_NOT_ALLOWED)
        assert_error_id(attempt([]), ERR_TECHNIQUE_NOT_ALLOWED)

        target = created_data(attempt(["SQLI"]))
        assert target["state"] == "ACTIVE", f"state: expected ACTIVE, got {target['state']}"
        assert target["id"], "an accepted target must carry an identifier"
        assert target["technique_allowlist"] == ["SQLI"], (
            f"technique_allowlist: expected ['SQLI'], got {target['technique_allowlist']}"
        )

        document = success_data(client.get_rules_of_engagement(roe_id))
        assert_exact_int(document["active_target_count"], 1, "active_target_count")

    def test_signing_reports_the_missing_target_before_the_signer_conflict(self, client):
        """One document yields three answers: no targets, then the drafter conflict, then a clean signature.

        PRD: "Checks are evaluated in the following order, and the first one that fails ends the request."
        PRD: "It must have at least one target in `ACTIVE` state, or the signature is refused with `ERR_NO_AUTHORIZED_TARGETS` — an engagement cannot be authorized to test nothing."
        PRD: "And the signer's `X-User-ID` must differ from the document's `drafted_by_user_id`, or the signature is refused with `ERR_SOD_ROE_SIGNER_CONFLICT`."
        PRD: "On success the document moves `DRAFT` → `SIGNED`, `signed_by_user_id` is stamped from `X-User-ID` and `signed_at` from the current instant, and — the cross-record effect that matters most — the engagement's authorization axis moves `ROE_PENDING` → `AUTHORIZED`."

        Design: Corner/validations/signing_a_document_hits_the_target_rule_before_the_signer_conflict
        """
        scenario = build_scenario(client, stage="engagement")
        document = created_data(
            client.create_rules_of_engagement(
                factories.rules_of_engagement_payload(scenario["engagement_id"]),
                headers=program_manager_headers(CO_USER_ID),
            )
        )
        assert document["drafted_by_user_id"] == CO_USER_ID, (
            f"drafted_by_user_id: expected {CO_USER_ID}, "
            f"got {document['drafted_by_user_id']}"
        )

        assert_error_id(
            client.sign_rules_of_engagement(
                document["id"],
                signature_note=DRAFTER_SIGN_NOTE,
                headers=compliance_officer_headers(CO_USER_ID),
            ),
            ERR_NO_AUTHORIZED_TARGETS,
        )

        created_data(
            client.create_authorized_target(
                factories.authorized_target_payload(
                    document["id"], scenario["asset_id"], window_end=TARGET_WINDOW_END
                )
            )
        )

        assert_error_id(
            client.sign_rules_of_engagement(
                document["id"],
                signature_note=DRAFTER_SIGN_NOTE,
                headers=compliance_officer_headers(CO_USER_ID),
            ),
            ERR_SOD_ROE_SIGNER_CONFLICT,
        )

        signed = success_data(
            client.sign_rules_of_engagement(
                document["id"],
                signature_note=SIGN_NOTE,
                headers=compliance_officer_headers(CO_ALT_USER_ID),
            )
        )
        assert signed["status"] == "SIGNED", (
            f"status: expected SIGNED, got {signed['status']}"
        )
        assert signed["signed_by_user_id"] == CO_ALT_USER_ID, (
            f"signed_by_user_id: expected {CO_ALT_USER_ID}, "
            f"got {signed['signed_by_user_id']}"
        )

        engagement = success_data(client.get_engagement(scenario["engagement_id"]))
        assert_engagement_axes(engagement, authorization_state="AUTHORIZED")

    def test_a_target_window_outside_the_engagement_outranks_the_collision(self, client):
        """A window that both escapes the engagement and collides reports the containment failure.

        PRD: "Checks are evaluated in the following order, and the first one that fails ends the request."
        PRD: "The target's window must lie entirely inside the engagement's own window, and a window that pokes out at either end is refused with `ERR_WINDOW_OUTSIDE_ENGAGEMENT`."

        Design: Corner/validations/a_target_window_outside_the_engagement_outranks_a_collision
        """
        scenario = build_scenario(
            client, stage="targets", target={"window_end": TARGET_WINDOW_END}
        )
        roe_id, asset_a = scenario["roe_id"], scenario["asset_id"]
        assert scenario["target"]["state"] == "ACTIVE", (
            f"state: expected ACTIVE, got {scenario['target']['state']}"
        )
        asset_b = created_data(client.create_asset(factories.partner_portal_asset_payload()))

        assert_error_id(
            client.create_authorized_target(
                factories.authorized_target_payload(
                    roe_id,
                    asset_a,
                    window_start=T_PROGRAMME_OPEN,
                    window_end=T_TARGET_CLOSING,
                )
            ),
            ERR_WINDOW_OUTSIDE_ENGAGEMENT,
        )

        assert_error_id(
            client.create_authorized_target(
                factories.authorized_target_payload(
                    roe_id,
                    asset_a,
                    window_start="2026-09-11T00:00:00Z",
                    window_end="2026-10-01T00:00:00Z",
                )
            ),
            ERR_WINDOW_OUTSIDE_ENGAGEMENT,
        )

        boundary = created_data(
            client.create_authorized_target(
                factories.authorized_target_payload(
                    roe_id, asset_b["id"], window_start=WINDOW_START, window_end=WINDOW_END
                )
            )
        )
        assert boundary["state"] == "ACTIVE", (
            f"state: expected ACTIVE, got {boundary['state']}"
        )
        assert boundary["id"], "the boundary target must carry an identifier"
        assert_instant_equals(boundary["window_end"], WINDOW_END, "window_end")


class TestBookingGuards:
    """The four booking gates, and the least-privilege re-check at provisioning time."""

    def test_an_assignment_interval_that_leaves_the_engagement_window_is_refused(self, client):
        """An interval starting before the window is refused without moving the version or the ledger.

        PRD: "Four gates guard a booking, and they are evaluated in a fixed order so that the most structural complaint always wins. First, the occupation interval must lie inside the engagement's own testing window; an interval that extends beyond it is refused with `ERR_INTERVAL_OUTSIDE_WINDOW`."
        PRD: "From the certification list the server derives `qualification_score`: award 45 points for `OSCP`, 35 for `GPEN`, 25 for `CREST` and 15 for `CISSP`, add up the points for the certifications the tester actually holds, and cap the total at 100."

        Design: Corner/validations/an_assignment_interval_that_leaves_the_engagement_window_is_rejected
        """
        scenario = build_scenario(client, stage="roe_signed")
        tester = created_data(
            client.create_tester(
                factories.tester_payload(
                    full_name="Dana Reyes", certifications=["OSCP", "CISSP"]
                )
            )
        )
        assert_exact_int(tester["qualification_score"], 60, "qualification_score")

        before = success_data(client.get_engagement(scenario["engagement_id"]))
        assert_hour_ledger(before, allocated=80, reserved=0, consumed=0, available=80)

        assert_error_id(
            _book(
                client,
                scenario,
                tester["id"],
                expected_engagement_version=before["version"],
                assignment_role="MEMBER",
                interval_start=T_PROGRAMME_OPEN,
                interval_end=TARGET_WINDOW_END,
            ),
            ERR_INTERVAL_OUTSIDE_WINDOW,
        )

        midway = success_data(client.get_engagement(scenario["engagement_id"]))
        assert_exact_int(midway["version"], before["version"], "version")
        assert_hour_ledger(midway, reserved=0, available=80)

        booked = created_data(
            _book(
                client,
                scenario,
                tester["id"],
                expected_engagement_version=before["version"],
                assignment_role="MEMBER",
                interval_start=WINDOW_START,
                interval_end=WINDOW_END,
            )
        )
        assert booked["id"], "the boundary booking must carry an identifier"
        assert booked["access_state"] == "REQUESTED", (
            f"access_state: expected REQUESTED, got {booked['access_state']}"
        )
        assert_instant_equals(booked["interval_end"], WINDOW_END, "interval_end")

        after = success_data(client.get_engagement(scenario["engagement_id"]))
        assert_hour_ledger(after, reserved=40, consumed=0, available=40)

    def test_the_lead_gate_admits_exactly_sixty_qualification_points(self, client):
        """A forty-point tester cannot lead but may join, and a sixty-point tester leads.

        PRD: "Third comes the lead-qualification gate: a booking whose `assignment_role` is `LEAD` requires the tester's `qualification_score` to be at least 60, so a tester holding exactly 60 points qualifies while 59 does not, and a shortfall is refused with `ERR_LEAD_QUALIFICATION_NOT_MET`. A `MEMBER` booking has no qualification floor."
        PRD: "Fourth and last comes the money: `requested_hours` must be no greater than the engagement's current `hours_available`, with equality passing, and an over-draw is refused with `ERR_ENGAGEMENT_HOURS_EXCEEDED`."

        Design: Corner/validations/lead_role_requires_exactly_sixty_qualification_points
        """
        scenario = build_scenario(client, stage="roe_signed")
        junior = created_data(
            client.create_tester(
                factories.tester_payload(
                    full_name="Lee Nakamura", certifications=["CREST", "CISSP"]
                )
            )
        )
        senior = created_data(
            client.create_tester(
                factories.tester_payload(
                    full_name="Ada Fontaine", certifications=["GPEN", "CREST"]
                )
            )
        )
        assert_exact_int(junior["qualification_score"], 40, "qualification_score")
        assert_exact_int(senior["qualification_score"], 60, "qualification_score")

        interval = {
            "interval_start": WINDOW_START,
            "interval_end": BOOKING_INTERVAL_END,
        }
        assert_error_id(
            _book(client, scenario, junior["id"], assignment_role="LEAD", **interval),
            ERR_LEAD_QUALIFICATION_NOT_MET,
        )

        member = created_data(
            _book(client, scenario, junior["id"], assignment_role="MEMBER", **interval)
        )
        assert member["id"], "the member booking must carry an identifier"
        assert member["assignment_role"] == "MEMBER", (
            f"assignment_role: expected MEMBER, got {member['assignment_role']}"
        )

        lead = created_data(
            _book(client, scenario, senior["id"], assignment_role="LEAD", **interval)
        )
        assert lead["id"], "the lead booking must carry an identifier"
        assert lead["assignment_role"] == "LEAD", (
            f"assignment_role: expected LEAD, got {lead['assignment_role']}"
        )

        exhausted = success_data(client.get_engagement(scenario["engagement_id"]))
        assert_hour_ledger(exhausted, allocated=80, reserved=80, consumed=0, available=0)

    def test_provisioning_a_grant_wider_than_the_authorized_targets_is_refused(self, client):
        """A grant naming an unauthorized asset books happily and is stopped at provisioning.

        PRD: "Finally it re-verifies the scope: every member of `granted_asset_ids` must be the `asset_id` of an authorized target that belongs to this engagement's rules-of-engagement document and that is currently in `ACTIVE` state."
        PRD: "This deliberate re-check at provisioning time, rather than at booking time, is what keeps least privilege honest: authorization can shrink between the two moments."

        Design: Corner/validations/provisioning_a_grant_wider_than_the_authorized_targets_is_rejected
        """
        scenario = build_scenario(client, stage="roe_signed")
        engagement = success_data(client.get_engagement(scenario["engagement_id"]))
        assert_engagement_axes(engagement, authorization_state="AUTHORIZED")

        asset_b = created_data(client.create_asset(factories.partner_portal_asset_payload()))
        tester = _register_cleared_tester(
            client, full_name="Dana Reyes", certifications=["OSCP", "CISSP"]
        )
        assert tester["background_check_status"] == "CLEARED", (
            f"background_check_status: expected CLEARED, "
            f"got {tester['background_check_status']}"
        )

        wide = created_data(
            _book(
                client,
                scenario,
                tester["id"],
                granted_asset_ids=[scenario["asset_id"], asset_b["id"]],
                interval_start=WINDOW_START,
                interval_end=BOOKING_INTERVAL_END,
            )
        )
        assert wide["access_state"] == "REQUESTED", (
            f"access_state: expected REQUESTED, got {wide['access_state']}"
        )

        narrow = created_data(
            _book(
                client,
                scenario,
                tester["id"],
                assignment_role="MEMBER",
                granted_asset_ids=[scenario["asset_id"]],
                interval_start=WINDOW_START,
                interval_end=BOOKING_INTERVAL_END,
            )
        )

        assert_error_id(
            client.set_access(wide["id"], "PROVISION"), ERR_GRANT_EXCEEDS_AUTHORIZED_SCOPE
        )
        unchanged = success_data(client.get_tester_assignment(wide["id"]))
        assert unchanged["access_state"] == "REQUESTED", (
            f"access_state: expected REQUESTED, got {unchanged['access_state']}"
        )

        provisioned = success_data(client.set_access(narrow["id"], "PROVISION"))
        assert provisioned["access_state"] == "PROVISIONED", (
            f"access_state: expected PROVISIONED, got {provisioned['access_state']}"
        )

        roster_row = success_data(client.get_tester(tester["id"]))
        assert roster_row["availability_state"] == "ASSIGNED", (
            f"availability_state: expected ASSIGNED, "
            f"got {roster_row['availability_state']}"
        )
        assert_exact_int(roster_row["active_assignment_count"], 1, "active_assignment_count")


class TestClearanceAndWindowGates:
    """Two strict comparisons against the clock: clearance expiry and the window opening."""

    def test_clearance_expiring_exactly_at_the_clock_blocks_both_gated_calls(self, client):
        """An expiry equal to the clock is already expired for provisioning and for a fresh check alike.

        PRD: "It then re-verifies the human: the tester's `background_check_status` must be `CLEARED`, refused with `ERR_TESTER_NOT_CLEARED` if it is anything else, and their `clearance_expires_at` must lie strictly after the current instant, refused with `ERR_CLEARANCE_EXPIRED` when the expiry has arrived or passed."
        PRD: "A `CLEARED` result requires the tester to be at `PENDING_CLEARANCE` or `SUSPENDED` and additionally requires that `clearance_expires_at` lies strictly after the current instant — a clearance whose expiry falls exactly on the clock instant is already expired and the request is refused with `ERR_CLEARANCE_EXPIRED`."

        Design: Corner/validations/clearance_expiring_exactly_at_the_clock_blocks_both_gated_calls
        """
        scenario = build_scenario(
            client,
            stage="assignment",
            tester={
                "full_name": "Dana Reyes",
                "certifications": ["OSCP", "CISSP"],
                "clearance_expires_at": T_CLEARANCE_INSTANT,
            },
            assignment={
                "interval_start": WINDOW_START,
                "interval_end": BOOKING_INTERVAL_END,
            },
        )
        assert scenario["tester"]["background_check_status"] == "CLEARED", (
            "the first tester cleared on 2026-09-01 while its clearance was still ahead: "
            f"got {scenario['tester']['background_check_status']}"
        )

        pending = created_data(
            client.create_tester(
                factories.tester_payload(
                    full_name="Kim Alvarez",
                    certifications=["GPEN", "CREST"],
                    clearance_expires_at=T_CLEARANCE_INSTANT,
                )
            )
        )
        long_cleared = _register_cleared_tester(
            client,
            full_name="Ada Fontaine",
            certifications=["OSCP", "GPEN"],
            clearance_expires_at=LATE_CLEARANCE_EXPIRY,
        )
        spare_grant = created_data(
            _book(
                client,
                scenario,
                long_cleared["id"],
                assignment_role="MEMBER",
                interval_start=WINDOW_START,
                interval_end=BOOKING_INTERVAL_END,
            )
        )

        advance_clock(client, T_CLEARANCE_INSTANT)

        assert_error_id(
            client.set_access(scenario["assignment_id"], "PROVISION"), ERR_CLEARANCE_EXPIRED
        )
        assert_error_id(
            client.record_background_check(pending["id"], "CLEARED"), ERR_CLEARANCE_EXPIRED
        )

        untouched = success_data(client.get_tester(pending["id"]))
        assert untouched["background_check_status"] == "PENDING", (
            f"background_check_status: expected PENDING, "
            f"got {untouched['background_check_status']}"
        )
        assert untouched["availability_state"] == "PENDING_CLEARANCE", (
            f"availability_state: expected PENDING_CLEARANCE, "
            f"got {untouched['availability_state']}"
        )

        provisioned = success_data(client.set_access(spare_grant["id"], "PROVISION"))
        assert provisioned["access_state"] == "PROVISIONED", (
            "a clearance running strictly past the clock provisions at the same instant: "
            f"got {provisioned['access_state']}"
        )

    def test_starting_before_the_window_opens_is_refused_and_the_first_instant_passes(
        self, client
    ):
        """An authorized engagement cannot start four days early, and starts at the window's first instant.

        PRD: "It also requires the current instant to lie inside the engagement's window with both bounds inclusive, refusing anything earlier or later with `ERR_OUTSIDE_TESTING_WINDOW`."
        PRD: "Fieldwork begins with a start action on the engagement, which either a `ProgramManager` or a `Tester` may issue and which moves the execution axis `PLANNED` → `EXECUTING`."

        Design: Corner/validations/starting_before_the_window_opens_is_rejected_and_the_first_instant_passes
        """
        scenario = build_scenario(client, stage="roe_signed")
        assert scenario["roe"]["status"] == "SIGNED", (
            f"status: expected SIGNED, got {scenario['roe']['status']}"
        )
        assert_engagement_axes(
            scenario["engagement"],
            execution_state="PLANNED",
            authorization_state="AUTHORIZED",
        )

        assert_error_id(
            client.drive_execution(scenario["engagement_id"], "START"),
            ERR_OUTSIDE_TESTING_WINDOW,
        )
        midway = success_data(client.get_engagement(scenario["engagement_id"]))
        assert_engagement_axes(
            midway, execution_state="PLANNED", authorization_state="AUTHORIZED"
        )

        advance_clock(client, WINDOW_START)
        started = success_data(client.drive_execution(scenario["engagement_id"], "START"))
        assert_engagement_axes(
            started, execution_state="EXECUTING", authorization_state="AUTHORIZED"
        )


class TestFieldworkAndFindingGates:
    """Alerts hold fieldwork open, and target windows govern what may be reported."""

    def test_fieldwork_cannot_complete_while_a_critical_alert_is_unacknowledged(
        self, client, compliance_officer
    ):
        """A raised alert blocks completion; acknowledging it inside the hour lets the same call through.

        PRD: "Unacknowledged alerts hold the engagement open. Neither completing fieldwork nor closing the engagement is permitted while any alert of any finding of that engagement is still `RAISED`, and both attempts are refused with `ERR_UNACKNOWLEDGED_CRITICAL_ALERT`."
        PRD: "Its `ack_deadline_at` is `raised_at` advanced by a window that depends on the finding's `exposure_class`: an internet-facing critical finding must be acknowledged within one hour, that is 60 minutes, while a partner-facing or internal critical finding is allowed four hours, that is 240 minutes."
        PRD: "Completing fieldwork moves the engagement `EXECUTING` → `FIELDWORK_COMPLETE` and may be issued by a `ProgramManager` or a `Tester`; it is blocked while any alert of the engagement is still `RAISED`. It stamps `provisional_assurance_score`."

        Design: Corner/validations/fieldwork_cannot_complete_while_a_critical_alert_is_unacknowledged
        """
        scenario = build_scenario(client, stage="executing")
        advance_clock(client, T_FIELDWORK_OPENING)

        finding = report_finding(client, scenario, **INTERNET_CRITICAL)
        assert_severity(finding, score=9.90, band="CRITICAL", points=40, immediate=True)

        alert = find_alert_for_finding(client, finding["id"])
        assert alert is not None, "a CRITICAL finding must raise exactly one alert"
        assert alert["state"] == "RAISED", f"state: expected RAISED, got {alert['state']}"
        assert_instant_equals(alert["ack_deadline_at"], T_ALERT_DEADLINE, "ack_deadline_at")

        assert_error_id(
            client.drive_execution(scenario["engagement_id"], "COMPLETE_FIELDWORK"),
            ERR_UNACKNOWLEDGED_CRITICAL_ALERT,
        )

        advance_clock(client, T_HALF_HOUR_LATER)
        acknowledged = success_data(
            client.acknowledge_critical_alert(
                alert["id"], CONTAINMENT_ACTION, headers=compliance_officer
            )
        )
        assert acknowledged["state"] == "ACKNOWLEDGED", (
            f"state: expected ACKNOWLEDGED, got {acknowledged['state']}"
        )
        assert_exact_int(acknowledged["escalation_level"], 1, "escalation_level")

        completed = success_data(
            client.drive_execution(scenario["engagement_id"], "COMPLETE_FIELDWORK")
        )
        assert_engagement_axes(completed, execution_state="FIELDWORK_COMPLETE")
        assert_score(completed["provisional_assurance_score"], 75.00, "provisional_assurance_score")
        assert completed["final_assurance_score"] is None, (
            "final_assurance_score: expected null at fieldwork completion, "
            f"got {completed['final_assurance_score']}"
        )

    def test_a_finding_filed_after_every_authorized_window_closed_is_refused(self, client):
        """The finding gate reads the target windows, so a report two days late is refused.

        PRD: "First, at least one authorized target of the engagement's document must cover the current instant, meaning the instant falls between that target's `window_start` and `window_end` with both bounds inclusive; **the target's state is deliberately not consulted here**, so even an excluded target proves that an authorized window covered this moment, and this check refuses only reports filed when no authorized window of the document is open at all, with `ERR_NO_OPEN_TESTING_WINDOW`."

        Design: Corner/validations/a_finding_filed_after_every_authorized_window_closed_is_rejected
        """
        scenario = build_scenario(
            client, stage="executing", target={"window_end": T_TARGET_CLOSING}
        )
        assert_engagement_axes(scenario["engagement"], execution_state="EXECUTING")
        document = success_data(client.get_rules_of_engagement(scenario["roe_id"]))
        assert_exact_int(document["active_target_count"], 1, "active_target_count")

        advance_clock(client, T_FIELDWORK_DAY)
        assert_error_id(
            _report_as(
                client, scenario, scenario["tester_id"], scenario["asset_id"], PARTNER_MEDIUM
            ),
            ERR_NO_OPEN_TESTING_WINDOW,
        )

        advance_clock(client, T_TARGET_CLOSING)
        filed = created_data(
            _report_as(
                client, scenario, scenario["tester_id"], scenario["asset_id"], PARTNER_MEDIUM
            )
        )
        assert filed["id"], "the in-window report must carry an identifier"
        assert_instant_equals(filed["discovered_at"], T_TARGET_CLOSING, "discovered_at")
        assert_severity(filed, score=6.70, band="MEDIUM")

    def test_an_unprovisioned_tester_is_told_so_before_the_least_privilege_check(self, client):
        """A tester who is both unprovisioned and ungranted hears about the assignment first.

        PRD: "Fourth, the reporting tester must hold an assignment on this engagement whose `access_state` is `PROVISIONED`, or the report is refused with `ERR_TESTER_NOT_ASSIGNED`; this precedes the grant check because the grant check needs that assignment to exist. Fifth, the finding's `asset_id` must appear in that assignment's `granted_asset_ids`, or the report is refused with `ERR_ASSET_NOT_GRANTED`."

        Design: Corner/validations/an_unprovisioned_tester_is_told_so_before_the_least_privilege_check
        """
        asset_b = created_data(client.create_asset(factories.analytics_lake_asset_payload()))
        scenario = build_scenario(
            client, stage="executing", extra_targets=({"asset_id": asset_b["id"]},)
        )
        second = created_data(client.create_tester(factories.second_tester_payload()))
        spare_grant = created_data(
            _book(
                client,
                scenario,
                second["id"],
                assignment_role="MEMBER",
                granted_asset_ids=[scenario["asset_id"]],
                interval_start=WINDOW_START,
                interval_end=BOOKING_INTERVAL_END,
            )
        )
        assert spare_grant["access_state"] == "REQUESTED", (
            f"access_state: expected REQUESTED, got {spare_grant['access_state']}"
        )

        assert_error_id(
            _report_as(client, scenario, second["id"], asset_b["id"], PORTAL_IDOR),
            ERR_TESTER_NOT_ASSIGNED,
        )
        assert_error_id(
            _report_as(client, scenario, scenario["tester_id"], asset_b["id"], PORTAL_IDOR),
            ERR_ASSET_NOT_GRANTED,
        )

        filed = created_data(
            _report_as(
                client, scenario, scenario["tester_id"], scenario["asset_id"], PORTAL_IDOR
            )
        )
        assert filed["id"], "the granted report must carry an identifier"
        assert filed["discovered_by_tester_id"] == scenario["tester_id"], (
            f"discovered_by_tester_id: expected {scenario['tester_id']}, "
            f"got {filed['discovered_by_tester_id']}"
        )
        assert_severity(filed, score=6.70, band="MEDIUM")


class TestRemediationAndRetestGuards:
    """Deadlines move twice at most, and three verifier rules fire in a fixed order."""

    def test_a_third_extension_is_refused_and_leaves_the_due_date_alone(self, client):
        """Two extensions move the deadline, the third is refused and the counter stops at two.

        PRD: "A `ProgramManager` may grant an extension on a remediation that is still `ASSIGNED`, supplying `additional_days` and a mandatory `reason`; the extension adds those days to the current `due_at`, increments `extension_count`, re-evaluates the overdue flag, and leaves the remediation at `ASSIGNED` — it is a self-loop rather than a state change. A remediation whose `extension_count` has already reached 2 accepts no third extension and the request is refused with `ERR_EXTENSION_LIMIT_REACHED`."
        PRD: "The severity default gives a `CRITICAL` finding one week — 7 days — a `HIGH` finding 30 days, a `MEDIUM` finding 60 days and a `LOW` finding 120 days."

        Design: Corner/validations/a_third_extension_is_refused_and_leaves_the_due_date_alone
        """
        scenario = build_scenario(client, stage="executing")
        advance_clock(client, T_FIELDWORK_DAY)

        finding = report_finding(client, scenario, **LOW_RISK_MEDIUM)
        assert_severity(finding, score=4.20, band="MEDIUM", points=8)
        accept_finding(client, finding["id"])

        remediation = open_remediation(client, finding["id"])
        assert remediation["status"] == "ASSIGNED", (
            f"status: expected ASSIGNED, got {remediation['status']}"
        )
        assert_exact_int(remediation["sla_days"], 60, "sla_days")
        assert_instant_equals(remediation["due_at"], "2026-11-07T10:00:00Z", "due_at")
        assert_exact_int(remediation["extension_count"], 0, "extension_count")

        first = success_data(
            client.extend_remediation(remediation["id"], 10, "Vendor patch slipped")
        )
        assert_instant_equals(first["due_at"], "2026-11-17T10:00:00Z", "due_at")
        assert_exact_int(first["extension_count"], 1, "extension_count")

        second = success_data(client.extend_remediation(remediation["id"], 5, "Change freeze"))
        assert_instant_equals(second["due_at"], "2026-11-22T10:00:00Z", "due_at")
        assert_exact_int(second["extension_count"], 2, "extension_count")

        assert_error_id(
            client.extend_remediation(remediation["id"], 5, "One more slip"),
            ERR_EXTENSION_LIMIT_REACHED,
        )

        final = success_data(client.get_remediation(remediation["id"]))
        assert_instant_equals(final["due_at"], "2026-11-22T10:00:00Z", "due_at")
        assert_exact_int(final["extension_count"], 2, "extension_count")
        assert final["overdue_flag"] is False, (
            f"overdue_flag: expected False, got {final['overdue_flag']}"
        )
        assert final["status"] == "ASSIGNED", (
            f"status: expected ASSIGNED, got {final['status']}"
        )

    def test_retest_verification_gates_fire_in_priority_order(self, client):
        """The finder, then the officer, then the noteless failure: three refusals before one verification.

        PRD: "Checks are evaluated in the following order, and the first one that fails ends the request."
        PRD: "When the acting user is a `Tester`, their `X-User-ID` must differ from the finding's `discovered_by_tester_id`, since the tester who found a weakness may not be the one who certifies it fixed, and a self-verification is refused with `ERR_SOD_VERIFIER_CONFLICT`. When the remediation's `validation_requirement` is `RETEST_REQUIRED`, the verifier must be a `Tester`; a `ComplianceOfficer` may only verify remediations whose requirement is `EVIDENCE_ONLY`, and overreach is refused with `ERR_VERIFIER_ROLE_NOT_PERMITTED`. And `residual_note` must be present and non-blank whenever the `outcome` is `FAIL` or `PARTIAL`, refused with `ERR_RESIDUAL_NOTE_REQUIRED`; a `PASS` needs no residual note."
        PRD: "A `FAIL` moves the remediation `SUBMITTED` → `REJECTED` and the finding `REMEDIATION_SUBMITTED` → `RETEST_FAILED`, and then immediately re-opens both: the remediation returns to `ASSIGNED` with its `evidence_uri` and `submitted_at` cleared, and the finding returns to `REMEDIATION_ASSIGNED`, ready for another attempt."

        Design: Corner/validations/retest_verification_gates_fire_in_priority_order
        """
        scenario = build_scenario(client, stage="executing")
        advance_clock(client, T_FIELDWORK_DAY)

        finding = report_finding(client, scenario, **LOW_RISK_MEDIUM)
        assert finding["discovered_by_tester_id"] == scenario["tester_id"], (
            f"discovered_by_tester_id: expected {scenario['tester_id']}, "
            f"got {finding['discovered_by_tester_id']}"
        )
        accept_finding(client, finding["id"])
        remediation = open_remediation(client, finding["id"])
        assert remediation["validation_requirement"] == "RETEST_REQUIRED", (
            "validation_requirement: expected RETEST_REQUIRED, "
            f"got {remediation['validation_requirement']}"
        )
        submitted = submit_evidence(client, remediation["id"])
        assert submitted["status"] == "SUBMITTED", (
            f"status: expected SUBMITTED, got {submitted['status']}"
        )

        independent = created_data(client.create_tester(factories.second_tester_payload()))

        def verify(headers, **overrides):
            return client.create_retest_verification(
                factories.retest_verification_payload(remediation["id"], **overrides),
                headers,
            )

        assert_error_id(
            verify(
                make_tester_headers(scenario["tester_id"]),
                evidence_uri="s3://evidence/retest-1",
            ),
            ERR_SOD_VERIFIER_CONFLICT,
        )
        assert_error_id(
            verify(
                compliance_officer_headers(CO_USER_ID),
                evidence_uri="s3://evidence/retest-2",
                outcome="FAIL",
            ),
            ERR_VERIFIER_ROLE_NOT_PERMITTED,
        )
        assert_error_id(
            verify(
                make_tester_headers(independent["id"]),
                evidence_uri="s3://evidence/retest-3",
                outcome="FAIL",
            ),
            ERR_RESIDUAL_NOTE_REQUIRED,
        )

        verification = created_data(
            verify(
                make_tester_headers(independent["id"]),
                evidence_uri="s3://evidence/retest-4",
                outcome="FAIL",
                residual_note=RESIDUAL_NOTE,
            )
        )
        assert verification["id"], "the accepted verification must carry an identifier"
        assert verification["state"] == "VERIFIED", (
            f"state: expected VERIFIED, got {verification['state']}"
        )
        assert verification["outcome"] == "FAIL", (
            f"outcome: expected FAIL, got {verification['outcome']}"
        )
        assert verification["verifier_tester_id"] == independent["id"], (
            f"verifier_tester_id: expected {independent['id']}, "
            f"got {verification['verifier_tester_id']}"
        )

        reopened = success_data(client.get_remediation(remediation["id"]))
        assert reopened["status"] == "ASSIGNED", (
            f"status: expected ASSIGNED, got {reopened['status']}"
        )
        assert reopened["evidence_uri"] is None, (
            f"evidence_uri: expected null, got {reopened['evidence_uri']}"
        )
        reopened_finding = success_data(client.get_finding(finding["id"]))
        assert reopened_finding["status"] == "REMEDIATION_ASSIGNED", (
            f"status: expected REMEDIATION_ASSIGNED, got {reopened_finding['status']}"
        )

    def test_duplicate_marking_refuses_self_reference_and_duplicate_chains(self, client):
        """A finding may not duplicate itself, and no duplicate may be the parent of another.

        PRD: "It requires `duplicate_of_finding_id` to be present and to resolve to an existing finding; that target must not be the finding being triaged, and a self-reference is refused with `ERR_DUPLICATE_SELF_REFERENCE`; and the target must not itself already be `DUPLICATE`, since duplicate-of-a-duplicate chains are forbidden and are refused with `ERR_DUPLICATE_CHAIN_NOT_ALLOWED`."
        PRD: "On success the supplied identifier is written to the finding's `duplicate_of_finding_id`."

        Design: Corner/validations/duplicate_marking_refuses_self_reference_and_duplicate_chains
        """
        scenario = build_scenario(client, stage="executing")
        advance_clock(client, T_FIELDWORK_DAY)

        first = report_finding(client, scenario, **PARTNER_MEDIUM)
        second = report_finding(
            client, scenario, **dict(PARTNER_MEDIUM, title="Session replay on the mobile client")
        )
        third = report_finding(
            client, scenario, **dict(PARTNER_MEDIUM, title="Session replay on the partner API")
        )
        assert_exact_int(first["version"], 1, "version")
        for row in (first, second, third):
            assert row["status"] == "REPORTED", (
                f"status: expected REPORTED, got {row['status']}"
            )

        assert_error_id(
            client.triage_finding(
                second["id"],
                factories.triage_payload(
                    "MARK_DUPLICATE",
                    note="Same as itself",
                    duplicate_of_finding_id=second["id"],
                ),
            ),
            ERR_DUPLICATE_SELF_REFERENCE,
        )

        marked = success_data(
            client.triage_finding(
                second["id"],
                factories.triage_payload(
                    "MARK_DUPLICATE",
                    note="Same root cause as the first report",
                    duplicate_of_finding_id=first["id"],
                ),
            )
        )
        assert marked["status"] == "DUPLICATE", (
            f"status: expected DUPLICATE, got {marked['status']}"
        )
        assert marked["duplicate_of_finding_id"] == first["id"], (
            f"duplicate_of_finding_id: expected {first['id']}, "
            f"got {marked['duplicate_of_finding_id']}"
        )

        assert_error_id(
            client.triage_finding(
                third["id"],
                factories.triage_payload(
                    "MARK_DUPLICATE",
                    note="Chaining onto a duplicate",
                    duplicate_of_finding_id=second["id"],
                ),
            ),
            ERR_DUPLICATE_CHAIN_NOT_ALLOWED,
        )

        untouched = success_data(client.get_finding(third["id"]))
        assert untouched["status"] == "REPORTED", (
            f"status: expected REPORTED, got {untouched['status']}"
        )
        assert untouched["duplicate_of_finding_id"] is None, (
            f"duplicate_of_finding_id: expected null, "
            f"got {untouched['duplicate_of_finding_id']}"
        )
