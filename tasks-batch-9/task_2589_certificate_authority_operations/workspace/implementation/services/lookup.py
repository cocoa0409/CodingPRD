"""Existence resolution (PRD 2.8 band 3). The order in which a route calls
these helpers is the order of the catalogue in PRD 2.8."""

from db import db
from errors import fail


def _get(bucket, key, error_id, label):
    if not isinstance(key, str):
        fail(error_id, "%s not found." % label)
    record = bucket.get(key)
    if record is None:
        fail(error_id, "%s '%s' not found." % (label, key))
    return record


def get_profile(key):
    return _get(db.profiles, key, "ERR_PROFILE_NOT_FOUND", "Certificate profile")


def get_subscriber(key):
    return _get(db.subscribers, key, "ERR_SUBSCRIBER_NOT_FOUND", "Subscriber")


def get_vetting(key):
    return _get(db.vettings, key, "ERR_VETTING_NOT_FOUND", "Organization vetting")


def get_authorization(key):
    return _get(db.authorizations, key, "ERR_AUTHORIZATION_NOT_FOUND", "Domain authorization")


def get_request(key):
    return _get(db.requests, key, "ERR_REQUEST_NOT_FOUND", "Certificate request")


def get_certificate(key):
    return _get(db.certificates, key, "ERR_CERTIFICATE_NOT_FOUND", "Certificate")


def get_partition(key):
    return _get(db.partitions, key, "ERR_PARTITION_NOT_FOUND", "HSM partition")


def get_ceremony(key):
    return _get(db.ceremonies, key, "ERR_CEREMONY_NOT_FOUND", "Key ceremony")


def get_revocation_request(key):
    return _get(
        db.revocation_requests, key, "ERR_REVOCATION_REQUEST_NOT_FOUND", "Revocation request"
    )


def get_incident(key):
    return _get(db.incidents, key, "ERR_INCIDENT_NOT_FOUND", "Misissuance incident")


def get_audit(key):
    return _get(db.audits, key, "ERR_AUDIT_NOT_FOUND", "Root program audit")
