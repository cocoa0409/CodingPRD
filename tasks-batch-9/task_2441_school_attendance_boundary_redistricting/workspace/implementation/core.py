"""Core infrastructure: error catalog, logical clock, in-memory store, response
envelope, auth middleware and request validators.

Every structural name in this module (header names, envelope field names,
pagination parameter names, error ids) is taken from PRD.md sections 2.1-2.10
and the SCAFFOLD.yaml response_envelope / errors / roles tables.
"""

import random
import re
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify, request

UTC = timezone.utc

# PRD 2.5 - on a fresh server the logical clock stands at 2026-08-01T00:00:00Z.
CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

# --------------------------------------------------------------------------
# Enumerations (PRD 3.x)
# --------------------------------------------------------------------------
ROLES = (
    "DistrictPlanner",
    "EngagementCoordinator",
    "BoardMember",
    "TransferOfficer",
    "Guardian",
)
ALL_ROLES = list(ROLES)
READ_ROLES_PUBLIC = [
    "DistrictPlanner",
    "EngagementCoordinator",
    "BoardMember",
    "TransferOfficer",
    "Guardian",
]
READ_ROLES_INTERNAL = [
    "DistrictPlanner",
    "EngagementCoordinator",
    "BoardMember",
    "TransferOfficer",
]

LEVELS = ("ELEMENTARY", "MIDDLE", "HIGH")
PROGRAM_TYPES = ("DUAL_LANGUAGE", "SPECIAL_ED_INTENSIVE", "GIFTED_MAGNET")
SCHOOL_STATUSES = ("ACTIVE", "MOTHBALLED")
STUDY_STATUSES = (
    "SETUP",
    "DATA_LOCKED",
    "SCENARIO_DEVELOPMENT",
    "ENGAGEMENT",
    "BOARD_DECISION",
    "IMPLEMENTATION",
    "CLOSED",
)
UNIT_TYPES = ("SINGLE_FAMILY", "TOWNHOME", "MULTI_FAMILY")
ENTITLEMENT_STAGES = (
    "PROPOSED",
    "ENTITLED",
    "PERMITTED",
    "UNDER_CONSTRUCTION",
    "COMPLETE",
    "WITHDRAWN",
)
ENTITLEMENT_FORWARD = {
    "PROPOSED": "ENTITLED",
    "ENTITLED": "PERMITTED",
    "PERMITTED": "UNDER_CONSTRUCTION",
    "UNDER_CONSTRUCTION": "COMPLETE",
}
RUN_VARIANTS = ("COHORT_SURVIVAL", "DEVELOPMENT_WEIGHTED")
RUN_STATUSES = ("COMPLETE", "STALE", "SUPERSEDED")
SCENARIO_STATUSES = (
    "DRAFT",
    "UNDER_REVIEW",
    "REVISION",
    "BOARD_READY",
    "ADOPTED",
    "REJECTED",
)
IMPACT_VARIANTS = ("RESIDENT_BASED", "PROJECTED_BASED")
COMMENT_THEMES = (
    "TRANSPORTATION",
    "SIBLING_SPLIT",
    "EQUITY",
    "CAPACITY",
    "PROGRAM_ACCESS",
    "OTHER",
)
COMMENT_PRIORITIES = ("LOW", "MEDIUM", "HIGH")
COMMENT_STATUSES = ("SUBMITTED", "TRIAGED", "ADDRESSED", "DISMISSED")
IMPLEMENTATION_STATUSES = (
    "PENDING_EFFECTIVE",
    "IN_EFFECT",
    "MONITORING_CLOSED",
    "RESCINDED",
)
TRANSFER_WINDOW_STATUSES = ("TRANSFER_WINDOW_OPEN", "TRANSFER_WINDOW_CLOSED")
RULE_TYPES = ("TERMINAL_GRADE_GRANDFATHER", "SIBLING_LINK", "PHASE_IN_GRADE_BAND")
TRANSFER_REASONS = ("GRANDFATHER", "SIBLING", "PHASE_IN", "HARDSHIP", "PROGRAM")
TRANSFER_STATUSES = ("SUBMITTED", "APPROVED", "DENIED", "WAITLISTED")
RESOLVED_REASONS = (
    "TERMINAL_GRADE_GRANDFATHER",
    "SIBLING_LINK",
    "PHASE_IN_GRADE_BAND",
    "HARDSHIP_REVIEW",
    "NONE",
)
DECISIONS = ("APPROVE", "DENY", "WAITLIST")
VARIANCE_FLAGS = ("WITHIN_TOLERANCE", "WATCH", "CORRECTIVE_ACTION_REQUIRED")

MAX_REVISION_ROUNDS = 3

# --------------------------------------------------------------------------
# Error catalog (PRD section 5 / SCAFFOLD 1.6)
# --------------------------------------------------------------------------
ERRORS = {
    "ERR_UNAUTHENTICATED": (401, "Request is missing the X-User-ID or X-User-Role identity headers."),
    "ERR_UNAUTHORIZED": (403, "The caller's role is not permitted to perform this operation."),
    "ERR_SELF_REVIEW_FORBIDDEN": (403, "The planner who authored this scenario may not review, revise or advance it."),
    "ERR_SELF_ADOPTION_FORBIDDEN": (403, "The planner who authored this scenario may not record its adoption."),
    "ERR_SELF_DECISION_FORBIDDEN": (403, "An operator may not decide a transfer request they filed."),
    "ERR_STUDY_NOT_FOUND": (404, "No boundary study exists with the supplied id."),
    "ERR_SCHOOL_NOT_FOUND": (404, "No school exists with the supplied id."),
    "ERR_AREA_NOT_FOUND": (404, "No planning area exists with the supplied id."),
    "ERR_DEVELOPMENT_NOT_FOUND": (404, "No housing development exists with the supplied id."),
    "ERR_PROJECTION_RUN_NOT_FOUND": (404, "No projection run exists with the supplied id."),
    "ERR_SCENARIO_NOT_FOUND": (404, "No boundary scenario exists with the supplied id."),
    "ERR_ASSIGNMENT_NOT_FOUND": (404, "No area assignment exists with the supplied id."),
    "ERR_COMMENT_NOT_FOUND": (404, "No public comment exists with the supplied id."),
    "ERR_ADOPTION_NOT_FOUND": (404, "No adoption record exists with the supplied id."),
    "ERR_TRANSFER_NOT_FOUND": (404, "No transfer request exists with the supplied id."),
    "ERR_OBSERVATION_NOT_FOUND": (404, "No variance observation exists with the supplied id."),
    "ERR_INVALID_REQUEST": (422, "The request body is missing a required field or carries a value outside its permitted domain."),
    "ERR_STUDY_PHASE_INVALID": (409, "The boundary study is not in a phase that permits this operation."),
    "ERR_NO_SCENARIO_UNDER_REVIEW": (409, "No scenario of this study is under review, so public engagement cannot open."),
    "ERR_STUDY_SETUP_INCOMPLETE": (409, "The study's seed inventory is incomplete, so its data cannot be locked."),
    "ERR_STUDY_DATA_LOCKED": (409, "The study's seed inventory is locked and may no longer be extended."),
    "ERR_ENTITLEMENT_STAGE_INVALID": (409, "The requested entitlement stage is not reachable from the development's current stage."),
    "ERR_SCENARIO_NOT_BOARD_READY": (409, "The scenario is not BOARD_READY, so it cannot be adopted."),
    "ERR_SCENARIO_NOT_EDITABLE": (409, "The scenario is not in DRAFT or REVISION, so its content is frozen."),
    "ERR_SCENARIO_NOT_REVIEWABLE": (409, "The scenario is not in a state that accepts this review action."),
    "ERR_COMMENT_STATE_INVALID": (409, "The public comment is not in a state that accepts this operation."),
    "ERR_SCHOOL_NOT_ACTIVE": (409, "The referenced school is mothballed and cannot receive students or programs."),
    "ERR_ADOPTION_STATE_INVALID": (409, "The adoption record is not in a state that accepts this operation."),
    "ERR_TRANSFER_NOT_DECIDABLE": (409, "The transfer request has already reached a decided state."),
    "ERR_TRANSFER_WINDOW_CLOSED": (409, "The adoption's transfer window is closed to new requests."),
    "ERR_PROJECTION_STALE": (409, "The scenario's projection run is stale or superseded, so its scores cannot be certified."),
    "ERR_STALE_SCENARIO_VERSION": (412, "expected_scenario_version does not match the scenario's current version."),
    "ERR_STALE_STUDY_VERSION": (412, "expected_study_version does not match the study's current version."),
    "ERR_TRANSFER_WINDOW_EXPIRED": (409, "The adoption's transfer deadline has passed."),
    "ERR_EFFECTIVE_DATE_NOT_REACHED": (409, "The adoption's effective date has not been reached yet."),
    "ERR_INVALID_DATE_WINDOW": (422, "The supplied dates or school years are not in the required order."),
    "ERR_TRAVEL_OPTION_MISSING": (422, "The planning area has no travel option recorded for the assigned school."),
    "ERR_SCHOOL_LEVEL_MISMATCH": (422, "The school's grade level does not match the planning area's grade band."),
    "ERR_CROSS_STUDY_REFERENCE": (422, "The referenced entities belong to different boundary studies."),
    "ERR_SELF_ADJACENCY": (422, "A planning area cannot be declared adjacent to itself."),
    "ERR_PROGRAM_HOST_INCAPABLE": (422, "The named host school cannot host the requested program type."),
    "ERR_SIBLING_LINK_INVALID": (422, "The sibling transfer link is missing or does not point at an approved sibling at the same school."),
    "ERR_RIDE_TIME_EXCEEDED": (422, "The bus ride for this area-school pair exceeds the maximum ride time for the school level."),
    "ERR_DUPLICATE_ADJACENCY": (409, "An adjacency already exists for this pair of planning areas."),
    "ERR_DUPLICATE_NAME": (409, "The supplied name, area code or student reference is already used inside its scope."),
    "ERR_AREA_UNASSIGNED": (409, "The scenario does not assign every planning area of the study exactly once."),
    "ERR_CONTIGUITY_BROKEN": (409, "At least one school's assigned attendance area is not contiguous."),
    "ERR_PROGRAM_HOST_UNASSIGNED": (409, "A program host school has no attendance area assigned in this scenario."),
    "ERR_PROGRAM_PLACEMENT_INCOMPLETE": (409, "A required district program is not placed exactly once in this scenario."),
    "ERR_PHASE_IN_BAND_OVERLAP": (409, "The grade band overlaps an existing phase-in rule of the same type on this adoption."),
    "ERR_REGIME_WINDOW_CONFLICT": (409, "The adoption's boundary regime conflicts with an existing regime or its quiet-period buffer."),
    "ERR_AREA_ABSORPTION_EXCEEDED": (409, "The development would push the area past its rolling housing absorption cap."),
    "ERR_REVISION_LIMIT_EXCEEDED": (409, "The scenario has already used all permitted revision rounds."),
    "ERR_NO_ELIGIBILITY_BASIS": (409, "No grandfathering, sibling, phase-in or hardship basis applies to this transfer request."),
    "ERR_UNADDRESSED_COMMENTS": (409, "Public comments on this scenario are still untriaged."),
    "ERR_SCHOOL_CAPACITY_CRITICAL": (409, "At least one school reaches critical capacity utilization under this scenario."),
    "ERR_NO_TRANSFER_SEATS": (409, "The requested school has no transfer seats available."),
    "ERR_QUORUM_NOT_MET": (409, "The recorded board votes do not meet quorum."),
    "ERR_MAJORITY_NOT_MET": (409, "The recorded board votes do not meet the required approval threshold."),
    "ERR_ZERO_PROJECTION_BASE": (422, "The projected enrollment is zero, so a variance percentage is undefined."),
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        status, default_message = ERRORS[error_id]
        self.error_id = error_id
        self.http_status = status
        self.message = message or default_message


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# --------------------------------------------------------------------------
# Logical clock + in-memory store
# --------------------------------------------------------------------------
class Store:
    """Pure in-memory storage. Starts completely empty on every boot."""

    def __init__(self):
        self.clock = CLOCK_START
        self.seq = 0
        self.studies = {}
        self.schools = {}
        self.areas = {}
        self.adjacencies = {}
        self.developments = {}
        self.runs = {}
        self.scenarios = {}
        self.assignments = {}
        self.comments = {}
        self.adoptions = {}
        self.rules = {}
        self.transfers = {}
        self.observations = {}


db = Store()


def now():
    return db.clock


def iso3(dt):
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_dt(value, error_id="ERR_INVALID_REQUEST"):
    if not isinstance(value, str) or not value.strip():
        fail(error_id, "Expected an ISO 8601 UTC instant.")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        fail(error_id, "Expected an ISO 8601 UTC instant.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def new_record(mutable=True):
    db.seq += 1
    stamp = iso3(db.clock)
    rec = {"id": str(uuid.uuid4()), "created_at": stamp, "_seq": db.seq}
    if mutable:
        rec["updated_at"] = stamp
        rec["version"] = 1
    return rec


def touch(rec):
    """PRD 2.4 - every mutation refreshes updated_at and bumps version by 1."""
    rec["updated_at"] = iso3(db.clock)
    rec["version"] = rec.get("version", 1) + 1


def sort_key(rec):
    # created_at ASC, with insertion order as a deterministic tiebreak because the
    # logical clock does not advance between requests.
    return (rec["created_at"], rec["_seq"])


def ordered(records):
    return sorted(records, key=sort_key)


def pub(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# --------------------------------------------------------------------------
# Response envelope (PRD 2.2)
# --------------------------------------------------------------------------
_ALNUM = string.ascii_uppercase + string.digits


def _meta():
    return {
        "api_request_id": "req_" + "".join(random.choice(_ALNUM) for _ in range(20)),
        "api_request_timestamp": iso3(datetime.now(UTC)),
    }


def respond(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def respond_list(items, limit, offset, total):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(items)) < total
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# --------------------------------------------------------------------------
# Auth (PRD 2.1)
# --------------------------------------------------------------------------
def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if role is None or (isinstance(role, str) and not role.strip()):
        # SCAFFOLD roles.identity_headers also spells this header X-Role.
        alt = request.headers.get("X-Role")
        if alt is not None and alt.strip():
            role = alt
    if not user_id or not user_id.strip() or not role or not role.strip():
        fail("ERR_UNAUTHENTICATED")
    user_id = user_id.strip()
    role = role.strip()
    if role not in ROLES or role not in allowed_roles:
        fail("ERR_UNAUTHORIZED")
    return user_id, role


# --------------------------------------------------------------------------
# Body / query helpers
# --------------------------------------------------------------------------
def body_json():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return data


def present(body, key):
    return key in body and body[key] is not None


def need(body, key):
    if not present(body, key):
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
    return body[key]


def as_int(value, key, minimum=None, maximum=None):
    if isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % key)
    if isinstance(value, float):
        if not value.is_integer():
            fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % key)
        value = int(value)
    if not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be >= %s." % (key, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be <= %s." % (key, maximum))
    return value


def as_num(value, key, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % key)
    dec = Decimal(str(value))
    if minimum is not None and dec < Decimal(str(minimum)):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be >= %s." % (key, minimum))
    if maximum is not None and dec > Decimal(str(maximum)):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be <= %s." % (key, maximum))
    return dec


def as_pct(value, key):
    # PRD 2.6 - percent fields supplied on input must lie within 0 through 1000.
    return as_num(value, key, minimum=0, maximum=1000)


def as_str(value, key, min_len=1, max_len=None):
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % key)
    if len(value) < min_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' is too short." % key)
    if max_len is not None and len(value) > max_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' is too long." % key)
    return value


def as_bool(value, key):
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % key)
    return value


def as_enum(value, key, members):
    if not isinstance(value, str) or value not in members:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be one of %s." % (key, ", ".join(members)))
    return value


def as_id_list(value, key):
    if not isinstance(value, list) or not value:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a non-empty array." % key)
    out = []
    for item in value:
        if not isinstance(item, str) or not item:
            fail("ERR_INVALID_REQUEST", "Field '%s' must contain string ids." % key)
        out.append(item)
    return out


def as_str_array(value, key, members=None):
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an array." % key)
    out = []
    for item in value:
        if not isinstance(item, str):
            fail("ERR_INVALID_REQUEST", "Field '%s' must contain strings." % key)
        if members is not None and item not in members:
            fail("ERR_INVALID_REQUEST", "Field '%s' contains an unknown member." % key)
        out.append(item)
    return out


def pagination():
    args = request.args
    limit = 10
    if args.get("limit") is not None and args.get("limit") != "":
        raw = args.get("limit")
        if not re.fullmatch(r"-?\d+", raw.strip()):
            fail("ERR_INVALID_REQUEST", "limit must be an integer.")
        limit = int(raw)
        if limit < 1 or limit > 200:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 200.")
    offset = 0
    if args.get("offset") is not None and args.get("offset") != "":
        raw = args.get("offset")
        if not re.fullmatch(r"-?\d+", raw.strip()):
            fail("ERR_INVALID_REQUEST", "offset must be an integer.")
        offset = int(raw)
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset may not be negative.")
    effective_limit = min(limit, 100)
    return effective_limit, offset


def bool_filter(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    low = raw.strip().lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    fail("ERR_INVALID_REQUEST", "Filter '%s' must be a boolean." % name)


def paginate(records, serializer):
    limit, offset = pagination()
    total = len(records)
    page = records[offset:offset + limit]
    return respond_list([serializer(r) for r in page], limit, offset, total)


# --------------------------------------------------------------------------
# Rounding (PRD 2.6 - round half up everywhere)
# --------------------------------------------------------------------------
def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value, places):
    quant = Decimal(1).scaleb(-places)
    return dec(value).quantize(quant, rounding=ROUND_HALF_UP)


def money(value):
    return float(round_half_up(value, 2))


def pct2(value):
    return float(round_half_up(value, 2))


def idx4(value):
    return float(round_half_up(value, 4))


def whole(value):
    return int(round_half_up(value, 0))


# --------------------------------------------------------------------------
# Lookups
# --------------------------------------------------------------------------
def get_study(study_id):
    rec = db.studies.get(study_id) if isinstance(study_id, str) else None
    if rec is None:
        fail("ERR_STUDY_NOT_FOUND")
    return rec


def get_school(school_id):
    rec = db.schools.get(school_id) if isinstance(school_id, str) else None
    if rec is None:
        fail("ERR_SCHOOL_NOT_FOUND")
    return rec


def get_area(area_id):
    rec = db.areas.get(area_id) if isinstance(area_id, str) else None
    if rec is None:
        fail("ERR_AREA_NOT_FOUND")
    return rec


def get_development(dev_id):
    rec = db.developments.get(dev_id) if isinstance(dev_id, str) else None
    if rec is None:
        fail("ERR_DEVELOPMENT_NOT_FOUND")
    return rec


def get_run(run_id):
    rec = db.runs.get(run_id) if isinstance(run_id, str) else None
    if rec is None:
        fail("ERR_PROJECTION_RUN_NOT_FOUND")
    return rec


def get_scenario(scenario_id):
    rec = db.scenarios.get(scenario_id) if isinstance(scenario_id, str) else None
    if rec is None:
        fail("ERR_SCENARIO_NOT_FOUND")
    return rec


def get_assignment(assignment_id):
    rec = db.assignments.get(assignment_id) if isinstance(assignment_id, str) else None
    if rec is None:
        fail("ERR_ASSIGNMENT_NOT_FOUND")
    return rec


def get_comment(comment_id):
    rec = db.comments.get(comment_id) if isinstance(comment_id, str) else None
    if rec is None:
        fail("ERR_COMMENT_NOT_FOUND")
    return rec


def get_adoption(adoption_id):
    rec = db.adoptions.get(adoption_id) if isinstance(adoption_id, str) else None
    if rec is None:
        fail("ERR_ADOPTION_NOT_FOUND")
    return rec


def get_transfer(transfer_id):
    rec = db.transfers.get(transfer_id) if isinstance(transfer_id, str) else None
    if rec is None:
        fail("ERR_TRANSFER_NOT_FOUND")
    return rec


def get_observation(observation_id):
    rec = db.observations.get(observation_id) if isinstance(observation_id, str) else None
    if rec is None:
        fail("ERR_OBSERVATION_NOT_FOUND")
    return rec


def schools_of_study(study_id):
    return ordered([s for s in db.schools.values() if s["study_id"] == study_id])


def active_schools_of_study(study_id):
    return [s for s in schools_of_study(study_id) if s["status"] == "ACTIVE"]


def areas_of_study(study_id):
    return ordered([a for a in db.areas.values() if a["study_id"] == study_id])


def developments_of_area(area_id):
    return ordered([d for d in db.developments.values() if d["area_id"] == area_id])


def runs_of_study(study_id):
    return ordered([r for r in db.runs.values() if r["study_id"] == study_id])


def scenarios_of_study(study_id):
    return ordered([s for s in db.scenarios.values() if s["study_id"] == study_id])


def assignments_of_scenario(scenario_id, live_only=False):
    rows = [a for a in db.assignments.values() if a["scenario_id"] == scenario_id]
    if live_only:
        rows = [a for a in rows if not a["is_superseded"]]
    return ordered(rows)


def comments_of_scenario(scenario_id):
    return ordered([c for c in db.comments.values() if c["scenario_id"] == scenario_id])


def rules_of_adoption(adoption_id):
    return ordered([r for r in db.rules.values() if r["adoption_id"] == adoption_id])


def transfers_of_adoption(adoption_id):
    return ordered([t for t in db.transfers.values() if t["adoption_id"] == adoption_id])


def observations_of_adoption(adoption_id):
    return ordered([o for o in db.observations.values() if o["adoption_id"] == adoption_id])


def adjacencies_of_study(study_id):
    rows = []
    for row in db.adjacencies.values():
        area = db.areas.get(row["area_id"])
        if area is not None and area["study_id"] == study_id:
            rows.append(row)
    return ordered(rows)


def live_assignment_for_area(scenario_id, area_id):
    for row in assignments_of_scenario(scenario_id, live_only=True):
        if row["area_id"] == area_id:
            return row
    return None


# --------------------------------------------------------------------------
# Derived-field maintenance
# --------------------------------------------------------------------------
def compute_effective_capacity(school, study):
    seats = school["core_capacity_seats"]
    if study["portables_count_toward_capacity"]:
        seats += school["portable_capacity_seats"]
    return seats


def recompute_school_capacity(school, study=None):
    study = study or db.studies[school["study_id"]]
    value = compute_effective_capacity(school, study)
    if school["effective_capacity_seats"] != value:
        school["effective_capacity_seats"] = value
        return True
    return False


def recompute_school_enrollment(school, changed_only=True):
    total = 0
    for area in areas_of_study(school["study_id"]):
        if area["current_school_id"] == school["id"]:
            total += area["resident_student_count"]
    if school["enrolled_students_of_record"] != total:
        school["enrolled_students_of_record"] = total
        touch(school)
        return True
    return False


def recompute_study_values(study):
    """Recompute resident_student_total, enrolled_of_record_total, projection_stale
    and comment_intake_open in place. Returns True when a stored value changed.
    Does not bump the version - the caller decides how many bumps the operation
    is specified to make."""
    changed = False
    resident_total = sum(a["resident_student_count"] for a in areas_of_study(study["id"]))
    if study["resident_student_total"] != resident_total:
        study["resident_student_total"] = resident_total
        changed = True
    enrolled_total = sum(s["enrolled_students_of_record"] for s in schools_of_study(study["id"]))
    if study["enrolled_of_record_total"] != enrolled_total:
        study["enrolled_of_record_total"] = enrolled_total
        changed = True
    stale = any(r["status"] == "STALE" for r in runs_of_study(study["id"]))
    if study["projection_stale"] != stale:
        study["projection_stale"] = stale
        changed = True
    intake = study["status"] == "ENGAGEMENT"
    if study["comment_intake_open"] != intake:
        study["comment_intake_open"] = intake
        changed = True
    return changed


def recompute_study_rollups(study):
    """Recompute the study roll-ups and bump the version once if anything moved."""
    if recompute_study_values(study):
        touch(study)
        return True
    return False


def set_study_status(study, new_status):
    """Transition the study and refresh comment_intake_open, bumping version once."""
    if study["status"] == new_status:
        return False
    study["status"] = new_status
    study["comment_intake_open"] = new_status == "ENGAGEMENT"
    touch(study)
    return True


def study_serializer(study):
    out = pub(study)
    out["comment_intake_open"] = study["status"] == "ENGAGEMENT"
    return out
