"""Authorized-representative effectiveness and scope helpers."""

import db
from errors import fail


def is_effective(rep, moment):
    """The designation must be DESIGNATED and the moment must sit inside the
    half-open window [effective_from, effective_to)."""
    if rep["designation_status"] != "DESIGNATED":
        return False
    if moment < rep["effective_from"]:
        return False
    if rep["effective_to"] is not None and moment >= rep["effective_to"]:
        return False
    return True


def scopes_intersect(left, right):
    """BOTH intersects everything; SUBMIT_TAKEDOWN and AUTHORIZE_LITIGATION do
    not intersect each other."""
    if left == "BOTH" or right == "BOTH":
        return True
    return left == right


def has_scope(rep, needed):
    return scopes_intersect(rep["authority_scope"], needed)


def require_effective(rep):
    if not is_effective(rep, db.now()):
        fail("ERR_REPRESENTATIVE_NOT_EFFECTIVE")


def require_scope(rep, needed):
    if not has_scope(rep, needed):
        fail("ERR_REPRESENTATIVE_SCOPE_INSUFFICIENT")


def windows_overlap(a_from, a_to, b_from, b_to):
    """Half-open comparison: a_from < b_to AND b_from < a_to.  Adjacency (one
    window ending exactly where the next begins) is allowed."""
    if a_to is not None and not (a_from < a_to):
        return False
    left = (a_to is None) or (b_from < a_to)
    right = (b_to is None) or (a_from < b_to)
    return left and right


def check_designation_overlap(enrollment_id, authority_scope, effective_from,
                              effective_to, exclude_id=None):
    for rep in db.values("representatives"):
        if rep["enrollment_id"] != enrollment_id:
            continue
        if rep["id"] == exclude_id:
            continue
        if rep["designation_status"] != "DESIGNATED":
            continue
        if not scopes_intersect(rep["authority_scope"], authority_scope):
            continue
        if windows_overlap(effective_from, effective_to, rep["effective_from"],
                           rep["effective_to"]):
            fail("ERR_REPRESENTATIVE_WINDOW_OVERLAP")
