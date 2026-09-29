"""Refusals proved against the accepting case that differs by one fact.

Each test stages the violation and then repairs exactly the field the rule reads,
so the refusal cannot be explained by anything the two requests share.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    BUREAU_ADMIN,
    CLIENT_LIAISON,
    COMPOSITION_OPERATOR,
    POSTAGE_CONTROLLER,
    PRODUCTION_SCHEDULER,
)


class TestSuspendedClientIntakeGate:
    """One suspended client and one active client sent the same intake body."""

    def test_the_suspended_client_is_refused_where_the_active_one_is_served(
        self, api: ApiClient
    ):
        """PRD §3.1: "While a client is `SUSPENDED`, the bureau will not lodge a data file
        for it, will not attach a statement record to one of its files, will not compose
        a job from one of its files and will not accept a postage deposit against it;
        each of those four attempts is refused with `ERR_CLIENT_SUSPENDED`."

        Commercial standing is read per client on intake, so the identical file
        body is refused for the suspended client and lodged for the active one, and the
        same gate also turns away a postage deposit against the suspended client.

        Design: Corner/validations/suspended_client_cannot_receive_a_new_data_file_while_an_active_client_can
        """
        fx.set_clock(api)
        suspended = fx.register_client(
            api,
            client_code="CLV1S",
            name="Suspended Statements Bank",
            status="SUSPENDED",
            dr_readiness_required=False,
        )
        active = fx.register_client(
            api,
            client_code="CLV1A",
            name="Active Statements Bank",
            dr_readiness_required=False,
        )
        assert suspended["status"] == "SUSPENDED"
        assert active["status"] == "ACTIVE"

        refused = api.create_data_file(
            f.data_file_payload(
                suspended["id"],
                file_name="v1.csv",
                declared_record_count=1,
                declared_control_total_cents=5000,
            ),
            CLIENT_LIAISON,
        )
        validate_error(refused, ApiErrorId.CLIENT_SUSPENDED.value, 409)

        lodged = fx.lodge_data_file(
            api,
            active["id"],
            file_name="v1.csv",
            declared_record_count=1,
            declared_control_total_cents=5000,
        )
        assert lodged["status"] == "RECEIVED"

        deposit = api.create_postage_deposit(
            suspended["id"],
            f.postage_deposit_payload(amount_cents=10000, reference="wire-v1"),
            POSTAGE_CONTROLLER,
        )
        validate_error(deposit, ApiErrorId.CLIENT_SUSPENDED.value, 409)

        _rows, meta = validate_paginated(
            api.list_client_data_files(suspended["id"], CLIENT_LIAISON)
        )
        assert meta["total_count"] == 0
        reread = fx.read_client(api, suspended["id"])
        assert reread["postage_deposited_cents"] == 0
        a.assert_escrow_ledger(reread)


class TestCompositionOwnershipGate:
    """Two clients, two templates and one file that belongs to only one of them."""

    def test_a_template_from_another_client_is_a_mismatch_not_a_not_found(
        self, api: ApiClient
    ):
        """PRD §3.4: "The file must be in status `ACCEPTED`, else `ERR_FILE_INVALID_STATE`;
        the template must be in status `ACTIVE`, else `ERR_TEMPLATE_NOT_ACTIVE` (HTTP
        409); the template must belong to the same client as the file, else
        `ERR_CLIENT_MISMATCH`; and that client must not be `SUSPENDED`, else
        `ERR_CLIENT_SUSPENDED`."

        Both referenced rows resolve and both are individually eligible, so the
        only thing left to fail is the ownership tie between file and template, and
        swapping in the file's own template composes the job.

        Design: Corner/validations/composition_job_with_a_template_from_another_client_returns_client_mismatch
        """
        fx.set_clock(api)
        client_a = fx.register_client(
            api,
            client_code="CLV2A",
            name="Owner A Financial",
            dr_readiness_required=False,
        )
        client_b = fx.register_client(
            api,
            client_code="CLV2B",
            name="Owner B Financial",
            dr_readiness_required=False,
        )
        template_a = fx.create_active_template(
            api,
            client_a["id"],
            template_code="T-V2A",
            sheets_per_document=1,
            color_pages_per_document=0,
        )
        template_b = fx.create_active_template(
            api,
            client_b["id"],
            template_code="T-V2B",
            sheets_per_document=1,
            color_pages_per_document=0,
        )
        bundle = fx.accepted_file(
            api,
            client_a["id"],
            [
                fx.record_spec(
                    "ABC2201",
                    1,
                    5000,
                    address_line1="2700 Ownership Way",
                    postal_code="30301",
                    postal_code_plus4="2701",
                )
            ],
            file_name="v2.csv",
            declared_record_count=1,
            declared_control_total_cents=5000,
        )
        assert bundle.status == "ACCEPTED"
        assert template_b["status"] == "ACTIVE"

        mismatched = api.create_composition_job(
            f.composition_job_payload(bundle.id, template_b["id"]),
            COMPOSITION_OPERATOR,
        )
        validate_error(mismatched, ApiErrorId.CLIENT_MISMATCH.value, 422)

        job = fx.compose_job(api, bundle.id, template_a["id"])
        assert job["status"] == "COMPOSED"

        _rows, meta = validate_paginated(
            api.list_composition_jobs(
                COMPOSITION_OPERATOR, {"template_id": template_b["id"]}
            )
        )
        assert meta["total_count"] == 0


class TestSchedulingWindowIsNotInThePast:
    """One presorted job scheduled a minute early and then exactly on the clock."""

    def test_a_start_before_the_clock_is_refused_and_the_clock_instant_is_taken(
        self, api: ApiClient
    ):
        """PRD §3.6: "A `window_start` earlier than the current logical clock is refused
        with `ERR_WINDOW_IN_PAST` (HTTP 422)."

        The requested start is compared against the logical clock with a strict
        comparison, so one minute earlier is refused with no run created, while a start
        exactly at the clock is scheduled and sizes its window from there.

        Design: Corner/validations/scheduling_a_window_that_starts_before_the_clock_is_rejected
        """
        fx.set_clock(api, "2026-08-10T00:00:00Z")
        client = fx.register_client(
            api,
            client_code="CLV3",
            name="Past Window Partners",
            dr_readiness_required=False,
        )
        line = fx.register_press_line(
            api,
            line_code="PL-V3",
            capabilities=["DUPLEX"],
            sheets_per_hour=600,
            daily_sheet_capacity=2000,
        )
        template = fx.create_active_template(
            api,
            client["id"],
            template_code="T-V3",
            sheets_per_document=1,
            color_pages_per_document=0,
        )
        bundle = fx.accepted_file(
            api,
            client["id"],
            [
                fx.record_spec(
                    "ABC2301",
                    1,
                    5000,
                    address_line1="2800 Clock Court",
                    postal_code="30301",
                    postal_code_plus4="2801",
                )
            ],
            file_name="v3.csv",
            declared_record_count=1,
            declared_control_total_cents=5000,
        )
        job = fx.compose_job(api, bundle.id, template["id"])
        fx.presort_job(api, job["id"])

        early = api.schedule_job(
            job["id"],
            f.schedule_payload("2026-08-09T23:59:00Z", line["id"]),
            PRODUCTION_SCHEDULER,
        )
        validate_error(early, ApiErrorId.WINDOW_IN_PAST.value, 422)
        assert fx.read_job(api, job["id"])["status"] == "PRESORTED"
        assert fx.list_runs(api, composition_job_id=job["id"]) == []

        run = fx.schedule_job(api, job["id"], "2026-08-10T00:00:00Z", line["id"])
        assert run["status"] == "PLANNED"
        a.assert_instant(
            run["window_start"], "2026-08-10T00:00:00Z", "run.window_start"
        )
        a.assert_instant(run["window_end"], "2026-08-10T01:00:00Z", "run.window_end")
        assert run["run_minutes"] == a.expected_run_minutes(1, 600) == 60
        assert fx.read_job(api, job["id"])["status"] == "SCHEDULED"

        _rows, meta = validate_paginated(
            api.list_print_runs(PRODUCTION_SCHEDULER, {"composition_job_id": job["id"]})
        )
        assert meta["total_count"] == 1


class TestDisasterRecoveryGateIsConditional:
    """A failed recovery site and a client that has opted out of the check."""

    def test_an_opted_out_client_schedules_over_a_failed_recovery_site(
        self, api: ApiClient
    ):
        """PRD §2.11: "When the client has `dr_readiness_required` set to false, readiness
        is not consulted at all and scheduling proceeds even with no DR site
        registered."

        Readiness is consulted only for clients that require it, so a job whose
        client has opted out schedules while the single site still reads FAILED, and the
        successful schedule neither repairs nor touches that site.

        Design: Corner/validations/dr_readiness_is_not_checked_when_the_client_opts_out
        """
        fx.set_clock(api)
        site = fx.register_dr_site(api, site_code="DR-V4", replication_lag_minutes=5)
        failed = fx.record_drill(api, site["id"], "FAIL")
        assert failed["readiness_status"] == "FAILED"

        client = fx.register_client(
            api,
            client_code="CLV4",
            name="Opted Out Utilities",
            dr_readiness_required=False,
        )
        assert client["dr_readiness_required"] is False
        line = fx.register_press_line(
            api,
            line_code="PL-V4",
            capabilities=["DUPLEX"],
            sheets_per_hour=600,
            daily_sheet_capacity=2000,
        )
        template = fx.create_active_template(
            api,
            client["id"],
            template_code="T-V4",
            sheets_per_document=1,
            color_pages_per_document=0,
        )
        bundle = fx.accepted_file(
            api,
            client["id"],
            [
                fx.record_spec(
                    "ABC2401",
                    1,
                    5000,
                    address_line1="2900 Failover Freeway",
                    postal_code="30301",
                    postal_code_plus4="2901",
                )
            ],
            file_name="v4.csv",
            declared_record_count=1,
            declared_control_total_cents=5000,
        )
        job = fx.compose_job(api, bundle.id, template["id"])
        fx.presort_job(api, job["id"])

        run = fx.schedule_job(api, job["id"], "2026-08-05T09:00:00Z", line["id"])

        assert run["status"] == "PLANNED"
        assert run["press_line_id"] == line["id"]
        assert run["selection_mode"] == "EXPLICIT"
        assert fx.read_job(api, job["id"])["status"] == "SCHEDULED"
        assert fx.read_dr_site(api, site["id"])["readiness_status"] == "FAILED"


class TestEmptyFileCascade:
    """A file with no records, refused twice for two different reasons."""

    def test_emptiness_answers_the_format_pass_and_state_answers_the_control_check(
        self, api: ApiClient
    ):
        """PRD §3.3: "Before any per-record work is done the file must carry at least one
        attached record; a file with none is refused with `ERR_FILE_EMPTY` (HTTP 422)."

        The emptiness check lives inside format validation, so the refusal leaves the
        file where it was and the follow-up control check fails earlier still, on the
        file-state gate; attaching one record then lets the same format pass through.

        Design: Corner/validations/empty_file_is_rejected_and_its_control_check_still_fails_on_state_first
        """
        fx.set_clock(api)
        client = fx.register_client(
            api,
            client_code="CLV5",
            name="Empty Intake Escrow",
            dr_readiness_required=False,
        )
        data_file = fx.lodge_data_file(
            api,
            client["id"],
            file_name="v5.csv",
            declared_record_count=1,
            declared_control_total_cents=5000,
        )
        assert data_file["status"] == "RECEIVED"
        assert data_file["format_error_count"] == 0
        assert data_file["actual_record_count"] == 0

        empty = api.validate_format(data_file["id"], COMPOSITION_OPERATOR)
        validate_error(empty, ApiErrorId.FILE_EMPTY.value, 422)
        after_empty = fx.read_data_file(api, data_file["id"])
        assert after_empty["status"] == "RECEIVED"
        assert after_empty["format_error_count"] == 0

        wrong_state = api.control_check(data_file["id"], COMPOSITION_OPERATOR)
        validate_error(wrong_state, ApiErrorId.FILE_INVALID_STATE.value, 409)

        fx.attach_records(
            api,
            data_file["id"],
            [
                fx.record_spec(
                    "ABC2501",
                    1,
                    5000,
                    address_line1="3000 Refill Road",
                    postal_code="30301",
                    postal_code_plus4="3001",
                )
            ],
        )
        validated = fx.validate_file_format(api, data_file["id"])
        assert validated["status"] == "FORMAT_VALIDATED"
        assert validated["format_error_count"] == 0


class TestAmendmentMateriality:
    """A held file amended first with its own stored figures, then with a new one."""

    def test_a_verbatim_resubmission_is_refused_and_a_real_change_reopens_the_file(
        self, api: ApiClient
    ):
        """PRD §3.3: "An amendment must actually move something: if neither supplied figure
        differs from the value already stored, the request is refused with
        `ERR_AMENDMENT_NO_CHANGE` (HTTP 422)."

        An amendment must move one of the two declared figures, so resubmitting both
        stored values is refused with the amendment count untouched, while raising the
        declared total to the figure the records actually carry returns the file to
        RECEIVED with its hold evidence cleared.

        Design: Corner/validations/amendment_that_moves_no_declared_figure_is_rejected
        """
        fx.set_clock(api)
        client = fx.register_client(
            api,
            client_code="CLV6",
            name="Amendment Assurance",
            dr_readiness_required=False,
        )
        assert client["control_total_tolerance_bp"] == 5
        bundle = fx.lodged_file(
            api,
            client["id"],
            [
                fx.record_spec(
                    "ABC2601",
                    1,
                    10500,
                    address_line1="3100 Variance Vista",
                    postal_code="30301",
                    postal_code_plus4="3101",
                )
            ],
            file_name="v6.csv",
            declared_record_count=1,
            declared_control_total_cents=10000,
        )
        fx.validate_file_format(api, bundle.id)
        held = fx.run_control_check(api, bundle.id)
        assert held["status"] == "HELD_VARIANCE"
        assert held["control_total_variance_cents"] == 500
        assert held["control_total_variance_bp"] == a.expected_variance_bp(10000, 10500)
        assert held["control_total_variance_bp"] == 500
        assert held["amendment_count"] == 0

        no_change = api.amend_control_totals(
            bundle.id,
            f.amend_control_totals_payload(1, 10000),
            CLIENT_LIAISON,
        )
        validate_error(no_change, ApiErrorId.AMENDMENT_NO_CHANGE.value, 422)
        assert fx.read_data_file(api, bundle.id)["amendment_count"] == 0

        amended = fx.amend_declared_totals(
            api, bundle.id, declared_control_total_cents=10500
        )
        assert amended["status"] == "RECEIVED"
        assert amended["declared_control_total_cents"] == 10500
        assert amended["declared_record_count"] == 1
        assert amended["amendment_count"] == 1
        assert amended["control_total_variance_cents"] == 0
        assert amended["control_total_variance_bp"] == 0
        assert amended["record_count_variance"] == 0
        assert amended["format_error_count"] == 0
        assert fx.file_records(api, bundle.id)[0]["format_valid"] is False


class TestShapeOutranksUniqueness:
    """One taken client code resubmitted well formed and then malformed."""

    def test_a_malformed_duplicate_reports_the_shape_failure(self, api: ApiClient):
        """PRD §3.1: "A duplicate `client_code` is refused with `ERR_DUPLICATE_CODE`."

        Request shape is settled before uniqueness is probed, so a body that is both
        a duplicate and missing a required field reports the shape failure, while the
        well-formed duplicate reports the taken code; neither attempt creates a row.

        Design: Corner/validations/duplicate_client_code_is_rejected_and_a_malformed_payload_outranks_it
        """
        fx.set_clock(api)
        first = fx.register_client(
            api,
            client_code="CLV7",
            name="First Registrant Bank",
            dr_readiness_required=False,
        )

        duplicate = api.create_client(
            {"client_code": "CLV7", "name": "Second Registrant Bank"}, BUREAU_ADMIN
        )
        validate_error(duplicate, ApiErrorId.DUPLICATE_CODE.value, 409)

        malformed_duplicate = api.create_client({"client_code": "CLV7"}, BUREAU_ADMIN)
        validate_error(malformed_duplicate, ApiErrorId.VALIDATION.value, 422)

        rows, meta = validate_paginated(api.list_clients(BUREAU_ADMIN, {"limit": 100}))
        assert meta["total_count"] == 1
        assert [row["client_code"] for row in rows] == ["CLV7"]
        assert rows[0]["id"] == first["id"]
        assert rows[0]["name"] == "First Registrant Bank"


class TestTemplateInsertCodeResolution:
    """Two template versions whose only difference is one rule's insert code."""

    def test_a_rule_triggered_code_with_no_stock_row_is_refused(self, api: ApiClient):
        """PRD §3.2: "At creation time, every insert code named anywhere in the template,
        whether unconditionally in `required_insert_codes` or as a rule's
        `required_insert_code`, must resolve to an existing insert stock row; a code
        with no such row is refused with `ERR_INSERT_CODE_UNKNOWN` (HTTP 422)."

        Every code the template names is resolved against the stock catalogue, the
        conditional ones included, so a rule pointing at a code no row carries is
        refused while the version whose codes all resolve is created as a draft.

        Design: Corner/validations/template_requiring_an_unknown_insert_code_is_rejected
        """
        fx.set_clock(api)
        stock = fx.register_insert_stock(
            api,
            insert_code="INS-V8",
            description="State disclosure",
            jurisdiction_code="GA",
            effective_from="2026-01-01T00:00:00Z",
            sheets_per_insert=1,
            received_count=25,
        )
        client = fx.register_client(
            api,
            client_code="CLV8",
            name="Unknown Insert Insurance",
            dr_readiness_required=False,
        )

        ghost = api.create_template(
            f.template_payload(
                client["id"],
                template_code="T-V8-BAD",
                sheets_per_document=1,
                color_pages_per_document=0,
                required_insert_codes=["INS-V8"],
                variable_content_rules=[
                    f.variable_content_rule("R1", 1000, 0, "INS-GHOST")
                ],
            ),
            BUREAU_ADMIN,
        )
        validate_error(ghost, ApiErrorId.INSERT_CODE_UNKNOWN.value, 422)

        good = fx.create_draft_template(
            api,
            client["id"],
            template_code="T-V8-GOOD",
            sheets_per_document=1,
            color_pages_per_document=0,
            required_insert_codes=["INS-V8"],
            variable_content_rules=[f.variable_content_rule("R1", 1000, 0, "INS-V8")],
        )
        assert good["status"] == "DRAFT"

        _rows, meta = validate_paginated(
            api.list_client_templates(client["id"], BUREAU_ADMIN)
        )
        assert meta["total_count"] == 1

        reread = fx.read_insert_stock(api, stock["id"])
        assert reread["on_hand_count"] == 25
        assert reread["reserved_count"] == 0
        a.assert_insert_stock_ledger(reread)


class TestInsertEffectivityAtComposition:
    """One expired insert composed after the clock is moved inside its window."""

    def test_an_expired_insert_blocks_composition_until_the_clock_is_inside_the_window(
        self, api: ApiClient
    ):
        """PRD §3.4: "A code that resolves to a `WITHDRAWN` row, or to a row whose window
        has not opened or has already closed, blocks the composition with
        `ERR_INSERT_NOT_EFFECTIVE` (HTTP 422)."

        Effectivity is judged against the composition instant, so a template whose
        insert closed a month earlier is refused, and the identical request succeeds
        once the clock sits inside the window — reserving the copy only then.

        Design: Corner/validations/insert_stock_outside_its_effective_window_is_rejected_at_composition
        """
        fx.set_clock(api)
        stock = fx.register_insert_stock(
            api,
            insert_code="INS-V9",
            description="Expired regulatory notice",
            effective_from="2026-01-01T00:00:00Z",
            effective_to="2026-07-01T00:00:00Z",
            sheets_per_insert=1,
            received_count=25,
        )
        assert stock["status"] == "ACTIVE"
        client = fx.register_client(
            api,
            client_code="CLV9",
            name="Expired Insert Indemnity",
            dr_readiness_required=False,
        )
        template = fx.create_active_template(
            api,
            client["id"],
            template_code="T-V9",
            sheets_per_document=1,
            color_pages_per_document=0,
            required_insert_codes=["INS-V9"],
        )
        bundle = fx.accepted_file(
            api,
            client["id"],
            [
                fx.record_spec(
                    "ABC2701",
                    1,
                    5000,
                    address_line1="3200 Expiry Esplanade",
                    postal_code="30301",
                    postal_code_plus4="3201",
                )
            ],
            file_name="v9.csv",
            declared_record_count=1,
            declared_control_total_cents=5000,
        )

        expired = api.create_composition_job(
            f.composition_job_payload(bundle.id, template["id"]),
            COMPOSITION_OPERATOR,
        )
        validate_error(expired, ApiErrorId.INSERT_NOT_EFFECTIVE.value, 422)
        untouched = fx.read_insert_stock(api, stock["id"])
        assert untouched["on_hand_count"] == 25
        assert untouched["reserved_count"] == 0

        fx.set_clock(api, "2026-06-30T23:59:00Z")
        job = fx.compose_job(api, bundle.id, template["id"])

        assert job["status"] == "COMPOSED"
        assert job["insert_sheet_total"] == 1

        reread = fx.read_insert_stock(api, stock["id"])
        assert reread["reserved_count"] == 1
        assert reread["on_hand_count"] == 24
        a.assert_insert_stock_ledger(reread)
