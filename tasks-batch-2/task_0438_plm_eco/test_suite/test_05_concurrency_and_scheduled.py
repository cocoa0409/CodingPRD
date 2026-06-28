"""Optimistic concurrency, clock-gated scheduled actions, and deviation coverage.

Breadth coverage of the cross-cutting complexity layers from PRD 2.7, 2.4,
3.7, 3.10.
"""
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId,
    TEST_USERS, make_change_admin_headers, make_approver_headers,
    factories, get_success_data, fixtures,
)

DESIGNER = TEST_USERS["designer_headers"]
SUPPLIER_MGR = TEST_USERS["supplier_manager_headers"]
QUALITY = TEST_USERS["quality_engineer_headers"]
VIEWER = TEST_USERS["viewer_headers"]
CA = "ca1"
CHANGE_ADMIN = make_change_admin_headers(CA)


class TestOptimisticConcurrency:
    def test_stale_part_version_on_second_revision_create(self, api):
        """PRD 2.7: "Because every new revision bumps the part's `version`, a second
        create issued against a part view whose `version` has already been advanced by
        an earlier revision create represents a genuine conflict — the client is acting
        on a stale view of the part — and the create is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_part_version_on_revision_create
        """
        part = fixtures.create_part("MAKE", base_cost_cents=0)
        v0 = part["version"]
        # First revision create advances the part's version.
        get_success_data(api.create_revision(
            part["id"], factories.create_revision_payload(v0), DESIGNER))
        # Second create reusing the stale v0 is a conflict.
        resp = api.create_revision(
            part["id"], factories.create_revision_payload(v0), DESIGNER)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_stale_revision_version_on_second_bom_line(self, api):
        """PRD 2.7: "Since each added line bumps the revision's `version`, a line add
        carrying a `version` that has already been superseded by a prior add is likewise
        rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_revision_version_on_bomline_add
        """
        leaf = fixtures.create_buy_part(base_cost_cents=10)
        part = fixtures.create_part("MAKE", base_cost_cents=0)
        rev = fixtures.create_revision(part["id"])
        rv0 = rev["version"]
        # First BOM line add advances the revision version.
        get_success_data(api.add_bom_line(
            rev["id"], factories.create_bom_line_payload(leaf["id"], 1, rv0), DESIGNER))
        # Second add reusing the stale rv0 is a conflict.
        resp = api.add_bom_line(
            rev["id"], factories.create_bom_line_payload(leaf["id"], 2, rv0), DESIGNER)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestScheduledEffectivity:
    def test_make_effective_after_clock_advance(self, api):
        """PRD 3.7: "Once an order is `APPROVED`, a `ChangeAdmin` makes it effective,
        but only when the logical clock has reached or passed the order's
        `effectivity_date`; an attempt before that instant is rejected with
        `ERR_NOT_YET_EFFECTIVE`."
        PRD 3.7: "Making the order effective transitions it `APPROVED → EFFECTIVE` and
        fires the central release cascade for each affected item's `part_revision_id`."

        Design: Corner/cross_cutting_complexity_layers/scheduled_make_effective_after_clock_advance
        """
        leaf = fixtures.create_buy_part(base_cost_cents=10)
        part, rev = fixtures.create_make_revision_with_bom(leaf["id"], base_cost_cents=0)
        get_success_data(api.submit_revision_review(rev["id"], DESIGNER))
        eco, _t = fixtures.create_approved_eco(
            part["id"], rev["id"], effectivity_date="2026-02-15T00:00:00Z")
        fixtures.set_clock("2026-02-20T00:00:00Z")
        effective = validate_success(api.make_change_order_effective(eco["id"], CHANGE_ADMIN))
        assert effective["status"] == "EFFECTIVE", effective
        r = validate_success(api.get_revision(rev["id"], VIEWER))
        assert r["lifecycle_state"] == "RELEASED", r

    def test_make_effective_before_clock_blocked(self, api):
        """PRD 3.7: "an attempt before that instant is rejected with
        `ERR_NOT_YET_EFFECTIVE`."

        Design: Corner/cross_cutting_complexity_layers/eco_make_effective_before_clock_blocked
        """
        leaf = fixtures.create_buy_part(base_cost_cents=10)
        part, rev = fixtures.create_make_revision_with_bom(leaf["id"], base_cost_cents=0)
        get_success_data(api.submit_revision_review(rev["id"], DESIGNER))
        # effectivity 2026-03-01, clock left at default 2026-01-01.
        eco, _t = fixtures.create_approved_eco(
            part["id"], rev["id"], effectivity_date="2026-03-01T00:00:00Z")
        resp = api.make_change_order_effective(eco["id"], CHANGE_ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_YET_EFFECTIVE)


class TestScheduledExpiry:
    def test_expire_before_window_end_blocked(self, api):
        """PRD 3.10: "A `QualityEngineer` expires a granted deviation, but only when the
        logical clock has passed strictly beyond its `effective_to`; an attempt at or
        before that instant is rejected with `ERR_NOT_YET_EXPIRED`."

        Design: Corner/cross_cutting_complexity_layers/deviation_expire_before_window_end_blocked
        """
        part = fixtures.create_part("PHANTOM")
        dev = fixtures.create_granted_deviation(
            part["id"], "2026-01-01T00:00:00Z", "2026-12-31T00:00:00Z",
            defect_code="FUNCTIONAL", max_units=1)
        # clock at default 2026-01-01, well before effective_to 2026-12-31.
        resp = api.expire_deviation(dev["id"], QUALITY)
        validate_error(resp, ApiErrorId.ERR_NOT_YET_EXPIRED)


class TestDeviationCoverageCap:
    def test_grant_waives_up_to_max_units_in_created_order(self, api):
        """PRD 3.10: "Candidates are ordered by their `created_at` ascending (never by
        id), and the first `max_units` of them are taken".
        PRD 3.10: "the deviation's `covered_unit_count` is incremented accordingly."

        Design: Corner/cross_cutting_complexity_layers/deviation_coverage_caps_at_max_units
        """
        part, rev, _leaf = fixtures.create_released_make_part()
        # 3 BUILT units all flagged NONCONFORMING, created in order u1, u2, u3.
        u1 = fixtures.create_nonconforming_unit(rev["id"])
        u2 = fixtures.create_nonconforming_unit(rev["id"])
        u3 = fixtures.create_nonconforming_unit(rev["id"])
        dev = fixtures.create_submitted_deviation(
            part["id"], "2026-01-01T00:00:00Z", "2026-12-31T00:00:00Z",
            defect_code="DIMENSIONAL", max_units=2)
        granted = validate_success(api.grant_deviation(dev["id"], QUALITY))
        assert granted["covered_unit_count"] == 2, granted
        assert validate_success(api.get_serialized_unit(u1["id"], QUALITY))["conformance_status"] == "WAIVED"
        assert validate_success(api.get_serialized_unit(u2["id"], QUALITY))["conformance_status"] == "WAIVED"
        assert validate_success(api.get_serialized_unit(u3["id"], QUALITY))["conformance_status"] == "NONCONFORMING"
