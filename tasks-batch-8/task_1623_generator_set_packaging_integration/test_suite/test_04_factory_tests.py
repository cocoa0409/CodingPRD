"""Factory tests: verdict boundary, billing rounding, SoD, bay overlap, retests (PRD §3.7)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_factory_test,
    get_success_data,
    make_test_engineer_headers,
    setup_testing_order,
    validate_error,
    validate_success,
)

SALES = TEST_USERS["sales_engineer_headers"]


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula/load_bank_billing_rounding_order
# ---------------------------------------------------------------------------

def test_load_bank_billing_round_per_step_then_sum(api):
    """PRD §3.7: "Billing and energy are computed with a pinned rounding order —
    round per step first, then sum, never sum-then-round. Each step's raw energy
    is its `kw` times its `hours`, rounded half-up to one decimal place of a
    kilowatt-hour; the `total_kwh` is the sum of those rounded per-step
    energies, itself rounded half-up to one decimal place. Each step's charge is
    its rounded step energy multiplied by 32 cents per kilowatt-hour, rounded
    half-up to whole cents, and the `invoice_total_cents` is the sum of those
    per-step charges."

    Steps 47.25 kW x 1.0 h (47.3 -> 1514 c... wait: 47.3*32 = 1513.6 -> 1514)
    and 33.33 kW x 0.5 h (16.7 -> 534.4 -> 534): invoice 2048, total_kwh 64.0.

    Design: Difficulty/combinatorial_formula/load_bank_billing_rounding_order
    """
    ctx = setup_testing_order()
    test = create_factory_test(
        ctx["order"]["id"], ctx["configuration"]["id"], ctx["bay"]["id"]
    )
    get_success_data(api.start_factory_test(test["id"], make_test_engineer_headers("eng-rec-1")))
    recorded = validate_success(api.record_factory_test(
        test["id"],
        {"readings": [
            {"kw": 47.25, "hours": 1.0, "power_factor": 0.80},
            {"kw": 33.33, "hours": 0.5, "power_factor": 0.82},
        ]},
        make_test_engineer_headers("eng-rec-1"),
    ))
    assert recorded["total_kwh"] == pytest.approx(64.0, abs=0.001)
    assert recorded["invoice_total_cents"] == 2048


def test_load_bank_billing_measured_avg_pf_and_verdict(api):
    """PRD §3.7: "The `measured_avg_pf` is the hours-weighted mean power factor —
    the sum over steps of each `power_factor` times its `hours`, divided by the
    sum of `hours` — rounded half-up to four decimal places. The `verdict` is
    `PASS` if every step's `power_factor` is at least 0.80 (0.80 exactly passes;
    0.79 fails) and `FAIL` otherwise..."

    For steps (0.80 x 1.0 h) and (0.82 x 0.5 h): weighted pf = 1.21 / 1.5 =
    0.8067, and both steps meet 0.80 so the verdict is PASS.

    Design: Difficulty/combinatorial_formula/load_bank_billing_rounding_order
    """
    ctx = setup_testing_order()
    test = create_factory_test(
        ctx["order"]["id"], ctx["configuration"]["id"], ctx["bay"]["id"]
    )
    get_success_data(api.start_factory_test(test["id"], make_test_engineer_headers("eng-rec-2")))
    recorded = validate_success(api.record_factory_test(
        test["id"],
        {"readings": [
            {"kw": 47.25, "hours": 1.0, "power_factor": 0.80},
            {"kw": 33.33, "hours": 0.5, "power_factor": 0.82},
        ]},
        make_test_engineer_headers("eng-rec-2"),
    ))
    assert recorded["measured_avg_pf"] == pytest.approx(0.8067, abs=0.0001)
    assert recorded["verdict"] == "PASS"
    assert recorded["status"] == "PASSED"


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check/power_factor_exactly_080_passes
# ---------------------------------------------------------------------------

def test_power_factor_exactly_080_passes(api):
    """PRD §3.7: "The `verdict` is `PASS` if every step's `power_factor` is at
    least 0.80 (0.80 exactly passes; 0.79 fails) and `FAIL` otherwise..."

    Design: Difficulty/boundary_precision_check/power_factor_exactly_080_passes
    """
    ctx = setup_testing_order()
    test = create_factory_test(
        ctx["order"]["id"], ctx["configuration"]["id"], ctx["bay"]["id"],
        service_date="2026-08-05",
    )
    get_success_data(api.start_factory_test(test["id"], make_test_engineer_headers("eng-rec-3")))
    recorded = validate_success(api.record_factory_test(
        test["id"],
        {"readings": [{"kw": 100, "hours": 1.0, "power_factor": 0.80}]},
        make_test_engineer_headers("eng-rec-3"),
    ))
    assert recorded["verdict"] == "PASS"
    assert recorded["status"] == "PASSED"


def test_power_factor_079_fails_and_regresses_build(api):
    """PRD §3.7: "The `verdict` is `PASS` if every step's `power_factor` is at
    least 0.80 (0.80 exactly passes; 0.79 fails) and `FAIL` otherwise..."
    PRD §3.7: "A `FAIL` has teeth. The order's `build_status` regresses —
    `TESTING` → `CONFIGURING`, or `READY_TO_SHIP` → `CONFIGURING` if the failure
    came from a post-acceptance retest — incrementing the order's `version`..."

    Design: Difficulty/boundary_precision_check/power_factor_exactly_080_passes
    """
    ctx = setup_testing_order()
    assert ctx["order"]["build_status"] == "TESTING"
    test = create_factory_test(
        ctx["order"]["id"], ctx["configuration"]["id"], ctx["bay"]["id"],
        service_date="2026-08-06",
    )
    get_success_data(api.start_factory_test(test["id"], make_test_engineer_headers("eng-rec-4")))
    recorded = validate_success(api.record_factory_test(
        test["id"],
        {"readings": [{"kw": 100, "hours": 1.0, "power_factor": 0.79}]},
        make_test_engineer_headers("eng-rec-4"),
    ))
    assert recorded["verdict"] == "FAIL"
    assert recorded["status"] == "FAILED"
    order = get_success_data(api.get_order(ctx["order"]["id"], SALES))
    assert order["build_status"] == "CONFIGURING"


# ---------------------------------------------------------------------------
# Corner/state_machines/test_record_before_start_rejected
# ---------------------------------------------------------------------------

def test_record_before_start_rejected(api):
    """PRD §3.7: "Starting moves the test `SCHEDULED` → `IN_PROGRESS`. Recording
    is the heavy step..." — recording targets an IN_PROGRESS test, so recording
    a SCHEDULED test fails the from-state check with ERR_TEST_STATE_INVALID
    (PRD §5: `ERR_TEST_STATE_INVALID` | 409).

    Design: Corner/state_machines/test_record_before_start_rejected
    """
    ctx = setup_testing_order()
    test = create_factory_test(
        ctx["order"]["id"], ctx["configuration"]["id"], ctx["bay"]["id"]
    )
    assert test["status"] == "SCHEDULED"
    resp = api.record_factory_test(
        test["id"],
        {"readings": [{"kw": 100, "hours": 1.0, "power_factor": 0.9}]},
        make_test_engineer_headers("eng-rec-5"),
    )
    validate_error(resp, ApiErrorId.ERR_TEST_STATE_INVALID)
    current = get_success_data(api.get_factory_test(test["id"], TEST_USERS["test_engineer_headers"]))
    assert current["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Corner/rbac/test_recorder_cannot_accept_own_test
# ---------------------------------------------------------------------------

def test_recorder_cannot_accept_own_test(api):
    """PRD §3.7: "Acceptance is segregated: a `TestEngineer` accepts a `PASSED`
    test, but the accepting `X-User-ID` must differ from `recorded_by_user_id`,
    or the call fails with `ERR_SOD_VIOLATION`. Acceptance stamps
    `accepted_by_user_id`, moves the test to the terminal `ACCEPTED` state..."

    Design: Corner/rbac/test_recorder_cannot_accept_own_test
    """
    ctx = setup_testing_order()
    test = create_factory_test(
        ctx["order"]["id"], ctx["configuration"]["id"], ctx["bay"]["id"]
    )
    recorder = make_test_engineer_headers("eng-same")
    get_success_data(api.start_factory_test(test["id"], recorder))
    recorded = get_success_data(api.record_factory_test(
        test["id"],
        {"readings": [{"kw": 100, "hours": 1.0, "power_factor": 0.9}]},
        recorder,
    ))
    assert recorded["status"] == "PASSED"
    assert recorded["recorded_by_user_id"] == "eng-same"

    resp = api.accept_factory_test(test["id"], recorder)
    validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)

    accepted = validate_success(
        api.accept_factory_test(test["id"], make_test_engineer_headers("eng-other"))
    )
    assert accepted["status"] == "ACCEPTED"
    assert accepted["accepted_by_user_id"] == "eng-other"
    assert accepted["recorded_by_user_id"] == "eng-same"


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency/factory_test_create_requires_cert_issued
# ---------------------------------------------------------------------------

def test_factory_test_create_requires_cert_issued(api):
    """PRD §3.7: "The configuration must exist under the named order and be
    `LOCKED` or `RELEASED` (otherwise `ERR_CONFIG_STATE_INVALID`), and an
    `EmissionsCertificate` for the order must already be `ISSUED` — this is the
    cross-entity precondition, and a certificate-less order fails with
    `ERR_CERT_NOT_ISSUED`."

    While the certificate is only SUBMITTED, factory-test creation fails; after
    issue, the identical create succeeds.

    Design: Difficulty/cross_entity_state_dependency/factory_test_create_requires_cert_issued
    """
    # Build the state manually: approved permit + SUBMITTED (not ISSUED) cert.
    from test_helpers import setup_approved_permit, setup_test_bay, create_certificate
    ctx = setup_approved_permit()
    cert = create_certificate(ctx["order"]["id"], ctx["configuration"]["id"])
    cert = get_success_data(
        api.submit_emissions_certificate(cert["id"], {}, TEST_USERS["compliance_officer_headers"])
    )
    assert cert["status"] == "SUBMITTED"
    bay = setup_test_bay()

    resp = api.create_factory_test(
        {
            "order_id": ctx["order"]["id"],
            "configuration_id": ctx["configuration"]["id"],
            "bay_id": bay["id"],
            "service_date": "2026-08-05",
            "start_hour": 8,
            "end_hour": 12,
        },
        make_test_engineer_headers("eng-sched-1"),
    )
    validate_error(resp, ApiErrorId.ERR_CERT_NOT_ISSUED)

    get_success_data(api.issue_emissions_certificate(
        cert["id"], TEST_USERS["platform_admin_headers"]
    ))
    created = validate_success(api.create_factory_test(
        {
            "order_id": ctx["order"]["id"],
            "configuration_id": ctx["configuration"]["id"],
            "bay_id": bay["id"],
            "service_date": "2026-08-05",
            "start_hour": 8,
            "end_hour": 12,
        },
        make_test_engineer_headers("eng-sched-1"),
    ), expected_status=201)
    assert created["status"] == "SCHEDULED"
    order = get_success_data(api.get_order(ctx["order"]["id"], SALES))
    assert order["build_status"] == "TESTING"


def test_factory_test_create_on_certless_order_rejected(api):
    """PRD §3.7: "...an `EmissionsCertificate` for the order must already be
    `ISSUED` — this is the cross-entity precondition, and a certificate-less
    order fails with `ERR_CERT_NOT_ISSUED`."

    An order with no certificate at all fails creation the same way.

    Design: Difficulty/cross_entity_state_dependency/factory_test_create_requires_cert_issued
    """
    from test_helpers import setup_approved_permit, setup_test_bay
    ctx = setup_approved_permit()
    bay = setup_test_bay()
    resp = api.create_factory_test(
        {
            "order_id": ctx["order"]["id"],
            "configuration_id": ctx["configuration"]["id"],
            "bay_id": bay["id"],
            "service_date": "2026-08-05",
            "start_hour": 8,
            "end_hour": 12,
        },
        make_test_engineer_headers("eng-sched-2"),
    )
    validate_error(resp, ApiErrorId.ERR_CERT_NOT_ISSUED)


# ---------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap/test_bay_touch_allowed
# ---------------------------------------------------------------------------

def test_test_bay_half_open_touch_allowed(api):
    """PRD §3.7: "The bay must be `ACTIVE`, and the requested window must not
    intersect any existing non-terminal test's window on the same bay and date —
    windows are half-open, so a test ending at hour 12 and another starting at
    hour 12 do not conflict — with violations rejected as
    `ERR_TEST_BAY_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/test_bay_touch_allowed
    """
    ctx = setup_testing_order()
    first = create_factory_test(
        ctx["order"]["id"], ctx["configuration"]["id"], ctx["bay"]["id"],
        service_date="2026-08-05", start_hour=8, end_hour=12,
    )
    assert first["status"] == "SCHEDULED"

    overlap = api.create_factory_test(
        {
            "order_id": ctx["order"]["id"],
            "configuration_id": ctx["configuration"]["id"],
            "bay_id": ctx["bay"]["id"],
            "service_date": "2026-08-05",
            "start_hour": 11,
            "end_hour": 14,
        },
        make_test_engineer_headers("eng-sched-3"),
    )
    validate_error(overlap, ApiErrorId.ERR_TEST_BAY_OVERLAP)

    touching = validate_success(api.create_factory_test(
        {
            "order_id": ctx["order"]["id"],
            "configuration_id": ctx["configuration"]["id"],
            "bay_id": ctx["bay"]["id"],
            "service_date": "2026-08-05",
            "start_hour": 12,
            "end_hour": 16,
        },
        make_test_engineer_headers("eng-sched-3"),
    ), expected_status=201)
    assert touching["status"] == "SCHEDULED"


def test_test_bay_overlap_same_day_only(api):
    """PRD §3.7: "...the requested window must not intersect any existing
    non-terminal test's window on the same bay and date — windows are
    half-open..." — windows on a different date share no interval, so a
    same-hours booking on the next day succeeds.

    Design: Difficulty/resource_temporal_overlap/test_bay_touch_allowed
    """
    ctx = setup_testing_order()
    first = create_factory_test(
        ctx["order"]["id"], ctx["configuration"]["id"], ctx["bay"]["id"],
        service_date="2026-08-05", start_hour=8, end_hour=12,
    )
    assert first["status"] == "SCHEDULED"
    other_day = validate_success(api.create_factory_test(
        {
            "order_id": ctx["order"]["id"],
            "configuration_id": ctx["configuration"]["id"],
            "bay_id": ctx["bay"]["id"],
            "service_date": "2026-08-06",
            "start_hour": 8,
            "end_hour": 12,
        },
        make_test_engineer_headers("eng-sched-4"),
    ), expected_status=201)
    assert other_day["status"] == "SCHEDULED"
