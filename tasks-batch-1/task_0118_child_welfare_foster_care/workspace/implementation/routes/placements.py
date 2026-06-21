"""Placement routes (PRD §3.5 create + match, §3.7 disrupt/end)."""
from flask import Blueprint, request

import clock
import db
import errors
import helpers
import middleware
import response
from services import compute, serialize

bp = Blueprint("placements", __name__)


def _case_plan_for(case_id):
    for p in db.case_plans.values():
        if p["case_id"] == case_id:
            return p
    return None


def _held_tpr_terminated(case_id):
    for h in db.hearings.values():
        if (h["case_id"] == case_id and h["hearing_type"] == "TPR"
                and h["status"] == "HELD" and h.get("ruling") == "TERMINATE_RIGHTS"):
            return True
    return False


def _case_maltreatment(case):
    """The case's originating maltreatment, reached via Investigation -> Referral."""
    investigation = db.investigations.get(case["investigation_id"])
    if investigation is None:
        return None
    referral = db.referrals.get(investigation["referral_id"])
    if referral is None:
        return None
    return referral["alleged_maltreatment"]


@bp.route("/placements", methods=["POST"])
def create_placement():
    _, role = middleware.authenticate()
    middleware.authorize(role, {"Caseworker"})
    body = helpers.get_body()
    child_id = helpers.require_str(body, "child_id")
    foster_home_id = helpers.require_str(body, "foster_home_id")
    expected = helpers.require_int(body, "expected_foster_home_version")

    # Existence: child and home must exist (left-to-right body FK order).
    child = db.children.get(child_id)
    if child is None:
        raise errors.not_found("Child not found.")
    home = db.foster_homes.get(foster_home_id)
    if home is None:
        raise errors.not_found("Foster home not found.")

    # State guard: child must be placeable (IN_HOME first placement, or REMOVED re-placement).
    if child["status"] not in ("IN_HOME", "REMOVED"):
        raise errors.invalid_state("Child is not in a placeable state (IN_HOME or REMOVED).")

    # Business gates, in this fixed order (PRD §3.5):
    # 1. home license_status must be LICENSED or PROVISIONAL.
    if home["license_status"] not in ("LICENSED", "PROVISIONAL"):
        raise errors.home_not_licensed()
    # 2. child age must be <= home max_age_years.
    child_age = compute.age_years(child)
    if child_age > home["max_age_years"]:
        raise errors.age_not_licensed()
    # 3. home must have an open bed.
    active_count = compute.active_placement_count(foster_home_id)
    if active_count >= home["bed_capacity"]:
        raise errors.no_beds()
    # 4. OCC: expected_foster_home_version must equal the home's current version.
    if expected != home["version"]:
        raise errors.stale_version()

    case = db.cases.get(child["case_id"])
    case_maltreatment = _case_maltreatment(case) if case is not None else None

    # Match score computed against PRE-placement home state.
    match_score = compute.placement_match_score(child_age, home, case_maltreatment)

    record = {
        "child_id": child_id,
        "foster_home_id": foster_home_id,
        "case_id": child["case_id"],
        "status": "ACTIVE",
        "start_at": clock.iso(clock.now()),
        "end_at": None,
        "match_score": match_score,
    }
    db.stamp_create(record)
    db.placements[record["id"]] = record

    # Cascade — home: bump version (active_placement_count is computed on read).
    db.bump(home)

    # Cascade — child: -> PLACED, set current_placement_id.
    child["status"] = "PLACED"
    child["current_placement_id"] = record["id"]
    db.bump(child)

    # Cascade — case: first placement removes the child into care.
    if case is not None and case["status"] == "OPEN":
        case["status"] = "IN_PLACEMENT"
        if case.get("removal_date") is None:
            case["removal_date"] = clock.iso(clock.now())
        db.bump(case)

    return response.success(serialize.placement(record), 201)


@bp.route("/placements/<pid>", methods=["GET"])
def get_placement(pid):
    _, role = middleware.authenticate()
    middleware.authorize(role, {"Admin", "Caseworker", "LicensingWorker"})
    record = db.placements.get(pid)
    if record is None:
        raise errors.not_found("Placement not found.")
    return response.success(serialize.placement(record), 200)


@bp.route("/placements", methods=["GET"])
def list_placements():
    _, role = middleware.authenticate()
    middleware.authorize(role, {"Admin", "Caseworker", "LicensingWorker"})
    limit, offset = helpers.pagination()
    child_id = request.args.get("child_id")
    foster_home_id = request.args.get("foster_home_id")
    case_id = request.args.get("case_id")
    status = request.args.get("status")
    records = list(db.placements.values())
    if child_id is not None:
        records = [r for r in records if r["child_id"] == child_id]
    if foster_home_id is not None:
        records = [r for r in records if r["foster_home_id"] == foster_home_id]
    if case_id is not None:
        records = [r for r in records if r["case_id"] == case_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, total = helpers.paginate(records, limit, offset)
    return response.list_success([serialize.placement(r) for r in page], limit, offset, total)


@bp.route("/placements/<pid>/disrupt", methods=["POST"])
def disrupt_placement(pid):
    _, role = middleware.authenticate()
    middleware.authorize(role, {"Caseworker"})
    record = db.placements.get(pid)
    if record is None:
        raise errors.not_found("Placement not found.")
    if record["status"] != "ACTIVE":
        raise errors.invalid_state("Placement is not ACTIVE.")
    record["status"] = "DISRUPTED"
    record["end_at"] = clock.iso(clock.now())
    db.bump(record)
    # Cascade — child -> REMOVED, clear current_placement_id.
    child = db.children.get(record["child_id"])
    if child is not None and child["status"] in ("PLACED", "TRIAL_HOME_VISIT"):
        child["status"] = "REMOVED"
        child["current_placement_id"] = None
        db.bump(child)
    # Cascade — home: active_placement_count decremented (computed on read);
    # bump the home's version so the change is observable.
    home = db.foster_homes.get(record["foster_home_id"])
    if home is not None:
        db.bump(home)
    return response.success(serialize.placement(record), 200)


@bp.route("/placements/<pid>/end-reunified", methods=["POST"])
def end_reunified(pid):
    _, role = middleware.authenticate()
    middleware.authorize(role, {"Caseworker"})
    record = db.placements.get(pid)
    if record is None:
        raise errors.not_found("Placement not found.")
    if record["status"] != "ACTIVE":
        raise errors.invalid_state("Placement is not ACTIVE.")
    case = db.cases.get(record["case_id"])
    if case is None or case["permanency_goal"] != "REUNIFICATION":
        raise errors.goal_mismatch("Case permanency_goal must be REUNIFICATION.")
    plan = _case_plan_for(record["case_id"])
    if plan is None or plan["status"] != "COMPLETED":
        raise errors.plan_not_complete("CasePlan must be COMPLETED.")
    record["status"] = "ENDED_REUNIFIED"
    record["end_at"] = clock.iso(clock.now())
    db.bump(record)
    # active_placement_count is computed on read; ending the placement frees the
    # bed automatically. PRD §3.7 bumps the placement version here (not the home).
    return response.success(serialize.placement(record), 200)


@bp.route("/placements/<pid>/end-adopted", methods=["POST"])
def end_adopted(pid):
    _, role = middleware.authenticate()
    middleware.authorize(role, {"Caseworker"})
    record = db.placements.get(pid)
    if record is None:
        raise errors.not_found("Placement not found.")
    if record["status"] != "ACTIVE":
        raise errors.invalid_state("Placement is not ACTIVE.")
    case = db.cases.get(record["case_id"])
    if case is None or case["permanency_goal"] != "ADOPTION":
        raise errors.goal_mismatch("Case permanency_goal must be ADOPTION.")
    if not _held_tpr_terminated(record["case_id"]):
        raise errors.tpr_not_terminated()
    record["status"] = "ENDED_ADOPTED"
    record["end_at"] = clock.iso(clock.now())
    db.bump(record)
    # active_placement_count is computed on read; ending the placement frees the
    # bed automatically. PRD §3.7 bumps the placement version here (not the home).
    return response.success(serialize.placement(record), 200)
