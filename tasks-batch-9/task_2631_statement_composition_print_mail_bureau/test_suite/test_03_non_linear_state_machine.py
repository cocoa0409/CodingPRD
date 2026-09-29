"""Lifecycles that fork, re-enter, or move one dimension while pinning another.

Three different entities carry non-linear machines: a mail piece advances two
independent dimensions on one trigger, an undeliverable return forks on its
endorsement and rejoins at release, and a data file loops backwards through a
state it has already left.
"""

from test_helpers import assertions as a
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient


PP_RECORD = fx.record_spec(
    "ACC5001",
    1,
    45000,
    address_line1="62 Pinepoint Drive",
    city="Denver",
    region_code="CO",
    postal_code="80202",
    postal_code_plus4="4401",
)


class TestPieceDimensionsMoveIndependently:
    """One fully read piece, then a second read at a stage already accepted."""

    @staticmethod
    def _pinepoint_printing(api: ApiClient):
        pipeline = fx.printing_job(
            api,
            client_code="CLPP",
            client_overrides={"name": "Pinepoint Credit Union"},
            template_code="T-PP",
            template_overrides={
                "mail_class_preference": "FIRST_CLASS",
                "sheets_per_document": 1,
            },
            press_line_code="PL-PP",
            press_line_overrides={
                "sheets_per_hour": 600,
                "daily_sheet_capacity": 9000,
                "changeover_buffer_minutes": 30,
            },
            file_name="pp-cycle-01.csv",
            specs=[PP_RECORD],
            window_start="2026-08-02T09:00:00Z",
            run_start_clock="2026-08-02T09:00:00Z",
        )
        fx.scan_piece_fully(api, pipeline.piece)
        return pipeline

    def test_duplicate_induct_read_is_recorded_as_evidence_not_refused(
        self, api: ApiClient
    ):
        """PRD §3.7: "Otherwise, a read whose `stage` already carries an accepted event is
        stored with `rejection_reason` `DUPLICATE_STAGE`, and this is the one-to-one
        integrity breach the whole scanning regime exists to catch: the same barcode has
        been read twice at one station, so two physical pieces may be carrying one
        account's identity."

        A second read at a stage that already carries an accepted event comes
        back as a created scan event whose accepted flag is false, because the
        production log records a refusal rather than raising it.

        Design: Difficulty/non_linear_state_machine/mail_piece_progress_and_integrity_dimensions_advance_independently
        """
        pipeline = self._pinepoint_printing(api)
        piece = pipeline.piece

        event = fx.scan_stage(
            api, piece["id"], "INDUCT", piece["imb_barcode"], "SC-09"
        )

        a.assert_scan_event(event)
        assert event["accepted"] is False
        assert event["rejection_reason"] == "DUPLICATE_STAGE"
        assert event["stage"] == "INDUCT"
        assert event["device_code"] == "SC-09"

        log = fx.scan_events(api, piece["id"])
        assert len(log) == 4
        assert len([e for e in log if e["accepted"]]) == 3

    def test_integrity_dimension_moves_while_progress_stays_terminal(
        self, api: ApiClient
    ):
        """PRD §3.7: "On that refusal the piece's `integrity_status` is driven to
        `DUPLICATE_SCAN` — from `UNVERIFIED` or from `SCAN_MATCHED`, either way — while
        `piece_status` is deliberately left untouched, and the piece's `version` is
        incremented by 1."

        The refused read drives integrity_status to DUPLICATE_SCAN and leaves
        piece_status on the terminal INDUCTED, with the accepted tally and the
        last accepted stage both untouched.

        Design: Difficulty/non_linear_state_machine/mail_piece_progress_and_integrity_dimensions_advance_independently
        """
        pipeline = self._pinepoint_printing(api)
        before = fx.read_piece(api, pipeline.piece["id"])
        assert before["piece_status"] == "INDUCTED"
        assert before["integrity_status"] == "SCAN_MATCHED"

        fx.scan_stage(
            api, before["id"], "INDUCT", before["imb_barcode"], "SC-09"
        )

        after = fx.read_piece(api, before["id"])
        a.assert_mail_piece(after)
        assert after["piece_status"] == "INDUCTED"
        assert after["integrity_status"] == "DUPLICATE_SCAN"
        assert after["accepted_scan_count"] == 3
        assert after["last_scan_stage"] == "INDUCT"
        assert after["version"] == before["version"] + 1

    def test_job_rollup_waits_for_reconciliation(self, api: ApiClient):
        """PRD §3.7: "Three counters are then written on the job from the printable set:
        `matched_piece_count` is the number now holding `RECONCILED`,
        `missing_scan_count` the number now holding `SCAN_MISSING`, and
        `duplicate_scan_count` the number holding `DUPLICATE_SCAN`."

        The breach is visible on the piece but not yet on the job: the job's
        own integrity rollup is written by reconciliation and by nothing else.

        Design: Difficulty/non_linear_state_machine/mail_piece_progress_and_integrity_dimensions_advance_independently
        """
        pipeline = self._pinepoint_printing(api)
        piece = pipeline.piece

        fx.scan_stage(api, piece["id"], "INDUCT", piece["imb_barcode"], "SC-09")

        job = pipeline.refresh_job()
        assert job["status"] == "PRINTING"
        assert job["integrity_status"] == "PENDING"
        assert job["duplicate_scan_count"] == 0


UD_RECORDS = [
    fx.record_spec(
        "ACC6001",
        1,
        40000,
        address_line1="31 Underhill Court",
        postal_code="30301",
        postal_code_plus4="5501",
    ),
    fx.record_spec(
        "ACC6002",
        2,
        40000,
        address_line1="33 Underhill Court",
        postal_code="30301",
        postal_code_plus4="5502",
    ),
]


class TestReturnForkRejoinsAtFeedbackSent:
    """Two inducted pieces, two returns classified onto opposite branches, one
    release."""

    @staticmethod
    def _underhill_returns(api: ApiClient):
        pipeline = fx.printing_job(
            api,
            client_code="CLUD",
            client_overrides={"name": "Underhill Mutual Bank"},
            template_code="T-UD",
            template_overrides={
                "mail_class_preference": "FIRST_CLASS",
                "sheets_per_document": 1,
            },
            press_line_code="PL-UD",
            press_line_overrides={
                "sheets_per_hour": 600,
                "daily_sheet_capacity": 9000,
                "changeover_buffer_minutes": 30,
            },
            file_name="ud-cycle-01.csv",
            specs=UD_RECORDS,
            window_start="2026-08-02T09:00:00Z",
            run_start_clock="2026-08-02T09:00:00Z",
        )
        for piece in pipeline.pieces:
            fx.scan_piece_fully(api, piece)
        pipeline.refresh_pieces()

        moved = fx.intake_return(api, pipeline.pieces[0]["id"], "MOVED_NO_FORWARD")
        moved = fx.classify_return(api, moved["id"], "77 Relocation Way", "30318")
        deceased = fx.intake_return(api, pipeline.pieces[1]["id"], "DECEASED")
        deceased = fx.classify_return(api, deceased["id"], "99 Estate Lane", "30319")
        return pipeline, moved, deceased

    def test_corrections_are_applied_on_the_address_updated_branch(
        self, api: ApiClient
    ):
        """PRD §3.9: "Because the return reached `ADDRESS_UPDATED`, the statement record
        behind the returned piece has its `address_line1` and `postal_code` overwritten
        with the corrected values, its `hygiene_status` set to `CORRECTED` and its
        `address_update_pending` set to true, with the record's `version` incremented by
        1; the piece itself has `undeliverable_flag` set to true with its `version`
        incremented by 1."

        A forwarding address on a non-deceased endorsement forks the return to
        ADDRESS_UPDATED and overwrites the record's address, leaving its hygiene
        standing at CORRECTED.

        Design: Difficulty/non_linear_state_machine/undeliverable_return_fork_branches_rejoin_at_feedback_sent
        """
        pipeline, moved, _deceased = self._underhill_returns(api)

        a.assert_undeliverable_return(moved)
        assert moved["disposition"] == "ADDRESS_UPDATED"
        a.assert_instant(
            moved["classified_at"], "2026-08-02T09:00:00Z", "return.classified_at"
        )
        assert moved["corrected_address_line1"] == "77 Relocation Way"
        assert moved["corrected_postal_code"] == "30318"

        record = fx.read_record(api, pipeline.file.records[0]["id"])
        assert record["address_line1"] == "77 Relocation Way"
        assert record["postal_code"] == "30318"
        assert record["hygiene_status"] == "CORRECTED"
        assert record["address_update_pending"] is True

    def test_deceased_endorsement_forces_the_unresolved_branch(self, api: ApiClient):
        """PRD §3.9: "On that branch the return moves `SCANNED` → `UNRESOLVED`, takes
        `classified_at` from the logical clock, and has its `version` incremented by 1,
        while any corrected fields that were supplied are discarded and persisted as
        null."

        Both corrected fields were supplied, but a deceased endorsement forks to
        UNRESOLVED, discards the corrections and leaves the record on its original
        address with a STALE hygiene standing.

        Design: Difficulty/non_linear_state_machine/undeliverable_return_fork_branches_rejoin_at_feedback_sent
        """
        pipeline, _moved, deceased = self._underhill_returns(api)

        a.assert_undeliverable_return(deceased)
        assert deceased["disposition"] == "UNRESOLVED"
        assert deceased["corrected_address_line1"] is None
        assert deceased["corrected_postal_code"] is None

        record = fx.read_record(api, pipeline.file.records[1]["id"])
        assert record["address_line1"] == "33 Underhill Court"
        assert record["postal_code"] == "30301"
        assert record["hygiene_status"] == "STALE"
        assert record["address_update_pending"] is True

    def test_both_branches_flag_their_piece_and_bank_one_pending_item_each(
        self, api: ApiClient
    ):
        """PRD §3.9: "Because the record's `address_update_pending` has flipped to true,
        the owning client's `pending_address_feedback_count` is increased by 1 and the
        client's `version` incremented by 1."

        Whichever branch a return took, its piece carries the undeliverable flag
        and its record contributed one item to the client's pending feedback
        backlog.

        Design: Difficulty/non_linear_state_machine/undeliverable_return_fork_branches_rejoin_at_feedback_sent
        """
        pipeline, _moved, _deceased = self._underhill_returns(api)

        for piece in pipeline.refresh_pieces():
            assert piece["undeliverable_flag"] is True

        client = pipeline.refresh_client()
        assert client["pending_address_feedback_count"] == 2
        assert client["address_feedback_batch_count"] == 0

    def test_one_release_rejoins_both_forks_under_a_shared_batch_sequence(
        self, api: ApiClient
    ):
        """PRD §3.9: "Every return of the client in either of those two dispositions moves
        to `FEEDBACK_SENT`, taking `feedback_sent_at` from the logical clock and
        `feedback_batch_seq` equal to the client's `address_feedback_batch_count` plus
        one — the client-scoped sequence number of this release — with each return's
        `version` incremented by 1."

        A single release closes out both dispositions at FEEDBACK_SENT, stamps
        them with the same client-scoped batch sequence, clears the pending
        backlog and takes each record out of the pending set.

        Design: Difficulty/non_linear_state_machine/undeliverable_return_fork_branches_rejoin_at_feedback_sent
        """
        pipeline, moved, deceased = self._underhill_returns(api)

        fx.release_feedback(api, pipeline.client_id, "August return file")

        for return_id in (moved["id"], deceased["id"]):
            closed = fx.read_return(api, return_id)
            assert closed["disposition"] == "FEEDBACK_SENT"
            assert closed["feedback_batch_seq"] == 1
            a.assert_instant(
                closed["feedback_sent_at"],
                "2026-08-02T09:00:00Z",
                "return.feedback_sent_at",
            )

        client = pipeline.refresh_client()
        assert client["address_feedback_batch_count"] == 1
        assert client["pending_address_feedback_count"] == 0

        for record in pipeline.file.records:
            assert fx.read_record(api, record["id"])["address_update_pending"] is False


DV_RECORDS = [
    fx.record_spec(
        f"ACC700{i}",
        i,
        amount,
        address_line1=f"{i} Deervale Loop",
        city="Boise",
        region_code="ID",
        postal_code="83702",
        postal_code_plus4=f"660{i}",
    )
    for i, amount in ((1, 100000), (2, 100000), (3, 100500))
]


class TestDataFileVarianceHoldLoopsBack:
    """A 500-cent overstatement, an amendment, and a second pass at both gates."""

    @staticmethod
    def _deervale_held(api: ApiClient):
        fx.set_clock(api)
        client = fx.register_client(
            api,
            client_code="CLDV",
            name="Deervale Telecom",
            dr_readiness_required=False,
        )
        assert client["control_total_tolerance_bp"] == 5
        bundle = fx.lodged_file(
            api,
            client["id"],
            DV_RECORDS,
            file_name="dv-cycle-01.csv",
            declared_record_count=3,
            declared_control_total_cents=300000,
        )
        fx.validate_file_format(api, bundle.id)
        held = fx.run_control_check(api, bundle.id)
        return client, bundle, held

    def test_control_check_forks_to_held_variance_on_the_rounded_drift(
        self, api: ApiClient
    ):
        """PRD §3.3: "In every other case the file goes `FORMAT_VALIDATED` →
        `HELD_VARIANCE` instead: the same five actual and variance figures are written,
        but `accepted_at` is left null."

        The reconciliation writes the actual figures and both variances, expresses
        the 500-cent drift as 17 basis points against the declared total, and holds
        the file because that exceeds the client's tolerance of 5.

        Design: Difficulty/non_linear_state_machine/data_file_variance_hold_loops_back_to_received
        """
        _client, _bundle, held = self._deervale_held(api)

        a.assert_data_file(held)
        assert held["status"] == "HELD_VARIANCE"
        assert held["actual_record_count"] == 3
        assert held["record_count_variance"] == 0
        assert held["actual_control_total_cents"] == 300500
        assert held["control_total_variance_cents"] == 500
        assert held["control_total_variance_bp"] == 17
        assert a.expected_variance_bp(300000, 300500) == 17
        assert held["accepted_at"] is None

    def test_amendment_loops_the_file_back_to_received(self, api: ApiClient):
        """PRD §3.3: "A successful amendment overwrites the supplied declared figures,
        increments `amendment_count` by 1, resets `format_error_count` to 0 and resets
        every attached record's `format_valid` to false so that the file must be
        re-validated from scratch, recomputes `record_count_variance`,
        `control_total_variance_cents` and `control_total_variance_bp` against the newly
        amended declarations, moves the file `HELD_VARIANCE` → `RECEIVED`, and
        increments the file's `version` by 1."

        Amending the declared total moves the file backwards out of the hold into
        RECEIVED, counts the amendment, and clears every format mark so the file
        must be validated from scratch.

        Design: Difficulty/non_linear_state_machine/data_file_variance_hold_loops_back_to_received
        """
        _client, bundle, held = self._deervale_held(api)

        amended = fx.amend_declared_totals(
            api, bundle.id, declared_control_total_cents=300500
        )

        assert amended["status"] == "RECEIVED"
        assert amended["amendment_count"] == 1
        assert amended["declared_control_total_cents"] == 300500
        assert amended["declared_record_count"] == 3
        assert amended["format_error_count"] == 0
        assert amended["version"] == held["version"] + 1
        for record in fx.file_records(api, bundle.id):
            assert record["format_valid"] is False

    def test_the_second_pass_re_traverses_both_gates_to_acceptance(
        self, api: ApiClient
    ):
        """PRD §3.3: "On that branch the file's `accepted_at` is stamped from the logical
        clock, and that instant becomes the service-level clock origin for every job
        composed from the file."

        The file visits RECEIVED and FORMAT_VALIDATED a second time before the
        same control-check trigger takes the accepting fork, stamping the acceptance
        instant from the clock with both variances now at zero.

        Design: Difficulty/non_linear_state_machine/data_file_variance_hold_loops_back_to_received
        """
        _client, bundle, held = self._deervale_held(api)
        observed = [bundle.data_file["status"], "FORMAT_VALIDATED", held["status"]]

        amended = fx.amend_declared_totals(
            api, bundle.id, declared_control_total_cents=300500
        )
        observed.append(amended["status"])
        revalidated = fx.validate_file_format(api, bundle.id)
        observed.append(revalidated["status"])
        assert revalidated["status"] == "FORMAT_VALIDATED"
        assert revalidated["format_error_count"] == 0

        fx.set_clock(api, "2026-08-01T06:00:00Z")
        accepted = fx.run_control_check(api, bundle.id)
        observed.append(accepted["status"])

        assert accepted["status"] == "ACCEPTED"
        assert accepted["control_total_variance_cents"] == 0
        assert accepted["control_total_variance_bp"] == 0
        assert accepted["record_count_variance"] == 0
        a.assert_instant(
            accepted["accepted_at"], "2026-08-01T06:00:00Z", "file.accepted_at"
        )
        assert observed == [
            "RECEIVED",
            "FORMAT_VALIDATED",
            "HELD_VARIANCE",
            "RECEIVED",
            "FORMAT_VALIDATED",
            "ACCEPTED",
        ]
        assert len(set(observed)) == 4
