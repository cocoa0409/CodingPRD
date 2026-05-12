"""Concurrency, OCC, and event idempotency (PRD §2.4, §2.9, §3.7, §3.8, §3.9)."""
from __future__ import annotations

import math

import pytest

from test_helpers import (
    TEST_USERS,
    admit_hospitalization,
    advance_clock_seconds,
    approve_prescription,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    create_bill,
    create_cage,
    create_drug,
    create_hospitalization_payload,
    create_prescription,
    dispense_prescription,
    issue_bill,
    make_drafting_vet_headers,
    make_prescription_item,
    make_reviewing_vet_headers,
    pay_bill,
    payment_payload,
    recompute_bill,
    reject_prescription_payload,
    run_race,
    setup_approved_prescription,
    setup_visit_consult_done,
    setup_visit_in_consult,
    submit_prescription,
    unique_event_id,
    validate_error,
    validate_error_is_one_of,
    validate_success,
    vet_headers_for_visit,
)


class TestApproveRejectRace:
    def test_approve_and_reject_concurrent_one_wins(self, api):
        """PRD §3.7: 'When an approve and a reject arrive concurrently
        for the same PENDING_REVIEW prescription, exactly one operation
        succeeds and the loser sees ERR_INVALID_STATE because the
        prescription has already moved out of PENDING_REVIEW.'"""
        owner, pet, visit = setup_visit_in_consult(weight_kg=10.0)
        from test_helpers import get_visit
        v = get_visit(visit["id"])
        drafting_id = v["assigned_vet_id"]
        d1 = create_drug(stock_units=200)
        item = make_prescription_item(
            drug_code=d1["code"], dose_mg_per_kg=2.0,
            frequency_per_day=2, duration_days=5,
            units=math.ceil(2.0 * 10.0 * 2 * 5),
        )
        rx = create_prescription(
            visit_id=visit["id"], items=[item], drafting_vet_id=drafting_id,
        )
        rx = submit_prescription(rx_id=rx["id"], drafting_vet_id=drafting_id)

        approve_headers = make_reviewing_vet_headers("rev-A-001")
        reject_headers = make_reviewing_vet_headers("rev-B-001")

        results = run_race(
            lambda: api.approve_prescription(rx["id"], approve_headers, {}),
            lambda: api.reject_prescription(
                rx["id"],
                reject_prescription_payload(rejection_reason="race"),
                reject_headers,
            ),
        )
        # Exactly one 2xx, one 4xx.
        outcome = assert_race_outcome(
            results, expected_successes=1, expected_failures=1,
        )
        # The loser must be ERR_INVALID_STATE per PRD §3.7.
        loser = outcome["failures"][0]
        validate_error(loser, "ERR_INVALID_STATE")


class TestDoubleApproveRace:
    def test_two_approves_concurrent_one_wins(self, api):
        """PRD §3.7: 'Two simultaneous approvals on the same prescription
        serialize first-writer-wins on the prescription's status: exactly
        one approve succeeds, and the loser receives
        ERR_PRESCRIPTION_ALREADY_REVIEWED because its version field is
        stale relative to the now-APPROVED row.'"""
        owner, pet, visit = setup_visit_in_consult(weight_kg=10.0)
        from test_helpers import get_visit
        v = get_visit(visit["id"])
        drafting_id = v["assigned_vet_id"]
        d1 = create_drug(stock_units=200)
        item = make_prescription_item(
            drug_code=d1["code"], dose_mg_per_kg=2.0,
            frequency_per_day=2, duration_days=5,
            units=math.ceil(2.0 * 10.0 * 2 * 5),
        )
        rx = create_prescription(
            visit_id=visit["id"], items=[item], drafting_vet_id=drafting_id,
        )
        rx = submit_prescription(rx_id=rx["id"], drafting_vet_id=drafting_id)

        a = make_reviewing_vet_headers("rev-A-001")
        b = make_reviewing_vet_headers("rev-B-001")
        results = run_race(
            lambda: api.approve_prescription(rx["id"], a, {}),
            lambda: api.approve_prescription(rx["id"], b, {}),
        )
        outcome = assert_race_outcome(
            results, expected_successes=1, expected_failures=1,
        )
        loser = outcome["failures"][0]
        validate_error(loser, "ERR_PRESCRIPTION_ALREADY_REVIEWED")


class TestDoubleDispenseRace:
    def test_dispense_twice_only_one_decrements_stock(self, api):
        """PRD §3.7: 'When two dispenses race for the same approved
        prescription, drug stock is decremented exactly once for that
        prescription; the second dispense is rejected with
        ERR_INVALID_STATE because status has already advanced past
        APPROVED.'"""
        owner, pet, visit = setup_visit_in_consult(weight_kg=10.0)
        d1 = create_drug(stock_units=500)
        rx = setup_approved_prescription(
            visit_id=visit["id"], drug_code=d1["code"],
            pet_weight_kg=10.0,
        )
        results = run_race(
            lambda: api.dispense_prescription(
                rx["id"], TEST_USERS["pharmacist_headers"]
            ),
            lambda: api.dispense_prescription(
                rx["id"], TEST_USERS["pharmacist_headers"]
            ),
        )
        outcome = assert_race_outcome(
            results, expected_successes=1, expected_failures=1,
        )
        loser = outcome["failures"][0]
        validate_error(loser, "ERR_INVALID_STATE")


class TestCageCapacityRace:
    def test_two_admissions_at_capacity_one_loses(self, api):
        """PRD §3.8: 'When two hospitalization-create requests race for
        the same cage at its capacity boundary, the cage's atomic
        check-and-increment guarantees that at most one assignment can
        push occupancy_count up to capacity; the other request is
        rejected with ERR_CAGE_CAPACITY_EXCEEDED.'"""
        cage = create_cage(capacity=1)
        owner_a, pet_a, visit_a, _ = setup_visit_consult_done(deposit_cents=200_000)
        owner_b, pet_b, visit_b, _ = setup_visit_consult_done(deposit_cents=200_000)
        headers_a = vet_headers_for_visit(visit_a["id"])
        headers_b = vet_headers_for_visit(visit_b["id"])
        results = run_race(
            lambda: api.create_hospitalization(
                create_hospitalization_payload(
                    visit_id=visit_a["id"], cage_id=cage["id"],
                ),
                headers_a,
            ),
            lambda: api.create_hospitalization(
                create_hospitalization_payload(
                    visit_id=visit_b["id"], cage_id=cage["id"],
                ),
                headers_b,
            ),
        )
        outcome = assert_race_outcome(
            results, expected_successes=1, expected_failures=1,
        )
        loser = outcome["failures"][0]
        validate_error(loser, "ERR_CAGE_CAPACITY_EXCEEDED")


class TestPaymentEventIdempotency:
    def test_two_payments_same_event_id_one_applied(self, api, platform_admin_headers):
        """PRD §3.9: 'Two simultaneous payment events with the same
        event_id serialize on that key — exactly one is applied, the
        other is a no-op rejected with ERR_DUPLICATE_EVENT.'"""
        owner, pet, visit, tr = setup_visit_consult_done(deposit_cents=0)
        bill = create_bill(visit_id=visit["id"])
        bill = recompute_bill(bill_id=bill["id"])
        bill = issue_bill(bill_id=bill["id"])
        amount_due = bill["provisional_total_cents"]
        assert amount_due >= 1, (
            "Need at least 1 cent due to exercise the duplicate-event branch"
        )
        ev_id = unique_event_id("evt-race")
        results = run_race(
            lambda: api.post_payment(
                payment_payload(
                    bill_id=bill["id"], amount_cents=amount_due, event_id=ev_id,
                ),
                platform_admin_headers,
            ),
            lambda: api.post_payment(
                payment_payload(
                    bill_id=bill["id"], amount_cents=amount_due, event_id=ev_id,
                ),
                platform_admin_headers,
            ),
        )
        outcome = assert_race_outcome(
            results, expected_successes=1, expected_failures=1,
        )
        loser = outcome["failures"][0]
        validate_error(loser, "ERR_DUPLICATE_EVENT")
