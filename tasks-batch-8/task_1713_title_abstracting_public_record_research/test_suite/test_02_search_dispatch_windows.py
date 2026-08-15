"""Search assignment dispatch: work windows, overlap, and dispatch RBAC (PRD §3.3)."""
from test_helpers import (
    ApiErrorId,
    assert_search_assignment,
    create_assignment_payload,
    create_order,
    get_order,
    is_valid_uuid,
    make_client_headers,
    make_ops_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestDispatch:
    def test_search_assignment_created_in_initial_state(self, api):
        """PRD §3.3: "The first assignment created for an order moves that order
        from `RECEIVED` to `SEARCH_IN_PROGRESS` as an automatic side effect,
        incrementing the order's `version` by one."
        PRD §3.3: "Each assignment tracks three read-only counters:
        `document_count`, the number of linked documents not in `VOID` status;
        `verified_count`, the number of linked documents in `VERIFIED` status; and
        `revision_count`, which starts at 0 and increments by one each time the
        assignment is returned for correction."
        PRD §3.3: "The assignment itself begins in `IN_PROGRESS`."

        Design: Corner/entities/search_assignment_created_in_initial_state
        """
        order = create_order("client_806", property_address="15 Cedar St")
        resp = api.create_search_assignment(
            create_assignment_payload(
                order["id"],
                "abs_806",
                search_type="LIEN_JUDGMENT_TAX",
                window_start="2026-08-01T09:00:00Z",
                window_end="2026-08-01T12:00:00Z",
            ),
            make_ops_headers(),
        )
        assignment = validate_success(resp, 201)
        assert_search_assignment(assignment)
        assert assignment["status"] == "IN_PROGRESS"
        assert assignment["document_count"] == 0
        assert assignment["verified_count"] == 0
        assert assignment["revision_count"] == 0

        refreshed = get_order(order["id"])
        assert refreshed["status"] == "SEARCH_IN_PROGRESS", (
            f"first assignment must start the search phase, got {refreshed['status']}"
        )

    def test_assignment_create_by_client_forbidden(self, api):
        """PRD §2.1: "A request whose role is not permitted on the target endpoint
        — or whose `X-User-ID` fails an attribute-ownership rule — is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: POST /api/search-assignments is authorized for OperationsManager
        only.

        Design: Corner/rbac/assignment_create_by_client_forbidden
        """
        order = create_order("client_861", property_address="80 Bee St")
        resp = api.create_search_assignment(
            create_assignment_payload(
                order["id"],
                "abs_861",
                window_start="2026-08-01T09:00:00Z",
                window_end="2026-08-01T17:00:00Z",
            ),
            make_client_headers("client_861"),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestAbstracterWindowOverlap:
    def _setup_first_window(self, api):
        order = create_order("client_771", property_address="1100 E 11th St")
        first = api.create_search_assignment(
            create_assignment_payload(
                order["id"],
                "abs_771",
                window_start="2026-08-01T09:00:00Z",
                window_end="2026-08-01T11:00:00Z",
            ),
            make_ops_headers(),
        )
        validate_success(first, 201)
        return order

    def test_touching_windows_permitted_under_half_open_semantics(self, api):
        """PRD §3.3: "the new window must not intersect any non-`CANCELLED`
        assignment window of the same `abstracter_ref`, under half-open semantics
        two windows that merely touch — one ending exactly where the other begins
        — are permitted, and any true intersection is rejected with
        `ERR_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/abstracter_window_half_open_touch_allowed_intersection_rejected
        """
        order = self._setup_first_window(api)
        touch = api.create_search_assignment(
            create_assignment_payload(
                order["id"],
                "abs_771",
                search_type="LIEN_JUDGMENT_TAX",
                window_start="2026-08-01T11:00:00Z",
                window_end="2026-08-01T13:00:00Z",
            ),
            make_ops_headers(),
        )
        touched = validate_success(touch, 201)
        assert is_valid_uuid(touched["id"]), (
            "touching window [11:00,13:00) must be accepted under half-open semantics"
        )
        assert touched["status"] == "IN_PROGRESS"

    def test_intersecting_window_rejected_with_overlap_error(self, api):
        """PRD §3.3: "the new window must not intersect any non-`CANCELLED`
        assignment window of the same `abstracter_ref`, under half-open semantics
        two windows that merely touch — one ending exactly where the other begins
        — are permitted, and any true intersection is rejected with
        `ERR_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/abstracter_window_half_open_touch_allowed_intersection_rejected
        """
        order = self._setup_first_window(api)
        touch = api.create_search_assignment(
            create_assignment_payload(
                order["id"],
                "abs_771",
                search_type="LIEN_JUDGMENT_TAX",
                window_start="2026-08-01T11:00:00Z",
                window_end="2026-08-01T13:00:00Z",
            ),
            make_ops_headers(),
        )
        validate_success(touch, 201)

        overlap = api.create_search_assignment(
            create_assignment_payload(
                order["id"],
                "abs_771",
                search_type="LIEN_JUDGMENT_TAX",
                window_start="2026-08-01T12:30:00Z",
                window_end="2026-08-01T14:00:00Z",
            ),
            make_ops_headers(),
        )
        validate_error(overlap, ApiErrorId.ERR_WINDOW_OVERLAP)


class TestWindowInvalidBeatsOverlap:
    def _setup(self, api):
        order = create_order("client_742", property_address="500 W 7th St")
        first = api.create_search_assignment(
            create_assignment_payload(
                order["id"],
                "abs_742",
                window_start="2026-08-01T09:00:00Z",
                window_end="2026-08-01T11:00:00Z",
            ),
            make_ops_headers(),
        )
        validate_success(first, 201)
        return order

    def test_inverted_window_rejected_as_temporal_error_despite_overlap(self, api):
        """PRD §3.3: "The window is a half-open interval: it must be strictly
        ordered, so a `window_end` that is not later than `window_start` is
        rejected with `ERR_WINDOW_INVALID` (HTTP 422)."
        PRD §2.10: "then the domain business rules — waiver safety, temporal
        windows, overlap and buffer conflicts, uniqueness, OCC staleness — each at
        its declared position. When several rules could reject the same request,
        the one earliest in this order is the error the client receives; for
        example, an attempt to post a fee against a retrieval that is already
        `INVOICED` on an already-delivered order surfaces `ERR_ALREADY_INVOICED`,
        never `ERR_ORDER_TERMINAL`."

        Design: Difficulty/priority_pair_validation_conflict/assignment_window_invalid_temporal_beats_overlap_constraint
        """
        order = self._setup(api)
        resp = api.create_search_assignment(
            create_assignment_payload(
                order["id"],
                "abs_742",
                search_type="LIEN_JUDGMENT_TAX",
                window_start="2026-08-01T10:00:00Z",
                window_end="2026-08-01T09:30:00Z",
            ),
            make_ops_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_INVALID)
        assert resp.status_code == 422, (
            f"temporal sanity must beat the overlap constraint (409), got {resp.status_code}"
        )

    def test_rejected_inverted_window_creates_no_assignment(self, api):
        """PRD §3.3: "The window is a half-open interval: it must be strictly
        ordered, so a `window_end` that is not later than `window_start` is
        rejected with `ERR_WINDOW_INVALID` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/assignment_window_invalid_temporal_beats_overlap_constraint
        """
        order = self._setup(api)
        resp = api.create_search_assignment(
            create_assignment_payload(
                order["id"],
                "abs_742",
                search_type="LIEN_JUDGMENT_TAX",
                window_start="2026-08-01T10:00:00Z",
                window_end="2026-08-01T09:30:00Z",
            ),
            make_ops_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_INVALID)

        listing, meta = validate_paginated(
            api.list_search_assignments(make_ops_headers(), params={"order_id": order["id"]})
        )
        assert meta["total_count"] == 1, (
            f"rejected create must be atomic — only the first assignment exists, got {meta['total_count']}"
        )
        assert len(listing) == 1
