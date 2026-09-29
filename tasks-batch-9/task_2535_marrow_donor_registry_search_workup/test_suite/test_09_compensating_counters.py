"""Derived counters and the exact reversibility of the programme's cascades.

The centre's committed collection minutes, the donor's blocked calendar days and
the patient's committed cost are re-derivations over child rows, never
accumulators.  Rows in the excluded terminal states contribute nothing, which is
what makes a cancellation or a void return each ledger to precisely the value it
held before — the property the finance and capacity teams reconcile against.
"""
from test_helpers import (
    assertions as A,
    constants as C,
    factories as f,
    fixtures,
    validate_paginated,
    validate_success,
)

PROVISIONAL_CLAIM_TOTAL_CENTS = 2_072_000

# ---------------------------------------------------------------------------
# Shared preconditions
# ---------------------------------------------------------------------------

def _cleared_case_ready_to_book():
    """A cleared PBSC case with conditioning scheduled and both ledgers at zero.

    No manual donor window exists and no slot has been held, so the centre's
    `committed_slot_minutes` and the donor's `blocked_day_count` both read zero
    on entry.
    """
    return fixtures.setup_pipeline("conditioning_scheduled")


def _cancel(api, ctx, reason="CENTER_UNAVAILABLE"):
    """Cancel the context's booking as the acting collection centre."""
    return validate_success(
        api.cancel_collection_booking(
            ctx["booking_id"],
            f.cancel_booking_payload(reason=reason),
            ctx["center_ops_headers"],
        )
    )


def _primary_and_backup_with_a_tight_budget():
    """A patient whose budget has room for exactly one provisional claim.

    Two domestic donors are materialised, so the search carries a rank-1
    `PRIMARY` and a single rank-2 `BACKUP`.  The primary's workup is opened —
    committing the whole of the 2,500,000-cent budget that a 2,072,000-cent
    provisional claim leaves room for — and the clock is moved to the clearance
    instant so the ladder can be resulted.
    """
    ctx = fixtures.setup_primary_candidate(
        num_donors=2,
        with_center=False,
        patient_overrides={"case_budget_cents": 2_500_000},
    )
    fixtures.engage_candidate(ctx)
    fixtures.advance_to_workup_open(ctx)
    fixtures.set_clock(C.TIMELINE["CLEARANCE_AT"])
    ctx["clearance"] = fixtures.find_clearance_items(
        ctx["workup_case_id"], ctx["physician_headers"]
    )
    return ctx


# ---------------------------------------------------------------------------
# A cancelled booking gives back the centre's minutes and the donor's days
# ---------------------------------------------------------------------------

def test_cancelling_a_confirmed_booking_restores_the_centres_committed_minutes(api):
    """PRD §2.10: "`CollectionCenter.committed_slot_minutes` is the sum of `duration_minutes` over that centre's bookings whose `status` is `HELD`, `CONFIRMED` or `COMPLETED`."
    PRD §2.10: "Because each of those numbers is a re-derivation and not an accumulator, rows in the excluded terminal states never contribute: a `CANCELLED` or `SUPERSEDED` booking contributes no minutes, a `RELEASED` calendar window contributes no days, and a `VOID` claim contributes no cents."
    PRD §2.10: "A booking that is created and then cancelled must leave its centre's committed minutes at precisely the value they held before the booking existed; confirming a booking and then cancelling it must leave the donor's blocked day count at precisely its prior value; and opening a workup and then voiding its provisional claim must leave the patient's committed cost at precisely its prior value."
    PRD §3.7: "Whether the booking had been confirmed matters for the money: cancelling from `HELD → CANCELLED` leaves `cancelled_after_confirmation` false and costs the programme nothing, whereas cancelling from `CONFIRMED → CANCELLED` sets `cancelled_after_confirmation` true, which adds a cancellation line to the case's final claim."
    PRD §3.7: "Finally, if the case is left with no booking in `HELD` or `CONFIRMED` status, the case's logistics dimension reverts `BOOKED → METHOD_SET` while its clearance dimension is untouched — the case is bookable again without redoing any clinical work."

    Design: Difficulty/compensating_invariant/booking_cancellation_restores_center_minutes_and_donor_blocked_days
    """
    ctx = _cleared_case_ready_to_book()
    assert fixtures.read_center(ctx["center_id"])["committed_slot_minutes"] == 0, (
        "a centre with no booking commits no minutes"
    )

    booking = fixtures.advance_to_booking_held(ctx)
    assert booking["duration_minutes"] == 300, (
        f"a PBSC slot lasts 300 minutes, got {booking['duration_minutes']}"
    )
    assert fixtures.read_center(ctx["center_id"])["committed_slot_minutes"] == 300, (
        "the HELD booking's duration_minutes must be committed at the centre"
    )

    fixtures.advance_to_booking_confirmed(ctx)
    assert fixtures.read_center(ctx["center_id"])["committed_slot_minutes"] == 300, (
        "confirmation moves no minutes: a CONFIRMED booking counts exactly as a "
        "HELD one did"
    )

    cancelled = _cancel(api, ctx)
    assert cancelled["status"] == "CANCELLED", (
        f"the cancel moves the booking to CANCELLED, got {cancelled['status']}"
    )
    assert cancelled["cancel_reason"] == "CENTER_UNAVAILABLE", (
        f"the supplied reason is recorded in cancel_reason, got "
        f"{cancelled['cancel_reason']}"
    )
    assert cancelled["cancelled_after_confirmation"] is True, (
        "cancelling from CONFIRMED sets cancelled_after_confirmation true, got "
        f"{cancelled['cancelled_after_confirmation']}"
    )
    assert fixtures.read_center(ctx["center_id"])["committed_slot_minutes"] == 0, (
        "a CANCELLED booking contributes no minutes, so the centre returns to "
        "precisely the value it held before the booking existed"
    )

    case = fixtures.read_workup_case(
        ctx["workup_case_id"], ctx["coordinator_headers"]
    )
    assert case["logistics_status"] == "METHOD_SET", (
        f"with no HELD or CONFIRMED booking left the case reverts to "
        f"METHOD_SET, got {case['logistics_status']}"
    )
    assert case["clearance_status"] == "CLEARED", (
        f"the clearance dimension is untouched by the cancel, got "
        f"{case['clearance_status']}"
    )


def test_cancelling_a_confirmed_booking_releases_the_collection_window_days(api):
    """PRD §2.10: "`DonorProfile.blocked_day_count` is the sum of `day_count` over that donor's calendar windows whose `status` is `ACTIVE`."
    PRD §2.10: "Because each of those numbers is a re-derivation and not an accumulator, rows in the excluded terminal states never contribute: a `CANCELLED` or `SUPERSEDED` booking contributes no minutes, a `RELEASED` calendar window contributes no days, and a `VOID` claim contributes no cents."
    PRD §3.7: "Either way the window's `day_count` is the inclusive number of days it spans, which comes to six for `PBSC` and eight for `MARROW` — precisely the case's `planned_window_days` — and it raises the donor's `blocked_day_count` accordingly."
    PRD §3.7: "Cancellation records the supplied reason in `cancel_reason`, releases the booking's `duration_minutes` from the centre's `committed_slot_minutes`, and moves any `COLLECTION_WINDOW` window that this booking sourced to `RELEASED`, restoring the donor's `blocked_day_count` to exactly its pre-confirmation value."

    Design: Difficulty/compensating_invariant/booking_cancellation_restores_center_minutes_and_donor_blocked_days
    """
    ctx = _cleared_case_ready_to_book()
    assert fixtures.read_donor(ctx["donor_id"])["blocked_day_count"] == 0, (
        "a donor with no calendar window blocks no days"
    )

    fixtures.advance_to_booking_held(ctx)
    assert fixtures.read_donor(ctx["donor_id"])["blocked_day_count"] == 0, (
        "holding a slot creates no calendar window, so no day is blocked yet"
    )

    fixtures.advance_to_booking_confirmed(ctx)
    assert fixtures.read_donor(ctx["donor_id"])["blocked_day_count"] == 6, (
        "confirmation blocks the six days of the derived PBSC collection window"
    )

    _cancel(api, ctx)
    assert fixtures.read_donor(ctx["donor_id"])["blocked_day_count"] == 0, (
        "a RELEASED window contributes no days, so the donor returns to exactly "
        "its pre-confirmation value"
    )

    windows = fixtures.find_windows(ctx["donor_id"])
    assert len(windows) == 1, (
        f"the released row is never deleted, so exactly one window remains, got "
        f"{len(windows)}"
    )
    window = windows[0]
    assert window["status"] == "RELEASED", (
        f"the cancel moves the sourced COLLECTION_WINDOW to RELEASED, got "
        f"{window['status']}"
    )
    assert window["released_at"] is not None, (
        "a released window carries the instant it was released"
    )
    assert window["day_count"] == 6, (
        f"the released row keeps its day_count of 6 and is merely excluded from "
        f"the re-derivation, got {window['day_count']}"
    )
    assert window["date_from"] == "2026-10-07", (
        f"the released row keeps its dates, got date_from {window['date_from']}"
    )
    assert window["date_to"] == "2026-10-12", (
        f"the released row keeps its dates, got date_to {window['date_to']}"
    )
    assert window["source_booking_id"] == ctx["booking_id"], (
        f"the released row still points back at the booking that sourced it, "
        f"got {window['source_booking_id']}"
    )


def test_released_slot_is_genuinely_rebookable_and_the_money_ledger_is_untouched(api):
    """PRD §2.10: "`CollectionCenter.committed_slot_minutes` is the sum of `duration_minutes` over that centre's bookings whose `status` is `HELD`, `CONFIRMED` or `COMPLETED`."
    PRD §3.7: "Bookings in `CANCELLED` or `SUPERSEDED` status are excluded from the comparison entirely, and they likewise contribute nothing to `committed_slot_minutes`."
    PRD §2.10: "`Patient.committed_cost_cents` is the sum of `total_usd_cents` over that patient's claims whose `status` is `PROVISIONAL` or `FINALIZED`."
    PRD §3.9: "The `CANCELLATION` line is the collection fee for the variant's method multiplied by 0.40, that is forty per cent, rounded half up to whole cents, and it is charged only in the final variant and only when some booking of the case carries `cancelled_after_confirmation` true; in every other situation it is zero."

    Design: Difficulty/compensating_invariant/booking_cancellation_restores_center_minutes_and_donor_blocked_days
    """
    ctx = _cleared_case_ready_to_book()
    fixtures.advance_to_booking_held(ctx)
    fixtures.advance_to_booking_confirmed(ctx)
    _cancel(api, ctx)

    # The released minutes are available, not merely bookkept: the very same
    # slot at the very same centre is accepted again.
    case = fixtures.read_workup_case(ctx["workup_case_id"], ctx["coordinator_headers"])
    rebooked = validate_success(
        api.create_collection_booking(
            f.create_booking_payload(
                case["id"],
                ctx["center_id"],
                C.TIMELINE["BOOKING_START_AT"],
                case["version"],
            ),
            ctx["center_ops_headers"],
        ),
        201,
    )
    assert rebooked["status"] == "HELD", (
        f"the re-booked slot opens in HELD, got {rebooked['status']}"
    )
    A.assert_same_instant(
        rebooked["start_at"], C.TIMELINE["BOOKING_START_AT"],
        "the re-booking holds the same instant the cancelled one did",
    )
    assert fixtures.read_center(ctx["center_id"])["committed_slot_minutes"] == 300, (
        "only the live booking counts: the cancelled one contributes nothing"
    )

    # The cancellation fee lives in the claim ledger, not the capacity ledgers,
    # and it is not charged while the claim is still provisional.
    claim = fixtures.read_claim(ctx["claim_id"])
    assert claim["status"] == "PROVISIONAL", (
        f"the cancel does not close the claim, got {claim['status']}"
    )
    assert A.claim_line(claim, "CANCELLATION") == 0, (
        "the provisional variant always charges a zero cancellation line, got "
        f"{A.claim_line(claim, 'CANCELLATION')}"
    )
    assert claim["cancellation_fee_applied"] is False, (
        "cancellation_fee_applied is recorded true only when the line is "
        f"charged, got {claim['cancellation_fee_applied']}"
    )
    assert claim["total_usd_cents"] == PROVISIONAL_CLAIM_TOTAL_CENTS, (
        f"the provisional total is unmoved by the cancel: expected "
        f"{PROVISIONAL_CLAIM_TOTAL_CENTS}, got {claim['total_usd_cents']}"
    )
    patient = fixtures.read_patient(ctx["patient_id"], ctx["coordinator_headers"])
    assert patient["committed_cost_cents"] == PROVISIONAL_CLAIM_TOTAL_CENTS, (
        f"the still-PROVISIONAL claim is the patient's whole commitment: "
        f"expected {PROVISIONAL_CLAIM_TOTAL_CENTS}, got "
        f"{patient['committed_cost_cents']}"
    )


# ---------------------------------------------------------------------------
# A voided claim gives back the patient's committed cost — and the budget
# ---------------------------------------------------------------------------

def test_failed_clearance_voids_the_claim_and_restores_the_patients_committed_cost(api):
    """PRD §2.10: "`Patient.committed_cost_cents` is the sum of `total_usd_cents` over that patient's claims whose `status` is `PROVISIONAL` or `FINALIZED`."
    PRD §2.10: "Because each of those numbers is a re-derivation and not an accumulator, rows in the excluded terminal states never contribute: a `CANCELLED` or `SUPERSEDED` booking contributes no minutes, a `RELEASED` calendar window contributes no days, and a `VOID` claim contributes no cents."
    PRD §2.10: "A booking that is created and then cancelled must leave its centre's committed minutes at precisely the value they held before the booking existed; confirming a booking and then cancelling it must leave the donor's blocked day count at precisely its prior value; and opening a workup and then voiding its provisional claim must leave the patient's committed cost at precisely its prior value."
    PRD §3.6: "A provisional reimbursement claim is created in the same breath, raising the patient's `committed_cost_cents` by its total."
    PRD §3.6: "The case's provisional reimbursement claim moves `PROVISIONAL → VOID` with its `void_reason` recorded, and the patient's `committed_cost_cents` drops back by that claim's `total_usd_cents`, returning to exactly the value it held before the workup was opened."
    PRD §3.6: "The case moves `case_status` `OPEN → ABORTED` with `clearance_status` `FAILED` and `abort_reason` recorded."
    PRD §3.6: "The candidate moves `WORKUP_OPEN → DEFERRED`."
    PRD §3.6: "When the failure was on the `PHYSICAL_EXAM` or `IDM_PANEL` item, the donor is also moved `AVAILABLE → TEMPORARILY_DEFERRED`: no client-supplied deferral date is accepted on this path, and `deferral_until` is instead derived as the current logical UTC date plus 90 days, with an `ACTIVE` `DEFERRAL` calendar window created over that same span, raising the donor's `blocked_day_count`."
    PRD §2.10: "`DonorProfile.blocked_day_count` is the sum of `day_count` over that donor's calendar windows whose `status` is `ACTIVE`."

    Design: Difficulty/compensating_invariant/claim_void_restores_patient_committed_cost_and_frees_the_budget
    """
    ctx = _primary_and_backup_with_a_tight_budget()

    claim = fixtures.read_claim(ctx["claim_id"])
    assert claim["status"] == "PROVISIONAL", (
        f"the workup open creates a PROVISIONAL claim, got {claim['status']}"
    )
    assert claim["total_usd_cents"] == PROVISIONAL_CLAIM_TOTAL_CENTS, (
        f"the provisional total for a domestic PBSC assumption is "
        f"{PROVISIONAL_CLAIM_TOTAL_CENTS}, got {claim['total_usd_cents']}"
    )
    patient = fixtures.read_patient(ctx["patient_id"], ctx["coordinator_headers"])
    assert patient["committed_cost_cents"] == PROVISIONAL_CLAIM_TOTAL_CENTS, (
        f"the open raised the patient's commitment by the claim's total: "
        f"expected {PROVISIONAL_CLAIM_TOTAL_CENTS}, got "
        f"{patient['committed_cost_cents']}"
    )

    validate_success(
        api.record_clearance_result(
            ctx["clearance"]["PHYSICAL_EXAM"]["id"],
            f.clearance_result_payload(
                result="FAIL", note="Resting ECG abnormality on examination"
            ),
            ctx["physician_headers"],
        )
    )

    voided = fixtures.read_claim(ctx["claim_id"])
    assert voided["status"] == "VOID", (
        f"the failing clearance result voids the provisional claim, got "
        f"{voided['status']}"
    )
    assert voided["void_reason"] is not None, (
        "the void records its reason on the claim"
    )
    assert voided["total_usd_cents"] == PROVISIONAL_CLAIM_TOTAL_CENTS, (
        f"the voided row keeps its computed total and is merely excluded from "
        f"the re-derivation: expected {PROVISIONAL_CLAIM_TOTAL_CENTS}, got "
        f"{voided['total_usd_cents']}"
    )
    A.assert_claim_line_items(voided)

    patient = fixtures.read_patient(ctx["patient_id"], ctx["coordinator_headers"])
    assert patient["committed_cost_cents"] == 0, (
        f"a VOID claim contributes no cents, so the commitment returns to "
        f"exactly the zero it held before the workup was opened, got "
        f"{patient['committed_cost_cents']}"
    )

    case = fixtures.read_workup_case(ctx["workup_case_id"], ctx["coordinator_headers"])
    assert case["case_status"] == "ABORTED", (
        f"the failing result aborts the case, got {case['case_status']}"
    )
    assert case["clearance_status"] == "FAILED", (
        f"the clinical dimension moves to FAILED, got {case['clearance_status']}"
    )
    assert case["abort_reason"] is not None, (
        "the abort records its reason on the case"
    )
    candidate = fixtures.read_candidate(ctx["candidate_id"], ctx["coordinator_headers"])
    assert candidate["status"] == "DEFERRED", (
        f"the failed candidate moves WORKUP_OPEN -> DEFERRED, got "
        f"{candidate['status']}"
    )

    # The same cascade moves the donor's own counter the other way: the derived
    # 90-day deferral blocks 2026-09-11 through 2026-12-10 inclusive.
    donor = fixtures.read_donor(ctx["donor_id"])
    assert donor["availability_status"] == "TEMPORARILY_DEFERRED", (
        f"a failed physical moves the donor AVAILABLE -> TEMPORARILY_DEFERRED, "
        f"got {donor['availability_status']}"
    )
    assert donor["deferral_until"] == "2026-12-10", (
        f"deferral_until is the current logical UTC date 2026-09-11 plus 90 "
        f"days, got {donor['deferral_until']}"
    )
    windows = fixtures.find_windows(ctx["donor_id"])
    assert len(windows) == 1, (
        f"the cascade creates exactly one calendar window, got {len(windows)}"
    )
    deferral = windows[0]
    assert deferral["reason"] == "DEFERRAL", (
        f"the system-created window carries reason DEFERRAL, got "
        f"{deferral['reason']}"
    )
    assert deferral["status"] == "ACTIVE", (
        f"the deferral window opens ACTIVE, got {deferral['status']}"
    )
    assert deferral["date_from"] == "2026-09-11", (
        f"the window spans the same 90 days, opening on the current logical UTC "
        f"date, got {deferral['date_from']}"
    )
    assert deferral["date_to"] == "2026-12-10", (
        f"the window closes on deferral_until, got {deferral['date_to']}"
    )
    assert deferral["day_count"] == 91, (
        f"2026-09-11 through 2026-12-10 inclusive spans 91 days, got "
        f"{deferral['day_count']}"
    )
    assert donor["blocked_day_count"] == 91, (
        f"the ACTIVE deferral window raises the donor's blocked_day_count to "
        f"its 91 days, got {donor['blocked_day_count']}"
    )


def test_void_frees_the_budget_so_the_promoted_backups_workup_fits_within_it(api):
    """PRD §3.6: "And the money must be there: the patient's current `committed_cost_cents` plus the total of the provisional claim about to be created must not exceed the patient's `case_budget_cents`, or the open is refused with `ERR_PATIENT_BUDGET_EXCEEDED` (HTTP 402)."
    PRD §2.10: "`Patient.committed_cost_cents` is the sum of `total_usd_cents` over that patient's claims whose `status` is `PROVISIONAL` or `FINALIZED`."
    PRD §3.6: "The case's provisional reimbursement claim moves `PROVISIONAL → VOID` with its `void_reason` recorded, and the patient's `committed_cost_cents` drops back by that claim's `total_usd_cents`, returning to exactly the value it held before the workup was opened."
    PRD §3.5: "Of the promotable ones, the candidate holding the smallest `rank_position` is lifted to `candidate_role` `PRIMARY`, and its `promoted_from_rank` records the `rank_position` it held when it was promoted."
    PRD §3.5: "The outgoing primary's `candidate_role` becomes `ARCHIVED_POOL`."
    PRD §3.6: "The promotion cascade runs, and the search moves `WORKUP_ACTIVE → BACKUP_REQUIRED`."
    PRD §3.6: "A provisional reimbursement claim is created in the same breath, raising the patient's `committed_cost_cents` by its total."

    Design: Difficulty/compensating_invariant/claim_void_restores_patient_committed_cost_and_frees_the_budget
    """
    ctx = _primary_and_backup_with_a_tight_budget()
    budget = ctx["patient"]["case_budget_cents"]
    assert budget < 2 * PROVISIONAL_CLAIM_TOTAL_CENTS, (
        f"Setup failed: the budget {budget} must have room for exactly one "
        f"{PROVISIONAL_CLAIM_TOTAL_CENTS}-cent claim, not two"
    )
    backup = fixtures.candidate_by_rank(ctx, 2)
    assert backup["candidate_role"] == "BACKUP", (
        f"Setup failed: the rank-2 candidate must be a BACKUP, got "
        f"{backup['candidate_role']}"
    )

    validate_success(
        api.record_clearance_result(
            ctx["clearance"]["PHYSICAL_EXAM"]["id"],
            f.clearance_result_payload(
                result="FAIL", note="Resting ECG abnormality on examination"
            ),
            ctx["physician_headers"],
        )
    )

    promoted = fixtures.read_candidate(backup["id"], ctx["coordinator_headers"])
    assert promoted["candidate_role"] == "PRIMARY", (
        f"the smallest-ranked promotable backup is lifted to PRIMARY, got "
        f"{promoted['candidate_role']}"
    )
    assert promoted["promoted_from_rank"] == 2, (
        f"promoted_from_rank records the rank_position held at promotion, got "
        f"{promoted['promoted_from_rank']}"
    )
    outgoing = fixtures.read_candidate(ctx["candidate_id"], ctx["coordinator_headers"])
    assert outgoing["candidate_role"] == "ARCHIVED_POOL", (
        f"the outgoing primary's role becomes ARCHIVED_POOL, got "
        f"{outgoing['candidate_role']}"
    )
    search = fixtures.read_search(ctx["search_id"], ctx["coordinator_headers"])
    assert search["status"] == "BACKUP_REQUIRED", (
        f"the search moves WORKUP_ACTIVE -> BACKUP_REQUIRED, got {search['status']}"
    )
    assert search["backup_candidate_count"] == 0, (
        f"the promoted backup vacates its slot and it is never refilled, so the "
        f"bench falls to zero, got {search['backup_candidate_count']}"
    )

    # The budget only admits a second provisional claim because the void gave
    # the first one's cents back.
    fixtures.engage_candidate(ctx, candidate_id=backup["id"])
    reopened = validate_success(
        api.open_workup_case(backup["id"], ctx["coordinator_headers"]), 201
    )
    assert reopened["case_status"] == "OPEN", (
        f"the promoted candidate's workup opens OPEN, got {reopened['case_status']}"
    )

    second_claim = fixtures.find_claim_for_case(reopened["id"])
    assert second_claim["status"] == "PROVISIONAL", (
        f"the second open creates its own PROVISIONAL claim, got "
        f"{second_claim['status']}"
    )
    assert second_claim["total_usd_cents"] == PROVISIONAL_CLAIM_TOTAL_CENTS, (
        f"the second provisional total is the same {PROVISIONAL_CLAIM_TOTAL_CENTS} "
        f"cents, got {second_claim['total_usd_cents']}"
    )

    patient = fixtures.read_patient(ctx["patient_id"], ctx["coordinator_headers"])
    assert patient["committed_cost_cents"] == PROVISIONAL_CLAIM_TOTAL_CENTS, (
        f"only the live claim counts, so the commitment is back at "
        f"{PROVISIONAL_CLAIM_TOTAL_CENTS} rather than doubled, got "
        f"{patient['committed_cost_cents']}"
    )
    assert patient["committed_cost_cents"] <= patient["case_budget_cents"], (
        f"the commitment must sit inside the budget: "
        f"{patient['committed_cost_cents']} against {patient['case_budget_cents']}"
    )

    claims, _meta = validate_paginated(
        api.list_reimbursement_claims(
            ctx["operations_headers"],
            params={"patient_id": ctx["patient_id"], "limit": 100},
        )
    )
    assert len(claims) == 2, (
        f"both the voided and the live claim are still listable, got {len(claims)}"
    )
    assert sorted(c["status"] for c in claims) == ["PROVISIONAL", "VOID"], (
        f"exactly one claim is VOID and one PROVISIONAL, got "
        f"{sorted(c['status'] for c in claims)}"
    )
    live_total = sum(
        c["total_usd_cents"] for c in claims if c["status"] in ("PROVISIONAL", "FINALIZED")
    )
    assert live_total == patient["committed_cost_cents"], (
        f"committed_cost_cents is the sum over the patient's non-void claims "
        f"({live_total}), got {patient['committed_cost_cents']}"
    )
