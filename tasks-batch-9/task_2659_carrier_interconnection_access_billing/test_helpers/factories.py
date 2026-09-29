"""Request payload factories.

Every factory returns a fresh dict of valid field values that the caller can
adjust with keyword overrides, e.g.
``carrier_payload(ocn="8117")``. Numeric fields are emitted as JSON numbers,
never as strings.
"""

from .constants import (
    AGREEMENT_LABEL,
    BATCH_EXCHANGE_REFERENCE_IN,
    BENCHMARK_INTERSTATE_RATE,
    CARRIER_NAME,
    CARRIER_OCN,
    CARRIER_TYPE,
    DOCKET_INTERSTATE,
    FACTOR_QUARTER,
    LATA_DALLAS,
    POI_CAPACITY_TRUNKS,
    POI_CLLI_DALLAS,
    RATE_INTERSTATE,
    RECIPROCAL_RATE,
    REPORTED_PIU_PCT,
    REPORTED_PLU_PCT,
    SECOND_CARRIER_NAME,
    SECOND_CARRIER_OCN,
    SECOND_CARRIER_TYPE,
    T_2026_07_01,
    T_2026_07_31,
    T_2026_08_01,
    T_2026_08_31,
    T_2026_09_15,
    T_2026_10_01,
    T_2027_01_01,
    TERM_MONTHS,
)


def _merge(base, overrides):
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def clock_payload(target_utc, **overrides):
    return _merge({"target_utc": target_utc}, overrides)


# ---------------------------------------------------------------------------
# Carrier
# ---------------------------------------------------------------------------
def carrier_payload(**overrides):
    return _merge(
        {
            "carrier_name": CARRIER_NAME,
            "ocn": CARRIER_OCN,
            "carrier_type": CARRIER_TYPE,
        },
        overrides,
    )


def second_carrier_payload(**overrides):
    return _merge(
        {
            "carrier_name": SECOND_CARRIER_NAME,
            "ocn": SECOND_CARRIER_OCN,
            "carrier_type": SECOND_CARRIER_TYPE,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Agreement and negotiation offers
# ---------------------------------------------------------------------------
def agreement_payload(carrier_id, **overrides):
    return _merge(
        {
            "carrier_id": carrier_id,
            "agreement_label": AGREEMENT_LABEL,
            "proposed_reciprocal_rate_per_mou_usd": RECIPROCAL_RATE,
            "proposed_term_months": TERM_MONTHS,
            "transit_traffic_allowed": False,
            "effective_date": T_2026_08_01,
            "poi_facility_capacity_trunks": POI_CAPACITY_TRUNKS,
        },
        overrides,
    )


def proposal_offer_payload(expected_agreement_version, **overrides):
    return _merge(
        {
            "expected_agreement_version": expected_agreement_version,
            "offer_type": "PROPOSAL",
            "reciprocal_rate_per_mou_usd": RECIPROCAL_RATE,
            "term_months": TERM_MONTHS,
            "poi_financial_responsibility": "SHARED",
            "transit_traffic_allowed": False,
        },
        overrides,
    )


def counter_offer_payload(expected_agreement_version, **overrides):
    return _merge(
        {
            "expected_agreement_version": expected_agreement_version,
            "offer_type": "COUNTER",
            "reciprocal_rate_per_mou_usd": 0.058,
            "term_months": 24,
            "poi_financial_responsibility": "TERMINATOR_PAYS",
            "transit_traffic_allowed": False,
        },
        overrides,
    )


def terminate_agreement_payload(**overrides):
    return _merge(
        {"termination_reason": "Counterparty exited the market at this POI"}, overrides
    )


def withdraw_agreement_payload(**overrides):
    return _merge(
        {"withdrawal_reason": "Commercial terms could not be reconciled"}, overrides
    )


# ---------------------------------------------------------------------------
# Trunk groups, traffic studies and augment orders
# ---------------------------------------------------------------------------
def trunk_group_payload(agreement_id, **overrides):
    return _merge(
        {
            "agreement_id": agreement_id,
            "trunk_group_serial": "TG-DLLS-TWOWAY-001",
            "poi_clli_code": POI_CLLI_DALLAS,
            "lata_code": LATA_DALLAS,
            "poi_type": "MEET_POINT",
            "direction": "TWO_WAY",
            "traffic_type": "LOCAL_INTERCONNECTION",
            "forecast_busy_hour_ccs": 1200.00,
            "forecast_horizon_quarters": 4,
        },
        overrides,
    )


def provision_payload(provisioned_trunks=48, **overrides):
    return _merge({"provisioned_trunks": provisioned_trunks}, overrides)


def measurement_payload(**overrides):
    return _merge(
        {
            "measurement_period_start": T_2026_07_01,
            "measurement_period_end": T_2026_07_31,
            "offered_calls": 10000,
            "blocked_calls": 300,
            "busy_hour_ccs": 2100.00,
        },
        overrides,
    )


def accept_augment_payload(committed_due_date=T_2026_09_15, **overrides):
    return _merge({"committed_due_date": committed_due_date}, overrides)


def reject_augment_payload(**overrides):
    return _merge(
        {"rejection_reason": "No capital available at this POI this quarter"}, overrides
    )


def complete_augment_payload(installed_trunks=24, **overrides):
    return _merge({"installed_trunks": installed_trunks}, overrides)


def reverse_augment_payload(**overrides):
    return _merge(
        {"reversal_reason": "Acceptance testing failed on the new DS1"}, overrides
    )


# ---------------------------------------------------------------------------
# Tariff filings
# ---------------------------------------------------------------------------
def tariff_filing_payload(**overrides):
    return _merge(
        {
            "filing_docket": DOCKET_INTERSTATE,
            "rate_element": "INTERSTATE_SWITCHED_ACCESS",
            "rate_per_mou_usd": RATE_INTERSTATE,
            "benchmark_interstate_rate_per_mou_usd": BENCHMARK_INTERSTATE_RATE,
            "effective_date": T_2026_08_01,
            "expiry_date": T_2027_01_01,
        },
        overrides,
    )


def approve_tariff_filing_payload(**overrides):
    return _merge({}, overrides)


# ---------------------------------------------------------------------------
# Traffic factor filings
# ---------------------------------------------------------------------------
def factor_filing_payload(carrier_id, expected_carrier_version, **overrides):
    return _merge(
        {
            "carrier_id": carrier_id,
            "expected_carrier_version": expected_carrier_version,
            "quarter": FACTOR_QUARTER,
            "reported_piu_pct": REPORTED_PIU_PCT,
            "reported_plu_pct": REPORTED_PLU_PCT,
        },
        overrides,
    )


def factor_review_accept_payload(**overrides):
    return _merge({"decision": "ACCEPT"}, overrides)


def factor_review_dispute_payload(**overrides):
    return _merge(
        {
            "decision": "DISPUTE",
            "dispute_reason": "Reported interstate use is inconsistent with the signalled sample",
        },
        overrides,
    )


def factor_audit_payload(audited_piu_pct=80.00, audited_plu_pct=5.00, **overrides):
    return _merge(
        {"audited_piu_pct": audited_piu_pct, "audited_plu_pct": audited_plu_pct},
        overrides,
    )


# ---------------------------------------------------------------------------
# Usage batches and call detail records
# ---------------------------------------------------------------------------
def usage_batch_payload(carrier_id, **overrides):
    return _merge(
        {
            "carrier_id": carrier_id,
            "period_start": T_2026_08_01,
            "period_end": T_2026_08_31,
            "direction": "TERMINATING_TO_US",
            "exchange_reference": BATCH_EXCHANGE_REFERENCE_IN,
        },
        overrides,
    )


def cdr_payload(**overrides):
    return _merge(
        {
            "originating_npanxx": "214555",
            "terminating_npanxx": "214777",
            "duration_seconds": 180,
            "signaling_cpn_present": True,
            "originating_state_code": "TX",
            "terminating_state_code": "TX",
            "same_local_calling_area": True,
        },
        overrides,
    )


def local_cdr_payload(**overrides):
    """A signalling-determined LOCAL record: same state, shared local calling area."""
    return cdr_payload(**overrides)


def interstate_cdr_payload(**overrides):
    """A signalling-determined INTERSTATE record: origin state differs from termination."""
    return cdr_payload(
        **_merge(
            {
                "terminating_npanxx": "405222",
                "duration_seconds": 61,
                "terminating_state_code": "OK",
                "same_local_calling_area": False,
            },
            overrides,
        )
    )


def intrastate_cdr_payload(**overrides):
    """A signalling-determined INTRASTATE record: same state, different local area."""
    return cdr_payload(
        **_merge(
            {
                "terminating_npanxx": "713444",
                "duration_seconds": 300,
                "same_local_calling_area": False,
            },
            overrides,
        )
    )


def indeterminate_no_cpn_cdr_payload(**overrides):
    """An INDETERMINATE record: Calling Party Number was absent from the signalling."""
    return cdr_payload(
        **_merge(
            {
                "terminating_npanxx": "713444",
                "duration_seconds": 120,
                "signaling_cpn_present": False,
                "same_local_calling_area": False,
            },
            overrides,
        )
    )


def indeterminate_no_origin_cdr_payload(**overrides):
    """An INDETERMINATE record: no originating state code could be derived."""
    payload = cdr_payload(
        **_merge(
            {
                "originating_npanxx": "682555",
                "terminating_npanxx": "713444",
                "duration_seconds": 3600,
                "signaling_cpn_present": False,
                "same_local_calling_area": False,
            },
            overrides,
        )
    )
    payload.pop("originating_state_code", None)
    return payload


def indeterminate_cpn_without_origin_cdr_payload(**overrides):
    """An INDETERMINATE record: CPN was signalled but the origin state is unknown."""
    payload = cdr_payload(
        **_merge(
            {
                "originating_npanxx": "682555",
                "terminating_npanxx": "713444",
                "duration_seconds": 30,
                "signaling_cpn_present": True,
                "same_local_calling_area": False,
            },
            overrides,
        )
    )
    payload.pop("originating_state_code", None)
    return payload


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------
def invoice_payload(usage_batch_id, **overrides):
    return _merge(
        {"usage_batch_id": usage_batch_id, "due_date": T_2026_10_01}, overrides
    )


def payment_payload(amount_usd, **overrides):
    return _merge(
        {"amount_usd": amount_usd, "remittance_reference": "WIRE-2026-09-01-A"},
        overrides,
    )


def write_off_payload(**overrides):
    return _merge(
        {
            "write_off_reason": "Counterparty entered receivership with no distribution expected"
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Billing disputes
# ---------------------------------------------------------------------------
def dispute_payload(invoice_id, **overrides):
    return _merge(
        {
            "invoice_id": invoice_id,
            "disputed_amount_usd": 10.00,
            "reason_code": "RATE_APPLICATION",
            "supporting_detail": "Interstate rate element applied to intrastate minutes on 4 records",
        },
        overrides,
    )


def resolve_sustained_payload(credited_amount_usd, **overrides):
    return _merge(
        {
            "decision": "SUSTAINED",
            "credited_amount_usd": credited_amount_usd,
            "resolution_note": "Jurisdiction factors were misapplied; credit is due",
        },
        overrides,
    )


def resolve_denied_payload(**overrides):
    return _merge(
        {
            "decision": "DENIED",
            "credited_amount_usd": 0.00,
            "resolution_note": "Rate element was applied correctly; no credit is due",
        },
        overrides,
    )


def escalate_dispute_payload(**overrides):
    return _merge(
        {"escalation_note": "First escalation to the interconnection escalation desk"},
        overrides,
    )


def withdraw_dispute_payload(**overrides):
    return _merge(
        {"withdrawal_reason": "Counterparty accepted our rating after further review"},
        overrides,
    )


# ---------------------------------------------------------------------------
# Reconciliation cases
# ---------------------------------------------------------------------------
def reconciliation_case_payload(usage_batch_id, **overrides):
    return _merge(
        {
            "usage_batch_id": usage_batch_id,
            "counterparty_reported_minutes": 63.0000,
            "counterparty_reported_amount_usd": 28.00,
            "exchange_reference": BATCH_EXCHANGE_REFERENCE_IN,
        },
        overrides,
    )


def reconciliation_adjust_payload(agreed_minutes, **overrides):
    return _merge({"agreed_minutes": agreed_minutes}, overrides)


def reconciliation_accept_payload(**overrides):
    return _merge(
        {"acceptance_note": "Variance is within the documented exchange drift"},
        overrides,
    )
