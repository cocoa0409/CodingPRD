"""Endpoint contracts: the computed read, the action endpoints and the three envelope shapes."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN_ADJUDICATOR,
    ADMIN_ADJUDICATOR_ID,
    ADMIN_INVESTIGATOR,
    ADMIN_INVESTIGATOR_ID,
    ADMIN_REVIEW,
    ApiErrorId,
    assert_cents,
    assert_envelope_meta,
    assert_error_data_shape,
    assert_fraction,
    assert_instant,
    assert_score,
    make_member_headers,
    make_supplier_headers,
)
from test_helpers.constants import (
    CLOCK_SEP_15,
    CLOCK_SEP_16,
    CLOCK_TERM_START,
    PRIMER_QTY_FOR_5000000,
    SKU_DISPENSER,
)
from test_helpers.factories import (
    ADJUSTMENT_LINE,
    DISPENSER_LINE,
    complaint_payload,
    price_quote_params,
)
from test_helpers.fixtures import (
    file_complaint,
    open_investigation,
    prime_committed_spend,
    read_complaint,
    read_contract,
    read_line_item,
    read_member,
    read_analysis,
    read_supplier,
    read_usage,
    record_usage,
    set_clock,
    setup_active_contract,
    setup_authorised_member,
    setup_substantiated_complaint,
)

AUSTIN = dict(
    legal_name="City of Austin",
    state_code="TX",
    member_category="CITY",
    annual_spend_ceiling_cents=5000000,
    governing_body_resolution_number="RES-2026-208",
)


def _quote_world(api):
    """An ACTIVE contract whose member sits on exactly the 5000000-cent tier threshold."""
    world = setup_active_contract(api, lines=(DISPENSER_LINE, ADJUSTMENT_LINE))
    member, analysis = setup_authorised_member(api, world)
    prime_committed_spend(api, world, member, analysis, PRIMER_QTY_FOR_5000000)
    world["member"] = read_member(api, member["id"])
    world["analysis"] = analysis
    world["line"] = world["lines"][SKU_DISPENSER]
    return world


def _quote(api, world, quantity=10):
    return api.get_price_quote(
        world["contract"]["id"],
        make_member_headers(world["member"]["id"]),
        price_quote_params(world["line"]["id"], world["member"]["id"], quantity=quantity),
    )


def _debar(api, supplier_id):
    return validate_success(
        api.supplier_qualification(
            supplier_id, {"action": "DEBAR", "note": "federal exclusion list"}, ADMIN_REVIEW
        )
    )


def _debar_world(api):
    """An ACTIVE contract with one authorised member and one complaint under investigation."""
    world = setup_active_contract(api)
    member, analysis = setup_authorised_member(api, world)
    complaint = file_complaint(
        api,
        world["contract"]["id"],
        member["id"],
        severity="CRITICAL",
        category="PRODUCT_QUALITY",
    )
    open_investigation(api, complaint["id"], ADMIN_INVESTIGATOR)
    world["member"] = member
    world["analysis"] = analysis
    world["complaint"] = complaint
    world["line"] = world["lines"][SKU_DISPENSER]
    return world


def _two_member_world(api):
    """One contract, two ACTIVE members, and one order already placed by the second."""
    world = setup_active_contract(api)
    riverside, riverside_analysis = setup_authorised_member(api, world)
    austin, austin_analysis = setup_authorised_member(api, world, **AUSTIN)
    world["line"] = world["lines"][SKU_DISPENSER]
    world["riverside"] = riverside
    world["riverside_analysis"] = riverside_analysis
    world["austin"] = austin
    world["austin_usage"] = record_usage(
        api,
        world["contract"]["id"],
        austin["id"],
        world["line"]["id"],
        austin_analysis["id"],
    )
    return world


def _appeal_world(api):
    """A MAJOR complaint substantiated at 2026-09-01 on an ACTIVE contract."""
    world = setup_active_contract(api)
    member, _ = setup_authorised_member(api, world)
    world["member"] = member
    world["complaint"] = setup_substantiated_complaint(
        api,
        world["contract"]["id"],
        member["id"],
        severity="MAJOR",
        investigator=ADMIN_INVESTIGATOR,
        adjudicator=ADMIN_ADJUDICATOR,
    )
    return world


def _close(api, complaint_id):
    return api.complaint_decision(complaint_id, {"action": "CLOSE"}, ADMIN_ADJUDICATOR)


class TestPriceQuoteWaterfall:
    def test_01_the_quote_runs_the_whole_waterfall_on_the_primed_basis(self, api):
        """PRD §3.6: "That read-only computation takes a `line_item_id`, a `member_agency_id`, a
        `quantity` and optional `add_on_codes`, runs exactly the same steps one through eight
        against the member's *current* `committed_spend_cents`, creates no row and moves no
        counter, and returns `line_item_id`, `member_agency_id`, `spend_basis_cents`,
        `discount_tier_index`, `total_discount_pct`, `net_unit_price_cents`, `subtotal_cents`,
        `add_on_charges_cents`, `chargeable_base_cents`, `effective_fee_rate_bps`,
        `admin_fee_cents` and `total_cents`, plus two diagnostic booleans: `floor_binding`, true
        when the price floor rather than the discounted price determined `net_unit_price_cents`,
        and `aggregate_add_on_cap_binding`, true when the fifteen-percent aggregate ceiling
        rather than the per-code sum determined `add_on_charges_cents`." PRD §3.6:
        "`effective_fee_rate_bps` is the contract's `admin_fee_rate_bps` multiplied by one minus
        the applicable rebate fraction, rounded half up to whole basis points."

        Design: Corner/Endpoints/price_quote_previews_the_whole_pricing_waterfall_without_mutating_anything
        """
        world = _quote_world(api)
        assert_cents(world["member"]["committed_spend_cents"], 5000000, "committed_spend_cents")

        response = _quote(api, world)

        quote = validate_success(response)
        assert response.json()["response_type"] == "object"
        assert quote["line_item_id"] == world["line"]["id"]
        assert quote["member_agency_id"] == world["member"]["id"]
        assert_cents(quote["spend_basis_cents"], 5000000, "spend_basis_cents")
        assert quote["discount_tier_index"] == 1
        assert_fraction(quote["total_discount_pct"], 0.0500, "total_discount_pct")
        assert_cents(quote["net_unit_price_cents"], 11875, "net_unit_price_cents")
        assert_cents(quote["subtotal_cents"], 118750, "subtotal_cents")
        assert_cents(quote["add_on_charges_cents"], 0, "add_on_charges_cents")
        assert_cents(quote["chargeable_base_cents"], 118750, "chargeable_base_cents")
        assert quote["effective_fee_rate_bps"] == 180
        assert_cents(quote["admin_fee_cents"], 2138, "admin_fee_cents")
        assert_cents(quote["total_cents"], 120888, "total_cents")
        assert quote["floor_binding"] is False
        assert quote["aggregate_add_on_cap_binding"] is False

    def test_02_the_quote_creates_no_row_and_moves_no_counter(self, api):
        """PRD §3.6: "Members and administrators can also price a hypothetical order without
        recording it." PRD §3.6: "Only now is `total_cents` added to the member's
        `committed_spend_cents`, and `chargeable_base_cents` added to the contract's
        `usage_chargeable_cents_total`."

        Design: Corner/Endpoints/price_quote_previews_the_whole_pricing_waterfall_without_mutating_anything
        """
        world = _quote_world(api)
        before = read_contract(api, world["contract"]["id"])
        _, meta_before = validate_paginated(
            api.list_contract_usages(ADMIN_REVIEW, {"member_agency_id": world["member"]["id"]})
        )

        validate_success(_quote(api, world))
        validate_success(_quote(api, world, quantity=25))

        member = read_member(api, world["member"]["id"])
        assert_cents(member["committed_spend_cents"], 5000000, "committed_spend_cents")
        assert member["version"] == world["member"]["version"]
        rows, meta_after = validate_paginated(
            api.list_contract_usages(ADMIN_REVIEW, {"member_agency_id": world["member"]["id"]})
        )
        assert meta_before["total_count"] == 1
        assert meta_after["total_count"] == 1
        assert len(rows) == 1
        contract = read_contract(api, world["contract"]["id"])
        assert_cents(
            contract["usage_chargeable_cents_total"],
            before["usage_chargeable_cents_total"],
            "usage_chargeable_cents_total",
        )
        assert contract["version"] == before["version"]

    def test_03_the_recorded_order_reproduces_the_quote_figure_for_figure(self, api):
        """PRD §3.6: "Multiply the line's `base_unit_price_cents` by one minus
        `total_discount_pct` and round half up to a whole cent." PRD §3.6: "`admin_fee_cents` is
        `chargeable_base_cents` multiplied by `effective_fee_rate_bps` and divided by 10,000,
        rounded half up to a whole cent."

        Design: Corner/Endpoints/price_quote_previews_the_whole_pricing_waterfall_without_mutating_anything
        """
        world = _quote_world(api)
        quote = validate_success(_quote(api, world))

        usage = record_usage(
            api,
            world["contract"]["id"],
            world["member"]["id"],
            world["line"]["id"],
            world["analysis"]["id"],
            quantity=10,
        )

        assert_cents(usage["spend_basis_cents"], quote["spend_basis_cents"], "spend_basis_cents")
        assert usage["discount_tier_index"] == 1
        assert_cents(usage["net_unit_price_cents"], 11875, "net_unit_price_cents")
        assert_cents(usage["subtotal_cents"], 118750, "subtotal_cents")
        assert_cents(usage["chargeable_base_cents"], 118750, "chargeable_base_cents")
        assert usage["effective_fee_rate_bps"] == 180
        assert_cents(usage["admin_fee_cents"], 2138, "admin_fee_cents")
        assert_cents(usage["total_cents"], 120888, "total_cents")
        member = read_member(api, world["member"]["id"])
        assert_cents(member["committed_spend_cents"], 5120888, "committed_spend_cents")


class TestDebarmentActionEndpoint:
    def test_04_debarment_terminates_the_contract_its_lines_and_its_opinions(self, api):
        """PRD §3.1: "`DEBAR` is reachable from either `QUALIFIED` or `SUSPENDED` and cascades
        harder: every `MasterContract` of the supplier whose `status` is `PENDING_EXECUTION`,
        `ACTIVE` or `SUSPENDED` becomes `TERMINATED`, and each of those terminations in turn
        withdraws that contract's line items and voids that contract's `DETERMINED` opinions with
        `voided_reason` `CONTRACT_TERMINATED`."

        Design: Corner/Endpoints/debarment_is_an_action_endpoint_that_terminates_downstream_and_then_blocks_adjudication
        """
        world = _debar_world(api)

        debarred = _debar(api, world["supplier_a"]["id"])

        assert debarred["qualification_status"] == "DEBARRED"
        assert read_contract(api, world["contract"]["id"])["status"] == "TERMINATED"
        assert read_line_item(api, world["line"]["id"])["status"] == "WITHDRAWN"
        analysis = read_analysis(api, world["analysis"]["id"])
        assert analysis["status"] == "VOIDED"
        assert analysis["voided_reason"] == "CONTRACT_TERMINATED"

    def test_05_a_debarred_supplier_can_no_longer_absorb_a_substantiation(self, api):
        """PRD §2.9: "The supplier who would absorb a performance deduction is not `DEBARRED` —
        `ERR_SUPPLIER_DEBARRED`, 409, on `POST /coop/complaints/{id}/decision`." PRD §3.9:
        "First, the severity points of every complaint on any of this supplier's contracts whose
        `status` is `SUBSTANTIATED`, `APPEALED` or `CLOSED` and whose `points_reversed` is false —
        complaints in `INTAKE` or `UNDER_INVESTIGATION`, complaints that were `DISMISSED`, and
        complaints that were `OVERTURNED` all contribute nothing."

        Design: Corner/Endpoints/debarment_is_an_action_endpoint_that_terminates_downstream_and_then_blocks_adjudication
        """
        world = _debar_world(api)
        _debar(api, world["supplier_a"]["id"])

        refused = api.complaint_decision(
            world["complaint"]["id"], {"action": "SUBSTANTIATE"}, ADMIN_ADJUDICATOR
        )

        validate_error(refused, ApiErrorId.ERR_SUPPLIER_DEBARRED, 409)
        complaint = read_complaint(api, world["complaint"]["id"])
        assert complaint["status"] == "UNDER_INVESTIGATION"
        assert complaint["investigator_user_id"] == ADMIN_INVESTIGATOR_ID
        assert complaint["adjudicator_user_id"] is None
        assert complaint["deduction_points"] is None
        assert complaint["substantiated_at"] is None
        supplier = read_supplier(api, world["supplier_a"]["id"])
        assert_score(supplier["deduction_points_total"], 0.00, "deduction_points_total")
        assert_score(supplier["performance_score"], 100.00, "performance_score")
        assert supplier["substantiated_complaint_count"] == 0


class TestComplaintCrossReference:
    def test_06_the_cited_order_must_belong_to_the_complaining_member(self, api):
        """PRD §3.9: "It may optionally cite one of its own orders through `related_usage_id`,
        which when present must belong to the same `contract_id` *and* the same
        `member_agency_id` as the complaint, a mismatch being `ERR_USAGE_PAIR_MISMATCH`."

        Design: Corner/Endpoints/complaint_usage_cross_reference_must_belong_to_the_complaining_member
        """
        world = _two_member_world(api)
        riverside_id = world["riverside"]["id"]

        refused = api.create_complaint(
            complaint_payload(
                world["contract"]["id"],
                riverside_id,
                related_usage_id=world["austin_usage"]["id"],
            ),
            make_member_headers(riverside_id),
        )

        validate_error(refused, ApiErrorId.ERR_USAGE_PAIR_MISMATCH, 422)
        _, meta = validate_paginated(
            api.list_complaints(ADMIN_REVIEW, {"contract_id": world["contract"]["id"]})
        )
        assert meta["total_count"] == 0

    def test_07_its_own_order_attaches_and_the_filter_finds_it(self, api):
        """PRD §3.9: "A new complaint starts in `status` `INTAKE` with `points_reversed` false and
        `deduction_points`, `investigator_user_id`, `adjudicator_user_id`, `substantiated_at`,
        `appeal_filed_at` and `appeal_deadline_at` all null." PRD §2.3: "Most list endpoints also
        accept optional equality filters drawn from the fields of the entity they return, and the
        filters compose."

        Design: Corner/Endpoints/complaint_usage_cross_reference_must_belong_to_the_complaining_member
        """
        world = _two_member_world(api)
        riverside_id = world["riverside"]["id"]
        own_usage = record_usage(
            api,
            world["contract"]["id"],
            riverside_id,
            world["line"]["id"],
            world["riverside_analysis"]["id"],
        )

        created = validate_success(
            api.create_complaint(
                complaint_payload(
                    world["contract"]["id"], riverside_id, related_usage_id=own_usage["id"]
                ),
                make_member_headers(riverside_id),
            ),
            201,
        )

        assert created["status"] == "INTAKE"
        assert created["related_usage_id"] == own_usage["id"]
        assert created["member_agency_id"] == riverside_id
        assert created["deduction_points"] is None
        assert created["points_reversed"] is False
        rows, meta = validate_paginated(
            api.list_complaints(ADMIN_REVIEW, {"related_usage_id": own_usage["id"]})
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [created["id"]]
        assert read_usage(api, world["austin_usage"]["id"])["member_agency_id"] == (
            world["austin"]["id"]
        )


class TestAppealWindowComplement:
    def test_08_substantiation_sets_the_fourteen_day_deadline_and_charges_the_points(self, api):
        """PRD §3.9: "`SUBSTANTIATE` moves `UNDER_INVESTIGATION → SUBSTANTIATED` and additionally
        requires the contract's supplier not to be `DEBARRED` (`ERR_SUPPLIER_DEBARRED`); it
        stamps `substantiated_at` with the current logical instant, sets `appeal_deadline_at` to
        fourteen days after `substantiated_at`, and writes `deduction_points` from the asserted
        `severity` — 2.50 points for `MINOR`, 7.50 for `MAJOR`, and 20.00 for `CRITICAL`."

        Design: Corner/Endpoints/closing_a_substantiated_complaint_is_conditional_on_the_appeal_window_having_lapsed
        """
        world = _appeal_world(api)

        complaint = read_complaint(api, world["complaint"]["id"])

        assert complaint["status"] == "SUBSTANTIATED"
        assert complaint["adjudicator_user_id"] == ADMIN_ADJUDICATOR_ID
        assert_instant(complaint["substantiated_at"], CLOCK_TERM_START, "substantiated_at")
        assert_instant(complaint["appeal_deadline_at"], CLOCK_SEP_15, "appeal_deadline_at")
        assert_score(complaint["deduction_points"], 7.50, "deduction_points")
        supplier = read_supplier(api, world["supplier_a"]["id"])
        assert_score(supplier["deduction_points_total"], 7.50, "deduction_points_total")
        assert_score(supplier["performance_score"], 92.50, "performance_score")
        assert supplier["performance_tier"] == "PREFERRED"

    def test_09_closing_is_refused_up_to_and_including_the_deadline_instant(self, api):
        """PRD §3.9: "Finally, `CLOSE` moves `SUBSTANTIATED → CLOSED` when no appeal was ever
        filed." PRD §3.9: "It requires the logical clock to be strictly past
        `appeal_deadline_at`; closing while the window is still open is `ERR_APPEAL_WINDOW_OPEN`."

        Design: Corner/Endpoints/closing_a_substantiated_complaint_is_conditional_on_the_appeal_window_having_lapsed
        """
        world = _appeal_world(api)
        complaint_id = world["complaint"]["id"]

        validate_error(_close(api, complaint_id), ApiErrorId.ERR_APPEAL_WINDOW_OPEN, 409)
        set_clock(api, CLOCK_SEP_15)
        validate_error(_close(api, complaint_id), ApiErrorId.ERR_APPEAL_WINDOW_OPEN, 409)

        complaint = read_complaint(api, complaint_id)
        assert complaint["status"] == "SUBSTANTIATED"
        assert complaint["appeal_filed_at"] is None
        assert_score(complaint["deduction_points"], 7.50, "deduction_points")
        assert complaint["points_reversed"] is False

    def test_10_one_instant_later_the_appeal_is_shut_and_the_close_lands(self, api):
        """PRD §3.9: "It requires the acting `X-User-ID` to be the contract's `supplier_id` and
        requires the logical clock to be at or before `appeal_deadline_at` — the instant exactly
        equal to the deadline is still inside the window, and anything later is
        `ERR_APPEAL_WINDOW_CLOSED`." PRD §3.9: "The deduction points then stay charged
        permanently."

        Design: Corner/Endpoints/closing_a_substantiated_complaint_is_conditional_on_the_appeal_window_having_lapsed
        """
        world = _appeal_world(api)
        complaint_id = world["complaint"]["id"]
        set_clock(api, CLOCK_SEP_16)

        refused = api.complaint_appeal(
            complaint_id,
            {"action": "FILE_APPEAL"},
            make_supplier_headers(world["supplier_a"]["id"]),
        )
        closed = validate_success(_close(api, complaint_id))

        validate_error(refused, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED, 409)
        assert closed["status"] == "CLOSED"
        assert closed["appeal_filed_at"] is None
        assert closed["points_reversed"] is False
        assert_score(closed["deduction_points"], 7.50, "deduction_points")
        supplier = read_supplier(api, world["supplier_a"]["id"])
        assert_score(supplier["deduction_points_total"], 7.50, "deduction_points_total")
        assert_score(supplier["performance_score"], 92.50, "performance_score")
        assert supplier["performance_tier"] == "PREFERRED"
        assert supplier["substantiated_complaint_count"] == 1


class TestEnvelopeShapes:
    def test_11_the_object_read_and_the_array_read_share_one_meta_block(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request
        that starts with `req_`." PRD §2.2: "Pagination-related fields in `meta` (`limit`,
        `offset`, `total_count`, `has_more`) are included for list endpoints." PRD §2.3: "The
        `meta` object of a list response carries `limit`, `offset`, `total_count` and `has_more`."

        Design: Corner/Endpoints/every_response_shape_carries_the_same_envelope_and_meta_block
        """
        world = setup_active_contract(api)

        one = api.get_master_contract(world["contract"]["id"], ADMIN_REVIEW)
        many = api.list_master_contracts(ADMIN_REVIEW)

        contract = validate_success(one)
        assert one.json()["response_type"] == "object"
        assert contract["contract_number"] == "COOP-MC-2026-001"
        assert_envelope_meta(one.json())
        rows, meta = validate_paginated(many)
        assert many.json()["response_type"] == "array"
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert [row["id"] for row in rows] == [world["contract"]["id"]]
        assert_envelope_meta(many.json())

    def test_12_the_error_read_replaces_the_payload_with_exactly_two_fields(self, api):
        """PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and
        `api_request_timestamp`." PRD §2.2: "The `error_id` is a unique, machine-readable string
        that identifies the specific error." PRD §2.2: "The `message` provides a human-readable
        explanation of what went wrong."

        Design: Corner/Endpoints/every_response_shape_carries_the_same_envelope_and_meta_block
        """
        setup_active_contract(api)

        missing = api.get_master_contract(NON_EXISTENT_UUID, ADMIN_REVIEW)

        validate_error(missing, ApiErrorId.ERR_CONTRACT_NOT_FOUND, 404)
        body = missing.json()
        assert body["response_type"] == "error"
        assert_error_data_shape(body["data"])
        assert body["data"]["error_id"] == ApiErrorId.ERR_CONTRACT_NOT_FOUND.value
        assert isinstance(body["data"]["message"], str) and body["data"]["message"]
        assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}
        assert_envelope_meta(body)
