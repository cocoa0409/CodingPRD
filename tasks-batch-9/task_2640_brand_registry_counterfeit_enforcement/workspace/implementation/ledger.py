"""Strike ledger, escalation ladder, alias clusters, and every multi-level
cascade (PRD 3.3, 3.4, 3.6, 3.8, 3.9, 3.10)."""

from decimal import Decimal

import calc
import db
from versioning import base_row, register_created, touch

# Strike bases per attribution source.
STRIKE_BASE = {
    "TAKEDOWN_REMOVAL": Decimal("12.55"),
    "SEIZURE_CONFIRMED": Decimal("25.15"),
    "CD_IGNORED": Decimal("5.05"),
}

FULL_WEIGHT = Decimal("1.00")
DECAYED_WEIGHT = Decimal("0.50")
DECAY_AGE_DAYS = 180
STRIKE_CAP = Decimal("100.00")
BLOCK_THRESHOLD = Decimal("60.00")
INVESTIGATION_THRESHOLD = Decimal("25.00")
STATUS_RANK = {"ACTIVE": 0, "UNDER_INVESTIGATION": 1, "BLOCKED": 2}


# ------------------------------------------------------------ strike input ---

def gather_strikes():
    """The live strike set, derived from current row states.  A reversal is an
    exclusion from this set, never a negative entry."""
    strikes = []
    for takedown in db.values("takedowns"):
        if takedown["status"] != "APPROVED_REMOVED":
            continue
        claim = db.get("claims", takedown["claim_id"])
        if claim is None:
            continue
        listing = db.get("listings", claim["listing_id"])
        if listing is None:
            continue
        strikes.append({
            "seller_id": listing["seller_id"],
            "kind": "TAKEDOWN_REMOVAL",
            "effective_at": takedown["decided_at"],
            "created_at": takedown["created_at"],
            "seq": takedown["_seq"],
            "brand_id": claim["brand_id"],
        })
    for inv in db.values("investigations"):
        if inv["status"] != "DIVERSION_CONFIRMED" or not inv["seller_id"]:
            continue
        strikes.append({
            "seller_id": inv["seller_id"],
            "kind": "SEIZURE_CONFIRMED",
            "effective_at": inv["concluded_at"],
            "created_at": inv["created_at"],
            "seq": inv["_seq"],
            "brand_id": inv["brand_id"],
        })
    for case in db.values("cases"):
        if case["correspondence_status"] != "CD_IGNORED" or not case["seller_id"]:
            continue
        strikes.append({
            "seller_id": case["seller_id"],
            "kind": "CD_IGNORED",
            "effective_at": case["cd_response_due_at"],
            "created_at": case["created_at"],
            "seq": case["_seq"],
            "brand_id": case["brand_id"],
        })
    return [s for s in strikes if s["effective_at"] is not None]


def points_for(strikes, seller_ids, now):
    """Enumerate in effective_at order, round every contribution to two places
    BEFORE summing, round the sum, then cap."""
    selected = [s for s in strikes if s["seller_id"] in seller_ids]
    selected.sort(key=lambda s: (s["effective_at"], s["created_at"], s["seq"]))
    total = Decimal("0")
    for strike in selected:
        age_days = int((now - strike["effective_at"]).total_seconds() // 86400)
        weight = FULL_WEIGHT if age_days <= DECAY_AGE_DAYS else DECAYED_WEIGHT
        total += calc.q2(STRIKE_BASE[strike["kind"]] * weight)
    return min(STRIKE_CAP, calc.q2(total))


def cluster_root(seller):
    return seller["canonical_seller_id"] or seller["id"]


def cluster_members(root_id):
    return [s for s in db.values("sellers")
            if s["id"] == root_id or s["canonical_seller_id"] == root_id]


def escalation_status(cluster_points):
    if cluster_points >= BLOCK_THRESHOLD:
        return "BLOCKED"
    if cluster_points >= INVESTIGATION_THRESHOLD:
        return "UNDER_INVESTIGATION"
    return "ACTIVE"


def recompute_sellers(seller_ids):
    """Recompute both strike variants for every cluster touched by the given
    sellers, rewrite each member's status from the cluster total, and bump only
    the members whose stored values actually change.

    Returns {seller_id: (previous_status, new_status)} for rows that moved."""
    now = db.now()
    strikes = gather_strikes()
    transitions = {}
    seen_roots = set()
    for seller_id in seller_ids:
        seller = db.get("sellers", seller_id)
        if seller is None:
            continue
        root = cluster_root(seller)
        if root in seen_roots:
            continue
        seen_roots.add(root)
        members = cluster_members(root)
        member_ids = set(m["id"] for m in members)
        cluster_points = points_for(strikes, member_ids, now)
        status = escalation_status(cluster_points)
        for member in members:
            standalone = points_for(strikes, {member["id"]}, now)
            previous = member["status"]
            changed = (Decimal(member["standalone_strike_points"]) != standalone
                       or Decimal(member["cluster_strike_points"]) != cluster_points
                       or previous != status)
            if not changed:
                continue
            member["standalone_strike_points"] = standalone
            member["cluster_strike_points"] = cluster_points
            member["status"] = status
            touch(member)
            if previous != status:
                transitions[member["id"]] = (previous, status)
    return transitions


def recompute_all_sellers():
    return recompute_sellers([s["id"] for s in db.values("sellers")])


# ------------------------------------------------------- enforcement cases ---

def open_case_exists(brand_id, seller_id):
    for case in db.values("cases"):
        if (case["brand_id"] == brand_id and case["seller_id"] == seller_id
                and case["case_status"] == "OPEN"):
            return True
    return False


def new_case(brand_id, seller_id, originating_takedown_id=None):
    row = base_row()
    row.update({
        "id": db.new_id(),
        "brand_id": brand_id,
        "seller_id": seller_id,
        "originating_takedown_id": originating_takedown_id,
        "cease_desist_sent_by_rep_id": None,
        "litigation_authorized_by_rep_id": None,
        "letter_ref": None,
        "cd_sent_at": None,
        "cd_response_due_at": None,
        "response_kind": None,
        "correspondence_status": "NONE",
        "litigation_status": "NONE",
        "case_status": "OPEN",
        "docket_ref": None,
        "closure_outcome": None,
    })
    ordered = order_row(row, CASE_FIELDS)
    db.insert("cases", ordered)
    register_created(ordered)
    return ordered


def attribute_strike(seller_id, brand_id, originating_takedown_id=None,
                     auto_case=True):
    """Recompute the affected cluster after a strike lands or leaves, and
    auto-open an enforcement case when the attributed seller escalates out of
    ACTIVE and no OPEN case already covers the pairing."""
    transitions = recompute_sellers([seller_id])
    if not auto_case:
        return transitions
    moved = transitions.get(seller_id)
    if moved and moved[0] == "ACTIVE" and moved[1] != "ACTIVE":
        if not open_case_exists(brand_id, seller_id):
            new_case(brand_id, seller_id, originating_takedown_id)
    return transitions


# ------------------------------------------------------------ brand posture --

def recompute_brand_posture(brand_id):
    """Compound status derived from every enrollment of the brand."""
    brand = db.get("brands", brand_id)
    if brand is None:
        return None
    enrollments = [e for e in db.values("enrollments")
                   if e["brand_id"] == brand_id]
    statuses = set(e["enrollment_status"] for e in enrollments)
    if "ACTIVE" in statuses:
        posture = "ENROLLED"
    elif "SUBMITTED" in statuses:
        posture = "ENROLLMENT_PENDING"
    elif enrollments:
        posture = "ENROLLMENT_LAPSED"
    else:
        posture = "DRAFT"
    if brand["status"] != posture:
        brand["status"] = posture
    touch(brand)
    return brand


def recompute_brand_posture_if_changed(brand_id):
    """Sweep-safe variant: only bumps when the derived value actually moves."""
    brand = db.get("brands", brand_id)
    if brand is None:
        return None
    enrollments = [e for e in db.values("enrollments")
                   if e["brand_id"] == brand_id]
    statuses = set(e["enrollment_status"] for e in enrollments)
    if "ACTIVE" in statuses:
        posture = "ENROLLED"
    elif "SUBMITTED" in statuses:
        posture = "ENROLLMENT_PENDING"
    elif enrollments:
        posture = "ENROLLMENT_LAPSED"
    else:
        posture = "DRAFT"
    if brand["status"] != posture:
        brand["status"] = posture
        touch(brand)
    return brand


# --------------------------------------------------------------- cascades ----

def release_listing_from_takedown(listing):
    if listing is not None and listing["enforcement_status"] == "TAKEDOWN_PENDING":
        listing["enforcement_status"] = "CLAIM_OPEN"
        touch(listing)
        return True
    return False


def demote_enforced_claims_on_listing(listing):
    count = 0
    for claim in db.values("claims"):
        if claim["listing_id"] == listing["id"] and claim["status"] == "ENFORCED":
            claim["status"] = "SUBSTANTIATED"
            touch(claim)
            count += 1
    return count


def withdraw_enrollment_takedowns(enrollment_id):
    """Level 1/2/3 of the enrolment-suspension cascade."""
    withdrawn = 0
    for takedown in db.values("takedowns"):
        if takedown["enrollment_id"] != enrollment_id:
            continue
        if takedown["status"] not in ("DRAFT", "SUBMITTED"):
            continue
        takedown["status"] = "WITHDRAWN"
        touch(takedown)
        withdrawn += 1
        claim = db.get("claims", takedown["claim_id"])
        if claim is None:
            continue
        listing = db.get("listings", claim["listing_id"])
        if listing is None:
            continue
        if release_listing_from_takedown(listing):
            demote_enforced_claims_on_listing(listing)
    return withdrawn


def suspend_enrollment(enrollment, reason_code):
    """ACTIVE -> SUSPENDED with the full three-level cascade and a brand
    posture re-derivation."""
    enrollment["enrollment_status"] = "SUSPENDED"
    enrollment["suspension_reason_code"] = reason_code
    touch(enrollment)
    withdrawn = withdraw_enrollment_takedowns(enrollment["id"])
    recompute_brand_posture(enrollment["brand_id"])
    return withdrawn


def revoke_enrollment_representatives(enrollment_id):
    revoked = 0
    for rep in db.values("representatives"):
        if (rep["enrollment_id"] == enrollment_id
                and rep["designation_status"] == "DESIGNATED"):
            rep["designation_status"] = "REVOKED"
            rep["revoked_at"] = db.now()
            touch(rep)
            revoked += 1
    return revoked


def supersede_enrollment(old, new_enrollment_id):
    """The only route to TERMINATED."""
    old["enrollment_status"] = "TERMINATED"
    old["superseded_by_enrollment_id"] = new_enrollment_id
    touch(old)
    revoke_enrollment_representatives(old["id"])
    withdraw_enrollment_takedowns(old["id"])


def rederive_listing_enforcement_after_claim_close(listing):
    if listing is None or listing["enforcement_status"] != "CLAIM_OPEN":
        return False
    for claim in db.values("claims"):
        if (claim["listing_id"] == listing["id"]
                and claim["status"] in ("DRAFT", "SUBSTANTIATED", "ENFORCED")):
            return False
    listing["enforcement_status"] = "NONE"
    touch(listing)
    return True


def withdraw_claim_packages(claim_id):
    count = 0
    for package in db.values("packages"):
        if (package["claim_id"] == claim_id
                and package["status"] in ("ASSEMBLING", "SEALED")):
            package["status"] = "WITHDRAWN"
            touch(package)
            count += 1
    return count


def claim_has_takedown_in(claim_id, statuses):
    for takedown in db.values("takedowns"):
        if takedown["claim_id"] == claim_id and takedown["status"] in statuses:
            return True
    return False


def demote_claim_after_reversal(claim):
    if claim is None or claim["status"] != "ENFORCED":
        return False
    if claim_has_takedown_in(claim["id"], ("APPROVED_REMOVED",)):
        return False
    claim["status"] = "SUBSTANTIATED"
    touch(claim)
    return True


CASE_FIELDS = [
    "id", "brand_id", "seller_id", "originating_takedown_id",
    "cease_desist_sent_by_rep_id", "litigation_authorized_by_rep_id",
    "letter_ref", "cd_sent_at", "cd_response_due_at", "response_kind",
    "correspondence_status", "litigation_status", "case_status", "docket_ref",
    "closure_outcome", "created_at", "updated_at", "version",
]


def order_row(row, fields):
    ordered = {}
    for field in fields:
        ordered[field] = row[field]
    for key, value in row.items():
        if key not in ordered:
            ordered[key] = value
    return ordered


# --------------------------------------------------- brand enforcement KPIs --

def brand_enforcement_metrics(brand):
    brand_id = brand["id"]
    decided = 0
    removed = 0
    for takedown in db.values("takedowns"):
        claim = db.get("claims", takedown["claim_id"])
        if claim is None or claim["brand_id"] != brand_id:
            continue
        if takedown["status"] in ("APPROVED_REMOVED", "REJECTED", "REINSTATED"):
            decided += 1
        if takedown["status"] == "APPROVED_REMOVED":
            removed += 1
    if decided == 0:
        rate = calc.q4(Decimal("0"))
    else:
        rate = calc.q4(Decimal(removed) / Decimal(decided))

    strikes = gather_strikes()
    repeat = 0
    for seller in db.values("sellers"):
        if seller["canonical_seller_id"]:
            continue  # alias rows are never counted, only cluster roots
        member_ids = set(m["id"] for m in cluster_members(seller["id"]))
        if Decimal(seller["cluster_strike_points"]) < INVESTIGATION_THRESHOLD:
            continue
        attributable = any(s["seller_id"] in member_ids
                           and s["brand_id"] == brand_id for s in strikes)
        if attributable:
            repeat += 1

    open_cases = len([c for c in db.values("cases")
                      if c["brand_id"] == brand_id
                      and c["case_status"] in ("OPEN", "IN_LITIGATION")])
    return {
        "listing_removal_rate": rate,
        "repeat_infringer_count": repeat,
        "decided_takedown_count": decided,
        "removed_takedown_count": removed,
        "open_case_count": open_cases,
        "enforcement_spend_cents": brand["enforcement_spend_cents"],
    }
