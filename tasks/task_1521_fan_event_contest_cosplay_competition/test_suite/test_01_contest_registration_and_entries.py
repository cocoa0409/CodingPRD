"""Contest lifecycle, registration rules, entry creation constraints, and
the safety reject/resubmit cycle.

Covers: contest initial state and transition gating, registration window,
entry defaults, prop screening, capacity and duplicate-entry constraints,
junior-division age boundary, validation-vs-state priority, and the cyclic
entry safety workflow.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_budget_invariant,
    assert_category,
    assert_contest_event,
    assert_entry,
    get_entry,
    make_contestant_headers,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.constants import CONTEST_END, CONTEST_START
from test_helpers.factories import (
    create_category_payload,
    create_contest_event_payload,
    create_entry_payload,
)
from test_helpers.test_users import TEST_USERS

LEAD = TEST_USERS["contest_lead_headers"]


# ---------------------------------------------------------------------------
# Contest lifecycle
# ---------------------------------------------------------------------------

def test_contest_starts_in_setup(api):
    """PRD §3.1: "The new contest starts in `SETUP` status."
    PRD §3.1: "A `ContestLead` begins by creating a `ContestEvent` with a human-readable `name`, a contest window bracketed by `start_at` and `end_at` (both ISO 8601 UTC, with `end_at` strictly after `start_at`), a total `prize_budget_cents` that must be at least zero, and an optional `max_entries_per_contestant` defaulting to 2"

    Design: Corner/state_machines/contest_creation_initial_state_and_open_requires_category
    """
    contest = fx.create_contest()
    assert_contest_event(contest)
    assert contest["status"] == "SETUP", f"Expected SETUP, got {contest['status']}"


def test_open_registration_requires_a_category(api):
    """PRD §3.1: "The precondition is that at least one category exists for the contest, otherwise the request is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/contest_creation_initial_state_and_open_requires_category
    """
    contest = fx.create_contest()
    resp = api.transition_contest_event(contest["id"], {"to": "REGISTRATION_OPEN"}, LEAD)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert fx.get_contest(contest["id"])["status"] == "SETUP"


def test_contest_transition_phase_skip_rejected(api):
    """PRD §3.1: "judging begins with a transition whose `to` is `JUDGING` from `REGISTRATION_CLOSED` which flips every `OPEN` category of the contest to `SCORING`, again bumping each category's `version`."

    A SETUP -> JUDGING skip is not a declared edge and is rejected.

    Design: Corner/state_machines/contest_transition_skip_returns_invalid_state
    """
    contest = fx.create_contest()
    fx.create_category(contest["id"])
    resp = api.transition_contest_event(contest["id"], {"to": "JUDGING"}, LEAD)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert fx.get_contest(contest["id"])["status"] == "SETUP"


# ---------------------------------------------------------------------------
# Creation defaults and computed fields
# ---------------------------------------------------------------------------

def test_creation_defaults_and_computed_fields(api):
    """PRD §3.1: "an optional `max_entries_per_contestant` defaulting to 2 that caps how many non-terminal entries a single contestant may hold in this contest (and must be at least 1)."
    PRD §3.2: "an optional `accessibility_needs` list (free-form values such as `WHEELCHAIR` or `ASL_INTERPRETER`, defaulting to empty)"
    PRD §3.3: "an optional `requires_prejudging` flag (default true) that declares whether the craftsmanship panel must see the build before the stage walk"
    PRD §3.3: "A fresh entry lands in `SUBMITTED` with `safety_status` set to `PENDING` and `rejected_props` empty."
    PRD §3.1: "The invariant `prize_budget_cents == budget_reserved_cents + budget_available_cents` holds at all times."

    Design: Corner/entities/entity_creation_defaults_and_system_fields
    """
    contest = fx.create_contest(prize_budget_cents=50000)
    category = fx.create_category(contest["id"])
    fx.open_registration(contest["id"])
    contestant = fx.create_contestant()
    entry_resp = api.create_entry(
        {"contestant_id": contestant["id"], "category_id": category["id"],
         "title": "E1", "prop_declarations": []},
        fx.contestant_headers(contestant),
    )
    entry = validate_success(entry_resp, 201)
    assert_entry(entry)

    contest_after = fx.get_contest(contest["id"])
    assert contest_after["max_entries_per_contestant"] == 2
    assert contest_after["budget_reserved_cents"] == 0
    assert contest_after["budget_available_cents"] == 50000
    assert_budget_invariant(contest_after)

    fetched = validate_success(
        api.get_contestant(contestant["id"], fx.contestant_headers(contestant))
    )
    assert fetched["accessibility_needs"] == []

    assert entry["requires_prejudging"] is True
    assert entry["status"] == "SUBMITTED"
    assert entry["safety_status"] == "PENDING"
    assert entry["rejected_props"] == []


# ---------------------------------------------------------------------------
# Entry creation: validation, window, screening, capacity, duplicates
# ---------------------------------------------------------------------------

def test_entry_create_missing_title_returns_400(api):
    """PRD §2.8: "then field-shape validation such as missing fields, bad types, bad enums, and out-of-range scores (`ERR_VALIDATION`)"
    PRD §3.3: "A contestant registers an `Entry` by posting their own `contestant_id`, the target `category_id`, a `title`, a `prop_declarations` list describing the prop types involved"

    Design: Corner/entities/entry_create_missing_required_title_returns_400
    """
    contest = fx.create_contest()
    category = fx.create_category(contest["id"])
    fx.open_registration(contest["id"])
    contestant = fx.create_contestant()
    resp = api.create_entry(
        {"contestant_id": contestant["id"], "category_id": category["id"],
         "prop_declarations": []},
        fx.contestant_headers(contestant),
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_entry_create_after_registration_closed_rejected(api):
    """PRD §3.3: "entry creation is permitted only while the parent contest is `REGISTRATION_OPEN` and the target category is `OPEN`, otherwise `ERR_REGISTRATION_NOT_OPEN`."

    Design: Corner/state_machines/entry_create_when_registration_closed
    """
    contest = fx.create_contest()
    category = fx.create_category(contest["id"])
    fx.open_registration(contest["id"])
    fx.transition_contest(contest["id"], "REGISTRATION_CLOSED")
    contestant = fx.create_contestant()
    resp = api.create_entry(
        create_entry_payload(contestant["id"], category["id"]),
        fx.contestant_headers(contestant),
    )
    validate_error(resp, ApiErrorId.ERR_REGISTRATION_NOT_OPEN)


def test_banned_prop_declaration_rejected(api):
    """PRD §3.3: "First, `prop_declarations` must not include any banned prop type — `LIVE_STEEL`, `FIREARM`, or `PYROTECHNICS` — or the request is rejected with `ERR_PROP_BANNED` (HTTP 422)."

    Design: Corner/validations/banned_prop_declaration_returns_422
    """
    contest = fx.create_contest()
    category = fx.create_category(contest["id"])
    fx.open_registration(contest["id"])
    contestant = fx.create_contestant()
    resp = api.create_entry(
        create_entry_payload(contestant["id"], category["id"],
                             title="Sharp", prop_declarations=["LIVE_STEEL"]),
        fx.contestant_headers(contestant),
    )
    validate_error(resp, ApiErrorId.ERR_PROP_BANNED)
    # No entry persisted for that contestant.
    data = validate_success(
        api.list_entries(LEAD, params={"contestant_id": contestant["id"]})
    )
    assert isinstance(data, list) and len(data) == 0


def test_category_full_at_quota_boundary(api):
    """PRD §3.3: "Second, capacity: if the category's current `entry_count` already equals its `max_entries`, the request is rejected with `ERR_CATEGORY_FULL` (the boundary is inclusive — exactly at quota rejects)."

    Design: Corner/validations/category_full_at_quota_boundary
    """
    contest = fx.create_contest()
    category = fx.create_category(contest["id"], name="Tiny", max_entries=1,
                                  skill_division="NOVICE")
    fx.open_registration(contest["id"])
    c1 = fx.create_contestant()
    c2 = fx.create_contestant()
    first = fx.create_entry(c1, category["id"], title="E1")
    assert first["status"] == "SUBMITTED"
    resp = api.create_entry(
        create_entry_payload(c2["id"], category["id"], title="E2"),
        fx.contestant_headers(c2),
    )
    validate_error(resp, ApiErrorId.ERR_CATEGORY_FULL)


def test_duplicate_entry_same_category_rejected(api):
    """PRD §3.3: "Third, per-contestant limits: if the contestant already holds a non-terminal entry in the same category, or already holds `max_entries_per_contestant` non-terminal entries anywhere in the contest, the request is rejected with `ERR_DUPLICATE_ENTRY`."

    Design: Corner/validations/duplicate_entry_same_category_returns_409
    """
    contest = fx.create_contest()
    category = fx.create_category(contest["id"])
    fx.open_registration(contest["id"])
    contestant = fx.create_contestant()
    fx.create_entry(contestant, category["id"], title="E1")
    resp = api.create_entry(
        create_entry_payload(contestant["id"], category["id"], title="E1-again"),
        fx.contestant_headers(contestant),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ENTRY)


def test_entries_list_filters_by_contestant(api):
    """PRD §4: "| GET | `/entries` | List entries with optional `category_id`, `contestant_id`, `contest_id`, `status` filters | ContestLead, Treasurer, StageManager, Judge, SafetyOfficer, Contestant |"

    The `contestant_id` filter returns exactly that contestant's entries.

    Design: Corner/endpoints/fk_reverse_entries_filtered_by_contestant
    """
    contest = fx.create_contest()
    category = fx.create_category(contest["id"])
    fx.open_registration(contest["id"])
    c1 = fx.create_contestant()
    c2 = fx.create_contestant()
    fx.create_entry(c1, category["id"], title="E1")
    fx.create_entry(c2, category["id"], title="E2")
    data = validate_success(api.list_entries(LEAD, params={"contestant_id": c2["id"]}))
    assert isinstance(data, list) and len(data) == 1
    assert data[0]["contestant_id"] == c2["id"]
    assert data[0]["title"] == "E2"


# ---------------------------------------------------------------------------
# Purse split (combinatorial formula with pinned rounding order)
# ---------------------------------------------------------------------------

def test_purse_split_remainder_absorbs_rounding(api):
    """PRD §3.1: "Rounding the third rank independently is forbidden — for a purse of 9999 cents the correct split is 5000, 3000, and 1999, not 5000, 3000, and 2000."

    Design: Difficulty/combinatorial_formula/purse_split_remainder_absorbs_rounding
    """
    contest = fx.create_contest()
    resp = api.create_category(
        create_category_payload(contest["id"], name="OddPurse",
                                skill_division="JOURNEYMAN", max_entries=9,
                                prize_purse_cents=9999),
        LEAD,
    )
    category = validate_success(resp, 201)
    assert_category(category)
    assert category["prize_rank1_cents"] == 5000
    assert category["prize_rank2_cents"] == 3000
    assert category["prize_rank3_cents"] == 1999
    total = (category["prize_rank1_cents"] + category["prize_rank2_cents"]
             + category["prize_rank3_cents"])
    assert total == 9999


def test_purse_split_recomputed_on_purse_edit(api):
    """PRD §3.1: "At creation (and again whenever `prize_purse_cents` is edited), the system computes the purse split and stores it as three integer-cent fields."
    PRD §3.1: "`prize_rank3_cents` is the remainder, computed as the purse minus rank 1 minus rank 2 so that rounding drift is absorbed by third place."

    Design: Difficulty/combinatorial_formula/purse_split_remainder_absorbs_rounding
    """
    contest = fx.create_contest()
    category = fx.create_category(contest["id"], prize_purse_cents=10000)
    assert (category["prize_rank1_cents"], category["prize_rank2_cents"],
            category["prize_rank3_cents"]) == (5000, 3000, 2000)
    resp = api.update_category(
        category["id"],
        {"prize_purse_cents": 9999,
         "expected_category_version": category["version"]},
        LEAD,
    )
    updated = validate_success(resp, 200)
    assert (updated["prize_rank1_cents"], updated["prize_rank2_cents"],
            updated["prize_rank3_cents"]) == (5000, 3000, 1999)


# ---------------------------------------------------------------------------
# Junior-division age boundary
# ---------------------------------------------------------------------------

def _junior_contest():
    contest = fx.create_contest()
    category = fx.create_category(contest["id"], name="Youth",
                                  skill_division="JUNIOR")
    fx.open_registration(contest["id"])
    return contest, category


def test_junior_age_boundary_exactly_16_on_contest_date(api):
    """PRD §3.3: "Eligibility requires the age to be strictly less than 16; a contestant whose sixteenth birthday falls on or before the contest date is rejected with `ERR_DIVISION_AGE_INELIGIBLE` (HTTP 422)."
    PRD §3.3: "age is the number of full calendar years between `birth_date` and the date part of the contest's `start_at`, where a birthday falling exactly on the contest date counts as already completed."

    Contest starts 2026-08-15: born 2010-08-15 -> exactly 16 -> rejected;
    born 2010-08-16 -> 15 -> accepted.

    Design: Difficulty/boundary_precision_check/junior_age_exactly_16_on_contest_date
    """
    _, category = _junior_contest()
    c_old = fx.create_contestant(full_name="Exact Sixteen", birth_date="2010-08-15")
    c_young = fx.create_contestant(full_name="Still Fifteen", birth_date="2010-08-16")

    resp_old = api.create_entry(
        create_entry_payload(c_old["id"], category["id"], title="Old"),
        fx.contestant_headers(c_old),
    )
    validate_error(resp_old, ApiErrorId.ERR_DIVISION_AGE_INELIGIBLE)

    resp_young = api.create_entry(
        create_entry_payload(c_young["id"], category["id"], title="Young"),
        fx.contestant_headers(c_young),
    )
    entry = validate_success(resp_young, 201)
    assert entry["status"] == "SUBMITTED"


def test_junior_age_boundary_birthday_one_day_before(api):
    """PRD §3.3: "Eligibility requires the age to be strictly less than 16; a contestant whose sixteenth birthday falls on or before the contest date is rejected with `ERR_DIVISION_AGE_INELIGIBLE` (HTTP 422)."

    Born 2010-08-14 (sixteenth birthday the day before the contest) is age 16
    and rejected; the same over-age contestant may enter a non-JUNIOR division
    because the age check applies only when the category's skill_division is JUNIOR.

    Design: Difficulty/boundary_precision_check/junior_age_exactly_16_on_contest_date
    """
    contest = fx.create_contest()
    junior_cat = fx.create_category(contest["id"], name="Youth",
                                    skill_division="JUNIOR")
    novice_cat = fx.create_category(contest["id"], name="Novice",
                                    skill_division="NOVICE")
    fx.open_registration(contest["id"])

    c_old = fx.create_contestant(full_name="Day Older", birth_date="2010-08-14")
    resp = api.create_entry(
        create_entry_payload(c_old["id"], junior_cat["id"], title="TooOld"),
        fx.contestant_headers(c_old),
    )
    validate_error(resp, ApiErrorId.ERR_DIVISION_AGE_INELIGIBLE)

    resp2 = api.create_entry(
        create_entry_payload(c_old["id"], novice_cat["id"], title="OpenEntry"),
        fx.contestant_headers(c_old),
    )
    entry = validate_success(resp2, 201)
    assert entry["status"] == "SUBMITTED"


# ---------------------------------------------------------------------------
# Priority pair: existence beats state
# ---------------------------------------------------------------------------

def test_entry_create_missing_category_beats_registration_state(api):
    """PRD §2.8: "then path-id and body-foreign-key resolution in left-to-right order (`ERR_NOT_FOUND`), then ownership (`ERR_NOT_OWNER`), then state-machine preconditions and phase gates (`ERR_INVALID_STATE` and the state-specific codes `ERR_REGISTRATION_NOT_OPEN`, `ERR_CATEGORY_NOT_TABULATED`, `ERR_PLACEMENT_NOT_FOUND`)"

    Nonexistent category_id while the contest is still SETUP surfaces the
    existence error, not the registration-window error.

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_state_on_entry_create
    """
    fx.create_contest()  # stays SETUP; registration never opens
    contestant = fx.create_contestant()
    resp = api.create_entry(
        create_entry_payload(contestant["id"], NON_EXISTENT_UUID, title="X"),
        fx.contestant_headers(contestant),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_entry_create_missing_contestant_beats_registration_state(api):
    """PRD §2.8: "then path-id and body-foreign-key resolution in left-to-right order (`ERR_NOT_FOUND`), then ownership (`ERR_NOT_OWNER`), then state-machine preconditions and phase gates (`ERR_INVALID_STATE` and the state-specific codes `ERR_REGISTRATION_NOT_OPEN`, `ERR_CATEGORY_NOT_TABULATED`, `ERR_PLACEMENT_NOT_FOUND`)"

    A nonexistent body contestant_id while the contest is still SETUP also
    surfaces the existence error, not the registration-window error.

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_state_on_entry_create
    """
    contest = fx.create_contest()  # stays SETUP
    category = fx.create_category(contest["id"])
    resp = api.create_entry(
        create_entry_payload(NON_EXISTENT_UUID, category["id"], title="X"),
        make_contestant_headers(NON_EXISTENT_UUID),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


# ---------------------------------------------------------------------------
# Entry safety reject -> resubmit cycle (cyclic state machine)
# ---------------------------------------------------------------------------

def _open_entry(props):
    contest = fx.create_contest()
    category = fx.create_category(contest["id"])
    fx.open_registration(contest["id"])
    contestant = fx.create_contestant()
    entry = fx.create_entry(contestant, category["id"], title="E1",
                            prop_declarations=props)
    return contestant, entry


def test_safety_reject_resubmit_cycle(api):
    """PRD §3.3: "A rejection moves a `SUBMITTED` entry to `SAFETY_REJECTED`, sets `safety_status` to `REJECTED`, and records the request's `rejected_props` list (which may be empty)."
    PRD §3.3: "When a `prop_declarations` change lands on a `SAFETY_REJECTED` entry, the entry cycles back to `SUBMITTED` with `safety_status` reset to `PENDING` and `rejected_props` cleared"
    PRD §3.3: "An approval of a `SUBMITTED` entry moves it to `SAFETY_APPROVED`, sets `safety_status` to `APPROVED`, and clears `rejected_props` to empty."
    PRD §2.4: "`version` is an integer that increments on every mutation."

    Design: Difficulty/non_linear_state_machine/entry_safety_reject_resubmit_cycle
    """
    contestant, entry = _open_entry(["FOAM_WEAPON"])
    headers = fx.contestant_headers(contestant)
    v0 = entry["version"]

    rejected = fx.reject_entry_safety(entry["id"], ["FOAM_WEAPON"])
    assert rejected["status"] == "SAFETY_REJECTED"
    assert rejected["safety_status"] == "REJECTED"
    assert rejected["rejected_props"] == ["FOAM_WEAPON"]
    assert rejected["version"] == v0 + 1

    resp = api.update_entry(
        entry["id"],
        {"prop_declarations": ["ARMOR"],
         "expected_entry_version": rejected["version"]},
        headers,
    )
    resubmitted = validate_success(resp, 200)
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["safety_status"] == "PENDING"
    assert resubmitted["rejected_props"] == []
    assert resubmitted["version"] == rejected["version"] + 1

    approved = fx.approve_entry_safety(entry["id"])
    assert approved["status"] == "SAFETY_APPROVED"
    assert approved["safety_status"] == "APPROVED"
    assert approved["rejected_props"] == []
    assert approved["version"] == resubmitted["version"] + 1


def test_safety_rejected_edit_without_prop_change_keeps_status(api):
    """PRD §3.3: "an edit that does not change `prop_declarations` leaves the status alone."
    PRD §3.3: "A contestant whose entry was safety-rejected may edit the entry — changing `title`, `character_source`, or `prop_declarations` — while it is in `SUBMITTED` or `SAFETY_REJECTED`."

    Design: Difficulty/non_linear_state_machine/entry_safety_reject_resubmit_cycle
    """
    contestant, entry = _open_entry(["FOAM_WEAPON"])
    headers = fx.contestant_headers(contestant)
    rejected = fx.reject_entry_safety(entry["id"], ["FOAM_WEAPON"])

    resp = api.update_entry(
        entry["id"],
        {"title": "Renamed",
         "expected_entry_version": rejected["version"]},
        headers,
    )
    updated = validate_success(resp, 200)
    assert updated["title"] == "Renamed"
    assert updated["status"] == "SAFETY_REJECTED"
    assert updated["safety_status"] == "REJECTED"
    assert updated["rejected_props"] == ["FOAM_WEAPON"]

    # The cycle is repeatable: a prop change still resubmits afterwards.
    resp2 = api.update_entry(
        entry["id"],
        {"prop_declarations": ["ARMOR"],
         "expected_entry_version": updated["version"]},
        headers,
    )
    resubmitted = validate_success(resp2, 200)
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["safety_status"] == "PENDING"
