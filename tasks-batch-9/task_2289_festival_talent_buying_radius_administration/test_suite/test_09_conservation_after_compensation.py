"""Conserved quantities across compensating writes: money, minutes, installments.

Every test below builds its own preconditions from an empty database, because
the server is restarted before each test.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    BUSINESS_AFFAIRS,
    FINANCE_CONTROLLER,
    PRODUCTION_MANAGER,
    TALENT_BUYER,
    expected_settlement_total_cents,
    make_artist_rep_headers,
)
from test_helpers import fixtures as fx
from test_helpers.factories import offer_payload

CLOCK_AT_PLANNING = "2026-08-01T00:00:00Z"
CLOCK_AT_DEPOSIT_RELEASE = "2026-08-24T00:00:00Z"


def _committed_sums(api, festival_id):
    """The three expressions the first conservation law ties together."""
    summary = validate_success(api.get_budget_summary(festival_id, TALENT_BUYER))
    return (
        summary["committed_budget_cents"],
        summary["tier_committed_sum_cents"],
        summary["booking_committed_sum_cents"],
    )


# --------------------------------------------------------------------------
# One issued offer carrying both a guarantee and a production fee.
# --------------------------------------------------------------------------
def _issued_offer_with_production_fee(api):
    fx.set_clock(api, CLOCK_AT_PLANNING)
    festival = fx.create_festival(api)
    tier = fx.create_tier(
        api,
        festival["id"],
        tier_code="HEADLINER",
        tier_rank=1,
        allocation_pct=1.00,
        max_slots=1,
        genre_focus="ELECTRONIC",
    )
    fx.allocate(api, festival)
    stage = fx.create_stage(api, festival["id"])
    artist = fx.create_artist(api)
    ctx = {"festival": festival, "tier": tier, "stage": stage, "artist": artist}
    offer = fx.issued_offer(
        api, ctx, artist, guarantee_cents=1600000, production_fee_cents=200000
    )
    return {
        "festival": festival,
        "tier": tier,
        "stage": stage,
        "artist": artist,
        "offer": offer,
    }


def _accept(api, offer_id, artist_id):
    return validate_success(
        api.accept_offer(offer_id, make_artist_rep_headers(artist_id)), 201
    )


def test_acceptance_debits_the_guarantee_and_the_production_fee_together(api):
    """1600000 of guarantee plus 200000 of production fee is one 1800000 commitment.

    "A festival's `committed_budget_cents` must always equal the sum of `committed_cents` across that festival's budget tiers, and must equally always equal the sum of `guarantee_cents` plus `production_fee_cents` over that festival's bookings whose `contract_status` is anything other than `CANCELLED`."
    "Accepting an offer debits the guarantee plus the production fee into the tier; cancelling the resulting booking credits exactly the same amount back."

    Design: Difficulty/compensating_invariant/budget_commitment_restored_after_cancel_and_replace
    """
    state = _issued_offer_with_production_fee(api)
    _accept(api, state["offer"]["id"], state["artist"]["id"])

    assert _committed_sums(api, state["festival"]["id"]) == (1800000, 1800000, 1800000)

    tier = validate_success(api.get_budget_tier(state["tier"]["id"], TALENT_BUYER))
    assert tier["committed_cents"] == 1800000
    assert tier["slots_committed"] == 1
    assert tier["status"] == "CLOSED"

    festival = validate_success(api.get_festival(state["festival"]["id"], TALENT_BUYER))
    assert festival["headliner_anchor_count"] == 1


def test_cancelling_credits_back_the_whole_commitment_including_the_fee(api):
    """The credit is the full 1800000, not the 1600000 guarantee alone.

    "Running an acceptance and then a cancellation on the same offer must return all three expressions to their pre-acceptance values with zero drift, including in the case where the tier flipped to `CLOSED` and back to `OPEN` in between."
    "The party percentage is 1.00 when `cancelling_party` is `ARTIST`, 0.50 when it is `FORCE_MAJEURE`, and 0.00 when it is `PROMOTER` — a promoter who walks away recovers no deposit."

    Design: Difficulty/compensating_invariant/budget_commitment_restored_after_cancel_and_replace
    """
    state = _issued_offer_with_production_fee(api)
    booking = _accept(api, state["offer"]["id"], state["artist"]["id"])
    clause = fx.clause_of_booking(api, booking["id"])

    cancelled = validate_success(
        api.cancel_booking(
            booking["id"],
            {
                "cancelling_party": "PROMOTER",
                "cancellation_reason": "Stage redesign dropped the slot",
            },
            TALENT_BUYER,
        )
    )
    assert cancelled["contract_status"] == "CANCELLED"
    assert cancelled["contractual_recovery_cents"] == 0

    assert _committed_sums(api, state["festival"]["id"]) == (0, 0, 0)

    tier = validate_success(api.get_budget_tier(state["tier"]["id"], TALENT_BUYER))
    assert tier["committed_cents"] == 0
    assert tier["slots_committed"] == 0
    assert tier["status"] == "OPEN"

    festival = validate_success(api.get_festival(state["festival"]["id"], TALENT_BUYER))
    assert festival["headliner_anchor_count"] == 0

    released = validate_success(api.get_radius_clause(clause["id"], BUSINESS_AFFAIRS))
    assert released["enforcement_status"] == "RELEASED"


def test_a_replacement_pointed_at_a_live_booking_is_refused(api):
    """A replacement stands in for a cancellation, never for a live commitment.

    "A replacement offer is drafted with `replaces_booking_id` naming the booking it stands in for; that booking must belong to the same edition and must already be `CANCELLED`, or the draft is refused with `ERR_REPLACEMENT_TARGET_NOT_CANCELLED`."

    Design: Difficulty/compensating_invariant/budget_commitment_restored_after_cancel_and_replace
    """
    state = _issued_offer_with_production_fee(api)
    booking = _accept(api, state["offer"]["id"], state["artist"]["id"])

    payload = offer_payload(
        state["festival"]["id"],
        state["artist"]["id"],
        state["tier"]["id"],
        state["stage"]["id"],
        guarantee_cents=1600000,
        production_fee_cents=200000,
        replaces_booking_id=booking["id"],
    )
    validate_error(
        api.create_offer(payload, TALENT_BUYER),
        "ERR_REPLACEMENT_TARGET_NOT_CANCELLED",
        409,
    )

    assert _committed_sums(api, state["festival"]["id"]) == (1800000, 1800000, 1800000)


# --------------------------------------------------------------------------
# Two stages, each carrying its own accepted booking.
# --------------------------------------------------------------------------
def _two_stages_each_with_a_booking(api):
    fx.set_clock(api, CLOCK_AT_PLANNING)
    festival = fx.create_festival(api)
    tier = fx.create_tier(
        api,
        festival["id"],
        tier_code="HEADLINER",
        tier_rank=1,
        allocation_pct=1.00,
        max_slots=2,
        genre_focus="MIXED",
    )
    fx.allocate(api, festival)
    main_stage = fx.create_stage(api, festival["id"])
    grove = fx.create_stage(
        api,
        festival["id"],
        name="Grove",
        capacity=6000,
        daily_curfew_minute=1200,
        daily_program_minutes_cap=360,
        changeover_buffer_minutes=30,
        is_flagship=False,
    )
    headliner = fx.create_artist(api)
    side_act = fx.create_artist(
        api,
        legal_name="Hollow Pines LLC",
        performing_name="Hollow Pines",
        primary_genre="COUNTRY",
        agency="Foghorn Agency",
        draw_score=20,
        default_radius_miles=75,
    )

    grove_booking = fx.accepted_booking(
        api,
        {"festival": festival, "tier": tier, "stage": grove, "artist": side_act},
        side_act,
        guarantee_cents=500000,
        production_fee_cents=0,
        billing_position=2,
        set_length_minutes=45,
        slot_start_utc="2026-12-05T14:00:00Z",
        radius_miles=75,
        window_start_date="2026-11-04",
        window_end_date="2026-12-14",
    )
    main_booking = fx.accepted_booking(
        api,
        {"festival": festival, "tier": tier, "stage": main_stage, "artist": headliner},
        headliner,
        billing_position=1,
        set_length_minutes=90,
        slot_start_utc="2026-12-05T21:00:00Z",
    )
    return {
        "festival": festival,
        "main_stage": validate_success(api.get_stage(main_stage["id"], PRODUCTION_MANAGER)),
        "grove": grove,
        "main_booking": main_booking,
        "grove_booking": grove_booking,
    }


def _cancel_for_force_majeure(api, booking_id):
    return validate_success(
        api.cancel_booking(
            booking_id,
            {
                "cancelling_party": "FORCE_MAJEURE",
                "cancellation_reason": "Artist visa withdrawn",
            },
            BUSINESS_AFFAIRS,
        )
    )


def test_each_stage_carries_only_the_minutes_of_its_own_bookings(api):
    """90 minutes on the flagship stage, 45 on the side stage, never pooled.

    "A stage's `booked_minutes` must always equal the sum of `set_length_minutes` over that stage's bookings whose `contract_status` is anything other than `CANCELLED`, again as exact integer equality."

    Design: Difficulty/compensating_invariant/stage_minutes_restored_after_cancel_and_replace
    """
    state = _two_stages_each_with_a_booking(api)

    main_stage = validate_success(
        api.get_stage(state["main_stage"]["id"], PRODUCTION_MANAGER)
    )
    grove = validate_success(api.get_stage(state["grove"]["id"], PRODUCTION_MANAGER))
    assert main_stage["booked_minutes"] == 90
    assert grove["booked_minutes"] == 45


def test_cancelling_debits_exactly_the_cancelled_set_length_from_one_stage(api):
    """The 90 minutes leave the flagship line and the side stage does not move.

    "Acceptance adds the set length; cancellation subtracts exactly the same minutes."

    Design: Difficulty/compensating_invariant/stage_minutes_restored_after_cancel_and_replace
    """
    state = _two_stages_each_with_a_booking(api)
    _cancel_for_force_majeure(api, state["main_booking"]["id"])

    main_stage = validate_success(
        api.get_stage(state["main_stage"]["id"], PRODUCTION_MANAGER)
    )
    grove = validate_success(api.get_stage(state["grove"]["id"], PRODUCTION_MANAGER))
    assert main_stage["booked_minutes"] == 0
    assert grove["booked_minutes"] == 45
    assert main_stage["version"] > state["main_stage"]["version"]


def test_a_force_majeure_cancellation_leaves_no_money_to_claw_back(api):
    """Nothing had been paid, so the minutes ledger is all that moved.

    "`contractual_recovery_cents` is then the booking's `deposit_paid_cents` multiplied by the party percentage and rounded half up, **plus separately** the booking's `guarantee_cents` multiplied by the liquidated-damages percentage and rounded half up."
    "Independently in the same hop, the installment flags decide the money dimension: `settlement_status` becomes `RECOVERY_PENDING` when at least one installment is now `CLAWBACK_PENDING`, and otherwise becomes `RECOVERED` with `actual_recovered_cents` at 0."

    Design: Difficulty/compensating_invariant/stage_minutes_restored_after_cancel_and_replace
    """
    state = _two_stages_each_with_a_booking(api)
    cancelled = _cancel_for_force_majeure(api, state["main_booking"]["id"])

    assert cancelled["contractual_recovery_cents"] == 0
    assert cancelled["actual_recovered_cents"] == 0
    assert cancelled["settlement_status"] == "RECOVERED"

    rows, _ = validate_paginated(
        api.list_payment_installments(state["main_booking"]["id"], FINANCE_CONTROLLER)
    )
    assert [row["status"] for row in rows] == ["VOIDED", "VOIDED"]


# --------------------------------------------------------------------------
# A booking whose deposit has already been paid before the amendment.
# --------------------------------------------------------------------------
def _booking_with_a_paid_deposit(api):
    fx.set_clock(api, CLOCK_AT_PLANNING)
    festival = fx.create_festival(api)
    tier = fx.create_tier(
        api,
        festival["id"],
        tier_code="HEADLINER",
        tier_rank=1,
        allocation_pct=1.00,
        max_slots=1,
        genre_focus="ELECTRONIC",
    )
    fx.allocate(api, festival)
    stage = fx.create_stage(api, festival["id"])
    artist = fx.create_artist(api, draw_score=95)
    ctx = {"festival": festival, "tier": tier, "stage": stage, "artist": artist}

    booking = fx.accepted_booking(api, ctx, artist)
    version_at_accept = booking["version"]
    installments = fx.installments_of(api, booking["id"])
    assert installments["DEPOSIT"]["amount_cents"] == 900000
    assert installments["BALANCE"]["amount_cents"] == 900000

    fx.set_clock(api, CLOCK_AT_DEPOSIT_RELEASE)
    fx.pay_installment(api, installments["DEPOSIT"])

    return {
        "festival": festival,
        "tier": tier,
        "booking": booking,
        "version_at_accept": version_at_accept,
        "deposit": installments["DEPOSIT"],
        "balance": installments["BALANCE"],
    }


def _amend(api, booking_id, expected_version):
    return api.amend_guarantee(
        booking_id,
        {
            "guarantee_cents": 2000000,
            "expected_booking_version": expected_version,
            "amendment_reason": "Agency renegotiated after the deposit cleared",
        },
        TALENT_BUYER,
    )


def test_an_amendment_replaying_the_acceptance_version_is_rejected(api):
    """Recording the deposit payment already advanced the booking's version.

    "Amending an executed guarantee requires `expected_booking_version` to match the target booking's `version`."
    "A mismatch is rejected with `ERR_STALE_BOOKING_VERSION` (HTTP 412)."

    Design: Difficulty/compensating_invariant/installment_total_conserved_across_guarantee_amendment
    """
    state = _booking_with_a_paid_deposit(api)

    validate_error(
        _amend(api, state["booking"]["id"], state["version_at_accept"]),
        "ERR_STALE_BOOKING_VERSION",
        412,
    )

    booking = validate_success(api.get_booking(state["booking"]["id"], TALENT_BUYER))
    assert booking["guarantee_cents"] == 1800000

    deposit = validate_success(
        api.get_payment_installment(state["deposit"]["id"], FINANCE_CONTROLLER)
    )
    balance = validate_success(
        api.get_payment_installment(state["balance"]["id"], FINANCE_CONTROLLER)
    )
    assert deposit["status"] == "PAID"
    assert deposit["amount_cents"] == 900000
    assert balance["status"] == "SCHEDULED"
    assert balance["amount_cents"] == 900000


def test_the_rebuilt_balance_absorbs_the_whole_amended_difference(api):
    """The paid deposit is untouchable, so all 200000 lands on the balance.

    "Every installment of the booking whose `status` is `SCHEDULED` is voided and replaced by a rebuilt scheduled row, using the same two-row deposit-and-balance construction; installments already `PAID` or `RELEASED` are never rewritten, and the rebuilt scheduled rows absorb the whole difference so that the sum of `amount_cents` over the booking's non-voided installments again equals its `guarantee_cents`."
    "A third conservation law governs the installment pair: the sum of `amount_cents` over a booking's installments whose status is anything other than `VOIDED` always equals that booking's `guarantee_cents`."

    Design: Difficulty/compensating_invariant/installment_total_conserved_across_guarantee_amendment
    """
    state = _booking_with_a_paid_deposit(api)
    booking = validate_success(api.get_booking(state["booking"]["id"], TALENT_BUYER))
    amended = validate_success(_amend(api, booking["id"], booking["version"]))
    assert amended["guarantee_cents"] == 2000000

    old_balance = validate_success(
        api.get_payment_installment(state["balance"]["id"], FINANCE_CONTROLLER)
    )
    assert old_balance["status"] == "VOIDED"

    deposit = validate_success(
        api.get_payment_installment(state["deposit"]["id"], FINANCE_CONTROLLER)
    )
    assert deposit["status"] == "PAID"
    assert deposit["amount_cents"] == 900000

    rows, _ = validate_paginated(
        api.list_payment_installments(booking["id"], FINANCE_CONTROLLER)
    )
    live = [row for row in rows if row["status"] != "VOIDED"]
    rebuilt = [row for row in live if row["status"] == "SCHEDULED"]
    assert len(rebuilt) == 1
    assert rebuilt[0]["amount_cents"] == 1100000
    assert rebuilt[0]["due_date"] == "2026-12-05"
    assert sum(row["amount_cents"] for row in live) == 2000000
    assert sum(row["amount_cents"] for row in live) == amended["guarantee_cents"]


def test_the_amendment_moves_both_committed_ledgers_by_the_delta(api):
    """The 200000 increase reaches the tier, the edition and the settlement.

    "The delta between the new guarantee-plus-production-fee and the old one is applied to the tier's `committed_cents` and to the edition's `committed_budget_cents`, and both the tier's `status` and the edition's `lineup_posture` are re-derived — which means an amendment can close a tier or freeze an edition just as an acceptance can."

    Design: Difficulty/compensating_invariant/installment_total_conserved_across_guarantee_amendment
    """
    state = _booking_with_a_paid_deposit(api)
    booking = validate_success(api.get_booking(state["booking"]["id"], TALENT_BUYER))
    amended = validate_success(_amend(api, booking["id"], booking["version"]))

    tier = validate_success(api.get_budget_tier(state["tier"]["id"], TALENT_BUYER))
    assert tier["committed_cents"] == 2000000

    festival = validate_success(api.get_festival(state["festival"]["id"], TALENT_BUYER))
    assert festival["committed_budget_cents"] == 2000000
    assert _committed_sums(api, state["festival"]["id"]) == (2000000, 2000000, 2000000)

    assert amended["settlement_total_cents"] == 1100000
    assert amended["settlement_total_cents"] == expected_settlement_total_cents(
        2000000, 0, 0, 900000
    )
