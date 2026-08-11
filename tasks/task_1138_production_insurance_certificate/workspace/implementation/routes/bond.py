"""Completion bond endpoints (one bond per production)."""

from db import db
from errors import err
from middleware import require_roles
from response import success_list, success_object
from routes import bp
from services.posture import derive_posture, recompute_posture
from services.pricing import bond_min_amount_cents, bond_premium_calculate
from util import (
    body,
    get_production,
    make_entity,
    paginate,
    req_int,
    req_string,
    serialize,
    touch,
)

BOND_READ_ROLES = {"BrokerAgent", "ProductionManager", "SuretyUnderwriter", "PlatformOperator"}
OPEN_CLAIM_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "ADJUSTED")


def get_bond_for_production(prod_id):
    bond_id = db.bond_by_production.get(prod_id)
    return db.completion_bonds.get(bond_id) if bond_id else None


def require_bond(prod_id):
    bond = get_bond_for_production(prod_id)
    if bond is None:
        raise err("ERR_NOT_FOUND", "Production '%s' has no completion bond" % prod_id)
    return bond


@bp.route("/productions/<id>/completion-bond", methods=["POST"])
def apply_completion_bond(id):
    require_roles({"ProductionManager"})
    with db.lock:
        prod = get_production(id)
        data = body()
        surety_company = req_string(data, "surety_company")
        bond_amount_cents = req_int(data, "bond_amount_cents")
        if bond_amount_cents <= 0:
            raise err("ERR_FISCAL_CONSTRAINT_VIOLATED",
                      "bond_amount_cents must be greater than zero")
        if get_bond_for_production(id) is not None:
            raise err("ERR_DUPLICATE_IDENTIFIER",
                      "Production '%s' already has a completion bond" % id)

        rec = make_entity({
            "production_id": id,
            "surety_company": surety_company,
            "bond_amount_cents": bond_amount_cents,
            "bond_premium_cents": None,
            "strike_price_cents": None,
            "status": "APPLIED",
        })
        db.completion_bonds[rec["id"]] = rec
        db.bond_by_production[id] = rec["id"]
        recompute_posture(prod)
        return success_object(serialize(rec), status=201)


@bp.route("/productions/<id>/completion-bond", methods=["GET"])
def get_completion_bond(id):
    require_roles(BOND_READ_ROLES)
    get_production(id)
    bond = get_bond_for_production(id)
    records = [bond] if bond else []
    items, page = paginate(records)
    return success_list(items, page)


@bp.route("/productions/<id>/completion-bond/underwrite", methods=["POST"])
def underwrite_bond(id):
    require_roles({"SuretyUnderwriter"})
    with db.lock:
        prod = get_production(id)
        bond = require_bond(id)
        if bond["status"] != "APPLIED":
            raise err("ERR_INVALID_STATE",
                      "Bond must be APPLIED to underwrite (current: %s)" % bond["status"])
        if not prod["requires_completion_bond"]:
            raise err("ERR_REFERENCED_STATE_INVALID",
                      "Production does not require a completion bond")
        if prod["budget_cents"] <= 0:
            raise err("ERR_FISCAL_CONSTRAINT_VIOLATED", "budget_cents must be positive")
        if bond["bond_amount_cents"] < bond_min_amount_cents(prod["budget_cents"]):
            raise err("ERR_FISCAL_CONSTRAINT_VIOLATED",
                      "bond_amount_cents must cover at least %d%% of budget_cents"
                      % 50)
        bond["bond_premium_cents"] = bond_premium_calculate(bond["bond_amount_cents"])
        bond["strike_price_cents"] = bond["bond_amount_cents"]
        bond["status"] = "UNDERWRITTEN"
        touch(bond)
        return success_object(serialize(bond))


@bp.route("/productions/<id>/completion-bond/issue", methods=["POST"])
def issue_bond(id):
    require_roles({"SuretyUnderwriter"})
    with db.lock:
        prod = get_production(id)
        bond = require_bond(id)
        if bond["status"] != "UNDERWRITTEN":
            raise err("ERR_INVALID_STATE",
                      "Bond must be UNDERWRITTEN to issue (current: %s)" % bond["status"])
        # Posture gate per PRD 3.7, evaluated with the bond's own
        # not-yet-issued contribution discounted: a required bond cannot
        # self-block its own issuance, or ISSUED would be unreachable.
        gate_posture, _ = derive_posture(prod, assume_bond_issued=True)
        if gate_posture not in ("BOUND_PARTIAL", "BOUND_FULL"):
            raise err("ERR_POSTURE_BLOCKS_BOND",
                      "coverage_posture %s blocks bond issuance" % gate_posture)
        bond["status"] = "ISSUED"
        touch(bond)
        recompute_posture(prod)
        return success_object(serialize(bond))


@bp.route("/productions/<id>/completion-bond/claim", methods=["POST"])
def claim_bond(id):
    require_roles({"SuretyUnderwriter"})
    with db.lock:
        prod = get_production(id)
        bond = require_bond(id)
        if bond["status"] != "ISSUED":
            raise err("ERR_INVALID_STATE",
                      "Bond must be ISSUED to claim (current: %s)" % bond["status"])
        has_qualifying = any(
            cl["production_id"] == id
            and cl["status"] in OPEN_CLAIM_STATUSES
            and cl["loss_amount_cents"] >= bond["strike_price_cents"]
            for cl in db.claims.values()
        )
        if not has_qualifying:
            raise err("ERR_INVALID_STATE",
                      "No open claim reaches the bond strike price")

        bond["status"] = "CLAIMED"
        touch(bond)
        for pol in db.policies.values():
            if (pol["production_id"] == id
                    and pol["status"] in ("QUOTED", "BOUND", "ENDORSED_PENDING", "ACTIVE")):
                pol["status"] = "CANCELLED"
                touch(pol)
        for cert in db.certificates.values():
            if cert["production_id"] == id and cert["status"] in ("DRAFT", "ISSUED"):
                cert["status"] = "VOIDED"
                touch(cert)
        recompute_posture(prod)
        return success_object(serialize(bond))


@bp.route("/productions/<id>/completion-bond/lapse", methods=["POST"])
def lapse_bond(id):
    require_roles({"SuretyUnderwriter"})
    with db.lock:
        get_production(id)
        bond = require_bond(id)
        if bond["status"] not in ("APPLIED", "UNDERWRITTEN"):
            raise err("ERR_INVALID_STATE",
                      "Bond must be APPLIED or UNDERWRITTEN to lapse (current: %s)"
                      % bond["status"])
        bond["status"] = "LAPSED"
        touch(bond)
        return success_object(serialize(bond))
