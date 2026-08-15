"""Hauler permitting cycle, pump manifests, and disposal reconciliation."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_interceptor,
    commission_interceptor,
    create_active_interceptor,
    create_and_permit_hauler,
    create_blockage,
    create_disposal_record,
    create_establishment,
    create_hauler,
    create_interceptor,
    create_manifest,
    create_pump_manifest_payload,
    create_variance,
    get_establishment,
    get_success_data,
    make_fse_contact_headers,
    make_hauler_admin_headers,
    set_clock,
    setup_pumping_chain,
    setup_submitted_manifest,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


class TestHaulerLifecycle:
    def test_hauler_permit_suspension_cycle(self, api):
        """PRD: "A suspended hauler may be reinstated by a
        `ComplianceOfficer`, returning to `PERMITTED` with its
        `mismatch_count` reset to zero."
        PRD: "Rejection carries teeth when the reason is `DISPOSAL_MISMATCH`:
        the hauler's `mismatch_count` increments by one"

        Design: Difficulty/non_linear_state_machine/hauler_permit_suspension_cycle
        """
        est, interceptor, hauler, manifest = setup_submitted_manifest(
            pump_date="2026-08-01T00:00:00Z", pumped_volume_gal=1500,
            establishment_name="Cycle Cafe", hauler_name="Cycle Haul",
            permit_number="PN-CYC")
        rejected = validate_success(api.reject_pump_manifest(
            manifest["id"], "DISPOSAL_MISMATCH", INSPECTOR))
        assert rejected["status"] == "REJECTED"
        assert rejected["reject_reason"] == "DISPOSAL_MISMATCH"
        mid = validate_success(api.get_hauler(hauler["id"], ADMIN))
        assert mid["mismatch_count"] == 1

        suspended = validate_success(api.suspend_hauler(hauler["id"], OFFICER))
        assert suspended["status"] == "SUSPENDED"
        reinstated = validate_success(api.reinstate_hauler(hauler["id"], OFFICER))
        assert reinstated["status"] == "PERMITTED", (
            "Hauler traversed APPLIED -> PERMITTED -> SUSPENDED -> PERMITTED"
        )
        assert reinstated["mismatch_count"] == 0, (
            "Reinstatement resets mismatch_count to zero"
        )

    def test_hauler_suspend_then_reinstate_allows_filing_again(self, api):
        """PRD: "The hauler must currently be `PERMITTED` — filing under any
        other status is rejected with `ERR_HAULER_NOT_PERMITTED` (HTTP 409)"
        PRD: "A suspended hauler may be reinstated by a `ComplianceOfficer`,
        returning to `PERMITTED` with its `mismatch_count` reset to zero."

        Design: Difficulty/non_linear_state_machine/hauler_permit_suspension_cycle
        """
        est, interceptor, hauler, manifest = setup_submitted_manifest(
            establishment_name="Cycle Annex", hauler_name="Cycle Haul 2",
            permit_number="PN-CYC2")
        get_success_data(api.suspend_hauler(hauler["id"], OFFICER))
        # The suspension cascade rejects the pre-existing SUBMITTED manifest
        # (PRD: "suspension cascades immediately"), so the disposal gate is
        # exercised against a manifest submitted *during* the suspension —
        # submission gates only interceptor ACTIVE (PRD section 2.9 item 9
        # scopes hauler PERMITTED to verification and disposal filing), so
        # this manifest is still SUBMITTED when the disposal is attempted.
        manifest2 = create_manifest(est["id"], interceptor["id"], hauler["id"],
                                    pump_date="2026-08-05T00:00:00Z")
        resp = api.create_disposal_record(
            {"hauler_id": hauler["id"], "manifest_id": manifest2["id"],
             "disposed_volume_gal": 1000, "disposal_site_name": "Site X",
             "disposed_at": "2026-08-05T12:00:00Z"},
            make_hauler_admin_headers(hauler["id"]))
        validate_error(resp, ApiErrorId.ERR_HAULER_NOT_PERMITTED, 409)

        # Reinstatement returns the hauler to PERMITTED, and filing against
        # the still-SUBMITTED manifest now succeeds.
        get_success_data(api.reinstate_hauler(hauler["id"], OFFICER))
        disposal = create_disposal_record(hauler["id"], manifest2["id"])
        assert disposal["manifest_id"] == manifest2["id"]

    def test_revoked_hauler_cannot_reinstate(self, api):
        """PRD: "Finally, a `ComplianceOfficer` may revoke the permit of a
        hauler in either `PERMITTED` or `SUSPENDED`, moving it to the terminal
        `REVOKED` status."

        Design: Corner/state_machines/c_revoked_hauler_cannot_reinstate
        """
        hauler = create_and_permit_hauler(name="Terminal Haul",
                                          permit_number="PN-TERM")
        revoked = validate_success(api.revoke_hauler(hauler["id"], OFFICER))
        assert revoked["status"] == "REVOKED"

        resp = api.reinstate_hauler(hauler["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        current = validate_success(api.get_hauler(hauler["id"], ADMIN))
        assert current["status"] == "REVOKED"

    def test_expired_insurance_blocks_permit(self, api):
        """PRD: "Permitting, also by a `ProgramAdmin`, requires
        `insurance_expires_on` to lie strictly after the current logical clock
        — insurance that has already lapsed, or that lapses at exactly the
        current instant, fails with `ERR_INSURANCE_EXPIRED` (HTTP 422) — and
        moves the hauler from `APPLIED` to `PERMITTED`."
        PRD: "Before any clock-setting call has been made, the logical clock
        reads exactly 2026-08-01T00:00:00Z."

        Design: Corner/validations/c_expired_insurance_blocks_permit
        """
        hauler = create_hauler(name="Uninsured Haul", permit_number="PN-EXP",
                               insurance_expires_on="2026-07-01T00:00:00Z")
        assert hauler["status"] == "APPLIED"
        resp = api.permit_hauler(hauler["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INSURANCE_EXPIRED, 422)
        current = validate_success(api.get_hauler(hauler["id"], ADMIN))
        assert current["status"] == "APPLIED"


class TestManifestCreation:
    def test_initial_states_on_create(self, api):
        """PRD: "the hauler starts in `APPLIED` status with its
        `mismatch_count` at zero"
        PRD: "A newly proposed interceptor sits in `PROPOSED` status."
        PRD: "A new request starts in `UNDER_REVIEW`."
        PRD: "the event starts in `REPORTED` status"
        PRD: "The manifest opens in `SUBMITTED` status"

        Design: Corner/state_machines/c_initial_states_on_create
        """
        est = create_establishment(name="Initial Inn", street_address="8 H St",
                                   seating_capacity=200, fryer_count=3,
                                   cuisine_profile="HIGH_GREASE")
        hauler = create_hauler(name="Init Haul", permit_number="PN-INIT")
        assert hauler["status"] == "APPLIED"
        assert hauler["mismatch_count"] == 0

        interceptor = create_interceptor(est["id"], nominal_capacity_gal=600)
        assert interceptor["status"] == "PROPOSED"
        approve_interceptor(interceptor["id"])
        commission_interceptor(interceptor["id"])
        get_success_data(api.permit_hauler(hauler["id"], ADMIN))

        variance = create_variance(est["id"], scope="INTERCEPTOR_SIZE",
                                   justification="tight space")
        assert variance["status"] == "UNDER_REVIEW"

        blockage = create_blockage("5th Ave line")
        assert blockage["status"] == "REPORTED"

        manifest = create_manifest(est["id"], interceptor["id"], hauler["id"])
        assert manifest["status"] == "SUBMITTED"

    def test_manifest_create_on_proposed_interceptor_rejected(self, api):
        """PRD: "Only an `ACTIVE` interceptor may be named on a new pump
        manifest; submitting against one that is still `PROPOSED`, or merely
        `APPROVED`, is rejected with `ERR_INTERCEPTOR_NOT_ACTIVE` (HTTP
        409)."

        Design: Corner/validations/c_manifest_create_on_proposed_interceptor_rejected
        """
        est = create_establishment(name="Proposed Place",
                                   street_address="21 R St")
        interceptor = create_interceptor(est["id"], nominal_capacity_gal=50)
        hauler = create_and_permit_hauler(name="Prop Haul",
                                          permit_number="PN-PRO")
        resp = api.create_pump_manifest(
            create_pump_manifest_payload(est["id"], interceptor["id"],
                                         hauler["id"], pumped_volume_gal=100),
            make_fse_contact_headers(est["id"]))
        validate_error(resp, ApiErrorId.ERR_INTERCEPTOR_NOT_ACTIVE, 409)

    def test_duplicate_manifest_same_day_rejected(self, api):
        """PRD: "at most one manifest may exist for a given interceptor and
        `pump_date` — a duplicate is rejected with `ERR_DUPLICATE_MANIFEST`
        (HTTP 409)."
        PRD: "The manifest opens in `SUBMITTED` status"

        Design: Corner/validations/c_duplicate_manifest_same_day_rejected
        """
        est, interceptor, hauler = setup_pumping_chain(
            establishment_name="Dup Diner", hauler_name="Dup Haul",
            permit_number="PN-DUP")
        fse = make_fse_contact_headers(est["id"])
        m1 = create_manifest(est["id"], interceptor["id"], hauler["id"],
                             pump_date="2026-08-01T00:00:00Z")
        assert m1["status"] == "SUBMITTED"

        resp = api.create_pump_manifest(
            create_pump_manifest_payload(est["id"], interceptor["id"],
                                         hauler["id"],
                                         pump_date="2026-08-01T00:00:00Z",
                                         pumped_volume_gal=1200),
            fse)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_MANIFEST, 409)

        m2 = validate_success(api.create_pump_manifest(
            create_pump_manifest_payload(est["id"], interceptor["id"],
                                         hauler["id"],
                                         pump_date="2026-08-02T00:00:00Z",
                                         pumped_volume_gal=1200),
            fse), 201)
        assert m2["status"] == "SUBMITTED", (
            "Same interceptor on a different pump_date is accepted"
        )


class TestManifestVerification:
    def test_verify_without_disposal_record_rejected(self, api):
        """PRD: "a disposal record must exist for the manifest
        (`ERR_DISPOSAL_RECORD_MISSING`, HTTP 422)"

        Design: Corner/validations/c_verify_without_disposal_record_rejected
        """
        est, interceptor, hauler, manifest = setup_submitted_manifest(
            establishment_name="NoDisposal Nook", hauler_name="ND Haul",
            permit_number="PN-ND")
        resp = api.verify_pump_manifest(manifest["id"], INSPECTOR)
        validate_error(resp, ApiErrorId.ERR_DISPOSAL_RECORD_MISSING, 422)
        current = validate_success(api.get_pump_manifest(manifest["id"],
                                                         INSPECTOR))
        assert current["status"] == "SUBMITTED"

    def test_interceptor_mismatch_on_verify_rejected(self, api):
        """PRD: "the named interceptor must belong to the manifest's
        establishment (`ERR_INTERCEPTOR_MISMATCH`, HTTP 422)"

        Design: Corner/validations/c_interceptor_mismatch_on_verify_rejected
        """
        ea = create_establishment(name="Mis A", street_address="24 U St",
                                  seating_capacity=200, fryer_count=3,
                                  cuisine_profile="HIGH_GREASE")
        ia = create_active_interceptor(ea["id"], 600)
        eb = create_establishment(name="Mis B", street_address="25 U St")
        ib = create_active_interceptor(eb["id"], 50)
        hauler = create_and_permit_hauler(name="Mis Haul",
                                          permit_number="PN-MIS")
        manifest = create_manifest(ea["id"], ib["id"], hauler["id"])
        create_disposal_record(hauler["id"], manifest["id"])

        resp = api.verify_pump_manifest(manifest["id"], INSPECTOR)
        validate_error(resp, ApiErrorId.ERR_INTERCEPTOR_MISMATCH, 422)
        current = validate_success(api.get_pump_manifest(manifest["id"],
                                                         INSPECTOR))
        assert current["status"] == "SUBMITTED"

    def test_disposal_tolerance_exactly_five_percent_passes(self, api):
        """PRD: "the disposal volume must reconcile with the pumped volume —
        the absolute difference between `disposed_volume_gal` and
        `pumped_volume_gal`, divided by `pumped_volume_gal`, must not exceed
        0.05, so a ratio of exactly 0.05 passes and only a strictly larger
        ratio is rejected as `ERR_DISPOSAL_DISCREPANCY` (HTTP 422)."

        Design: Corner/calculations/c_disposal_tolerance_exactly_five_percent_passes
        """
        est, interceptor, hauler = setup_pumping_chain(
            establishment_name="Tolerance Tavern", hauler_name="Tol Haul",
            permit_number="PN-TOL")
        m1 = create_manifest(est["id"], interceptor["id"], hauler["id"],
                             pump_date="2026-08-01T00:00:00Z",
                             pumped_volume_gal=2000)
        create_disposal_record(hauler["id"], m1["id"], disposed_volume_gal=2100,
                               disposed_at="2026-08-01T12:00:00Z")
        m2 = create_manifest(est["id"], interceptor["id"], hauler["id"],
                             pump_date="2026-08-02T00:00:00Z",
                             pumped_volume_gal=2000)
        create_disposal_record(hauler["id"], m2["id"], disposed_volume_gal=2101,
                               disposed_at="2026-08-02T12:00:00Z")

        # |2100 - 2000| / 2000 == 0.05 exactly -> passes.
        verified = validate_success(api.verify_pump_manifest(m1["id"], INSPECTOR))
        assert verified["status"] == "VERIFIED", "ratio exactly 0.05 passes"

        # |2101 - 2000| / 2000 == 0.0505 > 0.05 -> rejected.
        resp = api.verify_pump_manifest(m2["id"], INSPECTOR)
        validate_error(resp, ApiErrorId.ERR_DISPOSAL_DISCREPANCY, 422)
        current = validate_success(api.get_pump_manifest(m2["id"], INSPECTOR))
        assert current["status"] == "SUBMITTED"

    def test_disposal_tolerance_within_passes(self, api):
        """PRD: "the absolute difference between `disposed_volume_gal` and
        `pumped_volume_gal`, divided by `pumped_volume_gal`, must not exceed
        0.05, so a ratio of exactly 0.05 passes and only a strictly larger
        ratio is rejected as `ERR_DISPOSAL_DISCREPANCY` (HTTP 422). A verified
        manifest moves to `VERIFIED`"

        Design: Corner/calculations/c_disposal_tolerance_exactly_five_percent_passes
        """
        est, interceptor, hauler = setup_pumping_chain(
            establishment_name="Tolerance Annex", hauler_name="Tol Haul 2",
            permit_number="PN-TOL2")
        manifest = create_manifest(est["id"], interceptor["id"], hauler["id"],
                                   pumped_volume_gal=2000)
        # |2050 - 2000| / 2000 == 0.025 < 0.05 -> passes.
        create_disposal_record(hauler["id"], manifest["id"],
                               disposed_volume_gal=2050)
        verified = validate_success(api.verify_pump_manifest(manifest["id"],
                                                             INSPECTOR))
        assert verified["status"] == "VERIFIED"

    def test_second_disposal_for_manifest_rejected(self, api):
        """PRD: "at most one disposal record may exist per manifest, enforced
        with `ERR_DUPLICATE_DISPOSAL` (HTTP 409)."

        Design: Corner/validations/c_second_disposal_for_manifest_rejected
        """
        est, interceptor, hauler, manifest = setup_submitted_manifest(
            establishment_name="DupDisp Diner", hauler_name="DD Haul",
            permit_number="PN-DD")
        create_disposal_record(hauler["id"], manifest["id"],
                               disposal_site_name="Site E")
        resp = api.create_disposal_record(
            {"hauler_id": hauler["id"], "manifest_id": manifest["id"],
             "disposed_volume_gal": 500, "disposal_site_name": "Site E",
             "disposed_at": "2026-08-01T13:00:00Z"},
            make_hauler_admin_headers(hauler["id"]))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_DISPOSAL, 409)
