"""The eight declared machines: initial states, legal moves, terminal lockdown.

Each transition is checked for the side effects it owns and, just as important,
for the side effects it must not perform twice — signing an agreement, releasing
a block and cancelling a stop are all refused rather than treated as idempotent.
"""

from test_helpers import (
    ApiErrorId,
    BUSINESS_MANAGER_ID,
    CORPS_DIRECTOR_HEADERS,
    Duty,
    SECOND_BUSINESS_MANAGER_ID,
    TOUR_MANAGER_HEADERS,
    TOUR_MANAGER_ID,
    VolunteerRoleType,
    assert_all_nulls,
    assert_facility_agreement,
    assert_host_school,
    assert_housing_assignment,
    assert_member,
    assert_member_contract,
    assert_season,
    assert_show_settlement,
    assert_site_booking,
    assert_staff_assignment,
    assert_tour_stop,
    assert_volunteer,
    factories as f,
    fixtures as fx,
    validate_error,
)

SHOW_SHAPE = dict(
    venue_name="Rockford Stadium",
    city="Rockford",
    state_code="IL",
    arrive_at="2027-06-20T08:00:00Z",
    depart_at="2027-06-20T23:00:00Z",
    show_start_at="2027-06-20T19:00:00Z",
    travel_miles_from_previous=0,
    uniform_trunks=0,
    instrument_cases=0,
    prop_units=0,
    truck_count=1,
    rehearsal_minutes=0,
    heat_index_f=80,
)

REHEARSAL_SHAPE = dict(
    city="Rockford",
    state_code="IL",
    travel_miles_from_previous=0,
    uniform_trunks=0,
    instrument_cases=0,
    prop_units=0,
    truck_count=1,
    rehearsal_minutes=120,
    heat_index_f=80,
)


def test_an_empty_roster_show_stop_confirms_then_completes(api):
    """Every snapshot lands at zero except the one-truck floor.

    PRD: "`trucks_required` is the largest of those two figures and 1 — even an
    empty load requires one truck."

    Design: Corner/state_machines/zero_roster_show_stop_confirms_then_completes_with_snapshots
    """
    season = fx.create_season(api)
    stop = fx.create_stop(api, season["id"], **SHOW_SHAPE)

    confirmed = fx.confirm_stop(api, stop["id"])
    assert_tour_stop(confirmed, status="CONFIRMED", version=2, roster_head_count=0,
                     minor_head_count=0, required_chaperone_count=0,
                     required_cook_count=0, meal_cost_cents=0, total_load_cuft=0,
                     total_load_lbs=0, trucks_required=1,
                     required_travel_minutes=0)

    fx.set_clock(api, "2027-06-20T23:00:00Z")
    completed = fx.complete_stop(api, stop["id"])
    assert_tour_stop(completed, status="COMPLETED", version=3,
                     settlement_state="PENDING")


def test_every_entity_is_born_in_its_own_declared_initial_state(api):
    """Eight machines, eight initial states, including the parallel medical one.

    PRD: "Registration writes `membership_status` as `APPLICANT`, `medical_status`
    as `CLEARED`, every money field on the member — `tuition_charged_cents`,
    `tuition_paid_cents`, `tuition_balance_cents` and `refund_due_cents` — as 0,
    and `withdrawal_date`, `withdrawal_obligation_cents` and `audition_score` as
    null, with `withdrawal_obligation_basis` at `NONE`."

    Design: Corner/state_machines/newly_created_entities_start_in_their_declared_initial_states
    """
    season = fx.create_season(api)
    built = fx.signed_agreement_with_school(
        api, season["id"], usage_type="TOUR_REHEARSAL", start_date="2027-06-18",
        end_date="2027-06-25", nightly_rate_cents=400, minimum_billable_beds=0,
        school_overrides={"name": "Rockford High School", "city": "Rockford",
                          "state_code": "IL"},
    )

    member = fx.create_member(api, season["id"], full_name="Avery Nakamura",
                              date_of_birth="2005-03-04")
    assert_member(member, membership_status="APPLICANT", medical_status="CLEARED")
    assert_all_nulls(member, "withdrawal_date", "withdrawal_obligation_cents",
                     "audition_score")

    fx.offer_member(api, member["id"], 88)
    contract = fx.issue_contract(api, member["id"])
    assert_member_contract(contract, status="ISSUED", revision_round=0)
    assert_all_nulls(contract, "revision_note", "signature_name", "signed_at",
                     "executed_at")

    draft = fx.draft_agreement(api, built["school"]["id"], season["id"],
                               nightly_rate_cents=500, minimum_billable_beds=0)
    assert_facility_agreement(draft, status="DRAFT", counter_round=0)

    stop = fx.create_rehearsal_stop(api, season["id"],
                                    venue_name="Rockford High School",
                                    arrive_at="2027-06-19T08:00:00Z",
                                    depart_at="2027-06-19T20:00:00Z",
                                    **REHEARSAL_SHAPE)
    assert_tour_stop(stop, status="PLANNED", settlement_state="NONE",
                     meal_cost_cents=0)

    booking = fx.create_booking(api, stop["id"], built["school"]["id"],
                                built["agreement"]["id"], "2027-06-19T10:00:00Z",
                                "2027-06-19T14:00:00Z", indoor=False)
    assert_site_booking(booking, status="HELD", released_reason=None)

    volunteer = fx.create_volunteer(api, VolunteerRoleType.COOK,
                                    full_name="Rosa Cook")
    assert_volunteer(volunteer, screening_status="PENDING", assignment_count=0,
                     screening_expires_on=None)

    shift = fx.propose_shift(api, volunteer["id"], stop["id"], Duty.COOK,
                             "2027-06-19T09:00:00Z", "2027-06-19T19:00:00Z")
    assert_staff_assignment(shift, status="PROPOSED", approved_by_user_id=None)


def test_a_cancelled_stop_refuses_confirm_complete_and_a_second_cancel(api):
    """Three doors, all locked, and the version never moves again.

    PRD: "The stop's `status` permits the operation: confirming requires `PLANNED`,
    completing requires `CONFIRMED`, cancelling requires `PLANNED` or `CONFIRMED`,
    and creating a rehearsal block or a shift against a stop requires that stop to
    be `PLANNED` or `CONFIRMED`."

    Design: Corner/state_machines/cancelled_tour_stop_is_terminal_and_refuses_confirm_and_complete
    """
    season = fx.create_season(api)
    stop = fx.create_rehearsal_stop(api, season["id"], venue_name="Doomed Stop",
                                    city="Peoria", state_code="IL",
                                    arrive_at="2027-06-21T08:00:00Z",
                                    depart_at="2027-06-21T20:00:00Z",
                                    travel_miles_from_previous=0, uniform_trunks=0,
                                    instrument_cases=0, prop_units=0, truck_count=1,
                                    rehearsal_minutes=120, heat_index_f=80)
    cancelled = fx.cancel_stop(api, stop["id"], "venue lost")
    version_after_cancel = cancelled["version"]

    validate_error(api.confirm_tour_stop(stop["id"], TOUR_MANAGER_HEADERS),
                   ApiErrorId.INVALID_STOP_STATE, 409)
    validate_error(api.complete_tour_stop(stop["id"], TOUR_MANAGER_HEADERS),
                   ApiErrorId.INVALID_STOP_STATE, 409)
    validate_error(api.cancel_tour_stop(stop["id"], f.cancel_payload("again"),
                                        CORPS_DIRECTOR_HEADERS),
                   ApiErrorId.INVALID_STOP_STATE, 409)

    assert_tour_stop(fx.get_stop(api, stop["id"]), status="CANCELLED",
                     cancel_reason="venue lost", version=version_after_cancel)


def test_signing_an_agreement_twice_does_not_bill_the_school_twice(api):
    """The second signature is refused rather than re-pinning the economics.

    PRD: "The agreement's `status` permits the operation: submitting requires
    `DRAFT` or `COUNTERED`, countering requires `SUBMITTED`, signing requires
    `SUBMITTED`, and cancelling requires any status other than `CANCELLED`."

    Design: Corner/state_machines/second_facility_agreement_sign_is_rejected_not_idempotent
    """
    season = fx.create_season(api)
    built = fx.signed_agreement_with_school(
        api, season["id"], nightly_rate_cents=500, minimum_billable_beds=100,
        school_overrides={"name": "Rockford High School", "city": "Rockford",
                          "state_code": "IL"},
    )

    second = api.sign_facility_agreement(built["agreement"]["id"],
                                         CORPS_DIRECTOR_HEADERS)
    validate_error(second, ApiErrorId.INVALID_AGREEMENT_STATE, 409)

    assert_facility_agreement(fx.get_agreement(api, built["agreement"]["id"]),
                              status="SIGNED", effective_nightly_rate_cents=500,
                              billable_bed_nights=2600, billable_cents=1300000)
    assert fx.get_season(api, season["id"])["housing_cost_cents"] == 1300000


def test_releasing_a_block_twice_never_drives_the_counter_negative(api):
    """The second release is refused, so booked_block_count stops at zero.

    PRD: "Releasing an already-`RELEASED` block reports
    `ERR_INVALID_BOOKING_STATE`."

    Design: Corner/state_machines/released_site_booking_cannot_be_released_again
    """
    season = fx.create_season(api)
    built = fx.signed_agreement_with_school(
        api, season["id"], usage_type="TOUR_REHEARSAL", start_date="2027-06-18",
        end_date="2027-06-25", nightly_rate_cents=400, minimum_billable_beds=0,
        school_overrides={"name": "Rockford High School", "city": "Rockford",
                          "state_code": "IL"},
    )
    stop = fx.create_rehearsal_stop(api, season["id"],
                                    venue_name="Rockford High School",
                                    arrive_at="2027-06-19T08:00:00Z",
                                    depart_at="2027-06-19T20:00:00Z",
                                    **REHEARSAL_SHAPE)
    booking = fx.create_booking(api, stop["id"], built["school"]["id"],
                                built["agreement"]["id"], "2027-06-19T10:00:00Z",
                                "2027-06-19T14:00:00Z", indoor=False)
    fx.release_booking(api, booking["id"])

    second = api.release_site_booking(booking["id"], TOUR_MANAGER_HEADERS)
    validate_error(second, ApiErrorId.INVALID_BOOKING_STATE, 409)

    assert_site_booking(fx.get_booking(api, booking["id"]), status="RELEASED",
                        released_reason="MANUAL")
    assert_host_school(fx.get_school(api, built["school"]["id"]),
                       booked_block_count=0)


def test_confirmation_promotes_only_the_held_blocks_of_that_stop(api):
    """A released block is never revived and another stop's block is untouched.

    PRD: "Every rehearsal block on the stop whose `status` is `HELD` is promoted to
    `CONFIRMED`."

    Design: Corner/state_machines/stop_confirmation_promotes_held_bookings_and_leaves_released_alone
    """
    season = fx.create_season(api)
    built = fx.signed_agreement_with_school(
        api, season["id"], usage_type="TOUR_REHEARSAL", start_date="2027-06-18",
        end_date="2027-06-25", nightly_rate_cents=400, minimum_billable_beds=0,
        school_overrides={"name": "Rockford High School", "city": "Rockford",
                          "state_code": "IL"},
    )
    school_id, agreement_id = built["school"]["id"], built["agreement"]["id"]
    stop_a = fx.create_rehearsal_stop(api, season["id"], venue_name="Stop A",
                                      arrive_at="2027-06-19T06:00:00Z",
                                      depart_at="2027-06-19T23:00:00Z",
                                      **REHEARSAL_SHAPE)
    stop_b = fx.create_rehearsal_stop(api, season["id"], venue_name="Stop B",
                                      arrive_at="2027-06-20T06:00:00Z",
                                      depart_at="2027-06-20T23:00:00Z",
                                      **REHEARSAL_SHAPE)
    block_a1 = fx.create_booking(api, stop_a["id"], school_id, agreement_id,
                                 "2027-06-19T08:00:00Z", "2027-06-19T12:00:00Z",
                                 indoor=False)
    block_a2 = fx.create_booking(api, stop_a["id"], school_id, agreement_id,
                                 "2027-06-19T16:00:00Z", "2027-06-19T20:00:00Z",
                                 indoor=False)
    block_b1 = fx.create_booking(api, stop_b["id"], school_id, agreement_id,
                                 "2027-06-20T08:00:00Z", "2027-06-20T12:00:00Z",
                                 indoor=False)
    fx.release_booking(api, block_a2["id"])

    confirmed = fx.confirm_stop(api, stop_a["id"])
    assert_tour_stop(confirmed, status="CONFIRMED")

    assert_site_booking(fx.get_booking(api, block_a1["id"]), status="CONFIRMED")
    assert_site_booking(fx.get_booking(api, block_a2["id"]), status="RELEASED",
                        released_reason="MANUAL")
    assert_site_booking(fx.get_booking(api, block_b1["id"]), status="HELD")
    assert_host_school(fx.get_school(api, school_id), booked_block_count=2)


def test_cancelling_a_signed_agreement_frees_the_beds_and_zeroes_the_billing(api):
    """Occupancy and cash go to zero while the contracted minimum survives.

    PRD: "The agreement's `occupied_bed_nights` is set to 0 and its
    `billable_cents` to 0 — a cancelled agreement bills nothing at all — while
    `billable_bed_nights` settles at the product of `minimum_billable_beds` with
    the agreement's night count, floored at 0."

    Design: Corner/state_machines/cancelling_signed_agreement_releases_housing_bookings_and_zeroes_billing
    """
    season = fx.create_season(api)
    built = fx.signed_agreement_with_school(
        api, season["id"], nightly_rate_cents=500, minimum_billable_beds=100,
        school_overrides={"name": "Rockford High School", "city": "Rockford",
                          "state_code": "IL"},
    )
    member = fx.contracted_member(api, season["id"], full_name="Avery Nakamura",
                                  date_of_birth="2005-03-04")["member"]
    stay = fx.house_member(api, built["agreement"]["id"], member["id"], 3,
                           "2027-05-10", "2027-05-20")

    cancelled = fx.cancel_agreement(api, built["agreement"]["id"], "gym flooded")
    assert_facility_agreement(cancelled, status="CANCELLED",
                              cancel_reason="gym flooded", occupied_bed_nights=0,
                              billable_bed_nights=2600, billable_cents=0)

    assert_housing_assignment(fx.get_housing(api, stay["id"]), status="RELEASED",
                              released_reason="AGREEMENT_CANCELLED")
    assert_host_school(fx.get_school(api, built["school"]["id"]),
                       reserved_bed_nights=0)
    assert fx.get_season(api, season["id"])["housing_cost_cents"] == 0


def test_cancelling_a_signed_agreement_hands_its_rehearsal_blocks_back(api):
    """The block cascade fires on the agreement, not only on the stop.

    PRD: "Every rehearsal block on the agreement whose `status` is `HELD` or
    `CONFIRMED` moves to `RELEASED`, also with `released_reason`
    `AGREEMENT_CANCELLED`, and the owning school's `booked_block_count` is
    decremented once per released block."

    Design: Corner/state_machines/cancelling_signed_agreement_releases_housing_bookings_and_zeroes_billing
    """
    season = fx.create_season(api)
    built = fx.signed_agreement_with_school(
        api, season["id"], usage_type="TOUR_REHEARSAL", start_date="2027-05-10",
        end_date="2027-06-05", nightly_rate_cents=400, minimum_billable_beds=0,
        school_overrides={"name": "Rockford High School", "city": "Rockford",
                          "state_code": "IL"},
    )
    stop = fx.create_rehearsal_stop(api, season["id"],
                                    venue_name="Rockford High School",
                                    arrive_at="2027-05-15T08:00:00Z",
                                    depart_at="2027-05-15T20:00:00Z",
                                    **REHEARSAL_SHAPE)
    booking = fx.create_booking(api, stop["id"], built["school"]["id"],
                                built["agreement"]["id"], "2027-05-15T10:00:00Z",
                                "2027-05-15T14:00:00Z", indoor=False)

    fx.cancel_agreement(api, built["agreement"]["id"], "gym flooded")

    assert_site_booking(fx.get_booking(api, booking["id"]), status="RELEASED",
                        released_reason="AGREEMENT_CANCELLED")
    assert_host_school(fx.get_school(api, built["school"]["id"]),
                       booked_block_count=0)


def test_the_season_reconciles_on_the_sweep_after_the_last_finalization(api):
    """Finalizing pays the revenue in; only the next sweep closes the books.

    PRD: "`ledger_status` remains `OPEN` until a sweep observes that every tour
    stop of the season sits in `COMPLETED` or `CANCELLED` **and** that every
    settlement belonging to those stops sits in `FINALIZED`; at that point, and
    only inside a sweep, it becomes `RECONCILED`."

    Design: Corner/state_machines/season_ledger_reconciles_only_when_every_stop_and_settlement_is_closed
    """
    season = fx.create_season(api)
    show = fx.create_stop(api, season["id"], **SHOW_SHAPE)
    scrubbed = fx.create_rehearsal_stop(api, season["id"],
                                        venue_name="Scrubbed Rehearsal",
                                        city="Peoria", state_code="IL",
                                        arrive_at="2027-06-21T08:00:00Z",
                                        depart_at="2027-06-21T20:00:00Z",
                                        travel_miles_from_previous=0,
                                        uniform_trunks=0, instrument_cases=0,
                                        prop_units=0, truck_count=1,
                                        rehearsal_minutes=120, heat_index_f=80)
    fx.cancel_stop(api, scrubbed["id"], "route change")
    fx.confirm_stop(api, show["id"])
    fx.set_clock(api, "2027-06-22T09:00:00Z")
    fx.complete_stop(api, show["id"])
    settlement = fx.open_settlement(api, show["id"], 100000, 500000, 3)
    assert_show_settlement(settlement, status="DRAFT",
                           prepared_by_user_id=BUSINESS_MANAGER_ID,
                           provisional_prize_cents=80000,
                           provisional_gross_cents=180000,
                           provisional_circuit_fee_cents=7200,
                           provisional_net_cents=172800)

    finalized = fx.finalize_settlement(api, settlement["id"], 2, [])
    assert_show_settlement(finalized, status="FINALIZED",
                           finalized_by_user_id=SECOND_BUSINESS_MANAGER_ID,
                           final_prize_cents=110000, final_gross_cents=210000,
                           final_circuit_fee_cents=8400, final_net_cents=201600,
                           variance_cents=28800, provisional_net_cents=172800)
    assert_tour_stop(fx.get_stop(api, show["id"]), settlement_state="SETTLED")

    before = fx.get_season(api, season["id"])
    assert_season(before, ledger_status="OPEN", tour_revenue_cents=201600,
                  billing_epoch=0)

    swept = fx.run_sweep(api, season["id"])
    assert_season(swept, ledger_status="RECONCILED", billing_epoch=1,
                  tour_revenue_cents=201600)


def test_a_shift_is_approved_only_after_the_screener_clears_the_volunteer(api):
    """The refusal leaves the shift accepted and the load counter at zero.

    PRD: "The `TourManager` then approves it, moving it `ACCEPTED → APPROVED`,
    stamping `approved_by_user_id` with the approving user's `X-User-ID`, and
    increasing the volunteer's `assignment_count` by one."

    Design: Corner/state_machines/approving_a_staff_assignment_requires_a_cleared_screening
    """
    season = fx.create_season(api)
    stop = fx.create_rehearsal_stop(api, season["id"],
                                    venue_name="Rockford High School",
                                    arrive_at="2027-06-19T08:00:00Z",
                                    depart_at="2027-06-19T20:00:00Z",
                                    **REHEARSAL_SHAPE)
    volunteer = fx.create_volunteer(api, VolunteerRoleType.COOK,
                                    full_name="Rosa Cook")
    shift = fx.propose_shift(api, volunteer["id"], stop["id"], Duty.COOK,
                             "2027-06-19T09:00:00Z", "2027-06-19T19:00:00Z")
    fx.accept_shift(api, shift["id"], volunteer["id"])

    refused = api.approve_staff_assignment(shift["id"], TOUR_MANAGER_HEADERS)
    validate_error(refused, ApiErrorId.SCREENING_NOT_CLEARED, 409)
    assert_staff_assignment(fx.get_shift(api, shift["id"]), status="ACCEPTED")
    assert_volunteer(fx.get_volunteer(api, volunteer["id"]), assignment_count=0)

    cleared = fx.clear_volunteer(api, volunteer["id"], "2026-08-01")
    assert_volunteer(cleared, screening_status="CLEARED",
                     screening_decided_on="2026-08-01",
                     screening_expires_on="2027-08-01")

    approved = fx.approve_shift(api, shift["id"])
    assert_staff_assignment(approved, status="APPROVED",
                            approved_by_user_id=TOUR_MANAGER_ID)
    assert_volunteer(fx.get_volunteer(api, volunteer["id"]), assignment_count=1)
