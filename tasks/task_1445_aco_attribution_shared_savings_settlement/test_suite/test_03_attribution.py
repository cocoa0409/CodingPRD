"""Attribution: alignment windows, plurality, lock cascade, OCC, listings."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_beneficiary,
    add_participant,
    adjudicate,
    create_alignment_run_payload,
    create_period,
    current_period_version,
    get_period,
    ingest_claim,
    list_records,
    lock_period,
    open_period,
    run_alignment,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAlignmentWindowPlacement:
    def test_prospective_window_inside_performance_year_rejected(self, api, admin_headers):
        """PRD §3.3: "A `PROSPECTIVE` run looks backward: its `window_end_date`
        must fall on or before the period's `performance_start_date` — a
        prior-year alignment window." and "A window misplaced for its methodology
        is rejected with `ERR_DATE_OUTSIDE_PERIOD`."

        Design: Corner/validations/prospective_window_inside_performance_year_rejected
        """
        period = create_period(tax_id="ACO-V5")
        open_period(period["id"])
        version = current_period_version(period["id"])
        res = api.create_alignment_run(
            period["id"],
            create_alignment_run_payload(
                version, methodology="PROSPECTIVE",
                window_start_date="2025-01-01", window_end_date="2026-06-01",
            ),
            admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_DATE_OUTSIDE_PERIOD, expected_status=422)


class TestAlignmentWindowOverlapHalfOpen:
    def _setup_with_first_run(self, api, admin_headers):
        period = create_period(tax_id="ACO-AW")
        participant = add_participant(period["id"], "100000001", "PA", 10000)
        beneficiary = add_beneficiary("MBI-AW-1", 1980)
        open_period(period["id"])
        ingest_claim(period["id"], beneficiary["id"], "2026-03-15", 20000, "PART_B",
                     participant_id=participant["id"])
        run1 = run_alignment(period["id"], window_start="2026-01-01", window_end="2026-07-01")
        return period, run1

    def test_adjacent_alignment_windows_allowed_and_supersede(self, api, admin_headers):
        """PRD §3.3: "because windows are half-open, two windows that merely touch
        at a boundary do not conflict" and "When a new alignment run completes for
        the same period and methodology, the prior run of that pairing moves from
        `COMPLETED` to `SUPERSEDED`".

        Design: Difficulty/resource_temporal_overlap/alignment_window_overlap_half_open
        """
        period, run1 = self._setup_with_first_run(api, admin_headers)
        run2 = validate_success(
            api.create_alignment_run(
                period["id"],
                create_alignment_run_payload(
                    current_period_version(period["id"]),
                    window_start_date="2026-07-01", window_end_date="2027-01-01",
                ),
                admin_headers,
            ),
            201,
        )
        assert run2["status"] == "COMPLETED"
        run1_after = validate_success(api.get_alignment_run(run1["id"], admin_headers), 200)
        assert run1_after["status"] == "SUPERSEDED"

    def test_overlapping_alignment_window_rejected(self, api, admin_headers):
        """PRD §3.3: "Windows of the same period and methodology must not overlap
        any existing `COMPLETED` or `LOCKED` run — but because windows are
        half-open, two windows that merely touch at a boundary do not conflict;
        a true overlap is rejected with `ERR_ALIGNMENT_WINDOW_OVERLAP`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/alignment_window_overlap_half_open
        """
        period, _run1 = self._setup_with_first_run(api, admin_headers)
        run_alignment(period["id"], window_start="2026-07-01", window_end="2027-01-01")
        res = api.create_alignment_run(
            period["id"],
            create_alignment_run_payload(
                current_period_version(period["id"]),
                window_start_date="2026-06-30", window_end_date="2026-12-01",
            ),
            admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_ALIGNMENT_WINDOW_OVERLAP, expected_status=409)


class TestPlurality:
    def test_attribution_plurality_tie_break_by_created_at(self, api, admin_headers):
        """PRD §3.3: "declares the participant with the largest summed cost the
        plurality winner. Ties break first toward the participant with the most
        included claims, then toward the participant whose record was created
        earliest."

        Design: Corner/calculations/attribution_plurality_tie_break_by_created_at
        """
        period = create_period(tax_id="ACO-C5")
        pa = add_participant(period["id"], "100000001", "PA", 5000)
        pb = add_participant(period["id"], "100000002", "PB", 5000)
        beneficiary = add_beneficiary("MBI-C5", 1980)
        open_period(period["id"])
        ingest_claim(period["id"], beneficiary["id"], "2026-02-01", 30000, "PART_B",
                     participant_id=pa["id"])
        ingest_claim(period["id"], beneficiary["id"], "2026-03-01", 30000, "PART_B",
                     participant_id=pb["id"])
        run = run_alignment(period["id"])
        records = list_records(alignment_run_id=run["id"])
        assert len(records) == 1
        assert records[0]["participant_id"] == pa["id"]
        assert records[0]["plurality_cost_cents"] == 30000


class TestLockAssignmentCascade:
    def test_lock_assignment_cascades_records_and_runs(self, api, admin_headers):
        """PRD §4: "Transition `OPEN` → `ASSIGNMENT_LOCKED`; finalizes provisional
        attribution records and locks completed runs".

        Design: Corner/state_machines/lock_assignment_cascades_records_and_runs
        """
        period = create_period(tax_id="ACO-S8")
        participant = add_participant(period["id"], "100000001", "PA", 10000)
        beneficiary = add_beneficiary("MBI-S8", 1980)
        open_period(period["id"])
        claim = ingest_claim(period["id"], beneficiary["id"], "2026-02-01", 20000,
                             "PART_B", participant_id=participant["id"])
        adjudicate(claim["id"])
        run = run_alignment(period["id"])
        records_pre = list_records(alignment_run_id=run["id"])
        assert len(records_pre) == 1
        assert records_pre[0]["status"] == "PROVISIONAL"

        locked = lock_period(period["id"])
        assert locked["status"] == "ASSIGNMENT_LOCKED"

        records_post = list_records(alignment_run_id=run["id"])
        assert records_post[0]["status"] == "FINAL"
        run_after = validate_success(api.get_alignment_run(run["id"], admin_headers), 200)
        assert run_after["status"] == "LOCKED"

    def test_immediate_visibility_after_lock_assignment(self, api, admin_headers):
        """PRD §4: "Transition `OPEN` → `ASSIGNMENT_LOCKED`; finalizes provisional
        attribution records and locks completed runs" — the cascaded states are
        observable on the immediately following read.

        Design: Corner/consistency_model/immediate_visibility_after_lock_assignment
        """
        period = create_period(tax_id="ACO-K1")
        participant = add_participant(period["id"], "100000001", "PA", 10000)
        beneficiary = add_beneficiary("MBI-K1", 1980)
        open_period(period["id"])
        claim = ingest_claim(period["id"], beneficiary["id"], "2026-02-01", 20000,
                             "PART_B", participant_id=participant["id"])
        adjudicate(claim["id"])
        run_alignment(period["id"])
        lock_period(period["id"])
        records = list_records(agreement_period_id=period["id"])
        assert len(records) == 1
        assert records[0]["status"] == "FINAL"


class TestRecordDiscovery:
    def test_attribution_records_reverse_reachable_by_period(self, api, admin_headers):
        """PRD §3.3: "The run itself lands in `COMPLETED` status with
        `records_created_count` equal to the number of records it generated, and
        the period's `version` increments by 1." and each record is "linked back
        to its producing run via `alignment_run_id`".
        PRD §4: "List attribution records, optional filters
        (`agreement_period_id`, `beneficiary_id`, `alignment_run_id`,
        `participant_id`, `status`)".

        Design: Corner/endpoints/attribution_records_reverse_reachable_by_period
        """
        period = create_period(tax_id="ACO-N2")
        participant = add_participant(period["id"], "100000001", "PA", 10000)
        beneficiary = add_beneficiary("MBI-N2", 1980)
        open_period(period["id"])
        claim = ingest_claim(period["id"], beneficiary["id"], "2026-02-01", 20000,
                             "PART_B", participant_id=participant["id"])
        adjudicate(claim["id"])
        run = run_alignment(period["id"])
        assert run["records_created_count"] == 1

        res = api.list_attribution_records(
            admin_headers, params={"agreement_period_id": period["id"]},
        )
        records, meta = validate_paginated(res)
        assert meta["total_count"] == 1
        assert records[0]["beneficiary_id"] == beneficiary["id"]
        assert records[0]["alignment_run_id"] == run["id"]


class TestOccOnAlignmentRunCreate:
    def test_stale_version_on_alignment_run_create(self, api, admin_headers):
        """PRD §2.6: "If that value does not equal the period's current `version`
        — for example because another writer has since opened or locked the
        period, or has completed a run, benchmark, or settlement of their own —
        the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/stale_version_on_alignment_run_create
        """
        period = create_period(tax_id="ACO-X2")
        participant = add_participant(period["id"], "100000001", "PA", 10000)
        beneficiary = add_beneficiary("MBI-X2", 1980)
        open_period(period["id"])
        claim = ingest_claim(period["id"], beneficiary["id"], "2026-02-01", 20000,
                             "PART_B", participant_id=participant["id"])
        adjudicate(claim["id"])
        stale_version = current_period_version(period["id"])
        run_alignment(period["id"])  # advances the period version
        res = api.create_alignment_run(
            period["id"],
            create_alignment_run_payload(
                stale_version, methodology="PROSPECTIVE",
                window_start_date="2025-01-01", window_end_date="2026-01-01",
            ),
            admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
