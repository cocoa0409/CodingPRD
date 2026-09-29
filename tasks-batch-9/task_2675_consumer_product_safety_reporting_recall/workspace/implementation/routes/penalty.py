"""The civil penalty docket: assessment, negotiation, consent agreement (PRD 3.9)."""

from flask import Blueprint

import auth
import calc
import lookups
import responses
import shapes
import store
from errors import raise_error

bp = Blueprint("penalty", __name__)

CASE_STATUSES = ("ASSESSMENT_OPEN", "OFFER_MADE", "COUNTERED", "AGREED")
OFFER_PARTIES = ("AGENCY", "RESPONDENT")
RESOLUTIONS = ("WITHDRAWN", "ACCEPTED")
TIERS = ("TIER_1", "TIER_2", "TIER_3")
FILED_REPORT_STATUSES = ("SUBMITTED", "ACCEPTED", "RETURNED_FOR_INFO")
MAX_NEGOTIATION_ROUNDS = 6

ROLES = ("ProgramAdmin", "SafetyDirector", "PenaltyCounsel")


@bp.route("/civil-penalty-cases/<case_id>", methods=["GET"])
def get_case(case_id):
    auth.authorize(*ROLES)
    return responses.object_response(lookups.find("penalty_case", case_id))


@bp.route("/civil-penalty-cases", methods=["GET"])
def list_cases():
    auth.authorize(*ROLES)
    limit, offset = shapes.pagination()
    section_report_id = shapes.q_str("section_report_id")
    status = shapes.q_enum("status", CASE_STATUSES)
    tier = shapes.q_enum("cooperation_credit_tier", TIERS)
    bonus = shapes.q_bool("cooperation_bonus_applied")

    def keep(row):
        if section_report_id is not None and row["section_report_id"] != section_report_id:
            return False
        if status is not None and row["status"] != status:
            return False
        if tier is not None and row["cooperation_credit_tier"] != tier:
            return False
        if bonus is not None and row["cooperation_bonus_applied"] != bonus:
            return False
        return True

    return responses.list_response(
        store.ordered(store.penalty_cases, keep), limit, offset)


@bp.route("/civil-penalty-cases", methods=["POST"])
def create_case():
    auth.authorize("PenaltyCounsel")
    data = shapes.body()
    section_report_id = shapes._req(data, "section_report_id")
    violation_count = shapes.req_int(data, "violation_count", minimum=1)

    report = lookups.find("section_report", section_report_id)
    if report["status"] not in FILED_REPORT_STATUSES:
        raise_error("ERR_SECTION_REPORT_STATE_INVALID")

    for existing in store.penalty_cases.values():
        if existing["section_report_id"] == section_report_id:
            raise_error("ERR_DUPLICATE_DOCKET_ENTRY")

    assessed = calc.penalty_assessment(
        violation_count, lookups.pattern_for_report(report), report["days_late"])

    row = store.new_row(
        section_report_id=section_report_id,
        violation_count=violation_count,
        status="ASSESSMENT_OPEN",
        assessed_penalty_cents=assessed,
        reserved_cents=0,
        available_cents=assessed,
        current_offer_round=0,
        current_offer_cents=None,
        current_offer_by=None,
        cooperation_bonus_applied=False,
        cooperation_credit_tier=None,
        cooperation_credit_cents=None,
        consent_agreement_total_cents=None,
        consent_agreement_preview_cents=0,
        compliance_program_required=False,
        reporting_obligation_months=0,
    )
    calc.recompute_preview(row)
    store.penalty_cases[row["id"]] = row
    return responses.created(row)


@bp.route("/civil-penalty-cases/<case_id>/offers", methods=["POST"])
def table_offer(case_id):
    auth.authorize("PenaltyCounsel")
    case = lookups.find("penalty_case", case_id)
    data = shapes.body()
    amount_cents = shapes.req_money(data, "amount_cents")
    offered_by = shapes.req_enum(data, "offered_by", OFFER_PARTIES)
    expected_version = shapes.req_int(data, "expected_case_version")

    # The version guard precedes the state check.
    if expected_version != case["version"]:
        raise_error("ERR_STALE_PENALTY_CASE_VERSION")

    if offered_by == "AGENCY":
        if case["status"] not in ("ASSESSMENT_OPEN", "COUNTERED"):
            raise_error("ERR_PENALTY_CASE_STATE_INVALID")
    else:
        if case["status"] != "OFFER_MADE":
            raise_error("ERR_PENALTY_CASE_STATE_INVALID")

    if not case["current_offer_round"] < MAX_NEGOTIATION_ROUNDS:
        raise_error("ERR_NEGOTIATION_ROUNDS_EXHAUSTED")

    if amount_cents > case["assessed_penalty_cents"]:
        raise_error("ERR_OFFER_EXCEEDS_ASSESSMENT")

    case["current_offer_round"] = case["current_offer_round"] + 1
    case["current_offer_cents"] = amount_cents
    case["current_offer_by"] = offered_by
    if offered_by == "AGENCY":
        case["status"] = "OFFER_MADE"
        case["reserved_cents"] = amount_cents
        case["available_cents"] = case["assessed_penalty_cents"] - amount_cents
    else:
        case["status"] = "COUNTERED"
        case["reserved_cents"] = 0
        case["available_cents"] = case["assessed_penalty_cents"]

    calc.recompute_preview(case)
    store.touch(case)
    return responses.object_response(case)


@bp.route("/civil-penalty-cases/<case_id>/offer-resolution", methods=["POST"])
def resolve_offer(case_id):
    auth.authorize("PenaltyCounsel")
    case = lookups.find("penalty_case", case_id)
    data = shapes.body()
    resolution = shapes.req_enum(data, "resolution", RESOLUTIONS)
    shapes.opt_str(data, "note", 0, 2000)

    if case["status"] != "OFFER_MADE" or case["current_offer_by"] != "AGENCY":
        raise_error("ERR_PENALTY_CASE_STATE_INVALID")

    if resolution == "WITHDRAWN":
        case["status"] = "ASSESSMENT_OPEN"
        case["current_offer_cents"] = None
        case["current_offer_by"] = None
        # The consumed negotiation round is never given back.
        case["reserved_cents"] = 0
        case["available_cents"] = case["assessed_penalty_cents"]
        # The preview is recomputed in exactly three places (case opening, an
        # offer changing the standing number, cascade link 4) - not here.
        store.touch(case)
        return responses.object_response(case)

    settlement_base = case["current_offer_cents"]
    tier, credit, total = calc.consent_figures(
        settlement_base, case["cooperation_bonus_applied"])
    case["status"] = "AGREED"
    case["cooperation_credit_tier"] = tier
    case["cooperation_credit_cents"] = credit
    case["consent_agreement_total_cents"] = total
    case["compliance_program_required"] = total >= 5000000
    case["reporting_obligation_months"] = 24 if total >= 5000000 else 12
    case["reserved_cents"] = total
    case["available_cents"] = case["assessed_penalty_cents"] - total
    store.touch(case)
    return responses.object_response(case)
