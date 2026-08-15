"""Insurance claim business logic."""
import store
from util import new_record, bump
from errors import raise_err, ERR_CLAIM_INVALID_STATE, ERR_APPEAL_LIMIT_REACHED, \
    ERR_SEGREGATION_OF_DUTIES_VIOLATION, ERR_INVALID_REQUEST


def create_claim(death_loss, claimed_amount_cents):
    """Create an insurance claim against a death loss."""
    from errors import ERR_DEATH_LOSS_NOT_INSURED, ERR_CLAIM_ALREADY_EXISTS, \
        ERR_CLAIM_EXCEEDS_LOSS_VALUE, ERR_INVALID_STATE_TRANSITION

    # Check loss is RECORDED (not VOIDED)
    if death_loss["status"] == "VOIDED":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Cannot file claim against VOIDED death loss %s" % death_loss["id"])

    # Check loss is insured
    if not death_loss["insured"]:
        raise_err(ERR_DEATH_LOSS_NOT_INSURED,
                  "Death loss %s is not insured" % death_loss["id"])

    # Check at most one claim per loss
    for claim in store.insurance_claims.values():
        if claim["death_loss_id"] == death_loss["id"]:
            raise_err(ERR_CLAIM_ALREADY_EXISTS,
                      "An insurance claim already exists for death loss %s" % death_loss["id"])

    # Check claimed amount
    if claimed_amount_cents <= 0:
        raise_err(ERR_INVALID_REQUEST, "claimed_amount_cents must be > 0")
    if claimed_amount_cents > death_loss["loss_value_cents"]:
        raise_err(ERR_CLAIM_EXCEEDS_LOSS_VALUE,
                  "claimed_amount_cents (%d) exceeds loss_value_cents (%d)"
                  % (claimed_amount_cents, death_loss["loss_value_cents"]))

    rec = new_record()
    rec.update({
        "death_loss_id": death_loss["id"],
        "claimed_amount_cents": claimed_amount_cents,
        "approved_amount_cents": None,
        "status": "UNDER_REVIEW",
        "appeal_count": 0,
        "decided_by_user_id": None,
    })
    store.insurance_claims[rec["id"]] = rec
    return rec


def decide_claim(claim, decision, approved_amount_cents, user_id):
    """Decide an UNDER_REVIEW claim."""
    if claim["status"] != "UNDER_REVIEW":
        raise_err(ERR_CLAIM_INVALID_STATE,
                  "Claim %s is not UNDER_REVIEW (status=%s)" % (claim["id"], claim["status"]))

    if decision == "APPROVE":
        if approved_amount_cents is not None:
            if approved_amount_cents < 1 or approved_amount_cents > claim["claimed_amount_cents"]:
                raise_err(ERR_INVALID_REQUEST,
                          "approved_amount_cents must be in 1..claimed_amount_cents")
            claim["approved_amount_cents"] = approved_amount_cents
        else:
            claim["approved_amount_cents"] = claim["claimed_amount_cents"]
        claim["status"] = "APPROVED"
    elif decision == "DENY":
        claim["status"] = "DENIED"
    else:
        raise_err(ERR_INVALID_REQUEST, "decision must be APPROVE or DENY")

    claim["decided_by_user_id"] = user_id
    bump(claim)
    return claim


def appeal_claim(claim):
    """Appeal a DENIED claim."""
    if claim["status"] != "DENIED":
        raise_err(ERR_CLAIM_INVALID_STATE,
                  "Claim %s is not DENIED (status=%s)" % (claim["id"], claim["status"]))

    if claim["appeal_count"] >= 1:
        raise_err(ERR_APPEAL_LIMIT_REACHED,
                  "Claim %s has already been appealed (appeal_count=%d)"
                  % (claim["id"], claim["appeal_count"]))

    claim["appeal_count"] += 1
    claim["status"] = "UNDER_REVIEW"
    bump(claim)
    return claim


def pay_claim(claim, payer_user_id):
    """Pay an APPROVED claim with segregation of duties check."""
    # Segregation of duties: payer must differ from decider
    if claim["decided_by_user_id"] == payer_user_id:
        raise_err(ERR_SEGREGATION_OF_DUTIES_VIOLATION,
                  "Payer's X-User-ID equals the claim's decided_by_user_id")

    if claim["status"] != "APPROVED":
        raise_err(ERR_CLAIM_INVALID_STATE,
                  "Claim %s is not APPROVED (status=%s)" % (claim["id"], claim["status"]))

    # Route recovery
    death_loss = store.death_losses.get(claim["death_loss_id"])
    lot = store.lots.get(death_loss["lot_id"]) if death_loss else None
    owner = store.owners.get(lot["owner_id"]) if lot else None

    if lot and owner:
        # Check if lot has an OPEN invoice
        open_invoice = None
        for inv in store.invoices.values():
            if inv["lot_id"] == lot["id"] and inv["status"] == "OPEN":
                open_invoice = inv
                break

        approved_amount = claim["approved_amount_cents"]

        if open_invoice:
            # Direct credit to owner balance
            credit = min(approved_amount, owner["outstanding_balance_cents"])
            owner["outstanding_balance_cents"] -= credit
            bump(owner)
        else:
            # Add to lot's pending credit
            lot["insurance_credit_pending_cents"] += approved_amount
            bump(lot)

    claim["status"] = "PAID"
    bump(claim)
    return claim
