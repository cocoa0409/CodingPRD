"""Multi-row side effects: the three cascades, the settlement recomputation and
the shared agreement-suspension footprint."""
from decimal import Decimal

import config
from db import db
from numeric import D
from services import calc, derive
from validation import date_of

ZERO = Decimal("0")


# --------------------------------------------------------------- settlement
def issued_credit_revenue(facility_id, period_start, period_end):
    total = 0
    for b in db.batches.values():
        if b["facility_id"] != facility_id or b["status"] != "ISSUED":
            continue
        if date_of(b["period_start_date"]) >= period_start and \
                date_of(b["period_end_date"]) <= period_end:
            total += int(b["credit_value_cents"] or 0)
    return total


def participating_agreements(facility_id, period_start, period_end):
    rows = []
    for a in db.agreements.values():
        if a["facility_id"] != facility_id or a["status"] != "ACTIVE":
            continue
        if date_of(a["term_start_date"]) <= period_end and \
                date_of(a["term_end_date"]) >= period_start:
            rows.append(a)
    rows.sort(key=lambda r: (-D(r["committed_tonnes_per_day"]), r["_created"], r["_seq"]))
    return rows


def compute_statement(stmt):
    """Runs the waterfall, the share allocation and the covenant ratio, in order."""
    facility = db.facilities[stmt["facility_id"]]
    start = date_of(stmt["period_start_date"])
    end = date_of(stmt["period_end_date"])

    credit_revenue = issued_credit_revenue(facility["id"], start, end)
    wf = calc.net_distributable_waterfall(
        stmt["gas_revenue_cents"], credit_revenue,
        facility["reserve_target_cents"], facility["reserve_balance_cents"])
    stmt["credit_revenue_cents"] = credit_revenue
    stmt.update(wf)

    lines, total, retained = calc.dairy_share_allocation(
        participating_agreements(facility["id"], start, end),
        wf["net_distributable_cents"], wf["gross_revenue_cents"])
    stmt["share_lines"] = lines
    stmt["total_dairy_share_cents"] = total
    stmt["retained_cents"] = retained

    stmt["dscr_at_close"] = calc.dscr_value(
        wf["after_fee_cents"], facility["annual_debt_service_cents"])
    return stmt


def recompute_draft_statements_for_batches(facility_id, batches):
    """Cascade tail: DRAFT statements whose period contains an affected batch."""
    if not batches:
        return
    targets = []
    for s in db.statements.values():
        if s["facility_id"] != facility_id or s["status"] != "DRAFT":
            continue
        s_start = date_of(s["period_start_date"])
        s_end = date_of(s["period_end_date"])
        for b in batches:
            if s_start <= date_of(b["period_start_date"]) and \
                    date_of(b["period_end_date"]) <= s_end:
                targets.append(s)
                break
    if not targets:
        return
    targets.sort(key=lambda r: (r["_created"], r["_seq"]))
    for s in targets:
        compute_statement(s)
        db.touch(s)
    facility = db.facilities[facility_id]
    if derive.rederive_dscr_from_driver(facility):
        db.touch(facility)


# --------------------------------------------------- agreement suspension
def suspend_agreement(agreement, reason):
    """Shared footprint of an operator SUSPEND and of the UPSET sweep."""
    agreement["status"] = "SUSPENDED"
    agreement["suspension_reason"] = reason
    db.touch(agreement)

    dairy = db.dairies.get(agreement["dairy_id"])
    if dairy is not None:
        db.touch(dairy)

    affected_days = {}
    for d in db.deliveries.values():
        if d["agreement_id"] != agreement["id"] or d["status"] != "ACCEPTED":
            continue
        day = db.ops_days.get(d["ops_day_id"])
        if day is None or day["status"] != "OPEN":
            continue
        d["status"] = "CANCELLED"
        d["rejection_reason"] = "AGREEMENT_SUSPENDED"
        db.touch(d)
        affected_days[day["id"]] = day
    for day in sorted(affected_days.values(), key=lambda r: (r["_created"], r["_seq"])):
        derive.recompute_day_olr(day)
        db.touch(day)


# ------------------------------------------------------ cascade B: ops upset
def cascade_biological_upset(facility):
    rows = [a for a in db.agreements.values()
            if a["facility_id"] == facility["id"] and a["status"] == "ACTIVE"
            and a["curtailable"]]
    rows.sort(key=lambda r: (r["_created"], r["_seq"]))
    for agreement in rows:
        suspend_agreement(agreement, "OPS_UPSET")


# ----------------------------------------------------- cascade C: off-spec gas
def cascade_offspec_retest(day):
    rows = [n for n in db.nominations.values()
            if n["ops_day_id"] == day["id"] and n["status"] in ("NOMINATED", "CONFIRMED")]
    rows.sort(key=lambda r: (r["_created"], r["_seq"]))
    per_interconnect = {}
    for nom in rows:
        nom["status"] = "REJECTED_OFFSPEC"
        db.touch(nom)
        per_interconnect[nom["interconnect_id"]] = per_interconnect.get(nom["interconnect_id"], 0) + 1
    for ic_id, count in per_interconnect.items():
        ic = db.interconnects.get(ic_id)
        if ic is None:
            continue
        ic["curtailment_count"] += count
        if ic["status"] == "ACTIVE" and ic["curtailment_count"] >= config.CURTAILMENT_SUSPEND_THRESHOLD:
            ic["status"] = "SUSPENDED"
        db.touch(ic)


def bump_curtailment(interconnect, count=1):
    interconnect["curtailment_count"] += count
    if interconnect["status"] == "ACTIVE" and \
            interconnect["curtailment_count"] >= config.CURTAILMENT_SUSPEND_THRESHOLD:
        interconnect["status"] = "SUSPENDED"


# --------------------------------------------- cascade A: material CI finding
def recompute_batch_final(batch, pathway):
    ci = pathway["verified_ci_score"]
    if ci is None:
        ci = pathway["certified_ci_score"]
    qty, value = calc.credit_quantity(pathway["program"], ci, batch["delivered_mmbtu"])
    batch["ci_score_used"] = D(ci)
    batch["credit_quantity_final"] = qty
    batch["credit_value_cents"] = value


def cascade_material_finding(pathway):
    """Revalue every VERIFIED / ISSUED batch, then the DRAFT statements behind them."""
    rows = [b for b in derive.batches_of_pathway(pathway["id"])
            if b["status"] in ("VERIFIED", "ISSUED")]
    rows.sort(key=lambda r: (r["_created"], r["_seq"]))
    issued_touched = []
    for batch in rows:
        recompute_batch_final(batch, pathway)
        db.touch(batch)
        if batch["status"] == "ISSUED":
            issued_touched.append(batch)
    recompute_draft_statements_for_batches(pathway["facility_id"], issued_touched)
