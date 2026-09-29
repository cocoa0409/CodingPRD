"""Four-gate eligibility screen (PRD 3.5, ladder priorities 29-32)."""

from errors import ApiError, fail

GUEST_MOBILITY_RANK = {"WHEELCHAIR": 1, "ASSISTED": 2, "FULL": 3}
REQUIRED_MOBILITY_RANK = {"LEVEL_1": 1, "LEVEL_2": 2, "LEVEL_3": 3, "LEVEL_4": 3}
LEVEL4_EXCLUDED_FLAGS = ("CARDIAC", "RESPIRATORY", "PREGNANCY")


def age_at_meeting(guest, meeting_time_utc):
    birth = guest["birth_date"]
    years = meeting_time_utc.year - birth.year
    if (meeting_time_utc.month, meeting_time_utc.day) < (birth.month, birth.day):
        years -= 1
    return years


def screen(guest, excursion, age, language_choice, acknowledged):
    """Raise the first eligibility objection in ladder order."""
    # 29 - age band, inclusive on both sides
    if age < excursion["min_age"]:
        fail("ERR_AGE_RESTRICTION", "guest is below the excursion minimum age")
    if excursion.get("max_age") is not None and age > excursion["max_age"]:
        fail("ERR_AGE_RESTRICTION", "guest is above the excursion maximum age")

    # 30 - mobility rank and the absolute LEVEL_4 medical exclusion
    guest_rank = GUEST_MOBILITY_RANK[guest["mobility_level"]]
    required_rank = REQUIRED_MOBILITY_RANK[excursion["mobility_level"]]
    if guest_rank < required_rank:
        fail("ERR_MOBILITY_RESTRICTION", "guest mobility rank is below the excursion requirement")
    if excursion["mobility_level"] == "LEVEL_4":
        for flag in guest.get("medical_flags") or []:
            if flag in LEVEL4_EXCLUDED_FLAGS:
                fail("ERR_MOBILITY_RESTRICTION", "medical flag excluded from a LEVEL_4 excursion")

    # 31 - medical acknowledgement, only on a non-empty intersection
    intersection = set(guest.get("medical_flags") or []) & set(excursion.get("medical_warning_codes") or [])
    if intersection and acknowledged is not True:
        fail("ERR_MEDICAL_ACK_REQUIRED", "the guest's medical flags require acknowledgement")

    # 32 - language availability
    if language_choice not in (excursion.get("languages") or []):
        fail("ERR_LANGUAGE_UNAVAILABLE", "the chosen language is not offered on this excursion")


def passes(guest, excursion, age, language_choice, acknowledged):
    try:
        screen(guest, excursion, age, language_choice, acknowledged)
    except ApiError:
        return False
    return True
