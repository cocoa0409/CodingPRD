"""Payment calculation (SCAFFOLD §1.3; PRD §3.8).

PLC: payment triggers when effective price < reference price.
ARC-CO: revenue guarantee (86% of benchmark) vs actual revenue; rate
capped at 10% of benchmark.
Late-filed reports reduce the base payment by 10% (applied BEFORE
limitation). Payment limitation attributes through membership share
against the producer's cap. Sequestration withholds 5.7% last.

All monetary math uses Decimal with round-half-up to 2 places; stored
entity money fields are integer cents.
"""

from decimal import Decimal, ROUND_HALF_UP

import db
from errors import ApiError, ERR_PAYMENT_LIMITATION_EXCEEDED

REFERENCE_PRICE = {
    "CORN": Decimal("4.10"),
    "SOYBN": Decimal("9.00"),
    "WHEAT": Decimal("5.50"),
}

PLC_PAYMENT_FACTOR = Decimal("0.85")
ARC_GUARANTEE_FACTOR = Decimal("0.86")
ARC_CAP_FACTOR = Decimal("0.10")
ARC_PAYMENT_FACTOR = Decimal("0.85")
LATE_FILED_FACTOR = Decimal("0.90")
SEQUESTRATION_RATE = Decimal("0.057")

STANDARD_CAP_CENTS = 12500000
SPOUSE_CAP_CENTS = 25000000


def _cents(dollars):
    """Convert a Decimal dollar amount to integer cents, round half-up."""
    return int((dollars * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _round2(dollars):
    return dollars.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _membership_for_enrollment(enrollment):
    """The producer whose payment this is: the enrollment's submitting
    producer is the membership holder on the farm. The submitting producer
    is recorded on the enrollment at submit time."""
    producer_id = enrollment.get("submitted_by_producer_id")
    if producer_id is None:
        return None, None
    for m in db.memberships.values():
        if (m["farm_id"] == enrollment["farm_id"]
                and m["producer_id"] == producer_id
                and m["membership_status"] == "ACTIVE"):
            producer = db.producers.get(producer_id)
            return m, producer
    return None, db.producers.get(producer_id)


def _spouse_cap_applies(farm_id):
    """Spouse rule: two memberships on the farm flagged is_spouse_pair
    raise the cap to 25000000 cents (PRD §3.8)."""
    flagged = [
        m for m in db.memberships.values()
        if m["farm_id"] == farm_id
        and m["membership_status"] == "ACTIVE"
        and m.get("is_spouse_pair")
    ]
    return len(flagged) >= 2


def compute_payment(enrollment, inputs):
    """Compute payment for a CERTIFIED enrollment.

    inputs: dict with national_my_price (Decimal), and for ARC_CO also
    county_actual_yield and benchmark_revenue (Decimal).

    Mutates the enrollment: sets computed_payment_cents and
    sequestration_cents. Raises ERR_PAYMENT_LIMITATION_EXCEEDED when the
    attributable payment would exceed the producer's cap.
    """
    election = db.program_elections.get(enrollment["pinned_election_id"])
    yield_record = db.yield_records.get(enrollment["pinned_yield_record_id"])
    farm = db.farms.get(enrollment["farm_id"])

    commodity = enrollment["commodity"]
    base_acres = Decimal(str(farm.get("total_base_acres", 0)))

    national_my_price = inputs["national_my_price"]

    if election["election_code"] == "PLC":
        reference_price = REFERENCE_PRICE.get(commodity, Decimal("0"))
        # effective price = min(national_my_price, loan_rate); no loan-rate
        # table is declared anywhere in the PRD, so the effective price is
        # the supplied national marketing-year price.
        effective_price = national_my_price
        payment_rate = max(Decimal("0"), reference_price - effective_price)
        aph = Decimal(str(yield_record["aph_yield_bu_per_acre"]))
        base_payment = payment_rate * aph * base_acres * PLC_PAYMENT_FACTOR
    else:  # ARC_CO (and ARC_IC computed via the county formula inputs)
        benchmark_revenue = inputs["benchmark_revenue"]
        county_actual_yield = inputs["county_actual_yield"]
        guarantee = benchmark_revenue * ARC_GUARANTEE_FACTOR
        actual_revenue = county_actual_yield * national_my_price
        payment_rate = min(
            ARC_CAP_FACTOR * benchmark_revenue,
            max(Decimal("0"), guarantee - actual_revenue),
        )
        base_payment = payment_rate * base_acres * ARC_PAYMENT_FACTOR

    # Late-filed reduction applies BEFORE payment limitation (PRD §3.8).
    # A report that was filed late (filed_at past the reporting deadline)
    # carries the 10% reduction downstream even after certification, per
    # PRD §3.3: "a LATE_FILED report carries a downstream payment
    # reduction of ten percent."
    report = None
    for r in db.acreage_reports.values():
        if (r["farm_id"] == enrollment["farm_id"]
                and r["program_year"] == enrollment["program_year"]
                and r["report_status"] in ("FILED", "LATE_FILED", "CERTIFIED")):
            report = r
            break
    if report is not None and report.get("filed_at") is not None:
        from clock import _parse_iso
        if _parse_iso(report["filed_at"]) > _parse_iso("2026-07-15T23:59:59Z"):
            base_payment = base_payment * LATE_FILED_FACTOR

    base_payment = _round2(base_payment)

    # Payment limitation: attribute through membership share (PRD §3.8).
    membership, producer = _membership_for_enrollment(enrollment)
    if membership is None or producer is None:
        raise ApiError(
            ERR_PAYMENT_LIMITATION_EXCEEDED,
            "No ACTIVE membership for the enrolling producer on this farm",
            422,
        )

    share = Decimal(str(membership["share_percent"]))
    attributable = _round2(base_payment * share / Decimal("100"))

    cap_cents = producer["payment_limitation_cap_cents"]
    if _spouse_cap_applies(enrollment["farm_id"]):
        cap_cents = max(cap_cents, SPOUSE_CAP_CENTS)
    cap_dollars = Decimal(cap_cents) / Decimal("100")

    if attributable > cap_dollars:
        raise ApiError(
            ERR_PAYMENT_LIMITATION_EXCEEDED,
            "Computed payment exceeds producer payment-limitation cap",
            422,
        )
    allowed = min(attributable, cap_dollars)

    # Sequestration: final withholding (PRD §3.8).
    sequestration = _round2(allowed * SEQUESTRATION_RATE)
    net = _round2(allowed - sequestration)

    enrollment["sequestration_cents"] = _cents(sequestration)
    enrollment["computed_payment_cents"] = _cents(net)
