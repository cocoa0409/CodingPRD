"""The case cost ledger, its allocation waterfall and the derived trend analytics."""

import pytest

from test_helpers import (
    DIRECTOR_USER_ID,
    ApiErrorId,
    assert_cost_allocation,
    assert_cost_entry,
    assert_instant,
    cost_entry_payload,
    draft_offer,
    file_grievance,
    post_cost_entry,
    read_grievance,
    setup_base,
    setup_case_with_counsel_cost,
    setup_grievance,
    validate_error,
    validate_paginated,
    validate_success,
    void_cost_entry,
)


def test_posting_a_split_charge_moves_the_allocation_and_the_posture(api):
    """PRD §3.9: "Cost allocation is re-derived whenever an entry is posted or voided, and
    again on every read of the grievance, and it proceeds in five steps. First, the base total
    is the sum of `amount_cents` over the grievance's `POSTED` entries only, irrespective of
    category or origin; voided entries contribute nothing to any output."
    PRD §3.9: "Third, the union's share is summed over the same posted set: an entry borne by
    `UNION` contributes its full amount, an entry borne by `SPLIT` contributes its amount
    multiplied by the union split in basis points and divided by 10,000, rounded half up, and
    an entry borne by `EMPLOYER` contributes nothing."

    Design: Difficulty/compensating_invariant/cost_void_restores_case_cost_identity
    """
    ctx = setup_case_with_counsel_cost()

    before = read_grievance(ctx["grievance"]["id"])
    assert_cost_allocation(before, total=972_000, union=0, employer=972_000)
    assert before["cost_posture"] == "COST_OK"

    post_cost_entry(ctx["grievance"]["id"], "TRANSCRIPT", 400_000, "SPLIT")

    after = read_grievance(ctx["grievance"]["id"])
    assert_cost_allocation(after, total=1_384_800, union=240_000, employer=1_144_800)
    assert after["cost_posture"] == "COST_WATCH"


def test_voiding_the_charge_restores_the_exact_pre_posting_figures(api, analyst_headers):
    """PRD §3.9: "A void must restore the case's cost figures to their **exact** pre-posting
    values, which is only true if voided entries are excluded from the allocation input set
    entirely rather than being offset by a compensating charge."
    PRD §3.9: "A `LaborRelationsDirector` may **void** a posted entry, supplying a
    `void_reason`; the entry moves to `VOIDED` and `voided_by_user_id` records the acting
    `X-User-ID`."

    Design: Difficulty/compensating_invariant/cost_void_restores_case_cost_identity
    """
    ctx = setup_case_with_counsel_cost()
    transcript = post_cost_entry(ctx["grievance"]["id"], "TRANSCRIPT", 400_000, "SPLIT")

    voided = void_cost_entry(transcript["id"], "Transcript ordered in error")
    assert voided["status"] == "VOIDED"
    assert voided["voided_by_user_id"] == DIRECTOR_USER_ID

    restored = read_grievance(ctx["grievance"]["id"])
    assert_cost_allocation(restored, total=972_000, union=0, employer=972_000)
    assert restored["cost_posture"] == "COST_OK"


def test_the_void_keeps_the_audit_row_and_the_cost_identity(api, analyst_headers):
    """PRD §3.9: "And the identity that `total_cost_cents` always equals
    `union_cost_share_cents` plus `employer_cost_share_cents` holds after every posting and
    every void."
    PRD §3.9: "The ledger of a case may be listed in full, system-generated and voided
    entries included, filtered by `category`, by `status` or by `bearing_party`."

    Design: Difficulty/compensating_invariant/cost_void_restores_case_cost_identity
    """
    ctx = setup_case_with_counsel_cost()
    observations = [read_grievance(ctx["grievance"]["id"])]
    transcript = post_cost_entry(ctx["grievance"]["id"], "TRANSCRIPT", 400_000, "SPLIT")
    observations.append(read_grievance(ctx["grievance"]["id"]))
    void_cost_entry(transcript["id"], "Transcript ordered in error")
    observations.append(read_grievance(ctx["grievance"]["id"]))

    for observation in observations:
        assert observation["total_cost_cents"] == (
            observation["union_cost_share_cents"] + observation["employer_cost_share_cents"]
        )

    rows, meta = validate_paginated(
        api.list_cost_entries(ctx["grievance"]["id"], analyst_headers)
    )
    assert meta["total_count"] == 2, "the void preserves the audit row rather than deleting it"
    assert {row["status"] for row in rows} == {"POSTED", "VOIDED"}


def test_supervisor_scorecard_reads_zero_on_an_empty_closed_set(api, analyst_headers):
    """PRD §2.6: "Both derived rate fields in the system — `sustain_rate_bps` on a clause and
    `adverse_rate_bps` on a supervisor — are exactly 0 when their denominator is 0. Zero, not
    null, and not an error."
    PRD §3.9: "`open_grievance_count` counts those whose status is not `SETTLED`,
    `WITHDRAWN`, `CONSOLIDATED` or `CLOSED`."

    Design: Difficulty/boundary_precision_check/supervisor_scorecard_zero_denominator
    """
    ctx = setup_base()
    for statement in ("Grievance one", "Grievance two", "Grievance three"):
        file_grievance(ctx, statement=statement)

    supervisor = validate_success(
        api.get_employee(ctx["supervisor"]["id"], analyst_headers), 200
    )

    assert supervisor["open_grievance_count"] == 3
    assert supervisor["closed_grievance_count"] == 0
    assert supervisor["sustained_against_count"] == 0
    assert supervisor["adverse_rate_bps"] == 0
    assert supervisor["witness_release_hours_ytd"] == pytest.approx(0.0)


def test_clause_scorecard_counts_cases_in_flight_but_rates_them_at_zero(api, analyst_headers):
    """PRD §3.9: "`filed_count` counts every one whose status is not `CONSOLIDATED`, in
    flight or not. `sustained_count` counts those same non-consolidated grievances that meet
    the adverse-outcome predicate. `denied_count` counts those whose status is `SETTLED`,
    `WITHDRAWN` or `CLOSED` and that do **not** meet the predicate. `sustain_rate_bps` is
    `sustained_count` multiplied by 10,000, divided by `filed_count`, rounded half up — and
    exactly 0 when `filed_count` is 0."
    PRD §3.2: "Its `case_number` is minted as the literal prefix `GR-`, then the agreement's
    `local_number`, then another hyphen, then a four-digit zero-padded ordinal counting this
    grievance's position among the grievances of that same unit in ascending `created_at`
    order, starting at `0001`."

    Design: Difficulty/boundary_precision_check/supervisor_scorecard_zero_denominator
    """
    ctx = setup_base()
    filed = [
        file_grievance(ctx, statement=statement)
        for statement in ("Grievance one", "Grievance two", "Grievance three")
    ]

    clauses, _ = validate_paginated(
        api.list_contract_clauses(ctx["unit"]["id"], analyst_headers)
    )
    scorecard = clauses[0]

    assert scorecard["filed_count"] == 3
    assert scorecard["sustained_count"] == 0
    assert scorecard["denied_count"] == 0
    assert scorecard["sustain_rate_bps"] == 0

    assert [row["case_number"] for row in filed] == [
        "GR-L2100-0001", "GR-L2100-0002", "GR-L2100-0003"
    ]


def test_the_sharing_tier_is_selected_from_the_base_total(api, analyst_headers):
    """PRD §3.9: "Second, the cost-sharing schedule is selected **from that base total**: a
    base total of 500,000 cents or less puts the union's split at 5,000 basis points — an even
    division — a base total above that and up to 2,000,000 cents puts it at 6,000 basis
    points, and anything above that puts it at 7,000 basis points."
    PRD §3.9: "The sharing tier is selected from the base total of step one and is never
    re-selected from the grand total of step five after the administrative fee has been added
    — doing so yields different shares and is the wrong reading."

    Design: Corner/calculations/cost_allocation_tier_is_keyed_on_base_total_not_grand_total
    """
    ctx = setup_grievance()
    post_cost_entry(ctx["grievance"]["id"], "TRANSCRIPT", 400_000, "SPLIT")
    post_cost_entry(ctx["grievance"]["id"], "COUNSEL", 90_000, "EMPLOYER")

    grievance = read_grievance(ctx["grievance"]["id"])

    assert_cost_allocation(grievance, total=513_200, union=200_000, employer=313_200)
    assert grievance["total_cost_cents"] != 510_000, (
        "the 8 percent administrative fee sits on the employer side of the base total"
    )
    assert grievance["cost_posture"] == "COST_OK"

    rows, meta = validate_paginated(
        api.list_cost_entries(ctx["grievance"]["id"], analyst_headers)
    )
    assert meta["total_count"] == 2
    incurred = [row["incurred_at"] for row in rows]
    assert incurred == sorted(incurred), "ordered by incurred_at ASC"


def test_the_third_sharing_tier_applies_above_two_million(api):
    """PRD §3.9: "Second, the cost-sharing schedule is selected **from that base total**: a
    base total of 500,000 cents or less puts the union's split at 5,000 basis points — an even
    division — a base total above that and up to 2,000,000 cents puts it at 6,000 basis
    points, and anything above that puts it at 7,000 basis points."

    Design: Corner/calculations/cost_posture_reaches_breach_above_five_million
    """
    ctx = setup_case_with_counsel_cost()
    post_cost_entry(ctx["grievance"]["id"], "TRAVEL", 400_000, "SPLIT")

    watch = read_grievance(ctx["grievance"]["id"])
    assert watch["total_cost_cents"] == 1_384_800
    assert watch["union_cost_share_cents"] == 240_000
    assert watch["cost_posture"] == "COST_WATCH"

    post_cost_entry(ctx["grievance"]["id"], "COUNSEL", 5_000_000, "EMPLOYER")

    breach = read_grievance(ctx["grievance"]["id"])
    assert breach["union_cost_share_cents"] == 280_000, (
        "the 400000 split entry is now shared at 7000 basis points"
    )


def test_the_cost_posture_reaches_breach_above_five_million(api):
    """PRD §3.9: "Finally, `cost_posture` is derived from the grand total: `COST_OK` at
    1,000,000 cents or less, `COST_WATCH` above that and up to 5,000,000 cents, and
    `COST_BREACH` above that."
    PRD §3.9: "Fifth, the administrative fee is 800 basis points — eight percent — of the
    **employer's base side**, rounded half up, and it is added to the employer's side alone:
    `employer_cost_share_cents` is the employer base plus that fee, `union_cost_share_cents`
    is the figure from step three, and `total_cost_cents` is the two of them added together."

    Design: Corner/calculations/cost_posture_reaches_breach_above_five_million
    """
    ctx = setup_case_with_counsel_cost()
    post_cost_entry(ctx["grievance"]["id"], "TRAVEL", 400_000, "SPLIT")
    post_cost_entry(ctx["grievance"]["id"], "COUNSEL", 5_000_000, "EMPLOYER")

    breach = read_grievance(ctx["grievance"]["id"])

    assert_cost_allocation(breach, total=6_781_600, union=280_000, employer=6_501_600)
    assert breach["cost_posture"] == "COST_BREACH"


def test_operator_posted_cost_entry_defaults_to_manual_and_posted(api, analyst_headers):
    """PRD §3.9: "The entry is stamped with `incurred_at` at the clock's current instant, an
    `origin` of `MANUAL`, and a `status` of `POSTED`, with `void_reason` and
    `voided_by_user_id` both null."

    Design: Corner/entities/cost_entry_creation_defaults_origin_manual_and_status_posted
    """
    ctx = setup_grievance()

    entry = validate_success(
        api.create_cost_entry(
            ctx["grievance"]["id"],
            cost_entry_payload("FILING", 12_500, "UNION"),
            analyst_headers,
        ),
        201,
    )
    assert_cost_entry(entry)

    assert entry["origin"] == "MANUAL"
    assert entry["status"] == "POSTED"
    assert entry["void_reason"] is None
    assert entry["voided_by_user_id"] is None
    assert_instant(entry["incurred_at"], "2026-08-01T00:00:00Z", "incurred_at")

    grievance = read_grievance(ctx["grievance"]["id"])
    assert grievance["union_cost_share_cents"] == 12_500, "a UNION entry contributes in full"
    assert grievance["total_cost_cents"] == (
        grievance["union_cost_share_cents"] + grievance["employer_cost_share_cents"]
    )

    _, meta = validate_paginated(
        api.list_cost_entries(
            ctx["grievance"]["id"], analyst_headers, params={"category": "FILING"}
        )
    )
    assert meta["total_count"] == 1


def test_voiding_an_already_voided_entry_is_refused(api, analyst_headers, director_headers):
    """PRD §3.9: "Voiding an entry that is already `VOIDED` is rejected with
    `ERR_COST_ENTRY_ALREADY_VOIDED`."

    Design: Corner/state_machines/voiding_an_already_voided_cost_entry_is_refused
    """
    ctx = setup_grievance()
    entry = post_cost_entry(ctx["grievance"]["id"], "TRAVEL", 60_000, "UNION")
    voided = void_cost_entry(entry["id"], "Trip cancelled")

    response = api.void_cost_entry(
        entry["id"], {"void_reason": "Trip cancelled again"}, director_headers
    )
    validate_error(response, ApiErrorId.ERR_COST_ENTRY_ALREADY_VOIDED.value)

    rows, meta = validate_paginated(
        api.list_cost_entries(
            ctx["grievance"]["id"], analyst_headers, params={"status": "VOIDED"}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["void_reason"] == "Trip cancelled"
    assert rows[0]["version"] == voided["version"]

    grievance = read_grievance(ctx["grievance"]["id"])
    assert_cost_allocation(grievance, total=0, union=0, employer=0)
    assert grievance["cost_posture"] == "COST_OK"


def test_the_grievance_read_is_the_case_cost_summary(api, analyst_headers):
    """PRD §3.2: "Reading a single grievance returns its timeliness posture, both deadline
    instants and the four cost fields, all derived at the moment of the read."
    PRD §3.9: "Finally, `cost_posture` is derived from the grand total: `COST_OK` at
    1,000,000 cents or less, `COST_WATCH` above that and up to 5,000,000 cents, and
    `COST_BREACH` above that."

    Design: Corner/endpoints/grievance_read_exposes_the_derived_cost_summary
    """
    ctx = setup_grievance()

    empty = read_grievance(ctx["grievance"]["id"])
    assert_cost_allocation(empty, total=0, union=0, employer=0)
    assert empty["cost_posture"] == "COST_OK"

    post_cost_entry(ctx["grievance"]["id"], "COUNSEL", 900_000, "EMPLOYER")
    single = read_grievance(ctx["grievance"]["id"])
    assert_cost_allocation(single, total=972_000, union=0, employer=972_000)
    assert single["cost_posture"] == "COST_OK"

    post_cost_entry(ctx["grievance"]["id"], "TRAVEL", 400_000, "SPLIT")
    both = read_grievance(ctx["grievance"]["id"])
    assert_cost_allocation(both, total=1_384_800, union=240_000, employer=1_144_800)
    assert both["cost_posture"] == "COST_WATCH"


def test_derived_fields_are_settled_inside_the_request_that_causes_them(api, analyst_headers):
    """PRD §2.8: "The cascades are enumerated in the workflow narratives of §3, and they are
    not optional or best-effort: a reader who fetches the affected records immediately after
    the request must observe every stated consequence."
    PRD §3.4: "**Exposure and the authority tier** are computed at drafting time and
    re-verified when authorization is attempted, and they run in four stages whose order is
    normative."

    Design: Corner/consistency_model/immediate_consistency_derived_fields_land_in_the_same_response
    """
    ctx = setup_grievance()

    entry = validate_success(
        api.create_cost_entry(
            ctx["grievance"]["id"],
            cost_entry_payload("TRANSCRIPT", 400_000, "SPLIT"),
            analyst_headers,
        ),
        201,
    )
    assert entry["status"] == "POSTED"

    grievance = read_grievance(ctx["grievance"]["id"])
    assert_cost_allocation(grievance, total=416_000, union=200_000, employer=216_000)
    assert grievance["cost_posture"] == "COST_OK"

    offer = draft_offer(
        ctx["grievance"]["id"], monetary_cents=75_000, back_pay_hours=50
    )
    assert offer["exposure_cents"] == 250_000, "the creation response already carries it"
    assert offer["authority_tier"] == "DIRECTOR"
    assert offer["precedent_deviation_bps"] is None
