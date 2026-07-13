"""Order intake and lifecycle: creation shape, not-found and validation guards,
the draft-requires-production cross-entity gate, deliver-state guard, reverse-lookup
listing, and manual add-on credit grants."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    NON_EXISTENT_UUID,
    is_valid_uuid,
    assert_order,
    setup_confirmed_order,
    create_plan,
    create_client_entity,
    create_coach_entity,
    create_order_entity,
    create_order_payload,
    make_client_headers,
    make_coach_headers,
    first_deliverable_id,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]

BASIC_PLAN = {"tier": "BASIC", "base_price_cents": 20000, "included_deliverables": ["RESUME"],
              "included_revision_rounds": 1, "included_coaching_sessions": 0, "guarantee_type": "NONE"}


class TestDraftRequiresProduction:
    def _unconfirmed_order(self, api):
        plan = create_plan(**BASIC_PLAN)
        client = create_client_entity(email="mia@x.com")
        coach = create_coach_entity(name="Moe Coach", email="moe@x.com", specialty="GENERAL")
        order = create_order_entity(plan["id"], client["id"])
        return order["id"], first_deliverable_id(order["id"]), client["id"], coach["id"]

    def test_draft_on_intake_order_rejected(self, api):
        """PRD §3.4: "this first draft may be uploaded only while the parent order is
        IN_PRODUCTION, and an attempt while the order is not in production is rejected with
        ERR_ORDER_NOT_IN_PRODUCTION (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/deliverable_draft_requires_order_in_production
        """
        order_id, deliv_id, client_id, coach_id = self._unconfirmed_order(api)
        resp = api.create_draft(deliv_id, {"notes": "too early"}, make_coach_headers(coach_id))
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_IN_PRODUCTION.value)

    def test_draft_after_confirm_succeeds(self, api):
        """PRD §3.4: "A Coach uploads the first draft, transitioning the deliverable from
        PENDING to DRAFTED". After the order is confirmed into IN_PRODUCTION the same draft
        is accepted.

        Design: Difficulty/cross_entity_state_dependency/deliverable_draft_requires_order_in_production
        """
        order_id, deliv_id, client_id, coach_id = self._unconfirmed_order(api)
        validate_success(api.confirm_order(order_id, make_client_headers(client_id)))
        deliverable = validate_success(api.create_draft(deliv_id, {"notes": "now ok"}, make_coach_headers(coach_id)))
        assert deliverable["status"] == "DRAFTED"


def test_create_order_returns_201_with_fields(api):
    """PRD §3.2: "A Client opens an engagement by creating an order, which starts in the
    INTAKE state." It "records deliverables_total as the number of deliverables created —
    one per included deliverable type"; the single RESUME plan yields one deliverable and a
    provisional total equal to the base price.

    Design: Corner/entities/create_order_returns_201_with_fields
    """
    plan = create_plan(**BASIC_PLAN)
    client = create_client_entity(email="amy@x.com")
    data = validate_success(api.create_order(create_order_payload(plan["id"]), make_client_headers(client["id"])), 201)
    assert data["status"] == "INTAKE"
    assert data["deliverables_total"] == 1
    assert data["provisional_total_cents"] == 20000


def test_get_order_not_found_returns_404(api):
    """PRD §2.10: "the system validates the named identifiers left to right and rejects the
    request at the first identifier that does not resolve, returning that resource's specific
    not-found error." PRD §2.10: "a missing order yields `ERR_ORDER_NOT_FOUND`".

    Design: Corner/entities/get_order_not_found_returns_404
    """
    resp = api.get_order(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FOUND.value)


def test_order_missing_required_plan_id_returns_validation(api):
    """PRD §2.12: body well-formedness requires "required fields present, enum values in
    range, types correct" — a body missing a required field fails with `ERR_VALIDATION`
    (HTTP 422). PRD §3.2 names the purchased plan through `plan_id`, so omitting it is a
    malformed body.

    Design: Corner/entities/order_missing_required_plan_id_returns_validation
    """
    client = create_client_entity(email="bo@x.com")
    payload = {"target_role": "PM", "target_industry": "Tech", "requested_delivery_days": 7}
    resp = api.create_order(payload, make_client_headers(client["id"]))
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_order_system_fields_generated(api):
    """PRD §2.4: every full resource carries "an id formatted as a UUID with no type
    prefix; a created_at ISO 8601 UTC timestamp ...; an updated_at ISO 8601 UTC timestamp
    ...; and a version integer". The created order is minted with server-managed system fields.

    Design: Corner/entities/order_system_fields_generated
    """
    plan = create_plan(**BASIC_PLAN)
    client = create_client_entity(email="di@x.com")
    data = validate_success(api.create_order(create_order_payload(plan["id"]), make_client_headers(client["id"])), 201)
    assert is_valid_uuid(data["id"]), "order id must be a server-minted UUID with no type prefix"
    assert_order(data)


def test_deliver_not_ready_order_returns_invalid_state(api):
    """PRD §3.3: "Attempting to deliver an order that is not READY is rejected with
    ERR_INVALID_STATE (HTTP 409)."

    Design: Corner/state_machines/deliver_not_ready_order_returns_invalid_state
    """
    ctx = setup_confirmed_order(plan_overrides=BASIC_PLAN, with_coach=False)
    resp = api.deliver_order(ctx["order_id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_list_order_deliverables_reverse_lookup(api):
    """PRD §3.2: creating an order "creates one `Deliverable` in `PENDING` state for each
    entry of the plan's `included_deliverables`". A full-package plan seeds exactly three.

    Design: Corner/endpoints/list_order_deliverables_reverse_lookup
    """
    plan = create_plan(tier="EXECUTIVE", base_price_cents=60000,
                       included_deliverables=["RESUME", "LINKEDIN", "COVER_LETTER"],
                       included_revision_rounds=2, included_coaching_sessions=0, guarantee_type="NONE")
    client = create_client_entity(email="qi@x.com")
    order = validate_success(api.create_order(create_order_payload(plan["id"]), make_client_headers(client["id"])), 201)
    deliverables, _ = validate_paginated(api.list_order_deliverables(order["id"], ADMIN))
    assert len(deliverables) == 3
    assert order["deliverables_total"] == 3


def test_manual_addon_grants_session_credit(api):
    """PRD §3.6: "An `EXTRA_COACHING` or `INTERVIEW_PREP` purchase increments the order's
    `sessions_purchased` by one." The purchase "writes a `CHARGE` payment for the add-on's
    `price_cents` with reason `MANUAL_ADDON`, raising `amount_charged_cents` accordingly."

    Design: Corner/endpoints/manual_addon_grants_session_credit
    """
    ctx = setup_confirmed_order(plan_overrides={
        "tier": "PRO", "base_price_cents": 20000, "included_deliverables": ["RESUME"],
        "included_revision_rounds": 1, "included_coaching_sessions": 0, "guarantee_type": "NONE"},
        with_coach=False)
    addon = validate_success(api.create_addon(ctx["order_id"], {"type": "EXTRA_COACHING"}, ctx["client_headers"]), 201)
    assert addon["price_cents"] == 12000
    order = validate_success(api.get_order(ctx["order_id"], ADMIN))
    assert order["sessions_purchased"] == 1
    assert order["amount_charged_cents"] == 32000
