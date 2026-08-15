"""LoadManagementDevice service."""
from errors import ApiError
import db
from db import store, new_common, touch


def create_device(body, user_id, user_role):
    required = ["service_location_id", "device_type"]
    for field in required:
        if field not in body:
            raise ApiError("ERR_INVALID_REQUEST", 400, f"Missing required field: {field}")

    loc = store.service_locations.get(body["service_location_id"])
    if not loc:
        raise ApiError("ERR_NOT_FOUND", 404, "ServiceLocation not found")

    # Member role can only enroll for own locations
    if user_role == "Member":
        if loc.get("member_id") != user_id:
            raise ApiError("ERR_FORBIDDEN", 403, "Member acting on a resource they do not own")

    if body["device_type"] not in ("WATER_HEATER", "IRRIGATION_INTERRUPTIBLE", "AC_CYCLER"):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Invalid device_type")

    dev = new_common({
        "service_location_id": body["service_location_id"],
        "device_type": body["device_type"],
        "status": "ENROLLED",
        "enrolled_at": db.wall_now(),
        "monthly_credit_cents": 0,
    })
    store.load_management_devices[dev["id"]] = dev
    return dev


def get_device(dev_id):
    d = store.load_management_devices.get(dev_id)
    if not d:
        raise ApiError("ERR_NOT_FOUND", 404, "LoadManagementDevice not found")
    return d


def list_devices(service_location_id=None, status=None):
    rows = list(store.load_management_devices.values())
    if service_location_id is not None:
        rows = [r for r in rows if r.get("service_location_id") == service_location_id]
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    return rows


def activate_device(dev_id):
    dev = get_device(dev_id)
    if dev["status"] != "ENROLLED":
        raise ApiError("ERR_INVALID_STATE", 409, "Device must be ENROLLED to activate")

    loc = store.service_locations.get(dev["service_location_id"])
    if not loc:
        raise ApiError("ERR_NOT_FOUND", 404, "ServiceLocation not found")

    if loc["status"] != "ENERGIZED":
        raise ApiError("ERR_INVALID_STATE", 409, "ServiceLocation must be ENERGIZED")

    if dev["device_type"] == "IRRIGATION_INTERRUPTIBLE" and loc["rate_class"] != "IRRIGATION":
        raise ApiError("ERR_LMD_RATE_CLASS_MISMATCH", 409,
                       "IRRIGATION_INTERRUPTIBLE device on a non-IRRIGATION service location")

    # Snapshot monthly_credit_cents from current PUBLISHED RateSchedule
    from services.rate_schedule import find_published_schedule
    schedule = find_published_schedule(loc["rate_class"], db.logical_now())
    if schedule:
        dev["monthly_credit_cents"] = schedule.get("load_management_credit_cents", 0)
    else:
        dev["monthly_credit_cents"] = 0

    dev["status"] = "ACTIVE"
    dev["_active_since"] = db.wall_now()
    touch(dev)
    return dev


def suspend_device(dev_id):
    dev = get_device(dev_id)
    if dev["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Device must be ACTIVE to suspend")
    dev["_suspended_at"] = db.wall_now()
    dev["status"] = "SUSPENDED"
    touch(dev)
    return dev


def reactivate_device(dev_id):
    dev = get_device(dev_id)
    if dev["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", 409, "Device must be SUSPENDED to reactivate")

    loc = store.service_locations.get(dev["service_location_id"])
    if not loc:
        raise ApiError("ERR_NOT_FOUND", 404, "ServiceLocation not found")

    member = store.members.get(loc["member_id"])
    if not member or member["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Member must be ACTIVE")

    if loc["status"] != "ENERGIZED":
        raise ApiError("ERR_INVALID_STATE", 409, "ServiceLocation must be ENERGIZED")

    dev["status"] = "ACTIVE"
    dev["_active_since"] = db.wall_now()
    dev.pop("_suspended_at", None)
    touch(dev)
    return dev


def unenroll_device(dev_id, user_id):
    dev = get_device(dev_id)
    if dev["status"] not in ("ENROLLED", "ACTIVE"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Device must be ENROLLED or ACTIVE to unenroll")

    loc = store.service_locations.get(dev["service_location_id"])
    if not loc:
        raise ApiError("ERR_NOT_FOUND", 404, "ServiceLocation not found")
    if loc.get("member_id") != user_id:
        raise ApiError("ERR_FORBIDDEN", 403, "Member acting on a resource they do not own")

    dev["status"] = "UNENROLLED"
    touch(dev)
    return dev
