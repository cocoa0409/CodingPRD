"""Stockpile inventory, manual adjustments, and gradation quality control."""
import pytest

from test_helpers import (
    ADMIN,
    MANAGER,
    QC_1,
    ApiErrorId,
    adjust_stockpile,
    assert_stockpile_invariants,
    create_confirmed_order,
    create_gradation_test,
    create_product_spec_payload,
    create_site,
    create_spec,
    create_stockpile,
    create_zone,
    get_stockpile,
    make_qc_technician_headers,
    stockpile_adjustment_payload,
    validate_error,
    validate_success,
)

QC_2 = make_qc_technician_headers("qc-2")


def _site_with_pile():
    """Site + COARSE spec (band 1.5in [90,100]) + one OPEN stockpile."""
    site = create_site()
    spec = create_spec()
    pile = create_stockpile(site["id"], spec["id"])
    return site, spec, pile


class TestStockpileCreation:
    def test_stockpile_unique_per_site_spec_rejected(self, api):
        """PRD 3.4: "There is at most one stockpile per
        site-and-specification pair; a duplicate is rejected with
        `ERR_STOCKPILE_EXISTS`."

        Design: Corner/entities/stockpile_unique_per_site_spec_rejected
        """
        site = create_site()
        spec_a = create_spec(spec_code="A57", category="COARSE")
        spec_b = create_spec(spec_code="FINE-1", category="FINE")
        create_stockpile(site["id"], spec_a["id"])
        resp = api.create_stockpile(
            {"site_id": site["id"], "product_spec_id": spec_a["id"],
             "capacity_tons": 3000}, MANAGER)
        validate_error(resp, ApiErrorId.ERR_STOCKPILE_EXISTS)
        # Uniqueness is scoped to the pair: another spec is fine.
        pile_b = create_stockpile(site["id"], spec_b["id"],
                                  capacity_tons=3000)
        assert pile_b["status"] == "OPEN"

    def test_spec_create_invalid_enum_category_returns_invalid_request(
            self, api):
        """PRD 3.4: "a `category` of `COARSE`, `FINE`, or `RIPRAP`".
        PRD 2.7 tier 3: "Request shape — required fields present, types
        valid, enum values within their declared sets ... otherwise
        `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/spec_create_invalid_enum_category_returns_invalid_request
        """
        payload = create_product_spec_payload(spec_code="X-1",
                                              category="BOULDER")
        resp = api.create_product_spec(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestGradationResults:
    def test_gradation_result_computed_at_create(self, api):
        """PRD 3.4: "The test's `result` is computed at creation and is
        immutable thereafter: the result is `PASS` when every sieve's
        `pct_passing` falls within its band from `min_pct` through
        `max_pct` with both bounds included — a measurement exactly on
        either bound passes — and `FAIL` otherwise. A reported test stands
        `REPORTED` with the technician recorded in `reported_by_user_id`."

        Design: Corner/entities/gradation_result_computed_at_create
        """
        _site, _spec, pile = _site_with_pile()
        t1 = create_gradation_test(
            pile["id"], "2026-08-01T06:00:00Z",
            [{"sieve": "1.5in", "pct_passing": 95}])
        assert t1["result"] == "PASS"
        assert t1["status"] == "REPORTED"
        assert t1["reported_by_user_id"] == "qc-1"
        t2 = create_gradation_test(
            pile["id"], "2026-08-01T07:00:00Z",
            [{"sieve": "1.5in", "pct_passing": 85}])
        assert t2["result"] == "FAIL"

    def test_gradation_inclusive_band_bounds(self, api):
        """PRD 3.4: "the result is `PASS` when every sieve's `pct_passing`
        falls within its band from `min_pct` through `max_pct` with both
        bounds included — a measurement exactly on either bound passes".

        Design: Corner/calculations/gradation_inclusive_band_bounds
        """
        site = create_site()
        spec = create_spec(gradation_bands=[
            {"sieve": "1.5in", "min_pct": 90, "max_pct": 100},
            {"sieve": "No4", "min_pct": 0, "max_pct": 10},
        ])
        pile = create_stockpile(site["id"], spec["id"])
        t1 = create_gradation_test(
            pile["id"], "2026-08-01T06:00:00Z",
            [{"sieve": "1.5in", "pct_passing": 90},
             {"sieve": "No4", "pct_passing": 10}])
        assert t1["result"] == "PASS"

    def test_sod_gradation_confirm_same_user_rejected(self, api):
        """PRD 2.10: "A gradation test may not be confirmed by the
        technician who reported it. ... Each violation is rejected with
        `ERR_SOD_VIOLATION` (403)."

        Design: Corner/validations/sod_gradation_confirm_same_user_rejected
        """
        _site, _spec, pile = _site_with_pile()
        t1 = create_gradation_test(
            pile["id"], "2026-08-01T06:00:00Z",
            [{"sieve": "1.5in", "pct_passing": 95}])
        resp = api.confirm_gradation_test(t1["id"], QC_1)
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)
        t1 = validate_success(api.get_gradation_test(t1["id"], QC_1))
        assert t1["status"] == "REPORTED"


class TestQuarantineCycle:
    def test_confirmed_fail_quarantines_pile(self, api):
        """PRD 3.4: "A confirmed `FAIL` drives the pile `OPEN` →
        `QUARANTINED`, which blocks new order confirmations and ticket
        weigh-ins against it (`ERR_STOCKPILE_QUARANTINED`) as well as
        plant-run output credits."

        Design: Difficulty/non_linear_state_machine/stockpile_quarantine_release_cycle
        """
        _site, _spec, pile = _site_with_pile()
        t1 = create_gradation_test(
            pile["id"], "2026-08-01T06:00:00Z",
            [{"sieve": "1.5in", "pct_passing": 95}])
        validate_success(api.confirm_gradation_test(t1["id"], QC_2))
        assert get_stockpile(pile["id"])["status"] == "OPEN"
        t2 = create_gradation_test(
            pile["id"], "2026-08-01T07:00:00Z",
            [{"sieve": "1.5in", "pct_passing": 80}])
        assert t2["result"] == "FAIL"
        validate_success(api.confirm_gradation_test(t2["id"], QC_2))
        assert get_stockpile(pile["id"])["status"] == "QUARANTINED"

    def test_latest_confirmed_pass_releases_pile(self, api):
        """PRD 3.4: "A confirmed `PASS` restores the pile `QUARANTINED` →
        `OPEN` only when no later confirmed, non-voided `FAIL` exists for
        the pile: the latest confirmed test decides, selected by the
        greatest `sampled_at` with ties broken by the greatest
        `created_at`."

        Design: Difficulty/non_linear_state_machine/stockpile_quarantine_release_cycle
        """
        _site, _spec, pile = _site_with_pile()
        t1 = create_gradation_test(
            pile["id"], "2026-08-01T06:00:00Z",
            [{"sieve": "1.5in", "pct_passing": 95}])
        validate_success(api.confirm_gradation_test(t1["id"], QC_2))
        t2 = create_gradation_test(
            pile["id"], "2026-08-01T07:00:00Z",
            [{"sieve": "1.5in", "pct_passing": 80}])
        validate_success(api.confirm_gradation_test(t2["id"], QC_2))
        assert get_stockpile(pile["id"])["status"] == "QUARANTINED"
        t3 = create_gradation_test(
            pile["id"], "2026-08-01T08:00:00Z",
            [{"sieve": "1.5in", "pct_passing": 97}])
        assert t3["result"] == "PASS"
        validate_success(api.confirm_gradation_test(t3["id"], QC_2))
        assert get_stockpile(pile["id"])["status"] == "OPEN"


class TestAdjustmentsAndClose:
    def test_adjustment_below_reserved_rejected(self, api):
        """PRD 3.4: "A negative adjustment may not drive `on_hand_tons`
        below `reserved_tons` (`ERR_ADJUSTMENT_BELOW_RESERVED`)."

        Design: Corner/validations/adjustment_below_reserved_rejected
        """
        site = create_site()
        spec = create_spec()
        zone = create_zone()
        pile = create_stockpile(site["id"], spec["id"])
        pile = adjust_stockpile(pile, 100.0)
        order = create_confirmed_order(site["id"], spec["id"], zone["id"],
                                       quantity_tons=30)
        assert order["status"] == "CONFIRMED"
        pile = get_stockpile(pile["id"])
        assert pile["reserved_tons"] == pytest.approx(30.0, abs=1e-6)
        payload = stockpile_adjustment_payload(-85.0, pile["version"],
                                               reason="write-down")
        resp = api.adjust_stockpile(pile["id"], payload, MANAGER)
        validate_error(resp, ApiErrorId.ERR_ADJUSTMENT_BELOW_RESERVED)
        assert get_stockpile(pile["id"])["on_hand_tons"] == pytest.approx(
            100.0, abs=1e-6)

    def test_adjustment_over_capacity_rejected(self, api):
        """PRD 3.4: "Physical stock may never exceed `capacity_tons`: any
        run credit or manual adjustment that would push `on_hand_tons`
        above capacity is rejected with `ERR_STOCKPILE_CAPACITY_EXCEEDED`."

        Design: Corner/validations/adjustment_over_capacity_rejected
        """
        site = create_site()
        spec = create_spec()
        pile = create_stockpile(site["id"], spec["id"], capacity_tons=5000)
        pile = adjust_stockpile(pile, 4000.0)
        payload = stockpile_adjustment_payload(1500.0, pile["version"],
                                               reason="survey overcredited")
        resp = api.adjust_stockpile(pile["id"], payload, MANAGER)
        validate_error(resp, ApiErrorId.ERR_STOCKPILE_CAPACITY_EXCEEDED)
        after = get_stockpile(pile["id"])
        assert after["on_hand_tons"] == pytest.approx(4000.0, abs=1e-6)
        assert after["version"] == pile["version"]
        assert_stockpile_invariants(after)

    def test_occ_stockpile_adjustment_stale_version(self, api):
        """PRD 2.8: "In each case, if the supplied value does not equal the
        resource's current `version` — because an accepted write (a
        production credit, a ticket draw, a reservation, a prior adjustment,
        a prior release, or a prior reprice) has advanced it since the
        client last read the resource — the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412) and nothing is mutated."

        Design: Corner/complexity_layers/occ_stockpile_adjustment_stale_version
        """
        site = create_site()
        spec = create_spec()
        pile = create_stockpile(site["id"], spec["id"])
        pile_v = pile["version"]
        payload = stockpile_adjustment_payload(50.0, pile_v,
                                               reason="survey credit")
        pile = validate_success(
            api.adjust_stockpile(pile["id"], payload, MANAGER))
        assert pile["on_hand_tons"] == pytest.approx(50.0, abs=1e-6)
        assert pile["version"] == pile_v + 1
        stale = stockpile_adjustment_payload(10.0, pile_v,
                                             reason="stale recount")
        resp = api.adjust_stockpile(pile["id"], stale, MANAGER)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert get_stockpile(pile["id"])["on_hand_tons"] == pytest.approx(
            50.0, abs=1e-6)

    def test_stockpile_close_not_empty_rejected(self, api):
        """PRD 3.4: "Closing a pile — from either `OPEN` or `QUARANTINED` —
        requires that both `on_hand_tons` and `reserved_tons` stand at
        exactly zero (`ERR_STOCKPILE_NOT_EMPTY`); `CLOSED` is terminal."

        Design: Corner/validations/stockpile_close_not_empty_rejected
        """
        site = create_site()
        spec = create_spec()
        pile = create_stockpile(site["id"], spec["id"])
        pile = adjust_stockpile(pile, 100.0)
        resp = api.close_stockpile(pile["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_STOCKPILE_NOT_EMPTY)
        assert get_stockpile(pile["id"])["status"] == "OPEN"
