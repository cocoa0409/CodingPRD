"""License applications, license orders and compliance obligations."""
from flask import Blueprint, g

import auth
import clock
import constants as C
import listing
import payload
import response
import serializers as S
import services as SV
from db import db, sorted_rows
from errors import ApiError
from numeric import q2

bp = Blueprint("license", __name__)


def _executed_settlement(project):
    rows = sorted_rows(
        db.settlements,
        lambda s: s["project_id"] == project["id"] and s["status"] == "EXECUTED",
    )
    return rows[-1] if rows else None


def _pin_snapshot(application, project):
    plans = SV.approved_plans(project)
    plan = plans[0] if plans else None
    settlement = _executed_settlement(project)

    application["pinned_study_plan_id"] = plan["id"] if plan is not None else None
    application["pinned_study_plan_version"] = plan["version"] if plan is not None else None
    application["pinned_settlement_id"] = settlement["id"] if settlement is not None else None
    application["pinned_settlement_version"] = (
        settlement["version"] if settlement is not None else None
    )
    application["pinned_measure_ids"] = [m["id"] for m in SV.live_measures(project)]
    application["pinned_total_annual_burden_usd"] = project["total_annual_burden_usd"]


# ---------------------------------------------------------------------------
# applications
# ---------------------------------------------------------------------------


@bp.post("/relicensing/applications")
def file_application():
    auth.authenticate(["Licensee"])
    data = payload.body()

    project_id = payload.req_string(data, "project_id")
    project = SV.fetch("projects", project_id)

    amended_order = None
    if payload.present(data, "amends_order_id"):
        amends_order_id = payload.req_string(data, "amends_order_id")
        amended_order = SV.fetch("orders", amends_order_id)
        if SV.project_of_order(amended_order)["id"] != project_id:
            raise ApiError(
                "ERR_CROSS_PROJECT_REFERENCE",
                "The amended order belongs to a different project.",
            )

    application_type = payload.req_enum(data, "application_type", C.APPLICATION_TYPES)
    expected_version = payload.req_int(data, "expected_project_version")
    payload.opt_string(data, "filing_note")

    if application_type == "AMENDMENT" and amended_order is None:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "amends_order_id is required when application_type is AMENDMENT.",
        )
    if application_type == "ORIGINAL_RELICENSE" and amended_order is not None:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "amends_order_id is forbidden on an ORIGINAL_RELICENSE filing.",
        )

    if expected_version != project["version"]:
        raise ApiError(
            "ERR_STALE_PROJECT_VERSION",
            "expected_project_version does not match the project's current version.",
        )

    SV.require_not_frozen(project)

    if application_type == "ORIGINAL_RELICENSE":
        SV.require_stage(project, ["STUDY_PHASE"])

        plans = SV.approved_plans(project)
        if len(plans) != 1:
            raise ApiError(
                "ERR_STUDY_PLAN_NOT_APPROVED",
                "An original relicense filing requires exactly one APPROVED study plan.",
            )
        plan = plans[0]
        for study in sorted_rows(db.studies, lambda s: s["study_plan_id"] == plan["id"]):
            if study["review_status"] != "ACCEPTED":
                raise ApiError(
                    "ERR_STUDY_NOT_ACCEPTED",
                    "Every resource study of the approved plan must be ACCEPTED.",
                )
        if project["wqc_status"] == "NONE":
            raise ApiError(
                "ERR_WQC_STATE_INVALID",
                "A water-quality certification must be on file before filing.",
            )
        if clock.today() > SV.application_due_date(project):
            raise ApiError(
                "ERR_FILING_DEADLINE_PASSED",
                "The application deadline has passed.",
            )
    else:
        SV.require_stage(project, ["LICENSED"])
        if amended_order["compliance_state"] != "EFFECTIVE":
            raise ApiError(
                "ERR_ORDER_STATE_INVALID",
                "An amendment may be filed only against an EFFECTIVE order.",
            )

    if project["burden_ratio_pct"] >= C.BURDEN_RATIO_LIMIT_PCT and not project[
        "infeasibility_waiver_granted"
    ]:
        raise ApiError(
            "ERR_BURDEN_RATIO_EXCEEDED",
            "The project's burden ratio has reached the economic-feasibility ceiling.",
        )

    application = SV.base_row()
    application.update(
        {
            "project_id": project_id,
            "amends_order_id": amended_order["id"] if amended_order is not None else None,
            "application_type": application_type,
            "filing_status": "FILED",
            "ea_stage": "NOT_STARTED",
            "filed_at": clock.now_iso(),
            "deficiency_count": 0,
            "last_deficiency_note": None,
        }
    )
    _pin_snapshot(application, project)
    db.applications[application["id"]] = application

    if application_type == "AMENDMENT":
        for prior in sorted_rows(
            db.applications,
            lambda a: a["amends_order_id"] == amended_order["id"]
            and a["id"] != application["id"],
        ):
            if prior["filing_status"] in C.FILING_SUSPENDABLE:
                prior["filing_status"] = "SUPERSEDED"
                SV.touch(prior)
        amended_order["amendment_pending"] = True
        SV.touch(amended_order)
    else:
        project["stage"] = "APPLICATION_FILED"
        project["application_filed_at"] = clock.now_iso()
        SV.refresh_timeline_posture(project)

    SV.finalize_project(project)
    SV.touch(project)
    return response.object_response(S.application(application), 201)


@bp.get("/relicensing/applications")
def list_applications():
    auth.authenticate(C.ALL_ROLES)
    return listing.respond(
        sorted_rows(db.applications),
        S.application,
        ("project_id", "amends_order_id", "application_type", "filing_status", "ea_stage"),
    )


@bp.get("/relicensing/applications/<application_id>")
def get_application(application_id):
    auth.authenticate(C.ALL_ROLES)
    return response.object_response(S.application(SV.fetch("applications", application_id)))


@bp.post("/relicensing/applications/<application_id>/environmental-review")
def environmental_review(application_id):
    auth.authenticate(["Regulator"])
    application = SV.fetch("applications", application_id)
    data = payload.body()
    target_stage = payload.req_enum(data, "target_stage", C.EA_TARGET_STAGES)
    payload.opt_string(data, "review_note")

    project = SV.project_of_application(application)
    SV.require_not_frozen(project)

    required_ea = {"SCOPING": "NOT_STARTED", "DRAFT_EA": "SCOPING", "FINAL_EA": "DRAFT_EA"}
    required_filing = {"SCOPING": "FILED", "DRAFT_EA": "UNDER_REVIEW", "FINAL_EA": "UNDER_REVIEW"}

    if application["ea_stage"] != required_ea[target_stage]:
        raise ApiError(
            "ERR_APPLICATION_STATE_INVALID",
            "Advancing to %s requires ea_stage %s." % (target_stage, required_ea[target_stage]),
        )
    if application["filing_status"] != required_filing[target_stage]:
        raise ApiError(
            "ERR_APPLICATION_STATE_INVALID",
            "Advancing to %s requires filing_status %s."
            % (target_stage, required_filing[target_stage]),
        )

    if target_stage == "FINAL_EA":
        for measure in sorted_rows(
            db.measures,
            lambda m: m["project_id"] == project["id"] and m["source"] == "WQC_CONDITION",
        ):
            if measure["cost_estimate_variant"] != "DEFINITIVE":
                raise ApiError(
                    "ERR_DEFINITIVE_ESTIMATE_REQUIRED",
                    "Every WQC_CONDITION measure must carry a DEFINITIVE estimate.",
                )

    application["ea_stage"] = target_stage
    project_touched = False
    if target_stage == "SCOPING":
        application["filing_status"] = "UNDER_REVIEW"
        if (
            application["application_type"] == "ORIGINAL_RELICENSE"
            and project["stage"] == "APPLICATION_FILED"
        ):
            project["stage"] = "UNDER_ENVIRONMENTAL_REVIEW"
            project_touched = True

    SV.touch(application)
    SV.finalize_project(project)
    if project_touched:
        SV.touch(project)
    return response.object_response(S.application(application))


@bp.post("/relicensing/applications/<application_id>/deficiency")
def raise_deficiency(application_id):
    auth.authenticate(["Regulator"])
    application = SV.fetch("applications", application_id)
    data = payload.body()
    note = payload.req_string(data, "deficiency_note")

    project = SV.project_of_application(application)
    SV.require_not_frozen(project)

    if application["filing_status"] != "UNDER_REVIEW":
        raise ApiError(
            "ERR_APPLICATION_STATE_INVALID",
            "A deficiency notice requires filing_status UNDER_REVIEW.",
        )

    application["filing_status"] = "DEFICIENT"
    application["deficiency_count"] = application["deficiency_count"] + 1
    application["last_deficiency_note"] = note
    SV.touch(application)

    SV.finalize_project(project)
    return response.object_response(S.application(application))


@bp.post("/relicensing/applications/<application_id>/cure")
def cure_application(application_id):
    auth.authenticate(["Licensee"])
    application = SV.fetch("applications", application_id)
    data = payload.body()
    payload.opt_string(data, "cure_note")

    project = SV.project_of_application(application)
    SV.require_not_frozen(project)

    if application["filing_status"] not in ("DEFICIENT", "SUSPENDED"):
        raise ApiError(
            "ERR_APPLICATION_STATE_INVALID",
            "A cure requires filing_status DEFICIENT or SUSPENDED.",
        )

    application["filing_status"] = "UNDER_REVIEW"
    _pin_snapshot(application, project)
    SV.touch(application)

    SV.finalize_project(project)
    return response.object_response(S.application(application))


# ---------------------------------------------------------------------------
# order issuance
# ---------------------------------------------------------------------------


@bp.post("/relicensing/applications/<application_id>/order")
def issue_order(application_id):
    auth.authenticate(["Regulator"])
    application = SV.fetch("applications", application_id)
    data = payload.body()
    order_number = payload.req_string(data, "order_number")
    payload.opt_string(data, "order_note")

    for row in db.orders.values():
        if row["order_number"] == order_number:
            raise ApiError("ERR_DUPLICATE_KEY", "order_number is already in use.")

    project = SV.project_of_application(application)
    SV.require_not_frozen(project)

    if application["filing_status"] != "UNDER_REVIEW":
        raise ApiError(
            "ERR_APPLICATION_STATE_INVALID",
            "Order issuance requires filing_status UNDER_REVIEW.",
        )
    if application["ea_stage"] != "FINAL_EA":
        raise ApiError(
            "ERR_APPLICATION_STATE_INVALID",
            "Order issuance requires ea_stage FINAL_EA.",
        )
    if project["wqc_status"] not in ("CERTIFIED_WITH_CONDITIONS", "WAIVED"):
        raise ApiError(
            "ERR_WQC_CONDITION_NOT_INCORPORATED",
            "The state's water-quality conditions are not incorporated.",
        )
    if project["regulatory_posture"] == "RESTRICTED":
        raise ApiError(
            "ERR_PROJECT_POSTURE_RESTRICTED",
            "Order issuance is blocked while the project is RESTRICTED.",
        )

    effective_date = clock.today()
    order = SV.base_row()
    order.update(
        {
            "application_id": application["id"],
            "order_number": order_number,
            "effective_date": clock.fmt_date(effective_date),
            "compliance_state": "EFFECTIVE",
            "amendment_pending": False,
            "article_count": 0,
            "open_violation_count": 0,
            "last_report_basis": None,
            "last_report_period_year": None,
            "assessed_obligation_count": 0,
            "noncompliant_obligation_count": 0,
            "compliance_score": q2(100),
            "last_report_filed_at": None,
            "_reports": [],
        }
    )
    db.orders[order["id"]] = order

    created = SV.generate_obligation_schedule(order, project, effective_date)

    if application["application_type"] == "AMENDMENT" and application["amends_order_id"]:
        old_order = db.orders[application["amends_order_id"]]
        for obligation in SV.order_obligations(old_order):
            if obligation["status"] in ("PENDING", "SCHEDULED"):
                clone = SV.base_row()
                clone.update(
                    {
                        "order_id": order["id"],
                        "pme_measure_id": obligation["pme_measure_id"],
                        "dam_id": obligation["dam_id"],
                        "obligation_type": obligation["obligation_type"],
                        "due_date": obligation["due_date"],
                        "status": "PENDING",
                        "activity_window_start": None,
                        "activity_window_end": None,
                        "certified_at": None,
                        "certified_by_user_id": None,
                        "overdue_marked_at": None,
                    }
                )
                db.obligations[clone["id"]] = clone
                created.append(clone)
        for obligation in SV.order_obligations(old_order):
            if obligation["status"] != "WAIVED":
                obligation["status"] = "WAIVED"
                SV.touch(obligation)
        old_order["compliance_state"] = "SUPERSEDED"
        old_order["amendment_pending"] = False
        SV.touch(old_order)
        SV.refresh_order_violations(old_order)

    order["article_count"] = len(created)

    application["filing_status"] = "LICENSED"
    SV.touch(application)

    project["stage"] = "LICENSED"
    SV.finalize_project(project)
    SV.touch(project)

    return response.object_response(S.order(order), 201)


# ---------------------------------------------------------------------------
# orders
# ---------------------------------------------------------------------------


@bp.get("/relicensing/orders")
def list_orders():
    auth.authenticate(C.ALL_ROLES)
    return listing.respond(
        sorted_rows(db.orders), S.order, ("application_id", "compliance_state", "amendment_pending")
    )


@bp.get("/relicensing/orders/<order_id>")
def get_order(order_id):
    auth.authenticate(C.ALL_ROLES)
    return response.object_response(S.order(SV.fetch("orders", order_id)))


@bp.post("/relicensing/orders/<order_id>/annual-report")
def annual_report(order_id):
    auth.authenticate(["Licensee"])
    order = SV.fetch("orders", order_id)
    data = payload.body()
    basis = payload.req_enum(data, "report_basis", C.REPORT_BASES)
    period_year = payload.req_int(data, "period_year", minimum=1)
    payload.opt_string(data, "report_note")

    project = SV.project_of_order(order)

    start, _end = SV.report_window(order, basis, period_year)
    if start > clock.today():
        raise ApiError(
            "ERR_REPORT_PERIOD_INVALID",
            "The reporting period has not started yet.",
        )
    for filed_basis, filed_year in order.get("_reports", []):
        if filed_basis == basis and filed_year == period_year:
            raise ApiError(
                "ERR_REPORT_PERIOD_INVALID",
                "A report for this basis and period year has already been filed.",
            )

    assessed, noncompliant, score, _s, _e = SV.assess_compliance_year(order, basis, period_year)

    order["assessed_obligation_count"] = assessed
    order["noncompliant_obligation_count"] = noncompliant
    order["compliance_score"] = score
    order["last_report_basis"] = basis
    order["last_report_period_year"] = period_year
    order["last_report_filed_at"] = clock.now_iso()
    order.setdefault("_reports", []).append((basis, period_year))

    if noncompliant > 0 and order["compliance_state"] == "EFFECTIVE":
        order["compliance_state"] = "COMPLIANCE_FLAGGED"

    SV.touch(order)
    SV.finalize_project(project)
    return response.object_response(S.order(order))


# ---------------------------------------------------------------------------
# obligations
# ---------------------------------------------------------------------------


@bp.get("/relicensing/obligations")
def list_obligations():
    auth.authenticate(C.ALL_ROLES)
    return listing.respond(
        sorted_rows(db.obligations),
        S.obligation,
        ("order_id", "pme_measure_id", "dam_id", "obligation_type", "status"),
    )


@bp.get("/relicensing/obligations/<obligation_id>")
def get_obligation(obligation_id):
    auth.authenticate(C.ALL_ROLES)
    return response.object_response(S.obligation(SV.fetch("obligations", obligation_id)))


@bp.post("/relicensing/obligations/<obligation_id>/schedule")
def schedule_obligation(obligation_id):
    auth.authenticate(["Licensee"])
    obligation = SV.fetch("obligations", obligation_id)
    data = payload.body()
    window_start = payload.req_date(data, "activity_window_start")
    window_end = payload.req_date(data, "activity_window_end")
    payload.opt_string(data, "schedule_note")

    if window_start > window_end:
        payload.bad("activity_window_end", "must be on or after activity_window_start")

    project = SV.project_of_obligation(obligation)

    if obligation["status"] not in ("PENDING", "OVERDUE"):
        raise ApiError(
            "ERR_OBLIGATION_STATE_INVALID",
            "Only a PENDING or OVERDUE obligation can be scheduled.",
        )

    if obligation["obligation_type"] == "PME_IMPLEMENTATION" and obligation["pme_measure_id"]:
        measure = db.measures.get(obligation["pme_measure_id"])
        prerequisite_id = measure.get("prerequisite_measure_id") if measure else None
        if prerequisite_id:
            prerequisite = db.measures.get(prerequisite_id)
            if prerequisite is None or prerequisite["status"] != "IMPLEMENTED":
                raise ApiError(
                    "ERR_PREREQUISITE_NOT_IMPLEMENTED",
                    "The prerequisite measure is not yet IMPLEMENTED.",
                )

    if obligation["obligation_type"] in C.DAM_BOUND_TYPES and obligation["dam_id"]:
        dam = db.dams[obligation["dam_id"]]
        concurrent = 1
        for other in sorted_rows(db.obligations, lambda o: o["dam_id"] == dam["id"]):
            if other["id"] == obligation["id"] or other["status"] != "SCHEDULED":
                continue
            if other["obligation_type"] not in C.DAM_BOUND_TYPES:
                continue
            other_start = clock.parse_iso_date(other["activity_window_start"])
            other_end = clock.parse_iso_date(other["activity_window_end"])
            if other_start is None or other_end is None:
                continue
            if window_start <= other_end and other_start <= window_end:
                concurrent += 1
        if concurrent > int(dam["max_concurrent_field_activities"]):
            raise ApiError(
                "ERR_DAM_ACTIVITY_CAPACITY_EXCEEDED",
                "The dam cannot absorb another concurrent field activity.",
            )

    obligation["status"] = "SCHEDULED"
    obligation["activity_window_start"] = clock.fmt_date(window_start)
    obligation["activity_window_end"] = clock.fmt_date(window_end)
    SV.touch(obligation)

    SV.finalize_project(project)
    return response.object_response(S.obligation(obligation))


@bp.post("/relicensing/obligations/<obligation_id>/certify")
def certify_obligation(obligation_id):
    auth.authenticate(["Licensee"])
    obligation = SV.fetch("obligations", obligation_id)
    data = payload.body()
    payload.opt_string(data, "certification_note")

    order = db.orders[obligation["order_id"]]
    project = SV.project_of_order(order)

    if obligation["status"] != "SCHEDULED":
        raise ApiError(
            "ERR_OBLIGATION_STATE_INVALID",
            "Only a SCHEDULED obligation can be certified.",
        )

    window_start = clock.parse_iso_date(obligation["activity_window_start"])
    if window_start is None or clock.today() < window_start:
        raise ApiError(
            "ERR_CERTIFICATION_TOO_EARLY",
            "The activity window has not started yet.",
        )

    measure = (
        db.measures.get(obligation["pme_measure_id"]) if obligation["pme_measure_id"] else None
    )
    if measure is not None:
        category = measure["resource_category"]
        for study in db.studies.values():
            if study["report_submitted_by_user_id"] != g.user_id:
                continue
            if study["resource_category"] != category:
                continue
            plan = db.study_plans.get(study["study_plan_id"])
            if plan is not None and plan["project_id"] == project["id"]:
                raise ApiError(
                    "ERR_SEGREGATION_OF_DUTIES",
                    "The user who submitted a study report in this resource category "
                    "may not certify the obligation.",
                )

    obligation["status"] = "CERTIFIED"
    obligation["certified_at"] = clock.now_iso()
    obligation["certified_by_user_id"] = g.user_id
    SV.touch(obligation)

    if obligation["obligation_type"] == "PME_IMPLEMENTATION" and measure is not None:
        if measure["status"] == "INCLUDED":
            measure["status"] = "IMPLEMENTED"
            SV.touch(measure)

    SV.refresh_order_violations(order, unflag_on_zero=True)

    SV.finalize_project(project)
    return response.object_response(S.obligation(obligation))
