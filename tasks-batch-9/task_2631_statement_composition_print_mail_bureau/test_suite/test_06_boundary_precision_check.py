"""Thresholds probed one unit either side of the edge.

Three different metrics — rounded basis points of control-total drift, whole
minutes of press-line clock time and sheets per piece — each tested at the exact
boundary and one unit past it.
"""

import pytest

from prd_bench_local_runner.testing import validate_error

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import PRODUCTION_SCHEDULER


class TestControlToleranceEdge:
    """Two files whose variances differ by a single cent across the tolerance."""

    @staticmethod
    def _tolerance_edge_files(api: ApiClient):
        fx.set_clock(api)
        client = fx.register_client(
            api,
            client_code="CLTE",
            name="Tolerance Edge Bancorp",
            dr_readiness_required=False,
            control_total_tolerance_bp=5,
        )

        def _file(name, refs, over_cents, plus4s):
            bundle = fx.lodged_file(
                api,
                client["id"],
                [
                    fx.record_spec(
                        refs[0],
                        1,
                        180000,
                        address_line1="1 Tolerance Way",
                        city="Boise",
                        region_code="ID",
                        postal_code="83702",
                        postal_code_plus4=plus4s[0],
                    ),
                    fx.record_spec(
                        refs[1],
                        2,
                        180000 + over_cents,
                        address_line1="2 Tolerance Way",
                        city="Boise",
                        region_code="ID",
                        postal_code="83702",
                        postal_code_plus4=plus4s[1],
                    ),
                ],
                file_name=name,
                declared_record_count=2,
                declared_control_total_cents=360000,
            )
            fx.validate_file_format(api, bundle.id)
            return bundle

        accepting = _file("te-edge-accept.csv", ("ACC1401", "ACC1402"), 197, ("3301", "3302"))
        holding = _file("te-edge-hold.csv", ("ACC1403", "ACC1404"), 198, ("3303", "3304"))
        return client, accepting, holding

    def test_a_variance_rounding_to_the_exact_tolerance_is_accepted(
        self, api: ApiClient
    ):
        """PRD §3.3: "The file advances `FORMAT_VALIDATED` → `ACCEPTED` when, and only
        when, `record_count_variance` is exactly 0 **and** `control_total_variance_bp`
        is less than or equal to the client's tolerance; the comparison against
        tolerance is inclusive, so a variance sitting exactly on the tolerance passes."

        A 197-cent drift on a 360,000-cent declaration rounds to five basis points
        and passes, because the comparison against the client's tolerance is
        inclusive on its lower edge.

        Design: Difficulty/boundary_precision_check/control_total_variance_bp_at_the_exact_client_tolerance_edge
        """
        _client, accepting, _holding = self._tolerance_edge_files(api)

        checked = fx.run_control_check(api, accepting.id)

        assert checked["actual_control_total_cents"] == 360197
        assert checked["control_total_variance_cents"] == 197
        assert checked["record_count_variance"] == 0
        assert checked["control_total_variance_bp"] == 5
        assert a.expected_variance_bp(360000, 360197) == 5
        assert checked["status"] == "ACCEPTED"
        a.assert_instant(
            checked["accepted_at"], "2026-08-01T00:00:00Z", "file.accepted_at"
        )

    def test_one_cent_more_rounds_half_up_past_the_tolerance_and_holds(
        self, api: ApiClient
    ):
        """PRD §3.3: "In every other case the file goes `FORMAT_VALIDATED` →
        `HELD_VARIANCE` instead: the same five actual and variance figures are written,
        but `accepted_at` is left null."

        A 198-cent drift lands on exactly five and a half basis points, which
        rounds up rather than down and so exceeds the same tolerance the 197-cent
        file cleared.

        Design: Difficulty/boundary_precision_check/control_total_variance_bp_at_the_exact_client_tolerance_edge
        """
        _client, _accepting, holding = self._tolerance_edge_files(api)

        checked = fx.run_control_check(api, holding.id)

        assert checked["actual_control_total_cents"] == 360198
        assert checked["control_total_variance_cents"] == 198
        assert 198 * 10000 / 360000 == pytest.approx(5.5, abs=0.0001)
        assert checked["control_total_variance_bp"] == 6
        assert a.expected_variance_bp(360000, 360198) == 6
        assert checked["status"] == "HELD_VARIANCE"
        assert checked["accepted_at"] is None

    def test_the_single_cent_decides_the_fork_and_nothing_else(self, api: ApiClient):
        """PRD §3.3: "The fork is then decided against the owning client's own
        `control_total_tolerance_bp` — a per-client contract term, never a system-wide
        constant."

        The two files are identical apart from one cent of drift, and that cent is
        the whole difference between acceptance and a hold; neither file has been
        amended.

        Design: Difficulty/boundary_precision_check/control_total_variance_bp_at_the_exact_client_tolerance_edge
        """
        client, accepting, holding = self._tolerance_edge_files(api)

        first = fx.run_control_check(api, accepting.id)
        second = fx.run_control_check(api, holding.id)

        assert client["control_total_tolerance_bp"] == 5
        assert first["control_total_variance_bp"] <= 5
        assert second["control_total_variance_bp"] > 5
        assert second["control_total_variance_cents"] - first["control_total_variance_cents"] == 1
        assert first["status"] == "ACCEPTED"
        assert second["status"] == "HELD_VARIANCE"
        assert first["amendment_count"] == 0
        assert second["amendment_count"] == 0


class TestPressWindowChangeoverEdge:
    """One committed run and a second job probed at the buffer minute and the one
    after it."""

    @staticmethod
    def _eaglecrest_two_jobs(api: ApiClient):
        fx.set_clock(api)
        client = fx.register_client(
            api,
            client_code="CLEG",
            name="Eaglecrest Mutual",
            dr_readiness_required=False,
        )
        template = fx.create_active_template(
            api,
            client["id"],
            template_code="T-EG",
            sheets_per_document=1,
            duplex_required=False,
            color_pages_per_document=0,
        )
        line = fx.register_press_line(
            api,
            line_code="PL-EG",
            capabilities=["DUPLEX", "COLOR", "INSERT"],
            sheets_per_hour=600,
            daily_sheet_capacity=9000,
            changeover_buffer_minutes=30,
        )

        def _job(file_name, refs):
            bundle = fx.accepted_file(
                api,
                client["id"],
                [
                    fx.record_spec(refs[0], 1, 20000, postal_code="30301"),
                    fx.record_spec(refs[1], 2, 20000, postal_code="30301"),
                ],
                file_name=file_name,
                declared_record_count=2,
                declared_control_total_cents=40000,
            )
            job = fx.compose_job(api, bundle.id, template["id"])
            return fx.presort_job(api, job["id"])

        job_one = _job("eg-cycle-01.csv", ("ACC1501", "ACC1502"))
        job_two = _job("eg-cycle-02.csv", ("ACC1503", "ACC1504"))
        first_run = fx.schedule_job(
            api, job_one["id"], "2026-08-02T09:00:00Z", line["id"]
        )
        return client, line, job_two, first_run

    def test_a_start_on_the_buffer_minute_conflicts(self, api: ApiClient):
        """PRD §3.6: "Writing the line's `changeover_buffer_minutes` as the buffer, the
        requested run conflicts with an existing run when **both** of these hold: the
        requested `window_start` is at or before the existing run's `window_end`
        advanced by the buffer, **and** the existing run's `window_start` is at or
        before the requested `window_end` advanced by the buffer."

        The committed run ends at ten o'clock and the line carries a thirty-minute
        changeover buffer, so a request starting at exactly half past ten sits on the
        closed edge of the blocked interval and is refused.

        Design: Difficulty/boundary_precision_check/press_window_conflict_at_the_exact_changeover_buffer_edge
        """
        _client, line, job_two, first_run = self._eaglecrest_two_jobs(api)

        assert line["changeover_buffer_minutes"] == 30
        assert first_run["status"] == "PLANNED"
        assert first_run["run_minutes"] == a.expected_run_minutes(2, 600) == 60
        a.assert_instant(
            first_run["window_end"], "2026-08-02T10:00:00Z", "first_run.window_end"
        )

        response = api.schedule_job(
            job_two["id"],
            f.schedule_payload("2026-08-02T10:30:00Z", line["id"]),
            PRODUCTION_SCHEDULER,
        )
        validate_error(response, ApiErrorId.PRESS_WINDOW_CONFLICT.value, 409)

    def test_one_minute_past_the_buffer_is_scheduled(self, api: ApiClient):
        """PRD §3.6: "The `changeover_buffer_minutes` field records the mandatory
        make-ready gap enforced on **both** sides of every scheduled window; it defaults
        to 30 minutes and is bounded to the inclusive range from 0 to 480 minutes."

        A start one minute later clears the buffered interval, and the run it
        creates takes the named line without going through the selector.

        Design: Difficulty/boundary_precision_check/press_window_conflict_at_the_exact_changeover_buffer_edge
        """
        _client, line, job_two, _first_run = self._eaglecrest_two_jobs(api)

        second_run = fx.schedule_job(
            api, job_two["id"], "2026-08-02T10:31:00Z", line["id"]
        )

        assert second_run["press_line_id"] == line["id"]
        assert second_run["selection_mode"] == "EXPLICIT"
        assert second_run["selection_score"] == pytest.approx(
            a.expected_selection_score(9000 - 2, 600, 3), abs=0.01
        )
        assert second_run["planned_sheet_count"] == 2
        assert second_run["run_minutes"] == 60
        a.assert_instant(
            second_run["window_start"], "2026-08-02T10:31:00Z", "second_run.window_start"
        )
        a.assert_instant(
            second_run["window_end"], "2026-08-02T11:31:00Z", "second_run.window_end"
        )
        assert second_run["status"] == "PLANNED"
        assert fx.read_job(api, job_two["id"])["status"] == "SCHEDULED"

    def test_the_refused_minute_commits_nothing_to_the_line(self, api: ApiClient):
        """PRD §3.6: "A named line whose `committed_sheet_count` plus the run's
        `planned_sheet_count` would exceed its `daily_sheet_capacity` is refused with
        `ERR_PRESS_CAPACITY_EXCEEDED` (HTTP 409)."

        Only the accepted request adds to the line's committed sheets, so the line
        ends on the two runs' four sheets and one run row exists for the second job.

        Design: Difficulty/boundary_precision_check/press_window_conflict_at_the_exact_changeover_buffer_edge
        """
        _client, line, job_two, _first_run = self._eaglecrest_two_jobs(api)

        refused = api.schedule_job(
            job_two["id"],
            f.schedule_payload("2026-08-02T10:30:00Z", line["id"]),
            PRODUCTION_SCHEDULER,
        )
        validate_error(refused, ApiErrorId.PRESS_WINDOW_CONFLICT.value, 409)
        fx.schedule_job(api, job_two["id"], "2026-08-02T10:31:00Z", line["id"])

        reread = fx.read_press_line(api, line["id"])
        assert reread["committed_sheet_count"] == 4
        assert reread["utilization_bp"] == 4
        a.assert_press_ledger(reread)
        runs = fx.list_runs(api, composition_job_id=job_two["id"])
        assert len(runs) == 1


class TestMachinabilitySheetEdge:
    """Two jobs on one client whose per-piece sheet counts straddle the twelve-sheet
    screen."""

    @staticmethod
    def _mapleshade_two_jobs(api: ApiClient):
        fx.set_clock(api)
        client = fx.register_client(
            api,
            client_code="CLMS",
            name="Mapleshade Trust Bank",
            dr_readiness_required=False,
        )

        def _job(template_code, sheets, file_name, refs):
            template = fx.create_active_template(
                api,
                client["id"],
                template_code=template_code,
                sheets_per_document=sheets,
                duplex_required=False,
                color_pages_per_document=0,
                mail_class_preference="FIRST_CLASS",
            )
            bundle = fx.accepted_file(
                api,
                client["id"],
                [
                    fx.record_spec(refs[0], 1, 25000, postal_code="30301"),
                    fx.record_spec(refs[1], 2, 25000, postal_code="30301"),
                ],
                file_name=file_name,
                declared_record_count=2,
                declared_control_total_cents=50000,
            )
            job = fx.compose_job(api, bundle.id, template["id"])
            return bundle, fx.presort_job(api, job["id"])

        twelve = _job("T-MS12", 12, "ms-twelve.csv", ("ACC1601", "ACC1602"))
        thirteen = _job("T-MS13", 13, "ms-thirteen.csv", ("ACC1603", "ACC1604"))
        return client, twelve, thirteen

    def test_twelve_sheets_survive_the_screen_and_reach_the_waterfall(
        self, api: ApiClient
    ):
        """PRD §3.5: "That residue is grouped by the first three characters of the backing
        record's `postal_code`, again in ascending key order, and any group holding at
        least 2 pieces is assigned `THREE_DIGIT`."

        Twelve sheets is not strictly greater than twelve, so the screen passes the
        pieces through to the grouping tiers, where the pair's shared postal prefix
        earns them the three-digit bucket.

        Design: Difficulty/boundary_precision_check/machinability_screen_at_the_exact_max_sheet_boundary
        """
        _client, (_bundle, job), _thirteen = self._mapleshade_two_jobs(api)

        assert job["print_sheet_count"] == 24
        assert job["total_sheet_count"] == 24
        pieces = fx.list_pieces(api, job["id"])
        assert len(pieces) == 2
        for piece in pieces:
            assert piece["sheet_count"] == 12
            assert piece["presort_bucket"] == "THREE_DIGIT"
            assert piece["mail_class"] == "FIRST_CLASS"

        batches = fx.list_batches(api, job["id"])
        assert len(batches) == 1
        assert batches[0]["presort_bucket"] == "THREE_DIGIT"
        assert batches[0]["mail_class"] == "FIRST_CLASS"
        assert batches[0]["piece_count"] == 2
        assert batches[0]["tray_count"] == 1
        assert batches[0]["status"] == "OPEN"

    def test_thirteen_sheets_are_screened_out_before_any_grouping(
        self, api: ApiClient
    ):
        """PRD §3.5: "A candidate whose backing record has `hygiene_status` of either
        `UNDELIVERABLE_AS_ADDRESSED` or `STALE`, or whose `sheet_count` is strictly
        greater than 12 sheets, is assigned `presort_bucket` `NONMACHINABLE` immediately
        and takes no further part in the waterfall."

        One sheet more clears the strict comparison, so both pieces are stamped
        non-machinable outright and never reach the tier that gave their twelve-sheet
        counterparts a three-digit bucket.

        Design: Difficulty/boundary_precision_check/machinability_screen_at_the_exact_max_sheet_boundary
        """
        _client, _twelve, (_bundle, job) = self._mapleshade_two_jobs(api)

        assert job["print_sheet_count"] == 26
        pieces = fx.list_pieces(api, job["id"])
        assert len(pieces) == 2
        for piece in pieces:
            assert piece["sheet_count"] == 13
            assert piece["presort_bucket"] == "NONMACHINABLE"

        batches = fx.list_batches(api, job["id"])
        assert len(batches) == 1
        assert batches[0]["presort_bucket"] == "NONMACHINABLE"
        assert batches[0]["piece_count"] == 2
        assert batches[0]["tray_count"] == 1

    def test_the_screen_reads_sheets_and_not_address_quality(self, api: ApiClient):
        """PRD §3.5: "A candidate whose backing record has `hygiene_status` of either
        `UNDELIVERABLE_AS_ADDRESSED` or `STALE`, or whose `sheet_count` is strictly
        greater than 12 sheets, is assigned `presort_bucket` `NONMACHINABLE` immediately
        and takes no further part in the waterfall."

        The screened-out pieces sit on fully deliverable addresses, so sheet count
        alone accounts for the difference between the two jobs' buckets.

        Design: Difficulty/boundary_precision_check/machinability_screen_at_the_exact_max_sheet_boundary
        """
        _client, (twelve_bundle, twelve_job), (thirteen_bundle, thirteen_job) = (
            self._mapleshade_two_jobs(api)
        )

        for bundle in (twelve_bundle, thirteen_bundle):
            for record in fx.file_records(api, bundle.id):
                assert record["hygiene_status"] == "DELIVERABLE"
                assert record["hygiene_confidence"] == pytest.approx(1.00, abs=0.01)

        twelve_buckets = {p["presort_bucket"] for p in fx.list_pieces(api, twelve_job["id"])}
        thirteen_buckets = {
            p["presort_bucket"] for p in fx.list_pieces(api, thirteen_job["id"])
        }
        assert twelve_buckets == {"THREE_DIGIT"}
        assert thirteen_buckets == {"NONMACHINABLE"}
