"""Disaster application endpoints (PRD §3.9)."""

from decimal import Decimal

from flask import Blueprint, request

import db
from errors import (
    ApiError, ERR_LOSS_THRESHOLD_NOT_MET, ERR_SEGREGATION_OF_DUTIES,
    invalid_request, invalid_state,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, paginate
from services.aph import compute_aph, T_YIELD, DISASTER_SUBSTITUTION_FACTOR
from services.helpers import (
    get_farm_or_404, get_disaster_app_or_404, active_membership,
    certified_report_for,
)
from validation import (
    body, require_int, require_string, require_decimal, require_enum,
    optional_bool,
)

bp = Blueprint("disasters", __name__)

DISASTER_TYPES = ("DROUGHT", "FLOOD", "HAIL", "FREEZE", "WILDFIRE", "EXCESS_MOISTURE")


@bp.post("/fsa/farms/<farm_id>/disaster-applications")
def create_disaster_app(farm_id):
    user_id, _ = require_roles(["Producer"])
    get_farm_or_404(farm_id)
    data = body()
    program_year = require_int(data, "program_year")
    disaster_type = require_enum(data, "disaster_type", DISASTER_TYPES)
    loss_acres = require_decimal(data, "loss_acres")
    qualifying_commodity = require_string(data, "qualifying_commodity")
    documentation_complete = optional_bool(data, "documentation_complete", False)

    app = db.common_fields()
    app.update({
        "farm_id": farm_id,
        "program_year": program_year,
        "disaster_type": disaster_type,
        "application_status": "DRAFT",
        "loss_acres": float(loss_acres),
        "qualifying_commodity": qualifying_commodity,
        "documentation_complete": documentation_complete,
        "filed_by_producer_id": None,
    })
    db.disaster_applications[app["id"]] = app
    return success_object(app, 201)


@bp.get("/fsa/disaster-applications/<app_id>")
def get_disaster_app(app_id):
    require_roles(ALL_ROLES)
    return success_object(get_disaster_app_or_404(app_id))


@bp.get("/fsa/farms/<farm_id>/disaster-applications")
def list_farm_disaster_apps(farm_id):
    require_roles(ALL_ROLES)
    get_farm_or_404(farm_id)
    program_year = request.args.get("program_year")
    items = [a for a in db.disaster_applications.values() if a["farm_id"] == farm_id]
    if program_year is not None:
        try:
            py = int(program_year)
        except ValueError:
            raise invalid_request("program_year must be an integer")
        items = [a for a in items if a["program_year"] == py]
    items.sort(key=lambda a: a["created_at"])
    return paginate(items, request.args)


@bp.post("/fsa/disaster-applications/<app_id>/file")
def file_disaster_app(app_id):
    user_id, _ = require_roles(["Producer"])
    app = get_disaster_app_or_404(app_id)
    if app["application_status"] != "DRAFT":
        raise invalid_state("Only a DRAFT application may be filed")
    if active_membership(app["farm_id"], user_id) is None:
        raise invalid_request("Producer does not hold an ACTIVE membership on this farm")
    if certified_report_for(app["farm_id"], app["program_year"]) is None:
        raise invalid_state(
            "AcreageReport for (farm, program_year) must be CERTIFIED to file")
    app["application_status"] = "FILED"
    app["filed_by_producer_id"] = user_id
    db.touch(app)
    return success_object(app)


@bp.post("/fsa/disaster-applications/<app_id>/assign-reviewer")
def assign_reviewer(app_id):
    require_roles(["CountyExecutiveDirector"])
    app = get_disaster_app_or_404(app_id)
    if app["application_status"] != "FILED":
        raise invalid_state("Only a FILED application may be assigned for review")
    if not app.get("documentation_complete"):
        raise invalid_state("documentation_complete must be true to assign a reviewer")
    app["application_status"] = "UNDER_REVIEW"
    db.touch(app)
    return success_object(app)


@bp.post("/fsa/disaster-applications/<app_id>/approve")
def approve_disaster_app(app_id):
    user_id, _ = require_roles(["CountyCommittee"])
    app = get_disaster_app_or_404(app_id)
    if app["application_status"] != "UNDER_REVIEW":
        raise invalid_state("Only an UNDER_REVIEW application may be approved")

    # Segregation of duties: committee reviewer must differ from the filer.
    if app.get("filed_by_producer_id") is not None \
            and app["filed_by_producer_id"] == user_id:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES,
            "Committee reviewer is the filer",
            422,
        )

    # 35% trigger (priority 16): loss_acres >= 0.35 * reported acres for
    # the qualifying commodity.
    reported = Decimal("0")
    for r in db.acreage_reports.values():
        if (r["farm_id"] == app["farm_id"]
                and r["program_year"] == app["program_year"]
                and r["report_status"] == "CERTIFIED"):
            for line in db.acreage_report_lines.values():
                if (line["acreage_report_id"] == r["id"]
                        and line["crop_code"] == app["qualifying_commodity"]):
                    reported += Decimal(str(line["planted_acres"]))
                    reported += Decimal(str(line["prevented_planted_acres"]))
    if Decimal(str(app["loss_acres"])) < Decimal("0.35") * reported:
        raise ApiError(
            ERR_LOSS_THRESHOLD_NOT_MET,
            "Disaster loss_acres < 35% of reported acres for the commodity",
            422,
        )

    app["application_status"] = "APPROVED"
    db.touch(app)

    # Yield-substitution cascade: for each observation on the same farm and
    # qualifying commodity whose actual yield is below 65% of the T-yield,
    # set is_disaster_substituted and substitute 0.65*T into the APH
    # recompute (PRD §3.9).
    t_yield = T_YIELD.get(app["qualifying_commodity"])
    if t_yield is not None:
        threshold = DISASTER_SUBSTITUTION_FACTOR * t_yield
        affected_records = set()
        for obs in db.yield_observations.values():
            record = db.yield_records.get(obs["yield_record_id"])
            if record is None:
                continue
            if record["farm_id"] != app["farm_id"] \
                    or record["commodity"] != app["qualifying_commodity"]:
                continue
            actual = obs.get("actual_yield_bu_per_acre")
            if actual is not None and Decimal(str(actual)) < threshold:
                if not obs.get("is_disaster_substituted"):
                    obs["is_disaster_substituted"] = True
                    affected_records.add(record["id"])
        for rid in affected_records:
            record = db.yield_records.get(rid)
            if record is not None:
                compute_aph(record)
                db.touch(record)

        # Payment recompute (PRD §3.9): "if that enrollment is
        # PAYMENT_COMPUTED or PAYMENT_ISSUED the payment delta is
        # recomputed" — rerun the computation with the market inputs
        # captured at compute time; only the pinned APH has moved.
        from services.payment import compute_payment as _compute_payment
        for enrollment in db.enrollments.values():
            if enrollment["farm_id"] != app["farm_id"] \
                    or enrollment["commodity"] != app["qualifying_commodity"]:
                continue
            if enrollment["enrollment_status"] not in (
                    "PAYMENT_COMPUTED", "PAYMENT_ISSUED"):
                continue
            inputs = db.enrollment_compute_inputs.get(enrollment["id"])
            if inputs is None:
                continue
            _compute_payment(enrollment, inputs)
            db.touch(enrollment)

    return success_object(app)


@bp.post("/fsa/disaster-applications/<app_id>/deny")
def deny_disaster_app(app_id):
    require_roles(["CountyCommittee"])
    app = get_disaster_app_or_404(app_id)
    if app["application_status"] != "UNDER_REVIEW":
        raise invalid_state("Only an UNDER_REVIEW application may be denied")
    data = body()
    require_string(data, "reason")
    app["application_status"] = "DENIED"
    db.touch(app)
    return success_object(app)


@bp.post("/fsa/disaster-applications/<app_id>/withdraw")
def withdraw_disaster_app(app_id):
    user_id, _ = require_roles(["Producer"])
    app = get_disaster_app_or_404(app_id)
    if app["application_status"] not in ("DRAFT", "FILED"):
        raise invalid_state("Only a DRAFT or FILED application may be withdrawn")
    app["application_status"] = "WITHDRAWN"
    db.touch(app)
    return success_object(app)
