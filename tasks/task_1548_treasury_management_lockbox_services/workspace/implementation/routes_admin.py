"""Bank lifecycle, logical clock, customers, agreements."""
import re
from datetime import timedelta
from zoneinfo import ZoneInfo

from appobj import api
from store import banks, customers, agreements, sites, batches, incidents, cycles, image_requests
from util import (
    ApiError, ok, body, req_str, opt_int, req_int, opt_bool, new_entity, touch,
    pub, list_response, parse_date, invalid,
)
from helpers import (
    auth, require_role, scope, R_bank, R_customer, R_agreement, check_posture,
    bad_state, run_day_close, finalize_cycle, open_new_cycle, open_cycle,
)

ADMIN = {"BankOperationsAdmin"}
IMPL = {"TreasuryImplementer"}
ACT = {"TreasuryActivator"}

ROUTING_RE = re.compile(r"^\d{9}$")
CUTOFF_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


# ---------------------------------------------------------------------------
# Bank
# ---------------------------------------------------------------------------

@api.post("/banks")
def create_bank():
    uid, role = auth()
    require_role(role, ADMIN)
    b = body()
    legal_name = req_str(b, "legal_name")
    routing = req_str(b, "routing_number")
    if not ROUTING_RE.match(routing):
        invalid("routing_number must be a 9-digit ABA number")
    ecr = req_int(b, "default_earnings_credit_rate_bp", minv=0)
    threshold = opt_int(b, "sla_credit_breach_threshold_bp", minv=0)
    if threshold is None:
        threshold = 200
    for other in banks.values():
        if other["routing_number"] == routing:
            raise ApiError("ERR_DUPLICATE_UNIQUE_FIELD", 409,
                           "routing_number already in use")
    bank = new_entity({
        "legal_name": legal_name,
        "routing_number": routing,
        "current_business_date": "2026-08-01",
        "current_analysis_cycle_index": 0,
        "default_earnings_credit_rate_bp": ecr,
        "sla_credit_breach_threshold_bp": threshold,
        "posture": "OPERATING",
    })
    banks[bank["id"]] = bank
    return ok(pub(bank), "object", 201)


@api.get("/banks/<bankId>")
def get_bank(bankId):
    uid, role = auth()
    bank = R_bank(bankId)
    return ok(pub(bank))


def _bank_sites(bank_id):
    return [s for s in sites.values() if s["bank_id"] == bank_id]


def _bank_batches(bank_id):
    return [b for b in batches.values() if b["bank_id"] == bank_id]


@api.post("/banks/<bankId>/suspend")
def suspend_bank(bankId):
    uid, role = auth()
    require_role(role, ADMIN)
    bank = R_bank(bankId)
    if bank["posture"] != "OPERATING":
        bad_state("bank is not OPERATING")
    bank["posture"] = "SUSPENDED"
    touch(bank)
    for s in _bank_sites(bank["id"]):
        if s["status"] == "LIVE":
            s["status"] = "SUSPENDED"
            s["_ss"].add("bank")
            touch(s)
    for b in _bank_batches(bank["id"]):
        if b["capture_status"] in ("CAPTURING", "BALANCED"):
            b["_held"] = True
            touch(b)
    return ok(pub(bank))


@api.post("/banks/<bankId>/resume")
def resume_bank(bankId):
    uid, role = auth()
    require_role(role, ADMIN)
    bank = R_bank(bankId)
    if bank["posture"] != "SUSPENDED":
        bad_state("bank is not SUSPENDED")
    cur = parse_date(bank["current_business_date"])
    for inc in incidents.values():
        if (inc["bank_id"] == bank["id"] and inc["status"] == "CONFIRMED"
                and (cur - parse_date(inc["occurred_on_business_date"])).days > 30):
            bad_state("unresolved confirmed SLA incidents older than 30 days block resume")
    bank["posture"] = "OPERATING"
    touch(bank)
    for s in _bank_sites(bank["id"]):
        if "bank" in s["_ss"]:
            s["_ss"].discard("bank")
            if not s["_ss"] and s["status"] == "SUSPENDED":
                s["status"] = "LIVE"
            touch(s)
    for b in _bank_batches(bank["id"]):
        if b["_held"]:
            b["_held"] = False
            touch(b)
    return ok(pub(bank))


@api.post("/banks/<bankId>/liquidate")
def liquidate_bank(bankId):
    uid, role = auth()
    require_role(role, ADMIN)
    bank = R_bank(bankId)
    if bank["posture"] != "OPERATING":
        bad_state("bank is not OPERATING")
    for c in customers.values():
        if c["bank_id"] == bank["id"] and c["status"] != "TERMINATED":
            bad_state("all customers must be TERMINATED before liquidation")
    for cyc in cycles.values():
        # Same forced reading as customer termination: an in-flight OPEN cycle
        # always exists, so the SETTLED gate covers finalized work only.
        if (cyc["bank_id"] == bank["id"] and cyc["status"] != "SETTLED"
                and cyc["status"] != "OPEN"):
            bad_state("all analysis cycles must be SETTLED before liquidation")
    bank["posture"] = "LIQUIDATING"
    touch(bank)
    return ok(pub(bank))


@api.post("/banks/<bankId>/close_business_day")
def close_business_day(bankId):
    uid, role = auth()
    require_role(role, ADMIN)
    bank = R_bank(bankId)
    run_day_close(bank)
    return ok(pub(bank))


@api.post("/banks/<bankId>/close_analysis_cycle")
def close_analysis_cycle(bankId):
    uid, role = auth()
    require_role(role, {"BillingSpecialist"})
    bank = R_bank(bankId)
    b = body()
    cid = b.get("customer_id")
    if cid is not None:
        if not isinstance(cid, str):
            invalid("bad customer_id")
        target = customers.get(cid)
        if not target or target["bank_id"] != bank["id"]:
            raise ApiError("ERR_NOT_FOUND", 404, "customer not found")
        targets = [target]
    else:
        targets = [c for c in customers.values() if c["bank_id"] == bank["id"]]
    finalized_any = False
    for c in targets:
        if c["status"] != "ACTIVE":
            continue
        cyc = open_cycle(c["id"])
        if not cyc:
            continue
        if cyc["cycle_end_date"] != bank["current_business_date"]:
            continue
        finalize_cycle(bank, c, cyc, uid)
        finalized_any = True
    if finalized_any:
        bank["current_analysis_cycle_index"] += 1
    touch(bank)
    return ok(pub(bank))


# ---------------------------------------------------------------------------
# Logical clock (test-driving endpoint)
# ---------------------------------------------------------------------------

@api.post("/_clock/set_current_utc")
def set_clock():
    uid, role = auth()
    require_role(role, ADMIN)
    b = body()
    from util import req_dt_field
    import store as S
    S.CLOCK["now"] = req_dt_field(b, "to_iso8601")
    return ok({}, "object", 200)


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------

@api.post("/banks/<bankId>/customers")
def create_customer(bankId):
    uid, role = auth()
    require_role(role, IMPL)
    bank = R_bank(bankId)
    b = body()
    legal_name = req_str(b, "legal_name")
    tax_id = req_str(b, "tax_id")
    dda = req_str(b, "deposit_account_number")
    check_posture(bank)
    for other in customers.values():
        if other["bank_id"] == bank["id"] and other["tax_id"] == tax_id:
            raise ApiError("ERR_DUPLICATE_UNIQUE_FIELD", 409,
                           "tax_id already in use within this bank")
    c = new_entity({
        "bank_id": bank["id"],
        "legal_name": legal_name,
        "tax_id": tax_id,
        "status": "PROSPECT",
        "deposit_account_number": dda,
        "average_collected_balance_cents": 0,
        "collected_balance_accumulator_cents": 0,
        "days_in_cycle_elapsed": 0,
    })
    customers[c["id"]] = c
    return ok(pub(c), "object", 201)


@api.get("/banks/<bankId>/customers/<customerId>")
def get_customer(bankId, customerId):
    uid, role = auth()
    bank = R_bank(bankId)
    c = R_customer(bank, customerId, uid, role)
    return ok(pub(c))


@api.get("/banks/<bankId>/customers")
def list_customers(bankId):
    uid, role = auth()
    bank = R_bank(bankId)
    rows = [c for c in customers.values() if c["bank_id"] == bank["id"]]
    if role == "CustomerOperator":
        rows = [c for c in rows if c["id"] == uid]
    return list_response(rows, ["status"])


@api.post("/banks/<bankId>/customers/<customerId>/begin_onboarding")
def begin_onboarding(bankId, customerId):
    uid, role = auth()
    require_role(role, IMPL)
    bank = R_bank(bankId)
    c = R_customer(bank, customerId)
    check_posture(bank)
    if c["status"] != "PROSPECT":
        bad_state("customer is not PROSPECT")
    c["status"] = "ONBOARDING"
    touch(c)
    return ok(pub(c))


@api.post("/banks/<bankId>/customers/<customerId>/suspend")
def suspend_customer(bankId, customerId):
    uid, role = auth()
    require_role(role, ACT)
    bank = R_bank(bankId)
    c = R_customer(bank, customerId)
    check_posture(bank)
    if c["status"] != "ACTIVE":
        bad_state("customer is not ACTIVE")
    c["status"] = "SUSPENDED"
    touch(c)
    for a in agreements.values():
        if a["customer_id"] == c["id"] and a["status"] == "ACTIVE":
            a["status"] = "SUSPENDED"
            a["_sc"] = True
            touch(a)
    for s in sites.values():
        if s["customer_id"] == c["id"] and s["status"] == "LIVE":
            s["status"] = "SUSPENDED"
            s["_ss"].add("customer")
            touch(s)
    for b in batches.values():
        if (b["customer_id"] == c["id"]
                and b["capture_status"] in ("RECEIVED", "CAPTURING", "BALANCED", "OUT_OF_BALANCE")):
            b["_held"] = True
            touch(b)
    return ok(pub(c))


@api.post("/banks/<bankId>/customers/<customerId>/resume")
def resume_customer(bankId, customerId):
    uid, role = auth()
    require_role(role, ACT)
    bank = R_bank(bankId)
    c = R_customer(bank, customerId)
    check_posture(bank)
    if c["status"] != "SUSPENDED":
        bad_state("customer is not SUSPENDED")
    c["status"] = "ACTIVE"
    touch(c)
    for a in agreements.values():
        if a["customer_id"] == c["id"] and a["status"] == "SUSPENDED" and a.get("_sc"):
            a["status"] = "ACTIVE"
            a["_sc"] = False
            touch(a)
    for s in sites.values():
        if s["customer_id"] == c["id"] and "customer" in s["_ss"]:
            s["_ss"].discard("customer")
            if not s["_ss"] and s["status"] == "SUSPENDED":
                s["status"] = "LIVE"
            touch(s)
    for b in batches.values():
        if b["customer_id"] == c["id"] and b["_held"]:
            b["_held"] = False
            touch(b)
    return ok(pub(c))


@api.post("/banks/<bankId>/customers/<customerId>/terminate")
def terminate_customer(bankId, customerId):
    uid, role = auth()
    require_role(role, ACT)
    bank = R_bank(bankId)
    c = R_customer(bank, customerId)
    check_posture(bank)
    if c["status"] != "ACTIVE":
        bad_state("customer is not ACTIVE")
    for a in agreements.values():
        if a["customer_id"] == c["id"] and a["status"] != "TERMINATED":
            bad_state("all agreements must be TERMINATED before customer termination")
    for cyc in cycles.values():
        # The in-flight OPEN cycle does not block termination: PRD §3.7 notes a
        # cycle can open and close on the same day at termination, and a fresh
        # OPEN cycle always follows a close — requiring it SETTLED would make
        # termination unreachable.
        if (cyc["customer_id"] == c["id"] and cyc["status"] != "SETTLED"
                and cyc["status"] != "OPEN"):
            raise ApiError("ERR_CUSTOMER_NOT_SETTLED", 409,
                           "customer has non-SETTLED analysis cycles")
    for r in image_requests.values():
        if r["customer_id"] == c["id"] and r["status"] == "REQUESTED":
            raise ApiError("ERR_CUSTOMER_NOT_SETTLED", 409,
                           "customer has open image retrieval requests")
    c["status"] = "TERMINATED"
    touch(c)
    return ok(pub(c))


# ---------------------------------------------------------------------------
# Service agreements
# ---------------------------------------------------------------------------

@api.post("/banks/<bankId>/customers/<customerId>/agreements")
def create_agreement(bankId, customerId):
    uid, role = auth()
    require_role(role, IMPL)
    bank = R_bank(bankId)
    c = R_customer(bank, customerId)
    b = body()
    number = req_str(b, "agreement_number")
    ecr_override = opt_int(b, "earnings_credit_rate_bp", minv=0)
    override_allowed = opt_bool(b, "ecr_override_allowed", default=False)
    maint = req_int(b, "monthly_maintenance_fee_cents", minv=0)
    per_item = req_int(b, "per_item_capture_fee_cents", minv=0)
    per_exc = req_int(b, "per_exception_decision_fee_cents", minv=0)
    per_img = req_int(b, "per_image_retrieval_fee_cents", minv=0)
    check_posture(bank)
    for other in agreements.values():
        if other["bank_id"] == bank["id"] and other["agreement_number"] == number:
            raise ApiError("ERR_DUPLICATE_UNIQUE_FIELD", 409,
                           "agreement_number already in use within this bank")
    a = new_entity({
        "customer_id": c["id"],
        "bank_id": bank["id"],
        "agreement_number": number,
        "earnings_credit_rate_bp": ecr_override,
        "ecr_override_allowed": override_allowed,
        "monthly_maintenance_fee_cents": maint,
        "per_item_capture_fee_cents": per_item,
        "per_exception_decision_fee_cents": per_exc,
        "per_image_retrieval_fee_cents": per_img,
        "implemented_by_user_id": None,
        "activated_by_user_id": None,
        "status": "DRAFT",
        "_sc": False,
    })
    agreements[a["id"]] = a
    return ok(pub(a), "object", 201)


@api.get("/banks/<bankId>/customers/<customerId>/agreements/<agreementId>")
def get_agreement(bankId, customerId, agreementId):
    uid, role = auth()
    bank = R_bank(bankId)
    c = R_customer(bank, customerId, uid, role)
    a = R_agreement(c, agreementId)
    return ok(pub(a))


@api.get("/banks/<bankId>/customers/<customerId>/agreements")
def list_agreements(bankId, customerId):
    uid, role = auth()
    bank = R_bank(bankId)
    c = R_customer(bank, customerId, uid, role)
    rows = [a for a in agreements.values() if a["customer_id"] == c["id"]]
    return list_response(rows, ["status"])


@api.post("/banks/<bankId>/customers/<customerId>/agreements/<agreementId>/implement")
def implement_agreement(bankId, customerId, agreementId):
    uid, role = auth()
    require_role(role, IMPL)
    bank = R_bank(bankId)
    c = R_customer(bank, customerId)
    a = R_agreement(c, agreementId)
    check_posture(bank)
    if a["status"] != "DRAFT":
        bad_state("agreement is not DRAFT")
    if c["status"] not in ("ONBOARDING", "ACTIVE"):
        raise ApiError("ERR_CUSTOMER_NOT_ACTIVE", 409,
                       "customer must be ONBOARDING or ACTIVE to implement")
    a["implemented_by_user_id"] = uid
    a["status"] = "IMPLEMENTED"
    touch(a)
    return ok(pub(a))


@api.post("/banks/<bankId>/customers/<customerId>/agreements/<agreementId>/activate")
def activate_agreement(bankId, customerId, agreementId):
    uid, role = auth()
    require_role(role, ACT)
    bank = R_bank(bankId)
    c = R_customer(bank, customerId)
    a = R_agreement(c, agreementId)
    check_posture(bank)
    if a["status"] != "IMPLEMENTED":
        bad_state("agreement is not IMPLEMENTED")
    if a["implemented_by_user_id"] == uid:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 409,
                       "activator must differ from implementer")
    b = body()
    expected = req_int(b, "expected_agreement_version")
    if expected != a["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_agreement_version does not match current version")
    if c["status"] not in ("ONBOARDING", "ACTIVE"):
        raise ApiError("ERR_CUSTOMER_NOT_ACTIVE", 409,
                       "customer must be ONBOARDING or ACTIVE to activate")
    a["activated_by_user_id"] = uid
    a["status"] = "ACTIVE"
    touch(a)
    if c["status"] == "ONBOARDING":
        c["status"] = "ACTIVE"
        touch(c)
        # PRD §3.7: "the cycle's agreement_id references the ACTIVE agreement
        # at close" — the reference is established at close, not at open.
        open_new_cycle(bank, c, 1, parse_date(bank["current_business_date"]), None)
    return ok(pub(a))


@api.post("/banks/<bankId>/customers/<customerId>/agreements/<agreementId>/suspend")
def suspend_agreement(bankId, customerId, agreementId):
    uid, role = auth()
    require_role(role, ACT)
    bank = R_bank(bankId)
    c = R_customer(bank, customerId)
    a = R_agreement(c, agreementId)
    check_posture(bank)
    if a["status"] != "ACTIVE":
        bad_state("agreement is not ACTIVE")
    a["status"] = "SUSPENDED"
    touch(a)
    for s in sites.values():
        if s["agreement_id"] == a["id"] and s["status"] == "LIVE":
            s["status"] = "SUSPENDED"
            s["_ss"].add("agreement")
            touch(s)
    return ok(pub(a))


@api.post("/banks/<bankId>/customers/<customerId>/agreements/<agreementId>/resume")
def resume_agreement(bankId, customerId, agreementId):
    uid, role = auth()
    require_role(role, ACT)
    bank = R_bank(bankId)
    c = R_customer(bank, customerId)
    a = R_agreement(c, agreementId)
    check_posture(bank)
    if a["status"] != "SUSPENDED":
        bad_state("agreement is not SUSPENDED")
    if c["status"] != "ACTIVE":
        raise ApiError("ERR_CUSTOMER_NOT_ACTIVE", 409,
                       "customer must be ACTIVE to resume an agreement")
    a["status"] = "ACTIVE"
    touch(a)
    for s in sites.values():
        if s["agreement_id"] == a["id"] and "agreement" in s["_ss"]:
            s["_ss"].discard("agreement")
            if not s["_ss"] and s["status"] == "SUSPENDED":
                s["status"] = "LIVE"
            touch(s)
    return ok(pub(a))


@api.post("/banks/<bankId>/customers/<customerId>/agreements/<agreementId>/terminate")
def terminate_agreement(bankId, customerId, agreementId):
    uid, role = auth()
    require_role(role, ACT)
    bank = R_bank(bankId)
    c = R_customer(bank, customerId)
    a = R_agreement(c, agreementId)
    check_posture(bank)
    if a["status"] not in ("ACTIVE", "SUSPENDED"):
        bad_state("agreement is not ACTIVE or SUSPENDED")
    for s in sites.values():
        if s["agreement_id"] == a["id"] and s["status"] != "DECOMMISSIONED":
            bad_state("all sites must be DECOMMISSIONED before agreement termination")
    for cyc in cycles.values():
        if cyc.get("agreement_id") == a["id"] and cyc["status"] != "SETTLED":
            raise ApiError("ERR_CUSTOMER_NOT_SETTLED", 409,
                           "analysis cycles referencing this agreement must be SETTLED")
    a["status"] = "TERMINATED"
    touch(a)
    return ok(pub(a))
