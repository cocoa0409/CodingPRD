"""Reversals that must be partial: a forfeited seat, a non-double-refunded cancellation, and
a registry acceptance that restores a roster but not an insurance filing.
"""
from test_helpers import (
    acknowledge_accept,
    assignments_at_location,
    assert_seat_credit_ledger,
    cancel_session,
    enroll_server,
    get_account,
    get_certificate_row,
    get_enrollment_row,
    get_location,
    get_server,
    get_session,
    list_dram_shop_documents_for,
    lock_roster,
    mark_attendance,
    register_alcohol_server,
    set_clock,
    setup_documented_employer,
    setup_employer_account,
    setup_training_base,
    submissions_for_certificate,
    transmit_and_reject,
    transmit_certificate,
    withdraw_seat,
)

TWO_LOCATIONS = [
    {"location_name": "Alamo Taproom", "annual_premium_cents": 4821734},
    {"location_name": "Riverwalk Cantina", "annual_premium_cents": 1257444},
]
TRANSMIT_CLOCK = "2026-08-20T10:00:00Z"
RESUBMIT_CLOCK = "2026-08-27T10:00:00Z"


_EXTRA_SERVERS = [
    ("Bo Nakamura", "bo@example.com"),
    ("Cy Alvarez", "cy@example.com"),
]


def _sponsored_seats(count):
    """Claim `count` employer-credit seats from an 81-credit account on a SCHEDULED session."""
    base = setup_training_base()
    employer = setup_employer_account(base["jurisdiction"]["id"], location_specs=[])
    account_id = employer["account"]["id"]

    seats = []
    for index in range(count):
        if index == 0:
            server = register_alcohol_server(base["jurisdiction"]["id"])
        else:
            full_name, email = _EXTRA_SERVERS[index - 1]
            server = register_alcohol_server(base["jurisdiction"]["id"],
                                             full_name=full_name, email=email)
        seats.append(enroll_server(base["session"]["id"], server["id"],
                                   sponsoring_employer_account_id=account_id,
                                   headers=employer["employer_headers"]))
    return base, employer, seats


def _two_sponsored_seats_on_a_locked_roster():
    """Two employer-credit seats claimed from an 81-credit account, then the roster locked."""
    base, employer, seats = _sponsored_seats(2)
    lock_roster(base["session"]["id"], base["trainer_headers"])
    return base, employer, seats[0], seats[1]


def _three_sponsored_seats_with_one_already_withdrawn():
    """Three employer-credit seats, the third withdrawn and refunded before the cancellation."""
    base, employer, seats = _sponsored_seats(3)
    first_seat, second_seat, third_seat = seats
    withdraw_seat(third_seat["id"], employer["employer_headers"],
                  withdrawal_reason="hired elsewhere")
    lock_roster(base["session"]["id"], base["trainer_headers"])
    return base, employer, first_seat, second_seat, third_seat


def _reject_then_accept_the_registry_record():
    """Run the rejection cascade, then resubmit late and have the registry accept."""
    scenario = setup_documented_employer(location_specs=TWO_LOCATIONS,
                                         sponsor_enrollment=False)
    set_clock(TRANSMIT_CLOCK)
    first_submission = transmit_and_reject(scenario["certificate"]["id"], "NAME_MISMATCH")

    set_clock(RESUBMIT_CLOCK)
    second_submission = acknowledge_accept(
        transmit_certificate(scenario["certificate"]["id"])["id"])
    return scenario, first_submission, second_submission


class TestNoShowForfeitsWhileWithdrawalRefunds:
    def test_the_absent_seat_keeps_its_charge_and_the_withdrawn_seat_releases_it(self, api):
        """PRD §3.6: "A true value moves the seat `REGISTERED → ATTENDED`; a false value moves
        it `REGISTERED → NO_SHOW`. The asymmetry is fiscal and intentional: a no-show forfeits
        the seat, so no seat credit is refunded and `seat_credit_charged` stays true."
        PRD §3.5: "On success the seat moves to `WITHDRAWN`, the session's `enrolled_count` falls
        by one and the session's `version` rises by one; and when `seat_credit_charged` was true,
        the sponsor's `seat_credits_refunded_total` rises by one, `seat_credit_balance` rises by
        one, and `seat_credit_charged` becomes false."

        Design: Difficulty/compensating_invariant/no_show_forfeits_its_seat_credit_while_withdrawal_returns_one_to_the_balance
        """
        base, employer, absent_seat, leaving_seat = _two_sponsored_seats_on_a_locked_roster()

        mark_attendance(absent_seat["id"], False, base["trainer_headers"])
        withdraw_seat(leaving_seat["id"], employer["employer_headers"],
                      withdrawal_reason="transferred to a later class")

        forfeited = get_enrollment_row(absent_seat["id"])
        assert forfeited["enrollment_state"] == "NO_SHOW"
        assert forfeited["seat_credit_charged"] is True, (
            "a no-show forfeits the seat, so its charge stands")

        released = get_enrollment_row(leaving_seat["id"])
        assert released["enrollment_state"] == "WITHDRAWN"
        assert released["seat_credit_charged"] is False
        assert released["withdrawal_reason"] == "transferred to a later class"

    def test_the_ledger_reconciles_with_a_non_zero_forfeit_term(self, api):
        """PRD §3.8: "The seat-credit ledger is an identity that must hold at all times:
        `seat_credit_balance` equals `seat_credits_purchased_total` minus
        `seat_credits_consumed_total` plus `seat_credits_refunded_total`. Exactly one seat moves
        per event. An employer-sponsored enrollment consumes one; a withdrawal or a cascaded
        cancellation of a charged seat refunds one; a no-show moves nothing, leaving the balance
        debited."
        PRD §3.5: "The session must still be `SCHEDULED` — enrolling into a `ROSTER_LOCKED`
        session is `ERR_SESSION_INVALID_STATE` — and `enrolled_count` must be strictly less than
        `capacity`, otherwise `ERR_SESSION_AT_CAPACITY`."

        Design: Difficulty/compensating_invariant/no_show_forfeits_its_seat_credit_while_withdrawal_returns_one_to_the_balance
        """
        base, employer, absent_seat, leaving_seat = _two_sponsored_seats_on_a_locked_roster()

        mark_attendance(absent_seat["id"], False, base["trainer_headers"])
        withdraw_seat(leaving_seat["id"], employer["employer_headers"])

        account = get_account(employer["account"]["id"])
        assert account["seat_credits_purchased_total"] == 81
        assert account["seat_credits_consumed_total"] == 2
        assert account["seat_credits_refunded_total"] == 1, (
            "only the withdrawal returns a credit, got "
            f"{account['seat_credits_refunded_total']}")
        assert account["seat_credit_balance"] == 80, (
            "81 purchased minus 2 consumed plus 1 refunded is 80, got "
            f"{account['seat_credit_balance']}")
        assert_seat_credit_ledger(account)

        session = get_session(base["session"]["id"])
        assert session["enrolled_count"] == 1, (
            "the withdrawal decremented the headcount and the no-show did not, got "
            f"{session['enrolled_count']}")
        assert session["passed_count"] == 0
        assert session["session_status"] == "ROSTER_LOCKED"


class TestCancellationRefundsOnlyStillChargedSeats:
    def test_every_remaining_seat_is_withdrawn_and_the_earlier_reason_survives(self, api):
        """PRD §3.5: "Both the `SCHEDULED → CANCELLED` and the `ROSTER_LOCKED → CANCELLED` paths
        behave identically: the reason is recorded, every enrollment not already `WITHDRAWN`
        moves to `WITHDRAWN` in ascending enrollment `created_at`, `enrolled_count` becomes zero,
        and each of those enrollments whose `seat_credit_charged` was true refunds one seat
        credit to its sponsoring account."
        PRD §3.5: "Cancelling a class is available while its `session_status` is `SCHEDULED` or
        `ROSTER_LOCKED`, and requires a `cancellation_reason` from the caller."

        Design: Difficulty/compensating_invariant/session_cancellation_refunds_every_still_charged_seat_without_double_refunding_the_withdrawn_one
        """
        base, employer, first_seat, second_seat, third_seat = (
            _three_sponsored_seats_with_one_already_withdrawn())

        cancel_session(base["session"]["id"], cancellation_reason="venue flood")

        session = get_session(base["session"]["id"])
        assert session["session_status"] == "CANCELLED"
        assert session["cancellation_reason"] == "venue flood"
        assert session["enrolled_count"] == 0

        for seat in (first_seat, second_seat):
            cascaded = get_enrollment_row(seat["id"])
            assert cascaded["enrollment_state"] == "WITHDRAWN"
            assert cascaded["seat_credit_charged"] is False

        already_gone = get_enrollment_row(third_seat["id"])
        assert already_gone["enrollment_state"] == "WITHDRAWN"
        assert already_gone["seat_credit_charged"] is False
        assert already_gone["withdrawal_reason"] == "hired elsewhere", (
            "the cascade does not rewrite a reason recorded earlier, got "
            f"{already_gone['withdrawal_reason']}")

    def test_the_already_refunded_seat_is_not_refunded_twice(self, api):
        """PRD §3.8: "The seat-credit ledger is an identity that must hold at all times:
        `seat_credit_balance` equals `seat_credits_purchased_total` minus
        `seat_credits_consumed_total` plus `seat_credits_refunded_total`. Exactly one seat moves
        per event. An employer-sponsored enrollment consumes one; a withdrawal or a cascaded
        cancellation of a charged seat refunds one; a no-show moves nothing, leaving the balance
        debited."
        PRD §3.5: "Both the `SCHEDULED → CANCELLED` and the `ROSTER_LOCKED → CANCELLED` paths
        behave identically: the reason is recorded, every enrollment not already `WITHDRAWN`
        moves to `WITHDRAWN` in ascending enrollment `created_at`, `enrolled_count` becomes zero,
        and each of those enrollments whose `seat_credit_charged` was true refunds one seat
        credit to its sponsoring account."

        Design: Difficulty/compensating_invariant/session_cancellation_refunds_every_still_charged_seat_without_double_refunding_the_withdrawn_one
        """
        base, employer, first_seat, second_seat, third_seat = (
            _three_sponsored_seats_with_one_already_withdrawn())

        cancel_session(base["session"]["id"], cancellation_reason="venue flood")

        account = get_account(employer["account"]["id"])
        assert account["seat_credits_purchased_total"] == 81
        assert account["seat_credits_consumed_total"] == 3
        assert account["seat_credits_refunded_total"] == 3, (
            "the seat withdrawn before the cancellation is not refunded a second time, got "
            f"{account['seat_credits_refunded_total']}")
        assert account["seat_credit_balance"] == 81, (
            "81 purchased minus 3 consumed plus 3 refunded returns the full balance, got "
            f"{account['seat_credit_balance']}")
        assert_seat_credit_ledger(account)


class TestRegistryAcceptanceRestoresOnlyWhatItCan:
    def test_the_late_resubmission_is_priced_and_the_holder_is_restored(self, api):
        """PRD §3.7: "Otherwise `late_days` is the number of whole days between `due_at` and
        `transmitted_at` rounded **up**, so any part of a day counts — one second past `due_at`
        is already one late day."
        PRD §3.7: "An escalation factor grows with the transmission attempt: it is one plus five
        hundredths for each attempt beyond the first, so a first transmission carries a factor of
        one, a second 1.05, a third 1.10."
        PRD §3.7: "An accepted result moves the submission `TRANSMITTED → ACCEPTED` and sets the
        certificate's `registry_state` to `ACCEPTED`. If that certificate's `validity_state` was
        `SUSPENDED` and the logical clock is still strictly before its `expires_at`, the
        certificate additionally returns `SUSPENDED → ACTIVE`, and the recompute chain restores
        the holder: `work_eligibility` returns to `ELIGIBLE`, every `WORK_RESTRICTED` assignment
        of theirs returns to `ACTIVE` with `restriction_reason` back to `NONE`, and the affected
        location and account metrics are recomputed."

        Design: Difficulty/compensating_invariant/registry_acceptance_restores_the_assignment_but_never_revives_the_voided_dram_shop_document
        """
        scenario, first_submission, second_submission = (
            _reject_then_accept_the_registry_record())

        assert second_submission["attempt_number"] == 2
        assert second_submission["late_days"] == 2, (
            "2026-08-27T10:00:00Z is a day and sixteen hours past a 2026-08-25T18:30:00Z "
            f"deadline, rounded up to 2, got {second_submission['late_days']}")
        assert second_submission["penalty_fee_cents"] == 525, (
            "250 cents times 2 late days times a second-attempt factor of 1.05, got "
            f"{second_submission['penalty_fee_cents']}")
        assert second_submission["submission_state"] == "ACCEPTED"

        history = submissions_for_certificate(scenario["certificate"]["id"])
        assert [row["submission_state"] for row in history] == ["REJECTED", "ACCEPTED"], (
            "the refused row is kept, not rewritten, got "
            f"{[row['submission_state'] for row in history]}")

        certificate = get_certificate_row(scenario["certificate"]["id"])
        assert certificate["validity_state"] == "ACTIVE"
        assert certificate["registry_state"] == "ACCEPTED"

        server = get_server(scenario["server"]["id"])
        assert server["work_eligibility"] == "ELIGIBLE"
        assert server["active_certificate_id"] == scenario["certificate"]["id"]

        assignments = assignments_at_location(scenario["locations"][0]["id"],
                                              scenario["employer_headers"])
        assert len(assignments) == 1
        assert assignments[0]["assignment_state"] == "ACTIVE"
        assert assignments[0]["restriction_reason"] == "NONE"
        assert assignments[0]["restricted_at"] is None

    def test_the_voided_insurance_filing_is_never_revived(self, api):
        """PRD §2.8: "**Stage five — documentation floor.** If the account holds a
        `DramShopDocument` whose `document_state` is `ISSUED` and the recomputed
        `account_compliance_rate_pct` is below 80.00, that document moves to `VOIDED` with
        `void_reason` set to `COMPLIANCE_RATE_FELL_BELOW_FLOOR`, and the account's
        `dram_shop_discount_status` becomes `EXPIRED`."
        PRD §3.8: "The total live headcount is the sum of `assigned_server_count` over the
        account's locations; `account_compliance_rate_pct` is the sum of `compliant_server_count`
        divided by that total, multiplied by 100, rounded half up to two decimals — except that
        when the total live headcount is zero the account rate reads **0.00**, not 100.00."
        PRD §3.8: "Otherwise it is `COMPLIANT` at 95.00 or above, `AT_RISK` at 80.00 or above
        but below 95.00, and `NON_COMPLIANT` below 80.00."

        Design: Difficulty/compensating_invariant/registry_acceptance_restores_the_assignment_but_never_revives_the_voided_dram_shop_document
        """
        scenario, first_submission, second_submission = (
            _reject_then_accept_the_registry_record())

        location = get_location(scenario["locations"][0]["id"])
        assert location["restricted_server_count"] == 0
        assert location["compliance_rate_strict_pct"] == 100.00
        assert location["compliance_rate_grace_inclusive_pct"] == 100.00
        assert location["compliance_posture"] == "COMPLIANT"

        account = get_account(scenario["account"]["id"])
        assert account["account_compliance_rate_pct"] == 100.00

        documents = list_dram_shop_documents_for(scenario["account"]["id"],
                                                 scenario["employer_headers"])
        assert len(documents) == 1, (
            f"no replacement filing is created automatically, got {len(documents)}")
        assert documents[0]["document_state"] == "VOIDED", (
            "the insurer filing must be re-issued by hand, got "
            f"{documents[0]['document_state']}")
        assert documents[0]["void_reason"] == "COMPLIANCE_RATE_FELL_BELOW_FLOOR"
        assert account["dram_shop_discount_status"] == "EXPIRED", (
            "the discount does not return to ELIGIBLE on its own, got "
            f"{account['dram_shop_discount_status']}")
