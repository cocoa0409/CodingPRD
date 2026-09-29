"""Intake, petition, audit and money-path validation rules and their rejection order."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    adjudicate_claim_payload,
    api_client,
    approve_claim,
    create_audit_finding_payload,
    create_audit_payload,
    create_claim_payload,
    create_dealer,
    create_labor_operation,
    create_labor_rate_request_payload,
    create_part,
    create_vehicle,
    decide_goodwill_authorization_payload,
    deny_claim,
    get_claim,
    get_dealer,
    get_goodwill,
    get_parts_return,
    list_claim_edits,
    make_dealer_warranty_admin_headers,
    parts_return_for_claim,
    pay_claim,
    raise_goodwill,
    run_non_return_sweep,
    schedule_audit,
    set_clock,
    setup_reference_data,
    start_audit,
    submit_claim,
    validate_error,
    validate_paginated,
    validate_success,
    void_claim,
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

HVAC_PART = {
    "part_number": "CAB-FLT-1",
    "description": "Cabin air filter",
    "dealer_net_cents": 5000,
    "failure_group": "HVAC",
    "return_required": False,
    "retention_days": 0,
}

NO_PART_OPERATION = {
    "op_code": "NP-100",
    "description": "Software reflash, no parts",
    "standard_time_hours": 0.5,
    "max_time_hours": 1.0,
    "category": "BASIC",
    "requires_causal_part": False,
    "causal_failure_group": None,
    "overlap_group": "REFLASH",
}

VEHICLE_ONE = {
    "vin": "VIN00000000000001",
    "model_year": 2024,
    "warranty_start_date": "2024-01-15",
    "in_service_odometer": 0,
    "basic_months": 36,
    "basic_miles": 36000,
    "powertrain_months": 60,
    "powertrain_miles": 60000,
}

VEHICLE_TWO = {**VEHICLE_ONE, "vin": "VIN00000000000002", "warranty_start_date": "2024-02-15"}

NARRATIVE = {
    "complaint_text": "Customer reports brake squeal at low speed.",
    "cause_text": "Front brake pads worn beyond specification.",
    "correction_text": "Replaced front brake pads and verified normal braking.",
}

BRAKE_CLAIM = {
    "repair_order_number": "RO-1001",
    "repair_date": "2026-04-10",
    "odometer_at_repair": 20000,
    "claimed_labor_hours": 1.5,
    "claimed_parts_qty": 3,
    **NARRATIVE,
}


def build_brake_world():
    """A CA dealer with one covered vehicle, one brake operation and one returnable part."""
    set_clock("2026-05-01T00:00:00Z")
    return setup_reference_data(
        profile_overrides=CA_PROFILE,
        dealer_overrides=D1_TERMS,
        vehicle_overrides=VEHICLE_ONE,
        operation_overrides=BRAKE_OPERATION,
        part_overrides=BRAKE_PART,
    )


def build_brake_world_with_claim():
    """The brake world plus one accepted claim on repair order RO-1001."""
    world = build_brake_world()
    world["claim"] = submit_claim(world, **BRAKE_CLAIM)
    assert world["claim"]["status"] == "SUBMITTED"
    return world


def brake_claim_payload(world, **overrides):
    """A claim body against the world's reference data, defaulting to the RO-1001 repair."""
    part = world.get("part")
    fields = {
        "dealer_id": world["dealer"]["id"],
        "vehicle_id": world["vehicle"]["id"],
        "labor_operation_id": world["operation"]["id"],
        "causal_part_id": part["id"] if part is not None else None,
        **BRAKE_CLAIM,
        **overrides,
    }
    return create_claim_payload(**fields)


def claim_count_for(dealer_id):
    """How many claims the dealer owns, read back through the operator listing."""
    rows, meta = validate_paginated(
        api_client.list_claims(ADMIN, params={"dealer_id": dealer_id})
    )
    return meta["total_count"]


class TestDuplicateRepairOrderNumber:
    def test_01_a_live_claim_holds_its_repair_order_number_against_a_second_filing(self):
        """PRD §3.3: "First, no other *live* claim of the same dealer may already carry the same `repair_order_number`, where live means the claim's `status` is `SUBMITTED`, `SUSPENDED` or `APPROVED`; a collision is `ERR_DUPLICATE_REPAIR_ORDER`."

        Design: Corner/validations/duplicate_repair_order_on_a_live_claim_violation_to_error
        """
        world = build_brake_world_with_claim()
        second_vehicle = create_vehicle(**VEHICLE_TWO)

        response = api_client.create_claim(
            brake_claim_payload(
                world,
                vehicle_id=second_vehicle["id"],
                repair_date="2026-01-10",
                odometer_at_repair=18000,
            ),
            world["dealer_headers"],
        )

        validate_error(response, ApiErrorId.ERR_DUPLICATE_REPAIR_ORDER)
        assert claim_count_for(world["dealer"]["id"]) == 1

    def test_02_voiding_the_holder_frees_the_repair_order_number_for_reuse(self):
        """PRD §3.3: "Claims that have reached `DENIED` or `VOID` are dead and never collide."
        PRD §3.6: "A claim in `SUBMITTED` or `SUSPENDED` may be voided freely; a claim in `APPROVED` may be voided only while its `payment_status` is still `UNPAID`."

        Design: Corner/validations/duplicate_repair_order_on_a_live_claim_violation_to_error
        """
        world = build_brake_world_with_claim()
        second_vehicle = create_vehicle(**VEHICLE_TWO)

        voided = void_claim(world["claim"]["id"])
        assert voided["status"] == "VOID"

        response = api_client.create_claim(
            brake_claim_payload(
                world,
                vehicle_id=second_vehicle["id"],
                repair_date="2026-01-10",
                odometer_at_repair=18000,
            ),
            world["dealer_headers"],
        )

        reused = validate_success(response, 201)
        assert reused["repair_order_number"] == "RO-1001"
        assert reused["status"] == "SUBMITTED"
        assert reused["vehicle_id"] == second_vehicle["id"]
        assert reused["id"] != world["claim"]["id"]


class TestRepairNarrativeFloor:
    @pytest.mark.parametrize(
        "field,value",
        [
            ("complaint_text", "Squeal."),
            ("cause_text", "Worn."),
            ("correction_text", "Fixed."),
            ("correction_text", "     Fixed.     "),
        ],
    )
    def test_03_a_narrative_field_under_ten_characters_is_refused(self, field, value):
        """PRD §3.3: "Each of `complaint_text`, `cause_text` and `correction_text` must be present and, after leading and trailing whitespace is trimmed, must be at least ten characters long."
        PRD §3.3: "Any one of them falling short yields `ERR_NARRATIVE_INCOMPLETE`."

        Design: Corner/validations/narrative_below_min_chars_violation_to_error
        """
        world = build_brake_world()

        response = api_client.create_claim(
            brake_claim_payload(world, **{field: value}), world["dealer_headers"]
        )

        validate_error(response, ApiErrorId.ERR_NARRATIVE_INCOMPLETE)
        assert claim_count_for(world["dealer"]["id"]) == 0


class TestThinCorrectionTextIsAdvisoryOnly:
    def test_04_a_short_correction_text_over_the_floor_is_accepted_with_a_warning(self):
        """PRD §3.4: "A `NARRATIVE_THIN` edit fires when `correction_text` is strictly shorter than twenty characters — note that this is a separate and stricter test than the ten-character narrative floor of §3.3, applies to the correction text alone, and is merely advisory."
        PRD §3.4: "A `REPEAT_REPAIR` edit fires when a qualifying prior claim exists, and records that prior claim's identifier in `conflicting_claim_id`; on every other edit code `conflicting_claim_id` is null. Both carry `severity` `WARN`."
        PRD §3.4: "`suspend_edit_count` is then set to the number of edits just appended whose `severity` is `SUSPEND`, and the claim's `status` follows directly: `SUSPENDED` when that count is greater than zero, `SUBMITTED` when it is zero."
        PRD §3.4: "Each row records the `claim_id` it belongs to, the `edit_code` that fired, the `severity` that code carries, a human-readable `detail` naming the threshold that was crossed, a `resolved_at` stamp that stays null while the edit is open, and — for one code only — a `conflicting_claim_id`."

        Design: Corner/validations/narrative_thin_warn_edit_satisfaction_to_pass
        """
        world = build_brake_world()

        # Fourteen characters: over the ten-character floor, under the twenty-character
        # advisory threshold.
        response = api_client.create_claim(
            brake_claim_payload(world, correction_text="Replaced pads."),
            world["dealer_headers"],
        )

        claim = validate_success(response, 201)
        assert claim["status"] == "SUBMITTED"
        assert claim["suspend_edit_count"] == 0
        assert claim["provisional_total_cents"] == 124782

        edits = list_claim_edits(claim["id"])
        assert len(edits) == 1
        assert edits[0]["edit_code"] == "NARRATIVE_THIN"
        assert edits[0]["severity"] == "WARN"
        assert edits[0]["resolved_at"] is None
        assert edits[0]["conflicting_claim_id"] is None


class TestCausalPartConfiguration:
    def test_05_an_operation_that_requires_a_part_refuses_a_claim_without_one(self):
        """PRD §3.3: "When the cited labor operation has `requires_causal_part` true, the claim must supply a `causal_part_id`, that part's `failure_group` must be exactly equal to the operation's `causal_failure_group`, and `claimed_parts_qty` must be at least 1."
        PRD §3.3: "All four of those failures — missing part, mismatched failure group, zero quantity where a part is required, and an unwanted part — report `ERR_CAUSAL_PART_REQUIRED`."

        Design: Corner/validations/causal_part_configuration_conditional_validation_three_ways
        """
        world = build_brake_world()

        payload = brake_claim_payload(world)
        payload.pop("causal_part_id")
        payload["claimed_parts_qty"] = 0

        response = api_client.create_claim(payload, world["dealer_headers"])

        validate_error(response, ApiErrorId.ERR_CAUSAL_PART_REQUIRED)
        assert claim_count_for(world["dealer"]["id"]) == 0

    def test_06_a_part_from_the_wrong_failure_group_is_not_the_causal_part(self):
        """PRD §3.3: "When the cited labor operation has `requires_causal_part` true, the claim must supply a `causal_part_id`, that part's `failure_group` must be exactly equal to the operation's `causal_failure_group`, and `claimed_parts_qty` must be at least 1."
        PRD §3.3: "All four of those failures — missing part, mismatched failure group, zero quantity where a part is required, and an unwanted part — report `ERR_CAUSAL_PART_REQUIRED`."

        Design: Corner/validations/causal_part_configuration_conditional_validation_three_ways
        """
        world = build_brake_world()
        foreign_part = create_part(**HVAC_PART)
        assert foreign_part["failure_group"] != world["operation"]["causal_failure_group"]

        response = api_client.create_claim(
            brake_claim_payload(
                world, causal_part_id=foreign_part["id"], claimed_parts_qty=1
            ),
            world["dealer_headers"],
        )

        validate_error(response, ApiErrorId.ERR_CAUSAL_PART_REQUIRED)
        assert claim_count_for(world["dealer"]["id"]) == 0

    def test_07_an_operation_that_needs_no_part_refuses_an_unwanted_one(self):
        """PRD §3.3: "When the operation has `requires_causal_part` false, supplying a `causal_part_id` at all is a violation."
        PRD §3.3: "All four of those failures — missing part, mismatched failure group, zero quantity where a part is required, and an unwanted part — report `ERR_CAUSAL_PART_REQUIRED`."

        Design: Corner/validations/causal_part_configuration_conditional_validation_three_ways
        """
        world = build_brake_world()
        partless_operation = create_labor_operation(**NO_PART_OPERATION)
        assert partless_operation["requires_causal_part"] is False

        response = api_client.create_claim(
            brake_claim_payload(
                world,
                labor_operation_id=partless_operation["id"],
                claimed_labor_hours=0.5,
                claimed_parts_qty=1,
            ),
            world["dealer_headers"],
        )

        validate_error(response, ApiErrorId.ERR_CAUSAL_PART_REQUIRED)
        assert claim_count_for(world["dealer"]["id"]) == 0

    def test_08_a_matching_part_with_a_positive_quantity_satisfies_the_rule(self):
        """PRD §3.3: "When the cited labor operation has `requires_causal_part` true, the claim must supply a `causal_part_id`, that part's `failure_group` must be exactly equal to the operation's `causal_failure_group`, and `claimed_parts_qty` must be at least 1."

        Design: Corner/validations/causal_part_configuration_conditional_validation_three_ways
        """
        world = build_brake_world()

        response = api_client.create_claim(
            brake_claim_payload(world), world["dealer_headers"]
        )

        claim = validate_success(response, 201)
        assert claim["causal_part_id"] == world["part"]["id"]
        assert claim["claimed_parts_qty"] == 3
        assert claim["coverage_type"] == "BASIC"
        assert claim["status"] == "SUBMITTED"


def rate_request_payload(dealer, **overrides):
    """A retail-sample petition body whose figures all sit inside the CA statute."""
    fields = {
        "requested_labor_rate_cents": 17600,
        "requested_parts_markup_pct": 0.30,
        "sample_repair_order_count": 5,
        "sample_median_rate_cents": 17600,
        "effective_date": "2026-09-01",
        "expected_dealer_version": dealer["version"],
    }
    fields.update(overrides)
    return create_labor_rate_request_payload(dealer_id=dealer["id"], **fields)


def rate_request_count_for(dealer_id):
    rows, meta = validate_paginated(
        api_client.list_labor_rate_requests(ADMIN, params={"dealer_id": dealer_id})
    )
    return meta["total_count"]


class TestRetailSampleSufficiencyPrecedesTheCeiling:
    def test_09_a_sample_below_the_statutory_minimum_is_refused(self):
        """PRD §3.2: "In a retail-sample state the petition must cite at least as many repair orders as the statute's `min_sample_repair_orders` and must supply a non-null median rate; falling short of either yields `ERR_INSUFFICIENT_RATE_SAMPLE`."

        Design: Corner/validations/rate_sample_floor_runs_before_statutory_ceiling_cascading_validation
        """
        world = build_brake_world()

        response = api_client.create_labor_rate_request(
            rate_request_payload(world["dealer"], sample_repair_order_count=4),
            world["dealer_headers"],
        )

        validate_error(response, ApiErrorId.ERR_INSUFFICIENT_RATE_SAMPLE)
        assert rate_request_count_for(world["dealer"]["id"]) == 0

    def test_10_a_missing_median_is_refused_before_the_ceiling_can_be_computed(self):
        """PRD §3.2: "In a retail-sample state the petition must cite at least as many repair orders as the statute's `min_sample_repair_orders` and must supply a non-null median rate; falling short of either yields `ERR_INSUFFICIENT_RATE_SAMPLE`."
        PRD §3.2: "That check runs before the ceiling is computed, because the ceiling consumes the median."
        PRD §2.11: "Retail-sample sufficiency is checked before the statutory ceiling is computed, because the ceiling formula consumes the very sample figure that check validates."

        Design: Corner/validations/rate_sample_floor_runs_before_statutory_ceiling_cascading_validation
        """
        world = build_brake_world()

        # The requested rate is also far above any ceiling this statute could yield, so
        # the sample defect and the ceiling defect are both present in one body.
        payload = rate_request_payload(
            world["dealer"], sample_repair_order_count=6, requested_labor_rate_cents=19000
        )
        payload.pop("sample_median_rate_cents")

        response = api_client.create_labor_rate_request(payload, world["dealer_headers"])

        validate_error(response, ApiErrorId.ERR_INSUFFICIENT_RATE_SAMPLE)
        assert rate_request_count_for(world["dealer"]["id"]) == 0

    def test_11_a_sufficient_sample_pins_the_ceiling_from_the_step_up_floor(self):
        """PRD §3.2: "The ceiling itself is written into `statutory_ceiling_cents` at creation and never recomputed thereafter."
        PRD §3.2: "Under the retail-sample method the server first works out a step-up floor by taking the dealer's currently approved hourly rate, increasing it by twenty-five percent, and rounding the product half up to whole cents; it then takes the greater of the cited sample median and that step-up floor; and it finally takes the lesser of that result and the statute's absolute `max_labor_rate_cents`."
        PRD §3.2: "The request opens in `SUBMITTED` with `deemed_approved` false, and the petitioning dealer's `version` advances by 1."

        Design: Corner/validations/rate_sample_floor_runs_before_statutory_ceiling_cascading_validation
        """
        world = build_brake_world()

        response = api_client.create_labor_rate_request(
            rate_request_payload(world["dealer"]), world["dealer_headers"]
        )

        request = validate_success(response, 201)
        assert request["status"] == "SUBMITTED"
        assert request["deemed_approved"] is False
        # round_half_up(13750 * 1.25) = 17188, the sample median 17600 is greater, and
        # 17600 is below the statutory maximum of 19500.
        assert request["statutory_ceiling_cents"] == 17600
        assert request["requested_labor_rate_cents"] == 17600
        assert get_dealer(world["dealer"]["id"])["version"] == world["dealer"]["version"] + 1


class TestRequestedMarkupAgainstTheStateCap:
    def test_12_a_markup_above_the_state_cap_is_refused(self):
        """PRD §3.2: "A requested markup is judged separately and directly against the statute: equal to `markup_cap_pct` passes, strictly above it fails with `ERR_MARKUP_ABOVE_STATE_CAP`."

        Design: Corner/validations/parts_markup_above_state_cap_violation_to_error
        """
        world = build_brake_world()

        response = api_client.create_labor_rate_request(
            rate_request_payload(world["dealer"], requested_parts_markup_pct=0.35),
            world["dealer_headers"],
        )

        validate_error(response, ApiErrorId.ERR_MARKUP_ABOVE_STATE_CAP)
        assert rate_request_count_for(world["dealer"]["id"]) == 0

    def test_13_a_markup_equal_to_the_state_cap_passes_and_spares_the_enrolled_figure(self):
        """PRD §3.2: "A requested markup is judged separately and directly against the statute: equal to `markup_cap_pct` passes, strictly above it fails with `ERR_MARKUP_ABOVE_STATE_CAP`."
        PRD §3.1: "A grandfathered markup captured at onboarding may legitimately sit above the state's cap; the cap is applied when a claim is finally adjudicated, and again when a petition is decided, but never retroactively to the enrolled figure."

        Design: Corner/validations/parts_markup_above_state_cap_violation_to_error
        """
        world = build_brake_world()

        response = api_client.create_labor_rate_request(
            rate_request_payload(world["dealer"], requested_parts_markup_pct=0.30),
            world["dealer_headers"],
        )

        request = validate_success(response, 201)
        assert float(request["requested_parts_markup_pct"]) == pytest.approx(0.30, abs=0.01)
        assert request["status"] == "SUBMITTED"
        # The dealer keeps its enrolled 0.40 markup until a decision republishes terms.
        dealer = get_dealer(world["dealer"]["id"])
        assert float(dealer["approved_parts_markup_pct"]) == pytest.approx(0.40, abs=0.01)
        assert dealer["approved_labor_rate_cents"] == 13750


TRANS_OPERATION = {
    "op_code": "DS-100",
    "description": "Transmission valve body replacement",
    "standard_time_hours": 1.0,
    "max_time_hours": 1.5,
    "category": "POWERTRAIN",
    "requires_causal_part": True,
    "causal_failure_group": "TRANS",
    "overlap_group": "TRANS",
}

TRANS_PART = {
    "part_number": "TRN-VB-1",
    "description": "Transmission valve body",
    "dealer_net_cents": 220200,
    "failure_group": "TRANS",
    "return_required": True,
    "retention_days": 30,
}

MISC_OPERATION = {
    "op_code": "DS-200",
    "description": "Interior trim adjustment",
    "standard_time_hours": 1.0,
    "max_time_hours": 1.5,
    "category": "BASIC",
    "requires_causal_part": False,
    "causal_failure_group": None,
    "overlap_group": "DS_MISC",
}

SUSPENDED_VEHICLE = {
    "vin": "VIN0000000000SUS1",
    "model_year": 2025,
    "warranty_start_date": "2025-01-15",
    "in_service_odometer": 0,
    "basic_months": 36,
    "basic_miles": 36000,
    "powertrain_months": 60,
    "powertrain_miles": 60000,
}

TRANS_NARRATIVE = {
    "complaint_text": "Customer reports harsh upshift under load.",
    "cause_text": "Valve body solenoid stuck intermittently.",
    "correction_text": "Replaced the transmission valve body and road tested.",
}

MISC_NARRATIVE = {
    "complaint_text": "Customer reports a loose interior trim panel.",
    "cause_text": "Retaining clip had backed out of its socket.",
    "correction_text": "Reseated the trim panel and replaced the clip.",
}


def build_suspended_dealer_world():
    """A dealer driven to SUSPENDED by an unreturned part, with a sibling claim on hold.

    The transmission claim is approved and paid for 285,250 cents, its return obligation
    is then left unmet past its due date, and the non-return sweep debits the whole
    claim back — which crosses the 200,000-cent suspension band and drags the dealer's
    other in-flight claim into a posture hold.
    """
    set_clock("2026-05-01T00:00:00Z")
    world = setup_reference_data(
        profile_overrides=CA_PROFILE,
        dealer_overrides={
            "dealer_code": "DS",
            "name": "Suspended Motors",
            "vehicles_in_operation": 100,
            "initial_labor_rate_cents": 10000,
            "initial_parts_markup_pct": 0.25,
        },
        vehicle_overrides=SUSPENDED_VEHICLE,
        operation_overrides=TRANS_OPERATION,
        part_overrides=TRANS_PART,
    )
    second_vehicle = create_vehicle(
        **{**SUSPENDED_VEHICLE, "vin": "VIN0000000000SUS2"}
    )
    misc_operation = create_labor_operation(**MISC_OPERATION)

    trans_claim = submit_claim(
        world,
        repair_order_number="RO-DS-1",
        repair_date="2026-04-10",
        odometer_at_repair=40000,
        claimed_labor_hours=1.0,
        claimed_parts_qty=1,
        **TRANS_NARRATIVE,
    )
    assert trans_claim["coverage_type"] == "POWERTRAIN"
    assert trans_claim["provisional_total_cents"] == 285250
    trans_claim = approve_claim(
        trans_claim["id"], approved_labor_hours=1.0, approved_parts_qty=1
    )
    assert trans_claim["approved_total_cents"] == 285250
    trans_claim = pay_claim(trans_claim["id"])
    assert trans_claim["payment_status"] == "PAID"

    sibling_claim = submit_claim(
        {
            "dealer": world["dealer"],
            "vehicle": second_vehicle,
            "operation": misc_operation,
            "part": None,
            "dealer_headers": world["dealer_headers"],
        },
        repair_order_number="RO-DS-2",
        repair_date="2026-04-12",
        odometer_at_repair=30000,
        claimed_labor_hours=1.0,
        claimed_parts_qty=0,
        **MISC_NARRATIVE,
    )
    assert sibling_claim["status"] == "SUBMITTED"

    set_clock("2026-06-01T00:00:00Z")
    sweep = run_non_return_sweep()
    assert sweep["total_debit_cents"] == 285250

    world["dealer"] = get_dealer(world["dealer"]["id"])
    assert world["dealer"]["status"] == "SUSPENDED"
    world["second_vehicle"] = second_vehicle
    world["misc_operation"] = misc_operation
    world["trans_claim"] = get_claim(trans_claim["id"])
    world["sibling_claim"] = get_claim(sibling_claim["id"])
    return world


class TestSuspendedPostureBlocksMoneyPathsOnly:
    def test_14_a_suspended_dealer_can_neither_file_a_claim_nor_petition_for_a_rate(self):
        """PRD §2.8: "A balance of at least 200,000 cents — 2,000 dollars — puts the dealer in `SUSPENDED`."
        PRD §3.3: "Submission is refused while the dealer is `SUSPENDED`, with `ERR_DEALER_SUSPENDED`."
        PRD §3.2: "Filing is blocked outright while the petitioning dealer is `SUSPENDED`, with `ERR_DEALER_SUSPENDED`."

        Design: Corner/validations/suspended_dealer_blocks_money_paths_only_cross_entity_validation
        """
        world = build_suspended_dealer_world()
        assert world["dealer"]["chargeback_balance_cents"] == 285250
        assert world["dealer"]["open_parts_return_count"] == 0

        third_vehicle = create_vehicle(**{**SUSPENDED_VEHICLE, "vin": "VIN0000000000SUS3"})
        submission = api_client.create_claim(
            create_claim_payload(
                dealer_id=world["dealer"]["id"],
                vehicle_id=third_vehicle["id"],
                labor_operation_id=world["misc_operation"]["id"],
                repair_order_number="RO-DS-3",
                repair_date="2026-05-20",
                odometer_at_repair=31000,
                claimed_labor_hours=1.0,
                claimed_parts_qty=0,
                **MISC_NARRATIVE,
            ),
            world["dealer_headers"],
        )
        validate_error(submission, ApiErrorId.ERR_DEALER_SUSPENDED)

        petition = api_client.create_labor_rate_request(
            rate_request_payload(world["dealer"]), world["dealer_headers"]
        )
        validate_error(petition, ApiErrorId.ERR_DEALER_SUSPENDED)

        assert get_dealer(world["dealer"]["id"])["status"] == "SUSPENDED"

    def test_15_a_posture_hold_survives_adjudication_but_never_blocks_an_audit(self):
        """PRD §3.7: "Fourth, if that recomputation put the dealer into `PROBATION` or `SUSPENDED`, every claim of that dealer currently in `SUBMITTED` is driven `SUBMITTED → SUSPENDED`: each such claim receives an appended edit whose `edit_code` is `DEALER_POSTURE_HOLD` and whose `severity` is `SUSPEND`, has its `suspend_edit_count` incremented by 1, and has its `version` advanced by 1."
        PRD §3.6: "A claim holding an open edit whose `edit_code` is `DEALER_POSTURE_HOLD` cannot be adjudicated away: that request is refused with `ERR_CLAIM_STILL_SUSPENDED`, because a dealer-posture hold is lifted only by the dealer's balance recovering, never by an adjudicator's signature."
        PRD §2.9: "A second audit over a different, non-overlapping period is a perfectly legitimate operation that no state rule would block, so this check is what forces the scheduler to re-read the dealer's posture and `audit_hold` before committing another audit against it."

        Design: Corner/validations/suspended_dealer_blocks_money_paths_only_cross_entity_validation
        """
        world = build_suspended_dealer_world()
        sibling = world["sibling_claim"]
        assert sibling["status"] == "SUSPENDED"
        assert sibling["suspend_edit_count"] == 1
        hold_edits = [
            edit for edit in list_claim_edits(sibling["id"])
            if edit["edit_code"] == "DEALER_POSTURE_HOLD"
        ]
        assert len(hold_edits) == 1
        assert hold_edits[0]["severity"] == "SUSPEND"

        refused = api_client.adjudicate_claim(
            sibling["id"],
            adjudicate_claim_payload(
                decision="APPROVE", approved_labor_hours=1.0, approved_parts_qty=0
            ),
            ADJUDICATOR,
        )
        validate_error(refused, ApiErrorId.ERR_CLAIM_STILL_SUSPENDED)
        assert get_claim(sibling["id"])["status"] == "SUSPENDED"

        # Auditing the dealer is not a money path: the suspension does not close it.
        scheduled = api_client.create_audit(
            create_audit_payload(
                dealer_id=world["dealer"]["id"],
                expected_dealer_version=world["dealer"]["version"],
                period_start="2026-01-01",
                period_end="2026-05-01",
                sample_size=2,
            ),
            AUDIT_MANAGER,
        )
        audit = validate_success(scheduled, 201)
        assert audit["status"] == "SCHEDULED"
        assert audit["dealer_id"] == world["dealer"]["id"]
        assert audit["total_chargeback_cents"] == 0


def build_overdue_return_world():
    """An approved brake claim whose return obligation has run past its due date."""
    world = build_brake_world_with_claim()
    world["claim"] = approve_claim(
        world["claim"]["id"], approved_labor_hours=1.5, approved_parts_qty=3
    )
    assert world["claim"]["approved_total_cents"] == 117342
    obligation = parts_return_for_claim(world["claim"]["id"])
    assert obligation["status"] == "REQUESTED"
    # The obligation was raised at 2026-05-01 with a thirty-day retention window.
    assert obligation["due_date"][:10] == "2026-05-31"
    set_clock("2026-06-01T00:00:00Z")
    world["parts_return"] = obligation
    return world


class TestPaymentAgainstAnOverdueReturnObligation:
    def test_16_an_overdue_return_obligation_blocks_payment(self):
        """PRD §3.6: "And where the claim's causal part requires a return, the claim cannot be paid while that obligation is still in `REQUESTED` and the logical clock has already reached or passed its `due_date`; that case is `ERR_PARTS_RETURN_OVERDUE`, and the non-return sweep must be run first so that the debit lands before any payment does."
        PRD §2.6: "A parts-return request's `due_date` is its own `created_at` advanced by the causal part's `retention_days` days."

        Design: Corner/validations/payment_blocked_by_overdue_parts_return_temporal_validation
        """
        world = build_overdue_return_world()

        response = api_client.pay_claim(world["claim"]["id"], ADMIN)

        validate_error(response, ApiErrorId.ERR_PARTS_RETURN_OVERDUE)
        claim = get_claim(world["claim"]["id"])
        assert claim["status"] == "APPROVED"
        assert claim["payment_status"] == "UNPAID"

    def test_17_the_sweep_debits_the_whole_claim_and_leaves_it_unpayable(self):
        """PRD §3.7: "Each swept obligation moves `REQUESTED → NOT_RETURNED`, has `debit_amount_cents` set to the linked claim's entire `approved_total_cents` — a non-return costs the dealer the whole claim, labor included, not merely the parts — decrements the dealer's `open_parts_return_count` by 1, and advances its own `version` by 1."
        PRD §3.7: "First, the linked claim's `debited_amount_cents` is increased by the debit and its `payment_status` moves to `DEBITED`, from `PAID` if it had been paid and from `UNPAID` if it had not; a debit against an unpaid claim still books a positive ledger amount, and that claim can never be paid afterwards because payment requires `payment_status` to be `UNPAID`."
        PRD §3.6: "The claim's `status` must be `APPROVED` and its `payment_status` must be `UNPAID`, or the request is refused with `ERR_CLAIM_NOT_PAYABLE`; its `suspend_edit_count` must be 0."

        Design: Corner/validations/payment_blocked_by_overdue_parts_return_temporal_validation
        """
        world = build_overdue_return_world()

        run_non_return_sweep()

        obligation = get_parts_return(world["parts_return"]["id"])
        assert obligation["status"] == "NOT_RETURNED"
        assert obligation["debit_amount_cents"] == 117342

        response = api_client.pay_claim(world["claim"]["id"], ADMIN)
        validate_error(response, ApiErrorId.ERR_CLAIM_NOT_PAYABLE)

        claim = get_claim(world["claim"]["id"])
        assert claim["status"] == "APPROVED"
        assert claim["payment_status"] == "DEBITED"
        assert claim["debited_amount_cents"] == 117342
        assert get_dealer(world["dealer"]["id"])["open_parts_return_count"] == 0


class TestDealerScopingAcrossDealerships:
    def test_18_one_dealership_cannot_reach_another_dealerships_resources(self):
        """PRD §2.1: "When `X-User-Role` is `DealerWarrantyAdmin`, `X-User-ID` is the `id` of the acting dealership's `Dealer` row; ownership checks on any resource that references a `Dealer` compare the resource's dealer foreign key to `X-User-ID`."
        PRD §2.1: "Dealer scoping is enforced on ten operations: reading one dealer, listing that dealer's ledger entries, reading that dealer's expense analytics, submitting a claim, reading one claim, resubmitting a claim, listing a claim's edits, reading one audit, filing an appeal against an audit, and reading one appeal."
        PRD §2.1: "In each case the dealer reached from the target resource — the `Dealer` row itself, a claim's `dealer_id`, an audit's `dealer_id`, an appeal's `filed_by_dealer_id`, or the `dealer_id` of the claim behind a parts-return request — must equal `X-User-ID`, and on claim submission and appeal filing the `dealer_id` or `filed_by_dealer_id` the body would establish must equal `X-User-ID` as well."

        Design: Corner/validations/dealer_scope_cross_entity_validation_on_another_dealers_resources
        """
        world = build_brake_world_with_claim()
        other_dealer = create_dealer(
            world["profile"]["id"],
            dealer_code="D2",
            name="Dealer Two",
            vehicles_in_operation=80,
            initial_labor_rate_cents=11000,
            initial_parts_markup_pct=0.25,
        )
        intruder = make_dealer_warranty_admin_headers(other_dealer["id"])

        validate_error(
            api_client.get_claim(world["claim"]["id"], intruder),
            ApiErrorId.ERR_DEALER_SCOPE_VIOLATION,
        )
        validate_error(
            api_client.list_dealer_ledger_entries(world["dealer"]["id"], intruder),
            ApiErrorId.ERR_DEALER_SCOPE_VIOLATION,
        )
        validate_error(
            api_client.list_claim_edits(world["claim"]["id"], intruder),
            ApiErrorId.ERR_DEALER_SCOPE_VIOLATION,
        )

        # The body's dealer_id is scoped too, even though every id in it exists.
        second_vehicle = create_vehicle(**VEHICLE_TWO)
        validate_error(
            api_client.create_claim(
                brake_claim_payload(
                    world,
                    vehicle_id=second_vehicle["id"],
                    repair_order_number="RO-2001",
                    repair_date="2026-01-10",
                    odometer_at_repair=18000,
                ),
                intruder,
            ),
            ApiErrorId.ERR_DEALER_SCOPE_VIOLATION,
        )

    def test_19_the_owning_dealership_reads_its_own_claim(self):
        """PRD §2.1: "When `X-User-Role` is `DealerWarrantyAdmin`, `X-User-ID` is the `id` of the acting dealership's `Dealer` row; ownership checks on any resource that references a `Dealer` compare the resource's dealer foreign key to `X-User-ID`."

        Design: Corner/validations/dealer_scope_cross_entity_validation_on_another_dealers_resources
        """
        world = build_brake_world_with_claim()

        response = api_client.get_claim(world["claim"]["id"], world["dealer_headers"])

        claim = validate_success(response, 200)
        assert claim["id"] == world["claim"]["id"]
        assert claim["dealer_id"] == world["dealer"]["id"]


AUDIT_OPERATION = {
    "op_code": "AUD-100",
    "description": "Suspension bushing replacement",
    "standard_time_hours": 3.0,
    "max_time_hours": 4.0,
    "category": "BASIC",
    "requires_causal_part": False,
    "causal_failure_group": None,
    "overlap_group": "AUDIT_OPS",
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

AUDIT_NARRATIVE = {
    "complaint_text": "Customer reports a clunk from the front suspension.",
    "cause_text": "Lower control arm bushings were split.",
    "correction_text": "Replaced both lower control arm bushings.",
}


def build_audit_in_field_world():
    """A dealer under an in-field audit over [2026-01-01, 2026-04-01), with three paid
    claims: one inside the period, one before it, and one belonging to another dealer."""
    set_clock("2026-05-01T00:00:00Z")
    world = setup_reference_data(
        profile_overrides=CA_PROFILE,
        dealer_overrides={
            "dealer_code": "DA",
            "name": "Audited Motors",
            "vehicles_in_operation": 100,
            "initial_labor_rate_cents": 10000,
            "initial_parts_markup_pct": 0.25,
        },
        vehicle_overrides=AUDIT_VEHICLE,
        operation_overrides=AUDIT_OPERATION,
        with_part=False,
    )
    early_vehicle = create_vehicle(**{**AUDIT_VEHICLE, "vin": "VIN0000000000AUD2"})
    other_vehicle = create_vehicle(**{**AUDIT_VEHICLE, "vin": "VIN0000000000OTH1"})

    def paid_claim(dealer, headers, vehicle, repair_order_number, repair_date, hours):
        claim = submit_claim(
            {
                "dealer": dealer,
                "vehicle": vehicle,
                "operation": world["operation"],
                "part": None,
                "dealer_headers": headers,
            },
            repair_order_number=repair_order_number,
            repair_date=repair_date,
            odometer_at_repair=20000,
            claimed_labor_hours=hours,
            claimed_parts_qty=0,
            **AUDIT_NARRATIVE,
        )
        claim = approve_claim(claim["id"], approved_labor_hours=hours, approved_parts_qty=0)
        return pay_claim(claim["id"])

    world["sampled_claim"] = paid_claim(
        world["dealer"], world["dealer_headers"], world["vehicle"], "RO-AUD-1", "2026-02-15", 2.0
    )
    world["early_claim"] = paid_claim(
        world["dealer"], world["dealer_headers"], early_vehicle, "RO-AUD-OLD", "2025-12-10", 1.0
    )

    other_dealer = create_dealer(
        world["profile"]["id"],
        dealer_code="DB",
        name="Neighbour Motors",
        vehicles_in_operation=90,
        initial_labor_rate_cents=10000,
        initial_parts_markup_pct=0.25,
    )
    other_headers = make_dealer_warranty_admin_headers(other_dealer["id"])
    world["other_dealer"] = other_dealer
    world["other_claim"] = paid_claim(
        other_dealer, other_headers, other_vehicle, "RO-OTH-1", "2026-02-20", 1.0
    )

    audit = schedule_audit(
        get_dealer(world["dealer"]["id"]),
        period_start="2026-01-01",
        period_end="2026-04-01",
        sample_size=1,
    )
    world["audit"] = start_audit(audit["id"])
    assert world["audit"]["status"] == "IN_FIELD"
    return world


class TestFindingEligibilityOfTheCitedClaim:
    def test_20_a_claim_repaired_before_the_period_cannot_be_cited(self):
        """PRD §3.8: "The cited claim must satisfy five conditions at once: it must belong to the audited dealer, its `status` must be `APPROVED`, its `payment_status` must be either `UNPAID` or `PAID`, its `repair_date` must lie inside the half-open audit period, and it must not already be cited by another finding of the same audit."
        PRD §3.8: "Any failure is `ERR_CLAIM_NOT_ELIGIBLE_FOR_FINDING`."
        PRD §3.8: "The window is half-open throughout the entire audit machinery: a claim belongs to the period when its `repair_date` is at or after `period_start` and strictly before `period_end`."

        Design: Corner/validations/finding_eligibility_is_a_four_way_cross_entity_check
        """
        world = build_audit_in_field_world()

        response = api_client.create_audit_finding(
            world["audit"]["id"],
            create_audit_finding_payload(
                claim_id=world["early_claim"]["id"], unsupported_amount_cents=5000
            ),
            FIELD_AUDITOR,
        )

        validate_error(response, ApiErrorId.ERR_CLAIM_NOT_ELIGIBLE_FOR_FINDING)

    def test_21_a_claim_belonging_to_another_dealer_cannot_be_cited(self):
        """PRD §3.8: "The cited claim must satisfy five conditions at once: it must belong to the audited dealer, its `status` must be `APPROVED`, its `payment_status` must be either `UNPAID` or `PAID`, its `repair_date` must lie inside the half-open audit period, and it must not already be cited by another finding of the same audit."
        PRD §3.8: "Any failure is `ERR_CLAIM_NOT_ELIGIBLE_FOR_FINDING`."

        Design: Corner/validations/finding_eligibility_is_a_four_way_cross_entity_check
        """
        world = build_audit_in_field_world()
        assert world["other_claim"]["repair_date"][:10] == "2026-02-20"

        response = api_client.create_audit_finding(
            world["audit"]["id"],
            create_audit_finding_payload(
                claim_id=world["other_claim"]["id"], unsupported_amount_cents=5000
            ),
            FIELD_AUDITOR,
        )

        validate_error(response, ApiErrorId.ERR_CLAIM_NOT_ELIGIBLE_FOR_FINDING)

    def test_22_an_eligible_claim_is_citable_exactly_once(self):
        """PRD §3.8: "The cited claim must satisfy five conditions at once: it must belong to the audited dealer, its `status` must be `APPROVED`, its `payment_status` must be either `UNPAID` or `PAID`, its `repair_date` must lie inside the half-open audit period, and it must not already be cited by another finding of the same audit."
        PRD §3.8: "A new finding opens in `OPEN` with `appeal_id` null; `OVERTURNED` and `UPHELD` are its terminal states."
        PRD §3.8: "Any failure is `ERR_CLAIM_NOT_ELIGIBLE_FOR_FINDING`."

        Design: Corner/validations/finding_eligibility_is_a_four_way_cross_entity_check
        """
        world = build_audit_in_field_world()

        accepted = api_client.create_audit_finding(
            world["audit"]["id"],
            create_audit_finding_payload(
                claim_id=world["sampled_claim"]["id"], unsupported_amount_cents=10000
            ),
            FIELD_AUDITOR,
        )
        finding = validate_success(accepted, 201)
        assert finding["status"] == "OPEN"
        assert finding["appeal_id"] is None
        assert finding["claim_id"] == world["sampled_claim"]["id"]
        assert finding["unsupported_amount_cents"] == 10000

        repeat = api_client.create_audit_finding(
            world["audit"]["id"],
            create_audit_finding_payload(
                claim_id=world["sampled_claim"]["id"], unsupported_amount_cents=2000
            ),
            FIELD_AUDITOR,
        )
        validate_error(repeat, ApiErrorId.ERR_CLAIM_NOT_ELIGIBLE_FOR_FINDING)

        rows, meta = validate_paginated(
            api_client.list_audit_findings(
                FIELD_AUDITOR, params={"audit_id": world["audit"]["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == finding["id"]


HVAC_OPERATION = {
    "op_code": "GW-200",
    "description": "Blower motor replacement",
    "standard_time_hours": 1.0,
    "max_time_hours": 1.5,
    "category": "BASIC",
    "requires_causal_part": True,
    "causal_failure_group": "HVAC",
    "overlap_group": "HVAC",
}

BLOWER_PART = {
    "part_number": "GW-P1",
    "description": "Blower motor assembly",
    "dealer_net_cents": 40000,
    "failure_group": "HVAC",
    "return_required": True,
    "retention_days": 30,
}

OUT_OF_WARRANTY_VEHICLE = {
    "vin": "VIN00000000000GW1",
    "model_year": 2023,
    "warranty_start_date": "2023-06-15",
    "in_service_odometer": 0,
    "basic_months": 36,
    "basic_miles": 36000,
    "powertrain_months": 60,
    "powertrain_miles": 60000,
}

GOODWILL_NARRATIVE = {
    "complaint_text": "Customer reports no airflow from the dash vents.",
    "cause_text": "Blower motor seized and drew locked-rotor current.",
    "correction_text": "Replaced the blower motor assembly and tested airflow.",
}


def build_uncovered_claim_world():
    """A claim 3,600 miles past its basic mileage limit, so its coverage_type is NONE."""
    set_clock("2026-05-20T00:00:00Z")
    world = setup_reference_data(
        profile_overrides=CA_PROFILE,
        dealer_overrides={
            "dealer_code": "D-GW",
            "name": "Goodwill Motors",
            "vehicles_in_operation": 100,
            "initial_labor_rate_cents": 10000,
            "initial_parts_markup_pct": 0.25,
        },
        vehicle_overrides=OUT_OF_WARRANTY_VEHICLE,
        operation_overrides=HVAC_OPERATION,
        part_overrides=BLOWER_PART,
    )
    world["claim"] = submit_claim(
        world,
        repair_order_number="RO-GW-1",
        repair_date="2026-05-14",
        odometer_at_repair=39600,
        claimed_labor_hours=1.0,
        claimed_parts_qty=1,
        **GOODWILL_NARRATIVE,
    )
    assert world["claim"]["coverage_type"] == "NONE"
    assert world["claim"]["status"] == "SUSPENDED"
    assert world["claim"]["provisional_total_cents"] == 60000
    return world


class TestGoodwillDecisionAgainstTheDecidingRolesLimit:
    def test_23_an_adjudicator_cannot_approve_above_its_own_pinned_limit(self):
        """PRD §3.5: "`adjudicator_limit_cents` is the lesser of the share cap and the adjudicator base authority of 50,000 cents (500 dollars) multiplied by the decay multiplier and rounded half up to whole cents."
        PRD §3.5: "A `PENDING` authorization may be decided by either a `ClaimAdjudicator` or an `AdjudicationManager`."
        PRD §3.5: "On approval the decider supplies `approved_amount_cents`, which must be strictly positive and must not exceed the ceiling that belongs to the deciding role — `adjudicator_limit_cents` when a `ClaimAdjudicator` decides, `manager_limit_cents` when an `AdjudicationManager` decides — with `ERR_GOODWILL_LIMIT_EXCEEDED` on breach."

        Design: Corner/validations/goodwill_decision_amount_above_the_deciding_roles_limit
        """
        world = build_uncovered_claim_world()

        authorization = raise_goodwill(
            world["claim"], requested_amount_cents=40000, policy_adjustment_pct=0.25
        )
        assert authorization["status"] == "PENDING"
        assert float(authorization["out_of_warranty_margin_pct"]) == pytest.approx(0.1, abs=0.0001)
        assert authorization["adjudicator_limit_cents"] == 40000
        assert authorization["manager_limit_cents"] == 48000

        response = api_client.decide_goodwill_authorization(
            authorization["id"],
            decide_goodwill_authorization_payload(
                action="APPROVE", approved_amount_cents=44000
            ),
            ADJUDICATOR_ALT,
        )

        validate_error(response, ApiErrorId.ERR_GOODWILL_LIMIT_EXCEEDED)
        assert get_goodwill(authorization["id"])["status"] == "PENDING"

    def test_24_a_manager_approves_the_same_amount_under_its_higher_limit(self):
        """PRD §3.5: "`manager_limit_cents` is the lesser of the same share cap and the manager base authority of 250,000 cents (2,500 dollars) multiplied by the same decay multiplier and rounded half up to whole cents."
        PRD §3.5: "Approval records `approved_amount_cents` and stamps `decided_by_user_id` with the decider's `X-User-ID`, moving the authorization to `APPROVED` and advancing its `version` by 1."
        PRD §3.5: "It then cascades onto the claim: the claim's `coverage_type` flips from `NONE` to `GOODWILL`, the claim's open `NO_COVERAGE` edit is stamped `resolved_at`, `suspend_edit_count` is recomputed from the edits that remain open, and the claim's `version` advances by 1."
        PRD §3.5: "When that recount reaches zero the claim completes the second of its two cycle edges, `SUSPENDED → SUBMITTED`, which is what makes `GOODWILL` coverage reachable at all — without it a claim with no coverage would sit suspended forever."

        Design: Corner/validations/goodwill_decision_amount_above_the_deciding_roles_limit
        """
        world = build_uncovered_claim_world()

        authorization = raise_goodwill(
            world["claim"], requested_amount_cents=40000, policy_adjustment_pct=0.25
        )

        response = api_client.decide_goodwill_authorization(
            authorization["id"],
            decide_goodwill_authorization_payload(
                action="APPROVE", approved_amount_cents=44000
            ),
            MANAGER,
        )

        decided = validate_success(response, 200)
        assert decided["status"] == "APPROVED"
        assert decided["approved_amount_cents"] == 44000
        assert decided["decided_by_user_id"] == "mgr-user-1"

        claim = get_claim(world["claim"]["id"])
        assert claim["coverage_type"] == "GOODWILL"
        assert claim["status"] == "SUBMITTED"
        assert claim["suspend_edit_count"] == 0


class TestLaborTimeCeilingIsInclusive:
    def test_25_approved_hours_above_the_ceiling_are_refused_at_adjudication(self):
        """PRD §3.6: "On approval, `approved_labor_hours` is tested against the operation's `max_time_hours` exactly as claimed hours were at intake, with `ERR_LABOR_TIME_EXCEEDS_MAX` when it is strictly above."

        Design: Corner/validations/labor_time_ceiling_is_inclusive_on_submit_and_on_adjudicate
        """
        world = build_brake_world_with_claim()
        assert float(world["operation"]["max_time_hours"]) == pytest.approx(2.5, abs=0.01)

        response = api_client.adjudicate_claim(
            world["claim"]["id"],
            adjudicate_claim_payload(
                decision="APPROVE", approved_labor_hours=3.0, approved_parts_qty=3
            ),
            ADJUDICATOR,
        )

        validate_error(response, ApiErrorId.ERR_LABOR_TIME_EXCEEDS_MAX)
        claim = get_claim(world["claim"]["id"])
        assert claim["status"] == "SUBMITTED"
        assert claim["payment_status"] == "UNPAID"

    def test_26_claimed_hours_are_refused_above_the_ceiling_and_accepted_at_it(self):
        """PRD §3.3: "Finally, `claimed_labor_hours` is tested against the operation's absolute ceiling."
        PRD §3.3: "Hours at or below `max_time_hours` are accepted; hours strictly above it are refused with `ERR_LABOR_TIME_EXCEEDS_MAX`."
        PRD §3.3: "Note carefully that hours above `standard_time_hours` but at or below `max_time_hours` are perfectly acceptable at intake — they merely raise an excessive-time edit, described in §3.4."
        PRD §3.4: "An `EXCESSIVE_TIME` edit fires when `claimed_labor_hours` is strictly greater than the operation's `standard_time_hours`."

        Design: Corner/validations/labor_time_ceiling_is_inclusive_on_submit_and_on_adjudicate
        """
        world = build_brake_world()

        refused = api_client.create_claim(
            brake_claim_payload(
                world, repair_order_number="RO-4001", claimed_labor_hours=3.0
            ),
            world["dealer_headers"],
        )
        validate_error(refused, ApiErrorId.ERR_LABOR_TIME_EXCEEDS_MAX)
        assert claim_count_for(world["dealer"]["id"]) == 0

        accepted = api_client.create_claim(
            brake_claim_payload(
                world, repair_order_number="RO-4002", claimed_labor_hours=2.5
            ),
            world["dealer_headers"],
        )
        claim = validate_success(accepted, 201)
        assert float(claim["claimed_labor_hours"]) == pytest.approx(2.5, abs=0.01)
        assert claim["status"] == "SUSPENDED"
        assert claim["suspend_edit_count"] == 1

        edits = list_claim_edits(claim["id"])
        assert len(edits) == 1
        assert edits[0]["edit_code"] == "EXCESSIVE_TIME"
        assert edits[0]["severity"] == "SUSPEND"


class TestUncoveredClaimAdjudication:
    def test_27_a_claim_with_no_coverage_cannot_be_approved(self):
        """PRD §3.6: "And `coverage_type` must not be `NONE`: a claim with no coverage requires an `APPROVED` goodwill authorization to have flipped it to `GOODWILL` first, and approving without one is refused with `ERR_NO_COVERAGE_WITHOUT_GOODWILL` (HTTP 409)."
        PRD §3.3: "The one and only way `coverage_type` ever leaves `NONE` is the goodwill route of §3.5, which flips it from `NONE` to `GOODWILL`; no other transition of `coverage_type` exists."

        Design: Corner/validations/uncovered_claim_cannot_be_approved_but_can_be_denied
        """
        world = build_uncovered_claim_world()

        response = api_client.adjudicate_claim(
            world["claim"]["id"],
            adjudicate_claim_payload(
                decision="APPROVE", approved_labor_hours=1.0, approved_parts_qty=1
            ),
            ADJUDICATOR,
        )

        validate_error(response, ApiErrorId.ERR_NO_COVERAGE_WITHOUT_GOODWILL)
        claim = get_claim(world["claim"]["id"])
        assert claim["status"] == "SUSPENDED"
        assert claim["coverage_type"] == "NONE"

    def test_28_the_same_uncovered_claim_can_be_denied_and_waives_its_return(self):
        """PRD §3.6: "Denial requires a present, non-empty `denial_reason`, which is recorded as the claim moves `SUBMITTED → DENIED` or `SUSPENDED → DENIED`."
        PRD §3.6: "Denial also stamps `resolved_at` on every open edit, sets `suspend_edit_count` to 0, advances the claim's `version` by 1, and cascades onto the parts-return program: every parts-return obligation of this claim still in `REQUESTED` moves to `WAIVED`, and the dealer's `open_parts_return_count` is decremented by one for each waived row."

        Design: Corner/validations/uncovered_claim_cannot_be_approved_but_can_be_denied
        """
        world = build_uncovered_claim_world()
        obligation = parts_return_for_claim(world["claim"]["id"])
        assert obligation["status"] == "REQUESTED"

        denied = deny_claim(
            world["claim"]["id"], denial_reason="Repair is outside the warranty terms."
        )

        assert denied["status"] == "DENIED"
        assert denied["coverage_type"] == "NONE"
        assert denied["suspend_edit_count"] == 0
        assert get_parts_return(obligation["id"])["status"] == "WAIVED"
        assert get_dealer(world["dealer"]["id"])["open_parts_return_count"] == 0


class TestRejectionOrderOnClaimSubmission:
    def test_29_the_narrative_floor_speaks_before_causal_part_configuration(self):
        """PRD §2.11: "Checks are evaluated in the following order, and the first one that fails determines the response; no later check is consulted."
        PRD §2.11: "19. Repair narrative completeness — `ERR_NARRATIVE_INCOMPLETE`."
        PRD §2.11: "20. Causal-part configuration — `ERR_CAUSAL_PART_REQUIRED`."

        Design: Corner/validations/narrative_floor_outranks_causal_part_configuration_priority_ordering
        """
        world = build_brake_world()
        foreign_part = create_part(**HVAC_PART)

        # Both defects are present in one body: a six-character correction text and a
        # causal part drawn from the wrong failure group.
        response = api_client.create_claim(
            brake_claim_payload(
                world,
                correction_text="Fixed.",
                causal_part_id=foreign_part["id"],
                claimed_parts_qty=1,
            ),
            world["dealer_headers"],
        )

        validate_error(response, ApiErrorId.ERR_NARRATIVE_INCOMPLETE)
        assert claim_count_for(world["dealer"]["id"]) == 0

    def test_30_body_foreign_key_existence_speaks_before_body_shape(self):
        """PRD §2.11: "6. Body foreign-key existence, left to right — the not-found codes again."
        PRD §2.11: "7. Body shape: required fields present, enum values inside their declared domains, integers non-negative, decimal numerics parseable, dates in ISO-8601 calendar form, an audit's `period_start` strictly before its `period_end`, `requested_labor_rate_cents` strictly positive, `claimed_labor_hours` strictly positive, `claimed_parts_qty` at least 1 when a causal part is named and exactly 0 when none is, and a finding's `unsupported_amount_cents` non-negative — `ERR_VALIDATION`."
        PRD §2.7: "On claim submission that order is `dealer_id`, then `vehicle_id`, then `labor_operation_id`, then `causal_part_id`, so a request naming both a nonexistent dealer and a nonexistent vehicle reports `ERR_DEALER_NOT_FOUND` and never mentions the vehicle."

        Design: Corner/validations/foreign_key_existence_outranks_body_shape_priority_ordering
        """
        world = build_brake_world()

        # An unresolvable vehicle_id alongside a claimed_labor_hours of zero, which the
        # shape rule would reject on its own.
        response = api_client.create_claim(
            brake_claim_payload(
                world, vehicle_id=NON_EXISTENT_UUID, claimed_labor_hours=0
            ),
            world["dealer_headers"],
        )

        validate_error(response, ApiErrorId.ERR_VEHICLE_NOT_FOUND)
        assert claim_count_for(world["dealer"]["id"]) == 0
