"""Registration of licensees and terminals, and the record shapes they expose."""

from test_helpers import (
    ApiErrorId,
    assert_append_only_common_fields,
    assert_bond_position,
    assert_gallons,
    assert_imposition,
    assert_mutable_common_fields,
    assert_total_count,
    assert_zero_compliance_counters,
    factories,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    licensee_payload,
    line_payload,
    rack_removal_payload,
    terminal_payload,
)


class TestLicenseeRegistration:
    def test_registering_a_supplier_returns_201_with_the_system_fields_stamped(
        self, api, officer_headers
    ):
        """A create carrying only the four required inputs is stamped and lands in PENDING_BOND.

        PRD: "Every persisted resource carries a server-minted `id` formatted as a UUID with no
        type prefix, and a `created_at` timestamp rendered as an ISO 8601 UTC instant with three
        fractional digits (for example `2026-08-01T00:00:00.000Z`)."
        PRD: "A newly registered licensee lands in `PENDING_BOND`."

        Design: Corner/entities/licensee_creation_returns_201_with_system_fields_stamped
        """
        payload = licensee_payload(
            "SUPPLIER", legal_name="Cedar Bluff Fuel Supply LLC", mailing_state="MN"
        )

        response = api.create_licensee(payload, officer_headers)

        created = validate_success(response, expected_status=201)
        assert_mutable_common_fields(created, expected_version=1)
        assert created["legal_name"] == "Cedar Bluff Fuel Supply LLC"
        assert created["fein"] == payload["fein"]
        assert created["license_type"] == "SUPPLIER"
        assert created["mailing_state"] == "MN"
        assert (
            created["status"] == "PENDING_BOND"
        ), f"a newly registered licensee must land in PENDING_BOND, got {created['status']}"

        reread = validate_success(api.get_licensee(created["id"], officer_headers))
        assert reread["id"] == created["id"]
        assert reread["status"] == "PENDING_BOND"
        assert reread["version"] == created["version"]

    def test_omitting_license_type_is_refused_and_creates_nothing(self, api, officer_headers):
        """license_type is a required registration input, not something the server guesses.

        PRD: "A `LicensingOfficer` brings a taxpayer into the system by registering it with its
        registered `legal_name` (between 1 and 120 characters), its `fein` (a federal employer
        identification number written as two digits, a hyphen and seven digits), its statutory
        `license_type`, and the two-letter `mailing_state` of record."

        Design: Corner/entities/licensee_create_missing_license_type_returns_invalid_request
        """
        payload = {
            "legal_name": "Delta Fuel Supply LLC",
            "fein": factories.next_fein(),
            "mailing_state": "MN",
        }

        response = api.create_licensee(payload, officer_headers)

        validate_error(response, ApiErrorId.INVALID_REQUEST, expected_status=400)
        _rows, meta = validate_paginated(api.list_licensees(officer_headers))
        assert_total_count(meta, 0, "licensee total_count after a refused create")

    def test_an_undeclared_license_type_member_is_refused(self, api, officer_headers):
        """license_type is a closed five-member enum, so a plausible extra member is refused.

        PRD: "The classification is one of `SUPPLIER`, `DISTRIBUTOR`, `BLENDER`, `TRANSPORTER` or
        `RETAILER`, and it is consequential far beyond labelling: it sets the bond multiplier, it
        decides which schedules the licensee may report, and it decides whether tax imposition can
        be deferred to that licensee at a terminal rack."

        Design: Corner/entities/licensee_create_unknown_license_type_enum_returns_invalid_request
        """
        payload = licensee_payload(
            "TERMINAL_OPERATOR", legal_name="Juliet Terminal Services LLC"
        )

        response = api.create_licensee(payload, officer_headers)

        validate_error(response, ApiErrorId.INVALID_REQUEST, expected_status=400)
        _rows, meta = validate_paginated(api.list_licensees(officer_headers))
        assert_total_count(meta, 0, "licensee total_count after a refused create")

    def test_omitted_optional_declarations_materialise_their_defaults(
        self, api, officer_headers
    ):
        """The two optional declarations default on the row, and every counter starts at zero.

        PRD: "`gross_net_election` is the licensee's irrevocable choice of the gallons basis
        applied to its own rack removals — either `NET` or `GROSS`, defaulting to `NET`."
        PRD: "`parent_licensee_id` names the consolidated group filer this licensee reports under,
        and defaults to null."

        Design: Corner/entities/licensee_defaults_apply_when_election_and_channel_omitted
        """
        response = api.create_licensee(
            licensee_payload("TRANSPORTER", legal_name="Echo Transport Lines LLC"),
            officer_headers,
        )

        created = validate_success(response, expected_status=201)
        assert (
            created["gross_net_election"] == "NET"
        ), "gross_net_election defaults to NET when omitted"
        assert (
            created["retail_channel"] == "NOT_APPLICABLE"
        ), "retail_channel defaults to NOT_APPLICABLE when omitted"
        assert created["parent_licensee_id"] is None, "parent_licensee_id defaults to null"
        assert_zero_compliance_counters(created)

    def test_bond_figures_are_rederived_by_the_bond_post_itself(self, api, world):
        """A partial bond leaves the shortfall visible on the row and on the computed read.

        PRD: "`posted_bond_cents` is the sum of `amount_cents` over the licensee's bond
        instruments whose `status` is `ACTIVE`; released and forfeited instruments contribute
        nothing."
        PRD: "`bond_deficiency_cents` is the amount by which the requirement exceeds what is
        posted, floored at zero — when posted bond meets or exceeds the requirement, the deficiency
        is exactly 0."

        Design: Corner/entities/licensee_bond_computed_fields_rederived_after_bond_post
        """
        licensee = world.new_licensee("DISTRIBUTOR", legal_name="Foxtrot Distribution Inc")
        assert_bond_position(licensee, required_bond_cents=1500000, posted_bond_cents=0)

        bond = world.post_bond(licensee["id"], 900000)
        assert bond["status"] == "ACTIVE"
        assert bond["release_reason"] is None

        after = world.licensee(licensee["id"])
        assert_bond_position(
            after,
            required_bond_cents=1500000,
            posted_bond_cents=900000,
            bond_deficiency_cents=600000,
        )
        status = world.bond_status(licensee["id"])
        assert_bond_position(
            status,
            required_bond_cents=1500000,
            posted_bond_cents=900000,
            bond_deficiency_cents=600000,
            basis_return_count=0,
        )
        assert (
            after["version"] > licensee["version"]
        ), "posting a bond mutates the licensee, so its version must advance"

    def test_reading_an_unused_licensee_id_returns_licensee_not_found(
        self, api, officer_headers
    ):
        """A well-formed but unused path id resolves to the licensee's own 404 code.

        PRD: "Path parameters are resolved strictly left to right, and the first identifier that
        does not resolve determines the 404 that comes back."

        Design: Corner/entities/licensee_get_with_unused_uuid_returns_licensee_not_found
        """
        response = api.get_licensee("00000000-0000-4000-8000-000000000999", officer_headers)

        validate_error(response, ApiErrorId.LICENSEE_NOT_FOUND, expected_status=404)
        _rows, meta = validate_paginated(api.list_licensees(officer_headers))
        assert_total_count(meta, 0, "licensee total_count after a 404 probe")


class TestListingAndPagination:
    def test_licensee_listing_pages_while_total_count_covers_the_filtered_set(
        self, api, world, officer_headers
    ):
        """total_count counts the whole filtered set, and has_more tracks the page position.

        PRD: "The `meta` object of a list response carries `limit`, `offset`, `total_count` and
        `has_more`, where `total_count` is the number of rows matching the filters before
        pagination is applied."

        Design: Corner/entities/licensee_listing_paginates_with_total_count_and_has_more
        """
        world.new_licensee("SUPPLIER", legal_name="Alpha Fuel Supply LLC")
        world.new_licensee("DISTRIBUTOR", legal_name="Bravo Distribution Inc")
        world.new_licensee("RETAILER", legal_name="Charlie Retail Stops LLC")

        first_rows, first_meta = validate_paginated(
            api.list_licensees(officer_headers, params={"limit": 2, "offset": 0})
        )
        second_rows, second_meta = validate_paginated(
            api.list_licensees(officer_headers, params={"limit": 2, "offset": 2})
        )

        assert len(first_rows) == 2, "limit 2 must cap the first page at two rows"
        assert_total_count(first_meta, 3)
        assert first_meta["has_more"] is True, "two of three rows leaves more to fetch"
        assert len(second_rows) == 1, "the second page holds the remaining row"
        assert_total_count(second_meta, 3)
        assert second_meta["has_more"] is False, "the last page reports has_more false"
        first_ids = {row["id"] for row in first_rows}
        assert not (
            first_ids & {row["id"] for row in second_rows}
        ), "the two pages must not share a row"

        filtered_rows, filtered_meta = validate_paginated(
            api.list_licensees(officer_headers, params={"license_type": "DISTRIBUTOR"})
        )
        assert_total_count(filtered_meta, 1, "total_count under the license_type filter")
        assert filtered_rows[0]["license_type"] == "DISTRIBUTOR"

    def test_a_line_is_reachable_from_the_counterparty_side_of_the_edge(self, api, world):
        """The cross-licensee edge on a line is reachable from the counterparty that does not own it.

        PRD: "Lines may be listed under their schedule, or across schedules filtered by
        `schedule_id`, `counterparty_licensee_id`, `exemption_certificate_id` and
        `transaction_type`."

        Design: Corner/entities/schedule_line_is_reverse_reachable_from_its_counterparty_licensee
        """
        supplier = world.new_licensee("SUPPLIER", legal_name="November Fuel Supply LLC")
        distributor = world.new_licensee("DISTRIBUTOR", legal_name="Oscar Distribution Inc")
        built = world.build_return(
            distributor["id"],
            "2026-07",
            [
                {
                    "code": "SCH_1_RECEIVED_TAX_PAID",
                    "product": "UNDYED_DIESEL",
                    "total": 100.00,
                    "lines": [
                        {
                            "counterparty": supplier["id"],
                            "gallons": 100.00,
                            "date": "2026-07-09",
                        }
                    ],
                }
            ],
        )

        rows, meta = validate_paginated(
            api.list_schedule_lines(
                world.examiner, params={"counterparty_licensee_id": supplier["id"]}
            )
        )

        assert_total_count(meta, 1, "lines naming the supplier as counterparty")
        assert rows[0]["id"] == built.line["id"]
        assert rows[0]["schedule_id"] == built.schedule["id"]
        assert_gallons(rows[0]["gallons"], 100.00, "line gallons")
        assert rows[0]["transaction_type"] == "PURCHASE"

        owning_rows, owning_meta = validate_paginated(
            api.list_schedule_lines_of(built.schedule["id"], world.examiner)
        )
        assert_total_count(owning_meta, 1, "lines listed from the owning schedule")
        assert owning_rows[0]["id"] == built.line["id"]
        schedule = validate_success(api.get_schedule(built.schedule["id"], world.examiner))
        assert schedule["line_count"] == 1, "line_count is maintained as lines are added"

        _reverse, reverse_meta = validate_paginated(
            api.list_schedule_lines(
                world.examiner, params={"counterparty_licensee_id": distributor["id"]}
            )
        )
        assert_total_count(reverse_meta, 0, "the counterparty edge is directional")


class TestTerminalsAndAppendOnlyRecords:
    def test_reading_a_terminal_echoes_exactly_what_was_stored(self, api, world, officer_headers):
        """A terminal is inert reference data: the read echoes the stored control number and name.

        PRD: "Terminals are registered by a `LicensingOfficer` with their IRS
        `terminal_control_number` — the letter `T`, two digits, two uppercase letters and four
        digits — a trade `name`, and the two-letter `state_code` of the state the rack physically
        sits in."

        Design: Corner/entities/terminal_retrieval_returns_the_stored_row
        """
        payload = terminal_payload(name="Rosemount Rack", state_code="MN")
        created = validate_success(
            api.create_terminal(payload, officer_headers), expected_status=201
        )

        response = api.get_terminal(created["id"], world.examiner)

        terminal = validate_success(response)
        assert terminal["id"] == created["id"]
        assert terminal["terminal_control_number"] == payload["terminal_control_number"]
        assert terminal["name"] == "Rosemount Rack"
        assert terminal["state_code"] == "MN"
        assert_mutable_common_fields(terminal, expected_version=1)

    def test_a_rack_removal_freezes_its_determination_and_carries_no_version(self, api, world):
        """A rack removal is an append-only observation whose tax figures are frozen at report time.

        PRD: "Three record types are append-only observations rather than mutable state, and they
        carry only `id` and `created_at` — both `updated_at` and `version` are absent from them
        entirely: rack removals, schedule lines and ledger entries."

        Design: Corner/entities/rack_removal_row_is_immutable_and_carries_no_version
        """
        terminal = world.terminal(name="Duluth Rack")
        supplier = world.active_licensee("SUPPLIER", gross_net_election="NET")
        retailer = world.active_licensee("RETAILER")
        created = validate_success(
            api.create_rack_removal(
                rack_removal_payload(
                    terminal["id"],
                    supplier["id"],
                    retailer["id"],
                    product_code="GASOLINE",
                    gross_gallons=5000.00,
                    net_gallons=4975.00,
                ),
                world.examiner,
            ),
            expected_status=201,
        )

        response = api.get_rack_removal(created["id"], world.examiner)

        removal = validate_success(response)
        assert removal["id"] == created["id"]
        assert_append_only_common_fields(removal)
        assert_imposition(
            removal,
            basis_used="NET",
            imposition_point="TERMINAL_RACK",
            taxable_gallons=4975.00,
            tax_imposed=True,
            tax_amount_cents=142285,
            deferred_tax_cents=0,
        )

    def test_net_gallons_above_gross_gallons_is_refused_before_any_tax_is_computed(
        self, api, world
    ):
        """The declared numeric constraint on net gallons fires before the imposition calculation.

        PRD: "Gross gallons must be greater than zero; net gallons must be greater than zero and
        must not exceed gross gallons."

        Design: Corner/entities/rack_removal_net_above_gross_returns_invalid_request
        """
        terminal = world.terminal(name="Alexandria Rack")
        supplier = world.active_licensee("SUPPLIER", gross_net_election="NET")
        retailer = world.active_licensee("RETAILER")

        response = api.create_rack_removal(
            rack_removal_payload(
                terminal["id"],
                supplier["id"],
                retailer["id"],
                product_code="GASOLINE",
                gross_gallons=5000.00,
                net_gallons=5010.00,
            ),
            world.examiner,
        )

        validate_error(response, ApiErrorId.INVALID_REQUEST, expected_status=400)
        _rows, meta = validate_paginated(
            api.list_rack_removals(world.examiner, params={"terminal_id": terminal["id"]})
        )
        assert_total_count(meta, 0, "rack removals after a refused report")

    def test_a_line_under_an_unused_schedule_id_returns_schedule_not_found(self, api, world):
        """The path's schedule id is resolved before any check on the line body.

        PRD: "Path parameters are resolved strictly left to right, and the first identifier that
        does not resolve determines the 404 that comes back."

        Design: Corner/entities/schedule_line_create_under_unused_schedule_id_returns_schedule_not_found
        """
        supplier = world.new_licensee("SUPPLIER", legal_name="Mike Fuel Supply LLC")

        response = api.create_line(
            "00000000-0000-4000-8000-000000000777",
            line_payload(supplier["id"], 100.00, "2026-07-10"),
            world.examiner,
        )

        validate_error(response, ApiErrorId.SCHEDULE_NOT_FOUND, expected_status=404)
        _rows, meta = validate_paginated(
            api.list_schedule_lines(
                world.examiner, params={"counterparty_licensee_id": supplier["id"]}
            )
        )
        assert_total_count(meta, 0, "schedule lines after a 404 probe")

    def test_a_certificate_naming_an_unused_purchaser_is_refused_as_a_body_foreign_key(
        self, api, officer_headers
    ):
        """A body foreign key naming no licensee is refused, and no dangling certificate is created.

        PRD: "**Body foreign keys**, in the order the fields are declared on the request:
        identifiers naming a licensee (`licensee_id`, `parent_licensee_id`,
        `purchaser_licensee_id`, `position_holder_licensee_id`, `counterparty_licensee_id`,
        `inspected_licensee_id`, `subject_licensee_id`) resolve to a licensee or the request fails
        with `ERR_LICENSEE_NOT_FOUND`; `terminal_id` resolves or fails with
        `ERR_TERMINAL_NOT_FOUND`; a non-null `exemption_certificate_id` resolves or fails with
        `ERR_CERTIFICATE_NOT_FOUND`; a non-null `source_discrepancy_id` resolves or fails with
        `ERR_DISCREPANCY_NOT_FOUND`."

        Design: Corner/entities/exemption_certificate_for_unused_purchaser_id_returns_licensee_not_found
        """
        response = api.create_certificate(
            {
                "purchaser_licensee_id": "00000000-0000-4000-8000-000000000555",
                "exemption_type": "GOVERNMENT",
                "document_number": "CERT-ORPHAN-1",
                "valid_from": "2026-01-01",
                "valid_to": "2026-12-31",
            },
            officer_headers,
        )

        validate_error(response, ApiErrorId.LICENSEE_NOT_FOUND, expected_status=404)
        _rows, meta = validate_paginated(api.list_certificates(officer_headers))
        assert_total_count(meta, 0, "certificates after a refused create")
