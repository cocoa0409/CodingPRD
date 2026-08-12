"""Routes: builders, lot purchase agreements, takedown tranches, lots, closings."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

from core import (
    DB, actor, require_roles, body, check_no_undeclared, req_string, req_int,
    req_number, req_datetime, opt_int, opt_id, validation, err, invalid_state,
    new_entity, touch, get_or_404, check_body_fk, CURE_PERIOD_DAYS,
    RESCISSION_WINDOW_DAYS, round_half_up_int, add_years, ok_object, filter_args,
)
from serializers import (
    builder_out, agreement_out, tranche_out, lot_out, closing_out,
    compute_tranche_penalty,
)
from routes_core import paginate_pairs
import domain

bp = Blueprint("agreements", __name__)

EXEC = ["DeclarantExecutive"]
CTRL = ["DeclarantController"]


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------
@bp.route("/mpc/builders", methods=["POST"])
def create_builder():
    _, role = actor()
    require_roles(role, EXEC)
    data = body()
    community = check_body_fk("community", DB.communities, data.get("community_id"))
    check_no_undeclared(data, {"community_id", "legal_name", "credit_tier"})
    req_string(data, "community_id")
    name = req_string(data, "legal_name")
    tier = data.get("credit_tier")
    if tier not in ("A", "B", "C"):
        validation("credit_tier must be one of A, B, C")
    b = new_entity()
    b.update({
        "community_id": community["id"],
        "legal_name": name,
        "credit_tier": tier,
        "standing": "GOOD_STANDING",
        "total_lots_purchased": 0,
    })
    DB.builders[b["id"]] = b
    return ok_obj(b)


def ok_obj(b, code=201):
    return ok_object(builder_out(b), code)


@bp.route("/mpc/builders", methods=["GET"])
def list_builders():
    actor()
    f = filter_args(["community_id"])
    raw = [b for b in DB.builders.values()
           if f.get("community_id") in (None, b["community_id"])]
    return paginate_pairs(raw, builder_out)


@bp.route("/mpc/builders/<bid>", methods=["GET"])
def get_builder(bid):
    actor()
    b = get_or_404("builder", DB.builders, bid)
    return ok_object(builder_out(b))


@bp.route("/mpc/builders/<bid>/reinstate", methods=["POST"])
def reinstate_builder(bid):
    _, role = actor()
    require_roles(role, EXEC)
    b = get_or_404("builder", DB.builders, bid)
    data = body()
    check_no_undeclared(data, set())
    if b["standing"] not in ("PROBATION", "SUSPENDED"):
        invalid_state("Builder is not PROBATION or SUSPENDED")
    # No tranche of any of the builder's agreements in {MISSED, DEFAULTED}.
    builder_agreements = [a for a in DB.agreements.values() if a["builder_id"] == b["id"]]
    ag_ids = {a["id"] for a in builder_agreements}
    for t in DB.tranches.values():
        if t["agreement_id"] in ag_ids and t["status"] in ("MISSED", "DEFAULTED"):
            err("ERR_OUTSTANDING_COMPLIANCE_DEFAULTS", 409,
                "Outstanding MISSED/DEFAULTED tranches remain")
    if b["standing"] == "SUSPENDED":
        if any(a["status"] == "DEFAULTED" for a in builder_agreements):
            err("ERR_OUTSTANDING_COMPLIANCE_DEFAULTS", 409,
                "A DEFAULTED agreement remains")
    b["standing"] = "GOOD_STANDING"
    touch(b)
    return ok_object(builder_out(b))


# ---------------------------------------------------------------------------
# Lot purchase agreements
# ---------------------------------------------------------------------------
@bp.route("/mpc/agreements", methods=["POST"])
def create_agreement():
    _, role = actor()
    require_roles(role, CTRL)
    data = body()
    community = check_body_fk("community", DB.communities, data.get("community_id"))
    builder = check_body_fk("builder", DB.builders, data.get("builder_id"))
    phase = check_body_fk("phase", DB.phases, data.get("phase_id"))
    check_no_undeclared(data, {
        "community_id", "builder_id", "phase_id", "base_price_per_lot_cents",
        "annual_escalation_pct", "penalty_per_lot_per_day_cents",
        "earnest_money_cents", "total_lots_committed"})
    req_string(data, "community_id")
    req_string(data, "builder_id")
    req_string(data, "phase_id")
    base = req_int(data, "base_price_per_lot_cents", gt=0)
    esc = req_number(data, "annual_escalation_pct", minimum=0)
    pen = req_int(data, "penalty_per_lot_per_day_cents", minimum=0)
    em = req_int(data, "earnest_money_cents", minimum=0)
    committed = req_int(data, "total_lots_committed", minimum=1)
    a = new_entity()
    a.update({
        "community_id": community["id"],
        "builder_id": builder["id"],
        "phase_id": phase["id"],
        "base_price_per_lot_cents": base,
        "annual_escalation_pct": esc,
        "penalty_per_lot_per_day_cents": pen,
        "earnest_money_cents": em,
        "total_lots_committed": committed,
        "execution_date": None,
        "lots_closed_count": 0,
        "forfeited_earnest_money_cents": 0,
        "status": "DRAFT",
    })
    DB.agreements[a["id"]] = a
    return ok_object(agreement_out(a), 201)


@bp.route("/mpc/agreements", methods=["GET"])
def list_agreements():
    actor()
    f = filter_args(["community_id", "builder_id", "phase_id"])
    raw = [a for a in DB.agreements.values()
           if f.get("community_id") in (None, a["community_id"])
           and f.get("builder_id") in (None, a["builder_id"])
           and f.get("phase_id") in (None, a["phase_id"])]
    return paginate_pairs(raw, agreement_out)


@bp.route("/mpc/agreements/<aid>", methods=["GET"])
def get_agreement(aid):
    actor()
    a = get_or_404("agreement", DB.agreements, aid)
    return ok_object(agreement_out(a))


@bp.route("/mpc/agreements/<aid>/execute", methods=["POST"])
def execute_agreement(aid):
    _, role = actor()
    require_roles(role, EXEC)
    a = get_or_404("agreement", DB.agreements, aid)
    data = body()
    check_no_undeclared(data, set())
    if a["status"] != "DRAFT":
        invalid_state("Agreement is not DRAFT")
    community = DB.communities.get(a["community_id"])
    if community is None or community["status"] != "ACTIVE":
        err("ERR_COMMUNITY_NOT_ACTIVE", 409, "Community must be ACTIVE")
    builder = DB.builders.get(a["builder_id"])
    if builder is None or builder["standing"] != "GOOD_STANDING":
        err("ERR_BUILDER_NOT_IN_GOOD_STANDING", 409,
            "Builder must be in GOOD_STANDING")
    phase = DB.phases.get(a["phase_id"])
    if phase is None or phase["status"] not in ("SALES_OPEN", "DELIVERING"):
        err("ERR_PHASE_NOT_OPEN_FOR_SALES", 409,
            "Phase must be SALES_OPEN or DELIVERING")
    total_due = sum(t["lot_count_due"] for t in DB.tranches.values()
                    if t["agreement_id"] == a["id"])
    if total_due != a["total_lots_committed"]:
        err("ERR_TRANCHE_COVERAGE_MISMATCH", 422,
            "Tranche lot_count_due total must equal total_lots_committed")
    a["status"] = "EXECUTED"
    a["execution_date"] = DB.now()
    touch(a)
    return ok_object(agreement_out(a))


@bp.route("/mpc/agreements/<aid>/commence", methods=["POST"])
def commence_agreement(aid):
    _, role = actor()
    require_roles(role, CTRL)
    a = get_or_404("agreement", DB.agreements, aid)
    data = body()
    check_no_undeclared(data, set())
    if a["status"] != "EXECUTED":
        invalid_state("Agreement is not EXECUTED")
    a["status"] = "ACTIVE"
    touch(a)
    return ok_object(agreement_out(a))


@bp.route("/mpc/agreements/<aid>/terminate", methods=["POST"])
def terminate_agreement(aid):
    _, role = actor()
    require_roles(role, EXEC)
    a = get_or_404("agreement", DB.agreements, aid)
    data = body()
    check_no_undeclared(data, set())
    if a["status"] not in ("DRAFT", "EXECUTED", "ACTIVE"):
        invalid_state("Agreement cannot be terminated from its state")
    for cl in DB.closings.values():
        if cl["agreement_id"] == a["id"] and cl["status"] == "PENDING":
            err("ERR_CLOSINGS_PENDING", 409,
                "Agreement has a PENDING closing")
    a["status"] = "TERMINATED"
    touch(a)
    for t in DB.tranches.values():
        if t["agreement_id"] == a["id"] and t["status"] in ("SCHEDULED", "OPEN"):
            t["status"] = "CANCELLED"
            touch(t)
    return ok_object(agreement_out(a))


@bp.route("/mpc/agreements/<aid>/amendments", methods=["POST"])
def amend_agreement(aid):
    _, role = actor()
    require_roles(role, CTRL)
    a = get_or_404("agreement", DB.agreements, aid)
    data = body()
    check_no_undeclared(data, {"expected_agreement_version", "replacement_tranches"})
    expected = req_int(data, "expected_agreement_version")
    repl = data.get("replacement_tranches")
    if not isinstance(repl, list):
        validation("replacement_tranches must be a list")
    parsed = []
    for item in repl:
        if not isinstance(item, dict):
            validation("replacement_tranches entries must be objects")
        check_no_undeclared(item, {"tranche_no", "due_date", "lot_count_due"})
        tno = req_int(item, "tranche_no", minimum=1)
        due = req_datetime(item, "due_date")
        cnt = req_int(item, "lot_count_due", minimum=1)
        parsed.append((tno, due, cnt))
    if a["status"] not in ("EXECUTED", "ACTIVE"):
        invalid_state("Amendments require an EXECUTED or ACTIVE agreement")
    if expected != a["version"]:
        err("ERR_STALE_VERSION", 412,
            "expected_agreement_version does not match the current version")
    # Uniqueness: within the replacement set and against surviving tranches.
    seen = set()
    for tno, _, _ in parsed:
        if tno in seen:
            err("ERR_DUPLICATE_TRANCHE_NO", 409,
                "Duplicate tranche_no in replacement_tranches")
        seen.add(tno)
    for t in DB.tranches.values():
        if (t["agreement_id"] == a["id"]
                and t["status"] not in ("SCHEDULED", "OPEN", "CANCELLED")
                and t["tranche_no"] in seen):
            err("ERR_DUPLICATE_TRANCHE_NO", 409,
                "tranche_no already used within this agreement")
    outstanding = a["total_lots_committed"] - a["lots_closed_count"]
    if sum(cnt for _, _, cnt in parsed) != outstanding:
        err("ERR_TRANCHE_COVERAGE_MISMATCH", 422,
            "Replacement tranches must cover total_lots_committed - lots_closed_count")
    for t in list(DB.tranches.values()):
        if t["agreement_id"] == a["id"] and t["status"] in ("SCHEDULED", "OPEN"):
            t["status"] = "CANCELLED"
            touch(t)
    for tno, due, cnt in parsed:
        t = new_entity()
        t.update({
            "agreement_id": a["id"],
            "tranche_no": tno,
            "due_date": due,
            "lot_count_due": cnt,
            "lots_credited": 0,
            "cure_deadline": due + timedelta(days=CURE_PERIOD_DAYS),
            "accrued_penalty_cents": 0,
            "status": "SCHEDULED",
        })
        DB.tranches[t["id"]] = t
    touch(a)
    return ok_object(agreement_out(a), 201)


# ---------------------------------------------------------------------------
# Takedown tranches
# ---------------------------------------------------------------------------
@bp.route("/mpc/tranches", methods=["POST"])
def create_tranche():
    _, role = actor()
    require_roles(role, CTRL)
    data = body()
    agreement = check_body_fk("agreement", DB.agreements, data.get("agreement_id"))
    check_no_undeclared(data, {"agreement_id", "tranche_no", "due_date",
                               "lot_count_due"})
    req_string(data, "agreement_id")
    tno = req_int(data, "tranche_no", minimum=1)
    due = req_datetime(data, "due_date")
    cnt = req_int(data, "lot_count_due", minimum=1)
    if agreement["status"] != "DRAFT":
        invalid_state("Tranches may be added only to a DRAFT agreement")
    for t in DB.tranches.values():
        if (t["agreement_id"] == agreement["id"] and t["tranche_no"] == tno
                and t["status"] != "CANCELLED"):
            err("ERR_DUPLICATE_TRANCHE_NO", 409,
                "tranche_no already used within this agreement")
    t = new_entity()
    t.update({
        "agreement_id": agreement["id"],
        "tranche_no": tno,
        "due_date": due,
        "lot_count_due": cnt,
        "lots_credited": 0,
        "cure_deadline": due + timedelta(days=CURE_PERIOD_DAYS),
        "accrued_penalty_cents": 0,
        "status": "SCHEDULED",
    })
    DB.tranches[t["id"]] = t
    return ok_object(tranche_out(t), 201)


@bp.route("/mpc/tranches", methods=["GET"])
def list_tranches():
    actor()
    f = filter_args(["agreement_id"])
    raw = [t for t in DB.tranches.values()
           if f.get("agreement_id") in (None, t["agreement_id"])]
    return paginate_pairs(raw, tranche_out)


@bp.route("/mpc/tranches/<tid>", methods=["GET"])
def get_tranche(tid):
    actor()
    t = get_or_404("tranche", DB.tranches, tid)
    return ok_object(tranche_out(t))


@bp.route("/mpc/tranches/<tid>/cure", methods=["POST"])
def cure_tranche(tid):
    user_id, role = actor()
    require_roles(role, ["BuilderRep"])
    t = get_or_404("tranche", DB.tranches, tid)
    agreement = DB.agreements.get(t["agreement_id"])
    if agreement is None or agreement["builder_id"] != user_id:
        err("ERR_FORBIDDEN_ROLE", 403,
            "BuilderRep may cure only their own agreements' tranches")
    data = body()
    check_no_undeclared(data, {"payment_cents"})
    payment = req_int(data, "payment_cents")
    if t["status"] != "MISSED":
        err("ERR_TRANCHE_NOT_CURABLE", 409, "Tranche is not MISSED")
    now = DB.now()
    if now > t["cure_deadline"]:
        err("ERR_TRANCHE_NOT_CURABLE", 409, "Cure deadline has passed")
    accrued = compute_tranche_penalty(t, now)
    if payment != accrued:
        err("ERR_PENALTY_AMOUNT_MISMATCH", 402,
            "payment_cents must equal accrued_penalty_cents exactly")
    t["accrued_penalty_cents"] = accrued
    t["status"] = "CURED"
    touch(t)
    return ok_object(tranche_out(t))


@bp.route("/mpc/tranches/<tid>/waive", methods=["POST"])
def waive_tranche(tid):
    _, role = actor()
    require_roles(role, ["AssociationDirector"])
    t = get_or_404("tranche", DB.tranches, tid)
    data = body()
    check_no_undeclared(data, {"waiver_reason"})
    req_string(data, "waiver_reason")
    if t["status"] != "MISSED":
        invalid_state("Tranche is not MISSED")
    agreement = DB.agreements.get(t["agreement_id"])
    community = DB.communities.get(agreement["community_id"]) if agreement else None
    if community is not None and community["transition_stage"] == "TURNOVER_COMPLETE":
        err("ERR_DECLARANT_AUTHORITY_ENDED", 409,
            "Declarant authority has ended")
    now = DB.now()
    t["accrued_penalty_cents"] = compute_tranche_penalty(t, now)
    t["status"] = "WAIVED"
    touch(t)
    return ok_object(tranche_out(t))


@bp.route("/mpc/tranches/<tid>/certify-default", methods=["POST"])
def certify_default(tid):
    _, role = actor()
    require_roles(role, EXEC)
    t = get_or_404("tranche", DB.tranches, tid)
    data = body()
    check_no_undeclared(data, set())
    if t["status"] != "MISSED":
        invalid_state("Tranche is not MISSED")
    now = DB.now()
    if now <= t["cure_deadline"]:
        err("ERR_CURE_WINDOW_OPEN", 409, "Cure window is still open")
    t["accrued_penalty_cents"] = compute_tranche_penalty(t, now)
    t["status"] = "DEFAULTED"
    touch(t)
    # Agreement -> DEFAULTED; earnest money forfeited; builder suspended; cascade.
    agreement = DB.agreements.get(t["agreement_id"])
    if agreement is not None and agreement["status"] != "DEFAULTED":
        agreement["status"] = "DEFAULTED"
        agreement["forfeited_earnest_money_cents"] = agreement["earnest_money_cents"]
        touch(agreement)
        builder = DB.builders.get(agreement["builder_id"])
        if builder is not None:
            domain.suspend_builder(builder)
    return ok_object(tranche_out(t))


# ---------------------------------------------------------------------------
# Lots
# ---------------------------------------------------------------------------
@bp.route("/mpc/lots", methods=["POST"])
def create_lot():
    _, role = actor()
    require_roles(role, EXEC)
    data = body()
    phase = check_body_fk("phase", DB.phases, data.get("phase_id"))
    check_no_undeclared(data, {"phase_id", "parcel_number", "lot_premium_cents"})
    req_string(data, "phase_id")
    parcel = req_string(data, "parcel_number")
    premium = opt_int(data, "lot_premium_cents", 0, minimum=0)
    for lot in DB.lots.values():
        if (lot["community_id"] == phase["community_id"]
                and lot["parcel_number"] == parcel):
            validation("parcel_number must be unique within the community")
    l = new_entity()
    l.update({
        "community_id": phase["community_id"],
        "phase_id": phase["id"],
        "parcel_number": parcel,
        "lot_premium_cents": premium,
        "status": "PLATTED",
    })
    DB.lots[l["id"]] = l
    return ok_object(lot_out(l), 201)


@bp.route("/mpc/lots", methods=["GET"])
def list_lots():
    actor()
    f = filter_args(["phase_id", "community_id"])
    raw = [l for l in DB.lots.values()
           if f.get("phase_id") in (None, l["phase_id"])
           and f.get("community_id") in (None, l["community_id"])]
    return paginate_pairs(raw, lot_out)


@bp.route("/mpc/lots/<lid>", methods=["GET"])
def get_lot(lid):
    actor()
    l = get_or_404("lot", DB.lots, lid)
    return ok_object(lot_out(l))


@bp.route("/mpc/lots/<lid>/offer", methods=["POST"])
def offer_lot(lid):
    _, role = actor()
    require_roles(role, EXEC)
    l = get_or_404("lot", DB.lots, lid)
    data = body()
    check_no_undeclared(data, set())
    if l["status"] != "PLATTED":
        invalid_state("Lot is not PLATTED")
    phase = DB.phases.get(l["phase_id"])
    if phase is None or phase["status"] not in ("SALES_OPEN", "DELIVERING"):
        err("ERR_PHASE_NOT_OPEN_FOR_SALES", 409,
            "Phase must be SALES_OPEN or DELIVERING")
    l["status"] = "OFFERED"
    touch(l)
    return ok_object(lot_out(l))


@bp.route("/mpc/lots/<lid>/withdraw", methods=["POST"])
def withdraw_lot(lid):
    _, role = actor()
    require_roles(role, EXEC)
    l = get_or_404("lot", DB.lots, lid)
    data = body()
    check_no_undeclared(data, set())
    if l["status"] != "OFFERED":
        invalid_state("Lot is not OFFERED")
    l["status"] = "WITHDRAWN"
    touch(l)
    return ok_object(lot_out(l))


# ---------------------------------------------------------------------------
# Closings
# ---------------------------------------------------------------------------
@bp.route("/mpc/closings", methods=["POST"])
def create_closing():
    _, role = actor()
    require_roles(role, CTRL)
    data = body()
    agreement = check_body_fk("agreement", DB.agreements, data.get("agreement_id"))
    lot = check_body_fk("lot", DB.lots, data.get("lot_id"))
    resident = check_body_fk("resident", DB.residents, data.get("owner_resident_id"))
    check_no_undeclared(data, {"agreement_id", "lot_id", "owner_resident_id"})
    req_string(data, "agreement_id")
    req_string(data, "lot_id")
    opt_id(data, "owner_resident_id")
    if agreement["status"] != "ACTIVE":
        err("ERR_AGREEMENT_NOT_ACTIVE", 409, "Agreement must be ACTIVE")
    if lot["status"] != "OFFERED":
        err("ERR_LOT_NOT_OFFERED", 409, "Lot must be OFFERED")
    if lot["phase_id"] != agreement["phase_id"]:
        err("ERR_LOT_PHASE_MISMATCH", 422,
            "The lot does not belong to the agreement's phase")
    c = new_entity()
    c.update({
        "community_id": agreement["community_id"],
        "agreement_id": agreement["id"],
        "lot_id": lot["id"],
        "owner_resident_id": resident["id"] if resident else None,
        "closing_date": None,
        "escalated_base_cents": None,
        "premium_cents": None,
        "price_cents": None,
        "credited_tranche_id": None,
        "is_surplus": False,
        "status": "PENDING",
    })
    DB.closings[c["id"]] = c
    lot["status"] = "UNDER_CONTRACT"
    touch(lot)
    return ok_object(closing_out(c), 201)


@bp.route("/mpc/closings", methods=["GET"])
def list_closings():
    actor()
    f = filter_args(["agreement_id", "lot_id", "owner_resident_id",
                     "credited_tranche_id", "community_id"])
    raw = [c for c in DB.closings.values()
           if f.get("agreement_id") in (None, c["agreement_id"])
           and f.get("lot_id") in (None, c["lot_id"])
           and f.get("owner_resident_id") in (None, c["owner_resident_id"])
           and f.get("credited_tranche_id") in (None, c["credited_tranche_id"])
           and f.get("community_id") in (None, c["community_id"])]
    return paginate_pairs(raw, closing_out)


@bp.route("/mpc/closings/<clid>", methods=["GET"])
def get_closing(clid):
    actor()
    c = get_or_404("closing", DB.closings, clid)
    return ok_object(closing_out(c))


def compute_escalated_price(agreement, lot, closing_date):
    """escalated_lot_price: anniversaries of execution_date <= closing_date."""
    anniversaries = 0
    if agreement["execution_date"] is not None:
        k = 1
        while True:
            ann = add_years(agreement["execution_date"], k)
            if ann <= closing_date:
                anniversaries = k
                k += 1
            else:
                break
    factor = (Decimal(1) + Decimal(str(agreement["annual_escalation_pct"])) / Decimal(100)) ** anniversaries
    escalated = round_half_up_int(Decimal(agreement["base_price_per_lot_cents"]) * factor)
    premium = lot["lot_premium_cents"]
    return escalated, premium, escalated + premium


@bp.route("/mpc/closings/<clid>/close", methods=["POST"])
def close_closing(clid):
    _, role = actor()
    require_roles(role, CTRL)
    c = get_or_404("closing", DB.closings, clid)
    data = body()
    check_no_undeclared(data, set())
    if c["status"] != "PENDING":
        invalid_state("Closing is not PENDING")
    agreement = DB.agreements.get(c["agreement_id"])
    if agreement is None or agreement["status"] != "ACTIVE":
        err("ERR_AGREEMENT_NOT_ACTIVE", 409, "Agreement must be ACTIVE")
    lot = DB.lots.get(c["lot_id"])
    if lot is None or lot["status"] != "UNDER_CONTRACT":
        err("ERR_LOT_NOT_UNDER_CONTRACT", 409, "Lot must be UNDER_CONTRACT")
    now = DB.now()
    # 1. Price
    escalated, premium, price = compute_escalated_price(agreement, lot, now)
    c["closing_date"] = now
    c["escalated_base_cents"] = escalated
    c["premium_cents"] = premium
    c["price_cents"] = price
    # 2. Waterfall credit
    eligible = [t for t in DB.tranches.values()
                if t["agreement_id"] == agreement["id"]
                and t["status"] in ("OPEN", "MISSED")
                and t["lots_credited"] < t["lot_count_due"]]
    eligible.sort(key=lambda t: (t["due_date"], t["tranche_no"]))
    if eligible:
        selected = eligible[0]
        if selected["status"] == "MISSED":
            selected["accrued_penalty_cents"] = compute_tranche_penalty(selected, now)
        selected["lots_credited"] += 1
        if selected["lots_credited"] == selected["lot_count_due"]:
            selected["status"] = "SATISFIED"
        touch(selected)
        c["credited_tranche_id"] = selected["id"]
        c["is_surplus"] = False
    else:
        c["credited_tranche_id"] = None
        c["is_surplus"] = True
    c["status"] = "CLOSED"
    touch(c)
    # 3. Lot -> CLOSED; phase advances / counts; amenity trigger breach
    lot["status"] = "CLOSED"
    touch(lot)
    phase = DB.phases.get(lot["phase_id"])
    if phase is not None:
        if phase["status"] == "SALES_OPEN":
            phase["status"] = "DELIVERING"
        phase["closed_lot_count"] += 1
        touch(phase)
        domain.check_amenity_trigger_breach(phase)
    # 4. Agreement / builder counts, completion check
    agreement["lots_closed_count"] += 1
    touch(agreement)
    builder = DB.builders.get(agreement["builder_id"])
    if builder is not None:
        builder["total_lots_purchased"] += 1
        touch(builder)
    domain.check_agreement_completion(agreement)
    # 5. Community counts, stage ratchet, seat conversion
    community = DB.communities.get(c["community_id"])
    if community is not None:
        community["closed_unit_count"] += 1
        domain.recompute_community_stage(community)
        touch(community)
    # 6. Resident -> OWNER
    if c["owner_resident_id"]:
        resident = DB.residents.get(c["owner_resident_id"])
        if resident is not None and resident["status"] in ("PROSPECT", "PURCHASER"):
            resident["status"] = "OWNER"
            resident["owner_since"] = now
            if resident["lot_id"] is None:
                resident["lot_id"] = lot["id"]
            touch(resident)
    return ok_object(closing_out(c))


@bp.route("/mpc/closings/<clid>/cancel", methods=["POST"])
def cancel_closing(clid):
    _, role = actor()
    require_roles(role, CTRL)
    c = get_or_404("closing", DB.closings, clid)
    data = body()
    check_no_undeclared(data, set())
    if c["status"] != "PENDING":
        invalid_state("Closing is not PENDING")
    c["status"] = "CANCELLED"
    touch(c)
    lot = DB.lots.get(c["lot_id"])
    if lot is not None and lot["status"] == "UNDER_CONTRACT":
        lot["status"] = "OFFERED"
        touch(lot)
    return ok_object(closing_out(c))


@bp.route("/mpc/closings/<clid>/rescind", methods=["POST"])
def rescind_closing(clid):
    _, role = actor()
    require_roles(role, EXEC)
    c = get_or_404("closing", DB.closings, clid)
    data = body()
    check_no_undeclared(data, set())
    if c["status"] != "CLOSED":
        invalid_state("Closing is not CLOSED")
    now = DB.now()
    if now > c["closing_date"] + timedelta(days=RESCISSION_WINDOW_DAYS):
        err("ERR_RESCISSION_WINDOW_EXPIRED", 422,
            "Rescission window has expired")
    c["status"] = "RESCINDED"
    touch(c)
    # Unwind the credited tranche
    if c["credited_tranche_id"]:
        t = DB.tranches.get(c["credited_tranche_id"])
        if t is not None:
            t["lots_credited"] -= 1
            if t["status"] == "SATISFIED":
                t["status"] = "OPEN" if now <= t["due_date"] else "MISSED"
            touch(t)
    community = DB.communities.get(c["community_id"])
    if community is not None:
        community["closed_unit_count"] -= 1
        # transition_stage does NOT regress (ratchet)
        touch(community)
    lot = DB.lots.get(c["lot_id"])
    if lot is not None:
        phase = DB.phases.get(lot["phase_id"])
        if phase is not None:
            phase["closed_lot_count"] -= 1
            touch(phase)
        lot["status"] = "OFFERED"
        touch(lot)
    agreement = DB.agreements.get(c["agreement_id"])
    if agreement is not None:
        agreement["lots_closed_count"] -= 1
        touch(agreement)
        builder = DB.builders.get(agreement["builder_id"])
        if builder is not None:
            builder["total_lots_purchased"] -= 1
            touch(builder)
    # owner_resident remains OWNER (no regression)
    return ok_object(closing_out(c))
