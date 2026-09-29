"""One write, many rows: the advisory publication's four hops, the traveler
cancellation's ledger unwind, and the delinquency sweep's three hops."""

from __future__ import annotations

from test_helpers import (
    assert_instant_equals,
    active_agreement,
    assign_room,
    confirm_traveler,
    confirmed_air_block,
    create_advisory,
    create_plan,
    create_sacred_site,
    create_service_booking,
    enrol_traveler,
    file_ticket_name,
    open_sales,
    open_departure,
    pay,
    program_with_departure,
    publish_advisory,
    quote_protection,
    read_agreement,
    read_air_block,
    read_departure,
    read_plan,
    read_protection,
    read_service_booking,
    read_traveler,
    run_sweep,
    set_clock,
    api_client,
    get_success_data,
    TEST_USERS,
)

PLANNER = TEST_USERS["program_manager"]
RISK_OFFICER_ID = TEST_USERS["risk_officer"]["X-User-ID"]


# ---------------------------------------------------------------------------
# Advisory publication: four hops
# ---------------------------------------------------------------------------


def _suspended_by_advisory():
    """A fully-furnished departure in Israel, then a DO_NOT_TRAVEL publication."""
    program, departure = program_with_departure()
    departure_id = departure["id"]

    site = create_sacred_site(
        name="Basilica of the Holy Sepulchre",
        country="IL",
        access_regime="PERMIT_REQUIRED",
        daily_capacity_pax=200,
        turnaround_buffer_minutes=30,
        requires_local_clergy=True,
    )
    booking = create_service_booking(
        departure_id,
        site["id"],
        service_type="MASS",
        scheduled_start_utc="2026-11-02T06:00:00Z",
        duration_minutes=60,
        pax_count=2,
        permit_reference="PRM-2026-441",
    )
    open_sales(departure_id)

    agreement = active_agreement(
        departure_id,
        free_travel_threshold=2,
        commission_mode="PER_PAX_CASH",
        commission_rate_cents_per_pax=6000,
        accrual_basis="RECRUITED",
    )
    block = confirmed_air_block(
        departure_id,
        offered_fare_cents=850_000,
        carrier_code="LY",
        seats_held=20,
    )

    recruits = []
    for full_name in ("Recruit One", "Recruit Two"):
        traveler = enrol_traveler(
            departure_id,
            full_name=full_name,
            recruited_by_agreement_id=agreement["id"],
        )
        assign_room(traveler["id"])
        pay(traveler["id"], 50_000)
        confirm_traveler(traveler["id"])
        recruits.append(traveler)

    file_ticket_name(recruits[0]["id"], "RECRUIT/ONE MR")

    advisory = create_advisory(
        country="IL",
        level="DO_NOT_TRAVEL",
        effective_from="2026-08-01T00:00:00Z",
        source="US Department of State Travel Advisory",
    )
    published = publish_advisory(advisory["id"])
    return {
        "program": program,
        "departure_id": departure_id,
        "booking": booking,
        "agreement": agreement,
        "block": block,
        "recruits": recruits,
        "advisory": published,
    }


def test_publishing_a_do_not_travel_advisory_suspends_and_risk_cancels_services(api):
    """PRD §3.9: "Hop two: on each newly suspended departure, every service
    booking whose `status` is not `CANCELLED` moves to `CANCELLED` with
    `cancelled_by_risk` set to true, releasing the sacred site's daily pax
    capacity and buffered interval exactly as an operator cancellation would."

    Design: Difficulty/transitive_cascade/advisory_publish_four_hop_cascade
    """
    stage = _suspended_by_advisory()

    assert stage["advisory"]["status"] == "PUBLISHED"
    assert stage["advisory"]["affected_departure_count"] == 1

    departure = read_departure(stage["departure_id"])
    assert departure["risk_posture"] == "SUSPENDED"
    assert departure["governing_advisory_id"] == stage["advisory"]["id"]
    # A newly suspended departure whose status was OPEN_FOR_SALE is closed.
    assert departure["status"] == "SALES_CLOSED"
    assert departure["service_coverage_ok"] is False

    booking = read_service_booking(stage["booking"]["id"])
    assert booking["status"] == "CANCELLED"
    assert booking["cancelled_by_risk"] is True


def test_publishing_a_do_not_travel_advisory_releases_seats_and_forces_a_modification(api):
    """PRD §3.9: "Hop three: because services were risk-cancelled, that
    departure's `service_coverage_ok` flips to false,
    `pending_modification_required` flips to true, `pending_modification_reason`
    is set to the literal string `RISK_SUSPENSION`,
    `pending_modification_cost_delta_cents` is set to 0, and
    `pending_modification_proposed_by_user_id` is set to the publishing
    officer's `X-User-ID`, so that the officer who published the advisory cannot
    also ratify the change it forced."

    Design: Difficulty/transitive_cascade/advisory_publish_four_hop_cascade
    """
    stage = _suspended_by_advisory()

    departure = read_departure(stage["departure_id"])
    assert departure["pending_modification_required"] is True
    assert departure["pending_modification_reason"] == "RISK_SUSPENSION"
    assert departure["pending_modification_cost_delta_cents"] == 0
    assert departure["pending_modification_proposed_by_user_id"] == RISK_OFFICER_ID

    block = read_air_block(stage["block"]["id"])
    assert block["status"] == "RELEASED"
    assert block["seats_assigned"] == 0
    assert read_traveler(stage["recruits"][0]["id"])["ticketed_name"] is None

    agreement = read_agreement(stage["agreement"]["id"])
    assert agreement["recruited_paying_count"] == 2
    assert agreement["earned_free_seats"] == 1
    assert agreement["commission_payable_cents"] == 12_000


# ---------------------------------------------------------------------------
# Traveler cancellation: the ledger unwind
# ---------------------------------------------------------------------------


def _cancelled_recruit_with_a_plan():
    """A confirmed recruit on a live plan with 250,000 cents of cash, cancelled."""
    stage = open_departure()
    departure_id = stage["departure"]["id"]
    agreement = active_agreement(
        departure_id,
        free_travel_threshold=2,
        commission_mode="PER_PAX_CASH",
        commission_rate_cents_per_pax=6000,
    )

    recruits = []
    for full_name in ("Recruit One", "Recruit Two"):
        traveler = enrol_traveler(
            departure_id,
            full_name=full_name,
            recruited_by_agreement_id=agreement["id"],
        )
        assign_room(traveler["id"])
        pay(traveler["id"], 50_000)
        confirm_traveler(traveler["id"])
        recruits.append(traveler)

    protection = quote_protection(
        recruits[0]["id"], plan_code="STANDARD", medical_limit_cents=3_000_000
    )
    plan = create_plan(recruits[0]["id"], "MONTHLY_3", "2026-08-15")
    pay(recruits[0]["id"], 200_000, method="CARD")

    set_clock("2026-08-03T00:00:00Z")
    cancelled = get_success_data(
        api_client.cancel_pilgrim(
            recruits[0]["id"], {"cancellation_reason": "FAMILY_EMERGENCY"}, PLANNER
        )
    )
    return departure_id, agreement, recruits, protection, plan, cancelled


def test_traveler_cancellation_settles_on_the_inclusive_grid_bucket(api):
    """PRD §3.5: "Finally `penalty_retained_cents` is the lesser of the
    traveler's `cash_applied_cents` and the traveler's `invoice_total_cents`
    multiplied by the penalty rate in basis points, divided by 10,000, rounded
    half up — the rounding happens before the comparison, and the cap means a
    traveler can never be penalised more cash than they actually paid."

    Design: Difficulty/transitive_cascade/pilgrim_cancel_three_hop_ledger_cascade
    """
    _departure_id, _agreement, _recruits, _protection, _plan, cancelled = (
        _cancelled_recruit_with_a_plan()
    )

    assert cancelled["booking_status"] == "CANCELLED"
    assert cancelled["payment_status"] == "REFUNDED"
    # 90 whole days before departure sits in the 1000bp bucket inclusively:
    # 577168 * 1000 / 10000 = 57716.8 -> 57717, against 250000 of cash.
    assert cancelled["penalty_retained_cents"] == 57_717
    assert cancelled["refund_cents"] == 192_283


def test_traveler_cancellation_supersedes_the_plan_voids_cover_and_reworks_accrual(api):
    """PRD §3.5: "The traveler's `ACTIVE` payment plan moves to `SUPERSEDED`
    with every installment in `SCHEDULED`, `PARTIALLY_PAID` or `PAST_DUE` moved
    to `WAIVED`, and their travel protection, unless it is already `PURCHASED`
    or `VOIDED`, moves to `VOIDED` with `premium_cents`, `base_premium_cents`,
    `medical_uplift_cents` and `waiver_surcharge_cents` all zeroed and
    `protection_status` set to `VOIDED`."

    Design: Difficulty/transitive_cascade/pilgrim_cancel_three_hop_ledger_cascade
    """
    departure_id, agreement, _recruits, protection, plan, cancelled = (
        _cancelled_recruit_with_a_plan()
    )

    reread_plan = read_plan(plan["id"])
    assert reread_plan["status"] == "SUPERSEDED"
    # The first installment was fully funded before the cancellation, so it is
    # not one of the SCHEDULED / PARTIALLY_PAID / PAST_DUE rows that get waived.
    assert reread_plan["installments"][0]["status"] == "PAID"
    assert reread_plan["installments"][1]["status"] == "WAIVED"
    assert reread_plan["installments"][2]["status"] == "WAIVED"

    reread_protection = read_protection(protection["id"])
    assert reread_protection["status"] == "VOIDED"
    assert reread_protection["premium_cents"] == 0
    assert cancelled["protection_status"] == "VOIDED"

    reread_agreement = read_agreement(agreement["id"])
    assert reread_agreement["recruited_paying_count"] == 1
    assert reread_agreement["earned_free_seats"] == 0
    assert reread_agreement["commission_payable_cents"] == 6_000

    departure = read_departure(departure_id)
    assert departure["paying_pax_count"] == 1
    assert departure["provisional_tier_code"] == "T1"


# ---------------------------------------------------------------------------
# The delinquency sweep: three hops
# ---------------------------------------------------------------------------


def _swept_into_default():
    """A confirmed traveler with two overdue installments when the sweep runs."""
    stage = open_departure()
    departure_id = stage["departure"]["id"]

    traveler = enrol_traveler(departure_id, full_name="Delinquent Traveler")
    assign_room(traveler["id"])
    pay(traveler["id"], 50_000)
    confirm_traveler(traveler["id"])
    plan = create_plan(traveler["id"], "MONTHLY_3", "2026-08-05")

    set_clock("2026-09-06T00:00:00Z")
    run_sweep(departure_id)
    return departure_id, traveler, plan


def test_sweep_moves_overdue_installments_past_due_and_defaults_the_plan(api):
    """PRD §3.7: "Hop two: a plan whose refreshed `past_due_count` has reached 2
    or more moves to `DEFAULTED` and its traveler's `payment_status` becomes
    `IN_DEFAULT` — one missed installment is tolerated, two is not."

    Design: Difficulty/transitive_cascade/payment_sweep_default_three_hop_cascade
    """
    _departure_id, traveler, plan = _swept_into_default()

    reread_plan = read_plan(plan["id"])
    installments = reread_plan["installments"]
    assert installments[0]["amount_due_cents"] == 192_390
    assert installments[0]["amount_paid_cents"] == 50_000
    assert installments[0]["status"] == "PAST_DUE"
    assert installments[1]["amount_due_cents"] == 192_389
    assert installments[1]["status"] == "PAST_DUE"
    # The third installment is due 2026-10-05, still ahead of the clock.
    assert installments[2]["status"] == "SCHEDULED"
    assert reread_plan["past_due_count"] == 2
    assert reread_plan["status"] == "DEFAULTED"

    assert read_traveler(traveler["id"])["payment_status"] == "IN_DEFAULT"


def test_sweep_reverts_the_defaulted_traveler_and_stamps_the_departure(api):
    """PRD §3.7: "Hop three: a defaulted traveler has their `ticketed_name`
    cleared, which decrements `seats_assigned` on the departure's blocks, and a
    defaulted traveler in `CONFIRMED` reverts to `DEPOSITED`, which in turn
    re-runs the departure's provisional tier calculation and the recruiting
    agreement's snapshot accrual."

    Design: Difficulty/transitive_cascade/payment_sweep_default_three_hop_cascade
    """
    departure_id, traveler, _plan = _swept_into_default()

    assert read_traveler(traveler["id"])["booking_status"] == "DEPOSITED"

    departure = read_departure(departure_id)
    assert departure["sweep_run_count"] == 1
    assert_instant_equals(departure["last_sweep_at"], "2026-09-06T00:00:00Z")
