"""Conference groups: contract intake, deposits, rooming-list revisions,
submission loop, confirm, cancel, close-out (PRD 3.2, 3.4, 3.9)."""
from datetime import timedelta

from flask import Blueprint, request

from authz import (
    ADMIN, FACILITIES, HOUSEKEEPING, FINANCE, COORDINATOR, ALL_ROLES,
    require_roles, check_group_ownership,
)
from calc import (
    active_revision, binding_interval, cancellation_fee_cents,
    provisional_bed_night_subtotal, required_turn_hours, screening_is_expired,
)
from cascades import cancel_reserved_assignment, adjust_bed_counters
from db import store
from errors import (
    ApiError, date_range_invalid, invalid_request, invalid_state, stale_version,
)
from respond import success
from serialize import ser_group, ser_participant, ser_revision
from store_ops import (
    get_or_404, json_body, new_common_fields, new_id, opt_bool, opt_enum_default,
    paginate, req_enum, req_field, req_int, req_str, req_temporal,
    restore_store, snapshot_store, sorted_by_creation, touch,
)
from timeutil import as_date, as_instant, add_years

bp = Blueprint("groups", __name__)

GROUP_READ_ROLES = [ADMIN, FACILITIES, HOUSEKEEPING, FINANCE, COORDINATOR]


@bp.route("/conference-groups", methods=["POST"])
def create_group():
    require_roles([ADMIN])
    data = json_body()
    building_id = req_str(data, "building_id")
    if building_id not in store.buildings:
        raise invalid_request("building_id does not reference an existing building")
    client_name = req_str(data, "client_name")
    contact_email = req_str(data, "contact_email")
    arrival = req_temporal(data, "arrival_date")
    departure = req_temporal(data, "departure_date")
    has_minor = opt_bool(data, "has_minor_participants", False)
    linen_tier = opt_enum_default(data, "linen_tier", ("STANDARD", "DELUXE"), "STANDARD")
    contracted = req_int(data, "contracted_bed_count", minimum=1)
    deposit = 0
    if "deposit_paid_cents" in data and data["deposit_paid_cents"] is not None:
        deposit = req_int(data, "deposit_paid_cents", minimum=0)
    if as_date(departure) <= as_date(arrival):
        raise date_range_invalid("departure_date must be after arrival_date")
    g = {
        "id": new_id(),
        "_seq": next(store.seq),
        "building_id": building_id,
        "client_name": client_name,
        "contact_email": contact_email,
        "arrival_date": arrival,
        "departure_date": departure,
        "has_minor_participants": has_minor,
        "linen_tier": linen_tier,
        "contracted_bed_count": contracted,
        "deposit_paid_cents": deposit,
        "status": "DRAFT",
        "provisional_invoice_id": None,
        "cancellation_fee_cents": None,
    }
    g.update(new_common_fields())
    store.groups[g["id"]] = g
    return success(ser_group(g), status=201)


@bp.route("/conference-groups", methods=["GET"])
def list_groups():
    require_roles([ADMIN, FACILITIES, HOUSEKEEPING, FINANCE])
    building_id = request.args.get("building_id")
    status = request.args.get("status")
    items = [g for g in store.groups.values()
             if (building_id is None or g["building_id"] == building_id)
             and (status is None or g["status"] == status)]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_group(g) for g in page], response_type="array", pagination=pagination)


@bp.route("/conference-groups/<gid>", methods=["GET"])
def get_group(gid):
    uid, role = require_roles(GROUP_READ_ROLES)
    check_group_ownership(uid, role, gid)
    return success(ser_group(get_or_404(store.groups, gid)))


@bp.route("/conference-groups/<gid>/record-deposit", methods=["POST"])
def record_deposit(gid):
    require_roles([FINANCE, ADMIN])
    g = get_or_404(store.groups, gid)
    data = json_body()
    amount = req_int(data, "amount_cents", minimum=0)
    g["deposit_paid_cents"] += amount
    touch(g)
    return success(ser_group(g))


@bp.route("/conference-groups/<gid>/participants", methods=["POST"])
def add_participant(gid):
    uid, role = require_roles([COORDINATOR, ADMIN])
    check_group_ownership(uid, role, gid)
    g = get_or_404(store.groups, gid)
    data = json_body()
    full_name = req_str(data, "full_name")
    dob = req_temporal(data, "date_of_birth")
    role_in_group = req_enum(data, "role_in_group", ("ATTENDEE", "CHAPERONE", "STAFF"))
    if g["status"] not in ("DRAFT", "RETURNED", "SUBMITTED", "CONFIRMED"):
        raise invalid_state("Participants may be added only while the group is DRAFT, RETURNED, SUBMITTED, or CONFIRMED")
    is_minor = add_years(as_date(dob), 18) > as_date(g["arrival_date"])
    p = {
        "id": new_id(),
        "_seq": next(store.seq),
        "group_id": gid,
        "full_name": full_name,
        "date_of_birth": dob,
        "role_in_group": role_in_group,
        "is_minor": is_minor,
    }
    p.update(new_common_fields())
    store.participants[p["id"]] = p
    touch(g)
    return success(ser_participant(p), status=201)


@bp.route("/conference-groups/<gid>/participants", methods=["GET"])
def list_participants(gid):
    uid, role = require_roles(ALL_ROLES)
    check_group_ownership(uid, role, gid)
    get_or_404(store.groups, gid)
    rig = request.args.get("role_in_group")
    items = [p for p in store.participants.values()
             if p["group_id"] == gid and (rig is None or p["role_in_group"] == rig)]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_participant(p) for p in page], response_type="array", pagination=pagination)


# ---------------------------------------------------------------------------
# Rooming-list revisions (PRD 3.4)
# ---------------------------------------------------------------------------

RESERVABLE_ROOM_STATES = ("RELEASED", "READY", "RESERVED", "OCCUPIED")


def _intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open interval intersection; touching intervals do not overlap."""
    return a_start < b_end and b_start < a_end


def _validate_new_assignment(group, entry):
    """Per-assignment gauntlet, PRD 3.4 / validations priorities 10, 20, 21,
    22, 29: reservable -> date range -> double-booking -> turn window ->
    capacity."""
    room = store.rooms[entry["room_id"]]
    ci = as_instant(entry["checkin_at"])
    co = as_instant(entry["checkout_at"])
    if room["status"] not in RESERVABLE_ROOM_STATES:
        raise ApiError("ERR_ROOM_NOT_RESERVABLE", 409,
                       "Room is not reservable in its current state")
    if co <= ci:
        raise date_range_invalid("checkout_at must be strictly after checkin_at")
    # Participant double-booking: any room, same participant, binding interval.
    for a in store.assignments.values():
        if a["participant_id"] != entry["participant_id"]:
            continue
        iv = binding_interval(a)
        if iv and _intervals_overlap(ci, co, iv[0], iv[1]):
            raise ApiError("ERR_OCCUPANCY_OVERLAP", 409,
                           "Participant already holds an intersecting assignment")
    # Turn-window rule against immediate neighbors on the same room.
    preceding = []
    following = []
    for a in store.assignments.values():
        if a["room_id"] != room["id"]:
            continue
        iv = binding_interval(a)
        if iv is None:
            continue
        if iv[1] <= ci:
            preceding.append((iv[1], a))
        elif iv[0] >= co:
            following.append((iv[0], a))
    if preceding:
        _end, p = max(preceding, key=lambda t: t[0])
        gap = ci - _end
        if gap < timedelta(hours=required_turn_hours(group["linen_tier"])):
            raise ApiError("ERR_TURN_WINDOW_TOO_SHORT", 422,
                           "Gap before the preceding assignment is below the required turn hours")
    if following:
        _start, f = min(following, key=lambda t: t[0])
        f_group = store.groups.get(f["group_id"])
        f_tier = f_group["linen_tier"] if f_group else "STANDARD"
        gap = _start - co
        if gap < timedelta(hours=required_turn_hours(f_tier)):
            raise ApiError("ERR_TURN_WINDOW_TOO_SHORT", 422,
                           "Gap to the following assignment is below the required turn hours")
    # Room capacity over the new interval.
    overlapping = 0
    for a in store.assignments.values():
        if a["room_id"] != room["id"]:
            continue
        iv = binding_interval(a)
        if iv and _intervals_overlap(ci, co, iv[0], iv[1]):
            overlapping += 1
    if overlapping >= room["bed_count"]:
        raise ApiError("ERR_ROOM_CAPACITY_EXCEEDED", 422,
                       "Room capacity exceeded for the requested interval")


@bp.route("/conference-groups/<gid>/rooming-list-revisions", methods=["POST"])
def create_revision(gid):
    uid, role = require_roles([COORDINATOR, ADMIN])
    check_group_ownership(uid, role, gid)
    g = get_or_404(store.groups, gid)
    data = json_body()
    expected = req_int(data, "expected_conference_group_version")
    raw_assignments = req_field(data, "assignments")
    if not isinstance(raw_assignments, list):
        raise invalid_request("assignments must be an array")
    entries = []
    for raw in raw_assignments:
        if not isinstance(raw, dict):
            raise invalid_request("each assignment must be an object")
        room_id = req_str(raw, "room_id")
        if room_id not in store.rooms:
            raise invalid_request("room_id does not reference an existing room")
        participant_id = req_str(raw, "participant_id")
        participant = store.participants.get(participant_id)
        if participant is None or participant["group_id"] != gid:
            raise invalid_request("participant_id does not reference a participant of this group")
        checkin_at = req_temporal(raw, "checkin_at")
        checkout_at = req_temporal(raw, "checkout_at")
        entries.append({
            "room_id": room_id,
            "participant_id": participant_id,
            "checkin_at": checkin_at,
            "checkout_at": checkout_at,
        })
    # OCC on the parent group (priority 7).
    if expected != g["version"]:
        raise stale_version("expected_conference_group_version does not match the group's current version")

    snap = snapshot_store()
    try:
        building = store.buildings[g["building_id"]]
        building_changed = False
        # Supersede the prior ACTIVE revision BEFORE validating the new
        # assignments, so a superseding revision never collides with the
        # assignments it replaces.
        prior = active_revision(gid)
        if prior is not None:
            prior["status"] = "SUPERSEDED"
            prior["superseded_at"] = store.clock
            for aid in prior["assignment_ids"]:
                a = store.assignments[aid]
                if a["status"] == "RESERVED":
                    cancel_reserved_assignment(a)
                    building_changed = True
        rev = {
            "id": new_id(),
            "_seq": next(store.seq),
            "group_id": gid,
            "revision_number": sum(1 for r in store.revisions.values() if r["group_id"] == gid) + 1,
            "status": "ACTIVE",
            "assignment_ids": [],
            "superseded_at": None,
            "created_at": store.clock,
        }
        for entry in entries:
            _validate_new_assignment(g, entry)
            asn = {
                "id": new_id(),
                "_seq": next(store.seq),
                "revision_id": rev["id"],
                "group_id": gid,
                "room_id": entry["room_id"],
                "participant_id": entry["participant_id"],
                "checkin_at": entry["checkin_at"],
                "checkout_at": entry["checkout_at"],
                "actual_checkin_at": None,
                "actual_checkout_at": None,
                "status": "RESERVED",
            }
            asn.update(new_common_fields())
            store.assignments[asn["id"]] = asn
            rev["assignment_ids"].append(asn["id"])
            room = store.rooms[asn["room_id"]]
            if room["status"] in ("RELEASED", "READY"):
                room["status"] = "RESERVED"
                touch(room)
            adjust_bed_counters(building, 1)
            building_changed = True
        store.revisions[rev["id"]] = rev
        if building_changed:
            touch(building)
        touch(g)
        # A supersede while the group is CONFIRMED refreshes the provisional
        # invoice's bed-night subtotal.
        if g["status"] == "CONFIRMED" and g["provisional_invoice_id"] is not None:
            invoice = store.invoices.get(g["provisional_invoice_id"])
            if invoice is not None and invoice["status"] == "PROVISIONAL":
                subtotal = provisional_bed_night_subtotal(g)
                invoice["provisional_bed_night_subtotal_cents"] = subtotal
                invoice["provisional_total_cents"] = subtotal
                touch(invoice)
    except ApiError:
        restore_store(snap)
        raise
    return success(ser_revision(rev), status=201)


@bp.route("/conference-groups/<gid>/rooming-list-revisions", methods=["GET"])
def list_revisions(gid):
    uid, role = require_roles([ADMIN, FACILITIES, FINANCE, COORDINATOR])
    check_group_ownership(uid, role, gid)
    get_or_404(store.groups, gid)
    status = request.args.get("status")
    items = [r for r in store.revisions.values()
             if r["group_id"] == gid and (status is None or r["status"] == status)]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_revision(r) for r in page], response_type="array", pagination=pagination)


@bp.route("/rooming-list-revisions/<rid>", methods=["GET"])
def get_revision(rid):
    require_roles([ADMIN, FACILITIES, FINANCE, COORDINATOR])
    return success(ser_revision(get_or_404(store.revisions, rid)))


# ---------------------------------------------------------------------------
# Submission loop, confirm, cancel, close-out (PRD 3.2, 3.9)
# ---------------------------------------------------------------------------

@bp.route("/conference-groups/<gid>/submit", methods=["POST"])
def submit_group(gid):
    uid, role = require_roles([COORDINATOR, ADMIN])
    check_group_ownership(uid, role, gid)
    g = get_or_404(store.groups, gid)
    if g["status"] not in ("DRAFT", "RETURNED"):
        raise invalid_state("Group must be DRAFT or RETURNED to submit")
    if not any(p["group_id"] == gid for p in store.participants.values()):
        raise invalid_state("Group must have at least one participant to submit")
    g["status"] = "SUBMITTED"
    touch(g)
    return success(ser_group(g))


@bp.route("/conference-groups/<gid>/return-for-revision", methods=["POST"])
def return_for_revision(gid):
    require_roles([ADMIN])
    g = get_or_404(store.groups, gid)
    if g["status"] != "SUBMITTED":
        raise invalid_state("Group must be SUBMITTED to return for revision")
    g["status"] = "RETURNED"
    touch(g)
    return success(ser_group(g))


def _confirm_safety_gates(g):
    if not g["has_minor_participants"]:
        return
    participants = [p for p in store.participants.values() if p["group_id"] == g["id"]]
    minors = [p for p in participants if p["is_minor"]]
    non_minor_chaperones = [p for p in participants
                            if p["role_in_group"] == "CHAPERONE" and not p["is_minor"]]
    required = (len(minors) + 9) // 10
    if len(non_minor_chaperones) < required:
        raise ApiError("ERR_CHAPERONE_RATIO_UNMET", 422,
                       "Minor-flagged group lacks ceil(minors/10) non-minor chaperones")
    for p in participants:
        if p["role_in_group"] not in ("CHAPERONE", "STAFF"):
            continue
        cleared = [s for s in store.screenings.values()
                   if s["participant_id"] == p["id"] and s["status"] == "CLEARED"]
        if not cleared:
            raise ApiError("ERR_SCREENING_NOT_CLEARED", 422,
                           "A CHAPERONE/STAFF participant lacks a CLEARED screening")
        if all(screening_is_expired(s) for s in cleared):
            raise ApiError("ERR_SCREENING_EXPIRED", 422,
                           "A CHAPERONE/STAFF participant's CLEARED screening is expired")


@bp.route("/conference-groups/<gid>/confirm", methods=["POST"])
def confirm_group(gid):
    require_roles([ADMIN])
    g = get_or_404(store.groups, gid)
    if g["status"] != "SUBMITTED":
        raise invalid_state("Group must be SUBMITTED to confirm")
    building = store.buildings[g["building_id"]]
    if building["status"] != "TURN_ACTIVE":
        raise ApiError("ERR_BUILDING_NOT_RELEASED", 409,
                       "Host building is not TURN_ACTIVE")
    _confirm_safety_gates(g)
    rev = active_revision(gid)
    if rev is None or len(rev["assignment_ids"]) < 1:
        raise ApiError("ERR_ROOMING_LIST_REQUIRED", 422,
                       "An ACTIVE revision with at least one assignment is required")
    if len(rev["assignment_ids"]) != g["contracted_bed_count"]:
        raise ApiError("ERR_CONTRACTED_BED_MISMATCH", 422,
                       "ACTIVE revision assignment count does not equal contracted_bed_count")
    estimate = provisional_bed_night_subtotal(g)
    if g["deposit_paid_cents"] * 4 < estimate:
        raise ApiError("ERR_DEPOSIT_INSUFFICIENT", 422,
                       "Deposit does not cover one quarter of the provisional bed-night estimate")
    invoice = {
        "id": new_id(),
        "_seq": next(store.seq),
        "group_id": gid,
        "status": "PROVISIONAL",
        "provisional_bed_night_subtotal_cents": estimate,
        "provisional_total_cents": estimate,
        "final_bed_night_subtotal_cents": None,
        "linen_charge_cents": None,
        "key_charge_cents": None,
        "damage_charge_cents": None,
        "total_cents": None,
        "balance_due_cents": None,
        "finalized_at": None,
        "paid_at": None,
    }
    invoice.update(new_common_fields())
    store.invoices[invoice["id"]] = invoice
    g["provisional_invoice_id"] = invoice["id"]
    g["status"] = "CONFIRMED"
    touch(g)
    return success(ser_group(g))


@bp.route("/conference-groups/<gid>/cancel", methods=["POST"])
def cancel_group(gid):
    uid, role = require_roles([COORDINATOR, ADMIN])
    check_group_ownership(uid, role, gid)
    g = get_or_404(store.groups, gid)
    if g["status"] not in ("DRAFT", "SUBMITTED", "RETURNED", "CONFIRMED"):
        raise ApiError("ERR_GROUP_NOT_CANCELLABLE", 409,
                       "Group is not cancellable from its current state")
    if g["status"] == "CONFIRMED":
        invoice = store.invoices.get(g["provisional_invoice_id"])
        provisional_total = invoice["provisional_total_cents"] if invoice else 0
        g["cancellation_fee_cents"] = cancellation_fee_cents(g, provisional_total)
        if invoice is not None and invoice["status"] == "PROVISIONAL":
            invoice["status"] = "VOID"
            touch(invoice)
    else:
        g["cancellation_fee_cents"] = 0
    building = store.buildings[g["building_id"]]
    building_changed = False
    for a in list(store.assignments.values()):
        if a["group_id"] == gid and a["status"] == "RESERVED":
            cancel_reserved_assignment(a)
            building_changed = True
    if building_changed:
        touch(building)
    g["status"] = "CANCELLED"
    touch(g)
    return success(ser_group(g))


@bp.route("/conference-groups/<gid>/close-out", methods=["POST"])
def close_out_group(gid):
    require_roles([ADMIN])
    g = get_or_404(store.groups, gid)
    if g["status"] != "IN_HOUSE":
        raise invalid_state("Group must be IN_HOUSE to close out")
    for a in store.assignments.values():
        if a["group_id"] == gid and a["status"] not in ("CHECKED_OUT", "NO_SHOW", "CANCELLED"):
            raise invalid_state("Every stay assignment of the group must be terminal to close out")
    g["status"] = "DEPARTED"
    touch(g)
    return success(ser_group(g))
