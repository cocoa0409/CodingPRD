"""Core helpers: serialization, common field management, computed values,
pagination, validation helpers, and the ownership/treasury recalculation."""
import math
from decimal import Decimal, ROUND_HALF_UP

import db
from db import new_id, now_iso, clock, _parse_iso, _format_iso
from errors import raise_err, ERR_INVALID_REQUEST, ERR_NOT_FOUND


# ---------- request body ----------

def get_body():
    from flask import request
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def req_str(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v == "":
        raise_err(ERR_INVALID_REQUEST, f"Missing or invalid field: {field}")
    return v


def opt_str(body, field):
    v = body.get(field)
    if v is not None and not isinstance(v, str):
        raise_err(ERR_INVALID_REQUEST, f"Invalid field: {field}")
    return v


def req_int(body, field, min_val=None):
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        raise_err(ERR_INVALID_REQUEST, f"Missing or invalid field: {field}")
    if min_val is not None and v < min_val:
        raise_err(ERR_INVALID_REQUEST, f"Field {field} must be >= {min_val}")
    return v


def opt_int(body, field, min_val=None):
    v = body.get(field)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise_err(ERR_INVALID_REQUEST, f"Invalid field: {field}")
    if min_val is not None and v < min_val:
        raise_err(ERR_INVALID_REQUEST, f"Field {field} must be >= {min_val}")
    return v


def req_number(body, field):
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_err(ERR_INVALID_REQUEST, f"Missing or invalid field: {field}")
    return v


def opt_number(body, field):
    v = body.get(field)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_err(ERR_INVALID_REQUEST, f"Invalid field: {field}")
    return v


def req_enum(body, field, choices):
    v = body.get(field)
    if v is None or v not in choices:
        raise_err(ERR_INVALID_REQUEST, f"Missing or invalid field: {field}")
    return v


def opt_enum(body, field, choices):
    v = body.get(field)
    if v is None:
        return None
    if v not in choices:
        raise_err(ERR_INVALID_REQUEST, f"Invalid field: {field}")
    return v


def opt_bool(body, field, default=False):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise_err(ERR_INVALID_REQUEST, f"Invalid field: {field}")
    return v


def req_datetime(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str):
        raise_err(ERR_INVALID_REQUEST, f"Missing or invalid field: {field}")
    try:
        return _parse_iso(v)
    except Exception:
        raise_err(ERR_INVALID_REQUEST, f"Invalid datetime: {field}")


def check_unknown_fields(body, allowed):
    extra = set(body.keys()) - set(allowed)
    if extra:
        raise_err(ERR_INVALID_REQUEST, f"Unknown field(s): {', '.join(sorted(extra))}")


# ---------- rounding ----------

def round_half_up_cents(value: Decimal) -> int:
    """Round a Decimal to whole cents, half-up."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dec(x) -> Decimal:
    return Decimal(str(x))


# ---------- entity helpers ----------

def new_entity(store, fields: dict):
    eid = new_id()
    ts = now_iso()
    ent = {
        "id": eid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    ent.update(fields)
    store[eid] = ent
    return ent


def touch(ent):
    ent["updated_at"] = now_iso()
    ent["version"] += 1


def get_or_404(store, entity_id, label="Resource"):
    ent = store.get(entity_id)
    if ent is None:
        raise_err(ERR_NOT_FOUND, f"{label} not found: {entity_id}")
    return ent


# ---------- pagination ----------

def pagination_params():
    from flask import request
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except ValueError:
            raise_err(ERR_INVALID_REQUEST, "Invalid limit")
        if limit < 1 or limit > 100:
            raise_err(ERR_INVALID_REQUEST, "limit out of range")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except ValueError:
            raise_err(ERR_INVALID_REQUEST, "Invalid offset")
        if offset < 0:
            raise_err(ERR_INVALID_REQUEST, "offset out of range")
    return limit, offset


def paginate(items, limit, offset):
    ordered = sorted(items, key=lambda e: (e["created_at"], e["id"]))
    total = len(ordered)
    return ordered[offset:offset + limit], total


# ---------- physician computed fields ----------

def tenure_years(physician, at=None):
    at = at or clock.now()
    hire = _parse_iso(physician["hire_date"])
    delta_days = Decimal(str((at - hire).total_seconds())) / Decimal("86400")
    years = delta_days / Decimal("365.25")
    y = int(years.to_integral_value(rounding="ROUND_FLOOR"))
    return max(y, 0)


def total_shares_outstanding():
    return sum(p["shares_held"] for p in db.physicians.values()
               if p["partnership_status"] != "EXITED")


def recalc_ownership():
    """Recompute ownership_pct for all physicians + treasury_shares on the policy.
    ownership_pct = shares_held / total non-EXITED shares, 6dp half-up; 0 when total == 0."""
    total = total_shares_outstanding()
    for p in db.physicians.values():
        if total == 0:
            p["ownership_pct"] = 0.0
        else:
            pct = (Decimal(p["shares_held"]) / Decimal(total)).quantize(
                Decimal("0.000001"), rounding=ROUND_HALF_UP)
            p["ownership_pct"] = float(pct)
    if db.policy is not None:
        held = sum(p["shares_held"] for p in db.physicians.values())
        db.policy["treasury_shares"] = db.policy["total_shares_authorized"] - held


def serialize_physician(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "full_name": p["full_name"],
        "hire_date": p["hire_date"],
        "specialty": p.get("specialty"),
        "founding_shareholder": p.get("founding_shareholder", False),
        "initial_shares": p.get("initial_shares", 0),
        "partnership_status": p["partnership_status"],
        "standing": p["standing"],
        "shares_held": p["shares_held"],
        "capital_account_balance_cents": p["capital_account_balance_cents"],
        "ownership_pct": p["ownership_pct"],
        "tenure_years": tenure_years(p),
    }


# ---------- committee helpers ----------

def committee_status(members_len, quorum, current):
    if current == "DISSOLVED":
        return "DISSOLVED"
    if members_len >= quorum:
        return "ACTIVE"
    if current == "ACTIVE":
        return "IMPAIRED"
    if current == "IMPAIRED":
        return "IMPAIRED"
    return "CHARTERED"


def serialize_committee(c):
    count = len(c["members"])
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "name": c["name"],
        "committee_type": c["committee_type"],
        "quorum_count": c["quorum_count"],
        "approval_threshold": c["approval_threshold"],
        "charter_version": c["charter_version"],
        "members": c["members"],
        "active_member_count": count,
        "status": c["status"],
    }


# ---------- motion helpers ----------

def motion_tallies(motion):
    """Recompute vote tallies (non-voided only)."""
    vfor = vagainst = vabstain = 0
    for v in db.votes.values():
        if v["motion_id"] == motion["id"] and v["status"] != "VOIDED":
            if v["vote_choice"] == "FOR":
                vfor += 1
            elif v["vote_choice"] == "AGAINST":
                vagainst += 1
            elif v["vote_choice"] == "ABSTAIN":
                vabstain += 1
    motion["votes_for"] = vfor
    motion["votes_against"] = vagainst
    motion["votes_abstain"] = vabstain


def motion_threshold_type(motion_type):
    if motion_type in ("CAPITAL_CALL", "DISTRIBUTION", "COMP_POLICY"):
        return "SIMPLE_MAJORITY"
    return "SUPERMAJORITY"


def recompute_motion_counts(motion):
    """eligible_voter_count + required_votes."""
    evc = len(motion["eligible_voter_ids"]) - len(motion["recused_physician_ids"])
    motion["eligible_voter_count"] = evc
    if motion["threshold_type"] == "SUPERMAJORITY":
        num = db.policy["supermajority_num"]
        den = db.policy["supermajority_den"]
        motion["required_votes"] = math.ceil(num / den * evc)
    else:
        motion["required_votes"] = 0
    motion_tallies(motion)


def serialize_motion(m):
    return {
        "id": m["id"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
        "motion_type": m["motion_type"],
        "sponsor_physician_id": m["sponsor_physician_id"],
        "committee_id": m.get("committee_id"),
        "supersedes_motion_id": m.get("supersedes_motion_id"),
        "payload": m["payload"],
        "threshold_type": m["threshold_type"],
        "status": m["status"],
        "eligible_voter_ids": m["eligible_voter_ids"],
        "recused_physician_ids": m["recused_physician_ids"],
        "eligible_voter_count": m["eligible_voter_count"],
        "required_votes": m["required_votes"],
        "votes_for": m["votes_for"],
        "votes_against": m["votes_against"],
        "votes_abstain": m["votes_abstain"],
        "opened_at": m.get("opened_at"),
        "closes_at": m.get("closes_at"),
    }


# ---------- capital call helpers ----------

def recompute_call(collect_call):
    """Recompute collected_cents and compound status of a CapitalCall."""
    related = [a for a in db.assessments.values()
               if a["capital_call_id"] == collect_call["id"]]
    collect_call["collected_cents"] = sum(a["paid_cents"] for a in related)
    collect_call["assessed_total_cents"] = sum(a["assessed_cents"] for a in related)
    if collect_call["status"] == "BILLED" and related:
        if all(a["status"] == "PAID" for a in related):
            collect_call["status"] = "COLLECTED"
        elif all(a["status"] in ("PAID", "DEFAULTED") for a in related) and \
                any(a["status"] == "DEFAULTED" for a in related):
            collect_call["status"] = "PARTIALLY_DEFAULTED"


def serialize_assessment(a):
    return {
        "id": a["id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
        "capital_call_id": a["capital_call_id"],
        "physician_id": a["physician_id"],
        "shares_at_billing": a["shares_at_billing"],
        "assessed_cents": a["assessed_cents"],
        "late_fee_cents": a["late_fee_cents"],
        "paid_cents": a["paid_cents"],
        "total_due_cents": a["assessed_cents"] + a["late_fee_cents"],
        "status": a["status"],
    }


def serialize_call(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "motion_id": c["motion_id"],
        "purpose": c["purpose"],
        "total_amount_cents": c["total_amount_cents"],
        "due_date": c["due_date"],
        "assessed_total_cents": c["assessed_total_cents"],
        "collected_cents": c["collected_cents"],
        "status": c["status"],
    }


# ---------- policy ----------

def serialize_policy(pol):
    return dict(pol)


POLICY_DEFAULTS = {
    "board_quorum_count": 5,
    "supermajority_num": 2,
    "supermajority_den": 3,
    "voting_window_days": 14,
    "offer_window_days": 30,
    "buy_in_base_shareholder_cents": 25000000,
    "buy_in_base_partner_cents": 10000000,
    "tenure_discount_pct_per_year": 0.02,
    "max_tenure_discount_pct": 0.20,
    "min_buy_in_cents": 5000000,
    "fiscal_year_start_month": 7,
    "late_fee_pct": 0.10,
    "delinquency_grace_days": 30,
    "minority_discount_pct": 0.15,
    "ebitda_multiple": 6,
    "trailing_ebitda_cents": 0,
    "bonus_pool_pct": 0.25,
    "distribution_cap_pct": 0.60,
    "seniority_carve_pct": 0.20,
    "seniority_tier_years": 5,
    "max_dispute_rounds": 2,
    "max_committee_members": 7,
}

POLICY_INT_FIELDS = {
    "total_shares_authorized", "board_quorum_count", "supermajority_num",
    "supermajority_den", "voting_window_days", "offer_window_days",
    "buy_in_base_shareholder_cents", "buy_in_base_partner_cents",
    "min_buy_in_cents", "fiscal_year_start_month", "delinquency_grace_days",
    "trailing_ebitda_cents", "seniority_tier_years", "max_dispute_rounds",
    "max_committee_members",
}

POLICY_NUM_FIELDS = {
    "tenure_discount_pct_per_year", "max_tenure_discount_pct", "late_fee_pct",
    "minority_discount_pct", "ebitda_multiple", "bonus_pool_pct",
    "distribution_cap_pct", "seniority_carve_pct",
}

POLICY_ALL_FIELDS = POLICY_INT_FIELDS | POLICY_NUM_FIELDS


# ---------- distribution allocation ----------

def eligible_distribution_recipients():
    return [p for p in db.physicians.values()
            if p["partnership_status"] == "SHAREHOLDER" and p["standing"] != "SUSPENDED"]


def pro_rata_split(total_cents, recipients, shares, created):
    """Floor + residual pennies to largest holders (shares DESC, created_at ASC).
    recipients: list of ids. shares: dict id -> shares. created: dict id -> created_at.
    Returns dict id -> cents."""
    total_shares = sum(shares[r] for r in recipients)
    if total_shares <= 0:
        return {r: 0 for r in recipients}
    raw = {}
    for r in recipients:
        raw_amt = Decimal(total_cents) * Decimal(shares[r]) / Decimal(total_shares)
        raw[r] = int(raw_amt.to_integral_value(rounding="ROUND_FLOOR"))
    residual = total_cents - sum(raw.values())
    order = sorted(recipients, key=lambda r: (-shares[r], created[r]))
    i = 0
    while residual > 0 and i < len(order):
        raw[order[i]] += 1
        residual -= 1
        i += 1
    return raw


def compute_distribution_allocations(total_cents, method):
    eligible = eligible_distribution_recipients()
    ids = [p["id"] for p in eligible]
    shares = {p["id"]: p["shares_held"] for p in eligible}
    created = {p["id"]: p["created_at"] for p in eligible}
    if method == "PRO_RATA":
        return pro_rata_split(total_cents, ids, shares, created)
    # SENIORITY_TIERED
    carve = round_half_up_cents(dec(total_cents) * dec(db.policy["seniority_carve_pct"]))
    tier_years = db.policy["seniority_tier_years"]
    seniors = [p for p in eligible if tenure_years(p) >= tier_years]
    alloc = {pid: 0 for pid in ids}
    if seniors:
        senior_ids = [p["id"] for p in seniors]
        base = carve // len(seniors)
        for sid in senior_ids:
            alloc[sid] = base
        residual = carve - base * len(seniors)
        order = sorted(senior_ids, key=lambda r: created[r])
        i = 0
        while residual > 0:
            alloc[order[i]] += 1
            residual -= 1
            i += 1
        remainder = total_cents - carve
    else:
        remainder = total_cents
    rem_alloc = pro_rata_split(remainder, ids, shares, created)
    for pid in ids:
        alloc[pid] += rem_alloc[pid]
    return alloc


def serialize_distribution(d):
    return {
        "id": d["id"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
        "motion_id": d["motion_id"],
        "total_amount_cents": d["total_amount_cents"],
        "method": d["method"],
        "fiscal_net_income_before_bonus_cents": d["fiscal_net_income_before_bonus_cents"],
        "bonus_accrual_cents": d["bonus_accrual_cents"],
        "distributable_cap_cents": d["distributable_cap_cents"],
        "allocations": d["allocations"],
        "status": d["status"],
    }


def compute_distributable_cap(nibb_cents):
    bonus = round_half_up_cents(dec(nibb_cents) * dec(db.policy["bonus_pool_pct"]))
    net_after = nibb_cents - bonus
    cap = round_half_up_cents(dec(net_after) * dec(db.policy["distribution_cap_pct"]))
    return bonus, cap


# ---------- exit valuation ----------

def serialize_valuation(v):
    return {
        "id": v["id"],
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
        "physician_id": v["physician_id"],
        "trigger_type": v["trigger_type"],
        "ownership_pct_snapshot": v["ownership_pct_snapshot"],
        "provisional_value_cents": v["provisional_value_cents"],
        "appraised_practice_value_cents": v.get("appraised_practice_value_cents"),
        "final_value_cents": v.get("final_value_cents"),
        "appraisal_final": v["appraisal_final"],
        "dispute_rounds": v["dispute_rounds"],
        "approving_motion_id": v.get("approving_motion_id"),
        "payment_schedule_cents": v.get("payment_schedule_cents"),
        "status": v["status"],
    }


# ---------- misc serializers ----------

def serialize_seat(s):
    return {
        "id": s["id"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
        "seat_label": s["seat_label"],
        "seat_class": s["seat_class"],
        "status": s["status"],
        "current_holder_physician_id": s.get("current_holder_physician_id"),
        "current_term_start": s.get("current_term_start"),
        "current_term_end": s.get("current_term_end"),
        "next_holder_physician_id": s.get("next_holder_physician_id"),
        "next_term_start": s.get("next_term_start"),
        "next_term_end": s.get("next_term_end"),
    }


def serialize_offer(o):
    return {
        "id": o["id"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
        "physician_id": o["physician_id"],
        "target_tier": o["target_tier"],
        "share_grant": o["share_grant"],
        "installment_count": o["installment_count"],
        "offered_at": o["offered_at"],
        "acceptance_deadline": o["acceptance_deadline"],
        "tenure_years_at_offer": o["tenure_years_at_offer"],
        "discount_pct_applied": o["discount_pct_applied"],
        "proration_twelfths": o["proration_twelfths"],
        "final_amount_cents": o["final_amount_cents"],
        "installment_schedule_cents": o["installment_schedule_cents"],
        "paid_installment_count": o["paid_installment_count"],
        "status": o["status"],
    }


def serialize_vote(v):
    return {
        "id": v["id"],
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
        "motion_id": v["motion_id"],
        "physician_id": v["physician_id"],
        "vote_choice": v["vote_choice"],
        "status": v["status"],
        "void_reason": v.get("void_reason"),
    }


def serialize_coi(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "physician_id": c["physician_id"],
        "related_motion_id": c.get("related_motion_id"),
        "description": c["description"],
        "status": c["status"],
        "reviewed_by": c.get("reviewed_by"),
        "review_note": c.get("review_note"),
    }


def serialize_merger(m):
    return {
        "id": m["id"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
        "counterparty_name": m["counterparty_name"],
        "exchange_ratio_x1000": m["exchange_ratio_x1000"],
        "cash_consideration_cents": m["cash_consideration_cents"],
        "diligence_note": m.get("diligence_note"),
        "deciding_motion_id": m.get("deciding_motion_id"),
        "status": m["status"],
    }
