"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared endpoints
only — the harness restarts the server (empty database) before each test, so
nothing is ever carried over. Setup calls go through get_success_data() (the
lenient 2xx validator) so a broken precondition surfaces as a clear setup failure
rather than an opaque assertion error.

Identity threading: the ClientContact role is entity-backed (its X-User-ID is the
acting Client's id), so every ownership-gated client call below uses
make_client_contact_headers(client["id"]) — never the shared fallback constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_client_contact_headers,
    make_engineer_headers,
    make_delivery_lead_headers,
)
from . import factories as F


# Convenience aliases for the five opaque roles.
AM = TEST_USERS["account_manager_headers"]
DL = TEST_USERS["delivery_lead_headers"]  # pm-001
DL2 = TEST_USERS["delivery_lead_2_headers"]  # pm-002
ENG = TEST_USERS["engineer_headers"]  # eng-001
ENG2 = TEST_USERS["engineer_2_headers"]  # eng-002
FIN = TEST_USERS["finance_officer_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------------------
# Tier 0: clock and single-entity creates
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str) -> dict:
    """Reposition the logical clock. Every business timestamp is stamped from it."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_client(**overrides) -> dict:
    return get_success_data(api_client.create_client(F.create_client_payload(**overrides), AM))


def create_lead(client_id: str, **overrides) -> dict:
    """An engagement in its birth state: LEAD / UNBILLED / HEALTHY / version 1."""
    payload = F.create_engagement_payload(client_id=client_id, **overrides)
    return get_success_data(api_client.create_engagement(payload, AM))


def get_engagement(engagement_id: str, headers=DL) -> dict:
    return get_success_data(api_client.get_engagement(engagement_id, headers))


def engagement_version(engagement_id: str, headers=FIN) -> int:
    """Read the engagement's current version for the optimistic-concurrency guard
    carried by change-request and invoice creation."""
    return get_engagement(engagement_id, headers)["version"]


# ---------------------------------------------------------------------------
# Tier 1: engagement state progression (LEAD -> QUALIFIED -> SOW_ISSUED -> ACTIVE)
# ---------------------------------------------------------------------------
def setup_active_engagement(
    billing_model="TIME_AND_MATERIALS",
    contract_value=100000.00,
    budget_hours_cap=500,
    standard_hourly_rate=200.00,
    start_date="2026-05-01",
    end_date="2026-08-31",
    source_channel="REFERRAL",
    title="Acme Portal",
    client=None,
) -> dict:
    """Client + engagement walked all the way to ACTIVE.

    Returns {"client": ..., "engagement": ..., "client_headers": ...}.
    """
    client = client or create_client()
    client_headers = make_client_contact_headers(client["id"])
    engagement = create_lead(client["id"], title=title, source_channel=source_channel)
    get_success_data(
        api_client.qualify_engagement(engagement["id"], F.qualify_payload(outcome="QUALIFY"), AM)
    )
    get_success_data(
        api_client.issue_sow(
            engagement["id"],
            F.sow_payload(
                billing_model=billing_model,
                contract_value=contract_value,
                budget_hours_cap=budget_hours_cap,
                standard_hourly_rate=standard_hourly_rate,
                start_date=start_date,
                end_date=end_date,
            ),
            AM,
        )
    )
    engagement = get_success_data(
        api_client.sign_engagement(engagement["id"], F.sign_payload(), client_headers)
    )
    return {"client": client, "engagement": engagement, "client_headers": client_headers}


# ---------------------------------------------------------------------------
# Tier 2: delivery plan — milestones, sprints, tickets
# ---------------------------------------------------------------------------
def create_milestone(engagement_id: str, **overrides) -> dict:
    payload = F.create_milestone_payload(engagement_id=engagement_id, **overrides)
    return get_success_data(api_client.create_milestone(payload, DL))


def create_sprint(engagement_id: str, **overrides) -> dict:
    payload = F.create_sprint_payload(engagement_id=engagement_id, **overrides)
    return get_success_data(api_client.create_sprint(payload, DL))


def activate_sprint(sprint_id: str) -> dict:
    return get_success_data(api_client.transition_sprint(sprint_id, "ACTIVE", DL))


def close_sprint(sprint_id: str) -> dict:
    return get_success_data(api_client.transition_sprint(sprint_id, "CLOSED", DL))


def create_ticket(sprint_id: str, **overrides) -> dict:
    payload = F.create_ticket_payload(sprint_id=sprint_id, **overrides)
    return get_success_data(api_client.create_ticket(payload, DL))


def start_ticket(ticket_id: str, actor_user_id="eng-001") -> dict:
    return get_success_data(
        api_client.transition_ticket(
            ticket_id, "IN_PROGRESS", make_engineer_headers(actor_user_id)
        )
    )


def setup_planned_sprint(engagement_overrides=None, sprint_overrides=None) -> dict:
    """Active engagement + one PLANNED sprint. Tickets may already be added."""
    ctx = setup_active_engagement(**(engagement_overrides or {}))
    ctx["sprint"] = create_sprint(ctx["engagement"]["id"], **(sprint_overrides or {}))
    return ctx


def setup_active_sprint(engagement_overrides=None, sprint_overrides=None) -> dict:
    """Active engagement + one ACTIVE sprint."""
    ctx = setup_planned_sprint(engagement_overrides, sprint_overrides)
    ctx["sprint"] = activate_sprint(ctx["sprint"]["id"])
    return ctx


def setup_ticket_in_progress(
    engagement_overrides=None,
    sprint_overrides=None,
    ticket_overrides=None,
    assignee="eng-001",
) -> dict:
    """Active engagement + ACTIVE sprint + one ticket already IN_PROGRESS.

    This is the common preamble for everything that logs or reviews time.
    """
    ctx = setup_active_sprint(engagement_overrides, sprint_overrides)
    overrides = dict(ticket_overrides or {})
    overrides.setdefault("assignee_user_id", assignee)
    ctx["ticket"] = create_ticket(ctx["sprint"]["id"], **overrides)
    ctx["ticket"] = start_ticket(ctx["ticket"]["id"], assignee)
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: the hours ledger — logging, approving, reversing time
# ---------------------------------------------------------------------------
def log_time(ticket_id: str, hours, work_date="2026-05-05", employee="eng-001", **overrides) -> dict:
    payload = F.create_time_entry_payload(
        ticket_id=ticket_id, hours=hours, work_date=work_date, **overrides
    )
    return get_success_data(
        api_client.create_time_entry(payload, make_engineer_headers(employee))
    )


def approve_time(time_entry_id: str, reviewer="pm-001") -> dict:
    return get_success_data(
        api_client.review_time_entry(
            time_entry_id, "APPROVE", make_delivery_lead_headers(reviewer)
        )
    )


def reject_time(time_entry_id: str, reviewer="pm-001") -> dict:
    return get_success_data(
        api_client.review_time_entry(
            time_entry_id, "REJECT", make_delivery_lead_headers(reviewer)
        )
    )


def reverse_time(time_entry_id: str, reason="Logged against the wrong ticket", reviewer="pm-001") -> dict:
    return get_success_data(
        api_client.reverse_time_entry(
            time_entry_id, reason, make_delivery_lead_headers(reviewer)
        )
    )


def setup_with_approved_hours(
    hours=9.0,
    contract_value=2000.00,
    budget_hours_cap=10,
    standard_hourly_rate=200.00,
    estimated_hours=8,
    work_date="2026-05-05",
    assignee="eng-001",
) -> dict:
    """Accumulation helper: drive the engagement's approved-hours ledger to an
    exact figure so a burn_ratio boundary can be landed on precisely.

    With the defaults (9.0h at 200.00/h against a 2000.00 contract) the ratio
    lands on exactly 0.9000, which is the inclusive AT_RISK boundary, so the
    engagement is AT_RISK and its ACTIVE sprint is spend-frozen.

    Returns the full context plus the approved entry under "time_entry".
    """
    ctx = setup_ticket_in_progress(
        engagement_overrides={
            "contract_value": contract_value,
            "budget_hours_cap": budget_hours_cap,
            "standard_hourly_rate": standard_hourly_rate,
        },
        ticket_overrides={"estimated_hours": estimated_hours},
        assignee=assignee,
    )
    entry = log_time(ctx["ticket"]["id"], hours, work_date=work_date, employee=assignee)
    ctx["time_entry"] = approve_time(entry["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: change requests
# ---------------------------------------------------------------------------
def create_change_request(engagement_id: str, delta_hours=30, rush=False, **overrides) -> dict:
    version = overrides.pop("expected_engagement_version", None)
    if version is None:
        version = engagement_version(engagement_id, DL)
    payload = F.create_change_request_payload(
        engagement_id=engagement_id,
        delta_hours=delta_hours,
        rush=rush,
        expected_engagement_version=version,
        **overrides,
    )
    return get_success_data(api_client.create_change_request(payload, DL))


def setup_submitted_change_request(engagement_id: str, delta_hours=30, rush=False, **overrides) -> dict:
    """A change request quoted and sitting in SUBMITTED, awaiting the client."""
    cr = create_change_request(engagement_id, delta_hours=delta_hours, rush=rush, **overrides)
    return get_success_data(api_client.submit_change_request(cr["id"], DL))


# ---------------------------------------------------------------------------
# Tier 4: releases, acceptance, and the cascade-created milestone invoice
# ---------------------------------------------------------------------------
def setup_building_release(
    engagement_overrides=None,
    milestone_overrides=None,
    version_label="v1.0.0",
) -> dict:
    """Active engagement + one PLANNED milestone + a freshly cut release sitting
    in BUILDING (no QA result recorded yet).

    Returns the context plus "milestone" and "release". The engagement defaults to
    FIXED so the acceptance cascade's conditional invoice link is reachable.
    """
    overrides = dict(engagement_overrides or {})
    overrides.setdefault("billing_model", "FIXED")
    overrides.setdefault("contract_value", 50000.00)
    overrides.setdefault("budget_hours_cap", 200)
    ctx = setup_active_engagement(**overrides)
    ctx["milestone"] = create_milestone(ctx["engagement"]["id"], **(milestone_overrides or {}))
    ctx["release"] = get_success_data(
        api_client.create_release(
            F.create_release_payload(
                engagement_id=ctx["engagement"]["id"],
                milestone_id=ctx["milestone"]["id"],
                version_label=version_label,
            ),
            ENG,
        )
    )
    return ctx


def setup_qa_passed_release(
    engagement_overrides=None,
    milestone_overrides=None,
    version_label="v1.0.0",
) -> dict:
    """Active engagement + one PLANNED milestone + a release that has passed QA
    with zero defects, ready for the client's acceptance decision."""
    ctx = setup_building_release(engagement_overrides, milestone_overrides, version_label)
    ctx["release"] = get_success_data(
        api_client.record_qa_result(ctx["release"]["id"], "PASS", 0, ENG2)
    )
    return ctx


def setup_accepted_release(engagement_overrides=None, milestone_overrides=None) -> dict:
    """QA-passed release accepted by the client. On a FIXED engagement the
    acceptance cascade completes the milestone and auto-creates the DRAFT
    milestone invoice, which is discovered by listing invoices on the milestone;
    the created invoice (if any) is returned under "invoice"."""
    ctx = setup_qa_passed_release(engagement_overrides, milestone_overrides)
    ctx["release"] = get_success_data(
        api_client.decide_acceptance(ctx["release"]["id"], "ACCEPT", ctx["client_headers"])
    )
    invoices = get_success_data(
        api_client.list_invoices(FIN, params={"milestone_id": ctx["milestone"]["id"]})
    )
    ctx["invoice"] = invoices[0] if invoices else None
    return ctx


def setup_issued_milestone_invoice(engagement_overrides=None, milestone_overrides=None) -> dict:
    """The full fixed-fee billing chain: milestone accepted through a release,
    its cascade invoice ISSUED. invoiced_amount now carries the invoice subtotal
    and the milestone has been dragged COMPLETED -> BILLED."""
    ctx = setup_accepted_release(engagement_overrides, milestone_overrides)
    ctx["invoice"] = get_success_data(api_client.issue_invoice(ctx["invoice"]["id"], FIN))
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: retainers and the support SLA
# ---------------------------------------------------------------------------
def setup_retainer(
    engagement_overrides=None,
    sla_tier="GOLD",
    monthly_fee=4000.00,
    start_date="2026-05-01",
    end_date="2026-07-31",
    included_hours=10,
) -> dict:
    """Client + ACTIVE engagement + one maintenance retainer."""
    overrides = dict(engagement_overrides or {})
    overrides.setdefault("billing_model", "FIXED")
    overrides.setdefault("contract_value", 50000.00)
    overrides.setdefault("budget_hours_cap", 200)
    ctx = setup_active_engagement(**overrides)
    ctx["retainer"] = get_success_data(
        api_client.create_retainer(
            F.create_retainer_payload(
                client_id=ctx["client"]["id"],
                engagement_id=ctx["engagement"]["id"],
                start_date=start_date,
                end_date=end_date,
                monthly_fee=monthly_fee,
                included_hours=included_hours,
                sla_tier=sla_tier,
            ),
            AM,
        )
    )
    return ctx


def open_incident(ctx: dict, severity="SEV1", summary="Checkout returns 500", opened_at=None) -> dict:
    """Raise a support incident under the context's retainer, optionally pinning
    the logical clock first so opened_at lands on a known instant."""
    if opened_at is not None:
        set_clock(opened_at)
    return get_success_data(
        api_client.create_support_incident(
            F.create_support_incident_payload(
                retainer_id=ctx["retainer"]["id"], severity=severity, summary=summary
            ),
            ctx["client_headers"],
        )
    )


def respond_incident(incident_id: str, at=None, note=None) -> dict:
    if at is not None:
        set_clock(at)
    return get_success_data(api_client.respond_incident(incident_id, ENG, note=note))


def resolve_incident(incident_id: str, at=None, resolution_note="Fixed") -> dict:
    if at is not None:
        set_clock(at)
    return get_success_data(api_client.resolve_incident(incident_id, resolution_note, ENG))


def setup_resolved_incident(
    severity="SEV1",
    sla_tier="GOLD",
    monthly_fee=4000.00,
    opened_at="2026-05-01T16:00:00Z",
    responded_at="2026-05-04T10:00:00Z",
    resolved_at="2026-05-04T10:30:00Z",
) -> dict:
    """Retainer + an incident walked OPEN -> RESPONDED -> RESOLVED on a pinned
    clock, so both SLA durations and the resulting credit are deterministic.

    Returns the retainer context plus "incident" (the resolved incident).
    """
    ctx = setup_retainer(sla_tier=sla_tier, monthly_fee=monthly_fee)
    incident = open_incident(ctx, severity=severity, opened_at=opened_at)
    respond_incident(incident["id"], at=responded_at)
    ctx["incident"] = resolve_incident(incident["id"], at=resolved_at)
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: invoices
# ---------------------------------------------------------------------------
def create_invoice(engagement_id: str, kind: str, **overrides) -> dict:
    version = overrides.pop("expected_engagement_version", None)
    if version is None:
        version = engagement_version(engagement_id, FIN)
    payload = F.create_invoice_payload(
        engagement_id=engagement_id,
        kind=kind,
        expected_engagement_version=version,
        **overrides,
    )
    return get_success_data(api_client.create_invoice(payload, FIN))
