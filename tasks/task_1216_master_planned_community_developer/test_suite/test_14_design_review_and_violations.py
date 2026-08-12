"""Corner coverage: review rounds exhaustion, the violation lifecycle with
exact fine payment, and the appeal loop with segregation of duties."""
from test_helpers import (
    api_client,
    create_active_community,
    create_application,
    create_phase,
    create_lot,
    create_builder,
    create_resident,
    create_violation_hearing_scheduled,
    deny_round,
    resubmit_application,
    set_clock,
    get_success_data,
    validate_error,
    make_association_director_headers,
    make_builder_rep_headers,
    make_design_reviewer_headers,
    make_homeowner_resident_headers,
    ApiErrorId,
    TEST_USERS,
)

EXEC = TEST_USERS["declarant_executive_headers"]
CTRL = TEST_USERS["declarant_controller_headers"]
DIRECTOR = TEST_USERS["association_director_headers"]
REVIEWER = TEST_USERS["design_reviewer_headers"]
LIFESTYLE = TEST_USERS["lifestyle_coordinator_headers"]


class TestReviewRoundsExhaustedAtMax:
    def test_round_three_denial_leaves_no_resubmit_path(self):
        """PRD §3.7: "An applicant may resubmit a `DENIED` application while `submission_round` is below three rounds (`ERR_REVIEW_ROUNDS_EXHAUSTED` beyond that), provided the acting user matches the applicant — the `BuilderRep`'s id matching `applicant_builder_id` or the `HomeownerResident`'s id matching `applicant_resident_id` (`ERR_FORBIDDEN_ROLE`).".
        PRD §3.7: "Denial records a `denial_reason` and stamps `denied_by_user_id`; a denial landing at the third round leaves the application `DENIED` with no further resubmission path — the review loop is exhausted in practice."

        Design: Corner/state_machines/review_rounds_exhausted_at_max
        """
        community = create_active_community("Exhaustion Flats", 10)
        phase = create_phase(community["id"], "P1", 1, 5)
        lot = create_lot(phase["id"], "L1")
        builder = create_builder(community["id"], "Retry Builders", "A")
        application = create_application(
            community["id"], lot["id"], applicant_builder_id=builder["id"],
            project_type="ADDITION",
        )
        deny_round(application["id"], "rev-1", "massing")
        resubmit_application(application["id"], applicant_builder_id=builder["id"])
        deny_round(application["id"], "rev-2", "height")
        resubmit_application(application["id"], applicant_builder_id=builder["id"])
        final = deny_round(application["id"], "rev-3", "setback")
        assert final["submission_round"] == 3
        assert final["status"] == "DENIED", (
            f"round-3 denial leaves the application DENIED (no phantom state), "
            f"got {final['status']}"
        )

        resp = api_client.resubmit_application(
            application["id"], make_builder_rep_headers(builder["id"])
        )
        validate_error(resp, ApiErrorId.ERR_REVIEW_ROUNDS_EXHAUSTED)


class TestViolationLifecycleExactFinePayment:
    def test_full_walk_to_paid_with_exact_amount(self):
        """PRD §3.7: "A report starts `REPORTED`; sending notice moves it to `NOTICE_SENT` and sets the `cure_deadline` fourteen days out.".
        PRD §3.7: "Levying the fine moves it to `FINED`, stamps `fined_by_user_id`, freezes `days_late`, and computes `fine_cents` on a tiered schedule at the levy timestamp: the first thirty days late accrue 5000 cents per day, days thirty-one through sixty accrue 10000 cents per day, and every day beyond sixty accrues 20000 cents per day, with the total capped at 1000000 cents; no days late means no fine.".
        PRD §3.7: "From `FINED`, payment closes the matter: a `DeclarantController` records `payment_cents` equal to `fine_cents` exactly (`ERR_PENALTY_AMOUNT_MISMATCH`) and the violation is `PAID`."

        Design: Corner/state_machines/violation_lifecycle_exact_fine_payment
        """
        community = create_active_community("Fine Fields", 10)
        phase = create_phase(community["id"], "P1", 1, 5)
        lot = create_lot(phase["id"], "L1")
        resident = create_resident(community["id"], "Vera Violator", "vera@x.com")
        violation = create_violation_hearing_scheduled(
            community["id"], lot["id"],
            escalate_at="2026-05-16T00:00:00Z",
            hearing_date="2026-05-20T00:00:00Z",
            respondent_resident_id=resident["id"],
        )
        # Notice at default clock 2026-05-01 -> cure deadline 2026-05-15;
        # levy at the current clock 2026-05-16 -> 1 day late.
        fined = get_success_data(api_client.levy_fine(violation["id"], DIRECTOR))
        assert fined["status"] == "FINED"
        assert fined["days_late"] == 1
        assert fined["fine_cents"] == 5000, (
            f"day-1 fine is 5000, got {fined['fine_cents']}"
        )

        resp_short = api_client.record_violation_payment(
            violation["id"], {"payment_cents": 4999}, CTRL
        )
        validate_error(resp_short, ApiErrorId.ERR_PENALTY_AMOUNT_MISMATCH)

        paid = get_success_data(
            api_client.record_violation_payment(violation["id"], {"payment_cents": 5000}, CTRL)
        )
        assert paid["status"] == "PAID"


class TestAppealCycleSodAndRecomputedFine:
    def _setup_appealed(self):
        """Violation noticed 2026-05-01 (deadline 2026-05-15), escalated,
        hearing scheduled; fine levied by dir-1 at 2026-06-29 (day 45 ->
        300,000c); appealed by the respondent. Returns (violation_id, res_id)."""
        community = create_active_community("Appeal Acres", 10)
        phase = create_phase(community["id"], "P1", 1, 5)
        lot = create_lot(phase["id"], "L1")
        resident = create_resident(community["id"], "Adam Appellant", "adam@x.com")
        violation = create_violation_hearing_scheduled(
            community["id"], lot["id"],
            escalate_at="2026-05-16T00:00:00Z",
            hearing_date="2026-06-01T00:00:00Z",
            respondent_resident_id=resident["id"],
            violation_type="UNAPPROVED_MODIFICATION",
        )
        set_clock("2026-06-29T00:00:00Z")
        fined = get_success_data(
            api_client.levy_fine(violation["id"], make_association_director_headers("dir-1"))
        )
        assert fined["fine_cents"] == 300000, (
            f"day-45 fine is 30*5000 + 15*10000 = 300000, got {fined['fine_cents']}"
        )
        appealed = get_success_data(
            api_client.appeal_violation(
                violation["id"], {"appeal_reason": "new evidence"},
                make_homeowner_resident_headers(resident["id"]),
            )
        )
        assert appealed["status"] == "APPEALED"
        return violation["id"], resident["id"]

    def test_levier_cannot_resolve_own_appeal(self):
        """PRD §3.7: "Appeal resolution belongs to an `AssociationDirector` other than the director who levied the fine: the resolver's `X-User-ID` must differ from `fined_by_user_id` (`ERR_HEARING_OFFICER_CONFLICT`)."

        Design: Corner/state_machines/appeal_cycle_sod_and_recomputed_fine
        """
        violation_id, _ = self._setup_appealed()
        resp = api_client.resolve_appeal(
            violation_id, {"outcome": "APPEAL_DENIED"},
            make_association_director_headers("dir-1"),
        )
        validate_error(resp, ApiErrorId.ERR_HEARING_OFFICER_CONFLICT)

    def test_denied_appeal_recomputes_accrual_and_upheld_voids(self):
        """PRD §3.7: "APPEAL_UPHELD` moves the violation to `DISMISSED` and voids `fine_cents` to 0. `APPEAL_DENIED` returns the violation to `FINED`, with `fine_cents` recomputed on the same tiered schedule but with `days_late` measured to the resolution date — accrual resumes through the appeal."

        Design: Corner/state_machines/appeal_cycle_sod_and_recomputed_fine
        """
        violation_id, resident_id = self._setup_appealed()
        # Levier's own resolution is rejected; the appeal stays open.
        api_client.resolve_appeal(
            violation_id, {"outcome": "APPEAL_DENIED"},
            make_association_director_headers("dir-1"),
        )
        set_clock("2026-07-04T00:00:00Z")
        refined = get_success_data(
            api_client.resolve_appeal(
                violation_id, {"outcome": "APPEAL_DENIED"},
                make_association_director_headers("dir-2"),
            )
        )
        assert refined["status"] == "FINED"
        # Day 50 (deadline 2026-05-15 -> 2026-07-04): 30*5000 + 20*10000.
        assert refined["fine_cents"] == 350000, (
            f"accrual resumed to the resolution date: 350000, got {refined['fine_cents']}"
        )

        # Appeal again (within 30 days of the new fine) and uphold it.
        get_success_data(
            api_client.appeal_violation(
                violation_id, {"appeal_reason": "procedural defect"},
                make_homeowner_resident_headers(resident_id),
            )
        )
        dismissed = get_success_data(
            api_client.resolve_appeal(
                violation_id, {"outcome": "APPEAL_UPHELD"},
                make_association_director_headers("dir-2"),
            )
        )
        assert dismissed["status"] == "DISMISSED"
        assert dismissed["fine_cents"] == 0
