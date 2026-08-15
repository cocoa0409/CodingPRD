"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server). Setup calls
use the lenient get_success_data() so a failure surfaces as a clear
"Setup failed" style error rather than a confusing assertion deep in a test.

Ownership threading: Contestant and Judge are entity-backed roles, so every
ownership-gated call passes make_contestant_headers(entity["id"]) /
make_judge_headers(entity["id"]) — never the shared TEST_USERS fallback.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    BOOKING_END,
    BOOKING_START,
    CONTEST_END,
    CONTEST_START,
    SLOT_END,
    SLOT_START,
)
from .factories import (
    create_category_payload,
    create_contest_event_payload,
    create_contestant_payload,
    create_entry_payload,
    create_green_room_booking_payload,
    create_judge_payload,
    create_performance_slot_payload,
    create_prejudging_slot_payload,
    create_prize_award_payload,
    create_scoresheet_payload,
)
from .test_users import (
    TEST_USERS,
    make_contestant_headers,
    make_judge_headers,
    make_treasurer_headers,
)

LEAD = TEST_USERS["contest_lead_headers"]
ANON = TEST_USERS["anonymous_headers"]
SAFETY = TEST_USERS["safety_officer_headers"]
STAGE = TEST_USERS["stage_manager_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation and state progression
# ---------------------------------------------------------------------------

def create_contest(prize_budget_cents=50000, name=None, **overrides) -> dict:
    """Create a ContestEvent (starts in SETUP)."""
    payload = create_contest_event_payload(
        prize_budget_cents=prize_budget_cents, **overrides
    )
    if name is not None:
        payload["name"] = name
    return get_success_data(api_client.create_contest_event(payload, LEAD))


def create_category(contest_id, name="Armor", skill_division="MASTERS",
                    max_entries=5, tabulation_method="WEIGHTED_MEAN",
                    prize_purse_cents=30000, **overrides) -> dict:
    """Create a Category (starts in DRAFT); the purse split is computed at creation."""
    payload = create_category_payload(
        contest_id,
        name=name,
        skill_division=skill_division,
        max_entries=max_entries,
        tabulation_method=tabulation_method,
        prize_purse_cents=prize_purse_cents,
        **overrides,
    )
    return get_success_data(api_client.create_category(payload, LEAD))


def transition_contest(contest_id, to) -> dict:
    """Drive the contest state machine; returns the updated ContestEvent."""
    return get_success_data(
        api_client.transition_contest_event(contest_id, {"to": to}, LEAD)
    )


def open_registration(contest_id) -> dict:
    """SETUP -> REGISTRATION_OPEN (flips every DRAFT category to OPEN)."""
    return transition_contest(contest_id, "REGISTRATION_OPEN")


def advance_contest_to_judging(contest_id) -> dict:
    """REGISTRATION_OPEN -> REGISTRATION_CLOSED -> JUDGING
    (flips every OPEN category to SCORING)."""
    transition_contest(contest_id, "REGISTRATION_CLOSED")
    return transition_contest(contest_id, "JUDGING")


def create_contestant(full_name=None, birth_date="1990-01-01", **overrides) -> dict:
    """Self-register a contestant profile via the Anonymous endpoint."""
    payload = create_contestant_payload(birth_date=birth_date, **overrides)
    if full_name is not None:
        payload["full_name"] = full_name
    return get_success_data(api_client.create_contestant(payload, ANON))


def contestant_headers(contestant) -> dict:
    """Entity-backed headers for the given Contestant resource."""
    return make_contestant_headers(contestant["id"])


def grant_livestream_consent(contestant) -> dict:
    """Grant the LIVESTREAM consent scope; returns the updated Contestant."""
    return get_success_data(
        api_client.set_consent(
            contestant["id"],
            {"scope": "LIVESTREAM", "granted": True},
            contestant_headers(contestant),
        )
    )


def create_entry(contestant, category_id, title="E1", prop_declarations=None,
                 requires_prejudging=False, **overrides) -> dict:
    """Register an entry as its owning contestant (starts SUBMITTED, safety PENDING)."""
    payload = create_entry_payload(
        contestant["id"],
        category_id,
        title=title,
        prop_declarations=[] if prop_declarations is None else prop_declarations,
        requires_prejudging=requires_prejudging,
        **overrides,
    )
    return get_success_data(
        api_client.create_entry(payload, contestant_headers(contestant))
    )


def approve_entry_safety(entry_id) -> dict:
    """SafetyOfficer verdict APPROVED: SUBMITTED -> SAFETY_APPROVED."""
    return get_success_data(
        api_client.safety_check_entry(entry_id, {"verdict": "APPROVED"}, SAFETY)
    )


def reject_entry_safety(entry_id, rejected_props=None) -> dict:
    """SafetyOfficer verdict REJECTED: entry -> SAFETY_REJECTED."""
    payload = {"verdict": "REJECTED", "rejected_props": rejected_props or []}
    return get_success_data(api_client.safety_check_entry(entry_id, payload, SAFETY))


def create_judge(contest_id, category_ids, display_name="J1",
                 linked_contestant_id=None, **overrides) -> dict:
    """Onboard a judge onto a contest panel."""
    payload = create_judge_payload(
        contest_id, category_ids, display_name=display_name,
        linked_contestant_id=linked_contestant_id, **overrides,
    )
    return get_success_data(api_client.create_judge(payload, LEAD))


def judge_headers(judge) -> dict:
    """Entity-backed headers for the given Judge resource."""
    return make_judge_headers(judge["id"])


# ---------------------------------------------------------------------------
# Tier 2: pre-judging slots
# ---------------------------------------------------------------------------

def create_prejudging_slot(category_id, panel_name="P1", start_at=SLOT_START,
                           end_at=SLOT_END, **overrides) -> dict:
    """Define an OPEN craftsmanship-review slot."""
    payload = create_prejudging_slot_payload(
        category_id, panel_name=panel_name, start_at=start_at, end_at=end_at,
        **overrides,
    )
    return get_success_data(api_client.create_prejudging_slot(payload, LEAD))


def book_slot(slot_id, contestant, entry_id) -> dict:
    """Book an OPEN slot for the contestant's own SAFETY_APPROVED entry."""
    return get_success_data(
        api_client.book_prejudging_slot(
            slot_id, {"entry_id": entry_id}, contestant_headers(contestant)
        )
    )


# ---------------------------------------------------------------------------
# Tier 3: stage walk lifecycle
# ---------------------------------------------------------------------------

def stage_entry(entry_id, sequence_number, duration_seconds=120, **overrides) -> dict:
    """Queue an entry onto the stage order (entry -> STAGE_QUEUED)."""
    payload = create_performance_slot_payload(
        entry_id, sequence_number, duration_seconds=duration_seconds, **overrides
    )
    return get_success_data(api_client.create_performance_slot(payload, STAGE))


def advance_slot(slot_id, to) -> dict:
    """Advance the stage walk: QUEUED -> ON_STAGE -> COMPLETED, or -> SKIPPED."""
    return get_success_data(
        api_client.advance_performance_slot(slot_id, {"to": to}, STAGE)
    )


def perform_entry(entry_id, sequence_number, duration_seconds=120) -> dict:
    """Queue + ON_STAGE + COMPLETED: the entry lands in PERFORMED.
    Returns the COMPLETED PerformanceSlot."""
    slot = stage_entry(entry_id, sequence_number, duration_seconds=duration_seconds)
    advance_slot(slot["id"], "ON_STAGE")
    return advance_slot(slot["id"], "COMPLETED")


# ---------------------------------------------------------------------------
# Tier 3: scoring lifecycle
# ---------------------------------------------------------------------------

def submit_sheet(entry_id, judge, craftsmanship=8, accuracy=8, presentation=8,
                 phase="STAGE") -> dict:
    """Create + submit a scoresheet as its owning judge; returns SUBMITTED sheet."""
    payload = create_scoresheet_payload(
        entry_id, phase=phase, craftsmanship=craftsmanship,
        accuracy=accuracy, presentation=presentation,
    )
    sheet = get_success_data(
        api_client.create_scoresheet(payload, judge_headers(judge))
    )
    return get_success_data(api_client.submit_scoresheet(sheet["id"], judge_headers(judge)))


def lock_category_scoresheets(category_id) -> int:
    """Bulk-lock all SUBMITTED sheets of the category; returns locked_count."""
    data = get_success_data(api_client.lock_scoresheets(category_id, LEAD))
    return data["locked_count"]


def tabulate_category(category_id) -> dict:
    """SCORING -> TABULATED; returns the tabulate response data."""
    return get_success_data(api_client.tabulate_category(category_id, LEAD))


# ---------------------------------------------------------------------------
# Tier 4: full scored-contest scenarios
# ---------------------------------------------------------------------------

def setup_scored_contest(category_specs, prize_budget_cents=100000,
                         lock=True, tabulate=False) -> dict:
    """Build a contest in JUDGING with PERFORMED entries and submitted sheets.

    category_specs: list of dicts, each with category fields plus an
        "entries" list. Each entry spec takes:
            title, requires_prejudging (default False), prop_declarations,
            birth_date, phase (default "STAGE"),
            sheets: list of (craftsmanship, accuracy, presentation) triples —
                    one judge per triple is created (judges are pooled across
                    all categories of the contest).
    lock: bulk-lock each category's submitted sheets.
    tabulate: tabulate each category after locking.

    Returns {contest, categories, contestants, entries, judges, sheets, performance_slots}.
    """
    contest = create_contest(prize_budget_cents=prize_budget_cents)
    categories = [
        create_category(
            contest["id"],
            name=spec.get("name", f"Cat{i + 1}"),
            skill_division=spec.get("skill_division", "MASTERS"),
            max_entries=spec.get("max_entries", 9),
            tabulation_method=spec.get("tabulation_method", "WEIGHTED_MEAN"),
            prize_purse_cents=spec.get("prize_purse_cents", 30000),
        )
        for i, spec in enumerate(category_specs)
    ]
    open_registration(contest["id"])

    contestants, entries = [], []
    for spec, category in zip(category_specs, categories):
        cat_contestants, cat_entries = [], []
        for j, espec in enumerate(spec.get("entries", [])):
            contestant = create_contestant(
                full_name=espec.get("full_name", f"C {len(contestants)}{j}"),
                birth_date=espec.get("birth_date", "1990-01-01"),
            )
            entry = create_entry(
                contestant,
                category["id"],
                title=espec.get("title", f"E{j + 1}"),
                prop_declarations=espec.get("prop_declarations", []),
                requires_prejudging=espec.get("requires_prejudging", False),
            )
            approve_entry_safety(entry["id"])
            grant_livestream_consent(contestant)
            cat_contestants.append(contestant)
            cat_entries.append(entry)
        contestants.append(cat_contestants)
        entries.append(cat_entries)

    advance_contest_to_judging(contest["id"])

    category_ids = [c["id"] for c in categories]
    max_sheets = max(
        (len(espec.get("sheets", [])) for spec in category_specs
         for espec in spec.get("entries", [])),
        default=0,
    )
    judges = [
        create_judge(contest["id"], category_ids, display_name=f"J{i + 1}")
        for i in range(max_sheets)
    ]

    performance_slots, sheets = [], []
    seq = 1
    for spec, cat_entries in zip(category_specs, entries):
        slots_for_cat, sheets_for_cat = [], []
        for espec, entry in zip(spec.get("entries", []), cat_entries):
            slots_for_cat.append(perform_entry(entry["id"], seq))
            seq += 1
            entry_sheets = []
            for k, (c, a, p) in enumerate(espec.get("sheets", [])):
                entry_sheets.append(
                    submit_sheet(
                        entry["id"], judges[k], craftsmanship=c, accuracy=a,
                        presentation=p, phase=espec.get("phase", "STAGE"),
                    )
                )
            sheets_for_cat.append(entry_sheets)
        performance_slots.append(slots_for_cat)
        sheets.append(sheets_for_cat)

    if lock:
        for category in categories:
            lock_category_scoresheets(category["id"])
        # The bulk lock mutates every SUBMITTED sheet to LOCKED server-side;
        # refresh the snapshots so the returned structure reflects the
        # post-lock state rather than the submit-time one.
        sheets = [
            [
                [get_scoresheet(sheet["id"]) for sheet in entry_sheets]
                for entry_sheets in cat_sheets
            ]
            for cat_sheets in sheets
        ]
    if tabulate:
        for category in categories:
            tabulate_category(category["id"])

    return {
        "contest": contest,
        "categories": categories,
        "contestants": contestants,
        "entries": entries,
        "judges": judges,
        "sheets": sheets,
        "performance_slots": performance_slots,
    }


def setup_tabulated_category(prize_purse_cents=100000, prize_budget_cents=100000,
                             entry_sheets=None, tabulation_method="WEIGHTED_MEAN",
                             skill_division="MASTERS", max_entries=5) -> dict:
    """Single-category scenario taken all the way to TABULATED.

    entry_sheets: list of per-entry sheet triple lists, e.g.
        [[(9, 9, 9)], [(8, 8, 8)]] -> two PERFORMED entries, one sheet each.
    Returns the setup_scored_contest result dict.
    """
    if entry_sheets is None:
        entry_sheets = [[(9, 9, 9)]]
    spec = {
        "name": "Armor",
        "skill_division": skill_division,
        "max_entries": max_entries,
        "tabulation_method": tabulation_method,
        "prize_purse_cents": prize_purse_cents,
        "entries": [
            {"title": f"E{i + 1}", "sheets": sheets}
            for i, sheets in enumerate(entry_sheets)
        ],
    }
    return setup_scored_contest(
        [spec], prize_budget_cents=prize_budget_cents, lock=True, tabulate=True
    )


# ---------------------------------------------------------------------------
# Tier 5: prize-award lifecycle
# ---------------------------------------------------------------------------

def create_award(category_id, rank, creator_id="tr_1") -> dict:
    """Treasurer creates a PENDING award; entry auto-selected from placements."""
    return get_success_data(
        api_client.create_prize_award(
            create_prize_award_payload(category_id, rank),
            make_treasurer_headers(creator_id),
        )
    )


def approve_award(award_id, approver_id="tr_2") -> dict:
    """Checker approval: PENDING -> APPROVED (must differ from the creator)."""
    return get_success_data(
        api_client.approve_prize_award(award_id, make_treasurer_headers(approver_id))
    )


def disburse_award(award_id, tax_form_received, operator_id="tr_2") -> dict:
    """APPROVED -> DISBURSED; computes the withholding variant."""
    return get_success_data(
        api_client.disburse_prize_award(
            award_id, {"tax_form_received": tax_form_received},
            make_treasurer_headers(operator_id),
        )
    )


# ---------------------------------------------------------------------------
# Green room
# ---------------------------------------------------------------------------

def create_green_room_booking(contestant, contest_id, room_name="NORTH",
                              start_at=BOOKING_START, end_at=BOOKING_END,
                              requires_accessibility_setup=False, **overrides) -> dict:
    """Book green-room time as the owning contestant (starts BOOKED)."""
    payload = create_green_room_booking_payload(
        contestant["id"], contest_id, room_name=room_name, start_at=start_at,
        end_at=end_at, requires_accessibility_setup=requires_accessibility_setup,
        **overrides,
    )
    return get_success_data(
        api_client.create_green_room_booking(payload, contestant_headers(contestant))
    )


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

def set_logical_clock(to_iso8601) -> str:
    """Advance the test-driving logical clock; returns current_utc."""
    data = get_success_data(
        api_client.set_current_utc({"to_iso8601": to_iso8601}, LEAD)
    )
    return data["current_utc"]


def get_contest(contest_id) -> dict:
    return get_success_data(api_client.get_contest_event(contest_id, LEAD))


def get_category(category_id) -> dict:
    return get_success_data(api_client.get_category(category_id, LEAD))


def get_entry(entry_id) -> dict:
    return get_success_data(api_client.get_entry(entry_id, LEAD))


def get_prejudging_slot(slot_id) -> dict:
    return get_success_data(api_client.get_prejudging_slot(slot_id, LEAD))


def get_scoresheet(sheet_id) -> dict:
    return get_success_data(api_client.get_scoresheet(sheet_id, LEAD))


def get_performance_slot(slot_id) -> dict:
    return get_success_data(api_client.get_performance_slot(slot_id, STAGE))


def get_prize_award(award_id) -> dict:
    return get_success_data(
        api_client.get_prize_award(award_id, make_treasurer_headers("tr_1"))
    )
