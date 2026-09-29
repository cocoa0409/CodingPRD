"""Workout plans, workout alternatives and the controlling-class consultation cycle."""
from flask import Blueprint

from calc import (consultation_response_deadline, rank_alternatives,
                  workout_alternative_npv)
from datetimes import iso
from db import base_row, db, touch
from errors import ApiError
from middleware import (ASSET_MANAGER, CCR, COMMITTEE, PLATFORM_ADMIN,
                        STAFF_PLUS_CCR, authenticate, require_owner, role,
                        user_id)
from money import D, ZERO, q2, q6
from response import listing, object_response
from routing import (filter_rows, reject_system_only, require_target_role,
                     require_transition)
from services import (alternatives_of, apply_consultation_outcome, find,
                      has_current_accepted_appraisal, recompute_loan,
                      rows_of, sort_created, trust_of_loan)
from validate import (body, forbid, get_cash_flows, get_enum, get_int,
                      get_number, get_string, present)

bp = Blueprint("workout", __name__)

NPV_BASES = ("CONTRACTUAL", "DELAY_STRESSED")
ALTERNATIVE_TYPES = ("MODIFICATION", "DEED_IN_LIEU", "NOTE_SALE", "FORECLOSURE")

PLAN_STATUSES = ("DRAFT", "SCORED", "RECOMMENDED", "CONSULTATION",
                 "CONSENT_SATISFIED", "OBJECTED", "APPROVED", "EXECUTED",
                 "ABANDONED", "SUPERSEDED")
PLAN_TRANSITIONS = {
    "DRAFT": ("SCORED", "ABANDONED", "SUPERSEDED"),
    "SCORED": ("RECOMMENDED", "ABANDONED", "SUPERSEDED"),
    "RECOMMENDED": ("CONSULTATION", "ABANDONED"),
    "CONSULTATION": ("CONSENT_SATISFIED", "OBJECTED", "ABANDONED"),
    "OBJECTED": ("DRAFT", "ABANDONED"),
    "CONSENT_SATISFIED": ("APPROVED", "ABANDONED"),
    "APPROVED": ("EXECUTED", "ABANDONED"),
    "EXECUTED": (),
    "ABANDONED": (),
    "SUPERSEDED": (),
}
PLAN_TARGET_ROLES = {
    "SCORED": (ASSET_MANAGER,),
    "RECOMMENDED": (ASSET_MANAGER,),
    "DRAFT": (ASSET_MANAGER,),
    "EXECUTED": (ASSET_MANAGER,),
    "ABANDONED": (ASSET_MANAGER,),
    "APPROVED": (COMMITTEE,),
}
ALTERNATIVE_STATUSES = ("PROPOSED", "SCORED", "SELECTED", "DISCARDED", "SUPERSEDED")

CONSULTATION_SUBJECTS = ("WORKOUT_PLAN", "BORROWER_REQUEST")
CONSULTATION_STATUSES = ("PENDING", "CONSENTED", "OBJECTED", "DEEMED_CONSENTED",
                         "WAIVED")


def _superseded_ids(plan_id):
    out = set()
    for alt in alternatives_of(plan_id):
        target = alt.get("supersedes_alternative_id")
        if target:
            out.add(target)
    return out


# ------------------------------------------------------------- WorkoutPlan
@bp.route("/workout-plans", methods=["POST"])
def create_workout_plan():
    authenticate((ASSET_MANAGER,))
    data = body()
    loan_id = get_string(data, "loan_id")
    rate = get_number(data, "discount_rate_pct", exclusive_minimum=0)
    npv_basis = get_enum(data, "npv_basis", NPV_BASES, required=False) or "CONTRACTUAL"
    expected = get_int(data, "expected_loan_version")

    loan = find("loans", loan_id, "ERR_LOAN_NOT_FOUND")
    if loan["servicing_status"] not in ("SPECIAL_SERVICING", "IN_WORKOUT"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if int(loan["version"]) != int(expected):
        raise ApiError("ERR_STALE_LOAN_VERSION")

    row = base_row()
    row.update(
        {
            "loan_id": loan["id"],
            "discount_rate_pct": q6(rate),
            "npv_basis": npv_basis,
            "status": "DRAFT",
            "revision_round": 0,
            "recommended_alternative_id": None,
            "selected_alternative_id": None,
            "scored_on": None,
            "prepared_by_user_id": user_id(),
            "approved_by_user_id": None,
            "executed_on": None,
            "consent_requirement": None,
        }
    )
    db.workout_plans[row["id"]] = row

    for other in sort_created(rows_of("workout_plans")):
        if other["id"] == row["id"] or other["loan_id"] != loan["id"]:
            continue
        if other["status"] in ("DRAFT", "SCORED"):
            other["status"] = "SUPERSEDED"
            touch(other)
    loan["active_workout_plan_id"] = row["id"]
    if loan["servicing_status"] == "SPECIAL_SERVICING":
        loan["servicing_status"] = "IN_WORKOUT"
        trust = trust_of_loan(loan)
        from services import recompute_trust
        recompute_trust(trust)
        touch(trust)
    touch(loan)
    return object_response(row, 201)


@bp.route("/workout-plans/<plan_id>", methods=["GET"])
def get_workout_plan(plan_id):
    authenticate(STAFF_PLUS_CCR)
    row = find("workout_plans", plan_id, "ERR_WORKOUT_PLAN_NOT_FOUND")
    loan = db.loans.get(row["loan_id"])
    require_owner(loan["trust_id"] if loan else None)
    return object_response(row)


@bp.route("/workout-plans", methods=["GET"])
def list_workout_plans():
    authenticate(STAFF_PLUS_CCR)
    rows = sort_created(rows_of("workout_plans"))
    if role() == CCR:
        rows = [
            r for r in rows
            if db.loans.get(r["loan_id"]) is not None
            and db.loans[r["loan_id"]]["trust_id"] == user_id()
        ]
    rows = filter_rows(rows, (("loan_id", "loan_id"), ("status", "status"),
                              ("recommended_alternative_id", "recommended_alternative_id"),
                              ("selected_alternative_id", "selected_alternative_id"),
                              ("npv_basis", "npv_basis")))
    return listing(rows)


@bp.route("/workout-plans/<plan_id>/status", methods=["POST"])
def set_workout_plan_status(plan_id):
    authenticate((ASSET_MANAGER, COMMITTEE))
    plan = find("workout_plans", plan_id, "ERR_WORKOUT_PLAN_NOT_FOUND")
    data = body()
    to_status = get_enum(data, "to_status", PLAN_STATUSES)
    reject_system_only(to_status, PLAN_TARGET_ROLES)
    get_string(data, "note", required=False)

    selected = None
    if to_status == "RECOMMENDED":
        selected_id = get_string(data, "selected_alternative_id")
        selected = find("workout_alternatives", selected_id,
                        "ERR_WORKOUT_ALTERNATIVE_NOT_FOUND")
        if selected["workout_plan_id"] != plan["id"]:
            raise ApiError("ERR_SUBJECT_REFERENCE_MISMATCH")

    if to_status != "APPROVED":
        require_transition(plan["status"], to_status, PLAN_TRANSITIONS)
    if to_status == "APPROVED" and user_id() == plan["prepared_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    require_target_role(role(), to_status, PLAN_TARGET_ROLES)
    if to_status == "APPROVED" and plan["status"] != "CONSENT_SATISFIED":
        raise ApiError("ERR_CONSULTATION_NOT_SATISFIED")

    if to_status == "RECOMMENDED":
        if selected["id"] != plan.get("recommended_alternative_id"):
            raise ApiError("ERR_SERVICING_STANDARD_VIOLATION")
    elif to_status == "EXECUTED":
        if not has_current_accepted_appraisal(plan["loan_id"]):
            raise ApiError("ERR_STALE_APPRAISAL")
    elif to_status == "DRAFT":
        if int(plan["revision_round"]) >= 3:
            raise ApiError("ERR_REVISION_LIMIT_EXCEEDED")
    elif to_status == "SCORED":
        excluded = _superseded_ids(plan["id"])
        pool = [a for a in alternatives_of(plan["id"])
                if a["status"] == "PROPOSED" and a["id"] not in excluded]
        if not pool:
            raise ApiError("ERR_NO_ALTERNATIVES")

    loan = db.loans.get(plan["loan_id"])

    if to_status == "SCORED":
        for alt in alternatives_of(plan["id"]):
            if alt["id"] in excluded and alt["status"] in ("PROPOSED", "SCORED"):
                alt["status"] = "SUPERSEDED"
                alt["rank"] = None
                touch(alt)
        for alt in pool:
            discounted_pv, npv = workout_alternative_npv(
                alt["projected_cash_flows"], alt["upfront_cost_usd"],
                plan["discount_rate_pct"], plan["npv_basis"])
            alt["discounted_pv_usd"] = discounted_pv
            alt["npv_usd"] = npv
            alt["status"] = "SCORED"
        ordered = rank_alternatives(pool)
        for alt in ordered:
            touch(alt)
        plan["recommended_alternative_id"] = ordered[0]["id"]
        plan["scored_on"] = iso(db.now())

    elif to_status == "RECOMMENDED":
        plan["selected_alternative_id"] = selected["id"]
        for alt in alternatives_of(plan["id"]):
            if alt["id"] == selected["id"]:
                alt["status"] = "SELECTED"
                touch(alt)
            elif alt["status"] == "SCORED":
                alt["status"] = "DISCARDED"
                touch(alt)

    elif to_status == "DRAFT":
        plan["revision_round"] = int(plan["revision_round"]) + 1
        plan["recommended_alternative_id"] = None
        plan["selected_alternative_id"] = None
        plan["scored_on"] = None
        for alt in alternatives_of(plan["id"]):
            if alt["status"] in ("SCORED", "SELECTED", "DISCARDED"):
                alt["status"] = "PROPOSED"
                alt["rank"] = None
                alt["npv_usd"] = None
                alt["discounted_pv_usd"] = None
                touch(alt)

    elif to_status == "APPROVED":
        plan["approved_by_user_id"] = user_id()

    elif to_status == "EXECUTED":
        plan["executed_on"] = iso(db.now())
        alternative = db.workout_alternatives.get(plan.get("selected_alternative_id"))
        if alternative is not None and alternative["alternative_type"] == "MODIFICATION":
            loan["is_modified"] = True
        touch(loan)

    elif to_status == "ABANDONED":
        loan["active_workout_plan_id"] = None
        touch(loan)

    plan["status"] = to_status
    touch(plan)

    if to_status == "ABANDONED":
        for consultation in sort_created(rows_of("consultations")):
            if consultation.get("workout_plan_id") == plan["id"] and \
                    consultation["status"] == "PENDING":
                consultation["status"] = "WAIVED"
                touch(consultation)
    return object_response(plan)


# -------------------------------------------------------- WorkoutAlternative
@bp.route("/workout-alternatives", methods=["POST"])
def create_workout_alternative():
    authenticate((ASSET_MANAGER,))
    data = body()
    plan_id = get_string(data, "workout_plan_id")
    alternative_type = get_enum(data, "alternative_type", ALTERNATIVE_TYPES)
    flows = get_cash_flows(data, "projected_cash_flows")
    upfront = get_number(data, "upfront_cost_usd", minimum=0)
    supersedes_id = get_string(data, "supersedes_alternative_id", required=False)

    plan = find("workout_plans", plan_id, "ERR_WORKOUT_PLAN_NOT_FOUND")
    superseded = None
    if supersedes_id is not None:
        superseded = find("workout_alternatives", supersedes_id,
                          "ERR_WORKOUT_ALTERNATIVE_NOT_FOUND")
        if superseded["workout_plan_id"] != plan["id"]:
            raise ApiError("ERR_SUBJECT_REFERENCE_MISMATCH")
    if plan["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if superseded is not None and superseded["status"] not in ("PROPOSED", "SCORED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    row = base_row()
    row.update(
        {
            "workout_plan_id": plan["id"],
            "supersedes_alternative_id": supersedes_id,
            "alternative_type": alternative_type,
            "projected_cash_flows": [
                {"period_index": f["period_index"], "amount_usd": q2(f["amount_usd"])}
                for f in sorted(flows, key=lambda f: f["period_index"])
            ],
            "upfront_cost_usd": q2(upfront),
            "discounted_pv_usd": None,
            "npv_usd": None,
            "rank": None,
            "status": "PROPOSED",
        }
    )
    db.workout_alternatives[row["id"]] = row
    if superseded is not None:
        superseded["status"] = "SUPERSEDED"
        superseded["rank"] = None
        touch(superseded)
    return object_response(row, 201)


@bp.route("/workout-alternatives/<alternative_id>", methods=["GET"])
def get_workout_alternative(alternative_id):
    authenticate(STAFF_PLUS_CCR)
    row = find("workout_alternatives", alternative_id,
               "ERR_WORKOUT_ALTERNATIVE_NOT_FOUND")
    plan = db.workout_plans.get(row["workout_plan_id"])
    loan = db.loans.get(plan["loan_id"]) if plan else None
    require_owner(loan["trust_id"] if loan else None)
    return object_response(row)


@bp.route("/workout-alternatives", methods=["GET"])
def list_workout_alternatives():
    authenticate(STAFF_PLUS_CCR)
    rows = rows_of("workout_alternatives")
    if role() == CCR:
        keep = []
        for row in rows:
            plan = db.workout_plans.get(row["workout_plan_id"])
            loan = db.loans.get(plan["loan_id"]) if plan else None
            if loan is not None and loan["trust_id"] == user_id():
                keep.append(row)
        rows = keep
    rows.sort(key=lambda r: (0 if r.get("rank") is not None else 1,
                             r.get("rank") or 0, r["created_at"], r["_seq"]))
    rows = filter_rows(rows, (("workout_plan_id", "workout_plan_id"),
                              ("supersedes_alternative_id", "supersedes_alternative_id"),
                              ("alternative_type", "alternative_type"),
                              ("status", "status")))
    return listing(rows)


# ------------------------------------------------------ ConsultationRequest
@bp.route("/consultations", methods=["POST"])
def create_consultation():
    authenticate((ASSET_MANAGER,))
    data = body()
    trust_id = get_string(data, "trust_id")
    subject_type = get_enum(data, "subject_type", CONSULTATION_SUBJECTS)
    plan_id = get_string(data, "workout_plan_id", required=False)
    request_id = get_string(data, "borrower_request_id", required=False)
    if subject_type == "WORKOUT_PLAN":
        if plan_id is None or request_id is not None:
            raise ApiError("ERR_INVALID_REQUEST")
    else:
        if request_id is None or plan_id is not None:
            raise ApiError("ERR_INVALID_REQUEST")

    trust = find("trusts", trust_id, "ERR_TRUST_NOT_FOUND")
    plan = None
    borrower_request = None
    if subject_type == "WORKOUT_PLAN":
        plan = find("workout_plans", plan_id, "ERR_WORKOUT_PLAN_NOT_FOUND")
        subject_loan = db.loans.get(plan["loan_id"])
    else:
        borrower_request = find("borrower_requests", request_id,
                                "ERR_BORROWER_REQUEST_NOT_FOUND")
        subject_loan = db.loans.get(borrower_request["loan_id"])
    if subject_loan is None or subject_loan["trust_id"] != trust["id"]:
        raise ApiError("ERR_SUBJECT_REFERENCE_MISMATCH")

    subject = plan if plan is not None else borrower_request
    if subject["status"] != "RECOMMENDED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    issued = db.now()
    deadline = consultation_response_deadline(
        issued, trust["consultation_response_business_days"])
    rights = "CONSENT_RIGHT" if trust["control_status"] == "CONTROLLING" \
        else "CONSULTATION_ONLY"

    row = base_row()
    row.update(
        {
            "trust_id": trust["id"],
            "subject_type": subject_type,
            "workout_plan_id": plan["id"] if plan is not None else None,
            "borrower_request_id": borrower_request["id"] if borrower_request is not None else None,
            "rights_type": rights,
            "issued_at": iso(issued),
            "deadline_at": iso(deadline),
            "status": "PENDING",
            "responded_at": None,
            "response_note": None,
            "responded_by_user_id": None,
            "_deadline_dt": deadline,
        }
    )
    db.consultations[row["id"]] = row

    if plan is not None:
        plan["status"] = "CONSULTATION"
        plan["consent_requirement"] = rights
        touch(plan)
    else:
        borrower_request["status"] = "CONSULTATION_PENDING"
        touch(borrower_request)
    return object_response(row, 201)


@bp.route("/consultations/<consultation_id>", methods=["GET"])
def get_consultation(consultation_id):
    authenticate(STAFF_PLUS_CCR)
    row = find("consultations", consultation_id, "ERR_CONSULTATION_NOT_FOUND")
    require_owner(row["trust_id"])
    return object_response(row)


@bp.route("/consultations", methods=["GET"])
def list_consultations():
    authenticate(STAFF_PLUS_CCR)
    rows = rows_of("consultations")
    if role() == CCR:
        rows = [r for r in rows if r["trust_id"] == user_id()]
    rows.sort(key=lambda r: (r["_deadline_dt"], r["created_at"], r["_seq"]))
    rows = filter_rows(rows, (("trust_id", "trust_id"),
                              ("workout_plan_id", "workout_plan_id"),
                              ("borrower_request_id", "borrower_request_id"),
                              ("subject_type", "subject_type"),
                              ("rights_type", "rights_type"),
                              ("status", "status")))
    return listing(rows)


@bp.route("/consultations/<consultation_id>/response", methods=["POST"])
def respond_to_consultation(consultation_id):
    authenticate((CCR,))
    row = find("consultations", consultation_id, "ERR_CONSULTATION_NOT_FOUND")
    require_owner(row["trust_id"])
    data = body()
    response = get_enum(data, "response", ("CONSENTED", "OBJECTED"))
    note = get_string(data, "response_note", required=False)

    if row["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    now = db.now()
    if now > row["_deadline_dt"]:
        raise ApiError("ERR_CONSULTATION_WINDOW_CLOSED")

    row["status"] = response
    row["responded_at"] = iso(now)
    row["response_note"] = note
    row["responded_by_user_id"] = user_id()
    touch(row)
    apply_consultation_outcome(row)
    return object_response(row)


@bp.route("/consultations/sweep", methods=["POST"])
def sweep_consultations():
    authenticate((PLATFORM_ADMIN,))
    data = body()
    trust_id = get_string(data, "trust_id", required=False)
    if trust_id is not None:
        find("trusts", trust_id, "ERR_TRUST_NOT_FOUND")

    now = db.now()
    matches = [
        row
        for row in rows_of("consultations")
        if row["status"] == "PENDING"
        and row["_deadline_dt"] < now
        and (trust_id is None or row["trust_id"] == trust_id)
    ]
    matches.sort(key=lambda r: (r["_deadline_dt"], r["created_at"], r["_seq"]))

    swept = []
    for row in matches:
        row["status"] = "DEEMED_CONSENTED"
        touch(row)
        apply_consultation_outcome(row)
        swept.append(row["id"])
    return object_response({"swept_count": len(swept), "deemed_consented_ids": swept})
