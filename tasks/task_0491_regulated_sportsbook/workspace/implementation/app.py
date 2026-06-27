"""Regulated Sportsbook API — Flask entry point.

In-memory only; nothing is seeded at startup. The logical clock starts at
2026-01-01T00:00:00Z on every boot (db.Clock).
"""

import os

from flask import Flask, request

from db import db, clock, iso_now, parse_iso, parse_date, format_iso, next_seq
from errors import ApiError, err
from response import success, error_response
import helpers as H
import services as S
import calc

from datetime import timedelta

app = Flask(__name__)
app.url_map.strict_slashes = False


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
        return handle_api_error(e)
    return error_response("ERR_INVALID_REQUEST", f"Unexpected error: {e}", 422)


# Serialize every mutating request so cascades stay atomic and OCC is
# deterministic (PRD §1: disciplined ordering, atomic cascades).
@app.before_request
def _acquire_lock():
    from db import request_lock
    request_lock.acquire()


@app.teardown_request
def _release_lock(exc):
    from db import request_lock
    try:
        request_lock.release()
    except RuntimeError:
        pass


# ---------------------------------------------------------------------------
# Lookup helpers (existence -> ERR_NOT_FOUND, PRD §2.9)
# ---------------------------------------------------------------------------
def get_account_or_404(account_id):
    acct = db.accounts.get(account_id)
    if not acct:
        raise err("ERR_NOT_FOUND", "Account not found")
    return acct


def get_event_or_404(event_id):
    e = db.events.get(event_id)
    if not e:
        raise err("ERR_NOT_FOUND", "Event not found")
    return e


def get_market_or_404(market_id):
    m = db.markets.get(market_id)
    if not m:
        raise err("ERR_NOT_FOUND", "Market not found")
    return m


def get_selection_or_404(selection_id):
    s = db.selections.get(selection_id)
    if not s:
        raise err("ERR_NOT_FOUND", "Selection not found")
    return s


def get_bet_or_404(bet_id):
    b = db.bets.get(bet_id)
    if not b:
        raise err("ERR_NOT_FOUND", "Bet not found")
    return b


def get_promotion_or_404(promotion_id):
    p = db.promotions.get(promotion_id)
    if not p:
        raise err("ERR_NOT_FOUND", "Promotion not found")
    return p


def get_grant_or_404(grant_id):
    g = db.bonus_grants.get(grant_id)
    if not g:
        raise err("ERR_NOT_FOUND", "Bonus grant not found")
    return g


def check_account_ownership(acct, user_id, role):
    """Bettor may act only on their own account (PRD §2.1 / validation p4)."""
    if role == "Bettor" and acct["id"] != user_id:
        raise err("ERR_FORBIDDEN", "Bettor may only act on their own account")


def check_occ(acct, body):
    """Optimistic concurrency on Account.version (PRD §2.6).

    expected_account_version must be present and equal the current version.
    """
    expected = body.get("expected_account_version")
    if expected is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: expected_account_version")
    try:
        expected_int = int(expected)
    except (TypeError, ValueError):
        raise err("ERR_INVALID_REQUEST", "expected_account_version must be an integer")
    if expected_int != acct["version"]:
        raise err("ERR_STALE_VERSION", "expected_account_version does not match current version")


# ===========================================================================
# Health probe
# ===========================================================================
@app.route("/_health", methods=["GET"])
def health():
    return success({})


# ===========================================================================
# Logical clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    H.require_auth({"TradingOps", "SettlementAgent", "ComplianceOfficer"})
    body = H.get_json()
    H.require_fields(body, ["to_iso8601"])
    try:
        new_time = parse_iso(body["to_iso8601"])
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be a valid ISO 8601 timestamp")
    clock.set(new_time)
    # Auto event SCHEDULED->LIVE when clock reaches starts_at (PRD §3.6) is
    # surfaced lazily; explicit transitions remain the primary path.
    return success({"now": format_iso(clock.get())})


# ===========================================================================
# Accounts & KYC
# ===========================================================================
PERMITTED_RESIDENCE = {"NJ", "NY", "PA", "CO", "AZ", "NV"}


@app.route("/accounts", methods=["POST"])
def create_account():
    # Anonymous self-service: no auth headers required (PRD §2.1).
    body = H.get_json()
    H.require_fields(body, ["email", "full_name", "date_of_birth", "residence_state"])

    email = body["email"]
    if not isinstance(email, str) or email.strip() == "":
        raise err("ERR_INVALID_REQUEST", "email must be a non-empty string")
    # Unique email across the platform (PRD §3.1).
    for a in db.accounts.values():
        if a["email"] == email:
            raise err("ERR_INVALID_REQUEST", "email must be unique")

    full_name = body["full_name"]
    if not isinstance(full_name, str) or full_name.strip() == "":
        raise err("ERR_INVALID_REQUEST", "full_name must be a non-empty string")

    dob = body["date_of_birth"]
    try:
        parse_date(dob)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "date_of_birth must be YYYY-MM-DD")

    state = body["residence_state"]
    H.require_enum(state, PERMITTED_RESIDENCE, "residence_state")

    rec = S.base_record(versioned=True)
    rec.update({
        "email": email,
        "full_name": full_name,
        "date_of_birth": dob,
        "residence_state": state,
        "kyc_status": "PENDING",
        "rg_status": "ACTIVE",
        "cooling_off_until": None,
        "kyc_decided_by": None,
    })
    db.accounts[rec["id"]] = rec
    return success(S.serialize_account(rec), status=201)


@app.route("/accounts/<account_id>", methods=["GET"])
def read_account(account_id):
    uid, role = H.require_auth({"Bettor", "ComplianceOfficer", "TradingOps"})
    acct = get_account_or_404(account_id)
    check_account_ownership(acct, uid, role)
    return success(S.serialize_account(acct))


@app.route("/accounts", methods=["GET"])
def list_accounts():
    H.require_auth({"ComplianceOfficer", "TradingOps"})
    limit, offset = H.get_pagination()
    rows = list(db.accounts.values())
    kyc = request.args.get("kyc_status")
    rg = request.args.get("rg_status")
    # Re-eval cooling-off so filters reflect current rg_status.
    for a in rows:
        S.reeval_cooling_off(a)
    if kyc:
        rows = [a for a in rows if a["kyc_status"] == kyc]
    if rg:
        rows = [a for a in rows if a["rg_status"] == rg]
    rows = H.sorted_by_created(rows)
    page, meta = H.paginate(rows, limit, offset)
    return success([S.serialize_account(a) for a in page], pagination=meta)


@app.route("/accounts/<account_id>/kyc-decision", methods=["POST"])
def kyc_decision(account_id):
    uid, role = H.require_auth({"ComplianceOfficer"})
    acct = get_account_or_404(account_id)
    body = H.get_json()

    decision = body.get("decision")
    H.require_enum(decision, {"VERIFY", "REJECT"}, "decision")

    # State precondition: only PENDING accounts can be decided (PRD §3.1).
    if acct["kyc_status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "KYC already decided")

    # OCC after existence/state (PRD §2.10 ordering keeps OCC with the write).
    check_occ(acct, body)

    if decision == "VERIFY":
        # Age >= 21 at clock date (PRD §3.1).
        dob = parse_date(acct["date_of_birth"])
        today = clock.get().date()
        age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
        if age < calc.MIN_AGE_YEARS:
            raise err("ERR_UNDERAGE", "Account holder must be at least 21")
        acct["kyc_status"] = "VERIFIED"
    else:
        acct["kyc_status"] = "REJECTED"

    acct["kyc_decided_by"] = uid
    S.touch(acct)
    return success(S.serialize_account(acct))


# ---------------------------------------------------------------------------
# Responsible-gaming controls
# ---------------------------------------------------------------------------
RG_TYPES = {"DEPOSIT_LIMIT", "WAGER_LIMIT", "NET_LOSS_LIMIT", "COOLING_OFF", "SELF_EXCLUSION"}
LIMIT_TYPES = {"DEPOSIT_LIMIT", "WAGER_LIMIT", "NET_LOSS_LIMIT"}


@app.route("/accounts/<account_id>/rg-controls", methods=["POST"])
def create_rg_control(account_id):
    uid, role = H.require_auth({"Bettor", "ComplianceOfficer"})
    acct = get_account_or_404(account_id)
    body = H.get_json()

    control_type = body.get("control_type")
    H.require_enum(control_type, RG_TYPES, "control_type")

    # Role gating per control type (PRD §3.2):
    #   SELF_EXCLUSION -> ComplianceOfficer only.
    #   COOLING_OFF + limit controls -> Bettor (acting on own account).
    if control_type == "SELF_EXCLUSION":
        if role != "ComplianceOfficer":
            raise err("ERR_FORBIDDEN", "Only a ComplianceOfficer may self-exclude")
    else:
        if role != "Bettor":
            raise err("ERR_FORBIDDEN", "Only the account holder may set this control")
        check_account_ownership(acct, uid, role)

    S.reeval_cooling_off(acct)

    # State precondition: SELF_EXCLUDED is terminal/irreversible (PRD §3.2).
    if acct["rg_status"] == "SELF_EXCLUDED":
        raise err("ERR_INVALID_STATE", "Account is permanently self-excluded")

    # Field-level checks for cooling-off come before OCC's structural needs but
    # cooling-off duration is part of the request body validity (PRD §3.2).
    period = body.get("period", "DAILY")
    limit_cents = body.get("limit_cents")
    duration_days = body.get("duration_days")

    if control_type == "COOLING_OFF":
        if duration_days is None:
            raise err("ERR_INVALID_REQUEST", "duration_days is required for COOLING_OFF")
        H.require_int(duration_days, "duration_days")
        if duration_days < 1:
            raise err("ERR_INVALID_REQUEST", "duration_days must be >= 1")

    if control_type in LIMIT_TYPES:
        H.require_enum(period, {"DAILY", "WEEKLY"}, "period")
        if limit_cents is None:
            raise err("ERR_INVALID_REQUEST", "limit_cents is required for a limit control")
        H.require_positive_int(limit_cents, "limit_cents")

    # OCC (PRD §2.6) — required for every RG control creation.
    check_occ(acct, body)

    # Supersede a prior ACTIVE control of the same type (PRD §3.2).
    for c in db.rg_controls.values():
        if (c["account_id"] == account_id and c["control_type"] == control_type
                and c["status"] == "ACTIVE"):
            c["status"] = "SUPERSEDED"
            S.touch(c)

    rec = S.base_record(versioned=True)
    rec.update({
        "account_id": account_id,
        "control_type": control_type,
        "period": period if control_type in LIMIT_TYPES else (period or "DAILY"),
        "limit_cents": limit_cents if control_type in LIMIT_TYPES else None,
        "duration_days": duration_days if control_type == "COOLING_OFF" else None,
        "status": "ACTIVE",
        "set_at": iso_now(),
    })
    db.rg_controls[rec["id"]] = rec

    # Side effects on the account's rg_status (PRD §3.2).
    if control_type == "COOLING_OFF":
        until = clock.get() + timedelta(days=duration_days)
        acct["cooling_off_until"] = format_iso(until)
        acct["rg_status"] = "COOLING_OFF"
    elif control_type == "SELF_EXCLUSION":
        _self_exclude_cascade(acct)

    S.touch(acct)
    # PRD §3.2: every control creation increments the account's version. The
    # scaffold's OCC chains thread the account version forward from this
    # response's `version` field, so surface the account's post-bump version
    # here (the control row itself is immutable apart from supersession).
    rec["version"] = acct["version"]
    return success(S.serialize_rg_control(rec), status=201)


def _self_exclude_cascade(acct):
    """rg_status -> SELF_EXCLUDED + cascade (PRD §3.2)."""
    acct["rg_status"] = "SELF_EXCLUDED"
    acct["cooling_off_until"] = None
    # Void every PLACED bet, refunding stake.
    for bet in list(db.bets.values()):
        if bet["account_id"] == acct["id"] and bet["status"] == "PLACED":
            S.void_bet(bet)
    # Forfeit every ACTIVE bonus grant, zeroing bonus balance.
    for grant in list(db.bonus_grants.values()):
        if grant["account_id"] == acct["id"] and grant["status"] == "ACTIVE":
            remaining = S.bonus_balance(acct["id"])
            if remaining != 0:
                S.post_ledger(acct["id"], "VOID_REFUND", "BONUS", -remaining,
                              ref_type="BONUS_GRANT", ref_id=None)
            grant["status"] = "FORFEITED"
            S.touch(grant)


@app.route("/accounts/<account_id>/rg-controls", methods=["GET"])
def list_rg_controls(account_id):
    uid, role = H.require_auth({"Bettor", "ComplianceOfficer"})
    acct = get_account_or_404(account_id)
    check_account_ownership(acct, uid, role)
    limit, offset = H.get_pagination()
    rows = [c for c in db.rg_controls.values() if c["account_id"] == account_id]
    status = request.args.get("status")
    if status:
        rows = [c for c in rows if c["status"] == status]
    rows = H.sorted_by_created(rows)
    page, meta = H.paginate(rows, limit, offset)
    return success([S.serialize_rg_control(c) for c in page], pagination=meta)


# ---------------------------------------------------------------------------
# Deposits & withdrawals
# ---------------------------------------------------------------------------
def _active_control(account_id, control_type):
    for c in db.rg_controls.values():
        if (c["account_id"] == account_id and c["control_type"] == control_type
                and c["status"] == "ACTIVE"):
            return c
    return None


@app.route("/accounts/<account_id>/deposits", methods=["POST"])
def deposit(account_id):
    uid, role = H.require_auth({"Bettor"})
    acct = get_account_or_404(account_id)
    check_account_ownership(acct, uid, role)
    body = H.get_json()

    S.reeval_cooling_off(acct)

    # RG gates (PRD §2.10 order): self-excluded, cooling-off, then KYC.
    if acct["rg_status"] == "SELF_EXCLUDED":
        raise err("ERR_RG_SELF_EXCLUDED", "Account is self-excluded")
    if acct["rg_status"] == "COOLING_OFF":
        raise err("ERR_RG_COOLING_OFF", "Account is in a cooling-off period")
    if acct["kyc_status"] != "VERIFIED":
        raise err("ERR_KYC_NOT_VERIFIED", "Account must be KYC-verified")

    amount = body.get("amount_cents")
    if amount is None:
        raise err("ERR_INVALID_REQUEST", "amount_cents is required")
    H.require_positive_int(amount, "amount_cents")

    # Deposit limit (PRD §3.3) — rolling window, strict-> boundary.
    ctrl = _active_control(account_id, "DEPOSIT_LIMIT")
    if ctrl:
        window_start = clock.get() - timedelta(seconds=calc.period_seconds(ctrl["period"]))
        now = clock.get()
        deposited = 0
        for e in S.account_ledger(account_id):
            if e["entry_type"] == "DEPOSIT" and e["bucket"] == "CASH":
                ts = parse_iso(e["created_at"])
                if window_start < ts <= now:
                    deposited += e["amount_cents"]
        if deposited + amount > ctrl["limit_cents"]:
            raise err("ERR_DEPOSIT_LIMIT_EXCEEDED", "Deposit limit exceeded")

    # OCC
    check_occ(acct, body)

    entry = S.post_ledger(account_id, "DEPOSIT", "CASH", amount, ref_type="NONE", ref_id=None)
    S.touch(acct)
    return success(S.serialize_ledger_entry(entry), status=201)


@app.route("/accounts/<account_id>/withdrawals", methods=["POST"])
def withdraw(account_id):
    uid, role = H.require_auth({"Bettor"})
    acct = get_account_or_404(account_id)
    check_account_ownership(acct, uid, role)
    body = H.get_json()

    S.reeval_cooling_off(acct)

    # KYC required for withdrawals (PRD §3.3). (No RG block listed for withdraw.)
    if acct["kyc_status"] != "VERIFIED":
        raise err("ERR_KYC_NOT_VERIFIED", "Account must be KYC-verified")

    amount = body.get("amount_cents")
    if amount is None:
        raise err("ERR_INVALID_REQUEST", "amount_cents is required")
    H.require_positive_int(amount, "amount_cents")

    # Funds availability (CASH bucket) — priority 17 before WR? PRD §2.10 lists
    # ERR_INSUFFICIENT_FUNDS (p17) before ERR_WR_NOT_MET (p18).
    if amount > S.cash_balance(account_id):
        raise err("ERR_INSUFFICIENT_FUNDS", "Insufficient cash balance")

    # Blocked by any ACTIVE grant with unmet wagering requirement (PRD §3.3).
    for g in db.bonus_grants.values():
        if g["account_id"] == account_id and g["status"] == "ACTIVE":
            raise err("ERR_WR_NOT_MET", "Withdrawal blocked by unmet wagering requirement")

    check_occ(acct, body)

    entry = S.post_ledger(account_id, "WITHDRAWAL", "CASH", -amount, ref_type="NONE", ref_id=None)
    S.touch(acct)
    return success(S.serialize_ledger_entry(entry), status=201)


@app.route("/accounts/<account_id>/ledger", methods=["GET"])
def list_account_ledger(account_id):
    uid, role = H.require_auth({"Bettor", "ComplianceOfficer"})
    acct = get_account_or_404(account_id)
    check_account_ownership(acct, uid, role)
    limit, offset = H.get_pagination()
    rows = S.account_ledger(account_id)
    et = request.args.get("entry_type")
    bucket = request.args.get("bucket")
    if et:
        rows = [e for e in rows if e["entry_type"] == et]
    if bucket:
        rows = [e for e in rows if e["bucket"] == bucket]
    rows = H.sorted_by_created(rows)
    page, meta = H.paginate(rows, limit, offset)
    return success([S.serialize_ledger_entry(e) for e in page], pagination=meta)


@app.route("/ledger-entries", methods=["GET"])
def list_ledger_entries():
    H.require_auth({"ComplianceOfficer", "TradingOps"})
    limit, offset = H.get_pagination()
    rows = list(db.ledger_entries.values())
    ref_id = request.args.get("ref_id")
    account_id = request.args.get("account_id")
    if ref_id:
        rows = [e for e in rows if e["ref_id"] == ref_id]
    if account_id:
        rows = [e for e in rows if e["account_id"] == account_id]
    rows = H.sorted_by_created(rows)
    page, meta = H.paginate(rows, limit, offset)
    return success([S.serialize_ledger_entry(e) for e in page], pagination=meta)


@app.route("/ledger-entries/<entry_id>", methods=["GET"])
def read_ledger_entry(entry_id):
    H.require_auth({"ComplianceOfficer", "TradingOps"})
    e = db.ledger_entries.get(entry_id)
    if not e:
        raise err("ERR_NOT_FOUND", "Ledger entry not found")
    return success(S.serialize_ledger_entry(e))


# ---------------------------------------------------------------------------
# Geolocation
# ---------------------------------------------------------------------------
GEO_STATES = {"NJ", "NY", "PA", "CO", "AZ", "NV", "FL", "TX", "CA", "INTL"}


@app.route("/accounts/<account_id>/geo-checks", methods=["POST"])
def create_geo_check(account_id):
    uid, role = H.require_auth({"Bettor"})
    acct = get_account_or_404(account_id)
    check_account_ownership(acct, uid, role)
    body = H.get_json()

    H.require_fields(body, ["detected_state", "accuracy_meters"])
    state = body["detected_state"]
    H.require_enum(state, GEO_STATES, "detected_state")
    accuracy = body["accuracy_meters"]
    H.require_int(accuracy, "accuracy_meters")
    if accuracy < 0:
        raise err("ERR_INVALID_REQUEST", "accuracy_meters must be >= 0")
    vpn = body.get("is_vpn_suspected", False)
    if not isinstance(vpn, bool):
        raise err("ERR_INVALID_REQUEST", "is_vpn_suspected must be a boolean")

    eligible = (
        state in calc.PERMITTED_BET_STATES
        and accuracy <= calc.MAX_ACCURACY_M
        and not vpn
    )
    expires = clock.get() + timedelta(seconds=calc.GEO_TTL_SECONDS)

    rec = S.base_record(versioned=False)
    rec.update({
        "account_id": account_id,
        "detected_state": state,
        "accuracy_meters": accuracy,
        "is_vpn_suspected": vpn,
        "eligible": eligible,
        "expires_at": format_iso(expires),
    })
    db.geo_checks[rec["id"]] = rec
    return success(S.serialize_geo_check(rec), status=201)


@app.route("/accounts/<account_id>/geo-checks", methods=["GET"])
def list_geo_checks(account_id):
    uid, role = H.require_auth({"Bettor", "ComplianceOfficer"})
    acct = get_account_or_404(account_id)
    check_account_ownership(acct, uid, role)
    limit, offset = H.get_pagination()
    rows = [g for g in db.geo_checks.values() if g["account_id"] == account_id]
    rows = H.sorted_by_created(rows)
    page, meta = H.paginate(rows, limit, offset)
    return success([S.serialize_geo_check(g) for g in page], pagination=meta)


# ===========================================================================
# Events / Markets / Selections
# ===========================================================================
SPORTS = {"NFL", "NBA", "MLB", "SOCCER"}
MARKET_TYPES = {"MONEYLINE", "SPREAD", "TOTAL"}


@app.route("/events", methods=["POST"])
def create_event():
    H.require_auth({"TradingOps"})
    body = H.get_json()
    H.require_fields(body, ["sport", "home_team", "away_team", "starts_at"])
    H.require_enum(body["sport"], SPORTS, "sport")
    if not isinstance(body["home_team"], str) or body["home_team"] == "":
        raise err("ERR_INVALID_REQUEST", "home_team must be a non-empty string")
    if not isinstance(body["away_team"], str) or body["away_team"] == "":
        raise err("ERR_INVALID_REQUEST", "away_team must be a non-empty string")
    try:
        starts = parse_iso(body["starts_at"])
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "starts_at must be a valid ISO 8601 timestamp")

    rec = S.base_record(versioned=True)
    rec.update({
        "sport": body["sport"],
        "home_team": body["home_team"],
        "away_team": body["away_team"],
        "starts_at": format_iso(starts),
        "status": "SCHEDULED",
        "home_score": None,
        "away_score": None,
        "result_posted_by": None,
    })
    db.events[rec["id"]] = rec
    return success(S.serialize_event(rec), status=201)


@app.route("/events/<event_id>", methods=["GET"])
def read_event(event_id):
    H.require_auth({"TradingOps", "SettlementAgent", "Bettor"})
    e = get_event_or_404(event_id)
    return success(S.serialize_event(e))


@app.route("/events/<event_id>/status", methods=["POST"])
def event_status(event_id):
    H.require_auth({"TradingOps"})
    e = get_event_or_404(event_id)
    body = H.get_json()
    to = body.get("to")
    H.require_enum(to, {"LIVE", "VOIDED"}, "to")

    if to == "LIVE":
        if e["status"] != "SCHEDULED":
            raise err("ERR_INVALID_STATE", "Event must be SCHEDULED to go LIVE")
        e["status"] = "LIVE"
        # Suspend every OPEN market on this event (PRD §3.6).
        for m in db.markets.values():
            if m["event_id"] == event_id and m["status"] == "OPEN":
                m["status"] = "SUSPENDED"
                S.touch(m)
        S.touch(e)
    else:  # VOIDED
        if e["status"] not in ("SCHEDULED", "LIVE"):
            raise err("ERR_INVALID_STATE", "Event must be SCHEDULED or LIVE to be VOIDED")
        _void_event_cascade(e)
        S.touch(e)

    return success(S.serialize_event(e))


def _void_event_cascade(event):
    event["status"] = "VOIDED"
    # All markets -> VOIDED, all selections -> VOID (PRD §3.6).
    for m in db.markets.values():
        if m["event_id"] == event["id"] and m["status"] not in ("SETTLED", "VOIDED"):
            m["status"] = "VOIDED"
            m["current_liability_cents"] = 0
            S.touch(m)
        if m["event_id"] == event["id"]:
            for sel in db.selections.values():
                if sel["market_id"] == m["id"] and sel["result"] == "PENDING":
                    sel["result"] = "VOID"
                    S.touch(sel)
    # All PLACED bets with any leg on this event -> VOIDED, stake refunded.
    for bet in S.bets_touching_event(event["id"]):
        S.void_bet(bet)
    # Release liability on touched markets.
    for m in db.markets.values():
        if m["event_id"] == event["id"]:
            S.recompute_market_liability(m)


@app.route("/events/<event_id>/result", methods=["POST"])
def event_result(event_id):
    uid, role = H.require_auth({"SettlementAgent"})
    e = get_event_or_404(event_id)
    body = H.get_json()

    # State precondition: only LIVE events can be settled (PRD §3.10).
    if e["status"] != "LIVE":
        raise err("ERR_INVALID_STATE", "Event must be LIVE to post a result")

    home_score = body.get("home_score")
    away_score = body.get("away_score")
    if home_score is None or away_score is None:
        raise err("ERR_INVALID_REQUEST", "home_score and away_score are required")
    H.require_int(home_score, "home_score")
    H.require_int(away_score, "away_score")
    if home_score < 0 or away_score < 0:
        raise err("ERR_INVALID_REQUEST", "scores must be >= 0")

    # SoD: posting agent must differ from every Market.set_by on this event.
    for m in db.markets.values():
        if m["event_id"] == event_id and m.get("set_by") == uid:
            raise err("ERR_SOD_CONFLICT", "Settlement agent priced a market on this event")

    e["home_score"] = home_score
    e["away_score"] = away_score
    e["result_posted_by"] = uid
    e["status"] = "SETTLED"
    S.touch(e)

    _settle_event_cascade(e, home_score, away_score)
    return success(S.serialize_event(e))


def _settle_event_cascade(event, home_score, away_score):
    """Atomic grading cascade (PRD §3.10)."""
    # Stage 1+2: markets SETTLED, selections graded, leg_result mirrored.
    for m in db.markets.values():
        if m["event_id"] != event["id"]:
            continue
        if m["status"] in ("SETTLED", "VOIDED"):
            continue
        m["status"] = "SETTLED"
        m["current_liability_cents"] = 0
        S.touch(m)
        for sel in db.selections.values():
            if sel["market_id"] != m["id"]:
                continue
            if sel["result"] != "PENDING":
                continue
            grade = S.grade_selection(m, sel, home_score, away_score)
            sel["result"] = grade
            S.touch(sel)
            # Mirror into every leg on this selection.
            for leg in db.bet_legs.values():
                if leg["selection_id"] == sel["id"] and leg["leg_result"] == "PENDING":
                    leg["leg_result"] = grade

    # Stage 3+4: grade each bet whose legs are now all terminal.
    for bet in S.bets_touching_event(event["id"]):
        S.grade_bet_from_legs(bet)

    # Recompute remaining liabilities (settled markets released to 0).
    for m in db.markets.values():
        if m["event_id"] == event["id"]:
            S.recompute_market_liability(m)


@app.route("/events/<event_id>/markets", methods=["POST"])
def create_market(event_id):
    uid, role = H.require_auth({"TradingOps"})
    e = get_event_or_404(event_id)
    body = H.get_json()
    H.require_fields(body, ["market_type", "liability_cap_cents"])
    H.require_enum(body["market_type"], MARKET_TYPES, "market_type")
    cap = body["liability_cap_cents"]
    H.require_positive_int(cap, "liability_cap_cents")
    line = body.get("line")
    if line is not None and not isinstance(line, (int, float)):
        raise err("ERR_INVALID_REQUEST", "line must be a number")
    if isinstance(line, bool):
        raise err("ERR_INVALID_REQUEST", "line must be a number")

    rec = S.base_record(versioned=True)
    rec.update({
        "event_id": event_id,
        "market_type": body["market_type"],
        "line": line,
        "liability_cap_cents": cap,
        "current_liability_cents": 0,
        "status": "OPEN",
        "set_by": uid,
    })
    db.markets[rec["id"]] = rec
    return success(S.serialize_market(rec, recompute=False), status=201)


@app.route("/events/<event_id>/markets", methods=["GET"])
def list_event_markets(event_id):
    H.require_auth({"TradingOps", "SettlementAgent", "Bettor"})
    get_event_or_404(event_id)
    limit, offset = H.get_pagination()
    rows = [m for m in db.markets.values() if m["event_id"] == event_id]
    status = request.args.get("status")
    if status:
        rows = [m for m in rows if m["status"] == status]
    rows = H.sorted_by_created(rows)
    page, meta = H.paginate(rows, limit, offset)
    return success([S.serialize_market(m) for m in page], pagination=meta)


@app.route("/markets/<market_id>", methods=["GET"])
def read_market(market_id):
    H.require_auth({"TradingOps", "SettlementAgent", "Bettor"})
    m = get_market_or_404(market_id)
    return success(S.serialize_market(m))  # recomputes liability on read


@app.route("/markets/<market_id>/status", methods=["POST"])
def market_status(market_id):
    H.require_auth({"TradingOps"})
    m = get_market_or_404(market_id)
    body = H.get_json()
    to = body.get("to")
    H.require_enum(to, {"OPEN", "SUSPENDED"}, "to")

    if to == "SUSPENDED":
        if m["status"] != "OPEN":
            raise err("ERR_INVALID_STATE", "Only an OPEN market may be SUSPENDED")
        m["status"] = "SUSPENDED"
        S.touch(m)
    else:  # OPEN (reopen)
        if m["status"] != "SUSPENDED":
            raise err("ERR_INVALID_STATE", "Only a SUSPENDED market may be reopened")
        event = db.events.get(m["event_id"])
        if not event or event["status"] != "SCHEDULED":
            raise err("ERR_EVENT_LOCKED", "Market can only reopen while its event is SCHEDULED")
        S.recompute_market_liability(m)
        if m["current_liability_cents"] > m["liability_cap_cents"]:
            raise err("ERR_RISK_LIMIT_EXCEEDED", "Liability exceeds the cap")
        m["status"] = "OPEN"
        S.touch(m)

    return success(S.serialize_market(m, recompute=False))


@app.route("/markets/<market_id>/selections", methods=["POST"])
def create_selection(market_id):
    H.require_auth({"TradingOps"})
    m = get_market_or_404(market_id)
    body = H.get_json()
    H.require_fields(body, ["name", "american_odds"])
    if not isinstance(body["name"], str) or body["name"] == "":
        raise err("ERR_INVALID_REQUEST", "name must be a non-empty string")
    odds = body["american_odds"]
    H.require_int(odds, "american_odds")
    if odds == 0 or abs(odds) < 100:
        raise err("ERR_INVALID_REQUEST", "american_odds must be nonzero with magnitude >= 100")

    rec = S.base_record(versioned=True)
    rec.update({
        "market_id": market_id,
        "name": body["name"],
        "american_odds": odds,
        "decimal_odds": calc.american_to_decimal(odds),
        "result": "PENDING",
    })
    db.selections[rec["id"]] = rec
    return success(S.serialize_selection(rec), status=201)


@app.route("/markets/<market_id>/selections", methods=["GET"])
def list_market_selections(market_id):
    H.require_auth({"TradingOps", "SettlementAgent", "Bettor"})
    get_market_or_404(market_id)
    limit, offset = H.get_pagination()
    rows = [s for s in db.selections.values() if s["market_id"] == market_id]
    rows = H.sorted_by_created(rows)
    page, meta = H.paginate(rows, limit, offset)
    return success([S.serialize_selection(s) for s in page], pagination=meta)


@app.route("/selections/<selection_id>", methods=["GET"])
def read_selection(selection_id):
    H.require_auth({"TradingOps", "SettlementAgent", "Bettor"})
    s = get_selection_or_404(selection_id)
    return success(S.serialize_selection(s))


@app.route("/selections/<selection_id>", methods=["PATCH"])
def reprice_selection(selection_id):
    H.require_auth({"TradingOps"})
    s = get_selection_or_404(selection_id)
    body = H.get_json()
    H.require_fields(body, ["american_odds"])
    odds = body["american_odds"]
    H.require_int(odds, "american_odds")
    if odds == 0 or abs(odds) < 100:
        raise err("ERR_INVALID_REQUEST", "american_odds must be nonzero with magnitude >= 100")

    market = db.markets.get(s["market_id"])
    event = db.events.get(market["event_id"]) if market else None
    # Re-price only while market OPEN and event SCHEDULED (PRD §3.5).
    if not market or market["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Selection's market must be OPEN to re-price")
    if not event or event["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Selection's event must be SCHEDULED to re-price")

    s["american_odds"] = odds
    s["decimal_odds"] = calc.american_to_decimal(odds)
    S.touch(s)
    # Existing BetLeg snapshots are unchanged (immutable, PRD §3.5).
    return success(S.serialize_selection(s))


# ===========================================================================
# Bets
# ===========================================================================
@app.route("/bets", methods=["POST"])
def place_bet():
    uid, role = H.require_auth({"Bettor"})
    body = H.get_json()

    # account_id existence + ownership (priority 3/4).
    account_id = body.get("account_id")
    if account_id is None:
        raise err("ERR_INVALID_REQUEST", "account_id is required")
    acct = get_account_or_404(account_id)
    check_account_ownership(acct, uid, role)

    S.reeval_cooling_off(acct)

    # --- Field structural pre-reads needed for downstream checks. We defer the
    # lowest-priority ERR_INVALID_REQUEST surface until after compliance gates
    # (PRD §2.10), but bet_type / legs presence is needed to evaluate gates.
    bet_type = body.get("bet_type")
    legs_in = body.get("legs")
    stake_cents = body.get("stake_cents")
    stake_bucket = body.get("stake_bucket", "CASH")
    bonus_grant_id = body.get("bonus_grant_id")

    # Priority 6/7/8/9 RG + KYC + geo gates run before composition/limits.
    if acct["rg_status"] == "SELF_EXCLUDED":
        raise err("ERR_RG_SELF_EXCLUDED", "Account is self-excluded")
    if acct["rg_status"] == "COOLING_OFF":
        raise err("ERR_RG_COOLING_OFF", "Account is in a cooling-off period")
    if acct["kyc_status"] != "VERIFIED":
        raise err("ERR_KYC_NOT_VERIFIED", "Account must be KYC-verified")

    # Geo eligibility: latest geo-check eligible and unexpired (PRD §3.4).
    if not _geo_eligible(account_id):
        raise err("ERR_GEO_INELIGIBLE", "No unexpired eligible geo-check")

    # Validate bet_type / legs presence (needed for composition gate).
    H.require_enum(bet_type, {"SINGLE", "PARLAY", "SAME_GAME_PARLAY"}, "bet_type")
    if not isinstance(legs_in, list):
        raise err("ERR_INVALID_REQUEST", "legs must be an array")

    selection_ids = []
    for leg in legs_in:
        if not isinstance(leg, dict) or "selection_id" not in leg:
            raise err("ERR_INVALID_REQUEST", "each leg must have a selection_id")
        selection_ids.append(leg["selection_id"])

    # Resolve selections (existence -> 404). Empty legs handled by composition.
    selections = []
    for sid in selection_ids:
        selections.append(get_selection_or_404(sid))

    if bonus_grant_id is not None:
        grant = get_grant_or_404(bonus_grant_id)
        if grant["account_id"] != account_id:
            raise err("ERR_NOT_FOUND", "Bonus grant does not belong to this account")

    # Priority 10: every leg's market OPEN and event SCHEDULED with future start.
    now = clock.get()
    for sel in selections:
        market = db.markets.get(sel["market_id"])
        event = db.events.get(market["event_id"]) if market else None
        if not market or market["status"] != "OPEN":
            raise err("ERR_MARKET_NOT_OPEN", "A leg's market is not OPEN")
        if not event or event["status"] != "SCHEDULED":
            raise err("ERR_MARKET_NOT_OPEN", "A leg's event is not SCHEDULED")
        if parse_iso(event["starts_at"]) <= now:
            raise err("ERR_MARKET_NOT_OPEN", "A leg's event has already started")

    # Priority 11: composition matches bet_type.
    event_ids = set()
    market_ids = []
    for sel in selections:
        m = db.markets.get(sel["market_id"])
        market_ids.append(sel["market_id"])
        event_ids.add(m["event_id"])

    if bet_type == "SINGLE":
        if len(selections) != 1:
            raise err("ERR_PARLAY_COMPOSITION_INVALID", "SINGLE must have exactly one leg")
    elif bet_type == "PARLAY":
        if len(selections) < 2 or len(event_ids) < 2:
            raise err("ERR_PARLAY_COMPOSITION_INVALID", "PARLAY must span >= 2 distinct events")
    elif bet_type == "SAME_GAME_PARLAY":
        if len(selections) < 2 or len(event_ids) != 1:
            raise err("ERR_PARLAY_COMPOSITION_INVALID", "SGP legs must share one event")

    # Priority 12: duplicate legs / SGP same-market collision.
    if len(set(selection_ids)) != len(selection_ids):
        raise err("ERR_DUPLICATE_LEG", "Two legs reference the same selection")
    if bet_type == "SAME_GAME_PARLAY":
        if len(set(market_ids)) != len(market_ids):
            raise err("ERR_DUPLICATE_LEG", "SGP has two legs on the same market")

    # stake_cents structural check (positive int).
    if stake_cents is None:
        raise err("ERR_INVALID_REQUEST", "stake_cents is required")
    H.require_positive_int(stake_cents, "stake_cents")
    H.require_enum(stake_bucket, {"CASH", "BONUS"}, "stake_bucket")

    # Compute combined odds + potential payout (needed for limit/risk checks).
    leg_decimals = [sel["decimal_odds"] for sel in selections]
    combined = calc.combined_decimal_odds(leg_decimals)
    potential = calc.potential_payout(stake_cents, combined)

    # Priority 13: wager limit (gross window stake + new).
    wctrl = _active_control(account_id, "WAGER_LIMIT")
    if wctrl:
        window_start = clock.get() - timedelta(seconds=calc.period_seconds(wctrl["period"]))
        gross = 0
        for b in db.bets.values():
            if b["account_id"] != account_id:
                continue
            ts = parse_iso(b["created_at"])
            if window_start < ts <= now:
                gross += b["stake_cents"]
        if gross + stake_cents > wctrl["limit_cents"]:
            raise err("ERR_WAGER_LIMIT_EXCEEDED", "Wager limit exceeded")

    # Priority 14: net-loss limit (net realized loss + prospective stake).
    nctrl = _active_control(account_id, "NET_LOSS_LIMIT")
    if nctrl:
        window_start = clock.get() - timedelta(seconds=calc.period_seconds(nctrl["period"]))
        net_loss = 0
        for b in db.bets.values():
            if b["account_id"] != account_id:
                continue
            if b["status"] not in ("WON", "LOST", "PUSHED", "CASHED_OUT", "VOIDED"):
                continue
            if not b.get("settled_at"):
                continue
            ts = parse_iso(b["settled_at"])
            if window_start < ts <= now:
                net_loss += b["stake_cents"] - b["actual_payout_cents"]
        projected = net_loss + stake_cents
        if projected > nctrl["limit_cents"]:
            raise err("ERR_NET_LOSS_LIMIT_EXCEEDED", "Net-loss limit exceeded")

    # Priority 15: book risk cap — accepting this bet must not push any touched
    # market's current_liability above its cap.
    bet_net = potential - stake_cents
    distinct_markets = set(market_ids)
    for mid in distinct_markets:
        m = db.markets.get(mid)
        current = S.recompute_market_liability(m)
        if current + bet_net > m["liability_cap_cents"]:
            raise err("ERR_RISK_LIMIT_EXCEEDED", "Placement would breach market liability cap")

    # Priority 17: funds availability in the named bucket.
    if stake_bucket == "CASH":
        available = S.cash_balance(account_id)
    else:
        available = S.bonus_balance(account_id)
    if stake_cents > available:
        raise err("ERR_INSUFFICIENT_FUNDS", "Insufficient funds in the named bucket")

    # OCC last (PRD §2.6) — version must still match.
    check_occ(acct, body)

    # ----- Commit -----
    bet = S.base_record(versioned=True)
    bet.update({
        "account_id": account_id,
        "bet_type": bet_type,
        "stake_cents": stake_cents,
        "stake_bucket": stake_bucket,
        "combined_decimal_odds": combined,
        "potential_payout_cents": potential,
        "actual_payout_cents": 0,
        "bonus_grant_id": bonus_grant_id,
        "status": "PLACED",
        "settled_at": None,
    })
    db.bets[bet["id"]] = bet

    # Snapshot legs in submission order; created_at strictly increasing via _seq.
    for sel in selections:
        leg = S.base_record(versioned=False)
        leg.update({
            "bet_id": bet["id"],
            "selection_id": sel["id"],
            "odds_at_placement": sel["american_odds"],
            "decimal_odds_at_placement": sel["decimal_odds"],
            "leg_result": "PENDING",
        })
        db.bet_legs[leg["id"]] = leg

    # Debit stake.
    S.post_ledger(account_id, "STAKE", stake_bucket, -stake_cents,
                  ref_type="BET", ref_id=bet["id"])

    # Recompute touched-market liabilities; may auto-suspend (PRD §3.7).
    for mid in distinct_markets:
        m = db.markets.get(mid)
        S.recompute_market_liability(m)
        if m["status"] == "OPEN" and m["current_liability_cents"] > m["liability_cap_cents"]:
            m["status"] = "SUSPENDED"
            S.touch(m)

    S.touch(acct)
    return success(S.serialize_bet(bet), status=201)


def _geo_eligible(account_id):
    checks = [g for g in db.geo_checks.values() if g["account_id"] == account_id]
    if not checks:
        return False
    checks.sort(key=lambda g: (g["created_at"], g["_seq"]))
    latest = checks[-1]
    if not latest["eligible"]:
        return False
    return parse_iso(latest["expires_at"]) > clock.get()


@app.route("/bets/<bet_id>", methods=["GET"])
def read_bet(bet_id):
    uid, role = H.require_auth({"Bettor", "ComplianceOfficer", "TradingOps"})
    b = get_bet_or_404(bet_id)
    if role == "Bettor" and b["account_id"] != uid:
        raise err("ERR_FORBIDDEN", "Bettor may only read their own bets")
    return success(S.serialize_bet(b))


@app.route("/bets", methods=["GET"])
def list_bets():
    uid, role = H.require_auth({"Bettor", "ComplianceOfficer", "TradingOps"})
    limit, offset = H.get_pagination()
    rows = list(db.bets.values())
    if role == "Bettor":
        rows = [b for b in rows if b["account_id"] == uid]
    account_id = request.args.get("account_id")
    bonus_grant_id = request.args.get("bonus_grant_id")
    status = request.args.get("status")
    if account_id:
        rows = [b for b in rows if b["account_id"] == account_id]
    if bonus_grant_id:
        rows = [b for b in rows if b["bonus_grant_id"] == bonus_grant_id]
    if status:
        rows = [b for b in rows if b["status"] == status]
    rows = H.sorted_by_created(rows)
    page, meta = H.paginate(rows, limit, offset)
    return success([S.serialize_bet(b) for b in page], pagination=meta)


@app.route("/bets/<bet_id>/legs", methods=["GET"])
def list_bet_legs_of(bet_id):
    uid, role = H.require_auth({"Bettor", "ComplianceOfficer", "TradingOps"})
    b = get_bet_or_404(bet_id)
    if role == "Bettor" and b["account_id"] != uid:
        raise err("ERR_FORBIDDEN", "Bettor may only read their own bet legs")
    limit, offset = H.get_pagination()
    rows = S.legs_of_bet(bet_id)
    page, meta = H.paginate(rows, limit, offset)
    return success([S.serialize_bet_leg(l) for l in page], pagination=meta)


@app.route("/bet-legs", methods=["GET"])
def list_bet_legs():
    H.require_auth({"ComplianceOfficer", "TradingOps"})
    limit, offset = H.get_pagination()
    rows = list(db.bet_legs.values())
    selection_id = request.args.get("selection_id")
    bet_id = request.args.get("bet_id")
    if selection_id:
        rows = [l for l in rows if l["selection_id"] == selection_id]
    if bet_id:
        rows = [l for l in rows if l["bet_id"] == bet_id]
    rows = H.sorted_by_created(rows)
    page, meta = H.paginate(rows, limit, offset)
    return success([S.serialize_bet_leg(l) for l in page], pagination=meta)


@app.route("/bet-legs/<leg_id>", methods=["GET"])
def read_bet_leg(leg_id):
    H.require_auth({"ComplianceOfficer", "TradingOps"})
    l = db.bet_legs.get(leg_id)
    if not l:
        raise err("ERR_NOT_FOUND", "Bet leg not found")
    return success(S.serialize_bet_leg(l))


@app.route("/bets/<bet_id>/cash-out", methods=["POST"])
def cash_out(bet_id):
    uid, role = H.require_auth({"Bettor"})
    b = get_bet_or_404(bet_id)
    acct = get_account_or_404(b["account_id"])
    if b["account_id"] != uid:
        raise err("ERR_FORBIDDEN", "Bettor may only cash out their own bets")
    body = H.get_json()

    S.reeval_cooling_off(acct)

    # Priority 5: bet must be PLACED.
    if b["status"] != "PLACED":
        raise err("ERR_INVALID_STATE", "Only a PLACED bet may be cashed out")

    legs = S.legs_of_bet(bet_id)
    # No leg already graded (selection still PENDING) -> ERR_LEG_ALREADY_GRADED.
    for leg in legs:
        sel = db.selections.get(leg["selection_id"])
        if leg["leg_result"] != "PENDING" or (sel and sel["result"] != "PENDING"):
            raise err("ERR_LEG_ALREADY_GRADED", "A leg has already graded")

    # No leg's market SUSPENDED nor event LIVE/SETTLED -> ERR_CASHOUT_UNAVAILABLE.
    for leg in legs:
        sel = db.selections.get(leg["selection_id"])
        market = db.markets.get(sel["market_id"]) if sel else None
        event = db.events.get(market["event_id"]) if market else None
        if not market or market["status"] == "SUSPENDED":
            raise err("ERR_CASHOUT_UNAVAILABLE", "A leg's market is suspended")
        if not event or event["status"] in ("LIVE", "SETTLED"):
            raise err("ERR_CASHOUT_UNAVAILABLE", "A leg's event is live or settled")

    # OCC.
    check_occ(acct, body)

    # Cash-out value at CURRENT odds * retention (PRD §3.9).
    current_decimals = []
    for leg in legs:
        sel = db.selections.get(leg["selection_id"])
        current_decimals.append(calc.american_to_decimal(sel["american_odds"]))
    value = calc.cash_out_value(b["stake_cents"], current_decimals)

    b["actual_payout_cents"] = value
    b["status"] = "CASHED_OUT"
    b["settled_at"] = iso_now()
    S.post_ledger(b["account_id"], "CASHOUT", "CASH", value, ref_type="BET", ref_id=b["id"])

    # Release market liability (bet no longer PLACED).
    for mid in S.markets_touched_by_bet(b):
        m = db.markets.get(mid)
        if m:
            S.recompute_market_liability(m)

    S.touch(b)
    S.touch(acct)
    return success(S.serialize_bet(b))


# ===========================================================================
# Promotions & Bonuses
# ===========================================================================
@app.route("/promotions", methods=["POST"])
def create_promotion():
    H.require_auth({"TradingOps"})
    body = H.get_json()
    H.require_fields(body, ["code", "bonus_cents", "wagering_multiplier", "max_claims"])
    code = body["code"]
    if not isinstance(code, str) or code.strip() == "":
        raise err("ERR_INVALID_REQUEST", "code must be a non-empty string")
    for p in db.promotions.values():
        if p["code"] == code:
            raise err("ERR_INVALID_REQUEST", "code must be unique")
    bonus_cents = body["bonus_cents"]
    H.require_positive_int(bonus_cents, "bonus_cents")
    mult = body["wagering_multiplier"]
    H.require_int(mult, "wagering_multiplier")
    if mult < 1:
        raise err("ERR_INVALID_REQUEST", "wagering_multiplier must be >= 1")
    max_claims = body["max_claims"]
    H.require_int(max_claims, "max_claims")
    if max_claims < 1:
        raise err("ERR_INVALID_REQUEST", "max_claims must be >= 1")
    min_odds = body.get("min_odds_american", -200)
    H.require_int(min_odds, "min_odds_american")
    if min_odds == 0 or abs(min_odds) < 100:
        raise err("ERR_INVALID_REQUEST", "min_odds_american must be nonzero, magnitude >= 100")

    rec = S.base_record(versioned=True)
    rec.update({
        "code": code,
        "bonus_cents": bonus_cents,
        "wagering_multiplier": mult,
        "min_odds_american": min_odds,
        "max_claims": max_claims,
        "status": "ACTIVE",
    })
    db.promotions[rec["id"]] = rec
    return success(S.serialize_promotion(rec), status=201)


@app.route("/promotions/<promotion_id>", methods=["GET"])
def read_promotion(promotion_id):
    H.require_auth({"TradingOps", "Bettor", "ComplianceOfficer"})
    p = get_promotion_or_404(promotion_id)
    return success(S.serialize_promotion(p))


@app.route("/promotions", methods=["GET"])
def list_promotions():
    H.require_auth({"TradingOps", "Bettor", "ComplianceOfficer"})
    limit, offset = H.get_pagination()
    rows = list(db.promotions.values())
    status = request.args.get("status")
    if status:
        rows = [p for p in rows if _promo_status(p) == status]
    rows = H.sorted_by_created(rows)
    page, meta = H.paginate(rows, limit, offset)
    return success([S.serialize_promotion(p) for p in page], pagination=meta)


def _promo_status(p):
    """Derive EXHAUSTED when claims_used == max_claims unless ENDED (PRD §3.11)."""
    if p["status"] == "ENDED":
        return "ENDED"
    if S.claims_used(p["id"]) >= p["max_claims"]:
        return "EXHAUSTED"
    return "ACTIVE"


@app.route("/accounts/<account_id>/bonus-claims", methods=["POST"])
def claim_bonus(account_id):
    uid, role = H.require_auth({"Bettor"})
    acct = get_account_or_404(account_id)
    check_account_ownership(acct, uid, role)
    body = H.get_json()

    promotion_id = body.get("promotion_id")
    if promotion_id is None:
        raise err("ERR_INVALID_REQUEST", "promotion_id is required")
    promo = get_promotion_or_404(promotion_id)

    S.reeval_cooling_off(acct)

    # RG + KYC gates (PRD §3.11): self-excluded then KYC.
    if acct["rg_status"] == "SELF_EXCLUDED":
        raise err("ERR_RG_SELF_EXCLUDED", "Account is self-excluded")
    if acct["kyc_status"] != "VERIFIED":
        raise err("ERR_KYC_NOT_VERIFIED", "Account must be KYC-verified")

    # Promo availability (PRD §3.11): ACTIVE, claims_used < max, not already held.
    if _promo_status(promo) != "ACTIVE":
        raise err("ERR_PROMO_UNAVAILABLE", "Promotion is not claimable")
    if S.claims_used(promo["id"]) >= promo["max_claims"]:
        raise err("ERR_PROMO_UNAVAILABLE", "Promotion is exhausted")
    for g in db.bonus_grants.values():
        if g["account_id"] == account_id and g["promotion_id"] == promotion_id:
            raise err("ERR_PROMO_UNAVAILABLE", "Promotion already claimed by this account")

    check_occ(acct, body)

    grant = S.base_record(versioned=True)
    grant.update({
        "account_id": account_id,
        "promotion_id": promotion_id,
        "bonus_cents": promo["bonus_cents"],
        "wagering_target_cents": promo["bonus_cents"] * promo["wagering_multiplier"],
        "wagering_progress_cents": 0,
        "status": "ACTIVE",
    })
    db.bonus_grants[grant["id"]] = grant

    S.post_ledger(account_id, "BONUS_GRANT", "BONUS", promo["bonus_cents"],
                  ref_type="BONUS_GRANT", ref_id=None)

    # claims_used is derived; EXHAUSTED flips automatically. Persist explicit
    # EXHAUSTED status too for consistency with the stored field.
    if S.claims_used(promo["id"]) >= promo["max_claims"] and promo["status"] == "ACTIVE":
        promo["status"] = "EXHAUSTED"
        S.touch(promo)

    S.touch(acct)
    return success(S.serialize_bonus_grant(grant), status=201)


@app.route("/bonus-grants/<grant_id>", methods=["GET"])
def read_bonus_grant(grant_id):
    uid, role = H.require_auth({"Bettor", "ComplianceOfficer"})
    g = get_grant_or_404(grant_id)
    if role == "Bettor" and g["account_id"] != uid:
        raise err("ERR_FORBIDDEN", "Bettor may only read their own grants")
    return success(S.serialize_bonus_grant(g))


@app.route("/bonus-grants", methods=["GET"])
def list_bonus_grants():
    uid, role = H.require_auth({"Bettor", "ComplianceOfficer", "TradingOps"})
    limit, offset = H.get_pagination()
    rows = list(db.bonus_grants.values())
    if role == "Bettor":
        rows = [g for g in rows if g["account_id"] == uid]
    account_id = request.args.get("account_id")
    promotion_id = request.args.get("promotion_id")
    status = request.args.get("status")
    if account_id:
        rows = [g for g in rows if g["account_id"] == account_id]
    if promotion_id:
        rows = [g for g in rows if g["promotion_id"] == promotion_id]
    if status:
        rows = [g for g in rows if g["status"] == status]
    rows = H.sorted_by_created(rows)
    page, meta = H.paginate(rows, limit, offset)
    return success([S.serialize_bonus_grant(g) for g in page], pagination=meta)


def _patch_getfqdn_fast():
    """Neutralize the macOS reverse-DNS stall in socket.getfqdn("0.0.0.0").

    Werkzeug's dev server calls socket.getfqdn(host) during server_bind purely
    to compose its "Running on http://..." startup log line. On macOS,
    getfqdn("0.0.0.0") blocks ~5s on a reverse-DNS (PTR) lookup that has no
    answer for the unspecified address. Under per-test-server isolation the
    server reboots before every test, so that 5s stall is paid hundreds of
    times and, under the concurrent stability sweep, pushes a boot past the
    15s restart-poll window and surfaces as a spurious "could not be restarted".

    We short-circuit only the unspecified-address cases to "localhost"; named
    addresses fall through to the real resolver unchanged, and the result is
    used for nothing but the cosmetic startup log line. This is self-contained
    so the fast boot does not depend on any externally injected sitecustomize.
    """
    import socket
    _real = socket.getfqdn
    _unspecified = {"", "0.0.0.0", "::", "0:0:0:0:0:0:0:0"}

    def _fast(name=""):
        if name in _unspecified:
            return "localhost"
        return _real(name)

    socket.getfqdn = _fast


if __name__ == "__main__":
    _patch_getfqdn_fast()
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
