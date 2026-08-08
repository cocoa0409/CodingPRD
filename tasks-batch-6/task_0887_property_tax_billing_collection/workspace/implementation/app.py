"""Property-Tax Billing & Collection API (county treasurer).

Single-file Flask implementation. In-memory storage only; state is wiped on
every process boot (the harness restarts the server before each test).
"""
import os
import re
import uuid
import calendar
from datetime import datetime, timezone, date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify, g

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
INSTALLMENT_COUNT = 2
PENALTY_RATE = Decimal("0.05")
INTEREST_RATE_MONTHLY = Decimal("0.01")
LIEN_REFERRAL_THRESHOLD_CENTS = 50000
REDEMPTION_PERIOD_DAYS = 365
DAYS_PER_YEAR = 365

ROLES = {"Treasurer", "Cashier", "CollectionsOfficer", "ReliefOfficer", "Taxpayer"}
ALL_ROLES = ["Treasurer", "Cashier", "CollectionsOfficer", "ReliefOfficer", "Taxpayer"]

ENUM_PROPERTY_CLASS = {"RESIDENTIAL", "COMMERCIAL", "AGRICULTURAL", "INDUSTRIAL"}
ENUM_RELIEF_CLASS = {"EXEMPTION", "ABATEMENT"}
ENUM_RELIEF_TYPE = {"HOMESTEAD", "SENIOR", "HARDSHIP", "DISABLED_VETERAN"}
ENUM_TENDER = {"CASH", "CHECK", "ACH", "CARD"}
ENUM_SOURCE = {"COUNTER", "ESCROW", "ONLINE"}
ENUM_REFUND_MODE = {"GROSS_OVERPAYMENT", "NET_OF_DELINQUENCY"}
ENUM_PAYOFF_MODE = {"LEDGER_AS_OF", "PAYOFF_QUOTE"}

DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
db = {
    "tax_years": {},
    "escrow_agents": {},
    "parcels": {},
    "tax_bills": {},
    "installments": {},
    "relief_apps": {},
    "payments": {},
    "ledger": {},
    "refunds": {},
    "referrals": {},
}
_seq_counter = [0]
CLOCK = {"dt": None, "raw": None}


def reset_clock():
    CLOCK["dt"] = parse_iso(DEFAULT_CLOCK_ISO)
    CLOCK["raw"] = DEFAULT_CLOCK_ISO


def next_seq():
    _seq_counter[0] += 1
    return _seq_counter[0]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err(error_id, status, msg=""):
    raise ApiError(error_id, status, msg)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def parse_iso(s):
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_ms(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return iso_ms(datetime.now(timezone.utc))


def render_business(dt):
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return iso_ms(dt)


def add_months(d, k):
    m = d.month - 1 + k
    y = d.year + m // 12
    m = m % 12 + 1
    last = calendar.monthrange(y, m)[1]
    return date(y, m, min(d.day, last))


def months_elapsed(due_date, clock_date):
    k = 0
    while add_months(due_date, k + 1) <= clock_date:
        k += 1
    return k


def rhu(dec):
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Auth / request helpers
# ---------------------------------------------------------------------------
def authn():
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or role not in ROLES:
        err("ERR_UNAUTHENTICATED", 401, "Missing or unrecognized X-User-Role")
    return uid, role


def require_roles(role, allowed):
    if role not in allowed:
        err("ERR_FORBIDDEN", 403, "Role not permitted for this operation")


def body_json():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        err("ERR_VALIDATION", 400, "Request body must be a JSON object")
    return data


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(data, field):
    if field not in data or data[field] is None:
        err("ERR_VALIDATION", 400, f"Missing required field: {field}")
    v = data[field]
    if not isinstance(v, str) or v == "":
        err("ERR_VALIDATION", 400, f"Field {field} must be a non-empty string")
    return v


def req_int(data, field):
    if field not in data or data[field] is None:
        err("ERR_VALIDATION", 400, f"Missing required field: {field}")
    v = data[field]
    if not is_int(v):
        err("ERR_VALIDATION", 400, f"Field {field} must be an integer")
    return v


def req_num(data, field):
    if field not in data or data[field] is None:
        err("ERR_VALIDATION", 400, f"Missing required field: {field}")
    v = data[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        err("ERR_VALIDATION", 400, f"Field {field} must be a number")
    return v


def req_datetime(data, field):
    v = req_str(data, field)
    try:
        parse_iso(v)
    except Exception:
        err("ERR_VALIDATION", 400, f"Field {field} must be an ISO8601 datetime")
    return v


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def meta(extra=None):
    m = {"api_request_id": "req_" + uuid.uuid4().hex[:20], "api_request_timestamp": now_iso()}
    if extra:
        m.update(extra)
    return m


def ok(data, status=200, pagination=None):
    rt = "array" if isinstance(data, list) else "object"
    body = {"meta": meta(pagination), "response_type": rt, "data": data}
    return jsonify(body), status


def paginate(items):
    try:
        limit = request.args.get("limit", None)
        limit = int(limit) if limit is not None else 10
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = request.args.get("offset", None)
        offset = int(offset) if offset is not None else 0
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    pag = {"limit": limit, "offset": offset, "total_count": total,
           "has_more": offset + len(page) < total}
    return page, pag


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {"meta": meta(), "response_type": "error",
            "data": {"error_id": e.error_id, "message": e.message}}
    return jsonify(body), e.http_status


@app.errorhandler(404)
def handle_404(e):
    body = {"meta": meta(), "response_type": "error",
            "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"}}
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {"meta": meta(), "response_type": "error",
            "data": {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed"}}
    return jsonify(body), 404


# ---------------------------------------------------------------------------
# Store helpers
# ---------------------------------------------------------------------------
def new_common():
    ts = now_iso()
    return {"id": str(uuid.uuid4()), "created_at": ts, "updated_at": ts,
            "version": 1, "_seq": next_seq()}


def touch(obj):
    obj["updated_at"] = now_iso()
    obj["version"] += 1


def find(kind, oid):
    obj = db[kind].get(oid)
    if obj is None:
        err("ERR_NOT_FOUND", 404, f"{kind} {oid} not found")
    return obj


def sort_seq(items):
    return sorted(items, key=lambda o: o["_seq"])


def post_ledger(bill_id, installment_sequence, entry_type, amount_cents, memo):
    entry = {"id": str(uuid.uuid4()), "created_at": now_iso(), "_seq": next_seq(),
             "bill_id": bill_id, "installment_sequence": installment_sequence,
             "entry_type": entry_type, "amount_cents": amount_cents, "memo": memo}
    db["ledger"][entry["id"]] = entry
    return entry


def ledger_of(bill_id):
    return sort_seq([e for e in db["ledger"].values() if e["bill_id"] == bill_id])


def installments_of(bill_id):
    insts = [i for i in db["installments"].values() if i["bill_id"] == bill_id]
    return sorted(insts, key=lambda i: (i["sequence"], i["_seq"]))


def sum_ledger(bill_id, seq=None, types=None):
    total = 0
    for e in db["ledger"].values():
        if e["bill_id"] != bill_id:
            continue
        if seq is not None and e["installment_sequence"] != seq:
            continue
        if types is not None and e["entry_type"] not in types:
            continue
        total += e["amount_cents"]
    return total


# ---------------------------------------------------------------------------
# Financial computation
# ---------------------------------------------------------------------------
def inst_fin(bill_id, inst):
    """Compute financial breakdown for an installment from ledger + payments."""
    seq = inst["sequence"]
    principal_due = inst["principal_due_cents"]
    penalty_charged = sum_ledger(bill_id, seq, {"PENALTY"})
    interest_charged = sum_ledger(bill_id, seq, {"INTEREST"})
    abatement_amt = -sum_ledger(bill_id, seq, {"ABATEMENT"})  # positive
    penalty_paid = interest_paid = principal_paid = 0
    for pay in db["payments"].values():
        if pay["bill_id"] != bill_id or pay["status"] != "POSTED":
            continue
        for a in pay["allocation"]:
            if a["sequence"] == seq:
                penalty_paid += a["penalty_cents"]
                interest_paid += a["interest_cents"]
                principal_paid += a["principal_cents"]
    penalty_out = penalty_charged - penalty_paid
    interest_out = interest_charged - interest_paid
    principal_out = principal_due - principal_paid - abatement_amt
    if penalty_out < 0:
        penalty_out = 0
    if interest_out < 0:
        interest_out = 0
    if principal_out < 0:
        principal_out = 0
    paid_cents = penalty_paid + interest_paid + principal_paid
    balance = principal_due + penalty_charged + interest_charged - paid_cents - abatement_amt
    unpaid_principal = max(0, principal_due - principal_paid - abatement_amt)
    return {
        "seq": seq, "principal_due": principal_due,
        "penalty_charged": penalty_charged, "interest_charged": interest_charged,
        "abatement": abatement_amt,
        "penalty_out": penalty_out, "interest_out": interest_out,
        "principal_out": principal_out,
        "paid_cents": paid_cents, "balance": balance,
        "unpaid_principal": unpaid_principal,
    }


def inst_status(bill_id, inst):
    fin = inst_fin(bill_id, inst)
    if fin["balance"] <= 0:
        return "PAID"
    clock_date = CLOCK["dt"].date()
    if clock_date > inst["_due_dt"].date() and fin["unpaid_principal"] > 0:
        return "DELINQUENT"
    applied = fin["paid_cents"] + fin["abatement"]
    if applied > 0:
        return "PARTIALLY_PAID"
    return "PENDING"


def materialize(bill):
    """Post penalty/interest ledger entries for delinquent installments up to
    the current logical clock. Idempotent."""
    bill_id = bill["id"]
    clock_date = CLOCK["dt"].date()
    for inst in installments_of(bill_id):
        seq = inst["sequence"]
        fin = inst_fin(bill_id, inst)
        if not (clock_date > inst["_due_dt"].date() and fin["unpaid_principal"] > 0):
            continue
        principal_due = inst["principal_due_cents"]
        cap = principal_due
        existing_penalty = sum_ledger(bill_id, seq, {"PENALTY"})
        penalty = rhu(Decimal(principal_due) * PENALTY_RATE)
        if existing_penalty == 0 and penalty > 0:
            post_ledger(bill_id, seq, "PENALTY", min(penalty, cap),
                        f"penalty 5% installment {seq}")
        # interest per whole month, capped so penalty+interest <= principal
        per_month = rhu(Decimal(principal_due) * INTEREST_RATE_MONTHLY)
        desired_months = months_elapsed(inst["_due_dt"].date(), clock_date)
        already_months = len([e for e in db["ledger"].values()
                              if e["bill_id"] == bill_id
                              and e["installment_sequence"] == seq
                              and e["entry_type"] == "INTEREST"])
        cur_penalty = sum_ledger(bill_id, seq, {"PENALTY"})
        cur_interest = sum_ledger(bill_id, seq, {"INTEREST"})
        remaining_cap = principal_due - cur_penalty - cur_interest
        for _m in range(already_months, desired_months):
            if remaining_cap <= 0:
                break
            amt = min(per_month, remaining_cap)
            if amt <= 0:
                break
            post_ledger(bill_id, seq, "INTEREST", amt,
                        f"interest 1% installment {seq}")
            remaining_cap -= amt


def parcel_of_bill(bill):
    return db["parcels"].get(bill["parcel_id"])


def bill_collection_status(bill):
    insts = installments_of(bill["id"])
    if not insts:
        return "CURRENT"
    statuses = [inst_status(bill["id"], i) for i in insts]
    if all(s == "PAID" for s in statuses):
        return "PAID"
    if any(s == "DELINQUENT" for s in statuses):
        return "DELINQUENT"
    total_paid = -sum_ledger(bill["id"], types={"PAYMENT"}) - sum_ledger(bill["id"], types={"REVERSAL"})
    if any(s in ("PARTIALLY_PAID", "PAID") for s in statuses) or total_paid > 0:
        return "PARTIALLY_PAID"
    return "CURRENT"


def bill_sale_status(bill):
    refs = [r for r in db["referrals"].values() if r["bill_id"] == bill["id"]]
    if not refs:
        return "NONE"
    if any(r["status"] == "SOLD" for r in refs):
        return "SOLD"
    if any(r["status"] == "REFERRED" for r in refs):
        return "IN_TAX_SALE"
    if any(r["status"] == "REDEEMED" for r in refs):
        return "REDEEMED"
    return "NONE"


def bill_delinquent_principal(bill):
    total = 0
    for inst in installments_of(bill["id"]):
        if inst_status(bill["id"], inst) == "DELINQUENT":
            total += inst_fin(bill["id"], inst)["unpaid_principal"]
    return total


def bill_overpayment(bill):
    return max(0, -sum_ledger(bill["id"]))


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def ser_tax_year(o):
    return {k: o[k] for k in ("id", "created_at", "updated_at", "version",
                              "year", "millage_rate",
                              "first_installment_due_date", "second_installment_due_date")}


def ser_escrow(o):
    return {k: o[k] for k in ("id", "created_at", "updated_at", "version",
                              "name", "servicer_code")}


def ser_parcel(o):
    return {k: o[k] for k in ("id", "created_at", "updated_at", "version",
                              "parcel_number", "owner_name", "situs_address",
                              "assessed_value_cents", "property_class",
                              "homestead", "escrow_agent_id")}


def ser_bill(o):
    materialize(o)
    bid = o["id"]
    balance = sum_ledger(bid)
    total_charged = sum_ledger(bid, types={"CHARGE", "PENALTY", "INTEREST"})
    total_paid = -sum_ledger(bid, types={"PAYMENT"}) - sum_ledger(bid, types={"REVERSAL"})
    approved_refunds = sum(r["approved_amount_cents"] or 0 for r in db["refunds"].values()
                           if r["bill_id"] == bid and r["status"] == "APPROVED")
    abatement_credit = -sum_ledger(bid, types={"ABATEMENT"})
    return {
        "id": o["id"], "created_at": o["created_at"], "updated_at": o["updated_at"],
        "version": o["version"],
        "parcel_id": o["parcel_id"], "tax_year_id": o["tax_year_id"],
        "gross_tax_cents": o["gross_tax_cents"],
        "exemption_credit_cents": o["exemption_credit_cents"],
        "net_tax_cents": o["net_tax_cents"],
        "abatement_credit_cents": abatement_credit,
        "total_charged_cents": total_charged,
        "total_paid_cents": total_paid,
        "total_applied_cents": total_paid - approved_refunds,
        "balance_cents": balance,
        "overpayment_cents": max(0, -balance),
        "delinquent_principal_cents": bill_delinquent_principal(o),
        "collection_status": bill_collection_status(o),
        "sale_status": bill_sale_status(o),
    }


def ser_installment(o):
    bill = db["tax_bills"].get(o["bill_id"])
    if bill:
        materialize(bill)
    fin = inst_fin(o["bill_id"], o)
    return {
        "id": o["id"], "created_at": o["created_at"], "updated_at": o["updated_at"],
        "version": o["version"],
        "bill_id": o["bill_id"], "sequence": o["sequence"],
        "principal_due_cents": o["principal_due_cents"], "due_date": o["due_date"],
        "penalty_cents": fin["penalty_charged"], "interest_cents": fin["interest_charged"],
        "paid_cents": fin["paid_cents"], "balance_cents": fin["balance"],
        "status": inst_status(o["bill_id"], o),
    }


def ser_relief(o):
    return {
        "id": o["id"], "created_at": o["created_at"], "updated_at": o["updated_at"],
        "version": o["version"],
        "parcel_id": o["parcel_id"], "tax_year_id": o["tax_year_id"],
        "relief_class": o["relief_class"], "relief_type": o["relief_type"],
        "claimed_amount_cents": o["claimed_amount_cents"],
        "effective_from": o["effective_from"], "effective_to": o["effective_to"],
        "status": o["status"], "approved_credit_cents": o["approved_credit_cents"],
        "info_request_count": o["info_request_count"],
        "decided_by_user_id": o["decided_by_user_id"],
    }


def ser_payment(o):
    return {
        "id": o["id"], "created_at": o["created_at"], "updated_at": o["updated_at"],
        "version": o["version"],
        "bill_id": o["bill_id"], "amount_cents": o["amount_cents"],
        "tender_type": o["tender_type"], "source": o["source"],
        "escrow_agent_id": o["escrow_agent_id"], "status": o["status"],
        "allocation": o["allocation"],
        "overpayment_applied_cents": o["overpayment_applied_cents"],
        "posted_by_user_id": o["posted_by_user_id"],
        "reversed_by_user_id": o["reversed_by_user_id"],
    }


def ser_refund(o):
    return {
        "id": o["id"], "created_at": o["created_at"], "updated_at": o["updated_at"],
        "version": o["version"],
        "bill_id": o["bill_id"], "amount_cents": o["amount_cents"], "mode": o["mode"],
        "status": o["status"], "approved_amount_cents": o["approved_amount_cents"],
        "requested_by_user_id": o["requested_by_user_id"],
        "decided_by_user_id": o["decided_by_user_id"],
    }


def ser_referral(o):
    return {
        "id": o["id"], "created_at": o["created_at"], "updated_at": o["updated_at"],
        "version": o["version"],
        "bill_id": o["bill_id"], "referral_date": o["referral_date"],
        "redemption_deadline": o["redemption_deadline"],
        "delinquent_principal_at_referral_cents": o["delinquent_principal_at_referral_cents"],
        "status": o["status"], "created_by_user_id": o["created_by_user_id"],
        "sold_by_user_id": o["sold_by_user_id"], "sale_price_cents": o["sale_price_cents"],
    }


def ser_ledger(o):
    return {"id": o["id"], "created_at": o["created_at"], "bill_id": o["bill_id"],
            "installment_sequence": o["installment_sequence"],
            "entry_type": o["entry_type"], "amount_cents": o["amount_cents"],
            "memo": o["memo"]}


# ===========================================================================
# TaxYear
# ===========================================================================
@app.route("/property-tax/tax-years", methods=["POST"])
def create_tax_year():
    _, role = authn()
    require_roles(role, {"Treasurer"})
    data = body_json()
    year = req_int(data, "year")
    millage = req_num(data, "millage_rate")
    first = req_datetime(data, "first_installment_due_date")
    second = req_datetime(data, "second_installment_due_date")
    if year < 2000:
        err("ERR_VALIDATION", 400, "year must be >= 2000")
    if not (parse_iso(second) > parse_iso(first)):
        err("ERR_VALIDATION", 400, "second_installment_due_date must be after first")
    if any(ty["year"] == year for ty in db["tax_years"].values()):
        err("ERR_VALIDATION", 400, "year already exists")
    obj = new_common()
    obj.update({"year": year, "millage_rate": millage,
                "first_installment_due_date": first,
                "second_installment_due_date": second})
    db["tax_years"][obj["id"]] = obj
    return ok(ser_tax_year(obj), 201)


@app.route("/property-tax/tax-years/<oid>", methods=["GET"])
def get_tax_year(oid):
    _, role = authn()
    require_roles(role, set(ALL_ROLES))
    return ok(ser_tax_year(find("tax_years", oid)))


# ===========================================================================
# EscrowAgent
# ===========================================================================
@app.route("/property-tax/escrow-agents", methods=["POST"])
def create_escrow_agent():
    _, role = authn()
    require_roles(role, {"Treasurer"})
    data = body_json()
    name = req_str(data, "name")
    code = req_str(data, "servicer_code")
    if any(e["servicer_code"] == code for e in db["escrow_agents"].values()):
        err("ERR_VALIDATION", 400, "servicer_code already exists")
    obj = new_common()
    obj.update({"name": name, "servicer_code": code})
    db["escrow_agents"][obj["id"]] = obj
    return ok(ser_escrow(obj), 201)


# ===========================================================================
# Parcel
# ===========================================================================
@app.route("/property-tax/parcels", methods=["POST"])
def create_parcel():
    _, role = authn()
    require_roles(role, {"Cashier", "Treasurer"})
    data = body_json()
    parcel_number = req_str(data, "parcel_number")
    owner_name = req_str(data, "owner_name")
    situs = req_str(data, "situs_address")
    assessed = req_int(data, "assessed_value_cents")
    property_class = req_str(data, "property_class")
    escrow_agent_id = data.get("escrow_agent_id")
    if escrow_agent_id is not None:
        find("escrow_agents", escrow_agent_id)
    homestead = data.get("homestead", False)
    if homestead is None:
        homestead = False
    if not isinstance(homestead, bool):
        err("ERR_VALIDATION", 400, "homestead must be a boolean")
    if assessed < 0:
        err("ERR_VALIDATION", 400, "assessed_value_cents must be >= 0")
    if property_class not in ENUM_PROPERTY_CLASS:
        err("ERR_INVALID_ENUM", 422, "property_class outside declared domain")
    if any(p["parcel_number"] == parcel_number for p in db["parcels"].values()):
        err("ERR_VALIDATION", 400, "parcel_number already exists")
    obj = new_common()
    obj.update({"parcel_number": parcel_number, "owner_name": owner_name,
                "situs_address": situs, "assessed_value_cents": assessed,
                "property_class": property_class, "homestead": homestead,
                "escrow_agent_id": escrow_agent_id})
    db["parcels"][obj["id"]] = obj
    return ok(ser_parcel(obj), 201)


@app.route("/property-tax/parcels/<oid>", methods=["GET"])
def get_parcel(oid):
    _, role = authn()
    require_roles(role, set(ALL_ROLES))
    return ok(ser_parcel(find("parcels", oid)))


@app.route("/property-tax/parcels", methods=["GET"])
def list_parcels():
    _, role = authn()
    require_roles(role, set(ALL_ROLES))
    items = sort_seq(list(db["parcels"].values()))
    ea = request.args.get("escrow_agent_id")
    if ea is not None:
        items = [p for p in items if p["escrow_agent_id"] == ea]
    page, pag = paginate(items)
    return ok([ser_parcel(p) for p in page], pagination=pag)


# ===========================================================================
# TaxBill
# ===========================================================================
def gross_for(parcel, tax_year):
    return rhu(Decimal(parcel["assessed_value_cents"]) * Decimal(str(tax_year["millage_rate"])) / Decimal(1000))


@app.route("/property-tax/tax-bills", methods=["POST"])
def create_tax_bill():
    _, role = authn()
    require_roles(role, {"Treasurer"})
    data = body_json()
    parcel_id = req_str(data, "parcel_id")
    tax_year_id = req_str(data, "tax_year_id")
    parcel = find("parcels", parcel_id)
    tax_year = find("tax_years", tax_year_id)
    for b in db["tax_bills"].values():
        if b["parcel_id"] == parcel_id and b["tax_year_id"] == tax_year_id:
            err("ERR_DUPLICATE_BILL", 409, "A bill already exists for this parcel and tax year")
    gross = gross_for(parcel, tax_year)
    exemption = 0
    for ra in db["relief_apps"].values():
        if (ra["parcel_id"] == parcel_id and ra["tax_year_id"] == tax_year_id
                and ra["relief_class"] == "EXEMPTION" and ra["status"] == "APPROVED"):
            exemption += ra["approved_credit_cents"] or 0
    if exemption > gross:
        exemption = gross
    net = max(0, gross - exemption)

    bill = new_common()
    bill.update({"parcel_id": parcel_id, "tax_year_id": tax_year_id,
                 "gross_tax_cents": gross, "exemption_credit_cents": exemption,
                 "net_tax_cents": net})
    db["tax_bills"][bill["id"]] = bill

    base = net // INSTALLMENT_COUNT
    principals = [base, net - base]
    due_strs = [tax_year["first_installment_due_date"], tax_year["second_installment_due_date"]]
    for i in range(INSTALLMENT_COUNT):
        inst = new_common()
        inst.update({"bill_id": bill["id"], "sequence": i + 1,
                     "principal_due_cents": principals[i], "due_date": due_strs[i],
                     "_due_dt": parse_iso(due_strs[i])})
        db["installments"][inst["id"]] = inst
        post_ledger(bill["id"], i + 1, "CHARGE", principals[i], f"levy installment {i + 1}")
    materialize(bill)
    return ok(ser_bill(bill), 201)


@app.route("/property-tax/tax-bills/<oid>", methods=["GET"])
def get_tax_bill(oid):
    _, role = authn()
    require_roles(role, set(ALL_ROLES))
    return ok(ser_bill(find("tax_bills", oid)))


@app.route("/property-tax/tax-bills", methods=["GET"])
def list_tax_bills():
    _, role = authn()
    require_roles(role, set(ALL_ROLES))
    items = sort_seq(list(db["tax_bills"].values()))
    pid = request.args.get("parcel_id")
    tid = request.args.get("tax_year_id")
    if pid is not None:
        items = [b for b in items if b["parcel_id"] == pid]
    if tid is not None:
        items = [b for b in items if b["tax_year_id"] == tid]
    page, pag = paginate(items)
    return ok([ser_bill(b) for b in page], pagination=pag)


@app.route("/property-tax/tax-bills/<oid>/payoff", methods=["GET"])
def bill_payoff(oid):
    _, role = authn()
    require_roles(role, set(ALL_ROLES))
    bill = find("tax_bills", oid)
    materialize(bill)
    mode = request.args.get("mode", "LEDGER_AS_OF")
    if mode not in ENUM_PAYOFF_MODE:
        err("ERR_INVALID_ENUM", 422, "mode outside declared domain")
    as_of = request.args.get("as_of_date")

    insts = installments_of(oid)
    principal_balance = sum(inst_fin(oid, i)["unpaid_principal"] for i in insts)
    penalty_total = sum(inst_fin(oid, i)["penalty_charged"] for i in insts)

    if mode == "PAYOFF_QUOTE" and as_of is not None:
        as_of_dt = None
        try:
            as_of_dt = parse_iso(as_of)
        except Exception:
            err("ERR_VALIDATION", 400, "as_of_date must be ISO8601")
        interest = 0
        for i in insts:
            fin = inst_fin(oid, i)
            up = fin["unpaid_principal"]
            if up <= 0:
                continue
            days = (as_of_dt.date() - i["_due_dt"].date()).days
            if days < 0:
                days = 0
            interest += rhu(Decimal(up) * INTEREST_RATE_MONTHLY * Decimal(12)
                            / Decimal(DAYS_PER_YEAR) * Decimal(days))
    else:
        interest = sum(inst_fin(oid, i)["interest_charged"] for i in insts)

    payoff_total = principal_balance + penalty_total + interest
    return ok({"mode": mode, "as_of_date": as_of,
               "principal_balance_cents": principal_balance,
               "penalty_cents": penalty_total, "interest_cents": interest,
               "payoff_total_cents": payoff_total})


@app.route("/property-tax/tax-bills/<oid>/ledger-entries", methods=["GET"])
def bill_ledger_entries(oid):
    _, role = authn()
    require_roles(role, set(ALL_ROLES))
    bill = find("tax_bills", oid)
    materialize(bill)
    items = ledger_of(oid)
    page, pag = paginate(items)
    return ok([ser_ledger(e) for e in page], pagination=pag)


# ===========================================================================
# Installment
# ===========================================================================
@app.route("/property-tax/installments/<oid>", methods=["GET"])
def get_installment(oid):
    _, role = authn()
    require_roles(role, set(ALL_ROLES))
    return ok(ser_installment(find("installments", oid)))


@app.route("/property-tax/installments", methods=["GET"])
def list_installments():
    _, role = authn()
    require_roles(role, set(ALL_ROLES))
    items = sort_seq(list(db["installments"].values()))
    bid = request.args.get("bill_id")
    if bid is not None:
        items = [i for i in items if i["bill_id"] == bid]
    page, pag = paginate(items)
    return ok([ser_installment(i) for i in page], pagination=pag)


# ===========================================================================
# TaxReliefApplication
# ===========================================================================
def intervals_overlap(a_from, a_to, b_from, b_to):
    # closed intervals; touching counts as overlap
    return a_from <= b_to and b_from <= a_to


@app.route("/property-tax/relief-applications", methods=["POST"])
def create_relief():
    uid, role = authn()
    require_roles(role, {"Taxpayer", "Cashier"})
    data = body_json()
    parcel_id = req_str(data, "parcel_id")
    tax_year_id = req_str(data, "tax_year_id")
    parcel = find("parcels", parcel_id)
    find("tax_years", tax_year_id)
    if role == "Taxpayer" and uid != parcel_id:
        err("ERR_FORBIDDEN", 403, "Taxpayer may only act on own parcel")
    relief_class = req_str(data, "relief_class")
    relief_type = req_str(data, "relief_type")
    claimed = req_int(data, "claimed_amount_cents")
    eff_from = req_datetime(data, "effective_from")
    eff_to = req_datetime(data, "effective_to")
    if claimed <= 0:
        err("ERR_VALIDATION", 400, "claimed_amount_cents must be > 0")
    if parse_iso(eff_to) < parse_iso(eff_from):
        err("ERR_VALIDATION", 400, "effective_to must be >= effective_from")
    if relief_class not in ENUM_RELIEF_CLASS:
        err("ERR_INVALID_ENUM", 422, "relief_class outside declared domain")
    if relief_type not in ENUM_RELIEF_TYPE:
        err("ERR_INVALID_ENUM", 422, "relief_type outside declared domain")
    obj = new_common()
    obj.update({"parcel_id": parcel_id, "tax_year_id": tax_year_id,
                "relief_class": relief_class, "relief_type": relief_type,
                "claimed_amount_cents": claimed, "effective_from": eff_from,
                "effective_to": eff_to, "status": "SUBMITTED",
                "approved_credit_cents": None, "info_request_count": 0,
                "decided_by_user_id": None})
    db["relief_apps"][obj["id"]] = obj
    return ok(ser_relief(obj), 201)


@app.route("/property-tax/relief-applications/<oid>", methods=["GET"])
def get_relief(oid):
    _, role = authn()
    require_roles(role, set(ALL_ROLES))
    return ok(ser_relief(find("relief_apps", oid)))


@app.route("/property-tax/relief-applications", methods=["GET"])
def list_relief():
    _, role = authn()
    require_roles(role, set(ALL_ROLES))
    items = sort_seq(list(db["relief_apps"].values()))
    pid = request.args.get("parcel_id")
    tid = request.args.get("tax_year_id")
    if pid is not None:
        items = [r for r in items if r["parcel_id"] == pid]
    if tid is not None:
        items = [r for r in items if r["tax_year_id"] == tid]
    page, pag = paginate(items)
    return ok([ser_relief(r) for r in page], pagination=pag)


def relief_terminal_guard(app_obj):
    if app_obj["status"] in ("APPROVED", "DENIED"):
        err("ERR_RELIEF_ALREADY_DECIDED", 409, "Application already decided")


@app.route("/property-tax/relief-applications/<oid>/review", methods=["POST"])
def relief_review(oid):
    _, role = authn()
    require_roles(role, {"ReliefOfficer"})
    app_obj = find("relief_apps", oid)
    relief_terminal_guard(app_obj)
    if app_obj["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE", 409, "review requires SUBMITTED")
    app_obj["status"] = "UNDER_REVIEW"
    touch(app_obj)
    return ok(ser_relief(app_obj))


@app.route("/property-tax/relief-applications/<oid>/request-info", methods=["POST"])
def relief_request_info(oid):
    _, role = authn()
    require_roles(role, {"ReliefOfficer"})
    app_obj = find("relief_apps", oid)
    relief_terminal_guard(app_obj)
    if app_obj["status"] != "UNDER_REVIEW":
        err("ERR_INVALID_STATE", 409, "request-info requires UNDER_REVIEW")
    app_obj["status"] = "INFO_REQUESTED"
    app_obj["info_request_count"] += 1
    touch(app_obj)
    return ok(ser_relief(app_obj))


@app.route("/property-tax/relief-applications/<oid>/resubmit", methods=["POST"])
def relief_resubmit(oid):
    uid, role = authn()
    require_roles(role, {"Taxpayer", "Cashier"})
    app_obj = find("relief_apps", oid)
    if role == "Taxpayer" and uid != app_obj["parcel_id"]:
        err("ERR_FORBIDDEN", 403, "Taxpayer may only act on own application")
    relief_terminal_guard(app_obj)
    if app_obj["status"] != "INFO_REQUESTED":
        err("ERR_INVALID_STATE", 409, "resubmit requires INFO_REQUESTED")
    app_obj["status"] = "UNDER_REVIEW"
    touch(app_obj)
    return ok(ser_relief(app_obj))


@app.route("/property-tax/relief-applications/<oid>/decide", methods=["POST"])
def relief_decide(oid):
    uid, role = authn()
    require_roles(role, {"ReliefOfficer"})
    app_obj = find("relief_apps", oid)
    data = body_json()
    decision = data.get("decision")
    if decision is None:
        err("ERR_VALIDATION", 400, "Missing required field: decision")
    if decision not in ("APPROVE", "DENY"):
        err("ERR_VALIDATION", 400, "decision must be APPROVE or DENY")
    relief_terminal_guard(app_obj)
    if app_obj["status"] != "UNDER_REVIEW":
        err("ERR_INVALID_STATE", 409, "decide requires UNDER_REVIEW")

    if decision == "DENY":
        app_obj["status"] = "DENIED"
        app_obj["decided_by_user_id"] = uid
        touch(app_obj)
        return ok(ser_relief(app_obj))

    # APPROVE
    parcel_id = app_obj["parcel_id"]
    for other in db["relief_apps"].values():
        if other["id"] == oid:
            continue
        if other["parcel_id"] != parcel_id:
            continue
        if other["status"] not in ("SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED", "APPROVED"):
            continue
        if intervals_overlap(parse_iso(app_obj["effective_from"]).date(),
                             parse_iso(app_obj["effective_to"]).date(),
                             parse_iso(other["effective_from"]).date(),
                             parse_iso(other["effective_to"]).date()):
            err("ERR_RELIEF_PERIOD_OVERLAP", 409, "Overlapping relief period on parcel")

    target_bill = None
    for b in db["tax_bills"].values():
        if b["parcel_id"] == parcel_id and b["tax_year_id"] == app_obj["tax_year_id"]:
            target_bill = b
            break

    if app_obj["relief_class"] == "ABATEMENT":
        if target_bill is not None:
            materialize(target_bill)
            if bill_collection_status(target_bill) == "PAID":
                err("ERR_INVALID_STATE", 409, "Cannot abate a fully paid bill")
        unpaid = []
        ceiling = 0
        if target_bill is not None:
            for inst in installments_of(target_bill["id"]):
                fin = inst_fin(target_bill["id"], inst)
                if fin["balance"] > 0:
                    unpaid.append((inst, fin["balance"]))
                    ceiling += fin["balance"]
        approved = min(app_obj["claimed_amount_cents"], ceiling)
        remaining = approved
        for inst, bal in unpaid:
            if remaining <= 0:
                break
            credit = min(remaining, bal)
            post_ledger(target_bill["id"], inst["sequence"], "ABATEMENT", -credit,
                        f"abatement installment {inst['sequence']}")
            remaining -= credit
        app_obj["approved_credit_cents"] = approved
    else:  # EXEMPTION
        parcel = db["parcels"][parcel_id]
        tax_year = db["tax_years"][app_obj["tax_year_id"]]
        ceiling = gross_for(parcel, tax_year)
        app_obj["approved_credit_cents"] = min(app_obj["claimed_amount_cents"], ceiling)

    app_obj["status"] = "APPROVED"
    app_obj["decided_by_user_id"] = uid
    touch(app_obj)
    return ok(ser_relief(app_obj))


# ===========================================================================
# Payment
# ===========================================================================
def apply_payment_allocation(bill, amount):
    materialize(bill)
    remaining = amount
    allocation = []
    posted_entries = []
    ordered = sorted(installments_of(bill["id"]),
                     key=lambda i: (i["_due_dt"], i["sequence"], i["_seq"]))
    for inst in ordered:
        fin = inst_fin(bill["id"], inst)
        seq = inst["sequence"]
        p_pay = min(remaining, fin["penalty_out"])
        remaining -= p_pay
        i_pay = min(remaining, fin["interest_out"])
        remaining -= i_pay
        pr_pay = min(remaining, fin["principal_out"])
        remaining -= pr_pay
        total = p_pay + i_pay + pr_pay
        if total > 0:
            allocation.append({"sequence": seq, "penalty_cents": p_pay,
                               "interest_cents": i_pay, "principal_cents": pr_pay})
            entry = post_ledger(bill["id"], seq, "PAYMENT", -total, f"payment installment {seq}")
            posted_entries.append({"seq": seq, "amount": -total})
    overpayment = remaining
    if overpayment > 0:
        post_ledger(bill["id"], None, "PAYMENT", -overpayment, "payment overpayment credit")
        posted_entries.append({"seq": None, "amount": -overpayment})
    return allocation, overpayment, posted_entries


@app.route("/property-tax/payments", methods=["POST"])
def create_payment():
    uid, role = authn()
    require_roles(role, {"Cashier", "Taxpayer"})
    data = body_json()
    bill_id = req_str(data, "bill_id")
    bill = find("tax_bills", bill_id)
    escrow_agent_id = data.get("escrow_agent_id")
    if escrow_agent_id is not None:
        find("escrow_agents", escrow_agent_id)
    if role == "Taxpayer" and uid != bill["parcel_id"]:
        err("ERR_FORBIDDEN", 403, "Taxpayer may only pay own bill")
    amount = req_int(data, "amount_cents")
    tender = req_str(data, "tender_type")
    source = req_str(data, "source")
    if amount <= 0:
        err("ERR_ZERO_AMOUNT", 422, "amount_cents must be > 0")
    if source == "ESCROW" and escrow_agent_id is None:
        err("ERR_ESCROW_AGENT_REQUIRED", 422, "escrow_agent_id required for ESCROW source")
    if tender not in ENUM_TENDER:
        err("ERR_INVALID_ENUM", 422, "tender_type outside declared domain")
    if source not in ENUM_SOURCE:
        err("ERR_INVALID_ENUM", 422, "source outside declared domain")
    materialize(bill)
    if bill_collection_status(bill) == "PAID":
        err("ERR_BILL_ALREADY_PAID", 409, "Bill is already paid")

    allocation, overpayment, posted_entries = apply_payment_allocation(bill, amount)
    pay = new_common()
    pay.update({"bill_id": bill_id, "amount_cents": amount, "tender_type": tender,
                "source": source, "escrow_agent_id": escrow_agent_id,
                "status": "POSTED", "allocation": allocation,
                "overpayment_applied_cents": overpayment,
                "posted_by_user_id": uid, "reversed_by_user_id": None,
                "_posted_entries": posted_entries})
    db["payments"][pay["id"]] = pay
    # bill version bump
    bill["version"] += 1
    bill["updated_at"] = now_iso()
    # cascade: full payment auto-redeems open referral
    if sum_ledger(bill_id) <= 0:
        for ref in db["referrals"].values():
            if ref["bill_id"] == bill_id and ref["status"] == "REFERRED":
                ref["status"] = "REDEEMED"
                touch(ref)
    return ok(ser_payment(pay), 201)


@app.route("/property-tax/payments/<oid>", methods=["GET"])
def get_payment(oid):
    _, role = authn()
    require_roles(role, set(ALL_ROLES))
    return ok(ser_payment(find("payments", oid)))


@app.route("/property-tax/payments", methods=["GET"])
def list_payments():
    _, role = authn()
    require_roles(role, set(ALL_ROLES))
    items = sort_seq(list(db["payments"].values()))
    bid = request.args.get("bill_id")
    ea = request.args.get("escrow_agent_id")
    if bid is not None:
        items = [p for p in items if p["bill_id"] == bid]
    if ea is not None:
        items = [p for p in items if p["escrow_agent_id"] == ea]
    page, pag = paginate(items)
    return ok([ser_payment(p) for p in page], pagination=pag)


@app.route("/property-tax/payments/<oid>/reverse", methods=["POST"])
def reverse_payment(oid):
    uid, role = authn()
    require_roles(role, {"Treasurer"})
    pay = find("payments", oid)
    if pay["status"] == "REVERSED":
        err("ERR_PAYMENT_ALREADY_REVERSED", 409, "Payment already reversed")
    for e in pay["_posted_entries"]:
        post_ledger(pay["bill_id"], e["seq"], "REVERSAL", -e["amount"],
                    f"reversal installment {e['seq']}" if e["seq"] else "reversal overpayment")
    pay["status"] = "REVERSED"
    pay["reversed_by_user_id"] = uid
    touch(pay)
    bill = db["tax_bills"].get(pay["bill_id"])
    if bill:
        bill["version"] += 1
        bill["updated_at"] = now_iso()
        materialize(bill)
    return ok(ser_payment(pay))


# ===========================================================================
# Refund
# ===========================================================================
@app.route("/property-tax/refunds", methods=["POST"])
def create_refund():
    uid, role = authn()
    require_roles(role, {"Taxpayer", "Cashier", "Treasurer"})
    data = body_json()
    bill_id = req_str(data, "bill_id")
    bill = find("tax_bills", bill_id)
    if role == "Taxpayer" and uid != bill["parcel_id"]:
        err("ERR_FORBIDDEN", 403, "Taxpayer may only refund own bill")
    amount = req_int(data, "amount_cents")
    mode = req_str(data, "mode")
    expected = req_int(data, "expected_bill_version")
    if amount <= 0:
        err("ERR_ZERO_AMOUNT", 422, "amount_cents must be > 0")
    if mode not in ENUM_REFUND_MODE:
        err("ERR_INVALID_ENUM", 422, "mode outside declared domain")
    if expected != bill["version"]:
        err("ERR_STALE_VERSION", 412, "expected_bill_version does not match")
    obj = new_common()
    obj.update({"bill_id": bill_id, "amount_cents": amount, "mode": mode,
                "status": "REQUESTED", "approved_amount_cents": None,
                "requested_by_user_id": uid, "decided_by_user_id": None})
    db["refunds"][obj["id"]] = obj
    bill["version"] += 1
    bill["updated_at"] = now_iso()
    return ok(ser_refund(obj), 201)


@app.route("/property-tax/refunds/<oid>", methods=["GET"])
def get_refund(oid):
    _, role = authn()
    require_roles(role, set(ALL_ROLES))
    return ok(ser_refund(find("refunds", oid)))


@app.route("/property-tax/refunds", methods=["GET"])
def list_refunds():
    _, role = authn()
    require_roles(role, set(ALL_ROLES))
    items = sort_seq(list(db["refunds"].values()))
    bid = request.args.get("bill_id")
    if bid is not None:
        items = [r for r in items if r["bill_id"] == bid]
    page, pag = paginate(items)
    return ok([ser_refund(r) for r in page], pagination=pag)


@app.route("/property-tax/refunds/<oid>/decide", methods=["POST"])
def refund_decide(oid):
    uid, role = authn()
    require_roles(role, {"Treasurer"})
    refund = find("refunds", oid)
    data = body_json()
    decision = data.get("decision")
    if decision is None:
        err("ERR_VALIDATION", 400, "Missing required field: decision")
    if decision not in ("APPROVE", "DENY"):
        err("ERR_VALIDATION", 400, "decision must be APPROVE or DENY")
    # SoD precedes other decision checks
    if uid == refund["requested_by_user_id"]:
        err("ERR_SEGREGATION_OF_DUTIES", 403, "Requester may not decide own refund")
    if refund["status"] in ("APPROVED", "DENIED"):
        err("ERR_REFUND_ALREADY_DECIDED", 409, "Refund already decided")

    if decision == "DENY":
        refund["status"] = "DENIED"
        refund["decided_by_user_id"] = uid
        touch(refund)
        return ok(ser_refund(refund))

    bill = db["tax_bills"].get(refund["bill_id"])
    materialize(bill)
    overpayment = bill_overpayment(bill)
    if refund["mode"] == "GROSS_OVERPAYMENT":
        available = overpayment
    else:
        other_delinquent = 0
        for b in db["tax_bills"].values():
            if b["id"] == bill["id"]:
                continue
            if b["parcel_id"] == bill["parcel_id"]:
                other_delinquent += bill_delinquent_principal(b)
        available = max(0, overpayment - other_delinquent)
    if refund["amount_cents"] > available:
        err("ERR_OVERPAYMENT_UNAVAILABLE", 409, "Refund exceeds available overpayment")
    approved = refund["amount_cents"]
    post_ledger(bill["id"], None, "REFUND", approved, "refund")
    refund["approved_amount_cents"] = approved
    refund["status"] = "APPROVED"
    refund["decided_by_user_id"] = uid
    touch(refund)
    bill["version"] += 1
    bill["updated_at"] = now_iso()
    return ok(ser_refund(refund))


# ===========================================================================
# TaxSaleReferral
# ===========================================================================
@app.route("/property-tax/tax-sale-referrals", methods=["POST"])
def create_referral():
    uid, role = authn()
    require_roles(role, {"CollectionsOfficer"})
    data = body_json()
    bill_id = req_str(data, "bill_id")
    bill = find("tax_bills", bill_id)
    expected = req_int(data, "expected_bill_version")
    materialize(bill)
    # §3.8 order: not-delinquent -> threshold -> window overlap -> stale version
    if bill_collection_status(bill) != "DELINQUENT" or not any(
            inst_status(bill_id, i) == "DELINQUENT" for i in installments_of(bill_id)):
        err("ERR_NOT_DELINQUENT", 409, "Bill is not delinquent")
    delinquent_principal = bill_delinquent_principal(bill)
    if delinquent_principal < LIEN_REFERRAL_THRESHOLD_CENTS:
        err("ERR_BELOW_REFERRAL_THRESHOLD", 409, "Delinquent principal below threshold")
    parcel_id = bill["parcel_id"]
    new_from = CLOCK["dt"]
    new_to = CLOCK["dt"] + timedelta(days=REDEMPTION_PERIOD_DAYS)
    for ref in db["referrals"].values():
        rbill = db["tax_bills"].get(ref["bill_id"])
        if not rbill or rbill["parcel_id"] != parcel_id:
            continue
        if ref["status"] not in ("REFERRED",):  # non-terminal
            continue
        # half-open [from, to) overlap; adjacency at deadline allowed
        if ref["_referral_dt"] < new_to and new_from < ref["_deadline_dt"]:
            err("ERR_REFERRAL_WINDOW_OVERLAP", 409, "Referral window overlaps existing referral")
    if expected != bill["version"]:
        err("ERR_STALE_VERSION", 412, "expected_bill_version does not match")

    ref = new_common()
    ref.update({"bill_id": bill_id,
                "referral_date": render_business(new_from),
                "redemption_deadline": render_business(new_to),
                "_referral_dt": new_from, "_deadline_dt": new_to,
                "delinquent_principal_at_referral_cents": delinquent_principal,
                "status": "REFERRED", "created_by_user_id": uid,
                "sold_by_user_id": None, "sale_price_cents": None})
    db["referrals"][ref["id"]] = ref
    bill["version"] += 1
    bill["updated_at"] = now_iso()
    return ok(ser_referral(ref), 201)


@app.route("/property-tax/tax-sale-referrals/<oid>", methods=["GET"])
def get_referral(oid):
    _, role = authn()
    require_roles(role, set(ALL_ROLES))
    return ok(ser_referral(find("referrals", oid)))


@app.route("/property-tax/tax-sale-referrals", methods=["GET"])
def list_referrals():
    _, role = authn()
    require_roles(role, set(ALL_ROLES))
    items = sort_seq(list(db["referrals"].values()))
    bid = request.args.get("bill_id")
    if bid is not None:
        items = [r for r in items if r["bill_id"] == bid]
    page, pag = paginate(items)
    return ok([ser_referral(r) for r in page], pagination=pag)


@app.route("/property-tax/tax-sale-referrals/<oid>/redeem", methods=["POST"])
def redeem_referral(oid):
    _, role = authn()
    require_roles(role, {"CollectionsOfficer", "Treasurer"})
    ref = find("referrals", oid)
    if ref["status"] != "REFERRED":
        err("ERR_INVALID_STATE", 409, "Referral not in REFERRED state")
    if CLOCK["dt"] >= ref["_deadline_dt"]:
        err("ERR_REDEMPTION_EXPIRED", 409, "Redemption window has expired")
    ref["status"] = "REDEEMED"
    touch(ref)
    return ok(ser_referral(ref))


@app.route("/property-tax/tax-sale-referrals/<oid>/sell", methods=["POST"])
def sell_referral(oid):
    uid, role = authn()
    require_roles(role, {"Treasurer"})
    ref = find("referrals", oid)
    data = body_json()
    sale_price = data.get("sale_price_cents")
    if sale_price is not None and not is_int(sale_price):
        err("ERR_VALIDATION", 400, "sale_price_cents must be an integer")
    # SoD precedes business checks
    if uid == ref["created_by_user_id"]:
        err("ERR_SEGREGATION_OF_DUTIES", 403, "Opener may not execute the sale")
    if ref["status"] != "REFERRED":
        err("ERR_INVALID_STATE", 409, "Referral not in REFERRED state")
    if CLOCK["dt"] < ref["_deadline_dt"]:
        err("ERR_REDEMPTION_NOT_EXPIRED", 409, "Redemption window not yet expired")
    ref["status"] = "SOLD"
    ref["sold_by_user_id"] = uid
    ref["sale_price_cents"] = sale_price
    touch(ref)
    return ok(ser_referral(ref))


# ===========================================================================
# Logical clock
# ===========================================================================
@app.route("/property-tax/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = authn()
    require_roles(role, {"Treasurer", "Cashier", "CollectionsOfficer", "ReliefOfficer"})
    data = body_json()
    to_iso = data.get("to_iso8601")
    if to_iso is None:
        err("ERR_VALIDATION", 400, "Missing required field: to_iso8601")
    try:
        dt = parse_iso(to_iso)
    except Exception:
        err("ERR_VALIDATION", 400, "to_iso8601 must be ISO8601")
    CLOCK["dt"] = dt
    CLOCK["raw"] = to_iso
    for bill in db["tax_bills"].values():
        materialize(bill)
    return ok({"current_utc": render_business(dt)})


# ---------------------------------------------------------------------------
@app.route("/", methods=["GET"])
def health():
    return ok({"status": "ok"})


reset_clock()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
