"""Award offers, stacking caps, waitlist promotion, and offer responses."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_fund_availability_invariant,
    assert_instant_equal,
    create_donor,
    create_fund,
    create_offered_award,
    create_open_program,
    create_student,
    drive_to_selected,
    get_fund,
    get_success_data,
    list_adjustments,
    make_student_headers,
    send_and_confirm,
    set_clock,
    setup_accepted_award,
    setup_finalized_cycle,
    setup_offered_award,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]


class TestOfferCreationGates:
    def test_insufficient_funds_at_offer(self, api):
        """PRD §3.6: "The fund must be able to stand behind the offer: an
        offer amount exceeding the fund's `available_cents` is refused with
        `ERR_INSUFFICIENT_FUNDS`."
        PRD §3.6: "moves the application from `SELECTED` to `AWARDED`" — a
        refused offer never performs that move.

        Design: Corner/validations/validation_insufficient_funds_at_offer
        """
        student = create_student()
        donor = create_donor()
        fund = create_fund(committed_cents=400000)
        program = create_open_program(donor["id"], fund["id"])
        flow = drive_to_selected(student["id"], program["id"])
        assert flow["application"]["status"] == "SELECTED"

        resp = api.create_award(
            {
                "application_id": flow["application"]["id"],
                "student_id": student["id"],
                "amount_cents": 500000,
            },
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_FUNDS)

        after = validate_success(api.get_application(flow["application"]["id"], COORD))
        assert after["status"] == "SELECTED", "no offer created -> no AWARDED move"
        fund_after = get_fund(fund["id"])
        assert fund_after["reserved_cents"] == 0
        assert fund_after["available_cents"] == 400000


class TestImmediateConsistency:
    def test_accept_response_carries_both_dimensions(self, api):
        """PRD §2.4: "Every mutation is atomic and visible in the response of
        the request that caused it: when one operation updates several
        resources, all of those updates commit together".
        PRD §3.6: "Accepting drives the two parallel status dimensions
        together: `offer_status` moves `OFFERED` → `ACCEPTED` and
        `funding_status` moves `NONE` → `ENCUMBERED`. The `accepted_at`
        instant is stamped".

        Design: Corner/consistency_model/immediate_consistency_on_action_response
        """
        ctx = setup_offered_award()
        award = ctx["award"]
        assert award["offer_status"] == "OFFERED"
        assert award["funding_status"] == "NONE"
        assert award["accepted_at"] is None

        accepted = validate_success(
            api.accept_award(
                award["id"], make_student_headers(ctx["students"][0]["id"])
            )
        )
        assert accepted["offer_status"] == "ACCEPTED"
        assert accepted["funding_status"] == "ENCUMBERED"
        assert_instant_equal(
            accepted["accepted_at"], "2026-08-01T00:00:00Z", "accepted_at"
        )


class TestWaitlistPromotion:
    def test_decline_releases_reservation_and_promotes_waitlist(self, api):
        """PRD §3.6: "Declining, also the student's own act and only from
        `OFFERED`, moves the offer to `DECLINED`, releases the reservation —
        the fund's `reserved_cents` decreases by `amount_cents` as a
        compensating entry — and fires the waitlist promotion selector on the
        source cycle."
        PRD §3.6: "among the cycle's applications still `WAITLISTED`, the one
        with the lowest `decision_rank` is promoted; ties break by
        `submitted_at` ascending and then `created_at` ascending; an empty
        waitlist pool makes the promotion a no-op. The promoted application
        moves `WAITLISTED` → `SELECTED`, ready for a fresh offer."

        Design: Corner/state_machines/award_decline_promotes_waitlist
        """
        ctx = setup_finalized_cycle(
            student_specs=[{}, {}],
            cycle_overrides={
                "quorum_count": 1,
                "selection_quota": 1,
                "waitlist_quota": 1,
            },
            score_specs=[
                {"app_index": 0, "reviewer_id": "rev_1",
                 "academic": 95, "essay": 95, "need": 95},
                {"app_index": 1, "reviewer_id": "rev_1",
                 "academic": 80, "essay": 80, "need": 80},
            ],
        )
        app_1, app_2 = ctx["applications"]
        assert app_1["status"] == "SELECTED" and app_1["decision_rank"] == 1
        assert app_2["status"] == "WAITLISTED" and app_2["decision_rank"] == 2

        award = create_offered_award(app_1["id"], ctx["students"][0]["id"], 500000)
        assert get_fund(ctx["fund"]["id"])["available_cents"] == 4500000

        declined = validate_success(
            api.decline_award(award["id"], make_student_headers(ctx["students"][0]["id"]))
        )
        assert declined["offer_status"] == "DECLINED"

        promoted = validate_success(api.get_application(app_2["id"], COORD))
        assert promoted["status"] == "SELECTED", "waitlist promotion fired"

        fund_after = get_fund(ctx["fund"]["id"])
        assert fund_after["reserved_cents"] == 0
        assert fund_after["available_cents"] == 5000000
        assert_fund_availability_invariant(fund_after)


class TestStackingScopeVariants:
    """Identical finances (COA 3000000, EFC 1000000 -> annual difference
    2000000); an identical 1500000-cent award under ANNUAL vs PER_TERM."""

    FINANCES = {
        "household_income_cents": 2000000,
        "efc_cents": 1000000,
        "cost_of_attendance_cents": 3000000,
    }

    def _accepted(self, stacking_scope):
        return setup_accepted_award(
            amount_cents=1500000,
            student_overrides=dict(self.FINANCES),
            program_overrides={
                "program_type": "NEED",
                "stacking_scope": stacking_scope,
                "award_amount_cents": 1500000,
            },
            fund_overrides={"committed_cents": 10000000},
        )

    def test_annual_scope_admits_award_cleanly(self, api):
        """PRD §3.6: "an `ANNUAL` program caps the stack at the student's
        `cost_of_attendance_cents` minus `efc_cents`".
        PRD §3.6: "The excess is the amount by which the total exceeds the
        cap, or zero when the total fits."
        PRD §3.6: "When the excess is above zero, the over-award recovery
        order runs" — with zero excess no adjustment is created.

        Design: Difficulty/dual_variant_calc/stacking_scope_annual_vs_per_term_caps
        """
        ctx = self._accepted("ANNUAL")
        assert ctx["award"]["offer_status"] == "ACCEPTED"
        # Cap = 3000000 - 1000000 = 2000000 >= 1500000 accepted: no excess.
        _, meta = list_adjustments({"award_id": ctx["award"]["id"]})
        assert meta["total_count"] == 0, "no over-award cascade under ANNUAL"
        student = validate_success(api.get_student(ctx["students"][0]["id"], COORD))
        assert student["total_accepted_cents"] == 1500000
        assert student["excess_cents"] == 0

    def test_per_term_scope_cascades_auto_adjustment(self, api):
        """PRD §3.6: "a `PER_TERM` program caps it at the floor of half that
        difference — identical student data admits a smaller stack under a
        per-term program (for example, a 2,000,000-cent annual difference caps
        at 1,000,000 cents per term)."
        PRD §3.6: "When the reduction is positive, an auto-generated
        adjustment is created — `auto_generated` true, `reason` `OVER_AWARD`,
        `delta_cents` set to the negative of the reduction, and `status`
        `PENDING_APPROVAL` — and the remaining excess shrinks by the
        reduction."

        Design: Difficulty/dual_variant_calc/stacking_scope_annual_vs_per_term_caps
        """
        ctx = self._accepted("PER_TERM")
        award = ctx["award"]
        assert award["offer_status"] == "ACCEPTED"
        # PER_TERM cap = floor(2000000/2) = 1000000 < 1500000 -> stacking
        # excess 500000 drives the recovery pass below. (The student's
        # excess_cents field itself is defined by PRD §3.1 against the annual
        # aid_cap_cents, not the PER_TERM stacking cap, so it is not asserted
        # here.)
        student = validate_success(api.get_student(ctx["students"][0]["id"], COORD))
        assert student["total_accepted_cents"] == 1500000

        adjustments, meta = list_adjustments({"award_id": award["id"]})
        assert meta["total_count"] == 1, "exactly one auto adjustment"
        adj = adjustments[0]
        assert adj["delta_cents"] == -500000
        assert adj["reason"] == "OVER_AWARD"
        assert adj["auto_generated"] is True
        assert adj["status"] == "PENDING_APPROVAL"


class TestOverCapAutoAdjustment:
    """One student, two ANNUAL programs (1500000 + 800000), cap 2000000."""

    FINANCES = {
        "household_income_cents": 2000000,
        "efc_cents": 1000000,
        "cost_of_attendance_cents": 3000000,
    }

    def _setup_two_awards(self, api):
        student = create_student(**self.FINANCES)
        donor = create_donor()
        fund = create_fund(committed_cents=10000000)
        p_big = create_open_program(
            donor["id"], fund["id"], program_type="NEED",
            award_amount_cents=1500000, max_recipients=1,
        )
        p_small = create_open_program(
            donor["id"], fund["id"], program_type="NEED",
            award_amount_cents=800000, max_recipients=1,
        )
        flow_1 = drive_to_selected(student["id"], p_big["id"])
        flow_2 = drive_to_selected(
            student["id"], p_small["id"],
            scores=[{"reviewer_id": "rev_1", "academic": 85,
                     "essay": 85, "need": 85}],
        )
        aw_1 = create_offered_award(flow_1["application"]["id"], student["id"], 1500000)
        aw_2 = create_offered_award(flow_2["application"]["id"], student["id"], 800000)
        return student, fund, aw_1, aw_2

    def test_first_accept_within_cap_creates_no_adjustment(self, api):
        """PRD §3.6: "The stacking total is the sum of `amount_cents` over
        the student's awards whose `offer_status` is `ACCEPTED`; `OFFERED`,
        `DECLINED`, `REVOKED`, and `EXPIRED` awards are excluded. The excess
        is the amount by which the total exceeds the cap, or zero when the
        total fits."
        PRD §3.6: "The `accepted_at` instant is stamped, the student's
        `total_accepted_cents` grows by `amount_cents`, the student's
        `excess_cents` is recomputed, the fund's `reserved_cents` is
        recomputed (the offer was already reserved at creation), and then the
        stacking check below runs — the first trigger of the over-award
        cascade."

        Design: Difficulty/transitive_cascade/award_accept_over_cap_auto_adjustment
        """
        student, _, aw_1, _ = self._setup_two_awards(api)
        accepted = validate_success(
            api.accept_award(aw_1["id"], make_student_headers(student["id"]))
        )
        assert accepted["offer_status"] == "ACCEPTED"
        # 1500000 <= 2000000 cap: fits, so the recovery pass never fires.
        _, meta = list_adjustments({"award_id": aw_1["id"]})
        assert meta["total_count"] == 0
        student_after = validate_success(api.get_student(student["id"], COORD))
        assert student_after["total_accepted_cents"] == 1500000
        assert student_after["excess_cents"] == 0

    def test_second_accept_over_cap_creates_auto_adjustment_on_newest(self, api):
        """PRD §3.6: "The student's accepted awards are walked newest first —
        `accepted_at` descending, ties broken by `created_at` descending —
        tracking a remaining-excess figure that starts at the full excess.
        For each award, the reduction is the smaller of the remaining excess
        and that award's reducible headroom, meaning its `amount_cents` minus
        its net confirmed amount. When the reduction is positive, an
        auto-generated adjustment is created — `auto_generated` true,
        `reason` `OVER_AWARD`, `delta_cents` set to the negative of the
        reduction, and `status` `PENDING_APPROVAL` — and the remaining excess
        shrinks by the reduction."

        Design: Difficulty/transitive_cascade/award_accept_over_cap_auto_adjustment
        """
        student, _, aw_1, aw_2 = self._setup_two_awards(api)
        validate_success(api.accept_award(aw_1["id"], make_student_headers(student["id"])))

        accepted_2 = validate_success(
            api.accept_award(aw_2["id"], make_student_headers(student["id"]))
        )
        assert accepted_2["offer_status"] == "ACCEPTED"

        # Link 1: student aggregates mutated by the accept.
        student_after = validate_success(api.get_student(student["id"], COORD))
        assert student_after["total_accepted_cents"] == 2300000
        assert student_after["excess_cents"] == 300000

        # Link 2: the recompute created one auto adjustment on the
        # newest-accepted award (award2): reduction min(300000, 800000 - 0).
        adjustments, meta = list_adjustments({"award_id": aw_2["id"]})
        assert meta["total_count"] == 1
        adj = adjustments[0]
        assert adj["delta_cents"] == -300000
        assert adj["reason"] == "OVER_AWARD"
        assert adj["auto_generated"] is True
        assert adj["status"] == "PENDING_APPROVAL"

        # The older award is untouched by the recovery pass.
        _, meta_1 = list_adjustments({"award_id": aw_1["id"]})
        assert meta_1["total_count"] == 0


class TestParallelOfferAndFundingDimensions:
    """offer_status and funding_status evolve on independent triggers."""

    def test_accept_moves_offer_and_funding_together(self, api):
        """PRD §3.6: "Accepting drives the two parallel status dimensions
        together: `offer_status` moves `OFFERED` → `ACCEPTED` and
        `funding_status` moves `NONE` → `ENCUMBERED`."
        PRD §3.6: "Creation sets `offer_status` to `OFFERED` and
        `funding_status` to `NONE`".

        Design: Difficulty/non_linear_state_machine/award_parallel_offer_and_funding_dimensions
        """
        ctx = setup_accepted_award(amount_cents=600000)
        award = ctx["award"]
        assert award["offer_status"] == "ACCEPTED"
        assert award["funding_status"] == "ENCUMBERED"

    def test_confirmations_advance_funding_while_offer_stays_accepted(self, api):
        """PRD §3.7: "the award's `funding_status` is recomputed — the first
        confirmation moves `ENCUMBERED` → `DISBURSING`, and when the net
        confirmed amount reaches `amount_cents` the award moves `DISBURSING`
        → `FULLY_DISBURSED`."

        Design: Difficulty/non_linear_state_machine/award_parallel_offer_and_funding_dimensions
        """
        ctx = setup_accepted_award(amount_cents=600000, term_count=2)
        award_id = ctx["award"]["id"]
        disb_1, disb_2 = ctx["disbursements"]
        assert (disb_1["amount_cents"], disb_2["amount_cents"]) == (300000, 300000)

        get_success_data(api.send_disbursement(disb_1["id"], COORD))
        get_success_data(api.confirm_disbursement(
            disb_1["id"], TEST_USERS["fao_headers"]
        ))
        mid = validate_success(api.get_award(award_id, COORD))
        assert mid["offer_status"] == "ACCEPTED"
        assert mid["funding_status"] == "DISBURSING", "300000 of 600000 confirmed"

        set_clock("2027-02-01T00:00:00Z")
        send_and_confirm(disb_2["id"])
        final = validate_success(api.get_award(award_id, COORD))
        assert final["offer_status"] == "ACCEPTED"
        assert final["funding_status"] == "FULLY_DISBURSED"
