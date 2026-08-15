"""Routes: death claims, commutation requests, escheatment batches."""

from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

from db import DB, CLOCK, base_entity, touch, parse_date
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_CLAIM_INVALID_STATE,
    ERR_COMMUTATION_INVALID_STATE,
    ERR_COMMUTATION_NOT_PERMITTED,
    ERR_NO_COMMUTABLE_PAYMENTS,
    ERR_STALE_POLICY_VERSION,
    ERR_BATCH_INVALID_STATE,
    ERR_SOD_VIOLATION,
    ERR_OPEN_BATCH_EXISTS,
    ERR_INVALID_REQUEST,
)
from middleware import (
    get_caller, require_roles, get_json_body, check_unknown_fields,
    require_field, opt_field, as_string, as_date, as_enum, as_year_month,
    parse_pagination,
)
from response import success_object, success_list
from services import (
    pub, list_view, find_profile_by_state, active_schedule_for,
    recompute_agreement_totals, exhaustion_check, policy_for_agreement,
    pv_per_payment_then_sum,
)

bp = Blueprint("claims", __name__)


# ---------------------------------------------------------------------------
# DeathClaim
# ---------------------------------------------------------------------------

CLAIM_FIELDS = {"payee_id", "settlement_agreement_id", "date_of_death", "claimant_type", "claimant_name"}


def claim_view(c):
    return pub(c)


@bp.route("/annuity/death-claims", methods=["POST"])
def create_claim():
    caller = get_caller()
    require_roles(caller, {"CaseManager"})
    body = get_json_body()
    pid = body.get("payee_id")
    said = body.get("settlement_agreement_id")
    payee = None
    if pid is not None and isinstance(pid, str):
        payee = DB.payees.get(pid)
        if payee is None:
            raise ApiError(ERR_NOT_FOUND, "Payee not found", 404)
    agreement = None
    if said is not None and isinstance(said, str):
        agreement = DB.settlement_agreements.get(said)
        if agreement is None:
            raise ApiError(ERR_NOT_FOUND, "SettlementAgreement not found", 404)
    # state/business: payee must be ACTIVE (ERR_CLAIM_INVALID_STATE)
    if payee is not None and payee["status"] != "ACTIVE":
        raise ApiError(ERR_CLAIM_INVALID_STATE, "Payee not ACTIVE", 409)
    check_unknown_fields(body, CLAIM_FIELDS)
    pid = as_string(require_field(body, "payee_id"), "payee_id")
    payee = DB.payees.get(pid)
    if payee is None:
        raise ApiError(ERR_NOT_FOUND, "Payee not found", 404)
    if payee["status"] != "ACTIVE":
        raise ApiError(ERR_CLAIM_INVALID_STATE, "Payee not ACTIVE", 409)
    said = as_string(require_field(body, "settlement_agreement_id"), "settlement_agreement_id")
    agreement = DB.settlement_agreements.get(said)
    if agreement is None:
        raise ApiError(ERR_NOT_FOUND, "SettlementAgreement not found", 404)
    dod = as_date(require_field(body, "date_of_death"), "date_of_death")
    ctype = as_enum(require_field(body, "claimant_type"), "claimant_type", {"BENEFICIARY", "ESTATE"})
    cname = as_string(require_field(body, "claimant_name"), "claimant_name")

    e = base_entity()
    e.update({
        "payee_id": pid,
        "settlement_agreement_id": said,
        "date_of_death": dod.isoformat(),
        "claimant_type": ctype,
        "claimant_name": cname,
        "denial_reason": None,
        "status": "REPORTED",
    })
    DB.death_claims[e["id"]] = e
    return success_object(claim_view(e), status=201)


@bp.route("/annuity/death-claims", methods=["GET"])
def list_claims():
    caller = get_caller()
    require_roles(caller, {"Any"})
    limit, offset = parse_pagination(request.args)
    items = list(DB.death_claims.values())
    f = request.args.get("payee_id")
    if f is not None:
        items = [c for c in items if c["payee_id"] == f]
    f = request.args.get("settlement_agreement_id")
    if f is not None:
        items = [c for c in items if c["settlement_agreement_id"] == f]
    f = request.args.get("status")
    if f is not None:
        items = [c for c in items if c["status"] == f]
    page, total = list_view(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/annuity/death-claims/<claimId>", methods=["GET"])
def get_claim(claimId):
    caller = get_caller()
    require_roles(caller, {"Any"})
    c = DB.death_claims.get(claimId)
    if c is None:
        raise ApiError(ERR_NOT_FOUND, "DeathClaim not found", 404)
    return success_object(claim_view(c))


@bp.route("/annuity/death-claims/<claimId>/settle", methods=["POST"])
def settle_claim(claimId):
    caller = get_caller()
    require_roles(caller, {"ComplianceOfficer"})
    c = DB.death_claims.get(claimId)
    if c is None:
        raise ApiError(ERR_NOT_FOUND, "DeathClaim not found", 404)
    if c["status"] != "REPORTED":
        raise ApiError(ERR_CLAIM_INVALID_STATE, "Claim not REPORTED", 409)
    get_json_body()
    c["status"] = "SETTLED"
    touch(c)

    payee = DB.payees.get(c["payee_id"])
    agreement = DB.settlement_agreements.get(c["settlement_agreement_id"])
    policy = policy_for_agreement(c["settlement_agreement_id"]) if agreement else None

    # 1a: payee ACTIVE -> DECEASED
    if payee is not None and payee["status"] == "ACTIVE":
        payee["status"] = "DECEASED"
        payee["deceased_date"] = c["date_of_death"]
        touch(payee)

    # 1b: ACTIVE guardianship -> TERMINATED
    for g in DB.guardianship_cases.values():
        if g["payee_id"] == c["payee_id"] and g["status"] == "ACTIVE":
            g["status"] = "TERMINATED"
            g["terminated_at_date"] = c["date_of_death"]
            touch(g)

    # 1c: change requests UNDER_REVIEW -> REJECTED
    for r in DB.payee_change_requests.values():
        if r["payee_id"] == c["payee_id"] and r["status"] == "UNDER_REVIEW":
            r["status"] = "REJECTED"
            touch(r)

    # 1d: transfer petitions {FILED, DISCLOSURE_SERVED, HEARING_SCHEDULED} -> WITHDRAWN
    for pet in DB.transfer_petitions.values():
        if pet["payee_id"] == c["payee_id"] and pet["status"] in ("FILED", "DISCLOSURE_SERVED", "HEARING_SCHEDULED"):
            pet["status"] = "WITHDRAWN"
            touch(pet)

    # 2: cancel SCHEDULED/PAYABLE payments for this payee with
    # due_date > certain_period_end_date (all when null)
    if agreement is not None:
        cpe = policy["certain_period_end_date"] if policy is not None else None
        sched = active_schedule_for(agreement["id"])
        if sched is not None:
            for p in DB.scheduled_payments.values():
                if p["payment_schedule_id"] != sched["id"]:
                    continue
                if p["payee_id"] != c["payee_id"]:
                    continue
                if p["status"] not in ("SCHEDULED", "PAYABLE"):
                    continue
                cancel = False
                if cpe is None:
                    cancel = True
                else:
                    if parse_date(p["due_date"]) > parse_date(cpe):
                        cancel = True
                if cancel:
                    p["status"] = "CANCELLED"
                    p["cancel_reason"] = "DEATH"
                    touch(p)
        recompute_agreement_totals(agreement)
        # 3/4: exhaustion cascade
        exhaustion_check(agreement)

    return success_object(claim_view(c))


@bp.route("/annuity/death-claims/<claimId>/deny", methods=["POST"])
def deny_claim(claimId):
    caller = get_caller()
    require_roles(caller, {"ComplianceOfficer"})
    c = DB.death_claims.get(claimId)
    if c is None:
        raise ApiError(ERR_NOT_FOUND, "DeathClaim not found", 404)
    if c["status"] != "REPORTED":
        raise ApiError(ERR_CLAIM_INVALID_STATE, "Claim not REPORTED", 409)
    body = get_json_body()
    check_unknown_fields(body, {"denial_reason"})
    reason = as_string(require_field(body, "denial_reason"), "denial_reason")
    c["status"] = "DENIED"
    c["denial_reason"] = reason
    touch(c)
    return success_object(claim_view(c))


@bp.route("/annuity/death-claims/<claimId>/resubmit", methods=["POST"])
def resubmit_claim(claimId):
    caller = get_caller()
    require_roles(caller, {"CaseManager"})
    c = DB.death_claims.get(claimId)
    if c is None:
        raise ApiError(ERR_NOT_FOUND, "DeathClaim not found", 404)
    if c["status"] != "DENIED":
        raise ApiError(ERR_CLAIM_INVALID_STATE, "Claim not DENIED", 409)
    get_json_body()
    c["status"] = "REPORTED"
    c["denial_reason"] = None
    touch(c)
    return success_object(claim_view(c))


# ---------------------------------------------------------------------------
# CommutationRequest
# ---------------------------------------------------------------------------

COMMUTATION_FIELDS = {
    "annuity_policy_id", "settlement_agreement_id", "reason",
    "expected_annuity_policy_version", "death_claim_id",
}


def commutation_view(c):
    return pub(c)


@bp.route("/annuity/commutation-requests", methods=["POST"])
def create_commutation():
    caller = get_caller()
    require_roles(caller, {"CaseManager"})
    body = get_json_body()
    polid = body.get("annuity_policy_id")
    said = body.get("settlement_agreement_id")
    dcid = body.get("death_claim_id")
    policy = None
    if polid is not None and isinstance(polid, str):
        policy = DB.annuity_policies.get(polid)
        if policy is None:
            raise ApiError(ERR_NOT_FOUND, "AnnuityPolicy not found", 404)
    agreement = None
    if said is not None and isinstance(said, str):
        agreement = DB.settlement_agreements.get(said)
        if agreement is None:
            raise ApiError(ERR_NOT_FOUND, "SettlementAgreement not found", 404)
    claim = None
    if dcid is not None and isinstance(dcid, str):
        claim = DB.death_claims.get(dcid)
        if claim is None:
            raise ApiError(ERR_NOT_FOUND, "DeathClaim not found", 404)

    # OCC (priority 3.5): after existence, before state/business
    expected = body.get("expected_annuity_policy_version")
    if policy is not None and expected is not None and isinstance(expected, int) and not isinstance(expected, bool):
        if expected != policy["version"]:
            raise ApiError(ERR_STALE_POLICY_VERSION, "expected_annuity_policy_version != policy.version", 412)

    # cross-entity state (priority 18): DEATH requires SETTLED claim for the same agreement
    reason_raw = body.get("reason")
    if reason_raw == "DEATH" and claim is not None:
        if claim["status"] != "SETTLED" or claim["settlement_agreement_id"] != said:
            raise ApiError(ERR_CLAIM_INVALID_STATE, "DEATH commutation requires a SETTLED claim for the same agreement", 409)

    # business: commutation legality (priority 6)
    if policy is not None and agreement is not None and isinstance(reason_raw, str) and reason_raw in ("DEATH", "HARDSHIP"):
        rider = policy["commutation_rider"]
        rider_ok = False
        if reason_raw == "DEATH" and rider in ("DEATH_ONLY", "DEATH_AND_HARDSHIP"):
            rider_ok = True
        if reason_raw == "HARDSHIP" and rider == "DEATH_AND_HARDSHIP":
            rider_ok = True
        payee = DB.payees.get(agreement["primary_payee_id"])
        profile = find_profile_by_state(payee["address_state_code"]) if payee else None
        statute_ok = profile is not None and profile["commutation_permitted"]
        if not rider_ok or not statute_ok:
            raise ApiError(ERR_COMMUTATION_NOT_PERMITTED, "Commutation not permitted by rider or statute", 403)

    # shape validation
    check_unknown_fields(body, COMMUTATION_FIELDS)
    polid = as_string(require_field(body, "annuity_policy_id"), "annuity_policy_id")
    policy = DB.annuity_policies.get(polid)
    if policy is None:
        raise ApiError(ERR_NOT_FOUND, "AnnuityPolicy not found", 404)
    said = as_string(require_field(body, "settlement_agreement_id"), "settlement_agreement_id")
    agreement = DB.settlement_agreements.get(said)
    if agreement is None:
        raise ApiError(ERR_NOT_FOUND, "SettlementAgreement not found", 404)
    reason = as_enum(require_field(body, "reason"), "reason", {"DEATH", "HARDSHIP"})
    expected = require_field(body, "expected_annuity_policy_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError(ERR_INVALID_REQUEST, "expected_annuity_policy_version must be an integer", 400)
    if expected != policy["version"]:
        raise ApiError(ERR_STALE_POLICY_VERSION, "expected_annuity_policy_version != policy.version", 412)
    if reason == "DEATH":
        dcid = require_field(body, "death_claim_id")
        dcid = as_string(dcid, "death_claim_id")
        claim = DB.death_claims.get(dcid)
        if claim is None:
            raise ApiError(ERR_NOT_FOUND, "DeathClaim not found", 404)
        if claim["status"] != "SETTLED" or claim["settlement_agreement_id"] != said:
            raise ApiError(ERR_CLAIM_INVALID_STATE, "DEATH commutation requires a SETTLED claim for the same agreement", 409)
    else:
        dcid = None

    # legality re-check with validated inputs
    rider = policy["commutation_rider"]
    rider_ok = (reason == "DEATH" and rider in ("DEATH_ONLY", "DEATH_AND_HARDSHIP")) or \
               (reason == "HARDSHIP" and rider == "DEATH_AND_HARDSHIP")
    payee = DB.payees.get(agreement["primary_payee_id"])
    profile = find_profile_by_state(payee["address_state_code"]) if payee else None
    statute_ok = profile is not None and profile["commutation_permitted"]
    if not rider_ok or not statute_ok:
        raise ApiError(ERR_COMMUTATION_NOT_PERMITTED, "Commutation not permitted by rider or statute", 403)

    # eligible set: ACTIVE schedule, {SCHEDULED, PAYABLE}, due_date strictly after clock date
    today = CLOCK.today()
    eligible = []
    sched = active_schedule_for(said)
    if sched is not None:
        for p in DB.scheduled_payments.values():
            if p["payment_schedule_id"] != sched["id"]:
                continue
            if p["status"] not in ("SCHEDULED", "PAYABLE"):
                continue
            if parse_date(p["due_date"]) > today:
                eligible.append(p)
    if len(eligible) == 0:
        raise ApiError(ERR_NO_COMMUTABLE_PAYMENTS, "Zero eligible payments", 409)
    eligible.sort(key=lambda p: (p["due_date"], p["payment_seq_no"], p["id"]))

    rate_bps = min(policy["contract_discount_rate_bps"], profile["sspa_max_discount_rate_bps"])
    pairs = [(p["amount_cents"], parse_date(p["due_date"])) for p in eligible]
    pv_total = pv_per_payment_then_sum(pairs, rate_bps, today)
    if reason == "HARDSHIP":
        fee = int((Decimal("0.03") * Decimal(pv_total)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        if fee > 25000:
            fee = 25000
    else:
        fee = 0
    commuted_value = pv_total - fee

    e = base_entity()
    e.update({
        "annuity_policy_id": polid,
        "settlement_agreement_id": said,
        "death_claim_id": dcid,
        "reason": reason,
        "covered_payment_count": len(eligible),
        "fee_cents": fee,
        "commuted_value_cents": commuted_value,
        "status": "REQUESTED",
        "_covered_payment_ids": [p["id"] for p in eligible],
    })
    DB.commutation_requests[e["id"]] = e
    # creation advances policy version (OCC anchor)
    touch(policy)
    return success_object(commutation_view(e), status=201)


@bp.route("/annuity/commutation-requests", methods=["GET"])
def list_commutations():
    caller = get_caller()
    require_roles(caller, {"Any"})
    limit, offset = parse_pagination(request.args)
    items = list(DB.commutation_requests.values())
    f = request.args.get("annuity_policy_id")
    if f is not None:
        items = [c for c in items if c["annuity_policy_id"] == f]
    f = request.args.get("settlement_agreement_id")
    if f is not None:
        items = [c for c in items if c["settlement_agreement_id"] == f]
    f = request.args.get("death_claim_id")
    if f is not None:
        items = [c for c in items if c.get("death_claim_id") == f]
    f = request.args.get("status")
    if f is not None:
        items = [c for c in items if c["status"] == f]
    page, total = list_view(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/annuity/commutation-requests/<commutationId>", methods=["GET"])
def get_commutation(commutationId):
    caller = get_caller()
    require_roles(caller, {"Any"})
    c = DB.commutation_requests.get(commutationId)
    if c is None:
        raise ApiError(ERR_NOT_FOUND, "CommutationRequest not found", 404)
    return success_object(commutation_view(c))


@bp.route("/annuity/commutation-requests/<commutationId>/approve", methods=["POST"])
def approve_commutation(commutationId):
    caller = get_caller()
    require_roles(caller, {"ComplianceOfficer"})
    c = DB.commutation_requests.get(commutationId)
    if c is None:
        raise ApiError(ERR_NOT_FOUND, "CommutationRequest not found", 404)
    if c["status"] != "REQUESTED":
        raise ApiError(ERR_COMMUTATION_INVALID_STATE, "Commutation not REQUESTED", 409)
    get_json_body()
    c["status"] = "APPROVED"
    touch(c)
    return success_object(commutation_view(c))


@bp.route("/annuity/commutation-requests/<commutationId>/deny", methods=["POST"])
def deny_commutation(commutationId):
    caller = get_caller()
    require_roles(caller, {"ComplianceOfficer"})
    c = DB.commutation_requests.get(commutationId)
    if c is None:
        raise ApiError(ERR_NOT_FOUND, "CommutationRequest not found", 404)
    if c["status"] != "REQUESTED":
        raise ApiError(ERR_COMMUTATION_INVALID_STATE, "Commutation not REQUESTED", 409)
    get_json_body()
    c["status"] = "DENIED"
    touch(c)
    return success_object(commutation_view(c))


@bp.route("/annuity/commutation-requests/<commutationId>/pay-out", methods=["POST"])
def pay_out_commutation(commutationId):
    caller = get_caller()
    require_roles(caller, {"OperationsSpecialist"})
    c = DB.commutation_requests.get(commutationId)
    if c is None:
        raise ApiError(ERR_NOT_FOUND, "CommutationRequest not found", 404)
    if c["status"] != "APPROVED":
        raise ApiError(ERR_COMMUTATION_INVALID_STATE, "Commutation not APPROVED", 409)
    get_json_body()

    agreement = DB.settlement_agreements.get(c["settlement_agreement_id"])
    policy = DB.annuity_policies.get(c["annuity_policy_id"])
    covered_ids = list(c.get("_covered_payment_ids", []))
    for pid in covered_ids:
        p = DB.scheduled_payments.get(pid)
        if p is None:
            continue
        if p["status"] in ("SCHEDULED", "PAYABLE"):
            p["status"] = "COMMUTED"
            p["commuted_by_request_id"] = c["id"]
            touch(p)
            if agreement is not None:
                agreement["commuted_nominal_total_cents"] += p["amount_cents"]
    if agreement is not None:
        recompute_agreement_totals(agreement)
    c["status"] = "PAID_OUT"
    touch(c)

    # policy follows the remainder
    if policy is not None and policy["status"] in ("IN_FORCE", "PARTIALLY_COMMUTED"):
        remaining = 0
        sched = active_schedule_for(c["settlement_agreement_id"])
        if sched is not None:
            for p in DB.scheduled_payments.values():
                if p["payment_schedule_id"] == sched["id"] and p["status"] in (
                    "SCHEDULED", "PAYABLE", "ISSUED", "RETURNED", "STALE_DATED", "ESCHEATABLE",
                ):
                    remaining += 1
        if remaining == 0:
            policy["status"] = "FULLY_COMMUTED"
            touch(policy)
            if agreement is not None and agreement["status"] == "ACTIVE":
                agreement["status"] = "COMMUTED"
                touch(agreement)
        else:
            policy["status"] = "PARTIALLY_COMMUTED"
            touch(policy)

    # schedule with no non-terminal payments becomes TERMINATED
    sched = active_schedule_for(c["settlement_agreement_id"])
    if sched is not None:
        remaining_on_sched = 0
        for p in DB.scheduled_payments.values():
            if p["payment_schedule_id"] == sched["id"] and p["status"] in (
                "SCHEDULED", "PAYABLE", "ISSUED", "RETURNED", "STALE_DATED", "ESCHEATABLE",
            ):
                remaining_on_sched += 1
        if remaining_on_sched == 0:
            sched["status"] = "TERMINATED"
            touch(sched)

    return success_object(commutation_view(c))


# ---------------------------------------------------------------------------
# EscheatmentBatch
# ---------------------------------------------------------------------------

BATCH_FIELDS = {"state_code", "batch_period"}


def batch_view(b):
    return pub(b)


@bp.route("/annuity/escheatment-batches", methods=["POST"])
def create_batch():
    caller = get_caller()
    require_roles(caller, {"ComplianceOfficer"})
    body = get_json_body()
    sc = body.get("state_code")
    # uniqueness: at most one OPEN batch per state_code (priority 15)
    if sc is not None and isinstance(sc, str):
        for b in DB.escheatment_batches.values():
            if b["state_code"] == sc and b["status"] == "OPEN":
                raise ApiError(ERR_OPEN_BATCH_EXISTS, "An OPEN escheatment batch already exists for this state_code", 409)
    check_unknown_fields(body, BATCH_FIELDS)
    sc = as_string(require_field(body, "state_code"), "state_code")
    bp_ = as_year_month(require_field(body, "batch_period"), "batch_period")

    e = base_entity()
    e.update({
        "state_code": sc,
        "batch_period": bp_,
        "opened_by_user_id": caller.user_id,
        "swept_count": 0,
        "swept_amount_cents": 0,
        "reclaimed_count": 0,
        "reclaimed_amount_cents": 0,
        "status": "OPEN",
    })
    DB.escheatment_batches[e["id"]] = e
    return success_object(batch_view(e), status=201)


@bp.route("/annuity/escheatment-batches", methods=["GET"])
def list_batches():
    caller = get_caller()
    require_roles(caller, {"Any"})
    limit, offset = parse_pagination(request.args)
    items = list(DB.escheatment_batches.values())
    f = request.args.get("state_code")
    if f is not None:
        items = [b for b in items if b["state_code"] == f]
    f = request.args.get("status")
    if f is not None:
        items = [b for b in items if b["status"] == f]
    page, total = list_view(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/annuity/escheatment-batches/<batchId>", methods=["GET"])
def get_batch(batchId):
    caller = get_caller()
    require_roles(caller, {"Any"})
    b = DB.escheatment_batches.get(batchId)
    if b is None:
        raise ApiError(ERR_NOT_FOUND, "EscheatmentBatch not found", 404)
    return success_object(batch_view(b))


@bp.route("/annuity/escheatment-batches/<batchId>/finalize", methods=["POST"])
def finalize_batch(batchId):
    caller = get_caller()
    require_roles(caller, {"ComplianceOfficer"})
    b = DB.escheatment_batches.get(batchId)
    if b is None:
        raise ApiError(ERR_NOT_FOUND, "EscheatmentBatch not found", 404)
    if b["status"] != "OPEN":
        raise ApiError(ERR_BATCH_INVALID_STATE, "Batch not OPEN", 409)
    if caller.user_id == b["opened_by_user_id"]:
        raise ApiError(ERR_SOD_VIOLATION, "Finalizer must differ from batch opener", 403)
    get_json_body()

    # sweep: every ESCHEATABLE payment whose payee address_state_code == batch.state_code
    swept = []
    for p in DB.scheduled_payments.values():
        if p["status"] != "ESCHEATABLE":
            continue
        payee = DB.payees.get(p["payee_id"])
        if payee is None or payee["address_state_code"] != b["state_code"]:
            continue
        swept.append(p)
    swept.sort(key=lambda p: (p["created_at"], p["_seq"]))

    swept_count = 0
    swept_amount = 0
    agreements_touched = {}
    for p in swept:
        p["status"] = "ESCHEATED"
        p["escheated_in_batch_id"] = b["id"]
        touch(p)
        swept_count += 1
        swept_amount += p["amount_cents"]
        # close the payment's OPEN/ESCHEAT_PENDING returned cases
        for c in DB.returned_payment_cases.values():
            if c["scheduled_payment_id"] == p["id"] and c["status"] in ("OPEN", "ESCHEAT_PENDING"):
                c["status"] = "CLOSED_ESCHEATED"
                c["resolution_note"] = "ESCHEATED"
                touch(c)
        sched = DB.payment_schedules.get(p["payment_schedule_id"])
        if sched is not None:
            agreement = DB.settlement_agreements.get(sched["settlement_agreement_id"])
            if agreement is not None:
                agreement["escheated_total_cents"] += p["amount_cents"]
                agreements_touched[agreement["id"]] = agreement
    b["swept_count"] = swept_count
    b["swept_amount_cents"] = swept_amount
    b["status"] = "FINALIZED"
    touch(b)
    for agreement in agreements_touched.values():
        recompute_agreement_totals(agreement)
        exhaustion_check(agreement)
    return success_object(batch_view(b))
