"""Multi-row cascades: plan supersession, the five-link location compromise,
waitlist promotion and waitlist renumbering."""

from db import clock_iso, db, touch
from services import derive

BAND_RANK = {"IMMINENT": 0, "ELEVATED": 1, "MODERATE": 2, "LOW": 3}
LIVE_PLAN_STATUSES = ("DRAFT", "ACTIVE", "UNDER_REVISION")
OPEN_REFERRAL_STATUSES = ("SUBMITTED", "MATCHED")


# --------------------------------------------------------------------------
# safety-plan supersession
# --------------------------------------------------------------------------

def archive_live_plans(client, new_plan):
    """Archive every other live plan of the client; return True when an ACTIVE one fell."""
    lost_active = False
    for plan in derive.where("safety_plans", client_id=client["id"]):
        if plan["id"] == new_plan["id"]:
            continue
        if plan["status"] not in LIVE_PLAN_STATUSES:
            continue
        if plan["status"] == "ACTIVE":
            lost_active = True
        plan["status"] = "ARCHIVED"
        plan["archived_at"] = clock_iso()
        plan["superseded_by_plan_id"] = new_plan["id"]
        touch(plan)
    return lost_active


def reject_open_referrals(client, reason="SAFETY_PLAN_SUSPENDED"):
    """Close the client's live housing referrals and reverse the landlord ledger."""
    partners = []
    for referral in derive.where("housing_referrals", client_id=client["id"]):
        if referral["status"] not in OPEN_REFERRAL_STATUSES:
            continue
        was_matched = referral["status"] == "MATCHED"
        referral["status"] = "REJECTED"
        referral["rejection_reason"] = reason
        referral["incentive_fee_cents"] = None
        referral["incentive_tier_applied"] = None
        touch(referral)
        if was_matched:
            partner = db.landlord_partners.get(referral["landlord_partner_id"])
            if partner is not None and partner not in partners:
                partners.append(partner)
    for partner in partners:
        derive.recompute_partner(partner)


# --------------------------------------------------------------------------
# the five-link location-compromise cascade
# --------------------------------------------------------------------------

def compromise_cascade(admission, client):
    """Links two through five of PRD 3.6; link one is written by the caller."""
    # link 2 - the seal
    derive.recompute_client_posture(client)

    # link 3 - safety planning
    for plan in derive.where("safety_plans", client_id=client["id"], status="ACTIVE"):
        plan["status"] = "UNDER_REVISION"
        touch(plan)
        for component in derive.plan_components(plan["id"]):
            if component["status"] == "IMPLEMENTED":
                component["status"] = "REVIEW_REQUIRED"
                touch(component)
            elif (component["status"] == "DRAFT"
                  and component["component_type"] == "WORKPLACE_NOTIFICATION"):
                component["status"] = "BLOCKED"
                touch(component)
        derive.recompute_plan_coverage(plan)

    # links 4 and 5 - housing teardown and the landlord ledger reversal
    reject_open_referrals(client)


# --------------------------------------------------------------------------
# waitlist positions
# --------------------------------------------------------------------------

def waitlisted_of(shelter_id):
    rows = derive.where("screening_requests", requested_shelter_id=shelter_id,
                        status="WAITLISTED")
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def waitlist_position_for(request):
    """1 + the number of WAITLISTED peers of the same shelter created earlier."""
    earlier = 0
    for peer in waitlisted_of(request["requested_shelter_id"]):
        if peer["id"] == request["id"]:
            continue
        if (peer["created_at"], peer["_seq"]) < (request["created_at"], request["_seq"]):
            earlier += 1
    return 1 + earlier


def renumber_waitlist(shelter_id):
    for position, request in enumerate(waitlisted_of(shelter_id), start=1):
        if request["waitlist_position"] != position:
            request["waitlist_position"] = position
            touch(request)


# --------------------------------------------------------------------------
# waitlist promotion (exit only)
# --------------------------------------------------------------------------

def _eligible(request, unit):
    if request["status"] != "WAITLISTED":
        return False
    if request["requested_shelter_id"] != unit["shelter_id"]:
        return False
    if request["household_size"] > unit["available_beds"]:
        return False
    if request["accessibility_required"] and unit["unit_type"] != "ADA_ACCESSIBLE":
        return False
    if (request["minor_children_count"] > 0
            and unit["unit_type"] not in ("ADA_ACCESSIBLE", "FAMILY_SUITE")):
        return False
    advocate = db.staff_members.get(request["assigned_advocate_id"])
    if advocate is None or advocate["wellness_posture"] == "FROZEN":
        return False
    return True


def _rank(request):
    client = db.clients.get(request["client_id"])
    band = client["current_risk_band"] if client else None
    return (BAND_RANK.get(band, 4), request["requested_entry_date"],
            request["created_at"], request["_seq"])


def promote_from_waitlist(unit):
    """Promote exactly one eligible WAITLISTED request onto the freed unit.

    Returns the promoted request, or None when the eligible pool was empty.
    """
    if unit is None:
        return None
    pool = [r for r in waitlisted_of(unit["shelter_id"]) if _eligible(r, unit)]
    if not pool:
        return None
    winner = min(pool, key=_rank)
    winner["status"] = "APPROVED"
    winner["promoted_from_waitlist"] = True
    winner["offered_shelter_unit_id"] = unit["id"]
    winner["decided_at"] = clock_iso()
    winner["waitlist_position"] = None
    touch(winner)
    renumber_waitlist(unit["shelter_id"])
    derive.recompute_staff(db.staff_members.get(winner["assigned_advocate_id"]), force=True)
    return winner
