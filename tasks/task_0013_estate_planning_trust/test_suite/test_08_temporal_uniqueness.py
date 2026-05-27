"""Resource temporal-overlap conflicts.

POA half-open interval semantics vs Guardianship point-uniqueness — different
interval geometry on different entity types.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    set_clock,
    ApiErrorId,
    bootstrap_decedent_with_two_active_poas,
    bootstrap_estate_with_guardianship,
    create_decedent,
    create_estate,
    create_guardianship,
    create_poa,
    activate_poa,
    make_planner_headers,
)


class TestPoaHalfOpenIntervalSemantics:
    """PRD §3.4: half-open intervals [effective_at, effective_until); adjacency
    at boundary T does NOT overlap; true overlap with an existing ACTIVE POA
    on the same decedent/scope is rejected."""

    def test_adjacent_at_boundary_allowed_then_overlap_rejected(self, api):
        """PRD §3.4: "The interval semantics are half-open: an interval that
        ends at instant T does not collide with another interval that starts
        at T. On activation, the new interval [effective_at, effective_until)
        must not overlap any existing ACTIVE POA on the same decedent_id
        whose scope is identical; an overlap is rejected with
        ERR_POA_INTERVAL_OVERLAP."

        Design: Difficulty/resource_temporal_overlap/poa_half_open_interval_overlap_same_scope
        """
        ctx = bootstrap_decedent_with_two_active_poas(
            clock="2026-01-01T00:00:00Z",
            poa_a_start="2026-01-01T00:00:00Z",
            poa_a_end="2026-03-01T00:00:00Z",
            poa_scope="FINANCIAL",
        )
        # POA-B abuts POA-A's end: [2026-03-01, +inf). Half-open so no overlap.
        resp_b = api.activate_poa(
            ctx["poa_b"]["id"],
            {"effective_at": "2026-03-01T00:00:00Z"},
            make_planner_headers(),
        )
        d_b = validate_success(resp_b, expected_status=200)
        assert d_b["status"] == "ACTIVE", (
            f"POA-B abutting at boundary T should activate without overlap, "
            f"got {d_b['status']!r}"
        )

    def test_overlap_inside_a_existing_interval_rejected(self, api):
        """PRD §3.4: "the new interval [effective_at, effective_until) must
        not overlap any existing ACTIVE POA on the same decedent_id whose
        scope is identical; an overlap is rejected with
        ERR_POA_INTERVAL_OVERLAP."

        Design: Difficulty/resource_temporal_overlap/poa_half_open_interval_overlap_same_scope
        """
        ctx = bootstrap_decedent_with_two_active_poas(
            clock="2026-01-01T00:00:00Z",
            poa_a_start="2026-01-01T00:00:00Z",
            poa_a_end="2026-03-01T00:00:00Z",
            poa_scope="FINANCIAL",
        )
        # POA-C starts inside POA-A's interval (overlap).
        resp_c = api.activate_poa(
            ctx["poa_c"]["id"],
            {"effective_at": "2026-02-15T00:00:00Z"},
            make_planner_headers(),
        )
        validate_error(resp_c, ApiErrorId.ERR_POA_INTERVAL_OVERLAP)


class TestGuardianshipPointUniqueness:
    """PRD §3.3: two Guardianship rows on the same estate may not share the
    same ward_full_name — point-uniqueness regardless of status."""

    def test_duplicate_ward_on_same_estate_rejected(self, api):
        """PRD §3.3: "Within a single estate, two guardianship rows may not
        share the same ward_full_name regardless of their respective statuses
        — even a DISSOLVED row still consumes that name slot as a
        point-uniqueness audit-trail block; a duplicate is rejected with
        ERR_DUPLICATE_WARD."

        Design: Difficulty/resource_temporal_overlap/guardianship_point_uniqueness_no_adjacency_relief
        """
        ctx = bootstrap_estate_with_guardianship(
            ward_full_name="Junior Wei",
            ward_date_of_birth="2020-06-06T00:00:00Z",
        )
        # Same ward_full_name on same estate → ERR_DUPLICATE_WARD.
        resp = api.create_guardianship(
            {
                "estate_id": ctx["estate"]["id"],
                "ward_full_name": "Junior Wei",
                "ward_date_of_birth": "2020-06-06T00:00:00Z",
                "guardian_full_name": "Auntie B",
            },
            make_planner_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_WARD)

    def test_distinct_ward_names_on_same_estate_allowed(self, api):
        """PRD §3.3: "Within a single estate, two guardianship rows may not
        share the same ward_full_name regardless of their respective statuses
        — even a DISSOLVED row still consumes that name slot as a
        point-uniqueness audit-trail block; a duplicate is rejected with
        ERR_DUPLICATE_WARD."

        Design: Difficulty/resource_temporal_overlap/guardianship_point_uniqueness_no_adjacency_relief
        """
        ctx = bootstrap_estate_with_guardianship(
            ward_full_name="Junior Wei",
            ward_date_of_birth="2020-06-06T00:00:00Z",
        )
        # Distinct ward_full_name on same estate should be allowed.
        resp = api.create_guardianship(
            {
                "estate_id": ctx["estate"]["id"],
                "ward_full_name": "Distinct Ward",
                "ward_date_of_birth": "2019-04-04T00:00:00Z",
                "guardian_full_name": "Auntie C",
            },
            make_planner_headers(),
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "PROPOSED"
