"""Two violations at once, and only the higher-priority one may be reported.

The rejection ladder of §2.11 fixes which of two genuinely broken conditions the
caller hears about; each scenario below breaks exactly two and pins the winner.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers.api_errors import (
    ERR_RECORD_RELEASE_BLOCKED,
    ERR_REQUEST_NOT_RELEASE_READY,
)
from test_helpers.assertions import assert_fields, assert_total_count, assert_waiver_pct
from test_helpers.factories import redaction_task_payload, release_package_payload
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
    open_task,
    record_verdict,
    rule_inclusion,
    submit_for_qa,
)
from test_helpers.test_users import CLERK_HEADERS, make_technician_headers


def _unfunded_and_unready(api):
    """A request still in EXEMPTION_REVIEW that also owes an unpaid 2457-cent deposit."""
    counsel = create_staff(api, "Dana Counsel", "COUNSEL", 3)
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset = create_asset(
        api,
        incident_number="INC-2026-0509",
        device_serial="AXON-0509",
        officer_badge="B-1102",
        recorded_start_at="2026-07-31T20:00:00Z",
        duration_ms=2700000,
        classification="USE_OF_FORCE",
        retention_category="EVIDENTIARY_7Y",
        scheduled_purge_at="2033-07-31T00:00:00Z",
    )
    request = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0509",
        requested_date_from="2026-07-31T00:00:00Z",
        requested_date_to="2026-08-01T00:00:00Z",
        scope_narrative="BWC video for incident INC-2026-0509",
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative="Arrest sequence only",
        requested_date_from="2026-07-31T00:00:00Z",
        requested_date_to="2026-07-31T23:59:59Z",
    )
    record = attach_record(api, request["id"], asset["id"])
    rule_inclusion(api, record["id"], "RESPONSIVE")
    assert_claim(api, record["id"], counsel["id"], "JUVENILE", "PARTIAL_REDACT")
    estimate = create_estimate(api, request["id"], "PRESUMPTIVE", "DIGITAL_DOWNLOAD")
    return {
        "request_id": request["id"],
        "record_id": record["id"],
        "estimate": estimate,
    }


def test_release_readiness_outranks_the_unpaid_deposit(api):
    """A request that is neither ready nor funded reports the readiness failure.

    PRD: "The request must be at `processing_status` `RELEASE_READY` or `PARTIALLY_RELEASED`, or the call is refused with `ERR_REQUEST_NOT_RELEASE_READY` — and per §2.11 that refusal precedes the deposit check, so an unfunded request that is also not ready reports the readiness failure."

    Design: Difficulty/priority_pair_validation_conflict/release_readiness_state_beats_unpaid_deposit_fiscal
    """
    scenario = _unfunded_and_unready(api)

    response = api.create_release_package(
        scenario["request_id"], release_package_payload("DIGITAL_DOWNLOAD"), CLERK_HEADERS
    )

    validate_error(response, ERR_REQUEST_NOT_RELEASE_READY, 409)


def test_both_conditions_really_held_and_nothing_moved(api):
    """The deposit really is outstanding and the rejected call left every row alone.

    PRD: "**Eleventh**, `deposit_required_cents` is `estimated_total_cents` multiplied by one half and rounded half up when `estimated_total_cents` is **strictly greater** than 3500 cents, and is 0 otherwise — a total of exactly 3500 cents demands no deposit."

    Design: Difficulty/priority_pair_validation_conflict/release_readiness_state_beats_unpaid_deposit_fiscal
    """
    scenario = _unfunded_and_unready(api)
    assert_fields(scenario["estimate"], estimated_total_cents=4914)
    assert_waiver_pct(scenario["estimate"], "effective_waiver_pct", 0.10)

    api.create_release_package(
        scenario["request_id"], release_package_payload("DIGITAL_DOWNLOAD"), CLERK_HEADERS
    )

    assert_fields(
        get_request(api, scenario["request_id"]),
        processing_status="EXEMPTION_REVIEW",
        deposit_required_cents=2457,
        deposit_paid_cents=0,
        fee_status="DEPOSIT_DUE",
    )
    assert_fields(
        get_record(api, scenario["record_id"]),
        inclusion_status="RESPONSIVE",
        released_at=None,
    )
    assert_total_count(
        api.list_release_packages(scenario["request_id"], CLERK_HEADERS), 0
    )


def _blocked_record_with_an_approved_task(api):
    """A withheld-in-full record still carrying one APPROVED face task on [0,20000)."""
    counsel_a = create_staff(api, "Dana Counsel", "COUNSEL", 3)
    counsel_b = create_staff(api, "Ray Counsel", "COUNSEL", 3)
    tech = create_staff(api, "Tess Tech", "TECHNICIAN", 3)
    reviewer = create_staff(api, "Quinn Review", "REVIEWER", 3)
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset = create_asset(
        api,
        incident_number="INC-2026-0510",
        device_serial="AXON-0510",
        officer_badge="B-1103",
        recorded_start_at="2026-07-27T12:00:00Z",
        duration_ms=3600000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-27T00:00:00Z",
    )
    request = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0510",
        requested_date_from="2026-07-27T00:00:00Z",
        requested_date_to="2026-07-28T00:00:00Z",
        scope_narrative="BWC video for incident INC-2026-0510",
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative="Interview segment",
        requested_date_from="2026-07-27T00:00:00Z",
        requested_date_to="2026-07-27T23:59:59Z",
    )
    record = attach_record(api, request["id"], asset["id"])
    rule_inclusion(api, record["id"], "RESPONSIVE")
    kept = open_task(api, record["id"], tech["id"], "FACE", 0, 20000)
    submit_for_qa(
        api, kept["id"], tech["id"], reviewer["id"], 8,
        "2026-08-01T09:00:00Z", "2026-08-01T10:00:00Z",
    )
    record_verdict(api, kept["id"], reviewer["id"], "PASS")
    claim = assert_claim(
        api, record["id"], counsel_a["id"], "ONGOING_INVESTIGATION", "FULL_WITHHOLD"
    )
    adjudicate(api, claim["id"], counsel_b["id"], "SUSTAINED")
    return {
        "request_id": request["id"],
        "record_id": record["id"],
        "kept_task_id": kept["id"],
        "tech_id": tech["id"],
    }


def test_blocked_posture_outranks_the_clip_overlap_conflict(api):
    """An overlapping clip on a blocked record reports the block, never the overlap.

    PRD: "The parent record's `release_posture` must not be `BLOCKED`, since no work may be opened on a recording the unit has agreed to withhold in full; a blocked record is refused with `ERR_RECORD_RELEASE_BLOCKED`, and that refusal outranks the overlap check below, so an overlapping clip on a blocked record reports the block."

    Design: Difficulty/priority_pair_validation_conflict/blocked_posture_safety_beats_clip_overlap_constraint
    """
    scenario = _blocked_record_with_an_approved_task(api)

    response = api.create_redaction_task(
        scenario["record_id"],
        redaction_task_payload(scenario["tech_id"], "FACE", 5000, 15000),
        make_technician_headers(scenario["tech_id"]),
    )

    validate_error(response, ERR_RECORD_RELEASE_BLOCKED, 409)


def test_the_overlapping_interval_and_the_block_both_really_held(api):
    """The approved task survived the withholding cascade and no new row was written.

    PRD: "Tasks already at `APPROVED` are terminal and are not touched, which is why this link provably leaves the request's `billable_labor_minutes` unchanged."

    Design: Difficulty/priority_pair_validation_conflict/blocked_posture_safety_beats_clip_overlap_constraint
    """
    scenario = _blocked_record_with_an_approved_task(api)

    api.create_redaction_task(
        scenario["record_id"],
        redaction_task_payload(scenario["tech_id"], "FACE", 5000, 15000),
        make_technician_headers(scenario["tech_id"]),
    )

    assert_fields(
        get_record(api, scenario["record_id"]),
        release_posture="BLOCKED",
        inclusion_status="WITHHELD_IN_FULL",
    )
    assert_fields(
        get_task(api, scenario["kept_task_id"]),
        status="APPROVED",
        approved_labor_minutes=8,
        clip_start_ms=0,
        clip_end_ms=20000,
    )
    assert get_request(api, scenario["request_id"])["billable_labor_minutes"] == 8
    assert_total_count(
        api.list_redaction_tasks(
            CLERK_HEADERS, params={"responsive_record_id": scenario["record_id"]}
        ),
        1,
    )
