"""Inspections and findings: acceptance preconditions, enum validation, and
the open-critical-findings counter under resolve/reopen."""
from test_helpers import (
    ApiErrorId,
    create_finding,
    create_inspection,
    create_site,
    setup_inspection_with_finding,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

ENGINEER = TEST_USERS["compliance_engineer_headers"]
MANAGER = TEST_USERS["compliance_manager_headers"]
INSPECTOR = TEST_USERS["inspector_user_headers"]


def test_accept_blocked_until_findings_terminal(api):
    """PRD §3.7: "Acceptance (`SUBMITTED → ACCEPTED`) requires that every
    finding on the inspection is in `VERIFIED` or `WITHDRAWN` status; any
    other finding state blocks acceptance."
    PRD §2.10: "**State-machine validity**: the target resource's current state
    allows the requested transition (else `ERR_INVALID_STATE`)."

    Design: Corner/state_machines/inspection_accept_requires_all_findings_terminal
    """
    site = create_site(insurer_id="FM-1")
    inspection = create_inspection(site["id"])
    create_finding(site["id"], inspection["id"], severity="MINOR")
    validate_success(api.submit_inspection(site["id"], inspection["id"],
                                           INSPECTOR), 200)

    res = api.accept_inspection(site["id"], inspection["id"], MANAGER)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    after = validate_success(api.get_inspection(site["id"], inspection["id"],
                                                MANAGER), 200)
    assert after["status"] == "SUBMITTED"


def test_invalid_finding_severity_rejected(api):
    """PRD §3.7: "a `severity` of `OBSERVATION`, `MINOR`, `MAJOR`, or
    `CRITICAL`".
    PRD §2.10: "**Input shape**: required fields present, enum values within
    declared sets, numeric ranges respected."

    `SUPER_CRITICAL` is outside the declared severity set and is rejected with
    the catalogue's 400 input error `ERR_INVALID_REQUEST`.

    Design: Corner/validations/invalid_enum_returns_invalid_request
    """
    site = create_site(insurer_id="FM-1")
    inspection = create_inspection(site["id"])

    res = api.create_inspection_finding(
        site["id"], inspection["id"],
        {"severity": "SUPER_CRITICAL", "description": "f",
         "due_at": "2026-06-01T00:00:00Z"},
        INSPECTOR)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)
    assert res.status_code == 400


def test_critical_counter_decrements_on_resolve(api):
    """PRD §3.7: "When a finding of severity `CRITICAL` is created, the owning
    Site's `open_critical_findings` counter increments by 1 and the site's
    `version` increments by 1; posture is recomputed."
    PRD §3.7: "The engineer resolves it (`IN_PROGRESS → RESOLVED`); when
    severity is `CRITICAL` this decrements `open_critical_findings` by 1 and
    recomputes posture."

    Design: Difficulty/compensating_invariant/critical_finding_counter_invariant_under_resolve_and_reopen
    """
    site, inspection, finding = setup_inspection_with_finding(
        severity="CRITICAL", insurer_id="FM-1")

    initial = validate_success(api.get_site(site["id"], ENGINEER), 200)
    assert initial["open_critical_findings"] == 1

    validate_success(api.finding_start_work(site["id"], inspection["id"],
                                            finding["id"], ENGINEER), 200)
    validate_success(api.finding_resolve(site["id"], inspection["id"],
                                         finding["id"], ENGINEER), 200)

    mid = validate_success(api.get_site(site["id"], ENGINEER), 200)
    assert mid["open_critical_findings"] == 0


def test_critical_counter_restored_on_reopen(api):
    """PRD §3.7: "The engineer resolves it (`IN_PROGRESS → RESOLVED`); when
    severity is `CRITICAL` this decrements `open_critical_findings` by 1 and
    recomputes posture."
    PRD §3.7: "The manager may instead reopen the finding (`RESOLVED →
    REOPENED`); for a `CRITICAL` finding this increments
    `open_critical_findings` by 1 and recomputes posture."

    The (resolve, reopen) pair conserves the counter: final == initial.

    Design: Difficulty/compensating_invariant/critical_finding_counter_invariant_under_resolve_and_reopen
    """
    site, inspection, finding = setup_inspection_with_finding(
        severity="CRITICAL", insurer_id="FM-1")

    initial = validate_success(api.get_site(site["id"], ENGINEER), 200)
    assert initial["open_critical_findings"] == 1

    validate_success(api.finding_start_work(site["id"], inspection["id"],
                                            finding["id"], ENGINEER), 200)
    validate_success(api.finding_resolve(site["id"], inspection["id"],
                                         finding["id"], ENGINEER), 200)
    mid = validate_success(api.get_site(site["id"], ENGINEER), 200)
    assert mid["open_critical_findings"] == 0

    validate_success(api.finding_reopen(site["id"], inspection["id"],
                                        finding["id"], MANAGER), 200)
    final = validate_success(api.get_site(site["id"], ENGINEER), 200)
    assert final["open_critical_findings"] == 1
    assert final["open_critical_findings"] == initial["open_critical_findings"]
