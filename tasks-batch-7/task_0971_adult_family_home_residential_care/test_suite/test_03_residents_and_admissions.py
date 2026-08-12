"""Resident registration, withdrawal, and the admission hold/decision pipeline."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID,
    create_resident_payload, create_admission_payload,
    create_home, add_bed, create_licensed_home, set_clock, fresh_bed,
    fresh_resident, create_applicant, create_pending_admission,
    create_pending_admission_scenario, create_approved_admission_scenario,
    create_and_finalize_assessment, approve_admission, complete_admission,
    TEST_USERS,
)

PROVIDER = TEST_USERS["provider_headers"]
PROVIDER2 = TEST_USERS["provider2_headers"]
NURSE = TEST_USERS["nurse_headers"]


class TestResidentRegistrationValidation:
    def test_missing_payer_type_rejected(self, api):
        """PRD §3.2: "Registration brings a prospective resident into a home with a
        `full_name`, a `date_of_birth` given as an ISO 8601 date, and a `payer_type`
        of `PRIVATE_PAY` or `MEDICAID` — the funding source that later drives
        rate-schedule selection and bed-certification checks."
        PRD §2.9: "Structural payload validity — a missing required field, a wrong
        type, an enum outside its declared set, or an inverted range such as a
        `period_end` not after its `period_start` or an `end_at` not after its
        `start_at`; failure yields `ERR_INVALID_REQUEST`."

        Design: Corner/entities/resident_create_required_fields_and_enum_enforced
        """
        home = create_home(name="Corner Birch", licensed_bed_capacity=4)
        payload = {"full_name": "No Payer", "date_of_birth": "1940-01-01"}
        res = api.create_resident(home["id"], payload, NURSE)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_payer_type_outside_enum_rejected(self, api):
        """PRD §3.2: "Registration brings a prospective resident into a home with a
        `full_name`, a `date_of_birth` given as an ISO 8601 date, and a `payer_type`
        of `PRIVATE_PAY` or `MEDICAID` — the funding source that later drives
        rate-schedule selection and bed-certification checks."
        PRD §2.9: "Structural payload validity — a missing required field, a wrong
        type, an enum outside its declared set, or an inverted range such as a
        `period_end` not after its `period_start` or an `end_at` not after its
        `start_at`; failure yields `ERR_INVALID_REQUEST`."

        Design: Corner/entities/resident_create_required_fields_and_enum_enforced
        """
        home = create_home(name="Corner Birch", licensed_bed_capacity=4)
        payload = {"full_name": "Bad Payer", "date_of_birth": "1940-01-01",
                   "payer_type": "MEDICARE"}
        res = api.create_resident(home["id"], payload, NURSE)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


class TestResidentWithdrawal:
    def test_withdraw_returns_applicant_to_prospect(self, api):
        """PRD §3.2: "Withdrawal lets an `APPLICANT` return to `PROSPECT` through a
        `Provider` action, permitted only when no admission in `PENDING` or
        `APPROVED` exists for the resident."

        Design: Corner/state_machines/resident_withdraw_returns_prospect
        """
        home = create_home(name="Wd Ok", licensed_bed_capacity=4)
        appl = create_applicant(home["id"])
        withdrawn = validate_success(
            api.withdraw_resident(appl["resident"]["id"], PROVIDER), 200)
        assert withdrawn["status"] == "PROSPECT", "withdrawal must revert APPLICANT"

    def test_withdraw_keeps_finalized_assessment(self, api):
        """PRD §3.2: "Withdrawal does not disturb the resident's assessments:
        anything `FINALIZED` remains `FINALIZED`."

        Design: Corner/state_machines/resident_withdraw_returns_prospect
        """
        home = create_home(name="Wd Ok", licensed_bed_capacity=4)
        appl = create_applicant(home["id"])
        validate_success(api.withdraw_resident(appl["resident"]["id"], PROVIDER), 200)
        asm_after = validate_success(
            api.get_assessment(appl["assessment"]["id"], NURSE), 200)
        assert asm_after["status"] == "FINALIZED", \
            "withdrawal must not disturb the FINALIZED assessment"

    def test_withdraw_blocked_by_pending_admission(self, api):
        """PRD §3.2: "Withdrawal lets an `APPLICANT` return to `PROSPECT` through a
        `Provider` action, permitted only when no admission in `PENDING` or
        `APPROVED` exists for the resident."
        PRD §2.9: "State-machine legality — the target resource is in a from-state
        that permits the transition and is not terminally locked; failure yields
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/withdraw_applicant_with_pending_admission_rejected
        """
        ctx = create_licensed_home(name="Wd Block", bed_label="1A")
        home, bed = ctx["home"], ctx["bed"]
        adm = create_pending_admission_scenario(home["id"], bed["id"])
        res = api.withdraw_resident(adm["resident"]["id"], PROVIDER)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        assert fresh_resident(adm["resident"]["id"])["status"] == "APPLICANT"
        admission_after = validate_success(
            api.get_admission(adm["admission"]["id"], PROVIDER), 200)
        assert admission_after["status"] == "PENDING"
        assert fresh_bed(bed["id"])["status"] == "HELD", \
            "the hold must survive the rejected withdrawal"


class TestAdmissionCreation:
    def test_admission_with_unknown_bed_returns_404(self, api):
        """PRD §2.10: "A request for a bed listing under a non-existent home
        identifier, for example, fails on the home identifier before any bed is ever
        looked up, and the same left-to-right discipline applies to identifiers
        referenced in request bodies after the path has resolved."
        PRD §2.9: "Existence — every identifier referenced in the path and in the
        body exists, validated left-to-right (§2.10); failure yields
        `ERR_NOT_FOUND`."

        Design: Corner/entities/admission_with_unknown_bed_returns_404
        """
        home = create_home(name="Corner Juniper", licensed_bed_capacity=4)
        bed = add_bed(home["id"], label="1A")
        appl = create_applicant(home["id"])
        payload = create_admission_payload(
            appl["resident"]["id"], "11111111-2222-3333-4444-555555555555",
            appl["assessment"]["id"], bed["version"])
        res = api.create_admission(payload, PROVIDER)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)

    def test_medicaid_resident_on_uncertified_bed_rejected(self, api):
        """PRD §3.3: "Creation is refused with `ERR_BED_NOT_CERTIFIED` when a
        `MEDICAID` resident references a bed whose `medicaid_certified` flag is
        false."

        Design: Corner/errors/err_bed_not_certified_triggered
        """
        home = create_home(name="Cert", licensed_bed_capacity=4)
        bed = add_bed(home["id"], label="1A")
        appl = create_applicant(home["id"], payer_type="MEDICAID")
        payload = create_admission_payload(
            appl["resident"]["id"], bed["id"], appl["assessment"]["id"],
            bed["version"])
        res = api.create_admission(payload, PROVIDER)
        validate_error(res, ApiErrorId.ERR_BED_NOT_CERTIFIED, expected_status=422)
        assert fresh_bed(bed["id"])["status"] == "AVAILABLE", \
            "no hold may be placed when certification fails"

    def test_occ_stale_bed_version_rejected(self, api):
        """PRD §2.7: "A `POST /api/admissions` request must carry
        `expected_bed_version` equal to the target bed's current `version`. If the
        bed's version has advanced since the client last read it — another writer may
        have taken the bed out of service, or a competing admission may have held it
        — the client's view of the bed is stale and the create is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_admission_create_stale_bed_version
        """
        home = create_home(name="OCC Adm", licensed_bed_capacity=4)
        bed = add_bed(home["id"], label="1A")
        stale_version = bed["version"]
        appl1 = create_applicant(home["id"], full_name="Res O1")
        appl2 = create_applicant(home["id"], full_name="Res O2")
        first = api.create_admission(
            create_admission_payload(appl1["resident"]["id"], bed["id"],
                                     appl1["assessment"]["id"], stale_version),
            PROVIDER)
        validate_success(first, 201)
        res = api.create_admission(
            create_admission_payload(appl2["resident"]["id"], bed["id"],
                                     appl2["assessment"]["id"], stale_version),
            PROVIDER)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


class TestAdmissionDecision:
    def test_creator_cannot_approve_own_admission(self, api):
        """PRD §3.3: "The approving operator's `X-User-ID` must differ from the
        identifier recorded as the admission's creator — segregation of duties, so
        the requester can never approve their own admission — else
        `ERR_SELF_APPROVAL`."

        Design: Corner/errors/err_self_approval_triggered
        """
        ctx = create_licensed_home(name="Self Appr", bed_label="1A")
        home, bed = ctx["home"], ctx["bed"]
        adm = create_pending_admission_scenario(home["id"], bed["id"])
        res = api.approve_admission(adm["admission"]["id"], PROVIDER)  # creator prov-1
        validate_error(res, ApiErrorId.ERR_SELF_APPROVAL, expected_status=409)
        admission_after = validate_success(
            api.get_admission(adm["admission"]["id"], PROVIDER), 200)
        assert admission_after["status"] == "PENDING"

    def test_second_approve_rejected(self, api):
        """PRD §3.3: "Approval — a `Provider` decision moving `PENDING` → `APPROVED`
        — enforces its checks in the pipeline order of §2.9. The admission must
        actually be `PENDING`, else `ERR_INVALID_STATE`."

        Design: Corner/state_machines/approve_already_approved_admission_rejected
        """
        ctx = create_licensed_home(name="Adm Twice", bed_label="1A")
        home, bed = ctx["home"], ctx["bed"]
        adm = create_approved_admission_scenario(home["id"], bed["id"])
        assert adm["admission"]["status"] == "APPROVED"
        res = api.approve_admission(adm["admission"]["id"], PROVIDER2)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_complete_from_pending_rejected(self, api):
        """PRD §3.3: "Completion — `APPROVED` → `COMPLETED` — is the physical
        move-in."
        PRD §2.9: "State-machine legality — the target resource is in a from-state
        that permits the transition and is not terminally locked; failure yields
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/admission_complete_from_pending_rejected
        """
        ctx = create_licensed_home(name="Cpl Pend", bed_label="1A")
        home, bed = ctx["home"], ctx["bed"]
        adm = create_pending_admission_scenario(home["id"], bed["id"])
        res = api.complete_admission(adm["admission"]["id"], PROVIDER2)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        admission_after = validate_success(
            api.get_admission(adm["admission"]["id"], PROVIDER), 200)
        assert admission_after["status"] == "PENDING"
        assert fresh_resident(adm["resident"]["id"])["status"] == "APPLICANT"


class TestAdmissionCompletionCapacity:
    def test_complete_at_capacity_rejected(self, api):
        """PRD §3.3: "It requires the home `LICENSED` and the home's `current_census`
        strictly below its `licensed_bed_capacity`; a home already at capacity
        rejects the completion with `ERR_CAPACITY_EXCEEDED`."

        Design: Corner/errors/err_capacity_exceeded_triggered
        """
        set_clock("2026-05-20T00:00:00Z")
        ctx = create_licensed_home(name="Cap Two", capacity=2, bed_label="1A")
        home = ctx["home"]
        bed_b = add_bed(home["id"], label="1B")
        bed_c = add_bed(home["id"], label="1C")
        admissions = []
        for bed in (ctx["bed"], bed_b, bed_c):
            adm = create_approved_admission_scenario(home["id"], bed["id"])
            admissions.append(adm)
        complete_admission(admissions[0]["admission"]["id"])
        complete_admission(admissions[1]["admission"]["id"])
        res = api.complete_admission(admissions[2]["admission"]["id"], PROVIDER2)
        validate_error(res, ApiErrorId.ERR_CAPACITY_EXCEEDED, expected_status=409)
        admission_after = validate_success(
            api.get_admission(admissions[2]["admission"]["id"], PROVIDER), 200)
        assert admission_after["status"] == "APPROVED", \
            "rejected completion must leave the admission APPROVED"
        assert fresh_resident(admissions[2]["resident"]["id"])["status"] == "APPLICANT"
        assert get_success_data(api.get_home(home["id"], PROVIDER))[
            "current_census"] == 2


class TestAdmissionListing:
    def test_admissions_filterable_by_resident(self, api):
        """PRD §4: "Collection endpoints accept `limit` and `offset` for pagination
        plus resource-appropriate filters: `status` on most collections, `payer_type`
        on resident and rate-schedule listings, `severity` on incident listings, and
        the foreign-key filters `resident_id`, `bed_id`, `assessment_id`, `order_id`,
        `caregiver_id`, `home_id`, `incident_id`, and `invoice_id` where a collection
        is reachable through multiple parents."

        Design: Corner/endpoints/admissions_filterable_by_resident
        """
        home = create_home(name="Adm Filter", licensed_bed_capacity=4)
        bed1 = add_bed(home["id"], label="1A")
        bed2 = add_bed(home["id"], label="1B")
        adm1 = create_pending_admission_scenario(home["id"], bed1["id"],
                                                 full_name="Res F1")
        adm2 = create_pending_admission_scenario(home["id"], bed2["id"],
                                                 full_name="Res F2",
                                                 nursing_hours_per_week=3,
                                                 adl_dependency_score=2)
        data, meta = validate_paginated(api.list_admissions(
            PROVIDER, params={"resident_id": adm1["resident"]["id"]}))
        assert meta["total_count"] == 1
        assert len(data) == 1
        assert data[0]["id"] == adm1["admission"]["id"]
        assert data[0]["id"] != adm2["admission"]["id"], \
            "the other resident's admission must be excluded"


class TestSupersededAssessmentBlocksApproval:
    def test_approval_rejected_with_assessment_superseded(self, api):
        """PRD §3.3: "The pinned assessment must still be `FINALIZED`, else
        `ERR_ASSESSMENT_SUPERSEDED`."
        PRD §3.2: "And a `PENDING` admission that pinned the now-superseded
        assessment is left untouched at this moment — the pin references the
        assessment's `id`, which remains on record — but its later approval will be
        rejected with `ERR_ASSESSMENT_SUPERSEDED` (§3.3)."

        Design: Difficulty/cross_entity_state_dependency/admission_approval_blocked_by_superseded_assessment
        """
        ctx = create_licensed_home(name="Juniper AFH", bed_label="1A")
        home, bed = ctx["home"], ctx["bed"]
        adm = create_pending_admission_scenario(home["id"], bed["id"])
        asm2 = create_and_finalize_assessment(
            adm["resident"]["id"], nursing_hours_per_week=8,
            adl_dependency_score=4, care_plan={"diet": "PUREED"})
        res = api.approve_admission(adm["admission"]["id"], PROVIDER2)
        validate_error(res, ApiErrorId.ERR_ASSESSMENT_SUPERSEDED, expected_status=409)
        admission_after = validate_success(
            api.get_admission(adm["admission"]["id"], PROVIDER), 200)
        assert admission_after["status"] == "PENDING", \
            "rejected approval must leave the admission PENDING"

    def test_prior_assessment_marked_superseded(self, api):
        """PRD §3.2: "Any previously `FINALIZED` assessment for the same resident
        becomes `SUPERSEDED`, a terminal state, in a version-pinned replacement loop
        that supports cyclic re-assessment."

        Design: Difficulty/cross_entity_state_dependency/admission_approval_blocked_by_superseded_assessment
        """
        ctx = create_licensed_home(name="Juniper AFH", bed_label="1A")
        home, bed = ctx["home"], ctx["bed"]
        adm = create_pending_admission_scenario(home["id"], bed["id"])
        asm2 = create_and_finalize_assessment(
            adm["resident"]["id"], nursing_hours_per_week=8,
            adl_dependency_score=4, care_plan={"diet": "PUREED"})
        asm1_after = validate_success(
            api.get_assessment(adm["assessment"]["id"], NURSE), 200)
        assert asm1_after["status"] == "SUPERSEDED"
        asm2_after = validate_success(api.get_assessment(asm2["id"], NURSE), 200)
        assert asm2_after["status"] == "FINALIZED"
