"""Two reservation calendars with deliberately opposite endpoint semantics."""

from test_helpers import (
    ANALYST,
    TRADER,
    ApiErrorId,
    api_client,
    assert_commitment,
    assert_seller_scorecard,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestMandatoryDeliveryWindowReservation:
    """Mandatory lines reserve a half-open interval; best-efforts lines do not."""

    @staticmethod
    def _seller_holding_an_august_mandatory_line() -> dict:
        staged = fixtures.setup_lock_ready_seller()
        staged["base"] = fixtures.setup_commitment(
            staged["seller_id"],
            staged["product_id"],
            notional_amount_cents=40000000,
        )
        return staged

    @staticmethod
    def _lock(staged: dict, commitment_type: str, start: str, expiry: str):
        return api_client.create_commitment(
            factories.commitment_payload(
                staged["seller_id"],
                staged["product_id"],
                commitment_type=commitment_type,
                notional_amount_cents=40000000,
                delivery_window_start=start,
                delivery_expiry_date=expiry,
            ),
            TRADER,
        )

    def test_an_overlapping_mandatory_window_is_refused_but_a_touching_one_is_not(self):
        """One day of shared interval is fatal; sharing only the boundary is fine.

        The live line runs 2026-08-01 to 2026-08-31, so a second mandatory line
        starting 2026-08-15 genuinely shares half of August and is refused, while
        a line starting exactly on 2026-08-31 begins where the first has already
        stopped and locks without complaint.

        PRD: "A new `MANDATORY` lock's half-open window must not overlap the
        half-open window of any existing `MANDATORY` commitment of the **same
        seller and the same product** whose `status` is `LOCKED` or
        `PARTIALLY_FULFILLED`; an overlap is `ERR_DELIVERY_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/mandatory_delivery_windows_overlap_touching_allowed_best_efforts_exempt
        """
        staged = self._seller_holding_an_august_mandatory_line()

        validate_error(
            self._lock(staged, "MANDATORY", "2026-08-15", "2026-09-15"),
            ApiErrorId.ERR_DELIVERY_WINDOW_OVERLAP,
            409,
        )

        touching = validate_success(
            self._lock(staged, "MANDATORY", "2026-08-31", "2026-09-30"), 201
        )

        assert_commitment(touching)
        assert touching["status"] == "LOCKED"
        assert touching["commitment_type"] == "MANDATORY"
        assert touching["delivery_window_start"] == "2026-08-31"
        assert touching["delivery_expiry_date"] == "2026-09-30"

    def test_a_best_efforts_line_may_sit_on_the_rejected_dates(self):
        """The very dates a mandatory line was refused are open to best efforts.

        A best-efforts line on 2026-08-15 to 2026-09-15 locks even though a
        mandatory line on exactly those dates was refused, and it stays outside
        the exposure line, which counts only the two mandatory notionals.

        PRD: "`BEST_EFFORTS` commitments are exempt from this rule in both
        directions: a best-efforts lock never triggers it, and a best-efforts
        window never blocks a later mandatory lock."

        Design: Difficulty/resource_temporal_overlap/mandatory_delivery_windows_overlap_touching_allowed_best_efforts_exempt
        """
        staged = self._seller_holding_an_august_mandatory_line()
        validate_error(
            self._lock(staged, "MANDATORY", "2026-08-15", "2026-09-15"),
            ApiErrorId.ERR_DELIVERY_WINDOW_OVERLAP,
            409,
        )
        validate_success(self._lock(staged, "MANDATORY", "2026-08-31", "2026-09-30"), 201)

        best_efforts = validate_success(
            self._lock(staged, "BEST_EFFORTS", "2026-08-15", "2026-09-15"), 201
        )

        assert best_efforts["status"] == "LOCKED"
        assert best_efforts["commitment_type"] == "BEST_EFFORTS"
        assert best_efforts["delivery_window_start"] == "2026-08-15"

        seller = fixtures.read_seller(staged["seller_id"])
        assert seller["open_mandatory_exposure_cents"] == 80000000

        commitments, meta = validate_paginated(
            api_client.list_commitments(TRADER, {"seller_id": staged["seller_id"]})
        )
        assert meta["total_count"] == 3
        assert len(commitments) == 3


class TestScorecardPeriodReservation:
    """Scorecard periods are closed intervals, so endpoints collide."""

    @staticmethod
    def _seller_with_a_june_scorecard() -> dict:
        fixtures.setup_clock("2026-06-15T00:00:00Z")
        staged = fixtures.setup_approved_seller()
        staged["base"] = fixtures.open_scorecard(
            staged["seller_id"], "2026-06-01", "2026-06-30"
        )
        return staged

    def test_a_period_starting_on_the_previous_period_end_date_overlaps(self):
        """Sharing the single date 2026-06-30 is already an overlap.

        The existing period ends on 2026-06-30 inclusive, so a new period that
        starts on that same date collides on exactly one day and is refused, and
        the existing period is left as it was.

        PRD: "Because both ends are inclusive, two periods that merely share one
        endpoint date **do** overlap, and the second is refused with
        `ERR_SCORECARD_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/scorecard_periods_sharing_an_endpoint_date_overlap
        """
        staged = self._seller_with_a_june_scorecard()

        response = api_client.create_scorecard(
            staged["seller_id"],
            {"period_start": "2026-06-30", "period_end": "2026-07-31"},
            ANALYST,
        )

        validate_error(response, ApiErrorId.ERR_SCORECARD_PERIOD_OVERLAP, 409)

        scorecards, meta = validate_paginated(
            api_client.list_scorecards(staged["seller_id"], ANALYST)
        )
        assert meta["total_count"] == 1
        assert scorecards[0]["period_start"] == "2026-06-01"
        assert scorecards[0]["period_end"] == "2026-06-30"
        assert scorecards[0]["status"] == "OPEN"

    def test_a_period_starting_the_day_after_is_accepted_alongside_the_open_one(self):
        """Moving the start one day later removes the collision entirely.

        A July period that begins on 2026-07-01 shares no date with the June one
        and opens with every metric at zero, even though the June scorecard is
        still open rather than closed.

        PRD: "The new scorecard is created in `OPEN` status with every metric
        zeroed — `purchased_loan_count`, `purchased_upb_cents`,
        `defective_loan_count`, `defective_upb_cents`, `defect_rate_bps` and
        `upb_weighted_defect_rate_bps` — its `grade` at `UNRATED`, its `breach`
        flag false, its `standing_action_applied` at `NONE`, and `closed_at` null."

        Design: Difficulty/resource_temporal_overlap/scorecard_periods_sharing_an_endpoint_date_overlap
        """
        staged = self._seller_with_a_june_scorecard()
        validate_error(
            api_client.create_scorecard(
                staged["seller_id"],
                {"period_start": "2026-06-30", "period_end": "2026-07-31"},
                ANALYST,
            ),
            ApiErrorId.ERR_SCORECARD_PERIOD_OVERLAP,
            409,
        )

        july = validate_success(
            api_client.create_scorecard(
                staged["seller_id"],
                {"period_start": "2026-07-01", "period_end": "2026-07-31"},
                ANALYST,
            ),
            201,
        )

        assert_seller_scorecard(july)
        assert july["status"] == "OPEN"
        assert july["period_start"] == "2026-07-01"
        assert july["purchased_loan_count"] == 0
        assert july["grade"] == "UNRATED"
        assert july["standing_action_applied"] == "NONE"
        assert july["closed_at"] is None

        _, meta = validate_paginated(
            api_client.list_scorecards(staged["seller_id"], ANALYST)
        )
        assert meta["total_count"] == 2
