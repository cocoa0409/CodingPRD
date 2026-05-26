"""Donor routes."""
from __future__ import annotations

from flask import Flask, request

from db import store, stamp_create
from errors import (
    err,
    ERR_EMAIL_TAKEN,
    ERR_UNSUPPORTED_STATE_CODE,
    ERR_INVALID_REQUEST,
)
from middleware import require_roles
from response import success_object, success_array, parse_pagination, paginate
from validators import must_exist, require_dict, require_str, require_enum


SUPPORTED_STATE_CODES = {"CA", "NY", "IL", "TX", "FL", "OH"}


def _donor_view(donor: dict) -> dict:
    keys = ("id", "created_at", "updated_at", "version", "full_name", "state_code",
            "federal_tax_id_last4", "email")
    return {k: donor[k] for k in keys}


def register(app: Flask) -> None:

    @app.post("/donors")
    @require_roles("CustodianAgent")
    def create_donor():
        body = require_dict(request.get_json(silent=True))
        full_name = require_str(body, "full_name")
        # state_code: domain rule supersedes ERR_INVALID_REQUEST per priority 11.
        if "state_code" not in body or not isinstance(body["state_code"], str):
            raise err(ERR_INVALID_REQUEST, "state_code missing")
        state_code = body["state_code"]
        if state_code not in SUPPORTED_STATE_CODES:
            raise err(ERR_UNSUPPORTED_STATE_CODE, "state_code not supported")
        tax_id = require_str(body, "federal_tax_id_last4")
        if not (tax_id.isdigit() and len(tax_id) == 4):
            raise err(ERR_INVALID_REQUEST, "federal_tax_id_last4 must be exactly 4 digits")
        email = require_str(body, "email")
        if "@" not in email:
            raise err(ERR_INVALID_REQUEST, "email malformed")
        # Uniqueness — case-insensitive.
        lowered = email.lower()
        for existing in store.donors.values():
            if existing["email"].lower() == lowered:
                raise err(ERR_EMAIL_TAKEN, "donor email already exists")
        donor = stamp_create({
            "full_name": full_name,
            "state_code": state_code,
            "federal_tax_id_last4": tax_id,
            "email": email,
        }, store.clock_utc)
        store.donors[donor["id"]] = donor
        return success_object(_donor_view(donor), status=201)

    @app.get("/donors/<donor_id>")
    @require_roles("CustodianAgent", "AccountOwner", "ComplianceOfficer")
    def get_donor(donor_id: str):
        donor = must_exist(store.donors, donor_id, path=True)
        return success_object(_donor_view(donor))

    @app.get("/donors")
    @require_roles("CustodianAgent", "ComplianceOfficer")
    def list_donors():
        limit, offset = parse_pagination(request.args)
        rows = sorted(store.donors.values(), key=lambda d: d["created_at"])
        page, total = paginate(rows, limit, offset)
        return success_array(
            [_donor_view(d) for d in page],
            limit=limit, offset=offset, total_count=total,
        )
