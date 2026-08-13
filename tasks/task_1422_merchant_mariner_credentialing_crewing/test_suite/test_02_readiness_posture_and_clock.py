"""Readiness-posture computation, restricted-window boundaries, and the
logical clock."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    confirm_assignment,
    create_activated_mariner,
    create_mariner,
    issue_credential,
    issue_medical_certificate,
    propose_assignment,
    record_negative_drug_test,
    set_clock,
    setup_active_vessel_with_slot,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["fleet_admin_headers"]
CREWING = TEST_USERS["crewing_headers"]


class TestRestrictedWindowBoundary:

    def test_restricted_window_exactly_30_days_restricted(self, fleet_admin_headers):
        """PRD section 3.2: "If that earliest expiry falls within 30 days of
        now, posture is `RESTRICTED` and `readiness_reasons` carries one code
        per source expiring inside that window — `MEDICAL_EXPIRING_SOON`,
        `DRUG_CURRENCY_EXPIRING_SOON`, or `CREDENTIAL_EXPIRING_SOON`."

        Design: Corner/calculations/restricted_window_exactly_30_days
        """
        # Medical expiry 2026-08-31 is exactly 30 days past the default clock
        # 2026-08-01 -> within the window.
        mariner = create_mariner()
        issue_medical_certificate(
            mariner["id"], expiry_date="2026-08-31T00:00:00Z")
        issue_credential(mariner["id"])
        record_negative_drug_test(mariner["id"])
        resp = api_client.activate_mariner(mariner["id"], fleet_admin_headers)
        data = validate_success(resp)
        assert data["readiness_posture"] == "RESTRICTED", \
            f"30 days out must be RESTRICTED, got {data['readiness_posture']}"
        assert data["readiness_reasons"] == ["MEDICAL_EXPIRING_SOON"], \
            f"only the medical source is inside 30 days, got {data['readiness_reasons']}"

    def test_restricted_window_31_days_is_clear(self, fleet_admin_headers):
        """PRD section 3.2: "If that earliest expiry falls within 30 days of
        now, posture is `RESTRICTED` and `readiness_reasons` carries one code
        per source expiring inside that window — `MEDICAL_EXPIRING_SOON`,
        `DRUG_CURRENCY_EXPIRING_SOON`, or `CREDENTIAL_EXPIRING_SOON`.
        Otherwise posture is `CLEAR` with an empty reason list."

        Design: Corner/calculations/restricted_window_exactly_30_days
        """
        # Medical expiry 2026-09-01 is 31 days past the default clock.
        mariner = create_mariner()
        issue_medical_certificate(
            mariner["id"], expiry_date="2026-09-01T00:00:00Z")
        issue_credential(mariner["id"])
        record_negative_drug_test(mariner["id"])
        resp = api_client.activate_mariner(mariner["id"], fleet_admin_headers)
        data = validate_success(resp)
        assert data["readiness_posture"] == "CLEAR", \
            f"31 days out must be CLEAR, got {data['readiness_posture']}"
        assert data["readiness_reasons"] == []


class TestExpiryInstantBoundary:

    def test_medical_expiry_instant_boundary(self, fleet_admin_headers,
                                             officer_headers):
        """PRD section 2.6: "Expiry comparisons are strict: a credential or
        certificate whose `expiry_date` is exactly the current clock instant
        remains valid; it expires only once the clock moves strictly past
        that instant."
        PRD section 3.2: "The second gate is medical: if no medical
        certificate exists in `VALID` status with an `expiry_date` on or after
        now, posture is `BLOCKED` with reason `NO_VALID_MEDICAL`."

        Design: Corner/calculations/medical_expiry_instant_boundary
        """
        mariner = create_activated_mariner(
            medical_expiry="2026-08-20T00:00:00Z")

        # At clock == expiry_date the certificate is still VALID; the medical
        # source is 0 days out, inside the 30-day restricted window.
        set_clock("2026-08-20T00:00:00Z")
        certs = validate_success(
            api_client.list_medical_certificates(mariner["id"], officer_headers))
        assert certs[0]["status"] == "VALID", \
            f"expiry == now must remain VALID, got {certs[0]['status']}"
        m_at = validate_success(api_client.get_mariner(mariner["id"], officer_headers))
        assert m_at["readiness_posture"] == "RESTRICTED", \
            f"0 days remaining is within the restricted window, got {m_at['readiness_posture']}"

        # One second past the expiry instant the sweep flips it to EXPIRED.
        set_clock("2026-08-20T00:00:01Z")
        certs = validate_success(
            api_client.list_medical_certificates(mariner["id"], officer_headers))
        assert certs[0]["status"] == "EXPIRED", \
            f"one second past expiry must be EXPIRED, got {certs[0]['status']}"
        m_after = validate_success(
            api_client.get_mariner(mariner["id"], officer_headers))
        assert m_after["readiness_posture"] == "BLOCKED"
        assert "NO_VALID_MEDICAL" in m_after["readiness_reasons"]


class TestReadinessEvaluationSnapshot:

    def _setup_restricted_mariner(self):
        """Mariner RESTRICTED at the default clock: medical expiry
        2026-08-20 (19 days), credential expiry 2026-08-25 (24 days), drug
        currency until 2027-01-02 (155 days)."""
        mariner = create_mariner()
        issue_medical_certificate(
            mariner["id"], expiry_date="2026-08-20T00:00:00Z")
        issue_credential(mariner["id"], expiry_date="2026-08-25T00:00:00Z")
        record_negative_drug_test(mariner["id"])
        resp = api_client.activate_mariner(mariner["id"], ADMIN)
        return validate_success(resp)

    def test_restricted_posture_reasons_and_confirm_inside_window(
            self, crewing_headers):
        """PRD section 3.2: "If that earliest expiry falls within 30 days of
        now, posture is `RESTRICTED` and `readiness_reasons` carries one code
        per source expiring inside that window"
        PRD section 3.2: "a restricted mariner may be confirmed onto an
        assignment only when the assignment's `planned_relief_date` is on or
        before the earliest restricting expiry"

        Design: Difficulty/combinatorial_formula/readiness_posture_evaluation_order_snapshot
        """
        mariner = self._setup_restricted_mariner()
        assert mariner["readiness_posture"] == "RESTRICTED"
        reasons = mariner["readiness_reasons"]
        assert "MEDICAL_EXPIRING_SOON" in reasons
        assert "CREDENTIAL_EXPIRING_SOON" in reasons
        assert "DRUG_CURRENCY_EXPIRING_SOON" not in reasons, \
            f"drug currency (155 days out) must not contribute, got {reasons}"

        env = setup_active_vessel_with_slot()
        # Reuse only the vessel side; override the mariner with the
        # RESTRICTED one whose relief date is on or before the earliest
        # restricting expiry (medical, 2026-08-20).
        assignment = propose_assignment(
            mariner["id"], env["slot"]["id"],
            sign_on_date="2026-08-10T00:00:00Z",
            planned_relief_date="2026-08-19T00:00:00Z", local_join=True)
        confirmed = confirm_assignment(assignment["id"])
        assert confirmed["assignment_status"] == "CONFIRMED", \
            "relief 2026-08-19 <= earliest restricting expiry 2026-08-20 must confirm"

        # The confirm itself must not have re-entered or altered the posture.
        after = validate_success(api_client.get_mariner(mariner["id"], crewing_headers))
        assert after["readiness_posture"] == "RESTRICTED", (
            "posture is evaluated from the pre-transition committed snapshot; "
            f"a successful confirm must not alter it, got {after['readiness_posture']}")

    def test_restricted_confirm_beyond_window_rejected(self):
        """PRD section 3.2: "confirming beyond that horizon is rejected with
        `ERR_RESTRICTED_WINDOW_EXCEEDED`, while a `BLOCKED` mariner is
        rejected outright with `ERR_MARINER_NOT_CLEAR`."

        Design: Difficulty/combinatorial_formula/readiness_posture_evaluation_order_snapshot
        """
        mariner = self._setup_restricted_mariner()
        env = setup_active_vessel_with_slot()
        # Relief 2026-08-21 is past the earliest restricting expiry (medical
        # 2026-08-20), even though the credential runs to 2026-08-25.
        assignment = propose_assignment(
            mariner["id"], env["slot"]["id"],
            sign_on_date="2026-08-10T00:00:00Z",
            planned_relief_date="2026-08-21T00:00:00Z", local_join=True)
        resp = api_client.confirm_assignment(assignment["id"], CREWING)
        validate_error(resp, ApiErrorId.ERR_RESTRICTED_WINDOW_EXCEEDED)


class TestImmediatePostureRecompute:

    def test_immediate_posture_recompute_on_medical_suspend(self, officer_headers):
        """PRD section 3.5: "A suspended certificate does not satisfy the
        medical gate, so the posture recompute that follows will typically
        land the mariner on `BLOCKED` with reason `NO_VALID_MEDICAL`"
        PRD section 3.5: "Reinstatement moves `SUSPENDED` back to `VALID`
        (else `ERR_MEDICAL_CERT_NOT_VALID`), provided the `expiry_date` is
        still in the future."
        PRD section 2.9: "Whenever the underlying children change — a
        credential revoked or swept, a medical certificate suspended or
        expired, a drug result recorded ... the affected postures are
        recomputed immediately"

        Design: Corner/complexity_layers/immediate_posture_recompute_on_medical_suspend
        """
        mariner = create_activated_mariner()
        assert mariner["readiness_posture"] == "CLEAR"
        certs = validate_success(
            api_client.list_medical_certificates(mariner["id"], officer_headers))
        cert_id = certs[0]["id"]

        suspended = validate_success(
            api_client.suspend_medical_certificate(
                mariner["id"], cert_id, officer_headers))
        assert suspended["status"] == "SUSPENDED"
        blocked = validate_success(api_client.get_mariner(mariner["id"], officer_headers))
        assert blocked["readiness_posture"] == "BLOCKED", \
            "posture recompute is immediate — no clock advance required"
        assert "NO_VALID_MEDICAL" in blocked["readiness_reasons"]

        reinstated = validate_success(
            api_client.reinstate_medical_certificate(
                mariner["id"], cert_id, officer_headers))
        assert reinstated["status"] == "VALID"
        restored = validate_success(
            api_client.get_mariner(mariner["id"], officer_headers))
        assert restored["readiness_posture"] == "CLEAR"


class TestLogicalClock:

    def test_immediate_clock_visibility_after_set(self, fleet_admin_headers,
                                                  crewing_headers):
        """PRD section 2.6: "Before any clock-setting call, the clock reads
        exactly 2026-08-01T00:00:00Z."
        PRD section 2.6: "A `FleetAdmin` may advance the clock by supplying a
        `to_iso8601` instant; reading the clock returns `current_utc`."

        Design: Corner/consistency_model/immediate_clock_visibility_after_set
        """
        initial = validate_success(api_client.get_clock(fleet_admin_headers))
        assert initial["current_utc"] == "2026-08-01T00:00:00Z", \
            f"pinned startup default, got {initial['current_utc']}"

        set_resp = validate_success(
            api_client.set_clock({"to_iso8601": "2026-08-15T12:00:00Z"},
                                 fleet_admin_headers))
        assert set_resp["current_utc"] == "2026-08-15T12:00:00Z"
        read_back = validate_success(api_client.get_clock(crewing_headers))
        assert read_back["current_utc"] == "2026-08-15T12:00:00Z", \
            "the write must be visible in the very next read (immediate consistency)"
