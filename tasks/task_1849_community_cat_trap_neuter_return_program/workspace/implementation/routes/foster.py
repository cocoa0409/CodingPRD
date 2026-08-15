"""Foster network (PRD §3.6).

Placement check order (PRD §3.6): existence of the cat and the home; state
(cat POST_SURGERY); release-readiness (ERR_NOT_RELEASE_READY); the kitten
rule (ERR_NOT_A_KITTEN); and home availability (ERR_FOSTER_HOME_FULL when the
home is not ACTIVE or current_kittens has reached capacity_kittens).

Graduation and return-to-program are FosterVolunteer actions on their own
home (placement.foster_home_id must equal X-User-ID, else
ERR_OWNERSHIP_MISMATCH), requiring the cat IN_FOSTER and the placement
ACTIVE. Graduation sends the kitten to ADOPTION_PIPELINE; return-to-program
loops it back to POST_SURGERY with pathway reset to null and recomputes the
colony's derived fields (PRD §2.6 names a foster return as a recompute
trigger).
"""

from flask import Blueprint, request

from db import db
from errors import (ApiError, ERR_FOSTER_HOME_FULL, ERR_NOT_A_KITTEN,
                    ERR_NOT_RELEASE_READY, ERR_OWNERSHIP_MISMATCH,
                    invalid_state, not_found)
from middleware import json_body, require_roles
from response import paginate, success_object
from services.colony_service import recompute_colony
from util import now_iso, public, req_int, req_str, sorted_created, stamp_common, touch

bp = Blueprint("foster", __name__)


def get_home_or_404(home_id):
    home = db.foster_homes.get(home_id)
    if home is None:
        raise not_found("foster home")
    return home


def get_placement_or_404(placement_id):
    placement = db.foster_placements.get(placement_id)
    if placement is None:
        raise not_found("foster placement")
    return placement


@bp.post("/tnr/foster-homes")
@require_roles("ProgramCoordinator")
def create_foster_home(user_id, role):
    body = json_body()
    volunteer_name = req_str(body, "volunteer_name")
    capacity_kittens = req_int(body, "capacity_kittens", minimum=1)
    home = stamp_common({
        "volunteer_name": volunteer_name,
        "capacity_kittens": capacity_kittens,
        "current_kittens": 0,
        "status": "ACTIVE",
    })
    db.foster_homes[home["id"]] = home
    return success_object(public(home), status=201)


@bp.get("/tnr/foster-homes/<hid>")
@require_roles("ProgramCoordinator", "FosterVolunteer")
def get_foster_home(hid, user_id, role):
    return success_object(public(get_home_or_404(hid)))


@bp.get("/tnr/foster-homes/<hid>/placements")
@require_roles("ProgramCoordinator", "FosterVolunteer")
def list_home_placements(hid, user_id, role):
    get_home_or_404(hid)
    rows = [p for p in db.foster_placements.values() if p["foster_home_id"] == hid]
    status = request.args.get("status")
    if status is not None:
        rows = [p for p in rows if p["status"] == status]
    return paginate([public(p) for p in sorted_created(rows)])


@bp.post("/tnr/foster-placements")
@require_roles("ProgramCoordinator")
def create_foster_placement(user_id, role):
    body = json_body()
    cat_id = req_str(body, "cat_id")
    foster_home_id = req_str(body, "foster_home_id")

    # existence, body FKs in declared order
    cat = db.cats.get(cat_id)
    if cat is None:
        raise not_found("cat")
    home = db.foster_homes.get(foster_home_id)
    if home is None:
        raise not_found("foster home")

    # state
    if cat["status"] != "POST_SURGERY":
        raise invalid_state(
            f"Cat is {cat['status']}; foster placement requires POST_SURGERY.")

    # release-readiness: no unmarked or unvaccinated kitten enters a home
    if not (cat["ear_tipped"] and cat["vaccinated_rabies"]):
        raise ApiError(ERR_NOT_RELEASE_READY, 422,
                       "Foster placement requires ear_tipped and "
                       "vaccinated_rabies both true.")

    # kitten rule: adults may not enter foster homes
    if not cat["is_kitten"]:
        raise ApiError(ERR_NOT_A_KITTEN, 422,
                       "Foster placement requires a kitten "
                       "(approximate_age_months < 6).")

    # home availability
    if home["status"] != "ACTIVE" or home["current_kittens"] >= home["capacity_kittens"]:
        raise ApiError(ERR_FOSTER_HOME_FULL, 409,
                       "Foster home is not ACTIVE or is at capacity.")

    placement = stamp_common({
        "cat_id": cat_id,
        "foster_home_id": foster_home_id,
        "placed_at": now_iso(),
        "status": "ACTIVE",
    })
    db.foster_placements[placement["id"]] = placement
    cat["status"] = "IN_FOSTER"
    cat["pathway"] = "ADOPTION"
    touch(cat)
    home["current_kittens"] += 1
    touch(home)
    return success_object(public(placement), status=201)


def _end_placement(placement_id, user_id, end_status):
    placement = get_placement_or_404(placement_id)
    cat = db.cats.get(placement["cat_id"])
    if cat is None or cat["status"] != "IN_FOSTER":
        raise invalid_state("The placement's cat must stand IN_FOSTER.")
    if placement["status"] != "ACTIVE":
        raise invalid_state(
            f"Placement is {placement['status']}; only ACTIVE placements can "
            "be ended.")
    if placement["foster_home_id"] != user_id:
        raise ApiError(ERR_OWNERSHIP_MISMATCH, 403,
                       "A FosterVolunteer may only operate their own home.")
    return placement, cat


@bp.post("/tnr/foster-placements/<pid>/graduate")
@require_roles("FosterVolunteer")
def graduate(pid, user_id, role):
    placement, cat = _end_placement(pid, user_id, "ENDED_ADOPTION")
    placement["status"] = "ENDED_ADOPTION"
    touch(placement)
    cat["status"] = "ADOPTION_PIPELINE"
    touch(cat)
    home = db.foster_homes.get(placement["foster_home_id"])
    if home is not None:
        home["current_kittens"] -= 1
        touch(home)
    return success_object(public(placement))


@bp.post("/tnr/foster-placements/<pid>/return-to-program")
@require_roles("FosterVolunteer")
def return_to_program(pid, user_id, role):
    placement, cat = _end_placement(pid, user_id, "ENDED_RETURNED")
    placement["status"] = "ENDED_RETURNED"
    touch(placement)
    cat["status"] = "POST_SURGERY"
    cat["pathway"] = None  # decision re-opened
    touch(cat)
    home = db.foster_homes.get(placement["foster_home_id"])
    if home is not None:
        home["current_kittens"] -= 1
        touch(home)
    colony = db.colonies.get(cat["colony_id"])
    if colony is not None:
        # PRD §2.6 lists a foster return among the recompute triggers.
        recompute_colony(colony)
    return success_object(public(placement))
