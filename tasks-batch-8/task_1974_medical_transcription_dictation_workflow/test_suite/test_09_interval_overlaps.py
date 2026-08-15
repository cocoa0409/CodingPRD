"""Interval semantics: half-open shift windows vs closed billing periods."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_clinic, setup_editor,
    create_shift_window_payload, create_billing_period_payload,
    make_editor_headers, TEST_USERS,
)

VENDOR = TEST_USERS["vendor_admin_headers"]


def test_shift_window_adjacency_allowed(api):
    """PRD §2.9: "Two windows that merely touch — one ending at the precise
    instant the other begins — do not overlap and are allowed."
    PRD §2.9: "An editor's availability window is a half-open interval:
    `start_at` is inclusive, `end_at` is exclusive, and `end_at` must be
    strictly after `start_at`, with violations rejected as
    `ERR_INVALID_WINDOW`."

    Design: Difficulty/resource_temporal_overlap/shift_window_half_open_adjacency
    """
    editor = setup_editor(wide_window=False)
    headers = make_editor_headers(editor["id"])
    validate_success(api.create_editor_shift_window(
        create_shift_window_payload(
            editor["id"], start_at="2026-08-03T08:00:00Z",
            end_at="2026-08-03T12:00:00Z"), headers), 201)
    # Right-adjacent: end == start is not an overlap under half-open semantics.
    validate_success(api.create_editor_shift_window(
        create_shift_window_payload(
            editor["id"], start_at="2026-08-03T12:00:00Z",
            end_at="2026-08-03T16:00:00Z"), headers), 201)
    # Left-adjacent is allowed too.
    validate_success(api.create_editor_shift_window(
        create_shift_window_payload(
            editor["id"], start_at="2026-08-03T07:00:00Z",
            end_at="2026-08-03T08:00:00Z"), headers), 201)
    windows = validate_success(api.list_editor_shift_windows(editor["id"], VENDOR))
    assert len(windows) == 3


def test_shift_window_interior_intersection_rejected(api):
    """PRD §2.9: "A new window for an editor is rejected with
    `ERR_SHIFT_WINDOW_OVERLAP` exactly when it begins before an existing window
    of that same editor ends and that existing window begins before the new
    window ends."

    Design: Difficulty/resource_temporal_overlap/shift_window_half_open_adjacency
    """
    editor = setup_editor(wide_window=False)
    headers = make_editor_headers(editor["id"])
    validate_success(api.create_editor_shift_window(
        create_shift_window_payload(
            editor["id"], start_at="2026-08-03T08:00:00Z",
            end_at="2026-08-03T12:00:00Z"), headers), 201)
    resp = api.create_editor_shift_window(
        create_shift_window_payload(
            editor["id"], start_at="2026-08-03T11:00:00Z",
            end_at="2026-08-03T13:00:00Z"), headers)
    validate_error(resp, ApiErrorId.ERR_SHIFT_WINDOW_OVERLAP)
    windows = validate_success(api.list_editor_shift_windows(editor["id"], VENDOR))
    assert len(windows) == 1, "the rejected window was not recorded"


def test_billing_period_touching_endpoint_conflicts(api):
    """PRD §2.9: "A new period for a clinic is rejected with
    `ERR_BILLING_PERIOD_OVERLAP` exactly when its start falls on or before an
    existing period's end and that existing period's start falls on or before
    the new period's end. Unlike availability windows, two billing periods
    whose endpoints merely touch are in conflict."

    Design: Difficulty/resource_temporal_overlap/billing_period_closed_interval_touching_conflict
    """
    clinic = setup_clinic()
    validate_success(api.create_billing_period(
        create_billing_period_payload(
            clinic["id"], period_start="2026-08-01T00:00:00Z",
            period_end="2026-08-31T23:59:59Z"), VENDOR), 201)
    touching = api.create_billing_period(
        create_billing_period_payload(
            clinic["id"], period_start="2026-08-31T23:59:59Z",
            period_end="2026-09-30T23:59:59Z"), VENDOR)
    validate_error(touching, ApiErrorId.ERR_BILLING_PERIOD_OVERLAP)


def test_billing_period_one_second_clear_accepted(api):
    """PRD §2.9: "A billing period, by contrast, is a closed interval: both
    `period_start` and `period_end` are members, for overlap and for membership
    of delivered work alike."
    PRD §2.9: "A new period for a clinic is rejected with
    `ERR_BILLING_PERIOD_OVERLAP` exactly when its start falls on or before an
    existing period's end and that existing period's start falls on or before
    the new period's end."

    Design: Difficulty/resource_temporal_overlap/billing_period_closed_interval_touching_conflict
    """
    clinic = setup_clinic()
    validate_success(api.create_billing_period(
        create_billing_period_payload(
            clinic["id"], period_start="2026-08-01T00:00:00Z",
            period_end="2026-08-31T23:59:59Z"), VENDOR), 201)
    clear = api.create_billing_period(
        create_billing_period_payload(
            clinic["id"], period_start="2026-09-01T00:00:00Z",
            period_end="2026-09-30T23:59:59Z"), VENDOR)
    validate_success(clear, 201)
    periods = validate_success(api.list_clinic_billing_periods(clinic["id"], VENDOR))
    assert len(periods) == 2


def test_inverted_intervals_return_invalid_window(api):
    """PRD §2.9: "An editor's availability window is a half-open interval:
    `start_at` is inclusive, `end_at` is exclusive, and `end_at` must be
    strictly after `start_at`, with violations rejected as
    `ERR_INVALID_WINDOW`."
    PRD §2.9: "`period_end` must be strictly after `period_start`, again
    enforced as `ERR_INVALID_WINDOW`."

    Design: Corner/validations/inverted_intervals_return_invalid_window
    """
    clinic = setup_clinic()
    editor = setup_editor(wide_window=False)
    zero_length = api.create_editor_shift_window(
        create_shift_window_payload(
            editor["id"], start_at="2026-08-03T12:00:00Z",
            end_at="2026-08-03T12:00:00Z"),
        make_editor_headers(editor["id"]))
    validate_error(zero_length, ApiErrorId.ERR_INVALID_WINDOW)
    reversed_period = api.create_billing_period(
        create_billing_period_payload(
            clinic["id"], period_start="2026-09-01T00:00:00Z",
            period_end="2026-08-01T00:00:00Z"), VENDOR)
    validate_error(reversed_period, ApiErrorId.ERR_INVALID_WINDOW)
