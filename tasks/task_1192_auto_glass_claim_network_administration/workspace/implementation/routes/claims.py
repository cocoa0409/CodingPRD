"""Claim lifecycle: intake, coverage verification, deny/cancel/supplement,
choice disclosures, routing decisions."""

from flask import Blueprint, request

from db import store, base_fields, touch, sorted_created, new_id, now_iso, now_dt, next_seq
from errors import (
    ApiError,
    ERR_POLICYHOLDER_NOT_FOUND,
    ERR_POLICY_NOT_FOUND,
    ERR_STATE_REGULATION_NOT_FOUND,
    ERR_CLAIM_NOT_FOUND,
    ERR_SHOP_NOT_FOUND,
    ERR_CLAIM_NOT_SUBMITTED,
    ERR_CLAIM_NOT_COVERAGE_VERIFIED,
    ERR_CLAIM_NOT_CANCELLABLE,
    ERR_RESOURCE_OWNERSHIP_MISMATCH,
    ERR_POLICY_INACTIVE,
    ERR_COVERAGE_TYPE_INELIGIBLE,
    ERR_POLICYHOLDER_SUSPENDED,
    ERR_INVALID_REQUEST,
    ERR_STALE_CLAIM_VERSION,
    ERR_CHOICE_DISCLOSURE_REQUIRED,
    ERR_ACTIVE_WORK_ORDER_EXISTS,
    ERR_SHOP_NOT_ELIGIBLE,
    ERR_NO_ELIGIBLE_SHOP,
)
from middleware import (
    get_context,
    body_json,
    req_str,
    req_int,
    req_bool,
    opt_str,
    req_enum,
    pagination_params,
    paginate,
    ALL_ROLES,
    ROLE_POLICYHOLDER,
    ROLE_CLAIM_ADJUSTER,
)
from response import success_object, success_list
from serialize import claim_view, disclosure_view, work_order_view
from services.pricing import (
    provisional_responsibility,
    final_deductible_basis,
    TIER_MULTIPLIERS,
)
from services.fraud import create_alert, apply_signal, evaluate_repeat_window, FRAUD_THRESHOLD

bp = Blueprint("claims", __name__)

CLAIM_PART_CATEGORIES = {"WINDSHIELD", "SIDE_GLASS", "REAR_GLASS"}
DISCLOSURE_CHANNELS = {"PHONE", "PORTAL", "IN_PERSON"}


def _get_claim(cid):
    claim = store.claims.get(cid)
    if claim is None:
        raise ApiError(ERR_CLAIM_NOT_FOUND, 404, "Claim does not exist")
    return claim


def _check_claim_ownership(claim, uid):
    if claim["policyholder_id"] != uid:
        raise ApiError(
            ERR_RESOURCE_OWNERSHIP_MISMATCH,
            403,
            "Policyholder may act only on their own claims",
        )


@bp.route("/claims", methods=["POST"])
def create_claim():
    uid, _role = get_context([ROLE_POLICYHOLDER])
    data = body_json(required=True)
    policyholder = store.policyholders.get(uid)
    if policyholder is None:
        raise ApiError(ERR_POLICYHOLDER_NOT_FOUND, 404, "Policyholder does not exist")
    policy_id = req_str(data, "policy_id")
    policy = store.policies.get(policy_id)
    if policy is None:
        raise ApiError(ERR_POLICY_NOT_FOUND, 404, "Referenced policy does not exist")
    incident_state_code = req_str(data, "incident_state_code")
    reg_id = store.state_reg_by_code.get(incident_state_code)
    if reg_id is None:
        raise ApiError(
            ERR_STATE_REGULATION_NOT_FOUND,
            404,
            "No StateRegulation for the claim's incident_state_code",
        )
    regulation = store.state_regulations[reg_id]
    # payload sanity
    service_zip_code = req_str(data, "service_zip_code")
    part_category = req_enum(data, "part_category", CLAIM_PART_CATEGORIES)
    loss_date = req_str(data, "loss_date")
    description = req_str(data, "description")
    requires_adas = req_bool(data, "requires_adas_calibration")
    estimated_cost = req_int(data, "estimated_repair_cost_cents")
    # business constraint: suspended policyholder may not file
    if policyholder["status"] == "SUSPENDED":
        raise ApiError(ERR_POLICYHOLDER_SUSPENDED, 422, "Suspended policyholder may not file claims")

    claim = base_fields()
    claim.update(
        {
            "policyholder_id": uid,
            "policy_id": policy_id,
            "assigned_shop_id": None,
            "incident_state_code": incident_state_code,
            "service_zip_code": service_zip_code,
            "part_category": part_category,
            "loss_date": loss_date,
            "description": description,
            "requires_adas_calibration": requires_adas,
            "estimated_repair_cost_cents": estimated_cost,
            "provisional_customer_responsibility_cents": 0,
            "deductible_applied_cents": None,
            "oem_upcharge_cents": 0,
            "customer_responsibility_cents": None,
            "insurer_payment_cents": None,
            "coverage_verified_by_user_id": None,
            "status": "SUBMITTED",
        }
    )
    claim["provisional_customer_responsibility_cents"] = provisional_responsibility(
        claim, policy, regulation
    )
    store.claims[claim["id"]] = claim

    # Threshold gate at intake: pre-signal score >= 100 -> FRAUD_HOLD.
    if policyholder["fraud_score"] >= FRAUD_THRESHOLD:
        claim["status"] = "FRAUD_HOLD"
        create_alert(policyholder["id"], claim["id"], "SCORE_THRESHOLD", 0)

    # REPEAT_WINDOW signal.
    evaluate_repeat_window(policyholder, claim)

    return success_object(claim_view(claim), status=201)


@bp.route("/claims/<cid>", methods=["GET"])
def get_claim(cid):
    get_context(ALL_ROLES)
    return success_object(claim_view(_get_claim(cid)))


@bp.route("/claims", methods=["GET"])
def list_claims():
    get_context(ALL_ROLES)
    limit, offset = pagination_params()
    items = sorted_created(store.claims.values())
    policyholder_id = request.args.get("policyholder_id")
    policy_id = request.args.get("policy_id")
    assigned_shop_id = request.args.get("assigned_shop_id")
    status = request.args.get("status")
    if policyholder_id is not None:
        items = [c for c in items if c["policyholder_id"] == policyholder_id]
    if policy_id is not None:
        items = [c for c in items if c["policy_id"] == policy_id]
    if assigned_shop_id is not None:
        items = [c for c in items if c.get("assigned_shop_id") == assigned_shop_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([claim_view(c) for c in page], limit, offset, total)


@bp.route("/claims/<cid>/verify-coverage", methods=["POST"])
def verify_coverage(cid):
    uid, _role = get_context([ROLE_CLAIM_ADJUSTER])
    claim = _get_claim(cid)
    reg_id = store.state_reg_by_code.get(claim["incident_state_code"])
    if reg_id is None:
        raise ApiError(
            ERR_STATE_REGULATION_NOT_FOUND,
            404,
            "No StateRegulation for the claim's incident_state_code",
        )
    regulation = store.state_regulations[reg_id]
    if claim["status"] != "SUBMITTED":
        raise ApiError(ERR_CLAIM_NOT_SUBMITTED, 409, "verify-coverage requires Claim SUBMITTED")
    policy = store.policies.get(claim["policy_id"])
    if policy is None:
        raise ApiError(ERR_POLICY_NOT_FOUND, 404, "Referenced policy does not exist")
    if policy["status"] != "ACTIVE":
        raise ApiError(ERR_POLICY_INACTIVE, 422, "Policy is not ACTIVE")
    if policy["coverage_type"] != "COMPREHENSIVE":
        raise ApiError(
            ERR_COVERAGE_TYPE_INELIGIBLE,
            422,
            "Glass claims require COMPREHENSIVE coverage",
        )
    claim["deductible_applied_cents"] = final_deductible_basis(claim, policy, regulation)
    claim["coverage_verified_by_user_id"] = uid
    claim["status"] = "COVERAGE_VERIFIED"
    touch(claim)
    return success_object(claim_view(claim))


@bp.route("/claims/<cid>/deny", methods=["POST"])
def deny_claim(cid):
    get_context([ROLE_CLAIM_ADJUSTER])
    claim = _get_claim(cid)
    if claim["status"] != "SUBMITTED":
        raise ApiError(ERR_CLAIM_NOT_SUBMITTED, 409, "deny requires Claim SUBMITTED")
    data = body_json(required=True)
    req_str(data, "denial_reason")
    claim["status"] = "DENIED"
    touch(claim)
    return success_object(claim_view(claim))


@bp.route("/claims/<cid>/cancel", methods=["POST"])
def cancel_claim(cid):
    uid, _role = get_context([ROLE_POLICYHOLDER])
    claim = _get_claim(cid)
    _check_claim_ownership(claim, uid)
    if claim["status"] not in ("SUBMITTED", "COVERAGE_VERIFIED", "WORK_AUTHORIZED"):
        raise ApiError(
            ERR_CLAIM_NOT_CANCELLABLE,
            409,
            "cancel requires Claim in {SUBMITTED, COVERAGE_VERIFIED, WORK_AUTHORIZED}",
        )
    if claim["status"] == "WORK_AUTHORIZED":
        for wo in store.work_orders.values():
            if wo["claim_id"] == cid and wo["status"] in ("OFFERED", "ACCEPTED", "SCHEDULED"):
                wo["status"] = "CANCELLED"
                touch(wo)
    claim["status"] = "CANCELLED"
    touch(claim)
    return success_object(claim_view(claim))


@bp.route("/claims/<cid>/supplement", methods=["POST"])
def supplement_claim(cid):
    uid, _role = get_context([ROLE_POLICYHOLDER])
    claim = _get_claim(cid)
    _check_claim_ownership(claim, uid)
    if claim["status"] != "COVERAGE_VERIFIED":
        raise ApiError(
            ERR_CLAIM_NOT_COVERAGE_VERIFIED,
            409,
            "supplement requires Claim COVERAGE_VERIFIED",
        )
    data = body_json(required=True)
    req_str(data, "additional_damage_description")
    revised_cost = req_int(data, "revised_estimated_repair_cost_cents")
    claim["estimated_repair_cost_cents"] = revised_cost
    policy = store.policies.get(claim["policy_id"])
    regulation = store.state_regulations.get(store.state_reg_by_code.get(claim["incident_state_code"]))
    claim["provisional_customer_responsibility_cents"] = provisional_responsibility(
        claim, policy, regulation
    )
    claim["deductible_applied_cents"] = None
    claim["status"] = "SUBMITTED"
    touch(claim)
    return success_object(claim_view(claim))


# ------------------------------------------------------- Choice disclosures

@bp.route("/claims/<cid>/choice-disclosures", methods=["POST"])
def create_choice_disclosure(cid):
    uid, _role = get_context([ROLE_POLICYHOLDER])
    claim = _get_claim(cid)
    _check_claim_ownership(claim, uid)
    data = body_json(required=True)
    record = {
        "id": new_id(),
        "created_at": now_iso(),
        "_seq": next_seq(),
        "_created_dt": now_dt(),
        "claim_id": cid,
        "disclosure_channel": req_enum(data, "disclosure_channel", DISCLOSURE_CHANNELS),
        "shop_solicited": req_bool(data, "shop_solicited"),
        "customer_selected_shop_name": opt_str(data, "customer_selected_shop_name", None),
        "informed_of_network_options": req_bool(data, "informed_of_network_options"),
    }
    store.disclosures[record["id"]] = record
    if record["shop_solicited"] is True:
        policyholder = store.policyholders.get(claim["policyholder_id"])
        if policyholder is not None:
            apply_signal(policyholder, cid, "SOLICITATION", 35)
    return success_object(disclosure_view(record), status=201)


@bp.route("/claims/<cid>/choice-disclosures", methods=["GET"])
def list_choice_disclosures(cid):
    get_context(ALL_ROLES)
    _get_claim(cid)
    limit, offset = pagination_params()
    items = sorted_created([d for d in store.disclosures.values() if d["claim_id"] == cid])
    page, total = paginate(items, limit, offset)
    return success_list([disclosure_view(d) for d in page], limit, offset, total)


# --------------------------------------------------------- Routing decisions

def _eligible(shop, claim):
    if shop["network_status"] != "ACTIVE":
        return False
    if not any(claim["service_zip_code"].startswith(p) for p in shop["service_zip_prefixes"]):
        return False
    if claim["requires_adas_calibration"] and not shop["adas_certified"]:
        return False
    return True


@bp.route("/claims/<cid>/routing-decisions", methods=["POST"])
def create_routing_decision(cid):
    get_context([ROLE_CLAIM_ADJUSTER])
    claim = _get_claim(cid)
    data = body_json(required=True)
    requested_shop_id = data.get("requested_shop_id")
    requested_shop = None
    if requested_shop_id is not None:
        if not isinstance(requested_shop_id, str):
            raise ApiError(ERR_INVALID_REQUEST, 400, "requested_shop_id must be a string")
        requested_shop = store.shops.get(requested_shop_id)
        if requested_shop is None:
            raise ApiError(ERR_SHOP_NOT_FOUND, 404, "Requested shop does not exist")
    if claim["status"] not in ("COVERAGE_VERIFIED", "WORK_AUTHORIZED"):
        raise ApiError(
            ERR_CLAIM_NOT_COVERAGE_VERIFIED,
            409,
            "routing-decisions requires Claim COVERAGE_VERIFIED",
        )
    expected = data.get("expected_claim_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError(ERR_INVALID_REQUEST, 400, "expected_claim_version is required and must be an integer")
    if expected != claim["version"]:
        raise ApiError(
            ERR_STALE_CLAIM_VERSION,
            412,
            "expected_claim_version does not match the claim's current version",
        )
    if not any(d["claim_id"] == cid for d in store.disclosures.values()):
        raise ApiError(
            ERR_CHOICE_DISCLOSURE_REQUIRED,
            422,
            "At least one ChoiceDisclosureRecord must exist before routing",
        )
    for wo in store.work_orders.values():
        if wo["claim_id"] == cid and wo["status"] in ("ACCEPTED", "SCHEDULED"):
            raise ApiError(
                ERR_ACTIVE_WORK_ORDER_EXISTS,
                409,
                "An ACCEPTED or SCHEDULED work order already exists for this claim",
            )
    if requested_shop is not None:
        if not _eligible(requested_shop, claim):
            raise ApiError(
                ERR_SHOP_NOT_ELIGIBLE,
                422,
                "requested_shop_id fails the selector eligibility filter",
            )
        selected = requested_shop
    else:
        pool = [s for s in store.shops.values() if _eligible(s, claim)]
        if not pool:
            raise ApiError(ERR_NO_ELIGIBLE_SHOP, 422, "Selector candidate pool is empty")
        pool.sort(key=lambda s: (TIER_MULTIPLIERS[s["agreement_tier"]], s["_created_dt"], s["_seq"]))
        selected = pool[0]

    for wo in store.work_orders.values():
        if wo["claim_id"] == cid and wo["status"] in ("OFFERED", "NO_SHOW"):
            wo["status"] = "SUPERSEDED"
            touch(wo)

    work_order = base_fields()
    work_order.update(
        {
            "claim_id": cid,
            "shop_id": selected["id"],
            "warranty_claim_id": None,
            "service_mode": None,
            "scheduled_start": None,
            "scheduled_end": None,
            "completed_at": None,
            "status": "OFFERED",
        }
    )
    store.work_orders[work_order["id"]] = work_order
    claim["assigned_shop_id"] = selected["id"]
    claim["status"] = "WORK_AUTHORIZED"
    touch(claim)
    return success_object(work_order_view(work_order), status=201)


@bp.route("/claims/<cid>/work-orders", methods=["GET"])
def list_claim_work_orders(cid):
    get_context(ALL_ROLES)
    _get_claim(cid)
    limit, offset = pagination_params()
    items = sorted_created([w for w in store.work_orders.values() if w["claim_id"] == cid])
    status = request.args.get("status")
    if status is not None:
        items = [w for w in items if w["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([work_order_view(w) for w in page], limit, offset, total)
