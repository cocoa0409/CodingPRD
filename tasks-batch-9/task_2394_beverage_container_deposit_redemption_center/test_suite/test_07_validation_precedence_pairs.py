"""Precedence when one request breaks two rules at once.

Each pair below is arranged so that two different checks are violated by the
same call; the ladder decides which error is reported, and the loser is
explicitly excluded.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import ADMIN_HEADERS, ApiErrorId
from test_helpers import factories as f
from test_helpers import fixtures as h

INSTANT = "2026-08-05T09:00:00Z"


class TestCentreStateBeatsDailyCap:
    """A suspended centre is reported as a state problem, not a cash problem."""

    @staticmethod
    def _suspended_centre_and_exhausted_holder(api):
        """Redeem the account's whole 300-container day, open a third visit, suspend."""
        world = h.build_world(
            api, center_overrides={"site_name": "Bend Redemption Center"}
        )
        h.create_counted_center_visit(
            api,
            world.center_id,
            world.machine_id,
            world.product_id,
            [240],
            world.account_id,
        )
        h.create_counted_center_visit(
            api,
            world.center_id,
            world.machine_id,
            world.product_id,
            [60],
            world.account_id,
        )
        third = h.open_center_machine_visit(
            api, world.center_id, world.machine_id, world.account_id
        )
        h.center_status_change(
            api,
            world.center_id,
            "SUSPEND",
            reason="counting floor closed for equipment inspection",
        )
        return world, third

    def test_lot_add_reports_the_centre_state_and_not_the_cap(self, api):
        """Both rules are broken; the centre-state rung is the lower one and wins.

        PRD: "The `RedemptionCenter` owning the addressed resource has `status`
        `OPERATIONAL` → otherwise `ERR_CENTER_NOT_OPERATIONAL` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/center_suspended_beats_daily_cap_exhausted
        """
        world, third = self._suspended_centre_and_exhausted_holder(api)

        response = api.create_container_lot(
            third["id"],
            f.create_lot_payload(
                world.product_id,
                20,
                third["version"],
                out_of_state_marked_quantity=0,
                contaminated_quantity=0,
            ),
            world.center_headers,
        )

        body = validate_error(
            response,
            ApiErrorId.ERR_CENTER_NOT_OPERATIONAL.value,
            expected_status=409,
        )
        assert body["error_id"] != ApiErrorId.ERR_DAILY_CAP_EXHAUSTED.value

    def test_the_losing_cap_rule_was_genuinely_violated_too(self, api):
        """The holder really had exhausted the day, and the refusal wrote nothing.

        PRD: "The visit's account has not already reached the applicable daily cap for the
        visit's `visit_date` — that is, `cap_reached_today` is false, or `redemption_day`
        names a different date → otherwise `ERR_DAILY_CAP_EXHAUSTED` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/center_suspended_beats_daily_cap_exhausted
        """
        world, third = self._suspended_centre_and_exhausted_holder(api)

        account = h.read_account(api, world.account_id, ADMIN_HEADERS)
        assert account["containers_redeemed_today"] == 300
        assert account["cap_reached_today"] is True

        response = api.create_container_lot(
            third["id"],
            f.create_lot_payload(world.product_id, 20, third["version"]),
            world.center_headers,
        )
        validate_error(response, ApiErrorId.ERR_CENTER_NOT_OPERATIONAL.value)

        center = h.read_center(api, world.center_id, world.center_headers)
        assert center["status"] == "SUSPENDED"

        stored = h.read_visit(api, third["id"], world.center_headers)
        assert stored["count_status"] == "OPEN"
        assert stored["presented_total"] == 0

        _, meta = validate_paginated(
            api.list_visit_lots(third["id"], world.center_headers)
        )
        assert meta["total_count"] == 0


class TestEnrolmentBeatsTagUniqueness:
    """An unenrolled holder is reported before the tag collision is noticed."""

    @staticmethod
    def _unenrolled_holder_and_a_taken_tag(api):
        h.set_clock(api, INSTANT)
        fleet = h.create_operational_center(
            api,
            {
                "site_name": "Bend Redemption Center",
                "daily_account_cap_containers": 300,
                "opening_cash_cents": 50000,
            },
        )
        center = fleet["center"]
        enrolled = h.create_account(api, bag_drop_enrolled=True)
        plain = h.create_account(
            api, holder_name="Priya Shah", account_code="ACCT-2002"
        )
        first_bag = h.create_bag_drop(
            api,
            enrolled["id"],
            center["id"],
            tag_code="BAG-9001",
            declared_count=120,
        )
        return center, plain, first_bag

    def test_bag_drop_reports_the_enrolment_rule_and_not_the_duplicate(self, api):
        """Enrolment sits at a lower rung than natural-key uniqueness.

        PRD: "The account's `bag_drop_enrolled` is true → otherwise
        `ERR_ACCOUNT_NOT_ENROLLED` (HTTP 422). Applies to bag-drop creation."

        Design: Difficulty/priority_pair_validation_conflict/account_not_enrolled_beats_duplicate_tag_code
        """
        center, plain, _ = self._unenrolled_holder_and_a_taken_tag(api)

        response = api.create_bag_drop(
            f.create_bag_drop_payload(
                plain["id"], center["id"], tag_code="BAG-9001", declared_count=120
            ),
            h.make_center_headers(center["id"]),
        )

        body = validate_error(
            response,
            ApiErrorId.ERR_ACCOUNT_NOT_ENROLLED.value,
            expected_status=422,
        )
        assert body["error_id"] != ApiErrorId.ERR_DUPLICATE_TAG_CODE.value

    def test_the_losing_tag_rule_was_genuinely_violated_too(self, api):
        """The tag really was taken, and the refusal left both holders untouched.

        PRD: "The submitted natural key is unused → otherwise the matching duplicate
        error: `ERR_DUPLICATE_PERMIT_NUMBER` for `permit_number`, `ERR_DUPLICATE_UPC` for
        `upc`, `ERR_DUPLICATE_ASSET_TAG` for `asset_tag`, `ERR_DUPLICATE_ACCOUNT_CODE` for
        `account_code`, `ERR_DUPLICATE_TAG_CODE` for `tag_code`, `ERR_DUPLICATE_BATCH_CODE`
        for `batch_code`, `ERR_DUPLICATE_QUARTER_CODE` for `quarter_code` (all HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/account_not_enrolled_beats_duplicate_tag_code
        """
        center, plain, first_bag = self._unenrolled_holder_and_a_taken_tag(api)
        center_headers = h.make_center_headers(center["id"])

        response = api.create_bag_drop(
            f.create_bag_drop_payload(
                plain["id"], center["id"], tag_code="BAG-9001", declared_count=120
            ),
            center_headers,
        )
        validate_error(response, ApiErrorId.ERR_ACCOUNT_NOT_ENROLLED.value)

        holder = h.read_account(api, plain["id"], ADMIN_HEADERS)
        assert holder["bag_drop_enrolled"] is False
        assert holder["credit_balance_cents"] == 0

        _, meta = validate_paginated(
            api.list_bag_drops(ADMIN_HEADERS, params={"account_id": plain["id"]})
        )
        assert meta["total_count"] == 0

        assert h.read_bag_drop(api, first_bag["id"], center_headers)["status"] == "DROPPED"


class TestOverlapBeatsQuarterCodeUniqueness:
    """Two quarters cannot share a date, and that is checked before the code."""

    @staticmethod
    def _stored_third_quarter(api):
        h.set_clock(api, INSTANT)
        return h.create_period(api, operating_cost_cents=1000)

    def test_period_creation_reports_the_overlap_and_not_the_duplicate(self, api):
        """The temporal rung is lower than the uniqueness rung, so overlap is reported.

        PRD: "The requested closed date interval shares no calendar date with any existing
        reporting quarter, whatever that quarter's `status` — `OPEN`, `RECONCILING` or
        `CLOSED` all block → otherwise `ERR_PERIOD_OVERLAP` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/period_overlap_beats_duplicate_quarter_code
        """
        self._stored_third_quarter(api)

        response = api.create_program_period(
            f.create_program_period_payload(
                quarter_code="2026Q3",
                start_date="2026-09-30",
                end_date="2026-12-31",
                operating_cost_cents=1000,
            ),
            ADMIN_HEADERS,
        )

        body = validate_error(
            response, ApiErrorId.ERR_PERIOD_OVERLAP.value, expected_status=409
        )
        assert body["error_id"] != ApiErrorId.ERR_DUPLICATE_QUARTER_CODE.value

    def test_the_losing_quarter_code_rule_was_genuinely_violated_too(self, api):
        """The code really was taken, and nothing new was stored.

        PRD: "`ERR_DUPLICATE_QUARTER_CODE` for `quarter_code` (all HTTP 409). Applies to
        distributor creation, label creation, machine installation, account creation,
        bag-drop creation, batch creation and quarter creation."

        Design: Difficulty/priority_pair_validation_conflict/period_overlap_beats_duplicate_quarter_code
        """
        stored = self._stored_third_quarter(api)
        assert stored["quarter_code"] == "2026Q3"

        response = api.create_program_period(
            f.create_program_period_payload(
                quarter_code="2026Q3",
                start_date="2026-09-30",
                end_date="2026-12-31",
                operating_cost_cents=1000,
            ),
            ADMIN_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_PERIOD_OVERLAP.value)

        _, meta = validate_paginated(api.list_program_periods(ADMIN_HEADERS))
        assert meta["total_count"] == 1

        kept = h.read_period(api, stored["id"])
        assert kept["status"] == "OPEN"
        assert kept["end_date"] == "2026-09-30"
