"""The shared envelope, server-minted system fields, listing shape and schema refusals."""

from test_helpers import (
    ApiErrorId,
    ApplicationStatus,
    BorrowerStatus,
    DrawRequestStatus,
    EntityType,
    NON_EXISTENT_UUID,
    PropertyStatus,
    ScopeCode,
    api_client,
    assert_error_envelope,
    assert_system_fields,
    factories,
    fixtures,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
    CREDIT_COMMITTEE,
    INSPECTOR,
    LOAN_OFFICER,
    SERVICER,
)

CLOCK = "2026-08-10T09:00:00Z"
CLOCK_INSTANT = "2026-08-10T09:00:00.000Z"
LATER_CLOCK = "2026-08-10T11:00:00Z"
LATER_INSTANT = "2026-08-10T11:00:00.000Z"
CLOSING_DATE = "2026-08-10"
DRAW_CLOCK = "2026-09-01T12:00:00Z"


def _bad_application(borrower_id, property_id, **overrides):
    return validate_error(
        api_client.create_application(
            factories.application_payload(borrower_id, property_id, **overrides),
            LOAN_OFFICER,
        ),
        ApiErrorId.INVALID_REQUEST.value,
        400,
    )


def _bad_borrower(**overrides):
    return validate_error(
        api_client.create_borrower(factories.borrower_payload(**overrides), LOAN_OFFICER),
        ApiErrorId.INVALID_REQUEST.value,
        400,
    )


class TestApplicationListing:
    def test_the_sponsor_filter_narrows_the_set_before_the_page_is_cut(self):
        """Three rows for one sponsor page two at a time while the other sponsor sees one.

        `total_count` reports the size of the filtered collection rather than the size
        of the page, `has_more` turns false only once the last row has been handed out,
        and the omitted paging parameters come back at their declared defaults. The PRD
        states: "`limit` caps the number of records returned; it defaults to 10, has a
        minimum of 1 and a maximum of 100."

        Design: Corner/entities/application_list_paginates_and_filters_by_borrower
        """
        fixtures.set_clock(CLOCK)
        sponsor = fixtures.build_approved_sponsor()
        peer = fixtures.build_approved_sponsor(legal_entity_name="Saguaro Flips LLC")
        own = []
        for address in ("18 Larkspur Ct", "22 Larkspur Ct", "26 Larkspur Ct"):
            subject = fixtures.register_property(address_line=address)
            own.append(fixtures.open_application(sponsor["id"], subject["id"]))
        peer_property = fixtures.register_property(address_line="9 Ocotillo Ln")
        peer_application = fixtures.open_application(peer["id"], peer_property["id"])

        first_page, first_meta = validate_paginated(
            api_client.list_applications(
                LOAN_OFFICER,
                {"borrower_id": sponsor["id"], "limit": 2, "offset": 0},
            )
        )
        assert [row["id"] for row in first_page] == [own[0]["id"], own[1]["id"]], (
            "the page is ordered by created_at ascending"
        )
        assert first_meta["total_count"] == 3, (
            f"total_count reports the filtered set, got {first_meta['total_count']}"
        )
        assert first_meta["has_more"] is True
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0

        second_page, second_meta = validate_paginated(
            api_client.list_applications(
                LOAN_OFFICER,
                {"borrower_id": sponsor["id"], "limit": 2, "offset": 2},
            )
        )
        assert [row["id"] for row in second_page] == [own[2]["id"]]
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False
        assert second_meta["offset"] == 2

        peer_page, peer_meta = validate_paginated(
            api_client.list_applications(LOAN_OFFICER, {"borrower_id": peer["id"]})
        )
        assert [row["id"] for row in peer_page] == [peer_application["id"]], (
            "the peer's page never leaks the other sponsor's applications"
        )
        assert peer_meta["total_count"] == 1
        assert peer_meta["limit"] == 10, "the omitted limit falls back to its default"
        assert peer_meta["offset"] == 0
        assert peer_meta["has_more"] is False

        sized, sized_meta = validate_paginated(
            api_client.list_applications(
                LOAN_OFFICER, {"status": ApplicationStatus.SIZED.value}
            )
        )
        assert sized == []
        assert sized_meta["total_count"] == 0
        assert sized_meta["has_more"] is False

        for row in first_page + second_page + peer_page:
            assert row["status"] == ApplicationStatus.DRAFT.value
            assert row["approved_rehab_total_cents"] == 0
            assert row["max_total_loan_cents"] is None
            assert row["sizing_stale"] is False


class TestNotFoundCodes:
    def test_every_entity_reports_its_own_404_in_paths_and_in_bodies(self):
        """Ten path lookups and two body references each name the entity that is missing.

        The body arms are the discriminating ones: a missing `borrower_id` on an
        application is a not-found rather than a schema failure, and a missing
        `contractor_id` on a scope line is a not-found even though the parent
        application in the path resolves cleanly. The PRD states: "The same codes are
        used for identifiers supplied in a request body, such as a `borrower_id` or
        `property_id` on an application, a `contractor_id` on a scope line, or a
        `loan_id` and `contractor_id` on a lien waiver."

        Design: Corner/entities/unknown_identifiers_return_the_entity_specific_not_found_code
        """
        fixtures.set_clock(CLOCK)
        sponsor = fixtures.build_approved_sponsor()
        subject = fixtures.register_property()
        contractor = fixtures.register_contractor()
        application = fixtures.open_application(sponsor["id"], subject["id"])

        path_arms = (
            (api_client.get_borrower(NON_EXISTENT_UUID, LOAN_OFFICER),
             ApiErrorId.BORROWER_NOT_FOUND.value),
            (api_client.get_property(NON_EXISTENT_UUID, LOAN_OFFICER),
             ApiErrorId.PROPERTY_NOT_FOUND.value),
            (api_client.get_application(NON_EXISTENT_UUID, LOAN_OFFICER),
             ApiErrorId.APPLICATION_NOT_FOUND.value),
            (api_client.get_rehab_line_item(NON_EXISTENT_UUID, LOAN_OFFICER),
             ApiErrorId.REHAB_LINE_ITEM_NOT_FOUND.value),
            (api_client.get_contractor(NON_EXISTENT_UUID, LOAN_OFFICER),
             ApiErrorId.CONTRACTOR_NOT_FOUND.value),
            (api_client.get_loan(NON_EXISTENT_UUID, SERVICER),
             ApiErrorId.LOAN_NOT_FOUND.value),
            (api_client.get_draw_request(NON_EXISTENT_UUID, SERVICER),
             ApiErrorId.DRAW_REQUEST_NOT_FOUND.value),
            (api_client.report_inspection_visit(
                NON_EXISTENT_UUID,
                factories.inspection_report_payload(
                    [factories.line_verification(NON_EXISTENT_UUID, 0.50)]
                ),
                INSPECTOR,
             ), ApiErrorId.INSPECTION_VISIT_NOT_FOUND.value),
            (api_client.dispute_lien_waiver(
                NON_EXISTENT_UUID, factories.waiver_dispute_payload(), SERVICER
             ), ApiErrorId.LIEN_WAIVER_NOT_FOUND.value),
            (api_client.get_foreclosure_case(NON_EXISTENT_UUID, SERVICER),
             ApiErrorId.FORECLOSURE_CASE_NOT_FOUND.value),
        )
        seen = []
        for response, expected in path_arms:
            body = validate_error(response, expected, 404)
            assert_error_envelope(response.json())
            seen.append(body["error_id"])
        assert len(set(seen)) == 10, f"each entity needs its own code, got {seen}"

        body_borrower = validate_error(
            api_client.create_application(
                factories.application_payload(NON_EXISTENT_UUID, subject["id"]),
                LOAN_OFFICER,
            ),
            ApiErrorId.BORROWER_NOT_FOUND.value,
            404,
        )
        assert body_borrower["error_id"] == ApiErrorId.BORROWER_NOT_FOUND.value, (
            "a missing body reference is a not-found, never a schema failure"
        )
        validate_error(
            api_client.create_rehab_line_item(
                application["id"],
                factories.rehab_line_payload(
                    ScopeCode.ROOF.value, 4_000_000, NON_EXISTENT_UUID
                ),
                LOAN_OFFICER,
            ),
            ApiErrorId.CONTRACTOR_NOT_FOUND.value,
            404,
        )

        _, application_meta = validate_paginated(
            api_client.list_applications(LOAN_OFFICER, {"borrower_id": sponsor["id"]})
        )
        assert application_meta["total_count"] == 1, (
            "the refused application create wrote no row"
        )
        lines, line_meta = validate_paginated(
            api_client.list_application_rehab_line_items(application["id"], LOAN_OFFICER)
        )
        assert line_meta["total_count"] == 0, (
            f"the refused scope line wrote no row, got {line_meta['total_count']}"
        )
        assert lines == []
        assert fixtures.read_contractor(contractor["id"])["payable"] is True


class TestRequiredApplicationFields:
    def test_each_omitted_term_is_a_400_that_outranks_the_sponsor_eligibility_row(self):
        """Term, rate and reserve months carry no defaults, so each omission is refused alone.

        Both identifiers in the body resolve and the sponsor has not even been approved,
        yet all three refusals report the schema row rather than the eligibility row,
        which places the schema check ahead of every business gate. The PRD states:
        "Opening an application requires a `borrower_id`, a `property_id`, a
        `term_months` between 6 and 18 inclusive, a `quoted_rate_bps` between 800 and
        1800 inclusive, an `interest_reserve_months` between 0 and 12 inclusive, and an
        optional `day_count_convention` of `PER_DIEM_360` or `PER_DIEM_365` that
        defaults to `PER_DIEM_360`."

        Design: Corner/entities/application_missing_required_fields_is_rejected
        """
        fixtures.set_clock(CLOCK)
        sponsor = fixtures.register_borrower()
        assert sponsor["status"] == BorrowerStatus.PROSPECT.value, (
            "the sponsor is not eligible, which is the rule the schema check outranks"
        )
        subject = fixtures.register_property()

        for missing in ("term_months", "quoted_rate_bps", "interest_reserve_months"):
            refusal = _bad_application(
                sponsor["id"], subject["id"], **factories.omit(missing)
            )
            assert refusal["error_id"] == ApiErrorId.INVALID_REQUEST.value, (
                f"omitting {missing} must report the schema row"
            )

        rows, meta = validate_paginated(
            api_client.list_applications(LOAN_OFFICER, {"borrower_id": sponsor["id"]})
        )
        assert meta["total_count"] == 0, (
            f"none of the three refusals created a row, got {meta['total_count']}"
        )
        assert rows == []

        accepted = fixtures.open_application(sponsor["id"], subject["id"])
        assert accepted["term_months"] == 9
        assert accepted["quoted_rate_bps"] == 1150
        assert accepted["interest_reserve_months"] == 6
        assert accepted["status"] == ApplicationStatus.DRAFT.value


class TestServerMintedFields:
    def test_ids_timestamps_and_versions_come_from_the_server_not_the_caller(self):
        """Two bare-UUID rows at version 1, then one mutation that steps exactly one version.

        Neither create supplies an id, a status or a version, yet both rows come back
        with distinct identifiers, the system-assigned initial status and timestamps
        taken from the logical clock rather than the host wall clock. The PRD states:
        "`version` (integer): a server-managed counter that increments by one on every
        mutation of the record."

        Design: Corner/entities/system_fields_are_minted_by_the_server
        """
        fixtures.set_clock(CLOCK)
        first = fixtures.register_property(address_line="18 Larkspur Ct")
        second = fixtures.register_property(address_line="22 Larkspur Ct")

        for row in (first, second):
            assert_system_fields(row, expected_version=1)
            assert is_valid_uuid(row["id"]), f"id must be a bare UUID: {row['id']!r}"
            assert "prop_" not in row["id"], "the UUID carries no type prefix"
            assert row["created_at"] == CLOCK_INSTANT, (
                f"created_at reads the logical clock, got {row['created_at']}"
            )
            assert row["updated_at"] == CLOCK_INSTANT
            assert row["status"] == PropertyStatus.UNDER_CONTRACT.value, (
                "the initial status is system-assigned"
            )
            assert row["valuation_revision_count"] == 0
        assert first["id"] != second["id"], "two creates mint two distinct identifiers"

        fixtures.set_clock(LATER_CLOCK)
        revised = validate_success(
            api_client.revalue_property(
                first["id"],
                factories.valuation_payload(
                    appraisal_date=CLOSING_DATE, arv_cents=33_000_000
                ),
                LOAN_OFFICER,
            ),
            200,
        )
        assert revised["id"] == first["id"], "a mutation never re-mints the identifier"
        assert revised["created_at"] == CLOCK_INSTANT, "created_at is written once"
        assert revised["updated_at"] == LATER_INSTANT
        assert revised["updated_at"] > revised["created_at"]
        assert revised["version"] == 2, "one mutation steps the version by exactly one"
        assert revised["arv_cents"] == 33_000_000
        assert revised["appraisal_date"] == CLOSING_DATE
        assert revised["purchase_price_cents"] == 20_000_000, (
            "an omitted revision field is left untouched"
        )
        assert revised["as_is_value_cents"] == 21_000_000
        assert revised["valuation_revision_count"] == 1

        untouched = fixtures.read_property(second["id"])
        assert untouched["version"] == 1, "the sibling row was never mutated"
        assert untouched["arv_cents"] == 32_000_000


class TestSchemaBounds:
    def test_range_enum_and_cross_field_breaches_all_report_the_schema_row(self):
        """Six bad values, six identical refusals, and the inclusive upper bounds still pass.

        The cross-field flips comparison and the paging bound are enforced in the same
        layer as the simple ranges, so none of the six is silently clamped into a
        business error. The PRD states: "Counts of flips must be zero or greater,
        `flips_last_24mo` may never exceed `flips_lifetime`, `credit_score` must fall
        between 300 and 850 inclusive, `liquidity_cents` and `prior_default_count` must
        be zero or greater, and `declared_target_loan_cents` must be strictly greater
        than zero."

        Design: Corner/entities/out_of_range_and_out_of_enum_values_are_rejected
        """
        fixtures.set_clock(CLOCK)
        sponsor = fixtures.register_borrower()
        subject = fixtures.register_property()

        _bad_borrower(legal_entity_name="Over Fico LLC", credit_score=851)
        _bad_borrower(legal_entity_name="Family Trust", entity_type="TRUST")
        _bad_borrower(
            legal_entity_name="Bad Counts LLC", flips_last_24mo=9, flips_lifetime=8
        )
        _bad_application(sponsor["id"], subject["id"], term_months=24)
        _bad_application(sponsor["id"], subject["id"], interest_reserve_months=13)
        validate_error(
            api_client.list_applications(LOAN_OFFICER, {"limit": 101}),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )

        _, meta = validate_paginated(api_client.list_applications(LOAN_OFFICER))
        assert meta["total_count"] == 0, (
            f"no rejected application was written, got {meta['total_count']}"
        )

        edge_sponsor = validate_success(
            api_client.create_borrower(
                factories.borrower_payload(
                    legal_entity_name="Edge Fico LLC",
                    entity_type=EntityType.LLC.value,
                    credit_score=850,
                ),
                LOAN_OFFICER,
            ),
            201,
        )
        assert edge_sponsor["credit_score"] == 850, (
            "850 is the inclusive upper bound and must be accepted"
        )
        edge_application = fixtures.open_application(
            edge_sponsor["id"], subject["id"], term_months=18
        )
        assert edge_application["term_months"] == 18, (
            "18 is the inclusive upper bound and must be accepted"
        )
        _, after = validate_paginated(api_client.list_applications(LOAN_OFFICER))
        assert after["total_count"] == 1


class TestErrorEnvelope:
    def test_the_404_400_409_and_412_classes_share_one_envelope_shape(self):
        """Four different failure classes, one shape, and no resource payload in any of them.

        Every body carries the same three top-level keys, the same two `meta` keys and
        exactly `error_id` and `message` under `data`, so the status code and the code
        string are the only things that vary. The PRD states: "The `meta` object for
        error responses contains only `api_request_id` and `api_request_timestamp`."

        Design: Corner/errors/every_error_response_uses_the_same_envelope_and_never_carries_data
        """
        ctx = fixtures.build_closed_loan()
        stale_version = ctx.loan["version"]
        fixtures.set_clock(DRAW_CLOCK)
        draw = fixtures.submit_draw(
            ctx, [(ctx.line_by_code("ROOF")["id"], 0.60)]
        )
        assert draw["status"] == DrawRequestStatus.SUBMITTED.value

        arms = (
            (api_client.get_borrower(NON_EXISTENT_UUID, LOAN_OFFICER),
             ApiErrorId.BORROWER_NOT_FOUND.value, 404),
            (api_client.create_property(
                factories.property_payload(
                    address_line="9 Cholla Rd", purchase_price_cents=-1
                ),
                LOAN_OFFICER,
             ), ApiErrorId.INVALID_REQUEST.value, 400),
            (api_client.close_application(
                ctx.application_id, factories.close_payload("2026-08-11"), SERVICER
             ), ApiErrorId.APPLICATION_STATE_INVALID.value, 409),
            (api_client.create_draw_request(
                ctx.loan_id,
                factories.draw_request_payload(
                    [factories.line_allocation(ctx.line_by_code("ROOF")["id"], 0.60)],
                    stale_version,
                ),
                ctx.borrower_headers,
             ), ApiErrorId.STALE_LOAN_VERSION.value, 412),
        )
        codes = []
        for response, expected_code, expected_status in arms:
            body = response.json()
            assert_error_envelope(body)
            validate_error(response, expected_code, expected_status)
            assert "id" not in body["data"], (
                f"an error must not smuggle a resource row: {body['data']}"
            )
            codes.append((expected_status, body["data"]["error_id"]))
        assert codes == [
            (404, ApiErrorId.BORROWER_NOT_FOUND.value),
            (400, ApiErrorId.INVALID_REQUEST.value),
            (409, ApiErrorId.APPLICATION_STATE_INVALID.value),
            (412, ApiErrorId.STALE_LOAN_VERSION.value),
        ], f"four distinct classes with four distinct codes, got {codes}"

        assert ctx.refresh_application()["status"] == ApplicationStatus.CLOSED.value
        assert ctx.refresh_loan()["commitment_balance_check_cents"] == 0
        requests, request_meta = validate_paginated(
            api_client.list_draw_requests(SERVICER, {"loan_id": ctx.loan_id})
        )
        assert request_meta["total_count"] == 1, (
            f"the 412 created no draw request, got {request_meta['total_count']}"
        )
        assert requests[0]["id"] == draw["id"]

        healthy = validate_success(
            api_client.get_application(ctx.application_id, CREDIT_COMMITTEE), 200
        )
        assert healthy["id"] == ctx.application_id, (
            "the success envelope still carries the resource under data"
        )
