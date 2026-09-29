"""POST /reporting-portals."""

from flask import Blueprint

import db
import serializers as s
import validators as v
from auth import authenticate
from response import created

bp = Blueprint("portals", __name__)

SUBMISSION_FORMATS = ("WH347_PDF", "XML_LCP", "CSV_FLAT")


@bp.route("/reporting-portals", methods=["POST"])
def create_portal():
    authenticate(["PortalAdmin"])
    payload = v.body()
    portal_code = v.req_string(payload, "portal_code", min_len=3, max_len=40)
    submission_format = v.req_enum(payload, "submission_format", SUBMISSION_FORMATS)
    cutoff_offset_days = v.req_int(payload, "cutoff_offset_days", minimum=1, maximum=21)
    grace_hours = v.opt_int(payload, "grace_hours", default=0, minimum=0, maximum=72)
    requires_notarized = v.req_bool(payload, "requires_notarized_statement", default=False)

    v.unique_or_reject(
        db.reporting_portals,
        lambda r: r["portal_code"] == portal_code,
        "portal_code must be unique across all portals.",
    )

    row = db.base_row(versioned=False)
    row.update(
        {
            "portal_code": portal_code,
            "submission_format": submission_format,
            "cutoff_offset_days": cutoff_offset_days,
            "grace_hours": grace_hours,
            "requires_notarized_statement": requires_notarized,
        }
    )
    db.reporting_portals[row["id"]] = row
    return created(s.portal(row))
