"""Network roster: uniqueness, plan/provider lifecycle gates, participation windows."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_participation_payload, create_auth_rule_payload,
    create_patient_payload, create_specialist_payload, create_insurance_plan_payload,
    create_referral_payload,
    create_plan, create_provider, create_specialist, create_patient,
    create_participation, create_auth_rule, create_referral,
    make_referring_provider_headers,
    assert_participation, assert_referral,
    TEST_USERS,
)

ADMIN = TEST_USERS["network_admin_headers"]
COORD = TEST_USERS["coordinator_headers"]


class TestUniquenessMatrix:
    def test_duplicate_identity_uniqueness_matrix(self, api):
        """PRD §3.2: "Patients are registered by a `NetworkAdmin` with a unique `mrn`
        (duplicates fail with `ERR_DUPLICATE_MRN`)".
        PRD §3.1: "The National Provider Identifier is unique across both provider
        kinds: a second registration of the same `npi` on either a referring provider
        or a specialist fails with `ERR_DUPLICATE_NPI`."
        PRD §3.1: "Insurance plans are registered with a unique `plan_code`
        (duplicates fail with `ERR_DUPLICATE_PLAN_CODE`)".
        PRD §3.1: "At most one `ACTIVE` rule may exist per specialty-and-plan pair;
        creating a second `ACTIVE` row for the same pair fails with
        `ERR_DUPLICATE_AUTH_RULE`."

        Design: Corner/validations/duplicate_identity_uniqueness_matrix
        """
        plan = create_plan()
        provider = create_provider(npi="2000000001")
        create_patient(plan["id"], mrn="M001")
        create_auth_rule("CARDIOLOGY", plan["id"], requires_auth=True, auth_validity_days=10)

        e1 = api.create_patient(
            create_patient_payload(plan["id"], mrn="M001", full_name="Pat Two",
                                   date_of_birth="1990-01-01", region="SOUTH"),
            ADMIN,
        )
        validate_error(e1, ApiErrorId.ERR_DUPLICATE_MRN, expected_status=409)

        e2 = api.create_specialist(
            create_specialist_payload(npi="2000000001"), ADMIN
        )
        validate_error(e2, ApiErrorId.ERR_DUPLICATE_NPI, expected_status=409)

        e3 = api.create_insurance_plan(
            create_insurance_plan_payload(plan_code="PPO-1", payer_name="PayerTwo",
                                          payer_mix_factor=0.9),
            ADMIN,
        )
        validate_error(e3, ApiErrorId.ERR_DUPLICATE_PLAN_CODE, expected_status=409)

        e4 = api.create_auth_rule(
            create_auth_rule_payload("CARDIOLOGY", plan["id"], requires_auth=False,
                                     auth_validity_days=5),
            ADMIN,
        )
        validate_error(e4, ApiErrorId.ERR_DUPLICATE_AUTH_RULE, expected_status=409)


class TestPlanAndProviderLifecycleGates:
    def test_suspended_provider_cannot_create_referral(self, api):
        """PRD §3.1: "a suspended referring provider is blocked from creating new
        referrals with `ERR_PROVIDER_SUSPENDED`."
        PRD §3.1: "a `NetworkAdmin` may suspend a provider, moving it to `SUSPENDED`,
        and later reactivate it back to `ACTIVE`".

        Design: Corner/validations/suspended_provider_cannot_create_referral
        """
        plan = create_plan()
        provider = create_provider()
        validate_success(api.suspend_referring_provider(provider["id"], ADMIN))
        patient = create_patient(plan["id"])

        res = api.create_referral(
            create_referral_payload(patient["id"]),
            make_referring_provider_headers(provider["id"]),
        )
        validate_error(res, ApiErrorId.ERR_PROVIDER_SUSPENDED, expected_status=403)

        validate_success(api.reactivate_referring_provider(provider["id"], ADMIN))
        res2 = api.create_referral(
            create_referral_payload(patient["id"]),
            make_referring_provider_headers(provider["id"]),
        )
        referral = validate_success(res2, 201)
        assert referral["status"] == "PENDING_TRIAGE"

    def test_retired_plan_blocks_new_participation(self, api):
        """PRD §3.1: "A plan begins `ACTIVE`; retiring it flips `status` to `RETIRED`,
        after which creating referrals, participation rows, or prior-auth rules
        against that plan is rejected with `ERR_PLAN_RETIRED` — existing rows are
        unaffected."

        Design: Corner/validations/retired_plan_blocks_new_participation
        """
        plan = create_plan()
        specialist = create_specialist()
        existing = create_participation(
            specialist["id"], plan["id"], tier="PREFERRED",
            effective_from="2026-01-01", effective_to="2026-06-30",
        )
        validate_success(api.retire_insurance_plan(plan["id"], ADMIN))

        res = api.create_participation(
            create_participation_payload(
                specialist["id"], plan["id"], tier="STANDARD",
                effective_from="2026-07-01", effective_to="2026-12-31",
            ),
            ADMIN,
        )
        validate_error(res, ApiErrorId.ERR_PLAN_RETIRED, expected_status=409)

        row = validate_success(api.get_participation(existing["id"], COORD))
        assert row["status"] == "ACTIVE", "Existing participation rows are unaffected by plan retirement"


class TestParticipationWindowOverlap:
    def test_shared_boundary_day_collides(self, api):
        """PRD §3.1: "A new `ACTIVE` participation row may not overlap an existing
        `ACTIVE` row for the same specialist-and-plan pair — overlap is judged with
        inclusive date arithmetic, so two windows that share even a single calendar
        day collide with `ERR_PARTICIPATION_WINDOW_OVERLAP`, while pure adjacency,
        where the next window starts exactly one day after the previous window ends,
        is allowed."

        Design: Difficulty/resource_temporal_overlap/participation_inclusive_date_overlap
        """
        plan = create_plan()
        specialist = create_specialist()
        create_participation(
            specialist["id"], plan["id"], tier="PREFERRED",
            effective_from="2026-01-01", effective_to="2026-06-30",
        )
        res = api.create_participation(
            create_participation_payload(
                specialist["id"], plan["id"], tier="STANDARD",
                effective_from="2026-06-30", effective_to="2026-12-31",
            ),
            ADMIN,
        )
        validate_error(res, ApiErrorId.ERR_PARTICIPATION_WINDOW_OVERLAP, expected_status=409)

    def test_next_day_adjacency_allowed(self, api):
        """PRD §3.1: "pure adjacency, where the next window starts exactly one day
        after the previous window ends, is allowed."

        Design: Difficulty/resource_temporal_overlap/participation_inclusive_date_overlap
        """
        plan = create_plan()
        specialist = create_specialist()
        create_participation(
            specialist["id"], plan["id"], tier="PREFERRED",
            effective_from="2026-01-01", effective_to="2026-06-30",
        )
        res = api.create_participation(
            create_participation_payload(
                specialist["id"], plan["id"], tier="STANDARD",
                effective_from="2026-07-01", effective_to="2026-12-31",
            ),
            ADMIN,
        )
        row = validate_success(res, 201)
        assert_participation(row)
        assert row["status"] == "ACTIVE"
        assert row["effective_from"] == "2026-07-01"
