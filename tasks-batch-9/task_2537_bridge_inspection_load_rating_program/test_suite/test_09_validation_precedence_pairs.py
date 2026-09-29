"""
Validation precedence: when two rules are broken at once, only one is reported.

PRD §2.8: "When a single request violates several rules at once, exactly one error
is returned, chosen by a fixed global precedence. The checks are evaluated in this
order, and the first violated check is the one reported".
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import program_admin_headers

FIELD_DAY = "2026-09-02T12:00:00Z"
LATE_CLOCK = "2026-10-01T09:00:00Z"


# ─── A locked cycle and an unaffordable candidate ───────────────────────────
def _locked_cycle_with_an_unaffordable_candidate(client, roster, bridge):
    """
    A cycle authorised at 1,000,000 cents with no reserve, holding the automatic
    candidate the acceptance cascade files at 26,588,000 cents — far more than the
    cycle can fund — and then locked.
    """
    cycle = fx.create_cycle(
        client, fiscal_year=2028, authorized_budget_cents=1000000, reserve_pct=0.00
    )
    fx.accepted_report(client, bridge["id"], roster, qa_clock=FIELD_DAY)
    candidates = fx.candidates_in_cycle(client, cycle["id"])
    assert len(candidates) == 1, "the acceptance cascade files exactly one candidate"
    fx.lock_cycle(client, cycle["id"])
    return {"cycle": cycle, "candidate": candidates[0]}


def test_the_locked_cycle_is_reported_before_the_budget_shortfall(
    client, roster, bridge
):
    """
    The candidate is both unprogrammable by state and unaffordable by budget. The
    state gate sits at position nine of the precedence list and the budget check
    at position thirty-one, so the conflict is what the client is told.

    PRD §2.8: "9. **State gating** — the target resource, and any parent whose
    state gates the operation, is in a state from which the requested transition is
    declared, else the family-scoped 409 conflict code ... `ERR_PROGRAM_STATE_INVALID`."
    PRD §2.8: "31. **Budget headroom** — `ERR_BUDGET_EXCEEDED` (422). Applies to
    candidate programming."
    PRD §3.8: "While locked, candidate identification, programming, withdrawal and
    deferral are all blocked — every one of those actions requires `PLANNING`."

    Design: Difficulty/priority_pair_validation_conflict/cycle_state_beats_budget_exceeded
    """
    setup = _locked_cycle_with_an_unaffordable_candidate(client, roster, bridge)

    response = client.program_candidate(
        setup["candidate"]["id"], roster.district_headers
    )

    validate_error(response, e.ERR_PROGRAM_STATE_INVALID, 409)


def test_the_blocked_programming_attempt_changes_nothing(client, roster, bridge):
    """
    A refused programming attempt is inert: the candidate keeps its identification
    and the cycle's money is exactly where the lock left it.

    PRD §3.8: "A successful programming moves the candidate `IDENTIFIED →
    PROGRAMMED` and stamps `programmed_at` from the logical clock. It adds the cost
    to `committed_cents`, re-derives `remaining_cents` from `available_cents` minus
    `committed_cents`, increases `programmed_count` by one".
    PRD §3.8: "After every mutation the identity `authorized_budget_cents` equals
    `reserve_cents` plus `committed_cents` plus `remaining_cents` must hold."

    Design: Difficulty/priority_pair_validation_conflict/cycle_state_beats_budget_exceeded
    """
    setup = _locked_cycle_with_an_unaffordable_candidate(client, roster, bridge)

    client.program_candidate(setup["candidate"]["id"], roster.district_headers)

    candidate = fx.read_candidate(client, setup["candidate"]["id"])
    assert candidate["status"] == "IDENTIFIED"
    assert candidate["programmed_at"] is None

    cycle = fx.read_cycle(client, setup["cycle"]["id"])
    assert cycle["status"] == "LOCKED"
    assert cycle["programmed_count"] == 0
    assert cycle["committed_cents"] == 0
    assert cycle["remaining_cents"] == 1000000
    assert cycle["reserve_cents"] == 0
    a.assert_budget_identity(cycle)


def test_reopening_the_cycle_exposes_the_budget_shortfall_underneath(
    client, roster, bridge
):
    """
    Clearing the higher-precedence conflict lets the next violation speak: the same
    request now fails on budget headroom.

    PRD §3.8: "Reopening moves it `LOCKED → PLANNING` and *retains* `locked_at` as
    the instant of the most recent lock rather than clearing it".
    PRD §3.8: "The budget check then requires that the candidate's
    `estimated_cost_cents` is less than or equal to `remaining_cents`. The
    comparison is strict only on the failing side: a candidate that consumes
    *exactly* the residual is allowed and drives `remaining_cents` to 0. Anything
    larger is `ERR_BUDGET_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/cycle_state_beats_budget_exceeded
    """
    setup = _locked_cycle_with_an_unaffordable_candidate(client, roster, bridge)
    validate_success(
        client.reopen_program_cycle(setup["cycle"]["id"], program_admin_headers()), 200
    )

    response = client.program_candidate(
        setup["candidate"]["id"], roster.district_headers
    )

    validate_error(response, e.ERR_BUDGET_EXCEEDED, 422)
    assert fx.read_candidate(client, setup["candidate"]["id"])["status"] == "IDENTIFIED"


# ─── A lapsed team leader and an unbalanced element row ─────────────────────
def _lapsing_leader_with_an_unbalanced_row(client):
    """
    A roster whose inspector's refresher expires on 15 September 2026, a structure,
    and a three-group report whose deck row is short by 10 units.
    """
    fx.pin_base_clock(client)
    people = {
        "inspector": fx.create_person(
            client,
            f.personnel_payload(
                "Ivy Inspector", "2026-09-15", team_leader_certified=True
            ),
        ),
        "reviewer": fx.create_person(
            client,
            f.personnel_payload("Quinn Qa", "2027-06-30", team_leader_certified=True),
        ),
        "engineer": fx.create_person(
            client,
            f.personnel_payload(
                "Rita Rating",
                "2027-06-30",
                team_leader_certified=True,
                load_rating_engineer_licensed=True,
                pe_license_number="PE-11021",
            ),
        ),
        "district": fx.create_person(
            client,
            f.personnel_payload(
                "Dana District",
                "2027-06-30",
                team_leader_certified=True,
                load_rating_engineer_licensed=True,
                pe_license_number="PE-20044",
            ),
        ),
    }
    roster = fx.Roster(people)
    bridge = fx.create_cedar_creek(client)
    inspection = fx.open_inspection(client, bridge["id"], roster)
    deck = fx.add_element(
        client,
        inspection["id"],
        roster,
        f.element_condition_payload(
            "DECK", "SQM", 1000, 600, 200, 150, 40, photo_count=6,
            defect_notes="Deck spalling",
        ),
    )
    fx.add_element(client, inspection["id"], roster, f.BASELINE_GIRDER)
    fx.add_element(client, inspection["id"], roster, f.BASELINE_ABUTMENT)
    return {
        "roster": roster,
        "bridge": bridge,
        "inspection": inspection,
        "deck": deck,
    }


def test_the_lapsed_refresher_is_reported_before_the_quantity_mismatch(client):
    """
    The submission breaks two rules: the team leader's refresher has lapsed and the
    deck row does not balance. Team-leader qualification sits at position twelve and
    quantity balance at position eighteen, so the qualification failure is reported.

    PRD §2.8: "12. **Team-leader qualification** — `ERR_TEAM_LEADER_NOT_QUALIFIED`
    (422). Applies to inspection creation and inspection submit."
    PRD §2.8: "18. **Quantity balance** — `ERR_ELEMENT_QUANTITY_MISMATCH` (422).
    Applies to inspection submit."
    PRD §3.3: "That person's `qualification_status` must be `CURRENT` at the current
    logical clock instant — a refresher that lapsed between opening the report and
    submitting it blocks the submission".

    Design: Difficulty/priority_pair_validation_conflict/team_leader_qualification_beats_element_quantity_mismatch
    """
    setup = _lapsing_leader_with_an_unbalanced_row(client)
    assert setup["deck"]["balanced"] is False
    assert setup["deck"]["reported_sum"] == 990

    fx.set_clock(client, LATE_CLOCK)
    response = client.submit_inspection(
        setup["inspection"]["id"],
        f.submit_payload("2026-09-02T10:00:00Z"),
        setup["roster"].inspector_headers,
    )

    validate_error(response, e.ERR_TEAM_LEADER_NOT_QUALIFIED, 422)


def test_the_refresher_date_is_compared_against_the_clock_on_whole_days(client):
    """
    The same roster entry is qualified on 1 September and lapsed on 1 October,
    because the status is derived on each read from the clock rather than stored.

    PRD §2.10: "the derived `qualification_status` reads `CURRENT` when that expiry
    date falls on or after the logical clock's current UTC calendar date, and
    `EXPIRED` when the expiry date is strictly earlier than that calendar date."
    PRD §2.10: "Because the comparison reads the logical clock,
    `qualification_status` is recomputed on every read of a roster entry and
    re-evaluated at every operation that names the person".

    Design: Difficulty/priority_pair_validation_conflict/team_leader_qualification_beats_element_quantity_mismatch
    """
    setup = _lapsing_leader_with_an_unbalanced_row(client)

    assert (
        fx.read_person(client, setup["roster"].inspector_id)["qualification_status"]
        == "CURRENT"
    )

    fx.set_clock(client, LATE_CLOCK)
    assert (
        fx.read_person(client, setup["roster"].inspector_id)["qualification_status"]
        == "EXPIRED"
    )


def test_the_refused_submission_leaves_the_report_and_the_structure_untouched(
    client,
):
    """
    A refused submission publishes nothing: the report stays in draft with no
    condition arithmetic frozen on it and the structure has no health index or
    routine inspection date.

    PRD §3.3: "Submission moves the report from `DRAFT` to `SUBMITTED` and is the
    point at which the report's condition arithmetic is computed and frozen for
    review."
    PRD §3.1: "`bridge_health_index`, `posted_limit_tons`, `operating_rating_tons`,
    `inventory_rating_tons`, `governing_load_rating_id`,
    `last_routine_inspection_date` and `last_underwater_inspection_date` all null
    until the events that populate them occur."

    Design: Difficulty/priority_pair_validation_conflict/team_leader_qualification_beats_element_quantity_mismatch
    """
    setup = _lapsing_leader_with_an_unbalanced_row(client)

    fx.set_clock(client, LATE_CLOCK)
    client.submit_inspection(
        setup["inspection"]["id"],
        f.submit_payload("2026-09-02T10:00:00Z"),
        setup["roster"].inspector_headers,
    )

    report = fx.read_inspection(client, setup["inspection"]["id"])
    assert report["status"] == "DRAFT"
    assert report["submitted_at"] is None
    assert report["bridge_health_index"] is None

    structure = fx.read_bridge(client, setup["bridge"]["id"])
    assert structure["bridge_health_index"] is None
    assert structure["last_routine_inspection_date"] is None


def test_balancing_the_row_does_not_help_while_the_refresher_is_lapsed(client):
    """
    Fixing the lower-precedence violation cannot unblock the request; only winding
    the clock back inside the certificate's validity lets the submission through.

    PRD §2.8: "12. **Team-leader qualification** — `ERR_TEAM_LEADER_NOT_QUALIFIED`
    (422). Applies to inspection creation and inspection submit."
    PRD §3.2: "An inspector may redistribute quantities on an existing row while
    the report is still `DRAFT`".
    PRD §3.3: "Every element row must be individually balanced — its four
    condition-state quantities summing exactly to its `total_quantity`, which is the
    same thing as the report's `quantity_balanced` being true — else
    `ERR_ELEMENT_QUANTITY_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/team_leader_qualification_beats_element_quantity_mismatch
    """
    setup = _lapsing_leader_with_an_unbalanced_row(client)
    roster = setup["roster"]

    balanced = validate_success(
        client.update_element_condition(
            setup["deck"]["id"],
            f.element_update_payload(1000, 600, 200, 150, 50, photo_count=6),
            roster.inspector_headers,
        ),
        200,
    )
    assert balanced["balanced"] is True

    fx.set_clock(client, LATE_CLOCK)
    still_refused = client.submit_inspection(
        setup["inspection"]["id"],
        f.submit_payload("2026-09-02T10:00:00Z"),
        roster.inspector_headers,
    )
    validate_error(still_refused, e.ERR_TEAM_LEADER_NOT_QUALIFIED, 422)

    fx.set_clock(client, FIELD_DAY)
    accepted_submission = validate_success(
        client.submit_inspection(
            setup["inspection"]["id"],
            f.submit_payload("2026-09-02T10:00:00Z"),
            roster.inspector_headers,
        ),
        200,
    )
    assert accepted_submission["status"] == "SUBMITTED"
    assert accepted_submission["quantity_balanced"] is True
