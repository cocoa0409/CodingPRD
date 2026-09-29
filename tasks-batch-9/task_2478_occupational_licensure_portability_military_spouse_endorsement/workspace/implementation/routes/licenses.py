"""Minted licences (PRD §3.9, cascade link one)."""
from flask import Blueprint

import db
import response
import serializers
from constants import ALL_ROLES
from middleware import authenticate
from services import lookups

bp = Blueprint("licenses", __name__)


@bp.get("/licensure/licenses/<license_id>")
def read_license(license_id):
    authenticate(ALL_ROLES)
    row = lookups.license_row(license_id)
    return response.object_response(serializers.license_row(row))


@bp.get("/licensure/licenses")
def list_licenses():
    authenticate(ALL_ROLES)
    limit, offset = response.pagination()
    application_id = response.query_string("application_id")
    profession_id = response.query_string("profession_id")
    converted_from_permit_id = response.query_string("converted_from_permit_id")
    rows = []
    for row in db.licenses.values():
        if application_id is not None and row["application_id"] != application_id:
            continue
        if profession_id is not None and row["profession_id"] != profession_id:
            continue
        if (converted_from_permit_id is not None
                and row["converted_from_permit_id"] != converted_from_permit_id):
            continue
        rows.append(row)
    return response.paginate(db.ordered(rows), limit, offset,
                             serializers.license_row)
