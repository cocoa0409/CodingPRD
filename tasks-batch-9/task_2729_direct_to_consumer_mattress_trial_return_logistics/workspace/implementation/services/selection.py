"""Waterfall disposition-partner selection."""
from db import db
from errors import api_error
from services import entities

DONATION_GRADES = ("A", "B")


def _completed_route_region(case):
    for appointment in entities.appointments_of_case(case["id"]):
        if appointment["status"] == "COMPLETED":
            route = db.pickup_routes.get(appointment["route_id"])
            if route is not None:
                return route["region_code"]
    return None


def _clauses(partner, partner_type, region_code, case, units, intake_date):
    """Every eligibility clause except capacity, then capacity separately."""
    non_capacity = (
        partner["status"] == "ACTIVE"
        and partner["partner_type"] == partner_type
        and partner["region_code"] == region_code
        and case["condition_grade"] in partner["accepts_condition_grades"]
        and (not case["soil_flag"]
             or partner["soil_policy"] == "ACCEPT_SOILED")
    )
    booked = entities.partner_day_booked_units(partner["id"], intake_date)
    headroom = partner["daily_intake_capacity_units"] - booked
    capacity_ok = booked + units <= partner["daily_intake_capacity_units"]
    return non_capacity, capacity_ok, headroom


def select_partner(case, order, model, requested_disposition, intake_date,
                   units):
    """Returns (partner, fallback_applied). Raises the declared refusal when no
    partner of any tried type can take the unit."""
    if requested_disposition == "DONATION":
        if (not model["donation_eligible"]
                or case["condition_grade"] not in DONATION_GRADES
                or case["soil_flag"]):
            raise api_error(
                "ERR_DONATION_INELIGIBLE",
                "This mattress is not eligible for donation")
        type_order = ("CHARITY", "RECYCLER")
    else:
        type_order = ("RECYCLER",)

    region_code = _completed_route_region(case)
    candidates = list(db.disposition_partners.values())
    capacity_blocked_on_last_type = False

    for partner_type in type_order:
        eligible = []
        capacity_blocked_on_last_type = False
        for partner in candidates:
            non_capacity, capacity_ok, headroom = _clauses(
                partner, partner_type, region_code, case, units, intake_date)
            if not non_capacity:
                continue
            if capacity_ok:
                eligible.append((partner, headroom))
            else:
                capacity_blocked_on_last_type = True
        if eligible:
            eligible.sort(key=lambda item: (item[0]["priority_rank"],
                                            -item[1],
                                            item[0]["created_at"],
                                            item[0]["_seq"]))
            winner = eligible[0][0]
            fallback = (requested_disposition == "DONATION"
                        and partner_type == "RECYCLER")
            return winner, fallback

    if capacity_blocked_on_last_type:
        raise api_error(
            "ERR_PARTNER_INTAKE_CAPACITY_EXCEEDED",
            "Every otherwise eligible disposition partner is at its daily "
            "intake capacity for this date")
    raise api_error(
        "ERR_NO_DISPOSITION_PARTNER",
        "No disposition partner can accept this mattress")
