"""Business logic: classification, withholding math, aggregation, invalidation cascades."""
from decimal import Decimal, ROUND_HALF_UP

from db import store, logical_now, touch

CORP_EXEMPT = {"C_CORP", "S_CORP", "LLC_C", "LLC_S"}
DEFAULT_RATE_BPS = 2400

ENTITY_CLASSIFICATIONS = {
    "INDIVIDUAL_SOLE_PROP", "C_CORP", "S_CORP", "PARTNERSHIP",
    "LLC_C", "LLC_S", "LLC_P", "TRUST_ESTATE", "TAX_EXEMPT",
}
SOURCE_SYSTEMS = {"AP_ERP", "CORP_CARD", "MANUAL", "FIELD_OFFICE"}
PAYMENT_TYPES = {"SERVICE", "RENT", "ROYALTY", "ATTORNEY_FEE", "MEDICAL_HEALTH",
                 "PRIZE_AWARD", "GOODS", "REIMBURSEMENT"}
TIN_TYPES = {"SSN", "EIN"}
FORM_TYPES = {"NEC", "MISC"}
STAGE_RANK = {"NONE": 0, "FIRST": 1, "SECOND": 2}

_TYPE_TO_BOX = {"SERVICE": "NEC_1", "RENT": "MISC_1", "ROYALTY": "MISC_2", "PRIZE_AWARD": "MISC_3"}


def classify(payment_type, entity_classification):
    """box_classification: computed once at posting, frozen on the Payment."""
    if payment_type in ("GOODS", "REIMBURSEMENT"):
        return False, "NONE"
    if payment_type == "ATTORNEY_FEE":
        return True, "NEC_1"
    if payment_type == "MEDICAL_HEALTH":
        return True, "MISC_6"
    if entity_classification in CORP_EXEMPT:
        return False, "NONE"
    return True, _TYPE_TO_BOX[payment_type]


def withholding_cents(amount_cents, rate_bps):
    """Per-payment round-half-up; summing-then-rounding is forbidden for the ledger."""
    return int((Decimal(amount_cents) * Decimal(rate_bps) / Decimal(10000))
               .quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def quarter_of(dt):
    return (dt.month + 2) // 3


def find_tax_year_by_value(y):
    for ty in store["tax_years"].values():
        if ty["tax_year"] == y:
            return ty
    return None


def find_covering_tax_year(dt):
    for ty in store["tax_years"].values():
        if ty["_start"] <= dt < ty["_end"]:
            return ty
    return None


def vendor_balance(vendor_id):
    return sum(e["amount_cents"] for e in store["withholding_entries"].values()
               if e["vendor_id"] == vendor_id and e["status"] == "UNREMITTED")


def mismatch_count_3yr(vendor_id):
    now = logical_now()
    try:
        start = now.replace(year=now.year - 3)
    except ValueError:  # Feb 29
        start = now.replace(year=now.year - 3, day=28)
    n = 0
    for s in store["w9_submissions"].values():
        if (s["vendor_id"] == vendor_id and s["match_result"] == "MISMATCHED"
                and start <= s["_created"] <= now):
            n += 1
    return n


def backup_flag(vendor):
    return vendor["tin_match_status"] == "MISMATCHED" or vendor["b_notice_stage"] == "SECOND"


def recompute_draft_remittances(tax_year, quarter):
    for r in store["remittances"].values():
        if r["status"] == "DRAFT" and r["tax_year"] == tax_year and r["quarter"] == quarter:
            amt = sum(e["amount_cents"] for e in store["withholding_entries"].values()
                      if e["status"] == "UNREMITTED" and e["tax_year"] == tax_year
                      and e["quarter"] == quarter)
            if amt != r["amount_cents"]:
                r["amount_cents"] = amt
                touch(r)


def aggregate_year(vendor_id, tax_year):
    """reportable_box_aggregation over POSTED in-year payments."""
    sums = {"NEC_1": 0, "MISC_1": 0, "MISC_2": 0, "MISC_3": 0, "MISC_6": 0}
    box4 = 0
    for p in store["payments"].values():
        if p["vendor_id"] == vendor_id and p["tax_year"] == tax_year and p["status"] == "POSTED":
            if p["is_reportable"] and p["reportable_box"] in sums:
                sums[p["reportable_box"]] += p["amount_cents"]
            box4 += p["withheld_cents"]
    return sums, box4


def boxes_for_form(form_type, sums, box4):
    if form_type == "NEC":
        return {"box_1_cents": sums["NEC_1"], "box_2_cents": 0, "box_3_cents": 0,
                "box_4_cents": box4, "box_6_cents": 0}
    return {"box_1_cents": sums["MISC_1"], "box_2_cents": sums["MISC_2"],
            "box_3_cents": sums["MISC_3"], "box_4_cents": box4, "box_6_cents": sums["MISC_6"]}


def recompute_return_final(ret):
    sums, box4 = aggregate_year(ret["vendor_id"], ret["tax_year"])
    ret["box_amounts"] = boxes_for_form(ret["form_type"], sums, box4)
    ret["amount_basis"] = "FINAL"


def invalidate_open_returns(vendor_id, tax_year=None, open_years_only=False):
    """FINAL recompute of DRAFT/VALIDATED returns; VALIDATED reverts to DRAFT."""
    for ret in sorted(store["returns"].values(), key=lambda r: r["_seq"]):
        if ret["vendor_id"] != vendor_id:
            continue
        if ret["federal_status"] not in ("DRAFT", "VALIDATED"):
            continue
        if tax_year is not None and ret["tax_year"] != tax_year:
            continue
        if open_years_only:
            ty = find_tax_year_by_value(ret["tax_year"])
            if ty is None or ty["status"] != "OPEN":
                continue
        recompute_return_final(ret)
        ret["federal_status"] = "DRAFT"
        touch(ret)


def payment_in_accepted_return(payment):
    """A payment is 'included' when it feeds a box of an ACCEPTED return for its vendor-year."""
    for ret in store["returns"].values():
        if ret["vendor_id"] != payment["vendor_id"] or ret["tax_year"] != payment["tax_year"]:
            continue
        if ret["federal_status"] != "ACCEPTED":
            continue
        if payment["is_reportable"]:
            if ret["form_type"] == "NEC" and payment["reportable_box"] == "NEC_1":
                return True
            if ret["form_type"] == "MISC" and payment["reportable_box"] in (
                    "MISC_1", "MISC_2", "MISC_3", "MISC_6"):
                return True
        if payment["withheld_cents"] > 0:
            return True  # box_4 spans both forms regardless of reportability
    return False


def qualifying_return_count(tax_year):
    return sum(1 for r in store["returns"].values()
               if r["tax_year"] == tax_year
               and r["federal_status"] in ("VALIDATED", "TRANSMITTED", "ACCEPTED"))


def has_open_second_b_notice(vendor_id):
    return any(n["vendor_id"] == vendor_id and n["status"] == "OPEN" and n["stage"] == "SECOND"
               for n in store["b_notices"].values())


def reverse_entry(original):
    """Compensating pair: original -> REVERSED; new REVERSAL entry created already REVERSED."""
    from db import make_entry
    original["status"] = "REVERSED"
    make_entry({
        "vendor_id": original["vendor_id"],
        "payment_id": original["payment_id"],
        "reverses_entry_id": original["id"],
        "remittance_id": None,
        "tax_year": original["tax_year"],
        "quarter": original["quarter"],
        "entry_type": "REVERSAL",
        "amount_cents": -original["amount_cents"],
        "status": "REVERSED",
    })
    recompute_draft_remittances(original["tax_year"], original["quarter"])
    invalidate_open_returns(original["vendor_id"], tax_year=original["tax_year"])
