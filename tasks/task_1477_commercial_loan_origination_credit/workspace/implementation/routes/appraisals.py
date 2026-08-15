"""Appraisers and appraisals: registry, engagement ordering, report review."""
from flask import Blueprint

import serialize
from db import STORE, new_entity, touch
from errors import (
    raise_err, ERR_VALIDATION, ERR_INVALID_STATE, ERR_APPRAISER_NOT_ELIGIBLE,
    ERR_APPRAISER_WINDOW_CONFLICT,
)
from middleware import require_roles, ALL_ROLES
from response import success_object
from routes.common import get_or_404, render_list, body_fk_exists
from services.collateral import COLLATERAL_CLASSES, compute_eligible_values
from validation import get_body, req_str, req_int, req_enum, opt_str, opt_enum, opt_int, req_date

bp = Blueprint("appraisals", __name__)

APPRAISER_STATUSES = {"ELIGIBLE", "SUSPENDED"}
ORDERABLE_APP_STAGES = {"APPRAISAL_REVIEW", "EXCEPTION_REVIEW", "COMMITTEE_REVIEW"}
ACTIVE_ENGAGEMENT_STATUSES = {"ENGAGED", "REPORT_RECEIVED"}


@bp.post("/credit/appraisers")
def create_appraiser():
    require_roles("AppraisalManager")
    body = get_body()
    name = req_str(body, "name")
    license_number = req_str(body, "license_number")
    max_engagements = opt_int(body, "max_concurrent_engagements", 2)
    if max_engagements < 1:
        raise_err(ERR_VALIDATION, "Field 'max_concurrent_engagements' must be at least 1.")
    appraiser = new_entity()
    appraiser.update({
        'name': name,
        'license_number': license_number,
        'max_concurrent_engagements': max_engagements,
        'status': 'ELIGIBLE',
    })
    STORE.appraisers[appraiser['id']] = appraiser
    return success_object(serialize.appraiser(appraiser), status=201)


@bp.get("/credit/appraisers/<aid>")
def get_appraiser(aid):
    require_roles(*ALL_ROLES)
    appraiser = get_or_404(STORE.appraisers, aid, "Appraiser")
    return success_object(serialize.appraiser(appraiser))


@bp.patch("/credit/appraisers/<aid>")
def update_appraiser(aid):
    require_roles("AppraisalManager")
    appraiser = get_or_404(STORE.appraisers, aid, "Appraiser")
    body = get_body()
    name = opt_str(body, "name")
    status = opt_enum(body, "status", APPRAISER_STATUSES)
    if name is not None:
        appraiser['name'] = name
    if status is not None:
        appraiser['status'] = status
    touch(appraiser)
    return success_object(serialize.appraiser(appraiser))


@bp.get("/credit/appraisers/<aid>/appraisals")
def appraiser_appraisals(aid):
    require_roles(*ALL_ROLES)
    get_or_404(STORE.appraisers, aid, "Appraiser")
    items = [a for a in STORE.appraisals.values() if a['appraiser_id'] == aid]
    return render_list(items, serialize.appraisal)


@bp.post("/credit/appraisals")
def order_appraisal():
    require_roles("AppraisalManager")
    body = get_body()
    app_id = req_str(body, "loan_application_id")
    appraiser_id = req_str(body, "appraiser_id")
    collateral_class = req_enum(body, "collateral_class", COLLATERAL_CLASSES)
    start = req_date(body, "engagement_start_date")
    end = req_date(body, "engagement_end_date")
    if end < start:
        raise_err(ERR_VALIDATION, "engagement_end_date must be on or after engagement_start_date.")
    body_fk_exists(STORE.loan_applications, app_id, "LoanApplication")
    body_fk_exists(STORE.appraisers, appraiser_id, "Appraiser")

    app = STORE.loan_applications[app_id]
    if app['status'] not in ORDERABLE_APP_STAGES:
        raise_err(ERR_INVALID_STATE,
                  "Application status %s does not permit ordering appraisals." % app['status'])

    appraiser = STORE.appraisers[appraiser_id]
    if appraiser['status'] != 'ELIGIBLE':
        raise_err(ERR_APPRAISER_NOT_ELIGIBLE, "Appraiser status is %s." % appraiser['status'])

    # Aggregate closed-interval capacity: adjacent end == start IS a conflict.
    overlapping = 0
    for existing in STORE.appraisals.values():
        if existing['appraiser_id'] != appraiser_id:
            continue
        if existing['status'] not in ACTIVE_ENGAGEMENT_STATUSES:
            continue
        if existing['engagement_start_date'] <= end and start <= existing['engagement_end_date']:
            overlapping += 1
    if overlapping >= appraiser['max_concurrent_engagements']:
        raise_err(ERR_APPRAISER_WINDOW_CONFLICT,
                  "Appraiser engagement window capacity (%d) would be exceeded." % appraiser['max_concurrent_engagements'])

    appraisal = new_entity()
    appraisal.update({
        'loan_application_id': app_id,
        'appraiser_id': appraiser_id,
        'collateral_class': collateral_class,
        'engagement_start_date': start,
        'engagement_end_date': end,
        'appraised_value_cents': None,
        'orderly_liquidation_value_cents': None,
        'eligible_value_cents': None,
        'liquidation_basis_value_cents': None,
        'status': 'ENGAGED',
    })
    STORE.appraisals[appraisal['id']] = appraisal
    return success_object(serialize.appraisal(appraisal), status=201)


@bp.get("/credit/loan-applications/<aid>/appraisals")
def application_appraisals(aid):
    require_roles(*ALL_ROLES)
    get_or_404(STORE.loan_applications, aid, "LoanApplication")
    from services import exposure
    return render_list(exposure.appraisals_of_app(aid), serialize.appraisal)


@bp.post("/credit/appraisals/<aid>/receive-report")
def receive_report(aid):
    require_roles("AppraisalManager")
    appraisal = get_or_404(STORE.appraisals, aid, "Appraisal")
    body = get_body()
    appraised_value = req_int(body, "appraised_value_cents")
    if appraised_value <= 0:
        raise_err(ERR_VALIDATION, "Field 'appraised_value_cents' must be strictly greater than zero.")
    liquidation_value = req_int(body, "orderly_liquidation_value_cents")
    if liquidation_value <= 0:
        raise_err(ERR_VALIDATION, "Field 'orderly_liquidation_value_cents' must be strictly greater than zero.")
    if appraisal['status'] != 'ENGAGED':
        raise_err(ERR_INVALID_STATE, "Appraisal status is %s; receive-report requires ENGAGED." % appraisal['status'])
    appraisal['appraised_value_cents'] = appraised_value
    appraisal['orderly_liquidation_value_cents'] = liquidation_value
    appraisal['status'] = 'REPORT_RECEIVED'
    touch(appraisal)
    return success_object(serialize.appraisal(appraisal))


@bp.post("/credit/appraisals/<aid>/review")
def review_appraisal(aid):
    require_roles("AppraisalManager")
    appraisal = get_or_404(STORE.appraisals, aid, "Appraisal")
    body = get_body()
    outcome = req_enum(body, "outcome", {"ACCEPTED", "REJECTED"})
    if appraisal['status'] != 'REPORT_RECEIVED':
        raise_err(ERR_INVALID_STATE, "Appraisal status is %s; review requires REPORT_RECEIVED." % appraisal['status'])
    if outcome == 'ACCEPTED':
        eligible, liquidation = compute_eligible_values(
            appraisal['appraised_value_cents'],
            appraisal['orderly_liquidation_value_cents'],
            appraisal['collateral_class'])
        appraisal['eligible_value_cents'] = eligible
        appraisal['liquidation_basis_value_cents'] = liquidation
        appraisal['status'] = 'ACCEPTED'
    else:
        appraisal['status'] = 'REJECTED'
    touch(appraisal)
    return success_object(serialize.appraisal(appraisal))
