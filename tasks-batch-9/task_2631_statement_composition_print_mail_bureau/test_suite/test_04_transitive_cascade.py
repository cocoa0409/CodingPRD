"""Chains where each link fires only because the previous one did.

One abort unwinds four links from a run through a press line and its pieces back
onto the job; one classification carries three links from a return through a
statement record onto a client-level counter.
"""

import pytest

from test_helpers import assertions as a
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient


AB_RECORDS = [
    fx.record_spec(
        "ACC8001",
        1,
        35000,
        address_line1="10 Abbotsford Row",
        postal_code="30301",
        postal_code_plus4="7701",
    ),
    fx.record_spec(
        "ACC8002",
        2,
        35000,
        address_line1="12 Abbotsford Row",
        postal_code="30301",
        postal_code_plus4="7702",
    ),
]


class TestAbortUnwindsFourLinks:
    """A running job whose two pieces have taken their PRINT read only."""

    @staticmethod
    def _abbotsford_running(api: ApiClient):
        pipeline = fx.printing_job(
            api,
            client_code="CLAB",
            client_overrides={"name": "Abbotsford Savings"},
            template_code="T-AB",
            template_overrides={
                "mail_class_preference": "FIRST_CLASS",
                "sheets_per_document": 1,
            },
            press_line_code="PL-AB",
            press_line_overrides={
                "sheets_per_hour": 600,
                "daily_sheet_capacity": 2000,
                "changeover_buffer_minutes": 30,
            },
            file_name="ab-cycle-01.csv",
            specs=AB_RECORDS,
            window_start="2026-08-04T09:00:00Z",
            run_start_clock="2026-08-04T09:00:00Z",
        )
        for piece in pipeline.pieces:
            fx.scan_stage(api, piece["id"], "PRINT", piece["imb_barcode"], "SC-01")
        pipeline.refresh_pieces()
        fx.set_clock(api, "2026-08-04T09:30:00Z")
        return pipeline

    def test_the_aborting_run_records_its_reason_and_closing_instant(
        self, api: ApiClient
    ):
        """PRD §3.6: "First, the run moves `RUNNING` → `ABORTED`, takes `completed_at` from
        the logical clock, records the supplied `abort_reason`, and has its `version`
        incremented by 1."

        The first link is the run itself: it leaves RUNNING for ABORTED, keeps the
        supplied reason and stamps its closing instant from the clock, having been
        planned for both sheets over the floor window.

        Design: Difficulty/transitive_cascade/print_run_abort_unwinds_a_four_link_chain
        """
        pipeline = self._abbotsford_running(api)
        before = pipeline.refresh_run()
        assert before["status"] == "RUNNING"
        assert before["planned_sheet_count"] == 2
        assert before["run_minutes"] == 60
        a.assert_instant(
            before["window_end"], "2026-08-04T10:00:00Z", "run.window_end"
        )

        aborted = fx.abort_run(api, pipeline.run_id, "EQUIPMENT_FAULT")

        a.assert_print_run(aborted)
        assert aborted["status"] == "ABORTED"
        assert aborted["abort_reason"] == "EQUIPMENT_FAULT"
        a.assert_instant(
            aborted["completed_at"], "2026-08-04T09:30:00Z", "run.completed_at"
        )
        assert aborted["version"] == before["version"] + 1

    def test_the_released_reservation_restores_the_pre_schedule_ledger(
        self, api: ApiClient
    ):
        """PRD §3.6: "Second, because the run has left the planned-or-running set, the
        line's `committed_sheet_count` is reduced by `planned_sheet_count` — restoring
        exactly the value it held before this job was scheduled, with no drift —
        `utilization_bp` is recomputed and the line's `version` is incremented by 1."

        The second link follows from the run leaving the planned-or-running set:
        the line gives back exactly the sheets this job reserved, so its committed
        total and utilisation read as they did before scheduling.

        Design: Difficulty/transitive_cascade/print_run_abort_unwinds_a_four_link_chain
        """
        pipeline = self._abbotsford_running(api)
        reserved = pipeline.refresh_press_line()
        assert reserved["committed_sheet_count"] == 2
        assert reserved["utilization_bp"] == 10
        a.assert_press_ledger(reserved)

        fx.abort_run(api, pipeline.run_id, "EQUIPMENT_FAULT")

        released = pipeline.refresh_press_line()
        assert released["committed_sheet_count"] == 0
        assert released["utilization_bp"] == 0
        a.assert_press_ledger(released)
        assert released["version"] == reserved["version"] + 1

    def test_the_printed_pieces_revert_while_their_scan_log_stands(
        self, api: ApiClient
    ):
        """PRD §3.6: "Third, because the press reservation has been released and the job no
        longer owns the capacity on which it printed, nothing that run produced may
        stand: every piece of the job whose `piece_status` is `PRINTED` and whose
        `last_scan_stage` is `PRINT` reverts `PRINTED` → `COMPOSED`, has its
        `integrity_status` reset to `UNVERIFIED`, its `accepted_scan_count` recomputed
        to 0 and its `last_scan_stage` recomputed to `NONE`, and its `version`
        incremented by 1 — while its scan-event rows are retained untouched, because the
        log records what was physically read and an abort does not un-read it."

        The third link follows from the released reservation: nothing printed on
        that run may stand, so every PRINT-read piece goes back to COMPOSED with its
        tally cleared — while the append-only log still shows the read.

        Design: Difficulty/transitive_cascade/print_run_abort_unwinds_a_four_link_chain
        """
        pipeline = self._abbotsford_running(api)
        for piece in pipeline.pieces:
            assert piece["piece_status"] == "PRINTED"
            assert piece["last_scan_stage"] == "PRINT"
            assert piece["accepted_scan_count"] == 1
            assert piece["integrity_status"] == "UNVERIFIED"

        fx.abort_run(api, pipeline.run_id, "EQUIPMENT_FAULT")

        for piece in pipeline.refresh_pieces():
            a.assert_mail_piece(piece)
            assert piece["piece_status"] == "COMPOSED"
            assert piece["last_scan_stage"] == "NONE"
            assert piece["accepted_scan_count"] == 0
            assert piece["integrity_status"] == "UNVERIFIED"
            log = fx.scan_events(api, piece["id"])
            assert len(log) == 1
            assert log[0]["stage"] == "PRINT"
            assert log[0]["accepted"] is True

    def test_the_reverted_pieces_drag_the_job_back_and_clear_its_exposure(
        self, api: ApiClient
    ):
        """PRD §3.6: "Fourth, because pieces have reverted to `COMPOSED`, the job's
        `print_sheet_count` is recomputed, its `projected_completion_at` is cleared to
        null and its `projected_penalty_cents` reset to 0, its status moves `PRINTING` →
        `PRESORTED` and its `version` is incremented by 1."

        The fourth link follows from the pieces reverting: the job returns to
        PRESORTED and its forward-looking penalty exposure is cleared, while the
        presort work the abort did not touch survives intact.

        Design: Difficulty/transitive_cascade/print_run_abort_unwinds_a_four_link_chain
        """
        pipeline = self._abbotsford_running(api)
        before = pipeline.refresh_job()
        assert before["status"] == "PRINTING"
        a.assert_instant(
            before["sla_due_at"], "2026-08-03T00:00:00Z", "job.sla_due_at"
        )
        a.assert_instant(
            before["projected_completion_at"],
            "2026-08-04T12:00:00Z",
            "job.projected_completion_at",
        )
        assert before["projected_penalty_cents"] == 90000

        fx.abort_run(api, pipeline.run_id, "EQUIPMENT_FAULT")

        after = pipeline.refresh_job()
        assert after["status"] == "PRESORTED"
        assert after["projected_completion_at"] is None
        assert after["projected_penalty_cents"] == 0
        assert after["print_sheet_count"] == 2
        assert after["version"] == before["version"] + 1

        batches = pipeline.refresh_batches()
        assert len(batches) == 1
        assert batches[0]["status"] == "OPEN"
        assert batches[0]["piece_count"] == 2


CS_RECORD = fx.record_spec(
    "ACC9001",
    1,
    12500,
    address_line1="5 Castlereagh Terrace",
    city="Reno",
    region_code="NV",
    postal_code="89501",
    postal_code_plus4="8801",
)


class TestClassificationCascadesToTheClientCounter:
    """One inducted piece, one scanned return, one classification with a
    forwarding address."""

    @staticmethod
    def _castlereagh_scanned(api: ApiClient):
        pipeline = fx.printing_job(
            api,
            client_code="CLCS",
            client_overrides={"name": "Castlereagh Utilities"},
            template_code="T-CS",
            template_overrides={
                "mail_class_preference": "FIRST_CLASS",
                "sheets_per_document": 1,
            },
            press_line_code="PL-CS",
            press_line_overrides={
                "sheets_per_hour": 600,
                "daily_sheet_capacity": 9000,
                "changeover_buffer_minutes": 30,
            },
            file_name="cs-cycle-01.csv",
            specs=[CS_RECORD],
            window_start="2026-08-02T09:00:00Z",
            run_start_clock="2026-08-02T09:00:00Z",
        )
        fx.scan_piece_fully(api, pipeline.piece)
        pipeline.refresh_pieces()
        fx.set_clock(api, "2026-08-02T14:00:00Z")
        scanned = fx.intake_return(api, pipeline.piece["id"], "INSUFFICIENT_ADDRESS")
        return pipeline, scanned

    def test_classification_moves_the_return_and_persists_the_corrections(
        self, api: ApiClient
    ):
        """PRD §3.9: "On that branch the return moves `SCANNED` → `ADDRESS_UPDATED`, takes
        `classified_at` from the logical clock, persists both corrected fields, and has
        its `version` incremented by 1."

        The first link is the return: a complete forwarding address on a
        non-deceased endorsement moves it out of SCANNED and keeps both corrected
        fields on the row.

        Design: Difficulty/transitive_cascade/undeliverable_classification_cascades_three_links_to_the_client_counter
        """
        _pipeline, scanned = self._castlereagh_scanned(api)
        assert scanned["disposition"] == "SCANNED"
        assert scanned["classified_at"] is None

        classified = fx.classify_return(
            api, scanned["id"], "412 Sierra Vista Boulevard", "89502"
        )

        a.assert_undeliverable_return(classified)
        assert classified["disposition"] == "ADDRESS_UPDATED"
        a.assert_instant(
            classified["classified_at"], "2026-08-02T14:00:00Z", "return.classified_at"
        )
        assert classified["corrected_address_line1"] == "412 Sierra Vista Boulevard"
        assert classified["corrected_postal_code"] == "89502"

    def test_the_updated_return_rewrites_its_record_and_flags_its_piece(
        self, api: ApiClient
    ):
        """PRD §3.9: "Because the return reached `ADDRESS_UPDATED`, the statement record
        behind the returned piece has its `address_line1` and `postal_code` overwritten
        with the corrected values, its `hygiene_status` set to `CORRECTED` and its
        `address_update_pending` set to true, with the record's `version` incremented by
        1; the piece itself has `undeliverable_flag` set to true with its `version`
        incremented by 1."

        The second link follows from the return reaching its updated disposition:
        the record behind the piece takes the corrected address, drops from a
        perfectly deliverable standing to CORRECTED and enters the pending set,
        while the piece is flagged without leaving its terminal progress state.

        Design: Difficulty/transitive_cascade/undeliverable_classification_cascades_three_links_to_the_client_counter
        """
        pipeline, scanned = self._castlereagh_scanned(api)
        record_id = pipeline.file.records[0]["id"]
        before = fx.read_record(api, record_id)
        assert before["hygiene_status"] == "DELIVERABLE"
        assert before["hygiene_confidence"] == pytest.approx(1.00, abs=0.01)
        assert before["address_update_pending"] is False

        fx.classify_return(api, scanned["id"], "412 Sierra Vista Boulevard", "89502")

        after = fx.read_record(api, record_id)
        assert after["address_line1"] == "412 Sierra Vista Boulevard"
        assert after["postal_code"] == "89502"
        assert after["hygiene_status"] == "CORRECTED"
        assert after["address_update_pending"] is True

        piece = pipeline.refresh_pieces()[0]
        assert piece["undeliverable_flag"] is True
        assert piece["piece_status"] == "INDUCTED"

    def test_the_pending_flag_flip_writes_the_client_ledger(self, api: ApiClient):
        """PRD §3.9: "Because the record's `address_update_pending` has flipped to true,
        the owning client's `pending_address_feedback_count` is increased by 1 and the
        client's `version` incremented by 1."

        The third link follows from the record's pending flag flipping: the client
        row itself is written, its pending backlog rising by one while no feedback
        batch has yet been released.

        Design: Difficulty/transitive_cascade/undeliverable_classification_cascades_three_links_to_the_client_counter
        """
        pipeline, scanned = self._castlereagh_scanned(api)
        before = pipeline.refresh_client()
        assert before["pending_address_feedback_count"] == 0

        fx.classify_return(api, scanned["id"], "412 Sierra Vista Boulevard", "89502")

        after = pipeline.refresh_client()
        assert after["pending_address_feedback_count"] == 1
        assert after["address_feedback_batch_count"] == 0
        assert after["version"] > before["version"]
