"""Vault endpoints: create, read."""

from flask import Blueprint

from db import store
from errors import validation
from helpers import (
    get_body,
    require_string,
    require_enum,
    require_int,
    make_common_fields,
    get_vault,
)
from middleware import require_roles
from response import success_object

bp = Blueprint("vaults", __name__)

CLIMATE_CLASSES = {"CLIMATE_CONTROLLED", "STANDARD", "COLD_STORAGE"}


def serialize_vault(vault):
    return dict(vault)


@bp.route("/api/vaults", methods=["POST"])
def create_vault():
    user_id, role = require_roles("ProjectManager")
    body = get_body()
    code = require_string(body, "code")
    climate_class = require_enum(body, "climate_class", CLIMATE_CLASSES)
    capacity_cu_ft = require_int(body, "capacity_cu_ft", min_v=1)
    monthly_rate = require_int(body, "monthly_rate_cents_per_cu_ft", min_v=1)
    # global uniqueness of code
    for v in store.vaults.values():
        if v["code"] == code:
            raise validation(f"Vault code '{code}' already exists")
    vault = make_common_fields()
    vault.update({
        "code": code,
        "climate_class": climate_class,
        "capacity_cu_ft": capacity_cu_ft,
        "monthly_rate_cents_per_cu_ft": monthly_rate,
        "occupied_cu_ft": 0,
        "posture": "OPEN",
    })
    store.vaults[vault["id"]] = vault
    return success_object(serialize_vault(vault), status=201)


@bp.route("/api/vaults/<vault_id>", methods=["GET"])
def read_vault(vault_id):
    user_id, role = require_roles("ProjectManager", "InventoryTechnician", "BillingClerk")
    vault = get_vault(vault_id)
    return success_object(serialize_vault(vault))
