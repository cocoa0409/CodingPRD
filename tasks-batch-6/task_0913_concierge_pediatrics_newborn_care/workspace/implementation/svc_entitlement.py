"""EntitlementGrant pools (PRD 3.8, calculations.entitlement_consumption).

Conservation identity, true after EVERY request:
    available_count + booked_count + consumed_count == granted_count
released_count and overage_count sit outside it.
"""
from flask import g

import calc
import constants as C
from store import db, new_row, touch


def available_count(grant):
    value = grant["granted_count"] - grant["booked_count"] - grant["consumed_count"]
    return value if value > 0 else 0


def create_grant(membership, plan, benefit_type, year_index):
    granted = plan[C.BENEFIT_PLAN_FIELD[benefit_type]] if plan else 0
    grant = new_row(
        db.grants,
        {
            "membership_id": membership["id"],
            "benefit_type": benefit_type,
            "membership_year_index": year_index,
            "granted_count": granted,
            "booked_count": 0,
            "consumed_count": 0,
            "released_count": 0,
            "overage_count": 0,
            # A grant created with granted_count == 0 is EXHAUSTED from its
            # first read: the OPEN -> EXHAUSTED edge fires inside the creating
            # request.
            "status": "OPEN" if granted > 0 else "EXHAUSTED",
        },
    )
    return grant


def create_initial_grants(membership, plan):
    for benefit_type in C.BENEFIT_TYPES:
        create_grant(membership, plan, benefit_type, 0)


def find_grant(membership_id, benefit_type, year_index):
    for grant in db.grants.values():
        if (
            grant["membership_id"] == membership_id
            and grant["benefit_type"] == benefit_type
            and grant["membership_year_index"] == year_index
        ):
            return grant
    return None


def select_or_create_grant(membership, plan, benefit_type, on_date):
    year_index = calc.membership_year_index(membership, on_date)
    grant = find_grant(membership["id"], benefit_type, year_index)
    if grant is None:
        grant = create_grant(membership, plan, benefit_type, year_index)
    return grant


def hold_unit(grant):
    """create: ENTITLEMENT when available_count > 0, otherwise OVERAGE."""
    if available_count(grant) > 0:
        grant["booked_count"] += 1
        coverage_route = "ENTITLEMENT"
    else:
        grant["overage_count"] += 1
        coverage_route = "OVERAGE"
    if available_count(grant) == 0 and grant["status"] == "OPEN":
        grant["status"] = "EXHAUSTED"
    touch(grant, g.touched)
    return coverage_route


def consume_unit(grant, coverage_route):
    """complete: ENTITLEMENT moves booked -> consumed; OVERAGE moves nothing."""
    if coverage_route == "ENTITLEMENT":
        grant["booked_count"] -= 1
        grant["consumed_count"] += 1
        touch(grant, g.touched)


def release_unit(grant, coverage_route):
    """cancel: the compensating action of the hold placed at creation."""
    if coverage_route == "ENTITLEMENT":
        grant["booked_count"] -= 1
        grant["released_count"] += 1
        if available_count(grant) > 0 and grant["status"] == "EXHAUSTED":
            grant["status"] = "OPEN"
    else:
        grant["overage_count"] -= 1
    touch(grant, g.touched)


def expire_grants_of(membership):
    for grant in list(db.grants.values()):
        if grant["membership_id"] != membership["id"]:
            continue
        if grant["status"] in ("OPEN", "EXHAUSTED"):
            grant["status"] = "EXPIRED"
            touch(grant, g.touched)
