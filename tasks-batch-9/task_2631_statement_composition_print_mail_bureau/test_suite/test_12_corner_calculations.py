"""Computed figures probed one clause at a time.

Hygiene weights, format predicates, the presort waterfall, run-window sizing,
disaster-recovery readiness and cumulative variable content are each driven with
inputs chosen so that a single clause of the formula decides the answer.
"""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    CLIENT_LIAISON,
    COMPOSITION_OPERATOR,
    INTEGRITY_AUDITOR,
)


class TestAddressHygieneBands:
    """Three addresses of decreasing completeness, scored in one composition."""

    def test_three_addresses_score_into_the_three_hygiene_bands(
        self, api: ApiClient
    ):
        """PRD §3.4: "A `hygiene_confidence` of 0.90 or higher sets `hygiene_status` to
        `DELIVERABLE`; otherwise a `hygiene_confidence` of 0.65 or higher sets it to
        `CORRECTED`; otherwise it is set to `UNDELIVERABLE_AS_ADDRESSED`."

        A complete address collects all five awards for 1.00, dropping only the
        plus-four award leaves 0.72, and an address_line1 of three characters with no
        plus four leaves 0.47, which lands the three records in DELIVERABLE,
        CORRECTED and UNDELIVERABLE_AS_ADDRESSED respectively.

        Design: Corner/calculations/address_hygiene_scores_three_records_into_three_bands
        """
        fx.set_clock(api)
        client = fx.register_client(
            api,
            client_code="CLC1",
            name="Hygiene Bands Bank",
            dr_readiness_required=False,
        )
        template = fx.create_active_template(
            api,
            client["id"],
            template_code="T-C1",
            sheets_per_document=1,
            color_pages_per_document=0,
            mail_class_preference="FIRST_CLASS",
        )
        bundle = fx.accepted_file(
            api,
            client["id"],
            [
                fx.record_spec(
                    "ABC1101",
                    1,
                    5000,
                    address_line1="1600 Complete Avenue",
                    postal_code="30301",
                    postal_code_plus4="1601",
                ),
                fx.record_spec(
                    "ABC1102",
                    2,
                    5000,
                    address_line1="1602 Complete Avenue",
                    postal_code="30301",
                    postal_code_plus4=None,
                ),
                fx.record_spec(
                    "ABC1103",
                    3,
                    5000,
                    address_line1="N/A",
                    postal_code="30301",
                    postal_code_plus4=None,
                ),
            ],
            file_name="c1.csv",
            declared_record_count=3,
            declared_control_total_cents=15000,
        )

        job = fx.compose_job(api, bundle.id, template["id"])

        assert job["expected_piece_count"] == 3
        full, no_plus4, uaa = fx.file_records(api, bundle.id)

        assert full["hygiene_confidence"] == pytest.approx(1.00, abs=0.01)
        assert 2500 + 1000 + 1500 + 2200 + 2800 == 10000
        assert full["hygiene_status"] == "DELIVERABLE"

        assert no_plus4["hygiene_confidence"] == pytest.approx(0.72, abs=0.01)
        assert (10000 - 2800) / 10000 == pytest.approx(0.72, abs=0.01)
        assert no_plus4["hygiene_status"] == "CORRECTED"

        assert uaa["hygiene_confidence"] == pytest.approx(0.47, abs=0.01)
        assert (1000 + 1500 + 2200) / 10000 == pytest.approx(0.47, abs=0.01)
        assert uaa["hygiene_status"] == "UNDELIVERABLE_AS_ADDRESSED"

        for record in (full, no_plus4, uaa):
            assert record["delivery_channel"] == "PRINT"
            assert record["computed_sheet_count"] == 1

        _rows, meta = validate_paginated(
            api.list_file_records(
                bundle.id, CLIENT_LIAISON, {"hygiene_status": "DELIVERABLE"}
            )
        )
        assert meta["total_count"] == 1


class TestHygieneWeightIndependence:
    """One address that fails exactly two of the five per-field predicates."""

    def test_only_the_failing_predicates_withhold_their_weights(self, api: ApiClient):
        """PRD §3.4: "A record earns 2,500 basis points when its `address_line1` is at
        least 5 characters long; a further 1,000 basis points when its `city` is
        non-empty; a further 1,500 basis points when its `region_code` is exactly 2
        characters long — only a two-character region code earns this award; a further
        2,200 basis points when its `postal_code` consists of exactly five digits 0
        through 9 and nothing else; and a further 2,800 basis points, the largest single
        award available, when its `postal_code_plus4` consists of exactly four digits 0
        through 9 and nothing else."

        A three-character region code withholds its 1,500 basis points and a
        two-digit plus four withholds its 2,800, while the three intact fields keep
        their awards, so the record scores 0.57 rather than any all-or-nothing figure.

        Design: Corner/calculations/hygiene_withholds_only_the_weights_whose_predicate_fails
        """
        fx.set_clock(api)
        client = fx.register_client(
            api,
            client_code="CLC2",
            name="Weight Withholding Bancorp",
            dr_readiness_required=False,
        )
        template = fx.create_active_template(
            api,
            client["id"],
            template_code="T-C2",
            sheets_per_document=1,
            color_pages_per_document=0,
            mail_class_preference="FIRST_CLASS",
        )
        bundle = fx.lodged_file(
            api,
            client["id"],
            [
                fx.record_spec(
                    "ABC1201",
                    1,
                    6000,
                    address_line1="1700 Partial Predicate Place",
                    region_code="GAX",
                    postal_code="30301",
                    postal_code_plus4="12",
                )
            ],
            file_name="c2.csv",
            declared_record_count=1,
            declared_control_total_cents=6000,
        )

        validated = fx.validate_file_format(api, bundle.id)
        assert validated["format_error_count"] == 0
        assert validated["status"] == "FORMAT_VALIDATED"
        fx.run_control_check(api, bundle.id)

        job = fx.compose_job(api, bundle.id, template["id"])

        record = fx.read_record(api, bundle.records[0]["id"])
        assert record["hygiene_confidence"] == pytest.approx(0.57, abs=0.01)
        assert a.round_half_up((2500 + 1000 + 2200) / 10000, 2) == pytest.approx(
            0.57, abs=0.01
        )
        assert record["hygiene_status"] == "UNDELIVERABLE_AS_ADDRESSED"
        assert job["expected_piece_count"] == 1
        assert job["accountable_piece_count"] == 1


class TestFormatValidationScoresEveryRecord:
    """Three records, two of which fail different clauses of one predicate."""

    def test_both_failing_records_are_counted_and_the_file_stays_received(
        self, api: ApiClient
    ):
        """PRD §3.3: "If that count is greater than zero the file does **not** advance: it
        stays in `RECEIVED` and the request is refused with `ERR_FILE_FORMAT_ERRORS`
        (HTTP 422), while the per-record `format_valid` marks and the
        `format_error_count` remain persisted so the liaison can see which records
        failed."

        The pass marks every attached record rather than stopping at the first
        failure, so a lowercase account reference and a non-numeric postal code both
        register and the count of two holds the file where it was.

        Design: Corner/calculations/format_validation_counts_every_failing_record_and_holds_the_file
        """
        fx.set_clock(api)
        client = fx.register_client(
            api,
            client_code="CLC3",
            name="Format Error Federal",
            dr_readiness_required=False,
        )
        bundle = fx.lodged_file(
            api,
            client["id"],
            [
                fx.record_spec(
                    "ABC1301",
                    1,
                    3000,
                    address_line1="1800 Clean Street",
                    postal_code="30301",
                    postal_code_plus4="1801",
                ),
                fx.record_spec(
                    "abc1234",
                    2,
                    3000,
                    address_line1="1802 Clean Street",
                    postal_code="30301",
                    postal_code_plus4="1802",
                ),
                fx.record_spec(
                    "ABC1303",
                    3,
                    3000,
                    address_line1="1804 Clean Street",
                    postal_code="ABCDE",
                    postal_code_plus4=None,
                ),
            ],
            file_name="c3.csv",
            format_spec_code="DELIMITED",
            declared_record_count=3,
            declared_control_total_cents=9000,
        )

        response = api.validate_format(bundle.id, COMPOSITION_OPERATOR)
        validate_error(response, ApiErrorId.FILE_FORMAT_ERRORS.value, 422)

        data_file = fx.read_data_file(api, bundle.id)
        assert data_file["format_error_count"] == 2
        assert data_file["status"] == "RECEIVED"

        good, bad_ref, bad_postal = fx.file_records(api, bundle.id)
        assert good["format_valid"] is True
        assert bad_ref["format_valid"] is False
        assert bad_postal["format_valid"] is False

        held = api.control_check(bundle.id, COMPOSITION_OPERATOR)
        validate_error(held, ApiErrorId.FILE_INVALID_STATE.value, 409)


class TestFormatSpecSelectsThePredicate:
    """One address run through the XML predicate and then the DELIMITED one."""

    def test_xml_accepts_the_four_digit_postal_code_delimited_refuses(
        self, api: ApiClient
    ):
        """PRD §3.3: "Under `DELIMITED`, the record additionally requires `postal_code` to
        consist of exactly five digits 0 through 9 and nothing else."

        Under XML the layout clause asks only for a non-empty region code, so a
        four-digit postal code validates cleanly, while the very same address under
        DELIMITED fails the five-digit clause — the spec code decides, not the data.

        Design: Corner/calculations/xml_spec_predicate_accepts_a_postal_code_the_delimited_spec_rejects
        """
        fx.set_clock(api)
        client = fx.register_client(
            api,
            client_code="CLC4",
            name="Spec Selector Savings",
            dr_readiness_required=False,
        )
        short_postal = fx.record_spec(
            "ABC1401",
            1,
            2500,
            address_line1="1900 Markup Mews",
            region_code="GA",
            postal_code="3030",
            postal_code_plus4=None,
        )
        xml_bundle = fx.lodged_file(
            api,
            client["id"],
            [short_postal],
            file_name="c4.xml",
            format_spec_code="XML",
            declared_record_count=1,
            declared_control_total_cents=2500,
        )

        validated = fx.validate_file_format(api, xml_bundle.id)

        assert validated["status"] == "FORMAT_VALIDATED"
        assert validated["format_error_count"] == 0
        assert fx.read_record(api, xml_bundle.records[0]["id"])["format_valid"] is True

        delimited_bundle = fx.lodged_file(
            api,
            client["id"],
            [short_postal],
            file_name="c4.csv",
            format_spec_code="DELIMITED",
            declared_record_count=1,
            declared_control_total_cents=2500,
        )
        refused = api.validate_format(delimited_bundle.id, COMPOSITION_OPERATOR)
        validate_error(refused, ApiErrorId.FILE_FORMAT_ERRORS.value, 422)

        delimited_file = fx.read_data_file(api, delimited_bundle.id)
        assert delimited_file["format_error_count"] == 1
        assert delimited_file["status"] == "RECEIVED"
        assert (
            fx.read_record(api, delimited_bundle.records[0]["id"])["format_valid"]
            is False
        )


class TestPresortWaterfallFallthrough:
    """Two five-digit groups, neither of which reaches the tier's minimum."""

    def test_unqualified_five_digit_groups_merge_in_the_three_digit_tier(
        self, api: ApiClient
    ):
        """PRD §3.5: "That residue is grouped by the first three characters of the backing
        record's `postal_code`, again in ascending key order, and any group holding at
        least 2 pieces is assigned `THREE_DIGIT`."

        Groups of two and one both miss the three-piece five-digit minimum, so the
        residue falls to the three-digit tier where the shared 303 prefix gathers all
        three pieces into a single batch rather than leaving anything unqualified.

        Design: Corner/calculations/presort_falls_through_to_three_digit_when_no_five_digit_group_qualifies
        """
        fx.set_clock(api)
        client = fx.register_client(
            api,
            client_code="CLC5",
            name="Waterfall Fallthrough Mutual",
            dr_readiness_required=False,
        )
        template = fx.create_active_template(
            api,
            client["id"],
            template_code="T-C5",
            sheets_per_document=1,
            color_pages_per_document=0,
            mail_class_preference="FIRST_CLASS",
        )
        bundle = fx.accepted_file(
            api,
            client["id"],
            [
                fx.record_spec(
                    "ABC1501",
                    1,
                    4000,
                    address_line1="2000 Tier Two Terrace",
                    postal_code="30301",
                    postal_code_plus4="2001",
                ),
                fx.record_spec(
                    "ABC1502",
                    2,
                    4000,
                    address_line1="2002 Tier Two Terrace",
                    postal_code="30301",
                    postal_code_plus4="2002",
                ),
                fx.record_spec(
                    "ABC1503",
                    3,
                    4000,
                    address_line1="2004 Tier Two Terrace",
                    postal_code="30355",
                    postal_code_plus4="2003",
                ),
            ],
            file_name="c5.csv",
            declared_record_count=3,
            declared_control_total_cents=12000,
        )
        job = fx.compose_job(api, bundle.id, template["id"])

        presorted = fx.presort_job(api, job["id"])

        assert presorted["status"] == "PRESORTED"
        assert presorted["print_piece_count"] == 3

        batches = fx.list_batches(api, job["id"])
        assert len(batches) == 1
        assert batches[0]["presort_bucket"] == "THREE_DIGIT"
        assert batches[0]["piece_count"] == 3
        assert batches[0]["tray_count"] == a.expected_tray_count(3) == 1
        assert batches[0]["mail_class"] == "FIRST_CLASS"
        assert batches[0]["reserved_insert_sheets"] == 0

        _three, three_meta = validate_paginated(
            api.list_mail_pieces(
                INTEGRITY_AUDITOR,
                {"composition_job_id": job["id"], "presort_bucket": "THREE_DIGIT"},
            )
        )
        assert three_meta["total_count"] == 3
        _five, five_meta = validate_paginated(
            api.list_mail_pieces(
                INTEGRITY_AUDITOR,
                {"composition_job_id": job["id"], "presort_bucket": "FIVE_DIGIT"},
            )
        )
        assert five_meta["total_count"] == 0


class TestFiveDigitMinimumIsInclusive:
    """Three pieces sharing one postal code, which is exactly the floor."""

    def test_three_pieces_qualify_at_the_exact_five_digit_minimum(
        self, api: ApiClient
    ):
        """PRD §3.5: "The residue is grouped by the backing record's full `postal_code`,
        and the groups are considered in ascending key order; any group holding at least
        3 pieces is assigned `presort_bucket` `FIVE_DIGIT` in its entirety."

        The five-digit tier takes any group holding at least three pieces, so a
        group of exactly three qualifies where a group of two would have fallen
        through to the three-digit tier.

        Design: Corner/calculations/five_digit_qualifies_at_exactly_the_three_piece_minimum
        """
        fx.set_clock(api)
        client = fx.register_client(
            api,
            client_code="CLC6",
            name="Exact Minimum Insurance",
            dr_readiness_required=False,
        )
        template = fx.create_active_template(
            api,
            client["id"],
            template_code="T-C6",
            sheets_per_document=1,
            color_pages_per_document=0,
            mail_class_preference="FIRST_CLASS",
        )
        bundle = fx.accepted_file(
            api,
            client["id"],
            [
                fx.record_spec(
                    f"ABC160{i}",
                    i,
                    4000,
                    address_line1=f"{2098 + 2 * i} Five Digit Drive",
                    postal_code="30301",
                    postal_code_plus4=f"210{i}",
                )
                for i in (1, 2, 3)
            ],
            file_name="c6.csv",
            declared_record_count=3,
            declared_control_total_cents=12000,
        )
        job = fx.compose_job(api, bundle.id, template["id"])

        presorted = fx.presort_job(api, job["id"])

        assert presorted["status"] == "PRESORTED"
        batches = fx.list_batches(api, job["id"])
        assert len(batches) == 1
        assert batches[0]["presort_bucket"] == "FIVE_DIGIT"
        assert batches[0]["piece_count"] == 3
        assert batches[0]["tray_count"] == 1
        for piece in fx.list_pieces(api, job["id"]):
            assert piece["presort_bucket"] == "FIVE_DIGIT"
            assert piece["mail_class"] == "FIRST_CLASS"


class TestSuppressedPieceLeavesThePresortResidue:
    """Three same-postal records, one of them suppressed before composition."""

    def test_the_suppressed_piece_joins_no_tier_and_shrinks_the_group(
        self, api: ApiClient
    ):
        """PRD §3.5: "The candidate set is the job's print-channel, non-void pieces: every
        piece whose `piece_status` is neither `SUPPRESSED` nor `VOID`."

        Only pieces bound for print take part in the waterfall, so removing one of
        three same-postal pieces drops the five-digit group under its minimum and the
        surviving pair lands in a two-piece three-digit batch.

        Design: Corner/calculations/suppressed_electronic_piece_is_excluded_from_every_presort_tier
        """
        fx.set_clock(api)
        client = fx.register_client(
            api,
            client_code="CLC7",
            name="Suppression Shrinkage Trust",
            dr_readiness_required=False,
        )
        template = fx.create_active_template(
            api,
            client["id"],
            template_code="T-C7",
            sheets_per_document=1,
            color_pages_per_document=0,
            mail_class_preference="FIRST_CLASS",
        )
        enrollment = fx.suppress_account(api, client["id"], "ABC1701", "EMAIL")
        assert fx.read_client(api, client["id"])["paperless_sync_epoch"] == 1
        assert enrollment["status"] == "ENROLLED"
        assert enrollment["enrolled_epoch"] == 1

        bundle = fx.accepted_file(
            api,
            client["id"],
            [
                fx.record_spec(
                    f"ABC170{i}",
                    i,
                    4000,
                    address_line1=f"{2198 + 2 * i} Paperless Parkway",
                    postal_code="30301",
                    postal_code_plus4=f"220{i}",
                )
                for i in (1, 2, 3)
            ],
            file_name="c7.csv",
            declared_record_count=3,
            declared_control_total_cents=12000,
        )

        job = fx.compose_job(api, bundle.id, template["id"])

        assert job["composition_epoch"] == 1
        assert job["electronic_piece_count"] == 1
        assert job["print_piece_count"] == 2
        assert job["expected_piece_count"] == 3
        assert job["accountable_piece_count"] == 3

        presorted = fx.presort_job(api, job["id"])
        assert presorted["status"] == "PRESORTED"

        batches = fx.list_batches(api, job["id"])
        assert len(batches) == 1
        assert batches[0]["presort_bucket"] == "THREE_DIGIT"
        assert batches[0]["piece_count"] == 2

        suppressed_record = fx.file_records(api, bundle.id)[0]
        assert suppressed_record["account_ref"] == "ABC1701"
        pieces = fx.list_pieces(api, job["id"])
        suppressed_piece = next(
            p for p in pieces if p["statement_record_id"] == suppressed_record["id"]
        )
        assert suppressed_record["delivery_channel"] == "ELECTRONIC"
        assert suppressed_piece["piece_status"] == "SUPPRESSED"
        assert suppressed_piece["mail_class"] == "NONE_ELECTRONIC"
        assert suppressed_piece["presort_bucket"] == "PENDING"
        assert suppressed_piece["presort_batch_id"] is None

        _rows, meta = validate_paginated(
            api.list_mail_pieces(
                INTEGRITY_AUDITOR,
                {"composition_job_id": job["id"], "piece_status": "SUPPRESSED"},
            )
        )
        assert meta["total_count"] == 1


class TestSuppressionSnapshotIsNotRetroactive:
    """The same account composed once before its sync and once after it."""

    def test_a_later_sync_never_re_projects_an_earlier_job(self, api: ApiClient):
        """PRD §3.4: "The record is suppressed when four conditions all hold: such a row
        exists; its `status` is `ENROLLED`; its `enrolled_epoch` is not null; and its
        `enrolled_epoch` is less than or equal to the job's `composition_epoch`, an
        inclusive comparison."

        The job snapshots the client's epoch as it composes, so the job taken while
        the enrolment was still pending keeps its printed piece, and only the job
        composed after the sync — whose epoch matches the enrolment's exactly — is
        suppressed.

        Design: Corner/calculations/suppression_is_snapshotted_at_composition_and_never_retroactive
        """
        fx.set_clock(api)
        client = fx.register_client(
            api,
            client_code="CLC8",
            name="Epoch Snapshot Savings",
            dr_readiness_required=False,
        )
        assert client["paperless_sync_epoch"] == 0
        template = fx.create_active_template(
            api,
            client["id"],
            template_code="T-C8",
            sheets_per_document=1,
            color_pages_per_document=0,
            mail_class_preference="FIRST_CLASS",
        )
        enrollment = fx.enroll_account(api, client["id"], "ABC1801", "PORTAL")
        assert enrollment["status"] == "PENDING"

        def _file(file_name):
            return fx.accepted_file(
                api,
                client["id"],
                [
                    fx.record_spec(
                        "ABC1801",
                        1,
                        4000,
                        address_line1="2300 Snapshot Square",
                        postal_code="30301",
                        postal_code_plus4="2301",
                    )
                ],
                file_name=file_name,
                declared_record_count=1,
                declared_control_total_cents=4000,
            )

        first_bundle = _file("c8-aug.csv")
        first_job = fx.compose_job(api, first_bundle.id, template["id"])
        assert first_job["composition_epoch"] == 0
        assert first_job["print_piece_count"] == 1
        second_bundle = _file("c8-sep.csv")

        synced = fx.confirm_enrollments(api, client["id"], ["ABC1801"])
        assert synced["paperless_sync_epoch"] == 1
        second_job = fx.compose_job(api, second_bundle.id, template["id"])

        assert second_job["composition_epoch"] == 1
        assert second_job["electronic_piece_count"] == 1

        assert fx.file_records(api, first_bundle.id)[0]["delivery_channel"] == "PRINT"
        assert fx.list_pieces(api, first_job["id"])[0]["piece_status"] == "COMPOSED"
        assert (
            fx.file_records(api, second_bundle.id)[0]["delivery_channel"] == "ELECTRONIC"
        )
        assert fx.list_pieces(api, second_job["id"])[0]["piece_status"] == "SUPPRESSED"


class TestRunWindowSizingFloorAndCeiling:
    """One sheet on a fast press and three sheets on a one-sheet-an-hour press."""

    def test_the_floor_holds_a_short_run_and_the_ceiling_stretches_a_slow_one(
        self, api: ApiClient
    ):
        """PRD §3.6: "The run's `run_minutes` is the larger of a 60-minute minimum and the
        quotient of `planned_sheet_count` multiplied by 60 divided by the line's
        `sheets_per_hour`, that quotient being rounded up to the next whole minute."

        A single sheet needing one minute of press time is floored to the sixty
        minute minimum, while three sheets on a one-sheet-an-hour line ceiling up to
        exactly one hundred and eighty minutes, so the two windows close at ten and
        at twelve.

        Design: Corner/calculations/run_window_sizing_floors_short_runs_and_ceilings_slow_presses
        """
        fx.set_clock(api)
        client = fx.register_client(
            api,
            client_code="CLC9",
            name="Window Sizing Life",
            dr_readiness_required=False,
        )
        fast_line = fx.register_press_line(
            api,
            line_code="PL-C9F",
            capabilities=["DUPLEX"],
            sheets_per_hour=600,
            daily_sheet_capacity=5000,
            changeover_buffer_minutes=30,
        )
        slow_line = fx.register_press_line(
            api,
            line_code="PL-C9S",
            capabilities=["DUPLEX"],
            sheets_per_hour=1,
            daily_sheet_capacity=5000,
            changeover_buffer_minutes=30,
        )

        def _presorted(template_code, sheets, file_name, account_ref, address):
            template = fx.create_active_template(
                api,
                client["id"],
                template_code=template_code,
                sheets_per_document=sheets,
                color_pages_per_document=0,
                mail_class_preference="FIRST_CLASS",
            )
            bundle = fx.accepted_file(
                api,
                client["id"],
                [
                    fx.record_spec(
                        account_ref,
                        1,
                        4000,
                        address_line1=address,
                        postal_code="30301",
                        postal_code_plus4="2401",
                    )
                ],
                file_name=file_name,
                declared_record_count=1,
                declared_control_total_cents=4000,
            )
            job = fx.compose_job(api, bundle.id, template["id"])
            return fx.presort_job(api, job["id"])

        job_a = _presorted("T-C9A", 1, "c9a.csv", "ABC1901", "2400 Floor Field")
        job_b = _presorted("T-C9B", 3, "c9b.csv", "ABC1902", "2402 Floor Field")
        assert job_a["print_sheet_count"] == 1
        assert job_b["print_sheet_count"] == 3

        run_a = fx.schedule_job(
            api, job_a["id"], "2026-08-05T09:00:00Z", fast_line["id"]
        )
        run_b = fx.schedule_job(
            api, job_b["id"], "2026-08-05T09:00:00Z", slow_line["id"]
        )

        assert run_a["planned_sheet_count"] == 1
        assert run_a["run_minutes"] == a.expected_run_minutes(1, 600) == 60
        a.assert_instant(run_a["window_end"], "2026-08-05T10:00:00Z", "run_a.window_end")

        assert run_b["planned_sheet_count"] == 3
        assert run_b["run_minutes"] == a.expected_run_minutes(3, 1) == 180
        a.assert_instant(run_b["window_end"], "2026-08-05T12:00:00Z", "run_b.window_end")

        assert run_a["selection_mode"] == "EXPLICIT"
        assert run_b["selection_mode"] == "EXPLICIT"
        assert run_a["press_line_id"] != run_b["press_line_id"]


class TestReplicationLagLimitIsInclusive:
    """One recovery site walked across the fifteen-minute replication limit."""

    def test_a_lag_of_exactly_fifteen_minutes_still_reads_ready(self, api: ApiClient):
        """PRD §2.11: "Both of those comparisons are exclusive at the boundary — a logical
        clock exactly equal to `readiness_valid_until` still reads `READY`, and a
        replication lag of exactly 15 minutes still reads `READY`."

        The lag comparison is strict, so sixteen minutes degrades the site to STALE
        while a return to exactly fifteen restores READY, and neither read-through
        touches the drill history.

        Design: Corner/calculations/dr_readiness_holds_ready_at_the_exact_replication_lag_limit
        """
        fx.set_clock(api)
        site = fx.register_dr_site(
            api, site_code="DR-C10", replication_lag_minutes=15
        )
        assert site["readiness_status"] == "UNTESTED"
        assert site["readiness_valid_until"] is None
        assert site["last_drill_result"] == "NONE"

        drilled = fx.record_drill(api, site["id"], "PASS")
        assert drilled["readiness_status"] == "READY"
        a.assert_instant(
            drilled["readiness_valid_until"],
            "2026-08-31T00:00:00Z",
            "site.readiness_valid_until",
        )

        over_limit = fx.patch_dr_site(api, site["id"], replication_lag_minutes=16)
        assert over_limit["replication_lag_minutes"] == 16
        assert over_limit["readiness_status"] == "STALE"

        at_limit = fx.patch_dr_site(api, site["id"], replication_lag_minutes=15)
        assert at_limit["replication_lag_minutes"] == 15
        assert at_limit["readiness_status"] == "READY"

        assert at_limit["last_drill_result"] == "PASS"
        assert at_limit["drill_count"] == 1
        a.assert_instant(
            at_limit["readiness_valid_until"],
            "2026-08-31T00:00:00Z",
            "site.readiness_valid_until",
        )


class TestDrillValidityDecay:
    """A passing drill read at its expiry instant, one minute later, then failed."""

    def test_readiness_survives_the_expiry_instant_and_a_failed_drill_pins_failed(
        self, api: ApiClient
    ):
        """PRD §2.11: "From there the disposition is decided by the first matching
        condition: if `last_drill_result` is `FAIL`, readiness is `FAILED`; otherwise,
        if the logical clock is strictly later than `readiness_valid_until`, readiness
        is `STALE`; otherwise, if `replication_lag_minutes` is strictly greater than 15,
        readiness is `STALE`; otherwise readiness is `READY`."

        The validity comparison is strict too, so the site is still READY at exactly
        the thirty-day horizon and STALE one minute past it with no write in between,
        and a fresh failing drill restarts the horizon while pinning readiness to
        FAILED rather than STALE.

        Design: Corner/calculations/dr_readiness_decays_one_minute_past_validity_and_a_failed_drill_reads_failed
        """
        fx.set_clock(api)
        site = fx.register_dr_site(api, site_code="DR-C11", replication_lag_minutes=5)
        drilled = fx.record_drill(api, site["id"], "PASS")
        a.assert_instant(
            drilled["readiness_valid_until"],
            "2026-08-31T00:00:00Z",
            "site.readiness_valid_until",
        )
        assert drilled["drill_count"] == 1

        fx.set_clock(api, "2026-08-31T00:00:00Z")
        assert fx.read_dr_site(api, site["id"])["readiness_status"] == "READY"

        fx.set_clock(api, "2026-08-31T00:01:00Z")
        assert fx.read_dr_site(api, site["id"])["readiness_status"] == "STALE"

        failed = fx.record_drill(api, site["id"], "FAIL")
        assert failed["readiness_status"] == "FAILED"
        assert failed["last_drill_result"] == "FAIL"
        assert failed["drill_count"] == 2
        a.assert_instant(
            failed["readiness_valid_until"],
            "2026-09-30T00:01:00Z",
            "site.readiness_valid_until",
        )


class TestDuplicateEvidenceSurvivesReconciliation:
    """One piece read twice at the same stage, then reconciled."""

    def test_the_duplicate_verdict_is_left_alone_and_breaches_the_job(
        self, api: ApiClient
    ):
        """PRD §3.7: "A piece already carrying `DUPLICATE_SCAN` is left exactly as it is —
        a duplicate read is settled evidence, not a pending condition awaiting
        resolution."

        Reconciliation rewrites only the unverified and the matched, so a piece
        already carrying a duplicate read keeps that verdict instead of being
        downgraded to a missing scan, and the duplicate count alone breaches the job.

        Design: Corner/calculations/duplicate_stage_evidence_survives_reconcile_and_breaches_the_job
        """
        fx.set_clock(api)
        client = fx.register_client(
            api,
            client_code="CLC12",
            name="Duplicate Scan Depository",
            dr_readiness_required=False,
        )
        fx.fund_client(api, client["id"], 100000)
        line = fx.register_press_line(
            api,
            line_code="PL-C12",
            capabilities=["DUPLEX"],
            sheets_per_hour=600,
            daily_sheet_capacity=2000,
        )
        template = fx.create_active_template(
            api,
            client["id"],
            template_code="T-C12",
            sheets_per_document=1,
            color_pages_per_document=0,
            mail_class_preference="FIRST_CLASS",
        )
        bundle = fx.accepted_file(
            api,
            client["id"],
            [
                fx.record_spec(
                    "ABC2001",
                    1,
                    9000,
                    address_line1="2500 Duplicate Domain",
                    postal_code="30301",
                    postal_code_plus4="2501",
                )
            ],
            file_name="c12.csv",
            declared_record_count=1,
            declared_control_total_cents=9000,
        )
        job = fx.compose_job(api, bundle.id, template["id"])
        fx.presort_job(api, job["id"])
        piece = fx.list_pieces(api, job["id"])[0]
        run = fx.schedule_job(api, job["id"], "2026-08-05T09:00:00Z", line["id"])
        fx.set_clock(api, "2026-08-05T09:00:00Z")
        fx.start_run(api, run["id"])

        first = fx.scan_stage(api, piece["id"], "PRINT", piece["imb_barcode"], "SCN-C12")
        second = fx.scan_stage(
            api, piece["id"], "PRINT", piece["imb_barcode"], "SCN-C12"
        )
        assert first["accepted"] is True
        assert second["accepted"] is False
        assert second["rejection_reason"] == "DUPLICATE_STAGE"

        fx.set_clock(api, "2026-08-05T10:00:00Z")
        completed = fx.complete_run(api, run["id"])
        assert completed["status"] == "COMPLETED"
        assert completed["printed_piece_count"] == 1
        assert fx.read_job(api, job["id"])["status"] == "PRINTED"

        reconciled = fx.reconcile(api, job["id"])

        assert reconciled["integrity_status"] == "BREACHED"
        assert reconciled["status"] == "INTEGRITY_HELD"
        assert reconciled["matched_piece_count"] == 0
        assert reconciled["missing_scan_count"] == 0
        assert reconciled["duplicate_scan_count"] == 1

        reread = fx.read_piece(api, piece["id"])
        assert reread["integrity_status"] == "DUPLICATE_SCAN"
        assert reread["piece_status"] == "PRINTED"

        _rows, meta = validate_paginated(
            api.list_scan_events(piece["id"], INTEGRITY_AUDITOR, {"accepted": "false"})
        )
        assert meta["total_count"] == 1


class TestCumulativeVariableContent:
    """Three amounts against two thresholds and two insert codes."""

    def test_every_rule_that_fires_adds_its_sheets_and_its_insert(
        self, api: ApiClient
    ):
        """PRD §3.4: "The template's `variable_content_rules` are then evaluated in
        ascending `rule_code` order, and every rule whose threshold is met contributes —
        this is an accumulation, not a band selection, so three rules that all fire all
        add their sheets."

        Both rules fire on the largest statement and their added sheets accumulate
        rather than the higher rule replacing the lower, the middle statement fires
        only the inclusive lower threshold, and the smallest fires neither yet still
        carries the template's unconditional insert.

        Design: Corner/calculations/variable_content_rules_accumulate_sheets_across_every_met_threshold
        """
        fx.set_clock(api)
        insert_a = fx.register_insert_stock(
            api,
            insert_code="INS-C17A",
            description="Annual privacy notice",
            effective_from="2026-01-01T00:00:00Z",
            sheets_per_insert=2,
            received_count=10,
        )
        insert_b = fx.register_insert_stock(
            api,
            insert_code="INS-C17B",
            description="High balance disclosure",
            effective_from="2026-01-01T00:00:00Z",
            sheets_per_insert=1,
            received_count=10,
        )
        client = fx.register_client(
            api,
            client_code="CLC17",
            name="Cumulative Rules Credit Union",
            dr_readiness_required=False,
        )
        template = fx.create_active_template(
            api,
            client["id"],
            template_code="T-C17",
            duplex_required=True,
            sheets_per_document=1,
            color_pages_per_document=4,
            mail_class_preference="FIRST_CLASS",
            required_insert_codes=["INS-C17A"],
            variable_content_rules=[
                f.variable_content_rule("R1", 10000, 1, None),
                f.variable_content_rule("R2", 50000, 2, "INS-C17B"),
            ],
        )
        bundle = fx.accepted_file(
            api,
            client["id"],
            [
                fx.record_spec(
                    "ABC2101",
                    1,
                    50000,
                    address_line1="2600 Threshold Trace",
                    postal_code="30301",
                    postal_code_plus4="2601",
                ),
                fx.record_spec(
                    "ABC2102",
                    2,
                    10000,
                    address_line1="2602 Threshold Trace",
                    postal_code="30301",
                    postal_code_plus4="2602",
                ),
                fx.record_spec(
                    "ABC2103",
                    3,
                    9999,
                    address_line1="2604 Threshold Trace",
                    postal_code="30301",
                    postal_code_plus4="2603",
                ),
            ],
            file_name="c17.csv",
            declared_record_count=3,
            declared_control_total_cents=69999,
        )

        job = fx.compose_job(api, bundle.id, template["id"])

        high, edge, low = fx.file_records(api, bundle.id)
        assert high["computed_sheet_count"] == 1 + (1 + 2) + (2 + 1) == 7
        assert high["computed_insert_codes"] == ["INS-C17A", "INS-C17B"]
        assert edge["computed_sheet_count"] == 1 + 1 + 2 == 4
        assert edge["computed_insert_codes"] == ["INS-C17A"]
        assert low["computed_sheet_count"] == 1 + 0 + 2 == 3
        assert low["computed_insert_codes"] == ["INS-C17A"]

        assert job["total_sheet_count"] == 14
        assert job["insert_sheet_total"] == 3 + 2 + 2 == 7
        assert job["color_page_count"] == 12
        for piece in fx.list_pieces(api, job["id"]):
            assert piece["color_page_count"] == min(4, piece["sheet_count"] * 2) == 4

        stock_b = fx.read_insert_stock(api, insert_b["id"])
        assert stock_b["reserved_count"] == 1
        assert stock_b["on_hand_count"] == 9
        a.assert_insert_stock_ledger(stock_b)
        stock_a = fx.read_insert_stock(api, insert_a["id"])
        assert stock_a["reserved_count"] == 3
        assert stock_a["on_hand_count"] == 7
        a.assert_insert_stock_ledger(stock_a)
