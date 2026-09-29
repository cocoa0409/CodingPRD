"""Rejection paths whose whole point is which code wins, and what survives the refusal.

The ladder of §2.11 is authoritative, so each scenario is built so that more
than one condition could plausibly fire and only the higher rung may answer.
Every refusal is followed by a readback proving nothing moved.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
)

from test_helpers.api_errors import (
    ERR_DUPLICATE_MATTER_NUMBER,
    ERR_FEE_STATE_INVALID,
    ERR_LETTER_STATE_INVALID,
    ERR_NOTIFICATION_STATE_INVALID,
    ERR_RECORD_STATE_INVALID,
    ERR_REQUESTER_MISMATCH,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STAFF_NOT_FOUND,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
)
from test_helpers.assertions import (
    assert_created,
    assert_fields,
    assert_ids,
    assert_modified,
    assert_total_count,
)
from test_helpers.factories import (
    adjudication_payload,
    appeal_decision_payload,
    appeal_payload,
    denial_letter_payload,
    inclusion_payload,
    invoice_payload,
    litigation_hold_payload,
    notification_payload,
    objection_payload,
    payment_payload,
    redaction_task_payload,
    staff_payload,
    submit_qa_payload,
    video_asset_payload,
)
from test_helpers.fixtures import (
    adjudicate,
    assert_claim,
    attach_record,
    clarify_scope,
    create_asset,
    create_depicted_individual,
    create_request,
    create_requester,
    create_staff,
    get_asset,
    get_claim,
    get_individual,
    get_letter,
    get_record,
    get_request,
    get_staff,
    get_task,
    issue_notice,
    open_task,
    produce_release,
    record_verdict,
    rule_inclusion,
    submit_for_qa,
)
from test_helpers.test_users import (
    CLERK_HEADERS,
    SUPERVISOR_HEADERS,
    headers_for_role,
    make_clerk_headers,
    make_counsel_headers,
    make_requester_headers,
    make_reviewer_headers,
    make_technician_headers,
)


def test_an_absent_or_empty_identity_header_is_unauthenticated(api):
    """A missing X-User-Role and an empty X-User-ID both fail before any schema check.

    PRD: "If either header is absent or empty, if `X-User-Role` does not name one of the six roles declared below, or if the role is one of the entity-backed roles and `X-User-ID` resolves to no persisted row of its backing entity, the call is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/missing_x_user_headers_or_unresolvable_identity_returns_unauthenticated
    """
    roleless = api.create_video_asset(
        video_asset_payload(incident_number="INC-2026-0661"),
        {"X-User-ID": "clerk-1", "Content-Type": "application/json"},
    )
    validate_error(roleless, ERR_UNAUTHENTICATED, 401)

    empty_id = api.create_video_asset(
        video_asset_payload(incident_number="INC-2026-0661"), make_clerk_headers("")
    )

    validate_error(empty_id, ERR_UNAUTHENTICATED, 401)
    assert_total_count(api.list_video_assets(SUPERVISOR_HEADERS), 0)


def test_an_undeclared_role_or_unresolvable_staff_identity_is_unauthenticated(api):
    """A role nobody declared, and a reviewer id backing no staff row, both fail at rung one.

    PRD: "If either header is absent or empty, if `X-User-Role` does not name one of the six roles declared below, or if the role is one of the entity-backed roles and `X-User-ID` resolves to no persisted row of its backing entity, the call is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/missing_x_user_headers_or_unresolvable_identity_returns_unauthenticated
    """
    undeclared = api.get_request(
        NON_EXISTENT_UUID, headers_for_role("PressOfficer", "press-1")
    )
    validate_error(undeclared, ERR_UNAUTHENTICATED, 401)

    ghost_reviewer = api.list_redaction_tasks(make_reviewer_headers(NON_EXISTENT_UUID))

    validate_error(ghost_reviewer, ERR_UNAUTHENTICATED, 401)


def _request_with_one_asserted_claim(api):
    """A RESPONSIVE record carrying a single ASSERTED privacy claim, fee never assessed."""
    counsel_a = create_staff(api, "Counsel A", "COUNSEL", 3)
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset = create_asset(
        api,
        incident_number="INC-2026-0662",
        device_serial="AXON-0662",
        officer_badge="B-1153",
        recorded_start_at="2026-07-15T11:00:00Z",
        duration_ms=600000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-15T00:00:00Z",
    )
    request = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0662",
        requested_date_from="2026-07-15T00:00:00Z",
        requested_date_to="2026-07-16T00:00:00Z",
        scope_narrative="Ten minutes of footage for INC-2026-0662",
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative="The whole ten minutes",
        requested_date_from="2026-07-15T00:00:00Z",
        requested_date_to="2026-07-15T23:59:59Z",
    )
    record = attach_record(api, request["id"], asset["id"])
    rule_inclusion(api, record["id"], "RESPONSIVE")
    claim = assert_claim(
        api, record["id"], counsel_a["id"], "PERSONAL_PRIVACY", "PARTIAL_REDACT"
    )
    return {
        "request_id": request["id"],
        "record_id": record["id"],
        "claim_id": claim["id"],
        "counsel_a_id": counsel_a["id"],
    }


def test_a_clerk_may_not_register_staff_or_issue_an_invoice(api):
    """Both endpoints are the supervisor's alone, so the clerk is refused on both.

    PRD: "When the headers are well-formed but the named role is not among the roles authorised for the addressed endpoint, the call is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/errors/role_outside_the_endpoints_role_list_returns_unauthorized
    """
    scenario = _request_with_one_asserted_claim(api)

    hiring = api.create_staff(staff_payload("Sneaky Hire", "TECHNICIAN", 1), CLERK_HEADERS)
    validate_error(hiring, ERR_UNAUTHORIZED, 403)

    invoicing = api.issue_invoice(
        scenario["request_id"], invoice_payload("Clerk tries to bill"), CLERK_HEADERS
    )

    validate_error(invoicing, ERR_UNAUTHORIZED, 403)
    assert_fields(
        get_staff(api, scenario["counsel_a_id"]),
        full_name="Counsel A",
        role_type="COUNSEL",
    )
    assert_fields(
        get_request(api, scenario["request_id"]),
        fee_status="NOT_ASSESSED",
        invoiced_total_cents=0,
    )


def test_the_role_gate_outranks_every_state_check_on_adjudication(api):
    """A supervisor adjudicating is refused for the role, and the claim never moves.

    PRD: "When the headers are well-formed but the named role is not among the roles authorised for the addressed endpoint, the call is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/errors/role_outside_the_endpoints_role_list_returns_unauthorized
    """
    scenario = _request_with_one_asserted_claim(api)

    response = api.adjudicate_claim(
        scenario["claim_id"],
        adjudication_payload("OVERRULED", adjudication_note="Not counsel's call"),
        SUPERVISOR_HEADERS,
    )

    validate_error(response, ERR_UNAUTHORIZED, 403)
    # `disposition` is an adjudication input, which the PRD says "is also the
    # `status` the claim will carry afterwards" — the claim resource itself
    # carries `status`, not a separate disposition field.
    assert_fields(
        get_claim(api, scenario["claim_id"]),
        status="ASSERTED",
        adjudicated_at=None,
        adjudicated_by_staff_id=None,
    )
    assert_fields(get_record(api, scenario["record_id"]), unadjudicated_claim_count=1)


def test_the_role_gate_outranks_the_path_lookup_on_notification(api):
    """A supervisor addressing a non-existent individual is refused for the role, not the id.

    PRD: "The system evaluates them as a single ordered ladder and stops at the first violation, so the reported `error_id` is fully determined by the ladder position rather than by which check happens to be cheapest."

    Design: Corner/errors/role_outside_the_endpoints_role_list_returns_unauthorized
    """
    _request_with_one_asserted_claim(api)

    response = api.issue_notification(
        NON_EXISTENT_UUID, notification_payload("EMAIL"), SUPERVISOR_HEADERS
    )

    validate_error(response, ERR_UNAUTHORIZED, 403)


def _record_with_one_draft_face_task(api):
    """A RESPONSIVE ten-minute record carrying one DRAFT FACE task over the whole clip."""
    tech = create_staff(api, "Tess Tech", "TECHNICIAN", 3)
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset = create_asset(
        api,
        incident_number="INC-2026-0663",
        device_serial="AXON-0663",
        officer_badge="B-1154",
        recorded_start_at="2026-07-16T13:00:00Z",
        duration_ms=600000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-16T00:00:00Z",
    )
    request = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0663",
        requested_date_from="2026-07-16T00:00:00Z",
        requested_date_to="2026-07-17T00:00:00Z",
        scope_narrative="Ten minutes of footage for INC-2026-0663",
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative="The whole ten minutes",
        requested_date_from="2026-07-16T00:00:00Z",
        requested_date_to="2026-07-16T23:59:59Z",
    )
    record = attach_record(api, request["id"], asset["id"])
    rule_inclusion(api, record["id"], "RESPONSIVE")
    task = open_task(api, record["id"], tech["id"], "FACE", 0, 600000)
    return {
        "record_id": record["id"],
        "task_id": task["id"],
        "tech_id": tech["id"],
    }


def test_an_unknown_assigned_technician_is_a_staff_lookup_failure(api):
    """The body foreign key is resolved long before the certification comparison.

    PRD: "Foreign keys supplied inside a request body are resolved after the path, and each has its own code: an unknown `requester_id` yields `ERR_REQUESTER_NOT_FOUND`; an unknown `video_asset_id` yields `ERR_VIDEO_ASSET_NOT_FOUND`; an unknown `exemption_claim_id` yields `ERR_EXEMPTION_CLAIM_NOT_FOUND`; an unknown `depicted_individual_id` yields `ERR_DEPICTED_INDIVIDUAL_NOT_FOUND`; an unknown `responsive_record_id` yields `ERR_RESPONSIVE_RECORD_NOT_FOUND`; and an unknown `assigned_technician_id`, `qa_reviewer_id` or `asserted_by_staff_id` yields `ERR_STAFF_NOT_FOUND`."

    Design: Corner/errors/unknown_staff_foreign_keys_return_staff_not_found
    """
    scenario = _record_with_one_draft_face_task(api)

    response = api.create_redaction_task(
        scenario["record_id"],
        redaction_task_payload(NON_EXISTENT_UUID, "AUDIO_IDENTIFIER", 0, 600000),
        SUPERVISOR_HEADERS,
    )

    validate_error(response, ERR_STAFF_NOT_FOUND, 404)
    assert_total_count(
        api.list_redaction_tasks(
            CLERK_HEADERS, params={"responsive_record_id": scenario["record_id"]}
        ),
        1,
    )


def test_an_unknown_qa_reviewer_is_a_staff_lookup_failure(api):
    """The booking never happens, so the task keeps its DRAFT posture and no reviewer.

    PRD: "5. Existence of every foreign key supplied in the body, with the per-field mapping of §2.5 — `ERR_REQUESTER_NOT_FOUND`, `ERR_VIDEO_ASSET_NOT_FOUND`, `ERR_EXEMPTION_CLAIM_NOT_FOUND`, `ERR_DEPICTED_INDIVIDUAL_NOT_FOUND`, `ERR_RESPONSIVE_RECORD_NOT_FOUND` or `ERR_STAFF_NOT_FOUND`."

    Design: Corner/errors/unknown_staff_foreign_keys_return_staff_not_found
    """
    scenario = _record_with_one_draft_face_task(api)

    response = api.submit_qa(
        scenario["task_id"],
        submit_qa_payload(
            NON_EXISTENT_UUID, 10, "2026-08-02T09:00:00Z", "2026-08-02T09:30:00Z"
        ),
        make_technician_headers(scenario["tech_id"]),
    )

    validate_error(response, ERR_STAFF_NOT_FOUND, 404)
    assert_fields(
        get_task(api, scenario["task_id"]),
        status="DRAFT",
        qa_reviewer_id=None,
        qa_window_start_at=None,
        qa_window_end_at=None,
        logged_labor_minutes=0,
    )


def _two_filers_one_request(api):
    """Filer A owns a freshly intaken request; filer B owns nothing at all."""
    filer_a = create_requester(api, "Ada Filer", "ada@example.org", "GENERAL_PUBLIC")
    filer_b = create_requester(api, "Bo Filer", "bo@example.org", "GENERAL_PUBLIC")
    request = create_request(
        api,
        filer_a["id"],
        subject_incident_number="INC-2026-0664",
        requested_date_from="2026-07-17T00:00:00Z",
        requested_date_to="2026-07-18T00:00:00Z",
        scope_narrative="Footage from the INC-2026-0664 stop",
    )
    return {
        "request_id": request["id"],
        "filer_a_id": filer_a["id"],
        "filer_b_id": filer_b["id"],
    }


def test_a_filer_may_not_read_another_filers_request(api):
    """B is refused on A's request while A reads it perfectly well.

    PRD: "On `GET /records/requests/{id}`, `GET /records/requests`, `POST /records/requests/{id}/payments` and `POST /records/denial-letters/{id}/appeal`, an actor presenting the `Requester` role may only reach a public records request whose `requester_id` equals the presented `X-User-ID`; any attempt to read or act on another filer's request is rejected with `ERR_REQUESTER_MISMATCH` (HTTP 403)."

    Design: Corner/errors/requester_touching_another_filers_request_returns_requester_mismatch
    """
    scenario = _two_filers_one_request(api)

    intruder = api.get_request(
        scenario["request_id"], make_requester_headers(scenario["filer_b_id"])
    )
    validate_error(intruder, ERR_REQUESTER_MISMATCH, 403)

    owner = get_success_data(
        api.get_request(
            scenario["request_id"], make_requester_headers(scenario["filer_a_id"])
        )
    )

    assert_fields(
        owner,
        requester_id=scenario["filer_a_id"],
        processing_status="INTAKE",
        fee_status="NOT_ASSESSED",
    )


def test_a_filer_may_not_pay_another_filers_account(api):
    """The ownership rung answers before any fiscal check reads the fee dimension.

    PRD: "Note that this is a distinct failure from `ERR_UNAUTHORIZED`: the role is permitted at the endpoint, but the addressed resource belongs to someone else."

    Design: Corner/errors/requester_touching_another_filers_request_returns_requester_mismatch
    """
    scenario = _two_filers_one_request(api)

    response = api.post_payment(
        scenario["request_id"],
        payment_payload(500, "Paying a stranger's fee"),
        make_requester_headers(scenario["filer_b_id"]),
    )

    validate_error(response, ERR_REQUESTER_MISMATCH, 403)
    assert_total_count(
        api.list_ledger_entries(
            SUPERVISOR_HEADERS, params={"request_id": scenario["request_id"]}
        ),
        0,
    )
    assert_fields(
        get_request(api, scenario["request_id"]),
        deposit_paid_cents=0,
        deposit_balance_cents=0,
    )


def test_a_filer_may_not_list_another_filers_requests(api):
    """Filtering the collection by someone else's id is the same ownership failure.

    PRD: "6. Requester ownership on the four `Requester`-reachable request surfaces — `ERR_REQUESTER_MISMATCH`."

    Design: Corner/errors/requester_touching_another_filers_request_returns_requester_mismatch
    """
    scenario = _two_filers_one_request(api)

    response = api.list_requests(
        make_requester_headers(scenario["filer_b_id"]),
        params={"requester_id": scenario["filer_a_id"]},
    )

    validate_error(response, ERR_REQUESTER_MISMATCH, 403)


def _two_incidents_and_one_attorney(api):
    """Two catalogued recordings on two different incidents, both SCHEDULED and unlocked."""
    counsel = create_staff(api, "Dana Counsel", "COUNSEL", 3)
    asset_one = create_asset(
        api,
        incident_number="INC-2026-0665",
        device_serial="AXON-0665",
        officer_badge="B-1155",
        recorded_start_at="2026-07-18T21:00:00Z",
        duration_ms=600000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-18T00:00:00Z",
    )
    asset_two = create_asset(
        api,
        incident_number="INC-2026-0666",
        device_serial="AXON-0666",
        officer_badge="B-1156",
        recorded_start_at="2026-07-19T21:00:00Z",
        duration_ms=600000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-19T00:00:00Z",
    )
    return {
        "counsel_id": counsel["id"],
        "asset_one_id": asset_one["id"],
        "asset_two_id": asset_two["id"],
    }


def test_placing_the_hold_suspends_only_its_own_incident(api):
    """The three-link chain locks, suspends and counts exactly the matching recording.

    PRD: "Placement then fans out over every catalogued recording whose `incident_number` exactly equals the hold's `scope_incident_number`, in a three-link chain: because the hold became `ACTIVE`, each matching recording's `retention_locked` becomes true; because it became locked, the recording moves `SCHEDULED → SUSPENDED` and its `suspended_by_hold_id` is set to this hold's identifier; and because assets were suspended, the hold's `suspended_asset_count` is incremented once per suspended recording."

    Design: Corner/errors/matter_number_is_globally_unique_across_incidents
    """
    scenario = _two_incidents_and_one_attorney(api)

    response = api.create_litigation_hold(
        litigation_hold_payload(
            matter_number="LIT-2026-0044",
            scope_incident_number="INC-2026-0665",
            hold_type="LITIGATION",
        ),
        make_counsel_headers(scenario["counsel_id"]),
    )

    hold = assert_created(response)
    assert_fields(
        hold,
        status="ACTIVE",
        matter_number="LIT-2026-0044",
        scope_incident_number="INC-2026-0665",
        placed_at="2026-08-01T00:00:00Z",
        suspended_asset_count=1,
        released_at=None,
    )
    assert_fields(
        get_asset(api, scenario["asset_one_id"]),
        disposition_state="SUSPENDED",
        retention_locked=True,
        suspended_by_hold_id=hold["id"],
    )
    assert_fields(
        get_asset(api, scenario["asset_two_id"]),
        disposition_state="SCHEDULED",
        retention_locked=False,
        suspended_by_hold_id=None,
    )


def test_the_matter_number_may_not_be_reused_on_another_incident(api):
    """Global uniqueness bites even though the second hold covers different footage.

    PRD: "A `matter_number` is globally unique across every litigation hold ever placed, and a repeat is rejected with `ERR_DUPLICATE_MATTER_NUMBER` (HTTP 409)."

    Design: Corner/errors/matter_number_is_globally_unique_across_incidents
    """
    scenario = _two_incidents_and_one_attorney(api)
    first = assert_created(
        api.create_litigation_hold(
            litigation_hold_payload(
                matter_number="LIT-2026-0044",
                scope_incident_number="INC-2026-0665",
                hold_type="LITIGATION",
            ),
            make_counsel_headers(scenario["counsel_id"]),
        )
    )

    response = api.create_litigation_hold(
        litigation_hold_payload(
            matter_number="LIT-2026-0044",
            scope_incident_number="INC-2026-0666",
            hold_type="LITIGATION",
        ),
        make_counsel_headers(scenario["counsel_id"]),
    )

    validate_error(response, ERR_DUPLICATE_MATTER_NUMBER, 409)
    assert_fields(
        get_asset(api, scenario["asset_two_id"]),
        disposition_state="SCHEDULED",
        retention_locked=False,
        suspended_by_hold_id=None,
    )
    rows, _meta = assert_total_count(
        api.list_video_assets(
            SUPERVISOR_HEADERS, params={"suspended_by_hold_id": first["id"]}
        ),
        1,
    )
    assert_ids(rows, [scenario["asset_one_id"]])


def _victim_and_bystander_on_a_responsive_record(api):
    """A thirty-minute responsive recording depicting one victim and one bystander.

    The victim requires notification and therefore opens at PENDING; the
    bystander does not and therefore opens at NOT_REQUIRED.
    """
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset = create_asset(
        api,
        incident_number="INC-2026-0667",
        device_serial="AXON-0667",
        officer_badge="B-1157",
        recorded_start_at="2026-07-20T16:00:00Z",
        duration_ms=1800000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-20T00:00:00Z",
    )
    victim = create_depicted_individual(api, asset["id"], "SUBJECT-V1", "VICTIM")
    bystander = create_depicted_individual(api, asset["id"], "SUBJECT-B1", "BYSTANDER")
    request = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0667",
        requested_date_from="2026-07-20T00:00:00Z",
        requested_date_to="2026-07-21T00:00:00Z",
        scope_narrative="Thirty minutes of footage for INC-2026-0667",
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative="The whole half hour",
        requested_date_from="2026-07-20T00:00:00Z",
        requested_date_to="2026-07-20T23:59:59Z",
    )
    record = attach_record(api, request["id"], asset["id"])
    rule_inclusion(api, record["id"], "RESPONSIVE")
    return {
        "request_id": request["id"],
        "record_id": record["id"],
        "victim_id": victim["id"],
        "bystander_id": bystander["id"],
    }


def test_the_first_notice_starts_a_ten_day_objection_window(api):
    """A victim notified on 1 August has until 11 August to object.

    PRD: "Issuance moves the individual `PENDING → NOTIFIED`, stores the `notice_method`, stamps `notified_at` with the logical clock, and computes `objection_deadline_at` as `notified_at` advanced by fifteen whole days when the individual's `relationship` is `JUVENILE` and by ten whole days for every other relationship."

    Design: Corner/errors/notification_is_a_one_way_step_and_never_reaches_a_not_required_person
    """
    scenario = _victim_and_bystander_on_a_responsive_record(api)

    response = api.issue_notification(
        scenario["victim_id"], notification_payload("FIRST_CLASS_MAIL"), CLERK_HEADERS
    )

    individual = assert_modified(response)
    assert_fields(
        individual,
        notification_status="NOTIFIED",
        notice_method="FIRST_CLASS_MAIL",
        notified_at="2026-08-01T00:00:00Z",
        objection_deadline_at="2026-08-11T00:00:00Z",
    )
    assert_fields(get_request(api, scenario["request_id"]), open_notification_count=1)


def test_a_second_notice_to_the_same_person_is_refused(api):
    """Notification is a one-way step, so the stored method is never overwritten.

    PRD: "The individual must be at `notification_status` `PENDING` with `notification_required` true; anyone at `NOT_REQUIRED`, or already notified, is refused with `ERR_NOTIFICATION_STATE_INVALID`."

    Design: Corner/errors/notification_is_a_one_way_step_and_never_reaches_a_not_required_person
    """
    scenario = _victim_and_bystander_on_a_responsive_record(api)
    issue_notice(api, scenario["victim_id"], "FIRST_CLASS_MAIL")

    response = api.issue_notification(
        scenario["victim_id"], notification_payload("EMAIL"), CLERK_HEADERS
    )

    validate_error(response, ERR_NOTIFICATION_STATE_INVALID, 409)
    assert_fields(
        get_individual(api, scenario["victim_id"]),
        notification_status="NOTIFIED",
        notice_method="FIRST_CLASS_MAIL",
        objection_deadline_at="2026-08-11T00:00:00Z",
    )


def test_a_person_who_needs_no_notice_can_never_be_notified(api):
    """NOT_REQUIRED is terminal, so the bystander stays outside the notification flow.

    PRD: "That derivation picks the individual's initial position directly — a row that requires notification is created at `notification_status` `PENDING`, and a row that does not is created at `notification_status` `NOT_REQUIRED`, which is terminal and never gates a release."

    Design: Corner/errors/notification_is_a_one_way_step_and_never_reaches_a_not_required_person
    """
    scenario = _victim_and_bystander_on_a_responsive_record(api)

    response = api.issue_notification(
        scenario["bystander_id"], notification_payload("EMAIL"), CLERK_HEADERS
    )

    validate_error(response, ERR_NOTIFICATION_STATE_INVALID, 409)
    assert_fields(
        get_individual(api, scenario["bystander_id"]),
        notification_status="NOT_REQUIRED",
        notification_required=False,
        notified_at=None,
        notice_method=None,
        objection_deadline_at=None,
    )


def test_a_notice_after_an_objection_is_refused(api):
    """Having objected, the victim is past PENDING and cannot be notified again.

    PRD: "A recorded objection moves the individual `NOTIFIED → OBJECTED`, stores the `objection_basis`, and materialises a new exemption claim on the named record."

    Design: Corner/errors/notification_is_a_one_way_step_and_never_reaches_a_not_required_person
    """
    scenario = _victim_and_bystander_on_a_responsive_record(api)
    issue_notice(api, scenario["victim_id"], "FIRST_CLASS_MAIL")
    objection = assert_created(
        api.record_objection(
            scenario["victim_id"],
            objection_payload(scenario["record_id"], "VICTIM_STATUS"),
            CLERK_HEADERS,
        )
    )
    assert_fields(
        objection,
        claim_source="DEPICTED_OBJECTION",
        exemption_code="VICTIM_PROTECTION",
        depicted_individual_id=scenario["victim_id"],
        status="ASSERTED",
    )

    response = api.issue_notification(
        scenario["victim_id"], notification_payload("PERSONAL_SERVICE"), CLERK_HEADERS
    )

    validate_error(response, ERR_NOTIFICATION_STATE_INVALID, 409)
    assert_fields(
        get_individual(api, scenario["victim_id"]),
        notification_status="OBJECTED",
        objection_basis="VICTIM_STATUS",
        notice_method="FIRST_CLASS_MAIL",
    )
    assert_fields(get_request(api, scenario["request_id"]), open_notification_count=1)


def _scoped_request_with_a_candidate_record(api):
    """A scope-clarified request with one attached record still awaiting its ruling."""
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset = create_asset(
        api,
        incident_number="INC-2026-0668",
        device_serial="AXON-0668",
        officer_badge="B-1158",
        recorded_start_at="2026-07-21T10:00:00Z",
        duration_ms=600000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-21T00:00:00Z",
    )
    request = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0668",
        requested_date_from="2026-07-21T00:00:00Z",
        requested_date_to="2026-07-22T00:00:00Z",
        scope_narrative="Ten minutes of footage for INC-2026-0668",
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative="The whole ten minutes",
        requested_date_from="2026-07-21T00:00:00Z",
        requested_date_to="2026-07-21T23:59:59Z",
    )
    record = attach_record(api, request["id"], asset["id"])
    return {
        "request_id": request["id"],
        "record_id": record["id"],
        "asset_id": asset["id"],
    }


def test_the_first_ruling_carries_the_request_into_exemption_review(api):
    """Ruling the only candidate RESPONSIVE bubbles the request out of SCOPING.

    PRD: "A ruling of `RESPONSIVE` moves the record `CANDIDATE → RESPONSIVE` and does considerably more: the request's `responsive_record_count`, `is_critical_incident`, `statutory_deadline_at` and `open_notification_count` are all recomputed — and note that the deadline may jump backwards or forwards here, because the anchor can move from `received_at` to the earliest critical-incident `recorded_start_at` — and the first such ruling bubbles up to advance the request `SCOPING → EXEMPTION_REVIEW`."

    Design: Corner/errors/a_record_can_only_be_ruled_once
    """
    scenario = _scoped_request_with_a_candidate_record(api)

    response = api.rule_inclusion(
        scenario["record_id"], inclusion_payload("RESPONSIVE"), CLERK_HEADERS
    )

    record = assert_modified(response)
    assert_fields(record, inclusion_status="RESPONSIVE", release_posture="OPEN")
    assert_fields(
        get_request(api, scenario["request_id"]),
        processing_status="EXEMPTION_REVIEW",
        responsive_record_count=1,
    )
    assert_fields(get_asset(api, scenario["asset_id"]), retention_locked=True)


def test_a_record_cannot_be_ruled_a_second_time(api):
    """Neither a repeat of the same ruling nor a contradicting one is accepted.

    PRD: "The record must currently be at `CANDIDATE`; ruling twice is refused with `ERR_RECORD_STATE_INVALID`."

    Design: Corner/errors/a_record_can_only_be_ruled_once
    """
    scenario = _scoped_request_with_a_candidate_record(api)
    rule_inclusion(api, scenario["record_id"], "RESPONSIVE")

    repeat = api.rule_inclusion(
        scenario["record_id"], inclusion_payload("RESPONSIVE"), CLERK_HEADERS
    )
    validate_error(repeat, ERR_RECORD_STATE_INVALID, 409)

    contradiction = api.rule_inclusion(
        scenario["record_id"], inclusion_payload("EXCLUDED"), CLERK_HEADERS
    )

    validate_error(contradiction, ERR_RECORD_STATE_INVALID, 409)
    assert_fields(
        get_record(api, scenario["record_id"]),
        inclusion_status="RESPONSIVE",
        release_posture="OPEN",
    )
    assert_fields(
        get_request(api, scenario["request_id"]), responsive_record_count=1
    )


def _denied_request_with_an_issued_letter(api):
    """A fully withheld request denied in full by counsel A, letter at ISSUED."""
    counsel_a = create_staff(api, "Counsel A", "COUNSEL", 3)
    counsel_b = create_staff(api, "Counsel B", "COUNSEL", 3)
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset = create_asset(
        api,
        incident_number="INC-2026-0669",
        device_serial="AXON-0669",
        officer_badge="B-1159",
        recorded_start_at="2026-07-22T08:00:00Z",
        duration_ms=600000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-22T00:00:00Z",
    )
    request = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0669",
        requested_date_from="2026-07-22T00:00:00Z",
        requested_date_to="2026-07-23T00:00:00Z",
        scope_narrative="Ten minutes of footage for INC-2026-0669",
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative="The whole ten minutes",
        requested_date_from="2026-07-22T00:00:00Z",
        requested_date_to="2026-07-22T23:59:59Z",
    )
    record = attach_record(api, request["id"], asset["id"])
    rule_inclusion(api, record["id"], "RESPONSIVE")
    claim = assert_claim(
        api, record["id"], counsel_a["id"], "ONGOING_INVESTIGATION", "FULL_WITHHOLD"
    )
    adjudicate(
        api,
        claim["id"],
        counsel_b["id"],
        "SUSTAINED",
        adjudication_note="Active criminal investigation",
    )
    letter = assert_created(
        api.issue_denial_letter(
            request["id"],
            denial_letter_payload("FULL", "Petition the circuit court within thirty days"),
            make_counsel_headers(counsel_a["id"]),
        )
    )
    return {
        "request_id": request["id"],
        "requester_id": requester["id"],
        "record_id": record["id"],
        "claim_id": claim["id"],
        "letter_id": letter["id"],
        "counsel_a_id": counsel_a["id"],
        "counsel_b_id": counsel_b["id"],
    }


def test_a_decision_is_only_legal_while_the_letter_is_appealed(api):
    """An ISSUED letter and an already UPHELD letter are both closed to decisions.

    PRD: "The letter must be at `APPEALED`, or the call is refused with `ERR_LETTER_STATE_INVALID`."

    Design: Corner/errors/appeal_decision_outside_the_appealed_state_is_letter_state_invalid
    """
    scenario = _denied_request_with_an_issued_letter(api)

    too_early = api.decide_appeal(
        scenario["letter_id"],
        appeal_decision_payload("UPHELD"),
        make_counsel_headers(scenario["counsel_b_id"]),
    )
    validate_error(too_early, ERR_LETTER_STATE_INVALID, 409)
    assert_fields(get_letter(api, scenario["letter_id"]), status="ISSUED")

    assert_modified(
        api.file_appeal(
            scenario["letter_id"],
            appeal_payload("The investigation closed months ago."),
            make_requester_headers(scenario["requester_id"]),
        )
    )
    assert_modified(
        api.decide_appeal(
            scenario["letter_id"],
            appeal_decision_payload("UPHELD"),
            make_counsel_headers(scenario["counsel_b_id"]),
        )
    )

    too_late = api.decide_appeal(
        scenario["letter_id"],
        appeal_decision_payload("REVERSED"),
        make_counsel_headers(scenario["counsel_b_id"]),
    )

    validate_error(too_late, ERR_LETTER_STATE_INVALID, 409)
    assert_fields(get_letter(api, scenario["letter_id"]), status="UPHELD")


def test_the_attorney_who_issued_the_letter_may_not_decide_the_appeal(api):
    """Self-review is refused, and the appeal is left waiting for someone else.

    PRD: "Deciding the appeal returns to `LegalCounsel`, who supplies a `decision` of either `UPHELD` or `REVERSED`, and who may not be the attorney who issued the letter — a self-review is refused with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/errors/appeal_decision_outside_the_appealed_state_is_letter_state_invalid
    """
    scenario = _denied_request_with_an_issued_letter(api)
    appealed = assert_modified(
        api.file_appeal(
            scenario["letter_id"],
            appeal_payload("The investigation closed months ago."),
            make_requester_headers(scenario["requester_id"]),
        )
    )
    assert_fields(
        appealed,
        status="APPEALED",
        appeal_filed_at="2026-08-01T00:00:00Z",
        appeal_grounds="The investigation closed months ago.",
    )

    response = api.decide_appeal(
        scenario["letter_id"],
        appeal_decision_payload("UPHELD"),
        make_counsel_headers(scenario["counsel_a_id"]),
    )

    validate_error(response, ERR_SEGREGATION_OF_DUTIES, 409)
    assert_fields(
        get_letter(api, scenario["letter_id"]),
        status="APPEALED",
        appeal_decided_at=None,
    )
    assert_fields(get_request(api, scenario["request_id"]), processing_status="DENIED")


def test_upholding_the_denial_closes_the_request_and_touches_nothing_else(api):
    """The inert branch drives DENIED to CLOSED and leaves the sustained claim alone.

    PRD: "Where the letter's `denial_type` is `FULL` and the request sits at `DENIED`, the request advances `DENIED → CLOSED`."

    Design: Corner/errors/appeal_decision_outside_the_appealed_state_is_letter_state_invalid
    """
    scenario = _denied_request_with_an_issued_letter(api)
    api.file_appeal(
        scenario["letter_id"],
        appeal_payload("The investigation closed months ago."),
        make_requester_headers(scenario["requester_id"]),
    )

    response = api.decide_appeal(
        scenario["letter_id"],
        appeal_decision_payload("UPHELD"),
        make_counsel_headers(scenario["counsel_b_id"]),
    )

    letter = assert_modified(response)
    assert_fields(
        letter, status="UPHELD", appeal_decided_at="2026-08-01T00:00:00Z"
    )
    assert_fields(get_request(api, scenario["request_id"]), processing_status="CLOSED")
    assert_fields(get_claim(api, scenario["claim_id"]), status="SUSTAINED")
    assert_fields(
        get_record(api, scenario["record_id"]), inclusion_status="WITHHELD_IN_FULL"
    )


def test_an_upheld_letter_cannot_be_appealed_again(api):
    """Filing requires the ISSUED posture, which the upheld letter has long left.

    PRD: "The letter must be at `status` `ISSUED`, or the call is refused with `ERR_LETTER_STATE_INVALID`; the acting `X-User-ID` must equal the `requester_id` of the letter's request, or it is refused with `ERR_REQUESTER_MISMATCH`; and the logical clock must be at or before `appeal_deadline_at`, or it is refused with `ERR_WINDOW_CLOSED`."

    Design: Corner/errors/appeal_decision_outside_the_appealed_state_is_letter_state_invalid
    """
    scenario = _denied_request_with_an_issued_letter(api)
    api.file_appeal(
        scenario["letter_id"],
        appeal_payload("The investigation closed months ago."),
        make_requester_headers(scenario["requester_id"]),
    )
    api.decide_appeal(
        scenario["letter_id"],
        appeal_decision_payload("UPHELD"),
        make_counsel_headers(scenario["counsel_b_id"]),
    )

    response = api.file_appeal(
        scenario["letter_id"],
        appeal_payload("Trying a second bite at the apple."),
        make_requester_headers(scenario["requester_id"]),
    )

    validate_error(response, ERR_LETTER_STATE_INVALID, 409)
    assert_fields(
        get_letter(api, scenario["letter_id"]),
        status="UPHELD",
        appeal_grounds="The investigation closed months ago.",
    )


def _released_request_whose_fee_was_never_assessed(api):
    """A request carried all the way to RELEASED without a single fee estimate.

    The processing dimension therefore satisfies the release-readiness rung
    while the fee dimension is still at NOT_ASSESSED, which is the only way to
    reach the fee-state rung on the invoice endpoint.
    """
    tech = create_staff(api, "Tess Tech", "TECHNICIAN", 3)
    reviewer = create_staff(api, "Quinn Review", "REVIEWER", 3)
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset = create_asset(
        api,
        incident_number="INC-2026-0670",
        device_serial="AXON-0670",
        officer_badge="B-1160",
        recorded_start_at="2026-07-23T12:00:00Z",
        duration_ms=600000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-23T00:00:00Z",
    )
    request = create_request(
        api,
        requester["id"],
        subject_incident_number="INC-2026-0670",
        requested_date_from="2026-07-23T00:00:00Z",
        requested_date_to="2026-07-24T00:00:00Z",
        scope_narrative="Ten minutes of footage for INC-2026-0670",
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative="The whole ten minutes",
        requested_date_from="2026-07-23T00:00:00Z",
        requested_date_to="2026-07-23T23:59:59Z",
    )
    record = attach_record(api, request["id"], asset["id"])
    rule_inclusion(api, record["id"], "RESPONSIVE")
    task = open_task(api, record["id"], tech["id"], "FACE", 0, 600000)
    submit_for_qa(
        api, task["id"], tech["id"], reviewer["id"], 15,
        "2026-08-02T09:00:00Z", "2026-08-02T09:30:00Z",
    )
    record_verdict(api, task["id"], reviewer["id"], "PASS")
    package = produce_release(api, request["id"], "DIGITAL_DOWNLOAD")
    return {
        "request_id": request["id"],
        "record_id": record["id"],
        "task_id": task["id"],
        "package": package,
    }


def test_invoicing_a_request_whose_fee_was_never_assessed_is_a_fee_state_failure(api):
    """The readiness rung is satisfied, so the fee dimension is what refuses the call.

    PRD: "It requires `processing_status` to be `PARTIALLY_RELEASED`, `RELEASED` or `DENIED`, failing which it is refused with `ERR_REQUEST_NOT_RELEASE_READY`, and `fee_status` to be `ESTIMATED`, `DEPOSIT_DUE` or `DEPOSIT_PAID`, failing which it is refused with `ERR_FEE_STATE_INVALID` — invoicing a request whose fee was never assessed is exactly that failure."

    Design: Corner/errors/fiscal_calls_on_an_unassessed_request_return_fee_state_invalid
    """
    scenario = _released_request_whose_fee_was_never_assessed(api)
    assert_fields(
        get_request(api, scenario["request_id"]),
        processing_status="RELEASED",
        fee_status="NOT_ASSESSED",
    )

    response = api.issue_invoice(
        scenario["request_id"], invoice_payload("Bill it anyway"), SUPERVISOR_HEADERS
    )

    validate_error(response, ERR_FEE_STATE_INVALID, 409)
    assert_fields(
        get_request(api, scenario["request_id"]),
        fee_status="NOT_ASSESSED",
        invoiced_total_cents=0,
        fee_recognized_cents=0,
        deposit_balance_cents=0,
    )
    assert_total_count(
        api.list_ledger_entries(
            SUPERVISOR_HEADERS, params={"request_id": scenario["request_id"]}
        ),
        0,
    )


def test_a_released_request_with_an_unfinished_fee_dimension_stays_open(api):
    """Closure waits on SETTLED or WAIVED, neither of which an unassessed fee reaches.

    PRD: "A fulfilled request advances `RELEASED → CLOSED` as soon as its fee dimension finishes — that is, as soon as `fee_status` is `SETTLED` or `WAIVED` — which in practice happens inside the invoicing call or inside the payment that settles the invoice."

    Design: Corner/errors/fiscal_calls_on_an_unassessed_request_return_fee_state_invalid
    """
    scenario = _released_request_whose_fee_was_never_assessed(api)
    assert_fields(
        scenario["package"],
        package_kind="FINAL",
        included_record_count=1,
        produced_minutes=10,
        production_cost_cents=0,
    )

    api.issue_invoice(
        scenario["request_id"], invoice_payload("Bill it anyway"), SUPERVISOR_HEADERS
    )

    assert_fields(
        get_request(api, scenario["request_id"]),
        processing_status="RELEASED",
        fee_status="NOT_ASSESSED",
        billable_labor_minutes=15,
    )
    assert_fields(get_record(api, scenario["record_id"]), inclusion_status="RELEASED")
    assert_fields(get_task(api, scenario["task_id"]), approved_labor_minutes=15)
