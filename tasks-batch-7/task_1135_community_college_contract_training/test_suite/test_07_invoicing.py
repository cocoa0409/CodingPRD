"""Invoicing: per-line rounding, variant gating, grant offset order,
lifecycle lockdowns, employer rollup reconciliation."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    setup_launched_cohort,
    setup_delivered_cohort,
    close_session_attendance,
    create_grant_program,
    create_grant_application_for_cohort,
    submit_and_review,
    approve_application,
    api_client,
    TEST_USERS,
)

COORD = TEST_USERS["coordinator_headers"]
BILL = TEST_USERS["billing_clerk_headers"]


class TestInvoicePerLineRounding:
    def _two_session_delivered(self, api):
        return setup_delivered_cohort(
            num_participants=10, min_enrollment=1,
            sessions=[("2026-06-08T09:00:00Z", "2026-06-08T10:30:00Z"),
                      ("2026-06-09T09:00:00Z", "2026-06-09T10:30:00Z")],
            agreement_overrides={"pricing_model": "PER_PARTICIPANT",
                                 "est_participant_count": 10,
                                 "est_delivery_hours": 3,
                                 "target_start_date": "2026-06-08T00:00:00Z",
                                 "max_cohorts": 2,
                                 "cohort_start_date": "2026-06-08T00:00:00Z",
                                 "cohort_end_date": "2026-06-09T00:00:00Z"},
            curriculum_modules=[{"code": "MILL-1", "hours": 3,
                                 "required_credential_codes": ["CNC"]}],
            instructor_overrides={"full_name": "Ina Instructor",
                                  "credentials": [{"code": "CNC",
                                                   "expires_on": "2027-06-01"}],
                                  "hourly_rate_cents": 7250},
            venue_overrides={"name": "Delta Floor", "capacity": 25},
            participant_prefix="D",
            attendance_map=None,  # full 2h... sessions are 1.5h, override below
        )

    def test_per_line_rounding_pinned_order(self, api):
        """PRD §3.7: "the instruction component is the session's `hours`
        multiplied by the `hourly_rate_cents` of the instructor on the
        session's single `COMPLETED`-or-`CONFIRMED` assignment — exactly one
        such assignment is required — multiplied again by a load factor of
        1.15, rounded half up to whole cents; the materials component is the
        attendee count multiplied by 7,500 cents, rounded half up to whole
        cents; and the line total is the sum of the two rounded components."
        "rounding happens per line and only per line, because rounding a sum
        of unrounded lines produces a different cent figure and is forbidden."

        Design: Difficulty/combinatorial_formula/invoice_gross_mode_b_per_line_rounding_pinned
        """
        # 1.5h sessions: per line round(1.5*7250*1.15)=12506 + 75000 = 87506
        ctx = setup_delivered_cohort(
            num_participants=10, min_enrollment=1,
            sessions=[("2026-06-08T09:00:00Z", "2026-06-08T10:30:00Z"),
                      ("2026-06-09T09:00:00Z", "2026-06-09T10:30:00Z")],
            agreement_overrides={"pricing_model": "PER_PARTICIPANT",
                                 "est_participant_count": 10,
                                 "est_delivery_hours": 3,
                                 "target_start_date": "2026-06-08T00:00:00Z",
                                 "max_cohorts": 2,
                                 "cohort_start_date": "2026-06-08T00:00:00Z",
                                 "cohort_end_date": "2026-06-09T00:00:00Z"},
            curriculum_modules=[{"code": "MILL-1", "hours": 3,
                                 "required_credential_codes": ["CNC"]}],
            instructor_overrides={"full_name": "Ina Instructor",
                                  "credentials": [{"code": "CNC",
                                                   "expires_on": "2027-06-01"}],
                                  "hourly_rate_cents": 7250},
            venue_overrides={"name": "Delta Floor", "capacity": 25},
            participant_prefix="D",
            attendance_map={0: {f"D{i:02d}": 1.5 for i in range(1, 11)},
                            1: {f"D{i:02d}": 1.5 for i in range(1, 11)}},
        )
        inv = validate_success(
            api_client.create_invoice(ctx["cohort"]["id"], {"variant": "FINAL"}, BILL), 201
        )
        # Pinned order: 2 x 87506 = 175012; forbidden sum-then-round: 175013
        assert inv["gross_cents"] == 175012, (
            f"expected per-line-rounded gross 175012, got {inv['gross_cents']}"
        )
        assert inv["gross_cents"] != 175013
        assert inv["grant_offset_cents"] == 0  # no grant application
        assert inv["net_due_cents"] == 175012

    def test_invoice_lines_carry_rounded_components(self, api):
        """PRD §3.7: "each line records its `session_id`,
        `instruction_cents`, `materials_cents`, and `line_cents`"; "the line
        total is the sum of the two rounded components."

        Design: Difficulty/combinatorial_formula/invoice_gross_mode_b_per_line_rounding_pinned
        """
        ctx = setup_delivered_cohort(
            num_participants=10, min_enrollment=1,
            sessions=[("2026-06-08T09:00:00Z", "2026-06-08T10:30:00Z"),
                      ("2026-06-09T09:00:00Z", "2026-06-09T10:30:00Z")],
            agreement_overrides={"pricing_model": "PER_PARTICIPANT",
                                 "est_participant_count": 10,
                                 "est_delivery_hours": 3,
                                 "target_start_date": "2026-06-08T00:00:00Z",
                                 "max_cohorts": 2,
                                 "cohort_start_date": "2026-06-08T00:00:00Z",
                                 "cohort_end_date": "2026-06-09T00:00:00Z"},
            curriculum_modules=[{"code": "MILL-1", "hours": 3,
                                 "required_credential_codes": ["CNC"]}],
            instructor_overrides={"full_name": "Ina Instructor",
                                  "credentials": [{"code": "CNC",
                                                   "expires_on": "2027-06-01"}],
                                  "hourly_rate_cents": 7250},
            venue_overrides={"name": "Delta Floor", "capacity": 25},
            participant_prefix="D",
            attendance_map={0: {f"D{i:02d}": 1.5 for i in range(1, 11)},
                            1: {f"D{i:02d}": 1.5 for i in range(1, 11)}},
        )
        inv = validate_success(
            api_client.create_invoice(ctx["cohort"]["id"], {"variant": "FINAL"}, BILL), 201
        )
        assert len(inv["lines"]) == 2
        for line in inv["lines"]:
            assert line["instruction_cents"] == 12506
            assert line["materials_cents"] == 75000
            assert line["line_cents"] == line["instruction_cents"] + line["materials_cents"]


class TestGrantOffsetPinnedOrder:
    def _approved_grant_fixture(self, api):
        """10-enrollee 2-session cohort (gross 175012) + APPROVED grant with
        provisional award 100000."""
        gp = create_grant_program(code="GP-C", appropriation_cents=10000000)
        ctx = setup_launched_cohort(
            num_participants=10, min_enrollment=1,
            sessions=[("2026-06-08T09:00:00Z", "2026-06-08T10:30:00Z"),
                      ("2026-06-09T09:00:00Z", "2026-06-09T10:30:00Z")],
            agreement_overrides={"pricing_model": "FLAT_COHORT",
                                 "est_participant_count": 10,
                                 "est_delivery_hours": 3,
                                 "target_start_date": "2026-06-08T00:00:00Z",
                                 "max_cohorts": 2,
                                 "cohort_start_date": "2026-06-08T00:00:00Z",
                                 "cohort_end_date": "2026-06-09T00:00:00Z"},
            curriculum_modules=[{"code": "MILL-1", "hours": 3,
                                 "required_credential_codes": ["CNC"]}],
            instructor_overrides={"full_name": "Ina Instructor",
                                  "credentials": [{"code": "CNC",
                                                   "expires_on": "2027-06-01"}],
                                  "hourly_rate_cents": 7250},
            venue_overrides={"name": "Epsilon Floor", "capacity": 25},
            participant_prefix="D",
        )
        gap = create_grant_application_for_cohort(ctx["cohort"]["id"], gp["id"], 100000)
        submit_and_review(gap["id"])
        approved = approve_application(gap["id"])
        # min(100000, floor(505000*0.5)=252500, 10*50000) == 100000
        assert approved["provisional_award_cents"] == 100000
        # deliver: all 10 attend both 1.5h sessions in full
        entries = [{"external_employee_ref": f"D{i:02d}", "attended_hours": 1.5}
                   for i in range(1, 11)]
        for sid in ctx["session_ids"]:
            close_session_attendance(sid, ctx["instructor"]["id"], entries)
        ctx["cohort"] = get_success_data(api_client.get_cohort(ctx["cohort"]["id"], COORD))
        return ctx, gap

    def test_offset_computed_after_gross_then_net(self, api):
        """PRD §3.7: "Step one computes the gross as above. Step two locates
        the cohort's application in `APPROVED`, `CLAIMED`, or `PAID`; the
        award basis is the `final_award_cents` when the application is
        `CLAIMED` or `PAID` and the `provisional_award_cents` when it is
        `APPROVED`, and `grant_offset_cents` is the smallest of three ceilings
        — the award basis, the whole-cent floor of `gross_cents` multiplied by
        the program's `max_share_pct`, and the program's
        `cap_per_trainee_cents` multiplied by the headcount basis, which is
        the cohort's `completer_count` for a `FINAL` invoice and its
        `enrolled_count` for a `PROVISIONAL` one." "Step three sets
        `net_due_cents` to the gross minus the offset. The offset never feeds
        back into the gross; the three steps run exactly once, in this order."

        Design: Difficulty/combinatorial_formula/grant_offset_mode_c_pinned_evaluation_order
        """
        ctx, _ = self._approved_grant_fixture(api)
        inv = validate_success(
            api_client.create_invoice(ctx["cohort"]["id"], {"variant": "FINAL"}, BILL), 201
        )
        assert inv["gross_cents"] == 175012
        # min(100000, floor(175012*0.5)=87506, 10*50000) == 87506
        assert inv["grant_offset_cents"] == 87506, (
            f"expected offset 87506, got {inv['grant_offset_cents']}"
        )
        assert inv["net_due_cents"] == 87506
        assert inv["net_due_cents"] == inv["gross_cents"] - inv["grant_offset_cents"]

    def test_offset_is_zero_without_covering_application(self, api):
        """PRD §3.7: "Step two locates the cohort's application in `APPROVED`,
        `CLAIMED`, or `PAID`" and "When no such application covers the cohort,
        the offset is zero. Step three sets `net_due_cents` to the gross minus
        the offset."

        Design: Difficulty/combinatorial_formula/grant_offset_mode_c_pinned_evaluation_order
        """
        ctx = setup_delivered_cohort(num_participants=1, min_enrollment=1)
        inv = validate_success(
            api_client.create_invoice(ctx["cohort"]["id"], {"variant": "FINAL"}, BILL), 201
        )
        assert inv["grant_offset_cents"] == 0
        assert inv["net_due_cents"] == inv["gross_cents"]


class TestInvoiceVariantDivergence:
    def _twenty_participant_cohort(self, api):
        sessions = [("2026-06-%02dT09:00:00Z" % (1 + i),
                     "2026-06-%02dT11:00:00Z" % (1 + i)) for i in range(5)]
        return setup_launched_cohort(
            num_participants=20, min_enrollment=15, sessions=sessions,
            agreement_overrides={"pricing_model": "PER_PARTICIPANT",
                                 "est_participant_count": 20,
                                 "est_delivery_hours": 10,
                                 "target_start_date": "2026-06-01T00:00:00Z",
                                 "max_cohorts": 2,
                                 "cohort_start_date": "2026-06-01T00:00:00Z",
                                 "cohort_end_date": "2026-06-05T00:00:00Z"},
            instructor_overrides={"full_name": "Pat Instructor",
                                  "hourly_rate_cents": 8000},
            venue_overrides={"name": "Var Site", "capacity": 40},
            participant_prefix="V",
        )

    def test_provisional_and_final_gross_diverge(self, api):
        """PRD §3.7: "a `FINAL` invoice reads only `HELD` sessions and counts,
        per session, the participants whose recorded `attended_hours` for that
        session are greater than zero; a `PROVISIONAL` invoice reads only
        `PLANNED` sessions and counts the cohort's whole `enrolled_count` on
        every line."

        Design: Corner/calculations/invoice_provisional_vs_final_variant_divergence
        """
        ctx = self._twenty_participant_cohort(api)
        invp = validate_success(
            api_client.create_invoice(ctx["cohort"]["id"], {"variant": "PROVISIONAL"}, BILL), 201
        )
        # 5 PLANNED lines x (18400 + 20*7500=150000) = 842000
        assert invp["gross_cents"] == 842000, (
            f"expected PROVISIONAL gross 842000, got {invp['gross_cents']}"
        )
        validate_success(api_client.void_invoice(invp["id"], BILL))

        ins = ctx["instructor"]["id"]
        entries = [{"external_employee_ref": f"V{i:02d}", "attended_hours": 2}
                   for i in range(1, 18)]
        entries += [{"external_employee_ref": "V18", "attended_hours": 1.4},
                    {"external_employee_ref": "V19", "attended_hours": 1.4}]
        for sid in ctx["session_ids"]:
            close_session_attendance(sid, ins, entries)

        invf = validate_success(
            api_client.create_invoice(ctx["cohort"]["id"], {"variant": "FINAL"}, BILL), 201
        )
        # 5 HELD lines x (18400 + 19 attendees*7500=142500) = 804500
        assert invf["gross_cents"] == 804500, (
            f"expected FINAL gross 804500, got {invf['gross_cents']}"
        )
        assert invp["gross_cents"] != invf["gross_cents"]


class TestInvoiceVariantGating:
    def test_final_rejected_while_launched(self, api):
        """PRD §3.7: "the variant must fit the cohort's delivery state:
        `PROVISIONAL` requires `LAUNCHED` or `IN_PROGRESS`, while `FINAL`
        requires `DELIVERED` or `CREDENTIALED`; a mismatch is rejected with
        `ERR_INVOICE_VARIANT_NOT_ALLOWED`."

        Design: Corner/calculations/invoice_provisional_wrong_state_returns_variant_error
        """
        ctx = setup_launched_cohort(num_participants=1, min_enrollment=1)
        resp = api_client.create_invoice(ctx["cohort"]["id"], {"variant": "FINAL"}, BILL)
        validate_error(resp, ApiErrorId.ERR_INVOICE_VARIANT_NOT_ALLOWED)


class TestInvoiceLifecycle:
    def test_mark_paid_on_draft_rejected(self, api):
        """PRD §3.7: "Marking paid is allowed only from `ISSUED` — any other
        state is rejected with `ERR_INVOICE_NOT_PAYABLE`".

        Design: Corner/errors/error_mark_paid_on_draft_invoice
        """
        ctx = setup_launched_cohort(num_participants=1, min_enrollment=1)
        inv = validate_success(
            api_client.create_invoice(ctx["cohort"]["id"], {"variant": "PROVISIONAL"}, BILL), 201
        )
        assert inv["status"] == "DRAFT"
        resp = api_client.mark_paid_invoice(inv["id"], BILL)
        validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_PAYABLE)

    def _paid_invoice_fixture(self, api):
        ctx = setup_delivered_cohort(num_participants=1, min_enrollment=1)
        inv = validate_success(
            api_client.create_invoice(ctx["cohort"]["id"], {"variant": "FINAL"}, BILL), 201
        )
        validate_success(api_client.issue_invoice(inv["id"], BILL))
        validate_success(api_client.mark_paid_invoice(inv["id"], BILL))
        return ctx, inv

    def test_void_on_paid_invoice_rejected(self, api):
        """PRD §3.7: "attempting to void a `PAID` or already-`VOID` invoice is
        rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/invoice_paid_lockdown_void_rejected
        """
        _, inv = self._paid_invoice_fixture(api)
        resp = api_client.void_invoice(inv["id"], BILL)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        cur = get_success_data(api_client.get_invoice(inv["id"], BILL))
        assert cur["status"] == "PAID"


class TestEmployerRollup:
    def test_lifetime_billed_reconciles_on_mark_paid_only(self, api):
        """PRD §3.7: "`lifetime_billed_cents` is, at all times, the sum of
        `net_due_cents` over the employer's `PAID` invoices only — `DRAFT`,
        `ISSUED`, and `VOID` are excluded."

        Design: Corner/cross_cutting_layers/derived_field_reconciliation_employer_rollup
        """
        ctx = setup_delivered_cohort(num_participants=1, min_enrollment=1,
                                     participant_prefix="RO")
        emp_id = ctx["employer"]["id"]
        inv = validate_success(
            api_client.create_invoice(ctx["cohort"]["id"], {"variant": "FINAL"}, BILL), 201
        )
        # line = round(2*9000*1.15)=20700 + 7500 = 28200; no grant
        assert inv["gross_cents"] == 28200
        assert inv["net_due_cents"] == 28200

        validate_success(api_client.issue_invoice(inv["id"], BILL))
        emp_mid = get_success_data(api_client.get_employer(emp_id, COORD))
        assert emp_mid["lifetime_billed_cents"] == 0  # ISSUED excluded

        validate_success(api_client.mark_paid_invoice(inv["id"], BILL))
        emp_end = get_success_data(api_client.get_employer(emp_id, COORD))
        assert emp_end["lifetime_billed_cents"] == 28200
