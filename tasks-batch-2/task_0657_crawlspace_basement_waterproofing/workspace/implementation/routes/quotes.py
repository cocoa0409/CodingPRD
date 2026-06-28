"""Quote endpoints (PRD §3.4, §3.5)."""
from flask import Blueprint, request

import db
import errors
import helpers
from clock import clock
from middleware import authenticate, authorize, get_json_body, get_pagination
from response import object_response, array_response
from serializers import serialize, serialize_list
from services import factory

bp = Blueprint("quotes", __name__)

DISCOUNT_CODES = ["SPRING10", "SENIOR15", "NONE"]


def _read_scope(body):
    """Parse scope flags + drain + discount with defaults, enforcing backup-requires-sump."""
    scope = {
        "includes_vapor_barrier": helpers.optional_bool(body, "includes_vapor_barrier", False),
        "includes_sump": helpers.optional_bool(body, "includes_sump", False),
        "includes_dehumidifier": helpers.optional_bool(body, "includes_dehumidifier", False),
        "includes_drain": helpers.optional_bool(body, "includes_drain", False),
        "includes_battery_backup": helpers.optional_bool(body, "includes_battery_backup", False),
    }
    drain_linear_ft = helpers.optional_int(body, "drain_linear_ft", 0)
    if drain_linear_ft < 0:
        raise errors.err(errors.ERR_VALIDATION, "drain_linear_ft must be at least 0")
    discount_code = helpers.optional_enum(body, "discount_code", DISCOUNT_CODES, "NONE")
    return scope, drain_linear_ft, discount_code


def _check_backup_requires_sump(scope):
    # business rule (priority 11): backup requires sump on the same quote.
    if scope["includes_battery_backup"] and not scope["includes_sump"]:
        raise errors.err(errors.ERR_BACKUP_REQUIRES_SUMP, "battery backup requires includes_sump=true")


@bp.route("/jobs/<job_id>/quotes", methods=["POST"])
def create_quote(job_id):
    _uid, role = authenticate()
    authorize(role, ["Estimator"])
    job = helpers.find_or_404(db.jobs, job_id)
    body = get_json_body()
    scope, drain_linear_ft, discount_code = _read_scope(body)
    _check_backup_requires_sump(scope)
    entity = factory.create_quote(job_id, job["footprint_sqft"], scope, drain_linear_ft, discount_code, revision=1)
    return object_response(serialize(entity), status=201)


@bp.route("/quotes/<quote_id>", methods=["GET"])
def get_quote(quote_id):
    _uid, role = authenticate()
    authorize(role, ["Estimator", "Homeowner"])
    entity = helpers.find_or_404(db.quotes, quote_id)
    return object_response(serialize(entity), status=200)


@bp.route("/quotes", methods=["GET"])
def list_quotes():
    _uid, role = authenticate()
    authorize(role, ["Estimator", "Homeowner"])
    limit, offset = get_pagination()
    job_id = request.args.get("job_id")
    status = request.args.get("status")

    def pred(q):
        if job_id is not None and q["job_id"] != job_id:
            return False
        if status is not None and q["status"] != status:
            return False
        return True

    page, total = helpers.paginate_list(db.quotes, limit, offset, pred)
    return array_response(serialize_list(page), limit, offset, total)


@bp.route("/quotes/<quote_id>/send", methods=["POST"])
def send_quote(quote_id):
    _uid, role = authenticate()
    authorize(role, ["Estimator"])
    quote = helpers.find_or_404(db.quotes, quote_id)
    job = db.jobs.items.get(quote["job_id"])
    # state: quote DRAFT and Job in INSPECTED or QUOTED (PRD §3.4).
    if quote["status"] != "DRAFT":
        raise errors.err(errors.ERR_INVALID_STATE, "Only a DRAFT quote can be sent")
    if job is None or job["lifecycle_status"] not in ("INSPECTED", "QUOTED"):
        raise errors.err(errors.ERR_INVALID_STATE, "Quote send requires the job in INSPECTED or QUOTED")

    quote["status"] = "SENT"
    quote["expires_at"] = helpers.iso_from_dt(helpers.add_days(helpers.parse_iso(quote["created_at"]), 30))
    helpers.touch(quote)
    # First send advances the job INSPECTED -> QUOTED.
    if job["lifecycle_status"] == "INSPECTED":
        job["lifecycle_status"] = "QUOTED"
        helpers.touch(job)
    return object_response(serialize(quote), status=200)


@bp.route("/quotes/<quote_id>/revise", methods=["POST"])
def revise_quote(quote_id):
    _uid, role = authenticate()
    authorize(role, ["Estimator"])
    quote = helpers.find_or_404(db.quotes, quote_id)
    body = get_json_body()
    scope, drain_linear_ft, discount_code = _read_scope(body)
    _check_backup_requires_sump(scope)

    # state: SENT (PRD §3.4).
    if quote["status"] != "SENT":
        raise errors.err(errors.ERR_INVALID_STATE, "Only a SENT quote can be revised")

    job = db.jobs.items.get(quote["job_id"])
    new_quote = factory.create_quote(
        quote["job_id"], job["footprint_sqft"], scope, drain_linear_ft, discount_code,
        revision=quote["revision"] + 1,
    )
    quote["status"] = "REVISED"
    helpers.touch(quote)
    return object_response(serialize(new_quote), status=201)


@bp.route("/quotes/<quote_id>/accept", methods=["POST"])
def accept_quote(quote_id):
    _uid, role = authenticate()
    authorize(role, ["Homeowner"])
    quote = helpers.find_or_404(db.quotes, quote_id)
    body = get_json_body()
    expected_quote_version = helpers.require_int(body, "expected_quote_version")

    job = db.jobs.items.get(quote["job_id"])
    # state legality (priority 6): quote SENT and Job QUOTED.
    if quote["status"] != "SENT":
        raise errors.err(errors.ERR_INVALID_STATE, "Only a SENT quote can be accepted")
    if job is None or job["lifecycle_status"] != "QUOTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Quote accept requires the job in QUOTED")

    # OCC (priority 7).
    if expected_quote_version != quote["version"]:
        raise errors.err(errors.ERR_STALE_VERSION, "expected_quote_version does not match the Quote's current version")

    # quote expiry (priority 8): clock strictly before expires_at.
    expires_at = helpers.parse_iso(quote["expires_at"])
    if clock.now() >= expires_at:
        raise errors.err(errors.ERR_QUOTE_EXPIRED, "Quote has expired")

    quote["status"] = "ACCEPTED"
    helpers.touch(quote)
    job["accepted_quote_id"] = quote["id"]
    job["lifecycle_status"] = "SOLD"
    helpers.touch(job)
    # decline sibling SENT quotes on the same job.
    for q in db.quotes.items.values():
        if q["id"] != quote_id and q["job_id"] == quote["job_id"] and q["status"] == "SENT":
            q["status"] = "DECLINED"
            helpers.touch(q)
    return object_response(serialize(quote), status=200)


@bp.route("/quotes/<quote_id>/decline", methods=["POST"])
def decline_quote(quote_id):
    _uid, role = authenticate()
    authorize(role, ["Homeowner"])
    quote = helpers.find_or_404(db.quotes, quote_id)
    if quote["status"] != "SENT":
        raise errors.err(errors.ERR_INVALID_STATE, "Only a SENT quote can be declined")
    quote["status"] = "DECLINED"
    helpers.touch(quote)
    return object_response(serialize(quote), status=200)


@bp.route("/quotes/<quote_id>/expire", methods=["POST"])
def expire_quote(quote_id):
    _uid, role = authenticate()
    authorize(role, ["Estimator"])
    quote = helpers.find_or_404(db.quotes, quote_id)
    # state: SENT (PRD §3.4).
    if quote["status"] != "SENT":
        raise errors.err(errors.ERR_INVALID_STATE, "Only a SENT quote can be expired")
    # requires current_utc >= expires_at.
    expires_at = helpers.parse_iso(quote["expires_at"])
    if clock.now() < expires_at:
        raise errors.err(errors.ERR_INVALID_STATE, "Quote not yet past its expires_at")
    quote["status"] = "EXPIRED"
    helpers.touch(quote)
    return object_response(serialize(quote), status=200)
