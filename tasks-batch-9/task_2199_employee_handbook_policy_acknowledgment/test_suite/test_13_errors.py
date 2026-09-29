"""Graded error surfaces: auth gates, body foreign keys and per-actor authorization."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    add_addendum,
    api_client,
    build_user_headers,
    make_admin_headers,
    make_author_headers,
    make_counsel_headers,
    mint_version,
    new_document,
    new_jurisdiction,
    new_reviewer,
    refresh_addendum,
    refresh_review,
    refresh_version,
    request_review,
    submit_for_review,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_the_three_header_gates_answer_three_distinct_codes_and_statuses():
    """PRD §2.8: "First come the authentication and authorization checks: (1) presence
    and non-emptiness of both `X-User-ID` and `X-User-Role`, yielding
    `ERR_MISSING_AUTH_HEADERS`; (2) recognition of `X-User-Role` as one of the six
    declared roles, yielding `ERR_UNKNOWN_ROLE`; (3) for endpoints whose authorized
    roles include `Employee`, `PeopleManager` or `LegalCounsel`, resolution of
    `X-User-ID` against the backing entity, yielding `ERR_ACTOR_IDENTITY_UNKNOWN`".

    Design: Corner/errors/corner_auth_gate_errors_are_three_distinct_codes_and_statuses
    """
    jurisdiction = new_jurisdiction()
    reviewer = new_reviewer(jurisdiction["id"])
    version = mint_version(new_document(), [jurisdiction["id"]])
    addendum = add_addendum(version["id"], jurisdiction["id"])

    validate_error(
        api_client.approve_addendum(
            addendum["id"], make_counsel_headers(NON_EXISTENT_UUID)
        ),
        ApiErrorId.ERR_ACTOR_IDENTITY_UNKNOWN,
    )
    validate_error(
        api_client.approve_addendum(addendum["id"], {}),
        ApiErrorId.ERR_MISSING_AUTH_HEADERS,
    )
    validate_error(
        api_client.approve_addendum(
            addendum["id"], build_user_headers(reviewer["id"], "GeneralCounselIntern")
        ),
        ApiErrorId.ERR_UNKNOWN_ROLE,
    )

    untouched = refresh_addendum(addendum["id"])
    assert untouched["status"] == "DRAFT", (
        "three refused header gates must leave the addendum in DRAFT, got "
        f"{untouched['status']}"
    )
    assert untouched["approved_by_reviewer_id"] is None, (
        f"no reviewer may be recorded, got {untouched['approved_by_reviewer_id']}"
    )

    approved = validate_success(
        api_client.approve_addendum(
            addendum["id"], make_counsel_headers(reviewer["id"])
        )
    )
    assert approved["status"] == "APPROVED", (
        "the same call with a resolvable counsel identity must succeed, got "
        f"{approved['status']}"
    )
    assert approved["approved_by_reviewer_id"] == reviewer["id"]


def test_unresolvable_body_foreign_keys_answer_the_referenced_entity_error():
    """PRD §2.8: "Next, foreign keys named in the request body are resolved, yielding
    `ERR_REFERENCED_ENTITY_NOT_FOUND` (404)."

    Design: Corner/errors/corner_body_foreign_keys_on_link_endpoints_must_resolve
    """
    from test_helpers import (
        create_addendum_payload,
        create_legal_review_payload,
        new_package,
        refresh_package,
    )

    jurisdiction = new_jurisdiction()
    version = mint_version(new_document(), [jurisdiction["id"]])
    package = new_package([jurisdiction["id"]], "2026-09-01T00:00:00Z")

    validate_error(
        api_client.add_release_item(
            package["id"],
            {"policy_version_id": NON_EXISTENT_UUID},
            make_admin_headers(),
        ),
        ApiErrorId.ERR_REFERENCED_ENTITY_NOT_FOUND,
    )
    validate_error(
        api_client.create_addendum(
            version["id"],
            create_addendum_payload(NON_EXISTENT_UUID),
            make_author_headers(),
        ),
        ApiErrorId.ERR_REFERENCED_ENTITY_NOT_FOUND,
    )
    validate_error(
        api_client.create_legal_review(
            version["id"],
            create_legal_review_payload(
                jurisdiction["id"], NON_EXISTENT_UUID, "2026-08-20T00:00:00Z"
            ),
            make_author_headers(),
        ),
        ApiErrorId.ERR_REFERENCED_ENTITY_NOT_FOUND,
    )

    for lister, params in (
        (api_client.list_release_items, {"release_package_id": package["id"]}),
        (api_client.list_addenda, {"policy_version_id": version["id"]}),
        (api_client.list_legal_reviews, {"policy_version_id": version["id"]}),
    ):
        params["limit"] = 100
        _rows, meta = validate_paginated(lister(make_admin_headers(), params=params))
        assert meta["total_count"] == 0, (
            "a refused link creation must persist no row, got "
            f"{meta['total_count']} for {params}"
        )

    assert refresh_package(package["id"])["status"] == "DRAFT"
    assert refresh_version(version["id"])["status"] == "DRAFT"


def test_counsel_authorization_is_scoped_per_review_and_per_jurisdiction():
    """PRD §2.1: "A `LegalCounsel` acting on a legal review must be the review's own
    assigned reviewer: a mismatch against the review's `reviewer_id` yields
    `ERR_NOT_ASSIGNED_REVIEWER` (403) on both taking up the review and deciding it."
    PRD §3.2: "the acting reviewer's own `jurisdiction_id` must equal the addendum's
    `jurisdiction_id`, or the attempt is refused with
    `ERR_REVIEWER_JURISDICTION_MISMATCH` (403)".  PRD §3.3: "Counsel then takes up the
    work, moving their review `REQUESTED → IN_PROGRESS`. This requires the review to be
    in `REQUESTED`, the acting reviewer to be the review's own `reviewer_id`, and the
    owning version to be in `IN_LEGAL_REVIEW`."

    Design: Corner/errors/corner_reviewer_authorization_is_per_review_and_per_jurisdiction
    """
    home = new_jurisdiction(min_legal_review_days=5)
    other = new_jurisdiction(min_legal_review_days=5, retention_years=7)
    assigned = new_reviewer(home["id"])
    colleague = new_reviewer(home["id"])
    outsider = new_reviewer(other["id"])

    version = mint_version(new_document(), [home["id"]])
    addendum = add_addendum(version["id"], home["id"])
    review = request_review(version["id"], home["id"], assigned["id"])
    version = submit_for_review(version["id"])
    assert version["status"] == "IN_LEGAL_REVIEW"
    assert review["status"] == "REQUESTED"

    validate_error(
        api_client.start_legal_review(
            review["id"], make_counsel_headers(colleague["id"])
        ),
        ApiErrorId.ERR_NOT_ASSIGNED_REVIEWER,
    )
    validate_error(
        api_client.approve_addendum(
            addendum["id"], make_counsel_headers(outsider["id"])
        ),
        ApiErrorId.ERR_REVIEWER_JURISDICTION_MISMATCH,
    )

    held = refresh_review(review["id"])
    assert held["status"] == "REQUESTED", (
        "holding the counsel role is not authorization, so the review must stay "
        f"REQUESTED, got {held['status']}"
    )
    assert refresh_addendum(addendum["id"])["status"] == "DRAFT", (
        "an out-of-jurisdiction counsel must not move the addendum off DRAFT"
    )

    approved = validate_success(
        api_client.approve_addendum(
            addendum["id"], make_counsel_headers(assigned["id"])
        )
    )
    assert approved["status"] == "APPROVED", (
        f"the licensed counsel must succeed on the addendum, got {approved['status']}"
    )
    assert approved["approved_by_reviewer_id"] == assigned["id"], (
        "the acting reviewer's identifier must be recorded, got "
        f"{approved['approved_by_reviewer_id']}"
    )

    started = validate_success(
        api_client.start_legal_review(
            review["id"], make_counsel_headers(assigned["id"])
        )
    )
    assert started["status"] == "IN_PROGRESS", (
        "the identical call from the assigned reviewer must succeed, got "
        f"{started['status']}"
    )
    assert started["reviewer_id"] == assigned["id"]
    assert started["round_no"] == 1, (
        f"taking up a first-round review leaves round_no at 1, got {started['round_no']}"
    )


def test_ownership_is_read_off_the_assignment_not_off_the_acting_identity():
    """PRD §3.7: "The acting party must be entitled: an `Employee` actor must be the
    assignment's own `employee_id`, or the actor must be an `HRComplianceAdmin`
    recording a proxy acknowledgment with `method` of `ATTESTED`; a mismatch is
    `ERR_NOT_ASSIGNMENT_OWNER`." ... "When `method` is `ATTESTED`, the assignment
    jurisdiction's `proxy_ack_permitted` must be true **and** the actor must be an
    `HRComplianceAdmin`, or `ERR_PROXY_ACK_NOT_PERMITTED` (409)."

    Design: Corner/errors/corner_only_the_assignee_or_an_attesting_admin_may_acknowledge
    """
    from test_helpers import (
        create_acknowledgment_payload,
        deliver,
        make_employee_headers,
        refresh_assignment,
        refresh_employee,
        refresh_package,
        setup_released_scenario,
        sole_assignment,
    )

    ctx = setup_released_scenario(
        jurisdiction={
            "min_legal_review_days": 5,
            "esign_permitted": True,
            "proxy_ack_permitted": True,
            "ack_window_buffer_days": 3,
        },
        extra_employees=1,
        effective_date="2026-09-01T00:00:00Z",
    )
    assert ctx["jurisdiction"]["proxy_ack_permitted"] is True
    subject, bystander = ctx["employee"], ctx["extras"][0]
    asg1 = ctx["assignment"]
    asg2 = deliver(sole_assignment(ctx["package"]["id"], bystander["id"])["id"])
    assert asg1["ack_state"] == "PENDING"
    assert asg2["ack_state"] == "PENDING"

    validate_error(
        api_client.create_acknowledgment(
            create_acknowledgment_payload(
                asg1["id"], signature_text="Bystander signing for the subject"
            ),
            make_employee_headers(bystander["id"]),
        ),
        ApiErrorId.ERR_NOT_ASSIGNMENT_OWNER,
    )
    assert refresh_assignment(asg1["id"])["ack_state"] == "PENDING", (
        "a refused capture must leave the subject's assignment PENDING"
    )
    assert refresh_employee(bystander["id"])["open_ack_count"] == 1, (
        "the bystander's own obligation is untouched, got "
        f"{refresh_employee(bystander['id'])['open_ack_count']}"
    )

    ack = validate_success(
        api_client.create_acknowledgment(
            create_acknowledgment_payload(
                asg1["id"],
                method="ATTESTED",
                signature_text="HR attests a verbal acknowledgment",
            ),
            make_admin_headers(),
        ),
        201,
    )
    assert ack["employee_id"] == subject["id"], (
        "the acknowledgment's employee_id is copied from the assignment, never from "
        f"the acting admin, got {ack['employee_id']}"
    )
    assert ack["employee_id"] != bystander["id"]
    assert ack["method"] == "ATTESTED", (
        f"the recorded method must be ATTESTED, got {ack['method']}"
    )
    assert ack["status"] == "EFFECTIVE", (
        f"a fresh capture is EFFECTIVE, got {ack['status']}"
    )

    assert refresh_assignment(asg1["id"])["ack_state"] == "ACKNOWLEDGED", (
        "the proxy capture must satisfy the subject's assignment"
    )
    assert refresh_employee(subject["id"])["open_ack_count"] == 0, (
        "the subject's obligation is discharged, got "
        f"{refresh_employee(subject['id'])['open_ack_count']}"
    )
    assert refresh_assignment(asg2["id"])["ack_state"] == "PENDING", (
        "the bystander's assignment must be unaffected"
    )
    assert refresh_package(ctx["package"]["id"])["status"] == "RELEASED", (
        "one open assignment remains so the package stays RELEASED, got "
        f"{refresh_package(ctx['package']['id'])['status']}"
    )


def test_the_grant_ceiling_consults_the_conservative_score_not_the_aggregate():
    """PRD §3.9: "The request's `risk_score_conservative` must then be **strictly
    below** 70.00; a score of exactly 70.00 or higher is refused with
    `ERR_EXCEPTION_RISK_TOO_HIGH` (409)." ... "it is the conservative variant — never
    the aggregate — that the grant gate reads." ... "A legal `DENY` moves the request
    `MANAGER_APPROVED → DENIED`, records `deciding_reviewer_id`, leaves `expires_at`
    null, and leaves the linked assignment at `PENDING`."

    Design: Corner/errors/corner_grant_ceiling_reads_the_conservative_variant_only
    """
    from test_helpers import (
        assert_same_instant,
        legal_decide,
        refresh_assignment,
        refresh_employee,
        refresh_exception,
        setup_manager_approved_exception,
    )

    ctx = setup_manager_approved_exception(
        reason_code="ROLE_CONFLICT",
        requested_days=180,
        justification="Cannot comply while acting as safety marshal.",
        document={"category": "SAFETY"},
        jurisdiction={"ack_deadline_days": 30, "min_legal_review_days": 5},
        effective_date="2026-09-01T00:00:00Z",
    )
    request, assignment = ctx["exception"], ctx["assignment"]
    assert_same_instant(
        refresh_assignment(assignment["id"])["due_date"],
        "2026-09-08T00:00:00.000Z",
        "a SAFETY document caps the 30-day jurisdiction deadline at 7 days",
    )

    assert request["prior_exception_count"] == 0, (
        f"this is the employee's first request, got {request['prior_exception_count']}"
    )
    assert request["assignment_id"] == assignment["id"], (
        f"the sole pending assignment must be linked, got {request['assignment_id']}"
    )
    assert float(request["risk_score_aggregate"]) == 64.00, (
        "0.20*65 + 0.15*100 + 0.25*0 + 0.40*90 is 64.00, got "
        f"{request['risk_score_aggregate']}"
    )
    assert float(request["risk_score_conservative"]) == 85.60, (
        "0.60*100 + 0.40*64.00 is 85.60, got "
        f"{request['risk_score_conservative']}"
    )
    assert request["status"] == "MANAGER_APPROVED", (
        f"the manager stage still approves, got {request['status']}"
    )
    assert request["approving_manager_id"] == ctx["manager"]["id"]

    validate_error(
        api_client.legal_decision(
            request["id"],
            {"decision": "APPROVE", "note": "Attempting grant"},
            make_counsel_headers(ctx["reviewer_2"]["id"]),
        ),
        ApiErrorId.ERR_EXCEPTION_RISK_TOO_HIGH,
    )
    blocked = refresh_exception(request["id"])
    assert blocked["status"] == "MANAGER_APPROVED", (
        "a conservative score of 85.60 is at or above the 70.00 ceiling, so the "
        f"request must stay MANAGER_APPROVED, got {blocked['status']}"
    )
    assert blocked["expires_at"] is None, (
        f"a refused grant must leave expires_at null, got {blocked['expires_at']}"
    )
    assert blocked["deciding_reviewer_id"] is None, (
        f"no deciding reviewer may be recorded, got {blocked['deciding_reviewer_id']}"
    )
    assert refresh_assignment(assignment["id"])["ack_state"] == "PENDING"
    assert refresh_employee(ctx["employee"]["id"])["open_ack_count"] == 1, (
        "a refused grant must not release the obligation, got "
        f"{refresh_employee(ctx['employee']['id'])['open_ack_count']}"
    )

    denied = legal_decide(
        request["id"], ctx["reviewer_2"]["id"], "DENY", note="Risk above ceiling"
    )
    assert denied["status"] == "DENIED", (
        "the ceiling gates the grant only, so a denial must still land, got "
        f"{denied['status']}"
    )
    assert denied["deciding_reviewer_id"] == ctx["reviewer_2"]["id"], (
        f"the denial records the deciding reviewer, got {denied['deciding_reviewer_id']}"
    )
    assert denied["expires_at"] is None, (
        f"a denial leaves expires_at null, got {denied['expires_at']}"
    )
    assert refresh_assignment(assignment["id"])["ack_state"] == "PENDING", (
        "a denial leaves the linked assignment at PENDING"
    )
    assert refresh_employee(ctx["employee"]["id"])["open_ack_count"] == 1
