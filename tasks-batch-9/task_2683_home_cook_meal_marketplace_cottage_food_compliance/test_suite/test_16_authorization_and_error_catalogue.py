"""Authorization envelope, role allow-lists, resource ownership, segregation of
duties, and the transition codes not exercised elsewhere.

Every test builds its own state from scratch: the harness restarts the API
server before each test, so the database starts empty and the logical clock
starts at its mandatory startup default.
"""

from test_helpers import (
    ADMIN_HEADERS,
    ANONYMOUS_HEADERS,
    DINER_ONE_HEADERS,
    FINANCE_ONE_HEADERS,
    NON_EXISTENT_UUID,
    OFFICER_ONE,
    OFFICER_ONE_HEADERS,
    OFFICER_TWO,
    OFFICER_TWO_HEADERS,
    REVIEWER_ONE,
    REVIEWER_ONE_HEADERS,
    REVIEWER_TWO,
    REVIEWER_TWO_HEADERS,
    ApiErrorId,
    Role,
    adjudicate_payload,
    approve_menu_item_payload,
    cook_payload,
    delivery_zone_payload,
    document_review_payload,
    food_handler_cert_payload,
    headers_for_role,
    make_cook_headers,
    menu_item_payload,
    menu_item_review_payload,
    onboarding_decision_payload,
    order_payload,
    payout_statement_payload,
    production_window_payload,
    refund_event_payload,
    standing_action_payload,
    state_policy_payload,
    statement_advance_payload,
    triage_payload,
    validate_error,
    validate_paginated,
    validate_success,
    window_advance_payload,
)
from test_helpers import fixtures as fx

JSON_CONTENT_TYPE = {"Content-Type": "application/json"}


def headers_without_role(user_id="probe-1"):
    """Headers that carry a principal but no `X-User-Role` at all."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role):
    """Headers that name a role but carry no `X-User-ID`."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


# ===========================================================================
# The authorization envelope: the four header-level errors and their order
# ===========================================================================
def test_01_absent_or_empty_role_header_is_rejected(api):
    """An absent `X-User-Role` and an empty one are both missing-auth-header failures.

    PRD: "A request with the header absent or empty is rejected with `ERR_MISSING_AUTH_HEADER` (HTTP 401), and a request whose header value is not one of the seven declared roles is rejected with `ERR_UNKNOWN_ROLE` (also HTTP 401)."
    Design: Corner/errors/auth_envelope_errors_are_each_triggerable_and_ordered
    """
    absent = api.list_cooks(headers_without_role())
    validate_error(absent, ApiErrorId.MISSING_AUTH_HEADER, 401)

    empty = api.list_cooks(
        {"X-User-ID": "probe-1", "X-User-Role": "", "Content-Type": "application/json"}
    )
    validate_error(empty, ApiErrorId.MISSING_AUTH_HEADER, 401)


def test_02_unknown_role_header_value_is_rejected(api):
    """A role value outside the seven declared roles is an unknown-role failure.

    PRD: "A request with the header absent or empty is rejected with `ERR_MISSING_AUTH_HEADER` (HTTP 401), and a request whose header value is not one of the seven declared roles is rejected with `ERR_UNKNOWN_ROLE` (also HTTP 401)."
    Design: Corner/errors/auth_envelope_errors_are_each_triggerable_and_ordered
    """
    invented = api.list_cooks(headers_for_role("Chef", "who-1"))
    validate_error(invented, ApiErrorId.UNKNOWN_ROLE, 401)

    # The seven roles are exactly the declared spellings, so a lowercased one is
    # not one of them.
    miscased = api.list_cooks(headers_for_role("platformadmin", "who-1"))
    validate_error(miscased, ApiErrorId.UNKNOWN_ROLE, 401)


def test_03_identified_roles_must_send_a_user_id(api):
    """Cook and ComplianceReviewer must identify themselves even on a read.

    PRD: "`X-User-ID` is mandatory whenever the acting role is `Cook`, `ComplianceReviewer`, `SafetyOfficer` or `FinanceOperator`, because those four roles participate in ownership checks or in segregation-of-duties comparisons that need a stable principal identifier; its absence on any endpoint whose authorised-role list includes one of those four is rejected with `ERR_MISSING_USER_ID` (HTTP 401)."
    Design: Corner/errors/auth_envelope_errors_are_each_triggerable_and_ordered
    """
    fx.create_state_policy(api, state_code="CA")
    cook = fx.register_cook(api, state_code="CA")

    as_cook = api.get_cook(cook["id"], headers_without_user_id(Role.COOK))
    validate_error(as_cook, ApiErrorId.MISSING_USER_ID, 401)

    as_reviewer = api.list_cooks(headers_without_user_id(Role.COMPLIANCE_REVIEWER))
    validate_error(as_reviewer, ApiErrorId.MISSING_USER_ID, 401)


def test_04_role_outside_the_endpoint_allow_list_is_rejected(api):
    """A diner cannot register a state policy, and nothing is written.

    PRD: "Once the role is recognised, the acting role must appear in the endpoint's authorised-role list, or the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    Design: Corner/errors/auth_envelope_errors_are_each_triggerable_and_ordered
    """
    denied = api.create_state_policy(state_policy_payload(state_code="NV"), DINER_ONE_HEADERS)
    validate_error(denied, ApiErrorId.ROLE_NOT_PERMITTED, 403)

    rows, meta = validate_paginated(api.list_state_policies(ADMIN_HEADERS))
    assert meta["total_count"] == 0, f"a denied write created a state policy: {rows}"


def test_05_envelope_checks_mask_every_lower_check(api):
    """The header ladder answers before a path id, a role allow-list or a body is read.

    PRD: "Because the authorisation checks sit above everything, a caller with the wrong role never learns whether the resource exists."
    Design: Corner/errors/auth_envelope_errors_are_each_triggerable_and_ordered
    """
    # An unknown role on an unresolvable cook id reports the role, not the 404.
    unknown_role_ghost = api.get_cook(str(NON_EXISTENT_UUID), headers_for_role("Chef", "who-1"))
    validate_error(unknown_role_ghost, ApiErrorId.UNKNOWN_ROLE, 401)

    # No role header at all on an admin-only write reports the header, not the role.
    no_header_write = api.create_state_policy(state_policy_payload(), headers_without_role())
    validate_error(no_header_write, ApiErrorId.MISSING_AUTH_HEADER, 401)

    # A FinanceOperator with no principal on a standing action: the endpoint's
    # authorised-role list includes SafetyOfficer, so the missing user id is
    # reported ahead of the role denial and ahead of the unresolvable cook.
    no_user_id = api.cook_standing_action(
        str(NON_EXISTENT_UUID),
        standing_action_payload("SUSPEND", "no principal supplied"),
        headers_without_user_id(Role.FINANCE_OPERATOR),
    )
    validate_error(no_user_id, ApiErrorId.MISSING_USER_ID, 401)


# ===========================================================================
# The two transition codes belonging to undeclared edges
# ===========================================================================
def test_06_window_cannot_jump_from_open_to_closed(api):
    """OPEN -> CLOSED is not a declared window edge, and the rejection writes nothing.

    PRD: "`CLOSED` and `CANCELLED` are terminal, and any `to_status` unreachable from the window's current status — advancing straight from `OPEN` to `CLOSED`, or touching a window that has already closed or cancelled — is `ERR_INVALID_WINDOW_TRANSITION`."
    Design: Corner/errors/remaining_transition_codes_are_each_triggerable
    """
    setup = fx.onboard_active_cook(api)
    window = fx.open_production_window(api, setup.cook)

    denied = api.advance_production_window(
        window["id"], window_advance_payload("CLOSED"), setup.cook_headers
    )
    validate_error(denied, ApiErrorId.INVALID_WINDOW_TRANSITION, 409)

    after = fx.read_window(api, window["id"])
    assert after["status"] == "OPEN", f"a rejected advance moved the window: {after['status']}"
    assert after["closed_at"] is None, f"closed_at was stamped by a rejected advance: {after}"
    assert after["version"] == window["version"], (
        f"a rejected advance bumped version {window['version']} -> {after['version']}"
    )


def test_07_statement_cannot_jump_from_draft_to_paid(api):
    """DRAFT -> PAID skips FINALIZED, so the statement keeps its status and null stamps.

    PRD: "Any `to_status` unreachable from the current status — jumping `DRAFT` straight to `PAID`, or acting on a `SUPERSEDED` or `REVERSED` statement — is `ERR_INVALID_STATEMENT_TRANSITION`."
    Design: Corner/errors/remaining_transition_codes_are_each_triggerable
    """
    setup = fx.onboard_active_cook(api)
    window = fx.open_production_window(api, setup.cook)
    statement = fx.draft_payout_statement(api, setup.cook_id, window["id"])
    assert statement["status"] == "DRAFT", (
        f"drafting a statement on an OPEN window must succeed in DRAFT: {statement['status']}"
    )

    denied = api.advance_payout_statement(
        statement["id"], statement_advance_payload("PAID"), FINANCE_ONE_HEADERS
    )
    validate_error(denied, ApiErrorId.INVALID_STATEMENT_TRANSITION, 409)

    after = fx.read_statement(api, statement["id"])
    assert after["status"] == "DRAFT", f"a rejected advance moved the statement: {after['status']}"
    assert after["finalized_at"] is None and after["paid_at"] is None, (
        f"a rejected advance stamped a timestamp: {after}"
    )
    assert after["version"] == statement["version"], (
        f"a rejected advance bumped version {statement['version']} -> {after['version']}"
    )


# ===========================================================================
# Each role is denied the other roles' exclusive operations
# ===========================================================================
def test_08_safety_officer_is_denied_the_compliance_surface(api):
    """Document review, menu review and cook activation are closed to a safety officer.

    PRD: "Once the role is recognised, the acting role must appear in the endpoint's authorised-role list, or the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    Design: Corner/rbac/each_role_is_denied_the_other_roles_exclusive_operations
    """
    setup = fx.selling_cook(api)

    doc_review = api.review_onboarding_document(
        setup.cert_document["id"], document_review_payload("VERIFY"), OFFICER_ONE_HEADERS
    )
    validate_error(doc_review, ApiErrorId.ROLE_NOT_PERMITTED, 403)

    item_review = api.review_menu_item(
        setup.menu_item["id"], menu_item_review_payload("DELIST"), OFFICER_ONE_HEADERS
    )
    validate_error(item_review, ApiErrorId.ROLE_NOT_PERMITTED, 403)

    onboarding = api.cook_onboarding_decision(
        setup.cook_id, onboarding_decision_payload("REJECT"), OFFICER_ONE_HEADERS
    )
    validate_error(onboarding, ApiErrorId.ROLE_NOT_PERMITTED, 403)

    item = fx.read_menu_item(api, setup.menu_item["id"])
    cook = fx.read_cook(api, setup.cook_id)
    assert item["review_status"] == "APPROVED", f"a denied review moved the dish: {item}"
    assert cook["onboarding_status"] == "ACTIVE", f"a denied decision moved the cook: {cook}"


def test_09_compliance_reviewer_is_denied_the_safety_surface(api):
    """Incident triage and adjudication are closed to a compliance reviewer.

    PRD: "Once the role is recognised, the acting role must appear in the endpoint's authorised-role list, or the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    Design: Corner/rbac/each_role_is_denied_the_other_roles_exclusive_operations
    """
    fx.create_state_policy(api, state_code="CA")
    cook = fx.register_cook(api, state_code="CA")
    incident = fx.report_incident(api, cook["id"])

    triage = api.triage_safety_incident(
        incident["id"], triage_payload("DISMISS"), REVIEWER_ONE_HEADERS
    )
    validate_error(triage, ApiErrorId.ROLE_NOT_PERMITTED, 403)

    adjudicate = api.adjudicate_safety_incident(
        incident["id"], adjudicate_payload("SUBSTANTIATE"), REVIEWER_ONE_HEADERS
    )
    validate_error(adjudicate, ApiErrorId.ROLE_NOT_PERMITTED, 403)

    after = fx.read_incident(api, incident["id"])
    assert after["status"] == "INTAKE", f"a denied triage moved the incident: {after['status']}"
    assert after["triaged_by_user_id"] is None, f"a denied triage stamped an officer: {after}"


def test_10_finance_operator_is_denied_safety_and_configuration_operations(api):
    """Adjudication, standing actions and zone configuration are closed to finance.

    PRD: "Once the role is recognised, the acting role must appear in the endpoint's authorised-role list, or the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    Design: Corner/rbac/each_role_is_denied_the_other_roles_exclusive_operations
    """
    policy = fx.create_state_policy(api, state_code="CA")
    cook = fx.register_cook(api, state_code="CA")
    incident = fx.report_incident(api, cook["id"])

    adjudicate = api.adjudicate_safety_incident(
        incident["id"], adjudicate_payload("SUBSTANTIATE"), FINANCE_ONE_HEADERS
    )
    validate_error(adjudicate, ApiErrorId.ROLE_NOT_PERMITTED, 403)

    standing = api.cook_standing_action(
        cook["id"], standing_action_payload("SUSPEND", "finance says so"), FINANCE_ONE_HEADERS
    )
    validate_error(standing, ApiErrorId.ROLE_NOT_PERMITTED, 403)

    zone = api.create_delivery_zone(
        delivery_zone_payload(policy["id"], state_code="CA"), FINANCE_ONE_HEADERS
    )
    validate_error(zone, ApiErrorId.ROLE_NOT_PERMITTED, 403)

    after = fx.read_cook(api, cook["id"])
    assert after["compliance_standing"] == "CLEAR", (
        f"a denied standing action moved the cook: {after['compliance_standing']}"
    )
    rows, meta = validate_paginated(api.list_delivery_zones(ADMIN_HEADERS))
    assert meta["total_count"] == 0, f"a denied write created a delivery zone: {rows}"


def test_11_only_the_finance_operator_may_move_money(api):
    """Payout drafting and refund recording reject a reviewer and a safety officer.

    PRD: "Once the role is recognised, the acting role must appear in the endpoint's authorised-role list, or the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    Design: Corner/rbac/each_role_is_denied_the_other_roles_exclusive_operations
    """
    setup = fx.onboard_active_cook(api)
    window = fx.open_production_window(api, setup.cook)

    statement = api.create_payout_statement(
        payout_statement_payload(setup.cook_id, window["id"], window["version"]),
        REVIEWER_ONE_HEADERS,
    )
    validate_error(statement, ApiErrorId.ROLE_NOT_PERMITTED, 403)

    # The role check answers before any body reference is resolved: the id below
    # names a production window, not an order.
    refund = api.create_refund_event(
        refund_event_payload(
            window["id"], reason="QUALITY", fault_party="PLATFORM", refund_amount_cents=100
        ),
        OFFICER_ONE_HEADERS,
    )
    validate_error(refund, ApiErrorId.ROLE_NOT_PERMITTED, 403)

    _, statement_meta = validate_paginated(api.list_payout_statements(FINANCE_ONE_HEADERS))
    _, refund_meta = validate_paginated(api.list_refund_events(FINANCE_ONE_HEADERS))
    assert statement_meta["total_count"] == 0, "a denied draft created a payout statement"
    assert refund_meta["total_count"] == 0, "a denied refund created a refund event"


def test_12_cook_is_denied_order_placement_and_the_logical_clock(api):
    """A cook may neither place an order nor move the clock, and the clock stays put.

    PRD: "Once the role is recognised, the acting role must appear in the endpoint's authorised-role list, or the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    Design: Corner/rbac/each_role_is_denied_the_other_roles_exclusive_operations
    """
    setup = fx.selling_cook(api)

    order = api.create_order(
        order_payload(setup.menu_item["id"], setup.window["id"], setup.zone["id"], quantity=1),
        setup.cook_headers,
    )
    validate_error(order, ApiErrorId.ROLE_NOT_PERMITTED, 403)

    clock = api.set_clock("2027-01-01T00:00:00Z", setup.cook_headers)
    validate_error(clock, ApiErrorId.ROLE_NOT_PERMITTED, 403)

    _, order_meta = validate_paginated(api.list_orders(ADMIN_HEADERS))
    assert order_meta["total_count"] == 0, "a denied placement created an order"

    # The denied clock move never landed, so the window is still open for orders
    # ahead of its cutoff.
    placed = fx.order_in_scenario(api, setup, quantity=1)
    assert placed["fulfillment_status"] == "PLACED", (
        f"the clock moved under a denied request: {placed}"
    )


# ===========================================================================
# Anonymous is confined to the public catalogue
# ===========================================================================
def test_13_anonymous_may_self_register_a_cook_without_a_user_id(api):
    """Self-registration succeeds for a visitor that sends no principal at all.

    PRD: "Anonymous callers may self-register a cook and read the public catalogue of state policies, menu items, delivery zones and pickup hubs."
    Design: Corner/rbac/anonymous_is_confined_to_the_public_catalog
    """
    fx.create_state_policy(api, state_code="CA")
    visitor = {"X-User-Role": Role.ANONYMOUS, **JSON_CONTENT_TYPE}

    created = validate_success(
        api.create_cook(cook_payload(legal_name="Nia Walker", state_code="CA"), visitor), 201
    )
    assert created["onboarding_status"] == "DRAFT", created
    assert created["compliance_standing"] == "CLEAR", created
    assert created["safety_score"] == 100, created
    assert created["cap_status"] == "UNDER_CAP", created
    for counter in (
        "ytd_gross_sales_cents",
        "ytd_cottage_revenue_cents",
        "pending_payout_cents",
        "lifetime_paid_cents",
    ):
        assert created[counter] == 0, f"{counter} must start at zero: {created[counter]!r}"


def test_14_anonymous_may_read_the_public_catalogue(api):
    """State policies, dishes, delivery zones and pickup hubs are readable by a visitor.

    PRD: "Anonymous callers may self-register a cook and read the public catalogue of state policies, menu items, delivery zones and pickup hubs."
    Design: Corner/rbac/anonymous_is_confined_to_the_public_catalog
    """
    setup = fx.selling_cook(api)
    hub_zone = fx.create_delivery_zone(
        api, setup.policy["id"], state_code="CA", service_mode="HUB_PICKUP"
    )
    hub = fx.create_pickup_hub(api, hub_zone["id"])
    visitor = headers_without_user_id(Role.ANONYMOUS)

    for response in (
        api.list_state_policies(visitor, {"limit": 10, "offset": 0}),
        api.list_menu_items(visitor, {"limit": 10, "offset": 0}),
        api.list_delivery_zones(visitor, {"limit": 10, "offset": 0}),
        api.list_pickup_hubs(visitor, {"limit": 10, "offset": 0}),
    ):
        rows, meta = validate_paginated(response)
        assert meta["total_count"] >= 1, f"a catalogue read came back empty: {rows}"

    assert validate_success(api.get_state_policy(setup.policy["id"], visitor))["id"] == setup.policy["id"]
    assert validate_success(api.get_menu_item(setup.menu_item["id"], visitor))["id"] == setup.menu_item["id"]
    assert validate_success(api.get_delivery_zone(hub_zone["id"], visitor))["id"] == hub_zone["id"]
    assert validate_success(api.get_pickup_hub(hub["id"], visitor))["id"] == hub["id"]


def test_15_anonymous_is_denied_every_person_naming_collection(api):
    """Cook, order, window, document, incident, statement and refund lists are closed.

    PRD: "Read visibility follows the role model rather than the ownership rule: the public catalogue — state policies, menu items, delivery zones and pickup hubs — is readable by anonymous visitors, while cook lists, order lists, incident lists, statement lists and refund lists are restricted to the operational roles that need them, as §4 records endpoint by endpoint."
    Design: Corner/rbac/anonymous_is_confined_to_the_public_catalog
    """
    page = {"limit": 10, "offset": 0}
    for response in (
        api.list_cooks(ANONYMOUS_HEADERS, page),
        api.list_orders(ANONYMOUS_HEADERS, page),
        api.list_production_windows(ANONYMOUS_HEADERS, page),
        api.list_onboarding_documents(ANONYMOUS_HEADERS, page),
        api.list_safety_incidents(ANONYMOUS_HEADERS, page),
        api.list_payout_statements(ANONYMOUS_HEADERS, page),
        api.list_refund_events(ANONYMOUS_HEADERS, page),
    ):
        validate_error(response, ApiErrorId.ROLE_NOT_PERMITTED, 403)


# ===========================================================================
# The Cook identity is entity-backed: ownership guards another cook's rows
# ===========================================================================
def test_16_cook_cannot_write_rows_owned_by_another_cook(api):
    """A body `cook_id` that is not the caller's own id is refused on all three writes.

    PRD: "When the acting role is `Cook`, `X-User-ID` equals the `cook_id` that owns the target resource — either the resource's own `cook_id` or the `cook_id` of the referenced menu item, production window or order — `ERR_NOT_RESOURCE_OWNER`, 403."
    Design: Corner/rbac/cook_role_cannot_reach_another_cooks_rows
    """
    setup = fx.onboard_active_cook(api)
    intruder = fx.register_cook(api, state_code="CA")
    intruder_headers = make_cook_headers(intruder["id"])
    owner_version = fx.cook_version(api, setup.cook_id)

    document = api.create_onboarding_document(
        food_handler_cert_payload(setup.cook_id, owner_version), intruder_headers
    )
    validate_error(document, ApiErrorId.NOT_RESOURCE_OWNER, 403)

    item = api.create_menu_item(
        menu_item_payload(setup.cook_id, name="Borrowed Brioche"), intruder_headers
    )
    validate_error(item, ApiErrorId.NOT_RESOURCE_OWNER, 403)

    window = api.create_production_window(
        production_window_payload(
            setup.cook_id,
            week_start_date="2026-08-17",
            order_cutoff_at="2026-08-19T00:00:00Z",
            handoff_start_at="2026-08-22T16:00:00Z",
            handoff_end_at="2026-08-22T18:00:00Z",
            capacity_meals=5,
        ),
        intruder_headers,
    )
    validate_error(window, ApiErrorId.NOT_RESOURCE_OWNER, 403)

    _, doc_meta = validate_paginated(
        api.list_onboarding_documents(ADMIN_HEADERS, {"cook_id": setup.cook_id})
    )
    _, item_meta = validate_paginated(
        api.list_menu_items(ADMIN_HEADERS, {"cook_id": setup.cook_id})
    )
    _, window_meta = validate_paginated(
        api.list_production_windows(ADMIN_HEADERS, {"cook_id": setup.cook_id})
    )
    assert doc_meta["total_count"] == 2, "a denied submission changed the owner's documents"
    assert item_meta["total_count"] == 0, "a denied creation added a dish to the owner"
    assert window_meta["total_count"] == 0, "a denied creation added a window to the owner"


def test_17_ownership_masks_the_transition_and_cutoff_checks(api):
    """The ownership check answers before the dish's state and the window's cutoff.

    PRD: "Lower-numbered checks are evaluated first and mask everything below them."
    Design: Corner/rbac/cook_role_cannot_reach_another_cooks_rows
    """
    setup = fx.selling_cook(api)
    intruder = fx.register_cook(api, state_code="CA")
    intruder_headers = make_cook_headers(intruder["id"])

    # The dish is APPROVED and could never be submitted for review at all.
    submit = api.submit_menu_item(setup.menu_item["id"], intruder_headers)
    validate_error(submit, ApiErrorId.NOT_RESOURCE_OWNER, 403)

    # The clock has not reached the window's cutoff, so the cutoff gate would also fail.
    advance = api.advance_production_window(
        setup.window["id"], window_advance_payload("CUTOFF_PASSED"), intruder_headers
    )
    validate_error(advance, ApiErrorId.NOT_RESOURCE_OWNER, 403)

    assert fx.read_menu_item(api, setup.menu_item["id"])["review_status"] == "APPROVED"
    assert fx.read_window(api, setup.window["id"])["status"] == "OPEN"


def test_18_cook_reads_another_cooks_record_but_not_its_compliance_summary(api):
    """The record is shared, the compliance summary is ownership-scoped.

    PRD: "A cook's compliance picture is available as a single computed read, permitted to the cook themselves, to compliance reviewers, to safety officers and to platform administrators; when the acting role is `Cook`, the ownership rule applies and reading another cook's summary is `ERR_NOT_RESOURCE_OWNER`."
    Design: Corner/rbac/cook_role_cannot_reach_another_cooks_rows
    """
    setup = fx.onboard_active_cook(api)
    other = fx.register_cook(api, state_code="CA")
    other_headers = make_cook_headers(other["id"])

    record = validate_success(api.get_cook(setup.cook_id, other_headers))
    assert record["id"] == setup.cook_id, record
    assert record["compliance_standing"] == "CLEAR", record

    denied = api.get_compliance_summary(setup.cook_id, other_headers)
    validate_error(denied, ApiErrorId.NOT_RESOURCE_OWNER, 403)

    own = validate_success(api.get_compliance_summary(other["id"], other_headers))
    assert own["cook_id"] == other["id"], own
    assert own["safety_score"] == 100, own
    assert own["approved_menu_item_count"] == 0, own


def test_19_unresolvable_cook_id_masks_the_ownership_check(api):
    """A body `cook_id` that does not exist is a 404, not an ownership 403.

    PRD: "Body-side resolution failures use the same not-found codes, plus `ERR_ZONE_NOT_FOUND` for an unresolvable delivery zone."
    Design: Corner/rbac/cook_role_cannot_reach_another_cooks_rows
    """
    fx.create_state_policy(api, state_code="CA")
    cook = fx.register_cook(api, state_code="CA")
    cook_headers = make_cook_headers(cook["id"])

    document = api.create_onboarding_document(
        food_handler_cert_payload(str(NON_EXISTENT_UUID), cook["version"]), cook_headers
    )
    validate_error(document, ApiErrorId.COOK_NOT_FOUND, 404)

    item = api.create_menu_item(menu_item_payload(str(NON_EXISTENT_UUID)), cook_headers)
    validate_error(item, ApiErrorId.COOK_NOT_FOUND, 404)


# ===========================================================================
# Segregation of duties: both bars are keyed on X-User-ID, not on role
# ===========================================================================
def test_20_inspection_reviewer_may_not_approve_that_cooks_dish(api):
    """The reviewer who graded the kitchen inspection is barred from approving.

    PRD: "Segregation of duties applies here too: the approving reviewer's `X-User-ID` must differ from the `reviewed_by_user_id` recorded on the cook's kitchen-inspection document, or the approval is `ERR_SOD_SAME_OFFICER`."
    Design: Corner/rbac/segregation_of_duties_blocks_the_same_officer_on_both_steps
    """
    fx.create_state_policy(api, state_code="CA")
    cook = fx.register_cook(api, state_code="CA")
    cert = fx.submit_food_handler_cert(api, cook)
    inspection = fx.submit_kitchen_inspection(api, cook)
    fx.review_document(api, cert["id"], "VERIFY", REVIEWER_ONE_HEADERS)
    inspection = fx.review_document(api, inspection["id"], "PASS", REVIEWER_ONE_HEADERS)
    assert inspection["reviewed_by_user_id"] == REVIEWER_ONE, (
        f"the inspection must be graded by the reviewer under test: {inspection}"
    )
    cook = fx.decide_onboarding(api, cook["id"], "ACTIVATE", REVIEWER_ONE_HEADERS)
    item = fx.draft_menu_item(api, cook)
    fx.submit_menu_item(api, cook["id"], item["id"])

    denied = api.review_menu_item(item["id"], approve_menu_item_payload(), REVIEWER_ONE_HEADERS)
    validate_error(denied, ApiErrorId.SOD_SAME_OFFICER, 403)

    after = fx.read_menu_item(api, item["id"])
    assert after["review_status"] == "UNDER_REVIEW", f"a denied approval moved the dish: {after}"
    assert after["approved_by_user_id"] is None, f"a denied approval stamped an approver: {after}"
    assert after["approved_at"] is None, f"a denied approval stamped approved_at: {after}"


def test_21_inspection_reviewer_may_still_request_a_revision(api):
    """The bar fires only on APPROVE, so the same reviewer may bounce the dish back.

    PRD: "Segregation of duties: the adjudicating officer's `X-User-ID` differs from the incident's `triaged_by_user_id`, and the approving reviewer's `X-User-ID` differs from the `reviewed_by_user_id` of the cook's kitchen-inspection document — `ERR_SOD_SAME_OFFICER`, 403, on incident adjudication and on menu-item approval."
    Design: Corner/rbac/segregation_of_duties_blocks_the_same_officer_on_both_steps
    """
    fx.create_state_policy(api, state_code="CA")
    cook = fx.register_cook(api, state_code="CA")
    cert = fx.submit_food_handler_cert(api, cook)
    inspection = fx.submit_kitchen_inspection(api, cook)
    fx.review_document(api, cert["id"], "VERIFY", REVIEWER_ONE_HEADERS)
    fx.review_document(api, inspection["id"], "PASS", REVIEWER_ONE_HEADERS)
    cook = fx.decide_onboarding(api, cook["id"], "ACTIVATE", REVIEWER_ONE_HEADERS)
    item = fx.draft_menu_item(api, cook)
    fx.submit_menu_item(api, cook["id"], item["id"])

    bounced = validate_success(
        api.review_menu_item(
            item["id"],
            menu_item_review_payload(
                "REQUEST_REVISION", revision_note="add net weight to the label mock-up"
            ),
            REVIEWER_ONE_HEADERS,
        )
    )
    assert bounced["review_status"] == "REVISION_REQUESTED", bounced
    assert bounced["revision_round"] == 1, bounced

    resubmitted = fx.submit_menu_item(api, cook["id"], item["id"])
    assert resubmitted["review_status"] == "UNDER_REVIEW", resubmitted

    approved = validate_success(
        api.review_menu_item(item["id"], approve_menu_item_payload(), REVIEWER_TWO_HEADERS)
    )
    assert approved["review_status"] == "APPROVED", approved
    assert approved["approved_by_user_id"] == REVIEWER_TWO, approved


def test_22_triaging_officer_may_not_adjudicate_the_same_incident(api):
    """The adjudicator is compared against triaged_by_user_id, and a second officer passes.

    PRD: "Adjudication is a second safety officer's decision, and it must be a *different* officer: the acting `X-User-ID` must differ from the report's recorded `triaged_by_user_id`, or the request is rejected with `ERR_SOD_SAME_OFFICER`."
    Design: Corner/rbac/segregation_of_duties_blocks_the_same_officer_on_both_steps
    """
    fx.create_state_policy(api, state_code="CA")
    cook = fx.register_cook(api, state_code="CA")
    incident = fx.report_incident(api, cook["id"])
    triaged = fx.triage_incident(
        api, incident["id"], "ACCEPT", officer_headers=OFFICER_ONE_HEADERS
    )
    assert triaged["status"] == "TRIAGED", triaged
    assert triaged["triaged_by_user_id"] == OFFICER_ONE, triaged

    denied = api.adjudicate_safety_incident(
        incident["id"],
        adjudicate_payload("SUBSTANTIATE", "same officer closes its own triage"),
        OFFICER_ONE_HEADERS,
    )
    validate_error(denied, ApiErrorId.SOD_SAME_OFFICER, 403)

    after = fx.read_incident(api, incident["id"])
    assert after["status"] == "TRIAGED", f"a denied adjudication moved the incident: {after}"
    assert after["adjudicated_by_user_id"] is None, f"a denied adjudication stamped: {after}"
    assert after["adjudicated_at"] is None, f"a denied adjudication stamped: {after}"

    settled = validate_success(
        api.adjudicate_safety_incident(
            incident["id"],
            adjudicate_payload("SUBSTANTIATE", "independent review confirms the report"),
            OFFICER_TWO_HEADERS,
        )
    )
    assert settled["status"] == "SUBSTANTIATED", settled
    assert settled["adjudicated_by_user_id"] == OFFICER_TWO, settled
