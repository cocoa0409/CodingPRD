"""Lookups, derived-field projections, reserve reconciliation and the shared
cascades that several endpoints re-use."""

from fractions import Fraction

from db import (add_days, by_seq, clock_date, date_str, db, new_row, now_iso,
                to_fraction, touch)
from errors import ApiError
from services import calc
from services import constants as C

# ---------------------------------------------------------------------------
# existence resolution (checks 5 and 6 of PRD 2.10)
# ---------------------------------------------------------------------------

_TABLES = {
    "association": ("associations", "ERR_ASSOCIATION_NOT_FOUND"),
    "segment": ("road_segments", "ERR_ROAD_SEGMENT_NOT_FOUND"),
    "parcel": ("parcels", "ERR_PARCEL_NOT_FOUND"),
    "member": ("members", "ERR_MEMBER_NOT_FOUND"),
    "roll": ("assessment_rolls", "ERR_ROLL_NOT_FOUND"),
    "charge": ("assessment_charges", "ERR_CHARGE_NOT_FOUND"),
    "proposal": ("proposals", "ERR_PROPOSAL_NOT_FOUND"),
    "ballot": ("ballots", "ERR_BALLOT_NOT_FOUND"),
    "project": ("projects", "ERR_PROJECT_NOT_FOUND"),
    "bid": ("contractor_bids", "ERR_BID_NOT_FOUND"),
    "action": ("delinquency_actions", "ERR_DELINQUENCY_ACTION_NOT_FOUND"),
    "request": ("connection_requests", "ERR_CONNECTION_REQUEST_NOT_FOUND"),
}


def require(kind, row_id):
    table_name, error_id = _TABLES[kind]
    table = getattr(db, table_name)
    if not isinstance(row_id, str) or row_id not in table:
        raise ApiError(error_id, "%s does not resolve." % (row_id,))
    return table[row_id]


# ---------------------------------------------------------------------------
# relationship helpers
# ---------------------------------------------------------------------------

def segments_of(association_id):
    return [s for s in db.road_segments.values() if s["association_id"] == association_id]


def segment_ids_of(association_id):
    return {s["id"] for s in db.road_segments.values() if s["association_id"] == association_id}


def association_of_segment(segment):
    return db.associations.get(segment["association_id"])


def association_of_parcel(parcel):
    segment = db.road_segments.get(parcel["road_segment_id"])
    return association_of_segment(segment) if segment else None


def association_of_proposal(proposal):
    segment = db.road_segments.get(proposal["road_segment_id"])
    return association_of_segment(segment) if segment else None


def association_of_project(project):
    segment = db.road_segments.get(project["road_segment_id"])
    return association_of_segment(segment) if segment else None


def association_of_charge(charge):
    parcel = db.parcels.get(charge["parcel_id"])
    return association_of_parcel(parcel) if parcel else None


def segment_of_charge(charge):
    parcel = db.parcels.get(charge["parcel_id"])
    return db.road_segments.get(parcel["road_segment_id"]) if parcel else None


def member_for_parcel(parcel_id):
    rows = [m for m in db.members.values() if m["parcel_id"] == parcel_id]
    return by_seq(rows)[0] if rows else None


def charges_of_member(member_id):
    return by_seq([c for c in db.assessment_charges.values() if c["member_id"] == member_id])


def by_parcel_charges(parcel_id):
    return by_seq([c for c in db.assessment_charges.values() if c["parcel_id"] == parcel_id])


def actions_of_member(member_id):
    return by_seq([a for a in db.delinquency_actions.values() if a["member_id"] == member_id])


def actions_of_charge(charge_id):
    return by_seq([a for a in db.delinquency_actions.values() if a["charge_id"] == charge_id])


def bids_of_project(project_id):
    return by_seq([b for b in db.contractor_bids.values() if b["project_id"] == project_id])


def ballots_of_proposal(proposal_id):
    return by_seq([b for b in db.ballots.values() if b["proposal_id"] == proposal_id])


def rolls_of(association_id):
    return by_seq([r for r in db.assessment_rolls.values()
                   if r["association_id"] == association_id])


def has_certified_roll(association_id):
    return any(r["status"] == "CERTIFIED" for r in rolls_of(association_id))


def latest_levied_roll(association_id):
    """LEVIED rolls ranked by fiscal_year DESC then created_at DESC; first wins."""
    candidates = [r for r in rolls_of(association_id) if r["status"] == "LEVIED"]
    if not candidates:
        return None
    candidates.sort(key=lambda r: (int(r["fiscal_year"]), r["_seq"]), reverse=True)
    return candidates[0]


def proposals_of(association_id):
    seg_ids = segment_ids_of(association_id)
    return by_seq([p for p in db.proposals.values() if p["road_segment_id"] in seg_ids])


# ---------------------------------------------------------------------------
# assessable parcel set
# ---------------------------------------------------------------------------

ASSESSABLE_STANDINGS = ("GOOD_STANDING", "DELINQUENT", "LIEN_FILED")


def assessable_parcels(association_id, segment_id=None):
    """Explicit filter of PRD 3.4: ACTIVE, covenant recorded, on a segment of the
    association, with a member past deed verification."""
    seg_ids = segment_ids_of(association_id)
    result = []
    for parcel in by_seq(list(db.parcels.values())):
        if parcel["status"] != "ACTIVE" or parcel["covenant_recorded"] is not True:
            continue
        if parcel["road_segment_id"] not in seg_ids:
            continue
        if segment_id is not None and parcel["road_segment_id"] != segment_id:
            continue
        member = member_for_parcel(parcel["id"])
        if member is None or member["standing_status"] not in ASSESSABLE_STANDINGS:
            continue
        result.append((parcel, member))
    return result


def membership_roll_complete(association_id):
    seg_ids = segment_ids_of(association_id)
    for parcel in db.parcels.values():
        if parcel["status"] != "ACTIVE" or parcel["covenant_recorded"] is not True:
            continue
        if parcel["road_segment_id"] not in seg_ids:
            continue
        member = member_for_parcel(parcel["id"])
        if member is None or member["standing_status"] == "PENDING_DEED_VERIFICATION":
            return False
    return True


def association_frontage_units(association_id):
    """Sum of frontage_share_units over ACTIVE covenant-recorded parcels."""
    seg_ids = segment_ids_of(association_id)
    total = Fraction(0)
    for parcel in db.parcels.values():
        if parcel["status"] != "ACTIVE" or parcel["covenant_recorded"] is not True:
            continue
        if parcel["road_segment_id"] not in seg_ids:
            continue
        total += to_fraction(parcel["frontage_share_units"])
    return total


def units_for_variant(parcel, variant):
    if variant == "FRONTAGE_WEIGHTED":
        return to_fraction(parcel["frontage_share_units"])
    if variant == "TRIP_GENERATION_WEIGHTED":
        return to_fraction(parcel["trip_share_units"])
    return Fraction(1)  # EQUAL_SHARE


# ---------------------------------------------------------------------------
# member projections (PRD 2.8)
# ---------------------------------------------------------------------------

def reconcile_member(member):
    charges = charges_of_member(member["id"])
    actions = actions_of_member(member["id"])

    standing = member["standing_status"]
    if standing != "PENDING_DEED_VERIFICATION":
        if any(c["status"] == "LIEN_ENCUMBERED" for c in charges):
            standing = "LIEN_FILED"
        elif any(c["status"] == "DELINQUENT" for c in charges):
            standing = "DELINQUENT"
        else:
            standing = "GOOD_STANDING"

    encumbered = sum(a["lien_amount_cents"] for a in actions if a["status"] == "EFFECTIVE")

    if any(a["status"] == "EFFECTIVE" and a["action_type"] == "ACCESS_RESTRICTION"
           for a in actions):
        access = "RESTRICTED"
    elif any(a["status"] == "EFFECTIVE" and a["action_type"] == "NOTICE" for a in actions):
        access = "WARNED"
    else:
        access = "UNRESTRICTED"

    restricted_days = sum(
        a["restriction_days"] for a in actions
        if a["action_type"] == "ACCESS_RESTRICTION" and a["status"] in ("EFFECTIVE", "RELEASED")
    )

    changed = (standing != member["standing_status"]
               or access != member["access_status"]
               or encumbered != member["encumbered_principal_cents"]
               or restricted_days != member["restricted_days_used"])
    if changed:
        member["standing_status"] = standing
        member["access_status"] = access
        member["encumbered_principal_cents"] = encumbered
        member["restricted_days_used"] = restricted_days
        touch(member)
    return changed


def reconcile_members(member_ids):
    for member_id in dict.fromkeys(member_ids):
        member = db.members.get(member_id)
        if member is not None:
            reconcile_member(member)


def fiscal_year_of_charge(charge):
    roll = db.assessment_rolls.get(charge.get("roll_id"))
    return int(roll["fiscal_year"]) if roll else None


def restricted_days_in_fiscal_year(member_id, fiscal_year):
    total = 0
    for action in actions_of_member(member_id):
        if action["action_type"] != "ACCESS_RESTRICTION":
            continue
        if action["status"] not in ("EFFECTIVE", "RELEASED"):
            continue
        charge = db.assessment_charges.get(action["charge_id"])
        if charge is None:
            continue
        if fiscal_year is not None and fiscal_year_of_charge(charge) != fiscal_year:
            continue
        total += action["restriction_days"]
    return total


# ---------------------------------------------------------------------------
# reserve fund reconciliation (PRD 2.6)
# ---------------------------------------------------------------------------

def refresh_draft_thresholds(association):
    for proposal in proposals_of(association["id"]):
        if proposal["status"] != "DRAFT":
            continue
        bps = calc.vote_threshold_bps(
            proposal["project_type"],
            proposal["estimated_cost_cents"],
            association["reserve_posture"],
        )
        if bps != proposal["required_threshold_bps"]:
            proposal["required_threshold_bps"] = bps
            touch(proposal)


def recompute_reserve(association):
    """Reconciled aggregate, recomputed from first principles."""
    if association is None:
        return
    seg_ids = segment_ids_of(association["id"])

    balance = 0
    for roll in db.assessment_rolls.values():
        if roll["association_id"] == association["id"] and roll["status"] == "LEVIED":
            balance += roll["reserve_contribution_cents"]
    for request in db.connection_requests.values():
        if request["status"] != "APPROVED":
            continue
        parcel = db.parcels.get(request["parcel_id"])
        if parcel is not None and parcel["road_segment_id"] in seg_ids:
            balance += request["reserve_buyin_cents"]
    for project in db.projects.values():
        if project["road_segment_id"] in seg_ids and project["status"] in ("AWARDED", "COMPLETE"):
            balance -= project["reserve_draw_cents"]

    target = association["reserve_target_cents"]
    ratio = calc.ratio_4dp(balance, target)
    posture = calc.reserve_posture(balance, target)

    if (balance != association["reserve_balance_cents"]
            or ratio != association["reserve_funding_ratio"]
            or posture != association["reserve_posture"]):
        association["reserve_balance_cents"] = balance
        association["reserve_funding_ratio"] = ratio
        association["reserve_posture"] = posture
        touch(association)

    refresh_draft_thresholds(association)


# ---------------------------------------------------------------------------
# voting weights and tallies (PRD 3.5)
# ---------------------------------------------------------------------------

def voting_weight(member, basis):
    if basis == "PER_PARCEL":
        return 1
    candidates = []
    for charge in charges_of_member(member["id"]):
        if charge["charge_type"] != "ANNUAL" or charge["status"] == "VOIDED":
            continue
        roll = db.assessment_rolls.get(charge["roll_id"])
        if roll is None or roll["status"] not in ("CERTIFIED", "LEVIED"):
            continue
        candidates.append((int(roll["fiscal_year"]), charge["_seq"], charge))
    if not candidates:
        return 0
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][2]["amount_cents"] // 100


def eligible_voters(proposal):
    result = []
    for member in by_seq(list(db.members.values())):
        if member["standing_status"] not in ("GOOD_STANDING", "DELINQUENT"):
            continue
        parcel = db.parcels.get(member["parcel_id"])
        if parcel is None or parcel["status"] != "ACTIVE":
            continue
        if parcel["covenant_recorded"] is not True:
            continue
        if parcel["road_segment_id"] != proposal["road_segment_id"]:
            continue
        result.append(member)
    return result


def recompute_tally(proposal):
    """Totals are recomputed from CAST ballots only."""
    counted = 0
    totals = {"YES": 0, "NO": 0, "ABSTAIN": 0}
    for ballot in ballots_of_proposal(proposal["id"]):
        if ballot["status"] != "CAST":
            continue
        counted += ballot["weight_snapshot"]
        totals[ballot["choice"]] += ballot["weight_snapshot"]
    proposal["counted_weight_total"] = counted
    proposal["yes_weight_total"] = totals["YES"]
    proposal["no_weight_total"] = totals["NO"]
    proposal["abstain_weight_total"] = totals["ABSTAIN"]
    association = association_of_proposal(proposal)
    quorum_bps = association["quorum_bps"] if association else 0
    proposal["quorum_met"] = (
        counted * 10000 >= proposal["eligible_weight_total"] * quorum_bps
    )


# ---------------------------------------------------------------------------
# charge creation
# ---------------------------------------------------------------------------

def create_charge(roll_id, parcel_id, member_id, charge_type, share_units, amount_cents,
                  status, due_date=None, proposal_id=None):
    charge = new_row({
        "roll_id": roll_id,
        "proposal_id": proposal_id,
        "parcel_id": parcel_id,
        "member_id": member_id,
        "charge_type": charge_type,
        "share_units_snapshot": share_units,
        "amount_cents": amount_cents,
        "paid_cents": 0,
        "balance_cents": amount_cents,
        "status": status,
        "due_date": due_date,
        "delinquent_since": None,
    })
    db.assessment_charges[charge["id"]] = charge
    return charge


# ---------------------------------------------------------------------------
# shared project cascades
# ---------------------------------------------------------------------------

def reject_active_bids(project):
    for bid in bids_of_project(project["id"]):
        if bid["status"] in ("SUBMITTED", "AWARDED"):
            bid["status"] = "REJECTED"
            touch(bid)


def cancel_project(project, cancellation_reason=None):
    """Shared by POST /cancel and the access-inspection cascade."""
    reject_active_bids(project)
    project["status"] = "CANCELLED"
    if cancellation_reason is not None:
        project["cancellation_reason"] = cancellation_reason
    project["awarded_bid_id"] = None
    project["awarded_amount_cents"] = 0
    project["awarded_by_user_id"] = None
    project["reserve_draw_cents"] = 0
    touch(project)


def revert_award(project):
    """Awarded bid withdrawn: the project returns to solicitation and the draw
    is returned. Bids already REJECTED by that award stay REJECTED."""
    project["status"] = "BID_SOLICITATION"
    project["awarded_bid_id"] = None
    project["awarded_amount_cents"] = 0
    project["awarded_by_user_id"] = None
    project["reserve_draw_cents"] = 0
    touch(project)


def release_effective_actions_for_charge(charge):
    """Every EFFECTIVE remedy on a cleared charge moves to RELEASED."""
    affected_members = []
    for action in actions_of_charge(charge["id"]):
        if action["status"] != "EFFECTIVE":
            continue
        action["status"] = "RELEASED"
        action["released_at"] = now_iso()
        action["lien_amount_cents"] = 0
        touch(action)
        affected_members.append(action["member_id"])
    return affected_members


def void_ballots_for_lien(member):
    """Hop 4 of effectuation: CAST ballots on BALLOTING proposals are voided."""
    affected = {}
    for ballot in by_seq(list(db.ballots.values())):
        if ballot["member_id"] != member["id"] or ballot["status"] != "CAST":
            continue
        proposal = db.proposals.get(ballot["proposal_id"])
        if proposal is None or proposal["status"] != "BALLOTING":
            continue
        ballot["status"] = "VOIDED"
        touch(ballot)
        affected[proposal["id"]] = proposal
    for proposal in affected.values():
        recompute_tally(proposal)
        touch(proposal)


def due_date_from_clock():
    return date_str(add_days(clock_date(), C.NET_DAYS))
