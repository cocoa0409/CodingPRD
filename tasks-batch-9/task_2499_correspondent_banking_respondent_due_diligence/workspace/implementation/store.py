"""In-memory data store. Empty on every boot: no seeding, no persistence."""

import itertools
import uuid

from flask import g

import clock

COLLECTIONS = (
    "jurisdictions",
    "respondents",
    "owners",
    "questionnaires",
    "control_assessments",
    "nested",
    "profiles",
    "observations",
    "alerts",
    "rfis",
    "media",
    "refreshes",
    "payments",
    "plans",
)

db = {name: {} for name in COLLECTIONS}

_seq = itertools.count(1)


def next_seq():
    return next(_seq)


def new_id():
    return str(uuid.uuid4())


def insert(collection, fields):
    """Create a row with the four common properties and store it."""
    stamp = clock.iso(clock.now())
    row = {"id": new_id()}
    row.update(fields)
    row["created_at"] = stamp
    row["updated_at"] = stamp
    row["version"] = 1
    row["_seq"] = next_seq()
    row["_dt"] = {}
    db[collection][row["id"]] = row
    _mark_touched(row)
    return row


def _touched_set():
    s = getattr(g, "_touched_rows", None)
    if s is None:
        s = set()
        g._touched_rows = s
    return s


def _mark_touched(row):
    _touched_set().add(row["id"])


def touch(row):
    """Bump updated_at/version at most once per request for this row."""
    if row is None:
        return row
    seen = _touched_set()
    if row["id"] in seen:
        return row
    seen.add(row["id"])
    row["updated_at"] = clock.iso(clock.now())
    row["version"] = row["version"] + 1
    return row


def dt(row, field):
    """Parsed datetime for a stored ISO string field (cached per row)."""
    cache = row.setdefault("_dt", {})
    raw = row.get(field)
    if raw is None:
        return None
    hit = cache.get(field)
    if hit is not None and hit[0] == raw:
        return hit[1]
    parsed = clock.parse_instant(raw)
    cache[field] = (raw, parsed)
    return parsed


def set_dt(row, field, value):
    """Write a computed datetime field in canonical form."""
    row[field] = clock.iso(value) if value is not None else None
    row.setdefault("_dt", {}).pop(field, None)


def all_rows(collection):
    return list(db[collection].values())


def by_seq(rows):
    """created_at ascending (insertion order is the normative tie-break)."""
    return sorted(rows, key=lambda r: r["_seq"])


def by_seq_desc(rows):
    return sorted(rows, key=lambda r: -r["_seq"])


def get(collection, row_id):
    if not isinstance(row_id, str):
        return None
    return db[collection].get(row_id)


def find(collection, **eq):
    out = []
    for row in db[collection].values():
        if all(row.get(k) == v for k, v in eq.items()):
            out.append(row)
    return by_seq(out)


# ---------------------------------------------------------------- helpers ---

def jurisdiction_by_code(code):
    if not isinstance(code, str):
        return None
    for row in db["jurisdictions"].values():
        if row["jurisdiction_code"] == code:
            return row
    return None


def owners_of(respondent_id):
    return find("owners", respondent_bank_id=respondent_id)


def questionnaires_of(respondent_id):
    return find("questionnaires", respondent_bank_id=respondent_id)


def controls_of(questionnaire_id):
    return find("control_assessments", questionnaire_id=questionnaire_id)


def nested_of(respondent_id):
    return find("nested", respondent_bank_id=respondent_id)


def profiles_of(respondent_id):
    return find("profiles", respondent_bank_id=respondent_id)


def observations_of_profile(profile_id):
    return find("observations", monitoring_profile_id=profile_id)


def observations_of(respondent_id):
    ids = {p["id"] for p in profiles_of(respondent_id)}
    return by_seq([o for o in db["observations"].values()
                   if o["monitoring_profile_id"] in ids])


def alerts_of(respondent_id):
    return find("alerts", respondent_bank_id=respondent_id)


def rfis_of(respondent_id):
    return find("rfis", respondent_bank_id=respondent_id)


def media_of(respondent_id):
    return find("media", respondent_bank_id=respondent_id)


def refreshes_of(respondent_id):
    return find("refreshes", respondent_bank_id=respondent_id)


def payments_of(respondent_id):
    return find("payments", respondent_bank_id=respondent_id)


def plans_of(respondent_id):
    return find("plans", respondent_bank_id=respondent_id)
