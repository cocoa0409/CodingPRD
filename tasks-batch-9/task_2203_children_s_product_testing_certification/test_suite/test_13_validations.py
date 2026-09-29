"""Validation gates: each guard fires on its own condition and in its own rank."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    factories,
    fixtures as fx,
    validate_error,
    validate_success,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    COORDINATOR_HEADERS,
    MANAGER_HEADERS,
    OFFICER_HEADERS,
    OFFICER_USER_ID,
    make_supplier_user_headers,
)


STARTUP_CLOCK = "2026-08-01T00:00:00Z"
LATE_ATTESTATION = "2027-12-31T00:00:00Z"

BOOKING_WINDOW = {
    "window_start": "2026-08-10T00:00:00Z",
    "window_end": "2026-08-12T00:00:00Z",
}


def _extra_lab(
    api,
    rule_id,
    *,
    independence_class="INDEPENDENT",
    attest_through=LATE_ATTESTATION,
    accredit=True,
    **accreditation_overrides,
):
    """A second laboratory built one attribute at a time, so each gate can be isolated."""
    lab = fx.create_laboratory(api, independence_class=independence_class)
    if attest_through is not None:
        fx.attest(api, lab["id"], attest_through)
    if accredit:
        fx.accredit(api, lab["id"], rule_id, **accreditation_overrides)
    return lab


def _book(api, env, laboratory_id, **overrides):
    payload = factories.test_order_payload(
        env["product"]["id"],
        env["plan"]["id"],
        laboratory_id,
        env["rules"][0]["id"],
        **{**BOOKING_WINDOW, **overrides},
    )
    return api.create_test_order(payload, headers=COORDINATOR_HEADERS)


class TestUndueInfluenceGuardFamily:
    """Three laboratory-integrity gates that must never collapse into one code."""

    def test_a_barred_laboratory_is_refused_with_its_own_code(self, api):
        """PRD 2.10: "A laboratory whose `operational_state` is `BARRED` may not be assigned
        new work and may not take an order into testing; attempts are refused with
        `ERR_LAB_BARRED` (HTTP 422)."

        Design: Corner/validations/corner_validations_undue_influence_family_each_guard_produces_its_own_error
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.booking_env(api)
        barred = _extra_lab(api, env["rules"][0]["id"])
        assert fx.set_lab_state(api, barred["id"], "BARRED")["operational_state"] == "BARRED"

        validate_error(
            _book(api, env, barred["id"]),
            ApiErrorId.LAB_BARRED.value,
            422,
        )
        assert fx.list_orders_for_product(api, env["product"]["id"]) == []

    def test_missing_and_expired_attestations_share_one_code_and_are_curable(self, api):
        """PRD 2.10: "An attestation that is `MISSING`, that has been marked `EXPIRED`, or
        whose validity instant is at or before the logical clock, blocks the operation with
        `ERR_UNDUE_INFLUENCE_ATTESTATION_MISSING` (HTTP 422)."

        Design: Corner/validations/corner_validations_undue_influence_family_each_guard_produces_its_own_error
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.booking_env(api)
        rule_id = env["rules"][0]["id"]
        never_attested = _extra_lab(api, rule_id, attest_through=None)
        stale = _extra_lab(api, rule_id, attest_through="2026-07-31T00:00:00Z")

        assert fx.get_laboratory(api, never_attested["id"])["influence_attestation_state"] == (
            "MISSING"
        )
        validate_error(
            _book(api, env, never_attested["id"]),
            ApiErrorId.UNDUE_INFLUENCE_ATTESTATION_MISSING.value,
            422,
        )
        validate_error(
            _book(api, env, stale["id"]),
            ApiErrorId.UNDUE_INFLUENCE_ATTESTATION_MISSING.value,
            422,
        )

        refreshed = fx.attest(api, stale["id"], LATE_ATTESTATION)
        assert refreshed["influence_attestation_state"] == "CURRENT"
        booked = validate_success(_book(api, env, stale["id"]), 201)
        assert booked["order_state"] == "SCHEDULED"

    def test_a_manufacturer_owned_laboratory_may_take_ordinary_work(self, api):
        """PRD 2.10: "A `MANUFACTURER_OWNED` laboratory may never be handed a retest round.
        When an operation would create a test order flagged as a retest, the laboratory's
        `independence_class` must be `INDEPENDENT` or `FIREWALLED_GOVERNMENT`; a
        manufacturer-owned laboratory in that position is refused with
        `ERR_MANUFACTURER_OWNED_LAB_FORBIDDEN` (HTTP 422)."

        Design: Corner/validations/corner_validations_undue_influence_family_each_guard_produces_its_own_error
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.booking_env(api)
        owned = _extra_lab(
            api, env["rules"][0]["id"], independence_class="MANUFACTURER_OWNED"
        )
        order = validate_success(_book(api, env, owned["id"]), 201)
        assert order["order_state"] == "SCHEDULED"
        assert order["is_retest"] is False

    def test_a_manufacturer_owned_laboratory_may_not_take_a_retest_round(self, api):
        """PRD 3.9: "a laboratory whose `independence_class` is `MANUFACTURER_OWNED` may
        never be assigned a retest order, so the target laboratory's `independence_class`
        must be `INDEPENDENT` or `FIREWALLED_GOVERNMENT` or the request is refused with
        `ERR_MANUFACTURER_OWNED_LAB_FORBIDDEN`."

        Design: Corner/validations/corner_validations_undue_influence_family_each_guard_produces_its_own_error
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.stopped_case_env(api)
        owned = _extra_lab(
            api, env["rules"][0]["id"], independence_class="MANUFACTURER_OWNED"
        )

        validate_error(
            api.order_retest(
                env["case"]["id"],
                factories.retest_payload(env["plan"]["id"], owned["id"]),
                headers=COORDINATOR_HEADERS,
            ),
            ApiErrorId.MANUFACTURER_OWNED_LAB_FORBIDDEN.value,
            422,
        )
        case = fx.get_case(api, env["case"]["id"])
        assert case["case_state"] == "STOP_DISTRIBUTION_ISSUED"
        assert case["retest_round_count"] == 0
        assert case["active_retest_order_id"] is None


LEAD_METHOD = "CPSC-CH-E1002-08"
PHTHALATE_METHOD = "CPSC-CH-C1001-09"
TWO_METHOD_RULES = [
    {"test_method_code": LEAD_METHOD, "hazard_class": "LEAD_CONTENT"},
    {"test_method_code": PHTHALATE_METHOD, "hazard_class": "PHTHALATES"},
]


class TestAccreditationIsAFourWayTuple:
    """Laboratory, method, state and clock coverage must agree on one row."""

    def test_each_of_the_four_attributes_breaks_the_match_on_its_own(self, api):
        """PRD 2.10: "Exactly one accreditation record must exist for the target laboratory
        whose `test_method_code` equals the test method of the rule under test, whose
        `accreditation_state` is `ACCREDITED`, and whose closed coverage interval — from
        `valid_from` through `valid_through`, both endpoints inclusive — contains the logical
        clock instant. Absence of such a record is refused with
        `ERR_LAB_METHOD_NOT_ACCREDITED` (HTTP 422)."

        Design: Corner/validations/corner_validations_accreditation_match_is_a_four_way_cross_entity_tuple
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.booking_env(api, rule_specs=[dict(spec) for spec in TWO_METHOD_RULES])
        lead_id, phthalate_id = env["rules"][0]["id"], env["rules"][1]["id"]

        match = _extra_lab(api, lead_id)
        wrong_method = _extra_lab(api, phthalate_id)
        expired_window = _extra_lab(
            api,
            lead_id,
            valid_from="2025-01-01T00:00:00Z",
            valid_through="2026-07-31T00:00:00Z",
        )
        suspended = fx.create_laboratory(api)
        fx.attest(api, suspended["id"], LATE_ATTESTATION)
        suspended_row = fx.accredit(api, suspended["id"], lead_id)
        assert (
            fx.suspend_accreditation(api, suspended_row["id"], "Proficiency lapse")[
                "accreditation_state"
            ]
            == "SUSPENDED"
        )

        assert validate_success(_book(api, env, match["id"]), 201)["order_state"] == (
            "SCHEDULED"
        )
        for laboratory in (wrong_method, expired_window, suspended):
            validate_error(
                _book(api, env, laboratory["id"]),
                ApiErrorId.LAB_METHOD_NOT_ACCREDITED.value,
                422,
            )

    def test_coverage_is_inclusive_at_the_valid_from_endpoint(self, api):
        """PRD 2.10: "whose closed coverage interval — from `valid_from` through
        `valid_through`, both endpoints inclusive — contains the logical clock instant."

        Design: Corner/validations/corner_validations_accreditation_match_is_a_four_way_cross_entity_tuple
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.booking_env(api, rule_specs=[dict(spec) for spec in TWO_METHOD_RULES])
        edge = _extra_lab(
            api,
            env["rules"][0]["id"],
            valid_from=STARTUP_CLOCK,
            valid_through="2027-01-01T00:00:00Z",
        )
        order = validate_success(_book(api, env, edge["id"]), 201)
        assert order["laboratory_id"] == edge["id"]

    def test_the_supplier_evidence_route_shares_the_same_accreditation_guard(self, api):
        """PRD 2.10: "This gate applies to booking a test order and to submitting a component
        part certificate; the same coverage condition is additionally re-verified as a
        precondition when the laboratory takes an order into testing."

        Design: Corner/validations/corner_validations_accreditation_match_is_a_four_way_cross_entity_tuple
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.booking_env(api, rule_specs=[dict(spec) for spec in TWO_METHOD_RULES])
        lead_id = env["rules"][0]["id"]
        wrong_method = _extra_lab(api, env["rules"][1]["id"])
        part_id = env["parts"][0]["id"]
        supplier_headers = make_supplier_user_headers(env["supplier"]["id"])

        validate_error(
            api.submit_part_certificate(
                part_id,
                factories.part_certificate_payload(wrong_method["id"], lead_id),
                headers=supplier_headers,
            ),
            ApiErrorId.LAB_METHOD_NOT_ACCREDITED.value,
            422,
        )
        accepted = validate_success(
            api.submit_part_certificate(
                part_id,
                factories.part_certificate_payload(env["laboratory"]["id"], lead_id),
                headers=supplier_headers,
            ),
            201,
        )
        assert accepted["reliance_state"] == "SUBMITTED"


class TestTemporalWindowShapes:
    """Two temporal guards whose comparators point in opposite directions."""

    def test_booking_windows_reject_equality_and_backdating_but_allow_the_clock_instant(
        self, api
    ):
        """PRD 3.6: "`window_end` must be strictly after `window_start` and `window_start`
        must be at or after the logical clock — a window that ends at or before it starts, or
        that begins in the past, is refused with `ERR_WINDOW_INVALID`."

        Design: Corner/validations/corner_validations_temporal_window_shapes_reject_equality_and_backdating
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.booking_env(api)

        validate_error(
            _book(
                api,
                env,
                env["laboratory"]["id"],
                window_start="2026-08-10T00:00:00Z",
                window_end="2026-08-10T00:00:00Z",
            ),
            ApiErrorId.WINDOW_INVALID.value,
            422,
        )
        validate_error(
            _book(
                api,
                env,
                env["laboratory"]["id"],
                window_start="2026-07-31T00:00:00Z",
                window_end="2026-08-10T00:00:00Z",
            ),
            ApiErrorId.WINDOW_INVALID.value,
            422,
        )
        accepted = validate_success(
            _book(
                api,
                env,
                env["laboratory"]["id"],
                window_start=STARTUP_CLOCK,
                window_end="2026-08-02T00:00:00Z",
            ),
            201,
        )
        assert accepted["window_start"] == STARTUP_CLOCK
        assert accepted["order_state"] == "SCHEDULED"

    def test_periodic_review_treats_the_due_instant_itself_as_due(self, api):
        """PRD 3.5: "Running a **periodic review** on an `ACTIVE` plan requires that the
        logical clock be at or after `periodic_due_at`; an instant exactly equal to it is due,
        and an instant strictly before it is refused with `ERR_PERIODIC_REVIEW_NOT_DUE`."

        Design: Corner/validations/corner_validations_temporal_window_shapes_reject_equality_and_backdating
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.booking_env(api)
        plan_id = env["plan"]["id"]
        assert env["plan"]["periodic_due_at"] == "2027-08-01T00:00:00Z"

        fx.set_clock(api, "2027-07-31T23:59:59Z")
        validate_error(
            api.periodic_review(plan_id, headers=COORDINATOR_HEADERS),
            ApiErrorId.PERIODIC_REVIEW_NOT_DUE.value,
            409,
        )
        assert fx.get_plan(api, plan_id)["plan_state"] == "ACTIVE"

        fx.set_clock(api, "2027-08-01T00:00:00Z")
        reviewed = fx.periodic_review(api, plan_id)
        assert reviewed["plan_state"] == "RESAMPLE_DUE"
        assert reviewed["resample_trigger"] == "PERIODIC_INTERVAL"

    def test_the_same_code_guards_coverage_and_accreditation_intervals(self, api):
        """PRD 2.11 rank 27: "Interval well-formedness — `window_end` is strictly after
        `window_start` and `window_start` is at or after the logical clock;
        `coverage_through` is strictly after `coverage_from`; `valid_through` is strictly
        after `valid_from` → `ERR_WINDOW_INVALID` (422). Applies to test order booking,
        component part certificate submission, and accreditation creation."

        Design: Corner/validations/corner_validations_temporal_window_shapes_reject_equality_and_backdating
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.booking_env(api)
        rule_id = env["rules"][0]["id"]

        validate_error(
            api.submit_part_certificate(
                env["parts"][0]["id"],
                factories.part_certificate_payload(
                    env["laboratory"]["id"],
                    rule_id,
                    coverage_from="2026-02-01T00:00:00Z",
                    coverage_through="2026-02-01T00:00:00Z",
                ),
                headers=make_supplier_user_headers(env["supplier"]["id"]),
            ),
            ApiErrorId.WINDOW_INVALID.value,
            422,
        )
        validate_error(
            api.create_accreditation(
                env["laboratory"]["id"],
                factories.accreditation_payload(
                    rule_id,
                    valid_from="2026-05-01T00:00:00Z",
                    valid_through="2026-05-01T00:00:00Z",
                ),
                headers=ADMIN_HEADERS,
            ),
            ApiErrorId.WINDOW_INVALID.value,
            422,
        )


class TestTestingBudgetAggregate:
    """The fiscal ceiling is a recomputed aggregate over live order states."""

    def _book_units(self, api, env, sample_count):
        return _book(
            api,
            env,
            env["laboratory"]["id"],
            sample_count=sample_count,
            window_end="2026-08-20T00:00:00Z",
        )

    def test_the_sum_is_inclusive_and_the_refusal_carries_the_payment_status(self, api):
        """PRD 3.6: "the sum of `invoice_total_cents` over the product's orders in
        `SCHEDULED`, `IN_TESTING`, `REPORTED_PASS` or `REPORTED_FAIL`, plus the candidate's
        own `invoice_total_cents`, must not exceed the product's `testing_budget_cents`, or
        the booking is refused with `ERR_PRODUCT_TESTING_BUDGET_EXCEEDED`."

        Design: Corner/validations/corner_validations_budget_aggregate_sums_only_the_live_order_states
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.booking_env(
            api,
            rule_specs=[{"base_method_fee_cents": 20000}],
            laboratory={"concurrent_slot_capacity": 8},
            product={"testing_budget_cents": 60000},
        )
        assert env["product"]["testing_budget_cents"] == 60000

        one = validate_success(self._book_units(api, env, 2), 201)
        assert one["invoice_total_cents"] == 40000
        fx.start_order(api, one["id"], env["laboratory"]["id"])
        failed = fx.report(api, one["id"], env["laboratory"]["id"], 250)
        assert failed["order_state"] == "REPORTED_FAIL"

        two = validate_success(self._book_units(api, env, 1), 201)
        assert two["invoice_total_cents"] == 20000

        validate_error(
            self._book_units(api, env, 1),
            ApiErrorId.PRODUCT_TESTING_BUDGET_EXCEEDED.value,
            402,
        )
        assert fx.get_product(api, env["product"]["id"])["testing_budget_cents"] == 60000

    def test_cancelled_orders_drop_out_of_the_input_set(self, api):
        """PRD 2.11 rank 42: "the sum of `invoice_total_cents` over the product's orders in
        `SCHEDULED`, `IN_TESTING`, `REPORTED_PASS` or `REPORTED_FAIL`, plus the candidate
        order's own `invoice_total_cents`, does not exceed the product's
        `testing_budget_cents`."

        Design: Corner/validations/corner_validations_budget_aggregate_sums_only_the_live_order_states
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.booking_env(
            api,
            rule_specs=[{"base_method_fee_cents": 20000}],
            laboratory={"concurrent_slot_capacity": 8},
            product={"testing_budget_cents": 60000},
        )
        one = validate_success(self._book_units(api, env, 2), 201)
        two = validate_success(self._book_units(api, env, 1), 201)
        validate_error(
            self._book_units(api, env, 1),
            ApiErrorId.PRODUCT_TESTING_BUDGET_EXCEEDED.value,
            402,
        )

        cancelled = validate_success(
            api.cancel_test_order(two["id"], headers=COORDINATOR_HEADERS), 200
        )
        assert cancelled["order_state"] == "CANCELLED"
        four = validate_success(self._book_units(api, env, 1), 201)
        assert four["invoice_total_cents"] == 20000
        assert four["id"] not in (one["id"], two["id"])


class TestMaterialChangeSubjectDiscriminator:
    """`subject_type` decides whether the part reference is required or forbidden."""

    def test_the_discriminator_is_enforced_in_both_directions(self, api):
        """PRD 3.10: "When `subject_type` is `COMPONENT_PART`, `component_part_id` must be
        supplied and the named part's `product_id` must equal the submitted `product_id`; when
        `subject_type` is `PRODUCT`, `component_part_id` must be omitted or null. Either
        violation — a part event with no part, a part belonging to a different product, or a
        product event that nonetheless names a part — is refused with
        `ERR_PART_SUBJECT_MISMATCH`."

        Design: Corner/validations/corner_validations_material_change_subject_type_drives_a_conditional_referential_check
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.regulatory_env(api)
        parties = fx.party_env(api, env["rules"])
        alpha = fx.create_product(api, env["category"]["id"])
        beta = fx.create_product(api, env["category"]["id"])
        alpha_part = fx.add_part(api, alpha["id"], parties["supplier"]["id"])
        beta_part = fx.add_part(api, beta["id"], parties["supplier"]["id"])

        matched = validate_success(
            api.record_material_change(
                factories.material_change_payload(
                    alpha["id"],
                    subject_type="COMPONENT_PART",
                    component_part_id=alpha_part["id"],
                ),
                headers=ADMIN_HEADERS,
            ),
            201,
        )
        assert matched["occurred_at"] == STARTUP_CLOCK

        for payload in (
            factories.material_change_payload(
                alpha["id"],
                subject_type="COMPONENT_PART",
                component_part_id=beta_part["id"],
            ),
            factories.material_change_payload(alpha["id"], subject_type="COMPONENT_PART"),
            factories.material_change_payload(
                alpha["id"], subject_type="PRODUCT", component_part_id=alpha_part["id"]
            ),
        ):
            validate_error(
                api.record_material_change(payload, headers=ADMIN_HEADERS),
                ApiErrorId.PART_SUBJECT_MISMATCH.value,
                422,
            )

        clean = validate_success(
            api.record_material_change(
                factories.material_change_payload(alpha["id"]), headers=ADMIN_HEADERS
            ),
            201,
        )
        assert clean["component_part_id"] is None
        assert fx.get_product(api, alpha["id"])["material_change_count"] == 2


class TestEmptyCollectionBoundaries:
    """Scoping is blocked by an empty bill of materials and by an empty derived set."""

    def test_two_empty_sets_reach_the_same_endpoint_with_different_codes(self, api):
        """PRD 3.3: "An empty bill of materials is refused with `ERR_NO_COMPONENT_PARTS`; a
        bill of materials that produces no applicable rules is refused with
        `ERR_NO_APPLICABLE_RULES`."

        Design: Corner/validations/corner_validations_empty_collection_boundaries_block_scoping_in_two_distinct_ways
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.regulatory_env(
            api, rule_specs=[{"applicability_condition": "IF_ACCESSIBLE_METAL"}]
        )
        unmapped_category = fx.create_category(api)
        supplier = fx.create_supplier(api)

        no_parts = fx.create_product(api, env["category"]["id"])
        no_match = fx.create_product(api, env["category"]["id"])
        fx.add_part(
            api,
            no_match["id"],
            supplier["id"],
            material_class="TEXTILE",
            accessible_to_child=False,
            small_part_when_detached=False,
        )
        no_mapping = fx.create_product(api, unmapped_category["id"])
        fx.add_part(api, no_mapping["id"], supplier["id"], material_class="PAINTED_COATING")

        validate_error(
            api.submit_for_certification(
                no_parts["id"], {"evidence_path": "FULL_PRODUCT_TEST"},
                headers=COORDINATOR_HEADERS,
            ),
            ApiErrorId.NO_COMPONENT_PARTS.value,
            422,
        )
        for product in (no_match, no_mapping):
            validate_error(
                api.submit_for_certification(
                    product["id"], {"evidence_path": "FULL_PRODUCT_TEST"},
                    headers=COORDINATOR_HEADERS,
                ),
                ApiErrorId.NO_APPLICABLE_RULES.value,
                422,
            )

        for product in (no_parts, no_match, no_mapping):
            current = fx.get_product(api, product["id"])
            assert current["certification_state"] == "DRAFT"
            assert current["required_rule_ids"] == []
            assert current["compliance_posture"] == "UNSCOPED"

    def test_an_accessible_metal_part_repairs_both_empty_sets_at_once(self, api):
        """PRD 3.1: "`IF_ACCESSIBLE_METAL`, which applies when at least one part is of
        material class `ACCESSIBLE_METAL` **and** is also marked accessible to a child."

        Design: Corner/validations/corner_validations_empty_collection_boundaries_block_scoping_in_two_distinct_ways
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.regulatory_env(
            api, rule_specs=[{"applicability_condition": "IF_ACCESSIBLE_METAL"}]
        )
        supplier = fx.create_supplier(api)
        product = fx.create_product(api, env["category"]["id"])

        validate_error(
            api.submit_for_certification(
                product["id"], {"evidence_path": "FULL_PRODUCT_TEST"},
                headers=COORDINATOR_HEADERS,
            ),
            ApiErrorId.NO_COMPONENT_PARTS.value,
            422,
        )
        fx.add_part(
            api,
            product["id"],
            supplier["id"],
            material_class="ACCESSIBLE_METAL",
            accessible_to_child=True,
        )
        scoped = fx.submit_for_certification(api, product["id"], "FULL_PRODUCT_TEST")
        # PRD 3.4 forks SCOPED onward automatically inside the same request.
        assert scoped["certification_state"] == "FULL_TEST_PROGRAM"
        assert scoped["required_rule_ids"] == [env["rules"][0]["id"]]


class TestUniquenessScopes:
    """Mapping pairs are unique among ACTIVE rows; batch codes are unique per product."""

    def test_mapping_uniqueness_is_scoped_to_active_rows_only(self, api):
        """PRD 2.11 rank 35: "Mapping uniqueness — no `ACTIVE` mapping already exists for the
        submitted category-and-rule pair → `ERR_MAPPING_DUPLICATE` (409). Applies to mapping
        creation."

        Design: Corner/validations/corner_validations_uniqueness_scopes_differ_between_mapping_pairs_and_batch_codes
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.regulatory_env(api)
        category_id, rule_id = env["category"]["id"], env["rules"][0]["id"]

        validate_error(
            api.create_mapping(
                factories.mapping_payload(category_id, rule_id), headers=ADMIN_HEADERS
            ),
            ApiErrorId.MAPPING_DUPLICATE.value,
            409,
        )
        retired = validate_success(
            api.retire_mapping(env["mappings"][0]["id"], headers=ADMIN_HEADERS), 200
        )
        assert retired["mapping_state"] == "RETIRED"

        replacement = validate_success(
            api.create_mapping(
                factories.mapping_payload(category_id, rule_id), headers=ADMIN_HEADERS
            ),
            201,
        )
        assert replacement["mapping_state"] == "ACTIVE"
        assert replacement["id"] != env["mappings"][0]["id"]

    def test_batch_code_uniqueness_is_scoped_to_one_product(self, api):
        """PRD 3.8: "The code must also be unique among the batches of the same product; a
        repeat is refused with `ERR_BATCH_CODE_DUPLICATE`."

        Design: Corner/validations/corner_validations_uniqueness_scopes_differ_between_mapping_pairs_and_batch_codes
        """
        fx.set_clock(api, STARTUP_CLOCK)
        alpha = fx.distributed_env(api, batch_specs=[])
        beta = fx.distributed_env(api, batch_specs=[])
        shared_code = "RVR090-000501"

        first = fx.create_batch(
            api, alpha["product"]["id"], alpha["certificate"]["id"], batch_code=shared_code
        )
        assert first["batch_code"] == shared_code
        validate_error(
            api.create_production_batch(
                alpha["product"]["id"],
                factories.batch_payload(alpha["certificate"]["id"], batch_code=shared_code),
                headers=MANAGER_HEADERS,
            ),
            ApiErrorId.BATCH_CODE_DUPLICATE.value,
            409,
        )
        elsewhere = fx.create_batch(
            api, beta["product"]["id"], beta["certificate"]["id"], batch_code=shared_code
        )
        assert elsewhere["batch_code"] == shared_code
        assert elsewhere["product_id"] == beta["product"]["id"]

        alpha_batches = fx.list_batches_for_product(api, alpha["product"]["id"])
        assert [batch["batch_code"] for batch in alpha_batches] == [shared_code]


class TestSamplingFloorAboveTheCap:
    """A category floor above the hard ceiling of 40 makes activation unreachable."""

    def _plan_for_floor(self, api, floor):
        env = fx.scoped_product_env(
            api,
            category={"sampling_floor_units": floor},
            product={"projected_annual_units": 100000},
        )
        env["draft_plan"] = fx.create_plan(api, env["product"]["id"])
        return env

    def test_a_floor_of_forty_five_leaves_a_capped_plan_unactivatable(self, api):
        """PRD 3.5: "the plan's `units_authorized` must be at least the product category's
        `sampling_floor_units` — a plan sized below the category floor is refused with
        `ERR_SAMPLING_FLOOR_NOT_MET`."

        Design: Corner/validations/corner_validations_sampling_floor_can_exceed_the_cap_and_blocks_activation
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = self._plan_for_floor(api, 45)
        plan = env["draft_plan"]
        assert plan["units_authorized"] == 40

        validate_error(
            api.activate_sampling_plan(plan["id"], headers=COORDINATOR_HEADERS),
            ApiErrorId.SAMPLING_FLOOR_NOT_MET.value,
            422,
        )
        unchanged = fx.get_plan(api, plan["id"])
        assert unchanged["plan_state"] == "DRAFT"
        assert unchanged["activated_at"] is None
        assert unchanged["periodic_due_at"] is None

    def test_a_floor_equal_to_the_cap_activates_because_the_comparison_is_inclusive(
        self, api
    ):
        """PRD 3.5: "take the greater of that figure and the category's `sampling_floor_units`,
        then take the lesser of that result and the hard ceiling of 40 sample units; the
        outcome is written to `units_authorized`."

        Design: Corner/validations/corner_validations_sampling_floor_can_exceed_the_cap_and_blocks_activation
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = self._plan_for_floor(api, 40)
        plan = env["draft_plan"]
        assert plan["units_authorized"] == 40

        activated = fx.activate_plan(api, plan["id"])
        assert activated["plan_state"] == "ACTIVE"
        assert activated["activated_at"] == STARTUP_CLOCK

    def test_no_order_may_be_booked_against_the_plan_that_never_activated(self, api):
        """PRD 2.11 rank 11: "Sampling plan state — `DRAFT` for activation, either `ACTIVE` or
        `RESAMPLE_DUE` for periodic review, and either `ACTIVE` or `RESAMPLE_DUE` to accept a
        new test order → `ERR_PLAN_STATE_INVALID` (409)."

        Design: Corner/validations/corner_validations_sampling_floor_can_exceed_the_cap_and_blocks_activation
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = self._plan_for_floor(api, 45)
        validate_error(
            api.activate_sampling_plan(env["draft_plan"]["id"], headers=COORDINATOR_HEADERS),
            ApiErrorId.SAMPLING_FLOOR_NOT_MET.value,
            422,
        )
        validate_error(
            api.create_test_order(
                factories.test_order_payload(
                    env["product"]["id"],
                    env["draft_plan"]["id"],
                    env["laboratory"]["id"],
                    env["rules"][0]["id"],
                ),
                headers=COORDINATOR_HEADERS,
            ),
            ApiErrorId.PLAN_STATE_INVALID.value,
            409,
        )


class TestPostureGateReachesTwoEndpoints:
    """One computed posture field guards certificate issuance and batch release alike."""

    def test_batch_release_is_refused_while_the_posture_is_restricted(self, api):
        """PRD 3.8: "the owning product's `compliance_posture` is `CLEARED`, or the release is
        refused with `ERR_PRODUCT_POSTURE_NOT_CLEARED`."

        Design: Corner/validations/corner_validations_posture_gate_cascades_from_an_open_case_to_two_downstream_endpoints
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.distributed_env(api, release=False)
        batch = env["batches"][0]
        assert env["product"]["compliance_posture"] == "CLEARED"
        assert batch["distribution_state"] == "HELD"

        fx.record_material_change(api, env["product"]["id"])
        restricted = fx.get_product(api, env["product"]["id"])
        assert restricted["compliance_posture"] == "RESTRICTED"

        validate_error(
            api.release_batch(batch["id"], headers=MANAGER_HEADERS),
            ApiErrorId.PRODUCT_POSTURE_NOT_CLEARED.value,
            422,
        )
        assert fx.get_batch(api, batch["id"])["distribution_state"] == "HELD"

    def test_certificate_issuance_is_refused_by_the_same_computed_field(self, api):
        """PRD 3.7: "the product's `compliance_posture` is `CLEARED`, or the request is refused
        with `ERR_PRODUCT_POSTURE_NOT_CLEARED`."

        Design: Corner/validations/corner_validations_posture_gate_cascades_from_an_open_case_to_two_downstream_endpoints
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.evidence_complete_env(api)
        product = fx.get_product(api, env["product"]["id"])
        certificate = fx.draft_certificate(api, product["id"], product["version"])
        assert certificate["issuance_status"] == "DRAFT"
        assert certificate["content_completeness_pct"] == 100

        fx.record_material_change(api, product["id"])
        assert fx.get_product(api, product["id"])["compliance_posture"] == "RESTRICTED"

        validate_error(
            api.issue_certificate(certificate["id"], headers=OFFICER_HEADERS),
            ApiErrorId.PRODUCT_POSTURE_NOT_CLEARED.value,
            422,
        )
        assert fx.get_certificate(api, certificate["id"])["issuance_status"] == "DRAFT"

    def test_the_gate_is_derived_live_and_reopens_when_the_resample_closes(self, api):
        """PRD 3.3: "The **compliance posture** is recomputed immediately after every gap score
        evaluation, and also on product scoping and on archival."

        Design: Corner/validations/corner_validations_posture_gate_cascades_from_an_open_case_to_two_downstream_endpoints
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.distributed_env(api, release=False)
        batch = env["batches"][0]
        fx.record_material_change(api, env["product"]["id"])
        validate_error(
            api.release_batch(batch["id"], headers=MANAGER_HEADERS),
            ApiErrorId.PRODUCT_POSTURE_NOT_CLEARED.value,
            422,
        )

        fx.run_order_to_pass(
            api,
            env["product"]["id"],
            env["plan"]["id"],
            env["laboratory"]["id"],
            env["rules"][0]["id"],
        )
        assert fx.get_plan(api, env["plan"]["id"])["plan_state"] == "ACTIVE"
        assert fx.get_product(api, env["product"]["id"])["compliance_posture"] == "CLEARED"

        released = fx.release_batch(api, batch["id"])
        assert released["distribution_state"] == "RELEASED"
        assert released["released_at"] == STARTUP_CLOCK


def _rely(api, certificate_id, decision="RELY", headers=None):
    return api.record_reliance_documentation(
        certificate_id,
        {"reliance_decision": decision, "reliance_documentation_ref": "RELIANCE-PKG-001"},
        headers=headers or OFFICER_HEADERS,
    )


class TestRelianceReferentialGuards:
    """Rule scope, supplier paperwork and evidence path each refuse reliance separately."""

    def _reliance_env(self, api):
        no_agreement = fx.create_supplier(api)
        env = fx.scoped_product_env(
            api,
            evidence_path="COMPONENT_RELIANCE",
            supplier={"reliance_agreement_state": "ON_FILE"},
            part_specs=[{}, {"supplier_id": no_agreement["id"]}],
        )
        env["no_agreement_supplier"] = no_agreement
        env["unmapped_rule"] = fx.create_rule(api)
        fx.accredit(api, env["laboratory"]["id"], env["unmapped_rule"]["id"])
        return env

    def test_a_rule_outside_the_derived_scope_is_refused_on_its_own_ground(self, api):
        """PRD 3.4: "the certificate's `rule_id` is a member of the product's
        `required_rule_ids`, or the request is refused with
        `ERR_RULE_NOT_APPLICABLE_TO_PRODUCT`."

        Design: Corner/validations/corner_validations_reliance_referential_guards_separate_rule_scope_from_rule_policy
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = self._reliance_env(api)
        assert env["unmapped_rule"]["id"] not in env["product"]["required_rule_ids"]

        certificate = fx.submit_part_certificate(
            api,
            env["parts"][0]["id"],
            env["supplier"]["id"],
            env["laboratory"]["id"],
            env["unmapped_rule"]["id"],
        )
        validate_error(
            _rely(api, certificate["id"]),
            ApiErrorId.RULE_NOT_APPLICABLE_TO_PRODUCT.value,
            422,
        )
        assert fx.get_part_certificate(api, certificate["id"])["reliance_state"] == "SUBMITTED"

    def test_a_missing_reliance_agreement_is_refused_although_rule_and_row_are_sound(
        self, api
    ):
        """PRD 3.4: "the owning supplier's `reliance_agreement_state` is `ON_FILE`, or the
        request is refused with `ERR_RELIANCE_AGREEMENT_MISSING`."

        Design: Corner/validations/corner_validations_reliance_referential_guards_separate_rule_scope_from_rule_policy
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = self._reliance_env(api)
        assert (
            fx.get_supplier(api, env["no_agreement_supplier"]["id"])[
                "reliance_agreement_state"
            ]
            == "NOT_ON_FILE"
        )

        certificate = fx.submit_part_certificate(
            api,
            env["parts"][1]["id"],
            env["no_agreement_supplier"]["id"],
            env["laboratory"]["id"],
            env["rules"][0]["id"],
        )
        validate_error(
            _rely(api, certificate["id"]),
            ApiErrorId.RELIANCE_AGREEMENT_MISSING.value,
            422,
        )

    def test_rejection_ignores_the_policy_guards_and_the_clean_reliance_succeeds(self, api):
        """PRD 3.4: "In both branches the certificate must currently be in `reliance_state`
        `SUBMITTED`, and in both branches the submitted `reliance_documentation_ref` and the
        acting `X-User-ID` as `reliance_recorded_by_user_id` are stored on the certificate."

        Design: Corner/validations/corner_validations_reliance_referential_guards_separate_rule_scope_from_rule_policy
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = self._reliance_env(api)
        out_of_scope = fx.submit_part_certificate(
            api,
            env["parts"][0]["id"],
            env["supplier"]["id"],
            env["laboratory"]["id"],
            env["unmapped_rule"]["id"],
        )
        rejected = validate_success(_rely(api, out_of_scope["id"], decision="REJECT"), 200)
        assert rejected["reliance_state"] == "REJECTED"

        in_scope = fx.submit_part_certificate(
            api,
            env["parts"][0]["id"],
            env["supplier"]["id"],
            env["laboratory"]["id"],
            env["rules"][0]["id"],
        )
        relied = validate_success(_rely(api, in_scope["id"]), 200)
        assert relied["reliance_state"] == "RELIED_UPON"
        assert relied["reliance_recorded_by_user_id"] == OFFICER_USER_ID

    def test_reliance_may_not_be_recorded_on_the_full_product_testing_branch(self, api):
        """PRD 3.4: "the product's `evidence_path` is `COMPONENT_RELIANCE`, or the request is
        refused with `ERR_EVIDENCE_PATH_MISMATCH`."

        Design: Corner/validations/corner_validations_reliance_referential_guards_separate_rule_scope_from_rule_policy
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.scoped_product_env(
            api,
            evidence_path="FULL_PRODUCT_TEST",
            supplier={"reliance_agreement_state": "ON_FILE"},
        )
        certificate = fx.submit_part_certificate(
            api,
            env["parts"][0]["id"],
            env["supplier"]["id"],
            env["laboratory"]["id"],
            env["rules"][0]["id"],
        )
        validate_error(
            _rely(api, certificate["id"]),
            ApiErrorId.EVIDENCE_PATH_MISMATCH.value,
            422,
        )


class TestTopOfTheRefusalLadder:
    """Identity, role and request shape are all decided before any lookup."""

    def test_three_guards_of_different_kinds_all_outrank_existence(self, api):
        """PRD 2.11: "When a single request violates more than one rule, the response is
        decided by the **first** violated rule in the strict ordering below, and no later rule
        may mask an earlier one."

        Design: Corner/validations/corner_validations_authentication_and_shape_checks_outrank_existence
        """
        fx.set_clock(api, STARTUP_CLOCK)
        payload = factories.sampling_plan_payload()

        validate_error(
            api.create_sampling_plan(NON_EXISTENT_UUID, payload, headers=None),
            ApiErrorId.UNAUTHENTICATED.value,
            401,
        )
        validate_error(
            api.create_sampling_plan(
                NON_EXISTENT_UUID,
                payload,
                headers=make_supplier_user_headers(NON_EXISTENT_UUID),
            ),
            ApiErrorId.ROLE_NOT_PERMITTED.value,
            403,
        )
        validate_error(
            api.create_sampling_plan(
                NON_EXISTENT_UUID,
                factories.sampling_plan_payload(plan_type="ANNUAL"),
                headers=COORDINATOR_HEADERS,
            ),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )
        validate_error(
            api.create_sampling_plan(
                NON_EXISTENT_UUID, payload, headers=COORDINATOR_HEADERS
            ),
            ApiErrorId.PRODUCT_NOT_FOUND.value,
            404,
        )

    def test_every_refusal_on_that_ladder_carries_the_fixed_envelope(self, api):
        """PRD 2.2: "The `meta` object for error responses contains only `api_request_id` and
        `api_request_timestamp`." and "The `message` provides a human-readable explanation of
        what went wrong."

        Design: Corner/validations/corner_validations_authentication_and_shape_checks_outrank_existence
        """
        fx.set_clock(api, STARTUP_CLOCK)
        payload = factories.sampling_plan_payload()
        responses = [
            api.create_sampling_plan(NON_EXISTENT_UUID, payload, headers=None),
            api.create_sampling_plan(
                NON_EXISTENT_UUID,
                payload,
                headers=make_supplier_user_headers(NON_EXISTENT_UUID),
            ),
            api.create_sampling_plan(
                NON_EXISTENT_UUID,
                factories.sampling_plan_payload(plan_type="ANNUAL"),
                headers=COORDINATOR_HEADERS,
            ),
            api.create_sampling_plan(
                NON_EXISTENT_UUID, payload, headers=COORDINATOR_HEADERS
            ),
        ]
        for response in responses:
            body = response.json()
            assert body["response_type"] == "error"
            assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}
            assert body["meta"]["api_request_id"].startswith("req_")
            assert body["data"]["error_id"].startswith("ERR_")
            assert isinstance(body["data"]["message"], str) and body["data"]["message"]


class TestMiddleOfTheRefusalLadder:
    """The archive lock outranks operation-specific state, but existence outranks it."""

    def _archived_env(self, api):
        env = fx.certified_env(api)
        archived = validate_success(
            api.archive_product(env["product"]["id"], headers=ADMIN_HEADERS), 200
        )
        assert archived["certification_state"] == "ARCHIVED"
        env["product"] = archived
        return env

    def test_a_missing_body_reference_beats_the_archive_lock(self, api):
        """PRD 2.11 rank 6: "every resource named by a path segment or by a request-body
        foreign key exists, validated left to right across the path and then in declared
        body-field order, reporting the leftmost missing reference with that entity's own
        not-found code (404)."

        Design: Corner/validations/corner_validations_existence_precedes_state_and_state_precedes_business_rules
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = self._archived_env(api)
        validate_error(
            api.create_test_order(
                factories.test_order_payload(
                    env["product"]["id"],
                    env["plan"]["id"],
                    NON_EXISTENT_UUID,
                    env["rules"][0]["id"],
                ),
                headers=COORDINATOR_HEADERS,
            ),
            ApiErrorId.LABORATORY_NOT_FOUND.value,
            404,
        )

    def test_the_archive_lock_beats_every_operation_specific_state_error(self, api):
        """PRD 3.3: "`ARCHIVED` is terminal, and every subsequent write against the product or
        its children raises `ERR_PRODUCT_ARCHIVED`."

        Design: Corner/validations/corner_validations_existence_precedes_state_and_state_precedes_business_rules
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = self._archived_env(api)
        validate_error(
            api.create_test_order(
                factories.test_order_payload(
                    env["product"]["id"],
                    env["plan"]["id"],
                    env["laboratory"]["id"],
                    env["rules"][0]["id"],
                ),
                headers=COORDINATOR_HEADERS,
            ),
            ApiErrorId.PRODUCT_ARCHIVED.value,
            409,
        )
        validate_error(
            api.submit_for_certification(
                env["product"]["id"],
                {"evidence_path": "FULL_PRODUCT_TEST"},
                headers=COORDINATOR_HEADERS,
            ),
            ApiErrorId.PRODUCT_ARCHIVED.value,
            409,
        )
        validate_error(
            api.create_production_batch(
                env["product"]["id"],
                factories.batch_payload(env["certificate"]["id"]),
                headers=MANAGER_HEADERS,
            ),
            ApiErrorId.PRODUCT_ARCHIVED.value,
            409,
        )

    def test_reads_are_untouched_by_the_archive_lock(self, api):
        """PRD 3.3: "On success the product moves `CERTIFIED → ARCHIVED`, its
        `compliance_posture` becomes `UNSCOPED`, every sampling plan of the product whose
        `plan_state` is `DRAFT`, `ACTIVE` or `RESAMPLE_DUE` moves to `SUPERSEDED`, and the
        product's `version` increments by 1."

        Design: Corner/validations/corner_validations_existence_precedes_state_and_state_precedes_business_rules
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = self._archived_env(api)
        product = validate_success(
            api.get_product(env["product"]["id"], headers=ADMIN_HEADERS), 200
        )
        assert product["certification_state"] == "ARCHIVED"
        assert product["compliance_posture"] == "UNSCOPED"
        certificate = validate_success(
            api.get_certificate(env["certificate"]["id"], headers=OFFICER_HEADERS), 200
        )
        assert certificate["id"] == env["certificate"]["id"]
        assert fx.get_plan(api, env["plan"]["id"])["plan_state"] == "SUPERSEDED"


class TestFullGateStackSatisfied:
    """Certificate issuance succeeds only when all four of its guards are satisfied."""

    def test_the_success_response_is_asserted_field_by_field(self, api):
        """PRD 3.7: "On success, `issued_by_user_id` is set to the acting `X-User-ID` and
        `issued_at` to the logical clock instant; ... and the product advances
        `EVIDENCE_COMPLETE → CERTIFIED` with `compliance_posture` `CLEARED`."

        Design: Corner/validations/corner_validations_full_gate_stack_satisfied_yields_the_success_path
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.evidence_complete_env(api)
        product = fx.get_product(api, env["product"]["id"])
        assert product["certification_state"] == "EVIDENCE_COMPLETE"
        assert product["compliance_posture"] == "CLEARED"
        assert env["orders"][0]["ordered_by_user_id"] != OFFICER_USER_ID

        certificate = fx.draft_certificate(api, product["id"], product["version"])
        issued = validate_success(
            api.issue_certificate(certificate["id"], headers=OFFICER_HEADERS), 200
        )
        assert issued["issuance_status"] == "ISSUED"
        assert issued["issued_by_user_id"] == OFFICER_USER_ID
        assert issued["issued_at"] == STARTUP_CLOCK
        assert issued["content_completeness_pct"] == 100
        assert issued["cited_evidence_count"] >= len(issued["cited_rule_ids"])
        assert issued["accompaniment_status"] == "NOT_FURNISHED"
        assert fx.get_product(api, product["id"])["certification_state"] == "CERTIFIED"

    def test_the_success_cannot_be_replayed(self, api):
        """PRD 2.11: "When issuing a certificate, product state comes first, then the
        certificate's own axis state, then content completeness, then product posture, and
        only then segregation of duties." PRD 2.11 rank 9: "`EVIDENCE_COMPLETE` for
        certificate issuance → `ERR_PRODUCT_STATE_INVALID` (409)." The first issuance
        carried the product to `CERTIFIED`, so the replay is decided at rank 9.

        Design: Corner/validations/corner_validations_full_gate_stack_satisfied_yields_the_success_path
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.certified_env(api)
        validate_error(
            api.issue_certificate(env["certificate"]["id"], headers=OFFICER_HEADERS),
            ApiErrorId.PRODUCT_STATE_INVALID.value,
            409,
        )
