"""Schema validation (ladder rung 3), auth rungs 1/2/6/7/8, credential rungs 9/23."""
import re
from datetime import datetime, timezone

from flask import request

import constants as C
from db import db
from errors import ApiError

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d+)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def bad(message=None):
    raise ApiError("ERR_INVALID_REQUEST", message=message)


# ---------------------------------------------------------------- body parsing
def body():
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        bad("Request body must be valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        bad("Request body must be a JSON object.")
    return parsed


def no_unknown(_b, _allowed):
    # Unknown keys are tolerated; the spec never refuses them.
    return


# ------------------------------------------------------------- typed accessors
def _present(b, key):
    return key in b and b[key] is not None


def req_str(b, key, min_len=1, max_len=None):
    if not _present(b, key):
        bad("%s is required." % key)
    v = b[key]
    if not isinstance(v, str):
        bad("%s must be a string." % key)
    if len(v) < min_len:
        bad("%s must be at least %d characters." % (key, min_len))
    if max_len is not None and len(v) > max_len:
        bad("%s must be at most %d characters." % (key, max_len))
    return v


def opt_str(b, key, min_len=0, max_len=None, default=None):
    if not _present(b, key):
        if key in b and b[key] is None:
            return None
        return default
    return req_str(b, key, min_len=min_len, max_len=max_len)


def req_int(b, key, lo=None, hi=None):
    if not _present(b, key):
        bad("%s is required." % key)
    v = b[key]
    if isinstance(v, bool) or not isinstance(v, int):
        bad("%s must be an integer." % key)
    if lo is not None and v < lo:
        bad("%s must be at least %d." % (key, lo))
    if hi is not None and v > hi:
        bad("%s must be at most %d." % (key, hi))
    return v


def opt_int(b, key, lo=None, hi=None, default=None):
    if not _present(b, key):
        return default
    return req_int(b, key, lo, hi)


def req_enum(b, key, allowed):
    v = req_str(b, key)
    if v not in allowed:
        bad("%s must be one of %s." % (key, ", ".join(allowed)))
    return v


def opt_enum(b, key, allowed, default=None):
    if not _present(b, key):
        return default
    return req_enum(b, key, allowed)


def req_id(b, key):
    return req_str(b, key)


def opt_id(b, key):
    if key not in b or b[key] is None:
        return None
    v = b[key]
    if not isinstance(v, str) or len(v) == 0:
        bad("%s must be a string identifier." % key)
    return v


def req_dt(b, key):
    v = req_str(b, key)
    parsed = parse_dt(v)
    if parsed is None:
        bad("%s must be an ISO 8601 UTC timestamp." % key)
    return parsed


def parse_dt(value):
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    text = value.strip().replace(" ", "T")
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def req_enum_array(b, key, allowed, allow_empty=True):
    if key not in b or b[key] is None:
        bad("%s is required." % key)
    v = b[key]
    if not isinstance(v, list):
        bad("%s must be an array." % key)
    if not allow_empty and len(v) == 0:
        bad("%s must not be empty." % key)
    for item in v:
        if not isinstance(item, str) or item not in allowed:
            bad("%s contains an unrecognised value." % key)
    return list(v)


# ------------------------------------------------------------- query filtering
def filter_enum(name, allowed):
    if name not in request.args:
        return None
    v = request.args.get(name)
    if v not in allowed:
        bad("%s must be one of %s." % (name, ", ".join(allowed)))
    return v


def filter_int(name, lo=None, hi=None):
    if name not in request.args:
        return None
    raw = request.args.get(name)
    try:
        v = int(raw.strip())
    except (TypeError, ValueError, AttributeError):
        bad("%s must be an integer." % name)
    if lo is not None and v < lo:
        bad("%s must be at least %d." % (name, lo))
    if hi is not None and v > hi:
        bad("%s must be at most %d." % (name, hi))
    return v


def filter_str(name):
    if name not in request.args:
        return None
    v = request.args.get(name)
    if v is None or v == "":
        bad("%s must be a non-empty string." % name)
    return v


def filter_bool(name):
    if name not in request.args:
        return None
    v = request.args.get(name)
    if v in ("true", "True", "TRUE", "1"):
        return True
    if v in ("false", "False", "FALSE", "0"):
        return False
    bad("%s must be a boolean." % name)


# ----------------------------------------------------------------- auth rungs
class Actor(object):
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role
        self.clinician = None

    @property
    def is_clinician_role(self):
        return self.role in C.AFFILIATION_BY_ROLE


def authenticate(allowed_roles):
    """Rung 1 then rung 2."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in C.ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return Actor(user_id, role)


def role_identity(actor):
    """Rung 6: the three clinician-backed roles must resolve to a matching clinician."""
    if not actor.is_clinician_role:
        return None
    clinician = db.clinicians.get(actor.user_id)
    if clinician is None:
        raise ApiError("ERR_ROLE_IDENTITY_MISMATCH")
    if clinician["affiliation"] != C.AFFILIATION_BY_ROLE[actor.role]:
        raise ApiError("ERR_ROLE_IDENTITY_MISMATCH")
    if actor.role == "IndependentConsultant" and clinician.get("club_id") is not None:
        raise ApiError("ERR_ROLE_IDENTITY_MISMATCH")
    actor.clinician = clinician
    return clinician


def officer_scope(actor, club_id):
    """Rung 7."""
    if actor.role == "ClubComplianceOfficer" and actor.user_id != club_id:
        raise ApiError("ERR_CLUB_SCOPE_VIOLATION")


def physician_scope(actor, club_id):
    """Rung 8."""
    if actor.role == "ClubPhysician":
        if actor.clinician is None or actor.clinician.get("club_id") != club_id:
            raise ApiError("ERR_CLUB_SCOPE_VIOLATION")


def not_suspended(clinician):
    """Rung 9."""
    if clinician is not None and clinician["status"] != "ACTIVE":
        raise ApiError("ERR_CLINICIAN_SUSPENDED")


def credential_valid(clinician):
    """Rung 23: valid only while now is strictly earlier than credential_expires_at."""
    if clinician is None:
        return
    expires = clinician.get("credential_expires_at")
    if expires is None or db.now >= expires:
        raise ApiError("ERR_CLINICIAN_CREDENTIAL_EXPIRED")


# ------------------------------------------------------------- row resolution
def _resolve(store, row_id, error_id):
    if not isinstance(row_id, str):
        raise ApiError(error_id)
    row = store.get(row_id)
    if row is None:
        raise ApiError(error_id)
    return row


def get_club(row_id):
    return _resolve(db.clubs, row_id, "ERR_CLUB_NOT_FOUND")


def get_clinician(row_id):
    return _resolve(db.clinicians, row_id, "ERR_CLINICIAN_NOT_FOUND")


def get_player(row_id):
    return _resolve(db.players, row_id, "ERR_PLAYER_NOT_FOUND")


def get_game(row_id):
    return _resolve(db.games, row_id, "ERR_GAME_NOT_FOUND")


def get_evaluation(row_id):
    return _resolve(db.sideline_evaluations, row_id, "ERR_EVALUATION_NOT_FOUND")


def get_case(row_id):
    return _resolve(db.concussion_cases, row_id, "ERR_CASE_NOT_FOUND")


def get_baseline(row_id):
    return _resolve(db.baseline_tests, row_id, "ERR_RESOURCE_NOT_FOUND")


def get_step(row_id):
    return _resolve(db.return_steps, row_id, "ERR_RESOURCE_NOT_FOUND")


def get_clearance(row_id):
    return _resolve(db.inc_clearances, row_id, "ERR_RESOURCE_NOT_FOUND")


def get_audit(row_id):
    return _resolve(db.protocol_audits, row_id, "ERR_RESOURCE_NOT_FOUND")


def get_report(row_id):
    return _resolve(db.injury_report_entries, row_id, "ERR_RESOURCE_NOT_FOUND")
