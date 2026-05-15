"""Borrower CRUD routes."""
from __future__ import annotations

from flask import Flask, request

from ..auth import current_actor, require_auth, verify_borrower_ownership
from ..errors import ApiError
from ..pagination import parse_limit_offset, parse_optional_str
from ..response import success_envelope
from ..services.borrowers import borrower_view, recompute_aggregates
from ..store import bump_version, common_fields_create, get_store, now_iso
from ._helpers import (
    check_version_or_conflict,
    created,
    get_borrower_or_404,
    get_json_body,
    list_ok,
    ok,
)


VALID_VETERAN = {"NONE", "VETERAN", "TPD_VETERAN"}


def _validate_create(body: dict) -> None:
    if not isinstance(body.get("full_name"), str) or not body["full_name"]:
        raise ApiError("ERR_INVALID_INPUT", "full_name is required.")
    ssn = body.get("ssn_last4")
    if not isinstance(ssn, str) or len(ssn) != 4 or not ssn.isdigit():
        raise ApiError("ERR_INVALID_INPUT", "ssn_last4 must be exactly 4 digits.")
    fs = body.get("family_size", 1)
    try:
        fs = int(fs)
    except Exception:
        raise ApiError("ERR_INVALID_INPUT", "family_size must be an integer.")
    if fs < 1:
        raise ApiError("ERR_INVALID_INPUT", "family_size must be >= 1.")
    if "state_code" in body and not isinstance(body["state_code"], str):
        raise ApiError("ERR_INVALID_INPUT", "state_code must be a string.")
    if "adjusted_gross_income_cents" in body:
        try:
            agi = int(body["adjusted_gross_income_cents"])
        except Exception:
            raise ApiError("ERR_INVALID_INPUT", "adjusted_gross_income_cents must be int.")
        if agi < 0:
            raise ApiError("ERR_INVALID_INPUT", "adjusted_gross_income_cents must be >= 0.")
    if "veteran_status" in body and body["veteran_status"] not in VALID_VETERAN:
        raise ApiError("ERR_INVALID_INPUT", "Invalid veteran_status.")


def register(app: Flask) -> None:
    @app.route("/borrowers", methods=["POST"])
    @require_auth("ServicerAdmin")
    def create_borrower():
        body = get_json_body(allow_empty=False)
        _validate_create(body)
        b = {
            **common_fields_create(),
            "full_name": body["full_name"],
            "ssn_last4": body["ssn_last4"],
            "family_size": int(body.get("family_size", 1)),
            "state_code": body.get("state_code"),
            "adjusted_gross_income_cents": int(body.get("adjusted_gross_income_cents", 0)),
            "agi_certified_at": body.get("agi_certified_at"),
            "veteran_status": body.get("veteran_status", "NONE"),
            "aggregate_principal_balance_cents": 0,
            "aggregate_interest_balance_cents": 0,
        }
        get_store().borrowers[b["id"]] = b
        return created(borrower_view(b))

    @app.route("/borrowers", methods=["GET"])
    @require_auth("ServicerAdmin")
    def list_borrowers():
        limit, offset = parse_limit_offset()
        veteran = parse_optional_str("veteran_status")
        all_b = list(get_store().borrowers.values())
        if veteran:
            all_b = [b for b in all_b if b.get("veteran_status") == veteran]
        all_b.sort(key=lambda b: b["created_at"])
        sliced = all_b[offset : offset + limit]
        page = {
            "limit": limit,
            "offset": offset,
            "total_count": len(all_b),
            "has_more": offset + limit < len(all_b),
        }
        return list_ok([borrower_view(b) for b in sliced], page)

    @app.route("/borrowers/<borrower_id>", methods=["GET"])
    @require_auth("ServicerAdmin", "ServicerCertifier", "ServicerApprover", "CollectionsOfficer", "Borrower")
    def get_borrower(borrower_id):
        b = get_borrower_or_404(borrower_id)
        return ok(borrower_view(b))

    @app.route("/borrowers/<borrower_id>", methods=["PATCH"])
    @require_auth("ServicerAdmin", "Borrower")
    def update_borrower(borrower_id):
        b = get_borrower_or_404(borrower_id)
        body = get_json_body()
        check_version_or_conflict(b, body)
        # Validate fields if present.
        if "family_size" in body:
            try:
                fs = int(body["family_size"])
            except Exception:
                raise ApiError("ERR_INVALID_INPUT", "family_size must be an integer.")
            if fs < 1:
                raise ApiError("ERR_INVALID_INPUT", "family_size must be >= 1.")
            b["family_size"] = fs
        if "state_code" in body:
            if not isinstance(body["state_code"], str):
                raise ApiError("ERR_INVALID_INPUT", "state_code must be a string.")
            b["state_code"] = body["state_code"]
        if "adjusted_gross_income_cents" in body:
            try:
                agi = int(body["adjusted_gross_income_cents"])
            except Exception:
                raise ApiError("ERR_INVALID_INPUT", "agi must be int.")
            if agi < 0:
                raise ApiError("ERR_INVALID_INPUT", "agi must be >= 0.")
            if agi != int(b.get("adjusted_gross_income_cents", 0)):
                b["adjusted_gross_income_cents"] = agi
                b["agi_certified_at"] = now_iso()
            else:
                b["adjusted_gross_income_cents"] = agi
        if "veteran_status" in body:
            if body["veteran_status"] not in VALID_VETERAN:
                raise ApiError("ERR_INVALID_INPUT", "Invalid veteran_status.")
            b["veteran_status"] = body["veteran_status"]
        bump_version(b)
        return ok(borrower_view(b))
