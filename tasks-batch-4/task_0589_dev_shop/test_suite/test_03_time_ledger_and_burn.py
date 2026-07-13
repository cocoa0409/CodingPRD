"""The hours ledger: logging and reviewing time, the five-link approval cascade,
the burn thresholds that freeze a sprint, the two burn variants, and the exact
reversal that restores the ledger."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_delivery_lead_headers,
    assert_posture_matches_ratio,
    fixtures,
    factories as F,
)

DL = TEST_USERS["delivery_lead_headers"]  # pm-001
FIN = TEST_USERS["finance_officer_headers"]
ENG = TEST_USERS["engineer_headers"]  # eng-001
ENG2 = TEST_USERS["engineer_2_headers"]  # eng-002

# A tight engagement: 2000.00 over 10 hours at 200.00/h, so 9.0 approved hours
# land the burn ratio on exactly 0.9000.
TIGHT = {
    "contract_value": 2000.00,
    "budget_hours_cap": 10,
    "standard_hourly_rate": 200.00,
}


def test_time_entry_billable_defaults_to_true_when_omitted(api):
    """PRD 3.4: "An engineer submits a `ticket_id`, the `work_date` on which the work happened, the number of `hours`, an optional `billable` flag (defaulting to true), and an optional `note`."
    PRD 3.4: "The server stamps `employee_user_id` from the acting `X-User-ID`; if that identifier does not equal the ticket's `assignee_user_id`, the entry is refused with `ERR_NOT_TICKET_ASSIGNEE` (HTTP 422)."

    Design: Corner/entities/time_entry_billable_defaults_to_true_when_omitted
    """
    ctx = fixtures.setup_ticket_in_progress()
    resp = api.create_time_entry(
        F.create_time_entry_payload(
            ticket_id=ctx["ticket"]["id"], work_date="2026-05-05", hours=2.0
        ),
        ENG,
    )
    entry = validate_success(resp, expected_status=201)
    assert entry["billable"] is True, "an omitted billable flag defaults to true"
    assert entry["employee_user_id"] == "eng-001", (
        "employee_user_id is stamped from the acting X-User-ID, not from the body"
    )
    assert entry["status"] == "SUBMITTED"

    fixtures.approve_time(entry["id"])
    engagement = validate_success(api.get_engagement(ctx["engagement"]["id"], DL))
    assert engagement["approved_hours"] == 2.0, (
        "a defaulted-billable entry enters the burn ledger once approved"
    )
    assert engagement["burned_cost"] == pytest.approx(400.00, abs=0.01)


def test_daily_hours_cap_exceeded_on_second_entry_same_day(api):
    """PRD 3.4: "And across the whole system, no employee may accumulate more than 12 hours on any single calendar day: the sum of `hours` already logged by that same `employee_user_id` on that same `work_date`, counting entries in `SUBMITTED` and `APPROVED` status, plus the hours of the new entry, must not exceed 12 — a breach draws `ERR_DAILY_HOURS_EXCEEDED` (HTTP 422)."

    Design: Corner/validations/daily_hours_cap_exceeded_on_second_entry_same_day
    """
    ctx = fixtures.setup_ticket_in_progress(
        ticket_overrides={"title": "Long grind", "estimated_hours": 20}
    )
    ticket_id = ctx["ticket"]["id"]
    fixtures.log_time(ticket_id, 10.0, work_date="2026-05-05")

    resp = api.create_time_entry(
        F.create_time_entry_payload(ticket_id=ticket_id, work_date="2026-05-05", hours=2.5),
        ENG,
    )
    validate_error(resp, ApiErrorId.ERR_DAILY_HOURS_EXCEEDED.value)

    entries = validate_success(api.list_time_entries(DL, params={"ticket_id": ticket_id}))
    assert len(entries) == 1, "10.0 + 2.5 breaches the 12-hour day; only the first entry stands"


def test_work_date_on_the_exclusive_sprint_end_date_is_rejected(api):
    """PRD 3.4: "The `work_date` must fall inside the owning sprint's half-open window — on or after the sprint's `start_date` and strictly before its `end_date` — and an entry dated outside it is rejected with `ERR_WORK_DATE_OUT_OF_SPRINT` (HTTP 422)."

    Design: Corner/validations/work_date_outside_sprint_window_is_rejected_for_the_assignee
    """
    ctx = fixtures.setup_ticket_in_progress(
        sprint_overrides={"start_date": "2026-05-04", "end_date": "2026-05-18"},
        ticket_overrides={"title": "Edge case"},
    )
    ticket_id = ctx["ticket"]["id"]

    rejected = api.create_time_entry(
        F.create_time_entry_payload(ticket_id=ticket_id, work_date="2026-05-18", hours=2.0),
        ENG,
    )
    validate_error(rejected, ApiErrorId.ERR_WORK_DATE_OUT_OF_SPRINT.value)

    accepted = validate_success(
        api.create_time_entry(
            F.create_time_entry_payload(ticket_id=ticket_id, work_date="2026-05-17", hours=2.0),
            ENG,
        ),
        expected_status=201,
    )
    assert accepted["status"] == "SUBMITTED", "the day before the exclusive end is inside"

    entries = validate_success(api.list_time_entries(DL, params={"ticket_id": ticket_id}))
    assert len(entries) == 1, "only the in-window entry was persisted"


def test_sprint_spend_frozen_blocks_ticket_start(api):
    """PRD 3.3: "It requires the sprint to be `ACTIVE`; it requires the sprint's `spend_frozen` to be false, failing with `ERR_SPRINT_SPEND_FROZEN` (HTTP 409) when the engagement's posture has frozen the sprint; and, when the ticket declares a `blocking_ticket_id`, it requires that blocker to have reached `DONE`, failing with `ERR_TICKET_BLOCKED` (HTTP 409) otherwise."
    PRD 3.5: "The freeze is what stops a strained engagement from accruing more work: with `spend_frozen` true, no ticket in that sprint can be moved into `IN_PROGRESS`, whether from `TODO` or back out of `REWORK`."

    Design: Corner/validations/sprint_spend_frozen_blocks_ticket_start
    """
    ctx = fixtures.setup_active_sprint(engagement_overrides=TIGHT)
    sprint_id = ctx["sprint"]["id"]
    ticket_1 = fixtures.create_ticket(
        sprint_id, title="T1", estimated_hours=8, assignee_user_id="eng-001"
    )
    ticket_2 = fixtures.create_ticket(
        sprint_id, title="T2", estimated_hours=5, assignee_user_id="eng-002"
    )
    fixtures.start_ticket(ticket_1["id"], "eng-001")
    entry = fixtures.log_time(ticket_1["id"], 9.0)
    fixtures.approve_time(entry["id"])

    resp = api.transition_ticket(ticket_2["id"], "IN_PROGRESS", ENG2)
    validate_error(resp, ApiErrorId.ERR_SPRINT_SPEND_FROZEN.value)

    sprint = validate_success(api.get_sprint(sprint_id, DL))
    assert sprint["status"] == "ACTIVE", "the sprint is frozen, not closed"
    assert sprint["spend_frozen"] is True
    assert validate_success(api.get_ticket(ticket_2["id"], DL))["status"] == "TODO"


def test_budget_posture_is_overburned_at_a_ratio_of_exactly_one(api):
    """PRD 3.5: "`budget_posture` is a threshold read on that 4-decimal `burn_ratio`, and **both boundaries are inclusive**. A ratio of 1.0000 or above makes the engagement `OVERBURNED`."
    PRD 3.4: "Approval carries one further guard, and it fires before the cascade runs: **only for a billable entry**, the engagement's current `approved_hours` plus the entry's `hours` must not exceed the engagement's `budget_hours_cap`."

    Design: Corner/cross_cutting_complexity_layers/budget_posture_overburned_at_ratio_exactly_one
    """
    ctx = fixtures.setup_ticket_in_progress(
        engagement_overrides=TIGHT,
        ticket_overrides={"title": "Everything", "estimated_hours": 10},
    )
    entry = fixtures.log_time(ctx["ticket"]["id"], 10.0)

    approved = validate_success(api.review_time_entry(entry["id"], "APPROVE", DL))
    assert approved["status"] == "APPROVED", (
        "10.0 hours is exactly the 10-hour cap, so the cap check (which forbids only "
        "exceeding it) must pass"
    )

    engagement = validate_success(api.get_engagement(ctx["engagement"]["id"], DL))
    assert engagement["burn_ratio"] == pytest.approx(1.0, abs=1e-9)
    assert engagement["budget_posture"] == "OVERBURNED", (
        f"a ratio of exactly 1.0000 is OVERBURNED, not AT_RISK; got "
        f"{engagement['budget_posture']}"
    )
    assert_posture_matches_ratio(engagement)
    sprint = validate_success(api.get_sprint(ctx["sprint"]["id"], DL))
    assert sprint["spend_frozen"] is True


def test_burn_rate_on_engagement_with_zero_time_entries_is_zero(api):
    """PRD 3.5: "Likewise, when `approved_hours` is 0 the ratio is exactly 0.0."
    PRD 3.5: "The read also echoes the engagement's `engagement_id`, its current `budget_posture`, its `contract_value` and its `budget_hours_cap`, so a delivery lead can see the headroom and the pressure on the same screen."

    Design: Corner/calculations/burn_rate_on_engagement_with_zero_time_entries_is_zero
    """
    ctx = fixtures.setup_active_engagement(**TIGHT)
    burn = validate_success(api.get_burn_rate(ctx["engagement"]["id"], FIN))

    assert burn["approved_hours"] == 0
    assert burn["burned_cost"] == pytest.approx(0.0, abs=0.01)
    assert burn["burn_ratio"] == pytest.approx(0.0, abs=1e-9)
    assert burn["committed_hours"] == 0
    assert burn["committed_burn_ratio"] == pytest.approx(0.0, abs=1e-9)
    assert burn["budget_posture"] == "HEALTHY"
    assert burn["contract_value"] == pytest.approx(2000.00, abs=0.01)


# ---------------------------------------------------------------------------
# The five-link approval cascade
# ---------------------------------------------------------------------------
def test_time_entry_approval_rolls_hours_up_to_the_ticket(api):
    """PRD 3.4: "First, the entry is marked `APPROVED` and `reviewed_by_user_id` is recorded. Second, that approval adds the entry's `hours` to the ticket's `actual_hours` and recomputes the ticket's `variance_ratio`."
    PRD 3.3: "A ticket's `actual_hours` is at all times the sum of `hours` over its `APPROVED` time entries, and its `variance_ratio` is that `actual_hours` figure divided by its `estimated_hours`, rounded half up to 4 decimal places."

    Design: Difficulty/transitive_cascade/time_entry_approval_five_link_cascade_to_sprint_freeze
    """
    ctx = fixtures.setup_ticket_in_progress(
        engagement_overrides=TIGHT,
        ticket_overrides={"title": "Checkout flow", "estimated_hours": 8},
    )
    entry = fixtures.log_time(ctx["ticket"]["id"], 9.0)

    approved = validate_success(
        api.review_time_entry(entry["id"], "APPROVE", make_delivery_lead_headers("pm-001"))
    )
    assert approved["status"] == "APPROVED"
    assert approved["reviewed_by_user_id"] == "pm-001", (
        "the reviewer's X-User-ID is recorded on the entry"
    )

    ticket = validate_success(api.get_ticket(ctx["ticket"]["id"], DL))
    assert ticket["actual_hours"] == pytest.approx(9.0, abs=0.01)
    assert ticket["variance_ratio"] == pytest.approx(1.125, abs=1e-9), (
        f"9.0 approved hours against an 8-hour estimate is 1.125, got "
        f"{ticket['variance_ratio']}"
    )


def test_time_entry_approval_cascade_reaches_budget_posture_and_freezes_the_sprint(api):
    """PRD 3.4: "Third, the ticket's movement rolls up to the engagement, whose `approved_hours`, `burned_cost` and `burn_ratio` are recomputed. Fourth, the new `burn_ratio` recomputes the engagement's `budget_posture`. And fifth, the new posture propagates down: if it is `AT_RISK` or `OVERBURNED`, every sprint of that engagement currently in `ACTIVE` status has its `spend_frozen` set to true; if it is `HEALTHY`, every `ACTIVE` sprint has `spend_frozen` set to false."
    PRD 3.5: "A ratio at or above 0.9000 but below 1.0000 makes it `AT_RISK` — a ratio of exactly 0.9000 *is* `AT_RISK`, not `HEALTHY`."

    Design: Difficulty/transitive_cascade/time_entry_approval_five_link_cascade_to_sprint_freeze
    """
    ctx = fixtures.setup_ticket_in_progress(
        engagement_overrides=TIGHT,
        ticket_overrides={"title": "Checkout flow", "estimated_hours": 8},
    )
    entry = fixtures.log_time(ctx["ticket"]["id"], 9.0)
    fixtures.approve_time(entry["id"])

    engagement = validate_success(api.get_engagement(ctx["engagement"]["id"], DL))
    assert engagement["approved_hours"] == pytest.approx(9.0, abs=0.01)
    assert engagement["burned_cost"] == pytest.approx(1800.00, abs=0.01), (
        "9.0 hours at 200.00/h rounds once on the aggregate to 1800.00"
    )
    assert engagement["burn_ratio"] == pytest.approx(0.9, abs=1e-9)
    assert engagement["budget_posture"] == "AT_RISK"

    sprint = validate_success(api.get_sprint(ctx["sprint"]["id"], DL))
    assert sprint["spend_frozen"] is True, (
        "the AT_RISK posture freezes every ACTIVE sprint of the engagement"
    )


# ---------------------------------------------------------------------------
# The AT_RISK boundary
# ---------------------------------------------------------------------------
def test_burn_ratio_just_below_the_at_risk_threshold_stays_healthy(api):
    """PRD 3.5: "A ratio at or above 0.9000 but below 1.0000 makes it `AT_RISK` — a ratio of exactly 0.9000 *is* `AT_RISK`, not `HEALTHY`. Anything below 0.9000 is `HEALTHY`."

    Design: Difficulty/boundary_precision_check/burn_ratio_exactly_at_at_risk_threshold_flips_posture
    """
    ctx = fixtures.setup_ticket_in_progress(
        engagement_overrides=TIGHT,
        ticket_overrides={"title": "Portal gun API", "estimated_hours": 8},
    )
    entry = fixtures.log_time(ctx["ticket"]["id"], 8.95, work_date="2026-05-05")
    validate_success(api.review_time_entry(entry["id"], "APPROVE", DL))

    engagement = validate_success(api.get_engagement(ctx["engagement"]["id"], DL))
    assert engagement["burned_cost"] == pytest.approx(1790.00, abs=0.01)
    assert engagement["burn_ratio"] == pytest.approx(0.895, abs=1e-9)
    assert engagement["budget_posture"] == "HEALTHY", (
        f"0.8950 is below the inclusive 0.9000 floor, so the posture stays HEALTHY; "
        f"got {engagement['budget_posture']}"
    )
    sprint = validate_success(api.get_sprint(ctx["sprint"]["id"], DL))
    assert sprint["spend_frozen"] is False, "a HEALTHY engagement leaves its sprint unfrozen"


def test_burn_ratio_landing_exactly_on_the_at_risk_threshold_flips_the_posture(api):
    """PRD 3.5: "A ratio at or above 0.9000 but below 1.0000 makes it `AT_RISK` — a ratio of exactly 0.9000 *is* `AT_RISK`, not `HEALTHY`. Anything below 0.9000 is `HEALTHY`."
    PRD 3.5: "Every recompute re-runs the freeze cascade in full: a non-`HEALTHY` posture freezes every `ACTIVE` sprint of the engagement by setting `spend_frozen` true, and a `HEALTHY` posture thaws every `ACTIVE` sprint by setting it false."

    Design: Difficulty/boundary_precision_check/burn_ratio_exactly_at_at_risk_threshold_flips_posture
    """
    ctx = fixtures.setup_ticket_in_progress(
        engagement_overrides=TIGHT,
        ticket_overrides={"title": "Portal gun API", "estimated_hours": 8},
    )
    first = fixtures.log_time(ctx["ticket"]["id"], 8.95, work_date="2026-05-05")
    fixtures.approve_time(first["id"])
    before = validate_success(api.get_engagement(ctx["engagement"]["id"], DL))
    assert before["budget_posture"] == "HEALTHY", "at 0.8950 the engagement is still HEALTHY"

    second = fixtures.log_time(ctx["ticket"]["id"], 0.05, work_date="2026-05-06")
    validate_success(api.review_time_entry(second["id"], "APPROVE", DL))

    engagement = validate_success(api.get_engagement(ctx["engagement"]["id"], DL))
    assert engagement["approved_hours"] == pytest.approx(9.0, abs=0.01)
    assert engagement["burned_cost"] == pytest.approx(1800.00, abs=0.01)
    assert engagement["burn_ratio"] == pytest.approx(0.9, abs=1e-9)
    assert engagement["budget_posture"] == "AT_RISK", (
        f"the extra 0.05h lands the ratio on exactly 0.9000, which is inclusive; got "
        f"{engagement['budget_posture']}"
    )
    sprint = validate_success(api.get_sprint(ctx["sprint"]["id"], DL))
    assert sprint["spend_frozen"] is True


# ---------------------------------------------------------------------------
# The two burn variants
# ---------------------------------------------------------------------------
def test_burn_rate_read_exposes_diverging_approved_only_and_committed_variants(api):
    """PRD 3.5: "The **committed** variant — returned as `committed_hours`, `committed_burned_cost` and `committed_burn_ratio` — widens the filter to entries in `SUBMITTED` **or** `APPROVED` status (still billable only, and still excluding `REJECTED` and `REVERSED`); `committed_hours` is their summed `hours`, `committed_burned_cost` is that total multiplied by `standard_hourly_rate` and rounded half up to 2 decimal places, and `committed_burn_ratio` is that cost divided by `contract_value` rounded half up to 4 decimal places."
    PRD 3.5: "Whenever any billable entry is sitting unreviewed, the committed variant is strictly higher than the approved-only one — that is the whole point of it."

    Design: Difficulty/dual_variant_calc/burn_rate_approved_only_vs_committed_variant_divergence
    """
    ctx = fixtures.setup_ticket_in_progress(
        engagement_overrides=TIGHT,
        ticket_overrides={"title": "Checkout flow", "estimated_hours": 8},
    )
    approved_entry = fixtures.log_time(ctx["ticket"]["id"], 4.0, work_date="2026-05-05")
    fixtures.approve_time(approved_entry["id"])
    fixtures.log_time(ctx["ticket"]["id"], 2.0, work_date="2026-05-06")  # left SUBMITTED

    burn = validate_success(api.get_burn_rate(ctx["engagement"]["id"], DL))
    assert burn["approved_hours"] == pytest.approx(4.0, abs=0.01)
    assert burn["burned_cost"] == pytest.approx(800.00, abs=0.01)
    assert burn["burn_ratio"] == pytest.approx(0.4, abs=1e-9)
    assert burn["budget_posture"] == "HEALTHY"
    assert burn["committed_hours"] == pytest.approx(6.0, abs=0.01)
    assert burn["committed_burned_cost"] == pytest.approx(1200.00, abs=0.01)
    assert burn["committed_burn_ratio"] == pytest.approx(0.6, abs=1e-9)
    assert burn["burn_ratio"] != burn["committed_burn_ratio"], (
        "an unreviewed billable entry must make the committed variant strictly higher"
    )


def test_persisted_engagement_carries_only_the_approved_only_burn_variant(api):
    """PRD 3.5: "The **approved-only** variant — `approved_hours`, `burned_cost` and `burn_ratio` — is the persisted ledger described above, and it is the only variant that drives `budget_posture`, the spend freeze and the budget-cap check."
    PRD 3.5: "The engagement's burn ledger is computed from time entries alone, and only two things qualify: an entry must be `APPROVED` **and** it must be billable. Entries in `SUBMITTED`, `REJECTED` or `REVERSED` status are excluded, as is any entry marked non-billable, and the exclusions apply no matter how large the entry is."

    Design: Difficulty/dual_variant_calc/burn_rate_approved_only_vs_committed_variant_divergence
    """
    ctx = fixtures.setup_ticket_in_progress(
        engagement_overrides=TIGHT,
        ticket_overrides={"title": "Checkout flow", "estimated_hours": 8},
    )
    approved_entry = fixtures.log_time(ctx["ticket"]["id"], 4.0, work_date="2026-05-05")
    fixtures.approve_time(approved_entry["id"])
    fixtures.log_time(ctx["ticket"]["id"], 2.0, work_date="2026-05-06")  # left SUBMITTED

    engagement = validate_success(api.get_engagement(ctx["engagement"]["id"], DL))
    assert engagement["approved_hours"] == pytest.approx(4.0, abs=0.01), (
        "the SUBMITTED entry must not enter the persisted hours ledger"
    )
    assert engagement["burned_cost"] == pytest.approx(800.00, abs=0.01)
    assert engagement["burn_ratio"] == pytest.approx(0.4, abs=1e-9), (
        f"the persisted field carries the approved-only variant (0.4), never the "
        f"committed 0.6; got {engagement['burn_ratio']}"
    )
    assert engagement["budget_posture"] == "HEALTHY"
    assert_posture_matches_ratio(engagement)


# ---------------------------------------------------------------------------
# The compensating reversal
# ---------------------------------------------------------------------------
def test_reversing_an_approved_entry_restores_the_ticket_hours(api):
    """PRD 3.4: "the entry moves `APPROVED → REVERSED`, the entry's `hours` are subtracted back out of the ticket's `actual_hours` and `variance_ratio` is recomputed, the engagement's `approved_hours`, `burned_cost` and `burn_ratio` are recomputed, `budget_posture` is recomputed, and — should the posture return to `HEALTHY` — every `ACTIVE` sprint of the engagement has `spend_frozen` set back to false."
    PRD 2.9: "A ticket's `actual_hours` must equal the sum of `hours` over every `APPROVED` time entry against that ticket."

    Design: Difficulty/compensating_invariant/time_entry_reverse_restores_hours_ledger_with_zero_drift
    """
    ctx = fixtures.setup_with_approved_hours(hours=9.0)
    ticket_id = ctx["ticket"]["id"]
    before = validate_success(api.get_ticket(ticket_id, DL))
    assert before["actual_hours"] == pytest.approx(9.0, abs=0.01)

    reversed_entry = validate_success(
        api.reverse_time_entry(
            ctx["time_entry"]["id"], "Logged against the wrong ticket", DL
        )
    )
    assert reversed_entry["status"] == "REVERSED"

    ticket = validate_success(api.get_ticket(ticket_id, DL))
    assert ticket["actual_hours"] == 0, (
        f"the reversal subtracts the hours back out, got {ticket['actual_hours']}"
    )
    assert ticket["variance_ratio"] == pytest.approx(0.0, abs=1e-9)


def test_reversing_an_approved_entry_restores_the_engagement_ledger_and_thaws_the_sprint(api):
    """PRD 2.9: "Approving an entry and then reversing it must leave both sums — and therefore `burned_cost`, `burn_ratio`, `budget_posture`, and every affected sprint's `spend_frozen` flag — at exactly the values they held before the approval."
    PRD 2.9: "an engagement's `approved_hours` must equal the sum of `hours` over every time entry that is `APPROVED`, is marked billable, and whose ticket rolls up through a sprint to that engagement."

    Design: Difficulty/compensating_invariant/time_entry_reverse_restores_hours_ledger_with_zero_drift
    """
    ctx = fixtures.setup_with_approved_hours(hours=9.0)
    engagement_id = ctx["engagement"]["id"]
    sprint_id = ctx["sprint"]["id"]

    strained = validate_success(api.get_engagement(engagement_id, DL))
    assert strained["budget_posture"] == "AT_RISK", "precondition: the approval strained the budget"
    assert validate_success(api.get_sprint(sprint_id, DL))["spend_frozen"] is True

    validate_success(
        api.reverse_time_entry(ctx["time_entry"]["id"], "Logged in error", DL)
    )

    engagement = validate_success(api.get_engagement(engagement_id, DL))
    assert engagement["approved_hours"] == 0, "zero drift is permitted in the hours ledger"
    assert engagement["burned_cost"] == pytest.approx(0.0, abs=0.01)
    assert engagement["burn_ratio"] == pytest.approx(0.0, abs=1e-9)
    assert engagement["budget_posture"] == "HEALTHY"
    assert_posture_matches_ratio(engagement)

    sprint = validate_success(api.get_sprint(sprint_id, DL))
    assert sprint["spend_frozen"] is False, (
        "the posture's return to HEALTHY thaws every ACTIVE sprint"
    )

    entries = validate_success(
        api.list_time_entries(DL, params={"ticket_id": ctx["ticket"]["id"], "status": "APPROVED"})
    )
    assert len(entries) == 0, "no APPROVED entry remains, so the ledger sum is 0"
