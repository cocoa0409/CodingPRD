"""Ladder rungs 6-9: body parsing, the closed enum iff-list, numeric/format
constraints and pagination bounds.

PRD 2.9 draws the line between the two bad-value codes:
  * structurally wrong (missing, wrong JSON type, out of numeric range,
    malformed state code / email / timestamp)      -> ERR_VALIDATION
  * well-formed but not a declared enum member     -> ERR_INVALID_ENUM

============================  ENUM ROUTING (closed iff-list)  ================
`ERR_INVALID_ENUM` routes EXACTLY the fields registered with an `enum=` (or
`elem_enum=`) below and NO OTHERS.  The complete list, verbatim from PRD 2.9:

  Organization      : org_type, default_methodology
  Person            : housing_type
  Animal            : species, size_class, temperament,
                      each element of restriction_housing_types_excluded
  IntakeRecord      : intake_type, impound_billing_basis
  HoldRecord        : hold_type
  FosterApplication : species_requested
  FosterPlacement   : count_basis
  MedicalRecord     : procedure_type, expense_category
  TransportRun      : run_type, purpose
  TransportLeg      : species_policy
  Adoption          : credit_application_order, refund_basis, deposit_basis
  OutcomeRecord     : outcome_type
  Contribution      : designated_program, restriction_category
  PartnerCommitment : species
  action bodies     : `decision` (foster-application decision AND
                      adoption-application screen), `result` (home-check),
                      `action` (foster-application status-change),
                      `reason` (foster-placement end)
  query             : `methodology` on GET /rescue/reports/live-release-rate

NO OTHER FIELD ROUTES HERE.  The deliberate exclusions, with the codes they
carry instead:
  * every LIST query filter (species, status, lifecycle_status, hold_type,
    intake_type, transport_basis, application_status, home_check_status,
    procedure_type, designated_program, restriction_category, outcome_type,
    run_type, purpose, capacity_status, fee_status, destination_state, ...)
    -- these NEVER error at all.  PRD 2.3: "A filter naming a value that no
    row carries returns an empty array with a `total_count` of zero, not an
    error."  `methodology` on the report is the single query-parameter
    exception because PRD 2.9 names it explicitly.
  * numeric-range failures (amount_cents <= 0, weight_lb <= 0,
    crate_capacity_units < 1, sequence_no < 1, max_headcount < 1,
    slots_total < 1, any negative cents or count)     -> ERR_VALIDATION (r8)
  * format failures (state codes, email, ISO 8601 instants,
    scheduled_arrive_at <= scheduled_depart_at)       -> ERR_VALIDATION (r8)
  * wrong JSON type on an enum field (e.g. species: 7) -> ERR_VALIDATION (r6),
    because rung 6 sits above rung 7
  * a well-formed enum value that names no existing row is not an enum
    question at all: body foreign keys route to the PRD 2.11 not-found map
    (rung 11), e.g. ERR_ANIMAL_NOT_FOUND / ERR_FUNDING_RESOURCE_NOT_FOUND
  * a value that is a declared member but illegal from the current state
    routes to ERR_INVALID_STATE (rung 18), e.g. RESUME on an application that
    was never SUSPENDED
=============================================================================
"""

import re

import clock
from errors import ApiError

ENUM_MEMBERS = {
    "org_type": ["SHELTER", "PARTNER_RESCUE"],
    "methodology": ["SAC", "ASILOMAR"],
    "housing_type": ["APARTMENT", "CONDO", "HOUSE", "FARM"],
    "species": ["DOG", "CAT", "OTHER"],
    "size_class": ["SMALL", "MEDIUM", "LARGE"],
    "temperament": ["SOCIAL", "REACTIVE", "UNKNOWN"],
    "intake_type": ["STRAY", "OWNER_SURRENDER", "CONFISCATE", "TRANSFER_IN", "RETURN"],
    "impound_billing_basis": ["CALENDAR_DAY", "OVERNIGHT"],
    "hold_type": ["MEDICAL", "BEHAVIORAL", "LEGAL"],
    "count_basis": ["INDIVIDUAL", "NURSING_UNIT"],
    "procedure_type": ["EXAM", "VACCINE_RABIES", "SPAY_NEUTER", "TREATMENT"],
    "expense_category": ["MEDICAL", "SPAY_NEUTER", "VACCINE"],
    "run_type": ["RESCUE_LEG", "RELAY"],
    "purpose": ["INTAKE_TRANSPORT", "TRANSFER_OUT"],
    "species_policy": ["DOGS_ONLY", "CATS_ONLY", "MIXED_SEGREGATED", "ANY"],
    "credit_application_order": ["CREDIT_FIRST", "WAIVER_FIRST"],
    "refund_basis": ["FEE_PAID", "FEE_ASSESSED"],
    "deposit_basis": ["FLAT", "AGE_SCALED"],
    "outcome_type": [
        "ADOPTION", "FOSTER_TO_ADOPT", "TRANSFER_OUT", "RETURN_TO_OWNER",
        "EUTHANASIA_MEDICAL", "EUTHANASIA_BEHAVIORAL", "EUTHANASIA_OWNER_REQUESTED",
        "DIED_IN_CARE", "LOST_IN_CARE",
    ],
    "designated_program": ["NONE", "ADOPTION_FEE_ASSISTANCE", "TRANSPORT_FUND", "MEDICAL_FUND"],
    "restriction_category": ["UNRESTRICTED", "MEDICAL", "SPAY_NEUTER", "VACCINE", "TRANSPORT"],
    "decision": ["APPROVE", "DECLINE"],
    "result": ["PASS", "FAIL"],
    "action": ["SUSPEND", "RESUME", "WITHDRAW"],
    # PRD 3.4: only two of the five end_reason members may be supplied by a
    # caller; TRANSFERRED_OUT, ADOPTED and ANIMAL_OUTCOME_CLOSED are written by
    # the system and "are rejected here with ERR_INVALID_ENUM".
    "placement_end_reason": ["RETURNED_TO_SHELTER", "CANCELLED_BEFORE_START"],
}

LIVE_OUTCOME_TYPES = ("ADOPTION", "FOSTER_TO_ADOPT", "TRANSFER_OUT", "RETURN_TO_OWNER")
NON_LIVE_OUTCOME_TYPES = (
    "EUTHANASIA_MEDICAL", "EUTHANASIA_BEHAVIORAL", "EUTHANASIA_OWNER_REQUESTED",
    "DIED_IN_CARE", "LOST_IN_CARE",
)

ROLES = (
    "PlatformAdmin", "IntakeOfficer", "FosterCoordinator", "AdoptionCounselor",
    "TransportDispatcher", "Driver", "Veterinarian", "FinanceOfficer",
    "FosterParent", "Adopter", "PartnerRescue",
)

_STATE_RE = re.compile(r"^[A-Z]{2}$")
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")

_MISSING = object()


class Field(object):
    __slots__ = ("name", "kind", "required", "default", "enum", "elem_enum", "fmt")

    def __init__(self, name, kind, required=False, default=None, enum=None,
                 elem_enum=None, fmt=None):
        self.name = name
        self.kind = kind
        self.required = required
        self.default = default
        self.enum = enum
        self.elem_enum = elem_enum
        self.fmt = fmt


def _bad(msg):
    return ApiError("ERR_VALIDATION", msg)


def _type_ok(kind, value):
    if kind == "string":
        return isinstance(value, str)
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "datetime":
        return isinstance(value, str)
    if kind == "array":
        return isinstance(value, list)
    if kind == "object":
        return isinstance(value, dict)
    return True


def raw_body(request):
    """Rung 6, first clause: "The body parses as JSON"."""
    data = request.get_data(cache=True)
    if not data or not data.strip():
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        raise _bad("Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise _bad("Request body must be a JSON object.")
    return parsed


def parse_body(request, spec):
    """Rungs 6, 7 and 8, evaluated as three ordered passes over the whole body.

    Every field is checked for presence and JSON type before ANY field is
    checked for enum membership, and every enum membership is checked before
    ANY numeric or format constraint.  That ordering is what makes the ladder
    observable rather than implementation-order dependent (PRD 2.5).
    """
    body = raw_body(request)
    present = {}

    # ---- rung 6: required present, declared JSON type ---------------------
    for f in spec:
        value = body.get(f.name, _MISSING)
        if value is _MISSING or value is None:
            if f.required:
                raise _bad("Missing required field '%s'." % f.name)
            present[f.name] = f.default
            continue
        if not _type_ok(f.kind, value):
            raise _bad("Field '%s' has the wrong JSON type." % f.name)
        present[f.name] = value

    supplied = set(k for k in body.keys() if body.get(k) is not None)

    # ---- rung 7: the closed enum iff-list ---------------------------------
    for f in spec:
        if f.name not in supplied:
            continue
        value = present[f.name]
        if f.enum:
            if value not in ENUM_MEMBERS[f.enum]:
                raise ApiError("ERR_INVALID_ENUM",
                               "Field '%s' carries an undeclared enum member." % f.name)
        if f.elem_enum:
            members = ENUM_MEMBERS[f.elem_enum]
            for element in value:
                if not isinstance(element, str) or element not in members:
                    raise ApiError("ERR_INVALID_ENUM",
                                   "Field '%s' contains an undeclared enum member." % f.name)

    # ---- rung 8: numeric and format constraints ---------------------------
    for f in spec:
        if f.name not in supplied:
            continue
        _check_format(f, present[f.name])

    present["_supplied"] = supplied
    return present


def _check_format(f, value):
    fmt = f.fmt
    if f.kind == "datetime":
        try:
            clock.parse(value)
        except clock.BadInstant:
            raise _bad("Field '%s' is not an ISO 8601 UTC instant." % f.name)
        return
    if fmt is None:
        return
    if fmt == "gte0" and value < 0:
        raise _bad("Field '%s' must be at least 0." % f.name)
    if fmt == "gt0" and not value > 0:
        raise _bad("Field '%s' must be strictly greater than 0." % f.name)
    if fmt == "gte1" and value < 1:
        raise _bad("Field '%s' must be at least 1." % f.name)
    if fmt == "state" and not _STATE_RE.match(value):
        raise _bad("Field '%s' must be exactly two uppercase letters." % f.name)
    if fmt == "email" and "@" not in value:
        raise _bad("Field '%s' must contain an at-sign." % f.name)


def check_pagination(args):
    """Rung 9 (PRD 2.3): limit in [1, 100], offset >= 0."""
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise _bad("limit must be an integer.")
        if limit < 1 or limit > 100:
            raise _bad("limit must be between 1 and 100 inclusive.")
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise _bad("offset must be an integer.")
        if offset < 0:
            raise _bad("offset must be at least 0.")
    return limit, offset


def parse_date(raw, field):
    """Report window dates: an inclusive YYYY-MM-DD calendar date."""
    if not isinstance(raw, str) or not _DATE_RE.match(raw.strip()):
        raise _bad("Query parameter '%s' must be an ISO 8601 calendar date." % field)
    return raw.strip()
