"""The append-only charge ledger: rounding, rollups, solvency, OCC, and the
threshold-crossing cascade into PSM applicability and auto-created audits."""
import pytest

from test_helpers import (
    ADMIN,
    CO,
    ApiErrorId,
    api_client,
    assert_charge_adjustment,
    assert_charge_posture_consistent,
    assert_timestamp_instant,
    create_charge_adjustment_payload,
    create_system,
    get_facility,
    post_charge_adjustment,
    post_gauge_reading,
    set_clock,
    setup_facility_with_operator,
    validate_error,
    validate_paginated,
    validate_success,
)


def _read_version(facility_id):
    return get_facility(facility_id)["version"]


class TestBookVsGaugeDivergence:

    def _divergence_scenario(self):
        """Facility (threshold 10000), two systems, ledger 6000.1 + 2500.0 -
        100.1, gauges 4200.0 and 3900.5."""
        set_clock("2026-08-01T00:00:00Z")
        facility, employee, op_headers = setup_facility_with_operator(
            facility_name="ColdCo Plant", threshold_lbs=10000)
        sys1 = create_system(facility["id"], name="ER1", design_charge_lbs=4000)
        sys2 = create_system(facility["id"], name="ER2", design_charge_lbs=3500)
        e1, _ = post_charge_adjustment(facility["id"], "ADD", 6000.05,
                                       "initial charge ER1", op_headers,
                                       system_id=sys1["id"])
        e2, _ = post_charge_adjustment(facility["id"], "ADD", 2500.04,
                                       "initial charge ER2", op_headers,
                                       system_id=sys2["id"])
        e3, _ = post_charge_adjustment(facility["id"], "REMOVE", 100.05,
                                       "pump-out for valve work", op_headers,
                                       system_id=sys1["id"])
        post_gauge_reading(sys1["id"], 4200.0, op_headers)
        post_gauge_reading(sys2["id"], 3900.5, op_headers)
        return facility, [e1, e2, e3]

    def test_charge_rollup_book_vs_gauge_diverge(self):
        """PRD section 3.2: "the gauge figure sums, over the facility's
        `IN_SERVICE` systems only, each system's `last_gauge_reading_lbs`,
        substituting the nameplate `design_charge_lbs` for any system never
        gauged; `delta_lbs` records the difference between the gauge total and
        the book total."
        PRD section 3.2: "The `total_charge_lbs` on the facility is always the
        book variant — the rounded `ADD` lines minus the rounded `REMOVE` lines
        across the ledger's unbounded history — recomputed on every successful
        posting."

        Design: Difficulty/dual_variant_calc/charge_rollup_book_vs_gauge_diverge
        """
        facility, _ = self._divergence_scenario()
        resp = api_client.get_charge_summary(facility["id"], CO)
        summary = validate_success(resp, expected_status=200)
        # book: 6000.1 + 2500.0 - 100.1 = 8400.0; gauge: 4200.0 + 3900.5 = 8100.5
        assert summary["book_charge_lbs"] == pytest.approx(8400.0, abs=0.01)
        assert summary["gauge_charge_lbs"] == pytest.approx(8100.5, abs=0.01)
        assert abs(summary["delta_lbs"]) == pytest.approx(299.5, abs=0.01)
        # the book variant (8400.0 < 10000) is authoritative for posture
        assert summary["charge_posture"] == "BELOW_THRESHOLD"

    def test_charge_rollup_per_line_stamps_feed_book(self):
        """PRD section 2.6: "The rounding order is pinned: each requested
        quantity is rounded first, per line, at posting time — to the nearest
        tenth of a pound, half up — and stamped onto the entry as its
        `rounded_lbs`; the ledger stores and sums only those rounded values."

        Design: Difficulty/dual_variant_calc/charge_rollup_book_vs_gauge_diverge
        """
        facility, entries = self._divergence_scenario()
        assert entries[0]["rounded_lbs"] == pytest.approx(6000.1, abs=0.001)
        assert entries[1]["rounded_lbs"] == pytest.approx(2500.0, abs=0.001)
        assert entries[2]["rounded_lbs"] == pytest.approx(100.1, abs=0.001)
        facility_after = get_facility(facility["id"])
        assert facility_after["total_charge_lbs"] == pytest.approx(8400.0, abs=0.01)
        assert_charge_posture_consistent(facility_after)


class TestPerLineRoundingOrder:

    def test_per_line_rounding_stamps_each_entry(self):
        """PRD section 2.6: "The rounding order is pinned: each requested
        quantity is rounded first, per line, at posting time — to the nearest
        tenth of a pound, half up — and stamped onto the entry as its
        `rounded_lbs`; the ledger stores and sums only those rounded values."

        Design: Difficulty/combinatorial_formula/charge_rollup_per_line_rounding_order
        """
        facility, employee, op_headers = setup_facility_with_operator(
            facility_name="Rounding Test Facility")
        entries = [
            post_charge_adjustment(facility["id"], "ADD", 10.05,
                                   f"top-up {i}", op_headers)[0]
            for i in (1, 2, 3)
        ]
        for entry in entries:
            # round_half_up(10.05, 0.1) == 10.1, stamped per line at posting
            assert entry["rounded_lbs"] == pytest.approx(10.1, abs=0.001)

    def test_per_line_rounding_order_drives_summary_total(self):
        """PRD section 2.6: "The facility's book inventory is therefore the sum
        of the `rounded_lbs` of every `ADD` entry minus the sum of the
        `rounded_lbs` of every `REMOVE` entry, taken across the facility's
        entire ledger with no time window."

        Design: Difficulty/combinatorial_formula/charge_rollup_per_line_rounding_order
        """
        facility, employee, op_headers = setup_facility_with_operator(
            facility_name="Rounding Test Facility")
        for i in (1, 2, 3):
            post_charge_adjustment(facility["id"], "ADD", 10.05,
                                   f"top-up {i}", op_headers)
        summary = validate_success(
            api_client.get_charge_summary(facility["id"], ADMIN),
            expected_status=200)
        # 3 x round_half_up(10.05) = 3 x 10.1 = 30.3; a sum-then-round order
        # would produce round(30.15) = 30.2 — the per-line order is pinned.
        assert summary["book_charge_lbs"] == pytest.approx(30.3, abs=0.01)


class TestChargeConservation:

    def _seed_2000(self):
        facility, employee, op_headers = setup_facility_with_operator()
        _, facility = post_charge_adjustment(facility["id"], "ADD", 2000.0,
                                             "initial charge", op_headers)
        return facility, op_headers

    def test_charge_add_remove_conservation_restores_total(self):
        """PRD section 2.6: "The facility's book inventory is therefore the sum
        of the `rounded_lbs` of every `ADD` entry minus the sum of the
        `rounded_lbs` of every `REMOVE` entry, taken across the facility's
        entire ledger with no time window."

        Design: Difficulty/compensating_invariant/charge_add_remove_conservation
        """
        facility, op_headers = self._seed_2000()
        assert facility["total_charge_lbs"] == pytest.approx(2000.0, abs=0.01)

        _, mid = post_charge_adjustment(facility["id"], "ADD", 300.0,
                                        "top-up", op_headers)
        assert mid["total_charge_lbs"] == pytest.approx(2300.0, abs=0.01)

        _, end = post_charge_adjustment(facility["id"], "REMOVE", 300.0,
                                        "reverse erroneous top-up", op_headers)
        # forward + compensating entry restore the pre-pair total exactly
        assert end["total_charge_lbs"] == pytest.approx(2000.0, abs=0.01)
        assert end["charge_posture"] == "BELOW_THRESHOLD"

    def test_charge_conservation_only_version_advances(self):
        """PRD section 3.2: "On success the platform stamps the per-line
        `rounded_lbs` (rounded to the tenth of a pound, half up), records the
        acting operator as `posted_by_employee_id` from the request's
        `X-User-ID`, increments the facility's `version` by one, and recomputes
        the book inventory and charge posture."

        Design: Difficulty/compensating_invariant/charge_add_remove_conservation
        """
        facility, op_headers = self._seed_2000()
        v0 = facility["version"]  # already advanced once by the seed posting
        _, mid = post_charge_adjustment(facility["id"], "ADD", 300.0,
                                        "top-up", op_headers)
        assert mid["version"] == v0 + 1
        _, end = post_charge_adjustment(facility["id"], "REMOVE", 300.0,
                                        "reverse erroneous top-up", op_headers)
        assert end["version"] == v0 + 2
        assert end["total_charge_lbs"] == pytest.approx(2000.0, abs=0.01)


class TestThresholdCrossingCascade:

    def _facility_at(self, total, threshold=10000):
        facility, employee, op_headers = setup_facility_with_operator(
            facility_name="ColdCo Plant", threshold_lbs=threshold)
        set_clock("2026-08-01T00:00:00Z")
        _, facility = post_charge_adjustment(facility["id"], "ADD", total,
                                             "initial charge", op_headers)
        return facility, op_headers

    def test_threshold_crossing_flips_posture_and_program(self):
        """PRD section 3.2: "A posting that flips the posture from
        `BELOW_THRESHOLD` to `AT_OR_ABOVE_THRESHOLD` triggers the threshold
        cascade: the facility's `psm_program_status` flips to `REQUIRED` and
        stays there — the flag is sticky and never auto-reverts, even if the
        charge later drops — and the platform auto-creates a **ComplianceAudit**
        with `origin` `AUTO_THRESHOLD`, standing `SCHEDULED`, starting at the
        crossing instant, and due 1095 days (three years) after it."

        Design: Difficulty/transitive_cascade/charge_threshold_crossing_cascade
        """
        facility, op_headers = self._facility_at(9900.0)
        assert facility["total_charge_lbs"] == pytest.approx(9900.0, abs=0.01)
        assert facility["charge_posture"] == "BELOW_THRESHOLD"

        _, after = post_charge_adjustment(facility["id"], "ADD", 150.0,
                                          "top-up after expansion", op_headers)
        assert after["total_charge_lbs"] == pytest.approx(10050.0, abs=0.01)
        assert after["charge_posture"] == "AT_OR_ABOVE_THRESHOLD"
        assert after["psm_program_status"] == "REQUIRED"

    def test_threshold_crossing_creates_auto_audit(self):
        """PRD section 3.9: "The threshold cascade of §3.2 opens the second
        door: a facility's first crossing from `BELOW_THRESHOLD` to
        `AT_OR_ABOVE_THRESHOLD` auto-creates an audit with `origin`
        `AUTO_THRESHOLD`, scheduled to start at the crossing instant and due
        1095 days — three years — later."

        Design: Difficulty/transitive_cascade/charge_threshold_crossing_cascade
        """
        facility, op_headers = self._facility_at(9900.0)
        post_charge_adjustment(facility["id"], "ADD", 150.0,
                               "top-up after expansion", op_headers)
        resp = api_client.list_compliance_audits(
            CO, params={"facility_id": facility["id"]})
        audits, meta = validate_paginated(resp)
        assert meta["total_count"] == 1, \
            f"exactly one AUTO_THRESHOLD audit must exist, got {meta['total_count']}"
        audit = audits[0]
        assert audit["origin"] == "AUTO_THRESHOLD"
        assert audit["status"] == "SCHEDULED"
        # crossing at 2026-08-01T00:00:00Z + 1095 days (2028 is a leap year)
        assert_timestamp_instant(audit["due_at"], "2029-07-31T00:00:00Z")
        assert_timestamp_instant(audit["scheduled_start_at"],
                                 "2026-08-01T00:00:00Z")


class TestExactlyAtThreshold:

    def test_charge_posture_exactly_at_threshold_trips(self):
        """PRD section 3.2: "The `charge_posture` reads `AT_OR_ABOVE_THRESHOLD`
        whenever that book total reaches or exceeds `threshold_lbs`, and
        `BELOW_THRESHOLD` otherwise."

        Design: Difficulty/boundary_precision_check/charge_posture_exactly_at_threshold
        """
        set_clock("2026-08-01T00:00:00Z")
        facility, employee, op_headers = setup_facility_with_operator(
            facility_name="ColdCo Plant", threshold_lbs=10000)
        post_charge_adjustment(facility["id"], "ADD", 5000.0,
                               "vessel charge 1", op_headers)
        _, after = post_charge_adjustment(facility["id"], "ADD", 5000.0,
                                          "vessel charge 2", op_headers)
        # exactly 10000.0 == threshold: the comparison is >=, so it trips
        assert after["total_charge_lbs"] == pytest.approx(10000.0, abs=0.01)
        assert after["charge_posture"] == "AT_OR_ABOVE_THRESHOLD"
        assert after["psm_program_status"] == "REQUIRED"
        audits, meta = validate_paginated(api_client.list_compliance_audits(
            CO, params={"facility_id": facility["id"]}))
        assert meta["total_count"] == 1
        assert audits[0]["origin"] == "AUTO_THRESHOLD"
        assert_timestamp_instant(audits[0]["due_at"], "2029-07-31T00:00:00Z")

    def test_charge_posture_one_step_below_threshold_stays_below(self):
        """PRD section 3.2: "The `charge_posture` reads `AT_OR_ABOVE_THRESHOLD`
        whenever that book total reaches or exceeds `threshold_lbs`, and
        `BELOW_THRESHOLD` otherwise."

        Design: Difficulty/boundary_precision_check/charge_posture_exactly_at_threshold
        """
        facility, employee, op_headers = setup_facility_with_operator(
            facility_name="ColdCo Plant", threshold_lbs=10000)
        _, after = post_charge_adjustment(facility["id"], "ADD", 9999.9,
                                          "just under threshold", op_headers)
        assert after["total_charge_lbs"] == pytest.approx(9999.9, abs=0.01)
        assert after["charge_posture"] == "BELOW_THRESHOLD"
        assert after["psm_program_status"] == "NOT_REQUIRED"
        audits, meta = validate_paginated(api_client.list_compliance_audits(
            CO, params={"facility_id": facility["id"]}))
        assert meta["total_count"] == 0


class TestLedgerEntryShape:

    def test_charge_adjustment_immutable_ledger_entry(self):
        """PRD section 2.4: "One deliberate exception exists: the charge ledger
        entry is an append-only event carrying only `id` and `created_at`; both
        `updated_at` and `version` are absent from it, and a mistaken posting
        is corrected by posting a compensating entry, never by editing the
        original."
        PRD section 3.2: "On success the platform stamps the per-line
        `rounded_lbs` (rounded to the tenth of a pound, half up), records the
        acting operator as `posted_by_employee_id` from the request's
        `X-User-ID`, increments the facility's `version` by one, and recomputes
        the book inventory and charge posture."

        Design: Corner/entities/charge_adjustment_immutable_ledger_entry
        """
        facility, employee, op_headers = setup_facility_with_operator()
        version = _read_version(facility["id"])
        resp = api_client.create_charge_adjustment(
            create_charge_adjustment_payload(
                facility["id"], version, adjustment_type="ADD",
                quantity_lbs=250.0, reason="initial charge"),
            op_headers)
        entry = validate_success(resp, expected_status=201)
        assert_charge_adjustment(entry)
        assert entry["facility_id"] == facility["id"]
        assert entry["adjustment_type"] == "ADD"
        assert entry["quantity_lbs"] == pytest.approx(250.0, abs=0.001)
        assert entry["rounded_lbs"] == pytest.approx(250.0, abs=0.001)
        assert entry["reason"] == "initial charge"
        assert entry["posted_by_employee_id"] == employee["id"]


class TestGaugeVariantFallback:

    def test_ungauged_in_service_system_contributes_design_charge(self):
        """PRD section 3.2: "the gauge figure sums, over the facility's
        `IN_SERVICE` systems only, each system's `last_gauge_reading_lbs`,
        substituting the nameplate `design_charge_lbs` for any system never
        gauged; `delta_lbs` records the difference between the gauge total and
        the book total."

        Design: Corner/entities/ungauged_in_service_system_contributes_design_charge
        """
        facility, employee, op_headers = setup_facility_with_operator()
        sys1 = create_system(facility["id"], name="ER1", design_charge_lbs=4000)
        create_system(facility["id"], name="ER2", design_charge_lbs=3500)
        post_gauge_reading(sys1["id"], 4100.0, op_headers)
        summary = validate_success(
            api_client.get_charge_summary(facility["id"], ADMIN),
            expected_status=200)
        # gauged ER1 contributes 4100.0; never-gauged ER2 contributes 3500
        assert summary["gauge_charge_lbs"] == pytest.approx(7600.0, abs=0.01)
        # empty ledger — the variants are independent
        assert summary["book_charge_lbs"] == pytest.approx(0.0, abs=0.001)


class TestLedgerSolvency:

    def test_charge_remove_exceeding_total_rejected(self):
        """PRD section 2.6: "Every posted `quantity_lbs` must be strictly
        positive — a zero or negative quantity is rejected with
        `ERR_QUANTITY_NOT_POSITIVE` (422) — and a `REMOVE` posting may never
        drive the facility's book inventory below zero; a removal that would do
        so is rejected with `ERR_CHARGE_NEGATIVE` (422)."

        Design: Corner/validations/charge_remove_exceeding_total_rejected
        """
        facility, employee, op_headers = setup_facility_with_operator()
        _, facility = post_charge_adjustment(facility["id"], "ADD", 100.0,
                                             "seed charge", op_headers)
        version_before = facility["version"]
        resp = api_client.create_charge_adjustment(
            create_charge_adjustment_payload(
                facility["id"], version_before, adjustment_type="REMOVE",
                quantity_lbs=150.0, reason="overdraw attempt"),
            op_headers)
        validate_error(resp, ApiErrorId.ERR_CHARGE_NEGATIVE, expected_status=422)
        after = get_facility(facility["id"])
        assert after["total_charge_lbs"] == pytest.approx(100.0, abs=0.01)
        # a rejected write is no mutation: the version does not advance
        assert after["version"] == version_before

    def test_charge_zero_quantity_rejected(self):
        """PRD section 2.6: "Every posted `quantity_lbs` must be strictly
        positive — a zero or negative quantity is rejected with
        `ERR_QUANTITY_NOT_POSITIVE` (422) — and a `REMOVE` posting may never
        drive the facility's book inventory below zero; a removal that would do
        so is rejected with `ERR_CHARGE_NEGATIVE` (422)."
        PRD section 2.6: "The rounding order is pinned: each requested quantity
        is rounded first, per line, at posting time — to the nearest tenth of a
        pound, half up — and stamped onto the entry as its `rounded_lbs`; the
        ledger stores and sums only those rounded values."

        Design: Corner/validations/charge_zero_quantity_rejected
        """
        facility, employee, op_headers = setup_facility_with_operator()
        version = _read_version(facility["id"])
        resp = api_client.create_charge_adjustment(
            create_charge_adjustment_payload(
                facility["id"], version, adjustment_type="ADD",
                quantity_lbs=0, reason="zero add"),
            op_headers)
        validate_error(resp, ApiErrorId.ERR_QUANTITY_NOT_POSITIVE,
                       expected_status=422)
        # the rejection consumed nothing: the same expected version still posts
        ok = api_client.create_charge_adjustment(
            create_charge_adjustment_payload(
                facility["id"], version, adjustment_type="ADD",
                quantity_lbs=0.05, reason="smallest positive"),
            op_headers)
        entry = validate_success(ok, expected_status=201)
        # round_half_up(0.05, 0.1) == 0.1
        assert entry["rounded_lbs"] == pytest.approx(0.1, abs=0.001)


class TestImmediateConsistency:

    def test_immediate_visibility_after_charge_posting(self):
        """PRD section 3.2: "The `total_charge_lbs` on the facility is always
        the book variant — the rounded `ADD` lines minus the rounded `REMOVE`
        lines across the ledger's unbounded history — recomputed on every
        successful posting."
        PRD section 2.4: "The platform maintains these fields itself: they
        refresh whenever an input changes, and time-dependent ones also refresh
        when the logical clock is observed on a read or swept by the
        checkpoint."

        Design: Corner/consistency_model/immediate_visibility_after_charge_posting
        """
        facility, employee, op_headers = setup_facility_with_operator()
        version = _read_version(facility["id"])
        resp = api_client.create_charge_adjustment(
            create_charge_adjustment_payload(
                facility["id"], version, adjustment_type="ADD",
                quantity_lbs=250.0, reason="initial charge"),
            op_headers)
        validate_success(resp, expected_status=201)
        # no checkpoint or read-repair: the very next GET reflects the write
        after = get_facility(facility["id"])
        assert after["total_charge_lbs"] == pytest.approx(250.0, abs=0.01)
        assert after["version"] == version + 1


class TestChargeOcc:

    def test_occ_charge_adjust_stale_version_rejected(self):
        """PRD section 2.8: "Posting a charge adjustment requires the request
        to carry `expected_facility_version`, the facility version the client
        last observed. If that value does not match the facility's current
        `version` — because another posting has advanced it since the client
        last read the facility — the request is rejected with
        `ERR_STALE_VERSION` (412)."

        Design: Corner/complexity_layers/occ_charge_adjust_stale_version_rejected
        """
        facility, employee, op_headers = setup_facility_with_operator()
        stale_version = _read_version(facility["id"])
        _, facility = post_charge_adjustment(facility["id"], "ADD", 100.0,
                                             "first posting", op_headers)
        resp = api_client.create_charge_adjustment(
            create_charge_adjustment_payload(
                facility["id"], stale_version, adjustment_type="ADD",
                quantity_lbs=50.0, reason="stale posting"),
            op_headers)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
        after = get_facility(facility["id"])
        # only the first posting landed
        assert after["total_charge_lbs"] == pytest.approx(100.0, abs=0.01)
        assert after["version"] == facility["version"]
