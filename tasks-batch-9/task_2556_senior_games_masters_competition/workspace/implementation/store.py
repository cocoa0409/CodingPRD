"""In-memory store. Empty on every boot; every row is created through the API."""
from core import LogicalClock, fail, iso_ms, new_id

CLOCK = LogicalClock()

KINDS = (
    "games_edition",
    "sport",
    "sport_event",
    "venue",
    "session_slot",
    "athlete",
    "qualifying_result",
    "sport_entry",
    "medical_screening",
    "personnel",
    "personnel_assignment",
    "competition_result",
    "age_group_record",
    "accommodation_block",
    "village_stay",
    "sponsorship_commitment",
)

NOT_FOUND = {
    "games_edition": "ERR_GAMES_EDITION_NOT_FOUND",
    "sport": "ERR_SPORT_NOT_FOUND",
    "sport_event": "ERR_SPORT_EVENT_NOT_FOUND",
    "venue": "ERR_VENUE_NOT_FOUND",
    "session_slot": "ERR_SESSION_SLOT_NOT_FOUND",
    "athlete": "ERR_ATHLETE_NOT_FOUND",
    "qualifying_result": "ERR_QUALIFYING_RESULT_NOT_FOUND",
    "sport_entry": "ERR_SPORT_ENTRY_NOT_FOUND",
    "medical_screening": "ERR_MEDICAL_SCREENING_NOT_FOUND",
    "personnel": "ERR_PERSONNEL_NOT_FOUND",
    "personnel_assignment": "ERR_PERSONNEL_ASSIGNMENT_NOT_FOUND",
    "competition_result": "ERR_COMPETITION_RESULT_NOT_FOUND",
    "age_group_record": "ERR_AGE_GROUP_RECORD_NOT_FOUND",
    "accommodation_block": "ERR_ACCOMMODATION_BLOCK_NOT_FOUND",
    "village_stay": "ERR_VILLAGE_STAY_NOT_FOUND",
    "sponsorship_commitment": "ERR_SPONSORSHIP_COMMITMENT_NOT_FOUND",
}

DB = {kind: {} for kind in KINDS}
_SEQ = [0]


def next_seq():
    _SEQ[0] += 1
    return _SEQ[0]


def now_iso():
    return iso_ms(CLOCK.now())


def insert(kind, fields, versioned=True):
    row = {"id": new_id()}
    row.update(fields)
    row["created_at"] = now_iso()
    if versioned:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    row["_seq"] = next_seq()
    DB[kind][row["id"]] = row
    return row


def touch(row):
    """One mutation of one row: fresh updated_at and version + 1."""
    row["updated_at"] = now_iso()
    row["version"] = row.get("version", 0) + 1
    return row


def get(kind, row_id):
    if not isinstance(row_id, str):
        return None
    return DB[kind].get(row_id)


def must_get(kind, row_id):
    row = get(kind, row_id)
    if row is None:
        fail(NOT_FOUND[kind])
    return row


def rows(kind):
    """Every row of a kind in default order: created_at ASC, insertion order."""
    return sorted(DB[kind].values(), key=lambda r: (r["created_at"], r["_seq"]))


def where(kind, **criteria):
    out = []
    for row in rows(kind):
        keep = True
        for key, value in criteria.items():
            if value is None:
                continue
            if row.get(key) != value:
                keep = False
                break
        if keep:
            out.append(row)
    return out


def serialize(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def serialize_all(items):
    return [serialize(row) for row in items]
