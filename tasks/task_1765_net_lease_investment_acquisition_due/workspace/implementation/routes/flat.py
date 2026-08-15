"""Flat cross-deal query/read surface (PRD §3.12) — FK reverse-reachability
and reporting. Read-only."""

from flask import Blueprint, request

import db
from middleware import require_role
from response import ok, ok_list
from services import domain

bp = Blueprint("flat", __name__)

ALL_ROLES = ("AcquisitionsAnalyst", "UnderwritingCommittee", "DueDiligenceOfficer",
             "CapitalMarketsOfficer", "EscrowOfficer", "AssetManager", "PlatformAdmin")
MODEL_ROLES = ("AcquisitionsAnalyst", "UnderwritingCommittee", "PlatformAdmin")
DD_ROLES = ("AcquisitionsAnalyst", "UnderwritingCommittee", "DueDiligenceOfficer",
            "PlatformAdmin")
CLOSING_ROLES = ("AcquisitionsAnalyst", "UnderwritingCommittee", "EscrowOfficer",
                 "AssetManager", "CapitalMarketsOfficer", "PlatformAdmin")
TRUEUP_ROLES = ("AcquisitionsAnalyst", "UnderwritingCommittee", "EscrowOfficer",
                "AssetManager", "PlatformAdmin")


def _filter(items, params):
    for param in params:
        v = request.args.get(param)
        if v is not None:
            items = [r for r in items if str(r.get(param)) == v]
    return items


# --- properties -------------------------------------------------------------
@bp.route("/acquisition-deals/properties/<prop_id>", methods=["GET"])
def get_property_flat(prop_id):
    require_role(*ALL_ROLES)
    return ok(db.pub(domain.get_property_flat(prop_id)))


@bp.route("/acquisition-deals/properties", methods=["GET"])
def list_properties_flat():
    require_role(*ALL_ROLES)
    items = _filter(list(db.stores["properties"].values()), ("deal_id", "status"))
    return ok_list(items)


# --- leases -----------------------------------------------------------------
@bp.route("/acquisition-deals/leases/<lease_id>", methods=["GET"])
def get_lease_flat(lease_id):
    require_role(*ALL_ROLES)
    return ok(db.pub(domain.get_lease_flat(lease_id)))


@bp.route("/acquisition-deals/leases", methods=["GET"])
def list_leases_flat():
    require_role(*ALL_ROLES)
    items = _filter(list(db.stores["leases"].values()), ("property_id", "tenant_id", "status"))
    return ok_list(items)


# --- underwriting models ------------------------------------------------------
@bp.route("/acquisition-deals/underwriting-models/<model_id>", methods=["GET"])
def get_model_flat(model_id):
    require_role(*MODEL_ROLES)
    return ok(db.pub(domain.get_model_flat(model_id)))


@bp.route("/acquisition-deals/underwriting-models", methods=["GET"])
def list_models_flat():
    require_role(*MODEL_ROLES)
    items = _filter(list(db.stores["models"].values()), ("deal_id", "status"))
    return ok_list(items)


# --- title reviews / exceptions ---------------------------------------------
@bp.route("/acquisition-deals/title-reviews/<review_id>", methods=["GET"])
def get_title_review_flat(review_id):
    require_role(*DD_ROLES)
    return ok(db.pub(domain.get_title_review_flat(review_id)))


@bp.route("/acquisition-deals/title-exceptions/<ex_id>", methods=["GET"])
def get_exception_flat(ex_id):
    require_role(*DD_ROLES)
    return ok(db.pub(domain.get_exception_flat(ex_id)))


@bp.route("/acquisition-deals/title-exceptions", methods=["GET"])
def list_exceptions_flat():
    require_role(*DD_ROLES)
    items = _filter(list(db.stores["title_exceptions"].values()),
                    ("title_review_id", "cured_by_exception_id", "status", "severity"))
    return ok_list(items)


# --- estoppels ----------------------------------------------------------------
@bp.route("/acquisition-deals/estoppels/<estoppel_id>", methods=["GET"])
def get_estoppel_flat(estoppel_id):
    require_role(*DD_ROLES)
    return ok(db.pub(domain.get_estoppel_flat(estoppel_id)))


@bp.route("/acquisition-deals/estoppels", methods=["GET"])
def list_estoppels_flat():
    require_role(*DD_ROLES)
    items = _filter(list(db.stores["estoppels"].values()),
                    ("lease_id", "tenant_id", "deal_id", "status"))
    return ok_list(items)


# --- sndas --------------------------------------------------------------------
@bp.route("/acquisition-deals/sndas/<snda_id>", methods=["GET"])
def get_snda_flat(snda_id):
    require_role(*DD_ROLES)
    return ok(db.pub(domain.get_snda_flat(snda_id)))


@bp.route("/acquisition-deals/sndas", methods=["GET"])
def list_sndas_flat():
    require_role(*DD_ROLES)
    items = _filter(list(db.stores["sndas"].values()), ("lease_id", "deal_id", "status"))
    return ok_list(items)


# --- closing statements ---------------------------------------------------------
@bp.route("/acquisition-deals/closing-statements/<stmt_id>", methods=["GET"])
def get_statement_flat(stmt_id):
    require_role(*CLOSING_ROLES)
    return ok(db.pub(domain.get_statement_flat(stmt_id)))


@bp.route("/acquisition-deals/closing-statements", methods=["GET"])
def list_statements_flat():
    require_role(*CLOSING_ROLES)
    items = _filter(list(db.stores["statements"].values()), ("deal_id", "status"))
    return ok_list(items)


# --- prorations -----------------------------------------------------------------
@bp.route("/acquisition-deals/prorations/<proration_id>", methods=["GET"])
def get_proration_flat(proration_id):
    require_role(*CLOSING_ROLES)
    return ok(db.pub(domain.get_proration_flat(proration_id)))


@bp.route("/acquisition-deals/prorations", methods=["GET"])
def list_prorations_flat():
    require_role(*CLOSING_ROLES)
    items = _filter(list(db.stores["prorations"].values()),
                    ("closing_statement_id", "lease_id", "line_type"))
    return ok_list(items)


# --- true-up adjustments ----------------------------------------------------------
@bp.route("/acquisition-deals/true-up-adjustments/<adj_id>", methods=["GET"])
def get_trueup_flat(adj_id):
    require_role(*TRUEUP_ROLES)
    return ok(db.pub(domain.get_trueup_flat(adj_id)))


@bp.route("/acquisition-deals/true-up-adjustments", methods=["GET"])
def list_trueups_flat():
    require_role(*TRUEUP_ROLES)
    items = _filter(list(db.stores["true_ups"].values()), ("closing_statement_id", "status"))
    return ok_list(items)
