"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly started server). Setup calls use
the lenient get_success_data() validator so setup failures produce clear
"Setup step failed" errors instead of confusing assertion failures.

Lookups that the design recipes express as filtered-list captures are resolved
by listing and matching on PRD-named identity fields (custodian_id,
challenger_rule_id, record_id), so fixtures never depend on server-side
query-filter behavior.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    JUSTIFICATION_20,
    RELEASE_REASON_10,
    STANDARD_WINDOW_START,
)
from .factories import (
    create_custodian_payload,
    create_disposition_request_payload,
    create_freeze_window_payload,
    create_hold_audit_payload,
    create_jurisdiction_payload,
    create_legal_hold_payload,
    create_program_payload,
    create_record_class_payload,
    create_record_payload,
    create_retention_rule_payload,
    release_hold_payload,
)
from .test_users import (
    TEST_USERS,
    make_custodian_headers,
    make_legal_counsel_headers,
    make_records_manager_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
RM = TEST_USERS["records_manager_headers"]
LC = TEST_USERS["legal_counsel_headers"]
AUD = TEST_USERS["auditor_headers"]

DEFAULT_REQUESTER = "rm-1"
DEFAULT_APPROVER = "lc-1"


# ─── Tier 1: single-entity creation ──────────────────────────────────

def set_clock(to_iso8601: str) -> dict:
    """Advance the server logical clock (PlatformAdmin capability)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_program(name="Program", fiscal_year_end_month=12,
                   fiscal_year_end_day=31, **overrides) -> dict:
    return get_success_data(api_client.create_program(
        create_program_payload(name=name, fiscal_year_end_month=fiscal_year_end_month,
                               fiscal_year_end_day=fiscal_year_end_day, **overrides),
        ADMIN))


def add_record_class(program_id, code="GEN", name="General", rate=10) -> dict:
    return get_success_data(api_client.create_record_class(
        create_record_class_payload(program_id, code=code, name=name,
                                    monthly_storage_cost_cents_per_gb=rate),
        ADMIN))


def add_jurisdiction(program_id, code="US-FED", name="Federal") -> dict:
    return get_success_data(api_client.create_jurisdiction(
        create_jurisdiction_payload(program_id, code=code, name=name), ADMIN))


def register_custodian(program_id, email="c@x.com", full_name="Cust",
                       department="Legal") -> dict:
    return get_success_data(api_client.create_custodian(
        create_custodian_payload(program_id, email=email, full_name=full_name,
                                 department=department),
        RM))


def author_rule(program_id, record_class_id, jurisdiction_id, rule_code="R-1M",
                retention_months=1, trigger_basis="EVENT_DATE",
                effective_from=STANDARD_WINDOW_START, effective_to=None) -> dict:
    """Author a retention rule (born DRAFT)."""
    return get_success_data(api_client.create_retention_rule(
        create_retention_rule_payload(
            program_id, record_class_id, jurisdiction_id, rule_code=rule_code,
            retention_months=retention_months, trigger_basis=trigger_basis,
            effective_from=effective_from, effective_to=effective_to),
        RM))


def activate_rule(rule_id) -> dict:
    """Activate a DRAFT rule; returns the rule (ACTIVE or PENDING_CONFLICT)."""
    return get_success_data(api_client.activate_retention_rule(rule_id, RM))


def author_active_rule(program_id, record_class_id, jurisdiction_id, **kwargs) -> dict:
    rule = author_rule(program_id, record_class_id, jurisdiction_id, **kwargs)
    activated = activate_rule(rule["id"])
    assert activated["status"] == "ACTIVE", (
        f"Setup failed: rule {rule['rule_code']} did not activate cleanly "
        f"(status {activated['status']})"
    )
    return activated


def register_record(program_id, record_class_id, jurisdiction_id, title="R",
                    event_date="2026-06-01T00:00:00Z", size_gb=1,
                    auto_delete_enabled=None, source_system="ERP") -> dict:
    return get_success_data(api_client.create_record(
        create_record_payload(program_id, record_class_id, jurisdiction_id,
                              title=title, source_system=source_system,
                              event_date=event_date, size_gb=size_gb,
                              auto_delete_enabled=auto_delete_enabled),
        RM))


def create_hold(program_id, matter_ref, custodian_ids, record_ids,
                title="Hold", reason="Case") -> dict:
    return get_success_data(api_client.create_legal_hold(
        create_legal_hold_payload(program_id, matter_ref, custodian_ids, record_ids,
                                  title=title, reason=reason),
        LC))


def issue_hold(hold_id) -> dict:
    return get_success_data(api_client.issue_legal_hold(hold_id, LC))


def expand_scope(hold_id, record_ids) -> list:
    """Expand an ISSUED (or DRAFT) hold's scope; returns the created items."""
    return get_success_data(api_client.add_scope_items(
        hold_id, {"record_ids": record_ids}, LC))


def acknowledge_assignment(assignment_id, custodian_id) -> dict:
    """Custodian acknowledges their own assignment (identity-threaded)."""
    return get_success_data(api_client.acknowledge_hold_custodian(
        assignment_id, make_custodian_headers(custodian_id)))


def read_hold_version(hold_id) -> int:
    return get_success_data(api_client.get_legal_hold(hold_id, LC))["version"]


def release_hold(hold_id, expected_version, release_reason=RELEASE_REASON_10):
    """Raw release call — tests assert on success or failure themselves."""
    return api_client.release_legal_hold(
        hold_id, release_hold_payload(release_reason=release_reason,
                                      expected_legal_hold_version=expected_version),
        LC)


def create_request(program_id, record_ids, requester_id=DEFAULT_REQUESTER,
                   method="SECURE_ERASE", justification=JUSTIFICATION_20) -> dict:
    """Create a DRAFT disposition request owned by requester_id."""
    return get_success_data(api_client.create_disposition_request(
        create_disposition_request_payload(program_id, record_ids, method=method,
                                           justification=justification),
        make_records_manager_headers(requester_id)))


def submit_request(request_id, requester_id=DEFAULT_REQUESTER) -> dict:
    return get_success_data(api_client.submit_disposition_request(
        request_id, make_records_manager_headers(requester_id)))


def approve_request(request_id, approver_id=DEFAULT_APPROVER):
    """Raw approve call (LegalCounsel) — tests assert success or failure."""
    return api_client.approve_disposition_request(
        request_id, make_legal_counsel_headers(approver_id))


def get_request(request_id) -> dict:
    return get_success_data(api_client.get_disposition_request(request_id, RM))


def get_record(record_id) -> dict:
    return get_success_data(api_client.get_record(record_id, RM))


def get_rule(rule_id) -> dict:
    return get_success_data(api_client.get_retention_rule(rule_id, RM))


def create_freeze_window(program_id, start_at, end_at, reason="Audit season") -> dict:
    return get_success_data(api_client.create_freeze_window(
        create_freeze_window_payload(program_id, start_at, end_at, reason=reason),
        ADMIN))


def open_audit(program_id) -> dict:
    return get_success_data(api_client.create_hold_audit(
        create_hold_audit_payload(program_id), AUD))


def run_reminder_sweep(program_id) -> dict:
    return get_success_data(api_client.run_reminder_sweep(program_id, RM))


def run_auto_delete_sweep(program_id, method="SECURE_ERASE", user_id=None) -> dict:
    headers = make_records_manager_headers(user_id) if user_id else RM
    return get_success_data(api_client.run_auto_delete_sweep(program_id, method, headers))


# ─── Read-side lookups (list + client-side match on named identity fields) ──

def list_all_assignments() -> list:
    return get_success_data(api_client.list_hold_custodians(LC))


def find_assignment(custodian_id, hold_id=None) -> dict:
    """The unique assignment for a custodian (optionally within one hold)."""
    matches = [
        row for row in list_all_assignments()
        if row.get("custodian_id") == custodian_id
        and (hold_id is None or row.get("hold_id") == hold_id)
    ]
    assert len(matches) == 1, (
        f"Setup failed: expected exactly one assignment for custodian "
        f"{custodian_id}, found {len(matches)}"
    )
    return matches[0]


def list_all_conflicts() -> list:
    return get_success_data(api_client.list_retention_conflicts(RM))


def find_open_conflict(challenger_rule_id) -> dict:
    matches = [
        row for row in list_all_conflicts()
        if row.get("challenger_rule_id") == challenger_rule_id
        and row.get("status") == "OPEN"
    ]
    assert len(matches) == 1, (
        f"Setup failed: expected exactly one OPEN conflict for challenger "
        f"{challenger_rule_id}, found {len(matches)}"
    )
    return matches[0]


def list_all_scope_items() -> list:
    return get_success_data(api_client.list_hold_scope_items(LC))


def find_scope_items(record_id=None, hold_id=None, status=None) -> list:
    return [
        row for row in list_all_scope_items()
        if (record_id is None or row.get("record_id") == record_id)
        and (hold_id is None or row.get("hold_id") == hold_id)
        and (status is None or row.get("status") == status)
    ]


def list_all_disposition_items() -> list:
    return get_success_data(api_client.list_disposition_items(RM))


def find_disposition_item(record_id) -> dict:
    matches = [row for row in list_all_disposition_items()
               if row.get("record_id") == record_id]
    assert len(matches) == 1, (
        f"Setup failed: expected exactly one disposition item for record "
        f"{record_id}, found {len(matches)}"
    )
    return matches[0]


def list_all_certificates() -> list:
    return get_success_data(api_client.list_destruction_certificates(AUD))


# ─── Tier 2/3: composite scenarios ────────────────────────────────────

def setup_schedule(months=1, basis="EVENT_DATE", fye_month=12, fye_day=31,
                   rate=10, rule_code="R-1M", program_overrides=None,
                   effective_from=STANDARD_WINDOW_START, effective_to=None,
                   class_code="GEN", jur_code="US-FED", program_name="P") -> dict:
    """Program + record class + jurisdiction + one ACTIVE retention rule."""
    program = create_program(name=program_name, fiscal_year_end_month=fye_month,
                             fiscal_year_end_day=fye_day, **(program_overrides or {}))
    rclass = add_record_class(program["id"], code=class_code, rate=rate)
    jur = add_jurisdiction(program["id"], code=jur_code)
    rule = author_active_rule(
        program["id"], rclass["id"], jur["id"], rule_code=rule_code,
        retention_months=months, trigger_basis=basis,
        effective_from=effective_from, effective_to=effective_to)
    return {"program": program, "record_class": rclass,
            "jurisdiction": jur, "rule": rule}


def setup_schedule_with_record(months=1, basis="EVENT_DATE",
                               event_date="2026-06-01T00:00:00Z", title="R",
                               size_gb=1, auto_delete_enabled=None, **kwargs):
    """ACTIVE-rule schedule plus one record. Returns (ctx, record)."""
    ctx = setup_schedule(months=months, basis=basis, **kwargs)
    record = register_record(ctx["program"]["id"], ctx["record_class"]["id"],
                             ctx["jurisdiction"]["id"], title=title,
                             event_date=event_date, size_gb=size_gb,
                             auto_delete_enabled=auto_delete_enabled)
    return ctx, record


def setup_submitted_request(requester_id=DEFAULT_REQUESTER, months=1,
                            event_date="2026-06-01T00:00:00Z", method="SECURE_ERASE",
                            **kwargs):
    """ELIGIBLE record + DRAFT request submitted by its requester.
    Returns (ctx, record, request)."""
    ctx, record = setup_schedule_with_record(months=months, event_date=event_date,
                                             **kwargs)
    request = create_request(ctx["program"]["id"], [record["id"]],
                             requester_id=requester_id, method=method)
    request = submit_request(request["id"], requester_id=requester_id)
    return ctx, record, request


def setup_approved_request(requester_id=DEFAULT_REQUESTER,
                           approver_id=DEFAULT_APPROVER, **kwargs):
    """Full happy path through APPROVED. Returns (ctx, record, request)."""
    ctx, record, request = setup_submitted_request(requester_id=requester_id, **kwargs)
    request = get_success_data(approve_request(request["id"], approver_id=approver_id))
    assert request["status"] == "APPROVED", "Setup failed: approve did not succeed"
    return ctx, record, request


def setup_issued_hold(custodian_count=1, record_count=1, months=120,
                      event_date="2026-01-15T00:00:00Z", program_overrides=None,
                      matter_ref="M-1", issue=True):
    """Schedule + N records + N custodians + one hold covering them all.

    Returns dict(ctx, records, custodians, hold, assignments). With issue=True
    the hold is ISSUED and every assignment is PENDING."""
    ctx = setup_schedule(months=months, program_overrides=program_overrides)
    records = [
        register_record(ctx["program"]["id"], ctx["record_class"]["id"],
                        ctx["jurisdiction"]["id"], title=f"R{i + 1}",
                        event_date=event_date, source_system="MAIL")
        for i in range(record_count)
    ]
    custodians = [
        register_custodian(ctx["program"]["id"], email=f"c{i + 1}@x.com",
                           full_name=f"Cust {i + 1}")
        for i in range(custodian_count)
    ]
    hold = create_hold(ctx["program"]["id"], matter_ref,
                       [c["id"] for c in custodians], [r["id"] for r in records])
    assignments = []
    if issue:
        hold = issue_hold(hold["id"])
        assignments = [find_assignment(c["id"], hold_id=hold["id"])
                       for c in custodians]
    return {"ctx": ctx, "records": records, "custodians": custodians,
            "hold": hold, "assignments": assignments}


def setup_open_conflict(inc_months=84, ch_months=120, inc_code="R-INC",
                        ch_code="R-CH", **kwargs):
    """ACTIVE incumbent + challenger activated into PENDING_CONFLICT.
    Returns (ctx, incumbent, challenger, conflict)."""
    ctx = setup_schedule(months=inc_months, rule_code=inc_code, **kwargs)
    challenger = author_rule(ctx["program"]["id"], ctx["record_class"]["id"],
                             ctx["jurisdiction"]["id"], rule_code=ch_code,
                             retention_months=ch_months)
    activated = activate_rule(challenger["id"])
    assert activated["status"] == "PENDING_CONFLICT", (
        f"Setup failed: challenger landed in {activated['status']}, "
        "expected PENDING_CONFLICT"
    )
    conflict = find_open_conflict(challenger["id"])
    return ctx, ctx["rule"], activated, conflict


def setup_conflict_blocking_submitted_request(requester_id=DEFAULT_REQUESTER,
                                              inc_months=1, ch_months=120):
    """ELIGIBLE record + SUBMITTED request, then a challenger activation that
    flips the record to CONFLICT_BLOCKED and stales the request.
    Returns (ctx, record, request, incumbent, challenger, conflict)."""
    ctx, record, request = setup_submitted_request(requester_id=requester_id,
                                                   months=inc_months)
    incumbent = ctx["rule"]
    challenger = author_rule(ctx["program"]["id"], ctx["record_class"]["id"],
                             ctx["jurisdiction"]["id"], rule_code="R-CH",
                             retention_months=ch_months)
    challenger = activate_rule(challenger["id"])
    assert challenger["status"] == "PENDING_CONFLICT", (
        "Setup failed: challenger did not land in PENDING_CONFLICT"
    )
    conflict = find_open_conflict(challenger["id"])
    return ctx, record, request, incumbent, challenger, conflict


def setup_submitted_request_with_issued_hold(requester_id=DEFAULT_REQUESTER):
    """ELIGIBLE record + SUBMITTED request + an ISSUED hold that covers the
    record (record now HELD, request stale_item_count 1).
    Returns (ctx, record, request, custodian, hold, assignment)."""
    ctx, record, request = setup_submitted_request(requester_id=requester_id)
    custodian = register_custodian(ctx["program"]["id"])
    hold = create_hold(ctx["program"]["id"], "M-RFR", [custodian["id"]],
                       [record["id"]])
    hold = issue_hold(hold["id"])
    assignment = find_assignment(custodian["id"], hold_id=hold["id"])
    return ctx, record, request, custodian, hold, assignment
