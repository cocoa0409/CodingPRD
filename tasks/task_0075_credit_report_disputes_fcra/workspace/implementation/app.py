import os

from flask import Flask, request

from db import db
from errors import (
    ApiError, err,
    ERR_NOT_FOUND, ERR_NOT_RESOURCE_OWNER, ERR_VALIDATION,
    ERR_INVALID_DELINQUENCY_DATE, ERR_STALE_FILE_VERSION, ERR_INVALID_STATE,
    ERR_DEADLINE_BREACHED, ERR_FILE_FROZEN, ERR_FURNISHER_SUSPENDED,
    ERR_TRADELINE_NOT_DISPUTABLE, ERR_DUPLICATE_DISPUTE,
    ERR_OVERLAPPING_INVESTIGATION, ERR_REOPEN_LIMIT_REACHED,
    ERR_MISSING_CORRECTED_BALANCE, ERR_FREEZE_OVERLAP, ERR_COMPLAINT_PREMATURE,
    ERR_INVALID_DECISION,
)
from middleware import authenticate, require_role
from response import ok, ok_list, error_response
from util import new_id, parse_iso
from validation import (
    get_body, require_fields, require_string, require_enum, require_int,
    parse_pagination, paginate,
)
import services as svc
import serialize as ser

app = Flask(__name__)

# Enums
FURNISHER_TYPES = {"BANK", "CARD_ISSUER", "COLLECTION_AGENCY", "LENDER"}
BUREAU_CODES = {"EQUIFAX", "EXPERIAN", "TRANSUNION"}
ACCOUNT_TYPES = {"REVOLVING", "INSTALLMENT", "COLLECTION"}
DISPUTE_REASONS = {"NOT_MINE", "INACCURATE_BALANCE", "ILLEGAL_REAGE", "PAID_IN_FULL", "IDENTITY_THEFT"}
CLOCK_MODES = {"CALENDAR", "EXPEDITED"}
RESPONSE_TYPES = {"DELETE", "MODIFY", "VERIFY"}
FREEZE_TYPES = {"LOCK", "FREEZE"}
AGENCIES = {"CFPB", "STATE_AG"}
DECISIONS = {"UPHOLD", "DISMISS"}

DISPUTABLE_TRADELINE = {"REPORTING", "CORRECTED", "VERIFIED"}


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", "Method not allowed", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.message, e.http_status)
    return error_response("ERR_VALIDATION", "Unexpected error: %s" % str(e), 422)


# ---------------------------------------------------------------------------
# Lookup helpers (raise ERR_NOT_FOUND)
# ---------------------------------------------------------------------------

def find_or_404(store, entity_id):
    obj = store.get(entity_id)
    if obj is None:
        raise err(ERR_NOT_FOUND, "Resource not found: %s" % entity_id)
    return obj


def parse_iso_field(body, field, error_catalog=ERR_VALIDATION):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise err(error_catalog, "Field %s must be an ISO 8601 string" % field)
    try:
        return parse_iso(v)
    except ValueError:
        raise err(error_catalog, "Field %s is not a valid ISO 8601 instant" % field)


# ---------------------------------------------------------------------------
# Consumers
# ---------------------------------------------------------------------------

@app.route("/consumers", methods=["POST"])
def create_consumer():
    body = get_body()
    require_fields(body, ["email", "full_name", "ssn_last4"])
    email = require_string(body, "email")
    full_name = require_string(body, "full_name")
    ssn_last4 = body.get("ssn_last4")
    if not isinstance(ssn_last4, str) or len(ssn_last4) != 4 or not ssn_last4.isdigit():
        raise err(ERR_VALIDATION, "ssn_last4 must be exactly 4 numeric characters")
    c = {
        "id": new_id(),
        "email": email,
        "full_name": full_name,
        "ssn_last4": ssn_last4,
        "status": "ACTIVE",
    }
    svc.stamp_new(c)
    db.consumers[c["id"]] = c
    return ok(ser.consumer_view(c), status=201)


@app.route("/consumers/<consumer_id>", methods=["GET"])
def get_consumer(consumer_id):
    _, role = authenticate()
    require_role(role, {"Consumer", "CreditBureau", "Regulator"})
    c = find_or_404(db.consumers, consumer_id)
    return ok(ser.consumer_view(c))


# ---------------------------------------------------------------------------
# Furnishers
# ---------------------------------------------------------------------------

@app.route("/furnishers", methods=["POST"])
def create_furnisher():
    body = get_body()
    require_fields(body, ["name", "furnisher_type"])
    name = require_string(body, "name")
    furnisher_type = require_enum(body, "furnisher_type", FURNISHER_TYPES)
    f = {
        "id": new_id(),
        "name": name,
        "furnisher_type": furnisher_type,
        "status": "ACTIVE",
        "open_reverification_count": 0,
    }
    svc.stamp_new(f)
    db.furnishers[f["id"]] = f
    return ok(ser.furnisher_view(f), status=201)


@app.route("/furnishers/<furnisher_id>", methods=["GET"])
def get_furnisher(furnisher_id):
    _, role = authenticate()
    require_role(role, {"Furnisher", "CreditBureau", "Regulator"})
    f = find_or_404(db.furnishers, furnisher_id)
    return ok(ser.furnisher_view(f))


@app.route("/furnishers/<furnisher_id>/suspend", methods=["POST"])
def suspend_furnisher(furnisher_id):
    _, role = authenticate()
    require_role(role, {"CreditBureau"})
    f = find_or_404(db.furnishers, furnisher_id)
    f["status"] = "SUSPENDED"
    svc.touch(f)
    return ok(ser.furnisher_view(f))


# ---------------------------------------------------------------------------
# Credit Files
# ---------------------------------------------------------------------------

@app.route("/credit-files", methods=["POST"])
def create_credit_file():
    _, role = authenticate()
    require_role(role, {"CreditBureau"})
    body = get_body()
    require_fields(body, ["consumer_id", "bureau_code"])
    consumer_id = require_string(body, "consumer_id")
    bureau_code = require_enum(body, "bureau_code", BUREAU_CODES)
    find_or_404(db.consumers, consumer_id)
    cf = {
        "id": new_id(),
        "consumer_id": consumer_id,
        "bureau_code": bureau_code,
        "protection_state": "OPEN",
        "open_dispute_count": 0,
        "tradeline_count": 0,
    }
    svc.stamp_new(cf)
    db.credit_files[cf["id"]] = cf
    return ok(ser.credit_file_view(cf), status=201)


@app.route("/credit-files/<credit_file_id>", methods=["GET"])
def get_credit_file(credit_file_id):
    _, role = authenticate()
    require_role(role, {"Consumer", "CreditBureau", "Regulator"})
    cf = find_or_404(db.credit_files, credit_file_id)
    # recompute posture against current clock before returning (no version bump)
    svc.recompute_protection_state(cf)
    return ok(ser.credit_file_view(cf))


@app.route("/credit-files", methods=["GET"])
def list_credit_files():
    _, role = authenticate()
    require_role(role, {"CreditBureau", "Regulator"})
    limit, offset = parse_pagination()
    consumer_id = request.args.get("consumer_id")
    items = [cf for cf in db.credit_files.values()
             if consumer_id is None or cf["consumer_id"] == consumer_id]
    items.sort(key=lambda x: x["_seq"])
    for cf in items:
        svc.recompute_protection_state(cf)
    page, total = paginate(items, limit, offset)
    return ok_list([ser.credit_file_view(x) for x in page], limit, offset, total)


def _child_list(parent_store, parent_id, child_store, fk_field, roles, view, extra_filter=None):
    _, role = authenticate()
    require_role(role, roles)
    limit, offset = parse_pagination()
    find_or_404(parent_store, parent_id)
    items = [x for x in child_store.values()
             if x.get(fk_field) == parent_id and (extra_filter is None or extra_filter(x))]
    items.sort(key=lambda x: x["_seq"])
    page, total = paginate(items, limit, offset)
    return ok_list([view(x) for x in page], limit, offset, total)


@app.route("/credit-files/<credit_file_id>/tradelines", methods=["GET"])
def list_file_tradelines(credit_file_id):
    return _child_list(db.credit_files, credit_file_id, db.tradelines, "credit_file_id",
                       {"Consumer", "CreditBureau", "Regulator"}, ser.tradeline_view)


@app.route("/credit-files/<credit_file_id>/disputes", methods=["GET"])
def list_file_disputes(credit_file_id):
    return _child_list(db.credit_files, credit_file_id, db.disputes, "credit_file_id",
                       {"Consumer", "CreditBureau", "Regulator"}, ser.dispute_view)


@app.route("/credit-files/<credit_file_id>/security-freezes", methods=["GET"])
def list_file_freezes(credit_file_id):
    return _child_list(db.credit_files, credit_file_id, db.security_freezes, "credit_file_id",
                       {"Consumer", "CreditBureau", "Regulator"}, ser.freeze_view)


@app.route("/credit-files/<credit_file_id>/notifications", methods=["GET"])
def list_file_notifications(credit_file_id):
    return _child_list(db.credit_files, credit_file_id, db.notifications, "credit_file_id",
                       {"Consumer", "CreditBureau", "Regulator"}, ser.notification_view)


# ---------------------------------------------------------------------------
# Tradelines
# ---------------------------------------------------------------------------

@app.route("/tradelines", methods=["POST"])
def create_tradeline():
    _, role = authenticate()
    require_role(role, {"Furnisher", "CreditBureau"})
    body = get_body()
    require_fields(body, ["credit_file_id", "furnisher_id", "account_type",
                          "balance_cents", "date_of_first_delinquency",
                          "reported_delinquency_date"])
    credit_file_id = require_string(body, "credit_file_id")
    furnisher_id = require_string(body, "furnisher_id")
    account_type = require_enum(body, "account_type", ACCOUNT_TYPES)
    balance_cents = require_int(body, "balance_cents", min_value=0)
    dofd = parse_iso_field(body, "date_of_first_delinquency")
    rdd = parse_iso_field(body, "reported_delinquency_date")
    # existence (left to right): credit_file then furnisher
    cf = find_or_404(db.credit_files, credit_file_id)
    find_or_404(db.furnishers, furnisher_id)
    # business: reported >= DOFD
    if rdd < dofd:
        raise err(ERR_INVALID_DELINQUENCY_DATE,
                  "reported_delinquency_date must be >= date_of_first_delinquency")
    t = {
        "id": new_id(),
        "credit_file_id": credit_file_id,
        "furnisher_id": furnisher_id,
        "account_type": account_type,
        "balance_cents": balance_cents,
        "date_of_first_delinquency": dofd,
        "reported_delinquency_date": rdd,
        "status": "REPORTING",
        "reage_violation": svc.compute_reage_violation(rdd, dofd),
        "purge_due_at": svc.compute_purge_due_at(dofd),
    }
    svc.stamp_new(t)
    db.tradelines[t["id"]] = t
    svc.recompute_counts(cf)
    svc.touch(cf)
    return ok(ser.tradeline_view(t), status=201)


@app.route("/tradelines/<tradeline_id>", methods=["GET"])
def get_tradeline(tradeline_id):
    _, role = authenticate()
    require_role(role, {"Consumer", "Furnisher", "CreditBureau", "Regulator"})
    t = find_or_404(db.tradelines, tradeline_id)
    return ok(ser.tradeline_view(t))


@app.route("/tradelines", methods=["GET"])
def list_tradelines():
    _, role = authenticate()
    require_role(role, {"Furnisher", "CreditBureau", "Regulator"})
    limit, offset = parse_pagination()
    furnisher_id = request.args.get("furnisher_id")
    credit_file_id = request.args.get("credit_file_id")
    items = [t for t in db.tradelines.values()
             if (furnisher_id is None or t["furnisher_id"] == furnisher_id)
             and (credit_file_id is None or t["credit_file_id"] == credit_file_id)]
    items.sort(key=lambda x: x["_seq"])
    page, total = paginate(items, limit, offset)
    return ok_list([ser.tradeline_view(x) for x in page], limit, offset, total)


@app.route("/tradelines/<tradeline_id>/reage-events", methods=["GET"])
def list_tradeline_reage_events(tradeline_id):
    return _child_list(db.tradelines, tradeline_id, db.reage_events, "tradeline_id",
                       {"Consumer", "Furnisher", "CreditBureau", "Regulator"},
                       ser.reage_event_view)


@app.route("/tradelines/<tradeline_id>/reage", methods=["POST"])
def reage_tradeline(tradeline_id):
    user_id, role = authenticate()
    require_role(role, {"Furnisher"})
    body = get_body()
    require_fields(body, ["reported_delinquency_date"])
    new_rdd = parse_iso_field(body, "reported_delinquency_date")
    t = find_or_404(db.tradelines, tradeline_id)
    prior = t["reported_delinquency_date"]
    dofd = t["date_of_first_delinquency"]
    was_violation = svc.compute_reage_violation(new_rdd, dofd)
    t["reported_delinquency_date"] = new_rdd
    t["reage_violation"] = was_violation
    # purge_due_at unchanged (anchored to DOFD)
    svc.touch(t)
    svc.append_reage_event(t["id"], prior, new_rdd, was_violation, None)
    return ok(ser.tradeline_view(t))


# ---------------------------------------------------------------------------
# Disputes
# ---------------------------------------------------------------------------

@app.route("/disputes", methods=["POST"])
def create_dispute():
    user_id, role = authenticate()
    require_role(role, {"Consumer"})
    body = get_body()
    require_fields(body, ["credit_file_id", "tradeline_id", "dispute_reason",
                          "expected_credit_file_version"])
    credit_file_id = require_string(body, "credit_file_id")
    tradeline_id = require_string(body, "tradeline_id")
    dispute_reason = require_enum(body, "dispute_reason", DISPUTE_REASONS)
    clock_mode = body.get("clock_mode", "CALENDAR")
    if clock_mode is None:
        clock_mode = "CALENDAR"
    if clock_mode not in CLOCK_MODES:
        raise err(ERR_VALIDATION, "clock_mode must be one of %s" % sorted(CLOCK_MODES))
    expected_version = require_int(body, "expected_credit_file_version")
    # existence left-to-right
    cf = find_or_404(db.credit_files, credit_file_id)
    t = find_or_404(db.tradelines, tradeline_id)
    # ownership
    if cf["consumer_id"] != user_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "Consumer does not own this credit file")
    # OCC
    if expected_version != cf["version"]:
        raise err(ERR_STALE_FILE_VERSION, "expected_credit_file_version is stale")
    # frozen check (posture recomputed against current clock)
    svc.recompute_protection_state(cf)
    if cf["protection_state"] == "FROZEN":
        raise err(ERR_FILE_FROZEN, "Credit file is FROZEN")
    # tradeline disputable
    if t["status"] not in DISPUTABLE_TRADELINE:
        raise err(ERR_TRADELINE_NOT_DISPUTABLE, "Tradeline is not in a disputable status")
    # duplicate dispute on same tradeline
    for d in db.disputes.values():
        if d["tradeline_id"] == tradeline_id and d["status"] in svc.DISPUTE_NONTERMINAL:
            raise err(ERR_DUPLICATE_DISPUTE, "A non-terminal dispute already references this tradeline")
    # compute window for overlap check
    filed_at = db.clock
    deadline_at = svc.compute_deadline(filed_at, clock_mode)
    # overlapping investigation: same file, same reason, non-terminal, half-open overlap
    for d in db.disputes.values():
        if (d["credit_file_id"] == credit_file_id
                and d["status"] in svc.DISPUTE_NONTERMINAL
                and d["dispute_reason"] == dispute_reason):
            if filed_at < d["deadline_at"] and d["filed_at"] < deadline_at:
                raise err(ERR_OVERLAPPING_INVESTIGATION,
                          "Overlaps a non-terminal same-reason dispute on this file")
    # create
    d = {
        "id": new_id(),
        "credit_file_id": credit_file_id,
        "tradeline_id": tradeline_id,
        "consumer_id": cf["consumer_id"],
        "dispute_reason": dispute_reason,
        "clock_mode": clock_mode,
        "filed_at": filed_at,
        "deadline_at": deadline_at,
        "priority_score": 0,
        "reopen_count": 0,
        "status": "FILED",
        "outcome_reason": None,
    }
    d["priority_score"] = svc.compute_priority_score(d, t)
    svc.stamp_new(d)
    db.disputes[d["id"]] = d
    # tradeline -> DISPUTED
    t["status"] = "DISPUTED"
    svc.touch(t)
    # recompute counts, mint notification, bump version
    svc.recompute_counts(cf)
    svc.mint_notification(cf["id"], "DISPUTE", d["id"], "DISPUTE_FILED")
    svc.touch(cf)
    return ok(ser.dispute_view(d), status=201)


@app.route("/disputes/<dispute_id>", methods=["GET"])
def get_dispute(dispute_id):
    _, role = authenticate()
    require_role(role, {"Consumer", "CreditBureau", "Furnisher", "Regulator"})
    d = find_or_404(db.disputes, dispute_id)
    return ok(ser.dispute_view(d))


@app.route("/disputes", methods=["GET"])
def list_disputes():
    _, role = authenticate()
    require_role(role, {"Consumer", "CreditBureau", "Regulator"})
    limit, offset = parse_pagination()
    tradeline_id = request.args.get("tradeline_id")
    consumer_id = request.args.get("consumer_id")
    credit_file_id = request.args.get("credit_file_id")
    items = [d for d in db.disputes.values()
             if (tradeline_id is None or d["tradeline_id"] == tradeline_id)
             and (consumer_id is None or d["consumer_id"] == consumer_id)
             and (credit_file_id is None or d["credit_file_id"] == credit_file_id)]
    items.sort(key=lambda x: x["_seq"])
    page, total = paginate(items, limit, offset)
    return ok_list([ser.dispute_view(x) for x in page], limit, offset, total)


@app.route("/disputes/<dispute_id>/open-investigation", methods=["POST"])
def open_investigation(dispute_id):
    _, role = authenticate()
    require_role(role, {"CreditBureau"})
    d = find_or_404(db.disputes, dispute_id)
    # state
    if d["status"] != "FILED":
        raise err(ERR_INVALID_STATE, "Dispute is not in FILED")
    # deadline
    if db.clock > d["deadline_at"]:
        raise err(ERR_DEADLINE_BREACHED, "Investigation deadline has passed")
    # frozen file
    cf = db.credit_files[d["credit_file_id"]]
    svc.recompute_protection_state(cf)
    if cf["protection_state"] == "FROZEN":
        raise err(ERR_FILE_FROZEN, "Credit file is FROZEN")
    d["status"] = "INVESTIGATING"
    svc.touch(d)
    return ok(ser.dispute_view(d))


@app.route("/disputes/<dispute_id>/reage-events", methods=["GET"])
def list_dispute_reage_events(dispute_id):
    return _child_list(db.disputes, dispute_id, db.reage_events, "source_dispute_id",
                       {"Consumer", "CreditBureau", "Furnisher", "Regulator"},
                       ser.reage_event_view)


@app.route("/disputes/<dispute_id>/reopen", methods=["POST"])
def reopen_dispute(dispute_id):
    user_id, role = authenticate()
    require_role(role, {"Consumer"})
    d = find_or_404(db.disputes, dispute_id)
    # ownership
    if d["consumer_id"] != user_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "Consumer does not own this dispute")
    # state
    if d["status"] != "REVERIFYING":
        raise err(ERR_INVALID_STATE, "Dispute is not in REVERIFYING")
    # reopen limit
    if d["reopen_count"] >= 2:
        raise err(ERR_REOPEN_LIMIT_REACHED, "Dispute has reached the reopen limit")
    # deadline
    if db.clock > d["deadline_at"]:
        raise err(ERR_DEADLINE_BREACHED, "Investigation deadline has passed")
    d["status"] = "REOPENED"
    d["reopen_count"] += 1
    # cancel pending reverifications
    svc.cancel_pending_reverifications(d)
    # recompute priority score
    t = db.tradelines[d["tradeline_id"]]
    d["priority_score"] = svc.compute_priority_score(d, t)
    svc.touch(d)
    return ok(ser.dispute_view(d))


# ---------------------------------------------------------------------------
# Reverification Requests
# ---------------------------------------------------------------------------

@app.route("/reverification-requests", methods=["POST"])
def create_reverification():
    _, role = authenticate()
    require_role(role, {"CreditBureau"})
    body = get_body()
    require_fields(body, ["dispute_id", "furnisher_id"])
    dispute_id = require_string(body, "dispute_id")
    furnisher_id = require_string(body, "furnisher_id")
    # existence left-to-right
    d = find_or_404(db.disputes, dispute_id)
    f = find_or_404(db.furnishers, furnisher_id)
    # state: dispute must be INVESTIGATING or REOPENED
    if d["status"] not in ("INVESTIGATING", "REOPENED"):
        raise err(ERR_INVALID_STATE, "Dispute is not in INVESTIGATING or REOPENED")
    # deadline
    if db.clock > d["deadline_at"]:
        raise err(ERR_DEADLINE_BREACHED, "Investigation deadline has passed")
    # furnisher active
    if f["status"] != "ACTIVE":
        raise err(ERR_FURNISHER_SUSPENDED, "Target furnisher is SUSPENDED")
    r = {
        "id": new_id(),
        "dispute_id": dispute_id,
        "furnisher_id": furnisher_id,
        "response_type": None,
        "corrected_balance_cents": None,
        "status": "PENDING",
    }
    svc.stamp_new(r)
    db.reverifications[r["id"]] = r
    d["status"] = "REVERIFYING"
    svc.touch(d)
    f["open_reverification_count"] += 1
    svc.touch(f)
    return ok(ser.reverification_view(r), status=201)


@app.route("/reverification-requests/<reverification_id>", methods=["GET"])
def get_reverification(reverification_id):
    _, role = authenticate()
    require_role(role, {"Consumer", "CreditBureau", "Furnisher", "Regulator"})
    r = find_or_404(db.reverifications, reverification_id)
    return ok(ser.reverification_view(r))


@app.route("/reverification-requests", methods=["GET"])
def list_reverifications():
    _, role = authenticate()
    require_role(role, {"CreditBureau", "Furnisher", "Regulator"})
    limit, offset = parse_pagination()
    dispute_id = request.args.get("dispute_id")
    furnisher_id = request.args.get("furnisher_id")
    items = [r for r in db.reverifications.values()
             if (dispute_id is None or r["dispute_id"] == dispute_id)
             and (furnisher_id is None or r["furnisher_id"] == furnisher_id)]
    items.sort(key=lambda x: x["_seq"])
    page, total = paginate(items, limit, offset)
    return ok_list([ser.reverification_view(x) for x in page], limit, offset, total)


@app.route("/reverification-requests/<reverification_id>/respond", methods=["POST"])
def respond_reverification(reverification_id):
    user_id, role = authenticate()
    require_role(role, {"Furnisher"})
    body = get_body()
    require_fields(body, ["response_type"])
    response_type = require_enum(body, "response_type", RESPONSE_TYPES)
    # existence
    r = find_or_404(db.reverifications, reverification_id)
    d = db.disputes[r["dispute_id"]]
    cf = db.credit_files[d["credit_file_id"]]
    t = db.tradelines[d["tradeline_id"]]
    # ownership
    if r["furnisher_id"] != user_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "Acting furnisher does not own this reverification")
    # state
    if r["status"] != "PENDING":
        raise err(ERR_INVALID_STATE, "Reverification is not PENDING")
    # deadline
    if db.clock > d["deadline_at"]:
        raise err(ERR_DEADLINE_BREACHED, "Investigation deadline has passed")
    # MODIFY requires corrected_balance_cents >= 0
    corrected_balance = None
    if response_type == "MODIFY":
        cb = body.get("corrected_balance_cents")
        if isinstance(cb, bool) or not isinstance(cb, int) or cb < 0:
            raise err(ERR_MISSING_CORRECTED_BALANCE,
                      "MODIFY response requires corrected_balance_cents >= 0")
        corrected_balance = cb

    f = db.furnishers[r["furnisher_id"]]
    r["status"] = "RESPONDED"
    r["response_type"] = response_type
    if corrected_balance is not None:
        r["corrected_balance_cents"] = corrected_balance
    svc.touch(r)
    f["open_reverification_count"] -= 1
    svc.touch(f)

    if response_type == "DELETE":
        d["status"] = "RESOLVED_DELETE"
        d["outcome_reason"] = "FURNISHER_DELETED"
        svc.touch(d)
        svc.cascade_delete(d, cf, t, auto_deleted=False)
    elif response_type == "MODIFY":
        d["status"] = "RESOLVED_CORRECT"
        d["outcome_reason"] = "FURNISHER_CORRECTED"
        svc.touch(d)
        # cascade: balance replaced, tradeline -> CORRECTED
        t["balance_cents"] = corrected_balance
        t["status"] = "CORRECTED"
        # optional corrected_delinquency_date
        cdd_raw = body.get("corrected_delinquency_date")
        if cdd_raw is not None:
            cdd = parse_iso_field(body, "corrected_delinquency_date")
            dofd = t["date_of_first_delinquency"]
            if cdd > dofd:
                prior = t["reported_delinquency_date"]
                t["reported_delinquency_date"] = cdd
                t["reage_violation"] = svc.compute_reage_violation(cdd, dofd)
                svc.append_reage_event(t["id"], prior, cdd, t["reage_violation"], d["id"])
        svc.touch(t)
        svc.recompute_counts(cf)
        svc.mint_notification(cf["id"], "TRADELINE", t["id"], "TRADELINE_CORRECTED")
        svc.touch(cf)
    else:  # VERIFY
        d["status"] = "RESOLVED_VERIFY"
        d["outcome_reason"] = "FURNISHER_VERIFIED"
        svc.touch(d)
        t["status"] = "VERIFIED"
        svc.touch(t)
        svc.recompute_counts(cf)
        svc.mint_notification(cf["id"], "DISPUTE", d["id"], "DISPUTE_RESOLVED")
        svc.touch(cf)

    return ok(ser.reverification_view(r))


# ---------------------------------------------------------------------------
# Security Freezes
# ---------------------------------------------------------------------------

@app.route("/security-freezes", methods=["POST"])
def create_freeze():
    user_id, role = authenticate()
    require_role(role, {"Consumer"})
    body = get_body()
    require_fields(body, ["credit_file_id", "freeze_type", "effective_at",
                          "expected_credit_file_version"])
    credit_file_id = require_string(body, "credit_file_id")
    freeze_type = require_enum(body, "freeze_type", FREEZE_TYPES)
    effective_at = parse_iso_field(body, "effective_at")
    expires_at = None
    if body.get("expires_at") is not None:
        expires_at = parse_iso_field(body, "expires_at")
    expected_version = require_int(body, "expected_credit_file_version")
    # existence
    cf = find_or_404(db.credit_files, credit_file_id)
    # ownership
    if cf["consumer_id"] != user_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "Consumer does not own this credit file")
    # OCC
    if expected_version != cf["version"]:
        raise err(ERR_STALE_FILE_VERSION, "expected_credit_file_version is stale")
    # overlap with existing ACTIVE freeze of same type (half-open)
    for ex in db.security_freezes.values():
        if (ex["credit_file_id"] == credit_file_id
                and ex["status"] == "ACTIVE"
                and ex["freeze_type"] == freeze_type):
            if _intervals_overlap(effective_at, expires_at, ex["effective_at"], ex["expires_at"]):
                raise err(ERR_FREEZE_OVERLAP, "Overlaps an existing ACTIVE freeze of the same type")
    fz = {
        "id": new_id(),
        "credit_file_id": credit_file_id,
        "freeze_type": freeze_type,
        "effective_at": effective_at,
        "expires_at": expires_at,
        "status": "ACTIVE",
    }
    svc.stamp_new(fz)
    db.security_freezes[fz["id"]] = fz
    svc.recompute_protection_state(cf)
    svc.mint_notification(cf["id"], "SECURITY_FREEZE", fz["id"], "FREEZE_PLACED")
    svc.touch(cf)
    return ok(ser.freeze_view(fz), status=201)


def _intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end); end=None => +infinity. Abutting endpoints do not overlap."""
    a_end_inf = a_end is None
    b_end_inf = b_end is None
    # overlap iff a_start < b_end AND b_start < a_end
    cond1 = a_end_inf or (b_start < a_end)
    cond2 = b_end_inf or (a_start < b_end)
    return cond1 and cond2


@app.route("/security-freezes/<freeze_id>", methods=["GET"])
def get_freeze(freeze_id):
    _, role = authenticate()
    require_role(role, {"Consumer", "CreditBureau", "Regulator"})
    fz = find_or_404(db.security_freezes, freeze_id)
    return ok(ser.freeze_view(fz))


@app.route("/security-freezes", methods=["GET"])
def list_freezes():
    _, role = authenticate()
    require_role(role, {"Consumer", "CreditBureau", "Regulator"})
    limit, offset = parse_pagination()
    credit_file_id = request.args.get("credit_file_id")
    items = [f for f in db.security_freezes.values()
             if credit_file_id is None or f["credit_file_id"] == credit_file_id]
    items.sort(key=lambda x: x["_seq"])
    page, total = paginate(items, limit, offset)
    return ok_list([ser.freeze_view(x) for x in page], limit, offset, total)


@app.route("/security-freezes/<freeze_id>/lift", methods=["POST"])
def lift_freeze(freeze_id):
    user_id, role = authenticate()
    require_role(role, {"Consumer"})
    fz = find_or_404(db.security_freezes, freeze_id)
    cf = db.credit_files[fz["credit_file_id"]]
    # ownership
    if cf["consumer_id"] != user_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "Consumer does not own this freeze")
    # state
    if fz["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Freeze is not ACTIVE")
    fz["status"] = "LIFTED"
    svc.touch(fz)
    svc.recompute_protection_state(cf)
    svc.mint_notification(cf["id"], "SECURITY_FREEZE", fz["id"], "FREEZE_LIFTED")
    svc.touch(cf)
    return ok(ser.freeze_view(fz))


# ---------------------------------------------------------------------------
# Regulatory Complaints
# ---------------------------------------------------------------------------

@app.route("/regulatory-complaints", methods=["POST"])
def create_complaint():
    _, role = authenticate()
    require_role(role, {"Consumer"})
    body = get_body()
    require_fields(body, ["dispute_id", "narrative"])
    dispute_id = require_string(body, "dispute_id")
    narrative = require_string(body, "narrative")
    agency = body.get("agency", "CFPB")
    if agency is None:
        agency = "CFPB"
    if agency not in AGENCIES:
        raise err(ERR_VALIDATION, "agency must be one of %s" % sorted(AGENCIES))
    d = find_or_404(db.disputes, dispute_id)
    cf = db.credit_files[d["credit_file_id"]]
    c = {
        "id": new_id(),
        "dispute_id": dispute_id,
        "consumer_id": d["consumer_id"],
        "agency": agency,
        "narrative": narrative,
        "status": "SUBMITTED",
    }
    svc.stamp_new(c)
    db.complaints[c["id"]] = c
    svc.mint_notification(cf["id"], "REGULATORY_COMPLAINT", c["id"], "COMPLAINT_SUBMITTED")
    return ok(ser.complaint_view(c), status=201)


@app.route("/regulatory-complaints/<complaint_id>", methods=["GET"])
def get_complaint(complaint_id):
    _, role = authenticate()
    require_role(role, {"Consumer", "Regulator", "CreditBureau"})
    c = find_or_404(db.complaints, complaint_id)
    return ok(ser.complaint_view(c))


@app.route("/regulatory-complaints", methods=["GET"])
def list_complaints():
    _, role = authenticate()
    require_role(role, {"Regulator", "CreditBureau", "Consumer"})
    limit, offset = parse_pagination()
    dispute_id = request.args.get("dispute_id")
    consumer_id = request.args.get("consumer_id")
    items = [c for c in db.complaints.values()
             if (dispute_id is None or c["dispute_id"] == dispute_id)
             and (consumer_id is None or c["consumer_id"] == consumer_id)]
    items.sort(key=lambda x: x["_seq"])
    page, total = paginate(items, limit, offset)
    return ok_list([ser.complaint_view(x) for x in page], limit, offset, total)


@app.route("/regulatory-complaints/<complaint_id>/review", methods=["POST"])
def review_complaint(complaint_id):
    _, role = authenticate()
    require_role(role, {"Regulator"})
    c = find_or_404(db.complaints, complaint_id)
    if c["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "Complaint is not SUBMITTED")
    c["status"] = "UNDER_REVIEW"
    svc.touch(c)
    return ok(ser.complaint_view(c))


@app.route("/regulatory-complaints/<complaint_id>/adjudicate", methods=["POST"])
def adjudicate_complaint(complaint_id):
    _, role = authenticate()
    require_role(role, {"Regulator"})
    body = get_body()
    require_fields(body, ["decision"])
    decision = body.get("decision")
    c = find_or_404(db.complaints, complaint_id)
    # state check before decision-value check (per priority: INVALID_STATE=6 < decision=17)
    if c["status"] != "UNDER_REVIEW":
        raise err(ERR_INVALID_STATE, "Complaint is not UNDER_REVIEW")
    if decision not in DECISIONS:
        raise err(ERR_INVALID_DECISION, "decision must be UPHOLD or DISMISS")
    if decision == "UPHOLD":
        d = db.disputes[c["dispute_id"]]
        if d["status"] not in ("AUTO_DELETED", "RESOLVED_VERIFY"):
            raise err(ERR_COMPLAINT_PREMATURE,
                      "Referenced dispute has not reached a contestable terminal state")
        c["status"] = "UPHELD"
    else:
        c["status"] = "DISMISSED"
    svc.touch(c)
    cf = db.credit_files[db.disputes[c["dispute_id"]]["credit_file_id"]]
    svc.mint_notification(cf["id"], "REGULATORY_COMPLAINT", c["id"], "COMPLAINT_ADJUDICATED")
    return ok(ser.complaint_view(c))


# ---------------------------------------------------------------------------
# Notifications (read)
# ---------------------------------------------------------------------------

@app.route("/notifications/<notification_id>", methods=["GET"])
def get_notification(notification_id):
    _, role = authenticate()
    require_role(role, {"Consumer", "CreditBureau", "Regulator"})
    n = find_or_404(db.notifications, notification_id)
    return ok(ser.notification_view(n))


@app.route("/notifications", methods=["GET"])
def list_notifications():
    _, role = authenticate()
    require_role(role, {"Consumer", "CreditBureau", "Regulator"})
    limit, offset = parse_pagination()
    credit_file_id = request.args.get("credit_file_id")
    subject_id = request.args.get("subject_id")
    items = [n for n in db.notifications.values()
             if (credit_file_id is None or n["credit_file_id"] == credit_file_id)
             and (subject_id is None or n["subject_id"] == subject_id)]
    items.sort(key=lambda x: x["_seq"])
    page, total = paginate(items, limit, offset)
    return ok_list([ser.notification_view(x) for x in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Reage Events (read)
# ---------------------------------------------------------------------------

@app.route("/reage-events/<reage_event_id>", methods=["GET"])
def get_reage_event(reage_event_id):
    _, role = authenticate()
    require_role(role, {"Consumer", "Furnisher", "CreditBureau", "Regulator"})
    e = find_or_404(db.reage_events, reage_event_id)
    return ok(ser.reage_event_view(e))


@app.route("/reage-events", methods=["GET"])
def list_reage_events():
    _, role = authenticate()
    require_role(role, {"Consumer", "Furnisher", "CreditBureau", "Regulator"})
    limit, offset = parse_pagination()
    tradeline_id = request.args.get("tradeline_id")
    source_dispute_id = request.args.get("source_dispute_id")
    items = [e for e in db.reage_events.values()
             if (tradeline_id is None or e["tradeline_id"] == tradeline_id)
             and (source_dispute_id is None or e["source_dispute_id"] == source_dispute_id)]
    items.sort(key=lambda x: x["_seq"])
    page, total = paginate(items, limit, offset)
    return ok_list([ser.reage_event_view(x) for x in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Clock control
# ---------------------------------------------------------------------------

@app.route("/_clock/set", methods=["POST"])
def clock_set():
    _, role = authenticate()
    require_role(role, {"CreditBureau"})
    body = get_body()
    require_fields(body, ["to_iso8601"])
    to = parse_iso_field(body, "to_iso8601")
    db.clock = to
    return ok({})


@app.route("/_clock/advance", methods=["POST"])
def clock_advance():
    _, role = authenticate()
    require_role(role, {"CreditBureau"})
    body = get_body()
    require_fields(body, ["to_iso8601"])
    to = parse_iso_field(body, "to_iso8601")
    db.clock = to
    svc.run_deadline_sweep()
    return ok({})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
