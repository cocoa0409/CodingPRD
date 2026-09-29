"""Refusal codes: which complaint each stage of the programme raises, and in what order.

Every test here walks a real programme far enough to break one specific rule, then
checks that the answer names that rule rather than a neighbouring one.
"""

from test_helpers import (
    accept_finding,
    advance_clock,
    assert_engagement_axes,
    assert_error_id,
    assert_error_id_in,
    assert_page,
    assert_score,
    build_scenario,
    compliance_officer_headers,
    created_data,
    factories,
    make_tester_headers,
    report_finding,
    success_data,
    read_plan_version,
)
from test_helpers.api_errors import (
    ERR_ALERT_NOT_FOUND,
    ERR_ASSIGNMENT_NOT_FOUND,
    ERR_ENGAGEMENT_NOT_EXECUTING,
    ERR_ENGAGEMENT_NOT_FOUND,
    ERR_ENGAGEMENT_SUSPENDED,
    ERR_FINDING_NOT_FOUND,
    ERR_FINDING_NOT_TRIAGEABLE,
    ERR_FINDING_NOT_TRIAGED,
    ERR_PLAN_NOT_ACTIVE,
    ERR_REMEDIATION_ALREADY_EXISTS,
    ERR_REMEDIATION_NOT_ASSIGNED,
    ERR_REMEDIATION_NOT_FOUND,
    ERR_REMEDIATION_NOT_SUBMITTED,
    ERR_REMEDIATION_NOT_VALIDATED,
    ERR_RESIDUAL_NOTE_REQUIRED,
    ERR_RETEST_ALREADY_SIGNED_OFF,
    ERR_RETEST_NOT_FOUND,
    ERR_ROE_ALREADY_EXISTS,
    ERR_SCOPE_ITEM_NOT_APPROVED,
    ERR_SCOPE_ITEM_NOT_FOUND,
    ERR_SOD_SIGNOFF_CONFLICT,
    ERR_TARGET_NOT_FOUND,
    ERR_TESTER_NOT_FOUND,
)
from test_helpers.test_users import (
    CO_ALT_USER_ID,
    CO_USER_ID,
    OWNER_ALT_USER_ID,
    headers_with_role,
)

T_FIELDWORK_OPENING = "2026-09-08T09:00:00Z"
PAUSE_REASON = "Production incident on the shared platform"
RESIDUAL_NOTE = "The tenant check is still missing on the batch endpoint"
CO_OWNER_HEADERS = headers_with_role(CO_USER_ID, "RemediationOwner")


class TestNotFoundMapping:
    """Each collection answers an unknown identifier with its own not-found code."""

    def test_every_unknown_id_read_returns_its_own_not_found_code(self, client, admin):
        """Nine reads of nine unknown identifiers earn nine distinct 404 codes.

        PRD: "Every identifier embedded in the URL is resolved left to right, and the first one that fails to resolve determines the error: `ERR_ASSET_NOT_FOUND`, `ERR_TEST_PLAN_NOT_FOUND`, `ERR_SCOPE_ITEM_NOT_FOUND`, `ERR_ENGAGEMENT_NOT_FOUND`, `ERR_ROE_NOT_FOUND`, `ERR_TARGET_NOT_FOUND`, `ERR_TESTER_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_FINDING_NOT_FOUND`, `ERR_ALERT_NOT_FOUND`, `ERR_REMEDIATION_NOT_FOUND` or `ERR_RETEST_NOT_FOUND`, each with HTTP 404."
        PRD: "This band applies to every endpoint that has an identifier in its path."
        PRD: "The `message` provides a human-readable explanation of what went wrong."

        Design: Corner/errors/every_unknown_id_read_returns_its_own_not_found_code
        """
        assert_error_id(
            client.get_scope_item("00000000-0000-4000-8000-000000000001"),
            ERR_SCOPE_ITEM_NOT_FOUND,
        )
        assert_error_id(
            client.get_engagement("00000000-0000-4000-8000-000000000002"),
            ERR_ENGAGEMENT_NOT_FOUND,
        )
        assert_error_id(
            client.get_authorized_target("00000000-0000-4000-8000-000000000003"),
            ERR_TARGET_NOT_FOUND,
        )
        assert_error_id(
            client.get_tester(
                "00000000-0000-4000-8000-000000000004", headers=admin
            ),
            ERR_TESTER_NOT_FOUND,
        )
        assert_error_id(
            client.get_tester_assignment("00000000-0000-4000-8000-000000000005"),
            ERR_ASSIGNMENT_NOT_FOUND,
        )
        assert_error_id(
            client.get_finding("00000000-0000-4000-8000-000000000006"),
            ERR_FINDING_NOT_FOUND,
        )
        assert_error_id(
            client.get_critical_alert("00000000-0000-4000-8000-000000000007"),
            ERR_ALERT_NOT_FOUND,
        )
        assert_error_id(
            client.get_remediation("00000000-0000-4000-8000-000000000008"),
            ERR_REMEDIATION_NOT_FOUND,
        )
        assert_error_id(
            client.get_retest_verification("00000000-0000-4000-8000-000000000009"),
            ERR_RETEST_NOT_FOUND,
        )


class TestEngagementCharteringOrder:
    """Chartering complains about the plan before it complains about the candidate."""

    def test_engagement_creation_checks_the_plan_state_before_the_candidate_state(
        self, client
    ):
        """A draft plan with a proposed candidate answers about the plan, not the candidate.

        PRD: "The plan must be `ACTIVE` (`ERR_PLAN_NOT_ACTIVE`, 409) — for engagement creation."
        PRD: "The referenced scope item must be `APPROVED` and must belong to the same plan as the engagement being created (`ERR_SCOPE_ITEM_NOT_APPROVED`, 409)."
        PRD: "Once the plan is `ACTIVE`, a `ProgramManager` charters engagements out of it."

        Design: Corner/errors/engagement_creation_checks_the_plan_state_before_the_candidate_state
        """
        scenario = build_scenario(client, stage="scope_item")
        plan_id = scenario["plan_id"]
        candidate_a = scenario["scope_item"]

        tier_three_asset = created_data(
            client.create_asset(factories.analytics_lake_asset_payload())
        )
        candidate_b = created_data(
            client.create_scope_item(
                factories.scope_item_payload(
                    plan_id,
                    tier_three_asset["id"],
                    read_plan_version(client, plan_id),
                    justification="Opportunistic look at the analytics estate",
                )
            )
        )
        assert candidate_b["status"] == "PROPOSED", (
            f"status: expected PROPOSED, got {candidate_b['status']}"
        )

        assert_error_id(
            client.create_engagement(
                factories.engagement_payload(
                    plan_id, candidate_b["id"], hours_allocated=20
                )
            ),
            ERR_PLAN_NOT_ACTIVE,
        )

        # candidate_a is already APPROVED by the scenario builder; approval is only
        # declared from PROPOSED or DEFERRED, so it is not decided a second time.
        assert candidate_a["status"] == "APPROVED", (
            f"status: expected APPROVED, got {candidate_a['status']}"
        )
        success_data(
            client.decide_scope_item(
                candidate_b["id"], factories.decision_payload("DEFER", note="Next cycle")
            )
        )
        activated = success_data(client.activate_test_plan(plan_id))
        assert activated["status"] == "ACTIVE", (
            f"status: expected ACTIVE, got {activated['status']}"
        )
        assert_score(activated["coverage_score"], 100.00, "coverage_score")

        assert_error_id(
            client.create_engagement(
                factories.engagement_payload(
                    plan_id, candidate_b["id"], hours_allocated=20
                )
            ),
            ERR_SCOPE_ITEM_NOT_APPROVED,
        )

        engagement = created_data(
            client.create_engagement(
                factories.engagement_payload(plan_id, candidate_a["id"])
            )
        )
        assert_engagement_axes(
            engagement, execution_state="PLANNED", authorization_state="ROE_PENDING"
        )
        assert engagement["id"], "id: expected a non-empty identifier, got an empty value"


class TestDocumentUniqueness:
    """One live authorization document per engagement, drafted or signed."""

    def test_a_second_live_rules_of_engagement_document_is_refused(self, client):
        """The second draft is refused while the first is DRAFT and again once it is SIGNED.

        PRD: "An engagement may hold only one live document: if a document for the same engagement already exists at `DRAFT`, `SIGNED` or `SUSPENDED`, the draft is refused with `ERR_ROE_ALREADY_EXISTS`."
        PRD: "Documents can be browsed with optional filters on `engagement_id` and `status`."
        PRD: "no competing rules-of-engagement document for the same engagement may hold `DRAFT`, `SIGNED` or `SUSPENDED` status (`ERR_ROE_ALREADY_EXISTS`, 409)"

        Design: Corner/errors/a_second_live_rules_of_engagement_document_is_refused
        """
        scenario = build_scenario(client, stage="targets")
        engagement_id = scenario["engagement_id"]
        roe_id = scenario["roe_id"]
        assert scenario["roe"]["status"] == "DRAFT", (
            f"status: expected DRAFT, got {scenario['roe']['status']}"
        )

        assert_error_id(
            client.create_rules_of_engagement(
                factories.rules_of_engagement_payload(
                    engagement_id,
                    allowed_techniques=["XSS"],
                    emergency_stop_procedure="Second draft",
                )
            ),
            ERR_ROE_ALREADY_EXISTS,
        )

        signed = success_data(
            client.sign_rules_of_engagement(roe_id, signature_note="Authorized")
        )
        assert signed["status"] == "SIGNED", (
            f"status: expected SIGNED, got {signed['status']}"
        )

        assert_error_id(
            client.create_rules_of_engagement(
                factories.rules_of_engagement_payload(
                    engagement_id,
                    allowed_techniques=["XSS"],
                    emergency_stop_procedure="Third draft",
                )
            ),
            ERR_ROE_ALREADY_EXISTS,
        )

        rows, _ = assert_page(
            client.list_rules_of_engagement(
                params={"engagement_id": engagement_id, "limit": 10, "offset": 0}
            ),
            total_count=1,
            has_more=False,
            row_count=1,
        )
        assert rows[0]["id"] == roe_id, (
            f"first row: expected {roe_id}, got {rows[0]['id']}"
        )


class TestFindingStateGateOrder:
    """A pause speaks louder than a not-yet-started fieldwork phase."""

    def test_a_suspended_engagement_outranks_the_execution_state_gate(self, client):
        """The same report is refused first for not executing, then for the pause.

        PRD: "A `SUSPENDED` engagement rejects the report with `ERR_ENGAGEMENT_SUSPENDED`; an engagement at `ROE_PENDING` or `TERMINATED` rejects it with `ERR_ENGAGEMENT_NOT_AUTHORIZED`; and an engagement whose execution axis is anything other than `EXECUTING` rejects it with `ERR_ENGAGEMENT_NOT_EXECUTING`."
        PRD: "A `PAUSE` is reversible and moves the authorization axis `AUTHORIZED` → `SUSPENDED`, then runs a six-link cascade."
        PRD: "Invoking the stop supplies a `stop_code` of either `PAUSE` or `TERMINATE` and a mandatory `reason`, which is recorded in the engagement's `suspension_reason`."

        Design: Corner/errors/a_suspended_engagement_outranks_the_execution_state_gate
        """
        scenario = build_scenario(client, stage="provisioned")
        engagement_id = scenario["engagement_id"]
        tester_headers = scenario["tester_headers"]
        advance_clock(client, T_FIELDWORK_OPENING)

        before = success_data(client.get_engagement(engagement_id))
        assert_engagement_axes(
            before, execution_state="PLANNED", authorization_state="AUTHORIZED"
        )

        assert_error_id(
            client.create_finding(
                factories.finding_payload(
                    engagement_id,
                    scenario["asset_id"],
                    before["version"],
                    title="Early report",
                    technical_base_score=6.0,
                ),
                tester_headers,
            ),
            ERR_ENGAGEMENT_NOT_EXECUTING,
        )

        paused = success_data(
            client.emergency_stop(engagement_id, "PAUSE", PAUSE_REASON)
        )
        assert_engagement_axes(
            paused, execution_state="PLANNED", authorization_state="SUSPENDED"
        )

        assert_error_id(
            client.create_finding(
                factories.finding_payload(
                    engagement_id,
                    scenario["asset_id"],
                    paused["version"],
                    title="Report during the pause",
                    technical_base_score=6.0,
                ),
                tester_headers,
            ),
            ERR_ENGAGEMENT_SUSPENDED,
        )

        rows, _ = assert_page(
            client.list_findings(
                params={"engagement_id": engagement_id, "limit": 10, "offset": 0}
            ),
            total_count=0,
            has_more=False,
            row_count=0,
        )
        assert rows == [], f"findings: expected no rows, got {rows}"


class TestRemediationSequenceGates:
    """Every out-of-order call along the remediation chain names its own stage."""

    def test_the_remediation_lifecycle_refuses_every_out_of_order_call(self, client):
        """Five state codes fall out of one walk from a reported finding to a validated fix.

        PRD: "Remediation assignment requires the finding to be `TRIAGED`, and moving an engagement to reported requires that no finding of that engagement is still `REPORTED` (`ERR_FINDING_NOT_TRIAGED`, 409)."
        PRD: "A triage action that does not fit the finding's current status — accepting something already triaged, revoking an acceptance that was never granted — is refused with `ERR_FINDING_NOT_TRIAGEABLE`."
        PRD: "A finding may hold only one live remediation: if another remediation on the same finding exists in any status other than `CLOSED`, the assignment is refused with `ERR_REMEDIATION_ALREADY_EXISTS`."
        PRD: "Submission and extension require the remediation to be `ASSIGNED` (`ERR_REMEDIATION_NOT_ASSIGNED`, 409)."
        PRD: "Recording a retest verification requires the remediation to be `SUBMITTED` (`ERR_REMEDIATION_NOT_SUBMITTED`, 409)."

        Design: Corner/errors/the_remediation_lifecycle_refuses_every_out_of_order_call
        """
        scenario = build_scenario(client, stage="executing")
        first = report_finding(client, scenario)
        second = report_finding(client, scenario, secondary=True)
        accept_finding(client, first["id"])
        verifier = created_data(client.create_tester(factories.second_tester_payload()))
        verifier_headers = make_tester_headers(verifier["id"])

        assert (
            success_data(client.get_finding(second["id"]))["status"] == "REPORTED"
        ), "status: expected REPORTED for the untriaged finding"
        assert success_data(client.get_finding(first["id"]))["status"] == "TRIAGED", (
            "status: expected TRIAGED for the accepted finding"
        )

        assert_error_id(
            client.create_remediation(
                factories.remediation_payload(
                    second["id"],
                    validation_requirement="EVIDENCE_ONLY",
                    remediation_plan="Suppress stack traces",
                )
            ),
            ERR_FINDING_NOT_TRIAGED,
        )

        assert_error_id(
            client.triage_finding(
                first["id"], factories.triage_payload("ACCEPT", note="Confirming again")
            ),
            ERR_FINDING_NOT_TRIAGEABLE,
        )

        remediation = created_data(
            client.create_remediation(
                factories.remediation_payload(
                    first["id"],
                    validation_requirement="EVIDENCE_ONLY",
                    remediation_plan="Add server-side authorization checks",
                )
            )
        )
        assert remediation["status"] == "ASSIGNED", (
            f"status: expected ASSIGNED, got {remediation['status']}"
        )

        # The first assignment carried the finding to REMEDIATION_ASSIGNED, so the
        # competing request breaks both the live-remediation rule and the
        # finding-must-be-TRIAGED precondition. The requirements name both refusals
        # without stating which of the two answers here, so either is accepted.
        assert_error_id_in(
            client.create_remediation(
                factories.remediation_payload(
                    first["id"],
                    owner_user_id=OWNER_ALT_USER_ID,
                    validation_requirement="EVIDENCE_ONLY",
                    remediation_plan="Competing plan",
                )
            ),
            [ERR_REMEDIATION_ALREADY_EXISTS, ERR_FINDING_NOT_TRIAGED],
        )

        submitted = success_data(
            client.submit_remediation(remediation["id"], "s3://evidence/fix-1")
        )
        assert submitted["status"] == "SUBMITTED", (
            f"status: expected SUBMITTED, got {submitted['status']}"
        )

        assert_error_id(
            client.submit_remediation(remediation["id"], "s3://evidence/fix-1-again"),
            ERR_REMEDIATION_NOT_ASSIGNED,
        )
        assert_error_id(
            client.extend_remediation(remediation["id"], 5, "Needs more time"),
            ERR_REMEDIATION_NOT_ASSIGNED,
        )

        verification = created_data(
            client.create_retest_verification(
                factories.retest_verification_payload(
                    remediation["id"], evidence_uri="s3://evidence/retest-1"
                ),
                verifier_headers,
            )
        )
        assert verification["state"] == "VERIFIED", (
            f"state: expected VERIFIED, got {verification['state']}"
        )

        assert_error_id(
            client.create_retest_verification(
                factories.retest_verification_payload(
                    remediation["id"], evidence_uri="s3://evidence/retest-2"
                ),
                verifier_headers,
            ),
            ERR_REMEDIATION_NOT_SUBMITTED,
        )
        assert (
            success_data(client.get_remediation(remediation["id"]))["status"]
            == "VALIDATED"
        ), "status: expected VALIDATED after the passing verification"


class TestClosureSignoffGates:
    """Closure is attacked from four angles and refuses each in the declared order."""

    def test_closure_signoff_refuses_a_failed_retest_a_superseded_row_and_the_owner(
        self, client
    ):
        """A failed retest, its superseded row and the owner's own signature are all turned away.

        PRD: "And `residual_note` must be present and non-blank whenever the `outcome` is `FAIL` or `PARTIAL`, refused with `ERR_RESIDUAL_NOTE_REQUIRED`; a `PASS` needs no residual note."
        PRD: "A `FAIL` moves the remediation `SUBMITTED` → `REJECTED` and the finding `REMEDIATION_SUBMITTED` → `RETEST_FAILED`, and then immediately re-opens both: the remediation returns to `ASSIGNED` with its `evidence_uri` and `submitted_at` cleared, and the finding returns to `REMEDIATION_ASSIGNED`, ready for another attempt."
        PRD: "Submission carries the finding along, moving it `REMEDIATION_ASSIGNED` → `REMEDIATION_SUBMITTED`, and it also tidies history: every earlier verification of this remediation that is still sitting at `VERIFIED` state is moved to `SUPERSEDED`, so only the verification of the latest evidence bundle can ever be signed off."
        PRD: "Signing off supplies a mandatory `closure_note` and requires three things: the verification must still be at `VERIFIED` state, and one already `SIGNED_OFF` or `SUPERSEDED` is refused with `ERR_RETEST_ALREADY_SIGNED_OFF`; the verification's `outcome` must be `PASS` with its remediation at `VALIDATED`, and anything else is refused with `ERR_REMEDIATION_NOT_VALIDATED`; and the signer's `X-User-ID` must differ from the remediation's `owner_user_id`, with a self-sign-off refused by `ERR_SOD_SIGNOFF_CONFLICT`."
        PRD: "On success the verification moves `VERIFIED` → `SIGNED_OFF`, stamping `signed_off_by_user_id` from the header, `signed_off_at` from the current instant, and the supplied `closure_note`."
        PRD: "Because the remediation is closed, its finding moves `RETEST_PASSED` → `CLOSED` with `closed_at` stamped from the current instant."

        Design: Corner/errors/closure_signoff_refuses_a_failed_retest_a_superseded_row_and_the_owner
        """
        scenario = build_scenario(client, stage="executing")
        finding = report_finding(client, scenario)
        accept_finding(client, finding["id"])
        remediation = created_data(
            client.create_remediation(
                factories.remediation_payload(
                    finding["id"],
                    owner_user_id=CO_USER_ID,
                    validation_requirement="EVIDENCE_ONLY",
                )
            )
        )
        success_data(
            client.submit_remediation(
                remediation["id"], "s3://evidence/fix-1", headers=CO_OWNER_HEADERS
            )
        )
        verifier = compliance_officer_headers(CO_ALT_USER_ID)

        assert_error_id(
            client.create_retest_verification(
                factories.retest_verification_payload(
                    remediation["id"],
                    evidence_uri="s3://evidence/retest-1",
                    outcome="FAIL",
                ),
                verifier,
            ),
            ERR_RESIDUAL_NOTE_REQUIRED,
        )

        failed = created_data(
            client.create_retest_verification(
                factories.retest_verification_payload(
                    remediation["id"],
                    evidence_uri="s3://evidence/retest-1",
                    outcome="FAIL",
                    residual_note=RESIDUAL_NOTE,
                ),
                verifier,
            )
        )
        assert failed["state"] == "VERIFIED", (
            f"state: expected VERIFIED, got {failed['state']}"
        )

        assert_error_id(
            client.sign_off_retest_verification(
                failed["id"],
                "Trying to close a failed retest",
                headers=verifier,
            ),
            ERR_REMEDIATION_NOT_VALIDATED,
        )
        assert (
            success_data(client.get_remediation(remediation["id"]))["status"]
            == "ASSIGNED"
        ), "status: expected ASSIGNED after the failed retest re-opened the fix"

        success_data(
            client.submit_remediation(
                remediation["id"], "s3://evidence/fix-2", headers=CO_OWNER_HEADERS
            )
        )
        superseded = success_data(
            client.get_retest_verification(failed["id"], headers=verifier)
        )
        assert superseded["state"] == "SUPERSEDED", (
            f"state: expected SUPERSEDED, got {superseded['state']}"
        )

        assert_error_id(
            client.sign_off_retest_verification(
                failed["id"],
                "Trying to close a superseded row",
                headers=verifier,
            ),
            ERR_RETEST_ALREADY_SIGNED_OFF,
        )

        passed = created_data(
            client.create_retest_verification(
                factories.retest_verification_payload(
                    remediation["id"], evidence_uri="s3://evidence/retest-2"
                ),
                verifier,
            )
        )

        assert_error_id(
            client.sign_off_retest_verification(
                passed["id"],
                "Owner signing their own closure",
                headers=compliance_officer_headers(CO_USER_ID),
            ),
            ERR_SOD_SIGNOFF_CONFLICT,
        )

        signed_off = success_data(
            client.sign_off_retest_verification(
                passed["id"], "Independent closure accepted", headers=verifier
            )
        )
        assert signed_off["state"] == "SIGNED_OFF", (
            f"state: expected SIGNED_OFF, got {signed_off['state']}"
        )
        assert signed_off["signed_off_by_user_id"] == CO_ALT_USER_ID, (
            f"signed_off_by_user_id: expected {CO_ALT_USER_ID}, "
            f"got {signed_off['signed_off_by_user_id']}"
        )
        closed = success_data(client.get_finding(finding["id"], headers=verifier))
        assert closed["status"] == "CLOSED", (
            f"status: expected CLOSED, got {closed['status']}"
        )

        assert_error_id(
            client.sign_off_retest_verification(
                passed["id"], "Second closure attempt", headers=verifier
            ),
            ERR_RETEST_ALREADY_SIGNED_OFF,
        )
