"""Member service: CRUD, lifecycle transitions with cascade effects."""
from errors import ApiError
import db
from db import store, new_common, touch


def create_member(body):
    required = ["legal_name", "member_type", "district_id"]
    for field in required:
        if field not in body:
            raise ApiError("ERR_INVALID_REQUEST", 400, f"Missing required field: {field}")
    if body["member_type"] not in ("RESIDENTIAL", "COMMERCIAL", "IRRIGATION"):
        raise ApiError("ERR_INVALID_REQUEST", 400, "member_type must be RESIDENTIAL, COMMERCIAL, or IRRIGATION")
    member = new_common({
        "legal_name": body["legal_name"],
        "member_type": body["member_type"],
        "status": "APPLICANT",
        "joined_at": None,
        "terminated_at": None,
        "capital_credit_balance_cents": 0,
        "unclaimed_credit_cents": 0,
        "patronage_base_kwh": 0,
        "patronage_base_irrigation_kwh": 0,
        "deposit_cents": 0,
        "district_id": body["district_id"],
    })
    store.members[member["id"]] = member
    return member


def get_member(member_id):
    m = store.members.get(member_id)
    if not m:
        raise ApiError("ERR_NOT_FOUND", 404, "Member not found")
    return m


def list_members(status=None, district_id=None):
    rows = list(store.members.values())
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    if district_id is not None:
        rows = [r for r in rows if str(r.get("district_id")) == str(district_id)]
    return rows


def _member_locations(member_id):
    return [sl for sl in store.service_locations.values() if sl.get("member_id") == member_id]


def _member_invoices(member_id):
    loc_ids = {sl["id"] for sl in _member_locations(member_id)}
    return [inv for inv in store.invoices.values() if inv.get("service_location_id") in loc_ids]


def _member_devices(member_id):
    loc_ids = {sl["id"] for sl in _member_locations(member_id)}
    return [d for d in store.load_management_devices.values() if d.get("service_location_id") in loc_ids]


def activate_member(member_id):
    member = get_member(member_id)
    if member["status"] != "APPLICANT":
        raise ApiError("ERR_INVALID_STATE", 409, "Member must be in APPLICANT to activate")
    locs = _member_locations(member_id)
    has_valid = any(l["status"] in ("PENDING_CONSTRUCTION", "ENERGIZED") for l in locs)
    if not has_valid:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Member has no ServiceLocation in PENDING_CONSTRUCTION or ENERGIZED")
    member["status"] = "ACTIVE"
    member["joined_at"] = db.wall_now()
    touch(member)
    return member


def suspend_member(member_id):
    member = get_member(member_id)
    if member["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Member must be ACTIVE to suspend")
    invoices = _member_invoices(member_id)
    if any(inv["status"] == "PROVISIONAL" for inv in invoices):
        raise ApiError("ERR_MEMBER_PROVISIONAL_INVOICE", 409,
                       "Member has a PROVISIONAL invoice; suspend blocked")
    member["status"] = "SUSPENDED"
    touch(member)
    # Cascade: devices ENROLLED/ACTIVE -> SUSPENDED
    for dev in _member_devices(member_id):
        if dev["status"] in ("ENROLLED", "ACTIVE"):
            dev["status"] = "SUSPENDED"
            touch(dev)
    return member


def reinstate_member(member_id):
    member = get_member(member_id)
    if member["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", 409, "Member must be SUSPENDED to reinstate")
    invoices = _member_invoices(member_id)
    if any(inv["status"] == "FINALIZED" for inv in invoices):
        raise ApiError("ERR_MEMBER_PAST_DUE", 409,
                       "Member has unpaid FINALIZED invoices; reinstate blocked")
    member["status"] = "ACTIVE"
    touch(member)
    # Cascade: devices SUSPENDED -> ACTIVE
    for dev in _member_devices(member_id):
        if dev["status"] == "SUSPENDED":
            dev["status"] = "ACTIVE"
            touch(dev)
    return member


def terminate_member(member_id):
    member = get_member(member_id)
    if member["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Member must be ACTIVE or SUSPENDED to terminate")
    invoices = _member_invoices(member_id)
    if member["status"] == "ACTIVE":
        if any(inv["status"] == "PROVISIONAL" for inv in invoices):
            raise ApiError("ERR_MEMBER_UNPAID_FINAL", 409,
                           "Member has a PROVISIONAL invoice; terminate blocked")
        if any(inv["status"] == "FINALIZED" for inv in invoices):
            raise ApiError("ERR_MEMBER_UNPAID_FINAL", 409,
                           "Member has unpaid FINALIZED invoice; terminate blocked")
    elif member["status"] == "SUSPENDED":
        if any(inv["status"] == "FINALIZED" for inv in invoices):
            raise ApiError("ERR_MEMBER_UNPAID_FINAL", 409,
                           "Member has unpaid FINALIZED invoice; terminate blocked")

    member["status"] = "TERMINATED"
    member["terminated_at"] = db.wall_now()
    touch(member)

    # Cascade: locations ENERGIZED -> DISCONNECTED
    for loc in _member_locations(member_id):
        if loc["status"] == "ENERGIZED":
            loc["status"] = "DISCONNECTED"
            touch(loc)

    # Cascade: devices ENROLLED/ACTIVE/SUSPENDED -> UNENROLLED
    for dev in _member_devices(member_id):
        if dev["status"] in ("ENROLLED", "ACTIVE", "SUSPENDED"):
            dev["status"] = "UNENROLLED"
            touch(dev)

    # Cascade: payouts ISSUED -> UNCLAIMED
    for payout in store.capital_credit_payouts.values():
        if payout.get("member_id") == member_id and payout.get("status") == "ISSUED":
            payout["status"] = "UNCLAIMED"
            member["unclaimed_credit_cents"] = member.get("unclaimed_credit_cents", 0) + payout["payout_cents"]
            touch(payout)

    return member
