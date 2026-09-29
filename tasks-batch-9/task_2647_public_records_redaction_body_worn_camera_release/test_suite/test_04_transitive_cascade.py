"""Chains where each link exists only because the previous one fired.

The full-withhold sustain drives a four-link chain through record, tasks and
reviewer calendar; the litigation hold drives a three-link chain over the
recordings of one incident and then reverses it.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers.assertions import assert_fields, assert_list_response
from test_helpers.factories import hold_release_payload, purge_payload
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
    get_asset,
    get_claim,
    get_hold,
    get_record,
    get_request,
    get_staff,
    get_task,
    open_task,
    place_hold,
    rule_inclusion,
    submit_for_qa,
)
from test_helpers.test_users import (
    CLERK_HEADERS,
    SUPERVISOR_HEADERS,
    make_counsel_headers,
)


def _full_withhold_ready(api):
    """Two responsive records, R2 already sustained, R1 carrying an asserted full-withhold
    claim and one QA_PENDING face task, with an active 1750-cent estimate on the request."""
    counsel_a = create_staff(api, "Dana Counsel", "COUNSEL", 3)
    counsel_b = create_staff(api, "Ray Counsel", "COUNSEL", 3)
    tech = create_staff(api, "Tess Tech", "TECHNICIAN", 3)
    reviewer = create_staff(api, "Quinn Review", "REVIEWER", 3)
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset_a1 = create_asset(
        api,
        incident_number="INC-2026-0407",
        device_serial="AXON-0407",
        officer_badge="B-8821",
        recorded_start_at="2026-07-30T01:00:00Z",
        duration_ms=1800000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-30T00:00:00Z",
    )
    asset_a2 = create_asset(
        api,
        incident_number="INC-2026-0407",
        device_serial="AXON-0408",
        officer_badge="B-8822",
        recorded_start_at="2026-07-30T01:10:00Z",
        duration_ms=600000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-30T00:00:00Z",
    )
    request = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0407",
        requested_date_from="2026-07-30T00:00:00Z",
        requested_date_to="2026-07-31T00:00:00Z",
        scope_narrative="Both BWC recordings for incident INC-2026-0407",
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative="Both BWC recordings, full duration",
        requested_date_from="2026-07-30T00:00:00Z",
        requested_date_to="2026-07-30T23:59:59Z",
    )
    record_r1 = attach_record(api, request["id"], asset_a1["id"])
    rule_inclusion(api, record_r1["id"], "RESPONSIVE")
    record_r2 = attach_record(api, request["id"], asset_a2["id"])
    rule_inclusion(api, record_r2["id"], "RESPONSIVE")
    claim_c2 = assert_claim(
        api, record_r2["id"], counsel_a["id"], "PERSONAL_PRIVACY", "PARTIAL_REDACT"
    )
    adjudicate(api, claim_c2["id"], counsel_b["id"], "SUSTAINED")
    claim_c1 = assert_claim(
        api, record_r1["id"], counsel_a["id"], "ONGOING_INVESTIGATION", "FULL_WITHHOLD"
    )
    estimate = create_estimate(api, request["id"], "PRESUMPTIVE", "DIGITAL_DOWNLOAD")
    task = open_task(api, record_r1["id"], tech["id"], "FACE", 0, 60000, claim_c1["id"])
    submit_for_qa(
        api, task["id"], tech["id"], reviewer["id"], 6,
        "2026-08-01T13:00:00Z", "2026-08-01T14:00:00Z",
    )
    return {
        "request_id": request["id"],
        "record_r1_id": record_r1["id"],
        "record_r2_id": record_r2["id"],
        "claim_c1_id": claim_c1["id"],
        "task_id": task["id"],
        "reviewer_id": reviewer["id"],
        "counsel_b_id": counsel_b["id"],
        "estimate_id": estimate["id"],
    }


def test_sustained_full_withhold_blocks_the_record_it_was_claimed_against(api):
    """Links one and two: the claim is decided, the record is withheld and blocked.

    PRD: "**Link two** fires only when the sustained claim's `asserted_scope` is `FULL_WITHHOLD`: the record moves `RESPONSIVE → WITHHELD_IN_FULL` and its `release_posture` becomes `BLOCKED`."

    Design: Difficulty/transitive_cascade/sustained_full_withhold_cascade_depth_four
    """
    scenario = _full_withhold_ready(api)

    adjudicate(api, scenario["claim_c1_id"], scenario["counsel_b_id"], "SUSTAINED")

    claim = get_claim(api, scenario["claim_c1_id"])
    assert_fields(
        claim, status="SUSTAINED", adjudicated_by_staff_id=scenario["counsel_b_id"]
    )
    record = get_record(api, scenario["record_r1_id"])
    assert_fields(
        record,
        inclusion_status="WITHHELD_IN_FULL",
        release_posture="BLOCKED",
        unadjudicated_claim_count=0,
        adjudicated_burden_minutes=38,
        presumptive_burden_minutes=38,
    )
    assert get_request(api, scenario["request_id"])["unadjudicated_claim_count"] == 0


def test_full_withhold_cascade_cancels_work_and_frees_the_reviewer(api):
    """Links three and four: the pending task is cancelled and the request finishes.

    PRD: "**Link three**, caused by link two, cancels the redaction work that has just become pointless: every redaction task on that record whose `status` is `DRAFT`, `QA_PENDING` or `QA_REJECTED` moves to `CANCELLED` with its `approved_labor_minutes` left at 0."

    Design: Difficulty/transitive_cascade/sustained_full_withhold_cascade_depth_four
    """
    scenario = _full_withhold_ready(api)
    assert get_staff(api, scenario["reviewer_id"])["open_qa_assignment_count"] == 1

    adjudicate(api, scenario["claim_c1_id"], scenario["counsel_b_id"], "SUSTAINED")

    assert_fields(
        get_task(api, scenario["task_id"]), status="CANCELLED", approved_labor_minutes=0
    )
    assert get_staff(api, scenario["reviewer_id"])["open_qa_assignment_count"] == 0
    assert_fields(
        get_request(api, scenario["request_id"]),
        processing_status="RELEASE_READY",
        billable_labor_minutes=0,
    )


def test_full_withhold_cascade_spares_the_sibling_record_and_stales_the_estimate(api):
    """The chain touches only the adjudicated claim's own record; the estimate goes stale.

    PRD: "Alongside that chain, and independent of it, sustaining a claim marks any fee estimate on the request whose `status` is `ACTIVE` as `STALE`, because the adjudicated burden the estimate projected has changed."

    Design: Difficulty/transitive_cascade/sustained_full_withhold_cascade_depth_four
    """
    scenario = _full_withhold_ready(api)

    adjudicate(api, scenario["claim_c1_id"], scenario["counsel_b_id"], "SUSTAINED")

    assert_fields(
        get_record(api, scenario["record_r2_id"]),
        inclusion_status="RESPONSIVE",
        release_posture="RESTRICTED",
    )
    rows, _meta = assert_list_response(
        api.list_fee_estimates(scenario["request_id"], CLERK_HEADERS)
    )
    by_id = {row["id"]: row for row in rows}
    assert by_id[scenario["estimate_id"]]["status"] == "STALE"
    # The request's estimated_total_cents mirror is not asserted here: PRD 3.8
    # says the mirror is "0 whenever no `ACTIVE` estimate exists", and the sustain
    # has just driven this request's only estimate to STALE.
    assert_fields(
        get_request(api, scenario["request_id"]),
        fee_status="ESTIMATED",
    )


def _two_purgeable_recordings(api):
    """Two overdue recordings on one incident, referenced by no request and unheld."""
    counsel = create_staff(api, "Dana Counsel", "COUNSEL", 3)
    asset_a1 = create_asset(
        api,
        incident_number="INC-2026-0408",
        device_serial="AXON-0501",
        officer_badge="B-9901",
        recorded_start_at="2026-01-05T03:00:00Z",
        duration_ms=600000,
        classification="ROUTINE",
        retention_category="NON_EVIDENTIARY_180D",
        scheduled_purge_at="2026-07-01T00:00:00Z",
    )
    asset_a2 = create_asset(
        api,
        incident_number="INC-2026-0408",
        device_serial="AXON-0502",
        officer_badge="B-9902",
        recorded_start_at="2026-01-05T03:05:00Z",
        duration_ms=300000,
        classification="ROUTINE",
        retention_category="NON_EVIDENTIARY_180D",
        scheduled_purge_at="2026-07-01T00:00:00Z",
    )
    return {
        "counsel_id": counsel["id"],
        "asset_a1_id": asset_a1["id"],
        "asset_a2_id": asset_a2["id"],
    }


def test_placing_a_hold_locks_and_suspends_every_matching_recording(api):
    """One hold placement fans out over both recordings on the incident and counts them.

    PRD: "Placement then fans out over every catalogued recording whose `incident_number` exactly equals the hold's `scope_incident_number`, in a three-link chain: because the hold became `ACTIVE`, each matching recording's `retention_locked` becomes true; because it became locked, the recording moves `SCHEDULED → SUSPENDED` and its `suspended_by_hold_id` is set to this hold's identifier; and because assets were suspended, the hold's `suspended_asset_count` is incremented once per suspended recording."

    Design: Difficulty/transitive_cascade/litigation_hold_suspension_cascade_depth_three
    """
    scenario = _two_purgeable_recordings(api)

    hold = place_hold(
        api,
        scenario["counsel_id"],
        matter_number="LIT-2026-0408",
        scope_incident_number="INC-2026-0408",
        hold_type="SUBPOENA",
    )

    for asset_key in ("asset_a1_id", "asset_a2_id"):
        assert_fields(
            get_asset(api, scenario[asset_key]),
            retention_locked=True,
            disposition_state="SUSPENDED",
            suspended_by_hold_id=hold["id"],
        )
    assert_fields(get_hold(api, hold["id"]), status="ACTIVE", suspended_asset_count=2)


def test_releasing_the_hold_reverses_the_suspension_chain(api):
    """Lifting the only matching hold returns both recordings to SCHEDULED and unlocked.

    PRD: "only when no `ACTIVE` hold matches does the recording move `SUSPENDED → SCHEDULED` with `suspended_by_hold_id` cleared to null."

    Design: Difficulty/transitive_cascade/litigation_hold_suspension_cascade_depth_three
    """
    scenario = _two_purgeable_recordings(api)
    hold = place_hold(
        api,
        scenario["counsel_id"],
        matter_number="LIT-2026-0408",
        scope_incident_number="INC-2026-0408",
        hold_type="SUBPOENA",
    )

    released = get_success_data(
        api.release_litigation_hold(
            hold["id"],
            hold_release_payload("Subpoena satisfied"),
            make_counsel_headers(scenario["counsel_id"]),
        )
    )

    assert_fields(
        released,
        status="RELEASED",
        suspended_asset_count=0,
        released_at="2026-08-01T00:00:00Z",
    )
    for asset_key in ("asset_a1_id", "asset_a2_id"):
        assert_fields(
            get_asset(api, scenario[asset_key]),
            disposition_state="SCHEDULED",
            suspended_by_hold_id=None,
            retention_locked=False,
        )


def test_purge_after_the_hold_lifts_is_per_recording(api):
    """Destroying one recording of the incident leaves its sibling scheduled.

    PRD: "A successful destruction moves the recording `SCHEDULED → PURGED`, which is terminal."

    Design: Difficulty/transitive_cascade/litigation_hold_suspension_cascade_depth_three
    """
    scenario = _two_purgeable_recordings(api)
    hold = place_hold(
        api,
        scenario["counsel_id"],
        matter_number="LIT-2026-0408",
        scope_incident_number="INC-2026-0408",
        hold_type="SUBPOENA",
    )
    get_success_data(
        api.release_litigation_hold(
            hold["id"],
            hold_release_payload("Subpoena satisfied"),
            make_counsel_headers(scenario["counsel_id"]),
        )
    )

    purged = get_success_data(
        api.purge_video_asset(
            scenario["asset_a1_id"],
            purge_payload("180-day schedule elapsed"),
            SUPERVISOR_HEADERS,
        )
    )

    assert purged["disposition_state"] == "PURGED"
    assert get_asset(api, scenario["asset_a1_id"])["disposition_state"] == "PURGED"
    assert get_asset(api, scenario["asset_a2_id"])["disposition_state"] == "SCHEDULED"
