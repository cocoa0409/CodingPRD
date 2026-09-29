"""Entity-surface corners: creation echoes, retrieval, listing, defaults, computed
counters, server-owned fields, type constraints and parent resolution.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    is_valid_uuid,
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
    PRODUCTION_SCHEDULER,
)


class TestClientEntitySurface:
    """The client row: its creation echo, its declared defaults and its listing."""

    def test_creation_echoes_every_declared_field_and_seeds_the_ledgers(
        self, api: ApiClient
    ):
        """PRD §3.1: "Six counters on the client are system-maintained and are initialised
        to 0 at registration: `postage_deposited_cents`, `postage_committed_cents`,
        `postage_escrow_available_cents`, `paperless_sync_epoch`,
        `pending_address_feedback_count` and `address_feedback_batch_count`."

        A fully specified registration returns the row with every input echoed, every
        money and counter field at zero, and version one.

        Design: Corner/entities/client_creation_returns_201_with_every_declared_field
        """
        fx.set_clock(api)

        body = validate_success(
            api.create_client(
                f.client_payload(
                    client_code="CLE1",
                    name="Entity Corner Mutual",
                    sla_turnaround_hours=36,
                    sla_penalty_rate_cents_per_hour=1000,
                    sla_penalty_cap_cents=250000,
                    dr_readiness_required=False,
                    control_total_tolerance_bp=12,
                    status="ACTIVE",
                ),
                BUREAU_ADMIN,
            ),
            201,
        )
        a.assert_client(body)
        assert body["client_code"] == "CLE1"
        assert body["name"] == "Entity Corner Mutual"
        assert body["sla_turnaround_hours"] == 36
        assert body["sla_penalty_rate_cents_per_hour"] == 1000
        assert body["sla_penalty_cap_cents"] == 250000
        assert body["dr_readiness_required"] is False
        assert body["control_total_tolerance_bp"] == 12
        assert body["status"] == "ACTIVE"

        assert body["postage_deposited_cents"] == 0
        assert body["postage_committed_cents"] == 0
        assert body["postage_escrow_available_cents"] == 0
        assert body["paperless_sync_epoch"] == 0
        assert body["pending_address_feedback_count"] == 0
        assert body["address_feedback_batch_count"] == 0
        assert body["version"] == 1
        a.assert_instant(body["created_at"], "2026-08-01T00:00:00Z", "client.created_at")
        a.assert_instant(body["updated_at"], "2026-08-01T00:00:00Z", "client.updated_at")

        assert fx.read_client(api, body["id"]) == body

    def test_omitting_every_optional_field_applies_the_declared_defaults(
        self, api: ApiClient
    ):
        """PRD §3.1: "Four contracted commercial terms are captured at the same time, each
        with a default that applies when the field is omitted."

        A bare registration takes the contract's own defaults for the four commercial
        terms, for recovery posture and for status, and persists them.

        Design: Corner/entities/client_defaults_apply_when_optional_fields_omitted
        """
        fx.set_clock(api)

        created = get_success_data(
            api.create_client(
                {"client_code": "CLE6", "name": "Default Value Federal"},
                BUREAU_ADMIN,
            )
        )
        assert created["sla_turnaround_hours"] == 48
        assert created["sla_penalty_rate_cents_per_hour"] == 2500
        assert created["sla_penalty_cap_cents"] == 500000
        assert created["control_total_tolerance_bp"] == 5
        assert created["dr_readiness_required"] is True
        assert created["status"] == "ACTIVE"

        stored = fx.read_client(api, created["id"])
        assert stored["sla_turnaround_hours"] == 48
        assert stored["sla_penalty_rate_cents_per_hour"] == 2500
        assert stored["sla_penalty_cap_cents"] == 500000
        assert stored["control_total_tolerance_bp"] == 5
        assert stored["dr_readiness_required"] is True

    def test_a_page_size_outside_the_accepted_range_is_refused(self, api: ApiClient):
        """PRD §2.3: "The `limit` parameter defaults to 10 when omitted, with a minimum
        accepted value of 1 and a maximum of 100; a supplied `limit` outside that
        inclusive range is a request-shape failure and is rejected with `ERR_VALIDATION`
        (HTTP 422)."

        A page size of one hundred and one is above the maximum and a page size of
        zero is below the minimum, and neither is quietly clamped; the unparameterised
        read shows the defaults instead.

        Design: Corner/entities/client_listing_with_limit_above_maximum_returns_invalid_request
        """
        fx.set_clock(api)
        fx.register_client(api, client_code="CLE10", name="Pagination Bounds Bank")

        validate_error(
            api.list_clients(BUREAU_ADMIN, {"limit": 101}),
            ApiErrorId.VALIDATION.value,
            422,
        )
        validate_error(
            api.list_clients(BUREAU_ADMIN, {"limit": 0}),
            ApiErrorId.VALIDATION.value,
            422,
        )

        data, meta = validate_paginated(api.list_clients(BUREAU_ADMIN))
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert data[0]["client_code"] == "CLE10"


class TestInsertStockEntitySurface:
    """The warehouse row: what a read returns and what the server refuses to take
    from the caller."""

    def test_a_read_returns_the_stored_row_including_its_seeded_ledger(
        self, api: ApiClient
    ):
        """PRD §3.2: "On receipt, `on_hand_count` is initialised to `received_count` while
        `reserved_count` and `consumed_count` both start at 0."

        The stored insert is returned unchanged to a non-administrative reader, with
        its on-hand count seeded from the received count and an open-ended window.

        Design: Corner/entities/insert_stock_retrieval_returns_the_stored_row
        """
        fx.set_clock(api)
        stock = fx.register_insert_stock(
            api,
            insert_code="INS-E2",
            description="State disclosure leaflet",
            jurisdiction_code="US-CA",
            effective_from="2026-07-01T00:00:00Z",
            sheets_per_insert=3,
            received_count=40,
        )

        read = get_success_data(api.get_insert_stock(stock["id"], COMPOSITION_OPERATOR))
        a.assert_insert_stock(read)
        assert read["insert_code"] == "INS-E2"
        assert read["description"] == "State disclosure leaflet"
        assert read["jurisdiction_code"] == "US-CA"
        assert read["sheets_per_insert"] == 3
        assert read["received_count"] == 40
        assert read["on_hand_count"] == 40
        assert read["reserved_count"] == 0
        assert read["consumed_count"] == 0
        assert read["status"] == "ACTIVE"
        a.assert_instant(
            read["effective_from"], "2026-07-01T00:00:00Z", "stock.effective_from"
        )
        assert read["effective_to"] is None

    def test_server_owned_identity_and_ledger_fields_ignore_the_caller(
        self, api: ApiClient
    ):
        """PRD §2.4: "The `version` field is an integer that begins at 1 when the resource
        is created and increases by exactly 1 on every mutation of that row, including
        mutations the row suffers as a cascaded side effect of an operation aimed at
        some other resource."

        The identifier is minted by the server, the creation instant comes from the
        logical clock, the version starts at one and the on-hand count is seeded from
        the received count, whatever the caller supplied for any of them.

        Design: Corner/entities/insert_stock_system_and_ledger_fields_input_ignored
        """
        fx.set_clock(api)

        created = get_success_data(
            api.create_insert_stock(
                f.insert_stock_payload(
                    insert_code="INS-E8",
                    description="Rate change notice",
                    jurisdiction_code="US-FED",
                    effective_from="2026-07-01T00:00:00Z",
                    received_count=25,
                    id=NON_EXISTENT_UUID,
                    created_at="2020-01-01T00:00:00Z",
                    version=77,
                    on_hand_count=5,
                    reserved_count=4,
                    consumed_count=3,
                ),
                BUREAU_ADMIN,
            )
        )
        assert is_valid_uuid(created["id"])
        assert created["id"] != NON_EXISTENT_UUID
        assert created["version"] == 1
        a.assert_instant(
            created["created_at"], "2026-08-01T00:00:00Z", "stock.created_at"
        )
        assert created["on_hand_count"] == 25 == created["received_count"]
        assert created["reserved_count"] == 0
        assert created["consumed_count"] == 0
        assert created["sheets_per_insert"] == 1
        assert created["status"] == "ACTIVE"
        a.assert_insert_stock_ledger(created)


class TestPressLineEntitySurface:
    """The press floor: how its list pages and filters, and what it refuses to
    commission."""

    def test_pagination_and_the_status_filter_partition_the_floor(
        self, api: ApiClient
    ):
        """PRD §2.3: "When a list endpoint responds, the `meta` object carries four
        pagination fields alongside the request identifier and timestamp: `limit` (the
        effective page size), `offset` (the effective starting position), `total_count`
        (the number of rows matching the filter before pagination is applied) and
        `has_more` (true when rows remain beyond the current page)."

        Three commissioned lines page two-then-one under a page size of two, with the
        whole matching set reported on both pages and rows to come only on the first;
        the status filter narrows the set before that count is taken.

        Design: Corner/entities/press_line_listing_paginates_with_total_count_and_has_more
        """
        fx.set_clock(api)
        fx.register_press_line(
            api,
            line_code="PL-E3A",
            capabilities=["DUPLEX"],
            sheets_per_hour=600,
            daily_sheet_capacity=9000,
        )
        fx.register_press_line(
            api,
            line_code="PL-E3B",
            capabilities=["DUPLEX", "COLOR"],
            sheets_per_hour=900,
            daily_sheet_capacity=9000,
        )
        fx.register_press_line(
            api,
            line_code="PL-E3C",
            capabilities=["INSERT"],
            sheets_per_hour=300,
            daily_sheet_capacity=9000,
            status="MAINTENANCE",
        )

        first, first_meta = validate_paginated(
            api.list_press_lines(PRODUCTION_SCHEDULER, {"limit": 2, "offset": 0})
        )
        assert len(first) == 2
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0
        assert first_meta["total_count"] == 3
        assert first_meta["has_more"] is True

        second, second_meta = validate_paginated(
            api.list_press_lines(PRODUCTION_SCHEDULER, {"limit": 2, "offset": 2})
        )
        assert len(second) == 1
        assert second_meta["offset"] == 2
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False

        paged_codes = [row["line_code"] for row in first + second]
        assert paged_codes == ["PL-E3A", "PL-E3B", "PL-E3C"]
        assert len({row["id"] for row in first + second}) == 3

        available, available_meta = validate_paginated(
            api.list_press_lines(PRODUCTION_SCHEDULER, {"status": "AVAILABLE"})
        )
        assert available_meta["total_count"] == 2
        assert available_meta["has_more"] is False
        assert [row["line_code"] for row in available] == ["PL-E3A", "PL-E3B"]

    def test_values_outside_the_declared_enumerations_are_refused(
        self, api: ApiClient
    ):
        """PRD §2.10: "Request shape — every required field present, every enum value a
        member of its declared set, every integer inside its declared bounds, every
        datetime a well-formed ISO 8601 UTC instant, every variable-content-rule entry
        well formed, and pagination inside its declared range, else `ERR_VALIDATION`."

        A plausible third status and a plausible fourth capability are both outside
        their declared sets, and neither is coerced to the default; nothing is
        persisted by either attempt.

        Design: Corner/entities/press_line_creation_with_unknown_status_enum_returns_invalid_request
        """
        fx.set_clock(api)

        validate_error(
            api.create_press_line(
                f.press_line_payload(
                    line_code="PL-E9",
                    capabilities=["DUPLEX"],
                    sheets_per_hour=600,
                    daily_sheet_capacity=9000,
                    status="OFFLINE",
                ),
                BUREAU_ADMIN,
            ),
            ApiErrorId.VALIDATION.value,
            422,
        )
        validate_error(
            api.create_press_line(
                f.press_line_payload(
                    line_code="PL-E9B",
                    capabilities=["LASER"],
                    sheets_per_hour=600,
                    daily_sheet_capacity=9000,
                ),
                BUREAU_ADMIN,
            ),
            ApiErrorId.VALIDATION.value,
            422,
        )

        _rows, meta = validate_paginated(api.list_press_lines(BUREAU_ADMIN))
        assert meta["total_count"] == 0


class TestDataFileEntitySurface:
    """The lodged file: its required declarations and its computed counters."""

    def test_omitting_the_declared_control_total_is_a_shape_failure(
        self, api: ApiClient
    ):
        """PRD §3.3: "A `ClientLiaison` lodges each transmission as a data file, naming the
        owning `client_id`, the transmitted `file_name` as received (between 1 and 120
        characters), the declared physical layout in `format_spec_code` — one of
        `FIXED_WIDTH`, `DELIMITED` or `XML` — and the two trailer assertions the client
        makes about its own transmission: `declared_record_count`, the number of records
        the client says it sent, and `declared_control_total_cents`, the sum of
        statement amounts the client says those records carry."

        The declared control total has no default, so a lodgement that leaves it out
        is refused on shape rather than defaulted to zero, and no file row survives.

        Design: Corner/entities/data_file_creation_missing_required_declared_total_returns_invalid_request
        """
        fx.set_clock(api)
        client = fx.register_client(
            api, client_code="CLE5", name="Required Field Savings"
        )

        validate_error(
            api.create_data_file(
                {
                    "client_id": client["id"],
                    "file_name": "e5-no-total.csv",
                    "format_spec_code": "DELIMITED",
                    "declared_record_count": 3,
                },
                CLIENT_LIAISON,
            ),
            ApiErrorId.VALIDATION.value,
            422,
        )

        _rows, meta = validate_paginated(
            api.list_client_data_files(client["id"], CLIENT_LIAISON)
        )
        assert meta["total_count"] == 0

    def test_the_actual_counters_start_empty_and_are_recomputed_at_the_check(
        self, api: ApiClient
    ):
        """PRD §3.3: "The file begins in status `RECEIVED` with `received_at` taken from
        the logical clock, and every derived counter — `actual_record_count`,
        `actual_control_total_cents`, `record_count_variance`,
        `control_total_variance_cents`, `control_total_variance_bp`,
        `format_error_count` and `amendment_count` — initialised to 0, with
        `accepted_at` null."

        Lodgement leaves the computed counters at zero rather than copying the
        declarations, and the control check recomputes them from the attached records,
        landing a truthful file on zero variance and acceptance.

        Design: Corner/entities/data_file_actual_totals_are_computed_from_attached_records
        """
        fx.set_clock(api)
        client = fx.register_client(
            api, client_code="CLE7", name="Computed Totals Credit Union"
        )
        lodged = fx.lodge_data_file(
            api,
            client["id"],
            file_name="e7-clean.csv",
            declared_record_count=2,
            declared_control_total_cents=20000,
        )
        a.assert_data_file(lodged)
        assert lodged["actual_record_count"] == 0
        assert lodged["actual_control_total_cents"] == 0
        assert lodged["status"] == "RECEIVED"

        fx.attach_records(
            api,
            lodged["id"],
            [
                fx.record_spec(
                    "ABC1001",
                    1,
                    10000,
                    address_line1="700 Ledger Lane",
                    city="Atlanta",
                    region_code="GA",
                    postal_code="30301",
                    postal_code_plus4="7001",
                ),
                fx.record_spec(
                    "ABC1002",
                    2,
                    10000,
                    address_line1="702 Ledger Lane",
                    city="Atlanta",
                    region_code="GA",
                    postal_code="30301",
                    postal_code_plus4="7002",
                ),
            ],
        )
        validated = fx.validate_file_format(api, lodged["id"])
        assert validated["format_error_count"] == 0
        assert validated["status"] == "FORMAT_VALIDATED"

        checked = fx.run_control_check(api, lodged["id"])
        assert checked["actual_record_count"] == 2
        assert checked["actual_control_total_cents"] == 20000
        assert checked["record_count_variance"] == 0
        assert checked["control_total_variance_cents"] == 0
        assert checked["control_total_variance_bp"] == 0
        assert checked["status"] == "ACCEPTED"
        assert checked["amendment_count"] == 0
        a.assert_instant(
            checked["accepted_at"], "2026-08-01T00:00:00Z", "file.accepted_at"
        )


class TestStatementRecordEntitySurface:
    """The record row: its own not-found code, and its parent's."""

    def test_an_unknown_record_id_resolves_to_the_record_s_own_not_found(
        self, api: ApiClient
    ):
        """PRD §2.5: "Each entity owns its own not-found code: `ERR_CLIENT_NOT_FOUND`,
        `ERR_TEMPLATE_NOT_FOUND`, `ERR_INSERT_STOCK_NOT_FOUND`,
        `ERR_DATA_FILE_NOT_FOUND`, `ERR_RECORD_NOT_FOUND`, `ERR_JOB_NOT_FOUND`,
        `ERR_ENROLLMENT_NOT_FOUND`, `ERR_MAIL_PIECE_NOT_FOUND`,
        `ERR_PRESS_LINE_NOT_FOUND`, `ERR_PRINT_RUN_NOT_FOUND`,
        `ERR_ENTRY_FACILITY_NOT_FOUND`, `ERR_PRESORT_BATCH_NOT_FOUND`,
        `ERR_RETURN_NOT_FOUND` and `ERR_DR_SITE_NOT_FOUND`."

        A record identifier that matches nothing yields the record-specific
        not-found rather than a generic one, in the error envelope's two-field shape.

        Design: Corner/entities/statement_record_fetch_with_unknown_id_returns_not_found
        """
        fx.set_clock(api)

        error = validate_error(
            api.get_statement_record(NON_EXISTENT_UUID, CLIENT_LIAISON),
            ApiErrorId.RECORD_NOT_FOUND.value,
            404,
        )
        assert set(error) == {"error_id", "message"}
        assert error["message"].strip() != ""

    def test_an_unresolvable_parent_in_the_body_is_the_parent_s_not_found(
        self, api: ApiClient
    ):
        """PRD §2.5: "Identifiers supplied inside a request body are resolved with the same
        not-found codes as their path equivalents."

        The body is shape-valid, so the attachment fails on resolving the file it
        names rather than on validation, and reports the file's own not-found code.

        Design: Corner/entities/statement_record_with_unknown_data_file_returns_not_found
        """
        fx.set_clock(api)

        validate_error(
            api.create_statement_record(
                f.statement_record_payload(
                    NON_EXISTENT_UUID,
                    account_ref="ABC1201",
                    sequence_no=1,
                    statement_amount_cents=5000,
                    address_line1="900 Orphan Way",
                    city="Atlanta",
                    region_code="GA",
                    postal_code="30301",
                    postal_code_plus4=None,
                ),
                CLIENT_LIAISON,
            ),
            ApiErrorId.DATA_FILE_NOT_FOUND.value,
            404,
        )


class TestCompositionJobEntitySurface:
    """Every body reference is resolved on its own account."""

    def test_a_resolvable_file_does_not_mask_an_unresolvable_template(
        self, api: ApiClient
    ):
        """PRD §2.10: "Body reference existence, reusing each referenced entity's not-found
        code."

        The job body names a real accepted file and a template that does not exist,
        and the refusal is the template's not-found; the file is left unconsumed and no
        job row is created.

        Design: Corner/entities/composition_job_with_unknown_template_id_returns_not_found
        """
        fx.set_clock(api)
        client = fx.register_client(
            api, client_code="CLE13", name="Graph Integrity Trust"
        )
        bundle = fx.accepted_file(
            api,
            client["id"],
            [
                fx.record_spec(
                    "ABC1301",
                    1,
                    4000,
                    address_line1="1000 Graph Court",
                    city="Atlanta",
                    region_code="GA",
                    postal_code="30301",
                    postal_code_plus4="9001",
                )
            ],
            file_name="e13.csv",
            declared_record_count=1,
            declared_control_total_cents=4000,
        )
        assert bundle.status == "ACCEPTED"

        validate_error(
            api.create_composition_job(
                f.composition_job_payload(bundle.id, NON_EXISTENT_UUID),
                COMPOSITION_OPERATOR,
            ),
            ApiErrorId.TEMPLATE_NOT_FOUND.value,
            404,
        )

        assert fx.read_data_file(api, bundle.id)["status"] == "ACCEPTED"
        _rows, meta = validate_paginated(
            api.list_composition_jobs(
                COMPOSITION_OPERATOR, {"data_file_id": bundle.id, "limit": 100}
            )
        )
        assert meta["total_count"] == 0


class TestScanEventEntitySurface:
    """The audit log is written once and never revised."""

    def test_a_repeated_stage_read_appends_a_refusal_rather_than_editing(
        self, api: ApiClient
    ):
        """PRD §2.4: "It has no `updated_at` and no `version`, because a recorded barcode
        read is never revised — a refused read is stored as a refused read rather than
        corrected, and a run abort leaves the scan log untouched while reverting the
        piece it described."

        The second read of the same stage is stored, not rejected, as a refused row
        carrying the duplicate reason at its own instant, leaving the first row intact;
        the log has no version to revise, and the refusal moves only the evidential
        dimension.

        Design: Corner/entities/scan_event_rows_are_immutable_and_append_only
        """
        pipeline = fx.printing_job(
            api,
            client_code="CLE11",
            client_overrides={"name": "Immutable Audit Bank"},
            template_code="T-E11",
            press_line_code="PL-E11",
            press_line_overrides={"sheets_per_hour": 600, "daily_sheet_capacity": 9000},
            file_name="e11.csv",
            specs=[
                fx.record_spec(
                    "ABC1101",
                    1,
                    9000,
                    address_line1="800 Immutable Road",
                    city="Atlanta",
                    region_code="GA",
                    postal_code="30301",
                    postal_code_plus4="8001",
                )
            ],
        )
        piece = pipeline.piece
        barcode = piece["imb_barcode"]

        first = fx.scan_stage(api, piece["id"], "PRINT", barcode, device_code="SC-01")
        assert first["accepted"] is True
        assert first["rejection_reason"] == "NONE"
        a.assert_scan_event(first)
        a.assert_append_only_fields(first, "ScanEvent")
        a.assert_instant(
            first["scanned_at"], "2026-08-05T09:00:00Z", "first_scan.scanned_at"
        )

        fx.set_clock(api, "2026-08-05T09:05:00Z")
        second = fx.scan_stage(api, piece["id"], "PRINT", barcode, device_code="SC-01")
        assert second["accepted"] is False
        assert second["rejection_reason"] == "DUPLICATE_STAGE"
        a.assert_append_only_fields(second, "ScanEvent")
        a.assert_instant(
            second["scanned_at"], "2026-08-05T09:05:00Z", "second_scan.scanned_at"
        )
        assert second["id"] != first["id"]

        log = fx.scan_events(api, piece["id"])
        assert len(log) == 2
        assert log[0]["id"] == first["id"]
        assert log[0]["stage"] == "PRINT"
        assert log[0]["accepted"] is True
        assert log[0]["rejection_reason"] == "NONE"
        assert log[1]["rejection_reason"] == "DUPLICATE_STAGE"
        for row in log:
            assert "version" not in row
            assert "updated_at" not in row

        reread = fx.read_piece(api, piece["id"])
        assert reread["integrity_status"] == "DUPLICATE_SCAN"
        assert reread["piece_status"] == "PRINTED"
        assert reread["accepted_scan_count"] == 1
        assert reread["last_scan_stage"] == "PRINT"
