"""Deliverable lifecycle: revision cycle, credit cost, initial state, sprint guards.

Covers queue A non_linear_state_machine (revision loop) and the queue B
entities / state_machines / endpoints corner instances on deliverables and sprints.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    make_client_headers,
    factories,
    fixtures,
)

ADMIN = TEST_USERS["agency_admin_headers"]
AM = TEST_USERS["account_manager_headers"]


def test_revision_cycle_returns_to_in_progress_and_counts(api):
    """PRD §3.6: "From `IN_REVIEW`, the client either requests a revision or approves.
    Requesting a revision moves the deliverable back to `IN_PROGRESS`, increments
    `revision_count` by one, and increments the `version`, forming the cyclic review
    loop."

    First request_revision: status IN_PROGRESS, revision_count 1.

    Design: Difficulty/non_linear_state_machine/deliverable_revision_cycle_in_review_to_in_progress
    """
    client, retainer, sprint = fixtures.setup_client_retainer_active_sprint(
        retainer_overrides={"monthly_credits": 20},
    )
    deliverable, _ = fixtures.create_in_review_deliverable(
        client["id"], retainer["id"], sprint["id"],
        deliverable_overrides={"kind": "CONTENT", "complexity": "STANDARD"},
    )
    client_hdr = make_client_headers(client["id"])
    revised = validate_success(api.request_revision(deliverable["id"], client_hdr))
    assert revised["status"] == "IN_PROGRESS", (
        f"request_revision should return to IN_PROGRESS, got {revised['status']}"
    )
    assert revised["revision_count"] == 1, (
        f"revision_count should be 1 after first revision, got {revised['revision_count']}"
    )


def test_revision_cycle_second_pass_increments_count_again(api):
    """PRD §3.6: "Requesting a revision moves the deliverable back to `IN_PROGRESS`,
    increments `revision_count` by one, and increments the `version`, forming the
    cyclic review loop."
    PRD §3.6: "submitting an `IN_PROGRESS` deliverable moves it to `IN_REVIEW`".

    Looping IN_PROGRESS -> IN_REVIEW -> IN_PROGRESS a second time raises
    revision_count to 2.

    Design: Difficulty/non_linear_state_machine/deliverable_revision_cycle_in_review_to_in_progress
    """
    client, retainer, sprint = fixtures.setup_client_retainer_active_sprint(
        retainer_overrides={"monthly_credits": 20},
    )
    deliverable, _ = fixtures.create_in_review_deliverable(
        client["id"], retainer["id"], sprint["id"],
        deliverable_overrides={"kind": "CONTENT", "complexity": "STANDARD"},
    )
    client_hdr = make_client_headers(client["id"])
    validate_success(api.request_revision(deliverable["id"], client_hdr))
    validate_success(api.submit_deliverable(deliverable["id"], AM))
    revised_again = validate_success(api.request_revision(deliverable["id"], client_hdr))
    assert revised_again["revision_count"] == 2, (
        f"revision_count should be 2 after second revision, "
        f"got {revised_again['revision_count']}"
    )


def test_deliverable_credit_cost_computed_for_content_complex(api):
    """PRD §3.6: "The `credit_cost` derives from a base cost by kind — three for
    `CONTENT`, two for `BACKLINK`, four for `TECHNICAL` — multiplied by a complexity
    multiplier of one for `STANDARD` or one and one-half for `COMPLEX`, with the
    product rounded up to the next whole credit. Thus a `TECHNICAL` `COMPLEX`
    deliverable costs six credits and a `CONTENT` `COMPLEX` deliverable costs five
    credits."

    CONTENT/COMPLEX -> ceil(3*1.5) = 5.

    Design: Corner/entities/deliverable_credit_cost_computed_input_ignored
    """
    fixtures.set_clock("2026-04-10T00:00:00Z")
    client, retainer = fixtures.create_active_client_with_active_retainer(
        retainer_overrides={"monthly_credits": 20},
    )
    sprint_payload = factories.create_sprint_payload(
        client_id=client["id"], retainer_id=retainer["id"], capacity_credits=20
    )
    sprint = validate_success(api.create_sprint(sprint_payload, AM), expected_status=201)
    deliverable = validate_success(
        api.create_deliverable(
            factories.create_deliverable_payload(
                client_id=client["id"], retainer_id=retainer["id"],
                sprint_id=sprint["id"], kind="CONTENT", complexity="COMPLEX",
            ),
            AM,
        ),
        expected_status=201,
    )
    assert deliverable["credit_cost"] == 5, (
        f"CONTENT/COMPLEX credit_cost should be ceil(3*1.5)=5, "
        f"got {deliverable['credit_cost']}"
    )


def test_new_deliverable_starts_in_draft_with_backlink_cost(api):
    """PRD §3.6: "Creation computes the `credit_cost` and starts the deliverable in
    `DRAFT` `status` with `revision_count` 0."
    PRD §3.6: "The `credit_cost` derives from a base cost by kind — three for
    `CONTENT`, two for `BACKLINK`, four for `TECHNICAL` — multiplied by a complexity
    multiplier of one for `STANDARD`".

    BACKLINK/STANDARD -> credit_cost 2, status DRAFT.

    Design: Corner/state_machines/deliverable_initial_state_is_draft
    """
    fixtures.set_clock("2026-04-10T00:00:00Z")
    client, retainer = fixtures.create_active_client_with_active_retainer(
        retainer_overrides={"monthly_credits": 20},
    )
    sprint_payload = factories.create_sprint_payload(
        client_id=client["id"], retainer_id=retainer["id"], capacity_credits=20
    )
    sprint = validate_success(api.create_sprint(sprint_payload, AM), expected_status=201)
    deliverable = validate_success(
        api.create_deliverable(
            factories.create_deliverable_payload(
                client_id=client["id"], retainer_id=retainer["id"],
                sprint_id=sprint["id"], kind="BACKLINK", complexity="STANDARD",
            ),
            AM,
        ),
        expected_status=201,
    )
    assert deliverable["status"] == "DRAFT"
    assert deliverable["credit_cost"] == 2, (
        f"BACKLINK/STANDARD credit_cost should be 2, got {deliverable['credit_cost']}"
    )


def test_approve_non_in_review_deliverable_rejected(api):
    """PRD §3.6: "Approving an `IN_REVIEW` deliverable moves it to the terminal
    `APPROVED`".
    PRD §2.7: "(6) that the target resource is in a state that permits the requested
    transition, failing with `ERR_INVALID_STATE`".

    Approving an ASSIGNED (not IN_REVIEW) deliverable -> ERR_INVALID_STATE; status
    unchanged.

    Design: Corner/state_machines/approve_deliverable_not_in_review_invalid_state
    """
    client, retainer, sprint = fixtures.setup_client_retainer_active_sprint(
        retainer_overrides={"monthly_credits": 20},
    )
    deliverable, _ = fixtures.create_assigned_deliverable(
        client["id"], retainer["id"], sprint["id"],
        deliverable_overrides={"kind": "CONTENT", "complexity": "STANDARD"},
    )
    client_hdr = make_client_headers(client["id"])
    resp = api.approve_deliverable(deliverable["id"], client_hdr)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    after = validate_success(api.get_deliverable(deliverable["id"], ADMIN))
    assert after["status"] == "ASSIGNED", f"status must be unchanged, got {after['status']}"


def test_sprint_close_blocked_by_open_work(api):
    """PRD §3.6: "A sprint closes `ACTIVE → CLOSED` only when it holds no deliverable
    in `ASSIGNED`, `IN_PROGRESS`, or `IN_REVIEW`; an attempt to close with open work
    is rejected with `ERR_SPRINT_HAS_OPEN_WORK`."

    Design: Corner/state_machines/sprint_close_blocked_by_open_work
    """
    client, retainer, sprint = fixtures.setup_client_retainer_active_sprint(
        retainer_overrides={"monthly_credits": 20},
    )
    fixtures.create_assigned_deliverable(
        client["id"], retainer["id"], sprint["id"],
        deliverable_overrides={"kind": "TECHNICAL", "complexity": "STANDARD"},
    )
    resp = api.close_sprint(sprint["id"], AM)
    validate_error(resp, ApiErrorId.ERR_SPRINT_HAS_OPEN_WORK.value)

    after = validate_success(api.get_sprint(sprint["id"], ADMIN))
    assert after["status"] == "ACTIVE", f"sprint must stay ACTIVE, got {after['status']}"


def test_list_deliverables_filtered_by_sprint(api):
    """PRD §4: "GET | `/deliverables` | List deliverables; filter by client, retainer,
    sprint, or status".
    PRD §2.3: "Every list response surfaces `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."

    Filtering by sprint_id returns only that sprint's one deliverable.

    Design: Corner/endpoints/list_deliverables_filtered_by_sprint
    """
    fixtures.set_clock("2026-04-10T00:00:00Z")
    client, retainer = fixtures.create_active_client_with_active_retainer(
        retainer_overrides={"monthly_credits": 20},
    )
    sprint_payload = factories.create_sprint_payload(
        client_id=client["id"], retainer_id=retainer["id"], capacity_credits=20
    )
    sprint = validate_success(api.create_sprint(sprint_payload, AM), expected_status=201)
    deliverable = validate_success(
        api.create_deliverable(
            factories.create_deliverable_payload(
                client_id=client["id"], retainer_id=retainer["id"],
                sprint_id=sprint["id"], kind="CONTENT", complexity="STANDARD",
            ),
            AM,
        ),
        expected_status=201,
    )
    data, meta = validate_paginated(
        api.list_deliverables(AM, params={"sprint_id": sprint["id"]})
    )
    assert len(data) == 1, f"expected exactly one deliverable for the sprint, got {len(data)}"
    assert data[0]["sprint_id"] == sprint["id"]
