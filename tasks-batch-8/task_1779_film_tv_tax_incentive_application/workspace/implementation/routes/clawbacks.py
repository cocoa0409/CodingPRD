"""ClawbackCase endpoints: open, send-notice, appeal, resolve."""
from datetime import timedelta
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_APPEAL_WINDOW_CLOSED,
    ERR_CLAWBACK_EXCEEDS_EXPOSURE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_NOTICE_WINDOW_ACTIVE,
)
from helpers import (
    certificate_for_application,
    check_producer_owns,
    company_id_of_case,
    get_one,
    list_query,
    public,
)
from middleware import authorized
from response import success_object
from services.core import new_record, sustain_clawback, touch
from util import CLOCK, fmt_dt, parse_dt
from validate import (
    get_body,
    opt_enum,
    opt_int,
    opt_str,
    reject_unknown_fields,
    req_enum,
    req_str,
    require_body_ref,
    require_path_resource,
)

bp = Blueprint("clawback_cases", __name__)

TRIGGER_REASONS = {"SPEND_SHORTFALL", "RESIDENCY_FAILURE", "MISSING_AUDIT", "MISREPRESENTATION"}
PENALTY_MODES = {"SIMPLE", "AGGRAVATED"}
RESOLVE_OUTCOMES = {"SUSTAINED", "VACATE", "SETTLE"}


@bp.post("/clawback-cases")
def create_case():
    authorized(["FilmOfficeAdmin"])
    body = get_body()
    reject_unknown_fields(body, {"application_id", "trigger_reason", "penalty_mode", "shortfall_amount_cents"})
    application_id = req_str(body, "application_id")
    trigger_reason = req_enum(body, "trigger_reason", TRIGGER_REASONS)
    penalty_mode = opt_enum(body, "penalty_mode", PENALTY_MODES, default="SIMPLE")
    shortfall = opt_int(body, "shortfall_amount_cents", None)

    app = require_body_ref("applications", application_id, "application_id")
    # State (5): the target application must be CREDIT_ISSUED.
    if app["status"] != "CREDIT_ISSUED":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"cannot open a clawback case while the application is {app['status']}")
    cert = certificate_for_application(app["id"])
    # Fiscal (12): the base defaults to the certificate's current exposure and
    # must be positive and within the issued amount.
    if shortfall is None:
        shortfall = int(cert["overissued_exposure_cents"])
    if shortfall <= 0 or shortfall > int(cert["issued_amount_cents"]):
        raise_error(ERR_CLAWBACK_EXCEEDS_EXPOSURE,
                    "shortfall_amount_cents must be > 0 and <= the certificate's issued amount")
    rec = new_record("clawback_cases", {
        "application_id": application_id,
        "certificate_id": cert["id"],
        "trigger_reason": trigger_reason,
        "penalty_mode": penalty_mode,
        "shortfall_amount_cents": shortfall,
        "status": "OPENED",
        "notice_sent_at": None,
        "appeal_deadline_at": None,
        "appealed_at": None,
        "resolved_at": None,
        "interest_cents": None,
        "assessed_total_cents": None,
        "recovered_from_certificate_cents": 0,
        "cash_assessment_cents": None,
        "settled_amount_cents": None,
    })
    return success_object(public(rec), status=201)


@bp.get("/clawback-cases")
def list_cases():
    return list_query("clawback_cases", {
        "application_id": request.args.get("application_id"),
        "certificate_id": request.args.get("certificate_id"),
        "status": request.args.get("status"),
    })


@bp.get("/clawback-cases/<caseId>")
def get_case(caseId):
    return get_one("clawback_cases", caseId)


def _program_of_case(case):
    app = db["applications"].get(case["application_id"])
    return db["jurisdiction_programs"].get(app["jurisdiction_program_id"])


@bp.post("/clawback-cases/<caseId>/send-notice")
def send_notice(caseId):
    authorized(["FilmOfficeAdmin"])
    case = require_path_resource("clawback_cases", caseId)
    body = get_body()
    reject_unknown_fields(body, set())
    if case["status"] != "OPENED":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"send-notice is not declared from status {case['status']}")
    program = _program_of_case(case)
    now = CLOCK.now()
    case["notice_sent_at"] = CLOCK.now_iso()
    case["appeal_deadline_at"] = fmt_dt(now + timedelta(days=int(program["appeal_window_days"])))
    case["status"] = "NOTICE_SENT"
    touch(case)
    return success_object(public(case))


@bp.post("/clawback-cases/<caseId>/appeal")
def appeal_case(caseId):
    caller = authorized(["Producer"])
    case = require_path_resource("clawback_cases", caseId)
    body = get_body()
    reject_unknown_fields(body, {"appeal_grounds"})
    # Ownership (4): caller owns the application's production company.
    check_producer_owns(caller, company_id_of_case(case))
    # State (5).
    if case["status"] != "NOTICE_SENT":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"appeal is not declared from status {case['status']}")
    # Temporal (9): appeal allowed at or before the deadline (inclusive).
    if CLOCK.now() > parse_dt(case["appeal_deadline_at"]):
        raise_error(ERR_APPEAL_WINDOW_CLOSED, "the appeal window has closed")
    case["appealed_at"] = CLOCK.now_iso()
    case["status"] = "APPEALED"
    touch(case)
    return success_object(public(case))


@bp.post("/clawback-cases/<caseId>/resolve")
def resolve_case(caseId):
    authorized(["FilmOfficeAdmin"])
    case = require_path_resource("clawback_cases", caseId)
    body = get_body()
    reject_unknown_fields(body, {"outcome", "settled_amount_cents"})
    outcome = req_enum(body, "outcome", RESOLVE_OUTCOMES)
    settled_amount = None
    if outcome == "SETTLE":
        v = body.get("settled_amount_cents")
        if v is None or not isinstance(v, int) or isinstance(v, bool) or v <= 0:
            raise_error(ERR_INVALID_REQUEST,
                        "settled_amount_cents is required and must be > 0 when outcome is SETTLE")
        settled_amount = v
    elif "settled_amount_cents" in body and body["settled_amount_cents"] is not None:
        # tolerated on non-SETTLE outcomes only if it is a valid integer
        opt_int(body, "settled_amount_cents", None)

    # State (5): resolve is declared from NOTICE_SENT or APPEALED.
    if case["status"] not in ("NOTICE_SENT", "APPEALED"):
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"resolve is not declared from status {case['status']}")

    if outcome == "SUSTAINED":
        # Temporal (9): sustaining from NOTICE_SENT requires the appeal window
        # to have lapsed (clock strictly after the deadline); sustaining from
        # APPEALED carries no waiting period.
        if case["status"] == "NOTICE_SENT" and CLOCK.now() <= parse_dt(case["appeal_deadline_at"]):
            raise_error(ERR_NOTICE_WINDOW_ACTIVE, "the appeal quiet period is still running")
        app = db["applications"].get(case["application_id"])
        cert = db["certificates"].get(case["certificate_id"])
        program = _program_of_case(case)
        sustain_clawback(case, cert, app, program)
        return success_object(public(case))

    if outcome == "VACATE":
        case["status"] = "VACATED"
        case["resolved_at"] = CLOCK.now_iso()
        touch(case)
        return success_object(public(case))

    # SETTLE: cash settlement; the certificate and program are untouched.
    case["status"] = "SETTLED"
    case["settled_amount_cents"] = settled_amount
    case["cash_assessment_cents"] = settled_amount
    case["resolved_at"] = CLOCK.now_iso()
    touch(case)
    return success_object(public(case))
