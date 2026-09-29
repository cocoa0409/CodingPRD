"""USPS change-of-address filings: draft, submit/resubmit, USPS response and
withdrawal."""

from flask import Blueprint

import db
import response
import validators as v
from errors import ApiError
from middleware import (
    COMPLIANCE_OFFICER,
    EXTERNAL_SERVICE_GATEWAY,
    MOVE_OPS_AGENT,
    RESIDENT,
    authenticate,
)
from services import derive, enums, gates
from services.lookup import (
    filing_or_404,
    filings_of_move,
    move_or_404,
    verifications_of_move,
)

bp = Blueprint("filings", __name__)


@bp.post("/moves/<move_id>/address-change-filings")
def create_filing(move_id):
    authenticate(MOVE_OPS_AGENT, COMPLIANCE_OFFICER)
    move = move_or_404(move_id)
    body = v.body()
    filing_type = v.enum_field(body, "filing_type", enums.FILING_TYPES)
    start_text, start_date = v.date_field(body, "forward_start_date")

    # Deliberately permissive lifecycle gate: the identity rung is what rejects
    # a filing prepared before identity cleared.
    gates.require_move_state(
        move,
        (
            "IDENTITY_PENDING",
            "IDENTITY_FAILED",
            "VERIFIED",
            "SCHEDULING",
            "ATTENTION_REQUIRED",
            "IN_SERVICE",
        ),
    )
    gates.require_identity_verified(move)
    gates.require_duplicate_resolved(move)

    for existing in filings_of_move(move["id"]):
        if existing["status"] in enums.FILING_ACTIVE:
            raise ApiError(
                "ERR_FILING_NOT_SUBMITTABLE",
                "This move already has an active address-change filing.",
            )

    rec = db.base_record()
    rec.update(
        {
            "move_id": move["id"],
            "resident_id": move["resident_id"],
            "filing_type": filing_type,
            "forward_start_date": start_text,
            "forward_end_date": db.add_days(
                start_date, enums.FORWARD_PERIOD_DAYS - 1
            ).isoformat(),
            "status": "DRAFT",
            "submitted_by_user_id": None,
            "resubmit_count": 0,
            "usps_confirmation_code": None,
            "reject_reason": None,
            "mail_forwarding_confirmed_at": None,
            "cancellation_reason": None,
        }
    )
    db.db.filings[rec["id"]] = rec
    derive.refresh(move)
    return response.created(db.public(rec))


@bp.get("/address-change-filings/<filing_id>")
def read_filing(filing_id):
    caller = authenticate(MOVE_OPS_AGENT, COMPLIANCE_OFFICER, RESIDENT)
    rec = filing_or_404(filing_id)
    caller.own_if(RESIDENT, rec["resident_id"])
    return response.ok(db.public(rec))


@bp.get("/address-change-filings")
def list_filings():
    authenticate(MOVE_OPS_AGENT, COMPLIANCE_OFFICER)
    rows = response.match_filters(
        db.db.filings.values(),
        {
            "move_id": "move_id",
            "resident_id": "resident_id",
            "status": "status",
            "filing_type": "filing_type",
        },
    )
    return response.paginated(rows)


# ------------------------------------------------------------------ submission
@bp.post("/address-change-filings/<filing_id>/submission")
def submit_filing(filing_id):
    caller = authenticate(MOVE_OPS_AGENT, COMPLIANCE_OFFICER)
    filing = filing_or_404(filing_id)
    v.body()

    move = move_or_404(filing["move_id"])
    gates.require_move_state(
        move, ("VERIFIED", "SCHEDULING", "ATTENTION_REQUIRED", "IN_SERVICE")
    )
    gates.require_filing_state(filing["status"], enums.FILING_SUBMITTABLE)
    gates.require_identity_verified(move)
    gates.require_identity_current(move)

    # rung 19: whoever waved identity through may not also file the redirect.
    for row in verifications_of_move(move["id"]):
        if (
            row["method"] == "MANUAL_OVERRIDE"
            and row["status"] == "PASSED"
            and row["reviewer_user_id"] == caller.user_id
        ):
            raise ApiError(
                "ERR_SEGREGATION_OF_DUTIES",
                "The identity override reviewer may not submit the postal filing.",
            )

    gates.require_consent(move, "USPS_FILING")
    gates.require_gate_open(move)

    # rung 28: the destination must be deliverable.
    destination = db.db.service_addresses[move["destination_address_id"]]
    if not destination["usps_deliverable"]:
        raise ApiError(
            "ERR_ADDRESS_NOT_DELIVERABLE",
            "The destination address is not USPS deliverable.",
        )

    # rung 34: the forwarding period may not start in the past.
    start_date = db.parse_date(filing["forward_start_date"])
    if start_date < db.clock_date():
        raise ApiError(
            "ERR_FORWARD_DATE_INVALID",
            "forward_start_date must be on or after the current date.",
        )

    # rung 35: one active forwarding period per resident.
    end_date = db.parse_date(filing["forward_end_date"])
    for other in sorted(db.db.filings.values(), key=db.order_key):
        if other["id"] == filing["id"]:
            continue
        if other["resident_id"] != filing["resident_id"]:
            continue
        if other["status"] not in ("SUBMITTED", "CONFIRMED"):
            continue
        other_start = db.parse_date(other["forward_start_date"])
        other_end = db.parse_date(other["forward_end_date"])
        if start_date <= other_end and other_start <= end_date:
            raise ApiError(
                "ERR_FORWARDING_PERIOD_CONFLICT",
                "The resident already has an overlapping active forwarding period.",
            )

    # rung 42: the resubmission budget.
    if filing["status"] == "REJECTED":
        if filing["resubmit_count"] >= enums.MAX_RESUBMITS:
            raise ApiError(
                "ERR_RESUBMIT_LIMIT_REACHED",
                "This filing has reached its resubmission limit.",
            )
        filing["resubmit_count"] = filing["resubmit_count"] + 1
        filing["reject_reason"] = None

    filing["status"] = "SUBMITTED"
    filing["submitted_by_user_id"] = caller.user_id
    db.touch(filing)
    derive.refresh(move)
    return response.ok(db.public(filing))


# --------------------------------------------------------------- USPS response
@bp.post("/address-change-filings/<filing_id>/usps-response")
def usps_response(filing_id):
    authenticate(EXTERNAL_SERVICE_GATEWAY)
    filing = filing_or_404(filing_id)
    body = v.body()
    outcome = v.enum_field(body, "outcome", enums.FILING_OUTCOMES)
    code = v.str_field(
        body, "usps_confirmation_code", required=False, min_len=1, max_len=64, default=None
    )
    reject_reason = v.str_field(
        body, "reject_reason", required=False, min_len=1, max_len=500, default=None
    )
    if outcome == "CONFIRMED" and code is None:
        v.bad("Field 'usps_confirmation_code' is required for a CONFIRMED outcome.")
    if outcome == "REJECTED" and reject_reason is None:
        v.bad("Field 'reject_reason' is required for a REJECTED outcome.")

    gates.require_filing_state(filing["status"], ("SUBMITTED",))
    move = move_or_404(filing["move_id"])
    snap = derive.snapshot(move)

    if outcome == "CONFIRMED":
        filing["status"] = "CONFIRMED"
        filing["usps_confirmation_code"] = code
        filing["mail_forwarding_confirmed_at"] = db.now_iso()
        db.touch(filing)
        derive.recompute(move)
        derive.try_bubble_up(move)
    else:
        filing["status"] = "REJECTED"
        filing["reject_reason"] = reject_reason
        db.touch(filing)
        derive.park_attention(move, "FILING_REJECTED")

    derive.recompute(move)
    derive.commit(move, snap)
    return response.ok(db.public(filing))


# ---------------------------------------------------------------- cancellation
@bp.post("/address-change-filings/<filing_id>/cancellation")
def cancel_filing(filing_id):
    authenticate(COMPLIANCE_OFFICER)
    filing = filing_or_404(filing_id)
    body = v.body()
    reason = v.str_field(body, "cancellation_reason", min_len=1, max_len=500)

    gates.require_filing_state(filing["status"], enums.FILING_NON_TERMINAL)

    filing["status"] = "CANCELLED"
    filing["cancellation_reason"] = reason
    filing["mail_forwarding_confirmed_at"] = None
    db.touch(filing)

    move = db.db.moves.get(filing["move_id"])
    if move is not None and move["lifecycle_status"] not in enums.TERMINAL_LIFECYCLE:
        derive.refresh(move)
    return response.ok(db.public(filing))
