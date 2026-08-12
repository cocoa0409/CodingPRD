"""Collector lifecycle state machine: invalid transitions, decommission
referential gate, and the hot-work busy gate on take-out-of-service."""
from test_helpers import (
    ApiErrorId,
    create_finding,
    create_inspection,
    create_permit,
    create_started_permit,
    set_clock,
    setup_site_with_in_service_collector,
    setup_site_with_collector,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

ENGINEER = TEST_USERS["compliance_engineer_headers"]
MANAGER = TEST_USERS["compliance_manager_headers"]


def test_decommission_from_draft_rejected(api):
    """PRD §3.3: "Decommissioning is reserved for `ComplianceManager` and moves
    the collector from `OUT_OF_SERVICE` to the terminal `DECOMMISSIONED`
    state."
    PRD §2.10: "**State-machine validity**: the target resource's current state
    allows the requested transition (else `ERR_INVALID_STATE`)."

    A DRAFT collector has no decommission transition.

    Design: Corner/state_machines/collector_draft_to_decommissioned_invalid
    """
    site, _sample, collector = setup_site_with_collector(insurer_id="FM-1")
    assert collector["status"] == "DRAFT"

    res = api.decommission_collector(site["id"], collector["id"], MANAGER)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    after = validate_success(api.get_collector(site["id"], collector["id"],
                                               ENGINEER), 200)
    assert after["status"] == "DRAFT"


def test_decommission_blocked_by_open_finding(api):
    """PRD §3.3: "The transition is refused with
    `ERR_COLLECTOR_HAS_OPEN_FINDING` (HTTP 422) when any `InspectionFinding`
    referencing this collector is in `OPEN` or `IN_PROGRESS` status."

    Design: Corner/errors/err_collector_has_open_finding_on_decommission
    """
    site, _sample, collector = setup_site_with_in_service_collector(
        insurer_id="FM-1")
    validate_success(
        api.take_collector_out_of_service(site["id"], collector["id"], ENGINEER),
        200)
    inspection = create_inspection(site["id"])
    create_finding(site["id"], inspection["id"], severity="MINOR",
                   collector_id=collector["id"])

    res = api.decommission_collector(site["id"], collector["id"], MANAGER)
    validate_error(res, ApiErrorId.ERR_COLLECTOR_HAS_OPEN_FINDING)


def test_take_out_of_service_blocked_by_in_progress_permit(api):
    """PRD §3.3: "The transition is refused with `ERR_COLLECTOR_BUSY`
    (HTTP 422) when any `HotWorkPermit` whose `collector_id` equals this
    collector is currently in `ISSUED` or `IN_PROGRESS` status."

    Design: Difficulty/cross_entity_state_dependency/collector_take_out_blocked_by_open_hotwork_permit
    """
    set_clock("2026-05-01T00:00:00Z")
    site, _sample, collector = setup_site_with_in_service_collector()
    permit = create_started_permit(
        site["id"], "2026-05-01T00:00:00Z", "2026-05-01T04:00:00Z",
        fire_watch_minutes_after=60, collector_id=collector["id"])
    assert permit["status"] == "IN_PROGRESS"

    res = api.take_collector_out_of_service(site["id"], collector["id"], ENGINEER)
    validate_error(res, ApiErrorId.ERR_COLLECTOR_BUSY)

    after = validate_success(api.get_collector(site["id"], collector["id"],
                                               ENGINEER), 200)
    assert after["status"] == "IN_SERVICE"


def test_take_out_of_service_blocked_by_issued_permit(api):
    """PRD §3.3: "The transition is refused with `ERR_COLLECTOR_BUSY`
    (HTTP 422) when any `HotWorkPermit` whose `collector_id` equals this
    collector is currently in `ISSUED` or `IN_PROGRESS` status."

    The gate also fires for a permit that is merely ISSUED (never started).

    Design: Difficulty/cross_entity_state_dependency/collector_take_out_blocked_by_open_hotwork_permit
    """
    site, _sample, collector = setup_site_with_in_service_collector()
    permit = create_permit(site["id"], "2026-05-01T00:00:00Z",
                           "2026-05-01T04:00:00Z", fire_watch_minutes_after=60,
                           collector_id=collector["id"])
    assert permit["status"] == "ISSUED"

    res = api.take_collector_out_of_service(site["id"], collector["id"], ENGINEER)
    validate_error(res, ApiErrorId.ERR_COLLECTOR_BUSY)

    after = validate_success(api.get_collector(site["id"], collector["id"],
                                               ENGINEER), 200)
    assert after["status"] == "IN_SERVICE"
