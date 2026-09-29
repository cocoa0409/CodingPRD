"""Requests that violate two rules at once, where only the higher-ranked rule
may answer.

Each pair is proved live by repairing the winning fault and re-issuing the same
request, which then surfaces the rule that was merely outranked.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    POSTAGE_CONTROLLER,
    POSTAGE_CONTROLLER_2,
    POSTAGE_USER_ID,
    PRODUCTION_SCHEDULER,
)

ES_RECORDS = [
    fx.record_spec(
        "ACC1101",
        1,
        25000,
        address_line1="8 Eastshore Parade",
        postal_code="30301",
        postal_code_plus4="9901",
    ),
    fx.record_spec(
        "ACC1102",
        2,
        25000,
        address_line1="9 Eastshore Parade",
        postal_code="30301",
        postal_code_plus4="9902",
    ),
]


class TestStaleVersionOutranksEscrowShortfall:
    """A seal that is simultaneously pinned to an old client snapshot and
    unfunded."""

    @staticmethod
    def _eastshore_verified(api: ApiClient):
        pipeline = fx.verified_job(
            api,
            client_code="CLES",
            client_overrides={"name": "Eastshore Insurance"},
            template_code="T-ES",
            template_overrides={
                "mail_class_preference": "FIRST_CLASS",
                "sheets_per_document": 1,
            },
            press_line_code="PL-ES",
            press_line_overrides={
                "sheets_per_hour": 600,
                "daily_sheet_capacity": 9000,
                "changeover_buffer_minutes": 30,
            },
            file_name="es-cycle-01.csv",
            specs=ES_RECORDS,
            window_start="2026-08-02T09:00:00Z",
            run_start_clock="2026-08-02T09:00:00Z",
            run_complete_clock=None,
        )
        stale_version = pipeline.refresh_client()["version"]
        fresh = fx.patch_client(api, pipeline.client_id, name="Eastshore Insurance Group")
        assert fresh["version"] != stale_version
        return pipeline, stale_version, fresh["version"]

    def test_the_stale_version_answers_before_the_wallet(self, api: ApiClient):
        """PRD §3.8: "The request carries `expected_client_version`, and a stale value is
        rejected as described in §2.7 before the money is examined."

        Both faults are live — the pinned version is out of date and the escrow
        cannot cover the 112 cents this batch would commit — and the version check
        is the one that speaks.

        Design: Difficulty/priority_pair_validation_conflict/stale_client_version_outranks_postage_escrow_shortfall
        """
        pipeline, stale_version, _fresh_version = self._eastshore_verified(api)
        client = pipeline.refresh_client()
        assert client["postage_escrow_available_cents"] == 0
        assert a.expected_gross_postage_cents("FIRST_CLASS", "THREE_DIGIT", 1) == 56
        batch = pipeline.batch
        assert batch["mail_class"] == "FIRST_CLASS"
        assert batch["presort_bucket"] == "THREE_DIGIT"
        assert batch["piece_count"] == 2

        response = api.seal_batch(
            batch["id"], f.seal_payload(stale_version), POSTAGE_CONTROLLER
        )

        validate_error(response, ApiErrorId.STALE_CLIENT_VERSION.value, 412)

    def test_the_wallet_answers_once_the_version_is_current(self, api: ApiClient):
        """PRD §3.8: "The client's escrow must cover that figure: if
        `postage_escrow_available_cents` is less than the computed
        `estimated_postage_cents` the seal is refused with
        `ERR_POSTAGE_ESCROW_INSUFFICIENT` (HTTP 402), and the comparison is inclusive,
        so an escrow exactly equal to the estimate is sufficient."

        Re-issuing the same seal against the current client snapshot surfaces the
        funding verdict, which proves the escrow rule was live throughout and merely
        outranked.

        Design: Difficulty/priority_pair_validation_conflict/stale_client_version_outranks_postage_escrow_shortfall
        """
        pipeline, _stale_version, fresh_version = self._eastshore_verified(api)

        response = api.seal_batch(
            pipeline.batch["id"], f.seal_payload(fresh_version), POSTAGE_CONTROLLER
        )

        validate_error(response, ApiErrorId.POSTAGE_ESCROW_INSUFFICIENT.value, 402)

    def test_neither_rejection_moves_the_batch_or_the_money(self, api: ApiClient):
        """PRD §3.8: "On success the batch moves `OPEN` → `SEALED`,
        `estimated_postage_cents` is persisted, `sealed_by_user_id` records the acting
        `X-User-ID`, and the batch's `version` is incremented by 1."

        After both refusals the batch is still open and unpriced and the client's
        escrow ledger has not been touched.

        Design: Difficulty/priority_pair_validation_conflict/stale_client_version_outranks_postage_escrow_shortfall
        """
        pipeline, stale_version, fresh_version = self._eastshore_verified(api)
        batch_id = pipeline.batch["id"]

        api.seal_batch(batch_id, f.seal_payload(stale_version), POSTAGE_CONTROLLER)
        api.seal_batch(batch_id, f.seal_payload(fresh_version), POSTAGE_CONTROLLER)

        batch = fx.read_batch(api, batch_id)
        assert batch["status"] == "OPEN"
        assert batch["estimated_postage_cents"] is None
        assert batch["sealed_by_user_id"] is None

        client = pipeline.refresh_client()
        assert client["postage_committed_cents"] == 0
        assert client["postage_escrow_available_cents"] == 0
        assert client["version"] == fresh_version
        a.assert_escrow_ledger(client)


DP_RECORDS = [
    fx.record_spec(
        "ACC1201",
        1,
        22000,
        address_line1="44 Deepwater Quay",
        postal_code="30301",
        postal_code_plus4="1101",
    ),
    fx.record_spec(
        "ACC1202",
        2,
        22000,
        address_line1="46 Deepwater Quay",
        postal_code="30301",
        postal_code_plus4="1102",
    ),
]


class TestDrReadinessOutranksPressCapacity:
    """A schedule request against an unready recovery site and an undersized
    line."""

    @staticmethod
    def _deepwater_presorted(api: ApiClient):
        fx.set_clock(api)
        site = fx.register_dr_site(api, site_code="DR-WEST", replication_lag_minutes=30)
        site = fx.record_drill(api, site["id"], "PASS")
        pipeline = fx.presorted_job(
            api,
            clock=None,
            client_code="CLDP",
            client_overrides={
                "name": "Deepwater Mortgage",
                "dr_readiness_required": True,
            },
            template_code="T-DP",
            template_overrides={
                "mail_class_preference": "FIRST_CLASS",
                "sheets_per_document": 1,
            },
            with_press_line=True,
            press_line_code="PL-DP",
            press_line_overrides={
                "sheets_per_hour": 600,
                "daily_sheet_capacity": 1,
                "changeover_buffer_minutes": 30,
            },
            file_name="dp-cycle-01.csv",
            specs=DP_RECORDS,
        )
        return pipeline, site

    @staticmethod
    def _schedule(api: ApiClient, pipeline):
        return api.schedule_job(
            pipeline.job_id,
            f.schedule_payload("2026-08-04T09:00:00Z", pipeline.press_line["id"]),
            PRODUCTION_SCHEDULER,
        )

    def test_the_recovery_gate_answers_before_the_press_ceiling(self, api: ApiClient):
        """PRD §3.6: "Before anything else about the press floor is considered,
        disaster-recovery posture is checked: when the owning client's
        `dr_readiness_required` is true, the single DR site must read `READY`, else
        `ERR_DR_SITE_NOT_READY`."

        A replication lag beyond the tolerated fifteen minutes leaves the site
        unready even though its drill is fresh, and that verdict is returned in
        preference to the line's sheet ceiling, which the job also breaks.

        Design: Difficulty/priority_pair_validation_conflict/dr_site_not_ready_outranks_press_capacity_exceeded
        """
        pipeline, site = self._deepwater_presorted(api)
        assert site["readiness_status"] == "STALE"
        a.assert_instant(
            site["readiness_valid_until"],
            "2026-08-31T00:00:00Z",
            "site.readiness_valid_until",
        )
        assert pipeline.client["dr_readiness_required"] is True
        assert pipeline.job["print_sheet_count"] == 2
        assert pipeline.press_line["daily_sheet_capacity"] == 1
        assert pipeline.press_line["committed_sheet_count"] == 0

        response = self._schedule(api, pipeline)

        validate_error(response, ApiErrorId.DR_SITE_NOT_READY.value, 409)

    def test_the_press_ceiling_answers_once_the_lag_is_repaired(self, api: ApiClient):
        """PRD §3.6: "A named line whose `committed_sheet_count` plus the run's
        `planned_sheet_count` would exceed its `daily_sheet_capacity` is refused with
        `ERR_PRESS_CAPACITY_EXCEEDED` (HTTP 409)."

        Readiness is recomputed on every read, so trimming the replication lag to
        five minutes makes the site ready at once and the same schedule request then
        surfaces the capacity verdict it had been hiding.

        Design: Difficulty/priority_pair_validation_conflict/dr_site_not_ready_outranks_press_capacity_exceeded
        """
        pipeline, site = self._deepwater_presorted(api)
        self._schedule(api, pipeline)

        repaired = fx.patch_dr_site(api, site["id"], replication_lag_minutes=5)
        assert repaired["readiness_status"] == "READY"

        response = self._schedule(api, pipeline)

        validate_error(response, ApiErrorId.PRESS_CAPACITY_EXCEEDED.value, 409)

    def test_neither_rejection_reserves_press_capacity(self, api: ApiClient):
        """PRD §2.11: "From there the disposition is decided by the first matching
        condition: if `last_drill_result` is `FAIL`, readiness is `FAILED`; otherwise,
        if the logical clock is strictly later than `readiness_valid_until`, readiness
        is `STALE`; otherwise, if `replication_lag_minutes` is strictly greater than 15,
        readiness is `STALE`; otherwise readiness is `READY`."

        After both refusals no run exists, the line's ledger is untouched and the
        job is still waiting in its presorted state with no projected exposure.

        Design: Difficulty/priority_pair_validation_conflict/dr_site_not_ready_outranks_press_capacity_exceeded
        """
        pipeline, site = self._deepwater_presorted(api)
        self._schedule(api, pipeline)
        fx.patch_dr_site(api, site["id"], replication_lag_minutes=5)
        self._schedule(api, pipeline)

        job = pipeline.refresh_job()
        assert job["status"] == "PRESORTED"
        assert job["projected_completion_at"] is None

        line = pipeline.refresh_press_line()
        assert line["committed_sheet_count"] == 0
        assert line["utilization_bp"] == 0
        assert fx.list_runs(api, composition_job_id=pipeline.job_id) == []


BW_RECORDS = [
    fx.record_spec(
        "ACC1301",
        1,
        33000,
        address_line1="21 Bridgewater Mews",
        postal_code="30301",
        postal_code_plus4="2201",
    ),
    fx.record_spec(
        "ACC1302",
        2,
        33000,
        address_line1="23 Bridgewater Mews",
        postal_code="30301",
        postal_code_plus4="2202",
    ),
]

BW_ZERO_LENGTH_WINDOW = ("2026-08-05T08:00:00Z", "2026-08-05T08:00:00Z")


class TestBatchStateOutranksMalformedWindow:
    """A manifest carrying a zero-length window against a batch that was never
    sealed."""

    @staticmethod
    def _bridgewater_verified(api: ApiClient):
        return fx.verified_job(
            api,
            fund_cents=100000,
            client_code="CLBW",
            client_overrides={"name": "Bridgewater Health Plan"},
            template_code="T-BW",
            template_overrides={
                "mail_class_preference": "FIRST_CLASS",
                "sheets_per_document": 1,
            },
            press_line_code="PL-BW",
            press_line_overrides={
                "sheets_per_hour": 600,
                "daily_sheet_capacity": 9000,
                "changeover_buffer_minutes": 30,
            },
            with_facility=True,
            facility_code="EF-BW",
            facility_overrides={
                "facility_type": "SCF",
                "tray_capacity_per_window": 4,
                "discount_bp_first_class": 850,
                "discount_bp_marketing": 1200,
            },
            file_name="bw-cycle-01.csv",
            specs=BW_RECORDS,
            window_start="2026-08-02T09:00:00Z",
            run_start_clock="2026-08-02T09:00:00Z",
            run_complete_clock=None,
        )

    @staticmethod
    def _manifest(api: ApiClient, pipeline):
        start, end = BW_ZERO_LENGTH_WINDOW
        return api.manifest_batch(
            pipeline.batch["id"],
            f.manifest_payload(pipeline.facility["id"], start, end),
            POSTAGE_CONTROLLER_2,
        )

    def test_the_unsealed_batch_answers_before_the_payload_window(
        self, api: ApiClient
    ):
        """PRD §3.8: "A `PostageController` manifests a `SEALED` batch — any other status
        is `ERR_BATCH_NOT_SEALED` — supplying the `entry_facility_id` of the facility
        receiving the trays, plus `induction_window_start` and `induction_window_end`
        describing the half-open window during which the trays will be dropped, the
        start being inclusive and the end exclusive."

        The offending window sits in the request itself, yet the database fault
        wins: an open batch is refused as unsealed and the window is never judged.

        Design: Difficulty/priority_pair_validation_conflict/batch_not_sealed_outranks_malformed_induction_window
        """
        pipeline = self._bridgewater_verified(api)
        assert pipeline.batch["status"] == "OPEN"
        start, end = BW_ZERO_LENGTH_WINDOW
        assert start == end

        response = self._manifest(api, pipeline)

        validate_error(response, ApiErrorId.BATCH_NOT_SEALED.value, 409)

    def test_the_window_answers_once_the_batch_is_sealed(self, api: ApiClient):
        """PRD §3.8: "The window must be well formed: `induction_window_start` strictly
        earlier than `induction_window_end`, and the span between them at most 1,440
        minutes, which is one day; a malformed or over-long window is refused with
        `ERR_INVALID_INDUCTION_WINDOW` (HTTP 422)."

        Sealing the batch prices it at 112 cents and records the sealing identity;
        the identical manifest request then surfaces the temporal verdict, which was
        live all along.

        Design: Difficulty/priority_pair_validation_conflict/batch_not_sealed_outranks_malformed_induction_window
        """
        pipeline = self._bridgewater_verified(api)
        self._manifest(api, pipeline)

        sealed = fx.seal_batch(
            api, pipeline.batch["id"], pipeline.refresh_client()["version"]
        )
        assert sealed["status"] == "SEALED"
        assert sealed["estimated_postage_cents"] == 112
        assert sealed["sealed_by_user_id"] == POSTAGE_USER_ID
        pipeline.refresh_batches()

        response = self._manifest(api, pipeline)

        validate_error(response, ApiErrorId.INVALID_INDUCTION_WINDOW.value, 422)

    def test_the_failed_manifest_leaves_the_seal_and_the_facility_alone(
        self, api: ApiClient
    ):
        """PRD §3.8: "The batch moves `SEALED` → `MANIFESTED`, persisting
        `entry_facility_id`, `induction_window_start`, `induction_window_end` and
        `manifested_by_user_id`, with `manifested_postage_cents` and
        `postage_variance_cents` written and the batch's `version` incremented by 1."

        The refused manifest inducts nothing: the batch keeps its seal without an
        entry facility or a manifested figure, the facility reserves no trays, the
        job is still verified and the seal's commitment stands.

        Design: Difficulty/priority_pair_validation_conflict/batch_not_sealed_outranks_malformed_induction_window
        """
        pipeline = self._bridgewater_verified(api)
        fx.seal_batch(api, pipeline.batch["id"], pipeline.refresh_client()["version"])
        pipeline.refresh_batches()

        self._manifest(api, pipeline)

        batch = fx.read_batch(api, pipeline.batch["id"])
        assert batch["status"] == "SEALED"
        assert batch["entry_facility_id"] is None
        assert batch["manifested_postage_cents"] is None
        assert batch["postage_variance_cents"] is None

        assert pipeline.refresh_facility()["committed_tray_count"] == 0
        assert pipeline.refresh_job()["status"] == "VERIFIED"

        client = pipeline.refresh_client()
        assert client["postage_committed_cents"] == 112
        assert client["postage_escrow_available_cents"] == 99888
        a.assert_escrow_ledger(client)
