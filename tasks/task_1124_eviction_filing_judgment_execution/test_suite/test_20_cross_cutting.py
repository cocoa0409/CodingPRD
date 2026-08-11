"""Cross-cutting corners: OCC on notice drafting, ops-run checkpoint counts,
storage disposable boundary, immediate read-after-write
(PRD 2.8, 2.5, 3.7, 2.2)."""
from test_helpers import (
    ApiErrorId,
    CLERK_A,
    TEST_USERS,
    assert_instant_equal,
    create_case_payload,
    create_landlord_payload,
    create_notice_payload,
    create_tenancy_payload,
    create_unit_payload,
    get_case,
    get_notice,
    get_storage_record,
    make_landlord_headers,
    run_ops,
    set_clock,
    setup_case_draft,
    setup_executed_with_storage,
    setup_judgment_entered,
    validate_error,
    validate_success,
)
from test_helpers import api_client
from datetime import datetime, timedelta


class TestOccStaleVersionNoticeSupersede:
    """Corner instance: expected_case_version guards notice drafting; a stale
    version gets 412 and a fresh one supersedes."""

    def test_stale_version_rejected_fresh_supersedes(self, api):
        """PRD 2.8: "If another writer has advanced the case's version since
        that observation — for example by creating a notice of their own,
        which itself supersedes the prior notice and increments the case
        version by exactly 1 — the values will differ, and the request is
        rejected with ERR_STALE_VERSION (HTTP 412)." PRD 3.2: "On a
        NOTICE_ACTIVE case the same drafting action creates a replacement
        notice: the previously PENDING notice becomes SUPERSEDED, the new
        notice starts PENDING".

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_notice_supersede
        """
        ctx = setup_case_draft("CA")
        set_clock("2026-05-02T08:00:00Z")
        ll = make_landlord_headers(ctx["landlord"]["id"])
        case = get_case(ctx["case"]["id"])
        v1 = case["version"]

        n1 = validate_success(api.create_notice(
            case["id"],
            create_notice_payload(v1, claimed_rent_owed_cents=100000), ll), 201)
        assert n1["status"] == "PENDING"

        # Stale: v1 no longer matches (first create bumped it).
        resp = api.create_notice(
            case["id"],
            create_notice_payload(v1, claimed_rent_owed_cents=110000), ll)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

        case2 = get_case(case["id"])
        assert case2["version"] == v1 + 1

        n2 = validate_success(api.create_notice(
            case["id"],
            create_notice_payload(case2["version"],
                                  claimed_rent_owed_cents=110000), ll), 201)
        assert n2["status"] == "PENDING"
        assert get_notice(n1["id"])["status"] == "SUPERSEDED"


class TestOpsRunCheckpointCounts:
    """Corner instance: one ops run applies two sweeps at once and reports
    per-sweep counts."""

    def test_notice_expiry_and_judgment_finalization_counted(self, api):
        """PRD 2.5: "A CourtClerk performs an ops-run checkpoint sweep, which
        applies five steps in a fixed order: first, every notice still
        PENDING whose cure deadline has passed ... becomes EXPIRED ...;
        second, every judgment in ENTERED whose appeal_deadline has been
        reached or passed becomes FINAL; ... The sweep responds with a
        summary object containing the five integer counters notices_expired,
        judgments_finalized, writs_expired, writs_unscheduled, and
        storage_records_disposable."

        Design: Corner/cross_cutting_complexity_layers/ops_run_checkpoint_counts
        """
        # Case A: OH unit, PAY_OR_QUIT notice served 2026-06-01 (OH cure 5
        # days -> deadline 2026-06-06T23:59:59Z), still PENDING.
        ctx_oh = setup_case_draft("OH")
        set_clock("2026-06-01T11:00:00Z")
        ll = make_landlord_headers(ctx_oh["landlord"]["id"])
        case_oh = get_case(ctx_oh["case"]["id"])
        validate_success(api.create_notice(
            case_oh["id"],
            create_notice_payload(case_oh["version"],
                                  claimed_rent_owed_cents=80000,
                                  served_on="2026-06-01"), ll), 201)

        # Case B: CA judgment ENTERED at 2026-06-20T12:00:00Z (appeal
        # deadline 2026-06-25T12:00:00Z).
        ctx_ca = setup_judgment_entered("CA")

        # Sweep at exactly the CA appeal deadline: OH notice (past deadline)
        # expires; CA judgment finalizes at the >= boundary.
        set_clock("2026-06-25T12:00:00Z")
        summary = run_ops()
        assert summary["notices_expired"] == 1
        assert summary["judgments_finalized"] == 1
        assert summary["writs_expired"] == 0
        assert summary["writs_unscheduled"] == 0
        assert summary["storage_records_disposable"] == 0

        assert get_case(ctx_oh["case"]["id"])["status"] == "NOTICE_EXPIRED"
        from test_helpers import get_judgment

        assert get_judgment(ctx_ca["judgment"]["id"])["status"] == "FINAL"


class TestStorageDisposableBoundary:
    """Corner instance: at exactly disposal_eligible_on the record stays
    STORED; one second later the ops run marks it DISPOSABLE."""

    def test_exact_deadline_not_yet_disposable_then_disposable(self, api):
        """PRD 2.5: "fifth, every storage record still STORED whose
        disposal_eligible_on has passed becomes DISPOSABLE" and PRD 3.7: "The
        disposal_eligible_on instant is stored_at plus the statutory storage
        period — 15 days in CA, 14 in TX, 30 in OH — and the ops-run sweep
        moves a STORED record to DISPOSABLE once that instant has passed."

        Design: Corner/cross_cutting_complexity_layers/storage_disposable_boundary
        """
        ctx = setup_executed_with_storage("CA")
        sr_id = ctx["storage"]["id"]
        eligible = get_storage_record(sr_id)["disposal_eligible_on"]
        # CA: stored 2026-06-26T09:00:00Z + 15 days.
        assert_instant_equal(eligible, "2026-07-11T09:00:00Z")

        # At exactly the eligibility instant: NOT yet past it.
        set_clock(eligible)
        summary1 = run_ops()
        assert summary1["storage_records_disposable"] == 0
        assert get_storage_record(sr_id)["status"] == "STORED"

        # One second later.
        dt = datetime.fromisoformat(eligible.replace("Z", "+00:00"))
        set_clock((dt + timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ"))
        summary2 = run_ops()
        assert summary2["storage_records_disposable"] == 1
        assert get_storage_record(sr_id)["status"] == "DISPOSABLE"


class TestImmediateReadAfterWrite:
    """Corner instance: writes are immediately visible on a subsequent
    read."""

    def test_case_read_matches_create(self, api):
        """PRD 2.2: "operations that create or modify a resource will return
        the created or updated resource object in the data field." PRD 3.2:
        "A new case starts in DRAFT; the server mints its case_number in the
        format EV-<year>-<zero-padded sequence>".

        Design: Corner/consistency_model/immediate_read_after_write
        """
        landlord = validate_success(api.create_landlord(
            create_landlord_payload(), TEST_USERS["admin_headers"]), 201)
        ll = make_landlord_headers(landlord["id"])
        unit = validate_success(api.create_unit(
            create_unit_payload(landlord["id"], "CA"), ll), 201)
        tenancy = validate_success(api.create_tenancy(
            create_tenancy_payload(unit["id"]), ll), 201)
        created = validate_success(api.create_case(
            create_case_payload(tenancy["id"], "NONPAYMENT"), ll), 201)
        assert created["status"] == "DRAFT"

        read = validate_success(api.get_case(created["id"], CLERK_A), 200)
        assert read["status"] == "DRAFT"
        assert read["tenancy_id"] == tenancy["id"]
        assert read["case_number"] == created["case_number"]
