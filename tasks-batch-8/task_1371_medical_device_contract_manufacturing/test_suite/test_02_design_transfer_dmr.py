"""Design transfer: DMR creation, approval segregation, revision chain, obsolete."""
from test_helpers import (
    ApiErrorId,
    QE_ALICE,
    approve_dmr,
    assert_dmr,
    create_approved_dmr,
    create_dmr_draft,
    create_dmr_revision,
    create_study,
    create_validated_stack,
    create_lot,
    add_component,
    get_lot,
    make_quality_manager_headers,
    qe,
    qm,
    validate_error,
    validate_success,
    api_client,
)


class TestDmrCreateValidation:
    def test_dmr_create_missing_required_returns_400(self, api):
        """PRD section 3.1: "A `QualityEngineer` opens design transfer by creating
        the first revision of a Device Master Record, supplying a `device_code`
        for the device family, a `revision_code` label such as \"A\", a `sterile`
        flag indicating whether the device is supplied sterile, and a strictly
        positive `shelf_life_claim_months`." and PRD section 2.10 step 3:
        "Required fields are present ... (`ERR_VALIDATION`)".

        Design: Corner/entities/dmr_create_missing_required_returns_400
        """
        from test_helpers import validate_paginated

        resp = api.create_dmr(
            {"device_code": "DEV-M1", "revision_code": "A", "sterile": True}, qe()
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
        page, meta = validate_paginated(api.list_dmrs(qe(), params={"device_code": "DEV-M1"}))
        assert page == [], "nothing may be created when a required field is missing"


class TestDmrApproveSegregation:
    def test_author_cannot_approve_own_dmr(self, api):
        """PRD section 2.6: "The operator approving a Device Master Record
        revision must not be its `author_user_id`." — violation is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

        Design: Corner/state_machines/dmr_approve_segregation_of_duties
        """
        dmr = create_dmr_draft(device_code="DEV-AS", author=QE_ALICE)
        resp = api.approve_dmr(dmr["id"], make_quality_manager_headers(QE_ALICE))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        current = validate_success(api.get_dmr(dmr["id"], qm()))
        assert current["status"] == "DRAFT"
        approved = approve_dmr(dmr["id"])
        assert approved["status"] == "APPROVED"

    def test_second_approve_by_author_reports_segregation_not_state(self, api):
        """PRD section 2.10: "Every request passes a fixed twelve-step validation
        pipeline, and a failure at any step masks all later checks — the caller
        sees the earliest applicable error, never a later one" with step
        "6. **Segregation of duties.**" ahead of step "7. **State-machine
        shape.**"

        Design: Difficulty/priority_pair_validation_conflict/sod_vs_state_on_dmr_approve
        """
        dmr = create_dmr_draft(device_code="DEV-R", author=QE_ALICE)
        approve_dmr(dmr["id"])
        resp = api.approve_dmr(dmr["id"], make_quality_manager_headers(QE_ALICE))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        current = validate_success(api.get_dmr(dmr["id"], qm()))
        assert current["status"] == "APPROVED"

    def test_second_approve_by_other_manager_reports_state(self, api):
        """PRD section 3.1: "Approval is the preserve of a `QualityManager`,
        applies only from `DRAFT` (anything else is `ERR_INVALID_STATE_TRANSITION`)"
        — without a segregation violation the state failure surfaces.

        Design: Difficulty/priority_pair_validation_conflict/sod_vs_state_on_dmr_approve
        """
        dmr = create_dmr_draft(device_code="DEV-R", author=QE_ALICE)
        approve_dmr(dmr["id"])
        resp = api.approve_dmr(dmr["id"], qm())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        current = validate_success(api.get_dmr(dmr["id"], qm()))
        assert current["status"] == "APPROVED"


class TestDmrRevisionChain:
    def test_revision_supersede_invalidates_in_progress_study(self, api):
        """PRD section 3.1: "The successor inherits the parent's `device_code`,
        takes the caller-supplied `revision_code`, `shelf_life_claim_months`, and
        `sterile`, receives `revision_seq` one greater than its parent's, records
        the parent revision in `parent_dmr_id`, and starts in `DRAFT`." and "any
        other revision of the same `device_code` that is currently `APPROVED` —
        including revisions reachable through the `parent_dmr_id` chain —
        transitions to `SUPERSEDED`, and every sterile-barrier study of each such
        superseded revision that is still `IN_PROGRESS` transitions to
        `INVALIDATED`."

        Design: Corner/entities/dmr_revision_supersede_invalidates_study
        """
        dmr_a = create_approved_dmr(device_code="DEV-RV")
        study = create_study(dmr_a["id"], study_type="REAL_TIME", claimed_months=20)

        dmr_b = create_dmr_revision(
            dmr_a, revision_code="B", shelf_life_claim_months=30, sterile=True
        )
        assert dmr_b["revision_seq"] == dmr_a["revision_seq"] + 1
        assert dmr_b["parent_dmr_id"] == dmr_a["id"]
        assert dmr_b["status"] == "DRAFT"

        approve_dmr(dmr_b["id"])
        reloaded_a = validate_success(api.get_dmr(dmr_a["id"], qm()))
        assert reloaded_a["status"] == "SUPERSEDED"
        reloaded_study = validate_success(api.get_study(study["id"], qm()))
        assert reloaded_study["status"] == "INVALIDATED"


class TestDmrObsoleteGuards:
    def test_obsolete_blocked_by_inflight_lot(self, api):
        """PRD section 3.1: "A `QualityManager` is refused with
        `ERR_LOTS_IN_FLIGHT` while any lot references the revision with
        disposition `IN_PRODUCTION` or `COMPLETED`" — and a `VALIDATED` protocol
        is not in the in-flight list ("`DRAFT`, `IQ_EXECUTION`, `IQ_REVIEW`,
        `OQ_EXECUTION`, `OQ_REVIEW`, `PQ_EXECUTION`, or `PQ_REVIEW`").

        Design: Corner/state_machines/dmr_obsolete_blocked_by_inflight_lot
        """
        stack = create_validated_stack("DEV-OB")
        qs_resp = create_lot("LT-OB", stack["dmr"]["id"], stack["protocol"]["id"])
        resp = api.obsolete_dmr(stack["dmr"]["id"], qm())
        validate_error(resp, ApiErrorId.ERR_LOTS_IN_FLIGHT)
        validate_success(api.scrap_lot(qs_resp["id"], qe()))
        obsoleted = validate_success(api.obsolete_dmr(stack["dmr"]["id"], qm()))
        assert obsoleted["status"] == "OBSOLETE"

    def test_obsolete_blocked_by_inflight_protocol(self, api):
        """PRD section 3.1: "and with `ERR_PROTOCOLS_IN_FLIGHT` while any
        validation protocol references it in `DRAFT`, `IQ_EXECUTION`, `IQ_REVIEW`,
        `OQ_EXECUTION`, `OQ_REVIEW`, `PQ_EXECUTION`, or `PQ_REVIEW`."

        Design: Corner/state_machines/dmr_obsolete_blocked_by_inflight_protocol
        """
        from test_helpers import create_line, create_protocol

        line = create_line("L-OP")
        dmr = create_approved_dmr(device_code="DEV-OP")
        create_protocol("VP-OP", dmr["id"], line["id"])
        resp = api.obsolete_dmr(dmr["id"], qm())
        validate_error(resp, ApiErrorId.ERR_PROTOCOLS_IN_FLIGHT)
        current = validate_success(api.get_dmr(dmr["id"], qm()))
        assert current["status"] == "APPROVED"
