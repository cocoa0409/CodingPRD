"""The shape of a freshly written row: declared fields, defaults and envelopes."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    CASE_MANAGER,
    PROVIDER_ADMIN,
    admit_registrar,
    api_client,
    assert_complainant,
    assert_domain,
    assert_case,
    assert_event_row_fields,
    assert_fee_transaction,
    assert_ground,
    assert_panelist,
    assert_registrar,
    build_docket,
    case_payload,
    complainant_payload,
    domain_payload,
    fee_transaction_payload,
    file_complaint,
    get_success_data,
    ground_payload,
    is_iso8601_timestamp,
    make_complainant_headers,
    panelist_payload,
    post_ledger_line,
    read_case,
    read_complainant,
    register_domain,
    registrar_payload,
    set_domain_lock,
    setup_filed_case,
    validate_error,
    validate_paginated,
)


class TestRegistrarAccreditation:
    def test_accreditation_returns_every_declared_field_inside_a_standard_envelope(self):
        """PRD §3.1: "A `ProviderAdmin` accredits a registrar by supplying its display
        `name`, its IANA registrar identifier as `iana_id`, and the abuse and
        verification mailbox as `contact_email`."
        PRD §3.1: "A newly accredited registrar begins with `status` `ACTIVE` and
        `overdue_verification_count` at 0."
        PRD §2.5: "Most resources additionally carry `updated_at`, an ISO 8601 UTC
        timestamp refreshed on every mutation, and `version`, an integer that begins at
        1 when the row is created and increments by one on every mutation of that row."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the
        request that starts with `req_`."

        Design: Corner/entities/registrar_creation_returns_every_declared_field
        """
        response = api_client.create_registrar(
            registrar_payload(
                name="Northwind Registrar", iana_id="IANA-9001",
                contact_email="abuse@northwind.example", verification_response_hours=72,
            ),
            PROVIDER_ADMIN,
        )
        registrar = get_success_data(response, 201)
        assert_registrar(registrar)
        assert registrar["name"] == "Northwind Registrar"
        assert registrar["iana_id"] == "IANA-9001"
        assert registrar["contact_email"] == "abuse@northwind.example"
        assert registrar["verification_response_hours"] == 72, (
            "the supplied value stands in place of the default"
        )
        assert registrar["status"] == "ACTIVE"
        assert registrar["overdue_verification_count"] == 0
        assert registrar["version"] == 1
        assert registrar["created_at"] == "2026-08-01T00:00:00.000Z"
        assert registrar["updated_at"] == "2026-08-01T00:00:00.000Z"

        envelope = response.json()
        assert envelope["response_type"] == "object"
        assert envelope["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(envelope["meta"]["api_request_timestamp"])

        stored = get_success_data(api_client.get_registrar(registrar["id"], PROVIDER_ADMIN))
        assert stored["status"] == "ACTIVE"
        assert stored["overdue_verification_count"] == 0
        assert stored["verification_response_hours"] == 72

    def test_the_declared_defaults_stand_in_for_every_omitted_optional_input(self):
        """PRD §3.1: "Two service-level numbers ride along on the registrar record:
        `verification_response_hours`, the number of hours the registrar is given to
        answer a verification request before the provider sweeps it to overdue, which
        defaults to 48 when omitted and must be between 1 and 336; and
        `lock_sla_hours`, the number of hours the registrar commits to for applying a
        transfer lock, which defaults to 24, is likewise bounded between 1 and 336, and
        is recorded purely for audit — no gate anywhere in this specification enforces
        it."
        PRD §3.1: "Three optional attributes may accompany the admission: `firm_name`,
        the law-firm affiliation disclosed during conflict screening, which is null for
        a sole practitioner; `specializations`, an array of subject tags recorded
        strictly for audit and never used as a selector filter or as a ranking key; and
        `max_overlapping_engagements`, the aggregate ceiling on engagement windows that
        may overlap a new candidate window on that neutral, which defaults to 5 and
        must be between 1 and 20."
        PRD §3.1: "A newly admitted panelist begins at `status` `AVAILABLE` with
        `active_case_load` at 0."

        Design: Corner/entities/registrar_and_panelist_defaults_apply_when_optional_inputs_are_omitted
        """
        registrar = get_success_data(
            api_client.create_registrar(
                registrar_payload(
                    name="Default Registrar", iana_id="IANA-9002",
                    contact_email="abuse@defaultreg.example",
                ),
                PROVIDER_ADMIN,
            ),
            201,
        )
        assert_registrar(registrar)
        assert registrar["verification_response_hours"] == 48
        assert registrar["lock_sla_hours"] == 24

        panelist = get_success_data(
            api_client.create_panelist(
                panelist_payload(
                    full_name="Default Panelist", nationality_code="DE",
                    roster_admitted_at="2020-01-01T00:00:00Z",
                ),
                PROVIDER_ADMIN,
            ),
            201,
        )
        assert_panelist(panelist)
        assert panelist["max_overlapping_engagements"] == 5
        assert panelist["status"] == "AVAILABLE"
        assert panelist["active_case_load"] == 0
        assert panelist["firm_name"] is None


class TestFilingWritesItsComputedFields:
    def test_the_first_accepted_complaint_carries_the_provisional_assessment_and_docket_number(self):
        """PRD §3.2: "Two optional attributes shape the proceeding from the outset:
        `panel_election`, the panel size the complainant elects, which is `SINGLE` by
        default and may be `THREE`; and `expedited_requested`, a boolean defaulting to
        false that buys expedited administrative handling in exchange for a surcharge."
        PRD §3.2: "An accepted filing lands in `status` `FILED` with `version` 1, mints
        its `case_number`, and sets `respondent_panel_election` to `NONE`."
        PRD §3.2: "A standard single-member filing therefore assesses 150000 cents
        entirely to the complainant with a pool of 105000 cents, and an expedited
        single-member filing assesses 168750 cents entirely to the complainant with a
        pool of 118125 cents."
        PRD §2.5: "That counter increments once per accepted case creation, in
        `created_at` ascending order, so the first accepted complaint is
        `D-2026-000001`, the second `D-2026-000002`, and so on."

        Design: Corner/entities/case_creation_computes_money_fields_and_system_fields_at_filing
        """
        docket = build_docket(
            iana_id="IANA-9003", domain_name="compute.example",
            country_code="GB", legal_name="Compute Ltd", registrar_name="Compute Registrar",
        )
        complainant_id = docket["complainant"]["id"]
        case = get_success_data(
            api_client.create_case(
                case_payload(complainant_id, docket["domain"]["id"]),
                make_complainant_headers(complainant_id),
            ),
            201,
        )
        assert_case(case)
        assert case["status"] == "FILED"
        assert case["version"] == 1
        assert case["created_at"] == "2026-08-01T00:00:00.000Z"
        assert case["panel_election"] == "SINGLE"
        assert case["expedited_requested"] is False
        assert case["required_seat_count"] == 1
        assert case["respondent_panel_election"] == "NONE"
        assert case["assessed_fee_cents"] == 150000
        assert case["complainant_share_cents"] == 150000
        assert case["respondent_share_cents"] == 0
        assert case["honoraria_pool_cents"] == 105000
        assert case["fee_variant_applied"] == "PROVISIONAL"
        assert case["paid_cents"] == 0
        assert case["complainant_paid_cents"] == 0
        assert case["respondent_paid_cents"] == 0
        assert case["deficiency_round_count"] == 0
        assert case["case_number"] == "D-2026-000001", (
            "the docket number is minted by the server from its own counter"
        )
        assert read_complainant(complainant_id)["open_case_count"] == 1


class TestDomainListing:
    def test_the_domain_list_pages_in_creation_order_and_filters_on_the_lock(self):
        """PRD §2.3: "List endpoints are paginated through two query parameters.
        `limit` caps the number of rows returned; it defaults to 10 when omitted, must
        be at least 1, and may not exceed 100."
        PRD §2.3: "Unless a specific endpoint says otherwise, list results are ordered
        by the resource's creation timestamp ascending — oldest first."
        PRD §2.3: "`total_count` counts the rows that satisfy the request's filters
        before pagination is applied, and `has_more` is true when rows remain beyond
        the returned window."
        PRD §3.1: "Domains can be listed with a filter on `registrar_id` or on
        `lock_status`."

        Design: Corner/entities/domain_listing_is_paginated_and_filterable_with_a_correct_envelope
        """
        registrar = get_success_data(
            api_client.create_registrar(
                registrar_payload(
                    name="Paging Registrar", iana_id="IANA-9004",
                    contact_email="abuse@pagingreg.example",
                ),
                PROVIDER_ADMIN,
            ),
            201,
        )
        names = ["page1.example", "page2.example", "page3.example"]
        domains = [
            get_success_data(
                api_client.create_domain(domain_payload(registrar["id"], name), PROVIDER_ADMIN), 201
            )
            for name in names
        ]
        for domain in domains:
            assert_domain(domain)
            assert domain["lock_status"] == "UNLOCKED"
        set_domain_lock(domains[2]["id"], "LOCKED")

        first_response = api_client.list_domains(
            PROVIDER_ADMIN, params={"registrar_id": registrar["id"], "limit": 2, "offset": 0}
        )
        first_page, first_meta = validate_paginated(first_response)
        assert first_response.json()["response_type"] == "array"
        assert first_meta["total_count"] == 3
        assert first_meta["has_more"] is True
        assert [row["domain_name"] for row in first_page] == ["page1.example", "page2.example"]

        second_page, second_meta = validate_paginated(
            api_client.list_domains(
                PROVIDER_ADMIN, params={"registrar_id": registrar["id"], "limit": 2, "offset": 2}
            )
        )
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False
        assert second_meta["limit"] == 2
        assert second_meta["offset"] == 2
        assert [row["domain_name"] for row in second_page] == ["page3.example"]

        locked, locked_meta = validate_paginated(
            api_client.list_domains(PROVIDER_ADMIN, params={"lock_status": "LOCKED"})
        )
        assert locked_meta["total_count"] == 1
        assert [row["domain_name"] for row in locked] == ["page3.example"]


class TestMissingRowsReportTheirOwnCode:
    def test_a_case_id_that_names_nothing_is_a_missing_case(self):
        """PRD §2.6: "Identifiers in a path are resolved strictly left to right, and
        the first identifier that names nothing aborts the request with the 404 that
        belongs to that position."
        PRD §2.6: "A path rooted at a case resolves the case first and reports
        `ERR_CASE_NOT_FOUND` when it names no case; a domain path reports
        `ERR_DOMAIN_NOT_FOUND`; a panelist path reports `ERR_PANELIST_NOT_FOUND`; an
        appointment path reports `ERR_APPOINTMENT_NOT_FOUND`; a decision path reports
        `ERR_DECISION_NOT_FOUND`."

        Design: Corner/entities/unknown_case_id_read_returns_case_not_found
        """
        refused = api_client.get_case(NON_EXISTENT_UUID, CASE_MANAGER)
        validate_error(refused, ApiErrorId.ERR_CASE_NOT_FOUND.value, 404)
        body = refused.json()
        assert body["response_type"] == "error"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"]
        assert "id" not in body["data"]

        _, meta = validate_paginated(api_client.list_cases(CASE_MANAGER))
        assert meta["total_count"] == 0, "a failed read creates nothing"

    def test_each_root_entity_path_reports_the_404_that_belongs_to_its_position(self):
        """PRD §2.10: "**Existence**, path identifiers first and left to right
        (`ERR_CASE_NOT_FOUND`, `ERR_DOMAIN_NOT_FOUND`, `ERR_PANELIST_NOT_FOUND`,
        `ERR_APPOINTMENT_NOT_FOUND`, `ERR_DECISION_NOT_FOUND`), then nested
        sub-resource and court-challenge identifiers, then body-referenced identifiers
        (`ERR_RESOURCE_NOT_FOUND` for both of the latter)."

        Design: Corner/entities/unknown_domain_panelist_appointment_and_decision_ids_are_not_found
        """
        validate_error(
            api_client.get_domain(NON_EXISTENT_UUID, CASE_MANAGER),
            ApiErrorId.ERR_DOMAIN_NOT_FOUND.value, 404,
        )
        validate_error(
            api_client.get_panelist(NON_EXISTENT_UUID, PROVIDER_ADMIN),
            ApiErrorId.ERR_PANELIST_NOT_FOUND.value, 404,
        )
        validate_error(
            api_client.get_appointment(NON_EXISTENT_UUID, CASE_MANAGER),
            ApiErrorId.ERR_APPOINTMENT_NOT_FOUND.value, 404,
        )
        validate_error(
            api_client.get_decision(NON_EXISTENT_UUID, CASE_MANAGER),
            ApiErrorId.ERR_DECISION_NOT_FOUND.value, 404,
        )
        for response in (
            api_client.get_domain(NON_EXISTENT_UUID, CASE_MANAGER),
            api_client.get_panelist(NON_EXISTENT_UUID, PROVIDER_ADMIN),
            api_client.get_appointment(NON_EXISTENT_UUID, CASE_MANAGER),
            api_client.get_decision(NON_EXISTENT_UUID, CASE_MANAGER),
        ):
            body = response.json()
            assert body["response_type"] == "error"
            assert "id" not in body["data"]


class TestSchemaRefusalsWriteNothing:
    def test_a_filing_that_omits_the_remedy_is_refused_and_the_retry_with_it_lands(self):
        """PRD §3.2: "A complaint is filed by naming the filing party as
        `complainant_id`, the single disputed domain as `domain_id`, the country the
        complainant submits to for court challenge as `mutual_jurisdiction` (exactly two
        uppercase letters), and the relief sought as `remedy_requested`, which is either
        `TRANSFER` or `CANCELLATION`."
        PRD §2.10: "**Schema.** Required fields present, enum values drawn from their
        declared sets, integer fields non-negative where the field requires it, and any
        two-letter country code exactly two letters — else `ERR_INVALID_REQUEST`."

        Design: Corner/entities/case_creation_rejects_a_missing_required_input_field
        """
        docket = build_docket(
            iana_id="IANA-9005", domain_name="required.example",
            country_code="GB", legal_name="Required SA", registrar_name="Required Registrar",
        )
        complainant_id = docket["complainant"]["id"]
        headers = make_complainant_headers(complainant_id)
        incomplete = case_payload(complainant_id, docket["domain"]["id"])
        del incomplete["remedy_requested"]

        refused = api_client.create_case(incomplete, headers)
        validate_error(refused, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
        _, meta = validate_paginated(
            api_client.list_cases(CASE_MANAGER, params={"complainant_id": complainant_id})
        )
        assert meta["total_count"] == 0
        assert read_complainant(complainant_id)["open_case_count"] == 0

        accepted = get_success_data(
            api_client.create_case(
                case_payload(complainant_id, docket["domain"]["id"]), headers
            ),
            201,
        )
        assert accepted["status"] == "FILED"
        assert accepted["remedy_requested"] == "TRANSFER"

    def test_a_three_letter_code_an_undeclared_enum_and_a_zero_amount_are_all_refused(self):
        """PRD §3.1: "Complainants are registered with a `legal_name`, an ISO 3166-1
        alpha-2 `country_code` of exactly two uppercase letters, and a correspondence
        `email`."
        PRD §3.2: "A complaint is filed by naming the filing party as `complainant_id`,
        the single disputed domain as `domain_id`, the country the complainant submits to
        for court challenge as `mutual_jurisdiction` (exactly two uppercase letters), and
        the relief sought as `remedy_requested`, which is either `TRANSFER` or
        `CANCELLATION`."
        PRD §3.3: "Inflows are positive and refund lines are negative; the magnitude must
        lie between -10000000 and 10000000 and may never be exactly 0."

        Design: Corner/entities/two_letter_code_and_enum_and_amount_constraints_are_rejected
        """
        bundle = setup_filed_case(
            pay_filing_fee=False, iana_id="IANA-9006", domain_name="types.example",
            country_code="GB", legal_name="Types Ltd", registrar_name="Types Registrar",
        )
        case_id = bundle["case"]["id"]
        complainant_id = bundle["complainant"]["id"]

        lowercase = api_client.create_complainant(
            complainant_payload(
                legal_name="Lowercase Ltd", country_code="fra", email="ip@lowercase.example"
            ),
            CASE_MANAGER,
        )
        validate_error(lowercase, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

        bad_enum = case_payload(complainant_id, bundle["domain"]["id"])
        bad_enum["remedy_requested"] = "DELETE"
        validate_error(
            api_client.create_case(bad_enum, make_complainant_headers(complainant_id)),
            ApiErrorId.ERR_INVALID_REQUEST.value, 400,
        )

        zero_line = api_client.create_fee_transaction(
            case_id,
            fee_transaction_payload(0, kind="FILING_FEE", payer="COMPLAINANT", reference="ZERO"),
            CASE_MANAGER,
        )
        validate_error(zero_line, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

        _, ledger_meta = validate_paginated(
            api_client.list_fee_transactions(case_id, CASE_MANAGER, params={"limit": 10, "offset": 0})
        )
        assert ledger_meta["total_count"] == 0
        assert read_case(case_id)["paid_cents"] == 0
        _, case_meta = validate_paginated(
            api_client.list_cases(CASE_MANAGER, params={"complainant_id": complainant_id})
        )
        assert case_meta["total_count"] == 1, "only the setup filing exists"


class TestGroundGrading:
    def test_the_grade_is_computed_from_the_annex_count_on_both_sides_of_the_threshold(self):
        """PRD §3.2: "Every asserted element is graded the moment it is written."
        PRD §3.2: "Its `sufficiency_status` is `SUFFICIENT` when `evidence_count` is at
        least 1, and `DEFICIENT` otherwise — the threshold is inclusive, so a single
        annex suffices and zero annexes does not."
        PRD §3.2: "Each assertion also carries `cited_decision_ids`, an array of earlier
        decisions relied on as precedent, defaulting to empty."
        PRD §2.3: "Unless a specific endpoint says otherwise, list results are ordered by
        the resource's creation timestamp ascending — oldest first."

        Design: Corner/entities/ground_sufficiency_status_is_computed_from_evidence_count_and_never_supplied
        """
        docket = build_docket(
            iana_id="IANA-9007", domain_name="suff.example",
            country_code="GB", legal_name="Suff Ltd", registrar_name="Suff Registrar",
        )
        case = file_complaint(docket["complainant"], docket["domain"])
        headers = make_complainant_headers(docket["complainant"]["id"])

        unsupported = get_success_data(
            api_client.create_ground(
                case["id"],
                ground_payload(
                    "TRADEMARK_RIGHTS", evidence_count=0,
                    assertion_text="SUFF is a registered mark with no exhibits attached yet.",
                    similarity_claim="IDENTICAL",
                ),
                headers,
            ),
            201,
        )
        assert_ground(unsupported)
        assert unsupported["evidence_count"] == 0
        assert unsupported["sufficiency_status"] == "DEFICIENT"

        supported = get_success_data(
            api_client.create_ground(
                case["id"],
                ground_payload(
                    "BAD_FAITH", evidence_count=1,
                    assertion_text="The registrant offered the name for sale, exhibit attached.",
                ),
                headers,
            ),
            201,
        )
        assert_ground(supported)
        assert supported["evidence_count"] == 1
        assert supported["sufficiency_status"] == "SUFFICIENT"
        assert supported["cited_decision_ids"] == []

        rows, meta = validate_paginated(
            api_client.list_grounds(case["id"], CASE_MANAGER, params={"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 2
        assert [row["ground_type"] for row in rows] == ["TRADEMARK_RIGHTS", "BAD_FAITH"]
        assert [row["sufficiency_status"] for row in rows] == ["DEFICIENT", "SUFFICIENT"]


class TestLedgerLinesAreEventRows:
    def test_a_correcting_line_is_a_new_row_and_never_rewrites_the_original(self):
        """PRD §2.5: "Two record types are immutable event rows and are the exception: a
        panel ballot and a fee ledger line carry only `id` and `created_at`."
        PRD §2.5: "Neither has an `updated_at` and neither has a `version` — once
        written, they are never modified, and nothing in the system rewrites them."
        PRD §3.3: "Ledger lines are immutable once written — nothing in the system amends
        or deletes one, and a correction is expressed as a further line."
        PRD §3.3: "After every ledger write, and after every refund cascade, the case's
        three derived money fields are recomputed from the whole ledger rather than
        adjusted in place: `complainant_paid_cents` is the sum of `amount_cents` over the
        case's lines attributed to `COMPLAINANT`, `respondent_paid_cents` is the same sum
        over lines attributed to `RESPONDENT`, and `paid_cents` is the sum over every
        line on the case regardless of payer."

        Design: Corner/entities/fee_transaction_and_panel_vote_rows_are_immutable_and_carry_no_version
        """
        bundle = setup_filed_case(
            iana_id="IANA-9008", domain_name="immut.example",
            country_code="GB", legal_name="Immut Ltd", registrar_name="Immut Registrar",
        )
        case_id = bundle["case"]["id"]
        original = post_ledger_line(case_id, 150000, reference="WIRE-9008-EXTRA")
        assert_fee_transaction(original)
        assert_event_row_fields(original)
        assert original["amount_cents"] == 150000
        assert original["recorded_at"] == "2026-08-01T00:00:00.000Z"

        correction = post_ledger_line(
            case_id, -50000, kind="REFUND", reference="CORRECTION-9008", headers=PROVIDER_ADMIN
        )
        assert_fee_transaction(correction)
        assert_event_row_fields(correction)
        assert correction["amount_cents"] == -50000
        assert correction["id"] != original["id"]

        rows, meta = validate_paginated(
            api_client.list_fee_transactions(case_id, CASE_MANAGER, params={"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 3
        assert [row["amount_cents"] for row in rows] == [150000, 150000, -50000]
        stored_original = rows[1]
        assert stored_original["id"] == original["id"]
        assert stored_original["amount_cents"] == 150000
        assert stored_original["recorded_at"] == "2026-08-01T00:00:00.000Z"
        for row in rows:
            assert_event_row_fields(row)

        case = read_case(case_id)
        assert case["complainant_paid_cents"] == 250000
        assert case["paid_cents"] == 250000
        assert case["respondent_paid_cents"] == 0


class TestParentAndBodyIdentifiers:
    def test_a_ground_under_a_fabricated_case_id_reports_the_missing_parent(self):
        """PRD §2.6: "Identifiers in a path are resolved strictly left to right, and the
        first identifier that names nothing aborts the request with the 404 that belongs
        to that position."
        PRD §2.6: "A path rooted at a case resolves the case first and reports
        `ERR_CASE_NOT_FOUND` when it names no case; a domain path reports
        `ERR_DOMAIN_NOT_FOUND`; a panelist path reports `ERR_PANELIST_NOT_FOUND`; an
        appointment path reports `ERR_APPOINTMENT_NOT_FOUND`; a decision path reports
        `ERR_DECISION_NOT_FOUND`."

        Design: Corner/entities/child_creation_requires_an_existing_parent_case_in_the_path
        """
        docket = build_docket(
            iana_id="IANA-9009", domain_name="parent.example",
            country_code="GB", legal_name="Parent Ltd", registrar_name="Parent Registrar",
        )
        case = file_complaint(docket["complainant"], docket["domain"])
        headers = make_complainant_headers(docket["complainant"]["id"])
        body = ground_payload(
            "TRADEMARK_RIGHTS", evidence_count=1,
            assertion_text="PARENT is a registered mark with exhibits attached.",
            similarity_claim="IDENTICAL",
        )

        orphan = api_client.create_ground(NON_EXISTENT_UUID, body, headers)
        validate_error(orphan, ApiErrorId.ERR_CASE_NOT_FOUND.value, 404)
        assert orphan.json()["data"]["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value

        written = get_success_data(api_client.create_ground(case["id"], body, headers), 201)
        assert written["case_id"] == case["id"]
        assert written["ground_type"] == "TRADEMARK_RIGHTS"
        rows, meta = validate_paginated(
            api_client.list_grounds(case["id"], CASE_MANAGER, params={"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 1, "the refused write left no orphan row behind"
        assert rows[0]["id"] == written["id"]

    def test_a_filing_naming_an_unknown_domain_or_complainant_reports_the_body_reference(self):
        """PRD §2.6: "The same discipline extends to identifiers carried in a request
        body rather than in the path."
        PRD §2.6: "A `complainant_id`, `domain_id`, `panelist_id`, `notice_id`,
        `drafted_by_panelist_id`, `replacement_panelist_id` or any member of a
        `cited_decision_ids` array must name an existing row of the entity it is expected
        to name; if not, the request is refused with `ERR_RESOURCE_NOT_FOUND`."
        PRD §2.6: "Body-referenced existence is checked after path existence and before
        the schema check."

        Design: Corner/entities/body_referenced_foreign_keys_are_validated_on_case_creation
        """
        docket = build_docket(
            iana_id="IANA-9010", domain_name="fk.example",
            country_code="GB", legal_name="FK Ltd", registrar_name="FK Registrar",
        )
        complainant_id = docket["complainant"]["id"]
        domain_id = docket["domain"]["id"]

        unknown_domain = api_client.create_case(
            case_payload(complainant_id, NON_EXISTENT_UUID),
            make_complainant_headers(complainant_id),
        )
        validate_error(unknown_domain, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value, 404)

        unknown_complainant = api_client.create_case(
            case_payload(NON_EXISTENT_UUID, domain_id), CASE_MANAGER
        )
        validate_error(unknown_complainant, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value, 404)

        accepted = get_success_data(
            api_client.create_case(
                case_payload(complainant_id, domain_id), make_complainant_headers(complainant_id)
            ),
            201,
        )
        assert accepted["domain_id"] == domain_id
        assert accepted["complainant_id"] == complainant_id
        _, meta = validate_paginated(
            api_client.list_cases(CASE_MANAGER, params={"complainant_id": complainant_id})
        )
        assert meta["total_count"] == 1, "neither rejection wrote a case"


class TestDomainNameUniqueness:
    def test_the_same_name_under_a_second_registrar_is_still_a_duplicate(self):
        """PRD §3.1: "The `domain_name` is stored lowercased, must be between 4 and 253
        characters, and is globally unique — a second attempt at a name already on the
        docket is refused with `ERR_DUPLICATE_DOMAIN_NAME`."
        PRD §2.10: "**Referential uniqueness and occupation**, in this internal order:
        domain-name uniqueness (`ERR_DUPLICATE_DOMAIN_NAME`); a domain already occupied
        by a live proceeding (`ERR_DOMAIN_PROCEEDING_OVERLAP`); a domain still inside a
        closed case's cooling-off interval (`ERR_REFILING_BAR_ACTIVE`); a second ground
        of the same type on one case (`ERR_DUPLICATE_GROUND_TYPE`); a cited precedent
        that is not citable (`ERR_CITED_PRECEDENT_NOT_PUBLISHED`)."

        Design: Corner/entities/domain_name_uniqueness_is_global_across_registrars
        """
        first = admit_registrar(iana_id="IANA-9011", name="Dupe Registrar One")
        second = admit_registrar(iana_id="IANA-9012", name="Dupe Registrar Two")
        assert first["id"] != second["id"]
        domain = register_domain(first["id"], "dupe.example")
        assert domain["domain_name"] == "dupe.example"
        assert domain["registrar_id"] == first["id"]

        duplicate = api_client.create_domain(
            domain_payload(
                second["id"], "dupe.example",
                registrant_name_public="Other Holder",
                registrant_email_public="other@proxy.example",
                registration_date="2021-01-01T00:00:00Z",
                expiry_date="2028-01-01T00:00:00Z",
            ),
            PROVIDER_ADMIN,
        )
        validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_DOMAIN_NAME.value, 409)

        rows, meta = validate_paginated(
            api_client.list_domains(PROVIDER_ADMIN, params={"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == domain["id"]
        assert rows[0]["registrar_id"] == first["id"], "the rejected write did not repoint the row"
        assert rows[0]["version"] == domain["version"]
