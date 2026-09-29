"""Derived-field recomputation, ledger writes and the multi-hop cascades."""
from decimal import Decimal

import calc
import common as C
import store as S
from common import (add_days, add_months, as_datetime, clock_now, dec, iso,
                    new_id, now_iso, parse_date_str, vol)
from errors import ApiError
from store import ordered, touch, touch_once


# ------------------------------------------------------------------ nodes
def recompute_credit(node):
    node["available_credit_kg"] = calc.available_credit(node)


def add_certified_input(node, amount):
    node["certified_input_kg"] = vol(dec(node["certified_input_kg"]) + dec(amount))
    recompute_credit(node)


def add_reserved(node, amount):
    node["reserved_output_kg"] = vol(dec(node["reserved_output_kg"]) + dec(amount))
    recompute_credit(node)


def add_claimed(node, amount):
    node["claimed_output_kg"] = vol(dec(node["claimed_output_kg"]) + dec(amount))
    recompute_credit(node)


# ------------------------------------------------------------------ audits
def recompute_audit_counts(audit):
    findings = S.findings_of_audit(audit["id"])
    audit["nonconformity_count"] = len(findings)
    audit["open_nonconformity_count"] = len(
        [f for f in findings if f["status"] in C.NC_OPEN_STATUSES])


# ------------------------------------------------------------------ holders
def recompute_holder_aggregates(holder):
    """Step four of PRD 3.6: recount the open grade counters and the score."""
    critical, major, minor = calc.grade_counts(S.findings_of_holder(holder["id"]))
    holder["open_critical_count"] = critical
    holder["open_major_count"] = major
    holder["open_minor_count"] = minor
    holder["compliance_score"] = calc.score_from_counts(critical, major, minor)


def recompute_next_audit_due(holder):
    """Step five of PRD 3.6: cadence from the post-insert score, anchored on the
    latest window_end among CLOSED audits (tie broken by earlier created_at)."""
    closed = [a for a in S.audits_of(holder["id"]) if a["status"] == "CLOSED"]
    if not closed:
        holder["next_audit_due_at"] = None
        return
    anchor = sorted(closed, key=lambda a: (a["window_end"], a["created_at"], a["_seq"]))[-1]
    months = calc.audit_interval_months(holder["compliance_score"])
    due = add_months(parse_date_str(anchor["window_end"]), months)
    holder["next_audit_due_at"] = iso(as_datetime(due))


def recompute_annual_certified_volume(holder):
    """Sum of settled outbound volume attributed to the current licence year."""
    year = holder.get("license_year")
    total = Decimal(0)
    holder_nodes = {n["id"] for n in S.nodes_of(holder["id"])}
    for tx in ordered(list(S.transactions.values())):
        if tx["seller_node_id"] not in holder_nodes:
            continue
        if tx["settlement_status"] != "SETTLED":
            continue
        if year is not None:
            contract_year = parse_date_str(tx["contract_date"]).year
            if contract_year != year:
                continue
        total += dec(tx["volume_kg"])
    holder["annual_certified_volume_kg"] = vol(total)


def refresh_license_settlement(holder):
    holder["license_fee_settled"] = calc.license_fee_settled(
        holder["license_fee_paid_cents"], holder["license_fee_cents"])


# ------------------------------------------------------------------ ledger
_FUND_EFFECTS = {
    "ACCRUAL": (("total_accrued_cents", 1), ("balance_cents", 1)),
    "REVERSAL": (("total_accrued_cents", -1), ("balance_cents", -1)),
    "COMMITMENT": (("balance_cents", -1), ("committed_cents", 1)),
    "RELEASE": (("committed_cents", -1), ("balance_cents", 1)),
    "DISBURSEMENT": (("committed_cents", -1), ("disbursed_cents", 1)),
}

_SIGNED = {"ACCRUAL": 1, "REVERSAL": -1, "COMMITMENT": 0, "RELEASE": 0,
           "DISBURSEMENT": 0}


def write_entry(fund, entry_type, amount_cents, memo, trade_transaction_id=None,
                proposal_id=None):
    """Append an immutable ledger entry and apply it to the fund (PRD 2.11)."""
    amount = int(amount_cents)
    for field, sign in _FUND_EFFECTS[entry_type]:
        fund[field] = fund[field] + sign * amount
    entry = {
        "id": new_id(),
        "fund_id": fund["id"],
        "trade_transaction_id": trade_transaction_id,
        "proposal_id": proposal_id,
        "entry_type": entry_type,
        "amount_cents": amount,
        "signed_amount_cents": _SIGNED[entry_type] * amount,
        "balance_after_cents": fund["balance_cents"],
        "memo": memo,
    }
    S.stamp_event(entry)
    S.entries[entry["id"]] = entry
    touch_once(fund)
    return entry


# -------------------------------------------------------------- committees
def adjust_proposal_counters(committee, fund, d_open, d_pending):
    if committee is not None and d_open:
        committee["open_proposal_count"] = max(
            0, committee["open_proposal_count"] + d_open)
        touch_once(committee)
    if fund is not None and d_pending:
        fund["pending_proposal_count"] = max(
            0, fund["pending_proposal_count"] + d_pending)
        touch_once(fund)


def committee_on_balance_rise(committee, fund):
    """A settlement, a release or a disbursement raised balance_cents."""
    if committee is None or fund is None:
        return
    balance = fund["balance_cents"]
    if (committee["status"] == "FORMING"
            and balance >= C.COMMITTEE_ACTIVATION_THRESHOLD_CENTS):
        committee["status"] = "ACTIVE"
        touch_once(committee)
    elif (committee["status"] == "RESTRICTED"
            and balance >= C.LOW_BALANCE_THRESHOLD_CENTS):
        committee["status"] = "ACTIVE"
        touch_once(committee)


def committee_on_balance_fall(committee, fund):
    """A commitment or a reversal lowered balance_cents (PRD 3.5)."""
    if committee is None or fund is None:
        return
    if (committee["status"] == "ACTIVE"
            and fund["balance_cents"] < C.LOW_BALANCE_THRESHOLD_CENTS):
        committee["status"] = "RESTRICTED"
        touch_once(committee)
        cancel_draft_proposals(committee, fund)


def cancel_draft_proposals(committee, fund):
    """Falling into RESTRICTED cancels every sibling DRAFT proposal."""
    drafts = ordered([p for p in S.proposals.values()
                      if p["committee_id"] == committee["id"] and p["status"] == "DRAFT"])
    for proposal in drafts:
        proposal["status"] = "CANCELLED"
        proposal["cancelled_at"] = now_iso()
        touch_once(proposal)
        adjust_proposal_counters(committee, fund, -1, -1)


# -------------------------------------------------------- holder cascades
def suspend_holder(holder, reason):
    """The three-hop suspension cascade of PRD 3.2."""
    holder["certificate_status"] = "SUSPENDED"
    holder["suspension_reason"] = reason
    touch_once(holder)

    suspended_nodes = 0
    disputed_txs = 0
    for node in S.nodes_of(holder["id"]):
        if node["status"] != "ACTIVE":
            continue
        node["status"] = "SUSPENDED"
        touch_once(node)
        suspended_nodes += 1
        for tx in S.txs_of_seller(node["id"]):
            if tx["verification_status"] != "UNVERIFIED":
                continue
            if tx["settlement_status"] != "PENDING":
                continue
            tx["verification_status"] = "DISPUTED"
            add_reserved(node, -dec(tx["volume_kg"]))
            touch_once(tx)
            disputed_txs += 1

    if holder["label_license_status"] == "ACTIVE":
        holder["label_license_status"] = "SUSPENDED"
    for mark in ordered([m for m in S.marks.values()
                         if m["brand_holder_id"] == holder["id"]]):
        if mark["status"] != "SUBMITTED":
            continue
        mark["status"] = "WITHDRAWN"
        mark["decision_reason"] = "HOLDER_SUSPENDED"
        mark["decided_at"] = now_iso()
        touch_once(mark)
    return suspended_nodes, disputed_txs


def decertify_holder(holder, unwind_pipeline=True):
    """PRD 3.2 decertification. The PENDING branch runs the narrow cascade."""
    holder["certificate_status"] = "DECERTIFIED"
    touch_once(holder)

    for node in S.nodes_of(holder["id"]):
        if node["status"] == "RETIRED":
            continue
        node["status"] = "RETIRED"
        touch_once(node)
        if not unwind_pipeline:
            continue
        for tx in S.txs_of_seller(node["id"]):
            if tx["settlement_status"] != "PENDING":
                continue
            if tx["verification_status"] in ("REJECTED",):
                continue
            was_reserved = tx["verification_status"] in ("UNVERIFIED", "VERIFIED")
            tx["verification_status"] = "REJECTED"
            if was_reserved:
                add_reserved(node, -dec(tx["volume_kg"]))
            touch_once(tx)

    if not unwind_pipeline:
        return

    for audit in S.audits_of(holder["id"]):
        if audit["status"] == "SCHEDULED":
            audit["status"] = "CANCELLED"
            touch_once(audit)
    for committee in ordered([c for c in S.committees.values()
                              if c["holder_id"] == holder["id"]]):
        if committee["status"] != "DISSOLVED":
            committee["status"] = "DISSOLVED"
            touch_once(committee)
    if holder["label_license_status"] in ("ACTIVE", "SUSPENDED"):
        holder["label_license_status"] = "TERMINATED"


# ----------------------------------------------------- chain traversal read
def walk_upstream(node):
    """Walk up through upstream_node_id; at most seven nodes may be visited."""
    visited = []
    current = node
    while current is not None:
        visited.append(current)
        if len(visited) > C.MAX_CHAIN_DEPTH + 1:
            raise ApiError("ERR_SUPPLY_CHAIN_DEPTH_EXCEEDED",
                           "upstream traversal exceeded the chain depth ceiling")
        upstream_id = current.get("upstream_node_id")
        current = S.nodes.get(upstream_id) if upstream_id else None
    return visited


def traceability_summary(holder):
    """PRD 3.1 chain traversal as a read."""
    holder_nodes = S.nodes_of(holder["id"])
    brand_nodes = [n for n in holder_nodes
                   if n["node_role"] == "BRAND_NODE"
                   and n["status"] in ("ACTIVE", "SUSPENDED")]

    union = {}
    for brand in brand_nodes:
        for visited in walk_upstream(brand):
            union[visited["id"]] = visited

    chain_nodes = list(union.values())
    physical = len([n for n in chain_nodes if n["traceability_mode"] == "PHYSICAL"])
    mass_balance = len(chain_nodes) - physical

    if not brand_nodes:
        chain_mode = "NO_CHAIN"
    elif mass_balance == 0:
        chain_mode = "ALL_PHYSICAL"
    else:
        chain_mode = "CONTAINS_MASS_BALANCE"

    total_credit = Decimal(0)
    for node in holder_nodes:
        total_credit += dec(node["available_credit_kg"])

    return {
        "holder_id": holder["id"],
        "chain_mode": chain_mode,
        "chain_node_count": len(chain_nodes),
        "brand_node_count": len(brand_nodes),
        "physical_node_count": physical,
        "mass_balance_node_count": mass_balance,
        "total_available_credit_kg": vol(total_credit),
    }


# ------------------------------------------------------- compliance sweep
def run_compliance_sweep():
    """PRD 3.7: six steps in a fixed order, each feeding the next."""
    now = clock_now()
    counters = {
        "overdue_count": 0,
        "escalated_count": 0,
        "suspended_holder_count": 0,
        "suspended_node_count": 0,
        "disputed_transaction_count": 0,
        "decertified_holder_count": 0,
    }

    # step one -- overdue
    candidates = [f for f in S.nonconformities.values()
                  if f["status"] in ("OPEN", "CAP_SUBMITTED", "CAP_REJECTED")]
    candidates.sort(key=lambda f: (f["deadline_at"], f["created_at"], f["_seq"]))
    for finding in candidates:
        from common import parse_iso
        if parse_iso(finding["deadline_at"]) < now:
            finding["status"] = "OVERDUE"
            touch(finding)
            counters["overdue_count"] += 1

    # step two -- escalation past the pinned grace window
    from common import parse_iso
    overdue = [f for f in S.nonconformities.values() if f["status"] == "OVERDUE"]
    overdue.sort(key=lambda f: (f["deadline_at"], f["created_at"], f["_seq"]))
    escalated = []
    for finding in overdue:
        grace_instant = add_days(parse_iso(finding["deadline_at"]),
                                 finding["escalation_grace_days"])
        if now >= grace_instant:
            finding["status"] = "ESCALATED"
            touch(finding)
            counters["escalated_count"] += 1
            escalated.append(finding)

    # steps three, four and five -- sanction and the suspension cascade
    touched_holders = []
    for finding in escalated:
        audit = S.audits.get(finding["audit_id"])
        holder = S.holders.get(audit["holder_id"]) if audit else None
        if holder is None:
            continue
        if finding["grade"] in ("CRITICAL", "MAJOR") and holder["certificate_status"] == "CERTIFIED":
            nodes_suspended, txs_disputed = suspend_holder(
                holder, "NONCONFORMITY_ESCALATION")
            counters["suspended_holder_count"] += 1
            counters["suspended_node_count"] += nodes_suspended
            counters["disputed_transaction_count"] += txs_disputed
        if holder["id"] not in [h["id"] for h in touched_holders]:
            touched_holders.append(holder)

    for holder in touched_holders:
        recompute_holder_aggregates(holder)
        recompute_next_audit_due(holder)
        touch_once(holder)

    # step six -- expired sell-down windows
    for holder in ordered([h for h in S.holders.values()
                           if h["certificate_status"] == "TRANSITIONING"]):
        deadline = holder.get("transition_deadline_at")
        if deadline is None:
            continue
        if parse_iso(deadline) <= now:
            decertify_holder(holder)
            counters["decertified_holder_count"] += 1

    result = {"swept_at": iso(now)}
    result.update(counters)
    return result
