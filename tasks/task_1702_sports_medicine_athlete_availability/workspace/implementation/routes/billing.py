"""Insurance policies and claims lifecycle."""
from flask import Blueprint, request

from db import STORE, new_id, now_stamp, touch, logical_now_iso
from errors import (bad_request, not_found, conflict, unprocessable, ApiError,
                    ERR_STALE_VERSION, ERR_DUPLICATE_POLICY_NUMBER,
                    ERR_POLICY_NOT_ACTIVE, ERR_POLICY_CLAIMS_IN_FLIGHT,
                    ERR_CLAIM_NOT_DRAFT, ERR_CLAIM_NOT_SUBMITTABLE_STATE,
                    ERR_CLAIM_NOT_DENIED, ERR_CLAIM_NOT_VOIDABLE,
                    ERR_MAX_APPEALS_REACHED,
                    ERR_SERVICE_DATE_OUT_OF_POLICY_YEAR,
                    ERR_LINE_ITEM_SUM_MISMATCH, ERR_INVALID_SUPERSEDE_TARGET)
from middleware import require_roles
from response import ok_obj, ok_list
from routes.serializers import (insurance_policy_json, claim_json,
                                sorted_items)
from services.billing import adjudicate_claim
from util import (body, present, require_str, require_int, require_date,
                  parse_date_value)

bp = Blueprint("billing", __name__)

READERS = ("BillingStaff", "TeamAdmin")
MAX_APPEALS = 3


def _get_policy(pid):
    p = STORE["insurance_policies"].get(pid)
    if p is None:
        raise not_found("InsurancePolicy not found")
    return p


def _get_claim(cid):
    c = STORE["claims"].get(cid)
    if c is None:
        raise not_found("Claim not found")
    return c


# ---------------- Insurance policies ----------------

@bp.route("/insurance-policies", methods=["POST"])
def create_policy():
    require_roles("BillingStaff")
    j = body()
    # existence (3)
    athlete = None
    if present(j, "athlete_id"):
        athlete = STORE["athletes"].get(j["athlete_id"])
        if athlete is None:
            raise not_found("Athlete not found: athlete_id")
    if athlete is None:
        require_str(j, "athlete_id")
    # field constraints (10)
    payer_name = require_str(j, "payer_name")
    policy_number = require_str(j, "policy_number")
    deductible = require_int(j, "deductible_cents", 0, None)
    coinsurance = require_int(j, "coinsurance_pct", 0, 100)
    oop_max = require_int(j, "oop_max_cents", 0, None)
    ys_raw, ys = require_date(j, "policy_year_start")
    ye_raw, ye = require_date(j, "policy_year_end")
    if ye <= ys:
        raise bad_request("policy_year_end must be later than policy_year_start")
    if oop_max < deductible:
        raise bad_request("oop_max_cents must be >= deductible_cents")
    # uniqueness (17): (athlete_id, policy_number) among non-CANCELLED
    for p in STORE["insurance_policies"].values():
        if (p["athlete_id"] == athlete["id"]
                and p["policy_number"] == policy_number
                and p["status"] != "CANCELLED"):
            raise conflict(ERR_DUPLICATE_POLICY_NUMBER,
                           "Duplicate policy_number for athlete")
    ts = now_stamp()
    policy = {
        "id": new_id(), "athlete_id": athlete["id"],
        "payer_name": payer_name, "policy_number": policy_number,
        "deductible_cents": deductible, "deductible_met_cents": 0,
        "coinsurance_pct": coinsurance,
        "oop_max_cents": oop_max, "oop_accrued_cents": 0,
        "policy_year_start": ys_raw, "_policy_year_start": ys,
        "policy_year_end": ye_raw, "_policy_year_end": ye,
        "status": "ACTIVE",
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    STORE["insurance_policies"][policy["id"]] = policy
    return ok_obj(insurance_policy_json(policy), 201)


@bp.route("/insurance-policies", methods=["GET"])
def list_policies():
    require_roles(*READERS)
    items = sorted_items(STORE["insurance_policies"])
    athlete_id = request.args.get("athlete_id")
    status = request.args.get("status")
    if athlete_id is not None:
        items = [p for p in items if p["athlete_id"] == athlete_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return ok_list([insurance_policy_json(p) for p in items])


@bp.route("/insurance-policies/<policyId>", methods=["GET"])
def get_policy(policyId):
    require_roles(*READERS)
    return ok_obj(insurance_policy_json(_get_policy(policyId)))


@bp.route("/insurance-policies/<policyId>/cancel", methods=["POST"])
def cancel_policy(policyId):
    require_roles("BillingStaff")
    policy = _get_policy(policyId)
    if policy["status"] != "ACTIVE":
        raise conflict(ERR_POLICY_NOT_ACTIVE, "cancel requires policy ACTIVE")
    in_flight = any(c["insurance_policy_id"] == policy["id"]
                    and c["status"] in ("SUBMITTED", "APPEALED")
                    for c in STORE["claims"].values())
    if in_flight:
        raise conflict(ERR_POLICY_CLAIMS_IN_FLIGHT,
                       "Policy has claims in SUBMITTED/APPEALED")
    policy["status"] = "CANCELLED"
    touch(policy)
    return ok_obj(insurance_policy_json(policy))


# ---------------- Claims ----------------

def _validate_line_items(items):
    if not isinstance(items, list) or not (1 <= len(items) <= 50):
        raise bad_request("line_items must contain 1..50 items")
    out = []
    for li in items:
        if not isinstance(li, dict):
            raise bad_request("line_items entries must be objects")
        cpt = li.get("cpt_code")
        if not isinstance(cpt, str) or cpt == "":
            raise bad_request("line_items[].cpt_code required")
        charge = li.get("charge_cents")
        if not isinstance(charge, int) or isinstance(charge, bool) or charge <= 0:
            raise bad_request("line_items[].charge_cents must be > 0")
        sd_raw = li.get("service_date")
        sd = parse_date_value(sd_raw)
        if sd is None:
            raise bad_request("line_items[].service_date invalid")
        out.append({"cpt_code": cpt, "charge_cents": charge,
                    "service_date": sd_raw, "_sd": sd})
    return out


@bp.route("/claims", methods=["POST"])
def create_claim():
    require_roles("BillingStaff")
    j = body()
    # existence (3) incl. same-athlete cross-reference
    case = None
    if present(j, "injury_case_id"):
        case = STORE["injury_cases"].get(j["injury_case_id"])
        if case is None:
            raise not_found("InjuryCase not found: injury_case_id")
    policy = None
    if present(j, "insurance_policy_id"):
        policy = STORE["insurance_policies"].get(j["insurance_policy_id"])
        if policy is None:
            raise not_found("InsurancePolicy not found: insurance_policy_id")
    if case is not None and policy is not None \
            and policy["athlete_id"] != case["athlete_id"]:
        raise not_found("InsurancePolicy does not belong to the case athlete")
    if case is None:
        require_str(j, "injury_case_id")
    if policy is None:
        require_str(j, "insurance_policy_id")
    # field constraints (10)
    billed = require_int(j, "billed_amount_cents", 1, None)
    line_items = _validate_line_items(j.get("line_items"))
    # supersede target validity (13)
    supersedes_id = j.get("supersedes_claim_id")
    if supersedes_id is not None:
        target = STORE["claims"].get(supersedes_id)
        if (target is None or target["status"] != "VOID"
                or target["injury_case_id"] != case["id"]):
            raise unprocessable(ERR_INVALID_SUPERSEDE_TARGET,
                                "supersedes_claim_id must reference a VOID claim of the same injury case")
    ts = now_stamp()
    claim = {
        "id": new_id(), "injury_case_id": case["id"],
        "athlete_id": case["athlete_id"],
        "insurance_policy_id": policy["id"],
        "billed_amount_cents": billed,
        "line_items": [{k: li[k] for k in ("cpt_code", "charge_cents", "service_date")}
                       for li in line_items],
        "_line_items": line_items,
        "status": "DRAFT", "submitted_at": None, "adjudicated_at": None,
        "payer_paid_cents": None, "patient_resp_cents": None,
        "deductible_applied_cents": None,
        "appeals_count": 0, "supersedes_claim_id": supersedes_id,
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    STORE["claims"][claim["id"]] = claim
    return ok_obj(claim_json(claim), 201)


@bp.route("/claims", methods=["GET"])
def list_claims():
    require_roles(*READERS)
    items = sorted_items(STORE["claims"])
    injury_case_id = request.args.get("injury_case_id")
    athlete_id = request.args.get("athlete_id")
    insurance_policy_id = request.args.get("insurance_policy_id")
    status = request.args.get("status")
    supersedes_claim_id = request.args.get("supersedes_claim_id")
    if injury_case_id is not None:
        items = [c for c in items if c["injury_case_id"] == injury_case_id]
    if athlete_id is not None:
        items = [c for c in items if c["athlete_id"] == athlete_id]
    if insurance_policy_id is not None:
        items = [c for c in items if c["insurance_policy_id"] == insurance_policy_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    if supersedes_claim_id is not None:
        items = [c for c in items if c["supersedes_claim_id"] == supersedes_claim_id]
    return ok_list([claim_json(c) for c in items])


@bp.route("/claims/<claimId>", methods=["GET"])
def get_claim(claimId):
    require_roles(*READERS)
    return ok_obj(claim_json(_get_claim(claimId)))


@bp.route("/claims/<claimId>/submit", methods=["POST"])
def submit_claim(claimId):
    require_roles("BillingStaff")
    claim = _get_claim(claimId)
    policy = STORE["insurance_policies"][claim["insurance_policy_id"]]
    j = body()
    # OCC (3.5): after existence, before business rules
    if not present(j, "expected_policy_version"):
        raise bad_request("Missing required field: expected_policy_version")
    ev = j["expected_policy_version"]
    if not isinstance(ev, int) or isinstance(ev, bool):
        raise bad_request("Invalid expected_policy_version")
    if ev != policy["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_policy_version does not match current policy version")
    # state (4)
    if claim["status"] != "DRAFT":
        raise conflict(ERR_CLAIM_NOT_DRAFT, "submit requires claim DRAFT")
    # claim integrity (11)
    if sum(li["charge_cents"] for li in claim["_line_items"]) != claim["billed_amount_cents"]:
        raise unprocessable(ERR_LINE_ITEM_SUM_MISMATCH,
                            "sum(line_items.charge_cents) != billed_amount_cents")
    # temporal window (12)
    for li in claim["_line_items"]:
        if not (policy["_policy_year_start"] <= li["_sd"] <= policy["_policy_year_end"]):
            raise unprocessable(ERR_SERVICE_DATE_OUT_OF_POLICY_YEAR,
                                "service_date outside policy year window")
    # policy usable (15)
    if policy["status"] != "ACTIVE":
        raise conflict(ERR_POLICY_NOT_ACTIVE, "Policy is not ACTIVE")
    claim["status"] = "SUBMITTED"
    claim["submitted_at"] = logical_now_iso()
    touch(claim)
    touch(policy)  # submission increments policy version
    return ok_obj(claim_json(claim))


@bp.route("/claims/<claimId>/adjudicate", methods=["POST"])
def adjudicate(claimId):
    require_roles("BillingStaff")
    claim = _get_claim(claimId)
    if claim["status"] not in ("SUBMITTED", "APPEALED"):
        raise conflict(ERR_CLAIM_NOT_SUBMITTABLE_STATE,
                       "adjudicate requires claim SUBMITTED or APPEALED")
    j = body()
    deny = j.get("deny")
    if deny is not None and not isinstance(deny, bool):
        raise bad_request("deny must be a boolean")
    policy = STORE["insurance_policies"][claim["insurance_policy_id"]]
    final_status = adjudicate_claim(claim, policy, bool(deny))
    claim["status"] = final_status
    return ok_obj(claim_json(claim))


@bp.route("/claims/<claimId>/appeal", methods=["POST"])
def appeal_claim(claimId):
    require_roles("BillingStaff")
    claim = _get_claim(claimId)
    if claim["status"] != "DENIED":
        raise conflict(ERR_CLAIM_NOT_DENIED, "appeal requires claim DENIED")
    if claim["appeals_count"] >= MAX_APPEALS:
        raise conflict(ERR_MAX_APPEALS_REACHED, "Appeal budget exhausted")
    j = body()
    if not present(j, "appeal_reason") or not isinstance(j["appeal_reason"], str):
        raise bad_request("Missing required field: appeal_reason")
    claim["status"] = "APPEALED"
    claim["appeals_count"] += 1
    touch(claim)
    return ok_obj(claim_json(claim))


@bp.route("/claims/<claimId>/void", methods=["POST"])
def void_claim(claimId):
    require_roles("BillingStaff")
    claim = _get_claim(claimId)
    if claim["status"] != "DRAFT":
        raise conflict(ERR_CLAIM_NOT_VOIDABLE, "void requires claim DRAFT")
    claim["status"] = "VOID"
    touch(claim)
    return ok_obj(claim_json(claim))
