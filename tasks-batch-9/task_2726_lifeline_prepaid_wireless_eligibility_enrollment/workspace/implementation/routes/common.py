"""Shared row lookups. Every miss raises the entity-specific not-found code."""
import db
from errors import ApiError
from middleware import (ALL_ROLES, COMPLIANCE_AUDITOR, NATIONAL_VERIFIER,
                        PROGRAM_ADMINISTRATOR, PROVIDER_AGENT, SUBSCRIBER,
                        authenticate, require_provider_owner,
                        require_subscriber_owner)

ROLES_ALL = ALL_ROLES


def _get(bucket, row_id, error_id):
    if not isinstance(row_id, str):
        raise ApiError(error_id)
    row = bucket.get(row_id)
    if row is None:
        raise ApiError(error_id)
    return row


def get_provider(row_id):
    return _get(db.db.providers, row_id, "ERR_PROVIDER_NOT_FOUND")


def get_address(row_id):
    return _get(db.db.addresses, row_id, "ERR_ADDRESS_NOT_FOUND")


def get_subscriber(row_id):
    return _get(db.db.subscribers, row_id, "ERR_SUBSCRIBER_NOT_FOUND")


def get_check(row_id):
    return _get(db.db.eligibility_checks, row_id, "ERR_ELIGIBILITY_CHECK_NOT_FOUND")


def get_enrollment(row_id):
    return _get(db.db.enrollments, row_id, "ERR_ENROLLMENT_NOT_FOUND")


def get_device(row_id):
    return _get(db.db.devices, row_id, "ERR_DEVICE_NOT_FOUND")


def get_transfer(row_id):
    return _get(db.db.service_transfers, row_id, "ERR_SERVICE_TRANSFER_NOT_FOUND")


def get_claim(row_id):
    return _get(db.db.claims, row_id, "ERR_CLAIM_NOT_FOUND")


def get_sample(row_id):
    return _get(db.db.audit_samples, row_id, "ERR_AUDIT_SAMPLE_NOT_FOUND")


def get_case(row_id):
    return _get(db.db.cases, row_id, "ERR_CASE_NOT_FOUND")


QUALIFYING_BENEFITS = ("NONE", "SNAP", "MEDICAID", "SSI", "FPHA",
                       "VETERANS_PENSION", "TRIBAL_TANF", "BIA_GENERAL_ASSISTANCE")
MATCHED_BENEFITS = ("SNAP", "MEDICAID", "SSI", "FPHA", "VETERANS_PENSION",
                    "TRIBAL_TANF", "BIA_GENERAL_ASSISTANCE")
TRIBAL_ONLY_BENEFITS = ("TRIBAL_TANF", "BIA_GENERAL_ASSISTANCE")
SERVICE_TYPES = ("VOICE", "BROADBAND", "BUNDLED")
SUBSCRIBER_STATUSES = ("PROSPECT", "ELIGIBILITY_PENDING", "VERIFIED_ELIGIBLE",
                       "DUPLICATE_HOLD", "ENROLLED", "DE_ENROLLED", "BARRED")
ELIGIBILITY_BASES = ("NONE", "INCOME", "BENEFIT", "TRIBAL_BENEFIT")
CHECK_STATUSES = ("PENDING_VERIFIER", "DOCUMENTATION_REQUIRED",
                  "ELIGIBLE_CONFIRMED", "INELIGIBLE")
CLAIMED_BASES = ("INCOME", "BENEFIT")
BENEFIT_STATUSES = ("ACTIVE", "DE_ENROLLED")
USAGE_STATUSES = ("PENDING_FIRST_USE", "USING", "NON_USAGE_FLAGGED", "CURE_EXPIRED")
RECERT_STATUSES = ("NOT_DUE", "NOTICED", "NON_RESPONSIVE", "RESPONDED_INELIGIBLE")
DEVICE_DIMENSION_STATUSES = ("AWAITING_DEVICE", "DEVICE_ISSUED", "RECLAIM_PENDING")
DEVICE_STATUSES = ("IN_STOCK", "ISSUED", "RECLAIM_PENDING", "RETIRED", "LOST")
MODEL_TIERS = ("BASIC", "STANDARD", "SMART")
RETURN_CONDITIONS = ("GOOD", "DAMAGED", "LOST")
TRANSFER_STATUSES = ("REQUESTED", "ACCEPTED_COMPLETED", "REJECTED", "SUPERSEDED")
REJECTION_REASONS = ("CONSENT_INVALID", "TARGET_CAPACITY", "OTHER")
CLAIM_STATUSES = ("DRAFT", "FILED", "UNDER_AUDIT", "AUDIT_PASSED", "AUDIT_FAILED",
                  "HELD", "SUPERSEDED")
SAMPLE_STATUSES = ("DRAWN", "ADJUDICATED_PASS", "ADJUDICATED_FAIL")
FINDINGS = ("COMPLIANT", "INELIGIBLE_SUBSCRIBER", "DUPLICATE_HOUSEHOLD",
            "NON_USAGE_UNCURED", "MISSING_CERTIFICATION")
CASE_TYPES = ("SERVICE_COMPLAINT", "DE_ENROLLMENT_APPEAL")
CASE_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "REMANDED", "GRANTED", "DENIED",
                 "RESOLVED")
DECISIONS = ("GRANT_REINSTATE", "DENY", "RESOLVE_WITH_CREDIT", "REMAND")
DE_ENROLLMENT_REASONS = ("NON_USAGE", "RECERT_NON_RESPONSE", "INELIGIBLE_ON_RECERT",
                         "DUPLICATE_HOUSEHOLD", "SUBSCRIBER_REQUEST",
                         "AUDIT_INELIGIBLE")
MANUAL_DE_ENROLLMENT_REASONS = ("SUBSCRIBER_REQUEST", "DUPLICATE_HOUSEHOLD")
ADDRESS_STATUSES = ("UNVERIFIED", "DUPLICATE_FLAGGED", "RESOLVED_MULTI_HOUSEHOLD",
                    "RESOLVED_SINGLE_HOUSEHOLD")
PROVIDER_STATUSES = ("ACTIVE", "SUSPENDED")
