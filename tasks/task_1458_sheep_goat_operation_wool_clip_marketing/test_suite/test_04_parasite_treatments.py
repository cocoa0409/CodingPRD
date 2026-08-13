"""Parasite treatments: efficacy, resistance threshold, withdrawal gate."""
from test_helpers import (
    ApiErrorId,
    create_flock,
    create_treatment,
    set_clock,
    validate_error,
    validate_success,
)


class TestTreatmentEfficacy:

    def test_treatment_efficacy_and_resistance_threshold(self, api, range_hand_headers, ranch_manager_headers):
        """PRD §3.2: "The system then computes `efficacy_pct` as the reduction
        from `fecal_egg_count_before` to `fecal_egg_count_after`, divided by
        `fecal_egg_count_before`, multiplied by 100 and rounded half-up to one
        decimal place".
        PRD §3.2: "A `resistance_flag` is set to true exactly when
        `efficacy_pct` is not null and is strictly below 80.0 — an efficacy of
        exactly 80.0 leaves the flag false."
        PRD §3.2: "recomputes the flock's `withdrawal_until` as the latest
        `withdrawal_until` among the flock's treatments whose withdrawal moment
        is strictly after the logical clock".

        Design: Corner/calculations/treatment_efficacy_and_resistance_threshold
        """
        flock = create_flock(flock_name="Epg Ranch", species="SHEEP", baseline_headcount=500)
        tr_a = create_treatment(flock["id"], product_name="Moxidectin",
                                treatment_date="2026-08-05T00:00:00Z", withdrawal_days=7,
                                fecal_egg_count_before=500)
        tr_b = create_treatment(flock["id"], product_name="Levamisole",
                                treatment_date="2026-08-06T00:00:00Z", withdrawal_days=10,
                                fecal_egg_count_before=200)
        # Clock at startup default 2026-08-01: both withdrawals (08-12, 08-16) live.
        resp = api.post_treatment_follow_up(tr_a["id"], {"fecal_egg_count_after": 60}, range_hand_headers)
        tr_a = validate_success(resp)
        assert tr_a["efficacy_pct"] == 88.0, "(500-60)/500*100 == 88.0"
        assert tr_a["resistance_flag"] is False, "88.0 is not strictly below 80.0"

        resp = api.post_treatment_follow_up(tr_b["id"], {"fecal_egg_count_after": 50}, range_hand_headers)
        tr_b = validate_success(resp)
        assert tr_b["efficacy_pct"] == 75.0, "(200-50)/200*100 == 75.0"
        assert tr_b["resistance_flag"] is True, "75.0 is strictly below 80.0"

        flock = validate_success(api.get_flock(flock["id"], ranch_manager_headers))
        assert flock["withdrawal_until"] == "2026-08-16T00:00:00Z", (
            "max of 08-05+7d == 08-12 and 08-06+10d == 08-16"
        )

    def test_treatment_efficacy_zero_baseline_null(self, api, range_hand_headers):
        """PRD §3.2: "when `fecal_egg_count_before` is zero the efficacy is null
        rather than computed."
        PRD §3.2: "A `resistance_flag` is set to true exactly when
        `efficacy_pct` is not null and is strictly below 80.0".

        Design: Corner/calculations/treatment_efficacy_zero_baseline_null
        """
        flock = create_flock(flock_name="ZeroEpg Ranch", species="SHEEP", baseline_headcount=500)
        tr = create_treatment(flock["id"], product_name="Moxidectin",
                              treatment_date="2026-08-05T00:00:00Z", withdrawal_days=7,
                              fecal_egg_count_before=0)
        resp = api.post_treatment_follow_up(tr["id"], {"fecal_egg_count_after": 0}, range_hand_headers)
        tr = validate_success(resp)
        assert tr["efficacy_pct"] is None, "zero baseline -> null efficacy, not 0 and not an error"
        assert tr["resistance_flag"] is False


class TestWithdrawalGate:

    def test_withdrawal_date_equality_allows_meat_sale(self, api, ranch_manager_headers):
        """PRD §3.6: "when the flock's `withdrawal_until` (§3.2) is set, the
        `scheduled_date` must fall on or after it — a sale scheduled on the
        exact withdrawal expiry moment is allowed, and anything earlier is
        rejected with `ERR_WITHDRAWAL_ACTIVE` (HTTP 422)."
        PRD §3.2: "The system computes the treatment's `withdrawal_until` as
        `treatment_date` plus `withdrawal_days` calendar days".

        Design: Difficulty/boundary_precision_check/withdrawal_date_equality_allows_meat_sale
        """
        flock = create_flock(flock_name="Withdrawal Ranch", species="SHEEP", baseline_headcount=500)
        tr = create_treatment(flock["id"], product_name="Cydectin",
                              treatment_date="2026-08-10T00:00:00Z", withdrawal_days=14,
                              fecal_egg_count_before=250)
        assert tr["withdrawal_until"] == "2026-08-24T00:00:00Z"
        set_clock("2026-08-13T00:00:00Z")

        # Control: one day earlier than the expiry -> rejected.
        resp = api.create_livestock_sale({
            "flock_id": flock["id"], "sale_type": "MEAT", "channel": "DIRECT",
            "head_count": 10, "avg_weight_lbs": 100.0, "base_price_per_cwt_cents": 20000,
            "scheduled_date": "2026-08-23T00:00:00Z",
        }, ranch_manager_headers)
        validate_error(resp, ApiErrorId.ERR_WITHDRAWAL_ACTIVE.value, expected_status=422)

        # Boundary: scheduled exactly at withdrawal_until -> allowed.
        resp = api.create_livestock_sale({
            "flock_id": flock["id"], "sale_type": "MEAT", "channel": "DIRECT",
            "head_count": 10, "avg_weight_lbs": 100.0, "base_price_per_cwt_cents": 20000,
            "scheduled_date": "2026-08-24T00:00:00Z",
        }, ranch_manager_headers)
        sale = validate_success(resp, expected_status=201)
        # gross = 10 * 100.0 * 1 (DIRECT shrink default 0) * 20000 / 100 = 200000
        assert sale["booked_price_cents"] == 200000

    def test_withdrawal_one_second_before_rejected(self, api, ranch_manager_headers):
        """PRD §3.6: "when the flock's `withdrawal_until` (§3.2) is set, the
        `scheduled_date` must fall on or after it — a sale scheduled on the
        exact withdrawal expiry moment is allowed, and anything earlier is
        rejected with `ERR_WITHDRAWAL_ACTIVE` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/withdrawal_date_equality_allows_meat_sale
        """
        flock = create_flock(flock_name="Withdrawal2 Ranch", species="SHEEP", baseline_headcount=500)
        create_treatment(flock["id"], product_name="Cydectin",
                         treatment_date="2026-08-10T00:00:00Z", withdrawal_days=14,
                         fecal_egg_count_before=250)
        set_clock("2026-08-13T00:00:00Z")
        resp = api.create_livestock_sale({
            "flock_id": flock["id"], "sale_type": "MEAT", "channel": "DIRECT",
            "head_count": 5, "avg_weight_lbs": 100.0, "base_price_per_cwt_cents": 20000,
            "scheduled_date": "2026-08-23T23:59:59Z",
        }, ranch_manager_headers)
        validate_error(resp, ApiErrorId.ERR_WITHDRAWAL_ACTIVE.value, expected_status=422)

    def test_meat_sale_gated_by_flock_withdrawal(self, api, ranch_manager_headers):
        """PRD §3.6: "One safety gate stands in front of every `MEAT` booking:
        when the flock's `withdrawal_until` (§3.2) is set, the
        `scheduled_date` must fall on or after it — a sale scheduled on the
        exact withdrawal expiry moment is allowed, and anything earlier is
        rejected with `ERR_WITHDRAWAL_ACTIVE` (HTTP 422)."
        PRD §3.6: "a `sale_type` of `MEAT` or `BREEDING`" — the gate is stated
        for MEAT bookings only; BREEDING bookings carry no meat-withdrawal gate.

        Design: Difficulty/cross_entity_state_dependency/meat_sale_gated_by_flock_withdrawal
        """
        flock = create_flock(flock_name="Gate Ranch", species="SHEEP", baseline_headcount=500)
        create_treatment(flock["id"], product_name="Valbazen",
                         treatment_date="2026-08-10T00:00:00Z", withdrawal_days=14,
                         fecal_egg_count_before=100)
        set_clock("2026-08-13T00:00:00Z")

        resp = api.create_livestock_sale({
            "flock_id": flock["id"], "sale_type": "MEAT", "channel": "DIRECT",
            "head_count": 20, "avg_weight_lbs": 110.0, "base_price_per_cwt_cents": 21000,
            "scheduled_date": "2026-08-20T00:00:00Z",
        }, ranch_manager_headers)
        validate_error(resp, ApiErrorId.ERR_WITHDRAWAL_ACTIVE.value, expected_status=422)

        # Same date, BREEDING: the withdrawal gate does not apply to breeding sales.
        resp = api.create_livestock_sale({
            "flock_id": flock["id"], "sale_type": "BREEDING", "channel": "DIRECT",
            "head_count": 5, "per_head_price_cents": 60000,
            "scheduled_date": "2026-08-20T00:00:00Z",
        }, ranch_manager_headers)
        sale = validate_success(resp, expected_status=201)
        assert sale["booked_price_cents"] == 300000, "BREEDING booked == head_count * per_head_price_cents"

    def test_meat_sale_inside_withdrawal_rejected_while_outside_allowed(self, api, ranch_manager_headers):
        """PRD §3.6: "when the flock's `withdrawal_until` (§3.2) is set, the
        `scheduled_date` must fall on or after it — a sale scheduled on the
        exact withdrawal expiry moment is allowed, and anything earlier is
        rejected with `ERR_WITHDRAWAL_ACTIVE` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/meat_sale_gated_by_flock_withdrawal
        """
        flock = create_flock(flock_name="Gate4 Ranch", species="SHEEP", baseline_headcount=500)
        create_treatment(flock["id"], product_name="Valbazen",
                         treatment_date="2026-08-10T00:00:00Z", withdrawal_days=14,
                         fecal_egg_count_before=100)
        set_clock("2026-08-13T00:00:00Z")
        resp = api.create_livestock_sale({
            "flock_id": flock["id"], "sale_type": "MEAT", "channel": "AUCTION",
            "head_count": 20, "avg_weight_lbs": 110.0, "base_price_per_cwt_cents": 21000,
            "scheduled_date": "2026-08-20T00:00:00Z",
        }, ranch_manager_headers)
        validate_error(resp, ApiErrorId.ERR_WITHDRAWAL_ACTIVE.value, expected_status=422)
        resp = api.create_livestock_sale({
            "flock_id": flock["id"], "sale_type": "MEAT", "channel": "AUCTION",
            "head_count": 20, "avg_weight_lbs": 110.0, "base_price_per_cwt_cents": 21000,
            "scheduled_date": "2026-08-25T00:00:00Z",
        }, ranch_manager_headers)
        validate_success(resp, expected_status=201)
