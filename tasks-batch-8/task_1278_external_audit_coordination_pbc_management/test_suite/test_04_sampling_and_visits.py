"""Sampling window overlap (half-open) and fieldwork visit overlap (closed)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_fieldwork_visit,
    assert_sampling_request,
    create_fieldwork_engagement,
    create_sampling,
    create_sampling_request_payload,
    create_fieldwork_visit_payload,
    create_visit,
    dispatch_sampling,
    get_sampling,
    get_visit,
    make_auditor_headers,
    validate_error,
    validate_success,
)

AUDITOR = TEST_USERS["auditor_headers"]


class TestSamplingLocationSet:

    def test_empty_location_ids_rejected(self):
        """PRD §3.4: "Field shape is enforced at creation: `window_end`
        strictly after `window_start` (`ERR_INVALID_SAMPLING_WINDOW`),
        `sample_size` at least 1 (`ERR_INVALID_SAMPLE_SIZE`), and the location
        array non-empty (`ERR_NO_SAMPLING_LOCATIONS`)."

        Design: Difficulty/boundary_precision_check/sampling_locations_empty_set_rejected
        """
        eng, _loc = create_fieldwork_engagement(client_name="MuCo")
        resp = api_client.create_sampling_request(
            create_sampling_request_payload(
                eng["id"], [], title="Empty",
                window_start="2026-09-01", window_end="2026-09-15",
                sample_size=5),
            AUDITOR,
        )
        validate_error(resp, ApiErrorId.ERR_NO_SAMPLING_LOCATIONS)

    def test_single_location_accepted(self):
        """PRD §3.4: "An `ExternalAuditor` creates a sampling request with an
        `engagement_id`, a `title`, a non-empty `location_ids` array whose
        every element must reference a location registered under the same
        engagement, a `window_start` date, a `window_end` date, and a
        `sample_size` giving the number of items to pull per location."
        PRD §3.4: "A new request starts in `DRAFT`".

        Design: Difficulty/boundary_precision_check/sampling_locations_empty_set_rejected
        """
        eng, loc = create_fieldwork_engagement(client_name="MuCo")
        resp = api_client.create_sampling_request(
            create_sampling_request_payload(
                eng["id"], [loc["id"]], title="Solo",
                window_start="2026-09-01", window_end="2026-09-15",
                sample_size=5),
            AUDITOR,
        )
        data = validate_success(resp, expected_status=201)
        assert_sampling_request(data)
        assert data["status"] == "DRAFT"
        assert data["location_ids"] == [loc["id"]]

    def test_sample_size_zero_rejected(self):
        """PRD §3.4: "Field shape is enforced at creation: `window_end`
        strictly after `window_start` (`ERR_INVALID_SAMPLING_WINDOW`),
        `sample_size` at least 1 (`ERR_INVALID_SAMPLE_SIZE`), and the location
        array non-empty (`ERR_NO_SAMPLING_LOCATIONS`)."

        Design: Corner/errors/error_invalid_sample_size
        """
        eng, loc = create_fieldwork_engagement(client_name="C")
        resp = api_client.create_sampling_request(
            create_sampling_request_payload(
                eng["id"], [loc["id"]], title="T",
                window_start="2026-09-01", window_end="2026-09-15",
                sample_size=0),
            AUDITOR,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_SAMPLE_SIZE)


class TestSamplingWindowHalfOpen:

    def test_adjacent_half_open_windows_both_dispatch(self):
        """PRD §3.4: "A conflict exists only when the new window's
        `window_start` falls before the existing window's `window_end` **and**
        the existing window's `window_start` falls before the new window's
        `window_end`; windows that merely touch — the new `window_start` equal
        to an existing `window_end` — do not overlap."

        Design: Difficulty/resource_temporal_overlap/sampling_window_half_open_adjacency_allowed
        """
        eng, loc = create_fieldwork_engagement(client_name="Omicron")
        s1 = create_sampling(eng["id"], [loc["id"]], title="S1",
                             window_start="2026-09-01",
                             window_end="2026-09-15")
        dispatch_sampling(s1["id"])
        s2 = create_sampling(eng["id"], [loc["id"]], title="S2 adjacent",
                             window_start="2026-09-15",
                             window_end="2026-09-30")
        resp = api_client.dispatch_sampling_request(s2["id"], AUDITOR)
        data = validate_success(resp)
        assert data["status"] == "DISPATCHED", (
            "windows that merely touch (new start == existing end) do not "
            f"overlap, got {data['status']}"
        )

    def test_overlapping_windows_rejected_on_dispatch(self):
        """PRD §3.4: "A conflict exists only when the new window's
        `window_start` falls before the existing window's `window_end` **and**
        the existing window's `window_start` falls before the new window's
        `window_end`; windows that merely touch — the new `window_start` equal
        to an existing `window_end` — do not overlap. Any conflict rejects the
        dispatch with `ERR_SAMPLING_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/sampling_window_half_open_adjacency_allowed
        """
        eng, loc = create_fieldwork_engagement(client_name="Omicron")
        s1 = create_sampling(eng["id"], [loc["id"]], title="S1",
                             window_start="2026-09-01",
                             window_end="2026-09-15")
        dispatch_sampling(s1["id"])
        s2 = create_sampling(eng["id"], [loc["id"]], title="S2 overlap",
                             window_start="2026-09-10",
                             window_end="2026-09-20")
        resp = api_client.dispatch_sampling_request(s2["id"], AUDITOR)
        validate_error(resp, ApiErrorId.ERR_SAMPLING_WINDOW_OVERLAP)
        assert get_sampling(s2["id"])["status"] == "DRAFT", \
            "rejected dispatch leaves the request in DRAFT"


class TestFieldworkVisitOverlap:

    def test_visits_sharing_a_single_date_rejected(self):
        """PRD §3.5: "Against every existing `SCHEDULED` visit for the same
        `auditor_user_id`, an overlap exists whenever the new `visit_start` is
        on or before the existing `visit_end` and the existing `visit_start`
        is on or before the new `visit_end` — so two visits sharing even a
        single calendar date conflict."
        PRD §3.5: "Either failure rejects the scheduling with
        `ERR_VISIT_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/fieldwork_visit_closed_interval_with_buffer
        """
        eng, loc = create_fieldwork_engagement(client_name="PiLLC")
        create_visit(eng["id"], loc["id"], auditor_user="aud1",
                     visit_start="2026-09-01", visit_end="2026-09-10")
        resp = api_client.create_fieldwork_visit(
            create_fieldwork_visit_payload(
                eng["id"], loc["id"], auditor_user_id="aud1",
                visit_start="2026-09-10", visit_end="2026-09-15"),
            AUDITOR,
        )
        validate_error(resp, ApiErrorId.ERR_VISIT_WINDOW_OVERLAP)

    def test_different_auditor_same_window_allowed(self):
        """PRD §3.5: "Visits for different auditors never interfere."
        PRD §3.5: "A new visit starts `SCHEDULED`".

        Design: Difficulty/resource_temporal_overlap/fieldwork_visit_closed_interval_with_buffer
        """
        eng, loc = create_fieldwork_engagement(client_name="PiLLC")
        v1 = create_visit(eng["id"], loc["id"], auditor_user="aud1",
                          visit_start="2026-09-01", visit_end="2026-09-10")
        assert v1["status"] == "SCHEDULED"
        resp = api_client.create_fieldwork_visit(
            create_fieldwork_visit_payload(
                eng["id"], loc["id"], auditor_user_id="aud2",
                visit_start="2026-09-01", visit_end="2026-09-10"),
            AUDITOR,
        )
        data = validate_success(resp, expected_status=201)
        assert_fieldwork_visit(data)
        assert data["status"] == "SCHEDULED", (
            "identical window for a different auditor must not interfere"
        )
