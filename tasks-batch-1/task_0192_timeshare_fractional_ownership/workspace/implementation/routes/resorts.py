"""Resort, clock, and rollover routes."""
from db import db, stamp_create, touch
from errors import err
import errors
from middleware import get_user_context, require_role
from response import success
from routes.common import get_or_404, get_json, list_response
from services.util import (
    serialize,
    require_str,
    require_int,
    parse_iso,
)
from services.cascade import grace_elapsed, open_delinquency_case_for


EPOCH_UTC = "1970-01-01T00:00:00.000Z"


def serialize_resort(resort):
    return serialize(resort)


def register(app):
    @app.route("/resorts", methods=["POST"])
    def create_resort():
        _, role = get_user_context()
        require_role(role, ["ResortManager"])
        data = get_json()
        name = require_str(data, "name")
        points_per_week_base = require_int(data, "points_per_week_base")
        annual_fee = require_int(data, "annual_fee_cents_per_1000_points")

        resort = {
            "name": name,
            "points_per_week_base": points_per_week_base,
            "annual_fee_cents_per_1000_points": annual_fee,
            "rescission_days": _opt_int(data, "rescission_days", 7),
            "borrow_surcharge_pct": _opt_num(data, "borrow_surcharge_pct", 0.10),
            "delinquency_grace_days": _opt_int(data, "delinquency_grace_days", 30),
            "foreclosure_threshold_periods": _opt_int(data, "foreclosure_threshold_periods", 2),
            "current_use_year": 2026,
            "current_utc": EPOCH_UTC,
        }
        stamp_create(resort)
        db.resorts[resort["id"]] = resort
        return success(serialize_resort(resort), status=201)

    @app.route("/resorts/<resort_id>", methods=["GET"])
    def get_resort(resort_id):
        _, role = get_user_context()
        require_role(role, ["ResortManager", "Owner", "ResaleAgent", "ComplianceOfficer"])
        resort = get_or_404(db.resorts, resort_id)
        return success(serialize_resort(resort))

    @app.route("/resorts/<resort_id>/rollover-use-year", methods=["POST"])
    def rollover_use_year(resort_id):
        _, role = get_user_context()
        require_role(role, ["ResortManager", "System"])
        resort = get_or_404(db.resorts, resort_id)
        closing_year = resort["current_use_year"]
        resort["current_use_year"] = closing_year + 1
        touch(resort)

        # Sweep 1: roll OPEN PointsAccounts in the closing year.
        from services.calc import annual_full_fee  # noqa: F401 (kept local to avoid cycles)
        accts = [
            a
            for a in db.points_accounts.values()
            if a["use_year"] == closing_year and a["status"] == "OPEN"
        ]
        for acct in accts:
            acct["status"] = "ROLLED_OVER"
            touch(acct)
            _ensure_next_year_account(
                acct["contract_id"], closing_year + 1, carry_banked_in=acct["banked_out_points"]
            )

        # Sweep 2: expire still-HELD reservations on the closing year.
        for res in db.reservations.values():
            if res["use_year"] == closing_year and res["status"] == "HELD":
                res["status"] = "EXPIRED"
                touch(res)

        # Sweep 3: mark grace-expired ISSUED invoices DELINQUENT (system), open cases.
        for inv in db.invoices.values():
            if inv["status"] != "ISSUED":
                continue
            from services.computed import invoice_amount_due

            if invoice_amount_due(inv) <= 0:
                continue
            if not grace_elapsed(resort, inv):
                continue
            contract = db.contracts.get(inv["contract_id"])
            if contract is None or contract["resort_id"] != resort_id:
                continue
            inv["status"] = "DELINQUENT"
            touch(inv)
            open_delinquency_case_for(contract, inv)

        return success(serialize_resort(resort))

    @app.route("/_clock/set_current_utc", methods=["POST"])
    def set_clock():
        _, role = get_user_context()
        require_role(role, ["ResortManager", "System"])
        data = get_json()
        resort_id = require_str(data, "resort_id")
        to_iso = require_str(data, "to_iso8601")
        # Validate parseable timestamp.
        try:
            parse_iso(to_iso)
        except Exception:
            raise err(errors.ERR_INVALID_REQUEST, "to_iso8601 is not a valid ISO 8601 timestamp.")
        resort = get_or_404(db.resorts, resort_id)
        resort["current_utc"] = to_iso
        touch(resort)
        return success(serialize_resort(resort))


def _opt_int(data, field, default):
    if data.get(field) is None:
        return default
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be an integer." % field)
    return v


def _opt_num(data, field, default):
    if data.get(field) is None:
        return default
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err(errors.ERR_INVALID_REQUEST, "Field %s must be a number." % field)
    return v


def _ensure_next_year_account(contract_id, use_year, carry_banked_in=0):
    """Open (or fetch) the next-year PointsAccount for a contract during rollover.

    The PRD seeds banked_in_points by carrying the closing account's
    banked_out_points ONLY when the next-year account is freshly opened here.
    If the next-year account already exists (e.g. created earlier by banking,
    which already transferred banked_in at bank time), do not carry again to
    avoid double-counting."""
    for a in db.points_accounts.values():
        if a["contract_id"] == contract_id and a["use_year"] == use_year:
            return a
    contract = db.contracts.get(contract_id)
    allotment = contract["annual_points_allotment"] if contract else 0
    acct = {
        "contract_id": contract_id,
        "use_year": use_year,
        "allotment_points": allotment,
        "banked_in_points": carry_banked_in,
        "banked_out_points": 0,
        "borrowed_out_points": 0,
        "committed_points": 0,
        "status": "OPEN",
    }
    stamp_create(acct)
    db.points_accounts[acct["id"]] = acct
    return acct
