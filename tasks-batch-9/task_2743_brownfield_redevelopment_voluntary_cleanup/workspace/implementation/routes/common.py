"""Shared route helpers: path/body resolution and ownership checks."""

import db
from errors import ApiError
from middleware import actor_id

NOT_FOUND = {
    "parties": "ERR_PARTY_NOT_FOUND",
    "laboratories": "ERR_LAB_NOT_FOUND",
    "sites": "ERR_SITE_NOT_FOUND",
    "assessment_phases": "ERR_PHASE_NOT_FOUND",
    "contaminant_findings": "ERR_FINDING_NOT_FOUND",
    "cleanup_goals": "ERR_GOAL_NOT_FOUND",
    "liability_protections": "ERR_PROTECTION_NOT_FOUND",
    "continuing_obligations": "ERR_OBLIGATION_NOT_FOUND",
    "vcp_enrollments": "ERR_ENROLLMENT_NOT_FOUND",
    "remedial_action_plans": "ERR_PLAN_NOT_FOUND",
    "cost_cap_policies": "ERR_POLICY_NOT_FOUND",
    "site_controls": "ERR_CONTROL_NOT_FOUND",
    "funding_awards": "ERR_AWARD_NOT_FOUND",
    "nfa_letters": "ERR_LETTER_NOT_FOUND",
    "monitoring_events": "ERR_EVENT_NOT_FOUND",
}


def fetch(collection, row_id):
    row = db.get(collection, row_id)
    if row is None:
        raise ApiError(NOT_FOUND[collection],
                       "%s not found." % collection.rstrip("s").replace("_", " "))
    return row


def site_or_404(site_id):
    return fetch("sites", site_id)


def party_or_404(party_id):
    return fetch("parties", party_id)


def require_owner(site):
    """Priority 6: the acting Redeveloper must own the parcel."""
    if actor_id() != site["owner_party_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "Acting user does not own parcel %s." % site["id"])


def require_party_type(party, expected):
    """Priority 8: party typing."""
    if party["party_type"] != expected:
        raise ApiError("ERR_PARTY_TYPE_MISMATCH",
                       "Party %s must have party_type %s." % (party["id"], expected))


def acting_party_of_type(expected):
    party = db.get("parties", actor_id())
    if party is None or party["party_type"] != expected:
        raise ApiError("ERR_PARTY_TYPE_MISMATCH",
                       "Acting user must be a %s party." % expected)
    return party


def apply_filter(rows, field, value):
    if value is None:
        return rows
    return [r for r in rows if r.get(field) == value]
