"""The first four gates of PRD 2.7: authentication, role, scope and existence.

Each test drives a request that is otherwise perfectly formed so that the
answer isolates exactly one gate, and then reads the touched rows back to show
the refusal wrote nothing.
"""

import test_helpers as H
from test_helpers import (
    ASSEMBLY_TECH,
    NON_EXISTENT_UUID,
    PLANT_ENGINEER,
    QUALITY_INSPECTOR,
    SALES_ADMIN,
    WELD_SUPERVISOR,
    build_user_headers,
    make_dealer_headers,
    validate_error,
    validate_paginated,
)


class TestAuthenticationAndRoleGates:
    def test_an_unrecognized_role_string_is_unauthenticated_not_unauthorized(self, api):
        """A role outside the seven answers 401, never the 403 of the role gate.

        PRD 2.1: "If either header is absent, or if `X-User-Role` is not one of
        the seven recognized roles, the request is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/error_unauthenticated_when_the_role_header_names_an_unknown_role
        """
        H.set_clock(api, H.CLOCK_DEFAULT_UTC)
        model = H.create_certified_model(api)
        H.commission_jig(api)
        unit = H.open_unit(api, model["id"])

        response = api.get_unit(unit["id"], headers=build_user_headers("pp-1", "ProductionPlanner"))

        validate_error(response, H.ERR_UNAUTHENTICATED)
        after = H.read_unit(api, unit["id"])
        assert after["build_status"] == H.BuildStatus.PLANNED
        assert after["version"] == unit["version"]

    def test_an_assembly_tech_cannot_book_the_road_test_it_prepared(self, api):
        """Booking is the QualityInspector's exclusive lane, so the role gate fires.

        PRD 2.1: "When the role named in `X-User-Role` does not appear in the
        authorized-role list of the endpoint being called (see §4), the request is
        rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

        Design: Corner/errors/error_assembly_tech_cannot_book_a_road_test_role_not_permitted
        """
        plant = H.setup_plant(api)
        staged = H.unit_at_systems_installed(plant, api)

        response = api.book_road_test(
            staged["unit"]["id"],
            H.road_test_payload(plant["lane"]["id"]),
            headers=ASSEMBLY_TECH,
        )

        validate_error(response, H.ERR_ROLE_NOT_PERMITTED)
        tests, meta = validate_paginated(
            api.list_unit_road_tests(staged["unit"]["id"], headers=QUALITY_INSPECTOR)
        )
        assert tests == []
        assert meta["total_count"] == 0
        assert H.read_unit(api, staged["unit"]["id"])["build_status"] == (
            H.BuildStatus.SYSTEMS_INSTALLED
        )

    def test_a_dealer_cannot_file_a_claim_against_another_dealers_account(self, api):
        """The entity-backed identity does not match the body dealer_id.

        PRD 2.1: "Any of these mismatches is rejected with
        `ERR_DEALER_SCOPE_VIOLATION` (HTTP 403)."

        Design: Corner/errors/error_dealer_cannot_file_a_claim_against_another_dealers_account
        """
        plant = H.setup_plant(api)
        staged = H.unit_shipped(plant, api)
        H.set_clock(api, H.CLOCK_SEP_01)

        response = api.create_claim(
            H.claim_payload(staged["unit"]["id"], plant["dealer"]["id"]),
            headers=make_dealer_headers("dlr-9999"),
        )

        validate_error(response, H.ERR_DEALER_SCOPE_VIOLATION)
        claims, meta = validate_paginated(api.list_claims(headers=SALES_ADMIN))
        assert claims == []
        assert meta["total_count"] == 0
        H.assert_money(H.read_dealer(api, plant["dealer"]["id"])["warranty_receivable_cents"], 0)


class TestPathIdentifierVocabulary:
    def test_an_unknown_model_on_the_submission_path_names_the_model(self, api):
        """The path check answers before the DRAFT-versus-CERTIFIED state check.

        PRD 2.2: "The first identifier that names no existing row terminates the
        request with a 404 carrying the error for that resource type:
        `ERR_MODEL_NOT_FOUND` for a trailer model, `ERR_DEALER_NOT_FOUND` for a
        dealer, `ERR_UNIT_NOT_FOUND` for a trailer unit, `ERR_ORDER_NOT_FOUND` for
        a dealer order, `ERR_CLAIM_NOT_FOUND` for a warranty claim, and
        `ERR_RESOURCE_NOT_FOUND` for a weld jig, a test lane, a road test or an
        option install."

        Design: Corner/errors/error_model_not_found_on_a_certification_submission
        """
        H.set_clock(api, H.CLOCK_DEFAULT_UTC)

        response = api.submit_model(
            NON_EXISTENT_UUID, H.submission_payload(engineering_note="GVWR package"),
            headers=PLANT_ENGINEER,
        )

        validate_error(response, H.ERR_MODEL_NOT_FOUND)
        validate_error(api.get_model(NON_EXISTENT_UUID, headers=PLANT_ENGINEER),
                       H.ERR_MODEL_NOT_FOUND)

    def test_an_unknown_order_on_the_allocation_path_beats_the_concurrency_field(self, api):
        """A 404 wins over the 412 a version-first implementation would return.

        PRD 2.7: "The rule that fires masks every later rule completely, so a
        request that trips step 3 never reveals whether it would also have tripped
        step 20."

        Design: Corner/errors/error_order_not_found_on_allocation
        """
        H.set_clock(api, H.CLOCK_DEFAULT_UTC)
        dealer = H.enroll_dealer(api)

        response = api.allocate_order(
            NON_EXISTENT_UUID, H.allocation_payload(dealer["version"]), headers=SALES_ADMIN
        )

        validate_error(response, H.ERR_ORDER_NOT_FOUND)
        after = H.read_dealer(api, dealer["id"])
        assert after["version"] == dealer["version"]
        H.assert_floor_plan_conserved(after, 0)

    def test_an_unknown_claim_on_the_review_path_names_the_claim(self, api):
        """The decision enum is valid, so the 404 isolates path existence.

        PRD 2.2: "When a path contains an identifier, it is resolved before the
        body is examined, and when more than one identifier appears the resolution
        is strictly left to right."

        Design: Corner/errors/error_claim_not_found_on_review
        """
        H.set_clock(api, H.CLOCK_DEFAULT_UTC)

        response = api.review_claim(
            NON_EXISTENT_UUID,
            H.review_payload(H.ClaimDecision.APPROVE, review_note="looks payable"),
            headers=SALES_ADMIN,
        )

        validate_error(response, H.ERR_CLAIM_NOT_FOUND)
        claims, meta = validate_paginated(api.list_claims(headers=SALES_ADMIN))
        assert claims == []
        assert meta["total_count"] == 0


class TestBodyForeignKeyVocabulary:
    def test_an_unknown_body_dealer_id_names_the_dealer_not_the_model(self, api):
        """The model in the same body resolves, so the answer names the dealer.

        PRD 2.2: "Once the path resolves, every foreign key in the request body is
        resolved next, under the same 404 vocabulary — a body `model_id`,
        `unit_id`, `dealer_id`, `lane_id` or `order_id` that names no row produces
        `ERR_MODEL_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`, `ERR_DEALER_NOT_FOUND`,
        `ERR_ORDER_NOT_FOUND` or `ERR_RESOURCE_NOT_FOUND` respectively."

        Design: Corner/errors/error_dealer_not_found_on_order_placement
        """
        H.set_clock(api, H.CLOCK_DEFAULT_UTC)
        model = H.create_certified_model(api)

        response = api.create_order(
            H.order_payload(NON_EXISTENT_UUID, model["id"]), headers=SALES_ADMIN
        )

        validate_error(response, H.ERR_DEALER_NOT_FOUND)
        orders, meta = validate_paginated(api.list_orders(headers=SALES_ADMIN))
        assert orders == []
        assert meta["total_count"] == 0

    def test_an_unknown_body_unit_id_beats_the_jig_concurrency_and_geometry_checks(self, api):
        """The jig is untouched: no minutes booked and no version increment.

        PRD 2.2: "Body foreign-key resolution applies to unit creation, jig
        reservation, road-test booking, order placement, order allocation, claim
        filing and floor-plan adjustment."

        Design: Corner/errors/error_unit_not_found_on_a_jig_reservation
        """
        H.set_clock(api, H.CLOCK_DEFAULT_UTC)
        jig = H.commission_jig(api)

        response = api.reserve_jig(
            jig["id"],
            H.reservation_payload(NON_EXISTENT_UUID, jig["version"]),
            headers=WELD_SUPERVISOR,
        )

        validate_error(response, H.ERR_UNIT_NOT_FOUND)
        after = H.read_jig(api, jig["id"])
        assert after["reserved_minutes_total"] == 0
        assert after["version"] == jig["version"]

    def test_an_unknown_body_lane_id_falls_to_the_generic_resource_error(self, api):
        """TestLane has no dedicated code, so the booking reports the generic 404.

        PRD 2.2: "The first identifier that names no existing row terminates the
        request with a 404 carrying the error for that resource type:
        `ERR_MODEL_NOT_FOUND` for a trailer model, `ERR_DEALER_NOT_FOUND` for a
        dealer, `ERR_UNIT_NOT_FOUND` for a trailer unit, `ERR_ORDER_NOT_FOUND` for
        a dealer order, `ERR_CLAIM_NOT_FOUND` for a warranty claim, and
        `ERR_RESOURCE_NOT_FOUND` for a weld jig, a test lane, a road test or an
        option install."

        Design: Corner/errors/error_resource_not_found_for_an_unknown_lane_id
        """
        plant = H.setup_plant(api)
        staged = H.unit_at_systems_installed(plant, api)

        response = api.book_road_test(
            staged["unit"]["id"],
            H.road_test_payload(NON_EXISTENT_UUID),
            headers=QUALITY_INSPECTOR,
        )

        validate_error(response, H.ERR_RESOURCE_NOT_FOUND)
        assert H.read_unit(api, staged["unit"]["id"])["build_status"] == (
            H.BuildStatus.SYSTEMS_INSTALLED
        )


class TestSchemaConformance:
    def test_a_zero_length_weld_window_is_a_schema_violation(self, api):
        """A window whose end equals its start never reaches the interval arithmetic.

        PRD 3.2: "The window's end must be strictly later than its start."

        Design: Corner/errors/error_invalid_request_when_the_window_end_is_not_after_the_start
        """
        H.set_clock(api, H.CLOCK_DEFAULT_UTC)
        model = H.create_certified_model(api)
        jig = H.commission_jig(api)
        unit = H.open_unit(api, model["id"])

        response = api.reserve_jig(
            jig["id"],
            H.reservation_payload(
                unit["id"], jig["version"], window=(H.JIG_WINDOW_1[0], H.JIG_WINDOW_1[0])
            ),
            headers=WELD_SUPERVISOR,
        )

        validate_error(response, H.ERR_INVALID_REQUEST)
        reservations, meta = validate_paginated(
            api.list_jig_reservations(jig["id"], headers=WELD_SUPERVISOR)
        )
        assert reservations == []
        assert meta["total_count"] == 0
        assert H.read_jig(api, jig["id"])["reserved_minutes_total"] == 0
        after = H.read_unit(api, unit["id"])
        assert after["build_status"] == H.BuildStatus.PLANNED
        assert after["gvwr_lbs"] is None
