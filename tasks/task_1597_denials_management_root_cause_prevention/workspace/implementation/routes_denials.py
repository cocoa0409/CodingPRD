"""Routes: denial cases (intake, triage, assign, correction), work queue,
recovery projection."""

from flask import Blueprint, g, request

from auth import require_roles
from cascades import auto_create_task, recurrence_sweep, refresh_open_balance
from db import store
from envelope import list_response, ok
from errors import (
    ApiError,
    ERR_DENIAL_INVALID_STATE,
    ERR_DUPLICATE_CLAIM_NUMBER,
    ERR_PAYER_INACTIVE,
    ERR_STALE_VERSION,
    ERR_VALIDATION,
)
from services import (
    find_denial,
    find_payer,
    find_remittance_code,
    level1_deadline,
    make_record,
    matching_scorecard,
    bump_scorecard,
    emit_event,
    public,
    recompute_priority,
    recovery_projection,
    touch,
)
from util import (
    ALL_ROLES,
    DEPARTMENTS,
    get_body,
    opt_enum,
    opt_int,
    parse_date,
    req_bool,
    req_date,
    req_int,
    req_str,
    sort_created,
    today,
)

bp = Blueprint("denials", __name__)


# ---------------------------------------------------------------------------
# Denial intake
# ---------------------------------------------------------------------------


@bp.post("/rcm/denial-cases")
@require_roles("DenialsSpecialist")
def create_denial():
    body = get_body()
    claim_number = req_str(body, "claim_number")
    patient_account_number = req_str(body, "patient_account_number")
    payer_id = req_str(body, "payer_id")
    code_id = req_str(body, "remittance_code_id")
    billed = req_int(body, "billed_amount_cents")
    denied = req_int(body, "denied_amount_cents")
    if billed <= 0:
        raise ApiError(ERR_VALIDATION, 400, "billed_amount_cents must be > 0")
    if denied <= 0:
        raise ApiError(ERR_VALIDATION, 400, "denied_amount_cents must be > 0")
    if denied > billed:
        raise ApiError(
            ERR_VALIDATION, 400, "denied_amount_cents must be <= billed_amount_cents"
        )
    service_date = req_date(body, "service_date")
    remit_date = req_date(body, "remittance_received_date")

    payer = find_payer(payer_id)
    code = find_remittance_code(code_id)
    if payer["status"] != "ACTIVE":
        raise ApiError(ERR_PAYER_INACTIVE, 409, "Payer %s is INACTIVE" % payer_id)
    for existing in store.denials.values():
        if existing["claim_number"] == claim_number:
            raise ApiError(
                ERR_DUPLICATE_CLAIM_NUMBER,
                409,
                "claim_number %s already exists" % claim_number,
            )

    denial = make_record(
        {
            "claim_number": claim_number,
            "patient_account_number": patient_account_number,
            "payer_id": payer_id,
            "remittance_code_id": code_id,
            "category": code["category"],
            "billed_amount_cents": billed,
            "denied_amount_cents": denied,
            "service_date": service_date,
            "remittance_received_date": remit_date,
            "status": "RECEIVED",
            "root_cause_department": None,
            "preventable_flag": False,
            "current_appeal_level": 0,
            "assigned_specialist_id": None,
            "recovered_amount_cents": 0,
            "written_off_cents": 0,
            "open_balance_cents": denied,
            "next_appeal_deadline": level1_deadline(payer, remit_date),
            "priority_score": 0.0,
            "queue_bucket": "LOW",
        }
    )
    store.denials[denial["id"]] = denial
    emit_event(
        denial["id"],
        "INTAKE",
        g.user_role,
        g.user_id,
        "claim_number=%s;denied_amount_cents=%d;payer_id=%s;category=%s;status=RECEIVED"
        % (claim_number, denied, payer_id, code["category"]),
    )
    return ok(public(denial), "object", 201)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


@bp.get("/rcm/denial-cases")
@require_roles(*ALL_ROLES)
def list_denials():
    items = list(store.denials.values())
    for param, field in (
        ("payer_id", "payer_id"),
        ("remittance_code_id", "remittance_code_id"),
        ("status", "status"),
        ("category", "category"),
        ("queue_bucket", "queue_bucket"),
        ("assigned_specialist_id", "assigned_specialist_id"),
        ("root_cause_department", "root_cause_department"),
    ):
        val = request.args.get(param)
        if val is not None:
            items = [d for d in items if d[field] == val]
    return list_response([public(d) for d in sort_created(items)])


@bp.get("/rcm/denial-cases/<did>")
@require_roles(*ALL_ROLES)
def get_denial(did):
    return ok(public(find_denial(did)))


@bp.get("/rcm/denial-cases/<did>/recovery-projection")
@require_roles(*ALL_ROLES)
def get_recovery_projection(did):
    variant = request.args.get("variant", "gross")
    if variant not in ("gross", "net"):
        raise ApiError(ERR_VALIDATION, 400, "variant must be 'gross' or 'net'")
    denial = find_denial(did)
    return ok(recovery_projection(denial, variant))


# ---------------------------------------------------------------------------
# Intake correction (OCC-guarded)
# ---------------------------------------------------------------------------


@bp.patch("/rcm/denial-cases/<did>")
@require_roles("DenialsManager")
def patch_denial(did):
    body = get_body()
    expected = req_int(body, "expected_denial_case_version")
    new_billed = opt_int(body, "billed_amount_cents")
    new_denied = opt_int(body, "denied_amount_cents")
    new_remit = None
    if "remittance_received_date" in body and body["remittance_received_date"] is not None:
        new_remit = req_date(body, "remittance_received_date")
    if new_billed is not None and new_billed <= 0:
        raise ApiError(ERR_VALIDATION, 400, "billed_amount_cents must be > 0")
    if new_denied is not None and new_denied <= 0:
        raise ApiError(ERR_VALIDATION, 400, "denied_amount_cents must be > 0")

    denial = find_denial(did)
    if expected != denial["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            412,
            "expected_denial_case_version %s does not match current version %s"
            % (expected, denial["version"]),
        )
    if denial["status"] not in ("RECEIVED", "TRIAGED"):
        raise ApiError(
            ERR_DENIAL_INVALID_STATE,
            409,
            "Intake correction requires RECEIVED or TRIAGED status",
        )

    merged_billed = new_billed if new_billed is not None else denial["billed_amount_cents"]
    merged_denied = new_denied if new_denied is not None else denial["denied_amount_cents"]
    if merged_denied > merged_billed:
        raise ApiError(
            ERR_VALIDATION, 400, "denied_amount_cents must be <= billed_amount_cents"
        )

    denial["billed_amount_cents"] = merged_billed
    denial["denied_amount_cents"] = merged_denied
    if new_remit is not None and new_remit != denial["remittance_received_date"]:
        denial["remittance_received_date"] = new_remit
        payer = store.payers[denial["payer_id"]]
        denial["next_appeal_deadline"] = level1_deadline(payer, new_remit)
    refresh_open_balance(denial)
    recompute_priority(denial)
    touch(denial)
    emit_event(
        denial["id"],
        "INTAKE_CORRECTED",
        g.user_role,
        g.user_id,
        "billed_amount_cents=%d;denied_amount_cents=%d;remittance_received_date=%s"
        % (merged_billed, merged_denied, denial["remittance_received_date"]),
    )
    return ok(public(denial))


# ---------------------------------------------------------------------------
# Triage
# ---------------------------------------------------------------------------


@bp.post("/rcm/denial-cases/<did>/triage")
@require_roles("DenialsSpecialist")
def triage_denial(did):
    body = get_body()
    preventable = req_bool(body, "preventable_flag")
    override = opt_enum(body, "root_cause_department", DEPARTMENTS)
    denial = find_denial(did)
    if denial["status"] != "RECEIVED":
        raise ApiError(
            ERR_DENIAL_INVALID_STATE, 409, "Triage requires RECEIVED status"
        )
    code = store.remittance_codes[denial["remittance_code_id"]]
    department = override if override is not None else code["default_department"]
    denial["root_cause_department"] = department
    denial["preventable_flag"] = preventable
    denial["status"] = "TRIAGED"

    today_d = today()
    sc = matching_scorecard(department, today_d)
    if sc is not None:
        deltas = {"denial_count": 1, "denied_cents": denial["denied_amount_cents"]}
        if preventable:
            deltas["preventable_denial_count"] = 1
            deltas["preventable_denied_cents"] = denial["denied_amount_cents"]
        bump_scorecard(sc, **deltas)
    if preventable:
        auto_create_task(denial, g.user_role, g.user_id)
    recurrence_sweep(denial)

    recompute_priority(denial)
    touch(denial)
    emit_event(
        denial["id"],
        "TRIAGED",
        g.user_role,
        g.user_id,
        "root_cause_department=%s;preventable_flag=%s;status=TRIAGED"
        % (department, "true" if preventable else "false"),
    )
    return ok(public(denial))


# ---------------------------------------------------------------------------
# Assignment (OCC-guarded)
# ---------------------------------------------------------------------------


@bp.post("/rcm/denial-cases/<did>/assign")
@require_roles("DenialsManager")
def assign_denial(did):
    body = get_body()
    specialist_id = req_str(body, "specialist_id")
    expected = req_int(body, "expected_denial_case_version")
    denial = find_denial(did)
    if expected != denial["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            412,
            "expected_denial_case_version %s does not match current version %s"
            % (expected, denial["version"]),
        )
    if denial["status"] not in ("TRIAGED", "QUEUED"):
        raise ApiError(
            ERR_DENIAL_INVALID_STATE,
            409,
            "Assignment requires TRIAGED or QUEUED status",
        )
    denial["assigned_specialist_id"] = specialist_id
    denial["status"] = "QUEUED"
    recompute_priority(denial)
    touch(denial)
    emit_event(
        denial["id"],
        "ASSIGNED",
        g.user_role,
        g.user_id,
        "assigned_specialist_id=%s;status=%s" % (specialist_id, denial["status"]),
    )
    return ok(public(denial))


# ---------------------------------------------------------------------------
# Ranked work queue
# ---------------------------------------------------------------------------


@bp.get("/rcm/work-queue")
@require_roles("DenialsSpecialist", "DenialsManager")
def work_queue():
    items = [d for d in store.denials.values() if d["status"] in ("QUEUED", "IN_APPEAL")]
    specialist = request.args.get("assigned_specialist_id")
    if specialist is not None:
        items = [d for d in items if d["assigned_specialist_id"] == specialist]
    bucket = request.args.get("queue_bucket")
    if bucket is not None:
        items = [d for d in items if d["queue_bucket"] == bucket]
    items.sort(
        key=lambda d: (
            -d["priority_score"],
            d["next_appeal_deadline"] if d["next_appeal_deadline"] else "9999-12-31",
            d["created_at"],
            d["_seq"],
        )
    )
    return list_response([public(d) for d in items])
