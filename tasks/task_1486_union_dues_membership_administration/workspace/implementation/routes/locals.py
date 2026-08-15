"""Local, MemberClassification, per-capita report creation/list, election
creation/list, assessment-run list — everything mounted under /api/locals."""
from flask import Blueprint, request

import db
import errors
import serializers
import utils
from middleware import require_roles, ALL_ROLES
from response import ok, ok_list
from services import rebate as rebate_svc

bp = Blueprint("locals", __name__, url_prefix="/api/locals")

LOCAL_CONFIG_FIELDS = (
    "default_dues_percent_bp", "default_flat_dues_cents",
    "per_capita_rate_cents", "delinquency_threshold_cents", "grace_periods",
    "notice_cure_days", "reinstatement_base_fee_cents",
)


def get_local_or_404(local_id):
    local = db.store.locals.get(local_id)
    if local is None:
        raise errors.local_not_found()
    return local


@bp.route("", methods=["POST"])
@require_roles("ParentBodyAdmin")
def create_local(user_id, role):
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    name = utils.require_field(body, "name")
    if not isinstance(name, str):
        raise errors.invalid_request("name must be a string")
    dues_method = utils.require_field(body, "dues_method")
    if dues_method not in ("PERCENTAGE_OF_GROSS", "FLAT_RATE"):
        raise errors.invalid_request("dues_method must be PERCENTAGE_OF_GROSS or FLAT_RATE")
    config = {}
    for f in ("default_dues_percent_bp", "default_flat_dues_cents",
              "per_capita_rate_cents", "delinquency_threshold_cents",
              "grace_periods", "notice_cure_days",
              "reinstatement_base_fee_cents", "max_suspensions",
              "expel_after_months"):
        config[f] = utils.require_int(body, f)
    ts = db.fmt_ts(db.now())
    local = {
        "id": utils.new_id(),
        "name": name,
        "dues_method": dues_method,
        "status": "ACTIVE",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.store.next_seq(),
    }
    local.update(config)
    db.store.locals[local["id"]] = local
    return ok(serializers.local(local), 201)


@bp.route("/<local_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_local(user_id, role, local_id):
    return ok(serializers.local(get_local_or_404(local_id)), 200)


@bp.route("/<local_id>", methods=["PATCH"])
@require_roles("ParentBodyAdmin")
def update_local(user_id, role, local_id):
    local = get_local_or_404(local_id)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    for f in LOCAL_CONFIG_FIELDS:
        if f in body:
            v = body[f]
            if not utils.is_int(v):
                raise errors.invalid_request("Field %s must be an integer" % f)
            local[f] = v
    db.touch(local)
    return ok(serializers.local(local), 200)


@bp.route("/<local_id>/close", methods=["POST"])
@require_roles("ParentBodyAdmin")
def close_local(user_id, role, local_id):
    local = get_local_or_404(local_id)
    if local["status"] != "ACTIVE":
        raise errors.local_not_active()
    local["status"] = "CLOSED"
    db.touch(local)
    return ok(serializers.local(local), 200)


# --- MemberClassification -------------------------------------------------

CLASSIFICATION_CODES = ("JOURNEYMAN", "APPRENTICE", "PROBATIONARY", "RETIREE")


@bp.route("/<local_id>/classifications", methods=["POST"])
@require_roles("LocalAdmin")
def create_classification(user_id, role, local_id):
    local = get_local_or_404(local_id)
    if local["status"] != "ACTIVE":
        raise errors.local_not_active()
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    code = utils.require_field(body, "code")
    if code not in CLASSIFICATION_CODES:
        raise errors.invalid_request("code must be one of %s" % ", ".join(CLASSIFICATION_CODES))
    min_dues = utils.require_int(body, "min_monthly_dues_cents")
    dues_percent_bp = utils.optional_int(body, "dues_percent_bp")
    flat_dues_cents = utils.optional_int(body, "flat_dues_cents")
    max_dues = utils.optional_int(body, "max_monthly_dues_cents")
    per_capita_exempt = body.get("per_capita_exempt", False)
    if not isinstance(per_capita_exempt, bool):
        raise errors.invalid_request("per_capita_exempt must be a boolean")
    for c in db.store.classifications.values():
        if c["local_id"] == local_id and c["code"] == code:
            raise errors.duplicate_classification()
    ts = db.fmt_ts(db.now())
    classification = {
        "id": utils.new_id(),
        "local_id": local_id,
        "code": code,
        "dues_percent_bp": dues_percent_bp,
        "flat_dues_cents": flat_dues_cents,
        "min_monthly_dues_cents": min_dues,
        "max_monthly_dues_cents": max_dues,
        "per_capita_exempt": per_capita_exempt,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.store.next_seq(),
    }
    db.store.classifications[classification["id"]] = classification
    return ok(serializers.classification(classification), 201)


@bp.route("/<local_id>/classifications", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_classifications(user_id, role, local_id):
    get_local_or_404(local_id)
    rows = [c for c in db.store.classifications.values()
            if c["local_id"] == local_id]
    rows.sort(key=lambda c: c["_seq"])
    page, meta = utils.paginate(rows)
    return ok_list([serializers.classification(c) for c in page], meta)


# --- PerCapitaReport creation / listing (local-scoped) ---------------------

@bp.route("/<local_id>/per-capita-reports", methods=["POST"])
@require_roles("SecretaryTreasurer")
def create_per_capita_report(user_id, role, local_id):
    local = get_local_or_404(local_id)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    expected = utils.require_int(body, "expected_local_version")
    if expected != local["version"]:
        raise errors.stale_local_version()
    if local["status"] != "ACTIVE":
        raise errors.local_not_active()
    period = utils.require_field(body, "period")
    for r in db.store.per_capita_reports.values():
        if (r["local_id"] == local_id and r["period"] == period
                and r["status"] in ("APPROVED", "SUBMITTED", "PAID")):
            raise errors.report_state_forbidden()
    utils.parse_period(period)
    # A new DRAFT supersedes any existing DRAFT for the same local+period.
    for r in db.store.per_capita_reports.values():
        if (r["local_id"] == local_id and r["period"] == period
                and r["status"] == "DRAFT"):
            r["status"] = "SUPERSEDED"
            db.touch(r)
    member_count = rebate_svc.per_capita_count(local, period)
    rate = local["per_capita_rate_cents"]
    ts = db.fmt_ts(db.now())
    report = {
        "id": utils.new_id(),
        "local_id": local_id,
        "period": period,
        "member_count": member_count,
        "rate_cents": rate,
        "tax_due_cents": member_count * rate,
        "status": "DRAFT",
        "created_by_user_id": user_id,
        "approved_by_user_id": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.store.next_seq(),
    }
    db.store.per_capita_reports[report["id"]] = report
    db.touch(local)  # creation increments Local.version
    return ok(serializers.per_capita_report(report), 201)


@bp.route("/<local_id>/per-capita-reports", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_per_capita_reports(user_id, role, local_id):
    get_local_or_404(local_id)
    rows = [r for r in db.store.per_capita_reports.values()
            if r["local_id"] == local_id]
    period = request.args.get("period")
    status = request.args.get("status")
    if period is not None:
        rows = [r for r in rows if r["period"] == period]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: r["_seq"])
    page, meta = utils.paginate(rows)
    return ok_list([serializers.per_capita_report(r) for r in page], meta)


# --- Election scheduling (local-scoped) ------------------------------------

@bp.route("/<local_id>/elections", methods=["POST"])
@require_roles("LocalAdmin")
def create_election(user_id, role, local_id):
    local = get_local_or_404(local_id)
    if local["status"] != "ACTIVE":
        raise errors.local_not_active()
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    title = utils.require_field(body, "title")
    if not isinstance(title, str):
        raise errors.invalid_request("title must be a string")
    open_at = utils.parse_datetime(utils.require_field(body, "nomination_open_at"))
    close_at = utils.parse_datetime(utils.require_field(body, "nomination_close_at"))
    cutoff_at = utils.parse_datetime(utils.require_field(body, "eligibility_cutoff_at"))
    rgsm = utils.optional_int(body, "required_good_standing_months", 12)
    if rgsm is None:
        rgsm = 12
    if not (open_at < close_at < cutoff_at):
        raise errors.invalid_request(
            "Election window must be strictly ordered: open < close < cutoff")
    # Closed-interval overlap; touching endpoints count as overlap.
    for e in db.store.elections.values():
        if e["local_id"] != local_id:
            continue
        e_open = utils.parse_datetime(e["nomination_open_at"])
        e_close = utils.parse_datetime(e["nomination_close_at"])
        if open_at <= e_close and e_open <= close_at:
            raise errors.election_window_overlap()
    ts = db.fmt_ts(db.now())
    election = {
        "id": utils.new_id(),
        "local_id": local_id,
        "title": title,
        "nomination_open_at": db.fmt_ts(open_at),
        "nomination_close_at": db.fmt_ts(close_at),
        "eligibility_cutoff_at": db.fmt_ts(cutoff_at),
        "required_good_standing_months": rgsm,
        "status": "SCHEDULED",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.store.next_seq(),
    }
    db.store.elections[election["id"]] = election
    return ok(serializers.election(election), 201)


# --- AssessmentRun listing (local-scoped) ----------------------------------

@bp.route("/<local_id>/assessment-runs", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_assessment_runs(user_id, role, local_id):
    get_local_or_404(local_id)
    rows = [r for r in db.store.assessment_runs.values()
            if r["local_id"] == local_id]
    period = request.args.get("period")
    if period is not None:
        rows = [r for r in rows if r["period"] == period]
    rows.sort(key=lambda r: r["_seq"])
    page, meta = utils.paginate(rows)
    return ok_list([serializers.assessment_run(r) for r in page], meta)
