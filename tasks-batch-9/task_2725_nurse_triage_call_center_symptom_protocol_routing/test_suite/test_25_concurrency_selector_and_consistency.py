"""The version handshake, the deterministic selector, and immediate consistency."""

import pytest

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_cents,
    assert_instant,
    assert_version_is,
    assert_whole_minutes,
)


@pytest.fixture
def assessed_call_and_the_version_read_before_the_assessment(world):
    """Walk the call to ASSESSING, keeping the version read right after assignment."""
    world.bootstrap(
        clock="2026-08-03T14:30:00Z",
        nurse_keys=("nurse_a",),
        protocol={"base_severity": 62},
    )
    call = world.open_call(reason_text="chest discomfort")
    identified = world.match_patient(call["id"], world.patients["patient"]["id"])
    consented = world.record_consent(call["id"])
    assigned = world.assign_nurse(call["id"], "nurse_a")
    assessment = world.create_assessment(call["id"], "nurse_a", "protocol")
    return {
        "call": call,
        "identified": identified,
        "consented": consented,
        "assigned": assigned,
        "assessment": assessment,
    }


class TestStaleExpectedCallVersionOnDispositionCreate:
    def test_every_intake_write_bumps_the_call_version_by_one(
        self, world, assessed_call_and_the_version_read_before_the_assessment
    ):
        """PRD §2.7: "Any write that bumps the call's `version` — binding a patient,
        recording consent, a successful nurse assignment, an assignment attempt that
        found no eligible nurse, a new protocol assessment, a supervisor override, a
        completion, a reopen or an abandonment — invalidates a version the client read
        earlier."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_call_version_on_disposition_create_returns_412
        """
        walk = assessed_call_and_the_version_read_before_the_assessment

        assert_version_is(walk["call"], 1, "version on create")
        assert_version_is(walk["identified"], 2, "version after match-patient")
        assert_version_is(walk["consented"], 3, "version after consent")
        assert_version_is(walk["assigned"], 4, "version after assign-nurse")
        assert_version_is(world.call(walk["call"]["id"]), 5, "version after assessment")

    def test_the_pre_assessment_version_is_refused_with_412(
        self, world, assessed_call_and_the_version_read_before_the_assessment
    ):
        """PRD §2.7: "If that value does not equal the call's current `version`, the
        create is rejected with `ERR_STALE_CALL_VERSION` (HTTP 412) and nothing is
        written."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_call_version_on_disposition_create_returns_412
        """
        walk = assessed_call_and_the_version_read_before_the_assessment
        stale_version = walk["assigned"]["version"]

        response = world.api.create_disposition(
            f.disposition_payload(
                walk["call"]["id"],
                walk["assessment"]["id"],
                "ED_NOW",
                stale_version,
            ),
            world.nurse_headers("nurse_a"),
        )

        validate_error(response, ApiErrorId.ERR_STALE_CALL_VERSION, 412)
        after = world.call(walk["call"]["id"])
        assert_version_is(after, 5, "the refusal wrote nothing")
        assert after["status"] == "ASSESSING", "the call state was never the problem"
        _, meta = validate_paginated(
            world.api.list_dispositions(world.admin, {"call_id": walk["call"]["id"]})
        )
        assert meta["total_count"] == 0

    def test_the_freshly_re_read_version_makes_the_identical_body_succeed(
        self, world, assessed_call_and_the_version_read_before_the_assessment
    ):
        """PRD §2.7: "A `POST /dispositions` request, which creates a `Disposition`
        against a `TriageCall`, must carry `expected_call_version`, a non-optional integer
        field holding the `version` of the target `TriageCall` as the client last observed
        it."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_call_version_on_disposition_create_returns_412
        """
        walk = assessed_call_and_the_version_read_before_the_assessment
        world.api.create_disposition(
            f.disposition_payload(
                walk["call"]["id"],
                walk["assessment"]["id"],
                "ED_NOW",
                walk["assigned"]["version"],
            ),
            world.nurse_headers("nurse_a"),
        )
        fresh = world.call(walk["call"]["id"])

        disposition = world.create_disposition(
            walk["call"]["id"],
            walk["assessment"]["id"],
            "ED_NOW",
            "nurse_a",
            expected_call_version=fresh["version"],
        )

        assert fresh["status"] == "ASSESSING"
        assert_version_is(fresh, 5, "the fresh version")
        assert disposition["advice_status"] == "AUTHORIZED"
        closed_over = world.call(walk["call"]["id"])
        assert_version_is(closed_over, 6, "the accepted create bumped the call once")
        assert closed_over["status"] == "DISPOSITIONED"


@pytest.fixture
def three_candidates_and_three_waiting_calls(world):
    """A junior nurse registered first, then two equally senior nurses."""
    world.set_clock("2026-08-03T14:30:00Z")
    world.create_practice()
    roster = (
        ("nurse_junior", "Jun Park", 2, "CA-10001"),
        ("nurse_senior_early", "Senior Early", 4, "CA-10002"),
        ("nurse_senior_late", "Senior Late", 4, "CA-10003"),
    )
    for key, name, seniority, number in roster:
        world.create_nurse(
            key,
            full_name=name,
            seniority_level=seniority,
            max_concurrent_calls=2,
            high_risk_cap=2,
        )
        world.add_license(
            key, state_code="CA", license_number=number, expires_on="2027-01-31"
        )
        world.add_shift(
            key, start_utc="2026-08-03T12:00:00Z", end_utc="2026-08-03T20:00:00Z"
        )
    world.create_patient("patient")
    calls = [
        world.call_through_consent(reason_text=reason)
        for reason in ("call one", "call two", "call three")
    ]
    return calls


class TestSelectorRanksByLoadThenSeniorityThenCreatedAt:
    def test_the_first_pick_falls_to_the_earlier_of_two_equally_senior_nurses(
        self, world, three_candidates_and_three_waiting_calls
    ):
        """PRD §3.4: "remaining ties are broken by `created_at` ascending, so the nurse
        registered earlier wins."

        Design: Corner/cross_cutting_complexity_layers/selector_policy_ranks_by_load_then_seniority_then_created_at
        """
        call_1, _, _ = three_candidates_and_three_waiting_calls

        assigned = world.assign_nurse(call_1["id"])

        assert assigned["status"] == "ASSIGNED"
        assert assigned["assigned_nurse_id"] == world.nurse_id("nurse_senior_early")
        assert assigned["deferred_assignment_count"] == 0

    def test_the_second_pick_falls_to_seniority_once_the_winner_is_loaded(
        self, world, three_candidates_and_three_waiting_calls
    ):
        """PRD §3.4: "ties are broken by `seniority_level` descending, so the more senior
        of two equally loaded nurses wins".

        Design: Corner/cross_cutting_complexity_layers/selector_policy_ranks_by_load_then_seniority_then_created_at
        """
        call_1, call_2, _ = three_candidates_and_three_waiting_calls
        world.assign_nurse(call_1["id"])

        assigned = world.assign_nurse(call_2["id"])

        assert assigned["assigned_nurse_id"] == world.nurse_id("nurse_senior_late")

    def test_the_third_pick_falls_to_the_least_loaded_nurse(
        self, world, three_candidates_and_three_waiting_calls
    ):
        """PRD §3.4: "Candidates are ordered first by `active_call_load` ascending, so the
        least-loaded nurse wins".

        Design: Corner/cross_cutting_complexity_layers/selector_policy_ranks_by_load_then_seniority_then_created_at
        """
        call_1, call_2, call_3 = three_candidates_and_three_waiting_calls
        world.assign_nurse(call_1["id"])
        world.assign_nurse(call_2["id"])

        assigned = world.assign_nurse(call_3["id"])

        assert assigned["assigned_nurse_id"] == world.nurse_id("nurse_junior")
        assert_instant(assigned["assigned_at"], "2026-08-03T14:30:00Z", "assigned_at")
        for key in ("nurse_junior", "nurse_senior_early", "nurse_senior_late"):
            assert world.nurse(key)["active_call_load"] == 1, key


@pytest.fixture
def dispositioned_call_awaiting_its_billing(world):
    """An ED_NOW call ready to close, with the practice ledgers still empty."""
    world.bootstrap(
        clock="2026-08-03T14:30:00Z",
        nurse_keys=("nurse_a",),
        practice={"audit_period_start_utc": "2026-08-01T00:00:00Z"},
        protocol={"base_severity": 62},
    )
    call, assessment, disposition = world.dispositioned_call(
        "ED_NOW", "nurse_a", red_flag_count=1, reason_text="chest discomfort"
    )
    before = get_success_data(
        world.api.get_after_hours_invoice(
            world.practice_id, world.liaison_headers(world.practice_id)
        )
    )
    return call, disposition, before


class TestCompletionLedgerIsImmediatelyConsistent:
    def test_the_invoice_is_all_zeroes_before_the_call_closes(
        self, world, dispositioned_call_awaiting_its_billing
    ):
        """PRD §3.10: "Step one sets `advice_subtotal_cents` to the practice's
        `advice_fee_accrued_cents`, and the readout also surfaces
        `billed_advice_minutes_total` and `escalated_callback_count` unchanged so the
        arithmetic can be checked."

        Design: Corner/consistency_model/completion_ledger_is_readable_in_the_same_response_and_the_next_read
        """
        _, _, before = dispositioned_call_awaiting_its_billing

        assert_cents(before["advice_subtotal_cents"], 0, "advice_subtotal_cents")
        assert_whole_minutes(
            before["billed_advice_minutes_total"], 0, "billed_advice_minutes_total"
        )
        assert_cents(before["invoice_total_cents"], 0, "invoice_total_cents")

    def test_the_completion_response_itself_already_carries_the_money(
        self, world, dispositioned_call_awaiting_its_billing
    ):
        """PRD §3.9: "First, `billable_minutes` is `handle_minutes` rounded **up** to the
        next whole multiple of five: thirteen minutes bills as fifteen, eighteen as
        twenty, twenty-eight as thirty, and exactly twenty bills as twenty with no
        inflation to twenty-five."

        Design: Corner/consistency_model/completion_ledger_is_readable_in_the_same_response_and_the_next_read
        """
        call, _, _ = dispositioned_call_awaiting_its_billing

        closed = world.complete_call(call["id"], "nurse_a", handle_minutes=12)

        assert closed["status"] == "CLOSED"
        assert closed["handle_minutes"] == 12
        assert_whole_minutes(closed["billable_minutes"], 15, "billable_minutes")
        assert_cents(closed["advice_fee_cents"], 63, "advice_fee_cents")

    def test_the_very_next_invoice_read_already_agrees_with_it(
        self, world, dispositioned_call_awaiting_its_billing
    ):
        """PRD §3.9: "The practice ledgers then accumulate the already-rounded per-call
        figures: `billed_advice_minutes_total` is credited with this call's
        `billable_minutes` and `advice_fee_accrued_cents` is credited with this call's
        `advice_fee_cents`."

        Design: Corner/consistency_model/completion_ledger_is_readable_in_the_same_response_and_the_next_read
        """
        call, _, _ = dispositioned_call_awaiting_its_billing
        world.complete_call(call["id"], "nurse_a", handle_minutes=12)

        after = get_success_data(
            world.api.get_after_hours_invoice(
                world.practice_id, world.liaison_headers(world.practice_id)
            )
        )

        assert_cents(after["advice_subtotal_cents"], 63, "advice_subtotal_cents")
        assert_whole_minutes(
            after["billed_advice_minutes_total"], 15, "billed_advice_minutes_total"
        )
        assert after["coverage_credit_pct"] == 0
        assert_cents(after["invoice_total_cents"], 63, "invoice_total_cents")
        practice = world.practice()
        assert_cents(practice["advice_fee_accrued_cents"], 63, "advice_fee_accrued_cents")
        assert_whole_minutes(
            practice["billed_advice_minutes_total"], 15, "billed_advice_minutes_total"
        )
        assert world.nurse("nurse_a")["active_call_load"] == 0
