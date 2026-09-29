"""Multi-hop cascades and their compensating reversals (PRD sections 2.7, 3.x)."""
from decimal import Decimal as D

import core
from db import store


def hold_entries(pair):
    """A blocked pair holds its live entry lines (held_reason PAIR_BLOCKED)."""
    for entry in core.entries_of_pair(pair["id"]):
        if entry["status"] in ("SUBMITTED", "ACCEPTED"):
            entry["status"] = "HELD"
            entry["held_reason"] = "PAIR_BLOCKED"
            store.touch(entry)


def release_entries(pair):
    for entry in core.entries_of_pair(pair["id"]):
        if entry["status"] == "HELD":
            entry["status"] = "ACCEPTED"
            entry["held_reason"] = None
            store.touch(entry)


def block_pair(pair):
    if pair["entry_eligibility_status"] == "ELIGIBLE":
        pair["entry_eligibility_status"] = "BLOCKED"
        store.touch(pair)
        hold_entries(pair)
        return True
    return False


def new_corrective_action(supplier_id, pair_id, trigger_reason, pre_blocked):
    row = store.new_row("action")
    row.update(
        {
            "supplier_id": supplier_id,
            "pair_id": pair_id,
            "trigger_reason": trigger_reason,
            "status": "OPEN",
            "decision": None,
            "rationale": None,
            "decided_at": None,
            "closed_at": None,
            "pre_action_blocked_pair_count": pre_blocked,
            "supplier_version_at_decision": None,
            "_branch_b_blocked": [],
        }
    )
    return store.insert(row)


def suspension_cascade(supplier):
    """Hops 2-6 of the fail-attestation suspension chain (PRD section 3.6)."""
    if supplier["status"] not in ("APPROVED", "CONDITIONALLY_APPROVED"):
        return
    final = core.supplier_performance_final(supplier)[0]
    if final >= core.SUSPENSION_THRESHOLD:
        return

    importer = store.importers.get(supplier["importer_id"])
    # snapshot taken BEFORE this cascade blocks anything
    pre_blocked = core.importer_blocked_pair_count(importer) if importer else 0

    supplier["status"] = "SUSPENDED_PENDING_REVIEW"
    store.touch(supplier)

    for pair in core.sort_rows(core.pairs_of_supplier(supplier["id"])):
        if pair["verification_status"] != "VERIFICATION_APPROVED":
            continue
        pair["verification_status"] = "VERIFICATION_LAPSED"
        store.touch(pair)
        new_corrective_action(
            supplier["id"], pair["id"], "PERFORMANCE_SCORE_BREACH", pre_blocked
        )
        block_pair(pair)


def compliance_status_cascade(supplier):
    """Hops 2-3 of the import-alert replanning chain (PRD section 3.2)."""
    for pair in core.sort_rows(core.pairs_of_supplier(supplier["id"])):
        if pair["verification_status"] != "VERIFICATION_APPROVED":
            continue
        risk = core.pair_risk(pair)
        freq_sum = core.pair_approved_frequency_sum(pair)
        planned = core.pair_adequacy_planned(pair)
        floor = core.pair_adequacy_floor(pair)
        if freq_sum >= risk["required_annual_frequency"] and planned >= floor:
            continue
        pair["verification_status"] = "REASSESSMENT_REQUIRED"
        store.touch(pair)
        for activity in core.sort_rows(core.activities_of_pair(pair["id"])):
            if activity["status"] == "APPROVED":
                activity["status"] = "CHANGES_REQUESTED"
                store.touch(activity)


def remediation_branch(supplier):
    """Branch A of the corrective-action decision (PRD section 3.7)."""
    if supplier["status"] == "SUSPENDED_PENDING_REVIEW":
        supplier["status"] = "CONDITIONALLY_APPROVED"
    for pair in core.sort_rows(core.pairs_of_supplier(supplier["id"])):
        if pair["verification_status"] == "VERIFICATION_LAPSED":
            pair["verification_status"] = "REASSESSMENT_REQUIRED"
            store.touch(pair)


def suspension_branch(supplier, action):
    """Branch B of the corrective-action decision (PRD section 3.7)."""
    blocked = []
    for pair in core.sort_rows(core.pairs_of_supplier(supplier["id"])):
        if block_pair(pair):
            blocked.append(pair["id"])
    action["_branch_b_blocked"] = blocked


def resolved_closure(action, supplier):
    """The compensating chain of a resolved closure (PRD section 3.7)."""
    now = core.clock()
    pair = store.pairs.get(action["pair_id"])
    if pair is not None:
        if pair["verification_status"] in ("VERIFICATION_LAPSED", "REASSESSMENT_REQUIRED"):
            pair["verification_status"] = "VERIFICATION_APPROVED"
            pair["last_reassessed_at"] = now
            store.touch(pair)

    target_ids = []
    if action["pair_id"]:
        target_ids.append(action["pair_id"])
    for pair_id in action.get("_branch_b_blocked") or []:
        if pair_id not in target_ids:
            target_ids.append(pair_id)

    for pair_id in target_ids:
        target = store.pairs.get(pair_id)
        if target is None:
            continue
        if target["entry_eligibility_status"] == "BLOCKED":
            target["entry_eligibility_status"] = "ELIGIBLE"
            store.touch(target)
            release_entries(target)

    others = [
        a
        for a in core.actions_of_supplier(supplier["id"])
        if a["id"] != action["id"] and a["status"] in core.NON_CLOSED_ACTION_STATUSES
    ]
    if not others and supplier["status"] in (
        "SUSPENDED_PENDING_REVIEW",
        "CONDITIONALLY_APPROVED",
    ):
        supplier["status"] = "APPROVED"
    store.touch(supplier)


def disqualification_closure(supplier):
    """The terminal disqualification cascade (PRD section 3.7)."""
    supplier["status"] = "DISQUALIFIED"
    for pair in core.sort_rows(core.pairs_of_supplier(supplier["id"])):
        changed = False
        if pair["verification_status"] != "RETIRED":
            pair["verification_status"] = "RETIRED"
            changed = True
        if pair["entry_eligibility_status"] != "BLOCKED":
            pair["entry_eligibility_status"] = "BLOCKED"
            changed = True
        if changed:
            store.touch(pair)
        for activity in core.sort_rows(core.activities_of_pair(pair["id"])):
            if activity["status"] == "APPROVED":
                activity["status"] = "RETIRED"
                store.touch(activity)
        for entry in core.sort_rows(core.entries_of_pair(pair["id"])):
            if entry["status"] in ("SUBMITTED", "ACCEPTED", "HELD"):
                entry["status"] = "REJECTED"
                entry["held_reason"] = "SUPPLIER_DISQUALIFIED"
                store.touch(entry)
    store.touch(supplier)


def exemption_revocation_cascade(pair):
    """Hops 2-3 of the exemption revocation chain (PRD section 3.8)."""
    if pair["verification_status"] == "VERIFICATION_APPROVED":
        return
    block_pair(pair)
