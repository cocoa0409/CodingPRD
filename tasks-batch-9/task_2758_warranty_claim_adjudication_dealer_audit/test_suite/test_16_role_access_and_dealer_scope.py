"""Role authorisation, the dealer-side identity split and the segregation-of-duties guards."""
import pytest

from test_helpers import (
    OPERATORS,
    TEST_USERS,
    ApiErrorId,
    add_finding,
    adjudicate_claim_payload,
    analyze_parts_return_payload,
    api_client,
    approve_claim,
    assert_date_equals,
    assert_instant_equals,
    create_appeal_payload,
    create_audit_finding_payload,
    create_dealer,
    create_goodwill_authorization_payload,
    create_labor_rate_request_payload,
    create_rate_request,
    create_state_law_profile,
    decide_appeal_payload,
    decide_goodwill_authorization_payload,
    decide_labor_rate_request_payload,
    file_appeal,
    get_appeal,
    get_audit,
    get_claim,
    get_dealer,
    get_finding,
    get_goodwill,
    issue_findings,
    list_ledger_entries,
    make_operator_headers,
    parts_return_for_claim,
    pay_claim,
    receive_parts_return_payload,
    review_rate_request,
    schedule_audit,
    set_clock,
    setup_claim,
    start_audit,
    validate_error,
    validate_paginated,
    validate_success,
)

WARRANTY_ADMIN = TEST_USERS["warranty_admin_headers"]
ADJUDICATOR = TEST_USERS["claim_adjudicator_headers"]
ADJUDICATOR_ALT = TEST_USERS["claim_adjudicator_alt_headers"]
MANAGER = TEST_USERS["adjudication_manager_headers"]
FIELD_AUDITOR = TEST_USERS["field_auditor_headers"]
AUDIT_MANAGER = TEST_USERS["audit_manager_headers"]
APPEAL_REVIEWER = TEST_USERS["appeal_reviewer_headers"]

CA_PROFILE = {
    "state_code": "CA",
    "markup_cap_pct": 0.30,
    "labor_rate_method": "RETAIL_SAMPLE",
    "min_sample_repair_orders": 5,
    "max_labor_rate_cents": 19500,
    "deemed_approved_days": 30,
    "appeal_window_days": 30,
}

BRAKE_DEALER = {
    "dealer_code": "D1",
    "name": "Dealer One",
    "vehicles_in_operation": 100,
    "initial_labor_rate_cents": 13750,
    "initial_parts_markup_pct": 0.40,
}

BRAKE_VEHICLE = {
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

GOODWILL_DEALER = {
    "dealer_code": "DG",
    "name": "Goodwill Motors",
    "vehicles_in_operation": 100,
    "initial_labor_rate_cents": 10000,
    "initial_parts_markup_pct": 0.25,
}

GOODWILL_VEHICLE = {
    "vin": "VIN00000000000003",
    "model_year": 2023,
    "warranty_start_date": "2023-06-15",
    "in_service_odometer": 0,
    "basic_months": 36,
    "basic_miles": 36000,
    "powertrain_months": 60,
    "powertrain_miles": 60000,
}

GOODWILL_OPERATION = {
    "op_code": "HVA-200",
    "description": "Blower motor replacement",
    "standard_time_hours": 1.0,
    "max_time_hours": 1.5,
    "category": "BASIC",
    "requires_causal_part": True,
    "causal_failure_group": "HVAC",
    "overlap_group": "HVAC",
}

GOODWILL_PART = {
    "part_number": "HVA-BLW-1",
    "description": "Cabin blower motor",
    "dealer_net_cents": 40000,
    "failure_group": "HVAC",
    "return_required": False,
    "retention_days": 0,
}

GOODWILL_CLAIM = {
    "repair_order_number": "RO-GW-1",
    "repair_date": "2026-05-14",
    "odometer_at_repair": 39600,
    "claimed_labor_hours": 1.0,
    "claimed_parts_qty": 1,
    "complaint_text": "Customer reports no air flow from the cabin vents.",
    "cause_text": "Cabin blower motor seized and no longer turns.",
    "correction_text": "Replaced the cabin blower motor and verified air flow.",
}

AUDIT_DEALER = {
    "dealer_code": "DA",
    "name": "Audited Motors",
    "vehicles_in_operation": 100,
    "initial_labor_rate_cents": 10000,
    "initial_parts_markup_pct": 0.25,
}

AUDIT_VEHICLE = {
    "vin": "VIN00000000000004",
    "model_year": 2024,
    "warranty_start_date": "2024-01-15",
    "in_service_odometer": 0,
    "basic_months": 36,
    "basic_miles": 36000,
    "powertrain_months": 60,
    "powertrain_miles": 60000,
}

AUDIT_OPERATION = {
    "op_code": "AUD-100",
    "description": "Diagnostic labor only",
    "standard_time_hours": 3.0,
    "max_time_hours": 4.0,
    "category": "BASIC",
    "requires_causal_part": False,
    "causal_failure_group": None,
    "overlap_group": "DIAG",
}

AUDIT_CLAIM = {
    "repair_order_number": "RO-AUD-1",
    "repair_date": "2026-02-15",
    "odometer_at_repair": 20000,
    "claimed_labor_hours": 2.0,
    "claimed_parts_qty": 0,
    "complaint_text": "Customer reports an intermittent dash warning lamp.",
    "cause_text": "Diagnostic scan traced a transient body control fault.",
    "correction_text": "Cleared the stored fault and verified no recurrence.",
}


def build_brake_world():
    """A CA dealer with one covered brake claim, submitted clean by its own administrator."""
    set_clock("2026-05-01T00:00:00Z")
    world = setup_claim(
        profile_overrides=CA_PROFILE,
        dealer_overrides=BRAKE_DEALER,
        vehicle_overrides=BRAKE_VEHICLE,
        operation_overrides=BRAKE_OPERATION,
        part_overrides=BRAKE_PART,
        claim_overrides=BRAKE_CLAIM,
    )
    assert world["claim"]["coverage_type"] == "BASIC"
    assert world["claim"]["status"] == "SUBMITTED"
    assert world["claim"]["provisional_total_cents"] == 124782
    return world


def build_goodwill_world():
    """A claim 3,600 miles past its basic mileage limit, so coverage lands on NONE."""
    set_clock("2026-05-20T00:00:00Z")
    world = setup_claim(
        profile_overrides=CA_PROFILE,
        dealer_overrides=GOODWILL_DEALER,
        vehicle_overrides=GOODWILL_VEHICLE,
        operation_overrides=GOODWILL_OPERATION,
        part_overrides=GOODWILL_PART,
        claim_overrides=GOODWILL_CLAIM,
    )
    assert world["claim"]["coverage_type"] == "NONE"
    assert world["claim"]["status"] == "SUSPENDED"
    assert world["claim"]["provisional_total_cents"] == 60000
    return world


def build_scheduled_audit_world():
    """One paid 20000-cent claim inside a quarterly audit period, with the audit scheduled."""
    set_clock("2026-05-01T00:00:00Z")
    world = setup_claim(
        profile_overrides=CA_PROFILE,
        dealer_overrides=AUDIT_DEALER,
        vehicle_overrides=AUDIT_VEHICLE,
        operation_overrides=AUDIT_OPERATION,
        with_part=False,
        claim_overrides=AUDIT_CLAIM,
    )
    world["claim"] = approve_claim(
        world["claim"]["id"], approved_labor_hours=2.0, approved_parts_qty=0
    )
    assert world["claim"]["approved_total_cents"] == 20000
    world["claim"] = pay_claim(world["claim"]["id"])
    assert world["claim"]["payment_status"] == "PAID"
    world["audit"] = schedule_audit(
        get_dealer(world["dealer"]["id"]),
        period_start="2026-01-01",
        period_end="2026-04-01",
        sample_size=1,
    )
    assert world["audit"]["status"] == "SCHEDULED"
    return world


def build_in_field_audit_world():
    """The scheduled audit with the auditor on site and one unsupported-claim finding."""
    world = build_scheduled_audit_world()
    world["audit"] = start_audit(world["audit"]["id"])
    world["finding"] = add_finding(
        world["audit"]["id"],
        world["claim"]["id"],
        10000,
        finding_code="TIME_NOT_DOCUMENTED",
        evidence_note="Repair order records no documented technician time.",
    )
    return world


def build_issued_audit_world():
    """The audit with its findings issued, so the 10000-cent chargeback has landed."""
    world = build_in_field_audit_world()
    world["audit"] = issue_findings(world["audit"]["id"])
    assert world["audit"]["status"] == "FINDINGS_ISSUED"
    assert world["audit"]["total_chargeback_cents"] == 10000
    return world


class TestManufacturerAndDealerSideOperations:
    def test_01_dealer_administrator_reads_its_own_records_and_petitions_for_a_rate(self):
        """PRD §2.1: "A `DealerWarrantyAdmin` is a dealership-side administrator who submits, corrects and appeals on behalf of one dealership."
        PRD §2.1: "Dealer scoping is enforced on ten operations: reading one dealer, listing that dealer's ledger entries, reading that dealer's expense analytics, submitting a claim, reading one claim, resubmitting a claim, listing a claim's edits, reading one audit, filing an appeal against an audit, and reading one appeal."
        PRD §3.9: "The response also echoes `dealer_id`, the resolved `window_start` and `window_end`, and `vehicles_in_operation`, so a reader can see exactly which window and which denominator produced the figures."
        PRD §3.2: "Under the retail-sample method the server first works out a step-up floor by taking the dealer's currently approved hourly rate, increasing it by twenty-five percent, and rounding the product half up to whole cents; it then takes the greater of the cited sample median and that step-up floor; and it finally takes the lesser of that result and the statute's absolute `max_labor_rate_cents`."
        PRD §3.2: "The request opens in `SUBMITTED` with `deemed_approved` false, and the petitioning dealer's `version` advances by 1."

        Design: Corner/rbac/warranty_admin_and_dealer_admin_positive_operations
        """
        world = build_brake_world()
        dealer_headers = world["dealer_headers"]
        dealer_id = world["dealer"]["id"]
        claim_id = world["claim"]["id"]

        dealer = validate_success(api_client.get_dealer(dealer_id, dealer_headers))
        assert dealer["id"] == dealer_id
        assert dealer["status"] == "ACTIVE"
        assert dealer["chargeback_balance_cents"] == 0

        entries, _ = validate_paginated(
            api_client.list_dealer_ledger_entries(dealer_id, dealer_headers)
        )
        assert entries == []

        edits, _ = validate_paginated(
            api_client.list_claim_edits(claim_id, dealer_headers)
        )
        assert edits == []
        assert world["claim"]["suspend_edit_count"] == 0

        report = validate_success(
            api_client.get_dealer_expense_analytics(dealer_id, dealer_headers)
        )
        assert report["dealer_id"] == dealer_id
        assert report["vehicles_in_operation"] == 100

        petition = validate_success(
            api_client.create_labor_rate_request(
                create_labor_rate_request_payload(
                    dealer_id=dealer_id,
                    requested_labor_rate_cents=17600,
                    requested_parts_markup_pct=0.30,
                    sample_repair_order_count=6,
                    sample_median_rate_cents=17600,
                    effective_date="2026-06-01",
                    expected_dealer_version=dealer["version"],
                ),
                dealer_headers,
            ),
            201,
        )
        # The 13750 rate steps up to 17188, the cited median of 17600 is the greater of
        # the two, and 19500 does not bind: the ceiling is exactly the requested rate.
        assert petition["statutory_ceiling_cents"] == 17600
        assert petition["status"] == "SUBMITTED"
        assert petition["deemed_approved"] is False
        assert petition["state_law_profile_id"] == world["profile"]["id"]

        after = validate_success(api_client.get_dealer(dealer_id, dealer_headers))
        assert after["version"] == dealer["version"] + 1

    def test_02_warranty_admin_pays_the_claim_and_runs_the_parts_return_program(self):
        """PRD §2.1: "A `WarrantyAdmin` is the manufacturer's warranty program administrator: it publishes all reference data, drives the parts-return program, runs the deemed-approval and non-return sweeps, and pays approved claims."
        PRD §3.6: "A successful payment moves `payment_status` from `UNPAID` to `PAID`, leaves `status` untouched at `APPROVED`, and advances the claim's `version` by 1."
        PRD §3.7: "A timely receipt moves `REQUESTED → RECEIVED`, stamps `received_date`, decrements the dealer's `open_parts_return_count` by 1, advances the dealer's `version` by 1, and advances the obligation's `version` by 1."
        PRD §3.7: "`DEFECT_CONFIRMED` is the honest outcome and no money moves: `debit_amount_cents` stays 0."

        Design: Corner/rbac/warranty_admin_and_dealer_admin_positive_operations
        """
        world = build_brake_world()
        dealer_id = world["dealer"]["id"]
        claim_id = world["claim"]["id"]
        assert get_dealer(dealer_id)["open_parts_return_count"] == 1

        approved = approve_claim(claim_id, approved_labor_hours=1.5, approved_parts_qty=3)
        assert approved["approved_total_cents"] == 117342
        assert approved["oem_payable_cents"] == 117342

        paid = validate_success(api_client.pay_claim(claim_id, WARRANTY_ADMIN))
        assert paid["status"] == "APPROVED"
        assert paid["payment_status"] == "PAID"
        assert paid["version"] == approved["version"] + 1

        obligation = parts_return_for_claim(claim_id)
        assert obligation["status"] == "REQUESTED"

        received = validate_success(
            api_client.receive_parts_return(
                obligation["id"],
                receive_parts_return_payload(received_date="2026-05-01"),
                WARRANTY_ADMIN,
            )
        )
        assert received["status"] == "RECEIVED"
        assert_date_equals(received["received_date"], "2026-05-01")
        assert get_dealer(dealer_id)["open_parts_return_count"] == 0

        analyzed = validate_success(
            api_client.analyze_parts_return(
                obligation["id"],
                analyze_parts_return_payload(analysis_result="DEFECT_CONFIRMED"),
                WARRANTY_ADMIN,
            )
        )
        assert analyzed["status"] == "ANALYZED"
        assert analyzed["analysis_result"] == "DEFECT_CONFIRMED"
        assert analyzed["debit_amount_cents"] == 0
        assert get_claim(claim_id)["payment_status"] == "PAID"
        assert list_ledger_entries(dealer_id) == []


def build_rate_petition_world():
    """A dealer on 10000 cents an hour with a 12500-cent petition already under review."""
    set_clock("2026-05-20T00:00:00Z")
    profile = create_state_law_profile(**CA_PROFILE)
    dealer = create_dealer(profile["id"], **GOODWILL_DEALER)
    petition = create_rate_request(
        dealer,
        requested_labor_rate_cents=12500,
        requested_parts_markup_pct=0.30,
        sample_repair_order_count=6,
        sample_median_rate_cents=12500,
        effective_date="2026-06-01",
    )
    assert petition["statutory_ceiling_cents"] == 12500
    petition = review_rate_request(petition["id"], action="START_REVIEW")
    assert petition["status"] == "UNDER_REVIEW"
    return {"profile": profile, "dealer": dealer, "petition": petition}


class TestAdjudicationRoleSplit:
    def test_03_an_adjudicator_raises_goodwill_a_peer_decides_and_a_manager_approves(self):
        """PRD §2.1: "A `ClaimAdjudicator` adjudicates submitted claims against coverage, flat-rate time and the statutory markup cap, and raises goodwill requests for out-of-warranty repairs."
        PRD §3.5: "A `PENDING` authorization may be decided by either a `ClaimAdjudicator` or an `AdjudicationManager`."
        PRD §3.5: "Approval records `approved_amount_cents` and stamps `decided_by_user_id` with the decider's `X-User-ID`, moving the authorization to `APPROVED` and advancing its `version` by 1."
        PRD §3.5: "It then cascades onto the claim: the claim's `coverage_type` flips from `NONE` to `GOODWILL`, the claim's open `NO_COVERAGE` edit is stamped `resolved_at`, `suspend_edit_count` is recomputed from the edits that remain open, and the claim's `version` advances by 1."
        PRD §3.6: "A `ClaimAdjudicator` or an `AdjudicationManager` supplies a `decision` of `APPROVE` or `DENY`, and on approval also supplies `approved_labor_hours` and `approved_parts_qty` — the hours and part units it is willing to grant."
        PRD §3.6: "In that case `approved_total_cents` is the lesser of the unadjusted total and the approved goodwill authorization's `approved_amount_cents` — goodwill caps what the manufacturer will pay — and `dealer_participation_cents` is `approved_total_cents` multiplied by that authorization's `policy_adjustment_pct` and rounded half up to whole cents."

        Design: Corner/rbac/adjudication_roles_positive_operations
        """
        world = build_goodwill_world()
        claim = world["claim"]

        authorization = validate_success(
            api_client.create_goodwill_authorization(
                claim["id"],
                create_goodwill_authorization_payload(
                    requested_amount_cents=40000,
                    policy_adjustment_pct=0.25,
                    justification="Blower motor failed 3,600 miles past the basic limit.",
                    expected_claim_version=claim["version"],
                ),
                ADJUDICATOR,
            ),
            201,
        )
        assert authorization["requested_by_user_id"] == OPERATORS["ADJUDICATOR"]
        assert authorization["out_of_warranty_margin_pct"] == pytest.approx(
            0.1000, abs=0.00001
        )
        assert authorization["adjudicator_limit_cents"] == 40000
        assert authorization["manager_limit_cents"] == 48000
        assert authorization["status"] == "PENDING"

        decided = validate_success(
            api_client.decide_goodwill_authorization(
                authorization["id"],
                decide_goodwill_authorization_payload(
                    action="APPROVE", approved_amount_cents=40000
                ),
                ADJUDICATOR_ALT,
            )
        )
        assert decided["status"] == "APPROVED"
        assert decided["decided_by_user_id"] == OPERATORS["ADJUDICATOR_ALT"]
        assert decided["approved_amount_cents"] == 40000

        released = get_claim(claim["id"])
        assert released["coverage_type"] == "GOODWILL"
        assert released["status"] == "SUBMITTED"
        assert released["suspend_edit_count"] == 0

        final = validate_success(
            api_client.adjudicate_claim(
                claim["id"],
                adjudicate_claim_payload(
                    decision="APPROVE", approved_labor_hours=1.0, approved_parts_qty=1
                ),
                MANAGER,
            )
        )
        assert final["status"] == "APPROVED"
        # The unadjusted total is 60000, so the 40000 authorization caps the payout, and
        # the dealer absorbs a quarter of it.
        assert final["approved_total_cents"] == 40000
        assert final["dealer_participation_cents"] == 10000
        assert final["oem_payable_cents"] == 30000

    def test_04_an_adjudication_manager_grants_the_labor_rate_petition(self):
        """PRD §2.1: "An `AdjudicationManager` decides dealer labor-rate and parts-markup petitions and holds the higher goodwill authority limit."
        PRD §3.2: "An `AdjudicationManager` decides the petition by supplying an `action` of either `APPROVE` or `DENY`, and the acting `X-User-ID` must differ from the recorded `submitted_by_user_id`."
        PRD §3.2: "Approval moves the request to `APPROVED`, writes both granted figures onto the request, then republishes them onto the dealer: the dealer's `approved_labor_rate_cents` and `approved_parts_markup_pct` are overwritten with the granted values and its `labor_rate_effective_date` is set to the request's `effective_date`, with the dealer's `updated_at` refreshed and its `version` advanced by 1."

        Design: Corner/rbac/adjudication_roles_positive_operations
        """
        world = build_rate_petition_world()
        petition = world["petition"]
        before = get_dealer(world["dealer"]["id"])

        decided = validate_success(
            api_client.decide_labor_rate_request(
                petition["id"],
                decide_labor_rate_request_payload(
                    action="APPROVE",
                    approved_labor_rate_cents=12500,
                    approved_parts_markup_pct=0.30,
                ),
                MANAGER,
            )
        )
        assert decided["status"] == "APPROVED"
        assert decided["approved_labor_rate_cents"] == 12500
        assert decided["approved_parts_markup_pct"] == pytest.approx(0.30, abs=0.01)
        assert decided["version"] == petition["version"] + 1

        dealer = get_dealer(world["dealer"]["id"])
        assert dealer["approved_labor_rate_cents"] == 12500
        assert dealer["approved_parts_markup_pct"] == pytest.approx(0.30, abs=0.01)
        assert_date_equals(dealer["labor_rate_effective_date"], "2026-06-01")
        assert dealer["version"] == before["version"] + 1


class TestAuditRoleSplit:
    def test_05_the_field_auditor_visits_and_the_audit_manager_issues_the_chargeback(self):
        """PRD §2.1: "A `FieldAuditor` performs the on-site visit and attaches unsupported-claim findings, but may neither issue nor close an audit."
        PRD §2.1: "An `AuditManager` schedules audits, issues findings together with the extrapolated chargeback, and closes audits."
        PRD §3.8: "The lead auditor going on site moves the audit `SCHEDULED → IN_FIELD`, and any other starting state is `ERR_AUDIT_INVALID_STATE`."
        PRD §3.8: "Going on site sets the dealer's `audit_hold` to true and advances the dealer's `version` by 1, alongside the audit's own."
        PRD §3.8: "A new finding opens in `OPEN` with `appeal_id` null; `OVERTURNED` and `UPHELD` are its terminal states."
        PRD §3.8: "The second step pins the unsampled remainder: the same sum is taken over every claim of the dealer in `APPROVED` with `payment_status` `PAID` and a `repair_date` inside the period regardless of whether a finding names it, and `population_paid_snapshot_cents` is that figure less `sample_paid_snapshot_cents`."
        PRD §3.8: "The fourth step derives `error_rate`: when the pinned sampled denominator is zero the rate is zero, and otherwise it is `sample_chargeback_cents` divided by `sample_paid_snapshot_cents`, rounded half up to four decimal places."
        PRD §3.8: "The fifth step selects the extrapolation tier from that rate, with both boundaries inclusive on their lower edge: a rate of at least 0.10 gives an `extrapolation_factor` of 1.00, a rate of at least 0.05 but below 0.10 gives 0.50, and anything below 0.05 gives 0.00 — a dealer whose sampled error rate is under five percent is not extrapolated against at all."
        PRD §3.8: "Every finding of this audit in `OPEN` moves `OPEN → CHARGED_BACK`, each advancing its own `version` by 1."
        PRD §3.8: "The audit moves `IN_FIELD → FINDINGS_ISSUED`, sets `findings_issued_at` to the current logical-clock instant, sets `appeal_deadline` to that instant advanced by the governing statute's `appeal_window_days` days, and advances its own `version` by 1."

        Design: Corner/rbac/audit_roles_positive_operations
        """
        world = build_scheduled_audit_world()
        audit_id = world["audit"]["id"]
        dealer_id = world["dealer"]["id"]

        in_field = validate_success(api_client.start_audit(audit_id, FIELD_AUDITOR))
        assert in_field["status"] == "IN_FIELD"
        assert in_field["version"] == world["audit"]["version"] + 1
        assert get_dealer(dealer_id)["audit_hold"] is True

        finding = validate_success(
            api_client.create_audit_finding(
                audit_id,
                create_audit_finding_payload(
                    claim_id=world["claim"]["id"],
                    unsupported_amount_cents=10000,
                    finding_code="TIME_NOT_DOCUMENTED",
                    evidence_note="Repair order records no documented technician time.",
                ),
                FIELD_AUDITOR,
            ),
            201,
        )
        assert finding["status"] == "OPEN"
        assert finding["appeal_id"] is None
        assert finding["audit_id"] == audit_id

        issued = validate_success(api_client.issue_audit_findings(audit_id, AUDIT_MANAGER))
        assert issued["status"] == "FINDINGS_ISSUED"
        assert issued["sample_paid_snapshot_cents"] == 20000
        assert issued["population_paid_snapshot_cents"] == 0
        assert issued["sample_chargeback_cents"] == 10000
        # 10000 / 20000 = 0.5000, which is well past the 0.10 tier boundary.
        assert issued["error_rate"] == pytest.approx(0.5000, abs=0.00001)
        assert issued["extrapolation_factor"] == pytest.approx(1.00, abs=0.01)
        # There is no unsampled remainder to extrapolate across.
        assert issued["extrapolated_chargeback_cents"] == 0
        assert issued["total_chargeback_cents"] == 10000
        assert_instant_equals(issued["findings_issued_at"], "2026-05-01T00:00:00Z")
        assert_instant_equals(issued["appeal_deadline"], "2026-05-31T00:00:00Z")
        assert get_finding(finding["id"])["status"] == "CHARGED_BACK"

    def test_06_the_appeal_reviewer_denies_and_the_audit_manager_closes(self):
        """PRD §2.1: "An `AppealReviewer` independently grants, partially grants or denies a dealer's appeal."
        PRD §3.8: "A `DealerWarrantyAdmin` files an appeal against an audit in `FINDINGS_ISSUED`, supplying non-empty written `grounds`, a `contested_finding_ids` array holding at least one finding identifier, and the `expected_audit_version` of §2.9."
        PRD §3.8: "On acceptance the appeal opens in `FILED` with `filed_by_dealer_id` taken from `X-User-ID`, `overturned_finding_ids` an empty array, `reviewer_user_id` and `decision_note` null and `reinstated_amount_cents` at 0; each contested finding has its `appeal_id` stamped with the new appeal; and the audit moves `FINDINGS_ISSUED → APPEALED` with its `version` advanced by 1."
        PRD §3.8: "`DENY` moves the appeal `FILED → DENIED`, moves every contested finding `CHARGED_BACK → UPHELD`, and leaves the appeal's `reinstated_amount_cents` at 0."
        PRD §3.8: "In all three cases `reviewer_user_id` is stamped from `X-User-ID`, every touched finding advances its own `version` by 1, and the appeal's `version` advances by 1."
        PRD §3.8: "A partially granted or a denied appeal instead drives the audit `APPEALED → FINDINGS_ISSUED`, stamping a fresh `findings_issued_at` at the current clock instant and a fresh `appeal_deadline` derived from it, so the dealer may appeal the re-issued findings again inside the new window."
        PRD §3.8: "One ledger row with `source_type` `AUDIT_CHARGEBACK_SAMPLE` is appended per charged-back finding, each carrying that finding's `claim_id` and its positive `unsupported_amount_cents`, so the sampled rows sum to `sample_chargeback_cents`."
        PRD §3.8: "Each row is omitted entirely when its own delta is zero, which is why a denied appeal typically appends nothing at all."
        PRD §3.8: "A successful close moves the audit `FINDINGS_ISSUED → CLOSED`, moves every finding still in `CHARGED_BACK` to `UPHELD` with each such finding's `version` advancing by 1, recomputes the dealer's `audit_hold` and advances the dealer's `version` by 1, and advances the audit's own `version` by 1."

        Design: Corner/rbac/audit_roles_positive_operations
        """
        world = build_issued_audit_world()
        audit_id = world["audit"]["id"]
        dealer_id = world["dealer"]["id"]
        finding_id = world["finding"]["id"]

        appeal = validate_success(
            api_client.create_appeal(
                audit_id,
                create_appeal_payload(
                    contested_finding_ids=[finding_id],
                    expected_audit_version=world["audit"]["version"],
                    grounds="The technician time is documented on the shop copy.",
                ),
                world["dealer_headers"],
            ),
            201,
        )
        assert appeal["status"] == "FILED"
        assert appeal["filed_by_dealer_id"] == dealer_id
        assert appeal["overturned_finding_ids"] == []
        assert appeal["reviewer_user_id"] is None
        assert appeal["reinstated_amount_cents"] == 0
        assert get_finding(finding_id)["appeal_id"] == appeal["id"]
        assert get_audit(audit_id)["status"] == "APPEALED"

        decided = validate_success(
            api_client.decide_appeal(
                appeal["id"],
                decide_appeal_payload(
                    action="DENY",
                    decision_note="The shop copy does not record the hours worked.",
                ),
                APPEAL_REVIEWER,
            )
        )
        assert decided["status"] == "DENIED"
        assert decided["reviewer_user_id"] == OPERATORS["APPEAL_REVIEWER"]
        assert decided["reinstated_amount_cents"] == 0
        assert decided["version"] == appeal["version"] + 1
        assert get_finding(finding_id)["status"] == "UPHELD"

        reissued = get_audit(audit_id)
        assert reissued["status"] == "FINDINGS_ISSUED"
        assert reissued["total_chargeback_cents"] == 10000
        assert_instant_equals(reissued["findings_issued_at"], "2026-05-01T00:00:00Z")
        assert_instant_equals(reissued["appeal_deadline"], "2026-05-31T00:00:00Z")

        entries = list_ledger_entries(dealer_id)
        assert len(entries) == 1
        assert entries[0]["source_type"] == "AUDIT_CHARGEBACK_SAMPLE"
        assert entries[0]["amount_cents"] == 10000

        closed = validate_success(api_client.close_audit(audit_id, AUDIT_MANAGER))
        assert closed["status"] == "CLOSED"
        assert get_dealer(dealer_id)["audit_hold"] is False


class TestPeerRolePartition:
    def test_07_the_audit_lifecycle_roles_cannot_swap_each_others_operations(self):
        """PRD §2.1: "If both headers are well formed but the named role is not among the roles authorised for the target endpoint (see the table in §4), the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §2.1: "A `FieldAuditor` performs the on-site visit and attaches unsupported-claim findings, but may neither issue nor close an audit."
        PRD §3.8: "While the audit is in field the auditor attaches findings, one per unsupported claim."
        PRD §3.8: "The `AuditManager` issues from `IN_FIELD` only; anything else is `ERR_AUDIT_INVALID_STATE`."
        PRD §3.8: "An `AuditManager` closes an audit manually once nothing is pending."

        Design: Corner/rbac/peer_role_exclusive_operations_rejected
        """
        world = build_in_field_audit_world()
        audit_id = world["audit"]["id"]

        validate_error(
            api_client.create_audit_finding(
                audit_id,
                create_audit_finding_payload(
                    claim_id=world["claim"]["id"],
                    unsupported_amount_cents=5000,
                    finding_code="NO_TECHNICIAN_SIGNATURE",
                    evidence_note="Repair order carries no technician signature.",
                ),
                AUDIT_MANAGER,
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
        )
        validate_error(
            api_client.issue_audit_findings(audit_id, FIELD_AUDITOR),
            ApiErrorId.ERR_UNAUTHORIZED,
        )
        validate_error(
            api_client.close_audit(audit_id, APPEAL_REVIEWER),
            ApiErrorId.ERR_UNAUTHORIZED,
        )

        # None of the three refusals moved the audit or the finding it already carries.
        still_in_field = get_audit(audit_id)
        assert still_in_field["status"] == "IN_FIELD"
        assert still_in_field["total_chargeback_cents"] == 0
        assert still_in_field["findings_issued_at"] is None
        findings, meta = validate_paginated(
            api_client.list_audit_findings(WARRANTY_ADMIN, params={"audit_id": audit_id})
        )
        assert meta["total_count"] == 1
        assert len(findings) == 1
        assert findings[0]["id"] == world["finding"]["id"]
        assert findings[0]["status"] == "OPEN"

    def test_08_a_dealer_administrator_is_barred_from_the_cross_dealer_claim_list(self):
        """PRD §2.1: "If both headers are well formed but the named role is not among the roles authorised for the target endpoint (see the table in §4), the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §2.1: "Dealer scoping is enforced on ten operations: reading one dealer, listing that dealer's ledger entries, reading that dealer's expense analytics, submitting a claim, reading one claim, resubmitting a claim, listing a claim's edits, reading one audit, filing an appeal against an audit, and reading one appeal."

        Design: Corner/rbac/peer_role_exclusive_operations_rejected
        """
        world = build_brake_world()
        dealer_headers = world["dealer_headers"]
        claim_id = world["claim"]["id"]

        validate_error(
            api_client.list_claims(
                dealer_headers, params={"dealer_id": world["dealer"]["id"]}
            ),
            ApiErrorId.ERR_UNAUTHORIZED,
        )

        # Reading its own claim, which is one of the ten scoped operations, still works.
        own = validate_success(api_client.get_claim(claim_id, dealer_headers))
        assert own["id"] == claim_id
        assert own["dealer_id"] == world["dealer"]["id"]

        # And the manufacturer-side list the dealer was refused does return that claim.
        rows, _ = validate_paginated(
            api_client.list_claims(
                WARRANTY_ADMIN, params={"dealer_id": world["dealer"]["id"]}
            )
        )
        assert [row["id"] for row in rows] == [claim_id]


def raise_escalated_goodwill(world):
    """Ask for 44000 cents against a 40000/48000 authority pair, so the request escalates."""
    claim = world["claim"]
    authorization = validate_success(
        api_client.create_goodwill_authorization(
            claim["id"],
            create_goodwill_authorization_payload(
                requested_amount_cents=44000,
                policy_adjustment_pct=0.25,
                justification="Blower motor failed 3,600 miles past the basic limit.",
                expected_claim_version=claim["version"],
            ),
            ADJUDICATOR,
        ),
        201,
    )
    assert authorization["adjudicator_limit_cents"] == 40000
    assert authorization["manager_limit_cents"] == 48000
    assert authorization["status"] == "ESCALATED"
    return authorization


class TestEscalatedGoodwillAuthority:
    def test_09_a_claim_adjudicator_is_refused_on_an_escalated_authorization(self):
        """PRD §3.5: "The larger of those two fractions, rounded half up to four decimal places, is `out_of_warranty_margin_pct`."
        PRD §3.5: "`adjudicator_limit_cents` is the lesser of the share cap and the adjudicator base authority of 50,000 cents (500 dollars) multiplied by the decay multiplier and rounded half up to whole cents."
        PRD §3.5: "Above that but at or below `manager_limit_cents` it opens `ESCALATED`."
        PRD §3.5: "An `ESCALATED` authorization may be decided only by an `AdjudicationManager`; a `ClaimAdjudicator` attempting it is refused with `ERR_UNAUTHORIZED_FOR_ESCALATED_GOODWILL` (HTTP 403)."

        Design: Corner/rbac/escalated_goodwill_cannot_be_decided_by_a_claim_adjudicator
        """
        world = build_goodwill_world()
        authorization = raise_escalated_goodwill(world)

        # The peer adjudicator is not the requester, so nothing but the escalation blocks it.
        validate_error(
            api_client.decide_goodwill_authorization(
                authorization["id"],
                decide_goodwill_authorization_payload(
                    action="APPROVE", approved_amount_cents=44000
                ),
                ADJUDICATOR_ALT,
            ),
            ApiErrorId.ERR_UNAUTHORIZED_FOR_ESCALATED_GOODWILL,
        )

        unchanged = get_goodwill(authorization["id"])
        assert unchanged["status"] == "ESCALATED"
        assert unchanged["decided_by_user_id"] is None
        assert unchanged["version"] == authorization["version"]

        claim = get_claim(world["claim"]["id"])
        assert claim["coverage_type"] == "NONE"
        assert claim["status"] == "SUSPENDED"

    def test_10_an_adjudication_manager_decides_the_escalated_authorization(self):
        """PRD §3.5: "An `ESCALATED` authorization may be decided only by an `AdjudicationManager`; a `ClaimAdjudicator` attempting it is refused with `ERR_UNAUTHORIZED_FOR_ESCALATED_GOODWILL` (HTTP 403)."
        PRD §3.5: "On approval the decider supplies `approved_amount_cents`, which must be strictly positive and must not exceed the ceiling that belongs to the deciding role — `adjudicator_limit_cents` when a `ClaimAdjudicator` decides, `manager_limit_cents` when an `AdjudicationManager` decides — with `ERR_GOODWILL_LIMIT_EXCEEDED` on breach."
        PRD §3.5: "Approval records `approved_amount_cents` and stamps `decided_by_user_id` with the decider's `X-User-ID`, moving the authorization to `APPROVED` and advancing its `version` by 1."
        PRD §3.5: "It then cascades onto the claim: the claim's `coverage_type` flips from `NONE` to `GOODWILL`, the claim's open `NO_COVERAGE` edit is stamped `resolved_at`, `suspend_edit_count` is recomputed from the edits that remain open, and the claim's `version` advances by 1."

        Design: Corner/rbac/escalated_goodwill_cannot_be_decided_by_a_claim_adjudicator
        """
        world = build_goodwill_world()
        authorization = raise_escalated_goodwill(world)

        # 44000 is above the adjudicator ceiling of 40000 but inside the manager's 48000.
        decided = validate_success(
            api_client.decide_goodwill_authorization(
                authorization["id"],
                decide_goodwill_authorization_payload(
                    action="APPROVE", approved_amount_cents=44000
                ),
                MANAGER,
            )
        )
        assert decided["status"] == "APPROVED"
        assert decided["approved_amount_cents"] == 44000
        assert decided["decided_by_user_id"] == OPERATORS["MANAGER"]
        assert decided["version"] == authorization["version"] + 1

        released = get_claim(world["claim"]["id"])
        assert released["coverage_type"] == "GOODWILL"
        assert released["status"] == "SUBMITTED"
        assert released["suspend_edit_count"] == 0


class TestAppealIndependence:
    def test_11_the_lead_auditor_cannot_decide_the_appeal_of_its_own_audit(self):
        """PRD §2.10: "Four decisions may not be made by the person who set them up, and the check is always on `X-User-ID` rather than on role."
        PRD §2.10: "Deciding an appeal is refused when the acting user equals the appealed audit's `lead_auditor_user_id`."
        PRD §3.8: "Independence is mandatory: the acting `X-User-ID` must differ from the appealed audit's `lead_auditor_user_id`, and a reviewer who led the audit is refused with `ERR_SEGREGATION_OF_DUTIES`."
        PRD §3.8: "`DENY` moves the appeal `FILED → DENIED`, moves every contested finding `CHARGED_BACK → UPHELD`, and leaves the appeal's `reinstated_amount_cents` at 0."
        PRD §3.8: "In all three cases `reviewer_user_id` is stamped from `X-User-ID`, every touched finding advances its own `version` by 1, and the appeal's `version` advances by 1."

        Design: Corner/rbac/lead_auditor_cannot_decide_an_appeal_of_its_own_audit
        """
        world = build_issued_audit_world()
        audit_id = world["audit"]["id"]
        finding_id = world["finding"]["id"]
        assert get_audit(audit_id)["lead_auditor_user_id"] == OPERATORS["AUDITOR_LEAD"]

        appeal = file_appeal(world["audit"], [finding_id])
        assert appeal["status"] == "FILED"

        # Correct role, wrong person: the operator who led the visit is still barred.
        conflicted = make_operator_headers(OPERATORS["AUDITOR_LEAD"], "AppealReviewer")
        validate_error(
            api_client.decide_appeal(
                appeal["id"],
                decide_appeal_payload(
                    action="DENY", decision_note="Evidence file reviewed on site."
                ),
                conflicted,
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        )

        untouched = get_appeal(appeal["id"])
        assert untouched["status"] == "FILED"
        assert untouched["reviewer_user_id"] is None
        assert untouched["version"] == appeal["version"]
        assert get_finding(finding_id)["status"] == "CHARGED_BACK"

        decided = validate_success(
            api_client.decide_appeal(
                appeal["id"],
                decide_appeal_payload(
                    action="DENY",
                    decision_note="The shop copy does not record the hours worked.",
                ),
                APPEAL_REVIEWER,
            )
        )
        assert decided["status"] == "DENIED"
        assert decided["reviewer_user_id"] == OPERATORS["APPEAL_REVIEWER"]
        assert decided["reinstated_amount_cents"] == 0
        assert decided["version"] == appeal["version"] + 1
        assert get_finding(finding_id)["status"] == "UPHELD"
