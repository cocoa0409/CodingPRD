"""Distributor accounts and the credit ledger (PRD 3.1)."""

from flask import Blueprint

import envelope
import serializers
from auth import ALL_READ_ROLES, authorized
from errors import ERR_VALIDATION, raise_error
from store import db, stamp_new, touch
from validate import (
    check_allowed_fields,
    get_body,
    req_enum,
    req_int,
    req_number,
    req_str,
)
from services import get_or_404

bp = Blueprint("distributors", __name__)

EMISSIONS_REQUIREMENTS = {"FEDERAL", "CALIFORNIA"}
DISTRIBUTOR_STATUSES = {"ACTIVE", "CREDIT_HOLD"}


@bp.route("/distributors", methods=["POST"])
def create_distributor():
    authorized(["PlantAdmin"])
    body = get_body()
    check_allowed_fields(
        body,
        [
            "distributor_code",
            "name",
            "emissions_requirement",
            "credit_limit_cents",
            "volume_discount_pct",
        ],
    )
    distributor_code = req_str(body, "distributor_code")
    name = req_str(body, "name")
    emissions_requirement = req_enum(body, "emissions_requirement", EMISSIONS_REQUIREMENTS)
    credit_limit_cents = req_int(body, "credit_limit_cents", minimum=0)
    volume_discount_pct = req_number(body, "volume_discount_pct", minimum=0, maximum=0.5)

    for existing in db.distributors.values():
        if existing["distributor_code"] == distributor_code:
            raise_error(
                ERR_VALIDATION,
                "distributor_code %s is already registered" % distributor_code,
            )

    record = {
        "distributor_code": distributor_code,
        "name": name,
        "emissions_requirement": emissions_requirement,
        "status": "ACTIVE",
        "credit_limit_cents": credit_limit_cents,
        "volume_discount_pct": volume_discount_pct,
        "credit_balance_cents": 0,
    }
    stamp_new(record)  # status ACTIVE, both ledger fields 0, version 1
    db.distributors[record["id"]] = record
    return envelope.created(serializers.distributor(record))


@bp.route("/distributors/<rid>", methods=["GET"])
def get_distributor(rid):
    authorized(ALL_READ_ROLES)
    record = get_or_404("distributors", rid)
    return envelope.ok(serializers.distributor(record))


@bp.route("/distributors/<rid>", methods=["PATCH"])
def patch_distributor(rid):
    authorized(["PlantAdmin"])
    body = get_body()
    check_allowed_fields(body, ["credit_limit_cents", "volume_discount_pct", "status"])
    record = get_or_404("distributors", rid)

    if "credit_limit_cents" in body:
        record["credit_limit_cents"] = req_int(body, "credit_limit_cents", minimum=0)
    if "volume_discount_pct" in body:
        record["volume_discount_pct"] = req_number(
            body, "volume_discount_pct", minimum=0, maximum=0.5
        )
    if "status" in body:
        # ACTIVE <-> CREDIT_HOLD moves freeze / re-enable purchases.
        record["status"] = req_enum(body, "status", DISTRIBUTOR_STATUSES)

    touch(record)  # each update increments version by 1
    return envelope.ok(serializers.distributor(record))
