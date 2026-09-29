"""Guest-facing programmes and the custody of guest property -- PRD 3.9."""

from flask import Blueprint, request

import derive
from auth import FRONT_DESK_AGENT, ROOM_ATTENDANT, SUPERVISOR, authenticate
from envelope import created, filtered, ok, paginate
from errors import ApiError
from serialize import enrollment_out, lost_found_out
from store import STORE, base_record, touch
from validate import read_body, venum, vint, vstr

bp = Blueprint("guest", __name__)


# ---------------------------------------------------------------------------
# Lost and found
# ---------------------------------------------------------------------------

@bp.post("/housekeeping/lost-found-items")
def create_lost_found_item():
    authenticate((SUPERVISOR, ROOM_ATTENDANT))
    body = read_body()
    property_id = vstr(body, "property_id", 1, None)
    room_id = vstr(body, "room_id", 1, None)
    found_by_attendant_id = vstr(body, "found_by_attendant_id", 1, None)
    description = vstr(body, "description", 1, 240)
    category = venum(body, "category", derive.LOST_FOUND_CATEGORIES)

    prop = derive.get_property(STORE, property_id)
    room = derive.get_room(STORE, room_id)
    finder = derive.get_attendant(STORE, found_by_attendant_id)

    if room["property_id"] != prop["id"]:
        raise ApiError(
            "ERR_PROPERTY_SCOPE_MISMATCH",
            "Room %s belongs to another property." % room["id"],
        )
    if finder["property_id"] != prop["id"]:
        raise ApiError(
            "ERR_PROPERTY_SCOPE_MISMATCH",
            "Attendant %s belongs to another property." % finder["id"],
        )

    row = base_record(STORE)
    row.update({
        "property_id": prop["id"],
        "room_id": room["id"],
        "found_by_attendant_id": finder["id"],
        "description": description,
        "category": category,
        "logged_at": STORE.now(),
        "storage_bin": None,
        "stored_at": None,
        "retention_days": None,
        "retention_expires_at": None,
        "status": "LOGGED",
        "claimant_name": None,
        "claimant_contact": None,
        "proof_kind": None,
        "claim_attempt_count": 0,
        "denial_reason": None,
        "tracking_code": None,
    })
    STORE.lost_found_items[row["id"]] = row
    return created(lost_found_out(STORE, row))


@bp.get("/housekeeping/lost-found-items/<iid>")
def read_lost_found_item(iid):
    authenticate(None)
    row = derive.get_lost_found_item(STORE, iid)
    return ok(lost_found_out(STORE, row))


@bp.get("/housekeeping/lost-found-items")
def list_lost_found_items():
    authenticate(None)
    rows = filtered(
        list(STORE.lost_found_items.values()),
        request.args,
        {
            "property_id": ("property_id", None),
            "room_id": ("room_id", None),
            "found_by_attendant_id": ("found_by_attendant_id", None),
            "status": ("status", None),
            "category": ("category", None),
        },
    )
    return paginate(rows, request.args, lambda r: lost_found_out(STORE, r))


@bp.post("/housekeeping/lost-found-items/<iid>/store")
def store_lost_found_item(iid):
    authenticate((SUPERVISOR, FRONT_DESK_AGENT))
    body = read_body()
    storage_bin = vstr(body, "storage_bin", 1, 32)

    item = derive.get_lost_found_item(STORE, iid)
    if item["status"] != "LOGGED":
        raise ApiError("ERR_ITEM_NOT_LOGGED", "Item is not in LOGGED.")

    stored_at = STORE.now()
    retention_days, expires_at = derive.retention_window(item["category"], stored_at)
    item["storage_bin"] = storage_bin
    item["stored_at"] = stored_at
    item["retention_days"] = retention_days
    item["retention_expires_at"] = expires_at
    item["status"] = "STORED"
    touch(STORE, item)
    return ok(lost_found_out(STORE, item))


@bp.post("/housekeeping/lost-found-items/<iid>/claim")
def claim_lost_found_item(iid):
    authenticate((FRONT_DESK_AGENT,))
    body = read_body()
    claimant_name = vstr(body, "claimant_name", 1, 120)
    # An empty contact string is accepted here; it is the SHIPPED disposition that
    # later insists on a non-empty one.
    claimant_contact = vstr(body, "claimant_contact", 0, 160)
    proof_kind = venum(body, "proof_kind", derive.PROOF_KINDS)

    item = derive.get_lost_found_item(STORE, iid)
    if item["status"] != "STORED":
        raise ApiError("ERR_ITEM_NOT_STORED", "Item is not in STORED.")

    # The retention window is half-open: the boundary instant belongs to disposal.
    if item["retention_expires_at"] is not None and STORE.now() >= item["retention_expires_at"]:
        raise ApiError("ERR_RETENTION_EXPIRED", "The retention window has closed.")

    if item["category"] in ("HIGH_VALUE", "ID_DOCUMENT") and proof_kind not in (
        "PHOTO_ID", "RECEIPT",
    ):
        raise ApiError(
            "ERR_PROOF_INSUFFICIENT",
            "A %s item requires PHOTO_ID or RECEIPT proof." % item["category"],
        )

    item["claimant_name"] = claimant_name
    item["claimant_contact"] = claimant_contact
    item["proof_kind"] = proof_kind
    item["claim_attempt_count"] = item["claim_attempt_count"] + 1
    item["status"] = "CLAIM_PENDING"
    touch(STORE, item)
    return ok(lost_found_out(STORE, item))


CLAIM_DECISIONS = ("APPROVE", "DENY", "APPROVE_PICKUP", "APPROVE_SHIP")


@bp.post("/housekeeping/lost-found-items/<iid>/claim-decision")
def decide_lost_found_claim(iid):
    authenticate((SUPERVISOR,))
    body = read_body()
    decision = venum(body, "decision", CLAIM_DECISIONS)
    disposition = venum(
        body, "disposition", ("RELEASED", "SHIPPED"), required=False, default=None
    )
    tracking_code = vstr(body, "tracking_code", 1, 64, required=False, default=None)
    denial_reason = vstr(body, "denial_reason", 1, 240, required=False, default=None)

    item = derive.get_lost_found_item(STORE, iid)
    if item["status"] != "CLAIM_PENDING":
        raise ApiError("ERR_CLAIM_NOT_PENDING", "Item is not in CLAIM_PENDING.")

    if decision == "DENY":
        if denial_reason is None:
            raise ApiError("ERR_INVALID_REQUEST", "denial_reason is required on a denial.")
        # The retention clock keeps running, so a second claimant may still file.
        item["denial_reason"] = denial_reason
        item["claimant_name"] = None
        item["claimant_contact"] = None
        item["status"] = "STORED"
        touch(STORE, item)
        return ok(lost_found_out(STORE, item))

    # The combined decision values name their own disposition.
    if decision == "APPROVE_PICKUP":
        disposition = "RELEASED"
    elif decision == "APPROVE_SHIP":
        disposition = "SHIPPED"
    if disposition is None:
        raise ApiError(
            "ERR_DISPOSITION_NOT_PERMITTED",
            "An approval must name a disposition of RELEASED or SHIPPED.",
        )

    if disposition == "SHIPPED":
        if not item["claimant_contact"]:
            raise ApiError(
                "ERR_DISPOSITION_NOT_PERMITTED",
                "A SHIPPED disposition requires a non-empty claimant_contact.",
            )
        if tracking_code is None:
            raise ApiError(
                "ERR_INVALID_REQUEST", "tracking_code is required on a shipment."
            )
        item["tracking_code"] = tracking_code
        item["status"] = "SHIPPED"
    else:
        item["status"] = "RELEASED"

    # The item has left the property either way.
    item["storage_bin"] = None
    touch(STORE, item)
    return ok(lost_found_out(STORE, item))


@bp.post("/housekeeping/lost-found-items/<iid>/dispose")
def dispose_lost_found_item(iid):
    authenticate((SUPERVISOR,))
    body = read_body()
    disposition = venum(body, "disposition", ("DISPOSED", "DONATED"))

    item = derive.get_lost_found_item(STORE, iid)
    if item["status"] != "STORED":
        raise ApiError("ERR_ITEM_NOT_STORED", "Item is not in STORED.")
    if item["retention_expires_at"] is not None and STORE.now() < item["retention_expires_at"]:
        raise ApiError("ERR_RETENTION_ACTIVE", "The retention window is still open.")
    if disposition == "DONATED" and item["category"] not in ("STANDARD", "PERISHABLE"):
        raise ApiError(
            "ERR_DISPOSITION_NOT_PERMITTED",
            "A %s item may never be donated." % item["category"],
        )

    item["status"] = disposition
    item["storage_bin"] = None
    touch(STORE, item)
    return ok(lost_found_out(STORE, item))


# ---------------------------------------------------------------------------
# Service enrolments
# ---------------------------------------------------------------------------

@bp.post("/housekeeping/service-enrollments")
def create_enrollment():
    authenticate((FRONT_DESK_AGENT,))
    body = read_body()
    room_id = vstr(body, "room_id", 1, None)
    reservation_code = vstr(body, "reservation_code", 1, 32)
    program = venum(body, "program", derive.ENROLLMENT_PROGRAMS)
    nights = vint(body, "nights", 1, 60)

    room = derive.get_room(STORE, room_id)

    for existing in STORE.enrollments.values():
        if existing["room_id"] == room["id"] and existing["status"] == "ACTIVE":
            raise ApiError(
                "ERR_ENROLLMENT_ACTIVE_EXISTS",
                "Room %s already holds an ACTIVE enrolment." % room["room_number"],
            )

    row = base_record(STORE)
    row.update({
        "room_id": room["id"],
        "reservation_code": reservation_code,
        "program": program,
        "nights": nights,
        "points_per_skip": derive.POINTS_PER_SKIP[program],
        "skips_accrued": 0,
        "points_accrued": 0,
        "status": "ACTIVE",
    })
    STORE.enrollments[row["id"]] = row

    # Enrolling rewrites the room, which is exactly what activates the opt-out and
    # cadence gates of PRD 3.4.
    room["service_program"] = program
    touch(STORE, room)
    return created(enrollment_out(STORE, row))


@bp.get("/housekeeping/service-enrollments/<eid>")
def read_enrollment(eid):
    authenticate(None)
    row = derive.get_enrollment(STORE, eid)
    return ok(enrollment_out(STORE, row))


@bp.get("/housekeeping/service-enrollments")
def list_enrollments():
    authenticate(None)
    rows = filtered(
        list(STORE.enrollments.values()),
        request.args,
        {
            "room_id": ("room_id", None),
            "status": ("status", None),
            "program": ("program", None),
        },
    )
    return paginate(rows, request.args, lambda r: enrollment_out(STORE, r))


@bp.post("/housekeeping/service-enrollments/<eid>/accrue")
def accrue_enrollment(eid):
    authenticate((SUPERVISOR, FRONT_DESK_AGENT))
    enrollment = derive.get_enrollment(STORE, eid)
    if enrollment["status"] != "ACTIVE":
        raise ApiError("ERR_ENROLLMENT_NOT_ACTIVE", "Enrolment is not ACTIVE.")

    budget = derive.skip_budget(enrollment["program"], enrollment["nights"])
    if enrollment["skips_accrued"] >= budget:
        raise ApiError(
            "ERR_ENROLLMENT_SKIPS_EXHAUSTED",
            "The skip budget of %d has been exhausted." % budget,
        )

    enrollment["skips_accrued"] = enrollment["skips_accrued"] + 1
    enrollment["points_accrued"] = (
        enrollment["skips_accrued"] * enrollment["points_per_skip"]
    )
    # An OPT_OUT enrolment reaches COMPLETED on its last budgeted accrual; an
    # EVERY_OTHER_DAY one exhausts its budget while still ACTIVE.
    if enrollment["skips_accrued"] == enrollment["nights"]:
        enrollment["status"] = "COMPLETED"
    touch(STORE, enrollment)
    # Property.outstanding_incentive_points is computed live from the ACTIVE
    # enrolments, so it needs no stored counter.
    return ok(enrollment_out(STORE, enrollment))


@bp.post("/housekeeping/service-enrollments/<eid>/void")
def void_enrollment(eid):
    authenticate((FRONT_DESK_AGENT,))
    enrollment = derive.get_enrollment(STORE, eid)
    if enrollment["status"] != "ACTIVE":
        raise ApiError("ERR_ENROLLMENT_NOT_ACTIVE", "Enrolment is not ACTIVE.")

    enrollment["skips_accrued"] = 0
    enrollment["points_accrued"] = 0
    enrollment["status"] = "VOIDED"
    touch(STORE, enrollment)

    room = STORE.rooms.get(enrollment["room_id"])
    if room is not None:
        # The exact compensation of the creation side effect.
        room["service_program"] = "DAILY"
        touch(STORE, room)
    return ok(enrollment_out(STORE, enrollment))
