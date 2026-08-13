"""Business logic: lookups, serializers, derived fields, cascades, calculations.

Implements the PRD section 3 workflows: plan lifecycle, enrollment lifecycle,
dividend pricing/execution, OCP windows and settlement, transfers/gifts,
termination settlement, basis relief (FIFO / AVERAGE_COST), and tax reporting.
"""
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal

from db import DB, clock_dt, logical_now_iso, new_id, next_seq
from errors import ApiError
from util import fmt_dt, parse_dt, round4, round_cents

# ---------------------------------------------------------------------------
# Enum vocabularies
# ---------------------------------------------------------------------------
PLAN_STATUSES = ("DRAFT", "ACTIVE", "SUSPENDED", "TERMINATED")
ENROLLMENT_STATUSES = ("PENDING", "ACTIVE", "SUSPENDED", "TERMINATED")
DIVIDEND_STATUSES = ("DECLARED", "PRICED", "REINVESTED", "SETTLED")
WINDOW_STATUSES = ("SCHEDULED", "OPEN", "CLOSED", "SETTLED")
ORDER_STATUSES = ("SUBMITTED", "SETTLED", "CANCELLED", "REJECTED")
NOTICE_STATUSES = ("DRAFT", "PUBLISHED", "EFFECTIVE")
NOTICE_TYPES = ("MODIFICATION", "SUSPENSION", "TERMINATION")
TRANSFER_STATUSES = ("SUBMITTED", "EXECUTED", "CANCELLED")
TRANSFER_TYPES = ("TRANSFER", "GIFT")
ENTRY_TYPES = (
    "INITIAL",
    "REINVEST",
    "CASH_PAYOUT",
    "OCP_PURCHASE",
    "FRACTIONAL_SALE",
    "WHOLE_SHARE_WITHDRAWAL",
    "TRANSFER_OUT",
    "TRANSFER_IN",
)
FEE_TYPES = ("ENROLLMENT", "OCP", "SALE", "TRANSFER")
ELECTIONS = ("FULL_REINVEST", "PARTIAL_REINVEST", "CASH_ONLY")
PRICING_BASES = ("MARKET_CLOSE", "FIVE_DAY_AVERAGE")
BASIS_METHODS = ("FIFO", "AVERAGE_COST")

MIN_NOTICE_DAYS = 10


# ---------------------------------------------------------------------------
# Common field helpers (PRD section 2.6)
# ---------------------------------------------------------------------------

def stamp(rec):
    """Set created_at/updated_at/version on a newly created primary resource."""
    t = logical_now_iso()
    rec["created_at"] = t
    rec["updated_at"] = t
    rec["version"] = 1
    rec["_seq"] = next_seq()


def stamp_immutable(rec):
    """Share ledger entries carry only id + created_at (no updated_at/version)."""
    rec["created_at"] = logical_now_iso()
    rec["_seq"] = next_seq()


def touch(rec):
    """Refresh updated_at and increment version by exactly 1."""
    rec["updated_at"] = logical_now_iso()
    rec["version"] += 1


def sorted_created(records):
    """Default list order: creation timestamp ascending (insertion tiebreak)."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def list_response(records, serializer):
    from response import ok_list
    from util import pagination_args

    limit, offset = pagination_args()
    items = sorted_created(list(records))
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([serializer(r) for r in page], total, limit, offset)


def filter_enum(records, raw, field, choices, param):
    if raw is None:
        return records
    if raw not in choices:
        raise ApiError(
            "ERR_VALIDATION", 400, f"{param} must be one of {sorted(choices)}"
        )
    return [r for r in records if r[field] == raw]


# ---------------------------------------------------------------------------
# Lookups (existence, hierarchical left-to-right)
# ---------------------------------------------------------------------------

def _lookup(store, rid, label):
    rec = DB[store].get(rid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"{label} not found")
    return rec


def get_plan(rid):
    return _lookup("plans", rid, "Plan")


def get_participant(rid):
    return _lookup("participants", rid, "Participant")


def get_enrollment(rid):
    return _lookup("enrollments", rid, "Enrollment")


def get_dividend(rid):
    return _lookup("dividend_events", rid, "DividendEvent")


def get_window(rid):
    return _lookup("purchase_windows", rid, "PurchaseWindow")


def get_order(rid):
    return _lookup("purchase_orders", rid, "PurchaseOrder")


def get_fee(rid):
    return _lookup("fee_assessments", rid, "FeeAssessment")


def get_notice(rid):
    return _lookup("notices", rid, "PlanNotice")


def get_transfer(rid):
    return _lookup("transfers", rid, "TransferInstruction")


def plan_enrollments(plan_id):
    return sorted_created(
        e for e in DB["enrollments"].values() if e["plan_id"] == plan_id
    )


def enrollment_lots(eid):
    return sorted_created(
        l for l in DB["tax_lots"].values() if l["enrollment_id"] == eid
    )


def enrollment_entries(eid):
    return sorted_created(
        x for x in DB["ledger_entries"].values() if x["enrollment_id"] == eid
    )


def window_orders(window_id):
    return sorted_created(
        o for o in DB["purchase_orders"].values() if o["window_id"] == window_id
    )


def enrollment_orders(eid):
    return sorted_created(
        o for o in DB["purchase_orders"].values() if o["enrollment_id"] == eid
    )


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def ser_plan(p):
    return {
        "id": p["id"],
        "issuer_name": p["issuer_name"],
        "ticker": p["ticker"],
        "name": p["name"],
        "status": p["status"],
        "discount_pct": p["discount_pct"],
        "pricing_basis": p["pricing_basis"],
        "basis_method": p["basis_method"],
        "ocp_min_cents": p["ocp_min_cents"],
        "ocp_max_cents": p["ocp_max_cents"],
        "ocp_fee_pct": p["ocp_fee_pct"],
        "ocp_fee_min_cents": p["ocp_fee_min_cents"],
        "sale_fee_cents": p["sale_fee_cents"],
        "transfer_fee_cents": p["transfer_fee_cents"],
        "enrollment_fee_cents": p["enrollment_fee_cents"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def ser_participant(p):
    return {
        "id": p["id"],
        "full_name": p["full_name"],
        "email": p["email"],
        "fee_waiver_eligible": p["fee_waiver_eligible"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def ser_enrollment(e):
    return {
        "id": e["id"],
        "participant_id": e["participant_id"],
        "plan_id": e["plan_id"],
        "status": e["status"],
        "election": e["election"],
        "reinvest_pct": e["reinvest_pct"],
        "share_balance": float(e["share_balance"]),
        "total_cost_basis_cents": e["total_cost_basis_cents"],
        "terminated_at": e["terminated_at"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def ser_dividend(ev):
    return {
        "id": ev["id"],
        "plan_id": ev["plan_id"],
        "amount_per_share_cents": ev["amount_per_share_cents"],
        "record_date": ev["record_date"],
        "payable_date": ev["payable_date"],
        "status": ev["status"],
        "closing_price_cents": ev["closing_price_cents"],
        "avg5_price_cents": ev["avg5_price_cents"],
        "reinvestment_price_cents": ev["reinvestment_price_cents"],
        "created_at": ev["created_at"],
        "updated_at": ev["updated_at"],
        "version": ev["version"],
    }


def ser_window(w):
    return {
        "id": w["id"],
        "plan_id": w["plan_id"],
        "opens_at": w["opens_at"],
        "closes_at": w["closes_at"],
        "price_cents": w["price_cents"],
        "status": w["status"],
        "submitted_total_cents": w["submitted_total_cents"],
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }


def ser_order(o):
    return {
        "id": o["id"],
        "window_id": o["window_id"],
        "enrollment_id": o["enrollment_id"],
        "amount_cents": o["amount_cents"],
        "status": o["status"],
        "settled_shares": (
            float(o["settled_shares"]) if o["settled_shares"] is not None else None
        ),
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def ser_ledger_entry(x):
    return {
        "id": x["id"],
        "enrollment_id": x["enrollment_id"],
        "entry_type": x["entry_type"],
        "quantity": float(x["quantity"]),
        "price_cents": x["price_cents"],
        "cash_cents": x["cash_cents"],
        "source_type": x["source_type"],
        "source_id": x["source_id"],
        "created_at": x["created_at"],
    }


def ser_tax_lot(lot):
    return {
        "id": lot["id"],
        "enrollment_id": lot["enrollment_id"],
        "acquired_at": lot["acquired_at"],
        "quantity": float(lot["quantity"]),
        "remaining_quantity": float(lot["remaining_quantity"]),
        "cost_per_share_cents": lot["cost_per_share_cents"],
        "total_basis_cents": lot["total_basis_cents"],
        "acquisition_type": lot["acquisition_type"],
        "created_at": lot["created_at"],
        "updated_at": lot["updated_at"],
        "version": lot["version"],
    }


def ser_fee(f):
    return {
        "id": f["id"],
        "enrollment_id": f["enrollment_id"],
        "fee_type": f["fee_type"],
        "computed_cents": f["computed_cents"],
        "waived": f["waived"],
        "waived_reason": f["waived_reason"],
        "charged_cents": f["charged_cents"],
        "source_type": f["source_type"],
        "source_id": f["source_id"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def ser_notice(n):
    return {
        "id": n["id"],
        "plan_id": n["plan_id"],
        "notice_type": n["notice_type"],
        "message": n["message"],
        "effective_at": n["effective_at"],
        "status": n["status"],
        "published_at": n["published_at"],
        "created_at": n["created_at"],
        "updated_at": n["updated_at"],
        "version": n["version"],
    }


def ser_transfer(t):
    return {
        "id": t["id"],
        "source_enrollment_id": t["source_enrollment_id"],
        "recipient_enrollment_id": t["recipient_enrollment_id"],
        "transfer_type": t["transfer_type"],
        "quantity": float(t["quantity"]),
        "recipient_name": t["recipient_name"],
        "recipient_address": t["recipient_address"],
        "status": t["status"],
        "fmv_per_share_cents": t["fmv_per_share_cents"],
        "executed_at": t["executed_at"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


# ---------------------------------------------------------------------------
# Bookkeeping primitives (PRD sections 2.9, 2.10)
# ---------------------------------------------------------------------------

def add_ledger_entry(enrollment_id, entry_type, quantity, price_cents, cash_cents,
                     source_type, source_id):
    rec = {
        "id": new_id(),
        "enrollment_id": enrollment_id,
        "entry_type": entry_type,
        "quantity": round4(quantity),
        "price_cents": price_cents,
        "cash_cents": cash_cents,
        "source_type": source_type,
        "source_id": source_id,
    }
    stamp_immutable(rec)
    DB["ledger_entries"][rec["id"]] = rec
    return rec


def add_tax_lot(enrollment_id, quantity, cost_per_share_cents, total_basis_cents,
                acquisition_type):
    rec = {
        "id": new_id(),
        "enrollment_id": enrollment_id,
        "acquired_at": logical_now_iso(),
        "quantity": round4(quantity),
        "remaining_quantity": round4(quantity),
        "cost_per_share_cents": cost_per_share_cents,
        "total_basis_cents": total_basis_cents,
        "acquisition_type": acquisition_type,
        "_relieved_basis": Decimal("0"),
    }
    stamp(rec)
    DB["tax_lots"][rec["id"]] = rec
    return rec


def add_fee(enrollment_id, fee_type, computed_cents, source_type, source_id,
            waived=False, waived_reason=None):
    rec = {
        "id": new_id(),
        "enrollment_id": enrollment_id,
        "fee_type": fee_type,
        "computed_cents": computed_cents,
        "waived": waived,
        "waived_reason": waived_reason,
        "charged_cents": 0 if waived else computed_cents,
        "source_type": source_type,
        "source_id": source_id,
    }
    stamp(rec)
    DB["fee_assessments"][rec["id"]] = rec
    return rec


def recompute_enrollment(e):
    """Derived position fields (PRD 2.9). Does not bump enrollment.version."""
    total = Decimal("0")
    for x in enrollment_entries(e["id"]):
        total += x["quantity"]
    e["share_balance"] = round4(total)
    lots = [l for l in enrollment_lots(e["id"]) if l["remaining_quantity"] > 0]
    basis = 0
    for lot in lots[:-1]:
        basis += round_cents(
            lot["remaining_quantity"] * Decimal(lot["cost_per_share_cents"])
        )
    if lots:
        # Last-lot remainder reconciliation keeps the total consistent with
        # the lots' recorded basis.
        last = lots[-1]
        basis += round_cents(
            Decimal(last["total_basis_cents"]) - last["_relieved_basis"]
        )
    e["total_cost_basis_cents"] = basis


def recompute_window_total(w):
    """submitted_total_cents is derived; reconciliation does not bump version."""
    w["submitted_total_cents"] = sum(
        o["amount_cents"]
        for o in DB["purchase_orders"].values()
        if o["window_id"] == w["id"] and o["status"] == "SUBMITTED"
    )


# ---------------------------------------------------------------------------
# disposition_basis_relief (calculation table; PRD section 3.9)
# ---------------------------------------------------------------------------

def _relief_order(lots):
    return sorted(
        lots, key=lambda l: (l["acquired_at"], l["created_at"], l["_seq"])
    )


def relieve_lots(enrollment, plan, quantity):
    """Relieve `quantity` (Decimal, > 0) of shares from the enrollment's lots
    under the plan's basis_method. Returns basis_out in integer cents."""
    quantity = round4(quantity)
    if quantity <= 0:
        return 0
    lots = [l for l in enrollment_lots(enrollment["id"]) if l["remaining_quantity"] > 0]
    if plan["basis_method"] == "FIFO":
        needed = quantity
        contribs = []
        for lot in _relief_order(lots):
            if needed <= 0:
                break
            take = min(needed, lot["remaining_quantity"])
            if take == lot["remaining_quantity"]:
                # Fully consumed: contribute the lot's un-relieved recorded
                # basis so repeated relief never drifts.
                contrib = Decimal(lot["total_basis_cents"]) - lot["_relieved_basis"]
            else:
                contrib = take * Decimal(lot["cost_per_share_cents"])
            lot["_relieved_basis"] += contrib
            lot["remaining_quantity"] = round4(lot["remaining_quantity"] - take)
            touch(lot)
            contribs.append(contrib)
            needed = round4(needed - take)
        return round_cents(sum(contribs, Decimal("0")))
    # AVERAGE_COST: single weighted average computed once over all lots with
    # remaining shares; pro-rata relief; oldest lot absorbs the 4dp residue.
    total_remaining = sum((l["remaining_quantity"] for l in lots), Decimal("0"))
    avg_cost = round_cents(
        sum(
            (
                l["remaining_quantity"] * Decimal(l["cost_per_share_cents"])
                for l in lots
            ),
            Decimal("0"),
        )
        / total_remaining
    )
    basis_out = round_cents(quantity * Decimal(avg_cost))
    ordered = _relief_order(lots)
    takes = [
        round4(quantity * l["remaining_quantity"] / total_remaining) for l in ordered
    ]
    residue = round4(quantity - sum(takes, Decimal("0")))
    if residue != 0 and ordered:
        for i, lot in enumerate(ordered):
            adjusted = takes[i] + residue
            if Decimal("0") <= adjusted <= lot["remaining_quantity"]:
                takes[i] = adjusted
                residue = Decimal("0")
                break
        if residue != 0:
            takes[0] = round4(takes[0] + residue)
    for lot, take in zip(ordered, takes):
        if take <= 0:
            continue
        take = min(take, lot["remaining_quantity"])
        lot["_relieved_basis"] += take * Decimal(avg_cost)
        lot["remaining_quantity"] = round4(lot["remaining_quantity"] - take)
        touch(lot)
    return basis_out


# ---------------------------------------------------------------------------
# Tax-report records (PRD section 3.9)
# ---------------------------------------------------------------------------

def record_disposition(enrollment_id, proceeds_cents, basis_cents):
    DB["_dispositions"].append(
        {
            "enrollment_id": enrollment_id,
            "year": clock_dt().year,
            "proceeds_cents": proceeds_cents,
            "basis_cents": basis_cents,
            "gain_cents": proceeds_cents - basis_cents,
        }
    )


def record_dividend_income(enrollment_id, payable_date_raw, amount_cents):
    DB["_dividend_income"].append(
        {
            "enrollment_id": enrollment_id,
            "year": parse_dt(payable_date_raw).year,
            "amount_cents": amount_cents,
        }
    )


def tax_report(e, year):
    plan = get_plan(e["plan_id"])
    dividends = sum(
        r["amount_cents"]
        for r in DB["_dividend_income"]
        if r["enrollment_id"] == e["id"] and r["year"] == year
    )
    disps = [
        r
        for r in DB["_dispositions"]
        if r["enrollment_id"] == e["id"] and r["year"] == year
    ]
    proceeds = sum(d["proceeds_cents"] for d in disps)
    basis = sum(d["basis_cents"] for d in disps)
    return {
        "year": year,
        "dividends_cents": dividends,
        "proceeds_cents": proceeds,
        "basis_cents": basis,
        "gain_cents": proceeds - basis,
        "basis_method": plan["basis_method"],
    }


# ---------------------------------------------------------------------------
# termination_settlement (calculation table; PRD section 3.9)
# ---------------------------------------------------------------------------

def terminate_enrollment(e, sale_price_cents):
    """Full enrollment termination cascade: fractional sale (only when the
    fractional part is > 0), whole-share withdrawal, full lot relief, SALE fee,
    terminated_at stamp, version increment."""
    plan = get_plan(e["plan_id"])
    balance = e["share_balance"]
    whole = int(balance)  # floor; balance is non-negative
    frac = round4(balance - Decimal(whole))
    if frac > 0:
        # Pinned rounding order: gross rounded first, fee subtracted after.
        gross = round_cents(frac * Decimal(sale_price_cents))
        fee = plan["sale_fee_cents"]
        net = gross - fee
        add_ledger_entry(
            e["id"], "FRACTIONAL_SALE", -frac, sale_price_cents, net,
            "TERMINATION", e["id"],
        )
        add_fee(e["id"], "SALE", fee, "TERMINATION", e["id"])
        basis = relieve_lots(e, plan, frac)
        record_disposition(e["id"], gross, basis)
    if whole > 0:
        add_ledger_entry(
            e["id"], "WHOLE_SHARE_WITHDRAWAL", Decimal(-whole), None, None,
            "TERMINATION", e["id"],
        )
        relieve_lots(e, plan, Decimal(whole))
    e["status"] = "TERMINATED"
    e["terminated_at"] = logical_now_iso()
    touch(e)
    recompute_enrollment(e)


# ---------------------------------------------------------------------------
# Plan cascades (PRD sections 3.1, 3.7)
# ---------------------------------------------------------------------------

def suspend_plan(plan):
    plan["status"] = "SUSPENDED"
    touch(plan)
    for e in plan_enrollments(plan["id"]):
        if e["status"] != "ACTIVE":
            continue
        e["status"] = "SUSPENDED"
        touch(e)
        for o in enrollment_orders(e["id"]):
            if o["status"] != "SUBMITTED":
                continue
            o["status"] = "REJECTED"
            touch(o)
            w = DB["purchase_windows"].get(o["window_id"])
            if w is not None:
                recompute_window_total(w)


def resume_plan(plan):
    """Asymmetric compensation: REJECTED orders are NOT restored."""
    plan["status"] = "ACTIVE"
    touch(plan)
    for e in plan_enrollments(plan["id"]):
        if e["status"] == "SUSPENDED":
            e["status"] = "ACTIVE"
            touch(e)


def terminate_plan(plan, sale_price_cents=0):
    for e in plan_enrollments(plan["id"]):
        if e["status"] in ("PENDING", "ACTIVE", "SUSPENDED"):
            terminate_enrollment(e, sale_price_cents)
    plan["status"] = "TERMINATED"
    touch(plan)


# ---------------------------------------------------------------------------
# Dividend processing (PRD section 3.4; reinvestment_allocation /
# dividend_cash_split calculations)
# ---------------------------------------------------------------------------

def execute_dividend(event):
    plan = get_plan(event["plan_id"])
    # Holders of record at end of the record date (23:59:59Z) are eligible.
    record_end = datetime.combine(
        parse_dt(event["record_date"]).date(),
        time(23, 59, 59, 999999),
        tzinfo=timezone.utc,
    )
    for e in plan_enrollments(plan["id"]):
        if e["status"] != "ACTIVE":
            continue
        eligible = Decimal("0")
        for x in enrollment_entries(e["id"]):
            if parse_dt(x["created_at"]) <= record_end:
                eligible += x["quantity"]
        eligible = round4(eligible)
        if eligible <= 0:
            continue
        total_cash = round_cents(
            eligible * Decimal(event["amount_per_share_cents"])
        )
        # dividend_cash_split: reinvested portion rounded first; the cash
        # payout takes the remainder so the two sum exactly to the total.
        if e["election"] == "FULL_REINVEST":
            reinvest, payout = total_cash, 0
        elif e["election"] == "CASH_ONLY":
            reinvest, payout = 0, total_cash
        else:
            reinvest = round_cents(
                Decimal(total_cash) * Decimal(str(e["reinvest_pct"]))
            )
            payout = total_cash - reinvest
        if reinvest > 0:
            shares = round4(
                Decimal(reinvest) / Decimal(event["reinvestment_price_cents"])
            )
            add_ledger_entry(
                e["id"], "REINVEST", shares, event["reinvestment_price_cents"],
                None, "DIVIDEND", event["id"],
            )
            # REINVEST lot basis equals the actual cash reinvested.
            add_tax_lot(
                e["id"], shares, event["reinvestment_price_cents"], reinvest,
                "REINVEST",
            )
        if payout > 0:
            add_ledger_entry(
                e["id"], "CASH_PAYOUT", Decimal("0"), None, payout,
                "DIVIDEND", event["id"],
            )
        recompute_enrollment(e)
        record_dividend_income(e["id"], event["payable_date"], total_cash)
    event["status"] = "REINVESTED"
    touch(event)


# ---------------------------------------------------------------------------
# OCP window settlement (PRD section 3.5; ocp_fee_assessment calculation)
# ---------------------------------------------------------------------------

def settle_window(window):
    plan = get_plan(window["plan_id"])
    for o in window_orders(window["id"]):
        if o["status"] != "SUBMITTED":
            continue
        e = get_enrollment(o["enrollment_id"])
        participant = get_participant(e["participant_id"])
        computed = max(
            plan["ocp_fee_min_cents"],
            round_cents(
                Decimal(o["amount_cents"]) * Decimal(str(plan["ocp_fee_pct"]))
            ),
        )
        if participant["fee_waiver_eligible"]:
            fee = add_fee(
                e["id"], "OCP", computed, "WINDOW", o["id"],
                waived=True, waived_reason="AUTO_ELIGIBLE",
            )
        else:
            fee = add_fee(e["id"], "OCP", computed, "WINDOW", o["id"])
        charged = fee["charged_cents"]
        settled = round4(
            Decimal(o["amount_cents"] - charged) / Decimal(window["price_cents"])
        )
        o["settled_shares"] = settled
        o["status"] = "SETTLED"
        touch(o)
        add_ledger_entry(
            e["id"], "OCP_PURCHASE", settled, window["price_cents"], None,
            "WINDOW", o["id"],
        )
        add_tax_lot(
            e["id"], settled, window["price_cents"],
            o["amount_cents"] - charged, "OCP",
        )
        recompute_enrollment(e)
    window["status"] = "SETTLED"
    recompute_window_total(window)
    touch(window)


# ---------------------------------------------------------------------------
# Transfer execution (PRD section 3.8)
# ---------------------------------------------------------------------------

def execute_transfer(instr, fmv_per_share_cents):
    source = get_enrollment(instr["source_enrollment_id"])
    plan = get_plan(source["plan_id"])
    q = instr["quantity"]
    add_ledger_entry(
        source["id"], "TRANSFER_OUT", -q, fmv_per_share_cents, None,
        "TRANSFER", instr["id"],
    )
    basis_out = relieve_lots(source, plan, q)
    if instr["transfer_type"] == "TRANSFER":
        recipient = get_enrollment(instr["recipient_enrollment_id"])
        add_ledger_entry(
            recipient["id"], "TRANSFER_IN", q, fmv_per_share_cents, None,
            "TRANSFER", instr["id"],
        )
        # TRANSFER_IN lot carries over the per-share basis relieved at source.
        carried = round_cents(Decimal(basis_out) / q)
        add_tax_lot(recipient["id"], q, carried, basis_out, "TRANSFER_IN")
        recompute_enrollment(recipient)
    add_fee(
        source["id"], "TRANSFER", plan["transfer_fee_cents"], "TRANSFER",
        instr["id"],
    )
    proceeds = round_cents(q * Decimal(fmv_per_share_cents))
    record_disposition(source["id"], proceeds, basis_out)
    recompute_enrollment(source)
    instr["status"] = "EXECUTED"
    instr["fmv_per_share_cents"] = fmv_per_share_cents
    instr["executed_at"] = logical_now_iso()
    touch(instr)


# ---------------------------------------------------------------------------
# Notices
# ---------------------------------------------------------------------------

def auto_create_modification_notice(plan):
    """PATCH on an ACTIVE plan auto-creates a DRAFT MODIFICATION notice."""
    rec = {
        "id": new_id(),
        "plan_id": plan["id"],
        "notice_type": "MODIFICATION",
        "message": "Plan configuration modified.",
        "effective_at": fmt_dt(clock_dt() + timedelta(days=MIN_NOTICE_DAYS)),
        "status": "DRAFT",
        "published_at": None,
    }
    stamp(rec)
    DB["notices"][rec["id"]] = rec
    return rec


# ---------------------------------------------------------------------------
# Election payload rule (PRD section 3.2; ERR_INVALID_ELECTION)
# ---------------------------------------------------------------------------

def election_payload(data, election):
    """reinvest_pct present and in (0,1) iff PARTIAL_REINVEST; absent otherwise.
    Returns the reinvest_pct value to store (original number) or None."""
    has_pct = "reinvest_pct" in data and data["reinvest_pct"] is not None
    if election == "PARTIAL_REINVEST":
        if not has_pct:
            raise ApiError(
                "ERR_INVALID_ELECTION",
                422,
                "reinvest_pct is required for PARTIAL_REINVEST",
            )
        pct = None
        try:
            from util import as_decimal

            pct = as_decimal(
                data["reinvest_pct"], "reinvest_pct",
                error_id="ERR_INVALID_ELECTION", status=422,
            )
        except ApiError:
            raise
        if not (Decimal("0") < pct < Decimal("1")):
            raise ApiError(
                "ERR_INVALID_ELECTION",
                422,
                "reinvest_pct must be strictly between 0 and 1",
            )
        return data["reinvest_pct"]
    if has_pct:
        raise ApiError(
            "ERR_INVALID_ELECTION",
            422,
            "reinvest_pct must be absent unless election is PARTIAL_REINVEST",
        )
    return None
