"""Existence resolution (PRD 2.6 / precedence step 3)."""
from errors import ApiError
from store import db


def _get(collection, identifier, error_id):
    if not isinstance(identifier, str):
        raise ApiError(error_id)
    record = collection.get(identifier)
    if record is None:
        raise ApiError(error_id)
    return record


def get_publication(identifier):
    return _get(db.publications, identifier, "ERR_PUBLICATION_NOT_FOUND")


def get_subscriber(identifier):
    return _get(db.subscribers, identifier, "ERR_SUBSCRIBER_NOT_FOUND")


def get_source_document(identifier):
    return _get(db.source_documents, identifier, "ERR_SOURCE_DOCUMENT_NOT_FOUND")


def get_qualification_request(identifier):
    return _get(db.qualification_requests, identifier, "ERR_QUALIFICATION_REQUEST_NOT_FOUND")


def get_statement(identifier):
    return _get(db.statements, identifier, "ERR_STATEMENT_NOT_FOUND")


def get_engagement(identifier):
    return _get(db.engagements, identifier, "ERR_ENGAGEMENT_NOT_FOUND")


def get_finding(identifier):
    return _get(db.findings, identifier, "ERR_FINDING_NOT_FOUND")


def get_contract(identifier):
    return _get(db.contracts, identifier, "ERR_CONTRACT_NOT_FOUND")


def get_make_good(identifier):
    return _get(db.make_goods, identifier, "ERR_MAKEGOOD_NOT_FOUND")


def get_snapshot(identifier):
    return _get(db.snapshots, identifier, "ERR_SNAPSHOT_NOT_FOUND")
