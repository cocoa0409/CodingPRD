"""Public JSON projection of stored records.

Strips internal bookkeeping (e.g. _seq) and exposes each entity's declared
field set (SCAFFOLD §1.1). Computed fields are stored on the record and kept
reconciled by the services layer (PRD §2.5 immediate reconciliation).
"""

_COMMON = ["id", "created_at", "updated_at", "version"]
_LEAN = ["id", "created_at"]  # ConflictDeclaration / Evaluation

LEAGUE_FIELDS = [
    "name", "sport", "base_game_fee_cents", "mileage_rate_cents_per_mile",
    "postseason_min_games", "postseason_min_rating", "postseason_max_noshows",
    "status",
]

OFFICIAL_FIELDS = [
    "league_id", "full_name", "rank", "home_lat", "home_lon",
    "max_travel_miles", "status",
    "games_worked_count", "noshow_count", "penalty_points", "mean_rating",
    "reliability_score", "postseason_eligible",
]

GAME_FIELDS = [
    "league_id", "home_team", "away_team", "venue_lat", "venue_lon",
    "start_utc", "duration_minutes", "required_crew_size", "is_postseason",
    "status", "crew_filled_count", "settlement_total_cents",
]

CREW_SLOT_FIELDS = [
    "game_id", "position", "slot_fee_multiplier", "status",
    "current_assignment_id",
]

ASSIGNMENT_FIELDS = [
    "crew_slot_id", "game_id", "official_id", "status", "distance_miles",
    "provisional_pay_cents", "final_pay_cents", "mileage_cents",
    "penalty_assessed_points",
]

AVAILABILITY_FIELDS = [
    "official_id", "window_start_utc", "window_end_utc", "kind", "status",
]

CONFLICT_FIELDS = [
    "official_id", "scope", "team_name", "peer_official_id",
]

EVALUATION_FIELDS = [
    "assignment_id", "official_id", "score", "comment",
]

LEDGER_FIELDS = [
    "league_id", "official_id", "penalty_points", "total_pay_accrued_cents",
    "total_mileage_accrued_cents",
]

APPEAL_FIELDS = [
    "assignment_id", "official_id", "reason", "status", "reversed_points",
]


def _project(record, fields, common):
    out = {}
    for k in common:
        out[k] = record.get(k)
    for k in fields:
        out[k] = record.get(k)
    return out


def league(r):
    return _project(r, LEAGUE_FIELDS, _COMMON)


def official(r):
    return _project(r, OFFICIAL_FIELDS, _COMMON)


def game(r):
    return _project(r, GAME_FIELDS, _COMMON)


def crew_slot(r):
    return _project(r, CREW_SLOT_FIELDS, _COMMON)


def assignment(r):
    return _project(r, ASSIGNMENT_FIELDS, _COMMON)


def availability(r):
    return _project(r, AVAILABILITY_FIELDS, _COMMON)


def conflict(r):
    return _project(r, CONFLICT_FIELDS, _LEAN)


def evaluation(r):
    return _project(r, EVALUATION_FIELDS, _LEAN)


def ledger(r):
    return _project(r, LEDGER_FIELDS, _COMMON)


def appeal(r):
    return _project(r, APPEAL_FIELDS, _COMMON)
