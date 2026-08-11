"""Mail jobs: creation, quoting, scheduling, commitment, void, drop, EDDM routes."""
from flask import Blueprint, request

import calc
import derive
import enums
import envelope
import ladder
import serial
import services
import store
from errors import ApiError
from ladder import Ctx
from model import new_row, touch
from store import db

bp = Blueprint("jobs", __name__)

JOB_READ_ROLES = ["PlatformAdmin", "AccountOwner", "CampaignManager",
                  "ProductionOperator", "ComplianceOfficer"]


def _job_state(job, allowed):
    if job["status"] not in allowed:
        raise ApiError("ERR_MAIL_JOB_INVALID_STATE")


@bp.route("/mail/mail-jobs", methods=["POST"])
def create_mail_job():
    ctx = Ctx(["PlatformAdmin", "AccountOwner", "CampaignManager"])
    ctx.fk("campaign", "campaign_id")
    ctx.fk("template", "template_id")
    ctx.fk("mailing_list", "mailing_list_id")
    ctx.scope(lambda: ctx.get("campaign")["account_id"] if ctx.get("campaign") else None)
    ctx.fields(required=[("campaign_id", "str"), ("template_id", "str"),
                         ("job_kind", "str"), ("mail_class", "str")],
               optional=[("mailing_list_id", "str"), ("eddm_rate_variant", "str"),
                         ("target_in_home_date", "date")])
    ctx.enums([("job_kind", enums.JOB_KINDS), ("mail_class", enums.MAIL_CLASSES),
               ("eddm_rate_variant", enums.EDDM_RATE_VARIANTS)])
    ctx.gate(lambda: ctx.get("campaign"))
    ctx.at(14, lambda: _kind_agreement(ctx))
    ctx.at(16, lambda: _create_list_state(ctx))
    ctx.run()
    row = new_row({
        "campaign_id": ctx.body["campaign_id"],
        "template_id": ctx.body["template_id"],
        "mailing_list_id": ctx.body.get("mailing_list_id"),
        "job_kind": ctx.body["job_kind"],
        "mail_class": ctx.body["mail_class"],
        "eddm_rate_variant": ctx.body.get("eddm_rate_variant"),
        "status": "DRAFT",
        "pinned_template_version": None,
        "automation_piece_count": 0,
        "retail_piece_count": 0,
        "unmailable_piece_count": 0,
        "eddm_piece_count": 0,
        "billable_piece_count": 0,
        "presort_tier": "UNASSIGNED",
        "provisional_postage_cents": None,
        "final_postage_cents": None,
        "handling_fee_cents": None,
        "volume_credit_cents": None,
        "total_due_cents": None,
        "drawn_postage_cents": 0,
        "target_in_home_date": store.parse_date(ctx.body.get("target_in_home_date")),
        "mail_date": None,
        "blackout_shifted_days": 0,
        "scheduled_at": None,
    })
    db.mail_jobs[row["id"]] = row
    return envelope.object_response(serial.mail_job(row), 201)


def _kind_agreement(ctx):
    kind = ctx.body.get("job_kind")
    mail_class = ctx.body.get("mail_class")
    list_id = ctx.body.get("mailing_list_id")
    variant = ctx.body.get("eddm_rate_variant")
    if kind == "ADDRESSED":
        if not list_id or mail_class not in ("FIRST_CLASS", "MARKETING_MAIL") or variant:
            raise ApiError("ERR_JOB_KIND_MISMATCH")
    else:
        if list_id or mail_class != "EDDM" or not variant:
            raise ApiError("ERR_JOB_KIND_MISMATCH")


def _create_list_state(ctx):
    if ctx.body.get("job_kind") != "ADDRESSED":
        return
    lst = ctx.get("mailing_list")
    if lst is None:
        return
    if lst["import_status"] not in ("CASS_RUN", "DEDUPED", "LOCKED"):
        raise ApiError("ERR_LIST_INVALID_STATE")


@bp.route("/mail/mail-jobs/<mail_job_id>", methods=["GET"])
def get_mail_job(mail_job_id):
    ctx = Ctx(JOB_READ_ROLES)
    ctx.path("mail_job", mail_job_id)
    ctx.scope(lambda: derive.job_account_id(ctx.get("mail_job")))
    ctx.run()
    return envelope.object_response(serial.mail_job(ctx.get("mail_job")), 200)


@bp.route("/mail/mail-jobs", methods=["GET"])
def list_mail_jobs():
    ctx = Ctx(JOB_READ_ROLES)
    ctx.run()
    rows = list(db.mail_jobs.values())
    for field in ("campaign_id", "template_id", "mailing_list_id", "status", "job_kind"):
        wanted = request.args.get(field)
        if wanted is not None:
            rows = [r for r in rows if r[field] == wanted]
    rows = envelope.sort_rows(rows)
    page, limit, offset, total = envelope.paginate(rows, request.args)
    return envelope.list_response([serial.mail_job(r) for r in page], limit, offset, total)


# ------------------------------------------------------------------ quoting
@bp.route("/mail/mail-jobs/<mail_job_id>/estimate", methods=["POST"])
def estimate_job(mail_job_id):
    ctx = Ctx(["PlatformAdmin", "AccountOwner", "CampaignManager"])
    ctx.path("mail_job", mail_job_id)
    ctx.scope(lambda: derive.job_account_id(ctx.get("mail_job")))
    ctx.gate(lambda: ladder.campaign_of_job(ctx.get("mail_job")))
    ctx.at(17, lambda: _job_state(ctx.get("mail_job"), ("DRAFT", "PROOFED")))
    ctx.at(33, lambda: _eddm_eligibility(ctx.get("mail_job")))
    ctx.at(35, lambda: _billable_gate(ctx, "PROVISIONAL"))
    ctx.run()
    job = ctx.get("mail_job")
    counts = ctx.derived["counts"]
    postage = calc.postage_for(job, counts["automation_piece_count"],
                               counts["retail_piece_count"],
                               counts["eddm_piece_count"], counts["presort_tier"])
    services.write_job_counts(job, counts)
    job["provisional_postage_cents"] = postage
    touch(job)
    return envelope.object_response(serial.mail_job(job), 200)


def _eddm_eligibility(job):
    if job["job_kind"] != "EDDM":
        return
    calc.eddm_route_pricing(job, derive.job_routes(job["id"]))


def _billable_gate(ctx, variant):
    job = ctx.get("mail_job")
    counts = services.refresh_job_counts(job, variant)
    ctx.derived["counts"] = counts
    if counts["billable_piece_count"] < 1:
        raise ApiError("ERR_NO_MAILABLE_PIECES")


# ---------------------------------------------------------------- scheduling
@bp.route("/mail/mail-jobs/<mail_job_id>/schedule", methods=["POST"])
def schedule_job(mail_job_id):
    ctx = Ctx(["PlatformAdmin", "CampaignManager"])
    ctx.path("mail_job", mail_job_id)
    ctx.fields(optional=[("target_in_home_date", "date")])
    ctx.gate(lambda: ladder.campaign_of_job(ctx.get("mail_job")))
    # Adjudication of friction 4: a schedule request that supplies no
    # target_in_home_date while the job holds none is a MISSING REQUIRED INPUT
    # and answers ERR_VALIDATION at rung 6.  The alternative reading would have
    # to compare a null date at a temporal rung, which no rung defines; this
    # reading leaves every temporal rung (27, 28, 29) reachable with real dates.
    ctx.at(6, lambda: _anchor_present(ctx))
    ctx.at(17, lambda: _job_state(ctx.get("mail_job"), ("DRAFT", "PROOFED")))
    ctx.at(24, lambda: ctx.derived.__setitem__(
        "approval", services.approval_gate(ctx.get("mail_job"))))
    ctx.at(27, lambda: _derive_schedule(ctx))
    ctx.run()
    job = ctx.get("mail_job")
    if ctx.body.get("target_in_home_date") is not None:
        job["target_in_home_date"] = store.parse_date(ctx.body["target_in_home_date"])
    mail_date, in_home, shift = ctx.derived["derivation"]
    job["mail_date"] = mail_date
    job["blackout_shifted_days"] = shift
    job["scheduled_at"] = store.now()
    job["pinned_template_version"] = ctx.derived["approval"]["pinned_template_version"]
    job["status"] = "SCHEDULED"
    touch(job)
    return envelope.object_response(serial.mail_job(job), 200)


def _anchor_present(ctx):
    if ctx.body.get("target_in_home_date") is not None:
        return
    if ctx.get("mail_job")["target_in_home_date"] is None:
        raise ApiError("ERR_VALIDATION", "Missing required field 'target_in_home_date'.")


def _derive_schedule(ctx):
    job = ctx.get("mail_job")
    anchor = ctx.body.get("target_in_home_date")
    anchor_date = store.parse_date(anchor) if anchor is not None else job["target_in_home_date"]
    ctx.derived["derivation"] = calc.mail_date_derivation(
        anchor_date, job["mail_class"], "ANCHOR_IN_HOME")


# --------------------------------------------------------------- commitment
@bp.route("/mail/mail-jobs/<mail_job_id>/commit", methods=["POST"])
def commit_job(mail_job_id):
    ctx = Ctx(["PlatformAdmin", "CampaignManager"])
    ctx.path("mail_job", mail_job_id)
    ctx.gate(lambda: ladder.campaign_of_job(ctx.get("mail_job")))
    ctx.at(16, lambda: _commit_list_state(ctx.get("mail_job")))
    ctx.at(17, lambda: _job_state(ctx.get("mail_job"), ("SCHEDULED",)))
    ctx.at(24, lambda: services.approval_gate(ctx.get("mail_job")))
    ctx.at(33, lambda: _eddm_eligibility(ctx.get("mail_job")))
    ctx.at(34, lambda: _eddm_bounds(ctx.get("mail_job")))
    ctx.at(35, lambda: _billable_gate(ctx, "FINAL"))
    ctx.at(41, lambda: _settle(ctx))
    ctx.run()
    job = ctx.get("mail_job")
    counts = ctx.derived["counts"]
    postage, handling, credit, total = ctx.derived["settlement"]
    campaign = db.campaigns[job["campaign_id"]]
    services.write_job_counts(job, counts)
    job["final_postage_cents"] = postage
    job["handling_fee_cents"] = handling
    job["volume_credit_cents"] = credit
    job["total_due_cents"] = total
    job["drawn_postage_cents"] = total
    job["status"] = "COMMITTED"
    services.append_ledger(campaign["account_id"], "DRAW", total, "commit mail job",
                           campaign_id=campaign["id"], mail_job_id=job["id"])
    if job["job_kind"] == "ADDRESSED":
        for record in calc.surviving_records(job, "FINAL"):
            if record["mail_status"] == "NOT_MAILED":
                record["mail_status"] = "QUEUED"
                record["last_mail_job_id"] = job["id"]
                touch(record)
    touch(job)
    return envelope.object_response(serial.mail_job(job), 200)


def _commit_list_state(job):
    if job["job_kind"] != "ADDRESSED":
        return
    lst = db.mailing_lists.get(job["mailing_list_id"])
    if lst is None or lst["import_status"] != "LOCKED":
        raise ApiError("ERR_LIST_INVALID_STATE")


def _eddm_bounds(job):
    if job["job_kind"] != "EDDM":
        return
    routes = derive.job_routes(job["id"])
    for route in routes:
        calc.refresh_route(route)
    pieces = sum(r["selected_piece_count"] for r in routes)
    if pieces < store.EDDM_MIN_PIECES_PER_JOB or pieces > store.EDDM_MAX_PIECES_PER_JOB_DAY:
        raise ApiError("ERR_EDDM_PIECE_BOUNDS")


def _settle(ctx):
    job = ctx.get("mail_job")
    counts = ctx.derived["counts"]
    postage = calc.postage_for(job, counts["automation_piece_count"],
                               counts["retail_piece_count"],
                               counts["eddm_piece_count"], counts["presort_tier"])
    handling, credit, total = calc.commit_settlement(postage, counts["billable_piece_count"])
    ctx.derived["settlement"] = (postage, handling, credit, total)
    campaign = db.campaigns[job["campaign_id"]]
    if derive.account_balance(campaign["account_id"]) < total:
        raise ApiError("ERR_INSUFFICIENT_PERMIT_BALANCE")


# --------------------------------------------------------------------- void
@bp.route("/mail/mail-jobs/<mail_job_id>/void", methods=["POST"])
def void_job(mail_job_id):
    ctx = Ctx(["PlatformAdmin", "CampaignManager"])
    ctx.path("mail_job", mail_job_id)
    ctx.fields(optional=[("reason", "str")])
    ctx.gate(lambda: ladder.campaign_of_job(ctx.get("mail_job")))
    ctx.at(17, lambda: _job_state(ctx.get("mail_job"), ("COMMITTED",)))
    ctx.run()
    job = ctx.get("mail_job")
    campaign = db.campaigns[job["campaign_id"]]
    amount = job["drawn_postage_cents"]
    if amount:
        services.append_ledger(campaign["account_id"], "REFUND", amount,
                               ctx.body.get("reason") or "void refund",
                               campaign_id=campaign["id"], mail_job_id=job["id"])
    job["drawn_postage_cents"] = 0
    for run in derive.job_runs(job["id"]):
        if run["status"] in ("RESERVED", "FAILED"):
            services.void_run(run)
    for record in db.list_records.values():
        if record.get("last_mail_job_id") == job["id"] and record["mail_status"] == "QUEUED":
            record["mail_status"] = "NOT_MAILED"
            record["last_mail_job_id"] = None
            touch(record)
    job["final_postage_cents"] = None
    job["handling_fee_cents"] = None
    job["volume_credit_cents"] = None
    job["total_due_cents"] = None
    job["mail_date"] = None
    job["scheduled_at"] = None
    job["pinned_template_version"] = None
    job["status"] = "DRAFT"
    touch(job)
    return envelope.object_response(serial.mail_job(job), 200)


# --------------------------------------------------------------- the drop
@bp.route("/mail/mail-jobs/<mail_job_id>/mail", methods=["POST"])
def mail_job_drop(mail_job_id):
    ctx = Ctx(["PlatformAdmin", "ProductionOperator"])
    ctx.path("mail_job", mail_job_id)
    ctx.gate(lambda: ladder.campaign_of_job(ctx.get("mail_job")))
    ctx.at(17, lambda: _drop_state(ctx.get("mail_job")))
    ctx.run()
    job = ctx.get("mail_job")
    job["status"] = "MAILED"
    if job["job_kind"] == "ADDRESSED":
        for record in db.list_records.values():
            if record.get("last_mail_job_id") == job["id"] and record["mail_status"] == "QUEUED":
                record["mail_status"] = "MAILED"
                touch(record)
    for step in db.drip_steps.values():
        if step["mail_job_id"] == job["id"] and step["status"] == "RELEASED":
            step["status"] = "MAILED"
            touch(step)
    touch(job)
    return envelope.object_response(serial.mail_job(job), 200)


def _drop_state(job):
    if job["job_kind"] == "EDDM":
        _job_state(job, ("COMMITTED",))
        return
    _job_state(job, ("IN_PRODUCTION",))
    # Adjudication of friction 7: the "every run finished" requirement is
    # folded into the JOB's own state gate and answers
    # ERR_MAIL_JOB_INVALID_STATE at rung 17.  Rung 19's declared applies_to
    # covers only the four production-run endpoints, so reporting it there
    # would widen a declared rung scope; this reading leaves rung 19's scope
    # exactly as specified.
    runs = derive.job_runs(job["id"])
    if not runs:
        raise ApiError("ERR_MAIL_JOB_INVALID_STATE")
    if any(r["status"] not in ("COMPLETED", "VOIDED") for r in runs):
        raise ApiError("ERR_MAIL_JOB_INVALID_STATE")
    if not any(r["status"] == "COMPLETED" for r in runs):
        raise ApiError("ERR_MAIL_JOB_INVALID_STATE")


# --------------------------------------------------------------- EDDM routes
@bp.route("/mail/mail-jobs/<mail_job_id>/eddm-routes", methods=["POST"])
def create_eddm_route(mail_job_id):
    ctx = Ctx(["PlatformAdmin", "CampaignManager"])
    ctx.path("mail_job", mail_job_id)
    ctx.fields(required=[("route_code", "str"), ("total_deliveries", "int"),
                         ("residential_piece_count", "int"),
                         ("business_piece_count", "int")])
    ctx.ranges([("total_deliveries", 1, None, False),
                ("residential_piece_count", 0, None, False),
                ("business_piece_count", 0, None, False)])
    ctx.gate(lambda: ladder.campaign_of_job(ctx.get("mail_job")))
    ctx.at(14, lambda: _require_eddm_job(ctx.get("mail_job")))
    ctx.at(17, lambda: _job_state(ctx.get("mail_job"), ("DRAFT",)))
    ctx.at(26, lambda: _unique_route(ctx))
    ctx.run()
    job = ctx.get("mail_job")
    row = new_row({
        "mail_job_id": job["id"],
        "route_code": ctx.body["route_code"],
        "total_deliveries": ctx.body["total_deliveries"],
        "residential_piece_count": ctx.body["residential_piece_count"],
        "business_piece_count": ctx.body["business_piece_count"],
        "selected_piece_count": 0,
        "saturation_pct": 0,
    })
    calc.refresh_route(row)
    db.eddm_routes[row["id"]] = row
    pieces = sum(r["selected_piece_count"] for r in derive.job_routes(job["id"]))
    job["eddm_piece_count"] = pieces
    job["billable_piece_count"] = pieces
    touch(job)
    return envelope.object_response(serial.eddm_route(row), 201)


def _require_eddm_job(job):
    if job["job_kind"] != "EDDM":
        raise ApiError("ERR_JOB_KIND_MISMATCH")


def _unique_route(ctx):
    job = ctx.get("mail_job")
    code = ctx.body.get("route_code")
    for route in derive.job_routes(job["id"]):
        if route["route_code"] == code:
            raise ApiError("ERR_DUPLICATE_KEY")


@bp.route("/mail/eddm-routes/<eddm_route_selection_id>", methods=["GET"])
def get_eddm_route(eddm_route_selection_id):
    ctx = Ctx(["PlatformAdmin", "CampaignManager", "ProductionOperator"])
    ctx.path("eddm_route", eddm_route_selection_id)
    ctx.run()
    return envelope.object_response(serial.eddm_route(ctx.get("eddm_route")), 200)


@bp.route("/mail/eddm-routes", methods=["GET"])
def list_eddm_routes():
    ctx = Ctx(["PlatformAdmin", "CampaignManager", "ProductionOperator"])
    ctx.run()
    rows = list(db.eddm_routes.values())
    wanted = request.args.get("mail_job_id")
    if wanted is not None:
        rows = [r for r in rows if r["mail_job_id"] == wanted]
    rows = envelope.sort_rows(rows)
    page, limit, offset, total = envelope.paginate(rows, request.args)
    return envelope.list_response([serial.eddm_route(r) for r in page], limit, offset, total)
