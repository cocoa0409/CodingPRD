"""Endpoint behaviours: reference-data reads, the labor-rate action chain, the
non-return sweep as a bulk action, the appeal-to-finding link and the two dealer
computed reads."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_finding,
    api_client,
    approve_claim,
    assert_date_equals,
    assert_dealer_posture_matches_balance,
    assert_ledger_balance_invariant,
    assert_ledger_entry,
    create_dealer,
    create_labor_operation,
    create_part,
    create_rate_request,
    create_state_law_profile,
    create_vehicle,
    decide_rate_request,
    expense_analytics,
    file_appeal,
    get_audit,
    get_claim,
    get_dealer,
    get_finding,
    get_parts_return,
    issue_findings,
    list_claim_edits,
    list_ledger_entries,
    list_parts_returns,
    make_dealer_warranty_admin_headers,
    parts_return_for_claim,
    pay_claim,
    receive_part,
    review_rate_request,
    run_non_return_sweep,
    schedule_audit,
    set_clock,
    setup_audit_with_findings,
    setup_reference_data,
    start_audit,
    submit_claim,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["warranty_admin_headers"]
ADJUDICATOR = TEST_USERS["claim_adjudicator_headers"]
AUDIT_MANAGER = TEST_USERS["audit_manager_headers"]

UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"

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

DA_TERMS = {
    "dealer_code": "DA",
    "name": "Audit Motors",
    "vehicles_in_operation": 100,
    "initial_labor_rate_cents": 10000,
    "initial_parts_markup_pct": 0.25,
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

REFLASH_OPERATION = {
    "op_code": "NP-100",
    "description": "Software reflash, no parts",
    "standard_time_hours": 0.5,
    "max_time_hours": 1.0,
    "category": "BASIC",
    "requires_causal_part": False,
    "causal_failure_group": None,
    "overlap_group": "REFLASH",
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

BRAKE_PART = {
    "part_number": "BRK-PAD-9931",
    "description": "Front brake pad set",
    "dealer_net_cents": 24799,
    "failure_group": "BRAKE_FRONT",
    "return_required": True,
    "retention_days": 30,
}

CLIP_PART = {
    "part_number": "BRK-CLP-1",
    "description": "Front brake caliper clip",
    "dealer_net_cents": 5000,
    "failure_group": "BRAKE_FRONT",
    "return_required": False,
    "retention_days": 0,
}

COVERED_VEHICLE = {
    "model_year": 2024,
    "warranty_start_date": "2024-01-15",
    "in_service_odometer": 0,
    "basic_months": 36,
    "basic_miles": 36000,
    "powertrain_months": 60,
    "powertrain_miles": 60000,
}

AUDIT_VEHICLE = {
    "model_year": 2025,
    "warranty_start_date": "2025-01-15",
    "in_service_odometer": 0,
    "basic_months": 36,
    "basic_miles": 36000,
    "powertrain_months": 60,
    "powertrain_miles": 60000,
}

BRAKE_NARRATIVE = {
    "complaint_text": "Customer reports brake squeal at low speed.",
    "cause_text": "Front brake pads worn beyond specification.",
    "correction_text": "Replaced front brake pads and verified normal braking.",
}

AUDIT_NARRATIVE = {
    "complaint_text": "Customer reports intermittent fault on delivery.",
    "cause_text": "Component failed internal leak test at the dealership.",
    "correction_text": "Replaced the failed component and road tested the vehicle.",
}


def build_brake_reference_world():
    """A CA dealer at a grandfathered 0.40 markup, with the front-brake operation and
    its return-required causal part published."""
    set_clock("2026-05-01T00:00:00Z")
    return setup_reference_data(
        profile_overrides=CA_PROFILE,
        dealer_overrides=D1_TERMS,
        vehicle_overrides=COVERED_VEHICLE,
        operation_overrides=BRAKE_OPERATION,
        part_overrides=BRAKE_PART,
    )


def build_audited_dealer_world(issue=True):
    """A dealer with one paid 20000-cent claim, audited over a quarter that contains it,
    carrying one 10000-cent finding."""
    set_clock("2026-05-01T00:00:00Z")
    world = setup_audit_with_findings(
        claim_specs=[
            {
                "claim": {
                    "repair_order_number": "RO-AUD-1",
                    "repair_date": "2026-02-15",
                    "odometer_at_repair": 20000,
                    "claimed_labor_hours": 2.0,
                    "claimed_parts_qty": 0,
                    **AUDIT_NARRATIVE,
                },
                "approve": {"approved_labor_hours": 2.0, "approved_parts_qty": 0},
                "pay": True,
            }
        ],
        finding_specs=[
            {
                "claim_index": 0,
                "unsupported_amount_cents": 10000,
                "finding_code": "TIME_NOT_DOCUMENTED",
                "evidence_note": "Technician time is not documented on the repair order.",
            }
        ],
        audit_overrides={
            "period_start": "2026-01-01",
            "period_end": "2026-04-01",
            "sample_size": 1,
        },
        issue=issue,
        profile_overrides=CA_PROFILE,
        dealer_overrides=DA_TERMS,
        operation_overrides=AUDIT_OPERATION,
        vehicle_overrides=AUDIT_VEHICLE,
        with_part=False,
    )
    assert world["claims"][0]["approved_total_cents"] == 20000
    assert world["claims"][0]["payment_status"] == "PAID"
    return world


class TestReferenceDataReadBack:
    def test_01_published_operations_and_parts_read_back_with_their_conditional_fields(
        self,
    ):
        """PRD §3.1: "Each operation also declares whether it `requires_causal_part`; when that flag is true the operation must name a non-empty `causal_failure_group` identifying the component family the causal part has to belong to, and when it is false `causal_failure_group` must be null."
        PRD §3.1: "The companion `retention_days` field gives the number of days after the obligation is raised before the part is deemed not returned; it must be zero when `return_required` is false and may be zero or more otherwise."

        Design: Corner/endpoints/reference_data_standard_crud_create_then_read
        """
        set_clock("2026-05-01T00:00:00Z")

        causal_operation = create_labor_operation(**BRAKE_OPERATION)
        no_part_operation = create_labor_operation(**REFLASH_OPERATION)
        returnable_part = create_part(**BRAKE_PART)
        keepable_part = create_part(**CLIP_PART)

        read_causal = validate_success(
            api_client.get_labor_operation(causal_operation["id"], ADMIN)
        )
        read_no_part = validate_success(
            api_client.get_labor_operation(no_part_operation["id"], ADMIN)
        )
        read_returnable = validate_success(
            api_client.get_part(returnable_part["id"], ADMIN)
        )
        read_keepable = validate_success(
            api_client.get_part(keepable_part["id"], ADMIN)
        )

        assert read_causal["id"] == causal_operation["id"]
        assert read_causal["op_code"] == "A1234-56"
        assert read_causal["requires_causal_part"] is True
        assert read_causal["causal_failure_group"] == "BRAKE_FRONT"
        assert read_causal["standard_time_hours"] == pytest.approx(1.5, abs=0.01)
        assert read_causal["max_time_hours"] == pytest.approx(2.5, abs=0.01)
        assert read_causal["category"] == "BASIC"

        assert read_no_part["id"] == no_part_operation["id"]
        assert read_no_part["requires_causal_part"] is False
        assert read_no_part["causal_failure_group"] is None

        assert read_returnable["id"] == returnable_part["id"]
        assert read_returnable["part_number"] == "BRK-PAD-9931"
        assert read_returnable["dealer_net_cents"] == 24799
        assert read_returnable["return_required"] is True
        assert read_returnable["retention_days"] == 30

        assert read_keepable["return_required"] is False
        assert read_keepable["retention_days"] == 0

    def test_02_dealer_list_filters_by_governing_statute_and_reports_page_meta(self):
        """PRD §3.1: "Dealers can be listed with filters on `state_law_profile_id`, on posture via `status`, on `outlier_flag` and on `audit_hold`, alongside the usual `limit` and `offset`."
        PRD §2.3: "Results on every list endpoint are ordered by `created_at` ascending."
        PRD §2.3: "The `meta` block of a list response carries `limit` and `offset` as they were resolved for that request, `total_count` giving the number of records matching the filters before pagination was applied, and `has_more`, which is true exactly when records matching the filters remain beyond the current page."
        PRD §3.1: "Enrollment also takes `initial_labor_rate_cents` and `initial_parts_markup_pct`, which are copied straight into the dealer's live `approved_labor_rate_cents` and `approved_parts_markup_pct` — the only two fields that describe what the dealer is paid today."
        PRD §3.1: "A newly enrolled dealer opens `ACTIVE`, with `chargeback_balance_cents` at 0, `open_parts_return_count` at 0, `audit_hold` false, `outlier_flag` false, `version` at 1, and `labor_rate_effective_date` left null until the dealer's first petition is approved."

        Design: Corner/endpoints/reference_data_standard_crud_create_then_read
        """
        set_clock("2026-05-01T00:00:00Z")
        governing = create_state_law_profile(**CA_PROFILE)
        other_state = create_state_law_profile(**{**CA_PROFILE, "state_code": "NY"})

        first = create_dealer(governing["id"], **D1_TERMS)
        second = create_dealer(governing["id"], **DA_TERMS)
        out_of_state = create_dealer(
            other_state["id"],
            dealer_code="NY1",
            name="Empire Motors",
            vehicles_in_operation=50,
            initial_labor_rate_cents=9000,
            initial_parts_markup_pct=0.20,
        )

        rows, meta = validate_paginated(
            api_client.list_dealers(ADMIN, {"state_law_profile_id": governing["id"]})
        )
        assert [row["id"] for row in rows] == [first["id"], second["id"]]
        assert out_of_state["id"] not in [row["id"] for row in rows]
        assert meta["total_count"] == 2
        assert meta["has_more"] is False

        page, page_meta = validate_paginated(
            api_client.list_dealers(
                ADMIN,
                {"state_law_profile_id": governing["id"], "limit": 1, "offset": 0},
            )
        )
        assert [row["id"] for row in page] == [first["id"]]
        assert page_meta["limit"] == 1
        assert page_meta["offset"] == 0
        assert page_meta["total_count"] == 2
        assert page_meta["has_more"] is True

        enrolled = rows[0]
        assert enrolled["approved_labor_rate_cents"] == 13750
        assert enrolled["approved_parts_markup_pct"] == pytest.approx(0.40, abs=0.01)
        assert enrolled["status"] == "ACTIVE"
        assert enrolled["chargeback_balance_cents"] == 0
        assert enrolled["open_parts_return_count"] == 0
        assert enrolled["audit_hold"] is False
        assert enrolled["outlier_flag"] is False
        assert enrolled["version"] == 1
        assert enrolled["labor_rate_effective_date"] is None

        suspended, suspended_meta = validate_paginated(
            api_client.list_dealers(ADMIN, {"status": "SUSPENDED"})
        )
        assert suspended == []
        assert suspended_meta["total_count"] == 0


class TestLaborRatePetitionActionChain:
    def test_03_review_then_approval_republishes_the_granted_terms_onto_the_dealer(self):
        """PRD §3.2: "On acceptance the request pins `state_law_profile_id` as a snapshot of the dealer's governing profile at that instant, so that later reassigning the dealer to a different state cannot retroactively change this petition's ceiling, and records `submitted_by_user_id` from `X-User-ID` for the segregation-of-duties check that will guard its decision."
        PRD §3.2: "The request opens in `SUBMITTED` with `deemed_approved` false, and the petitioning dealer's `version` advances by 1."
        PRD §3.2: "Under the retail-sample method the server first works out a step-up floor by taking the dealer's currently approved hourly rate, increasing it by twenty-five percent, and rounding the product half up to whole cents; it then takes the greater of the cited sample median and that step-up floor; and it finally takes the lesser of that result and the statute's absolute `max_labor_rate_cents`."
        PRD §3.2: "An `action` of `START_REVIEW` moves the petition `SUBMITTED → UNDER_REVIEW` and requires it to be in `SUBMITTED`; an `action` of `RETURN_FOR_INFO` bounces it back `UNDER_REVIEW → SUBMITTED` and requires it to be in `UNDER_REVIEW`."
        PRD §3.2: "Approval moves the request to `APPROVED`, writes both granted figures onto the request, then republishes them onto the dealer: the dealer's `approved_labor_rate_cents` and `approved_parts_markup_pct` are overwritten with the granted values and its `labor_rate_effective_date` is set to the request's `effective_date`, with the dealer's `updated_at` refreshed and its `version` advanced by 1."
        PRD §3.2: "The request's own `version` advances by 1 as well."

        Design: Corner/endpoints/labor_rate_request_action_endpoint_chain_and_preconditions
        """
        world = build_brake_reference_world()
        dealer = world["dealer"]
        assert dealer["version"] == 1

        filed = create_rate_request(
            dealer,
            requested_labor_rate_cents=17600,
            requested_parts_markup_pct=0.30,
            sample_repair_order_count=5,
            sample_median_rate_cents=17600,
            effective_date="2026-09-01",
        )
        assert filed["status"] == "SUBMITTED"
        assert filed["deemed_approved"] is False
        assert filed["version"] == 1
        assert filed["state_law_profile_id"] == world["profile"]["id"]
        # round_half_up(13750 * 1.25) = 17188, the median 17600 is greater, and 17600
        # is below the statutory maximum of 19500.
        assert filed["statutory_ceiling_cents"] == 17600
        assert get_dealer(dealer["id"])["version"] == 2

        reviewed = review_rate_request(filed["id"], action="START_REVIEW")
        assert reviewed["status"] == "UNDER_REVIEW"
        assert reviewed["version"] == 2

        before_decision = get_dealer(dealer["id"])
        decided = decide_rate_request(
            filed["id"],
            action="APPROVE",
            approved_labor_rate_cents=17600,
            approved_parts_markup_pct=0.30,
        )
        assert decided["status"] == "APPROVED"
        assert decided["approved_labor_rate_cents"] == 17600
        assert decided["approved_parts_markup_pct"] == pytest.approx(0.30, abs=0.01)
        assert decided["deemed_approved"] is False
        assert decided["version"] == 3

        republished = get_dealer(dealer["id"])
        assert republished["approved_labor_rate_cents"] == 17600
        assert republished["approved_parts_markup_pct"] == pytest.approx(0.30, abs=0.01)
        assert_date_equals(
            republished["labor_rate_effective_date"],
            "2026-09-01",
            "labor_rate_effective_date",
        )
        assert republished["version"] == before_decision["version"] + 1

    def test_04_second_start_review_is_refused_by_the_petition_state(self):
        """PRD §3.2: "An `action` of `START_REVIEW` moves the petition `SUBMITTED → UNDER_REVIEW` and requires it to be in `SUBMITTED`; an `action` of `RETURN_FOR_INFO` bounces it back `UNDER_REVIEW → SUBMITTED` and requires it to be in `UNDER_REVIEW`."
        PRD §3.2: "A request in any other state is refused with `ERR_LABOR_RATE_REQUEST_INVALID_STATE`."

        Design: Corner/endpoints/labor_rate_request_action_endpoint_chain_and_preconditions
        """
        world = build_brake_reference_world()

        filed = create_rate_request(
            world["dealer"],
            requested_labor_rate_cents=17600,
            requested_parts_markup_pct=0.30,
            sample_repair_order_count=5,
            sample_median_rate_cents=17600,
            effective_date="2026-09-01",
        )
        reviewed = review_rate_request(filed["id"], action="START_REVIEW")
        assert reviewed["status"] == "UNDER_REVIEW"

        response = api_client.review_labor_rate_request(
            filed["id"],
            {"action": "START_REVIEW", "note": "Pulled into review a second time."},
            ADMIN,
        )
        validate_error(response, ApiErrorId.ERR_LABOR_RATE_REQUEST_INVALID_STATE)

        untouched = validate_success(
            api_client.get_labor_rate_request(filed["id"], ADMIN)
        )
        assert untouched["status"] == "UNDER_REVIEW"
        assert untouched["version"] == 2


LATER_PART = {
    "part_number": "BRK-PAD-9932",
    "description": "Front brake pad set, long retention",
    "dealer_net_cents": 24799,
    "failure_group": "BRAKE_FRONT",
    "return_required": True,
    "retention_days": 365,
}


def build_sweep_world():
    """One dealer with four return obligations: one due against a paid approved claim,
    one not yet due, one already received, and one whose claim is still `SUBMITTED`."""
    set_clock("2026-05-01T00:00:00Z")
    profile = create_state_law_profile(**CA_PROFILE)
    dealer = create_dealer(profile["id"], **D1_TERMS)
    operation = create_labor_operation(**BRAKE_OPERATION)
    due_part = create_part(**BRAKE_PART)
    later_part = create_part(**LATER_PART)
    headers = make_dealer_warranty_admin_headers(dealer["id"])

    def file_claim(part, repair_order_number):
        return submit_claim(
            {
                "dealer": dealer,
                "vehicle": create_vehicle(**COVERED_VEHICLE),
                "operation": operation,
                "part": part,
                "dealer_headers": headers,
            },
            repair_order_number=repair_order_number,
            repair_date="2026-04-10",
            odometer_at_repair=20000,
            claimed_labor_hours=1.5,
            claimed_parts_qty=3,
            **BRAKE_NARRATIVE,
        )

    due_claim = file_claim(due_part, "RO-DUE-1")
    approve_claim(due_claim["id"], approved_labor_hours=1.5, approved_parts_qty=3)
    due_claim = pay_claim(due_claim["id"])

    not_yet_due_claim = file_claim(later_part, "RO-LATER-1")
    not_yet_due_claim = approve_claim(
        not_yet_due_claim["id"], approved_labor_hours=1.5, approved_parts_qty=3
    )

    received_claim = file_claim(due_part, "RO-RECV-1")
    received_claim = approve_claim(
        received_claim["id"], approved_labor_hours=1.5, approved_parts_qty=3
    )
    received_obligation = receive_part(
        parts_return_for_claim(received_claim["id"])["id"], "2026-05-01"
    )

    unapproved_claim = file_claim(due_part, "RO-OPEN-1")

    assert due_claim["approved_total_cents"] == 117342
    assert due_claim["payment_status"] == "PAID"
    assert unapproved_claim["status"] == "SUBMITTED"
    assert received_obligation["status"] == "RECEIVED"
    assert get_dealer(dealer["id"])["open_parts_return_count"] == 3

    return {
        "dealer": dealer,
        "due_claim": due_claim,
        "not_yet_due_claim": not_yet_due_claim,
        "received_claim": received_claim,
        "unapproved_claim": unapproved_claim,
        "due_obligation": parts_return_for_claim(due_claim["id"]),
        "not_yet_due_obligation": parts_return_for_claim(not_yet_due_claim["id"]),
        "received_obligation": received_obligation,
        "unapproved_obligation": parts_return_for_claim(unapproved_claim["id"]),
    }


class TestNonReturnSweepSelection:
    def test_05_sweep_takes_only_the_due_requested_row_of_an_approved_claim(self):
        """PRD §3.7: "The sweep considers every obligation still in `REQUESTED` whose `due_date` the logical clock has reached or passed, and whose linked claim is in `APPROVED`; it processes them in ascending order of their own `created_at`, so that the sequence of `balance_after_cents` values it writes onto the ledger is deterministic."
        PRD §3.7: "Each swept obligation moves `REQUESTED → NOT_RETURNED`, has `debit_amount_cents` set to the linked claim's entire `approved_total_cents` — a non-return costs the dealer the whole claim, labor included, not merely the parts — decrements the dealer's `open_parts_return_count` by 1, and advances its own `version` by 1."
        PRD §3.7: "The sweep reports `swept_count`, the identifiers of the claims it debited as `debited_claim_ids`, and the summed positive debit as `total_debit_cents`."
        PRD §3.7: "Taken together, the four movements that touch the count — creation into `REQUESTED` adding one, and departure from `REQUESTED` to any of `RECEIVED`, `NOT_RETURNED` or `WAIVED` subtracting one, with the late `NOT_RETURNED → RECEIVED` step changing nothing — keep `open_parts_return_count` exactly equal to the number of that dealer's obligations sitting in `REQUESTED` at every observable instant."

        Design: Corner/endpoints/non_return_sweep_bulk_action_skips_ineligible_rows
        """
        world = build_sweep_world()
        set_clock("2026-06-01T00:00:00Z")

        result = run_non_return_sweep()

        assert result["swept_count"] == 1
        assert result["debited_claim_ids"] == [world["due_claim"]["id"]]
        assert result["total_debit_cents"] == 117342

        swept = get_parts_return(world["due_obligation"]["id"])
        assert swept["status"] == "NOT_RETURNED"
        assert swept["debit_amount_cents"] == 117342
        assert swept["version"] == world["due_obligation"]["version"] + 1

        # The row whose retention window has not elapsed is left alone.
        not_yet_due = get_parts_return(world["not_yet_due_obligation"]["id"])
        assert not_yet_due["status"] == "REQUESTED"
        assert not_yet_due["debit_amount_cents"] == 0
        assert get_claim(world["not_yet_due_claim"]["id"])["payment_status"] == "UNPAID"

        # The row that already left REQUESTED is not a candidate at all.
        received = get_parts_return(world["received_obligation"]["id"])
        assert received["status"] == "RECEIVED"
        assert received["debit_amount_cents"] == 0

        # The due row whose claim never reached APPROVED is skipped.
        unapproved = get_parts_return(world["unapproved_obligation"]["id"])
        assert unapproved["status"] == "REQUESTED"
        assert unapproved["debit_amount_cents"] == 0
        assert get_claim(world["unapproved_claim"]["id"])["debited_amount_cents"] == 0

        # Two obligations remain in REQUESTED, so the count invariant still holds.
        assert get_dealer(world["dealer"]["id"])["open_parts_return_count"] == 2

    def test_06_one_swept_row_debits_its_claim_and_holds_the_dealers_open_claim(self):
        """PRD §3.7: "First, the linked claim's `debited_amount_cents` is increased by the debit and its `payment_status` moves to `DEBITED`, from `PAID` if it had been paid and from `UNPAID` if it had not; a debit against an unpaid claim still books a positive ledger amount, and that claim can never be paid afterwards because payment requires `payment_status` to be `UNPAID`."
        PRD §3.7: "Second, a ledger row with `source_type` `PARTS_NON_RETURN` is appended for the positive debit amount against the dealer, raising `chargeback_balance_cents`."
        PRD §3.7: "Third, the dealer's `status` is recomputed from the new balance and may rise `ACTIVE → PROBATION` or `ACTIVE → SUSPENDED`, with the dealer's `version` advancing by 1."
        PRD §3.7: "Fourth, if that recomputation put the dealer into `PROBATION` or `SUSPENDED`, every claim of that dealer currently in `SUBMITTED` is driven `SUBMITTED → SUSPENDED`: each such claim receives an appended edit whose `edit_code` is `DEALER_POSTURE_HOLD` and whose `severity` is `SUSPEND`, has its `suspend_edit_count` incremented by 1, and has its `version` advanced by 1."
        PRD §2.8: "Otherwise, a balance of at least 90,000 cents — 900 dollars — puts the dealer in `PROBATION`."

        Design: Corner/endpoints/non_return_sweep_bulk_action_skips_ineligible_rows
        """
        world = build_sweep_world()
        set_clock("2026-06-01T00:00:00Z")

        run_non_return_sweep()

        debited = get_claim(world["due_claim"]["id"])
        assert debited["payment_status"] == "DEBITED"
        assert debited["debited_amount_cents"] == 117342
        assert debited["status"] == "APPROVED"

        entries = list_ledger_entries(world["dealer"]["id"])
        assert len(entries) == 1
        assert entries[0]["source_type"] == "PARTS_NON_RETURN"
        assert entries[0]["source_id"] == world["due_obligation"]["id"]
        assert entries[0]["amount_cents"] == 117342
        assert entries[0]["balance_after_cents"] == 117342

        dealer = get_dealer(world["dealer"]["id"])
        assert dealer["chargeback_balance_cents"] == 117342
        assert dealer["status"] == "PROBATION"
        assert_ledger_balance_invariant(dealer, entries)
        assert_dealer_posture_matches_balance(dealer)

        # The dealer's one open intake is caught by the posture hold.
        held = get_claim(world["unapproved_claim"]["id"])
        assert held["status"] == "SUSPENDED"
        assert held["suspend_edit_count"] == 1
        holds = [
            edit
            for edit in list_claim_edits(held["id"])
            if edit["edit_code"] == "DEALER_POSTURE_HOLD"
        ]
        assert len(holds) == 1
        assert holds[0]["severity"] == "SUSPEND"
        assert holds[0]["resolved_at"] is None

        # A claim already in APPROVED is not swept up by the posture cascade.
        assert get_claim(world["not_yet_due_claim"]["id"])["status"] == "APPROVED"
        assert get_claim(world["received_claim"]["id"])["status"] == "APPROVED"


def build_two_audit_world():
    """One dealer with two paid claims in adjacent quarters, each quarter audited on its
    own and each audit carrying one charged-back finding."""
    set_clock("2026-05-01T00:00:00Z")
    profile = create_state_law_profile(**CA_PROFILE)
    dealer = create_dealer(profile["id"], **DA_TERMS)
    operation = create_labor_operation(**AUDIT_OPERATION)
    headers = make_dealer_warranty_admin_headers(dealer["id"])

    def paid_claim(repair_order_number, repair_date):
        claim = submit_claim(
            {
                "dealer": dealer,
                "vehicle": create_vehicle(**AUDIT_VEHICLE),
                "operation": operation,
                "part": None,
                "dealer_headers": headers,
            },
            repair_order_number=repair_order_number,
            repair_date=repair_date,
            odometer_at_repair=20000,
            claimed_labor_hours=2.0,
            claimed_parts_qty=0,
            **AUDIT_NARRATIVE,
        )
        approve_claim(claim["id"], approved_labor_hours=2.0, approved_parts_qty=0)
        return pay_claim(claim["id"])

    first_claim = paid_claim("RO-Q1-1", "2026-02-15")
    second_claim = paid_claim("RO-Q2-1", "2026-04-20")
    assert first_claim["approved_total_cents"] == 20000
    assert second_claim["approved_total_cents"] == 20000

    first_audit = schedule_audit(
        get_dealer(dealer["id"]),
        period_start="2026-01-01",
        period_end="2026-04-01",
        sample_size=1,
    )
    second_audit = schedule_audit(
        get_dealer(dealer["id"]),
        period_start="2026-04-01",
        period_end="2026-07-01",
        sample_size=1,
    )

    start_audit(first_audit["id"])
    first_finding = add_finding(
        first_audit["id"],
        first_claim["id"],
        10000,
        finding_code="TIME_NOT_DOCUMENTED",
        evidence_note="Technician time is not documented on the repair order.",
    )
    assert first_finding["status"] == "OPEN"
    assert first_finding["appeal_id"] is None
    first_audit = issue_findings(first_audit["id"])

    start_audit(second_audit["id"])
    second_finding = add_finding(
        second_audit["id"],
        second_claim["id"],
        10000,
        finding_code="NO_TECHNICIAN_SIGNATURE",
        evidence_note="The repair order carries no technician signature.",
    )
    second_audit = issue_findings(second_audit["id"])

    assert first_audit["status"] == "FINDINGS_ISSUED"
    assert second_audit["status"] == "FINDINGS_ISSUED"
    assert get_finding(first_finding["id"])["status"] == "CHARGED_BACK"
    assert get_finding(second_finding["id"])["status"] == "CHARGED_BACK"

    return {
        "dealer": dealer,
        "first_audit": first_audit,
        "second_audit": second_audit,
        "first_finding": get_finding(first_finding["id"]),
        "second_finding": get_finding(second_finding["id"]),
        "first_claim": first_claim,
        "second_claim": second_claim,
    }


class TestAppealFindingCrossReference:
    def test_07_appeal_citing_another_audits_finding_is_refused(self):
        """PRD §3.8: "A `DealerWarrantyAdmin` files an appeal against an audit in `FINDINGS_ISSUED`, supplying non-empty written `grounds`, a `contested_finding_ids` array holding at least one finding identifier, and the `expected_audit_version` of §2.9."
        PRD §3.8: "Every identifier in `contested_finding_ids` must name a finding belonging to the audit in question and must find that finding in `CHARGED_BACK`; otherwise the filing is refused with `ERR_FINDING_NOT_IN_AUDIT`."

        Design: Corner/endpoints/appeal_links_only_findings_of_its_own_audit_cross_reference
        """
        world = build_two_audit_world()
        target_audit = world["first_audit"]

        response = api_client.create_appeal(
            target_audit["id"],
            {
                "grounds": "The cited repair orders were signed and are on file at the store.",
                "contested_finding_ids": [world["second_finding"]["id"]],
                "expected_audit_version": target_audit["version"],
            },
            make_dealer_warranty_admin_headers(world["dealer"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_FINDING_NOT_IN_AUDIT)

        # Neither audit moved, and the foreign finding was not adopted.
        unchanged = get_audit(target_audit["id"])
        assert unchanged["status"] == "FINDINGS_ISSUED"
        assert unchanged["version"] == target_audit["version"]
        foreign = get_finding(world["second_finding"]["id"])
        assert foreign["appeal_id"] is None
        assert foreign["status"] == "CHARGED_BACK"
        assert foreign["audit_id"] == world["second_audit"]["id"]

        rows, meta = validate_paginated(api_client.list_appeals(AUDIT_MANAGER))
        assert rows == []
        assert meta["total_count"] == 0

    def test_08_filed_appeal_stamps_its_own_findings_and_leaves_the_others_alone(self):
        """PRD §3.8: "On acceptance the appeal opens in `FILED` with `filed_by_dealer_id` taken from `X-User-ID`, `overturned_finding_ids` an empty array, `reviewer_user_id` and `decision_note` null and `reinstated_amount_cents` at 0; each contested finding has its `appeal_id` stamped with the new appeal; and the audit moves `FINDINGS_ISSUED → APPEALED` with its `version` advanced by 1."
        PRD §3.8: "Findings can be read individually and listed with filters on `audit_id`, `claim_id`, `appeal_id` and `status`, which is the only channel exposing the cascade-set `audit_id` and `appeal_id` links."
        PRD §3.8: "Appeals can be read individually and listed with filters on `audit_id`, `filed_by_dealer_id` and `status`."

        Design: Corner/endpoints/appeal_links_only_findings_of_its_own_audit_cross_reference
        """
        world = build_two_audit_world()
        target_audit = world["first_audit"]
        balance_before = get_dealer(world["dealer"]["id"])["chargeback_balance_cents"]

        appeal = file_appeal(target_audit, [world["first_finding"]["id"]])

        assert appeal["status"] == "FILED"
        assert appeal["audit_id"] == target_audit["id"]
        assert appeal["filed_by_dealer_id"] == world["dealer"]["id"]
        assert appeal["contested_finding_ids"] == [world["first_finding"]["id"]]
        assert appeal["overturned_finding_ids"] == []
        assert appeal["reviewer_user_id"] is None
        assert appeal["decision_note"] is None
        assert appeal["reinstated_amount_cents"] == 0

        appealed = get_audit(target_audit["id"])
        assert appealed["status"] == "APPEALED"
        assert appealed["version"] == target_audit["version"] + 1

        contested = get_finding(world["first_finding"]["id"])
        assert contested["appeal_id"] == appeal["id"]
        assert contested["status"] == "CHARGED_BACK"

        # The other audit's finding is not drawn into this appeal.
        untouched = get_finding(world["second_finding"]["id"])
        assert untouched["appeal_id"] is None
        assert get_audit(world["second_audit"]["id"])["status"] == "FINDINGS_ISSUED"

        linked, linked_meta = validate_paginated(
            api_client.list_audit_findings(AUDIT_MANAGER, {"appeal_id": appeal["id"]})
        )
        assert [row["id"] for row in linked] == [world["first_finding"]["id"]]
        assert linked_meta["total_count"] == 1

        own_audit_rows, _ = validate_paginated(
            api_client.list_appeals(AUDIT_MANAGER, {"audit_id": target_audit["id"]})
        )
        assert [row["id"] for row in own_audit_rows] == [appeal["id"]]
        other_audit_rows, other_meta = validate_paginated(
            api_client.list_appeals(
                AUDIT_MANAGER, {"audit_id": world["second_audit"]["id"]}
            )
        )
        assert other_audit_rows == []
        assert other_meta["total_count"] == 0

        # Filing contests the money; it does not move it.
        assert (
            get_dealer(world["dealer"]["id"])["chargeback_balance_cents"]
            == balance_before
        )


class TestDealerComputedReads:
    def test_09_ledger_read_reconciles_with_the_stored_chargeback_balance(self):
        """PRD §2.8: "Each row names the `dealer_id` whose balance it moves, a `source_type` identifying the mechanism that produced it, a `source_id` holding the identifier of the originating record, an `amount_cents` that is signed and never zero — positive increases the amount the dealer owes the manufacturer, negative reduces it — and a `balance_after_cents` recording the dealer's balance immediately after this row was appended, so that a reader can reconcile the running balance without re-summing the whole ledger."
        PRD §2.8: "The `source_id` points at a `PartsReturnRequest` for the two parts codes and for `LATE_RETURN_REVERSAL`, at a `DealerAudit` for the two audit chargeback codes, and at an `AuditAppeal` for the two appeal reversal codes."
        PRD §2.8: "A dealer's `chargeback_balance_cents` is *defined* as the signed sum of `amount_cents` over every ledger row naming that dealer, and this equality is an invariant that must hold at every observable instant."
        PRD §3.8: "One ledger row with `source_type` `AUDIT_CHARGEBACK_SAMPLE` is appended per charged-back finding, each carrying that finding's `claim_id` and its positive `unsupported_amount_cents`, so the sampled rows sum to `sample_chargeback_cents`."
        PRD §4: "All list endpoints accept the `limit` and `offset` query parameters of §2.3 in addition to the filters named in their description, all filters are optional and combine conjunctively, and an unrecognised filter value simply matches nothing rather than erroring."

        Design: Corner/endpoints/dealer_computed_reads_reconcile_after_chargeback
        """
        world = build_audited_dealer_world(issue=True)
        dealer_id = world["dealer"]["id"]
        claim = world["claims"][0]

        entries = list_ledger_entries(dealer_id)
        assert len(entries) == 1
        row = entries[0]
        assert_ledger_entry(row)
        assert row["dealer_id"] == dealer_id
        assert row["source_type"] == "AUDIT_CHARGEBACK_SAMPLE"
        assert row["source_id"] == world["audit"]["id"]
        assert row["claim_id"] == claim["id"]
        assert row["amount_cents"] == 10000
        assert row["balance_after_cents"] == 10000

        dealer = get_dealer(dealer_id)
        assert dealer["chargeback_balance_cents"] == 10000
        assert dealer["status"] == "ACTIVE"
        assert_ledger_balance_invariant(dealer, entries)
        assert_dealer_posture_matches_balance(dealer)

        assert (
            len(list_ledger_entries(dealer_id, {"source_type": "AUDIT_CHARGEBACK_SAMPLE"}))
            == 1
        )
        assert list_ledger_entries(dealer_id, {"source_type": "PARTS_NON_RETURN"}) == []
        assert len(list_ledger_entries(dealer_id, {"claim_id": claim["id"]})) == 1

        debited = get_claim(claim["id"])
        assert debited["payment_status"] == "DEBITED"
        assert debited["debited_amount_cents"] == 10000

    def test_10_paid_basis_drops_the_debited_claim_while_the_incurred_basis_keeps_it(self):
        """PRD §3.9: "When `window_start` is omitted it defaults to the logical clock less three hundred and sixty-five days; when `window_end` is omitted it defaults to the logical clock itself."
        PRD §3.9: "The paid basis sums `approved_total_cents` over the dealer's claims that are in `APPROVED` and whose `payment_status` is exactly `PAID`, reporting the result as `paid_numerator_cents`; a claim that is approved but not yet paid is invisible on this basis, and a claim later charged back to `DEBITED` drops out of it entirely."
        PRD §3.9: "The incurred basis sums `approved_total_cents` over the dealer's claims that are in `APPROVED` whatever their `payment_status` — `UNPAID`, `PAID`, `DEBITED` and `CREDIT_REINSTATED` all count — reporting the result as `incurred_numerator_cents`."
        PRD §3.9: "Each numerator is then divided by the dealer's `vehicles_in_operation` and rounded half up to whole cents, giving `warranty_expense_per_vehicle_paid_cents` and `warranty_expense_per_vehicle_incurred_cents`."
        PRD §3.9: "`outlier_ratio` is the dealer's own `warranty_expense_per_vehicle_paid_cents` divided by `peer_median_paid_cents`, rounded half up to four decimal places, and is reported as 0 when the median is 0."
        PRD §3.9: "The response also echoes `dealer_id`, the resolved `window_start` and `window_end`, and `vehicles_in_operation`, so a reader can see exactly which window and which denominator produced the figures."

        Design: Corner/endpoints/dealer_computed_reads_reconcile_after_chargeback
        """
        world = build_audited_dealer_world(issue=True)
        dealer_id = world["dealer"]["id"]
        assert get_claim(world["claims"][0]["id"])["payment_status"] == "DEBITED"

        report = expense_analytics(dealer_id)

        assert report["dealer_id"] == dealer_id
        assert report["vehicles_in_operation"] == 100
        assert_date_equals(report["window_start"], "2025-05-01", "window_start")
        assert_date_equals(report["window_end"], "2026-05-01", "window_end")

        # The chargeback removed the only claim from the paid basis.
        assert report["paid_numerator_cents"] == 0
        assert report["paid_claim_count"] == 0
        assert report["warranty_expense_per_vehicle_paid_cents"] == 0
        # The incurred basis still counts it at its full approved total.
        assert report["incurred_numerator_cents"] == 20000
        assert report["incurred_claim_count"] == 1
        assert report["warranty_expense_per_vehicle_incurred_cents"] == 200

        # The dealer is its own only peer and now spends nothing on the paid basis.
        assert report["peer_median_paid_cents"] == 0
        assert report["outlier_ratio"] == pytest.approx(0.0, abs=0.00001)
        assert report["outlier_flag"] is False
        assert get_dealer(dealer_id)["outlier_flag"] is False


class TestConditionalPartsReturnCreation:
    def test_11_no_obligation_when_the_causal_part_does_not_require_return(self):
        """PRD §3.1: "A part also declares `return_required`: when true, a claim naming this part as causal creates a return obligation for failed-component analysis."
        PRD §3.4: "When the submission's causal part has `return_required` true, the same request also raises a parts-return obligation in `REQUESTED`, whose `due_date` is its own `created_at` advanced by the part's `retention_days` days, and increments the dealer's `open_parts_return_count` by 1 — re-establishing the invariant that the count always equals the number of parts-return rows in `REQUESTED` whose claim belongs to that dealer."

        Design: Corner/endpoints/parts_return_created_only_when_the_part_requires_return
        """
        set_clock("2026-05-01T00:00:00Z")
        world = setup_reference_data(
            profile_overrides=CA_PROFILE,
            dealer_overrides=D1_TERMS,
            vehicle_overrides=COVERED_VEHICLE,
            operation_overrides=BRAKE_OPERATION,
            part_overrides=CLIP_PART,
        )
        assert world["part"]["return_required"] is False

        keepable_claim = submit_claim(
            world,
            repair_order_number="RO-KEEP-1",
            repair_date="2026-04-10",
            odometer_at_repair=20000,
            claimed_labor_hours=1.5,
            claimed_parts_qty=3,
            **BRAKE_NARRATIVE,
        )
        assert keepable_claim["status"] == "SUBMITTED"
        assert list_parts_returns({"claim_id": keepable_claim["id"]}) == []
        assert get_dealer(world["dealer"]["id"])["open_parts_return_count"] == 0

        # A claim that names no causal part at all raises nothing either.
        no_part_claim = submit_claim(
            {
                "dealer": world["dealer"],
                "vehicle": create_vehicle(**COVERED_VEHICLE),
                "operation": create_labor_operation(**REFLASH_OPERATION),
                "part": None,
                "dealer_headers": world["dealer_headers"],
            },
            repair_order_number="RO-KEEP-2",
            repair_date="2026-04-11",
            odometer_at_repair=20100,
            claimed_labor_hours=0.5,
            claimed_parts_qty=0,
            **BRAKE_NARRATIVE,
        )
        assert list_parts_returns({"claim_id": no_part_claim["id"]}) == []
        assert get_dealer(world["dealer"]["id"])["open_parts_return_count"] == 0

    def test_12_return_required_part_raises_one_obligation_with_its_due_date(self):
        """PRD §3.4: "When the submission's causal part has `return_required` true, the same request also raises a parts-return obligation in `REQUESTED`, whose `due_date` is its own `created_at` advanced by the part's `retention_days` days, and increments the dealer's `open_parts_return_count` by 1 — re-establishing the invariant that the count always equals the number of parts-return rows in `REQUESTED` whose claim belongs to that dealer."
        PRD §3.7: "The obligation names the `claim_id` that created it and the `part_id` to be returned, both established by the cascade at claim submission rather than by any request body, and both visible only through the parts-return listing, which filters on `claim_id`, `part_id` and `status` alongside `limit` and `offset`."
        PRD §3.7: "The obligation opens in `REQUESTED` with a `due_date` derived from its own creation instant and the part's retention window, with `received_date`, `analysis_result` and `analysis_note` all null, and with `debit_amount_cents` and `reversed_amount_cents` both at 0."

        Design: Corner/endpoints/parts_return_created_only_when_the_part_requires_return
        """
        world = build_brake_reference_world()
        assert world["part"]["return_required"] is True
        assert world["part"]["retention_days"] == 30

        claim = submit_claim(
            world,
            repair_order_number="RO-1001",
            repair_date="2026-04-10",
            odometer_at_repair=20000,
            claimed_labor_hours=1.5,
            claimed_parts_qty=3,
            **BRAKE_NARRATIVE,
        )

        rows = list_parts_returns({"claim_id": claim["id"]})
        assert len(rows) == 1
        obligation = rows[0]
        assert obligation["claim_id"] == claim["id"]
        assert obligation["part_id"] == world["part"]["id"]
        assert obligation["status"] == "REQUESTED"
        assert_date_equals(obligation["due_date"], "2026-05-31", "due_date")
        assert obligation["received_date"] is None
        assert obligation["analysis_result"] is None
        assert obligation["analysis_note"] is None
        assert obligation["debit_amount_cents"] == 0
        assert obligation["reversed_amount_cents"] == 0
        assert obligation["version"] == 1

        assert get_dealer(world["dealer"]["id"])["open_parts_return_count"] == 1
        assert get_parts_return(obligation["id"])["id"] == obligation["id"]
        assert list_parts_returns({"part_id": world["part"]["id"]}) == rows
        assert list_parts_returns({"status": "RECEIVED"}) == []
