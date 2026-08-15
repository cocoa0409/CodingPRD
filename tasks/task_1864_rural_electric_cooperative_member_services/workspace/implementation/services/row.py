"""RightOfWayAgreement service."""
from errors import ApiError
import db
from db import store, new_common, touch


def create_row(body):
    required = ["service_location_id", "easement_width_ft"]
    for field in required:
        if field not in body:
            raise ApiError("ERR_INVALID_REQUEST", 400, f"Missing required field: {field}")
    loc = store.service_locations.get(body["service_location_id"])
    if not loc:
        raise ApiError("ERR_NOT_FOUND", 404, "ServiceLocation not found")

    row = new_common({
        "service_location_id": body["service_location_id"],
        "status": "REQUESTED",
        "easement_width_ft": body["easement_width_ft"],
        "consented_at": None,
        "recorded_at": None,
    })
    store.right_of_way_agreements[row["id"]] = row
    return row


def get_row(row_id):
    r = store.right_of_way_agreements.get(row_id)
    if not r:
        raise ApiError("ERR_NOT_FOUND", 404, "RightOfWayAgreement not found")
    return r


def list_rows(service_location_id=None, status=None):
    rows = list(store.right_of_way_agreements.values())
    if service_location_id is not None:
        rows = [r for r in rows if r.get("service_location_id") == service_location_id]
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    return rows


def _check_member_ownership(row, user_id):
    """Check that the acting Member owns the location."""
    loc = store.service_locations.get(row["service_location_id"])
    if not loc:
        raise ApiError("ERR_NOT_FOUND", 404, "ServiceLocation not found")
    if loc.get("member_id") != user_id:
        raise ApiError("ERR_FORBIDDEN", 403, "Member acting on a resource they do not own")
    return loc


def consent_row(row_id, user_id):
    row = get_row(row_id)
    # §2.8 priority: entity-backed ownership (fourth) is evaluated before
    # state validity (fifth).
    loc = _check_member_ownership(row, user_id)
    if row["status"] not in ("REQUESTED", "CONTESTED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "ROW must be REQUESTED or CONTESTED to consent")

    # Check member is ACTIVE
    member = store.members.get(loc["member_id"])
    if not member or member["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Member must be ACTIVE to consent")

    row["status"] = "MEMBER_CONSENTED"
    row["consented_at"] = db.wall_now()
    touch(row)
    return row


def record_row(row_id):
    row = get_row(row_id)
    if row["status"] != "MEMBER_CONSENTED":
        raise ApiError("ERR_INVALID_STATE", 409, "ROW must be MEMBER_CONSENTED to record")
    row["status"] = "RECORDED"
    row["recorded_at"] = db.wall_now()
    touch(row)
    return row


def contest_row(row_id, user_id):
    row = get_row(row_id)
    # §2.8 priority: ownership (fourth) before state validity (fifth).
    _check_member_ownership(row, user_id)
    if row["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "ROW must be REQUESTED to contest")
    row["status"] = "CONTESTED"
    touch(row)
    return row


def condemn_row(row_id):
    row = get_row(row_id)
    if row["status"] != "CONTESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "ROW must be CONTESTED to condemn")
    row["status"] = "CONDEMNATION"
    touch(row)
    return row


def release_row(row_id):
    row = get_row(row_id)
    if row["status"] != "MEMBER_CONSENTED":
        raise ApiError("ERR_INVALID_STATE", 409, "ROW must be MEMBER_CONSENTED to release")
    row["status"] = "RELEASED"
    touch(row)
    return row
