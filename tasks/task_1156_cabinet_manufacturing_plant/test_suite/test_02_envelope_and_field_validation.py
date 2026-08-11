"""Response envelope shape and field-level validation rules (PRD §2.2, §2.7)."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_assembly_line_payload,
    create_box_line_payload,
    create_dealer_payload,
    create_finish_spec_payload,
    create_sub_lot_payload,
    get_success_data,
    make_dealer_headers,
    validate_error,
    validate_success,
)

PLANNER = TEST_USERS["production_planner_headers"]


class TestResponseEnvelope:
    def test_response_envelope_shape_for_success_and_error(self, api, plant_admin_headers):
        """PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."

        Design: Corner/endpoints/response_envelope_shape_for_success_and_error
        """
        created = api.create_door_style(
            {"style_code": "DS-E", "name": "Env", "construction": "SLAB", "base_list_price_cents": 1000},
            plant_admin_headers,
        )
        data = validate_success(created, 201)
        body = created.json()
        assert isinstance(body["meta"]["api_request_id"], str) and body["meta"]["api_request_id"]
        assert isinstance(body["meta"]["api_request_timestamp"], str)
        assert body["response_type"] == "object"
        assert data["style_code"] == "DS-E"

        missing = api.get_order("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", plant_admin_headers)
        err = validate_error(missing, ApiErrorId.ERR_ORDER_NOT_FOUND)
        err_body = missing.json()
        assert err_body["response_type"] == "error"
        assert err["error_id"] == "ERR_ORDER_NOT_FOUND"
        assert isinstance(err["message"], str) and err["message"].strip()


class TestFieldLevelValidation:
    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "If either header is missing, or if `X-User-Role` does not name
        one of the declared roles below, the request is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400) before any other
        processing."

        Design: Corner/validations/missing_auth_headers_rejected
        """
        resp = api.list_dealers({})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_invalid_enum_value_rejected(self, api, plant_admin_headers):
        """PRD §2.7: "Field-level sanity, always evaluated last: required fields
        present (`ERR_VALIDATION`), enum values within their declared sets
        (`ERR_INVALID_ENUM`), quantities within their positive or non-negative
        ranges (`ERR_INVALID_QUANTITY`), time windows well formed
        (`ERR_INVALID_TIME_WINDOW`), and unique codes free of collision
        (`ERR_DUPLICATE_CODE`)."

        Design: Corner/validations/invalid_enum_value_rejected
        """
        resp = api.create_dealer(
            {"name": "Bad", "dealer_code": "BAD", "price_level": "L9", "credit_limit_cents": 1000},
            plant_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_ENUM)

    def test_missing_required_field_rejected(self, api, plant_admin_headers):
        """PRD §2.7: "Field-level sanity, always evaluated last: required fields
        present (`ERR_VALIDATION`), enum values within their declared sets
        (`ERR_INVALID_ENUM`), quantities within their positive or non-negative
        ranges (`ERR_INVALID_QUANTITY`), time windows well formed
        (`ERR_INVALID_TIME_WINDOW`), and unique codes free of collision
        (`ERR_DUPLICATE_CODE`)."

        Design: Corner/validations/missing_required_field_rejected
        """
        resp = api.create_dealer(
            {"name": "NoCredit", "dealer_code": "NC1", "price_level": "L1"},
            plant_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_invalid_qty_zero_rejected(self, api, plant_admin_headers):
        """PRD §3.2: "Each line declares a `line_type` of `BOX` (a cabinet box) or
        `DOOR` (a door line), a `finish_id` referencing the finish specification
        both line types require, whole-inch dimensions `width_in`, `height_in`, and
        `depth_in` (all strictly positive), a strictly positive `qty`, and the
        client-looked-up catalog price `unit_list_price_cents`, which the server
        validates as strictly positive."
        PRD §2.7: "quantities within their positive or non-negative ranges
        (`ERR_INVALID_QUANTITY`)"

        Design: Corner/validations/invalid_qty_zero_rejected
        """
        dealer = get_success_data(api.create_dealer(create_dealer_payload(), plant_admin_headers))
        finish = get_success_data(
            api.create_finish_spec(create_finish_spec_payload(), plant_admin_headers)
        )
        order = get_success_data(api.create_order(make_dealer_headers(dealer["id"])))
        payload = create_box_line_payload(finish["id"], qty=0)
        resp = api.create_order_line(order["id"], payload, make_dealer_headers(dealer["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_QUANTITY)

    def test_invalid_time_window_end_beyond_day_rejected(self, api, plant_admin_headers):
        """PRD §3.6: "The sub-lot's `end_minute` is `start_minute` plus
        `work_minutes`, and if that computed end falls beyond minute 1440 the
        request is rejected with `ERR_INVALID_TIME_WINDOW`."

        Design: Corner/validations/invalid_time_window_end_beyond_day_rejected
        """
        dealer = get_success_data(api.create_dealer(create_dealer_payload(), plant_admin_headers))
        finish = get_success_data(
            api.create_finish_spec(create_finish_spec_payload(), plant_admin_headers)
        )
        order = get_success_data(api.create_order(make_dealer_headers(dealer["id"])))
        line = get_success_data(
            api.create_order_line(
                order["id"],
                create_box_line_payload(finish["id"], qty=10),
                make_dealer_headers(dealer["id"]),
            )
        )
        get_success_data(api.submit_order(order["id"], make_dealer_headers(dealer["id"])))
        assembly_line = get_success_data(
            api.create_assembly_line(create_assembly_line_payload(line_code="AL-1"), plant_admin_headers)
        )
        # 10 boxes x 30 min + 20 setup = 320 work minutes from 1400 -> end 1720.
        resp = api.create_sub_lot(
            create_sub_lot_payload(line["id"], assembly_line["id"], start_minute=1400, qty=10),
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_TIME_WINDOW)
