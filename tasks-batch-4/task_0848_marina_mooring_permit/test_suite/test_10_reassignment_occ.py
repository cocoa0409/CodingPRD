"""Berth reassignment: optimistic-concurrency version guard, type matching, and
the transfer target-invalid rule."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    setup_active_permit,
    create_berth,
    permit_version,
    get_permit,
    get_berth,
)

HARBOR = TEST_USERS["harbormaster_headers"]


def test_reassign_with_current_version_moves_permit_and_frees_old_berth(api):
    """PRD §3.5: "On success the old berth moves from `OCCUPIED` to `AVAILABLE`,
    triggering waitlist promotion on that vacated berth, the new berth moves from
    `AVAILABLE` to `OCCUPIED`, and the permit's `version` increments by one."

    Design: Corner/cross_cutting/reassign_correct_version_succeeds_and_bumps_version
    """
    b = setup_active_permit(api, clock="2026-05-15T00:00:00Z", vessel_overrides={"length_ft": 30})
    slip1 = b["berth"]["id"]
    slip2 = create_berth(api, b["marina"]["id"])
    pv = permit_version(api, b["permit"]["id"])
    data = validate_success(
        api.reassign_berth(
            b["permit"]["id"], {"new_berth_id": slip2["id"], "expected_permit_version": pv}, HARBOR
        )
    )
    assert data["berth_id"] == slip2["id"]
    assert data["version"] > pv
    assert get_berth(api, slip1)["status"] == "AVAILABLE"
    assert get_berth(api, slip2["id"])["status"] == "OCCUPIED"


def test_reassign_with_stale_version_rejected(api):
    """PRD §2.6: "The server compares that value against the permit's current
    `version`; if another writer has advanced the permit's `version` since the
    client last read it, the reassignment is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting/reassign_stale_version_returns_412
    """
    b = setup_active_permit(api, clock="2026-05-15T00:00:00Z", vessel_overrides={"length_ft": 30})
    slip2 = create_berth(api, b["marina"]["id"])
    slip3 = create_berth(api, b["marina"]["id"])
    pv0 = permit_version(api, b["permit"]["id"])
    validate_success(
        api.reassign_berth(
            b["permit"]["id"], {"new_berth_id": slip2["id"], "expected_permit_version": pv0}, HARBOR
        )
    )  # advances the permit version past pv0
    validate_error(
        api.reassign_berth(
            b["permit"]["id"], {"new_berth_id": slip3["id"], "expected_permit_version": pv0}, HARBOR
        ),
        ApiErrorId.ERR_STALE_VERSION,
    )
    assert get_permit(api, b["permit"]["id"])["berth_id"] == slip2["id"]


def test_reassign_onto_mooring_rejected_as_type_mismatch(api):
    """PRD §3.5: "the new berth's type and size must match and honor its
    `resident_only` flag (else `ERR_BERTH_TYPE_MISMATCH`)"

    Design: Corner/validations/reassign_wrong_berth_type_returns_type_mismatch
    """
    b = setup_active_permit(api, clock="2026-05-15T00:00:00Z", vessel_overrides={"length_ft": 30})
    slip1 = b["berth"]["id"]
    mooring = create_berth(
        api, b["marina"]["id"], berth_type="MOORING", size_class="MEDIUM", max_length_ft=40
    )
    pv = permit_version(api, b["permit"]["id"])
    validate_error(
        api.reassign_berth(
            b["permit"]["id"], {"new_berth_id": mooring["id"], "expected_permit_version": pv}, HARBOR
        ),
        ApiErrorId.ERR_BERTH_TYPE_MISMATCH,
    )
    assert get_permit(api, b["permit"]["id"])["berth_id"] == slip1


def test_transfer_to_current_holder_rejected(api):
    """PRD §3.5: "A harbormaster may transfer an `ACTIVE` permit to another boater
    by supplying `to_boater_id`, which must exist and differ from the permit's
    current `boater_id`; a target equal to the current holder is rejected with
    `ERR_TRANSFER_TARGET_INVALID` (HTTP 422)."

    Design: Corner/validations/transfer_to_same_holder_returns_invalid_target
    """
    b = setup_active_permit(api, clock="2026-05-15T00:00:00Z", vessel_overrides={"length_ft": 30})
    validate_error(
        api.transfer_permit(b["permit"]["id"], {"to_boater_id": b["boater"]["id"]}, HARBOR),
        ApiErrorId.ERR_TRANSFER_TARGET_INVALID,
    )
    assert get_permit(api, b["permit"]["id"])["status"] == "ACTIVE"
