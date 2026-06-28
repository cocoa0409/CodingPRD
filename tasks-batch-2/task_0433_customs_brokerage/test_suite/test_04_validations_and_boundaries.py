"""Validation rules, precedence ordering, numeric/empty-set boundaries, cross-entity
state dependencies, and resource temporal overlap (exam slots, statement periods).
"""
import test_helpers as h


# ---------------------------------------------------------------------------
# Queue A — priority_pair_validation_conflict
# ---------------------------------------------------------------------------
def test_segregation_beats_pga_not_cleared_on_review(api):
    """PRD §2.8: "The target resource's state for the requested transition is checked fifth, yielding `ERR_INVALID_STATE`. Segregation of duties is checked sixth. Beyond these, the remaining business, fiscal, and temporal rules described throughout §3 are applied".
    PRD §3.5: "if the officer's `X-User-ID` equals the entry's `filed_by_user_id`, the request is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    An officer who is also the filer attempts RELEASE while a PGAReview is still
    PENDING. Segregation (checked sixth) preempts the PGA-not-cleared business
    rule, so ERR_SEGREGATION_OF_DUTIES is returned.

    Design: Difficulty/priority_pair_validation_conflict/segregation_beats_pga_not_cleared_on_review
    """
    dual = h.make_broker_headers("broker-dual")
    base = h.setup_base(api, broker_user_id="broker-dual")
    entry, _ = h.create_draft_entry_with_lines(
        api, base,
        [{"hts_code": "2106909998", "customs_value_cents": 200_000,
          "quantity": 1, "pga_flag": "FDA"}],
        broker_headers=dual,
    )
    h.add_pga_review(api, entry["id"], "FDA", dual)
    h.file_entry(api, entry["id"], dual)
    dual_officer = h.make_officer_headers("broker-dual")
    h.validate_error(
        api.review_entry(entry["id"], "RELEASE", dual_officer),
        h.ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
    )


def test_pga_not_cleared_fires_when_segregation_satisfied(api):
    """PRD §3.5: "An entry may not be released while any review on it is `PENDING` or `HOLD`" ... "a release attempted in those circumstances is rejected with `ERR_PGA_NOT_CLEARED` (HTTP 409)."

    The companion to the segregation-preempts-PGA case: when the reviewing officer
    differs from the filer (segregation satisfied), the same still-PENDING PGAReview
    makes RELEASE fail with ERR_PGA_NOT_CLEARED — confirming the PGA rule is the one
    segregation preempted in the conflict case.

    Design: Difficulty/priority_pair_validation_conflict/segregation_beats_pga_not_cleared_on_review
    """
    ctx = h.setup_filed_entry_with_pending_pga(api)
    # Distinct officer -> no segregation failure; PGA is still PENDING.
    h.validate_error(
        api.review_entry(ctx["entry"]["id"], "RELEASE", h.OFFICER),
        h.ApiErrorId.ERR_PGA_NOT_CLEARED,
    )


def test_isf_not_filed_beats_bond_saturated_on_file(api):
    """PRD §2.8: "where two such rules could both fire on one request, the lower-numbered rule in the error catalogue's narrative ordering" ... "takes precedence."
    PRD §3.4: "the `isf_filing_id` must be set and the referenced ISF must be in `FILED` status, failing which the rejection is `ERR_ISF_NOT_FILED` (HTTP 409)".

    ERR_ISF_NOT_FILED (catalogue row 9) precedes ERR_BOND_SATURATED (row 15).
    Filing a second entry whose ISF is still DRAFT against an already-saturated
    bond returns ERR_ISF_NOT_FILED.

    Design: Difficulty/priority_pair_validation_conflict/isf_not_filed_beats_bond_saturated_on_file
    """
    base = h.setup_base(api, bond_limit_cents=54_800)
    # First entry saturates the bond.
    entry_a, _ = h.create_draft_entry_with_lines(api, base, [{}])
    h.file_entry(api, entry_a["id"], base["broker"])
    # Second entry uses a fresh DRAFT ISF (never filed).
    draft_isf = h.validate_success(
        api.create_isf(h.create_isf_payload(base["importer"]["id"]), base["broker"]),
        expected_status=201,
    )
    entry_b = h.validate_success(
        api.create_entry(
            h.create_entry_payload(
                base["importer"]["id"], base["bond"]["id"],
                isf_filing_id=draft_isf["id"],
            ),
            base["broker"],
        ),
        expected_status=201,
    )
    h.validate_success(
        api.create_line(entry_b["id"], h.create_line_payload(), base["broker"]),
        expected_status=201,
    )
    h.validate_error(
        api.file_entry(entry_b["id"], base["broker"]),
        h.ApiErrorId.ERR_ISF_NOT_FILED,
    )


# ---------------------------------------------------------------------------
# Queue A — boundary_precision_check
# ---------------------------------------------------------------------------
def test_bond_insufficient_strictly_above_limit_rejected(api):
    """PRD §3.4: "A filing that would drive the bond's `outstanding_liability_cents` strictly above its `limit_cents` is rejected outright with `ERR_BOND_INSUFFICIENT` (HTTP 422) — the filing fails rather than merely saturating the bond."

    A provisional total of 54800 against a bond with limit 54799 (one cent below)
    is rejected ERR_BOND_INSUFFICIENT; no liability is reserved.

    Design: Difficulty/boundary_precision_check/bond_insufficient_strictly_above_vs_saturate_at_equal
    """
    base = h.setup_base(api, bond_limit_cents=54_799)
    entry, _ = h.create_draft_entry_with_lines(api, base, [{}])
    h.validate_error(
        api.file_entry(entry["id"], base["broker"]),
        h.ApiErrorId.ERR_BOND_INSUFFICIENT,
    )
    bond = h.validate_success(api.get_bond(base["bond"]["id"], h.ADMIN))
    assert bond["outstanding_liability_cents"] == 0, bond


def test_bond_saturates_at_limit_equal_accepted(api):
    """PRD §3.4: "if that reconciliation brings the bond's outstanding liability up to or past its `limit_cents`, the bond auto-transitions from `ACTIVE` to `SATURATED`."

    The same provisional total of 54800 against a bond with limit 54800 is
    ACCEPTED (>= limit) and saturates the bond, pinning '>' (reject) versus '>='
    (accept-and-saturate).

    Design: Difficulty/boundary_precision_check/bond_insufficient_strictly_above_vs_saturate_at_equal
    """
    ctx = h.setup_filed_entry(api, bond_limit_cents=54_800)
    assert ctx["entry"]["provisional_total_cents"] == 54800, ctx["entry"]
    bond = h.validate_success(api.get_bond(ctx["base"]["bond"]["id"], h.ADMIN))
    assert bond["status"] == "SATURATED", bond
    assert bond["outstanding_liability_cents"] == 54800, bond


def test_file_with_zero_lines_rejected(api):
    """PRD §3.4: "it must carry at least one line, or the request is rejected with `ERR_NO_LINES` (HTTP 422)".

    Filing a DRAFT entry that has no lines is rejected ERR_NO_LINES.

    Design: Difficulty/boundary_precision_check/file_with_zero_lines_empty_set_rejected
    """
    base = h.setup_base(api)
    entry, _ = h.create_draft_entry_with_lines(api, base, [])
    h.validate_error(
        api.file_entry(entry["id"], base["broker"]), h.ApiErrorId.ERR_NO_LINES
    )


def test_file_with_one_line_passes_no_lines_guard(api):
    """PRD §3.4: "it must carry at least one line, or the request is rejected with `ERR_NO_LINES` (HTTP 422)".

    A DRAFT entry carrying exactly one line clears the at-least-one-line guard and
    files successfully (the X+1 side of the empty-set boundary).

    Design: Difficulty/boundary_precision_check/file_with_zero_lines_empty_set_rejected
    """
    base = h.setup_base(api)
    entry, _ = h.create_draft_entry_with_lines(api, base, [{}])
    filed = h.validate_success(api.file_entry(entry["id"], base["broker"]))
    assert filed["status"] == "FILED", filed


# ---------------------------------------------------------------------------
# Queue A — cross_entity_state_dependency
# ---------------------------------------------------------------------------
def test_entry_release_blocked_by_pga_hold(api):
    """PRD §3.5: "An entry may not be released while any review on it is `PENDING` or `HOLD`, and never if any is `REFUSED`; a release attempted in those circumstances is rejected with `ERR_PGA_NOT_CLEARED` (HTTP 409)."

    With its only PGAReview in HOLD, a FILED entry's RELEASE is rejected
    ERR_PGA_NOT_CLEARED and the entry stays FILED.

    Design: Difficulty/cross_entity_state_dependency/entry_release_blocked_by_pga_review_state
    """
    ctx = h.setup_filed_entry_with_pending_pga(api)
    h.decide_pga(api, ctx["pga"]["id"], "HOLD", h.OFFICER)
    h.validate_error(
        api.review_entry(ctx["entry"]["id"], "RELEASE", h.OFFICER),
        h.ApiErrorId.ERR_PGA_NOT_CLEARED,
    )
    refreshed = h.validate_success(api.get_entry(ctx["entry"]["id"], h.OFFICER))
    assert refreshed["status"] == "FILED", refreshed


def test_entry_release_allowed_once_pga_may_proceed(api):
    """PRD §3.5: "only when every partner-government-agency review on the entry has a `decision` of `MAY_PROCEED` and the referenced ISF is in `FILED` status."
    PRD §3.5: "An entry may not be released while any review on it is `PENDING` or `HOLD`, and never if any is `REFUSED`".

    The release block is keyed to PGA state: once the entry's only PGAReview is
    upgraded HOLD -> MAY_PROCEED, the RELEASE that was rejected ERR_PGA_NOT_CLEARED
    now succeeds.

    Design: Difficulty/cross_entity_state_dependency/entry_release_blocked_by_pga_review_state
    """
    ctx = h.setup_filed_entry_with_pending_pga(api)
    h.decide_pga(api, ctx["pga"]["id"], "HOLD", h.OFFICER)
    h.validate_error(
        api.review_entry(ctx["entry"]["id"], "RELEASE", h.OFFICER),
        h.ApiErrorId.ERR_PGA_NOT_CLEARED,
    )
    h.decide_pga(api, ctx["pga"]["id"], "MAY_PROCEED", h.OFFICER)
    released = h.review_entry(api, ctx["entry"]["id"], "RELEASE", h.OFFICER)
    assert released["status"] == "RELEASED", released


def test_statement_settle_allowed_once_entry_liquidated(api):
    """PRD §3.8: "Settlement is permitted only while the statement is `OPEN` and only when every entry whose `statement_id` equals this statement has reached `LIQUIDATED` status" ... "A statement therefore settles only after all of its entries have liquidated."

    The settle block is keyed to entry liquidation: the same statement that
    rejected settle while its entry was RELEASED settles once the entry liquidates.

    Design: Difficulty/cross_entity_state_dependency/statement_settle_blocked_until_all_entries_liquidated
    """
    ctx = h.setup_released_entry(api)
    stmt_id = ctx["entry"]["statement_id"]
    h.validate_error(
        api.settle_statement(stmt_id, h.ADMIN), h.ApiErrorId.ERR_INVALID_STATE
    )
    h.liquidate_entry(api, ctx["entry"]["id"], h.OFFICER)
    settled = h.validate_success(api.settle_statement(stmt_id, h.ADMIN))
    assert settled["status"] == "SETTLED", settled


def test_statement_settle_blocked_while_entry_released(api):
    """PRD §3.8: "Settlement is permitted only while the statement is `OPEN` and only when every entry whose `statement_id` equals this statement has reached `LIQUIDATED` status".

    A statement whose single scheduled entry is still RELEASED (not liquidated)
    cannot settle; the attempt is rejected ERR_INVALID_STATE and the statement
    stays OPEN.

    Design: Difficulty/cross_entity_state_dependency/statement_settle_blocked_until_all_entries_liquidated
    """
    ctx = h.setup_released_entry(api)
    stmt_id = ctx["entry"]["statement_id"]
    h.validate_error(
        api.settle_statement(stmt_id, h.ADMIN), h.ApiErrorId.ERR_INVALID_STATE
    )
    stmt = h.validate_success(api.get_statement(stmt_id, h.ADMIN))
    assert stmt["status"] == "OPEN", stmt


# ---------------------------------------------------------------------------
# Queue A — resource_temporal_overlap
# ---------------------------------------------------------------------------
def test_exam_slot_overlap_same_station_rejected(api):
    """PRD §3.7: "two slots overlap exactly when the first's `window_start` is strictly before the second's `window_end` and the second's `window_start` is strictly before the first's `window_end`" ... "An overlapping booking on the same station is rejected with `ERR_EXAM_SLOT_OVERLAP` (HTTP 409)."

    A BOOKED CES_LAX slot [10:00,12:00) blocks a new CES_LAX [11:00,13:00) overlap.

    Design: Difficulty/resource_temporal_overlap/exam_slot_half_open_overlap_same_station_rejected
    """
    ctx = h.setup_hold_exam_entry(api)
    h.book_exam_slot(
        api, ctx["entry"]["id"], h.OFFICER,
        window_start="2026-06-06T10:00:00Z", window_end="2026-06-06T12:00:00Z",
    )
    h.validate_error(
        api.create_exam_slot(
            h.create_exam_slot_payload(
                ctx["entry"]["id"],
                window_start="2026-06-06T11:00:00Z",
                window_end="2026-06-06T13:00:00Z",
            ),
            h.OFFICER,
        ),
        h.ApiErrorId.ERR_EXAM_SLOT_OVERLAP,
    )


def test_exam_slot_back_to_back_adjacency_allowed(api):
    """PRD §3.7: "adjacency, where one slot's end equals the next slot's start,
    does not collide."

    A back-to-back CES_LAX slot [12:00,14:00) after a BOOKED [10:00,12:00) is
    accepted because adjacency does not overlap under half-open intervals.

    Design: Difficulty/resource_temporal_overlap/exam_slot_half_open_overlap_same_station_rejected
    """
    ctx = h.setup_hold_exam_entry(api)
    h.book_exam_slot(
        api, ctx["entry"]["id"], h.OFFICER,
        window_start="2026-06-06T10:00:00Z", window_end="2026-06-06T12:00:00Z",
    )
    adjacent = h.validate_success(
        api.create_exam_slot(
            h.create_exam_slot_payload(
                ctx["entry"]["id"],
                window_start="2026-06-06T12:00:00Z",
                window_end="2026-06-06T14:00:00Z",
            ),
            h.OFFICER,
        ),
        expected_status=201,
    )
    assert adjacent["status"] == "BOOKED", adjacent


def test_statement_calendar_month_overlap_rejected(api):
    """PRD §3.8: "creating a statement whose `period_month` names a calendar month that overlaps an existing open statement for the same importer — in practice, a second open statement for the same importer and month — is rejected with `ERR_STATEMENT_PERIOD_OVERLAP` (HTTP 409)."

    A second OPEN 2026-06 statement for the same importer is rejected.

    Design: Difficulty/resource_temporal_overlap/statement_calendar_month_overlap_rejected
    """
    importer = h.create_importer(api)
    h.validate_success(
        api.create_statement(
            h.create_statement_payload(importer["id"], period_month="2026-06"), h.ADMIN
        ),
        expected_status=201,
    )
    h.validate_error(
        api.create_statement(
            h.create_statement_payload(importer["id"], period_month="2026-06"), h.ADMIN
        ),
        h.ApiErrorId.ERR_STATEMENT_PERIOD_OVERLAP,
    )


def test_distinct_month_statement_allowed(api):
    """PRD §3.8: "creating a statement whose `period_month` names a calendar month that overlaps an existing open statement for the same importer" ... "is rejected with `ERR_STATEMENT_PERIOD_OVERLAP` (HTTP 409)."

    A statement for a different calendar month (2026-07) for the same importer
    does not collide with an existing 2026-06 statement and is accepted.

    Design: Difficulty/resource_temporal_overlap/statement_calendar_month_overlap_rejected
    """
    importer = h.create_importer(api)
    h.validate_success(
        api.create_statement(
            h.create_statement_payload(importer["id"], period_month="2026-06"), h.ADMIN
        ),
        expected_status=201,
    )
    other = h.validate_success(
        api.create_statement(
            h.create_statement_payload(importer["id"], period_month="2026-07"), h.ADMIN
        ),
        expected_status=201,
    )
    assert other["status"] == "OPEN", other


# ---------------------------------------------------------------------------
# Queue B — validations section
# ---------------------------------------------------------------------------
def test_duplicate_ior_number_rejected(api):
    """PRD §3.1: "Attempting to reuse an `ior_number` already held by another importer is rejected with `ERR_DUPLICATE` (HTTP 409)."

    A second importer with an already-used ior_number is rejected ERR_DUPLICATE.

    Design: Corner/validations/duplicate_ior_number_rejected
    """
    h.validate_success(
        api.create_importer(
            h.create_importer_payload(ior_number="IOR-DUP-001"), h.ADMIN
        ),
        expected_status=201,
    )
    h.validate_error(
        api.create_importer(
            h.create_importer_payload(ior_number="IOR-DUP-001",
                                      owner_user_id="imp-user-2"),
            h.ADMIN,
        ),
        h.ApiErrorId.ERR_DUPLICATE,
    )


def test_duplicate_bill_of_lading_rejected(api):
    """PRD §3.2: "The `bill_of_lading` must be unique across all ISF filings; a duplicate is rejected with `ERR_DUPLICATE` (HTTP 409)."

    A second ISF with an already-used bill_of_lading is rejected ERR_DUPLICATE.

    Design: Corner/validations/duplicate_bill_of_lading_rejected
    """
    importer = h.create_importer(api)
    h.validate_success(
        api.create_isf(
            h.create_isf_payload(importer["id"], bill_of_lading="BOL-DUP-001"),
            h.BROKER,
        ),
        expected_status=201,
    )
    h.validate_error(
        api.create_isf(
            h.create_isf_payload(importer["id"], bill_of_lading="BOL-DUP-001",
                                 vessel_eta="2026-06-11T00:00:00Z"),
            h.BROKER,
        ),
        h.ApiErrorId.ERR_DUPLICATE,
    )


def test_bond_importer_mismatch_on_entry_create_rejected(api):
    """PRD §3.4: "The bond securing the entry must belong to the same importer as the entry — its `importer_id` must equal the entry's `importer_id` — or the filing is rejected with `ERR_BOND_IMPORTER_MISMATCH` (HTTP 422)."

    PRD §3.4 places this guard "specifically at filing": an entry whose bond_id
    belongs to a different importer than the entry's importer_id is accepted at
    draft (the FK merely has to resolve) but is rejected ERR_BOND_IMPORTER_MISMATCH
    when filed.

    Design: Corner/validations/bond_importer_mismatch_on_entry_create_rejected
    """
    imp_a = h.create_importer(api, ior_number="IOR-MM-A")
    bond_a = h.create_active_bond(api, imp_a["id"])
    imp_b = h.create_importer(api, ior_number="IOR-MM-B", owner_user_id="imp-user-b")
    isf_b = h.create_filed_isf(api, imp_b["id"], broker_headers=h.BROKER)
    # Draft entry for importer B but secured by importer A's bond.
    entry = h.validate_success(
        api.create_entry(
            h.create_entry_payload(
                imp_b["id"], bond_a["id"], isf_filing_id=isf_b["id"]
            ),
            h.BROKER,
        ),
        expected_status=201,
    )
    h.validate_success(
        api.create_line(entry["id"], h.create_line_payload(), h.BROKER),
        expected_status=201,
    )
    h.validate_error(
        api.file_entry(entry["id"], h.BROKER),
        h.ApiErrorId.ERR_BOND_IMPORTER_MISMATCH,
    )


def test_entry_date_precedes_manifest_cutoff_rejected(api):
    """PRD §3.4: "the entry's `entry_date` must not be earlier than the referenced ISF's `vessel_eta` minus 24 hours; an entry date that precedes that manifest cutoff is rejected with `ERR_ENTRY_PRECEDES_MANIFEST` (HTTP 422)."

    Filing an entry whose entry_date 2026-06-08T00:00:00Z precedes the cutoff
    2026-06-09T00:00:00Z (vessel_eta 2026-06-10T00:00:00Z minus 24h) is rejected.

    Design: Corner/validations/entry_date_precedes_manifest_cutoff_rejected
    """
    base = h.setup_base(api)
    entry, _ = h.create_draft_entry_with_lines(
        api, base, [{}], entry_date="2026-06-08T00:00:00Z"
    )
    h.validate_error(
        api.file_entry(entry["id"], base["broker"]),
        h.ApiErrorId.ERR_ENTRY_PRECEDES_MANIFEST,
    )


def test_invalid_exam_window_end_not_after_start_rejected(api):
    """PRD §3.7: "The `window_end` must be strictly after the `window_start`" ... "a slot booked for an entry not in `HOLD_EXAM`, or with a `window_end` that is not strictly after its `window_start`, is rejected with `ERR_INVALID_EXAM_WINDOW` (HTTP 422)."

    A slot whose window_end equals window_start is rejected ERR_INVALID_EXAM_WINDOW.

    Design: Corner/validations/invalid_exam_window_end_not_after_start_rejected
    """
    ctx = h.setup_hold_exam_entry(api)
    h.validate_error(
        api.create_exam_slot(
            h.create_exam_slot_payload(
                ctx["entry"]["id"],
                window_start="2026-06-06T10:00:00Z",
                window_end="2026-06-06T10:00:00Z",
            ),
            h.OFFICER,
        ),
        h.ApiErrorId.ERR_INVALID_EXAM_WINDOW,
    )


def test_exam_slot_for_non_hold_exam_entry_rejected(api):
    """PRD §3.7: "the `entry_id` being examined, which must be in `HOLD_EXAM` status" ... "a slot booked for an entry not in `HOLD_EXAM`" ... "is rejected with `ERR_INVALID_EXAM_WINDOW` (HTTP 422)."

    Booking an exam slot for a FILED (not HOLD_EXAM) entry is rejected
    ERR_INVALID_EXAM_WINDOW.

    Design: Corner/validations/exam_slot_for_non_hold_exam_entry_rejected
    """
    ctx = h.setup_filed_entry(api)
    h.validate_error(
        api.create_exam_slot(
            h.create_exam_slot_payload(ctx["entry"]["id"]), h.OFFICER
        ),
        h.ApiErrorId.ERR_INVALID_EXAM_WINDOW,
    )


def test_importer_user_acting_on_unowned_importer_rejected(api):
    """PRD §2.1: "An `ImporterUser` may draft ISF filings, entries, and lines and submit post-summary corrections only for an importer whose `owner_user_id` equals its `X-User-ID`; acting against any other importer is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    An ImporterUser whose X-User-ID is owner-B filing an ISF for an importer owned
    by owner-A is rejected ERR_NOT_RESOURCE_OWNER.

    Design: Corner/validations/importer_user_acting_on_unowned_importer_rejected
    """
    importer = h.create_importer(api, owner_user_id="owner-A", ior_number="IOR-OWN-A")
    other_user = h.make_importer_user_headers("owner-B")
    h.validate_error(
        api.create_isf(h.create_isf_payload(importer["id"]), other_user),
        h.ApiErrorId.ERR_NOT_RESOURCE_OWNER,
    )
