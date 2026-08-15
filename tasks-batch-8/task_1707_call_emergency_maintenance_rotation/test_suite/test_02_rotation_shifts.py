"""Rotation shifts: half-open overlap, OCC-guarded transfer, pagination."""
from test_helpers import (
    ApiErrorId,
    assert_rotation_shift,
    create_completed_shift,
    create_rotation_shift_payload,
    get_shift,
    make_technician,
    parse_instant,
    publish_shift,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestShiftHalfOpenOverlap:
    def _setup_tech_with_shift_a(self):
        tech = make_technician()
        shift_a = publish_shift(
            tech["id"], "2026-08-01T08:00:00Z", "2026-08-01T16:00:00Z"
        )
        return tech, shift_a

    def test_adjacent_shift_at_exact_end_boundary_is_allowed(
        self, api, property_admin_headers
    ):
        """PRD §2.10: "**Rotation shifts** occupy a half-open interval: the
        shift covers its `start_at` inclusive and its `end_at` exclusive, so
        two shifts of the same technician where one ends exactly when the other
        begins are adjacent, not overlapping."
        PRD §3.2: "rejects any half-open overlap with that technician's
        existing `PUBLISHED` or `ACTIVE` shifts with `ERR_SHIFT_OVERLAP` —
        adjacency, where one shift's `end_at` equals the other's `start_at`,
        is allowed."

        Design: Difficulty/resource_temporal_overlap/shift_half_open_adjacency_allowed_overlap_rejected
        """
        tech, shift_a = self._setup_tech_with_shift_a()
        resp = api.create_rotation_shift(
            create_rotation_shift_payload(
                technician_id=tech["id"],
                start_at="2026-08-01T16:00:00Z",
                end_at="2026-08-02T00:00:00Z",
            ),
            property_admin_headers,
        )
        data = validate_success(resp, 201)
        assert_rotation_shift(data)
        assert data["status"] == "PUBLISHED", (
            "adjacent shift (start 16:00 == A.end 16:00) must publish"
        )

    def test_interior_overlap_shift_rejected(self, api, property_admin_headers):
        """PRD §3.2: "rejects any half-open overlap with that technician's
        existing `PUBLISHED` or `ACTIVE` shifts with `ERR_SHIFT_OVERLAP` —
        adjacency, where one shift's `end_at` equals the other's `start_at`,
        is allowed."

        Design: Difficulty/resource_temporal_overlap/shift_half_open_adjacency_allowed_overlap_rejected
        """
        tech, shift_a = self._setup_tech_with_shift_a()
        # Adjacent one first: legal.
        validate_success(
            api.create_rotation_shift(
                create_rotation_shift_payload(
                    technician_id=tech["id"],
                    start_at="2026-08-01T16:00:00Z",
                    end_at="2026-08-02T00:00:00Z",
                ),
                property_admin_headers,
            ),
            201,
        )
        resp = api.create_rotation_shift(
            create_rotation_shift_payload(
                technician_id=tech["id"],
                start_at="2026-08-01T15:00:00Z",
                end_at="2026-08-01T17:00:00Z",
            ),
            property_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SHIFT_OVERLAP)
        rows, meta = validate_paginated(
            api.list_rotation_shifts(
                property_admin_headers, params={"technician_id": tech["id"]}
            )
        )
        assert meta["total_count"] == 2 and len(rows) == 2, (
            "the rejected overlap must leave no row behind"
        )


class TestShiftTransferConservation:
    def _setup_two_techs_two_shifts(self):
        t1 = make_technician(full_name="Pat Tech")
        t2 = make_technician(full_name="Terry Two")
        shift_a = publish_shift(
            t1["id"], "2026-08-01T00:00:00Z", "2026-08-01T08:00:00Z"
        )
        shift_b = publish_shift(
            t1["id"], "2026-08-02T00:00:00Z", "2026-08-02T08:00:00Z"
        )
        return t1, t2, shift_a, shift_b

    def test_shift_transfer_rewrites_owner_and_bumps_version(
        self, api, property_admin_headers
    ):
        """PRD §3.2: "A successful transfer rewrites `technician_id`, clears
        `needs_coverage` to false, and increments the shift's `version`."
        PRD §2.5: "`version` (integer): a system-managed integer that
        increments by one on every mutation of the resource and underpins
        optimistic concurrency control."

        Design: Difficulty/compensating_invariant/shift_transfer_conserves_period_minutes
        """
        t1, t2, shift_a, shift_b = self._setup_two_techs_two_shifts()
        v_before = shift_b["version"]
        resp = api.transfer_rotation_shift(
            shift_b["id"],
            {
                "to_technician_id": t2["id"],
                "expected_rotation_shift_version": v_before,
            },
            property_admin_headers,
        )
        data = validate_success(resp, 200)
        assert data["technician_id"] == t2["id"], "transfer must rewrite the owner"
        assert data["version"] == v_before + 1, "transfer increments version by 1"
        assert data["needs_coverage"] is False, "transfer clears the coverage flag"

    def test_shift_transfer_conserves_total_scheduled_minutes(
        self, api, property_admin_headers
    ):
        """PRD §3.2: "A `PUBLISHED` shift can be reassigned by a
        `PropertyAdmin` or `MaintenanceSupervisor` through a transfer carrying
        `to_technician_id` and the OCC field described in §2.7. ... A
        successful transfer rewrites `technician_id`, clears `needs_coverage`
        to false, and increments the shift's `version`."

        Design: Difficulty/compensating_invariant/shift_transfer_conserves_period_minutes
        """
        t1, t2, shift_a, shift_b = self._setup_two_techs_two_shifts()
        validate_success(
            api.transfer_rotation_shift(
                shift_b["id"],
                {
                    "to_technician_id": t2["id"],
                    "expected_rotation_shift_version": shift_b["version"],
                },
                property_admin_headers,
            ),
            200,
        )
        rows_t1, meta_t1 = validate_paginated(
            api.list_rotation_shifts(
                property_admin_headers, params={"technician_id": t1["id"]}
            )
        )
        rows_t2, meta_t2 = validate_paginated(
            api.list_rotation_shifts(
                property_admin_headers, params={"technician_id": t2["id"]}
            )
        )
        assert meta_t1["total_count"] == 1 and rows_t1[0]["id"] == shift_a["id"]
        assert meta_t2["total_count"] == 1 and rows_t2[0]["id"] == shift_b["id"]

        # The transfer moves attribution only: each row keeps its own window,
        # so the combined scheduled minutes are unchanged (480 + 480 == 960).
        def minutes(row):
            return int(
                (parse_instant(row["end_at"]) - parse_instant(row["start_at"]))
                .total_seconds() // 60
            )

        assert minutes(rows_t1[0]) == 480
        assert minutes(rows_t2[0]) == 480
        assert minutes(rows_t1[0]) + minutes(rows_t2[0]) == 960, (
            "scheduled minutes are conserved across the transfer"
        )


def test_completed_shift_cannot_be_cancelled(api, property_admin_headers):
    """PRD §3.2: "Cancelling moves `PUBLISHED → CANCELLED` and increments
    `version`; shifts already started cannot be cancelled."
    PRD §3.2: "The `provisional_shift_pay_cents` is then the standby minutes
    divided by sixty, multiplied by the technician's `base_hourly_rate_cents`,
    and increased by the on-call differential — that is, multiplied by one plus
    `on_call_differential_bp` divided by ten thousand — with the per-shift
    result rounded half-up to whole cents."

    Design: Corner/state_machines/completed_shift_cannot_be_cancelled
    """
    tech = make_technician(base_hourly_rate_cents=4800, on_call_differential_bp=1500)
    completed = create_completed_shift(
        tech["id"],
        "2026-08-01T01:00:00Z",
        "2026-08-01T02:00:00Z",
        start_clock="2026-08-01T01:30:00Z",
        complete_clock="2026-08-01T03:00:00Z",
    )
    assert completed["provisional_shift_pay_cents"] == 5520, (
        "60 standby min x 4800 cents/h x 1.15 differential"
    )
    resp = api.cancel_rotation_shift(completed["id"], property_admin_headers)
    validate_error(resp, ApiErrorId.ERR_ROTATION_SHIFT_INVALID_STATE)
    after = get_shift(completed["id"])
    assert after["status"] == "COMPLETED"
    assert after["provisional_shift_pay_cents"] == 5520, (
        "provisional pay survives the failed cancel"
    )


def test_list_rotation_shifts_paginates_with_envelope(api, property_admin_headers):
    """PRD §2.3: "Paginated and non-paginated list-based responses include the
    following fields in the `meta` object of the response envelope: `limit`,
    `offset`, `total_count`, and `has_more`."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/entities/list_rotation_shifts_paginates_with_envelope
    """
    t1 = make_technician(full_name="Pat Tech")
    t2 = make_technician(full_name="Terry Two")
    publish_shift(t1["id"], "2026-08-01T08:00:00Z", "2026-08-01T16:00:00Z")
    publish_shift(t2["id"], "2026-08-01T08:00:00Z", "2026-08-01T16:00:00Z")

    page1 = api.list_rotation_shifts(
        property_admin_headers, params={"limit": 1, "offset": 0}
    )
    rows1, meta1 = validate_paginated(page1)
    assert len(rows1) == 1
    assert meta1["total_count"] == 2
    assert meta1["has_more"] is True

    page2 = api.list_rotation_shifts(
        property_admin_headers, params={"limit": 1, "offset": 1}
    )
    rows2, meta2 = validate_paginated(page2)
    assert len(rows2) == 1
    assert meta2["total_count"] == 2
    assert meta2["has_more"] is False

    body = page1.json()
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert isinstance(body["meta"].get("api_request_timestamp"), str)
    assert body["response_type"] == "array"


class TestTransferOccAndConsistency:
    def test_occ_transfer_stale_version_rejected(self, api, property_admin_headers):
        """PRD §2.7: "Transferring a published rotation shift requires
        `expected_rotation_shift_version`. Because a transfer leaves the
        shift's `status` untouched, a second transfer issued after a completed
        one observes identical state; only the version check distinguishes a
        stale view. A mismatch with the shift's current `version` is rejected
        with `ERR_STALE_ROTATION_SHIFT_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/occ_transfer_stale_version_rejected
        """
        t1 = make_technician(full_name="Pat Tech")
        t2 = make_technician(full_name="Terry Two")
        t3 = make_technician(full_name="Tom Three")
        shift = publish_shift(
            t1["id"], "2026-08-05T00:00:00Z", "2026-08-05T08:00:00Z"
        )
        v1 = shift["version"]
        first = validate_success(
            api.transfer_rotation_shift(
                shift["id"],
                {"to_technician_id": t2["id"],
                 "expected_rotation_shift_version": v1},
                property_admin_headers,
            ),
            200,
        )
        assert first["technician_id"] == t2["id"]
        assert first["version"] == v1 + 1

        stale = api.transfer_rotation_shift(
            shift["id"],
            {"to_technician_id": t3["id"],
             "expected_rotation_shift_version": v1},
            property_admin_headers,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_ROTATION_SHIFT_VERSION)

        fresh = validate_success(
            api.transfer_rotation_shift(
                shift["id"],
                {"to_technician_id": t3["id"],
                 "expected_rotation_shift_version": first["version"]},
                property_admin_headers,
            ),
            200,
        )
        assert fresh["technician_id"] == t3["id"]

    def test_transfer_response_immediately_reflects_mutation(
        self, api, property_admin_headers
    ):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify
        a resource will return the created or updated resource object in the
        data field."
        PRD §3.2: "A successful transfer rewrites `technician_id`, clears
        `needs_coverage` to false, and increments the shift's `version`."

        Design: Corner/consistency_model/transfer_response_immediately_reflects_mutation
        """
        t1 = make_technician(full_name="Pat Tech")
        t2 = make_technician(full_name="Terry Two")
        shift = publish_shift(
            t1["id"], "2026-08-05T00:00:00Z", "2026-08-05T08:00:00Z"
        )
        v1 = shift["version"]
        data = validate_success(
            api.transfer_rotation_shift(
                shift["id"],
                {"to_technician_id": t2["id"],
                 "expected_rotation_shift_version": v1},
                property_admin_headers,
            ),
            200,
        )
        assert data["technician_id"] == t2["id"]
        assert data["version"] == v1 + 1, "mutation visible in the same response"
        reread = get_shift(shift["id"])
        assert reread["technician_id"] == t2["id"]
        assert reread["version"] == data["version"], "no lag between write and read"
