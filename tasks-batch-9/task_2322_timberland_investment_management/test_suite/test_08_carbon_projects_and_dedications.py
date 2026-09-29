"""Carbon projects: the registration gate on certification and the pending-release invariant."""

from test_helpers import (
    ApiErrorId,
    assert_fund_cash,
    assert_stand_partition,
    assert_tons,
    validate_error,
)
from test_helpers.fixtures import (
    advance_audit,
    advance_carbon_project,
    create_carbon_project,
    dedicate,
    owned_tract,
    raise_finding,
    read_audit,
    read_carbon_project,
    read_dedication,
    read_fund,
    read_property,
    read_stand,
    release_dedication,
    schedule_audit,
    stand_version,
    submit_car,
    verify_close_car,
)
from test_helpers.test_users import make_carbon_developer_headers


def _project_in_validation(api, property_id, stand_id, dedicated_tons=500.00):
    project = create_carbon_project(api, property_id)
    dedication = dedicate(api, project["id"], stand_id, dedicated_tons=dedicated_tons)
    advance_carbon_project(api, project["id"], "SUBMIT_VALIDATION")
    return project, dedication


def _suspend_with_two_majors(api, property_id):
    audit = schedule_audit(api, property_id)
    advance_audit(api, audit["id"], "START_FIELD_WORK")
    first = raise_finding(
        api, audit["id"], severity="MAJOR", finding_code="SFI-4.1", indicator_ref="4.1.2"
    )
    second = raise_finding(
        api, audit["id"], severity="MAJOR", finding_code="SFI-6.3", indicator_ref="6.3.1"
    )
    advance_audit(api, audit["id"], "ISSUE_FINDINGS")
    return audit, [first, second]


class TestRegistrationGatedByCertificationPosture:
    """A registry cannot be entered while the underlying tract is suspended."""

    def test_registration_is_refused_while_the_tract_is_suspended(self, api):
        """The project and its pledge are left exactly where they were.

        PRD: "Registration moves the project from `VALIDATION` to `REGISTERED` and requires both that the property's `certification_posture` not be `SUSPENDED` — otherwise `ERR_CERTIFICATION_SUSPENDED`"

        Design: Difficulty/cross_entity_state_dependency/carbon_registration_gated_by_property_certification_posture
        """
        ctx = owned_tract(api)
        project, dedication = _project_in_validation(api, ctx.property_id, ctx.stand_id)
        _suspend_with_two_majors(api, ctx.property_id)
        assert read_property(api, ctx.property_id)["certification_posture"] == "SUSPENDED"

        response = api.advance_carbon_project(
            project["id"], {"action": "REGISTER"}, make_carbon_developer_headers()
        )
        validate_error(response, ApiErrorId.CERTIFICATION_SUSPENDED.value, 409)

        assert read_carbon_project(api, project["id"])["status"] == "VALIDATION"
        assert read_dedication(api, dedication["id"])["status"] == "PENDING"

    def test_registration_succeeds_once_both_majors_are_verified_and_closed(self, api):
        """Closing the open majors returns the posture to certified and clears the gate.

        PRD: "which is how a suspended tract works its way back to `CONDITIONAL` and eventually to `CERTIFIED`"

        Design: Difficulty/cross_entity_state_dependency/carbon_registration_gated_by_property_certification_posture
        """
        ctx = owned_tract(api)
        project, _ = _project_in_validation(api, ctx.property_id, ctx.stand_id)
        audit, findings = _suspend_with_two_majors(api, ctx.property_id)
        api.advance_carbon_project(
            project["id"], {"action": "REGISTER"}, make_carbon_developer_headers()
        )

        for finding in findings:
            submit_car(api, finding["id"], manager="fm-1")
            verify_close_car(api, finding["id"], auditor="ca-1")

        assert read_property(api, ctx.property_id)["certification_posture"] == "CERTIFIED"
        assert read_audit(api, audit["id"])["open_major_count"] == 0

        registered = advance_carbon_project(api, project["id"], "REGISTER")
        assert registered["status"] == "REGISTERED"

    def test_registration_activates_the_pledge_and_fixes_the_buffer_pool(self, api):
        """The eighteen percent buffer is struck and the dedication is stamped and activated.

        PRD: "It also fixes `buffer_pool_tons` at `dedicated_tons_total` multiplied by eighteen percent, rounded half-up to two decimals — an eighteen percent insurance buffer against future reversal."

        Design: Difficulty/cross_entity_state_dependency/carbon_registration_gated_by_property_certification_posture
        """
        ctx = owned_tract(api)
        project, dedication = _project_in_validation(api, ctx.property_id, ctx.stand_id)
        _, findings = _suspend_with_two_majors(api, ctx.property_id)
        api.advance_carbon_project(
            project["id"], {"action": "REGISTER"}, make_carbon_developer_headers()
        )
        for finding in findings:
            submit_car(api, finding["id"], manager="fm-1")
            verify_close_car(api, finding["id"], auditor="ca-1")

        registered = advance_carbon_project(api, project["id"], "REGISTER")

        assert_tons(registered["buffer_pool_tons"], 90.00, "buffer_pool_tons")
        assert_tons(registered["dedicated_tons_total"], 500.00, "dedicated_tons_total")
        assert_tons(registered["buffer_deficit_tons"], 0.00, "buffer_deficit_tons")

        activated = read_dedication(api, dedication["id"])
        assert activated["status"] == "ACTIVE"
        assert activated["permanence_end_date"] == "2056-08-01"
        assert_stand_partition(
            read_stand(api, ctx.stand_id),
            dedicated_tons=500.00,
            available_tons=4147.12,
        )


class TestPendingDedicationReleaseRestoresTheStand:
    """Releasing an unregistered pledge gives the pool back exactly."""

    def test_releasing_a_pending_dedication_returns_its_tonnage_to_available(self, api):
        """A pledge that never reached the registry releases freely and restores the headroom.

        PRD: "A `PENDING` dedication is not yet permanence-locked and releases freely, provided its parent project is still in `DRAFT` or `VALIDATION`; its tonnage returns to the stand's `available_tons` and the stand's `version` is incremented."

        Design: Difficulty/compensating_invariant/pending_carbon_dedication_release_restores_available_tons
        """
        ctx = owned_tract(api)
        project = create_carbon_project(api, ctx.property_id)
        dedication = dedicate(api, project["id"], ctx.stand_id, dedicated_tons=500.00)
        assert_stand_partition(
            read_stand(api, ctx.stand_id),
            dedicated_tons=500.00,
            available_tons=4147.12,
        )

        released = release_dedication(
            api, dedication["id"], "Project re-scoped before validation."
        )

        assert released["status"] == "RELEASED"
        assert_stand_partition(
            read_stand(api, ctx.stand_id),
            net_merch_tons=4647.12,
            reserved_tons=0.00,
            committed_tons=0.00,
            dedicated_tons=0.00,
            hbu_withdrawn_tons=0.00,
            available_tons=4647.12,
        )

    def test_release_clears_the_project_total_and_leaves_no_permanence_date(self, api):
        """With nothing pledged the project total falls to zero and stays in draft.

        PRD: "In every case the dedication becomes `RELEASED`, which is terminal, the stand's `dedicated_tons` falls by the tonnage returned, and the project's `dedicated_tons_total` is recomputed."

        Design: Difficulty/compensating_invariant/pending_carbon_dedication_release_restores_available_tons
        """
        ctx = owned_tract(api)
        project = create_carbon_project(api, ctx.property_id)
        dedication = dedicate(api, project["id"], ctx.stand_id, dedicated_tons=500.00)

        release_dedication(api, dedication["id"], "Project re-scoped before validation.")

        assert read_dedication(api, dedication["id"])["permanence_end_date"] is None
        after = read_carbon_project(api, project["id"])
        assert_tons(after["dedicated_tons_total"], 0.00, "dedicated_tons_total")
        assert_tons(after["buffer_pool_tons"], 0.00, "buffer_pool_tons")
        assert after["status"] == "DRAFT"
        assert_fund_cash(read_fund(api, ctx.fund_id), cash_balance_usd=300000.00)

    def test_release_advances_the_stand_version_so_an_older_token_is_stale(self, api):
        """The release is a mutation of the stand, so the pre-release token no longer matches.

        PRD: "its tonnage returns to the stand's `available_tons` and the stand's `version` is incremented"

        Design: Difficulty/compensating_invariant/pending_carbon_dedication_release_restores_available_tons
        """
        ctx = owned_tract(api)
        project = create_carbon_project(api, ctx.property_id)
        dedication = dedicate(api, project["id"], ctx.stand_id, dedicated_tons=500.00)
        version_before_release = stand_version(api, ctx.stand_id)

        release_dedication(api, dedication["id"], "Project re-scoped before validation.")

        assert stand_version(api, ctx.stand_id) > version_before_release
