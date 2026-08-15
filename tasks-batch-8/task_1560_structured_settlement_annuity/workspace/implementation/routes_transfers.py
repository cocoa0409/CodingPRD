"""Routes: transfer petitions (secondary market / SSPA)."""

from decimal import Decimal

from flask import Blueprint, request

from db import DB, CLOCK, base_entity, touch, clock_date_iso, parse_date, add_years
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_FORBIDDEN_ROLE,
    ERR_AGREEMENT_INVALID_STATE,
    ERR_PETITION_INVALID_STATE,
    ERR_GUARDIANSHIP_REQUIRED,
    ERR_SOD_VIOLATION,
    ERR_EFFECTIVE_RATE_EXCEEDS_CAP,
    ERR_PRICE_EXCEEDS_PRESENT_VALUE,
    ERR_REFILE_BARRED_WITH_PREJUDICE,
    ERR_TRANSFER_WINDOW_OVERLAP,
    ERR_NO_TRANSFERRABLE_PAYMENTS,
    ERR_IPA_REQUIRED,
    ERR_COOLING_OFF_NOT_ELAPSED,
    ERR_INVALID_REQUEST,
)
from middleware import (
    get_caller, require_roles, get_json_body, check_unknown_fields,
    require_field, opt_field, as_string, as_positive_int, as_date, as_enum,
    parse_pagination,
)
from response import success_object, success_list
from services import (
    pub, list_view, find_profile_by_state, active_schedule_for,
    recompute_agreement_totals, exhaustion_check, compute_is_minor,
    active_guardianship, pv_per_payment_then_sum, disclosed_discount_rate_bps,
    solve_irr_bps, t_years,
)

bp = Blueprint("transfers", __name__)

PETITION_FIELDS = {
    "settlement_agreement_id", "payee_id", "factoring_company_name",
    "purchase_price_cents", "transfer_start_date", "transfer_end_date",
}


def petition_view(p):
    return pub(p)


def _matched_payments(agreement_id, start_date, end_date):
    """Payments of the agreement's ACTIVE schedule in {SCHEDULED, PAYABLE}
    with due_date in [start, end] inclusive."""
    sched = active_schedule_for(agreement_id)
    if sched is None:
        return []
    out = []
    for p in DB.scheduled_payments.values():
        if p["payment_schedule_id"] != sched["id"]:
            continue
        if p["status"] not in ("SCHEDULED", "PAYABLE"):
            continue
        d = parse_date(p["due_date"])
        if start_date <= d <= end_date:
            out.append(p)
    out.sort(key=lambda p: (p["due_date"], p["payment_seq_no"], p["id"]))
    return out


def _payment_set_ids(payments):
    return {p["id"] for p in payments}


@bp.route("/annuity/transfer-petitions", methods=["POST"])
def create_petition():
    caller = get_caller()
    require_roles(caller, {"Payee", "CaseManager"})
    body = get_json_body()
    said = body.get("settlement_agreement_id")
    pid = body.get("payee_id")
    # Payee self-service ownership (priority 2)
    if caller.role == "Payee":
        if pid is not None and isinstance(pid, str) and pid != caller.user_id:
            raise ApiError(ERR_FORBIDDEN_ROLE, "Payee may only draft petitions for themselves", 403)
    # existence
    agreement = None
    if said is not None and isinstance(said, str):
        agreement = DB.settlement_agreements.get(said)
        if agreement is None:
            raise ApiError(ERR_NOT_FOUND, "SettlementAgreement not found", 404)
    payee = None
    if pid is not None and isinstance(pid, str):
        payee = DB.payees.get(pid)
        if payee is None:
            raise ApiError(ERR_NOT_FOUND, "Payee not found", 404)
    # cross-entity state (priority 18): agreement must be FUNDED or ACTIVE
    if agreement is not None and agreement["status"] not in ("FUNDED", "ACTIVE"):
        raise ApiError(ERR_AGREEMENT_INVALID_STATE, "Agreement not FUNDED or ACTIVE", 409)
    # shape (so we can compute the matched set)
    check_unknown_fields(body, PETITION_FIELDS)
    said = as_string(require_field(body, "settlement_agreement_id"), "settlement_agreement_id")
    agreement = DB.settlement_agreements.get(said)
    if agreement is None:
        raise ApiError(ERR_NOT_FOUND, "SettlementAgreement not found", 404)
    if agreement["status"] not in ("FUNDED", "ACTIVE"):
        raise ApiError(ERR_AGREEMENT_INVALID_STATE, "Agreement not FUNDED or ACTIVE", 409)
    pid = as_string(require_field(body, "payee_id"), "payee_id")
    if caller.role == "Payee" and pid != caller.user_id:
        raise ApiError(ERR_FORBIDDEN_ROLE, "Payee may only draft petitions for themselves", 403)
    payee = DB.payees.get(pid)
    if payee is None:
        raise ApiError(ERR_NOT_FOUND, "Payee not found", 404)
    fc = as_string(require_field(body, "factoring_company_name"), "factoring_company_name")
    price = as_positive_int(require_field(body, "purchase_price_cents"), "purchase_price_cents")
    start = as_date(require_field(body, "transfer_start_date"), "transfer_start_date")
    end = as_date(require_field(body, "transfer_end_date"), "transfer_end_date")
    if end < start:
        raise ApiError(ERR_INVALID_REQUEST, "transfer_end_date must be >= transfer_start_date", 400)

    # matched set
    matched = _matched_payments(said, start, end)
    if len(matched) == 0:
        raise ApiError(ERR_NO_TRANSFERRABLE_PAYMENTS, "Petition window matches zero eligible payments", 409)

    # economics: valuation date = creation clock date
    valuation = CLOCK.today()
    policy = None
    for pol in DB.annuity_policies.values():
        if pol["settlement_agreement_id"] == said:
            policy = pol
            break
    if policy is None:
        raise ApiError(ERR_NOT_FOUND, "AnnuityPolicy not found for agreement", 404)
    pairs = [(p["amount_cents"], parse_date(p["due_date"])) for p in matched]
    pv = pv_per_payment_then_sum(pairs, policy["contract_discount_rate_bps"], valuation)
    nominal = sum(a for a, _ in pairs)
    wavg_num = Decimal(0)
    for amount, due in pairs:
        wavg_num += Decimal(amount) * t_years(valuation, due)
    wavg_years = wavg_num / Decimal(nominal)
    disclosed = disclosed_discount_rate_bps(nominal, price, wavg_years)
    effective = solve_irr_bps(pairs, price, valuation)

    e = base_entity()
    e.update({
        "settlement_agreement_id": said,
        "payee_id": pid,
        "factoring_company_name": fc,
        "purchase_price_cents": price,
        "transfer_start_date": start.isoformat(),
        "transfer_end_date": end.isoformat(),
        "state_code": None,
        "filed_by_user_id": None,
        "filed_at": None,
        "disclosure_served_at": None,
        "hearing_date": None,
        "ipa_completed_at": None,
        "transferred_payment_count": len(matched),
        "present_value_cents": pv,
        "disclosed_discount_rate_bps": disclosed,
        "effective_annual_rate_bps": effective,
        "court_outcome": None,
        "court_order_date": None,
        "prejudice": None,
        "approved_price_cents": None,
        "order_recorded_by_user_id": None,
        "status": "DRAFT",
    })
    DB.transfer_petitions[e["id"]] = e
    return success_object(petition_view(e), status=201)


@bp.route("/annuity/transfer-petitions", methods=["GET"])
def list_petitions():
    caller = get_caller()
    require_roles(caller, {"Any"})
    limit, offset = parse_pagination(request.args)
    items = list(DB.transfer_petitions.values())
    f = request.args.get("settlement_agreement_id")
    if f is not None:
        items = [p for p in items if p["settlement_agreement_id"] == f]
    f = request.args.get("payee_id")
    if f is not None:
        items = [p for p in items if p["payee_id"] == f]
    f = request.args.get("status")
    if f is not None:
        items = [p for p in items if p["status"] == f]
    page, total = list_view(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/annuity/transfer-petitions/<petitionId>", methods=["GET"])
def get_petition(petitionId):
    caller = get_caller()
    require_roles(caller, {"Any"})
    p = DB.transfer_petitions.get(petitionId)
    if p is None:
        raise ApiError(ERR_NOT_FOUND, "TransferPetition not found", 404)
    return success_object(petition_view(p))


@bp.route("/annuity/transfer-petitions/<petitionId>/file", methods=["POST"])
def file_petition(petitionId):
    caller = get_caller()
    require_roles(caller, {"Payee", "CaseManager"})
    pet = DB.transfer_petitions.get(petitionId)
    if pet is None:
        raise ApiError(ERR_NOT_FOUND, "TransferPetition not found", 404)
    # Payee self-service ownership
    if caller.role == "Payee" and pet["payee_id"] != caller.user_id:
        raise ApiError(ERR_FORBIDDEN_ROLE, "Payee may only file their own petition", 403)
    # state guard
    if pet["status"] != "DRAFT":
        raise ApiError(ERR_PETITION_INVALID_STATE, "Petition not DRAFT", 409)
    payee = DB.payees.get(pet["payee_id"])
    if payee is None:
        raise ApiError(ERR_NOT_FOUND, "Payee not found", 404)
    profile = find_profile_by_state(payee["address_state_code"])
    if profile is None:
        raise ApiError(ERR_NOT_FOUND, "StateStatuteProfile not found", 404)

    # business guards in global order (priorities 5, 8, 11, 13, 19):
    # priority 5: guardianship for a minor
    if compute_is_minor(payee) and active_guardianship(payee["id"]) is None:
        raise ApiError(ERR_GUARDIANSHIP_REQUIRED, "Minor payee requires an ACTIVE GuardianshipCase", 403)
    # priority 8: SSPA effective-rate cap
    if pet["effective_annual_rate_bps"] > profile["sspa_max_discount_rate_bps"]:
        raise ApiError(ERR_EFFECTIVE_RATE_EXCEEDS_CAP, "effective_annual_rate_bps exceeds the SSPA cap", 422)
    # priority 11: refile bar — barred while clock date < court_order_date + 365 days
    today = CLOCK.today()
    from datetime import timedelta
    for other in DB.transfer_petitions.values():
        if other["payee_id"] != pet["payee_id"]:
            continue
        if other["status"] != "COURT_DENIED":
            continue
        if other.get("prejudice") != "WITH":
            continue
        cod = other.get("court_order_date")
        if not cod:
            continue
        if today < parse_date(cod) + timedelta(days=365):
            raise ApiError(ERR_REFILE_BARRED_WITH_PREJUDICE, "Refiling barred by a with-prejudice denial", 409)
    # priority 13: transfer window overlap
    my_start = parse_date(pet["transfer_start_date"])
    my_end = parse_date(pet["transfer_end_date"])
    my_set = _payment_set_ids(_matched_payments(pet["settlement_agreement_id"], my_start, my_end))
    for other in DB.transfer_petitions.values():
        if other["id"] == pet["id"]:
            continue
        if other["settlement_agreement_id"] != pet["settlement_agreement_id"]:
            continue
        if other["status"] not in ("FILED", "DISCLOSURE_SERVED", "HEARING_SCHEDULED", "COURT_APPROVED", "EFFECTIVE"):
            continue
        o_set = _payment_set_ids(_matched_payments(
            other["settlement_agreement_id"],
            parse_date(other["transfer_start_date"]),
            parse_date(other["transfer_end_date"]),
        ))
        # For EFFECTIVE petitions the payments have left SCHEDULED/PAYABLE;
        # their transferred set is recorded via transferred_by_petition_id.
        if other["status"] == "EFFECTIVE":
            o_set = {p["id"] for p in DB.scheduled_payments.values()
                     if p.get("transferred_by_petition_id") == other["id"]}
        if my_set & o_set:
            raise ApiError(ERR_TRANSFER_WINDOW_OVERLAP, "Matched payment set intersects another petition's set", 409)
    # priority 19: price <= PV
    if pet["purchase_price_cents"] > pet["present_value_cents"]:
        raise ApiError(ERR_PRICE_EXCEEDS_PRESENT_VALUE, "purchase_price_cents exceeds present_value_cents", 422)

    get_json_body()
    pet["status"] = "FILED"
    pet["filed_at"] = clock_date_iso()
    pet["filed_by_user_id"] = caller.user_id
    pet["state_code"] = payee["address_state_code"]
    touch(pet)
    return success_object(petition_view(pet))


@bp.route("/annuity/transfer-petitions/<petitionId>/serve-disclosure", methods=["POST"])
def serve_disclosure(petitionId):
    caller = get_caller()
    require_roles(caller, {"CaseManager"})
    pet = DB.transfer_petitions.get(petitionId)
    if pet is None:
        raise ApiError(ERR_NOT_FOUND, "TransferPetition not found", 404)
    if pet["status"] != "FILED":
        raise ApiError(ERR_PETITION_INVALID_STATE, "Petition not FILED", 409)
    get_json_body()
    pet["status"] = "DISCLOSURE_SERVED"
    pet["disclosure_served_at"] = clock_date_iso()
    touch(pet)
    return success_object(petition_view(pet))


@bp.route("/annuity/transfer-petitions/<petitionId>/schedule-hearing", methods=["POST"])
def schedule_hearing(petitionId):
    caller = get_caller()
    require_roles(caller, {"CaseManager"})
    pet = DB.transfer_petitions.get(petitionId)
    if pet is None:
        raise ApiError(ERR_NOT_FOUND, "TransferPetition not found", 404)
    if pet["status"] != "DISCLOSURE_SERVED":
        raise ApiError(ERR_PETITION_INVALID_STATE, "Petition not DISCLOSURE_SERVED", 409)
    profile = find_profile_by_state(pet["state_code"])
    if profile is None:
        raise ApiError(ERR_NOT_FOUND, "StateStatuteProfile not found", 404)
    body = get_json_body()
    # temporal gates (priority 9 then 10) before shape validation
    today = CLOCK.today()
    served = parse_date(pet["disclosure_served_at"])
    from datetime import timedelta
    if today < served + timedelta(days=profile["disclosure_cooling_off_days"]):
        raise ApiError(ERR_COOLING_OFF_NOT_ELAPSED, "Cooling-off period has not elapsed", 409)
    if profile["ipa_required"] and not body.get("ipa_completed_at"):
        raise ApiError(ERR_IPA_REQUIRED, "Independent professional advice is required", 409)
    check_unknown_fields(body, {"hearing_date", "ipa_completed_at"})
    hd = as_date(require_field(body, "hearing_date"), "hearing_date")
    ipa = opt_field(body, "ipa_completed_at")
    ipa_iso = None
    if ipa is not None:
        ipa_iso = as_date(ipa, "ipa_completed_at").isoformat()
    pet["hearing_date"] = hd.isoformat()
    if ipa_iso is not None:
        pet["ipa_completed_at"] = ipa_iso
    pet["status"] = "HEARING_SCHEDULED"
    touch(pet)
    return success_object(petition_view(pet))


@bp.route("/annuity/transfer-petitions/<petitionId>/withdraw", methods=["POST"])
def withdraw_petition(petitionId):
    caller = get_caller()
    require_roles(caller, {"Payee", "CaseManager"})
    pet = DB.transfer_petitions.get(petitionId)
    if pet is None:
        raise ApiError(ERR_NOT_FOUND, "TransferPetition not found", 404)
    if caller.role == "Payee" and pet["payee_id"] != caller.user_id:
        raise ApiError(ERR_FORBIDDEN_ROLE, "Payee may only withdraw their own petition", 403)
    if pet["status"] not in ("FILED", "DISCLOSURE_SERVED", "HEARING_SCHEDULED"):
        raise ApiError(ERR_PETITION_INVALID_STATE, "Petition not in a withdrawable state", 409)
    get_json_body()
    pet["status"] = "WITHDRAWN"
    touch(pet)
    return success_object(petition_view(pet))


@bp.route("/annuity/transfer-petitions/<petitionId>/record-court-order", methods=["POST"])
def record_court_order(petitionId):
    caller = get_caller()
    require_roles(caller, {"JudicialRecorder"})
    pet = DB.transfer_petitions.get(petitionId)
    if pet is None:
        raise ApiError(ERR_NOT_FOUND, "TransferPetition not found", 404)
    if pet["status"] != "HEARING_SCHEDULED":
        raise ApiError(ERR_PETITION_INVALID_STATE, "Petition not HEARING_SCHEDULED", 409)
    if caller.user_id == pet["filed_by_user_id"]:
        raise ApiError(ERR_SOD_VIOLATION, "Recorder must differ from filer", 403)
    body = get_json_body()
    outcome = body.get("outcome")
    # outcome-specific business guards (still ERR_INVALID_REQUEST, 400)
    if outcome == "APPROVED_MODIFIED":
        ap = body.get("approved_price_cents")
        if ap is None or not isinstance(ap, int) or isinstance(ap, bool) or ap >= pet["purchase_price_cents"]:
            raise ApiError(ERR_INVALID_REQUEST, "APPROVED_MODIFIED requires approved_price_cents < purchase_price_cents", 400)
    if outcome == "DENIED":
        if body.get("prejudice") is None:
            raise ApiError(ERR_INVALID_REQUEST, "DENIED requires prejudice", 400)
    check_unknown_fields(body, {"outcome", "court_order_date", "prejudice", "approved_price_cents"})
    outcome = as_enum(require_field(body, "outcome"), "outcome",
                      {"APPROVED", "APPROVED_MODIFIED", "DENIED"})
    cod = as_date(require_field(body, "court_order_date"), "court_order_date")
    prejudice = opt_field(body, "prejudice")
    if prejudice is not None:
        prejudice = as_enum(prejudice, "prejudice", {"WITH", "WITHOUT"})
    approved_price = opt_field(body, "approved_price_cents")
    if approved_price is not None:
        if isinstance(approved_price, bool) or not isinstance(approved_price, int):
            raise ApiError(ERR_INVALID_REQUEST, "approved_price_cents must be an integer", 400)

    pet["court_outcome"] = outcome
    pet["court_order_date"] = cod.isoformat()
    pet["order_recorded_by_user_id"] = caller.user_id
    if outcome == "DENIED":
        pet["prejudice"] = prejudice
        pet["status"] = "COURT_DENIED"
    else:
        if prejudice is not None:
            pet["prejudice"] = prejudice
        if outcome == "APPROVED_MODIFIED":
            pet["approved_price_cents"] = approved_price
        else:
            pet["approved_price_cents"] = pet["purchase_price_cents"]
        pet["status"] = "COURT_APPROVED"
    touch(pet)
    return success_object(petition_view(pet))


@bp.route("/annuity/transfer-petitions/<petitionId>/effectuate", methods=["POST"])
def effectuate_petition(petitionId):
    caller = get_caller()
    require_roles(caller, {"ComplianceOfficer"})
    pet = DB.transfer_petitions.get(petitionId)
    if pet is None:
        raise ApiError(ERR_NOT_FOUND, "TransferPetition not found", 404)
    if pet["status"] != "COURT_APPROVED":
        raise ApiError(ERR_PETITION_INVALID_STATE, "Petition not COURT_APPROVED", 409)
    get_json_body()
    matched = _matched_payments(
        pet["settlement_agreement_id"],
        parse_date(pet["transfer_start_date"]),
        parse_date(pet["transfer_end_date"]),
    )
    if len(matched) == 0:
        raise ApiError(ERR_NO_TRANSFERRABLE_PAYMENTS, "No transferrable payments remain in the window", 409)
    agreement = DB.settlement_agreements.get(pet["settlement_agreement_id"])
    for p in matched:
        p["status"] = "TRANSFERRED"
        p["transferred_by_petition_id"] = pet["id"]
        touch(p)
        if agreement is not None:
            agreement["transferred_total_cents"] += p["amount_cents"]
    if agreement is not None:
        recompute_agreement_totals(agreement)
    pet["status"] = "EFFECTIVE"
    touch(pet)
    if agreement is not None:
        exhaustion_check(agreement)
    return success_object(petition_view(pet))
