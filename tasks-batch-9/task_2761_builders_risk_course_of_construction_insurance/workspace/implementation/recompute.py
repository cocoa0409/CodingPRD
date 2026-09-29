"""Derived-figure recomputation and the multi-hop cascades of PRD 2.7 / 2.12.

Nothing in this module increments a figure in place: written premium and coverage
erosion are always rebuilt from the underlying rows, which is what makes a
rescission or a void exact."""
import calc
from db import by_claim, by_facility, by_policy, by_project, new_row, ordered, store, touch


# ---- premium ledger ---------------------------------------------------------------
def ledger_rows(policy_id):
    return ordered(by_policy(store.premium_txns, policy_id))


def recompute_written_premium(policy):
    policy["written_premium_cents"] = sum(
        row["amount_cents"] for row in by_policy(store.premium_txns, policy["id"])
    )


def append_txn(policy, txn_type, amount_cents, effective_date, memo, reverses_sequence_no=None):
    """Appends an immutable ledger row (id + created_at only) and rebuilds written premium."""
    row = new_row(with_version=False)
    row.update({
        "policy_id": policy["id"],
        "sequence_no": len(by_policy(store.premium_txns, policy["id"])) + 1,
        "txn_type": txn_type,
        "amount_cents": amount_cents,
        "effective_date": effective_date,
        "memo": memo,
        "reverses_sequence_no": reverses_sequence_no,
    })
    store.premium_txns[row["id"]] = row
    recompute_written_premium(policy)
    return row


def extension_ap_sequence_no(policy_id, endorsement_id):
    for row in ledger_rows(policy_id):
        if row["txn_type"] == "EXTENSION_AP" and row.get("_endorsement_id") == endorsement_id:
            return row["sequence_no"]
    return None


# ---- coverage erosion -------------------------------------------------------------
def recompute_erosion(policy, claim=None):
    """PRD 2.12: eroded_cents from surviving ISSUED payments only, per part_type."""
    claim_ids = {row["id"] for row in by_policy(store.claims, policy["id"])}
    issued_by_type = {}
    for payment in store.payments.values():
        if payment["status"] != "ISSUED" or payment["claim_id"] not in claim_ids:
            continue
        issued_by_type[payment["part_type"]] = (
            issued_by_type.get(payment["part_type"], 0) + payment["amount_cents"]
        )
    total = 0
    for part in by_policy(store.coverage_parts, policy["id"]):
        eroded = issued_by_type.get(part["part_type"], 0)
        available = part["sublimit_cents"] - eroded
        if part["eroded_cents"] != eroded or part["available_cents"] != available:
            part["eroded_cents"] = eroded
            part["available_cents"] = available
            touch(part)
        total += part["eroded_cents"]
    policy["eroded_total_cents"] = total
    if claim is not None:
        paid = sum(
            payment["amount_cents"]
            for payment in by_claim(store.payments, claim["id"])
            if payment["status"] == "ISSUED"
        )
        claim["paid_cents"] = paid
        claim["outstanding_reserve_cents"] = claim["indemnity_cents"] - paid
        claim["total_incurred_cents"] = paid + claim["outstanding_reserve_cents"]


def issued_paid_for_part(claim_id, part_type):
    return sum(
        payment["amount_cents"]
        for payment in by_claim(store.payments, claim_id)
        if payment["status"] == "ISSUED" and payment["part_type"] == part_type
    )


# ---- project derived figures ------------------------------------------------------
def audit_basis_policy(project_id):
    """The project's single non-terminal policy: the one that is BOUND or IN_FORCE."""
    for policy in ordered(by_project(store.policies, project_id)):
        if policy["status"] in ("BOUND", "IN_FORCE"):
            return policy
    return None


def recompute_audit_risk_score(project):
    policy = audit_basis_policy(project["id"])
    if policy is None:
        return
    project["audit_risk_score"] = calc.audit_basis_score(project, policy)


def recompute_in_force_policy_count(project):
    project["in_force_policy_count"] = sum(
        1 for policy in by_project(store.policies, project["id"])
        if policy["status"] == "IN_FORCE"
    )


# ---- storage facility -------------------------------------------------------------
def recompute_committed_value(facility, bump=True):
    total = sum(
        row["stored_value_cents"] for row in by_facility(store.assignments, facility["id"])
        if row["status"] == "APPROVED"
    )
    changed = facility["committed_value_cents"] != total
    facility["committed_value_cents"] = total
    if bump and changed:
        touch(facility)
    return changed


# ---- the four-hop cascade of PRD 2.7 ----------------------------------------------
def policy_leaves_in_force(policy, release_reason):
    """Hops two to four plus the independent endorsement/project branch.

    The caller owns hop one (the policy's own status change and version bump)."""
    counters = {
        "closed_coverage_part_count": 0,
        "released_assignment_count": 0,
        "lapsed_endorsement_count": 0,
    }
    for part in ordered(by_policy(store.coverage_parts, policy["id"])):
        if part["status"] == "ACTIVE":
            part["status"] = "CLOSED"
            touch(part)
            counters["closed_coverage_part_count"] += 1
    facility_ids = []
    for row in ordered(by_policy(store.assignments, policy["id"])):
        if row["status"] != "APPROVED":
            continue
        row["status"] = "RELEASED"
        row["released_at"] = store.now()
        row["release_reason"] = release_reason
        touch(row)
        counters["released_assignment_count"] += 1
        if row["facility_id"] not in facility_ids:
            facility_ids.append(row["facility_id"])
    for facility_id in facility_ids:
        facility = store.facilities.get(facility_id)
        if facility is not None:
            recompute_committed_value(facility)
    for row in ordered(by_policy(store.endorsements, policy["id"])):
        if row["status"] in ("REQUESTED", "RETURNED_FOR_INFO"):
            row["status"] = "LAPSED"
            touch(row)
            counters["lapsed_endorsement_count"] += 1
    project = store.projects.get(policy["project_id"])
    if project is not None:
        before = project["in_force_policy_count"]
        recompute_in_force_policy_count(project)
        if project["in_force_policy_count"] != before:
            touch(project)
    return counters


def run_expiry_sweep():
    counters = {
        "expired_policy_count": 0,
        "closed_coverage_part_count": 0,
        "released_assignment_count": 0,
        "lapsed_endorsement_count": 0,
    }
    now = store.now()
    for policy in ordered(list(store.policies.values())):
        if policy["status"] != "IN_FORCE" or policy["term_end_date"] > now:
            continue
        policy["status"] = "EXPIRED"
        touch(policy)
        counters["expired_policy_count"] += 1
        hops = policy_leaves_in_force(policy, "POLICY_EXPIRY")
        for key, value in hops.items():
            counters[key] += value
    return counters
