"""Units: intake defaults, aging, not-found, required fields; floor-plan OCC on Unit.version."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    fixtures,
    create_floor_plan_payload,
)

MANAGER = TEST_USERS["manager_headers"]


def test_floor_plan_create_with_stale_unit_version_conflict(api):
    """PRD §2.8: "If that value does not equal the unit's current `version` — because
    some other writer has advanced the unit since the client read it — the request is
    rejected with `ERR_STALE_UNIT_VERSION` (HTTP 412)".

    Design: Corner/cross_cutting/floorplan_create_stale_unit_version_conflict
    """
    unit = fixtures.create_unit(acquisition_type="FLOOR_PLAN")
    observed_version = unit["version"]
    # First advance succeeds and bumps Unit.version past the observed value.
    first = create_floor_plan_payload(unit["id"], observed_version,
                                      principal_cents=6000000, apr_bps=900,
                                      advanced_at="2026-04-01T00:00:00Z")
    validate_success(api.create_floor_plan(first, MANAGER), expected_status=201)
    # Second create still carries the now-stale observed version.
    second = create_floor_plan_payload(unit["id"], observed_version,
                                       principal_cents=5500000, apr_bps=880,
                                       advanced_at="2026-04-15T00:00:00Z")
    validate_error(api.create_floor_plan(second, MANAGER),
                   ApiErrorId.ERR_STALE_UNIT_VERSION.value)


def test_floor_plan_create_bumps_unit_version(api):
    """PRD §3.2: "the prior plan is driven to `SUPERSEDED` (a terminal state that
    accepts no further curtailments), the new plan takes its place, the unit's `version`
    is incremented by one, and the unit's `floor_plan_balance_cents` is recomputed."
    PRD §3.2: "On creation the plan starts `ACTIVE`".

    Design: Corner/cross_cutting/floorplan_create_supersedes_prior_and_bumps_version
    """
    unit = fixtures.create_unit(acquisition_type="FLOOR_PLAN")
    version_before = unit["version"]
    payload = create_floor_plan_payload(unit["id"], version_before,
                                        principal_cents=6300000, apr_bps=900,
                                        advanced_at="2026-04-01T00:00:00Z")
    fp = validate_success(api.create_floor_plan(payload, MANAGER), expected_status=201)
    assert fp["status"] == "ACTIVE", f"Expected ACTIVE, got {fp['status']}"
    unit_after = validate_success(api.get_unit(unit["id"], MANAGER))
    assert unit_after["version"] == version_before + 1, \
        f"Expected version {version_before + 1}, got {unit_after['version']}"


def test_unit_create_missing_required_hin_rejected(api):
    """PRD §3.1: "by registering it with its `hin` (a 12-character Hull Identification
    Number that must be unique across all units)". PRD §2.5: "Structural validity of the
    request body is checked fourth — required fields present, types correct, and enum
    values within range — yielding `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/unit_create_missing_required_hin_rejected
    """
    payload = {
        "make": "Sea Ray", "model": "SLX", "model_year": 2024, "unit_type": "BOAT",
        "length_ft": 28, "cost_cents": 7000000, "list_price_cents": 9000000,
        "acquisition_type": "CASH",
    }
    validate_error(api.create_unit(payload, MANAGER), ApiErrorId.ERR_INVALID_REQUEST.value)


def test_unit_get_not_found_returns_404(api):
    """PRD §2.5: "the system resolves each referenced identifier left to right and
    rejects the request with `ERR_NOT_FOUND` (HTTP 404) on the first identifier that does
    not resolve to an existing resource."

    Design: Corner/entities/unit_get_not_found_returns_404
    """
    validate_error(api.get_unit(NON_EXISTENT_UUID, MANAGER), ApiErrorId.ERR_NOT_FOUND.value)


def test_unit_open_recall_defaults_false(api):
    """PRD §3.1: "The intake payload may also set `open_recall`; when omitted it
    defaults to false." PRD §3.1: "A newly registered unit begins in `INTAKE` status."

    Design: Corner/entities/unit_open_recall_defaults_false
    """
    unit = fixtures.create_unit(acquisition_type="CASH")  # payload omits open_recall
    data = validate_success(api.get_unit(unit["id"], MANAGER))
    assert data["open_recall"] is False, f"Expected open_recall False, got {data['open_recall']}"
    assert data["status"] == "INTAKE", f"Expected INTAKE, got {data['status']}"


def test_unit_aging_days_from_logical_clock(api):
    """PRD §3.1: "`aging_days` is the number of whole days the unit has been in stock,
    computed as the floor of the elapsed time from `created_at` to the current
    logical-clock instant."

    Design: Corner/calculations/unit_aging_days_from_clock
    """
    fixtures.set_clock("2026-05-01T00:00:00Z")
    unit = fixtures.create_unit(acquisition_type="CASH")
    fixtures.set_clock("2026-05-11T00:00:00Z")
    data = validate_success(api.get_unit(unit["id"], MANAGER))
    assert data["aging_days"] == 10, f"Expected aging_days 10, got {data['aging_days']}"
