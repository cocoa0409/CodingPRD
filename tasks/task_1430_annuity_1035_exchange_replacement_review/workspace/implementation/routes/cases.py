"""ExchangeCase endpoints — lifecycle state machine (SCAFFOLD §1.2, PRD §3)."""
from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_ANALYSIS_MISSING,
    ERR_CASE_NOT_OWNED_BY_PRODUCER,
    ERR_CONTRACT_EXCHANGED_WITHIN_12M,
    ERR_CONTRACT_EXCHANGE_IN_PROGRESS,
    ERR_CONTRACT_NOT_IN_FORCE,
    ERR_COOLING_OFF_ACTIVE,
    ERR_DOCUMENT_LOCKED,
    ERR_DUTY_SEGREGATION_VIOLATION,
    ERR_FREE_LOOK_EXPIRED,
    ERR_FREE_LOOK_STILL_ACTIVE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_NOT_FOUND,
    ERR_PARTIAL_AMOUNT_INVALID,
    ERR_PARTIAL_BELOW_MINIMUM,
    ERR_PRODUCER_SUSPENDED,
    ERR_REQUIRED_DOCUMENTS_INCOMPLETE,
    ERR_STALE_VERSION,
)
from middleware import require_roles
from response import success_object, success_list
from routes.common import (
    apply_pagination,
    get_json_body,
    lookup_or_404,
    optional_int,
    parse_pagination,
    require_enum,
    require_int,
    require_str,
)
from services import churn
from services.calculations import (
    ANTI_CHURN_WINDOW_DAYS,
    COOLING_OFF_DAYS_AFTER_RESCISSION,
    MIN_PARTIAL_CENTS,
    SETTLEMENT_LAG_DAYS,
    compute_analysis_fields,
    free_look_deadline_date,
    surrender_charge_cents,
    surrender_pct_bps,
)
from services.serializers import (
    activity_event_view,
    analysis_view,
    case_view,
    document_view,
    review_decision_view,
    transfer_view,
)

bp = Blueprint("cases", __name__)

ALL_ROLES = (
    "CarrierAdmin", "Producer", "SuitabilityReviewer",
    "Principal", "ComplianceOfficer", "OperationsDesk",
)

TERMINAL_CASE_STATES = {"COMPLETED", "REJECTED", "WITHDRAWN", "RESCINDED"}
REQUIRED_DOC_TYPES = {"REPLACEMENT_DISCLOSURE", "SUITABILITY_FORM", "IN_FORCE_ILLUSTRATION"}
ALLOWED_DOC_CASE_STATES = {"DRAFT", "SUBMITTED", "SUITABILITY_REVIEW", "INFO_REQUESTED"}
WITHDRAWABLE_STATES = {"DRAFT", "SUBMITTED", "SUITABILITY_REVIEW", "INFO_REQUESTED", "PENDING_PRINCIPAL", "APPROVED"}
DOC_TYPES = {"REPLACEMENT_DISCLOSURE", "SUITABILITY_FORM", "IN_FORCE_ILLUSTRATION"}


def _bump(entity, now):
    entity["version"] += 1
    entity["updated_at"] = now


def _now():
    return db.now_formatted()


def _now_dt():
    return db.parse_iso(db.now_iso())


def _append_review_decision(case_id, stage, reviewer_id, decision, rationale):
    rd = {
        "id": db.new_id(),
        "case_id": case_id,
        "stage": stage,
        "reviewer_id": reviewer_id,
        "decision": decision,
        "rationale": rationale,
        "created_at": _now(),
    }
    db.review_decisions.append(rd)
    return rd


def _check_case_ownership(case, user_id, role):
    """Producer-role callers may only mutate cases whose producer_id matches."""
    if role == "Producer" and case["producer_id"] != user_id:
        raise ApiError(
            ERR_CASE_NOT_OWNED_BY_PRODUCER,
            "Producer-role caller attempts to mutate a case whose producer_id differs from X-User-ID",
            403,
        )


# ---------------------------------------------------------------------------
# Case CRUD
# ---------------------------------------------------------------------------

@bp.route("/cases", methods=["POST"])
def create_case():
    user_id, role = require_roles("Producer")
    body = get_json_body()

    producer_id = require_str(body, "producer_id")
    client_id = require_str(body, "client_id")
    existing_contract_id = require_str(body, "existing_contract_id")
    exchange_type = require_enum(body, "exchange_type", {"FULL", "PARTIAL"})
    new_product_code = require_str(body, "new_product_code")
    new_product_surrender_years = require_int(body, "new_product_surrender_years", min_value=0)
    new_product_bonus_bps = optional_int(body, "new_product_bonus_bps", 0, min_value=0, max_value=10000)
    new_product_annual_fee_bps = optional_int(body, "new_product_annual_fee_bps", 0, min_value=0, max_value=10000)

    # Body-shape check for exchange_amount_cents on PARTIAL
    if exchange_type == "PARTIAL":
        if "exchange_amount_cents" not in body or body["exchange_amount_cents"] is None:
            raise ApiError(
                ERR_INVALID_REQUEST,
                "exchange_amount_cents is required for PARTIAL exchanges",
                400,
            )
        exchange_amount_cents = require_int(body, "exchange_amount_cents", positive=True)
    else:
        # FULL: field is ignored (system-set to account_value_cents)
        exchange_amount_cents = None

    # Existence: body FKs resolved left-to-right (client_id, existing_contract_id, producer_id)
    # PRD §2.8: "then body foreign keys such as client_id, existing_contract_id, and producer_id"
    if client_id not in db.clients:
        raise ApiError(ERR_NOT_FOUND, "client_id does not resolve to an existing resource", 404)
    if existing_contract_id not in db.contracts:
        raise ApiError(ERR_NOT_FOUND, "existing_contract_id does not resolve to an existing resource", 404)
    if producer_id not in db.producers:
        raise ApiError(ERR_NOT_FOUND, "producer_id does not resolve to an existing resource", 404)

    # Ownership: producer_id must equal X-User-ID (case creation is a producer mutation)
    if producer_id != user_id:
        raise ApiError(
            ERR_CASE_NOT_OWNED_BY_PRODUCER,
            "producer_id must equal the caller's X-User-ID",
            403,
        )

    contract = db.contracts[existing_contract_id]
    if exchange_type == "FULL":
        exchange_amount_cents = contract["account_value_cents"]

    now = _now()
    case = {
        "id": db.new_id(),
        "producer_id": producer_id,
        "client_id": client_id,
        "existing_contract_id": existing_contract_id,
        "exchange_type": exchange_type,
        "exchange_amount_cents": exchange_amount_cents,
        "new_product_code": new_product_code,
        "new_product_surrender_years": new_product_surrender_years,
        "new_product_bonus_bps": new_product_bonus_bps,
        "new_product_annual_fee_bps": new_product_annual_fee_bps,
        "status": "DRAFT",
        "submitted_at": None,
        "reviewed_by_id": None,
        "approved_by_id": None,
        "free_look_started_at": None,
        "free_look_deadline_date": None,
        "completed_at": None,
        "rescinded_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.cases[case["id"]] = case
    return success_object(case_view(case), 201)


@bp.route("/cases/<cid>", methods=["GET"])
def get_case(cid):
    require_roles(*ALL_ROLES)
    case = lookup_or_404(db.cases, cid, "ExchangeCase")
    return success_object(case_view(case), 200)


@bp.route("/cases", methods=["GET"])
def list_cases():
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination()
    producer_id = request.args.get("producer_id")
    client_id = request.args.get("client_id")
    existing_contract_id = request.args.get("existing_contract_id")
    status = request.args.get("status")
    items = list(db.cases.values())
    if producer_id:
        items = [c for c in items if c["producer_id"] == producer_id]
    if client_id:
        items = [c for c in items if c["client_id"] == client_id]
    if existing_contract_id:
        items = [c for c in items if c["existing_contract_id"] == existing_contract_id]
    if status:
        items = [c for c in items if c["status"] == status]
    page, total = apply_pagination(items, limit, offset)
    return success_list([case_view(c) for c in page], limit, offset, total, 200)


# ---------------------------------------------------------------------------
# Case lifecycle actions
# ---------------------------------------------------------------------------

@bp.route("/cases/<cid>/submit", methods=["POST"])
def submit_case(cid):
    user_id, role = require_roles("Producer")
    case = lookup_or_404(db.cases, cid, "ExchangeCase")
    _check_case_ownership(case, user_id, role)

    # State legality: case must be DRAFT
    if case["status"] != "DRAFT":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Case must be in DRAFT to submit",
            409,
        )

    contract = db.contracts[case["existing_contract_id"]]
    client = db.clients[case["client_id"]]
    producer = db.producers[case["producer_id"]]

    # State gate: contract must be IN_FORCE (special error per PRD §2.8 rung 6)
    if contract["status"] != "IN_FORCE":
        raise ApiError(
            ERR_CONTRACT_NOT_IN_FORCE,
            "Case submit requires the ExistingContract to be IN_FORCE",
            409,
        )

    # Business rules (§3.2): order fixed by PRD prose
    # 3rd: producer not suspended
    if producer["status"] == "SUSPENDED":
        raise ApiError(
            ERR_PRODUCER_SUSPENDED,
            "SUSPENDED producer attempts to submit a case",
            409,
        )

    now_dt = _now_dt()
    # 4th: client cooling-off
    if client["last_rescinded_at"] is not None:
        last_rescinded_dt = db.parse_iso(client["last_rescinded_at"])
        if now_dt < last_rescinded_dt + timedelta(days=COOLING_OFF_DAYS_AFTER_RESCISSION):
            raise ApiError(
                ERR_COOLING_OFF_ACTIVE,
                "Client's most recent rescission is fewer than 30 days before the new submission",
                409,
            )

    # 5th: anti-churn
    if contract["last_exchange_completed_at"] is not None:
        last_exchange_dt = db.parse_iso(contract["last_exchange_completed_at"])
        if now_dt < last_exchange_dt + timedelta(days=ANTI_CHURN_WINDOW_DAYS):
            raise ApiError(
                ERR_CONTRACT_EXCHANGED_WITHIN_12M,
                "Contract was itself acquired via a completed exchange fewer than 365 days before the new submission",
                409,
            )

    # 6th: occupation
    for other in db.cases.values():
        if other["id"] == case["id"]:
            continue
        if other["existing_contract_id"] != contract["id"]:
            continue
        if other["status"] not in TERMINAL_CASE_STATES:
            raise ApiError(
                ERR_CONTRACT_EXCHANGE_IN_PROGRESS,
                "Another non-terminal ExchangeCase already occupies the contract",
                409,
            )

    # 7th: PARTIAL bounds
    if case["exchange_type"] == "PARTIAL":
        amt = case["exchange_amount_cents"]
        if amt < MIN_PARTIAL_CENTS:
            raise ApiError(
                ERR_PARTIAL_BELOW_MINIMUM,
                "PARTIAL exchange_amount_cents below MIN_PARTIAL_CENTS (100000)",
                409,
            )
        if amt >= contract["account_value_cents"]:
            raise ApiError(
                ERR_PARTIAL_AMOUNT_INVALID,
                "PARTIAL exchange_amount_cents >= contract account_value_cents",
                409,
            )

    # Success path
    now = _now()
    case["status"] = "SUBMITTED"
    case["submitted_at"] = now
    _bump(case, now)
    churn.append_event(producer["id"], case["id"], "CASE_SUBMITTED")
    churn.evaluate_producer(producer)
    return success_object(case_view(case), 200)


@bp.route("/cases/<cid>/withdraw", methods=["POST"])
def withdraw_case(cid):
    user_id, role = require_roles("Producer")
    case = lookup_or_404(db.cases, cid, "ExchangeCase")
    _check_case_ownership(case, user_id, role)
    if case["status"] not in WITHDRAWABLE_STATES:
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Case may only be withdrawn before funds are requested",
            409,
        )
    was_draft = case["status"] == "DRAFT"
    now = _now()
    case["status"] = "WITHDRAWN"
    _bump(case, now)
    if not was_draft:
        producer = db.producers[case["producer_id"]]
        churn.append_event(producer["id"], case["id"], "CASE_WITHDRAWN")
        churn.recompute_counters(producer)
    return success_object(case_view(case), 200)


@bp.route("/cases/<cid>/start_review", methods=["POST"])
def start_review(cid):
    require_roles("SuitabilityReviewer")
    case = lookup_or_404(db.cases, cid, "ExchangeCase")
    if case["status"] != "SUBMITTED":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Case must be SUBMITTED to start review",
            409,
        )
    case["status"] = "SUITABILITY_REVIEW"
    _bump(case, _now())
    return success_object(case_view(case), 200)


@bp.route("/cases/<cid>/request_info", methods=["POST"])
def request_info(cid):
    user_id, role = require_roles("SuitabilityReviewer")
    case = lookup_or_404(db.cases, cid, "ExchangeCase")
    body = get_json_body()
    rationale = require_str(body, "rationale")
    if case["status"] != "SUITABILITY_REVIEW":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Case must be in SUITABILITY_REVIEW to request info",
            409,
        )
    case["status"] = "INFO_REQUESTED"
    _bump(case, _now())
    _append_review_decision(case["id"], "SUITABILITY", user_id, "REQUEST_INFO", rationale)
    return success_object(case_view(case), 200)


@bp.route("/cases/<cid>/recommend", methods=["POST"])
def recommend(cid):
    user_id, role = require_roles("SuitabilityReviewer")
    case = lookup_or_404(db.cases, cid, "ExchangeCase")
    body = get_json_body()
    rationale = require_str(body, "rationale")
    if case["status"] != "SUITABILITY_REVIEW":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Case must be in SUITABILITY_REVIEW to recommend",
            409,
        )
    # 1st: all three required doc types VERIFIED
    verified_types = {
        d["doc_type"]
        for d in db.documents.values()
        if d["case_id"] == case["id"] and d["status"] == "VERIFIED"
    }
    if not REQUIRED_DOC_TYPES.issubset(verified_types):
        raise ApiError(
            ERR_REQUIRED_DOCUMENTS_INCOMPLETE,
            "Recommend attempted without all three required doc types VERIFIED",
            409,
        )
    # 2nd: FINAL analysis exists
    has_final = any(
        a["case_id"] == case["id"] and a["status"] == "FINAL"
        for a in db.analyses.values()
    )
    if not has_final:
        raise ApiError(
            ERR_ANALYSIS_MISSING,
            "Recommend attempted without a FINAL ComparisonAnalysis",
            409,
        )
    case["status"] = "PENDING_PRINCIPAL"
    case["reviewed_by_id"] = user_id
    _bump(case, _now())
    _append_review_decision(case["id"], "SUITABILITY", user_id, "APPROVE", rationale)
    return success_object(case_view(case), 200)


@bp.route("/cases/<cid>/reject", methods=["POST"])
def reject(cid):
    user_id, role = require_roles("SuitabilityReviewer", "Principal")
    case = lookup_or_404(db.cases, cid, "ExchangeCase")
    body = get_json_body()
    rationale = require_str(body, "rationale")

    # Reviewer rejects from SUITABILITY_REVIEW; principal from PENDING_PRINCIPAL
    if role == "SuitabilityReviewer":
        if case["status"] != "SUITABILITY_REVIEW":
            raise ApiError(
                ERR_INVALID_STATE_TRANSITION,
                "Reviewer may reject only from SUITABILITY_REVIEW",
                409,
            )
        stage = "SUITABILITY"
    else:  # Principal
        if case["status"] != "PENDING_PRINCIPAL":
            raise ApiError(
                ERR_INVALID_STATE_TRANSITION,
                "Principal may reject only from PENDING_PRINCIPAL",
                409,
            )
        stage = "PRINCIPAL"

    case["status"] = "REJECTED"
    _bump(case, _now())
    _append_review_decision(case["id"], stage, user_id, "REJECT", rationale)
    producer = db.producers[case["producer_id"]]
    churn.append_event(producer["id"], case["id"], "CASE_REJECTED")
    churn.recompute_counters(producer)
    return success_object(case_view(case), 200)


@bp.route("/cases/<cid>/approve", methods=["POST"])
def approve(cid):
    user_id, role = require_roles("Principal")
    case = lookup_or_404(db.cases, cid, "ExchangeCase")
    body = get_json_body()
    rationale = require_str(body, "rationale")
    if case["status"] != "PENDING_PRINCIPAL":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Case must be in PENDING_PRINCIPAL to approve",
            409,
        )
    # Segregation of duties
    if user_id == case["reviewed_by_id"]:
        raise ApiError(
            ERR_DUTY_SEGREGATION_VIOLATION,
            "Approving principal's X-User-ID equals the recommending reviewer's id",
            409,
        )
    case["status"] = "APPROVED"
    case["approved_by_id"] = user_id
    _bump(case, _now())
    _append_review_decision(case["id"], "PRINCIPAL", user_id, "APPROVE", rationale)
    return success_object(case_view(case), 200)


@bp.route("/cases/<cid>/request_funds", methods=["POST"])
def request_funds(cid):
    require_roles("OperationsDesk")
    case = lookup_or_404(db.cases, cid, "ExchangeCase")
    if case["status"] != "APPROVED":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Case must be APPROVED to request funds",
            409,
        )
    contract = db.contracts[case["existing_contract_id"]]
    now_iso = db.now_iso()
    now_dt = db.parse_iso(now_iso)

    # Compute the at-settlement surrender charge at request time
    if case["exchange_type"] == "FULL":
        exchange_base = contract["account_value_cents"]
    else:
        exchange_base = case["exchange_amount_cents"]
    settlement_dt = now_dt + timedelta(days=SETTLEMENT_LAG_DAYS)
    pct_settlement = surrender_pct_bps(
        contract["surrender_schedule"], contract["issue_date"], settlement_dt
    )
    charge = surrender_charge_cents(exchange_base, pct_settlement)
    amount = exchange_base - charge

    # Tax basis allocation (multiply-then-divide; FULL transfers all)
    if case["exchange_type"] == "FULL":
        basis_transferred = contract["tax_basis_cents"]
    else:
        basis_transferred = (
            contract["tax_basis_cents"] * case["exchange_amount_cents"]
        ) // contract["account_value_cents"]

    now = _now()
    transfer = {
        "id": db.new_id(),
        "case_id": case["id"],
        "amount_cents": amount,
        "surrender_charge_cents": charge,
        "basis_transferred_cents": basis_transferred,
        "pre_exchange_value_cents": contract["account_value_cents"],
        "pre_exchange_basis_cents": contract["tax_basis_cents"],
        "status": "REQUESTED",
        "requested_at": now,
        "received_at": None,
        "returned_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.transfers[transfer["id"]] = transfer

    case["status"] = "FUNDS_REQUESTED"
    _bump(case, now)

    contract["status"] = "SURRENDER_PENDING"
    _bump(contract, now)

    return success_object(transfer_view(transfer), 201)


@bp.route("/cases/<cid>/confirm_delivery", methods=["POST"])
def confirm_delivery(cid):
    require_roles("OperationsDesk")
    case = lookup_or_404(db.cases, cid, "ExchangeCase")
    if case["status"] != "FUNDS_RECEIVED":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Case must be FUNDS_RECEIVED to confirm delivery",
            409,
        )
    now_dt = _now_dt()
    now = _now()
    client = db.clients[case["client_id"]]
    case["status"] = "IN_FREE_LOOK"
    case["free_look_started_at"] = now
    case["free_look_deadline_date"] = free_look_deadline_date(now_dt, client["is_senior"])
    _bump(case, now)
    return success_object(case_view(case), 200)


@bp.route("/cases/<cid>/complete", methods=["POST"])
def complete(cid):
    require_roles("OperationsDesk")
    case = lookup_or_404(db.cases, cid, "ExchangeCase")
    if case["status"] != "IN_FREE_LOOK":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Case must be IN_FREE_LOOK to complete",
            409,
        )
    now_dt = _now_dt()
    now_date = now_dt.date()
    deadline = case["free_look_deadline_date"]
    from datetime import date as _date
    deadline_date = _date.fromisoformat(deadline)
    if not (now_date > deadline_date):
        raise ApiError(
            ERR_FREE_LOOK_STILL_ACTIVE,
            "Complete attempted on or before free_look_deadline_date",
            409,
        )
    now = _now()
    case["status"] = "COMPLETED"
    case["completed_at"] = now
    _bump(case, now)

    contract = db.contracts[case["existing_contract_id"]]
    contract["last_exchange_completed_at"] = now
    _bump(contract, now)

    producer = db.producers[case["producer_id"]]
    churn.append_event(producer["id"], case["id"], "EXCHANGE_COMPLETED")
    churn.evaluate_producer(producer)
    return success_object(case_view(case), 200)


@bp.route("/cases/<cid>/rescind", methods=["POST"])
def rescind(cid):
    user_id, role = require_roles("Producer", "CarrierAdmin")
    case = lookup_or_404(db.cases, cid, "ExchangeCase")
    # Ownership check only applies to Producer-role callers (PRD §3.7)
    if role == "Producer":
        _check_case_ownership(case, user_id, role)
    if case["status"] != "IN_FREE_LOOK":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Case must be IN_FREE_LOOK to rescind",
            409,
        )
    now_dt = _now_dt()
    now_date = now_dt.date()
    from datetime import date as _date
    deadline_date = _date.fromisoformat(case["free_look_deadline_date"])
    if not (now_date <= deadline_date):
        raise ApiError(
            ERR_FREE_LOOK_EXPIRED,
            "Rescind attempted after free_look_deadline_date",
            409,
        )

    now = _now()
    case["status"] = "RESCINDED"
    case["rescinded_at"] = now
    _bump(case, now)

    # Transfer cascade: RECEIVED -> RETURNED
    transfer = None
    for t in db.transfers.values():
        if t["case_id"] == case["id"] and t["status"] == "RECEIVED":
            transfer = t
            break
    if transfer is not None:
        transfer["status"] = "RETURNED"
        transfer["returned_at"] = now
        _bump(transfer, now)

        # Contract restore from transfer snapshots
        contract = db.contracts[case["existing_contract_id"]]
        contract["status"] = "IN_FORCE"
        contract["account_value_cents"] = transfer["pre_exchange_value_cents"]
        contract["tax_basis_cents"] = transfer["pre_exchange_basis_cents"]
        _bump(contract, now)

    # Client stamp
    client = db.clients[case["client_id"]]
    client["last_rescinded_at"] = now
    _bump(client, now)

    producer = db.producers[case["producer_id"]]
    churn.append_event(producer["id"], case["id"], "EXCHANGE_RESCINDED")
    churn.evaluate_producer(producer)
    return success_object(case_view(case), 200)


# ---------------------------------------------------------------------------
# Documents (nested under a case)
# ---------------------------------------------------------------------------

@bp.route("/cases/<cid>/documents", methods=["POST"])
def submit_document(cid):
    user_id, role = require_roles("Producer")
    case = lookup_or_404(db.cases, cid, "ExchangeCase")
    _check_case_ownership(case, user_id, role)
    body = get_json_body()
    doc_type = require_enum(body, "doc_type", DOC_TYPES)

    # State check: case must be in an allowed state
    if case["status"] not in ALLOWED_DOC_CASE_STATES:
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Documents may only be submitted while the case is DRAFT, SUBMITTED, SUITABILITY_REVIEW, or INFO_REQUESTED",
            409,
        )

    # Locked check: a VERIFIED doc of this type cannot be resubmitted
    for d in db.documents.values():
        if d["case_id"] == case["id"] and d["doc_type"] == doc_type and d["status"] == "VERIFIED":
            raise ApiError(
                ERR_DOCUMENT_LOCKED,
                "Resubmitting a doc_type that already has a VERIFIED document",
                409,
            )

    now = _now()
    # If there's an existing REJECTED doc of this type, resubmit it (revision += 1)
    existing_rejected = None
    for d in db.documents.values():
        if d["case_id"] == case["id"] and d["doc_type"] == doc_type and d["status"] == "REJECTED":
            existing_rejected = d
            break

    if existing_rejected is not None:
        doc = existing_rejected
        doc["status"] = "SUBMITTED"
        doc["revision"] += 1
        doc["rejection_reason"] = None
        _bump(doc, now)
    else:
        doc = {
            "id": db.new_id(),
            "case_id": case["id"],
            "doc_type": doc_type,
            "status": "SUBMITTED",
            "revision": 1,
            "rejection_reason": None,
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        db.documents[doc["id"]] = doc

    # INFO_REQUESTED case returns to SUITABILITY_REVIEW on resubmission
    if case["status"] == "INFO_REQUESTED":
        case["status"] = "SUITABILITY_REVIEW"
        _bump(case, now)

    return success_object(document_view(doc), 201)


@bp.route("/cases/<cid>/documents", methods=["GET"])
def list_documents(cid):
    require_roles(*ALL_ROLES)
    case = lookup_or_404(db.cases, cid, "ExchangeCase")
    limit, offset = parse_pagination()
    doc_type = request.args.get("doc_type")
    status = request.args.get("status")
    items = [d for d in db.documents.values() if d["case_id"] == case["id"]]
    if doc_type:
        items = [d for d in items if d["doc_type"] == doc_type]
    if status:
        items = [d for d in items if d["status"] == status]
    page, total = apply_pagination(items, limit, offset)
    return success_list([document_view(d) for d in page], limit, offset, total, 200)


# ---------------------------------------------------------------------------
# Comparison analyses (OCC-guarded)
# ---------------------------------------------------------------------------

@bp.route("/cases/<cid>/comparison-analyses", methods=["POST"])
def create_analysis(cid):
    user_id, role = require_roles("SuitabilityReviewer")
    case = lookup_or_404(db.cases, cid, "ExchangeCase")
    body = get_json_body()

    # State check precedes version check (PRD §3.4)
    if case["status"] not in ("SUITABILITY_REVIEW", "INFO_REQUESTED"):
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Comparison analysis requires case in SUITABILITY_REVIEW or INFO_REQUESTED",
            409,
        )

    # Body shape
    if "expected_case_version" not in body:
        raise ApiError(ERR_INVALID_REQUEST, "expected_case_version is required", 400)
    expected_case_version = require_int(body, "expected_case_version", min_value=0)
    assumed_old_growth_bps = require_int(body, "assumed_old_growth_bps")
    assumed_new_growth_bps = require_int(body, "assumed_new_growth_bps")

    # OCC check
    if expected_case_version != case["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            "expected_case_version does not match the case's current version (OCC)",
            412,
        )

    contract = db.contracts[case["existing_contract_id"]]
    analysis_dt = _now_dt()
    now = _now()

    fields = compute_analysis_fields(
        case, contract, analysis_dt, assumed_old_growth_bps, assumed_new_growth_bps
    )

    # Find prior FINAL analysis on this case to supersede
    prior_final = None
    for a in db.analyses.values():
        if a["case_id"] == case["id"] and a["status"] == "FINAL":
            prior_final = a
            break

    analysis = {
        "id": db.new_id(),
        "case_id": case["id"],
        "assumed_old_growth_bps": assumed_old_growth_bps,
        "assumed_new_growth_bps": assumed_new_growth_bps,
        "analysis_date": now,
        "exchange_base_cents": fields["exchange_base_cents"],
        "surrender_pct_bps_today": fields["surrender_pct_bps_today"],
        "surrender_charge_today_cents": fields["surrender_charge_today_cents"],
        "surrender_pct_bps_at_settlement": fields["surrender_pct_bps_at_settlement"],
        "surrender_charge_at_settlement_cents": fields["surrender_charge_at_settlement_cents"],
        "amount_received_cents": fields["amount_received_cents"],
        "bonus_credit_cents": fields["bonus_credit_cents"],
        "benefit_loss_cents": fields["benefit_loss_cents"],
        "net_replacement_cost_cents": fields["net_replacement_cost_cents"],
        "break_even_years": fields["break_even_years"],
        "basis_transferred_cents": fields["basis_transferred_cents"],
        "basis_remaining_cents": fields["basis_remaining_cents"],
        "status": "FINAL",
        "supersedes_analysis_id": prior_final["id"] if prior_final else None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.analyses[analysis["id"]] = analysis

    if prior_final is not None:
        prior_final["status"] = "SUPERSEDED"
        _bump(prior_final, now)

    # Side effect: creating an analysis bumps the case version by 1
    _bump(case, now)

    return success_object(analysis_view(analysis), 201)


@bp.route("/cases/<cid>/comparison-analyses", methods=["GET"])
def list_analyses(cid):
    require_roles(*ALL_ROLES)
    case = lookup_or_404(db.cases, cid, "ExchangeCase")
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = [a for a in db.analyses.values() if a["case_id"] == case["id"]]
    if status:
        items = [a for a in items if a["status"] == status]
    page, total = apply_pagination(items, limit, offset)
    return success_list([analysis_view(a) for a in page], limit, offset, total, 200)


# ---------------------------------------------------------------------------
# Funds transfers (nested under a case)
# ---------------------------------------------------------------------------

@bp.route("/cases/<cid>/funds-transfers", methods=["GET"])
def list_transfers(cid):
    require_roles(*ALL_ROLES)
    case = lookup_or_404(db.cases, cid, "ExchangeCase")
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = [t for t in db.transfers.values() if t["case_id"] == case["id"]]
    if status:
        items = [t for t in items if t["status"] == status]
    page, total = apply_pagination(items, limit, offset)
    return success_list([transfer_view(t) for t in page], limit, offset, total, 200)


# ---------------------------------------------------------------------------
# Audit listings
# ---------------------------------------------------------------------------

@bp.route("/cases/<cid>/activity-events", methods=["GET"])
def list_case_activity_events(cid):
    require_roles(*ALL_ROLES)
    case = lookup_or_404(db.cases, cid, "ExchangeCase")
    limit, offset = parse_pagination()
    event_type = request.args.get("event_type")
    items = [e for e in db.activity_events if e["case_id"] == case["id"]]
    if event_type:
        items = [e for e in items if e["event_type"] == event_type]
    page, total = apply_pagination(items, limit, offset)
    return success_list([activity_event_view(e) for e in page], limit, offset, total, 200)


@bp.route("/cases/<cid>/review-decisions", methods=["GET"])
def list_review_decisions(cid):
    require_roles(*ALL_ROLES)
    case = lookup_or_404(db.cases, cid, "ExchangeCase")
    limit, offset = parse_pagination()
    stage = request.args.get("stage")
    items = [r for r in db.review_decisions if r["case_id"] == case["id"]]
    if stage:
        items = [r for r in items if r["stage"] == stage]
    page, total = apply_pagination(items, limit, offset)
    return success_list([review_decision_view(r) for r in page], limit, offset, total, 200)
