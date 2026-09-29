"""Endpoint behaviour compliance: computed reads, bulk actions, links and lists.

Every test builds its own world from an empty database and sets the logical
clock explicitly whenever a temporal rule is in play.
"""

from datetime import datetime

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
    make_artist_rep_headers,
)
from test_helpers import fixtures as fx
from test_helpers.constants import DEFAULT_CLOCK_UTC
from test_helpers.factories import advance_packet_payload, offer_payload


# --------------------------------------------------------------- local builders
def _parse_instant(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _same_instant(actual: str, expected: str) -> bool:
    """Compare two ISO 8601 UTC instants without pinning their rendering."""
    return _parse_instant(actual) == _parse_instant(expected)


def _canonical_edition(api, clock: str = DEFAULT_CLOCK_UTC) -> dict:
    """Harbor Lights 2026 with three allocated tiers, a flagship stage and one act.

    Returns a context whose `tier` key is the HEADLINER tier, so the shared
    offer builders can draft against it directly.
    """
    fx.set_clock(api, clock)
    festival = fx.create_festival(api)
    headliner = fx.create_tier(
        api,
        festival["id"],
        tier_code="HEADLINER",
        tier_rank=1,
        allocation_pct=0.5,
        max_slots=5,
        genre_focus="MIXED",
    )
    mid_card = fx.create_tier(
        api,
        festival["id"],
        tier_code="MID_CARD",
        tier_rank=2,
        allocation_pct=0.3,
        max_slots=5,
        genre_focus="MIXED",
    )
    emerging = fx.create_tier(
        api,
        festival["id"],
        tier_code="EMERGING",
        tier_rank=3,
        allocation_pct=0.2,
        max_slots=5,
        genre_focus="MIXED",
    )
    fx.allocate(api, festival)
    stage = fx.create_stage(api, festival["id"])
    artist = fx.create_artist(api)
    return {
        "festival": validate_success(api.get_festival(festival["id"], TALENT_BUYER)),
        "tier": validate_success(api.get_budget_tier(headliner["id"], TALENT_BUYER)),
        "mid_card": validate_success(api.get_budget_tier(mid_card["id"], TALENT_BUYER)),
        "emerging": validate_success(api.get_budget_tier(emerging["id"], TALENT_BUYER)),
        "stage": stage,
        "artist": artist,
        "artist_headers": make_artist_rep_headers(artist["id"]),
    }


def _vela_roan(api, **overrides) -> dict:
    return fx.create_artist(
        api,
        legal_name="Vela Roan Touring Ltd",
        performing_name="Vela Roan",
        primary_genre="ROCK",
        **overrides,
    )


def _issue(api, festival_id: str, artist_id: str, tier_id: str, stage_id: str, **overrides):
    offer = validate_success(
        api.create_offer(
            offer_payload(festival_id, artist_id, tier_id, stage_id, **overrides),
            TALENT_BUYER,
        ),
        201,
    )
    return validate_success(api.issue_offer(offer["id"], TALENT_BUYER))


# --------------------------------------------------------------------- tests
def test_the_budget_summary_reconciles_the_ledger_after_a_tier_closes(api):
    """The computed reconciliation agrees with the tier and booking ledgers at once.

    "It reports `allocatable_budget_cents`, `committed_budget_cents`, `tier_committed_sum_cents`, `booking_committed_sum_cents`, `committed_ratio`, `lineup_posture`, `open_tier_count`, `closed_tier_count` and `headliner_anchor_count`, and asserts that the three committed figures agree."
    "It reads `CLOSED` once its `slots_committed` has reached its `max_slots`, or once its `committed_cents` has reached or passed its `allocation_cents`; otherwise it reads `OPEN`."
    "A tier that reached `CLOSED` in hop three drives every other offer of that same tier whose `status` is `DRAFT`, `ISSUED` or `COUNTERED` to `SUPERSEDED`, and each of those offers' clauses moves from `PROVISIONAL` or `ACTIVE` to `RELEASED`."

    Design: Corner/endpoints/budget_summary_computed_read_reconciles_ledgers_after_a_tier_closes
    """
    fx.set_clock(api, DEFAULT_CLOCK_UTC)
    festival = fx.create_festival(
        api, talent_budget_cents=4000000, contingency_reserve_pct=0.0
    )
    tier_h = fx.create_tier(
        api,
        festival["id"],
        tier_code="HEADLINER",
        tier_rank=1,
        allocation_pct=0.5,
        max_slots=1,
        genre_focus="MIXED",
    )
    fx.create_tier(
        api,
        festival["id"],
        tier_code="MID_CARD",
        tier_rank=2,
        allocation_pct=0.5,
        max_slots=5,
        genre_focus="MIXED",
    )
    fx.allocate(api, festival)
    stage = fx.create_stage(api, festival["id"])
    nova = fx.create_artist(api, draw_score=48)
    vela = _vela_roan(api, draw_score=48)

    offer_nova = _issue(
        api,
        festival["id"],
        nova["id"],
        tier_h["id"],
        stage["id"],
        guarantee_cents=1200000,
        slot_start_utc="2026-12-04T21:00:00Z",
    )
    offer_vela = _issue(
        api,
        festival["id"],
        vela["id"],
        tier_h["id"],
        stage["id"],
        guarantee_cents=1200000,
        slot_start_utc="2026-12-05T21:00:00Z",
    )

    validate_success(
        api.accept_offer(offer_nova["id"], make_artist_rep_headers(nova["id"])), 201
    )

    summary = validate_success(api.get_budget_summary(festival["id"], FINANCE_CONTROLLER))
    assert summary["allocatable_budget_cents"] == 4000000
    assert summary["committed_budget_cents"] == 1200000
    assert summary["tier_committed_sum_cents"] == 1200000
    assert summary["booking_committed_sum_cents"] == 1200000
    assert abs(float(summary["committed_ratio"]) - 0.30) < 1e-9
    assert summary["lineup_posture"] == "OPEN"
    assert summary["open_tier_count"] == 1
    assert summary["closed_tier_count"] == 1
    assert summary["headliner_anchor_count"] == 1

    closed_tier = validate_success(api.get_budget_tier(tier_h["id"], FINANCE_CONTROLLER))
    assert closed_tier["status"] == "CLOSED"
    assert closed_tier["slots_committed"] == 1
    assert closed_tier["max_slots"] == 1
    assert closed_tier["committed_cents"] == 1200000
    assert closed_tier["allocation_cents"] == 2000000

    sibling = validate_success(api.get_offer(offer_vela["id"], TALENT_BUYER))
    assert sibling["status"] == "SUPERSEDED"

    clauses, _ = validate_paginated(
        api.list_radius_clauses(BUSINESS_AFFAIRS, {"offer_id": offer_vela["id"]})
    )
    assert clauses[0]["enforcement_status"] == "RELEASED"


def test_the_settlement_read_exposes_the_unadjusted_gross_and_the_deposit_offset(api):
    """The pinned steps stay auditable and the paid deposit is a final subtraction.

    "A computed settlement read exposes every pinned step for audit: `guarantee_cents`, `rider_estimate_cents`, `waiver_fee_cents`, `gross_pre_share_cents` reported with the unadjusted rider so the bracket choice is checkable, `promoter_share_pct`, `reimbursed_rider_cents`, `deposit_paid_cents` and `settlement_total_cents`."
    "A deposit payment recomputes the booking's `deposit_paid_cents`, defined as the sum of `paid_amount_cents` over that booking's deposit installments whose `status` is `PAID`, `CLAWBACK_PENDING` or `RECOVERED`, and moves the booking's `settlement_status` `UNFUNDED → DEPOSIT_PAID`."

    Design: Corner/endpoints/settlement_computed_read_exposes_the_unadjusted_gross_and_the_deposit_offset
    """
    ctx = _canonical_edition(api)
    executed = fx.countersigned_booking(
        api,
        ctx,
        unit_cost_cents=250000,
        slot_start_utc="2026-12-04T21:00:00Z",
    )
    booking_id = executed["booking"]["id"]
    installments = fx.installments_of(api, booking_id)
    deposit = installments["DEPOSIT"]
    assert deposit["amount_cents"] == 900000
    assert deposit["due_date"] == "2026-08-31"

    before = validate_success(api.get_settlement(booking_id, FINANCE_CONTROLLER))
    assert before["guarantee_cents"] == 1800000
    assert before["rider_estimate_cents"] == 250000
    assert before["waiver_fee_cents"] == 0
    assert before["gross_pre_share_cents"] == 2050000
    assert abs(float(before["promoter_share_pct"]) - 0.75) < 1e-9
    assert before["reimbursed_rider_cents"] == 187500
    assert before["deposit_paid_cents"] == 0
    assert before["settlement_total_cents"] == 1987500

    fx.set_clock(api, "2026-08-24T00:00:00Z")
    validate_success(api.release_installment(deposit["id"], FINANCE_CONTROLLER))
    paid = validate_success(
        api.mark_installment_paid(
            deposit["id"], {"paid_amount_cents": 900000}, FINANCE_CONTROLLER
        )
    )
    assert paid["status"] == "PAID"
    assert _same_instant(paid["paid_at"], "2026-08-24T00:00:00Z")

    after = validate_success(api.get_settlement(booking_id, FINANCE_CONTROLLER))
    assert after["gross_pre_share_cents"] == 2050000
    assert abs(float(after["promoter_share_pct"]) - 0.75) < 1e-9
    assert after["deposit_paid_cents"] == 900000
    assert after["settlement_total_cents"] == 1087500

    booking = validate_success(api.get_booking(booking_id, TALENT_BUYER))
    assert booking["settlement_status"] == "DEPOSIT_PAID"


def test_the_computed_reads_echo_their_variant_and_reject_unknown_ones(api):
    """Both computed reads report every figure regardless of the variant asked for.

    "A computed rider read exposes both side by side; it accepts a `variant` of `PROPOSED_SCOPE`, `CONTRACTED_SCOPE` or `BOTH`, defaults to `BOTH`, and returns both totals regardless, as `proposed_scope_cents` and `contracted_scope_cents`, together with `variant_delta_cents` — the proposed total less the contracted total — and the counts `priced_line_count`, `capped_line_count` and `zeroed_line_count`."
    "It accepts a `variant` of `STRICT`, which is the default, or `ADJUDICATED`; any other value is `ERR_INVALID_REQUEST`."

    Design: Corner/endpoints/computed_read_variants_are_echoed_and_unknown_variants_rejected
    """
    ctx = _canonical_edition(api)
    settled = fx.rider_settled_booking(
        api,
        ctx,
        unit_cost_cents=250000,
        slot_start_utc="2026-12-04T21:00:00Z",
    )
    booking_id = settled["booking"]["id"]
    artist_id = ctx["artist"]["id"]

    rider = validate_success(
        api.get_rider_estimate(
            booking_id, PRODUCTION_MANAGER, {"variant": "CONTRACTED_SCOPE"}
        )
    )
    assert rider["variant"] == "CONTRACTED_SCOPE"
    assert rider["contracted_scope_cents"] == 250000
    assert rider["proposed_scope_cents"] == 250000
    assert rider["variant_delta_cents"] == 0
    assert rider["priced_line_count"] == 1
    assert rider["capped_line_count"] == 0
    assert rider["zeroed_line_count"] == 0

    validate_error(
        api.get_rider_estimate(booking_id, PRODUCTION_MANAGER, {"variant": "NET"}),
        "ERR_INVALID_REQUEST",
        422,
    )

    risk = validate_success(api.get_radius_risk(artist_id, BUSINESS_AFFAIRS))
    assert risk["variant"] == "STRICT"
    assert risk["reported_conflict_count"] == 0
    assert risk["radius_breach_count"] == 0
    assert risk["draw_penalty"] == 6
    assert risk["risk_score"] == 6
    assert risk["blocked"] is False

    validate_error(
        api.get_radius_risk(artist_id, BUSINESS_AFFAIRS, {"variant": "LENIENT"}),
        "ERR_INVALID_REQUEST",
        422,
    )


def test_the_expiry_sweep_is_scoped_by_festival_id(api):
    """The optional festival filter narrows the sweep and a quiet sweep is not an error.

    "The sweep accepts an optional `festival_id` to narrow its scope and reports `expired_count`, `expired_offer_ids` ordered by `offer_expires_utc` ascending with `created_at` ascending as the tie-break, and `released_clause_count`."
    "A second sweep with nothing newly expired reports `expired_count` 0 and is not an error."

    Design: Corner/endpoints/sweep_expired_bulk_action_is_scoped_by_festival_id
    """
    fx.set_clock(api, DEFAULT_CLOCK_UTC)

    harbor = fx.create_festival(api)
    harbor_tier = fx.create_tier(
        api,
        harbor["id"],
        tier_code="HEADLINER",
        tier_rank=1,
        allocation_pct=1.0,
        max_slots=5,
        genre_focus="MIXED",
    )
    fx.allocate(api, harbor)
    harbor_stage = fx.create_stage(api, harbor["id"])
    nova = fx.create_artist(api)
    harbor_offer = _issue(
        api,
        harbor["id"],
        nova["id"],
        harbor_tier["id"],
        harbor_stage["id"],
        slot_start_utc="2026-12-04T21:00:00Z",
        offer_expires_utc="2026-09-01T00:00:00Z",
    )

    bayside = fx.create_festival(
        api,
        name="Bayside Sessions",
        event_start_date="2026-11-06",
        event_end_date="2026-11-07",
        talent_budget_cents=6000000,
        contingency_reserve_pct=0.0,
    )
    bayside_tier = fx.create_tier(
        api,
        bayside["id"],
        tier_code="HEADLINER",
        tier_rank=1,
        allocation_pct=1.0,
        max_slots=5,
        genre_focus="MIXED",
    )
    fx.allocate(api, bayside)
    bayside_stage = fx.create_stage(
        api, bayside["id"], name="Bayside Main", capacity=9000
    )
    vela = _vela_roan(api)
    bayside_offer = _issue(
        api,
        bayside["id"],
        vela["id"],
        bayside_tier["id"],
        bayside_stage["id"],
        slot_start_utc="2026-11-06T21:00:00Z",
        offer_expires_utc="2026-09-01T00:00:00Z",
        window_start_date="2026-09-06",
        window_end_date="2026-12-06",
    )

    fx.set_clock(api, "2026-09-02T00:00:00Z")

    scoped = validate_success(
        api.sweep_expired_offers(BUSINESS_AFFAIRS, {"festival_id": harbor["id"]})
    )
    assert scoped["expired_count"] == 1
    assert scoped["expired_offer_ids"] == [harbor_offer["id"]]
    assert scoped["released_clause_count"] == 1

    untouched = validate_success(api.get_offer(bayside_offer["id"], TALENT_BUYER))
    assert untouched["status"] == "ISSUED"

    unscoped = validate_success(api.sweep_expired_offers(TALENT_BUYER))
    assert unscoped["expired_count"] == 1
    assert unscoped["expired_offer_ids"] == [bayside_offer["id"]]
    assert unscoped["released_clause_count"] == 1

    quiet = validate_success(api.sweep_expired_offers(TALENT_BUYER))
    assert quiet["expired_count"] == 0
    assert quiet["expired_offer_ids"] == []
    assert quiet["released_clause_count"] == 0

    released, meta = validate_paginated(
        api.list_radius_clauses(BUSINESS_AFFAIRS, {"enforcement_status": "RELEASED"})
    )
    assert meta["total_count"] == 2
    assert len(released) == 2


def test_wave_assignment_sets_reveal_order_in_the_order_the_calls_were_made(api):
    """reveal_order follows the assignment calls, while the booking list stays in slot order.

    "On success the booking's `announcement_wave_id` is set and its `reveal_order` becomes the wave's `assignment_count` after the increment, so the first booking assigned reveals first."
    "The wave's `assignment_count` increases by one, its `headliner_count` increases by one when the booking's `billing_position` is 1, and its `version` advances."

    Design: Corner/endpoints/wave_assignment_cross_reference_sets_reveal_order_in_call_order
    """
    ctx = _canonical_edition(api)
    vela = _vela_roan(api)

    headliner = fx.countersigned_booking(
        api,
        ctx,
        unit_cost_cents=250000,
        billing_position=1,
        slot_start_utc="2026-12-04T21:00:00Z",
    )["booking"]
    support = fx.countersigned_booking(
        api,
        ctx,
        vela,
        unit_cost_cents=250000,
        billing_position=2,
        slot_start_utc="2026-12-04T18:00:00Z",
    )["booking"]

    wave = fx.planned_wave(
        api,
        ctx["festival"]["id"],
        wave_number=1,
        phase="PRESALE",
        scheduled_reveal_utc="2026-09-10T12:00:00Z",
    )
    assert wave["version"] == 1

    validate_success(
        api.assign_booking_to_wave(
            wave["id"],
            {
                "booking_id": support["id"],
                "expected_announcement_wave_version": wave["version"],
            },
            TALENT_BUYER,
        )
    )
    support = validate_success(api.get_booking(support["id"], TALENT_BUYER))
    assert support["announcement_wave_id"] == wave["id"]
    assert support["reveal_order"] == 1

    after_first = validate_success(api.get_announcement_wave(wave["id"], TALENT_BUYER))
    assert after_first["assignment_count"] == 1
    assert after_first["headliner_count"] == 0
    assert after_first["version"] == 2

    validate_success(
        api.assign_booking_to_wave(
            wave["id"],
            {
                "booking_id": headliner["id"],
                "expected_announcement_wave_version": after_first["version"],
            },
            TALENT_BUYER,
        )
    )
    headliner = validate_success(api.get_booking(headliner["id"], TALENT_BUYER))
    assert headliner["reveal_order"] == 2

    after_second = validate_success(api.get_announcement_wave(wave["id"], TALENT_BUYER))
    assert after_second["assignment_count"] == 2
    assert after_second["headliner_count"] == 1
    assert after_second["version"] == 3
    assert after_second["status"] == "PLANNED"

    rows, meta = validate_paginated(
        api.list_bookings(
            TALENT_BUYER, {"announcement_wave_id": wave["id"], "limit": 10}
        )
    )
    assert meta["total_count"] == 2
    assert [row["id"] for row in rows] == [support["id"], headliner["id"]]
    assert [row["reveal_order"] for row in rows] == [1, 2]


def test_the_booking_list_keeps_cancelled_rows_unless_a_filter_removes_them(api):
    """Filters compose conjunctively and nothing hides a cancelled booking implicitly.

    "Bookings can be listed and filtered by `festival_id`, `artist_id`, `offer_id`, `budget_tier_id`, `stage_id`, `replaces_booking_id`, `announcement_wave_id`, `contract_status` and `settlement_status`, with agents again seeing only their own act's rows."
    "The documented orderings are: budget tiers by `tier_rank` ascending; stages by `is_flagship` descending, then `name` ascending; offers by `slot_start_utc` ascending; radius clauses by `radius_miles` descending, then `window_start_date` ascending — deliberately the same ranking the radius conflict detector uses to pick a winning clause; competing performances by `performance_date` ascending; bookings by `slot_start_utc` ascending; rider items by `category` ascending; advance packets by `created_at` ascending alone; payment installments by `due_date` ascending, which is exactly the order the chronological recovery replay uses; and announcement waves by `wave_number` ascending."
    "A stage's `booked_minutes` must always equal the sum of `set_length_minutes` over that stage's bookings whose `contract_status` is anything other than `CANCELLED`, again as exact integer equality."

    Design: Corner/endpoints/booking_list_filters_compose_and_exclude_cancelled_rows_only_on_request
    """
    ctx = _canonical_edition(api)
    festival_id = ctx["festival"]["id"]
    aurora = ctx["stage"]
    grove = fx.create_stage(
        api,
        festival_id,
        name="Grove",
        capacity=6000,
        daily_curfew_minute=1200,
        daily_program_minutes_cap=360,
        changeover_buffer_minutes=20,
        is_flagship=False,
    )
    vela = _vela_roan(api)
    cassia = fx.create_artist(
        api,
        legal_name="Cassia Vale Touring Inc",
        performing_name="Cassia Vale",
        primary_genre="POP",
        draw_score=40,
    )

    nova_booking = fx.accepted_booking(
        api, ctx, billing_position=1, slot_start_utc="2026-12-04T21:00:00Z"
    )
    vela_booking = fx.accepted_booking(
        api, ctx, vela, billing_position=2, slot_start_utc="2026-12-04T18:00:00Z"
    )
    cassia_offer = _issue(
        api,
        festival_id,
        cassia["id"],
        ctx["mid_card"]["id"],
        grove["id"],
        guarantee_cents=500000,
        billing_position=2,
        set_length_minutes=60,
        slot_start_utc="2026-12-05T15:00:00Z",
    )
    cassia_booking = validate_success(
        api.accept_offer(cassia_offer["id"], make_artist_rep_headers(cassia["id"])), 201
    )

    validate_success(
        api.cancel_booking(
            vela_booking["id"],
            {"cancelling_party": "PROMOTER", "cancellation_reason": "Visa denied."},
            TALENT_BUYER,
        )
    )

    rows, meta = validate_paginated(
        api.list_bookings(TALENT_BUYER, {"festival_id": festival_id, "limit": 10})
    )
    assert meta["total_count"] == 3
    assert [row["id"] for row in rows] == [
        vela_booking["id"],
        nova_booking["id"],
        cassia_booking["id"],
    ]
    assert [row["contract_status"] for row in rows].count("CANCELLED") == 1

    rows, meta = validate_paginated(
        api.list_bookings(
            TALENT_BUYER,
            {"festival_id": festival_id, "contract_status": "PENDING_RIDER"},
        )
    )
    assert meta["total_count"] == 2
    assert [row["id"] for row in rows] == [nova_booking["id"], cassia_booking["id"]]

    rows, meta = validate_paginated(
        api.list_bookings(
            TALENT_BUYER, {"stage_id": aurora["id"], "contract_status": "CANCELLED"}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == vela_booking["id"]

    rows, meta = validate_paginated(
        api.list_bookings(TALENT_BUYER, {"stage_id": grove["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == cassia_booking["id"]

    aurora_now = validate_success(api.get_stage(aurora["id"], PRODUCTION_MANAGER))
    assert aurora_now["booked_minutes"] == 90


def test_installment_release_turns_on_the_release_window_alone(api):
    """The same row flips outcome on the logical clock, per installment due date.

    "It also requires the release window to be open: the logical clock's date must have reached the installment's `due_date` less 7 days."
    "Money cannot leave more than a week ahead of its due date, and the boundary date itself is releasable; earlier than that is `ERR_PAYMENT_NOT_RELEASABLE`."
    "On success `status` moves `SCHEDULED → RELEASED` and `released_at` records the logical clock."

    Design: Corner/endpoints/installment_release_is_a_conditional_action_on_the_release_window
    """
    ctx = _canonical_edition(api)
    executed = fx.countersigned_booking(
        api,
        ctx,
        unit_cost_cents=250000,
        slot_start_utc="2026-12-04T21:00:00Z",
    )
    booking_id = executed["booking"]["id"]
    installments = fx.installments_of(api, booking_id)
    deposit, balance = installments["DEPOSIT"], installments["BALANCE"]
    assert deposit["amount_cents"] == 900000
    assert deposit["due_date"] == "2026-08-31"
    assert balance["amount_cents"] == 900000
    assert balance["due_date"] == "2026-12-04"

    fx.set_clock(api, "2026-08-23T23:59:59Z")
    validate_error(
        api.release_installment(deposit["id"], FINANCE_CONTROLLER),
        "ERR_PAYMENT_NOT_RELEASABLE",
        409,
    )

    fx.set_clock(api, "2026-08-24T00:00:00Z")
    released = validate_success(
        api.release_installment(deposit["id"], FINANCE_CONTROLLER)
    )
    assert released["status"] == "RELEASED"
    assert _same_instant(released["released_at"], "2026-08-24T00:00:00Z")

    validate_error(
        api.release_installment(balance["id"], FINANCE_CONTROLLER),
        "ERR_PAYMENT_NOT_RELEASABLE",
        409,
    )

    rows, _ = validate_paginated(
        api.list_payment_installments(booking_id, FINANCE_CONTROLLER)
    )
    assert [row["status"] for row in rows] == ["RELEASED", "SCHEDULED"]

    booking = validate_success(api.get_booking(booking_id, TALENT_BUYER))
    assert booking["settlement_status"] == "UNFUNDED"


def test_the_child_and_report_collections_order_and_filter_independently(api):
    """Four collections, four declared orderings, one filter vocabulary each.

    "The documented orderings are: budget tiers by `tier_rank` ascending; stages by `is_flagship` descending, then `name` ascending; offers by `slot_start_utc` ascending; radius clauses by `radius_miles` descending, then `window_start_date` ascending — deliberately the same ranking the radius conflict detector uses to pick a winning clause; competing performances by `performance_date` ascending; bookings by `slot_start_utc` ascending; rider items by `category` ascending; advance packets by `created_at` ascending alone; payment installments by `due_date` ascending, which is exactly the order the chronological recovery replay uses; and announcement waves by `wave_number` ascending."
    "Each of those responses reports `limit`, `offset`, `total_count` and `has_more` inside `meta`, where `total_count` is the number of rows matching the filters before the window is applied and `has_more` is true when rows remain beyond it."

    Design: Corner/endpoints/child_and_report_collections_paginate_and_filter_independently
    """
    ctx = _canonical_edition(api)
    artist_id = ctx["artist"]["id"]
    booking = fx.accepted_booking(
        api, ctx, slot_start_utc="2026-12-04T21:00:00Z"
    )
    booking_id = booking["id"]

    hospitality = fx.add_rider_line(
        api,
        booking_id,
        artist_id,
        category="HOSPITALITY",
        description="Dressing room catering",
        unit_cost_cents=120000,
    )
    technical = fx.add_rider_line(
        api,
        booking_id,
        artist_id,
        category="TECHNICAL",
        description="Line-array PA package",
        unit_cost_cents=250000,
    )
    fx.decide_rider_line(api, technical["id"], "APPROVED")

    packet = validate_success(
        api.create_advance_packet(
            advance_packet_payload(booking_id), make_artist_rep_headers(artist_id)
        ),
        201,
    )

    tacoma = fx.report_performance(
        api,
        artist_id,
        venue_city="Tacoma",
        venue_latitude=47.2529,
        venue_longitude=-122.4443,
        performance_date="2026-11-18",
        is_ticketed=True,
        is_festival=False,
        announced_capacity=None,
    )
    boise = fx.report_performance(
        api,
        artist_id,
        venue_city="Boise",
        venue_latitude=43.615,
        venue_longitude=-116.2023,
        performance_date="2026-11-20",
        is_ticketed=True,
        is_festival=False,
        announced_capacity=None,
    )

    wave_two = fx.planned_wave(
        api,
        ctx["festival"]["id"],
        wave_number=2,
        phase="PRESALE",
        scheduled_reveal_utc="2026-10-01T12:00:00Z",
    )
    wave_one = fx.planned_wave(
        api,
        ctx["festival"]["id"],
        wave_number=1,
        phase="PRESALE",
        scheduled_reveal_utc="2026-09-10T12:00:00Z",
    )

    rows, meta = validate_paginated(
        api.list_rider_items(booking_id, PRODUCTION_MANAGER, {"limit": 10})
    )
    assert meta["total_count"] == 2
    assert [row["id"] for row in rows] == [hospitality["id"], technical["id"]]
    for key in ("limit", "offset", "total_count", "has_more"):
        assert key in meta

    rows, meta = validate_paginated(
        api.list_rider_items(
            booking_id, PRODUCTION_MANAGER, {"approval_status": "PROPOSED"}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == hospitality["id"]

    rows, meta = validate_paginated(
        api.list_advance_packets(booking_id, PRODUCTION_MANAGER, {"status": "DRAFT"})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == packet["id"]
    assert rows[0]["status"] == "DRAFT"

    rows, meta = validate_paginated(
        api.list_competing_performances(
            BUSINESS_AFFAIRS, {"artist_id": artist_id, "limit": 10}
        )
    )
    assert meta["total_count"] == 2
    assert [row["id"] for row in rows] == [tacoma["id"], boise["id"]]

    rows, meta = validate_paginated(
        api.list_competing_performances(
            BUSINESS_AFFAIRS, {"artist_id": artist_id, "conflict_assessment": "CONFLICT"}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == tacoma["id"]
    assert rows[0]["conflict_assessment"] == "CONFLICT"

    rows, meta = validate_paginated(
        api.list_competing_performances(
            BUSINESS_AFFAIRS, {"artist_id": artist_id, "limit": 1, "offset": 1}
        )
    )
    assert len(rows) == 1
    assert rows[0]["id"] == boise["id"]
    assert meta["total_count"] == 2
    assert meta["has_more"] is False

    rows, meta = validate_paginated(
        api.list_announcement_waves(
            TALENT_BUYER, {"festival_id": ctx["festival"]["id"], "status": "PLANNED"}
        )
    )
    assert meta["total_count"] == 2
    assert [row["wave_number"] for row in rows] == [1, 2]
    assert [row["id"] for row in rows] == [wave_one["id"], wave_two["id"]]
