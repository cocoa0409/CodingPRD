"""Existence resolution (priority 3, PRD 2.10): path ids left to right first,
then body foreign keys in the order they appear in the endpoint input list."""
from db import db, sorted_rows
from errors import err

_NOT_FOUND = {
    "race_editions": "ERR_RACE_EDITION_NOT_FOUND",
    "athletes": "ERR_ATHLETE_NOT_FOUND",
    "rep_agents": "ERR_REP_AGENT_NOT_FOUND",
    "performance_records": "ERR_PERFORMANCE_RECORD_NOT_FOUND",
    "invitations": "ERR_INVITATION_NOT_FOUND",
    "doping_tests": "ERR_DOPING_TEST_NOT_FOUND",
    "race_results": "ERR_RACE_RESULT_NOT_FOUND",
    "prize_awards": "ERR_PRIZE_AWARD_NOT_FOUND",
}


def _resolve(collection, entity_id):
    if not isinstance(entity_id, str):
        raise err(_NOT_FOUND[collection], "%s does not resolve" % collection)
    row = getattr(db, collection).get(entity_id)
    if row is None:
        raise err(_NOT_FOUND[collection], "Referenced %s does not exist" % collection)
    return row


def get_edition(edition_id):
    return _resolve("race_editions", edition_id)


def get_athlete(athlete_id):
    return _resolve("athletes", athlete_id)


def get_agent(agent_id):
    return _resolve("rep_agents", agent_id)


def get_performance(performance_id):
    return _resolve("performance_records", performance_id)


def get_invitation(invitation_id):
    return _resolve("invitations", invitation_id)


def get_doping_test(test_id):
    return _resolve("doping_tests", test_id)


def get_result(result_id):
    return _resolve("race_results", result_id)


def get_award(award_id):
    return _resolve("prize_awards", award_id)


def soft_get(collection, entity_id):
    """Non-raising lookup, for internal reads of already-validated links."""
    if not isinstance(entity_id, str):
        return None
    return getattr(db, collection).get(entity_id)


# --- collection scans ---------------------------------------------------------

def rows(collection, **match):
    out = []
    for row in getattr(db, collection).values():
        ok = True
        for key, value in match.items():
            if row.get(key) != value:
                ok = False
                break
        if ok:
            out.append(row)
    return sorted_rows(out)


def edition_invitations(edition_id):
    return rows("invitations", race_edition_id=edition_id)


def edition_purse_lines(edition_id):
    return rows("purse_lines", race_edition_id=edition_id)


def edition_standards(edition_id):
    return rows("division_standards", race_edition_id=edition_id)


def edition_results(edition_id):
    return rows("race_results", race_edition_id=edition_id)


def edition_awards(edition_id):
    return rows("prize_awards", race_edition_id=edition_id)


def edition_doping_tests(edition_id):
    return rows("doping_tests", race_edition_id=edition_id)


def invitation_rounds(invitation_id):
    return sorted(
        rows("negotiation_rounds", invitation_id=invitation_id),
        key=lambda r: r["round_number"],
    )


def invitation_slots(invitation_id):
    return rows("fluid_station_slots", invitation_id=invitation_id)


def find_standard(edition_id, division, gender):
    for row in edition_standards(edition_id):
        if row["division"] == division and row["gender"] == gender:
            return row
    return None
