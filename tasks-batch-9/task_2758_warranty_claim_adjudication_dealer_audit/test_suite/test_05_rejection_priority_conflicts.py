"""Conflicting rules on one request: the §2.11 ladder decides which one speaks."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    approve_claim,
    create_dealer,
    create_labor_operation,
    create_part,
    create_state_law_profile,
    create_vehicle,
    decide_appeal,
    decide_goodwill,
    file_appeal,
    get_audit,
    get_claim,
    get_goodwill,
    get_success_data,
    make_dealer_warranty_admin_headers,
    make_operator_headers,
    raise_goodwill,
    set_clock,
    setup_audit_with_findings,
    submit_claim,
    validate_error,
)

CA_PROFILE = {
    "state_code": "CA",
    "markup_cap_pct": 0.30,
    "labor_rate_method": "RETAIL_SAMPLE",
    "min_sample_repair_orders": 5,
    "max_labor_rate_cents": 19500,
    "deemed_approved_days": 30,
    "appeal_window_days": 30,
}

COVERED_TERMS = {
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

BRAKE_NARRATIVE = {
    "complaint_text": "Customer reports brake squeal at low speed.",
    "cause_text": "Front brake pads worn beyond specification.",
    "correction_text": "Replaced front brake pads and verified normal braking.",
}

ELEC_OPERATION = {
    "op_code": "AUD-100",
    "description": "Electrical harness repair",
    "standard_time_hours": 2.0,
    "max_time_hours": 3.0,
    "category": "BASIC",
    "requires_causal_part": True,
    "causal_failure_group": "ELEC",
    "overlap_group": "ELEC",
}

ELEC_PART = {
    "part_number": "AUD-P1",
    "description": "Electrical harness",
    "dealer_net_cents": 24000,
    "failure_group": "ELEC",
    "return_required": False,
    "retention_days": 0,
}

ELEC_NARRATIVE = {
    "complaint_text": "Customer reports intermittent electrical fault.",
    "cause_text": "Harness chafed through insulation layer.",
    "correction_text": "Replaced the electrical harness assembly.",
}

GOODWILL_PROFILE = dict(CA_PROFILE)

GOODWILL_VEHICLE = {
    "model_year": 2023,
    "warranty_start_date": "2023-06-15",
    "in_service_odometer": 0,
    "basic_months": 36,
    "basic_miles": 36000,
    "powertrain_months": 60,
    "powertrain_miles": 60000,
}

GOODWILL_OPERATION = {
    "op_code": "GW-200",
    "description": "Cabin blower motor replacement",
    "standard_time_hours": 1.0,
    "max_time_hours": 1.5,
    "category": "BASIC",
    "requires_causal_part": True,
    "causal_failure_group": "HVAC",
    "overlap_group": "HVAC",
}

GOODWILL_PART = {
    "part_number": "GW-P1",
    "description": "Cabin blower motor",
    "dealer_net_cents": 40000,
    "failure_group": "HVAC",
    "return_required": False,
    "retention_days": 0,
}

EXCESSIVE_ADJUDICATION = {
    "decision": "APPROVE",
    "approved_labor_hours": 9.0,
    "approved_parts_qty": 3,
}


def build_approved_and_submitted_claims():
    """One APPROVED claim and one SUBMITTED claim under the same 2.5-hour ceiling."""
    set_clock("2026-05-01T00:00:00Z")
    profile = create_state_law_profile(**CA_PROFILE)
    dealer = create_dealer(
        profile["id"],
        dealer_code="D1",
        name="Dealer One",
        vehicles_in_operation=100,
        initial_labor_rate_cents=13750,
        initial_parts_markup_pct=0.40,
    )
    headers = make_dealer_warranty_admin_headers(dealer["id"])
    operation = create_labor_operation(**BRAKE_OPERATION)
    part = create_part(**BRAKE_PART)
    claims = []
    for ro, odo in [("RO-P1-1", 20000), ("RO-P2-1", 21000)]:
        vehicle = create_vehicle(**COVERED_TERMS)
        claims.append(
            submit_claim(
                {
                    "dealer": dealer,
                    "vehicle": vehicle,
                    "operation": operation,
                    "part": part,
                    "dealer_headers": headers,
                },
                repair_order_number=ro,
                repair_date="2026-04-10",
                odometer_at_repair=odo,
                claimed_labor_hours=1.5,
                claimed_parts_qty=3,
                **BRAKE_NARRATIVE,
            )
        )
    approved = approve_claim(
        claims[0]["id"], approved_labor_hours=1.5, approved_parts_qty=3
    )
    assert approved["status"] == "APPROVED"
    assert claims[1]["status"] == "SUBMITTED"
    return {"approved": approved, "submitted": claims[1]}


def build_reissued_audit():
    """An audit back in FINDINGS_ISSUED after a PARTIAL decision, holding one OVERTURNED finding."""
    set_clock("2026-05-01T00:00:00Z")
    specs = []
    for ro, date, odo in [
        ("RO-A1", "2026-01-05", 11000),
        ("RO-A2", "2026-02-10", 13000),
        ("RO-A3", "2026-03-20", 15000),
    ]:
        specs.append(
            {
                "claim": dict(
                    ELEC_NARRATIVE,
                    repair_order_number=ro,
                    repair_date=date,
                    odometer_at_repair=odo,
                    claimed_labor_hours=2.0,
                    claimed_parts_qty=1,
                ),
                "approve": {"approved_labor_hours": 2.0, "approved_parts_qty": 1},
                "pay": True,
            }
        )
    world = setup_audit_with_findings(
        specs,
        [
            {
                "claim_index": 0,
                "unsupported_amount_cents": 30000,
                "finding_code": "NO_REPAIR_ORDER",
                "evidence_note": "No repair order on file for this claim.",
            },
            {
                "claim_index": 1,
                "unsupported_amount_cents": 10000,
                "finding_code": "TIME_NOT_DOCUMENTED",
                "evidence_note": "Technician time is not documented on the order.",
            },
        ],
        audit_overrides={
            "period_start": "2026-01-01",
            "period_end": "2026-07-01",
            "sample_size": 2,
            "lead_auditor_user_id": "auditor-lead-1",
        },
        issue=True,
        profile_overrides=CA_PROFILE,
        dealer_overrides={
            "dealer_code": "D-AUD",
            "name": "Audit Dealer",
            "vehicles_in_operation": 100,
            "initial_labor_rate_cents": 10000,
            "initial_parts_markup_pct": 0.25,
        },
        operation_overrides=ELEC_OPERATION,
        part_overrides=ELEC_PART,
        vehicle_overrides=COVERED_TERMS,
    )
    set_clock("2026-05-10T00:00:00Z")
    world["appeal"] = file_appeal(
        world["audit"],
        [world["findings"][0]["id"], world["findings"][1]["id"]],
        world["dealer"]["id"],
        grounds="Repair orders and technician time records are on file for both claims.",
    )
    set_clock("2026-05-12T00:00:00Z")
    decide_appeal(
        world["appeal"]["id"],
        action="PARTIAL",
        overturned_finding_ids=[world["findings"][1]["id"]],
        decision_note="Technician time record produced for the second claim only.",
    )
    world["audit"] = get_audit(world["audit"]["id"])
    assert world["audit"]["status"] == "FINDINGS_ISSUED"
    return world


def build_decided_goodwill_authorization():
    """A goodwill authorization raised by adj-user-1 and already APPROVED by mgr-user-1."""
    set_clock("2026-05-20T00:00:00Z")
    profile = create_state_law_profile(**GOODWILL_PROFILE)
    dealer = create_dealer(
        profile["id"],
        dealer_code="D-GW",
        name="Goodwill Dealer",
        vehicles_in_operation=100,
        initial_labor_rate_cents=10000,
        initial_parts_markup_pct=0.25,
    )
    vehicle = create_vehicle(**GOODWILL_VEHICLE)
    operation = create_labor_operation(**GOODWILL_OPERATION)
    part = create_part(**GOODWILL_PART)
    claim = submit_claim(
        {
            "dealer": dealer,
            "vehicle": vehicle,
            "operation": operation,
            "part": part,
            "dealer_headers": make_dealer_warranty_admin_headers(dealer["id"]),
        },
        repair_order_number="RO-GW-1",
        repair_date="2026-05-14",
        odometer_at_repair=39600,
        claimed_labor_hours=1.0,
        claimed_parts_qty=1,
        complaint_text="Customer reports no airflow from the cabin vents.",
        cause_text="Cabin blower motor seized in the housing.",
        correction_text="Replaced the cabin blower motor and verified airflow.",
    )
    assert claim["coverage_type"] == "NONE"
    assert claim["provisional_total_cents"] == 60000
    authorization = raise_goodwill(
        claim,
        requested_amount_cents=48000,
        policy_adjustment_pct=0.25,
        justification="Loyal customer just outside the mileage limit.",
    )
    assert authorization["status"] == "ESCALATED"
    decided = decide_goodwill(
        authorization["id"],
        action="APPROVE",
        headers=TEST_USERS["adjudication_manager_headers"],
        approved_amount_cents=40000,
    )
    assert decided["status"] == "APPROVED"
    return {"claim": claim, "authorization": decided}


class TestStateGateOutranksLaborTimeCeiling:
    def test_15_an_already_approved_claim_reports_the_state_gate_not_the_body_check(self):
        """PRD §2.11: "Checks are evaluated in the following order, and the first one that fails determines the response; no later check is consulted."
        PRD §2.11: "State admissibility of the requested transition — `ERR_CLAIM_NOT_ADJUDICABLE`, `ERR_CLAIM_NOT_PAYABLE`, `ERR_CLAIM_NOT_VOIDABLE`, `ERR_CLAIM_NOT_RESUBMITTABLE`, `ERR_CLAIM_STILL_SUSPENDED`, `ERR_PARTS_RETURN_INVALID_STATE`, `ERR_AUDIT_INVALID_STATE`, `ERR_APPEAL_INVALID_STATE`, `ERR_GOODWILL_INVALID_STATE` or `ERR_LABOR_RATE_REQUEST_INVALID_STATE`."
        PRD §2.11: "Labor time against the operation's absolute maximum — `ERR_LABOR_TIME_EXCEEDS_MAX`."

        Design: Difficulty/priority_pair_validation_conflict/claim_state_gate_outranks_labor_time_ceiling_on_adjudicate
        """
        world = build_approved_and_submitted_claims()
        approved = world["approved"]

        response = api_client.adjudicate_claim(
            approved["id"],
            dict(EXCESSIVE_ADJUDICATION),
            TEST_USERS["claim_adjudicator_headers"],
        )

        validate_error(response, ApiErrorId.ERR_CLAIM_NOT_ADJUDICABLE.value)

        unchanged = get_claim(approved["id"])
        assert unchanged["status"] == "APPROVED"
        assert unchanged["approved_labor_amount_cents"] == 20625
        assert unchanged["approved_total_cents"] == 117342
        assert unchanged["version"] == approved["version"]

    def test_16_the_same_body_on_a_submitted_claim_reaches_the_labor_time_ceiling(self):
        """PRD §3.6: "On approval, `approved_labor_hours` is tested against the operation's `max_time_hours` exactly as claimed hours were at intake, with `ERR_LABOR_TIME_EXCEEDS_MAX` when it is strictly above."
        PRD §2.11: "Labor time against the operation's absolute maximum — `ERR_LABOR_TIME_EXCEEDS_MAX`."

        Design: Difficulty/priority_pair_validation_conflict/claim_state_gate_outranks_labor_time_ceiling_on_adjudicate
        """
        world = build_approved_and_submitted_claims()
        submitted = world["submitted"]

        response = api_client.adjudicate_claim(
            submitted["id"],
            dict(EXCESSIVE_ADJUDICATION),
            TEST_USERS["claim_adjudicator_headers"],
        )

        validate_error(response, ApiErrorId.ERR_LABOR_TIME_EXCEEDS_MAX.value)

        unchanged = get_claim(submitted["id"])
        assert unchanged["status"] == "SUBMITTED"
        assert unchanged["approved_total_cents"] is None


class TestAppealWindowOutranksFindingMembership:
    def test_17_a_late_filing_reports_the_closed_window_not_the_overturned_finding(self):
        """PRD §2.11: "Appeal window — `ERR_APPEAL_WINDOW_CLOSED`."
        PRD §2.11: "Contested findings belonging to the audit — `ERR_FINDING_NOT_IN_AUDIT`."
        PRD §3.8: "The filing must arrive while the logical clock is at or before `appeal_deadline` — the boundary instant itself is still open — and a late filing is refused with `ERR_APPEAL_WINDOW_CLOSED`."

        Design: Difficulty/priority_pair_validation_conflict/appeal_window_closure_outranks_finding_membership_check
        """
        world = build_reissued_audit()
        overturned_finding = world["findings"][1]
        audit = world["audit"]
        assert str(audit["appeal_deadline"])[:10] == "2026-06-11"

        set_clock("2026-06-12T00:00:00Z")
        response = api_client.create_appeal(
            audit["id"],
            {
                "grounds": "The technician time record covers the whole repair order.",
                "contested_finding_ids": [overturned_finding["id"]],
                "expected_audit_version": audit["version"],
            },
            make_dealer_warranty_admin_headers(world["dealer"]["id"]),
        )

        validate_error(response, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED.value)

        appeals = get_success_data(
            api_client.list_appeals(
                TEST_USERS["audit_manager_headers"], params={"audit_id": audit["id"]}
            )
        )
        assert len(appeals) == 1
        after = get_audit(audit["id"])
        assert after["status"] == "FINDINGS_ISSUED"
        assert after["version"] == audit["version"]

    def test_18_inside_the_refreshed_window_the_membership_check_speaks(self):
        """PRD §3.8: "Every identifier in `contested_finding_ids` must name a finding belonging to the audit in question and must find that finding in `CHARGED_BACK`; otherwise the filing is refused with `ERR_FINDING_NOT_IN_AUDIT`."
        PRD §2.11: "Contested findings belonging to the audit — `ERR_FINDING_NOT_IN_AUDIT`."

        Design: Difficulty/priority_pair_validation_conflict/appeal_window_closure_outranks_finding_membership_check
        """
        world = build_reissued_audit()
        overturned_finding = world["findings"][1]
        audit = world["audit"]

        set_clock("2026-06-10T00:00:00Z")
        response = api_client.create_appeal(
            audit["id"],
            {
                "grounds": "The technician time record covers the whole repair order.",
                "contested_finding_ids": [overturned_finding["id"]],
                "expected_audit_version": audit["version"],
            },
            make_dealer_warranty_admin_headers(world["dealer"]["id"]),
        )

        validate_error(response, ApiErrorId.ERR_FINDING_NOT_IN_AUDIT.value)

        appeals = get_success_data(
            api_client.list_appeals(
                TEST_USERS["audit_manager_headers"], params={"audit_id": audit["id"]}
            )
        )
        assert len(appeals) == 1
        assert get_audit(audit["id"])["status"] == "FINDINGS_ISSUED"


class TestSegregationOutranksGoodwillStateGate:
    def test_19_the_original_requester_is_refused_on_identity_before_state(self):
        """PRD §2.11: "Segregation of duties — `ERR_SEGREGATION_OF_DUTIES`."
        PRD §3.5: "The decision supplies an `action` of `APPROVE` or `DENY`, and the acting `X-User-ID` must differ from `requested_by_user_id` or the request is refused with `ERR_SEGREGATION_OF_DUTIES`."
        PRD §3.5: "Deciding an authorization requires it to be in `PENDING` or `ESCALATED`; anything else is `ERR_GOODWILL_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_outranks_goodwill_state_gate
        """
        world = build_decided_goodwill_authorization()
        authorization = world["authorization"]
        assert authorization["requested_by_user_id"] == "adj-user-1"

        response = api_client.decide_goodwill_authorization(
            authorization["id"],
            {
                "action": "DENY",
                "denial_reason": "Reconsidered after the customer withdrew the request.",
            },
            make_operator_headers("adj-user-1", "ClaimAdjudicator"),
        )

        validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

        unchanged = get_goodwill(authorization["id"])
        assert unchanged["status"] == "APPROVED"
        assert unchanged["approved_amount_cents"] == 40000
        assert unchanged["decided_by_user_id"] == "mgr-user-1"
        assert unchanged["denial_reason"] is None
        assert unchanged["version"] == authorization["version"]

    def test_20_an_uninvolved_adjudicator_reaches_the_goodwill_state_gate(self):
        """PRD §3.5: "Deciding an authorization requires it to be in `PENDING` or `ESCALATED`; anything else is `ERR_GOODWILL_INVALID_STATE`."
        PRD §3.5: "`adjudicator_limit_cents` is the lesser of the share cap and the adjudicator base authority of 50,000 cents (500 dollars) multiplied by the decay multiplier and rounded half up to whole cents."
        PRD §3.5: "`manager_limit_cents` is the lesser of the same share cap and the manager base authority of 250,000 cents (2,500 dollars) multiplied by the same decay multiplier and rounded half up to whole cents."

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_outranks_goodwill_state_gate
        """
        world = build_decided_goodwill_authorization()
        authorization = world["authorization"]
        assert authorization["adjudicator_limit_cents"] == 40000
        assert authorization["manager_limit_cents"] == 48000
        assert authorization["out_of_warranty_margin_pct"] == 0.1000

        response = api_client.decide_goodwill_authorization(
            authorization["id"],
            {
                "action": "DENY",
                "denial_reason": "Reconsidered after the customer withdrew the request.",
            },
            TEST_USERS["claim_adjudicator_alt_headers"],
        )

        validate_error(response, ApiErrorId.ERR_GOODWILL_INVALID_STATE.value)

        unchanged = get_goodwill(authorization["id"])
        assert unchanged["status"] == "APPROVED"
        assert unchanged["version"] == authorization["version"]
