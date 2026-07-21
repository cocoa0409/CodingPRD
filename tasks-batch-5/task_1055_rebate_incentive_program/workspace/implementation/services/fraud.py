"""Fraud scoring (PRD §3.7) and the substantiation cascade."""
from decimal import Decimal

import db
from services import budget


def heuristic_score(claimant, subject_claim=None):
    """Real-time weighted heuristic. `subject_claim` supplies the high-value input."""
    clock = db.now()
    denied = claimant["denied_claim_count"]
    dup = claimant["duplicate_attempt_count"]

    recent = 0
    for c in db.claims_of_claimant(claimant["id"]):
        if c["adjudication_status"] in ("DRAFT", "WITHDRAWN", "VOIDED"):
            continue
        if c["submitted_at"] is None:
            continue
        if (clock - c["submitted_at"]).total_seconds() < db.VELOCITY_WINDOW_DAYS * 86400:
            recent += 1

    velocity_excess = max(0, recent - db.VELOCITY_FREE_CLAIMS)

    high_value = 0
    if subject_claim is not None and (subject_claim.get("provisional_rebate_cents") or 0) >= db.HIGH_VALUE_CLAIM_CENTS:
        high_value = 1

    score = (
        db.W_DENIED * denied
        + db.W_DUPLICATE * dup
        + db.W_VELOCITY * velocity_excess
        + db.W_HIGH_VALUE * high_value
    )
    return min(db.FRAUD_SCORE_MAX, max(db.FRAUD_SCORE_MIN, score))


def open_case(claimant, claim_id, opened_by, opened_reason, heuristic_at_open):
    case = db.base_record()
    case.update({
        "claimant_id": claimant["id"],
        "claim_id": claim_id,
        "status": "OPEN",
        "opened_reason": opened_reason,
        "opened_by": opened_by,
        "heuristic_score_at_open": heuristic_at_open,
        "final_score": None,
        "info_request_count": 0,
    })
    db.fraud_cases[case["id"]] = case
    return case


def substantiated_score(case):
    return min(
        db.FRAUD_SCORE_MAX,
        db.round_half_up(Decimal(case["heuristic_score_at_open"]) * db.SUBSTANTIATION_MULTIPLIER),
    )


def cleared_score(case):
    return max(db.FRAUD_SCORE_MIN, case["heuristic_score_at_open"] - db.CLEARANCE_CREDIT)


def block_claimant_cascade(claimant):
    """PRD §3.7 substantiation fan-out, three hops deep."""
    if claimant["status"] != "ACTIVE":
        return
    # hop 1
    claimant["status"] = "BLOCKED"
    db.touch(claimant)

    touched_programs = {}
    revoked = []

    # hop 2
    for claim in db.claims_of_claimant(claimant["id"]):
        offer = db.offers.get(claim["offer_id"])
        if claim["adjudication_status"] in db.CLAIM_OPEN_ADJ:
            claim["adjudication_status"] = "DENIED"
            claim["denied_at"] = db.now()
            claim["denial_reason_code"] = "FRAUD_SUBSTANTIATED"
            db.touch(claim)
            claimant["denied_claim_count"] += 1
            claimant["open_claim_count"] -= 1
            if offer is not None:
                offer["active_claim_count"] -= 1
                db.touch(offer)
        elif (
            claim["adjudication_status"] == "APPROVED"
            and claim["payment_status"] in ("NONE", "SCHEDULED")
        ):
            claim["adjudication_status"] = "REVOKED"
            db.touch(claim)
            if offer is not None:
                offer["active_claim_count"] -= 1
                db.touch(offer)
            revoked.append(claim)

    db.touch(claimant)

    # hop 3
    for claim in revoked:
        program = db.program_of_claim(claim)
        if program is not None:
            budget.append_entry(
                program, "RELEASE", claim["final_rebate_cents"] or 0, claim_id=claim["id"]
            )
            touched_programs[program["id"]] = program
        for payout in db.payouts_of_claim(claim["id"]):
            if payout["status"] in ("PENDING", "REISSUE_PENDING"):
                payout["status"] = "VOIDED"
                db.touch(payout)
                claim["payment_status"] = "NONE"
                db.touch(claim)

    # denials also move pending_provisional; recompute every affected program
    for claim in db.claims_of_claimant(claimant["id"]):
        program = db.program_of_claim(claim)
        if program is not None:
            touched_programs[program["id"]] = program
    for program in touched_programs.values():
        budget.recompute(program, trigger="RELEASE")
