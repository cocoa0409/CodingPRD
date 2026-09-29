"""Coverage screens, defense allocation and settlement funding (PRD 3.7 - 3.9)."""

from money import ZERO, dec, q2
from services import derive
from services.derive import SIDE_A, SIDE_B, ELIGIBLE_PARTS

HAMMER_CONSENT = dec("1.00")
HAMMER_REFUSE = dec("0.70")


# --------------------------------------------------------------------------
# Notice screens
# --------------------------------------------------------------------------


def prior_acts_ok(policy, wrongful_act_date):
    """The retroactive date binds unless full-prior-acts wording was agreed."""
    if wrongful_act_date >= policy["retroactive_date"]:
        return True
    term = derive.agreed_term(policy["quote_id"], "PRIOR_ACTS")
    return term is not None and term["agreed_variant"] == "RETRO_DATE_FULL_PRIOR_ACTS"


def insured_vs_insured_ok(policy, claimant_capacity):
    if claimant_capacity == "THIRD_PARTY":
        return True
    term = derive.agreed_term(policy["quote_id"], "INSURED_VS_INSURED")
    if term is None:
        return False
    variant = term["agreed_variant"]
    if variant == "NONE":
        return True
    if variant == "DERIVATIVE_CARVEBACK" and claimant_capacity == "SHAREHOLDER_DERIVATIVE":
        return True
    if variant == "BANKRUPTCY_CARVEBACK" and claimant_capacity == "BANKRUPTCY_TRUSTEE":
        return True
    return False


# --------------------------------------------------------------------------
# Defense allocation and the advancement waterfall
# --------------------------------------------------------------------------


def relative_exposure_share(invoice):
    persons = dec(invoice["insured_person_defendant_count"])
    entities = dec(invoice["entity_defendant_count"])
    denominator = persons + entities
    if denominator == 0:
        return ZERO
    return persons / denominator


def covered_allocated(invoice, method):
    covered = dec(invoice["covered_matter_amount_usd"])
    mixed = dec(invoice["mixed_matter_amount_usd"])
    if method == "RELATIVE_EXPOSURE":
        return q2(covered + mixed * relative_exposure_share(invoice))
    return q2(covered + mixed * dec("1.00"))


def waterfall(claim, policy, covered, touched):
    """Retention, then Side B, then Side A, then unfunded excess."""
    eligible = ELIGIBLE_PARTS[claim["claim_type"]]
    remaining = q2(covered)
    retention_applied = ZERO
    if SIDE_B in eligible:
        available = dec(claim["retention_remaining_usd"])
        retention_applied = q2(available if available < remaining else remaining)
        remaining = q2(remaining - retention_applied)
    advanced = ZERO
    charges = []
    for part_name in (SIDE_B, SIDE_A):
        if remaining <= 0:
            break
        if part_name not in eligible:
            continue
        part = derive.part_of(policy["id"], part_name)
        if part is None or part["status"] != "ACTIVE":
            continue
        capacity = dec(part["remaining_limit_usd"])
        take = q2(capacity if capacity < remaining else remaining)
        if take <= 0:
            continue
        derive.erode_part(part, take, touched)
        charges.append({"part_id": part["id"], "amount": take})
        advanced = q2(advanced + take)
        remaining = q2(remaining - take)
    return {
        "retention_applied_usd": q2(retention_applied),
        "advanced_usd": q2(advanced),
        "unfunded_excess_usd": q2(remaining),
        "charges": charges,
    }


# --------------------------------------------------------------------------
# Settlement consent and the hammer clause
# --------------------------------------------------------------------------


def hammer_cap(hammer_pct, recommended_amount, retention_baseline):
    excess = dec(recommended_amount) - dec(retention_baseline)
    if excess < 0:
        excess = ZERO
    return q2(dec(hammer_pct) * excess)


def insurer_share(final_amount, retention_baseline, cap, aggregate_remaining):
    excess = dec(final_amount) - dec(retention_baseline)
    if excess < 0:
        excess = ZERO
    share = excess
    if dec(cap) < share:
        share = dec(cap)
    if dec(aggregate_remaining) < share:
        share = dec(aggregate_remaining)
    if share < 0:
        share = ZERO
    return q2(share)


def split_indemnity(claim, policy, share, touched):
    """Split the insurer share across the parts that can respond, residual last."""
    eligible_names = ELIGIBLE_PARTS[claim["claim_type"]]
    eligible = [
        part
        for part in derive.parts_of(policy["id"])
        if part["part"] in eligible_names
        and part["status"] == "ACTIVE"
        and dec(part["remaining_limit_usd"]) > 0
    ]
    share = q2(share)
    if share <= 0:
        return q2(ZERO)
    basis = ZERO
    for part in eligible:
        basis += dec(part["remaining_limit_usd"])
    if basis == 0:
        return share
    shares = []
    assigned = ZERO
    for part in eligible:
        amount = q2(share * dec(part["remaining_limit_usd"]) / basis)
        shares.append([part, amount])
        assigned = q2(assigned + amount)
    residual = q2(share - assigned)
    if residual != 0:
        best_index = 0
        for index in range(1, len(shares)):
            candidate = shares[index][0]
            incumbent = shares[best_index][0]
            if dec(candidate["remaining_limit_usd"]) > dec(incumbent["remaining_limit_usd"]):
                best_index = index
        shares[best_index][1] = q2(shares[best_index][1] + residual)
    for part, amount in shares:
        if amount > 0:
            derive.erode_part(part, amount, touched)
        elif amount < 0:
            derive.restore_part(part, -amount, touched)
    return q2(ZERO)


# --------------------------------------------------------------------------
# Clawback on a denial after advancement (PRD 3.8)
# --------------------------------------------------------------------------


def clawback(claim, policy, touched):
    for invoice in derive.invoices_of(claim["id"]):
        if invoice["status"] == "ADVANCED":
            invoice["status"] = "CLAWED_BACK"
            _reverse_invoice(claim, policy, invoice, touched)
            touched.add(invoice)
        elif invoice["status"] == "SUBMITTED":
            invoice["status"] = "VOIDED"
            touched.add(invoice)
    claim["advanced_defense_usd"] = q2(ZERO)
    claim["retention_applied_usd"] = q2(ZERO)
    claim["retention_remaining_usd"] = q2(dec(policy["retention_usd"]))
    derive.cascade_restore(policy, touched)


def _reverse_invoice(claim, policy, invoice, touched):
    """Return the invoice's advanced money to the very parts it eroded."""
    from db import store

    for charge in reversed(invoice.get("_charges") or []):
        part = store.coverage_parts.get(charge["part_id"])
        if part is None:
            continue
        derive.restore_part(part, dec(charge["amount"]), touched)
    invoice["_charges"] = []
