"""Lifecycle transitions of the study, the credit claim and the notice window:
the states they are born in, the stamps they write, and the replays they refuse."""

from test_helpers import ANALYST_1, ANALYST_2, api_errors as err
from test_helpers import assertions as check
from test_helpers import constants as K
from test_helpers import factories, fixtures, get_success_data, make_analyst_headers
from test_helpers import validate_error, validate_success
from test_helpers.fixtures import ADMIN, ANALYST, CLERK

SECOND_ANALYST = make_analyst_headers(ANALYST_2)
INSIDE_PROTEST_WINDOW = "2026-01-20T00:00:00Z"
DAY_AFTER_CERTIFICATION = "2026-01-06T00:00:00Z"

STUDY_LIFECYCLE_FIELDS = (
    "certified_by_user_id",
    "certified_at",
    "notice_method",
    "notice_days",
    "notice_published_at",
    "protest_window_ends_at",
    "adopted_by_user_id",
    "adopted_at",
    "effective_at",
    "activated_at",
    "superseded_by_fee_study_id",
)


def test_a_new_study_is_born_in_draft_with_both_tallies_at_zero(api):
    """A new study is born in status `DRAFT` with `revision_round` 0, a protest
    tally of zero on both counters, and every notice, adoption and activation
    timestamp null; the create additionally increments the parent program's
    `version`, because the program's roster of studies has changed.

    Design: Corner/state_machines/new_fee_study_starts_in_draft_with_empty_protest_tallies
    """
    fixtures.set_clock(api, K.CLOCK_PROGRAM_SETUP)
    program = fixtures.create_program(api)

    study = validate_success(
        api.create_fee_study(
            factories.fee_study_payload(program["id"], program["version"]), ANALYST
        ),
        201,
    )

    assert study["status"] == K.STUDY_DRAFT
    assert study["revision_round"] == 0
    assert study["protest_weight_bp"] == 0, "the tally is zero, not null"
    assert study["protest_count"] == 0, "the tally is zero, not null"
    check.assert_fields_null(study, *STUDY_LIFECYCLE_FIELDS)
    check.assert_common_fields(study, expected_version=1)
    check.assert_created_unmutated(study)
    assert fixtures.program_version(api, program["id"]) == program["version"] + 1


def test_adoption_is_refused_while_the_protest_window_is_still_open(api):
    """Closing the protest window is a single clerk action with two divergent
    outcomes, and both require the same two preconditions: the study is
    `NOTICE_PUBLISHED` (`ERR_STUDY_INVALID_STATE`) and the logical clock has
    reached `protest_window_ends_at`, inclusively — closing exactly at that
    instant is allowed, and closing before it returns `ERR_PROTEST_WINDOW_OPEN`.
    Adoption by a `CouncilClerk` moves the study `PROTEST_CLEARED → ADOPTED` and
    requires the study to be in `PROTEST_CLEARED` (`ERR_STUDY_INVALID_STATE`) and
    the caller's `X-User-ID` to differ from `certified_by_user_id` per §2.9
    (`ERR_SEGREGATION_OF_DUTIES`).

    Design: Corner/state_machines/adopt_before_the_protest_window_closes_returns_study_invalid_state
    """
    chain = fixtures.noticed_program(api, with_roads=False)
    noticed = get_success_data(api.get_fee_study(chain.study_id, ADMIN))
    fixtures.set_clock(api, INSIDE_PROTEST_WINDOW)

    response = api.adopt_fee_study(chain.study_id, CLERK)

    validate_error(response, err.ERR_STUDY_INVALID_STATE, 409)
    study = get_success_data(api.get_fee_study(chain.study_id, ADMIN))
    assert study["status"] == K.STUDY_NOTICE_PUBLISHED
    check.assert_fields_null(study, "adopted_at", "adopted_by_user_id", "effective_at")
    check.assert_timestamp_equals(
        study["notice_published_at"], K.CLOCK_NOTICE_PUBLISHED, "notice_published_at"
    )
    check.assert_timestamp_equals(
        study["protest_window_ends_at"], K.CLOCK_PROTEST_WINDOW_END, "protest_window_ends_at"
    )
    assert study["revision_round"] == 0
    check.assert_version_advanced_by(noticed["version"], study["version"], 0)


def test_a_denied_credit_claim_cannot_be_decided_a_second_time(api):
    """Every decision requires the claim to still be `SUBMITTED`
    (`ERR_CLAIM_INVALID_STATE`), the application's `assessment_status` to be
    `ASSESSED` or `REASSESSED`, and the application's `co_issued_at` to still be
    null (either of the latter two returning `ERR_APPLICATION_INVALID_STATE`).
    Denial is the only decision that leaves the application row completely
    untouched: no re-assessment fires, no money field changes, and the
    application's `version` does not move. All three status values
    `APPROVED_FULL`, `APPROVED_PARTIAL` and `DENIED` are terminal for the claim.

    Design: Corner/state_machines/denied_credit_claim_cannot_be_decided_twice
    """
    chain = fixtures.effective_program(api)
    assessed = fixtures.assessed_application(api, chain)
    claim = fixtures.file_credit_claim(
        api,
        chain.application_id,
        facility_category_code=K.PARKS_CODE,
        credit_type=K.CREDIT_TYPE_DEVELOPER_IMPROVEMENT,
        valuation_method=K.VALUATION_NOMINAL,
        improvement_value_cents=1000000,
        annual_tax_contribution_cents=0,
        contribution_years=0,
    )
    denied = fixtures.decide_credit_claim(
        api, claim["id"], chain.application_id, K.DECISION_DENY
    )
    assert denied["status"] == K.CLAIM_DENIED

    response = api.decide_credit_claim(
        claim["id"],
        factories.credit_decision_payload(
            fixtures.application_version(api, chain.application_id),
            decision=K.DECISION_APPROVE_FULL,
        ),
        ANALYST,
    )

    validate_error(response, err.ERR_CLAIM_INVALID_STATE, 409)
    claims = get_success_data(api.list_credit_claims(chain.application_id, ADMIN))
    assert [row["status"] for row in claims] == [K.CLAIM_DENIED]
    check.assert_money_equals(claims[0]["approved_cents"], 0, "approved_cents")
    application = get_success_data(api.get_development_application(chain.application_id, ADMIN))
    assert application["assessment_status"] == assessed["assessment_status"]
    check.assert_application_totals(
        application,
        gross_assessed_cents=K.BASELINE_GROSS_ASSESSED,
        credit_applied_cents=0,
        admin_charge_cents=K.BASELINE_ADMIN_CHARGE,
        net_due_cents=K.BASELINE_NET_DUE,
    )


def test_certifying_an_already_certified_study_changes_nothing(api):
    """Certification is the analyst's formal record that the rational nexus and
    rough-proportionality tests are met for every category the study prices, and
    it moves the study `DRAFT → NEXUS_CERTIFIED`. It is refused unless the study
    is in `DRAFT` (`ERR_STUDY_INVALID_STATE`), unless the study has at least one
    component (`ERR_STUDY_HAS_NO_COMPONENTS`), unless every component of the study
    has `allocation_status` `VALID` and carries at least one schedule line
    (`ERR_COMPONENT_ALLOCATION_STALE` in either case), and unless every
    component's `nexus_ratio` is at least 1.0 (`ERR_NEXUS_RATIO_INSUFFICIENT`,
    HTTP 409) — a component whose planned capacity falls short of its projected
    growth demand would be charging new development for capacity the programme
    never buys. Certification writes `certified_by_user_id` from the caller's
    `X-User-ID` and `certified_at` from the logical clock, and increments the
    study's `version`.

    Design: Corner/state_machines/certify_nexus_twice_returns_study_invalid_state
    """
    chain = fixtures.certified_program(api, with_roads=False)
    certified = get_success_data(api.get_fee_study(chain.study_id, ADMIN))
    check.assert_timestamp_equals(
        certified["certified_at"], K.CLOCK_PROGRAM_SETUP, "certified_at"
    )
    fixtures.set_clock(api, DAY_AFTER_CERTIFICATION)

    response = api.certify_nexus(chain.study_id, SECOND_ANALYST)

    validate_error(response, err.ERR_STUDY_INVALID_STATE, 409)
    study = get_success_data(api.get_fee_study(chain.study_id, ADMIN))
    assert study["status"] == K.STUDY_NEXUS_CERTIFIED
    check.assert_timestamp_equals(study["certified_at"], K.CLOCK_PROGRAM_SETUP, "certified_at")
    assert study["certified_by_user_id"] == ANALYST_1, "the second caller is not recorded"
    assert study["revision_round"] == 0
    check.assert_version_advanced_by(certified["version"], study["version"], 0)


def test_closing_one_second_early_is_refused_and_closing_on_time_clears(api):
    """Closing the protest window is a single clerk action with two divergent
    outcomes, and both require the same two preconditions: the study is
    `NOTICE_PUBLISHED` (`ERR_STUDY_INVALID_STATE`) and the logical clock has
    reached `protest_window_ends_at`, inclusively — closing exactly at that
    instant is allowed, and closing before it returns `ERR_PROTEST_WINDOW_OPEN`.
    When `protest_weight_bp` is strictly below `protest_threshold_bp`, the protest
    fails and the study moves `NOTICE_PUBLISHED → PROTEST_CLEARED`.

    Design: Corner/state_machines/close_protest_window_before_window_end_returns_protest_window_open
    """
    chain = fixtures.noticed_program(api, with_roads=False)
    fixtures.set_clock(api, K.CLOCK_JUST_BEFORE_WINDOW_END)

    response = api.close_protest_window(chain.study_id, CLERK)

    validate_error(response, err.ERR_PROTEST_WINDOW_OPEN, 409)
    still_open = get_success_data(api.get_fee_study(chain.study_id, ADMIN))
    assert still_open["status"] == K.STUDY_NOTICE_PUBLISHED
    check.assert_timestamp_equals(
        still_open["protest_window_ends_at"],
        K.CLOCK_PROTEST_WINDOW_END,
        "protest_window_ends_at",
    )

    fixtures.set_clock(api, K.CLOCK_PROTEST_WINDOW_END)
    cleared = fixtures.close_protest_window(api, chain.study_id)

    assert cleared["status"] == K.STUDY_PROTEST_CLEARED
    assert cleared["protest_weight_bp"] == 0
    assert cleared["protest_count"] == 0
    assert cleared["revision_round"] == 0
    check.assert_version_advanced_by(still_open["version"], cleared["version"], 1)


def test_publication_stamps_the_notice_fields_and_the_window_end(api):
    """Notice publication by a `CouncilClerk` moves the study
    `NEXUS_CERTIFIED → NOTICE_PUBLISHED`, and requires the study to be in
    `NEXUS_CERTIFIED` (`ERR_STUDY_INVALID_STATE`). Publication stores the notice
    method and days, stamps `notice_published_at` from the logical clock, sets
    `protest_window_ends_at` to that instant plus `notice_days` days, and
    increments the study's `version`.

    Design: Corner/state_machines/publish_notice_stamps_the_notice_fields_and_window_end
    """
    chain = fixtures.certified_program(api, with_roads=False)
    certified = get_success_data(api.get_fee_study(chain.study_id, ADMIN))
    fixtures.set_clock(api, K.CLOCK_NOTICE_PUBLISHED)

    published = fixtures.publish_notice(
        api, chain.study_id, notice_days=30, notice_method=K.NOTICE_MAILED
    )

    assert published["status"] == K.STUDY_NOTICE_PUBLISHED
    assert published["notice_method"] == K.NOTICE_MAILED
    assert published["notice_days"] == 30
    check.assert_timestamp_equals(
        published["notice_published_at"], K.CLOCK_NOTICE_PUBLISHED, "notice_published_at"
    )
    check.assert_timestamp_equals(
        published["protest_window_ends_at"],
        K.CLOCK_PROTEST_WINDOW_END,
        "protest_window_ends_at",
    )
    assert published["protest_weight_bp"] == 0
    assert published["protest_count"] == 0
    check.assert_timestamp_equals(
        published["certified_at"], K.CLOCK_PROGRAM_SETUP, "certified_at"
    )
    check.assert_version_advanced_by(certified["version"], published["version"], 1)


def test_a_partial_approval_applies_only_the_amount_the_analyst_allowed(api):
    """`APPROVE_PARTIAL` moves the claim `SUBMITTED → APPROVED_PARTIAL` and sets
    `approved_cents` to the value supplied in the body. The system re-assesses the
    application on its own initiative — `assessment_status` becomes `REASSESSED`
    and `assessed_lines`, `credit_applied_cents`, `admin_charge_cents` and
    `net_due_cents` are all recomputed under the credit cap by the seven-step
    procedure of §3.6 — and the application's `version` increments. For each line,
    subtract `line_credit_cents` from `line_gross_cents` to get that line's net
    before administration. `line_net_cents` is the line's net before
    administration plus its `line_admin_cents`. `admin_charge_cents` on the
    application is the sum of the per-line `line_admin_cents` values.

    Design: Corner/state_machines/credit_claim_approve_partial_applies_only_the_approved_amount
    """
    chain = fixtures.effective_program(api)
    fixtures.assessed_application(api, chain)
    claim = fixtures.file_credit_claim(
        api,
        chain.application_id,
        facility_category_code=K.PARKS_CODE,
        credit_type=K.CREDIT_TYPE_DEVELOPER_IMPROVEMENT,
        valuation_method=K.VALUATION_NOMINAL,
        improvement_value_cents=1000000,
        annual_tax_contribution_cents=0,
        contribution_years=0,
    )
    check.assert_money_equals(claim["claimed_credit_cents"], 1000000, "claimed_credit_cents")

    decided = fixtures.decide_credit_claim(
        api,
        claim["id"],
        chain.application_id,
        K.DECISION_APPROVE_PARTIAL,
        approved_cents=500000,
        headers=SECOND_ANALYST,
    )

    assert decided["status"] == K.CLAIM_APPROVED_PARTIAL
    check.assert_money_equals(decided["approved_cents"], 500000, "approved_cents")
    application = get_success_data(api.get_development_application(chain.application_id, ADMIN))
    assert application["assessment_status"] == K.ASSESSMENT_REASSESSED
    assert application["collection_status"] == K.COLLECTION_DUE
    check.assert_application_totals(
        application,
        gross_assessed_cents=K.BASELINE_GROSS_ASSESSED,
        credit_applied_cents=500000,
        admin_charge_cents=136151,
        net_due_cents=4674521,
    )
    check.assert_net_due_identity(application)
    parks_line = check.line_for_code(application["assessed_lines"], K.PARKS_CODE)
    roads_line = check.line_for_code(application["assessed_lines"], K.ROADS_CODE)
    check.assert_assessed_line(
        parks_line,
        line_gross_cents=K.BASELINE_PARKS_LINE_GROSS,
        line_credit_cents=500000,
        line_admin_cents=61250,
        line_net_cents=2102930,
    )
    check.assert_assessed_line(
        roads_line,
        line_gross_cents=K.BASELINE_ROADS_LINE_GROSS,
        line_credit_cents=0,
        line_admin_cents=K.BASELINE_ROADS_LINE_ADMIN,
        line_net_cents=K.BASELINE_ROADS_LINE_NET,
    )
