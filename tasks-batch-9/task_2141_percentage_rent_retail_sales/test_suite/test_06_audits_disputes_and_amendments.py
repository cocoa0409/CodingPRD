"""Sales audits: window cooldowns, findings, settlement, the compensating
rescission and the dispute-amend cycle with its contractual limit.
"""
from test_helpers import (
    accept_report, amend_report, ApiErrorId,
    assert_audit, assert_charge, AUDITOR, charges_for_year,
    create_audit_payload, dispute_report, issue_findings, ledger_entries,
    make_tenant_headers, open_audit, read_audit, read_lease_year, read_report,
    settle_audit, setup_report_under_audit, setup_report_with_findings,
    setup_year_with_accepted_reports, submit_report, TEST_DEFAULTS,
    validate_error, validate_paginated, validate_success,
)

ARTIFICIAL_BREAKPOINT = TEST_DEFAULTS["ARTIFICIAL_BREAKPOINT_CENTS"]
UNREACHABLE_BREAKPOINT = TEST_DEFAULTS["UNREACHABLE_BREAKPOINT_CENTS"]


def _disputed_report_scene():
    """A 30,000,000 September period disputed after findings of +2,000,000."""
    scene = setup_report_with_findings(
        gross=30_000_000, proposed_adjustment_cents=2_000_000,
        suite_code="501", breakpoint_type="ARTIFICIAL",
        artificial_breakpoint_cents=ARTIFICIAL_BREAKPOINT)
    dispute_report(scene["report"]["id"], scene["tenant"]["id"])
    return scene


def _settled_audit_scene():
    """A 38,000,000 period settled at +5,000,000, crossing the breakpoint."""
    scene = setup_report_with_findings(
        gross=38_000_000, proposed_adjustment_cents=5_000_000,
        suite_code="2401", breakpoint_type="ARTIFICIAL",
        artificial_breakpoint_cents=ARTIFICIAL_BREAKPOINT)
    scene["audit"] = settle_audit(scene["audit"]["id"], 5_000_000)
    return scene


# ─── The report's audit-dispute-amend cycle ───────────────────────────────

def test_report_returns_to_accepted_through_the_amend_and_refile_cycle(api):
    """PRD §3.7: "Amendment is the withdrawal that follows. A `TenantUser`
    moves the report `DISPUTED → AMENDED` with a `reason`, again only while
    `amendment_round` is strictly below two. Amendment increases
    `amendment_round` by 1 and takes the report out of the counted set: the
    year's `cumulative_net_sales_cents` decreases by the report's
    `net_sales_cents` and a ledger entry of type `REPORT_WITHDRAWN` is appended
    carrying that figure negated."
    PRD §3.4: "A resubmission after an amendment is `AMENDED → SUBMITTED`, and
    this one is permitted while the year is either `OPEN` or `RECONCILING`,
    because a report withdrawn for amendment must be able to come back even
    after the year has been frozen for reconciliation."

    Design: Difficulty/non_linear_state_machine/sales_report_audit_dispute_amend_resubmit_cycle
    """
    scene = _disputed_report_scene()
    report_id = scene["report"]["id"]

    amend_report(report_id, scene["tenant"]["id"])
    submit_report(report_id, scene["tenant"]["id"], 31_000_000)
    accept_report(report_id)

    report_now = read_report(report_id)
    assert report_now["status"] == "ACCEPTED"
    assert report_now["amendment_round"] == 1
    assert report_now["gross_sales_cents"] == 31_000_000
    assert report_now["net_sales_cents"] == 31_000_000


def test_amending_a_disputed_report_rescinds_its_audit_and_withdraws_the_sales(api):
    """PRD §3.7: "The report's audit flips `FINDINGS_ISSUED → RESCINDED` and
    the year's `open_audit_count` decreases by 1. The tenant then refiles
    through the `AMENDED → SUBMITTED` leg, closing the cycle `ACCEPTED →
    UNDER_AUDIT → DISPUTED → AMENDED → SUBMITTED → ACCEPTED`."
    PRD §3.5: "The second layer, caused by the first, moves the year's running
    sales: `cumulative_net_sales_cents` increases by the report's
    `net_sales_cents`, and a ledger entry of type `REPORT_ACCEPTED` is appended
    with that figure as its `delta_net_sales_cents` and 0 as its
    `delta_billed_cents`."

    Design: Difficulty/non_linear_state_machine/sales_report_audit_dispute_amend_resubmit_cycle
    """
    scene = _disputed_report_scene()
    report_id = scene["report"]["id"]

    amend_report(report_id, scene["tenant"]["id"])
    submit_report(report_id, scene["tenant"]["id"], 31_000_000)
    accept_report(report_id)

    audit_now = read_audit(scene["audit"]["id"])
    assert_audit(audit_now)
    assert audit_now["status"] == "RESCINDED"

    year = read_lease_year(scene["lease_year"]["id"])
    assert year["open_audit_count"] == 0
    assert year["cumulative_net_sales_cents"] == 31_000_000, (
        "the withdrawal removed 30,000,000 before the refiled 31,000,000 "
        "was counted")
    assert year["cumulative_billed_cents"] == 0, (
        "31,000,000 stays below the 40,000,000 breakpoint")


def test_dispute_before_findings_are_issued_is_refused(api):
    """PRD §3.7: "The tenant's answer to findings is a dispute. A `TenantUser`
    on the lease may move the report `UNDER_AUDIT → DISPUTED` with a `reason`,
    but only while the report's audit stands at `FINDINGS_ISSUED` — disputing
    an audit that is merely `OPEN` is refused with `ERR_AUDIT_STATE_INVALID` —
    and only while the report's `amendment_round` is still strictly below two."

    Design: Corner/state_machines/dispute_before_findings_issued_rejected
    """
    scene = setup_report_under_audit(
        gross=30_000_000, suite_code="4601", breakpoint_type="ARTIFICIAL",
        artificial_breakpoint_cents=UNREACHABLE_BREAKPOINT)

    validate_error(
        api.dispute_sales_report(scene["report"]["id"],
                                 {"reason": "We disagree in advance"},
                                 make_tenant_headers(scene["tenant"]["id"])),
        ApiErrorId.ERR_AUDIT_STATE_INVALID.value, 409)

    report_now = read_report(scene["report"]["id"])
    assert report_now["status"] == "UNDER_AUDIT"
    assert report_now["amendment_round"] == 0
    assert read_audit(scene["audit"]["id"])["status"] == "OPEN"


def test_third_dispute_after_two_completed_cycles_is_refused(api):
    """PRD §3.7: "Two full dispute-amend cycles are the contractual limit. Once
    a report's `amendment_round` has reached 2, both dispute and amendment are
    refused with `ERR_AMENDMENT_LIMIT_EXCEEDED`, and the audit trail on that
    period is final."

    Design: Corner/state_machines/amend_beyond_max_amendment_rounds_rejected
    """
    scene = setup_year_with_accepted_reports(
        [30_000_000], suite_code="4701", breakpoint_type="ARTIFICIAL",
        artificial_breakpoint_cents=UNREACHABLE_BREAKPOINT)
    report_id = scene["reports"][0]["id"]
    tenant_id = scene["tenant"]["id"]

    windows = [("2026-10-05T00:00:00Z", "2026-10-20T00:00:00Z"),
               ("2026-11-25T00:00:00Z", "2026-11-30T00:00:00Z"),
               ("2027-01-05T00:00:00Z", "2027-01-10T00:00:00Z")]
    audits = []
    for index, (window_start, window_end) in enumerate(windows):
        audit = open_audit(report_id, window_start, window_end)
        issue_findings(audit["id"], 1_000_000)
        audits.append(audit)
        if index < 2:
            dispute_report(report_id, tenant_id, reason=f"Round {index + 1} dispute")
            amend_report(report_id, tenant_id, reason=f"Round {index + 1} amendment")
            submit_report(report_id, tenant_id, 31_000_000 + index * 1_000_000)
            accept_report(report_id)

    validate_error(
        api.dispute_sales_report(report_id, {"reason": "Round three dispute"},
                                 make_tenant_headers(tenant_id)),
        ApiErrorId.ERR_AMENDMENT_LIMIT_EXCEEDED.value, 422)

    report_now = read_report(report_id)
    assert report_now["amendment_round"] == 2
    assert report_now["status"] == "UNDER_AUDIT"
    assert read_audit(audits[0]["id"])["status"] == "RESCINDED"
    assert read_audit(audits[1]["id"])["status"] == "RESCINDED"
    assert read_audit(audits[2]["id"])["status"] == "FINDINGS_ISSUED"
    assert read_lease_year(
        scene["lease_year"]["id"])["cumulative_net_sales_cents"] == 32_000_000


# ─── Audit window intervals ───────────────────────────────────────────────

def test_audit_window_inside_the_thirty_day_cooldown_is_refused(api):
    """PRD §2.10: "A proposed window collides with an existing non-rescinded
    audit window on the same lease when the proposed start is at or before that
    existing window's end extended forward by the 30-day cooldown, and the
    existing window's start pulled back by the same 30-day cooldown is at or
    before the proposed end. Touching the expanded edge does collide here,
    which is the opposite of the reporting-period rule."

    Design: Difficulty/resource_temporal_overlap/audit_window_closed_interval_with_cooldown_buffer_rejected
    """
    scene = setup_year_with_accepted_reports(
        [30_000_000, 30_000_000], suite_code="2201",
        breakpoint_type="ARTIFICIAL",
        artificial_breakpoint_cents=UNREACHABLE_BREAKPOINT)
    september, october = scene["reports"]
    open_audit(september["id"], "2026-11-01T00:00:00Z", "2026-11-30T00:00:00Z")

    validate_error(
        api.create_audit(
            create_audit_payload(october["id"], "2026-12-20T00:00:00Z",
                                 "2026-12-31T00:00:00Z"),
            AUDITOR),
        ApiErrorId.ERR_AUDIT_WINDOW_CONFLICT.value, 409)

    assert read_report(october["id"])["status"] == "ACCEPTED", (
        "the refused audit leaves the second period untouched")


def test_audit_window_clear_of_the_cooldown_is_accepted(api):
    """PRD §3.7: "The proposed window is tested against every non-`RESCINDED`
    audit already recorded on the same lease under the buffered closed-interval
    rule of Section 2.10, with its thirty-day cooldown on each side; a
    collision is refused with `ERR_AUDIT_WINDOW_CONFLICT`."
    PRD §3.7: "The report moves `ACCEPTED → UNDER_AUDIT` and the reporting
    year's `open_audit_count` increases by 1."

    Design: Difficulty/resource_temporal_overlap/audit_window_closed_interval_with_cooldown_buffer_rejected
    """
    scene = setup_year_with_accepted_reports(
        [30_000_000, 30_000_000], suite_code="2201",
        breakpoint_type="ARTIFICIAL",
        artificial_breakpoint_cents=UNREACHABLE_BREAKPOINT)
    september, october = scene["reports"]
    open_audit(september["id"], "2026-11-01T00:00:00Z", "2026-11-30T00:00:00Z")

    data = validate_success(
        api.create_audit(
            create_audit_payload(october["id"], "2027-01-05T00:00:00Z",
                                 "2027-01-20T00:00:00Z"),
            AUDITOR),
        201,
    )

    assert_audit(data)
    assert data["status"] == "OPEN"
    assert data["lease_id"] == scene["lease"]["id"]
    assert read_report(october["id"])["status"] == "UNDER_AUDIT"

    rows, meta = validate_paginated(
        api.list_audits(AUDITOR, params={"lease_id": scene["lease"]["id"]}))
    assert meta["total_count"] == 2
    assert len(rows) == 2
    assert read_lease_year(scene["lease_year"]["id"])["open_audit_count"] == 2


# ─── Settlement and its reversal ──────────────────────────────────────────

def test_settlement_adjusts_the_report_and_closes_the_open_audit_count(api):
    """PRD §3.7: "Settlement moves the audit `FINDINGS_ISSUED → SETTLED` with a
    `settled_adjustment_cents` supplied at settlement — which need not equal
    what was proposed and may likewise be negative — and drives the report
    `UNDER_AUDIT → ADJUSTED` through a four-layer cascade. First, the audit
    settles with its `settled_adjustment_cents` recorded and the year's
    `open_audit_count` decreases by 1. Second, caused by the first, the
    report's `gross_sales_cents` increases by `settled_adjustment_cents` — a
    negative adjustment therefore reduces it — its `source` becomes
    `AUDIT_ADJUSTED`, and the exclusion waterfall of Section 3.4 re-runs over
    the report's existing exclusion lines against the new gross, rewriting
    `allowed_exclusions_cents` and `net_sales_cents`."

    Design: Difficulty/transitive_cascade/audit_settlement_cascades_to_supplemental_charge_depth_four
    """
    scene = _settled_audit_scene()

    audit_now = read_audit(scene["audit"]["id"])
    assert audit_now["status"] == "SETTLED"
    assert audit_now["settled_adjustment_cents"] == 5_000_000

    report_now = read_report(scene["report"]["id"])
    assert report_now["status"] == "ADJUSTED"
    assert report_now["source"] == "AUDIT_ADJUSTED"
    assert report_now["gross_sales_cents"] == 43_000_000
    assert report_now["net_sales_cents"] == 43_000_000

    assert read_lease_year(scene["lease_year"]["id"])["open_audit_count"] == 0


def test_settlement_that_crosses_the_breakpoint_issues_a_supplemental_charge(api):
    """PRD §3.7: "Fourth, caused by the third, the percentage-rent computation
    re-runs on the new cumulative; when its amount is non-zero a supplemental
    charge is created against the reporting year with `sales_report_id` naming
    this report, `billing_status` of `ISSUED`, and a `charge_type` of
    `PERIODIC` when the amount is positive or `CREDIT` when it is negative, the
    year's `cumulative_billed_cents` moves by `amount_cents`, and a matching
    ledger entry — `PERIODIC_CHARGE_ISSUED` for a positive amount,
    `CREDIT_ISSUED` for a negative one — is appended with `amount_cents` as its
    `delta_billed_cents`."
    PRD §3.7: "Third, caused by the second, the year's
    `cumulative_net_sales_cents` moves by the difference between the report's
    new `net_sales_cents` and its previous `net_sales_cents`, and a ledger
    entry of type `AUDIT_ADJUSTMENT` is appended carrying that difference as
    its `delta_net_sales_cents`."

    Design: Difficulty/transitive_cascade/audit_settlement_cascades_to_supplemental_charge_depth_four
    """
    scene = _settled_audit_scene()

    year = read_lease_year(scene["lease_year"]["id"])
    assert year["cumulative_net_sales_cents"] == 43_000_000
    assert year["cumulative_billed_cents"] == 180_000

    charges = charges_for_year(scene["lease_year"]["id"])
    assert len(charges) == 1
    assert_charge(charges[0])
    assert charges[0]["charge_type"] == "PERIODIC"
    assert charges[0]["billing_status"] == "ISSUED"
    assert charges[0]["amount_cents"] == 180_000
    assert charges[0]["sales_report_id"] == scene["report"]["id"]

    entries = ledger_entries(scene["lease_year"]["id"])
    assert len(entries) == 3
    assert [entry["entry_type"] for entry in entries] == [
        "REPORT_ACCEPTED", "AUDIT_ADJUSTMENT", "PERIODIC_CHARGE_ISSUED"]
    assert entries[1]["delta_net_sales_cents"] == 5_000_000
    assert entries[2]["delta_billed_cents"] == 180_000


def test_rescinding_a_settlement_restores_the_reported_sales(api):
    """PRD §3.7: "From `SETTLED`, rescission is a compensating reversal and
    additionally requires the reporting year to be `OPEN` or `RECONCILING`: the
    report moves `ADJUSTED → ACCEPTED`, its `gross_sales_cents` decreases by
    the audit's `settled_adjustment_cents`, its `source` returns to
    `TENANT_REPORTED`, and the exclusion waterfall re-runs."
    PRD §3.7: "Every charge that the settlement itself created — that is, every
    charge whose `sales_report_id` is this report and whose `issued_at` is at
    or after the moment the audit was settled — flips `ISSUED → VOID`, the
    year's `cumulative_billed_cents` is reduced by that charge's
    `amount_cents`, and a matching `AUDIT_RESCINDED` ledger entry is appended
    carrying that amount negated as its `delta_billed_cents`."

    Design: Difficulty/compensating_invariant/audit_rescind_leaves_reported_sales_conserved
    """
    scene = _settled_audit_scene()

    validate_success(
        api.rescind_audit(scene["audit"]["id"],
                          {"reason": "Settlement vacated by arbitration"},
                          AUDITOR))

    assert read_audit(scene["audit"]["id"])["status"] == "RESCINDED"

    report_now = read_report(scene["report"]["id"])
    assert report_now["status"] == "ACCEPTED"
    assert report_now["gross_sales_cents"] == 38_000_000
    assert report_now["net_sales_cents"] == 38_000_000

    year = read_lease_year(scene["lease_year"]["id"])
    assert year["cumulative_net_sales_cents"] == 38_000_000
    assert year["cumulative_billed_cents"] == 0

    charges = charges_for_year(scene["lease_year"]["id"])
    assert len(charges) == 1
    assert charges[0]["billing_status"] == "VOID"
    assert charges[0]["amount_cents"] == 180_000


def test_rescinded_settlement_leaves_the_ledger_conserved(api):
    """PRD §3.7: "The year's `cumulative_net_sales_cents` moves by the
    difference between the report's new and previous `net_sales_cents` and a
    ledger entry of type `AUDIT_RESCINDED` records the reversal."
    PRD §2.11: "Ledger entries are never updated or deleted, and they are read
    back oldest first."

    Design: Difficulty/compensating_invariant/audit_rescind_leaves_reported_sales_conserved
    """
    scene = _settled_audit_scene()

    validate_success(
        api.rescind_audit(scene["audit"]["id"],
                          {"reason": "Settlement vacated by arbitration"},
                          AUDITOR))

    entries = ledger_entries(scene["lease_year"]["id"])
    net_movements = [entry["delta_net_sales_cents"] for entry in entries]
    billed_movements = [entry["delta_billed_cents"] for entry in entries]

    assert sum(net_movements) == 38_000_000, (
        f"reported sales must return to the filed figure; movements were "
        f"{net_movements}")
    assert sum(billed_movements) == 0, (
        f"billed money must net to nothing; movements were {billed_movements}")
    assert "AUDIT_RESCINDED" in [entry["entry_type"] for entry in entries]
    assert -180_000 in billed_movements
    assert -5_000_000 in net_movements
