"""Household intake, eligibility, member composition, and service referrals."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_member,
    create_household,
    get_household,
    set_eligibility,
    setup_active_tenancy,
    setup_eligible_household,
    validate_error,
    validate_success,
)


class TestMemberMinorComputation:
    def test_member_is_minor_computed_from_clock(self, api,
                                                 intake_coordinator_headers):
        """PRD §3.3: "The system derives `is_minor` — true when the member is
        under eighteen years of age on the clock date — and recomputes
        `member_count` and `minor_count` on every add, incrementing the
        household's `version`."
        PRD §2.4: "Until that capability is first invoked, the clock reads
        exactly 2026-08-01T00:00:00Z, and the implementation must never fall
        back to wall-clock time."

        Design: Corner/entities/member_is_minor_computed_from_clock
        """
        household = create_household(name="Fam M")
        minor = validate_success(api.create_household_member(
            {"household_id": household["id"], "full_name": "Kid",
             "date_of_birth": "2015-06-01", "relationship": "CHILD"},
            intake_coordinator_headers), expected_status=201)
        boundary = validate_success(api.create_household_member(
            {"household_id": household["id"], "full_name": "Adult",
             "date_of_birth": "2008-08-01", "relationship": "CHILD"},
            intake_coordinator_headers), expected_status=201)
        assert minor["is_minor"] is True, "Age 11 at the default clock"
        assert boundary["is_minor"] is False, (
            "Exactly 18 on the clock date is not under eighteen")

        after = get_household(household["id"])
        assert after["member_count"] == 2
        assert after["minor_count"] == 1


class TestEligibilityGate:
    def test_household_ag_work_default_and_verify_gate(
            self, api, intake_coordinator_headers):
        """PRD §3.3: "`ag_work_verified` may be supplied at intake and defaults
        to false."
        PRD §3.3: "Granting it — `PENDING_ELIGIBILITY → ELIGIBLE` — requires
        `ag_work_verified` to be true, and an unverified grant is refused with
        `ERR_AG_WORK_NOT_VERIFIED` (HTTP 422)."

        Design: Corner/entities/household_ag_work_default_and_verify_gate
        """
        undocumented = validate_success(api.create_household(
            {"head_of_household_name": "NoDoc",
             "annual_family_income_cents": 3000000},
            intake_coordinator_headers), expected_status=201)
        assert undocumented["ag_work_verified"] is False, (
            "Default false applies when the field is omitted")

        denied = api.update_household(
            undocumented["id"], {"eligibility_status": "ELIGIBLE"},
            intake_coordinator_headers)
        validate_error(denied, ApiErrorId.ERR_AG_WORK_NOT_VERIFIED)

        documented = validate_success(api.create_household(
            {"head_of_household_name": "Doc",
             "annual_family_income_cents": 3000000, "ag_work_verified": True},
            intake_coordinator_headers), expected_status=201)
        granted = validate_success(api.update_household(
            documented["id"], {"eligibility_status": "ELIGIBLE"},
            intake_coordinator_headers))
        assert granted["eligibility_status"] == "ELIGIBLE"

    def test_household_reapplication_cycle(self, api,
                                           intake_coordinator_headers):
        """PRD §3.3: "Denying it — `PENDING_ELIGIBILITY → INELIGIBLE` — is
        unconditional, and a household may re-apply with new documentation,
        `INELIGIBLE → PENDING_ELIGIBILITY`."

        Design: Corner/state_machines/household_reapplication_cycle
        """
        household = create_household(name="Fam RC", income_cents=3000000)
        s1 = set_eligibility(household["id"], "INELIGIBLE")
        assert s1["eligibility_status"] == "INELIGIBLE"
        s2 = set_eligibility(household["id"], "PENDING_ELIGIBILITY")
        assert s2["eligibility_status"] == "PENDING_ELIGIBILITY"
        s3 = set_eligibility(household["id"], "ELIGIBLE")
        assert s3["eligibility_status"] == "ELIGIBLE"


class TestServiceReferrals:
    def test_education_referral_requires_minor(self, api,
                                               intake_coordinator_headers):
        """PRD §3.3: "an `EDUCATION` referral requires at least one minor in
        the household — a `minor_count` of zero is rejected with
        `ERR_EDUCATION_REFERRAL_REQUIRES_MINOR` (HTTP 422)."

        Design: Corner/validations/education_referral_requires_minor
        """
        hh = setup_eligible_household(
            name="Fam ED", income_cents=3000000,
            members=(("ED Adult", "1990-01-01", "HEAD"),))["household"]
        assert hh["minor_count"] == 0

        denied = api.create_service_referral(
            {"household_id": hh["id"], "referral_type": "EDUCATION",
             "agency_name": "Migrant Ed"}, intake_coordinator_headers)
        validate_error(denied, ApiErrorId.ERR_EDUCATION_REFERRAL_REQUIRES_MINOR)

        ok = validate_success(api.create_service_referral(
            {"household_id": hh["id"], "referral_type": "HEALTH",
             "agency_name": "Clinic"}, intake_coordinator_headers),
            expected_status=201)
        assert ok["status"] == "INITIATED", (
            "HEALTH referrals carry no minor precondition")

    def test_referral_completed_terminal_lockdown(self, api,
                                                  intake_coordinator_headers):
        """PRD §3.3: "A referral starts `INITIATED` and proceeds `INITIATED →
        ACCEPTED_BY_AGENCY → COMPLETED`; an agency that will not take the case
        ends it `INITIATED → DECLINED`. `COMPLETED` and `DECLINED` are
        terminal."

        Design: Corner/state_machines/referral_completed_terminal_lockdown
        """
        hh = setup_eligible_household(name="Fam RT", income_cents=3000000)[
            "household"]
        referral = validate_success(api.create_service_referral(
            {"household_id": hh["id"], "referral_type": "HEALTH",
             "agency_name": "Clinic"}, intake_coordinator_headers),
            expected_status=201)
        validate_success(api.update_service_referral(
            referral["id"], {"status": "ACCEPTED_BY_AGENCY"},
            intake_coordinator_headers))
        done = validate_success(api.update_service_referral(
            referral["id"], {"status": "COMPLETED"},
            intake_coordinator_headers))
        assert done["status"] == "COMPLETED"

        resp = api.update_service_referral(
            referral["id"], {"status": "DECLINED"}, intake_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestOccupancyRecheckOnMemberAdd:
    def test_occupancy_recheck_on_member_add_when_housed(
            self, api, intake_coordinator_headers):
        """PRD §3.3: "Adding members is not free once the household is housed:
        when the household holds an `ACTIVE` or `NOTICE` tenancy, an add that
        would push the unit past its `max_occupancy` is rejected with
        `ERR_OCCUPANCY_LIMIT_EXCEEDED`."

        Design: Corner/validations/occupancy_recheck_on_member_add_when_housed
        """
        ctx = setup_active_tenancy(
            site_name="Site OM",
            unit_spec={"unit_code": "U1", "unit_type": "SEASONAL_DORM",
                       "max_occupancy": 1, "monthly_rent_cents": 62000},
            household_name="Fam OM",
            members=(("OM One", "1990-01-01", "HEAD"),))
        assert ctx["unit"]["max_occupancy"] == 1

        resp = api.create_household_member(
            {"household_id": ctx["household"]["id"], "full_name": "OM Two",
             "date_of_birth": "1992-01-01", "relationship": "SPOUSE"},
            intake_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_OCCUPANCY_LIMIT_EXCEEDED)
