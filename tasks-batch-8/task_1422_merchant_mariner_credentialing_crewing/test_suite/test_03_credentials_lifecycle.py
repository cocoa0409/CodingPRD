"""Credential issuance, renewal cycle, prerequisite chains, revocation, and
the clock-driven expiry cascade."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    confirm_assignment,
    create_mariner,
    issue_credential,
    issue_medical_certificate,
    make_mariner_headers,
    propose_assignment,
    record_negative_drug_test,
    set_clock,
    setup_active_vessel_with_slot,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["fleet_admin_headers"]
OFFICER = TEST_USERS["officer_headers"]
CREWING = TEST_USERS["crewing_headers"]


class TestCredentialRenewalCycle:

    def _mariner_with_credential(self, expiry="2027-01-01T00:00:00Z"):
        mariner = create_mariner()
        credential = issue_credential(mariner["id"], expiry_date=expiry)
        return mariner, credential

    def test_renewal_deny_loops_back_to_valid_with_old_dates(self):
        """PRD section 3.3: "Denying a renewal — with an optional `reason` —
        also returns the credential to `VALID`, but keeps the old dates
        unchanged, so a credential whose `expiry_date` has already passed is
        simply re-expired by the next clock sweep."
        PRD section 3.3: "The renewal loop runs `VALID` → `RENEWAL_PENDING` →
        `VALID`."

        Design: Difficulty/non_linear_state_machine/credential_renewal_cycle_loops
        """
        mariner, credential = self._mariner_with_credential()
        # Mariner self-service submits the renewal.
        pending = validate_success(
            api_client.submit_credential_renewal(
                mariner["id"], credential["id"],
                make_mariner_headers(mariner["id"])))
        assert pending["status"] == "RENEWAL_PENDING"

        denied = validate_success(
            api_client.deny_credential_renewal(
                mariner["id"], credential["id"],
                {"reason": "paperwork incomplete"}, OFFICER))
        assert denied["status"] == "VALID", "deny loops back to VALID"
        assert denied["renewal_count"] == 0, "deny must not count as a renewal"
        assert denied["expiry_date"] == "2027-01-01T00:00:00Z", \
            f"deny keeps the old dates, got {denied['expiry_date']}"
        assert denied["issue_date"] == "2026-01-01T00:00:00Z"

    def test_renewal_approve_then_late_renewal_after_expiry_sweep(self):
        """PRD section 3.3: "Approval replaces `issue_date` with
        `new_issue_date` and `expiry_date` with `new_expiry_date`, increments
        `renewal_count` by one"
        PRD section 3.3: "Late renewal from `EXPIRED` is reachable only within
        the 180-day grace window, before the sweep moves the credential to
        `LAPSED`."
        PRD section 2.6: "Credentials in `VALID`, `RENEWAL_PENDING`, or
        `SUSPENDED_PREREQ` whose `expiry_date` is strictly earlier than the
        new clock become `EXPIRED`."

        Design: Difficulty/non_linear_state_machine/credential_renewal_cycle_loops
        """
        mariner, credential = self._mariner_with_credential()
        cid = credential["id"]

        # Loop 1: submit + approve with replacement dates.
        validate_success(
            api_client.submit_credential_renewal(mariner["id"], cid, OFFICER))
        approved = validate_success(
            api_client.approve_credential_renewal(
                mariner["id"], cid,
                {"new_issue_date": "2026-08-02T00:00:00Z",
                 "new_expiry_date": "2031-08-02T00:00:00Z"}, OFFICER))
        assert approved["status"] == "VALID"
        assert approved["renewal_count"] == 1
        assert approved["expiry_date"] == "2031-08-02T00:00:00Z"

        # Clock sweep past the new expiry (30 days past: EXPIRED, not LAPSED).
        set_clock("2031-09-01T00:00:00Z")
        swept = validate_success(api_client.get_credential(cid, OFFICER))
        assert swept["status"] == "EXPIRED", \
            f"expiry 2031-08-02 < clock 2031-09-01, got {swept['status']}"

        # Late renewal from EXPIRED inside the 180-day grace, then approve.
        late = validate_success(
            api_client.submit_credential_renewal(mariner["id"], cid, OFFICER))
        assert late["status"] == "RENEWAL_PENDING", \
            "EXPIRED -> RENEWAL_PENDING late-renewal edge"
        final = validate_success(
            api_client.approve_credential_renewal(
                mariner["id"], cid,
                {"new_issue_date": "2031-09-02T00:00:00Z",
                 "new_expiry_date": "2032-09-02T00:00:00Z"}, OFFICER))
        assert final["status"] == "VALID"
        assert final["renewal_count"] == 2
        assert final["expiry_date"] == "2032-09-02T00:00:00Z"


class TestCredentialPreconditionErrors:

    def test_credential_prerequisite_invalid_rejected(self):
        """PRD section 3.3: "The prerequisite, when supplied, must belong to
        the same mariner and must itself be `VALID` at issuance, else the
        issuance is rejected with `ERR_ENDORSEMENT_PREREQUISITE_INVALID`."

        Design: Corner/state_machines/credential_prerequisite_invalid_rejected
        """
        mariner_a = create_mariner()
        cred_a = issue_credential(mariner_a["id"])
        validate_success(
            api_client.revoke_credential(
                mariner_a["id"], cred_a["id"],
                {"reason": "regulatory action"}, OFFICER))

        mariner_b = create_mariner()
        cred_b = issue_credential(mariner_b["id"])

        payload_base = {
            "credential_type": "TANKER", "endorsement_code": "TANKER_PIC",
            "issue_date": "2026-08-02T00:00:00Z",
            "expiry_date": "2031-08-02T00:00:00Z",
        }
        # Prerequisite REVOKED.
        resp = api_client.create_credential(
            mariner_a["id"],
            {**payload_base, "prerequisite_credential_id": cred_a["id"]},
            OFFICER)
        validate_error(resp, ApiErrorId.ERR_ENDORSEMENT_PREREQUISITE_INVALID)

        # Prerequisite belongs to another mariner.
        resp = api_client.create_credential(
            mariner_a["id"],
            {**payload_base, "prerequisite_credential_id": cred_b["id"]},
            OFFICER)
        validate_error(resp, ApiErrorId.ERR_ENDORSEMENT_PREREQUISITE_INVALID)

    def test_approve_renewal_without_submit_rejected(self):
        """PRD section 3.3: "Approving a renewal — a `CredentialingOfficer`
        capability — requires the credential to be `RENEWAL_PENDING` (else
        `ERR_RENEWAL_NOT_PENDING`)"

        Design: Corner/errors/approve_renewal_without_submit_rejected
        """
        mariner = create_mariner()
        credential = issue_credential(mariner["id"])
        resp = api_client.approve_credential_renewal(
            mariner["id"], credential["id"],
            {"new_issue_date": "2026-08-02T00:00:00Z",
             "new_expiry_date": "2031-08-02T00:00:00Z"}, OFFICER)
        validate_error(resp, ApiErrorId.ERR_RENEWAL_NOT_PENDING)

    def test_submit_renewal_on_revoked_rejected(self):
        """PRD section 3.3: "The mariner themself, or a
        `CredentialingOfficer`, submits a renewal for a credential in `VALID`
        or `EXPIRED` status — anything else is `ERR_CREDENTIAL_NOT_RENEWABLE`."

        Design: Corner/errors/submit_renewal_on_revoked_rejected
        """
        mariner = create_mariner()
        credential = issue_credential(mariner["id"])
        revoked = validate_success(
            api_client.revoke_credential(
                mariner["id"], credential["id"],
                {"reason": "fraudulent sea time"}, OFFICER))
        assert revoked["status"] == "REVOKED"

        resp = api_client.submit_credential_renewal(
            mariner["id"], credential["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_CREDENTIAL_NOT_RENEWABLE)

    def test_credential_revoke_from_renewal_pending_rejected(self):
        """PRD section 3.3: "Revocation moves a `VALID` credential to
        `REVOKED` — any other source state is `ERR_CREDENTIAL_NOT_VALID` — and
        requires a `reason`."

        Design: Corner/errors/credential_revoke_from_renewal_pending_rejected
        """
        mariner = create_mariner()
        credential = issue_credential(mariner["id"])
        validate_success(
            api_client.submit_credential_renewal(
                mariner["id"], credential["id"], OFFICER))
        resp = api_client.revoke_credential(
            mariner["id"], credential["id"],
            {"reason": "mid-renewal revocation"}, OFFICER)
        validate_error(resp, ApiErrorId.ERR_CREDENTIAL_NOT_VALID)


class TestClockCredentialExpiryCascade:

    def _setup_cascade(self):
        """Mariner CLEAR: C1 MMC_BASE/DECK_AB expiry 2026-09-05 (35 days out
        at the default clock) is the primary credential; C2 TANKER/TANKER_PIC
        expiry 2028-01-01 has C1 as prerequisite. One CONFIRMED assignment."""
        mariner = create_mariner()
        issue_medical_certificate(mariner["id"])
        c1 = issue_credential(mariner["id"], expiry_date="2026-09-05T00:00:00Z")
        c2 = issue_credential(
            mariner["id"], credential_type="TANKER",
            endorsement_code="TANKER_PIC",
            issue_date="2026-02-01T00:00:00Z",
            expiry_date="2028-01-01T00:00:00Z",
            prerequisite_credential_id=c1["id"])
        record_negative_drug_test(mariner["id"])
        mariner = validate_success(api_client.activate_mariner(mariner["id"], ADMIN))
        assert mariner["readiness_posture"] == "CLEAR", \
            "C1 expiry 35 days out at activation must be CLEAR"

        env = setup_active_vessel_with_slot(
            slot_overrides={"is_critical_position": True})
        assignment = propose_assignment(
            mariner["id"], env["slot"]["id"],
            sign_on_date="2026-10-01T00:00:00Z",
            planned_relief_date="2027-01-01T00:00:00Z", local_join=True)
        assignment = confirm_assignment(assignment["id"])
        return {"mariner": mariner, "c1": c1, "c2": c2,
                "assignment": assignment, **env}

    def test_clock_sweep_expires_credential_and_suspends_dependents(self):
        """PRD section 2.6: "Credentials in `VALID`, `RENEWAL_PENDING`, or
        `SUSPENDED_PREREQ` whose `expiry_date` is strictly earlier than the
        new clock become `EXPIRED`."
        PRD section 2.6: "The prerequisite cascade runs: dependents of newly
        expired or revoked credentials move to `SUSPENDED_PREREQ`"

        Design: Difficulty/transitive_cascade/clock_credential_expiry_deep_cascade
        """
        ctx = self._setup_cascade()
        set_clock("2026-09-10T00:00:00Z")

        c1 = validate_success(api_client.get_credential(ctx["c1"]["id"], OFFICER))
        assert c1["status"] == "EXPIRED", \
            f"hop 1: expiry 2026-09-05 < clock 2026-09-10, got {c1['status']}"
        c2 = validate_success(api_client.get_credential(ctx["c2"]["id"], OFFICER))
        assert c2["status"] == "SUSPENDED_PREREQ", (
            f"hop 2: prerequisite cascade, own expiry 2028-01-01 untouched, "
            f"got {c2['status']}")

    def test_clock_sweep_blocks_mariner_and_suspends_assignments(self):
        """PRD section 2.6: "The `readiness_posture` of every affected mariner
        is recomputed (section 3.2)."
        PRD section 2.6: "Mariners whose posture became `BLOCKED` have their
        confirmed assignments suspended (section 3.7)."
        PRD section 3.2: "if no credential exists in `VALID` status whose
        `endorsement_code` equals the mariner's `primary_endorsement_code`,
        posture is `BLOCKED` with reason `NO_VALID_PRIMARY_CREDENTIAL`."

        Design: Difficulty/transitive_cascade/clock_credential_expiry_deep_cascade
        """
        ctx = self._setup_cascade()
        set_clock("2026-09-10T00:00:00Z")

        mariner = validate_success(
            api_client.get_mariner(ctx["mariner"]["id"], CREWING))
        assert mariner["readiness_posture"] == "BLOCKED"
        assert "NO_VALID_PRIMARY_CREDENTIAL" in mariner["readiness_reasons"]

        assignment = validate_success(
            api_client.get_assignment(ctx["assignment"]["id"], CREWING))
        assert assignment["assignment_status"] == "SUSPENDED", (
            f"hop 4: posture cascade onto the future CONFIRMED assignment, "
            f"got {assignment['assignment_status']}")
