"""Evaluation routes (scaffold §1.5 — Evaluations; PRD §3.3)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import APIError, ERR_THERAPIST_LICENSE_INVALID
from middleware import get_json_body, require_auth
from response import ok_array, ok_object, paginate_params, slice_page
from services.calculations import eight_minute_units
from services.validation import (
    lookup_or_404,
    require_date,
    require_enum,
    require_fields,
    require_int,
    require_string,
)


bp = Blueprint("evaluations", __name__)


EVALUATION_KINDS = {"INITIAL", "RE_EVALUATION", "DISCHARGE"}


@bp.post("/rehab/evaluations")
def create_evaluation():
    require_auth(["Therapist"])()
    body = get_json_body()
    require_fields(
        body,
        [
            "plan_of_care_id",
            "therapist_id",
            "evaluation_kind",
            "performed_on",
            "functional_score",
            "minutes_spent",
        ],
    )
    poc_id = require_string(body["plan_of_care_id"], "plan_of_care_id")
    therapist_id = require_string(body["therapist_id"], "therapist_id")
    kind = require_enum(body["evaluation_kind"], EVALUATION_KINDS, "evaluation_kind")
    performed_on = require_date(body["performed_on"], "performed_on")
    functional_score = require_int(
        body["functional_score"], "functional_score", min_value=0, max_value=100
    )
    minutes_spent = require_int(
        body["minutes_spent"], "minutes_spent", min_value=8, max_value=240
    )

    poc = lookup_or_404(db.plans_of_care, poc_id, "PlanOfCare")
    therapist = lookup_or_404(db.therapists, therapist_id, "Therapist")
    patient = db.patients[poc["patient_id"]]

    # PRD §3.10 demo licensing policy applies on Evaluation create (priority 420).
    if patient["insurance_type"] != "VA_TRICARE" and therapist["license_state"] != "CA":
        raise APIError(
            ERR_THERAPIST_LICENSE_INVALID,
            422,
            f"Therapist.license_state={therapist['license_state']} not valid "
            f"for patient.insurance_type={patient['insurance_type']}",
        )

    with db.mutation_lock:
        ev = {
            "plan_of_care_id": poc_id,
            "therapist_id": therapist_id,
            "evaluation_kind": kind,
            "performed_on": performed_on.isoformat(),
            "functional_score": functional_score,
            "minutes_spent": minutes_spent,
            "billable_units": eight_minute_units(minutes_spent),
        }
        db.stamp_common(ev)
        db.evaluations[ev["id"]] = ev

        # PRD §3.3: first INITIAL evaluation back-populates POC.initial_evaluation_id
        # and bumps the POC's version. Subsequent INITIALs (and any non-INITIAL)
        # do not retouch the field.
        if kind == "INITIAL" and poc.get("initial_evaluation_id") in (None, ""):
            poc["initial_evaluation_id"] = ev["id"]
            db.bump(poc)

        return ok_object(ev, 201)


@bp.get("/rehab/evaluations/<eid>")
def get_evaluation(eid: str):
    require_auth(["PlatformAdmin", "Therapist", "BillingClerk"])()
    ev = lookup_or_404(db.evaluations, eid, "Evaluation")
    return ok_object(ev, 200)


@bp.get("/rehab/evaluations")
def list_evaluations():
    require_auth(["PlatformAdmin", "Therapist", "BillingClerk"])()
    limit, offset = paginate_params(request.args)
    items = list(db.evaluations.values())
    for key in ("plan_of_care_id", "therapist_id", "evaluation_kind"):
        if key in request.args:
            items = [e for e in items if e.get(key) == request.args.get(key)]
    items.sort(key=db.created_then_id)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)
