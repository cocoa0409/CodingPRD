"""The public account of what the field earns: the two population bases, the statistics they
disagree on, the review loop that guards a draft, and the version a draft consumes."""

from test_helpers import (
    assert_bucket_counts_and_shares,
    assert_income_disclosure_statement,
    assert_instant,
    constants as k,
    factories as f,
    fixtures as fx,
    make_headers,
    TEST_USERS,
    validate_error,
    validate_success,
)

ANALYST = TEST_USERS["commission_analyst_headers"]
LEGAL = TEST_USERS["legal_reviewer_headers"]


def _paid_three_generation_run(api):
    """A 47,500-cent run in which A and C were paid and B's 500 cents were carried forward."""
    state = fx.setup_paid_run(api)
    assert state["run"]["gross_total_cents"] == 47500, "the run's gross earnings"
    assert state["run"]["paid_total_cents"] == 47000, "A's 23,800 and C's 23,200 were disbursed"
    assert state["run"]["carry_forward_total_cents"] == 500, "B fell below the minimum payout"
    return state


def _paid_run_that_pays_nobody(api):
    """One consultant, 99 volume points, one statement of 0 cents carried forward."""
    state = fx.setup_single_earner_paid_run(
        api, pairs=(("SAMPLE", 99),), order_type="PERSONAL_INVENTORY"
    )
    assert state["order"]["total_due_cents"] == 12529, "99 sample packs shipped into TX"
    assert state["order"]["total_volume_points"] == 99, "one point below pv_bonus_min_points 100"
    assert state["run"]["status"] == "PAID", "the run completed its lifecycle"
    assert state["run"]["statement_count"] == 1, "the single consultant still gets a statement"
    assert state["run"]["paid_total_cents"] == 0, "but nothing was disbursed"
    statement = fx.statement_of(api, state["run"]["id"], state["a"]["id"])
    assert statement["gross_commission_cents"] == 0, "99 points earn no personal volume bonus"
    assert statement["payout_status"] == "CARRIED_FORWARD", "0 is below min_payout_cents 2500"
    return state


def test_all_enrolled_keeps_the_carried_earner_in_and_pulls_the_averages_down(api):
    """Drafted over the whole enrolled population, the distribution counts B's 500 cents and
    reports the median and mean of all three consultants.

    PRD: "Under `ALL_ENROLLED`, the population is every consultant of the run's plan whose status is
    not `TERMINATED` and whose `enrollment_completed_at` is strictly before the period's
    `period_end`; a member with no `ACTIVE` statement in the run contributes earnings of 0, so
    `zero_earner_count` can be positive and the mean and median are pulled down."

    Design: Difficulty/dual_variant_calc/income_disclosure_all_enrolled_vs_paid_only_divergence
    """
    state = _paid_three_generation_run(api)
    run_version_before = validate_success(
        api.get_commission_run(state["run"]["id"], ANALYST)
    )["version"]

    disclosure = fx.draft_disclosure(api, state["run"], "ALL_ENROLLED")
    assert_income_disclosure_statement(disclosure)
    assert disclosure["population_basis"] == "ALL_ENROLLED", "the basis is recorded on the row"
    assert disclosure["population_count"] == 3, "every non-terminated consultant of the plan"
    assert disclosure["total_earnings_cents"] == 47500, "gross commission, before withholding"
    assert disclosure["median_earnings_cents"] == 23200, "the middle of 500, 23,200 and 23,800"
    assert disclosure["mean_earnings_cents"] == 15833, "47,500 over three, rounded half up"
    assert disclosure["p90_earnings_cents"] == 23800, "the nearest-rank ninetieth percentile"
    assert disclosure["top_decile_share_bp"] == 5011, (
        "23,800 of 47,500 in basis points, rounded half up"
    )
    assert disclosure["zero_earner_count"] == 0, "all three consultants earned something"
    assert_bucket_counts_and_shares(disclosure, [0, 1, 2, 0], [0, 3333, 6667, 0])
    assert disclosure["status"] == "DRAFT", "a new statement starts at DRAFT"
    assert disclosure["revision_number"] == 0, "before any revision round trip"
    assert disclosure["period_code"] == "2026-08", "denormalised from the run"

    run_after = validate_success(api.get_commission_run(state["run"]["id"], ANALYST))
    assert run_after["version"] == run_version_before + 1, "the draft consumed the run's version"
    assert run_after["status"] == "PAID", "while the run itself is unchanged"


def test_paid_only_drops_the_carried_statement_and_lifts_every_figure(api):
    """The same run disclosed on the narrower basis loses exactly B's 500 cents and reports a
    higher median, mean and top-decile share on a population of two.

    PRD: "Under `PAID_ONLY`, the population is only those consultants whose `ACTIVE` statement in
    the run has `payout_status` `PAID`; statements carried forward below the minimum payout and
    consultants with no statement at all are excluded entirely, so `population_count` is smaller,
    `zero_earner_count` is normally 0, and the mean, median and ninetieth percentile all come out
    higher."

    Design: Difficulty/dual_variant_calc/income_disclosure_all_enrolled_vs_paid_only_divergence
    """
    state = _paid_three_generation_run(api)
    everyone = fx.draft_disclosure(api, state["run"], "ALL_ENROLLED")
    paid_only = fx.draft_disclosure(api, state["run"], "PAID_ONLY")
    assert_income_disclosure_statement(paid_only)

    assert paid_only["population_count"] == 2, "only the two disbursed consultants"
    assert paid_only["total_earnings_cents"] == 47000, "23,800 plus 23,200"
    assert paid_only["median_earnings_cents"] == 23500, "the average of the two central values"
    assert paid_only["mean_earnings_cents"] == 23500, "47,000 over two"
    assert paid_only["p90_earnings_cents"] == 23800, "the larger of the two values"
    assert paid_only["top_decile_share_bp"] == 5064, (
        "23,800 of 47,000 in basis points, rounded half up"
    )
    assert paid_only["zero_earner_count"] == 0, "a paid population has no non-earners"
    assert_bucket_counts_and_shares(paid_only, [0, 0, 2, 0], [0, 0, 10000, 0])
    assert paid_only["period_code"] == "2026-08", "both bases describe the same period"

    assert everyone["total_earnings_cents"] - paid_only["total_earnings_cents"] == 500, (
        "the whole divergence is B's carried-forward statement"
    )
    assert paid_only["population_count"] < everyone["population_count"], "a narrower population"
    assert paid_only["median_earnings_cents"] > everyone["median_earnings_cents"], (
        "which lifts the median for one and the same run"
    )
    assert paid_only["mean_earnings_cents"] > everyone["mean_earnings_cents"], "and the mean"
    assert paid_only["top_decile_share_bp"] > everyone["top_decile_share_bp"], (
        "and concentrates the top decile further"
    )
    assert paid_only["id"] != everyone["id"], "two drafts of the same run coexist"


def test_a_run_that_paid_nobody_still_discloses_and_the_review_loop_guards_itself(api):
    """PAID_ONLY has nothing to describe, ALL_ENROLLED describes a single zero earner, and each move
    of the review loop refuses the wrong state, the missing note and the submitter's own identity.

    PRD: "After the version check, the referenced run's `status` must be `PAID`, or the draft is
    refused with `ERR_RUN_NOT_PAID`; and the population the chosen basis selects must be non-empty,
    or the draft is refused with `ERR_DISCLOSURE_POPULATION_EMPTY` — a real possibility under
    `PAID_ONLY` when every statement of the run was carried forward."

    PRD: "Its checks run in this order: the caller's `X-User-ID` must differ from
    `submitted_by_user_id`, or `ERR_SEGREGATION_OF_DUTIES`; the underlying run must still be `PAID`,
    since a reversed run may not be disclosed, or `ERR_RUN_NOT_PAID`; the statement's `status` must
    be `LEGAL_REVIEW`, or `ERR_DISCLOSURE_NOT_IN_REVIEW`; and a `REQUEST_REVISION` decision must
    supply a `revision_note`, since the analyst must be told what to change, or
    `ERR_REVISION_NOTE_REQUIRED`."

    Design: Corner/errors/a_run_that_pays_nobody_still_discloses_and_the_review_loop_guards_itself
    """
    state = _paid_run_that_pays_nobody(api)
    run = validate_success(api.get_commission_run(state["run"]["id"], ANALYST))

    validate_error(
        api.create_income_disclosure_statement(
            f.income_disclosure_payload(run["id"], run["version"], "PAID_ONLY"), ANALYST
        ),
        "ERR_DISCLOSURE_POPULATION_EMPTY",
        422,
    )
    validate_error(
        api.create_income_disclosure_statement(
            f.income_disclosure_payload(run["id"], run["version"] - 1, "ALL_ENROLLED"), ANALYST
        ),
        "ERR_STALE_RUN_VERSION",
        412,
    )

    disclosure = fx.draft_disclosure(api, run, "ALL_ENROLLED")
    assert_income_disclosure_statement(disclosure)
    assert disclosure["population_count"] == 1, "the one enrolled consultant is the population"
    assert disclosure["zero_earner_count"] == 1, "and she earned nothing"
    assert disclosure["total_earnings_cents"] == 0, "so the total is zero"
    assert disclosure["median_earnings_cents"] == 0, "as are the median"
    assert disclosure["mean_earnings_cents"] == 0, "the mean"
    assert disclosure["p90_earnings_cents"] == 0, "and the ninetieth percentile"
    assert disclosure["top_decile_share_bp"] == 0, (
        "the share is defined as 0 when total earnings are 0 rather than dividing by zero"
    )
    assert_bucket_counts_and_shares(disclosure, [1, 0, 0, 0], [10000, 0, 0, 0])
    assert disclosure["status"] == "DRAFT", "the draft stands"

    validate_error(
        api.decide_disclosure_legal_review(
            disclosure["id"], f.legal_decision_payload("PUBLISH"), LEGAL
        ),
        "ERR_DISCLOSURE_NOT_IN_REVIEW",
        409,
    )

    submitted = fx.submit_disclosure(api, disclosure)
    assert submitted["status"] == "LEGAL_REVIEW", "DRAFT moves into review"
    assert submitted["submitted_by_user_id"] == k.ANALYST_USER_ID, (
        "the submitter is recorded for the segregation test"
    )
    validate_error(
        api.submit_disclosure_for_legal_review(disclosure["id"], None, ANALYST),
        "ERR_DISCLOSURE_NOT_DRAFT",
        409,
    )

    validate_error(
        api.decide_disclosure_legal_review(
            disclosure["id"], f.legal_decision_payload("REQUEST_REVISION"), LEGAL
        ),
        "ERR_REVISION_NOTE_REQUIRED",
        422,
    )
    validate_error(
        api.decide_disclosure_legal_review(
            disclosure["id"],
            f.legal_decision_payload("PUBLISH"),
            make_headers(k.ANALYST_USER_ID, "LegalReviewer"),
        ),
        "ERR_SEGREGATION_OF_DUTIES",
        409,
    )

    returned = validate_success(
        api.decide_disclosure_legal_review(
            disclosure["id"],
            f.legal_decision_payload("REQUEST_REVISION", "Add a footnote on non-earners"),
            LEGAL,
        )
    )
    assert returned["status"] == "DRAFT", "a revision request sends the statement back"
    assert returned["revision_number"] == 1, "and counts the round trip"
    assert returned["submitted_by_user_id"] is None, (
        "the submitter is cleared so the segregation test is re-armed against whoever resubmits"
    )


def test_an_identical_second_draft_is_refused_because_the_first_moved_the_version(api):
    """Nothing about the run changed, yet the replayed token is stale: the draft itself consumed it,
    and the refreshed token buys a second coexisting draft.

    PRD: "The statement row is written only when that value equals the run's current `version`;
    otherwise no row is created and the request is rejected with `ERR_STALE_RUN_VERSION`
    (HTTP 412)."

    PRD: "A successful create increments the run's `version` by 1, so a second draft attempt reusing
    the stale expected value is rejected and the caller must re-read the run."

    Design: Corner/cross-cutting complexity layers/drafting_a_disclosure_consumes_the_run_version_it_quoted
    """
    state = _paid_run_that_pays_nobody(api)
    quoted_version = validate_success(
        api.get_commission_run(state["run"]["id"], ANALYST)
    )["version"]
    payload = f.income_disclosure_payload(state["run"]["id"], quoted_version, "ALL_ENROLLED")

    first = validate_success(api.create_income_disclosure_statement(payload, ANALYST), 201)
    assert first["population_count"] == 1, "the first draft is written"
    assert first["status"] == "DRAFT", "and stands as a draft"

    validate_error(
        api.create_income_disclosure_statement(payload, ANALYST), "ERR_STALE_RUN_VERSION", 412
    )

    refreshed = validate_success(api.get_commission_run(state["run"]["id"], ANALYST))
    assert refreshed["version"] == quoted_version + 1, "the create moved the run's version"
    assert refreshed["status"] == "PAID", "though the run's state and money are untouched"
    assert refreshed["paid_total_cents"] == 0, "nothing was disbursed by a disclosure"

    second = validate_success(
        api.create_income_disclosure_statement(
            f.income_disclosure_payload(refreshed["id"], refreshed["version"], "ALL_ENROLLED"),
            ANALYST,
        ),
        201,
    )
    assert second["id"] != first["id"], "the retry writes a second statement"
    assert second["population_count"] == 1, "over the same population"
    both = validate_success(
        api.list_income_disclosure_statements(
            ANALYST, params={"commission_run_id": state["run"]["id"], "status": "DRAFT"}
        )
    )
    assert len(both) == 2, "two coexisting drafts of one run are legal until one is published"


def test_a_cascading_write_is_already_visible_in_its_own_response_and_the_next_read(api):
    """The terminate response itself carries the recomputed downline counter, and the reads that
    follow show the promoted child and the rewritten depth below her with no lag.

    PRD: "`direct_downline_count` is recomputed on both ends: it falls to 0 on the terminated
    consultant and rises on the receiving grandparent by the number of children it inherited."

    PRD: "`upline_path` and `genealogy_depth` are recomputed for every reassigned consultant and,
    transitively, for every descendant of a reassigned consultant."

    Design: Corner/consistency model/every_side_effect_of_a_write_is_readable_in_the_next_request
    """
    env = fx.setup_environment(api)
    people = fx.setup_genealogy_abc(api, env)

    before = fx.read_consultant(api, people["a"]["id"])
    assert before["direct_downline_count"] == 1, "A carries one direct child before the write"
    assert before["status"] == "ACTIVE", "and is active"

    response = fx.terminate_consultant(api, people["a"], termination_reason="VOLUNTARY")
    assert response["status"] == "TERMINATED", "the new status is in the mutating response"
    assert response["direct_downline_count"] == 0, (
        "the derived counter is recomputed inside the same request, not on a later sweep"
    )
    assert_instant(response["terminated_at"], k.INITIAL_CLOCK, "terminated_at")

    promoted = fx.read_consultant(api, people["b"]["id"])
    assert promoted["sponsor_consultant_id"] is None, "B is promoted to root on the very next read"
    assert promoted["reassigned_from_sponsor_consultant_id"] == people["a"]["id"], (
        "and the edge she was moved off is already remembered"
    )
    assert promoted["genealogy_depth"] == 0, "her depth is rewritten immediately"
    assert promoted["reassignment_count"] == 1, "the move is counted once"

    deeper = fx.read_consultant(api, people["c"]["id"])
    assert deeper["sponsor_consultant_id"] == people["b"]["id"], "C keeps her own edge"
    assert deeper["reassignment_count"] == 0, "she was never reassigned"
    assert deeper["genealogy_depth"] == 1, "yet her depth already reflects her ancestor's move"
    assert deeper["upline_path"] == [people["b"]["id"]], "and so does her path"
