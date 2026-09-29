"""Witness parties and witness assignments (PRD 3.6)."""
from flask import Blueprint

import calc
import clock
import common
import envelope
import posture
import rbac
import store
import validation
from errors import ApiError
from validation import DATETIME, INTEGER, STRING, f

bp = Blueprint("witness", __name__)

PARTY_TYPES = ["CUSTOMER", "THIRD_PARTY_LAB", "INSURER"]
REGIONS = ["NA", "EU", "APAC", "LATAM"]
PARTY_STATUSES = ["ACTIVE", "CREDENTIAL_EXPIRED", "INACTIVE"]


def _check_credential(party, fat):
    """Rung 50: the party must be assignable and its credential outlive the window."""
    if party.get("status") != "ACTIVE":
        raise ApiError("ERR_WITNESS_CREDENTIAL_EXPIRED",
                       "witness party is %s" % party.get("status"))
    start = clock.sec(clock.parse(fat.get("window_start_at"))) if fat else None
    expiry = clock.sec(clock.parse(party.get("credential_expires_at")))
    if start is not None and (expiry is None or expiry <= start):
        raise ApiError("ERR_WITNESS_CREDENTIAL_EXPIRED",
                       "the credential lapses at or before the test window starts")


def _check_blackout(assignment, party_id, fat):
    """Rung 62: set-membership collision in either direction."""
    day = clock.day(clock.parse(fat.get("window_start_at")))
    if day is None:
        return
    own_blackout = calc.blackout_days_set(day, assignment.get("travel_region"))
    for other in calc.party_confirmed_assignments(party_id, exclude_id=assignment.get("id")):
        other_day = calc.assignment_day(other)
        if other_day is None:
            continue
        if day in calc.blackout_days_set(other_day, other.get("travel_region")):
            raise ApiError("ERR_WITNESS_TRAVEL_BLACKOUT",
                           "the day is blacked out by confirmed assignment %s" % other["id"])
        if other_day in own_blackout:
            raise ApiError("ERR_WITNESS_TRAVEL_BLACKOUT",
                           "confirmed assignment %s falls in this trip's blackout" % other["id"])


def _fat_scheduled(fat):
    if fat.get("status") not in ("BAY_SCHEDULED", "WITNESS_CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "the parent test is %s" % fat.get("status"))


def _before_window(fat):
    start = clock.sec(clock.parse(fat.get("window_start_at")))
    if start is not None and clock.sec(clock.now()) >= start:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "the test window has already started")


# --------------------------------------------------------------------------- #
# witness parties
# --------------------------------------------------------------------------- #

@bp.route("/witness-parties", methods=["POST"])
def create_party():
    rbac.authenticate("POST /witness-parties")
    payload = validation.body()
    data = validation.validate(payload, [
        f("party_code", STRING, required=True),
        f("display_name", STRING, required=True),
        f("party_type", STRING, required=True, enum=PARTY_TYPES),
        f("home_region", STRING, required=True, enum=REGIONS),
        f("daily_witness_capacity", INTEGER, minimum=1, maximum=3, default=1),
        f("credential_expires_at", DATETIME, required=True),
    ])
    for p in store.all_rows("party"):
        if p.get("party_code") == data["party_code"]:
            raise ApiError("ERR_DUPLICATE_CODE", "party_code already exists")
    party = dict(data)
    party["status"] = "ACTIVE"
    store.insert("party", party)
    return envelope.created(store.public(party))


@bp.route("/witness-parties", methods=["GET"])
def list_parties():
    rbac.authenticate("GET /witness-parties")
    limit, offset = envelope.pagination()
    rows = common.apply_filters(store.all_rows("party"), {
        "party_type": common.qstr("party_type"),
        "home_region": common.qstr("home_region"),
        "status": common.qstr("status"),
    })
    return envelope.listing(store.public_list(rows), limit, offset)


@bp.route("/witness-parties/<pid>", methods=["GET"])
def get_party(pid):
    rbac.authenticate("GET /witness-parties/{id}")
    return envelope.ok(store.public(common.resolve("party", pid)))


@bp.route("/witness-parties/<pid>", methods=["PATCH"])
def patch_party(pid):
    rbac.authenticate("PATCH /witness-parties/{id}")
    party = common.resolve("party", pid)
    payload = validation.body()
    data = validation.validate(payload, [
        f("daily_witness_capacity", INTEGER, minimum=1, maximum=3),
        f("credential_expires_at", DATETIME),
        f("home_region", STRING, enum=REGIONS),
        f("status", STRING, enum=PARTY_STATUSES),
    ])
    for key in ("daily_witness_capacity", "credential_expires_at", "home_region", "status"):
        if key in data:
            party[key] = data[key]
    store.touch("party", party)
    return envelope.ok(store.public(party))


@bp.route("/witness-parties/<pid>/load", methods=["GET"])
def party_load(pid):
    rbac.authenticate("GET /witness-parties/{id}/load")
    common.resolve("party", pid)
    limit, offset = envelope.pagination()
    rows = calc.party_confirmed_assignments(pid)
    rows = sorted(rows, key=lambda a: (a.get("created_at"), a.get("_seq", 0)))
    return envelope.listing(store.public_list(rows), limit, offset)


# --------------------------------------------------------------------------- #
# witness assignments
# --------------------------------------------------------------------------- #

@bp.route("/factory-acceptance-tests/<fid>/witness-assignments", methods=["POST"])
def create_assignment(fid):
    rbac.authenticate("POST /factory-acceptance-tests/{id}/witness-assignments")
    fat = common.resolve("fat", fid)
    payload = validation.body()
    party = common.resolve_body_ref("party", payload, "witness_party_id")
    data = validation.validate(payload, [
        f("witness_party_id", STRING, required=True),
        f("travel_region", STRING, required=True, enum=REGIONS),
        f("blackout_days", INTEGER, minimum=0),
    ])
    common.check_fat_administrable(fat)
    _check_credential(party, fat)
    for other in store.where("assignment", factory_acceptance_test_id=fid,
                             witness_party_id=party["id"]):
        if other.get("status") not in common.TERMINAL["assignment"]:
            raise ApiError("ERR_WITNESS_ALREADY_ASSIGNED",
                           "a non-terminal assignment already pairs this test and party")
    assignment = {
        "factory_acceptance_test_id": fid,
        "witness_party_id": party["id"],
        "status": "INVITED",
        "travel_region": data["travel_region"],
        "blackout_days": calc.blackout_for(data["travel_region"]),
        "confirmed_at": None,
        "decline_reason": None,
    }
    store.insert("assignment", assignment)
    common.refresh_fat_witness_aggregate(fat)
    posture.refresh_by_id(fat.get("engineered_order_id"))
    return envelope.created(store.public(assignment))


@bp.route("/factory-acceptance-tests/<fid>/witness-assignments", methods=["GET"])
def list_fat_assignments(fid):
    rbac.authenticate("GET /factory-acceptance-tests/{id}/witness-assignments")
    common.resolve("fat", fid)
    limit, offset = envelope.pagination()
    rows = common.apply_filters(store.where("assignment", factory_acceptance_test_id=fid),
                                {"status": common.qstr("status")})
    return envelope.listing(store.public_list(rows), limit, offset)


@bp.route("/witness-assignments", methods=["GET"])
def list_assignments():
    rbac.authenticate("GET /witness-assignments")
    limit, offset = envelope.pagination()
    rows = common.apply_filters(store.all_rows("assignment"), {
        "factory_acceptance_test_id": common.qstr("factory_acceptance_test_id"),
        "witness_party_id": common.qstr("witness_party_id"),
        "status": common.qstr("status"),
        "travel_region": common.qstr("travel_region"),
    })
    return envelope.listing(store.public_list(rows), limit, offset)


@bp.route("/witness-assignments/<aid>", methods=["GET"])
def get_assignment(aid):
    rbac.authenticate("GET /witness-assignments/{id}")
    return envelope.ok(store.public(common.resolve("assignment", aid)))


@bp.route("/witness-assignments/<aid>/confirm", methods=["POST"])
def confirm_assignment(aid):
    actor = rbac.authenticate("POST /witness-assignments/{id}/confirm")
    assignment = common.resolve("assignment", aid)
    rbac.check_witness_identity(actor, assignment.get("witness_party_id"))
    party = common.resolve("party", assignment.get("witness_party_id"))
    fat = common.resolve("fat", assignment.get("factory_acceptance_test_id"))
    common.check_state("assignment", assignment, ("INVITED",))
    _fat_scheduled(fat)
    _check_credential(party, fat)
    _check_blackout(assignment, party["id"], fat)
    day = calc.assignment_day(assignment)
    load = calc.party_day_load(party["id"], day, exclude_id=aid)
    if load >= (party.get("daily_witness_capacity") or 1):
        raise ApiError("ERR_WITNESS_DAY_CAPACITY",
                       "the party already holds %d confirmed assignments that day" % load)
    assignment["status"] = "CONFIRMED"
    assignment["confirmed_at"] = clock.now_str()
    assignment["blackout_days"] = calc.blackout_for(assignment.get("travel_region"))
    store.touch("assignment", assignment)
    common.refresh_fat_witness_aggregate(fat)
    posture.refresh_by_id(fat.get("engineered_order_id"))
    return envelope.ok(store.public(assignment))


@bp.route("/witness-assignments/<aid>/decline", methods=["POST"])
def decline_assignment(aid):
    actor = rbac.authenticate("POST /witness-assignments/{id}/decline")
    assignment = common.resolve("assignment", aid)
    rbac.check_witness_identity(actor, assignment.get("witness_party_id"))
    fat = common.resolve("fat", assignment.get("factory_acceptance_test_id"))
    payload = validation.body()
    data = validation.validate(payload, [f("decline_reason", STRING, required=True)])
    if not data["decline_reason"].strip():
        raise ApiError("ERR_MISSING_REQUIRED_FIELD", "decline_reason must be non-empty")
    was_confirmed = assignment.get("status") == "CONFIRMED"
    common.check_state("assignment", assignment, ("INVITED", "CONFIRMED"))
    if was_confirmed:
        _fat_scheduled(fat)
    assignment["status"] = "DECLINED"
    assignment["decline_reason"] = data["decline_reason"]
    store.touch("assignment", assignment)
    common.refresh_fat_witness_aggregate(fat)
    posture.refresh_by_id(fat.get("engineered_order_id"))
    return envelope.ok(store.public(assignment))


@bp.route("/witness-assignments/<aid>/reinvite", methods=["POST"])
def reinvite_assignment(aid):
    rbac.authenticate("POST /witness-assignments/{id}/reinvite")
    assignment = common.resolve("assignment", aid)
    party = common.resolve("party", assignment.get("witness_party_id"))
    fat = common.resolve("fat", assignment.get("factory_acceptance_test_id"))
    common.check_state("assignment", assignment, ("DECLINED",))
    common.check_fat_administrable(fat)
    _fat_scheduled(fat)
    _check_credential(party, fat)
    _before_window(fat)
    assignment["status"] = "INVITED"
    assignment["decline_reason"] = None
    store.touch("assignment", assignment)
    common.refresh_fat_witness_aggregate(fat)
    posture.refresh_by_id(fat.get("engineered_order_id"))
    return envelope.ok(store.public(assignment))


@bp.route("/witness-assignments/<aid>/waive", methods=["POST"])
def waive_assignment(aid):
    rbac.authenticate("POST /witness-assignments/{id}/waive")
    assignment = common.resolve("assignment", aid)
    fat = common.resolve("fat", assignment.get("factory_acceptance_test_id"))
    payload = validation.body()
    validation.validate(payload, [f("reason", STRING)])
    common.check_state("assignment", assignment, ("INVITED", "DECLINED"))
    common.check_fat_administrable(fat)
    if not fat.get("witness_required"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "the test does not require witnessing")
    for other in store.where("assignment", factory_acceptance_test_id=fat["id"]):
        if other.get("status") == "CONFIRMED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "assignment %s is already confirmed on this test" % other["id"])
    _before_window(fat)
    assignment["status"] = "WAIVED"
    if isinstance(payload.get("reason"), str):
        assignment["waive_reason"] = payload["reason"]
    store.touch("assignment", assignment)
    fat["witness_required"] = False
    store.touch("fat", fat)
    common.refresh_fat_witness_aggregate(fat)
    posture.refresh_by_id(fat.get("engineered_order_id"))
    return envelope.ok(store.public(assignment))
