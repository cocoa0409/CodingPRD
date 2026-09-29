"""Liner CQA documentation cycle and aerial surveys."""
from decimal import Decimal

from core import (Body, ALL_ROLES, D, created, endpoint, err, filtered,
                  fk_or_404, get_or_404, new_row, obj_response, paged, public,
                  q2, q4, rows, touch, whole_days_between)
import services as S


def register(app):
    # ---------------------------------------------------- liner qa packages ---
    @endpoint(app, "/liner-qa-packages", ["POST"], ["SiteOperator"])
    def submit_package(user_id, role):
        b = Body()
        cell_id = b.fk("cell_id")
        seam = b.number("seam_length_ft", gt=0)
        destructive = b.integer("destructive_test_count", minimum=1)
        passing = b.integer("passing_test_count", minimum=0)
        panels = b.integer("panel_count", minimum=1)
        defects = b.integer("defect_count", minimum=0)
        if passing > destructive:
            raise err("ERR_INVALID_REQUEST",
                      "passing_test_count may not exceed destructive_test_count.")
        cell = fk_or_404("cell", cell_id)
        S.scope(user_id, cell["landfill_id"])
        if cell["status"] != "UNDER_CONSTRUCTION":
            raise err("ERR_INVALID_STATE_TRANSITION",
                      "The cell is not under construction.")
        for p in rows("liner_qa_package"):
            if p["cell_id"] == cell["id"] and p["status"] in ("SUBMITTED",
                                                              "UNDER_REVIEW"):
                raise err("ERR_INVALID_STATE_TRANSITION",
                          "A package for this cell is already in flight.")
        row = new_row("liner_qa_package", {
            "cell_id": cell["id"],
            "seam_length_ft": seam,
            "destructive_test_count": destructive,
            "passing_test_count": passing,
            "panel_count": panels,
            "defect_count": defects,
            "qa_conformance_score": S.qa_conformance_score(
                seam, destructive, passing, panels, defects),
            "revision_round": 1,
            "submitted_by_user_id": user_id,
            "reviewed_by_user_id": None,
            "certification_reference": None,
            "status": "SUBMITTED",
        })
        cell["status"] = "QA_REVIEW"
        touch(cell)
        return created(public(row))

    @endpoint(app, "/liner-qa-packages/<liner_qa_package_id>", ["GET"], ALL_ROLES)
    def read_package(user_id, role, liner_qa_package_id):
        return obj_response(public(get_or_404("liner_qa_package",
                                              liner_qa_package_id)))

    @endpoint(app, "/liner-qa-packages", ["GET"], ALL_ROLES)
    def list_packages(user_id, role):
        return paged(filtered(rows("liner_qa_package"),
                              {"cell_id": "cell_id", "status": "status"}))

    @endpoint(app, "/cells/<cell_id>/liner-qa-packages", ["GET"], ALL_ROLES)
    def list_cell_packages(user_id, role, cell_id):
        cell = get_or_404("cell", cell_id)
        pkgs = [p for p in rows("liner_qa_package") if p["cell_id"] == cell["id"]]
        return paged(filtered(pkgs, {"status": "status"}))

    @endpoint(app, "/liner-qa-packages/<liner_qa_package_id>/begin-review",
              ["POST"], ["CqaEngineer"])
    def begin_review(user_id, role, liner_qa_package_id):
        pkg = get_or_404("liner_qa_package", liner_qa_package_id)
        if pkg["status"] != "SUBMITTED":
            raise err("ERR_INVALID_STATE_TRANSITION",
                      "Review opens only from SUBMITTED.")
        if user_id == pkg["submitted_by_user_id"]:
            raise err("ERR_SEGREGATION_OF_DUTIES",
                      "The submitter may not review their own package.")
        pkg["reviewed_by_user_id"] = user_id
        pkg["status"] = "UNDER_REVIEW"
        touch(pkg)
        return obj_response(public(pkg))

    @endpoint(app, "/liner-qa-packages/<liner_qa_package_id>/return", ["POST"],
              ["CqaEngineer"])
    def return_package(user_id, role, liner_qa_package_id):
        b = Body()
        b.string("return_note")
        pkg = get_or_404("liner_qa_package", liner_qa_package_id)
        if pkg["status"] != "UNDER_REVIEW":
            raise err("ERR_INVALID_STATE_TRANSITION",
                      "A package is returned only from UNDER_REVIEW.")
        if user_id == pkg["submitted_by_user_id"]:
            raise err("ERR_SEGREGATION_OF_DUTIES",
                      "The submitter may not return their own package.")
        cell = S.cell_of(pkg["cell_id"])
        rounds = pkg["revision_round"]
        if rounds < 3:
            pkg["status"] = "RETURNED"
            pkg["revision_round"] = rounds + 1
            touch(pkg)
            cell["status"] = "UNDER_CONSTRUCTION"
            touch(cell)
        else:
            pkg["status"] = "REJECTED"
            touch(pkg)
            cell["status"] = "REJECTED"
            touch(cell)
        return obj_response(public(pkg))

    @endpoint(app, "/liner-qa-packages/<liner_qa_package_id>/resubmit", ["POST"],
              ["SiteOperator"])
    def resubmit_package(user_id, role, liner_qa_package_id):
        b = Body()
        seam = b.number("seam_length_ft", gt=0)
        destructive = b.integer("destructive_test_count", minimum=1)
        passing = b.integer("passing_test_count", minimum=0)
        panels = b.integer("panel_count", minimum=1)
        defects = b.integer("defect_count", minimum=0)
        if passing > destructive:
            raise err("ERR_INVALID_REQUEST",
                      "passing_test_count may not exceed destructive_test_count.")
        pkg = get_or_404("liner_qa_package", liner_qa_package_id)
        cell = S.cell_of(pkg["cell_id"])
        S.scope(user_id, cell["landfill_id"])
        if pkg["status"] != "RETURNED":
            raise err("ERR_INVALID_STATE_TRANSITION",
                      "Only a RETURNED package may be resubmitted.")
        if cell["status"] != "UNDER_CONSTRUCTION":
            raise err("ERR_INVALID_STATE_TRANSITION",
                      "The parent cell is not back under construction.")
        pkg["seam_length_ft"] = seam
        pkg["destructive_test_count"] = destructive
        pkg["passing_test_count"] = passing
        pkg["panel_count"] = panels
        pkg["defect_count"] = defects
        pkg["qa_conformance_score"] = S.qa_conformance_score(
            seam, destructive, passing, panels, defects)
        pkg["submitted_by_user_id"] = user_id
        pkg["reviewed_by_user_id"] = None
        pkg["status"] = "SUBMITTED"
        touch(pkg)
        cell["status"] = "QA_REVIEW"
        touch(cell)
        return obj_response(public(pkg))

    @endpoint(app, "/liner-qa-packages/<liner_qa_package_id>/approve", ["POST"],
              ["CqaEngineer"])
    def approve_package(user_id, role, liner_qa_package_id):
        b = Body()
        certification_reference = b.string("certification_reference")
        pkg = get_or_404("liner_qa_package", liner_qa_package_id)
        if pkg["status"] != "UNDER_REVIEW":
            raise err("ERR_INVALID_STATE_TRANSITION",
                      "Approval runs only from UNDER_REVIEW.")
        if user_id == pkg["submitted_by_user_id"]:
            raise err("ERR_SEGREGATION_OF_DUTIES",
                      "The submitter may not approve their own package.")
        if D(pkg["qa_conformance_score"]) < S.QA_APPROVAL_MIN_SCORE:
            raise err("ERR_QA_SCORE_BELOW_THRESHOLD",
                      "The conformance score is below 85.0.")
        pkg["certification_reference"] = certification_reference
        pkg["status"] = "APPROVED"
        touch(pkg)
        # Link 1
        cell = S.cell_of(pkg["cell_id"])
        cell["status"] = "QA_CERTIFIED"
        touch(cell)
        # Link 2 (+ 2b)
        lf = S.landfill_of_cell(cell)
        S.sync_landfill(lf)
        if lf["operating_status"] == "RESTRICTED_AIRSPACE" \
                and D(lf["remaining_life_years"]) >= S.SITE_LIFE_RESTRICT_YEARS:
            lf["operating_status"] = "OPEN"
        touch(lf)
        # Link 3
        staled = False
        for est in S.estimates_of_landfill(lf["id"]):
            if est["status"] == "CERTIFIED":
                est["status"] = "STALE"
                touch(est)
                staled = True
        # Link 4, caused by link 3
        if staled:
            lf["financial_assurance_status"] = "SHORTFALL_REVIEW"
            touch(lf)
        return obj_response(public(pkg))

    # ------------------------------------------------------- aerial surveys ---
    @endpoint(app, "/aerial-surveys", ["POST"], ["SurveyorOfRecord"])
    def record_survey(user_id, role):
        b = Body()
        landfill_id = b.fk("landfill_id")
        flown_on = b.timestamp("flown_on")
        period_start = b.timestamp("coverage_period_start")
        period_end = b.timestamp("coverage_period_end")
        measured = b.number("measured_remaining_airspace_cy", ge=0)
        tons = b.number("tons_placed_in_period", gt=0)
        if period_start > period_end:
            raise err("ERR_INVALID_REQUEST", "The coverage period runs backwards.")
        if period_end > flown_on:
            raise err("ERR_INVALID_REQUEST",
                      "coverage_period_end may not be later than flown_on.")
        lf = fk_or_404("landfill", landfill_id)
        occupying = [s for s in S.surveys_of_landfill(lf["id"])
                     if s["status"] in ("RECORDED", "SUPERSEDED")]
        for other in occupying:
            if period_start <= other["coverage_period_end"] \
                    and other["coverage_period_start"] <= period_end:
                raise err("ERR_SURVEY_PERIOD_OVERLAP",
                          "The coverage period overlaps an existing survey.")
        for other in occupying:
            if whole_days_between(flown_on, other["flown_on"]) \
                    < S.SURVEY_MIN_SPACING_DAYS:
                raise err("ERR_SURVEY_SPACING_VIOLATION",
                          "Flights must be at least 90 whole days apart.")
        prior = S.recorded_survey(lf["id"])
        if prior is not None:
            consumed = q2(D(prior["measured_remaining_airspace_cy"]) - D(measured))
        else:
            consumed = q2(D(lf["certified_airspace_cy"]) - D(measured))
        if consumed <= 0:
            density = Decimal("0.0000")
        else:
            density = q4(D(tons) / consumed)
        row = new_row("aerial_survey", {
            "landfill_id": lf["id"],
            "flown_on": flown_on,
            "coverage_period_start": period_start,
            "coverage_period_end": period_end,
            "measured_remaining_airspace_cy": measured,
            "tons_placed_in_period": tons,
            "airspace_consumed_in_period_cy": float(consumed),
            "measured_density_tons_per_cy": float(density),
            "void_reason": None,
            "status": "RECORDED",
        })
        if prior is not None:
            prior["status"] = "SUPERSEDED"
            touch(prior)
        S.sync_remaining_life(lf)
        S.apply_life_restriction(lf)
        touch(lf)
        return created(public(row))

    @endpoint(app, "/aerial-surveys/<aerial_survey_id>", ["GET"], ALL_ROLES)
    def read_survey(user_id, role, aerial_survey_id):
        return obj_response(public(get_or_404("aerial_survey", aerial_survey_id)))

    @endpoint(app, "/aerial-surveys", ["GET"], ALL_ROLES)
    def list_surveys(user_id, role):
        return paged(filtered(rows("aerial_survey"),
                              {"landfill_id": "landfill_id", "status": "status"}))

    @endpoint(app, "/aerial-surveys/<aerial_survey_id>/void", ["POST"],
              ["SurveyorOfRecord"])
    def void_survey(user_id, role, aerial_survey_id):
        b = Body()
        void_reason = b.string("void_reason")
        survey = get_or_404("aerial_survey", aerial_survey_id)
        if survey["status"] != "RECORDED":
            raise err("ERR_INVALID_STATE_TRANSITION",
                      "Only a RECORDED survey may be voided.")
        survey["status"] = "VOID"
        survey["void_reason"] = void_reason
        touch(survey)
        candidates = [s for s in S.surveys_of_landfill(survey["landfill_id"])
                      if s["status"] == "SUPERSEDED"]
        if candidates:
            best = sorted(candidates,
                          key=lambda s: (s["flown_on"], s["created_at"], s["_seq"]),
                          reverse=True)[0]
            best["status"] = "RECORDED"
            touch(best)
        lf = S.landfill_of(survey["landfill_id"])
        S.sync_remaining_life(lf)
        touch(lf)
        return obj_response(public(survey))
