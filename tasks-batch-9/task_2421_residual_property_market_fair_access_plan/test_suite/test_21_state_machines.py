"""State machines: initial states, legal edges, terminal lockdown and preconditions.

Each test drives one lifecycle — application, rate filing, producer agreement,
inspection, improvement requirement, assessment event, assessment allocation or
policy coverage — to a single edge or to a single refused edge, and reads back
both the record itself and the records its cascade should or should not have
touched.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_ALLOCATION_NOT_PAYABLE,
    ERR_APPLICATION_NOT_REVIEWABLE,
    ERR_APPLICATION_NOT_SUBMITTABLE,
    ERR_ASSESSMENT_STATE_INVALID,
    ERR_FILING_NOT_REVIEWABLE,
    ERR_INSPECTION_ALREADY_COMPLETED,
    ERR_PRODUCER_STATUS_INVALID,
    ERR_REQUIREMENT_STATE_INVALID,
)
from test_helpers.assertions import (
    assert_cents,
    assert_count,
    assert_date_equals,
    assert_field_equals,
    assert_field_null,
    assert_fields_null,
    assert_instant_equals,
    assert_ratio,
)
from test_helpers.constants import (
    AGREEMENT_STATUS_APPOINTED,
    AGREEMENT_STATUS_SUSPENDED,
    ALLOCATION_STATUS_PENDING,
    APP_STATUS_APPROVED_TO_BIND,
    APP_STATUS_DRAFT,
    APP_STATUS_IMPROVEMENTS_REQUIRED,
    APP_STATUS_SUBMITTED,
    CANCEL_REASON_PLAN_INITIATED,
    CLOCK_BASE,
    CLOCK_ORIGIN,
    COMMISSION_BPS_STANDARD,
    COVERAGE_STATUS_BOUND,
    COVERAGE_STATUS_CANCELLED,
    DECISION_DISAPPROVE,
    EVENT_STATUS_ALLOCATED,
    EVENT_STATUS_DRAFT,
    FILING_STATUS_DISAPPROVED,
    INSPECTION_RESULT_FAIL,
    INSPECTION_RESULT_PASS,
    INSPECTION_RESULT_PASS_WITH_CONDITIONS,
    PACKAGE_BASIC_FIRE_EO,
    PRODUCER_ACTION_REINSTATE,
    PRODUCER_ACTION_SUSPEND,
    REQUIREMENT_CODE_ELECTRICAL,
    REQUIREMENT_CODE_ROOF,
    REQUIREMENT_STATUS_OPEN,
    SEVERITY_MAJOR,
    SEVERITY_MINOR,
    ZONE_STATUS_OPEN,
)
from test_helpers.fixtures import (
    Foundations,
    build_bindable_application,
    build_inspection_pending_application,
    build_submitted_application,
    bind,
    complete_inspection,
    create_applicant,
    create_appointed_producer,
    create_draft_application,
    create_event,
    create_member_insurer,
    create_property,
    create_zone,
    file_rate,
    pin_clock,
    read_application,
    read_event,
    read_inspection,
    read_filing,
    read_producer,
    read_requirements,
    read_zone,
    run_sweep,
)
from test_helpers.test_users import (
    admin_headers,
    inspector_headers,
    make_member_insurer_headers,
    regulator_headers,
    reviewer_headers,
    second_inspector_headers,
    second_regulator_headers,
)


def _registry_only_foundations(client, clock=CLOCK_ORIGIN):
    """A territory and an appointed producer — no rate filing, no carriers."""
    pin_clock(client, clock)
    zone = create_zone(client, exposure_cap_cents=900_000_000)
    producer = create_appointed_producer(client)
    return Foundations(client=client, zone=zone, producer=producer)


def test_application_starts_in_draft_with_zero_declination_count(client):
    """A freshly opened application is DRAFT with no count, no quote and no deadline.

    PRD: "A fresh application sits in `status` `DRAFT` with `declination_count` at 0;
    `quoted_annual_premium_cents` and `voluntary_equivalent_premium_cents` at 0;
    `voluntary_market_comparison_pct` at 0.0; and `quote_rate_filing_id`,
    `submitted_at`, `eligibility_hold_reason`, `decline_reason`,
    `eligibility_reviewer_user_id`, `approved_to_bind_at` and `bind_deadline_at`
    all null."

    PRD: "The application's `producer_id` is never accepted in the request body — it
    is taken from the submitting producer's `X-User-ID`."

    Design: Corner/state_machines/application_starts_in_draft_with_zero_declination_count
    """
    foundations = _registry_only_foundations(client)
    applicant = create_applicant(client, foundations)
    prop = create_property(client, foundations)

    response = client.create_application(
        f.application_payload(
            property_id=prop["id"],
            applicant_id=applicant["id"],
            requested_dwelling_limit_cents=54_000_000,
            requested_peril_package=PACKAGE_BASIC_FIRE_EO,
        ),
        foundations.producer_headers,
    )

    application = validate_success(response, 201)
    assert_field_equals(application, "status", APP_STATUS_DRAFT)
    assert_field_equals(application, "producer_id", foundations.producer_id)
    assert_field_equals(application, "declination_count", 0)
    assert_cents(
        application["quoted_annual_premium_cents"], 0, "quoted_annual_premium_cents"
    )
    assert_fields_null(
        application, ("submitted_at", "quote_rate_filing_id", "bind_deadline_at")
    )


def test_rate_filing_disapproval_records_reviewer_and_note(client):
    """Disapproval writes the reviewer and note but leaves the filed differential.

    PRD: "A `Regulator` reviews a filing by supplying a `decision` of either
    `APPROVE` or `DISAPPROVE` together with an optional `note`, which is stored
    as `review_note`; the reviewer's `X-User-ID` is stored as
    `reviewed_by_user_id`."

    PRD: "`FILED → DISAPPROVED` also writes the reviewer fields and increments the
    filing's `version` by one, but supersedes nothing and — this is the asymmetry
    to watch — does **not** increment the territory's `version`."

    PRD: "At filing time the server computes `differential_pct`: the filed rate minus
    the surveyed voluntary average, divided by that same surveyed voluntary
    average, rounded half up to four decimal places."

    Design: Corner/state_machines/rate_filing_disapproval_records_reviewer_and_note
    """
    pin_clock(client, CLOCK_ORIGIN)
    zone = create_zone(client, exposure_cap_cents=900_000_000)
    filing = file_rate(
        client,
        zone["id"],
        filed_rate_per_1000_cents=900,
        voluntary_market_avg_rate_per_1000_cents=800,
        effective_date="2026-08-01",
    )

    response = client.review_rate_filing(
        filing["id"],
        f.filing_review_payload(
            decision=DECISION_DISAPPROVE, note="indication not supported"
        ),
        regulator_headers(),
    )

    validate_success(response, 200)
    reviewed = read_filing(client, filing["id"])
    assert_field_equals(reviewed, "status", FILING_STATUS_DISAPPROVED)
    assert_field_equals(reviewed, "reviewed_by_user_id", "reg-1")
    assert_field_equals(reviewed, "review_note", "indication not supported")
    assert_ratio(reviewed["differential_pct"], "0.1250", "differential_pct")
    assert_field_equals(reviewed, "filed_by_user_id", "ra-1")


def test_disapproved_filing_rejects_a_second_review(client):
    """A disapproved filing is terminal, so a second review cannot overwrite it.

    PRD: "Review is only possible while the filing's `status` is `FILED`, and the
    reviewer must be a different person from the filer (§2.8)."

    PRD: "`DISAPPROVED` and `SUPERSEDED` are both terminal."

    Design: Corner/state_machines/disapproved_filing_rejects_a_second_review
    """
    pin_clock(client, CLOCK_ORIGIN)
    zone = create_zone(client, exposure_cap_cents=900_000_000)
    filing = file_rate(client, zone["id"])
    validate_success(
        client.review_rate_filing(
            filing["id"],
            f.filing_review_payload(
                decision=DECISION_DISAPPROVE, note="indication not supported"
            ),
            regulator_headers(),
        ),
        200,
    )

    response = client.review_rate_filing(
        filing["id"], f.filing_review_payload(), second_regulator_headers()
    )

    validate_error(response, ERR_FILING_NOT_REVIEWABLE)
    unchanged = read_filing(client, filing["id"])
    assert_field_equals(unchanged, "status", FILING_STATUS_DISAPPROVED)
    assert_field_equals(unchanged, "reviewed_by_user_id", "reg-1")


def test_producer_suspension_then_reinstatement_cycles_back_to_appointed(client):
    """Reinstatement restores the appointment without recomputing the rate.

    PRD: "An `action` of `SUSPEND` requires `APPOINTED` and moves the agreement
    `APPOINTED → SUSPENDED`; while suspended the agent may neither create nor
    submit applications, and no policy may be bound on an application of theirs,
    but existing policies are left completely untouched and
    `ytd_commission_cents` does not move."

    PRD: "An `action` of `REINSTATE` requires `SUSPENDED` and moves it back
    `SUSPENDED → APPOINTED`, retaining the `commission_rate_bps` written at
    agreement execution rather than recomputing it — the suspend-and-reinstate
    loop may repeat any number of times."

    Design: Corner/state_machines/producer_suspension_then_reinstatement_cycles_back_to_appointed
    """
    pin_clock(client, CLOCK_ORIGIN)
    producer = create_appointed_producer(client)

    suspended = validate_success(
        client.producer_status_action(
            producer["id"],
            f.producer_status_action_payload(
                action=PRODUCER_ACTION_SUSPEND, reason="E&O certificate under review"
            ),
            admin_headers(),
        ),
        200,
    )
    validate_success(
        client.producer_status_action(
            producer["id"],
            f.producer_status_action_payload(action=PRODUCER_ACTION_REINSTATE, reason=None),
            admin_headers(),
        ),
        200,
    )

    assert_field_equals(suspended, "agreement_status", AGREEMENT_STATUS_SUSPENDED)
    reinstated = read_producer(client, producer["id"])
    assert_field_equals(reinstated, "agreement_status", AGREEMENT_STATUS_APPOINTED)
    assert_field_equals(reinstated, "commission_rate_bps", COMMISSION_BPS_STANDARD)
    assert_date_equals(
        reinstated["agreement_effective_date"], "2026-08-01", "agreement_effective_date"
    )
    assert_cents(reinstated["ytd_commission_cents"], 0, "ytd_commission_cents")


def test_producer_agreement_execution_twice_returns_producer_status_invalid(client):
    """A second agreement execution is refused and does not move the effective date.

    PRD: "Executing the producer agreement — which requires the agreement to
    currently be `PENDING` — carries an `agreement_effective_date` in the
    request, moves `agreement_status` from `PENDING` to `APPOINTED`, and fixes
    the commission rate from the tier: a `STANDARD` tier writes 1,000 basis
    points (ten percent of commissionable premium), and a `PREFERRED` tier
    writes 1,250 basis points (twelve and a half percent)."

    PRD: "Producer agreement state: `PENDING` for agreement execution, `APPOINTED`
    for suspension, `SUSPENDED` for reinstatement, and either `APPOINTED` or
    `SUSPENDED` for termination, or `ERR_PRODUCER_STATUS_INVALID` (409)."

    Design: Corner/state_machines/producer_agreement_execution_twice_returns_producer_status_invalid
    """
    pin_clock(client, CLOCK_ORIGIN)
    producer = create_appointed_producer(client, agreement_effective_date="2026-08-01")

    response = client.execute_producer_agreement(
        producer["id"], f.agreement_execution_payload("2026-08-15"), admin_headers()
    )

    validate_error(response, ERR_PRODUCER_STATUS_INVALID)
    unchanged = read_producer(client, producer["id"])
    assert_field_equals(unchanged, "agreement_status", AGREEMENT_STATUS_APPOINTED)
    assert_date_equals(
        unchanged["agreement_effective_date"], "2026-08-01", "agreement_effective_date"
    )


def test_eligibility_review_on_draft_application_returns_not_reviewable(client):
    """An unsubmitted application cannot be reviewed and records no reviewer.

    PRD: "An `Underwriter` then reviews eligibility on an application whose `status`
    is `SUBMITTED` or `ELIGIBILITY_HELD`; from any other state the review is
    rejected with `ERR_APPLICATION_NOT_REVIEWABLE`."

    PRD: "Both decisions record the reviewing underwriter's `X-User-ID` as
    `eligibility_reviewer_user_id` and increment the application's `version` by
    one — and that recorded identifier is what later bars the same person from
    binding the policy."

    Design: Corner/state_machines/eligibility_review_on_draft_application_returns_not_reviewable
    """
    foundations = _registry_only_foundations(client)
    chain = create_draft_application(client, foundations)

    response = client.review_application_eligibility(
        chain.application_id, f.eligibility_review_payload(), reviewer_headers()
    )

    validate_error(response, ERR_APPLICATION_NOT_REVIEWABLE)
    application = read_application(client, chain.application_id)
    assert_field_equals(application, "status", APP_STATUS_DRAFT)
    assert_field_null(application, "eligibility_reviewer_user_id")


def test_second_submission_of_a_submitted_application_returns_not_submittable(
    roomy_foundations,
):
    """Submission is not idempotent and the first anchor instant survives.

    PRD: "Submitting an application is the producer's act, permitted only on an
    application they own whose `status` is `DRAFT` or `ELIGIBILITY_HELD` —
    anything else is rejected with `ERR_APPLICATION_NOT_SUBMITTABLE`."

    PRD: "Whatever the outcome, a successful submission writes `submitted_at` to the
    current logical clock, writes `declination_count` from the sufficiency test
    just described, pins `quote_rate_filing_id` to the filing that rate selection
    chose, writes the three quote fields, and increments the application's
    `version` by one."

    Design: Corner/state_machines/second_submission_of_a_submitted_application_returns_not_submittable
    """
    client = roomy_foundations.client
    chain = build_submitted_application(
        client, roomy_foundations, declined_on="2026-07-03"
    )
    assert_field_equals(chain.application, "status", APP_STATUS_SUBMITTED)
    assert_instant_equals(chain.application["submitted_at"], CLOCK_BASE, "submitted_at")

    response = client.submit_application(
        chain.application_id, {}, chain.producer_headers
    )

    validate_error(response, ERR_APPLICATION_NOT_SUBMITTABLE)
    application = read_application(client, chain.application_id)
    assert_field_equals(application, "status", APP_STATUS_SUBMITTED)
    assert_instant_equals(application["submitted_at"], CLOCK_BASE, "submitted_at")
    assert_field_equals(application, "declination_count", 3)


def test_assessment_invoicing_from_draft_returns_state_invalid(client):
    """Invoicing is only defined from ALLOCATED, so a draft event is refused.

    PRD: "The server immediately writes `assessable_amount_cents` as the trigger loss
    minus the reserve balance, with a negative result replaced by zero. The event
    opens in `status` `DRAFT` with `allocated_total_cents` and `remainder_cents`
    at 0, `allocation_run_count` at 0 and `cancellation_reason` null."

    PRD: "Invoicing moves the event `ALLOCATED → INVOICED`, which requires
    `allocated_total_cents` to equal `assessable_amount_cents`, makes the
    allocations payable, and increments the event's `version` by one."

    PRD: "Assessment state: `DRAFT` or `ALLOCATED` for an allocation run, `ALLOCATED`
    for invoicing, and one of `DRAFT`, `ALLOCATED` or `INVOICED` for
    cancellation, or `ERR_ASSESSMENT_STATE_INVALID` (409)."

    Design: Corner/state_machines/assessment_invoicing_from_draft_returns_state_invalid
    """
    pin_clock(client, CLOCK_BASE)
    create_member_insurer(client)
    zone = create_zone(client, exposure_cap_cents=900_000_000)
    event = create_event(
        client,
        zone["id"],
        trigger_loss_cents=200_000_001,
        reserve_balance_cents_at_trigger=100_000_000,
    )

    response = client.invoice_assessment(event["id"], {}, admin_headers())

    validate_error(response, ERR_ASSESSMENT_STATE_INVALID)
    stored = read_event(client, event["id"])
    assert_field_equals(stored, "status", EVENT_STATUS_DRAFT)
    assert_cents(
        stored["assessable_amount_cents"], 100_000_001, "assessable_amount_cents"
    )
    assert_field_equals(stored, "allocation_run_count", 0)
    _rows, meta = validate_paginated(
        client.list_assessment_event_allocations(
            event["id"], admin_headers(), {"limit": 10}
        )
    )
    assert_field_equals(meta, "total_count", 0)


def test_allocation_payment_before_invoicing_returns_not_payable(client):
    """A pending allocation on a merely allocated event is not yet payable.

    PRD: "The allocation's `status` must be `PENDING` and its parent event's `status`
    must be `INVOICED`, or the payment is refused with
    `ERR_ALLOCATION_NOT_PAYABLE`; the allocation's `member_insurer_id` must equal
    the caller's `X-User-ID`; the paying carrier's membership `status` must be
    `ACTIVE` or `RUNOFF` — a `WITHDRAWN` carrier may not pay, and is refused with
    `ERR_MEMBER_NOT_ACTIVE`; and `amount_cents` must equal the allocation's
    `net_due_cents` exactly, since the plan accepts no partial or over-payment,
    or the refusal is `ERR_PAYMENT_AMOUNT_MISMATCH`."

    PRD: "A first run moves the event `DRAFT → ALLOCATED`: it creates one allocation
    per eligible member, each in `status` `PENDING` with `paid_at` null, writes
    `allocated_total_cents` and `remainder_cents`, increments
    `allocation_run_count` by one, raises each touched member's
    `cumulative_assessed_cents` by that member's `net_due_cents` while
    incrementing each member's `version` by one, and increments the event's
    `version` by one."

    Design: Corner/state_machines/allocation_payment_before_invoicing_returns_not_payable
    """
    pin_clock(client, CLOCK_BASE)
    member = create_member_insurer(
        client, market_share_pct=100.00, written_premium_share_pct=100.00
    )
    zone = create_zone(client, exposure_cap_cents=900_000_000)
    event = create_event(
        client,
        zone["id"],
        trigger_loss_cents=200_000_000,
        reserve_balance_cents_at_trigger=100_000_000,
    )
    validate_success(
        client.run_allocation(
            event["id"], f.allocation_run_payload(event["version"]), admin_headers()
        ),
        200,
    )
    allocations, _meta = validate_paginated(
        client.list_assessment_event_allocations(
            event["id"], admin_headers(), {"limit": 10}
        )
    )
    assert_count(allocations, 1, "allocations")
    allocation = allocations[0]

    response = client.pay_allocation(
        allocation["id"],
        f.payment_payload(100_000_000),
        make_member_insurer_headers(member["id"]),
    )

    validate_error(response, ERR_ALLOCATION_NOT_PAYABLE)
    rows, _after = validate_paginated(
        client.list_assessment_event_allocations(
            event["id"], admin_headers(), {"limit": 10}
        )
    )
    unpaid = rows[0]
    assert_field_equals(unpaid, "status", ALLOCATION_STATUS_PENDING)
    assert_cents(unpaid["net_due_cents"], 100_000_000, "net_due_cents")
    assert_field_null(unpaid, "paid_at")
    assert_field_equals(read_event(client, event["id"]), "status", EVENT_STATUS_ALLOCATED)


def test_completion_with_conditions_raises_requirement_and_holds_the_application(
    roomy_foundations,
):
    """Pass-with-conditions raises one dated requirement and holds the application.

    PRD: "`PENDING → PASS_WITH_CONDITIONS` is available when the request supplies at
    least one requirement. It creates one improvement requirement per supplied
    entry, each in `status` `OPEN` with `due_at` set to forty-five days after the
    inspection's `completed_at`; it writes the inspection's
    `open_requirement_count` to the number of requirements created and its
    `cleared_major_count` to 0; and it cascades the application
    `INSPECTION_PENDING → IMPROVEMENTS_REQUIRED`, on which branch
    `approved_to_bind_at` and `bind_deadline_at` both remain null."

    PRD: "All three outcomes write `inspector_user_id` from `X-User-ID`, write
    `completed_at` to the current logical clock, and write
    `observed_condition_score`, and all three increment both the inspection's
    `version` and the application's `version` by one."

    Design: Corner/state_machines/completion_with_conditions_raises_requirement_and_holds_the_application
    """
    client = roomy_foundations.client
    chain = build_inspection_pending_application(client, roomy_foundations)

    response = client.complete_inspection(
        chain.inspection_id,
        f.inspection_completion_payload(
            observed_condition_score=64,
            result=INSPECTION_RESULT_PASS_WITH_CONDITIONS,
            requirements=[
                f.requirement_spec(code=REQUIREMENT_CODE_ROOF, severity=SEVERITY_MAJOR)
            ],
        ),
        inspector_headers(),
    )

    validate_success(response, 200)
    inspection = read_inspection(client, chain.inspection_id)
    assert_field_equals(
        inspection, "result", INSPECTION_RESULT_PASS_WITH_CONDITIONS
    )
    assert_field_equals(inspection, "inspector_user_id", "insp-1")
    assert_instant_equals(inspection["completed_at"], CLOCK_BASE, "completed_at")
    assert_field_equals(inspection, "observed_condition_score", 64)
    assert_field_equals(inspection, "open_requirement_count", 1)
    assert_field_equals(inspection, "cleared_major_count", 0)

    requirements = read_requirements(client, chain.inspection_id)
    assert_count(requirements, 1, "requirements")
    requirement = requirements[0]
    assert_field_equals(requirement, "code", REQUIREMENT_CODE_ROOF)
    assert_field_equals(requirement, "severity", SEVERITY_MAJOR)
    assert_field_equals(requirement, "status", REQUIREMENT_STATUS_OPEN)
    assert_instant_equals(requirement["due_at"], "2026-10-16T00:00:00Z", "due_at")

    application = read_application(client, chain.application_id)
    assert_field_equals(application, "status", APP_STATUS_IMPROVEMENTS_REQUIRED)
    assert_fields_null(application, ("approved_to_bind_at", "bind_deadline_at"))


def test_second_completion_of_the_same_inspection_returns_already_completed(
    roomy_foundations,
):
    """A completed inspection is terminal and a second completion changes nothing.

    PRD: "The inspection's current `result` must be `PENDING`, or the request is
    refused with `ERR_INSPECTION_ALREADY_COMPLETED`."

    PRD: "`PENDING → PASS` is available when the request supplies no requirements. It
    cascades the application `INSPECTION_PENDING → APPROVED_TO_BIND`, writing
    `approved_to_bind_at` to the current logical clock and `bind_deadline_at` to
    thirty days after that instant."

    Design: Corner/state_machines/second_completion_of_the_same_inspection_returns_already_completed
    """
    client = roomy_foundations.client
    chain = build_bindable_application(
        client, roomy_foundations, observed_condition_score=72
    )

    response = client.complete_inspection(
        chain.inspection_id,
        f.inspection_completion_payload(
            observed_condition_score=40, result=INSPECTION_RESULT_FAIL
        ),
        second_inspector_headers(),
    )

    validate_error(response, ERR_INSPECTION_ALREADY_COMPLETED)
    inspection = read_inspection(client, chain.inspection_id)
    assert_field_equals(inspection, "result", INSPECTION_RESULT_PASS)
    assert_field_equals(inspection, "observed_condition_score", 72)
    assert_field_equals(inspection, "inspector_user_id", "insp-1")
    application = read_application(client, chain.application_id)
    assert_field_equals(application, "status", APP_STATUS_APPROVED_TO_BIND)
    assert_instant_equals(
        application["bind_deadline_at"], "2026-10-01T00:00:00Z", "bind_deadline_at"
    )


def test_clearance_of_an_open_requirement_returns_requirement_state_invalid(
    roomy_foundations,
):
    """Clearance from OPEN is refused and the remediation counters do not move.

    PRD: "Clearance is available only from `EVIDENCE_SUBMITTED`."

    PRD: "Evidence submission, clearance and waiver attempted from a status outside
    their respective accepted sets are all refused with
    `ERR_REQUIREMENT_STATE_INVALID`."

    PRD: "The requirement's `due_at` is the informational deadline shown to the
    producer, and its lifecycle `status` runs `OPEN`, then either
    `EVIDENCE_SUBMITTED` and on to the terminal `CLEARED`, or directly to the
    terminal `WAIVED`. Its `evidence_reference`, `cleared_at` and `waiver_reason`
    are null until the corresponding step writes them."

    Design: Corner/state_machines/clearance_of_an_open_requirement_returns_requirement_state_invalid
    """
    client = roomy_foundations.client
    chain = build_inspection_pending_application(client, roomy_foundations)
    complete_inspection(
        chain,
        observed_condition_score=64,
        result=INSPECTION_RESULT_PASS_WITH_CONDITIONS,
        requirements=[
            f.requirement_spec(code=REQUIREMENT_CODE_ELECTRICAL, severity=SEVERITY_MINOR)
        ],
    )
    requirement = read_requirements(client, chain.inspection_id)[0]

    response = client.clear_requirement(
        requirement["id"],
        f.requirement_clearance_payload(note="looks fine to me"),
        inspector_headers(),
    )

    validate_error(response, ERR_REQUIREMENT_STATE_INVALID)
    unchanged = read_requirements(client, chain.inspection_id)[0]
    assert_field_equals(unchanged, "status", REQUIREMENT_STATUS_OPEN)
    assert_fields_null(unchanged, ("cleared_at", "evidence_reference"))
    inspection = read_inspection(client, chain.inspection_id)
    assert_field_equals(inspection, "open_requirement_count", 1)
    assert_field_equals(
        inspection, "result", INSPECTION_RESULT_PASS_WITH_CONDITIONS
    )
    assert_field_equals(
        read_application(client, chain.application_id),
        "status",
        APP_STATUS_IMPROVEMENTS_REQUIRED,
    )


def test_pre_inception_cancellation_of_a_future_dated_bind_leaves_bound_directly(
    roomy_foundations,
):
    """A future-dated bind is BOUND, and a plan-initiated cancellation refunds it all.

    PRD: "The `coverage_status` starts at `IN_FORCE` when the `effective_date` is on
    or before the bind clock date, and at `BOUND` when the policy is
    future-dated."

    PRD: "Cancellation ends coverage early. An `Underwriter` cancels an `IN_FORCE`
    policy, and either an `Underwriter` or a `PlanAdmin` may act on the
    cancellation surface; a policy still merely `BOUND` may be cancelled only
    when the supplied `cancel_reason` is `PLAN_INITIATED`."

    PRD: "Count the whole days from the policy's `effective_date` to its
    `cancellation_date`; that is the days in force. Subtract that count from
    three hundred sixty-five, treat a negative result as zero, and divide by
    three hundred sixty-five; that quotient is the unearned fraction, and it
    equals one when the cancellation date is the effective date itself."

    PRD: "On early termination the same unearned fraction used by the refund
    calculation is applied to the amount originally credited: multiply the
    policy's `commission_credited_cents` by that unearned fraction, round half up
    to whole cents, and write the result to `commission_returned_cents`."

    PRD: "First, any policy whose `coverage_status` is `BOUND` and whose
    `effective_date` is on or before the clock date moves `BOUND → IN_FORCE`; the
    territory's `aggregate_insured_value_cents` does **not** change on this move,
    because a `BOUND` policy was already counted in the exposure, and only the
    policy's `version` increments."

    Design: Corner/state_machines/pre_inception_cancellation_of_a_future_dated_bind_leaves_bound_directly
    """
    client = roomy_foundations.client
    chain = build_bindable_application(
        client, roomy_foundations, observed_condition_score=72
    )
    policy = bind(chain, effective_date="2026-09-15")
    assert_field_equals(policy, "coverage_status", COVERAGE_STATUS_BOUND)

    response = client.cancel_policy(
        chain.policy_id,
        f.cancellation_payload(
            cancel_reason=CANCEL_REASON_PLAN_INITIATED, cancel_date="2026-09-15"
        ),
        admin_headers(),
    )

    cancelled = validate_success(response, 200)
    assert_field_equals(cancelled, "coverage_status", COVERAGE_STATUS_CANCELLED)
    assert_field_equals(cancelled, "cancel_reason", CANCEL_REASON_PLAN_INITIATED)
    assert_cents(cancelled["unearned_premium_cents"], 577_125, "unearned_premium_cents")
    assert_cents(cancelled["cancellation_fee_cents"], 17_314, "cancellation_fee_cents")
    assert_cents(cancelled["refund_cents"], 559_811, "refund_cents")
    assert_cents(
        cancelled["commission_returned_cents"], 57_713, "commission_returned_cents"
    )
    producer = read_producer(client, roomy_foundations.producer_id)
    assert_cents(producer["ytd_commission_cents"], 0, "ytd_commission_cents")
    zone = read_zone(client, roomy_foundations.zone_id)
    assert_cents(
        zone["aggregate_insured_value_cents"], 0, "aggregate_insured_value_cents"
    )
    assert_ratio(zone["concentration_ratio"], "0.0000", "concentration_ratio")
    assert_field_equals(zone, "status", ZONE_STATUS_OPEN)
    sweep = run_sweep(client)
    assert_field_equals(sweep, "activated_policy_count", 0)
