"""SiteHostAgreement endpoints."""

from datetime import timedelta

from flask import Blueprint, request

import db
import errors
from middleware import require_roles
from response import success_object, success_list
from routes.helpers import (
    body, require_fields, require_str, require_dt_field,
    get_program_or_404, get_site_or_404, get_agreement_or_404,
    paginate, sort_created,
)
from services import posture as posture_svc
from services.programs import touch
from services.serializers import agreement as serialize_agreement

bp = Blueprint("agreements", __name__)

READ_ROLES = ("ProgramAdmin", "SiteHost", "MunicipalAuditor")


@bp.route("/programs/<program_id>/host-agreements", methods=["POST"])
def create_agreement(program_id):
    require_roles("ProgramAdmin")
    program = get_program_or_404(program_id)
    data = body()
    require_fields(data, "site_id", "host_name", "term_start", "term_end")
    site = get_site_or_404(data["site_id"], program_id)
    host_name = require_str(data, "host_name")
    term_start = require_dt_field(data, "term_start")
    term_end = require_dt_field(data, "term_end")
    cure_period_days = data.get("cure_period_days", 14)
    if isinstance(cure_period_days, bool) or not isinstance(cure_period_days, int):
        errors.raise_err(errors.ERR_INVALID_REQUEST, "cure_period_days must be an integer")

    now = db.iso_now()
    agreement = {
        "id": db.new_id(),
        "program_id": program["id"],
        "site_id": site["id"],
        "host_name": host_name,
        "term_start": term_start,
        "term_end": term_end,
        "cure_period_days": cure_period_days,
        "status": "DRAFT",
        "breach_noticed_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.host_agreements[agreement["id"]] = agreement
    return success_object(serialize_agreement(agreement), status=201)


@bp.route("/programs/<program_id>/host-agreements", methods=["GET"])
def list_agreements(program_id):
    require_roles(*READ_ROLES)
    get_program_or_404(program_id)
    items = [a for a in db.host_agreements.values() if a["program_id"] == program_id]
    if request.args.get("site_id"):
        items = [a for a in items if a["site_id"] == request.args["site_id"]]
    if request.args.get("status"):
        items = [a for a in items if a["status"] == request.args["status"]]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return success_list([serialize_agreement(a) for a in page], limit, offset, total)


@bp.route("/programs/<program_id>/host-agreements/<agreement_id>", methods=["GET"])
def get_agreement(program_id, agreement_id):
    require_roles(*READ_ROLES)
    get_program_or_404(program_id)
    agreement = get_agreement_or_404(agreement_id, program_id)
    return success_object(serialize_agreement(agreement))


@bp.route("/programs/<program_id>/host-agreements/<agreement_id>/activate", methods=["POST"])
def activate_agreement(program_id, agreement_id):
    require_roles("ProgramAdmin")
    get_program_or_404(program_id)
    agreement = get_agreement_or_404(agreement_id, program_id)
    if agreement["status"] != "DRAFT":
        errors.raise_err(errors.ERR_INVALID_STATE, "Agreement must be DRAFT to activate")
    if not agreement["term_end"] > agreement["term_start"]:
        errors.raise_err(errors.ERR_INVALID_TERM, "Agreement term_end must be after term_start")
    # Half-open overlap check against other ACTIVE agreements for same site
    for other in db.host_agreements.values():
        if other["id"] == agreement["id"]:
            continue
        if other["site_id"] != agreement["site_id"]:
            continue
        if other["status"] != "ACTIVE":
            continue
        if agreement["term_start"] < other["term_end"] and other["term_start"] < agreement["term_end"]:
            errors.raise_err(
                errors.ERR_AGREEMENT_OVERLAP,
                "Another ACTIVE agreement for the same site overlaps the requested term",
            )
    if not agreement["term_end"] > db.clock_now():
        errors.raise_err(
            errors.ERR_AGREEMENT_ALREADY_EXPIRED,
            "Cannot activate an agreement whose term_end is in the past",
        )
    agreement["status"] = "ACTIVE"
    touch(agreement)
    # Link site when no other ACTIVE agreement covers it
    site = db.sites.get(agreement["site_id"])
    if site:
        other_active = any(
            a["site_id"] == site["id"] and a["status"] == "ACTIVE" and a["id"] != agreement["id"]
            for a in db.host_agreements.values()
        )
        if not other_active:
            site["host_agreement_id"] = agreement["id"]
            posture_svc.recompute_site_posture(site)
            touch(site)
    return success_object(serialize_agreement(agreement))


@bp.route("/programs/<program_id>/host-agreements/<agreement_id>/breach-notice", methods=["POST"])
def breach_notice(program_id, agreement_id):
    require_roles("ProgramAdmin")
    get_program_or_404(program_id)
    agreement = get_agreement_or_404(agreement_id, program_id)
    if agreement["status"] != "ACTIVE":
        errors.raise_err(errors.ERR_INVALID_STATE, "Agreement must be ACTIVE for breach notice")
    agreement["status"] = "BREACH_NOTICED"
    agreement["breach_noticed_at"] = db.clock_now()
    touch(agreement)
    return success_object(serialize_agreement(agreement))


@bp.route("/programs/<program_id>/host-agreements/<agreement_id>/cure", methods=["POST"])
def cure_agreement(program_id, agreement_id):
    require_roles("ProgramAdmin")
    get_program_or_404(program_id)
    agreement = get_agreement_or_404(agreement_id, program_id)
    if agreement["status"] != "BREACH_NOTICED":
        errors.raise_err(errors.ERR_INVALID_STATE, "Agreement must be BREACH_NOTICED to cure")
    deadline = agreement["breach_noticed_at"] + timedelta(days=agreement["cure_period_days"])
    if not db.clock_now() < deadline:
        errors.raise_err(errors.ERR_CURE_PERIOD_ELAPSED, "Cure period has elapsed")
    agreement["status"] = "ACTIVE"
    agreement["breach_noticed_at"] = None
    touch(agreement)
    return success_object(serialize_agreement(agreement))


@bp.route("/programs/<program_id>/host-agreements/<agreement_id>/terminate", methods=["POST"])
def terminate_agreement(program_id, agreement_id):
    require_roles("ProgramAdmin")
    get_program_or_404(program_id)
    agreement = get_agreement_or_404(agreement_id, program_id)
    if agreement["status"] == "BREACH_NOTICED":
        deadline = agreement["breach_noticed_at"] + timedelta(days=agreement["cure_period_days"])
        if db.clock_now() < deadline:
            errors.raise_err(
                errors.ERR_CURE_PERIOD_NOT_ELAPSED,
                "Termination from BREACH_NOTICED requires cure period to have elapsed",
            )
    elif agreement["status"] != "ACTIVE":
        errors.raise_err(errors.ERR_INVALID_STATE, "Agreement must be ACTIVE or BREACH_NOTICED to terminate")
    agreement["status"] = "TERMINATED"
    touch(agreement)
    site = db.sites.get(agreement["site_id"])
    if site and site.get("host_agreement_id") == agreement["id"]:
        site["host_agreement_id"] = None
        posture_svc.recompute_site_posture(site)
        touch(site)
    return success_object(serialize_agreement(agreement))


# --- Flat aliases ---

@bp.route("/host-agreements", methods=["GET"])
def list_agreements_flat():
    require_roles(*READ_ROLES)
    items = list(db.host_agreements.values())
    if request.args.get("program_id"):
        items = [a for a in items if a["program_id"] == request.args["program_id"]]
    if request.args.get("site_id"):
        items = [a for a in items if a["site_id"] == request.args["site_id"]]
    if request.args.get("status"):
        items = [a for a in items if a["status"] == request.args["status"]]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return success_list([serialize_agreement(a) for a in page], limit, offset, total)


@bp.route("/host-agreements/<agreement_id>", methods=["GET"])
def get_agreement_flat(agreement_id):
    require_roles(*READ_ROLES)
    agreement = get_agreement_or_404(agreement_id)
    return success_object(serialize_agreement(agreement))
