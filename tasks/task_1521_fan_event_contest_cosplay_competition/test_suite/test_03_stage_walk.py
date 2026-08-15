"""Stage walk: queueing gate tiers (state, safety, consent, sequence), the
strictly ordered stage advance, skip regression, and the withdraw cascade's
slot skip + sequence compaction.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_entry,
    assert_performance_slot,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.factories import create_performance_slot_payload
from test_helpers.test_users import TEST_USERS

LEAD = TEST_USERS["contest_lead_headers"]
STAGE = TEST_USERS["stage_manager_headers"]


def _judging_contest_with_entries(entry_specs=()):
    """Contest in JUDGING with entries created/safety-approved per spec.

    entry_specs: list of dicts {title, requires_prejudging, approve, consent}.
    Returns (contest, category, [(contestant, entry), ...]).
    """
    contest = fx.create_contest()
    category = fx.create_category(contest["id"])
    fx.open_registration(contest["id"])
    pairs = []
    for i, spec in enumerate(entry_specs):
        contestant = fx.create_contestant(full_name=f"C {i + 1}")
        entry = fx.create_entry(
            contestant, category["id"], title=spec.get("title", f"E{i + 1}"),
            requires_prejudging=spec.get("requires_prejudging", False),
        )
        if spec.get("approve", True):
            fx.approve_entry_safety(entry["id"])
        if spec.get("consent", True):
            fx.grant_livestream_consent(contestant)
        pairs.append((contestant, entry))
    fx.advance_contest_to_judging(contest["id"])
    return contest, category, pairs


# ---------------------------------------------------------------------------
# Cross-entity gate: PerformanceSlot -> Entry.safety_status
# ---------------------------------------------------------------------------

def test_stage_queue_blocked_until_safety_approved(api):
    """PRD §3.6: "Safety next: the entry's `safety_status` must be `APPROVED`, otherwise `ERR_SAFETY_NOT_APPROVED`."
    PRD §3.6: "Successful queuing moves a `SAFETY_APPROVED` or `PREJUDGED` entry to `STAGE_QUEUED`."

    The identical queue request fails while the entry is SUBMITTED (safety
    PENDING) and succeeds after the SafetyOfficer approves.

    Design: Difficulty/cross_entity_state_dependency/stage_queue_blocked_until_entry_safety_approved
    """
    contest, category, pairs = _judging_contest_with_entries(
        [{"approve": False, "consent": True}]
    )
    contestant, entry = pairs[0]

    resp_blocked = api.create_performance_slot(
        create_performance_slot_payload(entry["id"], 1), STAGE
    )
    validate_error(resp_blocked, ApiErrorId.ERR_SAFETY_NOT_APPROVED)

    fx.approve_entry_safety(entry["id"])
    resp_ok = api.create_performance_slot(
        create_performance_slot_payload(entry["id"], 1), STAGE
    )
    slot = validate_success(resp_ok, 201)
    assert_performance_slot(slot)
    assert slot["status"] == "QUEUED"
    assert fx.get_entry(entry["id"])["status"] == "STAGE_QUEUED"


def test_stage_queue_blocked_for_safety_rejected_entry(api):
    """PRD §3.6: "State first: the entry must be in `SUBMITTED`, `SAFETY_REJECTED`, `SAFETY_APPROVED`, or `PREJUDGED`, and either `requires_prejudging` must be false or the entry must actually be `PREJUDGED` — anything else is `ERR_INVALID_STATE`. Safety next: the entry's `safety_status` must be `APPROVED`, otherwise `ERR_SAFETY_NOT_APPROVED`."

    A SAFETY_REJECTED entry passes the state tier but is stopped at the
    safety tier.

    Design: Difficulty/cross_entity_state_dependency/stage_queue_blocked_until_entry_safety_approved
    """
    contest, category, pairs = _judging_contest_with_entries(
        [{"approve": False, "consent": True}]
    )
    _, entry = pairs[0]
    fx.reject_entry_safety(entry["id"], ["FOAM_WEAPON"])

    resp = api.create_performance_slot(
        create_performance_slot_payload(entry["id"], 1), STAGE
    )
    validate_error(resp, ApiErrorId.ERR_SAFETY_NOT_APPROVED)
    assert fx.get_entry(entry["id"])["status"] == "SAFETY_REJECTED"


# ---------------------------------------------------------------------------
# Priority pair: safety beats sequence conflict
# ---------------------------------------------------------------------------

def test_safety_error_beats_sequence_conflict(api):
    """PRD §2.8: "then business-safety gates (`ERR_PROP_BANNED`, `ERR_SAFETY_NOT_APPROVED`, `ERR_CONSENT_REQUIRED`)"
    PRD §3.6: "Safety next: the entry's `safety_status` must be `APPROVED`, otherwise `ERR_SAFETY_NOT_APPROVED`. Consent next: because every stage performance is carried on the livestream, the entry's contestant must hold a consent item with `scope` `LIVESTREAM` and `status` `GRANTED`, otherwise `ERR_CONSENT_REQUIRED`. Constraint last: the requested `sequence_number` must be unique among the contest's slots currently in `QUEUED` or `ON_STAGE`, and the entry must not already occupy another `QUEUED` or `ON_STAGE` slot — a violation is `ERR_SEQUENCE_CONFLICT`."

    Queueing a safety-PENDING entry on an already-taken sequence number
    surfaces the safety error, not the sequence conflict.

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_sequence_conflict_on_stage_queue
    """
    contest, category, pairs = _judging_contest_with_entries(
        [{"approve": True, "consent": True},
         {"approve": False, "consent": True}]
    )
    _, e1 = pairs[0]
    _, e2 = pairs[1]
    fx.stage_entry(e1["id"], 1)

    resp = api.create_performance_slot(
        create_performance_slot_payload(e2["id"], 1, duration_seconds=60), STAGE
    )
    validate_error(resp, ApiErrorId.ERR_SAFETY_NOT_APPROVED)


def test_safety_error_beats_sequence_conflict_after_rejection(api):
    """PRD §3.6: "Safety next: the entry's `safety_status` must be `APPROVED`, otherwise `ERR_SAFETY_NOT_APPROVED`. Consent next: because every stage performance is carried on the livestream, the entry's contestant must hold a consent item with `scope` `LIVESTREAM` and `status` `GRANTED`, otherwise `ERR_CONSENT_REQUIRED`. Constraint last: the requested `sequence_number` must be unique among the contest's slots currently in `QUEUED` or `ON_STAGE`, and the entry must not already occupy another `QUEUED` or `ON_STAGE` slot — a violation is `ERR_SEQUENCE_CONFLICT`."

    Same priority pair with the entry in SAFETY_REJECTED instead of
    SUBMITTED: the safety gate still wins over the taken sequence number.

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_sequence_conflict_on_stage_queue
    """
    contest, category, pairs = _judging_contest_with_entries(
        [{"approve": True, "consent": True},
         {"approve": False, "consent": True}]
    )
    _, e1 = pairs[0]
    _, e2 = pairs[1]
    fx.reject_entry_safety(e2["id"], ["FOAM_WEAPON"])
    fx.stage_entry(e1["id"], 1)

    resp = api.create_performance_slot(
        create_performance_slot_payload(e2["id"], 1, duration_seconds=60), STAGE
    )
    validate_error(resp, ApiErrorId.ERR_SAFETY_NOT_APPROVED)


# ---------------------------------------------------------------------------
# Other queue gates
# ---------------------------------------------------------------------------

def test_requires_prejudging_gate_on_stage_queue(api):
    """PRD §3.6: "State first: the entry must be in `SUBMITTED`, `SAFETY_REJECTED`, `SAFETY_APPROVED`, or `PREJUDGED`, and either `requires_prejudging` must be false or the entry must actually be `PREJUDGED` — anything else is `ERR_INVALID_STATE`."

    An entry with requires_prejudging == true cannot queue from
    SAFETY_APPROVED; it must complete pre-judging first.

    Design: Corner/state_machines/requires_prejudging_gate_on_stage_queue
    """
    contest, category, pairs = _judging_contest_with_entries(
        [{"requires_prejudging": True, "approve": True, "consent": True}]
    )
    _, entry = pairs[0]
    resp = api.create_performance_slot(
        create_performance_slot_payload(entry["id"], 1), STAGE
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert fx.get_entry(entry["id"])["status"] == "SAFETY_APPROVED"


def test_consent_required_on_stage_queue(api):
    """PRD §3.6: "Consent next: because every stage performance is carried on the livestream, the entry's contestant must hold a consent item with `scope` `LIVESTREAM` and `status` `GRANTED`, otherwise `ERR_CONSENT_REQUIRED`."

    Design: Corner/state_machines/consent_required_on_stage_queue
    """
    contest, category, pairs = _judging_contest_with_entries(
        [{"approve": True, "consent": False}]
    )
    contestant, entry = pairs[0]

    resp_blocked = api.create_performance_slot(
        create_performance_slot_payload(entry["id"], 1), STAGE
    )
    validate_error(resp_blocked, ApiErrorId.ERR_CONSENT_REQUIRED)

    fx.grant_livestream_consent(contestant)
    resp_ok = api.create_performance_slot(
        create_performance_slot_payload(entry["id"], 1), STAGE
    )
    slot = validate_success(resp_ok, 201)
    assert slot["status"] == "QUEUED"


def test_consent_revoke_regrant_cycle_rechecks_at_advance(api):
    """PRD §3.2: "The owning `Contestant` grants or revokes one scope at a time by posting a `scope` together with a `granted` boolean; this is a cyclic upsert that creates the item if absent, flips its `status` if present, and bumps the contestant's `version`."
    PRD §3.6: "Advancing with `to` set to `ON_STAGE` from `QUEUED` requires that no other slot of the contest is currently `ON_STAGE`, that the entry is `STAGE_QUEUED` with `safety_status` `APPROVED` (else `ERR_SAFETY_NOT_APPROVED`), and that the contestant's `LIVESTREAM` consent is `GRANTED` (else `ERR_CONSENT_REQUIRED`)."

    Consent is re-checked at advance time, not only at queue time.

    Design: Corner/state_machines/consent_revoke_regrant_cycle
    """
    contest, category, pairs = _judging_contest_with_entries(
        [{"approve": True, "consent": True}]
    )
    contestant, entry = pairs[0]
    slot = fx.stage_entry(entry["id"], 1)

    headers = fx.contestant_headers(contestant)
    validate_success(
        api.set_consent(contestant["id"],
                        {"scope": "LIVESTREAM", "granted": False}, headers)
    )
    resp_blocked = api.advance_performance_slot(slot["id"], {"to": "ON_STAGE"}, STAGE)
    validate_error(resp_blocked, ApiErrorId.ERR_CONSENT_REQUIRED)

    validate_success(
        api.set_consent(contestant["id"],
                        {"scope": "LIVESTREAM", "granted": True}, headers)
    )
    resp_ok = api.advance_performance_slot(slot["id"], {"to": "ON_STAGE"}, STAGE)
    advanced = validate_success(resp_ok, 200)
    assert advanced["status"] == "ON_STAGE"


def test_advance_skipping_on_stage_rejected(api):
    """PRD §3.6: "The stage walk itself is driven by posting a `to` field naming the desired next state. Advancing with `to` set to `ON_STAGE` from `QUEUED` requires that no other slot of the contest is currently `ON_STAGE`, that the entry is `STAGE_QUEUED` with `safety_status` `APPROVED` (else `ERR_SAFETY_NOT_APPROVED`), and that the contestant's `LIVESTREAM` consent is `GRANTED` (else `ERR_CONSENT_REQUIRED`). Advancing with `to` set to `COMPLETED` from `ON_STAGE` then moves the entry from `STAGE_QUEUED` to `PERFORMED`."

    QUEUED -> COMPLETED skips ON_STAGE and is rejected; the slot stays QUEUED.

    Design: Corner/state_machines/advance_skipping_on_stage_returns_invalid_state
    """
    contest, category, pairs = _judging_contest_with_entries(
        [{"approve": True, "consent": True}]
    )
    _, entry = pairs[0]
    slot = fx.stage_entry(entry["id"], 1)

    resp = api.advance_performance_slot(slot["id"], {"to": "COMPLETED"}, STAGE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert fx.get_performance_slot(slot["id"])["status"] == "QUEUED"


def test_sequence_conflict_on_duplicate_order_number(api):
    """PRD §3.6: "Constraint last: the requested `sequence_number` must be unique among the contest's slots currently in `QUEUED` or `ON_STAGE`, and the entry must not already occupy another `QUEUED` or `ON_STAGE` slot — a violation is `ERR_SEQUENCE_CONFLICT`."

    Design: Corner/validations/sequence_conflict_on_duplicate_order_number
    """
    contest, category, pairs = _judging_contest_with_entries(
        [{"approve": True, "consent": True},
         {"approve": True, "consent": True}]
    )
    _, e1 = pairs[0]
    _, e2 = pairs[1]
    fx.stage_entry(e1["id"], 1)

    resp_conflict = api.create_performance_slot(
        create_performance_slot_payload(e2["id"], 1, duration_seconds=90), STAGE
    )
    validate_error(resp_conflict, ApiErrorId.ERR_SEQUENCE_CONFLICT)

    resp_ok = api.create_performance_slot(
        create_performance_slot_payload(e2["id"], 2, duration_seconds=90), STAGE
    )
    slot = validate_success(resp_ok, 201)
    assert slot["status"] == "QUEUED"
    assert slot["sequence_number"] == 2


# ---------------------------------------------------------------------------
# Withdraw cascade: slot skip + stage sequence compaction
# ---------------------------------------------------------------------------

def _three_queued_entries():
    contest, category, pairs = _judging_contest_with_entries(
        [{"approve": True, "consent": True}] * 3
    )
    slots = [fx.stage_entry(entry["id"], i + 1) for i, (_, entry) in enumerate(pairs)]
    return contest, category, pairs, slots


def test_withdraw_skips_slot_and_compacts_sequence(api):
    """PRD §3.3: "Withdrawal cascades: any `BOOKED` pre-judging slot of the entry returns to `OPEN` with `booked_entry_id` cleared, and any `QUEUED` or `ON_STAGE` stage slot of the entry is marked `SKIPPED`, after which the remaining `QUEUED` stage slots of the contest are resequenced per the compaction rule in §3.6."
    PRD §3.6: "Every skip triggers stage sequence compaction across the contest: the remaining `QUEUED` slots are ordered by `sequence_number` ascending with `created_at` ascending as the tie-break (never `id`), and `sequence_number` is reassigned 1 through N gap-free in that order, each reassignment bumping the slot's `version`."

    Design: Difficulty/transitive_cascade/withdraw_cascade_slot_skip_resequence
    """
    _, _, pairs, slots = _three_queued_entries()
    (c1, e1), (c2, e2), (c3, e3) = pairs
    ps1, ps2, ps3 = slots

    withdrawn = validate_success(
        api.withdraw_entry(e2["id"], fx.contestant_headers(c2))
    )
    assert withdrawn["status"] == "WITHDRAWN"

    slot2 = fx.get_performance_slot(ps2["id"])
    assert slot2["status"] == "SKIPPED"

    slot1 = fx.get_performance_slot(ps1["id"])
    slot3 = fx.get_performance_slot(ps3["id"])
    assert slot1["sequence_number"] == 1
    assert slot3["sequence_number"] == 2, (
        f"Compaction should renumber 3 -> 2, got {slot3['sequence_number']}"
    )
    # Survivors remain queued.
    assert slot1["status"] == "QUEUED"
    assert slot3["status"] == "QUEUED"


def test_withdraw_releases_booked_prejudging_slot(api):
    """PRD §3.3: "Withdrawal cascades: any `BOOKED` pre-judging slot of the entry returns to `OPEN` with `booked_entry_id` cleared, and any `QUEUED` or `ON_STAGE` stage slot of the entry is marked `SKIPPED`, after which the remaining `QUEUED` stage slots of the contest are resequenced per the compaction rule in §3.6."

    The other cascade arm: a withdrawn PREJUDGED-track entry releases its
    BOOKED craftsmanship slot.

    Design: Difficulty/transitive_cascade/withdraw_cascade_slot_skip_resequence
    """
    contest = fx.create_contest()
    category = fx.create_category(contest["id"])
    fx.open_registration(contest["id"])
    contestant = fx.create_contestant()
    entry = fx.create_entry(contestant, category["id"], title="E1",
                            requires_prejudging=True)
    fx.approve_entry_safety(entry["id"])
    slot = fx.create_prejudging_slot(category["id"], panel_name="P1")
    fx.book_slot(slot["id"], contestant, entry["id"])

    withdrawn = validate_success(
        api.withdraw_entry(entry["id"], fx.contestant_headers(contestant))
    )
    assert withdrawn["status"] == "WITHDRAWN"

    slot_after = fx.get_prejudging_slot(slot["id"])
    assert slot_after["status"] == "OPEN"
    assert slot_after["booked_entry_id"] is None
