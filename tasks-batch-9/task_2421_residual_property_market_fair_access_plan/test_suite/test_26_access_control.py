"""Access control: authentication, role exclusivity, ownership and separation of duties.

The four gates guarding a write are tested in the order the plan evaluates them:
an unrecognised or absent identity, a well-formed identity in the wrong role, an
entity-backed caller reaching for someone else's file, and a caller who is the
wrong *person* even though the role is right.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_FORBIDDEN_ROLE,
    ERR_NOT_RESOURCE_OWNER,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHENTICATED,
)
from test_helpers.assertions import (
    assert_cents,
    assert_field_equals,
    assert_field_null,
)
from test_helpers.constants import (
    AGREEMENT_STATUS_APPOINTED,
    APP_STATUS_APPROVED_TO_BIND,
    APP_STATUS_DRAFT,
    CLOCK_BASE,
    CLOCK_BASE_DATE,
    COMMISSION_TIER_PREFERRED,
    DECISION_APPROVE,
    FILING_STATUS_APPROVED,
    FILING_STATUS_FILED,
    INSPECTION_RESULT_PASS,
    INSPECTION_RESULT_PASS_WITH_CONDITIONS,
    PACKAGE_EXTENDED_WIND,
    REQUIREMENT_CODE_ELECTRICAL,
    REQUIREMENT_STATUS_OPEN,
    REQUIREMENT_STATUS_WAIVED,
    ROLE_PLAN_ADMIN,
    SEVERITY_MINOR,
    ZONE_STATUS_OPEN,
)
from test_helpers.fixtures import (
    Foundations,
    build_inspection_pending_application,
    complete_inspection,
    create_appointed_producer,
    create_draft_application,
    create_member_insurer,
    create_zone,
    file_rate,
    pin_clock,
    read_application,
    read_filing,
    read_inspection,
    read_producer,
    read_requirements,
    read_zone,
)
from test_helpers.test_users import (
    admin_headers,
    binder_headers,
    make_producer_headers,
    make_rate_analyst_headers,
    make_regulator_headers,
    make_underwriter_headers,
    rate_analyst_headers,
    regulator_headers,
    reviewer_headers,
    second_regulator_headers,
)


def test_exclusive_operations_of_other_roles_are_forbidden(client):
    """Five cross-role writes with well-formed bodies are all refused, changing nothing.

    PRD: "If the headers are well-formed but the named role is not authorized for
    the operation being attempted, the rejection is `ERR_FORBIDDEN_ROLE` (HTTP
    403)."

    PRD: "**Role authorization.** The caller's role is listed for the operation,
    or `ERR_FORBIDDEN_ROLE` (403)."

    PRD: "When `X-User-Role` is `PlanAdmin`, the identifier is not persisted on
    any record; plan administrators are trusted operators of membership,
    territory, producer-agreement, assessment, sweep and clock functions."

    Design: Corner/rbac/exclusive_operations_of_other_roles_are_forbidden
    """
    pin_clock(client, CLOCK_BASE)
    zone = create_zone(client, exposure_cap_cents=900_000_000)
    producer = create_appointed_producer(client)
    filing = file_rate(client, zone["id"])
    zone_version = read_zone(client, zone["id"])["version"]

    zone_attempt = client.create_cat_zone(
        f.cat_zone_payload(code="HUR-02", exposure_cap_cents=100_000_000),
        reviewer_headers(),
    )
    applicant_attempt = client.create_applicant(f.applicant_payload(), reviewer_headers())
    filing_attempt = client.create_rate_filing(
        f.rate_filing_payload(
            cat_zone_id=zone["id"],
            expected_zone_version=zone_version,
            peril_package=PACKAGE_EXTENDED_WIND,
            filed_rate_per_1000_cents=1200,
            voluntary_market_avg_rate_per_1000_cents=1000,
        ),
        regulator_headers(),
    )
    review_attempt = client.review_rate_filing(
        filing["id"],
        f.filing_review_payload(decision=DECISION_APPROVE),
        rate_analyst_headers(),
    )
    status_attempt = client.producer_status_action(
        producer["id"],
        f.producer_status_action_payload(reason=None),
        reviewer_headers(),
    )

    validate_error(zone_attempt, ERR_FORBIDDEN_ROLE)
    validate_error(applicant_attempt, ERR_FORBIDDEN_ROLE)
    validate_error(filing_attempt, ERR_FORBIDDEN_ROLE)
    validate_error(review_attempt, ERR_FORBIDDEN_ROLE)
    validate_error(status_attempt, ERR_FORBIDDEN_ROLE)
    untouched_filing = read_filing(client, filing["id"])
    assert_field_equals(untouched_filing, "status", FILING_STATUS_FILED)
    assert_field_null(untouched_filing, "reviewed_by_user_id")
    assert_field_null(untouched_filing, "review_note")
    assert_field_equals(
        read_producer(client, producer["id"]),
        "agreement_status",
        AGREEMENT_STATUS_APPOINTED,
    )
    _rows, meta = validate_paginated(
        client.list_member_insurers(regulator_headers(), {"limit": 10})
    )
    assert_field_equals(meta, "total_count", 0)
    _filings, filing_meta = validate_paginated(
        client.list_cat_zone_rate_filings(zone["id"], regulator_headers(), {"limit": 10})
    )
    assert_field_equals(filing_meta, "total_count", 1)


def test_missing_or_unknown_identity_headers_return_unauthenticated(client):
    """An undeclared role and an absent user id both fail at the first rung.

    PRD: "Every request must carry two headers: `X-User-ID`, identifying the
    acting user, and `X-User-Role`, naming the capacity in which they act. If
    either header is absent, or if `X-User-Role` is not one of the eight declared
    roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    PRD: "The eight declared roles are `PlanAdmin`, `Producer`, `Underwriter`,
    `Inspector`, `RateAnalyst`, `Regulator`, `MemberInsurerUser`, and
    `Policyholder`."

    PRD: "**Authentication.** Both headers present and `X-User-Role` a declared
    role, or `ERR_UNAUTHENTICATED` (401)."

    Design: Corner/rbac/missing_or_unknown_identity_headers_return_unauthenticated
    """
    undeclared_role = {
        "X-User-ID": "pa-1",
        "X-User-Role": "PlanAdministrator",
        "Content-Type": "application/json",
    }
    no_user_id = {"X-User-Role": ROLE_PLAN_ADMIN, "Content-Type": "application/json"}

    undeclared_attempt = client.create_cat_zone(
        f.cat_zone_payload(exposure_cap_cents=900_000_000), undeclared_role
    )
    anonymous_read = client.get_member_insurer(NON_EXISTENT_UUID, no_user_id)

    validate_error(undeclared_attempt, ERR_UNAUTHENTICATED)
    validate_error(anonymous_read, ERR_UNAUTHENTICATED)
    _rows, meta = validate_paginated(
        client.list_member_insurers(admin_headers(), {"limit": 10})
    )
    assert_field_equals(meta, "total_count", 0)

    accepted = validate_success(
        client.create_cat_zone(
            f.cat_zone_payload(exposure_cap_cents=900_000_000), admin_headers()
        ),
        201,
    )
    assert_field_equals(accepted, "code", "HUR-01")
    assert_field_equals(accepted, "status", ZONE_STATUS_OPEN)


def test_producer_acting_on_another_producers_application_is_not_resource_owner(client):
    """A second appointed producer is refused on a file they do not own.

    PRD: "A producer therefore acts only on applications whose `producer_id`
    equals `X-User-ID`, and only on improvement requirements reachable from those
    applications."

    PRD: "When an entity-backed role passes role authorization but the ownership
    comparison fails, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP
    403). This ownership gate guards seven operations: submitting an application,
    recording a declination on an application, submitting remediation evidence
    for an improvement requirement, creating a take-out offer against a policy,
    electing on a take-out offer, withdrawing a take-out offer, and paying an
    assessment allocation."

    PRD: "Its `application_id` comes from the application being documented, and
    only the producer who owns that application may record it."

    Design: Corner/rbac/producer_acting_on_another_producers_application_is_not_resource_owner
    """
    pin_clock(client, CLOCK_BASE)
    member = create_member_insurer(client)
    zone = create_zone(client, exposure_cap_cents=900_000_000)
    owner = create_appointed_producer(client)
    rival = create_appointed_producer(
        client,
        full_name="Rex Rival",
        license_number="P-2002",
        commission_tier=COMMISSION_TIER_PREFERRED,
    )
    foundations = Foundations(client=client, members=[member], zone=zone, producer=owner)
    chain = create_draft_application(client, foundations)
    rival_headers = make_producer_headers(rival["id"])

    declination_attempt = client.create_declination(
        chain.application_id,
        f.declination_payload(member["id"], evidence_reference="DEC-X1"),
        rival_headers,
    )
    submission_attempt = client.submit_application(
        chain.application_id, {}, rival_headers
    )

    validate_error(declination_attempt, ERR_NOT_RESOURCE_OWNER)
    validate_error(submission_attempt, ERR_NOT_RESOURCE_OWNER)
    application = read_application(client, chain.application_id)
    assert_field_equals(application, "producer_id", owner["id"])
    assert_field_equals(application, "status", APP_STATUS_DRAFT)
    assert_field_equals(application, "declination_count", 0)
    assert_field_null(application, "submitted_at")
    _rows, meta = validate_paginated(
        client.list_application_declinations(
            chain.application_id, admin_headers(), {"limit": 10}
        )
    )
    assert_field_equals(meta, "total_count", 0)


def test_rate_filing_reviewed_by_its_own_filer_is_rejected(client):
    """One person cannot file and then approve; a different regulator can.

    PRD: "The regulator reviewing a rate filing must have an `X-User-ID`
    different from that filing's `filed_by_user_id`."

    PRD: "Three separations are enforced, and every one of them is keyed on
    `X-User-ID` rather than on `X-User-Role` — two different people holding the
    same role satisfy the rule, while one person switching roles does not evade
    it."

    PRD: "A `Regulator` reviews a filing by supplying a `decision` of either
    `APPROVE` or `DISAPPROVE` together with an optional `note`, which is stored
    as `review_note`; the reviewer's `X-User-ID` is stored as
    `reviewed_by_user_id`."

    Design: Corner/rbac/rate_filing_reviewed_by_its_own_filer_is_rejected
    """
    pin_clock(client, CLOCK_BASE)
    zone = create_zone(client, exposure_cap_cents=900_000_000)
    filing = validate_success(
        client.create_rate_filing(
            f.rate_filing_payload(
                cat_zone_id=zone["id"], expected_zone_version=zone["version"]
            ),
            make_rate_analyst_headers("dual-hatted-1"),
        ),
        201,
    )

    self_review = client.review_rate_filing(
        filing["id"],
        f.filing_review_payload(decision=DECISION_APPROVE, note="self review"),
        make_regulator_headers("dual-hatted-1"),
    )

    validate_error(self_review, ERR_SEGREGATION_OF_DUTIES)
    unreviewed = read_filing(client, filing["id"])
    assert_field_equals(unreviewed, "status", FILING_STATUS_FILED)
    assert_field_null(unreviewed, "reviewed_by_user_id")
    assert_field_null(unreviewed, "review_note")

    independent = client.review_rate_filing(
        filing["id"],
        f.filing_review_payload(decision=DECISION_APPROVE, note="independent review"),
        second_regulator_headers(),
    )

    approved = validate_success(independent, 200)
    assert_field_equals(approved, "status", FILING_STATUS_APPROVED)
    assert_field_equals(approved, "reviewed_by_user_id", "reg-2")
    assert_field_equals(approved, "filed_by_user_id", "dual-hatted-1")


def test_waiver_by_the_raising_inspector_and_bind_by_the_eligibility_reviewer_are_rejected(
    roomy_foundations,
):
    """Two more incompatible-actor pairs on one file, each cleared by a second person.

    PRD: "The underwriter waiving an improvement requirement must have an
    `X-User-ID` different from the `inspector_user_id` recorded on the parent
    inspection."

    PRD: "The underwriter binding a policy must have an `X-User-ID` different
    from the `eligibility_reviewer_user_id` recorded on the application being
    bound."

    PRD: "Waiver writes `waiver_reason` and `cleared_at` and increments the
    requirement's `version`; on the second hop it decrements the parent
    inspection's `open_requirement_count` by one but pointedly does **not** touch
    `cleared_major_count`, since a waiver earns no improvement credit; and on the
    third hop, when the open count reaches zero, the same terminal cascade to
    `PASS` and `APPROVED_TO_BIND` fires exactly as it does on clearance."

    PRD: "Multiply four percent by the chosen inspection's `cleared_major_count`;
    if the result exceeds eight percent, use eight percent instead — so clearing
    two or more major requirements reaches the cap."

    Design: Corner/rbac/waiver_by_the_raising_inspector_and_bind_by_the_eligibility_reviewer_are_rejected
    """
    client = roomy_foundations.client
    chain = build_inspection_pending_application(client, roomy_foundations)
    complete_inspection(
        chain,
        observed_condition_score=88,
        result=INSPECTION_RESULT_PASS_WITH_CONDITIONS,
        requirements=[
            f.requirement_spec(code=REQUIREMENT_CODE_ELECTRICAL, severity=SEVERITY_MINOR)
        ],
    )
    requirement = chain.requirements[0]

    inspector_waiver = client.waive_requirement(
        requirement["id"],
        {"reason": "alarms observed on site"},
        make_underwriter_headers("insp-1"),
    )

    validate_error(inspector_waiver, ERR_SEGREGATION_OF_DUTIES)
    assert_field_equals(
        read_requirements(client, chain.inspection_id)[0],
        "status",
        REQUIREMENT_STATUS_OPEN,
    )

    underwriter_waiver = client.waive_requirement(
        requirement["id"],
        {"reason": "alarms accepted by underwriting"},
        binder_headers(),
    )

    waived = validate_success(underwriter_waiver, 200)
    assert_field_equals(waived, "status", REQUIREMENT_STATUS_WAIVED)
    inspection = read_inspection(client, chain.inspection_id)
    assert_field_equals(inspection, "open_requirement_count", 0)
    assert_field_equals(inspection, "cleared_major_count", 0)
    assert_field_equals(inspection, "result", INSPECTION_RESULT_PASS)
    assert_field_equals(
        read_application(client, chain.application_id),
        "status",
        APP_STATUS_APPROVED_TO_BIND,
    )

    reviewer_bind = client.bind_policy(
        f.bind_payload(chain.application_id, CLOCK_BASE_DATE), reviewer_headers()
    )

    validate_error(reviewer_bind, ERR_SEGREGATION_OF_DUTIES)
    assert_field_equals(
        read_application(client, chain.application_id),
        "status",
        APP_STATUS_APPROVED_TO_BIND,
    )

    binder_bind = client.bind_policy(
        f.bind_payload(chain.application_id, CLOCK_BASE_DATE), binder_headers()
    )

    policy = validate_success(binder_bind, 201)
    assert_field_equals(policy, "condition_score_at_bind", 88)
    assert_cents(policy["base_premium_cents"], 607_500, "base_premium_cents")
    assert_cents(policy["annual_premium_cents"], 546_750, "annual_premium_cents")
    assert_cents(
        policy["commission_credited_cents"], 54_675, "commission_credited_cents"
    )
    assert_field_equals(
        read_application(client, chain.application_id),
        "eligibility_reviewer_user_id",
        "uw-1",
    )
