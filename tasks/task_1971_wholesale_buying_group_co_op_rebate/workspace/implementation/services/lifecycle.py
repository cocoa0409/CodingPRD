"""Cross-entity cascades: quarter close, audit resolution, distribution
calculation/disbursement (PRD §3.5-§3.7)."""

import db
from db import store, new_entity, touch
from errors import ApiError, ERR_SPLIT_MISMATCH
from services import calc


def finalize_accrual(accrual, coop):
    """OPEN -> FINALIZED at quarter close: lock final under the final variant,
    run the pass-through split, book final_rebate_cents into the pool."""
    new_final, applied = calc.recompute_final(accrual)
    accrual["final_rebate_cents"] = new_final
    accrual["tier_applied_min_qty"] = applied
    enrollment = calc.enrollment_of(accrual)
    member = calc.member_of_enrollment(enrollment)
    pass_through, retained = calc.split_rebate(member["commitment_level"], new_final)
    if pass_through + retained != new_final:
        raise ApiError(ERR_SPLIT_MISMATCH, 500,
                       "pass_through_cents + retained_cents != final_rebate_cents")
    accrual["pass_through_cents"] = pass_through
    accrual["retained_cents"] = retained
    accrual["status"] = "FINALIZED"
    # Pool booking (literal event ledger): every finalization at quarter close
    # adds the accrual's final_rebate_cents to the pool.
    coop["pool_reserve_cents"] += new_final
    touch(accrual)


def close_quarter():
    """PRD §3.6: advance the counter, then run the four cascades in order."""
    coop = db.get_coop()
    closing = coop["current_quarter_index"]
    coop["current_quarter_index"] = closing + 1

    # 1) Accrual finalization for OPEN accruals due at this close. Accruals
    #    pulled back to OPEN by a late audit resolution belong to an earlier
    #    quarter and are re-finalized here on the corrected evidence.
    due = sorted(
        (a for a in store.accruals.values()
         if a["status"] == "OPEN" and a["quarter_index"] <= closing),
        key=lambda a: a["_seq"],
    )
    for accrual in due:
        reports = calc.live_reports(accrual["enrollment_id"], accrual["quarter_index"])
        if any(r["status"] == "FLAGGED" for r in reports):
            continue  # a FLAGGED report holds its accrual open
        finalize_accrual(accrual, coop)

    # 2) Exclusivity recomputation over ACTIVE enrollments (closing quarter's
    #    evidence). A flip to SHORTFALL on an exclusivity program mints a
    #    clawback case.
    active_enrollments = sorted(
        (e for e in store.enrollments.values() if e["status"] == "ACTIVE"),
        key=lambda e: e["_seq"],
    )
    for enr in active_enrollments:
        program = calc.program_of_enrollment(enr)
        in_program = sum(
            (r["audited_cents"] if r["status"] == "ADJUDICATED" and r["audited_cents"] is not None
             else r["self_report_cents"])
            for r in calc.live_reports(enr["id"], closing)
        )
        total_wallet = 0
        for other in store.enrollments.values():
            if other["member_id"] != enr["member_id"]:
                continue
            total_wallet += sum(
                (r["audited_cents"] if r["status"] == "ADJUDICATED" and r["audited_cents"] is not None
                 else r["self_report_cents"])
                for r in calc.live_reports(other["id"], closing)
            )
        share = 0 if total_wallet == 0 else (in_program * 100) // total_wallet
        if not program["exclusivity_required"]:
            new_status = "NOT_APPLICABLE"
        elif share >= program["exclusivity_threshold_pct"]:
            new_status = "COMPLIANT"
        else:
            new_status = "SHORTFALL"
        old_status = enr["exclusivity_status"]
        if share != enr["exclusivity_share_pct"] or new_status != old_status:
            enr["exclusivity_share_pct"] = share
            enr["exclusivity_status"] = new_status
            touch(enr)
        if (new_status == "SHORTFALL" and old_status != "SHORTFALL"
                and program["exclusivity_required"]):
            calc.create_clawback_case(enr["member_id"], "EXCLUSIVITY_BREACH")

    # 3) Holdback releases that have come due.
    due_releases = sorted(
        (h for h in store.holdbacks.values()
         if h["status"] == "SCHEDULED"
         and h["release_quarter_index"] <= coop["current_quarter_index"]),
        key=lambda h: h["_seq"],
    )
    for h in due_releases:
        member = store.members.get(h["member_id"])
        if member is not None and member["status"] == "CHURNED":
            # The churn cascade already forfeits SCHEDULED releases; guard anyway.
            h["status"] = "FORFEITED"
            touch(h)
            continue
        h["status"] = "RELEASED"
        touch(h)
        coop["pool_reserve_cents"] -= h["release_cents"]
        if member is not None:
            member["lifetime_pass_through_cents"] += h["release_cents"]
            touch(member)

    # 4) Seal the close.
    touch(coop)
    return coop


def resolve_audit(audit, audited_qty, audited_cents):
    """PRD §3.5 resolution cascade."""
    coop = db.get_coop()
    report = store.reports[audit["purchase_report_id"]]
    audit["audited_qty"] = audited_qty
    audit["audited_cents"] = audited_cents
    audit["resolved_quarter_index"] = coop["current_quarter_index"]
    severity = calc.finding_severity(report["self_report_cents"], audited_cents)
    audit["finding_severity"] = severity
    audit["status"] = "RESOLVED"
    touch(audit)

    # First: the audited report transitions SUBMITTED -> ADJUDICATED.
    if report["status"] == "SUBMITTED":
        report["audited_qty"] = audited_qty
        report["audited_cents"] = audited_cents
        report["status"] = "ADJUDICATED"
        touch(report)

    # Second: recompute the accrual under the final variant; pull a FINALIZED
    # accrual whose final amount moved back to OPEN for re-finalization.
    accrual = calc.find_accrual(report["enrollment_id"], report["quarter_index"])
    if accrual is not None:
        new_final, applied = calc.recompute_final(accrual)
        prior_final = accrual["final_rebate_cents"]
        accrual["final_rebate_cents"] = new_final
        accrual["tier_applied_min_qty"] = applied
        changed = new_final != prior_final
        if changed and accrual["status"] == "FINALIZED":
            accrual["status"] = "OPEN"
        if changed:
            touch(accrual)
            # OCC coupling: a late audit resolution that recomputes an accrual
            # advances the version of the still-DRAFT distribution covering
            # that quarter, so a stale calculate is rejected (412).
            for dist in store.distributions.values():
                if dist["status"] == "DRAFT" and dist["quarter_index"] == accrual["quarter_index"]:
                    touch(dist)

    # Third: MATERIAL findings increment the member's material-finding count.
    enrollment = store.enrollments[report["enrollment_id"]]
    member = store.members[enrollment["member_id"]]
    if severity == "MATERIAL":
        member["prior_audit_findings_count"] += 1
        touch(member)
        # Fourth: MATERIAL against an already-DISTRIBUTED accrual mints a case.
        if accrual is not None and accrual["status"] == "DISTRIBUTED":
            calc.create_clawback_case(member["id"], "AUDIT_SHORTFALL")
    return audit


def calculate_distribution(dist):
    """Aggregate FINALIZED accruals for the distribution's quarter and derive
    totals, the holdback (FLAT vs RISK_ADJUSTED), and clawback offsets."""
    included = sorted(
        (a for a in store.accruals.values()
         if a["status"] == "FINALIZED" and a["quarter_index"] == dist["quarter_index"]),
        key=lambda a: a["_seq"],
    )
    dist["gross_rebate_cents"] = sum(a["final_rebate_cents"] for a in included)
    dist["total_pass_through_cents"] = sum(a["pass_through_cents"] for a in included)
    dist["total_retained_cents"] = sum(a["retained_cents"] for a in included)

    per_member = {}
    flat_pass_through = 0
    for a in included:
        enrollment = calc.enrollment_of(a)
        program = calc.program_of_enrollment(enrollment)
        mid = enrollment["member_id"]
        bucket = per_member.setdefault(mid, {"pass_through": 0, "flat_pt": 0, "ra_pt": 0})
        bucket["pass_through"] += a["pass_through_cents"]
        if program["holdback_policy"] == "FLAT":
            bucket["flat_pt"] += a["pass_through_cents"]
            flat_pass_through += a["pass_through_cents"]
        else:
            bucket["ra_pt"] += a["pass_through_cents"]

    # FLAT: one withholding over total pass-through. RISK_ADJUSTED: per member,
    # elevated rate when prior_audit_findings_count >= 2 (inclusive).
    holdback = (flat_pass_through * calc.FLAT_HOLDBACK_BPS) // calc.BPS_DENOMINATOR
    for mid, bucket in per_member.items():
        member = store.members[mid]
        rate = (calc.RISK_HOLDBACK_BPS
                if member["prior_audit_findings_count"] >= calc.MATERIAL_FINDING_THRESHOLD
                else calc.FLAT_HOLDBACK_BPS)
        ra_holdback = (bucket["ra_pt"] * rate) // calc.BPS_DENOMINATOR
        holdback += ra_holdback
        bucket["withheld"] = ((bucket["flat_pt"] * calc.FLAT_HOLDBACK_BPS) // calc.BPS_DENOMINATOR
                              + ra_holdback)
    dist["holdback_cents"] = holdback

    offset = sum(c["net_clawback_cents"] for c in store.clawbacks.values()
                 if c["status"] in ("OPEN", "NOTIFIED"))
    dist["clawback_offset_cents"] = offset
    dist["net_disbursed_cents"] = (dist["total_pass_through_cents"]
                                   - dist["holdback_cents"] - offset)
    dist["_included"] = [a["id"] for a in included]
    dist["_per_member"] = per_member
    dist["status"] = "CALCULATED"
    touch(dist)
    return dist


def disburse_distribution(dist):
    """Move cash: pool -= net_disbursed, retained += total_retained; accruals
    FINALIZED -> DISTRIBUTED; member lifetimes credited net of their holdback;
    per-member HoldbackReleases scheduled at current quarter + lag."""
    coop = db.get_coop()
    coop["pool_reserve_cents"] -= dist["net_disbursed_cents"]
    coop["retained_revenue_cents"] += dist["total_retained_cents"]
    touch(coop)

    for aid in dist.get("_included", []):
        accrual = store.accruals.get(aid)
        if accrual is not None and accrual["status"] == "FINALIZED":
            accrual["status"] = "DISTRIBUTED"
            touch(accrual)

    per_member = dist.get("_per_member", {})
    for mid in sorted(per_member, key=lambda m: store.members[m]["_seq"]):
        bucket = per_member[mid]
        member = store.members[mid]
        # PRD §3.6: disbursement "credits each member's
        # lifetime_pass_through_cents by that member's share" — the member's
        # share is pass_through_cents (§3.6 pass-through split), not net of
        # the holdback withholding.
        credit = bucket["pass_through"]
        if credit:
            member["lifetime_pass_through_cents"] += credit
            touch(member)
        withheld = bucket.get("withheld", 0)
        if withheld > 0:
            release = new_entity()
            release.update({
                "member_id": mid,
                "source_distribution_id": dist["id"],
                "release_quarter_index": coop["current_quarter_index"] + calc.HOLDBACK_LAG_QUARTERS,
                "release_cents": withheld,
                "status": "SCHEDULED",
            })
            store.holdbacks[release["id"]] = release

    dist["status"] = "DISBURSED"
    touch(dist)
    return dist


def resolve_clawback(case):
    """NOTIFIED/DISPUTED -> RESOLVED: recover the net amount into the pool,
    grow the member's recovered ledger, claw back the compute set."""
    coop = db.get_coop()
    case["recovered_cents"] = case["net_clawback_cents"]
    coop["pool_reserve_cents"] += case["recovered_cents"]
    touch(coop)
    member = store.members.get(case["member_id"])
    if member is not None:
        member["lifetime_clawback_cents"] += case["recovered_cents"]
        touch(member)
    for aid in case.get("_compute_set", []):
        accrual = store.accruals.get(aid)
        if accrual is not None and accrual["status"] == "DISTRIBUTED":
            accrual["status"] = "CLAWED_BACK"
            touch(accrual)
    case["status"] = "RESOLVED"
    touch(case)
    return case
