"""calculations.invitation_package_valuation (PRD 3.4)."""
from constants import (
    AIR_CLASS_VALUE_CENTS,
    GROUND_TRANSPORT_CENTS,
    HOTEL_NIGHTLY_CENTS,
    MAX_HOTEL_NIGHTS,
)
from services import lookup


def record_field_name(division, gender):
    """record_class(ELITE) = record_class(SUB_ELITE) = OPEN;
    record_class(WHEELCHAIR) = WHEELCHAIR."""
    if division == "WHEELCHAIR":
        return (
            "course_record_wheelchair_male_seconds"
            if gender == "MALE"
            else "course_record_wheelchair_female_seconds"
        )
    return (
        "course_record_male_seconds" if gender == "MALE" else "course_record_female_seconds"
    )


def course_record(edition, division, gender):
    return edition[record_field_name(division, gender)]


def guaranteed_valuation(invitation):
    fee = invitation["current_appearance_fee_cents"] or 0
    air_class = invitation["current_air_class"]
    air_value = AIR_CLASS_VALUE_CENTS.get(air_class, 0) if air_class else 0
    nights = invitation["current_hotel_nights"] or 0
    hotel_value = HOTEL_NIGHTLY_CENTS * min(nights, MAX_HOTEL_NIGHTS)
    ground_value = GROUND_TRANSPORT_CENTS if invitation["current_ground_transport"] else 0
    return fee + air_value + hotel_value + ground_value


def _bonus_line_amount(edition_id, category, division, gender):
    amounts = [
        line["amount_cents"]
        for line in lookup.edition_purse_lines(edition_id)
        if line["category"] == category
        and line["division"] == division
        and line["gender"] == gender
    ]
    return max(amounts) if amounts else 0


def full_exposure_valuation(edition, invitation, athlete):
    guaranteed = guaranteed_valuation(invitation)
    time_exposure = _bonus_line_amount(
        edition["id"], "TIME_BONUS", invitation["division"], athlete["gender"]
    )
    performance = lookup.soft_get(
        "performance_records", invitation["qualifying_performance_id"]
    )
    qual_seconds = performance["verified_seconds"] if performance else None
    key_record = course_record(edition, invitation["division"], athlete["gender"])
    if key_record is None:
        record_threat = True
    elif qual_seconds is None:
        record_threat = False
    else:
        record_threat = qual_seconds <= key_record
    record_exposure = 0
    if record_threat:
        record_exposure = _bonus_line_amount(
            edition["id"], "RECORD_BONUS", invitation["division"], athlete["gender"]
        )
    return guaranteed + time_exposure + record_exposure
