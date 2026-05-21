"""CNC (Currently Not Collectible) endpoints (§3.11)."""
from __future__ import annotations

from flask import Blueprint

from app.auth import enforce_taxpayer_ownership, require_roles
from app.envelope import success
from app.errors import (
    ERR_CNC_NOT_ELIGIBLE,
    ERR_INVALID_STATE,
    ERR_LIABILITY_NOT_OWNED,
    ERR_NOT_FOUND,
    ERR_VALIDATION,
    raise_error,
)
from app.services.common import bump_version, check_version, init_common_fields
from app.services.csed import close_events_of_kind, open_event
from app.services.liabilities import set_status
from app.services.taxpayers import refresh_taxpayer_aggregates
from app.store import STORE, new_id
from app.timeutil import add_months, fmt, now_iso, parse_iso
from app.util import (
    get_json_body,
    optional_version,
    require_enum,
    require_fields,
    require_list,
    require_str,
)


bp = Blueprint("cnc_statuses", __name__, url_prefix="/collections/cnc-statuses")


HARDSHIPS = ("UNEMPLOYMENT", "MEDICAL", "NEGATIVE_DISPOSABLE_INCOME", "OTHER")


def _serialize(c: dict) -> dict:
    return {
        "id": c["id"],
        "taxpayer_id": c["taxpayer_id"],
        "liability_ids": list(c["liability_ids"]),
        "hardship_reason": c["hardship_reason"],
        "effective_date": c["effective_date"],
        "review_due_date": c["review_due_date"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


@bp.route("", methods=["POST"])
@require_roles("IRSOfficer")
def place_cnc(identity):
    body = get_json_body()
    require_fields(body, ["taxpayer_id", "liability_ids", "hardship_reason"])
    taxpayer_id = require_str(body, "taxpayer_id")
    liab_ids = require_list(body, "liability_ids", min_len=1)
    if any(not isinstance(x, str) for x in liab_ids):
        raise_error(ERR_VALIDATION, "liability_ids must be an array of strings.")
    hardship = require_enum(body, "hardship_reason", HARDSHIPS)

    with STORE.lock:
        tp = STORE.taxpayers.get(taxpayer_id)
        if tp is None:
            raise_error(ERR_NOT_FOUND, f"Taxpayer {taxpayer_id!r} not found.")
        for lid in liab_ids:
            l = STORE.tax_liabilities.get(lid)
            if l is None or l["taxpayer_id"] != taxpayer_id:
                raise_error(ERR_LIABILITY_NOT_OWNED, f"Liability {lid!r} not owned by taxpayer.")
            if l["status"] != "OPEN":
                raise_error(ERR_INVALID_STATE, f"Liability {lid!r} not in OPEN status.")

        # CNC eligibility (priority 22): MDI <= 0
        if tp["monthly_disposable_income_cents"] > 0:
            raise_error(ERR_CNC_NOT_ELIGIBLE,
                        "CNC requires monthly_disposable_income_cents <= 0.")

        effective = now_iso()
        review_due = fmt(add_months(parse_iso(effective), 24))

        cnc = {
            "id": new_id(),
            "taxpayer_id": taxpayer_id,
            "liability_ids": list(liab_ids),
            "hardship_reason": hardship,
            "effective_date": effective,
            "review_due_date": review_due,
            "status": "ACTIVE",
        }
        init_common_fields(cnc)
        STORE.cnc_statuses[cnc["id"]] = cnc

        for lid in liab_ids:
            liab = STORE.tax_liabilities[lid]
            set_status(liab, "CNC")
            open_event(lid, "CNC_HARDSHIP", source_ref=cnc["id"])

        refresh_taxpayer_aggregates(taxpayer_id)
    return success(_serialize(cnc), status=201)


@bp.route("/<cnc_id>/reverse", methods=["POST"])
@require_roles("IRSOfficer")
def reverse_cnc(identity, cnc_id):
    body = get_json_body()
    with STORE.lock:
        cnc = STORE.cnc_statuses.get(cnc_id)
        if cnc is None:
            raise_error(ERR_NOT_FOUND, f"CNC {cnc_id!r} not found.")
        if cnc["status"] != "ACTIVE":
            raise_error(ERR_INVALID_STATE, f"CNC in status {cnc['status']}, cannot reverse.")
        check_version(cnc, optional_version(body))

        cnc["status"] = "REVERSED"
        bump_version(cnc)

        for lid in cnc["liability_ids"]:
            liab = STORE.tax_liabilities.get(lid)
            if liab is None:
                continue
            if liab["status"] == "CNC":
                set_status(liab, "OPEN")
            close_events_of_kind(lid, "CNC_HARDSHIP")

        refresh_taxpayer_aggregates(cnc["taxpayer_id"])
        return success(_serialize(cnc))


@bp.route("/<cnc_id>", methods=["GET"])
@require_roles("IRSOfficer", "Taxpayer")
def get_cnc(identity, cnc_id):
    with STORE.lock:
        cnc = STORE.cnc_statuses.get(cnc_id)
        if cnc is None:
            raise_error(ERR_NOT_FOUND, f"CNC {cnc_id!r} not found.")
        enforce_taxpayer_ownership(identity, cnc["taxpayer_id"])
        return success(_serialize(cnc))
