"""Receivership certificates -- the depositors' claims against the estate.

Certificates are only ever created by the certify cascade and only ever mutated
by the dividend waterfall, so the surface here is read-only (PRD section 4).
"""

from flask import Blueprint, request

import db as dbmod
import lookup
import response
import serializers
from auth import ALL_ROLES, require
from db import db

bp = Blueprint("certificates", __name__)


@bp.get("/receivership-certificates")
@require(ALL_ROLES)
def list_certificates():
    rows = list(db.certificates.values())
    for field in (
        "insurance_determination_id",
        "depositor_record_id",
        "institution_id",
        "status",
    ):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    return response.paginated(dbmod.ordered(rows), serializers.certificate)


@bp.get("/receivership-certificates/<certificate_id>")
@require(ALL_ROLES)
def get_certificate(certificate_id):
    return response.ok(serializers.certificate(lookup.certificate(certificate_id)))
