"""The bulk sweep, the logical clock, filtered listings and the error envelope."""

from typing import Any, Dict

import pytest
from test_helpers import (
    ADMIN_HEADERS,
    DECLARANT_HEADERS,
    DEFAULT_CLOCK_UTC,
    ERR_ASSOCIATION_NOT_FOUND,
    ERR_INVALID_REQUEST,
    NON_EXISTENT_UUID,
    ApiClient,
    assert_error_envelope_shape,
    assert_instant,
    assert_pagination_meta,
    association_payload,
    build_completed_component,
    do_deliver_item,
    do_repose_sweep,
    lot_payload,
    make_transition_committee_headers,
    seed_association,
    seed_component,
    seed_defect_claim,
    seed_records_item,
    seed_turnover_case,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def _plain_association(api: ApiClient, name: str, **overrides: Any) -> Dict[str, Any]:
    """A community with no money in either pool unless the caller says otherwise."""
    defaults: Dict[str, Any] = {
        "name": name,
        "total_planned_lots": 6,
        "turnover_threshold_pct": 66.67,
        "fixed_turnover_date": "2027-01-01T00:00:00Z",
        "statute_of_repose_years": 8,
        "reserve_pool_cents": 0,
        "reserve_claim_pool_cents": 0,
        "declarant_monthly_subsidy_cents": 0,
    }
    defaults.update(overrides)
    return seed_association(api, **defaults)


# ─── Netherfold: the repose sweep as a bulk conditional action ─────────


@pytest.fixture
def netherfold(api: ApiClient) -> Dict[str, Any]:
    """One component completed in 2016 and one in 2024, both against an 8-year repose."""
    association = _plain_association(api, "Netherfold", reserve_claim_pool_cents=900000)
    old_component = build_completed_component(
        api,
        association["id"],
        effective_date="2016-01-01T00:00:00Z",
        name="Old Bridge",
        category="INFRASTRUCTURE",
        replacement_cost_cents=500000,
        useful_life_years=30,
        effective_age_years=10,
        promised_completion_date="2016-01-01T00:00:00Z",
    )
    new_component = build_completed_component(
        api,
        association["id"],
        effective_date="2024-06-01T00:00:00Z",
        name="New Pavilion",
        category="AMENITY",
        replacement_cost_cents=300000,
        useful_life_years=20,
        effective_age_years=2,
        promised_completion_date="2024-06-01T00:00:00Z",
    )
    return {
        "association": association,
        "old_component": old_component,
        "new_component": new_component,
        "committee_headers": make_transition_committee_headers(association["id"]),
    }


def _open_two_claims(api: ApiClient, netherfold: Dict[str, Any]) -> Dict[str, Any]:
    """A claim against the time-expired component and one against the fresh one."""
    association_id = netherfold["association"]["id"]
    expired = seed_defect_claim(
        api,
        association_id,
        netherfold["old_component"]["id"],
        defect_summary="Bridge deck spalling",
        repair_cost_estimate_cents=300000,
        diminution_value_cents=200000,
    )
    fresh = seed_defect_claim(
        api,
        association_id,
        netherfold["new_component"]["id"],
        defect_summary="Pavilion roof leak",
        repair_cost_estimate_cents=100000,
        diminution_value_cents=60000,
    )
    return {"expired": expired, "fresh": fresh}


class TestReposeSweepReportsWhatItDid:
    """An empty sweep is a success, and a sweep bars only the expired claim."""

    def test_the_sweep_bars_only_the_claim_whose_deadline_has_run(
        self, api: ApiClient, netherfold: Dict[str, Any]
    ) -> None:
        """With no claims at all the sweep still answers with a zero count.

        "A committee-driven sweep over the association bars every claim whose
        `status` is still `INVESTIGATING` and whose `repose_deadline` is non-null
        and strictly earlier than the logical clock, moving each `INVESTIGATING →
        TIME_BARRED`, oldest first."

        Design: Corner/endpoints/repose_sweep_reports_only_claims_already_past_their_deadline
        """
        association_id = netherfold["association"]["id"]

        empty = do_repose_sweep(api, association_id)
        assert empty["swept_claim_count"] == 0
        assert empty["time_barred_claim_ids"] == []

        claims = _open_two_claims(api, netherfold)
        assert_instant(
            claims["expired"]["repose_deadline"],
            "2024-01-01T00:00:00Z",
            "repose_deadline",
        )
        assert_instant(
            claims["fresh"]["repose_deadline"],
            "2032-06-01T00:00:00Z",
            "repose_deadline",
        )

        swept = do_repose_sweep(api, association_id)
        assert swept["swept_claim_count"] == 1
        assert swept["time_barred_claim_ids"] == [claims["expired"]["id"]]

    def test_a_second_sweep_is_a_no_op_because_the_barred_claim_has_moved_on(
        self, api: ApiClient, netherfold: Dict[str, Any]
    ) -> None:
        """TIME_BARRED is not INVESTIGATING, so the same claim cannot be barred twice.

        "Claims with a null `repose_deadline` are never swept, and neither are
        claims in any other status. The sweep reports what it did:
        `swept_claim_count` as an integer and `time_barred_claim_ids` as the list
        of affected claim identifiers."

        Design: Corner/endpoints/repose_sweep_reports_only_claims_already_past_their_deadline
        """
        association_id = netherfold["association"]["id"]
        committee = netherfold["committee_headers"]
        claims = _open_two_claims(api, netherfold)

        do_repose_sweep(api, association_id)
        second = do_repose_sweep(api, association_id)
        assert second["swept_claim_count"] == 0
        assert second["time_barred_claim_ids"] == []

        expired = validate_success(
            api.get_defect_claim(claims["expired"]["id"], committee)
        )
        assert expired["status"] == "TIME_BARRED"
        fresh = validate_success(api.get_defect_claim(claims["fresh"]["id"], committee))
        assert fresh["status"] == "INVESTIGATING", (
            "A deadline in 2032 is not strictly earlier than the clock"
        )


# ─── Oakhanger: the logical clock is the only source of "now" ──────────


class TestLogicalClockDefaultAndMove:
    """Rows are stamped from the clock, and moving it touches nothing."""

    def test_rows_are_stamped_from_the_declared_default_then_from_the_new_instant(
        self, api: ApiClient
    ) -> None:
        """The set call echoes the instant it installed as current_utc.

        "Before any call is made to set it, that clock reads exactly
        `2026-08-01T00:00:00Z`, and it never falls back to real time. A
        `PlatformAdmin` may move it by supplying a `to_iso8601` instant; the
        response reports the new value as `current_utc`."

        Design: Corner/endpoints/logical_clock_starts_at_the_declared_default_and_set_current_utc_moves_it
        """
        association = _plain_association(api, "Oakhanger", total_planned_lots=4)
        case = seed_turnover_case(api, association["id"], total_seats=3)

        # §2.5 names ``delivered_at`` as one of the instants taken from the clock.
        before_item = seed_records_item(api, case["id"], "WARRANTIES")
        delivered_before = do_deliver_item(api, before_item["id"])
        assert_instant(
            delivered_before["delivered_at"], DEFAULT_CLOCK_UTC, "delivered_at"
        )

        moved = set_clock(api, "2026-09-15T12:00:00Z")
        assert_instant(moved["current_utc"], "2026-09-15T12:00:00Z", "current_utc")

        after_item = seed_records_item(api, case["id"], "PERMITS")
        delivered_after = do_deliver_item(api, after_item["id"])
        assert_instant(
            delivered_after["delivered_at"], "2026-09-15T12:00:00Z", "delivered_at"
        )

    def test_moving_the_clock_leaves_the_rows_written_before_it_untouched(
        self, api: ApiClient
    ) -> None:
        """The earlier row keeps its stamp and its version across the move.

        "Moving the clock performs no business transition, supersedes nothing,
        and touches no record."

        Design: Corner/endpoints/logical_clock_starts_at_the_declared_default_and_set_current_utc_moves_it
        """
        association = _plain_association(api, "Oakhanger", total_planned_lots=4)
        case = seed_turnover_case(api, association["id"], total_seats=3)
        item = seed_records_item(api, case["id"], "WARRANTIES")
        delivered = do_deliver_item(api, item["id"])

        set_clock(api, "2026-09-15T12:00:00Z")

        rows, _meta = validate_paginated(
            api.list_records_items(
                case["id"], make_transition_committee_headers(association["id"])
            )
        )
        reread = next(row for row in rows if row["id"] == item["id"])
        assert_instant(reread["delivered_at"], DEFAULT_CLOCK_UTC, "delivered_at")
        assert reread["version"] == delivered["version"], (
            "The clock move is not a mutation of the records item"
        )
        assert reread["updated_at"] == delivered["updated_at"], (
            "Moving the clock touches no record"
        )


# ─── Pellingford: two filters intersect before the page window ─────────


@pytest.fixture
def pellingford(api: ApiClient) -> Dict[str, Any]:
    """Five components: three unbuilt amenities, one complete amenity, one structure."""
    association = _plain_association(api, "Pellingford")
    unbuilt_amenities = [
        seed_component(
            api,
            association["id"],
            name=name,
            category="AMENITY",
            replacement_cost_cents=100000,
            useful_life_years=15,
            effective_age_years=0,
            promised_completion_date="2027-01-01T00:00:00Z",
        )
        for name in ("Pool", "Tennis Court", "Playground")
    ]
    complete_amenity = build_completed_component(
        api,
        association["id"],
        effective_date="2026-01-01T00:00:00Z",
        name="Gatehouse",
        category="AMENITY",
        replacement_cost_cents=100000,
        useful_life_years=15,
        effective_age_years=0,
        promised_completion_date="2026-01-01T00:00:00Z",
    )
    unbuilt_structure = seed_component(
        api,
        association["id"],
        name="Retaining Wall",
        category="STRUCTURE",
        replacement_cost_cents=100000,
        useful_life_years=25,
        effective_age_years=0,
        promised_completion_date="2027-01-01T00:00:00Z",
    )
    return {
        "association": association,
        "unbuilt_amenities": unbuilt_amenities,
        "complete_amenity": complete_amenity,
        "unbuilt_structure": unbuilt_structure,
        "committee_headers": make_transition_committee_headers(association["id"]),
    }


class TestComponentListingFiltersThenPaginates:
    """The filtered set is three rows, and the window is applied to that set."""

    def test_total_count_is_the_size_of_the_intersection_not_of_the_page(
        self, api: ApiClient, pellingford: Dict[str, Any]
    ) -> None:
        """Two pages of two cover the three unbuilt amenities exactly once each.

        "List responses report `limit`, `offset`, `total_count` and `has_more`
        inside the `meta` object of the envelope, where `total_count` is the size
        of the filtered set before the window is applied and `has_more` indicates
        whether records remain beyond it."

        Design: Corner/endpoints/component_listing_intersects_two_filters_before_paginating
        """
        association_id = pellingford["association"]["id"]
        committee = pellingford["committee_headers"]
        both_filters = {"category": "AMENITY", "build_status": "UNBUILT"}

        first_rows, first_meta = validate_paginated(
            api.list_components(
                association_id, committee, {**both_filters, "limit": 2, "offset": 0}
            )
        )
        assert_pagination_meta(
            first_meta,
            expected_total=3,
            expected_limit=2,
            expected_offset=0,
            expected_has_more=True,
        )
        assert len(first_rows) == 2

        second_rows, second_meta = validate_paginated(
            api.list_components(
                association_id, committee, {**both_filters, "limit": 2, "offset": 2}
            )
        )
        assert_pagination_meta(
            second_meta,
            expected_total=3,
            expected_limit=2,
            expected_offset=2,
            expected_has_more=False,
        )
        assert len(second_rows) == 1

        paged_ids = [row["id"] for row in first_rows + second_rows]
        assert len(set(paged_ids)) == 3, "The two pages must not repeat a row"
        assert set(paged_ids) == {
            component["id"] for component in pellingford["unbuilt_amenities"]
        }

    def test_dropping_the_filters_widens_the_set_and_an_unmatched_filter_empties_it(
        self, api: ApiClient, pellingford: Dict[str, Any]
    ) -> None:
        """All five rows fit inside the default page, and no component is conveyed.

        "`limit` caps the number of records returned; it defaults to 10 when
        omitted, may not be smaller than 1, and may not exceed 100."

        Design: Corner/endpoints/component_listing_intersects_two_filters_before_paginating
        """
        association_id = pellingford["association"]["id"]
        committee = pellingford["committee_headers"]

        all_rows, all_meta = validate_paginated(
            api.list_components(association_id, committee, {"limit": 10, "offset": 0})
        )
        assert_pagination_meta(
            all_meta,
            expected_total=5,
            expected_limit=10,
            expected_offset=0,
            expected_has_more=False,
        )
        listed_ids = {row["id"] for row in all_rows}
        assert pellingford["complete_amenity"]["id"] in listed_ids
        assert pellingford["unbuilt_structure"]["id"] in listed_ids

        conveyed_rows, conveyed_meta = validate_paginated(
            api.list_components(
                association_id,
                committee,
                {"conveyance_status": "CONVEYED", "limit": 10, "offset": 0},
            )
        )
        assert conveyed_meta["total_count"] == 0
        assert conveyed_rows == [], "An empty filtered set is a page, not a 404"


# ─── The error envelope is the success envelope's twin ─────────────────


class TestErrorEnvelopeShape:
    """error_id and message live inside data, and nowhere else."""

    def _assert_error_body(
        self, response: Any, expected_error_id: str
    ) -> Dict[str, Any]:
        validate_error(response, expected_error_id)
        body = response.json()
        assert_error_envelope_shape(body)
        assert set(body.keys()) == {"meta", "response_type", "data"}, (
            f"An error body carries exactly meta, response_type and data, got "
            f"{sorted(body.keys())}"
        )
        assert isinstance(body["data"]["message"], str)
        assert body["data"]["message"].strip() != "", (
            "The message provides a human-readable explanation of what went wrong"
        )
        return body

    def test_a_path_miss_a_shape_failure_and_a_body_key_miss_share_one_envelope(
        self, api: ApiClient
    ) -> None:
        """Three different rungs of the ladder produce the identical body shape.

        "The `meta` object for error responses contains only `api_request_id` and
        `api_request_timestamp`."

        Design: Corner/errors/error_responses_wrap_error_id_and_message_in_the_data_envelope
        """
        path_miss = self._assert_error_body(
            api.get_association(NON_EXISTENT_UUID, ADMIN_HEADERS),
            ERR_ASSOCIATION_NOT_FOUND,
        )
        shape_failure = self._assert_error_body(
            api.create_association(association_payload(name=None), ADMIN_HEADERS),
            ERR_INVALID_REQUEST,
        )
        body_key_miss = self._assert_error_body(
            api.create_lot(lot_payload(NON_EXISTENT_UUID, "X-1"), DECLARANT_HEADERS),
            ERR_ASSOCIATION_NOT_FOUND,
        )

        for body in (path_miss, shape_failure, body_key_miss):
            assert body["response_type"] == "error"
            assert "limit" not in body["meta"], (
                "No error response carries a pagination field"
            )
            assert "total_count" not in body["meta"]
