"""What the entities look like the moment they are created, what a read gives
back, and which malformed creates are refused before anything is persisted.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import (
    OPERATOR_HEADERS,
    REVIEWER_HEADERS,
    make_facility_registrant_headers,
    make_responsible_person_agent_headers,
)
from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import constants as K
from test_helpers import factories as F
from test_helpers import fixtures as X


class TestFacilityCreationAndReads:
    """The create response, the read that echoes it, and the register listing."""

    def test_a_bare_create_returns_draft_with_every_declared_default(self, api):
        """Five inputs are all the register needs, and everything else on the response is a
        server-side default: no points, no cycles, no coverage window and no registration
        number before the agency has approved anything.

        PRD: "A newly created establishment begins with `registration_status` at `DRAFT`, `compliance_posture` at `OPEN`, `serious_event_points` at 0.00, `registration_cycle_count` at 0, `abbreviated_renewal_eligible` true, `listed_product_count` and `open_serious_event_count` at 0, and `facility_fei`, `gmp_readiness_score`, `last_inspection_outcome`, `current_period_start`, `current_period_end`, `renewal_window_open_date` and `grace_end_date` all null."

        Design: Corner/entities/facility_create_returns_draft_status_and_every_declared_default
        """
        created = get_success_data(
            api.create_facility(
                F.facility_payload(
                    facility_name="Aster Labs Newark",
                    owner_operator_name="Aster Holdings LLC",
                    facility_type="MANUFACTURER",
                    country_code="US",
                    state_or_province="NJ",
                ),
                make_facility_registrant_headers("bootstrap"),
            ),
            expected_status=201,
        )

        assert created["facility_name"] == "Aster Labs Newark"
        assert created["owner_operator_name"] == "Aster Holdings LLC"
        assert created["facility_type"] == "MANUFACTURER"
        assert created["country_code"] == "US"
        assert created["state_or_province"] == "NJ"
        A.assert_facility_defaults(created)
        A.assert_identity_fields(created, "facility")

    def test_two_consecutive_reads_return_the_same_snapshot(self, api):
        """A read is not a mutation: the establishment comes back at version 1 and still in
        draft on both reads, whichever role asks for it.

        PRD: "Establishments themselves are read individually by anyone, and the agency-side roles may browse the whole register, narrowing it with a `registration_status` filter, a `compliance_posture` filter, or both."

        Design: Corner/entities/facility_retrieval_returns_the_stored_snapshot_unchanged
        """
        created = X.create_draft_facility(
            api, facility_name="Aster Labs Newark", owner_operator_name="Aster Holdings LLC"
        )
        registrant = make_facility_registrant_headers(created["id"])

        first = get_success_data(api.get_facility(created["id"], registrant))
        second = get_success_data(api.get_facility(created["id"], REVIEWER_HEADERS))

        assert first["id"] == created["id"]
        assert first["registration_status"] == K.REGISTRATION_STATUS_DRAFT
        assert first["version"] == 1
        assert second == first

    def test_the_register_pages_the_collection_and_reports_what_remains(self, api):
        """Three establishments across two pages of two: the first page is full and says more
        remain, the second holds the remainder and says otherwise, and every row appears once.

        PRD: "For every list response the `meta` object carries `limit` (the effective page size), `offset` (the effective skip count), `total_count` (the number of records matching the filter before pagination) and `has_more` (true when records remain beyond the current page)."

        Design: Corner/entities/facility_list_paginates_with_total_count_and_has_more
        """
        first_id = X.create_draft_facility(
            api, facility_name="Aster Labs Newark", owner_operator_name="Aster Holdings LLC"
        )["id"]
        second_id = X.create_draft_facility(
            api, facility_name="Borel Cosmetics Reno", owner_operator_name="Borel Group",
            facility_type="PROCESSOR", state_or_province="NV",
        )["id"]
        third_id = X.create_draft_facility(
            api, facility_name="Cyan Fill Tampa", owner_operator_name="Cyan Fill LLC",
            facility_type="BOTH", state_or_province="FL",
        )["id"]

        page_one, meta_one = validate_paginated(
            api.list_facilities(REVIEWER_HEADERS, {"limit": 2, "offset": 0})
        )
        assert len(page_one) == 2
        assert meta_one["limit"] == 2
        assert meta_one["offset"] == 0
        assert meta_one["total_count"] == 3
        assert meta_one["has_more"] is True

        page_two, meta_two = validate_paginated(
            api.list_facilities(REVIEWER_HEADERS, {"limit": 2, "offset": 2})
        )
        assert len(page_two) == 1
        assert meta_two["total_count"] == 3
        assert meta_two["has_more"] is False

        seen = A.ids_of(page_one) + A.ids_of(page_two)
        assert sorted(seen) == sorted([first_id, second_id, third_id])

    def test_the_default_page_size_is_ten_and_the_status_filter_keeps_all_three(self, api):
        """Omitting the page size falls back to ten, which is wider than the three drafts in
        the register, so the status filter matches every one of them with nothing left over.

        PRD: "Every collection endpoint accepts two optional query parameters. `limit` caps the page size: it defaults to 10 when omitted, must be at least 1, and must not exceed 100."

        Design: Corner/entities/facility_list_paginates_with_total_count_and_has_more
        """
        for name, owner in (
            ("Aster Labs Newark", "Aster Holdings LLC"),
            ("Borel Cosmetics Reno", "Borel Group"),
            ("Cyan Fill Tampa", "Cyan Fill LLC"),
        ):
            X.create_draft_facility(api, facility_name=name, owner_operator_name=owner)

        rows, meta = validate_paginated(
            api.list_facilities(
                OPERATOR_HEADERS,
                {"registration_status": K.REGISTRATION_STATUS_DRAFT},
            )
        )

        assert meta["limit"] == K.DEFAULT_LIMIT
        assert meta["offset"] == 0
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert len(rows) == 3
        assert all(
            row["registration_status"] == K.REGISTRATION_STATUS_DRAFT for row in rows
        )

    def test_an_unknown_identifier_is_not_found_on_the_root_and_the_nested_route(self, api):
        """A well-formed identifier matching no establishment is reported the same way whether
        it addresses the establishment itself or a collection beneath it, and neither call
        creates anything.

        PRD: "Existence of the addressed resources, resolved left to right along the URL as described in §2.9: `ERR_FACILITY_NOT_FOUND`, then `ERR_RESPONSIBLE_PERSON_NOT_FOUND`, then `ERR_LISTING_NOT_FOUND`, then `ERR_SUBSTANTIATION_NOT_FOUND`, then `ERR_ADVERSE_EVENT_NOT_FOUND`, then `ERR_INSPECTION_NOT_FOUND`, then `ERR_RECALL_ACTION_NOT_FOUND`, then `ERR_WITHDRAWAL_NOT_FOUND`, then `ERR_OWNERSHIP_CHANGE_NOT_FOUND`, then `ERR_DISTRIBUTION_RECORD_NOT_FOUND`."

        Design: Corner/entities/facility_get_with_unknown_uuid_not_found
        """
        validate_error(
            api.get_facility(NON_EXISTENT_UUID, REVIEWER_HEADERS),
            E.ERR_FACILITY_NOT_FOUND,
        )
        validate_error(
            api.list_registration_periods(NON_EXISTENT_UUID, REVIEWER_HEADERS),
            E.ERR_FACILITY_NOT_FOUND,
        )

        _rows, meta = validate_paginated(api.list_facilities(REVIEWER_HEADERS))
        assert meta["total_count"] == 0

    def test_the_registration_number_is_minted_in_approval_order(self, api):
        """Two establishments approved one after the other take the first two ordinals of the
        register, and the number appears only at approval — never at creation.

        PRD: "It mints the establishment's registration number into `facility_fei`, formatted as the literal prefix `FEI-` followed by a six-digit zero-padded ordinal; the ordinal is the establishment's position among all approved establishments ordered by ascending `created_at`, so the first establishment ever approved carries `FEI-000001`."

        Design: Corner/entities/facility_fei_minted_in_ascending_approval_order
        """
        first = X.create_pending_facility(
            api, facility_name="Aster Labs Newark", owner_operator_name="Aster Holdings LLC"
        )
        second = X.create_pending_facility(
            api, facility_name="Borel Cosmetics Reno", owner_operator_name="Borel Group",
            facility_type="PROCESSOR", state_or_province="NV",
        )
        assert first["facility_fei"] is None

        approved_first = get_success_data(
            api.decide_registration(
                first["id"], F.registration_decision_payload("APPROVE"), REVIEWER_HEADERS
            )
        )
        approved_second = get_success_data(
            api.decide_registration(
                second["id"], F.registration_decision_payload("APPROVE"), REVIEWER_HEADERS
            )
        )

        A.assert_fei_format(approved_first["facility_fei"], 1)
        A.assert_fei_format(approved_second["facility_fei"], 2)
        for approved in (approved_first, approved_second):
            assert approved["registration_status"] == K.REGISTRATION_STATUS_REGISTERED
            assert approved["registration_cycle_count"] == 1
            assert approved["compliance_posture"] == K.POSTURE_OPEN

    def test_approval_mints_the_initial_coverage_window_the_draft_lacked(self, api):
        """The four date fields that were null on the draft are filled from the newly active
        period, which is the establishment's first and only one.

        PRD: "Approval also mints the establishment's first coverage window as a registration period with `period_kind` `INITIAL`, `sequence_index` 1 and `status` `ACTIVE`, whose `period_start` is the UTC calendar date of the logical clock at the moment of approval."

        Design: Corner/entities/facility_fei_minted_in_ascending_approval_order
        """
        facility = X.create_registered_facility(
            api, facility_name="Aster Labs Newark", owner_operator_name="Aster Holdings LLC"
        )

        A.assert_facility_period_mirror(
            facility, K.CANONICAL_PERIOD_START, K.CANONICAL_PERIOD_END,
            "2028-05-02", "2028-09-29",
        )

        periods, meta = validate_paginated(
            api.list_registration_periods(facility["id"], REVIEWER_HEADERS)
        )
        assert meta["total_count"] == 1
        assert periods[0]["period_kind"] == K.PERIOD_KIND_INITIAL
        assert periods[0]["sequence_index"] == 1
        assert periods[0]["status"] == K.PERIOD_STATUS_ACTIVE
        assert periods[0]["facility_id"] == facility["id"]
        A.assert_period_bounds(
            periods[0], K.CANONICAL_PERIOD_START, K.CANONICAL_PERIOD_END,
            "2028-05-02", "2028-09-29",
        )


def _registered_facility_and_designee(api):
    """One approved establishment plus one designee, with the designee's headers."""
    facility = X.create_registered_facility(
        api, facility_name="Aster Labs Newark", owner_operator_name="Aster Holdings LLC"
    )
    person = X.create_responsible_person(
        api, legal_name="Aster Brands Inc",
        us_address_line="12 Market St, Newark NJ 07102",
        contact_phone="+1-202-555-0110", contact_email="safety@aster.example",
    )
    return facility, person, make_responsible_person_agent_headers(person["id"])


class TestListingCreationContract:
    """What the register accepts, what it refuses, and what it fills in."""

    def test_omitting_the_product_form_is_a_schema_violation(self, api):
        """The form of the product has no default, so a payload without it cannot be scored
        against any threshold and is refused before a row is written.

        PRD: "Request-schema conformance — `ERR_INVALID_REQUEST`."

        Design: Corner/entities/listing_create_without_product_form_returns_invalid_request
        """
        facility, person, agent = _registered_facility_and_designee(api)

        validate_error(
            api.create_listing(
                {
                    "facility_id": facility["id"],
                    "responsible_person_id": person["id"],
                    "product_name": "Aster Blush Powder",
                    "category_code": "07A",
                    "label_contact_type": K.LABEL_CONTACT_ELECTRONIC_CONTACT,
                    "label_contact_value": "safety@aster.example",
                },
                agent,
            ),
            E.ERR_INVALID_REQUEST,
        )

        _rows, meta = validate_paginated(
            api.list_listings(REVIEWER_HEADERS, {"facility_id": facility["id"]})
        )
        assert meta["total_count"] == 0

    def test_a_product_form_outside_the_enum_is_a_schema_violation_not_a_category_error(
        self, api
    ):
        """The form is an enumeration of exactly two values, so an invented third one fails the
        schema gate — which outranks the category-registry gate — even though the category code
        on the same payload is perfectly good.

        PRD: "Request-schema conformance — `ERR_INVALID_REQUEST`."
        PRD: "Category-code membership on listing creation — `ERR_UNKNOWN_CATEGORY_CODE`."

        Design: Corner/entities/listing_create_with_out_of_range_product_form_returns_invalid_request
        """
        facility, person, agent = _registered_facility_and_designee(api)

        validate_error(
            api.create_listing(
                F.listing_payload(
                    facility["id"], person["id"],
                    product_name="Aster Blush Powder",
                    category_code="07A",
                    product_form="SPRAY_ON",
                ),
                agent,
            ),
            E.ERR_INVALID_REQUEST,
        )

        _rows, meta = validate_paginated(
            api.list_listings(REVIEWER_HEADERS, {"facility_id": facility["id"]})
        )
        assert meta["total_count"] == 0

    def test_a_bare_payload_takes_every_declared_default(self, api):
        """The three optional inputs fall to their defaults, the two state dimensions start at
        the bottom, the empty ingredient set makes disclosure vacuously complete, and a draft
        occupies no designation slot.

        PRD: "A freshly created listing answers 201 and begins with `listing_status` `DRAFT`, `safety_status` `UNSUBSTANTIATED`, `listing_number` and `suspension_reason` both null, `allergen_disclosure_complete` true, `undisclosed_allergen_count` 0, `distributed_units_total` 0, `open_recall_count` 0, `open_serious_event_count` 0, `marketable` false and `version` 1."
        PRD: "three optional fields: `professional_use_only` and `professional_use_statement_present`, each defaulting to false, and `lot_authorized_units`, the per-lot unit ceiling, defaulting to 0."

        Design: Corner/entities/listing_create_applies_every_declared_default_on_a_bare_payload
        """
        facility, person, agent = _registered_facility_and_designee(api)

        created = get_success_data(
            api.create_listing(
                F.listing_payload(
                    facility["id"], person["id"],
                    product_name="Aster Blush Powder",
                    category_code="07A",
                    product_form=K.PRODUCT_FORM_LEAVE_ON,
                    label_contact_type=K.LABEL_CONTACT_ELECTRONIC_CONTACT,
                    label_contact_value="safety@aster.example",
                ),
                agent,
            ),
            expected_status=201,
        )

        A.assert_listing_defaults(created)
        assert created["professional_use_only"] is False
        assert created["professional_use_statement_present"] is False
        assert created["lot_authorized_units"] == 0

        assert X.read_facility(api, facility["id"])["listed_product_count"] == 0
        assert X.read_responsible_person(api, person["id"])["active_designation_count"] == 0

    def test_the_same_row_is_reachable_from_either_of_its_two_parents(self, api):
        """A product hangs off both an establishment and a designee, so either filter finds it
        and the unrelated establishment's filter finds nothing.

        PRD: "Listings are browsed with any combination of a `facility_id` filter, a `responsible_person_id` filter, a `listing_status` filter and a `safety_status` filter — the two state dimensions are filtered independently because they evolve independently."

        Design: Corner/entities/hybrid_topology_reaches_a_listing_from_both_of_its_parents
        """
        facility, person, agent = _registered_facility_and_designee(api)
        other = X.create_draft_facility(
            api, facility_name="Borel Cosmetics Reno", owner_operator_name="Borel Group",
            facility_type="PROCESSOR", state_or_province="NV",
        )
        listing = X.create_draft_listing(
            api, facility["id"], person["id"], product_name="Aster Blush Powder"
        )
        assert get_success_data(api.get_listing(listing["id"], agent))["id"] == listing["id"]

        by_facility, facility_meta = validate_paginated(
            api.list_listings(REVIEWER_HEADERS, {"facility_id": facility["id"]})
        )
        assert facility_meta["total_count"] == 1
        assert by_facility[0]["id"] == listing["id"]

        by_person, person_meta = validate_paginated(
            api.list_listings(REVIEWER_HEADERS, {"responsible_person_id": person["id"]})
        )
        assert person_meta["total_count"] == 1
        assert by_person[0]["id"] == listing["id"]

        _rows, other_meta = validate_paginated(
            api.list_listings(REVIEWER_HEADERS, {"facility_id": other["id"]})
        )
        assert other_meta["total_count"] == 0

        assert by_facility[0]["facility_id"] == facility["id"]
        assert by_facility[0]["responsible_person_id"] == person["id"]


class TestResponsiblePersonDefaults:
    """The designation ceiling defaults without becoming a constant."""

    def test_an_omitted_ceiling_defaults_to_twenty_five_and_the_party_starts_dormant(
        self, api
    ):
        """A designee holding no products is dormant rather than active, and the supplied
        ceiling on a second party proves the twenty-five is only a default.

        PRD: "When `designation_cap` is omitted it defaults to 25, and it may be set anywhere from 1 to 500."
        PRD: "A new responsible person starts with `active_designation_count` at 0 and `status` `DORMANT`."

        Design: Corner/entities/responsible_person_create_applies_cap_default_and_dormant_status
        """
        default_cap = X.create_responsible_person(
            api, legal_name="Aster Brands Inc",
            us_address_line="12 Market St, Newark NJ 07102",
            contact_phone="+1-202-555-0110", contact_email="safety@aster.example",
        )
        supplied_cap = X.create_responsible_person(
            api, legal_name="Borel Label Services",
            us_address_line="88 Sierra Way, Reno NV 89501",
            contact_phone="+1-202-555-0166", contact_email="rp@borel.example",
            designation_cap=1,
        )

        assert default_cap["designation_cap"] == K.DESIGNATION_CAP_DEFAULT
        assert default_cap["active_designation_count"] == 0
        assert default_cap["status"] == K.RP_STATUS_DORMANT
        assert default_cap["version"] == 1

        assert supplied_cap["designation_cap"] == 1
        assert supplied_cap["active_designation_count"] == 0
        assert supplied_cap["status"] == K.RP_STATUS_DORMANT

        stored = X.read_responsible_person(api, default_cap["id"])
        assert stored["designation_cap"] == K.DESIGNATION_CAP_DEFAULT
        assert stored["active_designation_count"] == 0
        assert stored["status"] == K.RP_STATUS_DORMANT


class TestIngredientRowsAreComputedAndParented:
    """The disclosure flag is derived, and an orphan row cannot be created."""

    def test_the_disclosure_flag_is_derived_from_the_row_not_taken_from_the_request(
        self, api
    ):
        """An allergen well above the leave-on threshold must be named while a preservative at
        two hundred and fifty times the concentration need not be: what decides the flag is the
        allergen marker and the threshold, never the request.

        PRD: "For each ingredient of the listing, `disclosure_required` is true when all three of the following hold: `is_fragrance_allergen` is true, `concentration_pct` is at or above the applicable threshold — the comparison is inclusive, and it is made against the stored four-decimal value — and the listing's `professional_use_only` is false."

        Design: Corner/entities/ingredient_disclosure_required_is_computed_not_supplied
        """
        facility, person, agent = _registered_facility_and_designee(api)
        listing = X.create_draft_listing(
            api, facility["id"], person["id"],
            product_name="Aster Blush Powder", category_code="07A",
            product_form=K.PRODUCT_FORM_LEAVE_ON,
        )

        allergen = X.add_ingredient(
            api, listing["id"], agent,
            F.allergen_ingredient_payload("LINALOOL", 0.0020),
        )
        preservative = X.add_ingredient(
            api, listing["id"], agent,
            F.ingredient_payload(
                inci_name="PHENOXYETHANOL", function_code="PRESERVATIVE",
                concentration_pct=0.5000, is_fragrance_allergen=False,
            ),
        )

        assert allergen["disclosure_required"] is True
        assert preservative["disclosure_required"] is False

        stored = X.read_listing(api, listing["id"])
        assert stored["undisclosed_allergen_count"] == 1
        assert stored["allergen_disclosure_complete"] is False

        rows, meta = validate_paginated(
            api.list_ingredients(listing["id"], agent, {"is_fragrance_allergen": True})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == allergen["id"]

    def test_an_ingredient_cannot_be_hung_off_a_listing_that_does_not_exist(self, api):
        """The parent is taken from the path and nowhere else, so an unknown path segment is
        reported before any rule about the row itself, and no orphan is written.

        PRD: "A dossier identifier that resolves to nothing is `ERR_SUBSTANTIATION_NOT_FOUND` (HTTP 404)."
        PRD: "Ingredient names are unique within a listing compared case-insensitively, so a second row whose `inci_name` differs only in letter case is rejected with `ERR_DUPLICATE_INGREDIENT` (HTTP 409)."

        Design: Corner/entities/ingredient_create_against_unknown_listing_not_found
        """
        validate_error(
            api.add_ingredient(
                NON_EXISTENT_UUID,
                F.allergen_ingredient_payload("LINALOOL", 0.0020),
                make_responsible_person_agent_headers(NON_EXISTENT_UUID),
            ),
            E.ERR_LISTING_NOT_FOUND,
        )

        _rows, meta = validate_paginated(api.list_listings(REVIEWER_HEADERS))
        assert meta["total_count"] == 0


class TestLedgerEntriesAreAppendOnlyFacts:
    """The one resource in the system without a version."""

    def test_the_approval_leaves_one_transition_row_carrying_no_version(self, api):
        """The approval writes the establishment's first ledger fact at sequence one, and the
        row exposes only an identifier and a creation instant — there is nothing on it to
        revise.

        PRD: "Ledger entries are append-only facts, never revised, so they carry only `id` and `created_at`: both `updated_at` and `version` are absent from a ledger entry, and no endpoint exists to update or delete one."
        PRD: "takes a `sequence_no` that is a 1-based monotonic counter assigned per establishment in append order."

        Design: Corner/entities/ledger_entry_is_append_only_with_no_version_field
        """
        facility = X.create_registered_facility(
            api, facility_name="Aster Labs Newark", owner_operator_name="Aster Holdings LLC"
        )

        rows, meta = validate_paginated(
            api.list_ledger_entries(
                facility["id"], REVIEWER_HEADERS,
                {"entry_type": K.ENTRY_TYPE_STATE_TRANSITION},
            )
        )

        assert meta["total_count"] == 1
        entry = rows[0]
        assert entry["entry_type"] == K.ENTRY_TYPE_STATE_TRANSITION
        assert entry["subject_entity"] == "Facility"
        assert entry["subject_id"] == facility["id"]
        assert entry["facility_id"] == facility["id"]
        assert entry["sequence_no"] == 1
        assert entry["signed_units_delta"] == 0
        assert "version" not in entry
        assert "updated_at" not in entry


class TestWindowBoundsShareOneRejection:
    """Two calendars, opposite conventions, the same error identifier."""

    def test_a_zero_length_inspection_window_is_not_a_window(self, api):
        """The inspection window is half-open, so an engagement whose end equals its start
        covers no on-site day at all and is refused before the containment and overlap rules
        are consulted.

        PRD: "First the window must be well formed: `window_start` strictly before `window_end`, or the request is refused with `ERR_INVALID_WINDOW_BOUNDS` (HTTP 422) — a zero-length window is not a window."

        Design: Corner/entities/inspection_window_bounds_reversed_returns_invalid_window_bounds
        """
        facility = X.create_registered_facility(
            api, facility_name="Aster Labs Newark", owner_operator_name="Aster Holdings LLC"
        )

        validate_error(
            api.schedule_inspection(
                facility["id"],
                F.inspection_payload(
                    "2026-09-01", "2026-09-01", K.INSPECTION_TYPE_GMP_ROUTINE
                ),
                REVIEWER_HEADERS,
            ),
            E.ERR_INVALID_WINDOW_BOUNDS,
        )

        _rows, meta = validate_paginated(
            api.list_inspections(facility["id"], REVIEWER_HEADERS)
        )
        assert meta["total_count"] == 0

    def test_a_shipment_delivered_before_it_ships_is_refused(self, api):
        """The distribution window reaches the same rejection by the opposite predicate: the
        delivery may not precede the despatch.

        PRD: "Window-bound ordering — `ERR_INVALID_WINDOW_BOUNDS`."

        Design: Corner/entities/distribution_record_ship_date_after_delivery_date_returns_invalid_window_bounds
        """
        facility, person, agent = _registered_facility_and_designee(api)
        listing = X.create_draft_listing(
            api, facility["id"], person["id"],
            product_name="Aster Blush Powder", lot_authorized_units=5000,
        )

        validate_error(
            api.create_distribution_record(
                listing["id"],
                F.distribution_record_payload(
                    lot_code="LOT-A", ship_date="2026-09-10", delivery_date="2026-09-08",
                    units_shipped=100,
                ),
                agent,
            ),
            E.ERR_INVALID_WINDOW_BOUNDS,
        )

        assert X.read_listing(api, listing["id"])["distributed_units_total"] == 0

    def test_a_same_day_shipment_is_a_legal_closed_closed_window(self, api):
        """Because the distribution window includes both its endpoints, a consignment that
        ships and arrives on one day is a real window and is accepted with everything still
        outstanding.

        PRD: "the **closed-closed** distribution window `ship_date` to `delivery_date` — both days inclusive — and the `units_shipped`, which must be greater than zero."

        Design: Corner/entities/distribution_record_ship_date_after_delivery_date_returns_invalid_window_bounds
        """
        facility, person, agent = _registered_facility_and_designee(api)
        listing = X.create_draft_listing(
            api, facility["id"], person["id"],
            product_name="Aster Blush Powder", lot_authorized_units=5000,
        )

        record = get_success_data(
            api.create_distribution_record(
                listing["id"],
                F.distribution_record_payload(
                    lot_code="LOT-A", ship_date="2026-09-10", delivery_date="2026-09-10",
                    units_shipped=100,
                ),
                agent,
            ),
            expected_status=201,
        )

        assert record["ship_date"] == record["delivery_date"] == "2026-09-10"
        assert record["units_shipped"] == 100
        assert record["units_outstanding"] == 100
        assert record["withdrawal_id"] is None
        A.assert_record_unit_balance(record)
        assert X.read_listing(api, listing["id"])["distributed_units_total"] == 100
