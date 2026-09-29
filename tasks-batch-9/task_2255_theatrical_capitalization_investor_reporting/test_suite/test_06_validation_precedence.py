"""
Requests rigged so that two different rules both have grounds to reject them.

Only the earlier rule in the global order may answer, and the later rule's code
must never appear — which is the whole point of pinning the order.
"""

from typing import List, Tuple

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import (
    COMPTROLLER2_HEADERS,
    COMPTROLLER_HEADERS,
    COUNSEL_HEADERS,
    GM_HEADERS,
    ApiClient,
    ApiErrorId,
    World,
    assert_no_write,
    factories,
    fixtures,
)


def _full_offering(
    api: ApiClient, investor_count: int
) -> Tuple[World, List[str], List[str]]:
    """An offering of 120,000,000 filled exactly by two units of 60,000,000."""
    world = fixtures.base_world(api)
    fixtures.open_offering(world)
    fixtures.with_effective_document(
        world,
        offering_amount_cents=120_000_000,
        unit_price_cents=60_000_000,
        max_investors=5,
    )
    investor_ids: List[str] = []
    subscription_ids: List[str] = []
    for index in range(investor_count):
        investor_id = fixtures.new_accredited_investor(
            world,
            legal_name=f"Investor {index + 1}",
            contact_email=f"investor{index + 1}@example.com",
        )
        investor_ids.append(investor_id)
        subscription_ids.append(fixtures.new_subscription(world, investor_id, units=1))
    fixtures.accept_subscription(world, subscription_ids[0])
    fixtures.accept_subscription(world, subscription_ids[1])
    return world, investor_ids, subscription_ids


class TestSubscriptionStateBeatsTheAmountCeiling:
    """Re-accepting an ACCEPTED subscription is a state fault, not a money fault."""

    def test_the_state_machine_answers_before_the_fiscal_gate(self, api: ApiClient):
        """The offering is exactly full, yet the second accept is refused on state.

        "**Own-state admissibility.** The target row is in a state from which the
        requested transition exists, else that machine's state error (409)."

        "The fiscal rules are the last gate a write passes, and they are
        evaluated among themselves in exactly this order:"

        Design: Difficulty/priority_pair_validation_conflict/subscription_state_precedes_oversubscription_fiscal_check
        """
        world, _, subscription_ids = _full_offering(api, 2)
        assert world.production()["capital_raised_cents"] == 120_000_000

        refused = api.accept_subscription(subscription_ids[0], COUNSEL_HEADERS)
        validate_error(refused, ApiErrorId.INVALID_SUBSCRIPTION_STATE)

    def test_the_refused_re_accept_does_not_double_count_the_units(
        self, api: ApiClient
    ):
        """The ledger, the accounts and the production version all stand still.

        "Counsel may accept only a subscription in `SUBMITTED`, only while its
        instrument reads `EFFECTIVE`, only while the subscribing investor reads
        `ACCREDITED`, and only within the instrument's date window."

        Design: Difficulty/priority_pair_validation_conflict/subscription_state_precedes_oversubscription_fiscal_check
        """
        world, investor_ids, subscription_ids = _full_offering(api, 2)
        before = world.production()

        validate_error(
            api.accept_subscription(subscription_ids[0], COUNSEL_HEADERS),
            ApiErrorId.INVALID_SUBSCRIPTION_STATE,
        )

        after = world.production()
        assert_no_write(before, after)
        assert after["capital_raised_cents"] == 120_000_000
        assert after["active_investor_count"] == 2

        rows, meta = validate_paginated(
            api.list_investor_accounts(
                COMPTROLLER_HEADERS, {"production_id": world.production_id}
            )
        )
        assert meta["total_count"] == 2
        for row in rows:
            assert row["ownership_pct"] == 0.500000
            assert row["units_total"] == 1
            assert row["investor_id"] in investor_ids


class TestAccreditationBeatsTheAmountCeiling:
    """A securities rule fires at step 11; the amount ceiling waits until step 14."""

    def _unaccredited_third_subscription(
        self, api: ApiClient
    ) -> Tuple[World, str, str]:
        world, investor_ids, subscription_ids = _full_offering(api, 3)
        third_investor_id = investor_ids[2]
        get_success_data(
            api.accredit_investor(
                third_investor_id,
                factories.accreditation_payload("NON_ACCREDITED"),
                COUNSEL_HEADERS,
            ),
            200,
        )
        return world, third_investor_id, subscription_ids[2]

    def test_the_securities_rule_answers_before_the_fiscal_gate(self, api: ApiClient):
        """A unit that is both unaccredited and over the amount reports accreditation.

        "**Securities compliance.** Accreditation, offering-instrument agreement,
        and the investor headcount ceiling, else `ERR_INVESTOR_NOT_ACCREDITED`,
        `ERR_OFFERING_TYPE_MISMATCH`, or `ERR_MAX_INVESTORS_EXCEEDED` (all 422)."

        "The fiscal rules are the last gate a write passes, and they are
        evaluated among themselves in exactly this order:"

        Design: Difficulty/priority_pair_validation_conflict/investor_accreditation_safety_precedes_oversubscription_fiscal
        """
        world, third_investor_id, third_subscription_id = (
            self._unaccredited_third_subscription(api)
        )
        assert world.production()["capital_raised_cents"] == 120_000_000

        refused = api.accept_subscription(third_subscription_id, COUNSEL_HEADERS)
        validate_error(refused, ApiErrorId.INVESTOR_NOT_ACCREDITED)
        assert (
            get_success_data(api.get_investor(third_investor_id, COUNSEL_HEADERS), 200)[
                "accreditation_status"
            ]
            == "NON_ACCREDITED"
        )

    def test_the_refused_unit_stays_submitted_and_raises_nothing(
        self, api: ApiClient
    ):
        """The withdrawn determination blocks acceptance without touching the raise.

        "Only an investor reading `ACCREDITED` may subscribe, and only one
        reading `ACCREDITED` may have a subscription accepted; a subscription
        created or accepted for anyone else is rejected with
        `ERR_INVESTOR_NOT_ACCREDITED` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/investor_accreditation_safety_precedes_oversubscription_fiscal
        """
        world, _, third_subscription_id = self._unaccredited_third_subscription(api)
        before = world.production()

        validate_error(
            api.accept_subscription(third_subscription_id, COUNSEL_HEADERS),
            ApiErrorId.INVESTOR_NOT_ACCREDITED,
        )

        assert (
            get_success_data(
                api.get_subscription(third_subscription_id, COUNSEL_HEADERS), 200
            )["status"]
            == "SUBMITTED"
        )
        after = world.production()
        assert_no_write(before, after)
        assert after["capital_raised_cents"] == 120_000_000
        assert after["active_investor_count"] == 2


class TestWrapWeekTemporalBeatsOccupancy:
    """A week that has not finished is a temporal fault before it is a collision."""

    def _rewound_running_world(self, api: ApiClient) -> World:
        world = fixtures.ledger_world(api, pool_basis=True)
        fixtures.with_submitted_standard_week(world)
        fixtures.certify_wrap(world, world.wrap_id or "")
        # Back before the certified week has finished, so a 2026-09-05 week is
        # both unfinished and fewer than seven days from 2026-09-06.
        world.set_clock("2026-09-04")
        return world

    def test_the_unfinished_week_reports_the_temporal_error(self, api: ApiClient):
        """2026-09-05 is in the future and collides, and the temporal rule answers.

        "**Temporal rules.** Offering window, wrap week, and notice period, else
        `ERR_OFFERING_EXPIRED`, `ERR_WRAP_WEEK_IN_FUTURE`,
        `ERR_NOTICE_DATE_IN_PAST`, or `ERR_INSUFFICIENT_CLOSING_NOTICE` (all
        422)."

        "**Occupancy and uniqueness.** House and performance-week collisions,
        single-notice and single-conversion constraints, else
        `ERR_THEATRE_ENGAGEMENT_OVERLAP`, `ERR_WRAP_WEEK_OVERLAP`,
        `ERR_CLOSING_NOTICE_ALREADY_ISSUED`, or `ERR_ROYALTY_BASIS_ALREADY_POOL`
        (all 409)."

        Design: Difficulty/priority_pair_validation_conflict/wrap_week_future_temporal_precedes_week_overlap_constraint
        """
        world = self._rewound_running_world(api)

        refused = api.create_weekly_wrap(
            factories.standard_week_payload(
                world.production_id,
                week_ending_date="2026-09-05",
                gross_receipts_cents=50_000_000,
                paid_attendance=6_000,
            ),
            GM_HEADERS,
        )
        validate_error(refused, ApiErrorId.WRAP_WEEK_IN_FUTURE)

    def test_the_refused_week_was_never_filed(self, api: ApiClient):
        """Only the certified week survives, and its settlement is untouched.

        "And the `week_ending_date` may not be later than the current logical UTC
        date; a week that has not finished yet cannot be wrapped, and the attempt
        is rejected with `ERR_WRAP_WEEK_IN_FUTURE` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/wrap_week_future_temporal_precedes_week_overlap_constraint
        """
        world = self._rewound_running_world(api)

        validate_error(
            api.create_weekly_wrap(
                factories.standard_week_payload(
                    world.production_id,
                    week_ending_date="2026-09-05",
                    gross_receipts_cents=50_000_000,
                    paid_attendance=6_000,
                ),
                GM_HEADERS,
            ),
            ApiErrorId.WRAP_WEEK_IN_FUTURE,
        )

        rows, meta = validate_paginated(
            api.list_weekly_wraps(GM_HEADERS, {"production_id": world.production_id})
        )
        assert meta["total_count"] == 1
        assert rows[0]["week_ending_date"] == "2026-09-06"
        assert rows[0]["status"] == "CERTIFIED"
        assert world.production()["recouped_amount_cents"] == 18_362_500


class TestStaleVersionBeatsTheDistributableCeiling:
    """The concurrency token is checked four steps before any money is compared."""

    def _recouped_world_with_a_stale_read(self, api: ApiClient) -> Tuple[World, int]:
        world = fixtures.ledger_world(
            api,
            capitalization_target_cents=18_362_500,
            unit_price_cents=18_362_500,
            pool_basis=True,
        )
        stale_version = world.production_version()
        fixtures.with_submitted_standard_week(world)
        fixtures.certify_wrap(world, world.wrap_id or "")
        return world, stale_version

    def test_the_concurrency_token_answers_before_the_fiscal_gate(
        self, api: ApiClient
    ):
        """An absurd amount quoted against a stale version reports the stale version.

        "The stale-version check itself is the tenth validation in the global
        order: it runs after role, path, body, referential, ownership,
        duty-segregation and state checks, and before the securities, temporal,
        occupancy and fiscal rules."

        Design: Difficulty/priority_pair_validation_conflict/stale_production_version_occ_precedes_distribution_fiscal_ceiling
        """
        world, stale_version = self._recouped_world_with_a_stale_read(api)
        assert world.production()["recoupment_status"] == "RECOUPED"

        refused = api.declare_investor_distribution(
            factories.distribution_payload(
                world.production_id,
                99_999_999_999,
                stale_version,
                "NET_PROFIT",
            ),
            COMPTROLLER2_HEADERS,
        )
        validate_error(refused, ApiErrorId.STALE_PRODUCTION_VERSION)
        assert world.production_version() > stale_version

    def test_the_refused_declaration_distributes_nothing(self, api: ApiClient):
        """No distribution row is filed and the distributable cash is untouched.

        "Declaring an investor distribution likewise requires
        `expected_production_version` carrying the client's last observed
        production `version`."

        Design: Difficulty/priority_pair_validation_conflict/stale_production_version_occ_precedes_distribution_fiscal_ceiling
        """
        world, stale_version = self._recouped_world_with_a_stale_read(api)
        before = world.production()

        validate_error(
            api.declare_investor_distribution(
                factories.distribution_payload(
                    world.production_id,
                    99_999_999_999,
                    stale_version,
                    "NET_PROFIT",
                ),
                COMPTROLLER2_HEADERS,
            ),
            ApiErrorId.STALE_PRODUCTION_VERSION,
        )

        _, meta = validate_paginated(
            api.list_investor_distributions(
                COMPTROLLER_HEADERS, {"production_id": world.production_id}
            )
        )
        assert meta["total_count"] == 0

        after = world.production()
        assert_no_write(before, after)
        assert after["distributed_total_cents"] == 0
        assert after["distributable_cash_cents"] == 18_362_500
        assert after["recoupment_status"] == "RECOUPED"
