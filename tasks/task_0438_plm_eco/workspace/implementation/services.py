"""Domain services: calculations, BOM graph, state-machine cascades.

Every behaviour here traces to a PRD sentence (Sections 3.3, 3.4, 3.6, 3.7,
3.10) and the scaffold calculation / state-machine tables.
"""
import datetime
from decimal import Decimal, ROUND_HALF_UP

from db import store
from common import touch
from errors import err


# =============================================================================
# Clock helpers
# =============================================================================

def parse_iso(value):
    """Parse an ISO 8601 UTC instant into an aware datetime.

    Accepts a trailing 'Z' or an explicit offset. Naive input is treated as UTC.
    """
    if not isinstance(value, str) or not value:
        raise err("ERR_INVALID_REQUEST", "Expected an ISO 8601 UTC timestamp")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(text)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "Malformed ISO 8601 timestamp: %s" % value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)


# =============================================================================
# Lookup helpers
# =============================================================================

def revisions_of_part(part_id):
    return [r for r in store.part_revisions.values() if r["part_id"] == part_id]


def bom_lines_of_revision(rev_id):
    """BOM lines whose parent is this revision, ordered created_at ASC."""
    lines = [l for l in store.bom_lines.values() if l["parent_revision_id"] == rev_id]
    return sorted(lines, key=lambda l: l["_seq"])


def latest_non_obsolete_revision(part):
    """The child part's LATEST non-OBSOLETE revision by rev_label sequence.

    rev_label runs A, B, C, ... in per-part creation order; the newest is the
    one created last (highest _seq) among non-OBSOLETE revisions. (PRD 3.3
    planned variant.)
    """
    candidates = [r for r in revisions_of_part(part["id"]) if r["lifecycle_state"] != "OBSOLETE"]
    if not candidates:
        return None
    return max(candidates, key=lambda r: r["_seq"])


# =============================================================================
# Cost roll-up (PRD Section 3.3 / calc bom_cost_rollup)
# =============================================================================

def _round_half_up(raw):
    """Round a Decimal to whole cents, half up."""
    return int(Decimal(raw).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _pick_child_revision(child_part, variant):
    if variant == "planned":
        return latest_non_obsolete_revision(child_part)
    # effective: only the single released revision
    rel_id = child_part.get("released_revision_id")
    if rel_id is None:
        return None
    return store.part_revisions.get(rel_id)


def _rollup(rev, variant, seen):
    """Recursive multi-level rolled-up cost of a PartRevision, in cents."""
    part = store.parts[rev["part_id"]]
    part_type = part["part_type"]

    # Leaf BUY part: cost is its base_cost_cents.
    if part_type == "BUY":
        return part["base_cost_cents"]

    total = 0
    for line in bom_lines_of_revision(rev["id"]):
        child_part = store.parts.get(line["child_part_id"])
        if child_part is None:
            continue
        child_rev = _pick_child_revision(child_part, variant)
        if child_rev is None:
            child_unit = child_part["base_cost_cents"]
        else:
            child_unit = _rollup(child_rev, variant, seen)
        raw = Decimal(line["quantity"]) * Decimal(child_unit) * (Decimal(1) + Decimal(str(line["scrap_factor"])))
        ext = _round_half_up(raw)  # ROUND PER LINE (pinned), then sum
        total += ext

    if part_type == "PHANTOM":
        return total  # PHANTOM adds no cost of its own
    # MAKE: add own labor/overhead adder on top
    return total + part["base_cost_cents"]


def compute_costs(rev):
    """Return (planned_cost_cents, effective_cost_cents) for a revision."""
    planned = _rollup(rev, "planned", set())
    effective = _rollup(rev, "effective", set())
    return planned, effective


def recompute_and_store_costs(rev):
    planned, effective = compute_costs(rev)
    rev["planned_cost_cents"] = planned
    rev["effective_cost_cents"] = effective
    return planned, effective


# =============================================================================
# Where-used impact analysis (PRD Section 3.4 / calc where_used_blast_radius)
# =============================================================================

def where_used(part):
    """Compute distinct-parent counts and direct parent revision ids.

    Transitive, multi-level reverse traversal over non-OBSOLETE parent
    revisions. Counts distinct parent PART ids under two interpretations.
    """
    target_id = part["id"]

    # Direct parent revision ids: parent revisions of BOM lines consuming target.
    direct_lines = [l for l in store.bom_lines.values() if l["child_part_id"] == target_id]
    direct_lines_sorted = sorted(direct_lines, key=lambda l: l["_seq"])
    direct_parent_revision_ids = []
    for line in direct_lines_sorted:
        rid = line["parent_revision_id"]
        if rid not in direct_parent_revision_ids:
            direct_parent_revision_ids.append(rid)

    as_designed_parents = set()
    as_released_parents = set()

    # Transitive closure: reverse-walk up the assembly tree over non-OBSOLETE
    # parent revisions until no new parent PART is discovered.
    frontier = {target_id}
    visited_parts = set()
    while frontier:
        next_frontier = set()
        for child_part_id in frontier:
            if child_part_id in visited_parts:
                continue
            visited_parts.add(child_part_id)
            for line in store.bom_lines.values():
                if line["child_part_id"] != child_part_id:
                    continue
                parent_rev = store.part_revisions.get(line["parent_revision_id"])
                if parent_rev is None:
                    continue
                parent_part = store.parts.get(parent_rev["part_id"])
                if parent_part is None:
                    continue
                # as_designed: any non-OBSOLETE parent revision consumes child.
                if parent_rev["lifecycle_state"] != "OBSOLETE":
                    as_designed_parents.add(parent_part["id"])
                    # continue walking up only over non-OBSOLETE revisions
                    next_frontier.add(parent_part["id"])
                # as_released: parent revision is exactly the parent's released rev.
                if parent_part.get("released_revision_id") == parent_rev["id"]:
                    as_released_parents.add(parent_part["id"])
        frontier = next_frontier - visited_parts

    return {
        "part_id": target_id,
        "as_designed_affected_count": len(as_designed_parents),
        "as_released_affected_count": len(as_released_parents),
        "direct_parent_revision_ids": direct_parent_revision_ids,
    }


# =============================================================================
# BOM cycle detection (PRD Section 3.2 / validation priority 7)
# =============================================================================

def would_create_cycle(parent_rev, child_part_id):
    """True if adding child_part_id under parent_rev introduces a BOM cycle.

    A cycle exists if the child part transitively (through any chain of its own
    revisions' lines) consumes the parent revision's part.
    """
    parent_part_id = parent_rev["part_id"]
    if child_part_id == parent_part_id:
        return True

    # Walk down from the child part: collect every part transitively consumed.
    stack = [child_part_id]
    seen = set()
    while stack:
        pid = stack.pop()
        if pid in seen:
            continue
        seen.add(pid)
        if pid == parent_part_id:
            return True
        # All revisions of this part; their BOM lines reach further children.
        for rev in revisions_of_part(pid):
            for line in store.bom_lines.values():
                if line["parent_revision_id"] == rev["id"]:
                    stack.append(line["child_part_id"])
    return False


# =============================================================================
# ECO approval / pinning (PRD Section 3.6)
# =============================================================================

NON_TERMINAL_ECO_STATES = {"DRAFT", "IN_APPROVAL", "APPROVED"}


def recompute_eco_approval_count(eco):
    """approval_count = count of this ECO's APPROVED ApprovalTasks."""
    count = sum(
        1
        for t in store.approval_tasks.values()
        if t["change_order_id"] == eco["id"] and t["decision"] == "APPROVED"
    )
    eco["approval_count"] = count
    return count


def pin_affected_items(eco):
    """On ECO IN_APPROVAL -> APPROVED: pin every affected item (PRD 3.6).

    Each item's pinned flag is set true and the child revision ids of its
    part_revision_id are frozen. We snapshot the child revision ids onto the
    affected item (private field) so the released configuration is locked.
    """
    for item in store.affected_items.values():
        if item["change_order_id"] != eco["id"]:
            continue
        item["pinned"] = True
        rev = store.part_revisions.get(item["part_revision_id"])
        if rev is not None:
            child_rev_ids = []
            for line in bom_lines_of_revision(rev["id"]):
                child_part = store.parts.get(line["child_part_id"])
                if child_part is None:
                    continue
                cr = _pick_child_revision(child_part, "planned")
                if cr is not None:
                    child_rev_ids.append(cr["id"])
            item["_pinned_child_revision_ids"] = child_rev_ids
        touch(item)


def cascade_eco_to_approved(eco):
    """ECO IN_APPROVAL -> APPROVED cascade (PRD 3.6)."""
    eco["status"] = "APPROVED"
    pin_affected_items(eco)
    touch(eco)


def cascade_eco_to_rejected(eco):
    """ECO IN_APPROVAL -> REJECTED cascade (PRD 3.6)."""
    eco["status"] = "REJECTED"
    touch(eco)


# =============================================================================
# Make-effective release cascade (PRD Section 3.7)
# =============================================================================

def release_cascade(eco):
    """Fire the central release cascade for each affected item of the ECO.

    Hop 1: each affected revision IN_REVIEW -> RELEASED, set part.released_revision_id,
            recompute revision_count.
    Hop 2: a different prior RELEASED revision of the same part -> OBSOLETE.
    Hop 3: serialized units pinned to that obsoleted revision that are CONFORMING
            and not covered by a granted deviation -> NONCONFORMING.

    Preconditions per affected revision (PRD 3.7):
      - an affected item must link the revision to the ECO becoming effective
        (otherwise ERR_NO_GOVERNING_ECO);
      - that governing ECO must be APPROVED at make-effective time
        (otherwise ERR_ECO_NOT_APPROVED).
    """
    items = [i for i in store.affected_items.values() if i["change_order_id"] == eco["id"]]
    items = sorted(items, key=lambda i: i["_seq"])

    # Per-revision release preconditions (PRD 3.7) are validated first, before any
    # mutation, so a failure leaves the cascade atomic. The caller (make-effective)
    # has already verified the ECO was APPROVED at make-effective time.
    for item in items:
        rev = store.part_revisions.get(item["part_revision_id"])
        if rev is None:
            raise err("ERR_NO_GOVERNING_ECO", "Affected revision no longer exists")
        # Governing-ECO precondition: this revision must be governed by this ECO.
        if rev.get("governing_change_order_id") != eco["id"]:
            raise err("ERR_NO_GOVERNING_ECO", "Revision is not governed by this ECO")

    for item in items:
        rev = store.part_revisions[item["part_revision_id"]]
        part = store.parts[rev["part_id"]]

        # Hop 1: this revision IN_REVIEW -> RELEASED.
        rev["lifecycle_state"] = "RELEASED"
        touch(rev)

        # Hop 2: a different prior RELEASED revision of the same part -> OBSOLETE.
        prior_released = [
            r
            for r in revisions_of_part(part["id"])
            if r["id"] != rev["id"] and r["lifecycle_state"] == "RELEASED"
        ]
        for prior in prior_released:
            obsolete_revision(prior)  # also fires hop 3 for that revision

        # Set part.released_revision_id and recompute revision_count.
        part["released_revision_id"] = rev["id"]
        part["revision_count"] = len(revisions_of_part(part["id"]))
        touch(part)

    # Recompute costs for revisions whose descendants just changed release state.
    _recompute_all_costs()


def obsolete_revision(rev):
    """RELEASED -> OBSOLETE plus hop-3 conformance cascade (PRD 3.7)."""
    rev["lifecycle_state"] = "OBSOLETE"
    touch(rev)
    # Hop 3: serialized units pinned to this revision, CONFORMING and not covered
    # by a granted deviation, become NONCONFORMING.
    for unit in store.serialized_units.values():
        if unit["part_revision_id"] != rev["id"]:
            continue
        if unit["conformance_status"] != "CONFORMING":
            continue
        if unit.get("deviation_id") is not None:
            continue  # covered by a granted deviation
        unit["conformance_status"] = "NONCONFORMING"
        touch(unit)


def _recompute_all_costs():
    """Recompute stored cost fields on every revision (descendants changed)."""
    for rev in store.part_revisions.values():
        recompute_and_store_costs(rev)


# =============================================================================
# Deviation coverage (PRD Section 3.10 / calc deviation_coverage)
# =============================================================================

def part_ids_for_revision(rev_id):
    rev = store.part_revisions.get(rev_id)
    return rev["part_id"] if rev else None


def grant_deviation_coverage(dev):
    """Waive NONCONFORMING units for the deviation's part, capped at max_units.

    Candidates: units whose pinned revision belongs to dev.part_id, conformance
    NONCONFORMING, deviation_id null. Ordered created_at ASC, first max_units.
    """
    candidates = []
    for unit in store.serialized_units.values():
        if part_ids_for_revision(unit["part_revision_id"]) != dev["part_id"]:
            continue
        if unit["conformance_status"] != "NONCONFORMING":
            continue
        if unit.get("deviation_id") is not None:
            continue
        candidates.append(unit)
    candidates.sort(key=lambda u: u["_seq"])  # created_at ASC, never id
    take = candidates[: dev["max_units"]]
    for unit in take:
        unit["deviation_id"] = dev["id"]
        unit["conformance_status"] = "WAIVED"
        touch(unit)
    dev["covered_unit_count"] = len(take)


def expire_deviation_coverage(dev):
    """Revert each WAIVED unit covered by this deviation back to NONCONFORMING."""
    for unit in store.serialized_units.values():
        if unit.get("deviation_id") != dev["id"]:
            continue
        if unit["conformance_status"] != "WAIVED":
            continue
        unit["conformance_status"] = "NONCONFORMING"
        unit["deviation_id"] = None
        touch(unit)
    dev["covered_unit_count"] = 0


def windows_overlap_inclusive(a_from, a_to, b_from, b_to):
    """True if [a_from, a_to] overlaps [b_from, b_to], both endpoints inclusive."""
    return a_from <= b_to and b_from <= a_to
