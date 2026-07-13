"""Inspection scheduling and start guards: precedence, overlap, buffer, OCC, cross-entity.

Covers difficulty instances state_beats_temporal_on_schedule,
referential_beats_temporal_on_schedule, inspector_half_open_window_overlap,
device_buffer_window_overlap, inspection_start_requires_testable_device,
seal_requires_active_establishment; plus corner OCC and window-validity instances.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    bootstrap_est_inspector, register_device, in_progress_accuracy,
    schedule_inspection, device_version, get_device,
    get_inspection, make_inspector_headers,
    api_client,
)

ADMIN = TEST_USERS["program_admin_headers"]


def _insp_payload(device_id, inspector_id, start, end, expected_version,
                  inspection_type="ACCURACY_TEST", complaint_id=None):
    payload = {
        "device_id": device_id,
        "inspector_id": inspector_id,
        "inspection_type": inspection_type,
        "scheduled_start": start,
        "scheduled_end": end,
        "expected_device_version": expected_version,
    }
    if complaint_id is not None:
        payload["complaint_id"] = complaint_id
    return payload


# --------------------------------------------------------------------------- #
# Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_schedule
# --------------------------------------------------------------------------- #
def _setup_retired_device_with_inspector_busy():
    est, inspector = bootstrap_est_inspector(est_name="Conf1 Store", jurisdiction="CA-09")
    devY = register_device(est["id"], device_type="SCALE", serial_number="SN-Y",
                           device_class="CLASS_III")
    # Inspector holds a SCHEDULED window [10:00,11:00) on device Y.
    schedule_inspection(devY["id"], inspector["id"],
                        "2026-03-14T10:00:00Z", "2026-03-14T11:00:00Z")
    devX = register_device(est["id"], device_type="SCALE", serial_number="SN-X",
                           device_class="CLASS_III")
    validate_success(api_client.retire_device(devX["id"], ADMIN, {"reason": "scrapped"}), 200)
    return inspector, devX


def test_retired_device_outranks_inspector_overlap_returns_not_testable():
    """PRD §3.3: "scheduling applies a sequence of scheduling-specific checks, evaluated
    in the following order so that an earlier rejection takes precedence over a later
    one:"
    PRD §3.3: "A device in the terminal `RETIRED` state cannot be scheduled and the
    request is rejected with `ERR_DEVICE_NOT_TESTABLE`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_schedule
    """
    inspector, devX = _setup_retired_device_with_inspector_busy()
    payload = _insp_payload(devX["id"], inspector["id"],
                            "2026-03-14T10:30:00Z", "2026-03-14T11:30:00Z",
                            device_version(devX["id"]))
    resp = api_client.create_inspection(payload, make_inspector_headers(inspector["id"]))
    validate_error(resp, ApiErrorId.ERR_DEVICE_NOT_TESTABLE.value)


def test_state_check_masks_inspector_conflict_error():
    """PRD §3.3: "scheduling applies a sequence of scheduling-specific checks, evaluated
    in the following order so that an earlier rejection takes precedence over a later
    one:"
    PRD §3.3: "Overlap is judged on the half-open interval from `scheduled_start` up to
    but not including `scheduled_end`: two inspections that merely touch, where one's end
    equals the other's start, do not conflict, whereas any genuine overlap is rejected
    with `ERR_INSPECTOR_SCHEDULE_CONFLICT`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_schedule
    """
    inspector, devX = _setup_retired_device_with_inspector_busy()
    payload = _insp_payload(devX["id"], inspector["id"],
                            "2026-03-14T10:30:00Z", "2026-03-14T11:30:00Z",
                            device_version(devX["id"]))
    resp = api_client.create_inspection(payload, make_inspector_headers(inspector["id"]))
    error = resp.json()["data"]["error_id"]
    assert error == ApiErrorId.ERR_DEVICE_NOT_TESTABLE.value, (
        f"device testability (check 2) must mask inspector conflict (check 5), got {error}")


# --------------------------------------------------------------------------- #
# Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_schedule
# --------------------------------------------------------------------------- #
def _setup_device_busy_for_complaint_retest():
    est, inspector = bootstrap_est_inspector(est_name="Conf2 Store", jurisdiction="CA-10")
    devD = register_device(est["id"], device_type="SCALE", serial_number="SN-D",
                           device_class="CLASS_III")
    schedule_inspection(devD["id"], inspector["id"],
                        "2026-03-15T10:00:00Z", "2026-03-15T11:00:00Z")
    return inspector, devD


def test_missing_complaint_outranks_device_buffer_returns_complaint_required():
    """PRD §3.3: "When `inspection_type` is `COMPLAINT_RETEST`, the `complaint_id` is
    mandatory and must reference a `Complaint` that is currently in `status` `FILED` and
    whose own `device_id` equals the inspection's `device_id`; a missing or mismatched
    complaint is rejected with `ERR_COMPLAINT_REQUIRED`."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_schedule
    """
    inspector, devD = _setup_device_busy_for_complaint_retest()
    # COMPLAINT_RETEST with no complaint_id AND a window only 30 min after the prior one.
    payload = _insp_payload(devD["id"], inspector["id"],
                            "2026-03-15T11:30:00Z", "2026-03-15T12:30:00Z",
                            device_version(devD["id"]), inspection_type="COMPLAINT_RETEST")
    resp = api_client.create_inspection(payload, make_inspector_headers(inspector["id"]))
    validate_error(resp, ApiErrorId.ERR_COMPLAINT_REQUIRED.value)


def test_referential_check_masks_device_buffer_error():
    """PRD §3.3: "scheduling applies a sequence of scheduling-specific checks, evaluated
    in the following order so that an earlier rejection takes precedence over a later
    one:"
    PRD §3.3: "In practice, a gap of less than 60 minutes between this inspection and
    another of the device's non-terminal inspections is a conflict and is rejected with
    `ERR_DEVICE_RETEST_BUFFER`, while a gap of 60 minutes or more is allowed."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_schedule
    """
    inspector, devD = _setup_device_busy_for_complaint_retest()
    payload = _insp_payload(devD["id"], inspector["id"],
                            "2026-03-15T11:30:00Z", "2026-03-15T12:30:00Z",
                            device_version(devD["id"]), inspection_type="COMPLAINT_RETEST")
    resp = api_client.create_inspection(payload, make_inspector_headers(inspector["id"]))
    error = resp.json()["data"]["error_id"]
    assert error == ApiErrorId.ERR_COMPLAINT_REQUIRED.value, (
        f"complaint linkage (check 4) must mask device buffer (check 6), got {error}")


# --------------------------------------------------------------------------- #
# Difficulty/resource_temporal_overlap/inspector_half_open_window_overlap
# --------------------------------------------------------------------------- #
def test_adjacent_inspector_window_is_accepted():
    """PRD §3.3: "Overlap is judged on the half-open interval from `scheduled_start` up
    to but not including `scheduled_end`: two inspections that merely touch, where one's
    end equals the other's start, do not conflict, whereas any genuine overlap is
    rejected with `ERR_INSPECTOR_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/inspector_half_open_window_overlap
    """
    est, inspector = bootstrap_est_inspector(est_name="Ovl1 Store", jurisdiction="CA-15")
    dev1 = register_device(est["id"], device_type="SCALE", serial_number="SN-O1",
                           device_class="CLASS_III")
    dev2 = register_device(est["id"], device_type="SCALE", serial_number="SN-O2",
                           device_class="CLASS_III")
    schedule_inspection(dev1["id"], inspector["id"],
                        "2026-03-19T10:00:00Z", "2026-03-19T11:00:00Z")
    payload = _insp_payload(dev2["id"], inspector["id"],
                            "2026-03-19T11:00:00Z", "2026-03-19T12:00:00Z",
                            device_version(dev2["id"]))
    resp = api_client.create_inspection(payload, make_inspector_headers(inspector["id"]))
    data = validate_success(resp, 201)
    assert data["status"] == "SCHEDULED"


def test_overlapping_inspector_window_is_rejected():
    """PRD §3.3: "The assigned inspector must not already hold another non-terminal
    inspection (one in `SCHEDULED` or `IN_PROGRESS`) whose window overlaps this one."

    Design: Difficulty/resource_temporal_overlap/inspector_half_open_window_overlap
    """
    est, inspector = bootstrap_est_inspector(est_name="Ovl1 Store", jurisdiction="CA-15")
    dev1 = register_device(est["id"], device_type="SCALE", serial_number="SN-O1",
                           device_class="CLASS_III")
    dev3 = register_device(est["id"], device_type="SCALE", serial_number="SN-O3",
                           device_class="CLASS_III")
    schedule_inspection(dev1["id"], inspector["id"],
                        "2026-03-19T10:00:00Z", "2026-03-19T11:00:00Z")
    payload = _insp_payload(dev3["id"], inspector["id"],
                            "2026-03-19T10:30:00Z", "2026-03-19T11:30:00Z",
                            device_version(dev3["id"]))
    resp = api_client.create_inspection(payload, make_inspector_headers(inspector["id"]))
    validate_error(resp, ApiErrorId.ERR_INSPECTOR_SCHEDULE_CONFLICT.value)


# --------------------------------------------------------------------------- #
# Difficulty/resource_temporal_overlap/device_buffer_window_overlap
# --------------------------------------------------------------------------- #
def test_device_retest_within_60_minute_buffer_is_rejected():
    """PRD §3.3: "In practice, a gap of less than 60 minutes between this inspection and
    another of the device's non-terminal inspections is a conflict and is rejected with
    `ERR_DEVICE_RETEST_BUFFER`, while a gap of 60 minutes or more is allowed."

    Design: Difficulty/resource_temporal_overlap/device_buffer_window_overlap
    """
    est, inspector = bootstrap_est_inspector(est_name="Ovl2 Store", jurisdiction="CA-16")
    devD = register_device(est["id"], device_type="SCALE", serial_number="SN-BUF",
                           device_class="CLASS_III")
    schedule_inspection(devD["id"], inspector["id"],
                        "2026-03-20T10:00:00Z", "2026-03-20T11:00:00Z")
    # Second window starts 30 min after the first ends -> gap 30 < 60 -> conflict.
    payload = _insp_payload(devD["id"], inspector["id"],
                            "2026-03-20T11:30:00Z", "2026-03-20T12:30:00Z",
                            device_version(devD["id"]))
    resp = api_client.create_inspection(payload, make_inspector_headers(inspector["id"]))
    validate_error(resp, ApiErrorId.ERR_DEVICE_RETEST_BUFFER.value)


def test_device_retest_at_exactly_60_minute_gap_is_allowed():
    """PRD §3.3: "In practice, a gap of less than 60 minutes between this inspection and
    another of the device's non-terminal inspections is a conflict and is rejected with
    `ERR_DEVICE_RETEST_BUFFER`, while a gap of 60 minutes or more is allowed."

    Design: Difficulty/resource_temporal_overlap/device_buffer_window_overlap
    """
    est, inspector = bootstrap_est_inspector(est_name="Ovl2 Store", jurisdiction="CA-16")
    devD = register_device(est["id"], device_type="SCALE", serial_number="SN-BUF",
                           device_class="CLASS_III")
    schedule_inspection(devD["id"], inspector["id"],
                        "2026-03-20T10:00:00Z", "2026-03-20T11:00:00Z")
    # Second window starts exactly 60 min after the first ends -> gap 60 >= 60 -> allowed.
    payload = _insp_payload(devD["id"], inspector["id"],
                            "2026-03-20T12:00:00Z", "2026-03-20T13:00:00Z",
                            device_version(devD["id"]))
    resp = api_client.create_inspection(payload, make_inspector_headers(inspector["id"]))
    data = validate_success(resp, 201)
    assert data["status"] == "SCHEDULED"


# --------------------------------------------------------------------------- #
# Difficulty/cross_entity_state_dependency/inspection_start_requires_testable_device
# --------------------------------------------------------------------------- #
def test_start_inspection_on_retired_device_returns_not_testable():
    """PRD §3.4: "Starting is permitted only while the underlying device remains
    testable — its `status` must be one of `REGISTERED`, `SEALED`, `CONDEMNED`, or
    `OUT_OF_SERVICE`; a device that has since been retired blocks the start with
    `ERR_DEVICE_NOT_TESTABLE`."

    Design: Difficulty/cross_entity_state_dependency/inspection_start_requires_testable_device
    """
    est, inspector = bootstrap_est_inspector(est_name="Dep1 Store", jurisdiction="CA-13")
    dev = register_device(est["id"], device_type="SCALE", serial_number="SN-DEP1",
                          device_class="CLASS_III")
    ins = schedule_inspection(dev["id"], inspector["id"],
                              "2026-03-17T09:00:00Z", "2026-03-17T10:00:00Z")
    validate_success(api_client.retire_device(dev["id"], ADMIN, {"reason": "removed"}), 200)
    resp = api_client.start_inspection(ins["id"], make_inspector_headers(inspector["id"]))
    validate_error(resp, ApiErrorId.ERR_DEVICE_NOT_TESTABLE.value)


def test_start_blocked_by_retire_leaves_inspection_scheduled():
    """PRD §3.4: "An `Inspector` begins field work by moving a scheduled inspection from
    `SCHEDULED` to `IN_PROGRESS`."
    PRD §3.4: "a device that has since been retired blocks the start with
    `ERR_DEVICE_NOT_TESTABLE`."

    Design: Difficulty/cross_entity_state_dependency/inspection_start_requires_testable_device
    """
    est, inspector = bootstrap_est_inspector(est_name="Dep1 Store", jurisdiction="CA-13")
    dev = register_device(est["id"], device_type="SCALE", serial_number="SN-DEP1",
                          device_class="CLASS_III")
    ins = schedule_inspection(dev["id"], inspector["id"],
                              "2026-03-17T09:00:00Z", "2026-03-17T10:00:00Z")
    validate_success(api_client.retire_device(dev["id"], ADMIN, {"reason": "removed"}), 200)
    api_client.start_inspection(ins["id"], make_inspector_headers(inspector["id"]))
    assert get_inspection(ins["id"])["status"] == "SCHEDULED"


# --------------------------------------------------------------------------- #
# Difficulty/cross_entity_state_dependency/seal_requires_active_establishment
# --------------------------------------------------------------------------- #
def test_finalize_pass_on_suspended_establishment_returns_suspended():
    """PRD §3.7: "Sealing requires the owning establishment to be `ACTIVE`; if the
    establishment is `SUSPENDED`, the pass cannot seal the device and finalization is
    rejected with `ERR_ESTABLISHMENT_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/seal_requires_active_establishment
    """
    est, inspector = bootstrap_est_inspector(est_name="Dep2 Store", jurisdiction="CA-14")
    dev = register_device(est["id"], device_type="SCALE", serial_number="SN-DEP2",
                          device_class="CLASS_III")
    ins = in_progress_accuracy(inspector, dev, "2026-03-18T09:00:00Z", "2026-03-18T10:00:00Z",
                               applied_load=3000, indicated_value=3000)  # passing reading
    validate_success(api_client.suspend_establishment(est["id"], ADMIN, {"reason": "nonpayment"}), 200)
    resp = api_client.finalize_inspection(ins["id"], make_inspector_headers(inspector["id"]))
    validate_error(resp, ApiErrorId.ERR_ESTABLISHMENT_SUSPENDED.value)


def test_suspended_seal_block_leaves_device_registered():
    """PRD §3.7: "Sealing requires the owning establishment to be `ACTIVE`; if the
    establishment is `SUSPENDED`, the pass cannot seal the device and finalization is
    rejected with `ERR_ESTABLISHMENT_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/seal_requires_active_establishment
    """
    est, inspector = bootstrap_est_inspector(est_name="Dep2 Store", jurisdiction="CA-14")
    dev = register_device(est["id"], device_type="SCALE", serial_number="SN-DEP2",
                          device_class="CLASS_III")
    ins = in_progress_accuracy(inspector, dev, "2026-03-18T09:00:00Z", "2026-03-18T10:00:00Z",
                               applied_load=3000, indicated_value=3000)
    validate_success(api_client.suspend_establishment(est["id"], ADMIN, {}), 200)
    api_client.finalize_inspection(ins["id"], make_inspector_headers(inspector["id"]))
    assert get_device(dev["id"])["status"] == "REGISTERED", "blocked seal must leave device REGISTERED"


# --------------------------------------------------------------------------- #
# Corner/cross_cutting_complexity_layers/occ_schedule_stale_device_version_returns_412
# --------------------------------------------------------------------------- #
def test_stale_expected_device_version_returns_412():
    """PRD §2.6: "Its value must equal the current `version` of the `Device` named in the
    request. If the two do not match — because some other writer has advanced the
    device's `version` since the client last read the device (for example, the device
    may have just been retired or condemned by another writer whose write already
    advanced the version) — the scheduling request is refused with
    `ERR_STALE_DEVICE_VERSION` and HTTP status 412."

    Design: Corner/cross_cutting_complexity_layers/occ_schedule_stale_device_version_returns_412
    """
    est, inspector = bootstrap_est_inspector(est_name="Occ Store", jurisdiction="CA-44")
    dev = register_device(est["id"], device_type="SCALE", serial_number="SN-OCC",
                          device_class="CLASS_III")
    v0 = dev["version"]
    # First schedule with the correct version advances Device.version.
    schedule_inspection(dev["id"], inspector["id"],
                        "2026-04-05T09:00:00Z", "2026-04-05T10:00:00Z",
                        expected_device_version=v0)
    # Second schedule still carries the now-stale v0.
    payload = _insp_payload(dev["id"], inspector["id"],
                            "2026-04-06T09:00:00Z", "2026-04-06T10:00:00Z", v0)
    resp = api_client.create_inspection(payload, make_inspector_headers(inspector["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_DEVICE_VERSION.value)


# --------------------------------------------------------------------------- #
# Corner/cross_cutting_complexity_layers/occ_schedule_correct_version_succeeds_and_bumps
# --------------------------------------------------------------------------- #
def test_schedule_with_current_version_succeeds_and_bumps_device_version():
    """PRD §3.3: "A successful scheduling call increments the device's `version` by one,
    which both reserves the device and arms the concurrency guard of §2.6 against any
    writer still holding the previous version."

    Design: Corner/cross_cutting_complexity_layers/occ_schedule_correct_version_succeeds_and_bumps
    """
    est, inspector = bootstrap_est_inspector(est_name="Occ2 Store", jurisdiction="CA-45")
    dev = register_device(est["id"], device_type="SCALE", serial_number="SN-OCC2",
                          device_class="CLASS_III")
    v0 = dev["version"]
    payload = _insp_payload(dev["id"], inspector["id"],
                            "2026-04-07T09:00:00Z", "2026-04-07T10:00:00Z", v0)
    resp = api_client.create_inspection(payload, make_inspector_headers(inspector["id"]))
    data = validate_success(resp, 201)
    assert data["status"] == "SCHEDULED"
    assert get_device(dev["id"])["version"] == v0 + 1, "successful schedule bumps device version by one"


# --------------------------------------------------------------------------- #
# Corner/validations/schedule_end_before_start_returns_window_invalid
# --------------------------------------------------------------------------- #
def test_schedule_end_not_after_start_returns_window_invalid():
    """PRD §3.3: "The window must be well-formed: `scheduled_end` strictly after
    `scheduled_start`, otherwise `ERR_SCHEDULE_WINDOW_INVALID`."

    Design: Corner/validations/schedule_end_before_start_returns_window_invalid
    """
    est, inspector = bootstrap_est_inspector(est_name="Win Store", jurisdiction="CA-34")
    dev = register_device(est["id"], device_type="SCALE", serial_number="SN-WIN",
                          device_class="CLASS_III")
    payload = _insp_payload(dev["id"], inspector["id"],
                            "2026-03-29T11:00:00Z", "2026-03-29T10:00:00Z",
                            device_version(dev["id"]))
    resp = api_client.create_inspection(payload, make_inspector_headers(inspector["id"]))
    validate_error(resp, ApiErrorId.ERR_SCHEDULE_WINDOW_INVALID.value)
