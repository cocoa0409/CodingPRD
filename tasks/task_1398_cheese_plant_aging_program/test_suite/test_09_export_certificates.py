"""Export certification: issuance gates (plant listing, reconciled run),
per-run uniqueness, and terminal-state lockdown."""
from test_helpers import (
    ApiErrorId,
    assert_export_certificate,
    create_allocation_order,
    create_cut_wrap_run,
    create_export_certificate,
    make_released_batch,
    reconcile_run,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["plant_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def _setup_requested_cert(api, export_listed, license_number, reconcile=True):
    """Full chain: released MUENSTER batch -> order -> cut-wrap run
    (optionally reconciled) -> REQUESTED export certificate."""
    ctx = make_released_batch(
        variety="MUENSTER", wheels_produced=4, green_weight_kg=500.0,
        age_to="2026-08-25T00:00:00Z", export_listed=export_listed,
    )
    order = create_allocation_order(
        ctx["batch_id"], channel="PRIVATE_LABEL", customer_name="Acme",
        wheels_requested=2, priority=1,
    )
    run = create_cut_wrap_run(
        order["id"], wheels_in=2, finished_case_weight_kg=5.5, trim_waste_kg=0.5
    )
    if reconcile:
        reconcile_run(run["id"])
    cert = create_export_certificate(
        run["id"], destination_country="DE", consignee="Berlin Imports"
    )
    return ctx, run, cert


class TestIssuanceGates:
    def test_export_issue_gated_by_plant_listing_and_run_state(self, api):
        """PRD §3.9: "Issuance applies both gates: the plant's `export_listed`
        must be `true`, failing `ERR_PLANT_NOT_EXPORT_LISTED`, and the run must
        be `RECONCILED`, failing `ERR_RUN_NOT_RECONCILED`."
        PRD §3.1: "the `export_listed` flag, which records whether the plant
        appears on the federal export-eligible regulatory listing, defaults to
        `false` when omitted, and a later plant update may flip it — each such
        update increments the plant's `version` by one."

        Design: Difficulty/cross_entity_state_dependency/export_issue_gated_by_plant_listing_and_run_state
        """
        ctx, run, cert = _setup_requested_cert(api, export_listed=False,
                                               license_number="WI-113")
        resp = api.issue_export_certificate(cert["id"], COMPLIANCE)
        validate_error(resp, ApiErrorId.ERR_PLANT_NOT_EXPORT_LISTED, 409)
        # Flipping the plant flag re-opens the gate for the same certificate.
        validate_success(api.update_plant(ctx["plant"]["id"], {"export_listed": True}, ADMIN))
        issued = validate_success(api.issue_export_certificate(cert["id"], COMPLIANCE))
        assert issued["status"] == "ISSUED", (
            "after the plant flag flips, the same certificate issues with no "
            "certificate-side mutation in between"
        )
        assert_export_certificate(issued)

    def test_export_issue_requires_reconciled_run(self, api):
        """PRD §3.9: "Issuance applies both gates: the plant's `export_listed`
        must be `true`, failing `ERR_PLANT_NOT_EXPORT_LISTED`, and the run must
        be `RECONCILED`, failing `ERR_RUN_NOT_RECONCILED`. Issuing mints the
        server-generated `certificate_number`, stamps `issued_at` from the
        logical clock, and moves the certificate `REQUESTED` → `ISSUED`."

        Design: Difficulty/cross_entity_state_dependency/export_issue_gated_by_plant_listing_and_run_state
        """
        ctx, run, cert = _setup_requested_cert(api, export_listed=True,
                                               license_number="WI-113B",
                                               reconcile=False)
        resp = api.issue_export_certificate(cert["id"], COMPLIANCE)
        validate_error(resp, ApiErrorId.ERR_RUN_NOT_RECONCILED, 409)
        cert_now = validate_success(api.get_export_certificate(cert["id"], COMPLIANCE))
        assert cert_now["status"] == "REQUESTED", (
            "a rejected issuance leaves the certificate REQUESTED"
        )


class TestCertificateUniquenessAndLockdown:
    def test_error_cert_duplicate_active_per_run(self, api):
        """PRD §3.9: "Only one active certificate may exist per run: a second
        request while a certificate for the same run sits in `REQUESTED` or
        `ISSUED` fails with `ERR_CERT_ALREADY_EXISTS`."

        Design: Corner/errors/error_cert_duplicate_active_per_run
        """
        ctx, run, cert = _setup_requested_cert(api, export_listed=True,
                                               license_number="WI-254")
        validate_success(api.issue_export_certificate(cert["id"], COMPLIANCE))
        resp = api.create_export_certificate(
            {"cut_wrap_run_id": run["id"], "destination_country": "JP",
             "consignee": "Tokyo Foods"},
            COMPLIANCE,
        )
        validate_error(resp, ApiErrorId.ERR_CERT_ALREADY_EXISTS, 409)

    def test_export_certificate_revoke_terminal_lockdown(self, api):
        """PRD §3.9: "A requested certificate may instead be denied, moving
        `REQUESTED` → terminal `DENIED`, and an issued certificate may later be
        revoked, moving `ISSUED` → terminal `REVOKED`. Because uniqueness
        covers only active certificates, a fresh request may follow a denial or
        a revocation. Every terminal transition attempted from the wrong state
        — issuing a denied certificate, revoking one never issued, and the like
        — fails with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/export_certificate_revoke_terminal_lockdown
        """
        ctx, run, cert = _setup_requested_cert(api, export_listed=True,
                                               license_number="WI-218")
        validate_success(api.issue_export_certificate(cert["id"], COMPLIANCE))
        revoked = validate_success(api.revoke_export_certificate(cert["id"], COMPLIANCE))
        assert revoked["status"] == "REVOKED"
        resp = api.issue_export_certificate(cert["id"], COMPLIANCE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
