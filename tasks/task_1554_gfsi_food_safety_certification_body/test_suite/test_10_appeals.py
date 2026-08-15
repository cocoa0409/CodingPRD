"""Appeals: filing gates, independence, windows, and the overturn cascade."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_instant_equal,
    certificate_appeals,
    certificate_listing,
    decide_appeal,
    file_appeal,
    get_certificate,
    make_client_admin_headers,
    make_decision_maker,
    make_decision_maker_headers,
    set_clock,
    setup_granted_chain,
    suspend_certificate,
    validate_error,
)

ADMIN = TEST_USERS["scheme_admin_headers"]


def _setup_suspended_with_appeal(api):
    """Certificate granted by dm1, then manually suspended by a second
    decision maker at 2026-08-20T00:00:00Z, with the client's appeal FILED.
    Returns (chain, dm2, appeal)."""
    chain = setup_granted_chain()
    dm2 = make_decision_maker(name="Second Reviewer")
    suspend_certificate(chain.certificate["id"], dm2["id"],
                        reason="complaint investigation",
                        at="2026-08-20T00:00:00Z")
    appeal = file_appeal(chain.certificate["id"], chain.client["id"],
                         grounds="complaint unsubstantiated")
    return chain, dm2, appeal


class TestAppealFilingGate:
    def test_appeal_on_active_certificate_rejected(self, api):
        """PRD §3.9: "The target certificate must be `SUSPENDED` or
        `WITHDRAWN` (`ERR_INVALID_CERTIFICATE_STATE` otherwise)"

        Design: Difficulty/cross_entity_state_dependency/appeal_filing_requires_suspended_or_withdrawn_certificate
        """
        chain = setup_granted_chain()
        assert chain.certificate["status"] == "ACTIVE"
        resp = api.create_appeal(
            {"certificate_id": chain.certificate["id"],
             "grounds": "premature appeal"},
            make_client_admin_headers(chain.client["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_CERTIFICATE_STATE, 409)

    def test_appeal_on_active_certificate_creates_no_row(self, api):
        """PRD §3.9: "The target certificate must be `SUSPENDED` or
        `WITHDRAWN` (`ERR_INVALID_CERTIFICATE_STATE` otherwise)" — a rejected
        filing leaves the certificate's appeal list empty.

        Design: Difficulty/cross_entity_state_dependency/appeal_filing_requires_suspended_or_withdrawn_certificate
        """
        chain = setup_granted_chain()
        resp = api.create_appeal(
            {"certificate_id": chain.certificate["id"],
             "grounds": "premature appeal"},
            make_client_admin_headers(chain.client["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_CERTIFICATE_STATE, 409)
        assert certificate_appeals(chain.certificate["id"]) == []


class TestAppealWindow:
    def test_appeal_window_boundary_expired_rejected(self, api):
        """PRD §3.9: "the filing must land no later than the scheme's
        `appeal_window_days` days after the certificate's `status_changed_at`
        — the boundary is inclusive, so filing exactly at the deadline is
        allowed, while a later filing is rejected with
        `ERR_APPEAL_WINDOW_EXPIRED`"

        Design: Corner/validations/appeal_window_boundary_expired_rejected
        """
        chain = setup_granted_chain()  # appeal_window_days 14
        # status_changed_at becomes 2026-08-20T00:00:00Z.
        suspend_certificate(chain.certificate["id"], chain.dm["id"],
                            reason="window probe", at="2026-08-20T00:00:00Z")
        # One second past status_changed_at + 14 days (2026-09-03T00:00:00Z).
        set_clock("2026-09-03T00:00:01Z")
        resp = api.create_appeal(
            {"certificate_id": chain.certificate["id"],
             "grounds": "one second late"},
            make_client_admin_headers(chain.client["id"]))
        validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_EXPIRED, 422)
        # Exactly at the boundary is allowed.
        set_clock("2026-09-03T00:00:00Z")
        appeal = file_appeal(chain.certificate["id"], chain.client["id"],
                             grounds="exactly at the boundary")
        assert appeal["status"] == "FILED"


class TestAppealGuards:
    def test_duplicate_open_appeal_rejected(self, api):
        """PRD §3.9: "a certificate may have at most one appeal in `FILED`
        status at a time (`ERR_DUPLICATE_APPEAL`, 409)."

        Design: Corner/validations/duplicate_open_appeal_rejected
        """
        chain = setup_granted_chain()
        suspend_certificate(chain.certificate["id"], chain.dm["id"],
                            reason="hold")
        file_appeal(chain.certificate["id"], chain.client["id"],
                    grounds="first appeal")
        resp = api.create_appeal(
            {"certificate_id": chain.certificate["id"],
             "grounds": "second appeal"},
            make_client_admin_headers(chain.client["id"]))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_APPEAL, 409)

    def test_appeal_decided_by_original_decision_maker_rejected(self, api):
        """PRD §2.7: "the acting decision maker must be neither the decision
        maker who rendered the appealed certificate's issuing audit decision
        nor a person linked to that audit's auditor — that is, the acting
        decision maker's own `id` must differ from the issuing audit's
        `decision_maker_id`, and the acting decision maker's `linked_auditor_id`
        must differ from that audit's `auditor_id`; a violation is rejected
        with `ERR_APPEAL_NOT_INDEPENDENT` (403)."
        PRD §3.9: "An `UPHELD` outcome stamps `decided_by` and `decided_at`,
        increments the appeal's `version`, and leaves the certificate's status
        unchanged."

        Design: Corner/validations/appeal_decided_by_original_decision_maker_rejected
        """
        chain, dm2, appeal = _setup_suspended_with_appeal(api)
        # chain.dm rendered the issuing audit's GRANT.
        resp = api.decide_appeal(appeal["id"], {"outcome": "UPHELD"},
                                 make_decision_maker_headers(chain.dm["id"]))
        validate_error(resp, ApiErrorId.ERR_APPEAL_NOT_INDEPENDENT, 403)
        decided = decide_appeal(appeal["id"], dm2["id"], "UPHELD")
        assert decided["status"] == "UPHELD"
        assert decided["decided_by"] == dm2["id"]
        # UPHELD never mutates the certificate.
        assert get_certificate(chain.certificate["id"])["status"] == "SUSPENDED"

    def test_appeal_double_decide_rejected(self, api):
        """PRD §3.9: "the appeal must be `FILED` (`ERR_INVALID_APPEAL_STATE`)"
        — a decided appeal is locked.

        Design: Corner/state_machines/appeal_double_decide_rejected
        """
        chain, dm2, appeal = _setup_suspended_with_appeal(api)
        decide_appeal(appeal["id"], dm2["id"], "UPHELD")
        resp = api.decide_appeal(appeal["id"], {"outcome": "OVERTURNED"},
                                 make_decision_maker_headers(dm2["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_APPEAL_STATE, 409)
        stored = [a for a in certificate_appeals(chain.certificate["id"])
                  if a["id"] == appeal["id"]][0]
        assert stored["status"] == "UPHELD"
        assert get_certificate(chain.certificate["id"])["status"] == "SUSPENDED"


class TestOverturnCascade:
    def test_appeal_overturn_reinstates_certificate(self, api):
        """PRD §3.9: "An `OVERTURNED` outcome stamps the same fields and
        reinstates the certificate — `SUSPENDED → ACTIVE` or `WITHDRAWN →
        ACTIVE` — clearing `suspension_reason`, setting `status_changed_at` to
        the current logical time, incrementing the certificate's `version` by
        one, and transitioning the DirectoryListing back to `LISTED` with
        `listed_at` stamped."

        Design: Difficulty/transitive_cascade/appeal_overturn_reinstates_certificate_relists_directory
        """
        chain, dm2, appeal = _setup_suspended_with_appeal(api)
        decided = decide_appeal(appeal["id"], dm2["id"], "OVERTURNED")
        assert decided["status"] == "OVERTURNED"
        assert decided["decided_by"] == dm2["id"]
        cert = get_certificate(chain.certificate["id"])
        assert cert["status"] == "ACTIVE"
        assert cert["suspension_reason"] is None

    def test_appeal_overturn_relists_directory(self, api):
        """PRD §3.9: "An `OVERTURNED` outcome stamps the same fields and
        reinstates the certificate — `SUSPENDED → ACTIVE` or `WITHDRAWN →
        ACTIVE` — clearing `suspension_reason`, setting `status_changed_at` to
        the current logical time, incrementing the certificate's `version` by
        one, and transitioning the DirectoryListing back to `LISTED` with
        `listed_at` stamped."
        PRD §2.10: "every reinstatement — manual or through an overturned
        appeal — transitions the listing back to `LISTED` and stamps
        `listed_at`."

        Design: Difficulty/transitive_cascade/appeal_overturn_reinstates_certificate_relists_directory
        """
        chain, dm2, appeal = _setup_suspended_with_appeal(api)
        listing = certificate_listing(chain.certificate["id"])
        assert listing["status"] == "UNLISTED"
        decide_appeal(appeal["id"], dm2["id"], "OVERTURNED")
        listing = certificate_listing(chain.certificate["id"])
        assert listing["status"] == "LISTED"
        # The appeal was decided at the current logical time
        # 2026-08-20T00:00:00Z.
        assert_instant_equal(listing["listed_at"], "2026-08-20T00:00:00Z")
