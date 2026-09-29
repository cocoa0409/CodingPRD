"""Multi-hop cascade compliance: acceptance, adjudicated violation and cancellation.

Every test builds its own preconditions from an empty database and sets the
logical clock explicitly, because the server is restarted before each test.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_success,
)

from test_helpers import (
    BUSINESS_AFFAIRS,
    FINANCE_CONTROLLER,
    TALENT_BUYER,
    assert_booking_state,
    expected_adjudicated_risk_score,
    expected_deposit_pct,
    expected_distance_miles,
    expected_draw_penalty,
    expected_strict_risk_score,
    make_artist_rep_headers,
)
from test_helpers import fixtures as fx
from test_helpers.constants import (
    ARTIST_DRAW_SCORE,
    CANONICAL_GUARANTEE_CENTS,
    MARKET_LATITUDE,
    MARKET_LONGITUDE,
    PORTLAND_DISTANCE_MILES,
    PORTLAND_LATITUDE,
    PORTLAND_LONGITUDE,
)
from test_helpers.factories import cancel_payload

OFFER_A_SLOT_UTC = "2026-12-04T21:00:00Z"
OFFER_B_SLOT_UTC = "2026-12-05T21:00:00Z"


# --------------------------------------------------------------- module helpers
def _two_acts_against_a_one_slot_tier(api):
    """Edition whose only tier carries one slot, with two ISSUED offers on it.

    Offer A sits on 2026-12-04 and offer B on 2026-12-05, both at billing
    position 1 on the flagship stage, each at a guarantee of 1800000 cents.
    """
    ctx = fx.single_tier_edition(api, tier_overrides={"max_slots": 1})
    rival = fx.create_artist(
        api, legal_name="Glass Harbor Inc", performing_name="Glass Harbor"
    )
    offer_a = fx.issued_offer(api, ctx, ctx["artist"], slot_start_utc=OFFER_A_SLOT_UTC)
    offer_b = fx.issued_offer(api, ctx, rival, slot_start_utc=OFFER_B_SLOT_UTC)
    return {
        "ctx": ctx,
        "rival": rival,
        "offer_a": offer_a,
        "offer_b": offer_b,
        "clause_a": fx.clause_of_offer(api, offer_a["id"]),
        "clause_b": fx.clause_of_offer(api, offer_b["id"]),
    }


def _accept_offer_a(api, world):
    headers = make_artist_rep_headers(world["ctx"]["artist"]["id"])
    return validate_success(api.accept_offer(world["offer_a"]["id"], headers), 201)


def _booking_with_a_reported_portland_show(api):
    """Accepted booking plus one REPORTED Portland show inside its clause window."""
    ctx = fx.single_tier_edition(api)
    booking = fx.accepted_booking(api, ctx)
    clause = fx.clause_of_booking(api, booking["id"])
    installments = fx.installments_of(api, booking["id"])
    performance = fx.report_performance(api, ctx["artist"]["id"])
    return {
        "ctx": ctx,
        "booking": booking,
        "clause": clause,
        "installments": installments,
        "performance": performance,
    }


def _countersigned_booking_inside_a_locked_wave(api):
    """One countersigned booking assigned to a LOCKED PRESALE wave.

    The tier carries a single slot, so the acceptance closed it and froze the
    edition before the cancellation runs.
    """
    ctx = fx.single_tier_edition(api, tier_overrides={"max_slots": 1})
    settled = fx.countersigned_booking(api, ctx)
    booking = settled["booking"]
    clause = fx.clause_of_booking(api, booking["id"])
    installments = fx.installments_of(api, booking["id"])
    wave = fx.planned_wave(api, ctx["festival"]["id"])
    fx.assign_to_wave(api, wave, booking["id"])
    wave = validate_success(api.lock_wave(wave["id"], BUSINESS_AFFAIRS))
    return {
        "ctx": ctx,
        "booking": booking,
        "clause": clause,
        "installments": installments,
        "wave": wave,
    }


# ------------------------------------------- acceptance commitment cascade
def test_accepting_an_offer_writes_the_booking_and_stamps_its_radius_clause(api):
    """Acceptance flips the offer and opens a booking whose clause is now attached.

    "**Hop one** flips the offer's `status` to `ACCEPTED` and writes a booking."
    "In the same hop the offer's radius clause has its `booking_id` stamped with the new booking's identifier, and its `enforcement_status` moves `PROVISIONAL → ACTIVE` if the clause was not already activated at issuance."
    Design: Difficulty/transitive_cascade/accept_offer_depth5_commitment_cascade
    """
    world = _two_acts_against_a_one_slot_tier(api)

    booking = _accept_offer_a(api, world)

    assert_booking_state(booking, "PENDING_RIDER", "UNFUNDED")
    offer_a = validate_success(api.get_offer(world["offer_a"]["id"], TALENT_BUYER))
    assert offer_a["status"] == "ACCEPTED"
    clause_a = validate_success(
        api.get_radius_clause(world["clause_a"]["id"], BUSINESS_AFFAIRS)
    )
    assert clause_a["enforcement_status"] == "ACTIVE"
    assert clause_a["booking_id"] == booking["id"]


def test_the_new_booking_debits_the_tier_and_the_stage_ledger(api):
    """The booking's guarantee and set length land on the tier and stage ledgers.

    "The tier's `committed_cents` increases by the guarantee plus the production fee and its `slots_committed` increases by one; the stage's `booked_minutes` increases by the booking's `set_length_minutes`."
    Design: Difficulty/transitive_cascade/accept_offer_depth5_commitment_cascade
    """
    world = _two_acts_against_a_one_slot_tier(api)

    _accept_offer_a(api, world)

    tier = validate_success(
        api.get_budget_tier(world["ctx"]["tier"]["id"], TALENT_BUYER)
    )
    assert tier["committed_cents"] == 1800000
    assert tier["slots_committed"] == 1
    stage = validate_success(api.get_stage(world["ctx"]["stage"]["id"], TALENT_BUYER))
    assert stage["booked_minutes"] == 90


def test_the_full_tier_closes_and_freezes_the_edition_posture(api):
    """The debit closes the only tier, which in turn freezes the edition.

    "The tier's `status` is recomputed and flips `OPEN → CLOSED` when `slots_committed` has reached `max_slots` or `committed_cents` has reached `allocation_cents`."
    "The posture reads `FROZEN` when the edition's `announcement_phase` has reached `GA_ONSALE`, or when the committed ratio has reached or passed 1.00, or when the edition has at least one budget tier and every one of them reads `CLOSED`."
    Design: Difficulty/transitive_cascade/accept_offer_depth5_commitment_cascade
    """
    world = _two_acts_against_a_one_slot_tier(api)

    _accept_offer_a(api, world)

    tier = validate_success(
        api.get_budget_tier(world["ctx"]["tier"]["id"], TALENT_BUYER)
    )
    assert tier["status"] == "CLOSED"
    festival = validate_success(
        api.get_festival(world["ctx"]["festival"]["id"], TALENT_BUYER)
    )
    assert festival["committed_budget_cents"] == 1800000
    assert festival["headliner_anchor_count"] == 1
    assert festival["lineup_posture"] == "FROZEN"


def test_the_closed_tier_supersedes_its_sibling_offer_and_releases_its_clause(api):
    """The sibling offer and its clause move although the request never named them.

    "A tier that reached `CLOSED` in hop three drives every other offer of that same tier whose `status` is `DRAFT`, `ISSUED` or `COUNTERED` to `SUPERSEDED`, and each of those offers' clauses moves from `PROVISIONAL` or `ACTIVE` to `RELEASED`."
    Design: Difficulty/transitive_cascade/accept_offer_depth5_commitment_cascade
    """
    world = _two_acts_against_a_one_slot_tier(api)

    _accept_offer_a(api, world)

    offer_b = validate_success(api.get_offer(world["offer_b"]["id"], TALENT_BUYER))
    assert offer_b["status"] == "SUPERSEDED"
    clause_b = validate_success(
        api.get_radius_clause(world["clause_b"]["id"], BUSINESS_AFFAIRS)
    )
    assert clause_b["enforcement_status"] == "RELEASED"


def test_acceptance_builds_a_two_row_deposit_and_balance_schedule(api):
    """125 days out earns the 0.50 deposit and an exact integer complement balance.

    "The deposit percentage is 0.50 when there are at least 120 days to go — exactly 120 days still earns 0.50 — 0.40 when there are at least 60 but fewer than 120, and 0.25 when there are fewer than 60."
    "The deposit's `amount_cents` is the booking's `guarantee_cents` multiplied by that percentage and rounded half up once; the balance's `amount_cents` is the guarantee less the deposit, taken as an exact integer complement and never independently rounded, so the pair always sums back to the guarantee."
    "The deposit's `due_date` is the later of today's date and the earlier of two candidates: today plus 30 days, and the edition's `event_start_date` less 14 days."
    Design: Difficulty/transitive_cascade/accept_offer_depth5_commitment_cascade
    """
    world = _two_acts_against_a_one_slot_tier(api)

    booking = _accept_offer_a(api, world)

    installments = fx.installments_of(api, booking["id"])
    assert set(installments) == {"DEPOSIT", "BALANCE"}
    deposit, balance = installments["DEPOSIT"], installments["BALANCE"]
    assert expected_deposit_pct(125) == 0.50
    assert deposit["amount_cents"] == 900000
    assert balance["amount_cents"] == 900000
    assert deposit["amount_cents"] + balance["amount_cents"] == CANONICAL_GUARANTEE_CENTS
    assert deposit["due_date"] == "2026-08-31"
    assert deposit["status"] == "SCHEDULED"
    assert balance["status"] == "SCHEDULED"


def test_accepting_a_superseded_offer_is_refused_as_terminal(api):
    """The overtaken offer cannot be revived, so the cascade cannot be replayed.

    "`ACCEPTED`, `DECLINED`, `EXPIRED` and `SUPERSEDED` are all terminal: a further negotiation call against any of them is `ERR_OFFER_NOT_NEGOTIABLE`, which is also what a repeat call on an already-transitioned offer returns."
    Design: Difficulty/transitive_cascade/accept_offer_depth5_commitment_cascade
    """
    world = _two_acts_against_a_one_slot_tier(api)
    _accept_offer_a(api, world)

    rival_headers = make_artist_rep_headers(world["rival"]["id"])
    validate_error(
        api.accept_offer(world["offer_b"]["id"], rival_headers),
        "ERR_OFFER_NOT_NEGOTIABLE",
        409,
    )


# ------------------------------------------------ adjudicated enforcement cascade
def test_a_violation_finding_moves_the_report_and_the_acts_risk_scores(api):
    """The finding re-derives both counts and both risk variants for the act.

    "Hop one moves `status` `REPORTED → VIOLATION`, re-derives the act's `radius_breach_count` and `reported_conflict_count`, and recomputes both risk-score variants — which is how a single violation can push an act's `adjudicated_risk_score` to 60 and lock it out of further offers."
    "The draw penalty is 0.20 multiplied by the difference between 100 and the act's `draw_score`, rounded half up to a whole number of points — so a low-draw act carries a structural penalty of up to twenty points on its own."
    Design: Difficulty/transitive_cascade/violation_adjudication_depth4_enforcement_cascade
    """
    world = _booking_with_a_reported_portland_show(api)

    performance = fx.adjudicate(
        api,
        world["performance"]["id"],
        "VIOLATION",
        "Portland headline date inside the Seattle radius window",
    )

    assert performance["status"] == "VIOLATION"
    artist = validate_success(
        api.get_artist(world["ctx"]["artist"]["id"], TALENT_BUYER)
    )
    assert artist["radius_breach_count"] == 1
    assert artist["reported_conflict_count"] == 0
    assert expected_draw_penalty(ARTIST_DRAW_SCORE) == 6
    assert artist["strict_risk_score"] == 31
    assert artist["adjudicated_risk_score"] == 31
    assert artist["strict_risk_score"] == expected_strict_risk_score(
        0, 1, ARTIST_DRAW_SCORE
    )
    assert artist["adjudicated_risk_score"] == expected_adjudicated_risk_score(
        1, ARTIST_DRAW_SCORE
    )


def test_the_violation_breaches_the_conflicting_clause(api):
    """The clause named by the detector breaches although the request never named it.

    "Hop two drives the conflicting clause `ACTIVE → BREACHED` and increases that clause's `breach_count` by one."
    Design: Difficulty/transitive_cascade/violation_adjudication_depth4_enforcement_cascade
    """
    world = _booking_with_a_reported_portland_show(api)

    fx.adjudicate(api, world["performance"]["id"], "VIOLATION", "Inside the window")

    clause = validate_success(
        api.get_radius_clause(world["clause"]["id"], BUSINESS_AFFAIRS)
    )
    assert clause["enforcement_status"] == "BREACHED"
    assert clause["breach_count"] == 1


def test_the_breach_holds_every_scheduled_installment_of_the_booking(api):
    """Both scheduled installments are held by the breach two hops upstream.

    "Hop three moves every payment installment of the clause's booking whose `status` is `SCHEDULED` to `HELD`."
    Design: Difficulty/transitive_cascade/violation_adjudication_depth4_enforcement_cascade
    """
    world = _booking_with_a_reported_portland_show(api)

    fx.adjudicate(api, world["performance"]["id"], "VIOLATION", "Inside the window")

    for installment_type in ("DEPOSIT", "BALANCE"):
        row = validate_success(
            api.get_payment_installment(
                world["installments"][installment_type]["id"], FINANCE_CONTROLLER
            )
        )
        assert row["status"] == "HELD", installment_type


def test_the_held_money_withholds_the_bookings_settlement_dimension(api):
    """The money dimension goes to WITHHELD while the contract dimension stands still.

    "Hop four sets that booking's `settlement_status` to `WITHHELD` from whichever of `UNFUNDED`, `DEPOSIT_PAID` or `BALANCE_DUE` it was in."
    Design: Difficulty/transitive_cascade/violation_adjudication_depth4_enforcement_cascade
    """
    world = _booking_with_a_reported_portland_show(api)

    fx.adjudicate(api, world["performance"]["id"], "VIOLATION", "Inside the window")

    booking = validate_success(api.get_booking(world["booking"]["id"], TALENT_BUYER))
    assert_booking_state(booking, "PENDING_RIDER", "WITHHELD")


def test_the_report_records_the_winning_clause_and_its_market_distance(api):
    """Detection stamps the winning clause and the distance to its market.

    "Otherwise the candidates are ranked by `radius_miles` descending, then `window_start_date` ascending, then `created_at` ascending, and the first is the winner: `conflict_assessment` becomes `CONFLICT`, `conflicting_radius_clause_id` names the winning clause, and `distance_to_market_miles` records the distance to that winner's market, rounded half up to two decimals."
    Design: Difficulty/transitive_cascade/violation_adjudication_depth4_enforcement_cascade
    """
    world = _booking_with_a_reported_portland_show(api)

    performance = validate_success(
        api.get_competing_performance(world["performance"]["id"], BUSINESS_AFFAIRS)
    )

    assert performance["conflict_assessment"] == "CONFLICT"
    assert performance["conflicting_radius_clause_id"] == world["clause"]["id"]
    assert performance["distance_to_market_miles"] == PORTLAND_DISTANCE_MILES
    assert performance["distance_to_market_miles"] == expected_distance_miles(
        MARKET_LATITUDE, MARKET_LONGITUDE, PORTLAND_LATITUDE, PORTLAND_LONGITUDE
    )


def test_a_second_adjudication_of_the_same_report_is_refused(api):
    """The enforcement cascade cannot be replayed against the same report.

    "Adjudication is `BusinessAffairs`'s call, takes a `finding` and an optional `finding_note`, and requires the report to still be `REPORTED` — a second adjudication is `ERR_PERFORMANCE_ALREADY_ADJUDICATED`."
    Design: Difficulty/transitive_cascade/violation_adjudication_depth4_enforcement_cascade
    """
    world = _booking_with_a_reported_portland_show(api)
    fx.adjudicate(api, world["performance"]["id"], "VIOLATION", "Inside the window")

    validate_error(
        api.adjudicate_performance(
            world["performance"]["id"], {"finding": "VIOLATION"}, BUSINESS_AFFAIRS
        ),
        "ERR_PERFORMANCE_ALREADY_ADJUDICATED",
        409,
    )


# --------------------------------------------------- cancellation release cascade
def test_cancelling_stamps_the_clock_and_computes_no_promoter_recovery(api):
    """A promoter cancellation recovers nothing, so the contractual figure is zero.

    "Hop one sets `contract_status` to `CANCELLED`, stamps `cancelled_at` from the logical clock, records `cancellation_reason` and `cancelling_party`, and computes the contractual recovery figure."
    "The party percentage is 1.00 when `cancelling_party` is `ARTIST`, 0.50 when it is `FORCE_MAJEURE`, and 0.00 when it is `PROMOTER` — a promoter who walks away recovers no deposit."
    Design: Difficulty/transitive_cascade/cancel_booking_depth4_release_cascade
    """
    world = _countersigned_booking_inside_a_locked_wave(api)

    booking = validate_success(
        api.cancel_booking(world["booking"]["id"], cancel_payload(), BUSINESS_AFFAIRS)
    )

    assert booking["contract_status"] == "CANCELLED"
    assert booking["cancelling_party"] == "PROMOTER"
    assert booking["cancelled_at"].startswith("2026-08-01T00:00:00")
    assert booking["contractual_recovery_cents"] == 0


def test_cancelling_unwinds_the_ledgers_voids_the_money_and_releases_the_clause(api):
    """Every debit the acceptance made is credited back inside the same request.

    "Hop two unwinds everything the acceptance did: the tier's `committed_cents` is reduced by the booking's `guarantee_cents` plus `production_fee_cents` and its `slots_committed` by one, the stage's `booked_minutes` is reduced by the booking's `set_length_minutes`, every installment whose `status` is `SCHEDULED`, `HELD` or `RELEASED` becomes `VOIDED` — none of those ever moved cash — every installment whose `status` is `PAID` becomes `CLAWBACK_PENDING`, and the booking's radius clause is released."
    Design: Difficulty/transitive_cascade/cancel_booking_depth4_release_cascade
    """
    world = _countersigned_booking_inside_a_locked_wave(api)

    validate_success(
        api.cancel_booking(world["booking"]["id"], cancel_payload(), BUSINESS_AFFAIRS)
    )

    tier = validate_success(
        api.get_budget_tier(world["ctx"]["tier"]["id"], TALENT_BUYER)
    )
    assert tier["committed_cents"] == 0
    assert tier["slots_committed"] == 0
    stage = validate_success(api.get_stage(world["ctx"]["stage"]["id"], TALENT_BUYER))
    assert stage["booked_minutes"] == 0
    for installment_type in ("DEPOSIT", "BALANCE"):
        row = validate_success(
            api.get_payment_installment(
                world["installments"][installment_type]["id"], FINANCE_CONTROLLER
            )
        )
        assert row["status"] == "VOIDED", installment_type
    clause = validate_success(
        api.get_radius_clause(world["clause"]["id"], BUSINESS_AFFAIRS)
    )
    assert clause["enforcement_status"] == "RELEASED"


def test_the_credited_tier_reopens_and_the_edition_posture_reverts(api):
    """The credit reopens the tier, thaws the edition and settles the money dimension.

    "Hop three re-derives what those ledgers feed: the tier's `status` flips `CLOSED → OPEN` when its `slots_committed` has fallen below `max_slots` and its `committed_cents` below its `allocation_cents`, the edition's `committed_budget_cents` and `headliner_anchor_count` are credited back and `lineup_posture` is re-derived — so a `FROZEN` edition can revert to `RESTRICTED` or `OPEN`."
    "Independently in the same hop, the installment flags decide the money dimension: `settlement_status` becomes `RECOVERY_PENDING` when at least one installment is now `CLAWBACK_PENDING`, and otherwise becomes `RECOVERED` with `actual_recovered_cents` at 0."
    Design: Difficulty/transitive_cascade/cancel_booking_depth4_release_cascade
    """
    world = _countersigned_booking_inside_a_locked_wave(api)
    frozen = validate_success(
        api.get_festival(world["ctx"]["festival"]["id"], TALENT_BUYER)
    )
    assert frozen["lineup_posture"] == "FROZEN"

    validate_success(
        api.cancel_booking(world["booking"]["id"], cancel_payload(), BUSINESS_AFFAIRS)
    )

    tier = validate_success(
        api.get_budget_tier(world["ctx"]["tier"]["id"], TALENT_BUYER)
    )
    assert tier["status"] == "OPEN"
    festival = validate_success(
        api.get_festival(world["ctx"]["festival"]["id"], TALENT_BUYER)
    )
    assert festival["committed_budget_cents"] == 0
    assert festival["headliner_anchor_count"] == 0
    assert festival["lineup_posture"] == "OPEN"
    booking = validate_success(api.get_booking(world["booking"]["id"], TALENT_BUYER))
    assert booking["settlement_status"] == "RECOVERED"
    assert booking["actual_recovered_cents"] == 0


def test_the_emptied_locked_wave_reverts_to_planning(api):
    """The booking's departure empties the wave, which falls back to planning.

    "Hop four removes the booking from its announcement wave, decrementing that wave's `assignment_count` and, for a top-billed booking, its `headliner_count`; a wave whose `assignment_count` reaches 0 while it is `LOCKED` reverts `LOCKED → PLANNED`, with its `headliner_count` re-derived to 0."
    Design: Difficulty/transitive_cascade/cancel_booking_depth4_release_cascade
    """
    world = _countersigned_booking_inside_a_locked_wave(api)
    assert world["wave"]["status"] == "LOCKED"

    validate_success(
        api.cancel_booking(world["booking"]["id"], cancel_payload(), BUSINESS_AFFAIRS)
    )

    wave = validate_success(
        api.get_announcement_wave(world["wave"]["id"], TALENT_BUYER)
    )
    assert wave["assignment_count"] == 0
    assert wave["headliner_count"] == 0
    assert wave["status"] == "PLANNED"


def test_the_committed_budget_reconciles_to_zero_after_the_cancellation(api):
    """All three committed expressions agree at zero once the booking is cancelled.

    "A festival's `committed_budget_cents` must always equal the sum of `committed_cents` across that festival's budget tiers, and must equally always equal the sum of `guarantee_cents` plus `production_fee_cents` over that festival's bookings whose `contract_status` is anything other than `CANCELLED`."
    Design: Difficulty/transitive_cascade/cancel_booking_depth4_release_cascade
    """
    world = _countersigned_booking_inside_a_locked_wave(api)

    validate_success(
        api.cancel_booking(world["booking"]["id"], cancel_payload(), BUSINESS_AFFAIRS)
    )

    summary = validate_success(
        api.get_budget_summary(world["ctx"]["festival"]["id"], TALENT_BUYER)
    )
    assert summary["committed_budget_cents"] == 0
    assert summary["tier_committed_sum_cents"] == 0
    assert summary["booking_committed_sum_cents"] == 0


def test_locking_the_reverted_wave_is_refused_as_empty(api):
    """The wave really is back in planning with nothing left to announce.

    "It requires the wave to be `PLANNED`, requires `assignment_count` to be at least 1 — a wave with nothing in it is rejected with `ERR_EMPTY_WAVE` rather than locking vacuously, and a single assignment is enough — requires every booking assigned to the wave whose `contract_status` is not `CANCELLED` to have reached `COUNTERSIGNED`, failing which the answer is `ERR_WAVE_BOOKING_NOT_COUNTERSIGNED`, requires the wave's `phase` to equal the edition's current `announcement_phase`, and requires the reveal instant to still precede the event start."
    Design: Difficulty/transitive_cascade/cancel_booking_depth4_release_cascade
    """
    world = _countersigned_booking_inside_a_locked_wave(api)
    validate_success(
        api.cancel_booking(world["booking"]["id"], cancel_payload(), BUSINESS_AFFAIRS)
    )

    validate_error(
        api.lock_wave(world["wave"]["id"], BUSINESS_AFFAIRS), "ERR_EMPTY_WAVE", 409
    )
