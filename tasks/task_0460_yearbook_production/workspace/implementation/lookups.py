"""Path/body resource lookups with the correct not-found errors.

Path-referenced resources -> ERR_NOT_FOUND (404).
Body-referenced FK targets -> ERR_REFERENCE_NOT_FOUND (404).
"""
from db import db
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_REFERENCE_NOT_FOUND,
)


def get_path(collection, resource_id):
    rec = collection.get(resource_id)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Resource not found")
    return rec


def get_yearbook_path(yearbook_id):
    return get_path(db.yearbooks, yearbook_id)


def get_page_path(page_id):
    return get_path(db.ladder_pages, page_id)


def get_submission_path(submission_id):
    return get_path(db.submissions, submission_id)


def get_assignment_path(assignment_id):
    return get_path(db.staff_assignments, assignment_id)


def get_contract_path(contract_id):
    return get_path(db.ad_contracts, contract_id)


def get_proof_path(proof_id):
    return get_path(db.proofs, proof_id)


def get_order_path(order_id):
    return get_path(db.presale_orders, order_id)


def get_print_run_path(print_run_id):
    return get_path(db.print_runs, print_run_id)


def get_distribution_path(record_id):
    return get_path(db.distribution_records, record_id)


def get_ref(collection, resource_id):
    rec = collection.get(resource_id)
    if rec is None:
        raise ApiError(ERR_REFERENCE_NOT_FOUND, 404, "Referenced resource not found")
    return rec
