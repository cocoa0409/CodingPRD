"""Matter intake, suspension, closure and the commercial readout (PRD 3.1, 3.9)."""

from decimal import Decimal

from flask import Blueprint, request

from db import base_row, by_creation, db, touch
from errors import ApiError
from middleware import (
    ROLE_CLIENT_COUNSEL,
    ROLE_ENGAGEMENT_MANAGER,
    ROLE_QC_LEAD,
    ROLE_STAFFING_COORDINATOR,
    body,
    require_roles,
    role,
    user_id,
)
from response import object_response, created_response, paginated
from services import cascade, compute
from services.compute import dec, round_half_up
from validation import (
    bad,
    opt_bool,
    opt_int,
    opt_str,
    present,
    req_bool,
    req_code_array,
    req_enum,
    req_id,
    req_instant,
    req_int,
    req_str,
    req_tag_array,
)

bp = Blueprint("matters", __name__)

COMPLEXITY_TIERS = ("SIMPLE", "STANDARD", "COMPLEX")
PRICING_MODELS = ("PER_DOCUMENT", "HOURLY")
BASES = ("REMAINING_WORK_BASIS", "LEDGER_REPLAY_BASIS")
LEDGER_ENTRY_TYPES = ("COMMITMENT", "REVERSAL", "ACTUAL_PER_DOCUMENT", "ACTUAL_HOURLY")


def require_matter_client(matter):
    """Rank 7 - a ClientCounsel caller must own the matter."""
    if role() == ROLE_CLIENT_COUNSEL and user_id() != matter["client_id"]:
        raise ApiError("ERR_NOT_MATTER_CLIENT",
                       "The acting client does not instruct this matter.")


def require_not_suspended(matter):
    """Rank 13."""
    if matter["status"] == "SUSPENDED":
        raise ApiError("ERR_MATTER_SUSPENDED", "The governing matter is suspended.")


@bp.route("/matters", methods=["POST"])
def create_matter():
    require_roles(ROLE_ENGAGEMENT_MANAGER)
    payload = body()

    # Rank 5 - body foreign keys resolve before request-shape checks.
    client = None
    if present(payload, "client_id") and isinstance(payload["client_id"], str) \
            and payload["client_id"].strip() != "":
        client = compute.get_client(payload["client_id"])

    client_id = req_id(payload, "client_id")
    if client is None:
        client = compute.get_client(client_id)
    name = req_str(payload, "name", 1, 200)
    document_count = req_int(payload, "document_count", 1)
    deadline_dt, deadline_raw = req_instant(payload, "deadline_utc")
    complexity_tier = req_enum(payload, "complexity_tier", COMPLEXITY_TIERS)
    required_languages = req_code_array(payload, "required_languages",
                                        allow_empty=False, must_include="EN")
    required_bar_states = req_code_array(payload, "required_bar_states", allow_empty=True)
    subject_matter_tags = req_tag_array(payload, "subject_matter_tags", allow_empty=True)
    pricing_model = req_enum(payload, "pricing_model", PRICING_MODELS)

    per_document_rate_cents = None
    hourly_rate_cents = None
    if pricing_model == "PER_DOCUMENT":
        per_document_rate_cents = req_int(payload, "per_document_rate_cents", 1)
        if present(payload, "hourly_rate_cents"):
            raise bad("'hourly_rate_cents' must be omitted for a PER_DOCUMENT matter.")
    else:
        hourly_rate_cents = req_int(payload, "hourly_rate_cents", 1)
        if present(payload, "per_document_rate_cents"):
            raise bad("'per_document_rate_cents' must be omitted for an HOURLY matter.")

    budget_cap_cents = req_int(payload, "budget_cap_cents", 1)
    min_staffed_reviewers = opt_int(payload, "min_staffed_reviewers", 1, None, 2)
    onsite_seat_count = opt_int(payload, "onsite_seat_count", 0, None, 1)
    remote_work_permitted = opt_bool(payload, "remote_work_permitted", False)

    row = base_row()
    row.update({
        "client_id": client["id"],
        "name": name,
        "document_count": document_count,
        "deadline_utc": deadline_raw,
        "_deadline_dt": deadline_dt,
        "complexity_tier": complexity_tier,
        "required_languages": required_languages,
        "required_bar_states": required_bar_states,
        "subject_matter_tags": subject_matter_tags,
        "pricing_model": pricing_model,
        "per_document_rate_cents": per_document_rate_cents,
        "hourly_rate_cents": hourly_rate_cents,
        "budget_cap_cents": budget_cap_cents,
        "min_staffed_reviewers": min_staffed_reviewers,
        "onsite_seat_count": onsite_seat_count,
        "remote_work_permitted": remote_work_permitted,
        "status": "INTAKE",
        "suspension_reason": None,
    })
    db.matters[row["id"]] = row
    return created_response(compute.matter_out(row))


@bp.route("/matters/<matter_id>", methods=["GET"])
def read_matter(matter_id):
    require_roles(ROLE_ENGAGEMENT_MANAGER, ROLE_STAFFING_COORDINATOR,
                  ROLE_QC_LEAD, ROLE_CLIENT_COUNSEL)
    matter = compute.get_matter(matter_id)
    require_matter_client(matter)
    # The read consults confidentiality agreements, so lazy expiry applies first.
    cascade.apply_lazy_expiry_many(compute.agreements_of_matter(matter["id"]))
    cascade.sync_matter_staffing(matter)
    return object_response(compute.matter_out(matter))


@bp.route("/matters", methods=["GET"])
def list_matters():
    require_roles(ROLE_ENGAGEMENT_MANAGER, ROLE_STAFFING_COORDINATOR, ROLE_QC_LEAD)
    rows = by_creation(list(db.matters.values()))
    client_id = request.args.get("client_id")
    status = request.args.get("status")
    if client_id:
        rows = [r for r in rows if r["client_id"] == client_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return paginated(rows, compute.matter_out)


@bp.route("/matters/<matter_id>/suspension", methods=["POST"])
def set_suspension(matter_id):
    require_roles(ROLE_ENGAGEMENT_MANAGER)
    matter = compute.get_matter(matter_id)
    payload = body()
    suspended = req_bool(payload, "suspended")
    suspension_reason = opt_str(payload, "suspension_reason", 1, 500, None)

    if suspended:
        if matter["status"] not in ("STAFFING", "IN_REVIEW", "QC_CLOSEOUT"):
            raise ApiError("ERR_INVALID_STATE",
                           "A matter in %s may not be suspended." % matter["status"])
        matter["status"] = "SUSPENDED"
        matter["suspension_reason"] = suspension_reason
        touch(matter)
        for session in compute.sessions_of_matter(matter["id"]):
            if session["status"] in ("SCHEDULED", "ACTIVE"):
                session["status"] = "REVOKED"
                session["closed_at"] = db.now_iso()
                touch(session)
    else:
        if matter["status"] != "SUSPENDED":
            raise ApiError("ERR_INVALID_STATE",
                           "A matter in %s may not be resumed." % matter["status"])
        matter["status"] = "STAFFING"
        matter["suspension_reason"] = None
        touch(matter)
        cascade.sync_matter_staffing(matter)
    return object_response(compute.matter_out(matter))


@bp.route("/matters/<matter_id>/close", methods=["POST"])
def close_matter(matter_id):
    require_roles(ROLE_ENGAGEMENT_MANAGER)
    matter = compute.get_matter(matter_id)
    if matter["status"] != "QC_CLOSEOUT":
        raise ApiError("ERR_INVALID_STATE",
                       "A matter closes from QC_CLOSEOUT only.")
    for batch in compute.batches_of_matter(matter["id"]):
        if batch["status"] not in ("RELEASED", "DISSOLVED"):
            raise ApiError("ERR_MATTER_NOT_CLOSEABLE",
                           "Every batch must be released or dissolved.")
    if compute.unbatched_document_count(matter) != 0:
        raise ApiError("ERR_MATTER_NOT_CLOSEABLE",
                       "Documents remain unbatched.")
    for entry in compute.entries_of_matter(matter["id"]):
        if entry["status"] != "FINAL":
            raise ApiError("ERR_MATTER_NOT_CLOSEABLE",
                           "Every privilege log entry must be FINAL.")
    for assignment in compute.assignments_of_matter(matter["id"]):
        if assignment["status"] == "SUBMITTED":
            assignment["status"] = "COMPLETED"
            touch(assignment)
    matter["status"] = "CLOSED"
    touch(matter)
    return object_response(compute.matter_out(matter))


@bp.route("/matters/<matter_id>/budget-ledger", methods=["GET"])
def list_matter_ledger(matter_id):
    require_roles(ROLE_ENGAGEMENT_MANAGER, ROLE_CLIENT_COUNSEL)
    matter = compute.get_matter(matter_id)
    rows = compute.ledger_of_matter(matter["id"])
    entry_type = request.args.get("entry_type")
    if entry_type:
        rows = [r for r in rows if r["entry_type"] == entry_type]
    return paginated(rows, compute.ledger_entry_out)


@bp.route("/matters/<matter_id>/spend-projection", methods=["GET"])
def spend_projection(matter_id):
    require_roles(ROLE_ENGAGEMENT_MANAGER, ROLE_CLIENT_COUNSEL)
    matter = compute.get_matter(matter_id)
    require_matter_client(matter)

    basis = request.args.get("basis")
    if basis is not None and basis != "":
        if basis not in BASES:
            raise bad("'basis' must be one of %s." % ", ".join(BASES))
    else:
        basis = None

    protocol = compute.effective_protocol(matter["id"])
    qc_sample_pct = dec(protocol["qc_sample_pct"]) if protocol else Decimal(0)

    # Invoice waterfall (four pinned steps, band selected exactly once).
    gross = 0
    for assignment in compute.assignments_of_matter(matter["id"]):
        if assignment["status"] in ("SUBMITTED", "COMPLETED"):
            gross += assignment["billable_amount_cents"]
    qc_surcharge = int(round_half_up(dec(gross) * qc_sample_pct * compute.QC_SURCHARGE_FACTOR, 0))
    provisional = gross + qc_surcharge
    discount_pct = compute.volume_discount_pct(provisional)
    discount = int(round_half_up(dec(provisional) * discount_pct, 0))
    invoice_total = provisional - discount

    # Remaining-work basis at the contract rate (no language premium).
    if matter["per_document_rate_cents"] is None:
        contract_rate = 0
    else:
        contract_rate = int(round_half_up(
            dec(matter["per_document_rate_cents"])
            * compute.COMPLEXITY_TIER_MULTIPLIER[matter["complexity_tier"]], 0))
    uncoded_in_flight = 0
    for assignment in compute.assignments_of_matter(matter["id"]):
        if assignment["pass_type"] != "FIRST_PASS":
            continue
        if assignment["status"] not in compute.ACTIVE_ASSIGNMENT_STATUSES:
            continue
        batch = compute.batch_of_assignment(assignment)
        uncoded_in_flight += batch["document_count"] - assignment["documents_coded"]
    unassigned_batched = sum(b["document_count"] for b in compute.batches_of_matter(matter["id"])
                             if b["status"] == "CREATED")
    unbatched = compute.unbatched_document_count(matter)
    remaining_basis = contract_rate * (uncoded_in_flight + unassigned_batched + unbatched)

    ledger_basis = compute.committed_spend_cents(matter)
    variance = remaining_basis - ledger_basis

    if basis is not None:
        basis_applied = basis
    elif matter["status"] in ("INTAKE", "PROTOCOL_PENDING", "STAFFING", "IN_REVIEW"):
        basis_applied = "REMAINING_WORK_BASIS"
    else:
        basis_applied = "LEDGER_REPLAY_BASIS"

    applied_value = remaining_basis if basis_applied == "REMAINING_WORK_BASIS" else ledger_basis

    return object_response({
        "matter_id": matter["id"],
        "basis_applied": basis_applied,
        "remaining_work_basis_cents": remaining_basis,
        "ledger_replay_basis_cents": ledger_basis,
        "variance_cents": variance,
        "gross_billable_cents": gross,
        "qc_surcharge_cents": qc_surcharge,
        "provisional_total_cents": provisional,
        "volume_discount_pct": float(discount_pct),
        "volume_discount_cents": discount,
        "invoice_total_cents": invoice_total,
        "budget_cap_cents": matter["budget_cap_cents"],
        "budget_headroom_cents": matter["budget_cap_cents"] - applied_value,
    })
