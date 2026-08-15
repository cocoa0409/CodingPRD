"""Tow enforcement: authorization gates, hold timing, impound fee, and the
release billing gate."""
import pytest

from test_helpers import (
    TEST_USERS,
    accept_permit,
    apply_for_permit,
    close_cycle,
    close_and_export_cycle,
    create_employee,
    create_tow_event_payload,
    get_cycle,
    get_permit,
    issue_violations,
    make_enforcement_officer_headers,
    set_logical_clock,
    settle_entry,
    setup_active_permit,
    setup_program_lot_cycle,
    setup_threshold_suspended_permit,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["parking_admin_headers"]
OFFICER1 = TEST_USERS["enforcement_officer_headers"]


def _authorize_tow(api, permit_id, violation_id):
    return api.create_tow_event(
        create_tow_event_payload(permit_id, violation_id), OFFICER1
    )


def _setup_tow_authorized(api):
    """Threshold-suspended permit (3 x WRONG_LOT at 2026-08-10T08:00:00Z) with a
    tow authorized at 2026-08-12T09:00:00Z (49 hours into the 48-hour hold)."""
    bundle = setup_threshold_suspended_permit(
        program_overrides={"tow_hold_hours": 48},
    )
    set_logical_clock("2026-08-12T09:00:00Z")
    tow = validate_success(
        _authorize_tow(api, bundle["permit"]["id"], bundle["violations"][0]["id"]),
        201,
    )
    assert tow["status"] == "AUTHORIZED"
    bundle["tow"] = tow
    return bundle


def test_tow_impound_fee_two_day_hold(api):
    """PRD section 3.7: "An event of `RELEASE` moves `TOWED` to `RELEASED`,
    requires an `OPEN` billing cycle (`ERR_NO_OPEN_BILLING_CYCLE`), stamps
    `released_at`, and computes `impound_fee_cents` as a 15000-cent tow base plus
    2500 cents of storage per day held — the held time being `released_at` minus
    `towed_at`, rounded up to whole days, with a one-day minimum. Release then
    posts a `PENDING` `TOW_FEE` entry for that amount into the `OPEN` cycle and
    records it in the tow event's `charge_entry_id`."

    Design: Corner/calculations/tow_impound_fee_two_day_hold
    """
    bundle = _setup_tow_authorized(api)
    tow = bundle["tow"]

    set_logical_clock("2026-08-12T10:00:00Z")
    validate_success(
        api.tow_event_action(tow["id"], {"event_type": "MARK_TOWED"}, OFFICER1), 200
    )

    # 36 hours held -> ceil to 2 storage days -> 15000 + 2 x 2500 = 20000.
    set_logical_clock("2026-08-13T22:00:00Z")
    released = validate_success(
        api.tow_event_action(tow["id"], {"event_type": "RELEASE"}, OFFICER1), 200
    )
    assert released["status"] == "RELEASED"
    assert released["impound_fee_cents"] == 20000
    assert released["charge_entry_id"], "release records the posted entry"

    entry = validate_success(
        api.get_charge_entry(released["charge_entry_id"], ADMIN), 200
    )
    assert entry["charge_type"] == "TOW_FEE"
    assert entry["amount_cents"] == 20000
    assert entry["status"] == "PENDING"
    assert entry["cycle_id"] == bundle["cycle"]["id"]


def test_tow_impound_fee_minimum_one_day(api):
    """PRD section 3.7: "An event of `RELEASE` moves `TOWED` to `RELEASED`,
    requires an `OPEN` billing cycle (`ERR_NO_OPEN_BILLING_CYCLE`), stamps
    `released_at`, and computes `impound_fee_cents` as a 15000-cent tow base plus
    2500 cents of storage per day held — the held time being `released_at` minus
    `towed_at`, rounded up to whole days, with a one-day minimum. Release then
    posts a `PENDING` `TOW_FEE` entry for that amount into the `OPEN` cycle and
    records it in the tow event's `charge_entry_id`."

    Design: Corner/calculations/tow_impound_fee_minimum_one_day
    """
    bundle = _setup_tow_authorized(api)
    tow = bundle["tow"]

    set_logical_clock("2026-08-12T10:00:00Z")
    validate_success(
        api.tow_event_action(tow["id"], {"event_type": "MARK_TOWED"}, OFFICER1), 200
    )

    # 12 hours held clamps to the one-day minimum -> 15000 + 1 x 2500 = 17500.
    set_logical_clock("2026-08-12T22:00:00Z")
    released = validate_success(
        api.tow_event_action(tow["id"], {"event_type": "RELEASE"}, OFFICER1), 200
    )
    assert released["impound_fee_cents"] == 17500


def test_tow_violation_permit_mismatch_rejected(api):
    """PRD section 3.7: "Authorization requires the permit to be `SUSPENDED` with
    `suspension_reason` `VIOLATION_THRESHOLD` (`ERR_INVALID_STATE` otherwise); the
    triggering violation must remain enforceable — `payment_status` `UNPAID` and
    `appeal_status` anything other than `DISMISSED`
    (`ERR_TOW_VIOLATION_NOT_ENFORCEABLE`); the tow hold must have elapsed, meaning
    the current logical time has reached or passed `suspended_at` plus the
    program's `tow_hold_hours` (`ERR_TOW_HOLD_NOT_ELAPSED`); and the cited
    violation must belong to the same permit (`ERR_VIOLATION_PERMIT_MISMATCH`)."

    Design: Corner/validations/tow_violation_permit_mismatch_rejected
    """
    bundle = setup_threshold_suspended_permit(
        program_overrides={"tow_hold_hours": 48},
    )
    # A second, perfectly valid ACTIVE permit with its own unpaid violation.
    e2 = create_employee(bundle["program"]["id"], badge_number="B002")
    p2 = apply_for_permit(e2, bundle["lot"], vehicle_plate="P002")
    accept_permit(p2, e2)
    other_violation = issue_violations(p2, "WRONG_LOT", count=1,
                                       officer_id="officer-1")[0]

    set_logical_clock("2026-08-12T09:00:00Z")
    res = _authorize_tow(api, bundle["permit"]["id"], other_violation["id"])
    validate_error(res, "ERR_VIOLATION_PERMIT_MISMATCH", expected_status=409)

    data, meta = validate_paginated(
        api.list_tow_events(ADMIN, params={"permit_id": bundle["permit"]["id"]})
    )
    assert meta["total_count"] == 0, "the rejected authorization persists nothing"


class TestTowSafetyBeatsHoldTimer:
    """Compliance gate (priority 7) vs temporal gate (priority 8): a tow citing
    an already-PAID violation only 4 hours into the hold violates both; the
    safety error must win."""

    def _setup(self, api):
        bundle = setup_threshold_suspended_permit(
            program_overrides={"tow_hold_hours": 48},
        )
        # Pay off the third violation: close + export the cycle, then settle its
        # fine entry to SETTLED so the violation's payment_status flips to PAID.
        v3_entry = bundle["violations"][2]["charge_entry_id"]
        close_and_export_cycle(bundle["cycle"]["id"])
        settle_entry(v3_entry, "SETTLED")
        v3 = validate_success(
            api.get_violation(bundle["violations"][2]["id"], ADMIN), 200
        )
        assert v3["payment_status"] == "PAID"
        # 4 hours into the 48-hour hold.
        set_logical_clock("2026-08-10T12:00:00Z")
        return bundle, v3

    def test_safety_error_returned_when_both_gates_fail(self, api):
        """PRD section 2.8: "When several checks could reject the same request, the
        server evaluates them in a fixed order, and an earlier failure masks all
        later ones." Compliance gates (step 7) name
        `ERR_TOW_VIOLATION_NOT_ENFORCEABLE`; temporal gates (step 8) name
        `ERR_TOW_HOLD_NOT_ELAPSED`.
        PRD section 3.7: "Authorization requires the permit to be `SUSPENDED` with
        `suspension_reason` `VIOLATION_THRESHOLD` (`ERR_INVALID_STATE` otherwise);
        the triggering violation must remain enforceable — `payment_status`
        `UNPAID` and `appeal_status` anything other than `DISMISSED`
        (`ERR_TOW_VIOLATION_NOT_ENFORCEABLE`); the tow hold must have elapsed,
        meaning the current logical time has reached or passed `suspended_at`
        plus the program's `tow_hold_hours` (`ERR_TOW_HOLD_NOT_ELAPSED`); and the
        cited violation must belong to the same permit
        (`ERR_VIOLATION_PERMIT_MISMATCH`)."

        Design: Difficulty/priority_pair_validation_conflict/tow_safety_beats_hold_timer
        """
        bundle, v3 = self._setup(api)
        res = _authorize_tow(api, bundle["permit"]["id"], v3["id"])
        validate_error(res, "ERR_TOW_VIOLATION_NOT_ENFORCEABLE", expected_status=409)

    def test_no_tow_persisted_and_permit_untouched(self, api):
        """PRD section 3.7: "An `EnforcementOfficer` authorizes a tow by naming the
        `permit_id` and the triggering `violation_id`." — a rejected authorization
        records nothing.
        PRD section 2.8: "When several checks could reject the same request, the
        server evaluates them in a fixed order, and an earlier failure masks all
        later ones."

        Design: Difficulty/priority_pair_validation_conflict/tow_safety_beats_hold_timer
        """
        bundle, v3 = self._setup(api)
        res = _authorize_tow(api, bundle["permit"]["id"], v3["id"])
        validate_error(res, "ERR_TOW_VIOLATION_NOT_ENFORCEABLE", expected_status=409)

        permit = get_permit(bundle["permit"]["id"])
        assert permit["status"] == "SUSPENDED"
        assert permit["suspension_reason"] == "VIOLATION_THRESHOLD"

        _data, meta = validate_paginated(
            api.list_tow_events(ADMIN, params={"permit_id": bundle["permit"]["id"]})
        )
        assert meta["total_count"] == 0


def test_tow_release_without_open_cycle_rejected(api):
    """PRD section 3.7: "An event of `RELEASE` moves `TOWED` to `RELEASED`,
    requires an `OPEN` billing cycle (`ERR_NO_OPEN_BILLING_CYCLE`), stamps
    `released_at`, and computes `impound_fee_cents` as a 15000-cent tow base plus
    2500 cents of storage per day held — the held time being `released_at` minus
    `towed_at`, rounded up to whole days, with a one-day minimum."

    Design: Corner/validations/tow_release_without_open_cycle_rejected
    """
    bundle = _setup_tow_authorized(api)
    tow = bundle["tow"]

    set_logical_clock("2026-08-12T10:00:00Z")
    validate_success(
        api.tow_event_action(tow["id"], {"event_type": "MARK_TOWED"}, OFFICER1), 200
    )

    # Closing the only cycle leaves the program with no OPEN cycle.
    close_cycle(bundle["cycle"]["id"])

    res = api.tow_event_action(tow["id"], {"event_type": "RELEASE"}, OFFICER1)
    validate_error(res, "ERR_NO_OPEN_BILLING_CYCLE", expected_status=409)

    after = validate_success(api.get_tow_event(tow["id"], ADMIN), 200)
    assert after["status"] == "TOWED"
    assert after["impound_fee_cents"] is None
    assert after["charge_entry_id"] is None
