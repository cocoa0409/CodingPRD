"""Refusals proved to be the specific code the contract names.

Each test fires a family of guards that a single generic rejection could not
tell apart: eleven distinct not-found identifiers, a singleton constraint that
is not a duplicate-code, three separate guards on the return queue, three on a
sealed batch, four eligibility faults on the press floor, a per-piece insert
reservation and a per-piece integrity verdict.
"""

import pytest

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
    BUREAU_ADMIN,
    CLIENT_LIAISON,
    COMPOSITION_OPERATOR,
    INTEGRITY_AUDITOR,
    POSTAGE_CONTROLLER,
    POSTAGE_CONTROLLER_2,
    PRODUCTION_SCHEDULER,
)


class TestNotFoundFamilyIsPerEntity:
    """Eleven structurally identical reads against well-formed identifiers that
    match no row."""

    def test_each_path_lookup_reports_its_own_entitys_not_found_code(
        self, api: ApiClient
    ):
        """PRD §2.10: "Path existence, left to right, using each entity's own not-found
        code."

        Every path-identifier lookup answers with the not-found identifier that
        belongs to its own entity rather than one shared generic code, so the
        eleven refusals carry eleven distinct error identifiers.

        Design: Corner/errors/not_found_family_returns_each_entitys_own_error_id
        """
        fx.set_clock(api)

        probes = [
            (
                api.get_client(
                    "00000000-0000-4000-8000-000000000001", BUREAU_ADMIN
                ),
                ApiErrorId.CLIENT_NOT_FOUND,
            ),
            (
                api.get_insert_stock(
                    "00000000-0000-4000-8000-000000000002", BUREAU_ADMIN
                ),
                ApiErrorId.INSERT_STOCK_NOT_FOUND,
            ),
            (
                api.get_enrollment(
                    "00000000-0000-4000-8000-000000000003", CLIENT_LIAISON
                ),
                ApiErrorId.ENROLLMENT_NOT_FOUND,
            ),
            (
                api.get_composition_job(
                    "00000000-0000-4000-8000-000000000004", COMPOSITION_OPERATOR
                ),
                ApiErrorId.JOB_NOT_FOUND,
            ),
            (
                api.get_mail_piece(
                    "00000000-0000-4000-8000-000000000005", INTEGRITY_AUDITOR
                ),
                ApiErrorId.MAIL_PIECE_NOT_FOUND,
            ),
            (
                api.get_press_line(
                    "00000000-0000-4000-8000-000000000006", PRODUCTION_SCHEDULER
                ),
                ApiErrorId.PRESS_LINE_NOT_FOUND,
            ),
            (
                api.get_print_run(
                    "00000000-0000-4000-8000-000000000007", PRODUCTION_SCHEDULER
                ),
                ApiErrorId.PRINT_RUN_NOT_FOUND,
            ),
            (
                api.get_entry_facility(
                    "00000000-0000-4000-8000-000000000008", POSTAGE_CONTROLLER
                ),
                ApiErrorId.ENTRY_FACILITY_NOT_FOUND,
            ),
            (
                api.get_presort_batch(
                    "00000000-0000-4000-8000-000000000009", POSTAGE_CONTROLLER
                ),
                ApiErrorId.PRESORT_BATCH_NOT_FOUND,
            ),
            (
                api.get_return(
                    "00000000-0000-4000-8000-00000000000a", INTEGRITY_AUDITOR
                ),
                ApiErrorId.RETURN_NOT_FOUND,
            ),
            (
                api.get_dr_site(
                    "00000000-0000-4000-8000-00000000000b", BUREAU_ADMIN
                ),
                ApiErrorId.DR_SITE_NOT_FOUND,
            ),
        ]

        for response, expected in probes:
            validate_error(response, expected.value, 404)

        reported = [expected.value for _response, expected in probes]
        assert len(set(reported)) == len(reported) == 11


class TestDisasterRecoverySiteIsASingleton:
    """A second site creation whose payload duplicates nothing."""

    def test_a_different_site_code_still_collides_with_the_singleton(
        self, api: ApiClient
    ):
        """PRD §2.11: "The bureau operates exactly one disaster-recovery site, and at most
        one may exist in the system; a second creation attempt is refused with
        `ERR_DR_SITE_ALREADY_EXISTS` (HTTP 409)."

        The bureau operates exactly one recovery site, so a second creation is
        refused as already existing even though its code and its replication lag
        both differ from the first, and the surviving row is untouched.

        Design: Corner/errors/second_dr_site_creation_is_rejected_as_already_existing
        """
        fx.set_clock(api)
        first = fx.register_dr_site(
            api, site_code="DR-X2-PRIMARY", replication_lag_minutes=5
        )

        response = api.create_dr_site(
            f.dr_site_payload("DR-X2-SECONDARY", 7), BUREAU_ADMIN
        )
        validate_error(response, ApiErrorId.DR_SITE_ALREADY_EXISTS.value, 409)

        survivor = fx.read_dr_site(api, first["id"])
        assert survivor["site_code"] == "DR-X2-PRIMARY"
        assert survivor["replication_lag_minutes"] == 5
        assert survivor["readiness_status"] == "UNTESTED"
        assert survivor["drill_count"] == 0
        assert survivor["version"] == first["version"]


class TestReturnQueueGuardsAreDistinct:
    """One printed piece with a classified return and one suppressed piece that
    was never mailed."""

    def test_the_duplicate_the_reclassification_and_the_suppressed_piece_each_fail_differently(
        self, api: ApiClient
    ):
        """PRD §3.9: "At most one return may exist per piece; a second attempt against the
        same piece is refused with `ERR_RETURN_DUPLICATE` (HTTP 409)."

        A second return against the same piece is a duplicate, a second
        classification of a return that has already forked is an invalid state, and
        a return aimed at a suppressed piece is not scannable — three guards on one
        job, each with its own code.

        Design: Corner/errors/return_intake_rejects_a_duplicate_a_reclassification_and_a_suppressed_piece
        """
        fx.set_clock(api)
        client = fx.register_client(
            api,
            client_code="CLX3",
            name="Return Queue Reinsurance",
            dr_readiness_required=False,
        )
        template = fx.create_active_template(
            api,
            client["id"],
            template_code="T-X3",
            sheets_per_document=1,
            duplex_required=False,
            color_pages_per_document=0,
            mail_class_preference="FIRST_CLASS",
        )
        fx.suppress_account(api, client["id"], "ABC4002", "EMAIL")
        bundle = fx.accepted_file(
            api,
            client["id"],
            [
                fx.record_spec(
                    "ABC4001",
                    1,
                    4000,
                    address_line1="3900 Queue Quay",
                    postal_code_plus4="3901",
                ),
                fx.record_spec(
                    "ABC4002",
                    2,
                    4000,
                    address_line1="3902 Queue Quay",
                    postal_code_plus4="3902",
                ),
            ],
            file_name="x3.csv",
        )
        job = fx.compose_job(api, bundle.id, template["id"])
        printed_piece = fx.list_pieces(api, job["id"], piece_status="COMPOSED")[0]
        suppressed_piece = fx.list_pieces(api, job["id"], piece_status="SUPPRESSED")[0]

        scanned = fx.intake_return(api, printed_piece["id"], "VACANT")
        classified = fx.classify_return(api, scanned["id"])
        assert classified["disposition"] == "UNRESOLVED"

        duplicate = api.create_return(
            f.return_payload(printed_piece["id"], "REFUSED"), INTEGRITY_AUDITOR
        )
        validate_error(duplicate, ApiErrorId.RETURN_DUPLICATE.value, 409)

        reclassify = api.classify_return(
            scanned["id"],
            INTEGRITY_AUDITOR,
            f.classify_payload("4000 Second Thought Street", "30304"),
        )
        validate_error(reclassify, ApiErrorId.RETURN_INVALID_STATE.value, 409)
        reread = fx.read_return(api, scanned["id"])
        assert reread["disposition"] == "UNRESOLVED"
        assert reread["corrected_address_line1"] is None
        assert reread["corrected_postal_code"] is None
        assert reread["version"] == classified["version"]

        not_scannable = api.create_return(
            f.return_payload(suppressed_piece["id"], "VACANT"), INTEGRITY_AUDITOR
        )
        validate_error(not_scannable, ApiErrorId.PIECE_NOT_SCANNABLE.value, 409)

        _rows, printed_meta = validate_paginated(
            api.list_piece_returns(printed_piece["id"], INTEGRITY_AUDITOR, {"limit": 20})
        )
        assert printed_meta["total_count"] == 1
        _rows, suppressed_meta = validate_paginated(
            api.list_piece_returns(
                suppressed_piece["id"], INTEGRITY_AUDITOR, {"limit": 20}
            )
        )
        assert suppressed_meta["total_count"] == 0


class TestSealedBatchGuardsAreDistinct:
    """One sealed batch offered a second seal, a closed facility and three
    induction windows."""

    def test_the_reseal_the_closed_facility_and_the_malformed_windows_each_fail_differently(
        self, api: ApiClient
    ):
        """PRD §3.8: "The window must be well formed: `induction_window_start` strictly
        earlier than `induction_window_end`, and the span between them at most 1,440
        minutes, which is one day; a malformed or over-long window is refused with
        `ERR_INVALID_INDUCTION_WINDOW` (HTTP 422)."

        A second seal is refused by the open gate, the shut facility by the
        openness gate, and a zero-length window and a span one minute over the day
        limit by the window check — while the day-long window itself is accepted,
        proving the span limit is inclusive.

        Design: Corner/errors/sealed_batch_rejects_a_second_seal_a_closed_facility_and_a_malformed_window
        """
        fx.set_clock(api)
        client = fx.register_client(
            api,
            client_code="CLX4",
            name="Induction Window Wholesale",
            dr_readiness_required=False,
        )
        fx.fund_client(api, client["id"], 100000, "wire-x4")
        line = fx.register_press_line(
            api,
            line_code="PL-X4",
            capabilities=["DUPLEX"],
            sheets_per_hour=600,
            daily_sheet_capacity=2000,
        )
        shut = fx.register_entry_facility(
            api,
            facility_code="EF-X4-SHUT",
            facility_type="SCF",
            tray_capacity_per_window=10,
            discount_bp_first_class=850,
            discount_bp_marketing=400,
            status="CLOSED",
        )
        open_facility = fx.register_entry_facility(
            api,
            facility_code="EF-X4-OPEN",
            facility_type="SCF",
            tray_capacity_per_window=10,
            discount_bp_first_class=850,
            discount_bp_marketing=400,
        )
        assert shut["status"] == "CLOSED"
        assert open_facility["status"] == "OPEN"
        template = fx.create_active_template(
            api,
            client["id"],
            template_code="T-X4",
            sheets_per_document=1,
            duplex_required=False,
            color_pages_per_document=0,
            mail_class_preference="FIRST_CLASS",
        )
        bundle = fx.accepted_file(
            api,
            client["id"],
            [
                fx.record_spec(
                    "ABC4101",
                    1,
                    9000,
                    address_line1="4100 Induction Isle",
                    postal_code_plus4="4101",
                )
            ],
            file_name="x4.csv",
        )
        job = fx.compose_job(api, bundle.id, template["id"])
        job = fx.presort_job(api, job["id"])
        piece = fx.list_pieces(api, job["id"])[0]
        batch = fx.list_batches(api, job["id"])[0]
        run = fx.schedule_job(api, job["id"], "2026-08-05T09:00:00Z", line["id"])
        fx.set_clock(api, "2026-08-05T09:00:00Z")
        fx.start_run(api, run["id"])
        fx.scan_piece_fully(api, piece, device_code="SCN-X4")
        fx.set_clock(api, "2026-08-05T10:00:00Z")
        fx.complete_run(api, run["id"])
        verified = fx.reconcile(api, job["id"])
        assert verified["status"] == "VERIFIED"

        client_version = fx.read_client(api, client["id"])["version"]
        sealed = fx.seal_batch(api, batch["id"], client_version)
        assert sealed["status"] == "SEALED"
        assert sealed["estimated_postage_cents"] == 62
        assert sealed["tray_count"] == a.expected_tray_count(1) == 1

        reseal = api.seal_batch(
            batch["id"], f.seal_payload(client_version), POSTAGE_CONTROLLER
        )
        validate_error(reseal, ApiErrorId.BATCH_NOT_OPEN.value, 409)
        after_reseal = fx.read_client(api, client["id"])
        assert after_reseal["postage_committed_cents"] == 62
        assert after_reseal["postage_escrow_available_cents"] == 100000 - 62
        a.assert_escrow_ledger(after_reseal)

        closed = api.manifest_batch(
            batch["id"],
            f.manifest_payload(
                shut["id"], "2026-08-06T08:00:00Z", "2026-08-06T12:00:00Z"
            ),
            POSTAGE_CONTROLLER_2,
        )
        validate_error(closed, ApiErrorId.ENTRY_FACILITY_CLOSED.value, 409)
        assert fx.read_facility(api, shut["id"])["committed_tray_count"] == 0

        zero_length = api.manifest_batch(
            batch["id"],
            f.manifest_payload(
                open_facility["id"], "2026-08-06T08:00:00Z", "2026-08-06T08:00:00Z"
            ),
            POSTAGE_CONTROLLER_2,
        )
        validate_error(zero_length, ApiErrorId.INVALID_INDUCTION_WINDOW.value, 422)

        too_long = api.manifest_batch(
            batch["id"],
            f.manifest_payload(
                open_facility["id"], "2026-08-06T08:00:00Z", "2026-08-07T08:01:00Z"
            ),
            POSTAGE_CONTROLLER_2,
        )
        validate_error(too_long, ApiErrorId.INVALID_INDUCTION_WINDOW.value, 422)
        assert fx.read_batch(api, batch["id"])["status"] == "SEALED"

        manifested = fx.manifest_batch(
            api,
            batch["id"],
            open_facility["id"],
            "2026-08-06T08:00:00Z",
            "2026-08-07T08:00:00Z",
        )
        assert manifested["status"] == "MANIFESTED"
        assert manifested["manifested_postage_cents"] == 57
        assert manifested["manifested_postage_cents"] == a.expected_net_postage_cents(
            62, 850
        )
        assert manifested["postage_variance_cents"] == -5
        assert fx.read_facility(api, open_facility["id"])["committed_tray_count"] == 1


class TestPressFloorFaultsAreReportedSeparately:
    """One duplex job offered three lines that each fail a different eligibility
    predicate, then a fourth that passes."""

    def test_status_capability_and_capacity_each_have_their_own_code_and_the_selector_has_a_fourth(
        self, api: ApiClient
    ):
        """PRD §3.6: "If no line survives every eligibility predicate the request is
        refused with `ERR_NO_ELIGIBLE_PRESS_LINE` (HTTP 409); a line in `MAINTENANCE` is
        simply invisible to the selector."

        Naming the line under maintenance is refused as unavailable, the line
        without duplex as a capability mismatch and the line without headroom as a
        capacity breach; omitting the line while all three fail is refused by the
        selector itself; and adding one qualifying line makes the same omission
        succeed.

        Design: Corner/errors/press_line_faults_are_reported_separately_by_status_capability_and_capacity
        """
        fx.set_clock(api)
        client = fx.register_client(
            api,
            client_code="CLX5",
            name="Press Predicate Press",
            dr_readiness_required=False,
        )
        maintenance_line = fx.register_press_line(
            api,
            line_code="PL-X5M",
            capabilities=["DUPLEX"],
            sheets_per_hour=600,
            daily_sheet_capacity=1000,
            status="MAINTENANCE",
        )
        no_duplex_line = fx.register_press_line(
            api,
            line_code="PL-X5N",
            capabilities=["COLOR"],
            sheets_per_hour=600,
            daily_sheet_capacity=1000,
        )
        small_line = fx.register_press_line(
            api,
            line_code="PL-X5C",
            capabilities=["DUPLEX"],
            sheets_per_hour=600,
            daily_sheet_capacity=4,
        )
        assert maintenance_line["status"] == "MAINTENANCE"
        assert no_duplex_line["status"] == "AVAILABLE"
        assert small_line["status"] == "AVAILABLE"

        template = fx.create_active_template(
            api,
            client["id"],
            template_code="T-X5",
            duplex_required=True,
            sheets_per_document=2,
            color_pages_per_document=0,
            mail_class_preference="FIRST_CLASS",
        )
        bundle = fx.accepted_file(
            api,
            client["id"],
            [
                fx.record_spec(
                    "ABC4201", 1, 4000, address_line1="4200 Duplex Drive",
                    postal_code_plus4="4201",
                ),
                fx.record_spec(
                    "ABC4202", 2, 4000, address_line1="4202 Duplex Drive",
                    postal_code_plus4="4202",
                ),
                fx.record_spec(
                    "ABC4203", 3, 4000, address_line1="4204 Duplex Drive",
                    postal_code_plus4="4203",
                ),
            ],
            file_name="x5.csv",
        )
        job = fx.compose_job(api, bundle.id, template["id"])
        job = fx.presort_job(api, job["id"])
        assert job["print_sheet_count"] == 6

        unavailable = api.schedule_job(
            job["id"],
            f.schedule_payload("2026-08-05T09:00:00Z", maintenance_line["id"]),
            PRODUCTION_SCHEDULER,
        )
        validate_error(unavailable, ApiErrorId.PRESS_LINE_UNAVAILABLE.value, 409)

        mismatch = api.schedule_job(
            job["id"],
            f.schedule_payload("2026-08-05T09:00:00Z", no_duplex_line["id"]),
            PRODUCTION_SCHEDULER,
        )
        validate_error(
            mismatch, ApiErrorId.PRESS_LINE_CAPABILITY_MISMATCH.value, 422
        )

        over_capacity = api.schedule_job(
            job["id"],
            f.schedule_payload("2026-08-05T09:00:00Z", small_line["id"]),
            PRODUCTION_SCHEDULER,
        )
        validate_error(over_capacity, ApiErrorId.PRESS_CAPACITY_EXCEEDED.value, 409)

        no_eligible = api.schedule_job(
            job["id"],
            f.schedule_payload("2026-08-05T09:00:00Z"),
            PRODUCTION_SCHEDULER,
        )
        validate_error(no_eligible, ApiErrorId.NO_ELIGIBLE_PRESS_LINE.value, 409)
        assert fx.read_job(api, job["id"])["status"] == "PRESORTED"
        assert fx.list_runs(api, composition_job_id=job["id"]) == []

        good_line = fx.register_press_line(
            api,
            line_code="PL-X5G",
            capabilities=["DUPLEX"],
            sheets_per_hour=600,
            daily_sheet_capacity=1000,
        )
        run = get_success_data(
            api.schedule_job(
                job["id"],
                f.schedule_payload("2026-08-05T09:00:00Z"),
                PRODUCTION_SCHEDULER,
            ),
            201,
        )
        assert run["selection_mode"] == "SELECTED"
        assert run["press_line_id"] == good_line["id"]
        assert run["planned_sheet_count"] == 6
        assert run["selection_score"] == pytest.approx(
            a.expected_selection_score(1000, 600, 0), abs=0.01
        )
        assert run["selection_score"] == pytest.approx(840.00, abs=0.01)
        assert fx.read_job(api, job["id"])["status"] == "SCHEDULED"
        runs = fx.list_runs(api, composition_job_id=job["id"])
        assert len(runs) == 1
        assert runs[0]["id"] == run["id"]


class TestInsertReservationIsPerPiece:
    """Two copies of a required insert offered a three-piece file and then a
    two-piece file."""

    def test_the_three_piece_file_is_refused_and_the_two_piece_file_consumes_the_stock_exactly(
        self, api: ApiClient
    ):
        """PRD §3.4: "If any insert stock row's `on_hand_count` cannot cover the copies the
        job requires for that code, the whole composition is refused with
        `ERR_INSERT_STOCK_INSUFFICIENT` (HTTP 409)."

        Reservation is one copy per piece, so a stock of two copies cannot serve
        three pieces and the refused composition reserves nothing; the same stock
        then serves a two-piece file exactly, leaving nothing on hand.

        Design: Corner/errors/composition_is_rejected_when_the_insert_stock_cannot_cover_every_piece
        """
        fx.set_clock(api)
        stock = fx.register_insert_stock(
            api,
            insert_code="INS-X6",
            description="Scarce notice",
            jurisdiction_code="US",
            effective_from="2026-01-01T00:00:00Z",
            sheets_per_insert=1,
            received_count=2,
        )
        assert stock["on_hand_count"] == 2
        assert stock["reserved_count"] == 0
        client = fx.register_client(
            api,
            client_code="CLX6",
            name="Scarce Insert Savings",
            dr_readiness_required=False,
        )
        template = fx.create_active_template(
            api,
            client["id"],
            template_code="T-X6",
            sheets_per_document=1,
            duplex_required=False,
            color_pages_per_document=0,
            mail_class_preference="FIRST_CLASS",
            required_insert_codes=["INS-X6"],
        )
        big = fx.accepted_file(
            api,
            client["id"],
            [
                fx.record_spec(
                    "ABC4301", 1, 4000, address_line1="4300 Scarcity Street",
                    postal_code_plus4="4301",
                ),
                fx.record_spec(
                    "ABC4302", 2, 4000, address_line1="4302 Scarcity Street",
                    postal_code_plus4="4302",
                ),
                fx.record_spec(
                    "ABC4303", 3, 4000, address_line1="4304 Scarcity Street",
                    postal_code_plus4="4303",
                ),
            ],
            file_name="x6-big.csv",
        )
        small = fx.accepted_file(
            api,
            client["id"],
            [
                fx.record_spec(
                    "ABC4304", 1, 4000, address_line1="4306 Scarcity Street",
                    postal_code_plus4="4304",
                ),
                fx.record_spec(
                    "ABC4305", 2, 4000, address_line1="4308 Scarcity Street",
                    postal_code_plus4="4305",
                ),
            ],
            file_name="x6-small.csv",
        )

        refused = api.create_composition_job(
            f.composition_job_payload(big.id, template["id"]), COMPOSITION_OPERATOR
        )
        validate_error(refused, ApiErrorId.INSERT_STOCK_INSUFFICIENT.value, 409)

        after_failure = fx.read_insert_stock(api, stock["id"])
        assert after_failure["on_hand_count"] == 2
        assert after_failure["reserved_count"] == 0
        assert after_failure["consumed_count"] == 0
        a.assert_insert_stock_ledger(after_failure)
        assert fx.read_data_file(api, big.id)["status"] == "ACCEPTED"

        job = fx.compose_job(api, small.id, template["id"])
        assert job["insert_sheet_total"] == 2

        final = fx.read_insert_stock(api, stock["id"])
        assert final["on_hand_count"] == 0
        assert final["reserved_count"] == 2
        assert final["consumed_count"] == 0
        assert final["received_count"] == 2
        a.assert_insert_stock_ledger(final)


class TestReprintEligibilityIsPerPiece:
    """One held job holding a reconciled piece and a missing-scan sibling."""

    def test_the_reconciled_piece_is_refused_while_its_sibling_is_replaced(
        self, api: ApiClient
    ):
        """PRD §3.7: "The owning job must be in status `INTEGRITY_HELD`, else
        `ERR_JOB_INVALID_STATE`, and the target piece must be reprint-eligible, meaning
        its `integrity_status` is either `SCAN_MISSING` or `DUPLICATE_SCAN` and its
        `piece_status` is not already `VOID`; a piece failing that test is refused with
        `ERR_PIECE_NOT_REPRINT_ELIGIBLE` (HTTP 409)."

        Eligibility is the piece's own integrity verdict, so on one held job the
        reconciled piece is refused as not reprint eligible while the sibling that
        was never scanned is replaced by the identical call.

        Design: Corner/errors/reprint_of_a_reconciled_piece_is_rejected_as_not_reprint_eligible
        """
        fx.set_clock(api)
        client = fx.register_client(
            api,
            client_code="CLX7",
            name="Reprint Eligibility Escrow",
            dr_readiness_required=False,
        )
        line = fx.register_press_line(
            api,
            line_code="PL-X7",
            capabilities=["DUPLEX"],
            sheets_per_hour=600,
            daily_sheet_capacity=2000,
        )
        template = fx.create_active_template(
            api,
            client["id"],
            template_code="T-X7",
            sheets_per_document=1,
            duplex_required=False,
            color_pages_per_document=0,
            mail_class_preference="FIRST_CLASS",
        )
        bundle = fx.accepted_file(
            api,
            client["id"],
            [
                fx.record_spec(
                    "ABC4401", 1, 4000, address_line1="4400 Eligible Edge",
                    postal_code_plus4="4401",
                ),
                fx.record_spec(
                    "ABC4402", 2, 4000, address_line1="4402 Eligible Edge",
                    postal_code_plus4="4402",
                ),
            ],
            file_name="x7.csv",
        )
        job = fx.compose_job(api, bundle.id, template["id"])
        job = fx.presort_job(api, job["id"])
        piece_one, piece_two = fx.list_pieces(api, job["id"])
        run = fx.schedule_job(api, job["id"], "2026-08-05T09:00:00Z", line["id"])
        fx.set_clock(api, "2026-08-05T09:00:00Z")
        fx.start_run(api, run["id"])
        fx.scan_piece_fully(api, piece_one, device_code="SCN-X7")
        fx.set_clock(api, "2026-08-05T10:00:00Z")
        fx.complete_run(api, run["id"])
        held = fx.reconcile(api, job["id"])

        assert held["status"] == "INTEGRITY_HELD"
        a.assert_integrity_counters(held, 1, 1, 0, "BREACHED")
        assert fx.read_piece(api, piece_one["id"])["integrity_status"] == "RECONCILED"
        assert fx.read_piece(api, piece_two["id"])["integrity_status"] == "SCAN_MISSING"

        refused = api.create_reprint(
            piece_one["id"],
            f.reprint_payload(held["version"], "operator hunch"),
            INTEGRITY_AUDITOR,
        )
        validate_error(refused, ApiErrorId.PIECE_NOT_REPRINT_ELIGIBLE.value, 409)
        untouched = fx.read_piece(api, piece_one["id"])
        assert untouched["piece_status"] == "INDUCTED"
        assert untouched["integrity_status"] == "RECONCILED"
        assert fx.read_job(api, job["id"])["version"] == held["version"]

        replacement = fx.reprint_piece(
            api, piece_two["id"], held["version"], "no induct scan"
        )
        assert replacement["reprint_of_piece_id"] == piece_two["id"]
        assert replacement["billable"] is False
        assert replacement["piece_status"] == "COMPOSED"
        assert replacement["integrity_status"] == "UNVERIFIED"

        released = fx.read_job(api, job["id"])
        assert released["status"] == "PRINTED"
        assert released["integrity_status"] == "PENDING"
        assert released["void_piece_count"] == 1
        assert released["reprint_piece_count"] == 1
        assert released["accountable_piece_count"] == 2
        assert fx.read_piece(api, piece_two["id"])["piece_status"] == "VOID"
