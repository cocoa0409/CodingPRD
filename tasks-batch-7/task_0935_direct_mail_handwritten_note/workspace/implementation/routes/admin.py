"""Clock, accounts, escrow top-ups, blackout calendar, styles, machines, lots."""
from flask import Blueprint, request

import enums
import envelope
import serial
import services
import store
from errors import ApiError
from ladder import Ctx
from model import new_row, touch
from store import db

bp = Blueprint("admin", __name__)


# ------------------------------------------------------------------- clock
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    ctx = Ctx(["PlatformAdmin"])
    ctx.fields(required=[("to_iso8601", "datetime")])
    ctx.run()
    db.clock = store.parse_instant(ctx.body["to_iso8601"])
    return envelope.object_response({"current_utc": store.render_instant(db.clock)}, 200)


# ---------------------------------------------------------------- accounts
@bp.route("/mail/accounts", methods=["POST"])
def create_account():
    ctx = Ctx(["PlatformAdmin"])
    ctx.fields(required=[("name", "str"), ("permit_number", "str")],
               optional=[("status", "str")])
    ctx.enums([("status", enums.ACCOUNT_STATUS)])
    ctx.at(6, lambda: _require_non_empty(ctx, "permit_number"))
    ctx.at(26, lambda: _unique(db.accounts, "permit_number", ctx.body.get("permit_number")))
    ctx.run()
    row = new_row({
        "name": ctx.body["name"],
        "permit_number": ctx.body["permit_number"],
        "status": ctx.body.get("status") or "ACTIVE",
    })
    db.accounts[row["id"]] = row
    return envelope.object_response(serial.account(row), 201)


def _require_non_empty(ctx, field):
    value = ctx.body.get(field)
    if isinstance(value, str) and value.strip() == "":
        raise ApiError("ERR_VALIDATION", "Field '%s' may not be empty." % field)


def _unique(collection, field, value, scope_field=None, scope_value=None):
    for row in collection.values():
        if scope_field is not None and row.get(scope_field) != scope_value:
            continue
        if row.get(field) == value:
            raise ApiError("ERR_DUPLICATE_KEY")


@bp.route("/mail/accounts/<account_id>", methods=["GET"])
def get_account(account_id):
    ctx = Ctx(["PlatformAdmin", "AccountOwner", "CampaignManager", "ComplianceOfficer"])
    ctx.path("account", account_id)
    ctx.scope(lambda: ctx.get("account")["id"])
    ctx.run()
    return envelope.object_response(serial.account(ctx.get("account")), 200)


@bp.route("/mail/accounts/<account_id>/postage-topups", methods=["POST"])
def postage_topup(account_id):
    ctx = Ctx(["PlatformAdmin", "AccountOwner"])
    ctx.path("account", account_id)
    ctx.scope(lambda: ctx.get("account")["id"])
    ctx.fields(required=[("amount_cents", "int")], optional=[("reason", "str")])
    ctx.ranges([("amount_cents", 1, None, False)])
    ctx.run()
    account = ctx.get("account")
    services.append_ledger(account["id"], "TOPUP", ctx.body["amount_cents"],
                           ctx.body.get("reason") or "postage top-up")
    touch(account)
    return envelope.object_response(serial.account(account), 201)


# -------------------------------------------------------- blackout calendar
@bp.route("/mail/blackout-dates", methods=["POST"])
def create_blackout():
    ctx = Ctx(["PlatformAdmin", "CampaignManager"])
    ctx.fields(required=[("blackout_date", "date"), ("reason", "str")])
    ctx.at(26, lambda: _unique(db.blackout_dates, "blackout_date",
                               store.parse_date(ctx.body.get("blackout_date"))))
    ctx.run()
    row = new_row({
        "blackout_date": store.parse_date(ctx.body["blackout_date"]),
        "reason": ctx.body["reason"],
    }, common=False)
    db.blackout_dates[row["id"]] = row
    return envelope.object_response(serial.blackout_date(row), 201)


@bp.route("/mail/blackout-dates", methods=["GET"])
def list_blackouts():
    ctx = Ctx(["PlatformAdmin", "CampaignManager", "ProductionOperator"])
    ctx.run()
    rows = list(db.blackout_dates.values())
    wanted = request.args.get("blackout_date")
    if wanted is not None:
        target = store.parse_date(wanted)
        rows = [r for r in rows if r["blackout_date"] == target]
    rows = envelope.sort_rows(rows)
    page, limit, offset, total = envelope.paginate(rows, request.args)
    return envelope.list_response([serial.blackout_date(r) for r in page], limit, offset, total)


# ------------------------------------------------------- handwriting styles
@bp.route("/mail/handwriting-styles", methods=["POST"])
def create_style():
    ctx = Ctx(["PlatformAdmin", "ProductionOperator"])
    ctx.fields(required=[("name", "str"), ("pen_type", "str"), ("ink_type", "str"),
                         ("chars_per_minute", "int"), ("ink_ul_per_1000_chars", "num")])
    ctx.enums([("pen_type", enums.PEN_TYPES), ("ink_type", enums.INK_TYPES)])
    ctx.ranges([("chars_per_minute", 1, None, False),
                ("ink_ul_per_1000_chars", 0, None, True)])
    ctx.run()
    row = new_row({
        "name": ctx.body["name"],
        "pen_type": ctx.body["pen_type"],
        "ink_type": ctx.body["ink_type"],
        "chars_per_minute": ctx.body["chars_per_minute"],
        "ink_ul_per_1000_chars": ctx.body["ink_ul_per_1000_chars"],
    })
    db.handwriting_styles[row["id"]] = row
    return envelope.object_response(serial.handwriting_style(row), 201)


# ---------------------------------------------------------------- machines
@bp.route("/mail/machines", methods=["POST"])
def create_machine():
    ctx = Ctx(["PlatformAdmin", "ProductionOperator"])
    ctx.fields(required=[("machine_code", "str")],
               optional=[("daily_capacity_minutes", "int"), ("status", "str")])
    ctx.enums([("status", enums.MACHINE_STATUS)])
    ctx.ranges([("daily_capacity_minutes", 1, None, False)])
    ctx.at(26, lambda: _unique(db.machines, "machine_code", ctx.body.get("machine_code")))
    ctx.run()
    capacity = ctx.body.get("daily_capacity_minutes")
    row = new_row({
        "machine_code": ctx.body["machine_code"],
        "daily_capacity_minutes": (capacity if capacity is not None
                                   else store.DEFAULT_MACHINE_DAILY_CAPACITY_MINUTES),
        "status": ctx.body.get("status") or "ONLINE",
    })
    db.machines[row["id"]] = row
    return envelope.object_response(serial.machine(row), 201)


@bp.route("/mail/machines/<machine_id>", methods=["GET"])
def get_machine(machine_id):
    ctx = Ctx(["PlatformAdmin", "ProductionOperator"])
    ctx.path("machine", machine_id)
    ctx.run()
    return envelope.object_response(serial.machine(ctx.get("machine")), 200)


# ---------------------------------------------------------------- ink lots
@bp.route("/mail/ink-lots", methods=["POST"])
def create_ink_lot():
    ctx = Ctx(["PlatformAdmin", "ProductionOperator"])
    ctx.fields(required=[("lot_code", "str"), ("ink_type", "str"),
                         ("initial_volume_ul", "int")])
    ctx.enums([("ink_type", enums.INK_TYPES)])
    ctx.ranges([("initial_volume_ul", 1, None, False)])
    ctx.at(26, lambda: _unique(db.ink_lots, "lot_code", ctx.body.get("lot_code")))
    ctx.run()
    row = new_row({
        "lot_code": ctx.body["lot_code"],
        "ink_type": ctx.body["ink_type"],
        "initial_volume_ul": ctx.body["initial_volume_ul"],
        "remaining_ul": ctx.body["initial_volume_ul"],
        "status": "SEALED",
    })
    db.ink_lots[row["id"]] = row
    return envelope.object_response(serial.ink_lot(row), 201)


@bp.route("/mail/ink-lots/<ink_lot_id>", methods=["GET"])
def get_ink_lot(ink_lot_id):
    ctx = Ctx(["PlatformAdmin", "ProductionOperator"])
    ctx.path("ink_lot", ink_lot_id)
    ctx.run()
    return envelope.object_response(serial.ink_lot(ctx.get("ink_lot")), 200)


@bp.route("/mail/ink-lots/<ink_lot_id>/quarantine", methods=["POST"])
def quarantine_ink_lot(ink_lot_id):
    ctx = Ctx(["PlatformAdmin", "ProductionOperator"])
    ctx.path("ink_lot", ink_lot_id)
    ctx.fields(optional=[("reason", "str")])
    ctx.at(21, lambda: _lot_state(ctx.get("ink_lot"), ("SEALED", "OPEN")))
    ctx.run()
    lot = ctx.get("ink_lot")
    lot["status"] = "QUARANTINED"
    touch(lot)
    return envelope.object_response(serial.ink_lot(lot), 200)


@bp.route("/mail/ink-lots/<ink_lot_id>/release", methods=["POST"])
def release_ink_lot(ink_lot_id):
    ctx = Ctx(["PlatformAdmin", "ProductionOperator"])
    ctx.path("ink_lot", ink_lot_id)
    ctx.at(21, lambda: _lot_state(ctx.get("ink_lot"), ("QUARANTINED",)))
    ctx.run()
    lot = ctx.get("ink_lot")
    lot["status"] = "OPEN"
    touch(lot)
    return envelope.object_response(serial.ink_lot(lot), 200)


def _lot_state(lot, allowed):
    if lot["status"] not in allowed:
        raise ApiError("ERR_INK_LOT_UNAVAILABLE")
