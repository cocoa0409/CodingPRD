"""Payload factories — one per entity, client-supplied input fields only."""

from .constants import DEFAULT_CLOCK_UTC, TEST_DEFAULTS

DEFAULTS = {
    "CUSTODIAN_NAME": "First Custody Bank",
    "POOL_NAME": "Ohio Public Funds Pool",
    "PUBLIC_UNIT_NAME": "Ridge County",
    "DEPOSITORY_NAME": "Ridge National Bank",
    "STATE": TEST_DEFAULTS["JURISDICTION_STATE"],
    "AGREEMENT_NUMBER": "AG-0001",
    "CUSIP": "912828CC3",
    "RECEIPT_NUMBER": "RCPT-0001",
}


def create_custodian_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["CUSTODIAN_NAME"],
        "custodian_type": "TRUST_BANK",
        "tri_party_capable": True,
        "concentration_limit_bps": 10000,
    }
    payload.update(overrides)
    return payload


def create_pooled_program_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["POOL_NAME"],
        "administrator_state": DEFAULTS["STATE"],
        "minimum_pool_pct_bps": 11000,
    }
    payload.update(overrides)
    return payload


def create_public_unit_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["PUBLIC_UNIT_NAME"],
        "unit_type": "COUNTY",
        "jurisdiction_state": DEFAULTS["STATE"],
        "statutory_max_deposit_cents": TEST_DEFAULTS["STATUTORY_MAX_DEPOSIT_CENTS"],
        "collateral_program_preference": "DEDICATED",
        "reporting_frequency": "MONTHLY",
    }
    payload.update(overrides)
    return payload


def create_depository_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["DEPOSITORY_NAME"],
        "charter_type": "STATE_CHARTERED",
        "home_state": DEFAULTS["STATE"],
        "capital_ratio_bps": 1200,
        "insurance_determination_basis": "AGGREGATED_BY_UNIT",
    }
    payload.update(overrides)
    return payload


def create_qualification_review_payload(**overrides) -> dict:
    payload = {
        "requested_pledge_capacity_cents": TEST_DEFAULTS[
            "REQUESTED_PLEDGE_CAPACITY_CENTS"
        ],
    }
    payload.update(overrides)
    return payload


def attest_payload(**overrides) -> dict:
    payload = {"attestation_note": "Package complete"}
    payload.update(overrides)
    return payload


def return_for_info_payload(**overrides) -> dict:
    payload = {"info_request_note": "Provide audited call report"}
    payload.update(overrides)
    return payload


def decide_payload(decision="APPROVE", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def create_deposit_account_payload(depository_id, public_unit_id, **overrides) -> dict:
    payload = {
        "depository_id": depository_id,
        "public_unit_id": public_unit_id,
        "deposit_class": "DEMAND",
        "pledging_mode": "DEDICATED",
    }
    payload.update(overrides)
    return payload


def amount_payload(amount_cents, **overrides) -> dict:
    payload = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def create_pledge_agreement_payload(depository_id, custodian_id, **overrides) -> dict:
    payload = {
        "depository_id": depository_id,
        "custodian_id": custodian_id,
        "beneficiary_type": "DEPOSIT_ACCOUNT",
        "agreement_number": DEFAULTS["AGREEMENT_NUMBER"],
        "governing_law_state": DEFAULTS["STATE"],
    }
    payload.update(overrides)
    return payload


def signature_payload(party, **overrides) -> dict:
    payload = {"party": party}
    payload.update(overrides)
    return payload


def create_collateral_asset_payload(depository_id, custodian_id, **overrides) -> dict:
    payload = {
        "depository_id": depository_id,
        "custodian_id": custodian_id,
        "cusip": DEFAULTS["CUSIP"],
        "asset_type": "US_TREASURY",
        "par_value_cents": 10_000_000,
        "market_price_bps": 10000,
    }
    payload.update(overrides)
    return payload


def price_payload(market_price_bps, **overrides) -> dict:
    payload = {"market_price_bps": market_price_bps}
    payload.update(overrides)
    return payload


def mark_ineligible_payload(**overrides) -> dict:
    payload = {"ineligible_reason": "Withdrawn from the eligible collateral list"}
    payload.update(overrides)
    return payload


def create_pledge_allocation_payload(
    pledge_agreement_id,
    collateral_asset_id,
    allocated_par_cents,
    expected_pledge_agreement_version,
    effective_from=DEFAULT_CLOCK_UTC,
    **overrides,
) -> dict:
    payload = {
        "pledge_agreement_id": pledge_agreement_id,
        "collateral_asset_id": collateral_asset_id,
        "allocated_par_cents": allocated_par_cents,
        "effective_from": effective_from,
        "expected_pledge_agreement_version": expected_pledge_agreement_version,
    }
    payload.update(overrides)
    return payload


def create_substitution_request_payload(
    pledge_agreement_id,
    outgoing_allocation_id,
    incoming_asset_id,
    incoming_par_cents,
    **overrides,
) -> dict:
    payload = {
        "pledge_agreement_id": pledge_agreement_id,
        "outgoing_allocation_id": outgoing_allocation_id,
        "incoming_asset_id": incoming_asset_id,
        "incoming_par_cents": incoming_par_cents,
    }
    payload.update(overrides)
    return payload


def reject_substitution_payload(**overrides) -> dict:
    payload = {"rejection_reason": "Incoming security is not acceptable"}
    payload.update(overrides)
    return payload


def create_mtm_run_payload(
    window_start, window_end, expected_depository_version, basis="SUPERVISORY", **overrides
) -> dict:
    payload = {
        "window_start": window_start,
        "window_end": window_end,
        "basis": basis,
        "expected_depository_version": expected_depository_version,
    }
    payload.update(overrides)
    return payload


def cure_payload(credited_allocation_ids, **overrides) -> dict:
    payload = {"credited_allocation_ids": list(credited_allocation_ids)}
    payload.update(overrides)
    return payload


def create_safekeeping_receipt_payload(
    pledge_agreement_id, reported_par_cents, reported_asset_count, **overrides
) -> dict:
    payload = {
        "pledge_agreement_id": pledge_agreement_id,
        "receipt_number": DEFAULTS["RECEIPT_NUMBER"],
        "reported_par_cents": reported_par_cents,
        "reported_asset_count": reported_asset_count,
    }
    payload.update(overrides)
    return payload


def create_runoff_forecast_payload(
    deposit_account_id,
    horizon_start,
    horizon_end,
    projected_windows,
    expected_deposit_account_version,
    cycle_label="TAX_COLLECTION",
    basis="PEAK_WINDOW",
    **overrides,
) -> dict:
    payload = {
        "deposit_account_id": deposit_account_id,
        "cycle_label": cycle_label,
        "basis": basis,
        "horizon_start": horizon_start,
        "horizon_end": horizon_end,
        "projected_windows": projected_windows,
        "expected_deposit_account_version": expected_deposit_account_version,
    }
    payload.update(overrides)
    return payload


def projected_window(window_start, window_end, projected_balance_cents) -> dict:
    return {
        "window_start": window_start,
        "window_end": window_end,
        "projected_balance_cents": projected_balance_cents,
    }


def set_clock_payload(to_iso8601=DEFAULT_CLOCK_UTC, **overrides) -> dict:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload
