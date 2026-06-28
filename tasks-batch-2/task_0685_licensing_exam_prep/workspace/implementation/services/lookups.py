"""Existence (priority 3) + ownership (priority 4) lookups."""
from db import db
from errors import raise_err
import errors


def get_or_404(collection, rid):
    rec = collection.get(rid)
    if rec is None:
        raise_err(errors.ERR_NOT_FOUND, "resource not found")
    return rec


def get_license_program(rid):
    return get_or_404(db.license_programs, rid)


def get_subscription_plan(rid):
    return get_or_404(db.subscription_plans, rid)


def get_ce_bundle(rid):
    return get_or_404(db.ce_bundles, rid)


def get_learner(rid):
    return get_or_404(db.learners, rid)


def get_enrollment(rid):
    return get_or_404(db.enrollments, rid)


def get_cohort(rid):
    return get_or_404(db.cohorts, rid)


def get_claim(rid):
    return get_or_404(db.pass_guarantee_claims, rid)


def get_membership(rid):
    return get_or_404(db.cohort_memberships, rid)


def get_installment_scoped(enrollment_id, installment_id):
    """Validate the installment exists AND belongs to the enrollment (nested
    ownership, PRD §2.6)."""
    rec = db.installments.get(installment_id)
    if rec is None or rec["enrollment_id"] != enrollment_id:
        raise_err(errors.ERR_NOT_FOUND, "installment not found")
    return rec


def get_membership_scoped(cohort_id, membership_id):
    rec = db.cohort_memberships.get(membership_id)
    if rec is None or rec["cohort_id"] != cohort_id:
        raise_err(errors.ERR_NOT_FOUND, "membership not found")
    return rec


def assert_owner(enrollment, user_id):
    """Learner ownership (priority 4): X-User-ID equals Enrollment.learner_id."""
    if enrollment["learner_id"] != user_id:
        raise_err(errors.ERR_NOT_RESOURCE_OWNER, "not the resource owner")
