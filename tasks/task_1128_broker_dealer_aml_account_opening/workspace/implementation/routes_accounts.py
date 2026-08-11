"""Routes: brokerage accounts (lifecycle + risk recalc), EDD reviews,
transactions, monitoring rules, monitoring scans."""

from datetime import date, timedelta
from decimal import Decimal

from flask import Blueprint, g, request

from db import store, new_record, bump, serialize, today
from errors import ApiError
from services import (
    apply_risk, compute_risk, recompute_aggregates, recompute_counts,
    recompute_posture, restrict_cascade, run_scan, to_dec, round2, add_months,
    matches_of_account, cases_of_account, TIER_LIMITS,
)
from util import (
    endpoint, ok_object, list_response, field, MISSING, require_fields,
    check_enum, get_or_404, parse_date, is_num, is_int, is_bool, ALL_ROLES,
)
from routes_core import _current_rep_active

bp = Blueprint("accounts", __name__)

PRODUCTS = {"CASH", "LOW_PRICED_SECURITIES", "MARGIN", "OPTIONS", "CORRESPONDENT"}
LIFECYCLES = {"PENDING_APPROVAL", "OPEN", "RESTRICTED", "CLOSED", "DECLINED"}
POSTURES = {"STANDARD", "ELEVATED", "SEVERE"}
RISK_TIERS = {"LOW", "MEDIUM", "HIGH", "PROHIBITED"}
TXN_TYPES = {"DEPOSIT_CERT", "DEPOSIT_DTC", "BUY", "SELL", "WIRE_OUT", "JOURNAL"}
SECURITY_TYPES = {"DEPOSIT_CERT", "DEPOSIT_DTC", "BUY", "SELL"}
TXN_STATUSES = {"POSTED", "FLAGGED", "CLEARED", "ESCALATED", "REVERSED"}
REVIEW_STATUSES = {"PENDING", "IN_REVIEW", "APPROVED", "REJECTED", "REFRESH_DUE"}
RULE_CODES = {"LPS_LIQUIDATION", "LPS_DEPOSIT_LIQUIDATE", "WIRE_VELOCITY", "STRUCTURING"}

EDD_INTERVAL_MONTHS = {"HIGH": 12, "MEDIUM": 24, "LOW": 36}


def _get_account(aid):
    return get_or_404("accounts", aid, "ERR_ACCOUNT_NOT_FOUND")


def _check_account_mutable_for_posting(account):
    """Lifecycle gate for transaction posting / certificate intake (priority 6)."""
    s = account["lifecycle_status"]
    if s == "RESTRICTED":
        raise ApiError("ERR_ACCOUNT_RESTRICTED", 409, "Account is RESTRICTED")
    if s in ("CLOSED", "DECLINED"):
        raise ApiError("ERR_ACCOUNT_CLOSED_TERMINAL", 409, "Account is CLOSED or DECLINED (terminal)")
    if s != "OPEN":
        raise ApiError("ERR_ACCOUNT_NOT_OPEN", 409, "Account is not OPEN")


def _check_posture_not_severe(account):
    if account["aml_posture"] == "SEVERE":
        raise ApiError("ERR_POSTURE_SEVERE_BLOCKS", 403,
                       "SEVERE AML posture blocks transaction posting and certificate intake")


def _lifecycle_action_gate(account, allowed_from):
    s = account["lifecycle_status"]
    if s in ("CLOSED", "DECLINED"):
        raise ApiError("ERR_ACCOUNT_CLOSED_TERMINAL", 409, "Account is in a terminal state")
    if s not in allowed_from:
        raise ApiError("ERR_INVALID_LIFECYCLE_TRANSITION", 409,
                       "Transition not valid from %s" % s)


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

@bp.post("/aml/accounts")
@endpoint(["RegisteredRep"])
def create_account():
    _current_rep_active()
    cust_id = field("customer_id")
    customer = None
    if isinstance(cust_id, str):
        customer = store.customers.get(cust_id)
        if customer is None:
            raise ApiError("ERR_CUSTOMER_NOT_FOUND", 404, "Customer %s does not exist" % cust_id)
    pset = field("product_set")
    if isinstance(pset, list):
        for p in pset:
            if not isinstance(p, str) or p not in PRODUCTS:
                raise ApiError("ERR_INVALID_ENUM", 400,
                               "product_set entries must be one of %s" % sorted(PRODUCTS))
    require_fields([("customer_id", "nstr", True), ("product_set", "list", True)])
    rec = new_record()
    rec.update({
        "customer_id": customer["id"],
        "product_set": list(pset),
        "lifecycle_status": "PENDING_APPROVAL",
        "aml_posture": "STANDARD",
        "risk_score": 0,
        "risk_tier": "LOW",
        "risk_variant_used": "INITIAL",
        "exposure_30d_amount": Decimal("0"),
        "exposure_tier": "T1",
        "wire_velocity_30d_amount": Decimal("0"),
        "open_alert_count": 0,
        "open_case_count": 0,
        "has_suspicion_flag": False,
        "decline_reason": None,
    })
    store.accounts[rec["id"]] = rec
    score, tier = compute_risk(rec, "INITIAL")
    rec["risk_score"] = score
    rec["risk_tier"] = tier
    return ok_object(serialize(rec), 201)


@bp.get("/aml/accounts")
@endpoint(ALL_ROLES)
def list_accounts():
    return list_response(
        list(store.accounts.values()),
        {
            "customer_id": request.args.get("customer_id"),
            "lifecycle_status": request.args.get("lifecycle_status"),
            "risk_tier": request.args.get("risk_tier"),
            "aml_posture": request.args.get("aml_posture"),
        },
        enum_filters=[("lifecycle_status", LIFECYCLES), ("risk_tier", RISK_TIERS),
                      ("aml_posture", POSTURES)],
    )


@bp.get("/aml/accounts/<aid>")
@endpoint(ALL_ROLES)
def get_account(aid):
    return ok_object(serialize(_get_account(aid)))


@bp.post("/aml/accounts/<aid>/approve")
@endpoint(["ComplianceOfficer"])
def approve_account(aid):
    account = _get_account(aid)
    _lifecycle_action_gate(account, {"PENDING_APPROVAL"})
    customer = store.customers[account["customer_id"]]
    # Gate 1: CIP completeness
    docs = [d for d in store.documents.values()
            if d["customer_id"] == customer["id"] and d["status"] == "VERIFIED"]
    if customer["customer_type"] == "INDIVIDUAL":
        cip_ok = any(d["doc_type"] == "GOVERNMENT_ID" for d in docs)
    else:
        cip_ok = any(d["doc_type"] == "FORMATION_DOC" for d in docs) \
            and any(d["doc_type"] == "PROOF_OF_ADDRESS" for d in docs)
    if not cip_ok:
        raise ApiError("ERR_CIP_INCOMPLETE", 409, "Required VERIFIED identification documents are missing")
    # Gate 2: beneficial ownership for legal entities
    if customer["customer_type"] == "LEGAL_ENTITY":
        if not any(c["customer_id"] == customer["id"] and c["status"] == "CERTIFIED"
                   for c in store.certifications.values()):
            raise ApiError("ERR_BENEFICIAL_OWNERSHIP_REQUIRED", 422,
                           "LEGAL_ENTITY approval requires a CERTIFIED beneficial ownership certification")
    # Gate 3: prohibited tier
    if account["risk_tier"] == "PROHIBITED":
        raise ApiError("ERR_PROHIBITED_TIER", 403, "PROHIBITED-tier accounts can never be approved")
    # Gate 4: HIGH tier requires APPROVED EDD review
    if account["risk_tier"] == "HIGH":
        if not any(r["account_id"] == account["id"] and r["status"] == "APPROVED"
                   for r in store.edd_reviews.values()):
            raise ApiError("ERR_EDD_APPROVAL_REQUIRED", 409,
                           "HIGH-tier approval requires an APPROVED EDD review")
    account["lifecycle_status"] = "OPEN"
    apply_risk(account, "INITIAL")  # approval re-stamps the INITIAL variant
    bump(account)
    return ok_object(serialize(account))


@bp.post("/aml/accounts/<aid>/decline")
@endpoint(["ComplianceOfficer"])
def decline_account(aid):
    account = _get_account(aid)
    _lifecycle_action_gate(account, {"PENDING_APPROVAL"})
    require_fields([("reason", "nstr", True)])
    account["lifecycle_status"] = "DECLINED"
    account["decline_reason"] = field("reason")
    bump(account)
    return ok_object(serialize(account))


@bp.post("/aml/accounts/<aid>/restrict")
@endpoint(["ComplianceOfficer"])
def restrict_account_endpoint(aid):
    account = _get_account(aid)
    _lifecycle_action_gate(account, {"OPEN"})
    account["lifecycle_status"] = "RESTRICTED"
    restrict_cascade(account, "ACCOUNT_RESTRICTED")
    bump(account)
    return ok_object(serialize(account))


@bp.post("/aml/accounts/<aid>/reinstate")
@endpoint(["ComplianceOfficer"])
def reinstate_account(aid):
    account = _get_account(aid)
    _lifecycle_action_gate(account, {"RESTRICTED"})
    if any(m["status"] == "CONFIRMED" for m in matches_of_account(aid)):
        raise ApiError("ERR_MATCH_314A_UNRESOLVED", 409,
                       "Reinstate blocked: a CONFIRMED 314(a) match is unresolved")
    if any(c["priority"] == "CRITICAL" and c["status"] in
           ("OPEN", "INVESTIGATING", "SAR_RECOMMENDED", "REOPENED")
           for c in cases_of_account(aid)):
        raise ApiError("ERR_CRITICAL_CASE_OPEN", 409,
                       "Reinstate blocked: an open CRITICAL case exists")
    account["lifecycle_status"] = "OPEN"
    recompute_posture(account)
    bump(account)
    return ok_object(serialize(account))


@bp.post("/aml/accounts/<aid>/close")
@endpoint(["ComplianceOfficer"])
def close_account(aid):
    account = _get_account(aid)
    _lifecycle_action_gate(account, {"OPEN", "RESTRICTED"})
    if any(c["status"] in ("OPEN", "INVESTIGATING", "SAR_RECOMMENDED", "REOPENED",
                           "DECIDED_FILED", "DECIDED_NO_FILE")
           for c in cases_of_account(aid)):
        raise ApiError("ERR_ACCOUNT_CLOSE_BLOCKED", 409, "Close blocked by an open case")
    if any(m["status"] in ("PENDING_REVIEW", "CONFIRMED")
           for m in matches_of_account(aid)):
        raise ApiError("ERR_ACCOUNT_CLOSE_BLOCKED", 409, "Close blocked by an unresolved 314(a) match")
    if any(d["status"] not in ("ACCEPTED", "REJECTED", "REJECTED_SUSPICIOUS")
           for d in store.deposits.values() if d["account_id"] == aid):
        raise ApiError("ERR_ACCOUNT_CLOSE_BLOCKED", 409, "Close blocked by a non-terminal certificate deposit")
    if any(t["status"] in ("FLAGGED", "ESCALATED")
           for t in store.transactions.values() if t["account_id"] == aid):
        raise ApiError("ERR_ACCOUNT_CLOSE_BLOCKED", 409, "Close blocked by flagged or escalated transactions")
    account["lifecycle_status"] = "CLOSED"
    bump(account)
    return ok_object(serialize(account))


@bp.post("/aml/accounts/<aid>/risk-recalculations")
@endpoint(["AMLAnalyst", "ComplianceOfficer"])
def risk_recalculation(aid):
    account = _get_account(aid)
    ev = field("expected_account_version")
    if is_int(ev) and ev != account["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_account_version does not match the account's current version")
    require_fields([("expected_account_version", "int", True)])
    apply_risk(account, "ONGOING")
    recompute_aggregates(account)
    recompute_counts(account)
    bump(account)
    return ok_object(serialize(account))


# ---------------------------------------------------------------------------
# EDD reviews
# ---------------------------------------------------------------------------

@bp.post("/aml/accounts/<accountId>/edd-reviews")
@endpoint(["AMLAnalyst"])
def create_edd_review(accountId):
    account = _get_account(accountId)
    ps_raw, pe_raw = field("period_start"), field("period_end")
    ps, pe = parse_date(ps_raw), parse_date(pe_raw)
    prior = field("prior_review_id")
    # Temporal overlap (priority 12) — half-open [start, end) per account
    if ps is not None and pe is not None:
        for r in store.edd_reviews.values():
            if r["account_id"] != account["id"] or r["status"] == "REJECTED":
                continue
            rs, re_ = date.fromisoformat(r["period_start"]), date.fromisoformat(r["period_end"])
            if ps < re_ and pe > rs:
                raise ApiError("ERR_OVERLAPPING_EDD_REVIEW", 409,
                               "Review period overlaps an existing non-REJECTED review")
    # Date sanity (priority 14)
    if (ps_raw is not MISSING and ps is None) or (pe_raw is not MISSING and pe is None):
        raise ApiError("ERR_INVALID_DATE_RANGE", 400, "Dates must be well-formed YYYY-MM-DD")
    if ps is not None and pe is not None and pe <= ps:
        raise ApiError("ERR_INVALID_DATE_RANGE", 400, "period_end must be later than period_start")
    # Cross-reference (priority 15): prior review must exist
    if prior is not MISSING and prior is not None:
        get_or_404("edd_reviews", prior, "ERR_EDD_REVIEW_NOT_FOUND")
    require_fields([
        ("period_start", "date", True),
        ("period_end", "date", True),
        ("trigger_reason", "nstr", True),
    ])
    rec = new_record()
    rec.update({
        "account_id": account["id"],
        "period_start": ps_raw,
        "period_end": pe_raw,
        "trigger_reason": field("trigger_reason"),
        "prior_review_id": prior if (prior is not MISSING) else None,
        "status": "PENDING",
        "refresh_due_date": None,
        "tier_at_completion": None,
        "decision_notes": None,
    })
    store.edd_reviews[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.get("/aml/edd-reviews")
@endpoint(ALL_ROLES)
def list_edd_reviews():
    return list_response(
        list(store.edd_reviews.values()),
        {
            "account_id": request.args.get("account_id"),
            "status": request.args.get("status"),
            "prior_review_id": request.args.get("prior_review_id"),
        },
        enum_filters=[("status", REVIEW_STATUSES)],
    )


@bp.get("/aml/edd-reviews/<rid>")
@endpoint(ALL_ROLES)
def get_edd_review(rid):
    return ok_object(serialize(get_or_404("edd_reviews", rid, "ERR_EDD_REVIEW_NOT_FOUND")))


@bp.post("/aml/edd-reviews/<rid>/begin")
@endpoint(["AMLAnalyst"])
def begin_edd_review(rid):
    review = get_or_404("edd_reviews", rid, "ERR_EDD_REVIEW_NOT_FOUND")
    if review["status"] not in ("PENDING", "REFRESH_DUE"):
        raise ApiError("ERR_EDD_REVIEW_NOT_ACTIONABLE", 409,
                       "Review must be PENDING or REFRESH_DUE to begin")
    review["status"] = "IN_REVIEW"
    bump(review)
    return ok_object(serialize(review))


@bp.post("/aml/edd-reviews/<rid>/complete")
@endpoint(["ComplianceOfficer"])
def complete_edd_review(rid):
    review = get_or_404("edd_reviews", rid, "ERR_EDD_REVIEW_NOT_FOUND")
    if review["status"] != "IN_REVIEW":
        raise ApiError("ERR_EDD_REVIEW_NOT_ACTIONABLE", 409,
                       "Review must be IN_REVIEW to complete")
    decision = check_enum("decision", {"APPROVED", "REJECTED"})
    require_fields([("decision", "str", True), ("notes", "str", False)])
    notes = field("notes")
    if notes is not MISSING:
        review["decision_notes"] = notes
    account = store.accounts[review["account_id"]]
    if decision == "APPROVED":
        tier = account["risk_tier"]
        interval = EDD_INTERVAL_MONTHS.get(tier, EDD_INTERVAL_MONTHS["HIGH"])
        review["status"] = "APPROVED"
        review["tier_at_completion"] = tier if tier in EDD_INTERVAL_MONTHS else "HIGH"
        review["refresh_due_date"] = add_months(today(), interval).isoformat()
        bump(review)
        recompute_posture(account)
    else:
        review["status"] = "REJECTED"
        bump(review)
        if account["lifecycle_status"] == "PENDING_APPROVAL":
            account["lifecycle_status"] = "DECLINED"
            account["decline_reason"] = notes if notes is not MISSING else "EDD rejection"
            bump(account)
        elif account["lifecycle_status"] == "OPEN":
            account["lifecycle_status"] = "RESTRICTED"
            restrict_cascade(account, "EDD_REJECTION")
            bump(account)
    return ok_object(serialize(review))


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------

@bp.post("/aml/accounts/<accountId>/transactions")
@endpoint(["RegisteredRep", "OperationsAnalyst"])
def post_transaction(accountId):
    account = _get_account(accountId)
    _check_account_mutable_for_posting(account)
    _check_posture_not_severe(account)
    txn_type = check_enum("txn_type", TXN_TYPES)
    amount = field("amount")
    quantity = field("quantity")
    unit_price = field("unit_price")
    # Wire velocity (priority 17): projected strictly greater than limit rejects
    if txn_type == "WIRE_OUT" and is_num(amount):
        recompute_aggregates(account)
        limit = TIER_LIMITS.get(account["risk_tier"], TIER_LIMITS["HIGH"])
        projected = account["wire_velocity_30d_amount"] + round2(to_dec(amount))
        if projected > limit:
            raise ApiError("ERR_VELOCITY_LIMIT_EXCEEDED", 422,
                           "Projected 30-day wire total exceeds the tier limit")
    # Body shape (priority 21)
    spec = [("txn_type", "str", True), ("security_id", "str", False)]
    if txn_type in SECURITY_TYPES:
        spec += [("quantity", "num", True), ("unit_price", "num", True)]
    else:
        spec += [("amount", "num", True)]
    require_fields(spec)
    rec = new_record()
    if txn_type in SECURITY_TYPES:
        amt = round2(to_dec(quantity) * to_dec(unit_price))
        low = to_dec(unit_price) < Decimal("5.00")
        rec.update({"security_id": field("security_id") if field("security_id") is not MISSING else None,
                    "quantity": to_dec(quantity), "unit_price": to_dec(unit_price),
                    "amount": amt, "is_low_priced": low})
    else:
        rec.update({"security_id": field("security_id") if field("security_id") is not MISSING else None,
                    "quantity": None, "unit_price": None,
                    "amount": round2(to_dec(amount)), "is_low_priced": False})
    status = "FLAGGED" if account["aml_posture"] == "ELEVATED" else "POSTED"
    rec.update({
        "account_id": account["id"],
        "txn_type": txn_type,
        "status": status,
        "reversal_reason": None,
    })
    store.transactions[rec["id"]] = rec
    recompute_aggregates(account)
    bump(account)
    return ok_object(serialize(rec), 201)


@bp.get("/aml/transactions")
@endpoint(ALL_ROLES)
def list_transactions():
    return list_response(
        list(store.transactions.values()),
        {
            "account_id": request.args.get("account_id"),
            "status": request.args.get("status"),
            "txn_type": request.args.get("txn_type"),
        },
        enum_filters=[("status", TXN_STATUSES), ("txn_type", TXN_TYPES)],
    )


@bp.get("/aml/transactions/<tid>")
@endpoint(ALL_ROLES)
def get_transaction(tid):
    return ok_object(serialize(get_or_404("transactions", tid, "ERR_TRANSACTION_NOT_FOUND")))


def _reverse_transaction(txn, reason):
    """Compensating action: REVERSED + aggregates recomputed excluding it."""
    txn["status"] = "REVERSED"
    txn["reversal_reason"] = reason
    bump(txn)
    account = store.accounts[txn["account_id"]]
    recompute_aggregates(account)
    bump(account)


@bp.post("/aml/transactions/<tid>/reverse")
@endpoint(["OperationsAnalyst"])
def reverse_transaction(tid):
    txn = get_or_404("transactions", tid, "ERR_TRANSACTION_NOT_FOUND")
    if txn["status"] not in ("POSTED", "FLAGGED"):
        raise ApiError("ERR_TRANSACTION_NOT_REVERSIBLE", 409,
                       "Transaction must be POSTED or FLAGGED to reverse")
    require_fields([("reason", "nstr", True)])
    _reverse_transaction(txn, field("reason"))
    return ok_object(serialize(txn))


@bp.post("/aml/transactions/<tid>/clear")
@endpoint(["AMLAnalyst"])
def clear_transaction(tid):
    txn = get_or_404("transactions", tid, "ERR_TRANSACTION_NOT_FOUND")
    if txn["status"] != "FLAGGED":
        raise ApiError("ERR_TRANSACTION_NOT_CLEARABLE", 409,
                       "Transaction must be FLAGGED to clear")
    txn["status"] = "CLEARED"
    bump(txn)
    return ok_object(serialize(txn))


# ---------------------------------------------------------------------------
# Monitoring rules & scans
# ---------------------------------------------------------------------------

@bp.post("/aml/monitoring-rules")
@endpoint(["SystemAdmin"])
def create_rule():
    code = check_enum("rule_code", RULE_CODES)
    require_fields([
        ("rule_code", "str", True),
        ("threshold_amount", "num", True),
        ("window_days", "int", True),
        ("min_transaction_count", "int", False),
        ("enabled", "bool", False),
    ])
    mtc = field("min_transaction_count")
    en = field("enabled")
    rec = new_record()
    rec.update({
        "rule_code": code,
        "threshold_amount": to_dec(field("threshold_amount")),
        "window_days": field("window_days"),
        "min_transaction_count": mtc if mtc is not MISSING else 1,
        "enabled": en if en is not MISSING else True,
    })
    store.rules[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.get("/aml/monitoring-rules")
@endpoint(ALL_ROLES)
def list_rules():
    from util import parse_bool_param
    return list_response(
        list(store.rules.values()),
        {"rule_code": request.args.get("rule_code"),
         "enabled": parse_bool_param("enabled")},
        enum_filters=[("rule_code", RULE_CODES)],
    )


@bp.get("/aml/monitoring-rules/<rid>")
@endpoint(ALL_ROLES)
def get_rule(rid):
    return ok_object(serialize(get_or_404("rules", rid, "ERR_RULE_NOT_FOUND")))


@bp.patch("/aml/monitoring-rules/<rid>")
@endpoint(["SystemAdmin"])
def update_rule(rid):
    rule = get_or_404("rules", rid, "ERR_RULE_NOT_FOUND")
    require_fields([
        ("enabled", "bool", False),
        ("threshold_amount", "num", False),
        ("window_days", "int", False),
        ("min_transaction_count", "int", False),
    ])
    en = field("enabled")
    if en is not MISSING:
        rule["enabled"] = en
    ta = field("threshold_amount")
    if ta is not MISSING:
        rule["threshold_amount"] = to_dec(ta)
    wd = field("window_days")
    if wd is not MISSING:
        rule["window_days"] = wd
    mtc = field("min_transaction_count")
    if mtc is not MISSING:
        rule["min_transaction_count"] = mtc
    bump(rule)
    return ok_object(serialize(rule))


@bp.post("/aml/monitoring-scans/run")
@endpoint(["AMLAnalyst"])
def run_monitoring_scan():
    rid = field("rule_id")
    if isinstance(rid, str):
        rule = store.rules.get(rid)
        if rule is None:
            raise ApiError("ERR_RULE_NOT_FOUND", 404, "Monitoring rule %s does not exist" % rid)
        if not rule.get("enabled"):
            raise ApiError("ERR_RULE_DISABLED", 409, "Monitoring rule is disabled")
    alerts_created, transactions_flagged = run_scan()
    return ok_object({"alerts_created": alerts_created,
                      "transactions_flagged": transactions_flagged})
