"""The six roles are peers with disjoint exclusive surfaces, not a privilege ladder.

Each exclusive operation is probed by a peer role that is not on its list and is
refused at priority 2, before any segregation-of-duties, state or fiscal check can
be reached; the shared operations are then driven successfully by every role their
list names. The clock-control surface is the one endpoint all six roles share, and
the staff directory is the one operational read the filer is denied.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ERR_UNAUTHORIZED
from test_helpers.assertions import (
    assert_created,
    assert_fields,
    assert_modified,
    assert_object_response,
    assert_total_count,
)
from test_helpers.factories import (
    clock_payload,
    inclusion_payload,
    litigation_hold_payload,
    purge_payload,
    qa_outcome_payload,
    request_payload,
    submit_qa_payload,
    video_asset_payload,
)
from test_helpers.fixtures import (
    attach_record,
    clarify_scope,
    create_asset,
    create_request,
    create_requester,
    create_staff,
    get_asset,
    get_request,
    get_requester,
    get_staff,
    get_task,
    open_task,
    rule_inclusion,
)
from test_helpers.test_users import (
    CLERK_HEADERS,
    SUPERVISOR_HEADERS,
    make_counsel_headers,
    make_requester_headers,
    make_technician_headers,
)


def _draft_face_task_on_a_responsive_record(api):
    """A RESPONSIVE 30-minute record carrying one DRAFT FACE task for the technician.

    The technician holds level 1 and the reviewer level 2, which is exactly the
    certification a FACE task with no linked claim requires of each of them.
    """
    tech = create_staff(api, "Tech One", "TECHNICIAN", 1)
    reviewer = create_staff(api, "Reviewer One", "REVIEWER", 2)
    counsel = create_staff(api, "Counsel A", "COUNSEL", 3)
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset = create_asset(
        api,
        incident_number="INC-2026-0667",
        device_serial="AXON-0667",
        officer_badge="B-1164",
        recorded_start_at="2026-06-28T09:00:00Z",
        duration_ms=1800000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-06-28T00:00:00Z",
    )
    request = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0667",
        requested_date_from="2026-06-28T00:00:00Z",
        requested_date_to="2026-06-29T00:00:00Z",
        scope_narrative="Half an hour of BWC video",
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative="The single half-hour recording",
        requested_date_from="2026-06-28T00:00:00Z",
        requested_date_to="2026-06-28T23:59:59Z",
    )
    record = attach_record(api, request["id"], asset["id"])
    rule_inclusion(api, record["id"], "RESPONSIVE")
    task = open_task(api, record["id"], tech["id"], "FACE", 0, 1800000)
    return {
        "asset_id": asset["id"],
        "request_id": request["id"],
        "record_id": record["id"],
        "task_id": task["id"],
        "tech_id": tech["id"],
        "reviewer_id": reviewer["id"],
        "counsel_id": counsel["id"],
    }


def test_supervisor_cannot_submit_the_technicians_redaction_work(api):
    """The fiscal authority is off the production surface; the technician's own call lands.

    PRD: "Submitting finished work is the `RedactionTechnician`'s exclusive act, and it does double duty as a booking."

    Design: Corner/rbac/peer_roles_cannot_reach_each_others_exclusive_operations
    """
    scenario = _draft_face_task_on_a_responsive_record(api)
    payload = submit_qa_payload(
        scenario["reviewer_id"], 15, "2026-08-02T09:00:00Z", "2026-08-02T09:30:00Z"
    )

    refused = api.submit_qa(scenario["task_id"], payload, SUPERVISOR_HEADERS)

    validate_error(refused, ERR_UNAUTHORIZED, 403)
    assert_fields(get_task(api, scenario["task_id"]), status="DRAFT", qa_reviewer_id=None)
    assert get_staff(api, scenario["reviewer_id"])["open_qa_assignment_count"] == 0

    accepted = api.submit_qa(
        scenario["task_id"], payload, make_technician_headers(scenario["tech_id"])
    )

    submitted = assert_modified(accepted)
    assert_fields(
        submitted,
        status="QA_PENDING",
        qa_reviewer_id=scenario["reviewer_id"],
        logged_labor_minutes=15,
    )
    assert get_staff(api, scenario["reviewer_id"])["open_qa_assignment_count"] == 1


def test_technician_cannot_record_the_quality_verdict_on_their_own_task(api):
    """Priority 2 answers before priority 10, so the role refusal precedes the SoD refusal.

    PRD: "The system evaluates them as a single ordered ladder and stops at the first violation, so the reported `error_id` is fully determined by the ladder position rather than by which check happens to be cheapest."

    Design: Corner/rbac/peer_roles_cannot_reach_each_others_exclusive_operations
    """
    scenario = _draft_face_task_on_a_responsive_record(api)
    assert_modified(
        api.submit_qa(
            scenario["task_id"],
            submit_qa_payload(
                scenario["reviewer_id"], 15, "2026-08-02T09:00:00Z", "2026-08-02T09:30:00Z"
            ),
            make_technician_headers(scenario["tech_id"]),
        )
    )

    response = api.record_qa_outcome(
        scenario["task_id"],
        qa_outcome_payload("PASS"),
        make_technician_headers(scenario["tech_id"]),
    )

    validate_error(response, ERR_UNAUTHORIZED, 403)
    assert_fields(
        get_task(api, scenario["task_id"]), status="QA_PENDING", approved_labor_minutes=0
    )
    assert get_staff(api, scenario["reviewer_id"])["open_qa_assignment_count"] == 1
    assert get_request(api, scenario["request_id"])["billable_labor_minutes"] == 0


def test_supervisor_cannot_place_a_litigation_hold(api):
    """The unit supervisor does not inherit counsel's litigation-hold authority.

    PRD: "Placing a litigation hold is `LegalCounsel`'s exclusive authority."

    Design: Corner/rbac/peer_roles_cannot_reach_each_others_exclusive_operations
    """
    scenario = _draft_face_task_on_a_responsive_record(api)

    response = api.create_litigation_hold(
        litigation_hold_payload(
            matter_number="LIT-2026-0067",
            scope_incident_number="INC-2026-0667",
            hold_type="LITIGATION",
        ),
        SUPERVISOR_HEADERS,
    )

    validate_error(response, ERR_UNAUTHORIZED, 403)
    assert_fields(
        get_asset(api, scenario["asset_id"]),
        disposition_state="SCHEDULED",
        suspended_by_hold_id=None,
    )


def test_counsel_cannot_destroy_a_recording(api):
    """Destruction is the supervisor's authority, so counsel never reaches the hold check.

    PRD: "Destruction closes the retention story and is a `RecordsSupervisor` authority."

    Design: Corner/rbac/peer_roles_cannot_reach_each_others_exclusive_operations
    """
    scenario = _draft_face_task_on_a_responsive_record(api)

    response = api.purge_video_asset(
        scenario["asset_id"],
        purge_payload("Counsel-ordered destruction"),
        make_counsel_headers(scenario["counsel_id"]),
    )

    validate_error(response, ERR_UNAUTHORIZED, 403)
    assert_fields(
        get_asset(api, scenario["asset_id"]),
        disposition_state="SCHEDULED",
        retention_locked=True,
    )


def _three_candidate_records(api):
    """Three 15-minute ROUTINE recordings of one incident attached to a clarified request."""
    counsel = create_staff(api, "Counsel A", "COUNSEL", 3)
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    assets = []
    for suffix, badge, start in (
        ("AXON-0668A", "B-1165", "2026-06-27T09:00:00Z"),
        ("AXON-0668B", "B-1166", "2026-06-27T09:15:00Z"),
        ("AXON-0668C", "B-1167", "2026-06-27T09:30:00Z"),
    ):
        assets.append(
            create_asset(
                api,
                incident_number="INC-2026-0668",
                device_serial=suffix,
                officer_badge=badge,
                recorded_start_at=start,
                duration_ms=900000,
                classification="ROUTINE",
                retention_category="INVESTIGATIVE_3Y",
                scheduled_purge_at="2029-06-27T00:00:00Z",
            )
        )
    request = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0668",
        requested_date_from="2026-06-27T00:00:00Z",
        requested_date_to="2026-06-28T00:00:00Z",
        scope_narrative="All three cameras",
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative="All three fifteen-minute clips",
        requested_date_from="2026-06-27T00:00:00Z",
        requested_date_to="2026-06-27T23:59:59Z",
    )
    records = [attach_record(api, request["id"], asset["id"]) for asset in assets]
    return {
        "counsel_id": counsel["id"],
        "requester_id": requester["id"],
        "asset_ids": [asset["id"] for asset in assets],
        "request_id": request["id"],
        "record_ids": [record["id"] for record in records],
    }


def test_inclusion_rulings_land_for_all_three_authorised_roles(api):
    """Clerk, counsel and supervisor each drive the same inclusion endpoint successfully.

    PRD: "Ruling on responsiveness is open to a `RecordsClerk`, `LegalCounsel` or `RecordsSupervisor`, and the payload carries a single `inclusion_status` that must be either `RESPONSIVE` or `EXCLUDED`."

    Design: Corner/rbac/shared_inclusion_and_intake_work_for_every_listed_role
    """
    scenario = _three_candidate_records(api)
    record_a, record_b, record_c = scenario["record_ids"]
    asset_a, asset_b, asset_c = scenario["asset_ids"]

    ruled_a = assert_modified(
        api.rule_inclusion(record_a, inclusion_payload("RESPONSIVE"), CLERK_HEADERS)
    )
    ruled_b = assert_modified(
        api.rule_inclusion(
            record_b,
            inclusion_payload("RESPONSIVE"),
            make_counsel_headers(scenario["counsel_id"]),
        )
    )
    ruled_c = assert_modified(
        api.rule_inclusion(record_c, inclusion_payload("EXCLUDED"), SUPERVISOR_HEADERS)
    )

    assert_fields(ruled_a, inclusion_status="RESPONSIVE")
    assert_fields(ruled_b, inclusion_status="RESPONSIVE")
    assert_fields(ruled_c, inclusion_status="EXCLUDED")
    assert_fields(
        get_request(api, scenario["request_id"]),
        processing_status="EXEMPTION_REVIEW",
        responsive_record_count=2,
    )
    assert get_asset(api, asset_a)["retention_locked"] is True
    assert get_asset(api, asset_b)["retention_locked"] is True
    assert get_asset(api, asset_c)["retention_locked"] is False


def test_intake_is_shared_by_the_clerk_and_the_supervisor(api):
    """A supervisor-filed request opens exactly as a clerk-filed one does.

    PRD: "A successful intake creates the request at `processing_status` `INTAKE`, `fee_status` `NOT_ASSESSED` and `version` 1, increments the filer's `open_request_count` by 1, and strikes the first `statutory_deadline_at`."

    Design: Corner/rbac/shared_inclusion_and_intake_work_for_every_listed_role
    """
    scenario = _three_candidate_records(api)

    response = api.create_request(
        request_payload(
            scenario["requester_id"],
            received_at="2026-08-01T00:00:00Z",
            subject_incident_number="INC-2026-0668",
            requested_date_from="2026-06-27T00:00:00Z",
            requested_date_to="2026-06-28T00:00:00Z",
            scope_narrative="A second, supervisor-filed request",
        ),
        SUPERVISOR_HEADERS,
    )

    created = assert_created(response)
    assert_fields(
        created, processing_status="INTAKE", fee_status="NOT_ASSESSED", version=1
    )
    assert get_requester(api, scenario["requester_id"])["open_request_count"] == 2
    assert_total_count(
        api.list_requests(CLERK_HEADERS, params={"requester_id": scenario["requester_id"]}), 2
    )


def test_requester_may_move_the_clock_but_may_not_catalogue_a_recording(api):
    """The filer shares the clock surface with every role and is refused the evidence desk.

    PRD: "Cataloguing a body-worn camera recording is the clerk's or supervisor's first act on the evidence side."

    Design: Corner/rbac/requester_may_set_the_clock_but_may_not_write_the_case_file
    """
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    filer = make_requester_headers(requester["id"])

    validate_success(api.set_clock(clock_payload("2026-08-04T08:00:00Z"), filer), 200)

    response = api.create_video_asset(
        video_asset_payload(
            incident_number="INC-2026-0669",
            device_serial="AXON-0669",
            officer_badge="B-1168",
            recorded_start_at="2026-06-26T09:00:00Z",
            duration_ms=900000,
            classification="ROUTINE",
            retention_category="INVESTIGATIVE_3Y",
            scheduled_purge_at="2029-06-26T00:00:00Z",
        ),
        filer,
    )

    validate_error(response, ERR_UNAUTHORIZED, 403)
    assert_total_count(api.list_video_assets(CLERK_HEADERS), 0)


def test_requester_may_not_file_their_own_request(api):
    """Intake stays a counter operation even when the filer addresses their own file.

    PRD: "When the headers are well-formed but the named role is not among the roles authorised for the addressed endpoint, the call is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/requester_may_set_the_clock_but_may_not_write_the_case_file
    """
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    filer = make_requester_headers(requester["id"])

    response = api.create_request(
        request_payload(
            requester["id"],
            received_at="2026-08-01T00:00:00Z",
            subject_incident_number="INC-2026-0669",
            requested_date_from="2026-06-26T00:00:00Z",
            requested_date_to="2026-06-27T00:00:00Z",
            scope_narrative="Self-filed request",
        ),
        filer,
    )

    validate_error(response, ERR_UNAUTHORIZED, 403)
    assert get_requester(api, requester["id"])["open_request_count"] == 0
    assert_total_count(api.list_requests(filer, params={"requester_id": requester["id"]}), 0)


def test_staff_directory_is_readable_by_the_operational_roles(api):
    """A technician, a clerk and a supervisor all read the identical certification row.

    PRD: "A newly registered staff member begins with `open_qa_assignment_count` at 0; that counter tracks how many redaction tasks currently name this person as their booked quality reviewer and sit awaiting a verdict, and it is maintained by the review workflow of §3.6."

    Design: Corner/rbac/staff_directory_reads_exclude_the_requester
    """
    tech = create_staff(api, "Tech Two", "TECHNICIAN", 2)

    as_technician = assert_object_response(
        api.get_staff(tech["id"], make_technician_headers(tech["id"])), 200
    )
    as_clerk = assert_object_response(api.get_staff(tech["id"], CLERK_HEADERS), 200)
    as_supervisor = assert_object_response(api.get_staff(tech["id"], SUPERVISOR_HEADERS), 200)

    assert_fields(
        as_technician,
        role_type="TECHNICIAN",
        redaction_certification_level=2,
        open_qa_assignment_count=0,
    )
    assert as_clerk == as_technician
    assert as_supervisor == as_technician


def test_requester_is_refused_the_staff_directory_read(api):
    """The filer is absent from the staff-read role list that five other roles are on.

    PRD: "When the headers are well-formed but the named role is not among the roles authorised for the addressed endpoint, the call is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/staff_directory_reads_exclude_the_requester
    """
    tech = create_staff(api, "Tech Two", "TECHNICIAN", 2)
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")

    response = api.get_staff(tech["id"], make_requester_headers(requester["id"]))

    validate_error(response, ERR_UNAUTHORIZED, 403)
    assert get_staff(api, tech["id"])["redaction_certification_level"] == 2
