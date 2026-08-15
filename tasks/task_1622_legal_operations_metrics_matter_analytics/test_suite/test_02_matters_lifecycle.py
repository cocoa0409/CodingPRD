"""Matter lifecycle: birth state, computed fields, transition gates, OCC on close."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_matter,
    close_matter,
    create_accrual,
    create_invoice,
    create_matter_payload,
    setup_archived_matter,
    setup_matter_graph,
    validate_success,
    validate_error,
    ANALYST,
    MANAGER,
)


def test_new_matter_born_in_intake(api):
    """PRD §3.3: "New matters are born in `INTAKE` with `actual_spend_cents` and
    `accrual_outstanding_cents` at zero and `cycle_days` null."

    Design: Corner/state_machines/matter_initial_state_is_intake
    """
    graph = setup_matter_graph(activate=False, assignment_hours=None)
    matter = graph["matter"]
    assert_matter(matter)
    assert matter["status"] == "INTAKE"


def test_matter_create_missing_matter_number_rejected(api):
    """PRD §2.12: "7. Payload shape — missing required fields, wrong scalar types,
    or malformed values yield `ERR_INVALID_REQUEST` (HTTP 400) as the final gate,
    so a request that fails a business rule never masquerades as a 400."
    PRD §3.3: "A `LegalOpsAnalyst` opens a matter by supplying its `matter_number`
    — a unique business key in the format LGL-YYYY-NNNNN — along with a `title`,
    the `practice_area_id` and `matter_type_id` classifying it, the
    `fiscal_period_id` of the period in which it opens, and the `lead_counsel_id`
    of the responsible in-house lawyer."

    Design: Corner/entities/matter_create_missing_required_returns_invalid_request
    """
    graph = setup_matter_graph(activate=False, assignment_hours=None)
    payload = create_matter_payload(
        graph["practice_area"]["id"],
        graph["matter_type"]["id"],
        graph["fiscal_period"]["id"],
        graph["counsel"]["id"],
        primary_firm_id=graph["firm"]["id"],
    )
    del payload["matter_number"]
    res = api_client.create_matter(payload, ANALYST)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_new_matter_computed_fields_zeroed(api):
    """PRD §3.3: "New matters are born in `INTAKE` with `actual_spend_cents` and
    `accrual_outstanding_cents` at zero and `cycle_days` null."

    Design: Corner/entities/matter_actual_spend_computed_not_input
    """
    graph = setup_matter_graph(activate=False, assignment_hours=None)
    matter = graph["matter"]
    assert matter["actual_spend_cents"] == 0
    assert matter["accrual_outstanding_cents"] == 0
    assert matter["cycle_days"] is None


def test_close_from_intake_rejected(api):
    """PRD §3.6: "Closing is an analyst action available from `ACTIVE` and, after
    a reopen, from `REOPENED`."
    PRD §2.12: "4. State eligibility — for the action endpoints (activate, hold,
    resume, close, reopen, archive, soft-close, hard-close, approve, pay, reject,
    release, publish), a target resource that is not in a state from which the
    requested transition is defined yields `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/matter_invalid_transition_intake_to_closed
    """
    graph = setup_matter_graph(activate=False, assignment_hours=None)
    matter = graph["matter"]
    res = api_client.close_matter(
        matter["id"], {"expected_matter_version": matter["version"]}, ANALYST
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_archived_matter_is_terminal(api):
    """PRD §3.6: "Once the matter's period has been hard-closed, the manager may
    archive the matter, moving it from `CLOSED` to its terminal `ARCHIVED` state;
    archiving against a period that is not yet `HARD_CLOSED` is rejected with
    `ERR_PERIOD_NOT_HARD_CLOSED` (HTTP 409)."
    PRD §3.6: "A `LegalOpsManager` may reopen a `CLOSED` matter while its period
    is `OPEN` or `REOPENED`" — ARCHIVED defines no outbound transition.

    Design: Corner/state_machines/matter_terminal_state_lockdown_archived
    """
    graph = setup_archived_matter()
    assert graph["matter"]["status"] == "ARCHIVED"
    res = api_client.reopen_matter(graph["matter"]["id"], MANAGER)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_activation_without_assignment_rejected(api):
    """PRD §3.3: "A matter with no active staffing is rejected with
    `ERR_NO_ACTIVE_ASSIGNMENT` (HTTP 422)."

    Design: Corner/validations/matter_activation_blocked_without_assignment
    """
    graph = setup_matter_graph(activate=False, assignment_hours=None)
    res = api_client.activate_matter(graph["matter"]["id"], ANALYST)
    validate_error(res, ApiErrorId.ERR_NO_ACTIVE_ASSIGNMENT)


def test_close_blocked_by_outstanding_accrual(api):
    """PRD §3.6: "Two housekeeping conditions guard it: no accrual on the matter
    may remain `OUTSTANDING`, and no invoice on the matter may linger in
    `SUBMITTED`; either violation is rejected as `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/matter_close_blocked_by_outstanding_accrual
    """
    graph = setup_matter_graph()
    matter = graph["matter"]
    create_accrual(
        matter["id"], graph["fiscal_period"]["id"], graph["firm"]["id"], 100000
    )
    current = validate_success(api_client.get_matter(matter["id"], ANALYST), 200)
    res = api_client.close_matter(
        matter["id"], {"expected_matter_version": current["version"]}, ANALYST
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    after = validate_success(api_client.get_matter(matter["id"], ANALYST), 200)
    assert after["status"] == "ACTIVE"


def test_close_blocked_by_submitted_invoice(api):
    """PRD §3.6: "Two housekeeping conditions guard it: no accrual on the matter
    may remain `OUTSTANDING`, and no invoice on the matter may linger in
    `SUBMITTED`; either violation is rejected as `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/matter_close_blocked_by_outstanding_accrual
    """
    graph = setup_matter_graph()
    matter = graph["matter"]
    create_invoice(
        matter["id"], graph["firm"]["id"], graph["fiscal_period"]["id"], 50000
    )
    current = validate_success(api_client.get_matter(matter["id"], ANALYST), 200)
    res = api_client.close_matter(
        matter["id"], {"expected_matter_version": current["version"]}, ANALYST
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    after = validate_success(api_client.get_matter(matter["id"], ANALYST), 200)
    assert after["status"] == "ACTIVE"


def test_close_with_stale_matter_version_rejected(api):
    """PRD §2.11: "Closing a matter requires `expected_matter_version`, compared
    the same way against the matter's current `version`; mismatches are rejected
    with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.6: "The state checks run first, so a second close attempted against an
    already-closed matter reports `ERR_INVALID_STATE`, while a close against a
    matter whose `version` has drifted — for instance, because an invoice payment
    cascade bumped it — reports `ERR_STALE_VERSION`."

    Design: Corner/errors/error_stale_version_triggerable
    """
    graph = setup_matter_graph()
    matter = graph["matter"]
    stale_version = matter["version"]

    closed = close_matter(matter["id"])
    assert closed["status"] == "CLOSED"
    validate_success(api_client.reopen_matter(matter["id"], MANAGER), 200)

    current = validate_success(api_client.get_matter(matter["id"], ANALYST), 200)
    assert current["status"] == "REOPENED"
    assert current["version"] != stale_version

    # Close is defined from REOPENED and housekeeping is clean, so the drifted
    # version is what the request must fail on.
    res = api_client.close_matter(
        matter["id"], {"expected_matter_version": stale_version}, ANALYST
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)
