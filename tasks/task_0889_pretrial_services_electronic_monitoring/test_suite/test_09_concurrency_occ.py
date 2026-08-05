"""Optimistic concurrency control on Defendant.version (level adjustments) and
EMEnrollment.version (curfew windows).

Translates SCAFFOLD_CORNER_DESIGN.yaml section cross_cutting_complexity_layers.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_defendant, create_device, create_pending_enrollment,
    create_level_adjustment_payload, create_curfew_window_payload,
)

SUPERVISING = TEST_USERS["supervising_headers"]


def test_level_adjustment_success_increments_version(api):
    """PRD §3.9: "On success the system sets the defendant's `supervision_level` to
    `to_level`, creates a `LevelAdjustment` ... and increments the defendant's `version` by
    one."

    Design: Corner/cross_cutting_complexity_layers/level_adjustment_success_increments_version
    """
    d = create_defendant()
    assert d["version"] == 1
    validate_success(api.create_level_adjustment(
        d["id"], create_level_adjustment_payload(d["version"], "MEDIUM", reason="manual"),
        SUPERVISING), 201)
    fresh = validate_success(api.get_defendant(d["id"], SUPERVISING), 200)
    assert fresh["supervision_level"] == "MEDIUM"
    assert fresh["version"] == 2


def test_level_adjustment_stale_version_rejected(api):
    """PRD §2.7: "If it does not match the defendant's current `version`, the write is
    rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/level_adjustment_stale_version_conflict
    """
    d = create_defendant()
    stale_version = d["version"]  # 1
    validate_success(api.create_level_adjustment(
        d["id"], create_level_adjustment_payload(stale_version, "MEDIUM"), SUPERVISING), 201)
    # Version is now 2; re-using the pre-adjustment version must be refused.
    resp = api.create_level_adjustment(
        d["id"], create_level_adjustment_payload(stale_version, "MAXIMUM"), SUPERVISING)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)


def test_curfew_window_stale_version_rejected(api):
    """PRD §2.7: "Adding a curfew window to an enrollment requires `expected_enrollment_version`
    in the request body ... If it does not match the enrollment's current `version`, the write
    is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/curfew_window_stale_version_conflict
    """
    d = create_defendant()
    dev = create_device(total_units=1)
    enr = create_pending_enrollment(d["id"], dev["id"])
    stale_version = enr["version"]
    validate_success(api.create_curfew_window(
        enr["id"], create_curfew_window_payload(stale_version, 0, 1200, 1320),
        SUPERVISING), 201)
    # A second, non-overlapping window still carrying the pre-edit version is refused.
    resp = api.create_curfew_window(
        enr["id"], create_curfew_window_payload(stale_version, 1, 600, 700), SUPERVISING)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
