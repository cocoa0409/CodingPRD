"""The arithmetic the housing program is judged on, at its awkward edges.

Room nights are counted at the peak night rather than added up across adjacent
stays; a rebate rate is chosen once from a contract-wide total and then applied to
every night of a stay; a utilisation reading of exactly nine tenths restricts a
block while nothing below it does; and the revenue split hands one leftover cent
to a single party. Each value below is derived by hand from the stated formula.
"""

from test_helpers import (
    HOUSING_MANAGER_HEADERS,
    RIGHTS_HOLDER_HEADERS,
    ApiErrorId,
    ComplaintOutcome,
    ComplaintRoute,
    DistributionAction,
    NegotiationAction,
    RebateModel,
    RemedyType,
    assertions,
    factories as f,
    fixtures as fx,
    get_success_data,
    validate_error,
    validate_success,
)

HM = HOUSING_MANAGER_HEADERS
RIGHTS = RIGHTS_HOLDER_HEADERS

_TIERED_TERMS = {
    "rebate_model": RebateModel.TIERED_PER_ROOM_NIGHT.value,
    "rebate_flat_cents_per_room_night": None,
}


def _mixed_booking_states_env(api) -> fx.Env:
    """One four-room stay confirmed and a second three-room stay left sitting at
    `ROOMING_LIST_SUBMITTED`, both for the same thirteen-player registration."""
    env = fx.registered_team_env(api)
    booking_confirmed = fx.add_booking(env, rooms_requested=4)
    fx.submit_rooming_list(env, booking=booking_confirmed)
    fx.confirm_booking(env, booking=booking_confirmed)
    booking_submitted = fx.add_booking(env, rooms_requested=3)
    fx.submit_rooming_list(
        env,
        booking=booking_submitted,
        entries=[f.rooming_list_entry(index + 1, occupant_count=4) for index in range(3)],
    )
    env.booking = booking_confirmed
    return env


def _tier_probe_env(api) -> fx.Env:
    """A tiered contract holding one five-room block over a ten-night window,
    with a three-room ten-night stay and a one-room three-night stay confirmed
    on it — thirty and three room nights respectively."""
    env = fx.executed_contract_env(
        api,
        tournament_overrides={"start_date": "2026-09-10", "end_date": "2026-09-20"},
        contract_overrides=dict(_TIERED_TERMS),
        block_overrides={
            "block_size_rooms": 5,
            "arrival_date": "2026-09-10",
            "departure_date": "2026-09-20",
        },
    )
    fx.add_team(env)
    fx.add_registration(env)
    long_stay = fx.add_booking(
        env, rooms_requested=3, check_in_date="2026-09-10", check_out_date="2026-09-20"
    )
    fx.submit_rooming_list(env, booking=long_stay)
    fx.confirm_booking(env, booking=long_stay)
    short_stay = fx.add_booking(
        env, rooms_requested=1, check_in_date="2026-09-10", check_out_date="2026-09-13"
    )
    fx.submit_rooming_list(env, booking=short_stay)
    fx.confirm_booking(env, booking=short_stay)
    fx.close_booking_window(env)
    env.bookings = [long_stay, short_stay]
    return env


def _first_stay_reported_env(api) -> fx.Env:
    """The tier probe with the ten-night stay already reported at thirty room
    nights, so the contract total sits exactly on the middle tier's lower edge."""
    env = _tier_probe_env(api)
    fx.actualize(env, 30, booking=env.bookings[0])
    return env


def _three_of_seven_rooms_env(api) -> fx.Env:
    """Three rooms confirmed against a seven-room block — a ratio that does not
    terminate in four decimal places."""
    env = fx.executed_contract_env(api, block_overrides={"block_size_rooms": 7})
    fx.add_team(env)
    fx.add_registration(env)
    fx.add_booking(env, rooms_requested=3)
    fx.submit_rooming_list(
        env,
        entries=[f.rooming_list_entry(index + 1, occupant_count=4) for index in range(3)],
    )
    return env


def _nine_of_ten_rooms_env(api) -> fx.Env:
    """A nine-room stay awaiting confirmation against a ten-room block, for a
    large roster whose segregated ceiling allows it."""
    env = fx.executed_contract_env(api, block_overrides={"block_size_rooms": 10})
    fx.add_team(env)
    fx.add_registration(env, roster_player_count=34, roster_staff_count=2)
    fx.add_booking(env, rooms_requested=9)
    fx.submit_rooming_list(
        env,
        entries=[f.rooming_list_entry(index + 1, occupant_count=4) for index in range(9)],
    )
    return env


def _two_blocks_env(api) -> fx.Env:
    """One contract holding a twenty-room block nobody has booked and a ten-room
    block with four rooms confirmed and five more awaiting confirmation."""
    env = fx.draft_contract_env(api)
    fx.add_block(env)
    small_block = fx.add_block(env, block_size_rooms=10)
    for action, headers in (
        (NegotiationAction.SUBMIT.value, HM),
        (NegotiationAction.COUNTERSIGN.value, env.hotel_headers),
    ):
        env.contract = get_success_data(
            api.negotiate_contract(env.contract_id, f.negotiation_payload(action), headers)
        )
    fx.add_team(env)
    fx.add_registration(env)
    first_stay = fx.add_booking(env, block=small_block, rooms_requested=4)
    fx.submit_rooming_list(env, booking=first_stay)
    fx.confirm_booking(env, booking=first_stay)

    second_team = fx.create_team(
        api, name="Bravo SC 16U", org_contact_email="bravo16@example.com"
    )
    second_registration = fx.add_registration(env, team=second_team)
    second_stay = fx.add_booking(
        env, registration=second_registration, block=small_block, rooms_requested=5
    )
    fx.submit_rooming_list(
        env,
        booking=second_stay,
        entries=[f.rooming_list_entry(index + 1, occupant_count=3) for index in range(5)],
    )
    env.block = small_block
    env.booking = second_stay
    return env


def _adjacent_stays_env(api) -> fx.Env:
    """Two stays on one ten-room block that share no night: four rooms over the
    first two nights, five rooms over the last one."""
    env = fx.executed_contract_env(api, block_overrides={"block_size_rooms": 10})
    fx.add_team(env)
    fx.add_registration(env)
    early_stay = fx.add_booking(
        env, rooms_requested=4, check_in_date="2026-09-10", check_out_date="2026-09-12"
    )
    fx.submit_rooming_list(env, booking=early_stay)
    fx.confirm_booking(env, booking=early_stay)

    second_team = fx.create_team(
        api, name="Bravo SC 16U", org_contact_email="bravo16@example.com"
    )
    second_registration = fx.add_registration(env, team=second_team)
    late_stay = fx.add_booking(
        env,
        registration=second_registration,
        rooms_requested=5,
        check_in_date="2026-09-12",
        check_out_date="2026-09-13",
    )
    fx.submit_rooming_list(
        env,
        booking=late_stay,
        entries=[f.rooming_list_entry(index + 1, occupant_count=3) for index in range(5)],
    )
    env.booking = late_stay
    return env


def _cancelled_booking_env(api) -> fx.Env:
    """A confirmed four-room, three-night stay cancelled forty days before
    check-in, carrying a 44,700-cent penalty."""
    env = fx.confirmed_booking_env(api)
    env.booking = get_success_data(
        api.cancel_booking(env.booking_id, f.cancel_payload(), HM)
    )
    return env


def _fully_credited_penalty_env(api) -> fx.Env:
    """The cancelled stay with its whole penalty already waived by an upheld
    complaint, so nothing of it remains uncredited."""
    env = _cancelled_booking_env(api)
    fx.add_complaint(env, affected_booking_id=env.booking_id)
    fx.triage_complaint(env, ComplaintRoute.INVESTIGATE.value)
    fx.adjudicate_complaint(
        env,
        ComplaintOutcome.UPHOLD.value,
        RemedyType.FEE_WAIVER.value,
        remedy_amount_cents=60000,
    )
    return env


class TestRevenueShareSplit:
    """The six-step waterfall on a fully collected invoice."""

    def test_the_split_of_ten_thousand_eight_hundred_cents_lands_to_the_cent(self, api):
        """A collected rebate of 10,800 cents pays an 864-cent administration fee
        and splits the remaining 9,936 into 4,969, 2,980 and 1,987 — the one cent
        lost to truncation going to the organizer.

        PRD §3.9: "Step one snapshots `gross_collected_cents` as the source
        invoice's `collected_cents` at that instant."

        PRD §3.9: "Step two selects `admin_fee_pct` from a three-tier table
        **keyed on `gross_collected_cents`**, never on the post-fee amount: below
        50,000 cents the fee is 0.08; from 50,000 cents up to but not including
        200,000 cents it is 0.06; at 200,000 cents or above it is 0.045."

        PRD §3.9: "Step three computes `admin_fee_cents` as
        `gross_collected_cents` multiplied by `admin_fee_pct`, rounded half up to
        a whole cent."

        PRD §3.9: "Step four computes `distributable_cents` as
        `gross_collected_cents` less `admin_fee_cents`."

        PRD §3.9: "Step six computes `rounding_remainder_cents` as
        `distributable_cents` less the three truncated allocations, and stores
        `organizer_cents` as the organizer's truncated allocation **plus that
        entire remainder**."

        PRD §3.9: "The invariant this guarantees is that `organizer_cents`,
        `rights_holder_cents` and `destination_cents` always sum to exactly
        `distributable_cents`."

        Design: Corner/calculations/revenue_share_split_base_case_exact_cents
        """
        env = fx.paid_invoice_env(api)
        assert env.invoice["collected_cents"] == 10800
        invoice = env.refresh_invoice()

        distribution = validate_success(
            api.create_revenue_distribution(
                f.revenue_distribution_payload(
                    env.tournament_id, invoice["id"], invoice["version"]
                ),
                HM,
            ),
            expected_status=201,
        )

        assert distribution["gross_collected_cents"] == 10800
        assert distribution["admin_fee_pct"] == 0.08
        assert distribution["admin_fee_cents"] == 864
        assert distribution["distributable_cents"] == 9936
        assert distribution["organizer_cents"] == 4969
        assert distribution["rights_holder_cents"] == 2980
        assert distribution["destination_cents"] == 1987
        assert distribution["rounding_remainder_cents"] == 1
        assert (
            distribution["organizer_cents"]
            + distribution["rights_holder_cents"]
            + distribution["destination_cents"]
            == 9936
        )


class TestCommittedRoomsScope:
    """Only confirmed and checked-out stays count toward a team's committed
    rooms."""

    def test_cancelling_the_confirmed_stay_drops_committed_rooms_back_to_zero(self, api):
        """With four rooms confirmed and three more merely manifested, the team
        counts four committed rooms and reads compliant; cancelling the confirmed
        stay leaves it at zero and pending again, the submitted stay contributing
        nothing either way.

        PRD §3.3: "Third, `committed_rooms` becomes the sum of `rooms_requested`
        across the registration's bookings whose `booking_status` is `CONFIRMED`
        or `CHECKED_OUT`; bookings at `DRAFT`, `ROOMING_LIST_SUBMITTED` or
        `CANCELLED` contribute nothing."

        PRD §3.3: "Otherwise, if `committed_rooms` is greater than or equal to
        `effective_required_rooms`, the registration is `HOUSING_COMPLIANT`; the
        comparison is inclusive, so a team that has committed exactly its
        effective requirement is compliant."

        PRD §3.5: "The registration's `committed_rooms` and `status` are
        recomputed too, and a team may legitimately fall back from
        `HOUSING_COMPLIANT` to `PENDING_HOUSING` when the rooms it was relying on
        disappear."

        Design: Corner/calculations/committed_rooms_counts_only_confirmed_bookings
        """
        env = _mixed_booking_states_env(api)
        registration = env.refresh_registration()
        assert registration["effective_required_rooms"] == 4
        assert registration["committed_rooms"] == 4
        assert registration["status"] == "HOUSING_COMPLIANT"

        booking = validate_success(
            api.cancel_booking(env.booking["id"], f.cancel_payload(), HM)
        )

        assert booking["booking_status"] == "CANCELLED"
        registration = env.refresh_registration()
        assert registration["committed_rooms"] == 0
        assert registration["status"] == "PENDING_HOUSING"


class TestTieredRebateRate:
    """One rate is chosen from the contract-wide total and applied to every night
    of a stay."""

    def test_a_contract_total_of_exactly_thirty_nights_bills_at_the_higher_rate(
        self, api
    ):
        """Reporting thirty room nights puts the contract exactly on the middle
        tier's inclusive lower edge, so the stay accrues at 750 cents a night for
        22,500 cents rather than 15,000 at the entry rate.

        PRD §3.7: "Under `TIERED_PER_ROOM_NIGHT`, the rate is a function of the
        contract's total volume: sum `actualized_room_nights` over every booking
        whose block belongs to this contract and whose `booking_status` is
        `CHECKED_OUT` — `CONFIRMED` and `CANCELLED` bookings are excluded, and the
        sum is order-insensitive — then select a single rate from that
        contract-wide total."

        PRD §3.7: "Fewer than 30 total room nights selects 500 cents per room
        night; from 30 up to 89 selects 750 cents; 90 or more selects 1,000
        cents."

        PRD §3.7: "The tier boundaries are inclusive at the lower edge, so a
        contract total of exactly 30 room nights selects the 750-cent rate."

        Design: Corner/calculations/tiered_rebate_rate_constant_at_lower_edge_of_tier_two
        """
        env = _tier_probe_env(api)
        long_stay, short_stay = env.bookings

        validate_success(
            api.create_actualization(
                long_stay["id"], f.actualization_payload(30), env.hotel_headers
            ),
            expected_status=201,
        )

        reported = env.refresh_booking(long_stay)
        assert reported["booking_status"] == "CHECKED_OUT"
        assert reported["actualized_room_nights"] == 30
        assert reported["rebate_accrued_cents"] == 22500
        unreported = env.refresh_booking(short_stay)
        assert unreported["booking_status"] == "CONFIRMED"
        assert unreported["actualized_room_nights"] == 0
        assert unreported["rebate_accrued_cents"] == 0

    def test_the_second_stay_bills_every_night_at_the_selected_average_rate(self, api):
        """With the contract total at thirty-three nights, the three-night stay
        accrues 2,250 cents — all three nights at 750 — and the invoice adds the
        two lines to 24,750, which a marginal allocation could not produce.

        PRD §3.7: "That single selected rate is then applied to **all** of this
        booking's room nights — an average-rate selection, not a marginal
        allocation in which the first thirty nights would bill at one rate and the
        rest at another."

        PRD §3.8: "`invoiced_room_nights` is the sum of `actualized_room_nights`
        across the scope."

        PRD §3.8: "`invoiced_rebate_cents` is the sum of each scoped booking's
        rebate line, computed exactly as in §3.7 and — this ordering is fixed —
        **rounded to whole cents per line before the lines are summed**."

        Design: Corner/calculations/tiered_rebate_uses_average_rate_not_marginal_allocation
        """
        env = _first_stay_reported_env(api)
        long_stay, short_stay = env.bookings

        validate_success(
            api.create_actualization(
                short_stay["id"], f.actualization_payload(3), env.hotel_headers
            ),
            expected_status=201,
        )

        assert env.refresh_booking(short_stay)["rebate_accrued_cents"] == 2250
        assert env.refresh_booking(long_stay)["rebate_accrued_cents"] == 22500
        invoice = validate_success(
            api.create_rebate_invoice(f.rebate_invoice_payload(env.contract_id), HM),
            expected_status=201,
        )
        assert invoice["invoiced_room_nights"] == 33
        assert invoice["invoiced_rebate_cents"] == 24750
        assert invoice["attrition_shortfall_room_nights_per_block"] == 0
        assert invoice["total_due_cents"] == 24750
        assertions.assert_rebate_ledger_conserved(invoice)


class TestBlockUtilisation:
    """Utilisation is carried to four decimal places and compared inclusively."""

    def test_three_of_seven_rooms_reads_as_four_decimal_places(self, api):
        """Three rooms of seven is 0.428571…, which the block records as 0.4286
        and which leaves the block open.

        PRD §3.4: "`utilization_pct` is `rooms_committed` divided by
        `block_size_rooms`, rounded half up to four decimal places."

        PRD §2.7: "A block's `utilization_pct` is carried as a decimal fraction
        rounded half up to **four** decimal places."

        PRD §3.4: "`rooms_available` is then `block_size_rooms` less
        `rooms_committed` while the block is `OPEN` or `RESTRICTED`, and exactly 0
        once it is `RELEASED` or `SETTLED`."

        Design: Corner/calculations/utilization_pct_rounded_to_four_decimals
        """
        env = _three_of_seven_rooms_env(api)

        validate_success(api.confirm_booking(env.booking_id, HM))

        block = env.refresh_block()
        assert block["rooms_committed"] == 3
        assert block["rooms_available"] == 4
        assert block["utilization_pct"] == 0.4286
        assert block["status"] == "OPEN"

    def test_a_utilisation_of_exactly_nine_tenths_restricts_the_block(self, api):
        """Nine rooms of ten is 0.9 exactly, and because the comparison is
        inclusive the block restricts itself the moment the stay is confirmed.

        PRD §3.4: "While a block's `status` is `OPEN` or `RESTRICTED`, it reads
        `RESTRICTED` whenever `utilization_pct` is at or above 0.90 — ninety
        percent of the held rooms committed — and `OPEN` otherwise."

        PRD §3.4: "The comparison is inclusive: a `utilization_pct` of exactly
        0.9000 restricts the block, and 0.8999 does not."

        Design: Corner/calculations/utilization_exactly_at_restrict_threshold_restricts_block
        """
        env = _nine_of_ten_rooms_env(api)
        assert env.refresh_block()["status"] == "OPEN"

        validate_success(api.confirm_booking(env.booking_id, HM))

        block = env.refresh_block()
        assert block["rooms_committed"] == 9
        assert block["rooms_available"] == 1
        assert block["utilization_pct"] == 0.9
        assert block["status"] == "RESTRICTED"

    def test_one_restricted_block_of_two_makes_the_contract_tight(self, api):
        """With one of its two live blocks restricted and the other untouched,
        the contract reads `TIGHT` — not sold out — and the event's housing
        pressure stays normal.

        PRD §3.2: "A contract's `block_posture` considers only its **live**
        blocks — those in `OPEN` or `RESTRICTED`; blocks in `RELEASED` or
        `SETTLED` are excluded from both the numerator and the denominator."

        PRD §3.2: "If at least one live block is `RESTRICTED` but not all of them
        are, it is `TIGHT`."

        PRD §3.2: "`housing_pressure` reads `CONSTRAINED` when
        `executed_contract_count` is at least 1 and `sold_out_contract_count`
        equals `executed_contract_count`; in every other case, including the case
        of no executed contracts at all, it reads `NORMAL`."

        Design: Corner/calculations/contract_block_posture_tight_when_only_some_blocks_restricted
        """
        env = _two_blocks_env(api)
        large_block, small_block = env.blocks
        assert env.refresh_contract()["block_posture"] == "AVAILABLE"

        validate_success(api.confirm_booking(env.booking["id"], HM))

        assert env.refresh_block(small_block)["status"] == "RESTRICTED"
        assert env.refresh_block(large_block)["status"] == "OPEN"
        contract = env.refresh_contract()
        assert contract["block_posture"] == "TIGHT"
        tournament = env.refresh_tournament()
        assert tournament["executed_contract_count"] == 1
        assert tournament["sold_out_contract_count"] == 0
        assert tournament["housing_pressure"] == "NORMAL"

    def test_adjacent_stays_peak_at_five_rooms_rather_than_summing_to_nine(self, api):
        """A four-room stay over the first two nights and a five-room stay over
        the third share no night, so the block's committed occupancy is five and
        not the nine a naive sum would report.

        PRD §3.4: "`rooms_committed` is the **peak-night** committed occupancy
        over the block's own half-open window: for each night from `arrival_date`
        up to but not including `departure_date`, sum `rooms_requested` over the
        bookings on this block whose `booking_status` is `CONFIRMED` or
        `CHECKED_OUT` and whose own half-open stay covers that night, then take
        the maximum of those per-night sums across the whole window."

        PRD §3.4: "The server computes `nights` as the whole days from
        `check_in_date` up to but not including `check_out_date`, and
        `projected_room_nights` as `rooms_requested` multiplied by `nights` — the
        pre-stay estimate that cancellation penalties are assessed against."

        Design: Corner/calculations/peak_night_occupancy_not_sum_over_adjacent_stays
        """
        env = _adjacent_stays_env(api)
        early_stay = env.bookings[0]
        assert early_stay["projected_room_nights"] == 8

        late_stay = validate_success(api.confirm_booking(env.booking["id"], HM))

        assert late_stay["projected_room_nights"] == 5
        block = env.refresh_block()
        assert block["rooms_committed"] == 5
        assert block["rooms_available"] == 5
        assert block["utilization_pct"] == 0.5
        assert block["status"] == "OPEN"
        assertions.assert_block_inventory_conserved(block)


class TestEventSettlement:
    """The event settles only once the distribution itself is paid."""

    def test_approving_the_distribution_leaves_the_event_reconciling(self, api):
        """Every invoice is paid and a distribution exists, but while that
        distribution is only approved the event stays in reconciliation.

        PRD §3.8: "Evaluated only while `posture` is `RECONCILING`, the event
        moves to `SETTLED` when every rebate invoice reachable through any of its
        hotel contracts has a `status` of `PAID` or `WRITTEN_OFF`, **and** at
        least one revenue distribution exists for the event, **and** every one of
        those distributions has a `status` of `PAID`."

        PRD §3.9: "`APPROVE`, a rights-holder action, moves it `CALCULATED →
        APPROVED` and sets `approved_by_user_id` to the acting `X-User-ID` — but
        only after the distribution-approver conflict check of §2.10 clears: if
        any complaint on the same `tournament_id` has `category`
        `REBATE_TRANSPARENCY`, `status` `UPHELD`, and an `adjudicated_by_user_id`
        equal to the acting `X-User-ID`, the approval is refused with
        `ERR_SOD_DISTRIBUTION_APPROVER_CONFLICT`."

        Design: Corner/calculations/tournament_settles_only_after_distribution_paid
        """
        env = fx.calculated_distribution_env(api)
        assert env.refresh_invoice()["status"] == "PAID"
        assert env.refresh_tournament()["posture"] == "RECONCILING"

        distribution = validate_success(
            api.advance_distribution(
                env.distribution_id,
                f.advance_payload(DistributionAction.APPROVE.value),
                RIGHTS,
            )
        )

        assert distribution["status"] == "APPROVED"
        assert env.refresh_tournament()["posture"] == "RECONCILING"

    def test_paying_the_distribution_settles_the_event(self, api):
        """Paying the last distribution closes the books, and the invoice records
        the full 10,800 cents of gross collections it has fed into distributions.

        PRD §3.9: "`PAY`, a housing-manager action, moves the distribution
        `APPROVED → PAID` and re-evaluates the tournament's `RECONCILING →
        SETTLED` transition."

        PRD §3.8: "Evaluated only while `posture` is `RECONCILING`, the event
        moves to `SETTLED` when every rebate invoice reachable through any of its
        hotel contracts has a `status` of `PAID` or `WRITTEN_OFF`, **and** at
        least one revenue distribution exists for the event, **and** every one of
        those distributions has a `status` of `PAID`."

        PRD §3.8: "`distributed_cents` is maintained as the sum of
        `gross_collected_cents` across the revenue distributions whose source is
        this invoice, and is updated whenever such a distribution is created."

        Design: Corner/calculations/tournament_settles_only_after_distribution_paid
        """
        env = fx.approved_distribution_env(api)
        assert env.refresh_tournament()["posture"] == "RECONCILING"

        distribution = validate_success(
            api.advance_distribution(
                env.distribution_id, f.advance_payload(DistributionAction.PAY.value), HM
            )
        )

        assert distribution["status"] == "PAID"
        assert env.refresh_tournament()["posture"] == "SETTLED"
        invoice = env.refresh_invoice()
        assert invoice["status"] == "PAID"
        assert invoice["distributed_cents"] == 10800


class TestRemedyCreditClamp:
    """A remedy may only credit the part of a penalty that is still uncredited."""

    def test_a_sixty_thousand_cent_waiver_is_clamped_to_the_forty_four_thousand_penalty(
        self, api
    ):
        """Cancelling forty days out charges three of the twelve projected room
        nights at 14,900 cents, and a waiver asking for 60,000 credits only the
        44,700 actually owed.

        PRD §3.5: "From twenty-one days out up to forty-four,
        `penalty_room_nights` is one quarter of `projected_room_nights`, rounded
        **up** to a whole room night."

        PRD §3.5: "`penalty_cents` is then `penalty_room_nights` multiplied by the
        `negotiated_nightly_rate_cents` of the contract that owns the booking's
        room block — reached from the booking through its block, since the rate
        lives on the contract rather than on the block."

        PRD §3.9: "The credit is computed against the booking named by
        `affected_booking_id`, and it is clamped by how much of that booking's
        penalty is still uncredited: take the booking's `penalty_cents` less its
        `penalty_credit_cents`, floored at 0."

        PRD §3.9: "A `FEE_WAIVER` credits the smaller of the requested
        `remedy_amount_cents` and the uncredited penalty."

        Design: Corner/calculations/remedy_credit_clamped_by_credit_already_granted
        """
        env = _cancelled_booking_env(api)
        assert env.booking["projected_room_nights"] == 12
        assert env.booking["penalty_room_nights"] == 3
        assert env.booking["penalty_cents"] == 44700
        assert env.booking["penalty_credit_cents"] == 0
        fx.add_complaint(env, affected_booking_id=env.booking_id)
        fx.triage_complaint(env, ComplaintRoute.INVESTIGATE.value)

        complaint = validate_success(
            api.adjudicate_complaint(
                env.complaint["id"],
                f.adjudicate_payload(
                    ComplaintOutcome.UPHOLD.value,
                    RemedyType.FEE_WAIVER.value,
                    remedy_amount_cents=60000,
                ),
                RIGHTS,
            )
        )

        assert complaint["remedy_credit_cents"] == 44700
        booking = env.refresh_booking()
        assert booking["penalty_credit_cents"] == 44700
        assert booking["penalty_cents"] == 44700

    def test_a_second_remedy_on_a_fully_credited_penalty_credits_nothing(self, api):
        """A rate adjustment worth 17,880 cents on its own terms credits 0,
        because the penalty it would relieve has already been waived in full.

        PRD §3.9: "A `RATE_ADJUSTMENT` credits the smaller of the uncredited
        penalty and one tenth of the booking's notional room revenue — that is,
        the booking's `projected_room_nights` multiplied by the
        `negotiated_nightly_rate_cents` of the contract owning that booking's
        block, multiplied by one tenth, with the product rounded half up to a
        whole cent before the clamp is applied."

        PRD §3.9: "Since the clamp floor is 0, a booking whose penalty has
        already been fully credited yields a further credit of 0."

        PRD §3.5: "Note that `penalty_credit_cents`, the relief a complaint
        remedy may grant, is tracked separately and **never** reduces
        `penalty_cents` itself; the two figures coexist on the booking so that
        the charge and the relief remain independently auditable."

        Design: Corner/calculations/remedy_credit_clamped_by_credit_already_granted
        """
        env = _fully_credited_penalty_env(api)
        assert env.refresh_booking()["penalty_credit_cents"] == 44700
        fx.add_complaint(env, affected_booking_id=env.booking_id)
        fx.triage_complaint(env, ComplaintRoute.ESCALATE.value)

        complaint = validate_success(
            api.adjudicate_complaint(
                env.complaint["id"],
                f.adjudicate_payload(
                    ComplaintOutcome.UPHOLD.value, RemedyType.RATE_ADJUSTMENT.value
                ),
                RIGHTS,
            )
        )

        assert complaint["status"] == "UPHELD"
        assert complaint["remedy_type"] == "RATE_ADJUSTMENT"
        assert complaint["remedy_credit_cents"] == 0
        booking = env.refresh_booking()
        assert booking["penalty_credit_cents"] == 44700
        assert booking["penalty_cents"] == 44700


class TestRosterRoomRequirements:
    """The segregated ceiling and the pooled floor come from identical inputs."""

    def test_the_booking_ceiling_is_the_segregated_six_and_not_the_pooled_four(
        self, api
    ):
        """Thirteen players and three staff need six rooms segregated but only
        four pooled, and a seven-room request is refused against the six.

        PRD §3.3: "Take `roster_player_count`, divide by four and round **up** to
        a whole number of player rooms; take `roster_staff_count`, divide by two
        and round **up** to a whole number of staff rooms; add the two counts."

        PRD §3.3: "Here players and staff share rooms at the four-per-room
        capacity: add `roster_player_count` and `roster_staff_count`, divide the
        single pooled total by four, and round **up** once."

        PRD §3.3: "A roster of 13 players and 3 staff yields four player rooms
        plus two staff rooms, so `required_rooms_registered` is 6, while the
        pooled computation divides 16 by four and yields
        `minimum_rooms_for_compliance` of 4 — six rooms bookable at most, four
        rooms required at least, from identical inputs."

        PRD §3.4: "`rooms_requested` may not exceed the registration's
        `required_rooms_registered` — the segregated-occupancy figure,
        deliberately not the pooled `minimum_rooms_for_compliance` — or the
        request is rejected with `ERR_ROOMS_EXCEED_ROSTER_REQUIREMENT`."

        Design: Corner/calculations/roster_variant_selection_ceiling_versus_floor
        """
        env = fx.registered_team_env(api)
        registration = env.refresh_registration()
        assert registration["roster_player_count"] == 13
        assert registration["roster_staff_count"] == 3
        assert registration["required_rooms_registered"] == 6
        assert registration["minimum_rooms_for_compliance"] == 4
        assert registration["required_room_nights"] == 18

        response = api.create_booking(
            f.booking_payload(
                registration["id"],
                env.block_id,
                registration["version"],
                rooms_requested=7,
            ),
            HM,
        )

        validate_error(
            response,
            ApiErrorId.ERR_ROOMS_EXCEED_ROSTER_REQUIREMENT.value,
            expected_status=422,
        )

    def test_compliance_is_judged_against_the_pooled_four_rooms(self, api):
        """Four confirmed rooms satisfy the pooled floor and make the team
        compliant, two rooms short of the segregated ceiling it could have
        booked.

        PRD §3.3: "`minimum_rooms_for_compliance` is the **floor** that
        stay-to-play compliance is judged against."

        PRD §3.3: "`required_rooms_registered` is the **ceiling** on how many
        rooms any single booking may request (§3.4)."

        PRD §3.3: "Otherwise, if `committed_rooms` is greater than or equal to
        `effective_required_rooms`, the registration is `HOUSING_COMPLIANT`; the
        comparison is inclusive, so a team that has committed exactly its
        effective requirement is compliant."

        Design: Corner/calculations/roster_variant_selection_ceiling_versus_floor
        """
        env = fx.rooming_list_env(api)
        assert env.refresh_registration()["status"] == "PENDING_HOUSING"

        validate_success(api.confirm_booking(env.booking_id, HM))

        registration = env.refresh_registration()
        assert registration["committed_rooms"] == 4
        assert registration["effective_required_rooms"] == 4
        assert registration["required_rooms_registered"] == 6
        assert registration["status"] == "HOUSING_COMPLIANT"
