"""Enrollment workflow: initial state, void lockdown, certification pinning,
submit/approval cross-entity gates, and the AGI boundary (PRD §3.7)."""
import pytest

from test_helpers import (
    AGI_LIMIT_CENTS,
    SAFE_CLOCK,
    ApiErrorId,
    assert_enrollment,
    create_farm_with_member,
    make_county_committee_headers,
    make_producer_headers,
    set_clock,
    setup_certified_enrollment,
    setup_enrollment_pipeline,
    validate_error,
    validate_success,
)


@pytest.fixture
def specialist(county_specialist_headers):
    return county_specialist_headers


@pytest.fixture
def ced(county_executive_director_headers):
    return county_executive_director_headers


class TestEnrollmentLifecycle:
    def test_new_enrollment_initial_state_draft(self, api, specialist):
        """PRD §3.7: "A producer opens an enrollment for a farm by supplying the
        `program_year` and the covered `commodity`; the enrollment starts in
        `DRAFT` under `enrollment_status`, with `pinned_election_id`,
        `pinned_yield_record_id`, `computed_payment_cents`, and
        `sequestration_cents` all null."

        Design: Corner/state_machines/new_enrollment_initial_state_draft
        """
        farm, producer, _ = create_farm_with_member()
        resp = api.create_enrollment(
            farm["id"],
            {"program_year": 2026, "commodity": "CORN"},
            make_producer_headers(producer["id"]),
        )
        enrollment = validate_success(resp, 201)
        assert_enrollment(enrollment)
        assert enrollment["enrollment_status"] == "DRAFT"
        assert enrollment["pinned_election_id"] is None
        assert enrollment["pinned_yield_record_id"] is None
        assert enrollment["computed_payment_cents"] is None
        assert enrollment["sequestration_cents"] is None

    def test_terminal_enrollment_void_lockdown(self, api, specialist):
        """PRD §3.8: "A producer may void an enrollment while it is in `DRAFT` or
        `SUBMITTED`, moving it to `VOID` (terminal)."
        PRD §2.8: "then the state-machine check that the target resource is in a
        state from which the requested transition is defined" — a VOID enrollment
        defines no submit transition, so the attempt surfaces `ERR_INVALID_STATE`
        (HTTP 409, PRD §5).

        Design: Corner/state_machines/terminal_enrollment_void_lockdown
        """
        set_clock(SAFE_CLOCK)
        farm, producer, _ = create_farm_with_member()
        producer_headers = make_producer_headers(producer["id"])
        enrollment = validate_success(
            api.create_enrollment(
                farm["id"], {"program_year": 2026, "commodity": "CORN"}, producer_headers
            ),
            201,
        )
        validate_success(api.void_enrollment(enrollment["id"], producer_headers), 200)
        resp = api.submit_enrollment(enrollment["id"], producer_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_enrollment_certify_pins_election_and_yield(self, api, specialist):
        """PRD §3.7: "Certification sets `pinned_election_id` to the current
        `ACTIVE` election and `pinned_yield_record_id` to the current yield
        record; the pinned election transitions to `LOCKED` and the pinned yield
        record transitions to `LOCKED`. The enrollment is now `CERTIFIED`."

        Design: Corner/state_machines/enrollment_certify_pins_election_and_yield
        """
        ctx = setup_certified_enrollment()
        enrollment = ctx["enrollment"]
        assert enrollment["enrollment_status"] == "CERTIFIED"
        assert enrollment["pinned_election_id"] == ctx["election"]["id"], (
            f"pinned_election_id must be the ACTIVE election {ctx['election']['id']}, "
            f"got {enrollment['pinned_election_id']}"
        )
        assert enrollment["pinned_yield_record_id"] == ctx["yield_record"]["id"], (
            f"pinned_yield_record_id must be the yield record "
            f"{ctx['yield_record']['id']}, got {enrollment['pinned_yield_record_id']}"
        )
        election = validate_success(
            api.get_program_election(ctx["election"]["id"], specialist), 200
        )
        assert election["election_status"] == "LOCKED", (
            f"pinned election must be LOCKED, got {election['election_status']}"
        )
        yield_record = validate_success(
            api.get_yield_record(ctx["yield_record"]["id"], specialist), 200
        )
        assert yield_record["yield_status"] == "LOCKED", (
            f"pinned yield record must be LOCKED, got {yield_record['yield_status']}"
        )


class TestSubmitRequiresCertifiedAcreageReport:
    def test_submit_blocked_when_report_only_filed(self, api, specialist):
        """PRD §3.7: "Submitting the enrollment requires that the producer hold
        an `ACTIVE` membership on the farm, that an `ACTIVE` program election
        exist for the same farm, year, and commodity (otherwise
        `ERR_NO_ACTIVE_ELECTION`), that a yield record exist for the same farm
        and commodity, and that the farm's acreage report for the year be
        `CERTIFIED` (otherwise `ERR_ACREAGE_NOT_CERTIFIED`)."

        Design: Difficulty/cross_entity_state_dependency/enrollment_submit_requires_certified_acreage_report
        """
        ctx = setup_enrollment_pipeline(stop_at="created", certify_report=False)
        assert ctx["acreage_report"]["report_status"] == "FILED"
        resp = api.submit_enrollment(
            ctx["enrollment"]["id"], ctx["producer_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_ACREAGE_NOT_CERTIFIED.value)

    def test_submit_succeeds_once_report_certified(self, api, specialist):
        """PRD §3.7: "Submission moves the enrollment from `DRAFT` to
        `SUBMITTED`." and "the farm's acreage report for the year be `CERTIFIED`
        (otherwise `ERR_ACREAGE_NOT_CERTIFIED`)."

        Design: Difficulty/cross_entity_state_dependency/enrollment_submit_requires_certified_acreage_report
        """
        ctx = setup_enrollment_pipeline(stop_at="submitted", certify_report=True)
        assert ctx["acreage_report"]["report_status"] == "CERTIFIED"
        assert ctx["enrollment"]["enrollment_status"] == "SUBMITTED", (
            f"submit with a CERTIFIED report must succeed, got "
            f"{ctx['enrollment']['enrollment_status']}"
        )


class TestCedApproveGates:
    def test_ced_approve_blocked_when_agi_not_verified(self, api, specialist, ced):
        """PRD §3.7: "The AGI gate requires the producer's
        `agi_attestation_status` to be `VERIFIED` and the attested
        `adjusted_gross_income` to be at most 90000000 cents — the statutory
        $900,000 AGI limit; a failure surfaces `ERR_AGI_INELIGIBLE`."

        Design: Difficulty/cross_entity_state_dependency/enrollment_ced_approve_requires_verified_agi
        """
        ctx = setup_enrollment_pipeline(
            stop_at="submitted", verify_agi_attestation=False
        )
        producer = validate_success(
            api.get_producer(ctx["producer"]["id"], specialist), 200
        )
        assert producer["agi_attestation_status"] == "FILED"
        resp = api.ced_approve_enrollment(ctx["enrollment"]["id"], ced)
        validate_error(resp, ApiErrorId.ERR_AGI_INELIGIBLE.value)

    def test_ced_approve_succeeds_once_agi_verified(self, api, specialist, ced):
        """PRD §3.7: "The AGI gate requires the producer's
        `agi_attestation_status` to be `VERIFIED` and the attested
        `adjusted_gross_income` to be at most 90000000 cents" and "Approval moves
        the enrollment from `SUBMITTED` to `CED_APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/enrollment_ced_approve_requires_verified_agi
        """
        ctx = setup_enrollment_pipeline(stop_at="ced_approved")
        assert ctx["enrollment"]["enrollment_status"] == "CED_APPROVED", (
            f"CED approval with VERIFIED AGI must succeed, got "
            f"{ctx['enrollment']['enrollment_status']}"
        )

    def test_agi_exactly_at_limit_passes(self, api, specialist, ced):
        """PRD §3.7: "The AGI gate requires the producer's
        `agi_attestation_status` to be `VERIFIED` and the attested
        `adjusted_gross_income` to be at most 90000000 cents — the statutory
        $900,000 AGI limit; a failure surfaces `ERR_AGI_INELIGIBLE`."

        AGI == 90000000 is at most the limit, so approval must succeed.

        Design: Difficulty/boundary_precision_check/agi_exactly_at_limit_passes
        """
        ctx = setup_enrollment_pipeline(
            stop_at="ced_approved", agi_cents=AGI_LIMIT_CENTS
        )
        assert ctx["enrollment"]["enrollment_status"] == "CED_APPROVED", (
            f"AGI exactly at 90000000 must pass, got "
            f"{ctx['enrollment']['enrollment_status']}"
        )

    def test_agi_one_cent_over_limit_rejected(self, api, specialist, ced):
        """PRD §3.7: "The AGI gate requires the producer's
        `agi_attestation_status` to be `VERIFIED` and the attested
        `adjusted_gross_income` to be at most 90000000 cents — the statutory
        $900,000 AGI limit; a failure surfaces `ERR_AGI_INELIGIBLE`."

        Design: Difficulty/boundary_precision_check/agi_exactly_at_limit_passes
        """
        ctx = setup_enrollment_pipeline(
            stop_at="submitted", agi_cents=AGI_LIMIT_CENTS + 1
        )
        resp = api.ced_approve_enrollment(ctx["enrollment"]["id"], ced)
        validate_error(resp, ApiErrorId.ERR_AGI_INELIGIBLE.value)

    def test_safety_gate_fires_at_ced_approve_not_at_compute(
        self, api, specialist, ced
    ):
        """PRD §3.7: "CED approval is the compliance gateway."
        PRD §3.7: "The `CountyExecutiveDirector` approves a `SUBMITTED`
        enrollment only when two independent gates both pass, and only when the
        CED is not the submitting producer (segregation of duties,
        `ERR_SEGREGATION_OF_DUTIES`)."
        PRD §3.7: "The AGI gate requires the producer's
        `agi_attestation_status` to be `VERIFIED` and the attested
        `adjusted_gross_income` to be at most 90000000 cents — the statutory
        $900,000 AGI limit; a failure surfaces `ERR_AGI_INELIGIBLE`."

        A producer over the AGI limit is stopped at approval — the safety gate
        fires before any fiscal payment-limitation step can run.

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_fiscal_on_payment
        """
        ctx = setup_enrollment_pipeline(
            stop_at="submitted", agi_cents=99_999_999
        )
        resp = api.ced_approve_enrollment(ctx["enrollment"]["id"], ced)
        validate_error(resp, ApiErrorId.ERR_AGI_INELIGIBLE.value)
        enrollment = validate_success(
            api.get_enrollment(ctx["enrollment"]["id"], specialist), 200
        )
        assert enrollment["enrollment_status"] == "SUBMITTED"
        assert enrollment["computed_payment_cents"] is None, (
            "no fiscal computation may run when approval never happened"
        )

    def test_conservation_violation_safety_gate_blocks_approval(
        self, api, specialist, ced
    ):
        """PRD §3.7: "The conservation gate requires the producer's
        `conservation_status` to be `CERTIFIED` or `EXEMPT`; a failure surfaces
        `ERR_CONSERVATION_NOT_CERTIFIED`."
        PRD §3.2: "A `CountyExecutiveDirector` records a conservation violation
        by supplying a `violation_code`, which moves `conservation_status` to
        `VIOLATION` and flags every non-terminal enrollment on farms where that
        producer holds membership, blocking their payment."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_fiscal_on_payment
        """
        ctx = setup_enrollment_pipeline(stop_at="submitted")
        validate_success(
            api.record_conservation_violation(
                ctx["producer"]["id"], {"violation_code": "HELC"}, ced
            ),
            201,
        )
        resp = api.ced_approve_enrollment(ctx["enrollment"]["id"], ced)
        validate_error(resp, ApiErrorId.ERR_CONSERVATION_NOT_CERTIFIED.value)

    def test_conservation_pending_blocks_ced_approval(self, api, specialist, ced):
        """PRD §3.7: "The conservation gate requires the producer's
        `conservation_status` to be `CERTIFIED` or `EXEMPT`; a failure surfaces
        `ERR_CONSERVATION_NOT_CERTIFIED`."

        Design: Corner/errors/error_conservation_not_certified
        """
        ctx = setup_enrollment_pipeline(
            stop_at="submitted", certify_conservation_status=False
        )
        producer = validate_success(
            api.get_producer(ctx["producer"]["id"], specialist), 200
        )
        assert producer["conservation_status"] == "PENDING"
        resp = api.ced_approve_enrollment(ctx["enrollment"]["id"], ced)
        validate_error(resp, ApiErrorId.ERR_CONSERVATION_NOT_CERTIFIED.value)
