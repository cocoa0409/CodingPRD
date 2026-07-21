"""Claim, receipt and adjudication endpoints (13)."""
from flask import Blueprint, g, request

import db
import middleware as mw
import response as resp
import serializers as ser
from errors import err
from services import budget, fraud, rebate

bp = Blueprint("claims", __name__)

READ_ROLES = (
    "ProgramAdmin", "ClaimsProcessor", "FinanceOfficer", "FraudAnalyst", "Dealer", "Consumer",
)
RECEIPT_READ_ROLES = ("ProgramAdmin", "ClaimsProcessor", "Dealer", "Consumer")


def _channel_ok(claimant, offer):
    if claimant["type"] == "DEALER":
        return offer["channel"] in ("DEALER", "BOTH")
    return offer["channel"] in ("CONSUMER", "BOTH")


def _state_error(claim, default_error):
    if claim["adjudication_status"] in db.CLAIM_TERMINAL_ADJ:
        return err("ERR_CLAIM_ALREADY_TERMINAL")
    return err(default_error)


# ---------------------------------------------------------------------------
# Claim CRUD
# ---------------------------------------------------------------------------
@bp.post("/api/claims")
@mw.require("Dealer", "Consumer")
def create_claim():
    data = mw.body()
    claimant_id = data.get("claimant_id")
    # ownership (step 3) precedes body-FK resolution (step 5)
    if isinstance(claimant_id, str):
        mw.owns(claimant_id)

    offer_id = data.get("offer_id")
    if not isinstance(offer_id, str) or not offer_id:
        raise err("ERR_VALIDATION", "Field 'offer_id' is required.")
    if not isinstance(claimant_id, str) or not claimant_id:
        raise err("ERR_VALIDATION", "Field 'claimant_id' is required.")
    offer = db.get_offer(offer_id)
    claimant = db.get_claimant(claimant_id)

    if offer["status"] != "PUBLISHED":
        raise err("ERR_OFFER_NOT_PUBLISHED")
    if not _channel_ok(claimant, offer):
        raise err("ERR_CHANNEL_MISMATCH")

    rec = db.base_record()
    rec.update({
        "offer_id": offer["id"],
        "claimant_id": claimant["id"],
        "adjudication_status": "DRAFT",
        "payment_status": "NONE",
        "total_units": 0,
        "provisional_rebate_cents": 0,
        "final_rebate_cents": None,
        "fraud_score_at_submit": None,
        "submitted_at": None,
        "approved_at": None,
        "denied_at": None,
        "approved_by_user_id": None,
        "denial_reason_code": None,
        "appeal_count": 0,
    })
    db.claims[rec["id"]] = rec
    return resp.created(ser.claim(rec))


@bp.get("/api/claims/<cid>")
@mw.require(*READ_ROLES)
def read_claim(cid):
    return resp.ok(ser.claim(db.get_claim(cid)))


@bp.get("/api/claims")
@mw.require(*READ_ROLES)
def list_claims():
    items = db.by_created(list(db.claims.values()))
    for field in ("claimant_id", "offer_id", "adjudication_status", "payment_status"):
        value = request.args.get(field)
        if value:
            items = [c for c in items if c[field] == value]
    return resp.paginated(items, ser.claim)


# ---------------------------------------------------------------------------
# Receipts
# ---------------------------------------------------------------------------
def _validate_lines(raw):
    if not isinstance(raw, list) or len(raw) == 0:
        raise err("ERR_VALIDATION", "Field 'lines' must be a non-empty array.")
    lines = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise err("ERR_VALIDATION", "Each line must be an object.")
        sku = entry.get("sku")
        qty = entry.get("quantity")
        price = entry.get("unit_price_cents")
        if not isinstance(sku, str) or not sku:
            raise err("ERR_VALIDATION", "Each line requires a 'sku' string.")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
            raise err("ERR_VALIDATION", "Each line requires 'quantity' greater than zero.")
        if isinstance(price, bool) or not isinstance(price, int) or price <= 0:
            raise err("ERR_VALIDATION", "Each line requires 'unit_price_cents' greater than zero.")
        lines.append({"sku": sku, "quantity": qty, "unit_price_cents": price})
    # the line ceiling is checked AFTER shape validation (PRD §2.8 step 7)
    if len(lines) > db.RECEIPT_MAX_LINES:
        raise err("ERR_RECEIPT_LIMIT_EXCEEDED")
    return lines


@bp.post("/api/claims/<cid>/receipts")
@mw.require("Dealer", "Consumer")
def create_receipt(cid):
    claim = db.get_claim(cid)
    mw.owns(claim["claimant_id"])
    data = mw.body()

    serial_number = mw.as_string(data, "serial_number")
    purchase_date = mw.as_datetime(data, "purchase_date")
    retailer_name = mw.as_string(data, "retailer_name")
    if "lines" not in data or data["lines"] is None:
        raise err("ERR_VALIDATION", "Field 'lines' is required.")
    lines = _validate_lines(data["lines"])

    if claim["adjudication_status"] != "DRAFT":
        raise err("ERR_CLAIM_NOT_DRAFT")

    rec = db.base_record()
    rec.update({
        "claim_id": claim["id"],
        "serial_number": serial_number,
        "purchase_date": purchase_date,
        "retailer_name": retailer_name,
        "lines": lines,
        "line_count": len(lines),
        "units": sum(l["quantity"] for l in lines),
        "gross_amount_cents": sum(l["quantity"] * l["unit_price_cents"] for l in lines),
        "validated": False,
        "validated_at": None,
    })
    db.receipts[rec["id"]] = rec
    return resp.created(ser.receipt(rec))


@bp.get("/api/claims/<cid>/receipts")
@mw.require(*READ_ROLES)
def list_claim_receipts(cid):
    claim = db.get_claim(cid)
    items = db.receipts_of_claim(claim["id"])
    validated = request.args.get("validated")
    if validated is not None and validated != "":
        want = str(validated).strip().lower() in ("true", "1", "yes")
        items = [r for r in items if r["validated"] == want]
    return resp.paginated(items, ser.receipt)


@bp.get("/api/receipts/<rid>")
@mw.require(*RECEIPT_READ_ROLES)
def read_receipt(rid):
    # PRD §2.1 scopes the ownership guard to seven write operations; reads are open
    # to every listed role.
    return resp.ok(ser.receipt(db.get_receipt(rid)))


@bp.post("/api/receipts/<rid>/validate")
@mw.require("ClaimsProcessor")
def validate_receipt(rid):
    receipt = db.get_receipt(rid)
    receipt["validated"] = True
    receipt["validated_at"] = db.now()
    db.touch(receipt)
    return resp.ok(ser.receipt(receipt))


# ---------------------------------------------------------------------------
# Submission gate
# ---------------------------------------------------------------------------
@bp.post("/api/claims/<cid>/submit")
@mw.require("Dealer", "Consumer")
def submit_claim(cid):
    claim = db.get_claim(cid)
    mw.owns(claim["claimant_id"])

    # (9) state
    if claim["adjudication_status"] != "DRAFT":
        raise err("ERR_CLAIM_NOT_DRAFT")

    claimant = db.get_claimant(claim["claimant_id"])
    offer = db.get_offer(claim["offer_id"])
    clock = db.now()

    # (11) claimant standing
    if claimant["status"] != "ACTIVE":
        raise err("ERR_CLAIMANT_BLOCKED")

    claim_receipts = db.receipts_of_claim(claim["id"])

    # (13) temporal windows, in the pinned internal order
    for r in claim_receipts:
        if db.whole_days(clock, r["purchase_date"]) > db.CLAIM_WINDOW_DAYS:
            raise err("ERR_CLAIM_WINDOW_EXPIRED")
    for r in claim_receipts:
        if not (offer["effective_start_date"] <= r["purchase_date"] < offer["effective_end_date"]):
            raise err("ERR_PURCHASE_OUTSIDE_OFFER_WINDOW")
    if offer["status"] == "PUBLISHED":
        pass
    elif offer["status"] == "CLOSED" and offer["closed_at"] is not None \
            and db.whole_days(clock, offer["closed_at"]) <= db.OFFER_GRACE_DAYS:
        pass
    else:
        raise err("ERR_OFFER_WINDOW_CLOSED")

    if not claim_receipts:
        raise err("ERR_VALIDATION", "The claim must carry at least one receipt.")

    # (14) referential: dedupe then channel
    if _has_duplicate_serial(claim, claim_receipts):
        claimant["duplicate_attempt_count"] += 1
        db.touch(claimant)
        raise err("ERR_DUPLICATE_RECEIPT_SERIAL")
    if not _channel_ok(claimant, offer):
        raise err("ERR_CHANNEL_MISMATCH")

    # (15) per-offer claim cap
    live = 0
    for other in db.claims_of_offer(offer["id"]):
        if other["id"] == claim["id"]:
            continue
        if other["claimant_id"] != claimant["id"]:
            continue
        if other["adjudication_status"] not in ("DRAFT", "WITHDRAWN", "VOIDED"):
            live += 1
    if live >= db.MAX_CLAIMS_PER_CLAIMANT_PER_OFFER:
        raise err("ERR_CLAIM_CAP_EXCEEDED")

    # --- apply -------------------------------------------------------------
    claim["adjudication_status"] = "SUBMITTED"
    claim["submitted_at"] = clock
    provisional, units = rebate.compute(claim, claimant, offer, "provisional")
    claim["provisional_rebate_cents"] = provisional
    claim["total_units"] = units
    db.touch(claim)

    score = fraud.heuristic_score(claimant, subject_claim=claim)
    claim["fraud_score_at_submit"] = score
    claimant["fraud_score"] = score
    db.touch(claimant)

    program = db.programs.get(offer["program_id"])
    if program is not None:
        budget.append_entry(program, "ACCRUAL", provisional, claim_id=claim["id"])

    claimant["open_claim_count"] += 1
    db.touch(claimant)
    offer["active_claim_count"] += 1
    db.touch(offer)

    if program is not None:
        budget.recompute(program, trigger="ACCRUAL")

    if score >= db.FRAUD_SCORE_THRESHOLD:
        claim["adjudication_status"] = "HELD"
        db.touch(claim)
        fraud.open_case(claimant, claim["id"], "SYSTEM_AUTO", "AUTO_THRESHOLD", score)

    return resp.ok(ser.claim(claim))


def _has_duplicate_serial(claim, claim_receipts):
    window_seconds = db.DEDUPE_WINDOW_DAYS * 86400
    for r in claim_receipts:
        for other in db.receipts.values():
            if other["claim_id"] == claim["id"]:
                continue
            if other["serial_number"] != r["serial_number"]:
                continue
            other_claim = db.claims.get(other["claim_id"])
            if other_claim is None:
                continue
            if other_claim["adjudication_status"] not in db.CLAIM_ACTIVE_ADJ:
                continue
            delta = abs((other["purchase_date"] - r["purchase_date"]).total_seconds())
            if int(delta // 86400) <= db.DEDUPE_WINDOW_DAYS:
                return True
    return False


@bp.post("/api/claims/<cid>/withdraw")
@mw.require("Dealer", "Consumer")
def withdraw_claim(cid):
    claim = db.get_claim(cid)
    mw.owns(claim["claimant_id"])
    if claim["adjudication_status"] not in ("DRAFT", "SUBMITTED"):
        raise _state_error(claim, "ERR_CLAIM_NOT_REVIEWABLE")

    was_submitted = claim["adjudication_status"] == "SUBMITTED"
    claim["adjudication_status"] = "WITHDRAWN"
    db.touch(claim)

    if was_submitted:
        claimant = db.claimants.get(claim["claimant_id"])
        if claimant is not None:
            claimant["open_claim_count"] -= 1
            db.touch(claimant)
        offer = db.offers.get(claim["offer_id"])
        if offer is not None:
            offer["active_claim_count"] -= 1
            db.touch(offer)
            program = db.programs.get(offer["program_id"])
            if program is not None:
                budget.recompute(program)
    return resp.ok(ser.claim(claim))


# ---------------------------------------------------------------------------
# Adjudication
# ---------------------------------------------------------------------------
@bp.post("/api/claims/<cid>/review")
@mw.require("ClaimsProcessor")
def review_claim(cid):
    claim = db.get_claim(cid)
    if claim["adjudication_status"] != "SUBMITTED":
        raise _state_error(claim, "ERR_CLAIM_NOT_REVIEWABLE")
    claim["adjudication_status"] = "UNDER_REVIEW"
    db.touch(claim)
    return resp.ok(ser.claim(claim))


@bp.post("/api/claims/<cid>/approve")
@mw.require("ClaimsProcessor")
def approve_claim(cid):
    claim = db.get_claim(cid)
    # (9) state: the claim first, then the funding program
    if claim["adjudication_status"] != "UNDER_REVIEW":
        raise _state_error(claim, "ERR_CLAIM_NOT_REVIEWABLE")
    offer = db.get_offer(claim["offer_id"])
    program = db.programs.get(offer["program_id"])
    if program is None or program["status"] != "ACTIVE":
        raise err("ERR_PROGRAM_NOT_ACTIVE")

    # (11) claimant standing
    claimant = db.get_claimant(claim["claimant_id"])
    if claimant["status"] != "ACTIVE":
        raise err("ERR_CLAIMANT_BLOCKED")

    # (15) validated-receipt requirement
    validated = [r for r in db.receipts_of_claim(claim["id"]) if r["validated"]]
    if not validated:
        raise err("ERR_NO_VALIDATED_RECEIPT")

    # (16) budget gate, with this claim excluded from pending_provisional_cents
    final_cents, units = rebate.compute(claim, claimant, offer, "final")
    pos = budget.position(program, subject_claim_id=claim["id"])
    if final_cents > pos["available_cents"]:
        raise err("ERR_BUDGET_EXCEEDED")

    claim["adjudication_status"] = "APPROVED"
    claim["final_rebate_cents"] = final_cents
    claim["total_units"] = units
    claim["approved_at"] = db.now()
    claim["approved_by_user_id"] = g.user_id
    db.touch(claim)

    claimant["open_claim_count"] -= 1
    db.touch(claimant)

    budget.append_entry(program, "COMMIT", final_cents, claim_id=claim["id"])
    budget.recompute(program, trigger="COMMIT")

    return resp.ok(ser.claim(claim))


@bp.post("/api/claims/<cid>/deny")
@mw.require("ClaimsProcessor")
def deny_claim(cid):
    claim = db.get_claim(cid)
    data = mw.body()
    reason_code = mw.as_string(data, "reason_code")
    if claim["adjudication_status"] != "UNDER_REVIEW":
        raise _state_error(claim, "ERR_CLAIM_NOT_REVIEWABLE")

    claim["adjudication_status"] = "DENIED"
    claim["denied_at"] = db.now()
    claim["denial_reason_code"] = reason_code
    db.touch(claim)

    claimant = db.claimants.get(claim["claimant_id"])
    if claimant is not None:
        claimant["denied_claim_count"] += 1
        claimant["open_claim_count"] -= 1
        db.touch(claimant)
    offer = db.offers.get(claim["offer_id"])
    if offer is not None:
        offer["active_claim_count"] -= 1
        db.touch(offer)
        program = db.programs.get(offer["program_id"])
        if program is not None:
            budget.recompute(program)
    return resp.ok(ser.claim(claim))


@bp.post("/api/claims/<cid>/appeal")
@mw.require("Dealer", "Consumer")
def appeal_claim(cid):
    claim = db.get_claim(cid)
    mw.owns(claim["claimant_id"])
    data = mw.body()
    mw.as_string(data, "appeal_note")

    # (9) state
    if claim["adjudication_status"] != "DENIED":
        raise _state_error(claim, "ERR_CLAIM_NOT_REVIEWABLE")
    if claim["denial_reason_code"] == "FRAUD_SUBSTANTIATED":
        raise err("ERR_CLAIM_NOT_REVIEWABLE", "A fraud denial is not appealable.")

    # (11) claimant standing
    claimant = db.get_claimant(claim["claimant_id"])
    if claimant["status"] != "ACTIVE":
        raise err("ERR_CLAIMANT_BLOCKED")

    # (13) appeal window
    if claim["denied_at"] is None or db.whole_days(db.now(), claim["denied_at"]) > db.APPEAL_WINDOW_DAYS:
        raise err("ERR_APPEAL_WINDOW_EXPIRED")

    # (15) appeal ceiling
    if claim["appeal_count"] >= db.MAX_APPEALS_PER_CLAIM:
        raise err("ERR_APPEAL_LIMIT_REACHED")

    claim["adjudication_status"] = "UNDER_REVIEW"
    claim["appeal_count"] += 1
    db.touch(claim)

    claimant["denied_claim_count"] -= 1
    claimant["open_claim_count"] += 1
    db.touch(claimant)
    offer = db.offers.get(claim["offer_id"])
    if offer is not None:
        offer["active_claim_count"] += 1
        db.touch(offer)
        program = db.programs.get(offer["program_id"])
        if program is not None:
            budget.recompute(program)
    return resp.ok(ser.claim(claim))
