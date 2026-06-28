"""Episode routes: open, clinical-axis transitions, write-off, sub-resource lists."""
from flask import Blueprint, request

from db import db
from common import stamp_new, touch, public, paginate, get_body, require_datetime
from errors import (err, ERR_KIT_OUT_OF_STOCK, ERR_INVALID_STATE,
                    ERR_RISK_TRANSFER_REQUIRED, ERR_NO_ACTIVE_BOOKING,
                    ERR_POSTPARTUM_INCOMPLETE)
from middleware import require_auth, require_role, ALL_ROLES
from response import object_response, array_response
import lookup
from services import calc, cascade

bp = Blueprint("episodes", __name__)


# ---------------------------------------------------------------------------
# Open an episode of care (§3.1)
# ---------------------------------------------------------------------------
@bp.route("/birth-center/episodes", methods=["POST"])
def create_episode():
    _, role = require_auth()
    require_role(role, ["IntakeCoordinator"])
    body = get_body()
    # well-formedness (priority 4) for required fields
    from common import require_string
    client_id = require_string(body, "client_id")
    package_code = require_string(body, "package_code")
    edd = require_datetime(body, "edd")
    # existence (priority 3) of FK targets, left-to-right
    lookup.get_client(client_id)
    package = lookup.get_care_package(package_code)
    kit = lookup.get_supply_kit(package["kit_sku"])

    rec = {
        "client_id": client_id,
        "package_code": package_code,
        "edd": edd,
        "clinical_status": "PLANNING",
        "financial_status": "UNBILLED",
        "risk_tier": "LOW",
        "kit_issued": False,
        "prenatal_visits_completed": 0,
        "global_fee_cents": package["global_fee_cents"],
        "balance_due_cents": 0,
        "_kit_sku": package["kit_sku"],
    }
    stamp_new(rec)

    # Reserve one kit unit; reject if reserving drives available below 0.
    if calc.kit_available(kit) - 1 < 0:
        raise err(ERR_KIT_OUT_OF_STOCK, "No supply kit unit available")

    db.episodes[rec["id"]] = rec
    rec["kit_issued"] = True
    # Recompute kit counters (episode now in PLANNING -> reserved++).
    if calc.reconcile_kit(kit):
        touch(kit)

    # Create the bundled GLOBAL_FEE charge in DRAFT (ESTIMATE variant).
    charge = {
        "episode_id": rec["id"],
        "claim_id": "",
        "charge_kind": "GLOBAL_FEE",
        "amount_cents": rec["global_fee_cents"],
        "client_responsibility_cents": 0,
        "status": "DRAFT",
    }
    stamp_new(charge)
    charge["client_responsibility_cents"] = calc.compute_charge_responsibility(charge)
    db.charges[charge["id"]] = charge

    # Derive balance from the new charge (does not bump version at creation;
    # balance_due_cents is a computed field set at open).
    rec["balance_due_cents"] = calc.compute_balance_due(rec)

    return object_response(public(rec), 201)


@bp.route("/birth-center/episodes/<eid>", methods=["GET"])
def get_episode(eid):
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    rec = lookup.get_episode(eid)
    return object_response(public(rec), 200)


@bp.route("/birth-center/episodes", methods=["GET"])
def list_episodes():
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    client_id = request.args.get("client_id")
    package_code = request.args.get("package_code")
    clinical_status = request.args.get("clinical_status")
    financial_status = request.args.get("financial_status")
    records = [r for r in db.episodes.values()
               if (client_id is None or r["client_id"] == client_id)
               and (package_code is None or r["package_code"] == package_code)
               and (clinical_status is None or r["clinical_status"] == clinical_status)
               and (financial_status is None or r["financial_status"] == financial_status)]
    items, limit, offset, total = paginate(records)
    return array_response(items, limit, offset, total, 200)


# ---------------------------------------------------------------------------
# Clinical axis transitions (§3.2)
# ---------------------------------------------------------------------------
@bp.route("/birth-center/episodes/<eid>/activate", methods=["POST"])
def activate(eid):
    _, role = require_auth()
    require_role(role, ["Midwife"])
    ep = lookup.get_episode(eid)
    # state check (priority 6)
    if ep["clinical_status"] != "PLANNING":
        raise err(ERR_INVALID_STATE, "Episode is not in PLANNING")
    # business-safety risk gate (priority 7)
    if ep["risk_tier"] == "TRANSFER_REQUIRED":
        raise err(ERR_RISK_TRANSFER_REQUIRED, "Episode requires transfer; cannot activate")
    # kit must have been reserved
    if not ep["kit_issued"]:
        raise err(ERR_INVALID_STATE, "No kit reserved for episode")
    ep["clinical_status"] = "ACTIVE"
    touch(ep)
    return object_response(public(ep), 200)


@bp.route("/birth-center/episodes/<eid>/transfer", methods=["POST"])
def transfer(eid):
    _, role = require_auth()
    require_role(role, ["Midwife"])
    ep = lookup.get_episode(eid)
    if ep["clinical_status"] not in ("PLANNING", "ACTIVE"):
        raise err(ERR_INVALID_STATE, "Episode cannot be transferred from this state")
    ep["clinical_status"] = "TRANSFERRED"
    touch(ep)  # single episode version bump for the transfer
    cascade.transfer_cascade(ep)
    return object_response(public(ep), 200)


@bp.route("/birth-center/episodes/<eid>/record-birth", methods=["POST"])
def record_birth(eid):
    _, role = require_auth()
    require_role(role, ["Midwife"])
    ep = lookup.get_episode(eid)
    # state check (priority 6): must be ACTIVE
    if ep["clinical_status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Episode is not ACTIVE")
    # risk gate (priority 8)
    if ep["risk_tier"] == "TRANSFER_REQUIRED":
        raise err(ERR_RISK_TRANSFER_REQUIRED, "Episode requires transfer; cannot record birth")
    # requires an IN_USE booking (priority 18)
    if cascade.episode_in_use_booking(ep) is None:
        raise err(ERR_NO_ACTIVE_BOOKING, "No IN_USE booking on episode")
    ep["clinical_status"] = "BORN"
    touch(ep)
    cascade.record_birth_cascade(ep)
    return object_response(public(ep), 200)


@bp.route("/birth-center/episodes/<eid>/complete-care", methods=["POST"])
def complete_care(eid):
    _, role = require_auth()
    require_role(role, ["Midwife"])
    ep = lookup.get_episode(eid)
    if ep["clinical_status"] != "BORN":
        raise err(ERR_INVALID_STATE, "Episode is not BORN")
    package = db.care_packages.get(ep["package_code"])
    required = package["postpartum_visits_included"] if package else 0
    if ep["prenatal_visits_completed"] < required:
        raise err(ERR_POSTPARTUM_INCOMPLETE, "Postpartum follow-up not fulfilled")
    ep["clinical_status"] = "COMPLETED"
    touch(ep)
    return object_response(public(ep), 200)


# ---------------------------------------------------------------------------
# Financial axis: write-off (§3.11)
# ---------------------------------------------------------------------------
@bp.route("/birth-center/episodes/<eid>/write-off", methods=["POST"])
def write_off(eid):
    _, role = require_auth()
    require_role(role, ["BillingClerk"])
    ep = lookup.get_episode(eid)
    if ep["financial_status"] not in ("UNBILLED", "PLAN_ACTIVE"):
        raise err(ERR_INVALID_STATE, "Episode cannot be written off from this financial state")
    ep["financial_status"] = "WRITTEN_OFF"
    cascade.write_off_cascade(ep)
    calc.rederive_balance(ep)
    touch(ep)
    return object_response(public(ep), 200)


# ---------------------------------------------------------------------------
# Sub-resource list endpoints (reverse-reachability)
# ---------------------------------------------------------------------------
@bp.route("/birth-center/episodes/<eid>/prenatal-visits", methods=["GET"])
def list_episode_visits(eid):
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    lookup.get_episode(eid)
    visit_kind = request.args.get("visit_kind")
    status = request.args.get("status")
    records = [r for r in db.prenatal_visits.values()
               if r["episode_id"] == eid
               and (visit_kind is None or r["visit_kind"] == visit_kind)
               and (status is None or r["status"] == status)]
    items, limit, offset, total = paginate(records)
    return array_response(items, limit, offset, total, 200)


@bp.route("/birth-center/episodes/<eid>/charges", methods=["GET"])
def list_episode_charges(eid):
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    lookup.get_episode(eid)
    charge_kind = request.args.get("charge_kind")
    status = request.args.get("status")
    records = [r for r in db.charges.values()
               if r["episode_id"] == eid
               and (charge_kind is None or r["charge_kind"] == charge_kind)
               and (status is None or r["status"] == status)]
    items, limit, offset, total = paginate(records)
    return array_response(items, limit, offset, total, 200)


@bp.route("/birth-center/episodes/<eid>/on-call-assignments", methods=["GET"])
def list_episode_assignments(eid):
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    lookup.get_episode(eid)
    coverage_role = request.args.get("coverage_role")
    status = request.args.get("status")
    records = [r for r in db.on_call_assignments.values()
               if r["episode_id"] == eid
               and (coverage_role is None or r["coverage_role"] == coverage_role)
               and (status is None or r["status"] == status)]
    items, limit, offset, total = paginate(records)
    return array_response(items, limit, offset, total, 200)


@bp.route("/birth-center/episodes/<eid>/bookings", methods=["GET"])
def list_episode_bookings(eid):
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    lookup.get_episode(eid)
    status = request.args.get("status")
    records = [r for r in db.bookings.values()
               if r["episode_id"] == eid
               and (status is None or r["status"] == status)]
    items, limit, offset, total = paginate(records)
    return array_response(items, limit, offset, total, 200)


@bp.route("/birth-center/episodes/<eid>/insurance-claims", methods=["GET"])
def list_episode_claims(eid):
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    lookup.get_episode(eid)
    status = request.args.get("status")
    records = [r for r in db.insurance_claims.values()
               if r["episode_id"] == eid
               and (status is None or r["status"] == status)]
    items, limit, offset, total = paginate(records)
    return array_response(items, limit, offset, total, 200)


@bp.route("/birth-center/episodes/<eid>/payment-plans", methods=["GET"])
def list_episode_plans(eid):
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    lookup.get_episode(eid)
    status = request.args.get("status")
    records = [r for r in db.payment_plans.values()
               if r["episode_id"] == eid
               and (status is None or r["status"] == status)]
    items, limit, offset, total = paginate(records)
    return array_response(items, limit, offset, total, 200)
