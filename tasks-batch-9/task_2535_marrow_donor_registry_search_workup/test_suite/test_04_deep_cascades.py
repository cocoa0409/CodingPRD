"""Deep transitive cascades: one write, many rows away.

Two triggers are exercised here, each of which reaches far past the row the
caller addressed:

* a failing `IDM_PANEL` clearance result, which walks item -> case -> donor
  calendar -> candidate -> claim/patient money -> search bench, and
* an `ABORT` of a *started* conditioning regimen, which walks patient ->
  confirmed booking -> centre capacity and donor calendar -> case -> claim and
  patient money -> candidate -> search, and deliberately leaves the backup
  bench alone because an ablated recipient cannot be re-matched.

Every assertion below is a consequence the PRD spells out for the trigger; the
counters are checked before as well as after, because §1 requires a cascade to
return the derived counters to exactly the value they held before.
"""
from test_helpers import (
    ApiErrorId,
    assertions as A,
    constants as C,
    factories as f,
    fixtures,
    validate_error_is_one_of,
    validate_success,
)

# The clearance work is resulted at the canonical clearance instant, whose UTC
# date anchors the derived 90-day deferral.
CLEARANCE_DATE = "2026-09-11"
DEFERRAL_UNTIL = "2026-12-10"
DEFERRAL_DAY_COUNT = 91

ABORT_REASON = "Recipient developed refractory sepsis; transplant stood down"


def _workup_open_with_one_backup():
    """Rank-1 primary in an open workup with a passed physical, rank-2 on the bench.

    The context also carries `cost_before_workup`, the patient's committed cost as
    it stood before the workup case (and therefore its provisional claim) existed.
    """
    ctx = fixtures.setup_primary_candidate(num_donors=2)
    fixtures.engage_candidate(ctx)
    ctx["cost_before_workup"] = fixtures.read_patient(
        ctx["patient_id"], ctx["coordinator_headers"]
    )["committed_cost_cents"]
    fixtures.advance_to_workup_open(ctx)
    fixtures.set_clock(C.TIMELINE["CLEARANCE_AT"])
    fixtures.result_clearance_item(ctx, "PHYSICAL_EXAM", "PASS")
    return ctx


def _fail_the_idm_panel(api, ctx):
    """Record the failing infectious-disease panel that fires the whole cascade."""
    return validate_success(
        api.record_clearance_result(
            ctx["clearance"]["IDM_PANEL"]["id"],
            f.clearance_result_payload(
                result="FAIL",
                note="Reactive infectious-disease marker on the confirmatory panel",
            ),
            ctx["physician_headers"],
        )
    )


def test_failing_idm_panel_freezes_clearance_aborts_the_case_and_defers_the_donor(api):
    """PRD §3.6: "Any failing result moves the dimension to `FAILED` — `PENDING → FAILED` when the failure is the very first result recorded, and `IN_PROGRESS → FAILED` when it follows an earlier pass — and once the dimension is `FAILED` the remaining items keep `result` `PENDING` forever and are never resultable again."
    PRD §3.6: "A passing `IDM_PANEL` sets that item's `expires_at` to its `resulted_at` plus thirty days — infectious-disease results are considered valid for one month and no longer — and surfaces the same instant as the case's `idm_resulted_at`, which stays null unless the panel actually passed."
    PRD §3.6: "The case moves `case_status` `OPEN → ABORTED` with `clearance_status` `FAILED` and `abort_reason` recorded."
    PRD §3.6: "When the failure was on the `PHYSICAL_EXAM` or `IDM_PANEL` item, the donor is also moved `AVAILABLE → TEMPORARILY_DEFERRED`: no client-supplied deferral date is accepted on this path, and `deferral_until` is instead derived as the current logical UTC date plus 90 days, with an `ACTIVE` `DEFERRAL` calendar window created over that same span, raising the donor's `blocked_day_count`."
    PRD §3.2: "Otherwise the server computes `day_count` as the number of calendar days in the closed interval — the difference between the two dates plus one, so a window whose two dates are equal has a day count of one — and adds that count to the donor's `blocked_day_count`."
    PRD §2.10: "`DonorProfile.blocked_day_count` is the sum of `day_count` over that donor's calendar windows whose `status` is `ACTIVE`."
    PRD §3.6: "The candidate moves `WORKUP_OPEN → DEFERRED`."

    Design: Difficulty/transitive_cascade/idm_panel_failure_cascades_five_levels_to_backup_promotion
    """
    ctx = _workup_open_with_one_backup()
    in_progress = fixtures.read_workup_case(ctx["workup_case_id"], ctx["coordinator_headers"])
    assert in_progress["clearance_status"] == "IN_PROGRESS", (
        f"the passing physical must move the clearance dimension off PENDING before "
        f"the failure lands on it, got {in_progress['clearance_status']}"
    )
    donor_id = fixtures.candidate_by_rank(ctx, 1)["donor_id"]

    failed = _fail_the_idm_panel(api, ctx)

    # Level 1 — the item itself.
    assert failed["result"] == "FAIL", failed["result"]
    A.assert_same_instant(
        failed["resulted_at"], C.TIMELINE["CLEARANCE_AT"],
        "resulted_at is stamped from the logical clock",
    )
    assert failed["expires_at"] is None, (
        f"only a passing IDM_PANEL earns a thirty-day expiry, got "
        f"{failed['expires_at']!r}"
    )
    items = fixtures.find_clearance_items(ctx["workup_case_id"], ctx["physician_headers"])
    assert items["CONSENT"]["result"] == "PENDING", (
        f"once the dimension is FAILED the remaining items keep result PENDING "
        f"forever, got {items['CONSENT']['result']}"
    )
    validate_error_is_one_of(
        api.record_clearance_result(
            items["CONSENT"]["id"],
            f.clearance_result_payload(result="PASS"),
            ctx["physician_headers"],
        ),
        [
            ApiErrorId.ERR_WORKUP_CASE_NOT_OPEN.value,
            ApiErrorId.ERR_CLEARANCE_ORDER_VIOLATION.value,
        ],
    )

    # Level 2 — the parent case, on both of its dimensions.
    case = fixtures.read_workup_case(ctx["workup_case_id"], ctx["coordinator_headers"])
    assert case["clearance_status"] == "FAILED", case["clearance_status"]
    assert case["case_status"] == "ABORTED", (
        f"a failing clearance item aborts the case outright, got {case['case_status']}"
    )
    assert isinstance(case["abort_reason"], str) and case["abort_reason"], (
        f"the case's abort_reason must be recorded, got {case['abort_reason']!r}"
    )
    assert case["idm_resulted_at"] is None, (
        f"idm_resulted_at stays null unless the panel actually passed, got "
        f"{case['idm_resulted_at']!r}"
    )

    # Level 3 — the volunteer's availability and calendar.
    donor = fixtures.read_donor(donor_id, ctx["liaison_headers"])
    assert donor["availability_status"] == "TEMPORARILY_DEFERRED", (
        f"a failed IDM panel defers the volunteer, got {donor['availability_status']}"
    )
    assert donor["deferral_until"] == DEFERRAL_UNTIL, (
        f"deferral_until is derived as the current logical UTC date "
        f"({CLEARANCE_DATE}) plus 90 days, expected {DEFERRAL_UNTIL}, got "
        f"{donor['deferral_until']!r}"
    )
    windows = fixtures.find_windows(donor_id, ctx["liaison_headers"])
    assert len(windows) == 1, (
        f"exactly one calendar window is created by the deferral, got {windows!r}"
    )
    window = windows[0]
    assert window["reason"] == "DEFERRAL", window["reason"]
    assert window["status"] == "ACTIVE", window["status"]
    assert window["date_from"] == CLEARANCE_DATE, window["date_from"]
    assert window["date_to"] == DEFERRAL_UNTIL, window["date_to"]
    assert window["day_count"] == DEFERRAL_DAY_COUNT, (
        f"the closed interval {CLEARANCE_DATE}..{DEFERRAL_UNTIL} spans "
        f"{DEFERRAL_DAY_COUNT} days, got {window['day_count']}"
    )
    assert donor["blocked_day_count"] == DEFERRAL_DAY_COUNT, (
        f"blocked_day_count sums the day_count of the donor's ACTIVE windows, "
        f"expected {DEFERRAL_DAY_COUNT}, got {donor['blocked_day_count']}"
    )

    # Level 4 — the candidate row that named the donor.
    candidate = fixtures.read_candidate(ctx["candidate_id"], ctx["coordinator_headers"])
    assert candidate["status"] == "DEFERRED", (
        f"the candidate moves WORKUP_OPEN -> DEFERRED, got {candidate['status']}"
    )


def test_failing_idm_panel_voids_the_claim_refunds_the_patient_and_promotes_the_backup(api):
    """PRD §3.6: "A provisional reimbursement claim is created in the same breath, raising the patient's `committed_cost_cents` by its total."
    PRD §3.6: "The case's provisional reimbursement claim moves `PROVISIONAL → VOID` with its `void_reason` recorded, and the patient's `committed_cost_cents` drops back by that claim's `total_usd_cents`, returning to exactly the value it held before the workup was opened."
    PRD §2.10: "`Patient.committed_cost_cents` is the sum of `total_usd_cents` over that patient's claims whose `status` is `PROVISIONAL` or `FINALIZED`."
    PRD §3.5: "Of the promotable ones, the candidate holding the smallest `rank_position` is lifted to `candidate_role` `PRIMARY`, and its `promoted_from_rank` records the `rank_position` it held when it was promoted."
    PRD §3.5: "The outgoing primary's `candidate_role` becomes `ARCHIVED_POOL`."
    PRD §3.5: "The search's `backup_candidate_count` therefore falls by one."
    PRD §3.6: "The promotion cascade runs, and the search moves `WORKUP_ACTIVE → BACKUP_REQUIRED`."

    Design: Difficulty/transitive_cascade/idm_panel_failure_cascades_five_levels_to_backup_promotion
    """
    ctx = _workup_open_with_one_backup()
    claim = fixtures.read_claim(ctx["claim_id"])
    assert claim["status"] == "PROVISIONAL", claim["status"]
    committed = claim["total_usd_cents"]
    patient_before = fixtures.read_patient(ctx["patient_id"], ctx["coordinator_headers"])
    assert patient_before["committed_cost_cents"] == ctx["cost_before_workup"] + committed, (
        f"opening the workup must raise committed_cost_cents by the provisional "
        f"claim's total ({committed}), got {patient_before['committed_cost_cents']} "
        f"against a pre-workup {ctx['cost_before_workup']}"
    )
    search_before = fixtures.read_search(ctx["search_id"], ctx["coordinator_headers"])
    assert search_before["status"] == "WORKUP_ACTIVE", search_before["status"]
    assert search_before["backup_candidate_count"] == 1, (
        f"the rank-2 candidate is the search's only backup, got "
        f"{search_before['backup_candidate_count']}"
    )
    backup = fixtures.candidate_by_rank(ctx, 2)
    assert backup["candidate_role"] == "BACKUP", backup["candidate_role"]
    assert backup["promoted_from_rank"] is None, backup["promoted_from_rank"]

    _fail_the_idm_panel(api, ctx)

    # Level 5a — the money.
    voided = fixtures.read_claim(ctx["claim_id"])
    assert voided["status"] == "VOID", (
        f"the case's provisional claim moves PROVISIONAL -> VOID, got {voided['status']}"
    )
    assert isinstance(voided["void_reason"], str) and voided["void_reason"], (
        f"the claim's void_reason must be recorded, got {voided['void_reason']!r}"
    )
    assert voided["total_usd_cents"] == committed, (
        f"voiding must not rewrite the claim's arithmetic, expected {committed}, got "
        f"{voided['total_usd_cents']}"
    )
    patient_after = fixtures.read_patient(ctx["patient_id"], ctx["coordinator_headers"])
    assert patient_after["committed_cost_cents"] == ctx["cost_before_workup"], (
        f"committed_cost_cents must return to exactly the value it held before the "
        f"workup was opened ({ctx['cost_before_workup']}), got "
        f"{patient_after['committed_cost_cents']}"
    )

    # Level 5b — the search bench.
    promoted = fixtures.read_candidate(backup["id"], ctx["coordinator_headers"])
    assert promoted["candidate_role"] == "PRIMARY", (
        f"the promotable backup is lifted to PRIMARY by the cascade, got "
        f"{promoted['candidate_role']}"
    )
    assert promoted["promoted_from_rank"] == 2, (
        f"promoted_from_rank records the rank_position held at promotion, got "
        f"{promoted['promoted_from_rank']!r}"
    )
    assert promoted["status"] == "IDENTIFIED", (
        f"promotion never touches the candidate's own workflow status, got "
        f"{promoted['status']}"
    )
    outgoing = fixtures.read_candidate(ctx["candidate_id"], ctx["coordinator_headers"])
    assert outgoing["candidate_role"] == "ARCHIVED_POOL", (
        f"the outgoing primary's role becomes ARCHIVED_POOL, got "
        f"{outgoing['candidate_role']}"
    )
    search_after = fixtures.read_search(ctx["search_id"], ctx["coordinator_headers"])
    assert search_after["status"] == "BACKUP_REQUIRED", (
        f"the search moves WORKUP_ACTIVE -> BACKUP_REQUIRED, got "
        f"{search_after['status']}"
    )
    assert search_after["backup_candidate_count"] == 0, (
        f"backup_candidate_count falls by one when the bench's only backup is "
        f"promoted, got {search_after['backup_candidate_count']}"
    )

    # The promoted volunteer is untouched by the failed donor's deferral.
    second_donor = fixtures.read_donor(promoted["donor_id"], ctx["liaison_headers"])
    assert second_donor["availability_status"] == "AVAILABLE", (
        f"the cascade defers only the failed volunteer, got "
        f"{second_donor['availability_status']}"
    )
    assert second_donor["blocked_day_count"] == 0, (
        f"no calendar window is written for the promoted volunteer, got "
        f"{second_donor['blocked_day_count']}"
    )


def _conditioning_started_with_one_backup():
    """A started regimen over a confirmed booking, with a rank-2 BACKUP still on the bench."""
    ctx = fixtures.setup_pipeline("booking_confirmed", num_donors=2)
    fixtures.advance_to_conditioning_started(ctx)
    return ctx


def _abort_the_regimen(api, ctx, expected_patient_version):
    """Abort the started conditioning regimen, quoting the patient's current version."""
    return validate_success(
        api.drive_conditioning(
            ctx["patient_id"],
            f.conditioning_payload(
                "ABORT", expected_patient_version, reason=ABORT_REASON
            ),
            ctx["coordinator_headers"],
        )
    )


def test_aborting_a_started_regimen_cancels_the_confirmed_booking_and_frees_capacity(api):
    """PRD §3.8: "Every booking of the patient's `OPEN` workup case in `HELD` or `CONFIRMED` status becomes `CANCELLED` with `cancel_reason` `CONDITIONING_ABORTED`, each releasing its minutes from its centre's `committed_slot_minutes`; bookings already in a terminal status keep whatever `cancel_reason` they already carried and are not rewritten."
    PRD §3.8: "Every `COLLECTION_WINDOW` calendar window sourced by those bookings becomes `RELEASED`, restoring the donor's `blocked_day_count`."
    PRD §2.10: "`CollectionCenter.committed_slot_minutes` is the sum of `duration_minutes` over that centre's bookings whose `status` is `HELD`, `CONFIRMED` or `COMPLETED`."
    PRD §2.10: "`DonorProfile.blocked_day_count` is the sum of `day_count` over that donor's calendar windows whose `status` is `ACTIVE`."

    Design: Difficulty/transitive_cascade/conditioning_abort_after_start_cascades_three_levels_and_stalls_search
    """
    ctx = _conditioning_started_with_one_backup()
    donor_id = ctx["donors"][0]["id"]

    booking_before = fixtures.read_booking(ctx["booking_id"], ctx["center_ops_headers"])
    assert booking_before["status"] == "CONFIRMED", booking_before["status"]
    center_before = fixtures.read_center(ctx["center_id"], ctx["center_ops_headers"])
    assert center_before["committed_slot_minutes"] == booking_before["duration_minutes"], (
        f"the confirmed booking is the centre's only live commitment, expected "
        f"{booking_before['duration_minutes']} committed minutes, got "
        f"{center_before['committed_slot_minutes']}"
    )
    booking_windows = fixtures.find_booking_windows(ctx["booking_id"])
    assert len(booking_windows) == 1, (
        f"confirmation creates exactly one collection window for the booking, got "
        f"{booking_windows!r}"
    )
    collection_window = booking_windows[0]
    assert collection_window["reason"] == "COLLECTION_WINDOW", collection_window["reason"]
    assert collection_window["status"] == "ACTIVE", collection_window["status"]
    assert collection_window["source_booking_id"] == ctx["booking_id"], (
        f"the window must point back at the booking that generated it, got "
        f"{collection_window['source_booking_id']!r}"
    )
    donor_before = fixtures.read_donor(donor_id, ctx["liaison_headers"])
    assert donor_before["blocked_day_count"] == collection_window["day_count"], (
        f"the collection window is the donor's only ACTIVE window, expected "
        f"{collection_window['day_count']} blocked days, got "
        f"{donor_before['blocked_day_count']}"
    )
    patient_before = fixtures.read_patient(ctx["patient_id"], ctx["coordinator_headers"])

    _abort_the_regimen(api, ctx, patient_before["version"])

    booking_after = fixtures.read_booking(ctx["booking_id"], ctx["center_ops_headers"])
    assert booking_after["status"] == "CANCELLED", (
        f"the abort cancels the confirmed booking, got {booking_after['status']}"
    )
    assert booking_after["cancel_reason"] == "CONDITIONING_ABORTED", (
        f"the cascade writes cancel_reason CONDITIONING_ABORTED, got "
        f"{booking_after['cancel_reason']!r}"
    )
    center_after = fixtures.read_center(ctx["center_id"], ctx["center_ops_headers"])
    assert center_after["committed_slot_minutes"] == 0, (
        f"a CANCELLED booking no longer counts towards committed_slot_minutes, "
        f"expected 0, got {center_after['committed_slot_minutes']}"
    )
    released = fixtures.find_booking_windows(ctx["booking_id"])
    assert len(released) == 1, released
    assert released[0]["id"] == collection_window["id"]
    assert released[0]["status"] == "RELEASED", (
        f"the COLLECTION_WINDOW sourced by the cancelled booking becomes RELEASED, "
        f"got {released[0]['status']}"
    )
    donor_after = fixtures.read_donor(donor_id, ctx["liaison_headers"])
    assert donor_after["blocked_day_count"] == 0, (
        f"releasing the window must restore blocked_day_count to the value it held "
        f"before confirmation (0), got {donor_after['blocked_day_count']}"
    )
    assert donor_after["availability_status"] == "AVAILABLE", (
        f"the abort is the recipient's misfortune, not the volunteer's: nothing "
        f"defers the donor, got {donor_after['availability_status']}"
    )


def test_aborting_a_started_regimen_voids_the_claim_closes_the_candidate_and_stalls_the_search(api):
    """PRD §3.8: "Aborting is the widest cascade in the system, and it runs identically whether the abort comes from `SCHEDULED → ABORTED` or from `STARTED → ABORTED`."
    PRD §3.8: "The supplied reason is recorded as the patient's `conditioning_aborted_reason`."
    PRD §3.8: "Every successful action increments the patient's `version` by one."
    PRD §3.8: "The workup case moves `case_status` `OPEN → ABORTED` with `abort_reason` `CONDITIONING_ABORTED`, and its match candidate is moved to `CLOSED` from either `WORKUP_OPEN` or `COLLECTED`, whichever it held."
    PRD §3.8: "Every reimbursement claim of that case still in `PROVISIONAL` status becomes `VOID` with its `void_reason` recorded, restoring the patient's `committed_cost_cents` by the voided total."
    PRD §2.10: "`Patient.committed_cost_cents` is the sum of `total_usd_cents` over that patient's claims whose `status` is `PROVISIONAL` or `FINALIZED`."
    PRD §3.8: "And the search moves `WORKUP_ACTIVE → STALLED`."
    PRD §3.8: "From `STARTED` onward, an abort is recorded with `conditioning_aborted_reason` and the search is moved to `STALLED` rather than to `BACKUP_REQUIRED`, because a recipient whose marrow has already been ablated cannot simply be re-matched to a backup volunteer."
    PRD §2.10: "`SearchRequest.backup_candidate_count` is the count of that search's candidates whose `candidate_role` is `BACKUP` and whose `status` is one of `IDENTIFIED`, `TYPING_REQUESTED`, `TYPING_RESPONDED` or `SCREENING_PASSED`."

    Design: Difficulty/transitive_cascade/conditioning_abort_after_start_cascades_three_levels_and_stalls_search
    """
    ctx = _conditioning_started_with_one_backup()
    backup = fixtures.candidate_by_rank(ctx, 2)

    patient_before = fixtures.read_patient(ctx["patient_id"], ctx["coordinator_headers"])
    assert patient_before["conditioning_status"] == "STARTED", (
        f"the abort must be driven from STARTED, got "
        f"{patient_before['conditioning_status']}"
    )
    claim_before = fixtures.read_claim(ctx["claim_id"])
    assert claim_before["status"] == "PROVISIONAL", claim_before["status"]
    assert patient_before["committed_cost_cents"] == claim_before["total_usd_cents"], (
        f"the provisional claim is the patient's only live commitment, expected "
        f"{claim_before['total_usd_cents']}, got "
        f"{patient_before['committed_cost_cents']}"
    )
    search_before = fixtures.read_search(ctx["search_id"], ctx["coordinator_headers"])
    assert search_before["status"] == "WORKUP_ACTIVE", search_before["status"]
    assert search_before["backup_candidate_count"] == 1, (
        f"the rank-2 candidate is on the bench before the abort, got "
        f"{search_before['backup_candidate_count']}"
    )

    aborted = _abort_the_regimen(api, ctx, patient_before["version"])

    # Level 1 — the patient the caller addressed.
    assert aborted["conditioning_status"] == "ABORTED", aborted["conditioning_status"]
    assert aborted["conditioning_aborted_reason"] == ABORT_REASON, (
        f"the supplied reason is recorded verbatim as conditioning_aborted_reason, "
        f"expected {ABORT_REASON!r}, got {aborted['conditioning_aborted_reason']!r}"
    )
    assert aborted["version"] == patient_before["version"] + 1, (
        f"every successful conditioning action increments the patient's version by "
        f"exactly one, expected {patient_before['version'] + 1}, got "
        f"{aborted['version']}"
    )

    # Level 2 — the workup case and its candidate.
    case = fixtures.read_workup_case(ctx["workup_case_id"], ctx["coordinator_headers"])
    assert case["case_status"] == "ABORTED", case["case_status"]
    assert case["abort_reason"] == "CONDITIONING_ABORTED", (
        f"the case records abort_reason CONDITIONING_ABORTED, got "
        f"{case['abort_reason']!r}"
    )
    assert case["clearance_status"] == "CLEARED", (
        f"the abort touches the case's disposition, not the clinical work already "
        f"done, got {case['clearance_status']}"
    )
    candidate = fixtures.read_candidate(ctx["candidate_id"], ctx["coordinator_headers"])
    assert candidate["status"] == "CLOSED", (
        f"the case's match candidate is moved to CLOSED from WORKUP_OPEN, got "
        f"{candidate['status']}"
    )

    # Level 3 — the money and the search.
    claim_after = fixtures.read_claim(ctx["claim_id"])
    assert claim_after["status"] == "VOID", (
        f"the PROVISIONAL claim of the aborted case becomes VOID, got "
        f"{claim_after['status']}"
    )
    assert isinstance(claim_after["void_reason"], str) and claim_after["void_reason"], (
        f"the claim's void_reason must be recorded, got {claim_after['void_reason']!r}"
    )
    patient_after = fixtures.read_patient(ctx["patient_id"], ctx["coordinator_headers"])
    assert patient_after["committed_cost_cents"] == (
        patient_before["committed_cost_cents"] - claim_before["total_usd_cents"]
    ), (
        f"committed_cost_cents must be restored by the voided total "
        f"({claim_before['total_usd_cents']}), expected "
        f"{patient_before['committed_cost_cents'] - claim_before['total_usd_cents']}, "
        f"got {patient_after['committed_cost_cents']}"
    )
    search_after = fixtures.read_search(ctx["search_id"], ctx["coordinator_headers"])
    assert search_after["status"] == "STALLED", (
        f"an abort from STARTED moves the search to STALLED rather than to "
        f"BACKUP_REQUIRED, got {search_after['status']}"
    )

    # The bench is deliberately left alone: no promotion cascade runs here.
    untouched = fixtures.read_candidate(backup["id"], ctx["coordinator_headers"])
    assert untouched["candidate_role"] == "BACKUP", (
        f"an ablated recipient cannot be re-matched, so the backup is never promoted, "
        f"got {untouched['candidate_role']}"
    )
    assert untouched["promoted_from_rank"] is None, (
        f"promoted_from_rank stays null when no promotion cascade runs, got "
        f"{untouched['promoted_from_rank']!r}"
    )
    assert untouched["status"] == "IDENTIFIED", untouched["status"]
    assert search_after["backup_candidate_count"] == 1, (
        f"the bench still holds its one backup after the abort, got "
        f"{search_after['backup_candidate_count']}"
    )
