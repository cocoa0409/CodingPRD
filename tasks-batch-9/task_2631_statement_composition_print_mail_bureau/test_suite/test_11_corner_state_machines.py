"""Lifecycle corners: declared initial states, ordered gates, family-scoped
cascades, non-idempotent transitions, cyclic re-entry, logged refusals and
terminal lockdown.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    BUREAU_ADMIN,
    CLIENT_LIAISON,
    COMPOSITION_OPERATOR,
    INTEGRITY_AUDITOR,
    PRODUCTION_SCHEDULER,
)


class TestDataFileLifecycleGates:
    """The intake file's declared start and the fixed order of its two control
    gates."""

    def test_a_lodged_file_starts_received_with_every_counter_empty(
        self, api: ApiClient
    ):
        """PRD §3.3: "The file begins in status `RECEIVED` with `received_at` taken from
        the logical clock, and every derived counter — `actual_record_count`,
        `actual_control_total_cents`, `record_count_variance`,
        `control_total_variance_cents`, `control_total_variance_bp`,
        `format_error_count` and `amendment_count` — initialised to 0, with
        `accepted_at` null."

        Lodgement puts the file in the first of its five states with the intake
        instant stamped from the logical clock, nothing accepted yet and every derived
        counter at zero.

        Design: Corner/state_machines/data_file_starts_in_received_with_empty_control_counters
        """
        fx.set_clock(api)
        client = fx.register_client(
            api, client_code="CLS1", name="Initial State Insurance"
        )

        lodged = validate_success(
            api.create_data_file(
                f.data_file_payload(
                    client["id"],
                    file_name="s1-intake.csv",
                    format_spec_code="FIXED_WIDTH",
                    declared_record_count=4,
                    declared_control_total_cents=40000,
                ),
                CLIENT_LIAISON,
            ),
            201,
        )
        a.assert_data_file(lodged)
        assert lodged["status"] == "RECEIVED"
        a.assert_instant(
            lodged["received_at"], "2026-08-01T00:00:00Z", "file.received_at"
        )
        assert lodged["accepted_at"] is None
        assert lodged["actual_record_count"] == 0
        assert lodged["actual_control_total_cents"] == 0
        assert lodged["record_count_variance"] == 0
        assert lodged["control_total_variance_cents"] == 0
        assert lodged["control_total_variance_bp"] == 0
        assert lodged["format_error_count"] == 0
        assert lodged["amendment_count"] == 0
        assert lodged["version"] == 1

        rows, meta = validate_paginated(
            api.list_client_data_files(
                client["id"], CLIENT_LIAISON, {"status": "RECEIVED"}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == lodged["id"]

    def test_a_clean_delimited_file_advances_to_format_validated(
        self, api: ApiClient
    ):
        """PRD §3.3: "Format validation is the first control gate, driven by a
        `CompositionOperator`, and it advances the file `RECEIVED` →
        `FORMAT_VALIDATED`."

        Every record satisfies both halves of the layout predicate, so the file takes
        the first gate with no errors counted, each record marked valid, one version
        step and acceptance still unstamped.

        Design: Corner/state_machines/validate_format_advances_the_file_to_format_validated
        """
        fx.set_clock(api)
        client = fx.register_client(
            api, client_code="CLS2", name="Valid Transition Bancorp"
        )
        bundle = fx.lodged_file(
            api,
            client["id"],
            [
                fx.record_spec(
                    "ABC2001",
                    1,
                    7000,
                    address_line1="1100 Transition Street",
                    city="Atlanta",
                    region_code="GA",
                    postal_code="30301",
                    postal_code_plus4="1101",
                ),
                fx.record_spec(
                    "ABC2002",
                    2,
                    8000,
                    address_line1="1102 Transition Street",
                    city="Atlanta",
                    region_code="GA",
                    postal_code="30301",
                    postal_code_plus4="1102",
                ),
            ],
            file_name="s2.csv",
            declared_record_count=2,
            declared_control_total_cents=15000,
        )
        assert bundle.data_file["version"] == 1
        assert bundle.data_file["format_spec_code"] == "DELIMITED"

        validated = fx.validate_file_format(api, bundle.id)
        assert validated["status"] == "FORMAT_VALIDATED"
        assert validated["format_error_count"] == 0
        assert validated["accepted_at"] is None
        assert validated["version"] == bundle.data_file["version"] + 1

        for record in fx.file_records(api, bundle.id):
            assert record["format_valid"] is True

    def test_the_control_check_refuses_to_run_before_the_format_gate(
        self, api: ApiClient
    ):
        """PRD §3.3: "A `CompositionOperator` runs it against a `FORMAT_VALIDATED` file;
        any other status is `ERR_FILE_INVALID_STATE`."

        The second gate demands the first one's outcome, so run against a merely
        received file it is refused on state and computes nothing at all.

        Design: Corner/state_machines/control_check_before_format_validation_is_rejected_as_invalid_state
        """
        fx.set_clock(api)
        client = fx.register_client(
            api, client_code="CLS3", name="Ordered Stage Savings"
        )
        bundle = fx.lodged_file(
            api,
            client["id"],
            [
                fx.record_spec(
                    "ABC3001",
                    1,
                    6000,
                    address_line1="1200 Sequence Way",
                    city="Atlanta",
                    region_code="GA",
                    postal_code="30301",
                    postal_code_plus4="1201",
                ),
                fx.record_spec(
                    "ABC3002",
                    2,
                    6000,
                    address_line1="1202 Sequence Way",
                    city="Atlanta",
                    region_code="GA",
                    postal_code="30301",
                    postal_code_plus4="1202",
                ),
            ],
            file_name="s3.csv",
            declared_record_count=2,
            declared_control_total_cents=12000,
        )

        validate_error(
            api.control_check(bundle.id, COMPOSITION_OPERATOR),
            ApiErrorId.FILE_INVALID_STATE.value,
            409,
        )

        reread = fx.read_data_file(api, bundle.id)
        assert reread["status"] == "RECEIVED"
        assert reread["actual_record_count"] == 0
        assert reread["actual_control_total_cents"] == 0
        assert reread["accepted_at"] is None
        assert reread["version"] == bundle.data_file["version"]


class TestTemplateActivation:
    """Promotion inside one template family, and what a replayed promotion does."""

    def test_promoting_the_next_version_retires_only_its_own_family(
        self, api: ApiClient
    ):
        """PRD §3.2: "That activation cascades: every sibling in the same family that is
        currently `ACTIVE` with a strictly lower `version_no` moves `ACTIVE` →
        `RETIRED`, takes `retired_at` from the logical clock, and has its own `version`
        incremented by 1."

        Activating version two stamps its own activation instant and drives the live
        version one into retirement at the same instant, while a template of a different
        code on the same client is left alone.

        Design: Corner/state_machines/activating_a_higher_version_retires_the_active_sibling
        """
        fx.set_clock(api)
        client = fx.register_client(
            api, client_code="CLS4", name="Template Family Fidelity"
        )
        first = fx.create_draft_template(
            api, client["id"], template_code="T-S4", version_no=1
        )
        second = fx.create_draft_template(
            api,
            client["id"],
            template_code="T-S4",
            version_no=2,
            duplex_required=True,
            sheets_per_document=2,
        )
        other = fx.create_draft_template(
            api,
            client["id"],
            template_code="T-S4B",
            version_no=1,
            mail_class_preference="MARKETING",
        )
        activated_first = fx.activate_template(api, first["id"])
        fx.activate_template(api, other["id"])
        a.assert_instant(
            activated_first["activated_at"],
            "2026-08-01T00:00:00Z",
            "first.activated_at",
        )

        fx.set_clock(api, "2026-08-02T00:00:00Z")
        activated_second = fx.activate_template(api, second["id"])

        a.assert_template(activated_second)
        assert activated_second["status"] == "ACTIVE"
        a.assert_instant(
            activated_second["activated_at"],
            "2026-08-02T00:00:00Z",
            "second.activated_at",
        )
        assert activated_second["retired_at"] is None

        retired = get_success_data(api.get_template(first["id"], BUREAU_ADMIN))
        assert retired["status"] == "RETIRED"
        a.assert_instant(
            retired["retired_at"], "2026-08-02T00:00:00Z", "first.retired_at"
        )

        untouched = get_success_data(api.get_template(other["id"], BUREAU_ADMIN))
        assert untouched["status"] == "ACTIVE"
        assert untouched["retired_at"] is None

        rows, meta = validate_paginated(
            api.list_client_templates(client["id"], BUREAU_ADMIN, {"status": "ACTIVE"})
        )
        assert meta["total_count"] == 2
        assert {(row["template_code"], row["version_no"]) for row in rows} == {
            ("T-S4", 2),
            ("T-S4B", 1),
        }

    def test_replaying_the_promotion_of_a_live_version_is_refused(
        self, api: ApiClient
    ):
        """PRD §3.2: "A `BureauAdmin` promotes a draft, and the promotion is refused with
        `ERR_TEMPLATE_INVALID_STATE` (HTTP 409) in two situations: when the target
        version is not `DRAFT`, and when a sibling in the same family is already
        `ACTIVE` with a strictly higher `version_no` — the bureau does not let an
        operator step backwards to an older layout by activating it after a newer one is
        live."

        Promotion is not a no-op when repeated: the second attempt is refused on
        template state, so a duplicated click cannot re-stamp the activation instant or
        move the row's version.

        Design: Corner/state_machines/second_activation_of_an_active_template_is_rejected
        """
        fx.set_clock(api)
        client = fx.register_client(
            api, client_code="CLS5", name="Idempotency Guard Group"
        )
        template = fx.create_active_template(
            api, client["id"], template_code="T-S5", version_no=1
        )
        assert template["status"] == "ACTIVE"
        a.assert_instant(
            template["activated_at"], "2026-08-01T00:00:00Z", "template.activated_at"
        )

        fx.set_clock(api, "2026-08-05T00:00:00Z")
        validate_error(
            api.activate_template(template["id"], BUREAU_ADMIN),
            ApiErrorId.TEMPLATE_INVALID_STATE.value,
            409,
        )

        reread = get_success_data(api.get_template(template["id"], BUREAU_ADMIN))
        assert reread["status"] == "ACTIVE"
        a.assert_instant(
            reread["activated_at"], "2026-08-01T00:00:00Z", "template.activated_at"
        )
        assert reread["version"] == template["version"]


class TestPaperlessEnrollmentLifecycle:
    """The suppression file: its epoch-stamped confirmation, its refusal to
    revoke twice and its re-entry from revocation."""

    def test_the_sync_advances_the_epoch_before_stamping_the_named_rows(
        self, api: ApiClient
    ):
        """PRD §3.1: "The run first increments the client's `paperless_sync_epoch` by 1,
        and only then walks the client's enrollments: every row of that client whose
        status is `PENDING` and whose `account_ref` appears in the supplied list moves
        `PENDING` → `ENROLLED`, taking `enrolled_epoch` equal to the newly incremented
        epoch, `confirmed_at` equal to the current logical clock and
        `suppression_effective` true, with its `version` incremented by 1."

        The run increments the client's epoch first and then writes that
        post-increment value onto the account it was told to confirm, at the run's own
        instant, leaving the unnamed account pending.

        Design: Corner/state_machines/paperless_sync_confirms_named_pending_enrollments_at_the_new_epoch
        """
        fx.set_clock(api)
        client = fx.register_client(
            api, client_code="CLS9", name="Suppression Sync Savings"
        )
        assert client["paperless_sync_epoch"] == 0
        first = fx.enroll_account(api, client["id"], "ABC9001", "EMAIL")
        a.assert_enrollment(first)
        assert first["status"] == "PENDING"
        assert first["suppression_effective"] is False
        second = fx.enroll_account(api, client["id"], "ABC9002", "PORTAL")

        fx.set_clock(api, "2026-08-03T06:00:00Z")
        synced = fx.confirm_enrollments(api, client["id"], ["ABC9001"])
        assert synced["paperless_sync_epoch"] == 1

        confirmed = get_success_data(api.get_enrollment(first["id"], CLIENT_LIAISON))
        assert confirmed["status"] == "ENROLLED"
        assert confirmed["enrolled_epoch"] == 1
        a.assert_instant(
            confirmed["confirmed_at"], "2026-08-03T06:00:00Z", "enrollment.confirmed_at"
        )
        assert confirmed["suppression_effective"] is True
        assert confirmed["revoked_epoch"] is None

        untouched = get_success_data(api.get_enrollment(second["id"], CLIENT_LIAISON))
        assert untouched["status"] == "PENDING"
        assert untouched["enrolled_epoch"] is None

        _rows, meta = validate_paginated(
            api.list_client_enrollments(
                client["id"], CLIENT_LIAISON, {"status": "ENROLLED"}
            )
        )
        assert meta["total_count"] == 1

    def test_revoking_a_revoked_enrollment_is_refused(self, api: ApiClient):
        """PRD §3.1: "Revoking a row that is already `REVOKED` is refused with
        `ERR_ENROLLMENT_INVALID_STATE`."

        Revocation from the pending state stamps the client's current epoch and the
        run instant, and the state accepts no second revocation, so a later clock cannot
        overwrite either stamp.

        Design: Corner/state_machines/revoking_an_already_revoked_enrollment_is_rejected
        """
        fx.set_clock(api)
        client = fx.register_client(api, client_code="CLS7", name="Revoke Twice Mutual")
        enrollment = fx.enroll_account(api, client["id"], "ABC7001", "EMAIL")

        revoked = get_success_data(
            api.revoke_enrollment(enrollment["id"], CLIENT_LIAISON)
        )
        assert revoked["status"] == "REVOKED"
        a.assert_instant(
            revoked["revoked_at"], "2026-08-01T00:00:00Z", "enrollment.revoked_at"
        )
        assert revoked["revoked_epoch"] == 0
        assert revoked["suppression_effective"] is False

        fx.set_clock(api, "2026-08-09T00:00:00Z")
        validate_error(
            api.revoke_enrollment(enrollment["id"], CLIENT_LIAISON),
            ApiErrorId.ENROLLMENT_INVALID_STATE.value,
            409,
        )

        reread = get_success_data(api.get_enrollment(enrollment["id"], CLIENT_LIAISON))
        assert reread["status"] == "REVOKED"
        a.assert_instant(
            reread["revoked_at"], "2026-08-01T00:00:00Z", "enrollment.revoked_at"
        )
        assert reread["version"] == revoked["version"]

    def test_re_enrolling_a_revoked_account_cycles_the_same_row(self, api: ApiClient):
        """PRD §3.1: "If an enrollment already exists for the same client and `account_ref`
        and it sits in status `REVOKED`, the create request reinstates that existing row
        in place rather than minting a second one: `status` moves `REVOKED` → `PENDING`,
        `channel` is overwritten with the newly supplied channel, and `enrolled_epoch`,
        `revoked_epoch`, `confirmed_at` and `revoked_at` are all cleared to null while
        `suppression_effective` returns to false, with the row's `version` incremented
        by 1."

        A create for an account whose enrollment is revoked reinstates that very row
        rather than minting a second one, overwriting the channel and clearing every
        epoch and instant the previous cycle left behind.

        Design: Corner/state_machines/reenrolling_a_revoked_account_loops_the_same_row_back_to_pending
        """
        fx.set_clock(api)
        client = fx.register_client(
            api, client_code="CLS8", name="Cyclic Enrollment Bank"
        )
        enrollment = fx.enroll_account(api, client["id"], "ABC8001", "PORTAL")
        assert enrollment["version"] == 1

        synced = fx.confirm_enrollments(api, client["id"], ["ABC8001"])
        assert synced["paperless_sync_epoch"] == 1
        confirmed = get_success_data(api.get_enrollment(enrollment["id"], CLIENT_LIAISON))
        assert confirmed["status"] == "ENROLLED"
        assert confirmed["enrolled_epoch"] == 1
        revoked = get_success_data(
            api.revoke_enrollment(enrollment["id"], CLIENT_LIAISON)
        )
        assert revoked["status"] == "REVOKED"

        reinstated = get_success_data(
            api.create_enrollment(
                f.enrollment_payload(client["id"], account_ref="ABC8001", channel="EMAIL"),
                CLIENT_LIAISON,
            )
        )
        assert reinstated["id"] == enrollment["id"]
        assert reinstated["status"] == "PENDING"
        assert reinstated["channel"] == "EMAIL"
        assert reinstated["enrolled_epoch"] is None
        assert reinstated["revoked_epoch"] is None
        assert reinstated["confirmed_at"] is None
        assert reinstated["revoked_at"] is None
        assert reinstated["suppression_effective"] is False
        assert reinstated["version"] == enrollment["version"] + 3

        _rows, meta = validate_paginated(
            api.list_client_enrollments(client["id"], CLIENT_LIAISON)
        )
        assert meta["total_count"] == 1


class TestScanRefusalsAreLoggedNotRaised:
    """A read at the wrong station is evidence, not an error."""

    def test_an_out_of_sequence_read_changes_no_field_on_the_piece(
        self, api: ApiClient
    ):
        """PRD §3.7: "Otherwise, a read whose `stage` does not follow the current
        `piece_status` is stored with `rejection_reason` `OUT_OF_SEQUENCE` and changes
        no field on the piece."

        An insertion read against a piece that has not yet been printed is stored as a
        refused event rather than raised as an error, and unlike a repeated-stage refusal
        it leaves both of the piece's dimensions exactly where they were.

        Design: Corner/state_machines/out_of_sequence_scan_is_recorded_without_advancing_the_piece
        """
        pipeline = fx.printing_job(
            api,
            client_code="CLS14",
            client_overrides={"name": "Scan Sequence Trust"},
            template_code="T-S14",
            press_line_code="PL-S14",
            press_line_overrides={"sheets_per_hour": 600, "daily_sheet_capacity": 9000},
            file_name="s14.csv",
            specs=[
                fx.record_spec(
                    "ABC1401",
                    1,
                    5000,
                    address_line1="1300 Sequence Circle",
                    city="Atlanta",
                    region_code="GA",
                    postal_code="30301",
                    postal_code_plus4="1301",
                )
            ],
        )
        piece = pipeline.piece
        assert piece["piece_status"] == "COMPOSED"

        event = validate_success(
            api.create_scan(
                piece["id"],
                f.scan_payload("INSERT", piece["imb_barcode"], device_code="SC-02"),
                INTEGRITY_AUDITOR,
            ),
            201,
        )
        assert event["accepted"] is False
        assert event["rejection_reason"] == "OUT_OF_SEQUENCE"

        reread = fx.read_piece(api, piece["id"])
        assert reread["piece_status"] == "COMPOSED"
        assert reread["integrity_status"] == "UNVERIFIED"
        assert reread["last_scan_stage"] == "NONE"
        assert reread["accepted_scan_count"] == 0

        assert len(fx.scan_events(api, piece["id"])) == 1
        assert fx.scan_events(api, piece["id"], accepted="true") == []


class TestPrintRunTerminalLockdown:
    """A finished run takes no further execution command."""

    def test_neither_start_nor_abort_reopens_a_completed_run(self, api: ApiClient):
        """PRD §3.6: "Starting a run that is not `PLANNED` is refused with
        `ERR_RUN_INVALID_STATE` (HTTP 409)."

        Completion is terminal for the run, so both remaining execution commands are
        refused on run state, and neither refusal re-commits the sheet capacity the
        completion released.

        Design: Corner/state_machines/starting_a_completed_run_is_rejected_as_invalid_run_state
        """
        pipeline = fx.build_pipeline(
            api,
            stage="printed",
            unscanned_piece_indexes=(0,),
            client_code="CLS15",
            client_overrides={"name": "Terminal Run Reserve"},
            template_code="T-S15",
            press_line_code="PL-S15",
            press_line_overrides={"sheets_per_hour": 600, "daily_sheet_capacity": 9000},
            window_start="2026-08-01T09:00:00Z",
            run_start_clock="2026-08-01T09:00:00Z",
            run_complete_clock="2026-08-01T10:00:00Z",
            file_name="s15.csv",
            specs=[
                fx.record_spec(
                    "ABC1501",
                    1,
                    3000,
                    address_line1="1400 Terminal Trail",
                    city="Atlanta",
                    region_code="GA",
                    postal_code="30301",
                    postal_code_plus4="1401",
                )
            ],
        )
        run = pipeline.run
        a.assert_print_run(run)
        assert run["status"] == "COMPLETED"
        a.assert_instant(
            run["completed_at"], "2026-08-01T10:00:00Z", "run.completed_at"
        )
        assert run["printed_piece_count"] == 0

        validate_error(
            api.start_run(run["id"], PRODUCTION_SCHEDULER),
            ApiErrorId.RUN_INVALID_STATE.value,
            409,
        )
        validate_error(
            api.abort_run(
                run["id"], PRODUCTION_SCHEDULER, f.abort_payload("EQUIPMENT_FAULT")
            ),
            ApiErrorId.RUN_INVALID_STATE.value,
            409,
        )

        reread = fx.read_run(api, run["id"])
        assert reread["status"] == "COMPLETED"
        assert reread["abort_reason"] == "NONE"
        a.assert_instant(
            reread["started_at"], "2026-08-01T09:00:00Z", "run.started_at"
        )
        line = pipeline.refresh_press_line()
        assert line["committed_sheet_count"] == 0
        assert line["utilization_bp"] == 0
        assert pipeline.refresh_job()["status"] == "PRINTED"


class TestCompositionJobTerminalLockdown:
    """Closure computes the penalty and the invoice once and only once."""

    @staticmethod
    def _manifested_terminal_close(api: ApiClient):
        return fx.manifested_job(
            api,
            client_code="CLS6",
            client_overrides={"name": "Terminal Close Corporation"},
            fund_cents=100000,
            template_code="T-S6",
            template_overrides={
                "mail_class_preference": "FIRST_CLASS",
                "sheets_per_document": 1,
            },
            press_line_code="PL-S6",
            press_line_overrides={"sheets_per_hour": 600, "daily_sheet_capacity": 9000},
            facility_code="EF-S6",
            facility_overrides={
                "facility_type": "SCF",
                "tray_capacity_per_window": 4,
                "discount_bp_first_class": 850,
                "discount_bp_marketing": 1200,
            },
            window_start="2026-08-01T09:00:00Z",
            run_start_clock="2026-08-01T09:00:00Z",
            run_complete_clock="2026-08-01T10:00:00Z",
            induction_window_start="2026-08-05T08:00:00Z",
            induction_window_end="2026-08-05T12:00:00Z",
            file_name="s6.csv",
            specs=[
                fx.record_spec(
                    "ABC6001",
                    1,
                    9000,
                    address_line1="1500 Closure Boulevard",
                    city="Atlanta",
                    region_code="GA",
                    postal_code="30301",
                    postal_code_plus4="1501",
                )
            ],
        )

    def test_a_second_close_is_refused_and_recomputes_nothing(self, api: ApiClient):
        """PRD §3.8: "The job must be in status `MANIFESTED`, else `ERR_JOB_INVALID_STATE`;
        because `MANIFESTED` is reachable only from `VERIFIED` with every batch
        manifested, a matched integrity rollup and the absence of open batches are
        structurally guaranteed and need no separate check."

        The first closure stamps completion inside the deadline, assesses no penalty
        and writes the eight-step invoice; the replay against a much later clock is
        refused on job state and leaves all three figures exactly as the first close
        wrote them.

        Design: Corner/state_machines/closed_job_is_terminal_and_a_second_close_is_rejected
        """
        pipeline = self._manifested_terminal_close(api)
        job = pipeline.refresh_job()
        a.assert_instant(
            job["sla_due_at"], "2026-08-03T00:00:00Z", "job.sla_due_at"
        )
        assert job["integrity_status"] == "MATCHED"
        batch = pipeline.batch
        assert batch["presort_bucket"] == "MIXED_AADC"
        assert batch["tray_count"] == 1
        assert batch["estimated_postage_cents"] == 62
        assert batch["manifested_postage_cents"] == 57
        assert batch["postage_variance_cents"] == -5

        fx.set_clock(api, "2026-08-02T00:00:00Z")
        closed = fx.close_job(api, pipeline.job_id)
        assert closed["status"] == "CLOSED"
        a.assert_instant(
            closed["sla_completed_at"], "2026-08-02T00:00:00Z", "job.sla_completed_at"
        )
        assert closed["assessed_penalty_cents"] == 0
        assert closed["composition_charge_cents"] == 9
        assert closed["insert_charge_cents"] == 0
        assert closed["pre_discount_subtotal_cents"] == 9
        assert closed["volume_discount_cents"] == 0
        assert closed["expedite_fee_cents"] == 0
        assert closed["billing_total_cents"] == 9

        fx.set_clock(api, "2026-08-20T00:00:00Z")
        validate_error(
            api.close_job(pipeline.job_id, BUREAU_ADMIN),
            ApiErrorId.JOB_INVALID_STATE.value,
            409,
        )

        reread = pipeline.refresh_job()
        assert reread["status"] == "CLOSED"
        a.assert_instant(
            reread["sla_completed_at"], "2026-08-02T00:00:00Z", "job.sla_completed_at"
        )
        assert reread["assessed_penalty_cents"] == 0
        assert reread["billing_total_cents"] == 9
        assert reread["version"] == closed["version"]

        client = pipeline.refresh_client()
        assert client["postage_deposited_cents"] == 100000
        assert client["postage_committed_cents"] == 57
        assert client["postage_escrow_available_cents"] == 99943
        a.assert_escrow_ledger(client)
