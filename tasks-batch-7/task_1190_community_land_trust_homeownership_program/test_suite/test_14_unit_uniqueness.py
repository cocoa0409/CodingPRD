"""Unit uniqueness — at most one ACTIVE lease per unit (ERR_UNIT_OCCUPIED)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_lease_payload,
    create_program_payload,
    create_unit_payload,
    get_success_data,
    setup_active_lease,
    setup_eligible_household,
    setup_program,
    validate_error,
    validate_error_is_one_of,
)


def _lm():
    return TEST_USERS["lease_manager_headers"]


def _pga():
    return TEST_USERS["program_admin_headers"]


def _activate_second_lease_on_same_unit():
    """Build program + unit with one ACTIVE lease, then attempt to activate a
    second draft lease against the same unit."""
    prog = setup_program(name="P-UO")
    # Build first ACTIVE lease on unit 1.
    _, unit1, _, lease1 = setup_active_lease(prog["id"])
    # Second household, eligible.
    hh2, _, _ = setup_eligible_household(
        prog["id"], verified_income_cents=6_000_000, household_size=4, legal_name="H2"
    )
    # Draft a second lease against the same unit.
    lease2 = get_success_data(
        api_client.create_lease(
            prog["id"],
            unit1["id"],
            create_lease_payload(
                household_id=hh2["id"], start_date="2026-05-15T00:00:00Z"
            ),
            _lm(),
        )
    )
    unit_now = get_success_data(api_client.get_unit(prog["id"], unit1["id"], _lm()))
    resp = api_client.activate_lease(
        prog["id"],
        unit1["id"],
        lease2["id"],
        {"expected_unit_version": unit_now["version"]},
        _lm(),
    )
    return prog, unit1, lease1, lease2, resp


def test_second_lease_activation_on_occupied_unit_returns_unit_occupied():
    """PRD §3.3: "The unit itself must not already have another active lease —
    the symmetric check, which returns `ERR_UNIT_OCCUPIED`."

    On an OCCUPIED unit with an ACTIVE lease, two §3.3 guards fail at once:
    the occupancy check ("`occupancy_status` must be `VACANT` or ...
    `UNDER_CONTRACT` (otherwise `ERR_UNIT_BLOCKED`)") and the symmetric
    active-lease check (`ERR_UNIT_OCCUPIED`). PRD names both errors for this
    overlap without pinning which pre-empts, so either is accepted here.

    Design: Difficulty/resource_temporal_overlap/ground_lease_term_date_overlap_via_unit_uniqueness
    """
    prog, unit, lease1, lease2, resp = _activate_second_lease_on_same_unit()
    validate_error_is_one_of(
        resp,
        [ApiErrorId.ERR_UNIT_OCCUPIED.value, ApiErrorId.ERR_UNIT_BLOCKED.value],
    )

    # Both leases unchanged.
    l1_after = get_success_data(
        api_client.get_lease(prog["id"], unit["id"], lease1["id"], _lm())
    )
    l2_after = get_success_data(
        api_client.get_lease(prog["id"], unit["id"], lease2["id"], _lm())
    )
    assert l1_after["status"] == "ACTIVE"
    assert l2_after["status"] == "DRAFT"


def test_unit_occupancy_status_unchanged_on_rejected_second_activation():
    """PRD §3.3: "A successful activation performs a bundle of side effects
    atomically: ... the unit's `occupancy_status` becomes `OCCUPIED` and its
    `current_lease_id` is set to the new lease..."
    PRD §3.3: "The unit itself must not already have another active lease —
    the symmetric check, which returns `ERR_UNIT_OCCUPIED`."

    A rejected second activation leaves the unit's occupancy and current
    lease pointer untouched.

    Design: Difficulty/resource_temporal_overlap/ground_lease_term_date_overlap_via_unit_uniqueness
    """
    prog, unit, lease1, lease2, resp = _activate_second_lease_on_same_unit()
    validate_error_is_one_of(
        resp,
        [ApiErrorId.ERR_UNIT_OCCUPIED.value, ApiErrorId.ERR_UNIT_BLOCKED.value],
    )

    unit_after = get_success_data(api_client.get_unit(prog["id"], unit["id"], _lm()))
    assert unit_after["occupancy_status"] == "OCCUPIED"
    assert unit_after["current_lease_id"] == lease1["id"]
