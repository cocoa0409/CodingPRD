"""Award issuance and purchase-order intake gates (PRD §3.3, §3.4)."""
from test_helpers import (
    ApiErrorId, TEST_USERS, make_district_buyer_headers, validate_error,
    validate_paginated, validate_success, add_po_line, add_spec_line,
    build_awarded_context, build_accepted_award_context, cancel_po, close_spec,
    create_district, create_po, create_spec, get_po, get_spec, publish_spec,
    set_clock,
)


class TestPOIntakeGate:
    def test_po_intake_rejected_while_award_issued(self, api):
        """PRD §3.4: "Against an `ACCEPTED` award — anything earlier is rejected
        with `ERR_AWARD_NOT_ACTIVE`"

        Design: Difficulty/cross_entity_state_dependency/po_intake_requires_award_accepted
        """
        ctx = build_awarded_context(with_site=False, with_crew=False)
        d_id = ctx["district"]["id"]
        assert ctx["award"]["status"] == "ISSUED"

        resp = api.create_purchase_order(
            {"award_id": ctx["award"]["id"], "po_number": "PO-1", "fiscal_year": 2026},
            make_district_buyer_headers(d_id),
        )
        validate_error(resp, ApiErrorId.ERR_AWARD_NOT_ACTIVE)

    def test_po_intake_succeeds_after_award_acceptance(self, api):
        """PRD §3.3: "A `ContractManager` accepts the award notice, moving it
        `ISSUED` → `ACCEPTED` and incrementing the award's `version`."
        PRD §3.4: "A new purchase order is `RECEIVED`, with `posture` `ON_TRACK`,
        `open_backorder_count` 0, and `total_cents` 0."

        Design: Difficulty/cross_entity_state_dependency/po_intake_requires_award_accepted
        """
        ctx = build_awarded_context(with_site=False, with_crew=False)
        d_id = ctx["district"]["id"]
        assert ctx["award"]["status"] == "ISSUED"

        accepted = validate_success(api.accept_award(
            ctx["award"]["id"], TEST_USERS["contract_manager_headers"]))
        assert accepted["status"] == "ACCEPTED"
        assert accepted["version"] == ctx["award"]["version"] + 1

        po = validate_success(api.create_purchase_order(
            {"award_id": ctx["award"]["id"], "po_number": "PO-1", "fiscal_year": 2026},
            make_district_buyer_headers(d_id),
        ), 201)
        assert po["status"] == "RECEIVED"
        assert po["posture"] == "ON_TRACK"
        assert po["open_backorder_count"] == 0
        assert po["total_cents"] == 0


class TestAwardCreation:
    def test_award_creation_pins_spec_version_and_moves_spec_to_awarded(self, api):
        """PRD §3.3: "Creation stamps the award `ISSUED` and pins
        `awarded_spec_version` to the specification's current `spec_version`; as a
        cascade, the specification itself transitions `CLOSED` → `AWARDED`."

        Design: Corner/state_machines/award_creation_pins_spec_version_and_moves_spec_to_awarded
        """
        set_clock()
        district = create_district()
        d_id = district["id"]
        spec = create_spec(d_id)
        add_spec_line(spec["id"], d_id)
        publish_spec(spec["id"], d_id)
        close_spec(spec["id"], d_id)

        award = validate_success(api.create_award(
            {
                "bid_spec_id": spec["id"],
                "district_id": d_id,
                "pricing_mode": "AWARD_FLAT",
                "flat_unit_price_cents": 11000,
                "install_rate_cents": 25125,
                "order_by_date": "2026-06-01",
                "warranty_years": 5,
            },
            make_district_buyer_headers(d_id),
        ), 201)
        assert award["awarded_spec_version"] == 1
        assert award["status"] == "ISSUED"
        assert get_spec(spec["id"], d_id)["status"] == "AWARDED"

    def test_award_on_unclosed_spec_returns_bid_spec_not_closed(self, api):
        """PRD §3.3: "a specification not yet `CLOSED` yields
        `ERR_BID_SPEC_NOT_CLOSED`"

        Design: Corner/errors/award_on_unclosed_spec_returns_bid_spec_not_closed
        """
        set_clock()
        district = create_district()
        d_id = district["id"]
        spec = create_spec(d_id)
        add_spec_line(spec["id"], d_id)
        publish_spec(spec["id"], d_id)

        resp = api.create_award(
            {
                "bid_spec_id": spec["id"],
                "district_id": d_id,
                "pricing_mode": "AWARD_FLAT",
                "flat_unit_price_cents": 11000,
                "install_rate_cents": 25125,
                "order_by_date": "2026-06-01",
                "warranty_years": 5,
            },
            make_district_buyer_headers(d_id),
        )
        validate_error(resp, ApiErrorId.ERR_BID_SPEC_NOT_CLOSED)


class TestPONumberUniqueness:
    def test_duplicate_po_number_same_district_year_rejected(self, api):
        """PRD §3.4: "The `po_number` must be unique among the district's
        non-`CANCELLED` purchase orders within the same `fiscal_year`; a collision
        is rejected with `ERR_DUPLICATE_PO_NUMBER`."

        Design: Corner/validations/duplicate_po_number_same_district_year_rejected
        """
        ctx = build_accepted_award_context(with_site=False, with_crew=False)
        d_id = ctx["district"]["id"]
        create_po(ctx["award"]["id"], d_id, po_number="PO-1", fiscal_year=2026)

        dup = api.create_purchase_order(
            {"award_id": ctx["award"]["id"], "po_number": "PO-1", "fiscal_year": 2026},
            make_district_buyer_headers(d_id),
        )
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_PO_NUMBER)

        nxt = validate_success(api.create_purchase_order(
            {"award_id": ctx["award"]["id"], "po_number": "PO-1", "fiscal_year": 2027},
            make_district_buyer_headers(d_id),
        ), 201)
        assert nxt["status"] == "RECEIVED"


class TestPOTerminalLockdown:
    def test_po_cancelled_terminal_lockdown_rejects_new_lines(self, api):
        """PRD §2.8: "the target resource's current status permits the requested
        transition (`ERR_INVALID_STATE`, HTTP 409), including terminal lockdown:
        resources in `CANCELLED`, `CLOSED`, or `RESOLVED` accept no further actions."
        PRD §3.4: "Lines are added to the order while it remains `RECEIVED` —
        adding to any other status is `ERR_INVALID_STATE`."

        Design: Corner/state_machines/po_cancelled_terminal_lockdown_rejects_new_lines
        """
        ctx = build_accepted_award_context(with_site=False, with_crew=False)
        d_id = ctx["district"]["id"]
        po = create_po(ctx["award"]["id"], d_id, po_number="PO-1")
        add_po_line(po["id"], ctx["spec_line"]["id"], d_id, 5)
        cancel_po(po["id"], d_id)
        assert get_po(po["id"])["status"] == "CANCELLED"

        resp = api.create_po_line(
            {"purchase_order_id": po["id"], "spec_line_id": ctx["spec_line"]["id"], "ordered_qty": 3},
            make_district_buyer_headers(d_id),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        lines, meta = validate_paginated(api.list_po_lines(
            make_district_buyer_headers(d_id), params={"purchase_order_id": po["id"]}))
        assert len(lines) == 1 and meta["total_count"] == 1
