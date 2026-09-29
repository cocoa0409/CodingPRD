"""Boundaries that are stated inclusively or exclusively and must be honoured exactly.

The deposit threshold is a strict comparison; the objection window is an inclusive
one. Both are probed at the boundary and one step beyond it.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers.api_errors import ERR_WINDOW_CLOSED
from test_helpers.assertions import (
    assert_created,
    assert_fields,
    assert_list_response,
    assert_waiver_pct,
)
from test_helpers.factories import objection_payload
from test_helpers.fixtures import (
    assert_claim,
    attach_record,
    clarify_scope,
    create_asset,
    create_depicted_individual,
    create_estimate,
    create_request,
    create_requester,
    create_staff,
    get_individual,
    get_record,
    get_request,
    issue_notice,
    request_version,
    rule_inclusion,
    set_clock,
)
from test_helpers.test_users import CLERK_HEADERS


def _threshold_scenario(api):
    """A 40-minute claimed recording priced at exactly 3500 cents, plus a spare minute."""
    counsel = create_staff(api, "Dana Counsel", "COUNSEL", 3)
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset1 = create_asset(
        api,
        incident_number="INC-2026-0511",
        device_serial="AXON-0511A",
        officer_badge="B-1104",
        recorded_start_at="2026-07-26T18:00:00Z",
        duration_ms=2400000,
        classification="USE_OF_FORCE",
        retention_category="EVIDENTIARY_7Y",
        scheduled_purge_at="2033-07-26T00:00:00Z",
    )
    asset2 = create_asset(
        api,
        incident_number="INC-2026-0511",
        device_serial="AXON-0511B",
        officer_badge="B-1105",
        recorded_start_at="2026-07-26T18:40:00Z",
        duration_ms=60000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-26T00:00:00Z",
    )
    request = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0511",
        requested_date_from="2026-07-26T00:00:00Z",
        requested_date_to="2026-07-27T00:00:00Z",
        scope_narrative="All BWC video for INC-2026-0511",
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative="Traffic stop through arrest",
        requested_date_from="2026-07-26T00:00:00Z",
        requested_date_to="2026-07-26T23:59:59Z",
    )
    record1 = attach_record(api, request["id"], asset1["id"])
    rule_inclusion(api, record1["id"], "RESPONSIVE")
    assert_claim(api, record1["id"], counsel["id"], "MEDICAL", "PARTIAL_REDACT")
    return {"request_id": request["id"], "asset2_id": asset2["id"]}


def test_a_total_of_exactly_the_threshold_demands_no_deposit(api):
    """3500 cents is not strictly greater than 3500, so no deposit and no due date.

    PRD: "**Eleventh**, `deposit_required_cents` is `estimated_total_cents` multiplied by one half and rounded half up when `estimated_total_cents` is **strictly greater** than 3500 cents, and is 0 otherwise — a total of exactly 3500 cents demands no deposit."

    Design: Difficulty/boundary_precision_check/deposit_threshold_exact_versus_one_step_over
    """
    scenario = _threshold_scenario(api)

    estimate = create_estimate(
        api, scenario["request_id"], "PRESUMPTIVE", "DIGITAL_DOWNLOAD"
    )

    assert_fields(
        estimate,
        billable_minutes=50,
        estimated_labor_cents=3500,
        media_production_cents=0,
        subtotal_cents=3500,
        waiver_credit_cents=0,
        estimated_total_cents=3500,
        deposit_required_cents=0,
    )
    assert_waiver_pct(estimate, "effective_waiver_pct", 0.00)
    assert_fields(
        get_request(api, scenario["request_id"]),
        fee_status="ESTIMATED",
        deposit_due_at=None,
    )


def test_one_minute_over_the_threshold_demands_half_the_total(api):
    """One extra source minute lifts the total to 3640 and demands 1820 cents.

    PRD: "When `deposit_required_cents` comes out greater than 0, the request moves to `fee_status` `DEPOSIT_DUE` and `deposit_due_at` is set to the logical clock advanced by thirty whole days."

    Design: Difficulty/boundary_precision_check/deposit_threshold_exact_versus_one_step_over
    """
    scenario = _threshold_scenario(api)
    first = create_estimate(api, scenario["request_id"], "PRESUMPTIVE", "DIGITAL_DOWNLOAD")
    record2 = attach_record(api, scenario["request_id"], scenario["asset2_id"])
    rule_inclusion(api, record2["id"], "RESPONSIVE")

    second = create_estimate(
        api,
        scenario["request_id"],
        "PRESUMPTIVE",
        "DIGITAL_DOWNLOAD",
        expected_request_version=request_version(api, scenario["request_id"]),
    )

    assert_fields(
        second,
        sequence_number=2,
        status="ACTIVE",
        projected_review_minutes=81,
        projected_burden_minutes=31,
        billable_minutes=52,
        estimated_labor_cents=3640,
        subtotal_cents=3640,
        estimated_total_cents=3640,
        deposit_required_cents=1820,
    )
    assert_waiver_pct(second, "effective_waiver_pct", 0.00)
    assert_fields(
        get_request(api, scenario["request_id"]),
        fee_status="DEPOSIT_DUE",
        deposit_due_at="2026-08-31T00:00:00Z",
        estimated_total_cents=3640,
        deposit_required_cents=1820,
    )
    rows, _meta = assert_list_response(
        api.list_fee_estimates(scenario["request_id"], CLERK_HEADERS)
    )
    by_id = {row["id"]: row for row in rows}
    assert by_id[first["id"]]["status"] == "SUPERSEDED"


def _three_notified_individuals(api):
    """A 20-minute responsive recording with two juveniles and one victim, all notified."""
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset = create_asset(
        api,
        incident_number="INC-2026-0512",
        device_serial="AXON-0512",
        officer_badge="B-1106",
        recorded_start_at="2026-07-25T09:00:00Z",
        duration_ms=1200000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-25T00:00:00Z",
    )
    juvenile_one = create_depicted_individual(api, asset["id"], "SUBJECT-J1", "JUVENILE")
    victim_one = create_depicted_individual(api, asset["id"], "SUBJECT-V1", "VICTIM")
    juvenile_two = create_depicted_individual(api, asset["id"], "SUBJECT-J2", "JUVENILE")
    request = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0512",
        requested_date_from="2026-07-25T00:00:00Z",
        requested_date_to="2026-07-26T00:00:00Z",
        scope_narrative="BWC video for INC-2026-0512",
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative="Full contact",
        requested_date_from="2026-07-25T00:00:00Z",
        requested_date_to="2026-07-25T23:59:59Z",
    )
    record = attach_record(api, request["id"], asset["id"])
    rule_inclusion(api, record["id"], "RESPONSIVE")
    issue_notice(api, juvenile_one["id"], "FIRST_CLASS_MAIL")
    issue_notice(api, victim_one["id"], "PERSONAL_SERVICE")
    issue_notice(api, juvenile_two["id"], "EMAIL")
    return {
        "request_id": request["id"],
        "record_id": record["id"],
        "j1_id": juvenile_one["id"],
        "v1_id": victim_one["id"],
        "j2_id": juvenile_two["id"],
    }


def test_notification_windows_are_fifteen_days_for_juveniles_and_ten_otherwise(api):
    """A juvenile notified on 1 August has until 16 August; a victim until 11 August.

    PRD: "Issuance moves the individual `PENDING → NOTIFIED`, stores the `notice_method`, stamps `notified_at` with the logical clock, and computes `objection_deadline_at` as `notified_at` advanced by fifteen whole days when the individual's `relationship` is `JUVENILE` and by ten whole days for every other relationship."

    Design: Difficulty/boundary_precision_check/objection_window_inclusive_deadline_instant
    """
    scenario = _three_notified_individuals(api)

    assert_fields(
        get_individual(api, scenario["j1_id"]),
        notification_status="NOTIFIED",
        objection_deadline_at="2026-08-16T00:00:00Z",
    )
    assert_fields(
        get_individual(api, scenario["v1_id"]),
        notification_status="NOTIFIED",
        objection_deadline_at="2026-08-11T00:00:00Z",
    )


def test_an_objection_at_the_deadline_instant_is_still_open(api):
    """The deadline instant itself is inside the window and materialises a derived claim.

    PRD: "The logical clock must be at or before `objection_deadline_at` — the deadline instant itself is still open — and a later attempt is refused with `ERR_WINDOW_CLOSED`."

    Design: Difficulty/boundary_precision_check/objection_window_inclusive_deadline_instant
    """
    scenario = _three_notified_individuals(api)
    set_clock(api, "2026-08-16T00:00:00Z")

    response = api.record_objection(
        scenario["j1_id"],
        objection_payload(scenario["record_id"], "JUVENILE_STATUS"),
        CLERK_HEADERS,
    )

    assert_created(response)
    assert_fields(
        get_individual(api, scenario["j1_id"]),
        notification_status="OBJECTED",
        objection_basis="JUVENILE_STATUS",
    )
    claims, _meta = assert_list_response(
        api.list_exemption_claims(
            CLERK_HEADERS, params={"responsive_record_id": scenario["record_id"]}
        )
    )
    assert len(claims) == 1
    assert_fields(
        claims[0],
        claim_source="DEPICTED_OBJECTION",
        exemption_code="JUVENILE",
        statutory_citation="985.04(1)",
        asserted_scope="PARTIAL_REDACT",
        status="ASSERTED",
        depicted_individual_id=scenario["j1_id"],
        asserted_by_staff_id=None,
    )
    assert_fields(
        get_record(api, scenario["record_id"]),
        unadjudicated_claim_count=1,
        presumptive_burden_minutes=21,
    )
    assert_fields(
        get_request(api, scenario["request_id"]),
        unadjudicated_claim_count=1,
        open_notification_count=3,
    )


def test_an_objection_one_second_past_the_deadline_is_closed(api):
    """A ten-day window closed five days earlier, and one second past fifteen days is late.

    PRD: "Where a rule says a window is still open at its deadline, the comparison is inclusive of the deadline instant itself; where a rule says a waiting period has elapsed at its deadline, the comparison is likewise inclusive."

    Design: Difficulty/boundary_precision_check/objection_window_inclusive_deadline_instant
    """
    scenario = _three_notified_individuals(api)
    set_clock(api, "2026-08-16T00:00:00Z")

    victim_response = api.record_objection(
        scenario["v1_id"],
        objection_payload(scenario["record_id"], "VICTIM_STATUS"),
        CLERK_HEADERS,
    )
    validate_error(victim_response, ERR_WINDOW_CLOSED, 409)
    assert get_individual(api, scenario["v1_id"])["notification_status"] == "NOTIFIED"

    set_clock(api, "2026-08-16T00:00:01Z")
    juvenile_response = api.record_objection(
        scenario["j2_id"],
        objection_payload(scenario["record_id"], "PRIVACY"),
        CLERK_HEADERS,
    )

    validate_error(juvenile_response, ERR_WINDOW_CLOSED, 409)
    assert get_individual(api, scenario["j2_id"])["notification_status"] == "NOTIFIED"
