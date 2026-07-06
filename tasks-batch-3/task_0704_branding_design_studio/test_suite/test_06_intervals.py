"""Interval-window semantics: closed-interval licenses vs half-open care cycles,
and malformed-interval rejection."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_and_activate_project,
    create_active_retainer,
    create_license_payload,
    create_care_cycle_payload,
    set_clock,
)

SO = TEST_USERS["studio_ops_headers"]


def test_license_closed_interval_shared_endpoint_overlaps(api):
    """PRD §2.10: "A license window is a closed interval running from valid_from to
    valid_until inclusive of both ends; two license windows on the same project
    overlap if they share any instant, and a creation that would overlap an existing
    project license is rejected with ERR_INTERVAL_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/license_closed_interval_overlap_includes_shared_endpoint
    """
    studio, client, project, _ = create_and_activate_project([20000], deposit_pct=0.20, service_type="WEB")
    sid, pid = studio["id"], project["id"]
    get_success_data(api.create_license(
        sid, create_license_payload(pid, "2026-03-01T00:00:00Z", "2026-03-10T00:00:00Z", kind="STOCK", cost_cents=1000), SO
    ))
    # second window [2026-03-10, 2026-03-20] shares the endpoint 2026-03-10
    resp = api.create_license(
        sid, create_license_payload(pid, "2026-03-10T00:00:00Z", "2026-03-20T00:00:00Z", kind="FONT", cost_cents=1000), SO
    )
    validate_error(resp, ApiErrorId.ERR_INTERVAL_OVERLAP.value)


def test_license_non_overlapping_window_accepted(api):
    """PRD §2.10: "two license windows on the same project overlap if they share any
    instant" — windows that share no instant are accepted.

    Design: Difficulty/resource_temporal_overlap/license_closed_interval_overlap_includes_shared_endpoint
    """
    studio, client, project, _ = create_and_activate_project([20000], deposit_pct=0.20, service_type="WEB")
    sid, pid = studio["id"], project["id"]
    get_success_data(api.create_license(
        sid, create_license_payload(pid, "2026-03-01T00:00:00Z", "2026-03-10T00:00:00Z", kind="STOCK", cost_cents=1000), SO
    ))
    # window starting strictly after the prior end shares no instant
    lic2 = validate_success(api.create_license(
        sid, create_license_payload(pid, "2026-03-11T00:00:00Z", "2026-03-20T00:00:00Z", kind="FONT", cost_cents=1000), SO
    ), expected_status=201)
    assert lic2["status"] == "RESERVED"


def test_care_cycle_half_open_touching_endpoint_accepted(api):
    """PRD §2.10: "A care cycle window is a half-open interval running from
    period_start inclusive to period_end exclusive; two care-cycle windows on the
    same retainer overlap if they share any instant in their half-open extents"

    Design: Difficulty/resource_temporal_overlap/care_cycle_half_open_interval_endpoint_touch_is_allowed
    """
    set_clock("2026-03-01T00:00:00Z", SO)
    sid, cid, retainer = create_active_retainer()
    rid = retainer["id"]
    get_success_data(api.create_care_cycle(
        sid, rid, create_care_cycle_payload("2026-03-01T00:00:00Z", "2026-04-01T00:00:00Z", hours_used=3), SO
    ))
    # touching cycle starts exactly where the prior ends -> half-open => no shared instant
    cc2 = validate_success(api.create_care_cycle(
        sid, rid, create_care_cycle_payload("2026-04-01T00:00:00Z", "2026-05-01T00:00:00Z", hours_used=2), SO
    ), expected_status=201)
    assert cc2["status"] == "OPEN"


def test_care_cycle_half_open_straddling_window_rejected(api):
    """PRD §2.10: "an overlapping creation is likewise rejected with
    ERR_INTERVAL_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/care_cycle_half_open_interval_endpoint_touch_is_allowed
    """
    set_clock("2026-03-01T00:00:00Z", SO)
    sid, cid, retainer = create_active_retainer()
    rid = retainer["id"]
    get_success_data(api.create_care_cycle(
        sid, rid, create_care_cycle_payload("2026-03-01T00:00:00Z", "2026-04-01T00:00:00Z", hours_used=3), SO
    ))
    # straddling cycle [2026-03-15, 2026-04-15) shares instants with [03-01, 04-01)
    resp = api.create_care_cycle(
        sid, rid, create_care_cycle_payload("2026-03-15T00:00:00Z", "2026-04-15T00:00:00Z", hours_used=1), SO
    )
    validate_error(resp, ApiErrorId.ERR_INTERVAL_OVERLAP.value)


def test_license_invalid_interval_from_after_until_rejected(api):
    """PRD §2.10: "a window whose start is not strictly before its end — a license
    with valid_from at or after valid_until, or a care cycle with period_start at or
    after period_end — is malformed and rejected with ERR_INVALID_INTERVAL."

    Design: Corner/entities/license_invalid_interval_from_after_until_rejected
    """
    studio, client, project, _ = create_and_activate_project([20000], deposit_pct=0.20, service_type="WEB")
    sid, pid = studio["id"], project["id"]
    resp = api.create_license(
        sid, create_license_payload(pid, "2026-03-10T00:00:00Z", "2026-03-01T00:00:00Z", kind="STOCK", cost_cents=1000), SO
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_INTERVAL.value)


def test_care_cycle_invalid_interval_start_after_end_rejected(api):
    """PRD §2.10: "or a care cycle with period_start at or after period_end — is
    malformed and rejected with ERR_INVALID_INTERVAL."

    Design: Corner/validations/care_cycle_invalid_interval_start_after_end
    """
    set_clock("2026-03-01T00:00:00Z", SO)
    sid, cid, retainer = create_active_retainer()
    resp = api.create_care_cycle(
        sid, retainer["id"],
        create_care_cycle_payload("2026-04-01T00:00:00Z", "2026-03-01T00:00:00Z", hours_used=1), SO
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_INTERVAL.value)
