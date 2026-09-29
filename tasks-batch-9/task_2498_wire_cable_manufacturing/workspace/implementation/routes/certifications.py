"""Listing agency files, follow-up inspections and reinstatement (PRD 3.3)."""

from flask import Blueprint

import clock
import constants as C
import errors
import lookups
import response
import validation
from auth import require_auth
from db import db, new_record, sort_created, touch
from serializers import view, views
from services import cascades
from util import add_days, day_diff, parse_ymd

bp = Blueprint("certifications", __name__)


def _inspections_for(cert_id):
    return [r for r in db.factory_inspections.values() if r["certification_id"] == cert_id]


def _inspection_order_key(row):
    return (row["inspection_date"], row["created_at"], row["_seq"])


def _latest_inspection(cert_id):
    rows = _inspections_for(cert_id)
    if not rows:
        return None
    rows.sort(key=_inspection_order_key)
    return rows[-1]


@bp.route("/listing-certifications", methods=["POST"])
def create_certification():
    require_auth("CertificationOfficer", "PlantAdmin")
    b = validation.body()
    agency = validation.f_enum(b, "agency", C.AGENCIES)
    file_number = validation.f_str(b, "file_number")
    family = validation.f_str(b, "product_family_code")
    initial_listing_date = validation.f_date(b, "initial_listing_date")
    interval = validation.f_int(b, "inspection_interval_days", required=False, default=90, ge=30)

    rec = new_record()
    rec.update({
        "agency": agency,
        "file_number": file_number,
        "product_family_code": family,
        "initial_listing_date": initial_listing_date,
        "inspection_interval_days": interval,
        "last_inspection_date": None,
        "next_inspection_due_date": None,
        "open_variation_count": 0,
        "status": "PENDING",
    })
    db.listing_certifications[rec["id"]] = rec
    return response.created(view("listing_certification", rec))


@bp.route("/listing-certifications/<cert_id>", methods=["GET"])
def get_certification(cert_id):
    require_auth("CertificationOfficer", "ProcessEngineer", "QualityEngineer", "PlantAdmin")
    rec = lookups.certification(cert_id)
    return response.ok(view("listing_certification", rec))


@bp.route("/listing-certifications/<cert_id>/inspections", methods=["POST"])
def create_inspection(cert_id):
    require_auth("CertificationOfficer", "PlantAdmin")
    b = validation.body()
    inspection_date = validation.f_date(b, "inspection_date")
    inspector_code = validation.f_str(b, "inspector_code")
    findings_count = validation.f_int(b, "findings_count", ge=0)
    outcome = validation.f_enum(b, "outcome", C.INSPECTION_OUTCOMES)

    cert = lookups.certification(cert_id)
    status = cert["status"]
    prior_open_variations = cert["open_variation_count"]

    # Rung 7: is this outcome admissible against the file's current status?
    if status == "SUSPENDED":
        errors.fail(
            errors.ERR_INVALID_CERTIFICATION_STATE,
            "No inspection may be recorded against a SUSPENDED listing file",
        )
    if status == "PENDING":
        if outcome != "PASS":
            errors.fail(
                errors.ERR_INVALID_CERTIFICATION_STATE,
                "A PENDING listing file accepts only a PASS initial listing audit",
            )
        if parse_ymd(inspection_date) < parse_ymd(cert["initial_listing_date"]):
            errors.fail(
                errors.ERR_INVALID_CERTIFICATION_STATE,
                "The initial listing audit may not predate initial_listing_date",
            )

    # Rung 19: the agency's cadence guard.
    if cert["last_inspection_date"] is not None:
        if day_diff(inspection_date, cert["last_inspection_date"]) < C.INSPECTION_MIN_GAP_DAYS:
            errors.fail(
                errors.ERR_INSPECTION_WINDOW_CONFLICT,
                "A follow-up visit must fall at least %d days after %s"
                % (C.INSPECTION_MIN_GAP_DAYS, cert["last_inspection_date"]),
            )

    row = new_record()
    row.update({
        "certification_id": cert["id"],
        "inspection_date": inspection_date,
        "inspector_code": inspector_code,
        "findings_count": findings_count,
        "outcome": outcome,
        "corrective_action_due_date": (
            None if outcome == "PASS" else add_days(inspection_date, C.CAP_DAYS).isoformat()
        ),
        "status": "CLOSED" if outcome == "PASS" else "OPEN",
    })
    db.factory_inspections[row["id"]] = row

    # Cadence fields and the open-variation tally.
    latest = _latest_inspection(cert["id"])
    cert["last_inspection_date"] = latest["inspection_date"]
    cert["next_inspection_due_date"] = add_days(
        latest["inspection_date"], cert["inspection_interval_days"]
    ).isoformat()
    cert["open_variation_count"] = len(
        [r for r in _inspections_for(cert["id"]) if r["status"] == "OPEN"]
    )

    # The file's own status then follows the outcome.
    suspended_now = False
    if status == "PENDING" and outcome == "PASS":
        cert["status"] = "ACTIVE"
    elif status == "ACTIVE" and outcome == "VARIATION":
        cert["status"] = "VARIATION_NOTICE"
    elif status == "ACTIVE" and outcome == "SUSPEND":
        cert["status"] = "SUSPENDED"
        suspended_now = True
    elif status == "VARIATION_NOTICE" and outcome == "SUSPEND":
        cert["status"] = "SUSPENDED"
        suspended_now = True
    elif status == "VARIATION_NOTICE" and outcome == "VARIATION":
        # The escalation reads the tally as it stood before this visit.
        if prior_open_variations >= 1:
            cert["status"] = "SUSPENDED"
            suspended_now = True
    touch(cert)

    if suspended_now:
        cascades.certification_suspended(cert)

    return response.created(view("factory_inspection", row))


@bp.route("/listing-certifications/<cert_id>/inspections", methods=["GET"])
def list_inspections(cert_id):
    require_auth("CertificationOfficer", "ProcessEngineer", "QualityEngineer", "PlantAdmin")
    limit, offset = validation.pagination()
    outcome = validation.q_enum("outcome", C.INSPECTION_OUTCOMES)
    cert = lookups.certification(cert_id)

    rows = _inspections_for(cert["id"])
    if outcome is not None:
        rows = [r for r in rows if r["outcome"] == outcome]
    rows.sort(key=_inspection_order_key)
    page, total = response.paginate(rows, limit, offset)
    return response.ok_list(views("factory_inspection", page), limit, offset, total)


@bp.route("/listing-certifications/<cert_id>/reinstate", methods=["POST"])
def reinstate_certification(cert_id):
    require_auth("CertificationOfficer", "PlantAdmin")
    validation.body()
    cert = lookups.certification(cert_id)
    if cert["status"] not in ("VARIATION_NOTICE", "SUSPENDED"):
        errors.fail(
            errors.ERR_INVALID_CERTIFICATION_STATE,
            "A listing file at %s may not be reinstated" % cert["status"],
        )

    open_rows = [r for r in _inspections_for(cert["id"]) if r["status"] == "OPEN"]
    today = clock.today()
    for row in open_rows:
        due = row["corrective_action_due_date"]
        if due is not None and parse_ymd(due) < today:
            errors.fail(
                errors.ERR_OPEN_VARIATION_UNRESOLVED,
                "The corrective action window closed on %s; a fresh inspection is required" % due,
            )

    for row in sort_created(open_rows):
        row["status"] = "CLOSED"
        touch(row)
    cert["open_variation_count"] = 0
    cert["status"] = "ACTIVE"
    touch(cert)

    cascades.certification_reinstated(cert)
    return response.ok(view("listing_certification", cert))
