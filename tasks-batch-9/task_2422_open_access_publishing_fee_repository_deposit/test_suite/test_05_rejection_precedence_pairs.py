"""Rejection precedence: one call that violates two rules at once must report the
earlier rule, and the later rule only surfaces once the earlier violation is cleared.

Both scenarios pair rules from different categories — a state precondition against a
fiscal ceiling, and a safety gate against a referential gate.
"""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_eligibility_check_payload,
    create_decision_payload,
    list_request_allocations,
    open_fund,
    open_fund_request,
    read_article,
    read_fund,
    read_fund_request,
    read_grant,
    read_publisher,
    record_article,
    record_grant,
    register_author,
    register_funder,
    register_journal,
    register_publisher,
    request_more_information,
    resubmit_request,
    run_compliance_sweep,
    run_eligibility_check,
    screen_publisher,
    set_clock,
    start_review,
    validate_error,
)

LIBRARIAN = TEST_USERS["librarian_headers"]
FUND_MANAGER = TEST_USERS["fund_manager_headers"]

BLOCKED_AUTHOR_GUIDANCE = (
    "Venue blocked: eligibility checks are refused; contact the scholarly "
    "communications office."
)


# --------------------------------------------------------------------------- #
# preambles
# --------------------------------------------------------------------------- #
def _setup_zero_cap_request_in_info_requested() -> dict:
    """A fund request for 300000 driven to INFO_REQUESTED for an author whose annual
    cap is explicitly zero, so an approval violates both the state precondition and
    the author-cap ceiling at once."""
    set_clock("2026-08-05T00:00:00Z")
    publisher = register_publisher(
        publisher_code="HALDEN", name="Halden Open Science", country_code="NO"
    )
    journal = register_journal(
        publisher["id"],
        issn="2515-0847",
        title="Halden Journal of Open Metabolism",
        oa_model="FULLY_OA",
        list_apc_cents=300000,
        required_embargo_months=12,
    )
    author = register_author(
        full_name="Nadia Fors",
        email="nadia.fors@uni.example",
        orcid="0000-0004-1111-2222",
        department_code="MET",
        affiliation_status="ELIGIBLE_FACULTY",
        appointment_from="2024-01-01",
        appointment_until="2028-12-31",
        annual_cap_cents=0,
    )
    funder = register_funder(
        name="National Research Council",
        funder_code="NRC",
        mandate_type="GOLD_OA",
        max_embargo_months=6,
        deposit_deadline_days=90,
        license_required="CC_BY",
        apc_allowable=True,
    )
    grant = record_grant(
        funder["id"],
        author["id"],
        grant_number="NRC-2026-201",
        award_from="2026-01-01",
        award_until="2027-12-31",
        apc_budget_cents=900000,
    )
    fund = open_fund(
        fund_code="OA-CENTRAL-2027",
        fiscal_year=2027,
        period_from="2026-07-01",
        period_to="2027-06-30",
        total_budget_cents=1000000,
        priority_rank=1,
        eligible_affiliation_statuses=["ELIGIBLE_FACULTY"],
        per_article_cap_cents=300000,
    )
    article = record_article(
        journal["id"],
        author["id"],
        grant_id=grant["id"],
        manuscript_title="Capped authors and reviewable states",
        accepted_on="2026-08-05",
    )
    determination = run_eligibility_check(article["id"], basis="PROVISIONAL")
    request = open_fund_request(article["id"], author["id"], 300000)
    start_review(request["id"])
    request_more_information(
        request["id"], info_needed="Confirm the author's remaining annual allowance."
    )
    return {
        "publisher": publisher,
        "journal": journal,
        "author": author,
        "funder": funder,
        "grant": grant,
        "fund": fund,
        "article": article,
        "determination": determination,
        "request": request,
    }


def _setup_blocked_and_cleared_publishers_on_a_closed_grant() -> dict:
    """Two publishers sharing one grant that the sweep has closed; the first
    publisher has been screened to a BLOCKED verdict, the second is untouched."""
    set_clock("2026-08-01T00:00:00Z")
    blocked_publisher = register_publisher(
        publisher_code="APEXR", name="Apex Rapid Publications", country_code="SG"
    )
    cleared_publisher = register_publisher(
        publisher_code="HALDEN", name="Halden Open Science", country_code="NO"
    )
    blocked_journal = register_journal(
        blocked_publisher["id"],
        issn="2666-1667",
        title="Apex Rapid Journal of Life Sciences",
        oa_model="FULLY_OA",
        list_apc_cents=300000,
        required_embargo_months=12,
    )
    cleared_journal = register_journal(
        cleared_publisher["id"],
        issn="2515-0847",
        title="Halden Journal of Open Metabolism",
        oa_model="FULLY_OA",
        list_apc_cents=300000,
        required_embargo_months=12,
    )
    author = register_author(
        full_name="Sofia Lund",
        email="sofia.lund@uni.example",
        orcid="0000-0005-3333-4444",
        department_code="BIO",
        affiliation_status="ELIGIBLE_FACULTY",
        appointment_from="2024-01-01",
        appointment_until="2028-12-31",
        annual_cap_cents=500000,
    )
    funder = register_funder(
        name="National Research Council",
        funder_code="NRC",
        mandate_type="GOLD_OA",
        max_embargo_months=6,
        deposit_deadline_days=90,
        license_required="CC_BY",
        apc_allowable=True,
    )
    grant = record_grant(
        funder["id"],
        author["id"],
        grant_number="NRC-2026-330",
        award_from="2026-01-01",
        award_until="2026-08-15",
        apc_budget_cents=900000,
    )
    blocked_article = record_article(
        blocked_journal["id"],
        author["id"],
        grant_id=grant["id"],
        manuscript_title="Rapid-review submission on the blocked venue",
        accepted_on="2026-08-05",
    )
    cleared_article = record_article(
        cleared_journal["id"],
        author["id"],
        grant_id=grant["id"],
        manuscript_title="Companion study on the cleared venue",
        accepted_on="2026-08-05",
    )

    set_clock("2026-08-20T00:00:00Z")
    sweep = run_compliance_sweep()
    screening = screen_publisher(
        blocked_publisher["id"],
        doaj_indexed=False,
        cope_member=False,
        editorial_board_verified=False,
        retraction_rate_per_1000=3.0,
        peer_review_days_median=5,
        apc_transparency_score=10,
    )
    return {
        "blocked_publisher": blocked_publisher,
        "cleared_publisher": cleared_publisher,
        "author": author,
        "grant": grant,
        "blocked_article": blocked_article,
        "cleared_article": cleared_article,
        "sweep": sweep,
        "screening": screening,
    }


# --------------------------------------------------------------------------- #
# state precondition (rule 8) outranks the author cap (rule 33)
# --------------------------------------------------------------------------- #
def test_approving_from_info_requested_reports_the_state_conflict_not_the_cap(api):
    """The APPROVE call violates rule 8 and rule 33 together, and the earlier rule
    wins: the response is the 409 ERR_REQUEST_NOT_REVIEWABLE, never the cap error.

    PRD §2.11: "When a single request violates more than one rule, the reported error is determined by a fixed global precedence."
    PRD §2.11: "The rules are listed here in evaluation order, lowest number first; the first rule that fails produces the response, and no later rule is evaluated."
    PRD §2.11: "**Fund request reviewable.** Starting review requires `status` `SUBMITTED`; raising an information request and taking a decision each require `status` `UNDER_REVIEW`; withdrawal requires `status` to be one of `SUBMITTED`, `INFO_REQUESTED` or `APPROVED`. Otherwise `ERR_REQUEST_NOT_REVIEWABLE` (409)."
    PRD §2.11: "**Author cap not exhausted.** The author's remaining annual allowance on the `ENCUMBRANCE_INCLUSIVE` basis is greater than zero at decision time — otherwise `ERR_AUTHOR_CAP_EXHAUSTED` (422)."
    PRD §3.5: "The request must be in `UNDER_REVIEW`; from any other state the decision is refused with `ERR_REQUEST_NOT_REVIEWABLE`."
    Design: Difficulty/priority_pair_validation_conflict/state_precondition_outranks_author_cap_on_fund_decision
    """
    scenario = _setup_zero_cap_request_in_info_requested()
    assert scenario["determination"]["eligible_request_cents"] == 300000, (
        "expected eligible_request_cents 300000, got "
        f"{scenario['determination']['eligible_request_cents']}"
    )

    response = api.decide_fund_request(
        scenario["request"]["id"], create_decision_payload("APPROVE"), FUND_MANAGER
    )
    validate_error(response, ApiErrorId.ERR_REQUEST_NOT_REVIEWABLE.value)

    request = read_fund_request(scenario["request"]["id"])
    assert request["status"] == "INFO_REQUESTED", (
        "the refused decision leaves the request where it was, got "
        f"{request['status']!r}"
    )


def test_approving_after_resubmission_reports_the_author_cap_and_writes_nothing(api):
    """Once the resubmission and a fresh start-review clear the state violation, the
    identical APPROVE call surfaces rule 33's 422 ERR_AUTHOR_CAP_EXHAUSTED and no
    allocation, ledger figure or state is touched.

    PRD §2.11: "The rules are listed here in evaluation order, lowest number first; the first rule that fails produces the response, and no later rule is evaluated."
    PRD §2.11: "**Author cap not exhausted.** The author's remaining annual allowance on the `ENCUMBRANCE_INCLUSIVE` basis is greater than zero at decision time — otherwise `ERR_AUTHOR_CAP_EXHAUSTED` (422). Applies to `POST /fund-requests/{id}/decision` when the decision is to approve."
    PRD §3.5: "The author's remaining annual allowance is computed first, as the author's `annual_cap_cents` less that author's utilisation for the fiscal year on the `ENCUMBRANCE_INCLUSIVE` basis, floored at zero."
    PRD §3.5: "If the remaining allowance is zero, the approval is refused with `ERR_AUTHOR_CAP_EXHAUSTED` and nothing is written."
    PRD §3.5: "Resubmission replaces `requested_cents` outright, records the `response_note`, increases `revision_round` by one, and returns the request to `SUBMITTED`."
    PRD §2.10: "`APCFund.committed_cents` is the sum of `amount_cents` over that fund's `ENCUMBERED` allocation lines; `APCFund.spent_cents` is the same sum over its `DISBURSED` lines; `APCFund.available_cents` is `total_budget_cents` less `committed_cents` less `spent_cents`."
    PRD §3.5: "Creating it advances the article's funding dimension from `ELIGIBILITY_CHECKED` to `FUNDING_REQUESTED`."
    Design: Difficulty/priority_pair_validation_conflict/state_precondition_outranks_author_cap_on_fund_decision
    """
    scenario = _setup_zero_cap_request_in_info_requested()
    request_id = scenario["request"]["id"]

    resubmit_request(
        request_id,
        scenario["author"]["id"],
        300000,
        response_note="Allowance confirmed as fully consumed.",
    )
    start_review(request_id)

    response = api.decide_fund_request(
        request_id, create_decision_payload("APPROVE"), FUND_MANAGER
    )
    validate_error(response, ApiErrorId.ERR_AUTHOR_CAP_EXHAUSTED.value)

    request = read_fund_request(request_id)
    assert request["status"] == "UNDER_REVIEW", (
        "the refused approval writes nothing, so the request stays UNDER_REVIEW, got "
        f"{request['status']!r}"
    )
    assert request["revision_round"] == 1, (
        f"one completed cycle gives revision_round 1, got {request['revision_round']}"
    )
    assert request["approved_cents"] == 0, (
        f"nothing was approved, got approved_cents {request['approved_cents']}"
    )

    fund = read_fund(scenario["fund"]["id"])
    assert fund["committed_cents"] == 0, (
        f"no allocation was written, got committed_cents {fund['committed_cents']}"
    )
    assert fund["available_cents"] == 1000000, (
        "the whole 1000000 budget is still available, got "
        f"{fund['available_cents']}"
    )
    assert list_request_allocations(request_id) == [], (
        "a refused approval writes no allocation lines, got "
        f"{list_request_allocations(request_id)}"
    )

    article = read_article(scenario["article"]["id"])
    assert article["funding_status"] == "FUNDING_REQUESTED", (
        "the article stays where the request creation left it, got "
        f"{article['funding_status']!r}"
    )


# --------------------------------------------------------------------------- #
# publisher blocked (rule 15) outranks grant not active (rule 18)
# --------------------------------------------------------------------------- #
def test_blocked_publisher_outranks_the_closed_grant_on_an_eligibility_check(api):
    """The article on the BLOCKED venue violates rule 15 and rule 18 at once — its
    grant was closed by the sweep — and the earlier safety rule wins with the 422
    ERR_PUBLISHER_BLOCKED, leaving no determination behind.

    PRD §2.11: "The rules are listed here in evaluation order, lowest number first; the first rule that fails produces the response, and no later rule is evaluated."
    PRD §2.11: "**Publisher not blocked.** The publisher of the article's journal has a `screening_status` other than `BLOCKED` — otherwise `ERR_PUBLISHER_BLOCKED` (422). Applies to two operations: `POST /articles/{id}/eligibility-checks` and `POST /fund-requests`."
    PRD §3.4: "Before anything is computed, the publisher of the article's journal must not be `BLOCKED`, or the check is refused with `ERR_PUBLISHER_BLOCKED`; and if the article names a grant, that grant must be `ACTIVE`, or the check is refused with `ERR_GRANT_NOT_ACTIVE`."
    PRD §3.9: "Phase two closes grants: every `ACTIVE` grant whose `award_until` is strictly before the clock date moves to `CLOSED`."
    PRD §3.9: "Its response carries `swept_at_utc` as the logical-clock instant of the run, `agreements_expired_count`, `grants_closed_count`, `articles_marked_non_compliant_count` and `articles_promoted_compliant_count`, each being the number of rows the corresponding phase actually changed."
    PRD §3.1: "Twenty-five points are added when the publisher is not indexed in DOAJ."
    PRD §3.1: "Fifteen points are added when it is not a COPE member."
    PRD §3.1: "Twenty points are added when the editorial board could not be verified."
    PRD §3.1: "The retraction signal contributes the retraction rate per thousand multiplied by five and rounded half up to a whole number, but capped so that it can never contribute more than twenty-five points."
    PRD §3.1: "Fifteen points are added when the median peer-review turnaround is strictly less than fourteen days, on the reasoning that a two-week median is implausibly fast for genuine review; a median of exactly fourteen days adds nothing."
    PRD §3.1: "Finally, a transparency credit is subtracted: one tenth of the `apc_transparency_score`, rounded half up to a whole number."
    PRD §3.1: "A score of 85 or more is `BLOCKED`."
    PRD §3.1: "Each status pins an exact `author_guidance` string that the office shows to authors."
    PRD §2.10: "`Article.determination_count` is the number of determinations written for that article and equals the highest `sequence_no` among them; `Article.latest_deposit_ordinal` is the highest `version_ordinal` among that article's deposits."
    PRD §3.3: "A newly recorded article always starts with `funding_status` `DRAFT`, while its `compliance_status` is set at creation to either `PENDING_DEPOSIT` or `EXEMPT` by the mandate rule described in §3.8, which also sets `deposit_deadline_on` and `embargo_until`."
    Design: Difficulty/priority_pair_validation_conflict/business_safety_publisher_blocked_outranks_grant_not_active
    """
    scenario = _setup_blocked_and_cleared_publishers_on_a_closed_grant()

    assert scenario["sweep"]["grants_closed_count"] == 1, (
        "the sweep closes the one grant whose award_until 2026-08-15 is before "
        f"2026-08-20, got {scenario['sweep']['grants_closed_count']}"
    )
    assert read_grant(scenario["grant"]["id"])["status"] == "CLOSED", (
        "the swept grant is CLOSED, got "
        f"{read_grant(scenario['grant']['id'])['status']!r}"
    )
    assert scenario["screening"]["predatory_score"] == 89, (
        "25 + 15 + 20 + 15 + 15 less the transparency credit of 1 is 89, got "
        f"{scenario['screening']['predatory_score']}"
    )
    assert scenario["screening"]["screening_status"] == "BLOCKED", (
        f"a score of 85 or more is BLOCKED, got {scenario['screening']['screening_status']!r}"
    )
    assert scenario["screening"]["author_guidance"] == BLOCKED_AUTHOR_GUIDANCE, (
        "the BLOCKED verdict pins its guidance string exactly, got "
        f"{scenario['screening']['author_guidance']!r}"
    )

    response = api.create_eligibility_check(
        scenario["blocked_article"]["id"],
        create_eligibility_check_payload(basis="PROVISIONAL"),
        LIBRARIAN,
    )
    validate_error(response, ApiErrorId.ERR_PUBLISHER_BLOCKED.value)

    article = read_article(scenario["blocked_article"]["id"])
    assert article["determination_count"] == 0, (
        "the refused check writes no determination, got determination_count "
        f"{article['determination_count']}"
    )
    assert article["funding_status"] == "DRAFT", (
        f"the article's funding dimension stays at DRAFT, got {article['funding_status']!r}"
    )


def test_cleared_publisher_on_the_same_closed_grant_reports_grant_not_active(api):
    """The companion article sits on an unscreened venue, so only rule 18 is in play
    and the same call reports the 409 ERR_GRANT_NOT_ACTIVE — the two rules are
    distinguished by which publisher the journal belongs to.

    PRD §2.11: "**Grant active.** When the article references a grant, that grant's `status` is `ACTIVE`; additionally, on article creation the `accepted_on` date must fall inside the closed window from `award_from` through `award_until`. Otherwise `ERR_GRANT_NOT_ACTIVE` (409). Applies to three operations: `POST /articles`, `POST /articles/{id}/eligibility-checks` and `POST /fund-requests`."
    PRD §3.4: "Before anything is computed, the publisher of the article's journal must not be `BLOCKED`, or the check is refused with `ERR_PUBLISHER_BLOCKED`; and if the article names a grant, that grant must be `ACTIVE`, or the check is refused with `ERR_GRANT_NOT_ACTIVE`."
    PRD §3.9: "Phase two closes grants: every `ACTIVE` grant whose `award_until` is strictly before the clock date moves to `CLOSED`."
    PRD §3.1: "A freshly registered publisher has not been screened: its `screening_status` is `UNSCREENED`, its `predatory_score` is absent, its `active_agreement_count` is zero, and the signal snapshot fields and `author_guidance` and `last_screened_at` are all absent."
    PRD §3.1: "Note that `UNSCREENED` is only ever the pre-screening value; a completed run always produces one of the other four."
    PRD §2.10: "`Article.determination_count` is the number of determinations written for that article and equals the highest `sequence_no` among them; `Article.latest_deposit_ordinal` is the highest `version_ordinal` among that article's deposits."
    PRD §3.3: "A newly recorded article always starts with `funding_status` `DRAFT`, while its `compliance_status` is set at creation to either `PENDING_DEPOSIT` or `EXEMPT` by the mandate rule described in §3.8, which also sets `deposit_deadline_on` and `embargo_until`."
    Design: Difficulty/priority_pair_validation_conflict/business_safety_publisher_blocked_outranks_grant_not_active
    """
    scenario = _setup_blocked_and_cleared_publishers_on_a_closed_grant()

    assert read_publisher(scenario["cleared_publisher"]["id"])["screening_status"] == (
        "UNSCREENED"
    ), (
        "the second publisher was never screened, got "
        f"{read_publisher(scenario['cleared_publisher']['id'])['screening_status']!r}"
    )

    response = api.create_eligibility_check(
        scenario["cleared_article"]["id"],
        create_eligibility_check_payload(basis="PROVISIONAL"),
        LIBRARIAN,
    )
    validate_error(response, ApiErrorId.ERR_GRANT_NOT_ACTIVE.value)

    article = read_article(scenario["cleared_article"]["id"])
    assert article["determination_count"] == 0, (
        "the refused check writes no determination, got determination_count "
        f"{article['determination_count']}"
    )
    assert article["funding_status"] == "DRAFT", (
        f"the article's funding dimension stays at DRAFT, got {article['funding_status']!r}"
    )
