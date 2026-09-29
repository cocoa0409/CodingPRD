"""Gauge calibration linkage, subgroup scoring and the two capability variants."""

from test_helpers import (
    MEASUREMENTS_AT_CPK_MIN,
    MEASUREMENTS_BELOW_CPK_MIN,
    MEASUREMENTS_TIGHTER,
    ApiErrorId,
    add_characteristic,
    api_client,
    make_inspector_headers,
    make_quality_manager_headers,
    make_shop_planner_headers,
    post_subgroup,
    read_gauge,
    read_work_order,
    register_gauge,
    register_second_part,
    set_clock,
    setup_running_work_order,
    validate_error,
    validate_success,
)

PLANNER = make_shop_planner_headers()
QUALITY = make_quality_manager_headers()


def _post(shop, measurements, piece_index=200, inspector=None, characteristic_id=None, gauge_id=None):
    return api_client.create_spc_sample(
        {
            "work_order_id": shop.work_order_id,
            "characteristic_id": characteristic_id or shop.characteristic_id,
            "gauge_id": gauge_id or shop.gauge_id,
            "piece_index": piece_index,
            "measurements": list(measurements),
        },
        make_inspector_headers(inspector or shop.inspector_id),
    )


class TestCapabilityVariants:
    """The within-subgroup index and the pooled long-term index diverge."""

    def test_each_subgroup_is_scored_from_its_own_range(self):
        """PRD 3.8: "`sigma_within` is the range divided by the bias-correction
        constant for the subgroup size — 1.693 when the characteristic's
        `subgroup_size` is 3, and 2.326 when it is 5 — rounded half up to 6
        decimal places."
        PRD 3.8: "An accepted post is scored immediately, against that one
        subgroup and nothing else — no sibling sample and no other work order
        participates."

        Design: Difficulty/dual_variant_calc/capability_cpk_short_term_vs_ppk_long_term
        """
        shop = setup_running_work_order(
            characteristic_overrides={"sample_freq_pieces": 100}
        )

        first = validate_success(_post(shop, MEASUREMENTS_AT_CPK_MIN, piece_index=100), 201)
        second = validate_success(_post(shop, MEASUREMENTS_TIGHTER, piece_index=200), 201)

        assert first["cpk_short_term"] == 1.385
        assert first["range"] == 0.014
        assert first["sigma_within"] == 0.006019
        assert first["disposition"] == "ACCEPT"

        assert second["cpk_short_term"] == 1.615
        assert second["range"] == 0.012
        assert second["disposition"] == "ACCEPT"

    def test_long_term_index_differs_from_the_short_term_minimum(self):
        """PRD 3.8: "The long-term capability index is the lesser of the
        characteristic's `usl` minus the long-term mean and the long-term mean
        minus the characteristic's `lsl`, divided by three times that overall
        sigma, rounded half up to 3 decimal places."
        PRD 3.8: "Because the overall sigma counts drift between subgroups while
        the within-subgroup sigma cannot see it, the same measurement data yields
        a different number from the two variants; the per-subgroup verdict is
        judged on the short-term index and the acceptance gate of §3.9 is judged
        on the long-term one."

        Design: Difficulty/dual_variant_calc/capability_cpk_short_term_vs_ppk_long_term
        """
        shop = setup_running_work_order(
            characteristic_overrides={"sample_freq_pieces": 100}
        )
        _post(shop, MEASUREMENTS_AT_CPK_MIN, piece_index=100)
        _post(shop, MEASUREMENTS_TIGHTER, piece_index=200)

        summary = validate_success(
            api_client.get_quality_summary(shop.work_order_id, QUALITY), 200
        )
        assert summary["sample_count"] == 2
        assert summary["cpk_short_term_min"] == 1.385
        assert summary["ppk_long_term_min"] == 1.917
        assert summary["ppk_long_term_min"] != summary["cpk_short_term_min"]

        work_order = read_work_order(shop.work_order_id)
        assert work_order["quality_status"] == "IN_SPC"
        assert work_order["machining_status"] == "RUNNING"


class TestGaugeGateOrder:
    """An out-of-service gauge masks the subgroup-size mismatch behind it."""

    def test_out_of_service_gauge_is_reported_before_the_subgroup_size(self):
        """PRD 3.8: "Four domain checks guard the post, in this order. First the
        gauge must be `IN_SERVICE` after the lazy re-evaluation above; a gauge that
        is `CALIBRATION_DUE`, `GRR_FAILED` or `RETIRED` is rejected with
        `ERR_GAUGE_NOT_IN_SERVICE` (HTTP 409)."
        PRD 3.8: "Third, the length of the `measurements` array must equal the
        characteristic's `subgroup_size`; a mismatch is rejected with
        `ERR_SUBGROUP_SIZE_MISMATCH` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/gauge_out_of_service_beats_subgroup_size
        """
        shop = setup_running_work_order(
            gauge_overrides={"calibration_due_at": "2026-09-05T00:00:00Z"}
        )
        set_clock("2026-09-06T00:00:00Z")

        response = _post(shop, [6.343, 6.35, 6.35, 6.35])
        error = validate_error(response, ApiErrorId.ERR_GAUGE_NOT_IN_SERVICE.value)
        assert error["error_id"] != ApiErrorId.ERR_SUBGROUP_SIZE_MISMATCH.value

    def test_refused_subgroup_leaves_the_gauge_due_and_the_job_pending(self):
        """PRD 3.8: "Whenever a gauge is read, and whenever a subgroup post names
        it, the system re-evaluates lazily: a gauge that is `IN_SERVICE` and whose
        `calibration_due_at` is at or before the logical clock moves `IN_SERVICE →
        CALIBRATION_DUE`, and from that moment it no longer satisfies the
        in-service check that guards measurement."
        PRD 2.8: "`quality_status` is the quality dimension and takes one of
        `PENDING_INSPECTION`, `IN_SPC`, `QUALITY_HOLD`, `ACCEPTED` or `REJECTED`,
        beginning at `PENDING_INSPECTION` and terminating at `ACCEPTED` or
        `REJECTED`."

        Design: Difficulty/priority_pair_validation_conflict/gauge_out_of_service_beats_subgroup_size
        """
        shop = setup_running_work_order(
            gauge_overrides={"calibration_due_at": "2026-09-05T00:00:00Z"}
        )
        set_clock("2026-09-06T00:00:00Z")
        _post(shop, [6.343, 6.35, 6.35, 6.35])

        assert read_gauge(shop.gauge_id)["status"] == "CALIBRATION_DUE"
        assert read_work_order(shop.work_order_id)["quality_status"] == "PENDING_INSPECTION"


class TestCapabilityBoundary:
    """The acceptance boundary sits exactly on equality."""

    def test_subgroup_exactly_at_cpk_min_is_accepted(self):
        """PRD 3.8: "When no measurement is out of spec, it is `MARGINAL` if
        `cpk_short_term` is strictly less than the characteristic's `cpk_min`, and
        `ACCEPT` if `cpk_short_term` is greater than or equal to `cpk_min` — the
        boundary is inclusive, so a subgroup landing exactly on the minimum is
        accepted."
        PRD 3.8: "A subgroup dispositioned `ACCEPT` posted against a work order in
        `PENDING_INSPECTION` moves it `PENDING_INSPECTION → IN_SPC`, and nothing
        else in the system is touched — `machining_status` is left exactly as it
        was."

        Design: Difficulty/boundary_precision_check/cpk_exactly_at_cpk_min_is_accept
        """
        shop = setup_running_work_order()

        sample = validate_success(_post(shop, MEASUREMENTS_AT_CPK_MIN, piece_index=100), 201)
        assert sample["cpk_short_term"] == 1.385
        assert sample["disposition"] == "ACCEPT"
        assert read_work_order(shop.work_order_id)["quality_status"] == "IN_SPC"

    def test_subgroup_just_below_cpk_min_is_marginal_and_holds_the_job(self):
        """PRD 3.8: "A subgroup dispositioned `MARGINAL` or `REJECT` moves the
        work order `PENDING_INSPECTION → QUALITY_HOLD` if it was pending, or
        `IN_SPC → QUALITY_HOLD` if a study was already open."
        PRD 3.8: "A `MARGINAL` disposition does not touch the machine."

        Design: Difficulty/boundary_precision_check/cpk_exactly_at_cpk_min_is_accept
        """
        shop = setup_running_work_order()
        validate_success(_post(shop, MEASUREMENTS_AT_CPK_MIN, piece_index=100), 201)

        marginal = validate_success(_post(shop, MEASUREMENTS_BELOW_CPK_MIN, piece_index=200), 201)
        assert marginal["cpk_short_term"] == 1.292
        assert marginal["disposition"] == "MARGINAL"
        assert read_work_order(shop.work_order_id)["quality_status"] == "QUALITY_HOLD"


class TestGaugeInServiceGate:
    """The instrument, not the reading, decides whether a post is admitted."""

    def test_subgroup_refused_when_the_calibration_window_has_lapsed(self):
        """PRD 2.10: "A gauge may only be used when it is in service, which means
        both that its calibration window has not lapsed against the logical clock
        and that its most recent gauge R&R study came in at or below the acceptable
        percentage of tolerance."
        PRD 3.8: "First the gauge must be `IN_SERVICE` after the lazy
        re-evaluation above; a gauge that is `CALIBRATION_DUE`, `GRR_FAILED` or
        `RETIRED` is rejected with `ERR_GAUGE_NOT_IN_SERVICE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/spc_sample_blocked_by_gauge_calibration_due
        """
        shop = setup_running_work_order(
            gauge_overrides={"calibration_due_at": "2026-09-05T00:00:00Z"}
        )
        set_clock("2026-09-06T00:00:00Z")

        response = _post(shop, MEASUREMENTS_AT_CPK_MIN)
        validate_error(response, ApiErrorId.ERR_GAUGE_NOT_IN_SERVICE.value)

    def test_lapsed_gauge_reads_back_as_calibration_due(self):
        """PRD 3.8: "Calibration windows lapse on their own."
        PRD 2.4: "Advancing the clock does not itself rewrite any stored row; it
        changes the answer that later lazy re-evaluations give, most visibly for
        gauge calibration windows, blanket-order expiry and quote validity."

        Design: Difficulty/cross_entity_state_dependency/spc_sample_blocked_by_gauge_calibration_due
        """
        shop = setup_running_work_order(
            gauge_overrides={"calibration_due_at": "2026-09-05T00:00:00Z"}
        )
        assert read_gauge(shop.gauge_id)["status"] == "IN_SERVICE"

        set_clock("2026-09-06T00:00:00Z")
        _post(shop, MEASUREMENTS_AT_CPK_MIN)

        assert read_gauge(shop.gauge_id)["status"] == "CALIBRATION_DUE"
        assert read_work_order(shop.work_order_id)["quality_status"] == "PENDING_INSPECTION"


def test_calibration_posts_move_the_gauge_between_service_failure_and_retirement():
    """PRD 3.8: "The resulting state follows the posted study: when `grr_pct` is
    at most 10 percent and the posted `calibration_due_at` is strictly after the
    logical clock, the gauge returns to `IN_SERVICE` — the return edge that makes
    the gauge cyclic. When `grr_pct` is greater than 10 percent and at most 30
    percent, the gauge lands in `GRR_FAILED` and stops satisfying the in-service
    check. When `grr_pct` is greater than 30 percent, the gauge is moved to
    `RETIRED` permanently, and any later calibration post against a `RETIRED`
    gauge is rejected with `ERR_INVALID_STATE`."
    PRD 3.8: "The request supplies a fresh `calibrated_at`, a fresh
    `calibration_due_at` and the `grr_pct` from the new study; all three overwrite
    what was stored and `calibration_count` is increased by one on every post."

    Design: Corner/state_machines/gauge_grr_above_limit_moves_to_grr_failed_then_retired
    """
    set_clock()
    gauge = register_gauge()

    failed = validate_success(
        api_client.create_gauge_calibration(
            gauge["id"],
            {
                "calibrated_at": "2026-09-01T08:00:00Z",
                "calibration_due_at": "2027-03-01T00:00:00Z",
                "grr_pct": 18.0,
            },
            QUALITY,
        ),
        200,
    )
    assert failed["status"] == "GRR_FAILED"

    recovered = validate_success(
        api_client.create_gauge_calibration(
            gauge["id"],
            {
                "calibrated_at": "2026-09-01T09:00:00Z",
                "calibration_due_at": "2027-03-01T00:00:00Z",
                "grr_pct": 7.5,
            },
            QUALITY,
        ),
        200,
    )
    assert recovered["status"] == "IN_SERVICE"

    retired = validate_success(
        api_client.create_gauge_calibration(
            gauge["id"],
            {
                "calibrated_at": "2026-09-01T10:00:00Z",
                "calibration_due_at": "2027-03-01T00:00:00Z",
                "grr_pct": 42.0,
            },
            QUALITY,
        ),
        200,
    )
    assert retired["status"] == "RETIRED"
    assert retired["calibration_count"] == 3
    assert retired["grr_pct"] == 42.0


def test_subgroup_statistics_carry_their_declared_precision():
    """PRD 3.8: "The subgroup's `mean` is the arithmetic mean of the measured
    values, rounded half up to 4 decimal places. Its `range` is the largest
    measured value minus the smallest, likewise rounded half up to 4 decimal
    places."
    PRD 3.8: "`cpk_short_term` is then the lesser of two distances — the
    characteristic's `usl` minus the subgroup mean, and the subgroup mean minus the
    characteristic's `lsl` — divided by three times the within-subgroup sigma,
    rounded half up to 3 decimal places."

    Design: Corner/calculations/capability_precision_is_three_decimals_half_up
    """
    shop = setup_running_work_order()

    sample = validate_success(_post(shop, MEASUREMENTS_AT_CPK_MIN), 201)
    assert sample["mean"] == 6.35
    assert sample["range"] == 0.014
    assert sample["sigma_within"] == 0.006019
    assert sample["cpk_short_term"] == 1.385
    assert sample["cpk_short_term"] != 1.384


def test_long_term_index_pools_marginal_subgroups_instead_of_filtering_them():
    """PRD 3.8: "Every such subgroup is pooled in regardless of its own
    `disposition` — `MARGINAL` and `REJECT` subgroups are counted, not filtered out
    — while subgroups belonging to any other work order are excluded even when they
    measure the same characteristic."
    PRD 3.8: "An optional `characteristic_id` narrows the read to a single
    characteristic."

    Design: Corner/calculations/long_term_ppk_pools_marginal_subgroups_rather_than_filtering_them
    """
    shop = setup_running_work_order(characteristic_overrides={"sample_freq_pieces": 100})
    _post(shop, MEASUREMENTS_AT_CPK_MIN, piece_index=100)
    _post(shop, MEASUREMENTS_BELOW_CPK_MIN, piece_index=200)

    summary = validate_success(
        api_client.get_quality_summary(
            shop.work_order_id, QUALITY, {"characteristic_id": shop.characteristic_id}
        ),
        200,
    )
    assert summary["sample_count"] == 2
    assert summary["cpk_short_term_min"] == 1.292
    assert summary["ppk_long_term_min"] == 1.717
    assert summary["out_of_spec_count"] == 0
    assert read_work_order(shop.work_order_id)["quality_status"] == "QUALITY_HOLD"


def test_the_operator_who_ran_the_job_may_not_measure_it():
    """PRD 2.10: "Concretely, the `Inspector` whose `X-User-ID` accompanies a
    subgroup post must differ from the `machinist_operator_id` recorded on the work
    order being measured; when they are the same operator, the post is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD 3.8: "The subgroup's `inspector_operator_id` is taken from `X-User-ID`."

    Design: Corner/validations/machinist_cannot_inspect_the_job_they_ran
    """
    shop = setup_running_work_order()

    refused = _post(shop, MEASUREMENTS_AT_CPK_MIN, inspector=shop.machinist_id)
    validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    admitted = validate_success(_post(shop, MEASUREMENTS_AT_CPK_MIN), 201)
    assert admitted["inspector_operator_id"] == shop.inspector_id
    assert read_work_order(shop.work_order_id)["quality_status"] == "IN_SPC"


def test_subgroup_with_the_wrong_number_of_readings_is_refused():
    """PRD 3.8: "Third, the length of the `measurements` array must equal the
    characteristic's `subgroup_size`; a mismatch is rejected with
    `ERR_SUBGROUP_SIZE_MISMATCH` (HTTP 422)."
    PRD 3.1: "and `subgroup_size`, the number of measurements every subgroup for
    this characteristic must contain, defaults to 5 and must be either 3 or 5."

    Design: Corner/errors/subgroup_size_mismatch_on_an_in_service_gauge
    """
    shop = setup_running_work_order()

    response = _post(shop, [6.343, 6.35, 6.357])
    validate_error(response, ApiErrorId.ERR_SUBGROUP_SIZE_MISMATCH.value)
    assert read_work_order(shop.work_order_id)["quality_status"] == "PENDING_INSPECTION"


def test_characteristic_and_gauge_must_both_belong_to_the_measured_job():
    """PRD 3.8: "Fourth, the characteristic's `part_id` must equal the work
    order's `part_id`, failing which the post is rejected with
    `ERR_CHARACTERISTIC_PART_MISMATCH` (HTTP 422); and last, the gauge's
    `gauge_type` must equal the characteristic's `required_gauge_type`, failing
    which it is rejected with `ERR_GAUGE_TYPE_MISMATCH` (HTTP 422)."

    Design: Corner/errors/characteristic_part_mismatch_and_gauge_type_mismatch
    """
    shop = setup_running_work_order()
    other_part = register_second_part()
    foreign_characteristic = add_characteristic(other_part["id"], char_code="ID-C")
    bore_gauge = register_gauge(gauge_code="BG-14", gauge_type="BORE_GAUGE")

    wrong_part = _post(
        shop, MEASUREMENTS_AT_CPK_MIN, characteristic_id=foreign_characteristic["id"]
    )
    validate_error(wrong_part, ApiErrorId.ERR_CHARACTERISTIC_PART_MISMATCH.value)

    wrong_gauge = _post(shop, MEASUREMENTS_AT_CPK_MIN, gauge_id=bore_gauge["id"])
    validate_error(wrong_gauge, ApiErrorId.ERR_GAUGE_TYPE_MISMATCH.value)

    assert read_work_order(shop.work_order_id)["quality_status"] == "PENDING_INSPECTION"


def test_a_measured_subgroup_carries_neither_updated_at_nor_version():
    """PRD 2.4: "The single exception is `SpcSample`: a measured subgroup is an
    immutable observation, so it carries only `id` and `created_at` — it has no
    `updated_at` field and no `version` field at all, and neither key appears in its
    representation."

    Design: Corner/entities/spc_sample_is_immutable_and_carries_no_version
    """
    shop = setup_running_work_order()
    posted = post_subgroup(
        shop.work_order_id, shop.characteristic_id, shop.gauge_id, shop.inspector_id
    )

    stored = validate_success(
        api_client.get_spc_sample(posted["id"], make_inspector_headers(shop.inspector_id)), 200
    )
    assert stored["mean"] == 6.35
    assert stored["disposition"] == "ACCEPT"
    assert "id" in stored and "created_at" in stored
    assert "updated_at" not in stored
    assert "version" not in stored
