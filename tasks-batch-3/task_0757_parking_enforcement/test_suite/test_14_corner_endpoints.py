"""Corner section: endpoints (reverse-lookup / cross-reference links)."""
from test_helpers import (
    validate_paginated,
    TEST_USERS,
    setup_issuing_context,
    issue_in_context,
    create_payment,
    setup_boot_eligible_vehicle,
)

ADMIN = TEST_USERS["admin_headers"]


def test_reverse_lookup_citations_by_vehicle(api):
    """PRD §2.3: "List endpoints additionally accept reverse-lookup filters as query
    parameters — for example a citation listing may be narrowed by `vehicle_id`,
    `shift_id`, `violation_code_id`, `officer_id`, `beat_id`, or `status`."

    Design: Corner/endpoints/reverse_lookup_citations_by_vehicle
    """
    ctx = setup_issuing_context()
    cit = issue_in_context(ctx)
    data, meta = validate_paginated(
        api.list_citations(ADMIN, params={"vehicle_id": ctx["vehicle"]["id"]}))
    assert meta["total_count"] == 1, f"expected 1 citation, got {meta['total_count']}"
    assert data[0]["id"] == cit["id"]


def test_reverse_lookup_payments_by_citation(api):
    """PRD §2.3: "a payment or contest listing by `citation_id` and `status`."

    Design: Corner/endpoints/reverse_lookup_payments_by_citation
    """
    ctx = setup_issuing_context()
    cit = issue_in_context(ctx)
    pay = create_payment(cit["id"], 2500, method="ECHECK")
    data, meta = validate_paginated(
        api.list_payments(ADMIN, params={"citation_id": cit["id"]}))
    assert meta["total_count"] == 1, f"expected 1 payment, got {meta['total_count']}"
    assert data[0]["id"] == pay["id"]


def test_reverse_lookup_registration_holds_by_vehicle(api):
    """PRD §2.3: "and a registration-hold listing by `vehicle_id` or
    `boot_tow_order_id`."

    Design: Corner/endpoints/reverse_lookup_registration_holds_by_vehicle
    """
    ctx = setup_boot_eligible_vehicle()
    data, meta = validate_paginated(
        api.list_registration_holds(ADMIN, params={"vehicle_id": ctx["vehicle"]["id"]}))
    assert meta["total_count"] == 1, f"expected 1 hold, got {meta['total_count']}"
    assert data[0]["status"] == "PLACED"
