"""Membership drives, phone bank shifts, premiums, and pledges (PRD 3.9)."""

import response
from db import db, new_row, ordered, touch
from errors import ApiError
from middleware import (
    ROLE_DEVELOPMENT_COORDINATOR,
    ROLE_PROGRAM_DIRECTOR,
    ROLE_VOLUNTEER,
    authenticate,
    body,
    bool_field,
    bool_query,
    datetime_field,
    enum_field,
    int_field,
    lookup,
    optional_lookup,
    str_field,
    str_query,
)
from services import calc, domain
from services import serializers as ser

SHIFT_OUTCOMES = ("COMPLETED", "NO_SHOW")
PAYMENT_OUTCOMES = ("PAID", "LAPSED")
FULFILLMENT_ACTIONS = ("SHIP", "WAIVE")
OCCUPYING_SHIFT_STATUSES = ("SCHEDULED", "COMPLETED")

DRIVE_READ_ROLES = (ROLE_PROGRAM_DIRECTOR, ROLE_DEVELOPMENT_COORDINATOR, ROLE_VOLUNTEER)
DEV_READ_ROLES = (ROLE_PROGRAM_DIRECTOR, ROLE_DEVELOPMENT_COORDINATOR)


def _drive_shifts(drive_id):
    return [
        s for s in db.shifts.values()
        if s["drive_id"] == drive_id and s["status"] in OCCUPYING_SHIFT_STATUSES
    ]


def _phone_line_available(drive, start_at, end_at):
    """Line occupancy uses half-open windows: a shift ending exactly when the
    next begins does not consume the same line."""
    active = _drive_shifts(drive["id"])
    instants = [start_at] + [s["start_at"] for s in active if start_at <= s["start_at"] < end_at]
    for instant in instants:
        busy = sum(1 for s in active if s["start_at"] <= instant < s["end_at"])
        if busy + 1 > drive["phone_line_count"]:
            return False
    return True


def _volunteer_shift_conflict(volunteer_id, start_at, end_at):
    """A volunteer's own shifts are compared as closed intervals: touching
    endpoints do conflict."""
    for shift in db.shifts.values():
        if shift["volunteer_id"] != volunteer_id:
            continue
        if shift["status"] not in OCCUPYING_SHIFT_STATUSES:
            continue
        if start_at <= shift["end_at"] and shift["start_at"] <= end_at:
            return True
    return False


def register(app):
    # ----------------------------------------------------------------- drives
    @app.post("/membership-drives")
    def create_drive():
        authenticate(ROLE_DEVELOPMENT_COORDINATOR)
        data = body()
        name = str_field(data, "name", non_empty=True)
        goal_cents = int_field(data, "goal_cents", 1, None)
        phone_line_count = int_field(data, "phone_line_count", 1, None)
        start_at = datetime_field(data, "start_at")
        end_at = datetime_field(data, "end_at")
        if end_at <= start_at:
            raise ApiError("ERR_INVALID_INTERVAL")
        drive = new_row(db.drives, {
            "name": name,
            "goal_cents": goal_cents,
            "start_at": start_at,
            "end_at": end_at,
            "phone_line_count": phone_line_count,
            "status": "PLANNED",
        })
        return response.created(ser.drive(drive))

    @app.get("/membership-drives")
    def list_drives():
        authenticate(*DRIVE_READ_ROLES)
        status = str_query("status")
        return response.listing(
            ordered(db.drives, lambda r: status is None or r["status"] == status),
            ser.drive,
        )

    @app.get("/membership-drives/<drive_id>")
    def get_drive(drive_id):
        authenticate(*DRIVE_READ_ROLES)
        drive = lookup(db.drives, drive_id, "ERR_DRIVE_NOT_FOUND")
        return response.obj(ser.drive(drive))

    @app.post("/membership-drives/<drive_id>/activate")
    def activate_drive(drive_id):
        authenticate(ROLE_DEVELOPMENT_COORDINATOR)
        drive = lookup(db.drives, drive_id, "ERR_DRIVE_NOT_FOUND")
        if drive["status"] != "PLANNED":
            raise ApiError("ERR_INVALID_STATE", "Only a planned drive can be opened.")
        drive["status"] = "ACTIVE"
        touch(drive)
        return response.obj(ser.drive(drive))

    @app.post("/membership-drives/<drive_id>/close")
    def close_drive(drive_id):
        authenticate(ROLE_DEVELOPMENT_COORDINATOR)
        drive = lookup(db.drives, drive_id, "ERR_DRIVE_NOT_FOUND")
        if drive["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", "Only an active drive can be closed.")
        if any(p["payment_status"] == "PENDING" for p in calc.drive_pledges(drive["id"])):
            raise ApiError("ERR_PLEDGES_PENDING")
        drive["status"] = "CLOSED"
        touch(drive)
        for shift in db.shifts.values():
            if shift["drive_id"] == drive["id"] and shift["status"] == "SCHEDULED":
                shift["status"] = "CANCELLED"
                touch(shift)
        return response.obj(ser.drive(drive))

    # ----------------------------------------------------------------- shifts
    @app.post("/phone-bank-shifts")
    def create_shift():
        authenticate(ROLE_DEVELOPMENT_COORDINATOR)
        data = body()
        drive_id = str_field(data, "drive_id")
        volunteer_id = str_field(data, "volunteer_id")
        start_at = datetime_field(data, "start_at")
        end_at = datetime_field(data, "end_at")
        if end_at <= start_at:
            raise ApiError("ERR_INVALID_INTERVAL")
        drive = lookup(db.drives, drive_id, "ERR_DRIVE_NOT_FOUND")
        volunteer = lookup(db.volunteers, volunteer_id, "ERR_VOLUNTEER_NOT_FOUND")
        if drive["status"] != "ACTIVE":
            raise ApiError("ERR_DRIVE_NOT_ACTIVE")
        if volunteer["status"] in ("SUSPENDED", "RESIGNED"):
            raise ApiError("ERR_VOLUNTEER_NOT_ELIGIBLE")
        if start_at < drive["start_at"] or end_at > drive["end_at"]:
            raise ApiError("ERR_SHIFT_OUTSIDE_DRIVE_WINDOW")
        if _volunteer_shift_conflict(volunteer["id"], start_at, end_at):
            raise ApiError("ERR_SHIFT_CONFLICT")
        if not _phone_line_available(drive, start_at, end_at):
            raise ApiError("ERR_PHONE_LINE_CAPACITY")
        shift = new_row(db.shifts, {
            "drive_id": drive["id"],
            "volunteer_id": volunteer["id"],
            "start_at": start_at,
            "end_at": end_at,
            "status": "SCHEDULED",
            "pledges_taken_count": 0,
        })
        return response.created(ser.shift(shift))

    @app.get("/phone-bank-shifts")
    def list_shifts():
        authenticate(*DRIVE_READ_ROLES)
        drive_id = str_query("drive_id")
        volunteer_id = str_query("volunteer_id")
        status = str_query("status")

        def keep(row):
            if drive_id is not None and row["drive_id"] != drive_id:
                return False
            if volunteer_id is not None and row["volunteer_id"] != volunteer_id:
                return False
            if status is not None and row["status"] != status:
                return False
            return True

        return response.listing(ordered(db.shifts, keep), ser.shift)

    @app.get("/phone-bank-shifts/<shift_id>")
    def get_shift(shift_id):
        authenticate(*DRIVE_READ_ROLES)
        shift = lookup(db.shifts, shift_id, "ERR_SHIFT_NOT_FOUND")
        return response.obj(ser.shift(shift))

    @app.post("/phone-bank-shifts/<shift_id>/close")
    def close_shift(shift_id):
        authenticate(ROLE_DEVELOPMENT_COORDINATOR)
        data = body()
        outcome = enum_field(data, "outcome", SHIFT_OUTCOMES)
        shift = lookup(db.shifts, shift_id, "ERR_SHIFT_NOT_FOUND")
        if shift["status"] != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE", "Only a scheduled shift can be closed out.")
        if outcome == "COMPLETED":
            shift["status"] = "COMPLETED"
            shift["pledges_taken_count"] = sum(
                1 for p in db.pledges.values() if p["shift_id"] == shift["id"]
            )
            touch(shift)
        else:
            shift["status"] = "NO_SHOW"
            touch(shift)
            volunteer = db.volunteers.get(shift["volunteer_id"])
            if volunteer is not None:
                domain.add_strike(volunteer)
        return response.obj(ser.shift(shift))

    # --------------------------------------------------------------- premiums
    @app.post("/premium-items")
    def create_premium():
        authenticate(ROLE_DEVELOPMENT_COORDINATOR)
        data = body()
        sku = str_field(data, "sku", non_empty=True)
        name = str_field(data, "name", non_empty=True)
        tier_threshold_cents = int_field(data, "tier_threshold_cents", 1, None)
        fair_market_value_cents = int_field(data, "fair_market_value_cents", 0, None)
        units_received_qty = int_field(data, "units_received_qty", 0, None)
        for row in db.premiums.values():
            if row["sku"] == sku:
                raise ApiError("ERR_DUPLICATE_KEY", "A premium item with that sku already exists.")
        item = new_row(db.premiums, {
            "sku": sku,
            "name": name,
            "tier_threshold_cents": tier_threshold_cents,
            "fair_market_value_cents": fair_market_value_cents,
            "units_received_qty": units_received_qty,
            "on_hand_qty": units_received_qty,
            "reserved_qty": 0,
            "shipped_qty": 0,
        })
        return response.created(ser.premium(item))

    @app.get("/premium-items")
    def list_premiums():
        authenticate(*DEV_READ_ROLES)
        status = str_query("status")
        sku = str_query("sku")

        def keep(row):
            if status is not None and calc.premium_status(row) != status:
                return False
            if sku is not None and row["sku"] != sku:
                return False
            return True

        return response.listing(ordered(db.premiums, keep), ser.premium)

    @app.get("/premium-items/<premium_item_id>")
    def get_premium(premium_item_id):
        authenticate(*DEV_READ_ROLES)
        item = lookup(db.premiums, premium_item_id, "ERR_PREMIUM_NOT_FOUND")
        return response.obj(ser.premium(item))

    @app.post("/premium-items/<premium_item_id>/receipts")
    def receive_premium(premium_item_id):
        authenticate(ROLE_DEVELOPMENT_COORDINATOR)
        data = body()
        received_qty = int_field(data, "received_qty", 1, None)
        item = lookup(db.premiums, premium_item_id, "ERR_PREMIUM_NOT_FOUND")
        item["units_received_qty"] += received_qty
        item["on_hand_qty"] += received_qty
        touch(item)
        return response.obj(ser.premium(item))

    # ---------------------------------------------------------------- pledges
    @app.post("/pledges")
    def create_pledge():
        authenticate(ROLE_DEVELOPMENT_COORDINATOR)
        data = body()
        drive_id = str_field(data, "drive_id")
        donor_name = str_field(data, "donor_name", non_empty=True)
        amount_cents = int_field(data, "amount_cents", 1, None)
        shift_id = str_field(data, "shift_id", required=False, default=None)
        wants_premium = bool_field(data, "wants_premium", required=False, default=True)

        drive = lookup(db.drives, drive_id, "ERR_DRIVE_NOT_FOUND")
        shift = optional_lookup(db.shifts, shift_id, "ERR_SHIFT_NOT_FOUND")
        if shift is not None and shift["drive_id"] != drive["id"]:
            raise ApiError("ERR_SHIFT_DRIVE_MISMATCH")
        if drive["status"] != "ACTIVE":
            raise ApiError("ERR_DRIVE_NOT_ACTIVE")

        premium_item_id, premium_status, deductible = domain.run_premium_waterfall(
            amount_cents, wants_premium
        )
        pledge = new_row(db.pledges, {
            "drive_id": drive["id"],
            "shift_id": shift["id"] if shift is not None else None,
            "premium_item_id": premium_item_id,
            "donor_name": donor_name,
            "amount_cents": amount_cents,
            "wants_premium": wants_premium,
            "payment_status": "PENDING",
            "premium_status": premium_status,
            "tax_deductible_cents": deductible,
        })
        touch(drive)
        return response.created(ser.pledge(pledge))

    @app.get("/pledges")
    def list_pledges():
        authenticate(*DEV_READ_ROLES)
        drive_id = str_query("drive_id")
        payment_status = str_query("payment_status")
        premium_status = str_query("premium_status")
        shift_id = str_query("shift_id")
        premium_item_id = str_query("premium_item_id")

        def keep(row):
            if drive_id is not None and row["drive_id"] != drive_id:
                return False
            if payment_status is not None and row["payment_status"] != payment_status:
                return False
            if premium_status is not None and row["premium_status"] != premium_status:
                return False
            if shift_id is not None and row["shift_id"] != shift_id:
                return False
            if premium_item_id is not None and row["premium_item_id"] != premium_item_id:
                return False
            return True

        return response.listing(ordered(db.pledges, keep), ser.pledge)

    @app.get("/pledges/<pledge_id>")
    def get_pledge(pledge_id):
        authenticate(*DEV_READ_ROLES)
        pledge = lookup(db.pledges, pledge_id, "ERR_PLEDGE_NOT_FOUND")
        return response.obj(ser.pledge(pledge))

    @app.post("/pledges/<pledge_id>/payment")
    def settle_pledge(pledge_id):
        authenticate(ROLE_DEVELOPMENT_COORDINATOR)
        data = body()
        outcome = enum_field(data, "outcome", PAYMENT_OUTCOMES)
        pledge = lookup(db.pledges, pledge_id, "ERR_PLEDGE_NOT_FOUND")
        if pledge["payment_status"] != "PENDING":
            raise ApiError("ERR_INVALID_STATE", "Only a pending pledge can be settled.")
        if outcome == "PAID":
            pledge["payment_status"] = "PAID"
        else:
            pledge["payment_status"] = "LAPSED"
            domain.release_reserved_premium(pledge)
        touch(pledge)
        touch(db.drives.get(pledge["drive_id"]))
        return response.obj(ser.pledge(pledge))

    @app.post("/pledges/<pledge_id>/refund")
    def refund_pledge(pledge_id):
        authenticate(ROLE_DEVELOPMENT_COORDINATOR)
        pledge = lookup(db.pledges, pledge_id, "ERR_PLEDGE_NOT_FOUND")
        if pledge["payment_status"] != "PAID":
            raise ApiError("ERR_INVALID_STATE", "Only a paid pledge can be refunded.")
        pledge["payment_status"] = "REFUNDED"
        if pledge["premium_status"] == "SHIPPED":
            domain.return_shipped_premium(pledge)
        elif pledge["premium_status"] == "RESERVED":
            domain.release_reserved_premium(pledge)
        touch(pledge)
        touch(db.drives.get(pledge["drive_id"]))
        return response.obj(ser.pledge(pledge))

    @app.post("/pledges/<pledge_id>/premium-fulfillment")
    def fulfil_premium(pledge_id):
        authenticate(ROLE_DEVELOPMENT_COORDINATOR)
        data = body()
        action = enum_field(data, "action", FULFILLMENT_ACTIONS)
        pledge = lookup(db.pledges, pledge_id, "ERR_PLEDGE_NOT_FOUND")
        if pledge["premium_status"] != "RESERVED":
            raise ApiError("ERR_PREMIUM_NOT_RESERVED")
        item = db.premiums.get(pledge["premium_item_id"])
        if action == "SHIP":
            if pledge["payment_status"] != "PAID":
                raise ApiError("ERR_PLEDGE_NOT_PAID")
            if item is None or item["on_hand_qty"] < 1:
                raise ApiError("ERR_PREMIUM_OUT_OF_STOCK")
            item["reserved_qty"] = max(0, item["reserved_qty"] - 1)
            item["on_hand_qty"] -= 1
            item["shipped_qty"] += 1
            touch(item)
            pledge["premium_status"] = "SHIPPED"
        else:
            if item is not None:
                item["reserved_qty"] = max(0, item["reserved_qty"] - 1)
                touch(item)
            pledge["premium_status"] = "WAIVED"
        touch(pledge)
        return response.obj(ser.pledge(pledge))
