"""Trade-in lifecycle routes (PRD 3.3-3.7).

Validation precedence per PRD 2.4:
  auth -> role -> ownership -> path existence -> body FK -> well-formedness
  -> state -> OCC -> business checks.
"""
from flask import Blueprint, request

from db import db
from errors import (err, ERR_FK_NOT_FOUND, ERR_NOT_OWNER, ERR_INVALID_STATE,
                    ERR_STALE_VERSION, ERR_MODEL_RETIRED, ERR_PROMO_INVALID,
                    ERR_UNKNOWN_DEFECT, ERR_QUOTE_EXPIRED, ERR_DATA_WIPE_REQUIRED,
                    ERR_INVALID_REQUEST)
from middleware import get_principal, require_role
from models import new_record, touch, serialize, sort_by_created
from reqs import (get_json_body, req_str, req_int, req_enum, req_bool,
                  req_str_list, parse_pagination, paginate)
from response import object_response, array_response
from util import parse_iso, new_id, iso_now
from clock import clock
from services.lookups import (get_trade_in_or_404, get_customer_or_404,
                              get_device_model_or_404, locked_quote_of,
                              quotes_for, shipping_kits_for, inspections_for,
                              payouts_for, data_wipe_certs_for,
                              disposition_records_for, get_or_404)
from services import tradein as ti
from services import calc

bp = Blueprint("tradeins", __name__)

GRADE_KEYS = {"FLAWLESS", "GOOD", "FAIR", "POOR"}
PAYOUT_METHODS = {"STORE_CREDIT", "ACH", "CHECK"}
WIPE_METHODS = {"CRYPTO_ERASE", "NIST_PURGE", "PHYSICAL_DESTROY"}
WIPE_RESULTS = {"PASS", "FAIL"}


def _ownership_check(trade_in, user_id, role):
    """Priority-3 ownership: for Customer-owned actions X-User-ID == customer_id."""
    if role == "Customer" and trade_in["customer_id"] != user_id:
        raise err(ERR_NOT_OWNER, "caller does not own this trade-in")


def _resolve_promo_active(model, campaign):
    """A promo is valid for quoting iff ACTIVE and scope matches the device
    category or is ALL (PRD 3.3/3.4)."""
    if campaign is None:
        return False
    if campaign["status"] != "ACTIVE":
        return False
    scope = campaign["category_scope"]
    return scope == "ALL" or scope == model["category"]


# ---------------------------------------------------------------- Create / read
@bp.route("/trade-ins", methods=["POST"])
def create_trade_in():
    user_id, role = get_principal()
    require_role(role, {"Customer"})
    body = get_json_body()

    # Body FK references first need to be present strings, then resolved (priority 5),
    # then full well-formedness of the rest (priority 6). Per PRD 2.4 body-FK
    # existence (5) precedes request well-formedness (6).
    customer_id = body.get("customer_id")
    device_model_id = body.get("device_model_id")
    if not isinstance(customer_id, str) or not isinstance(device_model_id, str):
        # Missing/!str FK -> treat as unresolved FK reference.
        raise err(ERR_FK_NOT_FOUND, "customer_id / device_model_id must resolve")

    customer = db.customers.get(customer_id)
    model = db.device_models.get(device_model_id)
    if customer is None or model is None:
        raise err(ERR_FK_NOT_FOUND, "customer_id / device_model_id does not resolve")

    # Ownership: a Customer may only create trade-ins for themselves.
    if role == "Customer" and customer_id != user_id:
        raise err(ERR_NOT_OWNER, "caller does not own this customer")

    # Well-formedness.
    declared_grade = req_enum(body, "declared_grade", GRADE_KEYS)
    declared_defects = req_str_list(body, "declared_defects", required=False, default=[])
    declared_powers_on = req_bool(body, "declared_powers_on", required=False, default=True)
    promo_code = req_str(body, "promo_code", required=False, default=None)

    # Resolve promo_code -> campaign (PRD 3.3). Missing/non-active/out-of-scope -> ERR_PROMO_INVALID.
    promotion_campaign_id = None
    if promo_code is not None:
        match = None
        for p in db.promotion_campaigns.values():
            if (p["catalog_id"] == model["catalog_id"]
                    and p["code"].lower() == promo_code.lower()
                    and p["status"] == "ACTIVE"):
                if p["category_scope"] == "ALL" or p["category_scope"] == model["category"]:
                    match = p
                    break
        if match is None:
            raise err(ERR_PROMO_INVALID, "promo code missing, not active, or out of scope")
        promotion_campaign_id = match["id"]

    rec = new_record("TradeIn", {
        "customer_id": customer_id,
        "device_model_id": device_model_id,
        "promotion_campaign_id": promotion_campaign_id,
        "locked_quote_id": None,
        "declared_grade": declared_grade,
        "declared_defects": declared_defects,
        "declared_powers_on": declared_powers_on,
        "status": "DRAFT",
        "final_value_cents": None,
    })
    db.trade_ins[rec["id"]] = rec
    return object_response(serialize(rec), status=201)


@bp.route("/trade-ins/<tid>", methods=["GET"])
def get_trade_in(tid):
    _, role = get_principal()
    require_role(role, {"CatalogAdmin", "FinanceOperator", "GradingAgent", "Customer"})
    rec = get_trade_in_or_404(tid)
    return object_response(serialize(rec))


@bp.route("/trade-ins", methods=["GET"])
def list_trade_ins():
    _, role = get_principal()
    require_role(role, {"CatalogAdmin", "FinanceOperator", "GradingAgent", "Customer"})
    limit, offset = parse_pagination()

    items = list(db.trade_ins.values())
    for key in ("customer_id", "device_model_id", "promotion_campaign_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [t for t in items if t.get(key) == val]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return array_response([serialize(t) for t in page], limit, offset, total)


# ---------------------------------------------------------------- Quote
@bp.route("/trade-ins/<tid>/quote", methods=["POST"])
def quote_trade_in(tid):
    user_id, role = get_principal()
    require_role(role, {"Customer"})
    trade_in = get_trade_in_or_404(tid)
    _ownership_check(trade_in, user_id, role)

    if trade_in["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "trade-in is not in DRAFT")

    model = db.device_models.get(trade_in["device_model_id"])
    catalog = db.catalogs.get(model["catalog_id"])

    # Business checks (PRD 3.4): model active, promo valid, defects known.
    if model["status"] != "ACTIVE":
        raise err(ERR_MODEL_RETIRED, "device model is retired")

    campaign = None
    if trade_in["promotion_campaign_id"] is not None:
        campaign = db.promotion_campaigns.get(trade_in["promotion_campaign_id"])
        if not _resolve_promo_active(model, campaign):
            raise err(ERR_PROMO_INVALID, "resolved promotion is no longer valid")

    for d in trade_in["declared_defects"]:
        if d not in model["defect_deductions"]:
            raise err(ERR_UNKNOWN_DEFECT, f"unknown defect: {d}")

    ti.quote_initial(trade_in, model, campaign, catalog)
    return object_response(serialize(trade_in))


# ---------------------------------------------------------------- Ship kit
@bp.route("/trade-ins/<tid>/ship-kit", methods=["POST"])
def ship_kit(tid):
    user_id, role = get_principal()
    require_role(role, {"Customer"})
    trade_in = get_trade_in_or_404(tid)
    _ownership_check(trade_in, user_id, role)

    if trade_in["status"] != "QUOTED":
        raise err(ERR_INVALID_STATE, "trade-in is not in QUOTED")

    locked = locked_quote_of(trade_in)
    if locked is not None and parse_iso(locked["lock_expires_at"]) <= clock.now():
        raise err(ERR_QUOTE_EXPIRED, "locked quote has expired")

    kit = new_record("ShippingKit", {
        "trade_in_id": trade_in["id"],
        "tracking_number": "TRK-" + new_id().replace("-", "")[:16].upper(),
        "label_url": "https://labels.example.com/" + new_id(),
        "status": "DISPATCHED",
    })
    db.shipping_kits[kit["id"]] = kit
    trade_in["status"] = "KIT_SENT"
    touch(trade_in)
    return object_response(serialize(trade_in))


# ---------------------------------------------------------------- Receive
@bp.route("/trade-ins/<tid>/receive", methods=["POST"])
def receive(tid):
    _, role = get_principal()
    require_role(role, {"GradingAgent"})
    trade_in = get_trade_in_or_404(tid)

    if trade_in["status"] != "KIT_SENT":
        raise err(ERR_INVALID_STATE, "trade-in is not in KIT_SENT")

    locked = locked_quote_of(trade_in)
    if locked is not None and parse_iso(locked["lock_expires_at"]) <= clock.now():
        raise err(ERR_QUOTE_EXPIRED, "locked quote has expired")

    kits = shipping_kits_for(trade_in["id"])
    for kit in kits:
        if kit["status"] != "DELIVERED_TO_HUB":
            kit["status"] = "DELIVERED_TO_HUB"
            touch(kit)
    trade_in["status"] = "RECEIVED"
    touch(trade_in)
    return object_response(serialize(trade_in))


def _validate_verified_inputs(body, model):
    verified_grade = req_enum(body, "verified_grade", GRADE_KEYS)
    verified_defects = req_str_list(body, "verified_defects", required=False, default=[])
    verified_powers_on = req_bool(body, "verified_powers_on")
    for d in verified_defects:
        if d not in model["defect_deductions"]:
            raise err(ERR_UNKNOWN_DEFECT, f"unknown defect: {d}")
    return verified_grade, verified_defects, verified_powers_on


# ---------------------------------------------------------------- Inspect
@bp.route("/trade-ins/<tid>/inspect", methods=["POST"])
def inspect(tid):
    _, role = get_principal()
    require_role(role, {"GradingAgent"})
    trade_in = get_trade_in_or_404(tid)
    body = get_json_body()

    if trade_in["status"] != "RECEIVED":
        raise err(ERR_INVALID_STATE, "trade-in is not in RECEIVED")

    model = db.device_models.get(trade_in["device_model_id"])
    catalog = db.catalogs.get(model["catalog_id"])
    verified_grade, verified_defects, verified_powers_on = _validate_verified_inputs(body, model)

    # RECEIVED -> INSPECTED -> {ACCEPTED|REQUOTED|RECYCLED}. INSPECTED is a
    # transient pivot never observed by a client, so the trade-in receives a
    # single net version bump for the whole /inspect request (the branch helper
    # performs the one touch on the trade-in).
    trade_in["status"] = "INSPECTED"
    _, inspected_value, outcome = ti.run_inspection(
        trade_in, model, catalog, verified_grade, verified_defects, verified_powers_on)

    if outcome == "MATCH":
        ti.apply_match(trade_in)
    elif outcome == "REQUOTE":
        ti.apply_requote(trade_in, inspected_value, catalog)
    else:  # RECYCLE
        ti.apply_recycle(trade_in)

    return object_response(serialize(trade_in))


# ---------------------------------------------------------------- Reinspect
@bp.route("/trade-ins/<tid>/reinspect", methods=["POST"])
def reinspect(tid):
    _, role = get_principal()
    require_role(role, {"GradingAgent"})
    trade_in = get_trade_in_or_404(tid)
    body = get_json_body()

    if trade_in["status"] != "REQUOTED":
        raise err(ERR_INVALID_STATE, "trade-in is not in REQUOTED")

    model = db.device_models.get(trade_in["device_model_id"])
    catalog = db.catalogs.get(model["catalog_id"])
    verified_grade, verified_defects, verified_powers_on = _validate_verified_inputs(body, model)

    # Compute outcome against the currently-locked REQUOTE quote. Only a fresh
    # downgrade (REQUOTE outcome) is in scope; MATCH/RECYCLE -> ERR_INVALID_STATE.
    inspected_value = calc.graded_value(model, verified_grade, verified_defects,
                                        verified_powers_on)
    locked = locked_quote_of(trade_in)
    locked_amount = locked["amount_cents"] if locked else 0
    outcome = calc.inspection_outcome(
        inspected_value, locked_amount,
        catalog["requote_tolerance_pct"], catalog["recycle_floor_value_cents"])
    if outcome != "REQUOTE":
        raise err(ERR_INVALID_STATE, "re-inspection must yield a downgrade above the recycle floor")

    # Record a second Inspection.
    insp = new_record("Inspection", {
        "trade_in_id": trade_in["id"],
        "graded_at": iso_now(clock.now()),
        "verified_grade": verified_grade,
        "verified_defects": verified_defects,
        "verified_powers_on": verified_powers_on,
        "inspected_value_cents": inspected_value,
        "outcome": outcome,
    })
    db.inspections[insp["id"]] = insp

    # Supersede current REQUOTE quote, mint a new LOCKED REQUOTE quote.
    if locked is not None:
        locked["status"] = "SUPERSEDED"
        touch(locked)
    new_q = ti.make_quote(trade_in, "REQUOTE", inspected_value, 0, inspected_value,
                          catalog["price_lock_hours"])
    trade_in["locked_quote_id"] = new_q["id"]
    touch(trade_in)  # advances version -> stale-version guard for pending decisions
    return object_response(serialize(trade_in))


# ---------------------------------------------------------------- Accept / decline requote
def _check_occ(trade_in, body):
    if "expected_trade_in_version" not in body or body["expected_trade_in_version"] is None:
        raise err(ERR_INVALID_REQUEST, "missing required field: expected_trade_in_version")
    expected = body["expected_trade_in_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err(ERR_INVALID_REQUEST, "expected_trade_in_version must be an integer")
    if expected != trade_in["version"]:
        raise err(ERR_STALE_VERSION, "expected_trade_in_version does not match")


@bp.route("/trade-ins/<tid>/accept-requote", methods=["POST"])
def accept_requote(tid):
    user_id, role = get_principal()
    require_role(role, {"Customer"})
    trade_in = get_trade_in_or_404(tid)
    _ownership_check(trade_in, user_id, role)
    body = get_json_body()

    if trade_in["status"] != "REQUOTED":
        raise err(ERR_INVALID_STATE, "trade-in is not in REQUOTED")

    _check_occ(trade_in, body)

    locked = locked_quote_of(trade_in)
    if locked is not None and parse_iso(locked["lock_expires_at"]) <= clock.now():
        raise err(ERR_QUOTE_EXPIRED, "re-quote has expired")

    locked["status"] = "HONORED"
    touch(locked)
    trade_in["status"] = "ACCEPTED"
    trade_in["final_value_cents"] = locked["amount_cents"]
    touch(trade_in)
    return object_response(serialize(trade_in))


@bp.route("/trade-ins/<tid>/decline-requote", methods=["POST"])
def decline_requote(tid):
    user_id, role = get_principal()
    require_role(role, {"Customer"})
    trade_in = get_trade_in_or_404(tid)
    _ownership_check(trade_in, user_id, role)
    body = get_json_body()

    if trade_in["status"] != "REQUOTED":
        raise err(ERR_INVALID_STATE, "trade-in is not in REQUOTED")

    _check_occ(trade_in, body)

    reason = req_str(body, "reason", required=False, default=None)
    locked = locked_quote_of(trade_in)
    if locked is not None:
        locked["status"] = "SUPERSEDED"
        touch(locked)
    ti.make_disposition(trade_in, "RETURN_TO_CUSTOMER", reason)
    trade_in["status"] = "REJECTED"
    touch(trade_in)
    return object_response(serialize(trade_in))


# ---------------------------------------------------------------- Cancel
@bp.route("/trade-ins/<tid>/cancel", methods=["POST"])
def cancel(tid):
    user_id, role = get_principal()
    require_role(role, {"Customer"})
    trade_in = get_trade_in_or_404(tid)
    _ownership_check(trade_in, user_id, role)

    if trade_in["status"] not in ("DRAFT", "QUOTED"):
        raise err(ERR_INVALID_STATE, "trade-in cannot be cancelled from its current state")

    if trade_in["status"] == "QUOTED":
        locked = locked_quote_of(trade_in)
        if locked is not None:
            locked["status"] = "SUPERSEDED"
            touch(locked)
    trade_in["status"] = "CANCELLED"
    touch(trade_in)
    return object_response(serialize(trade_in))


# ---------------------------------------------------------------- Sweep expiry
@bp.route("/trade-ins/<tid>/sweep-expiry", methods=["POST"])
def sweep_expiry(tid):
    _, role = get_principal()
    require_role(role, {"CatalogAdmin"})
    trade_in = get_trade_in_or_404(tid)

    if trade_in["status"] not in ("QUOTED", "KIT_SENT"):
        raise err(ERR_INVALID_STATE, "trade-in is not in a sweepable state")

    locked = locked_quote_of(trade_in)
    if locked is None or not (clock.now() > parse_iso(locked["lock_expires_at"])):
        raise err(ERR_INVALID_STATE, "locked quote has not expired")

    locked["status"] = "EXPIRED"
    touch(locked)
    trade_in["status"] = "EXPIRED"
    touch(trade_in)
    return object_response(serialize(trade_in))


# ---------------------------------------------------------------- Data-wipe
@bp.route("/trade-ins/<tid>/data-wipe", methods=["POST"])
def data_wipe(tid):
    _, role = get_principal()
    require_role(role, {"GradingAgent"})
    trade_in = get_trade_in_or_404(tid)
    body = get_json_body()

    method = req_enum(body, "method", WIPE_METHODS)
    result = req_enum(body, "result", WIPE_RESULTS)

    rec = new_record("DataWipeCertificate", {
        "trade_in_id": trade_in["id"],
        "method": method,
        "result": result,
        "certificate_serial": "DWC-" + new_id().replace("-", "")[:16].upper(),
    })
    db.data_wipe_certificates[rec["id"]] = rec
    return object_response(serialize(rec), status=201)


# ---------------------------------------------------------------- Payouts
@bp.route("/trade-ins/<tid>/payouts", methods=["POST"])
def create_payout(tid):
    _, role = get_principal()
    require_role(role, {"FinanceOperator"})
    trade_in = get_trade_in_or_404(tid)
    body = get_json_body()

    if trade_in["status"] != "ACCEPTED":
        raise err(ERR_INVALID_STATE, "trade-in is not in ACCEPTED")

    method = req_enum(body, "method", PAYOUT_METHODS)

    model = db.device_models.get(trade_in["device_model_id"])
    catalog = db.catalogs.get(model["catalog_id"])
    # Data-wipe safety gate.
    if model["category"] in catalog["data_wipe_required_categories"]:
        has_pass = any(c["result"] == "PASS" for c in data_wipe_certs_for(trade_in["id"]))
        if not has_pass:
            raise err(ERR_DATA_WIPE_REQUIRED, "a passing data-wipe certificate is required")

    amount = trade_in["final_value_cents"]
    customer = db.customers.get(trade_in["customer_id"])

    payout = new_record("Payout", {
        "trade_in_id": trade_in["id"],
        "customer_id": trade_in["customer_id"],
        "method": method,
        "amount_cents": amount,
        "status": "PAID",
    })
    db.payouts[payout["id"]] = payout

    # Wallet ledger.
    if method == "STORE_CREDIT":
        customer["wallet_balance_cents"] += amount
    customer["lifetime_payout_cents"] += amount
    touch(customer)

    # Refurbish disposition.
    ti.make_disposition(trade_in, "REFURBISH_INVENTORY")

    trade_in["status"] = "PAID"
    touch(trade_in)
    return object_response(serialize(payout), status=201)


@bp.route("/trade-ins/<tid>/payouts/<payout_id>/reverse", methods=["POST"])
def reverse_payout(tid, payout_id):
    _, role = get_principal()
    require_role(role, {"FinanceOperator"})
    # Left-to-right path validation: trade-in first, then payout.
    trade_in = get_trade_in_or_404(tid)
    payout = db.payouts.get(payout_id)
    if payout is None or payout["trade_in_id"] != tid:
        from errors import ERR_NOT_FOUND
        raise err(ERR_NOT_FOUND, "payout not found under this trade-in")

    if payout["status"] != "PAID":
        raise err(ERR_INVALID_STATE, "payout is not PAID")

    customer = db.customers.get(payout["customer_id"])
    if payout["method"] == "STORE_CREDIT":
        customer["wallet_balance_cents"] -= payout["amount_cents"]
    customer["lifetime_payout_cents"] -= payout["amount_cents"]
    touch(customer)

    payout["status"] = "REVERSED"
    touch(payout)
    return object_response(serialize(payout))


# ---------------------------------------------------------------- Child reads
@bp.route("/trade-ins/<tid>/quotes", methods=["GET"])
def list_quotes(tid):
    _, role = get_principal()
    require_role(role, {"CatalogAdmin", "FinanceOperator", "GradingAgent", "Customer"})
    get_trade_in_or_404(tid)
    limit, offset = parse_pagination()
    items = quotes_for(tid)
    page, total = paginate(items, limit, offset)
    return array_response([serialize(q) for q in page], limit, offset, total)


@bp.route("/trade-ins/<tid>/shipping-kits", methods=["GET"])
def list_shipping_kits(tid):
    _, role = get_principal()
    require_role(role, {"CatalogAdmin", "GradingAgent", "Customer"})
    get_trade_in_or_404(tid)
    limit, offset = parse_pagination()
    items = shipping_kits_for(tid)
    page, total = paginate(items, limit, offset)
    return array_response([serialize(k) for k in page], limit, offset, total)


@bp.route("/trade-ins/<tid>/inspections", methods=["GET"])
def list_inspections(tid):
    _, role = get_principal()
    require_role(role, {"CatalogAdmin", "FinanceOperator", "GradingAgent", "Customer"})
    get_trade_in_or_404(tid)
    limit, offset = parse_pagination()
    items = inspections_for(tid)
    page, total = paginate(items, limit, offset)
    return array_response([serialize(i) for i in page], limit, offset, total)


@bp.route("/trade-ins/<tid>/data-wipe-certificates", methods=["GET"])
def list_data_wipe_certs(tid):
    _, role = get_principal()
    require_role(role, {"CatalogAdmin", "FinanceOperator", "GradingAgent", "Customer"})
    get_trade_in_or_404(tid)
    limit, offset = parse_pagination()
    items = data_wipe_certs_for(tid)
    page, total = paginate(items, limit, offset)
    return array_response([serialize(c) for c in page], limit, offset, total)


@bp.route("/trade-ins/<tid>/payouts", methods=["GET"])
def list_payouts(tid):
    _, role = get_principal()
    require_role(role, {"CatalogAdmin", "FinanceOperator", "Customer"})
    get_trade_in_or_404(tid)
    limit, offset = parse_pagination()
    items = payouts_for(tid)
    page, total = paginate(items, limit, offset)
    return array_response([serialize(p) for p in page], limit, offset, total)


@bp.route("/payouts/<pid>", methods=["GET"])
def get_payout(pid):
    _, role = get_principal()
    require_role(role, {"CatalogAdmin", "FinanceOperator", "Customer"})
    rec = get_or_404(db.payouts, pid)
    return object_response(serialize(rec))


@bp.route("/trade-ins/<tid>/disposition-records", methods=["GET"])
def list_disposition_records(tid):
    _, role = get_principal()
    require_role(role, {"CatalogAdmin", "GradingAgent", "Customer"})
    get_trade_in_or_404(tid)
    limit, offset = parse_pagination()
    items = disposition_records_for(tid)
    page, total = paginate(items, limit, offset)
    return array_response([serialize(d) for d in page], limit, offset, total)
