"""calculations.institution_aggregate_reconciliation -- PRD section 2.7.

Every derived aggregate on an institution is recomputed from scratch from the
underlying rows, never adjusted incrementally.  That is what lets a compensation
(a superseded determination, a voided dividend round) return every aggregate
exactly to its pre-operation value with no accumulated drift.
"""

import lookup
from db import db

LIVE_CERTIFICATE_STATUSES = ("ISSUED", "PARTIALLY_PAID", "PAID")


def total_deposit_balance_cents(institution_id):
    """Sum of balance + accrued interest over every account of the institution,
    with no filter on any of the three status dimensions."""
    return sum(
        a["balance_cents"] + a["accrued_interest_cents"]
        for a in lookup.accounts_of(institution_id)
    )


def depositor_record_count(institution_id):
    return len(lookup.depositors_of(institution_id))


def certified_determinations(institution_id):
    depositor_ids = {d["id"] for d in lookup.depositors_of(institution_id)}
    return [
        det
        for det in db.determinations.values()
        if det["status"] == "CERTIFIED" and det["depositor_record_id"] in depositor_ids
    ]


def aggregate_insured_cents(institution_id):
    return sum(
        det["insured_amount_cents"] for det in certified_determinations(institution_id)
    )


def live_certificates(institution_id):
    return [
        c
        for c in lookup.certificates_of_institution(institution_id)
        if c["status"] in LIVE_CERTIFICATE_STATUSES
    ]


def aggregate_certificate_face_cents(institution_id):
    return sum(c["face_amount_cents"] for c in live_certificates(institution_id))


def uninsured_claim_count(institution_id):
    return len(live_certificates(institution_id))


def settled_distributions(institution_id):
    return [
        d for d in lookup.distributions_of(institution_id) if d["status"] == "SETTLED"
    ]


def dividends_paid_cents(institution_id):
    return sum(d["total_distributed_cents"] for d in settled_distributions(institution_id))


def receivership_cash_cents(institution):
    return (
        institution["gross_disposition_proceeds_cents"]
        - institution["disposition_expense_total_cents"]
        - dividends_paid_cents(institution["id"])
    )


def dividend_round_count(institution_id):
    return len(
        [
            d
            for d in lookup.distributions_of(institution_id)
            if d["status"] in ("DECLARED", "SETTLED")
        ]
    )


def derived(institution):
    """The recomputed aggregate block shared by the institution serializer and
    the insurance-summary read."""
    institution_id = institution["id"]
    return {
        "total_deposit_balance_cents": total_deposit_balance_cents(institution_id),
        "depositor_record_count": depositor_record_count(institution_id),
        "aggregate_insured_cents": aggregate_insured_cents(institution_id),
        "aggregate_certificate_face_cents": aggregate_certificate_face_cents(
            institution_id
        ),
        "uninsured_claim_count": uninsured_claim_count(institution_id),
        "receivership_cash_cents": receivership_cash_cents(institution),
        "gross_disposition_proceeds_cents": institution[
            "gross_disposition_proceeds_cents"
        ],
        "disposition_expense_total_cents": institution[
            "disposition_expense_total_cents"
        ],
        "dividend_round_count": dividend_round_count(institution_id),
    }


def insurance_summary(institution):
    """The computed read of PRD section 2.8, including both conservation deltas."""
    institution_id = institution["id"]
    accounts = lookup.accounts_of(institution_id)
    agg = derived(institution)

    attributed_total = sum(a["attributed_amount_cents"] for a in accounts)
    held_total = sum(a["held_amount_cents"] for a in accounts)

    certified_side = 0
    for depositor in lookup.depositors_of(institution_id):
        has_certified = any(
            det["status"] == "CERTIFIED"
            for det in lookup.determinations_of_depositor(depositor["id"])
        )
        if has_certified:
            certified_side += (
                depositor["certified_insured_cents"]
                + depositor["certified_uninsured_cents"]
            )
    conservation_delta = certified_side - (
        agg["aggregate_insured_cents"] + agg["aggregate_certificate_face_cents"]
    )

    non_cancelled_dividends = sum(
        c["cumulative_dividends_cents"]
        for c in lookup.certificates_of_institution(institution_id)
        if c["status"] != "CANCELLED"
    )
    subrogation_paid = sum(
        d["total_distributed_cents"]
        for d in settled_distributions(institution_id)
        if d["priority_class"] == "INSURED_SUBROGATION"
    )
    dividends_paid = dividends_paid_cents(institution_id)
    cash_delta = (
        agg["gross_disposition_proceeds_cents"]
        - agg["disposition_expense_total_cents"]
    ) - (
        agg["receivership_cash_cents"] + non_cancelled_dividends + subrogation_paid
    )

    return {
        "institution_id": institution_id,
        "total_deposit_balance_cents": agg["total_deposit_balance_cents"],
        "attributed_total_cents": attributed_total,
        "unattributed_balance_cents": agg["total_deposit_balance_cents"]
        - attributed_total,
        "conservation_delta_cents": conservation_delta,
        "aggregate_insured_cents": agg["aggregate_insured_cents"],
        "aggregate_certificate_face_cents": agg["aggregate_certificate_face_cents"],
        "uninsured_claim_count": agg["uninsured_claim_count"],
        "held_amount_total_cents": held_total,
        "receivership_cash_cents": agg["receivership_cash_cents"],
        "gross_disposition_proceeds_cents": agg["gross_disposition_proceeds_cents"],
        "disposition_expense_total_cents": agg["disposition_expense_total_cents"],
        "dividends_paid_cents": dividends_paid,
        "cash_conservation_delta_cents": cash_delta,
    }
