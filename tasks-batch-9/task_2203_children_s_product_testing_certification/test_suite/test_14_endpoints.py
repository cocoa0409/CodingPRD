"""Endpoint contract: status codes, action semantics, computed reads and list shapes."""

from test_helpers import (
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
    COORDINATOR_HEADERS,
    MANAGER_HEADERS,
    OFFICER_HEADERS,
    make_laboratory_user_headers,
    make_supplier_user_headers,
)


STARTUP_CLOCK = "2026-08-01T00:00:00Z"
LATE_ATTESTATION = "2027-12-31T00:00:00Z"


def _extra_lab(api, rule_ids):
    """A second attested laboratory accredited for every rule handed to it."""
    lab = fx.create_laboratory(api)
    fx.attest(api, lab["id"], LATE_ATTESTATION)
    for rule_id in rule_ids:
        fx.accredit(api, lab["id"], rule_id)
    return lab


class TestStatusCodeContract:
    """Creation answers 201; state-advancing writes and every read answer 200."""

    def test_every_row_creating_post_answers_201_and_its_read_answers_200(self, api):
        """PRD 4: "Endpoints that create a new resource return HTTP 201 with the created
        resource in `data`. ... Read endpoints return HTTP 200, with single reads carrying
        `response_type` `object`."

        Design: Corner/endpoints/corner_endpoints_status_codes_split_creation_from_action_and_read
        """
        fx.set_clock(api, STARTUP_CLOCK)
        rule = validate_success(
            api.create_rule(factories.rule_payload(), headers=ADMIN_HEADERS), 201
        )
        category = validate_success(
            api.create_category(factories.category_payload(), headers=ADMIN_HEADERS), 201
        )
        mapping = validate_success(
            api.create_mapping(
                factories.mapping_payload(category["id"], rule["id"]), headers=ADMIN_HEADERS
            ),
            201,
        )
        supplier = validate_success(
            api.create_supplier(factories.supplier_payload(), headers=ADMIN_HEADERS), 201
        )
        laboratory = validate_success(
            api.create_laboratory(factories.laboratory_payload(), headers=ADMIN_HEADERS), 201
        )
        accreditation = validate_success(
            api.create_accreditation(
                laboratory["id"],
                factories.accreditation_payload(rule["id"]),
                headers=ADMIN_HEADERS,
            ),
            201,
        )
        product = validate_success(
            api.create_product(
                factories.product_payload(category["id"]), headers=ADMIN_HEADERS
            ),
            201,
        )
        # The product is read back before its bill of materials is built: PRD 3.3
        # makes a part addition bump the owning product's version.
        for created, response in (
            (rule, api.get_rule(rule["id"], headers=ADMIN_HEADERS)),
            (category, api.get_category(category["id"], headers=ADMIN_HEADERS)),
            (mapping, api.get_mapping(mapping["id"], headers=ADMIN_HEADERS)),
            (supplier, api.get_supplier(supplier["id"], headers=ADMIN_HEADERS)),
            (laboratory, api.get_laboratory(laboratory["id"], headers=ADMIN_HEADERS)),
            (
                accreditation,
                api.get_accreditation(accreditation["id"], headers=ADMIN_HEADERS),
            ),
            (product, api.get_product(product["id"], headers=ADMIN_HEADERS)),
        ):
            read = validate_success(response, 200)
            assert is_valid_uuid(read["id"])
            assert read["id"] == created["id"]
            assert read["created_at"] == created["created_at"]
            assert read["updated_at"] == created["updated_at"]
            assert read["version"] == created["version"] == 1
            assert response.json()["response_type"] == "object"

        part = validate_success(
            api.create_component_part(
                product["id"],
                factories.component_part_payload(supplier["id"]),
                headers=ADMIN_HEADERS,
            ),
            201,
        )

        for created, response in (
            (part, api.get_component_part(part["id"], headers=ADMIN_HEADERS)),
        ):
            read = validate_success(response, 200)
            assert is_valid_uuid(read["id"])
            assert read["id"] == created["id"]
            assert read["created_at"] == created["created_at"]
            assert read["updated_at"] == created["updated_at"]
            assert read["version"] == created["version"] == 1
            assert response.json()["response_type"] == "object"

    def test_the_two_laboratory_sub_path_posts_return_200_with_the_mutated_row(self, api):
        """PRD 4: "Endpoints that modify an existing resource — including every
        state-transition action, every attestation or flag update, and the logical-clock
        setter — return HTTP 200 with the updated resource in `data`."

        Design: Corner/endpoints/corner_endpoints_status_codes_split_creation_from_action_and_read
        """
        fx.set_clock(api, STARTUP_CLOCK)
        laboratory = fx.create_laboratory(api)
        assert laboratory["version"] == 1

        attested = validate_success(
            api.record_attestation(
                laboratory["id"],
                {"attestation_valid_through": LATE_ATTESTATION},
                headers=ADMIN_HEADERS,
            ),
            200,
        )
        assert attested["id"] == laboratory["id"]
        assert attested["influence_attestation_state"] == "CURRENT"
        assert attested["version"] == 2

        barred = validate_success(
            api.set_laboratory_operational_state(
                laboratory["id"], {"operational_state": "BARRED"}, headers=ADMIN_HEADERS
            ),
            200,
        )
        assert barred["id"] == laboratory["id"]
        assert barred["operational_state"] == "BARRED"
        assert barred["version"] == 3

    def test_every_state_advancing_action_answers_200(self, api):
        """PRD 4: "Endpoints that modify an existing resource — including every
        state-transition action ... — return HTTP 200 with the updated resource in `data`."

        Design: Corner/endpoints/corner_endpoints_status_codes_split_creation_from_action_and_read
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.scoped_product_env(api, submit=False)
        product_id = env["product"]["id"]

        scoped = validate_success(
            api.submit_for_certification(
                product_id, {"evidence_path": "FULL_PRODUCT_TEST"},
                headers=COORDINATOR_HEADERS,
            ),
            200,
        )
        assert scoped["certification_state"] == "FULL_TEST_PROGRAM"

        plan = validate_success(
            api.create_sampling_plan(
                product_id, factories.sampling_plan_payload(), headers=COORDINATOR_HEADERS
            ),
            201,
        )
        activated = validate_success(
            api.activate_sampling_plan(plan["id"], headers=COORDINATOR_HEADERS), 200
        )
        assert activated["plan_state"] == "ACTIVE"

        order = validate_success(
            api.create_test_order(
                factories.test_order_payload(
                    product_id, plan["id"], env["laboratory"]["id"], env["rules"][0]["id"]
                ),
                headers=COORDINATOR_HEADERS,
            ),
            201,
        )
        lab_headers = make_laboratory_user_headers(env["laboratory"]["id"])
        started = validate_success(api.start_testing(order["id"], headers=lab_headers), 200)
        assert started["order_state"] == "IN_TESTING"
        reported = validate_success(
            api.report_result(order["id"], {"measured_value": 10}, headers=lab_headers), 200
        )
        assert reported["order_state"] == "REPORTED_PASS"

        current = fx.get_product(api, product_id)
        certificate = validate_success(
            api.draft_certificate(
                product_id,
                factories.certificate_payload(current["version"]),
                headers=OFFICER_HEADERS,
            ),
            201,
        )
        issued = validate_success(
            api.issue_certificate(certificate["id"], headers=OFFICER_HEADERS), 200
        )
        assert issued["issuance_status"] == "ISSUED"
        furnished = validate_success(
            api.furnish_certificate(certificate["id"], headers=MANAGER_HEADERS), 200
        )
        assert furnished["accompaniment_status"] == "FURNISHED"

        batch = validate_success(
            api.create_production_batch(
                product_id,
                factories.batch_payload(certificate["id"]),
                headers=MANAGER_HEADERS,
            ),
            201,
        )
        labelled = validate_success(
            api.update_tracking_label(
                batch["id"], factories.tracking_label_payload(), headers=MANAGER_HEADERS
            ),
            200,
        )
        assert labelled["tracking_label_compliant"] is True
        released = validate_success(api.release_batch(batch["id"], headers=MANAGER_HEADERS), 200)
        assert released["distribution_state"] == "RELEASED"
        rescinded = validate_success(
            api.rescind_release(batch["id"], headers=MANAGER_HEADERS), 200
        )
        assert rescinded["distribution_state"] == "HELD"

    def test_list_reads_answer_200_with_the_array_response_type(self, api):
        """PRD 4: "list reads carrying `response_type` `array` together with the pagination
        fields in `meta`."

        Design: Corner/endpoints/corner_endpoints_status_codes_split_creation_from_action_and_read
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.booking_env(api)
        response = api.list_sampling_plans(
            {"product_id": env["product"]["id"]}, headers=COORDINATOR_HEADERS
        )
        rows, meta = validate_paginated(response)
        assert response.status_code == 200
        assert response.json()["response_type"] == "array"
        assert [row["id"] for row in rows] == [env["plan"]["id"]]
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert meta["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(meta["api_request_timestamp"])


class TestEmptyInputActionEndpoint:
    """Plan activation takes no input; the path and the clock carry the whole effect."""

    def _draft_plan_env(self, api):
        env = fx.scoped_product_env(api, product={"projected_annual_units": 6000})
        env["draft_plan"] = fx.create_plan(api, env["product"]["id"])
        return env

    def test_activation_shows_every_declared_side_effect_in_one_response(self, api):
        """PRD 3.5: "Activation stamps both `activated_at` and `last_verified_at` with the
        logical clock instant, recomputes `periodic_due_at`, resets `resample_trigger` to
        `NONE` on the resampling re-entry edge, and increments the plan's `version` by 1."

        Design: Corner/endpoints/corner_endpoints_action_endpoint_with_empty_input_still_mutates_and_bumps_version
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = self._draft_plan_env(api)
        plan = env["draft_plan"]
        assert plan["plan_state"] == "DRAFT"
        assert plan["units_authorized"] == 6
        assert plan["version"] == 1

        activated = validate_success(
            api.activate_sampling_plan(plan["id"], headers=COORDINATOR_HEADERS), 200
        )
        assert activated["plan_state"] == "ACTIVE"
        assert activated["activated_at"] == STARTUP_CLOCK
        assert activated["last_verified_at"] == STARTUP_CLOCK
        assert activated["units_authorized"] == 6
        assert activated["units_committed"] == 0
        assert activated["units_available"] == 6
        assert activated["periodic_due_at"] == "2027-08-01T00:00:00Z"
        assert activated["resample_trigger"] == "NONE"
        assert activated["version"] == 2
        assert fx.get_plan(api, plan["id"]) == activated

    def test_the_same_call_a_second_time_is_refused_and_changes_nothing(self, api):
        """PRD 2.11 rank 11: "Sampling plan state — `DRAFT` for activation ... →
        `ERR_PLAN_STATE_INVALID` (409). Applies to plan activation, periodic review, and test
        order booking."

        Design: Corner/endpoints/corner_endpoints_action_endpoint_with_empty_input_still_mutates_and_bumps_version
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = self._draft_plan_env(api)
        activated = fx.activate_plan(api, env["draft_plan"]["id"])
        assert fx.get_product(api, env["product"]["id"])["certification_state"] == (
            "FULL_TEST_PROGRAM"
        )

        validate_error(
            api.activate_sampling_plan(env["draft_plan"]["id"], headers=COORDINATOR_HEADERS),
            ApiErrorId.PLAN_STATE_INVALID.value,
            409,
        )
        unchanged = fx.get_plan(api, env["draft_plan"]["id"])
        assert unchanged["activated_at"] == activated["activated_at"]
        assert unchanged["version"] == activated["version"]


LEAD_METHOD = "CPSC-CH-E1002-08"
PHTHALATE_METHOD = "CPSC-CH-C1001-09"
TWO_METHOD_RULES = [
    {"test_method_code": LEAD_METHOD, "hazard_class": "LEAD_CONTENT"},
    {"test_method_code": PHTHALATE_METHOD, "hazard_class": "PHTHALATES"},
]


class TestComputedSummaryRead:
    """The compliance summary is recomputed per request and is stored nowhere."""

    def test_the_summary_is_derived_and_carries_no_row_identity(self, api):
        """PRD 3.3: "Alongside the plain product read, a computed **compliance summary** read
        recomputes rule derivation, the gap score, the posture and both unit ledgers on demand
        without mutating anything."

        Design: Corner/endpoints/corner_endpoints_computed_read_is_derived_and_never_stored
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.booking_env(api, rule_specs=TWO_METHOD_RULES)
        product_id = env["product"]["id"]
        rule_ids = {rule["id"] for rule in env["rules"]}

        before = fx.get_product(api, product_id)
        summary = fx.get_summary(api, product_id)
        assert summary["product_id"] == product_id
        assert set(summary["required_rule_ids"]) == rule_ids
        assert summary["covered_rule_ids"] == []
        assert set(summary["uncovered_rule_ids"]) == rule_ids
        assert summary["risk_weighted_gap_score"] == 100
        assert summary["compliance_posture"] == "RESTRICTED"
        assert summary["open_case_count"] == 0
        assert summary["resample_due_plan_count"] == 0
        assert summary["units_held"] == 0
        assert summary["units_released"] == 0
        assert summary["units_stopped"] == 0
        assert summary["units_destroyed"] == 0
        assert summary["units_total_produced"] == 0
        assert summary["ledger_balanced"] is True
        for absent in ("id", "version", "created_at", "updated_at"):
            assert absent not in summary

        after = fx.get_product(api, product_id)
        assert after["version"] == before["version"]
        assert after["updated_at"] == before["updated_at"]
        assert fx.get_summary(api, product_id) == summary

    def test_the_summary_tracks_evidence_and_penalties_as_they_land(self, api):
        """PRD 3.3: "It reports `product_id`, the derived `required_rule_ids`, the split of
        those rules into `covered_rule_ids` and `uncovered_rule_ids`, the recomputed
        `risk_weighted_gap_score` and `compliance_posture`, the `open_case_count` and
        `resample_due_plan_count` that fed the penalties."

        Design: Corner/endpoints/corner_endpoints_computed_read_is_derived_and_never_stored
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.booking_env(api, rule_specs=TWO_METHOD_RULES)
        product_id = env["product"]["id"]
        first_rule, second_rule = env["rules"][0], env["rules"][1]

        fx.run_order_to_pass(
            api,
            product_id,
            env["plan"]["id"],
            env["laboratory"]["id"],
            first_rule["id"],
        )
        half_covered = fx.get_summary(api, product_id)
        assert half_covered["covered_rule_ids"] == [first_rule["id"]]
        assert half_covered["uncovered_rule_ids"] == [second_rule["id"]]
        assert half_covered["risk_weighted_gap_score"] == 50
        assert half_covered["compliance_posture"] == "RESTRICTED"
        assert half_covered["open_case_count"] == 0

        fx.fail_an_order(api, env, rule_index=1, measured_value=250)
        failed = fx.get_summary(api, product_id)
        assert failed["covered_rule_ids"] == [first_rule["id"]]
        assert failed["uncovered_rule_ids"] == [second_rule["id"]]
        assert failed["open_case_count"] == 1
        assert failed["risk_weighted_gap_score"] == 65
        assert failed["compliance_posture"] == "SUSPENDED"

    def test_only_the_four_opaque_roles_may_read_the_summary(self, api):
        """PRD 4: the compliance-summary read is available to "ComplianceAdministrator,
        TestCoordinator, CertificationOfficer, DistributionManager".

        Design: Corner/endpoints/corner_endpoints_computed_read_is_derived_and_never_stored
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.booking_env(api, rule_specs=TWO_METHOD_RULES)
        product_id = env["product"]["id"]

        bodies = [
            validate_success(api.get_compliance_summary(product_id, headers=headers), 200)
            for headers in (
                ADMIN_HEADERS,
                COORDINATOR_HEADERS,
                OFFICER_HEADERS,
                MANAGER_HEADERS,
            )
        ]
        assert bodies[1:] == bodies[:-1]

        for headers in (
            make_laboratory_user_headers(env["laboratory"]["id"]),
            make_supplier_user_headers(env["supplier"]["id"]),
        ):
            validate_error(
                api.get_compliance_summary(product_id, headers=headers),
                ApiErrorId.ROLE_NOT_PERMITTED.value,
                403,
            )


class TestFilteredListEndpoint:
    """Test order filters intersect, and the page window rides on top of the filter."""

    def _six_orders(self, api):
        env = fx.booking_env(api, product={"projected_annual_units": 25000})
        assert env["plan"]["units_authorized"] == 13
        rule_id = env["rules"][0]["id"]
        first_lab = env["laboratory"]["id"]
        second_lab = _extra_lab(api, [rule_id])["id"]
        env["first_lab"] = first_lab
        env["second_lab"] = second_lab
        env["first_lab_orders"] = [
            fx.book_order(api, env["product"]["id"], env["plan"]["id"], first_lab, rule_id)
            for _ in range(3)
        ]
        env["second_lab_orders"] = [
            fx.book_order(api, env["product"]["id"], env["plan"]["id"], second_lab, rule_id)
            for _ in range(3)
        ]
        cancelled = env["first_lab_orders"][2]
        validate_success(api.cancel_test_order(cancelled["id"], headers=COORDINATOR_HEADERS), 200)
        env["cancelled_order"] = cancelled
        return env

    def test_two_filters_narrow_the_set_to_their_intersection(self, api):
        """PRD 3.6: "Orders may be listed filtered by `product_id`, `sampling_plan_id`,
        `laboratory_id`, `rule_id`, `order_state` and `is_retest`."

        Design: Corner/endpoints/corner_endpoints_filtered_list_combines_filters_conjunctively_and_paginates
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = self._six_orders(api)
        product_id = env["product"]["id"]

        rows, meta = validate_paginated(
            api.list_test_orders(
                {
                    "product_id": product_id,
                    "laboratory_id": env["first_lab"],
                    "order_state": "SCHEDULED",
                },
                headers=COORDINATOR_HEADERS,
            )
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {
            env["first_lab_orders"][0]["id"],
            env["first_lab_orders"][1]["id"],
        }
        assert all(row["laboratory_id"] == env["first_lab"] for row in rows)
        assert all(row["order_state"] == "SCHEDULED" for row in rows)

        cancelled_rows, cancelled_meta = validate_paginated(
            api.list_test_orders(
                {
                    "product_id": product_id,
                    "laboratory_id": env["first_lab"],
                    "order_state": "CANCELLED",
                },
                headers=COORDINATOR_HEADERS,
            )
        )
        assert cancelled_meta["total_count"] == 1
        assert [row["id"] for row in cancelled_rows] == [env["cancelled_order"]["id"]]

        empty_rows, empty_meta = validate_paginated(
            api.list_test_orders(
                {
                    "product_id": product_id,
                    "laboratory_id": env["second_lab"],
                    "order_state": "CANCELLED",
                },
                headers=COORDINATOR_HEADERS,
            )
        )
        assert empty_rows == []
        assert empty_meta["total_count"] == 0
        assert empty_meta["has_more"] is False

    def test_the_page_window_slices_the_filtered_set_without_gaps_or_repeats(self, api):
        """PRD 2.3: "List responses carry four pagination fields inside `meta`: the echoed
        `limit`, the echoed `offset`, `total_count` giving the number of rows matching the
        filter before pagination is applied, and `has_more`, which is true exactly when rows
        remain beyond the current page."

        Design: Corner/endpoints/corner_endpoints_filtered_list_combines_filters_conjunctively_and_paginates
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = self._six_orders(api)
        product_id = env["product"]["id"]

        all_rows, all_meta = validate_paginated(
            api.list_test_orders({"product_id": product_id}, headers=COORDINATOR_HEADERS)
        )
        assert all_meta["total_count"] == 6
        assert all_meta["limit"] == 10
        assert all_meta["offset"] == 0
        assert all_meta["has_more"] is False
        assert len(all_rows) == 6

        seen = []
        for offset, expect_more in ((0, True), (2, True), (4, False)):
            rows, meta = validate_paginated(
                api.list_test_orders(
                    {"product_id": product_id, "limit": 2, "offset": offset},
                    headers=COORDINATOR_HEADERS,
                )
            )
            assert meta["limit"] == 2
            assert meta["offset"] == offset
            assert meta["total_count"] == 6
            assert meta["has_more"] is expect_more
            assert len(rows) == 2
            seen.extend(row["id"] for row in rows)
        assert len(set(seen)) == 6
        assert seen == [row["id"] for row in all_rows]

    def test_out_of_range_windows_and_unknown_filter_values_are_shape_violations(self, api):
        """PRD 2.11 rank 5: "Request shape — every required field present, every enum value
        inside its declared set ... and on list endpoints `limit` between 1 and 100 inclusive
        with `offset` at least 0 → `ERR_INVALID_REQUEST` (400). Applies to every endpoint."

        Design: Corner/endpoints/corner_endpoints_filtered_list_combines_filters_conjunctively_and_paginates
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.booking_env(api)
        product_id = env["product"]["id"]

        for params in (
            {"product_id": product_id, "limit": 0},
            {"product_id": product_id, "limit": 101},
            {"product_id": product_id, "offset": -1},
            {"product_id": product_id, "order_state": "PENDING"},
        ):
            validate_error(
                api.list_test_orders(params, headers=COORDINATOR_HEADERS),
                ApiErrorId.INVALID_REQUEST.value,
                400,
            )

        for params in (
            {"product_id": product_id, "limit": 1},
            {"product_id": product_id, "limit": 100},
            {"product_id": product_id, "offset": 0},
        ):
            validate_paginated(api.list_test_orders(params, headers=COORDINATOR_HEADERS))

    def test_the_retest_flag_filter_separates_the_retest_round_from_its_origin(self, api):
        """PRD 3.6: "Orders may be listed filtered by `product_id`, `sampling_plan_id`,
        `laboratory_id`, `rule_id`, `order_state` and `is_retest`."

        Design: Corner/endpoints/corner_endpoints_filtered_list_combines_filters_conjunctively_and_paginates
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.retest_case_env(api)
        product_id = env["product"]["id"]
        retest_order_id = env["retest_order_ids"][0]

        retests, retest_meta = validate_paginated(
            api.list_test_orders(
                {"product_id": product_id, "is_retest": "true"}, headers=COORDINATOR_HEADERS
            )
        )
        assert retest_meta["total_count"] == 1
        assert [row["id"] for row in retests] == [retest_order_id]
        assert retests[0]["is_retest"] is True

        originals, original_meta = validate_paginated(
            api.list_test_orders(
                {"product_id": product_id, "is_retest": "false"}, headers=COORDINATOR_HEADERS
            )
        )
        assert original_meta["total_count"] >= 1
        assert retest_order_id not in {row["id"] for row in originals}
        assert all(row["is_retest"] is False for row in originals)


def _ids(rows):
    return {row["id"] for row in rows}


class TestCrossReferenceLinks:
    """Every child collection is reachable from its parent and stops at that parent."""

    def test_the_five_product_scoped_child_lists_never_leak_a_sibling_product(self, api):
        """PRD 3.3: "Parts may be listed filtered by `product_id`, `supplier_id` and
        `reliance_status`." PRD 3.7: "Certificates may be listed filtered by `product_id`,
        `supersedes_certificate_id`, `issuance_status` and `accompaniment_status`."

        Design: Corner/endpoints/corner_endpoints_cross_reference_links_resolve_every_child_collection
        """
        fx.set_clock(api, STARTUP_CLOCK)
        first = fx.distributed_env(api, batch_specs=[{}, {}])
        second = fx.distributed_env(api)

        for env, other in ((first, second), (second, first)):
            product_id = env["product"]["id"]
            parts, _ = validate_paginated(
                api.list_component_parts({"product_id": product_id}, headers=OFFICER_HEADERS)
            )
            assert _ids(parts) == _ids(env["parts"])
            assert _ids(parts).isdisjoint(_ids(other["parts"]))

            plans, _ = validate_paginated(
                api.list_sampling_plans({"product_id": product_id}, headers=OFFICER_HEADERS)
            )
            assert _ids(plans) == {env["plan"]["id"]}

            orders, _ = validate_paginated(
                api.list_test_orders({"product_id": product_id}, headers=OFFICER_HEADERS)
            )
            assert _ids(orders) == _ids(env["orders"])
            assert all(row["product_id"] == product_id for row in orders)

            certificates, _ = validate_paginated(
                api.list_certificates({"product_id": product_id}, headers=OFFICER_HEADERS)
            )
            assert _ids(certificates) == {env["certificate"]["id"]}
            assert certificates[0]["supersedes_certificate_id"] is None

            batches, batch_meta = validate_paginated(
                api.list_production_batches({"product_id": product_id}, headers=MANAGER_HEADERS)
            )
            assert _ids(batches) == _ids(env["batches"])
            assert batch_meta["total_count"] == len(env["batches"])
            assert _ids(batches).isdisjoint(_ids(other["batches"]))

    def test_non_product_parents_resolve_their_own_children_and_stop_there(self, api):
        """PRD 3.8: "Batches may be listed filtered by `product_id`, `certificate_id` and
        `distribution_state`." PRD 3.2: "Scopes may be listed filtered by `laboratory_id`,
        `rule_id` and `accreditation_state`."

        Design: Corner/endpoints/corner_endpoints_cross_reference_links_resolve_every_child_collection
        """
        fx.set_clock(api, STARTUP_CLOCK)
        first = fx.distributed_env(api, batch_specs=[{}, {}])
        second = fx.distributed_env(api)

        batches, meta = validate_paginated(
            api.list_production_batches(
                {"certificate_id": first["certificate"]["id"]}, headers=MANAGER_HEADERS
            )
        )
        assert _ids(batches) == _ids(first["batches"])
        assert meta["total_count"] == 2

        foreign_batches, foreign_meta = validate_paginated(
            api.list_production_batches(
                {
                    "product_id": second["product"]["id"],
                    "certificate_id": first["certificate"]["id"],
                },
                headers=MANAGER_HEADERS,
            )
        )
        assert foreign_batches == []
        assert foreign_meta["total_count"] == 0

        scopes, scope_meta = validate_paginated(
            api.list_accreditations(
                {"laboratory_id": first["laboratory"]["id"]}, headers=COORDINATOR_HEADERS
            )
        )
        assert _ids(scopes) == _ids(first["accreditations"])
        assert all(
            row["laboratory_id"] == first["laboratory"]["id"] for row in scopes
        )
        assert scope_meta["total_count"] == len(first["accreditations"])

        part = first["parts"][0]
        certificate = fx.submit_part_certificate(
            api,
            part["id"],
            first["supplier"]["id"],
            first["laboratory"]["id"],
            first["rules"][0]["id"],
        )
        part_certificates, _ = validate_paginated(
            api.list_part_certificates(
                {"component_part_id": part["id"]}, headers=OFFICER_HEADERS
            )
        )
        assert _ids(part_certificates) == {certificate["id"]}
        other_part_certificates, other_meta = validate_paginated(
            api.list_part_certificates(
                {"component_part_id": second["parts"][0]["id"]}, headers=OFFICER_HEADERS
            )
        )
        assert other_part_certificates == []
        assert other_meta["total_count"] == 0

    def test_the_case_link_and_the_append_only_event_log_resolve_from_their_parents(self, api):
        """PRD 3.9: "Cases may be listed filtered by `product_id`, `triggering_test_order_id`,
        `failed_rule_id`, `active_retest_order_id` and `case_state`." PRD 3.10: "The list may
        be filtered by `product_id`, `component_part_id`, `subject_type`, `change_kind` and
        `triggers_resample`."

        Design: Corner/endpoints/corner_endpoints_cross_reference_links_resolve_every_child_collection
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.failed_case_env(api)
        product_id = env["product"]["id"]
        failing_order = env["failing_order"]

        cases, case_meta = validate_paginated(
            api.list_cases(
                {"triggering_test_order_id": failing_order["id"]}, headers=OFFICER_HEADERS
            )
        )
        assert _ids(cases) == {env["case"]["id"]}
        assert case_meta["total_count"] == 1
        assert cases[0]["product_id"] == product_id
        assert cases[0]["failed_rule_id"] == failing_order["rule_id"]

        no_cases, no_case_meta = validate_paginated(
            api.list_cases(
                {"triggering_test_order_id": env["orders"][0]["id"]}, headers=OFFICER_HEADERS
            )
        )
        assert no_cases == []
        assert no_case_meta["total_count"] == 0

        part = env["parts"][0]
        event = fx.record_material_change(
            api, product_id, subject_type="COMPONENT_PART", component_part_id=part["id"]
        )
        product_event = fx.record_material_change(api, product_id)

        part_events, part_event_meta = validate_paginated(
            api.list_material_changes(
                {"component_part_id": part["id"]}, headers=ADMIN_HEADERS
            )
        )
        assert _ids(part_events) == {event["id"]}
        assert part_event_meta["total_count"] == 1
        assert "created_at" in part_events[0]
        assert "version" not in part_events[0]
        assert "updated_at" not in part_events[0]

        product_events, _ = validate_paginated(
            api.list_material_changes({"product_id": product_id}, headers=ADMIN_HEADERS)
        )
        assert _ids(product_events) == {event["id"], product_event["id"]}


class TestClockEndpoint:
    """The clock setter reports the new instant, stamps later writes, and mutates nothing."""

    def test_the_startup_instant_stamps_rows_created_while_it_stands(self, api):
        """PRD 2.4: "At startup the logical clock reads exactly `2026-08-01T00:00:00Z`; until
        an administrator moves it, that is the instant every rule sees."

        Design: Corner/endpoints/corner_endpoints_clock_endpoint_default_and_stamping
        """
        set_response = api.set_clock(STARTUP_CLOCK, headers=ADMIN_HEADERS)
        body = validate_success(set_response, 200)
        assert set_response.status_code == 200
        assert body["current_utc"] == STARTUP_CLOCK

        env = fx.scoped_product_env(api, product={"projected_annual_units": 6000})
        assert env["product"]["created_at"].startswith("2026-08-01T00:00:00")
        plan = fx.create_plan(api, env["product"]["id"])
        activated = fx.activate_plan(api, plan["id"])
        assert activated["activated_at"] == STARTUP_CLOCK
        assert activated["last_verified_at"] == STARTUP_CLOCK
        assert activated["periodic_due_at"] == "2027-08-01T00:00:00Z"

    def test_moving_the_clock_mutates_no_row_but_stamps_every_later_write(self, api):
        """PRD 2.4: "Moving the clock mutates no entity row — state machines observe the new
        instant only when a subsequent request arrives and re-evaluates its own preconditions
        against it."

        Design: Corner/endpoints/corner_endpoints_clock_endpoint_default_and_stamping
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.scoped_product_env(api, product={"projected_annual_units": 6000})
        plan = fx.create_plan(api, env["product"]["id"])
        before_product = fx.get_product(api, env["product"]["id"])

        later = "2026-09-15T08:30:00Z"
        moved = validate_success(api.set_clock(later, headers=ADMIN_HEADERS), 200)
        assert moved["current_utc"] == later

        after_product = fx.get_product(api, env["product"]["id"])
        assert after_product == before_product
        untouched_plan = fx.get_plan(api, plan["id"])
        assert untouched_plan["version"] == plan["version"] == 1
        assert untouched_plan["activated_at"] is None
        assert untouched_plan["updated_at"] == plan["updated_at"]

        activated = fx.activate_plan(api, plan["id"])
        assert activated["activated_at"] == later
        assert activated["last_verified_at"] == later
        assert activated["periodic_due_at"] == "2027-09-15T08:30:00Z"
        fx.set_clock(api, STARTUP_CLOCK)

    def test_only_the_administrator_may_move_the_clock_and_the_instant_must_parse(self, api):
        """PRD 2.4: "A `ComplianceAdministrator` may advance or rewind the clock to any
        supplied instant by submitting a `to_iso8601` value; the response reports the new
        setting as `current_utc`."

        Design: Corner/endpoints/corner_endpoints_clock_endpoint_default_and_stamping
        """
        fx.set_clock(api, STARTUP_CLOCK)
        for headers in (COORDINATOR_HEADERS, OFFICER_HEADERS, MANAGER_HEADERS):
            validate_error(
                api.set_clock("2026-10-01T00:00:00Z", headers=headers),
                ApiErrorId.ROLE_NOT_PERMITTED.value,
                403,
            )
        for payload in ({}, {"to_iso8601": "not-a-timestamp"}, {"to_iso8601": None}):
            validate_error(
                api.set_clock_raw(payload, headers=ADMIN_HEADERS),
                ApiErrorId.INVALID_REQUEST.value,
                400,
            )
        assert validate_success(api.set_clock(STARTUP_CLOCK, headers=ADMIN_HEADERS), 200)[
            "current_utc"
        ] == STARTUP_CLOCK


class TestConditionalReleaseAction:
    """Batch release converges four independent guards, each with its own refusal."""

    def _four_batches(self, api):
        return fx.distributed_env(
            api,
            batch_specs=[{}, {"label_on_packaging": False}, {}, {}],
            release=False,
        )

    def test_a_batch_that_satisfies_every_guard_releases_and_moves_its_units(self, api):
        """PRD 3.8: "On success the batch moves `HELD → RELEASED`, `released_at` is stamped
        with the logical clock, and the batch's `quantity` moves from the product's
        `units_held` to its `units_released`; both the batch's and the product's `version`
        increment by 1."

        Design: Corner/endpoints/corner_endpoints_conditional_action_release_requires_four_independent_preconditions
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = self._four_batches(api)
        product_before = fx.get_product(api, env["product"]["id"])
        assert product_before["compliance_posture"] == "CLEARED"
        assert product_before["units_held"] == 400
        assert product_before["units_released"] == 0
        batch = env["batches"][0]
        assert batch["distribution_state"] == "HELD"
        assert batch["tracking_label_compliant"] is True

        released = validate_success(api.release_batch(batch["id"], headers=MANAGER_HEADERS), 200)
        assert released["distribution_state"] == "RELEASED"
        assert released["released_at"] == STARTUP_CLOCK
        assert released["version"] == batch["version"] + 1

        product_after = fx.get_product(api, env["product"]["id"])
        assert product_after["units_held"] == 300
        assert product_after["units_released"] == 100
        assert product_after["version"] == product_before["version"] + 1

    def test_the_batch_state_guard_refuses_a_second_release(self, api):
        """PRD 2.11 rank 13: "Production batch state — `HELD` for release, `RELEASED` for
        rescinding a release ... → `ERR_BATCH_STATE_INVALID` (409)."

        Design: Corner/endpoints/corner_endpoints_conditional_action_release_requires_four_independent_preconditions
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = self._four_batches(api)
        batch = env["batches"][0]
        released = validate_success(api.release_batch(batch["id"], headers=MANAGER_HEADERS), 200)

        validate_error(
            api.release_batch(batch["id"], headers=MANAGER_HEADERS),
            ApiErrorId.BATCH_STATE_INVALID.value,
            409,
        )
        assert fx.get_batch(api, batch["id"])["version"] == released["version"]

    def test_the_label_guard_refuses_a_partially_labelled_batch(self, api):
        """PRD 3.8: "`tracking_label_compliant` is true, or the release is refused with
        `ERR_TRACKING_LABEL_NONCOMPLIANT`."

        Design: Corner/endpoints/corner_endpoints_conditional_action_release_requires_four_independent_preconditions
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = self._four_batches(api)
        unlabelled = env["batches"][1]
        assert unlabelled["label_on_packaging"] is False
        assert unlabelled["tracking_label_compliant"] is False
        assert fx.get_product(api, env["product"]["id"])["compliance_posture"] == "CLEARED"

        validate_error(
            api.release_batch(unlabelled["id"], headers=MANAGER_HEADERS),
            ApiErrorId.TRACKING_LABEL_NONCOMPLIANT.value,
            422,
        )
        still_held = fx.get_batch(api, unlabelled["id"])
        assert still_held["distribution_state"] == "HELD"
        assert still_held["version"] == unlabelled["version"]

        repaired = validate_success(
            api.update_tracking_label(
                unlabelled["id"], factories.tracking_label_payload(), headers=MANAGER_HEADERS
            ),
            200,
        )
        assert repaired["tracking_label_compliant"] is True
        assert (
            validate_success(api.release_batch(unlabelled["id"], headers=MANAGER_HEADERS), 200)[
                "distribution_state"
            ]
            == "RELEASED"
        )

    def test_the_posture_guard_refuses_while_a_material_change_stands_unresolved(self, api):
        """PRD 3.8: "and the owning product's `compliance_posture` is `CLEARED`, or the
        release is refused with `ERR_PRODUCT_POSTURE_NOT_CLEARED`."

        Design: Corner/endpoints/corner_endpoints_conditional_action_release_requires_four_independent_preconditions
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = self._four_batches(api)
        batch = env["batches"][2]

        fx.record_material_change(api, env["product"]["id"])
        assert fx.get_product(api, env["product"]["id"])["compliance_posture"] == "RESTRICTED"
        assert fx.get_plan(api, env["plan"]["id"])["plan_state"] == "RESAMPLE_DUE"

        validate_error(
            api.release_batch(batch["id"], headers=MANAGER_HEADERS),
            ApiErrorId.PRODUCT_POSTURE_NOT_CLEARED.value,
            422,
        )
        assert fx.get_batch(api, batch["id"])["distribution_state"] == "HELD"

        fx.run_order_to_pass(
            api,
            env["product"]["id"],
            env["plan"]["id"],
            env["laboratory"]["id"],
            env["rules"][0]["id"],
        )
        assert fx.get_plan(api, env["plan"]["id"])["plan_state"] == "ACTIVE"
        assert fx.get_product(api, env["product"]["id"])["compliance_posture"] == "CLEARED"
        assert (
            validate_success(api.release_batch(batch["id"], headers=MANAGER_HEADERS), 200)[
                "distribution_state"
            ]
            == "RELEASED"
        )

    def test_the_certificate_axis_guard_refuses_once_accompaniment_is_recalled(self, api):
        """PRD 3.8: "the referenced certificate's `issuance_status` is `ISSUED` **and** its
        `accompaniment_status` is `FURNISHED`, both axes satisfied simultaneously, or the
        release is refused with `ERR_CERTIFICATE_STATE_INVALID`."

        Design: Corner/endpoints/corner_endpoints_conditional_action_release_requires_four_independent_preconditions
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = self._four_batches(api)
        batch = env["batches"][3]

        recalled = fx.recall_accompaniment(api, env["certificate"]["id"])
        assert recalled["accompaniment_status"] == "RECALLED_FROM_SHIPMENTS"
        assert recalled["issuance_status"] == "ISSUED"

        validate_error(
            api.release_batch(batch["id"], headers=MANAGER_HEADERS),
            ApiErrorId.CERTIFICATE_STATE_INVALID.value,
            409,
        )
        untouched = fx.get_batch(api, batch["id"])
        assert untouched["distribution_state"] == "HELD"
        assert untouched["released_at"] is None
        assert untouched["version"] == batch["version"]


class TestEntityBackedIdentityWrites:
    """The two entity-backed roles never send their own id in a body; the header carries it."""

    def test_a_part_certificate_takes_its_supplier_from_the_owning_part(self, api):
        """PRD 3.4: "On acceptance the system copies the part's `supplier_id` onto the
        certificate, sets `reliance_state` to `SUBMITTED`, leaves `reliance_documentation_ref`
        and `reliance_recorded_by_user_id` null, and increments the supplier's
        `certificates_issued_count` by 1."

        Design: Corner/endpoints/corner_endpoints_entity_backed_write_endpoints_derive_the_actor_from_identity
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.scoped_product_env(api)
        part = env["parts"][0]
        supplier = env["supplier"]
        before = fx.get_supplier(api, supplier["id"])

        payload = factories.part_certificate_payload(
            env["laboratory"]["id"], env["rules"][0]["id"]
        )
        assert "supplier_id" not in payload
        certificate = validate_success(
            api.submit_part_certificate(
                part["id"], payload, headers=make_supplier_user_headers(supplier["id"])
            ),
            201,
        )
        assert certificate["supplier_id"] == supplier["id"]
        assert certificate["component_part_id"] == part["id"]
        assert certificate["reliance_state"] == "SUBMITTED"
        assert certificate["reliance_documentation_ref"] is None
        assert certificate["reliance_recorded_by_user_id"] is None

        after = fx.get_supplier(api, supplier["id"])
        assert after["certificates_issued_count"] == before["certificates_issued_count"] + 1

    def test_a_supplier_identity_that_does_not_own_the_part_is_refused(self, api):
        """PRD 2.11 rank 4: "Supplier part ownership — when the caller is a `SupplierUser`,
        `X-User-ID` equals the `supplier_id` of the component part named in the path →
        `ERR_SUPPLIER_NOT_PART_OWNER` (403). Applies to submitting a component part
        certificate."

        Design: Corner/endpoints/corner_endpoints_entity_backed_write_endpoints_derive_the_actor_from_identity
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.scoped_product_env(api)
        part = env["parts"][0]
        outsider = fx.create_supplier(api)

        validate_error(
            api.submit_part_certificate(
                part["id"],
                factories.part_certificate_payload(
                    env["laboratory"]["id"], env["rules"][0]["id"]
                ),
                headers=make_supplier_user_headers(outsider["id"]),
            ),
            ApiErrorId.SUPPLIER_NOT_PART_OWNER.value,
            403,
        )
        rows, meta = validate_paginated(
            api.list_part_certificates(
                {"component_part_id": part["id"]}, headers=OFFICER_HEADERS
            )
        )
        assert rows == []
        assert meta["total_count"] == 0

    def test_a_report_is_stamped_with_the_reporting_laboratory_identity_and_the_clock(self, api):
        """PRD 3.6: "The laboratory submits a single `measured_value` — one representative
        measurement per order, with no aggregation across samples — and the system stores it
        together with `reported_at` from the logical clock and `reported_by_user_id` from the
        acting `X-User-ID`."

        Design: Corner/endpoints/corner_endpoints_entity_backed_write_endpoints_derive_the_actor_from_identity
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.booking_env(api)
        laboratory_id = env["laboratory"]["id"]
        order = fx.book_order(
            api,
            env["product"]["id"],
            env["plan"]["id"],
            laboratory_id,
            env["rules"][0]["id"],
        )
        assert order["reported_by_user_id"] is None
        assert order["reported_at"] is None
        assert order["ordered_by_user_id"] is not None

        lab_headers = make_laboratory_user_headers(laboratory_id)
        fx.start_order(api, order["id"], laboratory_id)
        reported = validate_success(
            api.report_result(order["id"], {"measured_value": 42}, headers=lab_headers), 200
        )
        assert reported["measured_value"] == 42
        assert reported["result"] == "PASS"
        assert reported["order_state"] == "REPORTED_PASS"
        assert reported["reported_by_user_id"] == laboratory_id
        assert reported["reported_at"] == STARTUP_CLOCK

    def test_a_laboratory_identity_that_does_not_hold_the_order_is_refused(self, api):
        """PRD 2.11 rank 3: "Laboratory assignment ownership — when the caller is a
        `LaboratoryUser`, `X-User-ID` equals the `laboratory_id` of the test order named in the
        path → `ERR_LAB_NOT_ASSIGNED` (403). Applies to taking an order into testing and to
        filing its report."

        Design: Corner/endpoints/corner_endpoints_entity_backed_write_endpoints_derive_the_actor_from_identity
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
        outsider = _extra_lab(api, [env["rules"][0]["id"]])
        outsider_headers = make_laboratory_user_headers(outsider["id"])

        validate_error(
            api.start_testing(order["id"], headers=outsider_headers),
            ApiErrorId.LAB_NOT_ASSIGNED.value,
            403,
        )
        fx.start_order(api, order["id"], env["laboratory"]["id"])
        validate_error(
            api.report_result(order["id"], {"measured_value": 42}, headers=outsider_headers),
            ApiErrorId.LAB_NOT_ASSIGNED.value,
            403,
        )
        still_in_testing = fx.get_order(api, order["id"])
        assert still_in_testing["order_state"] == "IN_TESTING"
        assert still_in_testing["reported_by_user_id"] is None


class TestReadsAndRefusalsLeaveNoTrace:
    """Reads never mutate, and a refused write is indistinguishable from no request at all."""

    def test_repeated_reads_across_a_clock_move_return_the_same_rows(self, api):
        """PRD 2.8: "The on-demand compliance summary read for a product recomputes both unit
        ledgers and reports whether they balance, alongside the freshly derived rule set and
        score. It is a pure read: it mutates no row and bumps no `version`."

        Design: Corner/endpoints/corner_endpoints_reads_never_mutate_and_refused_writes_leave_no_trace
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.distributed_env(
            api, batch_specs=[{"label_on_packaging": False}], release=False
        )
        product_id = env["product"]["id"]
        batch_id = env["batches"][0]["id"]
        certificate_id = env["certificate"]["id"]

        first = {
            "product": fx.get_product(api, product_id),
            "certificate": fx.get_certificate(api, certificate_id),
            "batch": fx.get_batch(api, batch_id),
            "plan": fx.get_plan(api, env["plan"]["id"]),
            "summary": fx.get_summary(api, product_id),
        }
        for _ in range(2):
            again = {
                "product": fx.get_product(api, product_id),
                "certificate": fx.get_certificate(api, certificate_id),
                "batch": fx.get_batch(api, batch_id),
                "plan": fx.get_plan(api, env["plan"]["id"]),
                "summary": fx.get_summary(api, product_id),
            }
            assert again == first

        fx.set_clock(api, "2026-08-05T00:00:00Z")
        after_move = {
            "product": fx.get_product(api, product_id),
            "certificate": fx.get_certificate(api, certificate_id),
            "batch": fx.get_batch(api, batch_id),
            "plan": fx.get_plan(api, env["plan"]["id"]),
            "summary": fx.get_summary(api, product_id),
        }
        for key, row in first.items():
            assert after_move[key] == row
        fx.set_clock(api, STARTUP_CLOCK)

    def test_three_refused_releases_leave_the_batch_and_the_ledger_untouched(self, api):
        """PRD 3.8: "`tracking_label_compliant` is true, or the release is refused with
        `ERR_TRACKING_LABEL_NONCOMPLIANT` ... On success the batch moves `HELD → RELEASED`,
        `released_at` is stamped with the logical clock, and the batch's `quantity` moves from
        the product's `units_held` to its `units_released`" — the movement is on the success
        branch only, so a refused release moves nothing.

        Design: Corner/endpoints/corner_endpoints_reads_never_mutate_and_refused_writes_leave_no_trace
        """
        fx.set_clock(api, STARTUP_CLOCK)
        env = fx.distributed_env(
            api, batch_specs=[{"label_on_packaging": False}], release=False
        )
        product_id = env["product"]["id"]
        batch_before = fx.get_batch(api, env["batches"][0]["id"])
        product_before = fx.get_product(api, product_id)
        summary_before = fx.get_summary(api, product_id)

        for _ in range(3):
            validate_error(
                api.release_batch(batch_before["id"], headers=MANAGER_HEADERS),
                ApiErrorId.TRACKING_LABEL_NONCOMPLIANT.value,
                422,
            )

        batch_after = fx.get_batch(api, batch_before["id"])
        assert batch_after == batch_before
        assert batch_after["distribution_state"] == "HELD"
        assert batch_after["released_at"] is None
        assert batch_after["release_rescind_count"] == 0
        assert fx.get_product(api, product_id) == product_before
        assert fx.get_summary(api, product_id) == summary_before
        assert summary_before["units_held"] == 100
        assert summary_before["units_released"] == 0
        assert summary_before["ledger_balanced"] is True
