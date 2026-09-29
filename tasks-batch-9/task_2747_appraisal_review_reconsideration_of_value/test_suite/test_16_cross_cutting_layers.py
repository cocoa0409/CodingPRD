"""
Cross-cutting layers: guard tokens, fiscal ceilings and threshold cascades.

Each of the three stale-read-guarded writes is driven twice — once with the token the caller
read before somebody else wrote, and once with the token that is actually current — so that
the refusal and the acceptance are seen over the same body. The escalation ledger is then
driven to land exactly on a company's budget and refused one cent-worth of order later. And
an appraiser's rolling standing is walked across both of its thresholds, one revision at a
time, to show which comparison is strict and which cascade step is skipped.
"""

from test_helpers import (
    CHIEF_APPRAISER_HEADERS,
    DESK_REVIEWER_HEADERS,
    ApiErrorId,
    assert_instant,
    factories as f,
    fixtures as fx,
    make_amc_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

CLEAN_GRID = [
    {
        "street_address": "1 Alder Street",
        "sale_price_cents": 39000000,
        "gross_adjustment_cents": 390000,
        "net_adjustment_cents": 390000,
        "distance_miles": 1.0,
        "sale_date": "2026-05-01T00:00:00Z",
    },
    {
        "street_address": "2 Alder Street",
        "sale_price_cents": 40000000,
        "gross_adjustment_cents": 400000,
        "net_adjustment_cents": 0,
        "distance_miles": 1.5,
        "sale_date": "2026-06-01T00:00:00Z",
    },
    {
        "street_address": "3 Alder Street",
        "sale_price_cents": 41000000,
        "gross_adjustment_cents": 410000,
        "net_adjustment_cents": -410000,
        "distance_miles": 2.0,
        "sale_date": "2026-06-15T00:00:00Z",
    },
]


def _author(license_number, full_name="Alice Author"):
    return {
        "full_name": full_name,
        "license_number": license_number,
        "license_state": "CA",
    }


def _screened_with_a_stale_token(api):
    env = fx.delivered_report(
        api,
        amc={"name": "OCC Desk AMC"},
        appraiser=_author("CA-AL-C601"),
        loan={"loan_number": "LN-2747-C601", "borrower_display_name": "Val Borrower"},
        comparables=[dict(row) for row in CLEAN_GRID],
    )
    env["stale_version"] = fx.read_appraisal(api, env["appraisal"]["id"])["version"]
    env["appraisal"] = fx.run_rule_checks(api, env["appraisal"]["id"])
    env["appraisal"] = fx.run_bias_screen(api, env["appraisal"]["id"])
    return env


def test_two_scoring_runs_each_advance_the_appraisal_past_the_callers_read(api):
    """Both scoring actions are writes, so a pre-scoring read is two versions behind.

    The version observed before the battery ran is left behind by the battery and then again
    by the screen, and each of those runs advances the appraisal by exactly one.

    PRD: "running the rule checks, running the bias screen, and opening a desk review each
    bump the appraisal's `version`;"

    Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_desk_review_create_rejects_stale_appraisal_version
    """
    env = _screened_with_a_stale_token(api)

    assert env["appraisal"]["version"] == env["stale_version"] + 2
    assert env["appraisal"]["review_status"] == "RULES_CLEARED"
    assert env["appraisal"]["bias_screen_status"] == "CLEAR"


def test_opening_a_review_from_a_pre_scoring_read_is_refused(api):
    """A stale token means the review would have been scored from superseded numbers.

    The token offered is the one the caller read before either scoring action ran. The open is
    refused on the concurrency rung, no review row is created, and the appraisal is left where
    the screen left it — which also means its grid is still unlocked.

    PRD: "`POST /appraisal-desk/desk-reviews` requires `expected_appraisal_version`, matching
    the current `version` of the appraisal named in the body. Another reviewer may have
    re-run the rule checks in the interim, which rewrites `completeness_score_bps` and the
    rule-check tallies that the preliminary quality score is computed from; a stale token
    means the review being opened would be scored from superseded numbers, so it is refused
    with `ERR_STALE_VERSION` and HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_desk_review_create_rejects_stale_appraisal_version
    """
    env = _screened_with_a_stale_token(api)

    response = api.create_desk_review(
        f.desk_review_payload(
            env["appraisal"]["id"],
            env["stale_version"],
            reviewer_note="Opening from a stale read.",
        ),
        DESK_REVIEWER_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION, 412)

    _, meta = validate_paginated(api.list_desk_reviews(DESK_REVIEWER_HEADERS))
    assert meta["total_count"] == 0
    after = fx.read_appraisal(api, env["appraisal"]["id"])
    assert after["review_status"] == "RULES_CLEARED"
    assert after["version"] == env["appraisal"]["version"]


def test_opening_the_same_review_from_the_current_read_succeeds(api):
    """With the current token the open lands and spends it in turn.

    Only the token changes. The review is created in draft carrying the score computed from
    the battery that has already run, the appraisal moves into review, and the open itself
    advances the appraisal's version once more.

    PRD: "`POST /appraisal-desk/desk-reviews` requires `expected_appraisal_version`, matching
    the current `version` of the appraisal named in the body."

    PRD: "It moves the appraisal to `IN_DESK_REVIEW` and increments the appraisal's `version`
    by 1."

    Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_desk_review_create_rejects_stale_appraisal_version
    """
    env = _screened_with_a_stale_token(api)
    current = env["appraisal"]["version"]

    review = validate_success(
        api.create_desk_review(
            f.desk_review_payload(
                env["appraisal"]["id"],
                current,
                reviewer_note="Opening from the current read.",
            ),
            DESK_REVIEWER_HEADERS,
        ),
        201,
    )

    assert review["status"] == "DRAFT"
    assert review["preliminary_quality_score_bps"] == 10000
    after = fx.read_appraisal(api, env["appraisal"]["id"])
    assert after["review_status"] == "IN_DESK_REVIEW"
    assert after["version"] == current + 1


def _spine_and_first_delivery(api):
    """A panel, a loan file, and one report already delivered against it."""
    env = fx.panel_and_loan(
        api,
        amc={"name": "OCC Intake AMC"},
        appraiser=_author("CA-AL-C602"),
        loan={"loan_number": "LN-2747-C602", "borrower_display_name": "Wyn Borrower"},
    )
    env["loan_version_before"] = env["loan"]["version"]
    env["appraisal"] = fx.deliver_appraisal(
        api, env["loan"]["id"], env["appraiser"]["id"], env["amc"]["id"]
    )
    return env


def _redelivery(env, expected_loan_file_version):
    return f.appraisal_payload(
        env["loan"]["id"],
        env["appraiser"]["id"],
        env["amc"]["id"],
        expected_loan_file_version,
        effective_date="2026-07-16T00:00:00Z",
        reported_value_cents=40500000,
    )


def test_a_second_delivery_reusing_the_consumed_loan_token_is_refused(api):
    """The first delivery spent the loan file token the company was holding.

    The company re-delivers against the same loan with the version it read before its own
    first delivery landed. The write is refused, no second report exists, and the author's
    report tally is still one.

    PRD: "`POST /appraisal-desk/appraisals` requires `expected_loan_file_version`, matching
    the current `version` of the loan file named in the body. A prior delivery may already
    have landed and superseded the report the AMC believed was current, so a stale token means
    the caller's supersede pointer and risk-tier assumptions no longer describe the loan it is
    writing to; the delivery is refused with `ERR_STALE_VERSION` and HTTP 412."

    PRD: "The delivery increments the loan file's `version` by 1, increments the authoring
    appraiser's `total_appraisal_count`, and recomputes both of that appraiser's
    performance-score variants"

    Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_appraisal_intake_rejects_stale_loan_file_version
    """
    env = _spine_and_first_delivery(api)
    stale = env["loan_version_before"]

    response = api.create_appraisal(
        _redelivery(env, stale), make_amc_headers(env["amc"]["id"])
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION, 412)

    _, meta = validate_paginated(
        api.list_appraisals(CHIEF_APPRAISER_HEADERS, {"loan_file_id": env["loan"]["id"]})
    )
    assert meta["total_count"] == 1
    assert fx.read_appraiser(api, env["appraiser"]["id"])["total_appraisal_count"] == 1
    assert fx.read_loan_file(api, env["loan"]["id"])["version"] == stale + 1


def test_the_same_second_delivery_lands_on_the_refreshed_loan_token(api):
    """Re-reading the loan file yields the token the second delivery needs.

    The body is unchanged apart from the guard token. The new report is born in the same
    initial pair of statuses as any first delivery, the first report is untouched because no
    supersede pointer was supplied, and the loan file's version moves once more.

    PRD: "A successful delivery is created with `version` 1, with `review_status` `RECEIVED`
    and `bias_screen_status` `NOT_SCREENED`, and with every derived field empty:
    `completeness_score_bps`, `indicated_value_cents`, `variance_vs_reported_bps`,
    `bias_risk_index`, `current_value_cents`, and `quarantine_return_status` are all null,
    while `eligible_comp_count`, `closed_comp_count`, `max_gross_adjustment_bps`,
    `max_net_adjustment_bps`, `rule_check_fail_count`, and `rule_check_warn_count` all start
    at 0."

    PRD: "When the optional `supersedes_appraisal_id` is supplied it must name an existing
    appraisal — a dangling pointer yields `ERR_APPRAISAL_NOT_FOUND` — and that appraisal's
    `review_status` must be exactly `RETURNED_TO_AMC`. The replacement is created in
    `RECEIVED` and the superseded report moves `RETURNED_TO_AMC → SUPERSEDED`, which is the
    only terminal state on the review dimension."

    Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_appraisal_intake_rejects_stale_loan_file_version
    """
    env = _spine_and_first_delivery(api)
    current = fx.read_loan_file(api, env["loan"]["id"])["version"]
    assert current == env["loan_version_before"] + 1

    second = validate_success(
        api.create_appraisal(
            _redelivery(env, current), make_amc_headers(env["amc"]["id"])
        ),
        201,
    )

    assert second["version"] == 1
    assert second["review_status"] == "RECEIVED"
    assert second["bias_screen_status"] == "NOT_SCREENED"
    assert fx.read_appraisal(api, env["appraisal"]["id"])["review_status"] == "RECEIVED"
    assert fx.read_appraiser(api, env["appraiser"]["id"])["total_appraisal_count"] == 2
    assert fx.read_loan_file(api, env["loan"]["id"])["version"] == current + 1


def _monitored_appraiser(api):
    """An appraiser whose standing has been reviewed once before anyone enrols them."""
    amc = fx.create_amc(api, name="OCC Panel AMC")
    appraiser = fx.create_appraiser(api, **_author("CA-AL-C603"))
    monitored = fx.panel_review(
        api, appraiser["id"], "MONITOR",
        note="Baseline monitoring before enrolment.",
    )
    return amc, appraiser, monitored


def test_monitoring_spends_a_version_without_moving_either_score(api):
    """The read-and-recompute action is still a write on the appraiser.

    Nothing about a brand-new appraiser's standing can change, so both score variants come
    back at the opening figure — yet the review has consumed the caller's token all the same.

    PRD: "Every panel review increments the appraiser's `version` by 1, and a mismatched
    version is rejected before anything else happens."

    PRD: "A new appraiser starts with both score variants at a perfect 10000 basis points:
    `performance_score_bps` and `lifetime_performance_score_bps` are each initialised to
    10000."

    Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_panel_membership_rejects_stale_appraiser_version
    """
    _, appraiser, monitored = _monitored_appraiser(api)

    assert monitored["version"] == appraiser["version"] + 1
    assert monitored["performance_score_bps"] == 10000
    assert monitored["lifetime_performance_score_bps"] == 10000
    assert monitored["panel_status"] == "ACTIVE"


def test_enrolling_on_the_pre_monitoring_token_is_refused(api):
    """A token read before the panel review no longer describes the appraiser's standing.

    The enrolment is refused on the concurrency rung and the appraiser's membership tally is
    left at zero.

    PRD: "`POST /appraisal-desk/panel-memberships` requires `expected_appraiser_version`,
    matching the current `version` of the appraiser named in the body. A panel-review action
    may already have moved that appraiser's `panel_status`, so a stale token means the caller
    is enrolling an appraiser whose standing it has not observed; the enrolment is refused
    with `ERR_STALE_VERSION` and HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_panel_membership_rejects_stale_appraiser_version
    """
    amc, appraiser, _ = _monitored_appraiser(api)

    response = api.create_panel_membership(
        f.panel_membership_payload(appraiser["id"], amc["id"], appraiser["version"]),
        CHIEF_APPRAISER_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION, 412)

    after = fx.read_appraiser(api, appraiser["id"])
    assert after["panel_membership_count"] == 0
    _, meta = validate_paginated(
        api.list_panel_memberships(
            CHIEF_APPRAISER_HEADERS, {"appraiser_id": appraiser["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_the_post_monitoring_token_enrols_and_is_itself_consumed(api):
    """Each accepted write invalidates exactly one token.

    Enrolling with the version the panel review left behind succeeds, and the enrolment then
    spends that version in turn — so replaying the very same body is stale on the second try.

    PRD: "Enrolment is one of the three operations guarded by the stale-read token of §2.6, so
    `expected_appraiser_version` must carry the appraiser's current `version`; a successful
    enrolment increments that appraiser's `version` by 1 and increments the appraiser's
    `panel_membership_count`."

    Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_panel_membership_rejects_stale_appraiser_version
    """
    amc, _, monitored = _monitored_appraiser(api)
    token = monitored["version"]
    body = f.panel_membership_payload(monitored["id"], amc["id"], token)

    membership = validate_success(
        api.create_panel_membership(body, CHIEF_APPRAISER_HEADERS), 201
    )
    assert membership["status"] == "ACTIVE"
    assert membership["coverage_state"] == "CA"
    assert membership["tier"] == "GENERAL"

    after = fx.read_appraiser(api, monitored["id"])
    assert after["panel_membership_count"] == 1
    assert after["version"] == token + 1

    replay = api.create_panel_membership(body, CHIEF_APPRAISER_HEADERS)
    validate_error(replay, ApiErrorId.ERR_STALE_VERSION, 412)


def _two_field_review_orders(api):
    """One company at a 45000-cent budget with two field-review orders waiting to be staffed.

    Both reports are authored by the same appraiser and carry a single exhibit against a
    high-risk loan, which is what drives the escalation the desk review then orders. A second
    panel member is enrolled as the candidate reviewer, since nobody reviews their own report.
    """
    amc = fx.create_amc(api, name="Budget Ceiling AMC", escalation_budget_cents=45000)
    author = fx.create_appraiser(api, **_author("CA-AL-C604"))
    reviewer = fx.create_appraiser(api, **_author("CA-BR-C604", "Bruno Backup"))
    fx.enroll_on_panel(api, author["id"], amc["id"])
    fx.enroll_on_panel(api, reviewer["id"], amc["id"], tier="REVIEW_SPECIALIST")

    orders = []
    for suffix, borrower in (("A", "Xia Borrower"), ("B", "Yan Borrower")):
        loan = fx.create_loan_file(
            api,
            loan_number="LN-2747-C604%s" % suffix,
            risk_tier="HIGH",
            borrower_display_name=borrower,
        )
        appraisal = fx.deliver_appraisal(
            api, loan["id"], author["id"], amc["id"], exhibit_count=1
        )
        fx.add_comparables(
            api, appraisal["id"], amc["id"], [dict(row) for row in CLEAN_GRID]
        )
        fx.run_rule_checks(api, appraisal["id"])
        fx.run_bias_screen(api, appraisal["id"])
        review = fx.open_desk_review(api, appraisal["id"])
        fx.submit_desk_review(api, review["id"], findings_note="Thin exhibits.")
        fx.decide_desk_review(
            api, review["id"], "ESCALATE", decision_note="Field review."
        )
        orders.append(fx.escalation_order_for(api, review["id"]))
    return amc, reviewer, orders


def test_an_assignment_that_lands_exactly_on_the_budget_is_allowed(api):
    """The ceiling is a must-not-exceed, so spending the last cent of it is permitted.

    Exactly seventy-two hours of turnaround remain, so the rush test — which is strict — does
    not fire, and a 45000-cent subtotal sits below the first discount tier. The company's
    year-to-date spend therefore comes to rest on its budget rather than over it.

    PRD: "Step two decides the rush surcharge from the turnaround still remaining at the
    instant of assignment: take the number of hours from the logical clock to the order's
    `due_at`, and treat the order as rush when that remaining figure is **strictly less than**
    72 hours — exactly 72.0 hours remaining is not rush. A rush order's `rush_surcharge_cents`
    is 30 percent of the base fee, rounded half-up to whole cents; a non-rush order's surcharge
    is 0. Step three picks the volume discount tier from the **post-surcharge subtotal**, being
    base fee plus surcharge: a subtotal below 50000 cents earns `discount_pct_bps` of 0;"

    PRD: "the company's `ytd_escalation_spend_cents` plus this order's freshly computed
    `total_cost_cents` must not exceed its `escalation_budget_cents`"

    Design: Corner/cross_cutting_complexity_layers/rate_threshold_escalation_budget_accepted_at_the_exact_ceiling
    """
    amc, reviewer, orders = _two_field_review_orders(api)

    assigned = validate_success(
        api.assign_escalation_order(
            orders[0]["id"],
            f.assign_payload(
                reviewer["id"], "2026-08-02T09:00:00Z", "2026-08-02T12:00:00Z"
            ),
            CHIEF_APPRAISER_HEADERS,
        )
    )

    assert assigned["status"] == "ASSIGNED"
    assert assigned["escalation_type"] == "FIELD_REVIEW"
    assert_instant(assigned["due_at"], "2026-08-04T00:00:00Z", "due_at")
    assert assigned["base_fee_cents"] == 45000
    assert assigned["rush_surcharge_cents"] == 0
    assert assigned["discount_pct_bps"] == 0
    assert assigned["total_cost_cents"] == 45000

    company = fx.read_amc(api, amc["id"])
    assert company["ytd_escalation_spend_cents"] == 45000
    assert company["ytd_escalation_spend_cents"] == company["escalation_budget_cents"]


def test_the_next_order_against_an_exhausted_budget_is_refused(api):
    """A second identically priced order would take the company past its ceiling.

    The window chosen for the second order starts at 15:00, comfortably clear of the first
    window widened by the ninety-minute travel buffer to 07:30–13:30, so the conflict rung
    cannot be what refuses it. Nothing is written: the order keeps its null cost fields and
    null assignee, the ledger does not move, and the candidate still holds exactly one open
    assignment.

    PRD: "the **travel buffer of 90 minutes is applied to the existing window on both sides,
    while the incoming window is compared bare**"

    PRD: "an assignment that would breach the ceiling is refused with
    `ERR_ESCALATION_BUDGET_EXCEEDED` (HTTP 402) with no cost fields written and no window
    reserved."

    Design: Corner/cross_cutting_complexity_layers/rate_threshold_escalation_budget_accepted_at_the_exact_ceiling
    """
    amc, reviewer, orders = _two_field_review_orders(api)
    fx.assign_order(api, orders[0]["id"], reviewer["id"])

    response = api.assign_escalation_order(
        orders[1]["id"],
        f.assign_payload(reviewer["id"], "2026-08-02T15:00:00Z", "2026-08-02T17:00:00Z"),
        CHIEF_APPRAISER_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_ESCALATION_BUDGET_EXCEEDED, 402)

    refused = fx.read_escalation_order(api, orders[1]["id"])
    assert refused["status"] == "PENDING_ASSIGNMENT"
    assert refused["assigned_appraiser_id"] is None
    assert refused["base_fee_cents"] is None
    assert refused["total_cost_cents"] is None
    assert refused["inspection_window_start"] is None
    assert fx.read_amc(api, amc["id"])["ytd_escalation_spend_cents"] == 45000
    assert fx.read_appraiser(api, reviewer["id"])["open_assignment_count"] == 1


def _two_reports_awaiting_reconsideration(api):
    """One author, two graded reports, each with a routed reconsideration on the appraiser's desk.

    Both reports are valued at the same figure and carry the same clean grid, so the only
    thing that will move the author's standing is how many of the two reconsiderations end in
    a revision.
    """
    amc = fx.create_amc(api, name="Cascade Boundary AMC")
    author = fx.create_appraiser(api, **_author("CA-AL-C605"))
    fx.enroll_on_panel(api, author["id"], amc["id"])

    envs = []
    for suffix, borrower, prefix in (
        ("A", "Zoe Borrower", "Alpha"),
        ("B", "Abe Borrower", "Bravo"),
    ):
        loan = fx.create_loan_file(
            api,
            loan_number="LN-2747-C605%s" % suffix,
            borrower_display_name=borrower,
        )
        appraisal = fx.deliver_appraisal(api, loan["id"], author["id"], amc["id"])
        fx.add_comparables(
            api, appraisal["id"], amc["id"], [dict(row) for row in CLEAN_GRID]
        )
        env = {
            "amc": amc,
            "appraiser": author,
            "loan": loan,
            "appraisal": fx.run_rule_checks(api, appraisal["id"]),
        }
        envs.append(
            fx.rov_awaiting_appraiser(
                api, env, requested_value_cents=40600000, prefix=prefix
            )
        )
    return author, envs


def _revise(api, env, author_id):
    return fx.rov_respond(
        api, env["rov"]["id"], author_id, "VALUE_REVISED",
        response_note="Adopting the two closer sales.",
        revised_value_cents=40600000,
    )


def test_one_revision_in_two_reports_lands_on_the_probation_threshold(api):
    """A rolling score of exactly 7000 is not below 7000, so standing does not move.

    One revision over two reports is a rate of 5000 basis points, and sixty percent of that
    is the only penalty in play, leaving the score sitting precisely on the probation
    threshold. Because the automatic edge requires the score to be strictly below that
    threshold, the appraiser stays active with no probation stamp.

    PRD: "`revision_rate_bps` is zero when the appraisal count is zero — a brand-new appraiser
    is not penalised for having no history — and otherwise is 10000 multiplied by the revision
    count, divided by the appraisal count, rounded half up. The score then starts at 10000 and
    subtracts three penalties: 0.60 multiplied by `revision_rate_bps` and rounded half up, plus
    1200 for each entry in `substantiated_bias_count`, plus 400 for each entry in
    `sla_miss_count`."

    PRD: "A rolling score below 7000 but at or above 5500 moves the appraiser
    `ACTIVE → PROBATION`, stamping `probation_started_at` from the logical clock."

    Design: Corner/cross_cutting_complexity_layers/rate_threshold_probation_cascade_lands_exactly_on_the_threshold
    """
    author, envs = _two_reports_awaiting_reconsideration(api)
    responded = _revise(api, envs[0], author["id"])
    assert responded["status"] == "RESPONDED"
    assert responded["outcome"] == "VALUE_REVISED"

    after_one = fx.read_appraiser(api, author["id"])
    assert after_one["total_appraisal_count"] == 2
    assert after_one["revision_rate_bps"] == 5000
    assert after_one["performance_score_bps"] == 7000
    assert after_one["panel_status"] == "ACTIVE"
    assert after_one["probation_started_at"] is None


def test_the_second_revision_suspends_the_appraiser_outright(api):
    """A score of 4000 skips probation and stops short of removal.

    Revising both reports takes the rate to 10000 basis points and the score to 4000, which is
    below the suspension threshold as well as the probation one — so the appraiser lands in
    suspension directly rather than stepping through probation. Even at 4000 the automatic
    cascade leaves removal alone, and the lifetime variant agrees with the rolling one because
    every report and every revision here is inside the rolling window.

    PRD: "A rolling score below 5500 moves the appraiser `ACTIVE → SUSPENDED` or
    `PROBATION → SUSPENDED`. All three of those automatic edges also move the appraiser's
    `ASSIGNED` second-appraisal orders to `REASSIGNMENT_REQUIRED`, so degraded standing
    releases the work in flight. The automatic cascade never reaches `REMOVED`, even when the
    rolling score falls below 4000 — removal is always a deliberate act."

    PRD: "the appraisal moves `VALUE_CONTESTED → VALUE_REVISED`, a value revision with
    `source_type` `ROV` is written, the appraisal's `current_value_cents` is set to the revised
    value, the loan file's `collateral_status` moves `VALUE_CONTESTED → VALUE_REVISED` with its
    value, `ltv_bps`, and `decision_impact` recomputed and the underwriting cascade following,
    and the appraiser's revision tally is incremented with both performance-score variants
    recomputed."

    Design: Corner/cross_cutting_complexity_layers/rate_threshold_probation_cascade_lands_exactly_on_the_threshold
    """
    author, envs = _two_reports_awaiting_reconsideration(api)
    _revise(api, envs[0], author["id"])
    _revise(api, envs[1], author["id"])

    after_two = fx.read_appraiser(api, author["id"])
    assert after_two["revision_rate_bps"] == 10000
    assert after_two["performance_score_bps"] == 4000
    assert after_two["lifetime_performance_score_bps"] == 4000
    assert after_two["panel_status"] == "SUSPENDED"
    assert after_two["total_appraisal_count"] == 2

    for env in envs:
        appraisal = fx.read_appraisal(api, env["appraisal"]["id"])
        assert appraisal["review_status"] == "VALUE_REVISED"
        assert appraisal["current_value_cents"] == 40600000
