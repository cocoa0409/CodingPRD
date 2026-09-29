"""Cross-aggregate side effects and cascades (PRD 2.10, 3.1-3.9).

Every row a cascade mutates gets its own updated_at refresh and version bump.
Derived counters (open_conditions_count, cleared_gate_count, active_binding_count,
enforced_shadow_count, vendor_terms_grade, monitoring_posture) are pure
materialisations of facts held elsewhere and are recomputed in place; the version
bumps that accompany a status change are declared explicitly per transition.
"""
from decimal import Decimal

import clock
import constants
import db
from services import calc, queries


# --- ledger ---------------------------------------------------------------
def append_ledger(use_case_id, entry_type, actor_user_id, note,
                  reach_delta=0, debt_delta=Decimal("0.00")):
    if use_case_id is None:
        return None
    entry = {
        "use_case_id": use_case_id,
        "entry_type": entry_type,
        "reach_delta": reach_delta,
        "debt_delta": Decimal(debt_delta).quantize(Decimal("0.01")),
        "actor_user_id": actor_user_id,
        "recorded_at": clock.now(),
        "note": note,
    }
    return db.insert(db.ledger_entries, entry)


# --- use case derived counters -------------------------------------------
def recompute_use_case_counters(use_case):
    gates = queries.gates_of(use_case["id"])
    use_case["open_conditions_count"] = sum(
        g["open_condition_count"] for g in gates if g["status"] == "CONDITIONS_ISSUED"
    )
    use_case["cleared_gate_count"] = sum(1 for g in gates if g["status"] == "CLEARED")


# --- review gates --------------------------------------------------------
def create_required_gates(use_case):
    """Fresh PENDING gates in canonical order, pinned to this classification."""
    created = []
    for gate_type in constants.REQUIRED_GATES[use_case["risk_tier"]]:
        gate = {
            "use_case_id": use_case["id"],
            "gate_type": gate_type,
            "status": "PENDING",
            "pinned_risk_tier": use_case["risk_tier"],
            "pinned_classification_index": use_case["classification_cycle_index"],
            "assigned_reviewer_user_id": None,
            "conditions": [],
            "open_condition_count": 0,
            "control_debt_index": Decimal("0.00"),
            "debt_before_clear": Decimal("0.00"),
            "cleared_by_user_id": None,
            "cleared_at": None,
            "decision_note": None,
            "updated_at": clock.now(),
            "version": 1,
        }
        db.insert(db.review_gates, gate)
        created.append(gate)
    return created


def void_gates(use_case):
    """Reclassification / intake revision kills every live gate (PRD 3.3)."""
    for gate in queries.gates_of(use_case["id"]):
        if gate["status"] == "VOIDED":
            continue
        gate["status"] = "VOIDED"
        gate["control_debt_index"] = Decimal("0.00")
        gate["open_condition_count"] = 0
        db.touch(gate)
    recompute_use_case_counters(use_case)


# --- evaluations / bindings ----------------------------------------------
def void_planned_evaluations(binding):
    for evaluation in queries.evaluations_of_binding(binding["id"]):
        if evaluation["status"] == "PLANNED":
            evaluation["status"] = "VOIDED"
            db.touch(evaluation)


def stale_binding(binding, superseded_reason):
    binding["status"] = "STALE"
    binding["superseded_reason"] = superseded_reason
    db.touch(binding)
    void_planned_evaluations(binding)


def retire_binding(binding, superseded_reason):
    binding["status"] = "RETIRED"
    binding["superseded_reason"] = superseded_reason
    db.touch(binding)
    void_planned_evaluations(binding)
    asset = db.model_assets.get(binding["model_asset_id"])
    if asset is not None:
        asset["active_binding_count"] = max(0, asset["active_binding_count"] - 1)
    return asset


def stale_bindings_for_asset_version(asset):
    """Every PINNED binding pinned below the asset's new version goes STALE."""
    for binding in queries.bindings_of_asset(asset["id"]):
        if binding["status"] == "PINNED" and binding["pinned_model_version"] < asset["version"]:
            stale_binding(binding, "ASSET_REAPPROVED")


# --- model assets --------------------------------------------------------
def refresh_vendor_terms_grade(asset):
    """vendor_terms_grade is the grade of the most recently ACCEPTED assessment."""
    accepted = queries.accepted_assessments_of(asset["id"])
    asset["vendor_terms_grade"] = accepted[-1]["terms_grade"] if accepted else None


def expire_accepted_assessments(asset, ledger_use_case_id=None, actor_user_id=None):
    expired = 0
    for assessment in queries.accepted_assessments_of(asset["id"]):
        assessment["status"] = "EXPIRED"
        db.touch(assessment)
        expired += 1
        if ledger_use_case_id is not None:
            append_ledger(
                ledger_use_case_id,
                "VENDOR_ASSESSMENT_EXPIRED",
                actor_user_id,
                "vendor assessment %s expired because asset %s became RESTRICTED"
                % (assessment["id"], asset["id"]),
            )
    asset["vendor_terms_grade"] = None
    return expired


def restrict_asset(asset, ledger_use_case_id=None, actor_user_id=None):
    """APPROVED_FOR_USE -> RESTRICTED plus the assessment-expiry hop."""
    if asset["status"] != "APPROVED_FOR_USE":
        return False, 0
    asset["status"] = "RESTRICTED"
    db.touch(asset)
    expired = expire_accepted_assessments(asset, ledger_use_case_id, actor_user_id)
    return True, expired


# --- monitoring posture / suspension ------------------------------------
def suspend_use_case(use_case, actor_user_id, note):
    """The shared suspension body used by incidents, reassessment and the sweep."""
    use_case["status"] = "SUSPENDED"
    for binding in queries.bindings_of(use_case["id"]):
        if binding["status"] == "PINNED":
            stale_binding(binding, "APPROVAL_SUSPENDED")
    append_ledger(use_case["id"], "APPROVAL_SUSPENDED", actor_user_id, note)
    db.touch(use_case)


def rederive_monitoring_posture(use_case, actor_user_id):
    posture = calc.monitoring_posture(queries.incidents_of(use_case["id"]))
    use_case["monitoring_posture"] = posture
    if posture == "IMPAIRED" and use_case["status"] in ("APPROVED", "UNDER_REASSESSMENT"):
        suspend_use_case(
            use_case,
            actor_user_id,
            "approval suspended because monitoring posture became IMPAIRED",
        )
    return posture


def reinstate_use_case(use_case, actor_user_id):
    use_case["status"] = "APPROVED"
    for binding in queries.bindings_of(use_case["id"]):
        if binding["status"] != "STALE" or binding["superseded_reason"] != "APPROVAL_SUSPENDED":
            continue
        asset = db.model_assets.get(binding["model_asset_id"])
        if asset is not None and binding["pinned_model_version"] == asset["version"]:
            binding["status"] = "PINNED"
            binding["superseded_reason"] = None
            db.touch(binding)
    append_ledger(
        use_case["id"],
        "APPROVAL_REINSTATED",
        actor_user_id,
        "approval reinstated after every incident was resolved",
    )
    db.touch(use_case)


# --- revocation (four-hop cascade, PRD 3.8) ------------------------------
def revoke_use_case(use_case, revocation_reason, actor_user_id):
    was_in_inventory = use_case["status"] in constants.INVENTORY_STATUSES

    # hop 1
    use_case["status"] = "REVOKED"
    use_case["revoked_at"] = clock.now()
    use_case["revocation_reason"] = revocation_reason
    append_ledger(
        use_case["id"],
        "APPROVAL_REVOKED",
        actor_user_id,
        "approval revoked: %s" % revocation_reason,
        reach_delta=-use_case["deployed_headcount_reach"] if was_in_inventory else 0,
    )

    # hop 2 + hop 3
    touched_assets = []
    for binding in queries.bindings_of(use_case["id"]):
        if binding["status"] not in ("PINNED", "STALE"):
            continue
        asset = retire_binding(binding, "USE_CASE_REVOKED")
        append_ledger(
            use_case["id"],
            "BINDING_RETIRED",
            actor_user_id,
            "binding %s retired because the use case was revoked" % binding["id"],
        )
        if asset is not None and asset not in touched_assets:
            touched_assets.append(asset)

    # hop 4
    for asset in touched_assets:
        if (
            asset["active_binding_count"] == 0
            and asset["is_third_party"]
            and asset["status"] == "APPROVED_FOR_USE"
        ):
            restrict_asset(asset, use_case["id"], actor_user_id)

    # alongside the hops: published notices are withdrawn
    for notice in queries.notices_of(use_case["id"]):
        if notice["status"] != "PUBLISHED":
            continue
        notice["status"] = "WITHDRAWN"
        notice["withdrawn_at"] = clock.now()
        db.touch(notice)
        append_ledger(
            use_case["id"],
            "DISCLOSURE_WITHDRAWN",
            actor_user_id,
            "notice %s withdrawn because the use case was revoked" % notice["id"],
        )

    db.touch(use_case)
