"""Claim ingestion gates, lifecycle transitions, and privacy/temporal ordering."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    add_beneficiary,
    adjudicate,
    assert_claim_line,
    create_claim_payload,
    create_period,
    ingest_claim,
    open_period,
    validate_error,
    validate_success,
    void_claim,
)


class TestClaimIngestionGate:
    def test_claim_ingest_rejected_while_period_setup(self, api, claims_headers):
        """PRD §3.2: "A `ClaimsProcessor` ingests claim lines while the period is
        `OPEN`; ingestion against a period in any other status is rejected with
        `ERR_PERIOD_NOT_OPEN`."

        Design: Difficulty/cross_entity_state_dependency/claim_ingest_blocked_until_period_open
        """
        period = create_period(tax_id="ACO-XD3")
        beneficiary = add_beneficiary("MBI-XD3", 1980)
        res = api.create_claim(
            create_claim_payload(period["id"], beneficiary["id"],
                                 service_date="2026-03-01", allowed_amount_cents=1000),
            claims_headers,
        )
        validate_error(res, ApiErrorId.ERR_PERIOD_NOT_OPEN, expected_status=409)

    def test_claim_ingest_succeeds_after_open(self, api, claims_headers):
        """PRD §3.2: "A claim line starts life in `RECEIVED` status and carries
        `review_excluded` initialized to false."

        Design: Difficulty/cross_entity_state_dependency/claim_ingest_blocked_until_period_open
        """
        period = create_period(tax_id="ACO-XD3B")
        beneficiary = add_beneficiary("MBI-XD3B", 1980)
        open_period(period["id"])
        res = api.create_claim(
            create_claim_payload(period["id"], beneficiary["id"],
                                 service_date="2026-03-01", allowed_amount_cents=1000),
            claims_headers,
        )
        claim = validate_success(res, 201)
        assert_claim_line(claim)
        assert claim["status"] == "RECEIVED"
        assert claim["review_excluded"] is False


class TestClaimSchemaAndTemporalValidation:
    def test_claim_missing_service_date_returns_invalid_request(self, api, claims_headers):
        """PRD §2.5: "required fields present, types valid, enum members valid,
        and unknown fields rejected, else `ERR_INVALID_REQUEST` (HTTP 400)".
        PRD §3.2: "Each claim line names its `agreement_period_id`, the treated
        `beneficiary_id`, an optional rendering `participant_id` (meaningful for
        `PART_B` claims, where it drives attribution plurality, and typically
        absent on `PART_A` claims), the `service_date`, a strictly positive
        integer `allowed_amount_cents`, and the `claim_type`, exactly one of
        `PART_A` or `PART_B`."

        Design: Corner/validations/claim_missing_service_date_returns_invalid_request
        """
        period = create_period(tax_id="ACO-V1")
        beneficiary = add_beneficiary("MBI-V1", 1980)
        open_period(period["id"])
        payload = create_claim_payload(period["id"], beneficiary["id"],
                                       allowed_amount_cents=1000)
        del payload["service_date"]
        res = api.create_claim(payload, claims_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_service_date_outside_period_rejected(self, api, claims_headers):
        """PRD §3.2: "The service date must lie inside the period's closed span
        from `performance_start_date` through `performance_end_date`; a date
        outside it is rejected with `ERR_DATE_OUTSIDE_PERIOD` (HTTP 422)."

        Design: Corner/validations/service_date_outside_period_rejected
        """
        period = create_period(tax_id="ACO-V4")
        beneficiary = add_beneficiary("MBI-V4", 1980)
        open_period(period["id"])
        res = api.create_claim(
            create_claim_payload(period["id"], beneficiary["id"],
                                 service_date="2027-01-01", allowed_amount_cents=1000),
            claims_headers,
        )
        validate_error(res, ApiErrorId.ERR_DATE_OUTSIDE_PERIOD, expected_status=422)

    def test_claim_create_missing_auth_header_unauthenticated(self, api):
        """PRD §2.1: "A request in which either header is missing or empty is
        rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/claim_create_missing_auth_header_unauthenticated
        """
        res = api.create_claim(
            create_claim_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID,
                                 service_date="2026-03-01", allowed_amount_cents=100),
            headers={},
        )
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


class TestValidationOrderOnClaimCreate:
    def test_period_posture_error_precedes_temporal_on_claim_create(self, api, claims_headers):
        """PRD §2.5: "When several validation rules could reject the same request,
        the server evaluates them in a fixed order so that the surfaced error is
        deterministic" — period posture gates (step 6) are evaluated before
        temporal placement (step 11).
        PRD §3.2: "ingestion against a period in any other status is rejected
        with `ERR_PERIOD_NOT_OPEN`".

        Design: Difficulty/priority_pair_validation_conflict/conflict_state_beats_temporal_on_claim_create
        """
        period = create_period(tax_id="ACO-PC1")  # stays SETUP
        beneficiary = add_beneficiary("MBI-PC1", 1980)
        res = api.create_claim(
            create_claim_payload(period["id"], beneficiary["id"],
                                 service_date="2027-05-01", allowed_amount_cents=1000),
            claims_headers,
        )
        validate_error(res, ApiErrorId.ERR_PERIOD_NOT_OPEN, expected_status=409)

    def test_period_posture_wins_with_pre_span_date_too(self, api, claims_headers):
        """PRD §2.5: "6. **Period posture gates** — the period-status requirements
        of each workflow (for example, claim ingestion requires an `OPEN` period),
        else the corresponding `ERR_PERIOD_NOT_OPEN` or `ERR_PERIOD_NOT_LOCKED`."
        is listed before "11. **Temporal placement**".

        Design: Difficulty/priority_pair_validation_conflict/conflict_state_beats_temporal_on_claim_create
        """
        period = create_period(tax_id="ACO-PC1B")  # stays SETUP
        beneficiary = add_beneficiary("MBI-PC1B", 1980)
        res = api.create_claim(
            create_claim_payload(period["id"], beneficiary["id"],
                                 service_date="2025-06-15", allowed_amount_cents=1000),
            claims_headers,
        )
        validate_error(res, ApiErrorId.ERR_PERIOD_NOT_OPEN, expected_status=409)

    def test_privacy_gate_precedes_temporal_on_claim_create(self, api, admin_headers,
                                                            claims_headers):
        """PRD §2.5: "9. **Privacy** — the opt-out gate on claim ingestion, else
        `ERR_BENEFICIARY_OPTED_OUT`." is listed before "11. **Temporal
        placement**".
        PRD §3.2: "if the beneficiary's latest data-sharing election with an
        `effective_date` on or before the claim's `service_date` is an
        `OPT_OUT`, ingestion is rejected with `ERR_BENEFICIARY_OPTED_OUT`
        (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/conflict_safety_beats_temporal_on_claim_create
        """
        period = create_period(tax_id="ACO-PC2")
        beneficiary = add_beneficiary("MBI-PC2", 1980)
        open_period(period["id"])
        validate_success(
            api.create_data_sharing_election(
                beneficiary["id"],
                {"direction": "OPT_OUT", "effective_date": "2026-01-01"},
                admin_headers,
            ),
            201,
        )
        res = api.create_claim(
            create_claim_payload(period["id"], beneficiary["id"],
                                 service_date="2027-05-01", allowed_amount_cents=1000),
            claims_headers,
        )
        validate_error(res, ApiErrorId.ERR_BENEFICIARY_OPTED_OUT, expected_status=422)

    def test_privacy_gate_precedes_temporal_with_far_future_date(self, api, admin_headers,
                                                                 claims_headers):
        """PRD §3.2: "Privacy is enforced at the door: if the beneficiary's
        latest data-sharing election with an `effective_date` on or before the
        claim's `service_date` is an `OPT_OUT`, ingestion is rejected with
        `ERR_BENEFICIARY_OPTED_OUT` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/conflict_safety_beats_temporal_on_claim_create
        """
        period = create_period(tax_id="ACO-PC2B")
        beneficiary = add_beneficiary("MBI-PC2B", 1980)
        open_period(period["id"])
        validate_success(
            api.create_data_sharing_election(
                beneficiary["id"],
                {"direction": "OPT_OUT", "effective_date": "2026-01-01"},
                admin_headers,
            ),
            201,
        )
        res = api.create_claim(
            create_claim_payload(period["id"], beneficiary["id"],
                                 service_date="2027-12-31", allowed_amount_cents=1000),
            claims_headers,
        )
        validate_error(res, ApiErrorId.ERR_BENEFICIARY_OPTED_OUT, expected_status=422)


class TestClaimStateMachine:
    def test_claim_double_adjudicate_rejected(self, api, claims_headers):
        """PRD §3.2: "Adjudication moves a claim from `RECEIVED` to
        `ADJUDICATED`; attempting it on a claim in any other status yields
        `ERR_CLAIM_INVALID_STATE` (HTTP 409)".

        Design: Corner/state_machines/claim_double_adjudicate_rejected
        """
        period = create_period(tax_id="ACO-S1")
        beneficiary = add_beneficiary("MBI-S1", 1980)
        open_period(period["id"])
        claim = ingest_claim(period["id"], beneficiary["id"], "2026-03-01", 5000, "PART_A")
        adjudicate(claim["id"])
        res = api.adjudicate_claim(claim["id"], claims_headers)
        validate_error(res, ApiErrorId.ERR_CLAIM_INVALID_STATE, expected_status=409)

    def test_claim_voided_terminal_lockdown(self, api, claims_headers):
        """PRD §3.2: "a claim in `ADJUDICATED` may move to `VOIDED` (any other
        status draws `ERR_CLAIM_INVALID_STATE`)".

        Design: Corner/state_machines/claim_voided_terminal_lockdown
        """
        period = create_period(tax_id="ACO-S2")
        beneficiary = add_beneficiary("MBI-S2", 1980)
        open_period(period["id"])
        claim = ingest_claim(period["id"], beneficiary["id"], "2026-03-01", 5000, "PART_A")
        adjudicate(claim["id"])
        void_claim(claim["id"], reason="dup")

        res_void = api.void_claim(claim["id"], {"reason": "again"}, claims_headers)
        validate_error(res_void, ApiErrorId.ERR_CLAIM_INVALID_STATE, expected_status=409)
        res_adj = api.adjudicate_claim(claim["id"], claims_headers)
        validate_error(res_adj, ApiErrorId.ERR_CLAIM_INVALID_STATE, expected_status=409)
