"""Temporal-window rules: half-open development-pattern windows (adjacency
allowed, interior intersection rejected) versus closed catastrophe-event
intervals (touching rejected), the catastrophe-window assignment gate, and
the segregation cascade fired by catastrophe assignment (PRD §3.1, §3.2,
§3.4).
"""
from test_helpers import (
    ApiErrorId,
    aggregate_triangle,
    create_catastrophe_event,
    create_claim,
    create_pattern,
    create_segment,
    post_payment,
    select_pattern,
    validate_error,
    validate_success,
)


def _pattern_book():
    """Segment with one paid claim and a fresh triangle at 2025-Q2, ready for
    pattern creation."""
    segment = create_segment(name="Main Book", line_of_business="COMMERCIAL_AUTO")
    claim = create_claim(
        segment["id"],
        claim_number="C-A",
        accident_date="2025-01-15",
        report_date="2025-01-20",
    )
    post_payment(claim["id"], "2025-02-01T00:00:00Z", 100000)
    aggregate_triangle(segment["id"], "PAID", "2025-Q2")
    return {"segment": segment, "claim": claim}


def _cat_book():
    segment = create_segment(name="Cat Book", line_of_business="PROPERTY")
    event = create_catastrophe_event(
        segment["id"], name="CAT-1", start_date="2025-01-01", end_date="2025-03-31"
    )
    return {"segment": segment, "event": event}


class TestPatternWindowOverlap:
    def test_pattern_window_adjacency_allowed(self, api, actuarial_analyst_headers):
        """PRD §3.4: "Windows that merely touch — the incoming window beginning
        exactly where the incumbent ends — are adjacent, not overlapping, and
        are allowed."

        Design: Difficulty/resource_temporal_overlap/pattern_window_half_open_overlap_and_adjacency
        """
        ctx = _pattern_book()
        segment_id = ctx["segment"]["id"]
        incumbent = create_pattern(
            segment_id, "PAID", "2025-Q2", "2025-Q3", "2026-Q2"
        )
        select_pattern(incumbent["id"])

        adjacent = create_pattern(
            segment_id, "PAID", "2025-Q2", "2026-Q2", "2026-Q4"
        )
        resp = api.select_development_pattern(
            adjacent["id"], actuarial_analyst_headers
        )
        data = validate_success(resp, 200)
        assert data["status"] == "SELECTED", (
            "a window starting exactly at the incumbent's end is adjacent, not overlapping"
        )

    def test_pattern_window_overlap_rejected(self, api, actuarial_analyst_headers):
        """PRD §3.4: "Two windows intersect precisely when the incoming
        pattern's `effective_from_quarter` is earlier than the incumbent's
        `effective_to_quarter` and, at the same time, the incumbent's
        `effective_from_quarter` is earlier than the incoming pattern's
        `effective_to_quarter`; an intersecting selection is refused with
        `ERR_PATTERN_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/pattern_window_half_open_overlap_and_adjacency
        """
        ctx = _pattern_book()
        segment_id = ctx["segment"]["id"]
        incumbent = create_pattern(
            segment_id, "PAID", "2025-Q2", "2025-Q3", "2026-Q2"
        )
        select_pattern(incumbent["id"])

        overlapping = create_pattern(
            segment_id, "PAID", "2025-Q2", "2026-Q1", "2026-Q3"
        )
        resp = api.select_development_pattern(
            overlapping["id"], actuarial_analyst_headers
        )
        validate_error(resp, ApiErrorId.ERR_PATTERN_PERIOD_OVERLAP)

        data = validate_success(
            api.get_development_pattern(overlapping["id"], actuarial_analyst_headers)
        )
        assert data["status"] == "DRAFT", "a rejected selection must leave the pattern DRAFT"

    def test_pattern_select_twice_returns_invalid_state(
        self, api, actuarial_analyst_headers
    ):
        """PRD §3.4: "Acting on a pattern from a status other than the declared
        start of a transition — selecting a `SELECTED` pattern, or selecting or
        withdrawing a `WITHDRAWN` one — is refused with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/pattern_select_twice_returns_invalid_state
        """
        ctx = _pattern_book()
        pattern = create_pattern(
            ctx["segment"]["id"], "PAID", "2025-Q2", "2025-Q2", "2026-Q1"
        )
        select_pattern(pattern["id"])
        resp = api.select_development_pattern(pattern["id"], actuarial_analyst_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestPatternCreationGuards:
    def test_invalid_pattern_window_rejected(self, api, actuarial_analyst_headers):
        """PRD §3.4: "The window is half-open — inclusive at the start,
        exclusive at the end — and the start must be strictly earlier than the
        end, otherwise creation is refused with `ERR_INVALID_PATTERN_WINDOW`."

        Design: Corner/validations/invalid_pattern_window_rejected
        """
        ctx = _pattern_book()
        resp = api.create_development_pattern(
            {
                "segment_id": ctx["segment"]["id"],
                "basis": "PAID",
                "valuation_quarter": "2025-Q2",
                "effective_from_quarter": "2025-Q3",
                "effective_to_quarter": "2025-Q1",
            },
            actuarial_analyst_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_PATTERN_WINDOW)

    def test_pattern_create_without_triangle_returns_404(
        self, api, actuarial_analyst_headers
    ):
        """PRD §3.4: "The referenced triangle must exist (`ERR_NOT_FOUND`
        otherwise) and must not be stale (a stale source triangle is refused
        with `ERR_TRIANGLE_STALE`)."

        Design: Corner/validations/pattern_create_without_triangle_returns_404
        """
        segment = create_segment(name="Empty Book", line_of_business="WORKERS_COMP")
        resp = api.create_development_pattern(
            {
                "segment_id": segment["id"],
                "basis": "PAID",
                "valuation_quarter": "2025-Q4",
                "effective_from_quarter": "2025-Q4",
                "effective_to_quarter": "2026-Q1",
            },
            actuarial_analyst_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestCatastropheEventWindows:
    def test_cat_event_touching_interval_rejected(self, api, appointed_actuary_headers):
        """PRD §3.1: "Two events of the same segment may not overlap — and
        because the window is closed, merely touching counts as overlap: an
        event whose start date falls on the exact day another event of the
        segment ends is refused with `ERR_CAT_EVENT_DATE_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/cat_event_closed_interval_touching_rejected
        """
        ctx = _cat_book()
        resp = api.create_catastrophe_event(
            {
                "segment_id": ctx["segment"]["id"],
                "name": "CAT-2",
                "start_date": "2025-03-31",
                "end_date": "2025-06-30",
            },
            appointed_actuary_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CAT_EVENT_DATE_OVERLAP)

    def test_cat_event_disjoint_interval_accepted(self, api, appointed_actuary_headers):
        """PRD §3.1: "An event is created for a segment with a `segment_id`, a
        `name` such as a hurricane designation, and a closed accident-date
        window given by `start_date` and `end_date`: both endpoints of the
        window are inclusive, and the end date must not be earlier than the
        start date."

        Design: Difficulty/resource_temporal_overlap/cat_event_closed_interval_touching_rejected
        """
        ctx = _cat_book()
        resp = api.create_catastrophe_event(
            {
                "segment_id": ctx["segment"]["id"],
                "name": "CAT-3",
                "start_date": "2025-04-01",
                "end_date": "2025-06-30",
            },
            appointed_actuary_headers,
        )
        data = validate_success(resp, 201)
        assert data["start_date"] == "2025-04-01"
        assert data["end_date"] == "2025-06-30"


class TestCatastropheAssignment:
    def test_claim_outside_cat_window_rejected(self, api, claims_examiner_headers):
        """PRD §3.2: "The claim's `accident_date` must fall within the event's
        closed window, inclusive of both endpoints; otherwise the update is
        refused with `ERR_CLAIM_OUTSIDE_CAT_WINDOW`."

        Design: Corner/validations/claim_outside_cat_window_rejected
        """
        ctx = _cat_book()
        claim = create_claim(
            ctx["segment"]["id"],
            claim_number="C-O",
            accident_date="2025-04-10",
            report_date="2025-04-12",
        )
        resp = api.patch_claim(
            claim["id"],
            {"catastrophe_event_id": ctx["event"]["id"]},
            claims_examiner_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CLAIM_OUTSIDE_CAT_WINDOW)

        data = validate_success(api.get_claim(claim["id"], claims_examiner_headers))
        assert data["catastrophe_event_id"] is None, (
            "a rejected assignment must leave the claim unattached"
        )

    def test_patch_claim_assign_catastrophe_segregates_and_stales(
        self, api, claims_examiner_headers, actuarial_analyst_headers
    ):
        """PRD §3.2: "Because assigning or clearing an event changes layer
        membership, the update recomputes `is_segregated`, increments the
        claim's `version`, and fires the staleness cascade of §2.7 across every
        triangle of the segment."
        PRD §3.2: "`is_segregated` is true when the claim is a large loss or
        carries a catastrophe event assignment."

        Design: Corner/endpoints/patch_claim_assign_catastrophe_segregates_and_stales
        """
        ctx = _cat_book()
        claim = create_claim(
            ctx["segment"]["id"],
            claim_number="C-C",
            accident_date="2025-02-10",
            report_date="2025-02-12",
        )
        post_payment(claim["id"], "2025-02-15T00:00:00Z", 100000)
        triangle = aggregate_triangle(ctx["segment"]["id"], "PAID", "2025-Q1")
        assert triangle["is_stale"] is False

        resp = api.patch_claim(
            claim["id"],
            {"catastrophe_event_id": ctx["event"]["id"]},
            claims_examiner_headers,
        )
        data = validate_success(resp, 200)
        assert data["catastrophe_event_id"] == ctx["event"]["id"]
        assert data["is_segregated"] is True, (
            "carrying a catastrophe event assignment makes the claim segregated"
        )

        tri = validate_success(
            api.get_triangle(triangle["id"], actuarial_analyst_headers)
        )
        assert tri["is_stale"] is True, (
            "layer membership changed, so every triangle of the segment turns stale"
        )
