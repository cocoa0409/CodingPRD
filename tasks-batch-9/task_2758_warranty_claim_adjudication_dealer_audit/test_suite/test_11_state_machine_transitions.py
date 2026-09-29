"""State transitions: the opening states of the audit and the parts-return obligation,
the refusals that guard every edge, and the cross-entity side effects that a legitimate
transition fires on the dealer, the claim and the claim's edits."""

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    adjudicate_claim_payload,
    analyze_parts_return_payload,
    api_client,
    approve_claim,
    assert_date_equals,
    create_audit_payload,
    create_rate_request,
    decide_goodwill_authorization_payload,
    decide_labor_rate_request_payload,
    deny_claim,
    get_audit,
    get_claim,
    get_dealer,
    get_parts_return,
    list_claim_edits,
    parts_return_for_claim,
    pay_claim,
    raise_goodwill,
    resubmit_claim_payload,
    review_rate_request,
    schedule_audit,
    set_clock,
    setup_claim,
    setup_reference_data,
    start_audit,
    validate_error,
    validate_paginated,
    validate_success,
    void_claim,
    void_claim_payload,
)

ADMIN = TEST_USERS["warranty_admin_headers"]
ADJUDICATOR = TEST_USERS["claim_adjudicator_headers"]
ADJUDICATOR_ALT = TEST_USERS["claim_adjudicator_alt_headers"]
MANAGER = TEST_USERS["adjudication_manager_headers"]
FIELD_AUDITOR = TEST_USERS["field_auditor_headers"]
AUDIT_MANAGER = TEST_USERS["audit_manager_headers"]

CA_PROFILE = {
    "state_code": "CA",
    "markup_cap_pct": 0.30,
    "labor_rate_method": "RETAIL_SAMPLE",
    "min_sample_repair_orders": 5,
    "max_labor_rate_cents": 19500,
    "deemed_approved_days": 30,
    "appeal_window_days": 30,
}

D1_TERMS = {
    "dealer_code": "D1",
    "name": "Dealer One",
    "vehicles_in_operation": 100,
    "initial_labor_rate_cents": 13750,
    "initial_parts_markup_pct": 0.40,
}

COVERED_VEHICLE = {
    "vin": "VIN00000000000001",
    "model_year": 2024,
    "warranty_start_date": "2024-01-15",
    "in_service_odometer": 0,
    "basic_months": 36,
    "basic_miles": 36000,
    "powertrain_months": 60,
    "powertrain_miles": 60000,
}

BRAKE_OPERATION = {
    "op_code": "A1234-56",
    "description": "Front brake pad replacement",
    "standard_time_hours": 1.5,
    "max_time_hours": 2.5,
    "category": "BASIC",
    "requires_causal_part": True,
    "causal_failure_group": "BRAKE_FRONT",
    "overlap_group": "BRAKE_FRONT",
}

BRAKE_PART = {
    "part_number": "BRK-PAD-9931",
    "description": "Front brake pad set",
    "dealer_net_cents": 24799,
    "failure_group": "BRAKE_FRONT",
    "return_required": True,
    "retention_days": 30,
}

BRAKE_CLAIM = {
    "repair_order_number": "RO-1001",
    "repair_date": "2026-04-10",
    "odometer_at_repair": 20000,
    "claimed_labor_hours": 1.5,
    "claimed_parts_qty": 3,
    "complaint_text": "Customer reports brake squeal at low speed.",
    "cause_text": "Front brake pads worn beyond specification.",
    "correction_text": "Replaced front brake pads and verified normal braking.",
}

AUDIT_DEALER_TERMS = {
    "dealer_code": "DA",
    "name": "Audit Motors",
    "vehicles_in_operation": 100,
    "initial_labor_rate_cents": 10000,
    "initial_parts_markup_pct": 0.25,
}

AUDIT_VEHICLE = {
    "vin": "VIN0000000000AUD1",
    "model_year": 2025,
    "warranty_start_date": "2025-01-15",
    "in_service_odometer": 0,
    "basic_months": 36,
    "basic_miles": 36000,
    "powertrain_months": 60,
    "powertrain_miles": 60000,
}

AUDIT_OPERATION = {
    "op_code": "AUD-100",
    "description": "Instrument cluster diagnosis and repair",
    "standard_time_hours": 3.0,
    "max_time_hours": 4.0,
    "category": "BASIC",
    "requires_causal_part": False,
    "causal_failure_group": None,
    "overlap_group": "AUDIT_OPS",
}

AUDIT_CLAIM = {
    "repair_order_number": "RO-AUD-1",
    "repair_date": "2026-02-15",
    "odometer_at_repair": 20000,
    "claimed_labor_hours": 2.0,
    "claimed_parts_qty": 0,
    "complaint_text": "Customer reports intermittent fault on delivery.",
    "cause_text": "Component failed internal leak test at the dealership.",
    "correction_text": "Replaced the failed component and road tested the vehicle.",
}

AUDIT_TERMS = {
    "period_start": "2026-01-01",
    "period_end": "2026-04-01",
    "sample_size": 1,
    "lead_auditor_user_id": "auditor-lead-1",
}

GW_DEALER_TERMS = {
    "dealer_code": "D-GW",
    "name": "Goodwill Motors",
    "vehicles_in_operation": 100,
    "initial_labor_rate_cents": 10000,
    "initial_parts_markup_pct": 0.25,
}

GW_VEHICLE = {
    "vin": "VIN00000000000GW1",
    "model_year": 2023,
    "warranty_start_date": "2023-06-15",
    "in_service_odometer": 0,
    "basic_months": 36,
    "basic_miles": 36000,
    "powertrain_months": 60,
    "powertrain_miles": 60000,
}

GW_OPERATION = {
    "op_code": "GW-200",
    "description": "Cabin HVAC blower replacement",
    "standard_time_hours": 1.0,
    "max_time_hours": 1.5,
    "category": "BASIC",
    "requires_causal_part": True,
    "causal_failure_group": "HVAC",
    "overlap_group": "HVAC",
}

GW_PART = {
    "part_number": "GW-P1",
    "description": "HVAC blower motor",
    "dealer_net_cents": 40000,
    "failure_group": "HVAC",
    "return_required": True,
    "retention_days": 30,
}

GW_CLAIM = {
    "repair_order_number": "RO-GW-1",
    "repair_date": "2026-05-14",
    "odometer_at_repair": 39600,
    "claimed_labor_hours": 1.0,
    "claimed_parts_qty": 1,
    "complaint_text": "Customer reports intermittent fault on delivery.",
    "cause_text": "Component failed internal leak test at the dealership.",
    "correction_text": "Replaced the failed component and road tested the vehicle.",
}


def build_brake_claim_world():
    """CA statute, dealer D1, claim RO-1001 submitted with one open parts-return."""
    set_clock("2026-05-01T00:00:00Z")
    world = setup_claim(
        profile_overrides=CA_PROFILE,
        dealer_overrides=D1_TERMS,
        vehicle_overrides=COVERED_VEHICLE,
        operation_overrides=BRAKE_OPERATION,
        part_overrides=BRAKE_PART,
        claim_overrides=BRAKE_CLAIM,
    )
    assert world["claim"]["status"] == "SUBMITTED"
    return world


def build_paid_claim_dealer_world():
    """Dealer DA with its single claim RO-AUD-1 approved at 20000 cents and paid."""
    set_clock("2026-05-01T00:00:00Z")
    world = setup_claim(
        profile_overrides=CA_PROFILE,
        dealer_overrides=AUDIT_DEALER_TERMS,
        vehicle_overrides=AUDIT_VEHICLE,
        operation_overrides=AUDIT_OPERATION,
        with_part=False,
        claim_overrides=AUDIT_CLAIM,
    )
    approve_claim(world["claim"]["id"], approved_labor_hours=2.0, approved_parts_qty=0)
    world["claim"] = pay_claim(world["claim"]["id"])
    assert world["claim"]["approved_total_cents"] == 20000
    assert world["claim"]["payment_status"] == "PAID"
    return world


def build_pending_goodwill_world():
    """Claim RO-GW-1 sits SUSPENDED with coverage NONE, and adj-user-1 has raised a
    40000-cent goodwill request that is inside the adjudicator's own authority."""
    set_clock("2026-05-20T00:00:00Z")
    world = setup_claim(
        profile_overrides=CA_PROFILE,
        dealer_overrides=GW_DEALER_TERMS,
        vehicle_overrides=GW_VEHICLE,
        operation_overrides=GW_OPERATION,
        part_overrides=GW_PART,
        claim_overrides=GW_CLAIM,
    )
    claim = world["claim"]
    assert claim["coverage_type"] == "NONE"
    assert claim["status"] == "SUSPENDED"
    world["authorization"] = raise_goodwill(
        claim,
        requested_amount_cents=40000,
        policy_adjustment_pct=0.25,
        justification="Long-standing customer just outside the mileage limit.",
    )
    return world


def build_rate_petition_world(effective_date):
    """Dealer D1 has petitioned for 17600 cents an hour and a 0.30 markup, citing six
    customer-pay repair orders with a 17600-cent median."""
    set_clock("2026-05-01T00:00:00Z")
    world = setup_reference_data(
        profile_overrides=CA_PROFILE,
        dealer_overrides=D1_TERMS,
        vehicle_overrides=COVERED_VEHICLE,
        operation_overrides=BRAKE_OPERATION,
        part_overrides=BRAKE_PART,
    )
    world["request"] = create_rate_request(
        world["dealer"],
        headers=world["dealer_headers"],
        requested_labor_rate_cents=17600,
        requested_parts_markup_pct=0.30,
        sample_repair_order_count=6,
        sample_median_rate_cents=17600,
        effective_date=effective_date,
    )
    assert world["request"]["status"] == "SUBMITTED"
    return world


class TestDealerAuditLifecycleStates:
    def test_01_a_scheduled_audit_opens_with_every_snapshot_at_zero(self):
        """PRD §3.8: "A scheduled audit opens in `SCHEDULED` with `sample_paid_snapshot_cents`, `population_paid_snapshot_cents`, `sample_chargeback_cents`, `extrapolated_chargeback_cents` and `total_chargeback_cents` all at 0, with `error_rate` and `extrapolation_factor` at zero, and with `findings_issued_at` and `appeal_deadline` both null; the dealer's `version` advances by 1."
        PRD §3.8: "Going on site sets the dealer's `audit_hold` to true and advances the dealer's `version` by 1, alongside the audit's own."
        PRD §3.8: "`audit_hold` is true exactly while at least one audit of that dealer sits in `IN_FIELD`, `FINDINGS_ISSUED` or `APPEALED`, and as §3.6 explained it freezes payment of that dealer's claims for the duration."
        PRD §4: "Endpoints that create a resource return HTTP 201 on success; every other successful call returns HTTP 200, including the state-transition endpoints, the sweep endpoints and the computed reads."

        Design: Corner/state_machines/audit_initial_state_scheduled_with_zero_snapshots
        """
        world = build_paid_claim_dealer_world()
        dealer_before = get_dealer(world["dealer"]["id"])

        response = api_client.create_audit(
            create_audit_payload(
                dealer_id=world["dealer"]["id"],
                expected_dealer_version=dealer_before["version"],
                **AUDIT_TERMS,
            ),
            AUDIT_MANAGER,
        )
        audit = validate_success(response, 201)

        assert audit["status"] == "SCHEDULED"
        assert audit["sample_paid_snapshot_cents"] == 0
        assert audit["population_paid_snapshot_cents"] == 0
        assert audit["sample_chargeback_cents"] == 0
        assert audit["extrapolated_chargeback_cents"] == 0
        assert audit["total_chargeback_cents"] == 0
        assert audit["error_rate"] == pytest.approx(0.0, abs=0.00001)
        assert audit["extrapolation_factor"] == pytest.approx(0.0, abs=0.00001)
        assert audit["findings_issued_at"] is None
        assert audit["appeal_deadline"] is None
        assert audit["lead_auditor_user_id"] == "auditor-lead-1"
        assert audit["version"] == 1

        dealer_after = get_dealer(world["dealer"]["id"])
        assert dealer_after["version"] == dealer_before["version"] + 1
        # The hold belongs to the on-site edge, not to scheduling.
        assert dealer_after["audit_hold"] is False

    def test_02_starting_an_audit_that_is_already_in_field_is_refused(self):
        """PRD §3.8: "The lead auditor going on site moves the audit `SCHEDULED → IN_FIELD`, and any other starting state is `ERR_AUDIT_INVALID_STATE`."
        PRD §3.8: "Going on site sets the dealer's `audit_hold` to true and advances the dealer's `version` by 1, alongside the audit's own."

        Design: Corner/state_machines/audit_start_twice_returns_audit_invalid_state
        """
        world = build_paid_claim_dealer_world()
        audit = schedule_audit(get_dealer(world["dealer"]["id"]), **AUDIT_TERMS)
        started = start_audit(audit["id"])
        assert started["status"] == "IN_FIELD"
        dealer_after_start = get_dealer(world["dealer"]["id"])
        assert dealer_after_start["audit_hold"] is True

        validate_error(
            api_client.start_audit(audit["id"], FIELD_AUDITOR),
            ApiErrorId.ERR_AUDIT_INVALID_STATE.value,
            409,
        )

        unchanged = get_audit(audit["id"])
        assert unchanged["status"] == "IN_FIELD"
        # Creation minted version 1 and the successful start advanced it to 2; the
        # refused start wrote nothing.
        assert unchanged["version"] == 2

        dealer_now = get_dealer(world["dealer"]["id"])
        assert dealer_now["audit_hold"] is True
        assert dealer_now["version"] == dealer_after_start["version"]


class TestPartsReturnObligationStates:
    def test_03_analysis_before_receipt_is_refused_and_writes_nothing(self):
        """PRD §3.7: "The obligation must be in `RECEIVED`, or the request is `ERR_PARTS_RETURN_INVALID_STATE`, and `analysis_result` must be present."
        PRD §3.7: "A `WarrantyAdmin` supplies an `analysis_result` — one of `DEFECT_CONFIRMED`, `NO_DEFECT_FOUND` or `NOT_AVAILABLE` — together with a free-text `analysis_note`, and both are recorded as the obligation moves `RECEIVED → ANALYZED`."
        PRD §3.7: "The obligation opens in `REQUESTED` with a `due_date` derived from its own creation instant and the part's retention window, with `received_date`, `analysis_result` and `analysis_note` all null, and with `debit_amount_cents` and `reversed_amount_cents` both at 0."

        Design: Corner/state_machines/parts_return_analysis_before_receive_returns_invalid_state
        """
        world = build_brake_claim_world()
        obligation = parts_return_for_claim(world["claim"]["id"])
        assert obligation["status"] == "REQUESTED"

        validate_error(
            api_client.analyze_parts_return(
                obligation["id"],
                analyze_parts_return_payload(
                    analysis_result="DEFECT_CONFIRMED",
                    analysis_note="Bench test confirms the internal leak.",
                ),
                ADMIN,
            ),
            ApiErrorId.ERR_PARTS_RETURN_INVALID_STATE.value,
            409,
        )

        unchanged = get_parts_return(obligation["id"])
        assert unchanged["status"] == "REQUESTED"
        assert unchanged["analysis_result"] is None
        assert unchanged["analysis_note"] is None
        assert unchanged["received_date"] is None
        assert unchanged["debit_amount_cents"] == 0
        assert unchanged["version"] == 1

        dealer = get_dealer(world["dealer"]["id"])
        assert dealer["open_parts_return_count"] == 1
        assert dealer["chargeback_balance_cents"] == 0


class TestWarrantyClaimStatusStates:
    def test_04_a_void_claim_refuses_every_status_action_with_its_own_code(self):
        """PRD §3.6: "A claim already in `DENIED` or `VOID`, or an approved claim whose payment status has left `UNPAID`, is refused with `ERR_CLAIM_NOT_VOIDABLE`."
        PRD §3.6: "Voiding stamps `resolved_at` on every open edit, sets `suspend_edit_count` to 0, advances the claim's `version` by 1, and runs the same parts-return waiver as denial — every `REQUESTED` obligation becomes `WAIVED`, the dealer's `open_parts_return_count` drops by one per waived row, and the dealer's `version` advances by 1."
        PRD §3.6: "The claim's `status` must be `SUBMITTED` or `SUSPENDED`; anything else is `ERR_CLAIM_NOT_ADJUDICABLE`."
        PRD §3.4: "Correction requires the claim to be in `SUSPENDED` and its `payment_status` to be `UNPAID`; a claim in any other `status` is refused with `ERR_CLAIM_NOT_RESUBMITTABLE`."
        PRD §3.6: "The claim's `status` must be `APPROVED` and its `payment_status` must be `UNPAID`, or the request is refused with `ERR_CLAIM_NOT_PAYABLE`; its `suspend_edit_count` must be 0."
        PRD §3.6: "It requires a `void_reason`, which is recorded on the claim, and is available to a `WarrantyAdmin` or a `ClaimAdjudicator`."

        Design: Corner/state_machines/void_claim_cannot_be_adjudicated_terminal_lockdown
        """
        world = build_brake_claim_world()
        claim_id = world["claim"]["id"]
        voided = void_claim(claim_id, void_reason="Repair order withdrawn by the dealer.")
        assert voided["status"] == "VOID"
        assert voided["version"] == 2

        validate_error(
            api_client.adjudicate_claim(
                claim_id,
                adjudicate_claim_payload(
                    decision="APPROVE", approved_labor_hours=1.5, approved_parts_qty=3
                ),
                ADJUDICATOR,
            ),
            ApiErrorId.ERR_CLAIM_NOT_ADJUDICABLE.value,
            409,
        )
        validate_error(
            api_client.resubmit_claim(
                claim_id,
                resubmit_claim_payload(
                    claimed_labor_hours=1.5,
                    claimed_parts_qty=3,
                    complaint_text=BRAKE_CLAIM["complaint_text"],
                    cause_text=BRAKE_CLAIM["cause_text"],
                    correction_text=BRAKE_CLAIM["correction_text"],
                ),
                world["dealer_headers"],
            ),
            ApiErrorId.ERR_CLAIM_NOT_RESUBMITTABLE.value,
            409,
        )
        validate_error(
            api_client.pay_claim(claim_id, ADMIN),
            ApiErrorId.ERR_CLAIM_NOT_PAYABLE.value,
            409,
        )
        validate_error(
            api_client.void_claim(
                claim_id, void_claim_payload(void_reason="Second void attempt."), ADMIN
            ),
            ApiErrorId.ERR_CLAIM_NOT_VOIDABLE.value,
            409,
        )

        final = get_claim(claim_id)
        assert final["status"] == "VOID"
        assert final["payment_status"] == "UNPAID"
        assert final["version"] == 2
        assert final["void_reason"] == "Repair order withdrawn by the dealer."

    def test_05_paying_a_submitted_claim_is_refused_although_it_is_unpaid(self):
        """PRD §3.6: "The claim's `status` must be `APPROVED` and its `payment_status` must be `UNPAID`, or the request is refused with `ERR_CLAIM_NOT_PAYABLE`; its `suspend_edit_count` must be 0."
        PRD §3.6: "A successful payment moves `payment_status` from `UNPAID` to `PAID`, leaves `status` untouched at `APPROVED`, and advances the claim's `version` by 1."
        PRD §3.3: "A newly created claim opens with `version` at 1, with `payment_status` at `UNPAID`, and with `status` at either `SUBMITTED` or `SUSPENDED` depending on what the edit engine finds."

        Design: Corner/state_machines/claim_pay_from_submitted_status_precondition_rejected
        """
        world = build_brake_claim_world()
        claim_id = world["claim"]["id"]
        assert world["claim"]["payment_status"] == "UNPAID"

        validate_error(
            api_client.pay_claim(claim_id, ADMIN),
            ApiErrorId.ERR_CLAIM_NOT_PAYABLE.value,
            409,
        )

        unchanged = get_claim(claim_id)
        assert unchanged["status"] == "SUBMITTED"
        assert unchanged["payment_status"] == "UNPAID"
        assert unchanged["version"] == 1

    def test_06_denial_waives_the_open_parts_return_without_moving_money(self):
        """PRD §3.6: "Denial requires a present, non-empty `denial_reason`, which is recorded as the claim moves `SUBMITTED → DENIED` or `SUSPENDED → DENIED`."
        PRD §3.6: "Denial also stamps `resolved_at` on every open edit, sets `suspend_edit_count` to 0, advances the claim's `version` by 1, and cascades onto the parts-return program: every parts-return obligation of this claim still in `REQUESTED` moves to `WAIVED`, and the dealer's `open_parts_return_count` is decremented by one for each waived row."
        PRD §2.8: "A dealer's `chargeback_balance_cents` is *defined* as the signed sum of `amount_cents` over every ledger row naming that dealer, and this equality is an invariant that must hold at every observable instant."
        PRD §2.8: "Below 900 dollars the dealer is `ACTIVE`."

        Design: Corner/state_machines/claim_deny_waives_open_parts_return_valid_transition
        """
        world = build_brake_claim_world()
        assert get_dealer(world["dealer"]["id"])["open_parts_return_count"] == 1

        denied = deny_claim(
            world["claim"]["id"],
            denial_reason="Repair is not attributable to a covered defect.",
        )

        assert denied["status"] == "DENIED"
        assert denied["denial_reason"] == "Repair is not attributable to a covered defect."
        assert denied["suspend_edit_count"] == 0
        assert denied["payment_status"] == "UNPAID"
        assert denied["version"] == 2

        obligation = parts_return_for_claim(world["claim"]["id"])
        assert obligation["status"] == "WAIVED"
        assert obligation["debit_amount_cents"] == 0

        dealer = get_dealer(world["dealer"]["id"])
        assert dealer["open_parts_return_count"] == 0
        assert dealer["chargeback_balance_cents"] == 0
        assert dealer["status"] == "ACTIVE"

        rows, meta = validate_paginated(
            api_client.list_dealer_ledger_entries(
                dealer["id"], ADMIN, params={"limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 0
        assert rows == []


class TestLaborRatePetitionStates:
    def test_07_approving_a_petition_republishes_the_rate_onto_the_dealer(self):
        """PRD §3.2: "Approval moves the request to `APPROVED`, writes both granted figures onto the request, then republishes them onto the dealer: the dealer's `approved_labor_rate_cents` and `approved_parts_markup_pct` are overwritten with the granted values and its `labor_rate_effective_date` is set to the request's `effective_date`, with the dealer's `updated_at` refreshed and its `version` advanced by 1."
        PRD §3.2: "The request's own `version` advances by 1 as well."
        PRD §3.2: "The ceiling itself is written into `statutory_ceiling_cents` at creation and never recomputed thereafter."
        PRD §3.2: "Under the retail-sample method the server first works out a step-up floor by taking the dealer's currently approved hourly rate, increasing it by twenty-five percent, and rounding the product half up to whole cents; it then takes the greater of the cited sample median and that step-up floor; and it finally takes the lesser of that result and the statute's absolute `max_labor_rate_cents`."
        PRD §3.2: "An `action` of `START_REVIEW` moves the petition `SUBMITTED → UNDER_REVIEW` and requires it to be in `SUBMITTED`; an `action` of `RETURN_FOR_INFO` bounces it back `UNDER_REVIEW → SUBMITTED` and requires it to be in `UNDER_REVIEW`."
        PRD §3.2: "The request opens in `SUBMITTED` with `deemed_approved` false, and the petitioning dealer's `version` advances by 1."

        Design: Corner/state_machines/labor_rate_decision_approve_writes_dealer_rate_side_effects
        """
        world = build_rate_petition_world("2026-06-01")
        request_id = world["request"]["id"]
        # round_half_up(13750 * 1.25) = 17188, max(17600, 17188) = 17600, min(19500, 17600).
        assert world["request"]["statutory_ceiling_cents"] == 17600

        under_review = review_rate_request(request_id, action="START_REVIEW")
        assert under_review["status"] == "UNDER_REVIEW"
        dealer_before = get_dealer(world["dealer"]["id"])

        decided = validate_success(
            api_client.decide_labor_rate_request(
                request_id,
                decide_labor_rate_request_payload(
                    action="APPROVE",
                    approved_labor_rate_cents=17600,
                    approved_parts_markup_pct=0.30,
                ),
                MANAGER,
            ),
            200,
        )

        assert decided["status"] == "APPROVED"
        assert decided["statutory_ceiling_cents"] == 17600
        assert decided["approved_labor_rate_cents"] == 17600
        assert decided["approved_parts_markup_pct"] == pytest.approx(0.30, abs=0.001)
        assert decided["deemed_approved"] is False
        assert decided["denial_reason"] is None
        # Creation minted version 1, START_REVIEW made it 2, the decision makes it 3.
        assert decided["version"] == 3

        dealer = get_dealer(world["dealer"]["id"])
        assert dealer["approved_labor_rate_cents"] == 17600
        assert dealer["approved_parts_markup_pct"] == pytest.approx(0.30, abs=0.001)
        assert_date_equals(
            dealer["labor_rate_effective_date"], "2026-06-01", "labor_rate_effective_date"
        )
        # Enrollment minted version 1 and filing the petition made it 2, so the
        # cross-entity write of the approval leaves the dealer at 3.
        assert dealer["version"] == dealer_before["version"] + 1
        assert dealer["version"] == 3

    def test_08_the_deemed_approval_sweep_promotes_the_untouched_petition(self):
        """PRD §3.2: "A `WarrantyAdmin` triggers the deemed-approval sweep, which walks every request still in `SUBMITTED` whose `created_at` is at or beyond the governing statute's `deemed_approved_days` before the logical clock, in ascending `created_at` order, and promotes each one `SUBMITTED → APPROVED`."
        PRD §3.2: "A swept request has `deemed_approved` set true, has its `approved_labor_rate_cents` set equal to `requested_labor_rate_cents` and its `approved_parts_markup_pct` set equal to `requested_parts_markup_pct`, and applies exactly the same dealer-side writes a manual approval would — rate, markup, effective date, dealer `version` advanced by 1 — with the request's own `version` advancing by 1."
        PRD §3.2: "The sweep reports how many rows it promoted as `promoted_count` and lists their identifiers as `promoted_request_ids`."
        PRD §2.6: "A rate request becomes eligible for deemed approval once the clock reaches its `created_at` advanced by the governing state's `deemed_approved_days` days."
        PRD §3.2: "The request opens in `SUBMITTED` with `deemed_approved` false, and the petitioning dealer's `version` advances by 1."

        Design: Corner/state_machines/deemed_approval_run_promotes_request_after_window_side_effect
        """
        world = build_rate_petition_world("2026-07-01")
        request_id = world["request"]["id"]
        dealer_before = get_dealer(world["dealer"]["id"])
        assert dealer_before["approved_labor_rate_cents"] == 13750

        # Filed at 2026-05-01 under a 30-day statute, so the petition is deemed on
        # 2026-05-31 and the clock now sits one day past that.
        set_clock("2026-06-01T00:00:00Z")
        sweep = validate_success(api_client.run_deemed_approval(ADMIN), 200)

        assert sweep["promoted_count"] == 1
        assert sweep["promoted_request_ids"] == [request_id]

        promoted = validate_success(
            api_client.get_labor_rate_request(request_id, ADMIN), 200
        )
        assert promoted["status"] == "APPROVED"
        assert promoted["deemed_approved"] is True
        assert promoted["approved_labor_rate_cents"] == 17600
        assert promoted["approved_parts_markup_pct"] == pytest.approx(0.30, abs=0.001)
        assert promoted["version"] == 2

        dealer = get_dealer(world["dealer"]["id"])
        assert dealer["approved_labor_rate_cents"] == 17600
        assert dealer["approved_parts_markup_pct"] == pytest.approx(0.30, abs=0.001)
        assert_date_equals(
            dealer["labor_rate_effective_date"], "2026-07-01", "labor_rate_effective_date"
        )
        assert dealer["version"] == dealer_before["version"] + 1
        assert dealer["version"] == 3


class TestGoodwillAuthorizationStates:
    def test_09_approving_goodwill_flips_coverage_and_lifts_the_suspension(self):
        """PRD §3.5: "Approval records `approved_amount_cents` and stamps `decided_by_user_id` with the decider's `X-User-ID`, moving the authorization to `APPROVED` and advancing its `version` by 1."
        PRD §3.5: "It then cascades onto the claim: the claim's `coverage_type` flips from `NONE` to `GOODWILL`, the claim's open `NO_COVERAGE` edit is stamped `resolved_at`, `suspend_edit_count` is recomputed from the edits that remain open, and the claim's `version` advances by 1."
        PRD §3.5: "When that recount reaches zero the claim completes the second of its two cycle edges, `SUSPENDED → SUBMITTED`, which is what makes `GOODWILL` coverage reachable at all — without it a claim with no coverage would sit suspended forever."
        PRD §3.5: "`adjudicator_limit_cents` is the lesser of the share cap and the adjudicator base authority of 50,000 cents (500 dollars) multiplied by the decay multiplier and rounded half up to whole cents."
        PRD §3.5: "`manager_limit_cents` is the lesser of the same share cap and the manager base authority of 250,000 cents (2,500 dollars) multiplied by the same decay multiplier and rounded half up to whole cents."
        PRD §3.5: "The larger of those two fractions, rounded half up to four decimal places, is `out_of_warranty_margin_pct`."
        PRD §3.5: "At or below `adjudicator_limit_cents` it opens `PENDING`."

        Design: Corner/state_machines/goodwill_approval_flips_coverage_and_releases_suspension_side_effect
        """
        world = build_pending_goodwill_world()
        authorization = world["authorization"]
        claim_id = world["claim"]["id"]

        # 3600 miles past a 36000-mile limit is a 0.1000 margin, so the decay multiplier
        # is 0.8: the share cap is 48000 and the adjudicator authority is 40000.
        assert authorization["status"] == "PENDING"
        assert authorization["out_of_warranty_margin_pct"] == pytest.approx(
            0.1000, abs=0.00001
        )
        assert authorization["adjudicator_limit_cents"] == 40000
        assert authorization["manager_limit_cents"] == 48000
        assert authorization["requested_by_user_id"] == "adj-user-1"

        approved = validate_success(
            api_client.decide_goodwill_authorization(
                authorization["id"],
                decide_goodwill_authorization_payload(
                    action="APPROVE", approved_amount_cents=40000
                ),
                ADJUDICATOR_ALT,
            ),
            200,
        )

        assert approved["status"] == "APPROVED"
        assert approved["approved_amount_cents"] == 40000
        assert approved["decided_by_user_id"] == "adj-user-2"

        claim = get_claim(claim_id)
        assert claim["coverage_type"] == "GOODWILL"
        assert claim["status"] == "SUBMITTED"
        assert claim["suspend_edit_count"] == 0
        # Submission minted version 1, raising the authorization made it 2, and the
        # approval cascade makes it 3.
        assert claim["version"] == 3

        edits = list_claim_edits(claim_id, params={"limit": 10, "offset": 0})
        no_coverage = [edit for edit in edits if edit["edit_code"] == "NO_COVERAGE"]
        assert len(no_coverage) == 1
        assert no_coverage[0]["severity"] == "SUSPEND"
        assert no_coverage[0]["resolved_at"] is not None
