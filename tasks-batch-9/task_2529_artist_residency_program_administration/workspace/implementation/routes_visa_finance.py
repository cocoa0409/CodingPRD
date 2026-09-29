"""Visa sponsorship, stipend disbursement settlement and engagement obligations."""

import calc
import domain as D
import store as K
from auth import authorize
from envelope import object_response, paged, query_int, query_str
from errors import ApiError
from flask import Blueprint
from store import store, touch
from validate import (bad, body, d, ds, fk, opt_date, opt_int, opt_str,
                      path_row, req_enum, req_str, req_str_list)

bp = Blueprint("visa_finance", __name__)

VISA_ROLES = ["VisaCoordinator", "ProgramAdmin"]
DOC_ACTIONS = ["REQUEST", "SUBMIT"]
DOC_EDGE = {
    ("REQUEST", "INITIATED"): "DOCS_REQUESTED",
    ("REQUEST", "DOCS_SUBMITTED"): "DOCS_REQUESTED",
    ("SUBMIT", "DOCS_REQUESTED"): "DOCS_SUBMITTED",
}
ADJUDICATION_ACTIONS = ["FILE", "APPROVE", "DENY"]
ADJUDICATION_EDGE = {
    ("FILE", "DOCS_SUBMITTED"): "FILED",
    ("APPROVE", "FILED"): "APPROVED",
    ("DENY", "FILED"): "DENIED",
}


# ---------------------------------------------------------------- visa cases
@bp.route("/visa-cases", methods=["POST"])
def create_visa_case():
    authorize(VISA_ROLES)
    b = body()
    res = fk(b, "residency_id", store.residencies, "ERR_RESIDENCY_NOT_FOUND")
    req_str(b, "residency_id")

    if not D.residency_visa_required(res):
        raise ApiError("ERR_VISA_NOT_REQUIRED",
                       "this residency sponsors a domestic artist")
    if D.visa_case_of(res["id"]) is not None:
        raise ApiError("ERR_VISA_NOT_REQUIRED",
                       "this residency already carries a visa case")

    case = D.new_visa_case(res["id"])
    case["case_type"] = calc.visa_case_type(res.get("session_length_weeks"))
    return object_response(D.ser_visa_case(case), 201)


@bp.route("/visa-cases", methods=["GET"])
def list_visa_cases():
    authorize(VISA_ROLES)
    filters = {
        "residency_id": query_str("residency_id"),
        "status": query_str("status"),
        "case_type": query_str("case_type"),
    }
    rows = D.by_seq(list(store.visa_cases.values()))
    for key, value in filters.items():
        if value is not None:
            rows = [r for r in rows if r[key] == value]
    return paged(rows, D.ser_visa_case)


@bp.route("/visa-cases/<case_id>", methods=["GET"])
def get_visa_case(case_id):
    authorize(VISA_ROLES)
    row = path_row(store.visa_cases, case_id, "ERR_VISA_CASE_NOT_FOUND")
    return object_response(D.ser_visa_case(row))


@bp.route("/visa-cases/<case_id>/docs", methods=["POST"])
def visa_docs(case_id):
    authorize(["VisaCoordinator"])
    case = path_row(store.visa_cases, case_id, "ERR_VISA_CASE_NOT_FOUND")
    b = body()
    action = req_enum(b, "action", DOC_ACTIONS)
    doc_list = req_str_list(b, "doc_list", allow_empty=True, max_len=200)
    if action == "REQUEST" and len(doc_list) == 0:
        bad("doc_list must not be empty on a REQUEST")

    res = store.residencies.get(case["residency_id"])
    if res is None or res["status"] != "SCHEDULED":
        raise ApiError("ERR_RESIDENCY_NOT_SCHEDULED",
                       "visa document work requires a SCHEDULED residency")
    target = DOC_EDGE.get((action, case["status"]))
    if target is None:
        raise ApiError("ERR_VISA_STATE_INVALID",
                       "%s is not an edge from %s" % (action, case["status"]))

    if action == "SUBMIT":
        supplied = set(doc_list)
        for doc in case["requested_doc_list"]:
            if doc not in supplied:
                raise ApiError("ERR_VISA_DOCS_INCOMPLETE",
                               "the submission omits the requested document %s" % doc)
        case["submitted_doc_list"] = list(doc_list)
    else:
        # a re-request after a submission opens another RFE round; the loop is unbounded
        if case["status"] == "DOCS_SUBMITTED":
            case["rfe_round"] = int(case["rfe_round"]) + 1
        case["requested_doc_list"] = list(doc_list)
    case["status"] = target
    touch(case)
    return object_response(D.ser_visa_case(case))


@bp.route("/visa-cases/<case_id>/adjudication", methods=["POST"])
def visa_adjudication(case_id):
    authorize(["VisaCoordinator"])
    case = path_row(store.visa_cases, case_id, "ERR_VISA_CASE_NOT_FOUND")
    b = body()
    action = req_enum(b, "action", ADJUDICATION_ACTIONS)
    appointment = opt_date(b, "consulate_appointment_date")
    opt_str(b, "reason", min_len=1, max_len=1000)
    if action == "FILE" and appointment is None:
        bad("consulate_appointment_date is required on a FILE action")

    res = store.residencies.get(case["residency_id"])
    if res is None or res["status"] != "SCHEDULED":
        raise ApiError("ERR_RESIDENCY_NOT_SCHEDULED",
                       "visa adjudication requires a SCHEDULED residency")
    if res.get("session_start_date") is None:
        raise ApiError("ERR_RESIDENCY_NOT_SCHEDULED",
                       "the timeline is undefined until the residency is scheduled")
    target = ADJUDICATION_EDGE.get((action, case["status"]))
    if target is None:
        raise ApiError("ERR_VISA_STATE_INVALID",
                       "%s is not an edge from %s" % (action, case["status"]))

    if action == "FILE":
        _, filing_deadline, earliest_entry, _ = D.visa_timeline(case)
        today = store.today()
        if filing_deadline is not None and today > filing_deadline:
            raise ApiError("ERR_VISA_FILING_DEADLINE_PASSED",
                           "the filing deadline of %s has passed" % ds(filing_deadline))
        if appointment < today or (earliest_entry is not None
                                   and appointment > earliest_entry):
            raise ApiError("ERR_CONSULATE_DATE_OUT_OF_WINDOW",
                           "the consulate appointment falls outside the lawful window")
        case["consulate_appointment_date"] = ds(appointment)
        case["case_type"] = calc.visa_case_type(res.get("session_length_weeks"))
    case["status"] = target
    touch(case)
    return object_response(D.ser_visa_case(case))


# ---------------------------------------------------------------- stipend disbursements
READ_DISBURSEMENT_ROLES = ["FinanceOfficer", "ProgramAdmin", "Applicant"]
SETTLEMENT_ACTIONS = ["PAY", "VOID", "REVERSE"]


@bp.route("/stipend-disbursements", methods=["GET"])
def list_disbursements():
    authorize(READ_DISBURSEMENT_ROLES)
    residency_id = query_str("residency_id")
    status = query_str("status")
    period_index = query_int("period_index")
    rows = D.by_seq(list(store.disbursements.values()))
    if residency_id is not None:
        rows = [r for r in rows if r["residency_id"] == residency_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if period_index is not None:
        rows = [r for r in rows if int(r["period_index"]) == period_index]
    return paged(rows, D.ser_disbursement)


@bp.route("/stipend-disbursements/<disbursement_id>", methods=["GET"])
def get_disbursement(disbursement_id):
    authorize(READ_DISBURSEMENT_ROLES)
    row = path_row(store.disbursements, disbursement_id, "ERR_DISBURSEMENT_NOT_FOUND")
    return object_response(D.ser_disbursement(row))


def _settlement_edge(action, status):
    if action in ("PAY", "VOID"):
        return status == "SCHEDULED"
    return status == "PAID"


def _cumulative_paid_before(res, period_index):
    total = 0
    for row in D.residency_disbursements(res["id"]):
        if row["status"] == "PAID" and int(row["period_index"]) < period_index:
            total += int(row["gross_cents"])
    return total


def _is_final_period(res, row):
    live = [x for x in D.residency_disbursements(res["id"]) if x["status"] != "VOIDED"]
    if not live:
        return True
    return int(row["period_index"]) == max(int(x["period_index"]) for x in live)


@bp.route("/stipend-disbursements/<disbursement_id>/settlement", methods=["POST"])
def settle_disbursement(disbursement_id):
    actor = authorize(["FinanceOfficer"])
    row = path_row(store.disbursements, disbursement_id, "ERR_DISBURSEMENT_NOT_FOUND")
    b = body()
    action = req_enum(b, "action", SETTLEMENT_ACTIONS)
    paid_on = opt_date(b, "paid_on_date")
    opt_str(b, "reason", min_len=1, max_len=1000)

    if not _settlement_edge(action, row["status"]):
        raise ApiError("ERR_DISBURSEMENT_STATE_INVALID",
                       "%s is not an edge from %s" % (action, row["status"]))

    res = store.residencies.get(row["residency_id"])

    if action == "VOID":
        row["status"] = "VOIDED"
        row["withholding_cents"] = 0
        row["net_cents"] = 0
        touch(row)
        return object_response(D.ser_disbursement(row))

    if action == "REVERSE":
        # the second segregation point: the reverser may not be the payer
        if actor.user_id == row["paid_by_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                           "the officer who paid this row may not reverse it")
        row["status"] = "REVERSED"
        touch(row)
        if res is not None:
            D.recompute_residency_stipend_ledgers(res)
            touch(res)
        return object_response(D.ser_disbursement(row))

    # ---- PAY, under four further guards in ladder order
    if res is None or res["status"] not in ("IN_RESIDENCE", "COMPLETED"):
        raise ApiError("ERR_RESIDENCY_STATE_INVALID",
                       "only a resident in residence or completed may be paid")
    if res["compliance_status"] == "SUSPENDED":
        raise ApiError("ERR_COMPLIANCE_SUSPENDED",
                       "the resident's safety clearance is suspended")
    period_index = int(row["period_index"])
    for other in D.residency_disbursements(res["id"]):
        if int(other["period_index"]) < period_index and other["status"] == "SCHEDULED":
            raise ApiError("ERR_DISBURSEMENT_OUT_OF_ORDER",
                           "period %s is still SCHEDULED" % other["period_index"])
    if actor.user_id == row["scheduled_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "the officer who generated this schedule may not pay it")
    if _is_final_period(res, row) and int(res["obligations_breached_count"]) > 0:
        raise ApiError("ERR_OBLIGATIONS_OUTSTANDING",
                       "the final payment is withheld until the breached obligations "
                       "are settled")

    applicant = store.applicants.get(res["applicant_id"])
    treaty = bool(applicant["treaty_country"]) if applicant is not None else False
    rate = calc.withholding_rate(D.residency_tax_form_type(res), treaty)
    gross = int(row["gross_cents"])
    cumulative_before = _cumulative_paid_before(res, period_index)
    taxable, withheld = calc.withheld_actual(cumulative_before, gross, rate)

    row["withholding_rate"] = rate
    row["cumulative_taxable_cents"] = taxable
    row["withholding_cents"] = int(withheld)
    row["net_cents"] = gross - int(withheld)
    row["paid_on_date"] = ds(paid_on) if paid_on is not None else ds(store.today())
    row["paid_by_user_id"] = actor.user_id
    row["status"] = "PAID"
    touch(row)
    D.recompute_residency_stipend_ledgers(res)
    touch(res)
    return object_response(D.ser_disbursement(row))


# ---------------------------------------------------------------- obligations
READ_OBLIGATION_ROLES = ["ProgramAdmin", "Funder", "Applicant"]
WAIVABLE_RESIDENCY_STATUSES = ("SCHEDULED", "IN_RESIDENCE", "WITHDRAWN")


@bp.route("/obligations", methods=["GET"])
def list_obligations():
    authorize(READ_OBLIGATION_ROLES)
    filters = {
        "residency_id": query_str("residency_id"),
        "obligation_type": query_str("obligation_type"),
        "status": query_str("status"),
    }
    rows = D.by_seq(list(store.obligations.values()))
    for key, value in filters.items():
        if value is not None:
            rows = [r for r in rows if r[key] == value]
    return paged(rows, D.ser_obligation)


@bp.route("/obligations/<obligation_id>", methods=["GET"])
def get_obligation(obligation_id):
    authorize(READ_OBLIGATION_ROLES)
    row = path_row(store.obligations, obligation_id, "ERR_OBLIGATION_NOT_FOUND")
    return object_response(D.ser_obligation(row))


@bp.route("/obligations/<obligation_id>/progress", methods=["POST"])
def obligation_progress(obligation_id):
    authorize(["ProgramAdmin"])
    ob = path_row(store.obligations, obligation_id, "ERR_OBLIGATION_NOT_FOUND")
    b = body()
    action = req_enum(b, "action", ["LOG_COMPLETION", "WAIVE"])
    attendance = opt_int(b, "attendance", minimum=0)
    waived_reason = opt_str(b, "waived_reason", min_len=1, max_len=1000)

    if ob["status"] != "PENDING":
        raise ApiError("ERR_OBLIGATION_NOT_PENDING",
                       "an obligation in %s records no further progress" % ob["status"])

    res = store.residencies.get(ob["residency_id"])
    if action == "WAIVE":
        if res is None or res["status"] not in WAIVABLE_RESIDENCY_STATUSES:
            raise ApiError("ERR_RESIDENCY_NOT_SCHEDULED",
                           "an obligation may only be waived while the residency is "
                           "SCHEDULED, IN_RESIDENCE or WITHDRAWN")
        ob["status"] = "WAIVED"
        ob["waived_reason"] = waived_reason
    else:
        ob["completed_count"] = int(ob["completed_count"]) + 1
        ob["total_attendance"] = int(ob["total_attendance"]) + int(attendance or 0)
        if int(ob["completed_count"]) >= int(ob["required_count"]):
            ob["status"] = "SATISFIED"
    touch(ob)
    if res is not None:
        D.recompute_obligation_counters(res)
        touch(res)
    return object_response(D.ser_obligation(ob))
