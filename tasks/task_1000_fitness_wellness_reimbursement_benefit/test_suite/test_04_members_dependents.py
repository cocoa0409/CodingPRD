"""Members, dependents, termination cascade, and enrollment period overlap."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_plan,
    create_dependent_payload,
    create_employer,
    create_member,
    create_member_payload,
    create_enrollment,
    create_enrollment_payload,
    get_success_data,
    make_member_headers,
    set_clock,
    standard_world,
    submit_claim,
    tier_payload,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["benefits_admin_headers"]


def test_member_eligibility_pending_then_auto_flip(api, admin_headers):
    """PRD §3.2: "The member's `eligibility_status` starts at `PENDING`,
    unless the logical clock has already passed the derived `eligibility_date`
    at creation time, in which case the member starts `ELIGIBLE` immediately."
    PRD §2.5: "First, any member whose derived `eligibility_date` has been
    reached flips automatically from `PENDING` to `ELIGIBLE`, with the usual
    `version` increment."

    Design: Corner/entities/member_eligibility_pending_then_auto_flip
    """
    employer = create_employer()
    plan = create_active_plan(employer["id"])
    member = get_success_data(api.create_member(
        create_member_payload(employer["id"], plan["id"], hire_date="2026-04-15T00:00:00Z"), ADMIN,
    ))
    # eligibility_date = hire 2026-04-15 + 30 days = 2026-05-15 > clock 2026-05-01.
    assert member["eligibility_status"] == "PENDING", (
        f"member hired 2026-04-15 under clock 2026-05-01 must start PENDING, got {member['eligibility_status']}"
    )

    set_clock("2026-05-16T00:00:00Z")
    after = get_success_data(api.get_member(member["id"], admin_headers))
    assert after["eligibility_status"] == "ELIGIBLE", (
        f"clock past eligibility_date 2026-05-15 must auto-flip to ELIGIBLE, got {after['eligibility_status']}"
    )


def test_member_create_id_input_ignored(api):
    """PRD §2.4: "`id` (string): a unique, server-minted identifier formatted
    as a UUID, with no type prefix."
    PRD §2.4: "`version` (integer): a system-managed counter that increments
    with every mutation, including system-driven mutations such as cascade
    steps and automatic state transitions."

    Design: Corner/entities/member_create_id_input_ignored
    """
    employer = create_employer()
    plan = create_active_plan(employer["id"])
    payload = create_member_payload(employer["id"], plan["id"], external_ref="E3")
    payload["id"] = "11111111-1111-4111-8111-111111111111"
    payload["version"] = 99
    member = get_success_data(api.create_member(payload, ADMIN))
    assert member["id"] != "11111111-1111-4111-8111-111111111111", "id must be server-minted"
    assert member["version"] == 1, f"client-supplied version 99 must be ignored, got {member['version']}"


def test_member_reinstate_terminated_rejected(api):
    """PRD §3.2: "once `TERMINATED`, all member-scoped operations are refused
    with `ERR_MEMBER_TERMINATED`."

    Design: Corner/state_machines/member_reinstate_terminated_rejected
    """
    employer = create_employer()
    plan = create_active_plan(employer["id"])
    member = create_member(employer["id"], plan["id"])
    validate_success(api.terminate_member(member["id"], ADMIN))
    resp = api.reinstate_member(member["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_MEMBER_TERMINATED)


def test_dependent_deactivate_twice_rejected(api):
    """PRD §3.2: "Deactivation moves `ACTIVE → INACTIVE` and is open to both
    `BenefitsAdmin` and the owning `Member`; deactivating an already-inactive
    dependent fails with `ERR_DEPENDENT_INACTIVE`."

    Design: Corner/state_machines/dependent_deactivate_twice_rejected
    """
    employer = create_employer()
    plan = create_active_plan(employer["id"])
    member = create_member(employer["id"], plan["id"])
    dependent = get_success_data(api.add_dependent(member["id"], create_dependent_payload(), ADMIN))
    validate_success(api.deactivate_dependent(dependent["id"], ADMIN))
    resp = api.deactivate_dependent(dependent["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_DEPENDENT_INACTIVE)


class TestDependentChildAge26Boundary:
    def test_child_age_25_at_period_start_accepted(self, api):
        """PRD §3.2: "A `CHILD` dependent must be younger than 26 at the
        plan's `period_start`; a child who has already reached their
        twenty-sixth birthday by that date is refused with
        `ERR_DEPENDENT_AGE_INELIGIBLE`."

        Design: Difficulty/boundary_precision_check/dependent_child_age_26_boundary
        """
        employer = create_employer()
        plan = create_active_plan(employer["id"])  # period_start 2026-01-01
        member = create_member(employer["id"], plan["id"])
        # Born 2000-01-02: 26th birthday is 2026-01-02, after period_start -> age 25.
        resp = api.add_dependent(member["id"], create_dependent_payload(
            full_name="Kid Young", relationship="CHILD", birth_date="2000-01-02T00:00:00Z",
        ), ADMIN)
        data = validate_success(resp, expected_status=201)
        assert data["relationship"] == "CHILD"
        assert data["status"] == "ACTIVE"

    def test_child_exactly_26_at_period_start_rejected(self, api):
        """PRD §3.2: "A `CHILD` dependent must be younger than 26 at the
        plan's `period_start`; a child who has already reached their
        twenty-sixth birthday by that date is refused with
        `ERR_DEPENDENT_AGE_INELIGIBLE`."

        Design: Difficulty/boundary_precision_check/dependent_child_age_26_boundary
        """
        employer = create_employer()
        plan = create_active_plan(employer["id"])  # period_start 2026-01-01
        member = create_member(employer["id"], plan["id"])
        # Born 2000-01-01: 26th birthday is exactly period_start 2026-01-01 -> ineligible.
        resp = api.add_dependent(member["id"], create_dependent_payload(
            full_name="Kid Old", relationship="CHILD", birth_date="2000-01-01T00:00:00Z",
        ), ADMIN)
        validate_error(resp, ApiErrorId.ERR_DEPENDENT_AGE_INELIGIBLE)


def test_family_allowance_reconciles_with_dependents(api, admin_headers):
    """PRD §3.4: "For the `FAMILY` tier only, the base grows by the dependent
    uplift: count the member's `ACTIVE` dependents, cap that count at three,
    multiply the base by one plus the capped count times `dependent_cap_pct`,
    and round half up to a whole cent."
    PRD §3.4: "This figure is recomputed whenever a dependent is added to or
    deactivated from the parent member."

    Design: Corner/calculations/family_allowance_reconciles_with_dependents
    """
    employer = create_employer()
    plan = create_active_plan(employer["id"], tiers=[tier_payload(
        tier_code="FAMILY", annual_allowance_cents=60000, quarterly_cap_cents=20000,
        per_claim_cap_cents=8000,
    )], name="2026 Family")
    member = create_member(employer["id"], plan["id"], tier_code="FAMILY", full_name="Fam One")
    enrollment = create_enrollment(member["id"], plan["id"])
    assert enrollment["annual_allowance_cents"] == 60000

    d1 = get_success_data(api.add_dependent(member["id"], create_dependent_payload(
        full_name="Spouse One", relationship="SPOUSE", birth_date="1990-06-01T00:00:00Z"), ADMIN))
    after1 = get_success_data(api.get_enrollment(enrollment["id"], admin_headers))
    assert after1["annual_allowance_cents"] == 75000, f"60000 * 1.25 = 75000, got {after1['annual_allowance_cents']}"

    get_success_data(api.add_dependent(member["id"], create_dependent_payload(
        full_name="Kid One", relationship="CHILD", birth_date="2010-06-01T00:00:00Z"), ADMIN))
    after2 = get_success_data(api.get_enrollment(enrollment["id"], admin_headers))
    assert after2["annual_allowance_cents"] == 90000, f"60000 * 1.50 = 90000, got {after2['annual_allowance_cents']}"

    validate_success(api.deactivate_dependent(d1["id"], ADMIN))
    after3 = get_success_data(api.get_enrollment(enrollment["id"], admin_headers))
    assert after3["annual_allowance_cents"] == 75000, (
        f"deactivation must recompute back to 75000 with no drift, got {after3['annual_allowance_cents']}"
    )


class TestMemberTerminateCascade:
    def test_terminate_closes_enrollment(self, api, admin_headers):
        """PRD §3.2: "When a member is terminated, every dependent of theirs
        still `ACTIVE` flips to `INACTIVE`; every enrollment in `ACTIVE` or
        `EXHAUSTED` flips to `CLOSED`, regardless of open claims; each closing
        enrollment rejects its claims still in `SUBMITTED`, `UNDER_REVIEW`, or
        `NEEDS_INFO`; and each auto-rejected claim hands back its enrollment
        reservation"

        Design: Difficulty/transitive_cascade/member_terminate_cascade
        """
        world = standard_world()
        submit_claim(world, 1000, "R-C")
        validate_success(api.terminate_member(world["member"]["id"], ADMIN))

        member_after = get_success_data(api.get_member(world["member"]["id"], admin_headers))
        assert member_after["eligibility_status"] == "TERMINATED"
        enrollment_after = get_success_data(api.get_enrollment(world["enrollment"]["id"], admin_headers))
        assert enrollment_after["status"] == "CLOSED", (
            f"termination must close the ACTIVE enrollment, got {enrollment_after['status']}"
        )

    def test_terminate_rejects_open_claim_and_releases_reservation(self, api, admin_headers):
        """PRD §3.2: "each closing enrollment rejects its claims still in
        `SUBMITTED`, `UNDER_REVIEW`, or `NEEDS_INFO`; and each auto-rejected
        claim hands back its enrollment reservation — the `claimed_amount_cents`
        for a claim that never reached approval, or the `approved_amount_cents`
        for one that was `APPROVED` and still `UNPAID` — and releases any
        funding hold placed for it."

        Design: Difficulty/transitive_cascade/member_terminate_cascade
        """
        world = standard_world()
        claim = submit_claim(world, 1000, "R-C")
        validate_success(api.terminate_member(world["member"]["id"], ADMIN))

        claim_after = get_success_data(api.get_claim(claim["id"], admin_headers))
        assert claim_after["review_status"] == "REJECTED", (
            f"open claim must be cascade-rejected, got {claim_after['review_status']}"
        )
        enrollment_after = get_success_data(api.get_enrollment(world["enrollment"]["id"], admin_headers))
        assert enrollment_after["reserved_cents"] == 0, (
            f"reservation must be handed back, reserved={enrollment_after['reserved_cents']}"
        )


def test_member_cannot_read_other_member(api):
    """PRD §2.1: "When `X-User-Role` is `Member`, `X-User-ID` is the `id` of
    the acting `Member`; ownership checks on any resource that references a
    member compare the resource's `member_id` field to `X-User-ID`, and a
    member caller may only touch resources whose `member_id` equals it."
    PRD §2.1: "A caller whose role is permitted but who reaches for a resource
    owned by someone else is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403)."

    Design: Corner/rbac/member_cannot_read_other_member
    """
    employer = create_employer()
    plan = create_active_plan(employer["id"])
    member_a = create_member(employer["id"], plan["id"], external_ref="EA", full_name="Mem A")
    member_b = create_member(employer["id"], plan["id"], external_ref="EB", full_name="Mem B")
    resp = api.get_member(member_b["id"], make_member_headers(member_a["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)


class TestEnrollmentClosedIntervalOverlap:
    """Plans: A 2026-01-01..2026-06-30, B 2026-07-01..2026-12-31,
    C 2026-06-30..2026-12-31."""

    def _setup(self, api):
        employer = create_employer()
        plan_a = create_active_plan(employer["id"], name="H1",
                                    period_start="2026-01-01T00:00:00Z", period_end="2026-06-30T23:59:59Z")
        plan_b = create_active_plan(employer["id"], name="H2",
                                    period_start="2026-07-01T00:00:00Z", period_end="2026-12-31T23:59:59Z")
        plan_c = create_active_plan(employer["id"], name="Overlap",
                                    period_start="2026-06-30T00:00:00Z", period_end="2026-12-31T23:59:59Z")
        member = create_member(employer["id"], plan_a["id"])
        create_enrollment(member["id"], plan_a["id"])
        return member, plan_b, plan_c

    def test_back_to_back_periods_allowed(self, api):
        """PRD §3.4: "A member's enrollments must have pairwise disjoint plan
        periods under closed-interval semantics — two periods sharing even a
        single calendar date already overlap — and a clashing enrollment is
        rejected with `ERR_ENROLLMENT_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/enrollment_closed_interval_overlap
        """
        member, plan_b, _ = self._setup(api)
        resp = api.create_enrollment(create_enrollment_payload(member["id"], plan_b["id"]), ADMIN)
        data = validate_success(resp, expected_status=201)
        assert data["plan_id"] == plan_b["id"], (
            "2026-07-01 start is strictly after 2026-06-30 end, so no shared date"
        )

    def test_shared_single_date_rejected(self, api):
        """PRD §3.4: "A member's enrollments must have pairwise disjoint plan
        periods under closed-interval semantics — two periods sharing even a
        single calendar date already overlap — and a clashing enrollment is
        rejected with `ERR_ENROLLMENT_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/enrollment_closed_interval_overlap
        """
        member, _, plan_c = self._setup(api)
        resp = api.create_enrollment(create_enrollment_payload(member["id"], plan_c["id"]), ADMIN)
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_PERIOD_OVERLAP)
