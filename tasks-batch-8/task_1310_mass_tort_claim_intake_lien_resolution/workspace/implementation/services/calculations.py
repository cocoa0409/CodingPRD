"""Calculation rules from scaffold Table 3.

All monetary math uses Decimal with ROUND_HALF_UP for precision.
"""

from decimal import Decimal, ROUND_HALF_UP

import db


FEE_RATE = Decimal("0.40")
HARDSHIP_FLOOR_CENTS = 5_000_000


def _round_half_up_cents(value):
    """Round a Decimal to integer cents using ROUND_HALF_UP."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_severity_score(claim_id):
    """Max severity_score across ACCEPTED medical records for a claim."""
    accepted = [
        r for r in db.medical_records.values()
        if r["claim_id"] == claim_id and r["review_state"] == "ACCEPTED"
    ]
    if not accepted:
        return None
    return max(r["severity_score"] for r in accepted)


def tier_assignment(tier_matrix_id):
    """Return gross_award_cents from the matched matrix row."""
    row = db.tier_matrices.get(tier_matrix_id)
    if row is None:
        return 0
    return row["base_award_cents"]


def attorney_fee(claim, claimant):
    """Compute attorney_fee_cents per the nested-rounding canonical order.

    Per-lien shares are rounded to integer cents first, then summed.
    Base fee = round_half_up((gross - total_lien) * 0.40).
    attorney_fee = base_fee - lien_share_total, floored at 0.
    """
    if not claimant["represented_by_counsel"]:
        return 0

    gross = claim["gross_award_cents"]
    total_lien = claim["total_lien_cents"]

    lien_share_total = 0
    resolved_liens = [
        l for l in db.liens.values()
        if l["claim_id"] == claim["id"] and l["state"] == "RESOLVED"
    ]
    for lien in resolved_liens:
        share = _round_half_up_cents(
            Decimal(lien["final_demand_cents"]) * FEE_RATE
        )
        lien_share_total += share

    base_fee = _round_half_up_cents(
        Decimal(gross - total_lien) * FEE_RATE
    )

    fee = base_fee - lien_share_total
    return max(fee, 0)


def provisional_lien_demand(lien, claim):
    """Compute provisional_demand_cents based on lien type and claim gross award."""
    asserted = Decimal(lien["asserted_amount_cents"])
    gross = claim["gross_award_cents"]

    if lien["lien_type"] == "MEDICARE":
        rate = Decimal("0.60")
    elif lien["lien_type"] == "MEDICAID":
        rate = Decimal("0.50")
    elif lien["lien_type"] == "VA_TRICARE":
        rate = Decimal("0.70")
    elif lien["lien_type"] == "MEDICAL_PROVIDER":
        if gross < HARDSHIP_FLOOR_CENTS:
            rate = Decimal("0.40")
        else:
            rate = Decimal("0.80")
    else:  # PRIVATE_INSURER
        rate = Decimal("0.75")

    return _round_half_up_cents(asserted * rate)


def recompute_claim_totals(claim):
    """Recompute total_lien_cents and net_award_cents for a claim.

    total_lien_cents = sum of final_demand_cents over RESOLVED liens.
    net_award_cents = gross - total_lien - attorney_fee, floored at 0.
    """
    resolved = [
        l for l in db.liens.values()
        if l["claim_id"] == claim["id"] and l["state"] == "RESOLVED"
    ]
    claim["total_lien_cents"] = sum(l["final_demand_cents"] for l in resolved)
    claim["net_award_cents"] = max(
        claim["gross_award_cents"] - claim["total_lien_cents"] - claim["attorney_fee_cents"],
        0,
    )


def disbursement_allocation(claim, claimant):
    """Run the allocation waterfall and create Disbursement rows.

    Returns list of created disbursement dicts (already inserted into db.disbursements).
    Order: (1) LIEN_HOLDER buckets, (2) ATTORNEY, (3) CLAIMANT residual.
    """
    from routes.helpers import new_common_fields

    remaining = claim["net_award_cents"]
    created = []

    # Bucket 1: lien holders grouped by holder_name, ordered by earliest lien created_at ASC
    resolved = [
        l for l in db.liens.values()
        if l["claim_id"] == claim["id"] and l["state"] == "RESOLVED"
    ]
    # Group by holder_name preserving earliest created_at order
    holder_map = {}
    holder_order = []
    for lien in resolved:
        hn = lien["holder_name"]
        if hn not in holder_map:
            holder_map[hn] = 0
            holder_order.append((lien["created_at"], hn))
        holder_map[hn] += lien["final_demand_cents"]
    holder_order.sort(key=lambda x: x[0])

    for _, hn in holder_order:
        amt = holder_map[hn]
        disb = {
            "claim_id": claim["id"],
            "payee_name": hn,
            "payee_role": "LIEN_HOLDER",
            "amount_cents": amt,
            "state": "PENDING",
            "released_at": None,
        }
        disb.update(new_common_fields())
        db.disbursements[disb["id"]] = disb
        created.append(disb)
        remaining -= amt

    # Bucket 2: attorney
    if claimant["represented_by_counsel"]:
        disb = {
            "claim_id": claim["id"],
            "payee_name": "Counsel of Record",
            "payee_role": "ATTORNEY",
            "amount_cents": claim["attorney_fee_cents"],
            "state": "PENDING",
            "released_at": None,
        }
        disb.update(new_common_fields())
        db.disbursements[disb["id"]] = disb
        created.append(disb)
        remaining -= claim["attorney_fee_cents"]

    # Bucket 3: claimant residual
    disb = {
        "claim_id": claim["id"],
        "payee_name": claimant["full_name"],
        "payee_role": "CLAIMANT",
        "amount_cents": remaining,
        "state": "PENDING",
        "released_at": None,
    }
    disb.update(new_common_fields())
    db.disbursements[disb["id"]] = disb
    created.append(disb)

    return created


def qsf_reconciliation(program):
    """Recompute program.qsf_remaining_cents.

    = principal - sum(RELEASED disbursements) - sum(qsf_reservation on READY_FOR_DISBURSEMENT claims)
    """
    released_total = 0
    for d in db.disbursements.values():
        if d["state"] == "RELEASED":
            claim = db.claims.get(d["claim_id"])
            if claim and claim["settlement_program_id"] == program["id"]:
                released_total += d["amount_cents"]

    reserved_total = 0
    for c in db.claims.values():
        if c["settlement_program_id"] == program["id"] and c["status"] == "READY_FOR_DISBURSEMENT":
            reserved_total += c["qsf_reservation_cents"]

    program["qsf_remaining_cents"] = program["qsf_principal_cents"] - released_total - reserved_total
