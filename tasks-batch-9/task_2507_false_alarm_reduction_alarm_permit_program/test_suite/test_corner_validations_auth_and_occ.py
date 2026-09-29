"""Validation-family coverage: admission headers, endpoint role permission, payload
shape, referential existence, entity-backed ownership, segregation of duties, docket
ownership, the six revision guards and the state / occupancy gates."""
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

# A second fabricated identifier, so a request can carry two unknown references at
# once and the answer can show which of them the service reports.
OTHER_NON_EXISTENT_UUID = "55555555-5555-4555-8555-555555555555"


def test_alarm_site_read_missing_x_user_id_header_returns_401(api):
    """A premises read that omits X-User-ID is refused before the path id is resolved.

    "Every request to the service must carry two headers: `X-User-ID`, identifying the
    caller, and `X-User-Role`, naming the capacity in which the caller is acting. If
    either header is absent or empty the request is rejected with
    `ERR_MISSING_AUTH_HEADERS` before the body is parsed, before any path segment is
    resolved, and before any role lookup happens." (PRD §2.1)

    "**Positions 6 and 7 — existence.** Every identifier embedded in the request path
    must resolve, checked strictly left to right so the leftmost unknown segment wins"
    (PRD §2.10) — so replaying the header-less read against a fabricated premises id
    must still answer position 1 and never the 404.

    Design: Corner/validations/alarm_site_read_missing_x_user_id_header_returns_401
    """
    X.set_clock(api, C.CLOCK_STARTUP_UTC)
    X.create_active_fee_schedule(api)
    site_id = X.create_site(api)

    headerless = {k: v for k, v in U.PERMIT_CLERK.items() if k != "X-User-ID"}

    response = api.get_alarm_site(site_id, headerless)
    validate_error(response, E.ERR_MISSING_AUTH_HEADERS, expected_status=401)
    assert set(response.json()["data"]) == {"error_id", "message"}, (
        "an error envelope carries only error_id and message, never the premises body"
    )

    unknown = api.get_alarm_site(NON_EXISTENT_UUID, headerless)
    validate_error(unknown, E.ERR_MISSING_AUTH_HEADERS, expected_status=401)


def test_alarm_site_read_with_an_unrecognized_role_header_is_unauthenticated(api):
    """An unknown role string is rejected at admission, one step before permission.

    "If both headers are present but `X-User-Role` does not match one of the eight
    declared role names exactly, case included, the request is rejected with
    `ERR_UNKNOWN_ROLE`." (PRD §2.1)

    "Second, `X-User-Role` must name one of the eight roles with an exact
    case-sensitive match, failing with `ERR_UNKNOWN_ROLE`; an unrecognized role string
    is rejected here, before per-endpoint permission is consulted." (PRD §2.10)

    Design: Corner/validations/alarm_site_read_with_an_unrecognized_role_header_is_unauthenticated
    """
    X.set_clock(api, C.CLOCK_STARTUP_UTC)
    X.create_active_fee_schedule(api)
    site_id = X.create_site(api)

    response = api.get_alarm_site(
        site_id, U.headers_for("PermitSupervisor", U.PERMIT_CLERK_ID)
    )
    validate_error(response, E.ERR_UNKNOWN_ROLE, expected_status=401)

    # The exact declared spelling is authorized for this read, so the refusal above was
    # about role recognition and not about permission.
    recognized = api.get_alarm_site(site_id, U.PERMIT_CLERK)
    validate_success(recognized, 200)
    assert get_success_data(recognized)["id"] == site_id


def test_alarm_company_create_by_permit_clerk_is_forbidden(api):
    """Registering a monitoring company is an administrator-only write.

    "A recognized role that is not listed among the authorized roles for the endpoint it
    invoked is rejected with `ERR_ROLE_NOT_PERMITTED`." (PRD §2.1)

    "Third, the recognized role must appear in the authorized-role list of the endpoint
    being called, failing with `ERR_ROLE_NOT_PERMITTED`. All three apply to every
    endpoint." (PRD §2.10) — position 3 precedes the payload-shape checks of positions
    4 and 5, and PRD §4 lists only `ProgramAdministrator` for this route.

    Design: Corner/validations/alarm_company_create_by_permit_clerk_is_forbidden
    """
    X.set_clock(api, C.CLOCK_STARTUP_UTC)

    payload = F.alarm_company_payload(
        legal_name="Northgate Monitoring LLC",
        license_number="TXALM-51001",
        contact_email="ops@northgate.example",
        contact_phone="+12145550333",
        score_mode="VOLUME_WEIGHTED",
    )

    refused = api.create_alarm_company(payload, U.PERMIT_CLERK)
    validate_error(refused, E.ERR_ROLE_NOT_PERMITTED, expected_status=403)

    A.assert_total_count(api.list_alarm_companies(U.PROGRAM_ADMIN), 0)

    accepted = api.create_alarm_company(payload, U.PROGRAM_ADMIN)
    validate_success(accepted, 201)


def test_suspension_order_create_missing_required_effective_through_returns_422(api):
    """A missing required input outranks an unresolvable body reference.

    "On every write operation, each required input field must be present and non-null;
    the first missing field in the operation's declared input order is reported with
    `ERR_MISSING_REQUIRED_FIELD`." (PRD §2.10)

    "**Positions 6 and 7 — existence.** Every identifier embedded in the request path
    must resolve, checked strictly left to right so the leftmost unknown segment wins,
    and then every foreign reference supplied in the body must resolve, checked in
    declared input order." (PRD §2.10)

    "An administrator proposes withdrawal of police response by supplying the
    `alarm_site_id`, the `triggering_incident_id` naming the chargeable incident that
    crossed the threshold, a `basis` of `EXCESSIVE_FALSE_ALARMS`, `UNPERMITTED_OPERATION`
    or `NONPAYMENT`, the closed-interval bounds `effective_from` and `effective_through`,
    and an `expected_alarm_site_version`." (PRD §3.7) — `effective_through` is therefore
    required, and position 4 answers before the unknown `triggering_incident_id` at
    position 7 and before the basis gate.

    Design: Corner/validations/suspension_order_create_missing_required_effective_through_returns_422
    """
    bundle = X.setup_program_baseline(api, clock=C.CLOCK_STARTUP_UTC)
    site_version_before = X.site_version(api, bundle.site_id)

    response = api.create_suspension_order(
        {
            "alarm_site_id": bundle.site_id,
            "triggering_incident_id": NON_EXISTENT_UUID,
            "basis": "EXCESSIVE_FALSE_ALARMS",
            "effective_from": "2026-08-11T00:00:00Z",
            "expected_alarm_site_version": site_version_before,
        },
        U.PROGRAM_ADMIN,
    )
    validate_error(response, E.ERR_MISSING_REQUIRED_FIELD, expected_status=422)

    A.assert_total_count(
        api.list_suspension_orders(U.PROGRAM_ADMIN, {"alarm_site_id": bundle.site_id}), 0
    )
    assert X.site_version(api, bundle.site_id) == site_version_before


def test_compliance_report_create_with_a_negative_count_is_rejected(api):
    """A negative count field is malformed and is refused at the payload-shape check.

    "Then each supplied field must be well formed: enum fields must hold a declared
    member, cents and count fields must be non-negative integers with no floats accepted
    anywhere, timestamps must parse as RFC 3339 UTC with a trailing `Z`, percentage
    fields must lie between 0 and 1 inclusive, identifiers must be UUID strings, and tier
    arrays must be non-empty. The first offending field in declared input order is
    reported with `ERR_INVALID_FIELD_VALUE`." (PRD §2.10)

    Design: Corner/validations/compliance_report_create_with_a_negative_count_is_rejected
    """
    X.set_clock(api, C.CLOCK_STARTUP_UTC)
    X.create_active_fee_schedule(api)
    company_id = X.create_company(api)

    response = api.create_compliance_report(
        F.compliance_report_payload(
            company_id,
            "2026-08-01T00:00:00Z",
            "2026-08-31T00:00:00Z",
            reported_dispatch_count=-1,
            reported_cancellation_count=0,
            ecv_attempt_count=2.5,
        ),
        U.alarm_company_operator(company_id),
    )
    validate_error(response, E.ERR_INVALID_FIELD_VALUE, expected_status=422)

    A.assert_total_count(
        api.list_compliance_reports(
            U.PROGRAM_ADMIN, {"monitoring_company_id": company_id}
        ),
        0,
    )


def test_appeal_schedule_with_unknown_appeal_and_unknown_docket_is_not_found(api):
    """A path id and a body reference are both unknown; the path id is reported.

    "Every identifier embedded in the request path must resolve, checked strictly left to
    right so the leftmost unknown segment wins, and then every foreign reference supplied
    in the body must resolve, checked in declared input order." (PRD §2.10)

    "Path parameters are resolved strictly left to right, so the leftmost unresolvable
    segment determines the error." (PRD §2.5)

    Existence sits at positions 6 and 7 and the revision guard at position 16, so the
    quoted docket revision is never compared either.

    Design: Corner/validations/appeal_schedule_with_unknown_appeal_and_unknown_docket_is_not_found
    """
    X.set_clock(api, C.CLOCK_STARTUP_UTC)
    docket_id = X.create_docket(api, "2026-10-05T14:00:00Z", "2026-10-05T16:00:00Z")
    docket_version_before = X.docket_version(api, docket_id)

    response = api.schedule_appeal(
        NON_EXISTENT_UUID,
        {
            "hearing_docket_id": OTHER_NON_EXISTENT_UUID,
            "expected_hearing_docket_version": docket_version_before,
        },
        U.PROGRAM_ADMIN,
    )
    validate_error(response, E.ERR_APPEAL_NOT_FOUND, expected_status=404)

    docket = get_success_data(api.get_hearing_docket(docket_id, U.PROGRAM_ADMIN))
    assert docket["scheduled_appeal_count"] == 0
    assert docket["version"] == docket_version_before


def test_appeal_create_with_unknown_incident_and_unknown_prior_appeal_is_not_found(api):
    """Two unknown body references; only the first in declaration order is reported.

    "and then every foreign reference supplied in the body must resolve, checked in
    declared input order." (PRD §2.10)

    "Path parameters are resolved strictly left to right, so the leftmost unresolvable
    segment determines the error." (PRD §2.5) — this request carries no unknown path
    segment at all, so the answer must come from the body pass.

    `false_alarm_incident_id` is declared before `prior_appeal_id`, and existence at
    position 7 precedes the revision guard at position 15, so the quoted incident revision
    is irrelevant.

    Design: Corner/validations/appeal_create_with_unknown_incident_and_unknown_prior_appeal_is_not_found
    """
    bundle = X.setup_program_baseline(api, clock=C.CLOCK_STARTUP_UTC)
    incident = X.create_reported_incident(
        api, bundle, bundle.system_id, C.FIRST_CHARGEABLE_OCCURRED_AT
    )
    X.determine_counted(api, incident.incident_id)
    incident_version_before = X.incident_version(api, incident.incident_id)

    response = api.create_appeal(
        {
            "false_alarm_incident_id": NON_EXISTENT_UUID,
            "grounds": "WRONG_CAUSE_CODE",
            "narrative": "Filed against an incident id that does not exist.",
            "expected_false_alarm_incident_version": incident_version_before,
            "prior_appeal_id": OTHER_NON_EXISTENT_UUID,
        },
        U.alarm_user(bundle.site_id),
    )
    validate_error(response, E.ERR_FALSE_ALARM_INCIDENT_NOT_FOUND, expected_status=404)

    survivor = X.get_incident(api, incident.incident_id)
    A.assert_status(survivor, "COUNTED")
    assert survivor["version"] == incident_version_before
    A.assert_total_count(
        api.list_appeals(U.PROGRAM_ADMIN, {"false_alarm_incident_id": incident.incident_id}),
        0,
    )


def test_payment_record_read_by_a_different_site_alarm_user_is_forbidden(api):
    """An entity-backed premises holder cannot read another premises' payment.

    "When `X-User-Role` is `AlarmUser`, `X-User-ID` is the `id` of the acting `AlarmSite`;
    ownership checks on any resource that references a premises compare the resource's
    premises reference to `X-User-ID`, whether that reference is the site itself or the
    site reachable from the target system, permit, incident, appeal, invoice, payment or
    allocation." (PRD §2.1)

    "A mismatch in either direction is rejected with `ERR_NOT_RESOURCE_OWNER`." (PRD §2.1)

    "An entity-backed caller must be acting inside its own aggregate, failing with
    `ERR_NOT_RESOURCE_OWNER`" (PRD §2.10) — the premises named by the payment is the
    aggregate the acting holder must be inside, so the foreign holder is refused while
    the owning holder reads the same row.

    Design: Corner/validations/payment_record_read_by_a_different_site_alarm_user_is_forbidden
    """
    bundle = X.setup_program_baseline(api, clock=C.CLOCK_STARTUP_UTC)
    payment_id = X.post_payment(
        api, bundle, C.PERMIT_ISSUE_INVOICE_ASSESSED_CENTS, "2026-08-05T00:00:00Z"
    )

    other_site_id = X.create_site(api, address_key="88-ELM-AVE-75204-2507")

    response = api.get_payment_record(payment_id, U.alarm_user(other_site_id))
    validate_error(response, E.ERR_NOT_RESOURCE_OWNER, expected_status=403)

    holder = api.get_payment_record(payment_id, U.alarm_user(bundle.site_id))
    validate_success(holder, 200)
    assert get_success_data(holder)["id"] == payment_id


def test_incident_determination_by_the_validating_supervisor_is_forbidden(api):
    """The operator who validated the request may not rule on the resulting incident.

    "Determining an incident is barred to the operator recorded as `validated_by_user_id`
    on the dispatch request the incident came from, so the supervisor who released the
    patrol does not also judge whether the alarm was false." (PRD §2.11)

    "The unit's controls rest on the principle that nobody reviews their own work. Three
    pairings are enforced, all of them reported as `ERR_SEGREGATION_OF_DUTIES` at HTTP
    403." (PRD §2.11)

    "Then the segregation-of-duties pairings of §2.11 are enforced with
    `ERR_SEGREGATION_OF_DUTIES`." (PRD §2.10) — position 9, so both roles being
    individually permitted for their own endpoints is not enough.

    Design: Corner/validations/incident_determination_by_the_validating_supervisor_is_forbidden
    """
    bundle = X.setup_program_baseline(api, clock=C.CLOCK_STARTUP_UTC)
    dual_dispatch = U.headers_for("PoliceDispatchSupervisor", U.DUAL_ROLE_ID)
    occurred_at = C.FIRST_CHARGEABLE_OCCURRED_AT
    X.set_clock(api, X.day_start(occurred_at))

    request_id = X.submit_dispatch_request(api, bundle, bundle.system_id, occurred_at)
    validate_success(api.validate_dispatch_request(request_id, dual_dispatch), 200)
    validate_success(api.record_dispatch(request_id, dual_dispatch), 200)
    created = api.create_false_alarm_incident(
        F.false_alarm_incident_payload(request_id), dual_dispatch
    )
    validate_success(created, 201)
    incident_id = get_success_data(created)["id"]

    request_row = get_success_data(api.get_dispatch_request(request_id, U.PROGRAM_ADMIN))
    assert request_row["validated_by_user_id"] == U.DUAL_ROLE_ID

    refused = api.determine_incident(
        incident_id,
        F.determination_payload(
            "COUNTED",
            review_notes="Same officer who validated the request now rules on it.",
        ),
        U.headers_for("FalseAlarmReviewOfficer", U.DUAL_ROLE_ID),
    )
    validate_error(refused, E.ERR_SEGREGATION_OF_DUTIES, expected_status=403)

    untouched = X.get_incident(api, incident_id)
    A.assert_status(untouched, "REPORTED")
    assert untouched["occurrence_index"] is None
    assert untouched["assessed_fee_cents"] is None

    ruled = X.determine_counted(api, incident_id)
    assert ruled["occurrence_index"] == 1


def test_hold_session_by_a_non_docket_hearing_officer_is_forbidden(api):
    """Holding a session is pinned to the officer named on the docket.

    "Holding the session is the officer's own act: only the caller whose `X-User-ID` equals
    the docket's `hearing_officer_user_id` may do it, else `ERR_NOT_DOCKET_OFFICER`; the
    logical clock must have reached `session_start`, the boundary inclusive, else
    `ERR_HEARING_SESSION_NOT_STARTED`" (PRD §3.6)

    "Then docket ownership: only the officer named on a docket may hold that session or
    decide an appeal heard on it, failing with `ERR_NOT_DOCKET_OFFICER`." (PRD §2.10)

    With the clock parked exactly on `session_start` the temporal precondition is already
    satisfied, so the refusal can only be the identity comparison.

    Design: Corner/validations/hold_session_by_a_non_docket_hearing_officer_is_forbidden
    """
    X.set_clock(api, C.CLOCK_STARTUP_UTC)
    docket_id = X.create_docket(
        api, "2026-10-05T14:00:00Z", "2026-10-05T16:00:00Z",
        officer_user_id=U.HEARING_OFFICER_ID,
    )
    docket_version_before = X.docket_version(api, docket_id)
    X.set_clock(api, "2026-10-05T14:00:00Z")

    refused = api.hold_session(docket_id, {}, U.headers_for("HearingOfficer", "ho-99"))
    validate_error(refused, E.ERR_NOT_DOCKET_OFFICER, expected_status=403)

    docket = get_success_data(api.get_hearing_docket(docket_id, U.PROGRAM_ADMIN))
    A.assert_status(docket, "OPEN")
    assert docket["held_at"] is None
    assert docket["version"] == docket_version_before

    # The named officer clears position 10; whatever answers next, it is no longer the
    # identity refusal.
    named = api.hold_session(docket_id, {}, U.HEARING_OFFICER)
    assert named.status_code != 403 or (
        named.json()["data"]["error_id"] != E.ERR_NOT_DOCKET_OFFICER
    )


def test_alarm_site_read_by_its_own_alarm_user_satisfies_the_ownership_check(api):
    """The premises holder reading its own premises passes the ownership check.

    "When `X-User-Role` is `AlarmUser`, `X-User-ID` is the `id` of the acting `AlarmSite`;
    ownership checks on any resource that references a premises compare the resource's
    premises reference to `X-User-ID`, whether that reference is the site itself or the
    site reachable from the target system, permit, incident, appeal, invoice, payment or
    allocation." (PRD §2.1)

    "An invoice of kind `PERMIT_ISSUE_FEE` is assembled and issued." (PRD §3.3) — at the
    default schedule that is 5000 cents plus a 500-cent administrative fee, so the
    premises carries 5500 cents outstanding and no credit.

    Design: Corner/validations/alarm_site_read_by_its_own_alarm_user_satisfies_the_ownership_check
    """
    bundle = X.setup_program_baseline(api, clock=C.CLOCK_STARTUP_UTC)

    response = api.get_alarm_site(bundle.site_id, U.alarm_user(bundle.site_id))
    validate_success(response, 200)
    envelope = response.json()
    assert envelope["response_type"] == "object"

    site = get_success_data(response)
    assert site["id"] == bundle.site_id
    assert site["response_status"] == "RESPONSE_ACTIVE"
    assert site["chargeable_count_window"] == 0
    A.assert_money_cents(
        site["outstanding_balance_cents"], C.PERMIT_ISSUE_INVOICE_ASSESSED_CENTS
    )
    A.assert_money_cents(site["credit_balance_cents"], 0)
    assert isinstance(site["version"], int) and site["version"] >= 1


def test_suspension_order_create_with_a_stale_site_version_returns_412(api):
    """A roster edit invalidates the premises revision an order proposal quotes.

    "Opening a suspension order against a premises requires `expected_alarm_site_version`
    carrying the client's last observed `version` of the target `AlarmSite`. If any other
    writer has advanced that site's version since the client read it, the create is
    rejected with `ERR_STALE_ALARM_SITE_VERSION` (HTTP 412)." (PRD §2.8)

    "Both adding and removing a contact recompute `ecv_callable_contact_count` on the
    premises and bump that premises' `version` by 1 — which is why a client holding an
    `expected_alarm_site_version` from before a roster edit will be turned away on its
    next guarded write." (PRD §3.2)

    The revision guards sit at positions 11 to 16 and the state and business gates
    afterwards, so the 412 answers before the basis check that this single-occurrence
    premises would also fail.

    Design: Corner/validations/suspension_order_create_with_a_stale_site_version_returns_412
    """
    bundle = X.setup_program_baseline(api, clock=C.CLOCK_STARTUP_UTC)
    incident = X.create_counted_incident(
        api, bundle, bundle.system_id, C.FIRST_CHARGEABLE_OCCURRED_AT
    )

    site_version_read = X.site_version(api, bundle.site_id)
    X.create_contact(api, bundle.site_id, contact_priority=3)

    stale = api.create_suspension_order(
        F.suspension_order_payload(
            bundle.site_id,
            incident.incident_id,
            "2026-09-30T01:00:00Z",
            "2026-10-30T01:00:00Z",
            site_version_read,
        ),
        U.PROGRAM_ADMIN,
    )
    validate_error(stale, E.ERR_STALE_ALARM_SITE_VERSION, expected_status=412)

    assert X.site_version(api, bundle.site_id) == site_version_read + 1
    assert X.orders_of_site(api, bundle.site_id) == []

    retry = api.create_suspension_order(
        F.suspension_order_payload(
            bundle.site_id,
            incident.incident_id,
            "2026-09-30T01:00:00Z",
            "2026-10-30T01:00:00Z",
            X.site_version(api, bundle.site_id),
        ),
        U.PROGRAM_ADMIN,
    )
    validate_error(retry, E.ERR_SUSPENSION_BASIS_NO_LONGER_MET, expected_status=409)


def test_payment_record_create_with_a_stale_site_version_returns_412(api):
    """A tender quoting an invalidated premises revision allocates nothing.

    "Posting a payment against a premises account requires `expected_alarm_site_version`
    carrying the client's last observed `version` of the paying `AlarmSite`, and a
    mismatch is rejected with `ERR_STALE_ALARM_SITE_VERSION` (HTTP 412)." (PRD §2.8)

    "Both adding and removing a contact recompute `ecv_callable_contact_count` on the
    premises and bump that premises' `version` by 1" (PRD §3.2)

    Design: Corner/validations/payment_record_create_with_a_stale_site_version_returns_412
    """
    bundle = X.setup_program_baseline(api, clock=C.CLOCK_STARTUP_UTC)
    invoice = X.invoices_of_site(api, bundle.site_id)[0]

    site_version_read = X.site_version(api, bundle.site_id)
    X.create_contact(api, bundle.site_id, contact_priority=3)

    stale = api.create_payment_record(
        F.payment_record_payload(
            bundle.site_id,
            C.PERMIT_ISSUE_INVOICE_ASSESSED_CENTS,
            "2026-08-01T00:00:00Z",
            site_version_read,
        ),
        U.BILLING_CLERK,
    )
    validate_error(stale, E.ERR_STALE_ALARM_SITE_VERSION, expected_status=412)

    A.assert_total_count(api.list_payment_records(U.PROGRAM_ADMIN), 0)
    A.assert_total_count(api.list_payment_allocations(U.PROGRAM_ADMIN), 0)

    A.assert_invoice_totals(
        X.get_invoice(api, invoice["id"]),
        paid_cents=0,
        outstanding_cents=C.PERMIT_ISSUE_INVOICE_ASSESSED_CENTS,
        payment_status="UNPAID",
    )
    A.assert_money_cents(X.get_site(api, bundle.site_id)["credit_balance_cents"], 0)


def test_invoice_adjustment_with_a_stale_invoice_version_returns_412(api):
    """Settling an invoice invalidates the revision a later adjustment quotes.

    "Posting an adjustment against an invoice requires `expected_penalty_invoice_version`
    carrying the client's last observed `version` of that `PenaltyInvoice`, and a mismatch
    is rejected with `ERR_STALE_PENALTY_INVOICE_VERSION` (HTTP 412)." (PRD §2.8)

    "The invoice revision must still match, else `ERR_STALE_PENALTY_INVOICE_VERSION`" (PRD
    §3.8)

    The guard sits at position 12 and the amount-fit check late in the sequence, so the 412
    answers even though a `REDUCE` of 1000 cents against a fully paid invoice would also
    fail the fit check. The adjusting administrator differs from the collecting billing
    clerk, so no duty separation intervenes either.

    Design: Corner/validations/invoice_adjustment_with_a_stale_invoice_version_returns_412
    """
    bundle = X.setup_program_baseline(api, clock=C.CLOCK_STARTUP_UTC)
    invoice_id = X.invoices_of_site(api, bundle.site_id)[0]["id"]
    invoice_version_at_issuance = X.invoice_version(api, invoice_id)

    X.pay_invoice_in_full(api, bundle, invoice_id, "2026-08-01T00:00:00Z")
    assert X.invoice_version(api, invoice_id) > invoice_version_at_issuance

    stale = api.adjust_invoice(
        invoice_id,
        {
            "adjustment_kind": "REDUCE",
            "reason": "Clerical over-assessment reported by the permit desk.",
            "expected_penalty_invoice_version": invoice_version_at_issuance,
            "amount_cents": 1000,
        },
        U.PROGRAM_ADMIN,
    )
    validate_error(stale, E.ERR_STALE_PENALTY_INVOICE_VERSION, expected_status=412)

    A.assert_invoice_totals(
        X.get_invoice(api, invoice_id),
        adjusted_cents=0,
        outstanding_cents=0,
        payment_status="PAID",
    )
    A.assert_money_cents(X.get_site(api, bundle.site_id)["outstanding_balance_cents"], 0)


def test_alarm_system_patch_with_a_stale_system_version_returns_412(api):
    """A second reconfiguration replaying the first one's revision is refused.

    "Reconfiguring a registered alarm system requires `expected_alarm_system_version`
    carrying the client's last observed `version` of that `AlarmSystem`, and a mismatch is
    rejected with `ERR_STALE_ALARM_SYSTEM_VERSION` (HTTP 412)." (PRD §2.8)

    "it is refused because the submitted field set would silently overwrite a change
    another writer already applied, for example re-enabling enhanced call verification that
    was just switched off." (PRD §2.8)

    Design: Corner/validations/alarm_system_patch_with_a_stale_system_version_returns_412
    """
    bundle = X.setup_program_baseline(api, clock=C.CLOCK_STARTUP_UTC)
    system_version_read = X.system_version(api, bundle.system_id)

    first = api.patch_alarm_system(
        bundle.system_id,
        {"expected_alarm_system_version": system_version_read, "zone_count": 9},
        U.PERMIT_CLERK,
    )
    validate_success(first, 200)
    after_first = get_success_data(first)
    assert after_first["zone_count"] == 9
    assert after_first["version"] == system_version_read + 1

    stale = api.patch_alarm_system(
        bundle.system_id,
        {"expected_alarm_system_version": system_version_read, "ecv_enabled": False},
        U.PERMIT_CLERK,
    )
    validate_error(stale, E.ERR_STALE_ALARM_SYSTEM_VERSION, expected_status=412)

    survivor = X.get_system(api, bundle.system_id)
    assert survivor["ecv_enabled"] is True
    assert survivor["zone_count"] == 9
    assert survivor["version"] == after_first["version"]


def test_permit_renewal_with_a_stale_permit_version_returns_412(api):
    """The nightly term-cycle moves make an issuance-time permit revision stale.

    "A permit renewal requires `expected_alarm_permit_version` to equal the permit's
    current `version`, failing with `ERR_STALE_ALARM_PERMIT_VERSION`." (PRD §2.8)

    "When the logical clock reaches 30 days before `term_end_at`, the run moves `ACTIVE →
    RENEWAL_DUE`; no money moves, the permit simply becomes renewable. Past `term_end_at`
    the run moves `RENEWAL_DUE → GRACE`, and past `grace_through_at` it moves `GRACE →
    EXPIRED`." (PRD §3.3)

    "On success the permit returns to `ACTIVE` with `term_start_at` set to the logical
    clock, `term_end_at` recomputed as that instant plus `permit_term_days`,
    `grace_through_at` recomputed from the new term end, `renewal_count` increased by 1,
    `last_renewed_at` stamped, and `new_installation_grace_through` left null. A
    `PERMIT_RENEWAL_FEE` invoice is issued" (PRD §3.3) — none of which may happen here.

    Issued 2026-08-01 with `permit_term_days` 365, the term ends 2027-08-01 and grace runs
    30 days beyond it, so at 2027-08-16 the permit sits in `GRACE` and is genuinely
    renewable; only the quoted revision is wrong.

    Design: Corner/validations/permit_renewal_with_a_stale_permit_version_returns_412
    """
    bundle = X.setup_program_baseline(api, clock=C.CLOCK_STARTUP_UTC)
    permit_version_at_issuance = X.permit_version(api, bundle.permit_id)
    invoice_id = X.invoices_of_site(api, bundle.site_id)[0]["id"]
    X.pay_invoice_in_full(api, bundle, invoice_id, "2026-08-01T00:00:00Z")

    X.set_clock(api, "2027-07-05T00:00:00Z")
    X.run_nightly(api)
    X.set_clock(api, "2027-08-16T00:00:00Z")
    X.run_nightly(api)
    assert X.get_permit(api, bundle.permit_id)["status"] == "GRACE"

    stale = api.renew_permit(
        bundle.permit_id,
        {"expected_alarm_permit_version": permit_version_at_issuance},
        U.PERMIT_CLERK,
    )
    validate_error(stale, E.ERR_STALE_ALARM_PERMIT_VERSION, expected_status=412)

    permit = X.get_permit(api, bundle.permit_id)
    A.assert_status(permit, "GRACE")
    assert permit["renewal_count"] == 0
    assert permit["last_renewed_at"] is None

    A.assert_total_count(
        api.list_penalty_invoices(
            U.PROGRAM_ADMIN,
            {"alarm_site_id": bundle.site_id, "kind": "PERMIT_RENEWAL_FEE"},
        ),
        0,
    )


def test_appeal_create_with_a_stale_incident_version_returns_412(api):
    """The determination that made the incident appealable also bumped its revision.

    "Filing an appeal requires `expected_false_alarm_incident_version` to equal the
    contested incident's current `version`, failing with
    `ERR_STALE_FALSE_ALARM_INCIDENT_VERSION`." (PRD §2.8)

    Design: Corner/validations/appeal_create_with_a_stale_incident_version_returns_412
    """
    bundle = X.setup_program_baseline(api, clock=C.CLOCK_STARTUP_UTC)
    incident = X.create_reported_incident(
        api, bundle, bundle.system_id, C.FIRST_CHARGEABLE_OCCURRED_AT
    )
    version_before_determination = X.incident_version(api, incident.incident_id)
    X.determine_counted(api, incident.incident_id)
    version_after_determination = X.incident_version(api, incident.incident_id)
    assert version_after_determination > version_before_determination

    stale = api.create_appeal(
        {
            "false_alarm_incident_id": incident.incident_id,
            "grounds": "EXEMPT_CAUSE",
            "narrative": "Filed while holding the pre-determination version of the incident.",
            "expected_false_alarm_incident_version": version_before_determination,
        },
        U.alarm_user(bundle.site_id),
    )
    validate_error(
        stale, E.ERR_STALE_FALSE_ALARM_INCIDENT_VERSION, expected_status=412
    )

    A.assert_total_count(
        api.list_appeals(
            U.PROGRAM_ADMIN, {"false_alarm_incident_id": incident.incident_id}
        ),
        0,
    )
    held = X.get_incident(api, incident.incident_id)
    A.assert_status(held, "COUNTED")
    assert held["version"] == version_after_determination

    fresh = api.create_appeal(
        {
            "false_alarm_incident_id": incident.incident_id,
            "grounds": "EXEMPT_CAUSE",
            "narrative": "Filed while holding the pre-determination version of the incident.",
            "expected_false_alarm_incident_version": version_after_determination,
        },
        U.alarm_user(bundle.site_id),
    )
    validate_success(fresh, 201)
    A.assert_status(X.get_incident(api, incident.incident_id), "APPEALED")


def test_appeal_reschedule_with_a_stale_docket_version_returns_412(api):
    """A replayed scheduling call is answered by the revision guard, not the state gate.

    "Scheduling an appeal onto a docket requires `expected_hearing_docket_version` to equal
    that docket's current `version`, failing with `ERR_STALE_HEARING_DOCKET_VERSION`." (PRD
    §2.8)

    "**Position 17 — declared transition.** The target resource must sit in a state from
    which the requested transition is declared." (PRD §2.10)

    The revision guard is position 16 and the declared-transition check position 17, so the
    replay — stale docket revision and an already-scheduled appeal at once — must answer
    412 rather than the 409.

    Design: Corner/validations/appeal_reschedule_with_a_stale_docket_version_returns_412
    """
    bundle = X.setup_program_baseline(api, clock=C.CLOCK_STARTUP_UTC)
    incident = X.create_counted_incident(
        api, bundle, bundle.system_id, C.FIRST_CHARGEABLE_OCCURRED_AT
    )
    appeal_id = X.file_appeal(api, bundle, incident.incident_id)
    docket_id = X.create_docket(api, "2026-10-05T14:00:00Z", "2026-10-05T16:00:00Z")

    docket_version_before = X.docket_version(api, docket_id)
    X.schedule_appeal(api, appeal_id, docket_id)
    assert X.docket_version(api, docket_id) == docket_version_before + 1
    appeal_after_scheduling = X.get_appeal(api, appeal_id)

    replay = api.schedule_appeal(
        appeal_id,
        {
            "hearing_docket_id": docket_id,
            "expected_hearing_docket_version": docket_version_before,
        },
        U.HEARING_OFFICER,
    )
    validate_error(replay, E.ERR_STALE_HEARING_DOCKET_VERSION, expected_status=412)

    docket = get_success_data(api.get_hearing_docket(docket_id, U.PROGRAM_ADMIN))
    assert docket["scheduled_appeal_count"] == 1

    appeal = X.get_appeal(api, appeal_id)
    A.assert_status(appeal, "SCHEDULED")
    assert appeal["hearing_docket_id"] == docket_id
    A.assert_version_unchanged(appeal_after_scheduling, appeal)


def test_fee_schedule_activate_twice_returns_invalid_state(api):
    """Activation is declared only out of DRAFT, so replaying it is not idempotent.

    "A freshly created schedule lands in `DRAFT` and nothing consults it. Activating it
    moves it to `ACTIVE`, pushes any previously `ACTIVE` schedule to `SUPERSEDED` and
    stamps that outgoing row's `superseded_at` with the logical clock." (PRD §3.1)

    "At most one schedule is `ACTIVE` program-wide at any logical instant" (PRD §2.9)

    "**Position 17 — declared transition.** The target resource must sit in a state from
    which the requested transition is declared." (PRD §2.10)

    Design: Corner/validations/fee_schedule_activate_twice_returns_invalid_state
    """
    X.set_clock(api, C.CLOCK_STARTUP_UTC)
    schedule_id = X.create_active_fee_schedule(api)
    activated = get_success_data(api.get_fee_schedule(schedule_id, U.PROGRAM_ADMIN))

    replay = api.activate_fee_schedule(schedule_id, U.PROGRAM_ADMIN)
    validate_error(replay, E.ERR_INVALID_STATE, expected_status=409)

    schedule = get_success_data(api.get_fee_schedule(schedule_id, U.PROGRAM_ADMIN))
    A.assert_status(schedule, "ACTIVE")
    assert schedule["superseded_at"] is None
    # The PRD declares no `activated_at` column on AlarmFeeSchedule — only
    # `superseded_at` — so the replayed activation is checked against the fields
    # the contract actually names.
    assert schedule["version"] == activated["version"]

    A.assert_total_count(
        api.list_fee_schedules(U.PROGRAM_ADMIN, {"status": "ACTIVE"}), 1
    )


SIX_OCCURRENCES = [
    "2026-09-15T03:09:00Z",
    "2026-09-16T04:00:00Z",
    "2026-09-17T04:00:00Z",
    "2026-09-18T04:00:00Z",
    "2026-09-19T04:00:00Z",
    "2026-09-19T05:00:00Z",
]


def test_dispatch_request_create_on_a_busy_system_at_a_suspended_site_returns_open_request_exists(api):
    """A busy system and a suspended premises are both violated; the occupancy row wins.

    "A new dispatch request is refused when the named alarm system already has a dispatch
    request in `SUBMITTED`, `VALIDATED` or `DISPATCHED`, with
    `ERR_OPEN_DISPATCH_REQUEST_EXISTS`." (PRD §2.10)

    "Next, the premises behind the named system must not sit at `RESPONSE_SUSPENDED`
    posture when a dispatch request is lodged, failing with
    `ERR_POLICE_RESPONSE_SUSPENDED`." (PRD §2.10)

    "And when `chargeable_count_window` reaches or exceeds `suspension_threshold_count`, an
    enforcement order is auto-proposed for the premises: a suspension order in `PROPOSED`
    with `basis` of `EXCESSIVE_FALSE_ALARMS`, its `triggering_incident_id` set to this
    incident, `effective_from` at the logical clock plus 10 days and `effective_through` at
    30 days after that." (PRD §3.5)

    Occupancy is positions 18 to 21 and the public-safety gates positions 25 to 29, so the
    earlier row answers.

    Design: Corner/validations/dispatch_request_create_on_a_busy_system_at_a_suspended_site_returns_open_request_exists
    """
    bundle = X.setup_program_baseline(
        api, clock=C.CLOCK_STARTUP_UTC, contact_count=3, system_count=6
    )
    incidents = X.accumulate_counted_incidents(api, bundle, SIX_OCCURRENCES)
    busy_system_id = bundle.system_ids[5]
    open_request_id = incidents[5].dispatch_request_id

    proposed = [o for o in X.orders_of_site(api, bundle.site_id) if o["status"] == "PROPOSED"]
    assert len(proposed) == 1
    validate_success(api.serve_suspension_order(proposed[0]["id"], U.PERMIT_CLERK), 200)
    X.set_clock(api, "2026-10-05T00:00:00Z")
    assert X.get_site(api, bundle.site_id)["response_status"] == "RESPONSE_SUSPENDED"

    refused = api.create_dispatch_request(
        F.dispatch_request_payload(
            busy_system_id,
            "2026-10-05T00:00:00Z",
            [
                F.call_attempt(bundle.contact_ids[0], "2026-10-05T00:01:00Z", "NO_ANSWER"),
                F.call_attempt(bundle.contact_ids[1], "2026-10-05T00:02:00Z", "NO_ANSWER"),
            ],
            idempotency_key="gsm-1005-pairA",
        ),
        bundle.operator_headers,
    )
    validate_error(refused, E.ERR_OPEN_DISPATCH_REQUEST_EXISTS, expected_status=409)

    still_open = get_success_data(api.get_dispatch_request(open_request_id, U.PROGRAM_ADMIN))
    A.assert_status(still_open, "DISPATCHED")
    rows = A.assert_total_count(
        api.list_dispatch_requests(U.PROGRAM_ADMIN, {"alarm_system_id": busy_system_id}), 1
    )
    assert rows[0]["id"] == open_request_id


def test_dispatch_request_create_on_an_idle_system_at_a_suspended_site_returns_police_response_suspended(api):
    """With no open request in the way, the suspended-premises gate finally surfaces.

    "Next, the premises behind the named system must not sit at `RESPONSE_SUSPENDED`
    posture when a dispatch request is lodged, failing with
    `ERR_POLICE_RESPONSE_SUSPENDED`." (PRD §2.10)

    "Serving also issues a `REINSTATEMENT_FEE` invoice against the premises with
    `suspension_order_id` set, recomputes the premises' `response_status` to
    `RESPONSE_SUSPENDED` along with its `outstanding_balance_cents` and
    `renewal_block_active`, and bumps the premises' `version` by 1. From that point dispatch
    requests for the premises' systems are refused for the duration." (PRD §3.7)

    The roster still holds three callable contacts against a minimum of two, so the
    later insufficient-contacts gate cannot be what answers.

    Design: Corner/validations/dispatch_request_create_on_an_idle_system_at_a_suspended_site_returns_police_response_suspended
    """
    bundle = X.setup_program_baseline(
        api, clock=C.CLOCK_STARTUP_UTC, contact_count=3, system_count=6
    )
    X.accumulate_counted_incidents(api, bundle, SIX_OCCURRENCES)

    proposed = [o for o in X.orders_of_site(api, bundle.site_id) if o["status"] == "PROPOSED"]
    assert len(proposed) == 1
    validate_success(api.serve_suspension_order(proposed[0]["id"], U.PERMIT_CLERK), 200)
    X.set_clock(api, "2026-10-05T00:00:00Z")
    assert X.get_site(api, bundle.site_id)["response_status"] == "RESPONSE_SUSPENDED"

    idle_system_id = X.create_submitted_system(
        api,
        bundle.site_id,
        bundle.company_id,
        zone_count=4,
        installed_at="2026-10-01T09:00:00Z",
    )
    A.assert_total_count(
        api.list_dispatch_requests(U.PROGRAM_ADMIN, {"alarm_system_id": idle_system_id}), 0
    )

    refused = api.create_dispatch_request(
        F.dispatch_request_payload(
            idle_system_id,
            "2026-10-05T00:02:00Z",
            [
                F.call_attempt(bundle.contact_ids[0], "2026-10-05T00:03:00Z", "NO_ANSWER"),
                F.call_attempt(bundle.contact_ids[2], "2026-10-05T00:04:00Z", "NO_ANSWER"),
            ],
            idempotency_key="gsm-1005-pairA-idle",
        ),
        bundle.operator_headers,
    )
    validate_error(refused, E.ERR_POLICE_RESPONSE_SUSPENDED, expected_status=409)

    A.assert_total_count(
        api.list_dispatch_requests(U.PROGRAM_ADMIN, {"alarm_system_id": idle_system_id}), 0
    )
    assert X.get_site(api, bundle.site_id)["chargeable_count_window"] == 6


def test_second_incident_on_one_dispatch_request_returns_already_reported(api):
    """One live incident per dispatch request, even before the first is ruled on.

    "A new incident is refused when its dispatch request already has an incident that is not
    `VOIDED` — one live incident per dispatch request — with
    `ERR_INCIDENT_ALREADY_REPORTED`." (PRD §2.10)

    "The row denormalizes `alarm_site_id`, `alarm_system_id` and `occurred_at` from the
    request — the occurrence instant is the ordering key for all later numbering — and is
    created in `REPORTED`, not yet chargeable, with `occurrence_index` and
    `assessed_fee_cents` unset and `appeal_count` at 0." (PRD §3.5)

    Design: Corner/validations/second_incident_on_one_dispatch_request_returns_already_reported
    """
    bundle = X.setup_program_baseline(api, clock=C.CLOCK_STARTUP_UTC)
    incident = X.create_reported_incident(
        api, bundle, bundle.system_id, C.FIRST_CHARGEABLE_OCCURRED_AT
    )
    A.assert_status(X.get_incident(api, incident.incident_id), "REPORTED")

    duplicate = api.create_false_alarm_incident(
        F.false_alarm_incident_payload(
            incident.dispatch_request_id,
            cause_code="EQUIPMENT_MALFUNCTION",
            narrative="Duplicate report keyed by a second dispatcher.",
        ),
        U.DISPATCH_SUPERVISOR,
    )
    validate_error(duplicate, E.ERR_INCIDENT_ALREADY_REPORTED, expected_status=409)

    rows = A.assert_total_count(
        api.list_false_alarm_incidents(
            U.PROGRAM_ADMIN, {"dispatch_request_id": incident.dispatch_request_id}
        ),
        1,
    )
    assert rows[0]["id"] == incident.incident_id
    assert X.get_incident(api, incident.incident_id)["cause_code"] == "OPERATOR_ERROR"
    assert X.get_site(api, bundle.site_id)["chargeable_count_window"] == 0


def test_appeal_schedule_onto_a_cancelled_docket_is_rejected(api):
    """A schedulable appeal is still refused when the target docket has been cancelled.

    "Scheduling an appeal requires the target docket to be `OPEN`, failing with
    `ERR_DOCKET_NOT_OPEN`." (PRD §2.10)

    "Cancelling a docket is likewise available symmetrically from `OPEN` or
    `CLOSED_FOR_SCHEDULING`, takes an optional `cancellation_reason`, and lands in the
    terminal `CANCELLED`." (PRD §3.6)

    The docket revision quoted here is the one read back after cancellation, so the
    position-16 revision guard is satisfied and cannot mask the state gate.

    Design: Corner/validations/appeal_schedule_onto_a_cancelled_docket_is_rejected
    """
    bundle = X.setup_program_baseline(api, clock=C.CLOCK_STARTUP_UTC)
    incident = X.create_counted_incident(
        api, bundle, bundle.system_id, C.FIRST_CHARGEABLE_OCCURRED_AT
    )
    appeal_id = X.file_appeal(api, bundle, incident.incident_id)
    docket_id = X.create_docket(api, "2026-10-05T14:00:00Z", "2026-10-05T16:00:00Z")

    cancelled = api.cancel_docket(
        docket_id,
        {"cancellation_reason": "Hearing officer reassigned to a code enforcement calendar."},
        U.PROGRAM_ADMIN,
    )
    validate_success(cancelled, 200)
    version_after_cancellation = get_success_data(cancelled)["version"]

    refused = api.schedule_appeal(
        appeal_id,
        {
            "hearing_docket_id": docket_id,
            "expected_hearing_docket_version": version_after_cancellation,
        },
        U.HEARING_OFFICER,
    )
    validate_error(refused, E.ERR_DOCKET_NOT_OPEN, expected_status=409)

    docket = get_success_data(api.get_hearing_docket(docket_id, U.PROGRAM_ADMIN))
    A.assert_status(docket, "CANCELLED")
    assert docket["scheduled_appeal_count"] == 0

    appeal = X.get_appeal(api, appeal_id)
    A.assert_status(appeal, "FILED")
    assert appeal["hearing_docket_id"] is None


def test_explicit_payment_naming_a_written_off_invoice_returns_invoice_written_off(api):
    """A written-off invoice is refused as a payment target before the allocation maths.

    "And an invoice whose dunning stage has reached `WRITTEN_OFF` can no longer be adjusted,
    paid or referred, so invoice adjustment, payment posting and collections referral all
    fail with `ERR_INVOICE_WRITTEN_OFF`." (PRD §2.10)

    "The premises revision must still match, else `ERR_STALE_ALARM_SITE_VERSION`, and no
    allocation may target a written-off invoice, else `ERR_INVOICE_WRITTEN_OFF`." (PRD §3.9)

    "The nightly run advances `CURRENT → NOTICE` once `days_delinquent` is at least 1, and
    `NOTICE → FINAL_NOTICE` once it is at least 30" (PRD §3.8)

    "Step two: `late_penalty_cents` is that principal times `late_penalty_pct`, rounded half
    up, and is added into `assessed_cents` — once per invoice, never twice." (PRD §3.8)

    "a `WRITE_OFF` requires the stage to be `REFERRED` and moves it to the terminal
    `WRITTEN_OFF`, adding the whole outstanding amount to `adjusted_cents`, zeroing
    `outstanding_cents`, and removing the invoice from the premises' balance and from every
    allocation candidate set." (PRD §3.8)

    Arithmetic: a 24000-cent unpermitted-operation penalty issued 2026-08-01 falls due 30
    days later on 2026-08-31; at 2026-09-01 `days_delinquent` is 1, so the nightly run adds
    24000 x 0.10 = 2400 and the invoice stands at 26400; at 2026-09-30 it is 30 days
    delinquent and reaches `FINAL_NOTICE`; at 2026-11-29 it is 90 days delinquent with 26400
    outstanding, clearing both referral thresholds. The write-off is taken at exactly 26400.

    Design: Corner/validations/explicit_payment_naming_a_written_off_invoice_returns_invoice_written_off
    """
    bundle = X.setup_program_baseline(
        api,
        clock=C.CLOCK_STARTUP_UTC,
        schedule_overrides={
            "permit_issue_fee_cents": 0,
            "unpermitted_operation_penalty_cents": 24000,
            "admin_fee_pct": 0,
            "admin_fee_min_cents": 0,
        },
    )
    validate_success(
        api.revoke_permit(
            bundle.permit_id,
            {"revocation_reason": "Permit revoked for cause; system operating unpermitted."},
            U.PROGRAM_ADMIN,
        ),
        200,
    )
    invoice = X.invoices_of_site(
        api, bundle.site_id, kind="UNPERMITTED_OPERATION_PENALTY"
    )[0]
    invoice_id = invoice["id"]
    A.assert_invoice_totals(invoice, assessed_cents=24000, outstanding_cents=24000)

    X.set_clock(api, "2026-09-01T00:00:00Z")
    X.run_nightly(api)
    A.assert_invoice_totals(
        X.get_invoice(api, invoice_id),
        assessed_cents=26400,
        outstanding_cents=26400,
        collections_stage="NOTICE",
    )

    X.set_clock(api, "2026-09-30T00:00:00Z")
    X.run_nightly(api)
    A.assert_invoice_totals(
        X.get_invoice(api, invoice_id), collections_stage="FINAL_NOTICE"
    )

    X.set_clock(api, "2026-11-29T00:00:00Z")
    validate_success(
        api.refer_invoice_to_collections(
            invoice_id, {"referral_agency": "Trinity Recovery Partners"}, U.BILLING_CLERK
        ),
        200,
    )
    written_off = api.adjust_invoice(
        invoice_id,
        {
            "adjustment_kind": "WRITE_OFF",
            "reason": "Uncollectable after outside agency referral.",
            "expected_penalty_invoice_version": X.invoice_version(api, invoice_id),
            "amount_cents": 26400,
        },
        U.PROGRAM_ADMIN,
    )
    validate_success(written_off, 200)

    refused = api.create_payment_record(
        {
            "alarm_site_id": bundle.site_id,
            "amount_cents": 26400,
            "tendered_on": "2026-11-29T00:00:00Z",
            "method": "ACH",
            "allocation_mode": "EXPLICIT",
            "expected_alarm_site_version": X.site_version(api, bundle.site_id),
            "explicit_allocations": [
                {"penalty_invoice_id": invoice_id, "amount_cents": 26400}
            ],
        },
        U.BILLING_CLERK,
    )
    validate_error(refused, E.ERR_INVOICE_WRITTEN_OFF, expected_status=409)

    A.assert_invoice_totals(
        X.get_invoice(api, invoice_id),
        adjusted_cents=26400,
        outstanding_cents=0,
        collections_stage="WRITTEN_OFF",
    )
    A.assert_total_count(api.list_payment_records(U.PROGRAM_ADMIN), 0)
    A.assert_total_count(api.list_payment_allocations(U.PROGRAM_ADMIN), 0)
    site = X.get_site(api, bundle.site_id)
    A.assert_money_cents(site["credit_balance_cents"], 0)
    A.assert_money_cents(site["outstanding_balance_cents"], 0)


def test_determination_exempt_with_an_unrecognized_cause_code_is_rejected(api):
    """An exempt cause outside the governing schedule's list is refused.

    "A supplied `exempt_cause_code` must be a member of the governing schedule's
    `exempt_cause_codes` list, on both incident determination and appeal decision, failing
    with `ERR_EXEMPT_CAUSE_NOT_RECOGNIZED`." (PRD §2.10)

    "Coherence is required both ways: an `EXEMPT` ruling must supply a recognized exempt
    cause and a `COUNTED` ruling must supply none, else `ERR_EXEMPT_CAUSE_MUST_BE_EXEMPT`;
    and any supplied cause must be a member of the governing schedule's
    `exempt_cause_codes`, else `ERR_EXEMPT_CAUSE_NOT_RECOGNIZED`." (PRD §3.5)

    "`exempt_cause_codes` lists the causes that force an exempt determination — by default
    `SEVERE_WEATHER`, `UTILITY_POWER_FAILURE`, `TELEPHONE_LINE_FAILURE`,
    `AUTHORIZED_TEST_WITH_NOTICE`, `CRIMINAL_OFFENSE_CONFIRMED` and
    `NEW_INSTALLATION_GRACE`." (PRD §3.1)

    Design: Corner/validations/determination_exempt_with_an_unrecognized_cause_code_is_rejected
    """
    bundle = X.setup_program_baseline(api, clock=C.CLOCK_STARTUP_UTC)
    incident = X.create_reported_incident(
        api, bundle, bundle.system_id, C.FIRST_CHARGEABLE_OCCURRED_AT
    )
    assert "CONTRACTOR_ON_SITE" not in C.EXEMPT_CAUSE_CODES

    refused = api.determine_incident(
        incident.incident_id,
        F.determination_payload(
            "EXEMPT",
            exempt_cause_code="CONTRACTOR_ON_SITE",
            review_notes="Officer reported a contractor working in the protected area.",
        ),
        U.REVIEW_OFFICER,
    )
    validate_error(refused, E.ERR_EXEMPT_CAUSE_NOT_RECOGNIZED, expected_status=422)

    held = X.get_incident(api, incident.incident_id)
    A.assert_status(held, "REPORTED")
    assert held["determination"] is None
    assert held["determined_at"] is None
    assert held["determined_by_user_id"] is None

    accepted = X.determine_exempt(api, incident.incident_id, "SEVERE_WEATHER")
    assert accepted["status"] == "EXEMPT"


def test_determination_exempt_without_any_cause_code_is_rejected(api):
    """An exempt ruling that names no statutory cause fails the coherence check.

    "Determination coherence then requires that an exempt ruling supplies a recognized
    exempt cause and a chargeable ruling supplies none, failing with
    `ERR_EXEMPT_CAUSE_MUST_BE_EXEMPT`." (PRD §2.10)

    "A `FalseAlarmReviewOfficer` then rules on it, supplying `determination` as either
    `COUNTED` or `EXEMPT`, an `exempt_cause_code` when exempting, and optional
    `review_notes`." (PRD §3.5) — the cause is conditional rather than universally
    required, so the missing-field check at position 4 passes and only the coherence row at
    position 24 can reject the pair.

    Design: Corner/validations/determination_exempt_without_any_cause_code_is_rejected
    """
    bundle = X.setup_program_baseline(api, clock=C.CLOCK_STARTUP_UTC)
    incident = X.create_reported_incident(
        api, bundle, bundle.system_id, C.FIRST_CHARGEABLE_OCCURRED_AT
    )
    site_version_before = X.site_version(api, bundle.site_id)

    refused = api.determine_incident(
        incident.incident_id,
        F.determination_payload(
            "EXEMPT",
            review_notes="Reviewer waived the occurrence without naming a statutory cause.",
        ),
        U.REVIEW_OFFICER,
    )
    validate_error(refused, E.ERR_EXEMPT_CAUSE_MUST_BE_EXEMPT, expected_status=422)

    A.assert_status(X.get_incident(api, incident.incident_id), "REPORTED")
    A.assert_total_count(
        api.list_penalty_invoices(
            U.BILLING_CLERK, {"false_alarm_incident_id": incident.incident_id}
        ),
        0,
    )
    site = X.get_site(api, bundle.site_id)
    assert site["chargeable_count_window"] == 0
    assert site["version"] == site_version_before


def test_dispatch_request_from_a_suspended_monitoring_company_is_forbidden(api):
    """A suspended monitoring company may not lodge dispatch requests at all.

    "The reporting monitoring company must be `ACTIVE` or `PROBATION`; a `SUSPENDED` or
    `REVOKED` company may neither lodge dispatch requests nor open incident reports, and
    both operations fail with `ERR_COMPANY_DISPATCH_PRIVILEGE_SUSPENDED`." (PRD §2.10)

    "with `ERR_COMPANY_DISPATCH_PRIVILEGE_SUSPENDED` when the company is `SUSPENDED` or
    `REVOKED`" (PRD §3.4)

    The acting operator holds the company it names, so the role and ownership positions are
    both satisfied and only the company's own state can reject the call.

    Design: Corner/validations/dispatch_request_from_a_suspended_monitoring_company_is_forbidden
    """
    bundle = X.setup_program_baseline(api, clock=C.CLOCK_STARTUP_UTC)

    suspended = api.company_status_action(
        bundle.company_id,
        {
            "action": "SUSPEND",
            "status_reason": "Two consecutive variance-flagged periods and an unanswered audit letter.",
        },
        U.PROGRAM_ADMIN,
    )
    validate_success(suspended, 200)
    A.assert_status(get_success_data(suspended), "SUSPENDED")

    X.set_clock(api, "2026-09-15T00:00:00Z")
    refused = api.create_dispatch_request(
        F.dispatch_request_payload(
            bundle.system_id,
            "2026-09-15T03:09:00Z",
            [
                F.call_attempt(bundle.contact_ids[0], "2026-09-15T03:10:00Z", "NO_ANSWER"),
                F.call_attempt(bundle.contact_ids[1], "2026-09-15T03:11:00Z", "NO_ANSWER"),
            ],
            idempotency_key="gsm-0915-suspended",
        ),
        bundle.operator_headers,
    )
    validate_error(
        refused, E.ERR_COMPANY_DISPATCH_PRIVILEGE_SUSPENDED, expected_status=403
    )

    A.assert_status(X.get_company(api, bundle.company_id), "SUSPENDED")
    A.assert_total_count(
        api.list_dispatch_requests(
            U.PROGRAM_ADMIN, {"monitoring_company_id": bundle.company_id}
        ),
        0,
    )


def test_dispatch_request_for_a_thin_contact_roster_returns_insufficient_ecv_contacts(api):
    """A one-contact roster is an aggregate failure, refused at submission time.

    "Next, the premises' live contact roster must satisfy the distinct-contact minimum
    required for that system's posture — a premises that cannot be called back may not have
    a dispatch requested for it — failing with `ERR_INSUFFICIENT_ECV_CONTACTS`." (PRD §2.10)

    "A removal that would leave fewer than 2 live callable contacts is refused with
    `ERR_CONTACT_ROSTER_MINIMUM` while the premises still holds a system in `SUBMITTED` or
    `PERMITTED`, and the same minimum of 2 distinct callable contacts is what enhanced call
    verification is measured against in §3.4." (PRD §3.2)

    Every individual roster row is valid; only the count is short, so restoring the count
    lets the identical submission through.

    Design: Corner/validations/dispatch_request_for_a_thin_contact_roster_returns_insufficient_ecv_contacts
    """
    X.set_clock(api, C.CLOCK_STARTUP_UTC)
    X.create_active_fee_schedule(api)
    company_id = X.create_company(api)
    site_id = X.create_site(api, address_key="88-ELM-AVE-75204-THIN")
    contact_id = X.create_contact(
        api,
        site_id,
        full_name="Iris Nakamura",
        phone_number="+12145550221",
        relationship="OWNER",
        contact_priority=1,
        is_ecv_callable=True,
    )
    system_id = X.create_submitted_system(
        api, site_id, company_id, zone_count=3, installed_at="2026-07-20T10:00:00Z"
    )
    operator = U.alarm_company_operator(company_id)

    X.set_clock(api, "2026-09-15T00:00:00Z")
    payload = F.dispatch_request_payload(
        system_id,
        "2026-09-15T04:00:00Z",
        [F.call_attempt(contact_id, "2026-09-15T04:01:00Z", "NO_ANSWER")],
        idempotency_key="gsm-0915-thin",
    )

    refused = api.create_dispatch_request(payload, operator)
    validate_error(refused, E.ERR_INSUFFICIENT_ECV_CONTACTS, expected_status=409)

    assert X.get_site(api, site_id)["ecv_callable_contact_count"] == 1
    A.assert_total_count(
        api.list_dispatch_requests(U.PROGRAM_ADMIN, {"alarm_system_id": system_id}), 0
    )

    X.create_contact(api, site_id, contact_priority=2, is_ecv_callable=True)
    accepted = api.create_dispatch_request(payload, operator)
    validate_success(accepted, 201)


def test_dispatch_request_validate_with_one_distinct_contact_is_rejected(api):
    """Two calls to one contact are one distinct contact, so validation is refused.

    "`distinct_ecv_contact_count` is then the number of distinct contact identifiers
    surviving that filter, defaulting to 0 for an empty log." (PRD §3.4)

    "a log of two calls placed to the *same* contact yields a distinct count of 1 and is
    therefore insufficient for a two-call request even though two calls really were made"
    (PRD §3.4)

    "Then, at validation time, the request's frozen verification sufficiency must be true,
    failing with `ERR_ECV_REQUIREMENT_NOT_MET`" (PRD §2.10)

    The premises exposes three callable contacts, so the submission-time roster minimum is
    met and the request is accepted; only the frozen sufficiency is false.

    Design: Corner/validations/dispatch_request_validate_with_one_distinct_contact_is_rejected
    """
    bundle = X.setup_program_baseline(
        api, clock=C.CLOCK_STARTUP_UTC, contact_count=3
    )
    X.set_clock(api, "2026-09-15T00:00:00Z")

    submitted = api.create_dispatch_request(
        F.dispatch_request_payload(
            bundle.system_id,
            "2026-09-15T05:00:00Z",
            [
                F.call_attempt(bundle.contact_ids[0], "2026-09-15T05:01:00Z", "NO_ANSWER"),
                F.call_attempt(bundle.contact_ids[0], "2026-09-15T05:03:00Z", "VOICEMAIL"),
            ],
            idempotency_key="gsm-0915-onecontact",
        ),
        bundle.operator_headers,
    )
    validate_success(submitted, 201)
    frozen = get_success_data(submitted)
    assert frozen["distinct_ecv_contact_count"] == 1
    assert frozen["ecv_sufficient"] is False
    request_id = frozen["id"]

    refused = api.validate_dispatch_request(request_id, U.DISPATCH_SUPERVISOR)
    validate_error(refused, E.ERR_ECV_REQUIREMENT_NOT_MET, expected_status=422)

    still = get_success_data(api.get_dispatch_request(request_id, U.PROGRAM_ADMIN))
    A.assert_status(still, "SUBMITTED")
    assert still["validated_at"] is None
    assert still["validated_by_user_id"] is None


def test_dispatch_request_validate_without_audio_video_proof_is_rejected(api):
    """A guard on scene cannot substitute for the recording the system demands.

    "and the verified-response proof must match the system's requirement — recorded
    audio/video asserted when the system demands `AUDIO_VIDEO_REQUIRED`, a guard on scene
    asserted when it demands `GUARD_REQUIRED` — failing with
    `ERR_VERIFIED_RESPONSE_NOT_CONFIRMED`." (PRD §2.10)

    "and the verified-response proof to match what the system demands —
    `audio_video_evidence` true when the system's `verified_response_mode` is
    `AUDIO_VIDEO_REQUIRED`, `guard_on_scene` true when it is `GUARD_REQUIRED` — else
    `ERR_VERIFIED_RESPONSE_NOT_CONFIRMED`." (PRD §3.4)

    "otherwise it is true when the `verification_method` is `TWO_CALL_ECV` and
    `distinct_ecv_contact_count` is at least 2" (PRD §3.4) — the two attempts here name two
    distinct contacts, so the frozen sufficiency is true and the earlier gate cannot be what
    answers.

    Design: Corner/validations/dispatch_request_validate_without_audio_video_proof_is_rejected
    """
    bundle = X.setup_program_baseline(api, clock=C.CLOCK_STARTUP_UTC)
    av_system_id, _ = X.add_permitted_system(
        api,
        bundle,
        zone_count=6,
        verified_response_mode="AUDIO_VIDEO_REQUIRED",
        installed_at="2026-07-26T09:00:00Z",
    )
    X.set_clock(api, "2026-09-16T00:00:00Z")

    submitted = api.create_dispatch_request(
        F.dispatch_request_payload(
            av_system_id,
            "2026-09-16T02:00:00Z",
            [
                F.call_attempt(bundle.contact_ids[0], "2026-09-16T02:01:00Z", "NO_ANSWER"),
                F.call_attempt(bundle.contact_ids[1], "2026-09-16T02:02:00Z", "NO_ANSWER"),
            ],
            audio_video_evidence=False,
            guard_on_scene=True,
            idempotency_key="gsm-0916-av",
        ),
        bundle.operator_headers,
    )
    validate_success(submitted, 201)
    request_id = get_success_data(submitted)["id"]
    assert get_success_data(submitted)["ecv_sufficient"] is True

    refused = api.validate_dispatch_request(request_id, U.DISPATCH_SUPERVISOR)
    validate_error(
        refused, E.ERR_VERIFIED_RESPONSE_NOT_CONFIRMED, expected_status=409
    )

    still = get_success_data(api.get_dispatch_request(request_id, U.PROGRAM_ADMIN))
    A.assert_status(still, "SUBMITTED")
    assert still["validated_at"] is None
