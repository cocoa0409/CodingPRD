"""Guards and derivation chains that reach past the resource a request names.

Two optimistic-concurrency guards are made to fire by holding a version the
system has already moved past, and the block-utilization axis is driven up to its
restriction threshold and then back down again by giving the rooms back.
"""

from test_helpers import (
    HOUSING_MANAGER_HEADERS,
    ApiErrorId,
    ReviewAction,
    factories as f,
    fixtures as fx,
    get_success_data,
    make_team_manager_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

HM = HOUSING_MANAGER_HEADERS


def _exempted_registration_env(api) -> fx.Env:
    """A registration whose `version` has moved on because a reviewer granted it
    a one-room exemption after the client first read it."""
    env = fx.registered_team_env(api)
    env.stale_registration = dict(env.registration)
    fx.add_exception_request(env)
    fx.review_exception(env, ReviewAction.START_REVIEW.value)
    fx.review_exception(env, ReviewAction.APPROVE.value, approved_rooms_exempt=1)
    return env


def _cleared_invoice_env(api) -> fx.Env:
    """An invoice whose `version` has moved on because the hotel remitted in full
    after the client first read it at `ISSUED`."""
    env = fx.issued_invoice_env(api)
    env.stale_invoice = dict(env.invoice)
    fx.remit(env, env.invoice["outstanding_cents"])
    return env


def _restricted_then_cancellable_env(api) -> fx.Env:
    """A ten-room block driven to `RESTRICTED` by two confirmed bookings, the
    larger of which is still cancellable by its own team."""
    env = fx.executed_contract_env(api, block_overrides={"block_size_rooms": 10})

    staying_team = fx.create_team(api, name="Riverside FC 16U")
    staying_registration = fx.add_registration(env, team=staying_team)
    staying_booking = fx.add_booking(
        env, registration=staying_registration, block=env.block, rooms_requested=4
    )
    fx.submit_rooming_list(env, booking=staying_booking, rooms=4)
    fx.confirm_booking(env, booking=staying_booking)

    leaving_team = fx.create_team(
        api, name="Lakeside SC 16U", org_contact_email="lakeside@example.com"
    )
    leaving_registration = fx.add_registration(env, team=leaving_team)
    leaving_booking = fx.add_booking(
        env, registration=leaving_registration, block=env.block, rooms_requested=5
    )
    fx.submit_rooming_list(
        env,
        booking=leaving_booking,
        entries=[
            f.rooming_list_entry(1, occupant_count=4),
            f.rooming_list_entry(2, occupant_count=4),
            f.rooming_list_entry(3, occupant_count=4),
            f.rooming_list_entry(4, occupant_count=3),
            f.rooming_list_entry(5, occupant_count=1),
        ],
    )
    fx.confirm_booking(env, booking=leaving_booking)

    env.leaving_team = leaving_team
    env.leaving_booking = leaving_booking
    return env


class TestStaleRegistrationVersionOnBookingCreate:
    """A booking must declare the registration version it actually saw."""

    def test_a_version_taken_before_the_exemption_was_granted_is_refused(self, api):
        """The client read the registration before a reviewer granted it a room,
        so its declared version is behind and no rooms are held.

        PRD §2.8: "If that value does not equal the registration's current
        `version`, the create is rejected with `ERR_STALE_REGISTRATION_VERSION` and
        HTTP 412."

        PRD §2.11: "`expected_registration_version` matches the registration's
        current `version` on booking creation — otherwise
        `ERR_STALE_REGISTRATION_VERSION`."

        PRD §3.6: "`APPROVE` moves it `UNDER_REVIEW → APPROVED`, requires the
        tournament to be `OPEN`, sets `approved_rooms_exempt` from the payload and
        `decided_by_user_id` to the acting `X-User-ID`, then recomputes the
        registration's `exempt_rooms_granted`, `effective_required_rooms` and
        `status` — which may move to `EXCEPTION_GRANTED` or to
        `HOUSING_COMPLIANT` — and refreshes the registration's `updated_at` and
        increments its `version` by 1."

        Design: Corner/cross_cutting_complexity_layers/stale_registration_version_rejected_on_booking_create
        """
        env = _exempted_registration_env(api)
        current = env.refresh_registration()
        assert current["exempt_rooms_granted"] == 1
        assert current["version"] > env.stale_registration["version"]

        response = api.create_booking(
            f.booking_payload(
                current["id"], env.block_id, env.stale_registration["version"]
            ),
            HM,
        )

        validate_error(
            response,
            ApiErrorId.ERR_STALE_REGISTRATION_VERSION.value,
            expected_status=412,
        )
        bookings, meta = validate_paginated(
            api.list_bookings(HM, {"registration_id": current["id"]})
        )
        assert meta["total_count"] == 0
        assert bookings == []

    def test_the_same_booking_with_the_refreshed_version_is_created(self, api):
        """Re-reading the registration and declaring its current version is all
        that changes, and the four-room hold is then created.

        PRD §2.8: "Successful booking creation itself increments the
        registration's `version` by 1, so a client holding a stale view learns of
        it deterministically."

        PRD §3.4: "A booking that clears all of that is created with
        `booking_status` `DRAFT` and `rebate_status` `NOT_DUE`."

        PRD §3.4: "The server computes `nights` as the whole days from
        `check_in_date` up to but not including `check_out_date`, and
        `projected_room_nights` as `rooms_requested` multiplied by `nights` — the
        pre-stay estimate that cancellation penalties are assessed against."

        Design: Corner/cross_cutting_complexity_layers/stale_registration_version_rejected_on_booking_create
        """
        env = _exempted_registration_env(api)
        current = env.refresh_registration()
        validate_error(
            api.create_booking(
                f.booking_payload(
                    current["id"], env.block_id, env.stale_registration["version"]
                ),
                HM,
            ),
            ApiErrorId.ERR_STALE_REGISTRATION_VERSION.value,
            expected_status=412,
        )

        response = api.create_booking(
            f.booking_payload(current["id"], env.block_id, current["version"]), HM
        )

        booking = validate_success(response, expected_status=201)
        assert booking["booking_status"] == "DRAFT"
        assert booking["rebate_status"] == "NOT_DUE"
        assert booking["rooms_requested"] == 4
        assert booking["projected_room_nights"] == 12
        assert env.refresh_registration()["version"] == current["version"] + 1


class TestStaleInvoiceVersionOnDistributionCreate:
    """A payout must declare the invoice version its split was computed from."""

    def test_a_version_taken_before_the_remittance_is_refused(self, api):
        """The client read the invoice while it was still unpaid, so its declared
        version predates the collection the split would draw on.

        PRD §2.8: "If that value does not equal the invoice's current `version`,
        the create is rejected with `ERR_STALE_INVOICE_VERSION` and HTTP 412."

        PRD §2.11: "`expected_invoice_version` matches the source invoice's
        current `version` on distribution creation — otherwise
        `ERR_STALE_INVOICE_VERSION`."

        PRD §3.8: "The first link sets `collected_cents` to `total_due_cents` and
        `outstanding_cents` to 0."

        Design: Corner/cross_cutting_complexity_layers/stale_invoice_version_rejected_on_distribution_create
        """
        env = _cleared_invoice_env(api)
        current = env.refresh_invoice()
        assert current["status"] == "PAID"
        assert current["collected_cents"] == 10800
        assert current["outstanding_cents"] == 0
        assert current["version"] > env.stale_invoice["version"]

        response = api.create_revenue_distribution(
            f.revenue_distribution_payload(
                env.tournament_id, current["id"], env.stale_invoice["version"]
            ),
            HM,
        )

        validate_error(
            response, ApiErrorId.ERR_STALE_INVOICE_VERSION.value, expected_status=412
        )
        distributions, meta = validate_paginated(
            api.list_revenue_distributions(HM, {"source_invoice_id": current["id"]})
        )
        assert meta["total_count"] == 0
        assert distributions == []

    def test_the_same_split_with_the_refreshed_version_runs_the_whole_waterfall(
        self, api
    ):
        """With the current version declared, the split runs: an eight percent
        admin fee off 10,800 cents leaves 9,936 to divide, and the single cent the
        truncations leave over goes to the organizer.

        PRD §2.8: "Successful distribution creation increments the invoice's
        `version` by 1."

        PRD §3.9: "Step one snapshots `gross_collected_cents` as the source
        invoice's `collected_cents` at that instant."

        PRD §3.9: "Step two selects `admin_fee_pct` from a three-tier table
        **keyed on `gross_collected_cents`**, never on the post-fee amount: below
        50,000 cents the fee is 0.08; from 50,000 cents up to but not including
        200,000 cents it is 0.06; at 200,000 cents or above it is 0.045."

        PRD §3.9: "Step three computes `admin_fee_cents` as
        `gross_collected_cents` multiplied by `admin_fee_pct`, rounded half up to a
        whole cent."

        PRD §3.9: "Step four computes `distributable_cents` as
        `gross_collected_cents` less `admin_fee_cents`."

        PRD §3.9: "Step six computes `rounding_remainder_cents` as
        `distributable_cents` less the three truncated allocations, and stores
        `organizer_cents` as the organizer's truncated allocation **plus that
        entire remainder**."

        PRD §3.9: "A new distribution opens at `status` `CALCULATED` with
        `approved_by_user_id` null."

        Design: Corner/cross_cutting_complexity_layers/stale_invoice_version_rejected_on_distribution_create
        """
        env = _cleared_invoice_env(api)
        current = env.refresh_invoice()
        validate_error(
            api.create_revenue_distribution(
                f.revenue_distribution_payload(
                    env.tournament_id, current["id"], env.stale_invoice["version"]
                ),
                HM,
            ),
            ApiErrorId.ERR_STALE_INVOICE_VERSION.value,
            expected_status=412,
        )

        response = api.create_revenue_distribution(
            f.revenue_distribution_payload(
                env.tournament_id, current["id"], current["version"]
            ),
            HM,
        )

        distribution = validate_success(response, expected_status=201)
        assert distribution["status"] == "CALCULATED"
        assert distribution["approved_by_user_id"] is None
        assert distribution["gross_collected_cents"] == 10800
        assert distribution["admin_fee_pct"] == 0.08
        assert distribution["admin_fee_cents"] == 864
        assert distribution["distributable_cents"] == 9936
        assert distribution["organizer_cents"] == 4969
        assert distribution["rights_holder_cents"] == 2980
        assert distribution["destination_cents"] == 1987
        assert distribution["rounding_remainder_cents"] == 1
        refreshed_invoice = env.refresh_invoice()
        assert refreshed_invoice["version"] == current["version"] + 1
        assert refreshed_invoice["distributed_cents"] == 10800


class TestRestrictionResetsWhenRoomsComeBack:
    """The utilization axis runs both ways, and so does everything above it."""

    def test_cancelling_the_five_room_booking_restores_the_blocks_counters(self, api):
        """Nine of ten rooms committed restricts the block; handing five of them
        back drops utilization to four tenths and reopens it.

        PRD §3.4: "The axis is cyclic in both directions: a confirmation can drive
        `OPEN → RESTRICTED`, and a later cancellation that drops utilization back
        below 0.90 drives `RESTRICTED → OPEN`."

        PRD §3.4: "`rooms_committed` is the **peak-night** committed occupancy over
        the block's own half-open window: for each night from `arrival_date` up to
        but not including `departure_date`, sum `rooms_requested` over the bookings
        on this block whose `booking_status` is `CONFIRMED` or `CHECKED_OUT` and
        whose own half-open stay covers that night, then take the maximum of those
        per-night sums across the whole window."

        PRD §2.12: "A confirmation followed by the cancellation of that same
        booking must restore `rooms_committed`, `rooms_available` and
        `utilization_pct` to the values they held before the confirmation; no drift
        is permitted across such a pair."

        Design: Corner/cross_cutting_complexity_layers/restriction_threshold_resets_when_rooms_are_given_back
        """
        env = _restricted_then_cancellable_env(api)
        restricted = env.refresh_block()
        assert restricted["rooms_committed"] == 9
        assert restricted["rooms_available"] == 1
        assert restricted["utilization_pct"] == 0.9
        assert restricted["status"] == "RESTRICTED"

        cancelled = validate_success(
            api.cancel_booking(
                env.leaving_booking["id"],
                f.cancel_payload(),
                make_team_manager_headers(env.leaving_team["id"]),
            ),
            expected_status=200,
        )

        assert cancelled["booking_status"] == "CANCELLED"
        assert cancelled["penalty_room_nights"] == 4
        assert cancelled["penalty_cents"] == 59600
        block = env.refresh_block()
        assert block["rooms_committed"] == 4
        assert block["rooms_available"] == 6
        assert block["utilization_pct"] == 0.4
        assert block["status"] == "OPEN"

    def test_the_contract_posture_and_the_events_pressure_relax_with_it(self, api):
        """The event was sold out because its only executed contract's only live
        block was restricted; reopening that block relieves both readings.

        PRD §3.5: "The block's `rooms_committed`, `rooms_available` and
        `utilization_pct` are recomputed, which may fire the `RESTRICTED → OPEN`
        flip and, through it, recompute the contract's `block_posture` and the
        tournament's `housing_pressure` — the confirm chain run in reverse from the
        block downstream."

        PRD §3.2: "If every live block is `RESTRICTED`, it is `SOLD_OUT`."

        PRD §3.2: "`housing_pressure` reads `CONSTRAINED` when
        `executed_contract_count` is at least 1 and `sold_out_contract_count`
        equals `executed_contract_count`; in every other case, including the case
        of no executed contracts at all, it reads `NORMAL`."

        Design: Corner/cross_cutting_complexity_layers/restriction_threshold_resets_when_rooms_are_given_back
        """
        env = _restricted_then_cancellable_env(api)
        assert env.refresh_contract()["block_posture"] == "SOLD_OUT"
        sold_out_tournament = env.refresh_tournament()
        assert sold_out_tournament["executed_contract_count"] == 1
        assert sold_out_tournament["sold_out_contract_count"] == 1
        assert sold_out_tournament["housing_pressure"] == "CONSTRAINED"

        get_success_data(
            api.cancel_booking(
                env.leaving_booking["id"],
                f.cancel_payload(),
                make_team_manager_headers(env.leaving_team["id"]),
            )
        )

        assert env.refresh_contract()["block_posture"] == "AVAILABLE"
        relaxed_tournament = env.refresh_tournament()
        assert relaxed_tournament["executed_contract_count"] == 1
        assert relaxed_tournament["sold_out_contract_count"] == 0
        assert relaxed_tournament["housing_pressure"] == "NORMAL"
