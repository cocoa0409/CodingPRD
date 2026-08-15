"""Part 150 noise studies and land-use parcels (PRD §3.7; cascade A)."""
from flask import Blueprint, request

from db import db, new_id
from errors import err
from middleware import get_caller, require_role, get_body
from response import success_object, success_list
from serialize import ser_study, ser_parcel
import services
from services import touch, recompute_parcel, priority_score
from util import now
from validate import validate, parse_pagination

bp = Blueprint("studies", __name__)

STAFF = ["NoiseOfficeAdmin", "NoiseAnalyst", "CommunityLiaison",
         "StudyCoordinator", "BoardMember"]

LAND_USES = ["RESIDENTIAL", "SCHOOL", "HOSPITAL", "COMMERCIAL", "INDUSTRIAL",
             "OPEN_SPACE"]

REVOCABLE_STATES = {"SUBMITTED", "SCREENING", "ELIGIBLE_TIER1", "ELIGIBLE_TIER2"}


def _get_study(sid):
    s = db.studies.get(sid)
    if s is None:
        raise err("ERR_NOT_FOUND", f"NoiseStudy {sid} not found")
    return s


def _get_parcel(pid):
    p = db.parcels.get(pid)
    if p is None:
        raise err("ERR_NOT_FOUND", f"LandUseParcel {pid} not found")
    return p


@bp.post("/noise-studies")
def create_study():
    caller = get_caller()
    body = get_body()
    data = validate(body, [
        ("title", "str", True),
        ("baseline_year", "int", True),
        ("description", "str", False),
        ("supersedes_study_id", "str", False),
    ])
    require_role(caller, ["StudyCoordinator"])
    if data.get("supersedes_study_id") is not None \
            and data["supersedes_study_id"] not in db.studies:
        raise err("ERR_STUDY_NOT_FOUND",
                  f"NoiseStudy {data['supersedes_study_id']} not found")
    t = now()
    s = {
        "id": new_id(),
        "title": data["title"],
        "baseline_year": data["baseline_year"],
        "description": data.get("description"),
        "supersedes_study_id": data.get("supersedes_study_id"),
        "status": "SCOPING",
        "adopted_at": None,
        "revision_count": 0,
        "parcels_assessed_count": 0,
        "created_at": t,
        "updated_at": t,
        "version": 1,
    }
    db.studies[s["id"]] = s
    return success_object(ser_study(s), status=201)


@bp.get("/noise-studies")
def list_studies():
    caller = get_caller()
    require_role(caller, STAFF)
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    supersedes = request.args.get("supersedes_study_id")
    items = sorted(db.studies.values(), key=lambda s: s["created_at"])
    if status is not None:
        items = [s for s in items if s["status"] == status]
    if supersedes is not None:
        items = [s for s in items if s.get("supersedes_study_id") == supersedes]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_study(s) for s in page], limit, offset, total)


@bp.get("/noise-studies/<studyId>")
def get_study(studyId):
    caller = get_caller()
    require_role(caller, STAFF)
    s = _get_study(studyId)
    return success_object(ser_study(s))


def _study_transition(studyId, from_state, to_state, mutator=None):
    caller = get_caller()
    get_body()
    require_role(caller, ["StudyCoordinator"])
    s = _get_study(studyId)
    if s["status"] != from_state:
        raise err("ERR_INVALID_STUDY_STATE",
                  f"Transition requires status {from_state}")
    s["status"] = to_state
    if mutator:
        mutator(s)
    touch(s)
    return success_object(ser_study(s))


@bp.post("/noise-studies/<studyId>/start-data-collection")
def start_data_collection(studyId):
    return _study_transition(studyId, "SCOPING", "DATA_COLLECTION")


@bp.post("/noise-studies/<studyId>/release-draft")
def release_draft(studyId):
    return _study_transition(studyId, "DATA_COLLECTION", "DRAFTED")


@bp.post("/noise-studies/<studyId>/open-public-comment")
def open_public_comment(studyId):
    return _study_transition(studyId, "DRAFTED", "PUBLIC_REVIEW")


@bp.post("/noise-studies/<studyId>/request-revision")
def request_revision(studyId):
    caller = get_caller()
    body = get_body()
    validate(body, [("reason", "str", True)])
    require_role(caller, ["StudyCoordinator"])
    s = _get_study(studyId)
    if s["status"] != "PUBLIC_REVIEW":
        raise err("ERR_INVALID_STUDY_STATE",
                  "request-revision requires status PUBLIC_REVIEW")
    s["status"] = "DATA_COLLECTION"
    s["revision_count"] += 1
    touch(s)
    return success_object(ser_study(s))


@bp.post("/noise-studies/<studyId>/adopt")
def adopt_study(studyId):
    caller = get_caller()
    get_body()
    require_role(caller, ["NoiseOfficeAdmin"])
    s = _get_study(studyId)
    if s["status"] != "PUBLIC_REVIEW":
        raise err("ERR_INVALID_STUDY_STATE", "adopt requires status PUBLIC_REVIEW")
    # supersede target must currently be ADOPTED
    target = None
    if s.get("supersedes_study_id"):
        target = db.studies.get(s["supersedes_study_id"])
        if target is None:
            raise err("ERR_STUDY_NOT_FOUND",
                      f"NoiseStudy {s['supersedes_study_id']} not found")
        if target["status"] != "ADOPTED":
            raise err("ERR_INVALID_STUDY_STATE",
                      "The superseded study must currently be ADOPTED")
    s["status"] = "ADOPTED"
    s["adopted_at"] = now()
    touch(s)
    if target is not None:
        target["status"] = "SUPERSEDED"
        touch(target)

    # cascade A hop B: every parcel of the study recomputes under FINAL
    study_parcels = [p for p in db.parcels.values() if p["study_id"] == s["id"]]
    flips = {}  # parcel_id -> (old_eligible, new_eligible)
    for p in study_parcels:
        old_eligible = p["insulation_eligible"]
        changed = recompute_parcel(p, stamp_reassessed=True)
        if changed:
            touch(p)
        flips[p["id"]] = (old_eligible, p["insulation_eligible"])

    # cascade A hop C: revoke applications whose parcel eligibility evaporated;
    # rescore every non-withdrawn application on the study's parcels
    parcel_ids = set(flips.keys())
    for a in db.applications.values():
        if a["parcel_id"] not in parcel_ids:
            continue
        if a["eligibility_status"] == "WITHDRAWN":
            continue
        old_eligible, new_eligible = flips[a["parcel_id"]]
        changed = False
        if (old_eligible and not new_eligible
                and a["eligibility_status"] in REVOCABLE_STATES
                and a["funding_status"] == "UNFUNDED"):
            a["eligibility_status"] = "INELIGIBLE"
            a["decided_at"] = now()
            changed = True
        new_score = priority_score(a)
        if new_score != a["priority_score"]:
            a["priority_score"] = new_score
            changed = True
        if changed:
            touch(a)
    # cascade A hop D: fund pipeline recompute is derived dynamically at read
    return success_object(ser_study(s))


# ------------------------------ parcels ------------------------------------

@bp.post("/noise-studies/<studyId>/parcels")
def create_parcel(studyId):
    caller = get_caller()
    body = get_body()
    data = validate(body, [
        ("parcel_ref", "str", True),
        ("land_use", "enum", True, {"enum": LAND_USES}),
        ("dnl_db_measured", "num", True),
        ("dnl_db_modeled", "num", True),
        ("zone_code", "str", True),
    ])
    require_role(caller, ["StudyCoordinator"])
    s = _get_study(studyId)
    for p in db.parcels.values():
        if p["study_id"] == s["id"] and p["parcel_ref"] == data["parcel_ref"]:
            raise err("ERR_VALIDATION",
                      f"parcel_ref {data['parcel_ref']} already exists in this study")
    t = now()
    p = {
        "id": new_id(),
        "study_id": s["id"],
        "parcel_ref": data["parcel_ref"],
        "land_use": data["land_use"],
        "dnl_db_measured": data["dnl_db_measured"],
        "dnl_db_modeled": data["dnl_db_modeled"],
        "zone_code": data["zone_code"],
        "dnl_db_effective": 0.0,
        "dnl_band": 0,
        "compatibility_status": "COMPATIBLE",
        "insulation_eligible": False,
        "reassessed_at": None,
        "created_at": t,
        "updated_at": t,
        "version": 1,
    }
    recompute_parcel(p)
    db.parcels[p["id"]] = p
    s["parcels_assessed_count"] += 1
    touch(s)
    return success_object(ser_parcel(p), status=201)


@bp.get("/noise-studies/<studyId>/parcels")
def list_parcels(studyId):
    caller = get_caller()
    require_role(caller, STAFF)
    s = _get_study(studyId)
    limit, offset = parse_pagination(request.args)
    items = sorted((p for p in db.parcels.values() if p["study_id"] == s["id"]),
                   key=lambda p: p["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_parcel(p) for p in page], limit, offset, total)


@bp.get("/land-use-parcels/<parcelId>")
def get_parcel(parcelId):
    caller = get_caller()
    require_role(caller, STAFF)
    p = _get_parcel(parcelId)
    return success_object(ser_parcel(p))


@bp.post("/land-use-parcels/<parcelId>/reassess")
def reassess_parcel(parcelId):
    caller = get_caller()
    get_body()
    require_role(caller, ["StudyCoordinator"])
    p = _get_parcel(parcelId)
    recompute_parcel(p, stamp_reassessed=True)
    touch(p)
    return success_object(ser_parcel(p))
