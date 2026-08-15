"""Certificate lifecycle, directory propagation, OCC scope changes, sweeps."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_instant_equal,
    certificate_listing,
    certificate_scope_changes,
    create_scope_change,
    decide_audit,
    decide_scope_change,
    get_certificate,
    make_client_admin_headers,
    make_decision_maker_headers,
    reinstate_certificate,
    set_clock,
    setup_granted_chain,
    setup_reported_chain,
    start_second_audit,
    submit_report,
    suspend_certificate,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_certificate,
)

ADMIN = TEST_USERS["scheme_admin_headers"]

EXPANDED_SCOPE = [
    {"category_code": "BAKERY", "risk_tier": "STANDARD"},
    {"category_code": "DAIRY", "risk_tier": "HIGH"},
]


class TestSuspendReinstateWithdrawBranching:
    def test_suspend_then_reinstate_restores_active(self, api):
        """PRD §3.8: "the transition `ACTIVE → SUSPENDED` records
        `suspension_reason` `MANUAL`, stamps `status_changed_at` with the
        current logical time, increments the certificate's `version`, and
        unlists its DirectoryListing."
        PRD §3.8: "Reinstatement clears `suspension_reason` back to null,
        stamps `status_changed_at`, increments `version`, and transitions the
        DirectoryListing back to `LISTED` with a fresh `listed_at`."

        Design: Difficulty/non_linear_state_machine/certificate_suspend_reinstate_withdraw_branching
        """
        chain = setup_granted_chain()
        suspended = suspend_certificate(chain.certificate["id"],
                                        chain.dm["id"],
                                        reason="Routine regulatory hold")
        assert suspended["status"] == "SUSPENDED"
        assert suspended["suspension_reason"] == "MANUAL"
        # A MANUAL suspension carries no NC guard on reinstatement.
        reinstated = reinstate_certificate(chain.certificate["id"],
                                           chain.dm["id"])
        assert reinstated["status"] == "ACTIVE"
        assert reinstated["suspension_reason"] is None

    def test_suspend_withdraw_terminal_fork(self, api):
        """PRD §3.8: "Withdrawal is terminal: a `DecisionMaker` may withdraw a
        certificate from `ACTIVE` or `SUSPENDED` (any other status is rejected
        with `ERR_INVALID_CERTIFICATE_STATE`), stamping `status_changed_at`,
        incrementing `version`, and unlisting the DirectoryListing."
        PRD §2.10: "every transition that takes a certificate out of `ACTIVE`
        — suspension, withdrawal, or expiry — transitions its DirectoryListing
        to `UNLISTED` and stamps `unlisted_at` with the current logical time"

        Design: Difficulty/non_linear_state_machine/certificate_suspend_reinstate_withdraw_branching
        """
        chain = setup_granted_chain()
        suspend_certificate(chain.certificate["id"], chain.dm["id"],
                            reason="Second hold")
        withdrawn = withdraw_certificate(chain.certificate["id"],
                                         chain.dm["id"])
        assert withdrawn["status"] == "WITHDRAWN"
        listing = certificate_listing(chain.certificate["id"])
        assert listing["status"] == "UNLISTED"


class TestCertificateInvalidTransitions:
    def test_certificate_double_suspend_rejected(self, api):
        """PRD §3.8: "A `DecisionMaker` may manually suspend a certificate,
        supplying a free-text `reason`; the certificate must be `ACTIVE`
        (`ERR_INVALID_CERTIFICATE_STATE` otherwise)"

        Design: Corner/state_machines/certificate_double_suspend_rejected
        """
        chain = setup_granted_chain()
        suspend_certificate(chain.certificate["id"], chain.dm["id"],
                            reason="first hold")
        resp = api.suspend_certificate(chain.certificate["id"],
                                       {"reason": "second hold"},
                                       make_decision_maker_headers(chain.dm["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_CERTIFICATE_STATE, 409)
        assert get_certificate(chain.certificate["id"])["status"] == "SUSPENDED"

    def test_withdrawn_certificate_terminal_lockdown(self, api):
        """PRD §3.8: "Withdrawal is terminal: a `DecisionMaker` may withdraw a
        certificate from `ACTIVE` or `SUSPENDED` (any other status is rejected
        with `ERR_INVALID_CERTIFICATE_STATE`)"

        Design: Corner/state_machines/withdrawn_certificate_terminal_lockdown
        """
        chain = setup_granted_chain()
        withdraw_certificate(chain.certificate["id"], chain.dm["id"])
        dm_headers = make_decision_maker_headers(chain.dm["id"])
        resp = api.suspend_certificate(chain.certificate["id"],
                                       {"reason": "late hold"}, dm_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_CERTIFICATE_STATE, 409)
        resp = api.reinstate_certificate(chain.certificate["id"], dm_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_CERTIFICATE_STATE, 409)
        assert get_certificate(chain.certificate["id"])["status"] == "WITHDRAWN"


class TestDirectoryPropagation:
    def test_manual_suspend_unlists_directory(self, api):
        """PRD §3.8: "the transition `ACTIVE → SUSPENDED` records
        `suspension_reason` `MANUAL`, stamps `status_changed_at` with the
        current logical time, increments the certificate's `version`, and
        unlists its DirectoryListing."
        PRD §2.10: "every transition that takes a certificate out of `ACTIVE`
        — suspension, withdrawal, or expiry — transitions its DirectoryListing
        to `UNLISTED` and stamps `unlisted_at` with the current logical time"

        Design: Corner/state_machines/manual_suspend_unlists_directory
        """
        chain = setup_granted_chain()
        suspended = suspend_certificate(chain.certificate["id"],
                                        chain.dm["id"],
                                        reason="manual regulatory hold",
                                        at="2026-08-20T00:00:00Z")
        assert suspended["status"] == "SUSPENDED"
        assert suspended["suspension_reason"] == "MANUAL"
        assert_instant_equal(suspended["status_changed_at"],
                             "2026-08-20T00:00:00Z")
        listing = certificate_listing(chain.certificate["id"])
        assert listing["status"] == "UNLISTED"
        assert_instant_equal(listing["unlisted_at"], "2026-08-20T00:00:00Z")

    def test_surveillance_deny_withdraws_certificate_and_unlists(self, api):
        """PRD §3.6: "A `DENY` on a `SURVEILLANCE` or `UNANNOUNCED` audit
        withdraws the existing `ACTIVE` certificate — `ACTIVE → WITHDRAWN`
        with `status_changed_at` equal to `decided_at` — and unlists its
        DirectoryListing with `unlisted_at` equal to `decided_at`, scheduling
        no successor."

        Design: Corner/state_machines/surveillance_deny_withdraws_certificate_and_unlists
        """
        chain = setup_granted_chain()
        audit2 = start_second_audit(chain)
        audit2 = submit_report(audit2["id"], chain.auditor["id"],
                               actual_days=1)
        denied = decide_audit(audit2["id"], chain.dm["id"], "DENY")
        assert denied["decision_outcome"] == "DENY"
        assert denied["status"] == "DECIDED"
        cert = get_certificate(chain.certificate["id"])
        assert cert["status"] == "WITHDRAWN"
        # The decision ran at the current logical time 2026-10-14T09:00:00Z.
        assert_instant_equal(cert["status_changed_at"], "2026-10-14T09:00:00Z")
        listing = certificate_listing(cert["id"])
        assert listing["status"] == "UNLISTED"
        assert_instant_equal(listing["unlisted_at"], "2026-10-14T09:00:00Z")
        # No successor audit is scheduled after a surveillance DENY.
        from test_helpers import application_audits
        assert len(application_audits(chain.app["id"])) == 2


class TestPublicationParity:
    def test_parity_before_and_after_suspend(self, api):
        """PRD §2.10: "every transition that takes a certificate out of
        `ACTIVE` — suspension, withdrawal, or expiry — transitions its
        DirectoryListing to `UNLISTED` and stamps `unlisted_at` with the
        current logical time" — the count of ACTIVE certificates and the count
        of LISTED directory entries move together.

        Design: Difficulty/compensating_invariant/active_certificate_listed_directory_parity_over_suspend_reinstate
        """
        chain = setup_granted_chain()
        _d, meta = validate_paginated(
            api.list_certificates(ADMIN, params={"status": "ACTIVE"}))
        assert meta["total_count"] == 1
        _d, meta = validate_paginated(
            api.list_directory(ADMIN, params={"status": "LISTED"}))
        assert meta["total_count"] == 1

        suspend_certificate(chain.certificate["id"], chain.dm["id"],
                            reason="parity probe hold", at="2026-08-20T00:00:00Z")
        assert get_certificate(chain.certificate["id"])["status"] == "SUSPENDED"
        assert certificate_listing(chain.certificate["id"])["status"] == "UNLISTED"
        _d, meta = validate_paginated(
            api.list_certificates(ADMIN, params={"status": "ACTIVE"}))
        assert meta["total_count"] == 0
        _d, meta = validate_paginated(
            api.list_directory(ADMIN, params={"status": "LISTED"}))
        assert meta["total_count"] == 0

    def test_parity_restored_after_reinstate(self, api):
        """PRD §2.10: "every reinstatement — manual or through an overturned
        appeal — transitions the listing back to `LISTED` and stamps
        `listed_at`."

        Design: Difficulty/compensating_invariant/active_certificate_listed_directory_parity_over_suspend_reinstate
        """
        chain = setup_granted_chain()
        suspend_certificate(chain.certificate["id"], chain.dm["id"],
                            reason="parity probe hold", at="2026-08-20T00:00:00Z")
        listing = certificate_listing(chain.certificate["id"])
        assert listing["status"] == "UNLISTED"
        assert_instant_equal(listing["unlisted_at"], "2026-08-20T00:00:00Z")

        set_clock("2026-08-21T00:00:00Z")
        reinstated = reinstate_certificate(chain.certificate["id"],
                                           chain.dm["id"])
        assert reinstated["status"] == "ACTIVE"
        listing = certificate_listing(chain.certificate["id"])
        assert listing["status"] == "LISTED"
        # listed_at refreshes on reinstatement.
        assert_instant_equal(listing["listed_at"], "2026-08-21T00:00:00Z")
        _d, meta = validate_paginated(
            api.list_certificates(ADMIN, params={"status": "ACTIVE"}))
        assert meta["total_count"] == 1
        _d, meta = validate_paginated(
            api.list_directory(ADMIN, params={"status": "LISTED"}))
        assert meta["total_count"] == 1


class TestExpirySweep:
    def test_certificate_expiry_sweep_marks_expired_and_unlists(self, api):
        """PRD §3.8: "whenever the logical clock advances, each certificate in
        `ACTIVE` or `SUSPENDED` whose `valid_to` is strictly earlier than the
        current logical time transitions to the terminal `EXPIRED` state —
        processed in `created_at` ascending order — with `status_changed_at`
        set, `version` incremented, and its DirectoryListing transitioned to
        `UNLISTED` with `unlisted_at` stamped."
        PRD §2.6: "Both sweeps compare with strict inequality"

        Design: Corner/cross_cutting_layers/certificate_expiry_sweep_marks_expired_and_unlists
        """
        chain = setup_granted_chain()
        cert = get_certificate(chain.certificate["id"])
        # valid_from 2026-08-15T09:00:00Z + cert_validity_days 1095.
        assert_instant_equal(cert["valid_to"], "2029-08-14T09:00:00Z")
        # At exactly valid_to the strict-inequality sweep leaves it ACTIVE.
        set_clock("2029-08-14T09:00:00Z")
        assert get_certificate(cert["id"])["status"] == "ACTIVE"
        # One second later it expires and unlists.
        set_clock("2029-08-14T09:00:01Z")
        expired = get_certificate(cert["id"])
        assert expired["status"] == "EXPIRED"
        listing = certificate_listing(cert["id"])
        assert listing["status"] == "UNLISTED"


class TestPublicDirectory:
    def test_directory_publicly_accessible_without_auth(self, api):
        """PRD §3.9: "The public certification directory is the market-facing
        surface: it is queryable without authentication — the only endpoint an
        `Anonymous` caller may use — and by every other role"
        PRD §3.9: "Each listing row shows its `certificate_id`, the
        denormalized `client_name` and `scheme_code`, the computed
        `scope_summary`, its `status` of `LISTED` or `UNLISTED`, and the
        `listed_at` / `unlisted_at` stamps."

        Design: Corner/endpoints/directory_publicly_accessible_without_auth
        """
        setup_granted_chain()
        # No authentication headers at all.
        data, meta = validate_paginated(api.list_directory(headers={}))
        assert meta["total_count"] == 1
        listing = data[0]
        assert listing["client_name"] == "Acme Baking Co"
        assert listing["scheme_code"] == "SQF"
        assert listing["scope_summary"] == "BAKERY"
        assert listing["status"] == "LISTED"

    def test_certificate_directory_listing_returns_zero_or_one_array(self, api):
        """PRD §3.6: "The certificate an audit issued remains readable through
        the audit, as an array of zero or one entries."
        PRD §3.9: "A certificate's own listing is also readable through the
        certificate itself, as an array of zero or one entries."

        Design: Corner/endpoints/certificate_directory_listing_returns_zero_or_one_array
        """
        chain = setup_reported_chain()
        # Before any decision the issuing-audit lookup is an empty array.
        before = validate_success(api.get_audit_certificate(chain.audit["id"],
                                                            ADMIN))
        assert isinstance(before, list) and len(before) == 0
        decided = decide_audit(chain.audit["id"], chain.dm["id"], "GRANT")
        certs = validate_success(api.get_audit_certificate(chain.audit["id"],
                                                           ADMIN))
        assert len(certs) == 1
        listings = validate_success(
            api.get_certificate_listing(certs[0]["id"], ADMIN))
        assert isinstance(listings, list) and len(listings) == 1
        assert listings[0]["status"] == "LISTED"
        # listed_at equals the decision's decided_at (PRD §3.6).
        assert_instant_equal(listings[0]["listed_at"], decided["decided_at"])


class TestScopeChanges:
    def test_fresh_certificate_version_scope_change_succeeds(self, api):
        """PRD §2.11: "A request to `POST
        /certification-body/certificates/{id}/scope-changes` must carry
        `expected_certificate_version` as a non-optional input, holding the
        certificate `version` the client last observed."
        PRD §3.9: "Creation produces a ScopeChange in `PENDING` status and
        itself touches the certificate record, incrementing the certificate's
        `version` by one."

        Design: Corner/cross_cutting_layers/fresh_certificate_version_scope_change_succeeds
        """
        chain = setup_granted_chain()
        cert = get_certificate(chain.certificate["id"])
        resp = api.create_scope_change(
            cert["id"],
            {"requested_categories": EXPANDED_SCOPE,
             "reason": "adding dairy line",
             "expected_certificate_version": cert["version"]},
            make_client_admin_headers(chain.client["id"]))
        data = validate_success(resp, 201)
        assert data["status"] == "PENDING"
        # Every mutation bumps the certificate's version (PRD §2.4).
        assert get_certificate(cert["id"])["version"] == cert["version"] + 1

    def test_stale_certificate_version_returns_412(self, api):
        """PRD §2.11: "If another write — an earlier scope-change request, a
        suspension, a reinstatement, an approved scope change — has advanced
        the certificate's `version` since then, the client's view of the
        certificate is stale and the creation is rejected with
        `ERR_STALE_CERTIFICATE_VERSION` (HTTP 412)"

        Design: Corner/cross_cutting_layers/stale_certificate_version_returns_412
        """
        chain = setup_granted_chain()
        cert = get_certificate(chain.certificate["id"])
        observed_version = cert["version"]
        create_scope_change(cert["id"], chain.client["id"], EXPANDED_SCOPE,
                            "first change", observed_version)
        # The first create advanced the certificate's version, so the same
        # observed version is now stale.
        resp = api.create_scope_change(
            cert["id"],
            {"requested_categories": [{"category_code": "MEAT",
                                       "risk_tier": "HIGH"}],
             "reason": "second change against stale view",
             "expected_certificate_version": observed_version},
            make_client_admin_headers(chain.client["id"]))
        validate_error(resp, ApiErrorId.ERR_STALE_CERTIFICATE_VERSION, 412)
        _d, meta = validate_paginated(
            api.list_scope_changes(cert["id"], ADMIN))
        assert meta["total_count"] == 1

    def test_scope_change_approval_refreshes_listing_scope_summary(self, api):
        """PRD §3.9: "Approval replaces the certificate's `product_categories`
        with the `requested_categories`, increments the certificate's
        `version`, regenerates the DirectoryListing's `scope_summary` from the
        new categories, and stamps `decided_by` and `decided_at` on the
        request."
        PRD §2.10: "its `scope_summary` is computed as the category codes of
        the certificate's `product_categories` sorted in ascending order and
        joined with commas; the summary is regenerated whenever a scope change
        is approved."

        Design: Corner/cross_cutting_layers/scope_change_approval_refreshes_listing_scope_summary
        """
        chain = setup_granted_chain()
        cert = get_certificate(chain.certificate["id"])
        sc = create_scope_change(cert["id"], chain.client["id"],
                                 EXPANDED_SCOPE, "adding dairy line",
                                 cert["version"])
        decided = decide_scope_change(sc["id"], chain.dm["id"], "APPROVED")
        assert decided["status"] == "APPROVED"
        assert decided["decided_by"] == chain.dm["id"]
        assert decided["decided_at"] is not None
        updated = get_certificate(cert["id"])
        assert updated["product_categories"] == EXPANDED_SCOPE
        # 1 at issuance, +1 at scope-change create, +1 at approval.
        assert updated["version"] == cert["version"] + 2
        listing = certificate_listing(cert["id"])
        assert listing["scope_summary"] == "BAKERY,DAIRY"

    def test_scope_change_double_decision_rejected(self, api):
        """PRD §3.9: "A `DecisionMaker` then decides the request with an
        `outcome` of `APPROVED` or `REJECTED`; the request must be `PENDING`
        (`ERR_INVALID_SCOPE_CHANGE_STATE`)."

        Design: Corner/state_machines/scope_change_double_decision_rejected
        """
        chain = setup_granted_chain()
        cert = get_certificate(chain.certificate["id"])
        sc = create_scope_change(cert["id"], chain.client["id"],
                                 EXPANDED_SCOPE, "adding dairy line",
                                 cert["version"])
        decide_scope_change(sc["id"], chain.dm["id"], "APPROVED")
        resp = api.decide_scope_change(sc["id"], {"outcome": "REJECTED"},
                                       make_decision_maker_headers(chain.dm["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_SCOPE_CHANGE_STATE, 409)
        stored = [s for s in certificate_scope_changes(cert["id"])
                  if s["id"] == sc["id"]][0]
        assert stored["status"] == "APPROVED"
