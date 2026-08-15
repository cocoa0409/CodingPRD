"""Estimate lifecycle: state gates, terminal lockdown, OCC, logical clock,
expiry-vs-credit priority, and the exposure equality boundary."""
from datetime import datetime, timezone

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_estimate,
    create_customer,
    create_estimate,
    create_stock,
    get_success_data,
    make_customer_headers,
    minimal_signature,
    quote_estimate,
    set_clock_payload,
    validate_error,
    validate_success,
)


def _instant(ts: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp to an instant, accepting any fractional
    precision (PRD pins the instant, not the string formatting of quoted_at /
    expires_at)."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)


def _quoted_estimate(cust, stock, **kwargs):
    est = create_estimate(cust["id"], minimal_signature(stock["id"]), **kwargs)
    quote_estimate(est["id"])
    return est


class TestEstimateStateGates:
    def test_estimate_accept_from_draft_returns_invalid_state(self, api):
        """PRD §3.3: "A `Customer` accepts a `QUOTED` estimate." — accept is
        undefined from DRAFT; PRD §2.7: "State-machine validity follows, where
        the target entity must be in the required state for the operation."

        Design: Corner/state_machines/estimate_accept_from_draft_returns_invalid_state
        """
        cust = create_customer(name="D Cust")
        stock = create_stock(name="70U", grade="UNCOATED", cost_per_sheet_cents=5)
        est = create_estimate(cust["id"], minimal_signature(stock["id"]),
                              quantity_ordered=100, job_name="DJ")
        resp = api.accept_estimate(est["id"], make_customer_headers(cust["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        est_after = get_success_data(api.get_estimate(est["id"], TEST_USERS["estimator_headers"]))
        assert est_after["status"] == "DRAFT"

    def test_estimate_terminal_decline_lockdown(self, api, estimator_headers):
        """PRD §3.3: "Both `DECLINED` and `EXPIRED` are terminal, as is
        `ACCEPTED`." From DECLINED, quote and accept are both rejected.

        Design: Corner/state_machines/estimate_terminal_decline_lockdown
        """
        cust = create_customer(name="T Cust")
        stock = create_stock(name="70U", grade="UNCOATED", cost_per_sheet_cents=5)
        est = _quoted_estimate(cust, stock, quantity_ordered=100, job_name="TJ")
        api.decline_estimate(est["id"], make_customer_headers(cust["id"]))
        r1 = api.quote_estimate(est["id"], estimator_headers)
        validate_error(r1, ApiErrorId.ERR_INVALID_STATE)
        r2 = api.accept_estimate(est["id"], make_customer_headers(cust["id"]))
        validate_error(r2, ApiErrorId.ERR_INVALID_STATE)
        est_after = get_success_data(api.get_estimate(est["id"], estimator_headers))
        assert est_after["status"] == "DECLINED"

    def test_estimate_revise_after_quote_rejected(self, api, estimator_headers):
        """PRD §3.2: "An `Estimator` revises a `DRAFT` estimate with an
        optimistic-concurrency guard." — PUT is only valid from DRAFT, so a
        QUOTED estimate rejects revision even with the correct version.

        Design: Corner/state_machines/estimate_revise_after_quote_rejected
        """
        cust = create_customer(name="R Cust")
        stock = create_stock(name="70U", grade="UNCOATED", cost_per_sheet_cents=5)
        est = create_estimate(cust["id"], minimal_signature(stock["id"]),
                              quantity_ordered=100, job_name="RJ")
        quoted = quote_estimate(est["id"])
        resp = api.revise_estimate(
            est["id"],
            {"expected_estimate_version": quoted["version"], "quantity_ordered": 200},
            estimator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestEstimateOCC:
    def test_occ_estimate_revision_stale_version(self, api, estimator_headers):
        """PRD §2.4: "A revision to a `DRAFT` estimate must carry
        `expected_estimate_version` equal to the estimate's current `version`;
        a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_estimate_revision_stale_version
        """
        cust = create_customer(name="OC Cust")
        stock = create_stock(name="70U", grade="UNCOATED", cost_per_sheet_cents=5)
        est = create_estimate(cust["id"], minimal_signature(stock["id"]),
                              quantity_ordered=100, job_name="OJ")
        ev = est["version"]
        r1 = api.revise_estimate(
            est["id"], {"expected_estimate_version": ev, "quantity_ordered": 200},
            estimator_headers,
        )
        data = validate_success(r1, 200)
        assert data["version"] == ev + 1
        assert data["quantity_ordered"] == 200
        r2 = api.revise_estimate(
            est["id"], {"expected_estimate_version": ev, "quantity_ordered": 300},
            estimator_headers,
        )
        validate_error(r2, ApiErrorId.ERR_STALE_VERSION)
        after = get_success_data(api.get_estimate(est["id"], estimator_headers))
        assert after["quantity_ordered"] == 200, "stale write must not be applied"

    def test_occ_estimate_revision_second_replay_rejected(self, api, estimator_headers):
        """PRD §2.4: "the client's view of the parent resource may have
        advanced since it was last read, and the server refuses to let the
        write proceed on a stale basis."

        Design: Corner/cross_cutting_layers/occ_estimate_revision_stale_version
        """
        cust = create_customer(name="OC2 Cust")
        stock = create_stock(name="70U", grade="UNCOATED", cost_per_sheet_cents=5)
        est = create_estimate(cust["id"], minimal_signature(stock["id"]),
                              quantity_ordered=100, job_name="OJ2")
        ok = api.revise_estimate(
            est["id"],
            {"expected_estimate_version": est["version"], "press_spoilage_pct": 5},
            estimator_headers,
        )
        v2 = validate_success(ok, 200)["version"]
        stale = api.revise_estimate(
            est["id"],
            {"expected_estimate_version": est["version"], "press_spoilage_pct": 9},
            estimator_headers,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        after = get_success_data(api.get_estimate(est["id"], estimator_headers))
        assert after["press_spoilage_pct"] == 5
        assert after["version"] == v2


class TestLogicalClock:
    def test_clock_default_and_accept_at_expiry_boundary(self, api, plant_manager_headers):
        """PRD §2.5: "At startup the logical clock is exactly
        `2026-08-01T00:00:00Z`"; PRD §3.2: "`expires_at` is computed as
        `quoted_at` plus `quote_valid_days` days"; PRD §3.3: expiry fires when
        "the current clock is past `expires_at`" — so accept at exactly
        expires_at succeeds. (Timestamps are compared as instants: §2.2/§2.4
        pin three fractional digits for envelope/created_at/updated_at but do
        not pin the string formatting of `quoted_at`/`expires_at`.)

        Design: Corner/endpoints/clock_default_and_set
        """
        cust = create_customer(name="CK")
        stock = create_stock(name="70U", grade="UNCOATED", cost_per_sheet_cents=5)
        est = create_estimate(cust["id"], minimal_signature(stock["id"]),
                              quantity_ordered=100, job_name="CK",
                              quote_valid_days=30, due_date="2026-09-20T00:00:00Z")
        quoted = quote_estimate(est["id"])
        assert _instant(quoted["quoted_at"]) == _instant("2026-08-01T00:00:00Z"), (
            f"default clock must be the 2026-08-01T00:00:00Z instant, got {quoted['quoted_at']}"
        )
        assert _instant(quoted["expires_at"]) == _instant("2026-08-31T00:00:00Z")
        api.set_clock(set_clock_payload("2026-08-31T00:00:00Z"), plant_manager_headers)
        resp = api.accept_estimate(est["id"], make_customer_headers(cust["id"]))
        job = validate_success(resp, 200)
        assert job["id"], "accept at exactly expires_at (<= inclusive) must succeed"

    def test_clock_set_changes_expiry_evaluation(self, api, plant_manager_headers):
        """PRD §2.5: "The clock never falls back to wall-clock time... the
        transition to `EXPIRED` is observed when an accept is attempted after
        `expires_at`."

        Design: Corner/endpoints/clock_default_and_set
        """
        cust = create_customer(name="CK2")
        stock = create_stock(name="70U", grade="UNCOATED", cost_per_sheet_cents=5)
        est = create_estimate(cust["id"], minimal_signature(stock["id"]),
                              quantity_ordered=100, job_name="CK2",
                              quote_valid_days=30, due_date="2026-09-20T00:00:00Z")
        quote_estimate(est["id"])
        api.set_clock(set_clock_payload("2026-09-01T00:00:00Z"), plant_manager_headers)
        resp = api.accept_estimate(est["id"], make_customer_headers(cust["id"]))
        validate_error(resp, ApiErrorId.ERR_ESTIMATE_EXPIRED)


class TestExpiredEstimateBeatsCreditHold:
    def _setup_hold_and_expired(self, api, plant_manager_headers):
        cust = create_customer(name="Low Limit", credit_limit_cents=100)
        stock = create_stock(name="70U", grade="UNCOATED", cost_per_sheet_cents=5)
        e1 = _quoted_estimate(cust, stock, quantity_ordered=1000, job_name="E1")
        e2 = _quoted_estimate(cust, stock, quantity_ordered=1000, job_name="E2")
        accept_estimate(e1["id"], cust["id"])  # exposure 85000 > 100 -> CREDIT_HOLD
        api.set_clock(set_clock_payload("2026-09-01T00:00:00Z"), plant_manager_headers)
        return cust, e2

    def test_expired_estimate_beats_credit_hold(self, api, plant_manager_headers):
        """PRD §3.3: "The server enforces accept-time preconditions in a
        specific order: ownership first... then expiry (if the current clock
        is past `expires_at`, the estimate is transitioned to `EXPIRED` and
        the call fails with `ERR_ESTIMATE_EXPIRED`), then credit posture (the
        customer's `posture` must be `ACTIVE`, else `ERR_CREDIT_HOLD`)."

        Design: Difficulty/priority_pair_validation_conflict/expired_estimate_beats_credit_hold
        """
        cust, e2 = self._setup_hold_and_expired(api, plant_manager_headers)
        resp = api.accept_estimate(e2["id"], make_customer_headers(cust["id"]))
        validate_error(resp, ApiErrorId.ERR_ESTIMATE_EXPIRED)

    def test_expired_estimate_transitions_to_expired_and_posture_unchanged(
        self, api, plant_manager_headers, estimator_headers
    ):
        """PRD §3.3: "the estimate is transitioned to `EXPIRED` and the call
        fails with `ERR_ESTIMATE_EXPIRED`" — and the losing fiscal violation
        (CREDIT_HOLD posture) remains readable afterwards.

        Design: Difficulty/priority_pair_validation_conflict/expired_estimate_beats_credit_hold
        """
        cust, e2 = self._setup_hold_and_expired(api, plant_manager_headers)
        api.accept_estimate(e2["id"], make_customer_headers(cust["id"]))
        est_after = get_success_data(api.get_estimate(e2["id"], estimator_headers))
        assert est_after["status"] == "EXPIRED"
        cust_after = get_success_data(api.get_customer(cust["id"], plant_manager_headers))
        assert cust_after["posture"] == "CREDIT_HOLD"


class TestCreditExposureEqualityBoundary:
    def _setup_limit_customer(self):
        cust = create_customer(name="Eq Cust", credit_limit_cents=85000)
        stock = create_stock(name="70U", grade="UNCOATED", cost_per_sheet_cents=5)
        e1 = _quoted_estimate(cust, stock, quantity_ordered=1000, job_name="E1")
        e2 = _quoted_estimate(cust, stock, quantity_ordered=1000, job_name="E2")
        return cust, e1, e2

    def test_exposure_equal_to_limit_stays_active(self, api, plant_manager_headers):
        """PRD §3.1: "The customer's `posture` is `ACTIVE` when `exposure_cents`
        is less than or equal to `credit_limit_cents`, and flips to
        `CREDIT_HOLD` exactly when exposure strictly exceeds the credit limit
        — equality stays `ACTIVE`."

        Design: Difficulty/boundary_precision_check/credit_exposure_equality_boundary
        """
        cust, e1, _e2 = self._setup_limit_customer()
        accept_estimate(e1["id"], cust["id"])  # exposure 85000 == limit
        after = get_success_data(api.get_customer(cust["id"], plant_manager_headers))
        assert after["exposure_cents"] == 85000
        assert after["posture"] == "ACTIVE", (
            "equality must stay ACTIVE (strictly-greater comparison)"
        )

    def test_one_more_job_flips_to_credit_hold(self, api, plant_manager_headers):
        """PRD §3.1: "flips to `CREDIT_HOLD` exactly when exposure strictly
        exceeds the credit limit." A second 85000-cent job moves exposure to
        170000 > 85000.

        Design: Difficulty/boundary_precision_check/credit_exposure_equality_boundary
        """
        cust, e1, e2 = self._setup_limit_customer()
        accept_estimate(e1["id"], cust["id"])
        # Gate reads pre-accept posture (ACTIVE), so the second accept succeeds.
        accept_estimate(e2["id"], cust["id"])
        after = get_success_data(api.get_customer(cust["id"], plant_manager_headers))
        assert after["exposure_cents"] == 170000
        assert after["posture"] == "CREDIT_HOLD"


class TestCreditHoldBlocksAccept:
    def test_credit_hold_blocks_accept(self, api, estimator_headers):
        """PRD §3.1: "a customer in `CREDIT_HOLD` cannot accept an estimate,
        and the attempt is rejected with `ERR_CREDIT_HOLD` (HTTP 409)."

        Design: Corner/errors/credit_hold_blocks_accept
        """
        cust = create_customer(name="CH Cust", credit_limit_cents=85000)
        stock = create_stock(name="70U", grade="UNCOATED", cost_per_sheet_cents=5)
        e1 = _quoted_estimate(cust, stock, quantity_ordered=1000, job_name="E1")
        e2 = _quoted_estimate(cust, stock, quantity_ordered=1000, job_name="E2")
        e3 = _quoted_estimate(cust, stock, quantity_ordered=1000, job_name="E3")
        accept_estimate(e1["id"], cust["id"])
        accept_estimate(e2["id"], cust["id"])  # exposure 170000 > 85000
        resp = api.accept_estimate(e3["id"], make_customer_headers(cust["id"]))
        validate_error(resp, ApiErrorId.ERR_CREDIT_HOLD)
        est_after = get_success_data(api.get_estimate(e3["id"], estimator_headers))
        assert est_after["status"] == "QUOTED", "fiscal rejection must not change estimate state"
