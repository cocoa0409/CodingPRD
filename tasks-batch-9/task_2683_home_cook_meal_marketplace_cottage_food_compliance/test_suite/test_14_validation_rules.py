"""Input and precondition rejections: uniqueness, conditional fields, intervals,
ranges, disclosure requirements, refund limits, duplicate finalisation,
eligibility filters, and inputs sitting exactly on their declared limits.

Every rejection below is asserted with the exact error identifier and HTTP status
the PRD's error catalogue states, and every rejection is followed by a re-read of
the target row so the "no side effect" half of the rule is checked too.
"""

from test_helpers import (
    ADMIN_HEADERS,
    ANONYMOUS_HEADERS,
    DINER_ONE_HEADERS,
    FINANCE_ONE_HEADERS,
    REVIEWER_ONE,
    REVIEWER_ONE_HEADERS,
    REVIEWER_TWO_HEADERS,
    STANDARD_LABEL_FIELDS,
    ApiErrorId,
    assert_capacity_triple,
    assert_refund_three_bucket_identity,
    consolidate_payload,
    cook_payload,
    delivery_zone_payload,
    food_handler_cert_payload,
    make_cook_headers,
    menu_item_review_payload,
    order_payload,
    payout_statement_payload,
    production_window_payload,
    refund_event_payload,
    safety_incident_payload,
    state_policy_payload,
    statement_advance_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx


# ==========================================================================
# Uniqueness scopes
# ==========================================================================
def test_01_duplicate_state_code_is_rejected(api):
    """A second state policy for an already-registered state_code is refused.

    PRD: "The profile is keyed by `state_code`, a two-letter uppercase US state code that must be globally unique — a second attempt at the same code is rejected with `ERR_DUPLICATE_STATE_POLICY`."
    Design: Corner/validations/duplicate_state_policy_cook_email_and_zone_code_rejected
    """
    fx.reset_clock(api)
    policy = fx.create_state_policy(api, state_code="CA")

    resp = api.create_state_policy(
        state_policy_payload(
            state_code="CA",
            cottage_food_annual_cap_cents=7_500_000,
            allowed_kitchen_types=["HOME_COTTAGE"],
            tcs_requires_commercial_kitchen=False,
            max_shelf_life_days_non_refrigerated=30,
            label_required_fields=["cook_name"],
            cert_validity_max_days=365,
        ),
        ADMIN_HEADERS,
    )
    validate_error(resp, ApiErrorId.DUPLICATE_STATE_POLICY, 409)

    stored = validate_success(api.get_state_policy(policy["id"], ADMIN_HEADERS))
    assert stored["cottage_food_annual_cap_cents"] == 5_000_000, (
        f"the stored CA policy must keep its original cap, got {stored['cottage_food_annual_cap_cents']}"
    )
    assert stored["cert_validity_max_days"] == 1825
    assert stored["version"] == policy["version"]

    rows, meta = validate_paginated(api.list_state_policies(ADMIN_HEADERS, {"state_code": "CA"}))
    assert meta["total_count"] == 1, f"exactly one CA policy must exist, got {meta['total_count']}"


def test_02_duplicate_cook_email_is_rejected_case_insensitively(api):
    """A registration whose email differs only in case collides with the existing cook.

    PRD: "`email` is unique across all cooks, compared case-insensitively — `ERR_DUPLICATE_COOK_EMAIL`, 409, on cook registration."
    Design: Corner/validations/duplicate_state_policy_cook_email_and_zone_code_rejected
    """
    fx.reset_clock(api)
    fx.create_state_policy(api, state_code="CA")
    cook = fx.register_cook(
        api, legal_name="Dara Osei", email="dara@example.com", state_code="CA",
        claimed_kitchen_type="HOME_COTTAGE",
    )

    resp = api.create_cook(
        cook_payload(
            legal_name="Dara Impostor",
            email="DARA@example.com",
            state_code="CA",
            claimed_kitchen_type="HOME_COTTAGE",
        ),
        ANONYMOUS_HEADERS,
    )
    validate_error(resp, ApiErrorId.DUPLICATE_COOK_EMAIL, 409)

    stored = fx.read_cook(api, cook["id"])
    assert stored["legal_name"] == "Dara Osei", "the rejected registration must not touch the first cook"
    assert stored["onboarding_status"] == "DRAFT"
    assert stored["version"] == cook["version"]

    rows, meta = validate_paginated(api.list_cooks(ADMIN_HEADERS, {"state_code": "CA"}))
    assert meta["total_count"] == 1, f"exactly one CA cook must exist, got {meta['total_count']}"


def test_03_duplicate_zone_code_is_rejected(api):
    """A second delivery zone reusing an existing zone_code is refused.

    PRD: "`zone_code` is unique across all delivery zones — `ERR_DUPLICATE_ZONE_CODE`, 409, on delivery-zone creation."
    Design: Corner/validations/duplicate_state_policy_cook_email_and_zone_code_rejected
    """
    fx.reset_clock(api)
    policy = fx.create_state_policy(api, state_code="CA")
    zone = fx.create_delivery_zone(
        api, policy["id"], zone_code="SF-01", state_code="CA",
        service_mode="DOOR_DELIVERY", postal_codes=["94110"], max_cold_chain_minutes=240,
    )

    resp = api.create_delivery_zone(
        delivery_zone_payload(
            policy["id"],
            zone_code="SF-01",
            state_code="CA",
            service_mode="HUB_PICKUP",
            postal_codes=["94114"],
            max_cold_chain_minutes=180,
        ),
        ADMIN_HEADERS,
    )
    validate_error(resp, ApiErrorId.DUPLICATE_ZONE_CODE, 409)

    stored = validate_success(api.get_delivery_zone(zone["id"], ADMIN_HEADERS))
    assert stored["service_mode"] == "DOOR_DELIVERY", (
        f"the stored zone must keep its service_mode, got {stored['service_mode']}"
    )
    assert stored["postal_codes"] == ["94110"]
    assert stored["version"] == zone["version"]

    rows, meta = validate_paginated(api.list_delivery_zones(ADMIN_HEADERS, {"state_code": "CA"}))
    assert meta["total_count"] == 1, f"exactly one CA zone must exist, got {meta['total_count']}"


# ==========================================================================
# Onboarding-document conditional fields and certificate validity span
# ==========================================================================
def test_04_document_conditional_fields_must_belong_to_the_doc_type(api):
    """Both directions of the conditional-field shape rule are rejected.

    PRD: "A `FOOD_HANDLER_CERT` requires `certificate_number`, `issuing_authority`, `issued_on` and `expires_on`, and forbids `kitchen_type_claimed` and `inspection_date`; a `KITCHEN_INSPECTION` requires `kitchen_type_claimed` and `inspection_date` and forbids the four certificate fields."
    Design: Corner/validations/document_conditional_fields_beat_certificate_validity_window_rejected
    """
    fx.reset_clock(api)
    fx.create_state_policy(api, state_code="CA", cert_validity_max_days=1825)
    cook = fx.register_cook(
        api, legal_name="Dara Osei", email="dara@example.com", state_code="CA",
        claimed_kitchen_type="HOME_COTTAGE",
    )
    cook_v0 = cook["version"]
    cook_headers = make_cook_headers(cook["id"])

    cert_with_kitchen_fields = {
        "cook_id": cook["id"],
        "doc_type": "FOOD_HANDLER_CERT",
        "expected_cook_version": cook_v0,
        "kitchen_type_claimed": "HOME_COTTAGE",
        "inspection_date": "2026-06-01",
    }
    validate_error(
        api.create_onboarding_document(cert_with_kitchen_fields, cook_headers),
        ApiErrorId.DOC_FIELDS_INVALID_FOR_TYPE,
        422,
    )

    inspection_with_cert_fields = {
        "cook_id": cook["id"],
        "doc_type": "KITCHEN_INSPECTION",
        "expected_cook_version": cook_v0,
        "certificate_number": "FH-9",
        "issuing_authority": "CA DPH",
        "issued_on": "2026-01-15",
        "expires_on": "2028-01-15",
    }
    validate_error(
        api.create_onboarding_document(inspection_with_cert_fields, cook_headers),
        ApiErrorId.DOC_FIELDS_INVALID_FOR_TYPE,
        422,
    )

    stored = fx.read_cook(api, cook["id"])
    assert stored["onboarding_status"] == "DRAFT", (
        f"a rejected submission must not advance onboarding, got {stored['onboarding_status']}"
    )
    assert stored["version"] == cook_v0, "a rejected submission must not increment the cook's version"
    rows, meta = validate_paginated(
        api.list_onboarding_documents(ADMIN_HEADERS, {"cook_id": cook["id"]})
    )
    assert meta["total_count"] == 0, f"no document may have been created, got {meta['total_count']}"


def test_05_conditional_field_rule_masks_the_certificate_validity_rule(api):
    """A certificate that carries a kitchen field and also over-runs its validity span reports the field-shape error.

    PRD: "Lower-numbered checks are evaluated first and mask everything below them."
    Design: Corner/validations/document_conditional_fields_beat_certificate_validity_window_rejected
    """
    fx.reset_clock(api)
    fx.create_state_policy(api, state_code="CA", cert_validity_max_days=1825)
    cook = fx.register_cook(
        api, legal_name="Dara Osei", email="dara@example.com", state_code="CA",
        claimed_kitchen_type="HOME_COTTAGE",
    )
    cook_v0 = cook["version"]

    both_wrong = {
        "cook_id": cook["id"],
        "doc_type": "FOOD_HANDLER_CERT",
        "expected_cook_version": cook_v0,
        "certificate_number": "FH-1",
        "issuing_authority": "CA DPH",
        "issued_on": "2026-01-15",
        "expires_on": "2032-01-15",
        "kitchen_type_claimed": "HOME_COTTAGE",
    }
    validate_error(
        api.create_onboarding_document(both_wrong, make_cook_headers(cook["id"])),
        ApiErrorId.DOC_FIELDS_INVALID_FOR_TYPE,
        422,
    )

    stored = fx.read_cook(api, cook["id"])
    assert stored["onboarding_status"] == "DRAFT"
    assert stored["version"] == cook_v0
    rows, meta = validate_paginated(
        api.list_onboarding_documents(ADMIN_HEADERS, {"cook_id": cook["id"]})
    )
    assert meta["total_count"] == 0, f"no document may have been created, got {meta['total_count']}"


def test_06_certificate_validity_span_and_date_order_are_rejected(api):
    """An over-long span and a backwards expiry both fail under the certificate-validity rule, and a legal certificate is then admitted.

    PRD: "For a certificate, `expires_on` must fall strictly after `issued_on` and the number of days between them must not exceed the governing state's `cert_validity_max_days`; either failure is `ERR_CERT_VALIDITY_TOO_LONG`."
    Design: Corner/validations/document_conditional_fields_beat_certificate_validity_window_rejected
    """
    fx.reset_clock(api)
    fx.create_state_policy(api, state_code="CA", cert_validity_max_days=1825)
    cook = fx.register_cook(
        api, legal_name="Dara Osei", email="dara@example.com", state_code="CA",
        claimed_kitchen_type="HOME_COTTAGE",
    )
    cook_v0 = cook["version"]
    cook_headers = make_cook_headers(cook["id"])

    # 2032-01-15 minus 2026-01-15 is 2192 days, above the state's 1825-day ceiling.
    validate_error(
        api.create_onboarding_document(
            food_handler_cert_payload(
                cook["id"], cook_v0, certificate_number="FH-2",
                issued_on="2026-01-15", expires_on="2032-01-15",
            ),
            cook_headers,
        ),
        ApiErrorId.CERT_VALIDITY_TOO_LONG,
        422,
    )
    # expires_on must be strictly after issued_on.
    validate_error(
        api.create_onboarding_document(
            food_handler_cert_payload(
                cook["id"], cook_v0, certificate_number="FH-3",
                issued_on="2026-01-15", expires_on="2025-12-15",
            ),
            cook_headers,
        ),
        ApiErrorId.CERT_VALIDITY_TOO_LONG,
        422,
    )

    untouched = fx.read_cook(api, cook["id"])
    assert untouched["onboarding_status"] == "DRAFT"
    assert untouched["version"] == cook_v0, "neither rejection may increment the cook's version"
    rows, meta = validate_paginated(
        api.list_onboarding_documents(ADMIN_HEADERS, {"cook_id": cook["id"]})
    )
    assert meta["total_count"] == 0, f"no document may have been created, got {meta['total_count']}"

    accepted = validate_success(
        api.create_onboarding_document(
            food_handler_cert_payload(
                cook["id"], cook_v0, certificate_number="FH-4",
                issued_on="2026-01-15", expires_on="2028-01-15",
            ),
            cook_headers,
        ),
        201,
    )
    assert accepted["review_status"] == "SUBMITTED"
    advanced = fx.read_cook(api, cook["id"])
    assert advanced["onboarding_status"] == "DOCS_SUBMITTED"
    assert advanced["version"] == cook_v0 + 1


# ==========================================================================
# Production-window interval ordering and capacity bounds
# ==========================================================================
def test_07_window_instants_must_strictly_increase(api):
    """A cutoff after the handoff opening and a handoff that ends before it starts are both rejected.

    PRD: "The three instants must be in strictly increasing order — cutoff before handoff start, handoff start before handoff end — and any violation is `ERR_CUTOFF_AFTER_HANDOFF`."
    Design: Corner/validations/window_creation_interval_and_capacity_violations_rejected
    """
    fx.reset_clock(api)
    setup = fx.onboard_active_cook(api)

    validate_error(
        api.create_production_window(
            production_window_payload(
                setup.cook_id,
                order_cutoff_at="2026-08-09T00:00:00Z",
                handoff_start_at="2026-08-08T16:00:00Z",
                handoff_end_at="2026-08-08T18:00:00Z",
            ),
            setup.cook_headers,
        ),
        ApiErrorId.CUTOFF_AFTER_HANDOFF,
        422,
    )
    validate_error(
        api.create_production_window(
            production_window_payload(
                setup.cook_id,
                order_cutoff_at="2026-08-05T00:00:00Z",
                handoff_start_at="2026-08-08T18:00:00Z",
                handoff_end_at="2026-08-08T16:00:00Z",
            ),
            setup.cook_headers,
        ),
        ApiErrorId.CUTOFF_AFTER_HANDOFF,
        422,
    )

    rows, meta = validate_paginated(
        api.list_production_windows(ADMIN_HEADERS, {"cook_id": setup.cook_id})
    )
    assert meta["total_count"] == 0, (
        f"a rejected creation must leave no window behind, got {meta['total_count']}"
    )


def test_08_window_capacity_bounds_rejected_and_the_cook_limit_admitted(api):
    """Capacity above the cook's weekly limit and a zero capacity are rejected, while capacity exactly at the limit is admitted.

    PRD: "`capacity_meals` must be at least 1 and no greater than the cook's `weekly_capacity_meals`, failing which the request is `ERR_WINDOW_CAPACITY_ABOVE_COOK_LIMIT`."
    Design: Corner/validations/window_creation_interval_and_capacity_violations_rejected
    """
    fx.reset_clock(api)
    setup = fx.onboard_active_cook(api, cook_overrides={"weekly_capacity_meals": 40})
    assert setup.cook["weekly_capacity_meals"] == 40

    validate_error(
        api.create_production_window(
            production_window_payload(setup.cook_id, capacity_meals=60), setup.cook_headers
        ),
        ApiErrorId.WINDOW_CAPACITY_ABOVE_COOK_LIMIT,
        422,
    )
    validate_error(
        api.create_production_window(
            production_window_payload(setup.cook_id, capacity_meals=0), setup.cook_headers
        ),
        ApiErrorId.WINDOW_CAPACITY_ABOVE_COOK_LIMIT,
        422,
    )

    rows, meta = validate_paginated(
        api.list_production_windows(ADMIN_HEADERS, {"cook_id": setup.cook_id})
    )
    assert meta["total_count"] == 0, (
        f"a rejected creation must leave no window behind, got {meta['total_count']}"
    )

    window = validate_success(
        api.create_production_window(
            production_window_payload(setup.cook_id, capacity_meals=40), setup.cook_headers
        ),
        201,
    )
    assert window["capacity_meals"] == 40
    assert window["status"] == "OPEN"
    assert_capacity_triple(window, 0, capacity_meals=40)

    rows, meta = validate_paginated(
        api.list_production_windows(ADMIN_HEADERS, {"cook_id": setup.cook_id})
    )
    assert meta["total_count"] == 1, f"exactly one window must exist, got {meta['total_count']}"


# ==========================================================================
# Order placement: quantity band, dish state and zone geography
# ==========================================================================
def test_09_order_quantity_bounds_rejected_and_the_maximum_admitted(api):
    """A zero quantity and a quantity of twenty-one are rejected, while exactly twenty is admitted.

    PRD: "`quantity` must be an integer of at least 1 and at most 20; anything outside that band is `ERR_INVALID_QUANTITY`."
    Design: Corner/validations/order_placement_quantity_menu_state_and_zone_violations_rejected
    """
    fx.reset_clock(api)
    setup = fx.selling_cook(
        api,
        item_overrides={"unit_price_cents": 400},
        window_overrides={"capacity_meals": 20},
    )

    for bad_quantity in (0, 21):
        validate_error(
            api.create_order(
                order_payload(
                    setup.menu_item["id"], setup.window["id"], setup.zone["id"],
                    quantity=bad_quantity,
                ),
                DINER_ONE_HEADERS,
            ),
            ApiErrorId.INVALID_QUANTITY,
            422,
        )

    untouched = fx.read_window(api, setup.window["id"])
    assert untouched["committed_meals"] == 0, (
        f"a rejected placement must not commit meals, got {untouched['committed_meals']}"
    )
    rows, meta = validate_paginated(api.list_orders(ADMIN_HEADERS, {"cook_id": setup.cook_id}))
    assert meta["total_count"] == 0, f"no order may have been created, got {meta['total_count']}"

    order = validate_success(
        api.create_order(
            order_payload(
                setup.menu_item["id"], setup.window["id"], setup.zone["id"], quantity=20
            ),
            DINER_ONE_HEADERS,
        ),
        201,
    )
    assert order["quantity"] == 20
    assert order["subtotal_cents"] == 8000, (
        f"20 meals at 400 cents must subtotal 8000 cents, got {order['subtotal_cents']}"
    )
    assert_capacity_triple(fx.read_window(api, setup.window["id"]), 20, capacity_meals=20)


def test_10_order_against_an_unapproved_dish_is_rejected(api):
    """A dish still in DRAFT cannot be ordered, and that rejection outranks an out-of-band quantity.

    PRD: "The ordered menu item has `review_status` equal to `APPROVED` — `ERR_MENU_ITEM_NOT_APPROVED`, 409, on order placement."
    Design: Corner/validations/order_placement_quantity_menu_state_and_zone_violations_rejected
    """
    fx.reset_clock(api)
    setup = fx.selling_cook(
        api,
        item_overrides={"unit_price_cents": 400},
        window_overrides={"capacity_meals": 20},
    )
    draft_item = fx.draft_menu_item(api, setup.cook, name="Unreviewed Pozole")
    assert draft_item["review_status"] == "DRAFT"

    validate_error(
        api.create_order(
            order_payload(draft_item["id"], setup.window["id"], setup.zone["id"], quantity=2),
            DINER_ONE_HEADERS,
        ),
        ApiErrorId.MENU_ITEM_NOT_APPROVED,
        409,
    )
    # The dish-state check sits above the quantity band, so it still speaks for 99 meals.
    validate_error(
        api.create_order(
            order_payload(draft_item["id"], setup.window["id"], setup.zone["id"], quantity=99),
            DINER_ONE_HEADERS,
        ),
        ApiErrorId.MENU_ITEM_NOT_APPROVED,
        409,
    )

    untouched = fx.read_window(api, setup.window["id"])
    assert untouched["committed_meals"] == 0, (
        f"a rejected placement must not commit meals, got {untouched['committed_meals']}"
    )
    rows, meta = validate_paginated(api.list_orders(ADMIN_HEADERS, {"cook_id": setup.cook_id}))
    assert meta["total_count"] == 0, f"no order may have been created, got {meta['total_count']}"


def test_11_order_into_a_foreign_state_zone_is_rejected(api):
    """A Californian cook's dish cannot be ordered into a Nevada delivery zone.

    PRD: "The delivery zone's `state_code` must equal the cook's `state_code`, or the placement is `ERR_ZONE_STATE_MISMATCH` — a Californian cook cannot ship into an Oregon zone."
    Design: Corner/validations/order_placement_quantity_menu_state_and_zone_violations_rejected
    """
    fx.reset_clock(api)
    setup = fx.selling_cook(
        api,
        item_overrides={"unit_price_cents": 400},
        window_overrides={"capacity_meals": 20},
    )
    nevada_policy = fx.create_state_policy(api, state_code="NV")
    nevada_zone = fx.create_delivery_zone(
        api, nevada_policy["id"], zone_code="NV-DOOR-01", state_code="NV", postal_codes=["89101"]
    )

    validate_error(
        api.create_order(
            order_payload(
                setup.menu_item["id"], setup.window["id"], nevada_zone["id"], quantity=2
            ),
            DINER_ONE_HEADERS,
        ),
        ApiErrorId.ZONE_STATE_MISMATCH,
        422,
    )

    untouched = fx.read_window(api, setup.window["id"])
    assert untouched["committed_meals"] == 0, (
        f"a rejected placement must not commit meals, got {untouched['committed_meals']}"
    )
    rows, meta = validate_paginated(api.list_orders(ADMIN_HEADERS, {"cook_id": setup.cook_id}))
    assert meta["total_count"] == 0, f"no order may have been created, got {meta['total_count']}"


# ==========================================================================
# Menu-item approval: allergen disclosure and label completeness
# ==========================================================================
def test_12_approval_requires_an_allergen_disclosure(api):
    """A dish with neither declared allergens nor an allergen-free attestation cannot be approved, though it may sit in review.

    PRD: "The item's `allergens` list is non-empty, or `allergen_free_attested` is true — `ERR_ALLERGEN_DISCLOSURE_MISSING`, 422, on menu-item approval only, so a non-compliant draft can still enter review and be bounced by the reviewer."
    Design: Corner/validations/menu_item_approval_disclosure_and_label_violations_rejected
    """
    fx.reset_clock(api)
    setup = fx.onboard_active_cook(api)
    item = fx.draft_menu_item(
        api, setup.cook, name="Undeclared Flan", allergens=[], allergen_free_attested=False
    )
    assert item["label_compliance_status"] == "COMPLIANT"
    item = fx.submit_menu_item(api, setup.cook_id, item["id"])
    assert item["review_status"] == "UNDER_REVIEW", "an undisclosed draft may still enter review"

    validate_error(
        api.review_menu_item(
            item["id"],
            menu_item_review_payload("APPROVE", allergen_review_notes="allergen panel reviewed"),
            REVIEWER_ONE_HEADERS,
        ),
        ApiErrorId.ALLERGEN_DISCLOSURE_MISSING,
        422,
    )

    unchanged = fx.read_menu_item(api, item["id"])
    assert unchanged["review_status"] == "UNDER_REVIEW", (
        f"a rejected approval must not publish the dish, got {unchanged['review_status']}"
    )
    assert unchanged["approved_by_user_id"] is None
    assert unchanged["approved_at"] is None
    assert unchanged["revision_round"] == 0, (
        f"a rejected approval must not consume a revision round, got {unchanged['revision_round']}"
    )

    bounced = fx.review_menu_item(
        api, item["id"], "REQUEST_REVISION", REVIEWER_ONE_HEADERS,
        revision_note="declare the allergens or attest they are absent",
    )
    assert bounced["review_status"] == "REVISION_REQUESTED"
    assert bounced["revision_round"] == 1


def test_13_approval_requires_a_complete_label_declaration(api):
    """A dish whose label declaration omits a required key cannot be approved, though submission only recomputes its label status.

    PRD: "The item's `label_fields` covers every key in the state policy's `label_required_fields`, equivalently its `label_compliance_status` is `COMPLIANT` — `ERR_LABEL_FIELDS_INCOMPLETE`, 422, on menu-item approval only; submission for review merely recomputes `label_compliance_status` without rejecting."
    Design: Corner/validations/menu_item_approval_disclosure_and_label_violations_rejected
    """
    fx.reset_clock(api)
    setup = fx.onboard_active_cook(api)
    partial_label = [key for key in STANDARD_LABEL_FIELDS if key != "net_weight"]
    item = fx.draft_menu_item(
        api, setup.cook, name="Unlabelled Tamales", allergens=["MILK"], label_fields=partial_label
    )
    assert item["label_compliance_status"] == "MISSING_FIELDS", (
        "a draft missing net_weight records the gap rather than being refused"
    )
    item = fx.submit_menu_item(api, setup.cook_id, item["id"])
    assert item["review_status"] == "UNDER_REVIEW", "submission must not reject an incomplete label"
    assert item["label_compliance_status"] == "MISSING_FIELDS"

    validate_error(
        api.review_menu_item(
            item["id"],
            menu_item_review_payload("APPROVE", allergen_review_notes="allergen panel reviewed"),
            REVIEWER_ONE_HEADERS,
        ),
        ApiErrorId.LABEL_FIELDS_INCOMPLETE,
        422,
    )

    unchanged = fx.read_menu_item(api, item["id"])
    assert unchanged["review_status"] == "UNDER_REVIEW"
    assert unchanged["approved_by_user_id"] is None
    assert unchanged["approved_at"] is None
    assert unchanged["revision_round"] == 0


def test_14_missing_allergen_disclosure_outranks_the_incomplete_label(api):
    """A dish that violates both the disclosure rule and the label rule reports the disclosure error.

    PRD: "When several checks could reject the same request, exactly one error is returned, and which one is fully determined by a global precedence ladder."
    Design: Corner/validations/menu_item_approval_disclosure_and_label_violations_rejected
    """
    fx.reset_clock(api)
    setup = fx.onboard_active_cook(api)
    item = fx.draft_menu_item(
        api,
        setup.cook,
        name="Doubly Deficient Pie",
        allergens=[],
        allergen_free_attested=False,
        label_fields=[key for key in STANDARD_LABEL_FIELDS if key != "allergens"],
    )
    assert item["label_compliance_status"] == "MISSING_FIELDS"
    item = fx.submit_menu_item(api, setup.cook_id, item["id"])
    assert item["review_status"] == "UNDER_REVIEW"

    validate_error(
        api.review_menu_item(
            item["id"],
            menu_item_review_payload("APPROVE", allergen_review_notes="allergen panel reviewed"),
            REVIEWER_ONE_HEADERS,
        ),
        ApiErrorId.ALLERGEN_DISCLOSURE_MISSING,
        422,
    )

    unchanged = fx.read_menu_item(api, item["id"])
    assert unchanged["review_status"] == "UNDER_REVIEW"
    assert unchanged["approved_by_user_id"] is None
    assert unchanged["revision_round"] == 0


# ==========================================================================
# Refund recording: payment state and amount ceiling
# ==========================================================================
def test_15_refund_against_an_authorized_order_is_rejected(api):
    """An order whose payment is still merely authorised cannot be refunded.

    PRD: "The order named by a refund has `payment_status` equal to `CAPTURED` or `PARTIALLY_REFUNDED` — `ERR_ORDER_NOT_REFUNDABLE`, 409, on refund recording."
    Design: Corner/validations/refund_creation_payment_state_and_amount_violations_rejected
    """
    fx.reset_clock(api)
    setup = fx.selling_cook(api, item_overrides={"unit_price_cents": 400})
    order = fx.order_in_scenario(api, setup, quantity=2)
    assert order["payment_status"] == "AUTHORIZED"

    validate_error(
        api.create_refund_event(
            refund_event_payload(order["id"], refund_amount_cents=100), FINANCE_ONE_HEADERS
        ),
        ApiErrorId.ORDER_NOT_REFUNDABLE,
        409,
    )

    unchanged = fx.read_order(api, order["id"])
    assert unchanged["payment_status"] == "AUTHORIZED", (
        f"a rejected refund must not move payment, got {unchanged['payment_status']}"
    )
    assert unchanged["refunded_cents"] == 0
    assert unchanged["cook_chargeback_cents"] == 0
    rows, meta = validate_paginated(
        api.list_refund_events(FINANCE_ONE_HEADERS, {"order_id": order["id"]})
    )
    assert meta["total_count"] == 0, f"no refund event may exist, got {meta['total_count']}"


def test_16_refundability_outranks_the_refund_amount_ceiling(api):
    """An over-large refund against an authorised order reports the refundability error, not the amount error.

    PRD: "Lower-numbered checks are evaluated first and mask everything below them."
    Design: Corner/validations/refund_creation_payment_state_and_amount_violations_rejected
    """
    fx.reset_clock(api)
    setup = fx.selling_cook(api, item_overrides={"unit_price_cents": 400})
    order = fx.order_in_scenario(api, setup, quantity=2)
    assert order["payment_status"] == "AUTHORIZED"

    validate_error(
        api.create_refund_event(
            refund_event_payload(order["id"], refund_amount_cents=99999), FINANCE_ONE_HEADERS
        ),
        ApiErrorId.ORDER_NOT_REFUNDABLE,
        409,
    )

    unchanged = fx.read_order(api, order["id"])
    assert unchanged["payment_status"] == "AUTHORIZED"
    assert unchanged["refunded_cents"] == 0
    rows, meta = validate_paginated(
        api.list_refund_events(FINANCE_ONE_HEADERS, {"order_id": order["id"]})
    )
    assert meta["total_count"] == 0, f"no refund event may exist, got {meta['total_count']}"


def test_17_refund_amount_outside_the_remaining_band_is_rejected(api):
    """A refund larger than the remaining charge and a refund of zero are both rejected.

    PRD: "`refund_amount_cents` is at least 1 and at most the order's `total_charge_cents` minus its `refunded_cents` — `ERR_REFUND_EXCEEDS_REMAINING`, 422, on refund recording."
    Design: Corner/validations/refund_creation_payment_state_and_amount_violations_rejected
    """
    fx.reset_clock(api)
    setup = fx.closed_window_scenario(api, quantity=2, item_overrides={"unit_price_cents": 400})
    order = setup.order
    assert order["payment_status"] == "CAPTURED"
    assert order["total_charge_cents"] == 872, (
        f"800 cents of meals plus a 72-cent service fee is 872, got {order['total_charge_cents']}"
    )
    assert order["refunded_cents"] == 0

    for bad_amount in (2000, 0):
        validate_error(
            api.create_refund_event(
                refund_event_payload(order["id"], refund_amount_cents=bad_amount),
                FINANCE_ONE_HEADERS,
            ),
            ApiErrorId.REFUND_EXCEEDS_REMAINING,
            422,
        )

    unchanged = fx.read_order(api, order["id"])
    assert unchanged["payment_status"] == "CAPTURED", (
        f"a rejected refund must leave the payment captured, got {unchanged['payment_status']}"
    )
    assert unchanged["refunded_cents"] == 0
    assert unchanged["cook_chargeback_cents"] == 0
    assert unchanged["commission_reversed_cents"] == 0
    assert unchanged["platform_absorbed_cents"] == 0
    rows, meta = validate_paginated(
        api.list_refund_events(FINANCE_ONE_HEADERS, {"order_id": order["id"]})
    )
    assert meta["total_count"] == 0, f"no refund event may exist, got {meta['total_count']}"


def test_18_a_refund_of_exactly_the_remaining_charge_is_admitted_and_closes_the_order(api):
    """A refund of the whole remaining charge is admitted, and the now fully refunded order refuses a further cent.

    PRD: "An `AUTHORIZED`, `VOIDED` or fully `REFUNDED` order cannot be refunded."
    Design: Corner/validations/refund_creation_payment_state_and_amount_violations_rejected
    """
    fx.reset_clock(api)
    setup = fx.closed_window_scenario(api, quantity=2, item_overrides={"unit_price_cents": 400})
    order = setup.order
    assert order["total_charge_cents"] == 872
    assert order["cook_earnings_cents"] == 620
    assert order["platform_commission_cents"] == 180

    refund = validate_success(
        api.create_refund_event(
            refund_event_payload(
                order["id"], refund_amount_cents=872, fault_party="COOK", settle_immediately=True
            ),
            FINANCE_ONE_HEADERS,
        ),
        201,
    )
    assert refund["refund_amount_cents"] == 872
    assert refund["cook_chargeback_cents"] == 620
    assert refund["commission_reversed_cents"] == 180
    assert refund["platform_absorbed_cents"] == 72
    assert_refund_three_bucket_identity(refund)

    refunded_order = fx.read_order(api, order["id"])
    assert refunded_order["payment_status"] == "REFUNDED"
    assert refunded_order["refunded_cents"] == 872

    validate_error(
        api.create_refund_event(
            refund_event_payload(order["id"], refund_amount_cents=1), FINANCE_ONE_HEADERS
        ),
        ApiErrorId.ORDER_NOT_REFUNDABLE,
        409,
    )

    still_refunded = fx.read_order(api, order["id"])
    assert still_refunded["payment_status"] == "REFUNDED"
    assert still_refunded["refunded_cents"] == 872
    rows, meta = validate_paginated(
        api.list_refund_events(FINANCE_ONE_HEADERS, {"order_id": order["id"]})
    )
    assert meta["total_count"] == 1, f"exactly one refund event must exist, got {meta['total_count']}"


# ==========================================================================
# Payout statements: a single live statement and the suspension hold
# ==========================================================================
def test_19_a_second_live_statement_for_the_same_pair_is_rejected(api):
    """Once a statement for a cook-and-window pair is finalised, a second statement for that pair cannot be created.

    PRD: "A creation that would produce a second live statement, and equally an attempt to finalise a second one, is rejected with `ERR_DUPLICATE_FINALIZED_STATEMENT`."
    Design: Corner/validations/duplicate_finalized_statement_and_suspended_payout_rejected
    """
    fx.reset_clock(api)
    setup = fx.closed_window_scenario(api, quantity=2, item_overrides={"unit_price_cents": 400})
    fx.record_refund(api, setup.order["id"], refund_amount_cents=100, fault_party="COOK")
    statement = fx.draft_payout_statement(api, setup.cook_id, setup.window["id"])
    statement = fx.advance_statement(api, statement["id"], "FINALIZED")
    assert statement["status"] == "FINALIZED"
    assert statement["net_payout_cents"] == 520, (
        f"800 gross less 180 commission less a 100-cent chargeback is 520, "
        f"got {statement['net_payout_cents']}"
    )

    validate_error(
        api.create_payout_statement(
            payout_statement_payload(
                setup.cook_id,
                setup.window["id"],
                fx.window_version(api, setup.window["id"]),
                basis="CASH_HANDOFF",
            ),
            FINANCE_ONE_HEADERS,
        ),
        ApiErrorId.DUPLICATE_FINALIZED_STATEMENT,
        409,
    )

    unchanged = fx.read_statement(api, statement["id"])
    assert unchanged["status"] == "FINALIZED", (
        f"the live statement must be untouched, got {unchanged['status']}"
    )
    assert unchanged["net_payout_cents"] == 520
    rows, meta = validate_paginated(
        api.list_payout_statements(FINANCE_ONE_HEADERS, {"cook_id": setup.cook_id})
    )
    assert meta["total_count"] == 1, (
        f"the rejected creation must leave exactly one statement, got {meta['total_count']}"
    )


def test_20_payment_of_a_suspended_cook_is_rejected_until_reinstatement(api):
    """A finalised statement cannot be paid while the cook is suspended, and payment succeeds once the cook is reinstated.

    PRD: "`FINALIZED → PAID` requires that the cook's `compliance_standing` be neither `SUSPENDED` nor `REVOKED`, since in those standings `safety_hold_cents` already covers the entire net; an attempt anyway is `ERR_PAYOUT_HOLD_ACTIVE`."
    Design: Corner/validations/duplicate_finalized_statement_and_suspended_payout_rejected
    """
    fx.reset_clock(api)
    setup = fx.closed_window_scenario(api, quantity=2, item_overrides={"unit_price_cents": 400})
    fx.record_refund(api, setup.order["id"], refund_amount_cents=100, fault_party="COOK")
    statement = fx.draft_payout_statement(api, setup.cook_id, setup.window["id"])
    statement = fx.advance_statement(api, statement["id"], "FINALIZED")
    assert statement["safety_hold_cents"] == 0, "the statement was drafted while the cook was CLEAR"
    assert statement["net_payout_cents"] == 520

    suspended = fx.suspend_cook(api, setup.cook_id)
    assert suspended["compliance_standing"] == "SUSPENDED"

    validate_error(
        api.advance_payout_statement(
            statement["id"], statement_advance_payload("PAID"), FINANCE_ONE_HEADERS
        ),
        ApiErrorId.PAYOUT_HOLD_ACTIVE,
        409,
    )

    held = fx.read_statement(api, statement["id"])
    assert held["status"] == "FINALIZED", (
        f"a blocked payment must leave the statement finalised, got {held['status']}"
    )
    assert held["paid_at"] is None
    assert held["net_payout_cents"] == 520
    assert fx.read_cook(api, setup.cook_id)["lifetime_paid_cents"] == 0, (
        "a blocked payment must not credit the cook's lifetime paid total"
    )

    reinstated = fx.reinstate_cook(api, setup.cook_id)
    assert reinstated["compliance_standing"] == "CLEAR"
    paid = fx.advance_statement(api, statement["id"], "PAID")
    assert paid["status"] == "PAID"
    assert paid["paid_at"] is not None
    assert fx.read_cook(api, setup.cook_id)["lifetime_paid_cents"] == 520


# ==========================================================================
# Hub consolidation eligibility and incident subject shape
# ==========================================================================
def test_21_consolidating_a_hub_in_a_door_delivery_zone_is_rejected(api):
    """A hub whose zone runs door delivery cannot be consolidated, even once its window has passed its cutoff.

    PRD: "The hub's zone must have `service_mode` `HUB_PICKUP` and its `state_code` must equal the window cook's `state_code`, or the request is `ERR_HUB_ZONE_INELIGIBLE`."
    Design: Corner/validations/hub_consolidation_zone_and_incident_subject_violations_rejected
    """
    fx.reset_clock(api)
    setup = fx.selling_cook(api, zone_overrides={"service_mode": "DOOR_DELIVERY"})
    hub = fx.create_pickup_hub(api, setup.zone["id"], name="Doorstep Depot")
    assert hub["status"] == "OPEN"
    assert hub["assigned_order_count"] == 0
    hub_version = hub["version"]

    # The cutoff gate is evaluated before zone eligibility, so satisfy it first.
    fx.set_clock(api, setup.window["order_cutoff_at"])
    window = fx.advance_window(api, setup.window, "CUTOFF_PASSED")
    assert window["status"] == "CUTOFF_PASSED"

    validate_error(
        api.consolidate_pickup_hub(
            hub["id"], consolidate_payload(setup.window["id"]), ADMIN_HEADERS
        ),
        ApiErrorId.HUB_ZONE_INELIGIBLE,
        422,
    )

    unchanged = fx.read_hub(api, hub["id"])
    assert unchanged["assigned_order_count"] == 0, (
        f"a rejected consolidation must attach no order, got {unchanged['assigned_order_count']}"
    )
    assert unchanged["status"] == "OPEN"
    assert unchanged["version"] == hub_version, (
        "a rejected consolidation must not touch the hub's version"
    )


def test_22_incident_subject_identifier_mismatches_are_rejected(api):
    """A dish-subject report without a dish, and a cook-subject report carrying one, are both rejected before a valid one is admitted.

    PRD: "Any other combination — a missing required identifier, a forbidden one supplied, or a referenced dish or order belonging to a different cook — is `ERR_INCIDENT_SUBJECT_MISMATCH`."
    Design: Corner/validations/hub_consolidation_zone_and_incident_subject_violations_rejected
    """
    fx.reset_clock(api)
    setup = fx.selling_cook(api)

    validate_error(
        api.create_safety_incident(
            safety_incident_payload(setup.cook_id, subject_type="MENU_ITEM"), DINER_ONE_HEADERS
        ),
        ApiErrorId.INCIDENT_SUBJECT_MISMATCH,
        422,
    )
    validate_error(
        api.create_safety_incident(
            safety_incident_payload(
                setup.cook_id, subject_type="COOK", menu_item_id=setup.menu_item["id"]
            ),
            DINER_ONE_HEADERS,
        ),
        ApiErrorId.INCIDENT_SUBJECT_MISMATCH,
        422,
    )

    rows, meta = validate_paginated(
        api.list_safety_incidents(ADMIN_HEADERS, {"cook_id": setup.cook_id})
    )
    assert meta["total_count"] == 0, f"no incident may have been created, got {meta['total_count']}"
    assert fx.read_cook(api, setup.cook_id)["safety_score"] == 100, (
        "a rejected intake must not charge the cook's safety score"
    )

    accepted = validate_success(
        api.create_safety_incident(
            safety_incident_payload(
                setup.cook_id, subject_type="MENU_ITEM", menu_item_id=setup.menu_item["id"]
            ),
            DINER_ONE_HEADERS,
        ),
        201,
    )
    assert accepted["status"] == "INTAKE"
    assert accepted["menu_item_id"] == setup.menu_item["id"]
    rows, meta = validate_paginated(
        api.list_safety_incidents(ADMIN_HEADERS, {"cook_id": setup.cook_id})
    )
    assert meta["total_count"] == 1, f"exactly one incident must exist, got {meta['total_count']}"


# ==========================================================================
# Hub eligibility filter on routing
# ==========================================================================
def test_23_routing_is_rejected_when_no_hub_covers_the_handoff_interval(api):
    """A hub-pickup order finds no hub when the only hub's staffed interval does not contain the handoff interval.

    PRD: "If no hub survives the filter, the routing is rejected with `ERR_NO_ELIGIBLE_HUB`."
    Design: Corner/validations/routing_rejected_when_no_hub_survives_the_eligibility_filter
    """
    fx.reset_clock(api)
    setup = fx.selling_cook(
        api, zone_overrides={"service_mode": "HUB_PICKUP", "zone_code": "HUB-04"}
    )
    narrow_hub = fx.create_pickup_hub(
        api,
        setup.zone["id"],
        name="Narrow Depot",
        hub_window_start_at="2026-08-08T16:30:00Z",
        hub_window_end_at="2026-08-08T17:00:00Z",
    )
    order = fx.order_in_scenario(api, setup, quantity=2)
    assert order["fulfillment_status"] == "PLACED"

    validate_error(
        api.route_order(order["id"], ADMIN_HEADERS), ApiErrorId.NO_ELIGIBLE_HUB, 422
    )

    unchanged = fx.read_order(api, order["id"])
    assert unchanged["fulfillment_status"] == "PLACED", (
        f"a rejected routing must not advance the order, got {unchanged['fulfillment_status']}"
    )
    assert unchanged["routing_mode"] is None
    assert unchanged["pickup_hub_id"] is None
    assert fx.read_hub(api, narrow_hub["id"])["assigned_order_count"] == 0

    covering_hub = fx.create_pickup_hub(
        api,
        setup.zone["id"],
        name="Covering Depot",
        hub_window_start_at="2026-08-08T16:00:00Z",
        hub_window_end_at="2026-08-08T18:00:00Z",
    )
    routed = validate_success(api.route_order(order["id"], ADMIN_HEADERS))
    assert routed["fulfillment_status"] == "ROUTED"
    assert routed["pickup_hub_id"] == covering_hub["id"], (
        "the only hub whose staffed interval contains the handoff interval must be selected"
    )
    filled = fx.read_hub(api, covering_hub["id"])
    assert filled["assigned_order_count"] == 1
    assert filled["status"] == "OPEN"
    assert fx.read_hub(api, narrow_hub["id"])["assigned_order_count"] == 0


# ==========================================================================
# Inputs sitting exactly on their limits
# ==========================================================================
def test_24_inputs_exactly_on_their_limits_are_admitted(api):
    """A certificate spanning exactly the permitted days, a shelf life exactly at the ceiling and a label carrying exactly the required keys are all admitted.

    PRD: "A non-refrigerated item's `shelf_life_days` is at most the state policy's `max_shelf_life_days_non_refrigerated` — `ERR_SHELF_LIFE_EXCEEDS_POLICY`, 422, on menu-item approval only."
    Design: Corner/validations/inputs_sitting_exactly_on_their_limits_are_admitted
    """
    fx.reset_clock(api)
    fx.create_state_policy(
        api,
        state_code="CA",
        cert_validity_max_days=1825,
        max_shelf_life_days_non_refrigerated=14,
        label_required_fields=list(STANDARD_LABEL_FIELDS),
    )
    cook = fx.register_cook(
        api, legal_name="Lena Marsh", email="lena@example.com", state_code="CA",
        claimed_kitchen_type="HOME_INSPECTED",
    )

    # 2026-01-15 to 2031-01-14 spans exactly 1825 days, the permitted maximum.
    cert = validate_success(
        api.create_onboarding_document(
            food_handler_cert_payload(
                cook["id"], cook["version"], certificate_number="FH-1825",
                issued_on="2026-01-15", expires_on="2031-01-14",
            ),
            make_cook_headers(cook["id"]),
        ),
        201,
    )
    assert cert["review_status"] == "SUBMITTED"
    assert cert["expires_on"] == "2031-01-14"

    inspection = fx.submit_kitchen_inspection(api, cook)
    fx.review_document(api, cert["id"], "VERIFY", REVIEWER_ONE_HEADERS)
    fx.review_document(api, inspection["id"], "PASS", REVIEWER_TWO_HEADERS)
    activated = fx.decide_onboarding(api, cook["id"], "ACTIVATE", REVIEWER_ONE_HEADERS)
    assert activated["onboarding_status"] == "ACTIVE"
    assert activated["compliance_standing"] == "CLEAR"

    item = fx.draft_menu_item(
        api,
        activated,
        name="Edge Case Cookies",
        food_category="NON_TCS",
        allergens=[],
        allergen_free_attested=True,
        shelf_life_days=14,
        requires_refrigeration=False,
        label_fields=list(STANDARD_LABEL_FIELDS),
    )
    assert item["shelf_life_days"] == 14
    assert item["label_compliance_status"] == "COMPLIANT", (
        "a label declaring exactly the required keys is compliant"
    )
    submitted = fx.submit_menu_item(api, activated["id"], item["id"])
    assert submitted["review_status"] == "UNDER_REVIEW"

    approved = validate_success(
        api.review_menu_item(
            item["id"],
            menu_item_review_payload("APPROVE", allergen_review_notes="no major allergens present"),
            REVIEWER_ONE_HEADERS,
        )
    )
    assert approved["review_status"] == "APPROVED", (
        f"every input sits exactly on its limit, so approval must pass, got "
        f"{approved['review_status']}"
    )
    assert approved["approved_by_user_id"] == REVIEWER_ONE
    assert approved["approved_at"] is not None
    assert approved["delist_reason"] is None
