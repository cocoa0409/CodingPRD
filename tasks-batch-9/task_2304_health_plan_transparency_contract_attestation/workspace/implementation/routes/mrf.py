"""MachineReadableFile endpoints (PRD 3.2)."""

from flask import Blueprint

import clock
import db
import guards
import response

bp = Blueprint("mrf", __name__)

FILE_TYPES = ("IN_NETWORK_RATES", "ALLOWED_AMOUNTS")
READ_ROLES = ("PlanSponsorAdmin", "ComplianceOfficer", "ExternalAuditor")


@bp.route("/compliance/machine-readable-files", methods=["POST"])
def create_file():
    guards.authorize("PlanSponsorAdmin")
    body = guards.read_body()
    plan_year_id = guards.field(body, "plan_year_id", "string")
    file_type = guards.field(body, "file_type", "enum", enum=FILE_TYPES)
    posting_month = guards.field(body, "posting_month", "month")
    public_url = guards.field(body, "public_url", "string")
    row_count = guards.field(body, "row_count", "integer")
    schema_version = guards.field(body, "schema_version", "string")
    plan_year = guards.fetch("plan_year", plan_year_id)
    guards.not_frozen(plan_year)
    # Ladder step 39 — posting month inside the plan year, row_count >= 1.
    guards.require(
        row_count >= 1
        and clock.month_of(plan_year["start_date"])
        <= posting_month
        <= clock.month_of(plan_year["end_date"]),
        "ERR_INVALID_MRF_INPUT",
        "posting_month must fall inside the plan year and row_count must be >= 1.",
    )
    record = db.common_fields()
    record.update({
        "plan_year_id": plan_year_id,
        "file_type": file_type,
        "posting_month": posting_month,
        "public_url": public_url,
        "row_count": row_count,
        "schema_version": schema_version,
        "status": "DRAFT",
        "validation_error_count": None,
        "published_at": None,
        "superseded_at": None,
    })
    db.mrfs[record["id"]] = record
    return response.created_response(response.public(record))


@bp.route("/compliance/machine-readable-files/<row_id>", methods=["GET"])
def get_file(row_id):
    guards.authorize(*READ_ROLES)
    return response.object_response(response.public(guards.fetch("mrf", row_id)))


@bp.route("/compliance/machine-readable-files", methods=["GET"])
def list_files():
    guards.authorize(*READ_ROLES)
    limit, offset = guards.pagination()
    guards.filter_fk("plan_year", "plan_year_id")
    rows = guards.apply_filters(db.ordered(db.mrfs), [
        ("plan_year_id", "plan_year_id", None),
        ("file_type", "file_type", None),
        ("posting_month", "posting_month", None),
        ("status", "status", None),
    ])
    page, total = guards.paginate(rows, limit, offset)
    return response.array_response(
        [response.public(r) for r in page], limit, offset, total
    )


@bp.route("/compliance/machine-readable-files/<row_id>/validate", methods=["POST"])
def validate_file(row_id):
    guards.authorize("PlanSponsorAdmin")
    mrf = guards.fetch("mrf", row_id)
    body = guards.read_body()
    error_count = guards.field(body, "validation_error_count", "integer")
    plan_year = db.plan_years.get(mrf["plan_year_id"])
    guards.not_frozen(plan_year)
    guards.state_is(mrf["status"], "DRAFT")
    # Ladder step 39 — validation_error_count must be >= 0.
    guards.require(
        error_count >= 0,
        "ERR_INVALID_MRF_INPUT",
        "validation_error_count must be >= 0.",
    )
    # DRAFT -> VALIDATING (one version bump) …
    mrf["status"] = "VALIDATING"
    mrf["validation_error_count"] = error_count
    db.bump(mrf)
    # … then the same request continues to PUBLISHED or REJECTED (second bump).
    if error_count == 0:
        now = clock.now_iso()
        for other in db.ordered(db.mrfs):
            if (
                other["id"] != mrf["id"]
                and other["status"] == "PUBLISHED"
                and other["plan_year_id"] == mrf["plan_year_id"]
                and other["file_type"] == mrf["file_type"]
                and other["posting_month"] == mrf["posting_month"]
            ):
                other["status"] = "SUPERSEDED"
                other["superseded_at"] = now
                db.bump(other)
        mrf["status"] = "PUBLISHED"
        mrf["published_at"] = now
    else:
        mrf["status"] = "REJECTED"
    db.bump(mrf)
    return response.object_response(response.public(mrf))


@bp.route("/compliance/machine-readable-files/<row_id>/revise", methods=["POST"])
def revise_file(row_id):
    guards.authorize("PlanSponsorAdmin")
    mrf = guards.fetch("mrf", row_id)
    body = guards.read_body()
    public_url = guards.field(body, "public_url", "string")
    row_count = guards.field(body, "row_count", "integer")
    plan_year = db.plan_years.get(mrf["plan_year_id"])
    guards.not_frozen(plan_year)
    guards.state_is(mrf["status"], "REJECTED")
    # Ladder step 39 — row_count must be >= 1.
    guards.require(
        row_count >= 1, "ERR_INVALID_MRF_INPUT", "row_count must be >= 1."
    )
    with db.txn(mrf):
        mrf["status"] = "DRAFT"
        mrf["public_url"] = public_url
        mrf["row_count"] = row_count
        mrf["validation_error_count"] = None
    return response.object_response(response.public(mrf))
