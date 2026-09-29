"""Two contended resources under opposite interval conventions.

A press line's occupancy is closed on both ends and widened by a changeover
buffer; an entry facility's induction windows are half-open and measured as an
aggregate over already-manifested trays.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import POSTAGE_CONTROLLER_2, PRODUCTION_SCHEDULER


class TestPressWindowsAreClosedWithABuffer:
    """One incumbent run, a thirty-minute buffer and three two-sheet jobs on one
    line."""

    @staticmethod
    def _pressweald_three_jobs(api: ApiClient):
        fx.set_clock(api)
        client = fx.register_client(
            api,
            client_code="CLPW",
            name="Pressweald Mutual",
            dr_readiness_required=False,
        )
        template = fx.create_active_template(
            api,
            client["id"],
            template_code="T-PW",
            sheets_per_document=1,
            mail_class_preference="FIRST_CLASS",
        )
        line = fx.register_press_line(
            api,
            line_code="PL-PW",
            capabilities=["DUPLEX", "COLOR", "INSERT"],
            sheets_per_hour=600,
            daily_sheet_capacity=9000,
            changeover_buffer_minutes=30,
        )

        def _job(file_name, refs, postal_code, plus4s):
            bundle = fx.accepted_file(
                api,
                client["id"],
                [
                    fx.record_spec(
                        refs[0],
                        1,
                        10000,
                        address_line1=f"{refs[0][-1]} Pressweald Road",
                        postal_code=postal_code,
                        postal_code_plus4=plus4s[0],
                    ),
                    fx.record_spec(
                        refs[1],
                        2,
                        10000,
                        address_line1=f"{refs[1][-1]} Pressweald Road",
                        postal_code=postal_code,
                        postal_code_plus4=plus4s[1],
                    ),
                ],
                file_name=file_name,
                declared_record_count=2,
                declared_control_total_cents=20000,
            )
            job = fx.compose_job(api, bundle.id, template["id"])
            return fx.presort_job(api, job["id"])

        one = _job("pw-one.csv", ("ACC2001", "ACC2002"), "30301", ("1001", "1002"))
        two = _job("pw-two.csv", ("ACC2003", "ACC2004"), "30302", ("1003", "1004"))
        three = _job("pw-three.csv", ("ACC2005", "ACC2006"), "30303", ("1005", "1006"))
        run_one = fx.schedule_job(api, one["id"], "2026-08-04T09:00:00Z", line["id"])
        return line, (one, two, three), run_one

    @staticmethod
    def _schedule(api: ApiClient, job, line, window_start: str):
        return api.schedule_job(
            job["id"],
            f.schedule_payload(window_start, line["id"]),
            PRODUCTION_SCHEDULER,
        )

    def test_a_window_touching_the_buffer_from_the_left_conflicts(
        self, api: ApiClient
    ):
        """PRD §3.6: "Writing the line's `changeover_buffer_minutes` as the buffer, the
        requested run conflicts with an existing run when **both** of these hold: the
        requested `window_start` is at or before the existing run's `window_end`
        advanced by the buffer, **and** the existing run's `window_start` is at or
        before the requested `window_end` advanced by the buffer."

        A request ending at half past eight is refused against an incumbent that
        starts at nine, because the incumbent's start falls exactly on the requested
        end advanced by the buffer and that comparison is closed.

        Design: Difficulty/resource_temporal_overlap/press_line_windows_use_closed_intervals_with_a_changeover_buffer
        """
        line, (_one, two, _three), run_one = self._pressweald_three_jobs(api)

        assert run_one["status"] == "PLANNED"
        assert run_one["run_minutes"] == a.expected_run_minutes(2, 600) == 60
        a.assert_instant(
            run_one["window_end"], "2026-08-04T10:00:00Z", "run_one.window_end"
        )

        response = self._schedule(api, two, line, "2026-08-04T07:30:00Z")
        validate_error(response, ApiErrorId.PRESS_WINDOW_CONFLICT.value, 409)
        assert fx.list_runs(api, composition_job_id=two["id"]) == []

    def test_one_minute_earlier_clears_the_buffer_on_the_left(self, api: ApiClient):
        """PRD §3.6: "The `changeover_buffer_minutes` field records the mandatory
        make-ready gap enforced on **both** sides of every scheduled window; it defaults
        to 30 minutes and is bounded to the inclusive range from 0 to 480 minutes."

        Shifting the same request one minute earlier ends the window at 08:29, so
        the incumbent's nine o'clock start no longer falls inside the buffered span
        and the booking is taken.

        Design: Difficulty/resource_temporal_overlap/press_line_windows_use_closed_intervals_with_a_changeover_buffer
        """
        line, (_one, two, _three), _run_one = self._pressweald_three_jobs(api)
        validate_error(
            self._schedule(api, two, line, "2026-08-04T07:30:00Z"),
            ApiErrorId.PRESS_WINDOW_CONFLICT.value,
            409,
        )

        run_two = get_success_data(
            self._schedule(api, two, line, "2026-08-04T07:29:00Z")
        )
        a.assert_instant(
            run_two["window_start"], "2026-08-04T07:29:00Z", "run_two.window_start"
        )
        a.assert_instant(
            run_two["window_end"], "2026-08-04T08:29:00Z", "run_two.window_end"
        )
        assert run_two["status"] == "PLANNED"

        reread = fx.read_press_line(api, line["id"])
        assert reread["committed_sheet_count"] == 4
        assert reread["utilization_bp"] == 4
        a.assert_press_ledger(reread)
        assert len(fx.list_runs(api, composition_job_id=two["id"])) == 1

    def test_a_completed_run_stops_contending_for_its_window(self, api: ApiClient):
        """PRD §3.6: "Because the run has left the planned-or-running set, the line's
        `committed_sheet_count` is reduced by `planned_sheet_count`, `utilization_bp` is
        recomputed and the line's `version` is incremented by 1."

        Only planned and running runs occupy a line, so once the incumbent
        completes it releases both its committed sheets and its window, and a third
        job books that exact window.

        Design: Difficulty/resource_temporal_overlap/press_line_windows_use_closed_intervals_with_a_changeover_buffer
        """
        line, (_one, two, three), run_one = self._pressweald_three_jobs(api)
        get_success_data(self._schedule(api, two, line, "2026-08-04T07:29:00Z"))

        fx.set_clock(api, "2026-08-04T09:00:00Z")
        fx.start_run(api, run_one["id"])
        completed = fx.complete_run(api, run_one["id"])
        assert completed["status"] == "COMPLETED"
        assert fx.read_press_line(api, line["id"])["committed_sheet_count"] == 2

        run_three = get_success_data(
            self._schedule(api, three, line, "2026-08-04T09:00:00Z")
        )
        assert run_three["status"] == "PLANNED"
        a.assert_instant(
            run_three["window_start"], "2026-08-04T09:00:00Z", "run_three.window_start"
        )
        a.assert_instant(
            run_three["window_end"], "2026-08-04T10:00:00Z", "run_three.window_end"
        )

    def test_the_line_ends_with_three_runs_and_two_live_reservations(
        self, api: ApiClient
    ):
        """PRD §3.6: "Scheduling then cascades onto the line: `committed_sheet_count` is
        increased by `planned_sheet_count`, `utilization_bp` is recomputed as
        `committed_sheet_count` multiplied by 10,000 and divided by
        `daily_sheet_capacity`, and the line's `version` is incremented by 1."

        The refused attempt left no row behind, and only the two runs still in the
        planned-or-running set hold sheets on the line.

        Design: Difficulty/resource_temporal_overlap/press_line_windows_use_closed_intervals_with_a_changeover_buffer
        """
        line, (_one, two, three), run_one = self._pressweald_three_jobs(api)
        validate_error(
            self._schedule(api, two, line, "2026-08-04T07:30:00Z"),
            ApiErrorId.PRESS_WINDOW_CONFLICT.value,
            409,
        )
        get_success_data(self._schedule(api, two, line, "2026-08-04T07:29:00Z"))
        fx.set_clock(api, "2026-08-04T09:00:00Z")
        fx.start_run(api, run_one["id"])
        fx.complete_run(api, run_one["id"])
        get_success_data(self._schedule(api, three, line, "2026-08-04T09:00:00Z"))

        runs = fx.list_runs(api, press_line_id=line["id"])
        assert len(runs) == 3
        statuses = sorted(run["status"] for run in runs)
        assert statuses == ["COMPLETED", "PLANNED", "PLANNED"]

        reread = fx.read_press_line(api, line["id"])
        assert reread["committed_sheet_count"] == 4
        a.assert_press_ledger(reread)


class TestInductionWindowsAreHalfOpen:
    """One job yielding two single-tray batches against a dock that can absorb one
    tray per window."""

    FIRST_WINDOW = ("2026-08-06T08:00:00Z", "2026-08-06T12:00:00Z")
    OVERLAPPING_WINDOW = ("2026-08-06T11:00:00Z", "2026-08-06T13:00:00Z")
    TOUCHING_WINDOW = ("2026-08-06T12:00:00Z", "2026-08-06T14:00:00Z")

    @staticmethod
    def _inductor_sealed(api: ApiClient):
        pipeline = fx.build_pipeline(
            api,
            stage="sealed",
            fund_cents=100000,
            client_code="CLIN",
            client_overrides={"name": "Inductor Savings Bank"},
            template_code="T-IN",
            template_overrides={
                "sheets_per_document": 1,
                "mail_class_preference": "FIRST_CLASS",
            },
            press_line_code="PL-IN",
            press_line_overrides={
                "sheets_per_hour": 600,
                "daily_sheet_capacity": 9000,
                "changeover_buffer_minutes": 30,
            },
            with_facility=True,
            facility_code="EF-IN",
            facility_overrides={
                "facility_type": "SCF",
                "tray_capacity_per_window": 1,
                "discount_bp_first_class": 850,
                "discount_bp_marketing": 1200,
            },
            file_name="in-cycle-01.csv",
            file_overrides={
                "declared_record_count": 2,
                "declared_control_total_cents": 32000,
            },
            specs=[
                fx.record_spec(
                    "ACC2101",
                    1,
                    16000,
                    address_line1="120 Inductor Plaza",
                    city="New York",
                    region_code="NY",
                    postal_code="10001",
                    postal_code_plus4="2201",
                ),
                fx.record_spec(
                    "ACC2102",
                    2,
                    16000,
                    address_line1="N/A",
                    city="New York",
                    region_code="NY",
                    postal_code="10002",
                    postal_code_plus4=None,
                ),
            ],
        )
        by_bucket = {batch["presort_bucket"]: batch for batch in pipeline.batches}
        return pipeline, by_bucket["MIXED_AADC"], by_bucket["NONMACHINABLE"]

    def _manifest(self, api: ApiClient, batch_id: str, facility_id: str, window):
        return api.manifest_batch(
            batch_id,
            f.manifest_payload(facility_id, window[0], window[1]),
            POSTAGE_CONTROLLER_2,
        )

    def test_one_job_yields_two_single_tray_batches(self, api: ApiClient):
        """PRD §3.5: "Every piece still `PENDING` after that final grouping is assigned
        `MIXED_AADC` — the catch-all, and the most expensive machinable bucket."

        The unscorable address is stamped undeliverable and screened into the
        non-machinable bucket while its deliverable sibling falls through to the
        catch-all, so the job presents two trays to the dock rather than one.

        Design: Difficulty/resource_temporal_overlap/entry_facility_induction_windows_are_half_open_with_aggregate_tray_capacity
        """
        pipeline, batch_a, batch_b = self._inductor_sealed(api)

        records = fx.file_records(api, pipeline.file_id)
        by_ref = {record["account_ref"]: record for record in records}
        assert by_ref["ACC2101"]["hygiene_confidence"] == 1.00
        assert by_ref["ACC2101"]["hygiene_status"] == "DELIVERABLE"
        assert by_ref["ACC2102"]["hygiene_confidence"] == 0.47
        assert by_ref["ACC2102"]["hygiene_status"] == "UNDELIVERABLE_AS_ADDRESSED"

        for batch in (batch_a, batch_b):
            assert batch["piece_count"] == 1
            assert batch["tray_count"] == a.expected_tray_count(1) == 1
            assert batch["status"] == "SEALED"
        assert batch_a["estimated_postage_cents"] == 62
        assert batch_b["estimated_postage_cents"] == 88

        client = pipeline.refresh_client()
        assert client["postage_committed_cents"] == 150
        assert client["postage_escrow_available_cents"] == 99850

    def test_the_first_manifest_takes_the_only_tray_of_capacity(self, api: ApiClient):
        """PRD §3.8: "Second, the discount is applied **per piece** — a piece's net postage
        is its gross postage multiplied by the quantity ten thousand minus the
        applicable discount in basis points, divided by 10,000, and rounded half up to
        whole cents."

        The first batch is discounted per piece at the facility's first-class rate
        and its single tray is added to the dock's running commitment.

        Design: Difficulty/resource_temporal_overlap/entry_facility_induction_windows_are_half_open_with_aggregate_tray_capacity
        """
        pipeline, batch_a, _batch_b = self._inductor_sealed(api)

        manifested = get_success_data(
            self._manifest(
                api, batch_a["id"], pipeline.facility["id"], self.FIRST_WINDOW
            )
        )
        assert manifested["status"] == "MANIFESTED"
        assert manifested["manifested_postage_cents"] == (
            a.expected_net_postage_cents(62, 850)
        ) == 57
        assert manifested["postage_variance_cents"] == -5
        assert pipeline.refresh_facility()["committed_tray_count"] == 1

    def test_a_genuinely_overlapping_window_is_refused(self, api: ApiClient):
        """PRD §3.8: "The batch's own `tray_count`, added to the `tray_count` of every
        already-`MANIFESTED` batch at that same facility whose half-open induction
        window intersects the requested window, must not exceed the facility's
        `tray_capacity_per_window`; exceeding it is refused with
        `ERR_INDUCTION_CAPACITY_EXCEEDED` (HTTP 409)."

        The second batch's tray plus the already-manifested tray exceed the dock's
        ceiling of one across the hour the two windows share, and the refusal leaves
        the batch and the dock untouched.

        Design: Difficulty/resource_temporal_overlap/entry_facility_induction_windows_are_half_open_with_aggregate_tray_capacity
        """
        pipeline, batch_a, batch_b = self._inductor_sealed(api)
        get_success_data(
            self._manifest(
                api, batch_a["id"], pipeline.facility["id"], self.FIRST_WINDOW
            )
        )

        response = self._manifest(
            api, batch_b["id"], pipeline.facility["id"], self.OVERLAPPING_WINDOW
        )
        validate_error(response, ApiErrorId.INDUCTION_CAPACITY_EXCEEDED.value, 409)

        reread = fx.read_batch(api, batch_b["id"])
        assert reread["status"] == "SEALED"
        assert reread["entry_facility_id"] is None
        assert reread["induction_window_start"] is None
        assert reread["manifested_postage_cents"] is None
        assert reread["postage_variance_cents"] is None
        assert pipeline.refresh_facility()["committed_tray_count"] == 1

    def test_windows_that_merely_touch_do_not_compete(self, api: ApiClient):
        """PRD §3.8: "Because the windows are half-open, a batch whose window ends exactly
        when another's begins does not intersect it and the two do not compete for the
        same tray capacity."

        Starting exactly when the first window ends does not intersect it under the
        half-open convention, so the second tray is accepted, the dock's commitment
        becomes a sum of two and the job follows its batches to manifested.

        Design: Difficulty/resource_temporal_overlap/entry_facility_induction_windows_are_half_open_with_aggregate_tray_capacity
        """
        pipeline, batch_a, batch_b = self._inductor_sealed(api)
        get_success_data(
            self._manifest(
                api, batch_a["id"], pipeline.facility["id"], self.FIRST_WINDOW
            )
        )
        validate_error(
            self._manifest(
                api, batch_b["id"], pipeline.facility["id"], self.OVERLAPPING_WINDOW
            ),
            ApiErrorId.INDUCTION_CAPACITY_EXCEEDED.value,
            409,
        )

        manifested = get_success_data(
            self._manifest(
                api, batch_b["id"], pipeline.facility["id"], self.TOUCHING_WINDOW
            )
        )
        assert manifested["status"] == "MANIFESTED"
        assert manifested["manifested_postage_cents"] == (
            a.expected_net_postage_cents(88, 850)
        ) == 81
        assert manifested["postage_variance_cents"] == -7

        assert pipeline.refresh_facility()["committed_tray_count"] == 2
        assert pipeline.refresh_job()["status"] == "MANIFESTED"
        client = pipeline.refresh_client()
        assert client["postage_committed_cents"] == 138
        assert client["postage_escrow_available_cents"] == 99862
        a.assert_escrow_ledger(client)
