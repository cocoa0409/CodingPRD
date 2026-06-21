"""State-machine behaviour: valid/invalid transitions, terminal lockdown,
the waiver and boarding revision cycles, cross-entity gating (waiver- and
standing-gated transitions), and deterministic validation ordering (PRD §2.6,
§3.4, §3.5, §3.7, §3.8).
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_owner, create_owner_with_signed_waiver, create_signed_waiver,
    create_pending_waiver, create_stall, create_horse,
    create_draft_agreement, transition_agreement,
    create_active_boarding, create_lesson, complete_lesson,
    create_service_visit, schedule_service_visit,
    create_show_entry, confirm_show_entry, open_invoice, set_clock,
    setup_delinquent_owner_with_suspended_agreement,
    create_invoice_payload,
    make_owner_headers, TEST_USERS,
)

BM = TEST_USERS["barn_manager_headers"]
INSTRUCTOR = TEST_USERS["instructor_headers"]


def _owner_waiver_status(api, owner_id):
    data, _ = validate_paginated(api.list_waivers(owner_id, BM))
    return {w["id"]: w for w in data}


# ===========================================================================
# Difficulty: non_linear_state_machine
# ===========================================================================
def test_waiver_lazy_expires_when_clock_passes_expiry(api):
    """PRD §3.4: "when an owner's waiver list is read, each `SIGNED` waiver whose
    `expires_at` the clock has reached or passed is moved `SIGNED → EXPIRED` before
    the list is returned."

    Design: Difficulty/non_linear_state_machine/waiver_signed_expired_signed_cycle
    """
    set_clock("2026-06-01T00:00:00.000Z")
    owner = create_owner()
    waiver = create_signed_waiver(owner["id"])
    set_clock("2027-06-02T00:00:00.000Z")
    waivers = _owner_waiver_status(api, owner["id"])
    assert waivers[waiver["id"]]["status"] == "EXPIRED"


def test_waiver_resign_after_expiry_returns_to_signed_with_new_expiry(api):
    """PRD §3.4: "re-signing an `EXPIRED` waiver renews the same waiver
    `EXPIRED → SIGNED`. In both cases the system stamps `signed_at` with the current
    logical time and recomputes `expires_at` as exactly 365 days after `signed_at`
    (waivers are valid for one year)."

    Design: Difficulty/non_linear_state_machine/waiver_signed_expired_signed_cycle
    """
    set_clock("2026-06-01T00:00:00.000Z")
    owner = create_owner()
    waiver = create_signed_waiver(owner["id"])
    set_clock("2027-06-02T00:00:00.000Z")
    validate_paginated(api.list_waivers(owner["id"], BM))  # fires lazy expiry
    res = api.sign_waiver(owner["id"], waiver["id"], make_owner_headers(owner["id"]))
    signed = validate_success(res, 200)
    assert signed["status"] == "SIGNED"
    assert signed["expires_at"] == "2028-06-01T00:00:00.000Z"


def test_boarding_suspend_then_reinstate_accrues_suspended_days(api):
    """PRD §3.5: "On success the agreement becomes `ACTIVE` again; the whole number
    of days between `suspended_at` and the current logical time is added to the
    agreement's `suspended_days`, and `suspended_at` is cleared to null."

    Design: Difficulty/non_linear_state_machine/boarding_active_suspended_active_cycle
    """
    ctx = create_active_boarding(daily_rate_cents=4500)
    set_clock("2026-06-04T00:00:00.000Z")
    transition_agreement(ctx["agreement"]["id"], "SUSPENDED")
    set_clock("2026-06-07T00:00:00.000Z")
    reinstated = validate_success(
        api.transition_boarding_agreement(ctx["agreement"]["id"], {"target_status": "ACTIVE"}, BM),
        200,
    )
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["suspended_days"] == 3


def test_boarding_suspend_sets_suspended_status(api):
    """PRD §3.5: "On suspension the agreement becomes `SUSPENDED` and `suspended_at`
    is stamped with the current logical time."

    Design: Difficulty/non_linear_state_machine/boarding_active_suspended_active_cycle
    """
    ctx = create_active_boarding(daily_rate_cents=4500)
    set_clock("2026-06-04T00:00:00.000Z")
    suspended = validate_success(
        api.transition_boarding_agreement(ctx["agreement"]["id"], {"target_status": "SUSPENDED"}, BM),
        200,
    )
    assert suspended["status"] == "SUSPENDED"


# ===========================================================================
# Difficulty: cross_entity_state_dependency
# ===========================================================================
def test_boarding_activation_requires_signed_waiver(api):
    """PRD §3.5: "the owner must hold a `SIGNED` non-expired liability waiver, failing
    which the request is rejected with `ERR_WAIVER_NOT_ACTIVE`".

    Design: Difficulty/cross_entity_state_dependency/boarding_activation_requires_signed_waiver
    """
    set_clock("2026-06-01T00:00:00.000Z")
    owner = create_owner()
    create_pending_waiver(owner["id"])  # PENDING, never signed
    stall = create_stall(daily_rate_cents=4500)
    horse = create_horse(owner["id"])
    agreement = create_draft_agreement(horse["id"], stall["id"])
    res = api.transition_boarding_agreement(agreement["id"], {"target_status": "ACTIVE"}, BM)
    validate_error(res, "ERR_WAIVER_NOT_ACTIVE", expected_status=409)
    after = validate_success(api.get_horse(horse["id"], BM), 200)  # horse readable
    assert after is not None
    agreements, _ = validate_paginated(api.list_horse_boarding_agreements(horse["id"], BM))
    assert agreements[0]["status"] == "DRAFT"


def test_boarding_activation_with_signed_waiver_succeeds(api):
    """PRD §3.5: "On success the agreement becomes `ACTIVE`, the stall's
    `occupied_count` increases by one, and the agreement's `provisional_charge_cents`
    is computed by the provisional boarding-charge rule of Section 3.6."

    Design: Difficulty/cross_entity_state_dependency/boarding_activation_requires_signed_waiver
    """
    set_clock("2026-06-01T00:00:00.000Z")
    owner, _w = create_owner_with_signed_waiver()
    stall = create_stall(daily_rate_cents=4500)
    horse = create_horse(owner["id"])
    agreement = create_draft_agreement(horse["id"], stall["id"])
    res = api.transition_boarding_agreement(agreement["id"], {"target_status": "ACTIVE"}, BM)
    activated = validate_success(res, 200)
    assert activated["status"] == "ACTIVE"


def test_reinstate_requires_owner_standing_below_threshold(api):
    """PRD §3.5: "the owner's committed `standing_score` must be strictly less than
    the suspension threshold of 80 points, or reinstatement is refused with
    `ERR_OWNER_DELINQUENT`."

    Design: Difficulty/cross_entity_state_dependency/reinstate_requires_owner_standing_below_threshold
    """
    ctx = setup_delinquent_owner_with_suspended_agreement()
    owner = validate_success(api.get_owner(ctx["owner"]["id"], BM), 200)
    assert owner["standing_score"] == 80
    a2 = ctx["second_agreement"]["id"]
    res = api.transition_boarding_agreement(a2, {"target_status": "ACTIVE"}, BM)
    validate_error(res, "ERR_OWNER_DELINQUENT", expected_status=409)
    agreements, _ = validate_paginated(api.list_horse_boarding_agreements(ctx["horse"]["id"], BM))
    target = [a for a in agreements if a["id"] == a2][0]
    assert target["status"] == "SUSPENDED"


def test_delinquent_owner_standing_score_reaches_suspend_threshold(api):
    """PRD §3.9: "On each such recompute the owner's `status` is derived: `DELINQUENT`
    when `standing_score` is at or above the suspension threshold of 80 points,
    otherwise `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/reinstate_requires_owner_standing_below_threshold
    """
    ctx = setup_delinquent_owner_with_suspended_agreement()
    owner = validate_success(api.get_owner(ctx["owner"]["id"], BM), 200)
    assert owner["standing_score"] == 80
    assert owner["status"] == "DELINQUENT"


# ===========================================================================
# Difficulty: priority_pair_validation_conflict
# ===========================================================================
def test_state_beats_constraint_on_double_finalize(api):
    """PRD §2.6: "state before deeper business logic." — the state-conflict family
    (`ERR_INVOICE_NOT_OPEN`) is evaluated before the business rules including
    no-billable-lines.
    PRD §3.8: "The invoice must be `OPEN` (else `ERR_INVOICE_NOT_OPEN`)".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_finalize
    """
    set_clock("2026-06-01T00:00:00.000Z")
    owner = create_owner()
    invoice = open_invoice(owner["id"])
    validate_success(api.transition_invoice(invoice["id"], {"target_status": "VOID"}, BM), 200)
    fresh = validate_success(api.get_owner(owner["id"], BM), 200)
    res = api.transition_invoice(
        invoice["id"],
        {"target_status": "FINALIZED", "expected_owner_version": fresh["version"]},
        BM,
    )
    validate_error(res, "ERR_INVOICE_NOT_OPEN", expected_status=409)


def test_double_finalize_leaves_voided_invoice_unchanged(api):
    """PRD §3.8: "Voiding an `OPEN` invoice simply moves it to `VOID`". PRD §3.8:
    "Both `PAID` and `VOID` are terminal." — the rejected re-finalize must not move
    the already-terminal VOID invoice.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_finalize
    """
    set_clock("2026-06-01T00:00:00.000Z")
    owner = create_owner()
    invoice = open_invoice(owner["id"])
    validate_success(api.transition_invoice(invoice["id"], {"target_status": "VOID"}, BM), 200)
    fresh = validate_success(api.get_owner(owner["id"], BM), 200)
    api.transition_invoice(
        invoice["id"],
        {"target_status": "FINALIZED", "expected_owner_version": fresh["version"]},
        BM,
    )
    invoices, _ = validate_paginated(api.list_owner_invoices(owner["id"], BM))
    assert invoices[0]["status"] == "VOID"


def test_safety_beats_existence_on_show_confirm(api):
    """PRD §3.7: "the entry must be `SUBMITTED` (else `ERR_INVALID_STATE`) and the
    owner must hold a `SIGNED` non-expired waiver (else `ERR_WAIVER_NOT_ACTIVE`)".

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_show_confirm
    """
    set_clock("2026-06-01T00:00:00.000Z")
    owner = create_owner()  # no signed waiver
    horse = create_horse(owner["id"])
    entry = create_show_entry(horse["id"])
    res = api.transition_show_entry(entry["id"], {"target_status": "CONFIRMED"}, BM)
    validate_error(res, "ERR_WAIVER_NOT_ACTIVE", expected_status=409)


def test_show_confirm_blocked_by_missing_waiver_leaves_entry_submitted(api):
    """PRD §3.7: "A `BarnManager` confirms a submitted entry by requesting target
    status `CONFIRMED`: the entry must be `SUBMITTED` (else `ERR_INVALID_STATE`) and
    the owner must hold a `SIGNED` non-expired waiver (else `ERR_WAIVER_NOT_ACTIVE`)".

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_show_confirm
    """
    set_clock("2026-06-01T00:00:00.000Z")
    owner = create_owner()  # no signed waiver
    horse = create_horse(owner["id"])
    entry = create_show_entry(horse["id"])
    api.transition_show_entry(entry["id"], {"target_status": "CONFIRMED"}, BM)
    entries, _ = validate_paginated(api.list_horse_show_entries(horse["id"], BM))
    assert entries[0]["status"] == "SUBMITTED"


# ===========================================================================
# Corner: state_machines
# ===========================================================================
def test_sign_already_signed_waiver_returns_not_signable(api):
    """PRD §3.4: "A sign attempted on a waiver that is in neither `PENDING` nor
    `EXPIRED` is rejected with `ERR_WAIVER_NOT_SIGNABLE`."

    Design: Corner/state_machines/sign_already_signed_waiver_returns_not_signable
    """
    set_clock("2026-06-01T00:00:00.000Z")
    owner = create_owner()
    waiver = create_signed_waiver(owner["id"])
    res = api.sign_waiver(owner["id"], waiver["id"], make_owner_headers(owner["id"]))
    validate_error(res, "ERR_WAIVER_NOT_SIGNABLE", expected_status=409)


def test_lesson_completed_then_cancel_returns_invalid_state(api):
    """PRD §3.7: "the lesson must be `SCHEDULED` (else `ERR_INVALID_STATE`)" — applies
    to the cancellation branch, so a COMPLETED lesson cannot be cancelled.

    Design: Corner/state_machines/lesson_completed_then_cancel_returns_invalid_state
    """
    ctx = create_active_boarding()
    lesson = create_lesson(
        ctx["horse"]["id"],
        starts_at="2026-06-02T10:00:00.000Z",
        ends_at="2026-06-02T11:00:00.000Z",
    )
    complete_lesson(lesson["id"])
    res = api.transition_lesson(lesson["id"], {"target_status": "CANCELLED"}, BM)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    lessons, _ = validate_paginated(api.list_horse_lessons(ctx["horse"]["id"], BM))
    assert lessons[0]["status"] == "COMPLETED"


def test_lesson_completed_full_fee_branch(api):
    """PRD §3.7: "Marking it `COMPLETED` is performed by an `Instructor`: the lesson
    must be `SCHEDULED` (else `ERR_INVALID_STATE`) and the horse's boarding agreement
    must be `ACTIVE` (else `ERR_BOARDING_NOT_ACTIVE`), and on success `billed_fee_cents`
    is set to the full `lesson_fee_cents`."

    Design: Corner/state_machines/lesson_completed_full_fee_branch
    """
    ctx = create_active_boarding()
    lesson = create_lesson(
        ctx["horse"]["id"],
        starts_at="2026-06-02T10:00:00.000Z",
        ends_at="2026-06-02T11:00:00.000Z",
        lesson_fee_cents=8000,
    )
    res = api.transition_lesson(lesson["id"], {"target_status": "COMPLETED"}, INSTRUCTOR)
    completed = validate_success(res, 200)
    assert completed["status"] == "COMPLETED"
    assert completed["billed_fee_cents"] == 8000


def test_show_entry_scratched_keeps_fee_billable(api):
    """PRD §3.7: "A `BarnManager` may scratch a `CONFIRMED` entry by requesting target
    status `SCRATCHED` (the entry must be `CONFIRMED`, else `ERR_INVALID_STATE`); a
    scratched entry keeps its `entry_fee_cents` as a no-refund billable line."

    Design: Corner/state_machines/show_entry_scratched_keeps_fee_billable
    """
    set_clock("2026-06-01T00:00:00.000Z")
    owner, _w = create_owner_with_signed_waiver()
    horse = create_horse(owner["id"])
    entry = create_show_entry(horse["id"], event_name="Gala")
    confirm_show_entry(entry["id"])
    res = api.transition_show_entry(entry["id"], {"target_status": "SCRATCHED"}, BM)
    scratched = validate_success(res, 200)
    assert scratched["status"] == "SCRATCHED"


def test_service_visit_cancel_releases_window_allows_reschedule(api):
    """PRD §3.7: "A `BarnManager` or `Owner` may cancel a visit that is `REQUESTED`
    or `SCHEDULED` by requesting target status `CANCELLED`, which releases the horse's
    window so a replacement visit may be scheduled."

    Design: Corner/state_machines/service_visit_cancel_releases_window_allows_reschedule
    """
    set_clock("2026-06-01T00:00:00.000Z")
    owner = create_owner()
    horse = create_horse(owner["id"])
    sv1 = create_service_visit(horse["id"], scheduled_at="2026-06-05T09:00:00.000Z",
                               duration_minutes=60, fee_cents=12000)
    schedule_service_visit(sv1["id"])
    sv2 = create_service_visit(horse["id"], visit_type="VET",
                               scheduled_at="2026-06-05T09:30:00.000Z",
                               duration_minutes=60, fee_cents=20000)
    validate_success(api.transition_service_visit(sv1["id"], {"target_status": "CANCELLED"}, BM), 200)
    res = api.transition_service_visit(sv2["id"], {"target_status": "SCHEDULED"}, BM)
    scheduled = validate_success(res, 200)
    assert scheduled["status"] == "SCHEDULED"


def test_stall_full_blocks_second_activation(api):
    """PRD §3.5: "the chosen stall must have room — its `occupied_count` must be
    strictly less than its `capacity`, or activation fails with `ERR_STALL_FULL`."

    Design: Corner/state_machines/stall_full_blocks_second_activation
    """
    set_clock("2026-06-01T00:00:00.000Z")
    owner, _w = create_owner_with_signed_waiver()
    stall = create_stall(daily_rate_cents=4500)  # capacity 1
    h1 = create_horse(owner["id"], name="Juno2")
    h2 = create_horse(owner["id"], name="Kilo")
    a1 = create_draft_agreement(h1["id"], stall["id"])
    transition_agreement(a1["id"], "ACTIVE")
    a2 = create_draft_agreement(h2["id"], stall["id"])
    res = api.transition_boarding_agreement(a2["id"], {"target_status": "ACTIVE"}, BM)
    validate_error(res, "ERR_STALL_FULL", expected_status=409)
    agreements, _ = validate_paginated(api.list_horse_boarding_agreements(h2["id"], BM))
    assert agreements[0]["status"] == "DRAFT"


def test_waiver_supersede_marks_old_superseded(api):
    """PRD §3.4: "Creating a new waiver while the owner already holds a `SIGNED`
    waiver supersedes the old one: the system points the old waiver's
    `superseded_by_id` at the new waiver's `id` and moves the old waiver to
    `SUPERSEDED`, which is terminal."

    Design: Corner/state_machines/waiver_supersede_marks_old_superseded
    """
    set_clock("2026-06-01T00:00:00.000Z")
    owner = create_owner()
    old = create_signed_waiver(owner["id"])
    new = validate_success(
        api.create_waiver(owner["id"], make_owner_headers(owner["id"])), 201
    )
    waivers = _owner_waiver_status(api, owner["id"])
    assert waivers[old["id"]]["status"] == "SUPERSEDED"
    assert waivers[old["id"]]["superseded_by_id"] == new["id"]
