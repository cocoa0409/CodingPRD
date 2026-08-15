"""Repatriation and closure: the two-hop initiate cascade, OCC on initiation,
the vendor-engagement completion gate, and the fully-settled-ledger closure
gate completing the assignment lifecycle (PRD §2.5, §2.7, §3.9)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_engagement_to_under_review,
    create_and_post_record,
    create_current_projection,
    create_draft_record,
    create_engagement,
    get_assignment,
    get_assignment_version,
    initiate_repatriation_payload,
    list_chargebacks,
    mark_filed_payload,
    setup_active_assignment,
    setup_pending_review_settlement,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
PAYROLL = TEST_USERS["payroll_headers"]
FINANCE = TEST_USERS["finance_headers"]


def test_initiate_repatriation_cascades_split_suspend_and_draft_void(api, admin_headers, payroll_headers):
    """PRD §3.9: "On success the assignment moves `ACTIVE` → `REPATRIATION_PENDING`,
    its `version` increments by one, and the cascade fires in two hops: the `ACTIVE`
    payroll split transitions to `SUSPENDED`, and that suspension in turn transitions
    every `DRAFT` shadow payroll record of the assignment to `VOIDED`."

    Design: Corner/state_machines/initiate_repatriation_cascades_split_suspend_and_draft_void
    """
    ctx = setup_active_assignment()
    asg_id = ctx["assignment"]["id"]
    split_id = ctx["split"]["id"]
    september = create_and_post_record(asg_id, tax_year=2026, period_month=9,
                                       total_gross_cents=900000, per_diem_days=20,
                                       housing_receipts_cents=310000)
    october = create_draft_record(asg_id, tax_year=2026, period_month=10,
                                  total_gross_cents=900000, per_diem_days=20,
                                  housing_receipts_cents=310000)

    version = get_assignment_version(asg_id)
    updated = validate_success(api.initiate_repatriation(
        asg_id, initiate_repatriation_payload(version), ADMIN), 200)
    assert updated["status"] == "REPATRIATION_PENDING"
    assert updated["version"] == version + 1

    split = validate_success(api.get_split(split_id, admin_headers), 200)
    assert split["status"] == "SUSPENDED"

    october_after = validate_success(api.get_record(october["id"], admin_headers), 200)
    assert october_after["status"] == "VOIDED", "hop 2 voids every DRAFT record"

    september_after = validate_success(api.get_record(september["id"], admin_headers), 200)
    assert september_after["status"] == "POSTED", "POSTED records are untouched"


def test_occ_stale_version_rejected_on_repatriation_initiate(api, admin_headers):
    """PRD §3.9: "Initiating repatriation is a `MobilityAdmin` action guarded by
    optimistic concurrency: the request must carry `expected_assignment_version`
    matching the assignment's current `version`, with a mismatch rejected as
    `ERR_STALE_ASSIGNMENT_VERSION` (HTTP 412) — an extension approval or a projection
    creation landing since the client's last read is exactly the staleness this guard
    catches, because the assignment is still `ACTIVE` and the transition would
    otherwise proceed on outdated terms."

    Design: Corner/validations/occ_stale_version_rejected_on_repatriation_initiate
    """
    ctx = setup_active_assignment()
    asg_id = ctx["assignment"]["id"]
    stale_version = get_assignment_version(asg_id)
    # An unrelated projection create advances the assignment version.
    create_current_projection(asg_id)

    res = api.initiate_repatriation(
        asg_id, initiate_repatriation_payload(stale_version), ADMIN)
    validate_error(res, ApiErrorId.ERR_STALE_ASSIGNMENT_VERSION)

    mid = get_assignment(asg_id)
    assert mid["status"] == "ACTIVE", "the rejected attempt leaves the state untouched"

    retried = validate_success(api.initiate_repatriation(
        asg_id, initiate_repatriation_payload(mid["version"]), ADMIN), 200)
    assert retried["status"] == "REPATRIATION_PENDING"


def test_complete_repatriation_blocked_until_engagements_final(api, admin_headers):
    """PRD §3.9: "Completing repatriation requires every vendor engagement of the
    assignment to be `FILED` or `CLOSED` — otherwise `ERR_ENGAGEMENT_NOT_FINAL` — and
    moves the assignment `REPATRIATION_PENDING` → `REPATRIATED`, stamping
    `actual_end_date` with the current clock date and transitioning the `SUSPENDED`
    split to `TERMINATED`."
    PRD §2.5: "At startup the logical clock reads exactly 2026-08-01T00:00:00Z and
    never falls back to wall-clock time."

    Design: Corner/validations/complete_repatriation_blocked_until_engagements_final
    """
    ctx = setup_active_assignment()
    asg_id = ctx["assignment"]["id"]
    split_id = ctx["split"]["id"]
    engagement = create_engagement(asg_id, tax_year=2026)

    version = get_assignment_version(asg_id)
    validate_success(api.initiate_repatriation(
        asg_id, initiate_repatriation_payload(version), ADMIN), 200)

    # Engagement merely ENGAGED: completion is blocked.
    res = api.complete_repatriation(asg_id, ADMIN)
    validate_error(res, ApiErrorId.ERR_ENGAGEMENT_NOT_FINAL)

    # Drive the SAME engagement to FILED, then completion succeeds.
    advance_engagement_to_under_review(engagement["id"])
    validate_success(api.accept_engagement(engagement["id"], TEST_USERS["vendor_coordinator_headers"]), 200)
    validate_success(api.mark_filed(
        engagement["id"], mark_filed_payload(3600000, 320000),
        TEST_USERS["vendor_coordinator_headers"]), 200)

    completed = validate_success(api.complete_repatriation(asg_id, ADMIN), 200)
    assert completed["status"] == "REPATRIATED"
    assert completed["actual_end_date"] == "2026-08-01", (
        "stamped with the logical clock, still at its startup value"
    )

    split = validate_success(api.get_split(split_id, ADMIN), 200)
    assert split["status"] == "TERMINATED"


def test_close_blocked_until_ledger_settled_then_full_lifecycle_completes(api, admin_headers, finance_headers):
    """PRD §3.9: "A `MobilityAdmin` closes a `REPATRIATED` assignment only when the
    ledger is fully settled: every settlement of the assignment must be `SETTLED`, and
    every chargeback entry must be `POSTED` or `VOIDED`; any outstanding item is
    rejected with `ERR_UNSETTLED_LEDGER`."
    PRD §3.9: "A successful close moves the assignment to `CLOSED`, its terminal state
    alongside `CANCELLED`."

    Design: Corner/validations/close_blocked_until_ledger_settled_then_full_lifecycle_completes
    """
    # Activated, one POSTED record, vendor FILED, settlement +25000 APPROVED.
    ctx = setup_pending_review_settlement(
        filed_total_gross_cents=1500000, filed_home_tax_cents=130000)
    asg_id = ctx["assignment"]["id"]
    settlement = ctx["settlement"]
    approved = validate_success(api.approve_settlement(settlement["id"], finance_headers), 200)
    assert approved["status"] == "APPROVED"

    version = get_assignment_version(asg_id)
    validate_success(api.initiate_repatriation(
        asg_id, initiate_repatriation_payload(version), ADMIN), 200)
    validate_success(api.complete_repatriation(asg_id, ADMIN), 200)

    # Settlement APPROVED but not SETTLED: close is blocked.
    res = api.close_assignment(asg_id, ADMIN)
    validate_error(res, ApiErrorId.ERR_UNSETTLED_LEDGER)

    validate_success(api.settle_settlement(settlement["id"], finance_headers), 200)

    # Settlement SETTLED but its SETTLEMENT chargeback entry is still ACCRUED.
    res = api.close_assignment(asg_id, ADMIN)
    validate_error(res, ApiErrorId.ERR_UNSETTLED_LEDGER)

    entries = list_chargebacks(asg_id)
    assert len(entries) == 2
    for entry in entries:
        validate_success(api.post_chargeback(entry["id"], finance_headers), 200)

    closed = validate_success(api.close_assignment(asg_id, ADMIN), 200)
    assert closed["status"] == "CLOSED"
