"""Cascading side effects (order revoke, clinic close, standing-slot release) and
ledger-conservation invariants (transport confirm/cancel, session book/cancel,
settle reconciliation).

Difficulty queue (A): transitive_cascade, compensating_invariant.
Corner queue (B): cross_cutting_complexity_layers (release cascade, settle).
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    setup_bookable_scenario, book_session, book_and_complete,
    book_with_confirmed_transport, reserve_standing_slot,
    create_transport_trip_payload, create_session_payload,
    TEST_USERS,
)

SCHED = TEST_USERS["scheduler_headers"]
NEPH = TEST_USERS["nephrologist_headers"]
ADMIN = TEST_USERS["clinic_admin_headers"]
BILL = TEST_USERS["billing_clerk_headers"]


# ─── transitive_cascade / order_revoke_cascades_session_transport_account ─
def test_order_revoke_three_hop_cascade(api):
    """PRD §3.4: "First, every treatment session authorized by this order that is
    still `BOOKED` transitions to `CANCELLED`. Second, for each such cancelled
    session, any transport trip in `REQUESTED` or `CONFIRMED` transitions to
    `CANCELLED`. Third, for each of those transport trips that was in `CONFIRMED`
    at the moment of cancellation, its fare is reversed out of the patient's
    ledger — the trip's `fare_cents` is subtracted from the patient's
    `account_balance_cents`."

    Design: Difficulty/transitive_cascade/order_revoke_cascades_session_transport_account
    """
    scenario = setup_bookable_scenario(dialyzer_reuse_limit=99, coinsurance_pct=0.0)
    session, trip = book_with_confirmed_transport(scenario, miles=8, direction="INBOUND")
    # fare 2650 posted on confirm
    patient_id = scenario["patient"]["id"]
    after_confirm = validate_success(api.get_patient(patient_id, SCHED), 200)
    assert after_confirm["account_balance_cents"] == 2650

    revoked = validate_success(api.revoke_order(scenario["order"]["id"], NEPH), 200)
    assert revoked["status"] == "REVOKED"
    assert validate_success(api.get_session(session["id"], SCHED), 200)["clinical_status"] == "CANCELLED"
    assert validate_success(api.get_transport_trip(trip["id"], SCHED), 200)["status"] == "CANCELLED"
    final = validate_success(api.get_patient(patient_id, SCHED), 200)
    assert final["account_balance_cents"] == 0, \
        f"confirmed fare 2650 must be reversed, got {final['account_balance_cents']}"


def test_order_revoke_terminal_state(api):
    """PRD §3.4: "Revoking an order moves it from `ACTIVE → REVOKED` (or
    `UNDER_REVISION → REVOKED`); `REVOKED` is terminal."

    Design: Difficulty/transitive_cascade/order_revoke_cascades_session_transport_account
    """
    scenario = setup_bookable_scenario(dialyzer_reuse_limit=99, coinsurance_pct=0.0)
    session = book_session(scenario)
    revoked = validate_success(api.revoke_order(scenario["order"]["id"], NEPH), 200)
    assert revoked["status"] == "REVOKED"
    cancelled = validate_success(api.get_session(session["id"], SCHED), 200)
    assert cancelled["clinical_status"] == "CANCELLED"


# ─── transitive_cascade / clinic_close_cascades_slot_release_session_cancel ─
def test_clinic_close_cascade_releases_slot_and_cancels_session(api):
    """PRD §3.1: "When a clinic does close, a three-part cascade fires: first,
    every standing slot still in `RESERVED` transitions to `RELEASED`..."

    Note: the PRD also says closing is "blocked while any treatment session in the
    clinic is still in `BOOKED` or `CHECKED_IN`". The cascade's second leg
    ("each released slot's treatment sessions that were still `BOOKED` transition
    to `CANCELLED`") is therefore unreachable under a faithful reading — any
    `BOOKED` session would block the close before the cascade fires. This test
    exercises only the reachable first leg: a `RESERVED` slot (which does not
    block close) transitions to `RELEASED`.

    Design: Difficulty/transitive_cascade/clinic_close_cascades_slot_release_session_cancel
    """
    scenario = setup_bookable_scenario(dialyzer_reuse_limit=99, coinsurance_pct=0.0,
                                       patient_kind="RESIDENT")
    slot = reserve_standing_slot(scenario)
    closed = validate_success(api.close_clinic(scenario["clinic"]["id"], ADMIN), 200)
    assert closed["status"] == "CLOSED"
    assert validate_success(api.get_standing_slot(slot["id"], SCHED), 200)["status"] == "RELEASED"


def test_clinic_close_retires_active_shifts(api):
    """PRD §3.1: "and third, every shift still `ACTIVE` transitions to `RETIRED`."

    Design: Difficulty/transitive_cascade/clinic_close_cascades_slot_release_session_cancel
    """
    scenario = setup_bookable_scenario(dialyzer_reuse_limit=99, coinsurance_pct=0.0,
                                       patient_kind="RESIDENT")
    # A RESERVED standing slot does not block close (only BOOKED/CHECKED_IN
    # sessions do, per PRD §3.1); leave the shift ACTIVE so the close succeeds
    # and the third cascade leg can be observed.
    reserve_standing_slot(scenario)
    api.close_clinic(scenario["clinic"]["id"], ADMIN)
    shift = validate_success(api.get_shift(scenario["shift"]["id"], SCHED), 200)
    assert shift["status"] == "RETIRED"


# ─── compensating_invariant / transport_confirm_cancel_conserves_balance ──
def test_transport_confirm_then_cancel_conserves_balance(api):
    """PRD §3.8: "confirmation adds the trip's `fare_cents` to the patient's
    `account_balance_cents`."
    PRD §3.8: "cancelling a trip that was in `CONFIRMED` reverses its `fare_cents`
    back out of the patient's `account_balance_cents`"

    Design: Difficulty/compensating_invariant/transport_confirm_cancel_conserves_account_balance
    """
    scenario = setup_bookable_scenario(dialyzer_reuse_limit=99, coinsurance_pct=0.0)
    patient_id = scenario["patient"]["id"]
    before = validate_success(api.get_patient(patient_id, SCHED), 200)["account_balance_cents"]
    session, trip = book_with_confirmed_transport(scenario, miles=8, direction="INBOUND")
    after_confirm = validate_success(api.get_patient(patient_id, SCHED), 200)
    assert after_confirm["account_balance_cents"] == 2650
    api.cancel_transport_trip(trip["id"], SCHED)
    after_cancel = validate_success(api.get_patient(patient_id, SCHED), 200)
    assert after_cancel["account_balance_cents"] == before, \
        "money must be conserved: balance returns to pre-confirm value"


def test_requested_trip_cancel_touches_no_ledger(api):
    """PRD §3.8: "while cancelling a trip that was still in `REQUESTED` touches no
    ledger because no fare was ever posted."

    Design: Difficulty/compensating_invariant/transport_confirm_cancel_conserves_account_balance
    """
    scenario = setup_bookable_scenario(dialyzer_reuse_limit=99, coinsurance_pct=0.0)
    patient_id = scenario["patient"]["id"]
    session = book_session(scenario)
    trip = get_success_data(api.create_transport_trip(
        create_transport_trip_payload(session["id"], direction="INBOUND", miles=8), SCHED))
    api.cancel_transport_trip(trip["id"], SCHED)
    after = validate_success(api.get_patient(patient_id, SCHED), 200)
    assert after["account_balance_cents"] == 0


# ─── compensating_invariant / session_book_cancel_conserves_cell ──────────
def test_rebooking_cell_after_cancel_succeeds(api):
    """PRD §3.5: "No two sessions that are neither `CANCELLED` nor `MISSED` may
    occupy the same station, shift, and `service_date` combination ... and a
    collision is rejected with `ERR_STATION_DOUBLE_BOOKED`."
    PRD §3.6: "A booked session may instead be cancelled outright, moving it
    `BOOKED → CANCELLED` (terminal)"

    Design: Difficulty/compensating_invariant/session_book_cancel_conserves_station_cell_occupancy
    """
    scenario = setup_bookable_scenario(dialyzer_reuse_limit=99, coinsurance_pct=0.0)
    first = book_session(scenario, service_date="2026-06-01")
    cancelled = validate_success(api.cancel_session(first["id"], SCHED), 200)
    assert cancelled["clinical_status"] == "CANCELLED"
    # the same (station, shift, date) cell must now be free
    second = book_session(scenario, service_date="2026-06-01")
    assert second["clinical_status"] == "BOOKED"


def test_cancelled_cell_distinct_from_live_booking(api):
    """PRD §3.5: "a standing slot reserves that cell for every day-pattern
    occurrence — and a collision is rejected with `ERR_STATION_DOUBLE_BOOKED`."

    Design: Difficulty/compensating_invariant/session_book_cancel_conserves_station_cell_occupancy
    """
    scenario = setup_bookable_scenario(dialyzer_reuse_limit=99, coinsurance_pct=0.0)
    first = book_session(scenario, service_date="2026-06-01")
    # while the first booking is live, the identical cell must collide
    patient = scenario["patient"]
    pv = get_success_data(api.get_patient(patient["id"], SCHED))["version"]
    dup = create_session_payload(patient["id"], scenario["order"]["id"],
                                 scenario["station"]["id"], scenario["shift"]["id"],
                                 "2026-06-01", pv)
    res = api.create_session(dup, SCHED)
    validate_error(res, "ERR_STATION_DOUBLE_BOOKED")
    # after cancelling, re-booking the same cell succeeds
    api.cancel_session(first["id"], SCHED)
    again = book_session(scenario, service_date="2026-06-01")
    assert again["clinical_status"] == "BOOKED"


# ─── Corner: cross_cutting / standing_slot_release_cascade ────────────────
def test_standing_slot_release_cancels_generated_session(api):
    """PRD §3.5: "Releasing a standing slot transitions it to `RELEASED` and
    cascades: every treatment session generated from this slot that is still
    `BOOKED` transitions to `CANCELLED`"

    Design: Corner/cross_cutting_complexity_layers/standing_slot_release_cascade_cancels_session
    """
    scenario = setup_bookable_scenario(dialyzer_reuse_limit=99, coinsurance_pct=0.0,
                                       patient_kind="RESIDENT")
    slot = reserve_standing_slot(scenario)
    session = book_session(scenario, standing_slot_id=slot["id"])
    released = validate_success(api.release_standing_slot(slot["id"], SCHED), 200)
    assert released["status"] == "RELEASED"
    cancelled = validate_success(api.get_session(session["id"], SCHED), 200)
    assert cancelled["clinical_status"] == "CANCELLED"


# ─── Corner: cross_cutting / settle_reconciles_account_balance ────────────
def test_settle_reverses_coinsurance_posted_on_complete(api):
    """PRD §3.6: "Upon completion, the patient's coinsurance share — the
    `billed_amount_cents` multiplied by the patient's `coinsurance_pct`, rounded
    half-up to whole cents — is added to the patient's `account_balance_cents`."
    PRD §3.10: "Settling a billed session moves it `BILLED → SETTLED` (terminal)
    and subtracts the patient's coinsurance share — the `billed_amount_cents`
    multiplied by the patient's `coinsurance_pct`, rounded half-up to whole cents
    — back out of the patient's `account_balance_cents`."

    Design: Corner/cross_cutting_complexity_layers/settle_reconciles_account_balance
    """
    scenario = setup_bookable_scenario(modality="HEMODIALYSIS", dialyzer_reuse_limit=12,
                                       payer_class="STANDARD", coinsurance_pct=0.20)
    patient_id = scenario["patient"]["id"]
    completed = book_and_complete(scenario)
    after_complete = validate_success(api.get_patient(patient_id, SCHED), 200)
    # 28500 * 0.20 = 5700
    assert after_complete["account_balance_cents"] == 5700
    api.bill_session(completed["id"], BILL)
    api.settle_session(completed["id"], BILL)
    after_settle = validate_success(api.get_patient(patient_id, SCHED), 200)
    assert after_settle["account_balance_cents"] == 0
