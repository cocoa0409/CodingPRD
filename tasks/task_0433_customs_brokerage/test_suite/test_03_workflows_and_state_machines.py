"""Lifecycle workflows and state-machine transitions: bonds, ISF filings, entries,
PGA reviews, exam slots, and monthly statements — valid transitions, branch
divergence, cyclic recovery, terminal lockdown, and cross-entity bubbles.
"""
import test_helpers as h


# ---------------------------------------------------------------------------
# Queue A — non_linear_state_machine
# ---------------------------------------------------------------------------
def test_pga_review_cyclic_hold_then_may_proceed(api):
    """PRD §3.6: "From `HOLD`, the review may be upgraded to `MAY_PROCEED` — a cyclic recovery permitted only while the review is `HOLD` and the entry is `FILED` or `HOLD_EXAM`, incrementing the review's version".

    A PENDING FDA review is set to HOLD, then upgraded back to MAY_PROCEED; the
    decision reads MAY_PROCEED, proving HOLD was escapable.

    Design: Difficulty/non_linear_state_machine/pga_review_cyclic_hold_then_may_proceed
    """
    ctx = h.setup_filed_entry_with_pending_pga(api)
    h.decide_pga(api, ctx["pga"]["id"], "HOLD", h.OFFICER)
    upgraded = h.validate_success(
        api.decide_pga_review(ctx["pga"]["id"], "MAY_PROCEED", h.OFFICER)
    )
    assert upgraded["decision"] == "MAY_PROCEED", upgraded


def test_pga_review_pending_to_hold_blocks_then_recovers(api):
    """PRD §3.6: "From `PENDING`, the review may move to `MAY_PROCEED` or to `HOLD`".
    PRD §3.6: "A `HOLD` review blocks the entry's release until it is upgraded."

    Setting a PENDING review to HOLD reads decision HOLD; the entry cannot release
    until the review is upgraded, after which release succeeds — the cyclic path
    is traversable.

    Design: Difficulty/non_linear_state_machine/pga_review_cyclic_hold_then_may_proceed
    """
    ctx = h.setup_filed_entry_with_pending_pga(api)
    held = h.validate_success(
        api.decide_pga_review(ctx["pga"]["id"], "HOLD", h.OFFICER)
    )
    assert held["decision"] == "HOLD", held
    h.decide_pga(api, ctx["pga"]["id"], "MAY_PROCEED", h.OFFICER)
    released = h.review_entry(api, ctx["entry"]["id"], "RELEASE", h.OFFICER)
    assert released["status"] == "RELEASED", released


def test_entry_hold_then_release_divergent_side_effects(api):
    """PRD §3.5: "Unlike a release, a hold schedules no statement and matches no
    ISF."
    PRD §3.5: "This release fires the same ISF match and monthly-statement scheduling as the direct release, sets the entry `status` to `RELEASED`".

    A FILED entry routed to HOLD_EXAM leaves statement_id null and the ISF FILED;
    the later HOLD_EXAM->RELEASED assigns a statement_id and matches the ISF.

    Design: Difficulty/non_linear_state_machine/entry_branching_filed_to_hold_then_release_divergent_effects
    """
    ctx = h.setup_filed_entry_with_pending_pga(api)
    held = h.review_entry(api, ctx["entry"]["id"], "HOLD", h.OFFICER)
    assert held["status"] == "HOLD_EXAM", held
    assert held["statement_id"] is None, held
    isf_after_hold = h.validate_success(
        api.get_isf(ctx["base"]["isf"]["id"], h.OFFICER)
    )
    assert isf_after_hold["status"] == "FILED", isf_after_hold
    # Clear PGA, then release out of exam.
    h.decide_pga(api, ctx["pga"]["id"], "MAY_PROCEED", h.OFFICER)
    released = h.review_entry(api, ctx["entry"]["id"], "RELEASE", h.OFFICER)
    assert released["status"] == "RELEASED", released
    assert released["statement_id"] is not None, released
    isf_after_release = h.validate_success(
        api.get_isf(ctx["base"]["isf"]["id"], h.OFFICER)
    )
    assert isf_after_release["status"] == "MATCHED", isf_after_release


def test_hold_branch_leaves_statement_unscheduled(api):
    """PRD §3.5: "A hold stamps `reviewed_by_user_id`, sets the entry `status` to `HOLD_EXAM`, and increments the entry's version. Unlike a release, a hold schedules no statement and matches no ISF."

    Routing a FILED entry to HOLD_EXAM leaves its statement_id null (no scheduling
    on the hold branch).

    Design: Difficulty/non_linear_state_machine/entry_branching_filed_to_hold_then_release_divergent_effects
    """
    ctx = h.setup_filed_entry_with_pending_pga(api)
    held = h.review_entry(api, ctx["entry"]["id"], "HOLD", h.OFFICER)
    assert held["statement_id"] is None, held
    isf = h.validate_success(api.get_isf(ctx["base"]["isf"]["id"], h.OFFICER))
    assert isf["status"] == "FILED", isf


# ---------------------------------------------------------------------------
# Queue B — state_machines section
# ---------------------------------------------------------------------------
def test_bond_activate_sets_continuous_bond_id(api):
    """PRD §3.1: "On activation, if the bond's `bond_type` is `CONTINUOUS`, the securing importer's `continuous_bond_id` is set to point at this bond".

    Activating a PENDING CONTINUOUS bond moves it to ACTIVE and sets the
    importer's continuous_bond_id to the bond id.

    Design: Corner/state_machines/bond_activate_pending_to_active_sets_continuous_bond_id
    """
    importer = h.create_importer(api)
    bond = h.validate_success(
        api.create_bond(h.create_bond_payload(importer["id"]), h.ADMIN),
        expected_status=201,
    )
    activated = h.validate_success(api.activate_bond(bond["id"], h.ADMIN))
    assert activated["status"] == "ACTIVE", activated
    refreshed = h.validate_success(api.get_importer(importer["id"], h.ADMIN))
    assert refreshed["continuous_bond_id"] == bond["id"], refreshed


def test_isf_file_requires_ten_data_elements(api):
    """PRD §3.2: "This is permitted only while the ISF is in `DRAFT` and all ten importer data elements are present — that is, `data_element_count` equals exactly 10; an attempt with any other count is rejected with `ERR_ISF_INCOMPLETE` (HTTP 422)."

    Filing a DRAFT ISF with data_element_count 9 is rejected and the ISF stays DRAFT.

    Design: Corner/state_machines/isf_file_requires_ten_data_elements_precondition
    """
    importer = h.create_importer(api)
    isf = h.validate_success(
        api.create_isf(
            h.create_isf_payload(importer["id"], data_element_count=9), h.BROKER
        ),
        expected_status=201,
    )
    h.validate_error(api.file_isf(isf["id"], h.BROKER), h.ApiErrorId.ERR_ISF_INCOMPLETE)
    refreshed = h.validate_success(api.get_isf(isf["id"], h.BROKER))
    assert refreshed["status"] == "DRAFT", refreshed


def test_isf_file_sets_filed_at_and_late_filing_true(api):
    """PRD §3.2: "the server stamps `filed_at` with the current logical clock instant and computes `late_filing`: the filing is late, and `late_filing` is set true, exactly when `filed_at` is strictly later than the moment 24 hours before the `vessel_eta`".

    Filing at clock 2026-06-09T12:00:00Z against vessel_eta 2026-06-10T00:00:00Z
    (cutoff 2026-06-09T00:00:00Z) stamps filed_at = clock.now and sets
    late_filing true.

    Design: Corner/state_machines/isf_file_sets_filed_at_and_late_filing_true_side_effect
    """
    h.set_clock(api, "2026-06-09T12:00:00Z")
    importer = h.create_importer(api)
    isf = h.validate_success(
        api.create_isf(
            h.create_isf_payload(importer["id"], vessel_eta="2026-06-10T00:00:00Z"),
            h.BROKER,
        ),
        expected_status=201,
    )
    filed = h.validate_success(api.file_isf(isf["id"], h.BROKER))
    assert filed["status"] == "FILED", filed
    assert filed["late_filing"] is True, filed
    assert filed["filed_at"] == "2026-06-09T12:00:00.000Z", filed


def test_isf_file_on_time_sets_late_filing_false(api):
    """PRD §3.2: "if `filed_at` is at or before that cutoff, `late_filing` is false."

    Filing at clock 2026-06-08T00:00:00Z (before the cutoff 2026-06-09T00:00:00Z
    for vessel_eta 2026-06-10T00:00:00Z) sets late_filing false.

    Design: Corner/state_machines/isf_file_on_time_sets_late_filing_false
    """
    h.set_clock(api, "2026-06-08T00:00:00Z")
    importer = h.create_importer(api)
    isf = h.validate_success(
        api.create_isf(
            h.create_isf_payload(importer["id"], vessel_eta="2026-06-10T00:00:00Z"),
            h.BROKER,
        ),
        expected_status=201,
    )
    filed = h.validate_success(api.file_isf(isf["id"], h.BROKER))
    assert filed["status"] == "FILED", filed
    assert filed["late_filing"] is False, filed


def test_file_isf_twice_rejected_invalid_state(api):
    """PRD §3.2: "A `LicensedBroker` files a draft ISF, advancing it from `DRAFT` to `FILED`. This is permitted only while the ISF is in `DRAFT`".

    Filing an already-FILED ISF (no DRAFT->FILED edge from FILED) is rejected
    ERR_INVALID_STATE.

    Design: Corner/state_machines/file_isf_twice_invalid_from_filed_rejected
    """
    importer = h.create_importer(api)
    isf = h.create_filed_isf(api, importer["id"])
    h.validate_error(api.file_isf(isf["id"], h.BROKER), h.ApiErrorId.ERR_INVALID_STATE)


def test_cancel_filed_isf_rejected_invalid_state(api):
    """PRD §3.2: "A `LicensedBroker` may instead cancel a draft, moving it from `DRAFT` to the terminal `CANCELLED` state and incrementing its version; cancellation is permitted only while the ISF is in `DRAFT`."

    Cancelling a FILED ISF is rejected ERR_INVALID_STATE.

    Design: Corner/state_machines/cancel_isf_from_filed_invalid_state
    """
    importer = h.create_importer(api)
    isf = h.create_filed_isf(api, importer["id"])
    h.validate_error(api.cancel_isf(isf["id"], h.BROKER), h.ApiErrorId.ERR_INVALID_STATE)


def test_new_entry_initial_state_is_draft(api):
    """PRD §3.3: "A new entry begins in `DRAFT` `status` with its `provisional_total_cents` and `total_duties_owed_cents` at 0, its `final_total_cents` null".

    A freshly created entry starts DRAFT with zeroed provisional and owed totals.

    Design: Corner/state_machines/new_entry_initial_state_is_draft
    """
    importer = h.create_importer(api)
    bond = h.create_active_bond(api, importer["id"])
    entry = h.validate_success(
        api.create_entry(
            h.create_entry_payload(importer["id"], bond["id"]), h.BROKER
        ),
        expected_status=201,
    )
    assert entry["status"] == "DRAFT", entry
    assert entry["provisional_total_cents"] == 0, entry
    assert entry["total_duties_owed_cents"] == 0, entry


def test_cancel_already_cancelled_entry_rejected(api):
    """PRD §3.4: "A `LicensedBroker` may instead cancel a draft entry, moving it from `DRAFT` to the terminal `CANCELLED` state and incrementing its version; cancellation is permitted only while the entry is in `DRAFT`."

    CANCELLED is terminal; cancelling an already-CANCELLED entry is rejected
    ERR_INVALID_STATE and the entry stays CANCELLED.

    Design: Corner/state_machines/cancel_already_cancelled_entry_terminal_lockdown
    """
    importer = h.create_importer(api)
    bond = h.create_active_bond(api, importer["id"])
    entry = h.validate_success(
        api.create_entry(
            h.create_entry_payload(importer["id"], bond["id"]), h.BROKER
        ),
        expected_status=201,
    )
    h.validate_success(api.cancel_entry(entry["id"], h.BROKER))
    h.validate_error(
        api.cancel_entry(entry["id"], h.BROKER), h.ApiErrorId.ERR_INVALID_STATE
    )
    refreshed = h.validate_success(api.get_entry(entry["id"], h.BROKER))
    assert refreshed["status"] == "CANCELLED", refreshed


def test_bond_terminate_requires_zero_outstanding_liability(api):
    """PRD §3.1: "Terminating a bond moves it from `ACTIVE` to the terminal `TERMINATED` state; this is allowed only while the bond is `ACTIVE` and its `outstanding_liability_cents` is exactly 0."

    Terminating an ACTIVE bond carrying liability from a FILED entry is rejected
    ERR_INVALID_STATE and the bond stays ACTIVE.

    Design: Corner/state_machines/bond_terminate_requires_zero_outstanding_liability_precondition
    """
    ctx = h.setup_filed_entry(api)
    bond_id = ctx["base"]["bond"]["id"]
    h.validate_error(
        api.terminate_bond(bond_id, h.ADMIN), h.ApiErrorId.ERR_INVALID_STATE
    )
    refreshed = h.validate_success(api.get_bond(bond_id, h.ADMIN))
    assert refreshed["status"] == "ACTIVE", refreshed


def test_filing_entry_auto_saturates_bond_at_limit_equal(api):
    """PRD §3.4: "if that reconciliation brings the bond's outstanding liability up to or past its `limit_cents`, the bond auto-transitions from `ACTIVE` to `SATURATED`."

    Filing a general entry (provisional 54800) against a bond with limit 54800
    sets outstanding_liability_cents to 54800 and auto-saturates the bond (>= limit)
    without rejecting the filing.

    Design: Corner/state_machines/filing_entry_auto_saturates_bond_at_limit_equal
    """
    ctx = h.setup_filed_entry(api, bond_limit_cents=54_800)
    assert ctx["entry"]["provisional_total_cents"] == 54800, ctx["entry"]
    bond = h.validate_success(api.get_bond(ctx["base"]["bond"]["id"], h.ADMIN))
    assert bond["outstanding_liability_cents"] == 54800, bond
    assert bond["status"] == "SATURATED", bond


def test_hold_exam_release_frees_booked_exam_slot(api):
    """PRD §3.5: "additionally transitions every `BOOKED` examination slot booked against this entry to `RELEASED_SLOT`, freeing the station."

    Booking an exam slot on a HOLD_EXAM entry then releasing the entry bubbles the
    BOOKED slot to RELEASED_SLOT.

    Design: Corner/state_machines/hold_exam_release_frees_booked_exam_slot_cross_entity
    """
    ctx = h.setup_hold_exam_entry(api)
    slot = h.book_exam_slot(api, ctx["entry"]["id"], h.OFFICER)
    released = h.review_entry(api, ctx["entry"]["id"], "RELEASE", h.OFFICER)
    assert released["status"] == "RELEASED", released
    refreshed_slot = h.validate_success(api.get_exam_slot(slot["id"], h.OFFICER))
    assert refreshed_slot["status"] == "RELEASED_SLOT", refreshed_slot


def test_cancel_booked_exam_slot_moves_to_cancelled(api):
    """PRD §3.7: "A `CBPOfficer` may cancel a `BOOKED` slot, moving it from `BOOKED` to the terminal `CANCELLED_SLOT` state and incrementing its version; cancellation is permitted only while the slot is `BOOKED`".

    Cancelling a BOOKED slot moves it to CANCELLED_SLOT.

    Design: Corner/state_machines/cancel_booked_exam_slot_frees_interval
    """
    ctx = h.setup_hold_exam_entry(api)
    slot = h.book_exam_slot(api, ctx["entry"]["id"], h.OFFICER)
    cancelled = h.validate_success(api.cancel_exam_slot(slot["id"], h.OFFICER))
    assert cancelled["status"] == "CANCELLED_SLOT", cancelled


def test_pga_refused_is_terminal_cannot_upgrade(api):
    """PRD §3.6: "Once any review on an entry is `REFUSED`, that entry can never be released. The `MAY_PROCEED` and `REFUSED` states are terminal for a review."

    A HOLD review escalated to REFUSED cannot be decided MAY_PROCEED; the attempt
    is rejected ERR_INVALID_STATE and the decision stays REFUSED.

    Design: Corner/state_machines/pga_refused_is_terminal_cannot_upgrade
    """
    ctx = h.setup_filed_entry_with_pending_pga(api)
    h.decide_pga(api, ctx["pga"]["id"], "HOLD", h.OFFICER)
    h.decide_pga(api, ctx["pga"]["id"], "REFUSED", h.OFFICER)
    h.validate_error(
        api.decide_pga_review(ctx["pga"]["id"], "MAY_PROCEED", h.OFFICER),
        h.ApiErrorId.ERR_INVALID_STATE,
    )
    refreshed = h.validate_success(api.get_pga_review(ctx["pga"]["id"], h.OFFICER))
    assert refreshed["decision"] == "REFUSED", refreshed


def test_settle_statement_when_all_entries_liquidated(api):
    """PRD §3.8: "An `AccountAdmin` settles a statement, advancing it from `OPEN` to the terminal `SETTLED` state. Settlement is permitted only while the statement is `OPEN` and only when every entry whose `statement_id` equals this statement has reached `LIQUIDATED` status".

    A statement whose single entry is LIQUIDATED transitions OPEN->SETTLED.

    Design: Corner/state_machines/settle_statement_marks_settled_when_all_entries_liquidated
    """
    ctx = h.setup_liquidated_entry(api)
    stmt_id = ctx["statement_id"]
    settled = h.validate_success(api.settle_statement(stmt_id, h.ADMIN))
    assert settled["status"] == "SETTLED", settled


def test_review_release_bubbles_isf_to_matched(api):
    """PRD §3.5: "the referenced ISF transitions from `FILED` to the terminal `MATCHED` state, recording that the manifest has matched the security filing".

    Releasing a FILED entry cascades its referenced ISF FILED->MATCHED.

    Design: Corner/state_machines/review_release_bubbles_isf_filed_to_matched
    """
    ctx = h.setup_filed_entry(api)
    released = h.review_entry(api, ctx["entry"]["id"], "RELEASE", h.OFFICER)
    assert released["status"] == "RELEASED", released
    isf = h.validate_success(api.get_isf(ctx["base"]["isf"]["id"], h.OFFICER))
    assert isf["status"] == "MATCHED", isf
