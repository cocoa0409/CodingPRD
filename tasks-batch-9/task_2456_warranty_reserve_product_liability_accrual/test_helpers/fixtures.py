"""Composite setup helpers and pytest fixtures.

The harness restarts the API server before every test, so every helper here
builds the world it needs from an empty database. Setup calls go through
`get_success_data`, which raises a readable AssertionError when a setup step
fails, so a broken precondition never masquerades as a failing assertion.
"""

from typing import Any, Dict, List, Optional, Tuple

import pytest
from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import WarrantyApiClient
from .constants import DEFAULT_CLOCK_ISO
from .test_users import (
    ACTUARY_HEADERS,
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    CONTROLLER_HEADERS,
    ENGINEER_HEADERS,
    make_supplier_rep_headers,
)


# ---------------------------------------------------------------------------
# Client + header fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def api() -> WarrantyApiClient:
    return WarrantyApiClient()


@pytest.fixture
def analyst() -> Dict[str, str]:
    return ANALYST_HEADERS


@pytest.fixture
def controller() -> Dict[str, str]:
    return CONTROLLER_HEADERS


@pytest.fixture
def engineer() -> Dict[str, str]:
    return ENGINEER_HEADERS


@pytest.fixture
def actuary() -> Dict[str, str]:
    return ACTUARY_HEADERS


@pytest.fixture
def admin() -> Dict[str, str]:
    return ADMIN_HEADERS


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
def move_clock(api: WarrantyApiClient, to_iso8601: str) -> None:
    """Advance the logical clock (PlatformAdmin only)."""
    get_success_data(api.set_clock(ADMIN_HEADERS, to_iso8601=to_iso8601))


def reset_clock(api: WarrantyApiClient) -> None:
    """Move the clock back to the PRD's pre-set reading."""
    move_clock(api, DEFAULT_CLOCK_ISO)


# ---------------------------------------------------------------------------
# Accrual periods
# ---------------------------------------------------------------------------
def create_period(
    api: WarrantyApiClient,
    period_code: str = "2026-Q3",
    period_start_date: str = "2026-07-01",
    period_end_date: str = "2026-09-30",
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = factories.period_payload(
        period_code=period_code,
        period_start_date=period_start_date,
        period_end_date=period_end_date,
        **overrides,
    )
    return get_success_data(
        api.create_period_raw(headers or CONTROLLER_HEADERS, payload), expected_status=201
    )


def read_period(api: WarrantyApiClient, period_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_period(CONTROLLER_HEADERS, period_id))


def period_version(api: WarrantyApiClient, period_id: str) -> int:
    """Current `version` of a period, for the OCC guard fields."""
    return read_period(api, period_id)["version"]


def lock_period(api: WarrantyApiClient, period_id: str) -> Dict[str, Any]:
    return get_success_data(api.lock_analysis(CONTROLLER_HEADERS, period_id))


def open_review(api: WarrantyApiClient, period_id: str) -> Dict[str, Any]:
    return get_success_data(api.open_actuarial_review(CONTROLLER_HEADERS, period_id))


def locked_period(api: WarrantyApiClient, **kwargs: Any) -> Dict[str, Any]:
    """A period already at ANALYSIS_LOCKED."""
    period = create_period(api, **kwargs)
    return lock_period(api, period["id"])


def review_period(api: WarrantyApiClient, **kwargs: Any) -> Dict[str, Any]:
    """A period already at ACTUARIAL_REVIEW."""
    period = create_period(api, **kwargs)
    lock_period(api, period["id"])
    return open_review(api, period["id"])


def generate_rollforward(api: WarrantyApiClient, period_id: str) -> Dict[str, Any]:
    version = period_version(api, period_id)
    return get_success_data(
        api.generate_rollforward(CONTROLLER_HEADERS, period_id, expected_period_version=version),
        expected_status=201,
    )


# ---------------------------------------------------------------------------
# Families, vintages, failure modes, observations
# ---------------------------------------------------------------------------
def create_family(
    api: WarrantyApiClient, headers: Optional[Dict[str, str]] = None, **overrides: Any
) -> Dict[str, Any]:
    payload = factories.family_payload(**overrides)
    return get_success_data(
        api.create_product_family_raw(headers or ANALYST_HEADERS, payload), expected_status=201
    )


def read_family(api: WarrantyApiClient, family_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_product_family(ANALYST_HEADERS, family_id))


def patch_family(
    api: WarrantyApiClient, family_id: str, payload: Dict[str, Any]
) -> Dict[str, Any]:
    return get_success_data(api.update_product_family(ANALYST_HEADERS, family_id, payload))


def create_vintage(
    api: WarrantyApiClient, family_id: str, headers: Optional[Dict[str, str]] = None, **overrides: Any
) -> Dict[str, Any]:
    payload = factories.vintage_payload(family_id, **overrides)
    return get_success_data(
        api.create_vintage_raw(headers or ANALYST_HEADERS, payload), expected_status=201
    )


def read_vintage(api: WarrantyApiClient, vintage_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_vintage(ANALYST_HEADERS, vintage_id))


def create_failure_mode(
    api: WarrantyApiClient, family_id: str, headers: Optional[Dict[str, str]] = None, **overrides: Any
) -> Dict[str, Any]:
    payload = factories.failure_mode_payload(family_id, **overrides)
    return get_success_data(
        api.create_failure_mode_raw(headers or ANALYST_HEADERS, payload), expected_status=201
    )


def create_observation(
    api: WarrantyApiClient,
    vintage_id: str,
    failure_mode_id: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = factories.claim_observation_payload(vintage_id, failure_mode_id, **overrides)
    return get_success_data(
        api.create_claim_observation_raw(headers or ANALYST_HEADERS, payload), expected_status=201
    )


def read_observation(api: WarrantyApiClient, observation_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_claim_observation(ANALYST_HEADERS, observation_id))


# ---------------------------------------------------------------------------
# Composite: a family whose history classifies as MATURE
# ---------------------------------------------------------------------------
def mature_family(
    api: WarrantyApiClient,
    period_code: str = "2026-Q3",
    units_shipped: int = 10000,
    observed_months_to: int = 12,
    claim_count: int = 100,
    paid_cost_cents: int = 1000000,
    cost_per_claim_cents: int = 15000,
    warranty_expiry_date: str = "2027-12-31",
    **family_overrides: Any,
) -> Dict[str, Any]:
    """Family + one vintage + one failure mode + one observation.

    The single observation pushes `observed_history_months` to
    `observed_months_to` and the vintage supplies `observed_exposure_units`, so
    the caller controls both maturity inputs directly.

    Returns {"family", "vintage", "failure_mode", "observation"} freshly read
    back so the computed exposure metrics are current.
    """
    family = create_family(api, **family_overrides)
    vintage = create_vintage(
        api,
        family["id"],
        units_shipped=units_shipped,
        ship_period_code=period_code,
        warranty_expiry_date=warranty_expiry_date,
    )
    mode = create_failure_mode(api, family["id"], cost_per_claim_cents=cost_per_claim_cents)
    observation = create_observation(
        api,
        vintage["id"],
        mode["id"],
        observation_period_code=period_code,
        months_in_service_from=0,
        months_in_service_to=observed_months_to,
        claim_count=claim_count,
        paid_cost_cents=paid_cost_cents,
    )
    return {
        "family": read_family(api, family["id"]),
        "vintage": read_vintage(api, vintage["id"]),
        "failure_mode": mode,
        "observation": observation,
    }


def observed_modes_family(
    api: WarrantyApiClient,
    period_code: str,
    units_shipped: int,
    modes: List[Tuple[str, int, int]],
    observed_months_to: int = 12,
    paid_cost_cents: int = 0,
    warranty_expiry_date: str = "2027-12-31",
    **family_overrides: Any,
) -> Dict[str, Any]:
    """Family + one vintage + several failure modes, each with one observation.

    `modes` carries (mode_code, cost_per_claim_cents, claim_count) triples; the
    observation buckets are laid out back to back so they never intersect. The
    whole paid cost is attached to the first observation.
    """
    family = create_family(api, **family_overrides)
    vintage = create_vintage(
        api,
        family["id"],
        units_shipped=units_shipped,
        ship_period_code=period_code,
        warranty_expiry_date=warranty_expiry_date,
    )
    created_modes = []
    observations = []
    for index, (mode_code, cost_per_claim_cents, claim_count) in enumerate(modes):
        mode = create_failure_mode(
            api,
            family["id"],
            mode_code=mode_code,
            cost_per_claim_cents=cost_per_claim_cents,
        )
        created_modes.append(mode)
        observations.append(
            create_observation(
                api,
                vintage["id"],
                mode["id"],
                observation_period_code=period_code,
                months_in_service_from=0,
                months_in_service_to=observed_months_to,
                claim_count=claim_count,
                paid_cost_cents=paid_cost_cents if index == 0 else 0,
            )
        )
    return {
        "family": read_family(api, family["id"]),
        "vintage": read_vintage(api, vintage["id"]),
        "failure_modes": created_modes,
        "observations": observations,
    }


# ---------------------------------------------------------------------------
# Warranty accruals
# ---------------------------------------------------------------------------
def create_accrual(
    api: WarrantyApiClient,
    period_id: str,
    vintage_id: str,
    method: str = "HISTORICAL_RATE",
    elapsed_exposure_bps: int = 5000,
    headers: Optional[Dict[str, str]] = None,
    expected_period_version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    version = (
        expected_period_version
        if expected_period_version is not None
        else period_version(api, period_id)
    )
    payload = factories.accrual_payload(
        period_id,
        vintage_id,
        version,
        method=method,
        elapsed_exposure_bps=elapsed_exposure_bps,
        **overrides,
    )
    return get_success_data(
        api.create_accrual_raw(headers or ANALYST_HEADERS, payload), expected_status=201
    )


def read_accrual(api: WarrantyApiClient, accrual_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_accrual(ANALYST_HEADERS, accrual_id))


def propose_accrual(
    api: WarrantyApiClient, accrual_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(api.propose_accrual(headers or ANALYST_HEADERS, accrual_id))


def post_accrual(
    api: WarrantyApiClient, accrual_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(api.post_accrual(headers or CONTROLLER_HEADERS, accrual_id))


def posted_accrual(
    api: WarrantyApiClient,
    period_id: str,
    vintage_id: str,
    method: str = "HISTORICAL_RATE",
    elapsed_exposure_bps: int = 5000,
    propose_headers: Optional[Dict[str, str]] = None,
    post_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Create → propose → post, with the period already at ANALYSIS_LOCKED."""
    accrual = create_accrual(
        api, period_id, vintage_id, method=method, elapsed_exposure_bps=elapsed_exposure_bps
    )
    propose_accrual(api, accrual["id"], headers=propose_headers)
    return post_accrual(api, accrual["id"], headers=post_headers)


# ---------------------------------------------------------------------------
# Adequacy reviews
# ---------------------------------------------------------------------------
def create_adequacy_review(
    api: WarrantyApiClient,
    period_id: str,
    family_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    payload = factories.adequacy_review_payload(period_id, family_id)
    return get_success_data(
        api.create_adequacy_review_raw(headers or ANALYST_HEADERS, payload), expected_status=201
    )


def apply_true_up(
    api: WarrantyApiClient, review_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(api.apply_true_up(headers or CONTROLLER_HEADERS, review_id))


# ---------------------------------------------------------------------------
# Field actions
# ---------------------------------------------------------------------------
def create_field_action(
    api: WarrantyApiClient, family_id: str, headers: Optional[Dict[str, str]] = None, **overrides: Any
) -> Dict[str, Any]:
    payload = factories.field_action_payload(family_id, **overrides)
    return get_success_data(
        api.create_field_action_raw(headers or ENGINEER_HEADERS, payload), expected_status=201
    )


def read_field_action(api: WarrantyApiClient, field_action_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_field_action(ENGINEER_HEADERS, field_action_id))


def create_remedy_option(
    api: WarrantyApiClient,
    field_action_id: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = factories.remedy_option_payload(**overrides)
    return get_success_data(
        api.create_remedy_option_raw(headers or ENGINEER_HEADERS, field_action_id, payload),
        expected_status=201,
    )


def select_remedy(
    api: WarrantyApiClient,
    field_action_id: str,
    remedy_option_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    expected_field_action_version: Optional[int] = None,
) -> Dict[str, Any]:
    version = (
        expected_field_action_version
        if expected_field_action_version is not None
        else read_field_action(api, field_action_id)["version"]
    )
    return get_success_data(
        api.select_remedy(
            headers or ENGINEER_HEADERS,
            field_action_id,
            expected_field_action_version=version,
            remedy_option_id=remedy_option_id,
        )
    )


def submit_field_action(
    api: WarrantyApiClient, field_action_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(api.submit_field_action(headers or ENGINEER_HEADERS, field_action_id))


def decide_field_action(
    api: WarrantyApiClient,
    field_action_id: str,
    decision: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.decide_field_action(headers or CONTROLLER_HEADERS, field_action_id, decision=decision)
    )


def field_action_with_selected_remedy(
    api: WarrantyApiClient,
    family_id: str,
    option_overrides: Optional[Dict[str, Any]] = None,
    action_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Field action + one remedy option, explicitly selected.

    Returns {"field_action", "option"} with the action read back after the
    selection so `specific_accrual_cents` and `version` are current.
    """
    action = create_field_action(api, family_id, **(action_overrides or {}))
    option = create_remedy_option(api, action["id"], **(option_overrides or {}))
    selected = select_remedy(api, action["id"], remedy_option_id=option["id"])
    options = get_success_data(api.list_remedy_options(ENGINEER_HEADERS, action["id"]))
    stored_option = next(row for row in options if row["id"] == option["id"])
    return {"field_action": selected, "option": stored_option}


def approved_field_action(
    api: WarrantyApiClient,
    family_id: str,
    option_overrides: Optional[Dict[str, Any]] = None,
    action_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A field action carried all the way to APPROVED.

    The submitter and the decider are distinct actors so the segregation-of-
    duties guard is satisfied.
    """
    built = field_action_with_selected_remedy(
        api, family_id, option_overrides=option_overrides, action_overrides=action_overrides
    )
    submit_field_action(api, built["field_action"]["id"])
    approved = decide_field_action(api, built["field_action"]["id"], "APPROVED")
    return {"field_action": approved, "option": built["option"]}


# ---------------------------------------------------------------------------
# Service contracts
# ---------------------------------------------------------------------------
def create_service_contract(
    api: WarrantyApiClient, family_id: str, headers: Optional[Dict[str, str]] = None, **overrides: Any
) -> Dict[str, Any]:
    payload = factories.service_contract_payload(family_id, **overrides)
    return get_success_data(
        api.create_service_contract_raw(headers or ANALYST_HEADERS, payload), expected_status=201
    )


def read_service_contract(api: WarrantyApiClient, contract_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_service_contract(ANALYST_HEADERS, contract_id))


def cancel_service_contract(
    api: WarrantyApiClient, contract_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(api.cancel_service_contract(headers or ANALYST_HEADERS, contract_id))


# ---------------------------------------------------------------------------
# Suppliers and recoveries
# ---------------------------------------------------------------------------
def create_supplier(
    api: WarrantyApiClient, headers: Optional[Dict[str, str]] = None, **overrides: Any
) -> Dict[str, Any]:
    payload = factories.supplier_payload(**overrides)
    return get_success_data(
        api.create_supplier_raw(headers or ANALYST_HEADERS, payload), expected_status=201
    )


def read_supplier(api: WarrantyApiClient, supplier_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_supplier(ANALYST_HEADERS, supplier_id))


def create_recovery(
    api: WarrantyApiClient,
    supplier_id: str,
    failure_mode_id: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = factories.supplier_recovery_payload(supplier_id, failure_mode_id, **overrides)
    return get_success_data(
        api.create_supplier_recovery_raw(headers or ANALYST_HEADERS, payload), expected_status=201
    )


def read_recovery(api: WarrantyApiClient, recovery_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_supplier_recovery(ANALYST_HEADERS, recovery_id))


def assert_recovery(
    api: WarrantyApiClient,
    recovery_id: str,
    revised_asserted_amount_cents: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.assert_recovery(
            headers or ANALYST_HEADERS,
            recovery_id,
            revised_asserted_amount_cents=revised_asserted_amount_cents,
        )
    )


def respond_recovery(
    api: WarrantyApiClient, recovery_id: str, supplier_id: str, response_note: str = "Under review"
) -> Dict[str, Any]:
    return get_success_data(
        api.respond_recovery(
            make_supplier_rep_headers(supplier_id), recovery_id, response_note=response_note
        )
    )


def close_recovery(
    api: WarrantyApiClient,
    recovery_id: str,
    outcome: str,
    settled_amount_cents: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.close_recovery(
            headers or CONTROLLER_HEADERS,
            recovery_id,
            outcome=outcome,
            settled_amount_cents=settled_amount_cents,
        )
    )


def asserted_recovery(
    api: WarrantyApiClient,
    supplier_id: str,
    failure_mode_id: str,
    asserted_amount_cents: int = 4000000,
    **overrides: Any,
) -> Dict[str, Any]:
    """A recovery claim already moved from DRAFT to ASSERTED."""
    recovery = create_recovery(
        api,
        supplier_id,
        failure_mode_id,
        asserted_amount_cents=asserted_amount_cents,
        **overrides,
    )
    return assert_recovery(api, recovery["id"])


# ---------------------------------------------------------------------------
# Liability reserves
# ---------------------------------------------------------------------------
def create_liability_reserve(
    api: WarrantyApiClient,
    period_id: str,
    family_id: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = factories.liability_reserve_payload(period_id, family_id, **overrides)
    return get_success_data(
        api.create_liability_reserve_raw(headers or ACTUARY_HEADERS, payload), expected_status=201
    )


def read_liability_reserve(api: WarrantyApiClient, reserve_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_liability_reserve(ACTUARY_HEADERS, reserve_id))


def actuarial_decision(
    api: WarrantyApiClient,
    reserve_id: str,
    decision: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.actuarial_decision(headers or ACTUARY_HEADERS, reserve_id, decision=decision)
    )


def book_liability_reserve(
    api: WarrantyApiClient, reserve_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(api.book_liability_reserve(headers or CONTROLLER_HEADERS, reserve_id))


def reviewed_liability_reserve(
    api: WarrantyApiClient, period_id: str, family_id: str, **overrides: Any
) -> Dict[str, Any]:
    """A liability reserve already at ACTUARY_REVIEWED."""
    reserve = create_liability_reserve(api, period_id, family_id, **overrides)
    return actuarial_decision(api, reserve["id"], "REVIEWED")
