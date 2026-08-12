"""remediation_pool_allocation, cap_funds_rollup, board_report_aggregation,
monitoring_cycle_effects, market_penetration_index, matched-pair selector."""
from datetime import date, timedelta
from decimal import Decimal

import db
from services.officer import D, PROTECTED, q, refresh_officer


# --------------------------------------------------------------------------
# remediation_pool_allocation
# --------------------------------------------------------------------------
def allocate_pool(cap, finding):
    """Runs at CAP approval. Equal half-up shares; residual to the payment
    whose application appears FIRST in finding.harmed_application_ids."""
    harmed = finding["harmed_application_ids"]
    n = len(harmed)
    if n == 0:
        cap["remaining_cents"] = cap["pool_cents"]
        return
    share = int(
        (D(cap["pool_cents"]) / D(n)).quantize(Decimal("1"), rounding="ROUND_HALF_UP")
    )
    residual = cap["pool_cents"] - n * share
    total = 0
    for i, app_id in enumerate(harmed):
        amount = share + residual if i == 0 else share
        payment = db.new_record(
            {
                "corrective_action_plan_id": cap["id"],
                "application_id": app_id,
                "amount_cents": amount,
                "origin": "AUTO_ALLOCATED",
                "status": "PENDING",
                "disbursed_by_user_id": None,
                "disposition_reason": None,
            }
        )
        db.STORES["payments"][payment["id"]] = payment
        total += amount
    cap["remaining_cents"] = cap["pool_cents"] - total


# --------------------------------------------------------------------------
# cap_funds_rollup
# --------------------------------------------------------------------------
CAP_TERMINAL_PAYMENTS = ("DISBURSED", "VOIDED", "RETURNED")


def cap_rollup(cap):
    """Recompute funds counters and run the CAP completion check."""
    payments = [
        p
        for p in db.STORES["payments"].values()
        if p["corrective_action_plan_id"] == cap["id"]
    ]
    cap["disbursed_cents"] = sum(
        p["amount_cents"] for p in payments if p["status"] == "DISBURSED"
    )
    cap["remaining_cents"] = cap["pool_cents"] - sum(
        p["amount_cents"] for p in payments if p["status"] in ("PENDING", "DISBURSED")
    )
    if (
        cap["status"] in ("EXECUTING", "OVERDUE")
        and payments
        and all(p["status"] in CAP_TERMINAL_PAYMENTS for p in payments)
        and any(p["status"] == "DISBURSED" for p in payments)
    ):
        cap["status"] = "COMPLETED"
        db.touch(cap)
        finding = db.STORES["findings"].get(cap["finding_id"])
        if finding is not None and finding["status"] == "SUBSTANTIATED":
            finding["status"] = "CLOSED"
            db.touch(finding)
            run = db.STORES["runs"].get(finding["analysis_run_id"])
            if run is not None:
                run["open_finding_count"] -= 1
                db.touch(run)


# --------------------------------------------------------------------------
# board_report_aggregation
# --------------------------------------------------------------------------
def periods_overlap(a_start, a_end, b_start, b_end):
    """Half-open interval overlap: mere adjacency does not overlap."""
    return a_start < b_end and b_start < a_end


def board_refresh_counts(report):
    in_runs = [
        r
        for r in db.STORES["runs"].values()
        if periods_overlap(
            r["period_start"], r["period_end"], report["period_start"], report["period_end"]
        )
    ]
    in_run_ids = {r["id"] for r in in_runs}
    privileged_run_ids = {
        st["analysis_run_id"]
        for st in db.STORES["self_tests"].values()
        if st.get("analysis_run_id") and st["disclosure_status"] == "PRIVILEGED"
    }
    substantiated = 0
    excluded = 0
    for f in db.STORES["findings"].values():
        if f["analysis_run_id"] in in_run_ids and f["status"] in ("SUBSTANTIATED", "CLOSED"):
            if f["analysis_run_id"] in privileged_run_ids:
                excluded += 1
            else:
                substantiated += 1
    report["substantiated_finding_count"] = substantiated
    report["privileged_exclusion_count"] = excluded
    report["caps_executing_count"] = sum(
        1 for c in db.STORES["caps"].values() if c["status"] in ("EXECUTING", "OVERDUE")
    )
    report["red_officer_count"] = sum(
        1 for o in db.STORES["officers"].values() if o["monitoring_tier"] == "RED"
    )


# --------------------------------------------------------------------------
# monitoring_cycle_effects (pinned order)
# --------------------------------------------------------------------------
EXCEPTION_EXPIRY_DAYS = 30
PRIVILEGE_FORFEIT_CYCLES = 2


def run_cycle():
    cycle_index = db.next_cycle()
    today = db.now_dt().date()

    # 1. Exception expiry: created_at strictly more than 30 days before the
    # current logical time (timestamp precision; exactly 30 days does not flip).
    expired_ids = []
    now = db.now_dt()
    for exc in db.STORES["exceptions"].values():
        if exc["status"] in ("REQUESTED", "ESCALATED"):
            created_at = db.parse_iso(exc["created_at"])
            if now - created_at > timedelta(days=EXCEPTION_EXPIRY_DAYS):
                exc["status"] = "EXPIRED"
                db.touch(exc)
                app = db.STORES["applications"].get(exc["application_id"])
                if app is not None and app["has_exception"] != "NONE":
                    app["has_exception"] = "NONE"
                    db.touch(app)
                expired_ids.append(exc["id"])

    # 2. Overdue CAPs: due_date strictly before today with a PENDING payment.
    overdue_ids = []
    for cap in db.STORES["caps"].values():
        if cap["status"] == "EXECUTING":
            due = date.fromisoformat(cap["due_date"])
            has_pending = any(
                p["corrective_action_plan_id"] == cap["id"] and p["status"] == "PENDING"
                for p in db.STORES["payments"].values()
            )
            if due < today and has_pending:
                cap["status"] = "OVERDUE"
                db.touch(cap)
                overdue_ids.append(cap["id"])

    # 3. Self-test privilege forfeiture.
    lost_ids = []
    for st in db.STORES["self_tests"].values():
        if st["status"] == "CLOSED_VIOLATION":
            st["cycles_open"] += 1
            if st["cycles_open"] >= PRIVILEGE_FORFEIT_CYCLES:
                st["status"] = "PRIVILEGE_LOST"
                st["disclosure_status"] = "DISCLOSABLE"
                lost_ids.append(st["id"])
            db.touch(st)

    # 4. Recompute every officer's risk score / tier.
    for officer in db.STORES["officers"].values():
        refresh_officer(officer)

    return {
        "cycle_index": cycle_index,
        "expired_exception_ids": expired_ids,
        "overdue_cap_ids": overdue_ids,
        "privilege_lost_self_test_ids": lost_ids,
    }


# --------------------------------------------------------------------------
# market_penetration_index (both variants)
# --------------------------------------------------------------------------
def penetration_report(market, period_start, period_end):
    rows = [
        a
        for a in db.STORES["applications"].values()
        if a["market_id"] == market["id"]
        and a["status"] == "VALIDATED"
        and period_start <= a["decision_date"] < period_end
    ]
    originated = [a for a in rows if a["outcome"] == "ORIGINATED"]
    bench = None
    for b in db.STORES["benchmarks"].values():
        if (
            b["market_id"] == market["id"]
            and b["period_start"] == period_start
            and b["period_end"] == period_end
        ):
            bench = b
            break

    if not originated:
        share = None
        branch_weighted = None
        peer_relative = None
    else:
        prot_orig = [a for a in originated if a["applicant_group"] in PROTECTED]
        share_exact = D(len(prot_orig)) / D(len(originated))
        share = q(share_exact, 4)
        pop_share = D(str(market["protected_group_population_share"]))
        if pop_share == 0:
            branch_weighted = None
        else:
            branch_weighted = q(share_exact / pop_share, 4)
        prot_validated = [a for a in rows if a["applicant_group"] in PROTECTED]
        if bench is None or not prot_validated:
            peer_relative = None
        else:
            peer_rate = D(str(bench["peer_protected_origination_rate"]))
            if peer_rate == 0:
                peer_relative = None
            else:
                bank_rate = D(len(prot_orig)) / D(len(prot_validated))
                peer_relative = q(bank_rate / peer_rate, 4)

    return {
        "period_start": period_start,
        "period_end": period_end,
        "bank_protected_origination_share": share,
        "penetration_index_branch_weighted": branch_weighted,
        "penetration_index_peer_relative": peer_relative,
        "peer_benchmark_id": None if bench is None else bench["id"],
    }


# --------------------------------------------------------------------------
# Matched-pair comparator selector
# --------------------------------------------------------------------------
def select_control(target):
    """CONTROL-group ORIGINATED VALIDATED applications, same market/product,
    |credit_score diff| <= 40; ranked by |cs diff|, |dti diff|, created_at."""
    candidates = [
        a
        for a in db.STORES["applications"].values()
        if a["applicant_group"] == "CONTROL"
        and a["outcome"] == "ORIGINATED"
        and a["status"] == "VALIDATED"
        and a["market_id"] == target["market_id"]
        and a["product_type"] == target["product_type"]
        and abs(a["credit_score"] - target["credit_score"]) <= 40
    ]
    candidates.sort(
        key=lambda a: (
            abs(a["credit_score"] - target["credit_score"]),
            abs(D(str(a["dti_pct"])) - D(str(target["dti_pct"]))),
            a["created_at"],
            a["_seq"],
        )
    )
    return candidates[0] if candidates else None


def pair_comparable(target, control):
    return (
        target["applicant_group"] in PROTECTED
        and control["applicant_group"] == "CONTROL"
        and target["outcome"] == "DENIED"
        and control["outcome"] == "ORIGINATED"
        and target["market_id"] == control["market_id"]
        and target["product_type"] == control["product_type"]
        and abs(target["credit_score"] - control["credit_score"]) <= 40
    )
