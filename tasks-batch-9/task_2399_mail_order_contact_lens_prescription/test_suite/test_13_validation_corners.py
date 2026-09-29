"""Validation corners: uniqueness scoping, capture-mode evidence obligations,
cross-entity gates, temporal windows, aggregate allowance and the release path
where every guard is satisfied.
"""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    CO_ALPHA,
    CO_ALPHA_HEADERS,
    CO_BRAVO,
    CO_BRAVO_HEADERS,
    DEFAULT_CLOCK_UTC,
    WORKING_TUESDAY_10AM,
    ApiErrorId,
    assert_compliance_event,
    assert_ledger_values,
    assert_prescriber,
    assert_prescription,
    assert_reorder_hold,
    assert_timestamp_equals,
    create_prescription_payload,
    make_compliance_headers,
    make_customer_headers,
    new_prescriber,
    new_reorder_hold,
    retire_insurance_plan,
    set_clock,
    setup_allowance_partly_consumed,
    setup_generated_claim,
    setup_pending_verification_prescription,
    setup_reference_data,
    setup_second_delivered_order,
    setup_verified_prescription,
    suspend_prescriber,
    validate_error,
    validate_paginated,
    validate_success,
)

THIN_PLAN_OVERRIDES = {"name": "ThinPlan", "annual_allowance_cents": 6400}
"""A 6400-cent annual allowance, exactly the price of one two-box order."""


def _capture_payload_without_companion(customer_id, product_id, capture_mode):
    """A complete capture body for `capture_mode` that is missing only the
    companion field that mode demands."""
    payload = create_prescription_payload(customer_id, product_id)
    payload.pop("document_reference", None)
    payload["capture_mode"] = capture_mode
    return payload


def _plan_allowance_fully_consumed_with_second_draft_claim():
    """A 6400-cent-allowance customer whose first delivered order carries a
    GENERATED claim that swallowed the whole plan-year pool, plus a second
    delivered order carrying a DRAFT claim."""
    scenario = setup_allowance_partly_consumed(
        plan_overrides=THIN_PLAN_OVERRIDES,
        clock=DEFAULT_CLOCK_UTC,
    )
    return setup_second_delivered_order(scenario)


class TestPrescriberLicenceUniqueness:
    def test_duplicate_licence_in_the_same_state_is_rejected_and_another_state_passes(
        self, api
    ):
        """PRD §3.1: "A licence number must be unique within a state; a collision
        is rejected with `ERR_DUPLICATE_LICENSE`."

        PRD §3.1: "The boolean `directory_verified` defaults to false and is set
        true when the provider was matched from the authoritative provider
        directory — a distinction that shortens the passive verification clock,
        as §3.3 explains."

        Design: Corner/validations/duplicate_license_in_the_same_state_is_rejected_and_another_state_passes
        """
        set_clock(DEFAULT_CLOCK_UTC)
        incumbent = new_prescriber(
            license_number="UT-40921", license_state="UT", contact_channel="PORTAL"
        )
        assert incumbent["license_number"] == "UT-40921"
        assert incumbent["license_state"] == "UT"

        collision_payload = {
            "full_name": "Dr. Other Person",
            "license_number": "UT-40921",
            "license_state": "UT",
            "contact_channel": "FAX",
        }
        validate_error(
            api.create_prescriber(collision_payload, ADMIN_HEADERS),
            ApiErrorId.ERR_DUPLICATE_LICENSE,
        )

        in_state, in_state_meta = validate_paginated(
            api.list_prescribers(ADMIN_HEADERS, params={"license_state": "UT"})
        )
        assert in_state_meta["total_count"] == 1, (
            "the refused registration must not have created a second UT row"
        )
        assert len(in_state) == 1

        other_state_payload = dict(collision_payload, license_state="NV")
        accepted = validate_success(
            api.create_prescriber(other_state_payload, ADMIN_HEADERS), 201
        )
        assert_prescriber(accepted)
        assert accepted["license_number"] == "UT-40921"
        assert accepted["license_state"] == "NV"
        assert accepted["directory_verified"] is False
        assert accepted["status"] == "ACTIVE"


class TestCaptureModeCompanionFields:
    @pytest.mark.parametrize(
        "capture_mode,expected_error",
        [
            ("UPLOAD", ApiErrorId.ERR_CAPTURE_MODE_REQUIRES_DOCUMENT),
            ("DOCTOR_LOOKUP", ApiErrorId.ERR_CAPTURE_MODE_REQUIRES_PRESCRIBER),
            ("SELF_REPORT", ApiErrorId.ERR_SELF_REPORT_REQUIRES_NAME),
        ],
    )
    def test_capture_mode_missing_its_companion_field_is_rejected(
        self, api, capture_mode, expected_error
    ):
        """PRD §3.2: "Each capture mode carries its own evidence obligation,
        checked both at capture time and again at submit."

        PRD §3.2: "An `UPLOAD` capture must carry a `document_reference` naming
        the scan, or the request fails with `ERR_CAPTURE_MODE_REQUIRES_DOCUMENT`."

        PRD §3.2: "A `DOCTOR_LOOKUP` capture must carry a `prescriber_id`, or the
        request fails with `ERR_CAPTURE_MODE_REQUIRES_PRESCRIBER`; a
        `prescriber_id` that names no stored provider yields
        `ERR_PRESCRIBER_NOT_FOUND`."

        PRD §3.2: "A `SELF_REPORT` capture must carry a
        `self_reported_prescriber_name` in free text, or the request fails with
        `ERR_SELF_REPORT_REQUIRES_NAME`."

        Design: Corner/validations/capture_mode_companion_fields_are_enforced_per_mode
        """
        scenario = setup_reference_data(clock=DEFAULT_CLOCK_UTC)
        customer_id = scenario["customer"]["id"]

        payload = _capture_payload_without_companion(
            customer_id, scenario["product"]["id"], capture_mode
        )
        validate_error(
            api.create_prescription(payload, make_customer_headers(customer_id)),
            expected_error,
        )

        _, meta = validate_paginated(
            api.list_prescriptions(
                CO_ALPHA_HEADERS, params={"customer_id": customer_id}
            )
        )
        assert meta["total_count"] == 0, (
            "a capture refused for a missing companion field must persist no row"
        )

    def test_self_report_capture_naming_a_prescriber_is_accepted_in_draft(self, api):
        """PRD §3.2: "A `SELF_REPORT` capture must carry a
        `self_reported_prescriber_name` in free text, or the request fails with
        `ERR_SELF_REPORT_REQUIRES_NAME`."

        PRD §3.2: "A newly captured prescription is in `DRAFT`."

        Design: Corner/validations/capture_mode_companion_fields_are_enforced_per_mode
        """
        scenario = setup_reference_data(clock=DEFAULT_CLOCK_UTC)
        customer_id = scenario["customer"]["id"]

        payload = _capture_payload_without_companion(
            customer_id, scenario["product"]["id"], "SELF_REPORT"
        )
        payload["self_reported_prescriber_name"] = "Dr. Unknown"

        captured = validate_success(
            api.create_prescription(payload, make_customer_headers(customer_id)), 201
        )
        assert_prescription(captured)
        assert captured["status"] == "DRAFT"
        assert captured["capture_mode"] == "SELF_REPORT"

        _, meta = validate_paginated(
            api.list_prescriptions(
                CO_ALPHA_HEADERS, params={"customer_id": customer_id}
            )
        )
        assert meta["total_count"] == 1


class TestVerificationRoundPrescriberGate:
    def test_suspended_prescriber_blocks_a_new_verification_round(self, api):
        """PRD §3.1: "A prescriber's `status` is `ACTIVE` or `SUSPENDED`,
        defaulting to `ACTIVE`; suspension blocks any new verification contact
        and yields `ERR_PRESCRIBER_SUSPENDED`."

        PRD §3.3: "Both variants of the round-opening are governed by the same
        four gates, evaluated in the order given in §2.10: the named provider's
        `status` must be `ACTIVE`, or the contact is refused with
        `ERR_PRESCRIBER_SUSPENDED`; the same provider must not already have been
        contacted about the same prescription inside the four-business-hour
        cooldown window, or the contact is refused with
        `ERR_PRESCRIBER_CONTACT_COOLDOWN` at HTTP 429; the provider must
        currently hold fewer than three verification requests in `SENT` status
        counted across every prescription in the system, or the contact is
        refused with `ERR_PRESCRIBER_REQUEST_CAPACITY`; and the prescription's
        `verification_rounds` must be strictly less than the round cap of three,
        or the contact is refused with `ERR_MAX_VERIFICATION_ROUNDS`."

        PRD §3.2: "It also carries two derived counters: `boxes_consumed`, the
        running box ledger described in §2.7, and `verification_rounds`, the
        number of verification contacts sent on its behalf, both starting at
        zero."

        Design: Corner/validations/suspended_prescriber_blocks_a_new_verification_round
        """
        scenario = setup_pending_verification_prescription(clock=WORKING_TUESDAY_10AM)
        prescription_id = scenario["prescription"]["id"]
        prescriber_id = scenario["prescriber"]["id"]
        assert scenario["prescription"]["status"] == "PENDING_VERIFICATION"

        suspend_prescriber(prescriber_id)

        validate_error(
            api.send_verification_request(
                prescription_id, {"prescriber_id": prescriber_id}, CO_ALPHA_HEADERS
            ),
            ApiErrorId.ERR_PRESCRIBER_SUSPENDED,
        )

        prescription = validate_success(
            api.get_prescription(prescription_id, CO_ALPHA_HEADERS)
        )
        assert prescription["status"] == "PENDING_VERIFICATION"
        assert prescription["verification_rounds"] == 0

        _, meta = validate_paginated(
            api.list_verification_requests(
                CO_ALPHA_HEADERS, params={"prescription_id": prescription_id}
            )
        )
        assert meta["total_count"] == 0, (
            "a refused round must not create a verification request row"
        )

        prescriber = validate_success(api.get_prescriber(prescriber_id, ADMIN_HEADERS))
        assert prescriber["status"] == "SUSPENDED"


class TestClaimSubmissionWindow:
    def test_claim_submission_after_the_ninety_day_window_is_refused(self, api):
        """PRD §3.9: "Submission moves a claim from `GENERATED` to `SUBMITTED`."

        PRD §3.9: "It requires `packet_reference` to be present and the current
        logical date to still fall within the plan's `claim_window_days` of
        `delivered_at`, failing which it is refused with
        `ERR_CLAIM_WINDOW_CLOSED`."

        Design: Corner/validations/claim_submission_after_the_ninety_day_window_is_refused
        """
        scenario = setup_generated_claim(clock=DEFAULT_CLOCK_UTC)
        claim_id = scenario["claim"]["id"]
        assert scenario["claim"]["status"] == "GENERATED"
        assert scenario["order"]["delivered_at"] is not None

        set_clock("2026-10-31T09:00:00Z")

        validate_error(
            api.submit_reimbursement_claim(claim_id, CO_BRAVO_HEADERS),
            ApiErrorId.ERR_CLAIM_WINDOW_CLOSED,
        )

        claim = validate_success(
            api.get_reimbursement_claim(claim_id, CO_ALPHA_HEADERS)
        )
        assert claim["status"] == "GENERATED"
        assert claim.get("submitted_at") is None

    def test_claim_submission_on_the_final_window_day_is_accepted(self, api):
        """PRD §3.9: "The current logical date must not be more than the plan's
        `claim_window_days` past the order's `delivered_at`, or generation is
        refused with `ERR_CLAIM_WINDOW_CLOSED`."

        PRD §3.9: "It stamps `submitted_at` from the logical clock and leaves
        allowance consumption unchanged."

        Design: Corner/validations/claim_submission_after_the_ninety_day_window_is_refused
        """
        scenario = setup_generated_claim(clock=DEFAULT_CLOCK_UTC)
        claim_id = scenario["claim"]["id"]
        allowance_consumed = scenario["claim"]["applied_allowance_cents"]

        set_clock("2026-10-31T09:00:00Z")
        validate_error(
            api.submit_reimbursement_claim(claim_id, CO_BRAVO_HEADERS),
            ApiErrorId.ERR_CLAIM_WINDOW_CLOSED,
        )

        # Day ninety, counted from a 2026-08-01 delivery, is still inside.
        set_clock("2026-10-30T09:00:00Z")
        submitted = validate_success(
            api.submit_reimbursement_claim(claim_id, CO_BRAVO_HEADERS)
        )
        assert submitted["status"] == "SUBMITTED"
        assert_timestamp_equals(submitted["submitted_at"], "2026-10-30T09:00:00.000Z")

        ledger = validate_success(
            api.get_customer_ledger(
                scenario["customer"]["id"],
                make_customer_headers(scenario["customer"]["id"]),
            )
        )
        assert_ledger_values(ledger, allowance_used_cents=allowance_consumed)


class TestPlanYearAllowanceExhaustion:
    def test_allowance_exhausted_blocks_the_second_claim_generation(self, api):
        """PRD §3.9: "And the remaining plan-year allowance must be strictly
        greater than zero, or generation is refused with
        `ERR_ALLOWANCE_EXHAUSTED`."

        PRD §3.9: "`applied_allowance_cents` is whichever is smaller,
        `base_eligible_cents` or that remaining allowance."

        PRD §3.9: "`processing_fee_cents` is keyed on `pre_fee_subtotal_cents`
        across three tiers: nothing at all when it is at most 5,000 cents, 250
        cents when it is above 5,000 cents and at most 15,000 cents, and 500
        cents above that."

        PRD §2.7: "`allowance_remaining_cents` is the plan's
        `annual_allowance_cents` less `allowance_used_cents`, floored at zero;
        for a self-pay customer who carries no `insurance_plan_id` it is zero."

        Design: Corner/validations/allowance_exhausted_blocks_the_second_claim_generation
        """
        scenario = _plan_allowance_fully_consumed_with_second_draft_claim()
        first_claim = scenario["first_claim"]
        assert first_claim["applied_allowance_cents"] == 6400
        assert first_claim["coinsurance_cents"] == 0
        assert first_claim["pre_fee_subtotal_cents"] == 6400
        assert first_claim["processing_fee_cents"] == 250
        assert first_claim["reimbursable_cents"] == 6150

        second_claim_id = scenario["claim"]["id"]
        validate_error(
            api.generate_reimbursement_claim(second_claim_id, CO_ALPHA_HEADERS),
            ApiErrorId.ERR_ALLOWANCE_EXHAUSTED,
        )

        second_claim = validate_success(
            api.get_reimbursement_claim(second_claim_id, CO_ALPHA_HEADERS)
        )
        assert second_claim["status"] == "DRAFT"

        customer_id = scenario["customer"]["id"]
        ledger = validate_success(
            api.get_customer_ledger(customer_id, make_customer_headers(customer_id))
        )
        assert_ledger_values(
            ledger, allowance_used_cents=6400, allowance_remaining_cents=0
        )

    def test_retired_plan_outranks_exhausted_allowance_on_claim_generation(self, api):
        """PRD §2.10: "When several checks could reject the same request, the
        outcome is determined by a fixed, total ordering."

        PRD §2.10: "The first check that fails determines the response, and no
        later check is evaluated."

        PRD §2.10: "Plan is not retired, on claim creation and claim generation →
        `ERR_PLAN_RETIRED` (409)."

        PRD §2.10: "Plan-year allowance remains, on claim generation →
        `ERR_ALLOWANCE_EXHAUSTED` (409)."

        PRD §3.9: "The claim is created in `DRAFT` with every money field null
        except `refund_offset_cents`, which is seeded from the settled returns
        already recorded against the order."

        Design: Corner/validations/retired_plan_outranks_exhausted_allowance_on_claim_generation
        """
        scenario = _plan_allowance_fully_consumed_with_second_draft_claim()
        plan_id = scenario["plan"]["id"]
        second_claim_id = scenario["claim"]["id"]

        retire_insurance_plan(plan_id)

        validate_error(
            api.generate_reimbursement_claim(second_claim_id, CO_ALPHA_HEADERS),
            ApiErrorId.ERR_PLAN_RETIRED,
        )

        plan = validate_success(api.get_insurance_plan(plan_id, CO_ALPHA_HEADERS))
        assert plan["status"] == "RETIRED"
        assert plan["network_status"] == "OUT_OF_NETWORK"

        second_claim = validate_success(
            api.get_reimbursement_claim(second_claim_id, CO_ALPHA_HEADERS)
        )
        assert second_claim["status"] == "DRAFT"
        assert second_claim["reimbursable_cents"] is None

        customer_id = scenario["customer"]["id"]
        ledger = validate_success(
            api.get_customer_ledger(customer_id, make_customer_headers(customer_id))
        )
        assert_ledger_values(ledger, allowance_used_cents=6400)


class TestHoldReleaseGuardsSatisfied:
    def test_hold_release_by_a_second_officer_succeeds_when_no_dispute_is_open(
        self, api
    ):
        """PRD §3.7: "Opening a hold manually records the acting `X-User-ID` in
        `opened_by_user_id`, increments the customer's `open_hold_count`,
        recomputes `auto_reorder_enabled`, and appends a `HOLD_OPENED`
        compliance event."

        PRD §3.7: "Releasing a hold has three gates, evaluated in the §2.10
        order: the releasing `X-User-ID` must differ from `opened_by_user_id`, or
        the release is refused with `ERR_SEGREGATION_OF_DUTIES`; the
        prescription's `status` must be `VERIFIED_ACTIVE`, or the release is
        refused with `ERR_PRESCRIPTION_NOT_VERIFIED`; and no prescriber dispute
        on the same prescription may be in `OPEN` status, or the release is
        refused with `ERR_OPEN_DISPUTE_BLOCKS_RELEASE`."

        PRD §3.7: "A release records `released_by_user_id`, appends a
        `HOLD_RELEASED` compliance event, and recomputes the customer's
        `open_hold_count` and `auto_reorder_enabled`."

        PRD §2.7: "`open_hold_count` is the number of that customer's reorder
        holds whose `status` is `OPEN`."

        Design: Corner/validations/hold_release_by_a_second_officer_succeeds_when_no_dispute_is_open
        """
        scenario = setup_verified_prescription(clock=DEFAULT_CLOCK_UTC)
        customer_id = scenario["customer"]["id"]
        prescription_id = scenario["prescription"]["id"]
        assert scenario["prescription"]["status"] == "VERIFIED_ACTIVE"

        hold = new_reorder_hold(
            customer_id, prescription_id, actor=CO_ALPHA, reason="MANUAL"
        )
        assert hold["opened_by_user_id"] == CO_ALPHA

        released = validate_success(
            api.release_reorder_hold(
                hold["id"],
                {"note": "documentation received"},
                make_compliance_headers(CO_BRAVO),
            )
        )
        assert_reorder_hold(released)
        assert released["status"] == "RELEASED"
        assert released["opened_by_user_id"] == CO_ALPHA
        assert released["released_by_user_id"] == CO_BRAVO

        ledger = validate_success(
            api.get_customer_ledger(customer_id, make_customer_headers(customer_id))
        )
        assert_ledger_values(ledger, open_hold_count=0)

        _, open_meta = validate_paginated(
            api.list_reorder_holds(
                CO_ALPHA_HEADERS,
                params={"customer_id": customer_id, "status": "OPEN"},
            )
        )
        assert open_meta["total_count"] == 0

        events, _ = validate_paginated(
            api.list_compliance_events_for_prescription(
                prescription_id, CO_ALPHA_HEADERS
            )
        )
        release_events = [
            event for event in events if event["event_type"] == "HOLD_RELEASED"
        ]
        assert len(release_events) == 1, (
            "a release must append exactly one HOLD_RELEASED compliance event"
        )
        assert_compliance_event(release_events[0])
