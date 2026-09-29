"""Institution endpoints (PRD 3.1)."""

from flask import Blueprint

import calc
import constants as C
import serializers as S
import store
from auth import authenticate, institution_scope
from errors import fail
from response import array_response, object_response
from validate import (Field, bool_filter, check, enum_filter, json_body, lookup,
                      paginate, pagination)

bp = Blueprint("institutions", __name__)

READ_ROLES = C.ALL_ROLES
BACK_OFFICE_READ_ROLES = ["SystemAdmin", "InstitutionAdmin", "ComplianceAnalyst",
                          "ComplianceOfficer", "Examiner"]

CREATE_FIELDS = [
    Field("lei", "string", required=True),
    Field("name", "string", required=True),
    Field("activity_year", "integer", required=True,
          minimum=C.MIN_ACTIVITY_YEAR, maximum=C.MAX_ACTIVITY_YEAR),
    Field("asset_size_usd_cents", "integer", required=True),
    Field("prior_year_closed_end_originations", "integer"),
    Field("prior_year_open_end_originations", "integer"),
]

PATCH_FIELDS = [
    Field("name", "string"),
    Field("asset_size_usd_cents", "integer"),
    Field("prior_year_closed_end_originations", "integer"),
    Field("prior_year_open_end_originations", "integer"),
]


def new_institution(body):
    row = store.new_row()
    row.update({
        "lei": body["lei"],
        "name": body["name"],
        "activity_year": body["activity_year"],
        "asset_size_usd_cents": body["asset_size_usd_cents"],
        "prior_year_closed_end_originations":
            body.get("prior_year_closed_end_originations") or 0,
        "prior_year_open_end_originations":
            body.get("prior_year_open_end_originations") or 0,
        "partial_exemption_eligible": False,
        "quarterly_filer": False,
        "required_field_count": C.FULL_FIELD_COUNT,
        "total_application_count": 0,
        "pending_record_count": 0,
        "reportable_record_count": 0,
        "excluded_record_count": 0,
        "cleared_record_count": 0,
        "open_register_count": 0,
        "filing_posture": "OPEN",
        "filing_deadline_at": None,
        "_run_index": 0,
        "_submission_index": 0,
        "_sample_index": 0,
        "_analysis_index": 0,
    })
    calc.filing_profile_resolution(row)
    return row


@bp.route("/hmda/institutions", methods=["POST"])
def create_institution():
    authenticate(["SystemAdmin"])
    body = check(json_body(), CREATE_FIELDS)
    for existing in store.institutions.values():
        if existing["lei"] == body["lei"]:
            fail("ERR_DUPLICATE_LEI")
    row = new_institution(body)
    store.institutions[row["id"]] = row
    return object_response(S.institution(row), 201)


@bp.route("/hmda/institutions/<inst_id>", methods=["PATCH"])
def patch_institution(inst_id):
    user_id, role = authenticate(["InstitutionAdmin"])
    institution_scope(user_id, role, inst_id)
    inst = lookup(store.institutions, inst_id, "ERR_INSTITUTION_NOT_FOUND")
    body = check(json_body(), PATCH_FIELDS)
    for name in ("name", "asset_size_usd_cents", "prior_year_closed_end_originations",
                 "prior_year_open_end_originations"):
        if name in body and body[name] is not None:
            inst[name] = body[name]
    calc.filing_profile_resolution(inst)
    # partial_exemption_eligible may have flipped, so every own record is
    # re-evaluated for completeness (PRD 3.1).
    for app in store.ordered(store.applications.values()):
        if app["institution_id"] == inst["id"]:
            before = (app["lar_status"], app["captured_field_count"],
                      app["applicable_field_count"], app["exclusion_reason"])
            calc.application_completeness(app, inst)
            after = (app["lar_status"], app["captured_field_count"],
                     app["applicable_field_count"], app["exclusion_reason"])
            if before != after:
                store.bump(app)
    calc.recompute_institution_counters(inst)
    store.bump(inst)
    return object_response(S.institution(inst))


@bp.route("/hmda/institutions/<inst_id>", methods=["GET"])
def get_institution(inst_id):
    user_id, role = authenticate(READ_ROLES)
    institution_scope(user_id, role, inst_id)
    inst = lookup(store.institutions, inst_id, "ERR_INSTITUTION_NOT_FOUND")
    return object_response(S.institution(inst))


@bp.route("/hmda/institutions/<inst_id>/applications", methods=["GET"])
def list_applications(inst_id):
    user_id, role = authenticate(READ_ROLES)
    institution_scope(user_id, role, inst_id)
    lookup(store.institutions, inst_id, "ERR_INSTITUTION_NOT_FOUND")
    limit, offset = pagination()
    stage = enum_filter("stage", C.STAGES)
    lar_status = enum_filter("lar_status", C.LAR_STATUSES)
    rows = [a for a in store.ordered(store.applications.values())
            if a["institution_id"] == inst_id
            and (stage is None or a["stage"] == stage)
            and (lar_status is None or a["lar_status"] == lar_status)]
    items, total = paginate(rows, limit, offset, S.application)
    return array_response(items, limit, offset, total)


@bp.route("/hmda/institutions/<inst_id>/edit-runs", methods=["GET"])
def list_edit_runs(inst_id):
    user_id, role = authenticate(BACK_OFFICE_READ_ROLES)
    institution_scope(user_id, role, inst_id)
    lookup(store.institutions, inst_id, "ERR_INSTITUTION_NOT_FOUND")
    limit, offset = pagination()
    status = enum_filter("status", C.EDIT_RUN_STATUSES)
    rows = [r for r in store.ordered(store.edit_runs.values())
            if r["institution_id"] == inst_id
            and (status is None or r["status"] == status)]
    items, total = paginate(rows, limit, offset, S.edit_run)
    return array_response(items, limit, offset, total)


@bp.route("/hmda/institutions/<inst_id>/submissions", methods=["GET"])
def list_submissions(inst_id):
    user_id, role = authenticate(BACK_OFFICE_READ_ROLES)
    institution_scope(user_id, role, inst_id)
    lookup(store.institutions, inst_id, "ERR_INSTITUTION_NOT_FOUND")
    limit, offset = pagination()
    status = enum_filter("status", C.SUBMISSION_STATUSES)
    rows = [s for s in store.ordered(store.filing_submissions.values())
            if s["institution_id"] == inst_id
            and (status is None or s["status"] == status)]
    items, total = paginate(rows, limit, offset, S.filing_submission)
    return array_response(items, limit, offset, total)


@bp.route("/hmda/institutions/<inst_id>/audit-samples", methods=["GET"])
def list_audit_samples(inst_id):
    user_id, role = authenticate(BACK_OFFICE_READ_ROLES)
    institution_scope(user_id, role, inst_id)
    lookup(store.institutions, inst_id, "ERR_INSTITUTION_NOT_FOUND")
    limit, offset = pagination()
    status = enum_filter("status", C.AUDIT_SAMPLE_STATUSES)
    rows = [s for s in store.ordered(store.audit_samples.values())
            if s["institution_id"] == inst_id
            and (status is None or s["status"] == status)]
    items, total = paginate(rows, limit, offset, S.audit_sample)
    return array_response(items, limit, offset, total)


@bp.route("/hmda/institutions/<inst_id>/fair-lending-analyses", methods=["GET"])
def list_fair_lending(inst_id):
    user_id, role = authenticate(BACK_OFFICE_READ_ROLES)
    institution_scope(user_id, role, inst_id)
    lookup(store.institutions, inst_id, "ERR_INSTITUTION_NOT_FOUND")
    limit, offset = pagination()
    basis = enum_filter("basis", C.FAIR_LENDING_BASES)
    status = enum_filter("status", C.FAIR_LENDING_STATUSES)
    rows = [a for a in store.ordered(store.fair_lending_analyses.values())
            if a["institution_id"] == inst_id
            and (basis is None or a["basis"] == basis)
            and (status is None or a["status"] == status)]
    items, total = paginate(rows, limit, offset, S.fair_lending_analysis)
    return array_response(items, limit, offset, total)
