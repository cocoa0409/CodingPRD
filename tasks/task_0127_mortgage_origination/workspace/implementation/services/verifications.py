"""IncomeVerification & AssetVerification services (PRD §3.3)."""

from decimal import Decimal

import db
from config import (
    ASSET_TYPES,
    ASSET_VERIFICATION_MIN_CENTS,
    INCOME_SOURCE_TYPES,
    INCOME_VERIFICATION_THRESHOLD,
    VER_PENDING,
    VER_REJECTED,
    VER_VERIFIED,
)
from errors import (
    ERR_INVALID_STATE,
    ERR_RESOURCE_NOT_FOUND,
    raise_error,
)
from services.common import bump, init_common, occ_check
from services.validation import require_enum, require_int


# -------------------------------------------------------------------------
# Income verifications
# -------------------------------------------------------------------------
def income_create(application: dict, body: dict) -> dict:
    source_type = require_enum(body, "source_type", INCOME_SOURCE_TYPES)
    documented_annual_cents = require_int(body, "documented_annual_cents", min_value=0)
    iv = init_common(
        {
            "application_id": application["id"],
            "source_type": source_type,
            "documented_annual_cents": int(documented_annual_cents),
            "status": VER_PENDING,
            "verifier_user_id": None,
        }
    )
    db.income_verifications[iv["id"]] = iv
    return iv


def income_get_or_404(application_id: str, iv_id: str) -> dict:
    iv = db.income_verifications.get(iv_id)
    if iv is None or iv["application_id"] != application_id:
        raise_error(ERR_RESOURCE_NOT_FOUND, "IncomeVerification not found.")
    return iv


def income_verify(application: dict, iv: dict, actor_user_id: str, body: dict) -> dict:
    occ_check(iv, body)
    if iv["status"] != VER_PENDING:
        raise_error(ERR_INVALID_STATE, "IncomeVerification must be PENDING.")
    borrower = db.borrowers.get(application["borrower_id"])
    if borrower is None:
        raise_error(ERR_INVALID_STATE, "Borrower for this application is missing.")
    threshold = (
        Decimal(borrower["annual_income_cents"]) * INCOME_VERIFICATION_THRESHOLD
    )
    if Decimal(iv["documented_annual_cents"]) < threshold:
        raise_error(
            ERR_INVALID_STATE,
            "documented_annual_cents must be at least 80% of borrower stated income.",
        )
    iv["status"] = VER_VERIFIED
    iv["verifier_user_id"] = actor_user_id
    bump(iv)
    return iv


def income_reject(iv: dict, body: dict) -> dict:
    occ_check(iv, body)
    if iv["status"] != VER_PENDING:
        raise_error(ERR_INVALID_STATE, "IncomeVerification must be PENDING.")
    iv["status"] = VER_REJECTED
    bump(iv)
    return iv


# -------------------------------------------------------------------------
# Asset verifications
# -------------------------------------------------------------------------
def asset_create(application: dict, body: dict) -> dict:
    asset_type = require_enum(body, "asset_type", ASSET_TYPES)
    balance_cents = require_int(body, "balance_cents", min_value=0)
    av = init_common(
        {
            "application_id": application["id"],
            "asset_type": asset_type,
            "balance_cents": int(balance_cents),
            "status": VER_PENDING,
            "verifier_user_id": None,
        }
    )
    db.asset_verifications[av["id"]] = av
    return av


def asset_get_or_404(application_id: str, av_id: str) -> dict:
    av = db.asset_verifications.get(av_id)
    if av is None or av["application_id"] != application_id:
        raise_error(ERR_RESOURCE_NOT_FOUND, "AssetVerification not found.")
    return av


def asset_verify(av: dict, actor_user_id: str, body: dict) -> dict:
    occ_check(av, body)
    if av["status"] != VER_PENDING:
        raise_error(ERR_INVALID_STATE, "AssetVerification must be PENDING.")
    if av["balance_cents"] < ASSET_VERIFICATION_MIN_CENTS:
        raise_error(ERR_INVALID_STATE, "balance_cents must be >= 1000.")
    av["status"] = VER_VERIFIED
    av["verifier_user_id"] = actor_user_id
    bump(av)
    return av


def asset_reject(av: dict, body: dict) -> dict:
    occ_check(av, body)
    if av["status"] != VER_PENDING:
        raise_error(ERR_INVALID_STATE, "AssetVerification must be PENDING.")
    av["status"] = VER_REJECTED
    bump(av)
    return av
