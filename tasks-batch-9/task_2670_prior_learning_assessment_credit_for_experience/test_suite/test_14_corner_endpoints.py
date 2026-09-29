"""Endpoint corners: amendments, conditional actions, links and windows.

Each endpoint is exercised where its own contract is easiest to get wrong — which
arm of a ceiling binds, when an action is admissible, which candidate a link may
name, and whether a filter is applied before or after the pagination window.
"""

import pytest

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_claim_dimensions,
    assert_fields_equal,
    assert_instant,
    assert_invoice_money,
    assert_line,
    ids_of,
)
from test_helpers.test_users import (
    COORDINATOR,
    REGISTRAR,
    make_reviewer_headers,
    make_student_headers,
)
from test_helpers.types import (
    Alignment,
    AppealDecision,
    AppealStatus,
    AssessmentStatus,
    CourseLevel,
    FeeStatus,
    InvoiceLineKind,
    PaymentMethod,
    Recommendation,
    SourceType,
)

CLOCK_EPOCH = "2026-08-01T00:00:00Z"
ALL_SOURCES = [
    SourceType.CREDIT_BY_EXAM,
    SourceType.PORTFOLIO,
    SourceType.MILITARY_TRAINING,
    SourceType.INDUSTRY_CREDENTIAL,
]


def _cs150_outcomes():
    return [
        f.outcome_payload("OC1", 8000, mastery_threshold_bp=7000),
        f.outcome_payload("OC2", 2000, mastery_threshold_bp=7000),
    ]


def _bscs(client):
    return fx.new_program(
        client,
        program_code="BSCS",
        total_credits_required=120,
        residency_min_credits=30,
        pla_max_credits=30,
        pla_max_pct_bp=2500,
        pla_upper_division_max_credits=6,
        allowed_source_types=list(ALL_SOURCES),
    )


def _cs150(client, course_code="CS150", credits=6, learning_outcomes=None):
    return fx.new_course(
        client,
        course_code=course_code,
        department_code="CS",
        credits=credits,
        level=CourseLevel.LOWER,
        learning_outcomes=learning_outcomes or _cs150_outcomes(),
    )


def _student(client, program_id, student_number="S-1001", **overrides):
    return fx.new_student(
        client,
        program_id,
        student_number=student_number,
        transfer_credits_accepted=0,
        institutional_credits_earned=60,
        **overrides,
    )


def _submitted_portfolio_claim(client, student_id, course, outcomes):
    """A submitted PORTFOLIO claim: OC1 PRIMARY plus OC2 SUPPORTING, coverage 9000."""
    claim = fx.new_claim(
        client,
        student_id,
        course["id"],
        source_type=SourceType.PORTFOLIO,
        credits_requested=6,
    )
    portfolio = fx.new_portfolio(client, claim["id"], student_id)
    fx.attach_artifact(
        client, portfolio["id"], student_id, [f.mapping(outcomes[0]["id"], Alignment.PRIMARY)]
    )
    fx.attach_artifact(
        client, portfolio["id"], student_id, [f.mapping(outcomes[1]["id"], Alignment.SUPPORTING)]
    )
    fx.submit_portfolio(client, portfolio["id"], student_id)
    fx.submit_claim(client, claim["id"], student_id)
    return claim, portfolio, fx.invoice_for_claim(client, claim["id"])


def _pay(client, invoice_id, student_id, amount_cents):
    return get_success_data(
        client.pay_invoice(
            invoice_id,
            f.payment_payload(amount_cents, PaymentMethod.CARD),
            headers=make_student_headers(student_id),
        )
    )


def test_amending_the_credit_requirement_flips_which_ceiling_arm_binds(client):
    """At 120 credits the explicit ceiling ties the percentage; at 80 it does not.

    PRD: "`pla_max_credits` is an absolute credit ceiling. `pla_max_pct_bp` is a
    percentage ceiling in basis points of `total_credits_required`; the credits it
    permits are `total_credits_required` multiplied by `pla_max_pct_bp`, divided by
    10000, and then floored to a whole credit. The **programme ceiling** is the smaller
    of `pla_max_credits` and that floored percentage figure." "the amendment recomputes
    `effective_pla_cap_credits` and increments the programme's `version`."

    Design: Corner/endpoints/program_patch_recomputes_the_effective_cap_and_bumps_the_version
    """
    program = _bscs(client)
    # floor(120 * 2500 / 10000) is 30, exactly tying the explicit ceiling of 30.
    assert_fields_equal(program, effective_pla_cap_credits=30, version=1)

    amended = validate_success(
        client.patch_program(program["id"], {"total_credits_required": 80}, headers=COORDINATOR)
    )
    # floor(80 * 2500 / 10000) is 20, which now binds below pla_max_credits 30.
    assert_fields_equal(
        amended,
        total_credits_required=80,
        effective_pla_cap_credits=20,
        version=2,
        residency_min_credits=30,
        pla_max_credits=30,
        pla_max_pct_bp=2500,
        allowed_source_types=list(ALL_SOURCES),
    )

    reread = get_success_data(client.get_program(program["id"], headers=REGISTRAR))
    assert_fields_equal(reread, effective_pla_cap_credits=20, version=2)


def test_lowering_the_absolute_ceiling_hands_the_binding_arm_back(client):
    """A second amendment moves the ceiling to 12 and the version to 3.

    PRD: "Any of `pla_max_credits`, `pla_max_pct_bp`, `pla_upper_division_max_credits`,
    `residency_min_credits`, `total_credits_required`, `pla_pass_threshold_bp`,
    `allowed_source_types` and `status` may be revised, each independently optional".

    Design: Corner/endpoints/program_patch_recomputes_the_effective_cap_and_bumps_the_version
    """
    program = _bscs(client)
    validate_success(
        client.patch_program(program["id"], {"total_credits_required": 80}, headers=COORDINATOR)
    )
    tightened = validate_success(
        client.patch_program(program["id"], {"pla_max_credits": 12}, headers=COORDINATOR)
    )
    # The explicit ceiling of 12 is now below the floored percentage figure of 20.
    assert_fields_equal(
        tightened,
        pla_max_credits=12,
        pla_max_pct_bp=2500,
        total_credits_required=80,
        effective_pla_cap_credits=12,
        version=3,
    )

    untouched = validate_success(
        client.patch_program(program["id"], {}, headers=COORDINATOR)
    )
    assert_fields_equal(
        untouched, effective_pla_cap_credits=12, pla_max_credits=12, total_credits_required=80
    )


@pytest.fixture
def invoiced_claim_of_27000_cents(client):
    """A submitted PORTFOLIO claim carrying an unpaid 27000-cent invoice.

    PORTFOLIO base 15000 plus 2500 per credit over 6 credits is a subtotal of 30000
    with two artifacts, which earns the 1000 basis point discount tier.
    """
    program = _bscs(client)
    course = _cs150(client)
    outcomes = fx.outcomes_of(client, course["id"])
    student = _student(client, program["id"])
    claim, portfolio, invoice = _submitted_portfolio_claim(
        client, student["id"], course, outcomes
    )
    assert_invoice_money(invoice, total_cents=27000, balance_due_cents=27000)
    return {
        "program": program,
        "course": course,
        "outcomes": outcomes,
        "student": student,
        "claim": claim,
        "portfolio": portfolio,
        "invoice": invoice,
    }


def test_waiving_a_fully_settled_invoice_is_refused(client, invoiced_claim_of_27000_cents):
    """The waive action needs a balance to work on, and there is none left.

    PRD: "Waiving is a coordinator act carrying a `waive_reason`, available from
    `INVOICED` or `PARTIALLY_PAID`." "An invoice whose `fee_status` is `UNBILLED`,
    `WAIVED`, `REFUNDED` or `RETAINED` accepts no money movement, and an invoice
    already at `PAID` with `balance_due_cents` of 0 accepts no further payment.
    Failure: `ERR_INVOICE_NOT_PAYABLE` (409). Applies to paying an invoice and waiving
    an invoice."

    Design: Corner/endpoints/waive_on_a_fully_paid_invoice_returns_invoice_not_payable
    """
    scenario = invoiced_claim_of_27000_cents
    invoice_id = scenario["invoice"]["id"]
    settled = _pay(client, invoice_id, scenario["student"]["id"], 27000)
    assert_invoice_money(settled, paid_cents=27000, balance_due_cents=0, waived_cents=0)
    paid_claim = get_success_data(
        client.get_claim(scenario["claim"]["id"], headers=COORDINATOR)
    )
    assert_claim_dimensions(paid_claim, fee_status=FeeStatus.PAID)

    # The design's own literal is 422; the PRD fixes this rung's status at 409.
    refused = client.waive_invoice(
        invoice_id, {"waive_reason": "Late hardship petition"}, headers=COORDINATOR
    )
    validate_error(refused, ApiErrorId.ERR_INVOICE_NOT_PAYABLE, 409)

    unchanged = get_success_data(client.get_invoice(invoice_id, headers=COORDINATOR))
    assert_invoice_money(
        unchanged, paid_cents=27000, waived_cents=0, refunded_cents=0, balance_due_cents=0
    )
    still_paid = get_success_data(
        client.get_claim(scenario["claim"]["id"], headers=COORDINATOR)
    )
    assert_claim_dimensions(still_paid, fee_status=FeeStatus.PAID)


def test_waiving_a_partly_paid_invoice_absorbs_only_the_remaining_balance(
    client, invoiced_claim_of_27000_cents
):
    """20000 cents paid leaves 7000 to waive, not the whole 27000.

    PRD: "It sets `waived_cents` to `total_cents` minus net cash paid, drives
    `balance_due_cents` to 0" and "moves `fee_status` to `WAIVED`."

    Design: Corner/endpoints/waive_on_a_fully_paid_invoice_returns_invoice_not_payable
    """
    scenario = invoiced_claim_of_27000_cents
    invoice_id = scenario["invoice"]["id"]
    part_paid = _pay(client, invoice_id, scenario["student"]["id"], 20000)
    assert_invoice_money(part_paid, paid_cents=20000, balance_due_cents=7000)
    assert_claim_dimensions(
        get_success_data(client.get_claim(scenario["claim"]["id"], headers=COORDINATOR)),
        fee_status=FeeStatus.PARTIALLY_PAID,
    )

    waived = validate_success(
        client.waive_invoice(
            invoice_id, {"waive_reason": "Late hardship petition"}, headers=COORDINATOR
        )
    )
    assert_invoice_money(
        waived, total_cents=27000, waived_cents=7000, paid_cents=20000, balance_due_cents=0
    )

    claim = get_success_data(client.get_claim(scenario["claim"]["id"], headers=COORDINATOR))
    assert_claim_dimensions(claim, fee_status=FeeStatus.WAIVED)


@pytest.fixture
def filed_appeal_with_three_assessors(client):
    """A filed appeal on a denied claim, with the appeal filing fee still outstanding.

    Three ACTIVE rank-2 CS assessors stand behind it: E-9001 scored the claim and is
    not on the appeal panel, E-9002 is idle and not on the panel, and E-9003 is idle
    and is the only panel member. The invoice was settled at 27000 before the appeal,
    so the 6000-cent filing fee leaves it short.
    """
    program = _bscs(client)
    course = _cs150(client)
    outcomes = fx.outcomes_of(client, course["id"])
    student = _student(client, program["id"])

    def assessor(employee_number, appeal_panel_member):
        return fx.new_assessor(
            client,
            employee_number=employee_number,
            department_code="CS",
            credential_rank=2,
            max_concurrent_assignments=3,
            appeal_panel_member=appeal_panel_member,
        )

    scorer = assessor("E-9001", False)
    bystander = assessor("E-9002", False)
    panel_member = assessor("E-9003", True)

    claim, _portfolio, invoice = _submitted_portfolio_claim(
        client, student["id"], course, outcomes
    )
    _pay(client, invoice["id"], student["id"], 27000)
    assignment = fx.assign_assessor(client, claim["id"], scorer["id"])
    fx.accept_assignment(client, assignment["id"], scorer["id"])
    fx.score_all_outcomes(client, assignment["id"], scorer["id"], outcomes, [2, 2])
    fx.complete_assignment(client, assignment["id"], scorer["id"], Recommendation.FAIL)
    get_success_data(
        client.deny_claim(
            claim["id"],
            {"denial_reason": "Verified coverage below the pass threshold"},
            headers=COORDINATOR,
        )
    )
    appeal = validate_success(
        client.create_appeal(
            {"claim_id": claim["id"], "grounds": "The assessor overlooked the second artifact"},
            headers=make_student_headers(student["id"]),
        ),
        201,
    )
    return {
        "student": student,
        "scorer": scorer,
        "bystander": bystander,
        "panel_member": panel_member,
        "claim": claim,
        "invoice": invoice,
        "appeal": appeal,
    }


def test_filing_snapshots_the_scorers_and_appends_the_filing_fee(
    client, filed_appeal_with_three_assessors
):
    """The appeal arrives with its reviewer fields empty and its scorer list frozen.

    PRD: "Filing creates an `Appeal` in `status` `FILED` with `filed_at` stamped from
    the logical clock, and it snapshots `prior_scorer_assessor_ids` — the identifiers
    of every assessor who scored this claim." "an appeal filing fee line is appended to
    the claim's invoice and the whole invoice is repriced: the subtotal rises, the
    discount tier is re-selected from the **new** pre-discount subtotal, `discount_bp`,
    `discount_cents` and `total_cents` are recomputed, and `recompute_count` increments
    by one."

    Design: Corner/endpoints/appeal_reviewer_assignment_links_a_panel_member_excluding_prior_scorers
    """
    scenario = filed_appeal_with_three_assessors
    appeal = scenario["appeal"]
    assert_fields_equal(
        appeal, status=AppealStatus.FILED, reviewer_assessor_id=None, assigned_at=None
    )
    assert_instant(appeal["filed_at"], CLOCK_EPOCH, "filed_at")

    stored = get_success_data(client.get_appeal(appeal["id"], headers=COORDINATOR))
    assert stored["prior_scorer_assessor_ids"] == [scenario["scorer"]["id"]], (
        "only the assessor who recorded rubric scores is in the snapshot"
    )

    # 30000 plus the 6000 filing fee is a 36000 subtotal, still in the 1000bp tier.
    invoice = get_success_data(client.get_invoice(scenario["invoice"]["id"], headers=COORDINATOR))
    assert_line(invoice, InvoiceLineKind.APPEAL_FILING_FEE, 6000)
    assert_invoice_money(
        invoice,
        subtotal_cents=36000,
        discount_bp=1000,
        discount_cents=3600,
        total_cents=32400,
        paid_cents=27000,
        balance_due_cents=5400,
        recompute_count=1,
    )

    claim = get_success_data(client.get_claim(scenario["claim"]["id"], headers=COORDINATOR))
    assert_claim_dimensions(
        claim,
        assessment_status=AssessmentStatus.APPEAL_PENDING,
        fee_status=FeeStatus.PARTIALLY_PAID,
    )
    assert_fields_equal(claim, appeal_count=1)


def test_auto_selection_reaches_past_two_closer_candidates_to_the_panel_member(
    client, filed_appeal_with_three_assessors
):
    """E-9003 is chosen although E-9002 matches on load and rank.

    PRD: "The eligibility filter is the assessor filter of §3.6 with two additions: the
    candidate's `appeal_panel_member` must be true, and the candidate must not appear
    in the appeal's `prior_scorer_assessor_ids`." "On success `reviewer_assessor_id` is
    set, `assigned_at` is stamped from the logical clock, and the appeal's `version`
    increments."

    Design: Corner/endpoints/appeal_reviewer_assignment_links_a_panel_member_excluding_prior_scorers
    """
    scenario = filed_appeal_with_three_assessors
    appeal_id = scenario["appeal"]["id"]
    topped_up = _pay(client, scenario["invoice"]["id"], scenario["student"]["id"], 5400)
    assert_invoice_money(topped_up, paid_cents=32400, balance_due_cents=0)

    assigned = validate_success(
        client.assign_appeal_reviewer(appeal_id, {}, headers=COORDINATOR)
    )
    assert_fields_equal(
        assigned,
        reviewer_assessor_id=scenario["panel_member"]["id"],
        status=AppealStatus.UNDER_REVIEW,
    )
    assert assigned["reviewer_assessor_id"] != scenario["bystander"]["id"], (
        "an equally idle non-panel assessor is not eligible to review"
    )
    assert assigned["reviewer_assessor_id"] != scenario["scorer"]["id"], (
        "the prior scorer is barred from reviewing their own denial"
    )
    assert_instant(assigned["assigned_at"], CLOCK_EPOCH, "assigned_at")

    rows, meta = validate_paginated(
        client.list_appeals(
            {"reviewer_assessor_id": scenario["panel_member"]["id"]}, headers=COORDINATOR
        )
    )
    assert ids_of(rows) == [appeal_id]
    assert meta["total_count"] == 1

    claim = get_success_data(client.get_claim(scenario["claim"]["id"], headers=COORDINATOR))
    assert_claim_dimensions(claim, assessment_status=AssessmentStatus.APPEAL_PENDING)

    again = client.assign_appeal_reviewer(appeal_id, {}, headers=COORDINATOR)
    validate_error(again, ApiErrorId.ERR_APPEAL_NOT_FILED, 409)


def test_the_reviewer_desk_refuses_a_bystander_a_prior_scorer_and_an_unpaid_fee(
    client, filed_appeal_with_three_assessors
):
    """Three refusals in ladder order, each above the fiscal gate at the bottom.

    PRD: "Naming a reviewer who scored the claim is `ERR_SEGREGATION_OF_DUTIES`; naming
    one who is not an appeal-panel member is `ERR_ASSESSOR_NOT_ELIGIBLE`". "The appealed
    claim's invoice must be fully settled — `balance_due_cents` of 0 — before review may
    begin; an outstanding filing fee is `ERR_APPEAL_FEE_UNPAID` with HTTP 402."
    "`UNDER_REVIEW` permits a decision. Failures: `ERR_APPEAL_NOT_FILED` and
    `ERR_APPEAL_NOT_UNDER_REVIEW`, both 409."

    Design: Corner/endpoints/appeal_reviewer_assignment_links_a_panel_member_excluding_prior_scorers
    """
    scenario = filed_appeal_with_three_assessors
    appeal_id = scenario["appeal"]["id"]

    too_early = client.decide_appeal(
        appeal_id,
        {"decision": AppealDecision.UPHELD},
        headers=make_reviewer_headers(scenario["panel_member"]["id"]),
    )
    validate_error(too_early, ApiErrorId.ERR_APPEAL_NOT_UNDER_REVIEW, 409)

    # The design's own literal here is ERR_NOT_APPEAL_PANEL_MEMBER; the PRD reserves
    # that code for the decider and answers a named non-panel reviewer with rung 32.
    bystander = client.assign_appeal_reviewer(
        appeal_id, {"reviewer_assessor_id": scenario["bystander"]["id"]}, headers=COORDINATOR
    )
    validate_error(bystander, ApiErrorId.ERR_ASSESSOR_NOT_ELIGIBLE, 422)

    prior_scorer = client.assign_appeal_reviewer(
        appeal_id, {"reviewer_assessor_id": scenario["scorer"]["id"]}, headers=COORDINATOR
    )
    validate_error(prior_scorer, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 409)

    unpaid = client.assign_appeal_reviewer(appeal_id, {}, headers=COORDINATOR)
    validate_error(unpaid, ApiErrorId.ERR_APPEAL_FEE_UNPAID, 402)

    untouched = get_success_data(client.get_appeal(appeal_id, headers=COORDINATOR))
    assert_fields_equal(
        untouched, status=AppealStatus.FILED, reviewer_assessor_id=None, assigned_at=None
    )


@pytest.fixture
def three_claims_one_of_them_withdrawn(client):
    """Three claims for one student across three courses, the first withdrawn.

    All three share a `created_at`, because the logical clock never moves, so the
    listing order is decided entirely by the `claim_number` tie-break.
    """
    program = _bscs(client)
    single_outcome = [f.outcome_payload("OC1", 10000, mastery_threshold_bp=7000)]
    courses = [
        _cs150(client, course_code=code, learning_outcomes=single_outcome)
        for code in ("CS150", "CS160", "CS170")
    ]
    student = _student(client, program["id"])
    claims = [
        fx.new_claim(
            client,
            student["id"],
            course["id"],
            source_type=SourceType.PORTFOLIO,
            credits_requested=6,
        )
        for course in courses
    ]
    withdrawn = validate_success(
        client.withdraw_claim(
            claims[0]["id"],
            {"withdraw_reason": "Course already transferred in"},
            headers=make_student_headers(student["id"]),
        )
    )
    assert_claim_dimensions(withdrawn, assessment_status=AssessmentStatus.WITHDRAWN)
    return {"student": student, "courses": courses, "claims": claims}


def test_a_status_filter_narrows_the_set_before_the_pagination_window(
    client, three_claims_one_of_them_withdrawn
):
    """Page one of the filtered query is not page one of the unfiltered query.

    PRD: "listed with optional `student_id`, `course_id`, `articulation_rule_id`,
    `supersedes_claim_id`, `assessment_status`, `fee_status` and `credit_status`
    filters, sorted by `created_at` ascending then `claim_number` ascending". "Every
    list response carries `limit`, `offset`, `total_count` and `has_more` inside the
    envelope's `meta` object. `total_count` counts the records matching the filter
    before pagination is applied; `has_more` is true when records remain beyond the
    current window."

    Design: Corner/endpoints/pla_claim_listing_filter_and_offset_pagination_interact
    """
    scenario = three_claims_one_of_them_withdrawn
    student_id = scenario["student"]["id"]
    first, second, third = [claim["id"] for claim in scenario["claims"]]
    assert [claim["claim_number"] for claim in scenario["claims"]] == [1, 2, 3]

    page_one, meta_one = validate_paginated(
        client.list_claims(
            {"student_id": student_id, "limit": 2, "offset": 0}, headers=COORDINATOR
        )
    )
    assert ids_of(page_one) == [first, second]
    assert meta_one["total_count"] == 3
    assert meta_one["has_more"] is True

    page_two, meta_two = validate_paginated(
        client.list_claims(
            {"student_id": student_id, "limit": 2, "offset": 2}, headers=COORDINATOR
        )
    )
    assert ids_of(page_two) == [third]
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False

    # The withdrawn first claim is removed before the window, not after it.
    drafts, draft_meta = validate_paginated(
        client.list_claims(
            {
                "student_id": student_id,
                "assessment_status": AssessmentStatus.DRAFT,
                "limit": 2,
                "offset": 0,
            },
            headers=COORDINATOR,
        )
    )
    assert ids_of(drafts) == [second, third]
    assert draft_meta["total_count"] == 2
    assert draft_meta["has_more"] is False

    gone, gone_meta = validate_paginated(
        client.list_claims(
            {"student_id": student_id, "assessment_status": AssessmentStatus.WITHDRAWN},
            headers=COORDINATOR,
        )
    )
    assert ids_of(gone) == [first]
    assert gone_meta["total_count"] == 1

    by_course, _course_meta = validate_paginated(
        client.list_claims({"course_id": scenario["courses"][1]["id"]}, headers=COORDINATOR)
    )
    assert ids_of(by_course) == [second]
