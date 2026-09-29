"""Composite setup helpers.

The harness restarts the API server with an empty database before every single
test, so every precondition here is rebuilt from scratch through the PRD's own
endpoints. Each helper returns the created rows (or their identifiers) and
raises immediately if any step does not succeed, so a broken precondition never
masquerades as a failed assertion.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data, validate_success

from . import factories
from .api_client import ApiClient
from .constants import CLOCK_PRESENT_UTC, FEE_SCHEDULE_DEFAULTS
from .test_users import (
    BILLING_CLERK,
    DISPATCH_SUPERVISOR,
    HEARING_OFFICER,
    HEARING_OFFICER_ID,
    PERMIT_CLERK,
    PROGRAM_ADMIN,
    REVIEW_OFFICER,
    alarm_company_operator,
    alarm_user,
)


# --------------------------------------------------------------------------- #
# Time helpers
# --------------------------------------------------------------------------- #
def iso(moment: datetime) -> str:
    """Render a datetime as the Z-suffixed UTC instant the API speaks."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse(instant: str) -> datetime:
    """Parse a Z-suffixed UTC instant, with or without fractional digits.

    PRD §2.4 records timestamps as "an ISO 8601 UTC timestamp with three
    fractional digits", so a server-computed instant arrives as
    ``2026-08-31T00:00:00.000Z`` while a client-supplied one echoes back
    exactly as it was sent.  Both forms name the same instant.
    """
    text = instant.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1]
    fmt = "%Y-%m-%dT%H:%M:%S.%f" if "." in text else "%Y-%m-%dT%H:%M:%S"
    return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)


def same_instant(left: str, right: str) -> bool:
    """True when two Z-suffixed renderings name the same UTC instant."""
    return parse(left) == parse(right)


def plus_days(instant: str, days: int) -> str:
    return iso(parse(instant) + timedelta(days=days))


def plus_minutes(instant: str, minutes: int) -> str:
    return iso(parse(instant) + timedelta(minutes=minutes))


def plus_hours(instant: str, hours: int) -> str:
    return iso(parse(instant) + timedelta(hours=hours))


def day_start(instant: str) -> str:
    return iso(parse(instant).replace(hour=0, minute=0, second=0))


def date_part(instant: str) -> str:
    return instant[:10]


# --------------------------------------------------------------------------- #
# Result containers
# --------------------------------------------------------------------------- #
@dataclass
class SiteBundle:
    """A premises with its roster, its monitoring company and its systems."""

    schedule_id: str
    company_id: str
    site_id: str
    contact_ids: List[str] = field(default_factory=list)
    system_ids: List[str] = field(default_factory=list)
    permit_ids: List[str] = field(default_factory=list)

    @property
    def system_id(self) -> str:
        return self.system_ids[0]

    @property
    def permit_id(self) -> str:
        return self.permit_ids[0]

    @property
    def operator_headers(self) -> Dict[str, str]:
        return alarm_company_operator(self.company_id)

    @property
    def holder_headers(self) -> Dict[str, str]:
        return alarm_user(self.site_id)


@dataclass
class IncidentBundle:
    """One chargeable-path incident together with the rows behind it."""

    site: SiteBundle
    system_id: str
    dispatch_request_id: str
    incident_id: str
    occurred_at: str
    invoice_id: Optional[str] = None


# --------------------------------------------------------------------------- #
# Primitive steps
# --------------------------------------------------------------------------- #
def set_clock(api: ApiClient, instant: str, headers: Dict[str, str] = PROGRAM_ADMIN) -> Dict[str, Any]:
    response = api.set_clock({"current_utc": instant}, headers)
    validate_success(response, 200)
    return get_success_data(response)


def run_nightly(api: ApiClient, headers: Dict[str, str] = PROGRAM_ADMIN) -> Dict[str, Any]:
    response = api.run_nightly(headers)
    validate_success(response, 200)
    return get_success_data(response)


def create_active_fee_schedule(api: ApiClient, **overrides: Any) -> str:
    """Publish and activate one schedule; returns its identifier."""
    payload = factories.fee_schedule_payload(**overrides)
    response = api.create_fee_schedule(payload, PROGRAM_ADMIN)
    validate_success(response, 201)
    schedule_id = get_success_data(response)["id"]
    validate_success(api.activate_fee_schedule(schedule_id, PROGRAM_ADMIN), 200)
    return schedule_id


def create_draft_fee_schedule(api: ApiClient, **overrides: Any) -> str:
    payload = factories.fee_schedule_payload(**overrides)
    response = api.create_fee_schedule(payload, PROGRAM_ADMIN)
    validate_success(response, 201)
    return get_success_data(response)["id"]


def create_company(api: ApiClient, **overrides: Any) -> str:
    response = api.create_alarm_company(factories.alarm_company_payload(**overrides), PROGRAM_ADMIN)
    validate_success(response, 201)
    return get_success_data(response)["id"]


def create_site(api: ApiClient, **overrides: Any) -> str:
    response = api.create_alarm_site(factories.alarm_site_payload(**overrides), PROGRAM_ADMIN)
    validate_success(response, 201)
    return get_success_data(response)["id"]


def create_contact(api: ApiClient, site_id: str, **overrides: Any) -> str:
    response = api.create_site_contact(
        factories.site_contact_payload(site_id, **overrides), PROGRAM_ADMIN
    )
    validate_success(response, 201)
    return get_success_data(response)["id"]


def create_contacts(api: ApiClient, site_id: str, count: int = 2) -> List[str]:
    """A callable roster large enough for two-call verification."""
    ids = []
    for index in range(1, count + 1):
        ids.append(
            create_contact(
                api,
                site_id,
                contact_priority=index,
                is_ecv_callable=True,
                relationship="OWNER" if index == 1 else "KEYHOLDER",
            )
        )
    return ids


def create_submitted_system(api: ApiClient, site_id: str, company_id: str, **overrides: Any) -> str:
    response = api.create_alarm_system(
        factories.alarm_system_payload(site_id, company_id, **overrides), PROGRAM_ADMIN
    )
    validate_success(response, 201)
    return get_success_data(response)["id"]


def approve_system(api: ApiClient, system_id: str, headers: Dict[str, str] = PERMIT_CLERK) -> str:
    """Approve a submitted registration; returns the issued permit identifier."""
    response = api.approve_registration(system_id, headers)
    validate_success(response, 201)
    return get_success_data(response)["id"]


def create_permitted_system(
    api: ApiClient, site_id: str, company_id: str, **overrides: Any
) -> Tuple[str, str]:
    """Submit and approve one system; returns (system_id, permit_id)."""
    system_id = create_submitted_system(api, site_id, company_id, **overrides)
    permit_id = approve_system(api, system_id)
    return system_id, permit_id


def version_of(api: ApiClient, getter_name: str, resource_id: str, headers: Dict[str, str]) -> int:
    """Current revision counter of one row, read back through its GET route."""
    response = getattr(api, getter_name)(resource_id, headers)
    validate_success(response, 200)
    return get_success_data(response)["version"]


def site_version(api: ApiClient, site_id: str) -> int:
    return version_of(api, "get_alarm_site", site_id, PROGRAM_ADMIN)


def system_version(api: ApiClient, system_id: str) -> int:
    return version_of(api, "get_alarm_system", system_id, PROGRAM_ADMIN)


def permit_version(api: ApiClient, permit_id: str) -> int:
    return version_of(api, "get_alarm_permit", permit_id, PERMIT_CLERK)


def incident_version(api: ApiClient, incident_id: str) -> int:
    return version_of(api, "get_false_alarm_incident", incident_id, REVIEW_OFFICER)


def docket_version(api: ApiClient, docket_id: str) -> int:
    return version_of(api, "get_hearing_docket", docket_id, HEARING_OFFICER)


def invoice_version(api: ApiClient, invoice_id: str) -> int:
    return version_of(api, "get_penalty_invoice", invoice_id, BILLING_CLERK)


def get_site(api: ApiClient, site_id: str) -> Dict[str, Any]:
    response = api.get_alarm_site(site_id, PROGRAM_ADMIN)
    validate_success(response, 200)
    return get_success_data(response)


def get_summary(api: ApiClient, site_id: str) -> Dict[str, Any]:
    response = api.get_false_alarm_summary(site_id, PROGRAM_ADMIN)
    validate_success(response, 200)
    return get_success_data(response)


def get_incident(api: ApiClient, incident_id: str) -> Dict[str, Any]:
    response = api.get_false_alarm_incident(incident_id, REVIEW_OFFICER)
    validate_success(response, 200)
    return get_success_data(response)


def get_invoice(api: ApiClient, invoice_id: str) -> Dict[str, Any]:
    response = api.get_penalty_invoice(invoice_id, BILLING_CLERK)
    validate_success(response, 200)
    return get_success_data(response)


def get_permit(api: ApiClient, permit_id: str) -> Dict[str, Any]:
    response = api.get_alarm_permit(permit_id, PERMIT_CLERK)
    validate_success(response, 200)
    return get_success_data(response)


def get_system(api: ApiClient, system_id: str) -> Dict[str, Any]:
    response = api.get_alarm_system(system_id, PROGRAM_ADMIN)
    validate_success(response, 200)
    return get_success_data(response)


def get_company(api: ApiClient, company_id: str) -> Dict[str, Any]:
    response = api.get_alarm_company(company_id, PROGRAM_ADMIN)
    validate_success(response, 200)
    return get_success_data(response)


def get_appeal(api: ApiClient, appeal_id: str) -> Dict[str, Any]:
    response = api.get_appeal(appeal_id, PROGRAM_ADMIN)
    validate_success(response, 200)
    return get_success_data(response)


def get_order(api: ApiClient, order_id: str) -> Dict[str, Any]:
    response = api.get_suspension_order(order_id, PROGRAM_ADMIN)
    validate_success(response, 200)
    return get_success_data(response)


def get_payment(api: ApiClient, payment_id: str) -> Dict[str, Any]:
    response = api.get_payment_record(payment_id, BILLING_CLERK)
    validate_success(response, 200)
    return get_success_data(response)


def get_report(api: ApiClient, report_id: str) -> Dict[str, Any]:
    response = api.get_compliance_report(report_id, PROGRAM_ADMIN)
    validate_success(response, 200)
    return get_success_data(response)


def invoices_of_site(api: ApiClient, site_id: str, **params: Any) -> List[Dict[str, Any]]:
    query = {"alarm_site_id": site_id, "per_page": 100}
    query.update(params)
    response = api.list_penalty_invoices(BILLING_CLERK, query)
    validate_success(response, 200)
    return response.json()["data"]


def invoice_for_incident(api: ApiClient, incident_id: str) -> Dict[str, Any]:
    response = api.list_penalty_invoices(
        BILLING_CLERK, {"false_alarm_incident_id": incident_id, "kind": "FALSE_ALARM_FEE"}
    )
    validate_success(response, 200)
    rows = response.json()["data"]
    assert len(rows) == 1, f"expected one false alarm fee invoice for {incident_id}, got {len(rows)}"
    return rows[0]


def allocations_of_payment(api: ApiClient, payment_id: str) -> List[Dict[str, Any]]:
    response = api.list_payment_allocations(BILLING_CLERK, {"payment_record_id": payment_id, "per_page": 100})
    validate_success(response, 200)
    return response.json()["data"]


def orders_of_site(api: ApiClient, site_id: str) -> List[Dict[str, Any]]:
    response = api.list_suspension_orders(PROGRAM_ADMIN, {"alarm_site_id": site_id, "per_page": 100})
    validate_success(response, 200)
    return response.json()["data"]


def incidents_of_site(api: ApiClient, site_id: str) -> List[Dict[str, Any]]:
    response = api.list_false_alarm_incidents(REVIEW_OFFICER, {"alarm_site_id": site_id, "per_page": 100})
    validate_success(response, 200)
    return response.json()["data"]


# --------------------------------------------------------------------------- #
# Composite premises setup
# --------------------------------------------------------------------------- #
def setup_program_baseline(
    api: ApiClient,
    *,
    clock: str = CLOCK_PRESENT_UTC,
    schedule_overrides: Optional[Dict[str, Any]] = None,
    site_overrides: Optional[Dict[str, Any]] = None,
    company_overrides: Optional[Dict[str, Any]] = None,
    contact_count: int = 2,
    system_count: int = 1,
    installed_at: str = "2026-08-01T00:00:00Z",
    approve: bool = True,
) -> SiteBundle:
    """An active schedule, a company, a premises with a callable roster, and
    ``system_count`` registrations approved into permits.

    The clock is set first so the permits are issued at the schedule's effective
    instant, then advanced to ``clock`` after issuance so that the
    new-installation grace period of the first permit has already elapsed.
    """
    set_clock(api, installed_at)
    schedule_id = create_active_fee_schedule(api, **(schedule_overrides or {}))
    company_id = create_company(api, **(company_overrides or {}))
    site_id = create_site(api, **(site_overrides or {}))
    contact_ids = create_contacts(api, site_id, contact_count)

    system_ids: List[str] = []
    permit_ids: List[str] = []
    for _ in range(system_count):
        system_id = create_submitted_system(api, site_id, company_id, installed_at=installed_at)
        system_ids.append(system_id)
        if approve:
            permit_ids.append(approve_system(api, system_id))

    if clock != installed_at:
        set_clock(api, clock)

    return SiteBundle(
        schedule_id=schedule_id,
        company_id=company_id,
        site_id=site_id,
        contact_ids=contact_ids,
        system_ids=system_ids,
        permit_ids=permit_ids,
    )


def add_permitted_system(api: ApiClient, bundle: SiteBundle, **overrides: Any) -> Tuple[str, str]:
    """Register and approve one more system on an existing premises."""
    system_id, permit_id = create_permitted_system(
        api, bundle.site_id, bundle.company_id, **overrides
    )
    bundle.system_ids.append(system_id)
    bundle.permit_ids.append(permit_id)
    return system_id, permit_id


# --------------------------------------------------------------------------- #
# Dispatch requests
# --------------------------------------------------------------------------- #
def two_call_attempts(bundle: SiteBundle, occurred_at: str) -> List[Dict[str, Any]]:
    """Two attempts against two distinct callable contacts, neither cancelling."""
    return [
        factories.call_attempt(bundle.contact_ids[0], plus_minutes(occurred_at, 1), "NO_ANSWER"),
        factories.call_attempt(bundle.contact_ids[1], plus_minutes(occurred_at, 3), "VOICEMAIL"),
    ]


def submit_dispatch_request(
    api: ApiClient,
    bundle: SiteBundle,
    system_id: str,
    occurred_at: str,
    *,
    call_attempts: Optional[List[Dict[str, Any]]] = None,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> str:
    payload = factories.dispatch_request_payload(
        system_id,
        occurred_at,
        call_attempts if call_attempts is not None else two_call_attempts(bundle, occurred_at),
        **overrides,
    )
    response = api.create_dispatch_request(payload, headers or bundle.operator_headers)
    validate_success(response, 201)
    return get_success_data(response)["id"]


def create_dispatched_request(
    api: ApiClient,
    bundle: SiteBundle,
    system_id: str,
    occurred_at: str,
    **overrides: Any,
) -> str:
    """Submit, validate and record dispatch on one request."""
    request_id = submit_dispatch_request(api, bundle, system_id, occurred_at, **overrides)
    validate_success(api.validate_dispatch_request(request_id, DISPATCH_SUPERVISOR), 200)
    validate_success(api.record_dispatch(request_id, DISPATCH_SUPERVISOR), 200)
    return request_id


def create_reported_incident(
    api: ApiClient,
    bundle: SiteBundle,
    system_id: str,
    occurred_at: str,
    *,
    cause_code: str = "OPERATOR_ERROR",
    **request_overrides: Any,
) -> IncidentBundle:
    """Drive one system all the way to an incident sitting in the reported state."""
    request_id = create_dispatched_request(api, bundle, system_id, occurred_at, **request_overrides)
    response = api.create_false_alarm_incident(
        factories.false_alarm_incident_payload(request_id, cause_code=cause_code),
        DISPATCH_SUPERVISOR,
    )
    validate_success(response, 201)
    return IncidentBundle(
        site=bundle,
        system_id=system_id,
        dispatch_request_id=request_id,
        incident_id=get_success_data(response)["id"],
        occurred_at=occurred_at,
    )


def determine_counted(api: ApiClient, incident_id: str, **overrides: Any) -> Dict[str, Any]:
    response = api.determine_incident(
        incident_id, factories.determination_payload("COUNTED", **overrides), REVIEW_OFFICER
    )
    validate_success(response, 200)
    return get_success_data(response)


def determine_exempt(api: ApiClient, incident_id: str, exempt_cause_code: str, **overrides: Any) -> Dict[str, Any]:
    response = api.determine_incident(
        incident_id,
        factories.determination_payload("EXEMPT", exempt_cause_code=exempt_cause_code, **overrides),
        REVIEW_OFFICER,
    )
    validate_success(response, 200)
    return get_success_data(response)


def create_counted_incident(
    api: ApiClient,
    bundle: SiteBundle,
    system_id: str,
    occurred_at: str,
    *,
    cause_code: str = "OPERATOR_ERROR",
    **request_overrides: Any,
) -> IncidentBundle:
    """One incident ruled chargeable, with its fee invoice discovered."""
    incident = create_reported_incident(
        api, bundle, system_id, occurred_at, cause_code=cause_code, **request_overrides
    )
    determined = determine_counted(api, incident.incident_id)
    if determined.get("assessed_fee_cents"):
        incident.invoice_id = invoice_for_incident(api, incident.incident_id)["id"]
    return incident


def accumulate_counted_incidents(
    api: ApiClient,
    bundle: SiteBundle,
    occurrences: List[str],
    *,
    cause_code: str = "OPERATOR_ERROR",
) -> List[IncidentBundle]:
    """One chargeable incident per instant in ``occurrences``.

    Each incident gets its own system, because a dispatched request stays open
    on its own system and a second request for the same system would be refused.
    """
    incidents: List[IncidentBundle] = []
    for index, occurred_at in enumerate(occurrences):
        while len(bundle.system_ids) <= index:
            add_permitted_system(api, bundle)
        set_clock(api, day_start(occurred_at))
        incidents.append(
            create_counted_incident(
                api, bundle, bundle.system_ids[index], occurred_at, cause_code=cause_code
            )
        )
    return incidents


# --------------------------------------------------------------------------- #
# Hearing dockets and appeals
# --------------------------------------------------------------------------- #
def create_docket(
    api: ApiClient,
    session_start: str,
    session_end: str,
    *,
    officer_user_id: str = HEARING_OFFICER_ID,
    headers: Dict[str, str] = PROGRAM_ADMIN,
    **overrides: Any,
) -> str:
    response = api.create_hearing_docket(
        factories.hearing_docket_payload(officer_user_id, session_start, session_end, **overrides),
        headers,
    )
    validate_success(response, 201)
    return get_success_data(response)["id"]


def file_appeal(
    api: ApiClient,
    bundle: SiteBundle,
    incident_id: str,
    *,
    grounds: str = "WRONG_CAUSE_CODE",
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> str:
    """File an appeal against a chargeable incident, reading its revision first."""
    payload = factories.appeal_payload(
        incident_id,
        grounds=grounds,
        expected_false_alarm_incident_version=incident_version(api, incident_id),
        **overrides,
    )
    response = api.create_appeal(payload, headers or bundle.holder_headers)
    validate_success(response, 201)
    return get_success_data(response)["id"]


def schedule_appeal(
    api: ApiClient,
    appeal_id: str,
    docket_id: str,
    *,
    headers: Dict[str, str] = HEARING_OFFICER,
) -> Dict[str, Any]:
    response = api.schedule_appeal(
        appeal_id,
        {
            "hearing_docket_id": docket_id,
            "expected_hearing_docket_version": docket_version(api, docket_id),
        },
        headers,
    )
    validate_success(response, 200)
    return get_success_data(response)


def hold_session(api: ApiClient, docket_id: str, headers: Dict[str, str] = HEARING_OFFICER) -> Dict[str, Any]:
    response = api.hold_session(docket_id, {}, headers)
    validate_success(response, 200)
    return get_success_data(response)


def create_heard_appeal(
    api: ApiClient,
    bundle: SiteBundle,
    incident_id: str,
    *,
    session_start: str,
    session_end: str,
    grounds: str = "WRONG_CAUSE_CODE",
    officer_user_id: str = HEARING_OFFICER_ID,
    officer_headers: Dict[str, str] = HEARING_OFFICER,
) -> Tuple[str, str]:
    """File an appeal, dock it, advance the clock into the session and hold it.

    Returns (appeal_id, docket_id) with the appeal sitting in the heard state,
    ready for a decision.
    """
    appeal_id = file_appeal(api, bundle, incident_id, grounds=grounds)
    docket_id = create_docket(
        api, session_start, session_end, officer_user_id=officer_user_id
    )
    schedule_appeal(api, appeal_id, docket_id, headers=officer_headers)
    set_clock(api, session_start)
    hold_session(api, docket_id, officer_headers)
    return appeal_id, docket_id


def decide_appeal(
    api: ApiClient,
    appeal_id: str,
    decision: str,
    *,
    findings: str = "Decided on the record.",
    headers: Dict[str, str] = HEARING_OFFICER,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision, "findings": findings}
    payload.update(overrides)
    response = api.decide_appeal(appeal_id, payload, headers)
    validate_success(response, 200)
    return get_success_data(response)


# --------------------------------------------------------------------------- #
# Suspension orders
# --------------------------------------------------------------------------- #
def propose_suspension_order(
    api: ApiClient,
    bundle: SiteBundle,
    triggering_incident_id: str,
    effective_from: str,
    effective_through: str,
    *,
    headers: Dict[str, str] = PROGRAM_ADMIN,
    **overrides: Any,
) -> str:
    payload = factories.suspension_order_payload(
        bundle.site_id,
        triggering_incident_id,
        effective_from,
        effective_through,
        site_version(api, bundle.site_id),
        **overrides,
    )
    response = api.create_suspension_order(payload, headers)
    validate_success(response, 201)
    return get_success_data(response)["id"]


def create_served_suspension_order(
    api: ApiClient,
    bundle: SiteBundle,
    triggering_incident_id: str,
    effective_from: str,
    effective_through: str,
    **overrides: Any,
) -> str:
    """A suspension order proposed and then served, so response has stopped."""
    order_id = propose_suspension_order(
        api, bundle, triggering_incident_id, effective_from, effective_through, **overrides
    )
    validate_success(api.serve_suspension_order(order_id, PROGRAM_ADMIN), 200)
    return order_id


def request_reinstatement(
    api: ApiClient,
    order_id: str,
    *,
    technician_inspection_date: str,
    ecv_attestation: bool = True,
    corrective_action_summary: str = "Panel reprogrammed, motion sensor replaced, staff retrained on ECV.",
    headers: Optional[Dict[str, str]] = None,
    site_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "technician_inspection_date": technician_inspection_date,
        "ecv_attestation": ecv_attestation,
        "corrective_action_summary": corrective_action_summary,
    }
    payload.update(overrides)
    response = api.request_reinstatement(
        order_id,
        payload,
        headers or (alarm_user(site_id) if site_id else PROGRAM_ADMIN),
    )
    validate_success(response, 200)
    return get_success_data(response)


# --------------------------------------------------------------------------- #
# Invoices, payments and reports
# --------------------------------------------------------------------------- #
def adjust_invoice(
    api: ApiClient,
    invoice_id: str,
    kind: str,
    *,
    amount_cents: Optional[int] = None,
    reason: str = "Adjusted by the program administrator.",
    headers: Dict[str, str] = PROGRAM_ADMIN,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "adjustment_kind": kind,
        "reason": reason,
        "expected_penalty_invoice_version": invoice_version(api, invoice_id),
    }
    if amount_cents is not None:
        payload["amount_cents"] = amount_cents
    response = api.adjust_invoice(invoice_id, payload, headers)
    validate_success(response, 200)
    return get_success_data(response)


def post_payment(
    api: ApiClient,
    bundle: SiteBundle,
    amount_cents: int,
    tendered_on: str,
    *,
    allocation_mode: str = "AUTO_WATERFALL",
    explicit_allocations: Optional[List[Dict[str, Any]]] = None,
    method: str = "CHECK",
    headers: Dict[str, str] = BILLING_CLERK,
    **overrides: Any,
) -> str:
    payload = factories.payment_record_payload(
        bundle.site_id,
        amount_cents,
        tendered_on,
        site_version(api, bundle.site_id),
        allocation_mode=allocation_mode,
        method=method,
        **overrides,
    )
    if explicit_allocations is not None:
        payload["explicit_allocations"] = explicit_allocations
    response = api.create_payment_record(payload, headers)
    validate_success(response, 201)
    return get_success_data(response)["id"]


def pay_invoice_in_full(
    api: ApiClient,
    bundle: SiteBundle,
    invoice_id: str,
    tendered_on: str,
    *,
    headers: Dict[str, str] = BILLING_CLERK,
) -> str:
    """Settle one invoice exactly, by an explicit single-line allocation."""
    outstanding = get_invoice(api, invoice_id)["outstanding_cents"]
    return post_payment(
        api,
        bundle,
        outstanding,
        tendered_on,
        allocation_mode="EXPLICIT",
        explicit_allocations=[{"penalty_invoice_id": invoice_id, "amount_cents": outstanding}],
        headers=headers,
    )


def submit_compliance_report(
    api: ApiClient,
    bundle: SiteBundle,
    period_start: str,
    period_end: str,
    *,
    reported_dispatch_count: int = 10,
    reported_cancellation_count: int = 0,
    ecv_attempt_count: int = 10,
    headers: Optional[Dict[str, str]] = None,
) -> str:
    response = api.create_compliance_report(
        factories.compliance_report_payload(
            bundle.company_id,
            period_start,
            period_end,
            reported_dispatch_count=reported_dispatch_count,
            reported_cancellation_count=reported_cancellation_count,
            ecv_attempt_count=ecv_attempt_count,
        ),
        headers or bundle.operator_headers,
    )
    validate_success(response, 201)
    return get_success_data(response)["id"]


def review_compliance_report(
    api: ApiClient,
    report_id: str,
    decision: str,
    *,
    variance_notes: Optional[str] = None,
    headers: Dict[str, str] = REVIEW_OFFICER,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if variance_notes is not None:
        payload["variance_notes"] = variance_notes
    elif decision == "FLAG_VARIANCE":
        payload["variance_notes"] = "Reported volume does not match the recorded dispatch count."
    response = api.review_compliance_report(report_id, payload, headers)
    validate_success(response, 200)
    return get_success_data(response)
