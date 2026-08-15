"""RBAC, authentication, segregation-of-duties, and enrollment-gating tests."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_actuary_headers,
    make_senior_actuary_headers,
    create_plan,
    register_actuary,
    register_prep_and_review_actuaries,
    create_assumption_set,
    submit_assumption_set,
    create_census_batch,
    create_locked_census,
    create_locked_assumption_set,
    create_asset_statement,
    create_asset_valuation,
    create_valuation_run,
    compute_run,
    get_plan_version,
    setup_certified_plan,
    api_client,
)

PLAN_ADMIN = TEST_USERS["plan_admin_headers"]
FIRM_ADMIN = TEST_USERS["firm_admin_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


class TestAuthentication:
    def test_missing_auth_headers_returns_401(self, api):
        """PRD §2.1: "A request missing either header, or presenting an unrecognized
        role, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_headers_returns_401
        """
        resp = api.list_plans(headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


class TestRoleDenial:
    def test_actuary_cannot_approve_assumption_set(self, api):
        """PRD §3.3: "From `IN_REVIEW`, a `SeniorActuary` either approves or
        rejects." The Actuary role is outside that grant.
        PRD §2.1: "A recognized role attempting an operation outside its grant is
        rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/actuary_cannot_approve_assumption_set
        """
        plan = create_plan(sponsor_name="RBAC Co")
        prep = register_actuary("Prep Act", "EA-1", "ENROLLED")
        aset = create_assumption_set(plan["id"], prep["id"])
        submit_assumption_set(aset["id"], prep["id"])
        resp = api.approve_assumption_set(aset["id"], make_actuary_headers(prep["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)

    def test_plan_admin_cannot_certify_run(self, api):
        """PRD §3.6: "Certification — `COMPUTED` → `CERTIFIED` — is reserved for a
        `SeniorActuary`". PlanAdmin is outside that grant; per §2.1 the call is
        rejected with `ERR_UNAUTHORIZED` (HTTP 403).

        Design: Corner/rbac/plan_admin_cannot_certify_run
        """
        plan = create_plan(sponsor_name="RBAC2 Co", prior_aftap_pct=90.00)
        plan_id = plan["id"]
        prep, rev = register_prep_and_review_actuaries()
        batch = create_locked_census(plan_id, [
            {"external_ref": "R1", "date_of_birth": "1965-01-01", "status": "RETIREE",
             "current_annual_benefit": 1000},
        ])
        aset = create_locked_assumption_set(plan_id, prep["id"], rev["id"])
        create_asset_statement(plan_id)
        ava = create_asset_valuation(plan_id, prep["id"])
        run = create_valuation_run(plan_id, prep["id"], batch["id"], aset["id"], ava["id"])
        compute_run(run["id"], prep["id"])
        plan_v = get_plan_version(plan_id)
        resp = api.certify_valuation_run(
            run["id"], {"expected_plan_version": plan_v}, PLAN_ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)

    def test_auditor_cannot_create_census(self, api):
        """PRD §2.1: "A recognized role attempting an operation outside its grant is
        rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §3.2: "A `PlanAdmin` creates a census batch under a plan" — Auditor is
        read-only plus disclosure acknowledgment.

        Design: Corner/rbac/auditor_cannot_create_census
        """
        plan = create_plan(sponsor_name="RBAC3 Co")
        resp = api.create_census_batch(
            plan["id"], {"plan_year": 2028, "source_label": "c1"}, AUDITOR
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)

    def test_firm_admin_cannot_post_payments(self, api):
        """PRD §2.1: "A recognized role attempting an operation outside its grant is
        rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §3.7: "Cash payments are posted by a `PlanAdmin` against a specific
        demand" — FirmAdmin manages the actuary registry and the clock only.

        Design: Corner/rbac/firm_admin_cannot_post_payments
        """
        fx = setup_certified_plan(
            sponsor_name="RBAC4 Co",
            participant_rows=[
                {"external_ref": "A1", "date_of_birth": "1966-03-10", "status": "ACTIVE",
                 "years_of_service": 10, "annual_compensation": 100000},
            ],
            market_value_begin=14762.00, contributions_received=0,
            benefits_paid=738.10, investment_return=738.10,
            prior_aftap_pct=90.00,
        )
        resp = api.create_contribution_payment(
            fx["demand"]["id"], {"amount": 100.00, "paid_on": "2028-05-01"}, FIRM_ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)


class TestSegregationOfDuties:
    def test_segregation_of_duties_preparer_cannot_approve(self, api):
        """PRD §2.9: "An assumption set may be approved only by an actuary whose id
        differs from the set's `prepared_by_actuary_id` ... either violation is
        rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 422)."

        Design: Corner/rbac/segregation_of_duties_preparer_cannot_approve
        """
        plan = create_plan(sponsor_name="SoD Co")
        same = register_actuary("Same Act", "EA-9", "ENROLLED")
        # Create and submit as SeniorActuary role with the same actuary id
        resp = api.create_assumption_set(
            plan["id"],
            {
                "plan_year": 2028, "label": "base", "mortality_table": "TEST_TABLE_4AGE",
                "funding_discount_rate": 0.05, "disclosure_discount_rate": 0.04,
                "retirement_age": 62,
            },
            make_senior_actuary_headers(same["id"]),
        )
        aset = validate_success(resp, 201)
        api.submit_assumption_set(aset["id"], make_senior_actuary_headers(same["id"]))
        resp = api.approve_assumption_set(aset["id"], make_senior_actuary_headers(same["id"]))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 422)
        fetched = validate_success(api.get_assumption_set(aset["id"], PLAN_ADMIN), 200)
        assert fetched["status"] == "IN_REVIEW"


class TestEnrollmentGate:
    def test_associate_actuary_lock_enrollment_gate(self, api):
        """PRD §2.9: "approving an assumption set, locking an assumption set, and
        certifying a valuation run each require the acting actuary's
        `enrollment_status` to be `ENROLLED`; an `ASSOCIATE` attempting any of the
        three is rejected with `ERR_ACTUARY_NOT_ENROLLED` (HTTP 422)."

        Design: Corner/rbac/associate_actuary_lock_enrollment_gate
        """
        plan = create_plan(sponsor_name="Enroll2 Co")
        prep = register_actuary("Prep Act", "EA-1", "ENROLLED")
        rev = register_actuary("Rev Act", "EA-2", "ENROLLED")
        assoc = register_actuary("Assoc Act", "ASA-7", "ASSOCIATE")
        aset = create_assumption_set(plan["id"], prep["id"])
        submit_assumption_set(aset["id"], prep["id"])
        api.approve_assumption_set(aset["id"], make_senior_actuary_headers(rev["id"]))
        # ASSOCIATE in the SeniorActuary role attempts lock
        resp = api.lock_assumption_set(aset["id"], make_senior_actuary_headers(assoc["id"]))
        validate_error(resp, ApiErrorId.ERR_ACTUARY_NOT_ENROLLED, 422)
        fetched = validate_success(api.get_assumption_set(aset["id"], PLAN_ADMIN), 200)
        assert fetched["status"] == "APPROVED"
