"""The mission authorization gate: pilot credentials, spray licensing, plan
entitlement, airspace containment, and the scheduling-conflict scan
(PRD sections 2.10, 2.11, and 3.3)."""
from test_helpers import (
    ADMIN,
    FC,
    ApiErrorId,
    api_client,
    assert_mission,
    authorize,
    create_authorization,
    create_mission,
    create_mission_authorized,
    create_mission_captured,
    make_agronomist_headers,
    setup_ops,
    validate_error,
    validate_success,
)


class TestSprayCredentialGate:

    def test_spray_authorize_rejects_pilot_without_applicator_license(self):
        """PRD section 3.3: "for a `SPRAY` mission the pilot must additionally
        hold a non-empty applicator license whose
        `applicator_license_expires_on` also reaches the landing date, and the
        `chemical_product_label` must be non-empty — any failure here is
        `ERR_PILOT_CERT_EXPIRED`."

        Design: Difficulty/cross_entity_state_dependency/spray_mission_authorize_depends_on_pilot_applicator_license
        """
        ctx = setup_ops(plan_overrides={"spray_allowed": True})
        mission = create_mission(
            ctx["field"]["id"], ctx["pilot"]["id"],
            mission_type="SPRAY", chemical_product_label="EPA-REG-123",
            acres_planned=50)
        resp = api_client.authorize_mission(mission["id"], FC)
        validate_error(resp, ApiErrorId.ERR_PILOT_CERT_EXPIRED)

    def test_spray_authorize_rejects_expired_applicator_license(self):
        """PRD section 3.3: "for a `SPRAY` mission the pilot must additionally
        hold a non-empty applicator license whose
        `applicator_license_expires_on` also reaches the landing date, and the
        `chemical_product_label` must be non-empty — any failure here is
        `ERR_PILOT_CERT_EXPIRED`."

        Design: Difficulty/cross_entity_state_dependency/spray_mission_authorize_depends_on_pilot_applicator_license
        """
        ctx = setup_ops(
            plan_overrides={"spray_allowed": True},
            pilot_overrides={
                "applicator_license_no": "APP-OLD",
                # License expires before the 2026-06-02 landing date.
                "applicator_license_expires_on": "2026-01-01",
            })
        mission = create_mission(
            ctx["field"]["id"], ctx["pilot"]["id"],
            mission_type="SPRAY", chemical_product_label="EPA-REG-123",
            acres_planned=50)
        resp = api_client.authorize_mission(mission["id"], FC)
        validate_error(resp, ApiErrorId.ERR_PILOT_CERT_EXPIRED)

    def test_spray_plan_forbidden_blocks_spray_authorize(self):
        """PRD section 3.3: "Then plan entitlement: a `SPRAY` mission under a
        plan whose `spray_allowed` is false dies as
        `ERR_SPRAY_PLAN_FORBIDDEN`."

        Design: Corner/validations/spray_plan_forbidden_blocks_spray_authorize
        """
        ctx = setup_ops(
            plan_overrides={"spray_allowed": False},
            pilot_overrides={
                "applicator_license_no": "APP-1",
                "applicator_license_expires_on": "2027-01-01",
            })
        mission = create_mission(
            ctx["field"]["id"], ctx["pilot"]["id"],
            mission_type="SPRAY", chemical_product_label="EPA-1",
            acres_planned=10)
        resp = api_client.authorize_mission(mission["id"], FC)
        validate_error(resp, ApiErrorId.ERR_SPRAY_PLAN_FORBIDDEN)


class TestAirspaceGate:

    def test_auth_not_permitted_on_uncontrolled_airspace(self):
        """PRD section 3.3: "when the field does not require LAANC, any
        supplied `authorization_id` is itself a violation,
        `ERR_AUTH_NOT_PERMITTED`."

        Design: Corner/errors/error_auth_not_permitted_on_uncontrolled_airspace
        """
        ctx = setup_ops()
        field_g = ctx["field"]  # airspace_class G -> laanc_required false
        resp = api_client.create_field(
            ctx["grower"]["id"],
            {"field_name": "Controlled", "legal_acres": 100,
             "airspace_class": "B", "insurance_policy_no": "POL-ANP2"},
            ADMIN)
        field_b = validate_success(resp, expected_status=201)
        auth = create_authorization(field_b["id"])
        mission = create_mission(
            field_g["id"], ctx["pilot"]["id"],
            authorization_id=auth["id"], acres_planned=10)
        resp = api_client.authorize_mission(mission["id"], FC)
        validate_error(resp, ApiErrorId.ERR_AUTH_NOT_PERMITTED)

    def test_authorize_rejects_landing_exactly_at_effective_until(self):
        """PRD section 2.10: "the mission's planned landing falls strictly
        before the authorization's end instant; a landing scheduled at the
        exact expiry instant is rejected."

        Design: Difficulty/resource_temporal_overlap/authorization_window_strict_end_containment
        """
        ctx = setup_ops(field_overrides={"airspace_class": "C"})
        auth = create_authorization(
            ctx["field"]["id"],
            effective_from="2026-06-02T08:00:00Z",
            effective_until="2026-06-02T11:00:00Z")
        mission = create_mission(
            ctx["field"]["id"], ctx["pilot"]["id"],
            authorization_id=auth["id"],
            scheduled_start="2026-06-02T09:00:00Z",
            scheduled_end="2026-06-02T11:00:00Z",  # == effective_until: strict
            acres_planned=50)
        resp = api_client.authorize_mission(mission["id"], FC)
        validate_error(resp, ApiErrorId.ERR_AUTH_WINDOW_INSUFFICIENT)

    def test_authorize_accepts_inclusive_start_and_strictly_early_landing(self):
        """PRD section 2.10: "an authorization that becomes effective at the
        exact takeoff instant is valid — and the mission's planned landing
        falls strictly before the authorization's end instant".

        Design: Difficulty/resource_temporal_overlap/authorization_window_strict_end_containment
        """
        ctx = setup_ops(field_overrides={"airspace_class": "C"})
        auth = create_authorization(
            ctx["field"]["id"],
            effective_from="2026-06-02T08:00:00Z",
            effective_until="2026-06-02T11:00:00Z")
        mission = create_mission(
            ctx["field"]["id"], ctx["pilot"]["id"],
            authorization_id=auth["id"],
            scheduled_start="2026-06-02T08:00:00Z",   # == effective_from: valid
            scheduled_end="2026-06-02T10:59:59Z",     # strictly before until
            acres_planned=50)
        authorized = authorize(mission["id"])
        assert authorized["status"] == "AUTHORIZED"


class TestAuthorizationStateDependency:

    def test_revoke_cancels_referencing_planned_mission(self):
        """PRD section 3.2: "An `OpsAdmin` may revoke it — permitted only while
        it is `ACTIVE`, else `ERR_AUTH_NOT_ACTIVE` — moving it to `REVOKED`
        and, in the same stroke, cancelling every `PLANNED` or `AUTHORIZED`
        mission that references it."

        Design: Difficulty/cross_entity_state_dependency/mission_authorize_depends_on_authorization_state
        """
        ctx = setup_ops(field_overrides={"airspace_class": "D"})
        auth = create_authorization(
            ctx["field"]["id"],
            effective_from="2026-06-02T08:00:00Z",
            effective_until="2026-06-02T11:00:00Z")
        mission = create_mission(
            ctx["field"]["id"], ctx["pilot"]["id"],
            authorization_id=auth["id"],
            scheduled_start="2026-06-02T08:30:00Z",
            scheduled_end="2026-06-02T10:30:00Z",
            acres_planned=50)
        resp = api_client.revoke_authorization(auth["id"], ADMIN)
        revoked = validate_success(resp, expected_status=200)
        assert revoked["status"] == "REVOKED"
        after = validate_success(api_client.get_mission(mission["id"], FC))
        assert after["status"] == "CANCELLED", \
            f"revoking the authorization must cancel the referencing PLANNED " \
            f"mission, got {after['status']}"

    def test_authorize_after_revoke_fails_mission_not_planned(self):
        """PRD section 3.3: "State preconditions come first: the mission must
        be `PLANNED` (else `ERR_MISSION_NOT_PLANNED`)".
        PRD section 3.2: "An `OpsAdmin` may revoke it — permitted only while
        it is `ACTIVE`, else `ERR_AUTH_NOT_ACTIVE` — moving it to `REVOKED`
        and, in the same stroke, cancelling every `PLANNED` or `AUTHORIZED`
        mission that references it."

        Design: Difficulty/cross_entity_state_dependency/mission_authorize_depends_on_authorization_state
        """
        ctx = setup_ops(field_overrides={"airspace_class": "D"})
        auth = create_authorization(
            ctx["field"]["id"],
            effective_from="2026-06-02T08:00:00Z",
            effective_until="2026-06-02T11:00:00Z")
        mission = create_mission(
            ctx["field"]["id"], ctx["pilot"]["id"],
            authorization_id=auth["id"],
            scheduled_start="2026-06-02T08:30:00Z",
            scheduled_end="2026-06-02T10:30:00Z",
            acres_planned=50)
        validate_success(api_client.revoke_authorization(auth["id"], ADMIN))
        resp = api_client.authorize_mission(mission["id"], FC)
        validate_error(resp, ApiErrorId.ERR_MISSION_NOT_PLANNED)


class TestSchedulingConflictScan:

    def test_authorize_rejects_buffered_window_overlap(self):
        """PRD section 2.11: "Two missions on the same field conflict when
        both are non-terminal — anything other than `COMPLETED`, `CANCELLED`,
        or `WEATHER_ABORTED` — and their buffered windows intersect."
        PRD section 2.11: "a detected conflict is rejected with
        `ERR_MISSION_WINDOW_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/mission_window_buffered_overlap
        """
        ctx = setup_ops(field_overrides={"legal_acres": 500})
        create_mission_authorized(
            ctx["field"]["id"], ctx["pilot"]["id"],
            scheduled_start="2026-06-02T08:00:00Z",
            scheduled_end="2026-06-02T10:00:00Z", acres_planned=100)
        # Raw gap of 15 minutes after the first mission ends; the 30-minute
        # padded windows ([07:30,10:30) vs [09:45,12:30)) intersect.
        mission2 = create_mission(
            ctx["field"]["id"], ctx["pilot"]["id"],
            scheduled_start="2026-06-02T10:15:00Z",
            scheduled_end="2026-06-02T12:00:00Z", acres_planned=100)
        resp = api_client.authorize_mission(mission2["id"], FC)
        validate_error(resp, ApiErrorId.ERR_MISSION_WINDOW_CONFLICT)

    def test_authorize_permits_exactly_back_to_back_padded_windows(self):
        """PRD section 2.11: "Missions whose buffered windows are exactly
        back-to-back, where one mission's padded end equals the other's padded
        start with zero gap, are permitted."

        Design: Difficulty/resource_temporal_overlap/mission_window_buffered_overlap
        """
        ctx = setup_ops(field_overrides={"legal_acres": 500})
        create_mission_authorized(
            ctx["field"]["id"], ctx["pilot"]["id"],
            scheduled_start="2026-06-02T08:00:00Z",
            scheduled_end="2026-06-02T10:00:00Z", acres_planned=100)
        # Padded windows [07:30,10:30) and [10:30,13:00) are back-to-back.
        mission2 = create_mission(
            ctx["field"]["id"], ctx["pilot"]["id"],
            scheduled_start="2026-06-02T11:00:00Z",
            scheduled_end="2026-06-02T12:30:00Z", acres_planned=100)
        authorized = authorize(mission2["id"])
        assert authorized["status"] == "AUTHORIZED"


class TestAuthorizationStateGateOrdering:

    def test_authorize_captured_mission_reports_state_error(self):
        """PRD section 3.3: "State preconditions come first: the mission must
        be `PLANNED` (else `ERR_MISSION_NOT_PLANNED`)".
        PRD section 2.6: "Only after all four of those gates come the business
        rules, in their own fixed priority sequence: pilot certificate and
        applicator-license currency (`ERR_PILOT_CERT_EXPIRED`)".

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_authorize
        """
        ctx = setup_ops()
        mission = create_mission_captured(
            ctx["field"]["id"], ctx["pilot"]["id"], acres_flown=50,
            acres_planned=50)
        assert mission["status"] == "CAPTURED"
        resp = api_client.authorize_mission(mission["id"], FC)
        # State gate (fourth in the pipeline) runs before any business-safety
        # check, so the state error must surface.
        validate_error(resp, ApiErrorId.ERR_MISSION_NOT_PLANNED)

    def test_authorize_authorized_mission_reports_state_error(self):
        """PRD section 3.3: "State preconditions come first: the mission must
        be `PLANNED` (else `ERR_MISSION_NOT_PLANNED`)".

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_authorize
        """
        ctx = setup_ops()
        mission = create_mission_authorized(
            ctx["field"]["id"], ctx["pilot"]["id"], acres_planned=50)
        resp = api_client.authorize_mission(mission["id"], FC)
        validate_error(resp, ApiErrorId.ERR_MISSION_NOT_PLANNED)


class TestAuthorizationRoleGate:

    def test_agronomist_cannot_authorize_mission(self):
        """PRD section 2.1: "a role attempting an operation outside its grant
        is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD section 4: POST /ag-drone/missions/{id}/authorize is authorized
        for FlightCoordinator only.

        Design: Corner/roles/agronomist_cannot_authorize_mission
        """
        ctx = setup_ops()
        mission = create_mission(
            ctx["field"]["id"], ctx["pilot"]["id"], acres_planned=10)
        resp = api_client.authorize_mission(
            mission["id"], make_agronomist_headers(ctx["pilot"]["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
