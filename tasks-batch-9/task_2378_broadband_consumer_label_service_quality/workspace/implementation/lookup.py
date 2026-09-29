"""Existence resolution (ladder step 4 — PRD §2.6)."""

import db
import errors
from errors import fail


def _find(table, identifier, error_id):
    if not isinstance(identifier, str):
        fail(error_id)
    record = table.get(identifier)
    if record is None:
        fail(error_id)
    return record


def service_plan(identifier):
    return _find(db.store.service_plans, identifier,
                 errors.ERR_SERVICE_PLAN_NOT_FOUND)


def methodology_document(identifier):
    return _find(db.store.methodology_documents, identifier,
                 errors.ERR_METHODOLOGY_DOCUMENT_NOT_FOUND)


def measurement_probe(identifier):
    return _find(db.store.measurement_probes, identifier,
                 errors.ERR_MEASUREMENT_PROBE_NOT_FOUND)


def test_run(identifier):
    return _find(db.store.test_runs, identifier, errors.ERR_TEST_RUN_NOT_FOUND)


def attestation(identifier):
    return _find(db.store.attestations, identifier,
                 errors.ERR_ATTESTATION_NOT_FOUND)


def label_version(identifier):
    return _find(db.store.label_versions, identifier,
                 errors.ERR_LABEL_VERSION_NOT_FOUND)


def label_translation(identifier):
    return _find(db.store.label_translations, identifier,
                 errors.ERR_TRANSLATION_NOT_FOUND)


def subscriber_account(identifier):
    return _find(db.store.subscriber_accounts, identifier,
                 errors.ERR_SUBSCRIBER_ACCOUNT_NOT_FOUND)


def complaint(identifier):
    return _find(db.store.complaints, identifier,
                 errors.ERR_COMPLAINT_NOT_FOUND)


def remediation_credit(identifier):
    return _find(db.store.remediation_credits, identifier,
                 errors.ERR_REMEDIATION_CREDIT_NOT_FOUND)


def regulator_inquiry(identifier):
    return _find(db.store.regulator_inquiries, identifier,
                 errors.ERR_REGULATOR_INQUIRY_NOT_FOUND)


def plan_change_notice(identifier):
    return _find(db.store.plan_change_notices, identifier,
                 errors.ERR_PLAN_CHANGE_NOTICE_NOT_FOUND)


def translation_of_label(label, translation_id):
    """Resolve left-to-right: the label first, then its translation (§2.6)."""
    record = db.store.label_translations.get(translation_id)
    if record is None or record["label_version_id"] != label["id"]:
        fail(errors.ERR_TRANSLATION_NOT_FOUND)
    return record
