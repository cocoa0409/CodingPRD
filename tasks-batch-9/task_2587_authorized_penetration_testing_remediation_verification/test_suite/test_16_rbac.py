"""Who may act: exclusive writes, shared writes, the header ladder and duty boundaries.

The programme's authority model is proved from both sides — the owning role succeeds,
every other role is turned away, and the refusal lands before the request body or the
path identifiers are ever examined.
"""

from test_helpers import (
    assert_error_id,
    assert_exact_int,
    assert_page,
    created_data,
    engagement_version,
    factories,
    make_tester_headers,
    success_data,
    read_plan_version,
)
from test_helpers.api_errors import (
    ERR_ACTOR_NOT_OWNER,
    ERR_INVALID_ROLE,
    ERR_MISSING_AUTH_HEADERS,
    ERR_REMEDIATION_NOT_FOUND,
    ERR_SOD_ROE_SIGNER_CONFLICT,
    ERR_SOD_VERIFIER_CONFLICT,
    ERR_TEST_PLAN_NOT_FOUND,
    ERR_UNAUTHORIZED,
    ERR_VERIFIER_ROLE_NOT_PERMITTED,
)
from test_helpers.test_users import (
    CO_INDEPENDENT_USER_ID,
    OWNER_ALT_USER_ID,
    OWNER_USER_ID,
    PM_DRAFTER_USER_ID,
    UNRECOGNISED_ROLE,
    blank_user_id_headers,
    compliance_officer_headers,
    headers_with_role,
    program_manager_headers,
    remediation_owner_headers,
)

GHOST_FINDING_ID = "00000000-0000-0000-0000-0000000000f1"
GHOST_ENGAGEMENT_ID = "00000000-0000-0000-0000-0000000000e1"
GHOST_REMEDIATION_ID = "00000000-0000-0000-0000-0000000000r1"
GHOST_PLAN_ID = "00000000-0000-0000-0000-0000000000aa"
GHOST_SUBMIT_ID = "00000000-0000-0000-0000-0000000000bb"
T_FIELDWORK_OPENING = "2026-09-08T09:00:00Z"
BOOKING_START = "2026-09-05T00:00:00Z"
BOOKING_END = "2026-09-20T00:00:00Z"
DRAFTER = PM_DRAFTER_USER_ID


class TestExclusiveOperations:
    """Each role's exclusive writes are closed to the other four."""

    def test_every_roles_exclusive_write_is_refused_to_the_other_four_roles(
        self, client, admin, program_manager, compliance_officer, remediation_owner
    ):
        """Five sampled writes are issued under the wrong role and none of them lands.

        PRD: "If the role is recognised but is not among the roles authorised for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED` and HTTP 403 — and that decision is made **before** any identifier in the URL is looked up, so a caller lacking permission who addresses a resource that does not exist receives 403 rather than 404."
        PRD: "**`PlatformAdmin`** — the programme registrar. Owns the asset inventory, the tester roster, background-check recording and the logical clock."
        PRD: "**`ProgramManager`** — runs the annual programme: opening plans, proposing and deciding scope, chartering engagements, drafting rules of engagement, adding authorized targets, requesting testers, provisioning and revoking access, and assigning remediation."
        PRD: "**`Tester`** — a cleared, provisioned penetration tester. The only role that may file findings."
        PRD: "Verification is performed by a `Tester` or, in the narrow `EVIDENCE_ONLY` case, by a `ComplianceOfficer`."

        Design: Corner/rbac/every_roles_exclusive_write_is_refused_to_the_other_four_roles
        """
        asset = created_data(
            client.create_asset(factories.asset_payload(), headers=admin)
        )
        plan = created_data(client.create_test_plan(factories.test_plan_payload()))

        assert_error_id(
            client.create_asset(
                factories.core_network_asset_payload(name="Shadow asset"),
                headers=program_manager,
            ),
            ERR_UNAUTHORIZED,
        )
        assert_error_id(
            client.set_clock("2027-01-01T00:00:00Z", headers=program_manager),
            ERR_UNAUTHORIZED,
        )
        assert_error_id(
            client.create_test_plan(
                factories.test_plan_payload(
                    fiscal_year=2027, risk_appetite_score=50, planned_engagement_count=2
                ),
                headers=compliance_officer,
            ),
            ERR_UNAUTHORIZED,
        )
        assert_error_id(
            client.create_scope_item(
                factories.scope_item_payload(
                    plan["id"],
                    asset["id"],
                    plan["version"],
                    justification="Officer proposing scope",
                    requested_engagement_hours=40,
                ),
                headers=compliance_officer,
            ),
            ERR_UNAUTHORIZED,
        )
        assert_error_id(
            client.create_remediation(
                factories.remediation_payload(
                    GHOST_FINDING_ID,
                    validation_requirement="EVIDENCE_ONLY",
                    remediation_plan="Self-assigned work",
                ),
                headers=remediation_owner,
            ),
            ERR_UNAUTHORIZED,
        )
        assert_error_id(
            client.create_finding(
                factories.finding_payload(
                    GHOST_ENGAGEMENT_ID,
                    asset["id"],
                    plan["version"],
                    title="Manager-filed finding",
                    technical_base_score=5.0,
                ),
                program_manager,
            ),
            ERR_UNAUTHORIZED,
        )
        assert_error_id(
            client.create_retest_verification(
                factories.retest_verification_payload(
                    GHOST_REMEDIATION_ID, evidence_uri="s3://evidence/x"
                ),
                program_manager,
            ),
            ERR_UNAUTHORIZED,
        )

        untouched = success_data(
            client.get_test_plan(plan["id"], headers=compliance_officer)
        )
        assert untouched["status"] == "DRAFT", (
            f"status: expected DRAFT, got {untouched['status']}"
        )
        assert_exact_int(untouched["version"], 1, "version")

        rows, _ = assert_page(
            client.list_assets(
                params={"limit": 10, "offset": 0}, headers=program_manager
            ),
            total_count=1,
            has_more=False,
            row_count=1,
        )
        assert rows[0]["id"] == asset["id"], (
            f"first row: expected {asset['id']}, got {rows[0]['id']}"
        )


class TestAuthorizationLadder:
    """Headers are judged before the path, so the same URL answers four ways."""

    def test_header_and_role_checks_run_before_any_path_id_is_resolved(
        self, client, admin, compliance_officer
    ):
        """One unknown plan id yields 401, 401, 403 and only then 404 as the headers improve.

        PRD: "If either header is absent, empty, or contains only whitespace, the request is rejected with `ERR_MISSING_AUTH_HEADERS` and HTTP 401. If both headers are present but `X-User-Role` is not one of the five recognised role names, the request is rejected with `ERR_INVALID_ROLE`, also HTTP 401. If the role is recognised but is not among the roles authorised for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED` and HTTP 403 — and that decision is made **before** any identifier in the URL is looked up, so a caller lacking permission who addresses a resource that does not exist receives 403 rather than 404."
        PRD: "**Band 1 — authentication and authorization (in this order):** header presence (`ERR_MISSING_AUTH_HEADERS`, 401), then role recognition (`ERR_INVALID_ROLE`, 401), then endpoint permission (`ERR_UNAUTHORIZED`, 403). All three apply to every endpoint."
        PRD: "**Band 2 — path resolution.** Every identifier embedded in the URL is resolved left to right, and the first one that fails to resolve determines the error: `ERR_ASSET_NOT_FOUND`, `ERR_TEST_PLAN_NOT_FOUND`, `ERR_SCOPE_ITEM_NOT_FOUND`, `ERR_ENGAGEMENT_NOT_FOUND`, `ERR_ROE_NOT_FOUND`, `ERR_TARGET_NOT_FOUND`, `ERR_TESTER_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_FINDING_NOT_FOUND`, `ERR_ALERT_NOT_FOUND`, `ERR_REMEDIATION_NOT_FOUND` or `ERR_RETEST_NOT_FOUND`, each with HTTP 404."
        PRD: "**`RemediationOwner`** — the accountable owner of a fix, the only role that may submit remediation evidence."

        Design: Corner/rbac/header_and_role_checks_run_before_any_path_id_is_resolved
        """
        assert_error_id(
            client.activate_test_plan(GHOST_PLAN_ID, headers=blank_user_id_headers()),
            ERR_MISSING_AUTH_HEADERS,
        )
        assert_error_id(
            client.activate_test_plan(
                GHOST_PLAN_ID, headers=headers_with_role("sl-1", UNRECOGNISED_ROLE)
            ),
            ERR_INVALID_ROLE,
        )
        assert_error_id(
            client.activate_test_plan(GHOST_PLAN_ID, headers=compliance_officer),
            ERR_UNAUTHORIZED,
        )
        assert_error_id(
            client.activate_test_plan(GHOST_PLAN_ID), ERR_TEST_PLAN_NOT_FOUND
        )

        assert_error_id(
            client.submit_remediation(
                GHOST_SUBMIT_ID,
                "s3://evidence/ghost",
                headers=program_manager_headers(),
            ),
            ERR_UNAUTHORIZED,
        )
        assert_error_id(
            client.submit_remediation(GHOST_SUBMIT_ID, "s3://evidence/ghost"),
            ERR_REMEDIATION_NOT_FOUND,
        )

        rows, _ = assert_page(
            client.list_test_plans(params={"limit": 10, "offset": 0}, headers=admin),
            total_count=0,
            has_more=False,
            row_count=0,
        )
        assert rows == [], f"test plans: expected no rows, got {rows}"


class TestSharedOperations:
    """Sharing is per endpoint: each shared write accepts its pair and nobody else."""

    def test_operations_declared_shared_accept_both_owners_and_no_third_role(
        self, client, admin, compliance_officer, remediation_owner
    ):
        """Clearance and scope decisions each work from both declared sides and refuse a third.

        PRD: "Recording a background check supplies a `result` of `CLEARED`, `FLAGGED` or `EXPIRED`, and either a `PlatformAdmin` or a `ComplianceOfficer` may record it."
        PRD: "On success the result is written to `background_check_status`, `background_check_at` is stamped with the current instant, and `availability_state` advances `PENDING_CLEARANCE` → `AVAILABLE` (or `SUSPENDED` → `AVAILABLE`, which is how a re-cleared tester rejoins the roster)."
        PRD: "Both a `ProgramManager` and a `ComplianceOfficer` may decide a candidate's fate, supplying a `decision` of `APPROVE`, `DEFER` or `WITHDRAW` together with an optional free-text `note`, and — where the rules demand it — an `override_note`."
        PRD: "Deferring moves a candidate `PROPOSED` → `DEFERRED`, records the supplied `note` in `decision_note`, and drops the candidate out of the ranked population — which means the remaining proposed and approved candidates are renumbered so their ranks stay contiguous."
        PRD: "If the role is recognised but is not among the roles authorised for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED` and HTTP 403 — and that decision is made **before** any identifier in the URL is looked up, so a caller lacking permission who addresses a resource that does not exist receives 403 rather than 404."

        Design: Corner/rbac/operations_declared_shared_accept_both_owners_and_no_third_role
        """
        asset_a = created_data(client.create_asset(factories.asset_payload()))
        asset_b = created_data(
            client.create_asset(factories.analytics_lake_asset_payload())
        )
        plan = created_data(client.create_test_plan(factories.test_plan_payload()))
        candidate_a = created_data(
            client.create_scope_item(
                factories.scope_item_payload(
                    plan["id"], asset_a["id"], read_plan_version(client, plan["id"])
                )
            )
        )
        candidate_b = created_data(
            client.create_scope_item(
                factories.scope_item_payload(
                    plan["id"],
                    asset_b["id"],
                    read_plan_version(client, plan["id"]),
                    justification="Opportunistic look at the analytics estate",
                )
            )
        )

        roster = []
        for name in ("Tester One", "Tester Two", "Tester Three"):
            tester = created_data(
                client.create_tester(factories.tester_payload(full_name=name))
            )
            assert tester["availability_state"] == "PENDING_CLEARANCE", (
                f"availability_state: expected PENDING_CLEARANCE, "
                f"got {tester['availability_state']}"
            )
            roster.append(tester)
        first, second, third = roster

        by_admin = success_data(
            client.record_background_check(first["id"], "CLEARED", headers=admin)
        )
        assert by_admin["background_check_status"] == "CLEARED", (
            f"background_check_status: expected CLEARED, "
            f"got {by_admin['background_check_status']}"
        )
        assert by_admin["availability_state"] == "AVAILABLE", (
            f"availability_state: expected AVAILABLE, got {by_admin['availability_state']}"
        )

        by_officer = success_data(
            client.record_background_check(
                second["id"], "CLEARED", headers=compliance_officer
            )
        )
        assert by_officer["background_check_status"] == "CLEARED", (
            f"background_check_status: expected CLEARED, "
            f"got {by_officer['background_check_status']}"
        )
        assert by_officer["availability_state"] == "AVAILABLE", (
            f"availability_state: expected AVAILABLE, "
            f"got {by_officer['availability_state']}"
        )

        assert_error_id(
            client.record_background_check(
                third["id"], "CLEARED", headers=remediation_owner
            ),
            ERR_UNAUTHORIZED,
        )
        untouched = success_data(client.get_tester(third["id"], headers=admin))
        assert untouched["background_check_status"] == "PENDING", (
            f"background_check_status: expected PENDING, "
            f"got {untouched['background_check_status']}"
        )
        assert untouched["availability_state"] == "PENDING_CLEARANCE", (
            f"availability_state: expected PENDING_CLEARANCE, "
            f"got {untouched['availability_state']}"
        )

        approved = success_data(
            client.decide_scope_item(
                candidate_a["id"],
                factories.decision_payload(
                    "APPROVE", note="Independent assurance approves"
                ),
                headers=compliance_officer,
            )
        )
        assert approved["status"] == "APPROVED", (
            f"status: expected APPROVED, got {approved['status']}"
        )
        assert approved["decision_note"] == "Independent assurance approves", (
            f"decision_note: expected 'Independent assurance approves', "
            f"got {approved['decision_note']!r}"
        )

        deferred = success_data(
            client.decide_scope_item(
                candidate_b["id"],
                factories.decision_payload("DEFER", note="Next fiscal year"),
            )
        )
        assert deferred["status"] == "DEFERRED", (
            f"status: expected DEFERRED, got {deferred['status']}"
        )
        assert deferred["decision_note"] == "Next fiscal year", (
            f"decision_note: expected 'Next fiscal year', "
            f"got {deferred['decision_note']!r}"
        )

        assert_error_id(
            client.decide_scope_item(
                candidate_b["id"],
                factories.decision_payload("APPROVE", note="Admin overruling"),
                headers=admin,
            ),
            ERR_UNAUTHORIZED,
        )
        still_deferred = success_data(client.get_scope_item(candidate_b["id"]))
        assert still_deferred["status"] == "DEFERRED", (
            f"status: expected DEFERRED, got {still_deferred['status']}"
        )


class TestSegregationOfDuties:
    """One operator identity is pushed through four duty boundaries and stopped at each.

    PRD: "Segregation of duties forbids this role from signing a document it drafted or a remediation it owns."
    """

    def test_segregation_of_duties_separates_drafter_signer_owner_and_verifier(
        self, client
    ):
        """The drafter, the wrong owner, the discoverer and an officer are each refused in turn.

        PRD: "The server stamps `drafted_by_user_id` from `X-User-ID`, opens the document at `DRAFT` status, and sets `active_target_count` to 0."
        PRD: "And the signer's `X-User-ID` must differ from the document's `drafted_by_user_id`, or the signature is refused with `ERR_SOD_ROE_SIGNER_CONFLICT`."
        PRD: "Only the recorded owner may submit. A `RemediationOwner` whose `X-User-ID` matches the remediation's `owner_user_id` supplies an `evidence_uri` and moves the remediation `ASSIGNED` → `SUBMITTED`, stamping `submitted_at` with the current instant and recording the evidence pointer; anyone else is refused with `ERR_ACTOR_NOT_OWNER`."
        PRD: "When the acting user is a `Tester`, their `X-User-ID` must differ from the finding's `discovered_by_tester_id`, since the tester who found a weakness may not be the one who certifies it fixed, and a self-verification is refused with `ERR_SOD_VERIFIER_CONFLICT`."
        PRD: "When the remediation's `validation_requirement` is `RETEST_REQUIRED`, the verifier must be a `Tester`; a `ComplianceOfficer` may only verify remediations whose requirement is `EVIDENCE_ONLY`, and overreach is refused with `ERR_VERIFIER_ROLE_NOT_PERMITTED`."

        Design: Corner/rbac/segregation_of_duties_separates_drafter_signer_owner_and_verifier
        """
        drafter = program_manager_headers(DRAFTER)
        asset = created_data(client.create_asset(factories.asset_payload()))
        plan = created_data(
            client.create_test_plan(factories.test_plan_payload(), headers=drafter)
        )
        candidate = created_data(
            client.create_scope_item(
                factories.scope_item_payload(plan["id"], asset["id"], plan["version"]),
                headers=drafter,
            )
        )
        success_data(
            client.decide_scope_item(
                candidate["id"],
                factories.decision_payload("APPROVE", note="In scope"),
                headers=drafter,
            )
        )
        success_data(client.activate_test_plan(plan["id"], headers=drafter))
        engagement = created_data(
            client.create_engagement(
                factories.engagement_payload(plan["id"], candidate["id"]),
                headers=drafter,
            )
        )
        document = created_data(
            client.create_rules_of_engagement(
                factories.rules_of_engagement_payload(engagement["id"]), headers=drafter
            )
        )
        assert document["drafted_by_user_id"] == DRAFTER, (
            f"drafted_by_user_id: expected {DRAFTER}, "
            f"got {document['drafted_by_user_id']}"
        )
        created_data(
            client.create_authorized_target(
                factories.authorized_target_payload(document["id"], asset["id"]),
                headers=drafter,
            )
        )

        assert_error_id(
            client.sign_rules_of_engagement(
                document["id"],
                signature_note="Signing my own draft",
                headers=compliance_officer_headers(DRAFTER),
            ),
            ERR_SOD_ROE_SIGNER_CONFLICT,
        )
        signed = success_data(
            client.sign_rules_of_engagement(
                document["id"],
                signature_note="Independent counter-signature",
                headers=compliance_officer_headers(CO_INDEPENDENT_USER_ID),
            )
        )
        assert signed["status"] == "SIGNED", (
            f"status: expected SIGNED, got {signed['status']}"
        )
        assert signed["signed_by_user_id"] == CO_INDEPENDENT_USER_ID, (
            f"signed_by_user_id: expected {CO_INDEPENDENT_USER_ID}, "
            f"got {signed['signed_by_user_id']}"
        )

        discoverer = created_data(client.create_tester(factories.tester_payload()))
        independent = created_data(
            client.create_tester(factories.tester_payload(full_name="Tester Two"))
        )
        success_data(client.record_background_check(discoverer["id"], "CLEARED"))
        success_data(client.record_background_check(independent["id"], "CLEARED"))

        assignment = created_data(
            client.create_tester_assignment(
                factories.tester_assignment_payload(
                    engagement["id"],
                    discoverer["id"],
                    engagement_version(client, engagement["id"], headers=drafter),
                    [asset["id"]],
                    interval_start=BOOKING_START,
                    interval_end=BOOKING_END,
                ),
                headers=drafter,
            )
        )
        success_data(client.set_access(assignment["id"], "PROVISION", headers=drafter))
        success_data(client.set_clock(T_FIELDWORK_OPENING))
        started = success_data(
            client.drive_execution(engagement["id"], "START", headers=drafter)
        )

        finding = created_data(
            client.create_finding(
                factories.finding_payload(
                    engagement["id"],
                    asset["id"],
                    started["version"],
                    title="Payments IDOR",
                    technical_base_score=6.0,
                ),
                make_tester_headers(discoverer["id"]),
            )
        )
        assert finding["discovered_by_tester_id"] == discoverer["id"], (
            f"discovered_by_tester_id: expected {discoverer['id']}, "
            f"got {finding['discovered_by_tester_id']}"
        )
        success_data(
            client.triage_finding(
                finding["id"],
                factories.triage_payload("ACCEPT", note="Confirmed"),
                headers=drafter,
            )
        )
        remediation = created_data(
            client.create_remediation(
                factories.remediation_payload(
                    finding["id"],
                    owner_user_id=OWNER_USER_ID,
                    validation_requirement="RETEST_REQUIRED",
                ),
                headers=drafter,
            )
        )

        assert_error_id(
            client.submit_remediation(
                remediation["id"],
                "s3://evidence/other-owner",
                headers=remediation_owner_headers(OWNER_ALT_USER_ID),
            ),
            ERR_ACTOR_NOT_OWNER,
        )
        submitted = success_data(
            client.submit_remediation(
                remediation["id"],
                "s3://evidence/fix-1",
                headers=remediation_owner_headers(OWNER_USER_ID),
            )
        )
        assert submitted["status"] == "SUBMITTED", (
            f"status: expected SUBMITTED, got {submitted['status']}"
        )

        assert_error_id(
            client.create_retest_verification(
                factories.retest_verification_payload(
                    remediation["id"], evidence_uri="s3://evidence/self-retest"
                ),
                make_tester_headers(discoverer["id"]),
            ),
            ERR_SOD_VERIFIER_CONFLICT,
        )
        assert_error_id(
            client.create_retest_verification(
                factories.retest_verification_payload(
                    remediation["id"], evidence_uri="s3://evidence/officer-retest"
                ),
                compliance_officer_headers(CO_INDEPENDENT_USER_ID),
            ),
            ERR_VERIFIER_ROLE_NOT_PERMITTED,
        )
        verification = created_data(
            client.create_retest_verification(
                factories.retest_verification_payload(
                    remediation["id"], evidence_uri="s3://evidence/independent-retest"
                ),
                make_tester_headers(independent["id"]),
            )
        )
        assert verification["state"] == "VERIFIED", (
            f"state: expected VERIFIED, got {verification['state']}"
        )
        assert verification["verifier_tester_id"] == independent["id"], (
            f"verifier_tester_id: expected {independent['id']}, "
            f"got {verification['verifier_tester_id']}"
        )
