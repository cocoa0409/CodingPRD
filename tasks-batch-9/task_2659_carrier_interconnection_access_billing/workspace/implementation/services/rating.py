"""jurisdiction_determination and access_charge_rating (PRD 2.x calculations)."""
from decimal import Decimal

from constants import (DEFAULT_PIU_PCT, DEFAULT_PLU_PCT,
                       RATE_ELEMENT_BY_JURISDICTION)
from dec import q2, q4, q6
from errors import ApiError
from services.tariff import effective_filing_for
from store import db, ordered, sort_key

HUNDRED = Decimal("100")
ZERO4 = Decimal("0.0000")
ZERO2 = Decimal("0.00")
BILLABLE_JURISDICTIONS = ("INTERSTATE", "INTRASTATE", "LOCAL")


def batch_records(batch_id):
    return ordered([c for c in db.cdrs.values() if c["usage_batch_id"] == batch_id])


def quarter_of(instant):
    return "%04dQ%d" % (instant.year, (instant.month - 1) // 3 + 1)


def select_factor_filing(carrier_id, quarter):
    """Candidates are the carrier's filings for that quarter that are not
    SUPERSEDED; the one with the latest created_at wins."""
    candidates = [f for f in db.factor_filings.values()
                  if f["carrier_id"] == carrier_id
                  and f["quarter"] == quarter
                  and f["status"] != "SUPERSEDED"]
    if not candidates:
        return None
    return sorted(candidates, key=sort_key)[-1]


def determine_record_jurisdiction(cdr):
    """Signaling pass for a single call detail record."""
    if not cdr["signaling_cpn_present"] or cdr["originating_state_code"] is None:
        return "INDETERMINATE", "FACTOR_ALLOCATED"
    effective_origin = cdr["jip_state_code"] or cdr["originating_state_code"]
    if effective_origin != cdr["terminating_state_code"]:
        return "INTERSTATE", "SIGNALING"
    if cdr["same_local_calling_area"]:
        return "LOCAL", "SIGNALING"
    return "INTRASTATE", "SIGNALING"


def jurisdictionalize(batch):
    """Full re-run of jurisdiction_determination over the batch."""
    signaling = {"INTERSTATE": ZERO4, "INTRASTATE": ZERO4, "LOCAL": ZERO4}
    signaling_total = ZERO4
    indeterminate = ZERO4

    records = batch_records(batch["id"])
    for cdr in records:
        jurisdiction, source = determine_record_jurisdiction(cdr)
        cdr["jurisdiction"] = jurisdiction
        cdr["jurisdiction_source"] = source
        cdr["rated_amount_usd"] = None
        minutes = q4(cdr["billable_minutes"])
        if jurisdiction == "INDETERMINATE":
            indeterminate += minutes
        else:
            signaling[jurisdiction] += minutes
            signaling_total += minutes

    if indeterminate == ZERO4:
        factor_source = "SIGNALING_ONLY"
        filing_id = None
        piu = ZERO2
        plu = ZERO2
    else:
        quarter = quarter_of(batch["period_start"])
        filing = select_factor_filing(batch["carrier_id"], quarter)
        if filing is None:
            factor_source = "DEFAULT_TARIFF"
            filing_id = None
            piu = DEFAULT_PIU_PCT
            plu = DEFAULT_PLU_PCT
        else:
            filing_id = filing["id"]
            factor_source = "AUDITED" if filing["status"] == "AUDITED" else "CARRIER_REPORTED"
            piu = filing["effective_piu_pct"]
            plu = filing["effective_plu_pct"]

    allocated_interstate = q4(indeterminate * piu / HUNDRED)
    allocated_local = q4(indeterminate * plu / HUNDRED)
    allocated_intrastate = indeterminate - allocated_interstate - allocated_local

    batch["signaling_determined_minutes"] = q4(signaling_total)
    batch["indeterminate_minutes"] = q4(indeterminate)
    batch["interstate_minutes"] = q4(signaling["INTERSTATE"] + allocated_interstate)
    batch["intrastate_minutes"] = q4(signaling["INTRASTATE"] + allocated_intrastate)
    batch["local_minutes"] = q4(signaling["LOCAL"] + allocated_local)
    batch["traffic_factor_filing_id"] = filing_id
    batch["factor_source"] = factor_source
    batch["_allocated_minutes"] = {
        "INTERSTATE": allocated_interstate,
        "INTRASTATE": allocated_intrastate,
        "LOCAL": allocated_local,
    }
    batch["_piu_pct"] = piu
    batch["_plu_pct"] = plu
    return batch


def _minute_bucket(batch, jurisdiction):
    return batch[{
        "INTERSTATE": "interstate_minutes",
        "INTRASTATE": "intrastate_minutes",
        "LOCAL": "local_minutes",
    }[jurisdiction]]


def resolve_rates(batch, enforce=True):
    """Every jurisdiction whose minute bucket is greater than zero must have an
    EFFECTIVE filing whose half-open window covers period_start."""
    rates = {}
    filings = {}
    for jurisdiction in BILLABLE_JURISDICTIONS:
        filing = effective_filing_for(RATE_ELEMENT_BY_JURISDICTION[jurisdiction],
                                      batch["period_start"])
        if filing is None:
            if enforce and _minute_bucket(batch, jurisdiction) > ZERO4:
                raise ApiError("ERR_NO_EFFECTIVE_TARIFF_RATE",
                               "no effective tariff rate for %s" % jurisdiction)
            rates[jurisdiction] = None
            filings[jurisdiction] = None
        else:
            rates[jurisdiction] = filing["rate_per_mou_usd"]
            filings[jurisdiction] = filing["id"]
    return rates, filings


def rate_batch(batch, enforce=True):
    """access_charge_rating: per-record charges, then the two legs per
    jurisdiction rounded separately, then the untouched sum of subtotals."""
    rates, filings = resolve_rates(batch, enforce=enforce)
    allocated = batch.get("_allocated_minutes") or {
        "INTERSTATE": ZERO4, "INTRASTATE": ZERO4, "LOCAL": ZERO4}

    signaling_sums = {j: ZERO2 for j in BILLABLE_JURISDICTIONS}
    for cdr in batch_records(batch["id"]):
        if cdr["jurisdiction_source"] != "SIGNALING":
            cdr["rated_amount_usd"] = None
            continue
        rate = rates.get(cdr["jurisdiction"])
        if rate is None:
            cdr["rated_amount_usd"] = None
            continue
        amount = q6(Decimal(cdr["billable_minutes"]) * rate)
        cdr["rated_amount_usd"] = amount
        signaling_sums[cdr["jurisdiction"]] += amount

    subtotals = {}
    for jurisdiction in BILLABLE_JURISDICTIONS:
        rate = rates.get(jurisdiction)
        signaling_leg = q2(signaling_sums[jurisdiction])
        if rate is None:
            factor_leg = ZERO2
        else:
            factor_leg = q2(allocated.get(jurisdiction, ZERO4) * rate)
        subtotals[jurisdiction] = signaling_leg + factor_leg

    batch["interstate_amount_usd"] = subtotals["INTERSTATE"]
    batch["intrastate_amount_usd"] = subtotals["INTRASTATE"]
    batch["local_amount_usd"] = subtotals["LOCAL"]
    batch["rated_amount_usd"] = (subtotals["INTERSTATE"] + subtotals["INTRASTATE"]
                                 + subtotals["LOCAL"])
    batch["rating_variant"] = "FINAL" if batch["factor_source"] == "AUDITED" else "PRELIMINARY"
    batch["_rate_filing_ids"] = filings
    return batch
