"""Core domain logic: risk scoring, grant lifecycle, identity counter
reconciliation, SoD evaluation, audit evidence.

All numeric inputs are integers, so risk is integer points with no rounding
(PRD §2.7). Every recompute that changes a stored/derived field is a mutation
and bumps that resource's updated_at + version (PRD §2.4).
"""
import db
from db import touch
from response import now_iso

# Risk constants (SCAFFOLD §1.3 / PRD §2.7)
PRIVILEGED_STEP = 25
PRIVILEGED_CAP_STEPS = 3
HIGH_RISK_THRESHOLD = 100


# --- Audit evidence ---------------------------------------------------------
def append_audit(subject_identity_id, event_type, actor_user_id, detail):
    """Append an immutable audit evidence record (id + created_at only)."""
    record = {
        "id": db.new_id(),
        "created_at": now_iso(),
        "_seq": db.next_seq(),
        "subject_identity_id": subject_identity_id,
        "event_type": event_type,
        "actor_user_id": actor_user_id,
        "detail": detail,
    }
    db.audit_events[record["id"]] = record
    return record


# --- Identity counter / risk reconciliation ---------------------------------
def _active_grants_of(identity_id):
    return [g for g in db.grants.values()
            if g["identity_id"] == identity_id and g["lifecycle_status"] == "ACTIVE"]


def _entitlement(eid):
    return db.entitlements.get(eid)


def _effective_base(identity_id):
    total = 0
    for g in _active_grants_of(identity_id):
        ent = _entitlement(g["entitlement_id"])
        if ent is not None:
            total += ent["risk_weight"]
    return total


def _privileged_entitlement_ids_active(identity_id):
    """Distinct privileged entitlement ids held via an ACTIVE grant."""
    result = set()
    for g in _active_grants_of(identity_id):
        ent = _entitlement(g["entitlement_id"])
        if ent is not None and ent.get("is_privileged"):
            result.add(ent["id"])
    return result


def compute_effective_risk(identity_id):
    base = _effective_base(identity_id)
    priv_n = len(_privileged_entitlement_ids_active(identity_id))
    surcharge = PRIVILEGED_STEP * min(priv_n, PRIVILEGED_CAP_STEPS)
    return base + surcharge


def _pending_entitlement_ids(identity_id):
    """Union of entitlements bundled by the role of each SUBMITTED access
    request for this identity, minus entitlements already held via an ACTIVE
    grant (PRD §2.7 projected risk)."""
    held = {g["entitlement_id"] for g in _active_grants_of(identity_id)}
    pending = set()
    for ar in db.access_requests.values():
        if ar["identity_id"] != identity_id or ar["status"] != "SUBMITTED":
            continue
        role = db.roles.get(ar["role_id"])
        if role is None:
            continue
        for eid in role.get("entitlement_ids", []):
            pending.add(eid)
    return pending - held


def compute_projected_risk(identity_id):
    effective_base = _effective_base(identity_id)
    pending_ids = _pending_entitlement_ids(identity_id)
    pending_base = 0
    for eid in pending_ids:
        ent = _entitlement(eid)
        if ent is not None:
            pending_base += ent["risk_weight"]
    # Projected privileged count: distinct privileged across active-grant
    # entitlements UNION pending entitlements.
    active_priv = _privileged_entitlement_ids_active(identity_id)
    projected_priv = set(active_priv)
    for eid in pending_ids:
        ent = _entitlement(eid)
        if ent is not None and ent.get("is_privileged"):
            projected_priv.add(eid)
    projected_surcharge = PRIVILEGED_STEP * min(len(projected_priv), PRIVILEGED_CAP_STEPS)
    return effective_base + pending_base + projected_surcharge


def compute_is_orphan(identity):
    return (identity["status"] == "ACTIVE"
            and identity["is_human"] is False
            and identity["active_grant_count"] == 0)


def recompute_identity_counters(identity, touch_record=True):
    """Recompute the five conserved quantities + is_orphan from current grant
    state. A recompute that mutates the identity bumps version/updated_at."""
    iid = identity["id"]
    active = _active_grants_of(iid)
    identity["active_grant_count"] = len(active)
    identity["privileged_entitlement_count"] = len(_privileged_entitlement_ids_active(iid))
    identity["effective_risk_score"] = compute_effective_risk(iid)
    identity["projected_risk_score"] = compute_projected_risk(iid)
    identity["is_orphan"] = compute_is_orphan(identity)
    if touch_record:
        touch(identity)


def recompute_projected_only(identity):
    """Recompute projected risk (and is_orphan, which depends only on counters
    that did not change here but kept consistent) for request-set changes."""
    identity["projected_risk_score"] = compute_projected_risk(identity["id"])
    identity["is_orphan"] = compute_is_orphan(identity)
    touch(identity)


def grant_risk_contribution(grant):
    """A grant's risk_contribution is exactly its entitlement's risk_weight
    while it is ACTIVE; 0 otherwise (the surcharge is identity-level)."""
    ent = _entitlement(grant["entitlement_id"])
    if ent is None:
        return 0
    return ent["risk_weight"]


# --- Grant creation + activation -------------------------------------------
def create_and_activate_grant(identity, entitlement_id, source_request_id,
                              is_just_in_time, effective_from, effective_until,
                              actor_user_id, touch_identity=True):
    """Create a Grant in PROVISIONING and immediately auto-activate it to
    ACTIVE, running the activation side-effects (PRD §3.5).

    touch_identity controls whether the activation's counter recompute bumps the
    identity version. The approval cascade leaves it True (each activation is a
    downstream recompute that mutates the identity, PRD §2.4). The direct-grant
    path passes False because that operation is specified to bump the identity
    version exactly once (PRD §3.2), which the caller does explicitly.

    The HIGH_RISK auto-flag is applied by the caller after the full cascade via
    apply_high_risk_flag, so it reflects the post-cascade effective score and
    targets the newest privileged grant (PRD §3.4).
    """
    common = db.new_common()
    grant = {
        "id": common["id"],
        "created_at": common["created_at"],
        "updated_at": common["updated_at"],
        "version": common["version"],
        "_seq": common["_seq"],
        "identity_id": identity["id"],
        "entitlement_id": entitlement_id,
        "source_request_id": source_request_id,
        "is_just_in_time": is_just_in_time,
        "effective_from": effective_from,
        "effective_until": effective_until,
        "lifecycle_status": "PROVISIONING",
        "review_status": "NOT_DUE",
        "risk_contribution": 0,
    }
    db.grants[grant["id"]] = grant

    # PROVISIONING -> ACTIVE (auto)
    grant["lifecycle_status"] = "ACTIVE"
    grant["risk_contribution"] = grant_risk_contribution(grant)
    touch(grant)

    # Activation side effects: recompute identity counters.
    recompute_identity_counters(identity, touch_record=touch_identity)

    append_audit(identity["id"], "GRANT_ACTIVATED", actor_user_id,
                 "Grant %s activated for entitlement %s" % (grant["id"], entitlement_id))

    return grant


def apply_high_risk_flag(identity, risk_before, candidate_grants):
    """If the effective risk crossed the HIGH_RISK threshold (from below to
    at/above) as a result of an activation cascade, flag the newest privileged
    grant among the candidates for review (PRD §2.7, §3.4).

    candidate_grants are the grants created in this cascade, in creation order.
    """
    risk_after = identity["effective_risk_score"]
    if not (risk_before < HIGH_RISK_THRESHOLD <= risk_after):
        return
    privileged = [g for g in candidate_grants
                  if (_entitlement(g["entitlement_id"]) or {}).get("is_privileged")]
    if not privileged:
        return
    newest = max(privileged, key=lambda g: g.get("_seq", 0))
    if newest["lifecycle_status"] == "ACTIVE" and newest["review_status"] == "NOT_DUE":
        newest["review_status"] = "FLAGGED"
        touch(newest)


def revoke_grant(grant, identity, actor_user_id):
    """Transition a grant ACTIVE -> REVOKED and run the full revoke
    side-effects (PRD §3.5). Caller must have verified ACTIVE state."""
    grant["lifecycle_status"] = "REVOKED"
    grant["risk_contribution"] = 0
    touch(grant)

    recompute_identity_counters(identity)

    append_audit(identity["id"], "GRANT_REVOKED", actor_user_id,
                 "Grant %s revoked" % grant["id"])


# --- SoD evaluation ---------------------------------------------------------
def evaluate_sod(identity_id, role):
    """Evaluate ACTIVE SoD policies for granting `role` to `identity_id`.

    Returns (detected, hard_conflict, soft_conflict) per
    SCAFFOLD §1.3 sod_conflict_evaluation / PRD §3.3.
    """
    requested = set(role.get("entitlement_ids", []))
    held = {g["entitlement_id"] for g in _active_grants_of(identity_id)}
    union_after = requested | held

    conflicts = []
    for policy in db.sod_policies.values():
        if policy["status"] != "ACTIVE":
            continue
        if policy["entitlement_a_id"] in union_after and policy["entitlement_b_id"] in union_after:
            conflicts.append(policy)

    detected = len(conflicts) > 0
    hard = any(p["severity"] == "HARD" for p in conflicts)
    soft = any(p["severity"] == "SOFT" for p in conflicts) and not hard
    return detected, hard, soft
