"""Role authorization, entity-backed ownership, authentication, segregation of duties and docket-officer identity."""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID, get_success_data, validate_error,
    validate_error_is_one_of, validate_paginated, validate_success,
)

from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers import test_users as U


def test_program_administrator_runs_configuration_overrides_and_the_program_clock(api):
    """A single ProgramAdministrator session reaches company status actions, money adjustments, the logical clock and the nightly batch.

    PRD §3.10: "An administrator may also act by hand, supplying an `action` of `SUSPEND`, `REINSTATE` or `REVOKE` with a `status_reason`."
    PRD §3.10: "Every status action stamps `last_status_action_at` at the logical clock and records the `status_reason`."
    PRD §3.8: "Only the program administrator may move assessed money."
    PRD §3.8: "The adjustment raises `adjusted_cents` and recomputes `outstanding_cents`; a `WAIVE` that closes the gap settles `payment_status` to `PAID`; a `WRITE_OFF` requires the stage to be `REFERRED` and moves it to the terminal `WRITTEN_OFF`, adding the whole outstanding amount to `adjusted_cents`, zeroing `outstanding_cents`, and removing the invoice from the premises' balance and from every allocation candidate set."
    PRD §3.8: "Step one: the outstanding principal is `assessed_cents` minus `paid_cents` minus `adjusted_cents`, and must be above zero."

    The permit issue invoice is assessed at 5000 fee plus 500 administrative fee,
    so a WAIVE taken at its whole outstanding balance records adjusted_cents of
    5500 and drives outstanding_cents to 0. Because the delinquency arithmetic
    requires an outstanding principal above zero, the nightly run at
    2026-09-05 adds no late penalty to the settled invoice.

    Design: Corner/rbac/program_administrator_runs_configuration_overrides_and_the_program_clock
    """
    bundle = X.setup_program_baseline(
        api,
        clock=C.CLOCK_STARTUP_UTC,
        site_overrides={"occupancy_class": "COMMERCIAL"},
    )
    invoice = X.invoices_of_site(api, bundle.site_id, kind="PERMIT_ISSUE_FEE")[0]

    reason = "Central station failed the ECV audit for two consecutive months."
    resp = api.company_status_action(
        bundle.company_id,
        {"action": "SUSPEND", "status_reason": reason},
        U.PROGRAM_ADMIN,
    )
    company = A.data_of(resp)
    A.assert_status(company, "SUSPENDED")
    assert company["status_reason"] == reason, (
        f"status_reason must be echoed, got {company['status_reason']!r}"
    )
    assert str(company["last_status_action_at"]).startswith("2026-08-01T00:00:00"), (
        "last_status_action_at must be stamped at the logical clock 2026-08-01T00:00:00Z, "
        f"got {company['last_status_action_at']!r}"
    )

    resp = api.adjust_invoice(
        invoice["id"],
        {
            "adjustment_kind": "WAIVE",
            "reason": "Permit fee waived under the small-business hardship policy.",
            "expected_penalty_invoice_version": invoice["version"],
            # PRD §3.8: an adjustment supplies "an `amount_cents` where the kind
            # takes one", and a WAIVE is bounded by `outstanding_cents`, so the
            # whole 5500-cent balance is the amount waived here.
            "amount_cents": 5500,
        },
        U.PROGRAM_ADMIN,
    )
    waived = A.data_of(resp)
    A.assert_invoice_totals(
        waived,
        assessed_cents=5500,
        adjusted_cents=5500,
        paid_cents=0,
        outstanding_cents=0,
        payment_status="PAID",
    )

    validate_success(api.set_clock({"current_utc": "2026-09-05T00:00:00Z"}, U.PROGRAM_ADMIN))
    validate_success(api.run_nightly(U.PROGRAM_ADMIN))

    after = X.get_invoice(api, invoice["id"])
    A.assert_invoice_totals(
        after,
        adjusted_cents=5500,
        outstanding_cents=0,
        payment_status="PAID",
    )
    A.assert_money_cents(after["late_penalty_cents"], 0, "late_penalty_cents")


def test_permit_clerk_registers_the_premises_chain_and_decides_registrations(api):
    """A PermitClerk builds a premises, its roster and its systems, and issues both registration verdicts.

    PRD §2.1: "A recognized role that is not listed among the authorized roles for the endpoint it invoked is rejected with `ERR_ROLE_NOT_PERMITTED`."
    PRD §3.3: "Approval by a `PermitClerk` (or an administrator) drives `SUBMITTED → PERMITTED` and is the most consequential single operation in the program."
    PRD §3.3: "Rejection is the sibling branch out of `SUBMITTED`. A clerk supplies `rejection_reason`, the row moves `SUBMITTED → REJECTED` — a terminal state — the reason is stored on `rejection_reason`, and the monitoring company's `monitored_system_count` is decremented."
    PRD §3.3: "No permit is created, no money is assessed and no premises counter changes."

    The clerk's approval prices the issue fee from the schedule it cannot edit:
    a 5000-cent permit fee plus the 500-cent administrative floor is a
    5500-cent assessment.

    Design: Corner/rbac/permit_clerk_registers_the_premises_chain_and_decides_registrations
    """
    X.set_clock(api, C.CLOCK_STARTUP_UTC)
    X.create_active_fee_schedule(api)
    company_id = X.create_company(api)

    site_resp = api.create_alarm_site(
        F.alarm_site_payload(
            address_key="88-ELM-AVE-75204",
            street_address="88 Elm Avenue",
            occupancy_class="RESIDENTIAL",
        ),
        U.PERMIT_CLERK,
    )
    site_id = A.data_of(site_resp, 201)["id"]

    c1 = A.data_of(
        api.create_site_contact(
            F.site_contact_payload(
                site_id,
                full_name="Ingrid Halvorsen",
                phone_number="+12145550301",
                relationship="OWNER",
                contact_priority=1,
                is_ecv_callable=True,
            ),
            U.PERMIT_CLERK,
        ),
        201,
    )
    c2 = A.data_of(
        api.create_site_contact(
            F.site_contact_payload(
                site_id,
                full_name="Tobias Halvorsen",
                phone_number="+12145550302",
                relationship="KEYHOLDER",
                contact_priority=2,
                is_ecv_callable=True,
            ),
            U.PERMIT_CLERK,
        ),
        201,
    )

    sys1 = A.data_of(
        api.create_alarm_system(
            F.alarm_system_payload(
                site_id,
                company_id,
                system_type="BURGLARY",
                zone_count=4,
                ecv_enabled=True,
                verified_response_mode="NONE",
                installed_at="2026-07-28T10:00:00Z",
            ),
            U.PERMIT_CLERK,
        ),
        201,
    )
    permit = A.data_of(api.approve_registration(sys1["id"], U.PERMIT_CLERK), 201)

    sys2 = A.data_of(
        api.create_alarm_system(
            F.alarm_system_payload(
                site_id,
                company_id,
                system_type="HOLDUP_PANIC",
                zone_count=1,
                ecv_enabled=False,
                verified_response_mode="NONE",
                installed_at="2026-07-29T10:00:00Z",
            ),
            U.PERMIT_CLERK,
        ),
        201,
    )
    rejected = A.data_of(
        api.reject_registration(
            sys2["id"],
            {"rejection_reason": "Panic-only device is not eligible for a police response permit."},
            U.PERMIT_CLERK,
        )
    )

    contacts = A.assert_total_count(
        api.list_site_contacts(U.PERMIT_CLERK, {"alarm_site_id": site_id}), 2
    )
    assert {row["id"] for row in contacts} == {c1["id"], c2["id"]}, (
        "the clerk's two contacts must be the premises roster"
    )
    site = X.get_site(api, site_id)
    assert site["ecv_callable_contact_count"] == 2, (
        f"ecv_callable_contact_count expected 2, got {site['ecv_callable_contact_count']}"
    )

    A.assert_status(X.get_system(api, sys1["id"]), "PERMITTED")
    A.assert_status(rejected, "REJECTED")
    A.assert_status(X.get_system(api, sys2["id"]), "REJECTED")
    A.assert_status(X.get_permit(api, permit["id"]), "ACTIVE")

    issue_invoices = X.invoices_of_site(api, site_id, kind="PERMIT_ISSUE_FEE")
    assert len(issue_invoices) == 1, (
        f"exactly one issue-fee invoice expected, got {len(issue_invoices)}"
    )
    A.assert_invoice_totals(
        issue_invoices[0],
        subtotal_cents=5000,
        admin_fee_cents=500,
        assessed_cents=5500,
    )
    A.assert_total_count(api.list_penalty_invoices(U.BILLING_CLERK, {"alarm_site_id": site_id}), 1)
    A.assert_total_count(api.list_payment_records(U.BILLING_CLERK, {"alarm_site_id": site_id}), 0)
    A.assert_total_count(api.list_suspension_orders(U.PROGRAM_ADMIN, {"alarm_site_id": site_id}), 0)
    A.assert_total_count(
        api.list_false_alarm_incidents(U.PROGRAM_ADMIN, {"alarm_site_id": site_id}), 0
    )


def test_alarm_company_operator_lodges_requests_and_files_its_own_reports(api):
    """An AlarmCompanyOperator lodges a dispatch request, cancels it and files its own period report, but rules on neither.

    PRD §2.1: "When `X-User-Role` is `AlarmCompanyOperator`, `X-User-ID` is the `id` of the acting `AlarmCompany`; ownership checks compare the company reachable from the target resource — the company itself, or the monitoring company of the target system, dispatch request or compliance report — to `X-User-ID`."
    PRD §3.4: "Cancellation moves `VALIDATED → CANCELLED` (terminal) with an optional `cancellation_reason`; a company operator cancelling must be the request's own monitoring company, else `ERR_NOT_RESOURCE_OWNER`, and a cancelled request yields no chargeable incident and is excluded from the company's system-side dispatch count for reporting purposes."
    PRD §3.10: "`system_dispatch_count` is the number of dispatch requests attributed to that company whose `occurred_at` falls inside the closed period interval and whose status is not `CANCELLED` — a `REFUSED` request still counts, because the company did ask for dispatch even though the city declined, and only a cancellation removes the ask."
    PRD §3.10: "`period_score` is 0.6 times `period_accuracy` plus 0.4 times `period_ecv_rate`, rounded half up to two decimal places."

    The one September request is cancelled, so system_dispatch_count is 0 for
    the September period. variance_count is the absolute difference between the
    reported 1 and that 0, so 1; variance_pct is 1 divided by the greater of 1
    and 0, so 1.0000; period_accuracy is 1 minus the lesser of 1 and 1.0000, so
    0.0000; period_ecv_rate is the lesser of 1 and 2 divided by the greater of 1
    and 1, so 1.0000; and period_score is 0.6 times 0.0000 plus 0.4 times
    1.0000, which is 0.40.

    Design: Corner/rbac/alarm_company_operator_lodges_requests_and_files_its_own_reports
    """
    bundle = X.setup_program_baseline(api, site_overrides={"occupancy_class": "COMMERCIAL"})
    operator = U.alarm_company_operator(bundle.company_id)

    occurred_at = "2026-09-15T03:09:00Z"
    resp = api.create_dispatch_request(
        F.dispatch_request_payload(
            bundle.system_id,
            occurred_at,
            call_attempts=X.two_call_attempts(bundle, occurred_at),
            idempotency_key="gsm-0915-a",
        ),
        operator,
    )
    request_id = A.data_of(resp, 201)["id"]

    validate_success(api.validate_dispatch_request(request_id, U.DISPATCH_SUPERVISOR))

    cancelled = A.data_of(
        api.cancel_dispatch_request(
            request_id,
            operator,
            {"cancellation_reason": "Keyholder called back and disarmed the panel."},
        )
    )
    A.assert_status(cancelled, "CANCELLED")

    report = A.data_of(
        api.create_compliance_report(
            F.compliance_report_payload(
                bundle.company_id,
                "2026-09-01T00:00:00Z",
                "2026-09-30T00:00:00Z",
                reported_dispatch_count=1,
                reported_cancellation_count=0,
                ecv_attempt_count=2,
            ),
            operator,
        ),
        201,
    )

    A.assert_status(
        A.data_of(api.get_dispatch_request(request_id, U.PROGRAM_ADMIN)), "CANCELLED"
    )
    A.assert_total_count(
        api.list_false_alarm_incidents(U.PROGRAM_ADMIN, {"alarm_site_id": bundle.site_id}), 0
    )

    assert report["system_dispatch_count"] == 0, (
        f"system_dispatch_count expected 0 for a cancelled request, got {report['system_dispatch_count']}"
    )
    assert report["variance_count"] == 1, (
        f"variance_count expected 1, got {report['variance_count']}"
    )
    A.assert_ratio_4dp(report["variance_pct"], 1.0, "variance_pct")
    A.assert_ratio_4dp(report["period_accuracy"], 0.0, "period_accuracy")
    A.assert_ratio_4dp(report["period_ecv_rate"], 1.0, "period_ecv_rate")
    A.assert_score_2dp(report["period_score"], 0.40, "period_score")
    A.assert_status(report, "SUBMITTED")

    refused = api.review_compliance_report(
        report["id"], {"decision": "ACCEPT", "variance_notes": "Self-approved."}, operator
    )
    validate_error(refused, E.ERR_ROLE_NOT_PERMITTED, expected_status=403)


def test_alarm_user_contests_its_own_determination_and_manages_its_own_roster(api):
    """One entity-backed AlarmUser identity — the premises id itself — adds a contact, files the appeal and withdraws it.

    PRD §2.1: "When `X-User-Role` is `AlarmUser`, `X-User-ID` is the `id` of the acting `AlarmSite`; ownership checks on any resource that references a premises compare the resource's premises reference to `X-User-ID`, whether that reference is the site itself or the site reachable from the target system, permit, incident, appeal, invoice, payment or allocation."
    PRD §3.6: "An accepted appeal is created in `FILED` with `filed_at` at the logical clock, `filed_by_user_id` set from the acting `X-User-ID`, `hearing_docket_id` null, `decision`, `decided_at`, `decided_by_user_id` and `findings` all null, and `alarm_site_id` denormalized from the incident."
    PRD §3.6: "The contested incident moves from `COUNTED` to `APPEALED`, its `appeal_count` and `version` each rise by 1, and — this is the point of the state — the fee **stands**."
    PRD §3.6: "A permit holder may also give up a seat voluntarily: withdrawal is available from `FILED` or `SCHEDULED`, takes an optional `withdrawal_reason`, and may only be exercised by the appellant — the acting `X-User-ID` must equal the appeal's `alarm_site_id`, else `ERR_NOT_RESOURCE_OWNER`."
    PRD §3.6: "Withdrawal from either state returns the incident from `APPEALED` to `COUNTED` and resumes dunning on its invoice; withdrawal from `SCHEDULED` additionally decrements the docket's `scheduled_appeal_count`, and if that docket was `CLOSED_FOR_SCHEDULING` the freed seat reopens it, `CLOSED_FOR_SCHEDULING → OPEN`."

    The incident is created in the reported state at version 1 and the chargeable
    ruling bumps it to version 2, so the filing under the premises identity must
    consume exactly 2; the acceptance then carries the incident to version 3.

    Design: Corner/rbac/alarm_user_contests_its_own_determination_and_manages_its_own_roster
    """
    bundle = X.setup_program_baseline(api, site_overrides={"occupancy_class": "COMMERCIAL"})
    incident = X.create_reported_incident(
        api, bundle, bundle.system_id, "2026-09-15T03:09:00Z"
    )
    X.set_clock(api, "2026-09-20T01:00:00Z")
    X.determine_counted(api, incident.incident_id)

    holder = U.alarm_user(bundle.site_id)

    contact3 = A.data_of(
        api.create_site_contact(
            F.site_contact_payload(
                bundle.site_id,
                full_name="Marcus Oyelaran",
                phone_number="+12145550303",
                relationship="KEYHOLDER",
                contact_priority=3,
                is_ecv_callable=True,
            ),
            holder,
        ),
        201,
    )
    site = X.get_site(api, bundle.site_id)
    assert site["ecv_callable_contact_count"] == 3, (
        f"ecv_callable_contact_count expected 3 after the holder's own write, got {site['ecv_callable_contact_count']}"
    )

    ruled = X.get_incident(api, incident.incident_id)
    A.assert_status(ruled, "COUNTED")
    assert ruled["version"] == 2, f"incident version expected 2 after the ruling, got {ruled['version']}"

    appeal = A.data_of(
        api.create_appeal(
            F.appeal_payload(
                incident.incident_id,
                grounds="WRONG_CAUSE_CODE",
                expected_false_alarm_incident_version=ruled["version"],
            ),
            holder,
        ),
        201,
    )
    A.assert_status(appeal, "FILED")
    assert appeal["filed_by_user_id"] == bundle.site_id, (
        f"filed_by_user_id must be the acting premises identity, got {appeal['filed_by_user_id']!r}"
    )
    assert appeal["alarm_site_id"] == bundle.site_id, (
        f"alarm_site_id must be denormalized from the incident, got {appeal['alarm_site_id']!r}"
    )
    assert appeal["decision"] is None, f"decision must be null on a filed appeal, got {appeal['decision']!r}"

    appealed = X.get_incident(api, incident.incident_id)
    A.assert_status(appealed, "APPEALED")
    assert appealed["version"] == 3, (
        f"incident version expected 3 after the filing, got {appealed['version']}"
    )
    assert appealed["appeal_count"] == 1, (
        f"appeal_count expected 1, got {appealed['appeal_count']}"
    )

    withdrawn = A.data_of(
        api.withdraw_appeal(
            appeal["id"], holder, {"withdrawal_reason": "The holder accepts the ruling."}
        )
    )
    A.assert_status(withdrawn, "WITHDRAWN")
    A.assert_status(X.get_incident(api, incident.incident_id), "COUNTED")
    assert contact3["id"] in [row["id"] for row in
                             A.assert_total_count(
                                 api.list_site_contacts(holder, {"alarm_site_id": bundle.site_id}), 3
                             )], "the holder's own contact must remain on the roster"


def test_police_dispatch_supervisor_drives_the_whole_dispatch_lifecycle(api):
    """A PoliceDispatchSupervisor validates, dispatches, opens the incident and refuses a second signal, yet cannot rule on what it filed.

    PRD §3.4: "From `SUBMITTED` the request forks. A `PoliceDispatchSupervisor` may validate it, moving `SUBMITTED → VALIDATED` and stamping `validated_at` with the logical clock and `validated_by_user_id` with the acting `X-User-ID`."
    PRD §3.4: "The sibling branch is refusal: the supervisor supplies a coded `refusal_reason` of `ECV_DEFICIENT`, `RESPONSE_SUSPENDED`, `VERIFIED_RESPONSE_MISSING` or `DUPLICATE_SIGNAL`, the row moves `SUBMITTED → REFUSED` (terminal), the reason is stored, and no incident may ever reference that request."
    PRD §3.4: "Recording the dispatch moves `VALIDATED → DISPATCHED` and stamps `dispatched_at` with the logical clock; it requires that the premises posture is still not `RESPONSE_SUSPENDED` at the moment of dispatch, else `ERR_POLICE_RESPONSE_SUSPENDED`, because a suspension served between validation and dispatch must stop the patrol."
    PRD §2.1: "A `FalseAlarmReviewOfficer` rules each incident chargeable or exempt and reviews monitoring-company reports."
    PRD §2.1: "A recognized role that is not listed among the authorized roles for the endpoint it invoked is rejected with `ERR_ROLE_NOT_PERMITTED`."

    The two signals sit on two separate permitted systems of the premises,
    because a request in the submitted, validated or dispatched state already
    occupies its own system.

    Design: Corner/rbac/police_dispatch_supervisor_drives_the_whole_dispatch_lifecycle
    """
    bundle = X.setup_program_baseline(
        api, site_overrides={"occupancy_class": "COMMERCIAL"}, system_count=2
    )
    operator = U.alarm_company_operator(bundle.company_id)

    occurred_one = "2026-09-15T03:09:00Z"
    first = A.data_of(
        api.create_dispatch_request(
            F.dispatch_request_payload(
                bundle.system_ids[0],
                occurred_one,
                call_attempts=X.two_call_attempts(bundle, occurred_one),
                idempotency_key="gsm-0915-a",
            ),
            operator,
        ),
        201,
    )
    second = A.data_of(
        api.create_dispatch_request(
            F.dispatch_request_payload(
                bundle.system_ids[1],
                "2026-09-16T02:38:00Z",
                call_attempts=[
                    F.call_attempt(bundle.contact_ids[0], "2026-09-16T02:40:00Z", "NO_ANSWER")
                ],
                verification_method="SINGLE_CALL",
                idempotency_key="gsm-0916-b",
            ),
            operator,
        ),
        201,
    )

    validated = A.data_of(api.validate_dispatch_request(first["id"], U.DISPATCH_SUPERVISOR))
    A.assert_status(validated, "VALIDATED")
    assert validated["validated_by_user_id"] == U.DISPATCH_SUPERVISOR_ID, (
        f"validated_by_user_id expected pds-05, got {validated['validated_by_user_id']!r}"
    )

    X.set_clock(api, "2026-09-20T01:00:00Z")
    dispatched = A.data_of(api.record_dispatch(first["id"], U.DISPATCH_SUPERVISOR))
    A.assert_status(dispatched, "DISPATCHED")

    incident = A.data_of(
        api.create_false_alarm_incident(
            F.false_alarm_incident_payload(first["id"], cause_code="OPERATOR_ERROR"),
            U.DISPATCH_SUPERVISOR,
        ),
        201,
    )
    A.assert_status(incident, "REPORTED")
    assert incident["dispatch_request_id"] == first["id"], (
        "the incident must reference the request the supervisor dispatched"
    )

    refused = A.data_of(
        api.refuse_dispatch_request(
            second["id"], {"refusal_reason": "ECV_DEFICIENT"}, U.DISPATCH_SUPERVISOR
        )
    )
    A.assert_status(refused, "REFUSED")
    assert refused["refusal_reason"] == "ECV_DEFICIENT", (
        f"refusal_reason expected ECV_DEFICIENT, got {refused['refusal_reason']!r}"
    )
    A.assert_total_count(
        api.list_false_alarm_incidents(
            U.PROGRAM_ADMIN, {"dispatch_request_id": second["id"]}
        ),
        0,
    )

    denied = api.determine_incident(
        incident["id"], F.determination_payload("COUNTED"), U.DISPATCH_SUPERVISOR
    )
    validate_error(denied, E.ERR_ROLE_NOT_PERMITTED, expected_status=403)
    A.assert_status(X.get_incident(api, incident["id"]), "REPORTED")


def test_false_alarm_review_officer_determines_incidents_and_reviews_reports(api):
    """One FalseAlarmReviewOfficer session both prices a premises' incident and flags its monitoring company's period.

    PRD §2.1: "A `FalseAlarmReviewOfficer` rules each incident chargeable or exempt and reviews monitoring-company reports."
    PRD §3.5: "In either case the incident's `occurrence_index` is the size of the set it belongs to — the incident is already counted at that point, so it counts itself — and `counted_window_mode` records which variant produced the number."
    PRD §3.5: "When the assessed fee is above zero a `FALSE_ALARM_FEE` invoice is issued; when the tier base is zero under the free allowance and no aggravation applies, no invoice row is created at all and no administrative fee is charged."
    PRD §3.10: "Flagging requires an actual discrepancy — `variance_pct` must be strictly above 0.1000, else `ERR_NO_REPORTABLE_VARIANCE` — and moves the report to `VARIANCE_FLAGGED`, storing the `variance_notes` and incrementing `consecutive_flagged_report_count`."
    PRD §3.10: "`variance_pct` is that count divided by the greater of 1 and `system_dispatch_count`, at four decimal places."

    This is the premises' first chargeable occurrence, so occurrence_index is 1,
    which is at or below the two-alarm free allowance; the tier base is forced to
    zero and assessed_fee_cents is 0 with no invoice raised. The August period
    holds no dispatch request at all — the only signal occurred on 2026-09-15 —
    so system_dispatch_count is 0 against a reported 3: variance_count is 3 and
    variance_pct is 3 divided by the greater of 1 and 0, which is 3.0000, well
    above the 0.1000 flagging floor.

    Design: Corner/rbac/false_alarm_review_officer_determines_incidents_and_reviews_reports
    """
    bundle = X.setup_program_baseline(api, site_overrides={"occupancy_class": "COMMERCIAL"})
    incident = X.create_reported_incident(api, bundle, bundle.system_id, "2026-09-15T03:09:00Z")
    X.set_clock(api, "2026-09-20T01:00:00Z")

    report = A.data_of(
        api.create_compliance_report(
            F.compliance_report_payload(
                bundle.company_id,
                "2026-08-01T00:00:00Z",
                "2026-08-31T00:00:00Z",
                reported_dispatch_count=3,
                reported_cancellation_count=0,
                ecv_attempt_count=0,
            ),
            U.alarm_company_operator(bundle.company_id),
        ),
        201,
    )

    ruled = A.data_of(
        api.determine_incident(
            incident.incident_id, F.determination_payload("COUNTED"), U.REVIEW_OFFICER
        )
    )
    A.assert_status(ruled, "COUNTED")
    assert ruled["determination"] == "COUNTED", (
        f"determination expected COUNTED, got {ruled['determination']!r}"
    )
    assert ruled["determined_by_user_id"] == U.REVIEW_OFFICER_ID, (
        f"determined_by_user_id expected faro-11, got {ruled['determined_by_user_id']!r}"
    )
    assert ruled["occurrence_index"] == 1, (
        f"occurrence_index expected 1, got {ruled['occurrence_index']}"
    )
    A.assert_money_cents(ruled["assessed_fee_cents"], 0, "assessed_fee_cents")
    A.assert_total_count(
        api.list_penalty_invoices(
            U.BILLING_CLERK, {"alarm_site_id": bundle.site_id, "kind": "FALSE_ALARM_FEE"}
        ),
        0,
    )

    flagged = A.data_of(
        api.review_compliance_report(
            report["id"],
            {
                "decision": "FLAG_VARIANCE",
                "variance_notes": "Three dispatches reported for a month with none on record.",
            },
            U.REVIEW_OFFICER,
        )
    )
    A.assert_status(flagged, "VARIANCE_FLAGGED")
    assert flagged["reviewed_by_user_id"] == U.REVIEW_OFFICER_ID, (
        f"reviewed_by_user_id expected faro-11, got {flagged['reviewed_by_user_id']!r}"
    )
    assert flagged["variance_count"] == 3, (
        f"variance_count expected 3, got {flagged['variance_count']}"
    )
    A.assert_ratio_4dp(flagged["variance_pct"], 3.0, "variance_pct")

    company = X.get_company(api, bundle.company_id)
    assert company["consecutive_flagged_report_count"] == 1, (
        "consecutive_flagged_report_count expected 1 after the first flag, "
        f"got {company['consecutive_flagged_report_count']}"
    )


def test_hearing_officer_opens_a_docket_schedules_holds_and_decides(api):
    """A HearingOfficer creates its own docket, seats the appeal, holds the session and rules on it.

    PRD §3.6: "On success the appeal moves to `SCHEDULED` with its `hearing_docket_id` set, and the docket's `scheduled_appeal_count` and `version` each rise by 1."
    PRD §3.6: "Holding the session is the officer's own act: only the caller whose `X-User-ID` equals the docket's `hearing_officer_user_id` may do it, else `ERR_NOT_DOCKET_OFFICER`; the logical clock must have reached `session_start`, the boundary inclusive, else `ERR_HEARING_SESSION_NOT_STARTED`; and the docket must seat at least one appeal, else `ERR_DOCKET_EMPTY`."
    PRD §3.6: "A docket may be held from either `OPEN` or `CLOSED_FOR_SCHEDULING` under identical preconditions and with identical effects: `held_at` is stamped with the logical clock, the docket becomes `HELD`, which is terminal, its `version` rises by 1, and every appeal on it in `SCHEDULED` advances to `HEARD`, becoming decidable."
    PRD §3.6: "`DENIED` is the conservative outcome: the count stands. The incident returns from `APPEALED` to `COUNTED` with its `determination`, `occurrence_index` and `assessed_fee_cents` exactly as they were before the appeal, its invoice re-enters the nightly escalation set, and the incident becomes eligible for exactly one rehearing."

    The officer names itself on the docket it creates, so the priority-10
    docket-officer check passes for both the holding and the deciding call; and
    because the ruling was made by the review officer and the appeal filed by the
    premises, the deciding identity collides with neither.

    Design: Corner/rbac/hearing_officer_opens_a_docket_schedules_holds_and_decides
    """
    bundle = X.setup_program_baseline(api, site_overrides={"occupancy_class": "COMMERCIAL"})
    incident = X.create_reported_incident(api, bundle, bundle.system_id, "2026-09-15T03:09:00Z")
    X.set_clock(api, "2026-09-20T01:00:00Z")
    X.determine_counted(api, incident.incident_id)
    appeal_id = X.file_appeal(api, bundle, incident.incident_id, headers=U.alarm_user(bundle.site_id))

    docket = A.data_of(
        api.create_hearing_docket(
            F.hearing_docket_payload(
                U.HEARING_OFFICER_ID,
                "2026-10-05T16:15:00Z",
                "2026-10-05T18:15:00Z",
                location="Municipal Court Annex Room 2B",
                capacity=4,
            ),
            U.HEARING_OFFICER,
        ),
        201,
    )
    assert docket["hearing_officer_user_id"] == U.HEARING_OFFICER_ID, (
        f"hearing_officer_user_id expected ho-03, got {docket['hearing_officer_user_id']!r}"
    )
    A.assert_status(docket, "OPEN")

    scheduled = A.data_of(
        api.schedule_appeal(
            appeal_id,
            {
                "hearing_docket_id": docket["id"],
                "expected_hearing_docket_version": docket["version"],
            },
            U.HEARING_OFFICER,
        )
    )
    A.assert_status(scheduled, "SCHEDULED")
    assert scheduled["hearing_docket_id"] == docket["id"], (
        "the seated appeal must carry the docket it was placed on"
    )

    X.set_clock(api, "2026-10-05T16:15:00Z")
    held = A.data_of(api.hold_session(docket["id"], {}, U.HEARING_OFFICER))
    A.assert_status(held, "HELD")
    A.assert_status(X.get_appeal(api, appeal_id), "HEARD")

    decided = A.data_of(
        api.decide_appeal(
            appeal_id,
            {
                "decision": "DENIED",
                "findings": "The panel log confirms an operator error; the determination stands.",
            },
            U.HEARING_OFFICER,
        )
    )
    assert decided["decision"] == "DENIED", f"decision expected DENIED, got {decided['decision']!r}"
    A.assert_status(decided, "DENIED")
    assert decided["decided_by_user_id"] == U.HEARING_OFFICER_ID, (
        f"decided_by_user_id expected ho-03, got {decided['decided_by_user_id']!r}"
    )

    after = X.get_incident(api, incident.incident_id)
    A.assert_status(after, "COUNTED")
    assert after["determination"] == "COUNTED", (
        f"determination must be untouched by the appeal outcome, got {after['determination']!r}"
    )
    assert after["occurrence_index"] == 1, (
        f"occurrence_index must stand at 1 after a denial, got {after['occurrence_index']}"
    )
    assert after["determined_by_user_id"] == U.REVIEW_OFFICER_ID, (
        "the hearing officer never became the determining officer, got "
        f"{after['determined_by_user_id']!r}"
    )


def test_billing_clerk_posts_money_and_refers_unpaid_penalties(api):
    """A BillingClerk posts a full settlement and its waterfall allocation against the premises account.

    PRD §3.9: "The accepted payment is created in `APPLIED` with the next sequential `receipt_number` in the form RCT-000001 and `recorded_by_user_id` taken from the acting `X-User-ID` — that stamp is what later bars the same person from adjusting the invoice they collected on."
    PRD §3.9: "Walking that order with a running remainder, each invoice takes the lesser of the remainder and its own `outstanding_cents`."
    PRD §3.9: "Whatever remains after every candidate is exhausted becomes the payment's `credited_cents` and is added to the premises' `credit_balance_cents`; `allocated_cents` is the tendered amount minus that credit."
    PRD §3.8: "Settlement — `UNPAID → PAID` or `PARTIALLY_PAID → PAID` — occurs exactly when `paid_cents` plus `adjusted_cents` equals `assessed_cents` after the write, whether that is reached by an allocation covering the remainder or by a `WAIVE` adjustment; `outstanding_cents` becomes 0, the stage resettles to `CURRENT` on the next nightly run, and when every invoice for the premises is `PAID` a `REINSTATEMENT_PENDING` suspension order becomes liftable."

    The sole candidate invoice owes its whole 5500-cent assessment, so the
    running remainder of the 5500-cent tender is fully consumed by one
    allocation: allocated_cents is 5500, credited_cents is 0, and the invoice
    settles with outstanding_cents 0.

    Design: Corner/rbac/billing_clerk_posts_money_and_refers_unpaid_penalties
    """
    bundle = X.setup_program_baseline(
        api, clock=C.CLOCK_STARTUP_UTC, site_overrides={"occupancy_class": "COMMERCIAL"}
    )
    invoice = X.invoices_of_site(api, bundle.site_id, kind="PERMIT_ISSUE_FEE")[0]
    A.assert_invoice_totals(invoice, assessed_cents=5500, outstanding_cents=5500)

    payment = A.data_of(
        api.create_payment_record(
            F.payment_record_payload(
                bundle.site_id,
                5500,
                "2026-08-01T00:00:00Z",
                X.site_version(api, bundle.site_id),
                method="CARD",
                allocation_mode="AUTO_WATERFALL",
            ),
            U.BILLING_CLERK,
        ),
        201,
    )
    A.assert_status(payment, "APPLIED")
    assert payment["recorded_by_user_id"] == U.BILLING_CLERK_ID, (
        f"recorded_by_user_id expected bc-02, got {payment['recorded_by_user_id']!r}"
    )
    A.assert_money_cents(payment["allocated_cents"], 5500, "allocated_cents")
    A.assert_money_cents(payment["credited_cents"], 0, "credited_cents")
    A.assert_money_cents(payment["amount_cents"], 5500, "amount_cents")
    A.assert_cash_conservation(payment)

    rows = A.assert_total_count(
        api.list_payment_allocations(U.BILLING_CLERK, {"payment_record_id": payment["id"]}), 1
    )
    allocation = rows[0]
    A.assert_allocation_row(allocation)
    A.assert_money_cents(allocation["amount_cents"], 5500, "allocation amount_cents")
    assert allocation["penalty_invoice_id"] == invoice["id"], (
        "the allocation must land on the premises' only outstanding invoice"
    )
    assert allocation["sequence_index"] == 1, (
        f"sequence_index expected 1, got {allocation['sequence_index']}"
    )

    settled = X.get_invoice(api, invoice["id"])
    A.assert_invoice_totals(
        settled, paid_cents=5500, adjusted_cents=0, outstanding_cents=0, payment_status="PAID"
    )
    A.assert_outstanding_identity(settled)


def test_permit_clerk_cannot_activate_a_fee_schedule(api):
    """A PermitClerk may read a draft fee schedule but not activate it.

    PRD §2.1: "A `PermitClerk` staffs the permit desk: premises, contacts and system registrations, permit issuance and renewal, and service of suspension orders — never pricing, waiving or adjudication."
    PRD §2.1: "A recognized role that is not listed among the authorized roles for the endpoint it invoked is rejected with `ERR_ROLE_NOT_PERMITTED`."
    PRD §2.10: "Third, the recognized role must appear in the authorized-role list of the endpoint being called, failing with `ERR_ROLE_NOT_PERMITTED`."
    PRD §3.1: "A freshly created schedule lands in `DRAFT` and nothing consults it."
    PRD §3.1: "Activating it moves it to `ACTIVE`, pushes any previously `ACTIVE` schedule to `SUPERSEDED` and stamps that outgoing row's `superseded_at` with the logical clock."

    Design: Corner/rbac/permit_clerk_cannot_activate_a_fee_schedule
    """
    X.set_clock(api, C.CLOCK_STARTUP_UTC)
    schedule_id = X.create_draft_fee_schedule(api)

    refused = api.activate_fee_schedule(schedule_id, U.PERMIT_CLERK)
    validate_error(refused, E.ERR_ROLE_NOT_PERMITTED, expected_status=403)

    readable = A.data_of(api.get_fee_schedule(schedule_id, U.PERMIT_CLERK))
    A.assert_status(readable, "DRAFT")
    assert readable["superseded_at"] is None, (
        f"superseded_at must be null while a schedule is DRAFT, got {readable['superseded_at']!r}"
    )
    A.assert_total_count(api.list_fee_schedules(U.PERMIT_CLERK, {"status": "ACTIVE"}), 0)


def test_false_alarm_review_officer_cannot_take_a_company_status_action(api):
    """A FalseAlarmReviewOfficer cannot suspend a monitoring company by hand.

    PRD §2.1: "A `FalseAlarmReviewOfficer` rules each incident chargeable or exempt and reviews monitoring-company reports."
    PRD §2.10: "Third, the recognized role must appear in the authorized-role list of the endpoint being called, failing with `ERR_ROLE_NOT_PERMITTED`."
    PRD §3.10: "An administrator may also act by hand, supplying an `action` of `SUSPEND`, `REINSTATE` or `REVOKE` with a `status_reason`."
    PRD §3.10: "The company is created in `ACTIVE` with `reporting_compliance_score` at 1.00, `probation_started_at`, `status_reason` and `last_status_action_at` all null, and its derived counters recomputed: `monitored_system_count` as the number of systems it monitors in `SUBMITTED`, `PERMITTED` or `UNPERMITTED`, `dispatch_request_count_lifetime` as the number of dispatch requests it has lodged across every status, and `consecutive_flagged_report_count` as the length of the most-recent unbroken run of its reports ending in `VARIANCE_FLAGGED`, taken in order of `period_start` ascending."

    Design: Corner/rbac/false_alarm_review_officer_cannot_take_a_company_status_action
    """
    X.set_clock(api, C.CLOCK_STARTUP_UTC)
    X.create_active_fee_schedule(api)
    company_id = X.create_company(api)
    before = X.get_company(api, company_id)
    A.assert_status(before, "ACTIVE")

    refused = api.company_status_action(
        company_id,
        {
            "action": "SUSPEND",
            "status_reason": "Officer wants the monitor off the air immediately.",
        },
        U.REVIEW_OFFICER,
    )
    validate_error(refused, E.ERR_ROLE_NOT_PERMITTED, expected_status=403)

    after = X.get_company(api, company_id)
    A.assert_status(after, "ACTIVE")
    assert after["last_status_action_at"] is None, (
        f"last_status_action_at must still be null, got {after['last_status_action_at']!r}"
    )
    assert after["status_reason"] is None, (
        f"status_reason must still be null, got {after['status_reason']!r}"
    )
    A.assert_version_unchanged(before, after)


def test_alarm_user_cannot_approve_its_own_system_registration(api):
    """A premises owner may submit its own registration but the approval is refused on the role check, not the ownership check.

    PRD §2.10: "Third, the recognized role must appear in the authorized-role list of the endpoint being called, failing with `ERR_ROLE_NOT_PERMITTED`."
    PRD §2.1: "A mismatch in either direction is rejected with `ERR_NOT_RESOURCE_OWNER`."
    PRD §2.10: "A single request can violate several rules at once, and callers depend on a stable answer."
    PRD §3.3: "Approval by a `PermitClerk` (or an administrator) drives `SUBMITTED → PERMITTED` and is the most consequential single operation in the program."

    The acting identity is the premises that owns the system, so the priority-8
    ownership comparison would have passed; the priority-3 role check is
    evaluated first and is what answers, so the caller sees
    ERR_ROLE_NOT_PERMITTED rather than ERR_NOT_RESOURCE_OWNER.

    Design: Corner/rbac/alarm_user_cannot_approve_its_own_system_registration
    """
    X.set_clock(api, C.CLOCK_STARTUP_UTC)
    X.create_active_fee_schedule(api)
    company_id = X.create_company(api)
    site_id = X.create_site(api, address_key="1200-MAIN-ST-75201", occupancy_class="COMMERCIAL")
    X.create_contacts(api, site_id, 2)
    holder = U.alarm_user(site_id)

    system = A.data_of(
        api.create_alarm_system(
            F.alarm_system_payload(
                site_id,
                company_id,
                zone_count=6,
                installed_at="2026-07-26T09:00:00Z",
            ),
            holder,
        ),
        201,
    )
    A.assert_status(system, "SUBMITTED")

    refused = api.approve_registration(system["id"], holder)
    validate_error(refused, E.ERR_ROLE_NOT_PERMITTED, expected_status=403)

    after = X.get_system(api, system["id"])
    A.assert_status(after, "SUBMITTED")
    A.assert_version_unchanged(system, after)
    A.assert_total_count(
        api.list_alarm_permits(U.PERMIT_CLERK, {"alarm_system_id": system["id"]}), 0
    )
    assert X.invoices_of_site(api, site_id) == [], (
        "no issue-fee invoice may exist while the registration is unapproved"
    )


def test_police_dispatch_supervisor_cannot_lodge_a_dispatch_request(api):
    """A PoliceDispatchSupervisor cannot originate the dispatch request it would later rule on.

    PRD §3.4: "Every police response begins with a monitoring company lodging a dispatch request for one of its own systems."
    PRD §2.10: "Third, the recognized role must appear in the authorized-role list of the endpoint being called, failing with `ERR_ROLE_NOT_PERMITTED`."
    PRD §3.4: "The submission names the `alarm_system_id` that produced the signal, the `alarm_type` (`BURGLARY`, `HOLDUP`, `PANIC` or `DURESS`), the `verification_method` the central station used (`NONE`, `SINGLE_CALL`, `TWO_CALL_ECV`, `AUDIO_VIDEO` or `GUARD_RESPONSE`), the `call_attempts` log, the assertions `audio_video_evidence` and `guard_on_scene` (both defaulting to false), the `occurred_at` instant the signal fired, and an optional company-supplied `idempotency_key` which, when present, must be unique per monitoring company."

    Because the refused call persisted nothing, the idempotency key it carried is
    still free: the same key is accepted when the monitoring company itself
    lodges the request.

    Design: Corner/rbac/police_dispatch_supervisor_cannot_lodge_a_dispatch_request
    """
    bundle = X.setup_program_baseline(api, site_overrides={"occupancy_class": "COMMERCIAL"})
    payload = F.dispatch_request_payload(
        bundle.system_id,
        "2026-09-15T03:09:00Z",
        call_attempts=[
            F.call_attempt(bundle.contact_ids[0], "2026-09-15T03:10:00Z", "NO_ANSWER")
        ],
        idempotency_key="pds-forged-1",
    )

    refused = api.create_dispatch_request(payload, U.DISPATCH_SUPERVISOR)
    validate_error(refused, E.ERR_ROLE_NOT_PERMITTED, expected_status=403)

    A.assert_total_count(
        api.list_dispatch_requests(
            U.DISPATCH_SUPERVISOR,
            {"alarm_system_id": bundle.system_id, "page": 1, "per_page": 25},
        ),
        0,
    )

    accepted = A.data_of(
        api.create_dispatch_request(payload, U.alarm_company_operator(bundle.company_id)), 201
    )
    assert accepted["idempotency_key"] == "pds-forged-1", (
        "the key the refused call carried must still have been available, got "
        f"{accepted['idempotency_key']!r}"
    )
    A.assert_status(accepted, "SUBMITTED")


def test_false_alarm_review_officer_cannot_validate_a_dispatch_request(api):
    """A FalseAlarmReviewOfficer may read a submitted dispatch request but cannot validate it.

    PRD §3.4: "From `SUBMITTED` the request forks. A `PoliceDispatchSupervisor` may validate it, moving `SUBMITTED → VALIDATED` and stamping `validated_at` with the logical clock and `validated_by_user_id` with the acting `X-User-ID`."
    PRD §2.10: "Third, the recognized role must appear in the authorized-role list of the endpoint being called, failing with `ERR_ROLE_NOT_PERMITTED`."
    PRD §3.4: "**Verification sufficiency is computed once, at submission, and frozen on the row.**"
    PRD §3.4: "On acceptance the row denormalizes `alarm_site_id` and `monitoring_company_id` from the system and is created in `SUBMITTED`."

    The lodged request logged two attempts against two distinct callable
    contacts, so the frozen distinct_ecv_contact_count is 2, which meets the
    inclusive two-call threshold and leaves ecv_sufficient true even though the
    refused caller could not act on it.

    Design: Corner/rbac/false_alarm_review_officer_cannot_validate_a_dispatch_request
    """
    bundle = X.setup_program_baseline(api, site_overrides={"occupancy_class": "COMMERCIAL"})
    occurred_at = "2026-09-15T03:09:00Z"
    request_id = X.submit_dispatch_request(
        api,
        bundle,
        bundle.system_id,
        occurred_at,
        call_attempts=X.two_call_attempts(bundle, occurred_at),
        idempotency_key="gsm-0915-a",
    )

    refused = api.validate_dispatch_request(request_id, U.REVIEW_OFFICER)
    validate_error(refused, E.ERR_ROLE_NOT_PERMITTED, expected_status=403)

    readable = A.data_of(api.get_dispatch_request(request_id, U.REVIEW_OFFICER))
    A.assert_status(readable, "SUBMITTED")
    assert readable["version"] == 1, f"version expected 1, got {readable['version']}"
    assert readable["validated_at"] is None, (
        f"validated_at must still be null, got {readable['validated_at']!r}"
    )
    assert readable["validated_by_user_id"] is None, (
        f"validated_by_user_id must still be null, got {readable['validated_by_user_id']!r}"
    )
    assert readable["distinct_ecv_contact_count"] == 2, (
        f"distinct_ecv_contact_count expected 2, got {readable['distinct_ecv_contact_count']}"
    )
    assert readable["ecv_sufficient"] is True, (
        f"ecv_sufficient must stay frozen true, got {readable['ecv_sufficient']!r}"
    )


def test_hearing_officer_cannot_determine_an_incident(api):
    """A HearingOfficer cannot make the first-instance ruling on a reported incident.

    PRD §3.5: "A `FalseAlarmReviewOfficer` then rules on it, supplying `determination` as either `COUNTED` or `EXEMPT`, an `exempt_cause_code` when exempting, and optional `review_notes`."
    PRD §2.10: "Third, the recognized role must appear in the authorized-role list of the endpoint being called, failing with `ERR_ROLE_NOT_PERMITTED`."
    PRD §3.5: "The row denormalizes `alarm_site_id`, `alarm_system_id` and `occurred_at` from the request — the occurrence instant is the ordering key for all later numbering — and is created in `REPORTED`, not yet chargeable, with `occurrence_index` and `assessed_fee_cents` unset and `appeal_count` at 0."
    PRD §3.5: "It then sets `determination` to `COUNTED`, stamps `determined_at` with the logical clock and `determined_by_user_id` with the acting `X-User-ID`, assigns the occurrence numbering, prices the incident, and bills it."

    Because the refusal lands at the role check, none of the pricing side effects
    run: the incident keeps its unset numbering and the premises' chargeable
    window count stays at 0.

    Design: Corner/rbac/hearing_officer_cannot_determine_an_incident
    """
    bundle = X.setup_program_baseline(api, site_overrides={"occupancy_class": "COMMERCIAL"})
    incident = X.create_reported_incident(api, bundle, bundle.system_id, "2026-09-15T03:09:00Z")
    X.set_clock(api, "2026-09-20T01:00:00Z")

    refused = api.determine_incident(
        incident.incident_id,
        F.determination_payload(
            "COUNTED", review_notes="Hearing officer attempting a first-instance ruling."
        ),
        U.HEARING_OFFICER,
    )
    validate_error(refused, E.ERR_ROLE_NOT_PERMITTED, expected_status=403)

    after = X.get_incident(api, incident.incident_id)
    A.assert_status(after, "REPORTED")
    assert after["occurrence_index"] is None, (
        f"occurrence_index must still be unset, got {after['occurrence_index']!r}"
    )
    assert after["assessed_fee_cents"] is None, (
        f"assessed_fee_cents must still be unset, got {after['assessed_fee_cents']!r}"
    )
    assert after["determination"] is None, (
        f"determination must still be unset, got {after['determination']!r}"
    )

    site = X.get_site(api, bundle.site_id)
    assert site["chargeable_count_window"] == 0, (
        f"chargeable_count_window must still be 0, got {site['chargeable_count_window']}"
    )
    assert site["chargeable_count_rolling_365"] == 0, (
        f"chargeable_count_rolling_365 must still be 0, got {site['chargeable_count_rolling_365']}"
    )


def test_program_administrator_cannot_decide_an_appeal(api):
    """A ProgramAdministrator holds neither of the hearing officer's adjudicative operations.

    PRD §3.6: "**Deciding.** A heard appeal is decided by supplying a `decision` of `GRANTED`, `DENIED` or `REMANDED`, the written `findings`, and — only on a grant — an `exempt_cause_code`."
    PRD §3.6: "Holding the session is the officer's own act: only the caller whose `X-User-ID` equals the docket's `hearing_officer_user_id` may do it, else `ERR_NOT_DOCKET_OFFICER`; the logical clock must have reached `session_start`, the boundary inclusive, else `ERR_HEARING_SESSION_NOT_STARTED`; and the docket must seat at least one appeal, else `ERR_DOCKET_EMPTY`."
    PRD §2.10: "Third, the recognized role must appear in the authorized-role list of the endpoint being called, failing with `ERR_ROLE_NOT_PERMITTED`."
    PRD §2.10: "The service therefore evaluates its checks in one fixed sequence and returns the **first** failure it finds; later checks are never reached."

    The administrator opened the docket itself, so the denial is scoped to the
    adjudicative acts and not to the calendar. Both refusals land at the
    priority-3 role check, ahead of the priority-10 docket-officer rule and ahead
    of any state check on a docket that has already been held.

    Design: Corner/rbac/program_administrator_cannot_decide_an_appeal
    """
    bundle = X.setup_program_baseline(api, site_overrides={"occupancy_class": "COMMERCIAL"})
    incident = X.create_reported_incident(api, bundle, bundle.system_id, "2026-09-15T03:09:00Z")
    X.set_clock(api, "2026-09-20T01:00:00Z")
    X.determine_counted(api, incident.incident_id)
    appeal_id = X.file_appeal(api, bundle, incident.incident_id, headers=U.alarm_user(bundle.site_id))

    docket_id = X.create_docket(
        api,
        "2026-10-05T14:00:00Z",
        "2026-10-05T16:00:00Z",
        officer_user_id=U.HEARING_OFFICER_ID,
        headers=U.PROGRAM_ADMIN,
        location="City Hall Room 210",
        capacity=4,
    )
    X.schedule_appeal(api, appeal_id, docket_id)
    X.set_clock(api, "2026-10-05T14:00:00Z")
    X.hold_session(api, docket_id)

    heard = X.get_appeal(api, appeal_id)
    A.assert_status(heard, "HEARD")

    refused_decide = api.decide_appeal(
        appeal_id,
        {
            "decision": "GRANTED",
            "findings": "Administrator overruling the determination without a hearing.",
        },
        U.PROGRAM_ADMIN,
    )
    validate_error(refused_decide, E.ERR_ROLE_NOT_PERMITTED, expected_status=403)

    refused_hold = api.hold_session(docket_id, {}, U.PROGRAM_ADMIN)
    validate_error(refused_hold, E.ERR_ROLE_NOT_PERMITTED, expected_status=403)

    after = X.get_appeal(api, appeal_id)
    A.assert_status(after, "HEARD")
    assert after["decision"] is None, f"decision must still be null, got {after['decision']!r}"
    assert after["decided_by_user_id"] is None, (
        f"decided_by_user_id must still be null, got {after['decided_by_user_id']!r}"
    )
    A.assert_version_unchanged(heard, after)
    A.assert_status(X.get_incident(api, incident.incident_id), "APPEALED")


def test_billing_clerk_cannot_adjust_an_invoice(api):
    """A BillingClerk may collect an assessment in full but may not waive it.

    PRD §2.1: "A `BillingClerk` posts payments and refers unpaid penalties to collections, but never adjusts, waives or writes off an assessment."
    PRD §3.8: "Only the program administrator may move assessed money."
    PRD §2.10: "Third, the recognized role must appear in the authorized-role list of the endpoint being called, failing with `ERR_ROLE_NOT_PERMITTED`."
    PRD §3.8: "Settlement — `UNPAID → PAID` or `PARTIALLY_PAID → PAID` — occurs exactly when `paid_cents` plus `adjusted_cents` equals `assessed_cents` after the write, whether that is reached by an allocation covering the remainder or by a `WAIVE` adjustment; `outstanding_cents` becomes 0, the stage resettles to `CURRENT` on the next nightly run, and when every invoice for the premises is `PAID` a `REINSTATEMENT_PENDING` suspension order becomes liftable."

    The refused waive leaves the 5500-cent assessment wholly outstanding with
    adjusted_cents 0 and the invoice revision untouched, while the same clerk's
    5500-cent receipt reaches the identical zero balance through paid_cents.

    Design: Corner/rbac/billing_clerk_cannot_adjust_an_invoice
    """
    bundle = X.setup_program_baseline(
        api, clock=C.CLOCK_STARTUP_UTC, site_overrides={"occupancy_class": "COMMERCIAL"}
    )
    invoice = X.invoices_of_site(api, bundle.site_id, kind="PERMIT_ISSUE_FEE")[0]
    A.assert_invoice_totals(invoice, assessed_cents=5500, outstanding_cents=5500, adjusted_cents=0)

    refused = api.adjust_invoice(
        invoice["id"],
        {
            "adjustment_kind": "WAIVE",
            "reason": "Clerk waiving the fee at the counter.",
            "expected_penalty_invoice_version": invoice["version"],
            "amount_cents": 5500,
        },
        U.BILLING_CLERK,
    )
    validate_error(refused, E.ERR_ROLE_NOT_PERMITTED, expected_status=403)

    unchanged = X.get_invoice(api, invoice["id"])
    A.assert_invoice_totals(
        unchanged,
        assessed_cents=5500,
        adjusted_cents=0,
        paid_cents=0,
        outstanding_cents=5500,
        payment_status="UNPAID",
    )
    A.assert_version_unchanged(invoice, unchanged)

    payment = A.data_of(
        api.create_payment_record(
            F.payment_record_payload(
                bundle.site_id,
                5500,
                "2026-08-01T00:00:00Z",
                X.site_version(api, bundle.site_id),
                method="CHECK",
                allocation_mode="AUTO_WATERFALL",
            ),
            U.BILLING_CLERK,
        ),
        201,
    )
    A.assert_status(payment, "APPLIED")
    A.assert_invoice_totals(
        X.get_invoice(api, invoice["id"]),
        paid_cents=5500,
        adjusted_cents=0,
        outstanding_cents=0,
        payment_status="PAID",
    )


def test_alarm_company_operator_cannot_review_its_own_compliance_report(api):
    """A monitoring company cannot rule on the compliance report it filed.

    PRD §3.10: "**Review.** Program staff rule on a submitted report with a `decision` of `ACCEPT` or `FLAG_VARIANCE` plus optional `variance_notes`."
    PRD §2.10: "Third, the recognized role must appear in the authorized-role list of the endpoint being called, failing with `ERR_ROLE_NOT_PERMITTED`."
    PRD §3.10: "The report is created in `SUBMITTED` with `correction_count` 0 and `reviewed_at`, `reviewed_by_user_id` and `variance_notes` null."
    PRD §3.10: "Either way the result is rounded half up to two decimal places into `reporting_compliance_score`, and an empty score set yields 1.00."

    Only accepted and flagged reports enter the score set, so with the filing
    still unreviewed the company's score set is empty and its
    reporting_compliance_score stays at the 1.00 it was registered with.

    Design: Corner/rbac/alarm_company_operator_cannot_review_its_own_compliance_report
    """
    X.set_clock(api, C.CLOCK_STARTUP_UTC)
    X.create_active_fee_schedule(api)
    company_id = X.create_company(api)
    X.set_clock(api, C.CLOCK_PRESENT_UTC)
    operator = U.alarm_company_operator(company_id)

    report = A.data_of(
        api.create_compliance_report(
            F.compliance_report_payload(
                company_id,
                "2026-08-01T00:00:00Z",
                "2026-08-31T00:00:00Z",
                reported_dispatch_count=3,
                reported_cancellation_count=0,
                ecv_attempt_count=0,
            ),
            operator,
        ),
        201,
    )
    A.assert_status(report, "SUBMITTED")

    refused = api.review_compliance_report(
        report["id"],
        {"decision": "ACCEPT", "variance_notes": "Operator self-accepting its own filing."},
        operator,
    )
    validate_error(refused, E.ERR_ROLE_NOT_PERMITTED, expected_status=403)

    after = X.get_report(api, report["id"])
    A.assert_status(after, "SUBMITTED")
    assert after["reviewed_at"] is None, (
        f"reviewed_at must still be null, got {after['reviewed_at']!r}"
    )
    assert after["reviewed_by_user_id"] is None, (
        f"reviewed_by_user_id must still be null, got {after['reviewed_by_user_id']!r}"
    )
    assert after["correction_count"] == 0, (
        f"correction_count must still be 0, got {after['correction_count']}"
    )
    A.assert_version_unchanged(report, after)

    company = X.get_company(api, company_id)
    A.assert_score_2dp(company["reporting_compliance_score"], 1.00, "reporting_compliance_score")
    assert company["consecutive_flagged_report_count"] == 0, (
        "consecutive_flagged_report_count must still be 0, got "
        f"{company['consecutive_flagged_report_count']}"
    )


def test_alarm_user_cannot_move_the_program_clock(api):
    """A premises owner can neither advance the logical clock nor trigger the nightly program run.

    PRD §2.1: "The role owns program configuration, suspension orders, administrative voids, invoice adjustments and every override, and it is the only role permitted to move the logical clock or trigger the nightly program batch."
    PRD §2.10: "Third, the recognized role must appear in the authorized-role list of the endpoint being called, failing with `ERR_ROLE_NOT_PERMITTED`."
    PRD §2.6: "The server holds a **logical clock** whose startup value is exactly `2026-08-01T00:00:00Z`, and it never falls back to real time; an administrator moves it by supplying a `current_utc` instant, and the clock then reads that value for every subsequent window, deadline, expiry and delinquency computation."
    PRD §2.6: "Time-driven state changes are instead applied by an administrator-only **nightly program run**, a batch capability that takes no input and, at the current logical clock, walks the whole program in one pass."

    The refused batch runs nothing, so the outstanding issue-fee invoice stays at
    the opening dunning stage with no days delinquent, and the premises' permit
    is still live; the clock is provably unmoved because the next administrator
    write is stamped at 2026-08-01T00:00:00Z.

    Design: Corner/rbac/alarm_user_cannot_move_the_program_clock
    """
    bundle = X.setup_program_baseline(
        api, clock=C.CLOCK_STARTUP_UTC, site_overrides={"occupancy_class": "COMMERCIAL"}
    )
    holder = U.alarm_user(bundle.site_id)

    refused_clock = api.set_clock({"current_utc": "2027-01-01T00:00:00Z"}, holder)
    validate_error(refused_clock, E.ERR_ROLE_NOT_PERMITTED, expected_status=403)

    refused_nightly = api.run_nightly(holder)
    validate_error(refused_nightly, E.ERR_ROLE_NOT_PERMITTED, expected_status=403)

    stamped = A.data_of(
        api.create_site_contact(
            F.site_contact_payload(
                bundle.site_id,
                full_name="Rosalind Achebe",
                phone_number="+12145550399",
                contact_priority=3,
            ),
            U.PROGRAM_ADMIN,
        ),
        201,
    )
    assert str(stamped["created_at"]).startswith("2026-08-01T00:00:00"), (
        "the clock must still read 2026-08-01T00:00:00Z, but the next write was stamped "
        f"{stamped['created_at']!r}"
    )

    invoice = X.invoices_of_site(api, bundle.site_id, kind="PERMIT_ISSUE_FEE")[0]
    A.assert_invoice_totals(invoice, outstanding_cents=5500, collections_stage="CURRENT")
    assert invoice["days_delinquent"] == 0, (
        f"days_delinquent must still be 0, got {invoice['days_delinquent']}"
    )
    A.assert_money_cents(invoice["late_penalty_cents"], 0, "late_penalty_cents")
    A.assert_status(X.get_permit(api, bundle.permit_id), "ACTIVE")


def test_alarm_user_cannot_read_another_premises_incident(api):
    """A premises owner reading a neighbour's incident or roster entry is refused as a non-owner, not as a missing row.

    PRD §2.1: "When `X-User-Role` is `AlarmUser`, `X-User-ID` is the `id` of the acting `AlarmSite`; ownership checks on any resource that references a premises compare the resource's premises reference to `X-User-ID`, whether that reference is the site itself or the site reachable from the target system, permit, incident, appeal, invoice, payment or allocation."
    PRD §2.1: "A mismatch in either direction is rejected with `ERR_NOT_RESOURCE_OWNER`."

    The neighbouring premises exists and its identity is a real site id, so the
    refusal is about the aggregate the row belongs to; the same two reads
    performed by the owning premises succeed unchanged.

    Design: Corner/rbac/alarm_user_cannot_read_another_premises_incident
    """
    bundle = X.setup_program_baseline(api, site_overrides={"occupancy_class": "COMMERCIAL"})
    other_site_id = X.create_site(api, address_key="88-ELM-AVE-75204")
    incident = X.create_reported_incident(api, bundle, bundle.system_id, "2026-09-15T03:09:00Z")
    X.set_clock(api, "2026-09-20T01:00:00Z")
    X.determine_counted(api, incident.incident_id)

    contact_id = bundle.contact_ids[0]
    neighbour = U.alarm_user(other_site_id)
    owner = U.alarm_user(bundle.site_id)

    incident_before = X.get_incident(api, incident.incident_id)
    contact_before = A.data_of(api.get_site_contact(contact_id, owner))

    validate_error(
        api.get_false_alarm_incident(incident.incident_id, neighbour),
        E.ERR_NOT_RESOURCE_OWNER,
        expected_status=403,
    )
    validate_error(
        api.get_site_contact(contact_id, neighbour),
        E.ERR_NOT_RESOURCE_OWNER,
        expected_status=403,
    )

    owned_incident = A.data_of(api.get_false_alarm_incident(incident.incident_id, owner))
    owned_contact = A.data_of(api.get_site_contact(contact_id, owner))
    assert owned_incident == incident_before, (
        "the owner's read must return the incident exactly as it stood before the refused reads"
    )
    assert owned_contact == contact_before, (
        "the owner's read must return the roster entry exactly as it stood before the refused reads"
    )
    A.assert_status(owned_incident, "COUNTED")


def test_alarm_company_operator_cannot_lodge_a_dispatch_for_another_companys_system(api):
    """A rival central station cannot lodge a dispatch request for a panel it does not monitor.

    PRD §2.1: "When `X-User-Role` is `AlarmCompanyOperator`, `X-User-ID` is the `id` of the acting `AlarmCompany`; ownership checks compare the company reachable from the target resource — the company itself, or the monitoring company of the target system, dispatch request or compliance report — to `X-User-ID`."
    PRD §2.1: "A mismatch in either direction is rejected with `ERR_NOT_RESOURCE_OWNER`."
    PRD §3.10: "The company is created in `ACTIVE` with `reporting_compliance_score` at 1.00, `probation_started_at`, `status_reason` and `last_status_action_at` all null, and its derived counters recomputed: `monitored_system_count` as the number of systems it monitors in `SUBMITTED`, `PERMITTED` or `UNPERMITTED`, `dispatch_request_count_lifetime` as the number of dispatch requests it has lodged across every status, and `consecutive_flagged_report_count` as the length of the most-recent unbroken run of its reports ending in `VARIANCE_FLAGGED`, taken in order of `period_start` ascending."

    There is no company identifier in the path, so the ownership comparison
    reaches through the payload to the target system's monitoring company; the
    identical body succeeds for the monitoring company itself.

    Design: Corner/rbac/alarm_company_operator_cannot_lodge_a_dispatch_for_another_companys_system
    """
    bundle = X.setup_program_baseline(api, site_overrides={"occupancy_class": "COMMERCIAL"})
    rival_id = X.create_company(api, legal_name="Rival Central Station Co", license_number="TXALM-77002")

    occurred_at = "2026-09-15T03:09:00Z"
    payload = F.dispatch_request_payload(
        bundle.system_id,
        occurred_at,
        call_attempts=[
            F.call_attempt(bundle.contact_ids[0], "2026-09-15T03:10:00Z", "NO_ANSWER"),
            F.call_attempt(bundle.contact_ids[1], "2026-09-15T03:11:00Z", "NO_ANSWER"),
        ],
        idempotency_key="rival-0915-a",
    )

    refused = api.create_dispatch_request(payload, U.alarm_company_operator(rival_id))
    # §2.1 pins `ERR_NOT_RESOURCE_OWNER` for the operator/monitoring-company
    # mismatch while §3.4 pins `ERR_COMPANY_NOT_SYSTEM_MONITOR` for the same
    # submission; PRD names both, so either refusal is faithful.
    validate_error_is_one_of(
        refused,
        [E.ERR_NOT_RESOURCE_OWNER, E.ERR_COMPANY_NOT_SYSTEM_MONITOR],
    )

    A.assert_total_count(
        api.list_dispatch_requests(U.DISPATCH_SUPERVISOR, {"alarm_system_id": bundle.system_id}), 0
    )
    rival = X.get_company(api, rival_id)
    assert rival["dispatch_request_count_lifetime"] == 0, (
        "the rival must have lodged nothing, got "
        f"{rival['dispatch_request_count_lifetime']}"
    )

    accepted = A.data_of(
        api.create_dispatch_request(payload, U.alarm_company_operator(bundle.company_id)), 201
    )
    A.assert_status(accepted, "SUBMITTED")
    assert accepted["monitoring_company_id"] == bundle.company_id, (
        "the accepted request must denormalize the monitoring company, got "
        f"{accepted['monitoring_company_id']!r}"
    )


def test_alarm_company_operator_cannot_correct_another_companys_compliance_report(api):
    """A rival monitoring company can neither correct nor read another company's flagged report.

    PRD §3.10: "Only the company itself may correct, else `ERR_NOT_RESOURCE_OWNER`; at least one of the resupplied metrics must differ from the stored value, else `ERR_NO_REPORTABLE_VARIANCE`; and `correction_count` must be strictly below 2 as evaluated **before** the increment, else `ERR_CORRECTION_LIMIT_REACHED` — so a report may be corrected twice and no more."
    PRD §2.1: "A mismatch in either direction is rejected with `ERR_NOT_RESOURCE_OWNER`."
    PRD §3.10: "The correction overwrites the reported counts, increments `correction_count`, and recomputes `variance_count`, `variance_pct`, `period_accuracy`, `period_ecv_rate` and `period_score` from scratch."

    Design: Corner/rbac/alarm_company_operator_cannot_correct_another_companys_compliance_report
    """
    X.set_clock(api, C.CLOCK_STARTUP_UTC)
    X.create_active_fee_schedule(api)
    filer_id = X.create_company(api, legal_name="Guardian Signal Monitoring LLC", license_number="TXALM-44120")
    rival_id = X.create_company(api, legal_name="Rival Central Station Co", license_number="TXALM-77002")
    X.set_clock(api, C.CLOCK_PRESENT_UTC)

    report = A.data_of(
        api.create_compliance_report(
            F.compliance_report_payload(
                filer_id,
                "2026-08-01T00:00:00Z",
                "2026-08-31T00:00:00Z",
                reported_dispatch_count=3,
                reported_cancellation_count=0,
                ecv_attempt_count=0,
            ),
            U.alarm_company_operator(filer_id),
        ),
        201,
    )
    flagged = A.data_of(
        api.review_compliance_report(
            report["id"],
            {
                "decision": "FLAG_VARIANCE",
                "variance_notes": "Three dispatches reported for a month with none on record.",
            },
            U.REVIEW_OFFICER,
        )
    )
    A.assert_status(flagged, "VARIANCE_FLAGGED")
    filer_before = X.get_company(api, filer_id)

    rival = U.alarm_company_operator(rival_id)
    validate_error(
        api.correct_compliance_report(
            report["id"],
            {
                "reported_dispatch_count": 0,
                "reported_cancellation_count": 0,
                "ecv_attempt_count": 0,
            },
            rival,
        ),
        E.ERR_NOT_RESOURCE_OWNER,
        expected_status=403,
    )
    validate_error(
        api.get_compliance_report(report["id"], rival),
        E.ERR_NOT_RESOURCE_OWNER,
        expected_status=403,
    )

    after = X.get_report(api, report["id"])
    A.assert_status(after, "VARIANCE_FLAGGED")
    assert after["correction_count"] == 0, (
        f"correction_count must still be 0, got {after['correction_count']}"
    )
    assert after["reported_dispatch_count"] == 3, (
        f"reported_dispatch_count must still be 3, got {after['reported_dispatch_count']}"
    )
    assert after["reported_cancellation_count"] == 0, (
        f"reported_cancellation_count must still be 0, got {after['reported_cancellation_count']}"
    )
    assert after["ecv_attempt_count"] == 0, (
        f"ecv_attempt_count must still be 0, got {after['ecv_attempt_count']}"
    )
    A.assert_version_unchanged(flagged, after)

    filer_after = X.get_company(api, filer_id)
    A.assert_score_2dp(
        filer_after["reporting_compliance_score"],
        float(filer_before["reporting_compliance_score"]),
        "reporting_compliance_score",
    )
    assert (
        filer_after["consecutive_flagged_report_count"]
        == filer_before["consecutive_flagged_report_count"]
    ), "consecutive_flagged_report_count must be untouched by the refused calls"


def test_request_with_a_missing_x_user_role_header_is_unauthenticated(api):
    """A missing or empty authentication header answers 401 ahead of every path resolution.

    PRD §2.1: "Every request to the service must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the capacity in which the caller is acting."
    PRD §2.1: "If either header is absent or empty the request is rejected with `ERR_MISSING_AUTH_HEADERS` before the body is parsed, before any path segment is resolved, and before any role lookup happens."
    PRD §2.10: "First, both `X-User-Role` and `X-User-ID` must be present and non-empty, before any body parsing, path resolution or role lookup, failing with `ERR_MISSING_AUTH_HEADERS`."
    PRD §2.10: "Every identifier embedded in the request path must resolve, checked strictly left to right so the leftmost unknown segment wins, and then every foreign reference supplied in the body must resolve, checked in declared input order."

    The second call names a premises that does not exist, yet the header failure
    at the first position answers before the sixth position could report the
    missing row; supplying both headers turns the same two calls into a 200 and a
    404.

    Design: Corner/rbac/request_with_a_missing_x_user_role_header_is_unauthenticated
    """
    X.set_clock(api, C.CLOCK_STARTUP_UTC)
    X.create_active_fee_schedule(api)
    site_id = X.create_site(api, address_key="1200-MAIN-ST-75201", occupancy_class="COMMERCIAL")

    validate_error(
        api.get_alarm_site(site_id, U.MISSING_ROLE_HEADERS),
        E.ERR_MISSING_AUTH_HEADERS,
        expected_status=401,
    )
    validate_error(
        api.get_alarm_site(NON_EXISTENT_UUID, U.headers_for("PermitClerk", "")),
        E.ERR_MISSING_AUTH_HEADERS,
        expected_status=401,
    )

    present = A.data_of(api.get_alarm_site(site_id, U.PERMIT_CLERK))
    assert present["id"] == site_id, "the authenticated read must return the premises"
    validate_error(
        api.get_alarm_site(NON_EXISTENT_UUID, U.PERMIT_CLERK),
        E.ERR_ALARM_SITE_NOT_FOUND,
        expected_status=404,
    )


def test_unrecognized_role_header_is_rejected_as_an_unknown_role(api):
    """An undeclared or mis-cased role name is 401 unknown-role rather than 403 not-permitted.

    PRD §2.1: "If both headers are present but `X-User-Role` does not match one of the eight declared role names exactly, case included, the request is rejected with `ERR_UNKNOWN_ROLE`."
    PRD §2.1: "The eight roles are `ProgramAdministrator`, `PermitClerk`, `AlarmCompanyOperator`, `AlarmUser`, `PoliceDispatchSupervisor`, `FalseAlarmReviewOfficer`, `HearingOfficer` and `BillingClerk`."
    PRD §2.10: "Second, `X-User-Role` must name one of the eight roles with an exact case-sensitive match, failing with `ERR_UNKNOWN_ROLE`; an unrecognized role string is rejected here, before per-endpoint permission is consulted."

    The second call spells the administrator role entirely in lower case, which
    is not an exact match, so it never reaches the endpoint's permission list and
    the already-active schedule is not activated a second time.

    Design: Corner/rbac/unrecognized_role_header_is_rejected_as_an_unknown_role
    """
    X.set_clock(api, C.CLOCK_STARTUP_UTC)
    schedule_id = X.create_active_fee_schedule(api)
    site_id = X.create_site(api, address_key="1200-MAIN-ST-75201", occupancy_class="COMMERCIAL")
    before = A.data_of(api.get_fee_schedule(schedule_id, U.PROGRAM_ADMIN))
    A.assert_status(before, "ACTIVE")

    validate_error(
        api.get_alarm_site(site_id, U.headers_for("FireMarshal", "fm-01")),
        E.ERR_UNKNOWN_ROLE,
        expected_status=401,
    )
    validate_error(
        api.activate_fee_schedule(schedule_id, U.headers_for("programadministrator", "pa-01")),
        E.ERR_UNKNOWN_ROLE,
        expected_status=401,
    )

    after = A.data_of(api.get_fee_schedule(schedule_id, U.PROGRAM_ADMIN))
    A.assert_status(after, "ACTIVE")
    A.assert_version_unchanged(before, after)
    A.assert_total_count(api.list_fee_schedules(U.PROGRAM_ADMIN, {"status": "ACTIVE"}), 1)


def test_the_officer_who_determined_the_incident_cannot_decide_its_appeal(api):
    """The reviewer who stamped COUNTED may preside over the appeal's session yet may not decide it.

    PRD §2.11: "Deciding an appeal is barred to the operator whose identifier is recorded as the incident's `determined_by_user_id`, and equally barred to the operator recorded as the appeal's `filed_by_user_id` — the officer who ruled cannot review the ruling, and the filer cannot decide their own petition."
    PRD §3.6: "The decider must be the officer of the docket that heard the appeal, meaning the acting `X-User-ID` equals the `hearing_officer_user_id` of the docket named by the appeal's `hearing_docket_id`, else `ERR_NOT_DOCKET_OFFICER`."
    PRD §3.6: "And nobody reviews their own work: the deciding `X-User-ID` must differ both from the appealed incident's `determined_by_user_id` and from the appeal's `filed_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.6: "Holding the session is the officer's own act: only the caller whose `X-User-ID` equals the docket's `hearing_officer_user_id` may do it, else `ERR_NOT_DOCKET_OFFICER`; the logical clock must have reached `session_start`, the boundary inclusive, else `ERR_HEARING_SESSION_NOT_STARTED`; and the docket must seat at least one appeal, else `ERR_DOCKET_EMPTY`."

    The docket genuinely belongs to the same operator, so the docket-officer rule
    is satisfied and the refusal can only come from the segregation pairing; the
    hold-session that the same operator performed a moment earlier proves the
    conflict is scoped to the decision and not to presiding. The appealed
    occurrence is the premises' first chargeable one, so its assessed fee stands
    at 0 cents throughout.

    Design: Corner/rbac/the_officer_who_determined_the_incident_cannot_decide_its_appeal
    """
    bundle = X.setup_program_baseline(api, site_overrides={"occupancy_class": "COMMERCIAL"})
    incident = X.create_reported_incident(api, bundle, bundle.system_id, "2026-09-15T03:09:00Z")
    ruled = X.determine_counted(api, incident.incident_id)
    assert ruled["determined_by_user_id"] == U.REVIEW_OFFICER_ID, (
        "the determination must be stamped with the reviewing officer, got "
        f"{ruled['determined_by_user_id']!r}"
    )
    A.assert_money_cents(ruled["assessed_fee_cents"], 0, "assessed_fee_cents")

    appeal_id = X.file_appeal(api, bundle, incident.incident_id)
    docket_id = X.create_docket(
        api,
        "2026-10-06T09:00:00Z",
        "2026-10-06T11:00:00Z",
        officer_user_id=U.REVIEW_OFFICER_ID,
        headers=U.PROGRAM_ADMIN,
        location="City Hall Room 210",
    )
    X.schedule_appeal(api, appeal_id, docket_id, headers=U.PROGRAM_ADMIN)
    X.set_clock(api, "2026-10-06T09:00:00Z")

    conflicted_officer = U.headers_for("HearingOfficer", U.REVIEW_OFFICER_ID)
    held = X.hold_session(api, docket_id, headers=conflicted_officer)
    A.assert_status(held, "HELD")

    appeal_before = X.get_appeal(api, appeal_id)
    A.assert_status(appeal_before, "HEARD")

    validate_error(
        api.decide_appeal(
            appeal_id,
            {
                "decision": "GRANTED",
                "findings": "Reviewer revisiting his own determination from the bench.",
            },
            conflicted_officer,
        ),
        E.ERR_SEGREGATION_OF_DUTIES,
        expected_status=403,
    )

    appeal_after = X.get_appeal(api, appeal_id)
    A.assert_status(appeal_after, "HEARD")
    assert appeal_after["decision"] is None, (
        f"decision must still be null, got {appeal_after['decision']!r}"
    )
    assert appeal_after["decided_by_user_id"] is None, (
        f"decided_by_user_id must still be null, got {appeal_after['decided_by_user_id']!r}"
    )
    A.assert_version_unchanged(appeal_before, appeal_after)

    incident_after = X.get_incident(api, incident.incident_id)
    A.assert_status(incident_after, "APPEALED")
    A.assert_money_cents(incident_after["assessed_fee_cents"], 0, "assessed_fee_cents")
    assert incident_after["determined_by_user_id"] == U.REVIEW_OFFICER_ID, (
        "the original determination must be untouched by the refused decision"
    )
    A.assert_status(A.data_of(api.get_hearing_docket(docket_id, U.PROGRAM_ADMIN)), "HELD")


def test_the_supervisor_who_validated_the_request_cannot_determine_its_incident(api):
    """The conflict follows the operator across a role change: the validator of the signal cannot price it.

    PRD §2.11: "Determining an incident is barred to the operator recorded as `validated_by_user_id` on the dispatch request the incident came from, so the supervisor who released the patrol does not also judge whether the alarm was false."
    PRD §2.11: "The unit's controls rest on the principle that nobody reviews their own work."
    PRD §2.10: "Then the segregation-of-duties pairings of §2.11 are enforced with `ERR_SEGREGATION_OF_DUTIES`."

    Both endpoints accept the operator's role, so nothing but the pairing can
    refuse the determination; a colleague who validated nothing then rules on the
    very same incident and stamps it as the premises' first chargeable
    occurrence, index 1.

    Design: Corner/rbac/the_supervisor_who_validated_the_request_cannot_determine_its_incident
    """
    bundle = X.setup_program_baseline(api, site_overrides={"occupancy_class": "COMMERCIAL"})
    request_id = X.submit_dispatch_request(api, bundle, bundle.system_id, "2026-09-15T03:09:00Z")
    dual_supervisor = U.headers_for("PoliceDispatchSupervisor", U.DUAL_ROLE_ID)
    validated = A.data_of(api.validate_dispatch_request(request_id, dual_supervisor))
    assert validated["validated_by_user_id"] == U.DUAL_ROLE_ID, (
        f"validated_by_user_id must record the acting supervisor, got {validated['validated_by_user_id']!r}"
    )
    validate_success(api.record_dispatch(request_id, U.DISPATCH_SUPERVISOR))
    incident = A.data_of(
        api.create_false_alarm_incident(
            F.false_alarm_incident_payload(request_id), U.DISPATCH_SUPERVISOR
        ),
        201,
    )
    A.assert_status(incident, "REPORTED")
    site_before = X.get_site(api, bundle.site_id)

    validate_error(
        api.determine_incident(
            incident["id"],
            F.determination_payload(
                "COUNTED",
                review_notes="Same officer pricing the signal he cleared for dispatch.",
            ),
            U.headers_for("FalseAlarmReviewOfficer", U.DUAL_ROLE_ID),
        ),
        E.ERR_SEGREGATION_OF_DUTIES,
        expected_status=403,
    )

    after = X.get_incident(api, incident["id"])
    A.assert_status(after, "REPORTED")
    assert after["occurrence_index"] is None, (
        f"occurrence_index must still be null, got {after['occurrence_index']!r}"
    )
    assert after["assessed_fee_cents"] is None, (
        f"assessed_fee_cents must still be null, got {after['assessed_fee_cents']!r}"
    )
    assert after["determination"] is None, (
        f"determination must still be null, got {after['determination']!r}"
    )
    A.assert_version_unchanged(incident, after)
    assert X.invoices_of_site(api, bundle.site_id, kind="FALSE_ALARM_FEE") == [], (
        "a refused determination must assess no false alarm fee"
    )

    site_after = X.get_site(api, bundle.site_id)
    assert site_after["chargeable_count_window"] == 0, (
        f"chargeable_count_window must still be 0, got {site_after['chargeable_count_window']}"
    )
    A.assert_version_unchanged(site_before, site_after)

    ruled = A.data_of(
        api.determine_incident(
            incident["id"],
            F.determination_payload(
                "COUNTED", review_notes="Independent reviewer with no prior involvement."
            ),
            U.REVIEW_OFFICER,
        )
    )
    A.assert_status(ruled, "COUNTED")
    assert ruled["occurrence_index"] == 1, (
        f"occurrence_index expected 1, got {ruled['occurrence_index']}"
    )


def test_the_administrator_who_posted_the_payment_cannot_adjust_that_invoice(api):
    """The administrator whose identifier is stamped on a posted payment cannot reduce the invoice it paid.

    PRD §2.11: "Adjusting an invoice is barred to any operator whose identifier appears as `recorded_by_user_id` on a payment already posted against that invoice, which is why money movement (posting payments, referring to collections) sits with the `BillingClerk` while money reduction (waive, reduce, write off) sits exclusively with the `ProgramAdministrator`."
    PRD §3.9: "The accepted payment is created in `APPLIED` with the next sequential `receipt_number` in the form RCT-000001 and `recorded_by_user_id` taken from the acting `X-User-ID` — that stamp is what later bars the same person from adjusting the invoice they collected on."
    PRD §3.8: "The invoice revision must still match, else `ERR_STALE_PENALTY_INVOICE_VERSION`; a written-off invoice may not be adjusted again, else `ERR_INVOICE_WRITTEN_OFF`; the adjusting `X-User-ID` must differ from every `recorded_by_user_id` of a payment already posted to that invoice, else `ERR_SEGREGATION_OF_DUTIES`; and the amount must fit — a `WAIVE` or `REDUCE` may not exceed the invoice's current `outstanding_cents`, and a `WRITE_OFF` is taken at exactly `outstanding_cents`, else `ERR_ADJUSTMENT_EXCEEDS_OUTSTANDING`."
    PRD §3.8: "The adjustment raises `adjusted_cents` and recomputes `outstanding_cents`; a `WAIVE` that closes the gap settles `payment_status` to `PAID`; a `WRITE_OFF` requires the stage to be `REFERRED` and moves it to the terminal `WRITTEN_OFF`, adding the whole outstanding amount to `adjusted_cents`, zeroing `outstanding_cents`, and removing the invoice from the premises' balance and from every allocation candidate set."

    The issue invoice is assessed at 5000 plus the 500 administrative fee, so a
    1000-cent tender leaves 5500 - 1000 = 4500 outstanding. The refused
    adjustment supplies the invoice's current revision, so the revision guard
    cannot be what answers; a colleague holding the same role then waives the
    whole 4500 remaining, taking adjusted_cents to 4500 and outstanding_cents
    to 0.

    Design: Corner/rbac/the_administrator_who_posted_the_payment_cannot_adjust_that_invoice
    """
    bundle = X.setup_program_baseline(
        api, clock=C.CLOCK_STARTUP_UTC, site_overrides={"occupancy_class": "COMMERCIAL"}
    )
    invoice = X.invoices_of_site(api, bundle.site_id, kind="PERMIT_ISSUE_FEE")[0]
    A.assert_invoice_totals(invoice, assessed_cents=5500, outstanding_cents=5500)

    collector = U.headers_for("ProgramAdministrator", U.DUAL_ROLE_ID)
    payment = A.data_of(
        api.create_payment_record(
            F.payment_record_payload(
                bundle.site_id, 1000, "2026-08-01T00:00:00Z", X.site_version(api, bundle.site_id)
            ),
            collector,
        ),
        201,
    )
    A.assert_status(payment, "APPLIED")
    assert payment["recorded_by_user_id"] == U.DUAL_ROLE_ID, (
        f"recorded_by_user_id must be the acting operator, got {payment['recorded_by_user_id']!r}"
    )
    A.assert_money_cents(payment["allocated_cents"], 1000, "allocated_cents")

    paid = X.get_invoice(api, invoice["id"])
    A.assert_invoice_totals(
        paid, assessed_cents=5500, paid_cents=1000, adjusted_cents=0, outstanding_cents=4500
    )

    validate_error(
        api.adjust_invoice(
            invoice["id"],
            {
                "adjustment_kind": "WRITE_OFF",
                "reason": "Writing off the balance I just collected against.",
                "expected_penalty_invoice_version": paid["version"],
            },
            collector,
        ),
        E.ERR_SEGREGATION_OF_DUTIES,
        expected_status=403,
    )

    unchanged = X.get_invoice(api, invoice["id"])
    A.assert_invoice_totals(
        unchanged,
        assessed_cents=5500,
        paid_cents=1000,
        adjusted_cents=0,
        outstanding_cents=4500,
        payment_status="PARTIALLY_PAID",
    )
    A.assert_version_unchanged(paid, unchanged)
    A.assert_outstanding_identity(unchanged)

    waived = A.data_of(
        api.adjust_invoice(
            invoice["id"],
            {
                "adjustment_kind": "WAIVE",
                "reason": "Balance waived by an administrator who collected nothing on it.",
                "expected_penalty_invoice_version": unchanged["version"],
                # PRD §3.8: a WAIVE takes an `amount_cents`, here the whole
                # 4500-cent balance left after the 1000-cent payment.
                "amount_cents": 4500,
            },
            U.PROGRAM_ADMIN,
        )
    )
    A.assert_invoice_totals(
        waived,
        assessed_cents=5500,
        paid_cents=1000,
        adjusted_cents=4500,
        outstanding_cents=0,
        payment_status="PAID",
    )


def test_a_hearing_officer_who_does_not_preside_cannot_decide_the_appeal(api):
    """A hearing officer with no conflict of interest is still refused the decision on another officer's docket.

    PRD §3.6: "The decider must be the officer of the docket that heard the appeal, meaning the acting `X-User-ID` equals the `hearing_officer_user_id` of the docket named by the appeal's `hearing_docket_id`, else `ERR_NOT_DOCKET_OFFICER`."
    PRD §2.10: "Then docket ownership: only the officer named on a docket may hold that session or decide an appeal heard on it, failing with `ERR_NOT_DOCKET_OFFICER`."
    PRD §3.6: "All three branches record `decision`, `decided_at`, `decided_by_user_id` and `findings`, and all three are terminal for the appeal row."

    The refused caller neither ruled on the incident nor filed the appeal, so the
    segregation pairing is satisfied and only the docket binding can answer; the
    officer the docket names then decides the same appeal, and the docket remains
    held either way.

    Design: Corner/rbac/a_hearing_officer_who_does_not_preside_cannot_decide_the_appeal
    """
    bundle = X.setup_program_baseline(api, site_overrides={"occupancy_class": "COMMERCIAL"})
    incident = X.create_reported_incident(api, bundle, bundle.system_id, "2026-09-15T03:09:00Z")
    X.determine_counted(api, incident.incident_id)
    appeal_id, docket_id = X.create_heard_appeal(
        api,
        bundle,
        incident.incident_id,
        session_start="2026-10-05T14:00:00Z",
        session_end="2026-10-05T16:00:00Z",
    )
    before = X.get_appeal(api, appeal_id)
    A.assert_status(before, "HEARD")

    validate_error(
        api.decide_appeal(
            appeal_id,
            {
                "decision": "GRANTED",
                "findings": "A different officer ruling on someone else's calendar.",
            },
            U.headers_for("HearingOfficer", "ho-09"),
        ),
        E.ERR_NOT_DOCKET_OFFICER,
        expected_status=403,
    )

    after = X.get_appeal(api, appeal_id)
    A.assert_status(after, "HEARD")
    assert after["decision"] is None, f"decision must still be null, got {after['decision']!r}"
    assert after["findings"] is None, f"findings must still be null, got {after['findings']!r}"
    assert after["rehearing_depth"] == before["rehearing_depth"], (
        "rehearing_depth must not move, was "
        f"{before['rehearing_depth']}, now {after['rehearing_depth']}"
    )
    A.assert_version_unchanged(before, after)
    A.assert_status(A.data_of(api.get_hearing_docket(docket_id, U.PROGRAM_ADMIN)), "HELD")

    decided = A.data_of(
        api.decide_appeal(
            appeal_id,
            {
                "decision": "GRANTED",
                "findings": "The utility outage records support the appellant.",
                "exempt_cause_code": "UTILITY_POWER_FAILURE",
            },
            U.HEARING_OFFICER,
        )
    )
    A.assert_status(decided, "GRANTED")
    assert decided["decided_by_user_id"] == U.HEARING_OFFICER_ID, (
        f"decided_by_user_id expected {U.HEARING_OFFICER_ID}, got {decided['decided_by_user_id']!r}"
    )
    A.assert_status(A.data_of(api.get_hearing_docket(docket_id, U.PROGRAM_ADMIN)), "HELD")


def test_a_hearing_officer_who_does_not_preside_cannot_hold_the_session(api):
    """Holding a session is refused to any officer but the one the docket names, ahead of the calendar checks.

    PRD §3.6: "Holding the session is the officer's own act: only the caller whose `X-User-ID` equals the docket's `hearing_officer_user_id` may do it, else `ERR_NOT_DOCKET_OFFICER`; the logical clock must have reached `session_start`, the boundary inclusive, else `ERR_HEARING_SESSION_NOT_STARTED`; and the docket must seat at least one appeal, else `ERR_DOCKET_EMPTY`."
    PRD §2.10: "Then docket ownership: only the officer named on a docket may hold that session or decide an appeal heard on it, failing with `ERR_NOT_DOCKET_OFFICER`."
    PRD §3.6: "On success the appeal moves to `SCHEDULED` with its `hearing_docket_id` set, and the docket's `scheduled_appeal_count` and `version` each rise by 1."
    PRD §3.6: "A docket may be held from either `OPEN` or `CLOSED_FOR_SCHEDULING` under identical preconditions and with identical effects: `held_at` is stamped with the logical clock, the docket becomes `HELD`, which is terminal, its `version` rises by 1, and every appeal on it in `SCHEDULED` advances to `HEARD`, becoming decidable."

    The clock stands exactly at session_start and one appeal is seated, so the
    two calendar preconditions are both satisfied and the identity check is the
    only gate left; the docket keeps its single seat and stays open.

    Design: Corner/rbac/a_hearing_officer_who_does_not_preside_cannot_hold_the_session
    """
    bundle = X.setup_program_baseline(api, site_overrides={"occupancy_class": "COMMERCIAL"})
    incident = X.create_reported_incident(api, bundle, bundle.system_id, "2026-09-15T03:09:00Z")
    X.determine_counted(api, incident.incident_id)
    appeal_id = X.file_appeal(api, bundle, incident.incident_id)
    docket_id = X.create_docket(api, "2026-10-05T14:00:00Z", "2026-10-05T16:00:00Z")
    X.schedule_appeal(api, appeal_id, docket_id)
    X.set_clock(api, "2026-10-05T14:00:00Z")

    before = A.data_of(api.get_hearing_docket(docket_id, U.PROGRAM_ADMIN))
    A.assert_status(before, "OPEN")
    assert before["scheduled_appeal_count"] == 1, (
        f"scheduled_appeal_count expected 1, got {before['scheduled_appeal_count']}"
    )

    validate_error(
        api.hold_session(docket_id, {}, U.headers_for("HearingOfficer", "ho-09")),
        E.ERR_NOT_DOCKET_OFFICER,
        expected_status=403,
    )

    after = A.data_of(api.get_hearing_docket(docket_id, U.PROGRAM_ADMIN))
    A.assert_status(after, "OPEN")
    assert after["held_at"] is None, f"held_at must still be null, got {after['held_at']!r}"
    assert after["scheduled_appeal_count"] == 1, (
        f"scheduled_appeal_count must still be 1, got {after['scheduled_appeal_count']}"
    )
    A.assert_version_unchanged(before, after)
    A.assert_status(X.get_appeal(api, appeal_id), "SCHEDULED")
