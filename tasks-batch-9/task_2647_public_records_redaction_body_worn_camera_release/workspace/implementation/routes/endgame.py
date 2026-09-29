"""Release production, denial, appeal and closure (PRD 3.9)."""
from flask import Blueprint

import calc
import services
import validate
from core import must_get, read_endpoint, write_endpoint
from db import add_days, fmt_dt, parse_dt, store
from errors import fail
from middleware import (
    ROLE_LEGAL_COUNSEL,
    ROLE_RECORDS_CLERK,
    ROLE_RECORDS_SUPERVISOR,
    ROLE_REQUESTER,
)
from reconcile import reconcile_all
from response import paginate

bp = Blueprint("endgame", __name__)

DENIAL_PROCESSING_STATES = ("EXEMPTION_REVIEW", "REDACTION", "RELEASE_READY")


def _sweep_notifications(request_id, clock):
    """PRD 3.9: NOTIFIED individuals whose window has run move to WAIVED."""
    swept = 0
    seen = set()
    for record in calc.records_of_request(request_id):
        if record["inclusion_status"] != "RESPONSIVE":
            continue
        for individual in calc.individuals_of_asset(record["video_asset_id"]):
            if individual["id"] in seen:
                continue
            seen.add(individual["id"])
            if not individual["notification_required"]:
                continue
            if individual["notification_status"] != "NOTIFIED":
                continue
            deadline = parse_dt(individual["objection_deadline_at"])
            if deadline is not None and clock >= deadline:
                individual["notification_status"] = "WAIVED"
                swept += 1
    return swept


@bp.route("/records/requests/<request_id>/release-packages", methods=["POST"])
@write_endpoint([ROLE_RECORDS_CLERK, ROLE_RECORDS_SUPERVISOR], code=201)
def create_release_package(ctx, request_id):
    data = validate.body()
    media_type = validate.req_enum(data, "media_type", calc.MEDIA_TYPES)
    request = must_get("requests", request_id, "ERR_REQUEST_NOT_FOUND")
    if request["processing_status"] not in ("RELEASE_READY", "PARTIALLY_RELEASED"):
        fail("ERR_REQUEST_NOT_RELEASE_READY",
             "a package requires the request to be release ready or partially "
             "released (currently %s)" % request["processing_status"])
    clock = store.now()
    responsive = [row for row in calc.records_of_request(request["id"])
                  if row["inclusion_status"] == "RESPONSIVE"]
    for record in responsive:
        if record["release_posture"] == "BLOCKED":
            fail("ERR_RECORD_RELEASE_BLOCKED",
                 "a record on the request is withheld in full")
    for record in responsive:
        for claim in calc.claims_of_record(record["id"]):
            if claim["status"] == "ASSERTED":
                fail("ERR_UNADJUDICATED_CLAIM",
                     "an exemption claim on the request is still asserted")
    for record in responsive:
        for individual in calc.individuals_of_asset(record["video_asset_id"]):
            if calc.notification_blocks(individual, clock):
                fail("ERR_OBJECTION_UNRESOLVED",
                     "a depicted individual's objection window is unresolved")
    for record in responsive:
        asset = calc.asset_of_record(record)
        if asset is not None and calc.active_holds_for_incident(
                asset["incident_number"]):
            fail("ERR_RETENTION_HOLD_ACTIVE",
                 "an active litigation hold covers a recording on the request")
    eligible = calc.release_eligible_set(request["id"], clock)
    if not eligible:
        fail("ERR_NO_RELEASABLE_RECORDS",
             "no record on the request is currently releasable")
    final = len(eligible) == len(responsive)
    if final:
        for row in calc.records_of_request(request["id"]):
            if row["inclusion_status"] == "CANDIDATE":
                fail("ERR_REQUEST_STATE_INVALID",
                     "every candidate record must be ruled before a final package")
    if services.deposit_outstanding(request):
        fail("ERR_DEPOSIT_UNPAID", "the required deposit on the request is unpaid")
    waived = _sweep_notifications(request["id"], clock)
    stamp = fmt_dt(clock)
    for record in eligible:
        record["inclusion_status"] = "RELEASED"
        record["released_at"] = stamp
    produced_minutes, disc_count, cost = calc.media_production_cost(
        eligible, media_type)
    package = store.insert("release_packages", {
        "request_id": request["id"],
        "package_kind": "FINAL" if final else "INTERIM",
        "media_type": media_type,
        "included_record_count": len(eligible),
        "produced_minutes": produced_minutes,
        "disc_count": disc_count,
        "production_cost_cents": cost,
        "released_at": stamp,
        "waived_notification_count": waived,
    })
    request["processing_status"] = "RELEASED" if final else "PARTIALLY_RELEASED"
    return package


@bp.route("/records/requests/<request_id>/denial-letters", methods=["POST"])
@write_endpoint([ROLE_LEGAL_COUNSEL], code=201)
def issue_denial_letter(ctx, request_id):
    data = validate.body()
    denial_type = validate.req_enum(data, "denial_type", calc.DENIAL_TYPES)
    appeal_pathway_note = validate.req_str(data, "appeal_pathway_note")
    request = must_get("requests", request_id, "ERR_REQUEST_NOT_FOUND")
    if request["processing_status"] not in DENIAL_PROCESSING_STATES:
        fail("ERR_REQUEST_STATE_INVALID",
             "a denial cannot be issued from %s" % request["processing_status"])
    records = calc.records_of_request(request["id"])
    if request["unadjudicated_claim_count"] != 0:
        fail("ERR_UNADJUDICATED_CLAIM",
             "every exemption claim must be adjudicated before a denial")
    if denial_type == "FULL":
        for record in records:
            if record["inclusion_status"] == "EXCLUDED":
                continue
            if record["inclusion_status"] != "WITHHELD_IN_FULL":
                fail("ERR_REQUEST_STATE_INVALID",
                     "a full denial requires every retained record to be "
                     "withheld in full")
    citations = sorted({claim["statutory_citation"]
                        for claim in calc.claims_of_request(request["id"])
                        if claim["status"] == "SUSTAINED"})
    issued_at = store.now()
    letter = store.insert("denial_letters", {
        "request_id": request["id"],
        "denial_type": denial_type,
        "statutory_citations": citations,
        "withheld_record_count": sum(
            1 for row in records if row["inclusion_status"] == "WITHHELD_IN_FULL"),
        "appeal_authority": ("SUPERIOR_COURT" if denial_type == "FULL"
                             else "DISTRICT_ATTORNEY"),
        "appeal_pathway_note": appeal_pathway_note,
        "issued_at": fmt_dt(issued_at),
        "appeal_deadline_at": fmt_dt(add_days(issued_at, calc.APPEAL_WINDOW_DAYS)),
        "status": "ISSUED",
        "appeal_grounds": None,
        "appeal_filed_at": None,
        "appeal_decided_at": None,
        "_issued_by_staff_id": ctx.user_id,
    })
    if denial_type == "FULL":
        request["processing_status"] = "DENIED"
    return letter


@bp.route("/records/denial-letters/<letter_id>/appeal", methods=["POST"])
@write_endpoint([ROLE_REQUESTER], code=200)
def file_appeal(ctx, letter_id):
    data = validate.body()
    appeal_grounds = validate.req_str(data, "appeal_grounds")
    letter = must_get("denial_letters", letter_id, "ERR_DENIAL_LETTER_NOT_FOUND")
    request = store.get("requests", letter["request_id"])
    if request is not None and request["requester_id"] != ctx.user_id:
        fail("ERR_REQUESTER_MISMATCH", "the denial belongs to another filer")
    if letter["status"] != "ISSUED":
        fail("ERR_LETTER_STATE_INVALID",
             "only an ISSUED letter may be appealed (currently %s)"
             % letter["status"])
    deadline = parse_dt(letter["appeal_deadline_at"])
    if deadline is None or store.now() > deadline:
        fail("ERR_WINDOW_CLOSED", "the appeal window has closed")
    letter["status"] = "APPEALED"
    letter["appeal_grounds"] = appeal_grounds
    letter["appeal_filed_at"] = store.now_str()
    return letter


@bp.route("/records/denial-letters/<letter_id>/appeal-decision", methods=["POST"])
@write_endpoint([ROLE_LEGAL_COUNSEL], code=200)
def decide_appeal(ctx, letter_id):
    data = validate.body()
    decision = validate.req_enum(data, "decision", calc.DECISIONS)
    letter = must_get("denial_letters", letter_id, "ERR_DENIAL_LETTER_NOT_FOUND")
    if letter["status"] != "APPEALED":
        fail("ERR_LETTER_STATE_INVALID",
             "only an APPEALED letter carries a decision (currently %s)"
             % letter["status"])
    if letter.get("_issued_by_staff_id") == ctx.user_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "the attorney who issued the denial may not decide its appeal")
    request = store.get("requests", letter["request_id"])
    letter["status"] = decision
    letter["appeal_decided_at"] = store.now_str()
    if decision == "UPHELD":
        if request is not None and letter["denial_type"] == "FULL" and \
                request["processing_status"] == "DENIED":
            request["processing_status"] = "CLOSED"
        return letter
    # REVERSED reopens three levels at once.
    if request is not None:
        for claim in calc.claims_of_request(request["id"]):
            if claim["status"] != "SUSTAINED":
                continue
            claim["status"] = "WITHDRAWN"
            record = store.get("responsive_records", claim["responsive_record_id"])
            if record is not None:
                services.withdraw_releases_record(record)
        if letter["denial_type"] == "FULL" and \
                request["processing_status"] == "DENIED":
            request["processing_status"] = "EXEMPTION_REVIEW"
        reconcile_all()
    return letter


# -- reads -----------------------------------------------------------------
@bp.route("/records/denial-letters/<letter_id>", methods=["GET"])
@read_endpoint([ROLE_RECORDS_CLERK, ROLE_RECORDS_SUPERVISOR, ROLE_LEGAL_COUNSEL,
                ROLE_REQUESTER])
def get_denial_letter(ctx, letter_id):
    return must_get("denial_letters", letter_id, "ERR_DENIAL_LETTER_NOT_FOUND")


@bp.route("/records/requests/<request_id>/denial-letters", methods=["GET"])
@read_endpoint([ROLE_RECORDS_CLERK, ROLE_RECORDS_SUPERVISOR, ROLE_LEGAL_COUNSEL,
                ROLE_REQUESTER])
def list_denial_letters(ctx, request_id):
    limit, offset = validate.pagination()
    status = validate.query_enum("status", calc.LETTER_STATUSES)
    must_get("requests", request_id, "ERR_REQUEST_NOT_FOUND")
    rows = calc.letters_of_request(request_id)
    if status is not None:
        rows = [row for row in rows if row["status"] == status]
    return paginate(rows, limit, offset)


@bp.route("/records/requests/<request_id>/release-packages", methods=["GET"])
@read_endpoint([ROLE_RECORDS_CLERK, ROLE_RECORDS_SUPERVISOR, ROLE_REQUESTER])
def list_release_packages(ctx, request_id):
    limit, offset = validate.pagination()
    must_get("requests", request_id, "ERR_REQUEST_NOT_FOUND")
    return paginate(calc.packages_of_request(request_id), limit, offset)
