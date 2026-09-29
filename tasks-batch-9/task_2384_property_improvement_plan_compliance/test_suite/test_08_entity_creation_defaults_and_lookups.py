"""Creation defaults, single-resource reads, paging and the not-found vocabulary."""

from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    BRAND_MANAGER_HEADERS,
    bootstrap_portfolio,
    is_iso8601_timestamp,
    is_valid_uuid,
    issue_plan,
    item_payload,
    ledger_entries,
    list_rows,
    property_payload,
    read_franchisee,
    read_item,
    read_plan,
    read_property,
    register_franchisee,
    scope_plan,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

PROBE_ID = "00000000-0000-0000-0000-0000000000ff"

NOT_FOUND_PROBES = (
    ("get_franchisee_account", ApiErrorId.ERR_FRANCHISEE_NOT_FOUND),
    ("get_property", ApiErrorId.ERR_PROPERTY_NOT_FOUND),
    ("get_plan", ApiErrorId.ERR_PLAN_NOT_FOUND),
    ("get_item", ApiErrorId.ERR_ITEM_NOT_FOUND),
    ("get_extension_request", ApiErrorId.ERR_EXTENSION_REQUEST_NOT_FOUND),
    ("get_capital_budget", ApiErrorId.ERR_BUDGET_NOT_FOUND),
    ("get_reserve_draw", ApiErrorId.ERR_DRAW_NOT_FOUND),
    ("get_renovation_phase", ApiErrorId.ERR_PHASE_NOT_FOUND),
    ("get_contractor", ApiErrorId.ERR_CONTRACTOR_NOT_FOUND),
    ("get_contractor_booking", ApiErrorId.ERR_BOOKING_NOT_FOUND),
    ("get_inspection", ApiErrorId.ERR_INSPECTION_NOT_FOUND),
    ("get_punch_list_item", ApiErrorId.ERR_PUNCH_NOT_FOUND),
    ("get_dispute", ApiErrorId.ERR_DISPUTE_NOT_FOUND),
    ("get_default_notice", ApiErrorId.ERR_NOTICE_NOT_FOUND),
    ("get_compliance_ledger_entry", ApiErrorId.ERR_LEDGER_ENTRY_NOT_FOUND),
)


class TestPropertyRegistration:
    def test_the_create_pins_the_reserve_anchor_and_the_opening_posture(self, api, brand_manager):
        """"`initial_reserve_balance_cents` is set to the supplied `reserve_balance_cents` and
        becomes the immutable anchor of the reserve-corpus invariant; `reserve_contributed_total_cents`
        starts at 0; `rooms_out_of_service_current` starts at 0; `franchise_agreement_status` starts
        at `ACTIVE`; `compliance_risk_score` starts at 100 and `compliance_posture` at `COMPLIANT`;
        `open_plan_count` starts at 0."

        Design: Corner/entities/property_create_pins_reserve_baseline_and_bumps_portfolio_count
        """
        franchisee = register_franchisee(api, "Ashgrove Lodging LLC", "ops@ashgrovel.example")

        prop = validate_success(
            api.create_property(
                property_payload(franchisee["id"], name="Ashgrove Downtown"), brand_manager
            ),
            expected_status=201,
        )

        assert prop["initial_reserve_balance_cents"] == 50000000, (
            f"the anchor should pin the supplied reserve balance, got {prop!r}"
        )
        assert prop["reserve_balance_cents"] == 50000000, f"unexpected balance in {prop!r}"
        assert prop["reserve_contributed_total_cents"] == 0, f"unexpected credit in {prop!r}"
        assert prop["rooms_out_of_service_current"] == 0, f"unexpected keys down in {prop!r}"
        assert prop["franchise_agreement_status"] == "ACTIVE", f"unexpected standing {prop!r}"
        assert prop["compliance_risk_score"] == 100, f"unexpected score in {prop!r}"
        assert prop["compliance_posture"] == "COMPLIANT", f"unexpected posture in {prop!r}"
        assert prop["open_plan_count"] == 0, f"a new property has no open plans, got {prop!r}"

    def test_the_create_returns_the_full_envelope_and_bumps_the_portfolio_count(
        self, api, brand_manager
    ):
        """"Every resource in the system carries an `id`: a server-minted UUID with no type prefix,
        generated at creation and never reassigned." "`version`, an integer that starts at 1 on
        creation". "The owning franchisee's `portfolio_property_count` increments by one." "The
        account is created with `portfolio_property_count` at 0 and `standing` at `GOOD`."

        Design: Corner/entities/property_create_pins_reserve_baseline_and_bumps_portfolio_count
        """
        franchisee = register_franchisee(api, "Ashgrove Lodging LLC", "ops@ashgrovel.example")
        assert franchisee["portfolio_property_count"] == 0, (
            f"a fresh account owns nothing yet, got {franchisee!r}"
        )

        response = api.create_property(
            property_payload(franchisee["id"], name="Ashgrove Downtown"), brand_manager
        )
        prop = validate_success(response, expected_status=201)

        body = response.json()
        assert body["response_type"] == "object", f"unexpected envelope {body['response_type']!r}"
        assert is_valid_uuid(prop["id"]), f"the minted id should be a bare UUID, got {prop['id']!r}"
        assert is_iso8601_timestamp(prop["created_at"]), f"unexpected created_at in {prop!r}"
        assert prop["version"] == 1, f"a created row opens at version 1, got {prop!r}"

        parent = read_franchisee(api, franchisee["id"])
        assert parent["portfolio_property_count"] == 1, f"unexpected roll-up in {parent!r}"
        assert parent["standing"] == "GOOD", f"unexpected standing in {parent!r}"


class TestDraftPlanReads:
    def test_a_draft_plan_reads_back_its_aggregates_with_issuance_fields_still_null(self, api):
        """"The plan is born with `status` at `DRAFT` and `dispute_state` at `NONE`, with
        `issued_by_user_id` and `issued_at` null, with all three category deadline dates null, and
        with every cost aggregate at 0." "with `deadline_date`, `priority_rank` and `is_overdue`
        left null, null and false respectively for as long as the plan remains `DRAFT`."
        "Creating an item recomputes the plan's `scope_item_count` and both cost totals and
        increments the plan's `version`" — the funding requirement is not among them, and a new
        item is created "with `item_funding_cents` at 0", so the requirement is still 0 here.
        The owner-claimed variant "substitutes `owner_claimed_cost_cents` for any item on which a
        dispute has been filed and falls back to `brand_estimated_cost_cents` for the rest", and
        "the two variants are identical until the first dispute exists".

        Design: Corner/entities/plan_get_by_id_returns_stored_scope_aggregates
        """
        portfolio = bootstrap_portfolio(
            api, "Brightwater Hotels LLC", "ops@brightwaterh.example", name="Brightwater Quay"
        )
        scenario = scope_plan(
            api,
            portfolio,
            [
                {
                    "key": "lobby",
                    "category": "GUEST_FACING",
                    "standards_reference": "GF-2.4.1",
                    "brand_estimated_cost_cents": 2500000,
                }
            ],
            trigger_type="RELICENSING",
        )

        plan = read_plan(api, scenario.plan_id)
        item = read_item(api, scenario.item_id("lobby"))

        assert plan["id"] == scenario.plan_id, f"unexpected plan read back: {plan!r}"
        assert plan["property_id"] == portfolio.property_id, f"unexpected parent in {plan!r}"
        assert plan["status"] == "DRAFT", f"unexpected lifecycle state in {plan!r}"
        assert plan["dispute_state"] == "NONE", f"unexpected dispute dimension in {plan!r}"
        assert plan["scope_item_count"] == 1, f"unexpected scope count in {plan!r}"
        assert plan["brand_scoped_total_cents"] == 2500000, f"unexpected brand total in {plan!r}"
        assert plan["owner_claimed_total_cents"] == 2500000, f"unexpected owner total in {plan!r}"
        assert plan["funding_requirement_cents"] == 0, f"unexpected requirement in {plan!r}"
        assert plan["life_safety_deadline_date"] is None, f"unexpected deadline in {plan!r}"
        assert plan["guest_facing_deadline_date"] is None, f"unexpected deadline in {plan!r}"
        assert plan["back_of_house_deadline_date"] is None, f"unexpected deadline in {plan!r}"
        assert plan["issued_by_user_id"] is None, f"unexpected issuer in {plan!r}"
        assert plan["issued_at"] is None, f"unexpected issuance instant in {plan!r}"
        assert item["deadline_date"] is None, f"a draft item has no deadline, got {item!r}"
        assert item["priority_rank"] is None, f"a draft item has no rank, got {item!r}"

    def test_the_item_list_pages_at_the_requested_limit(self, api):
        """"The `limit` parameter caps the number of rows returned; it defaults to 10 when omitted,
        may not be smaller than 1, and may not be larger than 100." "List responses carry four
        pagination fields inside the envelope's `meta` object: `limit`, `offset`, `total_count`, and
        `has_more`."

        Design: Corner/entities/items_list_paginates_with_total_count_and_has_more
        """
        portfolio = bootstrap_portfolio(
            api, "Cedarpoint Inns LLC", "ops@cedarpointi.example", name="Cedarpoint Plaza"
        )
        scenario = scope_plan(
            api,
            portfolio,
            [
                {
                    "key": f"boh{index}",
                    "category": "BACK_OF_HOUSE",
                    "standards_reference": f"BOH-1.1.{index}",
                    "brand_estimated_cost_cents": 100000,
                }
                for index in (1, 2, 3)
            ],
        )

        first_rows, first_meta = list_rows(
            api, "list_items", plan_id=scenario.plan_id, limit=2, offset=0
        )
        second_rows, second_meta = list_rows(
            api, "list_items", plan_id=scenario.plan_id, limit=2, offset=2
        )

        assert (first_meta["limit"], first_meta["offset"]) == (2, 0), f"unexpected {first_meta!r}"
        assert first_meta["total_count"] == 3, f"unexpected total in {first_meta!r}"
        assert first_meta["has_more"] is True, f"a third row remains, got {first_meta!r}"
        assert len(first_rows) == 2, f"the first page should hold two rows, got {len(first_rows)}"
        assert (second_meta["limit"], second_meta["offset"]) == (2, 2), f"got {second_meta!r}"
        assert second_meta["total_count"] == 3, f"unexpected total in {second_meta!r}"
        assert second_meta["has_more"] is False, f"the page is the last one, got {second_meta!r}"
        assert len(second_rows) == 1, f"the second page should hold one row, got {second_rows!r}"

        ids = [row["id"] for row in first_rows + second_rows]
        assert len(set(ids)) == 3, f"the two pages should be disjoint, got {ids!r}"
        assert all(row["plan_id"] == scenario.plan_id for row in first_rows + second_rows), (
            "every row should belong to the filtered plan"
        )
        plan = read_plan(api, scenario.plan_id)
        assert plan["brand_scoped_total_cents"] == 300000, f"unexpected total in {plan!r}"
        # "Creating an item recomputes the plan's `scope_item_count` and both cost totals" — the
        # funding requirement is not in that list, and every new item carries
        # "`item_funding_cents` at 0", so a draft plan's requirement is still 0.
        assert plan["funding_requirement_cents"] == 0, f"unexpected requirement in {plan!r}"


class TestNotFoundVocabulary:
    @pytest.mark.parametrize("method_name,error_id", NOT_FOUND_PROBES)
    def test_each_collection_answers_with_its_own_not_found_code(
        self, api, brand_manager, method_name, error_id
    ):
        """"That `{id}` is resolved before any request-body field is read, and a miss yields the
        collection's own not-found code — `ERR_FRANCHISEE_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`,
        `ERR_PLAN_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, `ERR_EXTENSION_REQUEST_NOT_FOUND`,
        `ERR_BUDGET_NOT_FOUND`, `ERR_DRAW_NOT_FOUND`, `ERR_PHASE_NOT_FOUND`,
        `ERR_CONTRACTOR_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`,
        `ERR_PUNCH_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND` or
        `ERR_LEDGER_ENTRY_NOT_FOUND`, each 404."

        Design: Corner/entities/unknown_ids_return_the_collection_specific_not_found_error
        """
        response = getattr(api, method_name)(PROBE_ID, brand_manager)

        validate_error(response, error_id, 404)
        assert response.json()["response_type"] == "error", (
            f"a 404 must still carry the error envelope, got {response.text}"
        )

    def test_a_list_filter_that_resolves_to_nothing_is_an_empty_page_not_a_miss(
        self, api, brand_manager
    ):
        """"Filter parameters on list endpoints behave differently from path identifiers: a filter
        value that resolves to nothing — a `plan_id` that does not exist, a `status` no row
        currently holds — yields an empty page with `total_count` of 0, never a 404."

        Design: Corner/entities/unknown_ids_return_the_collection_specific_not_found_error
        """
        rows, meta = validate_paginated(
            api.list_plans(brand_manager, {"property_id": PROBE_ID, "limit": 10})
        )

        assert rows == [], f"an unmatched filter yields no rows, got {rows!r}"
        assert meta["total_count"] == 0, f"unexpected total in {meta!r}"
        assert meta["has_more"] is False, f"an empty page has no successor, got {meta!r}"


class TestRequestShapeOnCreate:
    def test_a_plan_without_a_standards_edition_is_refused(self, api, brand_manager):
        """"A `BrandManager` scopes a plan by naming the `property_id` it is issued against, a
        `trigger_type` drawn from `POST_INSPECTION`, `TRANSACTION_CHANGE_OF_OWNERSHIP` and
        `RELICENSING`, and a `standards_edition` of 1 to 40 characters pinning the brand standards
        manual edition against which the plan's clause references are read." "Required fields
        present and non-null, enum-typed inputs drawn from their declared sets, numeric bounds
        respected, pagination parameters in range — all `ERR_VALIDATION` (422)".

        Design: Corner/entities/plan_create_missing_standards_edition_is_rejected
        """
        portfolio = bootstrap_portfolio(
            api, "Dovetail Hotels LLC", "ops@dovetailh.example", name="Dovetail Market Street"
        )

        response = api.create_plan(
            {"property_id": portfolio.property_id, "trigger_type": "POST_INSPECTION"},
            brand_manager,
        )

        validate_error(response, ApiErrorId.ERR_VALIDATION, 422)
        _rows, meta = list_rows(api, "list_plans", property_id=portfolio.property_id)
        assert meta["total_count"] == 0, f"the refused plan must not persist, got {meta!r}"
        assert read_property(api, portfolio.property_id)["open_plan_count"] == 0, (
            "a refused scope leaves the property's open-plan roll-up alone"
        )

    def test_enum_closure_and_numeric_bounds_are_all_refused_the_same_way(self, api, brand_manager):
        """"a `room_count` of at least 1 key, an `adr_baseline_cents` of at least 0 giving the
        baseline average daily rate in cents, an `occupancy_baseline_pct` between 0 and 1 inclusive
        expressed as a decimal fraction with exactly 2 decimal places". "Any numeric bound breached
        here yields `ERR_VALIDATION` (422)." "A `limit` outside the range 1 through 100, or a
        negative `offset`, is rejected with `ERR_VALIDATION` (422)."

        Design: Corner/entities/enum_and_numeric_input_bounds_are_rejected
        """
        portfolio = bootstrap_portfolio(
            api, "Ivyleaf Lodging LLC", "ops@ivyleafl.example", name="Ivyleaf Station"
        )

        validate_error(
            api.create_plan(
                {
                    "property_id": portfolio.property_id,
                    "trigger_type": "POST_INSPECTIONS",
                    "standards_edition": "2026.1",
                },
                brand_manager,
            ),
            ApiErrorId.ERR_VALIDATION,
            422,
        )
        validate_error(
            api.create_property(
                property_payload(
                    portfolio.franchisee_id, name="Ivyleaf Overflow", occupancy_baseline_pct=1.5
                ),
                brand_manager,
            ),
            ApiErrorId.ERR_VALIDATION,
            422,
        )
        validate_error(
            api.create_property(
                property_payload(portfolio.franchisee_id, name="Ivyleaf Annex", room_count=0),
                brand_manager,
            ),
            ApiErrorId.ERR_VALIDATION,
            422,
        )
        validate_error(
            api.list_plans(brand_manager, {"limit": 101}), ApiErrorId.ERR_VALIDATION, 422
        )

        parent = read_franchisee(api, portfolio.franchisee_id)
        assert parent["portfolio_property_count"] == 1, (
            f"no rejected property may persist, got {parent!r}"
        )
        _rows, meta = list_rows(api, "list_plans", property_id=portfolio.property_id)
        assert meta["total_count"] == 0, f"no rejected plan may persist, got {meta!r}"

    def test_declared_defaults_are_applied_rather_than_invented(self, api, brand_manager):
        """"an optional `brand_approved` flag recording whether the brand has vetted the firm
        (default `false`), and an optional `max_concurrent_bookings` of at least 1 stating how many
        booked engagements the firm may have occupying any single instant (default 1)." "A new item
        is created with `status` `SCOPED`, with `approved_cost_cents` equal to its
        `brand_estimated_cost_cents`, with `owner_claimed_cost_cents` null, with
        `extension_days_granted` at 0, with `item_funding_cents` at 0".

        Design: Corner/entities/contractor_and_item_creates_apply_declared_defaults
        """
        portfolio = bootstrap_portfolio(
            api, "Elmcrest Lodging LLC", "ops@elmcrestl.example", name="Elmcrest Terrace"
        )
        scenario = scope_plan(api, portfolio, [])

        contractor = validate_success(
            api.create_contractor({"name": "Fernwood Millwork", "trade": "FF_AND_E"}, brand_manager),
            expected_status=201,
        )
        item = validate_success(
            api.create_item(
                {
                    "plan_id": scenario.plan_id,
                    "category": "BACK_OF_HOUSE",
                    "standards_reference": "BOH-3.2.1",
                    "brand_estimated_cost_cents": 400000,
                    "room_impacting": False,
                },
                brand_manager,
            ),
            expected_status=201,
        )

        assert contractor["brand_approved"] is False, f"unexpected vetting flag {contractor!r}"
        assert contractor["max_concurrent_bookings"] == 1, f"unexpected capacity {contractor!r}"

        stored = read_item(api, item["id"])
        assert stored["rooms_affected_count"] == 0, f"unexpected key impact in {stored!r}"
        assert stored["status"] == "SCOPED", f"unexpected item state in {stored!r}"
        assert stored["extension_days_granted"] == 0, f"unexpected granted days in {stored!r}"
        assert stored["is_overdue"] is False, f"a fresh item is never overdue, got {stored!r}"
        assert stored["owner_claimed_cost_cents"] is None, f"unexpected owner claim {stored!r}"
        assert stored["approved_cost_cents"] == 400000, f"unexpected approved cost {stored!r}"
        assert stored["item_funding_cents"] == 0, f"unexpected funding in {stored!r}"


class TestIssuanceDerivations:
    def test_issuance_derives_the_deadline_rank_and_funding_of_every_item(self, api):
        """"It then sets `deadline_date` on every item of the plan to the deadline of that item's
        own category — life-safety items to the 90-day date, guest-facing items to the 270-day date,
        back-of-house items to the 450-day date — plus that item's `extension_days_granted`, which
        is 0 at this point." "Candidates are ordered by three keys in strict succession: first by
        category, with life safety ordering before guest facing and guest facing before back of
        house".

        Design: Corner/entities/issuance_derives_item_deadlines_ranks_and_funding
        """
        portfolio = bootstrap_portfolio(
            api, "Foxglove Hotels LLC", "ops@foxgloveh.example", name="Foxglove Garden District"
        )
        scenario = scope_plan(
            api,
            portfolio,
            [
                {
                    "key": "guest",
                    "category": "GUEST_FACING",
                    "standards_reference": "GF-1.2.3",
                    "brand_estimated_cost_cents": 200000,
                },
                {
                    "key": "safety",
                    "category": "LIFE_SAFETY",
                    "standards_reference": "LS-1.2.3",
                    "brand_estimated_cost_cents": 300000,
                },
            ],
        )

        issue_plan(api, scenario)

        plan = read_plan(api, scenario.plan_id)
        safety = read_item(api, scenario.item_id("safety"))
        guest = read_item(api, scenario.item_id("guest"))

        assert plan["status"] == "ISSUED", f"unexpected lifecycle state in {plan!r}"
        assert plan["life_safety_deadline_date"] == "2026-10-30", f"unexpected date in {plan!r}"
        assert plan["guest_facing_deadline_date"] == "2027-04-28", f"unexpected date in {plan!r}"
        assert plan["back_of_house_deadline_date"] == "2027-10-25", f"unexpected date in {plan!r}"
        assert safety["deadline_date"] == "2026-10-30", f"unexpected item date in {safety!r}"
        assert safety["priority_rank"] == 1, f"life safety ranks first, got {safety!r}"
        assert guest["deadline_date"] == "2027-04-28", f"unexpected item date in {guest!r}"
        assert guest["priority_rank"] == 2, (
            f"category order beats the earlier creation order, got {guest!r}"
        )
        assert safety["item_funding_cents"] == 330000, f"unexpected funding in {safety!r}"
        assert guest["item_funding_cents"] == 236500, f"unexpected funding in {guest!r}"
        assert plan["brand_scoped_total_cents"] == 500000, f"unexpected total in {plan!r}"
        assert plan["funding_requirement_cents"] == 566500, f"unexpected requirement in {plan!r}"
        assert safety["is_overdue"] is False, f"unexpected overdue flag in {safety!r}"
        assert guest["is_overdue"] is False, f"unexpected overdue flag in {guest!r}"

    def test_issuance_stamps_the_acting_operator_and_the_logical_clock(self, api):
        """"It stamps `issued_by_user_id` with the acting operator's `X-User-ID` — the id thereby
        barred from certifying this plan's completion — and `issued_at` with the logical clock."
        "It stamps the three category deadlines from the date of `issued_at`:
        `life_safety_deadline_date` 90 calendar days out, `guest_facing_deadline_date` 270 calendar
        days out, and `back_of_house_deadline_date` 450 calendar days out."

        Design: Corner/entities/issuance_stamps_issuer_identity_and_logical_clock
        """
        portfolio = bootstrap_portfolio(
            api, "Glenmoor Inns LLC", "ops@glenmoori.example", name="Glenmoor Airport West"
        )
        scenario = scope_plan(
            api,
            portfolio,
            [
                {
                    "key": "safety",
                    "category": "LIFE_SAFETY",
                    "standards_reference": "LS-6.1.1",
                    "brand_estimated_cost_cents": 400000,
                }
            ],
            trigger_type="TRANSACTION_CHANGE_OF_OWNERSHIP",
        )
        set_clock(api, "2026-02-15T09:30:00Z")

        issuing_manager = {**BRAND_MANAGER_HEADERS, "X-User-ID": "bm-014"}
        plan = validate_success(api.issue_plan(scenario.plan_id, issuing_manager))

        assert plan["issued_by_user_id"] == "bm-014", (
            f"the issuing call's own identity is stamped, got {plan!r}"
        )
        assert plan["issued_at"] == "2026-02-15T09:30:00Z", f"unexpected instant in {plan!r}"
        assert plan["life_safety_deadline_date"] == "2026-05-16", f"unexpected date in {plan!r}"
        assert plan["guest_facing_deadline_date"] == "2026-11-12", f"unexpected date in {plan!r}"
        assert plan["back_of_house_deadline_date"] == "2027-05-11", f"unexpected date in {plan!r}"
        assert read_item(api, scenario.item_id("safety"))["deadline_date"] == "2026-05-16", (
            "the item takes its own category's deadline"
        )
        entries = ledger_entries(api, plan_id=scenario.plan_id)
        assert [entry["recorded_at_clock"] for entry in entries] == ["2026-02-15T09:30:00Z"], (
            f"the appended row records the logical clock, got {entries!r}"
        )

    def test_a_ledger_row_carries_no_version_and_no_updated_at(self, api):
        """"The one exception is the compliance ledger. A `ComplianceLedgerEntry` is append-only:
        it carries only `id` and `created_at`. Both `updated_at` and `version` are absent from its
        representation entirely, because a ledger row is never modified after it is appended." "It
        appends a ledger entry of type `SCOPE_ISSUED` with a null item reference and a `delta_cents`
        equal to the plan's brand-scoped total."

        Design: Corner/entities/ledger_entries_are_append_only_without_a_version_field
        """
        portfolio = bootstrap_portfolio(
            api, "Hollybrook Hotels LLC", "ops@hollybrookh.example", name="Hollybrook Civic Center"
        )
        scenario = scope_plan(
            api,
            portfolio,
            [
                {
                    "key": "first",
                    "category": "LIFE_SAFETY",
                    "standards_reference": "LS-7.1.1",
                    "brand_estimated_cost_cents": 300000,
                },
                {
                    "key": "second",
                    "category": "LIFE_SAFETY",
                    "standards_reference": "LS-7.1.2",
                    "brand_estimated_cost_cents": 700000,
                },
            ],
        )
        issue_plan(api, scenario)

        rows, meta = list_rows(api, "list_compliance_ledger_entries", plan_id=scenario.plan_id)

        assert meta["total_count"] == 1, f"issuance appends exactly one row, got {meta!r}"
        entry = validate_success(
            api.get_compliance_ledger_entry(rows[0]["id"], portfolio.owner_headers)
        )
        assert entry["entry_type"] == "SCOPE_ISSUED", f"unexpected type in {entry!r}"
        assert entry["item_id"] is None, f"a plan-level event names no item, got {entry!r}"
        assert entry["delta_cents"] == 1000000, f"unexpected delta in {entry!r}"
        assert entry["recorded_at_clock"] == "2026-08-01T00:00:00Z", f"unexpected clock {entry!r}"
        assert "version" not in entry, f"an append-only row carries no version, got {entry!r}"
        assert "updated_at" not in entry, f"an append-only row is never updated, got {entry!r}"


class TestForeignKeyResolution:
    def test_an_item_pointed_at_no_plan_reports_the_missing_plan(self, api, brand_manager):
        """"Only then are foreign keys carried in the body resolved, in body-field declaration
        order — `franchisee_id`, `property_id`, `plan_id`, then the item references (`item_id`,
        `pip_item_id`, `purpose_item_id`), then `predecessor_item_id`, `capital_budget_id`,
        `contractor_id`, `phase_id`, `inspection_id` — each yielding its own parent's not-found
        code."

        Design: Corner/entities/item_create_with_unknown_plan_id_returns_not_found
        """
        bootstrap_portfolio(
            api, "Junipergate Hotels LLC", "ops@junipergateh.example", name="Junipergate Harbour"
        )

        response = api.create_item(
            item_payload(
                PROBE_ID,
                category="GUEST_FACING",
                standards_reference="GF-1.1.1",
                brand_estimated_cost_cents=100000,
            ),
            brand_manager,
        )

        validate_error(response, ApiErrorId.ERR_PLAN_NOT_FOUND, 404)
        _rows, meta = list_rows(api, "list_items")
        assert meta["total_count"] == 0, f"no item may have been written, got {meta!r}"

    def test_a_dispute_naming_an_item_of_another_plan_is_refused(self, api):
        """"**Referential coherence and duty separation.** `ERR_PREDECESSOR_PLAN_MISMATCH`,
        `ERR_PREDECESSOR_NOT_SATISFIED`, `ERR_PREDECESSOR_CYCLE`, `ERR_ITEM_PLAN_MISMATCH`,
        `ERR_DRAW_ITEM_PLAN_MISMATCH`, `ERR_DRAW_PROPERTY_MISMATCH`, `ERR_NOT_PROPERTY_FRANCHISEE`,
        `ERR_NOT_ASSIGNED_INSPECTOR`, `ERR_SEGREGATION_OF_DUTIES`, and the sign-off dispute bar
        `ERR_DISPUTE_OPEN_BLOCKS_SIGNOFF`, in that order."

        Design: Corner/entities/dispute_on_an_item_of_another_plan_is_rejected
        """
        portfolio = bootstrap_portfolio(
            api, "Kestrelbay Hotels LLC", "ops@kestrelbayh.example", name="Kestrelbay Marina"
        )
        plan_a = scope_plan(
            api,
            portfolio,
            [
                {
                    "key": "a",
                    "category": "GUEST_FACING",
                    "standards_reference": "GF-1.4.1",
                    "brand_estimated_cost_cents": 1000000,
                }
            ],
        )
        issue_plan(api, plan_a)
        plan_b = scope_plan(
            api,
            portfolio,
            [
                {
                    "key": "b",
                    "category": "GUEST_FACING",
                    "standards_reference": "GF-1.4.2",
                    "brand_estimated_cost_cents": 1000000,
                }
            ],
            trigger_type="RELICENSING",
        )
        issue_plan(api, plan_b)

        response = api.create_dispute(
            {
                "plan_id": plan_a.plan_id,
                "item_id": plan_b.item_id("b"),
                "dispute_basis": "COST_ESTIMATE",
                "claimed_cost_cents": 500000,
            },
            portfolio.owner_headers,
        )

        validate_error(response, ApiErrorId.ERR_ITEM_PLAN_MISMATCH, 422)
        assert read_plan(api, plan_a.plan_id)["dispute_state"] == "NONE", (
            "the refused filing leaves the addressed plan's dispute dimension untouched"
        )
        assert read_plan(api, plan_b.plan_id)["dispute_state"] == "NONE", (
            "the refused filing leaves the owning plan's dispute dimension untouched"
        )
        assert read_item(api, plan_b.item_id("b"))["owner_claimed_cost_cents"] is None, (
            "no owner claim may be recorded by a refused filing"
        )
        _rows, meta = list_rows(api, "list_disputes", plan_id=plan_a.plan_id)
        assert meta["total_count"] == 0, f"no dispute row may persist, got {meta!r}"
