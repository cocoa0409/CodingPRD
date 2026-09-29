"""Gates that fire because of a sibling or parent entity's state.

Every test below builds its own preconditions from an empty database, because
the server is restarted before each test.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    BUSINESS_AFFAIRS,
    FINANCE_CONTROLLER,
    PRODUCTION_MANAGER,
    TALENT_BUYER,
    expected_settlement_total_cents,
    make_artist_rep_headers,
)
from test_helpers import fixtures as fx

CLOCK_AT_PLANNING = "2026-08-01T00:00:00Z"
CLOCK_AT_DEPOSIT_RELEASE = "2026-08-24T00:00:00Z"


# --------------------------------------------------------------------------
# An edition whose single tier can be exhausted to the cent by three accepts.
# --------------------------------------------------------------------------
def _exhaustible_edition(api):
    fx.set_clock(api, CLOCK_AT_PLANNING)
    festival = fx.create_festival(
        api, talent_budget_cents=5000000, contingency_reserve_pct=0.00
    )
    tier = fx.create_tier(
        api,
        festival["id"],
        tier_code="HEADLINER",
        tier_rank=1,
        allocation_pct=1.00,
        max_slots=3,
        genre_focus="MIXED",
    )
    fx.allocate(api, festival)
    stage = fx.create_stage(api, festival["id"])
    electronic = fx.create_artist(
        api,
        legal_name="Nova Kade LLC",
        performing_name="Nova Kade",
        primary_genre="ELECTRONIC",
        agency="Meridian Talent",
        draw_score=80,
        default_radius_miles=120,
    )
    hip_hop = fx.create_artist(
        api,
        legal_name="Cass Meridian LLC",
        performing_name="Cass Meridian",
        primary_genre="HIP_HOP",
        agency="Foghorn Agency",
        draw_score=80,
        default_radius_miles=120,
    )
    rock = fx.create_artist(
        api,
        legal_name="Ironvale LLC",
        performing_name="Ironvale",
        primary_genre="ROCK",
        agency="Foghorn Agency",
        draw_score=40,
        default_radius_miles=120,
    )
    ctx = {"festival": festival, "tier": tier, "stage": stage, "artist": electronic}

    def issue(artist, guarantee_cents, slot_start_utc):
        offer = fx.draft_offer(
            api,
            ctx,
            artist,
            guarantee_cents=guarantee_cents,
            production_fee_cents=0,
            billing_position=1,
            slot_start_utc=slot_start_utc,
            radius_miles=120,
            window_start_date="2026-11-04",
            window_end_date="2026-12-14",
        )
        return validate_success(api.issue_offer(offer["id"], TALENT_BUYER))

    offers = [
        issue(electronic, 2000000, "2026-12-04T21:00:00Z"),
        issue(hip_hop, 2000000, "2026-12-05T21:00:00Z"),
        issue(rock, 1000000, "2026-12-06T21:00:00Z"),
    ]
    return {
        "festival": festival,
        "tier": tier,
        "stage": stage,
        "artists": [electronic, hip_hop, rock],
        "offers": offers,
    }


def _accept(api, offer, artist):
    return validate_success(
        api.accept_offer(offer["id"], make_artist_rep_headers(artist["id"])), 201
    )


def test_two_accepts_leave_the_edition_open_below_the_restricted_ratio(api):
    """Four fifths of the allocatable budget committed keeps the posture OPEN.

    "`lineup_posture` is derived from the committed ratio — `committed_budget_cents` divided by `allocatable_budget_cents`, compared as an exact rational value and never rounded or stored."
    "It reads `RESTRICTED` when the committed ratio has reached 0.85 but is still below 1.00 — so a ratio of exactly 0.85 is `RESTRICTED` and a ratio of exactly 1.00 is `FROZEN`."
    "Otherwise it reads `OPEN`."

    Design: Difficulty/cross_entity_state_dependency/offer_issuance_blocked_by_frozen_parent_festival
    """
    ctx = _exhaustible_edition(api)
    _accept(api, ctx["offers"][0], ctx["artists"][0])
    _accept(api, ctx["offers"][1], ctx["artists"][1])

    festival = validate_success(api.get_festival(ctx["festival"]["id"], TALENT_BUYER))
    assert festival["committed_budget_cents"] == 4000000
    assert festival["lineup_posture"] == "OPEN"


def test_the_accept_that_exhausts_the_allocation_freezes_the_edition(api):
    """The third accept takes the committed ratio to exactly 1.00.

    "The posture reads `FROZEN` when the edition's `announcement_phase` has reached `GA_ONSALE`, or when the committed ratio has reached or passed 1.00, or when the edition has at least one budget tier and every one of them reads `CLOSED`."
    "It reads `CLOSED` once its `slots_committed` has reached its `max_slots`, or once its `committed_cents` has reached or passed its `allocation_cents`; otherwise it reads `OPEN`."

    Design: Difficulty/cross_entity_state_dependency/offer_issuance_blocked_by_frozen_parent_festival
    """
    ctx = _exhaustible_edition(api)
    _accept(api, ctx["offers"][0], ctx["artists"][0])
    _accept(api, ctx["offers"][1], ctx["artists"][1])
    _accept(api, ctx["offers"][2], ctx["artists"][2])

    festival = validate_success(api.get_festival(ctx["festival"]["id"], TALENT_BUYER))
    assert festival["committed_budget_cents"] == 5000000
    assert festival["lineup_posture"] == "FROZEN"

    tier = validate_success(api.get_budget_tier(ctx["tier"]["id"], TALENT_BUYER))
    assert tier["slots_committed"] == 3
    assert tier["status"] == "CLOSED"


# --------------------------------------------------------------------------
# A released deposit sitting behind a breached radius clause.
# --------------------------------------------------------------------------
def _released_deposit_behind_a_breach(api):
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

    booking = fx.accepted_booking(api, ctx, artist)
    clause = fx.clause_of_booking(api, booking["id"])
    installments = fx.installments_of(api, booking["id"])

    fx.set_clock(api, CLOCK_AT_DEPOSIT_RELEASE)
    validate_success(
        api.release_installment(installments["DEPOSIT"]["id"], FINANCE_CONTROLLER)
    )

    performance = fx.report_performance(api, artist["id"], performance_date="2026-11-20")
    fx.adjudicate(api, performance["id"], "VIOLATION", "Inside the radius window")

    return {
        "festival": festival,
        "tier": tier,
        "artist": artist,
        "booking": booking,
        "clause": clause,
        "deposit": installments["DEPOSIT"],
        "balance": installments["BALANCE"],
        "performance": performance,
    }


def _grant_the_waiver(api, state):
    artist_headers = make_artist_rep_headers(state["artist"]["id"])
    validate_success(
        api.request_waiver(
            state["clause"]["id"],
            {
                "competing_performance_id": state["performance"]["id"],
                "waiver_fee_offer_cents": 250000,
                "request_note": "One-off support slot",
            },
            artist_headers,
        )
    )
    return validate_success(
        api.decide_waiver(
            state["clause"]["id"],
            {
                "decision": "GRANTED",
                "waiver_fee_cents": 250000,
                "decision_note": "Priced at the artist's own offer",
            },
            BUSINESS_AFFAIRS,
        )
    )


def test_recording_the_deposit_wire_is_refused_while_the_clause_is_breached(api):
    """The installment itself is a perfectly payable RELEASED row.

    "While a booking is `WITHHELD`, no money may leave: an attempt to release an installment is refused with `ERR_RADIUS_BREACH_ACTIVE`, and so is a countersignature attempt or an attempt to record payment."
    "Recording the wire moves a `RELEASED` installment to `PAID`, with `paid_at` stamped from the logical clock and the supplied `paid_amount_cents` stored — it equals the installment's `amount_cents`."

    Design: Difficulty/cross_entity_state_dependency/installment_payment_blocked_by_breached_clause
    """
    state = _released_deposit_behind_a_breach(api)

    clause = validate_success(
        api.get_radius_clause(state["clause"]["id"], BUSINESS_AFFAIRS)
    )
    assert clause["enforcement_status"] == "BREACHED"

    validate_error(
        api.mark_installment_paid(
            state["deposit"]["id"], {"paid_amount_cents": 900000}, FINANCE_CONTROLLER
        ),
        "ERR_RADIUS_BREACH_ACTIVE",
        409,
    )

    deposit = validate_success(
        api.get_payment_installment(state["deposit"]["id"], FINANCE_CONTROLLER)
    )
    assert deposit["status"] == "RELEASED"
    assert deposit["paid_at"] is None
    assert deposit["paid_amount_cents"] == 0


def test_granting_the_waiver_lifts_the_breach_and_unholds_the_balance(api):
    """The waiver cascade moves the clause, the report and the held money.

    "The clause's `waiver_status` becomes `GRANTED` and its `enforcement_status` moves `BREACHED → WAIVED`, with the decided fee stored in `waiver_fee_cents`."
    "The named competing performance moves `VIOLATION → WAIVED`, which re-derives the act's `radius_breach_count` and recomputes both risk-score variants, so the act's `adjudicated_risk_score` falls."
    "Every installment of the booking whose `status` is `HELD` returns to `SCHEDULED`."

    Design: Difficulty/cross_entity_state_dependency/installment_payment_blocked_by_breached_clause
    """
    state = _released_deposit_behind_a_breach(api)
    held_balance = validate_success(
        api.get_payment_installment(state["balance"]["id"], FINANCE_CONTROLLER)
    )
    assert held_balance["status"] == "HELD"

    clause = _grant_the_waiver(api, state)
    assert clause["enforcement_status"] == "WAIVED"
    assert clause["waiver_status"] == "GRANTED"
    assert clause["waiver_fee_cents"] == 250000

    performance = validate_success(
        api.get_competing_performance(state["performance"]["id"], BUSINESS_AFFAIRS)
    )
    assert performance["status"] == "WAIVED"

    balance = validate_success(
        api.get_payment_installment(state["balance"]["id"], FINANCE_CONTROLLER)
    )
    assert balance["status"] == "SCHEDULED"


def test_the_identical_deposit_wire_records_once_the_waiver_is_granted(api):
    """Nothing about the installment changed — only the sibling clause did.

    "A deposit payment recomputes the booking's `deposit_paid_cents`, defined as the sum of `paid_amount_cents` over that booking's deposit installments whose `status` is `PAID`, `CLAWBACK_PENDING` or `RECOVERED`, and moves the booking's `settlement_status` `UNFUNDED → DEPOSIT_PAID`."
    "The order is: take the booking's `rider_estimate_cents`, which is the contracted-scope rider total; take the `waiver_fee_cents` of the booking's clause, or 0 when the booking has no clause row; form the pre-share gross as `guarantee_cents` plus that rider figure plus that waiver fee, using the **unadjusted** rider on purpose; select the promoter share from that pre-share gross — 0.60 when the gross has reached 5000000 cents (fifty thousand dollars), 0.75 when it has reached 2000000 cents (twenty thousand dollars) but is below the higher bracket, and 0.90 when it is below 2000000 cents; compute the reimbursed rider as the rider figure multiplied by that share, rounded half up once; and finally set `settlement_total_cents` to `guarantee_cents` plus the reimbursed rider plus the waiver fee, less `deposit_paid_cents`."

    Design: Difficulty/cross_entity_state_dependency/installment_payment_blocked_by_breached_clause
    """
    state = _released_deposit_behind_a_breach(api)
    validate_error(
        api.mark_installment_paid(
            state["deposit"]["id"], {"paid_amount_cents": 900000}, FINANCE_CONTROLLER
        ),
        "ERR_RADIUS_BREACH_ACTIVE",
        409,
    )
    _grant_the_waiver(api, state)

    deposit = validate_success(
        api.mark_installment_paid(
            state["deposit"]["id"], {"paid_amount_cents": 900000}, FINANCE_CONTROLLER
        )
    )
    assert deposit["status"] == "PAID"
    assert deposit["paid_amount_cents"] == 900000

    booking = validate_success(api.get_booking(state["booking"]["id"], TALENT_BUYER))
    assert booking["deposit_paid_cents"] == 900000
    assert booking["settlement_total_cents"] == 1150000
    assert booking["settlement_total_cents"] == expected_settlement_total_cents(
        1800000, 0, 250000, 900000
    )


# --------------------------------------------------------------------------
# A wave whose own row is valid but one member booking is not executed.
# --------------------------------------------------------------------------
def _wave_holding_one_countersigned_member(api):
    fx.set_clock(api, CLOCK_AT_PLANNING)
    festival = fx.create_festival(api)
    tier = fx.create_tier(
        api,
        festival["id"],
        tier_code="HEADLINER",
        tier_rank=1,
        allocation_pct=1.00,
        max_slots=2,
        genre_focus="ELECTRONIC",
    )
    fx.allocate(api, festival)
    stage = fx.create_stage(api, festival["id"])
    artist_one = fx.create_artist(api)
    artist_two = fx.create_artist(
        api,
        legal_name="Glass Harbor Inc",
        performing_name="Glass Harbor",
        primary_genre="ELECTRONIC",
        agency="Meridian Talent",
        draw_score=72,
        default_radius_miles=150,
    )
    ctx = {"festival": festival, "tier": tier, "stage": stage, "artist": artist_one}

    executed = fx.countersigned_booking(
        api, ctx, artist_one, unit_cost_cents=100000, slot_start_utc="2026-12-04T21:00:00Z"
    )
    settled = fx.rider_settled_booking(
        api, ctx, artist_two, unit_cost_cents=90000, slot_start_utc="2026-12-05T21:00:00Z"
    )

    wave = fx.planned_wave(
        api,
        festival["id"],
        wave_number=1,
        phase="PRESALE",
        scheduled_reveal_utc="2026-09-20T17:00:00Z",
    )
    wave_at_creation = dict(wave)
    wave = fx.assign_to_wave(api, wave, executed["booking"]["id"])
    wave = validate_success(api.get_announcement_wave(wave["id"], TALENT_BUYER))

    return {
        "festival": festival,
        "artist_two": artist_two,
        "countersigned": executed["booking"],
        "rider_settled": settled["booking"],
        "wave": wave,
        "wave_at_creation": wave_at_creation,
    }


def _assign(api, wave, booking_id):
    return api.assign_booking_to_wave(
        wave["id"],
        {"booking_id": booking_id, "expected_announcement_wave_version": wave["version"]},
        TALENT_BUYER,
    )


def _countersign_the_second_member(api, state):
    booking_id = state["rider_settled"]["id"]
    fx.approved_advance_packet(
        api,
        booking_id,
        state["artist_two"]["id"],
        stage_plot_ref="PLOT-GH-01",
        input_channel_count=40,
        monitor_mix_count=6,
        travel_party_size=9,
        load_in_offset_minutes=180,
    )
    return validate_success(api.countersign_booking(booking_id, BUSINESS_AFFAIRS))


def test_locking_is_refused_while_one_member_booking_is_only_rider_settled(api):
    """Two assignments satisfy the emptiness rule, so only the member state blocks.

    "It requires the wave to be `PLANNED`, requires `assignment_count` to be at least 1 — a wave with nothing in it is rejected with `ERR_EMPTY_WAVE` rather than locking vacuously, and a single assignment is enough — requires every booking assigned to the wave whose `contract_status` is not `CANCELLED` to have reached `COUNTERSIGNED`, failing which the answer is `ERR_WAVE_BOOKING_NOT_COUNTERSIGNED`, requires the wave's `phase` to equal the edition's current `announcement_phase`, and requires the reveal instant to still precede the event start."

    Design: Difficulty/cross_entity_state_dependency/wave_lock_blocked_by_uncountersigned_member_booking
    """
    state = _wave_holding_one_countersigned_member(api)
    wave = validate_success(_assign(api, state["wave"], state["rider_settled"]["id"]))
    assert wave["assignment_count"] == 2

    validate_error(
        api.lock_wave(wave["id"], BUSINESS_AFFAIRS),
        "ERR_WAVE_BOOKING_NOT_COUNTERSIGNED",
        409,
    )

    after = validate_success(api.get_announcement_wave(wave["id"], TALENT_BUYER))
    assert after["status"] == "PLANNED"
    assert after["assignment_count"] == 2
    assert after["version"] == wave["version"]

    for booking_id in (state["countersigned"]["id"], state["rider_settled"]["id"]):
        booking = validate_success(api.get_booking(booking_id, TALENT_BUYER))
        assert booking["announcement_wave_id"] == wave["id"]


def test_the_second_assignment_needs_the_version_the_first_assignment_advanced(api):
    """The wave's counters moved on the first assignment, so its version did too.

    "Assigning a booking into an announcement wave requires `expected_announcement_wave_version` to match the target wave's `version`."
    "A mismatch is rejected with `ERR_STALE_WAVE_VERSION` (HTTP 412)."

    Design: Difficulty/cross_entity_state_dependency/wave_lock_blocked_by_uncountersigned_member_booking
    """
    state = _wave_holding_one_countersigned_member(api)
    assert state["wave"]["version"] > state["wave_at_creation"]["version"]

    validate_error(
        _assign(api, state["wave_at_creation"], state["rider_settled"]["id"]),
        "ERR_STALE_WAVE_VERSION",
        412,
    )

    wave = validate_success(_assign(api, state["wave"], state["rider_settled"]["id"]))
    assert wave["assignment_count"] == 2


def test_locking_succeeds_once_every_member_booking_is_countersigned(api):
    """Nothing about the wave changed between the refusal and the success.

    "Both counters are aggregates: `assignment_count` is the count of bookings carrying this `announcement_wave_id` whose `contract_status` is not `CANCELLED`, and `headliner_count` is the count of those whose `billing_position` is 1."

    Design: Difficulty/cross_entity_state_dependency/wave_lock_blocked_by_uncountersigned_member_booking
    """
    state = _wave_holding_one_countersigned_member(api)
    wave = validate_success(_assign(api, state["wave"], state["rider_settled"]["id"]))
    validate_error(
        api.lock_wave(wave["id"], BUSINESS_AFFAIRS),
        "ERR_WAVE_BOOKING_NOT_COUNTERSIGNED",
        409,
    )

    executed = _countersign_the_second_member(api, state)
    assert executed["contract_status"] == "COUNTERSIGNED"

    locked = validate_success(api.lock_wave(wave["id"], BUSINESS_AFFAIRS))
    assert locked["status"] == "LOCKED"
    assert locked["assignment_count"] == 2
    assert locked["headliner_count"] == 2
