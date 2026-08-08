"""Release planning and the bridge supply, the release cascade, the in-custody death
cascade, the two independent inmate axes and the statutory mortality review."""

from test_helpers import (
    ApiErrorId,
    assert_adherence_equals,
    assert_mortality_review,
    assert_release_plan,
    assert_same_instant,
    bucket_counts,
    fixtures as fx,
    sick_call_payload,
    validate_error,
    validate_success,
)


class TestReleasePlanLeadTime:
    def test_scheduled_plan_six_days_ahead_is_refused_and_seven_days_is_accepted(
        self, api, admin_headers
    ):
        """PRD §3.9: "A `SCHEDULED` plan must be opened with at least 7 days of runway:
        `planned_release_at` must be at or later than the current clock instant plus 7 days,
        with exactly 7 days ahead **accepted**. A shorter runway is rejected at rung 13 with
        `ERR_RELEASE_PLAN_LEAD_TIME` (422). An `UNEXPECTED` plan — a court order, a sudden
        bond posting — is exempt from that rule entirely, which is precisely why the two
        release types exist. New plans start at `status` `DRAFT` with `records_packet_ready`
        false."

        Design: Corner/validations/release_plan_scheduled_lead_time_boundary
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="C-2290", full_name="Vin Xiao", booked_at="2026-05-01T00:00:00Z"
        )

        too_soon = api.create_release_plan(
            inmate["id"],
            {"release_type": "SCHEDULED", "planned_release_at": "2026-05-07T00:00:00Z"},
            admin_headers,
        )
        validate_error(too_soon, ApiErrorId.ERR_RELEASE_PLAN_LEAD_TIME.value, 422)

        at_boundary = api.create_release_plan(
            inmate["id"],
            {"release_type": "SCHEDULED", "planned_release_at": "2026-05-08T00:00:00Z"},
            admin_headers,
        )
        plan = validate_success(at_boundary, 201)
        assert_release_plan(plan)
        assert plan["status"] == "DRAFT"
        assert plan["bridge_supply_total_days"] == 0
        assert plan["records_packet_ready"] is False


class TestBridgeSupplySizing:
    def test_unexpected_release_uses_the_truncated_day_table(self, api, admin_headers):
        """PRD §3.9: "A `SCHEDULED` release uses the generous table — 30 days for
        `PSYCHOTROPIC`, 7 days for `CONTROLLED`, 30 days for `CHRONIC_MAINTENANCE` and 10 days
        for `ACUTE_SHORT_COURSE`. An `UNEXPECTED` release uses the truncated table — 7 days
        for `PSYCHOTROPIC`, **zero** days for `CONTROLLED`, 7 days for `CHRONIC_MAINTENANCE`
        and 3 days for `ACUTE_SHORT_COURSE`. The same medication list therefore produces
        materially different totals under the two release types, with controlled substances
        dispensed on an unexpected release not at all."
        PRD §3.9: "Each order contributes one line to `bridge_supply_lines` carrying the
        `order_id`, the `drug_class` and the `days` granted, in the same `created_at`
        ascending order as the eligible set was taken. The `bridge_supply_total_days` is the
        sum of the `days` across all lines."

        Design: Corner/calculations/bridge_supply_unexpected_release_truncates_totals
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="C-2270", full_name="Tex Varga", booked_at="2026-05-01T00:00:00Z"
        )
        psych = fx.write_medication_order(
            inmate["id"],
            drug_name="Sertraline",
            drug_class="PSYCHOTROPIC",
            start_date="2026-05-01T00:00:00Z",
            end_date="2026-05-20T00:00:00Z",
        )
        controlled = fx.write_medication_order(
            inmate["id"],
            drug_name="Oxycodone",
            drug_class="CONTROLLED",
            start_date="2026-05-01T00:00:00Z",
            end_date="2026-05-03T00:00:00Z",
        )

        resp = api.create_release_plan(
            inmate["id"],
            {"release_type": "UNEXPECTED", "planned_release_at": "2026-05-10T00:00:00Z"},
            admin_headers,
        )
        plan = validate_success(resp, 201)
        assert plan["bridge_supply_total_days"] == 7
        assert plan["reentry_referral_required"] is False
        assert plan["status"] == "DRAFT"

        lines = plan["bridge_supply_lines"]
        assert len(lines) == 2
        assert lines[0]["order_id"] == psych["id"]
        assert lines[0]["drug_class"] == "PSYCHOTROPIC"
        assert lines[0]["days"] == 7
        assert lines[1]["order_id"] == controlled["id"]
        assert lines[1]["drug_class"] == "CONTROLLED"
        assert lines[1]["days"] == 0


class TestReleaseGatedByFinalizedPlan:
    def test_release_is_refused_while_the_only_plan_is_still_draft(self, api, admin_headers):
        """PRD §3.9: "Releasing the patient is the origin of **Cascade B**, and it requires
        two things: the patient must still be `IN_CUSTODY`, and there must exist a release
        plan for them whose status is `FINALIZED`. A release attempted with no finalized plan
        is refused at rung 10 with `ERR_INVALID_STATE` (409)."
        PRD §3.9: "For each eligible order in turn, compute how many days of therapy remain on
        the order itself: the number of whole days from the plan's `planned_release_at`
        calendar date to the order's `end_date` calendar date, **plus one** because the span
        is inclusive of both dates, floored at zero so an order that has already expired
        contributes nothing. The days actually dispensed for that order are the smaller of the
        table value for its `drug_class` and that remaining-days figure."

        Design: Difficulty/cross_entity_state_dependency/release_gated_by_finalized_release_plan
        """
        scenario = fx.setup_patient_with_two_medication_orders_and_tier1_enrollment()
        plan = fx.open_release_plan(
            scenario["inmate"]["id"], "2026-05-10T00:00:00Z", release_type="SCHEDULED"
        )
        assert plan["bridge_supply_total_days"] == 11
        assert plan["reentry_referral_required"] is True

        resp = api.release_inmate(scenario["inmate"]["id"], admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
        assert fx.read_inmate(scenario["inmate"]["id"])["custody_status"] == "IN_CUSTODY"

    def test_finalizing_the_plan_lets_the_release_cascade_run(self, api, admin_headers):
        """PRD §3.9: "Finalizing a plan moves it from `DRAFT` to `FINALIZED` and recomputes
        `bridge_supply_lines`, `bridge_supply_total_days` and `reentry_referral_required`
        against the medication and enrollment lists as they stand at that later moment, so a
        drug discontinued between drafting and finalization drops out of the packet."
        PRD §3.9: "At level one that finalized plan transitions to `EXECUTED` and its
        `records_packet_ready` becomes true. At level two, because the plan executed, every
        medication order for the patient whose status is `ACTIVE` or `HELD` transitions to
        `COMPLETED`."
        PRD §3.9: "Alongside the cascade, every `ACTIVE` chronic-care enrollment transitions
        to `RESOLVED` with its `next_due_date` set null, and every sick-call request in
        `SUBMITTED`, `TRIAGED` or `SCHEDULED` transitions to `CANCELLED`."

        Design: Difficulty/cross_entity_state_dependency/release_gated_by_finalized_release_plan
        """
        scenario = fx.setup_patient_with_two_medication_orders_and_tier1_enrollment()
        inmate_id = scenario["inmate"]["id"]
        plan = fx.open_release_plan(
            inmate_id, "2026-05-10T00:00:00Z", release_type="SCHEDULED"
        )
        validate_error(
            api.release_inmate(inmate_id, admin_headers),
            ApiErrorId.ERR_INVALID_STATE.value,
            409,
        )

        fx.finalize_release_plan(plan["id"])
        released = validate_success(api.release_inmate(inmate_id, admin_headers), 200)
        assert released["custody_status"] == "RELEASED"

        executed = fx.read_release_plan(inmate_id, plan["id"])
        assert executed["status"] == "EXECUTED"
        assert executed["records_packet_ready"] is True
        assert executed["bridge_supply_total_days"] == 11
        assert fx.read_order(scenario["order_psych"]["id"])["status"] == "COMPLETED"
        assert fx.read_order(scenario["order_controlled"]["id"])["status"] == "COMPLETED"
        assert fx.read_enrollment(scenario["enrollment"]["id"])["status"] == "RESOLVED"


class TestCustodyGateAfterRelease:
    def test_a_released_patient_cannot_submit_a_new_sick_call_slip(self, api, nurse_headers):
        """PRD §2.6: "The custody gate is narrower and sits one rung lower. Six operations
        require the inmate to be `IN_CUSTODY` at the moment of the call and reject with
        `ERR_INMATE_NOT_IN_CUSTODY` (HTTP 409) otherwise: submitting a sick-call request,
        enrolling an inmate in chronic care, writing a medication order, requesting a
        specialty referral, dispatching a transport, and holding or resuming a medication
        order."
        PRD §3.9: "On success `custody_status` moves from `IN_CUSTODY` to `RELEASED` while
        `records_state` is left exactly as it was — a released patient's record does not
        freeze."

        Design: Corner/validations/released_inmate_cannot_submit_new_sick_call
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="C-2330", full_name="Zac Bruno", booked_at="2026-05-01T00:00:00Z"
        )
        plan, released = fx.setup_released_inmate(
            inmate["id"], "2026-05-02T00:00:00Z", release_type="UNEXPECTED"
        )

        resp = api.create_sick_call_request(
            sick_call_payload(inmate["id"], complaint_text="post-release question"),
            nurse_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INMATE_NOT_IN_CUSTODY.value, 409)

        refreshed = fx.read_inmate(inmate["id"])
        assert refreshed["custody_status"] == "RELEASED"
        assert refreshed["records_state"] == "OPEN"
        assert plan["status"] == "EXECUTED"
        assert plan["records_packet_ready"] is True


class TestDeathCascade:
    def test_death_freezes_the_record_and_discontinues_the_live_order(self, api, admin_headers):
        """PRD §3.9: "The cascade then runs five levels. Level one sets `custody_status` to
        `DECEASED`. Level two, because custody became `DECEASED`, flips `records_state` from
        `OPEN` to `FROZEN` on the same row. Level three, because the record froze, transitions
        every medication order in `ACTIVE` or `HELD` to `DISCONTINUED` — note that a death
        discontinues while a release completes, and the two landing states are not
        interchangeable. Level four, because each of those orders was discontinued, transitions
        every administration under it whose outcome is `SCHEDULED` to `VOIDED`."

        Design: Difficulty/transitive_cascade/death_event_depth5_freeze_discontinue_void_deescalate
        """
        scenario = fx.setup_escalated_dot_order_before_death()
        inmate_id = scenario["inmate"]["id"]
        assert fx.read_order(scenario["order"]["id"])["escalated_to_prescriber"] is True

        review = validate_success(
            api.record_death_event(
                inmate_id, {"death_at": "2026-05-04T00:00:00Z", "manner": "NATURAL"},
                admin_headers,
            ),
            201,
        )
        assert_mortality_review(review)
        assert review["status"] == "OPEN"
        assert_same_instant(review["due_at"], "2026-06-03T00:00:00Z", "mortality due_at")

        refreshed = fx.read_inmate(inmate_id)
        assert refreshed["custody_status"] == "DECEASED"
        assert refreshed["records_state"] == "FROZEN"
        assert fx.read_order(scenario["order"]["id"])["status"] == "DISCONTINUED"

        rows = fx.administrations_for(scenario["order"]["id"])
        outcomes = {row["id"]: row["outcome"] for row in rows}
        assert outcomes[scenario["doses"][3]["id"]] == "VOIDED"
        assert bucket_counts(rows)["VOIDED"] == 1

    def test_voiding_the_last_dose_withdraws_the_prescriber_escalation(self, api, admin_headers):
        """PRD §3.9: "Level five, because those doses were voided, resets each affected
        order's `consecutive_missed_count` and `consecutive_refused_count` to 0, sets
        `escalated_to_prescriber` false, and recomputes `adherence_pct` over the surviving
        denominator."

        Design: Difficulty/transitive_cascade/death_event_depth5_freeze_discontinue_void_deescalate
        """
        scenario = fx.setup_escalated_dot_order_before_death()
        before = fx.read_order(scenario["order"]["id"])
        assert before["consecutive_missed_count"] == 3
        assert before["escalated_to_prescriber"] is True

        validate_success(
            api.record_death_event(
                scenario["inmate"]["id"],
                {"death_at": "2026-05-04T00:00:00Z", "manner": "NATURAL"},
                admin_headers,
            ),
            201,
        )
        after = fx.read_order(scenario["order"]["id"])
        assert after["consecutive_missed_count"] == 0
        assert after["escalated_to_prescriber"] is False
        assert_adherence_equals(after["adherence_pct"], 0.00)

    def test_a_second_death_event_is_refused_and_creates_no_second_review(self, api, admin_headers):
        """PRD §3.9: "The patient must still be `IN_CUSTODY`, and no mortality review may
        already exist for them — a second death event is refused at rung 9 with
        `ERR_INVALID_STATE` (409)."

        Design: Corner/state_machines/death_event_cannot_be_recorded_twice
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="C-2200", full_name="Lou Njoku", booked_at="2026-05-01T00:00:00Z"
        )
        review = fx.record_death(inmate["id"], "2026-05-01T00:00:00Z", "NATURAL")

        resp = api.record_death_event(
            inmate["id"], {"death_at": "2026-05-01T01:00:00Z", "manner": "UNDETERMINED"},
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)

        reviews = fx.mortality_reviews_for(inmate["id"])
        assert len(reviews) == 1
        assert reviews[0]["id"] == review["id"]
        assert reviews[0]["manner"] == "NATURAL"

    def test_a_death_induced_freeze_can_never_be_lifted(self, api, admin_headers):
        """PRD §3.9: "Lifting the hold moves `records_state` from `FROZEN` back to `OPEN` and
        again leaves `custody_status` alone, but it is refused when the patient is `DECEASED`.
        A death-induced freeze is therefore permanent and unrecoverable by design."
        PRD §2.5: "**Target state.** The addressed row's own `status` or `outcome` is one from
        which the requested transition is declared. Failure yields `ERR_INVALID_STATE` (409)."

        Design: Corner/state_machines/records_unfreeze_cannot_reopen_a_decedent_record
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="C-2210", full_name="Moe Oyelaran", booked_at="2026-05-01T00:00:00Z"
        )
        fx.record_death(inmate["id"], "2026-05-01T00:00:00Z", "NATURAL")

        resp = api.unfreeze_records(inmate["id"], admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)

        refreshed = fx.read_inmate(inmate["id"])
        assert refreshed["records_state"] == "FROZEN"
        assert refreshed["custody_status"] == "DECEASED"


class TestParallelInmateAxes:
    def test_a_litigation_hold_closes_the_clinical_write_surface_without_touching_custody(
        self, api, nurse_headers, admin_headers
    ):
        """PRD §3.9: "A litigation hold moves `records_state` from `OPEN` to `FROZEN` and
        explicitly leaves `custody_status` untouched — this is the proof that the two axes are
        independent, since a freeze is entirely legal on a patient who is still in custody."
        PRD §2.6: "While `records_state` is `FROZEN`, the clinical write surface is closed.
        Rung 5 of the ladder guards, and rejects with `ERR_RECORDS_FROZEN` (HTTP 409), every
        mutating intake-screening, chronic-care, sick-call, medication, referral and co-pay
        operation."

        Design: Difficulty/non_linear_state_machine/inmate_parallel_axes_freeze_leaves_custody_untouched
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="D-1050", full_name="Gale Hart", booked_at="2026-05-01T00:00:00Z"
        )
        frozen = validate_success(api.freeze_records(inmate["id"], admin_headers), 200)
        assert frozen["records_state"] == "FROZEN"
        assert frozen["custody_status"] == "IN_CUSTODY"

        blocked = api.create_sick_call_request(
            sick_call_payload(inmate["id"], complaint_text="tooth pain"), nurse_headers
        )
        validate_error(blocked, ApiErrorId.ERR_RECORDS_FROZEN.value, 409)

    def test_lifting_the_hold_reopens_the_write_surface_and_only_the_two_axis_writes_bump_version(
        self, api, nurse_headers, admin_headers
    ):
        """PRD §3.9: "Both operations increment the inmate's `version` by 1, and neither is
        itself blocked by the freeze gate."
        PRD §3.3: "Because `open_sick_call_count` on the inmate is a read-time projection,
        submitting a slip changes what subsequent inmate reads report without advancing the
        inmate's `version`."

        Design: Difficulty/non_linear_state_machine/inmate_parallel_axes_freeze_leaves_custody_untouched
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="D-1051", full_name="Gale Hart", booked_at="2026-05-01T00:00:00Z"
        )
        fx.freeze_records(inmate["id"])
        validate_error(
            api.create_sick_call_request(
                sick_call_payload(inmate["id"], complaint_text="tooth pain"), nurse_headers
            ),
            ApiErrorId.ERR_RECORDS_FROZEN.value,
            409,
        )

        thawed = validate_success(api.unfreeze_records(inmate["id"], admin_headers), 200)
        assert thawed["records_state"] == "OPEN"
        assert thawed["custody_status"] == "IN_CUSTODY"

        accepted = validate_success(
            api.create_sick_call_request(
                sick_call_payload(inmate["id"], complaint_text="tooth pain"), nurse_headers
            ),
            201,
        )
        assert accepted["status"] == "SUBMITTED"

        refreshed = fx.read_inmate(inmate["id"])
        assert refreshed["custody_status"] == "IN_CUSTODY"
        assert refreshed["records_state"] == "OPEN"
        assert refreshed["version"] == 3, (
            "Only the freeze and the unfreeze mutate the inmate row"
        )


class TestMortalityReviewClosure:
    def test_closing_without_a_corrective_action_is_refused(self, api, admin_headers):
        """PRD §3.9: "Closing moves the review from `CORRECTIVE_ACTIONS_ISSUED` to `CLOSED`,
        but only when `corrective_action_count` is at least 1; a review with no corrective
        action attached is refused at rung 9 with `ERR_MORTALITY_REVIEW_INCOMPLETE` (422)."

        Design: Corner/state_machines/mortality_review_close_requires_corrective_action
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="C-2190", full_name="Kit Mbeki", booked_at="2026-05-01T00:00:00Z"
        )
        review = fx.record_death(inmate["id"], "2026-05-01T00:00:00Z", "NATURAL")
        assert_same_instant(review["due_at"], "2026-05-31T00:00:00Z", "due_at")
        fx.set_clock("2026-06-01T00:00:00Z")

        resp = api.close_mortality_review(review["id"], admin_headers)
        validate_error(resp, ApiErrorId.ERR_MORTALITY_REVIEW_INCOMPLETE.value, 422)
        assert fx.read_mortality_review(inmate["id"], review["id"])["status"] == "OPEN"

    def test_closing_after_the_statutory_deadline_is_flagged_late(self, api, admin_headers):
        """PRD §3.9: "Attaching a corrective action supplies `action_text`; the action is
        appended to the review's `corrective_actions` array as an object carrying that
        `action_text` and a `recorded_at` stamped from the current clock, the array is kept
        sorted by `recorded_at` ascending, `corrective_action_count` increments, and the review
        moves from `OPEN` to `CORRECTIVE_ACTIONS_ISSUED`."
        PRD §3.9: "Closing stamps `closed_at` from the clock and sets `closed_late` by
        comparing it to `due_at`: true only when `closed_at` is strictly after `due_at`, false
        when it lands at or before. A review closed exactly at its statutory deadline is on
        time."

        Design: Corner/state_machines/mortality_review_close_requires_corrective_action
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="C-2191", full_name="Kit Mbeki", booked_at="2026-05-01T00:00:00Z"
        )
        review = fx.record_death(inmate["id"], "2026-05-01T00:00:00Z", "NATURAL")
        fx.set_clock("2026-06-01T00:00:00Z")

        issued = validate_success(
            api.add_corrective_action(
                review["id"], {"action_text": "retrain night shift on hourly checks"},
                admin_headers,
            ),
            200,
        )
        assert issued["status"] == "CORRECTIVE_ACTIONS_ISSUED"
        assert issued["corrective_action_count"] == 1

        closed = validate_success(api.close_mortality_review(review["id"], admin_headers), 200)
        assert closed["status"] == "CLOSED"
        assert closed["closed_late"] is True
        assert_same_instant(closed["closed_at"], "2026-06-01T00:00:00Z", "closed_at")
