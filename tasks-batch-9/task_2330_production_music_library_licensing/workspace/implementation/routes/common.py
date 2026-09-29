"""Helpers shared by the route modules."""

from db import DB, date_only, parse_ts
from errors import fail
from middleware import is_role, user_id

PREFIX = "/music-library"

GENRES = ("CINEMATIC", "ROCK", "ELECTRONIC", "JAZZ", "FOLK", "HIPHOP", "CLASSICAL")
MOODS = ("UPLIFTING", "HOPEFUL", "EPIC", "DARK", "TENSE", "CALM", "QUIRKY")
INSTRUMENTS = ("PIANO", "STRINGS", "BRASS", "GUITAR", "SYNTH", "PERCUSSION", "VOCALS")
MEDIA_TYPES = ("BROADCAST_TV", "ONLINE_AD", "FILM", "CORPORATE", "GAME")
SCALES = ("LOCAL", "NATIONAL", "WORLDWIDE")
USAGE_TYPES = ("THEME", "FEATURE", "BACKGROUND", "LOGO")
MARKET_TIERS = ("NETWORK", "CABLE", "LOCAL", "DIGITAL")
PRO_AFFILIATIONS = ("ASCAP", "BMI", "SESAC", "PRS", "NONE")
LICENSEE_TYPES = ("BROADCASTER", "PRODUCTION_COMPANY", "AGENCY", "GAME_STUDIO")
CADENCES = ("MONTHLY", "QUARTERLY")
SOURCE_TYPES = (
    "SYNC_FEE",
    "SYNC_FEE_REVERSAL",
    "PERFORMANCE",
    "PERFORMANCE_REVERSAL",
    "BLANKET_POOL",
    "SETTLEMENT",
    "ADVANCE",
    "ADVANCE_RECOUP",
    "ADJUSTMENT",
)


def set_dt(row, name, raw, parsed):
    """Store a client-supplied timestamp verbatim plus its parsed twin."""
    row[name] = raw
    row["_%s_dt" % name] = parsed
    return row


def set_clock_dt(row, name, moment=None):
    """Store a server-written instant from the logical clock."""
    from db import fmt_ts

    moment = DB.now if moment is None else moment
    row[name] = fmt_ts(moment)
    row["_%s_dt" % name] = moment
    return row


def today():
    return date_only(DB.now)


def as_dt(value):
    return parse_ts(value)


# ---------------------------------------------------------------------------
# ownership guards (ladder steps 5 and 6)
# ---------------------------------------------------------------------------
def guard_licensee(licensee_id):
    if is_role("Licensee") and user_id() != licensee_id:
        fail("ERR_LICENSEE_MISMATCH", "This row belongs to another licensee.")


def guard_composer(composer_id):
    if is_role("Composer") and user_id() != composer_id:
        fail("ERR_COMPOSER_IDENTITY_MISMATCH", "This row belongs to another composer.")


# ---------------------------------------------------------------------------
# query filters
# ---------------------------------------------------------------------------
def filter_rows(rows, args, fields):
    """Keep rows whose field equals the query parameter, when supplied."""
    out = rows
    for name in fields:
        wanted = args.get(name)
        if wanted is None or wanted == "":
            continue
        out = [r for r in out if r.get(name) == wanted]
    return out


def state_error(entity):
    return {
        "agreement": "ERR_AGREEMENT_STATE_INVALID",
        "composition": "ERR_COMPOSITION_STATE_INVALID",
        "sync_request": "ERR_SYNC_REQUEST_STATE_INVALID",
        "license": "ERR_LICENSE_STATE_INVALID",
        "blanket": "ERR_BLANKET_STATE_INVALID",
        "report": "ERR_REPORT_STATE_INVALID",
        "cue_sheet": "ERR_CUE_SHEET_STATE_INVALID",
        "claim": "ERR_CLAIM_STATE_INVALID",
        "statement": "ERR_STATEMENT_STATE_INVALID",
    }[entity]


def require_state(row, field, allowed, entity):
    """Ladder step 10."""
    if row[field] not in allowed:
        fail(
            state_error(entity),
            "%s is %r; this transition accepts %s."
            % (field, row[field], ", ".join(allowed)),
        )
