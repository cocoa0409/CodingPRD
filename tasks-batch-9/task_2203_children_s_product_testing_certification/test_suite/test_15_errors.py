"""Error taxonomy: one code per entity, one status per family, one envelope for all."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    factories,
    fixtures as fx,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    COORDINATOR_HEADERS,
    MANAGER_HEADERS,
    OFFICER_HEADERS,
    make_laboratory_user_headers,
    make_supplier_user_headers,
)


STARTUP_CLOCK = "2026-08-01T00:00:00Z"


class TestFifteenNotFoundCodes:
    """Every entity owns its own 404 code, and the codes are never interchanged."""

    def test_each_single_resource_read_reports_the_code_named_for_its_own_entity(self, api):
        """PRD 2.11 rank 6: "Path and body reference existence — every resource named by a path
        segment or by a request-body foreign key exists, validated left to right across the path
        and then in declared body-field order, reporting the leftmost missing reference with
        that entity's own not-found code (404)."

        Design: Corner/errors/corner_errors_fifteen_not_found_codes_are_one_per_entity_and_never_interchangeable
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.distributed_env(api)
        validate_success(api.get_product(env["product"]["id"], headers=ADMIN_HEADERS), 200)

        probes = [
            (api.get_rule, ApiErrorId.RULE_NOT_FOUND),
            (api.get_category, ApiErrorId.CATEGORY_NOT_FOUND),
            (api.get_mapping, ApiErrorId.MAPPING_NOT_FOUND),
            (api.get_supplier, ApiErrorId.SUPPLIER_NOT_FOUND),
            (api.get_laboratory, ApiErrorId.LABORATORY_NOT_FOUND),
            (api.get_accreditation, ApiErrorId.ACCREDITATION_NOT_FOUND),
            (api.get_product, ApiErrorId.PRODUCT_NOT_FOUND),
            (api.get_component_part, ApiErrorId.COMPONENT_PART_NOT_FOUND),
            (api.get_part_certificate, ApiErrorId.PART_CERTIFICATE_NOT_FOUND),
            (api.get_sampling_plan, ApiErrorId.SAMPLING_PLAN_NOT_FOUND),
            (api.get_test_order, ApiErrorId.TEST_ORDER_NOT_FOUND),
            (api.get_certificate, ApiErrorId.CERTIFICATE_NOT_FOUND),
            (api.get_production_batch, ApiErrorId.BATCH_NOT_FOUND),
            (api.get_case, ApiErrorId.CASE_NOT_FOUND),
            (api.get_material_change, ApiErrorId.MATERIAL_CHANGE_EVENT_NOT_FOUND),
        ]
        assert len(probes) == 15
        assert len({code for _, code in probes}) == 15

        for read, expected in probes:
            response = read(NON_EXISTENT_UUID, headers=ADMIN_HEADERS)
            validate_error(response, expected.value, 404)
            body = response.json()
            assert body["response_type"] == "error"
            assert body["data"]["message"]

    def test_an_action_path_reports_its_own_entity_and_never_its_parent(self, api):
        """PRD 2.11 rank 6: "reporting the leftmost missing reference with that entity's own
        not-found code (404). Applies to every endpoint that has a path parameter or a body
        foreign key."

        Design: Corner/errors/corner_errors_fifteen_not_found_codes_are_one_per_entity_and_never_interchangeable
        """
        fx.set_clock(api, STARTUP_CLOCK)
        validate_error(
            api.retire_mapping(NON_EXISTENT_UUID, headers=ADMIN_HEADERS),
            ApiErrorId.MAPPING_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.suspend_accreditation(
                NON_EXISTENT_UUID,
                {"suspension_reason": "Proficiency testing lapse"},
                headers=ADMIN_HEADERS,
            ),
            ApiErrorId.ACCREDITATION_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.record_reliance_documentation(
                NON_EXISTENT_UUID,
                {"reliance_decision": "RELY", "reliance_documentation_ref": "PKG-001"},
                headers=OFFICER_HEADERS,
            ),
            ApiErrorId.PART_CERTIFICATE_NOT_FOUND.value,
            404,
        )

    def test_a_missing_body_foreign_key_reports_that_key_s_entity(self, api):
        """PRD 2.11 rank 7: "Body foreign-key existence, second pass — every foreign key
        supplied in the body resolves, in declared field order, using the same per-entity
        not-found codes (404)."

        Design: Corner/errors/corner_errors_fifteen_not_found_codes_are_one_per_entity_and_never_interchangeable
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.booking_env(api)
        product_id = env["product"]["id"]

        validate_error(
            api.create_component_part(
                product_id,
                factories.component_part_payload(NON_EXISTENT_UUID),
                headers=ADMIN_HEADERS,
            ),
            ApiErrorId.SUPPLIER_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.create_test_order(
                factories.test_order_payload(
                    product_id,
                    NON_EXISTENT_UUID,
                    env["laboratory"]["id"],
                    env["rules"][0]["id"],
                ),
                headers=COORDINATOR_HEADERS,
            ),
            ApiErrorId.SAMPLING_PLAN_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.create_production_batch(
                product_id,
                factories.batch_payload(NON_EXISTENT_UUID),
                headers=MANAGER_HEADERS,
            ),
            ApiErrorId.CERTIFICATE_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.record_material_change(
                factories.material_change_payload(
                    product_id,
                    subject_type="COMPONENT_PART",
                    component_part_id=NON_EXISTENT_UUID,
                ),
                headers=ADMIN_HEADERS,
            ),
            ApiErrorId.COMPONENT_PART_NOT_FOUND.value,
            404,
        )

    def test_a_request_missing_two_references_reports_the_leftmost_one(self, api):
        """PRD 2.11 rank 6: "every resource named by a path segment or by a request-body foreign
        key exists, validated left to right across the path and then in declared body-field
        order, reporting the leftmost missing reference with that entity's own not-found code
        (404)."

        Design: Corner/errors/corner_errors_fifteen_not_found_codes_are_one_per_entity_and_never_interchangeable
        """
        fx.set_clock(api, STARTUP_CLOCK)
        validate_error(
            api.create_production_batch(
                NON_EXISTENT_UUID,
                factories.batch_payload(NON_EXISTENT_UUID),
                headers=MANAGER_HEADERS,
            ),
            ApiErrorId.PRODUCT_NOT_FOUND.value,
            404,
        )


class TestNineStateConflictCodes:
    """Each lifecycle owns its own 409, and the archived lock stays distinct from it."""

    def test_the_archived_lock_and_the_ordinary_product_state_error_are_two_codes(self, api):
        """PRD 2.11 rank 8: "Product archival — the product named or referenced by the request
        is not in `ARCHIVED` → `ERR_PRODUCT_ARCHIVED` (409)." PRD 2.11 rank 9: "Product
        certification state — the product is in a state the operation allows ... `CERTIFIED` for
        archival → `ERR_PRODUCT_STATE_INVALID` (409)."

        Design: Corner/errors/corner_errors_nine_state_conflict_codes_are_one_per_entity_lifecycle
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.certified_env(api)
        archived = validate_success(
            api.archive_product(env["product"]["id"], headers=ADMIN_HEADERS), 200
        )
        assert archived["certification_state"] == "ARCHIVED"

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

        draft_product = fx.create_product(api, env["category"]["id"])
        assert draft_product["certification_state"] == "DRAFT"
        validate_error(
            api.archive_product(draft_product["id"], headers=ADMIN_HEADERS),
            ApiErrorId.PRODUCT_STATE_INVALID.value,
            409,
        )
        assert fx.get_product(api, draft_product["id"])["version"] == draft_product["version"]

    def test_an_order_reported_before_testing_starts_hits_the_order_state_code(self, api):
        """PRD 2.11 rank 10: "Test order state — `SCHEDULED` for taking into testing,
        `IN_TESTING` for filing a report, and either `SCHEDULED` or `IN_TESTING` for
        cancellation → `ERR_ORDER_STATE_INVALID` (409)."

        Design: Corner/errors/corner_errors_nine_state_conflict_codes_are_one_per_entity_lifecycle
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.booking_env(api)
        order = fx.book_order(
            api,
            env["product"]["id"],
            env["plan"]["id"],
            env["laboratory"]["id"],
            env["rules"][0]["id"],
        )
        assert order["order_state"] == "SCHEDULED"

        validate_error(
            api.report_result(
                order["id"],
                {"measured_value": 10},
                headers=make_laboratory_user_headers(env["laboratory"]["id"]),
            ),
            ApiErrorId.ORDER_STATE_INVALID.value,
            409,
        )
        unchanged = fx.get_order(api, order["id"])
        assert unchanged["order_state"] == "SCHEDULED"
        assert unchanged["version"] == order["version"]

    def test_a_second_activation_hits_the_plan_state_code(self, api):
        """PRD 2.11 rank 11: "Sampling plan state — `DRAFT` for activation, either `ACTIVE` or
        `RESAMPLE_DUE` for periodic review, and either `ACTIVE` or `RESAMPLE_DUE` to accept a
        new test order → `ERR_PLAN_STATE_INVALID` (409)."

        Design: Corner/errors/corner_errors_nine_state_conflict_codes_are_one_per_entity_lifecycle
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.booking_env(api)
        assert env["plan"]["plan_state"] == "ACTIVE"

        validate_error(
            api.activate_sampling_plan(env["plan"]["id"], headers=COORDINATOR_HEADERS),
            ApiErrorId.PLAN_STATE_INVALID.value,
            409,
        )
        assert fx.get_plan(api, env["plan"]["id"])["version"] == env["plan"]["version"]

    def test_furnishing_a_draft_certificate_hits_the_certificate_axis_code(self, api):
        """PRD 3.7: "This is the single cross-axis coupling in the whole machine: furnishing
        requires the issuance axis to have reached `ISSUED`, and attempting it on a draft is
        refused with `ERR_CERTIFICATE_STATE_INVALID`."

        Design: Corner/errors/corner_errors_nine_state_conflict_codes_are_one_per_entity_lifecycle
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.evidence_complete_env(api)
        product = fx.get_product(api, env["product"]["id"])
        certificate = fx.draft_certificate(api, product["id"], product["version"])
        assert certificate["issuance_status"] == "DRAFT"
        assert certificate["accompaniment_status"] == "NOT_FURNISHED"

        validate_error(
            api.furnish_certificate(certificate["id"], headers=MANAGER_HEADERS),
            ApiErrorId.CERTIFICATE_STATE_INVALID.value,
            409,
        )
        unchanged = fx.get_certificate(api, certificate["id"])
        assert unchanged["accompaniment_status"] == "NOT_FURNISHED"
        assert unchanged["version"] == certificate["version"]

    def test_rescinding_a_held_batch_hits_the_batch_state_code(self, api):
        """PRD 2.11 rank 13: "Production batch state — `HELD` for release, `RELEASED` for
        rescinding a release, and either `HELD` or `STOP_DISTRIBUTION` for tracking-label edits
        (a `DESTROYED` batch accepts no label edit) → `ERR_BATCH_STATE_INVALID` (409)."

        Design: Corner/errors/corner_errors_nine_state_conflict_codes_are_one_per_entity_lifecycle
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.distributed_env(api, release=False)
        batch = env["batches"][0]
        assert batch["distribution_state"] == "HELD"

        validate_error(
            api.rescind_release(batch["id"], headers=MANAGER_HEADERS),
            ApiErrorId.BATCH_STATE_INVALID.value,
            409,
        )
        unchanged = fx.get_batch(api, batch["id"])
        assert unchanged["distribution_state"] == "HELD"
        assert unchanged["release_rescind_count"] == 0
        assert unchanged["version"] == batch["version"]

    def test_closing_an_open_case_hits_the_case_state_code(self, api):
        """PRD 2.11 rank 14: "Noncompliance case state — `OPEN` for issuing stop-distribution,
        either `STOP_DISTRIBUTION_ISSUED` or `RETEST_FAILED` for ordering a retest, either
        `RETEST_PASSED` or `CORRECTIVE_ACTION_APPROVED` for recording a corrective action, and
        `CORRECTIVE_ACTION_APPROVED` for closure → `ERR_CASE_STATE_INVALID` (409)."

        Design: Corner/errors/corner_errors_nine_state_conflict_codes_are_one_per_entity_lifecycle
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.failed_case_env(api)
        case = env["case"]
        assert case["case_state"] == "OPEN"

        validate_error(
            api.close_case(case["id"], headers=OFFICER_HEADERS),
            ApiErrorId.CASE_STATE_INVALID.value,
            409,
        )
        unchanged = fx.get_case(api, case["id"])
        assert unchanged["case_state"] == "OPEN"
        assert unchanged["closed_by_user_id"] is None
        assert unchanged["version"] == case["version"]

    def test_a_second_reliance_decision_hits_the_part_certificate_state_code(self, api):
        """PRD 3.4: "In both branches the certificate must currently be in `reliance_state`
        `SUBMITTED`" and "a second decision against it is refused with
        `ERR_PART_CERTIFICATE_STATE_INVALID`."

        Design: Corner/errors/corner_errors_nine_state_conflict_codes_are_one_per_entity_lifecycle
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.reliance_env(api, rely=True)
        certificate = env["part_certificates"][0]
        assert certificate["reliance_state"] == "RELIED_UPON"

        validate_error(
            api.record_reliance_documentation(
                certificate["id"],
                {"reliance_decision": "REJECT", "reliance_documentation_ref": "PKG-002"},
                headers=OFFICER_HEADERS,
            ),
            ApiErrorId.PART_CERTIFICATE_STATE_INVALID.value,
            409,
        )
        unchanged = fx.get_part_certificate(api, certificate["id"])
        assert unchanged["reliance_state"] == "RELIED_UPON"
        assert unchanged["version"] == certificate["version"]

    def test_a_second_suspension_hits_the_accreditation_state_code(self, api):
        """PRD 3.2: "Both `SUSPENDED` and `EXPIRED` are terminal, and a second suspension attempt
        against a row already in either is refused with `ERR_ACCREDITATION_STATE_INVALID`."

        Design: Corner/errors/corner_errors_nine_state_conflict_codes_are_one_per_entity_lifecycle
        """
        fx.set_clock(api, STARTUP_CLOCK)
        rule = fx.create_rule(api)
        laboratory = fx.create_laboratory(api)
        fx.attest(api, laboratory["id"], "2027-12-31T00:00:00Z")
        scope = fx.accredit(api, laboratory["id"], rule["id"])
        suspended = fx.suspend_accreditation(api, scope["id"], "Proficiency testing lapse")
        assert suspended["accreditation_state"] == "SUSPENDED"

        validate_error(
            api.suspend_accreditation(
                scope["id"],
                {"suspension_reason": "Repeat finding"},
                headers=ADMIN_HEADERS,
            ),
            ApiErrorId.ACCREDITATION_STATE_INVALID.value,
            409,
        )
        unchanged = validate_success(
            api.get_accreditation(scope["id"], headers=ADMIN_HEADERS), 200
        )
        assert unchanged["accreditation_state"] == "SUSPENDED"
        assert unchanged["version"] == suspended["version"]


class TestStatusDisciplineAcrossTheNon404Families:
    """One probe per non-404 status the domain uses, so the statuses cannot drift."""

    def test_the_five_families_answer_five_different_statuses(self, api):
        """PRD 5 pins each code to its status: `ERR_INVALID_REQUEST` 400,
        `ERR_PRODUCT_TESTING_BUDGET_EXCEEDED` 402, `ERR_MAPPING_DUPLICATE` 409,
        `ERR_STALE_PRODUCT_VERSION` 412 and `ERR_BATCH_OUTSIDE_CERTIFICATE_COVERAGE` 422.

        Design: Corner/errors/corner_errors_status_code_discipline_across_the_five_non_404_families
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.evidence_complete_env(api, product={"testing_budget_cents": 20000})
        product = fx.get_product(api, env["product"]["id"])
        assert product["certification_state"] == "EVIDENCE_COMPLETE"
        assert env["orders"][0]["invoice_total_cents"] == 18700

        observed = {}

        shape = api.create_product(
            factories.product_payload(env["category"]["id"], projected_annual_units=0),
            headers=ADMIN_HEADERS,
        )
        validate_error(shape, ApiErrorId.INVALID_REQUEST.value, 400)
        observed[ApiErrorId.INVALID_REQUEST.value] = shape.status_code

        budget = api.create_test_order(
            factories.test_order_payload(
                product["id"],
                env["plan"]["id"],
                env["laboratory"]["id"],
                env["rules"][0]["id"],
            ),
            headers=COORDINATOR_HEADERS,
        )
        validate_error(budget, ApiErrorId.PRODUCT_TESTING_BUDGET_EXCEEDED.value, 402)
        observed[ApiErrorId.PRODUCT_TESTING_BUDGET_EXCEEDED.value] = budget.status_code

        duplicate = api.create_mapping(
            factories.mapping_payload(env["category"]["id"], env["rules"][0]["id"]),
            headers=ADMIN_HEADERS,
        )
        validate_error(duplicate, ApiErrorId.MAPPING_DUPLICATE.value, 409)
        observed[ApiErrorId.MAPPING_DUPLICATE.value] = duplicate.status_code

        stale = api.draft_certificate(
            product["id"],
            factories.certificate_payload(product["version"] - 1),
            headers=OFFICER_HEADERS,
        )
        validate_error(stale, ApiErrorId.STALE_PRODUCT_VERSION.value, 412)
        observed[ApiErrorId.STALE_PRODUCT_VERSION.value] = stale.status_code

        certificate = fx.draft_certificate(api, product["id"], product["version"])
        fx.issue_certificate(api, certificate["id"])
        coverage = api.create_production_batch(
            product["id"],
            factories.batch_payload(certificate["id"], produced_on="2026-09-15T00:00:00Z"),
            headers=MANAGER_HEADERS,
        )
        validate_error(coverage, ApiErrorId.BATCH_OUTSIDE_CERTIFICATE_COVERAGE.value, 422)
        observed[ApiErrorId.BATCH_OUTSIDE_CERTIFICATE_COVERAGE.value] = coverage.status_code

        assert observed == {
            ApiErrorId.INVALID_REQUEST.value: 400,
            ApiErrorId.PRODUCT_TESTING_BUDGET_EXCEEDED.value: 402,
            ApiErrorId.MAPPING_DUPLICATE.value: 409,
            ApiErrorId.STALE_PRODUCT_VERSION.value: 412,
            ApiErrorId.BATCH_OUTSIDE_CERTIFICATE_COVERAGE.value: 422,
        }
        assert len(set(observed.values())) == 5

        for response in (shape, budget, duplicate, stale, coverage):
            body = response.json()
            assert body["response_type"] == "error"
            assert set(body["data"].keys()) == {"error_id", "message"}
            assert body["data"]["message"]


class TestInvalidRequestCoversEveryShapeRule:
    """The single 400 code answers presence, enum, range, pattern, type and pagination."""

    def test_six_structurally_different_shape_violations_all_answer_the_same_code(self, api):
        """PRD 2.11 rank 5: "Request shape — every required field present, every enum value
        inside its declared set, every regex-constrained string matching its pattern, every
        numeric field inside its declared range, and on list endpoints `limit` between 1 and 100
        inclusive with `offset` at least 0 → `ERR_INVALID_REQUEST` (400)."

        Design: Corner/errors/corner_errors_invalid_request_covers_every_shape_rule_declared_on_the_inputs
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.distributed_env(api, release=False)

        missing_field = factories.rule_payload()
        missing_field.pop("periodic_interval_months")
        probes = [
            api.create_rule(missing_field, headers=ADMIN_HEADERS),
            api.create_rule(
                factories.rule_payload(hazard_class="SHARP_EDGE"), headers=ADMIN_HEADERS
            ),
            api.create_rule(
                factories.rule_payload(severity_weight=11), headers=ADMIN_HEADERS
            ),
            api.create_production_batch(
                env["product"]["id"],
                factories.batch_payload(
                    env["certificate"]["id"], batch_code="RVR090_000601"
                ),
                headers=MANAGER_HEADERS,
            ),
            api.create_product(
                factories.product_payload(
                    env["category"]["id"], projected_annual_units="6000"
                ),
                headers=ADMIN_HEADERS,
            ),
            api.list_products({"offset": -1}, headers=ADMIN_HEADERS),
        ]
        for response in probes:
            validate_error(response, ApiErrorId.INVALID_REQUEST.value, 400)

    def test_each_refused_bound_has_an_accepted_neighbour(self, api):
        """PRD 3.1: "`severity_weight`, an integer between 1 and 10 inclusive". PRD 3.8: "The
        `batch_code` must match a strict format: 3 to 10 uppercase letters or digits, then a
        hyphen, then exactly 6 digits". PRD 2.3: "`limit` ... must be at least 1, and must not
        exceed 100. `offset` ... defaults to 0 and must not be negative."

        Design: Corner/errors/corner_errors_invalid_request_covers_every_shape_rule_declared_on_the_inputs
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.distributed_env(api, release=False)

        accepted_rule = validate_success(
            api.create_rule(factories.rule_payload(severity_weight=10), headers=ADMIN_HEADERS),
            201,
        )
        assert accepted_rule["severity_weight"] == 10

        accepted_batch = validate_success(
            api.create_production_batch(
                env["product"]["id"],
                factories.batch_payload(
                    env["certificate"]["id"], batch_code="RVR090-000601"
                ),
                headers=MANAGER_HEADERS,
            ),
            201,
        )
        assert accepted_batch["batch_code"] == "RVR090-000601"

        for params in ({"offset": 0}, {"limit": 1}, {"limit": 100}):
            validate_paginated(api.list_products(params, headers=ADMIN_HEADERS))
        for params in ({"offset": -1}, {"limit": 0}, {"limit": 101}):
            validate_error(
                api.list_products(params, headers=ADMIN_HEADERS),
                ApiErrorId.INVALID_REQUEST.value,
                400,
            )

    def test_a_refused_shape_creates_no_row(self, api):
        """PRD 2.11 rank 5: "Request shape — every required field present, every enum value
        inside its declared set ... → `ERR_INVALID_REQUEST` (400). Applies to every endpoint."

        Design: Corner/errors/corner_errors_invalid_request_covers_every_shape_rule_declared_on_the_inputs
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.distributed_env(api, release=False)
        before_batches, before_meta = validate_paginated(
            api.list_production_batches(
                {"product_id": env["product"]["id"]}, headers=MANAGER_HEADERS
            )
        )

        for batch_code in ("RVR090_000601", "AB-000601", "RVR090-00060"):
            validate_error(
                api.create_production_batch(
                    env["product"]["id"],
                    factories.batch_payload(env["certificate"]["id"], batch_code=batch_code),
                    headers=MANAGER_HEADERS,
                ),
                ApiErrorId.INVALID_REQUEST.value,
                400,
            )

        after_batches, after_meta = validate_paginated(
            api.list_production_batches(
                {"product_id": env["product"]["id"]}, headers=MANAGER_HEADERS
            )
        )
        assert after_meta["total_count"] == before_meta["total_count"]
        assert [row["id"] for row in after_batches] == [row["id"] for row in before_batches]


class TestErrorEnvelopeIsIdenticalAcrossStatuses:
    """401, 403, 404 and 412 all answer in the same three-key envelope."""

    def test_four_statuses_share_one_envelope_shape(self, api):
        """PRD 2.2: "The `meta` object for error responses contains only `api_request_id` and
        `api_request_timestamp`." The error body carries `response_type` "error" and a `data`
        object holding `error_id` and `message`.

        Design: Corner/errors/corner_errors_error_envelope_is_identical_across_every_status
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.corrective_action_env(api)
        product_id = env["product"]["id"]
        case = fx.get_case(api, env["case"]["id"])
        assert case["case_state"] == "CORRECTIVE_ACTION_APPROVED"

        unauthenticated = api.get_product(product_id, headers=None)
        validate_error(unauthenticated, ApiErrorId.UNAUTHENTICATED.value, 401)
        forbidden = api.get_product(
            product_id, headers=make_supplier_user_headers(env["supplier"]["id"])
        )
        validate_error(forbidden, ApiErrorId.ROLE_NOT_PERMITTED.value, 403)
        missing = api.get_product(NON_EXISTENT_UUID, headers=ADMIN_HEADERS)
        validate_error(missing, ApiErrorId.PRODUCT_NOT_FOUND.value, 404)
        stale = api.file_corrective_action(
            case["id"],
            {
                "expected_case_version": case["version"] - 1,
                "corrective_action_ref": "CAPA-STALE",
            },
            headers=OFFICER_HEADERS,
        )
        validate_error(stale, ApiErrorId.STALE_CASE_VERSION.value, 412)

        responses = [unauthenticated, forbidden, missing, stale]
        assert [response.status_code for response in responses] == [401, 403, 404, 412]

        request_ids = []
        for response in responses:
            body = response.json()
            assert set(body.keys()) == {"meta", "response_type", "data"}
            assert body["response_type"] == "error"
            assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}
            assert body["meta"]["api_request_id"].startswith("req_")
            assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
            assert set(body["data"].keys()) == {"error_id", "message"}
            assert isinstance(body["data"]["message"], str) and body["data"]["message"]
            request_ids.append(body["meta"]["api_request_id"])
        assert len(set(request_ids)) == 4

    def test_the_success_envelope_never_carries_an_error_id(self, api):
        """PRD 2.2: "The `response_type` is either "object" for a single resource or "array" for
        a list of resources." The success envelope's `data` holds the resource itself.

        Design: Corner/errors/corner_errors_error_envelope_is_identical_across_every_status
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.booking_env(api)

        response = api.get_product(env["product"]["id"], headers=ADMIN_HEADERS)
        body = response.json()
        assert response.status_code == 200
        assert set(body.keys()) == {"meta", "response_type", "data"}
        assert body["response_type"] == "object"
        assert body["data"]["id"] == env["product"]["id"]
        assert "error_id" not in body["data"]
        assert "error_id" not in body["meta"]
        assert body["meta"]["api_request_id"].startswith("req_")

        listing = api.list_products({"category_id": env["category"]["id"]}, headers=ADMIN_HEADERS)
        listing_body = listing.json()
        assert listing_body["response_type"] == "array"
        assert isinstance(listing_body["data"], list)
        assert "error_id" not in listing_body["meta"]
