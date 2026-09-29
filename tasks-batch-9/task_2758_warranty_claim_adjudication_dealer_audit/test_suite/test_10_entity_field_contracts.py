"""Field-level contracts of the persisted entities: echoed inputs, declared opening
values, the configuration records that carry no version, the paginated list envelope
and the not-found / body-shape rejections that leave no row behind."""
from datetime import date, timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    analyze_parts_return_payload,
    api_client,
    assert_date_equals,
    create_dealer,
    create_dealer_payload,
    create_goodwill_authorization_payload,
    create_labor_operation_payload,
    create_state_law_profile,
    create_state_law_profile_payload,
    get_claim,
    get_dealer,
    get_parts_return,
    parts_return_for_claim,
    receive_part,
    set_clock,
    setup_claim,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["warranty_admin_headers"]
ADJUDICATOR = TEST_USERS["claim_adjudicator_headers"]

# A syntactically valid identifier that names no record.
UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"

CA_PROFILE = {
    "state_code": "CA",
    "markup_cap_pct": 0.30,
    "labor_rate_method": "RETAIL_SAMPLE",
    "min_sample_repair_orders": 5,
    "max_labor_rate_cents": 19500,
    "deemed_approved_days": 30,
    "appeal_window_days": 30,
}

TX_PROFILE = {
    "state_code": "TX",
    "markup_cap_pct": 0.40,
    "labor_rate_method": "TIME_AND_PRICE",
    "min_sample_repair_orders": 5,
    "max_labor_rate_cents": 20000,
    "deemed_approved_days": 45,
    "appeal_window_days": 20,
}

D1_TERMS = {
    "dealer_code": "D1",
    "name": "Dealer One",
    "vehicles_in_operation": 100,
    "initial_labor_rate_cents": 13750,
    "initial_parts_markup_pct": 0.40,
}

COVERED_VEHICLE = {
    "vin": "VIN00000000000001",
    "model_year": 2024,
    "warranty_start_date": "2024-01-15",
    "in_service_odometer": 0,
    "basic_months": 36,
    "basic_miles": 36000,
    "powertrain_months": 60,
    "powertrain_miles": 60000,
}

BRAKE_OPERATION = {
    "op_code": "A1234-56",
    "description": "Front brake pad replacement",
    "standard_time_hours": 1.5,
    "max_time_hours": 2.5,
    "category": "BASIC",
    "requires_causal_part": True,
    "causal_failure_group": "BRAKE_FRONT",
    "overlap_group": "BRAKE_FRONT",
}

BRAKE_PART = {
    "part_number": "BRK-PAD-9931",
    "description": "Front brake pad set",
    "dealer_net_cents": 24799,
    "failure_group": "BRAKE_FRONT",
    "return_required": True,
    "retention_days": 30,
}

BRAKE_CLAIM = {
    "repair_order_number": "RO-1001",
    "repair_date": "2026-04-10",
    "odometer_at_repair": 20000,
    "claimed_labor_hours": 1.5,
    "claimed_parts_qty": 3,
    "complaint_text": "Customer reports brake squeal at low speed.",
    "cause_text": "Front brake pads worn beyond specification.",
    "correction_text": "Replaced front brake pads and verified normal braking.",
}

GW_DEALER_TERMS = {
    "dealer_code": "D-GW",
    "name": "Goodwill Motors",
    "vehicles_in_operation": 100,
    "initial_labor_rate_cents": 10000,
    "initial_parts_markup_pct": 0.25,
}

GW_VEHICLE = {
    "vin": "VIN00000000000GW1",
    "model_year": 2023,
    "warranty_start_date": "2023-06-15",
    "in_service_odometer": 0,
    "basic_months": 36,
    "basic_miles": 36000,
    "powertrain_months": 60,
    "powertrain_miles": 60000,
}

GW_OPERATION = {
    "op_code": "GW-200",
    "description": "Cabin HVAC blower replacement",
    "standard_time_hours": 1.0,
    "max_time_hours": 1.5,
    "category": "BASIC",
    "requires_causal_part": True,
    "causal_failure_group": "HVAC",
    "overlap_group": "HVAC",
}

GW_PART = {
    "part_number": "GW-P1",
    "description": "HVAC blower motor",
    "dealer_net_cents": 40000,
    "failure_group": "HVAC",
    "return_required": True,
    "retention_days": 30,
}

GW_CLAIM = {
    "repair_order_number": "RO-GW-1",
    "repair_date": "2026-05-14",
    "odometer_at_repair": 39600,
    "claimed_labor_hours": 1.0,
    "claimed_parts_qty": 1,
    "complaint_text": "Customer reports intermittent fault on delivery.",
    "cause_text": "Component failed internal leak test at the dealership.",
    "correction_text": "Replaced the failed component and road tested the vehicle.",
}


def build_brake_world():
    """CA statute, dealer D1 at 13750 and 0.40, one covered vehicle, the front-brake
    operation and its return-required causal part, plus claim RO-1001."""
    set_clock("2026-05-01T00:00:00Z")
    return setup_claim(
        profile_overrides=CA_PROFILE,
        dealer_overrides=D1_TERMS,
        vehicle_overrides=COVERED_VEHICLE,
        operation_overrides=BRAKE_OPERATION,
        part_overrides=BRAKE_PART,
        claim_overrides=BRAKE_CLAIM,
    )


def build_out_of_warranty_world():
    """Dealer D-GW with a repair 3,600 miles past the vehicle's basic mileage limit, so
    the claim opens with no coverage."""
    set_clock("2026-05-20T00:00:00Z")
    return setup_claim(
        profile_overrides=CA_PROFILE,
        dealer_overrides=GW_DEALER_TERMS,
        vehicle_overrides=GW_VEHICLE,
        operation_overrides=GW_OPERATION,
        part_overrides=GW_PART,
        claim_overrides=GW_CLAIM,
    )


class TestStateLawProfileFieldContract:
    def test_01_registration_echoes_every_statute_field_and_omits_version(self):
        """PRD §3.1: "The profile carries `markup_cap_pct`, the statutory ceiling on dealer parts markup expressed as a decimal fraction between 0.00 and 1.00 inclusive and carried to two decimal places; `labor_rate_method`, which is either `RETAIL_SAMPLE` or `TIME_AND_PRICE` and selects how the labor-rate ceiling is established; `min_sample_repair_orders`, the minimum number of customer-pay repair orders a retail-sample petition must cite, which may be zero or more; `max_labor_rate_cents`, an absolute statutory cap on the hourly warranty labor rate that must be strictly positive; `deemed_approved_days`, a strictly positive count of days after which an untouched petition is deemed approved; and `appeal_window_days`, a strictly positive count of days a dealer has to appeal issued findings."
        PRD §2.4: "Six record kinds are configuration or append-only history and therefore carry only `id` and `created_at` — both `updated_at` and `version` are absent from them entirely."
        PRD §4: "Endpoints that create a resource return HTTP 201 on success; every other successful call returns HTTP 200, including the state-transition endpoints, the sweep endpoints and the computed reads."
        PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."

        Design: Corner/entities/state_law_profile_create_returns_all_declared_fields
        """
        set_clock("2026-05-01T00:00:00Z")

        response = api_client.create_state_law_profile(
            create_state_law_profile_payload(**TX_PROFILE), ADMIN
        )
        profile = validate_success(response, 201)

        assert profile["state_code"] == "TX"
        assert profile["markup_cap_pct"] == pytest.approx(0.40, abs=0.001)
        assert profile["labor_rate_method"] == "TIME_AND_PRICE"
        assert profile["min_sample_repair_orders"] == 5
        assert profile["max_labor_rate_cents"] == 20000
        assert profile["deemed_approved_days"] == 45
        assert profile["appeal_window_days"] == 20
        assert profile["id"]
        assert profile["created_at"]
        assert "updated_at" not in profile
        assert "version" not in profile

        envelope = response.json()
        assert envelope["response_type"] == "object"
        assert envelope["meta"]["api_request_id"].startswith("req_")

    def test_02_registered_profile_is_never_mutated_and_carries_no_version(self):
        """PRD §2.4: "A `StateLawProfile` in particular is never mutated after creation, and a `ClaimEdit` is only ever amended by stamping its `resolved_at`, which the append-only ledger analogy tolerates because the row's substance does not change."
        PRD §2.4: "Six record kinds are configuration or append-only history and therefore carry only `id` and `created_at` — both `updated_at` and `version` are absent from them entirely."
        PRD §3.1: "A profile is configuration and is never mutated once registered."

        Design: Corner/entities/state_law_profile_immutable_with_no_version_field
        """
        set_clock("2026-05-01T00:00:00Z")
        profile = create_state_law_profile(**CA_PROFILE)

        read_back = validate_success(
            api_client.get_state_law_profile(profile["id"], ADMIN), 200
        )
        assert read_back == profile
        assert "version" not in read_back
        assert "updated_at" not in read_back

        # Enrolling a dealer that cites the statute changes nothing on the statute itself.
        create_dealer(profile["id"], **D1_TERMS)
        after_enrollment = validate_success(
            api_client.get_state_law_profile(profile["id"], ADMIN), 200
        )
        assert after_enrollment == profile
        assert "version" not in after_enrollment
        assert "updated_at" not in after_enrollment


class TestDealerFieldContract:
    def test_03_enrollment_stores_the_paid_terms_and_opens_the_computed_counters(self):
        """PRD §3.1: "Enrolling a dealer establishes `dealer_code`, the manufacturer's non-empty and program-unique dealer code; `name`, the dealer's non-empty legal name; `state_law_profile_id`, naming the statute that governs this dealer's rates; and `vehicles_in_operation`, the non-negative count of vehicles in the dealer's territory that serves as the denominator for warranty-expense analytics."
        PRD §3.1: "Enrollment also takes `initial_labor_rate_cents` and `initial_parts_markup_pct`, which are copied straight into the dealer's live `approved_labor_rate_cents` and `approved_parts_markup_pct` — the only two fields that describe what the dealer is paid today."
        PRD §3.1: "A newly enrolled dealer opens `ACTIVE`, with `chargeback_balance_cents` at 0, `open_parts_return_count` at 0, `audit_hold` false, `outlier_flag` false, `version` at 1, and `labor_rate_effective_date` left null until the dealer's first petition is approved."

        Design: Corner/entities/dealer_retrieval_returns_stored_and_computed_fields
        """
        set_clock("2026-05-01T00:00:00Z")
        profile = create_state_law_profile(**CA_PROFILE)
        created = create_dealer(profile["id"], **D1_TERMS)

        dealer = get_dealer(created["id"])

        assert dealer["dealer_code"] == "D1"
        assert dealer["name"] == "Dealer One"
        assert dealer["state_law_profile_id"] == profile["id"]
        assert dealer["vehicles_in_operation"] == 100
        assert dealer["approved_labor_rate_cents"] == 13750
        assert dealer["approved_parts_markup_pct"] == pytest.approx(0.40, abs=0.001)
        assert dealer["status"] == "ACTIVE"
        assert dealer["chargeback_balance_cents"] == 0
        assert dealer["open_parts_return_count"] == 0
        assert dealer["audit_hold"] is False
        assert dealer["outlier_flag"] is False
        assert dealer["version"] == 1
        assert dealer["labor_rate_effective_date"] is None
        assert dealer["id"] == created["id"]
        assert dealer["created_at"]
        assert dealer["updated_at"]

    def test_04_dealer_listing_reports_total_count_and_has_more_across_pages(self):
        """PRD §2.3: "`limit` controls page size: it defaults to 10 when omitted, may not be smaller than 1, and may not be larger than 100."
        PRD §2.3: "The `meta` block of a list response carries `limit` and `offset` as they were resolved for that request, `total_count` giving the number of records matching the filters before pagination was applied, and `has_more`, which is true exactly when records matching the filters remain beyond the current page."
        PRD §4: "Endpoints that create a resource return HTTP 201 on success; every other successful call returns HTTP 200, including the state-transition endpoints, the sweep endpoints and the computed reads."

        Design: Corner/entities/dealer_listing_paginates_with_total_count_and_has_more
        """
        set_clock("2026-05-01T00:00:00Z")
        profile = create_state_law_profile(**CA_PROFILE)
        enrolled = {
            create_dealer(
                profile["id"],
                dealer_code=code,
                name=name,
                vehicles_in_operation=100,
                initial_labor_rate_cents=13750,
                initial_parts_markup_pct=0.40,
            )["id"]
            for code, name in (
                ("D1", "Dealer One"),
                ("D2", "Dealer Two"),
                ("D3", "Dealer Three"),
            )
        }

        first_page, first_meta = validate_paginated(
            api_client.list_dealers(ADMIN, params={"limit": 2, "offset": 0})
        )
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0
        assert first_meta["total_count"] == 3
        assert first_meta["has_more"] is True
        assert len(first_page) == 2

        second_page, second_meta = validate_paginated(
            api_client.list_dealers(ADMIN, params={"limit": 2, "offset": 2})
        )
        assert second_meta["limit"] == 2
        assert second_meta["offset"] == 2
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False
        assert len(second_page) == 1

        first_ids = {row["id"] for row in first_page}
        second_ids = {row["id"] for row in second_page}
        assert first_ids.isdisjoint(second_ids)
        assert first_ids | second_ids == enrolled

    def test_05_enrollment_missing_a_required_field_is_rejected_and_stores_nothing(self):
        """PRD §2.11: "Body shape: required fields present, enum values inside their declared domains, integers non-negative, decimal numerics parseable, dates in ISO-8601 calendar form, an audit's `period_start` strictly before its `period_end`, `requested_labor_rate_cents` strictly positive, `claimed_labor_hours` strictly positive, `claimed_parts_qty` at least 1 when a causal part is named and exactly 0 when none is, and a finding's `unsupported_amount_cents` non-negative — `ERR_VALIDATION`."
        PRD §3.1: "Enrolling a dealer establishes `dealer_code`, the manufacturer's non-empty and program-unique dealer code; `name`, the dealer's non-empty legal name; `state_law_profile_id`, naming the statute that governs this dealer's rates; and `vehicles_in_operation`, the non-negative count of vehicles in the dealer's territory that serves as the denominator for warranty-expense analytics."

        Design: Corner/entities/dealer_create_missing_required_fields_rejected
        """
        set_clock("2026-05-01T00:00:00Z")
        profile = create_state_law_profile(**CA_PROFILE)

        without_code = create_dealer_payload(profile["id"], **D1_TERMS)
        del without_code["dealer_code"]
        validate_error(
            api_client.create_dealer(without_code, ADMIN),
            ApiErrorId.ERR_VALIDATION.value,
            422,
        )

        without_vehicle_count = create_dealer_payload(profile["id"], **D1_TERMS)
        del without_vehicle_count["vehicles_in_operation"]
        validate_error(
            api_client.create_dealer(without_vehicle_count, ADMIN),
            ApiErrorId.ERR_VALIDATION.value,
            422,
        )

        rows, meta = validate_paginated(
            api_client.list_dealers(ADMIN, params={"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 0
        assert rows == []


class TestWarrantyClaimFieldContract:
    def test_06_a_clean_submission_opens_with_the_declared_field_defaults(self):
        """PRD §3.3: "A newly created claim opens with `version` at 1, with `payment_status` at `UNPAID`, and with `status` at either `SUBMITTED` or `SUSPENDED` depending on what the edit engine finds."
        PRD §3.4: "`suspend_edit_count` is then set to the number of edits just appended whose `severity` is `SUSPEND`, and the claim's `status` follows directly: `SUSPENDED` when that count is greater than zero, `SUBMITTED` when it is zero."
        PRD §3.3: "A submission may also carry `resubmission_of_claim_id`, naming the earlier claim this one replaces after a dealer correction; it defaults to null for an original submission and, when supplied, must name a real claim or the request fails with `ERR_CLAIM_NOT_FOUND`."

        Design: Corner/entities/claim_created_applies_declared_field_defaults
        """
        world = build_brake_world()
        claim = world["claim"]

        assert claim["status"] == "SUBMITTED"
        assert claim["payment_status"] == "UNPAID"
        assert claim["suspend_edit_count"] == 0
        assert claim["version"] == 1
        assert claim["resubmission_of_claim_id"] is None

        read_back = get_claim(claim["id"])
        assert read_back["status"] == "SUBMITTED"
        assert read_back["payment_status"] == "UNPAID"
        assert read_back["suspend_edit_count"] == 0
        assert read_back["version"] == 1
        assert read_back["resubmission_of_claim_id"] is None

    def test_07_reading_an_unknown_claim_id_returns_the_not_found_envelope(self):
        """PRD §2.7: "The twelve not-found codes are `ERR_STATE_LAW_PROFILE_NOT_FOUND`, `ERR_DEALER_NOT_FOUND`, `ERR_VEHICLE_NOT_FOUND`, `ERR_LABOR_OPERATION_NOT_FOUND`, `ERR_CATALOG_ITEM_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_LABOR_RATE_REQUEST_NOT_FOUND`, `ERR_PARTS_RETURN_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`, `ERR_FINDING_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND` and `ERR_GOODWILL_AUTH_NOT_FOUND`, all HTTP 404."
        PRD §2.11: "Path-parameter existence — the twelve not-found codes."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."
        PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."

        Design: Corner/entities/claim_get_with_unknown_id_returns_claim_not_found
        """
        world = build_brake_world()
        # The live claim proves the read path itself works before probing an absent id.
        assert get_claim(world["claim"]["id"])["id"] == world["claim"]["id"]

        response = api_client.get_claim(UNKNOWN_ID, ADMIN)
        validate_error(response, ApiErrorId.ERR_CLAIM_NOT_FOUND.value, 404)

        envelope = response.json()
        assert envelope["response_type"] == "error"
        assert envelope["data"]["error_id"] == "ERR_CLAIM_NOT_FOUND"
        assert envelope["data"]["message"]
        assert set(envelope["meta"]) == {"api_request_id", "api_request_timestamp"}
        assert envelope["meta"]["api_request_id"].startswith("req_")


class TestPartsReturnObligationFieldContract:
    def test_08_submission_mints_the_obligation_linking_the_claim_and_the_part(self):
        """PRD §3.4: "When the submission's causal part has `return_required` true, the same request also raises a parts-return obligation in `REQUESTED`, whose `due_date` is its own `created_at` advanced by the part's `retention_days` days, and increments the dealer's `open_parts_return_count` by 1 — re-establishing the invariant that the count always equals the number of parts-return rows in `REQUESTED` whose claim belongs to that dealer."
        PRD §3.7: "The obligation names the `claim_id` that created it and the `part_id` to be returned, both established by the cascade at claim submission rather than by any request body, and both visible only through the parts-return listing, which filters on `claim_id`, `part_id` and `status` alongside `limit` and `offset`."
        PRD §3.7: "The obligation opens in `REQUESTED` with a `due_date` derived from its own creation instant and the part's retention window, with `received_date`, `analysis_result` and `analysis_note` all null, and with `debit_amount_cents` and `reversed_amount_cents` both at 0."
        PRD §2.6: "A parts-return request's `due_date` is its own `created_at` advanced by the causal part's `retention_days` days."
        PRD §2.6: "Every deadline, retention window, appeal window and analytics window in this system is evaluated against a server-held logical clock, never against real wall-clock time."

        Design: Corner/entities/parts_return_junction_links_claim_and_catalog_item
        """
        world = build_brake_world()

        rows, meta = validate_paginated(
            api_client.list_parts_returns(
                ADMIN,
                params={"claim_id": world["claim"]["id"], "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 1
        obligation = rows[0]

        assert obligation["claim_id"] == world["claim"]["id"]
        assert obligation["part_id"] == world["part"]["id"]
        assert obligation["status"] == "REQUESTED"
        assert obligation["received_date"] is None
        assert obligation["analysis_result"] is None
        assert obligation["analysis_note"] is None
        assert obligation["debit_amount_cents"] == 0
        assert obligation["reversed_amount_cents"] == 0
        assert obligation["version"] == 1

        # The 30-day retention window runs from the obligation's own creation instant,
        # which the logical clock holds at 2026-05-01.
        assert_date_equals(obligation["created_at"], "2026-05-01", "created_at")
        assert_date_equals(obligation["due_date"], "2026-05-31", "due_date")
        expected_due = date.fromisoformat(str(obligation["created_at"])[:10]) + timedelta(
            days=30
        )
        assert_date_equals(obligation["due_date"], expected_due.isoformat(), "due_date")

        assert get_dealer(world["dealer"]["id"])["open_parts_return_count"] == 1

    def test_09_analysis_outside_the_declared_result_domain_is_rejected(self):
        """PRD §3.7: "A `WarrantyAdmin` supplies an `analysis_result` — one of `DEFECT_CONFIRMED`, `NO_DEFECT_FOUND` or `NOT_AVAILABLE` — together with a free-text `analysis_note`, and both are recorded as the obligation moves `RECEIVED → ANALYZED`."
        PRD §2.11: "Body shape: required fields present, enum values inside their declared domains, integers non-negative, decimal numerics parseable, dates in ISO-8601 calendar form, an audit's `period_start` strictly before its `period_end`, `requested_labor_rate_cents` strictly positive, `claimed_labor_hours` strictly positive, `claimed_parts_qty` at least 1 when a causal part is named and exactly 0 when none is, and a finding's `unsupported_amount_cents` non-negative — `ERR_VALIDATION`."
        PRD §3.1: "Flat-rate labor operations are published with an `op_code` that is non-empty and unique, a non-empty human-readable `description`, and two time figures carried to one decimal place: `standard_time_hours`, strictly positive, which is what the manufacturer will actually reimburse, and `max_time_hours`, at least equal to standard time, which is the absolute ceiling above which a claim is not accepted at all."

        Design: Corner/entities/parts_return_analysis_invalid_enum_rejected
        """
        world = build_brake_world()
        obligation = parts_return_for_claim(world["claim"]["id"])
        received = receive_part(obligation["id"], "2026-05-01")
        assert received["status"] == "RECEIVED"

        validate_error(
            api_client.analyze_parts_return(
                obligation["id"],
                analyze_parts_return_payload(
                    analysis_result="MAYBE_DEFECT",
                    analysis_note="Bench test inconclusive.",
                ),
                ADMIN,
            ),
            ApiErrorId.ERR_VALIDATION.value,
            422,
        )

        validate_error(
            api_client.create_labor_operation(
                create_labor_operation_payload(
                    op_code="ZERO-1",
                    description="Zero time operation",
                    standard_time_hours=0,
                    max_time_hours=1.0,
                    category="BASIC",
                    requires_causal_part=False,
                    causal_failure_group=None,
                    overlap_group="MISC",
                ),
                ADMIN,
            ),
            ApiErrorId.ERR_VALIDATION.value,
            422,
        )

        unchanged = get_parts_return(obligation["id"])
        assert unchanged["status"] == "RECEIVED"
        assert unchanged["analysis_result"] is None
        assert unchanged["debit_amount_cents"] == 0
        assert unchanged["version"] == 2


class TestGoodwillAuthorizationParentContract:
    def test_10_raising_goodwill_under_an_unknown_claim_reports_claim_not_found(self):
        """PRD §2.7: "The outer identifier is looked up first, and if it names no live record the request fails immediately with that entity's not-found code — the inner identifier is not consulted at all."
        PRD §2.11: "Checks are evaluated in the following order, and the first one that fails determines the response; no later check is consulted."
        PRD §2.11: "Path-parameter existence — the twelve not-found codes."
        PRD §2.7: "The twelve not-found codes are `ERR_STATE_LAW_PROFILE_NOT_FOUND`, `ERR_DEALER_NOT_FOUND`, `ERR_VEHICLE_NOT_FOUND`, `ERR_LABOR_OPERATION_NOT_FOUND`, `ERR_CATALOG_ITEM_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_LABOR_RATE_REQUEST_NOT_FOUND`, `ERR_PARTS_RETURN_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`, `ERR_FINDING_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND` and `ERR_GOODWILL_AUTH_NOT_FOUND`, all HTTP 404."

        Design: Corner/entities/goodwill_authorization_under_unknown_claim_returns_claim_not_found
        """
        world = build_out_of_warranty_world()
        claim = world["claim"]
        assert claim["coverage_type"] == "NONE"

        validate_error(
            api_client.create_goodwill_authorization(
                UNKNOWN_ID,
                create_goodwill_authorization_payload(
                    expected_claim_version=claim["version"],
                    requested_amount_cents=40000,
                    policy_adjustment_pct=0.25,
                    justification="Loyal customer, repeat visit.",
                ),
                ADJUDICATOR,
            ),
            ApiErrorId.ERR_CLAIM_NOT_FOUND.value,
            404,
        )

        rows, meta = validate_paginated(
            api_client.list_goodwill_authorizations(
                ADJUDICATOR, params={"claim_id": claim["id"], "limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 0
        assert rows == []
        assert get_claim(claim["id"])["version"] == 1
