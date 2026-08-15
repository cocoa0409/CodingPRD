"""DropEvent endpoints."""

from flask import Blueprint, request

import db
import errors
from middleware import require_roles
from response import success_object, success_list
from routes.helpers import (
    body, require_fields, require_number, require_dt_field, occ_check,
    get_program_or_404, get_site_or_404, get_drop_or_404,
    paginate, sort_created,
)
from services import posture as posture_svc
from services.drops import serialize_drop, accept_drop, reject_drop
from services.programs import touch, site_posture_touch

bp = Blueprint("drops", __name__)

READ_ROLES = ("ProgramAdmin", "SiteHost", "Participant", "MunicipalAuditor")


def _material_in_season(material):
    """material_season_window calc: annual MM-DD window, inclusive both ends,
    may wrap year boundary."""
    now = db.clock_now()
    md = f"{now.month:02d}-{now.day:02d}"
    start = material["accepted_start_month_day"]
    end = material["accepted_end_month_day"]
    if start <= end:
        return start <= md <= end
    return md >= start or md <= end


@bp.route("/programs/<program_id>/sites/<site_id>/drops", methods=["POST"])
def create_drop(program_id, site_id):
    user_id, role = require_roles("Participant")
    program = get_program_or_404(program_id)
    site = get_site_or_404(site_id, program_id)
    data = body()
    require_fields(
        data, "participant_id", "access_grant_id", "material_category_id",
        "gross_weight_kg", "contamination_kg", "occurred_at",
    )

    participant_id = data["participant_id"]
    if not isinstance(participant_id, str):
        errors.raise_err(errors.ERR_INVALID_REQUEST, "participant_id must be a string")
    access_grant_id = data["access_grant_id"]
    if not isinstance(access_grant_id, str):
        errors.raise_err(errors.ERR_INVALID_REQUEST, "access_grant_id must be a string")
    material_category_id = data["material_category_id"]
    if not isinstance(material_category_id, str):
        errors.raise_err(errors.ERR_INVALID_REQUEST, "material_category_id must be a string")

    gross = require_number(data, "gross_weight_kg")
    contam = require_number(data, "contamination_kg")
    occurred_at = require_dt_field(data, "occurred_at")

    if gross <= 0:
        errors.raise_err(errors.ERR_INVALID_REQUEST, "gross_weight_kg must be > 0")
    if contam < 0 or contam > gross:
        errors.raise_err(
            errors.ERR_INVALID_REQUEST,
            "contamination_kg must be in [0, gross_weight_kg]",
        )

    # Priority 4: OCC on Site.version
    occ_check(site, data.get("expected_site_version"), "expected_site_version")

    # Priority 6: posture gate
    posture = site["posture"]
    if posture in ("SUSPENDED", "CLOSED"):
        errors.raise_err(
            errors.ERR_SITE_POSTURE_BLOCKS_DROP,
            "Site posture rejects drops",
        )
    if posture == "WATCH" and gross > 5:
        errors.raise_err(
            errors.ERR_SITE_POSTURE_BLOCKS_DROP,
            "WATCH posture rejects drops > 5 kg gross",
        )

    # Priority 7: material active and in season
    material = db.materials.get(material_category_id)
    if not material or material["program_id"] != program_id:
        errors.raise_err(errors.ERR_MATERIAL_NOT_ACCEPTED, "Material category not found")
    if not material["active"] or not _material_in_season(material):
        errors.raise_err(
            errors.ERR_MATERIAL_NOT_ACCEPTED,
            "MaterialCategory inactive or outside its seasonal acceptance window",
        )

    # Priority 8: access grant validity
    grant = db.grants.get(access_grant_id)
    if (
        not grant
        or grant["status"] != "ACTIVE"
        or grant["participant_id"] != participant_id
        or grant["site_id"] != site["id"]
        or grant.get("buckets_checked_out", 0) >= grant["bucket_quota"]
    ):
        errors.raise_err(
            errors.ERR_ACCESS_GRANT_INVALID,
            "Access grant not ACTIVE, wrong participant/site, or bucket quota exhausted",
        )

    # Priority 9: occurred_at <= clock and within host agreement term
    now = db.clock_now()
    if occurred_at > now:
        errors.raise_err(
            errors.ERR_DROP_OUTSIDE_AGREEMENT_TERM,
            "occurred_at must not be in the future",
        )
    agreement = None
    if site.get("host_agreement_id"):
        agreement = db.host_agreements.get(site["host_agreement_id"])
    if not agreement or agreement["status"] != "ACTIVE":
        errors.raise_err(
            errors.ERR_DROP_OUTSIDE_AGREEMENT_TERM,
            "Site has no ACTIVE host agreement",
        )
    if not (agreement["term_start"] <= occurred_at < agreement["term_end"]):
        errors.raise_err(
            errors.ERR_DROP_OUTSIDE_AGREEMENT_TERM,
            "occurred_at outside the site's host agreement term",
        )

    # Create the drop
    provisional_net = db.round_kg(gross - contam)
    now_iso = db.iso_now()
    drop = {
        "id": db.new_id(),
        "site_id": site["id"],
        "participant_id": participant_id,
        "access_grant_id": access_grant_id,
        "material_category_id": material_category_id,
        "gross_weight_kg": gross,
        "contamination_kg": contam,
        "provisional_net_kg": provisional_net,
        "final_net_kg": None,
        "credit_state": "UNCREDITED",
        "verification_state": "PENDING_AUDIT",
        "processing_batch_id": None,
        "occurred_at": occurred_at,
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
    }
    db.drops[drop["id"]] = drop

    # Side effects: stored_kg += provisional; posture recompute; site version +1
    site["stored_kg"] = db.round_kg(float(site["stored_kg"]) + provisional_net)
    site_posture_touch(site)

    return success_object(serialize_drop(drop), status=201)


@bp.route("/programs/<program_id>/sites/<site_id>/drops", methods=["GET"])
def list_drops(program_id, site_id):
    require_roles(*READ_ROLES)
    get_program_or_404(program_id)
    get_site_or_404(site_id, program_id)
    items = [d for d in db.drops.values() if d["site_id"] == site_id]
    if request.args.get("participant_id"):
        items = [d for d in items if d["participant_id"] == request.args["participant_id"]]
    if request.args.get("verification_state"):
        items = [d for d in items if d["verification_state"] == request.args["verification_state"]]
    if request.args.get("credit_state"):
        items = [d for d in items if d["credit_state"] == request.args["credit_state"]]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return success_list([serialize_drop(d) for d in page], limit, offset, total)


@bp.route("/programs/<program_id>/sites/<site_id>/drops/<drop_id>", methods=["GET"])
def get_drop(program_id, site_id, drop_id):
    require_roles(*READ_ROLES)
    get_program_or_404(program_id)
    get_site_or_404(site_id, program_id)
    drop = get_drop_or_404(drop_id, site_id)
    return success_object(serialize_drop(drop))


@bp.route("/programs/<program_id>/sites/<site_id>/drops/<drop_id>/accept", methods=["POST"])
def accept_drop_endpoint(program_id, site_id, drop_id):
    require_roles("SiteHost")
    get_program_or_404(program_id)
    site = get_site_or_404(site_id, program_id)
    drop = get_drop_or_404(drop_id, site_id)
    if site.get("archived"):
        errors.raise_err(errors.ERR_INVALID_STATE, "Site is archived")
    if drop["verification_state"] != "PENDING_AUDIT":
        errors.raise_err(errors.ERR_INVALID_STATE, "Drop must be PENDING_AUDIT to accept")
    accept_drop(drop)
    return success_object(serialize_drop(drop))


@bp.route("/programs/<program_id>/sites/<site_id>/drops/<drop_id>/reject", methods=["POST"])
def reject_drop_endpoint(program_id, site_id, drop_id):
    require_roles("SiteHost")
    get_program_or_404(program_id)
    get_site_or_404(site_id, program_id)
    drop = get_drop_or_404(drop_id, site_id)
    if drop["verification_state"] != "FLAGGED_CONTAMINATED":
        errors.raise_err(errors.ERR_INVALID_STATE, "Drop must be FLAGGED_CONTAMINATED to reject")
    reject_drop(drop)
    return success_object(serialize_drop(drop))


# --- Flat aliases ---

@bp.route("/drops", methods=["GET"])
def list_drops_flat():
    require_roles(*READ_ROLES)
    items = list(db.drops.values())
    for param in ("site_id", "participant_id", "access_grant_id",
                  "material_category_id", "processing_batch_id",
                  "verification_state", "credit_state"):
        if request.args.get(param):
            items = [d for d in items if str(d.get(param)) == request.args[param]]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return success_list([serialize_drop(d) for d in page], limit, offset, total)


@bp.route("/drops/<drop_id>", methods=["GET"])
def get_drop_flat(drop_id):
    require_roles(*READ_ROLES)
    drop = get_drop_or_404(drop_id)
    return success_object(serialize_drop(drop))
