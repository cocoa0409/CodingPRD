"""DeterminationEvidence endpoint (PRD §3.1). Append-only."""
from flask import Blueprint

from constants import (
    EVIDENCE_KINDS,
    FACTOR_CODES,
    MEASUREMENT_METHODS,
    RATINGS,
    ROLE_COMPLIANCE_OFFICER,
    SAMPLE_FIELDS,
)
from db import db
from errors import fail
from helpers import base_row, bump_service, resolve_body_fk
from middleware import (
    authenticate,
    body,
    opt_bool,
    opt_string,
    req_datetime,
    req_enum,
    req_int,
)
from response import created
from serializers import evidence_out

bp = Blueprint("evidence", __name__)

DESIGN_ONLY_FIELDS = ("factor_code", "rating")


def _present(data, key):
    return key in data and data.get(key) is not None


@bp.post("/determination-evidence")
@authenticate(ROLE_COMPLIANCE_OFFICER)
def create_evidence():
    data = body()
    service = resolve_body_fk("service", data, "service_id")

    evidence_kind = req_enum(data, "evidence_kind", EVIDENCE_KINDS)

    # evidence_kind discriminates two mutually exclusive field groups; supplying
    # the wrong group is ERR_EVIDENCE_FIELDS_MISMATCH (PRD §3.1).
    if evidence_kind == "AUDIENCE_SAMPLE":
        for field in SAMPLE_FIELDS:
            if not _present(data, field):
                fail(
                    "ERR_EVIDENCE_FIELDS_MISMATCH",
                    "%s is required for an AUDIENCE_SAMPLE row." % field,
                )
        for field in DESIGN_ONLY_FIELDS:
            if _present(data, field):
                fail(
                    "ERR_EVIDENCE_FIELDS_MISMATCH",
                    "%s must be absent on an AUDIENCE_SAMPLE row." % field,
                )
    else:
        for field in DESIGN_ONLY_FIELDS:
            if not _present(data, field):
                fail(
                    "ERR_EVIDENCE_FIELDS_MISMATCH",
                    "%s is required for a DESIGN_FACTOR row." % field,
                )
        for field in SAMPLE_FIELDS:
            if _present(data, field):
                fail(
                    "ERR_EVIDENCE_FIELDS_MISMATCH",
                    "%s must be absent on a DESIGN_FACTOR row." % field,
                )

    row = base_row(with_version=False)
    row.update(
        {
            "service_id": service["id"],
            "evidence_kind": evidence_kind,
            "measurement_method": None,
            "period_start": None,
            "period_end": None,
            "total_users": None,
            "users_under_13": None,
            "sample_verified": opt_bool(data, "sample_verified", False),
            "factor_code": None,
            "rating": None,
            "evidence_note": opt_string(data, "evidence_note"),
        }
    )

    if evidence_kind == "AUDIENCE_SAMPLE":
        measurement_method = req_enum(data, "measurement_method", MEASUREMENT_METHODS)
        period_start = req_datetime(data, "period_start")
        period_end = req_datetime(data, "period_end")
        total_users = req_int(data, "total_users")
        users_under_13 = req_int(data, "users_under_13")
        if total_users < 1:
            fail("ERR_INVALID_REQUEST", "total_users must be at least 1.")
        if users_under_13 < 0 or users_under_13 > total_users:
            fail(
                "ERR_INVALID_REQUEST",
                "users_under_13 must be between 0 and total_users.",
            )
        if period_end <= period_start:
            fail("ERR_INVALID_PERIOD", "period_end must be later than period_start.")

        # Half-open [period_start, period_end): touching endpoints are allowed.
        for existing in db.determination_evidence.values():
            if (
                existing["service_id"] == service["id"]
                and existing["evidence_kind"] == "AUDIENCE_SAMPLE"
                and existing["measurement_method"] == measurement_method
                and period_start < existing["period_end"]
                and existing["period_start"] < period_end
            ):
                fail("ERR_SAMPLE_PERIOD_OVERLAP")

        row.update(
            {
                "measurement_method": measurement_method,
                "period_start": period_start,
                "period_end": period_end,
                "total_users": total_users,
                "users_under_13": users_under_13,
            }
        )
    else:
        row["factor_code"] = req_enum(data, "factor_code", FACTOR_CODES)
        row["rating"] = req_enum(data, "rating", RATINGS)

    service["evidence_sequence_counter"] += 1
    row["evidence_sequence"] = service["evidence_sequence_counter"]
    db.determination_evidence[row["id"]] = row

    # design_score / audience_child_share are derived on read; the determination
    # axis is deliberately NOT touched here.
    bump_service(service)
    return created(evidence_out(row))
