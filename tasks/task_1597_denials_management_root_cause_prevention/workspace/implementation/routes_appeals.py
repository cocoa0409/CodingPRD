"""Routes: appeals (create, letter, revise, submit, outcome, reverse, withdraw)
and appeal attachments (create, void)."""

from datetime import timedelta

from flask import Blueprint, g, request

from auth import require_roles
from cascades import apply_record_outcome, apply_reverse_outcome, apply_withdraw
from db import store
from envelope import list_response, ok
from errors import (
    ApiError,
    ERR_APPEAL_ALREADY_ACTIVE,
    ERR_APPEAL_INVALID_STATE,
    ERR_APPEAL_LEVEL_EXHAUSTED,
    ERR_ATTACHMENT_REQUIREMENT_UNMET,
    ERR_CODE_NOT_APPEALABLE,
    ERR_DENIAL_INVALID_STATE,
    ERR_INVALID_STATE,
    ERR_OUTCOME_AMOUNT_INCONSISTENT,
    ERR_TIMELY_FILING_EXPIRED,
)
from services import (
    ACTIVE_APPEAL_STATES,
    DEFAULT_RESPONSE_WINDOW_DAYS,
    MAX_APPEAL_LEVEL,
    compose_letter,
    effective_policy,
    emit_event,
    find_appeal,
    find_attachment,
    find_denial,
    make_record,
    public,
    recompute_priority,
    touch,
)
from util import (
    ALL_ROLES,
    ATTACHMENT_TYPES,
    OUTCOMES,
    get_body,
    now_iso,
    opt_str,
    parse_date,
    req_enum,
    req_int,
    req_str,
    sort_created,
    today,
)

bp = Blueprint("appeals", __name__)

SPECIALIST = ("DenialsSpecialist",)


# ---------------------------------------------------------------------------
# Appeal creation
# ---------------------------------------------------------------------------


@bp.post("/rcm/appeals")
@require_roles(*SPECIALIST)
def create_appeal():
    body = get_body()
    denial_id = req_str(body, "denial_case_id")
    denial = find_denial(denial_id)
    if denial["status"] not in ("QUEUED", "IN_APPEAL"):
        raise ApiError(
            ERR_DENIAL_INVALID_STATE,
            409,
            "Appeals can only be opened for QUEUED or IN_APPEAL denials",
        )
    code = store.remittance_codes[denial["remittance_code_id"]]
    if not code["appealable"]:
        raise ApiError(
            ERR_CODE_NOT_APPEALABLE,
            422,
            "Remittance code %s is not appealable" % code["code"],
        )
    active = [
        a
        for a in store.appeals.values()
        if a["denial_case_id"] == denial_id and a["status"] in ACTIVE_APPEAL_STATES
    ]
    if active:
        raise ApiError(
            ERR_APPEAL_ALREADY_ACTIVE,
            409,
            "Denial already has an appeal in DRAFT, LETTER_GENERATED, or SUBMITTED",
        )
    next_level = denial["current_appeal_level"] + 1
    if next_level > MAX_APPEAL_LEVEL:
        raise ApiError(
            ERR_APPEAL_LEVEL_EXHAUSTED,
            422,
            "Maximum appeal level %d reached" % MAX_APPEAL_LEVEL,
        )
    if next_level >= 2 and effective_policy(denial["payer_id"], next_level, today()) is None:
        raise ApiError(
            ERR_APPEAL_LEVEL_EXHAUSTED,
            422,
            "No effective policy covers level %d for this payer" % next_level,
        )
    previous = None
    if next_level > 1:
        candidates = [
            a
            for a in store.appeals.values()
            if a["denial_case_id"] == denial_id
            and a["level_number"] == next_level - 1
            and a["status"] != "WITHDRAWN"
        ]
        if candidates:
            candidates.sort(key=lambda a: (a["created_at"], a["_seq"]))
            previous = candidates[-1]["id"]

    appeal = make_record(
        {
            "denial_case_id": denial_id,
            "previous_appeal_id": previous,
            "level_number": next_level,
            "status": "DRAFT",
            "letter_body": None,
            "generated_at": None,
            "submitted_at": None,
            "response_due_date": None,
            "outcome_recorded_at": None,
            "outcome_amount_cents": 0,
            "payer_response_code": "",
            "reversal_reason": "",
        }
    )
    store.appeals[appeal["id"]] = appeal

    denial["status"] = "IN_APPEAL"
    denial["current_appeal_level"] = next_level
    recompute_priority(denial)
    touch(denial)
    emit_event(
        denial_id,
        "APPEAL_CREATED",
        g.user_role,
        g.user_id,
        "appeal_id=%s;level_number=%d" % (appeal["id"], next_level),
    )
    return ok(public(appeal), "object", 201)


@bp.get("/rcm/appeals")
@require_roles(*ALL_ROLES)
def list_appeals():
    items = list(store.appeals.values())
    denial_id = request.args.get("denial_case_id")
    if denial_id is not None:
        items = [a for a in items if a["denial_case_id"] == denial_id]
    prev = request.args.get("previous_appeal_id")
    if prev is not None:
        items = [a for a in items if a["previous_appeal_id"] == prev]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    level_s = request.args.get("level_number")
    if level_s is not None:
        try:
            level = int(level_s)
        except ValueError:
            items = []
        else:
            items = [a for a in items if a["level_number"] == level]
    return list_response([public(a) for a in sort_created(items)])


@bp.get("/rcm/appeals/<aid>")
@require_roles(*ALL_ROLES)
def get_appeal(aid):
    return ok(public(find_appeal(aid)))


# ---------------------------------------------------------------------------
# Letter generation and revision
# ---------------------------------------------------------------------------


@bp.post("/rcm/appeals/<aid>/generate-letter")
@require_roles(*SPECIALIST)
def generate_letter(aid):
    appeal = find_appeal(aid)
    if appeal["status"] != "DRAFT":
        raise ApiError(
            ERR_APPEAL_INVALID_STATE, 409, "Letter generation requires DRAFT status"
        )
    denial = store.denials[appeal["denial_case_id"]]
    appeal["letter_body"] = compose_letter(denial, appeal)
    appeal["generated_at"] = now_iso()
    appeal["status"] = "LETTER_GENERATED"
    touch(appeal)
    emit_event(
        denial["id"],
        "LETTER_GENERATED",
        g.user_role,
        g.user_id,
        "appeal_id=%s;level_number=%d" % (appeal["id"], appeal["level_number"]),
    )
    return ok(public(appeal))


@bp.post("/rcm/appeals/<aid>/revise")
@require_roles(*SPECIALIST)
def revise_appeal(aid):
    appeal = find_appeal(aid)
    if appeal["status"] != "LETTER_GENERATED":
        raise ApiError(
            ERR_APPEAL_INVALID_STATE,
            409,
            "Revise requires LETTER_GENERATED status",
        )
    appeal["letter_body"] = None
    appeal["generated_at"] = None
    appeal["status"] = "DRAFT"
    touch(appeal)
    return ok(public(appeal))


# ---------------------------------------------------------------------------
# Submission
# ---------------------------------------------------------------------------


@bp.post("/rcm/appeals/<aid>/submit")
@require_roles(*SPECIALIST)
def submit_appeal(aid):
    appeal = find_appeal(aid)
    if appeal["status"] != "LETTER_GENERATED":
        raise ApiError(
            ERR_APPEAL_INVALID_STATE,
            409,
            "Submit requires LETTER_GENERATED status",
        )
    denial = store.denials[appeal["denial_case_id"]]
    today_d = today()
    deadline = denial.get("next_appeal_deadline")
    if deadline is None or today_d > parse_date(deadline):
        raise ApiError(
            ERR_TIMELY_FILING_EXPIRED,
            422,
            "Submission date is after the denial's next_appeal_deadline",
        )
    policy = effective_policy(denial["payer_id"], appeal["level_number"], today_d)
    required = policy["required_attachment_types"] if policy else []
    active_types = {
        a["document_type"]
        for a in store.attachments.values()
        if a["appeal_id"] == aid and a["status"] == "ACTIVE"
    }
    if not set(required).issubset(active_types):
        raise ApiError(
            ERR_ATTACHMENT_REQUIREMENT_UNMET,
            422,
            "Required attachment types %s are not all ACTIVE on this appeal"
            % sorted(set(required) - active_types),
        )
    window = policy["response_window_days"] if policy else DEFAULT_RESPONSE_WINDOW_DAYS
    appeal["submitted_at"] = now_iso()
    appeal["response_due_date"] = (today_d + timedelta(days=window)).isoformat()
    appeal["status"] = "SUBMITTED"
    touch(appeal)
    touch(denial)  # parent denial version increments on submission
    emit_event(
        denial["id"],
        "APPEAL_SUBMITTED",
        g.user_role,
        g.user_id,
        "appeal_id=%s;submitted_at=%s;response_due_date=%s"
        % (aid, appeal["submitted_at"], appeal["response_due_date"]),
    )
    return ok(public(appeal))


# ---------------------------------------------------------------------------
# Outcome recording / reversal / withdrawal
# ---------------------------------------------------------------------------


@bp.post("/rcm/appeals/<aid>/record-outcome")
@require_roles(*SPECIALIST)
def record_outcome(aid):
    body = get_body()
    outcome = req_enum(body, "outcome", OUTCOMES)
    amount = req_int(body, "recovered_amount_cents")
    response_code = opt_str(body, "payer_response_code", "")
    appeal = find_appeal(aid)
    if appeal["status"] != "SUBMITTED":
        raise ApiError(
            ERR_APPEAL_INVALID_STATE, 409, "Outcome recording requires SUBMITTED status"
        )
    denial = store.denials[appeal["denial_case_id"]]
    open_balance = denial["open_balance_cents"]
    if outcome == "OVERTURNED" and amount != open_balance:
        raise ApiError(
            ERR_OUTCOME_AMOUNT_INCONSISTENT,
            422,
            "OVERTURNED requires recovered_amount_cents == open_balance_cents (%d)"
            % open_balance,
        )
    if outcome == "PARTIALLY_OVERTURNED" and not (0 < amount < open_balance):
        raise ApiError(
            ERR_OUTCOME_AMOUNT_INCONSISTENT,
            422,
            "PARTIALLY_OVERTURNED requires 0 < recovered_amount_cents < "
            "open_balance_cents (%d)" % open_balance,
        )
    if outcome == "UPHELD" and amount != 0:
        raise ApiError(
            ERR_OUTCOME_AMOUNT_INCONSISTENT,
            422,
            "UPHELD requires recovered_amount_cents == 0",
        )
    appeal["payer_response_code"] = response_code
    apply_record_outcome(appeal, denial, outcome, amount, g.user_role, g.user_id)
    return ok(public(appeal))


@bp.post("/rcm/appeals/<aid>/reverse-outcome")
@require_roles("ComplianceAuditor")
def reverse_outcome(aid):
    body = get_body()
    reason = req_str(body, "reason")
    appeal = find_appeal(aid)
    if appeal["status"] not in ("OVERTURNED", "PARTIALLY_OVERTURNED", "UPHELD"):
        raise ApiError(
            ERR_APPEAL_INVALID_STATE,
            409,
            "Reverse-outcome requires an outcome state",
        )
    denial = store.denials[appeal["denial_case_id"]]
    apply_reverse_outcome(appeal, denial, reason, g.user_role, g.user_id)
    return ok(public(appeal))


@bp.post("/rcm/appeals/<aid>/withdraw")
@require_roles(*SPECIALIST)
def withdraw_appeal(aid):
    appeal = find_appeal(aid)
    if appeal["status"] not in ("DRAFT", "LETTER_GENERATED"):
        raise ApiError(
            ERR_APPEAL_INVALID_STATE,
            409,
            "Withdrawal requires DRAFT or LETTER_GENERATED status",
        )
    denial = store.denials[appeal["denial_case_id"]]
    apply_withdraw(appeal, denial, g.user_role, g.user_id)
    return ok(public(appeal))


# ---------------------------------------------------------------------------
# Appeal attachments
# ---------------------------------------------------------------------------


@bp.post("/rcm/appeal-attachments")
@require_roles(*SPECIALIST)
def create_attachment():
    body = get_body()
    appeal_id = req_str(body, "appeal_id")
    document_type = req_enum(body, "document_type", ATTACHMENT_TYPES)
    file_reference = req_str(body, "file_reference")
    appeal = find_appeal(appeal_id)
    if appeal["status"] not in ("DRAFT", "LETTER_GENERATED"):
        raise ApiError(
            ERR_APPEAL_INVALID_STATE,
            409,
            "Attachments require the appeal to be DRAFT or LETTER_GENERATED",
        )
    att = make_record(
        {
            "appeal_id": appeal_id,
            "document_type": document_type,
            "file_reference": file_reference,
            "status": "ACTIVE",
            "voided_reason": "",
        }
    )
    store.attachments[att["id"]] = att
    return ok(public(att), "object", 201)


@bp.get("/rcm/appeal-attachments")
@require_roles(*ALL_ROLES)
def list_attachments():
    items = list(store.attachments.values())
    appeal_id = request.args.get("appeal_id")
    if appeal_id is not None:
        items = [a for a in items if a["appeal_id"] == appeal_id]
    doc = request.args.get("document_type")
    if doc is not None:
        items = [a for a in items if a["document_type"] == doc]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return list_response([public(a) for a in sort_created(items)])


@bp.get("/rcm/appeal-attachments/<aid>")
@require_roles(*ALL_ROLES)
def get_attachment(aid):
    return ok(public(find_attachment(aid)))


@bp.post("/rcm/appeal-attachments/<aid>/void")
@require_roles(*SPECIALIST)
def void_attachment(aid):
    body = get_body()
    reason = req_str(body, "reason")
    att = find_attachment(aid)
    if att["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an ACTIVE attachment can be voided")
    appeal = store.appeals[att["appeal_id"]]
    if appeal["status"] not in ("DRAFT", "LETTER_GENERATED"):
        raise ApiError(
            ERR_APPEAL_INVALID_STATE,
            409,
            "Cannot void an attachment on an appeal in %s" % appeal["status"],
        )
    att["status"] = "VOIDED"
    att["voided_reason"] = reason
    touch(att)
    return ok(public(att))
