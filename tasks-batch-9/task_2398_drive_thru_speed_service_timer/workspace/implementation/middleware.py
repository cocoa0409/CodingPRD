"""Authentication, endpoint authorization, ownership scope and posture gating.

Header names and role spellings come from PRD §2.1 / scaffold validations 1-5.
"""

from flask import request

from constants import ROLES
from db import db
from errors import fail

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate(allowed_roles):
    """Ladder steps 1 and 2."""
    user_id = request.headers.get(HEADER_USER_ID)
    role = request.headers.get(HEADER_USER_ROLE)
    if not user_id or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-ID and a valid X-User-Role header are required")
    if role not in allowed_roles:
        fail("ERR_UNAUTHORIZED", "role %s may not call this endpoint" % role)
    return Actor(user_id, role)


# ------------------------------------------------------------- path resolution
def _lookup(collection, row_id, error_id):
    if not isinstance(row_id, str):
        fail(error_id)
    row = collection.get(row_id)
    if row is None:
        fail(error_id)
    return row


def get_restaurant(restaurant_id):
    return _lookup(db.restaurants, restaurant_id, "ERR_RESTAURANT_NOT_FOUND")


def get_profile(profile_id):
    return _lookup(db.daypart_profiles, profile_id, "ERR_PROFILE_NOT_FOUND")


def get_staff(staff_id):
    return _lookup(db.staff_members, staff_id, "ERR_STAFF_NOT_FOUND")


def get_deployment(deployment_id):
    return _lookup(db.deployments, deployment_id, "ERR_DEPLOYMENT_NOT_FOUND")


def get_loop(loop_id):
    return _lookup(db.timer_loops, loop_id, "ERR_LOOP_NOT_FOUND")


def get_slot(slot_id):
    return _lookup(db.merge_slots, slot_id, "ERR_SLOT_NOT_FOUND")


def get_pull_forward(pf_id):
    return _lookup(db.pull_forward_orders, pf_id, "ERR_PULL_FORWARD_NOT_FOUND")


def get_incident(incident_id):
    return _lookup(db.accuracy_incidents, incident_id, "ERR_INCIDENT_NOT_FOUND")


def get_report(report_id):
    return _lookup(db.throughput_reports, report_id, "ERR_REPORT_NOT_FOUND")


def get_coaching(coaching_id):
    return _lookup(db.coaching_interventions, coaching_id, "ERR_COACHING_NOT_FOUND")


def get_override(override_id):
    return _lookup(db.forecast_overrides, override_id, "ERR_OVERRIDE_NOT_FOUND")


# --------------------------------------------------------------- ownership scope
def operator_scope(actor, target_restaurant_id):
    """Ladder step 4 — Operator's X-User-ID is the target Restaurant.id.

    When the target identifier does not resolve to a store the comparison is
    deferred so the existence check (step 3 / step 7) can report the 404
    (PRD §2.12: existence always precedes ownership).
    """
    if actor.role != "Operator":
        return
    if not target_restaurant_id or target_restaurant_id not in db.restaurants:
        return
    if actor.user_id != target_restaurant_id:
        fail("ERR_RESTAURANT_SCOPE_MISMATCH",
             "acting Operator does not own restaurant %s" % target_restaurant_id)


def shift_leader_scope(actor, target_restaurant_id, staff_fk=None):
    """Ladder step 5 — ShiftLeader's X-User-ID is a StaffMember of the target store."""
    if actor.role != "ShiftLeader":
        return
    staff = db.staff_members.get(actor.user_id)
    if staff is None:
        fail("ERR_STAFF_SCOPE_MISMATCH", "acting X-User-ID is not a known team member")
    if target_restaurant_id and target_restaurant_id in db.restaurants:
        if staff["restaurant_id"] != target_restaurant_id:
            fail("ERR_STAFF_SCOPE_MISMATCH",
                 "acting team member does not belong to restaurant %s" % target_restaurant_id)
    if staff_fk is not None and actor.user_id != staff_fk:
        fail("ERR_STAFF_SCOPE_MISMATCH", "only the referenced team member may act here")


def scope(actor, target_restaurant_id, staff_fk=None):
    operator_scope(actor, target_restaurant_id)
    shift_leader_scope(actor, target_restaurant_id, staff_fk)


# ------------------------------------------------------------------ posture gate
def require_not_frozen(restaurant):
    """Ladder step 10 (PRD §2.6)."""
    if restaurant is not None and restaurant["service_posture"] == "FROZEN":
        fail("ERR_POSTURE_FROZEN", "the store is frozen; this mutation is blocked")


def require_not_accuracy_hold(restaurant):
    """Ladder step 11 — merge-award only."""
    if restaurant["service_posture"] == "ACCURACY_HOLD":
        fail("ERR_POSTURE_ACCURACY_HOLD", "the store is holding on accuracy")
