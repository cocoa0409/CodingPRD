"""calculations.place_and_tie_assignment (PRD 3.7)."""
from clock import parse_date
from db import touch
from services import lookup


def age_years(birth_date, race_date):
    """Difference of years, reduced by one when the race month-and-day falls
    before the birth month-and-day (a birthday on race day counts)."""
    reduction = 1 if (race_date.month, race_date.day) < (birth_date.month, birth_date.day) else 0
    return race_date.year - birth_date.year - reduction


def result_is_masters(edition, result):
    athlete = lookup.soft_get("athletes", result["athlete_id"])
    if athlete is None:
        return False
    race_date = parse_date(edition["race_date"], "race_date")
    birth_date = parse_date(athlete["birth_date"], "birth_date")
    return age_years(birth_date, race_date) >= edition["masters_min_age"]


def athlete_gender(result):
    athlete = lookup.soft_get("athletes", result["athlete_id"])
    return athlete["gender"] if athlete else None


def _place_in(partition, result):
    return 1 + sum(
        1 for other in partition if other["official_seconds"] < result["official_seconds"]
    )


def _apply(result, changes):
    changed = any(result.get(key) != value for key, value in changes.items())
    if changed:
        result.update(changes)
        touch(result)
    return changed


def assign_places(edition):
    """Writes place_overall / place_division / place_masters / tie_group_size /
    is_masters over the edition's CERTIFIED results.  Returns True when any
    result actually changed."""
    certified = [
        r for r in lookup.edition_results(edition["id"])
        if r["certification_status"] == "CERTIFIED"
    ]
    gender = {}
    masters = {}
    for result in certified:
        gender[result["id"]] = athlete_gender(result)
        masters[result["id"]] = result_is_masters(edition, result)

    overall_part = {}
    division_part = {}
    masters_part = {}
    for result in certified:
        g = gender[result["id"]]
        if result["division"] in ("ELITE", "SUB_ELITE"):
            overall_part.setdefault(g, []).append(result)
        division_part.setdefault((result["division"], g), []).append(result)
        if result["division"] == "ELITE" and masters[result["id"]]:
            masters_part.setdefault(g, []).append(result)

    any_changed = False
    for result in certified:
        g = gender[result["id"]]
        in_overall = result["division"] in ("ELITE", "SUB_ELITE")
        place_overall = _place_in(overall_part[g], result) if in_overall else None
        place_division = _place_in(division_part[(result["division"], g)], result)
        if result["division"] == "ELITE" and masters[result["id"]]:
            place_masters = _place_in(masters_part[g], result)
        else:
            place_masters = None
        tie_partition = (
            overall_part[g] if place_overall is not None
            else division_part[(result["division"], g)]
        )
        tie_group_size = sum(
            1 for other in tie_partition
            if other["official_seconds"] == result["official_seconds"]
        )
        changed = _apply(result, {
            "is_masters": masters[result["id"]],
            "place_overall": place_overall,
            "place_division": place_division,
            "place_masters": place_masters,
            "tie_group_size": tie_group_size,
        })
        any_changed = any_changed or changed
    return any_changed
