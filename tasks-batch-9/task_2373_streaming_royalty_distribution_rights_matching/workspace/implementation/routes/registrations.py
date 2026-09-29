"""RightsRegistration endpoints (§3.4, §3.5)."""

from flask import Blueprint

import lookup
import serializers
import validation
from constants import (
    API_PREFIX,
    MAX_EVIDENCE_ROUNDS,
    MAX_SHARE_BPS_PER_TERRITORY,
    RIGHT_TYPES,
    ROLE_RIGHTS_HOLDER_USER,
    ROLE_RIGHTS_OPS_ANALYST,
    ROUTINGS,
)
from db import by_created, db, now, parse_dt, stamp_new, touch
from errors import ApiError
from middleware import current_role, current_user_id, require
from response import created_response, object_response, paginate_and_serialize
from services import cascades, derive
from validation import half_open_overlap, territory_sets_intersect

bp = Blueprint("registrations", __name__, url_prefix=API_PREFIX)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _right_type_agrees(work, claimant, right_type):
    if right_type == "MASTER":
        return (work["work_type"] == "RECORDING"
                and claimant["holder_type"] in ("LABEL", "DISTRIBUTOR"))
    return (work["work_type"] == "COMPOSITION"
            and claimant["holder_type"] in ("PUBLISHER", "COLLECTIVE"))


def _claim_window_open(work_id, right_type):
    """§3.4: the window must be open for every period already carrying usage
    that touches the claimed work."""
    current = now()
    for period in db.periods.values():
        touches = False
        for line in derive.lines_of_period(period["id"]):
            if line["work_id"] is None:
                continue
            if right_type == "MASTER":
                if line["work_id"] == work_id:
                    touches = True
                    break
            else:
                matched = db.works.get(line["work_id"])
                if matched is not None and matched["linked_work_id"] == work_id:
                    touches = True
                    break
        if not touches:
            continue
        closes = parse_dt(period["claim_window_closes_at"])
        if closes is not None and current > closes:
            return False
    return True


def _overlapping_supersede_set(registration):
    if not registration["supersede_overlapping"]:
        return []
    victims = []
    for other in by_created(list(db.registrations.values())):
        if other["id"] == registration["id"]:
            continue
        if other["status"] != "APPROVED":
            continue
        if other["work_id"] != registration["work_id"]:
            continue
        if other["right_type"] != registration["right_type"]:
            continue
        if other["claimant_id"] != registration["claimant_id"]:
            continue
        if not territory_sets_intersect(other["territory_set"],
                                        registration["territory_set"]):
            continue
        if not half_open_overlap(other["effective_from"], other["effective_to"],
                                 registration["effective_from"],
                                 registration["effective_to"]):
            continue
        victims.append(other)
    return victims


def _test_territories(registration):
    """Concrete territories whose aggregate share must be tested (§3.4)."""
    if registration["territory_set"] == ["WORLD"]:
        claimed = []
        for other in by_created(list(db.registrations.values())):
            if other["work_id"] != registration["work_id"]:
                continue
            for code in other["territory_set"]:
                if code != "WORLD" and code not in claimed:
                    claimed.append(code)
        return claimed or ["WORLD"]
    return [c for c in registration["territory_set"] if c != "WORLD"]


def _oversubscribed(registration, excluded_ids):
    for territory in _test_territories(registration):
        total = registration["share_bps"]
        for other in db.registrations.values():
            if other["id"] == registration["id"] or other["id"] in excluded_ids:
                continue
            if other["status"] != "APPROVED":
                continue
            if other["work_id"] != registration["work_id"]:
                continue
            if other["right_type"] != registration["right_type"]:
                continue
            if territory not in other["territory_set"] \
                    and "WORLD" not in other["territory_set"]:
                continue
            if not half_open_overlap(other["effective_from"], other["effective_to"],
                                     registration["effective_from"],
                                     registration["effective_to"]):
                continue
            total += other["share_bps"]
        if total > MAX_SHARE_BPS_PER_TERRITORY:
            return True
    return False


def _work_state_snapshot(registration):
    work = db.works.get(registration["work_id"])
    if work is None:
        return None, None
    return work, derive.work_rights_state(work)


def _touch_work_if_state_changed(work, before):
    """§2.4: recomputation of a derived field counts as a mutation."""
    if work is None:
        return
    if derive.work_rights_state(work) != before:
        touch(work)


def _enforce_sod(registration):
    work = db.works.get(registration["work_id"])
    if work is None:
        return work
    stamped = work["provisional_match_by_user_id"]
    if stamped is not None and stamped == current_user_id():
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    return work


# --------------------------------------------------------------------------
# create / read / list
# --------------------------------------------------------------------------

@bp.post("/rights-registrations")
@require(ROLE_RIGHTS_HOLDER_USER, ROLE_RIGHTS_OPS_ANALYST)
def create_registration():
    data = validation.body()

    # Item 3: work_id, then claimant_id, then collective_id.
    raw_work_id = data.get("work_id")
    if isinstance(raw_work_id, str) and raw_work_id:
        work = lookup.work(raw_work_id)
    else:
        work = None
    raw_claimant_id = data.get("claimant_id")
    if isinstance(raw_claimant_id, str) and raw_claimant_id:
        claimant = lookup.holder(raw_claimant_id)
    else:
        claimant = None
    raw_collective_id = data.get("collective_id")
    if isinstance(raw_collective_id, str) and raw_collective_id:
        collective = lookup.holder(raw_collective_id)
    else:
        collective = None

    work_id = validation.get_id(data, "work_id")
    claimant_id = validation.get_id(data, "claimant_id")
    right_type = validation.get_enum(data, "right_type", RIGHT_TYPES)
    routing = validation.get_enum(data, "routing", ROUTINGS)
    share_bps = validation.get_int(data, "share_bps", minimum=1, maximum=10000)
    territory_set = validation.get_territory_set(data, "territory_set")
    effective_from = validation.get_date(data, "effective_from")
    effective_to = validation.get_date(data, "effective_to")
    expected_work_version = validation.get_int(data, "expected_work_version")
    collective_id = validation.get_id(
        data, "collective_id", required=False, nullable=True)
    supersede_overlapping = validation.get_bool(
        data, "supersede_overlapping", default=False)

    if routing == "COLLECTIVE" and not collective_id:
        validation.bad("Field 'collective_id' is required when routing is COLLECTIVE.")
    if routing == "DIRECT" and collective_id is not None:
        validation.bad("Field 'collective_id' must be null when routing is DIRECT.")

    if work is None:
        work = lookup.work(work_id)
    if claimant is None:
        claimant = lookup.holder(claimant_id)

    # Item 6: ownership for the entity-backed role.
    if current_role() == ROLE_RIGHTS_HOLDER_USER and claimant_id != current_user_id():
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    # Item 15: optimistic concurrency.
    if expected_work_version != work["version"]:
        raise ApiError("ERR_STALE_WORK_VERSION")

    # Item 17: claim window.
    if not _claim_window_open(work["id"], right_type):
        raise ApiError("ERR_CLAIM_WINDOW_CLOSED")

    # Item 19: half-open interval must be non-degenerate.
    if not effective_to > effective_from:
        raise ApiError("ERR_INVALID_EFFECTIVE_PERIOD")

    # Item 20: routing viability.
    if routing == "COLLECTIVE":
        if collective is None or collective["holder_type"] != "COLLECTIVE":
            raise ApiError("ERR_COLLECTIVE_NOT_ELIGIBLE")
        home = collective["home_territory_code"]
        if home != "WORLD" and territory_set != ["WORLD"] and home not in territory_set:
            raise ApiError("ERR_COLLECTIVE_NOT_ELIGIBLE")
    else:
        if claimant["direct_deal_rate_bps"] is None:
            raise ApiError("ERR_COLLECTIVE_NOT_ELIGIBLE")

    # Item 21: right type must agree with the work and the claimant.
    if not _right_type_agrees(work, claimant, right_type):
        raise ApiError("ERR_RIGHT_TYPE_WORK_MISMATCH")

    record = {
        "work_id": work["id"],
        "claimant_id": claimant["id"],
        "collective_id": collective_id,
        "right_type": right_type,
        "routing": routing,
        "share_bps": share_bps,
        "territory_set": territory_set,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "supersede_overlapping": supersede_overlapping,
        "payee_holder_id": collective_id if routing == "COLLECTIVE" else claimant["id"],
        "status": "SUBMITTED",
        "evidence_round": 0,
        "reviewed_by_user_id": None,
        "disputing_holder_id": None,
        "rejection_reason": None,
    }
    stamp_new(record)
    db.registrations[record["id"]] = record
    touch(work)
    return created_response(serializers.rights_registration(record))


@bp.get("/rights-registrations/<registration_id>")
@require()
def read_registration(registration_id):
    registration = lookup.registration(registration_id)
    return object_response(serializers.rights_registration(registration))


@bp.get("/rights-registrations")
@require()
def list_registrations():
    records = lookup.apply_filters(db.registrations.values(), {
        "work_id": lookup.field("work_id"),
        "claimant_id": lookup.field("claimant_id"),
        "collective_id": lookup.field("collective_id"),
        "payee_holder_id": lookup.field("payee_holder_id"),
        "disputing_holder_id": lookup.field("disputing_holder_id"),
        "status": lookup.field("status"),
        "right_type": lookup.field("right_type"),
    })
    return paginate_and_serialize(records, serializers.rights_registration)


# --------------------------------------------------------------------------
# review loop
# --------------------------------------------------------------------------

@bp.post("/rights-registrations/<registration_id>/review")
@require(ROLE_RIGHTS_OPS_ANALYST)
def review_registration(registration_id):
    registration = lookup.registration(registration_id)
    if registration["status"] not in ("SUBMITTED", "DISPUTED"):
        raise ApiError("ERR_INVALID_REGISTRATION_STATE")
    work, before = _work_state_snapshot(registration)
    registration["status"] = "UNDER_REVIEW"
    touch(registration)
    _touch_work_if_state_changed(work, before)
    return object_response(serializers.rights_registration(registration))


@bp.post("/rights-registrations/<registration_id>/request-evidence")
@require(ROLE_RIGHTS_OPS_ANALYST)
def request_evidence(registration_id):
    registration = lookup.registration(registration_id)
    if registration["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_REGISTRATION_STATE")
    if registration["evidence_round"] >= MAX_EVIDENCE_ROUNDS:
        raise ApiError("ERR_EVIDENCE_ROUNDS_EXHAUSTED")
    registration["status"] = "NEEDS_EVIDENCE"
    touch(registration)
    return object_response(serializers.rights_registration(registration))


@bp.post("/rights-registrations/<registration_id>/evidence")
@require(ROLE_RIGHTS_HOLDER_USER, ROLE_RIGHTS_OPS_ANALYST)
def supply_evidence(registration_id):
    registration = lookup.registration(registration_id)
    if current_role() == ROLE_RIGHTS_HOLDER_USER \
            and registration["claimant_id"] != current_user_id():
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if registration["status"] != "NEEDS_EVIDENCE":
        raise ApiError("ERR_INVALID_REGISTRATION_STATE")
    if registration["evidence_round"] >= MAX_EVIDENCE_ROUNDS:
        raise ApiError("ERR_EVIDENCE_ROUNDS_EXHAUSTED")
    registration["evidence_round"] += 1
    registration["status"] = "UNDER_REVIEW"
    touch(registration)
    return object_response(serializers.rights_registration(registration))


# --------------------------------------------------------------------------
# adjudication
# --------------------------------------------------------------------------

@bp.post("/rights-registrations/<registration_id>/approve")
@require(ROLE_RIGHTS_OPS_ANALYST)
def approve_registration(registration_id):
    registration = lookup.registration(registration_id)

    # Item 7: segregation of duties.
    work = _enforce_sod(registration)

    # Item 9: state.
    if registration["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_REGISTRATION_STATE")

    claimant = db.rights_holders.get(registration["claimant_id"])
    if work is None or claimant is None \
            or not _right_type_agrees(work, claimant, registration["right_type"]):
        raise ApiError("ERR_RIGHT_TYPE_WORK_MISMATCH")

    # The supersede step runs before the ceiling is tested, but nothing is
    # committed until the ceiling has passed.
    victims = _overlapping_supersede_set(registration)
    excluded = set(v["id"] for v in victims)

    # Item 22: aggregate share per concrete territory.
    if _oversubscribed(registration, excluded):
        raise ApiError("ERR_SHARE_OVERSUBSCRIBED")

    before = derive.work_rights_state(work)
    for victim in victims:
        victim["status"] = "SUPERSEDED"
        touch(victim)

    registration["status"] = "APPROVED"
    registration["reviewed_by_user_id"] = current_user_id()
    touch(registration)
    _touch_work_if_state_changed(work, before)

    cascades.approval_cascade(work)
    return object_response(serializers.rights_registration(registration))


@bp.post("/rights-registrations/<registration_id>/reject")
@require(ROLE_RIGHTS_OPS_ANALYST)
def reject_registration(registration_id):
    registration = lookup.registration(registration_id)
    data = validation.body()
    rejection_reason = validation.get_string(data, "rejection_reason")

    _enforce_sod(registration)

    if registration["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_REGISTRATION_STATE")

    work, before = _work_state_snapshot(registration)
    registration["status"] = "REJECTED"
    registration["rejection_reason"] = rejection_reason
    registration["reviewed_by_user_id"] = current_user_id()
    touch(registration)
    _touch_work_if_state_changed(work, before)
    return object_response(serializers.rights_registration(registration))


@bp.post("/rights-registrations/<registration_id>/dispute")
@require(ROLE_RIGHTS_HOLDER_USER, ROLE_RIGHTS_OPS_ANALYST)
def dispute_registration(registration_id):
    registration = lookup.registration(registration_id)
    data = validation.body()

    raw_holder_id = data.get("disputing_holder_id")
    if isinstance(raw_holder_id, str) and raw_holder_id:
        lookup.holder(raw_holder_id)

    disputing_holder_id = validation.get_id(data, "disputing_holder_id")
    lookup.holder(disputing_holder_id)

    if current_role() == ROLE_RIGHTS_HOLDER_USER \
            and disputing_holder_id != current_user_id():
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    if registration["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_REGISTRATION_STATE")

    if disputing_holder_id == registration["claimant_id"] \
            or (registration["collective_id"] is not None
                and disputing_holder_id == registration["collective_id"]):
        raise ApiError("ERR_DISPUTE_BY_CLAIMANT")

    work, before = _work_state_snapshot(registration)
    registration["status"] = "DISPUTED"
    registration["disputing_holder_id"] = disputing_holder_id
    touch(registration)
    _touch_work_if_state_changed(work, before)

    cascades.dispute_cascade(registration)
    return object_response(serializers.rights_registration(registration))
