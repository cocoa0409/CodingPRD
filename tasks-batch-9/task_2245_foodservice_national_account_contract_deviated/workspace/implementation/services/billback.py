"""Bill-back claim accrual, manufacturer exposure and the cash-application
waterfall (SCAFFOLD calculations bill_back_claim_amount,
bill_back_remittance_waterfall)."""

from db import db, touch, values

EXPOSURE_STATUSES = ("SUBMITTED", "PARTIALLY_RECOVERED", "DISPUTED")
SWEEP_BILLBACK_STATUSES = ("ACCRUED", "CLAIMED")
SWEEP_PRICING_STATUSES = ("INVOICED", "REPRICED", "CREDITED")


def _line_key(line):
    return (line["order_date"], line["created_at"], line["_seq"])


def sweep_lines(deviation_agreement_id, claim_period_start, claim_period_end):
    rows = [ol for ol in values(db.order_lines)
            if ol["deviation_agreement_id"] == deviation_agreement_id
            and ol["billback_status"] in SWEEP_BILLBACK_STATUSES
            and ol["pricing_status"] in SWEEP_PRICING_STATUSES
            and ol["order_date"] >= claim_period_start
            and ol["order_date"] < claim_period_end]
    return sorted(rows, key=_line_key)


def claim_figures(lines):
    claimed_cases = 0
    claimed_amount_cents = 0
    for line in lines:
        claimed_cases += line["quantity_cases"]
        delta = line["list_unit_price_cents"] - line["invoiced_unit_price_cents"]
        if delta < 0:
            delta = 0
        claimed_amount_cents += delta * line["quantity_cases"]
    return claimed_cases, claimed_amount_cents


def recompute_claim_amount(claim):
    """Recompute claimed_amount_cents over the lines as they stand now."""
    lines = sweep_lines(claim["deviation_agreement_id"],
                        claim["claim_period_start"], claim["claim_period_end"])
    _, amount = claim_figures(lines)
    claim["claimed_amount_cents"] = amount
    return amount


def claims_of(manufacturer_id):
    return [k for k in values(db.bill_back_claims)
            if k["manufacturer_id"] == manufacturer_id]


def recompute_exposure(manufacturer):
    total = 0
    for claim in claims_of(manufacturer["id"]):
        if claim["status"] in EXPOSURE_STATUSES:
            total += claim["claimed_amount_cents"] - claim["recovered_amount_cents"]
    manufacturer["open_claim_exposure_cents"] = total
    return total


def lines_of_claim(claim_id):
    return sorted([ol for ol in db.order_lines.values()
                   if ol["bill_back_claim_id"] == claim_id], key=_line_key)


def apply_waterfall(remittance, manufacturer):
    buckets = [k for k in claims_of(manufacturer["id"])
               if k["status"] in ("SUBMITTED", "PARTIALLY_RECOVERED")]
    buckets.sort(key=lambda k: (k["claim_period_start"], k["created_at"], k["_seq"]))

    remaining = remittance["remitted_amount_cents"]
    applied_claim_ids = []
    slices = {}
    for claim in buckets:
        shortfall = claim["claimed_amount_cents"] - claim["recovered_amount_cents"]
        piece = remaining if remaining < shortfall else shortfall
        if piece > 0:
            claim["recovered_amount_cents"] += piece
            applied_claim_ids.append(claim["id"])
            slices[claim["id"]] = piece
            remaining -= piece
            if claim["recovered_amount_cents"] == claim["claimed_amount_cents"]:
                claim["status"] = "RECOVERED"
                for line in lines_of_claim(claim["id"]):
                    if line["billback_status"] == "CLAIMED":
                        line["billback_status"] = "RECOVERED"
                        touch(line)
            else:
                claim["status"] = "PARTIALLY_RECOVERED"
            touch(claim)
        if remaining == 0:
            break

    remittance["applied_claim_ids"] = applied_claim_ids
    remittance["applied_amount_cents"] = remittance["remitted_amount_cents"] - remaining
    remittance["unapplied_amount_cents"] = remaining
    remittance["_slices"] = slices

    manufacturer["unapplied_credit_cents"] += remaining
    manufacturer["total_remitted_cents"] += remittance["remitted_amount_cents"]
    recompute_exposure(manufacturer)
    return remittance


def reverse_waterfall(remittance, manufacturer):
    slices = remittance.get("_slices") or {}
    for claim_id in remittance["applied_claim_ids"]:
        claim = db.bill_back_claims.get(claim_id)
        if claim is None:
            continue
        piece = slices.get(claim_id, 0)
        claim["recovered_amount_cents"] -= piece
        if claim["recovered_amount_cents"] == 0:
            claim["status"] = "SUBMITTED"
        else:
            claim["status"] = "PARTIALLY_RECOVERED"
        for line in lines_of_claim(claim["id"]):
            if line["billback_status"] == "RECOVERED":
                line["billback_status"] = "CLAIMED"
                touch(line)
        touch(claim)

    manufacturer["unapplied_credit_cents"] -= remittance["unapplied_amount_cents"]
    manufacturer["total_remitted_cents"] -= remittance["remitted_amount_cents"]
    recompute_exposure(manufacturer)
    return remittance
