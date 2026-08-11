"""Production endpoints: create/list/get, activate, wrap, cancel."""

from db import db
from errors import err
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from routes import bp
from services.lifecycle import sweep
from services.posture import (
    MANDATORY_CLEARANCE_KINDS,
    OPEN_CLAIM_STATUSES,
    recompute_posture,
)
from util import (
    body,
    get_production,
    make_entity,
    opt_bool,
    paginate,
    req_dt,
    req_enum,
    req_int,
    req_string,
    serialize,
    touch,
)

PRODUCTION_TYPES = ("FEATURE", "EPISODIC", "DOCUMENTARY", "COMMERCIAL", "MUSIC_VIDEO")


@bp.route("/productions", methods=["POST"])
def create_production():
    require_roles({"BrokerAgent"})
    data = body()
    production_code = req_string(data, "production_code")
    title = req_string(data, "title")
    production_type = req_enum(data, "production_type", PRODUCTION_TYPES)
    pp_start = req_dt(data, "principal_photography_start")
    pp_end = req_dt(data, "principal_photography_end")
    budget_cents = req_int(data, "budget_cents")
    requires_bond = opt_bool(data, "requires_completion_bond", False)
    if pp_end <= pp_start:
        raise err("ERR_TEMPORAL_RANGE_INVALID",
                  "principal_photography_end must be after principal_photography_start")
    if budget_cents <= 0:
        raise err("ERR_FISCAL_CONSTRAINT_VIOLATED", "budget_cents must be greater than zero")

    with db.lock:
        rec = make_entity({
            "production_code": production_code,
            "title": title,
            "production_type": production_type,
            "principal_photography_start": pp_start,
            "principal_photography_end": pp_end,
            "budget_cents": budget_cents,
            "requires_completion_bond": requires_bond,
            "coverage_posture": "UNBOUND",
            "posture_reasons": [],
            "status": "DRAFT",
        })
        db.productions[rec["id"]] = rec
        return success_object(serialize(rec), status=201)


@bp.route("/productions", methods=["GET"])
def list_productions():
    require_roles(set(ALL_ROLES))
    status = None
    posture = None
    from flask import request
    status = request.args.get("status")
    posture = request.args.get("coverage_posture")
    records = list(db.productions.values())
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if posture is not None:
        records = [r for r in records if r["coverage_posture"] == posture]
    items, page = paginate(records)
    return success_list(items, page)


@bp.route("/productions/<id>", methods=["GET"])
def get_production_by_id(id):
    require_roles(set(ALL_ROLES))
    rec = get_production(id)
    return success_object(serialize(rec))


@bp.route("/productions/<id>/activate", methods=["POST"])
def activate_production(id):
    require_roles({"BrokerAgent"})
    with db.lock:
        prod = get_production(id)
        if prod["status"] != "DRAFT":
            raise err("ERR_INVALID_STATE",
                      "Production must be DRAFT to activate (current: %s)" % prod["status"])

        has_bound = any(
            p["production_id"] == id and p["status"] in ("BOUND", "ENDORSED_PENDING", "ACTIVE")
            for p in db.policies.values()
        )
        if not has_bound:
            raise err("ERR_NO_BOUND_POLICY",
                      "Activation requires at least one policy in BOUND, ENDORSED_PENDING or ACTIVE")

        if prod["requires_completion_bond"]:
            bond_id = db.bond_by_production.get(id)
            bond = db.completion_bonds.get(bond_id) if bond_id else None
            if bond is None or bond["status"] != "ISSUED":
                raise err("ERR_BOND_NOT_ISSUED",
                          "Production requires a completion bond in ISSUED status")

        for cm in db.cast_members.values():
            if cm["production_id"] != id or not cm["endorsement_required"]:
                continue
            has_issued = any(
                e["cast_member_id"] == cm["id"] and e["status"] == "ISSUED"
                for e in db.cast_endorsements.values()
            )
            if not has_issued:
                raise err("ERR_CAST_ENDORSEMENT_MISSING",
                          "Cast member '%s' requires an ISSUED endorsement" % cm["id"])

        for ci in db.clearance_items.values():
            if (ci["production_id"] == id
                    and ci["clearance_kind"] in MANDATORY_CLEARANCE_KINDS
                    and ci["status"] not in ("CLEARED", "WAIVED")):
                raise err("ERR_MANDATORY_CLEARANCE_OPEN",
                          "Mandatory clearance '%s' is not CLEARED or WAIVED" % ci["id"])

        prod["status"] = "ACTIVE"
        touch(prod)
        recompute_posture(prod)
        return success_object(serialize(prod))


@bp.route("/productions/<id>/wrap", methods=["POST"])
def wrap_production(id):
    require_roles({"ProductionManager"})
    with db.lock:
        prod = get_production(id)
        if prod["status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE",
                      "Production must be ACTIVE to wrap (current: %s)" % prod["status"])

        for cl in db.claims.values():
            if cl["production_id"] == id and cl["status"] not in ("SETTLED", "DENIED", "CLOSED"):
                raise err("ERR_OPEN_CLAIMS_BLOCK_WRAP",
                          "Production cannot wrap while claims are open")

        for cert in db.certificates.values():
            if cert["production_id"] == id and cert["status"] == "DRAFT":
                raise err("ERR_DRAFT_CERTIFICATES_OPEN",
                          "Draft certificates must be issued or voided before wrap")

        prod["status"] = "WRAPPED"
        touch(prod)

        for cert in db.certificates.values():
            if cert["production_id"] == id and cert["status"] == "ISSUED":
                cert["status"] = "EXPIRED"
                touch(cert)

        for ext in db.travel_extensions.values():
            if ext["production_id"] == id and ext["status"] == "ACTIVE":
                ext["status"] = "EXPIRED"
                touch(ext)

        bond_id = db.bond_by_production.get(id)
        if bond_id:
            bond = db.completion_bonds[bond_id]
            if bond["status"] == "ISSUED":
                bond["status"] = "RELEASED"
                touch(bond)

        # Schedule a payroll audit per ACTIVE policy
        for pol in list(db.policies.values()):
            if pol["production_id"] == id and pol["status"] == "ACTIVE":
                audit = make_entity({
                    "policy_id": pol["id"],
                    "audit_period_start": pol["effective_date"],
                    "audit_period_end": pol["expiry_date"],
                    "auditor_name": None,
                    "reported_payroll_cents": 0,
                    "premium_delta_cents": None,
                    "status": "SCHEDULED",
                })
                db.payroll_audits[audit["id"]] = audit

        recompute_posture(prod)
        return success_object(serialize(prod))


@bp.route("/productions/<id>/cancel", methods=["POST"])
def cancel_production(id):
    require_roles({"BrokerAgent"})
    with db.lock:
        prod = get_production(id)
        if prod["status"] not in ("DRAFT", "ACTIVE"):
            raise err("ERR_INVALID_STATE",
                      "Production must be DRAFT or ACTIVE to cancel (current: %s)" % prod["status"])

        if prod["status"] == "ACTIVE":
            for cl in db.claims.values():
                if cl["production_id"] == id and cl["status"] in OPEN_CLAIM_STATUSES:
                    raise err("ERR_OPEN_CLAIMS_BLOCK_CANCEL",
                              "Production cannot cancel while claims are open")

        was = prod["status"]
        prod["status"] = "CANCELLED"
        touch(prod)

        if was == "ACTIVE":
            for pol in db.policies.values():
                if (pol["production_id"] == id
                        and pol["status"] in ("BOUND", "ENDORSED_PENDING", "ACTIVE")):
                    pol["status"] = "CANCELLED"
                    touch(pol)
            for cert in db.certificates.values():
                if cert["production_id"] == id and cert["status"] in ("DRAFT", "ISSUED"):
                    cert["status"] = "VOIDED"
                    touch(cert)
            for e in db.cast_endorsements.values():
                cm = db.cast_members.get(e["cast_member_id"])
                if (cm and cm["production_id"] == id and e["status"] == "ISSUED"):
                    e["status"] = "REVOKED"
                    e["revoked_at"] = prod["updated_at"]
                    touch(e)
            bond_id = db.bond_by_production.get(id)
            if bond_id:
                bond = db.completion_bonds[bond_id]
                if bond["status"] in ("APPLIED", "UNDERWRITTEN", "ISSUED"):
                    bond["status"] = "LAPSED"
                    touch(bond)
            for ext in db.travel_extensions.values():
                if (ext["production_id"] == id
                        and ext["status"] in ("REQUESTED", "APPROVED", "ACTIVE")):
                    ext["status"] = "DENIED"
                    touch(ext)
        else:
            for pol in db.policies.values():
                if pol["production_id"] == id and pol["status"] == "QUOTED":
                    pol["status"] = "CANCELLED"
                    touch(pol)

        recompute_posture(prod)
        sweep()
        return success_object(serialize(prod))
