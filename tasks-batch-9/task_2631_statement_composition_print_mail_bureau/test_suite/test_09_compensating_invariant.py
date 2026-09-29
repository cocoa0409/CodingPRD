"""Ledgers that must balance again after a compensating operation.

Money, press sheets and physical insert copies each have a three-way identity
that has to hold after every event, including the ones that undo earlier work.
"""

from test_helpers import assertions as a
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.test_users import POSTAGE_USER_ID


class TestEscrowConservedAcrossSealAndUnseal:
    """One batch worth 112 cents, sealed, unsealed and sealed again."""

    @staticmethod
    def _escrow_reconciled(api: ApiClient):
        pipeline = fx.verified_job(
            api,
            fund_cents=100000,
            client_code="CLEC",
            client_overrides={"name": "Escrow Conservation Trust"},
            template_code="T-EC",
            template_overrides={
                "sheets_per_document": 1,
                "mail_class_preference": "FIRST_CLASS",
            },
            press_line_code="PL-EC",
            press_line_overrides={
                "sheets_per_hour": 600,
                "daily_sheet_capacity": 9000,
                "changeover_buffer_minutes": 30,
            },
            file_name="ec-cycle-01.csv",
            file_overrides={
                "declared_record_count": 2,
                "declared_control_total_cents": 34000,
            },
            specs=[
                fx.record_spec(
                    "ACC2201",
                    1,
                    17000,
                    address_line1="200 Escrow Avenue",
                    postal_code="30301",
                    postal_code_plus4="3301",
                ),
                fx.record_spec(
                    "ACC2202",
                    2,
                    17000,
                    address_line1="202 Escrow Avenue",
                    postal_code="30301",
                    postal_code_plus4="3302",
                ),
            ],
        )
        return pipeline, pipeline.client["version"]

    def test_sealing_moves_money_from_available_into_committed(self, api: ApiClient):
        """PRD §3.8: "The client cascade adds `estimated_postage_cents` to
        `postage_committed_cents`, subtracts the same amount from
        `postage_escrow_available_cents`, and increments the client's `version` by 1."

        The deposit is unchanged by the seal and the two legs of the escrow still
        add up to it, so the money has only moved between them.

        Design: Difficulty/compensating_invariant/postage_escrow_conserved_across_seal_and_unseal
        """
        pipeline, client_version = self._escrow_reconciled(api)

        at_rest = pipeline.client
        assert at_rest["postage_deposited_cents"] == 100000
        assert at_rest["postage_committed_cents"] == 0
        assert at_rest["postage_escrow_available_cents"] == 100000
        a.assert_escrow_ledger(at_rest)

        sealed = fx.seal_batch(api, pipeline.batch["id"], client_version)
        assert sealed["estimated_postage_cents"] == 112

        client = pipeline.refresh_client()
        assert client["postage_deposited_cents"] == 100000
        assert client["postage_committed_cents"] == 112
        assert client["postage_escrow_available_cents"] == 99888
        a.assert_escrow_ledger(client)

    def test_unsealing_erases_the_derived_figures_and_restores_the_ledger(
        self, api: ApiClient
    ):
        """PRD §3.8: "The batch moves `SEALED` → `OPEN` with `estimated_postage_cents` and
        `sealed_by_user_id` both cleared to null and its `version` incremented by 1,
        while the client's `postage_committed_cents` is reduced by the released estimate
        and `postage_escrow_available_cents` increased by the same amount, restoring
        both to their exact pre-seal values, with the client's `version` incremented by
        1."

        Unsealing is the exact inverse: the estimate and the sealing controller are
        cleared to null rather than merely ignored, and both escrow legs return to
        their pre-seal values to the cent.

        Design: Difficulty/compensating_invariant/postage_escrow_conserved_across_seal_and_unseal
        """
        pipeline, client_version = self._escrow_reconciled(api)
        fx.seal_batch(api, pipeline.batch["id"], client_version)

        unsealed = fx.unseal_batch(api, pipeline.batch["id"])
        assert unsealed["status"] == "OPEN"
        assert unsealed["estimated_postage_cents"] is None
        assert unsealed["sealed_by_user_id"] is None

        client = pipeline.refresh_client()
        assert client["postage_committed_cents"] == 0
        assert client["postage_escrow_available_cents"] == 100000
        assert client["postage_deposited_cents"] == 100000
        a.assert_escrow_ledger(client)

    def test_a_full_cycle_leaves_no_drift(self, api: ApiClient):
        """PRD §2.9: "Sealing a batch moves its estimated postage from available to
        committed; unsealing that same batch moves exactly the same amount back, leaving
        both figures at their pre-seal values with no drift."

        The re-seal recomputes the estimate from the pieces rather than remembering
        it, lands on exactly the balance the first seal produced, and the client row
        records precisely the three writes the cycle made.

        Design: Difficulty/compensating_invariant/postage_escrow_conserved_across_seal_and_unseal
        """
        pipeline, client_version = self._escrow_reconciled(api)

        fx.seal_batch(api, pipeline.batch["id"], client_version)
        after_first = pipeline.refresh_client()["postage_escrow_available_cents"]
        fx.unseal_batch(api, pipeline.batch["id"])
        mid_version = pipeline.refresh_client()["version"]

        resealed = fx.seal_batch(api, pipeline.batch["id"], mid_version)
        assert resealed["estimated_postage_cents"] == 112
        assert resealed["status"] == "SEALED"
        assert resealed["sealed_by_user_id"] == POSTAGE_USER_ID
        assert resealed["manifested_postage_cents"] is None
        assert resealed["postage_variance_cents"] is None

        client = pipeline.refresh_client()
        assert client["postage_escrow_available_cents"] == after_first == 99888
        assert client["postage_committed_cents"] == 112
        assert client["version"] == client_version + 3
        a.assert_escrow_ledger(client)


class TestPressSheetLedgerConservedAcrossBothExits:
    """Two two-sheet reservations on a 2,000-sheet line, released once by an abort
    and once by a completion."""

    @staticmethod
    def _conserval_two_jobs(api: ApiClient):
        fx.set_clock(api)
        client = fx.register_client(
            api,
            client_code="CLCV",
            name="Conserval Publishing",
            dr_readiness_required=False,
        )
        template = fx.create_active_template(
            api,
            client["id"],
            template_code="T-CV",
            sheets_per_document=1,
            mail_class_preference="FIRST_CLASS",
        )
        line = fx.register_press_line(
            api,
            line_code="PL-CV",
            capabilities=["DUPLEX", "COLOR", "INSERT"],
            sheets_per_hour=600,
            daily_sheet_capacity=2000,
            changeover_buffer_minutes=30,
        )

        def _job(file_name, refs, postal_code):
            bundle = fx.accepted_file(
                api,
                client["id"],
                [
                    fx.record_spec(refs[0], 1, 10000, postal_code=postal_code),
                    fx.record_spec(refs[1], 2, 10000, postal_code=postal_code),
                ],
                file_name=file_name,
                declared_record_count=2,
                declared_control_total_cents=20000,
            )
            job = fx.compose_job(api, bundle.id, template["id"])
            return fx.presort_job(api, job["id"])

        one = _job("cv-one.csv", ("ACC2301", "ACC2302"), "30301")
        two = _job("cv-two.csv", ("ACC2303", "ACC2304"), "30302")
        return line, one, two

    @staticmethod
    def _live_sheets(api: ApiClient, line_id: str) -> int:
        """The sheets the line's planned-or-running runs actually hold."""
        return sum(
            run["planned_sheet_count"]
            for run in fx.list_runs(api, press_line_id=line_id)
            if run["status"] in ("PLANNED", "RUNNING")
        )

    def test_two_bookings_hold_the_sum_of_their_planned_sheets(self, api: ApiClient):
        """PRD §3.6: "Scheduling then cascades onto the line: `committed_sheet_count` is
        increased by `planned_sheet_count`, `utilization_bp` is recomputed as
        `committed_sheet_count` multiplied by 10,000 and divided by
        `daily_sheet_capacity`, and the line's `version` is incremented by 1."

        The line starts empty and after both bookings carries exactly the two runs'
        planned sheets, with utilisation recomputed against its 2,000-sheet capacity.

        Design: Difficulty/compensating_invariant/press_sheet_ledger_conserved_across_schedule_abort_and_complete
        """
        line, one, two = self._conserval_two_jobs(api)

        assert line["committed_sheet_count"] == 0
        assert line["utilization_bp"] == 0
        assert fx.list_runs(api, press_line_id=line["id"]) == []

        run_one = fx.schedule_job(api, one["id"], "2026-08-04T09:00:00Z", line["id"])
        run_two = fx.schedule_job(api, two["id"], "2026-08-04T11:00:00Z", line["id"])
        assert run_one["planned_sheet_count"] == 2
        assert run_two["planned_sheet_count"] == 2

        reread = fx.read_press_line(api, line["id"])
        assert reread["committed_sheet_count"] == 4
        assert reread["utilization_bp"] == 20
        assert reread["committed_sheet_count"] == self._live_sheets(api, line["id"])
        a.assert_press_ledger(reread)

    def test_starting_a_run_releases_nothing(self, api: ApiClient):
        """PRD §2.9: "Scheduling a job adds its planned sheets to the line's committed
        total; a run leaving the planned-or-running set, whether by completing or by
        being aborted, subtracts exactly the same figure, restoring the pre-schedule
        value."

        A run that moves from planned to running stays inside the occupying set, so
        the ledger does not budge.

        Design: Difficulty/compensating_invariant/press_sheet_ledger_conserved_across_schedule_abort_and_complete
        """
        line, one, two = self._conserval_two_jobs(api)
        run_one = fx.schedule_job(api, one["id"], "2026-08-04T09:00:00Z", line["id"])
        fx.schedule_job(api, two["id"], "2026-08-04T11:00:00Z", line["id"])

        fx.set_clock(api, "2026-08-04T09:00:00Z")
        started = fx.start_run(api, run_one["id"])
        assert started["status"] == "RUNNING"

        reread = fx.read_press_line(api, line["id"])
        assert reread["committed_sheet_count"] == 4
        assert reread["committed_sheet_count"] == self._live_sheets(api, line["id"])

    def test_aborting_releases_only_its_own_reservation_and_rewinds_only_its_job(
        self, api: ApiClient
    ):
        """PRD §3.6: "Second, because the run has left the planned-or-running set, the
        line's `committed_sheet_count` is reduced by `planned_sheet_count` — restoring
        exactly the value it held before this job was scheduled, with no drift —
        `utilization_bp` is recomputed and the line's `version` is incremented by 1."

        The abort hands back exactly the sheets its own run reserved, leaving the
        surviving booking's two sheets and a utilisation of ten, and it rewinds its
        own job without disturbing the other.

        Design: Difficulty/compensating_invariant/press_sheet_ledger_conserved_across_schedule_abort_and_complete
        """
        line, one, two = self._conserval_two_jobs(api)
        run_one = fx.schedule_job(api, one["id"], "2026-08-04T09:00:00Z", line["id"])
        fx.schedule_job(api, two["id"], "2026-08-04T11:00:00Z", line["id"])
        fx.set_clock(api, "2026-08-04T09:00:00Z")
        fx.start_run(api, run_one["id"])

        aborted = fx.abort_run(api, run_one["id"], "EQUIPMENT_FAULT")
        assert aborted["status"] == "ABORTED"
        assert aborted["abort_reason"] == "EQUIPMENT_FAULT"
        assert aborted["planned_sheet_count"] == 2

        reread = fx.read_press_line(api, line["id"])
        assert reread["committed_sheet_count"] == 2
        assert reread["utilization_bp"] == 10
        assert reread["committed_sheet_count"] == self._live_sheets(api, line["id"])
        assert fx.read_job(api, one["id"])["status"] == "PRESORTED"
        assert fx.read_job(api, two["id"])["status"] == "SCHEDULED"

    def test_the_other_exit_from_running_empties_the_ledger_too(self, api: ApiClient):
        """PRD §3.6: "Because the run has left the planned-or-running set, the line's
        `committed_sheet_count` is reduced by `planned_sheet_count`, `utilization_bp` is
        recomputed and the line's `version` is incremented by 1."

        Completion releases capacity just as abortion does, so the line returns to
        zero sheets and zero utilisation from a second terminal state, with the
        identity holding at every observation point.

        Design: Difficulty/compensating_invariant/press_sheet_ledger_conserved_across_schedule_abort_and_complete
        """
        line, one, two = self._conserval_two_jobs(api)
        run_one = fx.schedule_job(api, one["id"], "2026-08-04T09:00:00Z", line["id"])
        run_two = fx.schedule_job(api, two["id"], "2026-08-04T11:00:00Z", line["id"])
        observations = [self._live_sheets(api, line["id"])]

        fx.set_clock(api, "2026-08-04T09:00:00Z")
        fx.start_run(api, run_one["id"])
        observations.append(self._live_sheets(api, line["id"]))
        fx.abort_run(api, run_one["id"], "EQUIPMENT_FAULT")
        observations.append(self._live_sheets(api, line["id"]))

        fx.set_clock(api, "2026-08-04T11:00:00Z")
        fx.start_run(api, run_two["id"])
        completed = fx.complete_run(api, run_two["id"])
        assert completed["status"] == "COMPLETED"
        assert completed["abort_reason"] == "NONE"
        assert completed["planned_sheet_count"] == 2
        observations.append(self._live_sheets(api, line["id"]))

        assert observations == [4, 4, 2, 0]
        reread = fx.read_press_line(api, line["id"])
        assert reread["committed_sheet_count"] == 0
        assert reread["utilization_bp"] == 0
        a.assert_press_ledger(reread)


class TestInsertStockConservedAcrossReworkAndManifest:
    """Ten warehoused copies followed through reservation, a reprint's net-zero pair
    and consumption."""

    @staticmethod
    def _inkwell_held(api: ApiClient):
        fx.set_clock(api)
        stock = fx.register_insert_stock(
            api,
            insert_code="INS-REG-1",
            description="Federal disclosure booklet",
            jurisdiction_code="US-FED",
            effective_from="2026-07-01T00:00:00Z",
            sheets_per_insert=2,
            received_count=10,
        )
        pipeline = fx.integrity_held_job(
            api,
            unscanned_piece_indexes=(1,),
            clock=None,
            fund_cents=100000,
            client_code="CLIK",
            client_overrides={"name": "Inkwell Regional Bank"},
            template_code="T-IK",
            template_overrides={
                "sheets_per_document": 1,
                "mail_class_preference": "FIRST_CLASS",
                "required_insert_codes": ["INS-REG-1"],
            },
            press_line_code="PL-IK",
            press_line_overrides={
                "sheets_per_hour": 600,
                "daily_sheet_capacity": 9000,
                "changeover_buffer_minutes": 30,
            },
            with_facility=True,
            facility_code="EF-IK",
            facility_overrides={
                "tray_capacity_per_window": 4,
                "discount_bp_first_class": 850,
                "discount_bp_marketing": 1200,
            },
            file_name="ik-cycle-01.csv",
            file_overrides={
                "declared_record_count": 2,
                "declared_control_total_cents": 38000,
            },
            specs=[
                fx.record_spec(
                    "ACC2401",
                    1,
                    19000,
                    address_line1="300 Inkwell Street",
                    postal_code="30301",
                    postal_code_plus4="4401",
                ),
                fx.record_spec(
                    "ACC2402",
                    2,
                    19000,
                    address_line1="302 Inkwell Street",
                    postal_code="30301",
                    postal_code_plus4="4402",
                ),
            ],
        )
        stock = fx.read_insert_stock(api, stock["id"])
        missing = next(
            piece
            for piece in pipeline.pieces
            if piece["integrity_status"] == "SCAN_MISSING"
        )
        return pipeline, stock, missing

    def test_composition_reserves_one_copy_for_every_printable_piece(
        self, api: ApiClient
    ):
        """PRD §3.4: "For every insert code that appears in any composed piece's
        `insert_codes`, the number of copies the job needs is the count of that job's
        non-suppressed pieces whose `insert_codes` contain the code — exactly one copy
        per piece, and suppressed pieces need nothing because nothing physical is
        produced for them."

        The warehouse total splits into eight on hand and two reserved without
        changing, and each piece carries the insert's two sheets on top of its own.

        Design: Difficulty/compensating_invariant/insert_stock_conserved_across_composition_reprint_and_manifest
        """
        pipeline, stock, _missing = self._inkwell_held(api)

        assert stock["received_count"] == 10
        assert stock["on_hand_count"] == 8
        assert stock["reserved_count"] == 2
        assert stock["consumed_count"] == 0
        a.assert_insert_stock_ledger(stock)

        assert pipeline.job["insert_sheet_total"] == 4
        for piece in pipeline.pieces:
            assert piece["sheet_count"] == 3
            assert piece["insert_sheet_count"] == 2
            assert piece["insert_codes"] == ["INS-REG-1"]

    def test_the_reprint_returns_and_re_reserves_the_same_copies(self, api: ApiClient):
        """PRD §3.7: "The voided piece's reserved copies return to `on_hand_count` and the
        replacement immediately reserves the same number again, so neither
        `on_hand_count` nor `reserved_count` changes on net, the three-way stock
        identity still balances, and each touched stock row has its `version`
        incremented by 1."

        The rework voids a piece and mints a replacement, and the copies the voided
        piece held come back on hand only to be reserved again, so the ledger reads
        exactly as it did before.

        Design: Difficulty/compensating_invariant/insert_stock_conserved_across_composition_reprint_and_manifest
        """
        pipeline, stock, missing = self._inkwell_held(api)

        assert pipeline.job["status"] == "INTEGRITY_HELD"
        assert pipeline.job["integrity_status"] == "BREACHED"

        replacement = fx.reprint_piece(
            api, missing["id"], pipeline.refresh_job()["version"]
        )
        assert replacement["reprint_of_piece_id"] == missing["id"]
        assert replacement["billable"] is False
        assert replacement["imb_barcode"] == missing["imb_barcode"] + "-R1"
        assert fx.read_piece(api, missing["id"])["piece_status"] == "VOID"

        job = pipeline.refresh_job()
        assert job["void_piece_count"] == 1
        assert job["reprint_piece_count"] == 1

        after = fx.read_insert_stock(api, stock["id"])
        assert after["on_hand_count"] == 8
        assert after["reserved_count"] == 2
        assert after["consumed_count"] == 0
        a.assert_insert_stock_ledger(after)

    def test_the_rework_leaves_the_billing_and_postage_bases_alone(
        self, api: ApiClient
    ):
        """PRD §3.8: "Only billable pieces feed the sheet bases, so a reprint replacement
        contributes nothing while the voided original it replaced remains billable — a
        reprint therefore never changes the invoice."

        Once the replacement is read at all three stages the job verifies, and the
        two non-void pieces are billed and franked exactly as the original pair would
        have been.

        Design: Difficulty/compensating_invariant/insert_stock_conserved_across_composition_reprint_and_manifest
        """
        pipeline, _stock, missing = self._inkwell_held(api)
        replacement = fx.reprint_piece(
            api, missing["id"], pipeline.refresh_job()["version"]
        )
        fx.scan_piece_fully(api, replacement)

        job = fx.reconcile(api, pipeline.job_id)
        assert job["status"] == "VERIFIED"
        assert job["integrity_status"] == "MATCHED"

        sealed = fx.seal_batch(
            api, pipeline.batch["id"], pipeline.refresh_client()["version"]
        )
        assert sealed["estimated_postage_cents"] == 112

        manifested = fx.manifest_batch(
            api, pipeline.batch["id"], pipeline.facility["id"]
        )
        assert manifested["manifested_postage_cents"] == (
            2 * a.expected_net_postage_cents(56, 850)
        ) == 102
        assert manifested["postage_variance_cents"] == -10

    def test_the_manifest_bubble_up_turns_reservation_into_consumption(
        self, api: ApiClient
    ):
        """PRD §3.8: "That bubble-up in turn settles the insert stock: for every insert
        code the job had reserved, the reserved copies move out of `reserved_count` and
        into `consumed_count` by the same amount, `on_hand_count` is left untouched, and
        each affected stock row has its `version` incremented by 1."

        When the job's last batch is manifested the reserved copies move into the
        consumed column, the on-hand column is left where the reservation put it, and
        the warehouse total never moved at all.

        Design: Difficulty/compensating_invariant/insert_stock_conserved_across_composition_reprint_and_manifest
        """
        pipeline, stock, missing = self._inkwell_held(api)
        replacement = fx.reprint_piece(
            api, missing["id"], pipeline.refresh_job()["version"]
        )
        fx.scan_piece_fully(api, replacement)
        fx.reconcile(api, pipeline.job_id)
        fx.seal_batch(api, pipeline.batch["id"], pipeline.refresh_client()["version"])
        fx.manifest_batch(api, pipeline.batch["id"], pipeline.facility["id"])

        assert pipeline.refresh_job()["status"] == "MANIFESTED"
        settled = fx.read_insert_stock(api, stock["id"])
        assert settled["on_hand_count"] == 8
        assert settled["reserved_count"] == 0
        assert settled["consumed_count"] == 2
        assert settled["received_count"] == 10
        a.assert_insert_stock_ledger(settled)
