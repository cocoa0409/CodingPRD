"""Domain services: derived-field refresh, cascades and multi-aggregate writes."""

from decimal import Decimal

import calc
import clock
import config as C
import models
from store import db, ordered, sort_key, touch

_MISSING = object()


def update(record, **changes):
    """Apply changes; bump version/updated_at only when a value actually moved."""
    dirty = False
    for key, value in changes.items():
        if record.get(key, _MISSING) != value:
            record[key] = value
            dirty = True
    if dirty:
        touch(record)
    return dirty


# --------------------------------------------------------------- peer groups
def sync_member_count(peer_group_id):
    if not peer_group_id:
        return
    pg = db.peer_groups.get(peer_group_id)
    if pg is None:
        return
    count = sum(
        1
        for v in db.vendors.values()
        if v["peer_group_id"] == peer_group_id
        and v["authorization_status"] in C.MEMBER_STATUSES
    )
    update(pg, member_count=count)


def retire_peer_group(pg):
    update(pg, status="RETIRED", retired_at=clock.now())
    for vendor in ordered(db.vendors):
        if vendor["peer_group_id"] != pg["id"]:
            continue
        if vendor["authorization_status"] in ("IN_REVIEW", "REAUTH_PENDING"):
            update(vendor, authorization_blocked_reason=C.REASON_PEER_GROUP_RETIRED)


# ------------------------------------------------------------ vendor helpers
def refresh_completeness(vendor, extra_required_items=()):
    count, complete = calc.price_submission_completeness(vendor, extra_required_items)
    update(vendor, accepted_submission_count=count, price_submission_complete=complete)


def refresh_avg_redemption(vendor):
    update(vendor, avg_monthly_redemption_cents=calc.vendor_avg_monthly_redemption(vendor))


def has_open_case(vendor_id, exclude_case_id=None):
    for case in db.sanction_cases.values():
        if case["vendor_id"] != vendor_id:
            continue
        if exclude_case_id is not None and case["id"] == exclude_case_id:
            continue
        if case["status"] in C.OPEN_SANCTION_STATUSES:
            return True
    return False


def training_current(vendor):
    expires = vendor["training_expires_at"]
    return expires is not None and clock.now() < expires


def disqualification_live(vendor):
    until = vendor["disqualified_until"]
    return until is not None and clock.now() < until


def scheduled_compliance_buy_exists(vendor_id):
    return any(
        v["vendor_id"] == vendor_id
        and v["status"] == "SCHEDULED"
        and v["visit_type"] == "COMPLIANCE_BUY"
        for v in db.monitoring_visits.values()
    )


def void_open_submissions(vendor, reason):
    for submission in ordered(db.price_submissions):
        if submission["vendor_id"] != vendor["id"]:
            continue
        if submission["status"] not in ("SUBMITTED", "ACCEPTED"):
            continue
        cycle = db.price_cycles.get(submission["price_cycle_id"])
        if cycle is None or cycle["status"] not in ("OPEN", "CLOSED"):
            continue
        update(submission, status="VOIDED", voided_reason=reason)
    refresh_completeness(vendor)


# ------------------------------------------------------------ delist cascade
def delist_item(item, reason):
    # hop 1
    update(item, status="DELISTED", delisted_at=clock.now(), delist_reason=reason)
    # hop 2
    for ceiling in ordered(db.price_ceilings):
        if ceiling["food_item_id"] != item["id"]:
            continue
        if ceiling["status"] not in ("PROVISIONAL", "ACTIVE"):
            continue
        update(ceiling, status="SUPERSEDED", superseded_reason="ITEM_DELISTED")
    # hop 3
    affected = []
    for submission in ordered(db.price_submissions):
        if submission["food_item_id"] != item["id"]:
            continue
        if submission["status"] not in ("SUBMITTED", "ACCEPTED"):
            continue
        cycle = db.price_cycles.get(submission["price_cycle_id"])
        if cycle is None or cycle["status"] not in ("OPEN", "CLOSED"):
            continue
        update(submission, status="VOIDED", voided_reason="ITEM_DELISTED")
        if submission["vendor_id"] not in affected:
            affected.append(submission["vendor_id"])
    # hop 4
    for vendor_id in affected:
        vendor = db.vendors.get(vendor_id)
        if vendor is not None:
            refresh_completeness(vendor, extra_required_items=(item,))


# ------------------------------------------------------------- ceiling sweep
def _sweep(cycle, allowed_statuses, status):
    written = 0
    skipped = 0
    pairs = []
    now = clock.now()
    for pg in ordered(db.peer_groups):
        if pg["status"] != "ACTIVE":
            continue
        for item in ordered(db.food_items):
            if item["status"] != "ACTIVE":
                continue
            values = calc.compute_ceiling_values(pg, item, cycle, allowed_statuses)
            if values is None:
                skipped += 1
                continue
            row = models.price_ceiling(
                peer_group_id=pg["id"],
                food_item_id=item["id"],
                price_cycle_id=cycle["id"],
                mar_cents=values["mar_cents"],
                basis=values["basis"],
                base_cents=values["base_cents"],
                cap_cents=values["cap_cents"],
                cap_binding=values["cap_binding"],
                peer_submission_count=values["peer_submission_count"],
                contributing_submission_count=values["contributing_submission_count"],
                status=status,
                effective_from=now,
            )
            db.price_ceilings[row["id"]] = row
            written += 1
            pairs.append((pg["id"], item["id"]))
    return written, skipped, pairs


def close_cycle(cycle):
    written, skipped, _ = _sweep(cycle, ("SUBMITTED", "ACCEPTED"), "PROVISIONAL")
    update(
        cycle,
        status="CLOSED",
        closed_at=clock.now(),
        provisional_ceiling_count=written,
        skipped_pair_count=skipped,
    )
    return cycle


def publish_cycle(cycle):
    superseded = 0
    # pass 1: this cycle's provisional rows
    for ceiling in ordered(db.price_ceilings):
        if ceiling["price_cycle_id"] == cycle["id"] and ceiling["status"] == "PROVISIONAL":
            update(ceiling, status="SUPERSEDED", superseded_reason="PROVISIONAL_REPLACED")
            superseded += 1
    # pass 2: the FINAL sweep
    written, skipped, pairs = _sweep(cycle, ("ACCEPTED",), "ACTIVE")
    # pass 3: earlier-cycle ACTIVE rows for the published pairs
    published_pairs = set(pairs)
    for ceiling in ordered(db.price_ceilings):
        if ceiling["price_cycle_id"] == cycle["id"]:
            continue
        if ceiling["status"] != "ACTIVE":
            continue
        if (ceiling["peer_group_id"], ceiling["food_item_id"]) not in published_pairs:
            continue
        update(ceiling, status="SUPERSEDED", superseded_reason="NEWER_CYCLE_PUBLISHED")
        superseded += 1
    published_at = clock.now()
    update(
        cycle,
        status="PUBLISHED",
        published_at=published_at,
        published_ceiling_count=written,
        skipped_pair_count=skipped,
    )
    return {
        "price_cycle_id": cycle["id"],
        "status": cycle["status"],
        "published_ceiling_count": written,
        "skipped_pair_count": skipped,
        "superseded_ceiling_count": superseded,
        "published_at": published_at,
    }


# ------------------------------------------------------------ monitoring
def conduct_visit(visit, vendor, buy_items):
    now = clock.now()
    visit["buy_items"] = list(buy_items)
    pct, any_missing, passing, total = calc.verify_minimum_stock(visit, vendor)
    overcharge = calc.compliance_buy_overcharge(visit, vendor, visit["buy_items"])

    if any_missing:
        outcome = "FAIL_MISSING_CATEGORY"
    elif passing < total:
        outcome = "FAIL_BELOW_MINIMUM"
    elif overcharge > 0:
        outcome = "FAIL_PRICE_OVERCHARGE"
    else:
        outcome = "PASS"

    visit["conducted_at"] = now
    visit["outcome"] = outcome
    visit["stock_compliance_pct"] = pct
    visit["overcharge_cents"] = overcharge
    visit["status"] = "PASSED" if outcome == "PASS" else "FAILED"
    touch(visit)

    if outcome == "PASS":
        _pass_branch(visit, vendor)
    else:
        _fail_branch(visit, vendor)
    return visit


def _pass_branch(visit, vendor):
    if visit["visit_type"] == "HIGH_RISK_FOLLOWUP":
        deadline = vendor["cure_deadline_at"]
        can_cure = deadline is not None and clock.now() <= deadline
        if can_cure:
            for other in ordered(db.monitoring_visits):
                if other["id"] == visit["id"]:
                    continue
                if other["vendor_id"] != vendor["id"] or other["status"] != "FAILED":
                    continue
                update(other, status="CURED")
        update(
            vendor,
            open_finding_count=0,
            cure_deadline_at=None,
            compliance_buy_required=False,
            risk_flag="NONE",
            reauthorization_hold=scheduled_compliance_buy_exists(vendor["id"]),
        )
    if vendor["authorization_status"] == "SUSPENDED" and not has_open_case(vendor["id"]):
        update(vendor, authorization_status="AUTHORIZED", risk_flag="NONE")
        sync_member_count(vendor["peer_group_id"])


def _fail_branch(visit, vendor):
    now = clock.now()
    # hop 1
    findings = vendor["open_finding_count"] + 1
    update(
        vendor,
        open_finding_count=findings,
        cure_deadline_at=clock.add_days(now, C.CURE_PERIOD_DAYS),
    )
    if findings < C.HIGH_RISK_FINDING_THRESHOLD:
        return
    # hop 2
    was_required = vendor["compliance_buy_required"]
    update(vendor, compliance_buy_required=True, risk_flag="HIGH_FINDING_COUNT")
    if was_required:
        return
    # hop 3
    auto = models.monitoring_visit(
        vendor_id=vendor["id"],
        visit_type="COMPLIANCE_BUY",
        scheduled_for=clock.add_days(now, C.COMPLIANCE_BUY_LEAD_DAYS),
        auto_generated=True,
    )
    db.monitoring_visits[auto["id"]] = auto
    # hop 4
    changes = {"reauthorization_hold": True}
    if vendor["authorization_status"] == "REAUTH_PENDING":
        changes["reauth_blocked_reason"] = C.REASON_PENDING_COMPLIANCE_BUY
    update(vendor, **changes)


# ------------------------------------------------------------- adjudication
def adjudicate_claim(claim, vendor, governing):
    lines = [
        line
        for line in db.claim_lines.values()
        if line["redemption_claim_id"] == claim["id"]
    ]
    lines.sort(key=lambda line: line["line_number"])
    for line in lines:
        item = calc.find_active_or_any_item_by_upc(line["upc"])
        category = db.food_categories.get(item["food_category_id"]) if item else None
        ceiling = None
        if item is not None:
            ceiling = calc.find_active_ceiling(
                vendor["peer_group_id"], item["id"], governing["id"]
            )
        changes = {
            "food_item_id": item["id"] if item is not None else None,
            "applied_mar_cents": None,
        }
        if item is None or item["status"] == "DELISTED" or category is None:
            changes.update(edit_result="REJECTED", edit_code="E01", allowed_cents=0)
        elif category["is_formula"] and (
            (
                category["formula_restriction_level"] == "CONTRACT_BRAND_ONLY"
                and not item["contract_brand"]
            )
            or (
                category["formula_restriction_level"] == "MEDICAL_DOC_REQUIRED"
                and not line["medical_doc_on_file"]
            )
        ):
            changes.update(edit_result="REJECTED", edit_code="E02", allowed_cents=0)
        elif line["quantity"] <= 0 or line["quantity"] > category["max_units_per_transaction"]:
            changes.update(edit_result="REJECTED", edit_code="E03", allowed_cents=0)
        elif ceiling is None:
            changes.update(edit_result="REJECTED", edit_code="E04", allowed_cents=0)
        else:
            changes["applied_mar_cents"] = ceiling["mar_cents"]
            if line["charged_unit_price_cents"] > ceiling["mar_cents"]:
                changes.update(
                    edit_result="ACCEPTED_REDUCED",
                    edit_code="E05",
                    allowed_cents=ceiling["mar_cents"] * line["quantity"],
                )
            else:
                changes.update(
                    edit_result="ACCEPTED",
                    edit_code=None,
                    allowed_cents=line["charged_unit_price_cents"] * line["quantity"],
                )
        update(line, **changes)

    adjudicated_total = sum(line["allowed_cents"] for line in lines)
    applied = sum(
        adj["recoupment_cents"]
        for adj in db.adjustments.values()
        if adj["redemption_claim_id"] == claim["id"] and adj["status"] == "APPLIED"
    )
    update(
        claim,
        status="ADJUDICATED",
        governing_price_cycle_id=governing["id"],
        adjudicated_at=clock.now(),
        adjudicated_total_cents=adjudicated_total,
        net_payable_cents=adjudicated_total - applied,
        accepted_line_count=sum(1 for l in lines if l["edit_result"] == "ACCEPTED"),
        reduced_line_count=sum(1 for l in lines if l["edit_result"] == "ACCEPTED_REDUCED"),
        rejected_line_count=sum(1 for l in lines if l["edit_result"] == "REJECTED"),
    )
    refresh_avg_redemption(vendor)
    return claim


# --------------------------------------------------------------- adjustments
def apply_adjustment(adjustment, claim, vendor, actor_id):
    update(
        adjustment,
        status="APPLIED",
        applied_by_user_id=actor_id,
        applied_at=clock.now(),
    )
    for entry in adjustment["line_recoupments"]:
        line = db.claim_lines.get(entry["claim_line_id"])
        if line is None:
            continue
        update(line, recouped_cents=line["recouped_cents"] + entry["recoupment_cents"])
    update(
        claim,
        status="ADJUSTED",
        net_payable_cents=claim["net_payable_cents"] - adjustment["recoupment_cents"],
    )
    if vendor is not None:
        update(
            vendor,
            recoupment_balance_cents=vendor["recoupment_balance_cents"]
            + adjustment["recoupment_cents"],
        )
    return adjustment


def reverse_adjustment(adjustment, claim, vendor, reason):
    update(
        adjustment,
        status="REVERSED",
        reversed_at=clock.now(),
        reversal_reason=reason,
    )
    for entry in adjustment["line_recoupments"]:
        line = db.claim_lines.get(entry["claim_line_id"])
        if line is None:
            continue
        update(line, recouped_cents=line["recouped_cents"] - entry["recoupment_cents"])
    remaining = [
        adj
        for adj in db.adjustments.values()
        if adj["redemption_claim_id"] == claim["id"] and adj["status"] == "APPLIED"
    ]
    if remaining:
        update(
            claim,
            net_payable_cents=claim["adjudicated_total_cents"]
            - sum(adj["recoupment_cents"] for adj in remaining),
        )
    else:
        update(
            claim,
            status="ADJUDICATED",
            net_payable_cents=claim["adjudicated_total_cents"],
        )
    if vendor is not None:
        update(
            vendor,
            recoupment_balance_cents=vendor["recoupment_balance_cents"]
            - adjustment["recoupment_cents"],
        )
    return adjustment


# ------------------------------------------------------------ sanction cases
def open_sanction_case(vendor, violation_code, source_visit_id, narrative, opened_by):
    schedule = calc.sanction_schedule(vendor, violation_code)
    case = models.sanction_case(
        vendor_id=vendor["id"],
        source_visit_id=source_visit_id,
        violation_code=violation_code,
        narrative=narrative,
        base_tier=schedule["base_tier"],
        case_points=schedule["case_points"],
        cumulative_points_at_open=schedule["cumulative_points_at_open"],
        effective_tier=schedule["effective_tier"],
        disqualification_months=schedule["disqualification_months"],
        cmp_amount_cents=schedule["cmp_amount_cents"],
        cmp_permitted=schedule["cmp_permitted"],
        opened_by_user_id=opened_by,
    )
    db.sanction_cases[case["id"]] = case
    return case


def disqualify_vendor(vendor, case):
    update(
        vendor,
        authorization_status="DISQUALIFIED",
        disqualified_until=clock.add_months(clock.now(), case["disqualification_months"]),
        sanction_points=vendor["sanction_points"] + case["case_points"],
    )
    sync_member_count(vendor["peer_group_id"])
    for visit in ordered(db.monitoring_visits):
        if visit["vendor_id"] != vendor["id"] or visit["status"] != "SCHEDULED":
            continue
        update(visit, status="CANCELLED", cancelled_reason="VENDOR_DISQUALIFIED")
    update(vendor, compliance_buy_required=False, reauthorization_hold=False)
    void_open_submissions(vendor, "VENDOR_DISQUALIFIED")


# ---------------------------------------------------------------- risk run
def risk_run():
    epoch = clock.now()
    vendors = [
        v
        for v in ordered(db.vendors)
        if v["authorization_status"] not in C.TERMINAL_VENDOR_STATUSES
    ]
    high = 0
    escalated = 0
    opened = 0
    for vendor in vendors:
        refresh_avg_redemption(vendor)
        components = calc.risk_components(vendor, epoch)
        update(
            vendor,
            risk_score=components["risk_score"],
            risk_tier=components["risk_tier"],
            risk_epoch_at=epoch,
        )
        if components["risk_tier"] == "HIGH":
            high += 1
            update(vendor, risk_flag="HIGH_SCORE", compliance_buy_required=True)

        failed = [
            v
            for v in db.monitoring_visits.values()
            if v["vendor_id"] == vendor["id"] and v["status"] == "FAILED"
        ]
        failed.sort(key=lambda v: (v["scheduled_for"], v["created_at"], v["_seq"]))
        for visit in failed:
            deadline = vendor["cure_deadline_at"]
            if deadline is None or clock.now() <= deadline:
                continue
            update(visit, status="ESCALATED")
            escalated += 1
            open_sanction_case(
                vendor, "CLASS_C", visit["id"], None, C.SYSTEM_USER_ID
            )
            opened += 1
            if vendor["authorization_status"] == "AUTHORIZED":
                update(vendor, authorization_status="SUSPENDED")
                sync_member_count(vendor["peer_group_id"])
    return {
        "epoch_at": epoch,
        "evaluated_vendor_count": len(vendors),
        "high_risk_vendor_count": high,
        "escalated_visit_count": escalated,
        "opened_sanction_case_count": opened,
    }
