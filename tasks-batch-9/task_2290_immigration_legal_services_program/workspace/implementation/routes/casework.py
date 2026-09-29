"""Evidence items, declarations and interpretation sessions (PRD 3.7)."""

from flask import Blueprint, request

import auth
import calc
import response
import serialize
import store
import validation as v
from errors import ApiError

bp = Blueprint("casework", __name__)

STAFFED = ("STAFFED", "SUPERVISED_STAFFED")
REJECT_REASONS = ("ILLEGIBLE", "UNTRANSLATED", "INCONSISTENT_WITH_DECLARATION",
                  "UNOBTAINABLE_COUNTRY_CONDITIONS", "CLIENT_SAFETY_RISK", "DUPLICATE")
WAIVE_REASONS = ("UNOBTAINABLE_COUNTRY_CONDITIONS", "CLIENT_SAFETY_RISK")
REVISION_REASONS = ("FACTUAL_GAP", "LANGUAGE_MISMATCH", "MISSING_READBACK",
                    "EVIDENCE_INCONSISTENCY", "SUPERVISION_REQUIRED")
CLOSURE_REASONS = ("CLIENT_UNAVAILABLE", "INTERPRETER_UNAVAILABLE",
                   "FACILITY_DENIED_ACCESS", "HEARING_CONTINUED", "LANGUAGE_MISMATCH")
BOOL_FILTERS = {"true": True, "false": False}


def _matter_or_404(matter_id):
    matter = store.get("matters", matter_id)
    if matter is None:
        raise ApiError("ERR_MATTER_NOT_FOUND")
    return matter


def _not_closed(matter):
    if matter.get("representation_status") == "WITHDRAWN_FROM":
        raise ApiError("ERR_MATTER_CLOSED", "The matter is closed.")


def _bool_filter(rows, args, key):
    value = args.get(key)
    if value is None or value == "":
        return rows
    wanted = BOOL_FILTERS.get(str(value).lower())
    if wanted is None:
        v.bad("%s must be true or false." % key)
    return [r for r in rows if bool(r.get(key)) is wanted]


def _refresh_readiness(matter):
    calc.recompute_matter_readiness(matter, bump=False)
    store.touch(matter)


# --------------------------------------------------------------------------
# evidence items
# --------------------------------------------------------------------------

@bp.post("/evidence-items")
@auth.requires("CaseRepresentative", "SupervisingAttorney", "ProgramDirector",
               scoped=True)
def create_evidence():
    payload = v.body()
    matter_id = v.as_id(payload, "matter_id")
    auth.scope_matter(matter_id)
    matter = _matter_or_404(matter_id)
    item_type = v.as_enum(payload, "item_type", calc.EVIDENCE_ITEM_TYPES)
    tier = v.as_enum(payload, "tier", ("REQUIRED", "SUPPORTING", "OPTIONAL"))
    weight = v.as_int(payload, "weight_points", minimum=1, maximum=10)
    language = v.language_code(payload, "source_language_code", required=False,
                              default=None)
    if v.present(payload, "requires_translation"):
        v.as_bool(payload, "requires_translation")
    due_date = v.as_date(payload, "due_date", required=False, default=None)
    _not_closed(matter)
    row = store.new_row({
        "matter_id": matter_id,
        "item_type": item_type,
        "tier": tier,
        "weight_points": weight,
        "source_language_code": language,
        "requires_translation": language is not None and language != "en",
        "status": "REQUESTED",
        "due_date": due_date.isoformat() if due_date else None,
        "received_at_utc": None,
        "verified_at_utc": None,
        "rejection_round": 0,
        "disposition_reason_code": None,
    })
    store.insert("evidence", row)
    _refresh_readiness(matter)
    return response.created(serialize.evidence(row))


@bp.get("/evidence-items")
@auth.requires("ProgramDirector", "SupervisingAttorney", "CaseRepresentative",
               "GrantAnalyst")
def list_evidence():
    rows = store.rows("evidence")
    args = request.args
    for key in ("matter_id", "tier", "status"):
        if args.get(key):
            rows = [r for r in rows if r.get(key) == args[key]]
    rows = _bool_filter(rows, args, "requires_translation")
    page, meta = store.paginate(rows, args)
    return response.collection([serialize.evidence(r) for r in page], meta)


@bp.post("/evidence-items/<item_id>/transition")
@auth.requires("CaseRepresentative", "SupervisingAttorney", "ProgramDirector",
               scoped=True)
def transition_evidence(item_id):
    row = store.get("evidence", item_id)
    auth.scope_matter(row.get("matter_id") if row else None)
    if row is None:
        raise ApiError("ERR_NOT_FOUND", "The evidence item does not exist.")
    payload = v.body()
    action = v.as_enum(payload, "action", ("RECEIVE", "TRANSLATE", "VERIFY", "REJECT",
                                          "REREQUEST", "WAIVE"))
    matter = _matter_or_404(row["matter_id"])
    status = row["status"]
    translation = bool(row.get("requires_translation"))

    if action == "RECEIVE":
        if status != "REQUESTED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "RECEIVE is only legal from REQUESTED.")
        if matter.get("representation_status") not in STAFFED:
            raise ApiError("ERR_LEAD_NOT_ASSIGNED",
                           "An unstaffed matter cannot take custody of documents.")
        row["status"] = "RECEIVED"
        row["received_at_utc"] = store.clock_iso()
    elif action == "TRANSLATE":
        if status != "RECEIVED" or not translation:
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "TRANSLATE is only legal from RECEIVED when translation "
                           "is required.")
        row["status"] = "TRANSLATED"
    elif action == "VERIFY":
        if status == "RECEIVED" and translation:
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "A foreign-language item must be TRANSLATED first.")
        if status not in ("RECEIVED", "TRANSLATED"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "VERIFY is only legal from RECEIVED or TRANSLATED.")
        row["status"] = "VERIFIED"
        row["verified_at_utc"] = store.clock_iso()
    elif action == "REJECT":
        if status not in ("RECEIVED", "TRANSLATED"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "REJECT is only legal from RECEIVED or TRANSLATED.")
        reason = v.as_enum(payload, "disposition_reason_code", REJECT_REASONS)
        row["status"] = "REJECTED"
        row["rejection_round"] = int(row.get("rejection_round") or 0) + 1
        row["disposition_reason_code"] = reason
    elif action == "REREQUEST":
        if status != "REJECTED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "REREQUEST is only legal from REJECTED.")
        new_due = v.as_date(payload, "new_due_date")
        if new_due < store.clock_date():
            v.bad("new_due_date must be at or after the current logical date.")
        row["status"] = "REQUESTED"
        row["due_date"] = new_due.isoformat()
        row["received_at_utc"] = None
        row["disposition_reason_code"] = None
    else:
        if status not in ("REQUESTED", "RECEIVED", "TRANSLATED", "REJECTED"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "WAIVE is not legal from %s." % status)
        reason = v.as_enum(payload, "disposition_reason_code", WAIVE_REASONS)
        row["status"] = "WAIVED"
        row["disposition_reason_code"] = reason
    store.touch(row)
    _refresh_readiness(matter)
    return response.ok(serialize.evidence(row))


# --------------------------------------------------------------------------
# declarations
# --------------------------------------------------------------------------

def _preparer_rep_id(row):
    assignment = store.get("assignments", row.get("preparer_assignment_id"))
    return assignment.get("representative_id") if assignment else None


def _require_preparer(row):
    if not auth.is_rep_backed():
        return
    if auth.user_id() != _preparer_rep_id(row):
        raise ApiError("ERR_ACTOR_NOT_ON_CASE",
                       "Only the preparer's representative may perform this action.")


def _matter_sessions(matter_id):
    return sorted(
        [s for s in store.db["sessions"].values() if s.get("matter_id") == matter_id],
        key=store.order_key,
    )


def _readback_session(matter_id, language_code):
    best = None
    for session in _matter_sessions(matter_id):
        if session.get("status") != "COMPLETED":
            continue
        if session.get("purpose") != "DECLARATION_READBACK":
            continue
        if session.get("language_code") != language_code:
            continue
        if best is None:
            best = session
            continue
        current = store.parse_dt(session.get("scheduled_start_utc"))
        chosen = store.parse_dt(best.get("scheduled_start_utc"))
        if current is not None and chosen is not None and current > chosen:
            best = session
    return best


@bp.post("/declarations")
@auth.requires("CaseRepresentative", "SupervisingAttorney", "ProgramDirector",
               scoped=True)
def create_declaration():
    payload = v.body()
    matter_id = v.as_id(payload, "matter_id")
    preparer_id = v.as_id(payload, "preparer_assignment_id")
    auth.scope_matter(matter_id)
    matter = _matter_or_404(matter_id)
    preparer = store.get("assignments", preparer_id)
    if preparer is None:
        raise ApiError("ERR_NOT_FOUND", "The preparer assignment does not exist.")
    language = v.language_code(payload, "language_code")
    word_count = v.as_int(payload, "word_count", required=False, minimum=1, default=None)
    _not_closed(matter)
    if preparer.get("matter_id") != matter_id:
        raise ApiError("ERR_ASSIGNMENT_MATTER_MISMATCH",
                       "The preparer assignment belongs to a different matter.")
    if preparer.get("status") != "ACTIVE":
        raise ApiError("ERR_ASSIGNMENT_NOT_ACTIVE",
                       "The preparer assignment is not ACTIVE.")
    row = store.new_row({
        "matter_id": matter_id,
        "preparer_assignment_id": preparer_id,
        "reviewer_assignment_id": None,
        "readback_session_id": None,
        "language_code": language,
        "word_count": word_count,
        "status": "DRAFT",
        "revision_round": 0,
        "readback_completed": False,
        "revision_reason_code": None,
        "certified_at_utc": None,
    })
    store.insert("declarations", row)
    return response.created(serialize.declaration(row))


@bp.get("/declarations")
@auth.requires("ProgramDirector", "SupervisingAttorney", "CaseRepresentative")
def list_declarations():
    rows = store.rows("declarations")
    args = request.args
    for key in ("matter_id", "preparer_assignment_id", "reviewer_assignment_id",
                "readback_session_id", "status", "language_code"):
        if args.get(key):
            rows = [r for r in rows if r.get(key) == args[key]]
    page, meta = store.paginate(rows, args)
    return response.collection([serialize.declaration(r) for r in page], meta)


@bp.post("/declarations/<declaration_id>/transition")
@auth.requires("CaseRepresentative", "SupervisingAttorney", "ProgramDirector",
               scoped=True)
def transition_declaration(declaration_id):
    row = store.get("declarations", declaration_id)
    auth.scope_matter(row.get("matter_id") if row else None)
    if row is None:
        raise ApiError("ERR_NOT_FOUND", "The declaration does not exist.")
    payload = v.body()
    action = v.as_enum(payload, "action", ("SUBMIT_FOR_REVIEW", "REQUEST_REVISION",
                                          "RESUME_DRAFT", "CERTIFY", "WITHDRAW"))
    matter = _matter_or_404(row["matter_id"])
    client = store.get("clients", matter.get("client_id"))
    status = row["status"]

    if action == "SUBMIT_FOR_REVIEW":
        if status != "DRAFT":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "SUBMIT_FOR_REVIEW is only legal from DRAFT.")
        _require_preparer(row)
        preparer = store.get("assignments", row.get("preparer_assignment_id"))
        if preparer is None or preparer.get("status") != "ACTIVE":
            raise ApiError("ERR_ASSIGNMENT_NOT_ACTIVE",
                           "The preparer assignment is not ACTIVE.")
        preferred = client.get("preferred_language_code") if client else None
        session = _readback_session(row["matter_id"], preferred)
        if row.get("language_code") != preferred and session is None:
            raise ApiError("ERR_READBACK_NOT_COMPLETED",
                           "A completed read-back session in the client's language "
                           "is required.")
        if session is not None:
            row["readback_session_id"] = session["id"]
            row["readback_completed"] = True
        row["status"] = "IN_REVIEW"
    elif action == "REQUEST_REVISION":
        if status != "IN_REVIEW":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "REQUEST_REVISION is only legal from IN_REVIEW.")
        reason = v.as_enum(payload, "revision_reason_code", REVISION_REASONS,
                           required=auth.role() == "SupervisingAttorney")
        row["status"] = "REVISION_REQUESTED"
        row["revision_round"] = int(row.get("revision_round") or 0) + 1
        row["revision_reason_code"] = reason
    elif action == "RESUME_DRAFT":
        if status != "REVISION_REQUESTED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "RESUME_DRAFT is only legal from REVISION_REQUESTED.")
        _require_preparer(row)
        row["word_count"] = v.as_int(payload, "word_count", minimum=1)
        row["revision_reason_code"] = None
        row["status"] = "DRAFT"
    elif action == "CERTIFY":
        if status != "IN_REVIEW":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "CERTIFY is only legal from IN_REVIEW.")
        reviewer_id = v.as_id(payload, "reviewer_assignment_id")
        reviewer = store.get("assignments", reviewer_id)
        if reviewer is None:
            raise ApiError("ERR_NOT_FOUND", "The reviewer assignment does not exist.")
        if reviewer.get("matter_id") != row["matter_id"]:
            raise ApiError("ERR_ASSIGNMENT_MATTER_MISMATCH",
                           "The reviewer assignment belongs to a different matter.")
        if reviewer.get("status") != "ACTIVE":
            raise ApiError("ERR_ASSIGNMENT_NOT_ACTIVE",
                           "The reviewer assignment is not ACTIVE.")
        for item in calc.matter_evidence(row["matter_id"]):
            if (item.get("status") == "REJECTED"
                    and item.get("disposition_reason_code")
                    == "INCONSISTENT_WITH_DECLARATION"):
                raise ApiError("ERR_BLOCKING_EVIDENCE_OUTSTANDING",
                               "An evidence item is rejected as inconsistent with "
                               "the declaration.")
        reviewer_rep = store.get("representatives", reviewer.get("representative_id"))
        if (reviewer_rep is None
                or reviewer_rep["id"] == _preparer_rep_id(row)
                or reviewer_rep.get("rep_type") != "STAFF_ATTORNEY"
                or calc.authorization_status(reviewer_rep) != "AUTHORIZED_ATTORNEY"):
            raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                           "The certifier must be a different authorized attorney.")
        if client is not None and client.get("interpreter_required") \
                and not row.get("readback_completed"):
            raise ApiError("ERR_READBACK_NOT_COMPLETED",
                           "The declaration has not been read back to the client.")
        row["reviewer_assignment_id"] = reviewer_id
        row["certified_at_utc"] = store.clock_iso()
        row["status"] = "CERTIFIED"
    else:
        if status not in ("DRAFT", "IN_REVIEW", "REVISION_REQUESTED"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "WITHDRAW is not legal from %s." % status)
        row["readback_session_id"] = None
        row["readback_completed"] = False
        row["status"] = "WITHDRAWN"
    store.touch(row)
    if action == "CERTIFY":
        store.touch(matter)
    return response.ok(serialize.declaration(row))


# --------------------------------------------------------------------------
# interpretation sessions
# --------------------------------------------------------------------------

NAMED_SOURCES = ("STAFF", "VOLUNTEER")
ANONYMOUS_SOURCES = ("CONTRACT", "TELEPHONIC")


@bp.post("/interpretation-sessions")
@auth.requires("CaseRepresentative", "SupervisingAttorney", "ProgramDirector",
               scoped=True)
def create_session():
    payload = v.body()
    matter_id = v.as_id(payload, "matter_id")
    interpreter_id = v.as_id(payload, "interpreter_representative_id", required=False,
                            default=None)
    auth.scope_matter(matter_id)
    matter = _matter_or_404(matter_id)
    interpreter = None
    if interpreter_id is not None:
        interpreter = store.get("representatives", interpreter_id)
        if interpreter is None:
            raise ApiError("ERR_REPRESENTATIVE_NOT_FOUND")
    language = v.language_code(payload, "language_code")
    source = v.as_enum(payload, "interpreter_source", calc.INTERPRETER_SOURCES)
    purpose = v.as_enum(payload, "purpose", calc.INTERPRETATION_PURPOSES)
    start = v.as_datetime(payload, "scheduled_start_utc")
    end = v.as_datetime(payload, "scheduled_end_utc")
    if end <= start:
        v.bad("scheduled_end_utc must be strictly after scheduled_start_utc.")
    _not_closed(matter)
    if source in NAMED_SOURCES and interpreter_id is None:
        raise ApiError("ERR_INTERPRETER_SOURCE_MISMATCH",
                       "A %s session requires interpreter_representative_id." % source)
    if source in ANONYMOUS_SOURCES and interpreter_id is not None:
        raise ApiError("ERR_INTERPRETER_SOURCE_MISMATCH",
                       "A %s session must not name an interpreter." % source)
    if interpreter is not None and language not in (interpreter.get("languages") or []):
        raise ApiError("ERR_INTERPRETER_LANGUAGE_MISMATCH",
                       "The named interpreter does not speak %s." % language)
    row = store.new_row({
        "matter_id": matter_id,
        "interpreter_representative_id": interpreter_id,
        "language_code": language,
        "interpreter_source": source,
        "purpose": purpose,
        "scheduled_start_utc": store.iso(start),
        "scheduled_end_utc": store.iso(end),
        "actual_minutes": None,
        "billed_minutes": 0,
        "billable_cents": 0,
        "status": "SCHEDULED",
        "closure_reason_code": None,
    })
    store.insert("sessions", row)
    return response.created(serialize.session(row))


@bp.get("/interpretation-sessions")
@auth.requires("ProgramDirector", "SupervisingAttorney", "CaseRepresentative",
               "GrantAnalyst")
def list_sessions():
    rows = store.rows("sessions")
    args = request.args
    for key in ("matter_id", "interpreter_representative_id", "status", "purpose",
                "language_code"):
        if args.get(key):
            rows = [r for r in rows if r.get(key) == args[key]]
    page, meta = store.paginate(rows, args)
    return response.collection([serialize.session(r) for r in page], meta)


@bp.post("/interpretation-sessions/<session_id>/transition")
@auth.requires("CaseRepresentative", "SupervisingAttorney", "ProgramDirector",
               scoped=True)
def transition_session(session_id):
    row = store.get("sessions", session_id)
    auth.scope_matter(row.get("matter_id") if row else None)
    if row is None:
        raise ApiError("ERR_NOT_FOUND", "The interpretation session does not exist.")
    payload = v.body()
    action = v.as_enum(payload, "action", ("COMPLETE", "MARK_NO_SHOW", "CANCEL"))
    matter = _matter_or_404(row["matter_id"])
    if row["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "%s is only legal from SCHEDULED." % action)
    now = store.clock_dt()
    start = store.parse_dt(row.get("scheduled_start_utc"))
    end = store.parse_dt(row.get("scheduled_end_utc"))

    if action == "COMPLETE":
        minutes = v.as_int(payload, "actual_minutes", minimum=1)
        if start is not None and now < start:
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "The session window has not started yet.")
        billed, cents = calc.session_billing(row["interpreter_source"],
                                             row["language_code"], minutes)
        row["actual_minutes"] = minutes
        row["billed_minutes"] = billed
        row["billable_cents"] = cents
        row["status"] = "COMPLETED"
        store.touch(row)
        if row["purpose"] == "DECLARATION_READBACK":
            for declaration in sorted(store.db["declarations"].values(),
                                      key=store.order_key):
                if declaration.get("matter_id") != row["matter_id"]:
                    continue
                if declaration.get("status") != "IN_REVIEW":
                    continue
                if declaration.get("language_code") != row["language_code"]:
                    continue
                declaration["readback_session_id"] = row["id"]
                declaration["readback_completed"] = True
                store.touch(declaration)
        calc.recompute_matter_interpretation_cost(matter, bump=False)
        store.touch(matter)
        return response.ok(serialize.session(row))

    reason = v.as_enum(payload, "closure_reason_code", CLOSURE_REASONS)
    if action == "MARK_NO_SHOW":
        if end is not None and now < end:
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "A no-show may only be marked once the window has ended.")
        row["status"] = "NO_SHOW"
    else:
        if start is not None and now >= start:
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "A session may only be cancelled before it starts.")
        row["status"] = "CANCELLED"
    row["closure_reason_code"] = reason
    store.touch(row)
    if action == "CANCEL":
        for declaration in sorted(store.db["declarations"].values(),
                                  key=store.order_key):
            if declaration.get("readback_session_id") != row["id"]:
                continue
            declaration["readback_session_id"] = None
            declaration["readback_completed"] = False
            store.touch(declaration)
    return response.ok(serialize.session(row))
