"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only — each test starts against an empty database whose logical clock
reads its startup value of 2026-08-01T00:00:00Z.

Helpers use the lenient `get_success_data()` validator so a broken precondition
surfaces as a setup failure rather than as a confusing assertion failure.
"""

import uuid

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_STARTUP_UTC,
    TEST_DEFAULTS,
    add_business_days,
    add_calendar_days,
    roll_forward_to_business_day,
)
from .factories import (
    annual_report_cycle_payload,
    bond_issue_payload,
    content_requirement_payload,
    defease_payload,
    direct_placement_payload,
    engagement_payload,
    filing_payload,
    material_event_notice_payload,
    official_statement_payload,
    rating_action_payload,
    undertaking_payload,
)
from .test_users import (
    OFFICER_ASSEMBLER_ID,
    OFFICER_PREPARER_ID,
    REVIEWER_ONE_ID,
    REVIEWER_TWO_ID,
    TEST_USERS,
    make_agent_headers,
    make_officer_headers,
    make_reviewer_headers,
)

FD = TEST_USERS["finance_director_headers"]
OFFICER = TEST_USERS["disclosure_officer_headers"]
ASSEMBLER = TEST_USERS["assembler_officer_headers"]
REVIEWER = TEST_USERS["compliance_reviewer_headers"]
SECOND_REVIEWER = TEST_USERS["second_reviewer_headers"]


def unique_receipt_id(prefix: str = "MSRB") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12].upper()}"


# --------------------------------------------------------------------------- #
# Logical clock (PRD §2.5)
# --------------------------------------------------------------------------- #

def set_clock(current_utc: str) -> dict:
    """Move the server's logical clock. Writes no entity row and runs no sweep."""
    return get_success_data(api_client.set_clock({"current_utc": current_utc}, FD))


def set_clock_date(day: str, time_part: str = "T00:00:00Z") -> dict:
    return set_clock(f"{day}{time_part}")


def reset_clock() -> dict:
    return set_clock(CLOCK_STARTUP_UTC)


def run_sweep() -> dict:
    """Invoke the dated calendar sweep and return its summary object."""
    return get_success_data(api_client.run_calendar_sweep(FD))


# --------------------------------------------------------------------------- #
# Tier 1 — single-entity creation and reads
# --------------------------------------------------------------------------- #

def create_bond_issue(**overrides) -> dict:
    return get_success_data(api_client.create_bond_issue(bond_issue_payload(**overrides), FD))


def read_bond_issue(issue_id: str) -> dict:
    return get_success_data(api_client.get_bond_issue(issue_id, FD))


def issue_version(issue_id: str) -> int:
    return read_bond_issue(issue_id)["version"]


def create_undertaking(issue_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_undertaking(undertaking_payload(issue_id, **overrides), FD)
    )


def read_undertaking(undertaking_id: str) -> dict:
    return get_success_data(api_client.get_undertaking(undertaking_id, FD))


def undertaking_version(undertaking_id: str) -> int:
    return read_undertaking(undertaking_id)["version"]


def suspend_undertaking(undertaking_id: str, suspended_reason: str = "Pending legal opinion") -> dict:
    return get_success_data(
        api_client.suspend_undertaking(undertaking_id, {"suspended_reason": suspended_reason}, FD)
    )


def reinstate_undertaking(undertaking_id: str) -> dict:
    return get_success_data(api_client.reinstate_undertaking(undertaking_id, FD))


def create_content_requirement(undertaking_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_content_requirement(
            content_requirement_payload(undertaking_id, **overrides), OFFICER
        )
    )


def create_cycle(undertaking_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_annual_report_cycle(
            annual_report_cycle_payload(undertaking_id, **overrides), OFFICER
        )
    )


def read_cycle(cycle_id: str) -> dict:
    return get_success_data(api_client.get_annual_report_cycle(cycle_id, FD))


def read_content_item(item_id: str) -> dict:
    return get_success_data(api_client.get_content_item(item_id, FD))


def list_content_items(cycle_id: str, **filters) -> list:
    params = {"cycle_id": cycle_id, "limit": 100}
    params.update(filters)
    return get_success_data(api_client.list_content_items(FD, params=params))


def list_failure_events(**filters) -> list:
    params = {"limit": 100}
    params.update(filters)
    return get_success_data(api_client.list_failure_events(FD, params=params))


def read_failure_event(event_id: str) -> dict:
    return get_success_data(api_client.get_failure_event(event_id, FD))


def read_filing(filing_id: str) -> dict:
    return get_success_data(api_client.get_filing(filing_id, FD))


def read_notice(notice_id: str) -> dict:
    return get_success_data(api_client.get_material_event_notice(notice_id, FD))


def read_placement(placement_id: str) -> dict:
    return get_success_data(api_client.get_direct_placement(placement_id, FD))


def read_official_statement(statement_id: str) -> dict:
    return get_success_data(api_client.get_official_statement(statement_id, FD))


def read_engagement(engagement_id: str) -> dict:
    return get_success_data(api_client.get_engagement(engagement_id, FD))


# --------------------------------------------------------------------------- #
# Tier 2 — content requirements and cycle content
# --------------------------------------------------------------------------- #

# A single requirement whose weight closes at exactly 10000 basis points and
# which needs no audit opinion, so a cycle built on it can reach READY without
# any opinion multiplier penalty.
SIMPLE_REQUIREMENT_SPECS = [
    {"kind": "OPERATING_DATA_TABLE", "label": "Operating Data Tables", "weight_bp": 10000},
]

# Two requirements, one of which demands an audit opinion.
AUDIT_AND_DATA_REQUIREMENT_SPECS = [
    {"kind": "AUDITED_FINANCIALS", "label": "Audited Financial Statements", "weight_bp": 6000},
    {"kind": "OPERATING_DATA_TABLE", "label": "Operating Data Tables", "weight_bp": 4000},
]

# One waivable requirement plus one that is not waivable.
WAIVABLE_MIX_REQUIREMENT_SPECS = [
    {
        "kind": "OPERATING_DATA_TABLE",
        "label": "Operating Data Tables",
        "weight_bp": 5000,
        "waivable": False,
    },
    {
        "kind": "ENTERPRISE_STATISTICS",
        "label": "Enterprise Statistics",
        "weight_bp": 5000,
        "waivable": True,
    },
]


def create_requirements(undertaking_id: str, specs=None) -> list:
    """Declare one ContentRequirement per spec, in list order."""
    specs = SIMPLE_REQUIREMENT_SPECS if specs is None else specs
    return [create_content_requirement(undertaking_id, **spec) for spec in specs]


def setup_issue_with_undertaking(issue=None, undertaking=None) -> dict:
    """An OUTSTANDING issue with one ACTIVE undertaking and no content declared."""
    issue_row = create_bond_issue(**(issue or {}))
    undertaking_row = create_undertaking(issue_row["id"], **(undertaking or {}))
    return {"issue": issue_row, "undertaking": undertaking_row}


def setup_undertaking_with_requirements(specs=None, issue=None, undertaking=None) -> dict:
    """An undertaking whose content_weight_bp_total closes at 10000 basis points."""
    context = setup_issue_with_undertaking(issue=issue, undertaking=undertaking)
    context["requirements"] = create_requirements(context["undertaking"]["id"], specs)
    return context


def setup_cycle(specs=None, issue=None, undertaking=None, cycle=None) -> dict:
    """A DRAFTING cycle whose content items have just been snapshotted."""
    context = setup_undertaking_with_requirements(
        specs=specs, issue=issue, undertaking=undertaking
    )
    context["cycle"] = create_cycle(context["undertaking"]["id"], **(cycle or {}))
    context["items"] = list_content_items(context["cycle"]["id"])
    return context


def item_for_requirement(items, requirement_id: str) -> dict:
    for item in items:
        if item["content_requirement_id"] == requirement_id:
            return item
    raise AssertionError(f"No content item snapshotted for requirement {requirement_id}")


def item_of_kind(items, requirements, kind: str) -> dict:
    """Find the snapshotted item whose source requirement carries `kind`."""
    for requirement in requirements:
        if requirement["kind"] == kind:
            return item_for_requirement(items, requirement["id"])
    raise AssertionError(f"No requirement of kind {kind} in this undertaking")


def prepare_item(item_id: str, user_id: str = OFFICER_PREPARER_ID, **fields) -> dict:
    """Record preparation progress; defaults supply both readiness fields."""
    payload = {
        "source_document_ref": "DOC-CAFR-2026",
        "data_as_of_date": "2026-06-30",
    }
    payload.update(fields)
    return get_success_data(
        api_client.update_content_item(item_id, payload, make_officer_headers(user_id))
    )


def attest_item(item_id: str, user_id: str = OFFICER_PREPARER_ID) -> dict:
    return get_success_data(
        api_client.attest_content_item(item_id, make_officer_headers(user_id))
    )


def reopen_item(item_id: str, user_id: str = OFFICER_PREPARER_ID) -> dict:
    return get_success_data(
        api_client.reopen_content_item(item_id, make_officer_headers(user_id))
    )


def waive_item(item_id: str, waiver_reason: str = "Not applicable for this period") -> dict:
    return get_success_data(
        api_client.waive_content_item(item_id, {"waiver_reason": waiver_reason}, REVIEWER)
    )


def ready_item(item_id: str, requirement: dict = None, user_id: str = OFFICER_PREPARER_ID) -> dict:
    """Drive one item from NOT_STARTED all the way to READY."""
    fields = {}
    if requirement is not None and requirement.get("requires_audit_opinion"):
        fields["audit_opinion_type"] = "UNMODIFIED"
    prepare_item(item_id, user_id=user_id, **fields)
    return attest_item(item_id, user_id=user_id)


def assemble(cycle_id: str, user_id: str = OFFICER_ASSEMBLER_ID) -> dict:
    return get_success_data(
        api_client.assemble_cycle(cycle_id, make_officer_headers(user_id))
    )


def withdraw(cycle_id: str, withdrawal_reason: str = "Opened in error") -> dict:
    return get_success_data(
        api_client.withdraw_cycle(cycle_id, {"withdrawal_reason": withdrawal_reason}, OFFICER)
    )


def setup_ready_to_file_cycle(specs=None, issue=None, undertaking=None, cycle=None) -> dict:
    """Every item READY (attested by the preparer) and the cycle assembled by a
    second officer, so the cycle sits in READY_TO_FILE."""
    context = setup_cycle(specs=specs, issue=issue, undertaking=undertaking, cycle=cycle)
    requirements_by_id = {r["id"]: r for r in context["requirements"]}
    for item in context["items"]:
        ready_item(item["id"], requirements_by_id.get(item["content_requirement_id"]))
    context["cycle"] = assemble(context["cycle"]["id"])
    context["items"] = list_content_items(context["cycle"]["id"])
    return context


# --------------------------------------------------------------------------- #
# Tier 2 — dissemination engagements (PRD §3.10)
# --------------------------------------------------------------------------- #

def create_engagement(undertaking_id: str, expected_undertaking_version=None, **overrides) -> dict:
    """Open an engagement, reading the undertaking's current version when the
    caller does not want to pin one deliberately."""
    if expected_undertaking_version is None:
        expected_undertaking_version = undertaking_version(undertaking_id)
    return get_success_data(
        api_client.create_engagement(
            engagement_payload(undertaking_id, expected_undertaking_version, **overrides), FD
        )
    )


def acknowledge_calendar(engagement_id: str, last_calendar_ack_date: str) -> dict:
    return get_success_data(
        api_client.acknowledge_calendar(
            engagement_id,
            {"last_calendar_ack_date": last_calendar_ack_date},
            make_agent_headers(engagement_id),
        )
    )


def terminate_engagement(engagement_id: str) -> dict:
    return get_success_data(api_client.terminate_engagement(engagement_id, FD))


def setup_engagement_for_undertaking(undertaking_id: str, **overrides) -> dict:
    return create_engagement(undertaking_id, **overrides)


def setup_cycle_with_engagement(specs=None, issue=None, undertaking=None, cycle=None,
                                engagement=None) -> dict:
    """A READY_TO_FILE cycle plus an ACTIVE engagement able to submit for it."""
    context = setup_ready_to_file_cycle(
        specs=specs, issue=issue, undertaking=undertaking, cycle=cycle
    )
    context["engagement"] = create_engagement(
        context["undertaking"]["id"], **(engagement or {})
    )
    return context


# --------------------------------------------------------------------------- #
# Tier 2 — filings (PRD §3.7)
# --------------------------------------------------------------------------- #

def create_filing(issue_id: str, filing_type: str, expected_issue_version=None, **overrides) -> dict:
    if expected_issue_version is None:
        expected_issue_version = issue_version(issue_id)
    return get_success_data(
        api_client.create_filing(
            filing_payload(issue_id, filing_type, expected_issue_version, **overrides), OFFICER
        )
    )


def create_annual_report_filing(issue_id: str, cycle_id: str, **overrides) -> dict:
    return create_filing(issue_id, "ANNUAL_REPORT", cycle_id=cycle_id, **overrides)


def create_failure_notice_filing(issue_id: str, cycle_id: str, **overrides) -> dict:
    return create_filing(issue_id, "FAILURE_TO_FILE_NOTICE", cycle_id=cycle_id, **overrides)


def create_event_filing(issue_id: str, material_event_id: str, **overrides) -> dict:
    return create_filing(
        issue_id, "MATERIAL_EVENT_NOTICE", material_event_id=material_event_id, **overrides
    )


def create_placement_filing(issue_id: str, direct_placement_id: str, **overrides) -> dict:
    return create_filing(
        issue_id,
        "VOLUNTARY_FINANCIAL_OBLIGATION",
        direct_placement_id=direct_placement_id,
        **overrides,
    )


def submit(filing_id: str, engagement_id: str) -> dict:
    return get_success_data(
        api_client.submit_filing(filing_id, make_agent_headers(engagement_id))
    )


def reject(filing_id: str, engagement_id: str, rejection_reason: str = "Malformed attachment") -> dict:
    return get_success_data(
        api_client.reject_filing(
            filing_id, {"rejection_reason": rejection_reason}, make_agent_headers(engagement_id)
        )
    )


def resubmit(filing_id: str, engagement_id: str, correction_reason: str = "Attachment repaired") -> dict:
    return get_success_data(
        api_client.resubmit_filing(
            filing_id, {"correction_reason": correction_reason}, make_agent_headers(engagement_id)
        )
    )


def confirm(filing_id: str, engagement_id: str, repository_receipt_id: str = None) -> dict:
    receipt = repository_receipt_id or unique_receipt_id()
    return get_success_data(
        api_client.confirm_filing(
            filing_id, {"repository_receipt_id": receipt}, make_agent_headers(engagement_id)
        )
    )


def submit_and_confirm(filing_id: str, engagement_id: str, repository_receipt_id: str = None) -> dict:
    submit(filing_id, engagement_id)
    return confirm(filing_id, engagement_id, repository_receipt_id)


def file_annual_report(context: dict, receipt_id: str = None) -> dict:
    """Draft, submit and confirm the ANNUAL_REPORT filing for a READY_TO_FILE cycle.

    `context` must carry `issue`, `cycle` and `engagement`.  Returns the confirmed
    filing row and leaves the caller free to re-read the cycle.
    """
    filing = create_annual_report_filing(context["issue"]["id"], context["cycle"]["id"])
    return submit_and_confirm(filing["id"], context["engagement"]["id"], receipt_id)


def remediate_event(event_id: str, remediation_filing_id: str,
                    remediation_note: str = "Late annual report filed and confirmed") -> dict:
    return get_success_data(
        api_client.remediate_failure_event(
            event_id,
            {
                "remediation_filing_id": remediation_filing_id,
                "remediation_note": remediation_note,
            },
            OFFICER,
        )
    )


# --------------------------------------------------------------------------- #
# Tier 2 — listed events, ratings, defeasance (PRD §3.1, §3.5)
# --------------------------------------------------------------------------- #

def create_notice(issue_id: str, event_type: str = "TRUSTEE_SUBSTITUTION",
                  occurrence_date: str = None, **overrides) -> dict:
    payload_overrides = dict(overrides)
    payload_overrides["event_type"] = event_type
    if occurrence_date is not None:
        payload_overrides["occurrence_date"] = occurrence_date
    return get_success_data(
        api_client.create_material_event_notice(
            material_event_notice_payload(issue_id, **payload_overrides), OFFICER
        )
    )


def determine_notice(notice_id: str, determination: str = "MATERIAL",
                     determination_note: str = None, user_id: str = REVIEWER_ONE_ID) -> dict:
    payload = {"determination": determination}
    if determination_note is not None:
        payload["determination_note"] = determination_note
    return get_success_data(
        api_client.determine_material_event_notice(
            notice_id, payload, make_reviewer_headers(user_id)
        )
    )


def setup_material_notice(issue=None, event_type: str = "TRUSTEE_SUBSTITUTION",
                          occurrence_date: str = None, **overrides) -> dict:
    """An issue with an undertaking and one notice already determined MATERIAL."""
    context = setup_issue_with_undertaking(issue=issue)
    notice = create_notice(
        context["issue"]["id"], event_type=event_type, occurrence_date=occurrence_date, **overrides
    )
    context["notice"] = determine_notice(notice["id"], "MATERIAL")
    return context


def record_rating_action(issue_id: str, expected_issue_version=None, **overrides) -> dict:
    if expected_issue_version is None:
        expected_issue_version = issue_version(issue_id)
    return get_success_data(
        api_client.create_rating_action(
            issue_id, rating_action_payload(expected_issue_version, **overrides), FD
        )
    )


def defease_issue(issue_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.defease_bond_issue(issue_id, defease_payload(**overrides), FD)
    )


# --------------------------------------------------------------------------- #
# Tier 2 — direct placements (PRD §3.6)
# --------------------------------------------------------------------------- #

def create_placement(issue_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_direct_placement(direct_placement_payload(issue_id, **overrides), OFFICER)
    )


def classify_placement(placement_id: str, waiver_reason: str = None,
                       user_id: str = REVIEWER_ONE_ID) -> dict:
    payload = {"waiver_reason": waiver_reason} if waiver_reason is not None else None
    return get_success_data(
        api_client.classify_direct_placement(
            placement_id, make_reviewer_headers(user_id), payload
        )
    )


# --------------------------------------------------------------------------- #
# Tier 2 — official statements (PRD §3.9)
# --------------------------------------------------------------------------- #

def create_official_statement(issue_id: str, dated_date: str = None, **overrides) -> dict:
    payload_overrides = dict(overrides)
    if dated_date is not None:
        payload_overrides["dated_date"] = dated_date
    return get_success_data(
        api_client.create_official_statement(
            official_statement_payload(issue_id, **payload_overrides), OFFICER
        )
    )


def review_official_statement(statement_id: str, disclosed_event_ids=None,
                              lookback_policy: str = None,
                              user_id: str = REVIEWER_ONE_ID) -> dict:
    payload = {}
    if disclosed_event_ids is not None:
        payload["disclosed_event_ids"] = disclosed_event_ids
    if lookback_policy is not None:
        payload["lookback_policy"] = lookback_policy
    return get_success_data(
        api_client.review_official_statement(
            statement_id, make_reviewer_headers(user_id), payload or None
        )
    )


def post_official_statement(statement_id: str, user_id: str = REVIEWER_TWO_ID) -> dict:
    return get_success_data(
        api_client.post_official_statement(statement_id, make_reviewer_headers(user_id))
    )


# --------------------------------------------------------------------------- #
# List wrappers (cascade-created rows are discoverable only this way, PRD §2.12)
# --------------------------------------------------------------------------- #

def _list(method, params) -> list:
    merged = {"limit": 100}
    merged.update({k: v for k, v in params.items() if v is not None})
    return get_success_data(method(FD, params=merged))


def list_bond_issues(**filters) -> list:
    return _list(api_client.list_bond_issues, filters)


def list_undertakings(**filters) -> list:
    return _list(api_client.list_undertakings, filters)


def list_requirements(undertaking_id: str = None, **filters) -> list:
    return _list(api_client.list_content_requirements, dict(undertaking_id=undertaking_id, **filters))


def list_cycles(undertaking_id: str = None, **filters) -> list:
    return _list(api_client.list_annual_report_cycles, dict(undertaking_id=undertaking_id, **filters))


def list_notices(issue_id: str = None, **filters) -> list:
    return _list(api_client.list_material_event_notices, dict(issue_id=issue_id, **filters))


def list_filings(**filters) -> list:
    return _list(api_client.list_filings, filters)


def list_placements(issue_id: str = None, **filters) -> list:
    return _list(api_client.list_direct_placements, dict(issue_id=issue_id, **filters))


def list_official_statements(**filters) -> list:
    return _list(api_client.list_official_statements, filters)


def list_engagements(undertaking_id: str = None, **filters) -> list:
    return _list(api_client.list_engagements, dict(undertaking_id=undertaking_id, **filters))


def failure_events_for_cycle(cycle_id: str) -> list:
    return [e for e in list_failure_events() if e.get("cycle_id") == cycle_id]


def failure_events_for_notice(notice_id: str) -> list:
    return [e for e in list_failure_events() if e.get("material_event_id") == notice_id]


def sole_failure_event_for_cycle(cycle_id: str) -> dict:
    events = failure_events_for_cycle(cycle_id)
    assert len(events) == 1, f"Expected exactly one failure event for cycle {cycle_id}, got {len(events)}"
    return events[0]


def sole_failure_event_for_notice(notice_id: str) -> dict:
    events = failure_events_for_notice(notice_id)
    assert len(events) == 1, f"Expected exactly one failure event for notice {notice_id}, got {len(events)}"
    return events[0]


# --------------------------------------------------------------------------- #
# Tier 3 — sweep-driven states (PRD §3.11)
# --------------------------------------------------------------------------- #

def setup_delinquent_cycle(specs=None, filing_window_days: int = 1,
                           period_start_date: str = "2025-07-01",
                           period_end_date: str = "2026-07-01",
                           clock: str = None, issue=None) -> dict:
    """A cycle whose due_date has already passed, swept into DELINQUENT.

    With `filing_window_days` of 1 and a period ending 2026-07-01 the due date is
    2026-07-02, a business day, which lies before the clock's startup date of
    2026-08-01 — so a single sweep strands the cycle.
    """
    context = setup_cycle(
        specs=specs,
        issue=issue,
        undertaking={"filing_window_days": filing_window_days},
        cycle={"period_start_date": period_start_date, "period_end_date": period_end_date},
    )
    if clock is not None:
        set_clock(clock)
    context["sweep"] = run_sweep()
    context["cycle"] = read_cycle(context["cycle"]["id"])
    context["items"] = list_content_items(context["cycle"]["id"])
    context["undertaking"] = read_undertaking(context["undertaking"]["id"])
    context["failure_event"] = sole_failure_event_for_cycle(context["cycle"]["id"])
    return context


def setup_missed_notice(event_type: str = "TRUSTEE_SUBSTITUTION",
                        occurrence_date: str = None, issue=None) -> dict:
    """A MATERIAL notice whose ten-business-day window has lapsed and been swept."""
    context = setup_material_notice(issue=issue, event_type=event_type,
                                    occurrence_date=occurrence_date)
    deadline = context["notice"]["filing_deadline_date"]
    set_clock(f"{add_calendar_days(deadline, 1)}T00:00:00Z")
    context["sweep"] = run_sweep()
    context["notice"] = read_notice(context["notice"]["id"])
    context["undertaking"] = read_undertaking(context["undertaking"]["id"])
    context["failure_event"] = sole_failure_event_for_notice(context["notice"]["id"])
    return context


def setup_missed_events(count: int, issue=None) -> dict:
    """`count` distinct MATERIAL notices on one issue, all swept to MISSED.

    Each notice carries a different `event_type`, so the duplicate-notice guard of
    §3.5 never fires, and all of them share the one deadline computed from the
    common occurrence date.
    """
    event_types = [
        "TRUSTEE_SUBSTITUTION",
        "UNSCHEDULED_DRAW_ON_RESERVE",
        "MERGER_OR_SALE",
        "PRINCIPAL_PAYMENT_DELINQUENCY",
        "BOND_CALL",
    ]
    assert count <= len(event_types), "at most five distinct listed events are available"
    context = setup_issue_with_undertaking(issue=issue)
    notices = []
    for event_type in event_types[:count]:
        notice = create_notice(context["issue"]["id"], event_type=event_type)
        notices.append(determine_notice(notice["id"], "MATERIAL"))
    deadline = max(n["filing_deadline_date"] for n in notices)
    set_clock(f"{add_calendar_days(deadline, 1)}T00:00:00Z")
    context["sweep"] = run_sweep()
    context["notices"] = [read_notice(n["id"]) for n in notices]
    context["undertaking"] = read_undertaking(context["undertaking"]["id"])
    return context


def setup_filed_annual_report(timeliness_basis: str = None, submit_clock: str = None,
                              confirm_clock: str = None, specs=None, issue=None,
                              undertaking=None, cycle=None, engagement=None,
                              receipt_id: str = None) -> dict:
    """Drive one annual report all the way to a confirmed filing.

    `submit_clock` and `confirm_clock` are optional logical-clock instants applied
    immediately before the submission and the confirmation respectively, which is
    how a caller places the basis instant on either side of the cycle's `due_date`.
    """
    undertaking_overrides = dict(undertaking or {})
    if timeliness_basis is not None:
        undertaking_overrides["timeliness_basis"] = timeliness_basis
    context = setup_cycle_with_engagement(
        specs=specs, issue=issue, undertaking=undertaking_overrides, cycle=cycle,
        engagement=engagement,
    )
    filing = create_annual_report_filing(context["issue"]["id"], context["cycle"]["id"])
    if submit_clock is not None:
        set_clock(submit_clock)
    submit(filing["id"], context["engagement"]["id"])
    if confirm_clock is not None:
        set_clock(confirm_clock)
    context["filing"] = confirm(filing["id"], context["engagement"]["id"], receipt_id)
    context["cycle"] = read_cycle(context["cycle"]["id"])
    context["undertaking"] = read_undertaking(context["undertaking"]["id"])
    context["engagement"] = read_engagement(context["engagement"]["id"])
    return context


def setup_late_annual_report(timeliness_basis: str = None, filing_window_days: int = 1,
                             period_start_date: str = "2025-07-01",
                             period_end_date: str = "2026-07-01", **kwargs) -> dict:
    """A confirmed annual report whose basis instant falls after the due date.

    The due date lands on 2026-07-02 while the clock still reads its startup date
    of 2026-08-01, so the cycle reaches `FILED_LATE` and mints an
    `ANNUAL_REPORT_LATE` failure event.
    """
    context = setup_filed_annual_report(
        timeliness_basis=timeliness_basis,
        undertaking={"filing_window_days": filing_window_days},
        cycle={"period_start_date": period_start_date, "period_end_date": period_end_date},
        **kwargs,
    )
    context["failure_event"] = sole_failure_event_for_cycle(context["cycle"]["id"])
    return context
