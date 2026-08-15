"""Impairment windows: date-range sanity, half-open overlap, and the
four-hour re-certification buffer."""
from test_helpers import (
    ApiErrorId,
    assert_impairment,
    create_impairment_payload,
    get_success_data,
    setup_inspection_site,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

MARSHAL = TEST_USERS["fire_marshal_headers"]

_EXISTING = ("2026-08-10T08:00:00Z", "2026-08-10T12:00:00Z")


def _site_with_planned_impairment(api, legal_name):
    ctx = setup_inspection_site(system_category="SPRINKLER", device_count=0,
                                legal_name=legal_name)
    imp = get_success_data(api.create_impairment(
        ctx["sys"]["id"],
        create_impairment_payload(impairment_kind="PLANNED",
                                  planned_start=_EXISTING[0],
                                  planned_end=_EXISTING[1]),
        ctx["admin"]), 201)
    assert_impairment(imp)
    ctx["imp"] = imp
    return ctx


def _attempt(api, ctx, start, end):
    return api.create_impairment(
        ctx["sys"]["id"],
        create_impairment_payload(impairment_kind="PLANNED",
                                  planned_start=start, planned_end=end),
        ctx["admin"])


class TestImpairmentOverlap:
    def test_partial_overlap_rejected(self, api):
        """PRD §3.6: "A new `PLANNED` impairment is rejected with
        `ERR_IMPAIRMENT_OVERLAP` when its half-open window — start inclusive, end
        exclusive — overlaps that of any other non-`CLOSED` impairment on the
        system"

        Design: Difficulty/priority_pair_validation_conflict/temporal_overlap_beats_technician_capacity
        """
        ctx = _site_with_planned_impairment(api, "Overlap Co")
        resp = _attempt(api, ctx, "2026-08-10T10:00:00Z", "2026-08-10T14:00:00Z")
        validate_error(resp, ApiErrorId.ERR_IMPAIRMENT_OVERLAP)
        assert resp.status_code == 409
        remaining = get_success_data(api.list_impairments(ctx["sys"]["id"], ctx["admin"]))
        assert len(remaining) == 1, "the rejected overlap persists no second row"

    def test_contained_overlap_rejected(self, api):
        """PRD §3.6: "A new `PLANNED` impairment is rejected with
        `ERR_IMPAIRMENT_OVERLAP` when its half-open window — start inclusive, end
        exclusive — overlaps that of any other non-`CLOSED` impairment on the
        system"

        Design: Difficulty/priority_pair_validation_conflict/temporal_overlap_beats_technician_capacity
        """
        ctx = _site_with_planned_impairment(api, "Overlap Co")
        resp = _attempt(api, ctx, "2026-08-10T09:00:00Z", "2026-08-10T11:00:00Z")
        validate_error(resp, ApiErrorId.ERR_IMPAIRMENT_OVERLAP)
        assert resp.status_code == 409, (
            "a window entirely inside an existing window still overlaps")


class TestReCertificationBuffer:
    def test_adjacent_start_rejected_inside_buffer(self, api):
        """PRD §3.6: "the new start must be at least four hours after the other's
        `planned_end`, a start exactly equal to the other's end is inside the
        buffer and rejected, and a start exactly four hours after the other's end
        is allowed."

        Design: Difficulty/resource_temporal_overlap/impairment_buffer_adjacency_rejected_half_open
        """
        ctx = _site_with_planned_impairment(api, "Buffer Co")
        resp = _attempt(api, ctx, "2026-08-10T12:00:00Z", "2026-08-10T14:00:00Z")
        validate_error(resp, ApiErrorId.ERR_IMPAIRMENT_OVERLAP)
        assert resp.status_code == 409, (
            "start exactly equal to the prior end is inside the four-hour buffer")

    def test_start_exactly_four_hours_after_end_allowed(self, api):
        """PRD §3.6: "the new start must be at least four hours after the other's
        `planned_end`, a start exactly equal to the other's end is inside the
        buffer and rejected, and a start exactly four hours after the other's end
        is allowed."

        Design: Difficulty/resource_temporal_overlap/impairment_buffer_adjacency_rejected_half_open
        """
        ctx = _site_with_planned_impairment(api, "Buffer Co")
        resp = _attempt(api, ctx, "2026-08-10T16:00:00Z", "2026-08-10T18:00:00Z")
        imp = validate_success(resp, 201)
        assert_impairment(imp)
        assert imp["planned_start"].startswith("2026-08-10T16:00"), (
            "start exactly four hours after the prior end satisfies the buffer")


class TestDateRangeSanity:
    def test_planned_end_equal_to_start_rejected(self, api):
        """PRD §2.6: "10. **Date-range sanity** — every end must be strictly after
        its start: `expires_on` strictly after `issued_on`, `scheduled_end`
        strictly after `scheduled_start`, `planned_end` strictly after
        `planned_start`; failure yields `ERR_INVALID_DATE_RANGE`."

        Design: Corner/validations/invalid_date_range_rejected
        """
        ctx = setup_inspection_site(system_category="SPRINKLER", device_count=0,
                                    legal_name="Range Co")
        resp = _attempt(api, ctx, "2026-08-10T08:00:00Z", "2026-08-10T08:00:00Z")
        validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE)
        assert resp.status_code == 422
