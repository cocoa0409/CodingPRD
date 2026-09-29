"""Responsiveness, exemption assertion, adjudication, notification (PRD 3.4-3.7)."""
from flask import Blueprint

import calc
import services
import validate
from core import must_get, read_endpoint, write_endpoint
from db import fmt_dt, store
from errors import fail
from middleware import (
    ROLE_LEGAL_COUNSEL,
    ROLE_QUALITY_REVIEWER,
    ROLE_RECORDS_CLERK,
    ROLE_RECORDS_SUPERVISOR,
    ROLE_REDACTION_TECHNICIAN,
)
from reconcile import reconcile_all
from response import paginate

bp = Blueprint("review", __name__)


@bp.route("/records/responsive-records/<record_id>/inclusion", methods=["POST"])
@write_endpoint([ROLE_RECORDS_CLERK, ROLE_LEGAL_COUNSEL, ROLE_RECORDS_SUPERVISOR],
                code=200)
def rule_inclusion(ctx, record_id):
    data = validate.body()
    inclusion_status = validate.req_enum(data, "inclusion_status",
                                         ("RESPONSIVE", "EXCLUDED"))
    record = must_get("responsive_records", record_id,
                      "ERR_RESPONSIVE_RECORD_NOT_FOUND")
    request = services.request_of_record(record)
    if record["inclusion_status"] != "CANDIDATE":
        fail("ERR_RECORD_STATE_INVALID",
             "the record has already been ruled (%s)" % record["inclusion_status"])
    if request["processing_status"] not in ("SCOPING", "EXEMPTION_REVIEW"):
        fail("ERR_REQUEST_STATE_INVALID",
             "responsiveness cannot be judged while the request is %s"
             % request["processing_status"])
    record["inclusion_status"] = inclusion_status
    if inclusion_status == "RESPONSIVE":
        reconcile_all()
        services.restrike_deadline(request)
        if request["processing_status"] == "SCOPING":
            request["processing_status"] = "EXEMPTION_REVIEW"
    return record


@bp.route("/records/responsive-records/<record_id>/exemption-claims",
          methods=["POST"])
@write_endpoint([ROLE_LEGAL_COUNSEL], code=201)
def assert_exemption(ctx, record_id):
    data = validate.body()
    exemption_code = validate.req_enum(data, "exemption_code", calc.EXEMPTION_CODES)
    statutory_citation = validate.req_str(data, "statutory_citation")
    asserted_scope = validate.req_enum(data, "asserted_scope", calc.ASSERTED_SCOPES)
    record = must_get("responsive_records", record_id,
                      "ERR_RESPONSIVE_RECORD_NOT_FOUND")
    if record["inclusion_status"] in ("EXCLUDED", "RELEASED"):
        fail("ERR_RECORD_STATE_INVALID",
             "no exemption may be asserted against a %s record"
             % record["inclusion_status"])
    if statutory_citation != calc.CITATION_MAP[exemption_code]:
        fail("ERR_CITATION_MISMATCH",
             "%s requires the citation %s"
             % (exemption_code, calc.CITATION_MAP[exemption_code]))
    asset = calc.asset_of_record(record)
    claim = store.insert("exemption_claims", {
        "responsive_record_id": record["id"],
        "exemption_code": exemption_code,
        "statutory_citation": statutory_citation,
        "asserted_scope": asserted_scope,
        "claim_source": "STAFF_ANALYSIS",
        "depicted_individual_id": None,
        "asserted_by_staff_id": ctx.user_id,
        "adjudicated_by_staff_id": None,
        "status": "ASSERTED",
        "adjudicated_at": None,
        "adjudication_note": None,
        "estimated_redaction_minutes": calc.claim_redaction_minutes(
            asset, exemption_code, asserted_scope),
    })
    services.stale_active_estimates(record["request_id"])
    return claim


@bp.route("/records/exemption-claims/<claim_id>/adjudication", methods=["POST"])
@write_endpoint([ROLE_LEGAL_COUNSEL], code=200)
def adjudicate(ctx, claim_id):
    data = validate.body()
    disposition = validate.req_enum(data, "disposition", calc.DISPOSITIONS)
    note = validate.opt_str(data, "adjudication_note")
    claim = must_get("exemption_claims", claim_id, "ERR_EXEMPTION_CLAIM_NOT_FOUND")
    if claim["status"] != "ASSERTED":
        fail("ERR_CLAIM_ALREADY_ADJUDICATED",
             "the claim is already %s" % claim["status"])
    if claim["asserted_by_staff_id"] is not None and \
            claim["asserted_by_staff_id"] == ctx.user_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "an attorney may not adjudicate a claim they asserted")
    record = store.get("responsive_records", claim["responsive_record_id"])
    request = services.request_of_record(record) if record else None
    claim["status"] = disposition
    claim["adjudicated_by_staff_id"] = ctx.user_id
    claim["adjudicated_at"] = store.now_str()
    claim["adjudication_note"] = note
    apply_disposition_cascade(claim, record)
    if request is not None:
        services.stale_active_estimates(request["id"])
        reconcile_all()
        services.advance_after_adjudication(request)
    return claim


def apply_disposition_cascade(claim, record):
    """The four-link chain of PRD 3.5, plus the objection exits of PRD 3.7."""
    if record is not None:
        if claim["status"] == "SUSTAINED":
            if claim["asserted_scope"] == "FULL_WITHHOLD" and \
                    record["inclusion_status"] == "RESPONSIVE":
                # link two, then link three: the pointless work is cancelled.
                record["inclusion_status"] = "WITHHELD_IN_FULL"
                services.cancel_tasks(calc.tasks_of_record(record["id"]))
        elif claim["status"] == "OVERRULED":
            services.cancel_tasks(
                [task for task in calc.tasks_of_record(record["id"])
                 if task["exemption_claim_id"] == claim["id"]])
        elif claim["status"] == "WITHDRAWN":
            services.withdraw_releases_record(record)
    individual_id = claim["depicted_individual_id"]
    if claim["claim_source"] == "DEPICTED_OBJECTION" and individual_id:
        individual = store.get("depicted_individuals", individual_id)
        if individual is not None and individual["notification_status"] == "OBJECTED":
            individual["notification_status"] = (
                "OBJECTION_SUSTAINED" if claim["status"] == "SUSTAINED"
                else "OBJECTION_OVERRULED")


@bp.route("/records/depicted-individuals/<individual_id>/notification",
          methods=["POST"])
@write_endpoint([ROLE_RECORDS_CLERK], code=200)
def issue_notification(ctx, individual_id):
    data = validate.body()
    notice_method = validate.req_enum(data, "notice_method", calc.NOTICE_METHODS)
    individual = must_get("depicted_individuals", individual_id,
                          "ERR_DEPICTED_INDIVIDUAL_NOT_FOUND")
    if not individual["notification_required"] or \
            individual["notification_status"] != "PENDING":
        fail("ERR_NOTIFICATION_STATE_INVALID",
             "notice may only be issued to a PENDING individual who requires it")
    notified_at = store.now()
    individual["notification_status"] = "NOTIFIED"
    individual["notice_method"] = notice_method
    individual["notified_at"] = fmt_dt(notified_at)
    individual["objection_deadline_at"] = fmt_dt(
        calc.objection_deadline(individual, notified_at))
    return individual


@bp.route("/records/depicted-individuals/<individual_id>/objection",
          methods=["POST"])
@write_endpoint([ROLE_RECORDS_CLERK, ROLE_LEGAL_COUNSEL], code=201)
def record_objection(ctx, individual_id):
    data = validate.body()
    objection_basis = validate.req_enum(data, "objection_basis", calc.OBJECTION_BASES)
    record_id = validate.req_str(data, "responsive_record_id")
    individual = must_get("depicted_individuals", individual_id,
                          "ERR_DEPICTED_INDIVIDUAL_NOT_FOUND")
    record = must_get("responsive_records", record_id,
                      "ERR_RESPONSIVE_RECORD_NOT_FOUND")
    if individual["notification_status"] != "NOTIFIED":
        fail("ERR_NOTIFICATION_STATE_INVALID",
             "only a NOTIFIED individual may object (currently %s)"
             % individual["notification_status"])
    if record["video_asset_id"] != individual["video_asset_id"]:
        fail("ERR_CLAIM_RECORD_MISMATCH",
             "the record covers a different recording than the objector appears in")
    from db import parse_dt
    deadline = parse_dt(individual["objection_deadline_at"])
    if deadline is None or store.now() > deadline:
        fail("ERR_WINDOW_CLOSED", "the objection window has closed")
    individual["notification_status"] = "OBJECTED"
    individual["objection_basis"] = objection_basis
    exemption_code = calc.OBJECTION_BASIS_TO_CODE[objection_basis]
    asset = calc.asset_of_record(record)
    claim = store.insert("exemption_claims", {
        "responsive_record_id": record["id"],
        "exemption_code": exemption_code,
        "statutory_citation": calc.CITATION_MAP[exemption_code],
        "asserted_scope": "PARTIAL_REDACT",
        "claim_source": "DEPICTED_OBJECTION",
        "depicted_individual_id": individual["id"],
        "asserted_by_staff_id": None,
        "adjudicated_by_staff_id": None,
        "status": "ASSERTED",
        "adjudicated_at": None,
        "adjudication_note": None,
        "estimated_redaction_minutes": calc.claim_redaction_minutes(
            asset, exemption_code, "PARTIAL_REDACT"),
    })
    services.stale_active_estimates(record["request_id"])
    return claim


# -- reads -----------------------------------------------------------------
@bp.route("/records/exemption-claims/<claim_id>", methods=["GET"])
@read_endpoint([ROLE_RECORDS_CLERK, ROLE_RECORDS_SUPERVISOR, ROLE_LEGAL_COUNSEL])
def get_claim(ctx, claim_id):
    return must_get("exemption_claims", claim_id, "ERR_EXEMPTION_CLAIM_NOT_FOUND")


@bp.route("/records/exemption-claims", methods=["GET"])
@read_endpoint([ROLE_RECORDS_CLERK, ROLE_RECORDS_SUPERVISOR, ROLE_LEGAL_COUNSEL])
def list_claims(ctx):
    limit, offset = validate.pagination()
    filters = {
        "responsive_record_id": validate.query_str("responsive_record_id"),
        "depicted_individual_id": validate.query_str("depicted_individual_id"),
        "asserted_by_staff_id": validate.query_str("asserted_by_staff_id"),
        "adjudicated_by_staff_id": validate.query_str("adjudicated_by_staff_id"),
        "status": validate.query_enum("status", calc.CLAIM_STATUSES),
        "claim_source": validate.query_enum("claim_source", calc.CLAIM_SOURCES),
    }
    rows = store.all("exemption_claims")
    for field, value in filters.items():
        if value is not None:
            rows = [row for row in rows if row[field] == value]
    return paginate(rows, limit, offset)
