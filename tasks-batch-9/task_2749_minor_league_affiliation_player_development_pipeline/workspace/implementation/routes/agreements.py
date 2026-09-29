"""Player Development License endpoints (PRD Sections 3.2 and 3.3)."""
from flask import Blueprint

import auth
import calc
import common
import config
import derive
import envelope
import flows
import serialize
import store
import validate
from errors import ApiError

bp = Blueprint("agreements", __name__)

TRANSITIONS = {
    "SUBMIT": ("DRAFT",),
    "ACTIVATE": ("SUBMITTED",),
    "REJECT": ("SUBMITTED",),
    "SUSPEND": ("ACTIVE",),
    "REINSTATE": ("SUSPENDED",),
    "TERMINATE": ("ACTIVE", "SUSPENDED"),
    "SETTLE": ("ACTIVE",),
}

AUDITED_FIELDS = ("audited_housing_expense_cents", "audited_meal_expense_cents",
                  "audited_travel_expense_cents", "audited_upkeep_expense_cents")


def _declared_gross(agreement):
    return {cat: agreement[config.CATEGORY_DECLARED_FIELD[cat]]
            for cat in config.CATEGORY_ORDER}


def _audited_gross(agreement):
    gross = {}
    for cat in config.CATEGORY_ORDER:
        audited = agreement[config.CATEGORY_AUDITED_FIELD[cat]]
        if audited is None:
            audited = agreement[config.CATEGORY_DECLARED_FIELD[cat]]
        gross[cat] = audited
    return gross


@bp.post("/affiliates/<affiliate_id>/agreements")
def draft_agreement(affiliate_id):
    user_id, role = auth.require(config.ROLE_OPERATOR, config.ROLE_COMPLIANCE)
    auth.check_scope(role, user_id, affiliate_id)
    common.need("affiliates", affiliate_id)
    body = validate.json_body()
    term_start = validate.date_field(body, "term_start_date")
    term_end = validate.date_field(body, "term_end_date")
    tier = validate.enum_field(body, "facility_standard_tier", config.FACILITY_TIERS)
    cap = validate.int_field(body, "club_reimbursement_cap_cents", lo=0)
    minimum = validate.int_field(body, "minimum_active_players", lo=0, hi=40,
                                 required=False, default=22)
    required_roles = validate.enum_list_field(body, "required_staff_roles",
                                              config.STAFF_ROLES, required=False,
                                              default=[])
    housing = validate.int_field(body, "housing_expense_cents", lo=0,
                                 required=False, default=0)
    meals = validate.int_field(body, "meal_expense_cents", lo=0,
                               required=False, default=0)
    travel = validate.int_field(body, "travel_expense_cents", lo=0,
                                required=False, default=0)
    upkeep = validate.int_field(body, "upkeep_expense_cents", lo=0,
                                required=False, default=0)
    if store.parse_date(term_end) <= store.parse_date(term_start):
        raise validate.bad("term_end_date must be strictly after term_start_date.")

    record = store.base_record()
    record.update({
        "affiliate_id": affiliate_id,
        "term_start_date": term_start,
        "term_end_date": term_end,
        "facility_standard_tier": tier,
        "minimum_active_players": minimum,
        "required_staff_roles": required_roles,
        "club_reimbursement_cap_cents": cap,
        "housing_expense_cents": housing,
        "meal_expense_cents": meals,
        "travel_expense_cents": travel,
        "upkeep_expense_cents": upkeep,
        "audited_housing_expense_cents": None,
        "audited_meal_expense_cents": None,
        "audited_travel_expense_cents": None,
        "audited_upkeep_expense_cents": None,
        "status": "DRAFT",
        "posture": "FROZEN",
        "provisional_club_obligation_cents": 0,
        "final_club_obligation_cents": None,
        "affiliate_overflow_cents": 0,
        "settlement_status": "NOT_SETTLED",
        "submitted_by_user_id": None,
    })
    store.agreements[record["id"]] = record
    common.commit()
    return envelope.object_response(serialize.agreement(record), 201)


@bp.get("/affiliates/<affiliate_id>/agreements")
def list_agreements(affiliate_id):
    auth.require(config.ROLE_FARM, config.ROLE_COMPLIANCE, config.ROLE_OPERATOR)
    common.need("affiliates", affiliate_id)
    rows = derive.agreements_of(affiliate_id)
    rows = common.apply_filters(rows, (("status", "status"),))
    return envelope.paginate(rows, serialize.agreement)


@bp.post("/agreements/<agreement_id>/disposition")
def dispose_agreement(agreement_id):
    user_id, role = auth.require(config.ROLE_OPERATOR, config.ROLE_COMPLIANCE)
    raw = auth.raw_body()
    agreement = common.find("agreements", agreement_id)
    if agreement is not None:
        auth.check_scope(role, user_id, agreement["affiliate_id"])
    auth.check_action_role(raw.get("action"), role, config.AGREEMENT_ACTION_ROLES)
    if agreement is None:
        raise ApiError("ERR_AGREEMENT_NOT_FOUND")

    body = validate.json_body()
    action = auth.require_action(body, config.AGREEMENT_ACTION_ROLES)
    audited = {}
    for field in AUDITED_FIELDS:
        audited[field] = validate.int_field(body, field, lo=0, required=False,
                                            default=None)
    validate.str_field(body, "note", required=False, default=None, allow_blank=True)

    if agreement["status"] not in TRANSITIONS[action]:
        raise ApiError("ERR_INVALID_AGREEMENT_STATE",
                       "An agreement in status %s cannot be %sd."
                       % (agreement["status"], action.title()))

    affiliate = store.affiliates.get(agreement["affiliate_id"])

    if action == "SETTLE":
        if agreement["settlement_status"] != "NOT_SETTLED":
            raise ApiError("ERR_ALREADY_SETTLED")

    if action == "SUBMIT":
        for other in derive.agreements_of(agreement["affiliate_id"]):
            if other["id"] == agreement["id"]:
                continue
            if other["status"] in ("SUBMITTED", "ACTIVE"):
                raise ApiError("ERR_DUPLICATE_ACTIVE_AGREEMENT")

    if action in ("ACTIVATE", "REINSTATE"):
        if affiliate is not None and affiliate["facility_status"] == "DEFICIENT":
            raise ApiError("ERR_FACILITY_DEFICIENCY_BLOCKING")

    store.touch(agreement)
    if action == "SUBMIT":
        agreement["status"] = "SUBMITTED"
        agreement["submitted_by_user_id"] = user_id
        provisional, overflow = calc.provisional_allocation(
            agreement["club_reimbursement_cap_cents"], _declared_gross(agreement))
        agreement["provisional_club_obligation_cents"] = provisional
        agreement["affiliate_overflow_cents"] = overflow
    elif action == "ACTIVATE":
        agreement["status"] = "ACTIVE"
    elif action == "REJECT":
        agreement["status"] = "REJECTED"
    elif action == "SUSPEND":
        agreement["status"] = "SUSPENDED"
        flows.cascade_agreement_suspended(agreement["affiliate_id"])
    elif action == "REINSTATE":
        agreement["status"] = "ACTIVE"
    elif action == "TERMINATE":
        agreement["status"] = "TERMINATED"
        flows.cascade_agreement_terminated(agreement["affiliate_id"])
    elif action == "SETTLE":
        for field in AUDITED_FIELDS:
            if audited[field] is not None:
                agreement[field] = audited[field]
        final, overflow = calc.final_allocation(
            agreement["club_reimbursement_cap_cents"], _audited_gross(agreement))
        agreement["final_club_obligation_cents"] = final
        agreement["affiliate_overflow_cents"] = overflow
        agreement["settlement_status"] = "SETTLED"

    common.commit()
    return envelope.object_response(serialize.agreement(agreement))
