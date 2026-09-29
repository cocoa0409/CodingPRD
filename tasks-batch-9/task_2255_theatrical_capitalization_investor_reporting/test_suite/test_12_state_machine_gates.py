"""
One admissible hop and one inadmissible hop per state machine in the system.

Each machine is walked into the state the transition is declared from, and then
pushed at a transition that does not exist from where it stands.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import (
    COMPTROLLER_HEADERS,
    COUNSEL_HEADERS,
    GM_HEADERS,
    PRODUCER_HEADERS,
    PRODUCER_USER_ID,
    ApiClient,
    ApiErrorId,
    assert_no_write,
    factories,
    fixtures,
    make_investor_headers,
)


class TestOfferingDocumentMachine:
    """DRAFT to EFFECTIVE is the one hop the offering axis has to be open for."""

    def test_making_a_draft_instrument_effective_zeroes_its_accepted_totals(
        self, api: ApiClient
    ):
        """The instrument is live with nothing accepted under it yet.

        "The document must be in `DRAFT` — any other status reports
        `ERR_INVALID_OFFERING_DOCUMENT_STATE` (HTTP 409). The production's
        syndication axis must read `OFFERING`, else
        `ERR_PRODUCTION_NOT_OFFERING` (HTTP 409)."

        Design: Corner/state_machines/offering_document_make_effective_valid_transition
        """
        world = fixtures.base_world(api)
        fixtures.open_offering(world)
        created = get_success_data(
            api.create_offering_document(
                factories.offering_document_payload(world.production_id),
                COUNSEL_HEADERS,
            ),
            201,
        )
        assert created["status"] == "DRAFT"
        assert created["version"] == 1

        effective = get_success_data(
            api.make_offering_document_effective(created["id"], COUNSEL_HEADERS), 200
        )
        assert effective["status"] == "EFFECTIVE"
        assert effective["version"] == 2
        assert effective["accepted_units_total"] == 0
        assert effective["accepted_amount_cents"] == 0
        assert effective["accepted_investor_count"] == 0
        assert effective["submitted_units_total"] == 0
        assert effective["withdrawal_reason"] is None

        production = world.production()
        assert production["offering_status"] == "OFFERING"
        assert production["version"] == 2

    def test_making_an_instrument_effective_before_the_offering_opens_is_refused(
        self, api: ApiClient
    ):
        """The production is still DRAFT on the syndication axis, so the document waits.

        "Until the axis reads `OFFERING`, no offering instrument may be made
        effective."

        Design: Corner/state_machines/make_effective_before_open_offering_rejected
        """
        world = fixtures.base_world(api)
        created = get_success_data(
            api.create_offering_document(
                factories.offering_document_payload(world.production_id),
                COUNSEL_HEADERS,
            ),
            201,
        )

        refused = api.make_offering_document_effective(created["id"], COUNSEL_HEADERS)
        validate_error(refused, ApiErrorId.PRODUCTION_NOT_OFFERING)

        after = get_success_data(
            api.get_offering_document(created["id"], COUNSEL_HEADERS), 200
        )
        assert after["status"] == "DRAFT"
        assert after["version"] == 1
        assert world.production()["offering_status"] == "DRAFT"

    def test_a_withdrawn_instrument_cannot_be_withdrawn_again(self, api: ApiClient):
        """WITHDRAWN is terminal, and the recorded reason is not overwritten.

        "Withdrawal is available from either `DRAFT` or `EFFECTIVE`, takes a
        `withdrawal_reason` which is recorded on the document, and lands the
        document in the terminal `WITHDRAWN` state; the field reads null on any
        document that has not been withdrawn."

        "**Own-state admissibility.** The target row is in a state from which the
        requested transition exists, else that machine's state error (409)."

        Design: Corner/state_machines/offering_document_withdraw_twice_rejected
        """
        world = fixtures.base_world(api)
        fixtures.open_offering(world)
        fixtures.with_effective_document(world)
        document_id = world.offering_document_id or ""

        withdrawn = get_success_data(
            api.withdraw_offering_document(
                document_id, factories.withdrawal_payload("Terms repapered"), COUNSEL_HEADERS
            ),
            200,
        )
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["withdrawal_reason"] == "Terms repapered"
        assert withdrawn["version"] == 3

        refused = api.withdraw_offering_document(
            document_id,
            factories.withdrawal_payload("A second, different reason"),
            COUNSEL_HEADERS,
        )
        validate_error(refused, ApiErrorId.INVALID_OFFERING_DOCUMENT_STATE)

        after = get_success_data(
            api.get_offering_document(document_id, COUNSEL_HEADERS), 200
        )
        assert_no_write(withdrawn, after)
        assert after["withdrawal_reason"] == "Terms repapered"
        assert after["version"] == 3


class TestInvestorAccreditationMachine:
    """The securities determination has no terminal state at all."""

    def test_the_determination_can_be_re_recorded_in_either_direction(
        self, api: ApiClient
    ):
        """Accredited, withdrawn, then granted again, each hop advancing the version.

        "Counsel then records the securities determination by supplying an
        `accreditation_status` of `ACCREDITED` or `NON_ACCREDITED`; that
        determination is freely re-recordable in either direction and from any
        current value, so `UNVERIFIED → ACCREDITED`, `UNVERIFIED →
        NON_ACCREDITED`, `ACCREDITED → NON_ACCREDITED`, and `NON_ACCREDITED →
        ACCREDITED` are all admissible and each advances the investor's
        `version`."

        Design: Corner/state_machines/investor_accreditation_cycles_in_both_directions
        """
        investor = get_success_data(
            api.create_investor(factories.investor_payload(), COUNSEL_HEADERS), 201
        )
        assert investor["accreditation_status"] == "UNVERIFIED"
        assert investor["version"] == 1

        for expected_status, expected_version in (
            ("ACCREDITED", 2),
            ("NON_ACCREDITED", 3),
            ("ACCREDITED", 4),
        ):
            recorded = get_success_data(
                api.accredit_investor(
                    investor["id"],
                    factories.accreditation_payload(expected_status),
                    COUNSEL_HEADERS,
                ),
                200,
            )
            assert recorded["accreditation_status"] == expected_status
            assert recorded["version"] == expected_version


class TestOperatingAxisMachine:
    """The calendar axis advances one declared hop at a time and never skips."""

    def test_the_calendar_axis_cannot_jump_over_rehearsal(self, api: ApiClient):
        """RUNNING and CLOSED are both unreachable from PRE_PRODUCTION.

        "Three advances are available: `PRE_PRODUCTION → REHEARSAL`, `REHEARSAL →
        PREVIEWS`, and `PREVIEWS → RUNNING`. Requesting a `to_status` that is not
        reachable from the current `operating_status` is rejected with
        `ERR_INVALID_OPERATING_STATE` (HTTP 409)."

        Design: Corner/state_machines/operating_axis_cannot_skip_from_pre_production_to_running
        """
        world = fixtures.capitalized_world(api)
        before = world.production()
        assert before["operating_status"] == "PRE_PRODUCTION"
        assert before["version"] == 4

        for to_status in ("RUNNING", "CLOSED"):
            validate_error(
                api.set_operating_status(
                    world.production_id,
                    factories.operating_status_payload(to_status),
                    PRODUCER_HEADERS,
                ),
                ApiErrorId.INVALID_OPERATING_STATE,
            )

        after = world.production()
        assert_no_write(before, after)
        assert after["operating_status"] == "PRE_PRODUCTION"

        advanced = fixtures.advance_operating_status(world, "REHEARSAL")
        assert advanced["operating_status"] == "REHEARSAL"
        assert advanced["version"] == 5

    def test_leaving_rehearsal_needs_an_active_operating_budget(self, api: ApiClient):
        """The hop is refused until a budget is drafted and activated.

        "Leaving `REHEARSAL` for `PREVIEWS` requires that exactly one operating
        budget of the production be in `ACTIVE` status; if none is, the request is
        rejected with `ERR_ACTIVE_OPERATING_BUDGET_MISSING` (HTTP 409)."

        Design: Corner/state_machines/previews_without_active_operating_budget_rejected
        """
        world = fixtures.base_world(api)
        fixtures.with_accepted_subscription(world)
        fixtures.capitalize(world)
        fixtures.advance_operating_status(world, "REHEARSAL")

        before = world.production()
        assert before["operating_status"] == "REHEARSAL"
        assert before["version"] == 5

        refused = api.set_operating_status(
            world.production_id,
            factories.operating_status_payload("PREVIEWS"),
            PRODUCER_HEADERS,
        )
        validate_error(refused, ApiErrorId.ACTIVE_OPERATING_BUDGET_MISSING)
        assert_no_write(before, world.production())

        fixtures.with_active_operating_budget(world)
        advanced = fixtures.advance_operating_status(world, "PREVIEWS")
        assert advanced["operating_status"] == "PREVIEWS"
        assert advanced["version"] == 6

    def test_the_two_axes_advance_without_disturbing_one_another(
        self, api: ApiClient
    ):
        """Syndication reaches its terminal state while the calendar climbs separately.

        "A transition on one axis is never a transition on the other, and each
        axis reports its own rejection code: an inadmissible move on the
        syndication axis is `ERR_INVALID_OFFERING_STATE` (HTTP 409), and an
        inadmissible move on the calendar axis is `ERR_INVALID_OPERATING_STATE`
        (HTTP 409)."

        Design: Corner/state_machines/offering_and_operating_axes_advance_independently
        """
        world = fixtures.base_world(api)
        fixtures.with_active_operating_budget(world)
        fixtures.with_accepted_subscription(world)

        subscribed = world.production()
        assert subscribed["offering_status"] == "FULLY_SUBSCRIBED"
        assert subscribed["operating_status"] == "PRE_PRODUCTION"
        assert subscribed["version"] == 3

        capitalized = fixtures.capitalize(world)
        assert capitalized["offering_status"] == "CAPITALIZED"
        assert capitalized["operating_status"] == "PRE_PRODUCTION"
        assert capitalized["version"] == 4

        rehearsing = fixtures.advance_operating_status(world, "REHEARSAL")
        assert rehearsing["offering_status"] == "CAPITALIZED"
        assert rehearsing["operating_status"] == "REHEARSAL"
        assert rehearsing["version"] == 5

        previewing = fixtures.advance_operating_status(world, "PREVIEWS")
        assert previewing["offering_status"] == "CAPITALIZED"
        assert previewing["operating_status"] == "PREVIEWS"
        assert previewing["version"] == 6


class TestOfferingAxisTerminalState:
    """CAPITALIZED closes the syndication axis for good."""

    def test_neither_hop_is_available_once_capital_has_been_released(
        self, api: ApiClient
    ):
        """Re-opening the offering and re-releasing escrow are both refused.

        "That is the only transition available out of `DRAFT` on that axis, and
        requesting it from any other offering state reports
        `ERR_INVALID_OFFERING_STATE`."

        "A `Comptroller` releases it once the axis reads `FULLY_SUBSCRIBED`, which
        sets `released_capital_cents` equal to `capital_raised_cents`, drives
        `escrow_balance_cents` to 0, and advances the syndication axis
        `FULLY_SUBSCRIBED → CAPITALIZED`, the terminal state on that axis."

        Design: Corner/state_machines/capitalized_offering_axis_is_terminal
        """
        world = fixtures.capitalized_world(api)
        before = world.production()

        validate_error(
            api.open_offering(world.production_id, COUNSEL_HEADERS),
            ApiErrorId.INVALID_OFFERING_STATE,
        )
        validate_error(
            api.capitalize(world.production_id, COMPTROLLER_HEADERS),
            ApiErrorId.INVALID_OFFERING_STATE,
        )

        after = world.production()
        assert_no_write(before, after)
        assert after["offering_status"] == "CAPITALIZED"
        assert after["capital_raised_cents"] == 120_000_000
        assert after["released_capital_cents"] == 120_000_000
        assert after["escrow_balance_cents"] == 0
        assert after["version"] == 4


class TestSubscriptionCureBranch:
    """A subscription out for cure is not acceptable until it comes back."""

    def test_a_returned_subscription_must_be_resubmitted_before_acceptance(
        self, api: ApiClient
    ):
        """The cure round is recorded, acceptance is refused, and resubmission reopens it.

        "Counsel may accept only a subscription in `SUBMITTED`, only while its
        instrument reads `EFFECTIVE`, only while the subscribing investor reads
        `ACCREDITED`, and only within the instrument's date window."

        "The investor closes the cure loop by resubmitting, which returns the
        subscription from `RETURNED_FOR_CURE` to `SUBMITTED`."

        Design: Corner/state_machines/subscription_accept_from_returned_for_cure_rejected
        """
        world = fixtures.base_world(api)
        fixtures.open_offering(world)
        fixtures.with_effective_document(world)
        investor_id = fixtures.new_accredited_investor(world)
        subscription_id = fixtures.new_subscription(world, investor_id, units=1)

        returned = get_success_data(
            api.return_subscription_for_cure(
                subscription_id,
                factories.cure_payload("Signature page unsigned"),
                COUNSEL_HEADERS,
            ),
            200,
        )
        assert returned["status"] == "RETURNED_FOR_CURE"
        assert returned["cure_round_count"] == 1
        assert returned["defect_note"] == "Signature page unsigned"

        validate_error(
            api.accept_subscription(subscription_id, COUNSEL_HEADERS),
            ApiErrorId.INVALID_SUBSCRIPTION_STATE,
        )

        resubmitted = get_success_data(
            api.resubmit_subscription(
                subscription_id,
                factories.resubmit_payload(units=1),
                make_investor_headers(investor_id),
            ),
            200,
        )
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["amount_cents"] == 120_000_000

        accepted = fixtures.accept_subscription(world, subscription_id)
        assert accepted["status"] == "ACCEPTED"


class TestWeeklyWrapInitialState:
    """A wrap opens in DRAFT with the active budget pinned and no audit trail yet."""

    def test_a_new_wrap_pins_the_active_budget_and_records_no_operator(
        self, api: ApiClient
    ):
        """The pin captures the budget's post-activation version, and the wrap is DRAFT.

        "Exactly one operating budget of the production must be `ACTIVE`, else
        `ERR_ACTIVE_OPERATING_BUDGET_MISSING` (HTTP 409) — because opening a wrap
        **pins** that budget, capturing its identifier as `operating_budget_id`
        and its current `version` as `operating_budget_version_pinned`."

        Design: Corner/state_machines/weekly_wrap_starts_in_draft_initial_state
        """
        world = fixtures.running_world(api)
        before = world.production()
        assert before["version"] == 7

        world.set_clock("2026-09-07")
        wrap_id = fixtures.new_wrap(world)
        wrap = get_success_data(api.get_weekly_wrap(wrap_id, GM_HEADERS), 200)

        assert wrap["status"] == "DRAFT"
        assert wrap["version"] == 1
        assert wrap["operating_budget_id"] == world.operating_budget_id
        assert wrap["operating_budget_version_pinned"] == 2
        assert wrap["submitted_by_user_id"] is None
        assert wrap["certified_by_user_id"] is None
        assert wrap["dispute_note"] is None
        assert wrap["void_reason"] is None

        assert world.production()["version"] == 7


class TestOperatingBudgetSupersession:
    """Activating a second budget is admissible and demotes the first."""

    def test_the_previously_active_budget_moves_to_superseded(self, api: ApiClient):
        """Two activations leave exactly one ACTIVE budget behind.

        "Activation is deliberately not exclusive — a production may activate a
        second budget, and doing so supersedes the first. The previously `ACTIVE`
        budget of the same production, if there is one, transitions `ACTIVE →
        SUPERSEDED` and its `version` advances."

        Design: Corner/state_machines/activating_second_operating_budget_supersedes_the_first
        """
        world = fixtures.base_world(api)
        fixtures.with_active_operating_budget(world)
        first_id = world.operating_budget_id or ""

        second = get_success_data(
            api.create_operating_budget(
                factories.operating_budget_payload(
                    world.production_id, weekly_fixed_running_cost_cents=40_000_000
                ),
                GM_HEADERS,
            ),
            201,
        )
        assert second["status"] == "DRAFT"
        assert second["version"] == 1

        activated = get_success_data(
            api.activate_operating_budget(second["id"], COMPTROLLER_HEADERS), 200
        )
        assert activated["status"] == "ACTIVE"
        assert activated["version"] == 2

        first = get_success_data(api.get_operating_budget(first_id, GM_HEADERS), 200)
        assert first["status"] == "SUPERSEDED"
        assert first["version"] == 3

        rows, meta = validate_paginated(
            api.list_operating_budgets(
                GM_HEADERS, {"production_id": world.production_id, "status": "ACTIVE"}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == second["id"]


class TestClosingNoticeCascade:
    """Posting a notice commits the reserve lines and nothing else."""

    def test_only_the_reserve_component_is_driven_to_committed(self, api: ApiClient):
        """The production line stays PLANNED while the reserve line is earmarked.

        "Every budget line of the production whose `component` is `RESERVE` and
        whose `commitment_status` is `PLANNED` becomes `COMMITTED` — the reserve
        is being earmarked for the costs of shutting down."

        Design: Corner/state_machines/closing_notice_commits_only_reserve_budget_lines
        """
        world = fixtures.running_world(api)
        production_line = get_success_data(
            api.create_budget_line(
                factories.budget_line_payload(
                    world.production_id, 40_000_000, world.production_version()
                ),
                GM_HEADERS,
            ),
            201,
        )
        fixtures.with_reserve_line(world, 20_000_000)
        reserve_line_id = world.reserve_line_id or ""

        notice = get_success_data(
            api.create_closing_notice(
                factories.closing_notice_payload(
                    world.production_id, "2026-08-01", "2026-08-20"
                ),
                PRODUCER_HEADERS,
            ),
            201,
        )
        assert notice["status"] == "ISSUED"
        assert notice["notice_days"] == 19
        assert notice["issued_by_user_id"] == PRODUCER_USER_ID
        assert notice["settled_by_user_id"] is None

        reserve = get_success_data(api.get_budget_line(reserve_line_id, GM_HEADERS), 200)
        assert reserve["commitment_status"] == "COMMITTED"
        assert reserve["version"] == 2

        untouched = get_success_data(
            api.get_budget_line(production_line["id"], GM_HEADERS), 200
        )
        assert untouched["commitment_status"] == "PLANNED"
        assert untouched["version"] == 1

        production = world.production()
        assert production["operating_status"] == "CLOSING_NOTICE"
        assert production["budget_total_cents"] == 60_000_000
        assert production["budget_committed_cents"] == 20_000_000
        assert production["version"] == 10


class TestSubsidiaryRightsAllocationMachine:
    """RECORDED to ALLOCATED is what moves licensing money into the cash ledger."""

    def test_allocating_licensing_income_re_derives_the_recoupment_ledger(
        self, api: ApiClient
    ):
        """Four tenths of ten million lands on the ledger in the same request.

        "It then cascades: the recoupment figures are re-derived, and if the
        recompute crosses the target, `recoupment_status` becomes `RECOUPED` and
        every capital account of the production flips its `basis` to
        `NET_PROFIT`. The production's `version` advances. `ALLOCATED` is
        terminal."

        Design: Corner/state_machines/subsidiary_rights_allocation_syncs_recoupment_ledger
        """
        world = fixtures.capitalized_world(api)
        income = fixtures.with_recorded_income(world, gross_income_cents=10_000_000)
        assert income["status"] == "RECORDED"
        assert income["investor_share_cents"] == 0

        allocated = get_success_data(
            api.allocate_subsidiary_rights_income(income["id"], COMPTROLLER_HEADERS), 200
        )
        assert allocated["status"] == "ALLOCATED"
        assert allocated["investor_share_cents"] == 4_000_000

        production = world.production()
        assert production["recouped_amount_cents"] == 4_000_000
        assert production["recoupment_pct"] == 0.0333
        assert production["distributable_cash_cents"] == 4_000_000
        assert production["recoupment_status"] == "UNRECOUPED"
        assert production["version"] == 5

        assert fixtures.sole_account(world)["basis"] == "RECOUPMENT_RETURN"


class TestParticipantCycleGuards:
    """The participation cycle refuses the hop it is not standing on."""

    def test_an_active_participation_cannot_be_reinstated(self, api: ApiClient):
        """Reinstate needs TERMINATED, and terminate needs ACTIVE.

        "A `LeadProducer` may terminate an `ACTIVE` participation and may
        reinstate a `TERMINATED` one; requesting terminate on a participation that
        is not `ACTIVE`, or reinstate on one that is not `TERMINATED`, reports
        `ERR_INVALID_PARTICIPANT_STATE` (HTTP 409)."

        Design: Corner/state_machines/participant_reinstate_from_active_rejected
        """
        world = fixtures.base_world(api)
        participant = get_success_data(
            api.create_royalty_participant(
                factories.participant_payload(world.production_id), GM_HEADERS
            ),
            201,
        )
        assert participant["status"] == "ACTIVE"
        assert participant["pool_share_pct"] == 1.0
        assert participant["cumulative_royalty_cents"] == 0

        validate_error(
            api.reinstate_royalty_participant(participant["id"], PRODUCER_HEADERS),
            ApiErrorId.INVALID_PARTICIPANT_STATE,
        )
        assert (
            get_success_data(
                api.get_royalty_participant(participant["id"], GM_HEADERS), 200
            )["status"]
            == "ACTIVE"
        )

        terminated = get_success_data(
            api.terminate_royalty_participant(participant["id"], PRODUCER_HEADERS), 200
        )
        assert terminated["status"] == "TERMINATED"
        assert terminated["pool_share_pct"] == 0.0

        validate_error(
            api.terminate_royalty_participant(participant["id"], PRODUCER_HEADERS),
            ApiErrorId.INVALID_PARTICIPANT_STATE,
        )
        assert world.production()["total_pool_points"] == 0
