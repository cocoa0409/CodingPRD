"""Estimate endpoints: create (OCC + supersede), get/list, price, present,
accept, finalize (PRD 3.4, 3.5, 3.9)."""

from flask import Blueprint, request

from db import db
from errors import (
    ApiError,
    ERR_ESTIMATE_LOCKED,
    ERR_GFE_DEADLINE_MISSED,
    ERR_INVALID_REQUEST,
    ERR_SNAPSHOT_PATIENT_MISMATCH,
    ERR_STALE_VERSION,
    ERR_UNKNOWN_CPT_CODE,
    invalid_state,
    not_found,
)
from middleware import ALL_ROLES, authenticate
from response import ok_list, ok_object
from services import (
    active_estimate,
    case_estimates,
    compute_gfe_timeline,
    create_escalation,
    finalize_deposit_application,
    finalize_variance,
    price_estimate,
    recompute_case,
    regress_case_if_cleared,
    sync_case,
)
from util import (
    base_record,
    get_body,
    now_dt,
    now_iso,
    paginate,
    parse_datetime_value,
    req_int,
    req_str,
    serialize,
    today,
    touch,
)

bp = Blueprint("estimates", __name__)


def get_estimate_or_404(eid):
    est = db.estimates.get(eid)
    if est is None:
        raise not_found("estimate not found")
    return est


def get_case_or_404(cid):
    case = db.cases.get(cid)
    if case is None:
        raise not_found("case not found")
    return case


# --- create -----------------------------------------------------------------

@bp.post("/clearance/cases/<cid>/estimates")
def create_estimate(cid):
    authenticate(["FinancialCounselor"])
    case = get_case_or_404(cid)
    b = get_body()
    expected_case_version = req_int(b, "expected_case_version")
    pricing_mode = b.get("pricing_mode")
    if pricing_mode not in ("INSURED", "UNINSURED_GFE"):
        raise ApiError(ERR_INVALID_REQUEST, "pricing_mode must be INSURED or UNINSURED_GFE", 400)
    lines = b.get("lines")
    if not isinstance(lines, list) or len(lines) == 0:
        raise ApiError(ERR_INVALID_REQUEST, "lines must be a non-empty array", 400)
    for line in lines:
        if not isinstance(line, dict):
            raise ApiError(ERR_INVALID_REQUEST, "each line must be an object", 400)
        if not isinstance(line.get("cpt_code"), str):
            raise ApiError(ERR_INVALID_REQUEST, "each line requires a cpt_code string", 400)
        q = line.get("quantity")
        if not isinstance(q, int) or isinstance(q, bool) or q < 1:
            raise ApiError(ERR_INVALID_REQUEST, "each line quantity must be an integer >= 1", 400)
    snapshot_id = b.get("eligibility_snapshot_id")
    if snapshot_id is not None and not isinstance(snapshot_id, str):
        raise ApiError(ERR_INVALID_REQUEST, "eligibility_snapshot_id must be a string", 400)
    if pricing_mode == "INSURED" and snapshot_id is None:
        raise ApiError(ERR_INVALID_REQUEST, "eligibility_snapshot_id is required for INSURED estimates", 400)
    if pricing_mode == "UNINSURED_GFE" and snapshot_id is not None:
        raise ApiError(ERR_INVALID_REQUEST, "eligibility_snapshot_id is forbidden for UNINSURED_GFE estimates", 400)
    # OCC on Case.version (priority 5 — precedes all business rules)
    if expected_case_version != case["version"]:
        raise ApiError(ERR_STALE_VERSION, "expected_case_version does not match current case version", 412)
    # business rules in PRD 2.8 order: CPT existence -> snapshot-patient -> lock
    for line in lines:
        if line["cpt_code"] not in db.cpt_index:
            raise ApiError(ERR_UNKNOWN_CPT_CODE, "unknown cpt_code: %s" % line["cpt_code"], 422)
    if pricing_mode == "INSURED":
        snap = db.snapshots.get(snapshot_id)
        if snap is None or snap["patient_id"] != case["patient_id"]:
            raise ApiError(ERR_SNAPSHOT_PATIENT_MISMATCH,
                           "eligibility snapshot belongs to a different patient", 422)
    if any(e["status"] in ("ACCEPTED", "FINALIZED") for e in case_estimates(cid)):
        raise ApiError(ERR_ESTIMATE_LOCKED, "the case has an ACCEPTED or FINALIZED estimate", 409)

    # supersede the prior non-locked estimate(s): DRAFT/PRICED/PRESENTED
    siblings = case_estimates(cid)
    for prev in siblings:
        if prev["status"] in ("DRAFT", "PRICED", "PRESENTED"):
            prev["status"] = "SUPERSEDED"
            touch(prev)
    revision = (max((e["revision"] for e in siblings), default=0)) + 1

    rec = base_record()
    rec.update({
        "case_id": cid,
        "eligibility_snapshot_id": snapshot_id,
        "pricing_mode": pricing_mode,
        "revision": revision,
        "lines": [{"cpt_code": l["cpt_code"], "quantity": l["quantity"]} for l in lines],
        "status": "DRAFT",
        "allowed_amount_cents": 0,
        "deductible_applied_cents": 0,
        "coinsurance_cents": 0,
        "patient_responsibility_cents": 0,
        "insurance_pays_cents": 0,
        "gfe_total_cents": 0,
        "gfe_required": False,
        "gfe_delivery_deadline": None,
        "presented_at": None,
        "accepted_at": None,
        "first_presented_patient_resp_cents": None,
        "finalized_actual_billed_cents": None,
        "high_dollar_flag": False,
        "dispute_eligible": False,
    })
    if pricing_mode == "UNINSURED_GFE":
        gfe_required, deadline = compute_gfe_timeline(today(), case["service_date"])
        rec["gfe_required"] = gfe_required
        rec["gfe_delivery_deadline"] = deadline
    db.estimates[rec["id"]] = rec
    # estimate creation increments the case version by exactly 1
    recompute_case(case)
    touch(case)
    return ok_object(serialize(rec), 201)


# --- retrieval ---------------------------------------------------------------

@bp.get("/clearance/estimates/<eid>")
def get_estimate(eid):
    authenticate(ALL_ROLES)
    return ok_object(serialize(get_estimate_or_404(eid)))


@bp.get("/clearance/cases/<cid>/estimates")
def list_case_estimates(cid):
    authenticate(ALL_ROLES)
    get_case_or_404(cid)
    page, meta = paginate(case_estimates(cid))
    return ok_list([serialize(e) for e in page], meta)


@bp.get("/clearance/estimates")
def list_estimates():
    authenticate(ALL_ROLES)
    items = list(db.estimates.values())
    case_id = request.args.get("case_id")
    snapshot_id = request.args.get("eligibility_snapshot_id")
    status = request.args.get("status")
    if case_id is not None:
        items = [e for e in items if e["case_id"] == case_id]
    if snapshot_id is not None:
        items = [e for e in items if e["eligibility_snapshot_id"] == snapshot_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    page, meta = paginate(items)
    return ok_list([serialize(e) for e in page], meta)


# --- transitions --------------------------------------------------------------

@bp.post("/clearance/estimates/<eid>/price")
def price(eid):
    authenticate(["FinancialCounselor"])
    est = get_estimate_or_404(eid)
    if est["status"] != "DRAFT":
        raise invalid_state("only a DRAFT estimate can be priced")
    price_estimate(est)
    est["status"] = "PRICED"
    touch(est)
    case = db.cases[est["case_id"]]
    changed = recompute_case(case)
    if regress_case_if_cleared(case):
        changed = True
    if changed:
        touch(case)
    return ok_object(serialize(est))


@bp.post("/clearance/estimates/<eid>/present")
def present(eid):
    authenticate(["FinancialCounselor"])
    est = get_estimate_or_404(eid)
    if est["status"] != "PRICED":
        raise invalid_state("only a PRICED estimate can be presented")
    # GFE delivery deadline (only when the estimate is in the right state)
    if est["pricing_mode"] == "UNINSURED_GFE" and est["gfe_required"]:
        deadline = parse_datetime_value(est["gfe_delivery_deadline"])
        if now_dt() > deadline:
            raise ApiError(ERR_GFE_DEADLINE_MISSED,
                           "good-faith estimate delivery deadline has passed", 409)
    case = db.cases[est["case_id"]]
    est["status"] = "PRESENTED"
    est["presented_at"] = now_iso()
    # first-presented pin: written once per case, never overwritten
    if case["_first_presented_pin"] is None:
        case["_first_presented_pin"] = est["patient_responsibility_cents"]
    est["first_presented_patient_resp_cents"] = case["_first_presented_pin"]
    touch(est)
    return ok_object(serialize(est))


@bp.post("/clearance/estimates/<eid>/accept")
def accept(eid):
    authenticate(["FinancialCounselor"])
    est = get_estimate_or_404(eid)
    if est["status"] != "PRESENTED":
        raise invalid_state("only a PRESENTED estimate can be accepted")
    case = db.cases[est["case_id"]]
    est["status"] = "ACCEPTED"
    est["accepted_at"] = now_iso()
    touch(est)
    if case["status"] == "OPEN":
        case["status"] = "IN_REVIEW"
    recompute_case(case)
    touch(case)
    return ok_object(serialize(est))


@bp.post("/clearance/estimates/<eid>/finalize")
def finalize(eid):
    authenticate(["FinancialCounselor", "ClearanceSupervisor"])
    est = get_estimate_or_404(eid)
    b = get_body()
    actual_billed_cents = req_int(b, "actual_billed_cents")
    if actual_billed_cents <= 0:
        raise ApiError(ERR_INVALID_REQUEST, "actual_billed_cents must be > 0", 400)
    if est["status"] != "ACCEPTED":
        raise invalid_state("only an ACCEPTED estimate can be finalized")
    case = db.cases[est["case_id"]]

    est["status"] = "FINALIZED"
    est["finalized_actual_billed_cents"] = actual_billed_cents
    # dispute eligibility: GFE only, overage >= $400.00 (inclusive)
    if est["pricing_mode"] == "UNINSURED_GFE":
        est["dispute_eligible"] = (
            actual_billed_cents - est["gfe_total_cents"] >= 40000
        )
    else:
        est["dispute_eligible"] = False
    touch(est)

    # cascade link 1: variance record (both baselines)
    vr = finalize_variance(est, actual_billed_cents)

    # cascade link 2: GFE dispute escalation
    if est["dispute_eligible"]:
        create_escalation(
            case,
            reason="GFE_DISPUTE",
            estimate_id=est["id"],
            trigger_amount_cents=vr["variance_vs_accepted_cents"],
            opened_by="system",
        )

    # deposit application cascade
    finalize_deposit_application(case, actual_billed_cents)

    # case recompute + cascade link 3 regression
    recompute_case(case)
    regress_case_if_cleared(case)
    touch(case)
    return ok_object(serialize(est))
