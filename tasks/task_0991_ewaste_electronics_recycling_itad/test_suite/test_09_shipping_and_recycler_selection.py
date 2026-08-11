"""Batch shipping guards (empty, terminal, export ban, daily capacity,
certification validity window) and the recycler selector policy
(PRD §3.2, §3.7)."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_to_batch,
    deliver_batch,
    new_active_policy,
    new_batch,
    new_recycler,
    process_batch,
    scan_and_triage,
    set_clock,
    setup_received_manifest,
    ship_batch,
    validate_error,
    validate_success,
)

DELIVERY = "2026-06-10T00:00:00Z"


class TestShipGuards:
    def test_ship_empty_batch_rejected(self, api, logistics_coordinator_headers):
        """PRD §3.7: "and the batch must contain at least one item (`ERR_BATCH_EMPTY`)."

        Design: Corner/errors/ship_empty_batch_rejected
        """
        recycler = new_recycler(accepted_categories=["OTHER"], daily_intake_capacity_kg=1000)
        batch = new_batch(recycler_id=recycler["id"], scheduled_delivery_date=DELIVERY)

        resp = api.ship_batch(batch["id"], logistics_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_BATCH_EMPTY)
        assert resp.status_code == 422

    def test_ship_processed_batch_rejected(self, api, logistics_coordinator_headers):
        """PRD §3.7: "`PROCESSED` is terminal for the batch."
        PRD §2.6: "7. Generic transition state preconditions — the target resource is not in the state the transition starts from, or is in a terminal state, yielding `ERR_INVALID_STATE`."

        Design: Corner/state_machines/ship_processed_batch_returns_409
        """
        recycler = new_recycler(accepted_categories=["OTHER"], daily_intake_capacity_kg=1000)
        _account, manifest = setup_received_manifest(declared_item_count=1)
        item = scan_and_triage(manifest["id"], "RECYCLE", serial_number="SN-T1",
                               category="OTHER", weight_kg=3.0, declared_grade="D")
        batch = new_batch(recycler_id=recycler["id"], scheduled_delivery_date=DELIVERY)
        batch = add_to_batch(batch["id"], item["id"])
        ship_batch(batch["id"])
        deliver_batch(batch["id"])
        process_batch(batch["id"])

        resp = api.ship_batch(batch["id"], logistics_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409


class TestExportBan:
    def _estewards_policy_and_recycler(self):
        new_active_policy(standard="E_STEWARDS",
                          sanitization_methods_allowed=["NIST_PURGE", "PHYSICAL_DESTROY"],
                          export_allowed=False,
                          weight_cert_freshness=0.3, weight_volume=0.2,
                          weight_violations=0.5)
        return new_recycler(certification_standard="E_STEWARDS",
                            accepted_categories=["OTHER"], daily_intake_capacity_kg=1000)

    def test_export_batch_rejected_under_export_ban(self, api, logistics_coordinator_headers):
        """PRD §3.7: "Two policy gates run at creation, after body validation and before the temporal certification check: an export shipment while the active policy's `export_allowed` is false is rejected with `ERR_EXPORT_NOT_ALLOWED`, and — when no `recycler_id` was supplied — an empty selector pool is rejected with `ERR_NO_ELIGIBLE_RECYCLER`."

        Design: Corner/validations/export_ban_rejects_export_batch
        """
        recycler = self._estewards_policy_and_recycler()
        resp = api.create_recycle_batch(
            {"recycler_id": recycler["id"], "scheduled_delivery_date": DELIVERY,
             "is_export": True},
            logistics_coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_EXPORT_NOT_ALLOWED)
        assert resp.status_code == 422

    def test_domestic_batch_allowed_under_export_ban(self, api, logistics_coordinator_headers):
        """PRD §3.7: "Two policy gates run at creation, after body validation and before the temporal certification check: an export shipment while the active policy's `export_allowed` is false is rejected with `ERR_EXPORT_NOT_ALLOWED`, and — when no `recycler_id` was supplied — an empty selector pool is rejected with `ERR_NO_ELIGIBLE_RECYCLER`."

        Design: Corner/validations/export_ban_rejects_export_batch
        """
        recycler = self._estewards_policy_and_recycler()
        batch = new_batch(recycler_id=recycler["id"], scheduled_delivery_date=DELIVERY,
                          is_export=False)
        assert batch["status"] == "STAGING"
        assert batch["recycler_id"] == recycler["id"]


class TestDailyCapacityBoundary:
    def _setup_capacity_scenario(self, api):
        """Recycler capacity 100.0; batch A holds 60.0 kg (shipped), batch B
        holds 40.0 kg, batch C holds 0.001 kg — all delivering the same day."""
        recycler = new_recycler(accepted_categories=["OTHER"], daily_intake_capacity_kg=100.0)
        batches = {}
        for key, serial, weight, start, end in (
            ("A", "SN-CA", 60.0, "2026-06-01T09:00:00Z", "2026-06-01T10:00:00Z"),
            ("B", "SN-CB", 40.0, "2026-06-01T10:00:00Z", "2026-06-01T11:00:00Z"),
            ("C", "SN-CC", 0.001, "2026-06-01T11:00:00Z", "2026-06-01T12:00:00Z"),
        ):
            _account, manifest = setup_received_manifest(
                declared_item_count=1, scheduled_start=start, scheduled_end=end,
            )
            item = scan_and_triage(manifest["id"], "RECYCLE", serial_number=serial,
                                   category="OTHER", weight_kg=weight, declared_grade="D")
            batch = new_batch(recycler_id=recycler["id"], scheduled_delivery_date=DELIVERY)
            batches[key] = add_to_batch(batch["id"], item["id"])
        ship_batch(batches["A"]["id"])
        return recycler, batches

    def test_daily_capacity_exact_fit_allowed(self, api, logistics_coordinator_headers):
        """PRD §3.7: "the recycler's daily intake must absorb the load — the sum of `gross_weight_kg` over this recycler's batches in `IN_TRANSIT`, `DELIVERED`, or `PROCESSED` sharing the same calendar delivery day, plus this batch's own gross weight, must not exceed `daily_intake_capacity_kg`, with an exact fit allowed and only a strictly-greater overflow rejected with `ERR_RECYCLER_DAILY_CAPACITY_EXCEEDED`"

        Design: Difficulty/boundary_precision_check/recycler_daily_capacity_exact_fit_then_overflow
        """
        _recycler, batches = self._setup_capacity_scenario(api)
        # 60.0 already in transit; 60.0 + 40.0 == 100.0 exactly equals capacity.
        data = validate_success(api.ship_batch(batches["B"]["id"], logistics_coordinator_headers))
        assert data["status"] == "IN_TRANSIT"

    def test_daily_capacity_overflow_by_one_gram_rejected(self, api,
                                                          logistics_coordinator_headers):
        """PRD §3.7: "the recycler's daily intake must absorb the load — the sum of `gross_weight_kg` over this recycler's batches in `IN_TRANSIT`, `DELIVERED`, or `PROCESSED` sharing the same calendar delivery day, plus this batch's own gross weight, must not exceed `daily_intake_capacity_kg`, with an exact fit allowed and only a strictly-greater overflow rejected with `ERR_RECYCLER_DAILY_CAPACITY_EXCEEDED`"

        Design: Difficulty/boundary_precision_check/recycler_daily_capacity_exact_fit_then_overflow
        """
        _recycler, batches = self._setup_capacity_scenario(api)
        validate_success(api.ship_batch(batches["B"]["id"], logistics_coordinator_headers))
        # 100.0 already committed; +0.001 kg overflows strictly above capacity.
        resp = api.ship_batch(batches["C"]["id"], logistics_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_RECYCLER_DAILY_CAPACITY_EXCEEDED)
        assert resp.status_code == 422


class TestCertificationValidityWindow:
    def _expiring_recycler(self):
        return new_recycler(name="RecX", certification_standard="E_STEWARDS",
                            certification_expires_at="2026-06-01T00:00:00Z",
                            accepted_categories=["OTHER"], daily_intake_capacity_kg=1000)

    def test_delivery_before_expiry_accepted(self, api, logistics_coordinator_headers):
        """PRD §3.7: "Whether nominated or selected, the recycler's `certification_expires_at` must be strictly after the scheduled delivery date — the expiry instant itself is already too late — and a lapsed certification is rejected with `ERR_RECYCLER_CERT_EXPIRED`."

        Design: Difficulty/resource_temporal_overlap/delivery_date_outside_cert_validity_window
        """
        recycler = self._expiring_recycler()
        batch = new_batch(recycler_id=recycler["id"],
                          scheduled_delivery_date="2026-05-31T00:00:00Z", is_export=False)
        assert batch["status"] == "STAGING"

    def test_delivery_at_expiry_instant_rejected(self, api, logistics_coordinator_headers):
        """PRD §3.7: "Whether nominated or selected, the recycler's `certification_expires_at` must be strictly after the scheduled delivery date — the expiry instant itself is already too late — and a lapsed certification is rejected with `ERR_RECYCLER_CERT_EXPIRED`."

        Design: Difficulty/resource_temporal_overlap/delivery_date_outside_cert_validity_window
        """
        recycler = self._expiring_recycler()
        resp = api.create_recycle_batch(
            {"recycler_id": recycler["id"], "scheduled_delivery_date": "2026-06-01T00:00:00Z",
             "is_export": False},
            logistics_coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_RECYCLER_CERT_EXPIRED)
        assert resp.status_code == 422


class TestSelectorPolicy:
    def test_selector_empty_pool_rejected(self, api, logistics_coordinator_headers):
        """PRD §3.2: "When a batch is created without an explicit recycler, the selector policy chooses among the eligible recyclers — those whose `certification_expires_at` is strictly after the requested delivery date, expiry being exclusive — ranks them by `risk_score` descending, breaks ties by `total_processed_kg` descending and then by `created_at` ascending (never by identifier), and assigns the winner. If no recycler's certification is strictly valid on the requested date, creation fails with `ERR_NO_ELIGIBLE_RECYCLER`."

        Design: Corner/calculations/selector_empty_pool_returns_no_eligible
        """
        new_active_policy(sanitization_methods_allowed=["NIST_CLEAR"])
        # The only recycler's certification lapses before the requested date.
        new_recycler(name="RecOld", certification_expires_at="2026-06-01T00:00:00Z",
                     accepted_categories=["OTHER"], daily_intake_capacity_kg=1000)

        resp = api.create_recycle_batch(
            {"scheduled_delivery_date": DELIVERY, "is_export": False},
            logistics_coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_RECYCLER)
        assert resp.status_code == 422

    def test_selector_tie_break_created_at_ascending(self, api, logistics_coordinator_headers):
        """PRD §3.2: "ranks them by `risk_score` descending, breaks ties by `total_processed_kg` descending and then by `created_at` ascending (never by identifier), and assigns the winner."

        Design: Corner/calculations/selector_tie_break_created_at
        """
        new_active_policy(sanitization_methods_allowed=["NIST_CLEAR"])
        first = new_recycler(name="RecFirst", accepted_categories=["OTHER"],
                             daily_intake_capacity_kg=1000)
        # Distinct created_at so the tie-break ordering is deterministic.
        set_clock("2026-05-01T01:00:00Z")
        new_recycler(name="RecSecond", accepted_categories=["OTHER"],
                     daily_intake_capacity_kg=1000)

        batch = new_batch(scheduled_delivery_date=DELIVERY, is_export=False)
        assert batch["recycler_id"] == first["id"]


class TestRiskScorePolicyWeights:
    def _setup_two_recyclers(self):
        """Recycler A: 365 days of cert remaining, 4 violations, no volume.
        Recycler B: 184 days of cert remaining, 0 violations, no volume."""
        rec_a = new_recycler(name="RecA", certification_expires_at="2027-05-01T00:00:00Z",
                             accepted_categories=["LAPTOP", "SERVER"],
                             daily_intake_capacity_kg=100000, violation_count=4)
        rec_b = new_recycler(name="RecB", certification_expires_at="2026-11-01T00:00:00Z",
                             accepted_categories=["LAPTOP"], daily_intake_capacity_kg=100000,
                             violation_count=0)
        return rec_a, rec_b

    def test_risk_scores_rerank_under_policy_weights(self, api, compliance_officer_headers):
        """PRD §3.2: "The weighted sum of the three components — using `weight_cert_freshness`, `weight_volume`, and `weight_violations` from the active policy — is multiplied by 100 and rounded half-up to two decimal places to produce the `risk_score`."
        PRD §3.2: "an R2-style weighting such as 0.5, 0.2, and 0.3 lets certification freshness dominate, while an e-Stewards-style weighting such as 0.3, 0.2, and 0.5 lets the violation-free record dominate, and identical recycler statistics can produce a different winner under the two regimes."

        Design: Difficulty/dual_variant_calc/recycler_score_weights_flip_selector_winner
        """
        new_active_policy(standard="R2", weight_cert_freshness=0.5, weight_volume=0.2,
                          weight_violations=0.3)
        rec_a, rec_b = self._setup_two_recyclers()

        a_r2 = validate_success(api.get_recycler(rec_a["id"], compliance_officer_headers))
        b_r2 = validate_success(api.get_recycler(rec_b["id"], compliance_officer_headers))
        # R2 weights: A = 100 x (0.5 x 1.0 + 0.2 x 0 + 0.3 x 0.6) = 68.0.
        assert a_r2["risk_score"] == pytest.approx(68.0, abs=0.005)
        # B freshness = 184/365: 100 x (0.5 x 184/365 + 0.3 x 1.0) = 55.21.
        assert b_r2["risk_score"] == pytest.approx(55.21, abs=0.005)

        new_active_policy(standard="E_STEWARDS",
                          sanitization_methods_allowed=["NIST_PURGE", "PHYSICAL_DESTROY"],
                          export_allowed=False, weight_cert_freshness=0.3,
                          weight_volume=0.2, weight_violations=0.5)
        a_es = validate_success(api.get_recycler(rec_a["id"], compliance_officer_headers))
        b_es = validate_success(api.get_recycler(rec_b["id"], compliance_officer_headers))
        # E_STEWARDS weights: A = 100 x (0.3 + 0.5 x 0.6) = 60.0.
        assert a_es["risk_score"] == pytest.approx(60.0, abs=0.005)
        # B = 100 x (0.3 x 184/365 + 0.5 x 1.0) = 65.12.
        assert b_es["risk_score"] == pytest.approx(65.12, abs=0.005)

    def test_selector_winner_flips_with_policy_weights(self, api, logistics_coordinator_headers):
        """PRD §3.2: "ranks them by `risk_score` descending, breaks ties by `total_processed_kg` descending and then by `created_at` ascending (never by identifier), and assigns the winner."
        PRD §3.2: "an R2-style weighting such as 0.5, 0.2, and 0.3 lets certification freshness dominate, while an e-Stewards-style weighting such as 0.3, 0.2, and 0.5 lets the violation-free record dominate, and identical recycler statistics can produce a different winner under the two regimes."

        Design: Difficulty/dual_variant_calc/recycler_score_weights_flip_selector_winner
        """
        new_active_policy(standard="R2", weight_cert_freshness=0.5, weight_volume=0.2,
                          weight_violations=0.3)
        rec_a, rec_b = self._setup_two_recyclers()

        batch_one = new_batch(scheduled_delivery_date=DELIVERY, is_export=False)
        assert batch_one["recycler_id"] == rec_a["id"]

        new_active_policy(standard="E_STEWARDS",
                          sanitization_methods_allowed=["NIST_PURGE", "PHYSICAL_DESTROY"],
                          export_allowed=False, weight_cert_freshness=0.3,
                          weight_volume=0.2, weight_violations=0.5)
        batch_two = new_batch(scheduled_delivery_date=DELIVERY, is_export=False)
        assert batch_two["recycler_id"] == rec_b["id"]
