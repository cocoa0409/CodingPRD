"""Rows carrying two state dimensions that advance on separate tracks.

An application's merits dimension cycles while its evidentiary dimension stands
still, a tract's payment dimension cycles while its acquisition dimension rests
in a terminal state, and a certificate's posture oscillates while its status
never moves.
"""

from test_helpers import ApiErrorId, assert_score, assert_timestamp_equals, validate_error
from test_helpers import factories as f
from test_helpers import fixtures as fx


class TestApplicationDeficiencyCycle:
    """The review dimension cycles; the record dimension never opens."""

    def test_amendment_restarts_the_statutory_clock_without_opening_the_record(self, api):
        """PRD §3.6: "A successful amendment increments `amendment_round`, clears
        `deficiency_note` back to null, moves the application `DEFICIENT →
        FILED`, resets `filed_at` to the current logical clock reading and
        recomputes `decision_deadline_at` from it".

        Design: Difficulty/non_linear_state_machine/application_deficiency_amendment_cycle_leaves_record_dimension_untouched
        """
        ctx = fx.setup_filed_application(api)
        fx.review_application(
            api, ctx, outcome="REJECT",
            deficiency_note="Alternate route impact assessment missing",
        )
        fx.set_clock(api, "2026-09-15T00:00:00Z")
        application = fx.amend_application(api, ctx)

        assert application["review_status"] == "FILED", (
            f"The amendment returns the merits dimension to FILED, got "
            f"{application['review_status']}"
        )
        assert application["record_status"] == "NOT_OPENED", (
            "The evidentiary dimension never opened, so it is still NOT_OPENED, got "
            f"{application['record_status']}"
        )
        assert application["amendment_round"] == 1, (
            f"One amendment has been accepted, got {application['amendment_round']}"
        )
        assert application.get("deficiency_note") is None, (
            f"The amendment clears the deficiency note, got "
            f"{application.get('deficiency_note')!r}"
        )
        assert application["version"] == 3, (
            "Creation, the deficiency return and the amendment are three writes, so "
            f"version should be 3, got {application['version']}"
        )
        assert_timestamp_equals(application["filed_at"], "2026-09-15T00:00:00Z", "filed_at")
        assert_timestamp_equals(
            application["decision_deadline_at"], "2027-09-15T00:00:00Z", "decision_deadline_at"
        )
        project = fx.read_project(api, ctx)
        assert project["schedule_posture"] == "ON_TRACK", (
            "A 2027-09-15 deadline still leaves more than 180 days before the "
            f"2028-04-01 in-service date, got {project['schedule_posture']}"
        )

    def test_third_amendment_is_refused_with_the_record_still_unopened(self, api):
        """PRD §3.6: "The `FILED → DEFICIENT → FILED` cycle may therefore run at
        most twice."

        Design: Difficulty/non_linear_state_machine/application_deficiency_amendment_cycle_leaves_record_dimension_untouched
        """
        ctx = fx.setup_filed_application(api)
        for round_number in (1, 2):
            fx.review_application(
                api, ctx, outcome="REJECT",
                deficiency_note=f"Deficiency round {round_number}",
            )
            application = fx.amend_application(
                api, ctx, summary=f"Amendment round {round_number}"
            )
            assert application["amendment_round"] == round_number, (
                f"amendment_round should be {round_number}, got "
                f"{application['amendment_round']}"
            )
            assert application["record_status"] == "NOT_OPENED", (
                "Cycling the merits dimension leaves the record dimension alone, got "
                f"{application['record_status']}"
            )

        fx.review_application(
            api, ctx, outcome="REJECT", deficiency_note="Deficiency round 3",
        )
        response = api.amend_application(
            ctx["app"],
            f.amendment_payload(ctx["app_version"], amendment_summary="Amendment round 3"),
            fx.DEVELOPER_FILER_HEADERS,
        )
        validate_error(response, ApiErrorId.AMENDMENT_LIMIT_REACHED, expected_status=409)

        application = fx.read_application(api, ctx["app"])
        assert application["amendment_round"] == 2, (
            "The refused amendment leaves the round count at its cap of 2, got "
            f"{application['amendment_round']}"
        )
        assert application["review_status"] == "DEFICIENT", (
            "The refused amendment leaves the merits dimension at DEFICIENT, got "
            f"{application['review_status']}"
        )
        assert application["record_status"] == "NOT_OPENED", (
            f"The record dimension is still NOT_OPENED, got {application['record_status']}"
        )


class TestTractPaymentCycle:
    """The payment dimension cycles; the acquisition dimension stays AGREED."""

    def test_rescinded_tract_can_be_paid_again_from_the_escrow_ledger(self, api):
        """PRD §3.8: "A rescinded tract can be paid again — `RESCINDED → PAID`
        runs the same checks and debits the escrow ledger afresh".

        Design: Difficulty/non_linear_state_machine/tract_payment_rescission_cycle_independent_of_acquisition_dimension
        """
        ctx = fx.setup_issued_certificate(api)
        fx.setup_paid_tract(api, ctx)
        fx.rescind_payment(api, ctx)
        fx.set_clock(api, "2026-10-20T00:00:00Z")
        tract = fx.pay_tract(api, ctx, payment_reference="WIRE-2")

        assert tract["payment_status"] == "PAID", (
            f"The second disbursement moves RESCINDED -> PAID, got "
            f"{tract['payment_status']}"
        )
        assert tract["acquisition_status"] == "AGREED", (
            "The acquisition dimension rests at AGREED throughout, got "
            f"{tract['acquisition_status']}"
        )
        assert tract["paid_amount_cents"] == 4163406, (
            f"The re-payment pays the committed figure again, got "
            f"{tract['paid_amount_cents']}"
        )
        assert tract["agreed_compensation_cents"] == 4163406, (
            "The agreed figure was frozen at acceptance and is untouched, got "
            f"{tract['agreed_compensation_cents']}"
        )
        assert_timestamp_equals(tract["paid_at"], "2026-10-20T00:00:00Z", "paid_at")
        project = fx.read_project(api, ctx)
        assert project["escrow_balance_cents"] == 595836594, (
            f"600000000 less 4163406 leaves 595836594 cents, got "
            f"{project['escrow_balance_cents']}"
        )
        assert project["escrow_disbursed_cents"] == 4163406, (
            f"The disbursed total is back to one payment, got "
            f"{project['escrow_disbursed_cents']}"
        )

    def test_acquisition_dimension_never_moves_across_the_payment_cycle(self, api):
        """PRD §3.8: "`payment_status` runs `UNPAID`, `PAID` and `RESCINDED` with
        no terminal state, and it moves entirely independently of the acquisition
        track."

        Design: Difficulty/non_linear_state_machine/tract_payment_rescission_cycle_independent_of_acquisition_dimension
        """
        ctx = fx.setup_issued_certificate(api)
        fx.setup_agreed_tract(api, ctx)
        fx.fund_escrow(api, ctx)

        tract = fx.read_tract(api, ctx["tract1"])
        assert (tract["acquisition_status"], tract["payment_status"]) == ("AGREED", "UNPAID"), (
            "Before any disbursement the tract reads AGREED/UNPAID, got "
            f"{tract['acquisition_status']}/{tract['payment_status']}"
        )

        tract = fx.pay_tract(api, ctx)
        assert (tract["acquisition_status"], tract["payment_status"]) == ("AGREED", "PAID"), (
            "The disbursement moves only the payment dimension, got "
            f"{tract['acquisition_status']}/{tract['payment_status']}"
        )

        tract = fx.rescind_payment(api, ctx)
        assert (tract["acquisition_status"], tract["payment_status"]) == (
            "AGREED",
            "RESCINDED",
        ), (
            "The rescission moves only the payment dimension, got "
            f"{tract['acquisition_status']}/{tract['payment_status']}"
        )
        assert tract["paid_amount_cents"] == 0, (
            f"Rescission zeroes the paid amount, got {tract['paid_amount_cents']}"
        )
        assert tract["committed_cents"] == 4163406, (
            "The commitment is unaffected by the cash movement, got "
            f"{tract['committed_cents']}"
        )
        project = fx.read_project(api, ctx)
        assert project["easement_committed_cents"] == 4163406, (
            "easement_committed_cents tracks commitment rather than cash, got "
            f"{project['easement_committed_cents']}"
        )


class TestCertificatePostureOscillation:
    """Posture cycles ACTIVE -> STOP_WORK -> ACTIVE while status stays ISSUED."""

    def test_new_open_finding_drives_posture_back_to_stop_work(self, api):
        """PRD §3.9: "A finding that drives the rolling index below 60.00 while
        the cumulative index holds at 25.00 or above moves the certificate
        `ACTIVE → STOP_WORK`".

        Design: Difficulty/non_linear_state_machine/certificate_posture_oscillates_while_status_stays_issued
        """
        ctx = fx.setup_issued_certificate(api)
        fx.file_finding(api, ctx, key="ncr_sev", condition_key="cond1", severity="SEVERE")
        fx.correct_finding(api, ctx, key="ncr_sev")
        finding = fx.file_finding(
            api, ctx, key="ncr_maj", condition_key="cond3", severity="MAJOR",
            observation="Crew count above the certificate crew limit on two shifts",
        )

        assert_score(finding["deduction_points"], 19.20, "deduction_points")
        certificate = fx.read_certificate(api, ctx["cert"])
        assert_score(
            certificate["compliance_index_rolling"], 56.80, "compliance_index_rolling"
        )
        assert_score(
            certificate["compliance_index_cumulative"], 32.80, "compliance_index_cumulative"
        )
        assert certificate["posture"] == "STOP_WORK", (
            "A rolling index of 56.80 with a cumulative index of 32.80 is STOP_WORK, "
            f"got {certificate['posture']}"
        )
        assert certificate["status"] == "ISSUED", (
            f"The status dimension never moves off ISSUED, got {certificate['status']}"
        )
        assert fx.read_condition(api, ctx["cond3"])["status"] == "VIOLATED", (
            "The crew-limit condition now carries an open finding"
        )
        assert fx.read_condition(api, ctx["cond1"])["status"] == "ACTIVE", (
            "The blackout condition's only finding was corrected, so it is ACTIVE again"
        )

    def test_second_correction_lifts_posture_back_to_active(self, api):
        """PRD §3.9: "Either path may lift the certificate `STOP_WORK → ACTIVE`,
        which requires the cumulative index to be at 25.00 or above".

        Design: Difficulty/non_linear_state_machine/certificate_posture_oscillates_while_status_stays_issued
        """
        ctx = fx.setup_issued_certificate(api)
        fx.file_finding(api, ctx, key="ncr_sev", condition_key="cond1", severity="SEVERE")
        fx.correct_finding(api, ctx, key="ncr_sev")
        fx.file_finding(
            api, ctx, key="ncr_maj", condition_key="cond3", severity="MAJOR",
            observation="Crew count above the certificate crew limit on two shifts",
        )
        fx.correct_finding(api, ctx, key="ncr_maj", note="Crew rostering corrected")

        certificate = fx.read_certificate(api, ctx["cert"])
        assert_score(
            certificate["compliance_index_rolling"], 66.40, "compliance_index_rolling"
        )
        assert_score(
            certificate["compliance_index_cumulative"], 32.80, "compliance_index_cumulative"
        )
        assert certificate["posture"] == "ACTIVE", (
            "A rolling index of 66.40 is above the 60.00 floor, so posture returns to "
            f"ACTIVE, got {certificate['posture']}"
        )
        assert certificate["status"] == "ISSUED", (
            f"Posture oscillation never touches the status dimension, got "
            f"{certificate['status']}"
        )
        assert fx.read_condition(api, ctx["cond3"])["status"] == "ACTIVE", (
            "The correction was the last open finding on the crew-limit condition"
        )
