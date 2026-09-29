"""
The order money is allowed to be spent in, and the compliance percentage that decides
whether a federal package may be accepted at all.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import (
    FHWA_REVIEWER_USER_ID,
    PROGRAM_ADMIN_USER_ID,
    fhwa_reviewer_headers,
    program_admin_headers,
)

CEDAR_WINDOW_START = "2026-09-02T08:00:00Z"
CEDAR_WINDOW_END = "2026-09-02T16:00:00Z"
CEDAR_DATE = "2026-09-02T10:00:00Z"

WILLOW_WINDOW_START = "2026-09-10T08:00:00Z"
WILLOW_WINDOW_END = "2026-09-10T16:00:00Z"
WILLOW_DATE = "2026-09-10T10:00:00Z"
WILLOW_SUBMIT_CLOCK = "2026-09-10T12:00:00Z"
WILLOW_QA_CLOCK = "2026-09-11T09:00:00Z"

# Cedar Creek in poor condition: one row per group, the girder carrying a third of its
# length in severe defect, which drags the minimum component rating down to 3.
CEDAR_ROWS = (f.BASELINE_DECK, f.BASELINE_GIRDER, f.BASELINE_ABUTMENT)

# Willow Slough in fair condition: only 40 of its 804 units are deficient at all.
PATCHED_DECK = f.element_condition_payload(
    "DECK", "SQM", 600, 500, 60, 40, 0,
    photo_count=3,
    defect_notes="Isolated deck patching",
)
RUSTED_GIRDER = f.element_condition_payload(
    "GIRDER", "M", 200, 150, 50, 0, 0,
    photo_count=2,
    defect_notes="Light surface rust",
)
SOUND_ABUTMENT = f.element_condition_payload(
    "ABUTMENT", "EA", 4, 4, 0, 0, 0, photo_count=1, defect_notes="Sound"
)
WILLOW_ROWS = (PATCHED_DECK, RUSTED_GIRDER, SOUND_ABUTMENT)

CEDAR_SCORE = 42.21
CEDAR_COST = 25990000
WILLOW_SCORE = 6.67
WILLOW_COST = 828000

RESERVE = 500000000
AVAILABLE = 9500000000


def _accept_report(
    client,
    roster,
    bridge_id,
    rows,
    window_start,
    window_end,
    inspection_date,
    submit_clock,
    qa_clock,
):
    """Drive one report from `DRAFT` to `ACCEPTED` over a caller-chosen element set."""
    inspection = fx.open_inspection(
        client,
        bridge_id,
        roster,
        field_window_start=window_start,
        field_window_end=window_end,
    )
    for row in rows:
        fx.add_element(client, inspection["id"], roster, row)
    fx.set_clock(client, submit_clock)
    fx.submit_report(client, inspection["id"], roster, inspection_date=inspection_date)
    fx.set_clock(client, qa_clock)
    fx.qa_claim(client, inspection["id"], roster)
    return fx.qa_decide(client, inspection["id"], roster, "ACCEPT")


def _two_candidates_of_unequal_priority(client, roster, bridge, budget=10000000000):
    """
    Two structures, each with one `ACCEPTED` routine report — Cedar Creek in poor
    condition and Willow Slough in fair condition — and a `CONDITION_BASED` cycle
    opened *after* both acceptances, so the acceptance cascade seeded no candidate of
    its own and both candidates on the cycle were filed by the district engineer.
    """
    _accept_report(
        client,
        roster,
        bridge["id"],
        CEDAR_ROWS,
        CEDAR_WINDOW_START,
        CEDAR_WINDOW_END,
        CEDAR_DATE,
        c.FIELD_DAY_CLOCK,
        c.QA_DAY_CLOCK,
    )
    willow = fx.create_bridge(
        client,
        f.bridge_payload(
            "STR-000002",
            name="Willow Slough Bridge",
            structure_type="CULVERT",
            deck_area_sqm=600,
            year_built=1988,
            adt=3000,
            detour_length_km=2.0,
        ),
    )
    _accept_report(
        client,
        roster,
        willow["id"],
        WILLOW_ROWS,
        WILLOW_WINDOW_START,
        WILLOW_WINDOW_END,
        WILLOW_DATE,
        WILLOW_SUBMIT_CLOCK,
        WILLOW_QA_CLOCK,
    )
    cycle = fx.create_cycle(client, fiscal_year=2029, authorized_budget_cents=budget)
    cedar_candidate = fx.identify_candidate(
        client,
        cycle["id"],
        bridge["id"],
        roster,
        justification="Superstructure 3, girder section loss",
    )
    willow_candidate = fx.identify_candidate(
        client,
        cycle["id"],
        willow["id"],
        roster,
        justification="Deck patching before it spreads",
    )
    return {
        "cycle": cycle,
        "willow": willow,
        "cedar_candidate": cedar_candidate,
        "willow_candidate": willow_candidate,
    }


def test_the_lower_ranked_candidate_cannot_be_programmed_first(client, roster, bridge):
    """
    The two candidates are thirty-five points apart, and the cheaper, sounder one is
    refused while the deteriorated one is still merely identified — the gate looks at
    the other candidates, not at the money.

    PRD §3.8: "It collects the cycle's *other* candidates whose `status` is `IDENTIFIED`
    that both outrank the target and whose own `estimated_cost_cents` is less than or
    equal to the cycle's `remaining_cents`. One candidate outranks another when its
    `priority_score` is greater, or when the two scores are equal and its `created_at`
    is earlier; the row `id` is never a tie-break. If that collection is non-empty the
    request fails with `ERR_HIGHER_PRIORITY_CANDIDATE_PENDING`."
    PRD §2.8: "30. **Ranking gate** — `ERR_HIGHER_PRIORITY_CANDIDATE_PENDING` (409).
    Applies to candidate programming."

    Design: Corner/errors/programming_a_lower_ranked_candidate_returns_409
    """
    setup = _two_candidates_of_unequal_priority(client, roster, bridge)

    response = client.program_candidate(
        setup["willow_candidate"]["id"], roster.district_headers
    )

    validate_error(response, e.ERR_HIGHER_PRIORITY_CANDIDATE_PENDING, 409)
    assert setup["cedar_candidate"]["priority_score"] == CEDAR_SCORE
    assert setup["willow_candidate"]["priority_score"] == WILLOW_SCORE
    summary = fx.read_allocation(client, setup["cycle"]["id"])
    assert summary["committed_cents"] == 0
    assert summary["remaining_cents"] == AVAILABLE
    assert summary["identified_count"] == 2
    assert summary["programmed_count"] == 0
    assert summary["unprogrammed_cost_cents"] == CEDAR_COST + WILLOW_COST
    for candidate in (setup["cedar_candidate"], setup["willow_candidate"]):
        assert fx.read_candidate(client, candidate["id"])["status"] == "IDENTIFIED"


def test_the_refusal_was_not_about_affordability(client, roster, bridge):
    """
    The residual is more than eleven thousand times the refused candidate's cost, so
    nothing about the money explains the 409 — and the two priced estimates and work
    types confirm which candidate the gate was protecting.

    PRD §3.8: "`work_type` is a first-match threshold on the structure's
    `min_nbi_rating` at the moment of creation: a rating of 3 or below yields
    `REPLACEMENT`, exactly 4 yields `REHABILITATION`, exactly 5 yields `REPAIR`, and 6
    or above yields `PRESERVATION`."
    PRD §3.8: "The lines are then summed into a subtotal, and the subtotal is multiplied
    by a mobilisation factor of 1.15 and rounded half up once more."
    PRD §3.8: "The `CONDITION_BASED` variant is the default statewide preservation
    ranking and uses condition inputs only: 0.50 times the condition gap, plus 0.30
    times the rating gap, plus 0.20 times the structure's `deficiency_pct`."

    Design: Corner/errors/programming_a_lower_ranked_candidate_returns_409
    """
    setup = _two_candidates_of_unequal_priority(client, roster, bridge)
    cedar, willow = setup["cedar_candidate"], setup["willow_candidate"]

    validate_error(
        client.program_candidate(willow["id"], roster.district_headers),
        e.ERR_HIGHER_PRIORITY_CANDIDATE_PENDING,
        409,
    )

    assert cedar["estimated_cost_cents"] == CEDAR_COST
    assert cedar["work_type"] == "REPLACEMENT"
    assert cedar["ranking_policy_applied"] == "CONDITION_BASED"
    assert willow["estimated_cost_cents"] == WILLOW_COST
    assert willow["work_type"] == "PRESERVATION"
    assert willow["origin"] == "MANUAL"
    a.assert_two_decimals(willow["priority_score"], "priority_score")
    assert (
        fx.read_allocation(client, setup["cycle"]["id"])["remaining_cents"]
        > 11000 * WILLOW_COST
    ), "the residual dwarfs the cost, so the gate cannot have been a budget refusal"


def test_programming_the_higher_ranked_one_first_unblocks_the_other(
    client, roster, bridge
):
    """
    The gate is not a permanent ordering but a queue: once the higher-ranked candidate
    is no longer `IDENTIFIED` the identical request that was refused succeeds, and the
    cycle ends up holding both commitments.

    PRD §3.8: "A successful programming moves the candidate `IDENTIFIED → PROGRAMMED`
    and stamps `programmed_at` from the logical clock. It adds the cost to
    `committed_cents`, re-derives `remaining_cents` from `available_cents` minus
    `committed_cents`, increases `programmed_count` by one, decreases
    `identified_count` by one, subtracts the cost from `unprogrammed_cost_cents`, and
    increments the cycle's `version` by one."
    PRD §3.8: "After every mutation the identity `authorized_budget_cents` equals
    `reserve_cents` plus `committed_cents` plus `remaining_cents` must hold."

    Design: Corner/errors/programming_a_lower_ranked_candidate_returns_409
    """
    setup = _two_candidates_of_unequal_priority(client, roster, bridge)
    validate_error(
        client.program_candidate(
            setup["willow_candidate"]["id"], roster.district_headers
        ),
        e.ERR_HIGHER_PRIORITY_CANDIDATE_PENDING,
        409,
    )

    cedar_programmed = validate_success(
        client.program_candidate(
            setup["cedar_candidate"]["id"], roster.district_headers
        ),
        200,
    )
    after_first = fx.read_allocation(client, setup["cycle"]["id"])
    willow_programmed = validate_success(
        client.program_candidate(
            setup["willow_candidate"]["id"], roster.district_headers
        ),
        200,
    )

    assert cedar_programmed["status"] == "PROGRAMMED"
    assert willow_programmed["status"] == "PROGRAMMED"
    a.assert_instant_equals(
        willow_programmed["programmed_at"], WILLOW_QA_CLOCK, "programmed_at"
    )
    assert after_first["committed_cents"] == CEDAR_COST
    assert after_first["remaining_cents"] == 9474010000
    summary = fx.read_allocation(client, setup["cycle"]["id"])
    assert summary["committed_cents"] == 26818000
    assert summary["remaining_cents"] == 9473182000
    assert summary["identified_count"] == 0
    assert summary["programmed_count"] == 2
    assert summary["unprogrammed_cost_cents"] == 0
    assert summary["reserve_cents"] == RESERVE
    assert summary["identity_holds"] is True
    a.assert_budget_identity(fx.read_cycle(client, setup["cycle"]["id"]))


def test_a_higher_ranked_candidate_that_no_longer_fits_does_not_block(
    client, roster, bridge
):
    """
    The same two candidates against a cycle authorised at a millionth of the budget:
    the higher-ranked one cannot be funded from the residual, so it drops out of the
    gate's collection and the affordable lower-ranked work proceeds.

    PRD §3.8: "The affordability condition in the gate is what keeps a cycle from
    deadlocking: a higher-priority candidate that no longer *fits* in the residual does
    not block, so the cycle may spend what is left on affordable lower-priority work."
    PRD §3.8: "The budget check then requires that the candidate's
    `estimated_cost_cents` is less than or equal to `remaining_cents`."
    PRD §2.8: "31. **Budget headroom** — `ERR_BUDGET_EXCEEDED` (422). Applies to
    candidate programming."

    Design: Corner/errors/programming_a_lower_ranked_candidate_returns_409
    """
    setup = _two_candidates_of_unequal_priority(client, roster, bridge, budget=1000000)
    opening = fx.read_allocation(client, setup["cycle"]["id"])
    assert opening["reserve_cents"] == 50000
    assert opening["available_cents"] == 950000
    assert opening["remaining_cents"] == 950000

    willow_programmed = validate_success(
        client.program_candidate(
            setup["willow_candidate"]["id"], roster.district_headers
        ),
        200,
    )

    assert willow_programmed["status"] == "PROGRAMMED"
    summary = fx.read_allocation(client, setup["cycle"]["id"])
    assert summary["committed_cents"] == WILLOW_COST
    assert summary["remaining_cents"] == 122000
    assert summary["identity_holds"] is True

    refused = client.program_candidate(
        setup["cedar_candidate"]["id"], roster.district_headers
    )

    validate_error(refused, e.ERR_BUDGET_EXCEEDED, 422)
    assert fx.read_candidate(client, setup["cedar_candidate"]["id"])["status"] == (
        "IDENTIFIED"
    )


# ─── The compliance percentage a federal package is judged on ────────────────
STALE_CLOCK = "2020-01-01T00:00:00Z"


def _a_sent_package_over_three_structures_one_of_them_stale(client):
    """
    Three structures whose only difference is when they entered the inventory and how
    long their cycle is: one added in 2020 on the standard two-year cycle and therefore
    years overdue, and two added at the base clock whose first inspections are not yet
    due. None has a scour evaluation, so every `poa_compliant` is true and the package
    may be sent.
    """
    fx.set_clock(client, STALE_CLOCK)
    stale = fx.create_bridge(client, f.bridge_payload("STR-000001"))
    fx.set_clock(client, c.BASE_CLOCK)
    willow = fx.create_bridge(
        client,
        f.bridge_payload(
            "STR-000002",
            name="Willow Slough Bridge",
            structure_type="CULVERT",
            deck_area_sqm=600,
            year_built=1988,
            adt=3000,
            detour_length_km=2.0,
        ),
    )
    rock_fork = fx.create_bridge(
        client,
        f.bridge_payload(
            "STR-000003",
            name="Rock Fork Bridge",
            owner_agency="County of Rock",
            structure_type="ARCH",
            deck_area_sqm=450,
            year_built=1996,
            adt=900,
            detour_length_km=12.0,
        ),
    )
    cycle = fx.create_cycle(client, fiscal_year=2027)
    submission = fx.start_submission(client, cycle["id"], submission_type="NBI_ANNUAL")
    fx.lock_cycle(client, cycle["id"])
    sent = fx.send_submission(client, submission["id"])
    return {
        "stale": stale,
        "willow": willow,
        "rock_fork": rock_fork,
        "cycle": cycle,
        "submission": sent,
    }


def test_the_snapshot_counts_the_one_structure_whose_due_date_has_passed(client):
    """
    Two of the three structures are inside their cycle and the 2020 arrival is four
    years past its due date, so the statewide percentage lands on the PRD's own
    two-thirds worked example — and the package's only defect is that percentage.

    PRD §3.9: "`overdue_inspection_count` is the number of structures whose
    `next_inspection_due_date` falls **strictly before** the logical clock's current
    date — a structure whose due date *is* today is compliant, not overdue."
    PRD §3.9: "`inspection_compliance_pct` is 100 if there are no structures at all;
    otherwise it is 100 multiplied by the compliant count, which is the total minus the
    overdue count, divided by the total, rounded half up to two decimal places. Three
    structures with one overdue gives 100 times 2 divided by 3, which is 66.666…,
    rounded to 66.67."
    PRD §2.11: "Failing either the poor-condition test or the extension test, the base
    is the standard 24 months."

    Design: Corner/errors/federal_submission_accept_below_ninety_percent_compliance_rejected
    """
    setup = _a_sent_package_over_three_structures_one_of_them_stale(client)
    package = setup["submission"]

    assert package["status"] == "SUBMITTED"
    assert package["total_bridge_count"] == 3
    assert package["overdue_inspection_count"] == 1
    assert package["inspection_compliance_pct"] == 66.67
    assert package["poa_noncompliant_count"] == 0
    assert package["open_immediate_finding_count"] == 0
    assert package["error_count"] == 0
    assert package["submitted_by_user_id"] == PROGRAM_ADMIN_USER_ID
    a.assert_instant_equals(package["submitted_at"], c.BASE_CLOCK, "submitted_at")

    a.assert_date_equals(
        setup["stale"]["next_inspection_due_date"],
        "2022-01-01",
        "next_inspection_due_date",
    )
    assert fx.read_compliance(client, setup["stale"]["id"])["routine_overdue"] is True
    for structure in (setup["willow"], setup["rock_fork"]):
        assert fx.read_compliance(client, structure["id"])["routine_overdue"] is False


def test_acceptance_is_refused_below_ninety_per_cent(client):
    """
    The reviewer is a different user from the sender and the package is in the one state
    review is allowed from, so the compliance threshold is the only objection left —
    and the refusal leaves both the package and its cycle exactly where they were.

    PRD §3.9: "`ACCEPT` additionally requires the submission's stored
    `inspection_compliance_pct` to be at least 90.00, compared at the *rounded*
    two-decimal value: exactly 90.00 is acceptable, and anything below it fails with
    `ERR_COMPLIANCE_BELOW_THRESHOLD`."
    PRD §2.8: "32. **Federal compliance threshold** — `ERR_COMPLIANCE_BELOW_THRESHOLD`
    (422). Applies to federal-submission review."

    Design: Corner/errors/federal_submission_accept_below_ninety_percent_compliance_rejected
    """
    setup = _a_sent_package_over_three_structures_one_of_them_stale(client)

    response = client.review_federal_submission(
        setup["submission"]["id"], f.review_payload("ACCEPT"), fhwa_reviewer_headers()
    )

    validate_error(response, e.ERR_COMPLIANCE_BELOW_THRESHOLD, 422)
    unchanged = fx.read_submission(client, setup["submission"]["id"])
    assert unchanged["status"] == "SUBMITTED"
    assert unchanged["reviewed_at"] is None
    assert unchanged["reviewer_user_id"] is None
    assert unchanged["rejection_reason_code"] == "NONE"
    assert unchanged["inspection_compliance_pct"] == 66.67
    assert fx.read_cycle(client, setup["cycle"]["id"])["status"] == "SUBMITTED"


def test_rejection_names_the_percentage_as_the_reason_and_reopens_the_loop(client):
    """
    The same reviewer who could not accept the package may reject it, and the reason
    code is read off the snapshot rather than defaulting to data quality: the cycle goes
    back to locked with its submission instant erased, ready for a corrected package.

    PRD §3.9: "`REJECT` carries no compliance precondition — a reviewer may reject a
    package that would otherwise have qualified for acceptance, for reasons of data
    quality. It moves the submission `SUBMITTED → REJECTED`, stamps `reviewed_at`,
    records `reviewer_user_id`, and records a `rejection_reason_code` derived from the
    snapshot: `COMPLIANCE_BELOW_THRESHOLD` when the stored `inspection_compliance_pct`
    is below 90.00, and `DATA_GAPS` otherwise."
    PRD §3.9: "The owning cycle returns `SUBMITTED → LOCKED` and its `submitted_at` is
    **cleared to null** so a corrected package can be sent afresh."

    Design: Corner/errors/federal_submission_accept_below_ninety_percent_compliance_rejected
    """
    setup = _a_sent_package_over_three_structures_one_of_them_stale(client)
    validate_error(
        client.review_federal_submission(
            setup["submission"]["id"],
            f.review_payload("ACCEPT"),
            fhwa_reviewer_headers(),
        ),
        e.ERR_COMPLIANCE_BELOW_THRESHOLD,
        422,
    )

    rejected = fx.review_submission(
        client, setup["submission"]["id"], "REJECT", fhwa_reviewer_headers()
    )

    assert rejected["status"] == "REJECTED"
    assert rejected["rejection_reason_code"] == "COMPLIANCE_BELOW_THRESHOLD"
    assert rejected["reviewer_user_id"] == FHWA_REVIEWER_USER_ID
    assert rejected["reviewer_user_id"] != rejected["submitted_by_user_id"]
    a.assert_instant_equals(rejected["reviewed_at"], c.BASE_CLOCK, "reviewed_at")
    assert rejected["total_bridge_count"] == 3
    assert rejected["inspection_compliance_pct"] == 66.67

    cycle = fx.read_cycle(client, setup["cycle"]["id"])
    assert cycle["status"] == "LOCKED"
    assert cycle["submitted_at"] is None


# ─── The last rung: condition data must exist before money is planned ────────
def _a_planning_cycle_and_a_structure_with_only_a_draft(client, roster, bridge):
    """
    A `PLANNING` cycle and a structure whose only report is still a draft, so the
    inventory holds an inspection but no *accepted* condition data.
    """
    inspection = fx.open_inspection(
        client,
        bridge["id"],
        roster,
        field_window_start=CEDAR_WINDOW_START,
        field_window_end=CEDAR_WINDOW_END,
    )
    cycle = fx.create_cycle(client, fiscal_year=2027)
    return {"cycle": cycle, "draft": inspection}


def test_a_structure_whose_only_report_is_a_draft_cannot_be_programmed_against(
    client, roster, bridge
):
    """
    Every earlier rung of the ladder is satisfied — the cycle version matches, the cycle
    is planning, the structure exists and the acting role is the right one — and the
    request still fails, because a draft report is not condition data.

    PRD §3.8: "The cycle must be in `PLANNING`, and the structure must have at least one
    `ACCEPTED` inspection; a structure that has never had a report accepted cannot be
    programmed and the attempt fails with `ERR_BRIDGE_NOT_INSPECTED`."
    PRD §2.8: "33. **Condition data existence** — `ERR_BRIDGE_NOT_INSPECTED` (422).
    Applies to candidate creation."

    Design: Corner/errors/candidate_for_never_inspected_bridge_rejected
    """
    setup = _a_planning_cycle_and_a_structure_with_only_a_draft(client, roster, bridge)
    cycle = fx.read_cycle(client, setup["cycle"]["id"])

    response = client.create_project_candidate(
        cycle["id"],
        f.candidate_payload(
            cycle["version"], bridge["id"], justification="Anticipated replacement"
        ),
        roster.district_headers,
    )

    validate_error(response, e.ERR_BRIDGE_NOT_INSPECTED, 422)
    error_id = response.json()["data"]["error_id"]
    assert error_id != e.ERR_STALE_CYCLE_VERSION, "the supplied cycle version matched"
    assert error_id != e.ERR_BRIDGE_NOT_FOUND, "the structure exists"
    assert setup["draft"]["status"] == "DRAFT"
    rows, meta = validate_paginated(
        client.list_project_candidates(
            program_admin_headers(), {"program_cycle_id": cycle["id"]}
        )
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_the_refused_creation_left_the_cycle_untouched(client, roster, bridge):
    """
    A rejected identification is not a partial one: the cycle's version, its candidate
    counts and its unprogrammed total all read exactly what they read before, so nothing
    was consumed by the attempt.

    PRD §3.8: "The cycle's `identified_count` and `unprogrammed_cost_cents` are then
    recomputed and its `version` is incremented by one."
    PRD §3.8: "Three counters track the candidate mix: `identified_count`,
    `programmed_count` and `deferred_count`, each counting the cycle's candidates in the
    corresponding status and each starting at 0."

    Design: Corner/errors/candidate_for_never_inspected_bridge_rejected
    """
    setup = _a_planning_cycle_and_a_structure_with_only_a_draft(client, roster, bridge)
    before = fx.read_cycle(client, setup["cycle"]["id"])

    validate_error(
        client.create_project_candidate(
            before["id"],
            f.candidate_payload(before["version"], bridge["id"]),
            roster.district_headers,
        ),
        e.ERR_BRIDGE_NOT_INSPECTED,
        422,
    )

    after = fx.read_cycle(client, before["id"])
    a.assert_version_unchanged(after["version"], before["version"], "program cycle")
    assert after["status"] == "PLANNING"
    summary = fx.read_allocation(client, before["id"])
    assert summary["identified_count"] == 0
    assert summary["programmed_count"] == 0
    assert summary["deferred_count"] == 0
    assert summary["unprogrammed_cost_cents"] == 0


def test_once_a_report_is_accepted_the_same_request_supersedes_the_cascade_candidate(
    client, roster, bridge
):
    """
    Accepting the report both unblocks the identification and files a candidate of its
    own, so the district engineer's manual filing lands on a structure that already has
    one — and the automatic candidate is withdrawn in favour of the new estimate.

    PRD §3.8: "Creation supersedes: any prior candidate for the *same* structure and the
    *same* cycle whose `status` is `IDENTIFIED` is moved to `WITHDRAWN` with
    `withdrawn_at` stamped, because the new estimate replaces the old one."
    PRD §3.8: "A candidate created through this route records `origin` `MANUAL`; one
    created by the acceptance cascade of §3.3 records `origin` `AUTO_FROM_INSPECTION`."
    PRD §3.8: "a `source_inspection_id` naming the `ACCEPTED` report whose condition data
    produces the estimate — when omitted this defaults to the structure's latest
    `ACCEPTED` inspection"

    Design: Corner/errors/candidate_for_never_inspected_bridge_rejected
    """
    setup = _a_planning_cycle_and_a_structure_with_only_a_draft(client, roster, bridge)
    cycle_id = setup["cycle"]["id"]
    validate_error(
        client.create_project_candidate(
            cycle_id,
            f.candidate_payload(
                fx.read_cycle(client, cycle_id)["version"], bridge["id"]
            ),
            roster.district_headers,
        ),
        e.ERR_BRIDGE_NOT_INSPECTED,
        422,
    )
    draft_id = setup["draft"]["id"]
    fx.add_baseline_elements(client, draft_id, roster)
    fx.set_clock(client, c.FIELD_DAY_CLOCK)
    fx.submit_report(client, draft_id, roster, inspection_date=CEDAR_DATE)
    fx.set_clock(client, c.QA_DAY_CLOCK)
    fx.qa_claim(client, draft_id, roster)
    fx.qa_decide(client, draft_id, roster, "ACCEPT")
    from_cascade = fx.candidates_in_cycle(client, cycle_id)
    assert len(from_cascade) == 1
    assert from_cascade[0]["origin"] == "AUTO_FROM_INSPECTION"

    manual = get_success_data(
        client.create_project_candidate(
            cycle_id,
            f.candidate_payload(
                fx.read_cycle(client, cycle_id)["version"],
                bridge["id"],
                justification="Anticipated replacement",
            ),
            roster.district_headers,
        ),
        201,
    )

    assert manual["origin"] == "MANUAL"
    assert manual["status"] == "IDENTIFIED"
    assert manual["source_inspection_id"] == draft_id
    assert manual["estimated_cost_cents"] == 26588000
    assert manual["work_type"] == "REPLACEMENT"
    superseded = fx.read_candidate(client, from_cascade[0]["id"])
    assert superseded["status"] == "WITHDRAWN"
    a.assert_instant_equals(
        superseded["withdrawn_at"], c.QA_DAY_CLOCK, "withdrawn_at"
    )
    summary = fx.read_allocation(client, cycle_id)
    assert summary["identified_count"] == 1
    assert summary["unprogrammed_cost_cents"] == 26588000
    assert len(fx.candidates_in_cycle(client, cycle_id)) == 2
