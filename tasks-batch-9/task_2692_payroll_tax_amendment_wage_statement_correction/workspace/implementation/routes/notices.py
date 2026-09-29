"""Agency notices, response rounds and penalty abatement (PRD 3.8)."""

from flask import Blueprint

import calc
from common import (
    F, R_ADMIN, R_OFFICER, READ6,
    authenticate, cents, db, fail, get_agency, get_case, get_employer, get_notice,
    get_body, matches, new_row, now, ok, pagination, paginate, qs, qs_int,
    quarter_field, require_state, sorted_rows, tax_year_field, touch, validate,
)
from serializers import notice_json

bp = Blueprint("notices", __name__)

RESPONSE_TERMINAL = ("CLOSED",)
GROUNDS = ("FIRST_TIME", "REASONABLE_CAUSE", "STATUTORY_EXCEPTION", "AGENCY_ERROR")
OUTCOMES = ("ABATED_FULL", "ABATED_PARTIAL", "UPHELD")

NOTICE_CREATE = {
    "employer_id": F("string", True),
    "agency_id": F("string", True),
    "tax_year": tax_year_field(True),
    "quarter": quarter_field(True),
    "notice_number": F("string", True, min_len=1, max_len=32),
    "assessed_tax_cents": cents(True),
    "assessed_penalty_cents": cents(True),
    "assessed_interest_cents": cents(True),
    "response_due_date": F("datetime", True),
    "correction_case_id": F("string", False),
}

DRAFT_RESPONSE_INPUT = {
    "response_narrative": F("string", True, min_len=1, max_len=4000),
    "abatement_grounds": F("string", False, enum=GROUNDS),
    "requested_penalty_waiver_cents": cents(False),
}


@bp.post("/agency-notices")
def create_notice():
    actor = authenticate((R_ADMIN, R_OFFICER))
    body = get_body()
    employer = None
    case = None
    if isinstance(body.get("employer_id"), str) and body["employer_id"]:
        employer = get_employer(body["employer_id"])
    if isinstance(body.get("agency_id"), str) and body["agency_id"]:
        get_agency(body["agency_id"])
    if isinstance(body.get("correction_case_id"), str) and body["correction_case_id"]:
        case = get_case(body["correction_case_id"])
    data = validate(body, NOTICE_CREATE)
    if employer is not None:
        actor.require_employer(employer["id"])

    if case is not None:
        if (case["employer_id"] != data["employer_id"]
                or case["agency_id"] != data["agency_id"]
                or case["tax_year"] != data["tax_year"]
                or case["quarter"] != data["quarter"]):
            fail("ERR_SCOPE_MISMATCH",
                 "the notice scope does not match the correction case's scope")

    for other in db.agency_notices.values():
        if (other["agency_id"] == data["agency_id"]
                and other["notice_number"] == data["notice_number"]):
            fail("ERR_DUPLICATE_NOTICE_NUMBER",
                 "notice_number is already recorded for this agency")

    row = new_row({
        "employer_id": data["employer_id"],
        "agency_id": data["agency_id"],
        "correction_case_id": data.get("correction_case_id"),
        "tax_year": data["tax_year"],
        "quarter": data["quarter"],
        "notice_number": data["notice_number"],
        "assessed_tax_cents": data["assessed_tax_cents"],
        "assessed_penalty_cents": data["assessed_penalty_cents"],
        "assessed_interest_cents": data["assessed_interest_cents"],
        "response_due_date": data["response_due_date"],
        "response_narrative": None,
        "abatement_grounds": None,
        "requested_penalty_waiver_cents": None,
        "response_status": "RECEIVED",
        "abatement_status": "NONE",
        "abatement_round": 0,
        "waiver_pct_bps": 0,
        "waived_penalty_cents": 0,
        "waived_interest_cents": 0,
        "net_exposure_cents": 0,
        "responded_at": None,
        "agency_decision_reference": None,
    })
    db.agency_notices[row["id"]] = row
    return ok(notice_json(row), 201)


@bp.get("/agency-notices/<agency_notice_id>")
def read_notice(agency_notice_id):
    actor = authenticate(READ6)
    row = get_notice(agency_notice_id)
    actor.require_employer(row["employer_id"])
    return ok(notice_json(row))


@bp.get("/agency-notices")
def list_notices():
    actor = authenticate(READ6)
    limit, offset = pagination()
    filters = {
        "employer_id": actor.scoped_employer(qs("employer_id")),
        "agency_id": qs("agency_id"),
        "correction_case_id": qs("correction_case_id"),
        "tax_year": qs_int("tax_year"),
        "quarter": qs_int("quarter"),
        "response_status": qs("response_status"),
        "abatement_status": qs("abatement_status"),
    }
    rows = [r for r in sorted_rows(db.agency_notices.values()) if matches(r, filters)]
    return paginate(rows, limit, offset, notice_json)


@bp.post("/agency-notices/<agency_notice_id>/draft-response")
def draft_response(agency_notice_id):
    authenticate((R_ADMIN, R_OFFICER))
    notice = get_notice(agency_notice_id)
    body = get_body()
    data = validate(body, DRAFT_RESPONSE_INPUT)

    require_state(notice["response_status"], ("RECEIVED", "INFO_REQUESTED"), RESPONSE_TERMINAL)
    if now() > notice["response_due_date"]:
        fail("ERR_NOTICE_RESPONSE_OVERDUE",
             "the response due date has already passed")
    if ("requested_penalty_waiver_cents" in data
            and data["requested_penalty_waiver_cents"] > notice["assessed_penalty_cents"]):
        fail("ERR_WAIVER_EXCEEDS_ASSESSMENT",
             "requested_penalty_waiver_cents may not exceed assessed_penalty_cents")

    notice["response_narrative"] = data["response_narrative"]
    if "abatement_grounds" in data:
        notice["abatement_grounds"] = data["abatement_grounds"]
    if "requested_penalty_waiver_cents" in data:
        notice["requested_penalty_waiver_cents"] = data["requested_penalty_waiver_cents"]
    notice["response_status"] = "RESPONSE_DRAFTED"
    notice["abatement_round"] += 1
    if data.get("abatement_grounds") is not None and notice["abatement_status"] == "NONE":
        notice["abatement_status"] = "REQUESTED"
    touch(notice)
    return ok(notice_json(notice))


@bp.post("/agency-notices/<agency_notice_id>/respond")
def respond_notice(agency_notice_id):
    authenticate((R_ADMIN, R_OFFICER))
    notice = get_notice(agency_notice_id)
    get_body()

    require_state(notice["response_status"], ("RESPONSE_DRAFTED",), RESPONSE_TERMINAL)
    if now() > notice["response_due_date"]:
        fail("ERR_NOTICE_RESPONSE_OVERDUE",
             "the response due date has already passed")

    notice["response_status"] = "RESPONDED"
    notice["responded_at"] = now()
    touch(notice)
    return ok(notice_json(notice))


@bp.post("/agency-notices/<agency_notice_id>/request-info")
def request_info(agency_notice_id):
    authenticate((R_ADMIN, R_OFFICER))
    notice = get_notice(agency_notice_id)
    body = get_body()
    validate(body, {"info_request_note": F("string", False, max_len=2000)})

    require_state(notice["response_status"], ("RESPONDED",), RESPONSE_TERMINAL)
    if notice["abatement_status"] != "REQUESTED":
        fail("ERR_INVALID_STATE",
             "further information may only be requested while an abatement is pending")

    notice["response_status"] = "INFO_REQUESTED"
    notice["responded_at"] = None
    touch(notice)
    return ok(notice_json(notice))


@bp.post("/agency-notices/<agency_notice_id>/record-outcome")
def record_outcome(agency_notice_id):
    authenticate((R_ADMIN, R_OFFICER))
    notice = get_notice(agency_notice_id)
    body = get_body()
    data = validate(body, {
        "outcome": F("string", True, enum=OUTCOMES),
        "agency_decision_reference": F("string", False, min_len=1, max_len=120),
    })
    employer = db.employers.get(notice["employer_id"])

    require_state(notice["response_status"], ("RESPONDED",), RESPONSE_TERMINAL)
    if notice["abatement_status"] not in ("NONE", "REQUESTED"):
        fail("ERR_ALREADY_TERMINAL", "the abatement dimension has already been decided")
    requested = notice["requested_penalty_waiver_cents"]
    if requested is not None and requested > notice["assessed_penalty_cents"]:
        fail("ERR_WAIVER_EXCEEDS_ASSESSMENT",
             "requested_penalty_waiver_cents exceeds assessed_penalty_cents")

    # granted_abatement_count is read before this notice's own dimension moves.
    bps, waived_penalty, waived_interest, net = calc.compute_abatement(
        notice, employer, data["outcome"])

    notice["waiver_pct_bps"] = bps
    notice["waived_penalty_cents"] = waived_penalty
    notice["waived_interest_cents"] = waived_interest
    notice["net_exposure_cents"] = net
    if "agency_decision_reference" in data:
        notice["agency_decision_reference"] = data["agency_decision_reference"]
    if notice["abatement_status"] == "REQUESTED":
        notice["abatement_status"] = {
            "ABATED_FULL": "GRANTED",
            "ABATED_PARTIAL": "PARTIALLY_GRANTED",
            "UPHELD": "DENIED",
        }[data["outcome"]]
    notice["response_status"] = "CLOSED"
    touch(notice)

    case = db.correction_cases.get(notice["correction_case_id"]) if notice["correction_case_id"] else None
    if case is not None:
        calc.sync_case(case)
    calc.sync_employer(employer)
    return ok(notice_json(notice))
