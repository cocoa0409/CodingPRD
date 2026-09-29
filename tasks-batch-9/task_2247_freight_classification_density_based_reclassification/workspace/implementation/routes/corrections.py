"""Correction notices, the ops sweep, disputes, credit memos."""
from datetime import timedelta

from flask import Blueprint

import auth
import clock
import db
import response
import serialize
import validation
from constants import (
    CLAIM_BASES,
    DISPUTE_STATUSES,
    INTEREST_CAP_CENTS,
    INTEREST_RATE_PER_ROUND,
    MAX_DISPUTE_ROUNDS,
    MAX_SUPPLEMENT_REQUESTS,
    MIN_DISPUTE_DOCS,
    MIN_EVIDENCE_BUNDLE,
    NOTICE_STATUSES,
    NOTICE_TYPES,
    OUTCOMES,
    RECLASS_FEE_CENTS,
    REWEIGH_FEE_CENTS,
    SUPPLEMENT_EXTENSION_DAYS,
)
from errors import fail
from routes import _helpers as h
from services import customers, notices, rating
from util import D, rhu_int

bp = Blueprint("corrections", __name__)

NOTICE_READ_ROLES = ("ClassificationAuditor", "DisputeReviewer", "Shipper", "PricingAnalyst")
DISPUTE_READ_ROLES = ("Shipper", "DisputeReviewer", "ClassificationAuditor", "PricingAnalyst")
MEMO_READ_ROLES = ("PricingAnalyst", "Shipper", "DisputeReviewer")


def _customer_of(notice):
    shipment = db.get("shipments", notice["shipment_id"])
    if shipment is None:
        return None, None
    return shipment, db.get("customers", shipment["customer_id"])


# ---------------------------------------------------------------------------
# correction notices (PRD 3.7)
# ---------------------------------------------------------------------------
@bp.post("/ltl/correction-notices")
def create_correction_notice():
    auth.authenticate(("ClassificationAuditor",))
    body = validation.body()
    shipment = validation.fk(body, "shipment_id", "shipments", "ERR_SHIPMENT_NOT_FOUND")
    capture = validation.fk(
        body, "basis_capture_event_id", "capture_events", "ERR_CAPTURE_EVENT_NOT_FOUND",
        required=False,
    )
    superseded = validation.fk(
        body, "supersedes_notice_id", "correction_notices", "ERR_CORRECTION_NOTICE_NOT_FOUND",
        required=False,
    )
    if shipment is None:
        validation.req_str(body, "shipment_id")

    notice_type = validation.req_enum(body, "notice_type", NOTICE_TYPES)
    expected = validation.req_int(body, "expected_shipment_version")

    if expected != int(shipment["version"]):
        fail(
            "ERR_STALE_SHIPMENT_VERSION",
            "Shipment version is %s, not %s." % (shipment["version"], expected),
        )

    if superseded is not None:
        if superseded["shipment_id"] != shipment["id"]:
            fail(
                "ERR_INVALID_STATE_TRANSITION",
                "The superseded notice belongs to a different shipment.",
            )
        if superseded["status"] != "DRAFT":
            fail(
                "ERR_INVALID_STATE_TRANSITION",
                "Only a DRAFT notice may be superseded; this one is %s." % superseded["status"],
            )

    allowed = {superseded["id"]} if superseded is not None else set()
    for open_notice in notices.open_notices(shipment["id"]):
        if open_notice["id"] not in allowed:
            fail("ERR_OPEN_NOTICE_EXISTS", "The shipment already carries an open notice.")

    has_capture_basis = capture is not None and capture["shipment_id"] == shipment["id"]
    has_finding_basis = bool(rating.accepted_findings_of_shipment(shipment))
    if not has_capture_basis and not has_finding_basis:
        fail(
            "ERR_NO_RECLASS_BASIS",
            "A manual notice needs a capture of its own shipment or an accepted finding.",
        )

    row = notices.new_notice_row(
        shipment,
        notice_type,
        "AUDITOR_MANUAL",
        basis_capture_event_id=capture["id"] if capture is not None else None,
        supersedes_notice_id=superseded["id"] if superseded is not None else None,
    )

    if superseded is not None:
        superseded["status"] = "VOID"
        db.touch(superseded)

    notices.recompute_open_notice_count(shipment)
    db.touch(shipment)
    return response.created(serialize.correction_notice(row))


@bp.get("/ltl/correction-notices/<notice_id>")
def read_correction_notice(notice_id):
    auth.authenticate(NOTICE_READ_ROLES)
    row = validation.path_row("correction_notices", notice_id, "ERR_CORRECTION_NOTICE_NOT_FOUND")
    shipment = db.get("shipments", row["shipment_id"])
    if shipment is not None:
        auth.require_shipper_owner(shipment["customer_id"])
    return response.ok(serialize.correction_notice(row))


@bp.get("/ltl/correction-notices")
def list_correction_notices():
    auth.authenticate(NOTICE_READ_ROLES)
    rows = db.all_rows("correction_notices")
    if auth.is_shipper():
        me = auth.user_id()
        rows = [
            row
            for row in rows
            if (db.get("shipments", row["shipment_id"]) or {}).get("customer_id") == me
        ]
    rows = h.apply_filters(
        rows,
        (
            ("shipment_id", "shipment_id", None),
            ("status", "status", NOTICE_STATUSES),
            ("basis_capture_event_id", "basis_capture_event_id", None),
            ("supersedes_notice_id", "supersedes_notice_id", None),
        ),
    )
    return h.paged(rows, serialize.correction_notice)


@bp.post("/ltl/correction-notices/<notice_id>/issue")
def issue_correction_notice(notice_id):
    auth.authenticate(("ClassificationAuditor",))
    row = validation.path_row("correction_notices", notice_id, "ERR_CORRECTION_NOTICE_NOT_FOUND")
    if row["status"] != "DRAFT":
        fail("ERR_INVALID_STATE_TRANSITION", "Notice is %s, not DRAFT." % row["status"])

    shipment, customer = _customer_of(row)
    if shipment is None:
        fail("ERR_SHIPMENT_NOT_FOUND", "The notice's shipment no longer exists.")
    if shipment["billing_status"] == "UNBILLED":
        fail("ERR_SHIPMENT_NOT_BILLED", "The shipment has not been billed yet.")
    if shipment["billing_status"] == "CLOSED":
        fail("ERR_INVALID_STATE_TRANSITION", "The shipment is CLOSED.")
    if customer is not None and customer["billing_posture"] == "CLOSED":
        fail("ERR_CUSTOMER_CLOSED", "The customer account is CLOSED.")

    notices.refresh_notice_figures(shipment, row)
    if int(row["evidence_bundle_count"] or 0) < MIN_EVIDENCE_BUNDLE:
        fail(
            "ERR_INSUFFICIENT_EVIDENCE",
            "The notice needs at least %d evidence item(s)." % MIN_EVIDENCE_BUNDLE,
        )
    if int(row["final_delta_cents"] or 0) == 0:
        fail("ERR_ZERO_DELTA_NOTICE", "A notice with a zero final delta cannot be issued.")

    now = clock.now()
    row["applied_delta_cents"] = int(row["final_delta_cents"])
    row["inspection_fee_cents"] = (
        RECLASS_FEE_CENTS if row["notice_type"] in ("RECLASS", "BOTH") else REWEIGH_FEE_CENTS
    )
    row["status"] = "ISSUED"
    row["issued_at"] = now
    row["issued_by_user_id"] = auth.user_id()
    db.touch(row)

    shipment["class_status"] = "RECLASSED"
    shipment["billing_status"] = "REBILLED"
    db.touch(shipment)
    notices.recompute_open_notice_count(shipment)
    notices.recompute_assessed_total(shipment)

    if customer is not None:
        customers.recompute_record(customer)
        customers.apply_education_threshold(customer)
        window_days = int(customer["dispute_window_days"])
    else:
        window_days = 30

    row["dispute_deadline_at"] = now + timedelta(
        days=window_days + SUPPLEMENT_EXTENSION_DAYS * int(row["supplement_request_count"] or 0)
    )
    db.touch(row)
    return response.ok(serialize.correction_notice(row))


@bp.post("/ltl/notice-sweeps")
def sweep_notices():
    auth.authenticate(("PricingAnalyst",))
    validation.body()
    now = clock.now()
    swept = []
    for notice in db.all_rows("correction_notices", lambda n: n["status"] == "ISSUED"):
        deadline = notice.get("dispute_deadline_at")
        if deadline is None or not now > deadline:
            continue
        if db.all_rows("disputes", lambda d: d["correction_notice_id"] == notice["id"]):
            continue
        notice["status"] = "UPHELD"
        notice["resolved_at"] = now
        db.touch(notice)
        swept.append(notice)

    seen = set()
    for notice in swept:
        shipment, customer = _customer_of(notice)
        if shipment is not None:
            notices.recompute_open_notice_count(shipment)
        if customer is not None and customer["id"] not in seen:
            seen.add(customer["id"])
            customers.recompute_record(customer)
    return response.ok(
        {"swept_count": len(swept), "upheld_notice_ids": [notice["id"] for notice in swept]}
    )


# ---------------------------------------------------------------------------
# disputes (PRD 3.9)
# ---------------------------------------------------------------------------
@bp.post("/ltl/disputes")
def create_dispute():
    auth.authenticate(("Shipper",))
    body = validation.body()
    notice = validation.fk(
        body, "correction_notice_id", "correction_notices", "ERR_CORRECTION_NOTICE_NOT_FOUND"
    )
    if notice is None:
        validation.req_str(body, "correction_notice_id")

    shipment, customer = _customer_of(notice)
    if shipment is not None:
        auth.require_owner(shipment["customer_id"])

    claim_basis = validation.req_enum(body, "claim_basis", CLAIM_BASES)
    doc_count = validation.req_int(body, "evidence_doc_count", minimum=0)
    raw_class = body.get("claimed_class_code")
    if raw_class is not None and not validation.is_number(raw_class):
        fail("ERR_INVALID_REQUEST", "claimed_class_code must be a number.")
    claimed_class = (
        validation.as_class_code(raw_class, "claimed_class_code") if raw_class is not None else None
    )

    if notice["status"] != "ISSUED":
        fail("ERR_NOTICE_NOT_DISPUTABLE", "Notice is %s, not ISSUED." % notice["status"])
    if customer is not None and customer["education_status"] == "REQUIRED":
        fail("ERR_EDUCATION_HOLD", "Mandatory classification education is outstanding.")
    if doc_count < MIN_DISPUTE_DOCS:
        fail(
            "ERR_INSUFFICIENT_EVIDENCE",
            "A dispute needs at least %d document(s)." % MIN_DISPUTE_DOCS,
        )
    deadline = notice.get("dispute_deadline_at")
    if deadline is not None and clock.now() > deadline:
        fail("ERR_DISPUTE_WINDOW_CLOSED", "The dispute window has closed.")
    if int(notice["dispute_round_count"] or 0) >= MAX_DISPUTE_ROUNDS:
        fail("ERR_MAX_DISPUTE_ROUNDS", "The dispute round ceiling has been reached.")

    notice["dispute_round_count"] = int(notice["dispute_round_count"] or 0) + 1
    notice["status"] = "DISPUTED"
    db.touch(notice)

    row = db.insert(
        "disputes",
        {
            "correction_notice_id": notice["id"],
            "filed_by_customer_id": auth.user_id(),
            "round_no": int(notice["dispute_round_count"]),
            "claim_basis": claim_basis,
            "claimed_class_code": claimed_class,
            "evidence_doc_count": doc_count,
            "filed_at": clock.now(),
            "reviewer_user_id": None,
            "outcome": None,
            "outcome_class_code": None,
            "status": "OPEN",
            "resolved_at": None,
        },
    )
    return response.created(serialize.dispute(row))


@bp.get("/ltl/disputes/<dispute_id>")
def read_dispute(dispute_id):
    auth.authenticate(DISPUTE_READ_ROLES)
    row = validation.path_row("disputes", dispute_id, "ERR_DISPUTE_NOT_FOUND")
    auth.require_shipper_owner(row["filed_by_customer_id"])
    return response.ok(serialize.dispute(row))


@bp.get("/ltl/disputes")
def list_disputes():
    auth.authenticate(DISPUTE_READ_ROLES)
    rows = h.shipper_scope(db.all_rows("disputes"), "filed_by_customer_id")
    rows = h.apply_filters(
        rows,
        (
            ("correction_notice_id", "correction_notice_id", None),
            ("filed_by_customer_id", "filed_by_customer_id", None),
            ("status", "status", DISPUTE_STATUSES),
        ),
    )
    return h.paged(rows, serialize.dispute)


@bp.post("/ltl/disputes/<dispute_id>/request-supplement")
def request_supplement(dispute_id):
    auth.authenticate(("DisputeReviewer",))
    row = validation.path_row("disputes", dispute_id, "ERR_DISPUTE_NOT_FOUND")
    body = validation.body()
    validation.opt_str(body, "reason_note")

    notice = db.get("correction_notices", row["correction_notice_id"])
    if row["status"] not in ("OPEN", "SUPPLEMENTED"):
        fail("ERR_INVALID_STATE_TRANSITION", "Dispute is %s." % row["status"])
    if notice is None or notice["status"] != "DISPUTED":
        fail(
            "ERR_INVALID_STATE_TRANSITION",
            "The notice is not awaiting review.",
        )
    if auth.user_id() == notice.get("issued_by_user_id"):
        fail("ERR_SOD_VIOLATION", "The issuing auditor may not review this dispute.")
    if int(notice["supplement_request_count"] or 0) >= MAX_SUPPLEMENT_REQUESTS:
        fail("ERR_MAX_DISPUTE_ROUNDS", "The supplement request ceiling has been reached.")

    row["status"] = "SUPPLEMENT_REQUESTED"
    if row.get("reviewer_user_id") is None:
        row["reviewer_user_id"] = auth.user_id()
    db.touch(row)

    notice["status"] = "EVIDENCE_REQUESTED"
    notice["supplement_request_count"] = int(notice["supplement_request_count"] or 0) + 1
    if notice.get("dispute_deadline_at") is not None:
        notice["dispute_deadline_at"] = notice["dispute_deadline_at"] + timedelta(
            days=SUPPLEMENT_EXTENSION_DAYS
        )
    db.touch(notice)
    return response.ok(serialize.dispute(row))


@bp.post("/ltl/disputes/<dispute_id>/supplement")
def supplement_dispute(dispute_id):
    auth.authenticate(("Shipper",))
    row = validation.path_row("disputes", dispute_id, "ERR_DISPUTE_NOT_FOUND")
    auth.require_owner(row["filed_by_customer_id"])
    body = validation.body()
    additional = validation.req_int(body, "additional_doc_count", minimum=0)

    notice = db.get("correction_notices", row["correction_notice_id"])
    if row["status"] != "SUPPLEMENT_REQUESTED":
        fail("ERR_INVALID_STATE_TRANSITION", "Dispute is %s." % row["status"])
    if notice is None or notice["status"] != "EVIDENCE_REQUESTED":
        fail("ERR_INVALID_STATE_TRANSITION", "The notice is not awaiting supplemental evidence.")
    if int(notice["dispute_round_count"] or 0) >= MAX_DISPUTE_ROUNDS:
        fail("ERR_MAX_DISPUTE_ROUNDS", "The dispute round ceiling has been reached.")

    notice["dispute_round_count"] = int(notice["dispute_round_count"] or 0) + 1
    notice["status"] = "DISPUTED"
    db.touch(notice)

    row["status"] = "SUPPLEMENTED"
    row["evidence_doc_count"] = int(row["evidence_doc_count"] or 0) + additional
    row["round_no"] = int(notice["dispute_round_count"])
    db.touch(row)
    return response.ok(serialize.dispute(row))


@bp.post("/ltl/disputes/<dispute_id>/resolve")
def resolve_dispute(dispute_id):
    auth.authenticate(("DisputeReviewer",))
    row = validation.path_row("disputes", dispute_id, "ERR_DISPUTE_NOT_FOUND")
    body = validation.body()
    outcome = validation.req_enum(body, "outcome", OUTCOMES)
    raw_class = body.get("outcome_class_code")
    if raw_class is not None and not validation.is_number(raw_class):
        fail("ERR_INVALID_REQUEST", "outcome_class_code must be a number.")
    validation.opt_str(body, "resolution_note")
    outcome_class = (
        validation.as_class_code(raw_class, "outcome_class_code") if raw_class is not None else None
    )

    notice = db.get("correction_notices", row["correction_notice_id"])
    if row["status"] == "RESOLVED":
        fail("ERR_INVALID_STATE_TRANSITION", "The dispute is already RESOLVED.")
    if notice is None or notice["status"] not in ("DISPUTED", "EVIDENCE_REQUESTED"):
        fail("ERR_INVALID_STATE_TRANSITION", "The notice is not under dispute.")
    if auth.user_id() == notice.get("issued_by_user_id"):
        fail("ERR_SOD_VIOLATION", "The issuing auditor may not resolve this dispute.")

    shipment, customer = _customer_of(notice)
    lines = rating.lines_of(shipment["id"]) if shipment is not None else []
    reclassed = [line for line in lines if rating.is_reclassed(line)]

    if outcome == "PARTIAL":
        if outcome_class is None:
            fail("ERR_INVALID_PARTIAL_OUTCOME", "A PARTIAL resolution requires outcome_class_code.")
        for line in reclassed:
            if D(line["effective_class_code"]) == outcome_class:
                fail(
                    "ERR_INVALID_PARTIAL_OUTCOME",
                    "outcome_class_code must differ from every reclassed line's class.",
                )
    elif outcome_class is not None:
        fail(
            "ERR_INVALID_PARTIAL_OUTCOME",
            "outcome_class_code is only allowed on a PARTIAL resolution.",
        )

    now = clock.now()
    freight_credit = 0
    fee_credit = 0
    reason = None

    if outcome == "PARTIAL":
        frozen = rating.shipment_charge(shipment, "RECLASSED", lines=lines)
        substituted = rating.shipment_charge(
            shipment,
            "RECLASSED",
            class_fn=lambda line: outcome_class if rating.is_reclassed(line) else None,
            lines=lines,
        )
        freight_credit = frozen - substituted
        reason = "PARTIAL_OVERTURN"
        for line in reclassed:
            line["found_class_code"] = outcome_class
            line["effective_class_code"] = outcome_class
            db.touch(line)
        rating.recompute_line_charges(shipment)
        rating.refresh_delta_count(shipment)
        notice["status"] = "PARTIALLY_OVERTURNED"
    elif outcome == "OVERTURNED":
        freight_credit = int(notice["applied_delta_cents"] or 0)
        fee_credit = int(notice["inspection_fee_cents"] or 0)
        reason = "FULL_OVERTURN"
        for line in lines:
            rating.revert_line_to_declared(shipment, line)
            db.touch(line)
        rating.recompute_line_charges(shipment)
        rating.refresh_delta_count(shipment)
        if shipment["class_status"] == "RECLASSED":
            shipment["class_status"] = "CAPTURED"
            db.touch(shipment)
        notice["status"] = "OVERTURNED"
    else:
        notice["status"] = "UPHELD"

    notice["resolved_at"] = now
    db.touch(notice)

    row["status"] = "RESOLVED"
    row["outcome"] = outcome
    row["outcome_class_code"] = outcome_class
    row["reviewer_user_id"] = row.get("reviewer_user_id") or auth.user_id()
    row["resolved_at"] = now
    db.touch(row)

    if reason is not None:
        rounds = int(notice["dispute_round_count"] or 0)
        interest = min(
            rhu_int(D(freight_credit) * INTEREST_RATE_PER_ROUND * rounds), INTEREST_CAP_CENTS
        )
        db.insert(
            "credit_memos",
            {
                "correction_notice_id": notice["id"],
                "customer_id": shipment["customer_id"] if shipment else None,
                "reason": reason,
                "freight_credit_cents": freight_credit,
                "fee_credit_cents": fee_credit,
                "interest_credit_cents": interest,
                "amount_cents": freight_credit + fee_credit + interest,
                "issued_at": now,
            },
            versioned=False,
        )
        notices.recompute_credited_total(notice)
        if shipment is not None:
            shipment["billing_status"] = "CREDITED"
            db.touch(shipment)

    if shipment is not None:
        notices.recompute_open_notice_count(shipment)
        notices.recompute_assessed_total(shipment)
    if customer is not None:
        customers.recompute_record(customer)
    return response.ok(serialize.dispute(row))


# ---------------------------------------------------------------------------
# credit memos (read-only)
# ---------------------------------------------------------------------------
@bp.get("/ltl/credit-memos/<memo_id>")
def read_credit_memo(memo_id):
    auth.authenticate(MEMO_READ_ROLES)
    row = validation.path_row("credit_memos", memo_id, "ERR_CREDIT_MEMO_NOT_FOUND")
    auth.require_shipper_owner(row["customer_id"])
    return response.ok(serialize.credit_memo(row))


@bp.get("/ltl/credit-memos")
def list_credit_memos():
    auth.authenticate(MEMO_READ_ROLES)
    rows = h.shipper_scope(db.all_rows("credit_memos"), "customer_id")
    rows = h.apply_filters(
        rows,
        (
            ("correction_notice_id", "correction_notice_id", None),
            ("customer_id", "customer_id", None),
        ),
    )
    return h.paged(rows, serialize.credit_memo)
