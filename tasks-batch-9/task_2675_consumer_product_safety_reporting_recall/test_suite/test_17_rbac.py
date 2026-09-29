"""Who may act, who may not, and the two gates that read a stored user id."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_field_values,
    assert_fields_null,
    assert_unchanged,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    AUDITOR_HEADERS,
    COUNSEL_HEADERS,
    DIRECTOR_ALT_HEADERS,
    DIRECTOR_HEADERS,
    INTAKE_HEADERS,
    OFFICER_HEADERS,
    make_headers,
    make_retailer_rep_headers,
)

# A role string outside the seven the service declares.
UNDECLARED_ROLE = "AuditorGeneral"

# The second storefront enrolled alongside the default retailer, so that one
# retailer's representative has a foreign notification to reach for.
SECOND_RETAILER = {
    "name": "CornerHome Hardware",
    "channel_type": "SPECIALTY",
    "store_count": 4,
}

# A determination the penalty attorney has no business recording.
COUNSEL_DETERMINATION = {
    "determination": "NOT_REPORTABLE",
    "defect_score": 1,
    "risk_score": 1,
    "determination_note": "Counsel attempting to reopen a closed determination.",
}


class TestExclusiveOperationsAreRefusedToPeerRoles:
    """The seven roles are peers, so every denial is mutual rather than ranked."""

    def test_each_peer_role_is_refused_the_operations_another_role_owns(self, api):
        """Intake, the auditor, the officer and the officer again are each refused.

        The contract states: "When the headers are well formed but the named role
        does not appear in the authorised-role list for the endpoint being called
        (see the table in §4), the request is rejected with
        `ERR_ROLE_NOT_PERMITTED` (HTTP 403)." The table itself states: "The
        "Authorized Role(s)" column is exhaustive: a syntactically valid request
        from a role not listed for that endpoint is refused with
        `ERR_ROLE_NOT_PERMITTED`."

        Design: Corner/rbac/roles_cannot_perform_each_others_exclusive_operations
        """
        env = fx.submitted_recall_env(api)

        # Registering a product model belongs to the ProgramAdmin alone.
        validate_error(
            api.create_product_model(
                f.product_model_payload(model_code="KETTLE-Z9", units_distributed=10),
                headers=INTAKE_HEADERS,
            ),
            "ERR_ROLE_NOT_PERMITTED",
            403,
        )

        # Signing off a submitted plan belongs to the SafetyDirector alone.
        validate_error(
            api.approve_plan(env["recall_id"], headers=AUDITOR_HEADERS),
            "ERR_ROLE_NOT_PERMITTED",
            403,
        )

        # Closure is likewise the signing official's, not the case officer's.
        validate_error(
            api.close_recall(env["recall_id"], headers=OFFICER_HEADERS),
            "ERR_ROLE_NOT_PERMITTED",
            403,
        )

        # The penalty docket belongs to PenaltyCounsel alone.
        validate_error(
            api.create_penalty_case(
                f.penalty_case_payload(env["report_id"], violation_count=2),
                headers=OFFICER_HEADERS,
            ),
            "ERR_ROLE_NOT_PERMITTED",
            403,
        )

        after = fx.get_recall(api, env["recall_id"])
        assert_field_values(after, plan_status="SUBMITTED", submitted_by_user_id="co-1")
        assert_fields_null(after, "stop_sale_effective_at")

    def test_even_the_safety_director_cannot_register_a_retailer(self, api):
        """The role holding the most operations still has no registry key.

        The contract states: "A `ProgramAdmin` is the registry custodian: it owns
        the reference data the whole docket hangs off — product models and
        retailers — and it owns the logical clock, but it takes no substantive
        safety decision." The endpoint table lists `ProgramAdmin` alone against
        the retailer registry, and "The "Authorized Role(s)" column is
        exhaustive: a syntactically valid request from a role not listed for that
        endpoint is refused with `ERR_ROLE_NOT_PERMITTED`."

        Design: Corner/rbac/roles_cannot_perform_each_others_exclusive_operations
        """
        validate_error(
            api.create_retailer(
                f.retailer_payload(**SECOND_RETAILER), headers=DIRECTOR_HEADERS
            ),
            "ERR_ROLE_NOT_PERMITTED",
            403,
        )

    def test_role_refusal_precedes_the_terminal_state_of_the_evaluation(self, api):
        """Counsel touching a closed determination hears 403, never the state error.

        The contract states: "When a single request violates more than one rule,
        exactly one error is reported: the violation that comes first in the fixed
        ordering below." That ordering opens "**Authentication** — both headers
        present and non-empty, and `X-User-Role` a declared role, else
        `ERR_UNAUTHENTICATED`", then "**Role permission** — the acting role
        appears in the called endpoint's authorised-role list, else
        `ERR_ROLE_NOT_PERMITTED`", and only later "**Own-state precondition** —
        the target row's own state field permits the requested transition, else
        that entity's state error".

        Design: Corner/rbac/roles_cannot_perform_each_others_exclusive_operations
        """
        env = fx.submitted_recall_env(api)
        before = fx.get_evaluation(api, env["evaluation_id"])
        assert_field_values(before, status="REPORTABLE")

        validate_error(
            api.determine_evaluation(
                env["evaluation_id"],
                f.determination_payload(**COUNSEL_DETERMINATION),
                headers=COUNSEL_HEADERS,
            ),
            "ERR_ROLE_NOT_PERMITTED",
            403,
        )

        after = fx.get_evaluation(api, env["evaluation_id"])
        assert_field_values(
            after, status="REPORTABLE", defect_score=8, risk_score=7
        )
        assert_unchanged(before, after, "version", "determined_at", "report_due_at")

    def test_an_undeclared_role_or_an_empty_user_id_is_an_authentication_failure(
        self, api
    ):
        """A missing principal is 401, not 403 — there is nobody to authorise.

        The contract states: "Every request to the service — reads included — must
        carry two headers: `X-User-ID`, identifying the acting principal, and
        `X-User-Role`, naming the role that principal is acting in. If either
        header is absent or empty, or if `X-User-Role` does not name one of the
        seven roles defined below, the request is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401). An unrecognised role string is
        deliberately treated as a failure of authentication rather than of
        authorisation, because the server has no principal to authorise."

        Design: Corner/rbac/roles_cannot_perform_each_others_exclusive_operations
        """
        env = fx.submitted_recall_env(api)
        payload = f.incident_payload(
            env["model_id"],
            report_channel="WEB_FORM",
            incident_date="2026-02-20T00:00:00Z",
            narrative="Filed by a principal the service cannot authorise.",
        )

        validate_error(
            api.create_incident(
                payload, headers=make_headers("ag-1", UNDECLARED_ROLE)
            ),
            "ERR_UNAUTHENTICATED",
            401,
        )
        validate_error(
            api.create_incident(payload, headers=make_headers("", "IntakeSpecialist")),
            "ERR_UNAUTHENTICATED",
            401,
        )
        validate_error(
            api.create_incident(
                payload,
                headers={"X-User-ID": "intake-1", "Content-Type": "application/json"},
            ),
            "ERR_UNAUTHENTICATED",
            401,
        )

        rows, meta = validate_paginated(
            api.list_incidents({"product_model_id": env["model_id"]}, OFFICER_HEADERS)
        )
        assert meta["total_count"] == 3, (
            "no refused intake call may write an incident row"
        )
        assert len(rows) == 3, rows


class TestSharedOperationsAreOpenToEveryDeclaredHolder:
    """Where two roles are listed against one endpoint, both must succeed."""

    def test_the_compliance_officer_acknowledges_on_a_retailers_behalf(self, api):
        """An officer acknowledgement is accepted and is not scoped to a retailer.

        The contract states: "A `RetailerRep` may only acknowledge a notification
        whose `retailer_id` equals its own `X-User-ID`, per §2.1; a
        `ComplianceOfficer` may acknowledge on a retailer's behalf." It also
        states: "It stamps `acknowledged_at` with the logical clock and records
        `units_on_shelf_reported`."

        Design: Corner/rbac/shared_operations_are_open_to_every_declared_holder
        """
        env = fx.approved_recall_env(api)
        assert_field_values(env["notification"], status="ISSUED")

        acknowledged = validate_success(
            api.acknowledge_notification(
                env["notification_id"],
                f.acknowledge_payload(units_on_shelf_reported=0),
                headers=OFFICER_HEADERS,
            )
        )
        assert_field_values(
            acknowledged, status="ACKNOWLEDGED", units_on_shelf_reported=0
        )
        assert acknowledged["acknowledged_at"] is not None

    def test_an_audit_visit_may_be_scheduled_by_the_auditor_or_by_the_director(
        self, api
    ):
        """Both declared holders open a visit, and completion stays the auditor's.

        The contract states: "A `FieldAuditor` or `SafetyDirector` schedules an
        on-site inspection by naming the `retailer_notification_id` whose
        stop-sale instruction the visit verifies, together with a `window_start`
        and a `window_end`." It also states: "Completing a visit is a
        `FieldAuditor`-only act."

        Design: Corner/rbac/shared_operations_are_open_to_every_declared_holder
        """
        director_env = fx.approved_recall_env(api)
        director_visit = validate_success(
            api.create_audit_visit(
                f.audit_visit_payload(director_env["notification_id"]),
                headers=DIRECTOR_HEADERS,
            ),
            201,
        )
        assert_field_values(director_visit, status="SCHEDULED", verdict="PENDING")

        completed = validate_success(
            api.complete_audit_visit(
                director_visit["id"],
                f.complete_visit_payload(verdict="PASS", shelf_units_found=0),
                headers=AUDITOR_HEADERS,
            )
        )
        assert_field_values(
            completed, status="COMPLETED", verdict="PASS", shelf_units_found=0
        )

        auditor_env = fx.approved_recall_env(api)
        auditor_visit = validate_success(
            api.create_audit_visit(
                f.audit_visit_payload(auditor_env["notification_id"]),
                headers=AUDITOR_HEADERS,
            ),
            201,
        )
        assert_field_values(auditor_visit, status="SCHEDULED", verdict="PENDING")

    def test_shelf_removal_is_verifiable_by_the_director_and_by_the_auditor(self, api):
        """The same signature is accepted from either declared holder.

        The contract states: "Verifying shelf removal — the act of a
        `SafetyDirector` or `FieldAuditor` — advances the notification
        `ACKNOWLEDGED → VERIFIED` and stamps `verified_at` with the logical
        clock." It also states: "On the retailer, `open_stop_sale_count` is
        decremented by 1 and `verified_removal_count` is incremented by 1, and
        `compliance_posture` is set to `CLEAR` when `open_stop_sale_count`
        reaches 0."

        Design: Corner/rbac/shared_operations_are_open_to_every_declared_holder
        """
        for signer in (DIRECTOR_HEADERS, AUDITOR_HEADERS):
            env = fx.approved_recall_env(api)
            fx.acknowledge_notification(
                api, env["notification_id"], units_on_shelf_reported=0
            )
            fx.passing_visit(api, env["notification_id"])

            verified = validate_success(
                api.verify_notification(env["notification_id"], headers=signer)
            )
            assert_field_values(verified, status="VERIFIED")
            assert verified["verified_at"] is not None

            retailer = fx.get_retailer(api, env["retailer_id"])
            assert_field_values(
                retailer,
                open_stop_sale_count=0,
                verified_removal_count=1,
                compliance_posture="CLEAR",
            )

    def test_the_compliance_officer_may_run_a_sweep_that_finds_nothing(self, api):
        """An officer sweep over a satisfied recall answers 200 and flips nothing.

        The contract states: "A sweep is a query-and-mark capability over one
        recall's notifications, available to a `SafetyDirector` or
        `ComplianceOfficer`, and it requires the recall's `plan_status` to be
        `APPROVED` or `MONITORING`, otherwise `ERR_RECALL_PLAN_STATE_INVALID`."
        It also states: "A sweep that finds nothing newly overdue changes nothing
        and is still answered successfully — it is a scan, not a state transition
        on the recall itself, and it always answers with the recall record."

        Design: Corner/rbac/shared_operations_are_open_to_every_declared_holder
        """
        env = fx.satisfied_notification_env(api)
        before = fx.get_recall(api, env["recall_id"])
        assert_field_values(
            before, plan_status="MONITORING", notification_status="SATISFIED"
        )

        swept = validate_success(
            api.compliance_sweep(env["recall_id"], headers=OFFICER_HEADERS)
        )
        assert_field_values(
            swept, plan_status="MONITORING", notification_status="SATISFIED"
        )
        assert_unchanged(before, swept, "version", "notification_status")

        notification = fx.get_notification(api, env["notification_id"])
        assert_field_values(notification, status="VERIFIED")
        retailer = fx.get_retailer(api, env["retailer_id"])
        assert_field_values(retailer, delinquent_count=0, compliance_posture="CLEAR")

    def test_the_safety_director_may_also_run_the_sweep(self, api):
        """The other declared holder of the sweep is accepted on the same recall.

        The contract states: "A sweep is a query-and-mark capability over one
        recall's notifications, available to a `SafetyDirector` or
        `ComplianceOfficer`, and it requires the recall's `plan_status` to be
        `APPROVED` or `MONITORING`, otherwise `ERR_RECALL_PLAN_STATE_INVALID`."
        It also states: "a notification whose `ack_due_at` exactly equals the
        current clock reading is not yet overdue and is left alone."

        Design: Corner/rbac/shared_operations_are_open_to_every_declared_holder
        """
        env = fx.approved_recall_env(api)

        swept = validate_success(
            api.compliance_sweep(env["recall_id"], headers=DIRECTOR_HEADERS)
        )
        assert_field_values(
            swept, plan_status="APPROVED", notification_status="IN_PROGRESS"
        )

        notification = fx.get_notification(api, env["notification_id"])
        assert_field_values(notification, status="ISSUED")

    def test_the_program_admin_owns_the_clock_and_both_registries(self, api):
        """All three ProgramAdmin operations succeed under the ProgramAdmin.

        The contract states: "A `ProgramAdmin` is the registry custodian: it owns
        the reference data the whole docket hangs off — product models and
        retailers — and it owns the logical clock, but it takes no substantive
        safety decision." It also states: "A `ProgramAdmin`-only administrative
        capability, mounted outside the business prefix at
        `/_clock/set_current_utc`, replaces the clock value with a supplied
        instant given as `to_iso8601` and answers with the new value as
        `current_utc`."

        Design: Corner/rbac/shared_operations_are_open_to_every_declared_holder
        """
        clock = validate_success(
            api.set_clock("2026-03-01T00:00:00Z", headers=ADMIN_HEADERS)
        )
        assert str(clock["current_utc"]).startswith("2026-03-01T00:00:00"), clock

        model = validate_success(
            api.create_product_model(
                f.product_model_payload(model_code="TOAST-ADMIN-1"),
                headers=ADMIN_HEADERS,
            ),
            201,
        )
        assert_field_values(model, hazard_posture="MONITORED", open_escalation_count=0)

        retailer = validate_success(
            api.create_retailer(
                f.retailer_payload(**SECOND_RETAILER), headers=ADMIN_HEADERS
            ),
            201,
        )
        assert_field_values(
            retailer,
            compliance_posture="CLEAR",
            open_stop_sale_count=0,
            verified_removal_count=0,
            delinquent_count=0,
        )


def _plan_filed_by_the_signing_director(api):
    """A drafted recall whose plan the director dir-1 personally submitted."""
    env = fx.draft_recall_env(api)
    env["recall"] = validate_success(
        api.submit_plan(env["recall_id"], headers=DIRECTOR_HEADERS)
    )
    return env


def _report_prepared_by_the_alternate_director(api):
    """A filed monthly report opened by dir-2 on a plan dir-1 filed and dir-2 signed."""
    env = _plan_filed_by_the_signing_director(api)
    env["recall"] = validate_success(
        api.approve_plan(env["recall_id"], headers=DIRECTOR_ALT_HEADERS)
    )
    opened = validate_success(
        api.create_progress_report(
            f.progress_report_payload(
                env["recall_id"],
                period_start=env["recall"]["stop_sale_effective_at"],
                period_end="2026-04-12T00:00:00Z",
                effectiveness_basis="UNITS_BASIS",
            ),
            headers=DIRECTOR_ALT_HEADERS,
        ),
        201,
    )
    env["progress_report"] = validate_success(
        api.submit_progress_report(opened["id"], headers=DIRECTOR_ALT_HEADERS)
    )
    env["progress_report_id"] = opened["id"]
    return env


class TestSegregationOfDutiesIsScopedToTheStoredIdentity:
    """Both gates compare a stored user id, so a second holder of the role passes."""

    def test_the_director_who_filed_the_plan_cannot_approve_it(self, api):
        """dir-1 files the plan and dir-1 is then refused its own signature.

        The contract states: "When a recall plan is submitted, the acting
        `X-User-ID` is stored as `submitted_by_user_id` on the recall. Approving
        that plan requires an acting `X-User-ID` different from the stored
        `submitted_by_user_id`; an equal value is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)." It also states: "Two gates
        implement this, and both compare **stored operator identifiers**, not
        roles: a `SafetyDirector` who personally filed a plan still cannot approve
        that plan."

        Design: Corner/rbac/same_user_cannot_approve_what_they_filed_or_accept_what_they_prepared
        """
        env = _plan_filed_by_the_signing_director(api)
        assert_field_values(
            env["recall"], plan_status="SUBMITTED", submitted_by_user_id="dir-1"
        )

        validate_error(
            api.approve_plan(env["recall_id"], headers=DIRECTOR_HEADERS),
            "ERR_SEGREGATION_OF_DUTIES",
            403,
        )

        after = fx.get_recall(api, env["recall_id"])
        assert_field_values(
            after, plan_status="SUBMITTED", notification_status="NOT_STARTED"
        )
        assert_fields_null(after, "stop_sale_effective_at")
        notification = fx.get_notification(api, env["notification_id"])
        assert_field_values(
            notification, status="PENDING", stop_sale_required=False
        )
        retailer = fx.get_retailer(api, env["retailer_id"])
        assert_field_values(
            retailer, open_stop_sale_count=0, compliance_posture="CLEAR"
        )

    def test_a_second_director_approves_the_very_same_plan(self, api):
        """dir-2 signs what dir-1 filed, so the gate is identity and not role.

        The contract states: "This is precisely why the filing steps are shared
        between `ComplianceOfficer` and `SafetyDirector` — the same user can reach
        both sides of a gate and be refused by identity rather than by
        permission." It also states: "The first link advances `plan_status`
        `SUBMITTED → APPROVED` and stamps `stop_sale_effective_at` with the
        logical clock."

        Design: Corner/rbac/same_user_cannot_approve_what_they_filed_or_accept_what_they_prepared
        """
        env = _plan_filed_by_the_signing_director(api)

        approved = validate_success(
            api.approve_plan(env["recall_id"], headers=DIRECTOR_ALT_HEADERS)
        )
        assert_field_values(
            approved,
            plan_status="APPROVED",
            notification_status="IN_PROGRESS",
            submitted_by_user_id="dir-1",
        )
        assert str(approved["stop_sale_effective_at"]).startswith(
            "2026-03-13T00:00:00"
        ), approved["stop_sale_effective_at"]

    def test_the_director_who_prepared_the_report_cannot_accept_it(self, api):
        """dir-2 opens the monthly report and dir-2 is refused its acceptance.

        The contract states: "When a monthly progress report is opened, the acting
        `X-User-ID` is stored as `prepared_by_user_id` on the report. Accepting
        that report requires an acting `X-User-ID` different from the stored
        `prepared_by_user_id`, and an equal value is likewise rejected with
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/same_user_cannot_approve_what_they_filed_or_accept_what_they_prepared
        """
        env = _report_prepared_by_the_alternate_director(api)
        assert_field_values(
            env["progress_report"],
            status="SUBMITTED",
            prepared_by_user_id="dir-2",
        )
        assert env["recall"]["submitted_by_user_id"] == "dir-1", (
            "the two gates must read two different stored fields"
        )

        validate_error(
            api.accept_progress_report(
                env["progress_report_id"], headers=DIRECTOR_ALT_HEADERS
            ),
            "ERR_SEGREGATION_OF_DUTIES",
            403,
        )

        after = fx.get_progress_report(api, env["progress_report_id"])
        assert_field_values(after, status="SUBMITTED")
        assert_fields_null(after, "accepted_at")
        recall = fx.get_recall(api, env["recall_id"])
        assert_field_values(recall, effectiveness_flag="PENDING")
        assert_fields_null(recall, "last_accepted_period_end")

    def test_the_plan_filer_may_still_accept_a_report_they_did_not_prepare(self, api):
        """dir-1 filed the plan and may nonetheless accept dir-2's report.

        The contract states: "These two operations are the entire scope of the
        rule; no other approval in the system compares operator identifiers." It
        also states: "Acceptance also writes back to the recall:
        `last_accepted_period_end` is set to this report's `period_end`, and when
        the accepted report's `assessment` is `CRITICAL` the recall's
        `effectiveness_flag` is set to `SHORTFALL`."

        Design: Corner/rbac/same_user_cannot_approve_what_they_filed_or_accept_what_they_prepared
        """
        env = _report_prepared_by_the_alternate_director(api)
        assert_field_values(
            env["progress_report"], assessment="CRITICAL", cumulative_units_corrected=0
        )

        accepted = validate_success(
            api.accept_progress_report(
                env["progress_report_id"], headers=DIRECTOR_HEADERS
            )
        )
        assert_field_values(accepted, status="ACCEPTED", prepared_by_user_id="dir-2")
        assert accepted["accepted_at"] is not None

        recall = fx.get_recall(api, env["recall_id"])
        assert_field_values(
            recall, effectiveness_flag="SHORTFALL", submitted_by_user_id="dir-1"
        )
        assert recall["last_accepted_period_end"] == accepted["period_end"], (
            recall["last_accepted_period_end"]
        )


def _stop_sale_at_two_retailers(api):
    """An approved recall whose stop-sale reached two separately enrolled retailers."""
    env = fx.draft_recall_env(api)
    second = fx.create_retailer(api, **SECOND_RETAILER)
    second_notification = fx.create_notification(api, env["recall_id"], second["id"])
    fx.submit_plan(api, env["recall_id"])
    env["recall"] = fx.approve_plan(api, env["recall_id"])
    env["second_retailer_id"] = second["id"]
    env["second_notification_id"] = second_notification["id"]
    env["notification"] = fx.get_notification(api, env["notification_id"])
    env["second_notification"] = fx.get_notification(api, second_notification["id"])
    return env


class TestRetailerRepIsConfinedToItsOwnNotification:
    """The one entity-backed role is authorised against row data, not a role string."""

    def test_a_rep_cannot_acknowledge_another_retailers_notification(self, api):
        """The row, not the role, is what refuses the foreign acknowledgement.

        The contract states: "Concretely, a `RetailerRep` acknowledging a stop-sale
        notification must supply an `X-User-ID` equal to that notification's
        `retailer_id`; any other value is rejected with
        `ERR_RETAILER_SCOPE_VIOLATION` (HTTP 403)." The evaluation order likewise
        names "**Retailer scope** — a `RetailerRep` acts only on its own
        notification, else `ERR_RETAILER_SCOPE_VIOLATION`."

        Design: Corner/rbac/retailer_rep_is_confined_to_its_own_notification
        """
        env = _stop_sale_at_two_retailers(api)
        assert_field_values(env["second_notification"], status="ISSUED")
        assert env["second_notification"]["retailer_id"] == env["second_retailer_id"]

        validate_error(
            api.acknowledge_notification(
                env["second_notification_id"],
                f.acknowledge_payload(units_on_shelf_reported=0),
                headers=make_retailer_rep_headers(env["retailer_id"]),
            ),
            "ERR_RETAILER_SCOPE_VIOLATION",
            403,
        )

        after = fx.get_notification(api, env["second_notification_id"])
        assert_field_values(after, status="ISSUED")
        assert_fields_null(after, "acknowledged_at", "units_on_shelf_reported")
        retailer = fx.get_retailer(api, env["second_retailer_id"])
        assert_field_values(
            retailer,
            open_stop_sale_count=1,
            verified_removal_count=0,
            compliance_posture="STOP_SALE_ACTIVE",
        )

    def test_a_rep_cannot_read_another_retailers_notification(self, api):
        """Reads are scoped by the same ownership rule as writes.

        The contract states: "A retailer representative may only acknowledge its
        own stop-sale notice, and may only read the recall, retailer and
        notification records it is party to." It also states: "`RetailerRep` is
        the one **entity-backed** role. When `X-User-Role` is `RetailerRep`,
        `X-User-ID` is the `id` of the acting `Retailer`; ownership checks on any
        resource that references a `Retailer` compare that resource's retailer
        foreign-key field to `X-User-ID`."

        Design: Corner/rbac/retailer_rep_is_confined_to_its_own_notification
        """
        env = _stop_sale_at_two_retailers(api)

        validate_error(
            api.get_retailer_notification(
                env["second_notification_id"],
                headers=make_retailer_rep_headers(env["retailer_id"]),
            ),
            "ERR_RETAILER_SCOPE_VIOLATION",
            403,
        )

    def test_a_rep_acknowledges_its_own_notification_successfully(self, api):
        """The role is permitted on the endpoint, so its own row goes through.

        The contract states: "The retailer acknowledges the stop-sale order and
        reports the units it still holds, supplying a `units_on_shelf_reported`
        count of at least 0." It also states: "A retailer representative may only
        acknowledge its own stop-sale notice, and may only read the recall,
        retailer and notification records it is party to."

        Design: Corner/rbac/retailer_rep_is_confined_to_its_own_notification
        """
        env = _stop_sale_at_two_retailers(api)

        acknowledged = validate_success(
            api.acknowledge_notification(
                env["notification_id"],
                f.acknowledge_payload(units_on_shelf_reported=2),
                headers=make_retailer_rep_headers(env["retailer_id"]),
            )
        )
        assert_field_values(
            acknowledged, status="ACKNOWLEDGED", units_on_shelf_reported=2
        )
        assert acknowledged["acknowledged_at"] is not None
