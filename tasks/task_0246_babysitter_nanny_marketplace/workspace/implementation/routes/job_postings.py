"""JobPosting endpoints (PRD §3.3)."""

from flask import Blueprint, request

import errors
from db import store
from errors import err
from middleware import authenticate, require_roles, get_json, parse_pagination, paginate
from response import ok
from services import validate as v
from services.common import base_record
from services.lookup import get_family, get_job_posting, sorted_by_created
from services.serialize import job_posting_out

bp = Blueprint("job_postings", __name__)

TIERS = {"BASIC", "STANDARD", "PREMIUM"}
CARE_TYPES = {"ONE_TIME", "RECURRING"}


@bp.route("/marketplace/job-postings", methods=["POST"])
def create_posting():
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin", "Family"})
    body = get_json()
    family_id = v.req_str(body, "family_id")
    title = v.req_str(body, "title")
    care_type = v.req_enum(body, "care_type", CARE_TYPES)
    rate = v.req_int(body, "family_pay_rate_cents", minimum=1)
    required_tier = v.opt_enum(body, "required_tier", TIERS, default=None)

    if auth.is_family and auth.user_id != family_id:
        raise err(errors.ERR_FORBIDDEN, "Family may only post for itself")
    family = get_family(family_id)
    if required_tier is None:
        required_tier = family["required_tier"]

    rec = base_record()
    rec.update({
        "family_id": family_id,
        "title": title,
        "care_type": care_type,
        "family_pay_rate_cents": rate,
        "required_tier": required_tier,
        "status": "OPEN",
    })
    store.job_postings[rec["id"]] = rec
    return ok(job_posting_out(rec), status=201)


@bp.route("/marketplace/job-postings/<jid>", methods=["GET"])
def get_one_posting(jid):
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin", "Family", "Caregiver"})
    j = get_job_posting(jid)
    if auth.is_family and auth.user_id != j["family_id"]:
        raise err(errors.ERR_FORBIDDEN, "Family may only read its own postings")
    return ok(job_posting_out(j), status=200)


@bp.route("/marketplace/job-postings", methods=["GET"])
def list_postings():
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin", "Family", "Caregiver"})
    limit, offset = parse_pagination()
    family_id = request.args.get("family_id")
    status = request.args.get("status")
    care_type = request.args.get("care_type")

    items = list(store.job_postings.values())
    if auth.is_family:
        items = [j for j in items if j["family_id"] == auth.user_id]
    if family_id is not None:
        items = [j for j in items if j["family_id"] == family_id]
    if status is not None:
        items = [j for j in items if j["status"] == status]
    if care_type is not None:
        items = [j for j in items if j["care_type"] == care_type]
    items = sorted_by_created(items)
    page, meta = paginate(items, limit, offset)
    return ok([job_posting_out(j) for j in page], status=200, pagination=meta)
