"""Certificate lifecycle: creation stamps, review/issue/transmit happy path,
revision loop, void/lapse terminal lockdown (PRD §2.9, §2.10, §3.3, §3.4, §3.8)."""
from test_helpers import (
    DEFAULTS,
    ApiErrorId,
    assert_certificate,
    assert_transmission_audit,
    create_draft_certificate,
    create_issued_certificate,
    create_premises,
    create_submitted_certificate,
    create_veterinarian,
    make_vet_headers,
    set_clock,
    setup_standard_scenario,
    submit_certificate,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCertificateCreationStamps:
    def test_certificate_system_fields_stamped_on_create(self, api, admin_headers):
        """PRD §3.3: "The draft is born in `status` `DRAFT`. The creating
        veterinarian's identity is stamped automatically: `vet_id` is set to
        the caller's `X-User-ID`, and any client-supplied value for it is
        ignored. The certificate's fee fields stay null until their respective
        triggers — `provisional_fee_cents` until submission, `final_fee_cents`
        until issuance — and `cvi_number`, `issued_at`, and `valid_until`
        likewise remain null until issued."

        Design: Corner/entities/certificate_system_fields_stamped_on_create
        """
        premises = create_premises(name="Ranch D5", initial_head_count=20)
        vet = create_veterinarian()
        resp = api.create_certificate(
            {
                "origin_premises_id": premises["id"],
                "destination_state_code": "KS",
                "species_code": "CATTLE",
                "head_count": 5,
                "inspection_date": "2026-08-01T00:00:00Z",
                "consignment_description": "Feeder cattle",
            },
            make_vet_headers(vet["id"]),
        )
        data = validate_success(resp, 201)
        assert_certificate(data)
        assert data["vet_id"] == vet["id"], (
            f"vet_id must be stamped from X-User-ID: {data['vet_id']!r} != {vet['id']!r}"
        )
        assert data["status"] == "DRAFT"
        for field in ("cvi_number", "issued_at", "valid_until"):
            assert data[field] is None, f"{field} must be null before issuance"
        for field in ("provisional_fee_cents", "final_fee_cents"):
            assert data[field] is None, f"{field} must be null before its trigger"
        for field in ("pre_block_status", "reject_reason", "void_reason"):
            assert data.get(field) is None, f"{field} must be null on a fresh draft"


class TestIssueTransmitAcknowledge:
    def test_certificate_issue_transmit_acknowledge_happy_path(
        self, api, officer_headers, auditor_headers
    ):
        """PRD §2.9: "Issuance stamps a certificate with `issued_at` equal to
        the logical clock at that instant and computes `valid_until` as exactly
        30 days after `issued_at`."
        PRD §3.8: "Transmitting a certificate — an officer act permitted
        while the certificate is `ISSUED` or `TRANSMITTED`, and rejected from
        any other state with `ERR_CERTIFICATE_NOT_TRANSMITTABLE` (HTTP 409) —
        does not itself change the certificate's status."
        PRD §3.8: "The row is born `QUEUED`, and the trail is append-only —
        old rows are never rewritten."
        PRD §3.8: "The destination's acknowledgement, recorded by an
        officer, moves a `QUEUED` audit to `ACKNOWLEDGED`, stamps
        `acknowledged_at` with the logical clock, and bubbles the certificate
        upward: the certificate named by the audit's `certificate_id`
        transitions from `ISSUED` to `TRANSMITTED` (a no-op if it is already
        `TRANSMITTED`)."

        Design: Corner/state_machines/certificate_issue_transmit_acknowledge_happy_path
        """
        scenario, cert = create_issued_certificate()
        assert_certificate(cert)
        assert cert["cvi_number"] == "CVI-CA-000001", (
            f"first issuance must mint the example-form number, got {cert['cvi_number']!r}"
        )
        assert cert["issued_at"] == "2026-08-10T00:00:00Z"
        assert cert["valid_until"] == "2026-09-09T00:00:00Z", (
            f"valid_until must be issued_at + 30 days, got {cert['valid_until']!r}"
        )

        # Transmit appends a QUEUED audit WITHOUT changing certificate status.
        resp_t = api.transmit_certificate(cert["id"], {"channel": "XML_GATEWAY"}, officer_headers)
        audit = validate_success(resp_t, 201)
        assert_transmission_audit(audit)
        assert audit["status"] == "QUEUED"
        assert audit["certificate_id"] == cert["id"]
        mid = validate_success(api.get_certificate(cert["id"], auditor_headers))
        assert mid["status"] == "ISSUED", (
            "transmit is not a transition; the certificate must remain ISSUED "
            "until acknowledgement"
        )

        # Acknowledge bubbles the certificate to TRANSMITTED.
        resp_a = api.acknowledge_transmission(audit["id"], officer_headers)
        acked = validate_success(resp_a, 200)
        assert acked["status"] == "ACKNOWLEDGED"
        assert acked["acknowledged_at"] == "2026-08-10T00:00:00Z"
        end = validate_success(api.get_certificate(cert["id"], auditor_headers))
        assert end["status"] == "TRANSMITTED"


class TestProvisionalVsFinalFee:
    def test_cvi_fee_provisional_fee_uses_submit_time_standing(
        self, api, admin_headers, officer_headers
    ):
        """PRD §3.4: "A passing submission computes and stores the
        **provisional issuance fee** in `provisional_fee_cents`."
        PRD §3.4: "The fee is a base of 2500 cents, plus a per-head rate
        multiplied by the certificate's `head_count` — 150 cents for `CATTLE`,
        90 for `SWINE`, 25 for `POULTRY`, 60 for `SHEEP_GOAT`, 200 for `EQUINE`
        — plus a surcharge of 1000 cents when the origin premises'
        `disease_status` is `MONITORED` at the moment of submission, with the
        total capped at 20000 cents (an `ACCREDITED_FREE` premises pays no
        surcharge, and a `QUARANTINE_HOLD` or `INFECTED` premises never reaches
        this point because the disease-hold gate fires first)."

        Design: Difficulty/dual_variant_calc/cvi_fee_provisional_vs_final_on_premises_upgrade
        """
        scenario, cert = create_submitted_certificate()  # 10 head CATTLE, MONITORED
        assert cert["provisional_fee_cents"] == 5000, (
            f"2500 + 150*10 + 1000 MONITORED surcharge = 5000, "
            f"got {cert['provisional_fee_cents']}"
        )

    def test_cvi_fee_final_fee_drops_surcharge_after_accredit(
        self, api, admin_headers, officer_headers
    ):
        """PRD §3.4: "A successful issuance mints the `cvi_number` per
        §2.10, stamps `issued_at` with the logical clock, sets `valid_until`
        thirty days out per §2.9, and computes the **final issuance fee** into
        `final_fee_cents` using the same formula re-evaluated at issuance
        time."
        PRD §3.4: "The provisional-to-final comparison is deliberate: if the
        origin premises moved from `MONITORED` to `ACCREDITED_FREE` between
        submission and issuance, the final fee comes out exactly 1000 cents
        lower than the provisional quote."

        Design: Difficulty/dual_variant_calc/cvi_fee_provisional_vs_final_on_premises_upgrade
        """
        scenario, cert = create_submitted_certificate()
        assert cert["provisional_fee_cents"] == 5000

        # Upgrade the origin premises standing between submit and issue.
        resp_ac = api.accredit_premises(scenario["premises"]["id"], officer_headers)
        assert validate_success(resp_ac, 200)["disease_status"] == "ACCREDITED_FREE"

        resp_i = api.issue_certificate(cert["id"], officer_headers)
        issued = validate_success(resp_i, 200)
        assert_certificate(issued)
        assert issued["final_fee_cents"] == 4000, (
            f"final fee re-evaluates standing at issuance: 2500 + 150*10 + 0 = 4000, "
            f"got {issued['final_fee_cents']}"
        )
        assert issued["final_fee_cents"] == issued["provisional_fee_cents"] - 1000
        assert issued["cvi_number"] == "CVI-CA-000001"
        assert issued["valid_until"] == "2026-09-09T00:00:00Z"


class TestSubmitTwice:
    def test_certificate_submit_twice_rejected(self, api, admin_headers, auditor_headers):
        """PRD §3.4: "Submitting from any state other than `DRAFT` yields
        `ERR_CERTIFICATE_NOT_SUBMITTABLE` (HTTP 409)."

        Design: Corner/state_machines/certificate_submit_twice_rejected
        """
        scenario = setup_standard_scenario()
        cert = create_draft_certificate(
            scenario["premises"]["id"], scenario["vet"]["id"],
            test_record_id=scenario["test"]["id"],
            vaccination_date=DEFAULTS["VACCINATION_DATE"],
        )

        first = validate_success(
            api.submit_certificate(cert["id"], make_vet_headers(scenario["vet"]["id"])), 200
        )
        assert first["status"] == "PENDING_REVIEW"
        # 10 head CATTLE on a MONITORED premises: 2500 + 150*10 + 1000.
        assert first["provisional_fee_cents"] == 5000

        second = api.submit_certificate(cert["id"], make_vet_headers(scenario["vet"]["id"]))
        validate_error(second, ApiErrorId.ERR_CERTIFICATE_NOT_SUBMITTABLE)
        after = validate_success(api.get_certificate(cert["id"], auditor_headers))
        assert after["status"] == "PENDING_REVIEW"


class TestIssueRejectRequirePendingReview:
    def test_certificate_issue_reject_require_pending_review(
        self, api, admin_headers, officer_headers, auditor_headers
    ):
        """PRD §3.4: "Issuance is the `StateVetOfficer`'s act, moving
        `PENDING_REVIEW` to `ISSUED`. Attempting issuance — or rejection — from
        any other state yields `ERR_CERTIFICATE_NOT_PENDING_REVIEW` (HTTP 409)."

        Design: Corner/state_machines/certificate_issue_reject_require_pending_review
        """
        scenario = setup_standard_scenario()
        cert = create_draft_certificate(scenario["premises"]["id"], scenario["vet"]["id"])

        resp_i = api.issue_certificate(cert["id"], officer_headers)
        validate_error(resp_i, ApiErrorId.ERR_CERTIFICATE_NOT_PENDING_REVIEW)

        resp_r = api.reject_certificate(cert["id"], {"reason_code": "INCOMPLETE"}, officer_headers)
        validate_error(resp_r, ApiErrorId.ERR_CERTIFICATE_NOT_PENDING_REVIEW)

        after = validate_success(api.get_certificate(cert["id"], auditor_headers))
        assert after["status"] == "DRAFT"
        assert after["reject_reason"] is None


class TestReviseRequiresRejected:
    def test_certificate_revise_requires_rejected(self, api, admin_headers):
        """PRD §3.3: "Attempting revision from any state other than `REJECTED`
        is rejected with `ERR_CERTIFICATE_NOT_REVISABLE` (HTTP 409)."

        Design: Corner/state_machines/certificate_revise_requires_rejected
        """
        scenario = setup_standard_scenario()
        vet_h = make_vet_headers(scenario["vet"]["id"])
        cert_a = create_draft_certificate(
            scenario["premises"]["id"], scenario["vet"]["id"], head_count=5
        )
        cert_b = create_draft_certificate(
            scenario["premises"]["id"], scenario["vet"]["id"], head_count=5,
            test_record_id=scenario["test"]["id"],
            vaccination_date=DEFAULTS["VACCINATION_DATE"],
        )
        submit_certificate(cert_b["id"], scenario["vet"]["id"])

        resp_a = api.revise_certificate(cert_a["id"], vet_h)
        validate_error(resp_a, ApiErrorId.ERR_CERTIFICATE_NOT_REVISABLE)

        resp_b = api.revise_certificate(cert_b["id"], vet_h)
        validate_error(resp_b, ApiErrorId.ERR_CERTIFICATE_NOT_REVISABLE)


class TestRevisionCycle:
    def test_certificate_revision_cycle_returns_to_draft(
        self, api, admin_headers, officer_headers, auditor_headers
    ):
        """PRD §3.3: "The owning veterinarian may return a `REJECTED`
        certificate to `DRAFT` by revising it; revision clears `reject_reason`
        to null so the corrected draft resubmits cleanly."
        PRD §3.3: "This revision loop — `DRAFT → PENDING_REVIEW → REJECTED →
        DRAFT` — may cycle as often as needed while the certificate remains
        voidable of further progress."

        Design: Difficulty/non_linear_state_machine/certificate_revision_cycle_returns_to_draft
        """
        scenario = setup_standard_scenario()
        cert = create_draft_certificate(
            scenario["premises"]["id"], scenario["vet"]["id"],
            test_record_id=scenario["test"]["id"],
            vaccination_date=DEFAULTS["VACCINATION_DATE"],
        )
        submit_certificate(cert["id"], scenario["vet"]["id"])
        rejected = validate_success(
            api.reject_certificate(cert["id"], {"reason_code": "INCOMPLETE"}, officer_headers),
            200,
        )
        assert rejected["status"] == "REJECTED"
        assert rejected["reject_reason"] == "INCOMPLETE"

        revised = validate_success(
            api.revise_certificate(cert["id"], make_vet_headers(scenario["vet"]["id"])), 200
        )
        assert revised["status"] == "DRAFT", "revision loops the certificate back to DRAFT"
        assert revised["reject_reason"] is None, "revision clears reject_reason to null"

    def test_certificate_revision_cycle_resubmits_with_recomputed_fee(
        self, api, admin_headers, officer_headers
    ):
        """PRD §3.3: "This revision loop — `DRAFT → PENDING_REVIEW → REJECTED →
        DRAFT` — may cycle as often as needed while the certificate remains
        voidable of further progress."
        PRD §3.4: "A passing submission computes and stores the **provisional
        issuance fee** in `provisional_fee_cents`."

        Design: Difficulty/non_linear_state_machine/certificate_revision_cycle_returns_to_draft
        """
        scenario = setup_standard_scenario()
        cert = create_draft_certificate(
            scenario["premises"]["id"], scenario["vet"]["id"],
            test_record_id=scenario["test"]["id"],
            vaccination_date=DEFAULTS["VACCINATION_DATE"],
        )
        submit_certificate(cert["id"], scenario["vet"]["id"])
        api.reject_certificate(cert["id"], {"reason_code": "INCOMPLETE"}, officer_headers)
        api.revise_certificate(cert["id"], make_vet_headers(scenario["vet"]["id"]))

        resubmitted = validate_success(
            api.submit_certificate(cert["id"], make_vet_headers(scenario["vet"]["id"])), 200
        )
        assert resubmitted["status"] == "PENDING_REVIEW", (
            "the loop restores submittability after revision"
        )
        # Premises still MONITORED: 2500 + 150*10 + 1000 recomputed on resubmit.
        assert resubmitted["provisional_fee_cents"] == 5000


class TestRejectRecordsReason:
    def test_certificate_reject_records_reason(self, api, admin_headers, officer_headers):
        """PRD §3.4: "An officer may instead reject a certificate under review,
        recording the request's `reason_code` into `reject_reason`."

        Design: Corner/state_machines/certificate_reject_records_reason
        """
        scenario, cert = create_submitted_certificate(none_matrix=True)
        resp = api.reject_certificate(
            cert["id"], {"reason_code": "INSUFFICIENT_DATA"}, officer_headers
        )
        data = validate_success(resp, 200)
        assert data["status"] == "REJECTED"
        assert data["reject_reason"] == "INSUFFICIENT_DATA", (
            f"reject_reason must copy the request reason_code, got {data['reject_reason']!r}"
        )


class TestVoidRequiresIssuedFamily:
    def test_certificate_void_requires_issued_family(
        self, api, admin_headers, officer_headers, auditor_headers
    ):
        """PRD §3.4: "Certificates in `ISSUED`, `TRANSMITTED`, or
        `ENTRY_BLOCKED` may be voided by an officer, recording the request's
        `reason` into `void_reason`; voiding from any other state is rejected
        with `ERR_CERTIFICATE_NOT_VOIDABLE` (HTTP 409)."

        Design: Corner/state_machines/certificate_void_requires_issued_family
        """
        scenario = setup_standard_scenario(none_matrix=True)
        cert_a = create_draft_certificate(
            scenario["premises"]["id"], scenario["vet"]["id"], head_count=5
        )
        cert_b = create_draft_certificate(
            scenario["premises"]["id"], scenario["vet"]["id"], head_count=5
        )
        submit_certificate(cert_b["id"], scenario["vet"]["id"])

        resp_a = api.void_certificate(cert_a["id"], {"reason": "TOO_EARLY"}, officer_headers)
        validate_error(resp_a, ApiErrorId.ERR_CERTIFICATE_NOT_VOIDABLE)
        resp_b = api.void_certificate(cert_b["id"], {"reason": "TOO_EARLY"}, officer_headers)
        validate_error(resp_b, ApiErrorId.ERR_CERTIFICATE_NOT_VOIDABLE)

        after_a = validate_success(api.get_certificate(cert_a["id"], auditor_headers))
        after_b = validate_success(api.get_certificate(cert_b["id"], auditor_headers))
        assert after_a["status"] == "DRAFT" and after_a["void_reason"] is None
        assert after_b["status"] == "PENDING_REVIEW" and after_b["void_reason"] is None


class TestTransmitRequiresIssued:
    def test_certificate_transmit_requires_issued(
        self, api, admin_headers, officer_headers, auditor_headers
    ):
        """PRD §3.8: "Transmitting a certificate — an officer act permitted
        while the certificate is `ISSUED` or `TRANSMITTED`, and rejected from
        any other state with `ERR_CERTIFICATE_NOT_TRANSMITTABLE` (HTTP 409) —
        does not itself change the certificate's status."

        Design: Corner/state_machines/certificate_transmit_requires_issued
        """
        scenario = setup_standard_scenario(none_matrix=True)
        cert_a = create_draft_certificate(
            scenario["premises"]["id"], scenario["vet"]["id"], head_count=5
        )
        cert_b = create_draft_certificate(
            scenario["premises"]["id"], scenario["vet"]["id"], head_count=5
        )
        submit_certificate(cert_b["id"], scenario["vet"]["id"])

        resp_a = api.transmit_certificate(cert_a["id"], {"channel": "EMAIL"}, officer_headers)
        validate_error(resp_a, ApiErrorId.ERR_CERTIFICATE_NOT_TRANSMITTABLE)
        resp_b = api.transmit_certificate(cert_b["id"], {"channel": "EMAIL"}, officer_headers)
        validate_error(resp_b, ApiErrorId.ERR_CERTIFICATE_NOT_TRANSMITTABLE)

        data, meta = validate_paginated(
            api.list_transmissions_for_certificate(cert_a["id"], auditor_headers)
        )
        assert meta["total_count"] == 0 and data == [], (
            "a failed transmit must not append an audit row"
        )


class TestVoidTerminalLockdown:
    def test_certificate_void_terminal_lockdown(
        self, api, admin_headers, officer_headers, auditor_headers
    ):
        """PRD §3.4: "`VOID` and `LAPSED` are terminal; a lapsed
        certificate — one the logical clock has moved strictly past
        `valid_until`, materialized lazily per §2.4 — is also terminal, and
        when an `ENTRY_BLOCKED` certificate lapses its `pre_block_status` is
        cleared to null as part of the transition."
        PRD §3.4: "Submitting from any state other than `DRAFT` yields
        `ERR_CERTIFICATE_NOT_SUBMITTABLE` (HTTP 409)."
        PRD §3.4: "Attempting issuance — or rejection — from any other state
        yields `ERR_CERTIFICATE_NOT_PENDING_REVIEW` (HTTP 409)."
        PRD §3.3: "Attempting revision from any state other than `REJECTED` is
        rejected with `ERR_CERTIFICATE_NOT_REVISABLE` (HTTP 409)."

        Design: Corner/state_machines/certificate_void_terminal_lockdown
        """
        scenario, cert = create_issued_certificate()
        voided = validate_success(
            api.void_certificate(cert["id"], {"reason": "DISEASE_SUSPECT"}, officer_headers),
            200,
        )
        assert voided["status"] == "VOID"
        assert voided["void_reason"] == "DISEASE_SUSPECT"

        vet_h = make_vet_headers(scenario["vet"]["id"])
        validate_error(
            api.submit_certificate(cert["id"], vet_h),
            ApiErrorId.ERR_CERTIFICATE_NOT_SUBMITTABLE,
        )
        validate_error(
            api.issue_certificate(cert["id"], officer_headers),
            ApiErrorId.ERR_CERTIFICATE_NOT_PENDING_REVIEW,
        )
        validate_error(
            api.transmit_certificate(cert["id"], {"channel": "PORTAL"}, officer_headers),
            ApiErrorId.ERR_CERTIFICATE_NOT_TRANSMITTABLE,
        )
        validate_error(
            api.void_certificate(cert["id"], {"reason": "AGAIN"}, officer_headers),
            ApiErrorId.ERR_CERTIFICATE_NOT_VOIDABLE,
        )
        validate_error(
            api.revise_certificate(cert["id"], vet_h),
            ApiErrorId.ERR_CERTIFICATE_NOT_REVISABLE,
        )


class TestLapseBoundary:
    def test_certificate_lapses_only_after_valid_until(
        self, api, admin_headers, auditor_headers
    ):
        """PRD §2.9: "A certificate lapses only when the logical clock is
        strictly later than `valid_until`; sitting exactly at the boundary does
        not lapse it."
        PRD §2.4: "the state change materializes on the first read or write
        that touches the record after the logical clock has advanced beyond the
        threshold — a certificate read evaluates the `LAPSED` check before
        responding".

        Design: Corner/state_machines/certificate_lapses_only_after_valid_until
        """
        scenario, cert = create_issued_certificate()
        assert cert["valid_until"] == "2026-09-09T00:00:00Z"

        set_clock("2026-09-09T00:00:00Z")  # exactly at valid_until
        at_boundary = validate_success(api.get_certificate(cert["id"], auditor_headers))
        assert at_boundary["status"] == "ISSUED", (
            "equality with valid_until must NOT lapse the certificate"
        )
        assert at_boundary["valid_until"] == "2026-09-09T00:00:00Z"

        set_clock("2026-09-10T00:00:00Z")  # strictly past valid_until
        after = validate_success(api.get_certificate(cert["id"], auditor_headers))
        assert after["status"] == "LAPSED", (
            "the first read after the clock passes valid_until materializes LAPSED"
        )


class TestLapsedTerminalLockdown:
    def test_certificate_lapsed_terminal_lockdown(
        self, api, admin_headers, officer_headers, auditor_headers
    ):
        """PRD §3.4: "`VOID` and `LAPSED` are terminal; a lapsed
        certificate — one the logical clock has moved strictly past
        `valid_until`, materialized lazily per §2.4 — is also terminal, and
        when an `ENTRY_BLOCKED` certificate lapses its `pre_block_status` is
        cleared to null as part of the transition."
        PRD §3.5: "the permit must be `REQUESTED` and its backing certificate
        must be `ISSUED` or `TRANSMITTED` — either failure is
        `ERR_PERMIT_NOT_ISSUABLE` (HTTP 409)".
        PRD §3.8: "an officer act permitted while the certificate is `ISSUED`
        or `TRANSMITTED`, and rejected from any other state with
        `ERR_CERTIFICATE_NOT_TRANSMITTABLE` (HTTP 409)".

        Design: Corner/state_machines/certificate_lapsed_terminal_lockdown
        """
        scenario, cert = create_issued_certificate()
        permit = validate_success(
            api.create_movement_permit(
                {
                    "certificate_id": cert["id"],
                    "allocated_head_count": 10,
                    "valid_from": "2026-08-11T00:00:00Z",
                    "valid_until": "2026-09-08T00:00:00Z",
                },
                make_vet_headers(scenario["vet"]["id"]),
            ),
            201,
        )

        set_clock("2026-09-10T00:00:00Z")  # past valid_until 2026-09-09

        resp_p = api.issue_movement_permit(permit["id"], officer_headers)
        validate_error(resp_p, ApiErrorId.ERR_PERMIT_NOT_ISSUABLE)

        resp_t = api.transmit_certificate(cert["id"], {"channel": "EMAIL"}, officer_headers)
        validate_error(resp_t, ApiErrorId.ERR_CERTIFICATE_NOT_TRANSMITTABLE)

        resp_v = api.void_certificate(cert["id"], {"reason": "LATE"}, officer_headers)
        validate_error(resp_v, ApiErrorId.ERR_CERTIFICATE_NOT_VOIDABLE)

        final = validate_success(api.get_certificate(cert["id"], auditor_headers))
        assert final["status"] == "LAPSED"
