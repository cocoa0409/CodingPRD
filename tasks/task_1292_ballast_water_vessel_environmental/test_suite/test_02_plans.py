"""Ballast water management plan lifecycle, supersession, uniqueness, and OCC."""
import pytest

from test_helpers import (
    ApiErrorId,
    approve_plan,
    assert_plan,
    create_plan,
    create_vessel,
    get_success_data,
    get_vessel_version,
    set_clock,
    setup_vessel_with_approved_plan,
    submit_plan,
    validate_error,
    validate_success,
)
from test_helpers import api_client


class TestPlanLifecycle:
    def test_plan_withdraw_from_submitted_succeeds(self, api, shore_officer_headers):
        """PRD section 3.1: "A plan in `DRAFT` or `SUBMITTED` may be withdrawn by a
        `ShoreComplianceOfficer`, moving it to `WITHDRAWN`; both `SUPERSEDED` and
        `WITHDRAWN` are terminal."

        Design: Corner/state_machines/plan_withdraw_from_submitted_succeeds
        """
        vessel = create_vessel(imo_number="9100019", vessel_name="MV Jackdaw")
        plan = create_plan(vessel["id"], plan_revision=1)
        submit_plan(vessel["id"], plan["id"])

        resp = api.withdraw_plan(vessel["id"], plan["id"], shore_officer_headers)
        data = validate_success(resp, 200)
        assert_plan(data)
        assert data["status"] == "WITHDRAWN"

    def test_plan_withdraw_from_approved_returns_409(self, api, shore_officer_headers,
                                                     flag_surveyor_headers):
        """PRD section 3.1: "A plan in `DRAFT` or `SUBMITTED` may be withdrawn by a
        `ShoreComplianceOfficer`, moving it to `WITHDRAWN`; both `SUPERSEDED` and
        `WITHDRAWN` are terminal."
        PRD section 2.5: "An attempt to invoke a state transition that the target
        entity's current state does not permit is rejected with `ERR_INVALID_STATE`
        (HTTP 409)"

        Design: Corner/state_machines/plan_withdraw_from_approved_returns_409
        """
        vessel, plan = setup_vessel_with_approved_plan(
            imo_number="9100020", vessel_name="MV Kittiwake"
        )
        resp = api.withdraw_plan(vessel["id"], plan["id"], shore_officer_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        current = get_success_data(api.get_plan(vessel["id"], plan["id"], flag_surveyor_headers))
        assert current["status"] == "APPROVED", "rejected withdraw must leave the plan APPROVED"

    def test_plan_approve_from_draft_returns_409(self, api, flag_surveyor_headers):
        """PRD section 3.1: "Approval by a `FlagSurveyor` moves a `SUBMITTED` plan to
        `APPROVED`"
        PRD section 2.5: "An attempt to invoke a state transition that the target
        entity's current state does not permit is rejected with `ERR_INVALID_STATE`
        (HTTP 409)"

        Design: Corner/state_machines/plan_approve_from_draft_returns_409
        """
        vessel = create_vessel(imo_number="9100021", vessel_name="MV Lapwing")
        plan = create_plan(vessel["id"], plan_revision=1)
        resp = api.approve_plan(vessel["id"], plan["id"], flag_surveyor_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_plan_submit_twice_returns_409(self, api, shore_officer_headers):
        """PRD section 3.1: "Submission by a `ShoreComplianceOfficer` moves the plan
        from `DRAFT` to `SUBMITTED`"
        PRD section 2.5: "An attempt to invoke a state transition that the target
        entity's current state does not permit is rejected with `ERR_INVALID_STATE`
        (HTTP 409)"

        Design: Corner/state_machines/plan_submit_twice_returns_409
        """
        vessel = create_vessel(imo_number="9100022", vessel_name="MV Magpie")
        plan = create_plan(vessel["id"], plan_revision=1)
        submit_plan(vessel["id"], plan["id"])

        resp = api.submit_plan(vessel["id"], plan["id"], shore_officer_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestPlanSupersession:
    def test_plan_supersede_on_higher_revision_approval(self, api, shore_officer_headers,
                                                        flag_surveyor_headers):
        """PRD section 3.1: "Approval supersedes any prior `APPROVED` plan, which
        transitions to `SUPERSEDED`; the newly approved plan becomes the governing
        plan for compliance determination; the vessel's `version` increments by 1; and
        a compliance determination is recomputed for every non-terminal voyage of the
        vessel with trigger reason `PLAN_AMENDMENT`."

        Design: Corner/state_machines/plan_supersede_on_higher_revision_approval
        """
        from test_helpers import (
            create_voyage, depart_voyage, list_determinations,
        )

        vessel, plan1 = setup_vessel_with_approved_plan(
            imo_number="9100018", vessel_name="MV Indigo"
        )
        voyage = create_voyage(vessel["id"], voyage_number="V9302")
        depart_voyage(vessel["id"], voyage["id"])

        plan2 = create_plan(vessel["id"], plan_revision=2,
                            approved_at="2026-07-01T00:00:00Z")
        submit_plan(vessel["id"], plan2["id"])

        resp = api.approve_plan(vessel["id"], plan2["id"], flag_surveyor_headers)
        data = validate_success(resp, 200)
        assert data["status"] == "APPROVED"

        plans = get_success_data(api.list_plans(vessel["id"], flag_surveyor_headers))
        prior = [p for p in plans if p["id"] == plan1["id"]][0]
        assert prior["status"] == "SUPERSEDED", (
            f"prior APPROVED plan must be superseded, got {prior['status']}"
        )

        determinations = list_determinations(vessel["id"], voyage["id"])
        latest = determinations[0]
        assert latest["trigger_reason"] == "PLAN_AMENDMENT"
        assert latest["is_current"] is True


class TestPlanUniquenessConstraints:
    def test_plan_revision_regression_returns_422(self, api, shore_officer_headers):
        """PRD section 3.1: "The plan carries `plan_revision` (an integer at least 1
        that must be strictly greater than every existing revision for the same
        vessel; a regression is rejected with `ERR_PLAN_REVISION_REGRESSION`),
        `approval_authority` (either `USCG` or `CLASS_SOCIETY_ON_BEHALF`),
        `approved_at`, `exchange_distance_nm` (greater than 0; at least 200 for
        open-ocean exchange), and `sediment_management_included`."

        Design: Corner/validations/plan_revision_regression_returns_422
        """
        vessel = create_vessel(imo_number="9100041", vessel_name="MV Kestrel-II")
        create_plan(vessel["id"], plan_revision=1)

        resp = api.create_plan(
            vessel["id"],
            {
                "plan_revision": 1,
                "approval_authority": "CLASS_SOCIETY_ON_BEHALF",
                "approved_at": "2025-03-01T00:00:00Z",
                "exchange_distance_nm": 250,
                "sediment_management_included": False,
                "expected_vessel_version": get_vessel_version(vessel["id"]),
            },
            shore_officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_PLAN_REVISION_REGRESSION)

    def test_multiple_approved_plans_lower_revision_returns_409(self, api, shore_officer_headers,
                                                                flag_surveyor_headers):
        """PRD section 3.1: "Approval by a `FlagSurveyor` moves a `SUBMITTED` plan to
        `APPROVED` — but only if no other plan for the same vessel is already
        `APPROVED` with a higher `plan_revision`, and only if approving would not
        leave two plans `APPROVED` at once (a violation is rejected with
        `ERR_MULTIPLE_APPROVED_PLANS`, HTTP 409)."

        Design: Corner/validations/multiple_approved_plans_lower_revision_returns_409
        """
        vessel = create_vessel(imo_number="9100050", vessel_name="MV Waxwing")
        plan1 = create_plan(vessel["id"], plan_revision=1)
        submit_plan(vessel["id"], plan1["id"])
        plan2 = create_plan(vessel["id"], plan_revision=2,
                            approved_at="2026-07-01T00:00:00Z")
        submit_plan(vessel["id"], plan2["id"])
        approve_plan(vessel["id"], plan2["id"])

        resp = api.approve_plan(vessel["id"], plan1["id"], flag_surveyor_headers)
        validate_error(resp, ApiErrorId.ERR_MULTIPLE_APPROVED_PLANS)

        plans = get_success_data(api.list_plans(vessel["id"], flag_surveyor_headers))
        by_id = {p["id"]: p for p in plans}
        assert by_id[plan1["id"]]["status"] == "SUBMITTED"
        assert by_id[plan2["id"]]["status"] == "APPROVED"


class TestPlanOptimisticConcurrency:
    def test_occ_plan_create_stale_version_returns_412(self, api, shore_officer_headers,
                                                       flag_surveyor_headers):
        """PRD section 2.7: "Creating a new plan revision requires
        `expected_vessel_version` matching the target vessel's current `version`."
        PRD section 2.7: "In each case, if the supplied value does not match the
        parent entity's current `version` — because another writer has advanced that
        version since the client last read it — the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_plan_create_stale_version_returns_412
        """
        set_clock()
        resp = api.create_vessel(
            {
                "imo_number": "9100064", "vessel_name": "MV Osprey-II",
                "bwms_type": "TREATMENT_USCG_TYPE_APPROVED",
                "bwms_installation_date": "2025-01-15T00:00:00Z",
                "gross_tonnage": 40000, "keel_laid_date": "2010-10-01T00:00:00Z",
                "ballast_capacity_m3": 30000,
            },
            shore_officer_headers,
        )
        vessel = validate_success(resp, 201)
        observed_version = vessel["version"]

        # First create advances the vessel's version past the observed value.
        create_plan(vessel["id"], plan_revision=1,
                    expected_vessel_version=observed_version)

        stale = api.create_plan(
            vessel["id"],
            {
                "plan_revision": 2,
                "approval_authority": "USCG",
                "approved_at": "2026-07-01T00:00:00Z",
                "exchange_distance_nm": 220,
                "sediment_management_included": True,
                "expected_vessel_version": observed_version,
            },
            shore_officer_headers,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        plans = get_success_data(api.list_plans(vessel["id"], flag_surveyor_headers))
        assert len(plans) == 1, "stale plan create must not be persisted"

    def test_occ_plan_create_current_version_increments_vessel(self, api, shore_officer_headers):
        """PRD section 3.1: "Because plan creation is an OCC-guarded write, the
        request must carry `expected_vessel_version` matching the vessel's current
        `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).
        Creating the plan increments the vessel's `version` by 1."

        Design: Corner/cross_cutting_layers/occ_plan_create_current_version_increments_vessel
        """
        vessel = create_vessel(imo_number="9100065", vessel_name="MV Phalarope")
        assert vessel["version"] == 1

        plan = create_plan(vessel["id"], plan_revision=1,
                           expected_vessel_version=vessel["version"])
        assert_plan(plan)
        assert plan["status"] == "DRAFT"

        from test_helpers import get_vessel
        after = get_vessel(vessel["id"])
        assert after["version"] == 2, (
            f"exactly one vessel version increment expected, got {after['version']}"
        )
