"""Formulas whose inputs interact: the public-interest tier and the invoice ladder.

Both scenarios are built so that keying a step on the wrong intermediate value, or
rounding at the wrong moment, changes the money by an amount the assertions pin.
"""

from test_helpers.assertions import (
    assert_fields,
    assert_list_response,
    assert_money_is_integer_cents,
    assert_total_count,
    assert_waiver_pct,
)
from test_helpers.fixtures import (
    adjudicate,
    assert_claim,
    attach_record,
    clarify_scope,
    create_asset,
    create_estimate,
    create_request,
    create_requester,
    create_staff,
    get_record,
    get_request,
    get_task,
    issue_invoice,
    open_task,
    produce_release,
    record_verdict,
    request_version,
    rule_inclusion,
    submit_for_qa,
)
from test_helpers.test_users import SUPERVISOR_HEADERS


def _tier_scenario(api):
    """A GENERAL_PUBLIC filer, a 40-minute USE_OF_FORCE clip ruled responsive with a
    MEDICAL partial claim, and a spare one-minute ROUTINE clip on the same incident."""
    counsel = create_staff(api, "Dana Counsel", "COUNSEL", 3)
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset_a = create_asset(
        api,
        incident_number="INC-2026-0103",
        device_serial="AXON-0103",
        officer_badge="B-5510",
        recorded_start_at="2026-07-22T18:00:00Z",
        duration_ms=2400000,
        classification="USE_OF_FORCE",
        retention_category="EVIDENTIARY_7Y",
        scheduled_purge_at="2033-07-22T00:00:00Z",
    )
    asset_b = create_asset(
        api,
        incident_number="INC-2026-0103",
        device_serial="AXON-0104",
        officer_badge="B-5511",
        recorded_start_at="2026-07-22T18:40:00Z",
        duration_ms=60000,
        classification="ROUTINE",
        retention_category="NON_EVIDENTIARY_180D",
        scheduled_purge_at="2027-01-22T00:00:00Z",
    )
    request = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0103",
        requested_date_from="2026-07-22T00:00:00Z",
        requested_date_to="2026-07-23T00:00:00Z",
        scope_narrative="All BWC video for incident INC-2026-0103",
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative="Both body cameras, arrest sequence",
        requested_date_from="2026-07-22T00:00:00Z",
        requested_date_to="2026-07-22T23:59:59Z",
    )
    record_a = attach_record(api, request["id"], asset_a["id"])
    rule_inclusion(api, record_a["id"], "RESPONSIVE")
    assert_claim(api, record_a["id"], counsel["id"], "MEDICAL", "PARTIAL_REDACT")
    return {
        "request_id": request["id"],
        "record_a_id": record_a["id"],
        "asset_b_id": asset_b["id"],
    }


def test_subtotal_of_exactly_5000_lands_in_the_zero_tier(api):
    """A 5000-cent subtotal is the top of the first tier, so no public-interest waiver.

    PRD: "**Eighth**, the public-interest tier is chosen from `subtotal_cents`: the tier fraction is 0.00 when `subtotal_cents` is at most 5000, 0.10 when `subtotal_cents` is from 5001 through 25000 inclusive, and 0.20 when `subtotal_cents` exceeds 25000."

    Design: Difficulty/combinatorial_formula/public_interest_tier_keyed_on_pre_waiver_subtotal
    """
    scenario = _tier_scenario(api)

    estimate = create_estimate(api, scenario["request_id"], "PRESUMPTIVE", "USB")

    assert_fields(
        estimate,
        billable_minutes=50,
        estimated_labor_cents=3500,
        media_production_cents=1500,
        subtotal_cents=5000,
        waiver_credit_cents=0,
        estimated_total_cents=5000,
        deposit_required_cents=2500,
    )
    assert_waiver_pct(estimate, "effective_waiver_pct", 0.00)
    assert_money_is_integer_cents(estimate, "subtotal_cents", "estimated_total_cents")


def test_one_cent_over_the_tier_boundary_is_keyed_on_the_pre_waiver_subtotal(api):
    """A 5140-cent subtotal earns the 0.10 tier, and the total is 4626 rather than 5140.

    PRD: "The tier is **always** keyed on `subtotal_cents`, the pre-waiver figure computed in step seven."

    Design: Difficulty/combinatorial_formula/public_interest_tier_keyed_on_pre_waiver_subtotal
    """
    scenario = _tier_scenario(api)
    create_estimate(api, scenario["request_id"], "PRESUMPTIVE", "USB")
    record_b = attach_record(api, scenario["request_id"], scenario["asset_b_id"])
    rule_inclusion(api, record_b["id"], "RESPONSIVE")

    second = create_estimate(
        api,
        scenario["request_id"],
        "PRESUMPTIVE",
        "USB",
        expected_request_version=request_version(api, scenario["request_id"]),
    )

    assert_fields(
        second,
        projected_review_minutes=81,
        projected_burden_minutes=31,
        billable_minutes=52,
        estimated_labor_cents=3640,
        media_production_cents=1500,
        subtotal_cents=5140,
        waiver_credit_cents=514,
        estimated_total_cents=4626,
        deposit_required_cents=2313,
    )
    assert_waiver_pct(second, "effective_waiver_pct", 0.10)
    assert second["estimated_total_cents"] != 5140


def test_tier_estimate_moves_the_request_into_deposit_due_thirty_days_out(api):
    """The 2313-cent deposit lands the fee dimension at DEPOSIT_DUE with a 30-day due date.

    PRD: "When `deposit_required_cents` comes out greater than 0, the request moves to `fee_status` `DEPOSIT_DUE` and `deposit_due_at` is set to the logical clock advanced by thirty whole days."

    Design: Difficulty/combinatorial_formula/public_interest_tier_keyed_on_pre_waiver_subtotal
    """
    scenario = _tier_scenario(api)
    create_estimate(api, scenario["request_id"], "PRESUMPTIVE", "USB")
    record_b = attach_record(api, scenario["request_id"], scenario["asset_b_id"])
    rule_inclusion(api, record_b["id"], "RESPONSIVE")

    create_estimate(
        api,
        scenario["request_id"],
        "PRESUMPTIVE",
        "USB",
        expected_request_version=request_version(api, scenario["request_id"]),
    )

    assert_fields(
        get_request(api, scenario["request_id"]),
        estimated_total_cents=4626,
        deposit_required_cents=2313,
        fee_status="DEPOSIT_DUE",
        deposit_due_at="2026-08-31T00:00:00Z",
        responsive_record_count=2,
    )


def _invoiceable_two_plate_tasks(api):
    """One released hour of ROUTINE footage carrying two approved five-minute plate tasks."""
    counsel_a = create_staff(api, "Dana Counsel", "COUNSEL", 3)
    counsel_b = create_staff(api, "Ray Counsel", "COUNSEL", 3)
    tech = create_staff(api, "Tess Tech", "TECHNICIAN", 3)
    reviewer = create_staff(api, "Quinn Review", "REVIEWER", 3)
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset = create_asset(
        api,
        incident_number="INC-2026-0204",
        device_serial="AXON-0204",
        officer_badge="B-6602",
        recorded_start_at="2026-07-25T08:00:00Z",
        duration_ms=3600000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-25T00:00:00Z",
    )
    request = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0204",
        requested_date_from="2026-07-25T00:00:00Z",
        requested_date_to="2026-07-26T00:00:00Z",
        scope_narrative="Traffic stop BWC video, incident INC-2026-0204",
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative="Traffic stop, plates only",
        requested_date_from="2026-07-25T00:00:00Z",
        requested_date_to="2026-07-25T23:59:59Z",
    )
    record = attach_record(api, request["id"], asset["id"])
    rule_inclusion(api, record["id"], "RESPONSIVE")
    create_estimate(api, request["id"], "PRESUMPTIVE", "DIGITAL_DOWNLOAD")
    claim = assert_claim(api, record["id"], counsel_a["id"], "MEDICAL", "PARTIAL_REDACT")
    adjudicate(api, claim["id"], counsel_b["id"], "SUSTAINED")

    task1 = open_task(api, record["id"], tech["id"], "LICENSE_PLATE", 0, 10000, claim["id"])
    submit_for_qa(
        api, task1["id"], tech["id"], reviewer["id"], 5,
        "2026-08-01T13:00:00Z", "2026-08-01T14:00:00Z",
    )
    record_verdict(api, task1["id"], reviewer["id"], "PASS")
    task2 = open_task(api, record["id"], tech["id"], "LICENSE_PLATE", 10000, 20000, claim["id"])
    submit_for_qa(
        api, task2["id"], tech["id"], reviewer["id"], 5,
        "2026-08-01T15:00:00Z", "2026-08-01T16:00:00Z",
    )
    record_verdict(api, task2["id"], reviewer["id"], "PASS")
    package = produce_release(api, request["id"], "DIGITAL_DOWNLOAD")
    return {
        "request_id": request["id"],
        "record_id": record["id"],
        "task1_id": task1["id"],
        "task2_id": task2["id"],
        "package": package,
    }


def test_invoice_rounds_each_task_before_summing_them(api):
    """Two 297.5-cent plate tasks invoice at 596 cents, never at the aggregate 595.

    PRD: "The labour component is the total of those per-task amounts; the rounding happens once per task and only then are the results added, exactly as §2.8 requires."

    Design: Difficulty/combinatorial_formula/invoice_rounds_each_task_before_summing
    """
    scenario = _invoiceable_two_plate_tasks(api)
    assert get_task(api, scenario["task1_id"])["approved_labor_minutes"] == 5
    assert get_task(api, scenario["task2_id"])["approved_labor_minutes"] == 5
    assert get_request(api, scenario["request_id"])["billable_labor_minutes"] == 10

    issue_invoice(api, scenario["request_id"], memo="Final invoice for INC-2026-0204")

    request = get_request(api, scenario["request_id"])
    assert request["invoiced_total_cents"] == 596
    assert request["invoiced_total_cents"] != 595
    rows, _meta = assert_list_response(
        api.list_ledger_entries(
            SUPERVISOR_HEADERS,
            params={"request_id": scenario["request_id"], "entry_type": "LABOR_CHARGE"},
        )
    )
    assert len(rows) == 1
    assert_fields(rows[0], amount_cents=-596, source_kind="INVOICE")


def test_invoice_writes_one_line_and_reconciles_the_request_money(api):
    """A zero media component and a zero waiver are skipped, leaving a single ledger line.

    PRD: "Any component that computes to zero is skipped entirely rather than written as a zero line."

    Design: Difficulty/combinatorial_formula/invoice_rounds_each_task_before_summing
    """
    scenario = _invoiceable_two_plate_tasks(api)
    assert_fields(scenario["package"], package_kind="FINAL", production_cost_cents=0)

    issue_invoice(api, scenario["request_id"], memo="Final invoice for INC-2026-0204")

    assert_total_count(
        api.list_ledger_entries(
            SUPERVISOR_HEADERS, params={"request_id": scenario["request_id"]}
        ),
        1,
    )
    request = get_request(api, scenario["request_id"])
    assert_fields(
        request,
        fee_recognized_cents=596,
        deposit_balance_cents=-596,
        waiver_credit_total_cents=0,
        fee_status="INVOICED",
        processing_status="RELEASED",
    )
    assert get_record(api, scenario["record_id"])["inclusion_status"] == "RELEASED"
