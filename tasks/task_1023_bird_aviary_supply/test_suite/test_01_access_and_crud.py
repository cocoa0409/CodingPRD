"""Access control, creation defaults, not-found, required-field, and listing/filter tests.

All tests translate queue-B corner-design instances (breadth coverage).
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    NON_EXISTENT_UUID,
    new_customer, new_species, new_bird, new_inventory,
    make_customer_headers, TEST_USERS,
    create_customer_payload, create_species_payload, create_inventory_item_payload,
    create_subscription_payload,
)

SM = TEST_USERS["store_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]
STAFF = TEST_USERS["aviary_staff_headers"]


def test_customer_create_returns_defaults(api):
    """PRD 3.1: "A new customer begins in ACTIVE status, with club_tier of NONE
    and wallet_credit_cents of 0."

    Design: Corner/entities/customer_create_returns_defaults
    """
    cust = validate_success(api.create_customer(
        create_customer_payload(full_name="Def Ault", email="def@x.com"), SM), 201)
    assert cust["club_tier"] == "NONE"
    assert cust["wallet_credit_cents"] == 0
    assert cust["status"] == "ACTIVE"


def test_customer_get_nonexistent_returns_not_found(api):
    """PRD 2.8: "an unresolved customer yields ERR_CUSTOMER_NOT_FOUND".

    Design: Corner/entities/customer_get_nonexistent_returns_not_found
    """
    res = api.get_customer(NON_EXISTENT_UUID, SM)
    validate_error(res, "ERR_CUSTOMER_NOT_FOUND", expected_status=404)


def test_species_permit_required_computed_from_appendix(api):
    """PRD 3.2: "the species' permit_required flag is computed as true when
    cites_appendix is I, II, or III, and false when it is NONE".
    PRD 3.2: "A new species begins with status ACTIVE and listed_bird_count of 0."

    Design: Corner/entities/species_permit_required_computed_from_appendix
    """
    sp = validate_success(api.create_species(
        create_species_payload(common_name="Hyacinth Macaw",
                               scientific_name="Anodorhynchus hyacinthinus",
                               cites_appendix="I"), CO), 201)
    assert sp["permit_required"] is True
    assert sp["status"] == "ACTIVE"
    assert sp["listed_bird_count"] == 0


def test_inventory_create_missing_required_sku(api):
    """PRD 2.1: "request-body well-formedness — required fields present, correct types,
    valid enum members, and interval/quantity sanity such as planned_check_out strictly
    after planned_check_in, slot_end strictly after slot_start, capacity at least 1,
    bird_count at least 1, and build_qty at least 1"

    Design: Corner/entities/inventory_create_missing_required_sku
    """
    res = api.create_inventory_item({"feed_kind": "DRY", "quantity_on_hand": 5}, SM)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_customer_context_header_required(api):
    """PRD 2.1: "If either header is missing or malformed, the request is rejected
    with ERR_MISSING_USER_CONTEXT (HTTP 400). This check precedes all others."

    Design: Corner/validations/customer_context_header_required
    """
    res = api.list_customers(headers={})
    validate_error(res, "ERR_MISSING_USER_CONTEXT", expected_status=400)


def test_customer_cannot_create_species_forbidden(api):
    """PRD 2.1: "When a role attempts an operation it is not authorized to perform,
    the request is rejected with ERR_FORBIDDEN_ROLE (HTTP 403)."

    Design: Corner/validations/customer_cannot_create_species_forbidden
    """
    res = api.create_species(
        create_species_payload(common_name="Cockatiel",
                               scientific_name="Nymphicus hollandicus",
                               cites_appendix="NONE"),
        make_customer_headers("unused"))
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_compliance_cannot_create_cage_unit(api):
    """PRD 2.1: "When a role attempts an operation it is not authorized to perform,
    the request is rejected with ERR_FORBIDDEN_ROLE (HTTP 403)."

    Design: Corner/roles/compliance_cannot_create_cage_unit
    """
    res = api.create_cage({"label": "X", "cage_class": "HOUSING", "capacity": 1}, CO)
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_pause_others_subscription_not_owner(api):
    """PRD 2.1: "A customer acting on a subscription, boarding reservation, grooming
    appointment, or special order whose customer_id does not equal their X-User-ID
    is rejected with ERR_NOT_RESOURCE_OWNER (HTTP 403)."

    Design: Corner/validations/pause_others_subscription_not_owner
    """
    a = new_customer(wallet_cents=6000)
    sub = validate_success(api.create_subscription(
        create_subscription_payload(a["id"], tier="STANDARD", bird_count=1),
        make_customer_headers(a["id"])), 201)
    b = new_customer()
    res = api.pause_subscription(sub["id"], make_customer_headers(b["id"]))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER", expected_status=403)
    after = validate_success(api.get_subscription(sub["id"], SM), 200)
    assert after["status"] == "ACTIVE"


def test_suspended_customer_cannot_open_subscription(api):
    """PRD 3.1: "A SUSPENDED customer may not open new feed subscriptions or special
    orders, nor be the buyer of a bird; such attempts are rejected with ERR_CUSTOMER_SUSPENDED."

    Design: Corner/validations/suspended_customer_cannot_open_subscription
    """
    cust = new_customer(wallet_cents=6000, suspended=True)
    res = api.create_subscription(
        create_subscription_payload(cust["id"], tier="STANDARD", bird_count=1),
        make_customer_headers(cust["id"]))
    validate_error(res, "ERR_CUSTOMER_SUSPENDED", expected_status=409)


def test_feed_subscriptions_reverse_reachability_by_customer(api):
    """PRD 2.3: "Unless a specific endpoint states otherwise, list results are ordered
    by their created_at timestamp in ascending order."

    Design: Corner/endpoints/feed_subscriptions_reverse_reachability_by_customer
    """
    cust = new_customer(wallet_cents=6000)
    sub = validate_success(api.create_subscription(
        create_subscription_payload(cust["id"], tier="STANDARD", bird_count=1),
        make_customer_headers(cust["id"])), 201)
    data, meta = validate_paginated(api.list_subscriptions(SM, params={"customer_id": cust["id"]}))
    ids = [row["id"] for row in data]
    assert sub["id"] in ids


def test_birds_filtered_by_species(api):
    """PRD 3.4: "Birds can be listed and filtered by their species_id and housing_cage_id."

    Design: Corner/endpoints/birds_filtered_by_species
    """
    sp = new_species("NONE")
    bird = new_bird(sp["id"])
    data, meta = validate_paginated(api.list_birds(STAFF, params={"species_id": sp["id"]}))
    ids = [row["id"] for row in data]
    assert bird["id"] in ids
