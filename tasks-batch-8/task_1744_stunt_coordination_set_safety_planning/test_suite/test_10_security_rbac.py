"""Role authorization, performer ownership, and the three structural
segregation-of-duties walls (PRD §2.1, §2.10, §4)."""
from test_helpers import (
    ApiErrorId,
    COORD,
    DEPT_HEAD,
    EXEC,
    INSPECTOR,
    SAFETY,
    build_user_headers,
    create_active_production,
    create_equipment,
    create_inspection_payload,
    create_locked_sequence,
    create_pay_adjustment_payload,
    create_permit_payload,
    create_performer,
    create_production,
    create_qualified_performer,
    create_sequence,
    create_sequence_payload,
    create_draft_assessment,
    create_safety_meeting_payload,
    make_performer_headers,
    validate_error,
    validate_success,
)


class TestForbiddenRoles:
    def test_performer_cannot_create_sequence(self, api):
        """PRD §2.1: "A request whose role is not among the roles authorized for
        the target endpoint (see §4) is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)." and PRD §4: "POST | `/api/stunt-sequences` | Create a stunt
        sequence in `DRAFT` | StuntCoordinator"

        Design: Corner/rbac/rbac_performer_cannot_create_sequence
        """
        prod = create_production(name="P", budget=5000000)
        perf = create_performer(prod["id"], first_name="Kl", last_name="Rb")
        payload = create_sequence_payload(prod["id"], name="Nope")
        resp = api.create_sequence(payload, make_performer_headers(perf["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_department_head_cannot_grant_permit(self, api):
        """PRD §2.1: "A request whose role is not among the roles authorized for
        the target endpoint (see §4) is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)." and PRD §4: "POST | `/api/permits/{id}/grant` | Grant an
        applied permit | ProductionExecutive"

        Design: Corner/rbac/rbac_department_head_cannot_grant_permit_rejected
        """
        prod = create_production(name="P", budget=5000000)
        permit = validate_success(api.create_permit(create_permit_payload(prod["id"]), EXEC), 201)
        resp = api.grant_permit(permit["id"], DEPT_HEAD)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestPerformerOwnership:
    def test_performer_cannot_negotiate_for_another_performer(self, api):
        """PRD §2.1: "When `X-User-Role` is `Performer`, `X-User-ID` is the `id`
        of the acting StuntPerformer; on any write whose payload carries
        `performer_id`, ownership requires that field to equal `X-User-ID`, and
        a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

        Design: Corner/rbac/rbac_performer_ownership_enforced_rejected
        """
        prod = create_production(name="P", budget=10000000)
        seq = create_sequence(prod["id"], name="Own Seq", hazard_class="FIGHT", risk_category="MEDIUM")
        perf1, _ = create_qualified_performer(prod["id"], discipline="FIGHT", first_name="Lm", last_name="P1")
        perf2, _ = create_qualified_performer(prod["id"], discipline="FIGHT", first_name="Mn", last_name="P2")
        # Caller is performer P1 but names performer P2 in the payload.
        payload = create_pay_adjustment_payload(prod["id"], seq["id"], perf2["id"],
                                                base_amount_cents=100000, requested_pct=0.20)
        resp = api.create_pay_adjustment(payload, make_performer_headers(perf1["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)


class TestSegregationOfDuties:
    def test_approver_must_not_be_assessment_author(self, api):
        """PRD §2.10: "The coordinator who authored a risk assessment may not
        approve it: an approval whose `X-User-ID` equals the assessment's
        `assessor_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION`
        (HTTP 403)."

        Design: Corner/rbac/rbac_sod_approve_own_assessment_rejected
        """
        prod = create_production(name="P", budget=10000000)
        seq = create_sequence(prod["id"], name="SoD Seq", hazard_class="FIGHT", risk_category="LOW")
        ra = create_draft_assessment(prod["id"], seq["id"], 2, 2)
        validate_success(api.submit_assessment(ra["id"], COORD))
        # The approver's X-User-ID equals the assessor's ("coord-1").
        resp = api.approve_assessment(ra["id"], build_user_headers("coord-1", "SafetyOfficer"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION)

    def test_signer_must_not_be_sequence_designer(self, api):
        """PRD §2.10: "The coordinator who created a sequence may not decide its
        department signoffs: a signature or refusal whose `X-User-ID` equals the
        sequence's `coordinator_user_id` is rejected the same way."

        Design: Corner/rbac/rbac_sod_signoff_by_coordinator_rejected
        """
        prod = create_active_production(name="P", budget=10000000)
        seq = create_locked_sequence(prod["id"], name="SoD2 Seq", hazard_class="FIGHT", risk_category="LOW")
        mtg = validate_success(
            api.create_safety_meeting(create_safety_meeting_payload(prod["id"], seq["id"]), COORD), 201
        )
        validate_success(api.start_meeting(mtg["id"], SAFETY))
        signoffs = validate_success(api.list_signoffs(SAFETY, params={"meeting_id": mtg["id"]}))
        camera = next(s for s in signoffs if s["department"] == "CAMERA")
        # A DepartmentHead-role call carrying the designer's X-User-ID.
        resp = api.sign_signoff(camera["id"], build_user_headers("coord-1", "DepartmentHead"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION)

    def test_inspector_must_not_be_equipment_registrar(self, api):
        """PRD §2.10: "And the coordinator who registered an equipment item may
        not inspect it: an inspection whose `X-User-ID` equals the item's
        `registered_by_user_id` is rejected the same way."
        PRD §3.5: "`inspected_at` is stamped with the current logical time at
        creation."

        Design: Corner/rbac/rbac_sod_self_inspection_rejected
        """
        # Inspection recording requires posture ACTIVE (PRD §2.7 tier 5), so the
        # production is filed and activated before the inspections.
        prod = create_active_production(name="P", budget=5000000)
        eq = create_equipment(prod["id"], name="Harness", equipment_type="HARNESS", serial_number="HN-1",
                              inspection_interval_hours=48)
        resp = api.create_inspection(
            create_inspection_payload(eq["id"], outcome="PASSED"),
            build_user_headers("coord-1", "EquipmentInspector"),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION)
        insp = validate_success(
            api.create_inspection(create_inspection_payload(eq["id"], outcome="PASSED"), INSPECTOR), 201
        )
        assert insp["inspected_at"], "independent inspector succeeds; inspected_at stamped"
