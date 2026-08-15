"""Queue A difficulty tests: resource temporal overlap and single-occupancy rules."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_fiduciary_reviewer_headers,
    create_active_recordkeeper,
    create_plan,
    create_participant,
    create_open_batch,
    setup_reconciled_batch,
)

OPS = TEST_USERS["provider_ops_headers"]
SPONSOR = TEST_USERS["plan_sponsor_headers"]


class TestReviewPeriodHalfOpenOverlap:
    def _setup_reconciled_with_review(self):
        """Batch RECONCILED with an existing review R1 covering [08-01, 09-01)."""
        ctx = setup_reconciled_batch()
        r1 = get_success_data(api_client.create_fiduciary_review(
            {"distribution_batch_id": ctx["batch"]["id"],
             "period_start": "2026-08-01T00:00:00Z",
             "period_end": "2026-09-01T00:00:00Z"},
            make_fiduciary_reviewer_headers("fid_rev_1"),
        ))
        ctx["r1"] = r1
        return ctx

    def test_interior_overlap_rejected(self):
        """PRD §3.9: "the window must not intersect any existing non-`CLOSED` review of the
        same plan under half-open semantics — one review's `period_end` equal to another's
        `period_start` is adjacency, not overlap, and is allowed, while a true intersection
        is rejected with `ERR_REVIEW_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/review_period_half_open_overlap
        """
        ctx = self._setup_reconciled_with_review()
        # [08-15, 09-15) intersects [08-01, 09-01) in its interior.
        res = api_client.create_fiduciary_review(
            {"distribution_batch_id": ctx["batch"]["id"],
             "period_start": "2026-08-15T00:00:00Z",
             "period_end": "2026-09-15T00:00:00Z"},
            make_fiduciary_reviewer_headers("fid_rev_1"),
        )
        validate_error(res, ApiErrorId.ERR_REVIEW_PERIOD_OVERLAP, 409)

    def test_adjacent_period_accepted(self):
        """PRD §3.9: "one review's `period_end` equal to another's `period_start` is
        adjacency, not overlap, and is allowed"

        Design: Difficulty/resource_temporal_overlap/review_period_half_open_overlap
        """
        ctx = self._setup_reconciled_with_review()
        # Adjacent [09-01, 10-01): end == start, not an intersection under half-open.
        r2 = validate_success(api_client.create_fiduciary_review(
            {"distribution_batch_id": ctx["batch"]["id"],
             "period_start": "2026-09-01T00:00:00Z",
             "period_end": "2026-10-01T00:00:00Z"},
            make_fiduciary_reviewer_headers("fid_rev_1"),
        ), 201)
        assert r2["review_status"] == "OPEN"


class TestOpenBatchSingleOccupancy:
    def test_duplicate_batch_while_open_rejected(self):
        """PRD §3.3: "a plan may have at most one batch in flight at a time: opening a
        second batch while one exists in `OPEN`, `LOCKED`, `EXECUTED`, or
        `RECON_EXCEPTION` is rejected with `ERR_DUPLICATE_OPEN_BATCH`."

        Design: Difficulty/resource_temporal_overlap/open_batch_single_occupancy
        """
        rk = create_active_recordkeeper()
        plan = create_plan(rk["id"])
        create_open_batch(plan["id"])
        res = api_client.create_distribution_batch({"plan_id": plan["id"]}, SPONSOR)
        validate_error(res, ApiErrorId.ERR_DUPLICATE_OPEN_BATCH, 409)

    def test_occupancy_spans_locked_and_releases_after_reviewed(self):
        """PRD §3.3: "opening a second batch while one exists in `OPEN`, `LOCKED`,
        `EXECUTED`, or `RECON_EXCEPTION` is rejected with `ERR_DUPLICATE_OPEN_BATCH`."
        PRD §3.9: "Attestation is permitted only from `OPEN` — no unremediated findings —
        and stamps `attested_at`, closes the review (`CLOSED`), and in the same stroke
        moves the reviewed batch from `RECONCILED` to `REVIEWED`, its terminal state."

        Design: Difficulty/resource_temporal_overlap/open_batch_single_occupancy
        """
        ctx = setup_reconciled_batch()
        plan_id = ctx["plan"]["id"]
        # RECONCILED still occupies (it is not yet REVIEWED — occupancy set listed
        # above covers OPEN/LOCKED/EXECUTED/RECON_EXCEPTION; assert the listed states
        # are blocked via a LOCKED probe on a fresh plan below).
        rk2 = create_active_recordkeeper(code="RK-Z", legal_name="Recordkeeper Z")
        plan2 = create_plan(rk2["id"], plan_name="Plan Z", sponsor_ein="99-9999999")
        b2 = create_open_batch(plan2["id"])
        p2 = create_participant(ssn_hash="hash-z", full_name="Zed Z")
        from test_helpers import create_case
        create_case(b2["id"], plan2["id"], p2["id"],
                    separation_date_balance_cents=50000,
                    processing_date_balance_cents=50000)
        get_success_data(api_client.lock_distribution_batch(b2["id"], SPONSOR))
        # While LOCKED: duplicate rejected.
        res = api_client.create_distribution_batch({"plan_id": plan2["id"]}, SPONSOR)
        validate_error(res, ApiErrorId.ERR_DUPLICATE_OPEN_BATCH, 409)

        # After the first plan's batch is attested (REVIEWED), a new batch opens.
        review = get_success_data(api_client.create_fiduciary_review(
            {"distribution_batch_id": ctx["batch"]["id"],
             "period_start": "2026-08-01T00:00:00Z",
             "period_end": "2026-09-01T00:00:00Z"},
            make_fiduciary_reviewer_headers("fid_rev_1"),
        ))
        get_success_data(api_client.attest_review(
            review["id"], make_fiduciary_reviewer_headers("fid_rev_1")))
        batch = get_success_data(
            api_client.get_distribution_batch(ctx["batch"]["id"], OPS))
        assert batch["batch_status"] == "REVIEWED"
        new_batch = validate_success(api_client.create_distribution_batch(
            {"plan_id": plan_id}, SPONSOR), 201)
        assert new_batch["batch_status"] == "OPEN"
