"""Payload factories — one per entity, client-supplied input fields only."""

from .constants import TEST_DEFAULTS

_OPERATOR_SEQ = [0]


def create_operator_payload(**overrides) -> dict:
    """A comfortably self-bond-qualified operator by default.

    tangible_net_worth 16000000.00 against total_liabilities 5120000.00 clears
    the 2.5x leverage condition and the ten-million-dollar net-worth floor.
    """
    _OPERATOR_SEQ[0] += 1
    defaults = {
        "legal_name": f"Ridgeback Mining {_OPERATOR_SEQ[0]}",
        "tangible_net_worth": 16000000.00,
        "fixed_assets_in_state": 7900000.00,
        "total_liabilities": 5120000.00,
        "net_income_prior_year": 640000.00,
        "elected_financial_test": "NET_WORTH_TEST",
    }
    defaults.update(overrides)
    return defaults


def operator_financials_payload(**overrides) -> dict:
    """Any subset of the five financial inputs may be supplied."""
    return dict(overrides)


def create_mine_site_payload(**overrides) -> dict:
    defaults = {
        "name": "Copper Draw Pit",
        "county": "Pinal",
        "total_acres": 300.00,
    }
    defaults.update(overrides)
    return defaults


def nominate_legacy_payload(**overrides) -> dict:
    defaults = {
        "hazard_class": "H2_HIGH",
        "public_safety_score": 40,
        "water_quality_score": 30,
        "acres_affected": 40.00,
        "unfunded_reclamation_need": 350000.00,
    }
    defaults.update(overrides)
    return defaults


def create_inspector_profile_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Ingrid Halvorsen",
        "certification_level": "CERT_II",
        "region": "SOUTH",
    }
    defaults.update(overrides)
    return defaults


def create_permit_payload(mine_site_id, operator_id, **overrides) -> dict:
    defaults = {
        "mine_site_id": mine_site_id,
        "operator_id": operator_id,
        "mining_plan_acres": TEST_DEFAULTS["MINING_PLAN_ACRES"],
        "post_mining_land_use": "RANGELAND",
        "proposed_start_date": TEST_DEFAULTS["PROPOSED_START_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_estimate_payload(permit_id, **overrides) -> dict:
    defaults = {
        "permit_id": permit_id,
        "estimator_firm": TEST_DEFAULTS["ESTIMATOR_FIRM"],
        "estimator_license_no": TEST_DEFAULTS["ESTIMATOR_LICENSE_NO"],
        "estimate_effective_date": TEST_DEFAULTS["ESTIMATE_EFFECTIVE_DATE"],
        "direct_cost_per_acre": TEST_DEFAULTS["DIRECT_COST_PER_ACRE"],
    }
    defaults.update(overrides)
    return defaults


def create_bond_instrument_payload(permit_id, **overrides) -> dict:
    """A CASH instrument by default: no surety and no collateral group."""
    defaults = {
        "permit_id": permit_id,
        "instrument_type": "CASH",
        "face_amount": TEST_DEFAULTS["CASH_FACE_AMOUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_surety_instrument_payload(permit_id, rating="A", **overrides) -> dict:
    defaults = {
        "permit_id": permit_id,
        "instrument_type": "SURETY",
        "face_amount": TEST_DEFAULTS["CASH_FACE_AMOUNT"],
        "surety_company_name": "Cordillera Surety",
        "surety_naic_rating": rating,
    }
    defaults.update(overrides)
    return defaults


def create_collateral_instrument_payload(
    permit_id, collateral_type="US_TREASURY", market_value=900000.00, **overrides
) -> dict:
    defaults = {
        "permit_id": permit_id,
        "instrument_type": "COLLATERAL",
        "face_amount": TEST_DEFAULTS["CASH_FACE_AMOUNT"],
        "collateral_type": collateral_type,
        "collateral_market_value": market_value,
    }
    defaults.update(overrides)
    return defaults


def create_self_bond_instrument_payload(permit_id, face_amount=900000.00, **overrides) -> dict:
    defaults = {
        "permit_id": permit_id,
        "instrument_type": "SELF_BOND",
        "face_amount": face_amount,
    }
    defaults.update(overrides)
    return defaults


def create_release_application_payload(permit_id, **overrides) -> dict:
    defaults = {
        "permit_id": permit_id,
        "phase": "PHASE_I",
        "acres_requested": 30.00,
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(permit_id, inspector_id, **overrides) -> dict:
    defaults = {
        "permit_id": permit_id,
        "inspector_id": inspector_id,
        "inspection_type": "ROUTINE",
        "scheduled_start": "2026-08-10T09:00:00Z",
        "duration_hours": 3,
    }
    defaults.update(overrides)
    return defaults


def create_violation_notice_payload(inspection_id, **overrides) -> dict:
    defaults = {
        "inspection_id": inspection_id,
        "violation_class": "NON_COMPLIANCE",
        "severity_points": 20,
        "negligence_points": 15,
        "duration_points": 10,
        "abatement_days": 30,
    }
    defaults.update(overrides)
    return defaults


def create_permit_revision_payload(permit_id, revision_type="EXPANSION", **overrides) -> dict:
    defaults = {"permit_id": permit_id, "revision_type": revision_type}
    if revision_type == "EXPANSION":
        defaults["acreage_delta"] = 60.00
    elif revision_type == "PMLU_CHANGE":
        defaults["new_post_mining_land_use"] = "WILDLIFE_HABITAT"
    elif revision_type == "SEQUENCE_CHANGE":
        defaults["sequence_note"] = "Reordering the north and south panels."
    defaults.update(overrides)
    return defaults


def create_forfeiture_proceeding_payload(permit_id, **overrides) -> dict:
    defaults = {
        "permit_id": permit_id,
        "initiation_reason": "BOND_DEFICIENCY_UNCURED",
    }
    defaults.update(overrides)
    return defaults
