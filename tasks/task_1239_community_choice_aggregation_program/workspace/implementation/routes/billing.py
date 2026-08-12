"""BillingExtract and BillingLine endpoints (PRD §3.6)."""

from flask import Blueprint, request

from auth import require_roles
from envelope import ok_object, paginate
from errors import (ApiError, ERR_ALREADY_TERMINAL, ERR_AUTHORITY_POSTURE,
                    ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_NO_DEFAULT_PRODUCT, ERR_REFERENCED_NOT_FOUND,
                    ERR_REFERENTIAL_STATE)
from serializers import ser_extract, ser_line
from services import (adopted_product_for_election, covering_adopted_schedule,
                      get_or_404)
from store import STORE
from util import (as_int, check_month, dec, get_body, month_start,
                  round_half_up_int)

bp = Blueprint("billing", __name__)

BC_FC_UL = ("BillingCoordinator", "FinanceController", "UtilityLiaison")


def _present(body, field):
    if field not in body or body[field] is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Missing required field '{field}'")
    return body[field]


@bp.post("/cca/billing-extracts")
@require_roles("BillingCoordinator")
def create_extract():
    body = get_body(request)
    month = check_month(_present(body, "billing_month"), "billing_month")
    rec = STORE.new_record()
    rec.update({
        "billing_month": month,
        "status": "DRAFT",
        "submitted_on": None,
        "line_count": 0,
        "total_billed_cents": 0,
        "total_pcia_collected_cents": 0,
    })
    STORE.extracts[rec["id"]] = rec
    return ok_object(ser_extract(rec), status=201)


@bp.get("/cca/billing-extracts")
@require_roles(*BC_FC_UL)
def list_extracts():
    items = list(STORE.extracts.values())
    st = request.args.get("status")
    if st is not None:
        items = [e for e in items if e["status"] == st]
    bm = request.args.get("billing_month")
    if bm is not None:
        items = [e for e in items if e["billing_month"] == bm]
    items.sort(key=lambda e: (e["_created_dt"], e["_seq"]))
    return paginate(items, ser_extract)


@bp.get("/cca/billing-extracts/<eid>")
@require_roles(*BC_FC_UL)
def get_extract(eid):
    return ok_object(ser_extract(get_or_404(STORE.extracts, eid, "BillingExtract")))


@bp.post("/cca/billing-extracts/<eid>/lines")
@require_roles("BillingCoordinator")
def post_line(eid):
    extract = get_or_404(STORE.extracts, eid, "BillingExtract")
    body = get_body(request)
    acct_id = body.get("service_account_id")
    if acct_id is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Missing required field 'service_account_id'")
    acct = STORE.accounts.get(acct_id)
    if acct is None:
        raise ApiError(ERR_REFERENCED_NOT_FOUND, 404, f"ServiceAccount '{acct_id}' not found")
    if extract["status"] == "SETTLED":
        raise ApiError(ERR_ALREADY_TERMINAL, 409,
                       "BillingExtract is SETTLED (terminal); no lines may be posted")
    if extract["status"] != "DRAFT":
        raise ApiError(ERR_AUTHORITY_POSTURE, 409,
                       "Lines may only be posted into a DRAFT extract")
    # Default-product prerequisite (priority 8) before referential state (priority 12).
    svc_month_start = month_start(extract["billing_month"])
    if acct["product_election"] == "DEFAULT":
        prod = adopted_product_for_election("DEFAULT")
        if prod is None or covering_adopted_schedule(prod["id"], svc_month_start) is None:
            raise ApiError(ERR_NO_DEFAULT_PRODUCT, 422,
                           "No ADOPTED default product with a covering ADOPTED rate schedule "
                           "exists for the billed month")
        schedule = covering_adopted_schedule(prod["id"], svc_month_start)
    else:
        prod = adopted_product_for_election(acct["product_election"])
        if prod is None:
            raise ApiError(ERR_REFERENTIAL_STATE, 422,
                           f"No ADOPTED product exists for election {acct['product_election']}")
        schedule = covering_adopted_schedule(prod["id"], svc_month_start)
        if schedule is None:
            raise ApiError(ERR_REFERENTIAL_STATE, 422,
                           "No ADOPTED rate schedule covers the billed month for the "
                           "account's product")
    if acct["enrollment_state"] != "ENROLLED":
        raise ApiError(ERR_REFERENTIAL_STATE, 422,
                       f"Account in enrollment_state {acct['enrollment_state']} cannot be billed")
    usage = as_int(_present(body, "usage_kwh"), "usage_kwh")
    if usage <= 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "usage_kwh must be > 0")
    gen = round_half_up_int(dec(usage) * dec(schedule["energy_rate_cents_per_kwh"]))
    pcia = round_half_up_int(dec(usage) * dec(schedule["pcia_rate_cents_per_kwh"]))
    rec = STORE.new_record(with_version=False)
    rec.update({
        "billing_extract_id": extract["id"],
        "service_account_id": acct["id"],
        "usage_kwh": usage,
        "generation_charge_cents": gen,
        "pcia_charge_cents": pcia,
        "product_election_at_billing": acct["product_election"],
    })
    STORE.lines[rec["id"]] = rec
    extract["line_count"] += 1
    extract["total_billed_cents"] += gen
    extract["total_pcia_collected_cents"] += pcia
    STORE.touch(extract)
    return ok_object(ser_line(rec), status=201)


@bp.get("/cca/billing-extracts/<eid>/lines")
@require_roles(*BC_FC_UL)
def list_extract_lines(eid):
    extract = get_or_404(STORE.extracts, eid, "BillingExtract")
    items = [l for l in STORE.lines.values() if l["billing_extract_id"] == extract["id"]]
    items.sort(key=lambda l: (l["_created_dt"], l["_seq"]))
    return paginate(items, ser_line)


@bp.get("/cca/billing-lines")
@require_roles("BillingCoordinator", "FinanceController", "CustomerService")
def list_lines():
    items = list(STORE.lines.values())
    aid = request.args.get("service_account_id")
    if aid is not None:
        items = [l for l in items if l["service_account_id"] == aid]
    eid = request.args.get("billing_extract_id")
    if eid is not None:
        items = [l for l in items if l["billing_extract_id"] == eid]
    items.sort(key=lambda l: (l["_created_dt"], l["_seq"]))
    return paginate(items, ser_line)


@bp.get("/cca/billing-lines/<lid>")
@require_roles("BillingCoordinator", "FinanceController", "CustomerService")
def get_line(lid):
    return ok_object(ser_line(get_or_404(STORE.lines, lid, "BillingLine")))


@bp.post("/cca/billing-extracts/<eid>/submit")
@require_roles("BillingCoordinator")
def submit_extract(eid):
    extract = get_or_404(STORE.extracts, eid, "BillingExtract")
    if extract["status"] == "SETTLED":
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "BillingExtract is SETTLED (terminal)")
    if extract["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"BillingExtract in status {extract['status']} cannot be submitted")
    auth = STORE.authority()
    if auth is None or auth["status"] != "ACTIVE":
        raise ApiError(ERR_AUTHORITY_POSTURE, 409,
                       "Authority must be ACTIVE to submit a billing extract")
    if extract["line_count"] <= 0:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "A billing extract requires at least one line to be submitted")
    extract["submitted_on"] = STORE.now_iso()
    extract["status"] = "SUBMITTED"
    STORE.touch(extract)
    return ok_object(ser_extract(extract))


@bp.post("/cca/billing-extracts/<eid>/utility-accept")
@require_roles("UtilityLiaison")
def utility_accept(eid):
    extract = get_or_404(STORE.extracts, eid, "BillingExtract")
    if extract["status"] == "SETTLED":
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "BillingExtract is SETTLED (terminal)")
    if extract["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"BillingExtract in status {extract['status']} cannot be accepted")
    # Cascade: each line's generation charge lands on its account ledger.
    for line in STORE.lines.values():
        if line["billing_extract_id"] != extract["id"]:
            continue
        acct = STORE.accounts.get(line["service_account_id"])
        if acct is not None:
            acct["cumulative_billed_cents"] += line["generation_charge_cents"]
            STORE.touch(acct)
    extract["status"] = "ACCEPTED"
    STORE.touch(extract)
    return ok_object(ser_extract(extract))


@bp.post("/cca/billing-extracts/<eid>/utility-reject")
@require_roles("UtilityLiaison")
def utility_reject(eid):
    extract = get_or_404(STORE.extracts, eid, "BillingExtract")
    if extract["status"] == "SETTLED":
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "BillingExtract is SETTLED (terminal)")
    if extract["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"BillingExtract in status {extract['status']} cannot be rejected")
    extract["status"] = "REJECTED_BY_UTILITY"
    STORE.touch(extract)
    return ok_object(ser_extract(extract))


@bp.post("/cca/billing-extracts/<eid>/reopen")
@require_roles("BillingCoordinator")
def reopen_extract(eid):
    extract = get_or_404(STORE.extracts, eid, "BillingExtract")
    if extract["status"] == "SETTLED":
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "BillingExtract is SETTLED (terminal)")
    if extract["status"] != "REJECTED_BY_UTILITY":
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"BillingExtract in status {extract['status']} cannot be reopened")
    extract["status"] = "DRAFT"
    STORE.touch(extract)
    return ok_object(ser_extract(extract))
