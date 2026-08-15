"""Core shared services: entity factories, serialization, pagination, lookups,
and the cross-entity business operations (KYC cascades, sweeps, aggregate
recompute, series minting, effective-fee recomputation)."""
from datetime import timedelta
from decimal import Decimal

from db import db, next_seq
from errors import raise_error, ERR_NOT_FOUND
from util import (
    CLOCK, new_id, now_ts, parse_datetime, fmt_datetime, add_calendar_months,
    dec, quantize_half_up, round_half_up_int,
)

# ---------------------------------------------------------------------------
# Serialization / common fields
# ---------------------------------------------------------------------------


def serialize(rec):
    """Public view: drop internal `_`-prefixed bookkeeping fields."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def stamp_new(rec):
    ts = now_ts()
    rec["id"] = new_id()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = next_seq()
    return rec


def touch(rec):
    """Every mutation refreshes updated_at and bumps version (PRD 2.5)."""
    rec["updated_at"] = now_ts()
    rec["version"] += 1
    return rec


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3): limit/offset query params, created_at ascending.
# ---------------------------------------------------------------------------


def paginate(items):
    from flask import request
    from errors import raise_error as _raise, ERR_INVALID_REQUEST

    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        _raise(ERR_INVALID_REQUEST, "limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        _raise(ERR_INVALID_REQUEST, "offset must be an integer")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    ordered = sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return [serialize(r) for r in page], total, limit, offset


def filter_by(items, **criteria):
    out = []
    for rec in items:
        ok = True
        for key, val in criteria.items():
            if val is None:
                continue
            if rec.get(key) != val:
                ok = False
                break
        if ok:
            out.append(rec)
    return out


# ---------------------------------------------------------------------------
# Lookups (ERR_NOT_FOUND) and hierarchical ownership (PRD 2.6)
# ---------------------------------------------------------------------------


def get_fund(fund_id):
    rec = db["funds"].get(fund_id)
    if rec is None:
        raise_error(ERR_NOT_FOUND, f"fund not found: {fund_id}")
    return rec


def get_share_class(class_id):
    rec = db["share_classes"].get(class_id)
    if rec is None:
        raise_error(ERR_NOT_FOUND, f"share class not found: {class_id}")
    return rec


def get_nav_period(period_id):
    rec = db["nav_periods"].get(period_id)
    if rec is None:
        raise_error(ERR_NOT_FOUND, f"nav period not found: {period_id}")
    return rec


def get_series(series_id):
    rec = db["series"].get(series_id)
    if rec is None:
        raise_error(ERR_NOT_FOUND, f"series not found: {series_id}")
    return rec


def get_investor(investor_id):
    rec = db["investors"].get(investor_id)
    if rec is None:
        raise_error(ERR_NOT_FOUND, f"investor not found: {investor_id}")
    return rec


def get_kyc_case(case_id):
    rec = db["kyc_cases"].get(case_id)
    if rec is None:
        raise_error(ERR_NOT_FOUND, f"kyc case not found: {case_id}")
    return rec


def get_attestation(att_id):
    rec = db["accreditations"].get(att_id)
    if rec is None:
        raise_error(ERR_NOT_FOUND, f"accreditation attestation not found: {att_id}")
    return rec


def get_subscription(sub_id):
    rec = db["subscriptions"].get(sub_id)
    if rec is None:
        raise_error(ERR_NOT_FOUND, f"subscription not found: {sub_id}")
    return rec


def get_side_letter(letter_id):
    rec = db["side_letters"].get(letter_id)
    if rec is None:
        raise_error(ERR_NOT_FOUND, f"side letter not found: {letter_id}")
    return rec


def get_mfn_clause(clause_id):
    rec = db["mfn_clauses"].get(clause_id)
    if rec is None:
        raise_error(ERR_NOT_FOUND, f"mfn clause not found: {clause_id}")
    return rec


def get_capital_account(account_id):
    rec = db["capital_accounts"].get(account_id)
    if rec is None:
        raise_error(ERR_NOT_FOUND, f"capital account not found: {account_id}")
    return rec


def get_series_lot(lot_id):
    rec = db["series_lots"].get(lot_id)
    if rec is None:
        raise_error(ERR_NOT_FOUND, f"series lot not found: {lot_id}")
    return rec


def get_redemption(red_id):
    rec = db["redemptions"].get(red_id)
    if rec is None:
        raise_error(ERR_NOT_FOUND, f"redemption request not found: {red_id}")
    return rec


def get_statement(stmt_id):
    rec = db["statements"].get(stmt_id)
    if rec is None:
        raise_error(ERR_NOT_FOUND, f"statement not found: {stmt_id}")
    return rec


def child_of(child, parent_key, parent_id):
    """Hierarchical containment: child must belong to the path parent (404)."""
    if child.get(parent_key) != parent_id:
        raise_error(ERR_NOT_FOUND, "child resource not found under parent")


# ---------------------------------------------------------------------------
# KYC required documents (derived from investor_type x risk_rating)
# ---------------------------------------------------------------------------

_BASE_DOCS = {
    "INDIVIDUAL": ["GOVERNMENT_ID", "PROOF_OF_ADDRESS"],
    "JOINT": ["GOVERNMENT_ID", "PROOF_OF_ADDRESS"],
    "CORPORATION": ["FORMATION_DOCUMENT", "TAX_FORM", "BENEFICIAL_OWNERSHIP"],
    "TRUST": ["TRUST_DEED", "TAX_FORM", "BENEFICIAL_OWNERSHIP"],
    "PARTNERSHIP": ["FORMATION_DOCUMENT", "TAX_FORM", "BENEFICIAL_OWNERSHIP"],
    "LLC": ["FORMATION_DOCUMENT", "TAX_FORM", "BENEFICIAL_OWNERSHIP"],
    "EMPLOYEE_BENEFIT_PLAN": ["PLAN_DOCUMENT", "TAX_FORM", "BENEFICIAL_OWNERSHIP"],
}

_ENHANCED_DOCS = ["SOURCE_OF_FUNDS", "ENHANCED_DUE_DILIGENCE"]


def required_documents_for(investor_type, risk_rating):
    if risk_rating == "LOW":
        return []
    docs = list(_BASE_DOCS.get(investor_type, []))
    if risk_rating in ("HIGH", "PROHIBITED"):
        docs += list(_ENHANCED_DOCS)
    return docs


def documents_complete(case) -> bool:
    return set(case["required_documents"]) <= set(case["submitted_documents"])


# ---------------------------------------------------------------------------
# Investor aggregate recomputes
# ---------------------------------------------------------------------------

_UNFUNDED_STATUSES = {"ACCEPTED", "FUNDING_PARTIAL"}


def recompute_unfunded(investor):
    total = 0
    for sub in db["subscriptions"].values():
        if sub["investor_id"] == investor["id"] and sub["status"] in _UNFUNDED_STATUSES:
            total += sub["commitment_amount_cents"] - sub["funded_amount_cents"]
    if investor["aggregate_unfunded_commitment_cents"] != total:
        investor["aggregate_unfunded_commitment_cents"] = total
        touch(investor)


_TIER_RANK = {"UNVERIFIED": 0, "EXPIRED": 0, "ACCREDITED": 1, "QUALIFIED_PURCHASER": 2}


def recompute_accreditation(investor):
    """Highest tier among still-VERIFIED attestations, else UNVERIFIED."""
    best = "UNVERIFIED"
    for att in db["accreditations"].values():
        if att["investor_id"] == investor["id"] and att["status"] == "VERIFIED":
            if _TIER_RANK[att["attestation_tier"]] > _TIER_RANK[best]:
                best = att["attestation_tier"]
    if investor["accreditation_status"] != best:
        investor["accreditation_status"] = best
        touch(investor)


# ---------------------------------------------------------------------------
# KYC cascades (PRD 3.2)
# ---------------------------------------------------------------------------


def set_kyc_status(investor, status):
    if investor["kyc_status"] != status:
        investor["kyc_status"] = status
        touch(investor)


def cascade_kyc_approved(investor):
    set_kyc_status(investor, "APPROVED")
    for sub in db["subscriptions"].values():
        if sub["investor_id"] == investor["id"] and sub["status"] == "KYC_HOLD":
            sub["status"] = "COMPLIANCE_APPROVED"
            touch(sub)


def cascade_kyc_rejected(investor):
    set_kyc_status(investor, "REJECTED")
    for sub in db["subscriptions"].values():
        if sub["investor_id"] == investor["id"] and sub["status"] not in ("REJECTED", "CANCELLED"):
            sub["status"] = "REJECTED"
            touch(sub)
    recompute_unfunded(investor)


def open_kyc_case(investor, risk_rating, pep_hit, sanctions_hit, adverse_media_hit):
    """Create a KycCase: OPEN -> auto AWAITING_DOCUMENTS with required docs."""
    seq = sum(1 for c in db["kyc_cases"].values() if c["investor_id"] == investor["id"]) + 1
    case = stamp_new({
        "investor_id": investor["id"],
        "case_sequence": seq,
        "risk_rating": risk_rating,
        "required_documents": required_documents_for(investor["investor_type"], risk_rating),
        "submitted_documents": [],
        "pep_hit": pep_hit,
        "sanctions_hit": sanctions_hit,
        "adverse_media_hit": adverse_media_hit,
        "status": "AWAITING_DOCUMENTS",
        "rejection_reason": None,
    })
    db["kyc_cases"][case["id"]] = case
    set_kyc_status(investor, "DOCUMENTS_PENDING")
    return case


# ---------------------------------------------------------------------------
# Attestation expiry sweep (PRD 2.4 / 3.3)
# ---------------------------------------------------------------------------


def sweep_expirations():
    now = CLOCK.now()
    affected_investors = set()
    for att in db["accreditations"].values():
        if att["status"] == "VERIFIED" and parse_datetime(att["expires_at_utc"]) < now:
            att["status"] = "EXPIRED"
            touch(att)
            affected_investors.add(att["investor_id"])
    for inv_id in affected_investors:
        investor = db["investors"].get(inv_id)
        if investor is None:
            continue
        recompute_accreditation(investor)
        for sub in db["subscriptions"].values():
            if (sub["investor_id"] == inv_id
                    and sub["status"] in ("KYC_HOLD", "COMPLIANCE_APPROVED")):
                sub["status"] = "KYC_HOLD"
                touch(sub)


# ---------------------------------------------------------------------------
# Share class NAV per share (series accounting bookkeeping, PRD 3.6)
# ---------------------------------------------------------------------------

INITIAL_NAV_PER_SHARE_CENTS = 10000  # $100.00 conventional initial NAV/share


def class_nav_per_share(share_class) -> Decimal:
    nav = share_class.get("_nav_per_share")
    if nav is None:
        nav = Decimal(INITIAL_NAV_PER_SHARE_CENTS)
        share_class["_nav_per_share"] = nav
    return nav


def mint_series(share_class, nav_period):
    idx = sum(1 for s in db["series"].values()
              if s["share_class_id"] == share_class["id"]) + 1
    series = stamp_new({
        "share_class_id": share_class["id"],
        "nav_period_id": nav_period["id"],
        "series_index": idx,
        "opening_nav_per_share_cents": int(quantize_half_up(class_nav_per_share(share_class))),
        "equalization_factor_bps": 0,
        "status": "OPEN",
    })
    db["series"][series["id"]] = series
    return series


def current_open_series(share_class):
    """Latest OPEN series of the class, minting one under the open period if none."""
    open_series = [s for s in db["series"].values()
                   if s["share_class_id"] == share_class["id"] and s["status"] == "OPEN"]
    if open_series:
        open_series.sort(key=lambda s: (s["created_at"], s["_seq"]))
        return open_series[-1]
    fund = get_fund(share_class["fund_id"])
    period = get_nav_period(fund["current_nav_period_id"])
    return mint_series(share_class, period)


# ---------------------------------------------------------------------------
# MFN effective fee (calculation mfn_clause_effective_fee, PRD 3.5)
# ---------------------------------------------------------------------------


def base_fee_bps(share_class) -> int:
    return share_class["management_fee_bps"] + share_class["performance_fee_bps"]


def recompute_effective_fee(account):
    """Effective fee = base - min(sum of eligible ACTIVE FEE_REBATE rebates, base//2).

    Eligible clauses: elected on the account's subscription's EXECUTED side letters,
    still ACTIVE, tag FEE_REBATE, capacity_threshold <= commitment.
    """
    share_class = get_share_class(account["share_class_id"])
    base = base_fee_bps(share_class)
    sub = db["subscriptions"].get(account["subscription_id"])
    commitment = sub["commitment_amount_cents"] if sub else 0
    rebate = 0
    for letter in db["side_letters"].values():
        if (letter["subscription_id"] == account["subscription_id"]
                and letter["status"] == "EXECUTED"):
            for cid in letter["elected_clause_ids"]:
                clause = db["mfn_clauses"].get(cid)
                if (clause and clause["status"] == "ACTIVE"
                        and clause["clause_tag"] == "FEE_REBATE"
                        and clause["capacity_threshold_cents"] <= commitment):
                    rebate += clause["fee_rebate_bps"]
    rebate = min(rebate, base // 2)
    effective = base - rebate
    if account.get("effective_fee_bps") != effective:
        account["effective_fee_bps"] = effective
        touch(account)


def recompute_fees_for_subscription(subscription_id):
    for account in db["capital_accounts"].values():
        if account["subscription_id"] == subscription_id:
            recompute_effective_fee(account)


def applicable_liquidity_reduction(account) -> int:
    """Sum of notice_days_reduction over elected ACTIVE LIQUIDITY clauses on the
    account's subscription's EXECUTED side letters."""
    sub = db["subscriptions"].get(account["subscription_id"])
    commitment = sub["commitment_amount_cents"] if sub else 0
    total = 0
    for letter in db["side_letters"].values():
        if (letter["subscription_id"] == account["subscription_id"]
                and letter["status"] == "EXECUTED"):
            for cid in letter["elected_clause_ids"]:
                clause = db["mfn_clauses"].get(cid)
                if (clause and clause["status"] == "ACTIVE"
                        and clause["clause_tag"] == "LIQUIDITY"
                        and clause["capacity_threshold_cents"] <= commitment):
                    total += clause["notice_days_reduction"]
    return total


# ---------------------------------------------------------------------------
# Lockup (calculation lockup_expiry_date, PRD 3.4)
# ---------------------------------------------------------------------------


def compute_locked_until(funded_event_iso: str, lockup_months: int) -> str:
    base = parse_datetime(funded_event_iso)
    return fmt_datetime(add_calendar_months(base, lockup_months))


# ---------------------------------------------------------------------------
# Capital account period accumulators (statement generation, PRD 3.8)
# ---------------------------------------------------------------------------


def reset_period_accumulators(account, opening_balance):
    account["_period_opening"] = opening_balance
    account["_period_contributions"] = 0
    account["_period_distributions"] = 0
    account["_period_mgmt_fee"] = 0
    account["_period_perf_fee"] = 0
