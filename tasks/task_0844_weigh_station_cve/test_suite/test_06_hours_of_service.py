"""Driver duty-log Hours-of-Service rules: reset buffer, overlap, and driving limit.

Difficulty translation: the off-duty reset-buffer gap rule. Corner translations: duty-log
overlap and the single-entry driving-limit boundary.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    set_clock,
    create_carrier,
    create_driver,
    add_duty_log,
)

ADMIN = TEST_USERS["compliance_admin_headers"]


def _carrier_and_driver(usdot, name):
    carrier = create_carrier(usdot_number=usdot, legal_name=name)
    driver = create_driver(carrier["id"], cdl_number="CDL-HOS", full_name="HOS Driver")
    return carrier, driver


def test_new_driving_shift_without_reset_buffer_rejected(api):
    """PRD §3.2: "A new driving shift must be separated from the prior driving shift by
    an off-duty buffer of at least `600` minutes (ten hours); a driving entry that lacks
    that buffer is rejected with `ERR_HOS_RESET_REQUIRED`."

    Design: Difficulty/resource_temporal_overlap/duty_log_hos_reset_buffer
    """
    set_clock("2026-03-02T12:00:00Z")
    _, driver = _carrier_and_driver("DOT-844-P", "Papa Fleet")
    add_duty_log(driver["id"], entry_type="DRIVING",
                 start_utc="2026-03-02T00:00:00Z", end_utc="2026-03-02T05:00:00Z")
    add_duty_log(driver["id"], entry_type="OFF_DUTY",
                 start_utc="2026-03-02T05:00:00Z", end_utc="2026-03-02T11:00:00Z")  # only 6h
    resp = api.create_duty_log(driver["id"],
                               {"entry_type": "DRIVING", "start_utc": "2026-03-02T11:00:00Z",
                                "end_utc": "2026-03-02T12:00:00Z"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_HOS_RESET_REQUIRED)


def test_new_driving_shift_with_full_reset_buffer_accepted(api):
    """PRD §3.2: "A new driving shift must be separated from the prior driving shift by
    an off-duty buffer of at least `600` minutes (ten hours); a driving entry that lacks
    that buffer is rejected with `ERR_HOS_RESET_REQUIRED`."

    Design: Difficulty/resource_temporal_overlap/duty_log_hos_reset_buffer
    """
    set_clock("2026-03-02T20:00:00Z")
    _, driver = _carrier_and_driver("DOT-844-P2", "Papa Fleet")
    add_duty_log(driver["id"], entry_type="DRIVING",
                 start_utc="2026-03-02T00:00:00Z", end_utc="2026-03-02T05:00:00Z")
    add_duty_log(driver["id"], entry_type="OFF_DUTY",
                 start_utc="2026-03-02T05:00:00Z", end_utc="2026-03-02T15:00:00Z")  # 600 min
    resp = api.create_duty_log(driver["id"],
                               {"entry_type": "DRIVING", "start_utc": "2026-03-02T15:00:00Z",
                                "end_utc": "2026-03-02T16:00:00Z"}, ADMIN)
    data = validate_success(resp, expected_status=201)
    assert data["entry_type"] == "DRIVING"


def test_overlapping_duty_log_rejected(api):
    """PRD §3.2: "No two entries for the same driver may overlap in time; an overlapping
    entry is rejected with `ERR_DUTY_LOG_OVERLAP`."

    Design: Corner/validations/duty_log_overlap_rejected
    """
    set_clock("2026-03-02T12:00:00Z")
    _, driver = _carrier_and_driver("DOT-C10", "Corner Ten")
    add_duty_log(driver["id"], entry_type="DRIVING",
                 start_utc="2026-03-02T00:00:00Z", end_utc="2026-03-02T05:00:00Z")
    resp = api.create_duty_log(driver["id"],
                               {"entry_type": "ON_DUTY", "start_utc": "2026-03-02T04:00:00Z",
                                "end_utc": "2026-03-02T06:00:00Z"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_DUTY_LOG_OVERLAP)


def test_driving_entry_over_limit_rejected(api):
    """PRD §3.2: "If the entry is `DRIVING` and that prospective window would exceed
    `660` minutes (eleven hours), the entry is rejected with `ERR_HOS_DRIVING_LIMIT`, and
    as part of that rejection the driver's `hos_status` is set to `VIOLATION` and the
    driver transitions `ACTIVE → OOS`. The boundary is strict: a driving entry that
    brings the window to exactly `660` minutes is allowed."

    Design: Corner/validations/hos_driving_limit_exceeded_returns_422
    """
    set_clock("2026-03-02T12:00:00Z")
    _, driver = _carrier_and_driver("DOT-C11", "Corner Eleven")
    # 661 minutes (11h01m) > 660.
    resp = api.create_duty_log(driver["id"],
                               {"entry_type": "DRIVING", "start_utc": "2026-03-02T00:00:00Z",
                                "end_utc": "2026-03-02T11:01:00Z"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_HOS_DRIVING_LIMIT)
