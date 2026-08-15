"""AOG request filing, sourcing selector, escalation, and cancellation."""
from test_helpers import (
    validate_success, validate_error,
    create_customer, create_part, create_unit, create_aog_request,
    create_aog_request_payload, make_customer_headers, TEST_USERS,
)

AGENT = TEST_USERS["aog_desk_agent_headers"]


def test_aog_request_cross_customer_create_forbidden(api):
    """PRD §3.3: "A `CustomerContact` filing on someone else's account is
    rejected with `ERR_FORBIDDEN`."
    PRD §2.1: "ownership checks on any resource that references a `Customer`
    compare the resource's `customer_id` field to `X-User-ID`."

    Design: Corner/entities/aog_request_cross_customer_create_forbidden
    """
    air_a = create_customer(name="AirA")
    air_b = create_customer(name="AirB")
    part = create_part(part_number="PN-OC")

    res = api.create_aog_request(
        create_aog_request_payload(air_b["id"], part["id"],
                                   aircraft_tail="N1XB"),
        make_customer_headers(air_a["id"]),
    )
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_needed_by_in_past_rejected(api):
    """PRD §3.3: "a hard dispatch deadline `needed_by_utc` that must lie
    strictly after the current clock — a deadline in the past or at the
    present instant is rejected with `ERR_NEEDED_BY_IN_PAST`."

    Design: Corner/validations/needed_by_in_past_rejected
    """
    customer = create_customer(name="PastAir")
    part = create_part(part_number="PN-NP")
    res = api.create_aog_request(
        create_aog_request_payload(
            customer["id"], part["id"], aircraft_tail="N9NP",
            needed_by_utc="2026-04-30T23:59:59Z",
        ),
        AGENT,
    )
    validate_error(res, "ERR_NEEDED_BY_IN_PAST", expected_status=422)


def test_sourcing_selector_fifo_and_eligibility(api):
    """PRD §3.3: "the system considers only units of the requested part that
    are `AVAILABLE`, whose `condition` is in the request's acceptable set, and
    whose trace rank is at least the request's `min_trace_doc` rank. Eligible
    units are ranked oldest first by creation timestamp — first-in-first-out
    stock rotation, with no tie-break needed because creation timestamps are
    unique — and the first unit wins." The winner "moves `AVAILABLE` →
    `RESERVED`, its `reserved_by_request_id` is set to the request, the
    request's `reserved_unit_id` points at the unit, and
    `last_search_candidate_count` records the size of the eligible pool."

    Design: Corner/calculations/sourcing_selector_fifo_and_eligibility
    """
    customer = create_customer(name="SrcAir")
    part = create_part(part_number="PN-SR", rotable=True, core_value_cents=40_000,
                       list_price_cents=100_000)
    u_old = create_unit(part["id"], serial_number="SN-SR-OLD",
                        condition="OVERHAULED", trace_doc_level="DUAL_RELEASE")
    u_new = create_unit(part["id"], serial_number="SN-SR-NEW",
                        condition="OVERHAULED", trace_doc_level="DUAL_RELEASE")
    create_unit(part["id"], serial_number="SN-SR-COND",
                condition="AS_REMOVED", trace_doc_level="DUAL_RELEASE")
    create_unit(part["id"], serial_number="SN-SR-TRACE",
                condition="OVERHAULED", trace_doc_level="TEARDOWN_REPORT")
    aog = create_aog_request(
        customer["id"], part["id"], aircraft_tail="N6SR",
        condition_acceptable=["OVERHAULED"], min_trace_doc="FAA_8130",
    )

    found = validate_success(api.source_search(aog["id"], AGENT))
    assert found["reserved_unit_id"] == u_old["id"], (
        "oldest created_at among eligibles must win (FIFO)"
    )
    assert found["last_search_candidate_count"] == 2, (
        "AS_REMOVED (condition) and TEARDOWN_REPORT (trace rank) are excluded"
    )

    unit_old = validate_success(api.get_inventory_unit(u_old["id"], AGENT))
    assert unit_old["status"] == "RESERVED"
    assert unit_old["reserved_by_request_id"] == aog["id"]
    unit_new = validate_success(api.get_inventory_unit(u_new["id"], AGENT))
    assert unit_new["status"] == "AVAILABLE"


def test_sourcing_empty_pool_fallback(api):
    """PRD §3.3: "An empty pool changes nothing: the request stays `OPEN`, no
    reservation is made, the candidate count is recorded as zero, and the
    search answers `ERR_NO_SOURCE_AVAILABLE` (422)."

    Design: Corner/calculations/sourcing_empty_pool_fallback
    """
    customer = create_customer(name="EmptyAir")
    part = create_part(part_number="PN-EP")
    aog = create_aog_request(customer["id"], part["id"], aircraft_tail="N6EP")

    res = api.source_search(aog["id"], AGENT)
    validate_error(res, "ERR_NO_SOURCE_AVAILABLE", expected_status=422)

    after = validate_success(api.get_aog_request(aog["id"], AGENT))
    assert after["status"] == "OPEN"
    assert after["reserved_unit_id"] is None
    assert after["last_search_candidate_count"] == 0


def test_aog_cancel_releases_reserved_unit(api):
    """PRD §3.3: "from `OPEN`, either a desk agent or the request's own
    customer contact may cancel (a contact canceling another operator's request
    draws `ERR_FORBIDDEN`), and any pinned unit is released back to `AVAILABLE`
    with `reserved_unit_id` nulled." And "`FULFILLED`, `CLOSED`, and
    `CANCELLED` are terminal."

    Design: Corner/state_machines/aog_cancel_releases_reserved_unit
    """
    customer = create_customer(name="RelAir")
    part = create_part(part_number="PN-RL")
    unit = create_unit(part["id"], serial_number="SN-RL1")
    aog = create_aog_request(customer["id"], part["id"], aircraft_tail="N7RL")
    validate_success(api.source_search(aog["id"], AGENT))

    cancelled = validate_success(api.cancel_aog_request(aog["id"], AGENT))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["reserved_unit_id"] is None

    unit_after = validate_success(api.get_inventory_unit(unit["id"], AGENT))
    assert unit_after["status"] == "AVAILABLE"
    assert unit_after["reserved_by_request_id"] is None

    again = api.cancel_aog_request(aog["id"], AGENT)
    validate_error(again, "ERR_INVALID_STATE", expected_status=409)
