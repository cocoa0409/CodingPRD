"""Path-parameter resolution (band 3) shared by every route module."""

import db
import errors as E


def _need(store, row_id, spec, label):
    row = store.get(row_id)
    if row is None:
        E.fail(spec, "%s %s does not exist." % (label, row_id))
    return row


def project(row_id):
    return _need(db.projects, row_id, E.ERR_PROJECT_NOT_FOUND, "Project")


def stage_gate(row_id):
    return _need(db.stage_gates, row_id, E.ERR_STAGE_GATE_NOT_FOUND, "Stage gate")


def gate_review(row_id):
    return _need(db.gate_reviews, row_id, E.ERR_GATE_REVIEW_NOT_FOUND, "Gate review")


def deliverable(row_id):
    return _need(db.deliverables, row_id, E.ERR_DELIVERABLE_NOT_FOUND, "Deliverable")


def prerequisite(row_id):
    return _need(db.deliverables, row_id, E.ERR_PREREQUISITE_NOT_FOUND, "Prerequisite")


def business_case(row_id):
    return _need(db.business_cases, row_id, E.ERR_BUSINESS_CASE_NOT_FOUND,
                 "Business case")


def formulation(row_id):
    return _need(db.formulations, row_id, E.ERR_FORMULATION_NOT_FOUND, "Formulation")


def pilot_line(row_id):
    return _need(db.pilot_lines, row_id, E.ERR_PILOT_LINE_NOT_FOUND, "Pilot line")


def pilot_run(row_id):
    return _need(db.pilot_runs, row_id, E.ERR_PILOT_RUN_NOT_FOUND, "Pilot run")


def study(row_id):
    return _need(db.shelf_life_studies, row_id, E.ERR_SHELF_LIFE_STUDY_NOT_FOUND,
                 "Shelf life study")


def label(row_id):
    return _need(db.label_approvals, row_id, E.ERR_LABEL_APPROVAL_NOT_FOUND,
                 "Label approval")


def retailer(row_id):
    return _need(db.retailers, row_id, E.ERR_RETAILER_NOT_FOUND, "Retailer")


def reset_window(row_id):
    return _need(db.shelf_reset_windows, row_id, E.ERR_RESET_WINDOW_NOT_FOUND,
                 "Reset window")


def presentation(row_id):
    return _need(db.sell_in_presentations, row_id, E.ERR_PRESENTATION_NOT_FOUND,
                 "Presentation")
