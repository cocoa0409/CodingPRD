"""Third-party appraisal support and its adjudication (PRD Section 3.4)."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import enums
import serializers as ser
import validators as v
from db import clock_date, db, stamp_new, touch
from errors import ApiError, bad_request
from lookups import get_lease, get_resource, paged
from middleware import endpoint, require_tenant_scope
from response import object_response
from services import calc
from services.compliance import open_fmv_deviation_case
from routes.leases import _occ_check, _open_lease_guard

bp = Blueprint("appraisals", __name__)

TWO = Decimal("2")


@bp.post("/leases/<lease_id>/appraisals")
@endpoint("ComplianceOfficer")
def file_appraisal(lease_id):
    body = v.json_body()
    expected = v.get_int(body, "expected_lease_version", minimum=0)
    firm = v.get_string(body, "appraiser_firm")
    appraisal_date = v.get_date(body, "appraisal_date")
    low = v.get_money(body, "opinion_low_psf", allow_zero=False)
    high = v.get_money(body, "opinion_high_psf", allow_zero=False)
    if high < low:
        raise bad_request("Field 'opinion_high_psf' must be at least 'opinion_low_psf'.")
    independence = v.get_bool(body, "independence_attested")
    if appraisal_date > clock_date():
        raise bad_request("Field 'appraisal_date' may not be later than the clock date.")

    lease = get_lease(lease_id)
    _occ_check(expected, lease)
    _open_lease_guard(lease)

    row = {
        "lease_id": lease["id"],
        "appraiser_firm": firm,
        "appraisal_date": appraisal_date,
        "expires_on": appraisal_date + timedelta(days=calc.APPRAISAL_VALIDITY_DAYS),
        "opinion_low_psf": low,
        "opinion_high_psf": high,
        "opinion_midpoint_psf": calc.q2((low + high) / TWO),
        "independence_attested": independence,
        "status": "SUBMITTED",
        "is_controlling": False,
        "decision_reason": None,
    }
    stamp_new(row)
    db.appraisals[row["id"]] = row
    # The lease now has new evidence attached to it (PRD Section 3.4).
    touch(lease)
    return object_response(ser.appraisal_out(row), 201)


@bp.get("/leases/<lease_id>/appraisals")
@endpoint()
def list_appraisals(lease_id):
    limit, offset = v.pagination()
    status = v.query_enum("status", enums.APPRAISAL_STATUSES)
    lease = get_lease(lease_id)
    require_tenant_scope(lease["tenant_id"])
    rows = calc.appraisals_of_lease(lease["id"])
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    return paged(rows, ser.appraisal_out, limit, offset)


@bp.post("/appraisals/<appraisal_id>/decision")
@endpoint("ComplianceOfficer")
def adjudicate_appraisal(appraisal_id):
    body = v.json_body()
    action = v.get_enum(body, "action", enums.APPRAISAL_ACTIONS)
    reason = v.get_string(body, "decision_reason")

    appraisal = get_resource(db.appraisals, appraisal_id, "Appraisal")
    admissible = ("SUBMITTED",) if action == "QUALIFY" else ("SUBMITTED", "QUALIFIED")
    if appraisal["status"] not in admissible:
        raise ApiError(
            "ERR_INVALID_RECORD_STATE",
            "Appraisal '%s' is in status %s; %s admits only %s."
            % (appraisal["id"], appraisal["status"], action, ", ".join(admissible)),
        )
    lease = db.leases[appraisal["lease_id"]]

    if action == "QUALIFY":
        if not appraisal["independence_attested"]:
            raise ApiError(
                "ERR_APPRAISAL_INDEPENDENCE_MISSING",
                "Appraisal '%s' carries no attestation of independence." % appraisal["id"],
            )
        if appraisal["expires_on"] < clock_date():
            raise ApiError(
                "ERR_INVALID_RECORD_STATE",
                "Appraisal '%s' expired on %s and cannot be qualified retroactively."
                % (appraisal["id"], appraisal["expires_on"].isoformat()),
            )
        _open_lease_guard(lease)
        appraisal["status"] = "QUALIFIED"
        appraisal["decision_reason"] = reason
        touch(appraisal)
        return object_response(ser.appraisal_out(appraisal))

    # --- DISQUALIFY: the blast radius depends on what the row was doing ---
    was_controlling = appraisal["is_controlling"]
    appraisal["status"] = "DISQUALIFIED"
    appraisal["decision_reason"] = reason
    appraisal["is_controlling"] = False
    touch(appraisal)

    if was_controlling:
        if lease["status"] == "FMV_CERTIFIED":
            lease["fmv_certification_status"] = "STALE"
            lease["status"] = "DRAFT"
            lease["revision_round"] += 1
            lease["certified_fmv_floor_psf"] = None
            lease["certified_fmv_ceiling_psf"] = None
            lease["certified_base_rent_annual"] = None
            lease["fmv_variance_annual"] = None
            lease["fmv_variance_pct"] = None
            calc.apply_rent_variant(lease)
            touch(lease)
        elif lease["status"] in calc.OCCUPYING_LEASE_STATUSES:
            # The space is already committed, so the lease status is not rolled
            # back; the system raises a case on its own initiative instead.
            lease["fmv_certification_status"] = "STALE"
            touch(lease)
            open_fmv_deviation_case(
                lease,
                severity="HIGH",
                basis="Controlling appraisal %s disqualified on an occupied lease %s."
                % (appraisal["id"], lease["id"]),
            )
    return object_response(ser.appraisal_out(appraisal))
