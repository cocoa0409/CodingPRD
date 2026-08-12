"""Domain services: derived balances, record-position snapshots, entitlement
projection, terms coherence, and the shared event helpers."""

from datetime import timedelta

import db
import util
from errors import ApiError
import errors as errmod
from helpers import stamp_new, stamp_immutable, touch

EVENT_TYPES = ["SPLIT", "MERGER", "SPIN_OFF", "CASH_DIVIDEND", "STOCK_DIVIDEND", "RIGHTS_OFFERING"]
FRACTIONAL_POLICIES = ["ROUND_HALF_UP", "ROUND_DOWN", "ROUND_UP"]
SOURCE_TYPES = ["CUSTODIAN", "VENDOR", "DEPOSITORY"]
CLAIM_REASONS = ["MISSED_ENTITLEMENT", "INCORRECT_AMOUNT", "FRACTIONAL_DISPUTE"]
CLAIM_BASES = ["EVENT_TERMS", "MARKET_VALUE"]

SETTLEMENT_LAG_DAYS = 2
ODD_LOT_THRESHOLD = 100
CLAIM_AMOUNT_CAP_CENTS = 250000
CLAIM_WINDOW_DAYS = 30


# ---------------------------------------------------------------------------
# accounts: derived balances (PRD 2.9)
# ---------------------------------------------------------------------------

def recompute_account(account_id):
    """Recompute cash_balance_cents / total_cost_basis_cents /
    pending_entitlement_count eagerly; each recomputation is an account
    mutation and therefore refreshes updated_at and increments version."""
    acct = db.get("accounts", account_id)
    if acct is None:
        return
    cash = acct["opening_cash_cents"]
    # cash deltas from lines of POSTED bookings touching this account
    for line in db.all_rows("booking_lines"):
        booking = db.get("bookings", line["booking_id"])
        if booking is None or booking["status"] != "POSTED":
            continue
        ent = db.get("entitlements", line["entitlement_id"])
        if ent is not None and ent["account_id"] == account_id:
            cash += line["cash_delta_cents"]
    # claim payments
    for claim in db.all_rows("claims"):
        if claim["account_id"] == account_id and claim["payment_status"] == "PAID":
            cash += claim["compensation_cents"] or 0
    acct["cash_balance_cents"] = cash
    acct["total_cost_basis_cents"] = sum(
        lot["cost_basis_total_cents"]
        for lot in db.all_rows("position_lots")
        if lot["account_id"] == account_id and lot["status"] == "OPEN"
    )
    acct["pending_entitlement_count"] = sum(
        1
        for ent in db.all_rows("entitlements")
        if ent["account_id"] == account_id and ent["status"] in ("PROJECTED", "FIRM")
    )
    touch(acct)


# ---------------------------------------------------------------------------
# record-position snapshot (SCAFFOLD calculation record_position_snapshot)
# ---------------------------------------------------------------------------

def open_lots(account_id, security_id):
    """OPEN lots of an account in a security, pinned processing order:
    acquisition_date ASC, tie-break created_at ASC (== creation sequence)."""
    lots = [
        lot for lot in db.all_rows("position_lots")
        if lot["account_id"] == account_id
        and lot["security_id"] == security_id
        and lot["status"] == "OPEN"
    ]
    lots.sort(key=lambda l: (l["acquisition_date"], l["_seq"]))
    return lots


def record_position_quantity(account_id, security_id, record_date, basis):
    """Sum of included lot quantities at 4dp. TRADE_DATE_BASIS includes lots
    acquired on or before record_date; SETTLED_BASIS on or before
    record_date - SETTLEMENT_LAG_DAYS."""
    if basis == "SETTLED_BASIS":
        cutoff = util.date_minus_days(record_date, SETTLEMENT_LAG_DAYS)
    else:
        cutoff = record_date
    total = util.D(0)
    for lot in open_lots(account_id, security_id):
        if util.parse_date_iso(lot["acquisition_date"]) <= cutoff:
            total += util.dec_of(lot["quantity"])
    return util.round4_half_up(total)


# ---------------------------------------------------------------------------
# entitlement projection (SCAFFOLD calculation entitlement_share_quantity)
# ---------------------------------------------------------------------------

def project_quantities(event, qty):
    """Aggregate projection from a record-position quantity.
    Returns (entitled_shares, fractional_shares_float, cash_in_lieu_cents,
    cash_amount_cents)."""
    terms = event["terms"]
    etype = event["event_type"]
    qty = util.D(qty)
    if etype in ("SPLIT", "STOCK_DIVIDEND", "SPIN_OFF"):
        ratio = util.D(terms["ratio_num"]) / util.D(terms["ratio_den"])
        gross = qty * ratio
        entitled = util.floor_int(gross)
        frac = util.round4_half_up(gross - util.D(entitled))
        cil = util.policy_round_cents(frac * util.D(terms["price_per_share_cents"]),
                                      terms["fractional_policy"])
        return entitled, float(frac), cil, 0
    if etype == "CASH_DIVIDEND":
        cash = util.floor_int(qty) * terms["cash_per_share_cents"]
        return 0, 0.0, 0, cash
    if etype == "RIGHTS_OFFERING":
        ratio = util.D(terms["rights_ratio_num"]) / util.D(terms["rights_ratio_den"])
        entitled = util.floor_int(qty * ratio)
        return entitled, 0.0, 0, 0
    # MERGER: outcomes are election-dependent; projected as zero
    return 0, 0.0, 0, 0


def compute_entitlement_fields(event, account_id, basis):
    record_date = util.parse_date_iso(event["record_date"])
    qty = record_position_quantity(account_id, event["security_id"], record_date, basis)
    entitled, frac, cil, cash = project_quantities(event, qty)
    return {
        "calculation_basis": basis,
        "record_position_quantity": float(qty),
        "entitled_shares": entitled,
        "fractional_shares": frac,
        "cash_in_lieu_cents": cil,
        "cash_amount_cents": cash,
    }


def new_entitlement(event, account_id, supersedes_id=None):
    fields = compute_entitlement_fields(event, account_id, "TRADE_DATE_BASIS")
    ent = {
        "event_id": event["id"],
        "account_id": account_id,
        "supersedes_entitlement_id": supersedes_id,
        "calculation_basis": fields["calculation_basis"],
        "record_position_quantity": fields["record_position_quantity"],
        "entitled_shares": fields["entitled_shares"],
        "fractional_shares": fields["fractional_shares"],
        "cash_in_lieu_cents": fields["cash_in_lieu_cents"],
        "cash_amount_cents": fields["cash_amount_cents"],
        "booked_whole_shares": None,
        "booked_cash_in_lieu_cents": None,
        "status": "PROJECTED",
    }
    stamp_new(ent)
    db.insert("entitlements", ent)
    return ent


def generate_projected_entitlements(event):
    """Confirm-from-DRAFT side effect: one PROJECTED entitlement per account
    holding >= 1 OPEN lot in the security with included position > 0."""
    record_date = util.parse_date_iso(event["record_date"])
    account_ids = []
    seen = set()
    for lot in db.all_rows("position_lots"):
        if lot["security_id"] == event["security_id"] and lot["status"] == "OPEN":
            if lot["account_id"] not in seen:
                seen.add(lot["account_id"])
                account_ids.append(lot["account_id"])
    affected = set()
    for aid in account_ids:
        qty = record_position_quantity(aid, event["security_id"], record_date,
                                       "TRADE_DATE_BASIS")
        if qty > 0:
            new_entitlement(event, aid)
            affected.add(aid)
    for aid in affected:
        recompute_account(aid)


# ---------------------------------------------------------------------------
# terms coherence (validation priority 3, ERR_INVALID_EVENT_TERMS)
# ---------------------------------------------------------------------------

def _terms_int(terms, key):
    v = terms.get(key)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(errmod.E_INVALID_EVENT_TERMS, 400,
                       "terms.%s must be an integer" % key)
    return v


def _terms_nonneg_int(terms, key):
    v = _terms_int(terms, key)
    if v < 0:
        raise ApiError(errmod.E_INVALID_EVENT_TERMS, 400,
                       "terms.%s must be non-negative" % key)
    return v


def _terms_str(terms, key):
    v = terms.get(key)
    if not isinstance(v, str) or not v.strip():
        raise ApiError(errmod.E_INVALID_EVENT_TERMS, 400,
                       "terms.%s must be a non-empty string" % key)
    return v


def _terms_ratio(terms, num_key, den_key):
    num = _terms_nonneg_int(terms, num_key)
    den = _terms_int(terms, den_key)
    if den <= 0:
        raise ApiError(errmod.E_INVALID_EVENT_TERMS, 400,
                       "terms.%s must be greater than zero" % den_key)
    return num, den


def _terms_policy(terms):
    v = terms.get("fractional_policy")
    if v not in FRACTIONAL_POLICIES:
        raise ApiError(errmod.E_INVALID_EVENT_TERMS, 400,
                       "terms.fractional_policy must be one of %s" % FRACTIONAL_POLICIES)
    return v


def validate_terms(event_type, terms):
    """Per-type required keys, ratio coherence, non-negative amounts."""
    if not isinstance(terms, dict):
        raise ApiError(errmod.E_INVALID_EVENT_TERMS, 400,
                       "terms must be an object")
    if event_type in ("SPLIT", "STOCK_DIVIDEND"):
        _terms_ratio(terms, "ratio_num", "ratio_den")
        _terms_nonneg_int(terms, "price_per_share_cents")
        _terms_policy(terms)
    elif event_type == "MERGER":
        _terms_nonneg_int(terms, "cash_per_share_cents")
        _terms_nonneg_int(terms, "cash_pool_cents")
        _terms_str(terms, "new_security_id")
        _terms_ratio(terms, "ratio_num", "ratio_den")
        default_option = terms.get("default_option")
        if default_option not in ("CASH", "STOCK"):
            raise ApiError(errmod.E_INVALID_EVENT_TERMS, 400,
                           "terms.default_option must be CASH or STOCK")
    elif event_type == "SPIN_OFF":
        _terms_str(terms, "spinoff_security_id")
        _terms_ratio(terms, "ratio_num", "ratio_den")
        _terms_nonneg_int(terms, "fmv_parent_cents")
        _terms_nonneg_int(terms, "fmv_spin_cents")
        _terms_nonneg_int(terms, "price_per_share_cents")
        _terms_policy(terms)
    elif event_type == "CASH_DIVIDEND":
        _terms_nonneg_int(terms, "cash_per_share_cents")
    elif event_type == "RIGHTS_OFFERING":
        _terms_ratio(terms, "rights_ratio_num", "rights_ratio_den")
        _terms_nonneg_int(terms, "subscription_price_cents")
        _terms_nonneg_int(terms, "shares_offered")
        if not isinstance(terms.get("oversubscription_allowed"), bool):
            raise ApiError(errmod.E_INVALID_EVENT_TERMS, 400,
                           "terms.oversubscription_allowed must be a boolean")


# ---------------------------------------------------------------------------
# event helpers
# ---------------------------------------------------------------------------

def get_event_or_404(event_id):
    event = db.get("events", event_id)
    if event is None:
        raise ApiError(errmod.E_EVENT_NOT_FOUND, 404, "Event not found")
    return event


def event_terminal_guard(event):
    if event["status"] in ("COMPLETED", "CANCELLED"):
        raise ApiError(errmod.E_EVENT_ALREADY_TERMINAL, 409,
                       "Operation on a terminal event")


def bump_event(event):
    touch(event)


def event_entitlements(event_id, statuses=None):
    rows = [e for e in db.all_rows("entitlements") if e["event_id"] == event_id]
    if statuses is not None:
        rows = [e for e in rows if e["status"] in statuses]
    return rows


def event_elections(event_id):
    return [e for e in db.all_rows("elections") if e["event_id"] == event_id]


def active_entitlement_for(event_id, account_id):
    """The account's latest non-SUPERSEDED entitlement for the event."""
    rows = [e for e in event_entitlements(event_id)
            if e["account_id"] == account_id and e["status"] != "SUPERSEDED"]
    return rows[-1] if rows else None
