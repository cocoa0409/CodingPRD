"""Certificate submission validation battery: matrix lookup, linkage, temporal
windows, inventory, safety gates, and validation-priority pairs (PRD §2.5, §3.4)."""
from test_helpers import (
    ApiErrorId,
    create_draft_certificate,
    create_entry_requirement,
    create_negative_test,
    create_premises,
    create_quarantine_order,
    create_submitted_certificate,
    create_test_record,
    create_veterinarian,
    make_officer_headers,
    make_vet_headers,
    report_result,
    set_clock,
    setup_standard_scenario,
    submit_certificate,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestMatrixRowRequired:
    def test_certificate_submit_requires_active_matrix_row(self, api, admin_headers):
        """PRD §3.4: "An `ACTIVE` entry-requirement row must exist for the
        certificate's `destination_state_code` and `species_code` whose
        half-open window covers the `inspection_date`, else
        `ERR_NO_ACTIVE_ENTRY_REQUIREMENT` (HTTP 422)."
        PRD §3.1: "Each row is effective over a half-open window:
        `effective_from` is inclusive, `effective_until` is exclusive, and a
        null `effective_until` means the row is open-ended".

        Design: Corner/state_machines/certificate_submit_requires_active_matrix_row
        """
        premises = create_premises(name="Ranch S29", initial_head_count=30)
        vet = create_veterinarian()
        set_clock("2026-08-10T00:00:00Z")
        cert = create_draft_certificate(
            premises["id"], vet["id"], head_count=5, inspection_date="2026-08-10T00:00:00Z"
        )
        vet_h = make_vet_headers(vet["id"])

        # No matrix row at all.
        resp_none = api.submit_certificate(cert["id"], vet_h)
        validate_error(resp_none, ApiErrorId.ERR_NO_ACTIVE_ENTRY_REQUIREMENT)

        # Row whose window starts after the inspection date does not cover it.
        create_entry_requirement(
            none_type=True, permit_required=False, effective_from="2026-09-01T00:00:00Z"
        )
        resp_late = api.submit_certificate(cert["id"], vet_h)
        validate_error(resp_late, ApiErrorId.ERR_NO_ACTIVE_ENTRY_REQUIREMENT)

        # Adjacent covering row [2026-06-01, 2026-09-01) — half-open adjacency
        # does not overlap the existing [2026-09-01, open) row — unblocks submit.
        create_entry_requirement(
            none_type=True,
            permit_required=False,
            effective_from="2026-06-01T00:00:00Z",
            effective_until="2026-09-01T00:00:00Z",
        )
        resp_ok = api.submit_certificate(cert["id"], vet_h)
        data = validate_success(resp_ok, 200)
        assert data["status"] == "PENDING_REVIEW"
        # 5 head CATTLE on MONITORED premises: 2500 + 150*5 + 1000.
        assert data["provisional_fee_cents"] == 4250


class TestSpeciesLinkage:
    def test_certificate_species_mismatch_rejected(self, api, admin_headers, auditor_headers):
        """PRD §3.4: "The certificate's `species_code` must equal the origin
        premises' `species_code`, else `ERR_PREMISES_SPECIES_MISMATCH`
        (HTTP 422)."
        PRD §3.7: "supplying `premises_id`, `species_code` (which must equal
        the premises' own species, else `ERR_PREMISES_SPECIES_MISMATCH`)".

        Design: Corner/state_machines/certificate_species_mismatch_rejected
        """
        premises = create_premises(name="Ranch S30", initial_head_count=30)
        vet = create_veterinarian()
        # A matching SWINE matrix row exists, so only the species link can fail.
        create_entry_requirement(none_type=True, species_code="SWINE", permit_required=False)
        set_clock("2026-08-10T00:00:00Z")
        cert = create_draft_certificate(
            premises["id"], vet["id"], species_code="SWINE", head_count=5
        )

        resp_c = api.submit_certificate(cert["id"], make_vet_headers(vet["id"]))
        validate_error(resp_c, ApiErrorId.ERR_PREMISES_SPECIES_MISMATCH)

        resp_q = api.create_quarantine_order(
            {
                "premises_id": premises["id"],
                "species_code": "SWINE",
                "disease_code": "PSEUDORABIES",
                "start_at": "2026-08-10T00:00:00Z",
                "end_at": "2026-08-24T00:00:00Z",
                "reason": "WRONG_SPECIES",
            },
            make_officer_headers("officer-a"),
        )
        validate_error(resp_q, ApiErrorId.ERR_PREMISES_SPECIES_MISMATCH)

        after = validate_success(api.get_certificate(cert["id"], auditor_headers))
        assert after["status"] == "DRAFT"
        orders, meta = validate_paginated(
            api.list_quarantine_orders_for_premises(premises["id"], auditor_headers)
        )
        assert meta["total_count"] == 0, "no quarantine order may be persisted"

    def test_test_record_species_mismatch_rejected(self, api, admin_headers, auditor_headers):
        """PRD §3.4: "The `test_record_id` must name a test record drawn on
        the same origin premises, of the same species, and of the matrix row's
        `test_type`, else `ERR_TEST_RECORD_MISMATCH` (HTTP 422)."

        Design: Corner/state_machines/test_record_species_mismatch_rejected
        """
        premises = create_premises(name="Ranch S31", initial_head_count=30)
        vet = create_veterinarian()
        create_entry_requirement(vaccination_required=False)
        # Same premises, same test_type, NEGATIVE — but the wrong species.
        test = create_test_record(premises["id"], species_code="SWINE", lab_reference="LAB-S31")
        report_result(test["id"], "NEGATIVE")
        set_clock("2026-08-10T00:00:00Z")
        cert = create_draft_certificate(
            premises["id"], vet["id"], test_record_id=test["id"]
        )

        resp = api.submit_certificate(cert["id"], make_vet_headers(vet["id"]))
        validate_error(resp, ApiErrorId.ERR_TEST_RECORD_MISMATCH)
        after = validate_success(api.get_certificate(cert["id"], auditor_headers))
        assert after["status"] == "DRAFT"


class TestTestResultGate:
    def test_pending_test_not_qualifying(self, api, admin_headers, auditor_headers):
        """PRD §3.4: "When the matrix row's `test_type` is not `NONE`, the
        relied-upon test's `result` must be `NEGATIVE`; a `RESULT_PENDING` or
        `POSITIVE` test fails with `ERR_TEST_NOT_QUALIFYING` (HTTP 422)."

        Design: Corner/state_machines/pending_test_not_qualifying
        """
        premises = create_premises(name="Ranch S32", initial_head_count=30)
        vet = create_veterinarian()
        create_entry_requirement(vaccination_required=False)
        test = create_test_record(premises["id"], lab_reference="LAB-S32")
        # Result left RESULT_PENDING.
        set_clock("2026-08-10T00:00:00Z")
        cert = create_draft_certificate(
            premises["id"], vet["id"], test_record_id=test["id"]
        )

        resp = api.submit_certificate(cert["id"], make_vet_headers(vet["id"]))
        validate_error(resp, ApiErrorId.ERR_TEST_NOT_QUALIFYING)
        after = validate_success(api.get_certificate(cert["id"], auditor_headers))
        assert after["status"] == "DRAFT"


class TestVaccinationWindow:
    def test_vaccination_window_enforcement(self, api, admin_headers, auditor_headers):
        """PRD §3.4: "When the row's `vaccination_required` is true, a
        `vaccination_date` must be present and its whole-day age at inspection
        must be at least `vaccination_min_days_before_inspection`, else
        `ERR_VACCINATION_WINDOW_VIOLATION` (HTTP 422)."
        PRD §2.9: "A vaccination qualifies when its whole-day age at inspection
        is at least the matrix row's `vaccination_min_days_before_inspection`,
        again inclusive."

        Design: Corner/state_machines/vaccination_window_enforcement
        """
        scenario = setup_standard_scenario(head_count=40)  # vax min 14 days
        vet_h = make_vet_headers(scenario["vet"]["id"])
        base = {
            "destination_state_code": "KS",
            "species_code": "CATTLE",
            "head_count": 10,
            "inspection_date": "2026-08-10T00:00:00Z",
            "test_record_id": scenario["test"]["id"],
        }
        cert_a = create_draft_certificate(
            scenario["premises"]["id"], scenario["vet"]["id"],
            vaccination_date="2026-08-05T00:00:00Z", **base,
        )  # age 5 days < 14
        cert_b = create_draft_certificate(
            scenario["premises"]["id"], scenario["vet"]["id"], **base,
        )  # vaccination_date missing entirely
        cert_c = create_draft_certificate(
            scenario["premises"]["id"], scenario["vet"]["id"],
            vaccination_date="2026-07-27T00:00:00Z", **base,
        )  # age exactly 14 days

        validate_error(
            api.submit_certificate(cert_a["id"], vet_h),
            ApiErrorId.ERR_VACCINATION_WINDOW_VIOLATION,
        )
        validate_error(
            api.submit_certificate(cert_b["id"], vet_h),
            ApiErrorId.ERR_VACCINATION_WINDOW_VIOLATION,
        )
        ok = validate_success(api.submit_certificate(cert_c["id"], vet_h), 200)
        assert ok["status"] == "PENDING_REVIEW", "age exactly 14 days is inclusive-valid"
        assert ok["provisional_fee_cents"] == 5000


class TestInventoryGateAtSubmit:
    def test_head_count_exceeds_inventory_on_submit(self, api, admin_headers, auditor_headers):
        """PRD §3.4: "The certificate's `head_count` must not exceed the origin
        premises' `current_head_count`, else `ERR_HEAD_COUNT_EXCEEDS_INVENTORY`
        (HTTP 422)."

        Design: Corner/state_machines/head_count_exceeds_inventory_on_submit
        """
        premises = create_premises(name="Ranch S34", initial_head_count=20)
        vet = create_veterinarian()
        create_entry_requirement()
        test = create_negative_test(premises["id"], lab_reference="LAB-S34")
        set_clock("2026-08-10T00:00:00Z")
        # Creation succeeds: the inventory gate lives at submission.
        cert = create_draft_certificate(
            premises["id"], vet["id"], head_count=25,
            test_record_id=test["id"], vaccination_date="2026-07-12T00:00:00Z",
        )
        assert cert["status"] == "DRAFT"

        resp = api.submit_certificate(cert["id"], make_vet_headers(vet["id"]))
        validate_error(resp, ApiErrorId.ERR_HEAD_COUNT_EXCEEDS_INVENTORY)
        after = validate_success(api.get_certificate(cert["id"], auditor_headers))
        assert after["status"] == "DRAFT"


class TestTestValidityBoundary:
    def test_test_validity_day_boundary_inclusive_pass(
        self, api, admin_headers, auditor_headers
    ):
        """PRD §2.9: "A test qualifies when its whole-day age at inspection is
        at least zero and at most the matrix row's `test_validity_days`, with
        the upper bound inclusive."

        Design: Difficulty/boundary_precision_check/test_validity_day_boundary_inclusive
        """
        premises = create_premises(name="Ranch H", initial_head_count=30)
        vet = create_veterinarian()
        create_entry_requirement()  # test_validity_days 30, vax min 14
        # Drawn 2026-07-11; inspection 2026-08-10 -> whole-day age exactly 30.
        test = create_negative_test(
            premises["id"], test_date="2026-07-11T00:00:00Z", lab_reference="LAB-30"
        )
        set_clock("2026-08-10T00:00:00Z")
        cert = create_draft_certificate(
            premises["id"], vet["id"], test_record_id=test["id"],
            vaccination_date="2026-07-12T00:00:00Z",
        )
        resp = api.submit_certificate(cert["id"], make_vet_headers(vet["id"]))
        data = validate_success(resp, 200)
        assert data["status"] == "PENDING_REVIEW", (
            "whole-day test age 30 == test_validity_days 30 must pass (inclusive)"
        )

    def test_test_validity_day_boundary_inclusive_fail(self, api, admin_headers):
        """PRD §3.4: "The test's whole-day age at inspection (per §2.9) must
        not exceed the row's `test_validity_days`; an over-age test fails with
        `ERR_TEST_VALIDITY_EXPIRED` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/test_validity_day_boundary_inclusive
        """
        premises = create_premises(name="Ranch H2", initial_head_count=30)
        vet = create_veterinarian()
        create_entry_requirement()  # test_validity_days 30
        # Drawn 2026-07-10; inspection 2026-08-10 -> whole-day age 31.
        test = create_negative_test(
            premises["id"], test_date="2026-07-10T00:00:00Z", lab_reference="LAB-31"
        )
        set_clock("2026-08-10T00:00:00Z")
        cert = create_draft_certificate(
            premises["id"], vet["id"], test_record_id=test["id"],
            vaccination_date="2026-07-12T00:00:00Z",
        )
        resp = api.submit_certificate(cert["id"], make_vet_headers(vet["id"]))
        validate_error(resp, ApiErrorId.ERR_TEST_VALIDITY_EXPIRED)


class TestStateBeatsSafetyOnIssue:
    def _setup_rejected_cert_under_quarantine(self, api, admin_headers):
        scenario, cert = create_submitted_certificate()
        validate_success(
            api.reject_certificate(
                cert["id"], {"reason_code": "INCOMPLETE"}, make_officer_headers("officer-a")
            ),
            200,
        )
        create_quarantine_order(scenario["premises"]["id"], officer_user_id="officer-a")
        return scenario, cert

    def test_state_blocks_safety_on_issue_error_id(self, api, admin_headers):
        """PRD §2.5: "Every request passes through a fixed pipeline of
        validation layers, evaluated in the order below; the first layer that
        fails determines the error the client sees." (state preconditions are
        layer 6; safety gates layer 7.)
        PRD §3.4: "Attempting issuance — or rejection — from any other state
        yields `ERR_CERTIFICATE_NOT_PENDING_REVIEW` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/state_blocks_safety_on_issue
        """
        scenario, cert = self._setup_rejected_cert_under_quarantine(api, admin_headers)
        premises = validate_success(api.get_premises(scenario["premises"]["id"], make_officer_headers("officer-a")))
        assert premises["disease_status"] == "QUARANTINE_HOLD", (
            "precondition: the safety gate must also be eligible to fire"
        )

        resp = api.issue_certificate(cert["id"], make_officer_headers("officer-a"))
        validate_error(resp, ApiErrorId.ERR_CERTIFICATE_NOT_PENDING_REVIEW)

    def test_state_blocks_safety_on_issue_certificate_unchanged(
        self, api, admin_headers, auditor_headers
    ):
        """PRD §2.5: "Every request passes through a fixed pipeline of
        validation layers, evaluated in the order below; the first layer that
        fails determines the error the client sees."
        PRD §3.4: "Attempting issuance — or rejection — from any other state
        yields `ERR_CERTIFICATE_NOT_PENDING_REVIEW` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/state_blocks_safety_on_issue
        """
        scenario, cert = self._setup_rejected_cert_under_quarantine(api, admin_headers)
        resp = api.issue_certificate(cert["id"], make_officer_headers("officer-a"))
        err = validate_error(resp, ApiErrorId.ERR_CERTIFICATE_NOT_PENDING_REVIEW)
        assert err["error_id"] != ApiErrorId.ERR_PREMISES_DISEASE_HOLD, (
            "the layer-6 state error must win over the layer-7 safety error"
        )
        after = validate_success(api.get_certificate(cert["id"], auditor_headers))
        assert after["status"] == "REJECTED"
        assert after["cvi_number"] is None


class TestReferentialBeatsTemporal:
    def _setup_foreign_expired_test(self, api):
        prem_a = create_premises(name="Ranch A", county="Yolo", initial_head_count=20)
        prem_b = create_premises(name="Ranch B", county="Fresno", initial_head_count=20)
        vet = create_veterinarian()
        create_entry_requirement()  # validity 30d, vax min 14
        # NEGATIVE test drawn on premises B 45 days before inspection (expired).
        test_b = create_test_record(
            prem_b["id"], test_date="2026-06-26T00:00:00Z", lab_reference="LAB-B"
        )
        report_result(test_b["id"], "NEGATIVE")
        set_clock("2026-08-10T00:00:00Z")
        cert = create_draft_certificate(
            prem_a["id"], vet["id"], test_record_id=test_b["id"],
            vaccination_date="2026-07-12T00:00:00Z",
        )
        return vet, cert

    def test_referential_mismatch_beats_temporal_expiry_error_id(self, api, admin_headers):
        """PRD §2.5: "Every request passes through a fixed pipeline of
        validation layers, evaluated in the order below; the first layer that
        fails determines the error the client sees." (matrix/linkage integrity
        is layer 8; temporal-window rules layer 9.)
        PRD §3.4: "The `test_record_id` must name a test record drawn on
        the same origin premises, of the same species, and of the matrix row's
        `test_type`, else `ERR_TEST_RECORD_MISMATCH` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/referential_mismatch_beats_temporal_expiry
        """
        vet, cert = self._setup_foreign_expired_test(api)
        resp = api.submit_certificate(cert["id"], make_vet_headers(vet["id"]))
        validate_error(resp, ApiErrorId.ERR_TEST_RECORD_MISMATCH)

    def test_referential_mismatch_beats_temporal_expiry_not_temporal_error(
        self, api, admin_headers, auditor_headers
    ):
        """PRD §2.5: "Every request passes through a fixed pipeline of
        validation layers, evaluated in the order below; the first layer that
        fails determines the error the client sees."
        PRD §3.4: "The test's whole-day age at inspection (per §2.9) must not
        exceed the row's `test_validity_days`; an over-age test fails with
        `ERR_TEST_VALIDITY_EXPIRED` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/referential_mismatch_beats_temporal_expiry
        """
        vet, cert = self._setup_foreign_expired_test(api)
        resp = api.submit_certificate(cert["id"], make_vet_headers(vet["id"]))
        err = validate_error(resp, ApiErrorId.ERR_TEST_RECORD_MISMATCH)
        assert err["error_id"] != ApiErrorId.ERR_TEST_VALIDITY_EXPIRED, (
            "the layer-8 linkage error must win over the layer-9 temporal error "
            "even though the 45-day-old test is also expired"
        )
        after = validate_success(api.get_certificate(cert["id"], auditor_headers))
        assert after["status"] == "DRAFT"


class TestSubmitGatedByPremisesDiseaseHold:
    def test_certificate_submit_gated_by_premises_disease_hold_error(
        self, api, admin_headers
    ):
        """PRD §3.4: "The origin premises' `disease_status` must be neither
        `QUARANTINE_HOLD` nor `INFECTED` (`ERR_PREMISES_DISEASE_HOLD`,
        HTTP 422)."
        PRD §3.7: "Creation pushes the premises' `disease_status` to
        `QUARANTINE_HOLD` unless the premises is already `INFECTED`".

        Design: Difficulty/cross_entity_state_dependency/certificate_submit_gated_by_premises_disease_hold
        """
        scenario = setup_standard_scenario()
        cert = create_draft_certificate(scenario["premises"]["id"], scenario["vet"]["id"])
        create_quarantine_order(scenario["premises"]["id"], officer_user_id="officer-a")

        resp = api.submit_certificate(cert["id"], make_vet_headers(scenario["vet"]["id"]))
        validate_error(resp, ApiErrorId.ERR_PREMISES_DISEASE_HOLD)

    def test_certificate_submit_gated_by_premises_disease_hold_state_unchanged(
        self, api, admin_headers, auditor_headers
    ):
        """PRD §3.4: "The origin premises' `disease_status` must be neither
        `QUARANTINE_HOLD` nor `INFECTED` (`ERR_PREMISES_DISEASE_HOLD`,
        HTTP 422)."
        PRD §3.4: "Submission moves a `DRAFT` certificate to `PENDING_REVIEW`."

        Design: Difficulty/cross_entity_state_dependency/certificate_submit_gated_by_premises_disease_hold
        """
        scenario = setup_standard_scenario()
        cert = create_draft_certificate(scenario["premises"]["id"], scenario["vet"]["id"])
        create_quarantine_order(scenario["premises"]["id"], officer_user_id="officer-a")

        resp = api.submit_certificate(cert["id"], make_vet_headers(scenario["vet"]["id"]))
        validate_error(resp, ApiErrorId.ERR_PREMISES_DISEASE_HOLD)
        after = validate_success(api.get_certificate(cert["id"], auditor_headers))
        assert after["status"] == "DRAFT", (
            "a rejected submission must not move the certificate out of DRAFT"
        )


class TestIssueBlockedByDiseaseHold:
    def test_issue_blocked_by_premises_disease_hold(
        self, api, admin_headers, officer_headers, auditor_headers
    ):
        """PRD §3.4: "Issuance re-runs the first two safety gates: the acting
        veterinarian's credential must still be current (`ERR_VET_NOT_CURRENT`),
        and the origin premises must still be free of disease hold
        (`ERR_PREMISES_DISEASE_HOLD`)."

        Design: Corner/state_machines/issue_blocked_by_premises_disease_hold
        """
        scenario, cert = create_submitted_certificate(none_matrix=True)
        create_quarantine_order(scenario["premises"]["id"], officer_user_id="officer-a")

        resp = api.issue_certificate(cert["id"], officer_headers)
        validate_error(resp, ApiErrorId.ERR_PREMISES_DISEASE_HOLD)
        after = validate_success(api.get_certificate(cert["id"], auditor_headers))
        assert after["status"] == "PENDING_REVIEW"
        assert after["cvi_number"] is None


class TestVeterinarianCredential:
    def test_veterinarian_suspension_blocks_submit(
        self, api, admin_headers, officer_headers, auditor_headers
    ):
        """PRD §3.1: "A `StateVetOfficer` may suspend a veterinarian whose
        `status` is `ACTIVE`; suspending an already-`SUSPENDED` veterinarian is
        rejected with `ERR_VET_NOT_SUSPENDABLE` (HTTP 409). Suspension does not
        rewrite history, but it immediately blocks that veterinarian's
        certificate submissions and any issuance performed under their
        credential, which fail the credential check with `ERR_VET_NOT_CURRENT`
        (HTTP 422)."

        Design: Corner/state_machines/veterinarian_suspension_blocks_submit
        """
        scenario = setup_standard_scenario(none_matrix=True)
        cert = create_draft_certificate(scenario["premises"]["id"], scenario["vet"]["id"])

        suspended = validate_success(
            api.suspend_veterinarian(scenario["vet"]["id"], officer_headers), 200
        )
        assert suspended["status"] == "SUSPENDED"
        assert suspended["is_credential_current"] is False

        resp = api.submit_certificate(cert["id"], make_vet_headers(scenario["vet"]["id"]))
        validate_error(resp, ApiErrorId.ERR_VET_NOT_CURRENT)
        after = validate_success(api.get_certificate(cert["id"], auditor_headers))
        assert after["status"] == "DRAFT"

        resp2 = api.suspend_veterinarian(scenario["vet"]["id"], officer_headers)
        validate_error(resp2, ApiErrorId.ERR_VET_NOT_SUSPENDABLE)

    def test_veterinarian_credential_expiry_boundary(self, api, admin_headers, officer_headers):
        """PRD §3.1: "The derived flag `is_credential_current` recomputes on
        every read: it is true exactly when `status` is `ACTIVE` and
        `accreditation_expires_at` is at or after the logical clock."
        PRD §3.4: "The acting veterinarian's `is_credential_current` must be
        true (`ERR_VET_NOT_CURRENT`, HTTP 422)."

        Design: Corner/state_machines/veterinarian_credential_expiry_boundary
        """
        premises = create_premises(name="Ranch S26", initial_head_count=30)
        vet = create_veterinarian(
            full_name="Dr. Eve",
            accreditation_number="ACCRED-E",
            accreditation_expires_at="2026-08-15T00:00:00Z",
        )
        create_entry_requirement(none_type=True)
        set_clock("2026-08-10T00:00:00Z")
        cert1 = create_draft_certificate(premises["id"], vet["id"], head_count=5)
        cert2 = create_draft_certificate(premises["id"], vet["id"], head_count=5)
        submit_certificate(cert1["id"], vet["id"])

        # At clock exactly == accreditation_expires_at the credential still holds.
        set_clock("2026-08-15T00:00:00Z")
        issued = validate_success(api.issue_certificate(cert1["id"], officer_headers), 200)
        assert issued["status"] == "ISSUED", (
            "expiry 'at or after the logical clock' is inclusive"
        )

        # One day past expiry the same vet cannot submit.
        set_clock("2026-08-16T00:00:00Z")
        resp = api.submit_certificate(cert2["id"], make_vet_headers(vet["id"]))
        validate_error(resp, ApiErrorId.ERR_VET_NOT_CURRENT)
