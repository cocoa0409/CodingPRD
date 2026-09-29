"""Two cross-cutting guarantees the rest of the suite touches only in passing.

The first is that a stale picture of a held job is detectable even when the piece
being reprinted has not moved at all; the second is that every derived counter is
written in the request that caused it rather than settled afterwards.
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
    BUREAU_ADMIN,
    CLIENT_LIAISON,
    COMPOSITION_OPERATOR,
    INTEGRITY_AUDITOR,
)


class TestASecondReprintDetectsTheStaleJobPicture:
    """One held job carried through a reprint and a second reconciliation, then
    reprinted again from the auditor's original reading."""

    def test_the_second_reprint_is_refused_on_the_original_version_and_accepted_on_the_current_one(
        self, api: ApiClient
    ):
        """PRD §2.7: "If that value does not equal the job's current `version`, the reprint
        is rejected with `ERR_STALE_COMPOSITION_JOB_VERSION` (HTTP 412)."

        The third piece never changes — it is unscanned and reprint-eligible
        throughout — so the intervening reprint and reconciliation are visible only
        as two increments of the owning job's version, which is exactly what the
        pinned field detects; the refused attempt voids nothing.

        Design: Corner/cross_cutting_complexity_layers/stale_expected_composition_job_version_on_a_later_reprint_returns_412
        """
        pipeline = fx.integrity_held_job(
            api,
            unscanned_piece_indexes=(1, 2),
            client_code="CLC1",
            client_overrides={
                "name": "Stale View Statements",
                "dr_readiness_required": False,
            },
            template_code="T-C1",
            template_overrides={
                "sheets_per_document": 1,
                "duplex_required": False,
                "color_pages_per_document": 0,
                "mail_class_preference": "FIRST_CLASS",
            },
            press_line_code="PL-C1",
            press_line_overrides={
                "capabilities": ["DUPLEX"],
                "sheets_per_hour": 600,
                "daily_sheet_capacity": 2000,
            },
            file_name="c1.csv",
            specs=[
                fx.record_spec(
                    "ABC4701",
                    1,
                    4000,
                    address_line1="4700 Stale View Way",
                    postal_code_plus4="4701",
                ),
                fx.record_spec(
                    "ABC4702",
                    2,
                    4000,
                    address_line1="4702 Stale View Way",
                    postal_code_plus4="4702",
                ),
                fx.record_spec(
                    "ABC4703",
                    3,
                    4000,
                    address_line1="4704 Stale View Way",
                    postal_code_plus4="4703",
                ),
            ],
        )
        job_id = pipeline.job["id"]
        held = pipeline.job
        stale_version = held["version"]
        assert held["status"] == "INTEGRITY_HELD"
        a.assert_integrity_counters(held, 1, 2, 0, "BREACHED")

        pieces = fx.list_pieces(api, job_id)
        assert [piece["piece_seq"] for piece in pieces] == [1, 2, 3]
        piece_two, piece_three = pieces[1], pieces[2]
        assert piece_two["integrity_status"] == "SCAN_MISSING"
        assert piece_three["integrity_status"] == "SCAN_MISSING"
        assert piece_three["piece_status"] == "COMPOSED"

        replacement_two = fx.reprint_piece(
            api, piece_two["id"], stale_version, "no scans at all"
        )
        assert replacement_two["reprint_of_piece_id"] == piece_two["id"]
        assert fx.read_job(api, job_id)["status"] == "PRINTED"

        second_hold = fx.reconcile(api, job_id)
        fresh_version = second_hold["version"]
        assert second_hold["status"] == "INTEGRITY_HELD"
        assert fresh_version == stale_version + 2
        a.assert_integrity_counters(second_hold, 1, 2, 0, "BREACHED")
        assert second_hold["reprint_chain_depth"] == 1

        before_piece = fx.read_piece(api, piece_three["id"])
        refused = api.create_reprint(
            piece_three["id"],
            f.reprint_payload(stale_version, "still no scans"),
            INTEGRITY_AUDITOR,
        )
        validate_error(
            refused, ApiErrorId.STALE_COMPOSITION_JOB_VERSION.value, 412
        )
        a.assert_unchanged(
            before_piece,
            fx.read_piece(api, piece_three["id"]),
            "piece_status",
            "integrity_status",
            "accepted_scan_count",
            "reprint_of_piece_id",
        )
        assert before_piece["piece_status"] == "COMPOSED"
        assert fx.read_job(api, job_id)["version"] == fresh_version

        replacement_three = fx.reprint_piece(
            api, piece_three["id"], fresh_version, "still no scans"
        )
        assert replacement_three["reprint_of_piece_id"] == piece_three["id"]
        assert replacement_three["id"] != replacement_two["id"]
        assert replacement_three["billable"] is False

        voided, meta = validate_paginated(
            api.list_mail_pieces(
                INTEGRITY_AUDITOR,
                {
                    "composition_job_id": job_id,
                    "piece_status": "VOID",
                    "limit": 100,
                },
            )
        )
        assert meta["total_count"] == 2
        assert {piece["id"] for piece in voided} == {
            piece_two["id"],
            piece_three["id"],
        }
        final = fx.read_job(api, job_id)
        assert final["void_piece_count"] == 2
        assert final["reprint_piece_count"] == 2
        assert final["accountable_piece_count"] == 3


class TestCompositionSettlesEveryCounterInItsOwnResponse:
    """One composition of a three-record file whose second account is paperless,
    read once from the creation body and once from a fresh retrieval."""

    def test_the_creation_body_already_carries_the_counters_the_reread_repeats(
        self, api: ApiClient
    ):
        """PRD §3.4: "The accepted file cascades to `CONSUMED` in the same request, and the
        job's `version` is set by its creation."

        Nothing about the composition is deferred: the two divergent sheet bases,
        the piece counts, the capped colour figure and the deadline are all in the
        201 body, the insert reservation and the file cascade are visible on the very
        next read, and an immediate re-read of the job repeats the same figures.

        Design: Corner/consistency_model/composition_response_carries_every_derived_counter_in_the_same_request
        """
        fx.set_clock(api)
        stock = fx.register_insert_stock(
            api,
            insert_code="INS-D1",
            description="Two-sheet regulatory notice",
            effective_from="2026-01-01T00:00:00Z",
            sheets_per_insert=2,
            received_count=10,
        )
        client = fx.register_client(
            api,
            client_code="CLD1",
            name="Immediate Insight Insurance",
            dr_readiness_required=False,
        )
        assert client["sla_turnaround_hours"] == 48
        template = fx.create_active_template(
            api,
            client["id"],
            template_code="T-D1",
            sheets_per_document=2,
            duplex_required=False,
            color_pages_per_document=1,
            mail_class_preference="FIRST_CLASS",
            required_insert_codes=["INS-D1"],
            variable_content_rules=[],
        )
        fx.suppress_account(api, client["id"], "ABC4802", "EMAIL")
        bundle = fx.accepted_file(
            api,
            client["id"],
            [
                fx.record_spec(
                    "ABC4801",
                    1,
                    4000,
                    address_line1="4800 Immediate Isle",
                    postal_code_plus4="4801",
                ),
                fx.record_spec(
                    "ABC4802",
                    2,
                    4000,
                    address_line1="4802 Immediate Isle",
                    postal_code_plus4="4802",
                ),
                fx.record_spec(
                    "ABC4803",
                    3,
                    4000,
                    address_line1="4804 Immediate Isle",
                    postal_code_plus4="4803",
                ),
            ],
            file_name="d1.csv",
        )
        accepted = fx.read_data_file(api, bundle.id)
        a.assert_instant(
            accepted["accepted_at"], "2026-08-01T00:00:00Z", "file.accepted_at"
        )

        created = get_success_data(
            api.create_composition_job(
                f.composition_job_payload(bundle.id, template["id"], False),
                COMPOSITION_OPERATOR,
            ),
            201,
        )

        a.assert_instant(
            created["sla_due_at"], "2026-08-03T00:00:00Z", "job.sla_due_at"
        )
        assert created["expected_piece_count"] == 3
        assert created["print_piece_count"] == 2
        assert created["electronic_piece_count"] == 1
        assert created["accountable_piece_count"] == 3
        assert created["total_sheet_count"] == 12
        assert created["print_sheet_count"] == 8
        assert created["insert_sheet_total"] == 6
        assert created["color_page_count"] == 3
        assert created["status"] == "COMPOSED"

        pieces = fx.list_pieces(api, created["id"])
        assert len(pieces) == 3
        for piece in pieces:
            assert piece["insert_codes"] == ["INS-D1"]
            assert piece["insert_sheet_count"] == 2
            assert piece["sheet_count"] == 4
            assert piece["color_page_count"] == min(1, 4 * 2) == 1
            assert piece["billable"] is True
        suppressed = [p for p in pieces if p["piece_status"] == "SUPPRESSED"]
        assert len(suppressed) == 1
        assert suppressed[0]["piece_seq"] == 2
        assert suppressed[0]["mail_class"] == "NONE_ELECTRONIC"

        reread = get_success_data(
            api.get_composition_job(created["id"], COMPOSITION_OPERATOR)
        )
        assert reread["total_sheet_count"] == created["total_sheet_count"]
        assert reread["print_sheet_count"] == created["print_sheet_count"]
        assert reread["insert_sheet_total"] == created["insert_sheet_total"]
        assert reread["color_page_count"] == created["color_page_count"]
        assert reread["sla_due_at"] == created["sla_due_at"]
        assert reread["version"] == created["version"]

        settled = get_success_data(api.get_insert_stock(stock["id"], BUREAU_ADMIN))
        assert settled["received_count"] == 10
        assert settled["on_hand_count"] == 8
        assert settled["reserved_count"] == 2
        assert settled["consumed_count"] == 0
        a.assert_insert_stock_ledger(settled)

        consumed_file = get_success_data(api.get_data_file(bundle.id, CLIENT_LIAISON))
        assert consumed_file["status"] == "CONSUMED"
