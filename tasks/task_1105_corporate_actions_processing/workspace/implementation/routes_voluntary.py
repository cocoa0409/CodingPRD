"""Voluntary elections (PRD 3.5) and compensation claims (PRD 3.8)."""

from flask import Blueprint

import db
import util
import errors as errmod
from errors import ApiError
from helpers import (respond, respond_list, require_roles, body, req_str,
                     opt_int, req_int, req_enum, paginate, apply_filters,
                     stamp_new, touch)
from domain import (CLAIM_REASONS, CLAIM_AMOUNT_CAP_CENTS, CLAIM_WINDOW_DAYS,
                    get_event_or_404, event_terminal_guard,
                    active_entitlement_for, recompute_account)

bp = Blueprint("voluntary", __name__)

ALL = ("DeskAdministrator VendorFeed EventAnalyst OperationsManager "
       "AccountHolder ClaimsExaminer CustodianFeed").split()

ALLOWED_OPTIONS = {
    "MERGER": ("CASH", "STOCK"),
    "RIGHTS_OFFERING": ("EXERCISE",),
}


# ---------------------------------------------------------------------------
# elections
# ---------------------------------------------------------------------------

def _deadline_check(event):
    if event["election_required"] and event["election_deadline"]:
        deadline = util.parse_datetime_iso(event["election_deadline"])
        if util.now_dt() > deadline:
            raise ApiError(errmod.E_ELECTION_DEADLINE_PASSED, 422,
                           "The election deadline has passed")


@bp.post("/api/events/<rid>/elections")
def submit_election(rid):
    user_id = require_roles("AccountHolder")
    data = body()
    # --- priority 3: shape ---
    account_id = req_str(data, "account_id")
    option_code = req_enum(data, "option_code", ["CASH", "STOCK", "EXERCISE"])
    if "expected_event_version" not in data or data["expected_event_version"] is None:
        raise ApiError(errmod.E_INVALID_REQUEST, 400,
                       "Required field missing: expected_event_version")
    expected_version = data["expected_event_version"]
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise ApiError(errmod.E_INVALID_REQUEST, 400,
                       "expected_event_version must be an integer")
    quantity = data.get("quantity")
    if quantity is not None and (isinstance(quantity, bool)
                                 or not isinstance(quantity, int)):
        raise ApiError(errmod.E_INVALID_REQUEST, 400, "quantity must be an integer")
    if isinstance(quantity, int) and quantity <= 0:
        raise ApiError(errmod.E_INVALID_REQUEST, 400, "quantity must be positive")
    # --- priority 4: existence (path id, then body FKs) ---
    event = get_event_or_404(rid)
    account = db.get("accounts", account_id)
    if account is None:
        raise ApiError(errmod.E_ACCOUNT_NOT_FOUND, 404, "Account not found")
    # --- priority 5: ownership ---
    if user_id != account_id:
        raise ApiError(errmod.E_ACCOUNT_OWNERSHIP_MISMATCH, 403,
                       "X-User-ID must equal the election account_id")
    # --- priority 6: state ---
    event_terminal_guard(event)
    if event["status"] != "CONFIRMED":
        raise ApiError(errmod.E_EVENT_NOT_ACCEPTING_ELECTIONS, 409,
                       "Elections require a CONFIRMED event")
    # --- priority 7: OCC ---
    if expected_version != event["version"]:
        raise ApiError(errmod.E_STALE_EVENT_VERSION, 412,
                       "expected_event_version does not match the event version")
    # --- priority 9: account must be ACTIVE ---
    if account["status"] != "ACTIVE":
        raise ApiError(errmod.E_ACCOUNT_NOT_ACTIVE, 409,
                       "Election submission requires an ACTIVE account")
    # --- priority 10: temporal ---
    _deadline_check(event)
    # --- priority 11: referential ---
    if not event["election_required"]:
        raise ApiError(errmod.E_EVENT_NOT_VOLUNTARY, 422,
                       "The event does not require elections")
    allowed = ALLOWED_OPTIONS.get(event["event_type"], ())
    if option_code not in allowed:
        raise ApiError(errmod.E_INVALID_ELECTION_OPTION, 400,
                       "option_code is not allowed for this event type")
    if event["event_type"] == "RIGHTS_OFFERING" and quantity is None:
        raise ApiError(errmod.E_INVALID_ELECTION_OPTION, 400,
                       "quantity is required for a RIGHTS_OFFERING election")
    if event["event_type"] != "RIGHTS_OFFERING" and quantity is not None:
        raise ApiError(errmod.E_INVALID_ELECTION_OPTION, 400,
                       "quantity is forbidden for this event type")
    # --- priority 12: fiscal ---
    if (event["event_type"] == "RIGHTS_OFFERING"
            and not event["terms"]["oversubscription_allowed"]):
        ent = active_entitlement_for(rid, account_id)
        entitled = ent["entitled_shares"] if ent is not None else 0
        if quantity > entitled:
            raise ApiError(errmod.E_ELECTION_QUANTITY_EXCEEDS_ENTITLEMENT, 422,
                           "Requested quantity exceeds entitled rights")
    # --- side effects ---
    prior_count = sum(1 for e in db.all_rows("elections")
                      if e["event_id"] == rid and e["account_id"] == account_id)
    for el in db.all_rows("elections"):
        if (el["event_id"] == rid and el["account_id"] == account_id
                and el["status"] == "SUBMITTED"):
            el["status"] = "SUPERSEDED"
            touch(el)
    election = {
        "event_id": rid,
        "account_id": account_id,
        "option_code": option_code,
        "quantity": quantity,
        "election_seq": prior_count + 1,
        "submitted_at": util.now_iso(),
        "status": "SUBMITTED",
    }
    stamp_new(election)
    db.insert("elections", election)
    touch(event)
    return respond(db.public(election), 201)


@bp.post("/api/elections/<rid>/withdraw")
def withdraw_election(rid):
    user_id = require_roles("AccountHolder")
    election = db.get("elections", rid)
    if election is None:
        raise ApiError(errmod.E_ELECTION_NOT_FOUND, 404, "Election not found")
    if user_id != election["account_id"]:
        raise ApiError(errmod.E_ACCOUNT_OWNERSHIP_MISMATCH, 403,
                       "X-User-ID must equal the election account_id")
    event = get_event_or_404(election["event_id"])
    event_terminal_guard(event)
    if election["status"] != "SUBMITTED":
        raise ApiError(errmod.E_ELECTION_INVALID_STATE, 409,
                       "Withdrawal requires a SUBMITTED election")
    _deadline_check(event)
    election["status"] = "WITHDRAWN"
    touch(election)
    touch(event)
    return respond(db.public(election), 200)


@bp.post("/api/elections/<rid>/resubmit")
def resubmit_election(rid):
    user_id = require_roles("AccountHolder")
    election = db.get("elections", rid)
    if election is None:
        raise ApiError(errmod.E_ELECTION_NOT_FOUND, 404, "Election not found")
    if user_id != election["account_id"]:
        raise ApiError(errmod.E_ACCOUNT_OWNERSHIP_MISMATCH, 403,
                       "X-User-ID must equal the election account_id")
    event = get_event_or_404(election["event_id"])
    event_terminal_guard(event)
    if event["status"] != "CONFIRMED":
        raise ApiError(errmod.E_EVENT_NOT_ACCEPTING_ELECTIONS, 409,
                       "Resubmission requires a CONFIRMED event")
    if election["status"] != "WITHDRAWN":
        raise ApiError(errmod.E_ELECTION_INVALID_STATE, 409,
                       "Resubmission requires a WITHDRAWN election")
    _deadline_check(event)
    for el in db.all_rows("elections"):
        if (el["event_id"] == election["event_id"]
                and el["account_id"] == election["account_id"]
                and el["id"] != election["id"] and el["status"] == "SUBMITTED"):
            el["status"] = "SUPERSEDED"
            touch(el)
    election["status"] = "SUBMITTED"
    election["submitted_at"] = util.now_iso()
    election["election_seq"] += 1
    touch(election)
    touch(event)
    return respond(db.public(election), 200)


@bp.get("/api/elections")
def list_elections():
    require_roles(*ALL)
    rows = apply_filters(db.all_rows("elections"), [
        ("event_id", "event_id"),
        ("account_id", "account_id"),
        ("status", "status"),
    ])
    page, meta = paginate(rows)
    return respond_list([db.public(r) for r in page], meta)


@bp.get("/api/elections/<rid>")
def get_election(rid):
    require_roles(*ALL)
    rec = db.get("elections", rid)
    if rec is None:
        raise ApiError(errmod.E_ELECTION_NOT_FOUND, 404, "Election not found")
    return respond(db.public(rec), 200)


# ---------------------------------------------------------------------------
# claims
# ---------------------------------------------------------------------------

def compute_compensation(event, claim, entitlement):
    """claim_compensation_amount: EVENT_TERMS values shares at the terms price,
    MARKET_VALUE at the claim's filing market price."""
    price = (event["terms"].get("price_per_share_cents", 0)
             if event["claim_compensation_basis"] == "EVENT_TERMS"
             else (claim["market_price_cents"] or 0))
    return (entitlement["cash_amount_cents"]
            + entitlement["entitled_shares"] * price
            + entitlement["cash_in_lieu_cents"])


@bp.post("/api/claims")
def file_claim():
    user_id = require_roles("AccountHolder")
    data = body()
    # --- priority 3: shape ---
    event_id = req_str(data, "event_id")
    entitlement_id = req_str(data, "entitlement_id")
    account_id = req_str(data, "account_id")
    reason = req_enum(data, "reason", CLAIM_REASONS)
    claimed = req_int(data, "claimed_amount_cents")
    market_price = opt_int(data, "market_price_cents", None)
    # --- priority 4: existence, body FKs in declared field order ---
    event = db.get("events", event_id)
    if event is None:
        raise ApiError(errmod.E_EVENT_NOT_FOUND, 404, "Event not found")
    entitlement = db.get("entitlements", entitlement_id)
    if entitlement is None:
        raise ApiError(errmod.E_ENTITLEMENT_NOT_FOUND, 404, "Entitlement not found")
    if db.get("accounts", account_id) is None:
        raise ApiError(errmod.E_ACCOUNT_NOT_FOUND, 404, "Account not found")
    # market price required under the MARKET_VALUE basis
    if event["claim_compensation_basis"] == "MARKET_VALUE" and market_price is None:
        raise ApiError(errmod.E_INVALID_REQUEST, 400,
                       "market_price_cents is required when the event's "
                       "claim_compensation_basis is MARKET_VALUE")
    # --- priority 5: ownership ---
    if user_id != account_id:
        raise ApiError(errmod.E_ACCOUNT_OWNERSHIP_MISMATCH, 403,
                       "X-User-ID must equal the claim account_id")
    # --- priority 9: no other FILED claim on the same entitlement ---
    for claim in db.all_rows("claims"):
        if claim["entitlement_id"] == entitlement_id and claim["review_status"] == "FILED":
            raise ApiError(errmod.E_DUPLICATE_OPEN_CLAIM, 409,
                           "Another FILED claim already exists for this entitlement")
    # --- priority 10: temporal filing window ---
    payable = util.parse_date_iso(event["payable_date"])
    window_end = util.midnight_utc(util.date_plus_days(payable, CLAIM_WINDOW_DAYS + 1))
    if util.now_dt() >= window_end:
        raise ApiError(errmod.E_CLAIM_WINDOW_EXPIRED, 422,
                       "Claim filing window has expired")
    # --- priority 11: referential eligibility ---
    if (entitlement["event_id"] != event_id
            or entitlement["account_id"] != account_id
            or entitlement["status"] not in ("MISSED", "SETTLED")):
        raise ApiError(errmod.E_ENTITLEMENT_NOT_CLAIMABLE, 422,
                       "Entitlement must belong to the claim's event and account "
                       "and be MISSED or SETTLED")
    # --- priority 12: fiscal cap ---
    if claimed <= 0 or claimed > CLAIM_AMOUNT_CAP_CENTS:
        raise ApiError(errmod.E_CLAIM_AMOUNT_EXCEEDS_CAP, 422,
                       "claimed_amount_cents must be > 0 and <= 250000")
    # --- create ---
    claim = {
        "event_id": event_id,
        "entitlement_id": entitlement_id,
        "account_id": account_id,
        "reason": reason,
        "claimed_amount_cents": claimed,
        "market_price_cents": market_price,
        "compensation_cents": None,
        "filed_by_user_id": user_id,
        "reviewed_by_user_id": None,
        "review_status": "FILED",
        "payment_status": "UNPAID",
    }
    stamp_new(claim)
    db.insert("claims", claim)
    return respond(db.public(claim), 201)


@bp.get("/api/claims")
def list_claims():
    require_roles(*ALL)
    rows = apply_filters(db.all_rows("claims"), [
        ("event_id", "event_id"),
        ("entitlement_id", "entitlement_id"),
        ("account_id", "account_id"),
        ("review_status", "review_status"),
    ])
    page, meta = paginate(rows)
    return respond_list([db.public(r) for r in page], meta)


@bp.get("/api/claims/<rid>")
def get_claim(rid):
    require_roles(*ALL)
    rec = db.get("claims", rid)
    if rec is None:
        raise ApiError(errmod.E_CLAIM_NOT_FOUND, 404, "Claim not found")
    return respond(db.public(rec), 200)


@bp.post("/api/claims/<rid>/decide")
def decide_claim(rid):
    user_id = require_roles("ClaimsExaminer")
    data = body()
    decision = req_enum(data, "decision", ["APPROVED", "DENIED"])
    claim = db.get("claims", rid)
    if claim is None:
        raise ApiError(errmod.E_CLAIM_NOT_FOUND, 404, "Claim not found")
    # state
    if claim["review_status"] != "FILED":
        raise ApiError(errmod.E_CLAIM_NOT_FILED, 409,
                       "Decision requires a FILED claim")
    # segregation of duties
    if user_id == claim["filed_by_user_id"]:
        raise ApiError(errmod.E_SEGREGATION_OF_DUTIES, 403,
                       "The examiner must differ from the claim filer")
    event = db.get("events", claim["event_id"])
    if decision == "APPROVED":
        entitlement = db.get("entitlements", claim["entitlement_id"])
        compensation = compute_compensation(event, claim, entitlement)
        if compensation > event["compensation_pool_remaining_cents"]:
            raise ApiError(errmod.E_COMPENSATION_POOL_EXHAUSTED, 402,
                           "Compensation exceeds the event's remaining pool")
        claim["compensation_cents"] = compensation
        claim["review_status"] = "APPROVED"
        claim["reviewed_by_user_id"] = user_id
        touch(claim)
        event["compensation_pool_remaining_cents"] -= compensation
        touch(event)
    else:
        claim["review_status"] = "DENIED"
        claim["reviewed_by_user_id"] = user_id
        touch(claim)
    return respond(db.public(claim), 200)


@bp.post("/api/claims/<rid>/pay")
def pay_claim(rid):
    require_roles("OperationsManager")
    claim = db.get("claims", rid)
    if claim is None:
        raise ApiError(errmod.E_CLAIM_NOT_FOUND, 404, "Claim not found")
    if claim["review_status"] != "APPROVED" or claim["payment_status"] != "UNPAID":
        raise ApiError(errmod.E_CLAIM_NOT_PAYABLE, 409,
                       "Payment requires an APPROVED, UNPAID claim")
    claim["payment_status"] = "PAID"
    touch(claim)
    recompute_account(claim["account_id"])
    entitlement = db.get("entitlements", claim["entitlement_id"])
    if entitlement is not None and entitlement["status"] == "MISSED":
        entitlement["status"] = "COMPENSATED"
        touch(entitlement)
    return respond(db.public(claim), 200)
