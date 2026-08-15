"""Validation-pipeline ordering under dual violation + same-day cap boundary."""
from test_helpers import (
    ApiErrorId,
    append_entries_ok,
    append_entries_payload,
    create_active_originator,
    create_warehoused_file,
    define_next_day_window,
    define_same_day_1_window,
    entry_payload,
    make_originator_headers,
    open_manual_risk_case,
    read_file,
    read_originator,
    resolve_case_ok,
    set_clock,
    setup_standard_environment,
    validate_error,
)


def _setup_watch_org_at_limit():
    """ACTIVE originator (limit 10000000) with 6000000 DEBIT outstanding, then
    moved to WATCH. Returns (org, file) where file is WAREHOUSED."""
    org = setup_standard_environment("Lambda Co", exposure_limit_cents=10_000_000)
    ach_file = create_warehoused_file(org, "CCD", "NEXT_DAY", "2026-08-03")
    appended = append_entries_ok(ach_file["id"],
                                 [entry_payload("DEBIT", 6_000_000, "l-1")])
    case = open_manual_risk_case(org["id"])
    resolve_case_ok(case["id"], "WATCH")
    return org, appended


class TestStateBeatsFiscalOnEntriesAppend:
    def test_dual_violation_returns_state_error(self, api):
        """PRD 2.6: "Requests are validated in a fixed, ordered pipeline, and
        the order is observable: when several checks would fail, the earliest
        category's error is the one returned."
        PRD 3.3: "The file must still be `WAREHOUSED`, otherwise
        `ERR_FILE_NOT_WAREHOUSED`; the originator must still be `ACTIVE`,
        otherwise `ERR_ORIGINATOR_NOT_ACTIVE`; and the caller must own the file,
        otherwise `ERR_RESOURCE_OWNERSHIP`."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_entries_append
        """
        org, ach_file = _setup_watch_org_at_limit()
        assert read_originator(org["id"])["status"] == "WATCH"

        # 6000000 outstanding + 4000001 incoming > 10000000 also holds, but the
        # state check (pipeline step 6) precedes the fiscal check (step 11).
        res = api.append_entries(
            ach_file["id"],
            append_entries_payload(ach_file["version"],
                                   [entry_payload("DEBIT", 4_000_001, "l-2")]),
            make_originator_headers(org["id"]))
        validate_error(res, ApiErrorId.ERR_ORIGINATOR_NOT_ACTIVE,
                       expected_status=409)

    def test_rejected_append_is_atomic(self, api):
        """PRD 3.3: "The append is atomic: if any entry is rejected, no entry
        from the batch is persisted."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_entries_append
        """
        org, ach_file = _setup_watch_org_at_limit()

        res = api.append_entries(
            ach_file["id"],
            append_entries_payload(ach_file["version"],
                                   [entry_payload("DEBIT", 4_000_001, "l-2")]),
            make_originator_headers(org["id"]))
        validate_error(res, ApiErrorId.ERR_ORIGINATOR_NOT_ACTIVE,
                       expected_status=409)

        assert read_file(ach_file["id"])["entry_count"] == 1
        assert read_originator(org["id"])["outstanding_exposure_debit_cents"] \
            == 6_000_000


def _same_day_file():
    """SAME_DAY_1 + NEXT_DAY windows; originator with a wide limit; a file
    requesting SAME_DAY_1 effective 2026-08-03, created while SAME_DAY_1 is
    still open (10:00 < 12:00 close)."""
    define_same_day_1_window()
    define_next_day_window()
    org = create_active_originator("Nu LLC", ["CCD"],
                                   exposure_limit_cents=1_000_000_000)
    set_clock("2026-08-03T10:00:00Z")
    ach_file = create_warehoused_file(org, "CCD", "SAME_DAY_1", "2026-08-03")
    return org, ach_file


class TestSameDayCapBoundary:
    def test_exactly_one_million_eligible(self, api):
        """PRD 3.3: "If the file's `requested_window_kind` is one of the
        same-day kinds and any incoming entry's `amount_cents` exceeds
        $1,000,000.00, the append is rejected with `ERR_SAME_DAY_INELIGIBLE` —
        an entry of exactly $1,000,000.00 is eligible."

        Design: Difficulty/boundary_precision_check/same_day_cap_exactly_one_million
        """
        org, ach_file = _same_day_file()
        appended = append_entries_ok(
            ach_file["id"], [entry_payload("DEBIT", 100_000_000, "n-1")])
        assert appended["entry_count"] == 1
        assert appended["total_amount_cents"] == 100_000_000

    def test_one_cent_over_one_million_rejected(self, api):
        """PRD 3.3: "If the file's `requested_window_kind` is one of the
        same-day kinds and any incoming entry's `amount_cents` exceeds
        $1,000,000.00, the append is rejected with `ERR_SAME_DAY_INELIGIBLE` —
        an entry of exactly $1,000,000.00 is eligible."

        Design: Difficulty/boundary_precision_check/same_day_cap_exactly_one_million
        """
        org, ach_file = _same_day_file()
        appended = append_entries_ok(
            ach_file["id"], [entry_payload("DEBIT", 100_000_000, "n-1")])

        res = api.append_entries(
            ach_file["id"],
            append_entries_payload(appended["version"],
                                   [entry_payload("DEBIT", 100_000_001, "n-2")]),
            make_originator_headers(org["id"]))
        validate_error(res, ApiErrorId.ERR_SAME_DAY_INELIGIBLE,
                       expected_status=422)

        # The failed append is atomic: only the boundary-eligible entry persists.
        assert read_file(ach_file["id"])["entry_count"] == 1
