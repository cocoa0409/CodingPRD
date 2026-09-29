"""Version pinning on dependent creates, posture thresholds and the open-return counter."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_finding,
    api_client,
    approve_claim,
    assert_date_equals,
    assert_instant_equals,
    create_appeal_payload,
    create_audit_payload,
    create_dealer,
    create_goodwill_authorization_payload,
    create_labor_rate_request_payload,
    create_rate_request,
    create_state_law_profile,
    create_vehicle,
    decide_appeal,
    decide_rate_request,
    deny_claim,
    file_appeal,
    get_audit,
    get_claim,
    get_dealer,
    get_finding,
    get_parts_return,
    issue_findings,
    list_claim_edits,
    list_ledger_entries,
    make_dealer_warranty_admin_headers,
    parts_return_for_claim,
    pay_claim,
    receive_part,
    resubmit_claim,
    review_rate_request,
    run_non_return_sweep,
    schedule_audit,
    set_clock,
    setup_claim,
    start_audit,
    submit_claim,
    validate_error,
    validate_paginated,
    validate_success,
)

WARRANTY_ADMIN = TEST_USERS["warranty_admin_headers"]
ADJUDICATOR = TEST_USERS["claim_adjudicator_headers"]
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

COVERED_VEHICLE = {
    "model_year": 2025,
    "warranty_start_date": "2025-01-15",
    "in_service_odometer": 0,
    "basic_months": 36,
    "basic_miles": 36000,
    "powertrain_months": 60,
    "powertrain_miles": 60000,
}

NARRATIVE = {
    "complaint_text": "Customer reports intermittent fault on delivery.",
    "cause_text": "Component failed internal leak test at the dealership.",
    "correction_text": "Replaced the failed component and road tested the vehicle.",
}

PETITIONING_DEALER = {
    "dealer_code": "D1",
    "name": "Dealer One",
    "vehicles_in_operation": 100,
    "initial_labor_rate_cents": 13750,
    "initial_parts_markup_pct": 0.40,
}


def build_dealer_with_a_granted_rate():
    """A CA dealer at 13750 whose first petition for 17600 has already been granted,
    so the dealer version a client read before the petition is two writes behind."""
    set_clock("2026-05-01T00:00:00Z")
    profile = create_state_law_profile(**CA_PROFILE)
    dealer = create_dealer(profile["id"], **PETITIONING_DEALER)
    stale_dealer_version = dealer["version"]

    first = create_rate_request(
        dealer,
        requested_labor_rate_cents=17600,
        requested_parts_markup_pct=0.30,
        sample_repair_order_count=5,
        sample_median_rate_cents=17600,
        effective_date="2026-06-01",
    )
    # 13750 stepped up by 25% is 17188, the cited median of 17600 is greater, and the
    # statutory maximum of 19500 does not bite.
    assert first["statutory_ceiling_cents"] == 17600
    review_rate_request(first["id"], action="START_REVIEW")
    granted = decide_rate_request(
        first["id"],
        action="APPROVE",
        approved_labor_rate_cents=17600,
        approved_parts_markup_pct=0.30,
    )
    assert granted["status"] == "APPROVED"
    assert get_dealer(dealer["id"])["approved_labor_rate_cents"] == 17600
    return {
        "profile": profile,
        "dealer": dealer,
        "stale_dealer_version": stale_dealer_version,
        "first_request": first,
        "dealer_headers": make_dealer_warranty_admin_headers(dealer["id"]),
    }


def second_petition_payload(dealer_id, expected_dealer_version):
    """The follow-up petition for 19000, which every leg of the exercise re-uses."""
    return create_labor_rate_request_payload(
        dealer_id=dealer_id,
        expected_dealer_version=expected_dealer_version,
        requested_labor_rate_cents=19000,
        requested_parts_markup_pct=0.30,
        sample_repair_order_count=6,
        sample_median_rate_cents=19000,
        effective_date="2026-07-01",
    )


AUDIT_DEALER = {
    "dealer_code": "DA",
    "name": "Audit Motors",
    "vehicles_in_operation": 100,
    "initial_labor_rate_cents": 10000,
    "initial_parts_markup_pct": 0.25,
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
    **NARRATIVE,
}


def build_audited_dealer_in_field():
    """One paid 20000 claim, an audit over [2026-01-01, 2026-04-01) that the lead
    auditor has already started, and the dealer version read before it was scheduled."""
    set_clock("2026-05-01T00:00:00Z")
    world = setup_claim(
        profile_overrides=CA_PROFILE,
        dealer_overrides=AUDIT_DEALER,
        vehicle_overrides={**COVERED_VEHICLE, "vin": "VIN0000000000AUD1"},
        operation_overrides=AUDIT_OPERATION,
        with_part=False,
        claim_overrides=AUDIT_CLAIM,
    )
    approved = approve_claim(
        world["claim"]["id"], approved_labor_hours=2.0, approved_parts_qty=0
    )
    assert approved["approved_total_cents"] == 20000
    paid = pay_claim(approved["id"])
    assert paid["payment_status"] == "PAID"

    dealer = get_dealer(world["dealer"]["id"])
    world["claim"] = paid
    world["stale_dealer_version"] = dealer["version"]
    scheduled = schedule_audit(
        dealer, period_start="2026-01-01", period_end="2026-04-01", sample_size=1
    )
    world["audit"] = start_audit(scheduled["id"])
    return world


def build_issued_audit_with_a_denied_appeal():
    """The single 10000 finding was issued, appealed and denied, so the audit sits back
    in FINDINGS_ISSUED with a version beyond the one captured at issue."""
    world = build_audited_dealer_in_field()
    finding = add_finding(
        world["audit"]["id"],
        world["claim"]["id"],
        10000,
        finding_code="TIME_NOT_DOCUMENTED",
        evidence_note="Technician time is not documented on the repair order.",
    )
    issued = issue_findings(world["audit"]["id"])
    assert issued["status"] == "FINDINGS_ISSUED"
    assert issued["total_chargeback_cents"] == 10000
    stale_audit_version = issued["version"]

    appeal = file_appeal(
        issued,
        [finding["id"]],
        grounds="The repair order carries the technician time on its reverse side.",
    )
    denied = decide_appeal(
        appeal["id"],
        action="DENY",
        decision_note="The reverse of the repair order was reviewed on appeal.",
    )
    assert denied["status"] == "DENIED"

    world["finding"] = finding
    world["first_appeal"] = denied
    world["stale_audit_version"] = stale_audit_version
    world["audit"] = get_audit(issued["id"])
    return world


GOODWILL_DEALER = {
    "dealer_code": "D-GW",
    "name": "Goodwill Motors",
    "vehicles_in_operation": 100,
    "initial_labor_rate_cents": 10000,
    "initial_parts_markup_pct": 0.25,
}

GOODWILL_OPERATION = {
    "op_code": "GW-200",
    "description": "Cabin HVAC blower replacement",
    "standard_time_hours": 1.0,
    "max_time_hours": 1.5,
    "category": "BASIC",
    "requires_causal_part": True,
    "causal_failure_group": "HVAC",
    "overlap_group": "HVAC",
}

GOODWILL_PART = {
    "part_number": "GW-P1",
    "description": "HVAC blower motor",
    "dealer_net_cents": 40000,
    "failure_group": "HVAC",
    "return_required": True,
    "retention_days": 30,
}

GOODWILL_CLAIM = {
    "repair_order_number": "RO-GW-1",
    "repair_date": "2026-05-14",
    "odometer_at_repair": 39600,
    "claimed_labor_hours": 1.0,
    "claimed_parts_qty": 1,
    **NARRATIVE,
}


def build_corrected_out_of_warranty_claim():
    """A claim 3600 miles past its 36000-mile basic term, corrected in place once, so the
    claim version captured at submission is a write behind."""
    set_clock("2026-05-20T00:00:00Z")
    world = setup_claim(
        profile_overrides=CA_PROFILE,
        dealer_overrides=GOODWILL_DEALER,
        vehicle_overrides={
            **COVERED_VEHICLE,
            "vin": "VIN00000000000GW1",
            "model_year": 2023,
            "warranty_start_date": "2023-06-15",
        },
        operation_overrides=GOODWILL_OPERATION,
        part_overrides=GOODWILL_PART,
        claim_overrides=GOODWILL_CLAIM,
    )
    submitted = world["claim"]
    assert submitted["coverage_type"] == "NONE"
    assert submitted["status"] == "SUSPENDED"
    assert submitted["provisional_total_cents"] == 60000
    world["stale_claim_version"] = submitted["version"]

    corrected = resubmit_claim(
        world,
        claimed_labor_hours=1.0,
        claimed_parts_qty=1,
        complaint_text=NARRATIVE["complaint_text"],
        cause_text=NARRATIVE["cause_text"],
        correction_text=(
            "Replaced the failed component, road tested the vehicle and verified "
            "normal operation."
        ),
    )
    # The correction still trips the coverage edit, so the claim stays suspended and the
    # two authority inputs are unchanged.
    assert corrected["status"] == "SUSPENDED"
    assert corrected["coverage_type"] == "NONE"
    assert corrected["provisional_total_cents"] == 60000
    world["claim"] = corrected
    return world


def goodwill_payload(expected_claim_version):
    """The 40000-cent request at a 0.25 dealer share that both legs of the exercise send."""
    return create_goodwill_authorization_payload(
        expected_claim_version=expected_claim_version,
        requested_amount_cents=40000,
        policy_adjustment_pct=0.25,
        justification="Long-standing customer just outside the mileage limit.",
    )


PROBATION_DEALER = {
    "dealer_code": "DP",
    "name": "Probation Motors",
    "vehicles_in_operation": 100,
    "initial_labor_rate_cents": 10000,
    "initial_parts_markup_pct": 0.25,
}

AXLE_OPERATION = {
    "op_code": "PB-100",
    "description": "Rear axle assembly replacement",
    "standard_time_hours": 6.0,
    "max_time_hours": 6.0,
    "category": "BASIC",
    "requires_causal_part": True,
    "causal_failure_group": "AXLE",
    "overlap_group": "AXLE",
}

AXLE_PART = {
    "part_number": "AXL-1",
    "description": "Rear axle assembly",
    "dealer_net_cents": 24000,
    "failure_group": "AXLE",
    "return_required": True,
    "retention_days": 30,
}


def build_dealer_on_the_probation_boundary():
    """One paid claim worth exactly 90000 whose part never came back, and a second claim
    still in SUBMITTED whose own part did, with the clock past the first due date."""
    set_clock("2026-05-01T00:00:00Z")
    world = setup_claim(
        profile_overrides=CA_PROFILE,
        dealer_overrides=PROBATION_DEALER,
        vehicle_overrides={**COVERED_VEHICLE, "vin": "VIN0000000000PRB1"},
        operation_overrides=AXLE_OPERATION,
        part_overrides=AXLE_PART,
        claim_overrides={
            "repair_order_number": "RO-PB-1",
            "repair_date": "2026-04-10",
            "odometer_at_repair": 20000,
            "claimed_labor_hours": 6.0,
            "claimed_parts_qty": 1,
            **NARRATIVE,
        },
    )
    approved = approve_claim(
        world["claim"]["id"], approved_labor_hours=6.0, approved_parts_qty=1
    )
    # 6.0 h at 10000 plus round_half_up(24000 * 1.25) lands on the threshold exactly.
    assert approved["approved_total_cents"] == 90000
    world["overdue_claim"] = pay_claim(approved["id"])

    second_vehicle = create_vehicle(
        **{**COVERED_VEHICLE, "vin": "VIN0000000000PRB2"}
    )
    sibling = submit_claim(
        {**world, "vehicle": second_vehicle},
        repair_order_number="RO-PB-2",
        repair_date="2026-04-12",
        odometer_at_repair=21000,
        claimed_labor_hours=6.0,
        claimed_parts_qty=1,
        **NARRATIVE,
    )
    assert sibling["status"] == "SUBMITTED"
    receive_part(parts_return_for_claim(sibling["id"])["id"], "2026-05-01")
    world["sibling_claim"] = sibling

    assert get_dealer(world["dealer"]["id"])["open_parts_return_count"] == 1
    set_clock("2026-06-01T00:00:00Z")
    return world


RECONCILE_DEALER = {
    "dealer_code": "DR",
    "name": "Reconcile Motors",
    "vehicles_in_operation": 100,
    "initial_labor_rate_cents": 10000,
    "initial_parts_markup_pct": 0.25,
}

FUEL_OPERATION = {
    "op_code": "RC-100",
    "description": "Fuel pump replacement",
    "standard_time_hours": 1.0,
    "max_time_hours": 1.5,
    "category": "BASIC",
    "requires_causal_part": True,
    "causal_failure_group": "FUEL",
    "overlap_group": "FUEL",
}

FUEL_PART = {
    "part_number": "FUE-1",
    "description": "Fuel pump module",
    "dealer_net_cents": 8000,
    "failure_group": "FUEL",
    "return_required": True,
    "retention_days": 30,
}


def build_three_return_obligations():
    """Three 20000-cent claims on three vehicles, each with its own return obligation:
    the first paid, the second still submitted, the third approved but unpaid."""
    set_clock("2026-05-01T00:00:00Z")
    world = setup_claim(
        profile_overrides=CA_PROFILE,
        dealer_overrides=RECONCILE_DEALER,
        vehicle_overrides={**COVERED_VEHICLE, "vin": "VIN0000000000REC1"},
        operation_overrides=FUEL_OPERATION,
        part_overrides=FUEL_PART,
        claim_overrides={
            "repair_order_number": "RO-RC-1",
            "repair_date": "2026-04-10",
            "odometer_at_repair": 20000,
            "claimed_labor_hours": 1.0,
            "claimed_parts_qty": 1,
            **NARRATIVE,
        },
    )
    second_vehicle = create_vehicle(**{**COVERED_VEHICLE, "vin": "VIN0000000000REC2"})
    third_vehicle = create_vehicle(**{**COVERED_VEHICLE, "vin": "VIN0000000000REC3"})

    denied_candidate = submit_claim(
        {**world, "vehicle": second_vehicle},
        repair_order_number="RO-RC-2",
        repair_date="2026-04-11",
        odometer_at_repair=21000,
        claimed_labor_hours=1.0,
        claimed_parts_qty=1,
        **NARRATIVE,
    )
    unpaid_candidate = submit_claim(
        {**world, "vehicle": third_vehicle},
        repair_order_number="RO-RC-3",
        repair_date="2026-04-12",
        odometer_at_repair=22000,
        claimed_labor_hours=1.0,
        claimed_parts_qty=1,
        **NARRATIVE,
    )

    paid = approve_claim(
        world["claim"]["id"], approved_labor_hours=1.0, approved_parts_qty=1
    )
    assert paid["approved_total_cents"] == 20000
    world["paid_claim"] = pay_claim(paid["id"])

    unpaid = approve_claim(
        unpaid_candidate["id"], approved_labor_hours=1.0, approved_parts_qty=1
    )
    assert unpaid["approved_total_cents"] == 20000
    assert unpaid["payment_status"] == "UNPAID"

    world["submitted_claim"] = denied_candidate
    world["unpaid_claim"] = unpaid
    world["paid_return"] = parts_return_for_claim(world["paid_claim"]["id"])
    world["unpaid_return"] = parts_return_for_claim(unpaid["id"])
    return world


class TestStaleDealerVersionOnDependentCreates:
    def test_01_a_petition_pinned_to_a_superseded_dealer_version_is_refused(self):
        """PRD §2.9: "In all four cases the version field is a mandatory, non-optional body field, and a value that does not exactly equal the parent record's current `version` at the moment of the request is rejected before any state check runs."
        PRD §2.9: "Creating a labor-rate request requires `expected_dealer_version` matching the petitioning `Dealer`'s current `version`."
        PRD §2.9: "The rejection carries `ERR_STALE_DEALER_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_dealer_version_on_labor_rate_request
        """
        world = build_dealer_with_a_granted_rate()

        response = api_client.create_labor_rate_request(
            second_petition_payload(
                world["dealer"]["id"], world["stale_dealer_version"]
            ),
            world["dealer_headers"],
        )

        validate_error(response, ApiErrorId.ERR_STALE_DEALER_VERSION, 412)
        # Nothing was written: the granted petition is still the only row on file.
        rows, meta = validate_paginated(
            api_client.list_labor_rate_requests(WARRANTY_ADMIN)
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == world["first_request"]["id"]
        assert get_dealer(world["dealer"]["id"])["approved_labor_rate_cents"] == 17600

    def test_02_the_fresh_dealer_version_admits_the_petition_and_lifts_the_ceiling(self):
        """PRD §2.9: "If the dealer's version has advanced since the client last read it, the client's view of the dealer's currently approved rate and of any pending petition is stale — an earlier writer may already have created a request that superseded the prior one — and the statutory ceiling this request would compute would be derived from obsolete inputs."
        PRD §3.2: "The ceiling itself is written into `statutory_ceiling_cents` at creation and never recomputed thereafter."
        PRD §3.2: "Under the retail-sample method the server first works out a step-up floor by taking the dealer's currently approved hourly rate, increasing it by twenty-five percent, and rounding the product half up to whole cents; it then takes the greater of the cited sample median and that step-up floor; and it finally takes the lesser of that result and the statute's absolute `max_labor_rate_cents`."
        PRD §3.2: "The request opens in `SUBMITTED` with `deemed_approved` false, and the petitioning dealer's `version` advances by 1."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_dealer_version_on_labor_rate_request
        """
        world = build_dealer_with_a_granted_rate()

        refreshed = get_dealer(world["dealer"]["id"])
        assert refreshed["approved_labor_rate_cents"] == 17600
        assert refreshed["version"] > world["stale_dealer_version"]

        petition = validate_success(
            api_client.create_labor_rate_request(
                second_petition_payload(world["dealer"]["id"], refreshed["version"]),
                world["dealer_headers"],
            ),
            201,
        )

        # The step-up floor is now 17600 * 1.25 = 22000, above the 19000 median, so the
        # statutory maximum of 19500 is what caps this petition.
        assert petition["statutory_ceiling_cents"] == 19500
        assert petition["status"] == "SUBMITTED"
        assert petition["deemed_approved"] is False
        assert petition["requested_labor_rate_cents"] == 19000
        assert get_dealer(world["dealer"]["id"])["version"] == refreshed["version"] + 1

    def test_03_an_audit_pinned_to_a_pre_visit_dealer_version_is_refused(self):
        """PRD §2.9: "Scheduling a dealer audit likewise requires `expected_dealer_version` matching the audited `Dealer`'s current `version`, and a mismatch is rejected with `ERR_STALE_DEALER_VERSION` (HTTP 412)."
        PRD §2.9: "A second audit over a different, non-overlapping period is a perfectly legitimate operation that no state rule would block, so this check is what forces the scheduler to re-read the dealer's posture and `audit_hold` before committing another audit against it."
        PRD §3.8: "Going on site sets the dealer's `audit_hold` to true and advances the dealer's `version` by 1, alongside the audit's own."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_dealer_version_on_audit_create
        """
        world = build_audited_dealer_in_field()

        response = api_client.create_audit(
            create_audit_payload(
                dealer_id=world["dealer"]["id"],
                expected_dealer_version=world["stale_dealer_version"],
                period_start="2026-04-01",
                period_end="2026-07-01",
                sample_size=1,
            ),
            AUDIT_MANAGER,
        )

        validate_error(response, ApiErrorId.ERR_STALE_DEALER_VERSION, 412)
        _, meta = validate_paginated(api_client.list_audits(WARRANTY_ADMIN))
        assert meta["total_count"] == 1

        dealer = get_dealer(world["dealer"]["id"])
        assert dealer["audit_hold"] is True
        assert dealer["version"] > world["stale_dealer_version"]

    def test_04_the_fresh_dealer_version_admits_the_adjacent_audit_period(self):
        """PRD §3.8: "No other audit of the same dealer whose `status` is `SCHEDULED`, `IN_FIELD`, `FINDINGS_ISSUED` or `APPEALED` may have a period intersecting the requested one, and because the intervals are half-open with no buffer whatsoever, a new period whose `period_start` equals an existing period's `period_end` is adjacent rather than overlapping and is accepted."
        PRD §3.8: "A scheduled audit opens in `SCHEDULED` with `sample_paid_snapshot_cents`, `population_paid_snapshot_cents`, `sample_chargeback_cents`, `extrapolated_chargeback_cents` and `total_chargeback_cents` all at 0, with `error_rate` and `extrapolation_factor` at zero, and with `findings_issued_at` and `appeal_deadline` both null; the dealer's `version` advances by 1."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_dealer_version_on_audit_create
        """
        world = build_audited_dealer_in_field()
        refreshed = get_dealer(world["dealer"]["id"])

        second = validate_success(
            api_client.create_audit(
                create_audit_payload(
                    dealer_id=world["dealer"]["id"],
                    expected_dealer_version=refreshed["version"],
                    period_start="2026-04-01",
                    period_end="2026-07-01",
                    sample_size=1,
                ),
                AUDIT_MANAGER,
            ),
            201,
        )

        assert second["status"] == "SCHEDULED"
        assert_date_equals(second["period_start"], "2026-04-01", "period_start")
        assert_date_equals(second["period_end"], "2026-07-01", "period_end")
        assert second["sample_paid_snapshot_cents"] == 0
        assert second["population_paid_snapshot_cents"] == 0
        assert second["total_chargeback_cents"] == 0
        assert second["findings_issued_at"] is None
        assert second["appeal_deadline"] is None
        assert get_dealer(world["dealer"]["id"])["version"] == refreshed["version"] + 1
        # The audit already in field is untouched by the adjacent one.
        assert get_audit(world["audit"]["id"])["status"] == "IN_FIELD"


class TestStaleClaimAndAuditVersions:
    def test_05_goodwill_pinned_to_a_pre_correction_claim_version_is_refused(self):
        """PRD §2.9: "Creating a goodwill authorization requires `expected_claim_version` matching the target `WarrantyClaim`'s current `version`, and a mismatch is rejected with `ERR_STALE_CLAIM_VERSION` (HTTP 412)."
        PRD §2.9: "Because a new authorization supersedes any prior one that is still open, a second create would otherwise succeed against a claim whose `provisional_total_cents` — the input to both authority limits — had since been recomputed by a resubmission."
        PRD §3.4: "`suspend_edit_count` is set to the number of suspending edits in that fresh set, and the claim's `version` advances by 1."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_claim_version_on_goodwill_create
        """
        world = build_corrected_out_of_warranty_claim()
        claim_id = world["claim"]["id"]

        response = api_client.create_goodwill_authorization(
            claim_id,
            goodwill_payload(world["stale_claim_version"]),
            ADJUDICATOR,
        )

        validate_error(response, ApiErrorId.ERR_STALE_CLAIM_VERSION, 412)
        _, meta = validate_paginated(
            api_client.list_goodwill_authorizations(WARRANTY_ADMIN)
        )
        assert meta["total_count"] == 0

        current = get_claim(claim_id)
        assert current["version"] > world["stale_claim_version"]
        assert current["provisional_total_cents"] == 60000

    def test_06_the_fresh_claim_version_pins_both_authority_limits(self):
        """PRD §3.5: "A decay multiplier is then formed by subtracting twice the margin from one and flooring the result at zero, so a repair ten percent past its warranty terms retains eighty percent of the base authority, a repair fifty percent past them retains none of it."
        PRD §3.5: "Separately, a share cap is formed by taking eighty percent of the claim's `provisional_total_cents` and rounding half up to whole cents — goodwill never covers the entire provisional value of a repair."
        PRD §3.5: "`adjudicator_limit_cents` is the lesser of the share cap and the adjudicator base authority of 50,000 cents (500 dollars) multiplied by the decay multiplier and rounded half up to whole cents."
        PRD §3.5: "`manager_limit_cents` is the lesser of the same share cap and the manager base authority of 250,000 cents (2,500 dollars) multiplied by the same decay multiplier and rounded half up to whole cents."
        PRD §3.5: "At or below `adjudicator_limit_cents` it opens `PENDING`."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_claim_version_on_goodwill_create
        """
        world = build_corrected_out_of_warranty_claim()
        claim_id = world["claim"]["id"]
        current = get_claim(claim_id)

        authorization = validate_success(
            api_client.create_goodwill_authorization(
                claim_id, goodwill_payload(current["version"]), ADJUDICATOR
            ),
            201,
        )

        # 3600 miles over a 36000-mile term is a 0.10 margin, so the decay is 0.80: the
        # adjudicator keeps 40000 of its 50000 base and the 48000 share cap binds the
        # manager instead of its 200000 decayed base.
        assert authorization["out_of_warranty_margin_pct"] == pytest.approx(0.1000, abs=0.00001)
        assert authorization["adjudicator_limit_cents"] == 40000
        assert authorization["manager_limit_cents"] == 48000
        assert authorization["status"] == "PENDING"
        assert authorization["requested_amount_cents"] == 40000

    def test_07_a_second_appeal_pinned_to_the_pre_decision_audit_version_is_refused(self):
        """PRD §2.9: "Filing an appeal requires `expected_audit_version` matching the appealed `DealerAudit`'s current `version`, and a mismatch is rejected with `ERR_STALE_AUDIT_VERSION` (HTTP 412)."
        PRD §2.9: "Since a partially granted or denied decision returns the audit to `FINDINGS_ISSUED` with a fresh deadline, a second appeal round is legitimate, and this check forces the filer to re-read which findings are still charged back and what the current `appeal_deadline` is before filing again."
        PRD §3.8: "A partially granted or a denied appeal instead drives the audit `APPEALED → FINDINGS_ISSUED`, stamping a fresh `findings_issued_at` at the current clock instant and a fresh `appeal_deadline` derived from it, so the dealer may appeal the re-issued findings again inside the new window."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_audit_version_on_second_appeal
        """
        world = build_issued_audit_with_a_denied_appeal()
        audit_id = world["audit"]["id"]

        response = api_client.create_appeal(
            audit_id,
            create_appeal_payload(
                contested_finding_ids=[world["finding"]["id"]],
                expected_audit_version=world["stale_audit_version"],
                grounds="Fresh evidence was located in the dealership archive.",
            ),
            make_dealer_warranty_admin_headers(world["dealer"]["id"]),
        )

        validate_error(response, ApiErrorId.ERR_STALE_AUDIT_VERSION, 412)
        _, meta = validate_paginated(api_client.list_appeals(WARRANTY_ADMIN))
        assert meta["total_count"] == 1

        audit = get_audit(audit_id)
        assert audit["status"] == "FINDINGS_ISSUED"
        assert audit["version"] > world["stale_audit_version"]
        assert_instant_equals(
            audit["findings_issued_at"], "2026-05-01T00:00:00Z", "findings_issued_at"
        )
        assert_instant_equals(
            audit["appeal_deadline"], "2026-05-31T00:00:00Z", "appeal_deadline"
        )

    def test_08_the_fresh_audit_version_reaches_the_finding_membership_check(self):
        """PRD §2.9: "In all four cases the version field is a mandatory, non-optional body field, and a value that does not exactly equal the parent record's current `version` at the moment of the request is rejected before any state check runs."
        PRD §3.8: "Every identifier in `contested_finding_ids` must name a finding belonging to the audit in question and must find that finding in `CHARGED_BACK`; otherwise the filing is refused with `ERR_FINDING_NOT_IN_AUDIT`."
        PRD §3.8: "`DENY` moves the appeal `FILED → DENIED`, moves every contested finding `CHARGED_BACK → UPHELD`, and leaves the appeal's `reinstated_amount_cents` at 0."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_audit_version_on_second_appeal
        """
        world = build_issued_audit_with_a_denied_appeal()
        audit_id = world["audit"]["id"]
        assert get_finding(world["finding"]["id"])["status"] == "UPHELD"

        response = api_client.create_appeal(
            audit_id,
            create_appeal_payload(
                contested_finding_ids=[world["finding"]["id"]],
                expected_audit_version=get_audit(audit_id)["version"],
                grounds="Fresh evidence was located in the dealership archive.",
            ),
            make_dealer_warranty_admin_headers(world["dealer"]["id"]),
        )

        # With the version fresh the request survives the pinning check and now fails on
        # the finding, which the denial already upheld.
        validate_error(response, ApiErrorId.ERR_FINDING_NOT_IN_AUDIT, 409)
        _, meta = validate_paginated(api_client.list_appeals(WARRANTY_ADMIN))
        assert meta["total_count"] == 1
        assert world["first_appeal"]["reinstated_amount_cents"] == 0


class TestPostureThresholdBoundary:
    def test_09_a_non_return_debit_landing_exactly_on_the_probation_threshold(self):
        """PRD §3.7: "Each swept obligation moves `REQUESTED → NOT_RETURNED`, has `debit_amount_cents` set to the linked claim's entire `approved_total_cents` — a non-return costs the dealer the whole claim, labor included, not merely the parts — decrements the dealer's `open_parts_return_count` by 1, and advances its own `version` by 1."
        PRD §3.7: "The sweep reports `swept_count`, the identifiers of the claims it debited as `debited_claim_ids`, and the summed positive debit as `total_debit_cents`."
        PRD §2.8: "A balance of at least 200,000 cents — 2,000 dollars — puts the dealer in `SUSPENDED`."
        PRD §2.8: "Otherwise, a balance of at least 90,000 cents — 900 dollars — puts the dealer in `PROBATION`."
        PRD §2.8: "In practice the server maintains it incrementally: each append adds that row's `amount_cents` to the dealer's current balance, writes the result into the row's `balance_after_cents`, and stores it as the dealer's new `chargeback_balance_cents`."

        Design: Corner/cross_cutting_complexity_layers/chargeback_balance_at_exact_probation_threshold
        """
        world = build_dealer_on_the_probation_boundary()
        overdue_id = world["overdue_claim"]["id"]

        sweep = run_non_return_sweep()

        assert sweep["swept_count"] == 1
        assert sweep["total_debit_cents"] == 90000
        assert sweep["debited_claim_ids"] == [overdue_id]

        dealer = get_dealer(world["dealer"]["id"])
        # 90000 reaches the probation band inclusively and stops well short of 200000.
        assert dealer["chargeback_balance_cents"] == 90000
        assert dealer["status"] == "PROBATION"

        entries, meta = validate_paginated(
            api_client.list_dealer_ledger_entries(
                world["dealer"]["id"], WARRANTY_ADMIN, params={"limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 1
        assert entries[0]["source_type"] == "PARTS_NON_RETURN"
        assert entries[0]["amount_cents"] == 90000
        assert entries[0]["balance_after_cents"] == 90000
        assert entries[0]["claim_id"] == overdue_id

        swept_return = get_parts_return(parts_return_for_claim(overdue_id)["id"])
        assert swept_return["status"] == "NOT_RETURNED"
        assert swept_return["debit_amount_cents"] == 90000

    def test_10_the_boundary_cascade_suspends_the_sibling_submitted_claim(self):
        """PRD §3.7: "The sweep considers every obligation still in `REQUESTED` whose `due_date` the logical clock has reached or passed, and whose linked claim is in `APPROVED`; it processes them in ascending order of their own `created_at`, so that the sequence of `balance_after_cents` values it writes onto the ledger is deterministic."
        PRD §3.7: "Third, the dealer's `status` is recomputed from the new balance and may rise `ACTIVE → PROBATION` or `ACTIVE → SUSPENDED`, with the dealer's `version` advancing by 1."
        PRD §3.7: "Fourth, if that recomputation put the dealer into `PROBATION` or `SUSPENDED`, every claim of that dealer currently in `SUBMITTED` is driven `SUBMITTED → SUSPENDED`: each such claim receives an appended edit whose `edit_code` is `DEALER_POSTURE_HOLD` and whose `severity` is `SUSPEND`, has its `suspend_edit_count` incremented by 1, and has its `version` advanced by 1."
        PRD §3.7: "First, the linked claim's `debited_amount_cents` is increased by the debit and its `payment_status` moves to `DEBITED`, from `PAID` if it had been paid and from `UNPAID` if it had not; a debit against an unpaid claim still books a positive ledger amount, and that claim can never be paid afterwards because payment requires `payment_status` to be `UNPAID`."

        Design: Corner/cross_cutting_complexity_layers/chargeback_balance_at_exact_probation_threshold
        """
        world = build_dealer_on_the_probation_boundary()
        sibling_id = world["sibling_claim"]["id"]
        sibling_return = parts_return_for_claim(sibling_id)
        assert get_parts_return(sibling_return["id"])["status"] == "RECEIVED"

        run_non_return_sweep()

        debited = get_claim(world["overdue_claim"]["id"])
        assert debited["payment_status"] == "DEBITED"
        assert debited["debited_amount_cents"] == 90000

        # The sibling's own part came back, yet the dealer's posture suspends it anyway.
        sibling = get_claim(sibling_id)
        assert sibling["status"] == "SUSPENDED"
        assert sibling["suspend_edit_count"] == 1

        holds = [
            edit
            for edit in list_claim_edits(sibling_id, {"limit": 10, "offset": 0})
            if edit["edit_code"] == "DEALER_POSTURE_HOLD"
        ]
        assert len(holds) == 1
        assert holds[0]["severity"] == "SUSPEND"
        assert holds[0]["resolved_at"] is None


class TestOpenPartsReturnCountReconciliation:
    def test_11_the_counter_falls_by_one_on_receipt_and_on_the_denial_waiver(self):
        """PRD §3.4: "When the submission's causal part has `return_required` true, the same request also raises a parts-return obligation in `REQUESTED`, whose `due_date` is its own `created_at` advanced by the part's `retention_days` days, and increments the dealer's `open_parts_return_count` by 1 — re-establishing the invariant that the count always equals the number of parts-return rows in `REQUESTED` whose claim belongs to that dealer."
        PRD §3.7: "A timely receipt moves `REQUESTED → RECEIVED`, stamps `received_date`, decrements the dealer's `open_parts_return_count` by 1, advances the dealer's `version` by 1, and advances the obligation's `version` by 1."
        PRD §3.7: "The last route out of `REQUESTED` is the waiver already described in §3.6: when the linked claim reaches `DENIED` or `VOID`, its `REQUESTED` obligations move `REQUESTED → WAIVED`, the dealer's `open_parts_return_count` drops by one per waived row, and both the dealer's `version` and each waived obligation's `version` advance by 1."

        Design: Corner/cross_cutting_complexity_layers/open_parts_return_count_reconciles_across_all_four_exits
        """
        world = build_three_return_obligations()
        dealer_id = world["dealer"]["id"]

        opening = get_dealer(dealer_id)
        assert opening["open_parts_return_count"] == 3

        receive_part(world["paid_return"]["id"], "2026-05-01")
        after_receipt = get_dealer(dealer_id)
        assert after_receipt["open_parts_return_count"] == 2
        assert after_receipt["version"] > opening["version"]

        deny_claim(
            world["submitted_claim"]["id"],
            denial_reason="Narrative does not support the repair.",
        )
        after_waiver = get_dealer(dealer_id)
        assert after_waiver["open_parts_return_count"] == 1
        assert after_waiver["version"] > after_receipt["version"]

        assert get_parts_return(world["paid_return"]["id"])["status"] == "RECEIVED"
        waived = parts_return_for_claim(world["submitted_claim"]["id"])
        assert get_parts_return(waived["id"])["status"] == "WAIVED"

    def test_12_the_sweep_debits_only_the_overdue_approved_obligation(self):
        """PRD §3.7: "The sweep considers every obligation still in `REQUESTED` whose `due_date` the logical clock has reached or passed, and whose linked claim is in `APPROVED`; it processes them in ascending order of their own `created_at`, so that the sequence of `balance_after_cents` values it writes onto the ledger is deterministic."
        PRD §3.7: "The sweep reports `swept_count`, the identifiers of the claims it debited as `debited_claim_ids`, and the summed positive debit as `total_debit_cents`."
        PRD §3.7: "First, the linked claim's `debited_amount_cents` is increased by the debit and its `payment_status` moves to `DEBITED`, from `PAID` if it had been paid and from `UNPAID` if it had not; a debit against an unpaid claim still books a positive ledger amount, and that claim can never be paid afterwards because payment requires `payment_status` to be `UNPAID`."
        PRD §3.7: "Rows in `RECEIVED`, `ANALYZED`, `NOT_RETURNED` and `WAIVED` are all excluded from that count."
        PRD §2.8: "Below 900 dollars the dealer is `ACTIVE`."

        Design: Corner/cross_cutting_complexity_layers/open_parts_return_count_reconciles_across_all_four_exits
        """
        world = build_three_return_obligations()
        dealer_id = world["dealer"]["id"]
        receive_part(world["paid_return"]["id"], "2026-05-01")
        deny_claim(
            world["submitted_claim"]["id"],
            denial_reason="Narrative does not support the repair.",
        )
        set_clock("2026-06-01T00:00:00Z")
        before = get_dealer(dealer_id)

        sweep = run_non_return_sweep()

        # Only the approved-but-unpaid claim still holds a REQUESTED obligation.
        assert sweep["swept_count"] == 1
        assert sweep["total_debit_cents"] == 20000
        assert sweep["debited_claim_ids"] == [world["unpaid_claim"]["id"]]

        after = get_dealer(dealer_id)
        assert after["open_parts_return_count"] == 0
        assert after["chargeback_balance_cents"] == 20000
        assert after["status"] == "ACTIVE"
        assert after["version"] > before["version"]

        debited = get_claim(world["unpaid_claim"]["id"])
        assert debited["payment_status"] == "DEBITED"
        assert debited["debited_amount_cents"] == 20000
        assert get_parts_return(world["paid_return"]["id"])["status"] == "RECEIVED"

    def test_13_a_late_return_does_not_decrement_the_counter_a_second_time(self):
        """PRD §3.7: "Receipt on an obligation already in `NOT_RETURNED` moves `NOT_RETURNED → RECEIVED`, stamps `received_date`, and sets `reversed_amount_cents` equal to the obligation's `debit_amount_cents`."
        PRD §3.7: "The dealer's `open_parts_return_count` is deliberately **not** decremented again here: the row already left `REQUESTED` when the sweep moved it to `NOT_RETURNED`, and decrementing twice would break the count invariant."
        PRD §3.7: "The linked claim moves `DEBITED → CREDIT_REINSTATED` with its `reinstated_amount_cents` increased by the reversed amount and its `version` advanced by 1."
        PRD §3.7: "A ledger row with `source_type` `LATE_RETURN_REVERSAL` is appended carrying the negative of the debit amount, so the dealer's `chargeback_balance_cents` falls by exactly what it rose by."

        Design: Corner/cross_cutting_complexity_layers/open_parts_return_count_reconciles_across_all_four_exits
        """
        world = build_three_return_obligations()
        dealer_id = world["dealer"]["id"]
        receive_part(world["paid_return"]["id"], "2026-05-01")
        deny_claim(
            world["submitted_claim"]["id"],
            denial_reason="Narrative does not support the repair.",
        )
        set_clock("2026-06-01T00:00:00Z")
        run_non_return_sweep()
        assert get_parts_return(world["unpaid_return"]["id"])["status"] == "NOT_RETURNED"

        late = receive_part(world["unpaid_return"]["id"], "2026-06-01")

        assert late["status"] == "RECEIVED"
        assert late["reversed_amount_cents"] == 20000
        dealer = get_dealer(dealer_id)
        # The count already fell when the sweep moved the row out of REQUESTED.
        assert dealer["open_parts_return_count"] == 0
        assert dealer["chargeback_balance_cents"] == 0
        assert dealer["status"] == "ACTIVE"

        reinstated = get_claim(world["unpaid_claim"]["id"])
        assert reinstated["payment_status"] == "CREDIT_REINSTATED"
        assert reinstated["reinstated_amount_cents"] == 20000

        entries = list_ledger_entries(dealer_id, {"limit": 10, "offset": 0})
        assert len(entries) == 2
        reversals = [
            entry for entry in entries if entry["source_type"] == "LATE_RETURN_REVERSAL"
        ]
        assert len(reversals) == 1
        assert reversals[0]["amount_cents"] == -20000
        assert reversals[0]["balance_after_cents"] == 0
