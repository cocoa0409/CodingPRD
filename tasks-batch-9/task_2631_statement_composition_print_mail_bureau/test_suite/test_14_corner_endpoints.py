"""Endpoints probed on the behaviour that is theirs alone.

Each test drives one endpoint through the distinguishing half of its contract:
a bulk action that skips rather than fails, a read that writes nothing, a
release that closes a backlog, an audit log that records refusals, an inverse
transition gated on one status, and a request field whose absence hands the
choice to the selector.
"""

import pytest

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
    CLIENT_LIAISON,
    INTEGRITY_AUDITOR,
    POSTAGE_CONTROLLER,
    PRODUCTION_SCHEDULER,
)


class TestPaperlessSyncSkipsWhatItCannotConfirm:
    """One synchronisation run over a confirmable row, a revoked row and a name
    that matches nothing."""

    def test_only_the_pending_row_is_confirmed_and_the_call_still_succeeds(
        self, api: ApiClient
    ):
        """PRD §3.1: "Account references in the list that match no `PENDING` row of that
        client are ignored in silence — they are neither an error nor a no-op worth
        reporting."

        The run confirms the PENDING enrollment, silently ignores both the
        REVOKED row and an account reference with no row at all, and advances the
        client's epoch exactly once for the whole batch.

        Design: Corner/endpoints/paperless_sync_confirms_only_pending_rows_and_ignores_the_rest
        """
        fx.set_clock(api)
        client = fx.register_client(
            api,
            client_code="CLE1",
            name="Skip Not Fail Savings",
            dr_readiness_required=False,
        )
        version_before = client["version"]
        assert client["paperless_sync_epoch"] == 0

        pending = fx.enroll_account(api, client["id"], "ABC3001", "EMAIL")
        revoked = fx.enroll_account(api, client["id"], "ABC3002", "PORTAL")
        revoked = get_success_data(
            api.revoke_enrollment(revoked["id"], CLIENT_LIAISON), 200
        )
        assert revoked["status"] == "REVOKED"
        assert pending["status"] == "PENDING"

        synced = get_success_data(
            api.paperless_sync(
                client["id"],
                f.paperless_sync_payload(["ABC3001", "ABC3002", "ABC9999"]),
                CLIENT_LIAISON,
            ),
            200,
        )

        assert synced["paperless_sync_epoch"] == 1
        assert synced["version"] == version_before + 1

        confirmed = get_success_data(api.get_enrollment(pending["id"], CLIENT_LIAISON))
        assert confirmed["status"] == "ENROLLED"
        assert confirmed["enrolled_epoch"] == 1
        assert confirmed["suppression_effective"] is True
        a.assert_instant(
            confirmed["confirmed_at"], "2026-08-01T00:00:00Z", "enrollment.confirmed_at"
        )

        untouched = get_success_data(api.get_enrollment(revoked["id"], CLIENT_LIAISON))
        assert untouched["status"] == "REVOKED"
        assert untouched["enrolled_epoch"] is None
        assert untouched["suppression_effective"] is False

        rows, meta = validate_paginated(
            api.list_client_enrollments(client["id"], CLIENT_LIAISON, {"limit": 50})
        )
        assert meta["total_count"] == 2
        assert {row["account_ref"] for row in rows} == {"ABC3001", "ABC3002"}


class TestIntegritySummaryIsASideEffectFreeRead:
    """The same computed read taken before reconciliation, after it, and twice
    in a row."""

    def test_the_summary_reports_what_reconcile_wrote_and_never_writes_itself(
        self, api: ApiClient
    ):
        """PRD §3.7: "A read-only integrity summary capability exposes
        `accountable_piece_count`, `print_piece_count`, `matched_piece_count`,
        `missing_scan_count`, `duplicate_scan_count`, `reprint_chain_depth` and
        `integrity_status` as last written, without mutating anything and without
        touching `version`."

        Before reconciliation the counters read zero and the roll-up reads
        PENDING; reconciliation is what fills them in; and two consecutive reads
        of the filled-in summary leave the job's version exactly where
        reconciliation left it.

        Design: Corner/endpoints/integrity_summary_reads_the_reconciled_counters_without_writing
        """
        fx.set_clock(api)
        client = fx.register_client(
            api,
            client_code="CLE2",
            name="Summary Read Surety",
            dr_readiness_required=False,
        )
        line = fx.register_press_line(
            api,
            line_code="PL-E2",
            capabilities=["DUPLEX"],
            sheets_per_hour=600,
            daily_sheet_capacity=2000,
        )
        template = fx.create_active_template(
            api,
            client["id"],
            template_code="T-E2",
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
                    "ABC3101",
                    1,
                    9000,
                    address_line1="3300 Summary Street",
                    postal_code_plus4="3301",
                )
            ],
            file_name="e2.csv",
        )
        job = fx.compose_job(api, bundle.id, template["id"])
        job = fx.presort_job(api, job["id"])
        piece = fx.list_pieces(api, job["id"])[0]
        run = fx.schedule_job(api, job["id"], "2026-08-05T09:00:00Z", line["id"])
        fx.set_clock(api, "2026-08-05T09:00:00Z")
        fx.start_run(api, run["id"])
        events = fx.scan_piece_fully(api, piece, device_code="SCN-E2")
        assert [event["accepted"] for event in events] == [True, True, True]
        fx.set_clock(api, "2026-08-05T10:00:00Z")
        fx.complete_run(api, run["id"])

        before_job = fx.read_job(api, job["id"])
        assert before_job["status"] == "PRINTED"

        before = fx.read_integrity_summary(api, job["id"])
        a.assert_integrity_counters(before, 0, 0, 0, "PENDING")
        assert before["accountable_piece_count"] == 1
        assert before["print_piece_count"] == 1
        assert before["reprint_chain_depth"] == 0
        assert fx.read_job(api, job["id"])["version"] == before_job["version"]

        reconciled = fx.reconcile(api, job["id"])
        assert reconciled["status"] == "VERIFIED"
        assert reconciled["integrity_status"] == "MATCHED"
        assert reconciled["version"] == before_job["version"] + 1

        after = fx.read_integrity_summary(api, job["id"])
        a.assert_integrity_counters(after, 1, 0, 0, "MATCHED")
        assert after["reprint_chain_depth"] == 0

        repeat = fx.read_integrity_summary(api, job["id"], POSTAGE_CONTROLLER)
        a.assert_integrity_counters(repeat, 1, 0, 0, "MATCHED")
        assert fx.read_job(api, job["id"])["version"] == reconciled["version"]


class TestAddressFeedbackReleaseClosesTheBacklog:
    """One release over both classification branches, then the same call with an
    empty backlog."""

    def test_both_branches_go_out_under_one_sequence_and_the_second_call_is_refused(
        self, api: ApiClient
    ):
        """PRD §3.9: "The release requires at least one undeliverable return of that client
        sitting in disposition `ADDRESS_UPDATED` or `UNRESOLVED`; a client with no such
        backlog is refused with `ERR_NO_PENDING_FEEDBACK` (HTTP 409)."

        The corrected return and the deceased one leave in a single batch that
        carries one client-scoped sequence number, the pending counter is reset to
        zero, and an immediate second release has nothing left to send.

        Design: Corner/endpoints/address_feedback_release_closes_every_classified_return_and_a_second_release_is_rejected
        """
        fx.set_clock(api)
        client = fx.register_client(
            api,
            client_code="CLE3",
            name="Feedback Batch Bancshares",
            dr_readiness_required=False,
        )
        template = fx.create_active_template(
            api,
            client["id"],
            template_code="T-E3",
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
                    "ABC3201",
                    1,
                    4000,
                    address_line1="3400 Return Row",
                    postal_code_plus4="3401",
                ),
                fx.record_spec(
                    "ABC3202",
                    2,
                    4000,
                    address_line1="3402 Return Row",
                    postal_code_plus4="3402",
                ),
            ],
            file_name="e3.csv",
        )
        job = fx.compose_job(api, bundle.id, template["id"])
        pieces = fx.list_pieces(api, job["id"])
        assert [piece["piece_status"] for piece in pieces] == ["COMPOSED", "COMPOSED"]
        record_one, record_two = bundle.records

        return_one = fx.intake_return(api, pieces[0]["id"], "MOVED_NO_FORWARD")
        return_two = fx.intake_return(api, pieces[1]["id"], "DECEASED")
        classified_one = fx.classify_return(
            api, return_one["id"], "3500 Forwarding Lane", "30302"
        )
        classified_two = fx.classify_return(
            api, return_two["id"], "3502 Forwarding Lane", "30303"
        )
        assert classified_one["disposition"] == "ADDRESS_UPDATED"
        assert classified_two["disposition"] == "UNRESOLVED"
        assert classified_two["corrected_address_line1"] is None
        assert classified_two["corrected_postal_code"] is None
        assert fx.read_client(api, client["id"])["pending_address_feedback_count"] == 2

        released = fx.release_feedback(api, client["id"], "August correction file")

        assert released["address_feedback_batch_count"] == 1
        assert released["pending_address_feedback_count"] == 0

        sent_one = fx.read_return(api, return_one["id"])
        sent_two = fx.read_return(api, return_two["id"])
        for sent in (sent_one, sent_two):
            assert sent["disposition"] == "FEEDBACK_SENT"
            assert sent["feedback_batch_seq"] == 1
            a.assert_instant(
                sent["feedback_sent_at"],
                "2026-08-01T00:00:00Z",
                "return.feedback_sent_at",
            )

        updated = fx.read_record(api, record_one["id"])
        assert updated["address_line1"] == "3500 Forwarding Lane"
        assert updated["postal_code"] == "30302"
        assert updated["hygiene_status"] == "CORRECTED"
        assert updated["address_update_pending"] is False

        kept = fx.read_record(api, record_two["id"])
        assert kept["address_line1"] == "3402 Return Row"
        assert kept["postal_code"] == "30301"
        assert kept["hygiene_status"] == "STALE"
        assert kept["address_update_pending"] is False

        again = api.release_address_feedback(
            client["id"], f.address_feedback_payload("second attempt"), CLIENT_LIAISON
        )
        validate_error(again, ApiErrorId.NO_PENDING_FEEDBACK.value, 409)
        assert fx.read_client(api, client["id"])["address_feedback_batch_count"] == 1


class TestUnknownBarcodeIsEvidenceNotFailure:
    """A misread envelope recorded against a scannable piece, then the correct
    read on the very next call."""

    def test_the_refused_read_is_stored_and_moves_nothing_on_the_piece(
        self, api: ApiClient
    ):
        """PRD §3.7: "A `scanned_barcode` that does not equal the piece's `imb_barcode` is
        stored with `accepted` false and `rejection_reason` `UNKNOWN_BARCODE`, and
        changes no field on the piece at all — the bureau has read something that is not
        this piece, which says nothing about this piece."

        A barcode that is not this piece's is stored as a created scan event with
        accepted false and rejection_reason UNKNOWN_BARCODE, leaves every field of
        the piece — including its version — exactly as it was, and does not consume
        the PRINT stage.

        Design: Corner/endpoints/unknown_barcode_scan_is_recorded_as_a_rejected_event_and_leaves_the_piece_untouched
        """
        fx.set_clock(api)
        client = fx.register_client(
            api,
            client_code="CLE4",
            name="Barcode Mismatch Mutual",
            dr_readiness_required=False,
        )
        line = fx.register_press_line(
            api,
            line_code="PL-E4",
            capabilities=["DUPLEX"],
            sheets_per_hour=600,
            daily_sheet_capacity=2000,
        )
        template = fx.create_active_template(
            api,
            client["id"],
            template_code="T-E4",
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
                    "ABC3301",
                    1,
                    9000,
                    address_line1="3600 Mismatch Manor",
                    postal_code_plus4="3601",
                )
            ],
            file_name="e4.csv",
        )
        job = fx.compose_job(api, bundle.id, template["id"])
        job = fx.presort_job(api, job["id"])
        piece = fx.list_pieces(api, job["id"])[0]
        run = fx.schedule_job(api, job["id"], "2026-08-05T09:00:00Z", line["id"])
        fx.set_clock(api, "2026-08-05T09:00:00Z")
        fx.start_run(api, run["id"])

        before = fx.read_piece(api, piece["id"])
        assert before["piece_status"] == "COMPOSED"
        assert before["last_scan_stage"] == "NONE"
        assert before["accepted_scan_count"] == 0

        response = api.create_scan(
            piece["id"],
            f.scan_payload("PRINT", "NOT-THE-BARCODE", "SCN-E4"),
            INTEGRITY_AUDITOR,
        )
        rejected = validate_success(response, 201)
        assert rejected["accepted"] is False
        assert rejected["rejection_reason"] == "UNKNOWN_BARCODE"
        assert rejected["stage"] == "PRINT"
        assert rejected["scanned_barcode"] == "NOT-THE-BARCODE"

        after = fx.read_piece(api, piece["id"])
        assert after["piece_status"] == "COMPOSED"
        assert after["last_scan_stage"] == "NONE"
        assert after["accepted_scan_count"] == 0
        assert after["integrity_status"] == "UNVERIFIED"
        assert after["version"] == before["version"]

        accepted = fx.scan_stage(
            api, piece["id"], "PRINT", piece["imb_barcode"], "SCN-E4"
        )
        assert accepted["accepted"] is True
        assert accepted["rejection_reason"] == "NONE"
        printed = fx.read_piece(api, piece["id"])
        assert printed["piece_status"] == "PRINTED"
        assert printed["last_scan_stage"] == "PRINT"
        assert printed["accepted_scan_count"] == 1

        events, meta = validate_paginated(
            api.list_scan_events(piece["id"], INTEGRITY_AUDITOR, {"limit": 50})
        )
        assert meta["total_count"] == 2
        assert [event["accepted"] for event in events] == [False, True]


class TestUnsealIsGatedOnTheBatchBeingSealed:
    """The identical unseal call against an OPEN batch and against the same batch
    one seal later."""

    def test_the_premature_unseal_is_refused_and_the_same_call_succeeds_after_sealing(
        self, api: ApiClient
    ):
        """PRD §3.8: "A `PostageController` unseals a `SEALED` batch — a batch that is
        `OPEN` or already `MANIFESTED` is refused with `ERR_BATCH_NOT_SEALED` (HTTP
        409)."

        Unsealing a batch that has never been sealed is refused as not sealed
        even though the owning job is VERIFIED, and the same call one seal later
        returns the batch to OPEN with its estimate and sealing user cleared and
        the escrow restored.

        Design: Corner/endpoints/unseal_before_a_seal_is_rejected_and_permitted_immediately_after
        """
        fx.set_clock(api)
        client = fx.register_client(
            api,
            client_code="CLE5",
            name="Unseal Guard Guaranty",
            dr_readiness_required=False,
        )
        funded = fx.fund_client(api, client["id"], 100000, "wire-e5")
        assert funded["postage_escrow_available_cents"] == 100000
        line = fx.register_press_line(
            api,
            line_code="PL-E5",
            capabilities=["DUPLEX"],
            sheets_per_hour=600,
            daily_sheet_capacity=2000,
        )
        template = fx.create_active_template(
            api,
            client["id"],
            template_code="T-E5",
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
                    "ABC3401",
                    1,
                    9000,
                    address_line1="3700 Seal Gate",
                    postal_code_plus4="3701",
                )
            ],
            file_name="e5.csv",
        )
        job = fx.compose_job(api, bundle.id, template["id"])
        job = fx.presort_job(api, job["id"])
        batch = fx.list_batches(api, job["id"])[0]
        assert batch["status"] == "OPEN"
        assert batch["presort_bucket"] == "MIXED_AADC"
        assert batch["piece_count"] == 1
        assert batch["estimated_postage_cents"] is None
        piece = fx.list_pieces(api, job["id"])[0]
        run = fx.schedule_job(api, job["id"], "2026-08-05T09:00:00Z", line["id"])
        fx.set_clock(api, "2026-08-05T09:00:00Z")
        fx.start_run(api, run["id"])
        fx.scan_piece_fully(api, piece, device_code="SCN-E5")
        fx.set_clock(api, "2026-08-05T10:00:00Z")
        fx.complete_run(api, run["id"])
        verified = fx.reconcile(api, job["id"])
        assert verified["status"] == "VERIFIED"

        premature = api.unseal_batch(batch["id"], POSTAGE_CONTROLLER)
        validate_error(premature, ApiErrorId.BATCH_NOT_SEALED.value, 409)
        still_open = fx.read_batch(api, batch["id"])
        assert still_open["status"] == "OPEN"
        assert still_open["estimated_postage_cents"] is None
        assert still_open["sealed_by_user_id"] is None

        client_version = fx.read_client(api, client["id"])["version"]
        sealed = fx.seal_batch(api, batch["id"], client_version)
        assert sealed["status"] == "SEALED"
        assert sealed["estimated_postage_cents"] == 62
        assert sealed["estimated_postage_cents"] == a.expected_gross_postage_cents(
            "FIRST_CLASS", "MIXED_AADC", 1
        )
        assert sealed["sealed_by_user_id"] is not None

        unsealed = fx.unseal_batch(api, batch["id"])
        assert unsealed["status"] == "OPEN"
        assert unsealed["estimated_postage_cents"] is None
        assert unsealed["sealed_by_user_id"] is None

        reread = fx.read_client(api, client["id"])
        assert reread["postage_committed_cents"] == 0
        assert reread["postage_escrow_available_cents"] == 100000
        assert reread["postage_deposited_cents"] == 100000
        a.assert_escrow_ledger(reread)


class TestOmittingThePressLineRunsTheSelector:
    """The same scheduling endpoint called once with a named line and once
    without."""

    def test_naming_a_line_records_explicit_and_omitting_it_records_selected(
        self, api: ApiClient
    ):
        """PRD §3.6: "The chosen line is recorded on the run as `press_line_id`, its score
        as `selection_score`, and `selection_mode` as `SELECTED`."

        Naming the line records selection_mode EXPLICIT and omitting it records
        SELECTED, and because the score is computed either way the two runs differ
        only in mode and in the headroom the second one sees, the first run's
        committed sheet having already been taken off the line.

        Design: Corner/endpoints/omitting_the_press_line_selects_one_and_records_selection_mode_selected
        """
        fx.set_clock(api)
        client = fx.register_client(
            api,
            client_code="CLE6",
            name="Selector Mode Casualty",
            dr_readiness_required=False,
        )
        line = fx.register_press_line(
            api,
            line_code="PL-E6",
            capabilities=["DUPLEX"],
            sheets_per_hour=600,
            daily_sheet_capacity=1000,
        )
        template = fx.create_active_template(
            api,
            client["id"],
            template_code="T-E6",
            sheets_per_document=1,
            duplex_required=False,
            color_pages_per_document=0,
            mail_class_preference="FIRST_CLASS",
        )

        def _presorted_job(file_name, account_ref, address_line1, plus4):
            bundle = fx.accepted_file(
                api,
                client["id"],
                [
                    fx.record_spec(
                        account_ref,
                        1,
                        5000,
                        address_line1=address_line1,
                        postal_code_plus4=plus4,
                    )
                ],
                file_name=file_name,
            )
            job = fx.compose_job(api, bundle.id, template["id"])
            return fx.presort_job(api, job["id"])

        job_one = _presorted_job(
            "e6a.csv", "ABC3501", "3800 Selector Circle", "3801"
        )
        job_two = _presorted_job(
            "e6b.csv", "ABC3502", "3802 Selector Circle", "3802"
        )

        explicit = fx.schedule_job(
            api, job_one["id"], "2026-08-05T09:00:00Z", line["id"]
        )
        assert explicit["selection_mode"] == "EXPLICIT"
        assert explicit["press_line_id"] == line["id"]
        assert explicit["planned_sheet_count"] == 1
        assert explicit["selection_score"] == pytest.approx(
            a.expected_selection_score(1000, 600, 1), abs=0.01
        )
        assert explicit["selection_score"] == pytest.approx(340.00, abs=0.01)

        selected = get_success_data(
            api.schedule_job(
                job_two["id"],
                f.schedule_payload("2026-08-05T11:00:00Z"),
                PRODUCTION_SCHEDULER,
            ),
            201,
        )
        assert selected["selection_mode"] == "SELECTED"
        assert selected["press_line_id"] == line["id"]
        assert selected["planned_sheet_count"] == 1
        assert selected["selection_score"] == pytest.approx(
            a.expected_selection_score(1000 - 1, 600, 1), abs=0.01
        )
        assert selected["selection_score"] == pytest.approx(339.40, abs=0.01)
        a.assert_instant(
            selected["window_start"], "2026-08-05T11:00:00Z", "run.window_start"
        )
        a.assert_instant(
            selected["window_end"], "2026-08-05T12:00:00Z", "run.window_end"
        )

        assert fx.read_job(api, job_one["id"])["status"] == "SCHEDULED"
        assert fx.read_job(api, job_two["id"])["status"] == "SCHEDULED"
        reread = fx.read_press_line(api, line["id"])
        assert reread["committed_sheet_count"] == 2
        a.assert_press_ledger(reread)
