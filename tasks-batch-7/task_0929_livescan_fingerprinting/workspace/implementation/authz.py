"""Rungs 1 and 2 of the ordered validation ladder, plus the rung 7 freeze sets."""

from flask import g, request

from constants import ROLES
from errors import ApiError

# (METHOD, flask rule) -> the endpoint's authorized-role list of PRD section 4.
ENDPOINT_ROLES = {
    ("POST", "/livescan/agencies"): ["VendorAdmin"],
    ("GET", "/livescan/agencies/<id>"): ["VendorAdmin", "AgencyAdjudicator", "SiteSupervisor"],
    ("POST", "/livescan/oris"): ["VendorAdmin"],
    ("GET", "/livescan/oris/<id>"): [
        "VendorAdmin", "AgencyAdjudicator", "SiteSupervisor", "LivescanTechnician"],
    ("GET", "/livescan/oris"): [
        "VendorAdmin", "AgencyAdjudicator", "SiteSupervisor", "LivescanTechnician"],
    ("POST", "/livescan/oris/<id>/authority-status"): ["VendorAdmin"],
    ("POST", "/livescan/service-types"): ["VendorAdmin"],
    ("GET", "/livescan/service-types/<id>"): [
        "VendorAdmin", "AgencyAdjudicator", "LivescanTechnician", "Applicant"],
    ("GET", "/livescan/service-types"): [
        "VendorAdmin", "AgencyAdjudicator", "LivescanTechnician", "Applicant"],
    ("POST", "/livescan/sites"): ["VendorAdmin"],
    ("GET", "/livescan/sites/<id>"): [
        "VendorAdmin", "SiteSupervisor", "LivescanTechnician", "AgencyAdjudicator"],
    ("GET", "/livescan/sites"): [
        "VendorAdmin", "SiteSupervisor", "LivescanTechnician", "AgencyAdjudicator", "Applicant"],
    ("POST", "/livescan/sites/<id>/event-reconciliation"): ["VendorAdmin"],
    ("POST", "/livescan/devices"): ["VendorAdmin"],
    ("GET", "/livescan/devices/<id>"): ["VendorAdmin", "SiteSupervisor", "LivescanTechnician"],
    ("GET", "/livescan/devices"): ["VendorAdmin", "SiteSupervisor", "LivescanTechnician"],
    ("POST", "/livescan/devices/<id>/calibration"): ["VendorAdmin"],
    ("POST", "/livescan/devices/<id>/calibration-audit"): ["VendorAdmin"],
    ("POST", "/livescan/device-assignments"): ["VendorAdmin", "SiteSupervisor"],
    ("GET", "/livescan/device-assignments/<id>"): [
        "VendorAdmin", "SiteSupervisor", "LivescanTechnician"],
    ("GET", "/livescan/device-assignments"): [
        "VendorAdmin", "SiteSupervisor", "LivescanTechnician"],
    ("POST", "/livescan/device-assignments/<id>/release"): ["SiteSupervisor"],
    ("POST", "/livescan/applicants"): ["Applicant", "LivescanTechnician"],
    ("GET", "/livescan/applicants/<id>"): [
        "Applicant", "LivescanTechnician", "VendorAdmin", "AgencyAdjudicator"],
    ("PATCH", "/livescan/applicants/<id>"): ["Applicant", "LivescanTechnician"],
    ("POST", "/livescan/appointments"): ["Applicant", "LivescanTechnician"],
    ("GET", "/livescan/appointments/<id>"): [
        "Applicant", "LivescanTechnician", "SiteSupervisor", "VendorAdmin"],
    ("GET", "/livescan/appointments"): [
        "Applicant", "LivescanTechnician", "SiteSupervisor", "VendorAdmin"],
    ("POST", "/livescan/appointments/<id>/reschedule"): ["Applicant", "LivescanTechnician"],
    ("POST", "/livescan/appointments/<id>/cancel"): ["Applicant", "LivescanTechnician"],
    ("POST", "/livescan/appointments/<id>/check-in"): ["LivescanTechnician"],
    ("POST", "/livescan/appointments/<id>/no-show"): ["LivescanTechnician"],
    ("POST", "/livescan/cards"): ["LivescanTechnician"],
    ("GET", "/livescan/cards/<id>"): [
        "LivescanTechnician", "SiteSupervisor", "VendorAdmin", "AgencyAdjudicator"],
    ("GET", "/livescan/cards"): [
        "LivescanTechnician", "SiteSupervisor", "VendorAdmin", "AgencyAdjudicator"],
    ("GET", "/livescan/cards/<id>/positions"): [
        "LivescanTechnician", "SiteSupervisor", "VendorAdmin"],
    ("POST", "/livescan/cards/<id>/positions/<position_code>/attempts"): ["LivescanTechnician"],
    ("POST", "/livescan/cards/<id>/positions/<position_code>/exception"): ["LivescanTechnician"],
    ("POST", "/livescan/cards/<id>/exception-override"): ["SiteSupervisor"],
    ("POST", "/livescan/cards/<id>/finalize"): ["LivescanTechnician"],
    ("POST", "/livescan/submissions"): ["LivescanTechnician"],
    ("GET", "/livescan/submissions/<id>"): [
        "LivescanTechnician", "SiteSupervisor", "VendorAdmin", "AgencyAdjudicator", "Applicant"],
    ("GET", "/livescan/submissions"): [
        "LivescanTechnician", "SiteSupervisor", "VendorAdmin", "AgencyAdjudicator"],
    ("POST", "/livescan/submissions/<id>/destination-results"): ["StateRepository"],
    ("GET", "/livescan/submissions/<id>/responses"): [
        "AgencyAdjudicator", "VendorAdmin", "StateRepository"],
    ("GET", "/livescan/chr-responses/<id>"): ["AgencyAdjudicator", "Applicant", "VendorAdmin"],
    ("POST", "/livescan/submissions/<id>/reprints"): ["SiteSupervisor"],
    ("POST", "/livescan/submissions/<id>/purge-requests"): ["Applicant", "AgencyAdjudicator"],
    ("POST", "/livescan/submissions/<id>/purge-decisions"): ["VendorAdmin"],
    ("POST", "/livescan/fitness-determinations"): ["AgencyAdjudicator"],
    ("GET", "/livescan/fitness-determinations/<id>"): [
        "AgencyAdjudicator", "Applicant", "VendorAdmin"],
    ("GET", "/livescan/fitness-determinations"): [
        "AgencyAdjudicator", "Applicant", "VendorAdmin"],
    ("POST", "/livescan/fitness-determinations/<id>/challenges"): ["Applicant"],
    ("POST", "/livescan/fitness-determinations/<id>/challenge-resolutions"): ["AgencyAdjudicator"],
    ("POST", "/livescan/rapback-subscriptions"): ["AgencyAdjudicator"],
    ("GET", "/livescan/rapback-subscriptions/<id>"): [
        "AgencyAdjudicator", "VendorAdmin", "StateRepository"],
    ("GET", "/livescan/rapback-subscriptions"): [
        "AgencyAdjudicator", "VendorAdmin", "StateRepository"],
    ("POST", "/livescan/rapback-subscriptions/<id>/renew"): ["AgencyAdjudicator"],
    ("POST", "/livescan/rapback-subscriptions/<id>/cancel"): ["AgencyAdjudicator"],
    ("POST", "/livescan/rapback-notifications"): ["StateRepository"],
    ("GET", "/livescan/rapback-notifications/<id>"): [
        "AgencyAdjudicator", "VendorAdmin", "StateRepository"],
    ("GET", "/livescan/rapback-notifications"): [
        "AgencyAdjudicator", "VendorAdmin", "StateRepository"],
    ("POST", "/livescan/rapback-notifications/<id>/acknowledge"): ["AgencyAdjudicator"],
    ("GET", "/livescan/fee-assessments/<id>"): [
        "VendorAdmin", "AgencyAdjudicator", "LivescanTechnician", "Applicant"],
    ("GET", "/livescan/fee-assessments"): [
        "VendorAdmin", "AgencyAdjudicator", "LivescanTechnician", "Applicant"],
    ("POST", "/livescan/fee-assessments/<id>/payments"): ["LivescanTechnician", "Applicant"],
    ("POST", "/livescan/invoices"): ["VendorAdmin"],
    ("GET", "/livescan/invoices/<id>"): ["VendorAdmin", "AgencyAdjudicator"],
    ("GET", "/livescan/invoices"): ["VendorAdmin", "AgencyAdjudicator"],
    ("POST", "/livescan/invoices/<id>/issue"): ["VendorAdmin"],
    ("POST", "/livescan/invoices/<id>/payments"): ["VendorAdmin"],
    ("POST", "/livescan/_ops/aging-run"): ["VendorAdmin"],
    ("POST", "/livescan/_clock/set_current_utc"): ["VendorAdmin"],
}

# PRD 2.10 -- the closed enumeration of the thirteen frozen operations.
FROZEN_OPERATIONS = {
    ("POST", "/livescan/service-types"),
    ("POST", "/livescan/appointments"),
    ("POST", "/livescan/cards"),
    ("POST", "/livescan/cards/<id>/positions/<position_code>/attempts"),
    ("POST", "/livescan/cards/<id>/positions/<position_code>/exception"),
    ("POST", "/livescan/cards/<id>/exception-override"),
    ("POST", "/livescan/cards/<id>/finalize"),
    ("POST", "/livescan/submissions"),
    ("POST", "/livescan/submissions/<id>/reprints"),
    ("POST", "/livescan/rapback-subscriptions"),
    ("POST", "/livescan/rapback-subscriptions/<id>/renew"),
    ("POST", "/livescan/fitness-determinations"),
    ("POST", "/livescan/device-assignments"),
}


def authenticate():
    """Rung 1 -- runs before anything else, including path resolution."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip() or not role or not role.strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role are required")
    g.user_id = user_id
    g.role = role


def authorize():
    """Rung 2 -- role membership, checked before any path resource is looked up."""
    rule = request.url_rule
    if rule is None:
        return
    key = (request.method, rule.rule)
    allowed = ENDPOINT_ROLES.get(key)
    if allowed is None:
        return
    if g.role not in ROLES or g.role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", "role %s may not call this endpoint" % g.role)


def endpoint_key():
    rule = request.url_rule
    if rule is None:
        return None
    return (request.method, rule.rule)


def is_frozen_operation():
    return endpoint_key() in FROZEN_OPERATIONS
