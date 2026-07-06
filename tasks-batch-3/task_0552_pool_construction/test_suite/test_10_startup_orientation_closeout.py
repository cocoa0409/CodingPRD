"""Startup readiness, retainage release, owner orientation, and warranty close-out."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_project,
    setup_plaster_pending_all_passed_with_funded_draw, setup_oriented_project_with_open_punch,
)


def test_orient_before_startup_ready_rejected(api, builder_headers):
    """PRD §3.8: "With the pool started up, the BuilderPM records the owner orientation and handoff,
    advancing construction_status from STARTUP_READY to ORIENTED; attempting this orientation while
    the project is not in STARTUP_READY is rejected with ERR_NOT_STARTUP_READY."

    Design: Corner/state_machines/orient_before_startup_ready_rejected
    """
    project = create_project()  # NOT_STARTED
    res = api.transition_pool_project(project["id"], {"action": "ORIENT"}, builder_headers)
    validate_error(res, ApiErrorId.ERR_NOT_STARTUP_READY)


def test_plaster_pass_carries_project_to_startup_ready(api, inspector_headers, builder_headers):
    """PRD §3.8: "When the PLASTER gate passes and, with it, every one of the project's five gates
    is PASSED, the system carries the project's construction_status from IN_CONSTRUCTION to
    STARTUP_READY and recomputes current_phase to STARTUP."

    Design: Difficulty/transitive_cascade/plaster_pass_cascades_startup_and_retainage_release
    """
    project, gates, draw, inspection = setup_plaster_pending_all_passed_with_funded_draw()
    validate_success(api.record_inspection(inspection["id"], {"outcome": "PASS"}, inspector_headers), 200)
    plaster = validate_success(api.get_phase_gate(gates["PLASTER"]["id"], builder_headers), 200)
    assert plaster["status"] == "PASSED"
    project_after = validate_success(api.get_pool_project(project["id"], builder_headers), 200)
    assert project_after["construction_status"] == "STARTUP_READY"


def test_startup_releases_retainage_into_disbursed(api, inspector_headers, builder_headers):
    """PRD §3.8: "Reaching startup releases retainage: every funded draw whose retainage_released is
    still false has that flag set to true, and the project's held retainage is disbursed — the
    entire retainage_held_cents balance is moved into amount_disbursed_cents so that
    retainage_held_cents becomes 0."

    Design: Difficulty/transitive_cascade/plaster_pass_cascades_startup_and_retainage_release
    """
    project, gates, draw, inspection = setup_plaster_pending_all_passed_with_funded_draw()
    validate_success(api.record_inspection(inspection["id"], {"outcome": "PASS"}, inspector_headers), 200)
    project_after = validate_success(api.get_pool_project(project["id"], builder_headers), 200)
    assert project_after["retainage_held_cents"] == 0
    assert project_after["amount_disbursed_cents"] == 100000  # net 90000 + released retainage 10000
    draw_after = validate_success(api.get_draw_request(draw["id"], builder_headers), 200)
    assert draw_after["retainage_released"] is True


def test_close_with_open_punch_item_rejected(api, owner_headers, builder_headers):
    """PRD §3.8: "Closing requires the project to be in ORIENTED — an attempt from any other state
    is rejected with ERR_INVALID_STATE — and it requires that the count of OPEN punch items on the
    project is exactly zero; if any punch item remains open the close is rejected with
    ERR_OPEN_PUNCH_ITEMS."

    Design: Difficulty/boundary_precision_check/close_requires_zero_open_punch_items
    """
    project, punch = setup_oriented_project_with_open_punch()  # ORIENTED + one OPEN punch
    res = api.transition_pool_project(project["id"], {"action": "CLOSE"}, owner_headers)
    validate_error(res, ApiErrorId.ERR_OPEN_PUNCH_ITEMS)
    after = validate_success(api.get_pool_project(project["id"], builder_headers), 200)
    assert after["construction_status"] == "ORIENTED"


def test_close_succeeds_once_open_count_is_zero(api, owner_headers, builder_headers):
    """PRD §3.8: "it requires that the count of OPEN punch items on the project is exactly zero; if
    any punch item remains open the close is rejected with ERR_OPEN_PUNCH_ITEMS."
    PRD §3.8: "An open item is closed by the builder or the owner resolving it (OPEN to RESOLVED)
    or by the owner waiving it (OPEN to WAIVED); both RESOLVED and WAIVED are terminal."

    Design: Difficulty/boundary_precision_check/close_requires_zero_open_punch_items
    """
    project, punch = setup_oriented_project_with_open_punch()
    validate_success(api.resolve_punch_item(punch["id"], {"action": "RESOLVE"}, owner_headers), 200)
    closed = validate_success(api.transition_pool_project(project["id"], {"action": "CLOSE"},
                                                         owner_headers), 200)
    assert closed["construction_status"] == "CLOSED"
