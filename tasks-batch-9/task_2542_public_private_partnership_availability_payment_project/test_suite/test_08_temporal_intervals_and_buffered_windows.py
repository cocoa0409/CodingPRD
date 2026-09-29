"""Interval arithmetic: half-open payment periods and closed, buffered relief windows."""
from test_helpers import api_client, validate_error, validate_success
from test_helpers.factories import create_relief_claim_payload, create_service_period_payload
from test_helpers.fixtures import (
    ALPHA,
    set_clock,
    setup_concession_in_operations,
    setup_notified_relief_claim,
)


def _relief_claim_totals(concession_id, **params):
    query = {"concession_id": concession_id}
    query.update(params)
    body = api_client.list_relief_claims(ALPHA, params=query).json()
    return body["data"], body["meta"]


class TestServicePeriodHalfOpenAdjacency:
    def test_a_period_starting_on_the_previous_periods_end_date_is_accepted(self):
        """March and April touch at 2027-04-01, which the half-open rule permits.

        PRD: "The interval must not intersect any existing period of the same
        concession, failing which it is `ERR_SERVICE_PERIOD_OVERLAP` (HTTP 409);
        adjacency is explicitly permitted, so a period beginning exactly at the
        previous period's `period_end` does not intersect it and is accepted."

        Design: Difficulty/resource_temporal_overlap/service_period_half_open_intervals_allow_exact_adjacency
        """
        ctx = setup_concession_in_operations()

        first = validate_success(
            api_client.create_service_period(
                ctx["concession_id"],
                create_service_period_payload(1, "2027-03-01", "2027-04-01"),
                ALPHA,
            ),
            201,
        )
        second = validate_success(
            api_client.create_service_period(
                ctx["concession_id"],
                create_service_period_payload(2, "2027-04-01", "2027-05-01"),
                ALPHA,
            ),
            201,
        )

        assert first["days_in_period"] == 31
        assert second["days_in_period"] == 30
        for period in (first, second):
            assert period["gross_unitary_charge_cents"] == 8604167
            assert period["deduction_cap_cents"] == 1720833
        body = api_client.list_service_periods(
            ALPHA, params={"concession_id": ctx["concession_id"]}
        ).json()
        assert body["meta"]["total_count"] == 2

    def test_a_period_straddling_the_shared_boundary_is_refused_as_an_overlap(self):
        """2027-03-31 to 2027-04-30 genuinely intersects both existing periods.

        PRD: "A service period's interval is **half-open**: `period_start` is
        inclusive, `period_end` is exclusive, and `days_in_period` is the whole-day
        span of that half-open interval."

        Design: Difficulty/resource_temporal_overlap/service_period_half_open_intervals_allow_exact_adjacency
        """
        ctx = setup_concession_in_operations()
        validate_success(
            api_client.create_service_period(
                ctx["concession_id"],
                create_service_period_payload(1, "2027-03-01", "2027-04-01"),
                ALPHA,
            ),
            201,
        )
        validate_success(
            api_client.create_service_period(
                ctx["concession_id"],
                create_service_period_payload(2, "2027-04-01", "2027-05-01"),
                ALPHA,
            ),
            201,
        )

        response = api_client.create_service_period(
            ctx["concession_id"],
            create_service_period_payload(3, "2027-03-31", "2027-04-30"),
            ALPHA,
        )

        validate_error(response, "ERR_SERVICE_PERIOD_OVERLAP", 409)
        body = api_client.list_service_periods(
            ALPHA, params={"concession_id": ctx["concession_id"]}
        ).json()
        assert body["meta"]["total_count"] == 2


class TestReliefClaimBufferedWindows:
    def test_five_clear_days_between_two_claims_of_one_type_is_a_conflict(self):
        """A closes on 2027-02-10 and B opens on 2027-02-16: the buffers touch.

        PRD: "In practice this means two claims of the same type need at least six
        clear calendar days between the earlier window's end and the later window's
        start: five clear days conflicts, six does not."

        Design: Difficulty/resource_temporal_overlap/relief_claim_closed_windows_are_buffered_three_days_on_each_side_per_claim_type
        """
        ctx = setup_notified_relief_claim()
        set_clock("2027-02-18T00:00:00Z")

        response = api_client.create_relief_claim(
            ctx["concession_id"],
            create_relief_claim_payload(
                "RELIEF_EVENT", "2027-02-16", "2027-02-20", 5, 200000
            ),
            ctx["cnr_headers"],
        )

        validate_error(response, "ERR_RELIEF_WINDOW_CONFLICT", 409)
        _, meta = _relief_claim_totals(ctx["concession_id"])
        assert meta["total_count"] == 1

    def test_six_clear_days_is_accepted_and_a_different_type_never_conflicts(self):
        """One claim clears the buffer by a day; another of a different type ignores it.

        PRD: "Claims of different types never conflict with each other, and a claim
        that has been `REJECTED` releases its window entirely."

        Design: Difficulty/resource_temporal_overlap/relief_claim_closed_windows_are_buffered_three_days_on_each_side_per_claim_type
        """
        ctx = setup_notified_relief_claim()
        set_clock("2027-02-18T00:00:00Z")

        clear_of_the_buffer = validate_success(
            api_client.create_relief_claim(
                ctx["concession_id"],
                create_relief_claim_payload(
                    "RELIEF_EVENT", "2027-02-17", "2027-02-21", 5, 200000
                ),
                ctx["cnr_headers"],
            ),
            201,
        )
        other_type = validate_success(
            api_client.create_relief_claim(
                ctx["concession_id"],
                create_relief_claim_payload(
                    "COMPENSATION_EVENT", "2027-02-16", "2027-02-20", 5, 200000
                ),
                ctx["cnr_headers"],
            ),
            201,
        )

        assert clear_of_the_buffer["status"] == "NOTIFIED"
        assert other_type["status"] == "NOTIFIED"
        assert clear_of_the_buffer["granted_relief_days"] == 0
        assert other_type["granted_relief_days"] == 0
        rows, meta = _relief_claim_totals(ctx["concession_id"])
        assert meta["total_count"] == 3
        assert all(row["status"] == "NOTIFIED" for row in rows)
        _, relief_meta = _relief_claim_totals(
            ctx["concession_id"], claim_type="RELIEF_EVENT"
        )
        assert relief_meta["total_count"] == 2
