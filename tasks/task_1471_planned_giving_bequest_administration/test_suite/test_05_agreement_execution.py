"""Gift agreement execution: gates, boundaries, priorities, booked economics."""
from test_helpers import (
    CRAT80_ACTUARIAL_LIABILITY_CENTS,
    CRAT80_DEDUCTION_CENTS,
    EXHAUSTION_BAND_PAYOUT_BPS,
    STD_CGA_RESERVE_REQUIREMENT_CENTS,
    ApiErrorId,
    assert_gift_agreement,
    contribute_reserve,
    create_gift_asset_payload,
    make_active_rate_table,
    make_donor,
    make_draft_agreement,
    make_executed_agreement,
    make_illustration,
    make_verified_designation,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_reserve,
)


class TestAgreementCreateValidation:
    def test_agreement_create_invalid_enum_rejected(self, api, gift_officer_headers):
        """PRD §3.3: a gift agreement payload carries "`vehicle_type`" drawn from
        the illustration vocabulary of §3.2 — "one of `CGA`, `CRT_UNITRUST`,
        `CRT_ANNUITY`, or `BEQUEST`".
        PRD §2.10: "Envelope and schema conformance — `ERR_INVALID_REQUEST`:
        unknown fields, malformed types, invalid enum members, missing required
        fields, a `valuation_date` outside its own coverage window, or a
        `defer_until` not in the future."

        Design: Corner/entities/agreement_create_invalid_enum_rejected
        """
        donor = make_donor(full_name="Enum")
        make_active_rate_table()
        resp = api.create_gift_agreement(
            {
                "donor_id": donor["id"],
                "vehicle_type": "POOLED_INCOME",
                "gift_amount_cents": 1000000,
                "funding_month": "2026-08",
            },
            gift_officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert resp.status_code == 400


class TestPayoutRateBoundaries:
    def _setup(self):
        donor = make_donor(full_name="Boundary Rate")
        make_active_rate_table()
        return donor

    def test_payout_rate_lower_boundary_499_rejected_500_accepted(
        self, api, gift_officer_headers
    ):
        """PRD §3.2: "Where a payout rate is supplied it must lie within 500 to
        5000 basis points inclusive — 500 is accepted and 499 rejected, 5000 is
        accepted and 5001 rejected — or the request fails with
        `ERR_PAYOUT_RATE_OUT_OF_RANGE` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/payout_rate_boundaries_500_and_5000
        """
        donor = self._setup()
        resp = api.create_gift_agreement(
            {
                "donor_id": donor["id"],
                "vehicle_type": "CRT_ANNUITY",
                "gift_amount_cents": 10000000,
                "payout_rate_bps": 499,
                "lives": 1,
                "annuitant_1_age": 80,
                "funding_month": "2026-08",
            },
            gift_officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_PAYOUT_RATE_OUT_OF_RANGE)
        assert resp.status_code == 422

        resp = api.create_gift_agreement(
            {
                "donor_id": donor["id"],
                "vehicle_type": "CRT_ANNUITY",
                "gift_amount_cents": 10000000,
                "payout_rate_bps": 500,
                "lives": 1,
                "annuitant_1_age": 80,
                "funding_month": "2026-08",
            },
            gift_officer_headers,
        )
        data = validate_success(resp, 201)
        assert data["status"] == "DRAFT"
        assert data["payout_rate_bps"] == 500

    def test_payout_rate_upper_boundary_5000_accepted_5001_rejected(
        self, api, gift_officer_headers
    ):
        """PRD §3.2: "Where a payout rate is supplied it must lie within 500 to
        5000 basis points inclusive — 500 is accepted and 499 rejected, 5000 is
        accepted and 5001 rejected — or the request fails with
        `ERR_PAYOUT_RATE_OUT_OF_RANGE` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/payout_rate_boundaries_500_and_5000
        """
        donor = self._setup()
        resp = api.create_gift_agreement(
            {
                "donor_id": donor["id"],
                "vehicle_type": "CRT_ANNUITY",
                "gift_amount_cents": 10000000,
                "payout_rate_bps": 5000,
                "lives": 1,
                "annuitant_1_age": 95,
                "funding_month": "2026-08",
            },
            gift_officer_headers,
        )
        data = validate_success(resp, 201)
        assert data["status"] == "DRAFT"
        assert data["payout_rate_bps"] == 5000

        resp = api.create_gift_agreement(
            {
                "donor_id": donor["id"],
                "vehicle_type": "CRT_ANNUITY",
                "gift_amount_cents": 10000000,
                "payout_rate_bps": 5001,
                "lives": 1,
                "annuitant_1_age": 95,
                "funding_month": "2026-08",
            },
            gift_officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_PAYOUT_RATE_OUT_OF_RANGE)
        assert resp.status_code == 422


class TestExecutionGates:
    def test_generate_schedule_from_draft_rejected(self, api, gift_admin_headers):
        """PRD §3.6: "Once an agreement is `FUNDED`, a `GiftAdministrator`
        generates its payment schedule".
        PRD §2.10: "State-machine legality for the requested transition or
        action — `ERR_INVALID_STATE`, including terminal-state lockdown".

        Design: Corner/state_machines/agreement_generate_schedule_from_draft_rejected
        """
        donor = make_donor(full_name="Skip State", date_of_birth="1946-06-01T00:00:00Z")
        make_active_rate_table()
        agreement = make_draft_agreement(donor["id"])

        resp = api.generate_payment_schedule(agreement["id"], gift_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409

        _payments, meta = validate_paginated(
            api.list_annuity_payments(
                gift_admin_headers, params={"gift_agreement_id": agreement["id"]}
            )
        )
        assert meta["total_count"] == 0

    def test_withdrawn_agreement_is_terminal(self, api, gift_admin_headers):
        """PRD §3.3: "From `DRAFT`, a `GiftAdministrator` may `WITHDRAW` the
        agreement to `WITHDRAWN`" and the lifecycle's terminal states are
        "`SETTLED`, `WITHDRAWN`, `RESCINDED`, and `TERMINATED` terminal".
        PRD §2.10: "State-machine legality for the requested transition or
        action — `ERR_INVALID_STATE`, including terminal-state lockdown".

        Design: Corner/state_machines/withdrawn_agreement_is_terminal
        """
        donor = make_donor(full_name="Terminal", date_of_birth="1946-06-01T00:00:00Z")
        make_active_rate_table()
        agreement = make_draft_agreement(donor["id"])
        withdrawn = validate_success(
            api.transition_gift_agreement(
                agreement["id"], {"action": "WITHDRAW"}, gift_admin_headers
            )
        )
        assert withdrawn["status"] == "WITHDRAWN"

        resp = api.execute_gift_agreement(agreement["id"], gift_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409

        # Amend carries the CURRENT version, so the optimistic-concurrency
        # guard passes and the state gate is the failing check.
        current = validate_success(api.get_gift_agreement(agreement["id"], gift_admin_headers))
        resp = api.amend_gift_agreement(
            agreement["id"],
            {
                "expected_gift_agreement_version": current["version"],
                "restriction_type": "RESEARCH",
            },
            gift_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409

    def test_execute_without_verified_designation_rejected(
        self, api, gift_officer_headers, gift_admin_headers
    ):
        """PRD §3.3: "the documentation gate — a `VERIFIED` beneficiary
        designation with `slot` `PRIMARY_1` must exist, else
        `ERR_DESIGNATION_NOT_VERIFIED` (HTTP 409)".

        Design: Corner/validations/execute_without_verified_designation_rejected
        """
        donor = make_donor(full_name="No Verify", date_of_birth="1946-06-01T00:00:00Z")
        make_active_rate_table()
        agreement = make_draft_agreement(donor["id"])
        designation = validate_success(
            api.create_beneficiary_designation(
                {
                    "gift_agreement_id": agreement["id"],
                    "slot": "PRIMARY_1",
                    "beneficiary_name": "Heir",
                    "document_received": True,
                },
                gift_officer_headers,
            ),
            201,
        )
        validate_success(
            api.transition_beneficiary_designation(
                designation["id"], {"action": "SUBMIT"}, gift_officer_headers
            )
        )
        # Designation is SUBMITTED (documented but not verified).
        resp = api.execute_gift_agreement(agreement["id"], gift_admin_headers)
        validate_error(resp, ApiErrorId.ERR_DESIGNATION_NOT_VERIFIED)
        assert resp.status_code == 409
        after = validate_success(api.get_gift_agreement(agreement["id"], gift_admin_headers))
        assert after["status"] == "DRAFT"

    def test_bequest_vehicle_mismatch_rejected(self, api, gift_officer_headers):
        """PRD §3.3: "A `GiftAgreement` may also be created directly by a
        `GiftOfficer`, without any illustration, via a payload mirroring the
        illustration fields — `donor_id`, `vehicle_type`, `gift_amount_cents`,
        the conditional `payout_rate_bps`, `payment_frequency`, `lives`,
        `annuitant_1_age`, `annuitant_2_age`, `funding_month`".
        PRD §3.2: "For annuity vehicles the payload must carry
        `payout_rate_bps` (required) along with `annuitant_1_age`; a `BEQUEST`
        illustration must **not** carry `payout_rate_bps`, and violations in
        either direction are rejected with `ERR_BEQUEST_VEHICLE_MISMATCH`
        (HTTP 422)."

        Design: Corner/validations/bequest_vehicle_mismatch_rejected
        """
        donor = make_donor(full_name="Mismatch")
        make_active_rate_table()
        resp = api.create_gift_agreement(
            {
                "donor_id": donor["id"],
                "vehicle_type": "BEQUEST",
                "gift_amount_cents": 1000000,
                "payout_rate_bps": 600,
                "funding_month": "2026-08",
            },
            gift_officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_BEQUEST_VEHICLE_MISMATCH)
        assert resp.status_code == 422

        resp = api.create_gift_agreement(
            {
                "donor_id": donor["id"],
                "vehicle_type": "CRT_ANNUITY",
                "gift_amount_cents": 1000000,
                "lives": 1,
                "annuitant_1_age": 80,
                "funding_month": "2026-08",
            },
            gift_officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_BEQUEST_VEHICLE_MISMATCH)
        assert resp.status_code == 422

    def test_exhaustion_test_band_rejected(self, api, gift_admin_headers):
        """PRD §3.3: "the exhaustion test, which applies **only** to
        `CRT_ANNUITY` — the present value of the annuity must not exceed 85% of
        the gift principal, computed as `gift_amount_cents` times 8500 basis
        points and rounded half-up, else `ERR_EXHAUSTION_TEST_FAILED`
        (HTTP 422)".
        PRD §3.3: "The exhaustion band is deliberately tighter than the
        remainder ceiling: a present value in the band above 85% and at or
        below 90% passes the remainder test yet fails exhaustion, so each test
        exercises independently."

        Design: Corner/validations/exhaustion_test_band_rejected
        """
        donor = make_donor(full_name="Exhaustion", date_of_birth="1946-06-01T00:00:00Z")
        make_active_rate_table()
        agreement = make_draft_agreement(
            donor["id"],
            vehicle_type="CRT_ANNUITY",
            gift_amount_cents=10000000,
            payout_rate_bps=EXHAUSTION_BAND_PAYOUT_BPS,
            payment_frequency="ANNUAL",
            annuitant_1_age=80,
        )
        make_verified_designation(agreement["id"])
        # pv = round_half_up(700000 * a(20)@5%) = 8723547: passes the 10%
        # remainder floor (deduction 1276453) but exceeds the 85% limit.
        resp = api.execute_gift_agreement(agreement["id"], gift_admin_headers)
        validate_error(resp, ApiErrorId.ERR_EXHAUSTION_TEST_FAILED)
        assert resp.status_code == 422

    def test_agreement_funded_at_exact_gift_value(self, api, estate_manager_headers):
        """PRD §3.5: "if the agreement is `EXECUTED`, is not a `BEQUEST`
        (bequests are unfunded by definition and mature on death), and
        `received_value_cents` is at least `gift_amount_cents` — an inclusive
        boundary — the agreement auto-transitions to `FUNDED`".

        Design: Corner/state_machines/agreement_funded_at_exact_gift_value
        """
        donor = make_donor(full_name="Exact Funding", date_of_birth="1946-06-01T00:00:00Z")
        make_active_rate_table()
        agreement = make_executed_agreement(donor["id"])

        asset_1 = validate_success(
            api.create_gift_asset(
                create_gift_asset_payload(
                    gift_agreement_id=agreement["id"], pledged_value_cents=6000000
                ),
                estate_manager_headers,
            ),
            201,
        )
        validate_success(
            api.transition_gift_asset(asset_1["id"], {"action": "RECEIVE"}, estate_manager_headers)
        )
        mid = validate_success(api.get_gift_agreement(agreement["id"], estate_manager_headers))
        assert mid["status"] == "EXECUTED"
        assert mid["received_value_cents"] == 6000000

        asset_2 = validate_success(
            api.create_gift_asset(
                create_gift_asset_payload(
                    gift_agreement_id=agreement["id"], pledged_value_cents=4000000
                ),
                estate_manager_headers,
            ),
            201,
        )
        validate_success(
            api.transition_gift_asset(asset_2["id"], {"action": "RECEIVE"}, estate_manager_headers)
        )
        after = validate_success(api.get_gift_agreement(agreement["id"], estate_manager_headers))
        assert after["status"] == "FUNDED"
        assert after["received_value_cents"] == 10000000


class TestExecuteBookedEconomics:
    def test_immediate_consistency_execute_response(self, api, gift_admin_headers):
        """PRD §3.3: "A successful execution pins the agreement's booked
        economics: `annual_annuity_cents` (null for `BEQUEST`);
        `booked_deduction_cents` per the method above;
        `actuarial_liability_cents`, the present value of the future annuity
        obligation under the same factor method; `remainder_value_cents`,
        defined as `corpus_value_cents` minus `actuarial_liability_cents`
        floored at zero; `reserve_requirement_cents` for CGA agreements per
        §3.9 (zero for all other vehicles); and `corpus_value_cents`
        initialized to `gift_amount_cents`."
        PRD §2.2: "operations that create or modify a resource will return the
        created or updated resource object in the data field."

        Design: Corner/consistency_model/immediate_consistency_execute_response
        """
        donor = make_donor(full_name="Immediate", date_of_birth="1946-06-01T00:00:00Z")
        make_active_rate_table()
        agreement = make_draft_agreement(donor["id"], payment_frequency="QUARTERLY")
        make_verified_designation(agreement["id"])

        resp = api.execute_gift_agreement(agreement["id"], gift_admin_headers)
        data = validate_success(resp, 200)
        assert_gift_agreement(data)
        assert data["status"] == "EXECUTED"
        assert data["annual_annuity_cents"] == 500000
        assert data["booked_deduction_cents"] == CRAT80_DEDUCTION_CENTS
        assert data["actuarial_liability_cents"] == CRAT80_ACTUARIAL_LIABILITY_CENTS
        assert data["remainder_value_cents"] == CRAT80_DEDUCTION_CENTS
        assert data["corpus_value_cents"] == 10000000
        assert data["reserve_requirement_cents"] == 0


class TestStaleRateTableAtExecute:
    def _setup_booked_then_retired(self, api, gift_officer_headers, compliance_headers):
        """Illustration booked into a DRAFT agreement pinning table T, then T
        retired; PRIMARY_1 designation verified. Returns agreement id."""
        donor = make_donor(full_name="Stale Table", date_of_birth="1946-06-01T00:00:00Z")
        table = make_active_rate_table(
            label="7520-5pct-2026",
            effective_from="2026-01-01T00:00:00Z",
            effective_to="2026-12-01T00:00:00Z",
        )
        illustration = make_illustration(
            donor["id"],
            vehicle_type="CRT_ANNUITY",
            gift_amount_cents=10000000,
            payout_rate_bps=500,
            payment_frequency="QUARTERLY",
            annuitant_1_age=80,
            funding_month="2026-08",
        )
        agreement = validate_success(
            api.book_illustration(illustration["id"], gift_officer_headers), 201
        )
        validate_success(
            api.transition_rate_table(table["id"], {"action": "RETIRE"}, compliance_headers)
        )
        make_verified_designation(agreement["id"])
        return agreement

    def test_execute_rejected_when_pinned_table_retired(
        self, api, gift_officer_headers, compliance_headers, gift_admin_headers
    ):
        """PRD §2.7: "Retiring a table does not disturb agreements already
        pinning it, but execution re-validates the pin: at execute time the
        pinned table must still be `ACTIVE` and its window must still cover the
        agreement's `funding_month`, or the execution is rejected with
        `ERR_RATE_TABLE_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/agreement_execution_requires_active_rate_table
        """
        agreement = self._setup_booked_then_retired(
            api, gift_officer_headers, compliance_headers
        )
        resp = api.execute_gift_agreement(agreement["id"], gift_admin_headers)
        validate_error(resp, ApiErrorId.ERR_RATE_TABLE_NOT_ACTIVE)
        assert resp.status_code == 409

    def test_rejected_execute_leaves_agreement_draft(
        self, api, gift_officer_headers, compliance_headers, gift_admin_headers
    ):
        """PRD §2.7: "Retiring a table does not disturb agreements already
        pinning it, but execution re-validates the pin: at execute time the
        pinned table must still be `ACTIVE` and its window must still cover the
        agreement's `funding_month`, or the execution is rejected with
        `ERR_RATE_TABLE_NOT_ACTIVE`."
        PRD §3.3: execution is "performed by a `GiftAdministrator` on a `DRAFT`
        agreement" — a rejected execution leaves the DRAFT in place.

        Design: Difficulty/cross_entity_state_dependency/agreement_execution_requires_active_rate_table
        """
        agreement = self._setup_booked_then_retired(
            api, gift_officer_headers, compliance_headers
        )
        resp = api.execute_gift_agreement(agreement["id"], gift_admin_headers)
        validate_error(resp, ApiErrorId.ERR_RATE_TABLE_NOT_ACTIVE)
        after = validate_success(api.get_gift_agreement(agreement["id"], gift_admin_headers))
        assert after["status"] == "DRAFT"
        # The booked economics would otherwise have passed (deduction 3768895
        # clears the ten-percent floor), isolating the rate-table dependency.
        assert after["booked_deduction_cents"] is None


class TestSafetyBeatsRateTableTemporal:
    def _setup_failing_remainder_with_retired_table(
        self, api, gift_officer_headers, compliance_headers
    ):
        """Joint-life (60/60) CRT_ANNUITY at 5000bps: the booked deduction
        floors at 0, failing the ten-percent remainder test; the pinned table
        is then retired so the rate-coverage gate would also fail."""
        donor = make_donor(full_name="Prio SafetyTemporal", date_of_birth="1966-03-01T00:00:00Z")
        table = make_active_rate_table(
            label="7520-5pct-2026",
            effective_from="2026-01-01T00:00:00Z",
            effective_to="2026-12-01T00:00:00Z",
        )
        illustration = make_illustration(
            donor["id"],
            vehicle_type="CRT_ANNUITY",
            gift_amount_cents=10000000,
            payout_rate_bps=5000,
            payment_frequency="ANNUAL",
            lives=2,
            annuitant_1_age=60,
            annuitant_2_age=60,
            funding_month="2026-08",
            creator_headers=gift_officer_headers,
        )
        agreement = validate_success(
            api.book_illustration(illustration["id"], gift_officer_headers), 201
        )
        validate_success(
            api.transition_rate_table(table["id"], {"action": "RETIRE"}, compliance_headers)
        )
        make_verified_designation(agreement["id"])
        return agreement

    def test_remainder_test_reported_over_rate_table_failure(
        self, api, gift_officer_headers, compliance_headers, gift_admin_headers
    ):
        """PRD §2.10: "Every request is validated against an ordered chain of
        checks, and the **first** failure wins — a request that would fail two
        checks receives the error of the earlier one." The global order lists
        "8. The regulatory remainder test — `ERR_REMAINDER_TEST_FAILED`" ahead
        of "18. Rate-table coverage of the funding month —
        `ERR_RATE_TABLE_NOT_ACTIVE`."

        Design: Difficulty/priority_pair_validation_conflict/execute_safety_beats_rate_table_temporal
        """
        agreement = self._setup_failing_remainder_with_retired_table(
            api, gift_officer_headers, compliance_headers
        )
        resp = api.execute_gift_agreement(agreement["id"], gift_admin_headers)
        validate_error(resp, ApiErrorId.ERR_REMAINDER_TEST_FAILED)
        assert resp.status_code == 422

    def test_failed_execute_leaves_agreement_draft(
        self, api, gift_officer_headers, compliance_headers, gift_admin_headers
    ):
        """PRD §2.10: "Every request is validated against an ordered chain of
        checks, and the **first** failure wins — a request that would fail two
        checks receives the error of the earlier one."
        PRD §3.3: "the regulatory remainder test for annuity vehicles — the
        booked deduction multiplied by ten must be at least the gift principal,
        an inclusive ten-percent floor, else `ERR_REMAINDER_TEST_FAILED`
        (HTTP 422)".

        Design: Difficulty/priority_pair_validation_conflict/execute_safety_beats_rate_table_temporal
        """
        agreement = self._setup_failing_remainder_with_retired_table(
            api, gift_officer_headers, compliance_headers
        )
        resp = api.execute_gift_agreement(agreement["id"], gift_admin_headers)
        validate_error(resp, ApiErrorId.ERR_REMAINDER_TEST_FAILED)
        after = validate_success(api.get_gift_agreement(agreement["id"], gift_admin_headers))
        assert after["status"] == "DRAFT"


class TestStateBeatsReserveFiscal:
    def _setup_deficient_pool_with_executed_cga(self, api, gift_admin_headers, estate_manager_headers):
        """Two EXECUTED CGAs (requirement 7570148 each) against a pool that is
        then drawn down into RESERVE_DEFICIENT posture. Returns
        (cga2_id, posture_after_drawdown)."""
        donor = make_donor(full_name="Prio StateFiscal")
        make_active_rate_table()
        contribute_reserve(2 * STD_CGA_RESERVE_REQUIREMENT_CENTS)
        cga1 = make_draft_agreement(donor["id"], vehicle_type="CGA", payout_rate_bps=600)
        make_verified_designation(cga1["id"])
        validate_success(api.execute_gift_agreement(cga1["id"], gift_admin_headers))
        asset = validate_success(
            api.create_gift_asset(
                create_gift_asset_payload(
                    gift_agreement_id=cga1["id"],
                    asset_kind="CASH",
                    pledged_value_cents=10000000,
                ),
                estate_manager_headers,
            ),
            201,
        )
        validate_success(
            api.transition_gift_asset(asset["id"], {"action": "RECEIVE"}, estate_manager_headers)
        )
        cga2 = make_draft_agreement(donor["id"], vehicle_type="CGA", payout_rate_bps=600)
        make_verified_designation(cga2["id"])
        validate_success(api.execute_gift_agreement(cga2["id"], gift_admin_headers))
        # Draw the pool down so booked coverage floors below 10000 bps.
        pool = withdraw_reserve(9084790)
        return cga2["id"], pool["posture"]

    def test_reexecute_returns_invalid_state_not_reserve_deficient(
        self, api, gift_admin_headers, estate_manager_headers, compliance_headers
    ):
        """PRD §2.10: "Every request is validated against an ordered chain of
        checks, and the **first** failure wins — a request that would fail two
        checks receives the error of the earlier one." The global order lists
        "6. State-machine legality for the requested transition or action —
        `ERR_INVALID_STATE`" ahead of "25. The CGA reserve gate at execution —
        `ERR_RESERVE_DEFICIENT`."

        Design: Difficulty/priority_pair_validation_conflict/execute_state_beats_reserve_fiscal
        """
        cga2_id, posture = self._setup_deficient_pool_with_executed_cga(
            api, gift_admin_headers, estate_manager_headers
        )
        assert posture == "RESERVE_DEFICIENT"
        # CGA-2 is already EXECUTED; re-executing violates the state machine,
        # and that earlier-priority failure masks the reserve deficiency the
        # same request would also trigger.
        resp = api.execute_gift_agreement(cga2_id, gift_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409

    def test_reexecute_rejection_leaves_agreement_executed(
        self, api, gift_admin_headers, estate_manager_headers, compliance_headers
    ):
        """PRD §2.10: "Every request is validated against an ordered chain of
        checks, and the **first** failure wins — a request that would fail two
        checks receives the error of the earlier one."
        PRD §3.3: execution moves a DRAFT agreement to EXECUTED; a rejected
        transition changes nothing.

        Design: Difficulty/priority_pair_validation_conflict/execute_state_beats_reserve_fiscal
        """
        cga2_id, posture = self._setup_deficient_pool_with_executed_cga(
            api, gift_admin_headers, estate_manager_headers
        )
        assert posture == "RESERVE_DEFICIENT"
        resp = api.execute_gift_agreement(cga2_id, gift_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_gift_agreement(cga2_id, gift_admin_headers))
        assert after["status"] == "EXECUTED"
