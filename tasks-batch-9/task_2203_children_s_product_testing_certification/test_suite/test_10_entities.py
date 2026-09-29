"""Row shapes: creation echo, retrieval, listing, defaults and field ownership."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    factories,
    fixtures as fx,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    ADMIN_USER_ID,
    COORDINATOR_HEADERS,
    COORDINATOR_USER_ID,
    MANAGER_HEADERS,
    OFFICER_HEADERS,
    make_laboratory_user_headers,
    make_supplier_user_headers,
)


STARTUP_CLOCK = "2026-08-01T00:00:00Z"

LEAD_RULE_INPUT = {
    "rule_code": "LEAD_CONTENT_100",
    "hazard_class": "LEAD_CONTENT",
    "test_method_code": "CPSC-CH-E1002-08",
    "limit_value": 100,
    "limit_unit": "PPM",
    "limit_comparator": "AT_OR_BELOW",
    "periodic_interval_months": 12,
    "base_method_fee_cents": 18700,
    "component_reliance_allowed": True,
    "severity_weight": 9,
}


class TestApplicableRuleCreationEcho:
    """The root reference entity echoes every submitted field back unchanged."""

    def test_creation_echoes_every_submitted_field_and_stamps_the_audit_columns(self, api):
        """PRD 3.1: "A **regulatory rule** is registered with a `rule_code` — an uppercase
        snake-case identifier of between 3 and 40 characters that must be unique across all
        rules — and a `hazard_class` drawn from `LEAD_PAINT`, `LEAD_CONTENT`, `PHTHALATES`,
        `MECHANICAL_HAZARD` or `FLAMMABILITY`." PRD 2.4: "Almost every resource additionally
        carries `updated_at`, in the same format, refreshed on every mutation of that row,
        and `version`, an integer that begins at 1 on creation and increments by exactly 1
        on every mutation."

        Design: Corner/entities/corner_entities_creation_applicable_rule_echoes_every_input_field
        """
        fx.set_clock(api, STARTUP_CLOCK)
        rule = validate_success(
            api.create_rule(dict(LEAD_RULE_INPUT), headers=ADMIN_HEADERS), 201
        )

        assert is_valid_uuid(rule["id"])
        for field, submitted in LEAD_RULE_INPUT.items():
            assert rule[field] == submitted

        assert rule["version"] == 1
        assert is_iso8601_timestamp(rule["created_at"])
        assert is_iso8601_timestamp(rule["updated_at"])

    def test_a_second_rule_echoes_its_own_opposite_choices_independently(self, api):
        """PRD 3.1: "The rule carries its numeric ceiling or floor as `limit_value`, which
        must be at least 0, expressed in a `limit_unit` of `PPM`, `PERCENT_BY_WEIGHT`,
        `NEWTON` or `MILLIMETRE`, together with a `limit_comparator` of either `AT_OR_BELOW`
        or `AT_OR_ABOVE` that defaults to `AT_OR_BELOW` when the registrant omits it."

        Design: Corner/entities/corner_entities_creation_applicable_rule_echoes_every_input_field
        """
        fx.set_clock(api, STARTUP_CLOCK)
        first = validate_success(
            api.create_rule(dict(LEAD_RULE_INPUT), headers=ADMIN_HEADERS), 201
        )
        second_input = {
            "rule_code": "SEAM_STRENGTH_MIN",
            "hazard_class": "MECHANICAL_HAZARD",
            "test_method_code": "ASTM-F963-23",
            "limit_value": 15,
            "limit_unit": "NEWTON",
            "limit_comparator": "AT_OR_ABOVE",
            "periodic_interval_months": 3,
            "base_method_fee_cents": 0,
            "component_reliance_allowed": False,
            "severity_weight": 1,
        }
        second = validate_success(
            api.create_rule(dict(second_input), headers=ADMIN_HEADERS), 201
        )
        for field, submitted in second_input.items():
            assert second[field] == submitted
        assert second["id"] != first["id"]
        assert second["version"] == 1


class TestSingleResourceRetrieval:
    """A read is field-for-field identical to the write and mutates nothing."""

    def test_two_consecutive_reads_match_the_creation_body_exactly(self, api):
        """PRD 2.4: "Almost every resource additionally carries `updated_at`, in the same
        format, refreshed on every mutation of that row, and `version`, an integer that
        begins at 1 on creation and increments by exactly 1 on every mutation."

        Design: Corner/entities/corner_entities_retrieval_single_resource_read_matches_creation_response
        """
        fx.set_clock(api, STARTUP_CLOCK)
        created = validate_success(
            api.create_rule(dict(LEAD_RULE_INPUT), headers=ADMIN_HEADERS), 201
        )

        first = validate_success(api.get_rule(created["id"], headers=COORDINATOR_HEADERS))
        second = validate_success(api.get_rule(created["id"], headers=COORDINATOR_HEADERS))

        assert first["id"] == created["id"]
        assert first == created
        assert second == first
        assert second["version"] == 1
        assert second["updated_at"] == created["updated_at"]

    def test_the_category_read_path_is_open_to_a_coordinator_as_well(self, api):
        """PRD 3.1: "A category carries a unique uppercase snake-case `category_code` of 3
        to 40 characters, a human-readable `display_name` of 1 to 120 characters, an
        `intended_age_max_months` between 0 and 168 inclusive marking the top of the
        intended-user age range, and a `sampling_floor_units` of at least 1 — the absolute
        minimum number of sample units any sampling plan for a product in this category may
        authorise."

        Design: Corner/entities/corner_entities_retrieval_single_resource_read_matches_creation_response
        """
        fx.set_clock(api, STARTUP_CLOCK)
        created = fx.create_category(
            api,
            category_code="INFANT_CARRIER",
            display_name="Infant carriers",
            intended_age_max_months=24,
            sampling_floor_units=2,
        )
        read = validate_success(
            api.get_category(created["id"], headers=COORDINATOR_HEADERS)
        )
        assert read == created
        assert read["category_code"] == "INFANT_CARRIER"
        assert read["intended_age_max_months"] == 24
        assert read["sampling_floor_units"] == 2
        assert read["version"] == 1


THREE_RULE_CODES = [
    ("LEAD_CONTENT_100", "LEAD_CONTENT"),
    ("PHTHALATE_1000", "PHTHALATES"),
    ("SMALL_PARTS_01", "MECHANICAL_HAZARD"),
]


def _three_rules_env(api):
    """Three rules across three hazard classes, created oldest first."""
    fx.set_clock(api, STARTUP_CLOCK)
    return [
        fx.create_rule(api, rule_code=code, hazard_class=hazard_class)
        for code, hazard_class in THREE_RULE_CODES
    ]


class TestListingEnvelopeAndFilter:
    """Two pages partition the collection, and the filter narrows total_count."""

    def test_two_pages_of_two_partition_the_collection_with_no_overlap(self, api):
        """PRD 2.3: "List responses carry four pagination fields inside `meta`: the echoed
        `limit`, the echoed `offset`, `total_count` giving the number of rows matching the
        filter before pagination is applied, and `has_more`, which is true exactly when rows
        remain beyond the current page."

        Design: Corner/entities/corner_entities_listing_applicable_rules_pagination_and_filter_envelope
        """
        rules = _three_rules_env(api)

        first_page, first_meta = validate_paginated(
            api.list_rules(params={"limit": 2, "offset": 0}, headers=COORDINATOR_HEADERS)
        )
        assert len(first_page) == 2
        assert first_meta["total_count"] == 3
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0
        assert first_meta["has_more"] is True

        second_page, second_meta = validate_paginated(
            api.list_rules(params={"limit": 2, "offset": 2}, headers=COORDINATOR_HEADERS)
        )
        assert len(second_page) == 1
        assert second_meta["total_count"] == 3
        assert second_meta["offset"] == 2
        assert second_meta["has_more"] is False

        seen = [row["id"] for row in first_page] + [row["id"] for row in second_page]
        assert len(set(seen)) == 3
        assert set(seen) == {rule["id"] for rule in rules}

    def test_the_hazard_class_filter_reports_the_filtered_size_not_the_page_size(self, api):
        """PRD 3.1: "Rules may be listed with an optional `hazard_class` filter, and
        mappings may be listed filtered by `category_id`, `rule_id` or `mapping_state`."

        Design: Corner/entities/corner_entities_listing_applicable_rules_pagination_and_filter_envelope
        """
        _three_rules_env(api)
        rows, meta = validate_paginated(
            api.list_rules(params={"hazard_class": "PHTHALATES"}, headers=COORDINATOR_HEADERS)
        )
        assert meta["total_count"] == 1
        assert len(rows) == 1
        assert rows[0]["rule_code"] == "PHTHALATE_1000"
        assert meta["has_more"] is False

    def test_the_default_page_holds_the_whole_small_collection_in_created_at_order(self, api):
        """PRD 2.3: "Unless a specific endpoint states otherwise, list results are sorted by
        `created_at` ascending."

        Design: Corner/entities/corner_entities_listing_applicable_rules_pagination_and_filter_envelope
        """
        rules = _three_rules_env(api)
        rows, meta = validate_paginated(api.list_rules(headers=COORDINATOR_HEADERS))
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert [row["id"] for row in rows] == [rule["id"] for rule in rules]


class TestRequestShapeRejection:
    """A missing field and an out-of-enum value both fail before any lookup."""

    def test_a_missing_required_field_is_rejected_and_persists_nothing(self, api):
        """PRD 2.11: "Request shape — every required field present, every enum value inside
        its declared set, every regex-constrained string matching its pattern, every numeric
        field inside its declared range, and on list endpoints `limit` between 1 and 100
        inclusive with `offset` at least 0 → `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/corner_entities_required_fields_missing_and_unknown_enum_rejected_as_invalid_request
        """
        fx.set_clock(api, STARTUP_CLOCK)
        payload = dict(LEAD_RULE_INPUT)
        payload.pop("rule_code")
        validate_error(
            api.create_rule(payload, headers=ADMIN_HEADERS),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )
        _, meta = validate_paginated(api.list_rules(headers=COORDINATOR_HEADERS))
        assert meta["total_count"] == 0

    def test_a_value_outside_a_closed_enum_is_rejected(self, api):
        """PRD 3.1: "A **regulatory rule** is registered with a `rule_code` — an uppercase
        snake-case identifier of between 3 and 40 characters that must be unique across all
        rules — and a `hazard_class` drawn from `LEAD_PAINT`, `LEAD_CONTENT`, `PHTHALATES`,
        `MECHANICAL_HAZARD` or `FLAMMABILITY`."

        Design: Corner/entities/corner_entities_required_fields_missing_and_unknown_enum_rejected_as_invalid_request
        """
        fx.set_clock(api, STARTUP_CLOCK)
        validate_error(
            api.create_rule(
                dict(LEAD_RULE_INPUT, hazard_class="RADIOLOGICAL"), headers=ADMIN_HEADERS
            ),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )
        _, meta = validate_paginated(api.list_rules(headers=COORDINATOR_HEADERS))
        assert meta["total_count"] == 0

    def test_request_shape_answers_ahead_of_the_unresolvable_reference(self, api):
        """PRD 2.11: "Path and body reference existence — every resource named by a path
        segment or by a request-body foreign key exists, validated left to right across the
        path and then in declared body-field order, reporting the leftmost missing reference
        with that entity's own not-found code (404)."

        Design: Corner/entities/corner_entities_required_fields_missing_and_unknown_enum_rejected_as_invalid_request
        """
        fx.set_clock(api, STARTUP_CLOCK)
        payload = factories.product_payload(NON_EXISTENT_UUID)
        payload.pop("projected_annual_units")
        # The category cannot resolve either, but rank 5 answers ahead of rank 6.
        validate_error(
            api.create_product(payload, headers=ADMIN_HEADERS),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )
        _, meta = validate_paginated(api.list_products(headers=COORDINATOR_HEADERS))
        assert meta["total_count"] == 0


class TestOptionalInputDefaults:
    """Every optional input omitted in one sweep, across six entities."""

    def test_the_regulatory_library_supplies_its_two_declared_defaults(self, api):
        """PRD 3.1: "The rule carries its numeric ceiling or floor as `limit_value`, which
        must be at least 0, expressed in a `limit_unit` of `PPM`, `PERCENT_BY_WEIGHT`,
        `NEWTON` or `MILLIMETRE`, together with a `limit_comparator` of either `AT_OR_BELOW`
        or `AT_OR_ABOVE` that defaults to `AT_OR_BELOW` when the registrant omits it." and
        "`component_reliance_allowed` — a boolean defaulting to true — declares whether a
        supplier's component part certificate may stand in for finished-product testing of
        this rule; a rule that must be tested on the assembled product sets it false." and
        "The boolean `durable_infant_product`, defaulting to false, marks cots, high chairs,
        carriers and similar durable infant or toddler goods; setting it true doubles
        computed sample sizes, as §3.5 describes."

        Design: Corner/entities/corner_entities_defaults_applied_across_eleven_optional_inputs
        """
        fx.set_clock(api, STARTUP_CLOCK)
        rule_payload = factories.rule_payload()
        rule_payload.pop("limit_comparator")
        rule_payload.pop("component_reliance_allowed")
        rule = validate_success(api.create_rule(rule_payload, headers=ADMIN_HEADERS), 201)
        assert rule["limit_comparator"] == "AT_OR_BELOW"
        assert rule["component_reliance_allowed"] is True

        category_payload = factories.category_payload()
        category_payload.pop("durable_infant_product")
        category = validate_success(
            api.create_category(category_payload, headers=ADMIN_HEADERS), 201
        )
        assert category["durable_infant_product"] is False

    def test_the_party_register_starts_every_party_at_its_declared_floor(self, api):
        """PRD 3.2: "A newly registered laboratory begins with `operational_state` `ACTIVE`,
        `influence_attestation_state` `MISSING`, a null `influence_attestation_valid_through`,
        and both fee ledger counters — `billed_fee_cents_total` and
        `credited_fee_cents_total` — at 0." and "Its `reliance_agreement_state` may be
        supplied at registration and otherwise defaults to `NOT_ON_FILE`; only the value
        `ON_FILE` — meaning a signed component-part reliance agreement is held — permits the
        certifier to lean on that supplier's certificates."

        Design: Corner/entities/corner_entities_defaults_applied_across_eleven_optional_inputs
        """
        fx.set_clock(api, STARTUP_CLOCK)
        laboratory = fx.create_laboratory(api)
        assert laboratory["operational_state"] == "ACTIVE"
        assert laboratory["influence_attestation_state"] == "MISSING"
        assert laboratory["influence_attestation_valid_through"] is None
        assert laboratory["billed_fee_cents_total"] == 0
        assert laboratory["credited_fee_cents_total"] == 0

        supplier = fx.create_supplier(api)
        assert supplier["reliance_agreement_state"] == "NOT_ON_FILE"
        assert supplier["certificates_issued_count"] == 0

    def test_a_product_its_part_and_its_plan_all_fill_in_their_own_blanks(self, api):
        """PRD 3.3: "An optional `testing_budget_cents` sets the ceiling on how much
        outstanding laboratory invoicing this product may carry across its non-terminal
        orders; when omitted it defaults to 2,000,000 cents, which is to say twenty thousand
        dollars, and it must be at least 0." and "Two booleans complete the part:
        `accessible_to_child`, defaulting to true, states whether a child can reach the part
        during reasonably foreseeable use, and `small_part_when_detached`, defaulting to
        false, states whether the part fits the small-parts cylinder once detached." PRD
        3.5: "The plan also carries `resample_grace_days`, an integer between 0 and 365
        inclusive that defaults to 30, giving how long an unserviced resampling obligation
        may sit before the plan lapses."

        Design: Corner/entities/corner_entities_defaults_applied_across_eleven_optional_inputs
        """
        fx.set_clock(api, STARTUP_CLOCK)
        library = fx.regulatory_env(api)
        supplier = fx.create_supplier(api)

        product_payload = factories.product_payload(library["category"]["id"])
        product = validate_success(
            api.create_product(product_payload, headers=ADMIN_HEADERS), 201
        )
        assert product["testing_budget_cents"] == 2000000
        assert product["certification_state"] == "DRAFT"
        assert product["compliance_posture"] == "UNSCOPED"
        assert product["required_rule_ids"] == []
        assert product["risk_weighted_gap_score"] == 0

        part_payload = factories.component_part_payload(supplier["id"])
        part = validate_success(
            api.create_component_part(product["id"], part_payload, headers=ADMIN_HEADERS),
            201,
        )
        assert part["accessible_to_child"] is True
        assert part["small_part_when_detached"] is False
        assert part["reliance_status"] == "PENDING"
        assert part["last_material_change_at"] is None

        fx.submit_for_certification(api, product["id"], "FULL_PRODUCT_TEST")
        plan = validate_success(
            api.create_sampling_plan(
                product["id"], {"plan_type": "INITIAL"}, headers=COORDINATOR_HEADERS
            ),
            201,
        )
        assert plan["resample_grace_days"] == 30
        assert plan["baseline_units_produced"] == 0
        assert plan["plan_state"] == "DRAFT"
        assert plan["resample_trigger"] == "NONE"

    def test_an_order_and_a_batch_default_their_optional_flags_to_false(self, api):
        """PRD 3.6: "An optional `expedite_requested` boolean, defaulting to false, asks for
        expedited turnaround and feeds the pricing waterfall." PRD 3.8: "Three optional
        boolean label flags, each defaulting to false, are recorded at the same time:
        `label_on_product`, whether the permanent tracking label is affixed to the product
        itself; `label_on_packaging`, whether the label is printed on the packaging; and
        `label_batch_code_printed`, whether the `batch_code` itself appears in the label
        text."

        Design: Corner/entities/corner_entities_defaults_applied_across_eleven_optional_inputs
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.evidence_complete_env(api, measured_value=10)
        product = fx.get_product(api, env["product"]["id"])
        certificate = fx.draft_certificate(
            api, product["id"], product["version"], manufacture_date_month="2026-08"
        )
        order_payload = factories.test_order_payload(
            env["product"]["id"],
            env["plan"]["id"],
            env["laboratory"]["id"],
            env["rules"][0]["id"],
            sample_count=1,
            window_start="2026-08-21T00:00:00Z",
            window_end="2026-08-22T00:00:00Z",
        )
        assert "expedite_requested" not in order_payload
        order = validate_success(
            api.create_test_order(order_payload, headers=COORDINATOR_HEADERS), 201
        )
        assert order["expedite_requested"] is False
        assert order["is_retest"] is False
        assert order["order_state"] == "SCHEDULED"

        batch = validate_success(
            api.create_production_batch(
                product["id"],
                {
                    "certificate_id": certificate["id"],
                    "batch_code": "PLAINB-000401",
                    "produced_on": "2026-08-01T00:00:00Z",
                    "quantity": 100,
                },
                headers=MANAGER_HEADERS,
            ),
            201,
        )
        assert batch["label_on_product"] is False
        assert batch["label_on_packaging"] is False
        assert batch["label_batch_code_printed"] is False
        assert batch["tracking_label_compliant"] is False
        assert batch["distribution_state"] == "HELD"
        assert batch["release_rescind_count"] == 0
        assert batch["released_at"] is None


class TestServerOwnedComputedFields:
    """Values the server derives from other rows, never from the payload."""

    def test_the_accreditation_copies_its_method_key_from_the_named_rule(self, api):
        """PRD 3.2: "Each scope names the `rule_id` whose method it covers, and at creation
        the system copies that rule's `test_method_code` onto the accreditation record's own
        `test_method_code` — the scope key every later lookup uses."

        Design: Corner/entities/corner_entities_computed_fields_are_server_owned_and_ignore_client_supplied_values
        """
        fx.set_clock(api, STARTUP_CLOCK)
        rule = fx.create_rule(api, test_method_code="CPSC-CH-E1002-08")
        laboratory = fx.create_laboratory(api)
        created = fx.accredit(api, laboratory["id"], rule["id"])
        assert created["test_method_code"] == "CPSC-CH-E1002-08"
        assert created["accreditation_state"] == "ACCREDITED"
        assert created["suspension_reason"] is None
        assert created["fee_surcharge_basis_points"] == 0

        read = validate_success(
            api.get_accreditation(created["id"], headers=ADMIN_HEADERS)
        )
        assert read["test_method_code"] == rule["test_method_code"]

    def test_the_supplier_counter_and_the_certificate_owner_are_both_derived(self, api):
        """PRD 3.2: "The derived `certificates_issued_count` starts at 0 and tracks how many
        of the supplier's component part certificates are in `SUBMITTED` or `RELIED_UPON`:
        it rises by 1 when the supplier submits a certificate, and falls by 1 when a
        certificate is rejected or when a previously relied-upon certificate is voided." PRD
        3.4: "On acceptance the system copies the part's `supplier_id` onto the certificate,
        sets `reliance_state` to `SUBMITTED`, leaves `reliance_documentation_ref` and
        `reliance_recorded_by_user_id` null, and increments the supplier's
        `certificates_issued_count` by 1."

        Design: Corner/entities/corner_entities_computed_fields_are_server_owned_and_ignore_client_supplied_values
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.scoped_product_env(
            api,
            evidence_path="COMPONENT_RELIANCE",
            rule_specs=[{"component_reliance_allowed": True}],
            supplier={"reliance_agreement_state": "ON_FILE"},
        )
        before = fx.get_supplier(api, env["supplier"]["id"])
        assert before["certificates_issued_count"] == 0

        payload = factories.part_certificate_payload(
            env["laboratory"]["id"], env["rules"][0]["id"], measured_value=40
        )
        assert "supplier_id" not in payload
        certificate = validate_success(
            api.submit_part_certificate(
                env["parts"][0]["id"],
                payload,
                headers=make_supplier_user_headers(env["supplier"]["id"]),
            ),
            201,
        )
        assert certificate["supplier_id"] == env["supplier"]["id"]
        assert certificate["reliance_state"] == "SUBMITTED"
        assert certificate["reliance_documentation_ref"] is None
        assert certificate["reliance_recorded_by_user_id"] is None

        after = fx.get_supplier(api, env["supplier"]["id"])
        assert after["certificates_issued_count"] == 1

    def test_the_required_rule_set_stays_empty_until_scoping_derives_it(self, api):
        """PRD 3.3: "At registration the product's `certification_state` is `DRAFT`, its
        `compliance_posture` is `UNSCOPED`, and its `required_rule_ids` is the empty array —
        rule derivation deliberately does not run at registration, only at scoping."

        Design: Corner/entities/corner_entities_computed_fields_are_server_owned_and_ignore_client_supplied_values
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.scoped_product_env(api, submit=False)
        # The registration response is the moment PRD 3.3 speaks of; a later
        # component part addition legitimately re-derives the set while DRAFT.
        assert env["product"]["required_rule_ids"] == []
        drafted = fx.get_product(api, env["product"]["id"])
        assert drafted["certification_state"] == "DRAFT"

        scoped = fx.submit_for_certification(api, drafted["id"], "FULL_PRODUCT_TEST")
        assert scoped["required_rule_ids"] == [env["rules"][0]["id"]]
        assert scoped["certification_state"] == "FULL_TEST_PROGRAM"


LATER_CLOCK = "2026-08-03T00:00:00Z"


def _clock_shifted_order_env(api):
    """A plan activated at startup and an order booked before the clock moves on."""
    fx.set_clock(api, STARTUP_CLOCK)
    env = fx.booking_env(api, plan_overrides={"plan_type": "INITIAL"})
    env["order"] = fx.book_order(
        api,
        env["product"]["id"],
        env["plan"]["id"],
        env["laboratory"]["id"],
        env["rules"][0]["id"],
        sample_count=1,
        window_start="2026-08-02T00:00:00Z",
        window_end="2026-08-05T00:00:00Z",
    )
    # Snapshot the plan as it stands after the booking committed units against it
    # (PRD 3.6), so a later assertion isolates what the clock move alone changed.
    env["plan_before_clock_move"] = fx.get_plan(api, env["plan"]["id"])
    fx.set_clock(api, LATER_CLOCK)
    return env


class TestSystemFieldsStampedFromClockAndIdentity:
    """Request context, not sibling rows, fills these columns."""

    def test_the_activation_instant_survives_a_later_clock_move(self, api):
        """PRD 2.4: "Fields the server stamps from the logical clock rather than from the
        request include a plan's `activated_at` and `last_verified_at`, an order's
        `reported_at`, a batch's `released_at`, a certificate's `issued_at`, a part's
        `last_material_change_at`, and an event's `occurred_at`."

        Design: Corner/entities/corner_entities_system_fields_are_stamped_from_the_logical_clock_and_request_identity
        """
        env = _clock_shifted_order_env(api)
        assert env["plan"]["activated_at"] == STARTUP_CLOCK
        assert env["plan"]["last_verified_at"] == STARTUP_CLOCK

        # Moving the clock mutates no row, so the stamp cannot drift.
        after = fx.get_plan(api, env["plan"]["id"])
        assert after["activated_at"] == STARTUP_CLOCK
        assert after["version"] == env["plan_before_clock_move"]["version"]
        assert after["updated_at"] == env["plan_before_clock_move"]["updated_at"]

    def test_the_ordering_and_reporting_identities_come_from_the_header(self, api):
        """PRD 3.6: "On creation the order's `order_state` is `SCHEDULED`, its
        `ordered_by_user_id` is the acting `X-User-ID`, `is_retest` is false and
        `retest_case_id` is null; `measured_value`, `result`, `reported_at` and
        `reported_by_user_id` are all null." and "The laboratory submits a single
        `measured_value` — one representative measurement per order, with no aggregation
        across samples — and the system stores it together with `reported_at` from the
        logical clock and `reported_by_user_id` from the acting `X-User-ID`."

        Design: Corner/entities/corner_entities_system_fields_are_stamped_from_the_logical_clock_and_request_identity
        """
        env = _clock_shifted_order_env(api)
        lab_id = env["laboratory"]["id"]
        assert env["order"]["ordered_by_user_id"] == COORDINATOR_USER_ID
        assert env["order"]["reported_at"] is None
        assert env["order"]["reported_by_user_id"] is None

        fx.start_order(api, env["order"]["id"], lab_id)
        reported = fx.report(api, env["order"]["id"], lab_id, 40)
        assert reported["reported_at"] == LATER_CLOCK
        assert reported["reported_by_user_id"] == lab_id
        assert reported["ordered_by_user_id"] == COORDINATOR_USER_ID
        # Two days separate the activation stamp from the reporting stamp.
        assert reported["reported_at"] != env["plan"]["activated_at"]

    def test_the_event_log_stamps_the_clock_and_the_recording_administrator(self, api):
        """PRD 3.10: "On acceptance the event's `occurred_at` is stamped with the logical
        clock and `recorded_by_user_id` with the `X-User-ID` header value."

        Design: Corner/entities/corner_entities_system_fields_are_stamped_from_the_logical_clock_and_request_identity
        """
        env = _clock_shifted_order_env(api)
        event = fx.record_material_change(
            api,
            env["product"]["id"],
            subject_type="PRODUCT",
            change_kind="PACKAGING_ONLY",
            description="Retail carton artwork refreshed with no change to the goods.",
        )
        assert event["occurred_at"] == LATER_CLOCK
        assert event["recorded_by_user_id"] == ADMIN_USER_ID
        assert event["triggers_resample"] is False


class TestFieldRangeAndFormatConstraints:
    """Well-formed JSON of the right primitive type that still breaks its range."""

    def test_an_out_of_range_weight_and_a_sub_floor_sampling_minimum_are_refused(self, api):
        """PRD 3.1: "Finally, `severity_weight`, an integer between 1 and 10 inclusive, is
        the weight this rule contributes when the system measures how far a product's
        evidence falls short." and "A category carries a unique uppercase snake-case
        `category_code` of 3 to 40 characters, a human-readable `display_name` of 1 to 120
        characters, an `intended_age_max_months` between 0 and 168 inclusive marking the top
        of the intended-user age range, and a `sampling_floor_units` of at least 1 — the
        absolute minimum number of sample units any sampling plan for a product in this
        category may authorise."

        Design: Corner/entities/corner_entities_type_constraints_enum_closure_and_non_negative_integers
        """
        fx.set_clock(api, STARTUP_CLOCK)
        for weight in (-3, 0, 11):
            validate_error(
                api.create_rule(
                    factories.rule_payload(severity_weight=weight), headers=ADMIN_HEADERS
                ),
                ApiErrorId.INVALID_REQUEST.value,
                400,
            )
        _, meta = validate_paginated(api.list_rules(headers=COORDINATOR_HEADERS))
        assert meta["total_count"] == 0

        accepted = validate_success(
            api.create_rule(factories.rule_payload(severity_weight=1), headers=ADMIN_HEADERS),
            201,
        )
        assert accepted["severity_weight"] == 1

        validate_error(
            api.create_category(
                factories.category_payload(sampling_floor_units=-1), headers=ADMIN_HEADERS
            ),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )

    def test_a_zero_sample_count_is_below_the_declared_minimum(self, api):
        """PRD 3.6: "A `TestCoordinator` names the `product_id` under test, the
        `sampling_plan_id` whose authorised units the order will consume, the `laboratory_id`
        that will perform the work, the `rule_id` under test, a `sample_count` of at least 1,
        and a testing window running from `window_start` to `window_end`."

        Design: Corner/entities/corner_entities_type_constraints_enum_closure_and_non_negative_integers
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.booking_env(api, plan_overrides={"plan_type": "INITIAL"})
        payload = factories.test_order_payload(
            env["product"]["id"],
            env["plan"]["id"],
            env["laboratory"]["id"],
            env["rules"][0]["id"],
            sample_count=0,
        )
        validate_error(
            api.create_test_order(payload, headers=COORDINATOR_HEADERS),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )
        assert fx.list_orders_for_product(api, env["product"]["id"]) == []
        plan = fx.get_plan(api, env["plan"]["id"])
        assert plan["units_committed"] == 0

    def test_only_the_year_hyphen_month_form_of_the_manufacture_date_is_accepted(self, api):
        """PRD 3.7: "The content elements are `certifier_legal_name`, the legal name of the
        certifying party, 1 to 160 characters; `certifier_contact_email`, the recordkeeper's
        contact, 5 to 160 characters and required to contain an at-sign; `manufacture_place`,
        the place of manufacture, 1 to 120 characters; `manufacture_date_month`, the date of
        manufacture written as a four-digit year, a hyphen, and a two-digit month between 01
        and 12; and `testing_place`, the place where the supporting testing occurred, 1 to
        120 characters."

        Design: Corner/entities/corner_entities_type_constraints_enum_closure_and_non_negative_integers
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.evidence_complete_env(api, measured_value=10)
        product = fx.get_product(api, env["product"]["id"])

        validate_error(
            api.draft_certificate(
                product["id"],
                factories.certificate_payload(
                    product["version"], manufacture_date_month="August 2026"
                ),
                headers=OFFICER_HEADERS,
            ),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )
        _, meta = validate_paginated(
            api.list_certificates(
                params={"product_id": product["id"]}, headers=OFFICER_HEADERS
            )
        )
        assert meta["total_count"] == 0

        drafted = validate_success(
            api.draft_certificate(
                product["id"],
                factories.certificate_payload(
                    product["version"], manufacture_date_month="2026-08"
                ),
                headers=OFFICER_HEADERS,
            ),
            201,
        )
        assert drafted["manufacture_date_month"] == "2026-08"
        assert drafted["issuance_status"] == "DRAFT"


PACKAGING_NOTE = {
    "subject_type": "PRODUCT",
    "change_kind": "PACKAGING_ONLY",
    "description": "Outer carton switched to recycled board; goods unchanged.",
}


class TestMaterialChangeEventIsAppendOnly:
    """The one row shape in the model with no version and no mutator."""

    def test_the_event_row_carries_no_version_and_no_updated_at(self, api):
        """PRD 2.4: "There is one deliberate exception: a material change event is
        append-only evidence, so a `MaterialChangeEvent` row carries only `id` and
        `created_at` — it has no `updated_at`, no `version`, and no operation that updates
        it."

        Design: Corner/entities/corner_entities_material_change_event_is_append_only_with_no_version_column
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.scoped_product_env(api)
        event = fx.record_material_change(api, env["product"]["id"], **PACKAGING_NOTE)

        assert is_valid_uuid(event["id"])
        assert is_iso8601_timestamp(event["created_at"])
        assert "version" not in event
        assert "updated_at" not in event

        read = validate_success(api.get_material_change(event["id"], headers=ADMIN_HEADERS))
        assert read["id"] == event["id"]
        assert "version" not in read
        assert "updated_at" not in read

    def test_an_identical_second_payload_is_appended_rather_than_deduplicated(self, api):
        """PRD 3.10: "Recording the event always increments the product's
        `material_change_count` by 1, whichever way the resample decision falls."

        Design: Corner/entities/corner_entities_material_change_event_is_append_only_with_no_version_column
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.scoped_product_env(api)
        first = fx.record_material_change(api, env["product"]["id"], **PACKAGING_NOTE)
        second = fx.record_material_change(api, env["product"]["id"], **PACKAGING_NOTE)
        assert first["id"] != second["id"]
        assert first["occurred_at"] == STARTUP_CLOCK
        assert second["occurred_at"] == STARTUP_CLOCK

        rows, meta = validate_paginated(
            api.list_material_changes(
                params={"product_id": env["product"]["id"]}, headers=ADMIN_HEADERS
            )
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {first["id"], second["id"]}
        assert fx.get_product(api, env["product"]["id"])["material_change_count"] == 2


def _two_products_one_supplier_env(api):
    """Two sibling products under one category, sharing one part supplier."""
    fx.set_clock(api, STARTUP_CLOCK)
    category = fx.create_category(api)
    supplier = fx.create_supplier(api)
    alpha = fx.create_product(api, category["id"])
    beta = fx.create_product(api, category["id"])
    return {
        "category": category,
        "supplier": supplier,
        "alpha": alpha,
        "beta": beta,
    }


class TestChildCreationIsScopedByThePathParent:
    """The parent id arrives in the route and never in the payload."""

    def test_each_part_takes_its_product_from_the_path_it_was_posted_to(self, api):
        """PRD 3.3: "The **bill of materials** is built one component part at a time, each
        part naming the `supplier_id` that manufactures it, a `part_name` of 1 to 120
        characters as it appears in the bill of materials, and a `material_class` of
        `PAINTED_COATING`, `PLASTICIZED_PLASTIC`, `ACCESSIBLE_METAL`, `TEXTILE` or
        `RIGID_UNPAINTED_PLASTIC`."

        Design: Corner/entities/corner_entities_parent_relationships_child_creation_is_scoped_by_path_parent
        """
        env = _two_products_one_supplier_env(api)
        payload = factories.component_part_payload(env["supplier"]["id"], part_name="Shell")
        assert "product_id" not in payload

        alpha_shell = validate_success(
            api.create_component_part(env["alpha"]["id"], payload, headers=ADMIN_HEADERS),
            201,
        )
        beta_shell = validate_success(
            api.create_component_part(
                env["beta"]["id"],
                factories.component_part_payload(env["supplier"]["id"], part_name="Shell"),
                headers=ADMIN_HEADERS,
            ),
            201,
        )
        assert alpha_shell["product_id"] == env["alpha"]["id"]
        assert beta_shell["product_id"] == env["beta"]["id"]
        assert alpha_shell["supplier_id"] == env["supplier"]["id"]

    def test_the_filtered_child_list_is_the_reverse_path_from_either_parent(self, api):
        """PRD 3.3: "Parts may be listed filtered by `product_id`, `supplier_id` and
        `reliance_status`."

        Design: Corner/entities/corner_entities_parent_relationships_child_creation_is_scoped_by_path_parent
        """
        env = _two_products_one_supplier_env(api)
        for part_name in ("Moulded shell", "Handlebar grip"):
            fx.add_part(api, env["alpha"]["id"], env["supplier"]["id"], part_name=part_name)
        fx.add_part(api, env["beta"]["id"], env["supplier"]["id"], part_name="Moulded shell")

        _, alpha_meta = validate_paginated(
            api.list_component_parts(
                params={"product_id": env["alpha"]["id"]}, headers=ADMIN_HEADERS
            )
        )
        assert alpha_meta["total_count"] == 2

        _, beta_meta = validate_paginated(
            api.list_component_parts(
                params={"product_id": env["beta"]["id"]}, headers=ADMIN_HEADERS
            )
        )
        assert beta_meta["total_count"] == 1

        _, supplier_meta = validate_paginated(
            api.list_component_parts(
                params={"supplier_id": env["supplier"]["id"]}, headers=ADMIN_HEADERS
            )
        )
        assert supplier_meta["total_count"] == 3

    def test_the_category_reaches_both_of_its_products_through_the_product_list(self, api):
        """PRD 4: "Lists products, filterable by category, certification state and compliance
        posture."

        Design: Corner/entities/corner_entities_parent_relationships_child_creation_is_scoped_by_path_parent
        """
        env = _two_products_one_supplier_env(api)
        rows, meta = validate_paginated(
            api.list_products(
                params={"category_id": env["category"]["id"]}, headers=COORDINATOR_HEADERS
            )
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {env["alpha"]["id"], env["beta"]["id"]}


class TestCategoryRuleMappingIsAJunctionRow:
    """Unique on the pair, traversable from either end."""

    def test_the_pair_is_unique_even_when_the_predicate_differs(self, api):
        """PRD 3.1: "Attempting to create a second `ACTIVE` mapping for a category-and-rule
        pair that already has one is refused with `ERR_MAPPING_DUPLICATE`."

        Design: Corner/entities/corner_entities_category_rule_mapping_is_a_junction_row_unique_on_its_pair
        """
        fx.set_clock(api, STARTUP_CLOCK)
        lead = fx.create_rule(api, hazard_class="LEAD_CONTENT")
        toy = fx.create_category(api)

        mapping = fx.map_rule(api, toy["id"], lead["id"], applicability_condition="ALWAYS")
        assert mapping["mapping_state"] == "ACTIVE"
        assert mapping["category_id"] == toy["id"]
        assert mapping["rule_id"] == lead["id"]

        validate_error(
            api.create_mapping(
                factories.mapping_payload(
                    toy["id"], lead["id"], applicability_condition="IF_PAINTED_SURFACE"
                ),
                headers=ADMIN_HEADERS,
            ),
            ApiErrorId.MAPPING_DUPLICATE.value,
            409,
        )
        _, meta = validate_paginated(
            api.list_mappings(params={"category_id": toy["id"]}, headers=ADMIN_HEADERS)
        )
        assert meta["total_count"] == 1

    def test_the_junction_is_traversable_from_the_category_and_from_the_rule(self, api):
        """PRD 3.1: "Rules may be listed with an optional `hazard_class` filter, and mappings
        may be listed filtered by `category_id`, `rule_id` or `mapping_state`."

        Design: Corner/entities/corner_entities_category_rule_mapping_is_a_junction_row_unique_on_its_pair
        """
        fx.set_clock(api, STARTUP_CLOCK)
        lead = fx.create_rule(api, hazard_class="LEAD_CONTENT")
        phthalate = fx.create_rule(api, hazard_class="PHTHALATES")
        toy = fx.create_category(api)
        crib = fx.create_category(api)

        fx.map_rule(api, toy["id"], lead["id"], applicability_condition="ALWAYS")
        fx.map_rule(
            api, toy["id"], phthalate["id"], applicability_condition="IF_PLASTICIZED_PART"
        )
        fx.map_rule(api, crib["id"], lead["id"], applicability_condition="ALWAYS")

        _, by_category = validate_paginated(
            api.list_mappings(params={"category_id": toy["id"]}, headers=ADMIN_HEADERS)
        )
        assert by_category["total_count"] == 2

        _, by_rule = validate_paginated(
            api.list_mappings(params={"rule_id": lead["id"]}, headers=ADMIN_HEADERS)
        )
        assert by_rule["total_count"] == 2

        _, by_state = validate_paginated(
            api.list_mappings(params={"mapping_state": "ACTIVE"}, headers=ADMIN_HEADERS)
        )
        assert by_state["total_count"] == 3


class TestCertificateSupersessionLinkIsServerComputed:
    """The one self-referential edge, null while the product holds no issued row."""

    def test_the_first_certificate_of_a_product_points_nowhere(self, api):
        """PRD 3.7: "`supersedes_certificate_id` is set to the `id` of the product's
        currently issued certificate, or null when the product has none — this is the
        self-referential link that makes certificate history traceable."

        Design: Corner/entities/corner_entities_certificate_supersession_chain_is_a_single_parent_acyclic_link
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.evidence_complete_env(api, measured_value=10)
        product = fx.get_product(api, env["product"]["id"])
        payload = factories.certificate_payload(
            product["version"], manufacture_date_month="2026-08"
        )
        assert "supersedes_certificate_id" not in payload

        first = validate_success(
            api.draft_certificate(product["id"], payload, headers=OFFICER_HEADERS), 201
        )
        assert first["supersedes_certificate_id"] is None

        issued = fx.issue_certificate(api, first["id"])
        assert issued["issuance_status"] == "ISSUED"
        assert issued["supersedes_certificate_id"] is None

        _, meta = validate_paginated(
            api.list_certificates(
                params={"product_id": product["id"]}, headers=OFFICER_HEADERS
            )
        )
        assert meta["total_count"] == 1

    def test_a_replacement_drafted_after_a_void_still_points_nowhere(self, api):
        """PRD 3.7: "A certificate that was never issued may instead be **voided**, moving
        `DRAFT → VOIDED` with its `version` incremented by 1 and no effect whatsoever on the
        product, which stays in `EVIDENCE_COMPLETE`."

        Design: Corner/entities/corner_entities_certificate_supersession_chain_is_a_single_parent_acyclic_link
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.evidence_complete_env(api, measured_value=10)
        product = fx.get_product(api, env["product"]["id"])
        first = fx.draft_certificate(
            api, product["id"], product["version"], manufacture_date_month="2026-08"
        )
        voided = fx.void_certificate(api, first["id"])
        assert voided["issuance_status"] == "VOIDED"
        assert voided["supersedes_certificate_id"] is None
        assert fx.get_product(api, product["id"])["certification_state"] == "EVIDENCE_COMPLETE"

        refreshed = fx.get_product(api, product["id"])
        replacement = fx.draft_certificate(
            api, refreshed["id"], refreshed["version"], manufacture_date_month="2026-08"
        )
        assert replacement["id"] != first["id"]
        assert replacement["supersedes_certificate_id"] is None
        assert fx.get_certificate(api, first["id"])["supersedes_certificate_id"] is None


def _two_products_with_parts_env(api):
    """Two products under one category, each carrying one component part."""
    env = _two_products_one_supplier_env(api)
    env["part_alpha"] = fx.add_part(
        api, env["alpha"]["id"], env["supplier"]["id"], part_name="Moulded shell"
    )
    env["part_beta"] = fx.add_part(
        api, env["beta"]["id"], env["supplier"]["id"], part_name="Moulded shell"
    )
    return env


class TestMaterialChangeSubjectDiscriminator:
    """The polymorphic pairing is checked in both directions and against the graph."""

    def test_a_part_subject_without_a_part_and_with_a_foreign_part_are_both_refused(
        self, api
    ):
        """PRD 3.10: "When `subject_type` is `COMPONENT_PART`, `component_part_id` must be
        supplied and the named part's `product_id` must equal the submitted `product_id`;
        when `subject_type` is `PRODUCT`, `component_part_id` must be omitted or null."

        Design: Corner/entities/corner_entities_material_change_event_polymorphic_subject_requires_matching_part
        """
        env = _two_products_with_parts_env(api)
        validate_error(
            api.record_material_change(
                factories.material_change_payload(
                    env["alpha"]["id"],
                    subject_type="COMPONENT_PART",
                    change_kind="SUPPLIER_SWITCH",
                ),
                headers=ADMIN_HEADERS,
            ),
            ApiErrorId.PART_SUBJECT_MISMATCH.value,
            422,
        )
        validate_error(
            api.record_material_change(
                factories.material_change_payload(
                    env["alpha"]["id"],
                    subject_type="COMPONENT_PART",
                    change_kind="SUPPLIER_SWITCH",
                    component_part_id=env["part_beta"]["id"],
                ),
                headers=ADMIN_HEADERS,
            ),
            ApiErrorId.PART_SUBJECT_MISMATCH.value,
            422,
        )

    def test_a_product_subject_that_names_a_part_anyway_is_refused(self, api):
        """PRD 3.10: "Either violation — a part event with no part, a part belonging to a
        different product, or a product event that nonetheless names a part — is refused with
        `ERR_PART_SUBJECT_MISMATCH`."

        Design: Corner/entities/corner_entities_material_change_event_polymorphic_subject_requires_matching_part
        """
        env = _two_products_with_parts_env(api)
        validate_error(
            api.record_material_change(
                factories.material_change_payload(
                    env["alpha"]["id"],
                    subject_type="PRODUCT",
                    change_kind="PACKAGING_ONLY",
                    component_part_id=env["part_alpha"]["id"],
                ),
                headers=ADMIN_HEADERS,
            ),
            ApiErrorId.PART_SUBJECT_MISMATCH.value,
            422,
        )
        assert fx.get_product(api, env["alpha"]["id"])["material_change_count"] == 0

    def test_the_well_formed_part_event_is_the_only_one_appended(self, api):
        """PRD 3.10: "Recording the event always increments the product's
        `material_change_count` by 1, whichever way the resample decision falls."

        Design: Corner/entities/corner_entities_material_change_event_polymorphic_subject_requires_matching_part
        """
        env = _two_products_with_parts_env(api)
        for payload in (
            factories.material_change_payload(
                env["alpha"]["id"],
                subject_type="COMPONENT_PART",
                change_kind="SUPPLIER_SWITCH",
            ),
            factories.material_change_payload(
                env["alpha"]["id"],
                subject_type="PRODUCT",
                change_kind="PACKAGING_ONLY",
                component_part_id=env["part_alpha"]["id"],
            ),
        ):
            api.record_material_change(payload, headers=ADMIN_HEADERS)

        accepted = validate_success(
            api.record_material_change(
                factories.material_change_payload(
                    env["alpha"]["id"],
                    subject_type="COMPONENT_PART",
                    change_kind="SUPPLIER_SWITCH",
                    component_part_id=env["part_alpha"]["id"],
                ),
                headers=ADMIN_HEADERS,
            ),
            201,
        )
        assert accepted["subject_type"] == "COMPONENT_PART"
        assert accepted["component_part_id"] == env["part_alpha"]["id"]
        assert fx.get_product(api, env["alpha"]["id"])["material_change_count"] == 1


class TestNotFoundCodesAreEntitySpecific:
    """One unknown id, four read paths, four distinct codes."""

    def test_each_read_path_answers_with_its_own_entity_code(self, api):
        """PRD 2.5: "A missing regulatory rule reference — whether a rule path segment or a
        body `rule_id` — yields `ERR_RULE_NOT_FOUND`." and "A missing test order yields
        `ERR_TEST_ORDER_NOT_FOUND`." and "A missing material change event yields
        `ERR_MATERIAL_CHANGE_EVENT_NOT_FOUND`."

        Design: Corner/entities/corner_entities_not_found_returns_the_entity_specific_code_for_each_read_path
        """
        fx.set_clock(api, STARTUP_CLOCK)
        validate_error(
            api.get_rule(NON_EXISTENT_UUID, headers=ADMIN_HEADERS),
            ApiErrorId.RULE_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.get_product(NON_EXISTENT_UUID, headers=ADMIN_HEADERS),
            ApiErrorId.PRODUCT_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.get_test_order(NON_EXISTENT_UUID, headers=ADMIN_HEADERS),
            ApiErrorId.TEST_ORDER_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.get_material_change(NON_EXISTENT_UUID, headers=ADMIN_HEADERS),
            ApiErrorId.MATERIAL_CHANGE_EVENT_NOT_FOUND.value,
            404,
        )

    def test_an_empty_collection_is_not_a_not_found_condition(self, api):
        """PRD 2.3: "List responses carry four pagination fields inside `meta`: the echoed
        `limit`, the echoed `offset`, `total_count` giving the number of rows matching the
        filter before pagination is applied, and `has_more`, which is true exactly when rows
        remain beyond the current page."

        Design: Corner/entities/corner_entities_not_found_returns_the_entity_specific_code_for_each_read_path
        """
        fx.set_clock(api, STARTUP_CLOCK)
        for response in (
            api.list_rules(headers=ADMIN_HEADERS),
            api.list_products(headers=ADMIN_HEADERS),
            api.list_test_orders(headers=ADMIN_HEADERS),
            api.list_material_changes(headers=ADMIN_HEADERS),
        ):
            rows, meta = validate_paginated(response)
            assert rows == []
            assert meta["total_count"] == 0
            assert meta["has_more"] is False
