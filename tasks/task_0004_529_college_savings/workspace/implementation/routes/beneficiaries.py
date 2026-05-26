"""Beneficiary routes."""
from __future__ import annotations

from flask import Flask, request

from db import store, stamp_create
from errors import err, ERR_INVALID_REQUEST
from middleware import require_roles
from response import success_object, success_array, parse_pagination, paginate
from validators import must_exist, parse_iso, require_dict, require_enum, require_str


RELATIONSHIP_CLASSES = {"SELF", "CHILD", "SIBLING", "FIRST_COUSIN", "OTHER"}


def _ben_view(b: dict) -> dict:
    keys = ("id", "created_at", "updated_at", "version", "full_name",
            "date_of_birth", "relationship_class", "federal_tax_id_last4")
    return {k: b[k] for k in keys}


def register(app: Flask) -> None:

    @app.post("/beneficiaries")
    @require_roles("CustodianAgent")
    def create_beneficiary():
        body = require_dict(request.get_json(silent=True))
        full_name = require_str(body, "full_name")
        dob = require_str(body, "date_of_birth")
        # Validate format but store the original string for round-trip fidelity.
        parse_iso(dob)
        rel = require_enum(body, "relationship_class", RELATIONSHIP_CLASSES)
        tax_id = require_str(body, "federal_tax_id_last4")
        if not (tax_id.isdigit() and len(tax_id) == 4):
            raise err(ERR_INVALID_REQUEST, "federal_tax_id_last4 must be exactly 4 digits")
        ben = stamp_create({
            "full_name": full_name,
            "date_of_birth": dob,
            "relationship_class": rel,
            "federal_tax_id_last4": tax_id,
        }, store.clock_utc)
        store.beneficiaries[ben["id"]] = ben
        return success_object(_ben_view(ben), status=201)

    @app.get("/beneficiaries/<ben_id>")
    @require_roles("CustodianAgent", "AccountOwner", "ComplianceOfficer")
    def get_beneficiary(ben_id: str):
        ben = must_exist(store.beneficiaries, ben_id, path=True)
        return success_object(_ben_view(ben))

    @app.get("/beneficiaries")
    @require_roles("CustodianAgent", "ComplianceOfficer")
    def list_beneficiaries():
        limit, offset = parse_pagination(request.args)
        rows = sorted(store.beneficiaries.values(), key=lambda b: b["created_at"])
        page, total = paginate(rows, limit, offset)
        return success_array(
            [_ben_view(b) for b in page],
            limit=limit, offset=offset, total_count=total,
        )
