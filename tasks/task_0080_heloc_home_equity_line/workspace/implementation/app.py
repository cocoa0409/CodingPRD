"""HELOC Home Equity Line API — Flask entry point.

In-memory storage only. Server starts empty on every boot.
"""
import os

from flask import Flask, request

from errors import ApiError, err
from response import ok, created, listing, error_response
from store import (
    db, new_id, now_iso, parse_iso, stamp_create, touch,
)
from auth import get_identity, require_roles
from serializers import public
from validate import (
    get_body, req_int, req_str, req_enum, req_datetime, bad,
)
import calc

app = Flask(__name__)

# Roles
LO = "LoanOfficer"
LS = "LoanServicer"
BR = "Borrower"
AU = "Auditor"
ALL_READ = {LO, LS, AU}


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", 404, "Method not allowed")


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return error_response("ERR_INVALID_REQUEST", 422, str(e))


# ---------------------------------------------------------------------------
# Pagination helper
# ---------------------------------------------------------------------------
def paginate(items):
    """Sort by created_at ASC, apply limit/offset query params."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            bad("limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            bad("offset must be an integer")
        if offset < 0:
            offset = 0
    ordered = sorted(items, key=lambda o: (o["created_at"], o["id"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, limit, offset, total


# ---------------------------------------------------------------------------
# Lookup helpers (existence; raise ERR_NOT_FOUND)
# ---------------------------------------------------------------------------
def get_or_404(coll, _id):
    obj = coll.get(_id)
    if obj is None:
        raise err("ERR_NOT_FOUND", "Resource not found")
    return obj


def get_ref_or_404(coll, _id):
    obj = coll.get(_id)
    if obj is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "Referenced resource not found")
    return obj


# ---------------------------------------------------------------------------
# Reconciliation helpers
# ---------------------------------------------------------------------------
def reconcile_read(heloc):
    """Recompute available_credit and apr for read consistency. Does NOT bump
    version (read-only reconciliation). Persists the recomputed values."""
    heloc["current_apr_bps"] = calc.compute_apr_bps(heloc)
    if heloc["status"] == "DRAW":
        heloc["available_credit_cents"] = max(
            heloc["credit_limit_cents"] - heloc["current_balance_cents"], 0
        )
    else:
        # 0 while not in DRAW
        heloc["available_credit_cents"] = 0
    return heloc


def recompute_available(heloc):
    heloc["available_credit_cents"] = max(
        heloc["credit_limit_cents"] - heloc["current_balance_cents"], 0
    )


# ===========================================================================
# Borrower
# ===========================================================================
@app.post("/borrowers")
def create_borrower():
    _, role = get_identity()
    require_roles(role, {LO})
    body = get_body()
    full_name = req_str(body, "full_name")
    annual_income = req_int(body, "annual_income_cents", minimum=0)
    monthly_debt = req_int(body, "monthly_debt_obligation_cents", minimum=0,
                           required=False, default=0)
    credit_score = req_int(body, "credit_score", minimum=300, maximum=850)
    kyc = req_enum(body, "kyc_status", {"PENDING", "CLEARED", "REJECTED"},
                   required=False, default="PENDING")
    obj = {
        "full_name": full_name,
        "annual_income_cents": annual_income,
        "monthly_debt_obligation_cents": monthly_debt,
        "credit_score": credit_score,
        "kyc_status": kyc,
    }
    stamp_create(obj)
    db.borrowers[obj["id"]] = obj
    return created(public(obj))


@app.get("/borrowers/<bid>")
def get_borrower(bid):
    _, role = get_identity()
    require_roles(role, ALL_READ)
    obj = get_or_404(db.borrowers, bid)
    return ok(public(obj))


@app.patch("/borrowers/<bid>")
def patch_borrower(bid):
    _, role = get_identity()
    require_roles(role, {LO})
    obj = get_or_404(db.borrowers, bid)
    body = get_body()
    changed = False
    if "kyc_status" in body and body["kyc_status"] is not None:
        obj["kyc_status"] = req_enum(body, "kyc_status",
                                     {"PENDING", "CLEARED", "REJECTED"})
        changed = True
    if "annual_income_cents" in body and body["annual_income_cents"] is not None:
        obj["annual_income_cents"] = req_int(body, "annual_income_cents", minimum=0)
        changed = True
    if "monthly_debt_obligation_cents" in body and body["monthly_debt_obligation_cents"] is not None:
        obj["monthly_debt_obligation_cents"] = req_int(
            body, "monthly_debt_obligation_cents", minimum=0)
        changed = True
    if changed:
        touch(obj)
    return ok(public(obj))


# ===========================================================================
# Property
# ===========================================================================
@app.post("/properties")
def create_property():
    _, role = get_identity()
    require_roles(role, {LO})
    body = get_body()
    street = req_str(body, "street_address")
    appraised = req_int(body, "appraised_value_cents", minimum=1)
    senior = req_int(body, "senior_lien_balance_cents", minimum=0,
                     required=False, default=0)
    fips = req_str(body, "county_fips")
    obj = {
        "street_address": street,
        "appraised_value_cents": appraised,
        "senior_lien_balance_cents": senior,
        "county_fips": fips,
        "status": "ACTIVE",
    }
    stamp_create(obj)
    db.properties[obj["id"]] = obj
    return created(public(obj))


@app.get("/properties/<pid>")
def get_property(pid):
    _, role = get_identity()
    require_roles(role, ALL_READ)
    obj = get_or_404(db.properties, pid)
    return ok(public(obj))


@app.patch("/properties/<pid>")
def patch_property(pid):
    _, role = get_identity()
    require_roles(role, {LO, LS})
    obj = get_or_404(db.properties, pid)
    body = get_body()
    changed = False
    if "appraised_value_cents" in body and body["appraised_value_cents"] is not None:
        obj["appraised_value_cents"] = req_int(body, "appraised_value_cents", minimum=1)
        changed = True
    if "senior_lien_balance_cents" in body and body["senior_lien_balance_cents"] is not None:
        obj["senior_lien_balance_cents"] = req_int(
            body, "senior_lien_balance_cents", minimum=0)
        changed = True
    if changed:
        touch(obj)
    return ok(public(obj))


@app.get("/properties/<pid>/lien-records")
def list_property_liens(pid):
    _, role = get_identity()
    require_roles(role, ALL_READ)
    get_or_404(db.properties, pid)
    items = [lr for lr in db.lien_records.values() if lr["property_id"] == pid]
    page, limit, offset, total = paginate(items)
    return listing([public(o) for o in page], limit, offset, total)


# ===========================================================================
# IndexRate
# ===========================================================================
def _supersede_prior(index_name, effective_date):
    """Mark prior IndexRate with same name and earlier effective_date as superseded."""
    eff = parse_iso(effective_date)
    for r in db.index_rates.values():
        if r["index_name"] == index_name and not r["superseded"]:
            if parse_iso(r["effective_date"]) < eff:
                r["superseded"] = True
                touch(r)


@app.post("/index-rates")
def create_index_rate():
    _, role = get_identity()
    require_roles(role, {LS})
    body = get_body()
    name = req_enum(body, "index_name", {"PRIME"}, required=False, default="PRIME")
    rate_bps = req_int(body, "rate_bps", minimum=0)
    eff = req_datetime(body, "effective_date")
    obj = {
        "index_name": name,
        "rate_bps": rate_bps,
        "effective_date": eff,
        "superseded": False,
    }
    stamp_create(obj)
    # mark prior earlier ones superseded
    _supersede_prior(name, eff)
    db.index_rates[obj["id"]] = obj
    return created(public(obj))


@app.get("/index-rates/<rid>")
def get_index_rate(rid):
    _, role = get_identity()
    require_roles(role, {LS, LO, AU})
    obj = get_or_404(db.index_rates, rid)
    return ok(public(obj))


@app.get("/index-rates")
def list_index_rates():
    _, role = get_identity()
    require_roles(role, {LS, LO, AU})
    items = list(db.index_rates.values())
    name = request.args.get("index_name")
    if name is not None:
        items = [r for r in items if r["index_name"] == name]
    sup = request.args.get("superseded")
    if sup is not None:
        want = sup.lower() in ("true", "1", "yes")
        items = [r for r in items if r["superseded"] == want]
    page, limit, offset, total = paginate(items)
    return listing([public(o) for o in page], limit, offset, total)


@app.post("/index-rates/<rid>/supersede")
def supersede_index_rate(rid):
    _, role = get_identity()
    require_roles(role, {LS})
    target = get_or_404(db.index_rates, rid)
    body = get_body()
    rate_bps = req_int(body, "rate_bps", minimum=0)
    eff = req_datetime(body, "effective_date")
    expected = req_int(body, "expected_indexrate_version")
    if expected != target["version"]:
        raise err("ERR_STALE_VERSION", "expected_indexrate_version does not match")
    # create new PRIME index
    new_obj = {
        "index_name": "PRIME",
        "rate_bps": rate_bps,
        "effective_date": eff,
        "superseded": False,
    }
    stamp_create(new_obj)
    db.index_rates[new_obj["id"]] = new_obj
    # supersede target row
    target["superseded"] = True
    touch(target)
    # recompute current_apr_bps on every active line
    for h in db.helocs.values():
        if h["status"] in ("DRAW", "FROZEN", "REPAYMENT"):
            new_apr = calc.compute_apr_bps(h)
            if new_apr != h["current_apr_bps"]:
                h["current_apr_bps"] = new_apr
            touch(h)
    return created(public(new_obj))


# ===========================================================================
# Heloc
# ===========================================================================
@app.post("/helocs")
def create_heloc():
    _, role = get_identity()
    require_roles(role, {LO})
    body = get_body()
    borrower_id = req_str(body, "borrower_id")
    property_id = req_str(body, "property_id")
    lien_position = req_enum(body, "lien_position", {"FIRST", "SECOND"})
    credit_limit = req_int(body, "credit_limit_cents", minimum=100000)
    margin = req_int(body, "margin_bps", minimum=0, maximum=2000)
    ceiling = req_int(body, "rate_ceiling_bps", minimum=0)
    annual_fee = req_int(body, "annual_fee_cents", minimum=0, required=False, default=5000)
    orig = req_datetime(body, "origination_date")
    draw_years = req_int(body, "draw_period_years", minimum=1, maximum=15,
                         required=False, default=10)
    repay_years = req_int(body, "repayment_period_years", minimum=1, maximum=30,
                          required=False, default=20)
    # FK body references
    get_ref_or_404(db.borrowers, borrower_id)
    get_ref_or_404(db.properties, property_id)
    obj = {
        "borrower_id": borrower_id,
        "property_id": property_id,
        "lien_position": lien_position,
        "credit_limit_cents": credit_limit,
        "margin_bps": margin,
        "rate_ceiling_bps": ceiling,
        "annual_fee_cents": annual_fee,
        "origination_date": orig,
        "draw_period_years": draw_years,
        "repayment_period_years": repay_years,
        "status": "APPLICATION",
        "current_balance_cents": 0,
        "available_credit_cents": 0,
        "current_apr_bps": 0,
        "accrued_interest_cents": 0,
        "delinquency_days": 0,
        "anniversary_count": 0,
        "_activated_by": None,
    }
    stamp_create(obj)
    db.helocs[obj["id"]] = obj
    return created(public(obj))


@app.get("/helocs/<hid>")
def get_heloc(hid):
    _, role = get_identity()
    require_roles(role, ALL_READ)
    obj = get_or_404(db.helocs, hid)
    reconcile_read(obj)
    return ok(public(obj))


@app.get("/helocs")
def list_helocs():
    _, role = get_identity()
    require_roles(role, ALL_READ)
    items = list(db.helocs.values())
    bid = request.args.get("borrower_id")
    if bid is not None:
        items = [h for h in items if h["borrower_id"] == bid]
    pid = request.args.get("property_id")
    if pid is not None:
        items = [h for h in items if h["property_id"] == pid]
    st = request.args.get("status")
    if st is not None:
        items = [h for h in items if h["status"] == st]
    page, limit, offset, total = paginate(items)
    out = []
    for h in page:
        reconcile_read(h)
        out.append(public(h))
    return listing(out, limit, offset, total)


def _heloc_covenants(hid):
    return [c for c in db.covenants.values() if c["heloc_id"] == hid]


@app.post("/helocs/<hid>/activate")
def activate_heloc(hid):
    user_id, role = get_identity()
    require_roles(role, {LO})
    heloc = get_or_404(db.helocs, hid)
    # state guard
    if heloc["status"] != "APPLICATION":
        raise err("ERR_INVALID_STATE", "HELOC is not in APPLICATION state")
    borrower = db.borrowers.get(heloc["borrower_id"])
    prop = db.properties.get(heloc["property_id"])
    # KYC
    if not borrower or borrower["kyc_status"] != "CLEARED":
        raise err("ERR_KYC_NOT_CLEARED", "Borrower KYC is not CLEARED")
    # covenant set complete
    covs = _heloc_covenants(hid)
    types = {c["covenant_type"] for c in covs}
    if not {"MAX_CLTV", "MIN_DSCR", "MAX_DELINQUENCY_DAYS"}.issubset(types):
        raise err("ERR_COVENANT_SET_INCOMPLETE", "Covenant set incomplete")
    # active index
    prime = calc.active_prime()
    if prime is None:
        raise err("ERR_NO_ACTIVE_INDEX", "No active PRIME index rate")
    # lien position conflict
    if heloc["lien_position"] == "FIRST" and prop["senior_lien_balance_cents"] != 0:
        raise err("ERR_LIEN_POSITION_CONFLICT", "FIRST position requires zero senior lien balance")
    # success
    heloc["status"] = "DRAW"
    heloc["current_apr_bps"] = min(prime["rate_bps"] + heloc["margin_bps"],
                                   heloc["rate_ceiling_bps"])
    heloc["available_credit_cents"] = heloc["credit_limit_cents"]
    heloc["_activated_by"] = user_id
    # lien record
    lien = {
        "heloc_id": hid,
        "property_id": heloc["property_id"],
        "position": heloc["lien_position"],
        "status": "RECORDED",
    }
    stamp_create(lien)
    db.lien_records[lien["id"]] = lien
    # property active
    if prop["status"] != "ACTIVE":
        prop["status"] = "ACTIVE"
        touch(prop)
    touch(heloc)
    return ok(public(heloc))


@app.post("/helocs/<hid>/convert-to-repayment")
def convert_heloc(hid):
    _, role = get_identity()
    require_roles(role, {LS})
    heloc = get_or_404(db.helocs, hid)
    if heloc["status"] != "DRAW":
        raise err("ERR_INVALID_STATE", "HELOC is not in DRAW state")
    if db.current_utc < calc.draw_period_end(heloc):
        raise err("ERR_DRAW_PERIOD_NOT_ELAPSED", "Draw period has not elapsed")
    heloc["status"] = "REPAYMENT"
    heloc["available_credit_cents"] = 0
    touch(heloc)
    return ok(public(heloc))


@app.post("/helocs/<hid>/freeze")
def freeze_heloc(hid):
    _, role = get_identity()
    require_roles(role, {LS})
    heloc = get_or_404(db.helocs, hid)
    if heloc["status"] != "DRAW":
        raise err("ERR_INVALID_STATE", "HELOC is not in DRAW state")
    heloc["status"] = "FROZEN"
    heloc["available_credit_cents"] = 0
    touch(heloc)
    return ok(public(heloc))


@app.post("/helocs/<hid>/unfreeze")
def unfreeze_heloc(hid):
    _, role = get_identity()
    require_roles(role, {LS})
    heloc = get_or_404(db.helocs, hid)
    if heloc["status"] != "FROZEN":
        raise err("ERR_INVALID_STATE", "HELOC is not in FROZEN state")
    breached = any(c["status"] == "BREACHED" for c in _heloc_covenants(hid))
    if breached:
        raise err("ERR_INVALID_STATE", "A covenant is currently BREACHED")
    heloc["status"] = "DRAW"
    recompute_available(heloc)
    touch(heloc)
    return ok(public(heloc))


@app.post("/helocs/<hid>/declare-default")
def declare_default(hid):
    user_id, role = get_identity()
    require_roles(role, {LS})
    heloc = get_or_404(db.helocs, hid)
    body = get_body()
    covenant_id = req_str(body, "covenant_id")
    # body FK reference
    covenant = get_ref_or_404(db.covenants, covenant_id)
    # state guard
    if heloc["status"] not in ("DRAW", "REPAYMENT", "FROZEN"):
        raise err("ERR_INVALID_STATE", "HELOC cannot be defaulted from this state")
    # segregation of duties (priority 6) before breached covenant (priority 7)
    if heloc.get("_activated_by") is not None and user_id == heloc["_activated_by"]:
        raise err("ERR_SEGREGATION_OF_DUTIES",
                  "Default cannot be declared by the activating officer")
    # breached covenant belonging to this heloc
    if covenant["heloc_id"] != hid or covenant["status"] != "BREACHED":
        raise err("ERR_NO_BREACHED_COVENANT",
                  "Referenced covenant is not BREACHED or not on this HELOC")
    # observed value
    borrower = db.borrowers.get(heloc["borrower_id"])
    prop = db.properties.get(heloc["property_id"])
    observed = calc.covenant_observed_value(covenant, heloc, prop, borrower)
    # create default event (immutable: id + created_at only)
    ev = {
        "heloc_id": hid,
        "covenant_id": covenant_id,
        "trigger_type": covenant["covenant_type"],
        "observed_value": observed,
        "declared_by_user_id": user_id,
    }
    stamp_create(ev, with_common=False)
    db.default_events[ev["id"]] = ev
    # cascade
    heloc["status"] = "DEFAULTED"
    heloc["available_credit_cents"] = 0
    touch(heloc)
    return ok(public(heloc))


@app.post("/helocs/<hid>/close")
def close_heloc(hid):
    _, role = get_identity()
    require_roles(role, {LS})
    heloc = get_or_404(db.helocs, hid)
    if heloc["status"] not in ("DRAW", "REPAYMENT"):
        raise err("ERR_INVALID_STATE", "HELOC cannot be closed from this state")
    if heloc["current_balance_cents"] != 0 or heloc["accrued_interest_cents"] != 0:
        raise err("ERR_BALANCE_NOT_ZERO", "Balance and accrued interest must be zero")
    # early closure fee assessment (cascade 1) when closing from DRAW before
    # draw-period end. Assess at most once per line: a prior close attempt that
    # was blocked already created the EARLY_CLOSURE fee, which the borrower then
    # settles before retrying. Do not duplicate it on retry.
    if heloc["status"] == "DRAW" and db.current_utc < calc.draw_period_end(heloc):
        existing_ec = any(
            f["heloc_id"] == hid and f["fee_type"] == "EARLY_CLOSURE"
            for f in db.fee_assessments.values()
        )
        if not existing_ec:
            fee_amount = calc.early_closure_fee(heloc, db.current_utc)
            if fee_amount > 0:
                fee = {
                    "heloc_id": hid,
                    "fee_type": "EARLY_CLOSURE",
                    "amount_cents": fee_amount,
                    "settlement_status": "OUTSTANDING",
                }
                stamp_create(fee)
                db.fee_assessments[fee["id"]] = fee
    # blocked while any fee assessment OUTSTANDING
    outstanding = [f for f in db.fee_assessments.values()
                   if f["heloc_id"] == hid and f["settlement_status"] == "OUTSTANDING"]
    if outstanding:
        raise err("ERR_FEES_OUTSTANDING", "Outstanding fee assessments block closure")
    # success cascade
    heloc["status"] = "CLOSED"
    touch(heloc)
    # cure covenants
    for c in _heloc_covenants(hid):
        if c["status"] != "CURED":
            c["status"] = "CURED"
            touch(c)
    # release lien records of this heloc
    for lr in db.lien_records.values():
        if lr["heloc_id"] == hid and lr["status"] != "RELEASED":
            lr["status"] = "RELEASED"
            touch(lr)
    # release property if no other RECORDED lien references it
    prop = db.properties.get(heloc["property_id"])
    if prop is not None:
        others = [lr for lr in db.lien_records.values()
                  if lr["property_id"] == prop["id"] and lr["status"] == "RECORDED"]
        if not others and prop["status"] != "RELEASED":
            prop["status"] = "RELEASED"
            touch(prop)
    return ok(public(heloc))


@app.get("/helocs/<hid>/payoff-quote")
def payoff_quote(hid):
    _, role = get_identity()
    require_roles(role, ALL_READ)
    heloc = get_or_404(db.helocs, hid)
    as_of_raw = request.args.get("as_of")
    if as_of_raw is not None:
        try:
            as_of = parse_iso(as_of_raw)
        except Exception:
            bad("as_of must be a valid ISO 8601 datetime")
        as_of_str = as_of_raw
    else:
        as_of = db.current_utc
        as_of_str = now_iso(as_of)
    projected = calc.forward_projected_interest(heloc, as_of)
    payoff = heloc["current_balance_cents"] + heloc["accrued_interest_cents"] + projected
    return ok({
        "payoff_cents": payoff,
        "projected_interest_cents": projected,
        "as_of": as_of_str,
    })


@app.get("/helocs/<hid>/interest-quote")
def interest_quote(hid):
    _, role = get_identity()
    require_roles(role, ALL_READ)
    heloc = get_or_404(db.helocs, hid)
    as_of = db.current_utc
    accrued = calc.chronological_accrued(heloc, as_of)
    return ok({
        "accrued_interest_cents": accrued,
        "as_of": now_iso(as_of),
    })


# ===========================================================================
# Draw
# ===========================================================================
@app.post("/helocs/<hid>/draws")
def create_draw(hid):
    _, role = get_identity()
    require_roles(role, {LS})
    heloc = get_or_404(db.helocs, hid)
    if heloc["status"] != "DRAW":
        raise err("ERR_DRAWS_NOT_PERMITTED", "Draws are only permitted in DRAW state")
    body = get_body()
    amount = req_int(body, "amount_cents", minimum=1)
    if amount > heloc["available_credit_cents"]:
        raise err("ERR_INSUFFICIENT_CREDIT", "Draw exceeds available credit")
    # accrue interest up to now (chronological) before booking
    draw = {
        "heloc_id": hid,
        "amount_cents": amount,
        "requested_at": now_iso(db.current_utc),
        "status": "BOOKED",
    }
    stamp_create(draw)
    db.draws[draw["id"]] = draw
    # debit balance
    heloc["current_balance_cents"] += amount
    recompute_available(heloc)
    heloc["accrued_interest_cents"] = calc.chronological_accrued(heloc, db.current_utc)
    touch(heloc)
    return created(public(draw))


@app.get("/helocs/<hid>/draws")
def list_draws(hid):
    _, role = get_identity()
    require_roles(role, ALL_READ)
    get_or_404(db.helocs, hid)
    items = [d for d in db.draws.values() if d["heloc_id"] == hid]
    st = request.args.get("status")
    if st is not None:
        items = [d for d in items if d["status"] == st]
    page, limit, offset, total = paginate(items)
    return listing([public(o) for o in page], limit, offset, total)


@app.post("/helocs/<hid>/draws/<did>/reverse")
def reverse_draw(hid, did):
    _, role = get_identity()
    require_roles(role, {LS})
    heloc = get_or_404(db.helocs, hid)
    draw = get_or_404(db.draws, did)
    if draw["heloc_id"] != hid:
        raise err("ERR_NOT_FOUND", "Draw does not belong to this HELOC")
    # state guards
    if draw["status"] != "BOOKED":
        raise err("ERR_INVALID_STATE", "Draw is not BOOKED")
    if heloc["status"] not in ("DRAW", "FROZEN"):
        raise err("ERR_INVALID_STATE", "HELOC is not in DRAW or FROZEN state")
    if heloc["current_balance_cents"] < draw["amount_cents"]:
        raise err("ERR_REVERSAL_UNDERFLOW", "Reversal would underflow principal")
    heloc["current_balance_cents"] -= draw["amount_cents"]
    recompute_available(heloc)
    draw["status"] = "REVERSED"
    touch(draw)
    touch(heloc)
    return ok(public(draw))


# ===========================================================================
# Payment
# ===========================================================================
@app.post("/helocs/<hid>/payments")
def create_payment(hid):
    user_id, role = get_identity()
    require_roles(role, {LS, BR})
    heloc = get_or_404(db.helocs, hid)
    # Borrower ownership: X-User-ID is the Borrower entity id
    if role == BR and heloc["borrower_id"] != user_id:
        raise err("ERR_FORBIDDEN_ROLE", "Borrower does not own this line")
    body = get_body()
    amount = req_int(body, "amount_cents", minimum=1)
    # accrue chronological interest up to posted_at (= now)
    posted_at = now_iso(db.current_utc)
    heloc["accrued_interest_cents"] = calc.chronological_accrued(heloc, db.current_utc)
    # waterfall
    remaining = amount
    # fee bucket: OUTSTANDING fees oldest-first
    outstanding_fees = sorted(
        [f for f in db.fee_assessments.values()
         if f["heloc_id"] == hid and f["settlement_status"] == "OUTSTANDING"],
        key=lambda f: (f["created_at"], f["id"]),
    )
    fee_due = sum(f["amount_cents"] for f in outstanding_fees)
    fee_applied = min(remaining, fee_due)
    remaining -= fee_applied
    interest_applied = min(remaining, heloc["accrued_interest_cents"])
    remaining -= interest_applied
    principal_applied = min(remaining, heloc["current_balance_cents"])
    remaining -= principal_applied
    if remaining > 0:
        raise err("ERR_OVERPAYMENT", "Payment exceeds total owed")
    # commit
    payment = {
        "heloc_id": hid,
        "amount_cents": amount,
        "posted_at": posted_at,
        "interest_applied_cents": interest_applied,
        "principal_applied_cents": principal_applied,
        "fee_applied_cents": fee_applied,
    }
    stamp_create(payment)
    db.payments[payment["id"]] = payment
    # settle fees in order
    fee_remaining = fee_applied
    for f in outstanding_fees:
        if fee_remaining <= 0:
            break
        cover = min(fee_remaining, f["amount_cents"])
        fee_remaining -= cover
        # cumulative coverage: since we apply oldest-first fully, mark settled when fully covered
        if cover >= f["amount_cents"]:
            f["settlement_status"] = "SETTLED"
            touch(f)
    # reduce buckets
    heloc["accrued_interest_cents"] -= interest_applied
    heloc["current_balance_cents"] -= principal_applied
    recompute_available(heloc)
    # reset delinquency if obligation cleared (no outstanding fees & balance/interest serviced)
    still_outstanding = any(
        f["heloc_id"] == hid and f["settlement_status"] == "OUTSTANDING"
        for f in db.fee_assessments.values()
    )
    if not still_outstanding and heloc["accrued_interest_cents"] == 0:
        heloc["delinquency_days"] = 0
    touch(heloc)
    return created(public(payment))


@app.get("/helocs/<hid>/payments")
def list_payments(hid):
    user_id, role = get_identity()
    require_roles(role, {LO, LS, AU, BR})
    heloc = get_or_404(db.helocs, hid)
    if role == BR and heloc["borrower_id"] != user_id:
        raise err("ERR_FORBIDDEN_ROLE", "Borrower does not own this line")
    items = [p for p in db.payments.values() if p["heloc_id"] == hid]
    page, limit, offset, total = paginate(items)
    return listing([public(o) for o in page], limit, offset, total)


# ===========================================================================
# Covenant
# ===========================================================================
@app.post("/helocs/<hid>/covenants")
def create_covenant(hid):
    _, role = get_identity()
    require_roles(role, {LO})
    heloc = get_or_404(db.helocs, hid)
    body = get_body()
    ctype = req_enum(body, "covenant_type",
                     {"MAX_CLTV", "MIN_DSCR", "MAX_DELINQUENCY_DAYS"})
    threshold = req_int(body, "threshold_value", minimum=0)
    obj = {
        "heloc_id": hid,
        "covenant_type": ctype,
        "threshold_value": threshold,
        "status": "SATISFIED",
    }
    stamp_create(obj)
    db.covenants[obj["id"]] = obj
    return created(public(obj))


@app.get("/helocs/<hid>/covenants")
def list_covenants(hid):
    _, role = get_identity()
    require_roles(role, ALL_READ)
    get_or_404(db.helocs, hid)
    items = [c for c in db.covenants.values() if c["heloc_id"] == hid]
    st = request.args.get("status")
    if st is not None:
        items = [c for c in items if c["status"] == st]
    page, limit, offset, total = paginate(items)
    return listing([public(o) for o in page], limit, offset, total)


@app.get("/covenants/<cid>")
def get_covenant(cid):
    _, role = get_identity()
    require_roles(role, ALL_READ)
    obj = get_or_404(db.covenants, cid)
    return ok(public(obj))


def _eval_context(heloc):
    borrower = db.borrowers.get(heloc["borrower_id"])
    prop = db.properties.get(heloc["property_id"])
    return prop, borrower


@app.post("/helocs/<hid>/covenants/<cid>/evaluate")
def evaluate_covenant(hid, cid):
    _, role = get_identity()
    require_roles(role, {LS})
    heloc = get_or_404(db.helocs, hid)
    covenant = get_or_404(db.covenants, cid)
    if covenant["heloc_id"] != hid:
        raise err("ERR_NOT_FOUND", "Covenant does not belong to this HELOC")
    if covenant["status"] not in ("SATISFIED", "CURED"):
        raise err("ERR_INVALID_STATE", "Covenant cannot be evaluated from this state")
    prop, borrower = _eval_context(heloc)
    if not calc.covenant_breached(covenant, heloc, prop, borrower):
        raise err("ERR_INVALID_STATE", "Covenant metric does not cross threshold")
    covenant["status"] = "BREACHED"
    touch(covenant)
    # cascade: freeze line if in DRAW
    if heloc["status"] == "DRAW":
        heloc["status"] = "FROZEN"
        heloc["available_credit_cents"] = 0
        touch(heloc)
    return ok(public(covenant))


@app.post("/helocs/<hid>/covenants/<cid>/cure")
def cure_covenant(hid, cid):
    _, role = get_identity()
    require_roles(role, {LS})
    heloc = get_or_404(db.helocs, hid)
    covenant = get_or_404(db.covenants, cid)
    if covenant["heloc_id"] != hid:
        raise err("ERR_NOT_FOUND", "Covenant does not belong to this HELOC")
    if covenant["status"] != "BREACHED":
        raise err("ERR_INVALID_STATE", "Covenant is not BREACHED")
    if heloc["status"] == "DEFAULTED":
        raise err("ERR_INVALID_STATE", "HELOC is DEFAULTED")
    prop, borrower = _eval_context(heloc)
    if calc.covenant_breached(covenant, heloc, prop, borrower):
        raise err("ERR_INVALID_STATE", "Covenant metric still crosses threshold")
    # breach window: from when covenant breached until now. We approximate by
    # waiving OUTSTANDING ANNUAL fees created at/after the covenant's last
    # breach (updated_at). Use covenant updated_at as breach-window start.
    breach_start = covenant["updated_at"]
    covenant["status"] = "CURED"
    touch(covenant)
    for f in db.fee_assessments.values():
        if (f["heloc_id"] == hid and f["fee_type"] == "ANNUAL"
                and f["settlement_status"] == "OUTSTANDING"
                and f["created_at"] >= breach_start):
            f["settlement_status"] = "WAIVED"
            touch(f)
    return ok(public(covenant))


# ===========================================================================
# DefaultEvent / FeeAssessment reverse-reachability
# ===========================================================================
@app.get("/helocs/<hid>/default-events")
def list_heloc_default_events(hid):
    _, role = get_identity()
    require_roles(role, {LS, AU})
    get_or_404(db.helocs, hid)
    items = [e for e in db.default_events.values() if e["heloc_id"] == hid]
    page, limit, offset, total = paginate(items)
    return listing([public(o) for o in page], limit, offset, total)


@app.get("/helocs/<hid>/fee-assessments")
def list_heloc_fees(hid):
    user_id, role = get_identity()
    require_roles(role, {LO, LS, AU, BR})
    heloc = get_or_404(db.helocs, hid)
    if role == BR and heloc["borrower_id"] != user_id:
        raise err("ERR_FORBIDDEN_ROLE", "Borrower does not own this line")
    items = [f for f in db.fee_assessments.values() if f["heloc_id"] == hid]
    ft = request.args.get("fee_type")
    if ft is not None:
        items = [f for f in items if f["fee_type"] == ft]
    ss = request.args.get("settlement_status")
    if ss is not None:
        items = [f for f in items if f["settlement_status"] == ss]
    page, limit, offset, total = paginate(items)
    return listing([public(o) for o in page], limit, offset, total)


@app.get("/helocs/<hid>/lien-records")
def list_heloc_liens(hid):
    _, role = get_identity()
    require_roles(role, ALL_READ)
    get_or_404(db.helocs, hid)
    items = [lr for lr in db.lien_records.values() if lr["heloc_id"] == hid]
    page, limit, offset, total = paginate(items)
    return listing([public(o) for o in page], limit, offset, total)


@app.get("/covenants/<cid>/default-events")
def list_covenant_default_events(cid):
    _, role = get_identity()
    require_roles(role, {LS, AU})
    get_or_404(db.covenants, cid)
    items = [e for e in db.default_events.values() if e["covenant_id"] == cid]
    page, limit, offset, total = paginate(items)
    return listing([public(o) for o in page], limit, offset, total)


# ===========================================================================
# Clock
# ===========================================================================
@app.post("/_clock/set_current_utc")
def set_clock():
    _, role = get_identity()
    require_roles(role, {LS, LO})
    body = get_body()
    to_iso = req_datetime(body, "to_iso8601")
    db.current_utc = parse_iso(to_iso)
    return ok({"current_utc": now_iso(db.current_utc)})


@app.post("/helocs/<hid>/advance-clock")
def advance_clock(hid):
    _, role = get_identity()
    require_roles(role, {LS})
    heloc = get_or_404(db.helocs, hid)
    body = get_body()
    to_iso = req_datetime(body, "to_iso8601")
    new_clock = parse_iso(to_iso)
    db.current_utc = new_clock
    # annual fee assessment for newly crossed in-draw anniversaries
    orig = parse_iso(heloc["origination_date"])
    days = (new_clock - orig).total_seconds() / 86400.0
    elapsed_anniversaries = int(days // 365) if days >= 0 else 0
    draw_years = heloc["draw_period_years"]
    start = heloc["anniversary_count"]
    for k in range(start + 1, elapsed_anniversaries + 1):
        if k <= draw_years:
            fee = {
                "heloc_id": hid,
                "fee_type": "ANNUAL",
                "amount_cents": heloc["annual_fee_cents"],
                "settlement_status": "OUTSTANDING",
            }
            stamp_create(fee)
            db.fee_assessments[fee["id"]] = fee
    heloc["anniversary_count"] = min(elapsed_anniversaries, draw_years)
    # recompute accrued interest
    heloc["accrued_interest_cents"] = calc.chronological_accrued(heloc, new_clock)
    touch(heloc)
    return ok(public(heloc))


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
