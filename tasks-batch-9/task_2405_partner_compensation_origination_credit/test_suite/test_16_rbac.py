"""Role admission, actor resolution, ownership and ballot confidentiality: what
each of the five roles may and may not do, and how the identity in `X-User-ID`
is resolved for the three entity-backed roles."""

from test_helpers import (
    ApiErrorId,
    UNKNOWN_UUID,
    advance_cycle,
    advance_cycle_payload,
    approx2,
    create_assessment,
    create_contribution_record_payload,
    create_cycle,
    create_cycle_payload,
    create_matter,
    create_matter_payload,
    create_non_billable_record,
    create_partner,
    create_partner_payload,
    create_verified_non_billable_hours,
    make_audit_observer_headers,
    make_committee_member_headers,
    make_credit_arbiter_headers,
    make_cycle_admin_headers,
    make_partner_headers,
    matter_status_payload,
    read_assessment,
    read_matter,
    read_partner,
    setup_deliberation_cycle,
    submit_assessment,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_partner_cannot_perform_cycle_admin_exclusive_operations(api):
    """PRD 2.1: "A value of `X-User-Role` that is not one of those five, or that
    is one of them but is not authorised for the endpoint being called, is
    rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)." PRD 2.11: "When a single
    request violates more than one rule, the response is determined by the rule
    that sits highest on the following ladder."

    Design: Corner/rbac/a_partner_cannot_perform_cycle_admin_exclusive_operations
    """
    cycle = create_cycle(api)
    partner = create_partner(api, full_name="Ada Origin")
    record = create_verified_non_billable_hours(
        api, partner_id=partner["id"], cycle_id=cycle["id"], category="FIRM_MANAGEMENT", hours=40.00
    )
    actor = make_partner_headers(partner["id"])

    validate_error(
        api.create_cycle(create_cycle_payload(fiscal_year=2026), actor),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        403,
    )
    validate_error(
        api.verify_contribution_record(record["id"], {}, actor),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        403,
    )
    validate_error(
        api.advance_cycle(cycle["id"], advance_cycle_payload("SELF_ASSESSMENT"), actor),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        403,
    )
    validate_error(
        api.create_partner(create_partner_payload(full_name="Nel Newcomer"), actor),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        403,
    )

    rows, meta = validate_paginated(api.list_cycles(make_cycle_admin_headers()))
    assert meta["total_count"] == 1
    assert rows[0]["state"] == "OPEN_INTAKE"


def test_audit_observer_reads_everything_except_ballots_and_writes_nothing(api):
    """PRD 2.1: "`AuditObserver` holds no write operation of any kind; it is a
    read-only oversight role for a firm auditor or outside counsel, and it may
    never read a committee ballot under any cycle state." PRD 2.12: "Only
    `CycleAdmin` and `CommitteeMember` may read a ballot at all; the three other
    roles are simply not authorised for the ballot reads and are turned away at
    rung 2 of the ladder, which is why an `AuditObserver` can never see a ballot
    no matter what state its cycle is in."

    Design: Corner/rbac/audit_observer_reads_everything_except_ballots_and_writes_nothing
    """
    create_cycle(api)
    partner = create_partner(api, full_name="Ada Origin")
    matter = create_matter(api, billing_attorney_id=partner["id"])
    observer = make_audit_observer_headers()

    read = validate_success(api.get_matter(matter["id"], observer))
    assert read["state"] == "OPEN"
    assert read["id"] == matter["id"]
    awards, meta = validate_paginated(api.list_awards(observer))
    assert awards == []
    assert meta["total_count"] == 0

    validate_error(
        api.list_ballots(observer), ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403
    )
    validate_error(
        api.get_ballot(UNKNOWN_UUID, observer), ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403
    )
    validate_error(
        api.create_partner(create_partner_payload(full_name="Nel Newcomer"), observer),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        403,
    )
    validate_error(
        api.set_matter_status(matter["id"], matter_status_payload("CLOSED"), observer),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        403,
    )

    assert read_matter(api, matter["id"])["state"] == "OPEN"


def test_a_committee_member_may_read_only_their_own_ballots(api):
    """PRD 2.12: "Within that admission, a `CommitteeMember` may read only ballots
    whose `committee_member_id` equals their own `X-User-ID`, and when listing
    ballots must scope the list to their own `committee_member_id`." "A read that
    breaches either restriction is rejected with `ERR_BALLOT_CONFIDENTIAL` (HTTP
    403)."

    Design: Corner/rbac/a_committee_member_may_read_only_their_own_ballots
    """
    scenario = setup_deliberation_cycle(api)
    cycle_id = scenario["cycle"]["id"]
    first, second = scenario["committee"]
    own_ballot, other_ballot = scenario["ballots"]

    rows, meta = validate_paginated(
        api.list_ballots(
            make_committee_member_headers(first["id"]),
            {"cycle_id": cycle_id, "committee_member_id": first["id"]},
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == own_ballot["id"]
    assert rows[0]["committee_member_id"] == first["id"]

    validate_error(
        api.list_ballots(
            make_committee_member_headers(first["id"]),
            {"cycle_id": cycle_id, "committee_member_id": second["id"]},
        ),
        ApiErrorId.ERR_BALLOT_CONFIDENTIAL.value,
        403,
    )
    validate_error(
        api.get_ballot(other_ballot["id"], make_committee_member_headers(first["id"])),
        ApiErrorId.ERR_BALLOT_CONFIDENTIAL.value,
        403,
    )

    admin_read = validate_success(
        api.get_ballot(other_ballot["id"], make_cycle_admin_headers())
    )
    assert admin_read["committee_member_id"] == second["id"]
    assert admin_read["state"] == "PENDING"


def test_cycle_admin_performs_its_exclusive_operations_and_the_shared_reads(api):
    """PRD 2.1: "The server may record or log it, but it never compares it to any
    entity's `id`, and no ownership check applies to it." PRD 4: "Resource
    creation returns 201 Created; every other successful operation, including
    every state transition and every list read, returns 200 OK."

    Design: Corner/rbac/cycle_admin_performs_its_exclusive_operations_and_the_shared_reads
    """
    admin = make_cycle_admin_headers()

    cycle = validate_success(api.create_cycle(create_cycle_payload(), admin), 201)
    partner = validate_success(
        api.create_partner(create_partner_payload(full_name="Ada Origin"), admin), 201
    )
    matter = validate_success(
        api.create_matter(
            create_matter_payload(
                billing_attorney_id=partner["id"], responsible_attorney_id=partner["id"]
            ),
            admin,
        ),
        201,
    )
    record = validate_success(
        api.create_contribution_record(
            create_contribution_record_payload(
                partner_id=partner["id"],
                cycle_id=cycle["id"],
                matter_id=matter["id"],
                hours=5.00,
                standard_rate_cents=40000,
            ),
            admin,
        ),
        201,
    )
    verified = validate_success(api.verify_contribution_record(record["id"], {}, admin), 200)
    assert verified["verified"] is True

    advanced = validate_success(
        api.advance_cycle(cycle["id"], advance_cycle_payload("SELF_ASSESSMENT"), admin), 200
    )
    assert advanced["state"] == "SELF_ASSESSMENT"

    assert read_partner(api, partner["id"])["verified_billable_hours"] == approx2(5.00)
    rows, meta = validate_paginated(api.list_matter_credit_allocations(matter["id"], admin))
    assert meta["total_count"] == 3
    assert rows[0]["credit_role"] == "BILLING"
    assert {row["credit_role"] for row in rows} == {"BILLING", "RESPONSIBLE", "WORKING"}


def test_an_actor_id_that_is_not_an_eligible_partner_row_is_refused(api):
    """PRD 2.1: "For all three of those roles the identifier must resolve to a
    `Partner` row whose `status` is anything other than `DEPARTED`, and the
    role-specific flag must be set; otherwise the request fails with
    `ERR_ACTOR_NOT_A_PARTNER` (HTTP 403)."

    Design: Corner/rbac/an_actor_id_that_is_not_an_eligible_partner_row_is_refused
    """
    cycle = create_cycle(api)
    partner = create_partner(api, full_name="Ada Origin")

    validate_error(
        api.get_cycle(cycle["id"], make_partner_headers(UNKNOWN_UUID)),
        ApiErrorId.ERR_ACTOR_NOT_A_PARTNER.value,
        403,
    )
    validate_error(
        api.list_partners(make_committee_member_headers(partner["id"])),
        ApiErrorId.ERR_ACTOR_NOT_A_PARTNER.value,
        403,
    )
    validate_error(
        api.list_credit_transitions(make_credit_arbiter_headers(partner["id"])),
        ApiErrorId.ERR_ACTOR_NOT_A_PARTNER.value,
        403,
    )

    admitted = validate_success(
        api.get_cycle(cycle["id"], make_partner_headers(partner["id"]))
    )
    assert admitted["state"] == "OPEN_INTAKE"
    assert admitted["id"] == cycle["id"]


def test_a_partner_may_act_only_on_rows_they_own(api):
    """PRD 2.1: "A partner acting on a self-assessment must be that assessment's
    `partner_id`; on a peer review, its `reviewer_partner_id`; on a credit claim
    submission, its `claimant_partner_id`; on a ballot, its
    `committee_member_id`." "Any of these mismatches yields
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/a_partner_may_act_only_on_rows_they_own
    """
    cycle = create_cycle(api)
    owner = create_partner(api, full_name="Ada Origin")
    other = create_partner(api, full_name="Otto Other", practice_group="TAX")
    advance_cycle(api, cycle["id"], "SELF_ASSESSMENT")
    assessment = create_assessment(api, cycle_id=cycle["id"], partner_id=owner["id"])

    validate_error(
        api.submit_self_assessment(assessment["id"], {}, make_partner_headers(other["id"])),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
        403,
    )
    validate_error(
        api.create_contribution_record(
            create_contribution_record_payload(
                partner_id=owner["id"],
                cycle_id=cycle["id"],
                kind="NON_BILLABLE",
                category="FIRM_MANAGEMENT",
                hours=40.00,
                standard_rate_cents=0,
                service_period_start="2026-02-01",
                service_period_end="2026-02-28",
            ),
            make_partner_headers(other["id"]),
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
        403,
    )

    assert read_assessment(api, assessment["id"])["state"] == "DRAFT"

    submitted = submit_assessment(api, assessment["id"], owner["id"])
    assert submitted["state"] == "SUBMITTED"
    assert submitted["partner_id"] == owner["id"]

    own_record = create_non_billable_record(
        api,
        partner_id=owner["id"],
        cycle_id=cycle["id"],
        category="FIRM_MANAGEMENT",
        hours=40.00,
        headers=make_partner_headers(owner["id"]),
    )
    assert own_record["partner_id"] == owner["id"]
    assert own_record["verified"] is False
    assert read_partner(api, owner["id"])["non_billable_points"] == approx2(0.00)
