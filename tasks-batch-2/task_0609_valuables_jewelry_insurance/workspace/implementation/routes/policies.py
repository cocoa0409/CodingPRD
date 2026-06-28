"""Policy routes: create/get/list, scheduled-items, bind, cancel."""
from flask import Blueprint, request

import calc
import clock
import db
import lookups
import response
import serializers
import validators as V
from dateutil_min import add_months
from errors import err
from middleware import get_identity, require_role
from routes.common import paginate_and_respond, assert_policy_access

bp = Blueprint("policies", __name__)

COVERAGE_TYPES = {"ALL_RISK", "NAMED_PERIL"}
VALUATION_BASES = {"AGREED_VALUE", "REPLACEMENT_COST"}
DEDUCTIBLE_OPTIONS = {"ZERO", "LOW", "STANDARD", "HIGH"}
INFLATION_MODES = {"NONE", "SIMPLE", "COMPOUND"}
PERILS = {"THEFT", "FIRE", "FLOOD", "ACCIDENTAL_DAMAGE", "MYSTERIOUS_DISAPPEARANCE"}
CATEGORIES = {"RING", "NECKLACE", "WATCH", "LOOSE_STONE", "OTHER"}


def _appraisal_valid_now(appraisal):
    """True if the appraisal is currently within its half-open validity window."""
    if appraisal is None:
        return False
    if appraisal["status"] != "VALID":
        return False
    eff = clock.parse_iso(appraisal["effective_date_iso"])
    if eff is None:
        return False
    now = clock.now()
    window_end = add_months(eff, appraisal["valid_months"])
    return eff <= now < window_end


# =============================== Create / read ===========================
@bp.route("/policies", methods=["POST"])
def create_policy():
    _, role = get_identity()
    require_role(role, {"Underwriter"})
    body = V.get_json(request)
    policyholder_id = V.require_str(body, "policyholder_id")
    coverage_type = V.require_enum(body, "coverage_type", COVERAGE_TYPES)
    valuation_basis = V.require_enum(body, "valuation_basis", VALUATION_BASES)
    deductible_option = V.require_enum(body, "deductible_option", DEDUCTIBLE_OPTIONS)
    worldwide = V.opt_bool(body, "worldwide_coverage", default=False)
    listed_perils = V.require_list(body, "listed_perils", default=[])
    for p in listed_perils:
        if p not in PERILS:
            raise err("ERR_INVALID_REQUEST", "listed_perils contains an invalid peril")
    inflation_mode = V.opt_enum(body, "inflation_guard_mode", INFLATION_MODES, default="NONE")
    inflation_pct = V.opt_number(body, "inflation_guard_pct", default=0)

    lookups.get_policyholder(policyholder_id)

    rec = {
        "id": db.new_id(),
        "policyholder_id": policyholder_id,
        "coverage_type": coverage_type,
        "valuation_basis": valuation_basis,
        "deductible_option": deductible_option,
        "worldwide_coverage": worldwide,
        "listed_perils": listed_perils,
        "inflation_guard_mode": inflation_mode,
        "inflation_guard_pct": inflation_pct,
        "deductible_cents": None,
        "total_insured_value_cents": None,
        "annual_premium_cents": None,
        "coverage_status": "QUOTED",
        "billing_status": "UNBILLED",
        "past_due_since": None,
        "bound_at_iso": None,
    }
    db.stamp_create(rec)
    db.policies[rec["id"]] = rec
    return response.success(serializers.policy(rec), status=201)


@bp.route("/policies/<pid>", methods=["GET"])
def get_policy(pid):
    user_id, role = get_identity()
    require_role(role, {"Underwriter", "ClaimsAdjuster", "Policyholder"})
    rec = lookups.get_policy(pid)
    assert_policy_access(rec, user_id, role)
    return response.success(serializers.policy(rec), status=200)


@bp.route("/policies", methods=["GET"])
def list_policies():
    user_id, role = get_identity()
    require_role(role, {"Underwriter", "ClaimsAdjuster", "Policyholder"})
    policyholder_id = request.args.get("policyholder_id")
    records = list(db.policies.values())
    if policyholder_id is not None:
        records = [r for r in records if r["policyholder_id"] == policyholder_id]
    if role == "Policyholder":
        records = [r for r in records if r["policyholder_id"] == user_id]
    return paginate_and_respond(records, serializers.policy)


# =============================== Scheduled items =========================
@bp.route("/policies/<pid>/scheduled-items", methods=["POST"])
def create_scheduled_item(pid):
    _, role = get_identity()
    require_role(role, {"Underwriter"})
    policy = lookups.get_policy(pid)
    body = V.get_json(request)
    description = V.require_str(body, "description")
    category = V.require_enum(body, "category", CATEGORIES)
    location_zip = V.require_zip(body, "location_zip")
    scheduled_value = V.require_positive_int(body, "scheduled_value_cents")
    appraisal_id = body.get("appraisal_id")
    if appraisal_id is not None:
        if not isinstance(appraisal_id, str) or appraisal_id == "":
            raise err("ERR_INVALID_REQUEST", "appraisal_id must be a string")

    # State gate: rejected on CANCELLED policies.
    if policy["coverage_status"] == "CANCELLED":
        raise err("ERR_INVALID_STATE", "Cannot add items to a cancelled policy")

    if appraisal_id is not None:
        lookups.get_appraisal(appraisal_id)

    rec = {
        "id": db.new_id(),
        "policy_id": policy["id"],
        "description": description,
        "category": category,
        "location_zip": location_zip,
        "scheduled_value_cents": scheduled_value,
        "current_value_cents": None,
        "revaluation_epoch": 0,
        "appraisal_id": appraisal_id,
        "item_status": "PENDING",
    }
    db.stamp_create(rec)
    db.scheduled_items[rec["id"]] = rec
    # Attaching an appraisal to an item supersedes any prior VALID appraisal
    # for the same item slot (PRD §3.1). We supersede earlier VALID appraisals
    # of the same policyholder attached to scheduled items on this policy that
    # share this item's description.
    _supersede_prior_appraisals(policy, rec)
    return response.success(serializers.scheduled_item(rec), status=201)


def _supersede_prior_appraisals(policy, new_item):
    """When a newer VALID appraisal is attached to the same item (by
    description on the same policy), flip earlier VALID appraisals to
    SUPERSEDED (PRD §3.1)."""
    new_aid = new_item.get("appraisal_id")
    if new_aid is None:
        return
    new_ap = db.appraisals.get(new_aid)
    if new_ap is None or new_ap["status"] != "VALID":
        return
    for it in db.scheduled_items.values():
        if it["id"] == new_item["id"]:
            continue
        if it["policy_id"] != policy["id"]:
            continue
        if it["description"] != new_item["description"]:
            continue
        prior_aid = it.get("appraisal_id")
        if prior_aid is None or prior_aid == new_aid:
            continue
        prior = db.appraisals.get(prior_aid)
        if prior is not None and prior["status"] == "VALID":
            prior["status"] = "SUPERSEDED"
            db.touch(prior)


@bp.route("/scheduled-items/<iid>", methods=["GET"])
def get_scheduled_item(iid):
    user_id, role = get_identity()
    require_role(role, {"Underwriter", "ClaimsAdjuster", "Policyholder"})
    rec = lookups.get_scheduled_item(iid)
    policy = db.policies.get(rec["policy_id"])
    if policy is not None:
        assert_policy_access(policy, user_id, role)
    return response.success(serializers.scheduled_item(rec), status=200)


@bp.route("/scheduled-items", methods=["GET"])
def list_scheduled_items():
    user_id, role = get_identity()
    require_role(role, {"Underwriter", "ClaimsAdjuster", "Policyholder"})
    policy_id = request.args.get("policy_id")
    appraisal_id = request.args.get("appraisal_id")
    records = list(db.scheduled_items.values())
    if policy_id is not None:
        records = [r for r in records if r["policy_id"] == policy_id]
    if appraisal_id is not None:
        records = [r for r in records if r.get("appraisal_id") == appraisal_id]
    if role == "Policyholder":
        owned = {p["id"] for p in db.policies.values() if p["policyholder_id"] == user_id}
        records = [r for r in records if r["policy_id"] in owned]
    return paginate_and_respond(records, serializers.scheduled_item)


# =============================== Bind ====================================
@bp.route("/policies/<pid>/bind", methods=["POST"])
def bind_policy(pid):
    _, role = get_identity()
    require_role(role, {"Underwriter"})
    policy = lookups.get_policy(pid)

    # State legality (priority 5).
    if policy["coverage_status"] != "QUOTED":
        raise err("ERR_INVALID_STATE", "Policy is not QUOTED")

    items = [it for it in db.scheduled_items.values() if it["policy_id"] == policy["id"]]
    pending = [it for it in items if it["item_status"] == "PENDING"]

    # Business-rule order follows the PRD §3.3 narrative, which is authoritative
    # over the scaffold's validation priority numbers: after the QUOTED state
    # gate, PRD lists (1) at-least-one PENDING item, (2) NAMED_PERIL has perils,
    # (3) every above-threshold item carries a valid appraisal.
    if not pending:
        raise err("ERR_NO_SCHEDULED_ITEMS", "Policy has no PENDING scheduled items")

    if policy["coverage_type"] == "NAMED_PERIL" and not policy["listed_perils"]:
        raise err("ERR_NAMED_PERIL_REQUIRES_PERILS",
                  "NAMED_PERIL policy must list at least one peril")

    for it in pending:
        if it["scheduled_value_cents"] > calc.APPRAISAL_REQUIRED_THRESHOLD_CENTS:
            ap = db.appraisals.get(it.get("appraisal_id")) if it.get("appraisal_id") else None
            if not _appraisal_valid_now(ap):
                raise err("ERR_APPRAISAL_REQUIRED",
                          "Item above appraisal threshold lacks a valid appraisal")

    # ---- Cascade ----
    policy["deductible_cents"] = calc.resolve_deductible(policy["deductible_option"])
    for it in pending:
        it["item_status"] = "ACTIVE"
        it["current_value_cents"] = it["scheduled_value_cents"]
        it["revaluation_epoch"] = 0
        db.touch(it)
    calc.recompute_policy_aggregates(policy)
    policy["bound_at_iso"] = clock.now_iso()
    policy["coverage_status"] = "BOUND"
    db.touch(policy)
    return response.success(serializers.policy(policy), status=200)


# =============================== Cancel ==================================
@bp.route("/policies/<pid>/cancel", methods=["POST"])
def cancel_policy(pid):
    user_id, role = get_identity()
    require_role(role, {"Underwriter", "Policyholder"})
    policy = lookups.get_policy(pid)
    assert_policy_access(policy, user_id, role)

    if policy["coverage_status"] not in ("QUOTED", "BOUND", "ACTIVE"):
        raise err("ERR_INVALID_STATE", "Policy cannot be cancelled from its current state")

    blocking = {"UNDER_REVIEW", "INFO_REQUESTED", "APPROVED"}
    for cl in db.claims.values():
        if cl["policy_id"] == policy["id"] and cl["status"] in blocking:
            raise err("ERR_OPEN_CLAIM_BLOCKS_CANCEL",
                      "An open claim blocks cancellation")

    policy["coverage_status"] = "CANCELLED"
    db.touch(policy)
    for it in db.scheduled_items.values():
        if it["policy_id"] == policy["id"] and it["item_status"] != "REMOVED":
            it["item_status"] = "REMOVED"
            db.touch(it)
    return response.success(serializers.policy(policy), status=200)
