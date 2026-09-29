"""The two optimistic-concurrency guards, and the promise that derived values never lag."""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import ApiErrorId
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    COMPLIANCE_REVIEWER_USER_ID,
    brand_lead_headers,
    community_manager_headers,
    media_buyer_headers,
)


def test_reusing_the_program_version_after_ones_own_reservation_is_a_precondition_failure(api):
    """PRD §2.7: "If that value does not match the program's current `version`, the reservation is
    rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412)."
    PRD §2.7: "Note that program funding edits, flight reservations, flight activations and releases,
    and event-presence confirmations and cancellations all advance `Program.version`, so any of them
    invalidates a previously fetched version number."
    PRD §2.6: "`committed_budget_cents` is the sum of `delta_cents` over every ledger entry of that
    program, and `available_budget_cents` is the sum of `pool_job_board_cents`, `pool_social_cents`,
    `pool_programmatic_cents`, `flex_reserve_cents` and the `dedicated_budget_cents` of every
    `JobFamily` belonging to that program, less `committed_budget_cents`."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_program_version_on_flight_create_returns_412
    """
    program = fx.create_program(api, pool_job_board_cents=1000000)
    family = fx.create_job_family(api, program["id"])
    channel = fx.create_channel(api, program["id"])
    posting = fx.create_posting(api, family["id"])
    stale_version = fx.program_version(api, program["id"])

    first = fx.reserve_flight(
        api,
        channel["id"],
        family["id"],
        posting["id"],
        stale_version,
        start_date="2026-08-05",
        end_date="2026-08-10",
        daily_cap_cents=50000,
    )
    fresh_version = fx.program_version(api, program["id"])
    on_a_stale_read = api.create_media_flight(
        f.flight_payload(
            channel["id"],
            family["id"],
            posting["id"],
            stale_version,
            start_date="2026-08-12",
            end_date="2026-08-17",
            daily_cap_cents=50000,
        ),
        media_buyer_headers(),
    )
    after_the_refusal = fx.read_program(api, program["id"])
    retried = api.create_media_flight(
        f.flight_payload(
            channel["id"],
            family["id"],
            posting["id"],
            fresh_version,
            start_date="2026-08-12",
            end_date="2026-08-17",
            daily_cap_cents=50000,
        ),
        media_buyer_headers(),
    )

    a.assert_cents(first["total_cost_cents"], 257500, "total_cost_cents")
    assert fresh_version == stale_version + 1, (stale_version, fresh_version)
    validate_error(on_a_stale_read, ApiErrorId.STALE_PROGRAM_VERSION, 412)
    assert after_the_refusal["version"] == fresh_version, after_the_refusal
    a.assert_program_budget(
        after_the_refusal, committed_budget_cents=257500, available_budget_cents=742500
    )
    second = validate_success(retried, 201)
    a.assert_cents(second["total_cost_cents"], 257500, "total_cost_cents")
    settled = fx.read_program(api, program["id"])
    assert settled["version"] == fresh_version + 1, settled
    a.assert_program_budget(
        settled, committed_budget_cents=515000, available_budget_cents=485000
    )
    entries = fx.list_ledger_entries(api, program_id=program["id"])
    assert [entry["entry_type"] for entry in entries] == ["RESERVE", "RESERVE"], entries
    assert sorted(entry["source_id"] for entry in entries) == sorted(
        [first["id"], second["id"]]
    ), entries


def test_replaying_the_creation_version_on_a_second_optimize_is_a_precondition_failure(api):
    """PRD §2.7: "If that value does not match the posting's current `version`, the optimization is
    rejected with `ERR_STALE_POSTING_VERSION` (HTTP 412)."
    PRD §3.4: "It also has a compliance consequence that is easy to miss: if the posting's
    `compliance_status` was `CLEARED`, it is reset to `UNREVIEWED` and `cleared_by_user_id` is set
    back to null, because the text a reviewer cleared has just been superseded."
    PRD §3.4: "The benefits component contributes 5 points for each benefit bullet, counting at most
    five bullets, so it saturates at 25 points."
    PRD §3.4: "`optimization_score` is the sum of the five, it stays 0 until the first optimization
    revision runs, and publication requires it to be at least 70 — a score of exactly 70 publishes."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_posting_version_on_optimize_returns_412
    """
    program = fx.create_program(api)
    family = fx.create_job_family(api, program["id"])
    posting = fx.create_posting(api, family["id"])
    first_version = posting["version"]
    optimized = fx.optimize_posting(api, posting["id"], first_version)
    cleared = fx.clear_posting(api, posting["id"], user_id=COMPLIANCE_REVIEWER_USER_ID)

    replayed = api.optimize_job_posting(
        posting["id"],
        f.optimize_payload(first_version, benefit_count=2),
        brand_lead_headers(),
    )
    after_the_refusal = fx.read_posting(api, posting["id"])
    accepted = api.optimize_job_posting(
        posting["id"],
        f.optimize_payload(cleared["version"], benefit_count=2),
        brand_lead_headers(),
    )

    assert optimized["optimization_score"] == 100, optimized
    assert cleared["compliance_status"] == "CLEARED", cleared
    validate_error(replayed, ApiErrorId.STALE_POSTING_VERSION, 412)
    assert after_the_refusal["version"] == cleared["version"], after_the_refusal
    assert after_the_refusal["benefit_count"] == 5, after_the_refusal
    assert after_the_refusal["optimization_score"] == 100, after_the_refusal
    assert after_the_refusal["compliance_status"] == "CLEARED", after_the_refusal
    revised = validate_success(accepted, 200)
    assert revised["version"] == cleared["version"] + 1, revised
    assert revised["benefit_count"] == 2, revised
    assert revised["optimization_score"] == 85, revised
    assert revised["compliance_status"] == "UNREVIEWED", revised
    assert revised["cleared_by_user_id"] is None, revised


def test_the_brand_health_score_already_reflects_a_review_on_the_next_read(api):
    """PRD §3.8: "Ingesting a review immediately recomputes the program's `brand_health_score`."
    PRD §2.10: "There is no deferred queue and no eventual reconciliation."
    PRD §3.8: "So a one-star review posted yesterday costs 5 points, the same review 45 days old
    costs 2.5 points, and the same review 75 days old costs 1.25 points, while a three-star review
    costs nothing at all."
    PRD §3.8: "`response_due_at` is `posted_at` plus that many hours, recorded as an exact ISO 8601
    instant with three fractional digits."

    Design: Corner/consistency_model/derived_program_health_is_visible_in_the_same_request_that_creates_a_review
    """
    program = fx.create_program(api)
    version_before = program["version"]

    review = fx.ingest_review(
        api,
        program["id"],
        platform="GLASSDOOR",
        external_ref="gd-immediate",
        rating=1,
        posted_at="2026-07-31T00:00:00Z",
    )
    first_read = validate_success(
        api.get_program(program["id"], community_manager_headers()), 200
    )
    second_read = validate_success(
        api.get_program(program["id"], community_manager_headers()), 200
    )

    assert float(program["brand_health_score"]) == 100.00, program
    assert review["response_due_at"] == "2026-08-01T00:00:00.000Z", review
    assert review["sla_status"] == "PENDING", review
    assert float(first_read["brand_health_score"]) == 95.00, first_read
    assert first_read["version"] == version_before + 1, first_read
    assert second_read["brand_health_score"] == first_read["brand_health_score"], second_read
    assert second_read["version"] == first_read["version"], second_read
