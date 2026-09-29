"""calculations.dividend_waterfall_allocation -- PRD section 3.9.

The two priority classes compute a payout in completely different ways.  For a
general-unsecured round the round total is the sum of the payable amounts *after*
each has been rounded individually; summing the entitlements and rounding once is
a different and incorrect answer (PRD section 2.6).
"""

import lookup
from services import aggregates
from util import round_half_up

PRIORITY_CLASSES = ("INSURED_SUBROGATION", "GENERAL_UNSECURED")

PAYABLE_CERTIFICATE_STATUSES = ("ISSUED", "PARTIALLY_PAID")


def eligible_certificates(institution_id):
    """Claims at ISSUED or PARTIALLY_PAID -- CANCELLED and PAID are excluded --
    in created_at ascending order with ties broken by face amount descending."""
    rows = [
        c
        for c in lookup.certificates_of_institution(institution_id)
        if c["status"] in PAYABLE_CERTIFICATE_STATUSES
    ]
    rows.sort(key=lambda c: (c["created_at"], -c["face_amount_cents"], c["_seq"]))
    return rows


def allocate(institution, distribution):
    """Price a declared round without writing anything.

    Returns ``(total_distributed_cents, certificate_count, allocations)`` where
    ``allocations`` is a list of ``(certificate_row, payable_cents)`` pairs in
    payment order.
    """
    rate = distribution["declared_rate_bps"]

    if distribution["priority_class"] == "INSURED_SUBROGATION":
        # The money goes to the insurance fund as subrogee, so no receivership
        # certificate is touched at all and certificate_count stays 0.
        insured = aggregates.aggregate_insured_cents(institution["id"])
        return round_half_up(insured * rate, 10000), 0, []

    allocations = []
    total = 0
    paid_count = 0
    for certificate in eligible_certificates(institution["id"]):
        gross = round_half_up(certificate["face_amount_cents"] * rate, 10000)
        remaining_face = (
            certificate["face_amount_cents"] - certificate["cumulative_dividends_cents"]
        )
        payable = gross if gross < remaining_face else remaining_face
        if payable < 0:
            payable = 0
        allocations.append((certificate, payable))
        total += payable
        if payable > 0:
            paid_count += 1
    return total, paid_count, allocations


def certificate_status_for(certificate):
    """Recompute a certificate's status from its cumulative balance."""
    cumulative = certificate["cumulative_dividends_cents"]
    if cumulative >= certificate["face_amount_cents"]:
        return "PAID"
    if cumulative > 0:
        return "PARTIALLY_PAID"
    return "ISSUED"
