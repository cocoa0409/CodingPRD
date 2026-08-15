"""Remittance batches, items, exception items, image retrieval requests."""
from datetime import timedelta
from zoneinfo import ZoneInfo

from appobj import api
from store import (
    banks, customers, agreements, sites, formats, batches, items, exceptions,
    image_requests,
)
from util import (
    ApiError, ok, body, req_str, opt_str, req_int, req_enum, req_dt_field,
    new_entity, touch, pub, list_response, invalid, fmt, now,
)
from helpers import (
    auth, require_role, scope, R_bank, R_customer, R_agreement, R_site, R_batch,
    R_item, R_exception, R_image, check_posture, bad_state, batch_pub,
    batch_items, assign_availability, open_cycle, apply_decision,
    auto_decision_moment, emit_incident,
)
import re

LO = {"LockboxOperator"}
CO = {"CustomerOperator"}
ROUTING_RE = re.compile(r"^\d{9}$")
REASON_CODES = {"AMOUNT_MISMATCH", "PAYEE_MISMATCH", "MISSING_INVOICE_REF",
                "STALE_DATED", "DUPLICATE_SUSPECTED"}
DECISIONS = {"PAY", "RETURN"}
REQ_REASONS = {"AUDIT", "DISPUTE_SUPPORT", "RESEARCH", "LEGAL"}
IMAGE_KINDS = {"CHECK_FRONT", "CHECK_BACK", "REMIT_STUB", "ENVELOPE"}
TERMINAL_ITEM = {"ACCEPTED", "RETURNED", "DECISIONED_PAY", "DECISIONED_RETURN"}


def _resolve_batch(bankId, customerId, agreementId, siteId, batchId,
                   uid=None, role=None):
    bank = R_bank(bankId)
    c = R_customer(bank, customerId, uid, role)
    a = R_agreement(c, agreementId)
    s = R_site(a, siteId)
    b = R_batch(s, batchId)
    return bank, c, a, s, b


def _resolve_item(bankId, customerId, agreementId, siteId, batchId, itemId,
                  uid=None, role=None):
    bank, c, a, s, b = _resolve_batch(bankId, customerId, agreementId, siteId,
                                      batchId, uid, role)
    it = R_item(b, itemId)
    return bank, c, a, s, b, it


# ---------------------------------------------------------------------------
# Batches
# ---------------------------------------------------------------------------

@api.post("/banks/<bankId>/customers/<customerId>/agreements/<agreementId>/sites/<siteId>/batches")
def create_batch(bankId, customerId, agreementId, siteId):
    uid, role = auth()
    require_role(role, LO)
    bank = R_bank(bankId)
    c = R_customer(bank, customerId)
    a = R_agreement(c, agreementId)
    s = R_site(a, siteId)
    b = body()
    ref = req_str(b, "batch_reference")
    received = req_dt_field(b, "received_at")
    decl_count = req_int(b, "declared_item_count", minv=0)
    decl_total = req_int(b, "declared_total_cents", minv=0)
    check_posture(bank)
    if s["status"] != "LIVE":
        raise ApiError("ERR_SITE_NOT_LIVE", 409, "site is not LIVE")
    if c["status"] != "ACTIVE":
        raise ApiError("ERR_CUSTOMER_NOT_ACTIVE", 409, "customer is not ACTIVE")
    # business_date rollover: received-at vs site cutoff in the site's timezone
    received_local = received.astimezone(ZoneInfo(s["timezone"]))
    hh, mm = (int(x) for x in s["daily_cutoff_time_local"].split(":"))
    cutoff = received_local.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if received_local < cutoff:
        business_date = bank["current_business_date"]
    else:
        from util import add_business_days, parse_date
        business_date = add_business_days(
            parse_date(bank["current_business_date"]), 1).isoformat()
    for other in batches.values():
        if (other["site_id"] == s["id"] and other["business_date"] == business_date
                and other["batch_reference"] == ref):
            raise ApiError("ERR_DUPLICATE_UNIQUE_FIELD", 409,
                           "batch_reference already used for this site and business date")
    bt = new_entity({
        "site_id": s["id"],
        "agreement_id": a["id"],
        "customer_id": c["id"],
        "bank_id": bank["id"],
        "batch_reference": ref,
        "business_date": business_date,
        "received_at": fmt(received),
        "declared_item_count": decl_count,
        "declared_total_cents": decl_total,
        "captured_item_count": 0,
        "captured_total_cents": 0,
        "accepted_item_count": 0,
        "accepted_total_cents": 0,
        "same_day_credit_cents": 0,
        "capture_status": "RECEIVED",
        "transmission_status": "PENDING",
        "_compound": "OPEN",
        "_held": False,
        "_captured_by": None,
    })
    batches[bt["id"]] = bt
    return ok(batch_pub(bt), "object", 201)


@api.get("/banks/<bankId>/customers/<customerId>/agreements/<agreementId>/sites/<siteId>/batches/<batchId>")
def get_batch(bankId, customerId, agreementId, siteId, batchId):
    uid, role = auth()
    bank, c, a, s, bt = _resolve_batch(bankId, customerId, agreementId, siteId,
                                       batchId, uid, role)
    return ok(batch_pub(bt))


@api.get("/banks/<bankId>/customers/<customerId>/agreements/<agreementId>/sites/<siteId>/batches")
def list_batches(bankId, customerId, agreementId, siteId):
    uid, role = auth()
    bank = R_bank(bankId)
    c = R_customer(bank, customerId, uid, role)
    a = R_agreement(c, agreementId)
    s = R_site(a, siteId)
    rows = [bt for bt in batches.values() if bt["site_id"] == s["id"]]
    rows2 = []
    from flask import request
    bs_filter = request.args.get("batch_status")
    for bt in rows:
        if bs_filter is not None:
            from helpers import compound_status
            if compound_status(bt) != bs_filter:
                continue
        rows2.append(bt)
    return list_response(
        rows2, ["capture_status", "transmission_status", "business_date"],
        serialize=batch_pub)


def _batch_transition(bankId, customerId, agreementId, siteId, batchId, uid, role):
    bank, c, a, s, bt = _resolve_batch(bankId, customerId, agreementId, siteId, batchId)
    check_posture(bank)
    return bank, c, a, s, bt


@api.post("/banks/<bankId>/customers/<customerId>/agreements/<agreementId>/sites/<siteId>/batches/<batchId>/begin_capture")
def begin_capture(bankId, customerId, agreementId, siteId, batchId):
    uid, role = auth()
    require_role(role, LO)
    bank, c, a, s, bt = _batch_transition(bankId, customerId, agreementId,
                                          siteId, batchId, uid, role)
    if s["status"] != "LIVE":
        raise ApiError("ERR_SITE_NOT_LIVE", 409, "site is not LIVE")
    if bt["capture_status"] != "RECEIVED":
        bad_state("batch is not RECEIVED")
    bt["capture_status"] = "CAPTURING"
    bt["_captured_by"] = uid
    touch(bt)
    return ok(batch_pub(bt))


@api.post("/banks/<bankId>/customers/<customerId>/agreements/<agreementId>/sites/<siteId>/batches/<batchId>/balance")
def balance_batch(bankId, customerId, agreementId, siteId, batchId):
    uid, role = auth()
    require_role(role, LO)
    bank, c, a, s, bt = _batch_transition(bankId, customerId, agreementId,
                                          siteId, batchId, uid, role)
    if bt["capture_status"] != "CAPTURING":
        bad_state("batch is not CAPTURING")
    if (bt["captured_item_count"] == bt["declared_item_count"]
            and bt["captured_total_cents"] == bt["declared_total_cents"]):
        bt["capture_status"] = "BALANCED"
        touch(bt)
        return ok(batch_pub(bt))
    bt["capture_status"] = "OUT_OF_BALANCE"
    touch(bt)
    raise ApiError("ERR_BATCH_OUT_OF_BALANCE", 409,
                   "captured tallies do not match the courier manifest")


@api.post("/banks/<bankId>/customers/<customerId>/agreements/<agreementId>/sites/<siteId>/batches/<batchId>/force_out_of_balance")
def force_out_of_balance(bankId, customerId, agreementId, siteId, batchId):
    uid, role = auth()
    require_role(role, LO)
    bank, c, a, s, bt = _batch_transition(bankId, customerId, agreementId,
                                          siteId, batchId, uid, role)
    if bt["capture_status"] != "CAPTURING":
        bad_state("batch is not CAPTURING")
    bt["capture_status"] = "OUT_OF_BALANCE"
    touch(bt)
    return ok(batch_pub(bt))


@api.post("/banks/<bankId>/customers/<customerId>/agreements/<agreementId>/sites/<siteId>/batches/<batchId>/resume_capture")
def resume_capture(bankId, customerId, agreementId, siteId, batchId):
    uid, role = auth()
    require_role(role, LO)
    bank, c, a, s, bt = _batch_transition(bankId, customerId, agreementId,
                                          siteId, batchId, uid, role)
    if bt["capture_status"] != "OUT_OF_BALANCE":
        bad_state("batch is not OUT_OF_BALANCE")
    bt["capture_status"] = "CAPTURING"
    touch(bt)
    return ok(batch_pub(bt))


@api.post("/banks/<bankId>/customers/<customerId>/agreements/<agreementId>/sites/<siteId>/batches/<batchId>/close")
def close_batch(bankId, customerId, agreementId, siteId, batchId):
    uid, role = auth()
    require_role(role, LO)
    bank, c, a, s, bt = _batch_transition(bankId, customerId, agreementId,
                                          siteId, batchId, uid, role)
    if bt["capture_status"] != "BALANCED":
        bad_state("batch is not BALANCED")
    for it in batch_items(bt["id"]):
        if it["status"] not in TERMINAL_ITEM:
            bad_state("all items must be dispositioned before close")
    if bt["_captured_by"] == uid:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 409,
                       "closer must differ from the operator who began capture")
    bt["capture_status"] = "CLOSED"
    any_returned = any(i["status"] in ("RETURNED", "DECISIONED_RETURN")
                       for i in batch_items(bt["id"]))
    bt["_compound"] = "REJECTED" if any_returned else "READY_TO_SETTLE"
    touch(bt)
    return ok(batch_pub(bt))


@api.post("/banks/<bankId>/customers/<customerId>/agreements/<agreementId>/sites/<siteId>/batches/<batchId>/transmit")
def transmit_batch(bankId, customerId, agreementId, siteId, batchId):
    uid, role = auth()
    require_role(role, LO)
    bank, c, a, s, bt = _batch_transition(bankId, customerId, agreementId,
                                          siteId, batchId, uid, role)
    if bt["transmission_status"] not in ("PENDING", "TRANSMISSION_FAILED"):
        bad_state("batch transmission is not PENDING or TRANSMISSION_FAILED")
    if bt["capture_status"] != "CLOSED":
        bad_state("batch capture is not CLOSED")
    if not any(f["agreement_id"] == a["id"] and f["status"] == "ACTIVE"
               for f in formats.values()):
        raise ApiError("ERR_TRANSMISSION_FORMAT_INACTIVE", 409,
                       "no ACTIVE transmission format exists for the agreement")
    bt["transmission_status"] = "TRANSMITTED"
    touch(bt)
    return ok(batch_pub(bt))


@api.post("/banks/<bankId>/customers/<customerId>/agreements/<agreementId>/sites/<siteId>/batches/<batchId>/acknowledge_transmission")
def acknowledge_transmission(bankId, customerId, agreementId, siteId, batchId):
    uid, role = auth()
    require_role(role, CO)
    bank, c, a, s, bt = _batch_transition(bankId, customerId, agreementId,
                                          siteId, batchId, uid, role)
    scope(uid, role, bt["customer_id"])
    if bt["transmission_status"] != "TRANSMITTED":
        bad_state("batch transmission is not TRANSMITTED")
    bt["transmission_status"] = "ACKED"
    touch(bt)
    return ok(batch_pub(bt))


@api.post("/banks/<bankId>/customers/<customerId>/agreements/<agreementId>/sites/<siteId>/batches/<batchId>/mark_transmission_failed")
def mark_transmission_failed(bankId, customerId, agreementId, siteId, batchId):
    uid, role = auth()
    require_role(role, LO)
    bank, c, a, s, bt = _batch_transition(bankId, customerId, agreementId,
                                          siteId, batchId, uid, role)
    if bt["transmission_status"] != "TRANSMITTED":
        bad_state("batch transmission is not TRANSMITTED")
    bt["transmission_status"] = "TRANSMISSION_FAILED"
    touch(bt)
    return ok(batch_pub(bt))


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------

@api.post("/banks/<bankId>/customers/<customerId>/agreements/<agreementId>/sites/<siteId>/batches/<batchId>/items")
def create_item(bankId, customerId, agreementId, siteId, batchId):
    uid, role = auth()
    require_role(role, LO)
    bank, c, a, s, bt = _resolve_batch(bankId, customerId, agreementId, siteId, batchId)
    b = body()
    check_number = req_str(b, "check_number")
    payer_rt = req_str(b, "payer_routing_number")
    if not ROUTING_RE.match(payer_rt):
        invalid("payer_routing_number must be a 9-digit ABA number")
    amount = req_int(b, "amount_cents", minv=1)
    payee = req_str(b, "payee_name")
    invoice_ref = opt_str(b, "invoice_reference")
    check_posture(bank)
    if bt["capture_status"] != "CAPTURING":
        bad_state("batch is not CAPTURING")
    it = new_entity({
        "batch_id": bt["id"],
        "site_id": s["id"],
        "customer_id": c["id"],
        "bank_id": bank["id"],
        "check_number": check_number,
        "payer_routing_number": payer_rt,
        "amount_cents": amount,
        "payee_name": payee,
        "invoice_reference": invoice_ref,
        "availability_tier": None,
        "availability_date": None,
        "status": "CAPTURED",
    })
    items[it["id"]] = it
    bt["captured_item_count"] += 1
    bt["captured_total_cents"] += amount
    touch(bt)
    return ok(pub(it), "object", 201)


@api.get("/banks/<bankId>/customers/<customerId>/agreements/<agreementId>/sites/<siteId>/batches/<batchId>/items/<itemId>")
def get_item(bankId, customerId, agreementId, siteId, batchId, itemId):
    uid, role = auth()
    bank, c, a, s, bt, it = _resolve_item(bankId, customerId, agreementId,
                                          siteId, batchId, itemId, uid, role)
    return ok(pub(it))


@api.get("/banks/<bankId>/customers/<customerId>/agreements/<agreementId>/sites/<siteId>/batches/<batchId>/items")
def list_items(bankId, customerId, agreementId, siteId, batchId):
    uid, role = auth()
    bank, c, a, s, bt = _resolve_batch(bankId, customerId, agreementId, siteId,
                                       batchId, uid, role)
    rows = batch_items(bt["id"])
    return list_response(rows, ["status", "availability_tier"])


@api.post("/banks/<bankId>/customers/<customerId>/agreements/<agreementId>/sites/<siteId>/batches/<batchId>/items/<itemId>/accept")
def accept_item(bankId, customerId, agreementId, siteId, batchId, itemId):
    uid, role = auth()
    require_role(role, LO)
    bank, c, a, s, bt, it = _resolve_item(bankId, customerId, agreementId,
                                          siteId, batchId, itemId)
    check_posture(bank)
    if it["status"] != "CAPTURED":
        raise ApiError("ERR_ITEM_NOT_IN_CAPTURED_STATE", 409,
                       "item is not in CAPTURED status")
    if bt["capture_status"] not in ("CAPTURING", "BALANCED"):
        bad_state("batch capture is not CAPTURING or BALANCED")
    tier, avail = assign_availability(s, it, bt["business_date"])
    it["availability_tier"] = tier
    it["availability_date"] = avail
    it["status"] = "ACCEPTED"
    touch(it)
    bt["accepted_item_count"] += 1
    bt["accepted_total_cents"] += it["amount_cents"]
    if tier == "SAME_DAY":
        bt["same_day_credit_cents"] += it["amount_cents"]
    touch(bt)
    cyc = open_cycle(c["id"])
    if cyc:
        cyc["accepted_item_count"] += 1
        touch(cyc)
    return ok(pub(it))


@api.post("/banks/<bankId>/customers/<customerId>/agreements/<agreementId>/sites/<siteId>/batches/<batchId>/items/<itemId>/return")
def return_item(bankId, customerId, agreementId, siteId, batchId, itemId):
    uid, role = auth()
    require_role(role, LO)
    bank, c, a, s, bt, it = _resolve_item(bankId, customerId, agreementId,
                                          siteId, batchId, itemId)
    check_posture(bank)
    if it["status"] != "CAPTURED":
        raise ApiError("ERR_ITEM_NOT_IN_CAPTURED_STATE", 409,
                       "item is not in CAPTURED status")
    it["status"] = "RETURNED"
    touch(it)
    touch(bt)
    return ok(pub(it))


@api.post("/banks/<bankId>/customers/<customerId>/agreements/<agreementId>/sites/<siteId>/batches/<batchId>/items/<itemId>/raise_exception")
def raise_exception(bankId, customerId, agreementId, siteId, batchId, itemId):
    uid, role = auth()
    require_role(role, LO)
    bank, c, a, s, bt, it = _resolve_item(bankId, customerId, agreementId,
                                          siteId, batchId, itemId)
    b = body()
    reason = req_enum(b, "reason_code", REASON_CODES)
    default_decision = req_enum(b, "default_decision", DECISIONS)
    check_posture(bank)
    if it["status"] != "CAPTURED":
        raise ApiError("ERR_ITEM_NOT_IN_CAPTURED_STATE", 409,
                       "item is not in CAPTURED status")
    auto_dt, auto_date = auto_decision_moment(bank, s)
    ex = new_entity({
        "item_id": it["id"],
        "batch_id": bt["id"],
        "customer_id": c["id"],
        "bank_id": bank["id"],
        "reason_code": reason,
        "default_decision": default_decision,
        "auto_decision_at": fmt(auto_dt),
        "decision": None,
        "decided_by_user_id": None,
        "decided_at": None,
        "status": "PENDING",
        "_raised_by": uid,
        "_auto_date": auto_date,
    })
    exceptions[ex["id"]] = ex
    it["status"] = "ON_EXCEPTION"
    touch(it)
    touch(bt)
    return ok(pub(ex), "object", 200)


# ---------------------------------------------------------------------------
# Exception items
# ---------------------------------------------------------------------------

@api.get("/banks/<bankId>/customers/<customerId>/exception_items/<exceptionItemId>")
def get_exception(bankId, customerId, exceptionItemId):
    uid, role = auth()
    bank = R_bank(bankId)
    c = R_customer(bank, customerId, uid, role)
    ex = R_exception(c, exceptionItemId)
    return ok(pub(ex))


@api.get("/banks/<bankId>/customers/<customerId>/exception_items")
def list_exceptions(bankId, customerId):
    uid, role = auth()
    bank = R_bank(bankId)
    c = R_customer(bank, customerId, uid, role)
    rows = [e for e in exceptions.values() if e["customer_id"] == c["id"]]
    return list_response(rows, ["status", "reason_code", "batch_id"])


@api.post("/banks/<bankId>/customers/<customerId>/exception_items/<exceptionItemId>/decide")
def decide_exception(bankId, customerId, exceptionItemId):
    uid, role = auth()
    require_role(role, CO)
    bank = R_bank(bankId)
    c = R_customer(bank, customerId, uid, role)
    ex = R_exception(c, exceptionItemId)
    b = body()
    decision = req_enum(b, "decision", DECISIONS)
    check_posture(bank)
    if ex["status"] not in ("PENDING", "ESCALATED"):
        raise ApiError("ERR_EXCEPTION_ALREADY_DECIDED", 409,
                       "exception is not pending a decision")
    if ex["_raised_by"] == uid:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 409,
                       "decider must differ from the operator who raised the exception")
    if bank["current_business_date"] > ex["_auto_date"]:
        raise ApiError("ERR_AUTO_DECISION_IMMUTABLE", 409,
                       "the auto-decision moment has passed; the system owns this exception")
    apply_decision(bank, ex, decision, uid, fmt(now()), False)
    return ok(pub(ex))


@api.post("/banks/<bankId>/customers/<customerId>/exception_items/<exceptionItemId>/escalate")
def escalate_exception(bankId, customerId, exceptionItemId):
    uid, role = auth()
    require_role(role, CO)
    bank = R_bank(bankId)
    c = R_customer(bank, customerId, uid, role)
    ex = R_exception(c, exceptionItemId)
    check_posture(bank)
    if ex["status"] != "PENDING":
        bad_state("only a PENDING exception can be escalated")
    it = items[ex["item_id"]]
    bt = batches[ex["batch_id"]]
    site = sites[bt["site_id"]]
    from datetime import datetime, time as dtime
    from util import parse_date, add_business_days
    new_date = add_business_days(parse_date(ex["_auto_date"]), 1)
    hh, mm = (int(x) for x in site["daily_cutoff_time_local"].split(":"))
    dt = datetime.combine(new_date, dtime(hh, mm), tzinfo=ZoneInfo(site["timezone"]))
    ex["auto_decision_at"] = fmt(dt)
    ex["_auto_date"] = new_date.isoformat()
    ex["status"] = "ESCALATED"
    touch(ex)
    return ok(pub(ex))


# ---------------------------------------------------------------------------
# Image retrieval requests
# ---------------------------------------------------------------------------

def _add_years(dt, years):
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:
        return dt.replace(month=2, day=28, year=dt.year + years)


@api.post("/banks/<bankId>/customers/<customerId>/image_requests")
def create_image_request(bankId, customerId):
    uid, role = auth()
    require_role(role, CO)
    bank = R_bank(bankId)
    c = R_customer(bank, customerId, uid, role)
    b = body()
    item_id = req_str(b, "item_id")
    reason = req_enum(b, "request_reason", REQ_REASONS)
    kinds = b.get("requested_image_kinds")
    if (not isinstance(kinds, list) or not kinds
            or any(k not in IMAGE_KINDS for k in kinds)):
        invalid("requested_image_kinds must be a non-empty subset of CHECK_FRONT, CHECK_BACK, REMIT_STUB, ENVELOPE")
    check_posture(bank)
    it = items.get(item_id)
    if not it or it["bank_id"] != bank["id"] or it["customer_id"] != c["id"]:
        raise ApiError("ERR_INVALID_REFERENCE", 409,
                       "item_id does not resolve to an item of this customer")
    if c["status"] != "ACTIVE":
        raise ApiError("ERR_CUSTOMER_NOT_ACTIVE", 409, "customer is not ACTIVE")
    retention = _add_years(parse_dt_utc(it["created_at"]), 7)
    n = now()
    status = "DENIED" if n > retention else "REQUESTED"
    r = new_entity({
        "customer_id": c["id"],
        "bank_id": bank["id"],
        "item_id": it["id"],
        "request_reason": reason,
        "requested_image_kinds": kinds,
        "fulfillment_uri": None,
        "retention_expires_at": fmt(retention),
        "sla_due_at": fmt(n + timedelta(hours=1)),
        "fulfilled_at": None,
        "status": status,
    })
    image_requests[r["id"]] = r
    return ok(pub(r), "object", 201)


def parse_dt_utc(s):
    from util import parse_dt
    return parse_dt(s)


@api.get("/banks/<bankId>/customers/<customerId>/image_requests/<requestId>")
def get_image_request(bankId, customerId, requestId):
    uid, role = auth()
    bank = R_bank(bankId)
    c = R_customer(bank, customerId, uid, role)
    r = R_image(c, requestId)
    return ok(pub(r))


@api.get("/banks/<bankId>/customers/<customerId>/image_requests")
def list_image_requests(bankId, customerId):
    uid, role = auth()
    bank = R_bank(bankId)
    c = R_customer(bank, customerId, uid, role)
    rows = [r for r in image_requests.values() if r["customer_id"] == c["id"]]
    return list_response(rows, ["status", "request_reason", "item_id"])


@api.post("/banks/<bankId>/customers/<customerId>/image_requests/<requestId>/fulfill")
def fulfill_image_request(bankId, customerId, requestId):
    uid, role = auth()
    require_role(role, LO)
    bank = R_bank(bankId)
    c = R_customer(bank, customerId)
    r = R_image(c, requestId)
    check_posture(bank)
    if r["status"] != "REQUESTED":
        bad_state("image request is not REQUESTED")
    if now() > parse_dt_utc(r["retention_expires_at"]):
        raise ApiError("ERR_IMAGE_RETENTION_EXPIRED", 409,
                       "retention window has expired")
    n = now()
    r["status"] = "FULFILLED"
    r["fulfilled_at"] = fmt(n)
    r["fulfillment_uri"] = "lockbox-archive://%s/%s/%s" % (bank["id"], r["item_id"], r["id"])
    touch(r)
    cyc = open_cycle(c["id"])
    if cyc:
        cyc["image_retrieval_fulfilled_count"] += 1
        touch(cyc)
    if n > parse_dt_utc(r["sla_due_at"]):
        emit_incident(bank, c["id"], "LATE_IMAGE_FULFILLMENT",
                      bank["current_business_date"], request_id=r["id"])
    return ok(pub(r))


@api.post("/banks/<bankId>/customers/<customerId>/image_requests/<requestId>/deny")
def deny_image_request(bankId, customerId, requestId):
    uid, role = auth()
    require_role(role, LO)
    bank = R_bank(bankId)
    c = R_customer(bank, customerId)
    r = R_image(c, requestId)
    check_posture(bank)
    if r["status"] != "REQUESTED":
        bad_state("image request is not REQUESTED")
    r["status"] = "DENIED"
    touch(r)
    return ok(pub(r))
