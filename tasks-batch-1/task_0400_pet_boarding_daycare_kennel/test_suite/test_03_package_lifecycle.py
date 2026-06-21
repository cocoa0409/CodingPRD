"""Prepaid package cyclic lifecycle: ACTIVE -> EXPIRED -> ACTIVE and renewal guards.

Translates difficulty (A) non_linear_state_machine/package_cyclic_expired_to_active_renew
and corner (B) state-machine instances for renew preconditions.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    create_package, create_facility, create_owner,
    setup_expired_package,
    TEST_USERS,
)

MGR = TEST_USERS["manager_headers"]


def test_package_cycles_expired_then_renews_to_active(api):
    """PRD §3.7: "During a clock advance, an `ACTIVE` package whose 30-day cycle has
    lapsed — that is, when the facility's `current_date` is more than 30 days after the
    package's `cycle_start_date` — transitions to `EXPIRED`".
    PRD §3.7: "A successful renew sets `cycle_start_date` to the facility's current
    `current_date`, resets `credits_remaining` to `credits_total`, and increments
    `version` by one; the same package row may therefore visit `ACTIVE` more than once
    over its life."

    DAYCARE_10 (auto_renew) expired via clock, then renewed -> ACTIVE, credits 10.

    Design: Difficulty/non_linear_state_machine/package_cyclic_expired_to_active_renew
    """
    facility, owner, package = setup_expired_package(auto_renew=True, to_date="2026-02-15")
    assert package["status"] == "EXPIRED"
    renewed = validate_success(api.renew_package(package["id"], MGR), 200)
    assert renewed["status"] == "ACTIVE", "renew re-arms EXPIRED package to ACTIVE"
    assert renewed["credits_remaining"] == 10, "credits reset to credits_total (10) on renew"


def test_package_active_to_expired_on_clock(api):
    """PRD §3.7: "During a clock advance, an `ACTIVE` package whose 30-day cycle has
    lapsed — that is, when the facility's `current_date` is more than 30 days after the
    package's `cycle_start_date` — transitions to `EXPIRED`, its `credits_remaining`
    frozen and no further redemptions permitted until it is renewed".

    Design: Difficulty/non_linear_state_machine/package_cyclic_expired_to_active_renew
    """
    facility, owner, package = setup_expired_package(auto_renew=True, to_date="2026-02-15")
    assert package["status"] == "EXPIRED", "30-day cycle lapsed -> EXPIRED"
    assert package["credits_remaining"] == 10, "credits frozen at full on expiry (none consumed)"


def test_renew_active_package_rejected_invalid_state(api):
    """PRD §3.7: "Renewal re-arms an expired package: an owner or manager renews a
    package, but only from `EXPIRED` (a renew from any other state is rejected with
    `ERR_INVALID_STATE`)".

    Design: Corner/state_machines/renew_active_package_invalid_state
    """
    facility = create_facility()
    owner = create_owner(facility["id"])
    package = create_package(owner["id"], auto_renew=True)
    assert package["status"] == "ACTIVE"
    res = api.renew_package(package["id"], MGR)
    validate_error(res, "ERR_INVALID_STATE")


def test_renew_expired_without_autorenew_rejected(api):
    """PRD §3.7: "and only when the package's `auto_renew` is true (otherwise the renew
    is rejected with `ERR_RENEWAL_NOT_ALLOWED`)".

    Design: Corner/state_machines/renew_expired_without_autorenew_rejected
    """
    facility, owner, package = setup_expired_package(auto_renew=False, to_date="2026-02-15")
    assert package["status"] == "EXPIRED"
    res = api.renew_package(package["id"], MGR)
    validate_error(res, "ERR_RENEWAL_NOT_ALLOWED")
