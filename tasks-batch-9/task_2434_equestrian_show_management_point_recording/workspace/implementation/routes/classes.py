"""Classes, judging, purse posting and standings submissions."""

from decimal import Decimal

from flask import Blueprint, g

import calc
import serializers as ser
import services
import validate as v
from auth import endpoint, resolve_actor
from core import (
    ACK_OUTCOMES,
    STANDINGS_BODIES,
    assignments_of_slot,
    class_entries_of_class,
    classes_of_show,
    db,
    division_of_class,
    find,
    new_row,
    set_value,
    show_of_class,
    show_of_division,
    slots_of_class,
    submissions_of_class,
    touch,
)
from errors import ApiError
from response import object_response

bp = Blueprint("classes", __name__)

EDITABLE_LICENSE_STATES = ("DRAFT", "RETURNED_FOR_CORRECTION")
FINALIZED_SUBMISSION_STATES = ("RECORDED", "REJECTED", "RETRACTED")


@bp.post("/divisions/<division_id>/classes")
@endpoint("ShowSecretary")
def create_class(division_id):
    division = find(db.divisions, division_id, "ERR_DIVISION_NOT_FOUND")

    raw = v.raw_body()
    qualifier_key = v.fk_candidate(raw, "qualifier_for_class_id")
    if qualifier_key is not None:
        find(db.classes, qualifier_key, "ERR_CLASS_NOT_FOUND")

    payload = v.body()
    class_number = v.req_int(payload, "class_number", minimum=1)
    name = v.req_str(payload, "name")
    jump_height_cm = v.req_int(payload, "jump_height_cm", minimum=0)
    entry_fee_cents = v.req_int(payload, "entry_fee_cents", minimum=0)
    class_share_bp = v.req_int(payload, "class_share_bp", minimum=0, maximum=10000)
    max_entries = v.req_int(payload, "max_entries", minimum=1)
    qualifier_for_class_id = v.opt_str(payload, "qualifier_for_class_id")

    show = show_of_division(division)
    if show is None or show["license_status"] not in EDITABLE_LICENSE_STATES:
        raise ApiError("ERR_SHOW_LICENSE_LOCKED")

    if qualifier_for_class_id is not None:
        target = find(db.classes, qualifier_for_class_id, "ERR_CLASS_NOT_FOUND")
        target_show = show_of_class(target)
        if target_show is None or target_show["id"] != show["id"]:
            raise ApiError("ERR_QUALIFIER_CYCLE")
        seen = set()
        cursor = target
        while cursor is not None:
            if cursor["id"] in seen:
                raise ApiError("ERR_QUALIFIER_CYCLE")
            seen.add(cursor["id"])
            next_id = cursor.get("qualifier_for_class_id")
            cursor = db.classes.get(next_id) if next_id else None

    if not (
        int(division["min_jump_height_cm"]) <= jump_height_cm <= int(division["max_jump_height_cm"])
    ):
        raise ApiError("ERR_JUMP_HEIGHT_OUT_OF_RANGE")

    for existing in classes_of_show(show["id"]):
        if int(existing["class_number"]) == class_number:
            raise ApiError("ERR_CLASS_NUMBER_DUPLICATE")

    cls = new_row(
        db.classes,
        division_id=division["id"],
        class_number=class_number,
        name=name,
        jump_height_cm=jump_height_cm,
        entry_fee_cents=entry_fee_cents,
        class_share_bp=class_share_bp,
        max_entries=max_entries,
        qualifier_for_class_id=qualifier_for_class_id,
        status="PLANNED",
        entry_count=0,
        confirmed_entry_count=0,
        estimated_minutes=None,
        actual_minutes=None,
        class_purse_cents=0,
        awarded_prize_cents=0,
        placed_count=0,
        point_eligible=False,
    )
    touch(division)
    return object_response(ser.ser_class(cls), 201)


@bp.post("/classes/<class_id>/open")
@endpoint("ShowSecretary")
def open_class(class_id):
    cls = find(db.classes, class_id, "ERR_CLASS_NOT_FOUND")
    if cls["status"] != "PLANNED":
        raise ApiError("ERR_CLASS_NOT_PLANNED")
    show = show_of_class(cls)
    if show is None or show["license_status"] != "APPROVED":
        raise ApiError("ERR_SHOW_LICENSE_NOT_APPROVED")

    division = division_of_class(cls)
    cls["class_purse_cents"] = calc.class_purse(division, cls)
    cls["status"] = "OPEN"
    touch(cls)
    return object_response(ser.ser_class(cls))


def _running_slot(cls):
    for slot in slots_of_class(cls["id"]):
        if slot["status"] == "RUNNING":
            return slot
    return None


@bp.post("/classes/<class_id>/results")
@endpoint("Judge")
def record_results(class_id):
    cls = find(db.classes, class_id, "ERR_CLASS_NOT_FOUND")
    resolve_actor()

    raw = v.raw_body()
    raw_placings = raw.get("placings")
    if isinstance(raw_placings, list):
        for item in raw_placings:
            if isinstance(item, dict):
                key = v.fk_candidate(item, "class_entry_id")
                if key is not None:
                    find(db.class_entries, key, "ERR_CLASS_ENTRY_NOT_FOUND")

    payload = v.body()
    if "placings" not in payload or not isinstance(payload["placings"], list):
        raise ApiError("ERR_INVALID_REQUEST", "Field 'placings' must be an array.")
    actual_minutes = v.req_int(payload, "actual_minutes", minimum=0)

    cards = []
    for item in payload["placings"]:
        if not isinstance(item, dict):
            raise ApiError("ERR_INVALID_REQUEST", "Each placing must be an object.")
        class_entry_id = v.req_str(item, "class_entry_id")
        placing = v.req_int(item, "placing", minimum=1)
        round_seconds = v.opt_number(item, "round_seconds")
        cards.append((class_entry_id, placing, round_seconds))

    if cls["status"] != "IN_PROGRESS":
        raise ApiError("ERR_CLASS_NOT_IN_PROGRESS")

    slot = _running_slot(cls)
    assignments = assignments_of_slot(slot["id"]) if slot is not None else []
    holds_chair = any(
        a["status"] == "ACTIVE"
        and a["official_role"] == "JUDGE"
        and a["official_id"] == g.user_id
        for a in assignments
    )
    if not holds_chair:
        raise ApiError("ERR_JUDGE_NOT_ASSIGNED")
    also_steward = any(
        a["status"] == "ACTIVE"
        and a["official_role"] == "STEWARD"
        and a["official_id"] == g.user_id
        for a in assignments
    )
    if also_steward:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    if int(cls["entry_count"]) < 1:
        raise ApiError("ERR_NO_ENTRIES_TO_JUDGE")

    rows = class_entries_of_class(cls["id"])
    confirmed = [ce for ce in rows if ce["status"] == "CONFIRMED"]
    positions = [placing for (_ce, placing, _rs) in cards]
    ids = [class_entry_id for (class_entry_id, _p, _rs) in cards]
    if len(set(positions)) != len(positions) or len(set(ids)) != len(ids):
        raise ApiError("ERR_INVALID_PLACINGS")
    if sorted(positions) != list(range(1, len(positions) + 1)):
        raise ApiError("ERR_INVALID_PLACINGS")
    if len(positions) > min(5, len(confirmed)):
        raise ApiError("ERR_INVALID_PLACINGS")
    confirmed_ids = {ce["id"] for ce in confirmed}
    for class_entry_id in ids:
        if class_entry_id not in confirmed_ids:
            raise ApiError("ERR_INVALID_PLACINGS")

    named = set()
    for class_entry_id, placing, round_seconds in cards:
        class_entry = db.class_entries[class_entry_id]
        class_entry["status"] = "COMPLETED"
        class_entry["placing"] = placing
        class_entry["round_seconds"] = round_seconds
        touch(class_entry)
        named.add(class_entry_id)
    for class_entry in confirmed:
        if class_entry["id"] in named:
            continue
        class_entry["status"] = "COMPLETED"
        class_entry["placing"] = None
        touch(class_entry)

    cls["actual_minutes"] = actual_minutes
    cls["status"] = "JUDGED"
    touch(cls)
    services.recompute_placed_count(cls)
    services.recompute_class_counts(cls)

    if slot is not None:
        slot["status"] = "COMPLETED"
        touch(slot)
        ring = db.rings.get(slot["ring_id"])
        if ring is not None:
            services.recompute_ring_layout(ring)
    return object_response(ser.ser_class(cls))


@bp.post("/classes/<class_id>/post-results")
@endpoint("ShowSecretary")
def post_results(class_id):
    cls = find(db.classes, class_id, "ERR_CLASS_NOT_FOUND")
    if cls["status"] != "JUDGED":
        raise ApiError("ERR_CLASS_NOT_JUDGED")

    rows = class_entries_of_class(cls["id"])
    for class_entry in rows:
        if class_entry["placing"] is None:
            continue
        entry = db.entries.get(class_entry["entry_id"])
        if entry is None or entry["settlement_status"] != "PAID":
            raise ApiError("ERR_UNPAID_PLACED_ENTRY")

    place_cents, awarded = calc.ribbon_allocation(cls["class_purse_cents"], cls["placed_count"])
    show = show_of_class(cls)
    if show is not None and int(show["allocated_prize_cents"]) + awarded > int(
        show["prize_money_pool_cents"]
    ):
        raise ApiError("ERR_PRIZE_POOL_EXCEEDED")

    for class_entry in rows:
        placing = class_entry["placing"]
        if placing is not None and class_entry["status"] == "COMPLETED":
            set_value(class_entry, "prize_cents", place_cents.get(int(placing), 0))
        else:
            set_value(class_entry, "prize_cents", 0)

    cls["awarded_prize_cents"] = awarded
    cls["status"] = "RESULTS_POSTED"
    touch(cls)
    services.recompute_class_counts(cls)
    if show is not None:
        services.recompute_show_prizes(show)
        touch(show)
    return object_response(ser.ser_class(cls))


@bp.post("/classes/<class_id>/void-results")
@endpoint("ShowSecretary")
def void_results(class_id):
    cls = find(db.classes, class_id, "ERR_CLASS_NOT_FOUND")
    # A submission a standings body has already acted on outranks the plain state
    # check: raising a submission itself leaves the class in POINTS_SUBMITTED.
    for submission in submissions_of_class(cls["id"]):
        if submission["status"] in ("NATIONAL_ACCEPTED", "REGIONAL_ACCEPTED", "RECORDED"):
            raise ApiError("ERR_SUBMISSION_ALREADY_FINALIZED")
    if cls["status"] != "RESULTS_POSTED":
        raise ApiError("ERR_CLASS_RESULTS_NOT_POSTED")

    for class_entry in class_entries_of_class(cls["id"]):
        set_value(class_entry, "prize_cents", 0)
    cls["awarded_prize_cents"] = 0
    cls["status"] = "VOIDED"
    touch(cls)
    show = show_of_class(cls)
    if show is not None:
        services.recompute_show_prizes(show)
        touch(show)
    return object_response(ser.ser_class(cls))


@bp.post("/classes/<class_id>/point-submissions")
@endpoint("ShowSecretary")
def raise_point_submission(class_id):
    cls = find(db.classes, class_id, "ERR_CLASS_NOT_FOUND")
    payload = v.body()
    expected_class_version = v.req_int(payload, "expected_class_version")
    if expected_class_version != int(cls["version"]):
        raise ApiError("ERR_STALE_VERSION")
    if cls["status"] != "RESULTS_POSTED":
        raise ApiError("ERR_CLASS_RESULTS_NOT_POSTED")
    if not cls["point_eligible"]:
        raise ApiError("ERR_CLASS_NOT_POINT_ELIGIBLE")

    submission = new_row(
        db.submissions,
        class_id=cls["id"],
        submitted_by_user_id=g.user_id,
        national_body_reference=None,
        regional_body_reference=None,
        national_points_total=Decimal("0.0"),
        regional_points_total=0,
        status="PREPARED",
    )
    cls["status"] = "POINTS_SUBMITTED"
    touch(cls)
    return object_response(ser.ser_submission(submission), 201)


@bp.post("/point-submissions/<submission_id>/acknowledgement")
@endpoint("FederationOfficer")
def acknowledge_submission(submission_id):
    submission = find(db.submissions, submission_id, "ERR_POINT_SUBMISSION_NOT_FOUND")
    payload = v.body()
    standings_body = v.req_enum(payload, "standings_body", STANDINGS_BODIES)
    outcome = v.req_enum(payload, "outcome", ACK_OUTCOMES)
    body_reference = v.opt_str(payload, "body_reference")

    if submission["status"] in FINALIZED_SUBMISSION_STATES:
        raise ApiError("ERR_SUBMISSION_ALREADY_FINALIZED")

    cls = db.classes.get(submission["class_id"])

    if outcome == "REJECTED":
        services.reject_submission(submission, cls)
        if cls is not None and cls["status"] == "POINTS_SUBMITTED":
            cls["status"] = "RESULTS_POSTED"
            touch(cls)
        return object_response(ser.ser_submission(submission))

    status = submission["status"]
    if standings_body == "NATIONAL":
        if status == "PREPARED":
            submission["status"] = "NATIONAL_ACCEPTED"
        elif status == "REGIONAL_ACCEPTED":
            submission["status"] = "RECORDED"
        else:
            raise ApiError("ERR_SUBMISSION_ALREADY_FINALIZED")
        services.credit_national(cls, submission, body_reference)
    else:
        if status == "PREPARED":
            submission["status"] = "REGIONAL_ACCEPTED"
        elif status == "NATIONAL_ACCEPTED":
            submission["status"] = "RECORDED"
        else:
            raise ApiError("ERR_SUBMISSION_ALREADY_FINALIZED")
        services.credit_regional(cls, submission, body_reference)

    touch(submission)
    return object_response(ser.ser_submission(submission))
