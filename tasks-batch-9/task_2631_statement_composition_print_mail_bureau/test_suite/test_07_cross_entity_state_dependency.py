"""Guards that read a second entity's state rather than a local field.

Each class issues one request twice, byte for byte, and changes nothing but the
state of the entity the guard consults in between.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    COMPOSITION_OPERATOR,
    POSTAGE_CONTROLLER,
    PRODUCTION_SCHEDULER,
)


class TestScheduleReadsDrSiteReadiness:
    """A healthy but never-drilled site, and the same schedule request either side
    of its first drill."""

    WINDOW_START = "2026-08-04T09:00:00Z"

    @staticmethod
    def _drummond_presorted(api: ApiClient):
        fx.set_clock(api)
        site = fx.register_dr_site(
            api, site_code="DR-EAST", replication_lag_minutes=5
        )
        pipeline = fx.presorted_job(
            api,
            clock=None,
            client_code="CLDR",
            client_overrides={
                "name": "Drummond Life Assurance",
                "dr_readiness_required": True,
            },
            template_code="T-DR",
            template_overrides={
                "sheets_per_document": 1,
                "mail_class_preference": "FIRST_CLASS",
            },
            with_press_line=True,
            press_line_code="PL-DR",
            press_line_overrides={
                "sheets_per_hour": 600,
                "daily_sheet_capacity": 9000,
                "changeover_buffer_minutes": 30,
            },
            file_name="dr-cycle-01.csv",
            specs=[
                fx.record_spec(
                    "ACC1701",
                    1,
                    12000,
                    address_line1="70 Drummond Avenue",
                    postal_code="30301",
                    postal_code_plus4="6601",
                ),
                fx.record_spec(
                    "ACC1702",
                    2,
                    12000,
                    address_line1="72 Drummond Avenue",
                    postal_code="30301",
                    postal_code_plus4="6602",
                ),
            ],
            file_overrides={
                "declared_record_count": 2,
                "declared_control_total_cents": 24000,
            },
        )
        return site, pipeline

    def _schedule(self, api: ApiClient, pipeline):
        return api.schedule_job(
            pipeline.job_id,
            f.schedule_payload(self.WINDOW_START, pipeline.press_line["id"]),
            PRODUCTION_SCHEDULER,
        )

    def test_an_untested_site_blocks_the_schedule(self, api: ApiClient):
        """PRD §2.11: "When the client that owns a job has `dr_readiness_required` set to
        true, scheduling that job onto a press line requires the single DR site to read
        `READY`; a site reading `UNTESTED`, `STALE` or `FAILED` blocks the schedule with
        `ERR_DR_SITE_NOT_READY` (HTTP 409)."

        A site with a healthy five-minute replication lag still reads untested
        while no drill has ever been recorded, and an untested site blocks the
        schedule of a client that requires readiness.

        Design: Difficulty/cross_entity_state_dependency/job_scheduling_depends_on_dr_site_readiness_state
        """
        site, pipeline = self._drummond_presorted(api)

        assert site["readiness_status"] == "UNTESTED"
        assert site["readiness_valid_until"] is None
        assert site["last_drill_at"] is None
        assert site["last_drill_result"] == "NONE"
        assert site["drill_count"] == 0
        assert site["replication_lag_minutes"] == 5
        assert pipeline.client["dr_readiness_required"] is True

        response = self._schedule(api, pipeline)
        validate_error(response, ApiErrorId.DR_SITE_NOT_READY.value, 409)
        assert pipeline.refresh_job()["status"] == "PRESORTED"
        assert fx.read_press_line(api, pipeline.press_line["id"])["committed_sheet_count"] == 0

    def test_one_passing_drill_lets_the_identical_request_through(
        self, api: ApiClient
    ):
        """PRD §2.11: "Otherwise `readiness_valid_until` is `last_drill_at` plus the
        thirty-day drill validity horizon, which is 720 hours."

        A single passing drill takes the site to ready with a validity horizon
        seven hundred and twenty hours out, and the byte-identical schedule then
        creates the run.

        Design: Difficulty/cross_entity_state_dependency/job_scheduling_depends_on_dr_site_readiness_state
        """
        site, pipeline = self._drummond_presorted(api)
        validate_error(
            self._schedule(api, pipeline), ApiErrorId.DR_SITE_NOT_READY.value, 409
        )

        drilled = fx.record_drill(api, site["id"], "PASS")
        assert drilled["readiness_status"] == "READY"
        assert drilled["last_drill_result"] == "PASS"
        assert drilled["drill_count"] == 1
        a.assert_instant(
            drilled["last_drill_at"], "2026-08-01T00:00:00Z", "site.last_drill_at"
        )
        a.assert_instant(
            drilled["readiness_valid_until"],
            "2026-08-31T00:00:00Z",
            "site.readiness_valid_until",
        )

        run = get_success_data(self._schedule(api, pipeline))
        assert run["status"] == "PLANNED"
        assert run["planned_sheet_count"] == 2
        a.assert_instant(run["window_start"], self.WINDOW_START, "run.window_start")
        a.assert_instant(run["window_end"], "2026-08-04T10:00:00Z", "run.window_end")
        assert pipeline.refresh_job()["status"] == "SCHEDULED"

    def test_only_the_dr_row_was_written_between_the_two_calls(self, api: ApiClient):
        """PRD §3.6: "Before anything else about the press floor is considered,
        disaster-recovery posture is checked: when the owning client's
        `dr_readiness_required` is true, the single DR site must read `READY`, else
        `ERR_DR_SITE_NOT_READY`."

        Nothing about the job, the line or the window differs between the refusal
        and the acceptance — the drill wrote the recovery site and left the site's
        replication lag exactly where it was.

        Design: Difficulty/cross_entity_state_dependency/job_scheduling_depends_on_dr_site_readiness_state
        """
        site, pipeline = self._drummond_presorted(api)
        validate_error(
            self._schedule(api, pipeline), ApiErrorId.DR_SITE_NOT_READY.value, 409
        )
        fx.record_drill(api, site["id"], "PASS")
        get_success_data(self._schedule(api, pipeline))

        reread_site = fx.read_dr_site(api, site["id"])
        assert reread_site["replication_lag_minutes"] == 5
        assert reread_site["readiness_status"] == "READY"

        line = fx.read_press_line(api, pipeline.press_line["id"])
        assert line["committed_sheet_count"] == 2
        a.assert_press_ledger(line)
        runs = fx.list_runs(api, composition_job_id=pipeline.job_id)
        assert len(runs) == 1


class TestSealReadsParentJobIntegrityState:
    """A fully funded open batch whose only obstacle is its parent job's integrity
    state."""

    @staticmethod
    def _stonejoint_printed(api: ApiClient):
        pipeline = fx.printed_job(
            api,
            fund_cents=100000,
            client_code="CLSJ",
            client_overrides={"name": "Stonejoint Credit Services"},
            template_code="T-SJ",
            template_overrides={
                "sheets_per_document": 1,
                "mail_class_preference": "FIRST_CLASS",
            },
            press_line_code="PL-SJ",
            press_line_overrides={
                "sheets_per_hour": 600,
                "daily_sheet_capacity": 9000,
                "changeover_buffer_minutes": 30,
            },
            file_name="sj-cycle-01.csv",
            specs=[
                fx.record_spec(
                    "ACC1801",
                    1,
                    13000,
                    address_line1="80 Stonejoint Lane",
                    postal_code="30301",
                    postal_code_plus4="7701",
                ),
                fx.record_spec(
                    "ACC1802",
                    2,
                    13000,
                    address_line1="82 Stonejoint Lane",
                    postal_code="30301",
                    postal_code_plus4="7702",
                ),
            ],
            file_overrides={
                "declared_record_count": 2,
                "declared_control_total_cents": 26000,
            },
        )
        return pipeline, pipeline.client["version"]

    @staticmethod
    def _seal(api: ApiClient, batch_id: str, client_version: int):
        return api.seal_batch(
            batch_id, f.seal_payload(client_version), POSTAGE_CONTROLLER
        )

    def test_a_printed_parent_blocks_a_sealable_batch(self, api: ApiClient):
        """PRD §3.8: "Sealing additionally requires the owning job to have reached status
        `VERIFIED` — the bureau does not commit postage on mail whose one-to-one
        integrity has not been proven — and any other job status is refused with
        `ERR_JOB_INVALID_STATE`."

        The batch is open, its trays are counted and the escrow is untouched, so
        the only reason the seal fails is that its parent job has not yet been
        reconciled to verified.

        Design: Difficulty/cross_entity_state_dependency/batch_seal_depends_on_composition_job_verified_state
        """
        pipeline, client_version = self._stonejoint_printed(api)
        batch = pipeline.batch

        assert pipeline.job["status"] == "PRINTED"
        assert pipeline.job["integrity_status"] == "PENDING"
        assert batch["status"] == "OPEN"
        assert batch["piece_count"] == 2
        assert batch["tray_count"] == 1
        assert pipeline.client["postage_escrow_available_cents"] == 100000

        response = self._seal(api, batch["id"], client_version)
        validate_error(response, ApiErrorId.JOB_INVALID_STATE.value, 409)

    def test_reconciliation_flips_the_parent_and_the_seal_then_succeeds(
        self, api: ApiClient
    ):
        """PRD §3.8: "The client cascade adds `estimated_postage_cents` to
        `postage_committed_cents`, subtracts the same amount from
        `postage_escrow_available_cents`, and increments the client's `version` by 1."

        Reconciliation writes the job and its pieces only, and the identical seal
        request then commits the two pieces' three-digit first-class postage.

        Design: Difficulty/cross_entity_state_dependency/batch_seal_depends_on_composition_job_verified_state
        """
        pipeline, client_version = self._stonejoint_printed(api)
        validate_error(
            self._seal(api, pipeline.batch["id"], client_version),
            ApiErrorId.JOB_INVALID_STATE.value,
            409,
        )

        reconciled = fx.reconcile(api, pipeline.job_id)
        assert reconciled["status"] == "VERIFIED"
        assert reconciled["integrity_status"] == "MATCHED"
        assert reconciled["print_piece_count"] == 2
        assert reconciled["accountable_piece_count"] == 2
        for piece in pipeline.refresh_pieces():
            assert piece["integrity_status"] == "RECONCILED"

        sealed = get_success_data(
            self._seal(api, pipeline.batch["id"], client_version)
        )
        assert sealed["status"] == "SEALED"
        assert sealed["estimated_postage_cents"] == 2 * 56 == 112

    def test_the_refused_seal_wrote_nothing_at_all(self, api: ApiClient):
        """PRD §3.8: "On success the batch moves `OPEN` → `SEALED`,
        `estimated_postage_cents` is persisted, `sealed_by_user_id` records the acting
        `X-User-ID`, and the batch's `version` is incremented by 1."

        Because the refusal never touched the client row, the very same expected
        version is still current for the second attempt, and the money moves only
        once.

        Design: Difficulty/cross_entity_state_dependency/batch_seal_depends_on_composition_job_verified_state
        """
        pipeline, client_version = self._stonejoint_printed(api)
        validate_error(
            self._seal(api, pipeline.batch["id"], client_version),
            ApiErrorId.JOB_INVALID_STATE.value,
            409,
        )

        after_refusal = fx.read_batch(api, pipeline.batch["id"])
        assert after_refusal["status"] == "OPEN"
        assert after_refusal["sealed_by_user_id"] is None
        assert pipeline.refresh_client()["postage_committed_cents"] == 0
        assert pipeline.client["version"] == client_version

        fx.reconcile(api, pipeline.job_id)
        get_success_data(self._seal(api, pipeline.batch["id"], client_version))

        client = pipeline.refresh_client()
        assert client["postage_committed_cents"] == 112
        assert client["postage_escrow_available_cents"] == 99888
        a.assert_escrow_ledger(client)


class TestCompositionReadsTemplateActivationState:
    """A findable draft template, and the same composition request either side of
    its activation."""

    @staticmethod
    def _talbot_ready(api: ApiClient):
        fx.set_clock(api)
        client = fx.register_client(
            api,
            client_code="CLTA",
            name="Talbot Regional Gas",
            dr_readiness_required=False,
        )
        template = fx.create_draft_template(
            api,
            client["id"],
            template_code="T-TA",
            sheets_per_document=2,
            mail_class_preference="FIRST_CLASS",
        )
        bundle = fx.accepted_file(
            api,
            client["id"],
            [
                fx.record_spec(
                    "ACC1901",
                    1,
                    14000,
                    address_line1="90 Talbot Crescent",
                    postal_code="30301",
                    postal_code_plus4="8801",
                ),
                fx.record_spec(
                    "ACC1902",
                    2,
                    14000,
                    address_line1="92 Talbot Crescent",
                    postal_code="30301",
                    postal_code_plus4="8802",
                ),
            ],
            file_name="ta-cycle-01.csv",
            declared_record_count=2,
            declared_control_total_cents=28000,
        )
        return client, template, bundle

    @staticmethod
    def _compose(api: ApiClient, file_id: str, template_id: str):
        return api.create_composition_job(
            f.composition_job_payload(file_id, template_id),
            COMPOSITION_OPERATOR,
        )

    @staticmethod
    def _jobs_for_file(api: ApiClient, file_id: str):
        data, _meta = validate_paginated(
            api.list_composition_jobs(
                COMPOSITION_OPERATOR, {"data_file_id": file_id, "limit": 100}
            )
        )
        return data

    def test_a_draft_template_refuses_composition_without_being_missing(
        self, api: ApiClient
    ):
        """PRD §3.4: "The file must be in status `ACCEPTED`, else `ERR_FILE_INVALID_STATE`;
        the template must be in status `ACTIVE`, else `ERR_TEMPLATE_NOT_ACTIVE` (HTTP
        409); the template must belong to the same client as the file, else
        `ERR_CLIENT_MISMATCH`; and that client must not be `SUSPENDED`, else
        `ERR_CLIENT_SUSPENDED`."

        The draft template resolves perfectly well, so the refusal is a state
        conflict and not a lookup failure, even though the data side of the request
        is entirely ready.

        Design: Difficulty/cross_entity_state_dependency/job_composition_depends_on_template_active_state
        """
        _client, template, bundle = self._talbot_ready(api)

        assert template["status"] == "DRAFT"
        assert template["activated_at"] is None
        assert bundle.data_file["status"] == "ACCEPTED"

        response = self._compose(api, bundle.id, template["id"])
        validate_error(response, ApiErrorId.TEMPLATE_NOT_ACTIVE.value, 409)

    def test_the_refused_composition_consumed_no_file_and_minted_no_job(
        self, api: ApiClient
    ):
        """PRD §3.4: "The accepted file cascades to `CONSUMED` in the same request, and the
        job's `version` is set by its creation."

        A refusal at the template gate leaves the accepted file accepted rather
        than consumed, and no job row exists behind it.

        Design: Difficulty/cross_entity_state_dependency/job_composition_depends_on_template_active_state
        """
        _client, template, bundle = self._talbot_ready(api)

        validate_error(
            self._compose(api, bundle.id, template["id"]),
            ApiErrorId.TEMPLATE_NOT_ACTIVE.value,
            409,
        )

        assert fx.read_data_file(api, bundle.id)["status"] == "ACCEPTED"
        assert self._jobs_for_file(api, bundle.id) == []

    def test_activation_alone_lets_the_identical_request_mint_the_job(
        self, api: ApiClient
    ):
        """PRD §3.2: "When the promotion succeeds, the version moves `DRAFT` → `ACTIVE`,
        takes `activated_at` from the logical clock and has its `version` incremented by
        1."

        Activation writes only the template, and the same request then composes
        two two-sheet pieces and cascades the file to consumed.

        Design: Difficulty/cross_entity_state_dependency/job_composition_depends_on_template_active_state
        """
        _client, template, bundle = self._talbot_ready(api)
        validate_error(
            self._compose(api, bundle.id, template["id"]),
            ApiErrorId.TEMPLATE_NOT_ACTIVE.value,
            409,
        )

        activated = fx.activate_template(api, template["id"])
        assert activated["status"] == "ACTIVE"
        a.assert_instant(
            activated["activated_at"],
            "2026-08-01T00:00:00Z",
            "template.activated_at",
        )

        job = get_success_data(self._compose(api, bundle.id, template["id"]))
        assert job["status"] == "COMPOSED"
        assert job["expected_piece_count"] == 2
        assert job["print_piece_count"] == 2
        assert job["total_sheet_count"] == 4
        assert job["print_sheet_count"] == 4
        assert fx.read_data_file(api, bundle.id)["status"] == "CONSUMED"
        assert len(self._jobs_for_file(api, bundle.id)) == 1
