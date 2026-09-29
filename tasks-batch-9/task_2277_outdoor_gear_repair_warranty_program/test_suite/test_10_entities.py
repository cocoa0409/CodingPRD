"""Entity-level breadth: envelopes, defaults, derived fields, 404 vocabulary and integrity.

One test per corner of the entity surface the PRD declares — the creation
envelope and its derived defaults (§2.2, §3.1), the read and list contracts
(§2.3, §2.12), the per-registry not-found vocabulary and body-FK resolution
(§2.11), request-shape rejection (§2.11 check 9), server-computed fields that
ignore client input (§2.5, §2.8, §3.2), the immutable bench record (§2.5) and
the cross-registry integrity rules (§2.11 checks 25, 29 and 45).
"""

from test_helpers import (
    ERR_CLAIM_NOT_FOUND,
    ERR_CUSTOMER_NOT_FOUND,
    ERR_EMAIL_TAKEN,
    ERR_EMPLOYEE_CODE_TAKEN,
    ERR_ESTIMATE_NOT_FOUND,
    ERR_GEAR_ITEM_NOT_FOUND,
    ERR_GEAR_MODEL_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_MODEL_CODE_TAKEN,
    ERR_PART_CODE_TAKEN,
    ERR_PART_LOT_NOT_FOUND,
    ERR_REPAIR_ORDER_NOT_FOUND,
    ERR_RESERVATION_NOT_FOUND,
    ERR_SERIAL_ALREADY_REGISTERED,
    ERR_SERVICE_CENTER_NOT_FOUND,
    ERR_SUCCESSOR_CYCLE,
    ERR_TECHNICIAN_CENTER_MISMATCH,
    ERR_TECHNICIAN_NOT_FOUND,
    ERR_WORK_BLOCK_NOT_FOUND,
    ERR_ASSESSMENT_NOT_FOUND,
    NON_EXISTENT_UUID,
    PARTS_COORDINATOR_HEADERS,
    PROGRAM_ADMIN_HEADERS,
    SERVICE_AGENT_HEADERS,
    assert_common_fields,
    assert_immutable_common_fields,
    assert_money_cents,
    assert_multiplier,
    assert_part_lot_counts,
    assert_pct,
    assert_sorted_by_created_at,
    assert_timestamp_millis,
    factories,
    validate_error,
    validate_paginated,
    validate_success,
)


# ==========================================================================
# Creation envelopes, declared defaults and server-minted system fields
# ==========================================================================
class TestCreationDefaults:
    def test_service_center_creation_returns_envelope_with_derived_defaults(
        self, api, scenario, admin_headers
    ):
        """A centre created from the three required inputs comes back 201 with every rollup at zero.

        "A **service centre** is registered with a display `name` of one to one hundred and twenty non-blank characters, an uppercase `region_code` of two to eight characters, a `liability_cap_cents` of at least one cent, and optionally a `bench_capacity_blocks_per_day` between 1 and 200 that defaults to 24 when omitted."
        "A freshly registered centre starts with `open_liability_cents` at 0, `liability_utilization_pct` at 0, `liability_posture` at `OPEN`, `active_queue_depth` at 0 and `current_surge_multiplier` at 1.0; its `breached_commitment_count` is 0 and its `last_queue_review_at` is null until the first checkpoint runs."
        "Almost every resource additionally carries `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an integer that starts at 1 and increments by one on every mutation of that row."
        "Every resource also carries a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits, recording the logical-clock instant at which the row was inserted."

        Design: Corner/entities/service_center_creation_returns_envelope_with_derived_defaults
        """
        scenario.set_clock("2026-06-15T09:00:00Z")

        center = validate_success(
            api.create_service_center(
                factories.service_center_payload(
                    name="Cascade Service Hub",
                    region_code="US-OR",
                    liability_cap_cents=5000000,
                    bench_capacity_blocks_per_day=factories.OMIT,
                ),
                admin_headers,
            ),
            201,
        )

        assert center["name"] == "Cascade Service Hub"
        assert center["region_code"] == "US-OR"
        assert center["liability_cap_cents"] == 5000000
        assert center["bench_capacity_blocks_per_day"] == 24

        assert center["open_liability_cents"] == 0
        assert_pct(center["liability_utilization_pct"], 0.00)
        assert center["liability_posture"] == "OPEN"
        assert center["active_queue_depth"] == 0
        assert_multiplier(center["current_surge_multiplier"], 1.00)
        assert center["breached_commitment_count"] == 0
        assert center["last_queue_review_at"] is None

        assert_common_fields(center, expected_version=1)
        assert_timestamp_millis(center["created_at"])
        assert center["created_at"].startswith("2026-06-15T09:00:00")

    def test_part_lot_defaults_applied_when_optional_fields_omitted(
        self, api, scenario, parts_headers
    ):
        """Omitting the three optional lot fields defaults watermark 2, substitution off, null substitute code.

        "Optionally it carries a `low_watermark_units` of zero or more that defaults to 2, a `substitution_allowed` flag that defaults to false, and a `substitute_for_part_code` naming the discontinued part code this lot stands in for, which stays null unless `substitution_allowed` is true."
        "The new lot begins with `reserved_units` at 0, `available_units` equal to `on_hand_units` and a derived `status`, and it re-derives `parts_support_status` both for its own model and for any model whose successor its model is."
        "It is `DEPLETED` when `available_units` is zero; `LOW` when `available_units` is at least one and at most `low_watermark_units`; and `AVAILABLE` otherwise."
        "That model-level field is `SUPPORTED` when some part lot for the model has a `status` of `AVAILABLE` or `LOW`."

        Design: Corner/entities/part_lot_defaults_applied_when_optional_fields_omitted
        """
        scenario.set_clock("2026-06-15T09:00:00Z")
        model = scenario.model()

        lot = validate_success(
            api.create_part_lot(
                {
                    "gear_model_id": model["id"],
                    "part_code": "AS2-FLOOR-PANEL",
                    "part_kind": "FABRIC_PANEL",
                    "on_hand_units": 4,
                    "unit_price_cents": 4200,
                },
                parts_headers,
            ),
            201,
        )

        assert lot["low_watermark_units"] == 2
        assert lot["substitution_allowed"] is False
        assert lot["substitute_for_part_code"] is None
        assert_part_lot_counts(
            lot, on_hand_units=4, reserved_units=0, available_units=4, status="AVAILABLE"
        )

        refreshed_model = scenario.read_model(model["id"])
        assert refreshed_model["parts_support_status"] == "SUPPORTED"

    def test_technician_system_fields_generated_input_ignored(
        self, api, scenario, admin_headers
    ):
        """id, created_at, version and the minute counters are server-minted, never taken from the body.

        "Every resource in this system is addressed by an `id`, which is a server-minted UUID carrying no type prefix."
        "Every resource also carries a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits, recording the logical-clock instant at which the row was inserted."
        "New technicians start with `scheduled_minutes_open` and `completed_minutes` both at 0."
        "A roster `status` may be supplied and otherwise defaults to `ACTIVE`; the other admissible values are `ON_LEAVE` and `INACTIVE`, and only an `ACTIVE` technician may take assessments or work blocks."

        Design: Corner/entities/technician_system_fields_generated_input_ignored
        """
        scenario.set_clock("2026-06-15T09:00:00Z")
        center = scenario.center()

        planted_id = "deadbeef-0000-4000-8000-000000000000"
        technician = validate_success(
            api.create_technician(
                {
                    "service_center_id": center["id"],
                    "employee_code": "T-101",
                    "full_name": "Ines Park",
                    "certifications": [{"work_type": "FABRIC", "level": 3}],
                    "id": planted_id,
                    "version": 99,
                    "created_at": "2001-01-01T00:00:00Z",
                    "scheduled_minutes_open": 500,
                    "completed_minutes": 500,
                },
                admin_headers,
            ),
            201,
        )

        assert_common_fields(technician, expected_version=1)
        assert technician["id"] != planted_id
        assert technician["created_at"].startswith("2026-06-15T09:00:00")
        assert technician["updated_at"].startswith("2026-06-15T09:00:00")
        assert_timestamp_millis(technician["created_at"])
        assert_timestamp_millis(technician["updated_at"])

        assert technician["scheduled_minutes_open"] == 0
        assert technician["completed_minutes"] == 0
        assert technician["status"] == "ACTIVE"
        assert technician["certifications"] == [{"work_type": "FABRIC", "level": 3}]


# ==========================================================================
# Reads and listings
# ==========================================================================
class TestReadsAndListings:
    def test_gear_model_retrieval_returns_stored_row(self, api, scenario, agent_headers):
        """Reading a model echoes its stored inputs and reports NO_SUPPORT while no lot is stocked.

        "A model is created with a `model_code` of three to thirty-two characters drawn from uppercase letters, digits and hyphens and unique across the catalogue; a marketing `name`; a `category` drawn from `SHELL_APPAREL`, `INSULATION`, `TENT_SHELTER`, `PACK_HARNESS` and `HARDGOODS_FRAME`; an `msrp_cents` of at least one cent; a `release_year` between 2000 and 2100; and a `warranty_years` between 0 and 30 stating limited coverage in whole years from purchase."
        "A `lifetime_warranty` boolean defaults to false; when true the model carries coverage that never lapses and earns a bonus on its repair cap."
        "A new model begins with `parts_support_status` at `NO_SUPPORT`, because no lot has been stocked for it yet, with `repairability_flag` at `NONE`, and with its three feedback counters — `defect_claim_count`, `wear_denial_count` and `irreparable_count` — all at 0."

        Design: Corner/entities/gear_model_retrieval_returns_stored_row
        """
        scenario.set_clock("2026-06-15T09:00:00Z")
        created = scenario.model(
            model_code="TNT-ASCENT-2",
            name="Ascent 2P Tent",
            category="TENT_SHELTER",
            msrp_cents=79900,
            release_year=2019,
            warranty_years=5,
        )

        model = validate_success(api.get_gear_model(created["id"], agent_headers))

        assert model["id"] == created["id"]
        assert model["model_code"] == "TNT-ASCENT-2"
        assert model["name"] == "Ascent 2P Tent"
        assert model["category"] == "TENT_SHELTER"
        assert model["msrp_cents"] == 79900
        assert model["release_year"] == 2019
        assert model["warranty_years"] == 5

        assert model["lifetime_warranty"] is False
        assert model["discontinued_at"] is None
        assert model["successor_model_id"] is None

        assert model["parts_support_status"] == "NO_SUPPORT"
        assert model["defect_claim_count"] == 0
        assert model["wear_denial_count"] == 0
        assert model["irreparable_count"] == 0
        assert model["repairability_flag"] == "NONE"
        assert_common_fields(model)

    def test_gear_items_listing_filters_and_paginates(self, api, scenario, agent_headers):
        """The filtered unit list counts the filtered set and pages it created_at ascending.

        "Unless a specific endpoint says otherwise, every list endpoint returns its rows sorted by `created_at` in ascending order."
        "List responses carry `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope."
        "Reverse reachability is otherwise provided by query filters on the flat collections: `service_center_id`, `gear_item_id`, `gear_model_id`, `owner_customer_id`, `warranty_claim_id`, `repair_order_id`, `part_lot_id`, `technician_id`, `assessor_technician_id` and `successor_model_id` are all available as list filters, alongside the status-shaped filters `status`, `work_status`, `billing_status`, `disposition_status`, `warranty_state`, `parts_support_status`, `repairability_flag`, `commitment_breached`, `decision`, `intake_kind`, `determination`, `is_superseded`, `variant`, `basis`, `category`, `part_kind` and `work_type`."
        "A new customer starts with `lifetime_claim_count` and `trade_in_credit_cents` at 0."

        Design: Corner/entities/gear_items_listing_filters_and_paginates
        """
        scenario.set_clock("2026-06-15T09:00:00Z")
        model = scenario.model()
        customer = scenario.customer()

        item_a = scenario.gear_item(model["id"], customer["id"], serial_number="AS2-00417")
        scenario.set_clock("2026-06-15T09:05:00Z")
        item_b = scenario.gear_item(model["id"], customer["id"], serial_number="AS2-00418")
        scenario.set_clock("2026-06-15T09:10:00Z")
        scenario.gear_item(model["id"], customer["id"], serial_number="AS2-00419")

        rows, meta = validate_paginated(
            api.list_gear_items(
                agent_headers,
                owner_customer_id=customer["id"],
                disposition_status="WITH_CUSTOMER",
                limit=2,
                offset=0,
            )
        )

        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2
        assert meta["offset"] == 0
        assert len(rows) == 2
        assert_sorted_by_created_at(rows)
        assert [row["id"] for row in rows] == [item_a["id"], item_b["id"]]
        for row in rows:
            assert row["disposition_status"] == "WITH_CUSTOMER"
            assert row["owner_customer_id"] == customer["id"]

        assert scenario.read_customer(customer["id"])["lifetime_claim_count"] == 0


# ==========================================================================
# The per-registry 404 vocabulary and body-supplied foreign references
# ==========================================================================
class TestNotFoundVocabulary:
    def test_repair_order_read_with_unknown_id_not_found(
        self, api, scenario, agent_headers
    ):
        """An unregistered but well-formed order id answers the order's own not-found code.

        "(6) Every identifier in the URL path resolves, validated left to right, so that the leftmost unresolvable segment is the one reported."
        "The identifier-specific codes are `ERR_SERVICE_CENTER_NOT_FOUND`, `ERR_GEAR_MODEL_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_GEAR_ITEM_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_TECHNICIAN_NOT_FOUND`, `ERR_REPAIR_ORDER_NOT_FOUND`, `ERR_ESTIMATE_NOT_FOUND`, `ERR_PART_LOT_NOT_FOUND`, `ERR_RESERVATION_NOT_FOUND` and `ERR_WORK_BLOCK_NOT_FOUND`, all HTTP 404."

        Design: Corner/entities/repair_order_read_with_unknown_id_not_found
        """
        scenario.set_clock("2026-06-15T09:00:00Z")

        response = api.get_repair_order(NON_EXISTENT_UUID, agent_headers)

        validate_error(response, ERR_REPAIR_ORDER_NOT_FOUND)

    def test_path_ids_across_registries_not_found(self, api, scenario):
        """Every registry answers with its own 404 identifier rather than one generic code.

        "(6) Every identifier in the URL path resolves, validated left to right, so that the leftmost unresolvable segment is the one reported."
        "The identifier-specific codes are `ERR_SERVICE_CENTER_NOT_FOUND`, `ERR_GEAR_MODEL_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_GEAR_ITEM_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_TECHNICIAN_NOT_FOUND`, `ERR_REPAIR_ORDER_NOT_FOUND`, `ERR_ESTIMATE_NOT_FOUND`, `ERR_PART_LOT_NOT_FOUND`, `ERR_RESERVATION_NOT_FOUND` and `ERR_WORK_BLOCK_NOT_FOUND`, all HTTP 404."

        Design: Corner/entities/path_ids_across_registries_not_found
        """
        scenario.set_clock("2026-06-15T09:00:00Z")

        probes = [
            (
                api.get_service_center(
                    "00000000-0000-4000-8000-000000000001", PROGRAM_ADMIN_HEADERS
                ),
                ERR_SERVICE_CENTER_NOT_FOUND,
            ),
            (
                api.get_gear_model(
                    "00000000-0000-4000-8000-000000000002", PROGRAM_ADMIN_HEADERS
                ),
                ERR_GEAR_MODEL_NOT_FOUND,
            ),
            (
                api.get_customer(
                    "00000000-0000-4000-8000-000000000003", SERVICE_AGENT_HEADERS
                ),
                ERR_CUSTOMER_NOT_FOUND,
            ),
            (
                api.get_gear_item(
                    "00000000-0000-4000-8000-000000000004", SERVICE_AGENT_HEADERS
                ),
                ERR_GEAR_ITEM_NOT_FOUND,
            ),
            (
                api.get_warranty_claim(
                    "00000000-0000-4000-8000-000000000005", SERVICE_AGENT_HEADERS
                ),
                ERR_CLAIM_NOT_FOUND,
            ),
            (
                api.get_claim_assessment(
                    "00000000-0000-4000-8000-000000000006", SERVICE_AGENT_HEADERS
                ),
                ERR_ASSESSMENT_NOT_FOUND,
            ),
            (
                api.get_technician(
                    "00000000-0000-4000-8000-000000000007", PROGRAM_ADMIN_HEADERS
                ),
                ERR_TECHNICIAN_NOT_FOUND,
            ),
            (
                api.get_estimate(
                    "00000000-0000-4000-8000-000000000008", SERVICE_AGENT_HEADERS
                ),
                ERR_ESTIMATE_NOT_FOUND,
            ),
            (
                api.get_part_lot(
                    "00000000-0000-4000-8000-000000000009", PARTS_COORDINATOR_HEADERS
                ),
                ERR_PART_LOT_NOT_FOUND,
            ),
            (
                api.get_parts_reservation(
                    "00000000-0000-4000-8000-00000000000a", PARTS_COORDINATOR_HEADERS
                ),
                ERR_RESERVATION_NOT_FOUND,
            ),
            (
                api.get_work_block(
                    "00000000-0000-4000-8000-00000000000b", SERVICE_AGENT_HEADERS
                ),
                ERR_WORK_BLOCK_NOT_FOUND,
            ),
        ]

        for response, expected_error_id in probes:
            validate_error(response, expected_error_id)

    def test_gear_item_parent_model_must_exist_not_found(
        self, api, scenario, agent_headers
    ):
        """A body-supplied gear_model_id that resolves to nothing is a 404, not a shape error.

        "(7) Every foreign reference supplied in a request body resolves — `service_center_id`, `gear_item_id`, `gear_model_id`, `owner_customer_id`, `warranty_claim_id`, `repair_order_id` and `successor_model_id` — reported with the corresponding not-found code; this applies to unit registration, claim intake, repair-order creation, technician registration, part-lot stocking and the catalogue-model patch."

        Design: Corner/entities/gear_item_parent_model_must_exist_not_found
        """
        scenario.set_clock("2026-06-15T09:00:00Z")
        customer = scenario.customer()

        response = api.create_gear_item(
            factories.gear_item_payload(
                "00000000-0000-4000-8000-0000000000ff", customer["id"]
            ),
            agent_headers,
        )

        validate_error(response, ERR_GEAR_MODEL_NOT_FOUND)

        rows, meta = validate_paginated(
            api.list_gear_items(agent_headers, owner_customer_id=customer["id"])
        )
        assert meta["total_count"] == 0
        assert rows == []


# ==========================================================================
# Request-shape rejection
# ==========================================================================
class TestRequestShape:
    def test_warranty_claim_missing_required_fields_rejected(
        self, api, scenario, agent_headers
    ):
        """Intake without its required gear_item_id and reported_defect_type is a shape rejection.

        "(9) The body and query conform to the endpoint's input schema: required fields present, types correct, enum members recognised, integers at or above their declared minimum, ISO-8601 timestamps parseable, and the `certifications`, `labor_lines`, `estimated_labor_lines` and `work_log` arrays well formed — otherwise `ERR_INVALID_REQUEST` (HTTP 422)."
        "Intake carries a `service_center_id` naming the centre that will own the claim's liability and turnaround, a `gear_item_id` naming the unit whose defect is claimed, an `intake_kind`, a `reported_defect_type`, and an optional `customer_narrative` of one to two thousand characters describing the failure in the customer's words."

        Design: Corner/entities/warranty_claim_missing_required_fields_rejected
        """
        scenario.set_clock("2026-06-15T09:00:00Z")
        center = scenario.center()

        response = api.create_warranty_claim(
            {"service_center_id": center["id"], "customer_narrative": "Something failed."},
            agent_headers,
        )

        validate_error(response, ERR_INVALID_REQUEST)

        rows, meta = validate_paginated(
            api.list_warranty_claims(agent_headers, service_center_id=center["id"])
        )
        assert meta["total_count"] == 0
        assert rows == []

    def test_gear_model_invalid_enum_category_rejected(self, api, scenario, admin_headers):
        """An unrecognised category and an out-of-range release_year are both shape rejections.

        "(9) The body and query conform to the endpoint's input schema: required fields present, types correct, enum members recognised, integers at or above their declared minimum, ISO-8601 timestamps parseable, and the `certifications`, `labor_lines`, `estimated_labor_lines` and `work_log` arrays well formed — otherwise `ERR_INVALID_REQUEST` (HTTP 422)."
        "A model is created with a `model_code` of three to thirty-two characters drawn from uppercase letters, digits and hyphens and unique across the catalogue; a marketing `name`; a `category` drawn from `SHELL_APPAREL`, `INSULATION`, `TENT_SHELTER`, `PACK_HARNESS` and `HARDGOODS_FRAME`; an `msrp_cents` of at least one cent; a `release_year` between 2000 and 2100; and a `warranty_years` between 0 and 30 stating limited coverage in whole years from purchase."

        Design: Corner/entities/gear_model_invalid_enum_category_rejected
        """
        scenario.set_clock("2026-06-15T09:00:00Z")

        bad_category = api.create_gear_model(
            factories.gear_model_payload(
                model_code="TNT-BAD-1", name="Bad Tent", category="CAMP_KITCHEN"
            ),
            admin_headers,
        )
        validate_error(bad_category, ERR_INVALID_REQUEST)

        bad_year = api.create_gear_model(
            factories.gear_model_payload(
                model_code="TNT-BAD-2", name="Bad Year Tent", release_year=1899
            ),
            admin_headers,
        )
        validate_error(bad_year, ERR_INVALID_REQUEST)

        rows, meta = validate_paginated(
            api.list_gear_models(admin_headers, category="TENT_SHELTER")
        )
        assert meta["total_count"] == 0
        assert rows == []


# ==========================================================================
# Server-computed fields and the immutable bench record
# ==========================================================================
class TestComputedAndImmutableFields:
    def test_gear_item_computed_valuation_fields_input_ignored(
        self, api, scenario, agent_headers
    ):
        """Client-supplied age, coverage, valuations and disposition are discarded and recomputed.

        "On registration the server derives the unit's whole-month `age_months`, its `warranty_state`, and both valuations described in §2.8 — `replacement_value_depreciated_cents` and `replacement_value_successor_cents`."
        "Coverage is a three-valued field: `warranty_state` is `LIFETIME` whenever the unit's model carries `lifetime_warranty`; otherwise it is `IN_WARRANTY` as long as the logical clock instant is at or before the `purchase_date` advanced by the model's `warranty_years` in whole calendar years; and otherwise it is `EXPIRED`."
        "The depreciated value is then the greater of that residual floor and the unit's `purchase_price_cents` multiplied by one minus the depreciation fraction, rounded half up to whole cents."
        "The successor valuation is that base list price multiplied by ninety percent, rounded half up to whole cents."
        "Its `disposition_status` starts at `WITH_CUSTOMER`."
        "`trade_in_credit_cents` is 0 until the unit is accepted as a trade-in, `refurb_list_price_cents` is null until the same moment, and `resale_price_cents` is null until the unit is actually sold on the refurbished channel."

        Design: Corner/entities/gear_item_computed_valuation_fields_input_ignored
        """
        scenario.set_clock("2026-06-15T09:00:00Z")
        successor = scenario.successor_model(msrp_cents=99900)
        model = scenario.model(
            msrp_cents=79900,
            warranty_years=5,
            discontinued_at="2024-03-01T00:00:00Z",
            successor_model_id=successor["id"],
        )
        customer = scenario.customer()

        item = validate_success(
            api.create_gear_item(
                factories.gear_item_payload(
                    model["id"],
                    customer["id"],
                    purchase_date="2023-05-10T00:00:00Z",
                    purchase_price_cents=74900,
                    age_months=3,
                    warranty_state="LIFETIME",
                    replacement_value_depreciated_cents=1,
                    replacement_value_successor_cents=2,
                    disposition_status="RESOLD",
                ),
                agent_headers,
            ),
            201,
        )

        assert item["age_months"] == 37
        assert item["warranty_state"] == "IN_WARRANTY"
        assert item["replacement_value_depreciated_cents"] == 52430
        assert item["replacement_value_successor_cents"] == 89910
        assert_money_cents(item["replacement_value_depreciated_cents"])
        assert_money_cents(item["replacement_value_successor_cents"])

        assert item["disposition_status"] == "WITH_CUSTOMER"
        assert item["trade_in_credit_cents"] == 0
        assert item["refurb_list_price_cents"] is None
        assert item["resale_price_cents"] is None

    def test_claim_assessment_is_immutable_with_no_version_field(
        self, api, assessed_claim, agent_headers
    ):
        """The bench record carries id and created_at only, with no updated_at and no version.

        "A ClaimAssessment is an immutable record of what a technician found on a given day: it carries only `id` and `created_at`."
        "It has no `updated_at` and no `version`, there is no endpoint that updates it, and a later finding never edits an earlier one — it supersedes it by setting the earlier row's `is_superseded` flag."
        "The `assessor_technician_id` is never accepted from the body: the server stamps it from `X-User-ID`."
        "From those inputs the server computes `estimated_repair_cost_cents` on the assessment row using the labour block of the paid-repair pricing rule described in §3.7 — that is, the per-line rounded labour charges summed into a labour subtotal, plus `estimated_parts_cents` used directly as the parts subtotal, plus the capped shop supply fee."

        Design: Corner/entities/claim_assessment_is_immutable_with_no_version_field
        """
        assessment = validate_success(
            api.get_claim_assessment(assessed_claim.assessment_id, agent_headers)
        )

        assert_immutable_common_fields(assessment)
        assert_timestamp_millis(assessment["created_at"])
        assert assessment["created_at"].startswith("2026-06-15T09:00:00")

        assert assessment["assessor_technician_id"] == assessed_claim.technician_id
        assert assessment["is_superseded"] is False
        assert assessment["estimated_repair_cost_cents"] == 22390


# ==========================================================================
# Cross-registry integrity: centre affiliation, successor cycles, uniqueness
# ==========================================================================
class TestCrossRegistryIntegrity:
    def test_technician_from_other_center_cross_reference_rejected(
        self, api, open_order, agent_headers
    ):
        """A technician staffing another centre cannot be booked onto this centre's order.

        "(25) The technician — acting or named — belongs to the same service centre as the claim or repair order, else `ERR_TECHNICIAN_CENTER_MISMATCH` (422); this guards assessment recording and work-block scheduling."
        "When `technician_id` is supplied explicitly, that technician must have roster `status` `ACTIVE`, must belong to the order's centre, must hold a certification for the block's `work_type` at or above that lane's minimum level, and must have no block already in `status` `SCHEDULED` overlapping the requested half-open interval — a conflict is refused with `ERR_TECHNICIAN_WINDOW_CONFLICT`."

        Design: Corner/entities/technician_from_other_center_cross_reference_rejected
        """
        scenario = open_order.scenario
        other_center = scenario.center(name="Rainier Depot", region_code="US-WA")
        other_technician = scenario.technician(
            other_center["id"],
            employee_code="T-201",
            full_name="Mira Cole",
            certifications=[factories.certification("FABRIC", 3)],
        )

        response = api.create_work_block(
            factories.work_block_payload(
                open_order.order_id,
                work_type="FABRIC",
                start_at="2026-06-16T09:00:00Z",
                end_at="2026-06-16T11:00:00Z",
                technician_id=other_technician["id"],
            ),
            agent_headers,
        )

        validate_error(response, ERR_TECHNICIAN_CENTER_MISMATCH)

        rows, meta = validate_paginated(
            api.list_work_blocks(agent_headers, repair_order_id=open_order.order_id)
        )
        assert meta["total_count"] == 0
        assert rows == []
        assert scenario.read_order(open_order.order_id)["work_status"] == "QUEUED"
        assert (
            scenario.read_technician(other_technician["id"])["scheduled_minutes_open"] == 0
        )

    def test_gear_model_self_successor_cycle_rejected(self, api, catalogue, admin_headers):
        """A self-successor and a two-hop successor loop are both refused, leaving the links intact.

        "The successor link is self-referential and cycle-checked: a model may not name itself as its own successor and may not close a loop through existing successor links, and either attempt is refused with `ERR_SUCCESSOR_CYCLE`."

        Design: Corner/entities/gear_model_self_successor_cycle_rejected
        """
        scenario = catalogue.scenario

        self_loop = api.patch_gear_model(
            catalogue.model_id, {"successor_model_id": catalogue.model_id}, admin_headers
        )
        validate_error(self_loop, ERR_SUCCESSOR_CYCLE)

        two_hop = api.patch_gear_model(
            catalogue.successor_id,
            {"successor_model_id": catalogue.model_id},
            admin_headers,
        )
        validate_error(two_hop, ERR_SUCCESSOR_CYCLE)

        assert (
            scenario.read_model(catalogue.model_id)["successor_model_id"]
            == catalogue.successor_id
        )
        assert scenario.read_model(catalogue.successor_id)["successor_model_id"] is None

    def test_uniqueness_collisions_across_registries_rejected(
        self, api, scenario, admin_headers, agent_headers, parts_headers
    ):
        """Each uniqueness scope answers its own code, and a serial repeats freely under another model.

        "(45) Uniqueness holds: a model's `model_code` is unique across the whole catalogue (`ERR_MODEL_CODE_TAKEN`), a customer's `email` is globally unique (`ERR_EMAIL_TAKEN`), a technician's `employee_code` is globally unique (`ERR_EMPLOYEE_CODE_TAKEN`), a unit's `serial_number` is unique within its `gear_model_id` (`ERR_SERIAL_ALREADY_REGISTERED`), and a lot's `part_code` is unique within its `gear_model_id` (`ERR_PART_CODE_TAKEN`), all HTTP 409."

        Design: Corner/entities/uniqueness_collisions_across_registries_rejected
        """
        scenario.set_clock("2026-06-15T09:00:00Z")
        center = scenario.center()
        model = scenario.model(model_code="TNT-ASCENT-2")
        pack_model = scenario.model(
            model_code="PCK-SUMMIT-40",
            name="Summit 40 Pack",
            category="PACK_HARNESS",
            msrp_cents=24900,
            release_year=2023,
            warranty_years=5,
        )
        scenario.part_lot(model["id"], part_code="AS2-FLOOR-PANEL")
        customer = scenario.customer(email="rowan@example.com")
        scenario.technician(center["id"], employee_code="T-101")
        scenario.gear_item(model["id"], customer["id"], serial_number="AS2-00417")

        validate_error(
            api.create_gear_model(
                factories.gear_model_payload(
                    model_code="TNT-ASCENT-2", name="Clone Tent", release_year=2020
                ),
                admin_headers,
            ),
            ERR_MODEL_CODE_TAKEN,
        )
        validate_error(
            api.create_customer(
                factories.customer_payload(
                    full_name="Rowan Clone",
                    email="rowan@example.com",
                    loyalty_tier="STANDARD",
                ),
                agent_headers,
            ),
            ERR_EMAIL_TAKEN,
        )
        validate_error(
            api.create_technician(
                factories.technician_payload(
                    center["id"],
                    employee_code="T-101",
                    full_name="Clone Tech",
                    certifications=[factories.certification("ZIPPER", 2)],
                ),
                admin_headers,
            ),
            ERR_EMPLOYEE_CODE_TAKEN,
        )
        validate_error(
            api.create_gear_item(
                factories.gear_item_payload(
                    model["id"],
                    customer["id"],
                    serial_number="AS2-00417",
                    proof_of_purchase_ref="POS-99999",
                ),
                agent_headers,
            ),
            ERR_SERIAL_ALREADY_REGISTERED,
        )
        validate_error(
            api.create_part_lot(
                factories.part_lot_payload(
                    model["id"],
                    part_code="AS2-FLOOR-PANEL",
                    on_hand_units=2,
                    low_watermark_units=1,
                ),
                parts_headers,
            ),
            ERR_PART_CODE_TAKEN,
        )

        pack_item = validate_success(
            api.create_gear_item(
                factories.gear_item_payload(
                    pack_model["id"],
                    customer["id"],
                    serial_number="AS2-00417",
                    purchase_price_cents=21900,
                    proof_of_purchase_ref="POS-77777",
                ),
                agent_headers,
            ),
            201,
        )
        assert pack_item["serial_number"] == "AS2-00417"
        assert pack_item["gear_model_id"] == pack_model["id"]

        _, model_meta = validate_paginated(api.list_gear_models(admin_headers))
        assert model_meta["total_count"] == 2

        lot_rows, lot_meta = validate_paginated(
            api.list_part_lots(parts_headers, gear_model_id=model["id"])
        )
        assert lot_meta["total_count"] == 1
        assert lot_rows[0]["gear_model_id"] == model["id"]
        assert lot_rows[0]["part_code"] == "AS2-FLOOR-PANEL"
