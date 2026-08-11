"""The opt-out removal lifecycle (PRD §3.5)."""

from flask import Blueprint, request

import cascades
import constants as K
import context
import derive
import envelope
import ledger
import rows
import serializers
import states
from clock import CLOCK, plus_days, plus_hours
from context import Ctx
from errors import ApiError
from store import DB, ordered

bp = Blueprint("removals", __name__)

ALL_READ_ROLES = [
    K.ROLE_PLATFORM_ADMIN,
    K.ROLE_PRIVACY_AGENT,
    K.ROLE_ACCOUNT_OWNER,
    K.ROLE_MEMBER,
    K.ROLE_AUDITOR,
]

OPEN_STATUSES = ("DRAFTED", "SUBMITTED", "ACKNOWLEDGED", "ESCALATED")
CLOSED_STATUSES = ("COMPLETED", "REJECTED", "EXPIRED", "VOIDED")


def _account_of(request_row):
    member = DB.members.get(request_row["member_id"])
    return DB.accounts.get(member["account_id"]) if member else None


# --- POST /removal-requests -------------------------------------------------

@bp.post("/removal-requests")
def draft_removal():
    ctx = Ctx(request, [K.ROLE_PRIVACY_AGENT, K.ROLE_ACCOUNT_OWNER, K.ROLE_MEMBER])
    ctx.load_body()
    fields = ctx.validate([{"name": "exposure_id", "type": "string", "required": True}])
    # Rung 11
    exposure = DB.exposures.get(fields["exposure_id"])
    if exposure is None:
        raise ApiError("ERR_EXPOSURE_NOT_FOUND")
    profile = DB.profiles.get(exposure["profile_id"])
    member = DB.members.get(profile["member_id"])
    account = DB.accounts.get(member["account_id"])
    broker = DB.brokers.get(exposure["broker_id"])
    # Rung 12
    ctx.own(account["id"], member["id"])
    # Rungs 13-15
    ctx.write_gates(account)
    # Rung 16
    if member["authorization_status"] != "GRANTED":
        raise ApiError("ERR_AUTHORIZATION_REVOKED")
    # Rung 22
    if broker is None or broker["status"] != "ACTIVE":
        raise ApiError("ERR_BROKER_RETIRED")

    siblings = derive.exposure_requests(exposure["id"])

    # Adjudication of friction 2: rung 32 (the 24-hour reopen buffer) is
    # numbered ahead of rung 35 (the duplicate-request check), while PRD §3.5
    # narrates the open-request test first. Both codes stay fully reachable
    # under either ordering (a duplicate with no closed predecessor reports
    # rung 35; a buffer breach with no open incumbent reports rung 32), so
    # reachability does not separate them. The tie is broken by PRD §2.6's
    # unconditional statement that the ladder "is the single arbiter of error
    # precedence across the whole API" and its lowest-number-wins rule:
    # rung 32 is evaluated first.

    # Rung 32 -- the buffer. Incumbent = most recently closed request on this
    # exposure, ranked by closed_at DESC, tie-broken by created_at DESC.
    closed = [r for r in siblings if r["status"] in CLOSED_STATUSES and r["closed_at"]]
    if closed:
        closed.sort(key=lambda r: (r["closed_at"], r["created_at"], r["id"]), reverse=True)
        incumbent = closed[0]
        # INCLUSIVE on the allow side: exactly closed_at + 24h is admitted.
        if CLOCK.now < plus_hours(incumbent["closed_at"], K.REQUEST_REOPEN_BUFFER_HOURS):
            raise ApiError("ERR_EXPOSURE_CHANNEL_BUFFER")
    # Rung 35 -- capacity on an exposure is exactly one live request.
    if any(r["status"] in OPEN_STATUSES for r in siblings):
        raise ApiError("ERR_DUPLICATE_REMOVAL_REQUEST")

    # The entitlement draw, pinned in three steps.
    fee_exempt = exposure["status"] == "REAPPEARED"
    if fee_exempt:
        units = 0
    else:
        pools = derive.pool_figures(account["id"])
        # Rung 45 -- the shared pool is checked strictly before the sub-cap.
        if pools["removal"]["remaining"] < 1:
            raise ApiError("ERR_REMOVAL_QUOTA_EXCEEDED")
        # Rung 46
        if derive.member_subcap_remaining(member) < 1:
            raise ApiError("ERR_MEMBER_SUBCAP_EXCEEDED")
        units = 1

    row = rows.new_row(
        "removal_requests",
        {
            "exposure_id": exposure["id"],
            "broker_id": exposure["broker_id"],
            "member_id": member["id"],
            "status": "DRAFTED",
            "submitted_at": None,
            "acknowledged_at": None,
            "closed_at": None,
            "sla_deadline_at": None,
            "effective_window_days": None,
            "deadline_variant": None,
            "submitted_by_agent_id": None,
            "completed_by_agent_id": None,
            "broker_reference": None,
            "rejection_reason_code": None,
            "escalation_count": 0,
            "entitlement_units_consumed": units,
            "entitlement_units_released": 0,
        },
    )
    if units == 1:
        ledger.append(
            account_id=account["id"],
            member_id=member["id"],
            resource_type="REMOVAL",
            entry_type="CONSUME",
            amount=1,
            reason_code="REMOVAL_DRAFTED",
            source_reference=row["id"],
        )
    return envelope.created(serializers.removal_request(row))


# --- reads ------------------------------------------------------------------

def _visible(ctx, row):
    if not ctx.is_scoped_caller:
        return True
    member = DB.members.get(row["member_id"])
    if member is None or member["account_id"] != ctx.caller_member["account_id"]:
        return False
    if ctx.is_non_primary_member and row["member_id"] != ctx.caller_member["id"]:
        return False
    return True


@bp.get("/removal-requests")
def list_removals():
    ctx = Ctx(request, ALL_READ_ROLES)
    status = context.enum_filter(request, "status", K.REMOVAL_STATUSES)
    limit, offset = context.pagination(request)
    exposure_id = context.plain_filter(request, "exposure_id")
    broker_id = context.plain_filter(request, "broker_id")
    member_id = context.plain_filter(request, "member_id")
    result = []
    for row in DB.removal_requests.values():
        if exposure_id is not None and row["exposure_id"] != exposure_id:
            continue
        if broker_id is not None and row["broker_id"] != broker_id:
            continue
        if member_id is not None and row["member_id"] != member_id:
            continue
        if status is not None and row["status"] != status:
            continue
        if not _visible(ctx, row):
            continue
        result.append(row)
    page, total = context.window(ordered(result), limit, offset)
    return envelope.listing(
        [serializers.removal_request(r) for r in page], limit, offset, total
    )


@bp.get("/removal-requests/<request_id>")
def read_removal(request_id):
    ctx = Ctx(request, ALL_READ_ROLES)
    row = ctx.path("removal_request", request_id)
    ctx.own(_account_of(row)["id"], row["member_id"])
    return envelope.ok(serializers.removal_request(row))


# --- identity evidence gate (rungs 25 and 26) -------------------------------

def _apply_lazy_expiry(documents):
    """The declared system transition VERIFIED -> EXPIRED."""
    for doc in documents:
        if doc["status"] == "VERIFIED" and CLOCK.now >= doc["expires_at_dt"]:
            doc["status"] = "EXPIRED"
            rows.touch(doc)


def _identity_gate(member, broker):
    if not broker["requires_identity_verification"]:
        return
    documents = [d for d in DB.documents.values() if d["member_id"] == member["id"]]
    # Adjudication of friction 3: the lazy VERIFIED -> EXPIRED transition and
    # rungs 25/26. Applying the transition BEFORE the rungs would leave the
    # member with no VERIFIED document at all, so rung 25 would fire and
    # ERR_IDENTITY_DOCUMENT_EXPIRED (rung 26) would become unreachable for
    # every input. Reachability-maximising reading: rungs 25 and 26 are
    # evaluated against the STORED status first, and the declared system
    # transition is applied afterwards (the endpoint has consulted the
    # document either way), so both codes and the transition stay observable.
    verified = [d for d in documents if d["status"] == "VERIFIED"]
    # Rung 25
    if not verified:
        raise ApiError("ERR_IDENTITY_VERIFICATION_REQUIRED")
    # Rung 26
    all_expired = all(CLOCK.now >= d["expires_at_dt"] for d in verified)
    if all_expired:
        _apply_lazy_expiry(verified)
        raise ApiError("ERR_IDENTITY_DOCUMENT_EXPIRED")
    _apply_lazy_expiry(verified)


# --- transitions ------------------------------------------------------------

@bp.post("/removal-requests/<request_id>/submit")
def submit_removal(request_id):
    ctx = Ctx(request, [K.ROLE_PRIVACY_AGENT])
    row = ctx.path("removal_request", request_id)
    member = DB.members.get(row["member_id"])
    account = DB.accounts.get(member["account_id"])
    broker = DB.brokers.get(row["broker_id"])
    ctx.write_gates(account)
    # Rung 16
    if member["authorization_status"] != "GRANTED":
        raise ApiError("ERR_AUTHORIZATION_REVOKED")
    # Rungs 18/19
    states.gate("removal_status", row["status"], ("DRAFTED", "ESCALATED"))
    from_drafted = row["status"] == "DRAFTED"
    # Rung 22
    if broker["status"] != "ACTIVE":
        raise ApiError("ERR_BROKER_RETIRED")
    if from_drafted:
        # Adjudication of friction 4: the DRAFTED -> SUBMITTED precondition
        # "ExposureRecord.status IN {FOUND, REAPPEARED}" is declared with no
        # dedicated error code, and PRD §3.5 refuses to invent one. It IS
        # reachable (draft against an already-SUPPRESSED exposure once the
        # 24-hour buffer has elapsed, then submit). Reachability-maximising
        # reading: enforce it and report it through the generic state code
        # ERR_INVALID_STATE -- no code is invented, and the completion cascade
        # keeps a declared hop-2 edge (FOUND -> SUPPRESSED or REAPPEARED ->
        # RE_SUPPRESSED) for every request that can reach COMPLETED. Not
        # enforcing it would strand the cascade with no declared edge to take.
        # It is evaluated in the scaffold's declared precondition order, i.e.
        # after the broker check (rung 22) and before the identity gate.
        exposure = DB.exposures.get(row["exposure_id"])
        if exposure is None or exposure["status"] not in ("FOUND", "REAPPEARED"):
            raise ApiError(
                "ERR_INVALID_STATE",
                "The linked exposure is not in FOUND or REAPPEARED.",
            )
        # Rungs 25 and 26
        _identity_gate(member, broker)
        window_days = max(
            int(broker["response_window_days"])
            + K.METHOD_SLA_BUFFER_DAYS[broker["opt_out_method"]],
            K.JURISDICTION_SLA_FLOOR_DAYS[broker["jurisdiction"]],
        )
        variant = "BASE"
    else:
        # The ESCALATED edge declares neither the exposure-status precondition
        # nor the identity gate.
        window_days = K.ESCALATION_RESUBMIT_WINDOW_DAYS
        variant = "ESCALATED_RESUBMISSION"

    row["status"] = "SUBMITTED"
    row["submitted_at"] = CLOCK.now
    row["submitted_by_agent_id"] = ctx.user_id
    row["effective_window_days"] = window_days
    row["deadline_variant"] = variant
    row["sla_deadline_at"] = plus_days(CLOCK.now, window_days)
    rows.touch(row)
    return envelope.ok(serializers.removal_request(row))


@bp.post("/removal-requests/<request_id>/acknowledge")
def acknowledge_removal(request_id):
    ctx = Ctx(request, [K.ROLE_PRIVACY_AGENT])
    row = ctx.path("removal_request", request_id)
    ctx.load_body()
    fields = ctx.validate([{"name": "broker_reference", "type": "string", "required": True}])
    ctx.write_gates(_account_of(row))
    states.gate("removal_status", row["status"], ("SUBMITTED",))
    row["status"] = "ACKNOWLEDGED"
    row["broker_reference"] = fields["broker_reference"]
    row["acknowledged_at"] = CLOCK.now
    rows.touch(row)
    return envelope.ok(serializers.removal_request(row))


@bp.post("/removal-requests/<request_id>/complete")
def complete_removal(request_id):
    ctx = Ctx(request, [K.ROLE_PRIVACY_AGENT])
    row = ctx.path("removal_request", request_id)
    ctx.write_gates(_account_of(row))
    states.gate("removal_status", row["status"], ("ACKNOWLEDGED",))
    # Rung 27 -- segregation of duties.
    if ctx.user_id == row["submitted_by_agent_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    cascades.complete_removal(row, ctx.user_id)
    return envelope.ok(serializers.removal_request(row))


@bp.post("/removal-requests/<request_id>/reject")
def reject_removal(request_id):
    ctx = Ctx(request, [K.ROLE_PRIVACY_AGENT])
    row = ctx.path("removal_request", request_id)
    ctx.load_body()
    fields = ctx.validate(
        [{"name": "rejection_reason_code", "type": "string", "required": True}]
    )
    ctx.write_gates(_account_of(row))
    states.gate("removal_status", row["status"], ("ACKNOWLEDGED",))
    row["status"] = "REJECTED"
    row["rejection_reason_code"] = fields["rejection_reason_code"]
    row["closed_at"] = CLOCK.now
    # The consumed REMOVAL unit is deliberately NOT released.
    rows.touch(row)
    return envelope.ok(serializers.removal_request(row))


@bp.post("/removal-requests/<request_id>/expire")
def expire_removal(request_id):
    ctx = Ctx(request, [K.ROLE_PRIVACY_AGENT, K.ROLE_PLATFORM_ADMIN])
    row = ctx.path("removal_request", request_id)
    ctx.write_gates(_account_of(row))
    states.gate("removal_status", row["status"], ("SUBMITTED", "ACKNOWLEDGED"))
    # Rung 28 -- INCLUSIVE boundary.
    if row["sla_deadline_at"] is None or CLOCK.now < row["sla_deadline_at"]:
        raise ApiError("ERR_SLA_NOT_ELAPSED")
    row["status"] = "EXPIRED"
    row["closed_at"] = CLOCK.now
    rows.touch(row)
    return envelope.ok(serializers.removal_request(row))


@bp.post("/removal-requests/<request_id>/escalate")
def escalate_removal(request_id):
    ctx = Ctx(request, [K.ROLE_PRIVACY_AGENT])
    row = ctx.path("removal_request", request_id)
    ctx.write_gates(_account_of(row))
    states.gate("removal_status", row["status"], ("REJECTED", "EXPIRED"))
    broker = DB.brokers.get(row["broker_id"])
    # Rung 22
    if broker["status"] != "ACTIVE":
        raise ApiError("ERR_BROKER_RETIRED")
    # Rung 33
    if row["escalation_count"] >= K.MAX_ESCALATIONS:
        raise ApiError("ERR_ESCALATION_CAP_REACHED")
    row["status"] = "ESCALATED"
    row["escalation_count"] = row["escalation_count"] + 1
    row["closed_at"] = None
    rows.touch(row)
    return envelope.ok(serializers.removal_request(row))


@bp.post("/removal-requests/<request_id>/void")
def void_removal(request_id):
    ctx = Ctx(request, [K.ROLE_PRIVACY_AGENT, K.ROLE_ACCOUNT_OWNER, K.ROLE_MEMBER])
    row = ctx.path("removal_request", request_id)
    account = _account_of(row)
    ctx.own(account["id"], row["member_id"])
    ctx.write_gates(account)
    states.gate("removal_status", row["status"], ("DRAFTED",))
    row["status"] = "VOIDED"
    row["closed_at"] = CLOCK.now
    if row["entitlement_units_consumed"] == 1 and row["entitlement_units_released"] == 0:
        row["entitlement_units_released"] = 1
        ledger.append(
            account_id=account["id"],
            member_id=row["member_id"],
            resource_type="REMOVAL",
            entry_type="RELEASE",
            amount=1,
            reason_code="REMOVAL_VOIDED",
            source_reference=row["id"],
        )
    rows.touch(row)
    return envelope.ok(serializers.removal_request(row))
