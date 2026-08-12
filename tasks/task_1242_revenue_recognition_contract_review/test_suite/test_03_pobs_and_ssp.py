"""Performance obligations and the standalone-selling-price master (PRD §3.3)."""
import pytest

from test_helpers import (
    ApiErrorId, validate_success, validate_error, validate_paginated,
    create_pob_payload, TEST_USERS,
    create_customer, create_contract, create_ssp, add_pob, get_pob,
    assert_pob, assert_ssp_price,
)


def _draft_contract_with_ssp(api, accountant_headers, product="WIDGET", region="US"):
    create_ssp(product, region=region, ssp_cents=100000)
    customer = create_customer()
    contract = create_contract(customer["id"], fixed_consideration_cents=100000)
    return customer, contract


class TestPobConditionalFields:
    def test_straight_line_missing_dates_returns_invalid_request(self, api, accountant_headers):
        """PRD §3.3: "a straight-line obligation requires `service_start_date`
        and `service_end_date`, with the end date after the start date, while an
        input-cost obligation requires `estimated_total_cost_cents` greater than
        zero; missing conditional fields fail request validation with
        `ERR_INVALID_REQUEST`".

        Design: Corner/entities/pob_straight_line_missing_dates_returns_invalid_request
        """
        _, contract = _draft_contract_with_ssp(api, accountant_headers)
        resp = api.create_pob(
            contract["id"],
            create_pob_payload(pob_ref="P1", recognition_pattern="OVER_TIME_STRAIGHT_LINE"),
            accountant_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_straight_line_partial_dates_returns_invalid_request(self, api, accountant_headers):
        """PRD §3.3: "a straight-line obligation requires `service_start_date`
        and `service_end_date`, with the end date after the start date, while an
        input-cost obligation requires `estimated_total_cost_cents` greater than
        zero; missing conditional fields fail request validation with
        `ERR_INVALID_REQUEST`".

        Design: Corner/entities/pob_straight_line_missing_dates_returns_invalid_request
        """
        _, contract = _draft_contract_with_ssp(api, accountant_headers)
        resp = api.create_pob(
            contract["id"],
            create_pob_payload(
                pob_ref="P1", recognition_pattern="OVER_TIME_STRAIGHT_LINE",
                service_start_date="2026-06-01",
            ),
            accountant_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)
        listed = validate_paginated(api.list_pobs(contract["id"], accountant_headers))[0]
        assert listed == [], "no POB may be persisted when validation fails"


class TestPobEnumValidation:
    def test_invalid_recognition_pattern_returns_invalid_request(self, api, accountant_headers):
        """PRD §3.3: "a `recognition_pattern` of `POINT_IN_TIME`,
        `OVER_TIME_INPUT_COST`, or `OVER_TIME_STRAIGHT_LINE`".
        PRD §2.8: "enum fields must hold declared members; failures of this kind
        return `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/pob_invalid_enum_pattern_returns_invalid_request
        """
        _, contract = _draft_contract_with_ssp(api, accountant_headers)
        resp = api.create_pob(
            contract["id"],
            create_pob_payload(pob_ref="P1", recognition_pattern="SOME_TIME"),
            accountant_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_each_declared_pattern_accepted(self, api, accountant_headers):
        """PRD §3.3: "a `recognition_pattern` of `POINT_IN_TIME`,
        `OVER_TIME_INPUT_COST`, or `OVER_TIME_STRAIGHT_LINE`."

        Design: Corner/entities/pob_invalid_enum_pattern_returns_invalid_request
        """
        _, contract = _draft_contract_with_ssp(api, accountant_headers)
        cases = [
            {"pob_ref": "PA", "recognition_pattern": "POINT_IN_TIME"},
            {"pob_ref": "PB", "recognition_pattern": "OVER_TIME_INPUT_COST",
             "estimated_total_cost_cents": 40000},
            {"pob_ref": "PC", "recognition_pattern": "OVER_TIME_STRAIGHT_LINE",
             "service_start_date": "2026-06-01", "service_end_date": "2026-07-01"},
        ]
        for payload in cases:
            resp = api.create_pob(contract["id"], create_pob_payload(**payload), accountant_headers)
            pob = validate_success(resp, 201)
            assert pob["recognition_pattern"] == payload["recognition_pattern"]


class TestSspPinning:
    def test_ssp_pinned_from_covering_window(self, api, accountant_headers):
        """PRD §3.3: "At the moment an obligation is created, the server
        resolves its `ssp_cents` from the `ACTIVE` price record whose closed
        window covers the obligation's `product_code` and `region` at the
        contract's `signed_date`, and pins that price onto the obligation".

        Design: Corner/entities/pob_ssp_pinned_from_covering_window
        """
        create_ssp("GADGET", region="EU", ssp_cents=42000)
        customer = create_customer(legal_name="Pin Co", external_ref="PIN-1")
        contract = create_contract(customer["id"], contract_ref="C-PIN", fixed_consideration_cents=90000)
        pob = add_pob(contract["id"], pob_ref="P1", product_code="GADGET", region="EU")
        assert pob["ssp_cents"] == 42000

    def test_new_pob_initial_state(self, api, accountant_headers):
        """PRD §3.3: "A new obligation starts `PENDING` with
        `allocated_amount_cents`, `recognized_revenue_cents`,
        `costs_incurred_to_date_cents`, and `progress_pct` all zero and
        `satisfied_at` null".

        Design: Corner/entities/pob_ssp_pinned_from_covering_window
        """
        create_ssp("GADGET", region="EU", ssp_cents=42000)
        customer = create_customer()
        contract = create_contract(customer["id"], fixed_consideration_cents=90000)
        pob = add_pob(contract["id"], pob_ref="P1", product_code="GADGET", region="EU")
        assert_pob(pob)
        assert pob["status"] == "PENDING"
        assert pob["allocated_amount_cents"] == 0
        assert pob["recognized_revenue_cents"] == 0
        assert pob["costs_incurred_to_date_cents"] == 0
        assert pob["progress_pct"] == 0
        assert pob["satisfied_at"] is None
        assert pob["contract_id"] == contract["id"]

    def test_ssp_master_change_after_approval_keeps_pinned_allocation(self, api, manager_headers, accountant_headers):
        """PRD §3.3: "pins that price onto the obligation — later price-book
        changes never move an existing obligation."
        PRD §3.4: "After the residual lands, the allocated lines sum exactly to
        the transaction price, and the contract's `allocated_total_cents` is set
        to `transaction_price_cents`."

        Design: Corner/cross_cutting_layers/ssp_master_change_after_approval_keeps_pinned_allocation
        """
        ssp = create_ssp("GADGET", region="EU", ssp_cents=42000)
        customer = create_customer(legal_name="PinV Co", external_ref="PINV-1")
        contract = create_contract(customer["id"], contract_ref="C-PINV", fixed_consideration_cents=90000)
        pob = add_pob(contract["id"], pob_ref="P1", product_code="GADGET", region="EU")
        from test_helpers.fixtures import submit_contract, approve_contract
        submit_contract(contract["id"])
        approve_contract(contract["id"])

        retire = api.retire_ssp_price(ssp["id"], manager_headers)
        assert validate_success(retire)["status"] == "RETIRED"
        # A later, different price for the same lane must not move the pin.
        validate_success(api.create_ssp_price(
            {"product_code": "GADGET", "region": "EU", "ssp_cents": 99000,
             "effective_from": "2027-01-01", "effective_to": "2027-12-31"},
            manager_headers,
        ), 201)
        after = get_pob(pob["id"])
        assert after["ssp_cents"] == 42000
        assert after["allocated_amount_cents"] == 90000

    def test_retired_ssp_no_longer_resolves_prices(self, api, manager_headers):
        """PRD §3.3: "Records are created `ACTIVE`; retirement moves a record
        `ACTIVE → RETIRED`, after which it no longer resolves prices."
        PRD §3.3: "When no active window covers the triple, creation is rejected
        with `ERR_SSP_NOT_FOUND` (HTTP 422)."

        Design: Corner/cross_cutting_layers/ssp_master_change_after_approval_keeps_pinned_allocation
        """
        ssp = create_ssp("GADGET", region="EU", ssp_cents=42000)
        retired = validate_success(api.retire_ssp_price(ssp["id"], manager_headers))
        assert_ssp_price(retired)
        assert retired["status"] == "RETIRED"
        customer = create_customer()
        contract = create_contract(customer["id"], fixed_consideration_cents=90000)
        resp = api.create_pob(
            contract["id"],
            create_pob_payload(pob_ref="P1", product_code="GADGET", region="EU"),
            TEST_USERS["accountant_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_SSP_NOT_FOUND, 422)


class TestSspCoverage:
    def test_pob_without_covering_ssp_returns_ssp_not_found(self, api, accountant_headers):
        """PRD §3.3: "When no active window covers the triple, creation is
        rejected with `ERR_SSP_NOT_FOUND` (HTTP 422)."

        Design: Corner/entities/pob_without_covering_ssp_returns_ssp_not_found
        """
        # Window starts after the contract's signed_date 2026-05-20.
        create_ssp("WIDGET", region="US", ssp_cents=100000,
                   effective_from="2026-06-01", effective_to="2026-12-31")
        customer = create_customer(legal_name="NoSSP Co", external_ref="NOSSP-1")
        contract = create_contract(customer["id"], contract_ref="C-NOSSP")
        resp = api.create_pob(
            contract["id"], create_pob_payload(pob_ref="P1"), accountant_headers
        )
        validate_error(resp, ApiErrorId.ERR_SSP_NOT_FOUND, 422)

    def test_window_boundary_dates_are_covered(self, api, accountant_headers):
        """PRD §3.3: "The window is closed at both ends: `effective_from` is the
        first covered date and `effective_to` the last".

        Design: Corner/entities/pob_without_covering_ssp_returns_ssp_not_found
        """
        create_ssp("WIDGET", region="US", ssp_cents=100000,
                   effective_from="2026-05-20", effective_to="2026-05-20")
        customer = create_customer()
        contract = create_contract(customer["id"], signed_date="2026-05-20")
        pob = add_pob(contract["id"], pob_ref="P1")
        assert pob["ssp_cents"] == 100000
