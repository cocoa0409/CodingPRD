"""Design lock: compatibility gate, string-size bounds, effective-window
boundary semantics, and the computed system size."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_project,
    create_active_installer,
    create_inverter_product,
    create_locked_project,
    create_module_product,
    create_project,
    make_installer_rep_headers,
    seed_catalog,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId

MANAGER = TEST_USERS["manager_headers"]


def test_project_computed_system_size_kw_dc_at_design_lock(api):
    """PRD section 3.5: "A successful lock pins the winning rule's id into the
    project's `compatibility_rule_id` — immutable thereafter — stamps
    `design_locked_at`, computes `system_size_kw_dc` as the total module
    nameplate DC watts of the design divided by one thousand, and
    automatically creates the project's permit package in `ASSEMBLING` with
    `required_documents` derived from the module and inverter product
    documentation (§3.8)."

    Design: Corner/entities/project_computed_system_size_kw_dc_at_design_lock
    """
    set_clock()
    catalog = seed_catalog(min_modules=5, max_modules=20)
    installer = create_active_installer()
    project = create_locked_project(
        installer["id"], catalog["module"]["id"], catalog["inverter"]["id"],
        module_qty=10,
    )
    assert_project(project)
    # 10 modules x 400 W nameplate = 4000 W = 4.0 kW DC.
    assert project["system_size_kw_dc"] == pytest.approx(4.0), (
        f"system_size_kw_dc must be 4.0, got {project['system_size_kw_dc']}"
    )
    assert project["design_locked_at"] is not None
    assert project["compatibility_rule_id"] == catalog["rule"]["id"]

    packages = validate_success(
        api.list_project_permit_packages(project["id"], MANAGER), 200
    )
    assert len(packages) == 1, "design lock auto-creates one permit package"
    assert packages[0]["status"] == "ASSEMBLING"


def test_err_no_compatibility_rule_triggered(api):
    """PRD section 3.5: "If no rule covers the pair, the lock is rejected with
    `ERR_NO_COMPATIBILITY_RULE`."

    Design: Corner/errors/err_no_compatibility_rule_triggered
    """
    set_clock()
    module = create_module_product()
    inverter = create_inverter_product()
    installer = create_active_installer()
    project = create_project(installer["id"], module["id"], inverter["id"],
                             module_qty=5)
    resp = api.lock_design(
        project["id"], make_installer_rep_headers(installer["id"])
    )
    validate_error(resp, ApiErrorId.ERR_NO_COMPATIBILITY_RULE)


def test_err_string_size_violation_below_min(api):
    """PRD section 3.5: "the project's `module_qty` must be at least the
    rule's `min_modules_per_inverter` multiplied by the project's
    `inverter_qty`, and at most the rule's `max_modules_per_inverter`
    multiplied by `inverter_qty`; falling outside those bounds fails with
    `ERR_STRING_SIZE_VIOLATION`."

    Design: Corner/errors/err_string_size_violation_below_min
    """
    set_clock()
    catalog = seed_catalog(min_modules=10, max_modules=20)
    installer = create_active_installer()
    # 5 modules on 1 inverter is below the rule minimum of 10 per inverter.
    project = create_project(
        installer["id"], catalog["module"]["id"], catalog["inverter"]["id"],
        module_qty=5, inverter_qty=1,
    )
    resp = api.lock_design(
        project["id"], make_installer_rep_headers(installer["id"])
    )
    validate_error(resp, ApiErrorId.ERR_STRING_SIZE_VIOLATION)


def test_compatibility_rule_expired_at_effective_to_boundary(api):
    """PRD section 3.5: "The system looks for an `ACTIVE` compatibility rule
    whose `module_product_id` and `inverter_product_id` equal the project's
    choices and whose window covers the current instant — `effective_from` at
    or before now, and either open-ended or `effective_to` strictly after
    now". At the instant exactly equal to `effective_to` the window no longer
    covers, so the lock fails as if no rule existed.

    Design: Difficulty/resource_temporal_overlap/compatibility_rule_window_boundary_half_open_at_lock_time
    """
    set_clock("2026-08-01T00:00:00Z")
    catalog = seed_catalog(
        min_modules=5, max_modules=20,
        rule_effective_from="2026-07-01T00:00:00Z",
        rule_effective_to="2026-08-10T00:00:00Z",
    )
    installer = create_active_installer()
    project = create_project(
        installer["id"], catalog["module"]["id"], catalog["inverter"]["id"],
        module_qty=5,
    )
    # Move the clock to exactly the rule's effective_to instant.
    set_clock("2026-08-10T00:00:00Z")
    resp = api.lock_design(
        project["id"], make_installer_rep_headers(installer["id"])
    )
    validate_error(resp, ApiErrorId.ERR_NO_COMPATIBILITY_RULE)


def test_compatibility_rule_effective_from_boundary_inclusive(api):
    """PRD section 3.5: "whose window covers the current instant —
    `effective_from` at or before now, and either open-ended or
    `effective_to` strictly after now". At the instant exactly equal to
    `effective_from` the window already covers, so the lock succeeds and pins
    the rule.

    Design: Difficulty/resource_temporal_overlap/compatibility_rule_window_boundary_half_open_at_lock_time
    """
    set_clock("2026-07-01T00:00:00Z")
    catalog = seed_catalog(
        min_modules=5, max_modules=20,
        rule_effective_from="2026-07-01T00:00:00Z",
    )
    installer = create_active_installer()
    project = create_project(
        installer["id"], catalog["module"]["id"], catalog["inverter"]["id"],
        module_qty=5,
    )
    locked = validate_success(
        api.lock_design(
            project["id"], make_installer_rep_headers(installer["id"])
        ),
        200,
    )
    assert locked["compatibility_rule_id"] == catalog["rule"]["id"]
    assert locked["design_locked_at"] is not None
