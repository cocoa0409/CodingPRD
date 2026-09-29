"""Actions asked from a state their machine does not admit, rows that absorb
everything asked of them afterwards, replays that are refused rather than applied
twice, and the three transitions gated on the logical clock rather than on stored
state."""

from test_helpers import (
    ApiErrorId,
    assert_batch,
    assert_blackout_window,
    assert_complaint,
    assert_fund,
    assert_hotel,
    assert_ledger_entry,
    assert_member,
    assert_purchase,
    assert_redemption,
    assert_stay,
    collect_all,
    factories as fac,
    fixtures as fx,
    make_admin_headers,
    make_care_agent_headers,
    make_hotel_owner_headers,
    make_member_headers,
    validate_error,
    validate_success,
)


# ----------------------------------------------------------------------
# Scenario builders
# ----------------------------------------------------------------------
def _wrongstate_court_with_three_rows_mid_flight(api):
    """An active property holding a window still in draft, a stay still awaiting
    posting, and a point purchase already settled."""
    bundle = fx.create_active_hotel(
        api,
        rate_code="BAR",
        rate_category="TRANSIENT",
        name="Wrongstate Court",
        brand_code="WSC",
        market_tier="URBAN",
        program_fee_pct=0.05,
        rooms_count=100,
        trailing_12m_occupancy_pct=0.82,
        trailing_12m_adr_cents=30_000,
    )
    hotel_id = bundle["hotel"]["id"]
    window = fx.draft_blackout(
        api, hotel_id, "2026-12-20", "2026-12-26", scope="ALL_REDEMPTIONS"
    )
    member = fx.enroll_member(
        api,
        email="ws1@example.com",
        full_name="Petra Novy",
        enrollment_date="2026-02-01",
    )
    stay = fx.capture_stay(
        api,
        hotel_id,
        member["id"],
        bundle["rate_plan"]["id"],
        "2026-07-01",
        "2026-07-03",
        40_000,
    )
    purchase = fx.settled_purchase(api, member["id"], 20_000)

    bundle["window"] = window
    bundle["member"] = member
    bundle["member_headers"] = make_member_headers(member["id"])
    bundle["stay"] = stay
    bundle["purchase"] = purchase
    return bundle


def _lifecycle_lodge_with_a_row_in_every_opening_state(api):
    """A held award booking whose arrival has already passed, a batch nobody has
    released, and a complaint nobody has reviewed."""
    bundle = fx.create_active_hotel(
        api,
        rate_code="BAR",
        rate_category="TRANSIENT",
        name="Lifecycle Lodge",
        brand_code="LCL",
        market_tier="URBAN",
        program_fee_pct=0.05,
        rooms_count=100,
        trailing_12m_occupancy_pct=0.82,
        trailing_12m_adr_cents=30_000,
    )
    hotel_id = bundle["hotel"]["id"]
    fx.publish_standard_pricing(
        api,
        hotel_id,
        points_per_night=20_000,
        cash_copay_cents=0,
        min_tier_required="BASE",
        award_allotment_per_night=2,
    )
    funded = fx.member_funded_by_purchase(
        api,
        40_000,
        channel="DIRECT_PURCHASE",
        email="lc1@example.com",
        full_name="Yusuf Demir",
        enrollment_date="2026-02-11",
    )
    member_id = funded["member"]["id"]
    booking = fx.book_award(api, member_id, hotel_id, "2026-07-10", "2026-07-12")
    batch = fx.open_batch(api, hotel_id, "2026-07")
    complaint = fx.file_complaint(
        api,
        member_id,
        subject_type="BLACKOUT_DISPUTE",
        headers=funded["member_headers"],
    )

    bundle["member"] = funded["member"]
    bundle["member_headers"] = funded["member_headers"]
    bundle["booking"] = booking
    bundle["batch"] = batch
    bundle["complaint"] = complaint
    return bundle


def _terminal_terrace_after_every_exit(api):
    """A stay voided, a purchase refunded and the property itself terminated - three
    rows that have taken their absorbing exit."""
    bundle = fx.create_active_hotel(
        api,
        rate_code="BAR",
        rate_category="TRANSIENT",
        name="Terminal Terrace",
        brand_code="TMT",
        market_tier="SELECT",
        program_fee_pct=0.04,
        rooms_count=70,
        trailing_12m_occupancy_pct=0.75,
        trailing_12m_adr_cents=18_000,
    )
    hotel_id = bundle["hotel"]["id"]
    member = fx.enroll_member(
        api,
        email="tm1@example.com",
        full_name="Aris Pappas",
        enrollment_date="2026-03-01",
    )
    stay = fx.capture_stay(
        api,
        hotel_id,
        member["id"],
        bundle["rate_plan"]["id"],
        "2026-07-01",
        "2026-07-03",
        40_000,
    )
    voided = fx.void_stay(api, stay["id"], reason="Booked at the wrong property.")
    purchase = fx.settled_purchase(api, member["id"], 20_000)
    refunded = validate_success(
        api.refund_point_purchase(
            purchase["id"],
            fac.refund_point_purchase_payload(
                refund_reason="Member changed their mind."
            ),
            make_care_agent_headers("care-tm-01"),
        )
    )
    terminated = fx.terminate_hotel(api, hotel_id, reason="Franchise agreement ended.")

    bundle["hotel"] = terminated
    bundle["member"] = member
    bundle["member_headers"] = make_member_headers(member["id"])
    bundle["stay"] = voided
    bundle["purchase"] = refunded
    return bundle


def _replay_residence_after_one_of_each(api):
    """A property activated once, a two-night stay posted once and a 20,000-point
    direct purchase settled once - the ground truth every replay must not disturb."""
    bundle = fx.create_active_hotel(
        api,
        rate_code="BAR",
        rate_category="TRANSIENT",
        name="Replay Residence",
        brand_code="RPR",
        market_tier="URBAN",
        program_fee_pct=0.05,
        rooms_count=100,
        trailing_12m_occupancy_pct=0.82,
        trailing_12m_adr_cents=30_000,
    )
    hotel_id = bundle["hotel"]["id"]
    member = fx.enroll_member(
        api,
        email="rp1@example.com",
        full_name="Ola Nowak",
        enrollment_date="2026-02-20",
    )
    stay = fx.posted_stay(
        api,
        hotel_id,
        member["id"],
        bundle["rate_plan"]["id"],
        "2026-07-01",
        "2026-07-03",
        20_000,
    )
    purchase = fx.settled_purchase(api, member["id"], 20_000)

    bundle["member"] = member
    bundle["stay"] = stay
    bundle["purchase"] = purchase
    return bundle


def _clockgate_hotel_with_a_future_stay_and_a_confirmed_award(api):
    """The clock left at its opening instant, with a stay that has not yet ended and
    a confirmed award booking three weeks out."""
    bundle = fx.create_active_hotel(
        api,
        rate_code="BAR",
        rate_category="TRANSIENT",
        name="Clockgate Hotel",
        brand_code="CGH",
        market_tier="URBAN",
        program_fee_pct=0.05,
        rooms_count=120,
        trailing_12m_occupancy_pct=0.82,
        trailing_12m_adr_cents=30_000,
    )
    hotel_id = bundle["hotel"]["id"]
    fx.publish_standard_pricing(
        api,
        hotel_id,
        points_per_night=20_000,
        cash_copay_cents=0,
        min_tier_required="BASE",
        award_allotment_per_night=2,
    )
    funded = fx.member_funded_by_purchase(
        api,
        40_000,
        channel="DIRECT_PURCHASE",
        email="cg1@example.com",
        full_name="Ines Duarte",
        enrollment_date="2026-01-30",
    )
    member_id = funded["member"]["id"]
    stay = fx.capture_stay(
        api,
        hotel_id,
        member_id,
        bundle["rate_plan"]["id"],
        "2026-08-10",
        "2026-08-12",
        40_000,
    )
    booking = fx.book_award(
        api,
        member_id,
        hotel_id,
        "2026-08-20",
        "2026-08-22",
        headers=funded["member_headers"],
    )
    booking = fx.confirm_award(api, booking["id"], headers=funded["member_headers"])

    bundle["member"] = funded["member"]
    bundle["member_headers"] = funded["member_headers"]
    bundle["owner_headers"] = make_hotel_owner_headers(hotel_id)
    bundle["stay"] = stay
    bundle["booking"] = booking
    return bundle


# ----------------------------------------------------------------------
# Three entity-scoped lifecycle guards on stays, purchases and windows.
# ----------------------------------------------------------------------
class TestWrongStateActionsOnStaysPurchasesAndWindows:
    def test_disputing_a_stay_that_has_not_been_posted_is_refused(self, api):
        """Only the two posted statuses admit a dispute, so a stay still awaiting
        posting is refused and keeps an empty dispute reason.

        PRD: "a dispute raised against a stay in any other status is refused with
        `ERR_STAY_INVALID_STATE`"

        Design: Corner/state_machines/wrong_state_actions_on_stays_purchases_and_windows_are_refused
        """
        bundle = _wrongstate_court_with_three_rows_mid_flight(api)
        assert_stay(bundle["stay"], status="PENDING_POSTING")

        response = api.dispute_stay(
            bundle["stay"]["id"],
            fac.dispute_stay_payload(dispute_reason="Rate looks wrong."),
            bundle["member_headers"],
        )

        validate_error(response, ApiErrorId.ERR_STAY_INVALID_STATE.value)
        after = fx.read_stay(api, bundle["stay"]["id"])
        assert_stay(after, status="PENDING_POSTING")
        assert after["dispute_reason"] is None, (
            "a refused dispute records no dispute reason"
        )

    def test_settling_an_already_settled_purchase_banks_no_second_payment(self, api):
        """The state guard fires before any cash movement, so programme cash still
        holds exactly one 20,000-point sale.

        PRD: "**Settling a purchase** is administrator-only and moves it `PENDING →
        SETTLED`; any other status is `ERR_PURCHASE_INVALID_STATE`."

        Design: Corner/state_machines/wrong_state_actions_on_stays_purchases_and_windows_are_refused
        """
        bundle = _wrongstate_court_with_three_rows_mid_flight(api)
        assert_purchase(bundle["purchase"], status="SETTLED", cash_due_cents=25_000)

        response = api.settle_point_purchase(
            bundle["purchase"]["id"], make_admin_headers()
        )

        validate_error(response, ApiErrorId.ERR_PURCHASE_INVALID_STATE.value)
        assert_purchase(
            validate_success(
                api.get_point_purchase(bundle["purchase"]["id"], make_admin_headers())
            ),
            status="SETTLED",
            cash_due_cents=25_000,
        )
        assert_fund(fx.read_fund(api), cash_cents=25_000)

    def test_revoking_a_window_still_in_draft_is_refused(self, api):
        """Revocation is the exit from an active window only, and the refused attempt
        leaves the draft's revoke reason empty.

        PRD: "Revoking anything that is not `ACTIVE` — a draft, or an already-revoked
        window — is refused with `ERR_BLACKOUT_WINDOW_INVALID_STATE`."

        Design: Corner/state_machines/wrong_state_actions_on_stays_purchases_and_windows_are_refused
        """
        bundle = _wrongstate_court_with_three_rows_mid_flight(api)
        assert_blackout_window(bundle["window"], status="DRAFT", day_count=7)

        response = api.revoke_blackout_window(
            bundle["window"]["id"],
            fac.revoke_blackout_window_payload(revoke_reason="Changed our minds."),
            make_admin_headers(),
        )

        validate_error(response, ApiErrorId.ERR_BLACKOUT_WINDOW_INVALID_STATE.value)
        after = validate_success(
            api.get_blackout_window(bundle["window"]["id"], make_admin_headers())
        )
        assert_blackout_window(after, status="DRAFT", day_count=7)
        assert after["revoke_reason"] is None, (
            "a refused revocation records no revoke reason"
        )


# ----------------------------------------------------------------------
# The remaining three guards, on batches, bookings and complaints.
# ----------------------------------------------------------------------
class TestWrongStateActionsOnBatchesRedemptionsAndComplaints:
    def test_approving_a_batch_nobody_released_reports_the_status_not_the_duties(
        self, api
    ):
        """Approval is an exit from the released state, and because the batch has no
        recorded releaser the duties comparison cannot fire - the status guard answers.

        PRD: "**Approval and rejection** are the two exits from `RELEASED`, and both
        are administrator-only."

        Design: Corner/state_machines/wrong_state_actions_on_batches_redemptions_and_complaints_are_refused
        """
        bundle = _lifecycle_lodge_with_a_row_in_every_opening_state(api)
        assert bundle["batch"]["released_by_user_id"] is None, (
            "an open batch has no releasing operator for the duties check to compare"
        )

        response = api.approve_batch(
            bundle["batch"]["id"], make_admin_headers("op-approve-lc")
        )

        validate_error(response, ApiErrorId.ERR_BATCH_INVALID_STATE.value)
        after = fx.read_batch(api, bundle["batch"]["id"])
        assert_batch(after, status="OPEN", item_count=0, net_payable_cents=0)
        assert after["approved_by_user_id"] is None, (
            "the refused approval recorded no approving operator"
        )

    def test_a_no_show_against_a_held_booking_outranks_the_arrival_check(self, api):
        """The arrival date has already passed, so the only thing standing in the way
        is the booking's own status - and that is the refusal reported.

        PRD: "The `checkin_date` must be on or before the clock's current date, else
        `ERR_REDEMPTION_NOT_ARRIVED`; any status other than `CONFIRMED` is
        `ERR_REDEMPTION_INVALID_STATE`."

        Design: Corner/state_machines/wrong_state_actions_on_batches_redemptions_and_complaints_are_refused
        """
        bundle = _lifecycle_lodge_with_a_row_in_every_opening_state(api)
        assert_redemption(bundle["booking"], fulfillment_status="HELD")

        response = api.no_show_redemption(bundle["booking"]["id"], make_admin_headers())

        validate_error(response, ApiErrorId.ERR_REDEMPTION_INVALID_STATE.value)
        assert_redemption(
            fx.read_redemption(api, bundle["booking"]["id"]),
            fulfillment_status="HELD",
            reimbursement_status="NOT_DUE",
            points_charged=40_000,
        )

    def test_adjudicating_a_complaint_nobody_reviewed_is_refused(self, api):
        """Adjudication is reachable only from the escalated state, and a freshly
        filed complaint is nowhere near it.

        PRD: "Every one of the six complaint actions is gated on the complaint's own
        status, and any mismatch is `ERR_COMPLAINT_INVALID_STATE`"

        Design: Corner/state_machines/wrong_state_actions_on_batches_redemptions_and_complaints_are_refused
        """
        bundle = _lifecycle_lodge_with_a_row_in_every_opening_state(api)
        assert_complaint(bundle["complaint"], status="OPEN", subject_type="BLACKOUT_DISPUTE")

        response = api.adjudicate_complaint(
            bundle["complaint"]["id"],
            fac.adjudicate_complaint_payload(adjudication_outcome="DENIAL_UPHELD"),
            make_admin_headers(),
        )

        validate_error(response, ApiErrorId.ERR_COMPLAINT_INVALID_STATE.value)
        after = fx.read_complaint(api, bundle["complaint"]["id"])
        assert_complaint(after, status="OPEN", info_request_count=0)
        assert after["adjudication_outcome"] is None, (
            "the refused adjudication recorded no outcome"
        )


# ----------------------------------------------------------------------
# Absorbing rows: a void stay, a refunded purchase, a terminated property.
# ----------------------------------------------------------------------
class TestTerminalRowsAndATerminatedPropertyAdmitNothingFurther:
    def test_the_three_exits_landed_where_the_setup_intended(self, api):
        """Before any replay is attempted, each row is sitting in its absorbing state
        with the reason that put it there.

        PRD: "The caller supplies a `termination_reason`, which is recorded on the
        property; before termination that field is null."

        Design: Corner/state_machines/terminal_rows_and_a_terminated_property_admit_nothing_further
        """
        bundle = _terminal_terrace_after_every_exit(api)

        assert_stay(bundle["stay"], status="VOID")
        assert_purchase(
            bundle["purchase"],
            status="REFUNDED",
            refund_reason="Member changed their mind.",
        )
        assert_hotel(
            bundle["hotel"],
            status="TERMINATED",
            termination_reason="Franchise agreement ended.",
        )
        assert_fund(fx.read_fund(api), cash_cents=0, outstanding_points=0)

    def test_a_second_void_is_refused_and_keeps_the_first_reason(self, api):
        """Void absorbs: the row cannot be voided out of the state it is already in,
        and the refusal does not overwrite the recorded reason.

        PRD: "the stay moves to `VOID` from any status that is not already `VOID` —
        `PENDING_POSTING`, `POSTED_QUALIFYING`, `POSTED_NON_QUALIFYING` and `DISPUTED`
        are all valid origins, and a second void is refused with
        `ERR_STAY_INVALID_STATE`."

        Design: Corner/state_machines/terminal_rows_and_a_terminated_property_admit_nothing_further
        """
        bundle = _terminal_terrace_after_every_exit(api)

        response = api.void_stay(
            bundle["stay"]["id"],
            fac.void_stay_payload(void_reason="Trying again."),
            make_admin_headers(),
        )

        validate_error(response, ApiErrorId.ERR_STAY_INVALID_STATE.value)
        after = fx.read_stay(api, bundle["stay"]["id"])
        assert_stay(after, status="VOID")
        assert after["void_reason"] == "Booked at the wrong property.", (
            "the second void did not overwrite the first reason, got "
            f"{after['void_reason']!r}"
        )

    def test_a_dispute_against_a_void_stay_is_refused_too(self, api):
        """The dispute path is closed as well - a void stay admits no further action
        from any actor.

        PRD: "a dispute raised against a stay in any other status is refused with
        `ERR_STAY_INVALID_STATE`"

        Design: Corner/state_machines/terminal_rows_and_a_terminated_property_admit_nothing_further
        """
        bundle = _terminal_terrace_after_every_exit(api)

        response = api.dispute_stay(
            bundle["stay"]["id"],
            fac.dispute_stay_payload(dispute_reason="Still unhappy."),
            bundle["member_headers"],
        )

        validate_error(response, ApiErrorId.ERR_STAY_INVALID_STATE.value)
        after = fx.read_stay(api, bundle["stay"]["id"])
        assert_stay(after, status="VOID")
        assert after["dispute_reason"] is None, (
            "a refused dispute against a void stay records nothing"
        )

    def test_a_second_refund_on_a_refunded_purchase_is_refused(self, api):
        """The compensating action can only be taken once, so a second refund neither
        moves cash nor rewrites the reason.

        PRD: "moves it `SETTLED → REFUNDED` with a `refund_reason`, and is the exact
        compensating action for settlement; any status other than `SETTLED` is
        `ERR_PURCHASE_INVALID_STATE`."

        Design: Corner/state_machines/terminal_rows_and_a_terminated_property_admit_nothing_further
        """
        bundle = _terminal_terrace_after_every_exit(api)

        response = api.refund_point_purchase(
            bundle["purchase"]["id"],
            fac.refund_point_purchase_payload(refund_reason="Second refund attempt."),
            make_care_agent_headers("care-tm-01"),
        )

        validate_error(response, ApiErrorId.ERR_PURCHASE_INVALID_STATE.value)
        assert_purchase(
            validate_success(
                api.get_point_purchase(bundle["purchase"]["id"], make_admin_headers())
            ),
            status="REFUNDED",
            refund_reason="Member changed their mind.",
        )
        assert_fund(fx.read_fund(api), cash_cents=0)

    def test_a_terminated_property_refuses_both_termination_and_activation(self, api):
        """Termination demands a trading property and activation demands an onboarding
        one, so a terminated property satisfies neither and its version stands still.

        PRD: "Activation requires exactly `ONBOARDING`; termination requires `ACTIVE`
        or `FEE_DELINQUENT`, so an onboarding property cannot be terminated and a
        terminated one cannot be terminated twice."

        Design: Corner/state_machines/terminal_rows_and_a_terminated_property_admit_nothing_further
        """
        bundle = _terminal_terrace_after_every_exit(api)
        hotel_id = bundle["hotel"]["id"]
        version_at_termination = bundle["hotel"]["version"]

        again = api.terminate_hotel(
            hotel_id,
            fac.terminate_hotel_payload(termination_reason="Terminating again."),
            make_admin_headers(),
        )
        reopen = api.activate_hotel(hotel_id, make_admin_headers())

        validate_error(again, ApiErrorId.ERR_HOTEL_NOT_ACTIVE.value)
        validate_error(reopen, ApiErrorId.ERR_HOTEL_NOT_ACTIVE.value)
        after = fx.read_hotel(api, hotel_id)
        assert_hotel(
            after,
            status="TERMINATED",
            termination_reason="Franchise agreement ended.",
            version=version_at_termination,
        )

    def test_a_terminated_property_refuses_a_new_rate_plan(self, api):
        """Registration is open in every status but the terminal one, so the property's
        rate plan collection is closed for good at the one plan it already has.

        PRD: "A rate plan may be registered while the property is in any status other
        than `TERMINATED`; attempting it on a terminated property yields
        `ERR_HOTEL_NOT_ACTIVE`."

        Design: Corner/state_machines/terminal_rows_and_a_terminated_property_admit_nothing_further
        """
        bundle = _terminal_terrace_after_every_exit(api)
        hotel_id = bundle["hotel"]["id"]

        response = api.create_rate_plan(
            hotel_id,
            fac.create_rate_plan_payload(
                rate_code="COR", rate_category="CORPORATE_NEGOTIATED"
            ),
            make_admin_headers(),
        )

        validate_error(response, ApiErrorId.ERR_HOTEL_NOT_ACTIVE.value)
        plans = collect_all(api.list_rate_plans, make_admin_headers(), hotel_id=hotel_id)
        assert len(plans) == 1, (
            f"the terminated property keeps its single rate plan, got {len(plans)}"
        )
        assert plans[0]["rate_code"] == "BAR", (
            "the surviving plan is the one registered while the property still traded"
        )


# ----------------------------------------------------------------------
# Replays are refused on the state guard, and nothing doubles.
# ----------------------------------------------------------------------
class TestRepeatingActivatePostAndSettleIsRefused:
    def test_replaying_the_activation_is_refused_and_bumps_nothing(self, api):
        """A second activation is a refusal rather than a repeat, so the property's
        version stands exactly where the single successful pass left it.

        PRD: "Two conditions are checked, in this order: the property's status must be
        exactly `ONBOARDING`, so a second activation attempt on an already-active
        property is refused with `ERR_HOTEL_NOT_ACTIVE` rather than silently repeated"

        Design: Corner/state_machines/repeating_activate_post_and_settle_is_refused_rather_than_applied_twice
        """
        bundle = _replay_residence_after_one_of_each(api)
        hotel_id = bundle["hotel"]["id"]
        version_before = fx.hotel_version(api, hotel_id)

        response = api.activate_hotel(hotel_id, make_admin_headers())

        validate_error(response, ApiErrorId.ERR_HOTEL_NOT_ACTIVE.value)
        assert_hotel(fx.read_hotel(api, hotel_id), status="ACTIVE", version=version_before)

    def test_replaying_the_posting_is_refused_on_the_stays_own_status(self, api):
        """Posting is a one-way exit from the pending state, so the second attempt is
        refused and the stay's awards stand at their single-pass figures.

        PRD: "the stay must be in `PENDING_POSTING`, else `ERR_STAY_INVALID_STATE`"

        Design: Corner/state_machines/repeating_activate_post_and_settle_is_refused_rather_than_applied_twice
        """
        bundle = _replay_residence_after_one_of_each(api)
        assert_stay(
            bundle["stay"], status="POSTED_QUALIFYING", base_points=2_000, fee_cents=1_000
        )

        response = api.post_stay(bundle["stay"]["id"], make_admin_headers())

        validate_error(response, ApiErrorId.ERR_STAY_INVALID_STATE.value)
        assert_stay(
            fx.read_stay(api, bundle["stay"]["id"]),
            status="POSTED_QUALIFYING",
            base_points=2_000,
            bonus_points=0,
            fee_cents=1_000,
        )

    def test_replaying_the_settlement_is_refused_on_the_purchases_own_status(self, api):
        """The settled purchase cannot be settled again, so its priced cash figure is
        banked exactly once.

        PRD: "**Settling a purchase** is administrator-only and moves it `PENDING →
        SETTLED`; any other status is `ERR_PURCHASE_INVALID_STATE`."

        Design: Corner/state_machines/repeating_activate_post_and_settle_is_refused_rather_than_applied_twice
        """
        bundle = _replay_residence_after_one_of_each(api)

        response = api.settle_point_purchase(
            bundle["purchase"]["id"], make_admin_headers()
        )

        validate_error(response, ApiErrorId.ERR_PURCHASE_INVALID_STATE.value)
        assert_purchase(
            validate_success(
                api.get_point_purchase(bundle["purchase"]["id"], make_admin_headers())
            ),
            status="SETTLED",
            points_quantity=20_000,
            volume_discount_pct=0.0,
            cash_due_cents=25_000,
        )

    def test_the_fee_ledger_carries_one_stays_fee_rather_than_two(self, api):
        """The ledger is re-derived from the property's stays, and there is still only
        one posted stay to derive it from after the refused replay.

        PRD: "Per stay, the fee is the stay's `room_revenue_cents` multiplied by the
        property's `program_fee_pct`, rounded half up to the whole cent, and stored on
        the stay as `program_fee_assessed_cents`"

        Design: Corner/state_machines/repeating_activate_post_and_settle_is_refused_rather_than_applied_twice
        """
        bundle = _replay_residence_after_one_of_each(api)
        hotel_id = bundle["hotel"]["id"]

        api.post_stay(bundle["stay"]["id"], make_admin_headers())

        assert_hotel(fx.read_hotel(api, hotel_id), status="ACTIVE", fee_ledger_cents=1_000)
        assert len(fx.stays_of_hotel(api, hotel_id)) == 1, (
            "the refused replay created no second stay to be charged for"
        )

    def test_exactly_one_ledger_row_survives_for_each_source(self, api):
        """Each of the two refused replays would have written its own entry; neither
        did, so the earning row and the purchase row are singletons.

        PRD: "one `EARN_BONUS` entry is written with `points` equal to
        `bonus_points_awarded` and the same `source_stay_id`, and that second entry is
        emitted **only** when `bonus_points_awarded` is greater than zero."

        Design: Corner/state_machines/repeating_activate_post_and_settle_is_refused_rather_than_applied_twice
        """
        bundle = _replay_residence_after_one_of_each(api)

        api.post_stay(bundle["stay"]["id"], make_admin_headers())
        api.settle_point_purchase(bundle["purchase"]["id"], make_admin_headers())

        stay_entries = fx.ledger_for_stay(api, bundle["stay"]["id"])
        purchase_entries = fx.ledger_for_purchase(api, bundle["purchase"]["id"])
        assert len(stay_entries) == 1, (
            f"a base-tier stay writes one earning row, got {len(stay_entries)}"
        )
        assert_ledger_entry(
            stay_entries[0],
            entry_type="EARN_BASE",
            points=2_000,
            source_stay_id=bundle["stay"]["id"],
        )
        assert len(purchase_entries) == 1, (
            f"a direct purchase writes one row, got {len(purchase_entries)}"
        )
        assert_ledger_entry(
            purchase_entries[0],
            entry_type="PURCHASE",
            points=20_000,
            source_purchase_id=bundle["purchase"]["id"],
        )

    def test_the_member_balance_and_programme_cash_are_not_doubled(self, api):
        """Both derived totals are sums over rows that never multiplied, so the guest
        holds one earning plus one purchase and the fund holds one payment.

        PRD: "On the member side, `point_balance` is the signed sum of `points` across
        that member's ledger entries"

        Design: Corner/state_machines/repeating_activate_post_and_settle_is_refused_rather_than_applied_twice
        """
        bundle = _replay_residence_after_one_of_each(api)

        api.activate_hotel(bundle["hotel"]["id"], make_admin_headers())
        api.post_stay(bundle["stay"]["id"], make_admin_headers())
        api.settle_point_purchase(bundle["purchase"]["id"], make_admin_headers())

        assert_member(
            fx.read_member(api, bundle["member"]["id"]),
            point_balance=22_000,
            lifetime_points_earned=22_000,
            points_purchased_current_year=20_000,
        )
        assert_fund(fx.read_fund(api), cash_cents=25_000, outstanding_points=22_000)


# ----------------------------------------------------------------------
# Three transitions gated on the logical clock rather than on stored state.
# ----------------------------------------------------------------------
class TestPostingAndCompletingBeforeTheDatesHavePassed:
    def test_a_stay_whose_checkout_is_still_ahead_cannot_be_posted(self, api):
        """The stay is in exactly the right status at exactly the right property, and
        the only thing wrong with it is that the guest has not left yet.

        PRD: "the logical clock's current date must be on or after the stay's
        `checkout_date`, else `ERR_STAY_NOT_COMPLETED` — a stay may only be posted once
        it has actually ended."

        Design: Corner/state_machines/posting_and_completing_before_the_dates_have_passed_are_both_refused
        """
        bundle = _clockgate_hotel_with_a_future_stay_and_a_confirmed_award(api)
        assert_stay(bundle["stay"], status="PENDING_POSTING", nights=2)

        response = api.post_stay(bundle["stay"]["id"], bundle["owner_headers"])

        validate_error(response, ApiErrorId.ERR_STAY_NOT_COMPLETED.value)
        assert_stay(
            fx.read_stay(api, bundle["stay"]["id"]),
            status="PENDING_POSTING",
            base_points=0,
            fee_cents=0,
        )

    def test_a_confirmed_award_cannot_be_completed_before_its_checkout(self, api):
        """Completion is the owner's own action and the booking is confirmed, but the
        departure date has not arrived, so the request is refused on the calendar.

        PRD: "The booking's `checkout_date` must be on or before the logical clock's
        current date, else `ERR_REDEMPTION_NOT_ELAPSED`; any status other than
        `CONFIRMED` is `ERR_REDEMPTION_INVALID_STATE`."

        Design: Corner/state_machines/posting_and_completing_before_the_dates_have_passed_are_both_refused
        """
        bundle = _clockgate_hotel_with_a_future_stay_and_a_confirmed_award(api)
        assert_redemption(bundle["booking"], fulfillment_status="CONFIRMED")

        response = api.complete_redemption_stay(
            bundle["booking"]["id"], bundle["owner_headers"]
        )

        validate_error(response, ApiErrorId.ERR_REDEMPTION_NOT_ELAPSED.value)
        assert_redemption(
            fx.read_redemption(api, bundle["booking"]["id"]),
            fulfillment_status="CONFIRMED",
            reimbursement_status="NOT_DUE",
            estimated_cents=0,
        )

    def test_a_confirmed_award_cannot_be_no_showed_before_its_arrival(self, api):
        """The no-show gate is keyed on the arrival date rather than the departure one,
        and that date is in the future too.

        PRD: "The `checkin_date` must be on or before the clock's current date, else
        `ERR_REDEMPTION_NOT_ARRIVED`; any status other than `CONFIRMED` is
        `ERR_REDEMPTION_INVALID_STATE`."

        Design: Corner/state_machines/posting_and_completing_before_the_dates_have_passed_are_both_refused
        """
        bundle = _clockgate_hotel_with_a_future_stay_and_a_confirmed_award(api)

        response = api.no_show_redemption(
            bundle["booking"]["id"], bundle["owner_headers"]
        )

        validate_error(response, ApiErrorId.ERR_REDEMPTION_NOT_ARRIVED.value)
        assert_redemption(
            fx.read_redemption(api, bundle["booking"]["id"]),
            fulfillment_status="CONFIRMED",
            reimbursement_status="NOT_DUE",
            points_charged=40_000,
        )

    def test_advancing_the_clock_lets_the_identical_completion_succeed(self, api):
        """Nothing about the booking changed - only the clock did - and the same call
        now carries the room into the owed set.

        PRD: "the reimbursement dimension advances `NOT_DUE → ACCRUED` in the same
        request and `estimated_reimbursement_cents` is computed under the **accrual**
        reading of the reimbursement formula"

        Design: Corner/state_machines/posting_and_completing_before_the_dates_have_passed_are_both_refused
        """
        bundle = _clockgate_hotel_with_a_future_stay_and_a_confirmed_award(api)
        api.complete_redemption_stay(bundle["booking"]["id"], bundle["owner_headers"])

        fx.set_clock(api, "2026-08-22T11:00:00Z")
        response = api.complete_redemption_stay(
            bundle["booking"]["id"], bundle["owner_headers"]
        )

        completed = validate_success(response)
        assert_redemption(
            completed, fulfillment_status="STAYED", reimbursement_status="ACCRUED"
        )

    def test_the_strong_demand_band_prices_the_completed_award_at_forty_five_thousand(
        self, api
    ):
        """Occupancy of 0.82 sits in the middle band, so each of the two nights accrues
        three quarters of a 30,000-cent daily rate and the property is owed the sum.

        PRD: "When occupancy is below 0.95 but at or above 0.80 — strong demand — the
        rate per night is seventy-five percent of the average daily rate, rounded half
        up to the cent."

        Design: Corner/state_machines/posting_and_completing_before_the_dates_have_passed_are_both_refused
        """
        bundle = _clockgate_hotel_with_a_future_stay_and_a_confirmed_award(api)
        fx.set_clock(api, "2026-08-22T11:00:00Z")

        completed = fx.complete_award_stay(
            api, bundle["booking"]["id"], headers=bundle["owner_headers"]
        )

        assert_redemption(
            completed,
            fulfillment_status="STAYED",
            reimbursement_status="ACCRUED",
            estimated_cents=45_000,
            settled_cents=0,
            nights=2,
        )
        # The owed figure is defined as "the sum of `settled_reimbursement_cents`
        # across that property's award bookings whose `reimbursement_status` is
        # either `ACCRUED` or `BATCHED`", and the settlement figure is only written
        # at release, so an accrued-but-unbatched night contributes nothing yet.
        assert_hotel(
            fx.read_hotel(api, bundle["hotel"]["id"]),
            status="ACTIVE",
            reimbursement_owed_cents=0,
        )
