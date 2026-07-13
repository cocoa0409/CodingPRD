"""Penalty accrual, overdue reconciliation, reminders, and the utility compliance report."""
import pytest

from test_helpers import (
    validate_success, TEST_USERS, factories, fixtures,
)

ADMIN = TEST_USERS["admin_headers"]


# --------------------------------------------------------------------------- #
# Difficulty/combinatorial_formula/penalty_round_per_device_then_sum
# --------------------------------------------------------------------------- #
def _setup_two_overdue_moderate_devices(api):
    """Connection at MODERATE risk with two LOW-hazard devices each exactly 1 day overdue."""
    conn = fixtures.create_connection(api, ADMIN)
    fixtures.create_device(conn["id"], api, ADMIN, serial_number="SN-PEN-A", device_type="RP",
                           hazard_rating="LOW", install_date="2025-03-01T00:00:00Z")
    fixtures.create_device(conn["id"], api, ADMIN, serial_number="SN-PEN-B", device_type="RP",
                           hazard_rating="LOW", install_date="2025-03-01T00:00:00Z")
    fixtures.create_and_finalize_survey(conn["id"], api, ADMIN, premise_use_score=10,
                                        chemical_exposure_score=10, auxiliary_supply_score=30)
    fixtures.set_clock("2026-03-02T00:00:00Z", api, ADMIN)
    return conn


def test_penalty_rounds_per_device_then_sums(api):
    """PRD §3.6: "multiplies the base daily rate of 333 cents by the risk multiplier and by
    those overdue days, and rounds that per-device amount half up to whole cents. The
    per-device whole-cent penalties are then summed into `total_penalty_cents`."
    PRD §2.8: "each overdue device's daily penalty is computed and rounded to whole cents
    individually, and only then are the per-device whole-cent amounts summed into
    `total_penalty_cents`."

    Design: Difficulty/combinatorial_formula/penalty_round_per_device_then_sum
    """
    conn = _setup_two_overdue_moderate_devices(api)
    data = validate_success(api.get_connection(conn["id"], ADMIN))
    assert data["total_penalty_cents"] == 1000, (
        "round(333*1.5*1)=500 per device then summed = 1000 "
        f"(sum-then-round would give 999); got {data['total_penalty_cents']}")


def test_penalty_setup_two_overdue_devices_moderate_tier(api):
    """PRD §2.6: "`overdue_device_count` is the number of devices on the connection whose
    status is `ACTIVE` or `NEEDS_REPAIR` and whose `next_test_due_date` is strictly earlier
    than `current_utc`".
    PRD §3.6: "The penalty applies a risk multiplier drawn from the connection's
    `risk_tier`: 1.0 for `LOW`, 1.5 for `MODERATE`, and 2.0 for `HIGH`."

    Design: Difficulty/combinatorial_formula/penalty_round_per_device_then_sum
    """
    conn = _setup_two_overdue_moderate_devices(api)
    data = validate_success(api.get_connection(conn["id"], ADMIN))
    assert data["overdue_device_count"] == 2, \
        f"both devices overdue by 1 day, got {data['overdue_device_count']}"
    assert data["risk_tier"] == "MODERATE", \
        f"auxiliary=30 floor -> MODERATE, got {data['risk_tier']}"


# --------------------------------------------------------------------------- #
# Difficulty/boundary_precision_check/utility_report_empty_pool_rate_zero
# --------------------------------------------------------------------------- #
def test_utility_report_empty_pool_rate_zero(api):
    """PRD §3.7: "as an empty-pool boundary, when there are no connections in the pool the
    rate is exactly 0.00 with no division performed."
    PRD §3.7: "returns `total_connections` (the size of the pool)".

    Design: Difficulty/boundary_precision_check/utility_report_empty_pool_rate_zero
    """
    data = validate_success(api.utility_report(ADMIN))
    assert data["total_connections"] == 0, \
        f"empty database -> 0 connections, got {data['total_connections']}"
    assert data["compliance_rate"] == pytest.approx(0.00, abs=0.001), \
        f"empty pool -> compliance_rate 0.00, got {data['compliance_rate']}"


def test_utility_report_empty_pool_counts_zero(api):
    """PRD §3.7: "returns `total_connections` (the size of the pool), `compliant_count`
    (connections whose posture is `COMPLIANT`), `non_compliant_count` (connections whose
    posture is `NON_COMPLIANT` or `SHUTOFF`), and `compliance_rate`."

    Design: Difficulty/boundary_precision_check/utility_report_empty_pool_rate_zero
    """
    data = validate_success(api.utility_report(ADMIN))
    assert data["compliant_count"] == 0, f"got {data['compliant_count']}"
    assert data["non_compliant_count"] == 0, f"got {data['non_compliant_count']}"


# --------------------------------------------------------------------------- #
# Corner/endpoints/utility_report_counts_populated_pool
# --------------------------------------------------------------------------- #
def test_utility_report_counts_single_compliant_connection(api):
    """PRD §3.7: "The compliance rate is the compliant count divided by the total,
    multiplied by 100 and rounded half up to two decimal places".
    PRD §3.7: "`compliant_count` (connections whose posture is `COMPLIANT`),
    `non_compliant_count` (connections whose posture is `NON_COMPLIANT` or `SHUTOFF`)".

    Design: Corner/endpoints/utility_report_counts_populated_pool
    """
    fixtures.create_connection(api, ADMIN)
    data = validate_success(api.utility_report(ADMIN))
    assert data["total_connections"] == 1, f"got {data['total_connections']}"
    assert data["compliant_count"] == 1, f"got {data['compliant_count']}"
    assert data["non_compliant_count"] == 0, f"got {data['non_compliant_count']}"
    assert data["compliance_rate"] == pytest.approx(100.00, abs=0.001), \
        f"1/1*100 -> 100.00, got {data['compliance_rate']}"


# --------------------------------------------------------------------------- #
# Corner/cross_cutting_complexity_layers/overdue_count_reconciled_after_clock_advance
# --------------------------------------------------------------------------- #
def test_overdue_count_reconciled_after_clock_advance(api):
    """PRD §2.6: "`overdue_device_count` is the number of devices on the connection whose
    status is `ACTIVE` or `NEEDS_REPAIR` and whose `next_test_due_date` is strictly earlier
    than `current_utc`".
    PRD §2.6: "if the connection has at least one overdue device (its `overdue_device_count`
    is greater than zero), or any device on it is in `NEEDS_REPAIR` status, or it has at
    least one open shutoff notice (its `open_notice_count` is greater than zero), the
    posture is `NON_COMPLIANT`."

    Design: Corner/cross_cutting_complexity_layers/overdue_count_reconciled_after_clock_advance
    """
    conn = fixtures.create_connection(api, ADMIN)
    fixtures.create_device(conn["id"], api, ADMIN, install_date="2025-03-01T00:00:00Z")
    fixtures.set_clock("2026-03-15T00:00:00Z", api, ADMIN)
    data = validate_success(api.get_connection(conn["id"], ADMIN))
    assert data["overdue_device_count"] == 1, \
        f"device due 2026-03-01 is overdue at 2026-03-15, got {data['overdue_device_count']}"
    assert data["compliance_posture"] == "NON_COMPLIANT", \
        f"overdue device drives NON_COMPLIANT, got {data['compliance_posture']}"


# --------------------------------------------------------------------------- #
# Corner/cross_cutting_complexity_layers/reminders_generate_creates_overdue_reminder
# --------------------------------------------------------------------------- #
def test_reminders_generate_creates_overdue_reminder(api):
    """PRD §3.7: "The reminder's `reminder_type` is `UPCOMING_DUE` when `days_until_due` is
    at least 0 and at most 30, and `OVERDUE` when `days_until_due` is below 0. The batch
    returns a summary object reporting `generated_count` (total reminders created),
    `upcoming_count` (those of type `UPCOMING_DUE`), and `overdue_count` (those of type
    `OVERDUE`)."

    Design: Corner/cross_cutting_complexity_layers/reminders_generate_creates_overdue_reminder
    """
    conn = fixtures.create_connection(api, ADMIN)
    fixtures.create_device(conn["id"], api, ADMIN, install_date="2025-03-01T00:00:00Z")
    fixtures.set_clock("2026-03-15T00:00:00Z", api, ADMIN)
    data = validate_success(api.generate_reminders(ADMIN), expected_status=201)
    assert data["generated_count"] == 1, f"one device -> one reminder, got {data['generated_count']}"
    assert data["overdue_count"] == 1, f"device is overdue, got {data['overdue_count']}"
