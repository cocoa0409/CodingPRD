"""Borrower requests, appraisals, appraisal reductions and servicer advances."""
from flask import Blueprint

from calc import (request_deposit_floor, servicing_standard_analysis)
from datetimes import add_days, add_months, iso, parse_dt, render_like
from db import base_row, db, touch
from errors import ApiError
from middleware import (ALL_STAFF, ASSET_MANAGER, BORROWER, COMMITTEE,
                        MASTER_SERVICER, STAFF_PLUS_BORROWER, authenticate,
                        require_owner, role, user_id)
from money import D, ZERO, q2, q4, q6
from response import listing, object_response
from routing import (filter_rows, reject_system_only, require_target_role,
                     require_transition)
from services import (ACTIVE_ADVANCE_STATUSES, appraisals_of,
                      consultation_satisfied_for, create_provisional_reduction,
                      find, has_current_accepted_appraisal,
                      recalculate_prior_reductions, recompute_loan,
                      recompute_trust, refresh_advance, reductions_of, rows_of,
                      sort_created, supersede_prior_appraisals, trust_of_loan)
from validate import (body, forbid, get_datetime, get_enum, get_int,
                      get_number, get_string, present)

bp = Blueprint("credit", __name__)

REQUEST_TYPES = ("MODIFICATION", "ASSUMPTION", "LEASE_APPROVAL")
REQUEST_STATUSES = ("SUBMITTED", "UNDER_ANALYSIS", "INFO_REQUESTED", "RECOMMENDED",
                    "CONSULTATION_PENDING", "APPROVED", "DENIED", "WITHDRAWN")
REQUEST_TRANSITIONS = {
    "SUBMITTED": ("UNDER_ANALYSIS", "WITHDRAWN"),
    "UNDER_ANALYSIS": ("INFO_REQUESTED", "RECOMMENDED", "DENIED", "WITHDRAWN"),
    "INFO_REQUESTED": ("UNDER_ANALYSIS", "WITHDRAWN"),
    "RECOMMENDED": ("CONSULTATION_PENDING", "DENIED"),
    "CONSULTATION_PENDING": ("APPROVED", "DENIED"),
    "APPROVED": (),
    "DENIED": (),
    "WITHDRAWN": (),
}
REQUEST_TARGET_ROLES = {
    "UNDER_ANALYSIS": (ASSET_MANAGER,),
    "INFO_REQUESTED": (ASSET_MANAGER,),
    "RECOMMENDED": (ASSET_MANAGER,),
    "APPROVED": (COMMITTEE,),
    "DENIED": (COMMITTEE,),
    "WITHDRAWN": (BORROWER,),
}

APPRAISAL_TYPES = ("FULL_NARRATIVE", "UPDATE", "INTERNAL_VALUATION")
APPRAISAL_STATUSES = ("ORDERED", "RECEIVED", "ACCEPTED", "REJECTED", "SUPERSEDED",
                      "CANCELLED")
APPRAISAL_TRANSITIONS = {
    "ORDERED": ("RECEIVED", "CANCELLED"),
    "RECEIVED": ("ACCEPTED", "REJECTED"),
    "ACCEPTED": ("SUPERSEDED",),
    "REJECTED": (),
    "SUPERSEDED": (),
    "CANCELLED": (),
}
APPRAISAL_TARGET_ROLES = {
    "RECEIVED": (ASSET_MANAGER,),
    "ACCEPTED": (ASSET_MANAGER,),
    "REJECTED": (ASSET_MANAGER,),
    "CANCELLED": (ASSET_MANAGER,),
}

REDUCTION_STATUSES = ("PROVISIONAL", "EFFECTIVE", "RECALCULATED", "REVERSED")
REDUCTION_TRANSITIONS = {
    "PROVISIONAL": ("EFFECTIVE", "REVERSED"),
    "EFFECTIVE": ("RECALCULATED", "REVERSED"),
    "RECALCULATED": (),
    "REVERSED": (),
}
REDUCTION_TARGET_ROLES = {"EFFECTIVE": (COMMITTEE,), "REVERSED": (COMMITTEE,)}

ADVANCE_TYPES = ("PI_ADVANCE", "TAX_INSURANCE_ADVANCE", "PROPERTY_PROTECTION_ADVANCE")
ADVANCE_STATUSES = ("OUTSTANDING", "PARTIALLY_REIMBURSED", "REIMBURSED",
                    "DEEMED_NONRECOVERABLE", "REVERSED")
ADVANCE_TRANSITIONS = {
    "OUTSTANDING": ("PARTIALLY_REIMBURSED", "REIMBURSED", "DEEMED_NONRECOVERABLE",
                    "REVERSED"),
    "PARTIALLY_REIMBURSED": ("REIMBURSED", "DEEMED_NONRECOVERABLE"),
    "REIMBURSED": (),
    "DEEMED_NONRECOVERABLE": (),
    "REVERSED": (),
}
ADVANCE_TARGET_ROLES = {
    "DEEMED_NONRECOVERABLE": (COMMITTEE,),
    "REVERSED": (MASTER_SERVICER,),
}


# --------------------------------------------------------- BorrowerRequest
@bp.route("/borrower-requests", methods=["POST"])
def create_borrower_request():
    authenticate((BORROWER, ASSET_MANAGER))
    data = body()
    loan_id = get_string(data, "loan_id")
    request_type = get_enum(data, "request_type", REQUEST_TYPES)
    deposit = get_number(data, "processing_fee_deposit_usd", minimum=0)
    terms_note = get_string(data, "requested_terms_note")
    proposed_rate = get_number(data, "proposed_rate_pct", required=False)
    proposed_maturity = get_datetime(data, "proposed_maturity_date", required=False)[0]
    buyer = get_string(data, "assumption_buyer_name", required=False)
    suite = get_string(data, "suite_code", required=False)
    commencement_raw, commencement_dt = get_datetime(
        data, "lease_commencement_date", required=False)
    expiration_raw, expiration_dt = get_datetime(
        data, "lease_expiration_date", required=False)
    base_rent = get_number(data, "lease_base_rent_annual_usd", required=False)

    require_owner(loan_id)
    loan = find("loans", loan_id, "ERR_LOAN_NOT_FOUND")
    if loan["servicing_status"] not in ("SPECIAL_SERVICING", "IN_WORKOUT"):
        raise ApiError("ERR_LOAN_NOT_IN_SPECIAL_SERVICING")
    if D(deposit) < request_deposit_floor(request_type):
        raise ApiError("ERR_DEPOSIT_BELOW_MINIMUM")

    is_mod = request_type == "MODIFICATION"
    is_assumption = request_type == "ASSUMPTION"
    is_lease = request_type == "LEASE_APPROVAL"
    row = base_row()
    row.update(
        {
            "loan_id": loan["id"],
            "request_type": request_type,
            "status": "SUBMITTED",
            "processing_fee_deposit_usd": q2(deposit),
            "requested_terms_note": terms_note,
            "proposed_rate_pct": q6(proposed_rate) if (is_mod and proposed_rate is not None) else None,
            "proposed_maturity_date": proposed_maturity if is_mod else None,
            "assumption_buyer_name": buyer if is_assumption else None,
            "suite_code": suite if is_lease else None,
            "lease_commencement_date": commencement_raw if is_lease else None,
            "lease_expiration_date": expiration_raw if is_lease else None,
            "lease_base_rent_annual_usd": q2(base_rent) if (is_lease and base_rent is not None) else None,
            "info_request_count": 0,
            "npv_recovery_with_request_usd": None,
            "npv_recovery_without_request_usd": None,
            "analysis_discount_rate_pct": None,
            "servicing_standard_margin_usd": None,
            "servicing_standard_conclusion": None,
            "decided_on": None,
            "decided_by_user_id": None,
            "_lease_start_dt": commencement_dt if is_lease else None,
            "_lease_end_dt": expiration_dt if is_lease else None,
        }
    )
    db.borrower_requests[row["id"]] = row
    return object_response(row, 201)


@bp.route("/borrower-requests/<request_id>", methods=["GET"])
def get_borrower_request(request_id):
    authenticate(STAFF_PLUS_BORROWER)
    row = find("borrower_requests", request_id, "ERR_BORROWER_REQUEST_NOT_FOUND")
    require_owner(row["loan_id"])
    return object_response(row)


@bp.route("/borrower-requests", methods=["GET"])
def list_borrower_requests():
    authenticate(STAFF_PLUS_BORROWER)
    rows = sort_created(rows_of("borrower_requests"))
    if role() == BORROWER:
        rows = [r for r in rows if r["loan_id"] == user_id()]
    rows = filter_rows(rows, (("loan_id", "loan_id"), ("request_type", "request_type"),
                              ("status", "status"), ("suite_code", "suite_code")))
    return listing(rows)


@bp.route("/borrower-requests/<request_id>/analysis", methods=["POST"])
def record_analysis(request_id):
    authenticate((ASSET_MANAGER,))
    row = find("borrower_requests", request_id, "ERR_BORROWER_REQUEST_NOT_FOUND")
    data = body()
    npv_with = get_number(data, "npv_recovery_with_request_usd")
    npv_without = get_number(data, "npv_recovery_without_request_usd")
    rate = get_number(data, "analysis_discount_rate_pct")
    if row["status"] != "UNDER_ANALYSIS":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    loan = db.loans.get(row["loan_id"])
    margin, _required, conclusion = servicing_standard_analysis(
        npv_with, npv_without, loan["current_principal_balance_usd"])
    row["npv_recovery_with_request_usd"] = q2(npv_with)
    row["npv_recovery_without_request_usd"] = q2(npv_without)
    row["analysis_discount_rate_pct"] = q6(rate)
    row["servicing_standard_margin_usd"] = margin
    row["servicing_standard_conclusion"] = conclusion
    touch(row)
    return object_response(row)


def _lease_terms_overlap(a_start, a_end, b_start, b_end):
    if None in (a_start, a_end, b_start, b_end):
        return False
    return a_start <= b_end and b_start <= a_end


@bp.route("/borrower-requests/<request_id>/status", methods=["POST"])
def set_borrower_request_status(request_id):
    authenticate((BORROWER, ASSET_MANAGER, COMMITTEE))
    row = find("borrower_requests", request_id, "ERR_BORROWER_REQUEST_NOT_FOUND")
    require_owner(row["loan_id"])
    data = body()
    to_status = get_enum(data, "to_status", REQUEST_STATUSES)
    reject_system_only(to_status, REQUEST_TARGET_ROLES)
    get_string(data, "note", required=False)

    require_transition(row["status"], to_status, REQUEST_TRANSITIONS)
    require_target_role(role(), to_status, REQUEST_TARGET_ROLES)

    loan = db.loans.get(row["loan_id"])
    if to_status == "APPROVED":
        if not consultation_satisfied_for("BORROWER_REQUEST", "borrower_request_id",
                                          row["id"]):
            raise ApiError("ERR_CONSULTATION_NOT_SATISFIED")
        if row["request_type"] == "LEASE_APPROVAL":
            for other in rows_of("borrower_requests"):
                if other["id"] == row["id"]:
                    continue
                if other["loan_id"] != row["loan_id"] or other["status"] != "APPROVED":
                    continue
                if other.get("suite_code") != row.get("suite_code"):
                    continue
                if _lease_terms_overlap(row["_lease_start_dt"], row["_lease_end_dt"],
                                        other["_lease_start_dt"], other["_lease_end_dt"]):
                    raise ApiError("ERR_LEASE_TERM_OVERLAP")
    elif to_status == "RECOMMENDED":
        if row["servicing_standard_conclusion"] != "SERVICING_STANDARD_MET":
            raise ApiError("ERR_SERVICING_STANDARD_VIOLATION")
        if not has_current_accepted_appraisal(row["loan_id"]):
            raise ApiError("ERR_STALE_APPRAISAL")
    elif to_status == "INFO_REQUESTED":
        if int(row["info_request_count"]) >= 2:
            raise ApiError("ERR_INFO_REQUEST_LIMIT_EXCEEDED")

    if to_status == "INFO_REQUESTED":
        row["info_request_count"] = int(row["info_request_count"]) + 1
        row["servicing_standard_margin_usd"] = None
        row["servicing_standard_conclusion"] = None
    elif to_status in ("APPROVED", "DENIED"):
        row["decided_on"] = iso(db.now())
        row["decided_by_user_id"] = user_id()
        if to_status == "APPROVED" and row["request_type"] == "MODIFICATION":
            loan["is_modified"] = True
            touch(loan)

    row["status"] = to_status
    touch(row)
    return object_response(row)


# ---------------------------------------------------------------- Appraisal
@bp.route("/appraisals", methods=["POST"])
def create_appraisal():
    authenticate((ASSET_MANAGER,))
    data = body()
    loan_id = get_string(data, "loan_id")
    appraisal_type = get_enum(data, "appraisal_type", APPRAISAL_TYPES)
    ordered_raw, ordered_dt = get_datetime(data, "ordered_on")
    firm = get_string(data, "appraiser_firm")
    months = get_int(data, "valuation_valid_months", required=False, default=12,
                     minimum=1)
    loan = find("loans", loan_id, "ERR_LOAN_NOT_FOUND")

    row = base_row()
    row.update(
        {
            "loan_id": loan["id"],
            "appraisal_type": appraisal_type,
            "ordered_on": ordered_raw,
            "appraiser_firm": firm,
            "valuation_valid_months": months,
            "status": "ORDERED",
            "value_usd": None,
            "as_of_date": None,
            "estimated_liquidation_expenses_usd": None,
            "coverage_start_date": None,
            "coverage_end_date": None,
            "due_date": render_like(add_days(ordered_dt, 60), ordered_raw),
            "received_on": None,
            "ordered_by_user_id": user_id(),
            "accepted_by_user_id": None,
            "rejection_reason": None,
            "_ordered_on_dt": ordered_dt,
            "_coverage_start_dt": None,
            "_coverage_end_dt": None,
        }
    )
    db.appraisals[row["id"]] = row
    return object_response(row, 201)


@bp.route("/appraisals/<appraisal_id>", methods=["GET"])
def get_appraisal(appraisal_id):
    authenticate(ALL_STAFF)
    return object_response(find("appraisals", appraisal_id, "ERR_APPRAISAL_NOT_FOUND"))


@bp.route("/appraisals", methods=["GET"])
def list_appraisals():
    authenticate(ALL_STAFF)
    rows = filter_rows(
        sort_created(rows_of("appraisals")),
        (("loan_id", "loan_id"), ("appraisal_type", "appraisal_type"),
         ("status", "status")),
    )
    return listing(rows)


@bp.route("/appraisals/<appraisal_id>/status", methods=["POST"])
def set_appraisal_status(appraisal_id):
    authenticate((ASSET_MANAGER,))
    row = find("appraisals", appraisal_id, "ERR_APPRAISAL_NOT_FOUND")
    data = body()
    to_status = get_enum(data, "to_status", APPRAISAL_STATUSES)
    reject_system_only(to_status, APPRAISAL_TARGET_ROLES)

    value = as_of_raw = as_of_dt = expenses = None
    rejection_reason = None
    if to_status == "RECEIVED":
        value = get_number(data, "value_usd", minimum=0)
        as_of_raw, as_of_dt = get_datetime(data, "as_of_date")
        if row["appraisal_type"] == "FULL_NARRATIVE":
            expenses = get_number(data, "estimated_liquidation_expenses_usd", minimum=0)
        else:
            forbid(data, "estimated_liquidation_expenses_usd",
                   "only a FULL_NARRATIVE appraisal carries it")
        if as_of_dt < row["_ordered_on_dt"]:
            raise ApiError("ERR_INVALID_REQUEST",
                           "as_of_date must be at or after ordered_on.")
    elif to_status == "REJECTED":
        rejection_reason = get_string(data, "rejection_reason")

    require_transition(row["status"], to_status, APPRAISAL_TRANSITIONS)
    if to_status in ("ACCEPTED", "REJECTED"):
        if user_id() == row["ordered_by_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    require_target_role(role(), to_status, APPRAISAL_TARGET_ROLES)

    loan = db.loans.get(row["loan_id"])
    trust = trust_of_loan(loan)

    if to_status == "RECEIVED":
        start_dt = as_of_dt
        end_dt = add_months(as_of_dt, int(row["valuation_valid_months"]))
        for other in appraisals_of(row["loan_id"]):
            if other["id"] == row["id"] or other["status"] not in ("RECEIVED", "ACCEPTED"):
                continue
            o_start, o_end = other["_coverage_start_dt"], other["_coverage_end_dt"]
            if o_start is None or o_end is None:
                continue
            if start_dt < o_end and o_start < end_dt:
                raise ApiError("ERR_APPRAISAL_WINDOW_OVERLAP")
        row["value_usd"] = q2(value)
        row["as_of_date"] = as_of_raw
        if row["appraisal_type"] == "FULL_NARRATIVE":
            row["estimated_liquidation_expenses_usd"] = q2(expenses)
        row["coverage_start_date"] = as_of_raw
        row["coverage_end_date"] = render_like(end_dt, as_of_raw)
        row["_coverage_start_dt"] = start_dt
        row["_coverage_end_dt"] = end_dt
        row["received_on"] = iso(db.now())
        row["status"] = to_status
        touch(row)
        return object_response(row)

    if to_status == "ACCEPTED":
        touched_trust = bool([
            r for r in reductions_of(row["loan_id"]) if r["status"] == "EFFECTIVE"
        ])
        row["accepted_by_user_id"] = user_id()
        row["status"] = to_status
        supersede_prior_appraisals(row, loan)
        recalculate_prior_reductions(loan, None)
        create_provisional_reduction(row, loan, trust, user_id())
        loan["appraisal_required"] = False
        recompute_loan(loan)
        touch(row)
        touch(loan)
        if touched_trust:
            recompute_trust(trust)
            touch(trust)
        return object_response(row)

    if to_status == "REJECTED":
        row["rejection_reason"] = rejection_reason

    row["status"] = to_status
    touch(row)
    return object_response(row)


# -------------------------------------------------------- AppraisalReduction
@bp.route("/appraisal-reductions/<reduction_id>", methods=["GET"])
def get_reduction(reduction_id):
    authenticate(ALL_STAFF)
    return object_response(find("appraisal_reductions", reduction_id,
                                "ERR_APPRAISAL_REDUCTION_NOT_FOUND"))


@bp.route("/appraisal-reductions", methods=["GET"])
def list_reductions():
    authenticate(ALL_STAFF)
    rows = filter_rows(
        sort_created(rows_of("appraisal_reductions")),
        (("loan_id", "loan_id"), ("appraisal_id", "appraisal_id"),
         ("status", "status")),
    )
    return listing(rows)


@bp.route("/appraisal-reductions/<reduction_id>/status", methods=["POST"])
def set_reduction_status(reduction_id):
    authenticate((COMMITTEE,))
    row = find("appraisal_reductions", reduction_id,
               "ERR_APPRAISAL_REDUCTION_NOT_FOUND")
    data = body()
    to_status = get_enum(data, "to_status", REDUCTION_STATUSES)
    reject_system_only(to_status, REDUCTION_TARGET_ROLES)
    reversal_reason = None
    if to_status == "REVERSED":
        reversal_reason = get_string(data, "reversal_reason")

    require_transition(row["status"], to_status, REDUCTION_TRANSITIONS)
    if to_status == "EFFECTIVE":
        appraisal = db.appraisals.get(row["appraisal_id"])
        if appraisal is None or appraisal["status"] != "ACCEPTED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        for other in reductions_of(row["loan_id"]):
            if other["id"] != row["id"] and other["status"] == "EFFECTIVE":
                raise ApiError("ERR_INVALID_STATE_TRANSITION")
    require_target_role(role(), to_status, REDUCTION_TARGET_ROLES)

    loan = db.loans.get(row["loan_id"])
    trust = trust_of_loan(loan)

    if to_status == "EFFECTIVE":
        row["effective_on"] = iso(db.now())
        row["made_effective_by_user_id"] = user_id()
        row["advance_reduction_applies"] = True
    else:
        row["advance_reduction_applies"] = False
        row["reversal_reason"] = reversal_reason

    row["status"] = to_status
    recompute_loan(loan)
    recompute_trust(trust)
    touch(row)
    touch(loan)
    touch(trust)
    return object_response(row)


# ------------------------------------------------------------------ Advance
@bp.route("/advances", methods=["POST"])
def create_advance():
    authenticate((MASTER_SERVICER,))
    data = body()
    loan_id = get_string(data, "loan_id")
    advance_type = get_enum(data, "advance_type", ADVANCE_TYPES)
    amount = get_number(data, "amount_usd", exclusive_minimum=0)
    advanced_raw, advanced_dt = get_datetime(data, "advanced_on")
    loan = find("loans", loan_id, "ERR_LOAN_NOT_FOUND")

    if advance_type == "PI_ADVANCE":
        if q2(amount) > q2(loan["required_monthly_pi_advance_usd"]):
            raise ApiError("ERR_ADVANCE_EXCEEDS_ARA_ADJUSTED_OBLIGATION")
    for other in rows_of("advances"):
        if other["loan_id"] == loan["id"] and other["status"] == "DEEMED_NONRECOVERABLE":
            raise ApiError("ERR_NONRECOVERABLE_ADVANCE_OUTSTANDING")

    trust = trust_of_loan(loan)
    row = base_row()
    row.update(
        {
            "loan_id": loan["id"],
            "advance_type": advance_type,
            "amount_usd": q2(amount),
            "advanced_on": advanced_raw,
            "status": "OUTSTANDING",
            "reimbursed_principal_usd": ZERO,
            "reimbursed_interest_usd": ZERO,
            "accrued_interest_usd": ZERO,
            "interest_accrued_through": None,
            "nonrecoverable_determined_on": None,
            "reversal_reason": None,
            "_advanced_on_dt": advanced_dt,
        }
    )
    db.advances[row["id"]] = row
    refresh_advance(row, trust)
    recompute_loan(loan)
    recompute_trust(trust)
    touch(loan)
    touch(trust)
    return object_response(row, 201)


@bp.route("/advances/<advance_id>", methods=["GET"])
def get_advance(advance_id):
    authenticate(ALL_STAFF)
    row = find("advances", advance_id, "ERR_ADVANCE_NOT_FOUND")
    refresh_advance(row)
    return object_response(row)


@bp.route("/advances", methods=["GET"])
def list_advances():
    authenticate(ALL_STAFF)
    rows = rows_of("advances")
    for row in rows:
        refresh_advance(row)
    rows.sort(key=lambda r: (r["_advanced_on_dt"], r["created_at"], r["_seq"]))
    rows = filter_rows(rows, (("loan_id", "loan_id"),
                              ("advance_type", "advance_type"), ("status", "status")))
    return listing(rows)


@bp.route("/advances/<advance_id>/status", methods=["POST"])
def set_advance_status(advance_id):
    authenticate((MASTER_SERVICER, COMMITTEE))
    row = find("advances", advance_id, "ERR_ADVANCE_NOT_FOUND")
    data = body()
    to_status = get_enum(data, "to_status", ADVANCE_STATUSES)
    reject_system_only(to_status, ADVANCE_TARGET_ROLES)
    reversal_reason = get_string(data, "reversal_reason")

    require_transition(row["status"], to_status, ADVANCE_TRANSITIONS)
    if to_status == "REVERSED":
        if D(row["reimbursed_principal_usd"]) != 0 or \
                D(row["reimbursed_interest_usd"]) != 0:
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
    require_target_role(role(), to_status, ADVANCE_TARGET_ROLES)

    loan = db.loans.get(row["loan_id"])
    trust = trust_of_loan(loan)
    row["reversal_reason"] = reversal_reason
    if to_status == "REVERSED":
        row["accrued_interest_usd"] = ZERO
        row["interest_accrued_through"] = None
    else:
        refresh_advance(row, trust)
        row["nonrecoverable_determined_on"] = iso(db.now())
    row["status"] = to_status

    recompute_loan(loan)
    recompute_trust(trust)
    touch(row)
    touch(loan)
    touch(trust)
    return object_response(row)
