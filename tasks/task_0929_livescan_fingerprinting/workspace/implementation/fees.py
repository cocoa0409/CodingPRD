"""Fee assessment assembly (PRD 3.9).

The stage order is pinned: components (each percentage rounded on its own),
then the statutory waiver, then the invoiceable base, then the agency volume
discount keyed on mtd_billed_cents as it stands BEFORE this row joins it, then
the total, then the ledger.

Friction point 1 is resolved in favour of the scoped reading: a NO_SHOW row and
an ONSITE_SHORTFALL row stamp total_cents directly while all seven named
components stay 0, exactly as PRD 3.9's two-flat-kinds paragraph describes.
"""

from decimal import Decimal

import constants as C
from money import pct_of
from store import db


def volume_discount_pct(mtd_billed_cents):
    if mtd_billed_cents >= C.AGENCY_DISCOUNT_TIER2_FLOOR_CENTS:
        return C.AGENCY_DISCOUNT_TIER2_PCT
    if mtd_billed_cents >= C.AGENCY_DISCOUNT_TIER1_FLOOR_CENTS:
        return C.AGENCY_DISCOUNT_TIER1_PCT
    return Decimal("0")


def _blank(kind, agency, payer_regime):
    return {
        "agency_id": agency["id"],
        "submission_id": None,
        "appointment_id": None,
        "invoice_id": None,
        "assessment_kind": kind,
        "payer_regime": payer_regime,
        "state_fee_cents": 0,
        "federal_fee_cents": 0,
        "processing_surcharge_cents": 0,
        "vendor_convenience_fee_cents": 0,
        "vendor_tax_cents": 0,
        "trip_surcharge_cents": 0,
        "reprint_fee_cents": 0,
        "waived_cents": 0,
        "discount_cents": 0,
        "total_cents": 0,
        "paid_cents": 0,
        "credited_cents": 0,
        "status": "ASSESSED",
    }


def _ledger(agency, fields):
    """Step five -- the agency-side regimes accumulate mtd_billed_cents."""
    if fields["payer_regime"] in ("AGENCY_BILLED", "FEE_WAIVED"):
        agency["mtd_billed_cents"] += fields["total_cents"]
        db.touch(agency)


def create_transmission_assessment(kind, agency, submission, appointment, service_type, site, card):
    """kind is SUBMISSION or REPRINT."""
    fields = _blank(kind, agency, agency["payer_regime_default"])
    fields["submission_id"] = submission["id"]
    fields["appointment_id"] = appointment["id"]

    free_reprint = kind == "REPRINT" and bool(card["free_reprint_granted"])

    state_fee = 0 if free_reprint else service_type["state_fee_cents"]
    federal_fee = 0
    if not free_reprint and "FBI" in submission["destinations"]:
        federal_fee = service_type["federal_fee_cents"]
    processing = pct_of(C.PROCESSING_SURCHARGE_PCT, state_fee + federal_fee)
    convenience = C.VENDOR_CONVENIENCE_FEE_CENTS
    vendor_tax = pct_of(C.VENDOR_TAX_PCT, convenience)
    trip = C.TRIP_SURCHARGE_PER_CARD_CENTS if site["site_kind"] == "MOBILE_EVENT" else 0
    reprint_fee = C.REPRINT_FEE_CENTS if (kind == "REPRINT" and not free_reprint) else 0

    fields["state_fee_cents"] = state_fee
    fields["federal_fee_cents"] = federal_fee
    fields["processing_surcharge_cents"] = processing
    fields["vendor_convenience_fee_cents"] = convenience
    fields["vendor_tax_cents"] = vendor_tax
    fields["trip_surcharge_cents"] = trip
    fields["reprint_fee_cents"] = reprint_fee

    statutory = state_fee + federal_fee + processing
    waived = statutory if fields["payer_regime"] == "FEE_WAIVED" else 0
    fields["waived_cents"] = waived

    base = (statutory - waived) + convenience + vendor_tax + trip + reprint_fee

    discount = 0
    if fields["payer_regime"] in ("AGENCY_BILLED", "FEE_WAIVED"):
        discount = pct_of(volume_discount_pct(agency["mtd_billed_cents"]), base)
    fields["discount_cents"] = discount
    fields["total_cents"] = base - discount

    _ledger(agency, fields)
    return db.create("assessments", fields)


def create_no_show_assessment(agency, appointment):
    fields = _blank("NO_SHOW", agency, agency["payer_regime_default"])
    fields["appointment_id"] = appointment["id"]
    fields["total_cents"] = C.NO_SHOW_FEE_CENTS
    _ledger(agency, fields)
    return db.create("assessments", fields)


def create_shortfall_assessment(agency, shortfall_cents):
    """The onsite shortfall is always AGENCY_BILLED (PRD 3.2)."""
    fields = _blank("ONSITE_SHORTFALL", agency, "AGENCY_BILLED")
    fields["total_cents"] = shortfall_cents
    _ledger(agency, fields)
    return db.create("assessments", fields)
