"""Path- and body-identifier resolution (PRD 2.8)."""

from errors import ApiError
from store import DB


def _find(collection, row_id, error_id):
    row = collection.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        raise ApiError(error_id)
    return row


def season(row_id):
    return _find(DB.seasons, row_id, "ERR_SEASON_NOT_FOUND")


def team(row_id):
    return _find(DB.teams, row_id, "ERR_TEAM_NOT_FOUND")


def assessor(row_id):
    return _find(DB.assessors, row_id, "ERR_ASSESSOR_NOT_FOUND")


def wrestler(row_id):
    return _find(DB.wrestlers, row_id, "ERR_WRESTLER_NOT_FOUND")


def assessment(row_id):
    return _find(DB.assessments, row_id, "ERR_ASSESSMENT_NOT_FOUND")


def appeal(row_id):
    return _find(DB.appeals, row_id, "ERR_APPEAL_NOT_FOUND")


def plan(row_id):
    return _find(DB.plans, row_id, "ERR_PLAN_NOT_FOUND")


def event(row_id):
    return _find(DB.events, row_id, "ERR_EVENT_NOT_FOUND")


def entry(row_id):
    return _find(DB.entries, row_id, "ERR_ENTRY_NOT_FOUND")


def weigh_in(row_id):
    return _find(DB.weighins, row_id, "ERR_WEIGH_IN_NOT_FOUND")


def check(row_id):
    return _find(DB.checks, row_id, "ERR_ELIGIBILITY_CHECK_NOT_FOUND")


def flag(row_id):
    return _find(DB.flags, row_id, "ERR_HEALTH_FLAG_NOT_FOUND")


def audit(row_id):
    return _find(DB.audits, row_id, "ERR_AUDIT_NOT_FOUND")


# --------------------------------------------------------------------------
# navigation helpers
# --------------------------------------------------------------------------

def team_of_wrestler(row):
    return DB.teams.get(row.get("team_id"))


def season_of_team(row):
    return DB.seasons.get(row.get("season_id")) if row else None


def season_of_wrestler(row):
    return season_of_team(team_of_wrestler(row))


def season_of_event(row):
    return DB.seasons.get(row.get("season_id")) if row else None


def season_of_assessment(row):
    return season_of_wrestler(DB.wrestlers.get(row.get("wrestler_id")))


def season_of_plan(row):
    return season_of_wrestler(DB.wrestlers.get(row.get("wrestler_id")))


def latest_season():
    """The most recently created Season (PRD 3.2 training threshold)."""
    rows = sorted(
        DB.seasons.values(),
        key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0),
    )
    return rows[-1] if rows else None


def wrestlers_of_team(team_id):
    return [w for w in DB.wrestlers.values() if w.get("team_id") == team_id]


def flags_of_wrestler(wrestler_id):
    return [f for f in DB.flags.values() if f.get("wrestler_id") == wrestler_id]


def plans_of_wrestler(wrestler_id):
    return [p for p in DB.plans.values() if p.get("wrestler_id") == wrestler_id]


def milestones_of_plan(plan_id):
    return [m for m in DB.milestones.values() if m.get("plan_id") == plan_id]


def entries_of_event(event_id):
    return [e for e in DB.entries.values() if e.get("event_id") == event_id]


def entries_of_wrestler(wrestler_id):
    return [e for e in DB.entries.values() if e.get("wrestler_id") == wrestler_id]


def weighins_of_entry(entry_id):
    return [w for w in DB.weighins.values() if w.get("entry_id") == entry_id]


def weighins_of_wrestler(wrestler_id):
    return [w for w in DB.weighins.values() if w.get("wrestler_id") == wrestler_id]


def assessments_of_assessor(assessor_id):
    return [a for a in DB.assessments.values() if a.get("assessor_id") == assessor_id]


def assessments_of_wrestler(wrestler_id):
    return [a for a in DB.assessments.values() if a.get("wrestler_id") == wrestler_id]


def growth_of_season(season_id):
    return [gr for gr in DB.growth.values() if gr.get("season_id") == season_id]


def events_of_season(season_id):
    return [e for e in DB.events.values() if e.get("season_id") == season_id]


def teams_of_season(season_id):
    return [t for t in DB.teams.values() if t.get("season_id") == season_id]


def appeals_of_assessment(assessment_id):
    return [a for a in DB.appeals.values() if a.get("assessment_id") == assessment_id]
