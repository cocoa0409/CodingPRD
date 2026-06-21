"""ClosingDisclosure service — DRAFT -> DELIVERED -> [REISSUED] -> ACKNOWLEDGED."""
from __future__ import annotations

import datetime as dt
from typing import Any

from calculations import CD_WAIT_PERIOD_HOURS, cd_reissue_is_material
from clock import CLOCK
from db import DB_INSTANCE, new_id
from errors import (
    ERR_CD_REISSUE_NOT_MATERIAL,
    ERR_CD_THREE_DAY_NOT_ELAPSED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_STALE_AGREEMENT_VERSION,
    err,
)
from lookup import (
    get_cd_or_404,
    get_fk_agreement,
)
from validation import (
    require_bool,
    require_enum,
    require_fields,
    require_int,
    require_str,
)


CD_PRODUCT_TYPES = {"FIXED", "ARM", "IO", "BALLOON"}


def create_cd(body: dict) -> dict:
    require_fields(body, [
        "agreement_id",
        "expected_agreement_version",
        "cd_apr_bps",
        "cd_total_loan_amount_cents",
        "cd_monthly_payment_cents",
        "cd_product_type",
        "cd_prepayment_penalty",
    ])
    agreement_id = require_str(body, "agreement_id")
    expected_version = require_int(body, "expected_agreement_version")
    cd_apr_bps = require_int(body, "cd_apr_bps")
    cd_total = require_int(body, "cd_total_loan_amount_cents")
    cd_monthly = require_int(body, "cd_monthly_payment_cents")
    cd_product_type = require_enum(body, "cd_product_type", CD_PRODUCT_TYPES)
    cd_prepayment_penalty = require_bool(body, "cd_prepayment_penalty")

    # FK check.
    a = get_fk_agreement(agreement_id)

    # PRD §3.4: draft CD is created against an agreement that is UNDER_CONTRACT.
    if a["status"] != "UNDER_CONTRACT":
        raise err(ERR_INVALID_STATE, "agreement must be UNDER_CONTRACT to draft a closing disclosure")

    # Priority 6 OCC.
    if expected_version != a["version"]:
        raise err(ERR_STALE_AGREEMENT_VERSION, "expected_agreement_version mismatch")

    now = CLOCK.now()
    cd = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "agreement_id": agreement_id,
        "issued_at": None,
        "cd_apr_bps": cd_apr_bps,
        "cd_total_loan_amount_cents": cd_total,
        "cd_monthly_payment_cents": cd_monthly,
        "cd_product_type": cd_product_type,
        "cd_prepayment_penalty": cd_prepayment_penalty,
        "status": "DRAFT",
        "earliest_consummation_at": None,
        "acknowledged_at": None,
    }
    DB_INSTANCE.closing_disclosures[cd["id"]] = cd

    # OCC-pinned write bumps the parent's version.
    a["version"] += 1
    a["updated_at"] = CLOCK.now()
    return cd


def deliver_cd(cd_id: str) -> dict:
    cd = get_cd_or_404(cd_id)
    if cd["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "closing disclosure is not in DRAFT")
    a = DB_INSTANCE.purchase_agreements.get(cd["agreement_id"])
    if a is None or a["status"] != "UNDER_CONTRACT":
        raise err(ERR_INVALID_STATE, "agreement must be UNDER_CONTRACT to deliver a closing disclosure")
    issued = CLOCK.now()
    cd["issued_at"] = issued
    cd["earliest_consummation_at"] = issued + dt.timedelta(hours=CD_WAIT_PERIOD_HOURS)
    cd["status"] = "DELIVERED"
    cd["updated_at"] = CLOCK.now()
    cd["version"] += 1
    return cd


def reissue_cd(cd_id: str, body: dict) -> dict:
    cd = get_cd_or_404(cd_id)
    if cd["status"] != "DELIVERED":
        raise err(ERR_INVALID_STATE, "closing disclosure is not in DELIVERED")

    req_apr = body.get("cd_apr_bps")
    req_product = body.get("cd_product_type")
    req_penalty = body.get("cd_prepayment_penalty")

    # Type-check optional fields.
    if req_apr is not None:
        if isinstance(req_apr, bool) or not isinstance(req_apr, int):
            raise err(ERR_INVALID_REQUEST, "cd_apr_bps must be an integer")
    if req_product is not None:
        if not isinstance(req_product, str) or req_product not in CD_PRODUCT_TYPES:
            raise err(ERR_INVALID_REQUEST, f"cd_product_type must be one of {sorted(CD_PRODUCT_TYPES)}")
    if req_penalty is not None:
        if not isinstance(req_penalty, bool):
            raise err(ERR_INVALID_REQUEST, "cd_prepayment_penalty must be a boolean")

    # Priority 10: business_safety — must be a material change.
    is_material = cd_reissue_is_material(
        current_apr_bps=cd["cd_apr_bps"],
        current_product_type=cd["cd_product_type"],
        current_prepayment_penalty=cd["cd_prepayment_penalty"],
        req_apr_bps=req_apr,
        req_product_type=req_product,
        req_prepayment_penalty=req_penalty,
    )
    if not is_material:
        raise err(ERR_CD_REISSUE_NOT_MATERIAL, "reissue body produced no material change")

    # Apply field updates.
    if req_apr is not None:
        cd["cd_apr_bps"] = req_apr
    if req_product is not None:
        cd["cd_product_type"] = req_product
    if req_penalty is not None:
        cd["cd_prepayment_penalty"] = req_penalty

    issued = CLOCK.now()
    cd["issued_at"] = issued
    cd["earliest_consummation_at"] = issued + dt.timedelta(hours=CD_WAIT_PERIOD_HOURS)
    cd["status"] = "REISSUED"
    cd["updated_at"] = CLOCK.now()
    cd["version"] += 1
    return cd


def acknowledge_cd(cd_id: str) -> dict:
    cd = get_cd_or_404(cd_id)
    if cd["status"] not in ("DELIVERED", "REISSUED"):
        raise err(ERR_INVALID_STATE, "closing disclosure must be DELIVERED or REISSUED to acknowledge")
    if cd["earliest_consummation_at"] is None:
        raise err(ERR_INVALID_STATE, "earliest_consummation_at not stamped")
    if CLOCK.now() < cd["earliest_consummation_at"]:
        raise err(ERR_CD_THREE_DAY_NOT_ELAPSED, "72-hour wait has not yet elapsed")
    cd["acknowledged_at"] = CLOCK.now()
    cd["status"] = "ACKNOWLEDGED"
    cd["updated_at"] = CLOCK.now()
    cd["version"] += 1
    return cd


def list_cds(filters: dict[str, Any]) -> list[dict]:
    items = list(DB_INSTANCE.closing_disclosures.values())
    if filters.get("agreement_id"):
        items = [cd for cd in items if cd["agreement_id"] == filters["agreement_id"]]
    if filters.get("status"):
        items = [cd for cd in items if cd["status"] == filters["status"]]
    items.sort(key=lambda cd: cd["created_at"])
    return items
