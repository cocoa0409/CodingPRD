"""Shared derivations, recomputations and multi-hop cascades."""
from decimal import Decimal

from flask import g

import calc
from core import (ApiError, D0, add_days, db, deal_allocations, deal_batches,
                  deal_conditions, deal_instruments, deal_periods,
                  deal_risk_events, new_id, next_seq, now, q, touch)


def base_row():
    stamp = now()
    return {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": next_seq(),
    }


# ------------------------------------------------------------ offtaker scoring
def guarantor_of(offtaker):
    parent_id = offtaker.get("parent_guarantor_offtaker_id")
    if parent_id is None:
        return None
    return db.offtakers.get(parent_id)


def score_offtaker(offtaker):
    """Recompute the whole scoring chain on one Offtaker row (no version bump)."""
    score, variant, tier = calc.offtaker_credit_score(offtaker,
                                                      guarantor_of(offtaker))
    offtaker["credit_score"] = score
    offtaker["credit_score_variant"] = variant
    offtaker["credit_tier"] = tier
    offtaker["sustainability_score"] = calc.offtaker_sustainability_score(offtaker)
    offtaker["unsecured_credit_limit_usd"] = calc.unsecured_credit_limit(
        tier, offtaker["reported_ebitda_usd"])


def score_offtaker_credit_only(offtaker):
    """Rating-change cascade hop 1/4: credit figures only."""
    score, variant, tier = calc.offtaker_credit_score(offtaker,
                                                      guarantor_of(offtaker))
    offtaker["credit_score"] = score
    offtaker["credit_score_variant"] = variant
    offtaker["credit_tier"] = tier
    offtaker["unsecured_credit_limit_usd"] = calc.unsecured_credit_limit(
        tier, offtaker["reported_ebitda_usd"])


def check_guarantor_cycle(offtaker_id, proposed_parent_id):
    if proposed_parent_id is None:
        return
    if proposed_parent_id == offtaker_id:
        raise ApiError("ERR_GUARANTOR_CYCLE",
                       "an offtaker may not guarantee itself")
    seen = set()
    cursor = db.offtakers.get(proposed_parent_id)
    while cursor is not None:
        if cursor["id"] == offtaker_id:
            raise ApiError("ERR_GUARANTOR_CYCLE",
                           "the guarantor chain would close a cycle")
        if cursor["id"] in seen:
            return
        seen.add(cursor["id"])
        cursor = db.offtakers.get(cursor.get("parent_guarantor_offtaker_id"))


# ------------------------------------------------------------------- projects
def recompute_project_capacity(project, always_touch=False):
    contracted = D0
    for deal in db.deals.values():
        if deal["project_id"] == project["id"] and deal["status"] in (
                "EXECUTED", "EFFECTIVE"):
            contracted += Decimal(deal["contracted_mw"])
    contracted = q(contracted, 3)
    available = q(Decimal(project["capacity_mw"]) - contracted, 3)
    changed = (project.get("contracted_mw") != contracted
               or project.get("available_mw") != available)
    project["contracted_mw"] = contracted
    project["available_mw"] = available
    if changed or always_touch:
        touch(project)


# ---------------------------------------------------------------- deal totals
def recompute_alloc_totals(deal):
    confirmed = D0
    live = D0
    for alloc in db.allocations.values():
        if alloc["deal_id"] != deal["id"]:
            continue
        if alloc["status"] == "CONFIRMED":
            confirmed += Decimal(alloc["allocated_mw"])
        if alloc["status"] in ("PROPOSED", "CONFIRMED"):
            live += Decimal(alloc["allocated_mw"])
    deal["confirmed_allocated_mw"] = q(confirmed, 3)
    deal["unallocated_mw"] = q(Decimal(deal["contracted_mw"]) - live, 3)


def recompute_support_totals(deal):
    posted = D0
    released = D0
    drawn = D0
    for inst in db.instruments.values():
        if inst["deal_id"] != deal["id"]:
            continue
        amount = Decimal(inst.get("eligible_credit_usd") or 0)
        if inst["status"] == "POSTED":
            posted += amount
        elif inst["status"] == "RELEASED":
            released += amount
        elif inst["status"] == "DRAWN":
            drawn += amount
    deal["posted_credit_support_usd"] = q(posted, 2)
    deal["released_credit_support_usd"] = q(released, 2)
    deal["drawn_credit_support_usd"] = q(drawn, 2)


def recompute_attribute_totals(deal):
    minted = 0
    transferred = 0
    retired = 0
    for batch in db.batches.values():
        if batch["deal_id"] != deal["id"]:
            continue
        qty = int(batch["quantity_mwh"])
        if batch["status"] in ("MINTED", "TRANSFERRED", "RETIRED"):
            minted += qty
        if batch["status"] in ("TRANSFERRED", "RETIRED"):
            transferred += qty
        if batch["status"] == "RETIRED":
            retired += qty
    deal["attributes_minted_mwh"] = minted
    deal["attributes_transferred_mwh"] = transferred
    deal["attributes_retired_mwh"] = retired


def recompute_cp_totals(deal):
    conditions = deal_conditions(deal["id"])
    deal["cp_total_count"] = len(conditions)
    deal["cp_completion_pct"] = calc.cp_completion_pct(conditions)


def resize_deal_credit(deal, offtaker, snapshot=True):
    """Re-snapshot the buyer's limit and re-size the collateral requirement."""
    project = db.projects.get(deal["project_id"])
    if snapshot and offtaker is not None:
        limit = offtaker.get("unsecured_credit_limit_usd")
        deal["unsecured_credit_limit_usd"] = limit
        deal["collateral_threshold_usd"] = limit
    if project is not None:
        deal["expected_annual_mwh"] = calc.deal_expected_volume(
            deal["contracted_mw"], project["technology"])
    price = deal.get("contract_price_usd_per_mwh")
    if price is None or deal.get("expected_annual_mwh") is None:
        return
    exposure, required = calc.credit_support_requirement(
        deal["expected_annual_mwh"], price,
        deal.get("collateral_threshold_usd") or 0)
    deal["exposure_usd"] = exposure
    deal["credit_support_required_usd"] = required


# ------------------------------------------------------- effectiveness cascade
def release_development_security(deal):
    for inst in deal_instruments(deal["id"]):
        if (inst["purpose"] == "DEVELOPMENT_SECURITY"
                and inst["status"] == "POSTED"):
            inst["status"] = "RELEASED"
            inst["closed_at"] = now()
            touch(inst)
    recompute_support_totals(deal)


def maybe_effective(deal):
    """EXECUTED -> EFFECTIVE once cp_completion_pct reaches exactly 100.00."""
    if deal["status"] != "EXECUTED":
        return
    if deal.get("cp_completion_pct") != q(Decimal("100"), 2):
        return
    deal["status"] = "EFFECTIVE"
    deal["effective_at"] = now()
    release_development_security(deal)
    touch(deal)


def open_shortfall(deal):
    """APPROVED -> SUPPORT_SHORTFALL when a resize outgrew the posted support."""
    if deal.get("credit_status") != "APPROVED":
        return
    posted = Decimal(deal.get("posted_credit_support_usd") or 0)
    required = Decimal(deal.get("credit_support_required_usd") or 0)
    if posted < required:
        deal["credit_status"] = "SUPPORT_SHORTFALL"
        deal["support_cure_deadline"] = add_days(now(), calc.SUPPORT_CURE_DAYS)
        touch(deal)


def anchored_deals(offtaker_id, statuses=None):
    rows = [d for d in db.deals.values()
            if d["anchor_offtaker_id"] == offtaker_id]
    if statuses is not None:
        rows = [d for d in rows if d["status"] in statuses]
    rows.sort(key=lambda d: (d["created_at"], d["_seq"]))
    return rows


def decline_anchored_deals(offtaker_id):
    for deal in anchored_deals(offtaker_id,
                              ("DRAFT", "TERM_SHEET_ISSUED",
                               "UNDER_NEGOTIATION")):
        deal["credit_status"] = "DECLINED"
        touch(deal)


RESIZE_STATUSES = ("TERMS_AGREED", "EXECUTED", "EFFECTIVE")


def cascade_downgrade(offtaker):
    """rating-change QUALIFIED -> WATCHLIST, hops 2 to 4."""
    for deal in anchored_deals(offtaker["id"], RESIZE_STATUSES):
        resize_deal_credit(deal, offtaker)
        open_shortfall(deal)
        touch(deal)
    cascade_guarantor_children(offtaker)


def cascade_guarantor_children(offtaker):
    children = [o for o in db.offtakers.values()
                if o.get("parent_guarantor_offtaker_id") == offtaker["id"]
                and o.get("credit_score_variant") == "GUARANTOR_SUPPORTED"]
    children.sort(key=lambda o: (o["created_at"], o["_seq"]))
    for child in children:
        score_offtaker_credit_only(child)
        touch(child)


def cascade_recovery(offtaker):
    """rating-change WATCHLIST -> QUALIFIED."""
    for deal in anchored_deals(offtaker["id"], RESIZE_STATUSES):
        resize_deal_credit(deal, offtaker)
        if deal.get("credit_status") == "SUPPORT_SHORTFALL":
            posted = Decimal(deal.get("posted_credit_support_usd") or 0)
            required = Decimal(deal.get("credit_support_required_usd") or 0)
            if posted >= required:
                deal["credit_status"] = "APPROVED"
                deal["support_cure_deadline"] = None
        touch(deal)


def cascade_same_band(offtaker):
    """Tier unchanged: every non-terminated anchored deal still re-sizes."""
    for deal in anchored_deals(offtaker["id"]):
        if deal["status"] == "TERMINATED":
            continue
        resize_deal_credit(deal, offtaker)
        touch(deal)


# --------------------------------------------------------- project milestones
def project_cp_cascade(project, cp_type, evidence_ref):
    """Milestone hops 2 to 5: clear matching CPs on this project's EXECUTED deals."""
    deals = [d for d in db.deals.values()
             if d["project_id"] == project["id"] and d["status"] == "EXECUTED"]
    deals.sort(key=lambda d: (d["created_at"], d["_seq"]))
    for deal in deals:
        hit = False
        for cond in deal_conditions(deal["id"]):
            if cond["cp_type"] == cp_type and cond["status"] == "PENDING":
                cond["status"] = "SATISFIED"
                cond["evidence_ref"] = evidence_ref
                cond["resolved_at"] = now()
                touch(cond)
                hit = True
        if not hit:
            continue
        recompute_cp_totals(deal)
        touch(deal)
        maybe_effective(deal)


# ------------------------------------------------------ conditions precedent
def create_conditions(deal, project, offtaker):
    rows = calc.cp_template_selection(project["status"],
                                      offtaker.get("registry_account_id"),
                                      deal["commercial_operation_deadline"],
                                      now())
    for cp_type, deadline, waivable in rows:
        row = base_row()
        row.update({
            "deal_id": deal["id"],
            "cp_type": cp_type,
            "status": "PENDING",
            "deadline_date": deadline,
            "is_waivable": waivable,
            "evidence_ref": None,
            "waiver_justification": None,
            "resolved_at": None,
            "resolved_by_user_id": None,
            "cure_deadline": None,
        })
        db.conditions[row["id"]] = row
    recompute_cp_totals(deal)


# -------------------------------------------------------------- terminations
def termination_right_vested(deal, reason):
    clock = now()
    if reason == "CP_FAILURE":
        for cond in deal_conditions(deal["id"]):
            if cond["status"] != "FAILED":
                continue
            cure = cond.get("cure_deadline")
            if cure is None or cure < clock:
                return True
        return False
    if reason == "BUYER_DEFAULT":
        cure = deal.get("support_cure_deadline")
        return (deal.get("credit_status") == "SUPPORT_SHORTFALL"
                and cure is not None and cure < clock)
    if reason == "SELLER_DEFAULT":
        project = db.projects.get(deal["project_id"])
        return (clock > deal["commercial_operation_deadline"]
                and project is not None
                and project["status"] != "OPERATIONAL")
    if reason == "COD_DEADLINE_MISSED":
        return (clock > deal["commercial_operation_deadline"]
                and deal["status"] != "EFFECTIVE")
    if reason == "EXTENDED_FORCE_MAJEURE":
        for event in deal_risk_events(deal["id"]):
            if (event["status"] == "ACCEPTED"
                    and event["event_type"] == "FORCE_MAJEURE"
                    and (event.get("duration_days") or 0)
                    >= calc.FM_TERMINATION_DAYS):
                return True
        return False
    return False


def termination_cascade(deal):
    """Hops 2/2b/2c and their recomputations for an EXECUTED or EFFECTIVE deal."""
    stamp = now()
    for cond in deal_conditions(deal["id"]):
        if cond["status"] == "PENDING":
            cond["status"] = "FAILED"
            cond["resolved_at"] = stamp
            cond["cure_deadline"] = None
            touch(cond)
    recompute_cp_totals(deal)

    drawn = deal.get("termination_reason") == "BUYER_DEFAULT"
    for inst in deal_instruments(deal["id"]):
        if inst["status"] == "POSTED":
            inst["status"] = "DRAWN" if drawn else "RELEASED"
            inst["closed_at"] = stamp
            touch(inst)
    recompute_support_totals(deal)

    for batch in deal_batches(deal["id"]):
        if batch["status"] == "MINTED":
            batch["status"] = "CANCELLED"
            touch(batch)
    recompute_attribute_totals(deal)


# --------------------------------------------------------------- settlement
def deal_intervals(deal_id):
    """Every MeterInterval under any SettlementPeriod of the deal."""
    period_ids = set(p["id"] for p in db.periods.values()
                     if p["deal_id"] == deal_id)
    rows = [i for i in db.intervals.values()
            if i["settlement_period_id"] in period_ids]
    rows.sort(key=lambda i: (i["hour_start"], i["_seq"]))
    return rows


def covering_curtailment_event(deal_id, hour_start):
    for event in deal_risk_events(deal_id):
        if (event["status"] == "ACCEPTED"
                and event["event_type"] == "CURTAILMENT"
                and event["window_start"] <= hour_start <= event["window_end"]):
            return event
    return None


def recompute_period(period):
    """The full settlement run for one period."""
    deal = db.deals[period["deal_id"]]
    project = db.projects[deal["project_id"]]
    node = db.pricing_nodes.get(deal["settlement_point_id"])
    point_type = node["settlement_point_type"] if node else "HUB"
    intervals = [i for i in db.intervals.values()
                 if i["settlement_period_id"] == period["id"]]
    intervals.sort(key=lambda i: (i["hour_start"], i["_seq"]))

    for interval in intervals:
        event = covering_curtailment_event(deal["id"], interval["hour_start"])
        expected, deemed, delivered = calc.deemed_generation(
            interval, deal["contracted_mw"], project["technology"], event)
        interval["expected_mwh"] = expected
        interval["deemed_mwh"] = deemed
        interval["delivered_mwh"] = delivered
        touch(interval)

    totals = calc.settlement_netting(intervals, period["netting_method"],
                                     deal["contract_price_usd_per_mwh"],
                                     deal["basis_responsibility"], point_type)
    period.update(totals)
    period["mintable_attributes_mwh"] = calc.mintable_attributes(
        period["total_metered_mwh"])
    period["calculated_at"] = now()


def apply_risk_impact(event):
    event["duration_days"] = calc.risk_event_duration_days(
        event["window_start"], event["window_end"])
    hours = 0
    for interval in deal_intervals(event["deal_id"]):
        if event["window_start"] <= interval["hour_start"] <= event["window_end"]:
            hours += 1
    event["excused_hours"] = hours
