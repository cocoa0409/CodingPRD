"""Role exclusivity and the two separation-of-duties rules on exception approval."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_same_instant,
    create_policy_document_payload,
    create_release_package_payload,
    make_admin_headers,
    make_author_headers,
    make_localizer_headers,
    make_manager_headers,
    mint_version,
    new_document,
    new_jurisdiction,
    refresh_version,
    validate_error,
    validate_paginated,
)


def test_exclusive_writes_are_refused_per_operation_while_the_shared_read_is_open():
    """PRD §2.1: "When the header pair is well-formed but the named role is not
    authorized for the endpoint being called, the request is refused with
    `ERR_ROLE_NOT_PERMITTED` at 403." ... "`PolicyAuthor` is the handbook author. It
    creates policy documents and mints versions" ... "`LocalizationSpecialist` owns
    translation and accessibility."  PRD §2.8: "(4) membership of the acting role in
    the endpoint's authorized role list, yielding `ERR_ROLE_NOT_PERMITTED`."

    Design: Corner/rbac/corner_exclusive_operations_are_rejected_for_every_other_role
    """
    jurisdiction = new_jurisdiction(min_legal_review_days=5)
    document = new_document()
    version = mint_version(document, [jurisdiction["id"]])
    assert version["status"] == "DRAFT"

    validate_error(
        api_client.create_release_package(
            create_release_package_payload(
                [jurisdiction["id"]], "2026-09-01T00:00:00Z", name="Author Package"
            ),
            make_author_headers(),
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
    )
    validate_error(
        api_client.create_policy_document(
            create_policy_document_payload(
                title="Admin Authored Handbook", category="LEAVE"
            ),
            make_admin_headers(),
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
    )
    validate_error(
        api_client.approve_policy_version(version["id"], make_localizer_headers()),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED,
    )

    _rows, meta = validate_paginated(
        api_client.list_release_packages(
            make_admin_headers(), params={"status": "DRAFT", "limit": 100}
        )
    )
    assert meta["total_count"] == 0, (
        "the refused package creation must persist nothing, got "
        f"{meta['total_count']}"
    )
    _rows, meta = validate_paginated(
        api_client.list_policy_documents(
            make_admin_headers(), params={"category": "LEAVE", "limit": 100}
        )
    )
    assert meta["total_count"] == 0, (
        f"the refused document creation must persist nothing, got {meta['total_count']}"
    )

    blocked = refresh_version(version["id"])
    assert blocked["status"] == "DRAFT", (
        "the role check runs before the state check, and either way the version must "
        f"not move, got {blocked['status']}"
    )
    assert blocked["approved_at"] is None, (
        f"approved_at must stay null, got {blocked['approved_at']}"
    )

    for label, headers in (
        ("PolicyAuthor", make_author_headers()),
        ("HRComplianceAdmin", make_admin_headers()),
    ):
        rows, meta = validate_paginated(
            api_client.list_policy_versions(
                headers, params={"policy_document_id": document["id"], "limit": 100}
            )
        )
        assert meta["total_count"] == 1, (
            f"the shared read must answer for {label}, got {meta['total_count']}"
        )
        assert rows[0]["id"] == version["id"]


def test_both_approval_stages_carry_their_own_separation_of_duties_screen():
    """PRD §3.9: "Two identity conditions apply: the acting manager's identifier must
    equal the requesting employee's `manager_id`, and it must not equal the request's
    `employee_id`. A violation of either is refused with `ERR_SEGREGATION_OF_DUTIES`
    (403) — nobody approves their own suspension." ... "The acting reviewer must not be
    the `approved_by_reviewer_id` of any addendum on the exception's policy version,
    and must not be the `reviewer_id` of any review on that version whose `status` is
    `APPROVED`; a conflict is refused with `ERR_SOD_REVIEWER_CONFLICT` (403)".

    Design: Corner/rbac/corner_segregation_of_duties_on_both_exception_approval_steps
    """
    from test_helpers import (
        legal_decide,
        make_counsel_headers,
        manager_decide,
        refresh_assignment,
        refresh_employee,
        refresh_exception,
        refresh_package,
        setup_submitted_exception,
    )

    ctx = setup_submitted_exception(
        reason_code="MEDICAL",
        requested_days=30,
        justification="Recovering from surgery",
        extra_employees=1,
        jurisdiction={"min_legal_review_days": 5, "ack_deadline_days": 30},
        effective_date="2026-09-01T00:00:00Z",
    )
    request = ctx["exception"]
    subject, manager, bystander = ctx["employee"], ctx["manager"], ctx["extras"][0]
    tainted, untainted = ctx["reviewer"], ctx["reviewer_2"]
    assert float(request["risk_score_aggregate"]) == 23.50, (
        "0.20*25 + 0.15*16.6667 + 0.25*0 + 0.40*40 is 23.50, got "
        f"{request['risk_score_aggregate']}"
    )
    assert float(request["risk_score_conservative"]) == 33.40, (
        f"0.60*40 + 0.40*23.50 is 33.40, got {request['risk_score_conservative']}"
    )

    validate_error(
        api_client.manager_decision(
            request["id"], {"decision": "APPROVE"}, make_manager_headers(bystander["id"])
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
    )
    validate_error(
        api_client.manager_decision(
            request["id"], {"decision": "APPROVE"}, make_manager_headers(subject["id"])
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
    )
    held = refresh_exception(request["id"])
    assert held["status"] == "SUBMITTED", (
        "neither an unrelated manager nor the requester may move the request, got "
        f"{held['status']}"
    )
    assert held["approving_manager_id"] is None, (
        f"no approving manager may be recorded, got {held['approving_manager_id']}"
    )

    endorsed = manager_decide(request["id"], manager["id"], "APPROVE", note="Endorsed")
    assert endorsed["status"] == "MANAGER_APPROVED", (
        f"the requester's own manager must succeed, got {endorsed['status']}"
    )
    assert endorsed["approving_manager_id"] == manager["id"]

    validate_error(
        api_client.legal_decision(
            request["id"], {"decision": "APPROVE"}, make_counsel_headers(tainted["id"])
        ),
        ApiErrorId.ERR_SOD_REVIEWER_CONFLICT,
    )
    still_pending = refresh_exception(request["id"])
    assert still_pending["status"] == "MANAGER_APPROVED", (
        "the counsel who certified the policy may not excuse anyone from it, so the "
        f"request must stay MANAGER_APPROVED, got {still_pending['status']}"
    )
    assert still_pending["deciding_reviewer_id"] is None, (
        f"no deciding reviewer may be recorded, got {still_pending['deciding_reviewer_id']}"
    )

    granted = legal_decide(request["id"], untainted["id"], "APPROVE", note="Granted")
    assert granted["status"] == "GRANTED", (
        f"only the untainted reviewer can grant, got {granted['status']}"
    )
    assert granted["deciding_reviewer_id"] == untainted["id"]
    assert_same_instant(
        granted["expires_at"],
        "2026-10-01T00:00:00.000Z",
        "expires_at is the 2026-09-01 clock plus the 30 requested days",
    )

    assert refresh_assignment(ctx["assignment"]["id"])["ack_state"] == "EXEMPT", (
        "the grant excuses the linked assignment"
    )
    assert refresh_employee(subject["id"])["open_ack_count"] == 0, (
        "the grant releases the subject's obligation, got "
        f"{refresh_employee(subject['id'])['open_ack_count']}"
    )
    assert refresh_package(ctx["package"]["id"])["status"] == "RELEASED", (
        "the manager's and the bystander's assignments are still open, so the package "
        f"stays RELEASED, got {refresh_package(ctx['package']['id'])['status']}"
    )
