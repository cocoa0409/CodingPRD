"""Customer meters: accuracy-test pass/fail boundaries, FAIL cascade,
replacement succession and population conservation, retirement guard, and the
age lane on logical-clock advance (PRD §2.5, §3.5)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_DEFAULTS,
    assert_customer_meter,
    assert_meter_accuracy_test,
    complete_accuracy_test,
    create_customer_meter,
    create_dma,
    create_scheduled_accuracy_test,
    make_meter_technician_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

MT = TEST_DEFAULTS["METER_TECHNICIAN"]
PD = TEST_DEFAULTS["PROGRAM_DIRECTOR"]


def _find_meter_by_serial(api, dma_id, serial):
    data, _ = validate_paginated(
        api.list_dma_customer_meters(
            dma_id, make_meter_technician_headers(MT), params={"limit": 100}
        )
    )
    matches = [m for m in data if m["serial_number"] == serial]
    assert matches, f"expected a meter with serial {serial} under DMA {dma_id}"
    return matches[0]


class TestFailCascadeAndSuccession:
    def _setup_flagged_meter(self):
        dma = create_dma(code="DMA-TC2", connection_count=600,
                         mains_length_km=15.0, target_nrw_pct=10.0)
        meter = create_customer_meter(
            dma["id"], serial_number="SN-TC2", size_mm=20,
            installed_at="2020-01-01T00:00:00Z",
            replacement_policy="ACCURACY_BASED",
        )
        test = create_scheduled_accuracy_test(meter["id"])
        return dma, meter, test

    def test_failed_test_flags_meter_and_writes_last_accuracy(self, api,
                                                              meter_technician_headers):
        """PRD §3.5: "The `accuracy_pct` is the registered volume divided by the
        reference volume, multiplied by 100 and rounded half-up to 2 decimal
        places; the `result` is `PASS` when the accuracy is at least 98.0 and at
        most 102.0 — a test landing exactly on either boundary passes — and
        `FAIL` otherwise" and "Completion writes `last_test_accuracy_pct` onto
        the meter, and when the `result` is `FAIL` and the meter's
        `replacement_policy` is `ACCURACY_BASED` or `HYBRID`, the meter cascades
        from `IN_SERVICE` to `FLAGGED_FOR_REPLACEMENT`"

        Design: Difficulty/transitive_cascade/meter_test_fail_flags_meter_then_replace_spawns_successor
        """
        dma, meter, test = self._setup_flagged_meter()
        completed = complete_accuracy_test(test["id"], 97.99, 100.0)
        assert_meter_accuracy_test(completed)
        assert completed["status"] == "COMPLETED"
        assert completed["accuracy_pct"] == pytest.approx(97.99, abs=0.01)
        assert completed["result"] == "FAIL"

        meter_after = validate_success(
            api.get_customer_meter(meter["id"], meter_technician_headers), 200
        )
        assert meter_after["status"] == "FLAGGED_FOR_REPLACEMENT"
        assert meter_after["last_test_accuracy_pct"] == pytest.approx(97.99, abs=0.01)
        assert meter_after["replacement_due"] is True

    def test_replace_spawns_successor_meter(self, api, meter_technician_headers):
        """PRD §3.5: "Replacing a `FLAGGED_FOR_REPLACEMENT` meter requires the
        request to supply the replacement `serial_number`, which must be unique
        across the utility on pain of `ERR_DUPLICATE`. The operation retires the
        old row into `REPLACED` status and, in the same act, creates the
        successor meter: `IN_SERVICE`, carrying the replacement serial, with
        `dma_id` copied from its predecessor and `installed_at` stamped from the
        current logical clock."

        Design: Difficulty/transitive_cascade/meter_test_fail_flags_meter_then_replace_spawns_successor
        """
        dma, meter, test = self._setup_flagged_meter()
        complete_accuracy_test(test["id"], 97.99, 100.0)

        res = api.replace_customer_meter(
            meter["id"], {"serial_number": "SN-TC2-NEW"}, meter_technician_headers
        )
        assert res.status_code == 200, res.text

        old = validate_success(
            api.get_customer_meter(meter["id"], meter_technician_headers), 200
        )
        assert old["status"] == "REPLACED"

        successor = _find_meter_by_serial(api, dma["id"], "SN-TC2-NEW")
        assert_customer_meter(successor)
        assert successor["status"] == "IN_SERVICE"
        assert successor["dma_id"] == dma["id"]
        assert successor["id"] != meter["id"]


class TestAccuracyPassFailBoundaries:
    def _setup_four_meters(self):
        dma = create_dma(code="DMA-BP2", connection_count=600,
                         mains_length_km=15.0, target_nrw_pct=10.0)
        meters, tests = [], []
        for i in range(1, 5):
            m = create_customer_meter(
                dma["id"], serial_number=f"SN-BP2-{i}", size_mm=15,
                installed_at="2020-06-01T00:00:00Z",
                replacement_policy="ACCURACY_BASED",
            )
            t = create_scheduled_accuracy_test(m["id"])
            meters.append(m)
            tests.append(t)
        return dma, meters, tests

    def test_lower_boundaries_98_pass_9799_fail(self, api, meter_technician_headers):
        """PRD §3.5: "the `result` is `PASS` when the accuracy is at least 98.0
        and at most 102.0 — a test landing exactly on either boundary passes —
        and `FAIL` otherwise, remaining null until completion." and "when the
        `result` is `FAIL` and the meter's `replacement_policy` is
        `ACCURACY_BASED` or `HYBRID`, the meter cascades from `IN_SERVICE` to
        `FLAGGED_FOR_REPLACEMENT`"

        Design: Difficulty/boundary_precision_check/meter_accuracy_pass_fail_exact_boundaries
        """
        dma, meters, tests = self._setup_four_meters()

        passing = complete_accuracy_test(tests[0]["id"], 98.0, 100.0)
        assert passing["accuracy_pct"] == pytest.approx(98.0, abs=0.01)
        assert passing["result"] == "PASS"
        meter_pass = validate_success(
            api.get_customer_meter(meters[0]["id"], meter_technician_headers), 200
        )
        assert meter_pass["status"] == "IN_SERVICE"

        failing = complete_accuracy_test(tests[1]["id"], 97.99, 100.0)
        assert failing["accuracy_pct"] == pytest.approx(97.99, abs=0.01)
        assert failing["result"] == "FAIL"
        meter_fail = validate_success(
            api.get_customer_meter(meters[1]["id"], meter_technician_headers), 200
        )
        assert meter_fail["status"] == "FLAGGED_FOR_REPLACEMENT"

    def test_ceiling_boundaries_102_pass_10201_fail(self, api,
                                                    meter_technician_headers):
        """PRD §3.5: "the `result` is `PASS` when the accuracy is at least 98.0
        and at most 102.0 — a test landing exactly on either boundary passes —
        and `FAIL` otherwise, remaining null until completion."

        Design: Difficulty/boundary_precision_check/meter_accuracy_pass_fail_exact_boundaries
        """
        dma, meters, tests = self._setup_four_meters()

        ceiling_pass = complete_accuracy_test(tests[2]["id"], 102.0, 100.0)
        assert ceiling_pass["accuracy_pct"] == pytest.approx(102.0, abs=0.01)
        assert ceiling_pass["result"] == "PASS"
        meter_pass = validate_success(
            api.get_customer_meter(meters[2]["id"], meter_technician_headers), 200
        )
        assert meter_pass["status"] == "IN_SERVICE"

        over_ceiling = complete_accuracy_test(tests[3]["id"], 102.01, 100.0)
        assert over_ceiling["accuracy_pct"] == pytest.approx(102.01, abs=0.01)
        assert over_ceiling["result"] == "FAIL"
        meter_fail = validate_success(
            api.get_customer_meter(meters[3]["id"], meter_technician_headers), 200
        )
        assert meter_fail["status"] == "FLAGGED_FOR_REPLACEMENT"


class TestReplacementPopulationConservation:
    def test_flag_and_replace_keeps_in_service_count(self, api,
                                                     meter_technician_headers):
        """PRD §3.5: "The operation retires the old row into `REPLACED` status
        and, in the same act, creates the successor meter: `IN_SERVICE`,
        carrying the replacement serial, with `dma_id` copied from its
        predecessor and `installed_at` stamped from the current logical clock."

        Design: Difficulty/compensating_invariant/meter_replace_conserves_active_serial_population
        """
        dma = create_dma(code="DMA-CI2", connection_count=600,
                         mains_length_km=15.0, target_nrw_pct=10.0)
        meter_a = create_customer_meter(
            dma["id"], serial_number="SN-CI2-A", size_mm=20,
            installed_at="2019-01-01T00:00:00Z",
            replacement_policy="ACCURACY_BASED",
        )
        create_customer_meter(
            dma["id"], serial_number="SN-CI2-B", size_mm=20,
            installed_at="2021-01-01T00:00:00Z",
            replacement_policy="ACCURACY_BASED",
        )
        flagged = validate_success(
            api.flag_meter_replacement(meter_a["id"], meter_technician_headers), 200
        )
        assert flagged["status"] == "FLAGGED_FOR_REPLACEMENT"

        res = api.replace_customer_meter(
            meter_a["id"], {"serial_number": "SN-CI2-A2"}, meter_technician_headers
        )
        assert res.status_code == 200, res.text

        old = validate_success(
            api.get_customer_meter(meter_a["id"], meter_technician_headers), 200
        )
        assert old["status"] == "REPLACED"

        successor = _find_meter_by_serial(api, dma["id"], "SN-CI2-A2")
        assert successor["status"] == "IN_SERVICE"

        in_service, meta = validate_paginated(
            api.list_dma_customer_meters(
                dma["id"], meter_technician_headers,
                params={"status": "IN_SERVICE", "limit": 100},
            )
        )
        assert len(in_service) == 2, (
            "IN_SERVICE population conserved across flag+replace"
        )
        assert meta["total_count"] == 2

    def test_replaced_rows_persist_nothing_deleted(self, api,
                                                   meter_technician_headers):
        """PRD §3.5: "The operation retires the old row into `REPLACED` status
        and, in the same act, creates the successor meter: `IN_SERVICE`,
        carrying the replacement serial, with `dma_id` copied from its
        predecessor and `installed_at` stamped from the current logical clock."
        and "Meters are listable per DMA with optional `status` and
        `replacement_due` filters"

        Design: Difficulty/compensating_invariant/meter_replace_conserves_active_serial_population
        """
        dma = create_dma(code="DMA-CI2B", connection_count=600,
                         mains_length_km=15.0, target_nrw_pct=10.0)
        meter_a = create_customer_meter(
            dma["id"], serial_number="SN-CI2-A", size_mm=20,
            installed_at="2019-01-01T00:00:00Z",
            replacement_policy="ACCURACY_BASED",
        )
        create_customer_meter(
            dma["id"], serial_number="SN-CI2-B", size_mm=20,
            installed_at="2021-01-01T00:00:00Z",
            replacement_policy="ACCURACY_BASED",
        )
        validate_success(
            api.flag_meter_replacement(meter_a["id"], meter_technician_headers), 200
        )
        res = api.replace_customer_meter(
            meter_a["id"], {"serial_number": "SN-CI2-A2"}, meter_technician_headers
        )
        assert res.status_code == 200, res.text

        all_meters, meta_all = validate_paginated(
            api.list_dma_customer_meters(
                dma["id"], meter_technician_headers, params={"limit": 100}
            )
        )
        assert meta_all["total_count"] == 3, (
            "REPLACED rows persist; the successor is an additional row"
        )
        replaced, meta_replaced = validate_paginated(
            api.list_dma_customer_meters(
                dma["id"], meter_technician_headers,
                params={"status": "REPLACED", "limit": 100},
            )
        )
        assert meta_replaced["total_count"] == 1
        assert replaced[0]["id"] == meter_a["id"]


class TestRetireGuard:
    def test_retire_blocked_by_scheduled_test_then_succeeds(
        self, api, meter_technician_headers
    ):
        """PRD §3.5: "A meter may also leave service without replacement:
        retirement moves an `IN_SERVICE` meter to `RETIRED`, but only when no
        accuracy test for it remains `SCHEDULED`; attempting retirement with a
        scheduled test outstanding is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/meter_retire_blocked_by_scheduled_test
        """
        dma = create_dma(code="DMA-SM6", connection_count=600,
                         mains_length_km=15.0, target_nrw_pct=10.0)
        meter = create_customer_meter(dma["id"], serial_number="SN-SM6", size_mm=15,
                                      installed_at="2022-01-01T00:00:00Z")
        test = create_scheduled_accuracy_test(meter["id"])

        blocked = api.retire_customer_meter(meter["id"], meter_technician_headers)
        validate_error(blocked, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        reread = validate_success(
            api.get_customer_meter(meter["id"], meter_technician_headers), 200
        )
        assert reread["status"] == "IN_SERVICE"

        validate_success(
            api.cancel_meter_accuracy_test(test["id"], meter_technician_headers), 200
        )
        retired = validate_success(
            api.retire_customer_meter(meter["id"], meter_technician_headers), 200
        )
        assert retired["status"] == "RETIRED"


class TestAgeLaneOnClockAdvance:
    def test_age_based_meter_flagged_after_clock_advance(
        self, api, program_director_headers, meter_technician_headers
    ):
        """PRD §2.5: "Advancing the clock re-evaluates the age lane of the meter
        replacement policy (§3.5): the `replacement_due` flag is recomputed for
        every meter whose `replacement_policy` is `AGE_BASED` or `HYBRID`, and
        any `IN_SERVICE` meter whose age crosses the program's fifteen-year
        limit transitions to `FLAGGED_FOR_REPLACEMENT`, with an audit event
        appended."
        PRD §3.5: "the age trigger trips when that age reaches the program limit
        of 15 years — the boundary is inclusive."

        Design: Corner/cross_cutting_layers/age_based_replacement_on_clock_advance
        """
        dma = create_dma(code="DMA-AGE", connection_count=600,
                         mains_length_km=15.0, target_nrw_pct=10.0)
        meter = create_customer_meter(
            dma["id"], serial_number="SN-AGE", size_mm=15,
            installed_at="2010-01-01T00:00:00Z", replacement_policy="AGE_BASED",
        )

        clock = validate_success(
            api.set_current_utc({"to_iso8601": "2026-08-02T00:00:00Z"},
                                program_director_headers),
            200,
        )
        assert clock["current_utc"].startswith("2026-08-02")

        meter_after = validate_success(
            api.get_customer_meter(meter["id"], meter_technician_headers), 200
        )
        assert meter_after["replacement_due"] is True
        assert meter_after["status"] == "FLAGGED_FOR_REPLACEMENT"
