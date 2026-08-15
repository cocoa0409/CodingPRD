"""Submission preconditions: item presence, preparation acks, prohibition."""
from test_helpers import (
    ApiErrorId,
    create_household,
    create_draft_request,
    get_request,
    get_request_assessments,
    make_resident_headers,
    set_clock,
    setup_household_with_draft,
    validate_error,
    validate_paginated,
)


class TestSubmissionGates:
    def test_submit_without_items_returns_invalid_request(self, api):
        """PRD §3.2: "The request must contain at least one item, and
        submission is rejected with `ERR_INVALID_REQUEST` when the item list
        is empty or any item fails schema rules (unknown category, duplicated
        or sub-1 `sequence_no`)."

        Design: Corner/state_machines/submit_without_items_returns_invalid_request
        """
        set_clock("2026-08-05T00:00:00Z")
        hh = create_household("7 Zero Ave", "ZONE_NORTH")
        req = create_draft_request(hh["id"])

        resp = api.submit_pickup_request(req["id"], make_resident_headers(hh["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert resp.status_code == 400

        after = get_request(hh["id"], req["id"])
        assert after["status"] == "DRAFT"
        assert get_request_assessments(req["id"]) == []

    def test_submit_with_unacknowledged_preparation_rejected(self, api):
        """PRD §3.2: "Only after the prohibition scan passes does the
        preparation scan run: every item must carry `preparation_ack` equal to
        true, and refrigerant-bearing appliances in particular cannot be
        submitted without that acknowledgement because refrigerant recovery
        preparation is a regulatory requirement; any unacknowledged item fails
        with `ERR_PREPARATION_NOT_ACKED`."

        Design: Corner/state_machines/submit_with_unacknowledged_preparation_rejected
        """
        hh, req, _ = setup_household_with_draft(
            street_address="8 Prep Pl",
            service_zone="ZONE_SOUTH",
            items=((1, "MATTRESS", False, False),),
        )
        resp = api.submit_pickup_request(req["id"], make_resident_headers(hh["id"]))
        validate_error(resp, ApiErrorId.ERR_PREPARATION_NOT_ACKED)
        assert resp.status_code == 422
        assert get_request(hh["id"], req["id"])["status"] == "DRAFT"

    def test_err_prohibited_item_triggerable(self, api):
        """PRD §3.2: "A safety scan then runs, prohibition first: any item
        whose `category` is `PROHIBITED` causes rejection with
        `ERR_PROHIBITED_ITEM`."

        Design: Corner/errors/err_prohibited_item_triggerable
        """
        hh, req, _ = setup_household_with_draft(
            street_address="101 Ban Blvd",
            service_zone="ZONE_NORTH",
            items=((1, "PROHIBITED", False, True),),
        )
        resp = api.submit_pickup_request(req["id"], make_resident_headers(hh["id"]))
        validate_error(resp, ApiErrorId.ERR_PROHIBITED_ITEM)
        assert resp.status_code == 422

    def test_item_add_on_submitted_request_rejected(self, api):
        """PRD §3.2: "Against a draft the resident adds **PickupItems** one at
        a time, declaring for each a `sequence_no` (a 1-based resident-declared
        ordering within the request, unique across the request's items; it
        serves as the tie-breaker in allowance consumption after `created_at`),
        a `category`, an optional `is_oversize` flag defaulting to false, and a
        `preparation_ack` confirming the resident has read the preparation
        instructions for that category."
        PRD §2.9: "(4) state-machine legality — the resource's current state
        lists the attempted trigger, else `ERR_INVALID_STATE`"

        Design: Corner/endpoints/item_add_on_submitted_request_rejected
        """
        hh, req, _ = setup_household_with_draft(
            street_address="99 Addend Aly",
            service_zone="ZONE_NORTH",
            items=((1, "TIRES", False, True),),
        )
        # Move to SUBMITTED.
        resp = api.submit_pickup_request(req["id"], make_resident_headers(hh["id"]))
        assert resp.status_code == 200

        resp = api.add_item(
            req["id"],
            {
                "sequence_no": 2,
                "category": "TIRES",
                "is_oversize": False,
                "preparation_ack": True,
            },
            make_resident_headers(hh["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409

        items = api.list_items(req["id"], make_resident_headers(hh["id"]))
        _, meta = validate_paginated(items)
        assert meta["total_count"] == 1
