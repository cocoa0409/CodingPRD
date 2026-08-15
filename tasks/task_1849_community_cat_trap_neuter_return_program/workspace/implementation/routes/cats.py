"""Cat lifecycle endpoints (PRD §3.5, §3.6): pathway decision (OCC-guarded),
adoption finalization, long-term confirmation, plus reverse-reachability
lists for appointments and foster placements.

decide-pathway check order (PRD §3.5): existence, then state-transition
legality, then the stale-version rejection (ERR_STALE_VERSION), then
release-readiness (ERR_NOT_RELEASE_READY).
"""

from flask import Blueprint, request

from db import db
from errors import (ApiError, ERR_NOT_RELEASE_READY, ERR_STALE_VERSION,
                    invalid_state, not_found, validation)
from middleware import json_body, require_roles
from response import paginate, success_object
from services.colony_service import recompute_colony
from util import (now_iso, parse_datetime, public, sorted_created, touch)

bp = Blueprint("cats", __name__)

PATHWAYS = {"RETURN_TO_FIELD", "ADOPTION"}


def get_cat_or_404(cat_id):
    cat = db.cats.get(cat_id)
    if cat is None:
        raise not_found("cat")
    return cat


@bp.get("/tnr/cats/<cid>")
@require_roles("ProgramCoordinator", "Caretaker", "AnimalControlOfficer",
               "ClinicStaff", "FosterVolunteer")
def get_cat(cid, user_id, role):
    return success_object(public(get_cat_or_404(cid)))


@bp.post("/tnr/cats/<cid>/decide-pathway")
@require_roles("ProgramCoordinator")
def decide_pathway(cid, user_id, role):
    cat = get_cat_or_404(cid)
    body = json_body()
    pathway = body.get("pathway")
    if pathway is None:
        raise validation("Missing required field: 'pathway'.")
    if pathway not in PATHWAYS:
        raise invalid_state(
            f"No pathway transition exists for pathway {pathway!r}.")

    # --- state-transition legality (priority 4) ---
    # POST_SURGERY: RETURN_TO_FIELD always; ADOPTION only for adults (a kitten
    #   adoption decision requests a transition that does not exist).
    # ADOPTION_PIPELINE: RETURN_TO_FIELD falls through back to POST_SURGERY.
    if cat["status"] == "POST_SURGERY":
        if pathway == "ADOPTION" and cat["is_kitten"]:
            raise invalid_state(
                "Kittens never take the direct ADOPTION branch; they enter the "
                "pipeline through the foster network.")
    elif cat["status"] == "ADOPTION_PIPELINE":
        if pathway != "RETURN_TO_FIELD":
            raise invalid_state(
                "Only the RETURN_TO_FIELD fall-through exists from "
                "ADOPTION_PIPELINE.")
    else:
        raise invalid_state(
            f"Cat is {cat['status']}; a pathway decision requires POST_SURGERY "
            "or ADOPTION_PIPELINE.")

    # --- optimistic concurrency (priority 5, PRD §2.9): non-optional ---
    expected = body.get("expected_cat_version")
    if expected is None or expected != cat["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_cat_version does not match the cat's current "
                       "version.")

    # --- release-readiness (priority 6): no unmarked, unvaccinated cat leaves
    # the program ---
    if not (cat["ear_tipped"] and cat["vaccinated_rabies"]):
        raise ApiError(ERR_NOT_RELEASE_READY, 422,
                       "A pathway decision requires ear_tipped and "
                       "vaccinated_rabies both true.")

    colony = db.colonies.get(cat["colony_id"])

    if cat["status"] == "POST_SURGERY" and pathway == "RETURN_TO_FIELD":
        # No ACTIVE foster placement may exist for the cat.
        if any(p["cat_id"] == cid and p["status"] == "ACTIVE"
               for p in db.foster_placements.values()):
            raise invalid_state(
                "An ACTIVE foster placement exists for this cat.")
        cat["status"] = "RETURNED"
        cat["pathway"] = "RETURN_TO_FIELD"
        cat["_returned_at"] = now_iso()
    elif cat["status"] == "POST_SURGERY" and pathway == "ADOPTION":
        cat["status"] = "ADOPTION_PIPELINE"
        cat["pathway"] = "ADOPTION"
    else:  # ADOPTION_PIPELINE + RETURN_TO_FIELD: adoption fall-through
        cat["status"] = "POST_SURGERY"
        cat["pathway"] = None

    touch(cat)
    # Every pathway decision recomputes the colony's derived fields (PRD §3.5).
    if colony is not None:
        recompute_colony(colony)
    return success_object(public(cat))


@bp.post("/tnr/cats/<cid>/finalize-adoption")
@require_roles("ProgramCoordinator")
def finalize_adoption(cid, user_id, role):
    cat = get_cat_or_404(cid)
    if cat["status"] != "ADOPTION_PIPELINE":
        raise invalid_state(
            f"Cat is {cat['status']}; only ADOPTION_PIPELINE cats can be "
            "finalized as ADOPTED.")
    cat["status"] = "ADOPTED"
    touch(cat)
    colony = db.colonies.get(cat["colony_id"])
    if colony is not None:
        # ADOPTED cats leave the resident denominator (PRD §2.6).
        recompute_colony(colony)
    return success_object(public(cat))


@bp.post("/tnr/cats/<cid>/confirm-long-term")
@require_roles("ProgramCoordinator")
def confirm_long_term(cid, user_id, role):
    cat = get_cat_or_404(cid)
    if cat["status"] != "RETURNED":
        raise invalid_state(
            f"Cat is {cat['status']}; only RETURNED cats can be confirmed "
            "long-term.")
    returned_at = parse_datetime(cat.get("_returned_at", cat["updated_at"]),
                                 "_returned_at")
    qualifying = any(
        s["colony_id"] == cat["colony_id"]
        and s["eartipped_count"] >= 1
        and s["_surveyed_on"] >= returned_at
        for s in db.population_surveys.values())
    if not qualifying:
        raise invalid_state(
            "No qualifying PopulationSurvey (surveyed_on on or after the "
            "RETURNED transition, eartipped_count >= 1) exists for the cat's "
            "colony.")
    cat["status"] = "COLONY_STERILIZED"
    touch(cat)
    colony = db.colonies.get(cat["colony_id"])
    if colony is not None:
        recompute_colony(colony)
    return success_object(public(cat))


# --- reverse reachability ----------------------------------------------------

@bp.get("/tnr/cats/<cid>/appointments")
@require_roles("ProgramCoordinator", "Caretaker", "ClinicStaff")
def list_cat_appointments(cid, user_id, role):
    get_cat_or_404(cid)
    rows = [a for a in db.appointments.values() if a["cat_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    return paginate([public(a) for a in sorted_created(rows)])


@bp.get("/tnr/cats/<cid>/foster-placements")
@require_roles("ProgramCoordinator", "FosterVolunteer", "Caretaker")
def list_cat_foster_placements(cid, user_id, role):
    get_cat_or_404(cid)
    rows = [p for p in db.foster_placements.values() if p["cat_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        rows = [p for p in rows if p["status"] == status]
    return paginate([public(p) for p in sorted_created(rows)])
