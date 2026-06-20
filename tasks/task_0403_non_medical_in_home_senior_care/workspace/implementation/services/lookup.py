"""Existence-tier lookups (PRD §2.5). Each raises the correct not-found error."""
import db
import errors
from errors import ApiError


def get_agency(agency_id):
    obj = db.agencies.get(agency_id)
    if obj is None:
        raise ApiError(errors.ERR_AGENCY_NOT_FOUND, 404, "Agency not found")
    return obj


def get_caregiver(caregiver_id):
    obj = db.caregivers.get(caregiver_id)
    if obj is None:
        raise ApiError(errors.ERR_CAREGIVER_NOT_FOUND, 404, "Caregiver not found")
    return obj


def get_client(client_id):
    obj = db.clients.get(client_id)
    if obj is None:
        raise ApiError(errors.ERR_CLIENT_NOT_FOUND, 404, "Client not found")
    return obj


def get_care_plan(plan_id):
    obj = db.care_plans.get(plan_id)
    if obj is None:
        raise ApiError(errors.ERR_CARE_PLAN_NOT_FOUND, 404, "Care plan not found")
    return obj


def get_care_task(plan_id, task_id):
    # A missing CareTask under a valid plan folds into ERR_CARE_PLAN_NOT_FOUND.
    obj = db.care_tasks.get(task_id)
    if obj is None or obj["care_plan_id"] != plan_id:
        raise ApiError(errors.ERR_CARE_PLAN_NOT_FOUND, 404, "Care task not found")
    return obj


def get_match(match_id):
    obj = db.matches.get(match_id)
    if obj is None:
        raise ApiError(errors.ERR_MATCH_NOT_FOUND, 404, "Match not found")
    return obj


def get_visit(visit_id):
    obj = db.visits.get(visit_id)
    if obj is None:
        raise ApiError(errors.ERR_VISIT_NOT_FOUND, 404, "Visit not found")
    return obj


def get_mileage(mileage_id):
    # A missing MileageEntry on /mileage/{id}/void folds into ERR_VISIT_NOT_FOUND.
    obj = db.mileage_entries.get(mileage_id)
    if obj is None:
        raise ApiError(errors.ERR_VISIT_NOT_FOUND, 404, "Mileage entry not found")
    return obj


def get_invoice(invoice_id):
    obj = db.invoices.get(invoice_id)
    if obj is None:
        raise ApiError(errors.ERR_INVOICE_NOT_FOUND, 404, "Invoice not found")
    return obj


def get_claim(claim_id):
    obj = db.ltc_claims.get(claim_id)
    if obj is None:
        raise ApiError(errors.ERR_CLAIM_NOT_FOUND, 404, "Claim not found")
    return obj
