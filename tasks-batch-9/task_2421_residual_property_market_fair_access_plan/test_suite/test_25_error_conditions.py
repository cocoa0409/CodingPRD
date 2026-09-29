"""Error conditions: each refusal reached deliberately and shown to change nothing.

The tests are grouped by the part of the plan that raises them — uniqueness,
pre-submission assembly, depopulation and coverage state, assessment settlement,
and the underwriting gates at bind — and every group re-reads the records
afterwards to show the refusal left no partial write behind.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_COVERAGE_LIMIT_EXCEEDED,
    ERR_DUPLICATE_DECLINATION,
    ERR_DUPLICATE_IDENTIFIER,
    ERR_ELECTION_WINDOW_CLOSED,
    ERR_INSPECTION_NOT_ORDERABLE,
    ERR_INSPECTION_STALE,
    ERR_MAJOR_REQUIREMENT_NOT_WAIVABLE,
    ERR_NO_APPROVED_RATE,
    ERR_NO_ASSESSABLE_MEMBERS,
    ERR_OFFER_ALREADY_OUTSTANDING,
    ERR_OFFER_NOT_OUTSTANDING,
    ERR_PAYMENT_AMOUNT_MISMATCH,
    ERR_PERIL_NOT_OFFERED,
    ERR_POLICY_NOT_IN_FORCE,
    ERR_VACANT_PROPERTY_INELIGIBLE,
)
from test_helpers.assertions import (
    assert_cents,
    assert_field_equals,
    assert_field_null,
    assert_fields_equal,
    find_one,
)
from test_helpers.constants import (
    ALLOCATION_STATUS_PENDING,
    APP_STATUS_APPROVED_TO_BIND,
    APP_STATUS_DRAFT,
    BASIS_PREMIUM_VOLUME,
    CANCEL_REASON_POLICYHOLDER_REQUEST,
    CLOCK_BASE,
    COVERAGE_STATUS_CANCELLED,
    DEPOP_STATUS_NOT_OFFERED,
    ELECTION_ACCEPT,
    ELECTION_DECLINE,
    EVENT_STATUS_DRAFT,
    EVENT_STATUS_INVOICED,
    INSPECTION_RESULT_PASS,
    INSPECTION_RESULT_PASS_WITH_CONDITIONS,
    OCCUPANCY_VACANT,
    OFFER_STATUS_WITHDRAWN,
    PACKAGE_EXTENDED_WIND,
    PERIL_WILDFIRE,
    REQUIREMENT_CODE_ROOF,
    REQUIREMENT_STATUS_CLEARED,
    REQUIREMENT_STATUS_OPEN,
    SEVERITY_MAJOR,
)
from test_helpers.fixtures import (
    DEFAULT_MEMBER_SPECS,
    Foundations,
    build_bindable_application,
    build_foundations,
    build_in_force_policy,
    build_inspection_pending_application,
    build_invoiced_event,
    complete_inspection,
    create_applicant,
    create_appointed_producer,
    create_draft_application,
    create_event,
    create_member_insurers,
    create_offer,
    create_property,
    create_zone,
    pin_clock,
    read_allocations,
    read_application,
    read_event,
    read_inspection,
    read_member,
    read_offer,
    read_policy,
    read_requirements,
    read_zone,
)
from test_helpers.test_users import (
    admin_headers,
    binder_headers,
    inspector_headers,
    make_member_insurer_headers,
    reviewer_headers,
)


def test_duplicate_identifier_and_duplicate_declination_are_rejected(client):
    """Re-using a unique identifier or re-declining the same carrier both conflict.

    PRD: "**Uniqueness** of a member's `naic_code`, a producer's `license_number`, a
    territory's `code` and an applicant's `email`, or `ERR_DUPLICATE_IDENTIFIER`
    (409), on the four corresponding create operations."

    PRD: "At most one declination may exist for a given application-and-carrier pair; a
    second attempt is rejected with `ERR_DUPLICATE_DECLINATION`."

    PRD: "A fresh application sits in `status` `DRAFT` with `declination_count` at 0;
    `quoted_annual_premium_cents` and `voluntary_equivalent_premium_cents` at 0;
    `voluntary_market_comparison_pct` at 0.0; and `quote_rate_filing_id`,
    `submitted_at`, `eligibility_hold_reason`, `decline_reason`,
    `eligibility_reviewer_user_id`, `approved_to_bind_at` and `bind_deadline_at`
    all null."

    Design: Corner/errors/duplicate_identifier_and_duplicate_declination_are_rejected
    """
    foundations = build_foundations(
        client,
        member_specs=DEFAULT_MEMBER_SPECS[:1],
        zone_overrides={"exposure_cap_cents": 900_000_000},
    )
    chain = create_draft_application(client, foundations)
    member_id = foundations.member_ids[0]
    validate_success(
        client.create_declination(
            chain.application_id,
            f.declination_payload(member_insurer_id=member_id),
            chain.producer_headers,
        ),
        201,
    )

    duplicate_naic = client.create_member_insurer(
        f.member_insurer_payload(name="Carrier One Again", naic_code="10001"),
        admin_headers(),
    )
    duplicate_email = client.create_applicant(
        f.applicant_payload(full_name="Another Owner", email="ann@example.com"),
        foundations.producer_headers,
    )
    duplicate_declination = client.create_declination(
        chain.application_id,
        f.declination_payload(member_insurer_id=member_id, evidence_reference="DEC-2"),
        chain.producer_headers,
    )

    validate_error(duplicate_naic, ERR_DUPLICATE_IDENTIFIER)
    validate_error(duplicate_email, ERR_DUPLICATE_IDENTIFIER)
    validate_error(duplicate_declination, ERR_DUPLICATE_DECLINATION)
    assert_field_equals(
        read_application(client, chain.application_id), "declination_count", 0
    )
    _rows, meta = validate_paginated(
        client.list_member_insurers(admin_headers(), {"limit": 10})
    )
    assert_field_equals(meta, "total_count", 1)


def test_pre_submission_eligibility_and_ordering_errors_are_rejected(client):
    """Four pre-bind refusals off one draft, each with its own error identifier.

    PRD: "The broader `EXTENDED_WIND` package is only offered where the territory's
    dominant `peril` is `HURRICANE`; requesting it in a wildfire or earthquake
    territory yields `ERR_PERIL_NOT_OFFERED`."

    PRD: "And the requested dwelling limit must be no greater than the plan's statutory
    ceiling of one and a half million dollars — 150,000,000 cents — **and** no
    greater than the property's own `replacement_cost_cents`; breaching either
    bound yields `ERR_COVERAGE_LIMIT_EXCEEDED`."

    PRD: "An `Underwriter` orders a site inspection on an application whose `status` is
    `INSPECTION_PENDING` or `IMPROVEMENTS_REQUIRED`; from any other state the
    order is refused with `ERR_INSPECTION_NOT_ORDERABLE`."

    PRD: "The producer's agreement must be `APPOINTED`, and an approved rate must exist
    for the property's territory and the requested package with an
    `effective_date` on or before the current clock date, selected by the rule in
    §3.2."

    Design: Corner/errors/pre_submission_eligibility_and_ordering_errors_are_rejected
    """
    pin_clock(client, CLOCK_BASE)
    zone = create_zone(
        client, code="WIL-01", peril=PERIL_WILDFIRE, exposure_cap_cents=900_000_000
    )
    producer = create_appointed_producer(client)
    foundations = Foundations(client=client, zone=zone, producer=producer)
    applicant = create_applicant(client, foundations)
    prop = create_property(client, foundations, replacement_cost_cents=100_000_000)
    application = validate_success(
        client.create_application(
            f.application_payload(
                property_id=prop["id"], applicant_id=applicant["id"]
            ),
            foundations.producer_headers,
        ),
        201,
    )

    wrong_peril = client.create_application(
        f.application_payload(
            property_id=prop["id"],
            applicant_id=applicant["id"],
            requested_peril_package=PACKAGE_EXTENDED_WIND,
        ),
        foundations.producer_headers,
    )
    over_limit = client.create_application(
        f.application_payload(
            property_id=prop["id"],
            applicant_id=applicant["id"],
            requested_dwelling_limit_cents=100_000_001,
        ),
        foundations.producer_headers,
    )
    early_inspection = client.order_inspection(
        application["id"], {}, reviewer_headers()
    )
    submission = client.submit_application(
        application["id"], {}, foundations.producer_headers
    )

    validate_error(wrong_peril, ERR_PERIL_NOT_OFFERED)
    validate_error(over_limit, ERR_COVERAGE_LIMIT_EXCEEDED)
    validate_error(early_inspection, ERR_INSPECTION_NOT_ORDERABLE)
    validate_error(submission, ERR_NO_APPROVED_RATE)
    assert_field_equals(
        read_application(client, application["id"]), "status", APP_STATUS_DRAFT
    )
    _rows, meta = validate_paginated(
        client.list_applications(admin_headers(), {"limit": 10})
    )
    assert_field_equals(meta, "total_count", 1)


def test_depopulation_and_coverage_state_errors_are_rejected(roomy_foundations):
    """Four refusals along the take-out path, none of which moves a state.

    PRD: "Making an offer requires the target policy's `coverage_status` to be
    `IN_FORCE` (otherwise `ERR_POLICY_NOT_IN_FORCE`) and its `depopulation_status`
    to be `NOT_OFFERED` (otherwise `ERR_OFFER_ALREADY_OUTSTANDING`), and the
    offering carrier's membership `status` to be `ACTIVE` — a carrier in `RUNOFF`
    or `WITHDRAWN` may not offer, and is refused with `ERR_MEMBER_NOT_ACTIVE`."

    PRD: "The offer's `status` must be `OUTSTANDING`, or the election is refused with
    `ERR_OFFER_NOT_OUTSTANDING`, and the election clock instant must be at or
    before `election_deadline_at`, inclusive of that instant, or
    `ERR_ELECTION_WINDOW_CLOSED`."

    PRD: "Withdrawal moves the offer `OUTSTANDING → WITHDRAWN`, increments its
    `version`, and resets the policy's `depopulation_status` from
    `OFFER_OUTSTANDING` back to `NOT_OFFERED` with the policy's `version`
    incremented by one — which makes the policy offerable again by any `ACTIVE`
    member, so the depopulation dimension is genuinely cyclic."

    PRD: "The predecessor's `coverage_status` must be `IN_FORCE`, or the renewal is
    refused with `ERR_POLICY_NOT_IN_FORCE`."

    Design: Corner/errors/depopulation_and_coverage_state_errors_are_rejected
    """
    client = roomy_foundations.client
    chain = build_in_force_policy(client, roomy_foundations)
    offer = create_offer(
        chain,
        member_index=0,
        offered_premium_cents=600_000,
        election_deadline_at="2026-09-10T00:00:00Z",
    )

    second_offer = client.create_takeout_offer(
        chain.policy_id,
        f.takeout_offer_payload(
            member_insurer_id=roomy_foundations.member_ids[1],
            election_deadline_at="2026-09-10T00:00:00Z",
        ),
        roomy_foundations.member_headers(1),
    )
    validate_error(second_offer, ERR_OFFER_ALREADY_OUTSTANDING)

    pin_clock(client, "2026-09-10T00:00:01Z")
    late_election = client.elect_takeout_offer(
        offer["id"], f.election_payload(election=ELECTION_ACCEPT), chain.policyholder_headers
    )
    validate_error(late_election, ERR_ELECTION_WINDOW_CLOSED)

    validate_success(
        client.withdraw_takeout_offer(
            offer["id"],
            f.withdrawal_payload(reason="capacity reallocated"),
            roomy_foundations.member_headers(0),
        ),
        200,
    )
    assert_field_equals(
        read_offer(client, offer["id"]), "status", OFFER_STATUS_WITHDRAWN
    )

    election_on_withdrawn = client.elect_takeout_offer(
        offer["id"],
        f.election_payload(election=ELECTION_DECLINE),
        chain.policyholder_headers,
    )
    validate_error(election_on_withdrawn, ERR_OFFER_NOT_OUTSTANDING)

    validate_success(
        client.cancel_policy(
            chain.policy_id,
            f.cancellation_payload(
                cancel_reason=CANCEL_REASON_POLICYHOLDER_REQUEST,
                cancel_date="2026-09-10",
            ),
            binder_headers(),
        ),
        200,
    )
    renewal = client.renew_policy(
        chain.policy_id, f.renewal_payload("2027-09-01"), binder_headers()
    )

    validate_error(renewal, ERR_POLICY_NOT_IN_FORCE)
    policy = read_policy(client, chain.policy_id)
    assert_field_equals(policy, "coverage_status", COVERAGE_STATUS_CANCELLED)
    assert_field_equals(policy, "depopulation_status", DEPOP_STATUS_NOT_OFFERED)
    assert_field_equals(read_offer(client, offer["id"]), "credit_units_granted", 0)
    assert_field_equals(
        read_member(client, roomy_foundations.member_ids[0]), "takeout_credit_count", 0
    )
    _rows, meta = validate_paginated(
        client.list_policies(
            admin_headers(), {"predecessor_policy_id": chain.policy_id, "limit": 10}
        )
    )
    assert_field_equals(meta, "total_count", 0)


def test_assessment_payment_and_basis_weight_errors_are_rejected(client):
    """Settlement is exact-amount only, and an all-zero basis has no assessable set.

    PRD: "`amount_cents` must equal the allocation's `net_due_cents` exactly, since the
    plan accepts no partial or over-payment, or the refusal is
    `ERR_PAYMENT_AMOUNT_MISMATCH`."

    PRD: "The eligible members are those whose membership `status` is `ACTIVE` or
    `RUNOFF`; `WITHDRAWN` carriers are excluded."

    PRD: "Two fiscal gates follow: `assessable_amount_cents` must be **strictly greater
    than zero**, so a loss exactly equal to the reserve balance yields zero and
    blocks the run with `ERR_LOSSES_WITHIN_RESERVES`; and the eligible member set
    must be non-empty with a total basis weight greater than zero, or
    `ERR_NO_ASSESSABLE_MEMBERS`."

    Design: Corner/errors/assessment_payment_and_basis_weight_errors_are_rejected
    """
    pin_clock(client, CLOCK_BASE)
    members = create_member_insurers(
        client,
        [
            {
                "name": "Carrier One",
                "naic_code": "10001",
                "market_share_pct": 30.00,
                "written_premium_share_pct": 0.00,
            },
            {
                "name": "Carrier Two",
                "naic_code": "10002",
                "market_share_pct": 30.00,
                "written_premium_share_pct": 0.00,
            },
            {
                "name": "Carrier Three",
                "naic_code": "10003",
                "market_share_pct": 40.00,
                "written_premium_share_pct": 0.00,
            },
        ],
    )
    zone = create_zone(client, exposure_cap_cents=900_000_000)
    invoiced = build_invoiced_event(client, zone["id"], 200_000_000, 100_000_000)
    allocation = find_one(
        read_allocations(client, invoiced["id"]),
        "member_insurer_id",
        members[0]["id"],
    )

    underpayment = client.pay_allocation(
        allocation["id"],
        f.payment_payload(29_999_999),
        make_member_insurer_headers(members[0]["id"]),
    )
    validate_error(underpayment, ERR_PAYMENT_AMOUNT_MISMATCH)

    premium_volume_event = create_event(
        client,
        zone["id"],
        trigger_loss_cents=200_000_000,
        reserve_balance_cents_at_trigger=100_000_000,
        allocation_basis=BASIS_PREMIUM_VOLUME,
    )
    empty_basis_run = client.run_allocation(
        premium_volume_event["id"],
        f.allocation_run_payload(premium_volume_event["version"]),
        admin_headers(),
    )

    validate_error(empty_basis_run, ERR_NO_ASSESSABLE_MEMBERS)
    unpaid = find_one(
        read_allocations(client, invoiced["id"]),
        "member_insurer_id",
        members[0]["id"],
    )
    assert_cents(unpaid["net_due_cents"], 30_000_000, "net_due_cents")
    assert_field_equals(unpaid, "status", ALLOCATION_STATUS_PENDING)
    assert_field_null(unpaid, "paid_at")
    assert_field_equals(
        read_event(client, invoiced["id"]), "status", EVENT_STATUS_INVOICED
    )
    second = read_event(client, premium_volume_event["id"])
    assert_field_equals(second, "status", EVENT_STATUS_DRAFT)
    assert_field_equals(second, "allocation_run_count", 0)
    assert_cents(second["allocated_total_cents"], 0, "allocated_total_cents")
    _rows, meta = validate_paginated(
        client.list_assessment_event_allocations(
            premium_volume_event["id"], admin_headers(), {"limit": 10}
        )
    )
    assert_field_equals(meta, "total_count", 0)


def test_vacancy_major_waiver_and_inspection_staleness_are_rejected(roomy_foundations):
    """Three underwriting refusals survive files that are otherwise perfect.

    PRD: "A property whose `occupancy` is `VACANT` is ineligible unless the chosen
    inspection carries a `VACANCY_CURE` requirement whose `status` is `CLEARED`;
    otherwise `ERR_VACANT_PROPERTY_INELIGIBLE`."

    PRD: "Severity is consequential in two directions: a `MAJOR` requirement earns
    rating credit when it is genuinely remediated and can never be waived, while a
    `MINOR` requirement may be waived but earns no credit."

    PRD: "The chosen inspection's `completed_at` must fall within ninety days of the
    bind clock date, inclusive of the ninetieth day, or `ERR_INSPECTION_STALE`."

    PRD: "It writes `cleared_at` to the current logical clock and increments the
    requirement's `version`; then, on a second hop, it decrements the parent
    inspection's `open_requirement_count` by one and — only when the requirement's
    `severity` is `MAJOR` — increments the parent's `cleared_major_count` by one,
    incrementing the inspection's `version`; then, on a third hop, if
    `open_requirement_count` has reached zero, the inspection's `result` flips
    `PASS_WITH_CONDITIONS → PASS` and the application cascades
    `IMPROVEMENTS_REQUIRED → APPROVED_TO_BIND` with `approved_to_bind_at` set to
    the current logical clock and `bind_deadline_at` set thirty days later."

    Design: Corner/errors/vacancy_major_waiver_and_inspection_staleness_are_rejected
    """
    client = roomy_foundations.client
    vacant_chain = build_bindable_application(
        client,
        roomy_foundations,
        observed_condition_score=88,
        property_overrides={"address_line": "5 Empty St", "occupancy": OCCUPANCY_VACANT},
    )
    conditioned_chain = build_inspection_pending_application(
        client,
        roomy_foundations,
        applicant_overrides={"email": "bea@example.com"},
        property_overrides={"address_line": "7 Elm St"},
    )
    complete_inspection(
        conditioned_chain,
        observed_condition_score=88,
        result=INSPECTION_RESULT_PASS_WITH_CONDITIONS,
        requirements=[
            f.requirement_spec(code=REQUIREMENT_CODE_ROOF, severity=SEVERITY_MAJOR)
        ],
    )
    requirement = read_requirements(client, conditioned_chain.inspection_id)[0]

    vacant_bind = client.bind_policy(
        f.bind_payload(vacant_chain.application_id, "2026-09-01"), binder_headers()
    )
    validate_error(vacant_bind, ERR_VACANT_PROPERTY_INELIGIBLE)
    assert_field_equals(
        read_application(client, vacant_chain.application_id),
        "status",
        APP_STATUS_APPROVED_TO_BIND,
    )

    waiver = client.waive_requirement(
        requirement["id"],
        {"reason": "roof deemed acceptable by desk review"},
        binder_headers(),
    )
    validate_error(waiver, ERR_MAJOR_REQUIREMENT_NOT_WAIVABLE)
    still_open = read_requirements(client, conditioned_chain.inspection_id)[0]
    assert_fields_equal(
        still_open,
        {"severity": SEVERITY_MAJOR, "status": REQUIREMENT_STATUS_OPEN},
    )

    validate_success(
        client.submit_requirement_evidence(
            requirement["id"],
            f.requirement_evidence_payload(evidence_reference="ROOF-INV-99"),
            conditioned_chain.producer_headers,
        ),
        200,
    )
    validate_success(
        client.clear_requirement(
            requirement["id"],
            f.requirement_clearance_payload(note="new roof verified"),
            inspector_headers(),
        ),
        200,
    )
    cleared = read_requirements(client, conditioned_chain.inspection_id)[0]
    assert_field_equals(cleared, "status", REQUIREMENT_STATUS_CLEARED)
    inspection = read_inspection(client, conditioned_chain.inspection_id)
    assert_field_equals(inspection, "result", INSPECTION_RESULT_PASS)
    assert_field_equals(inspection, "open_requirement_count", 0)
    assert_field_equals(inspection, "cleared_major_count", 1)
    assert_field_equals(
        read_application(client, conditioned_chain.application_id),
        "status",
        APP_STATUS_APPROVED_TO_BIND,
    )

    pin_clock(client, "2026-12-01T00:00:00Z")
    stale_bind = client.bind_policy(
        f.bind_payload(conditioned_chain.application_id, "2026-12-01"),
        binder_headers(),
    )

    validate_error(stale_bind, ERR_INSPECTION_STALE)
    zone = read_zone(client, roomy_foundations.zone_id)
    assert_cents(
        zone["aggregate_insured_value_cents"], 0, "aggregate_insured_value_cents"
    )
    _rows, meta = validate_paginated(
        client.list_policies(admin_headers(), {"limit": 10})
    )
    assert_field_equals(meta, "total_count", 0)
