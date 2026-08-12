"""Abstraction workflow: segregation of duties, reopen cycle, OCC, priority."""
from test_helpers import (
    ApiErrorId,
    create_lease,
    create_property,
    get_lease,
    make_abstractor_headers,
    make_certifier_headers,
    make_portfolio_manager_headers,
    set_clock,
    validate_error,
    validate_success,
)


def _fresh_lease(api):
    set_clock()
    prop = create_property()
    return create_lease(prop["id"])


class TestCertifySegregation:
    def test_certify_segregation_of_duties(self, api):
        """PRD §2.9: "Certification of a lease abstraction requires that the
        acting operator's `X-User-ID` differ from the lease's recorded
        `abstractor_user_id`; approval of a posted reconciliation requires that
        the acting operator's `X-User-ID` differ from the reconciliation's
        recorded `posted_by_user_id`. A same-user attempt on either transition
        is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."

        Design: Corner/validations/certify_segregation_of_duties
        """
        lease = _fresh_lease(api)
        abs_headers = make_abstractor_headers("abs-1")
        validate_success(api.abstract_lease(lease["id"], abs_headers))
        # Same operator id, now acting as Certifier, attempts certification.
        resp = api.certify_lease(lease["id"], make_certifier_headers("abs-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    def test_certify_by_distinct_user_succeeds(self, api):
        """PRD §3.2: "A `Certifier` then reviews and certifies, moving
        `abstraction_status` from `ABSTRACTED` to `CERTIFIED`. Certification is
        segregation-controlled per §2.9: if the certifier's `X-User-ID` equals
        the recorded `abstractor_user_id`, the attempt is rejected with
        `ERR_SEGREGATION_OF_DUTIES`. A successful certification records
        `certifier_user_id` and increments the lease's `version`."

        Design: Corner/validations/certify_segregation_of_duties
        """
        lease = _fresh_lease(api)
        validate_success(api.abstract_lease(lease["id"], make_abstractor_headers("abs-1")))
        data = validate_success(
            api.certify_lease(lease["id"], make_certifier_headers("cert-1"))
        )
        assert data["abstraction_status"] == "CERTIFIED"
        assert data["certifier_user_id"] == "cert-1"
        assert data["abstractor_user_id"] == "abs-1"


class TestAbstractionReopen:
    def test_lease_abstraction_cycle_certify_reopen(self, api, portfolio_manager_headers):
        """PRD §3.2: "If a certified abstraction turns out to be wrong while the
        lease is still in `DRAFT`, a `PortfolioManager` may reopen it, returning
        `abstraction_status` from `CERTIFIED` to `PENDING` and clearing both
        `abstractor_user_id` and `certifier_user_id` to null."

        Design: Corner/state_machines/lease_abstraction_cycle_certify_reopen
        """
        lease = _fresh_lease(api)
        validate_success(api.abstract_lease(lease["id"], make_abstractor_headers("abs-1")))
        validate_success(api.certify_lease(lease["id"], make_certifier_headers("cert-1")))
        current = get_lease(lease["id"])
        data = validate_success(
            api.reopen_abstraction(
                lease["id"],
                {"expected_lease_version": current["version"]},
                portfolio_manager_headers,
            )
        )
        assert data["abstraction_status"] == "PENDING", (
            f"expected PENDING after reopen, got {data['abstraction_status']}"
        )
        assert data["abstractor_user_id"] is None, (
            f"abstractor_user_id must be cleared to null, got {data['abstractor_user_id']}"
        )
        assert data["certifier_user_id"] is None, (
            f"certifier_user_id must be cleared to null, got {data['certifier_user_id']}"
        )

    def test_occ_stale_version_on_reopen_abstraction(self, api, portfolio_manager_headers):
        """PRD §3.2: "Reopening is one of the two OCC-guarded writes in the
        system: the request must carry `expected_lease_version` matching the
        lease's current `version`, and a mismatch is rejected with
        `ERR_STALE_VERSION` (HTTP 412), since an intervening amendment approval
        may have advanced the lease past the state the reopener observed."

        Design: Corner/validations/occ_stale_version_on_reopen_abstraction
        """
        lease = _fresh_lease(api)
        validate_success(api.abstract_lease(lease["id"], make_abstractor_headers("abs-1")))
        validate_success(api.certify_lease(lease["id"], make_certifier_headers("cert-1")))
        stale_version = get_lease(lease["id"])["version"]
        # First reopen advances the lease version.
        validate_success(
            api.reopen_abstraction(
                lease["id"], {"expected_lease_version": stale_version},
                portfolio_manager_headers,
            )
        )
        # Re-certify so the second reopen attempt is state-legal; the stale
        # version must still be rejected by the OCC check.
        validate_success(api.abstract_lease(lease["id"], make_abstractor_headers("abs-2")))
        validate_success(api.certify_lease(lease["id"], make_certifier_headers("cert-2")))
        resp = api.reopen_abstraction(
            lease["id"], {"expected_lease_version": stale_version},
            portfolio_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestCertifyValidationPriority:
    def test_state_fires_before_segregation_on_certify(self, api):
        """PRD §2.11: "Every request passes through a fixed validation pipeline,
        and the order is part of the contract: an earlier failure masks every
        later check, so the error a client observes is always the earliest
        applicable one."
        PRD §2.11: "Sixth, state-machine legality on every state-transition
        endpoint, else `ERR_INVALID_STATE` (HTTP 409). Seventh, segregation of
        duties as defined in §2.9."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_certify
        """
        lease = _fresh_lease(api)
        validate_success(api.abstract_lease(lease["id"], make_abstractor_headers("abs-1")))
        validate_success(api.certify_lease(lease["id"], make_certifier_headers("cert-1")))
        # Lease already CERTIFIED (state violation) AND caller id equals the
        # recorded abstractor_user_id (would also violate segregation).
        resp = api.certify_lease(lease["id"], make_certifier_headers("abs-1"))
        data = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert data["error_id"] != ApiErrorId.ERR_SEGREGATION_OF_DUTIES

    def test_recertify_by_original_certifier_also_invalid_state(self, api):
        """PRD §2.11: "Sixth, state-machine legality on every state-transition
        endpoint, else `ERR_INVALID_STATE` (HTTP 409). Seventh, segregation of
        duties as defined in §2.9."
        PRD §3.2: "A `Certifier` then reviews and certifies, moving
        `abstraction_status` from `ABSTRACTED` to `CERTIFIED`."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_certify
        """
        lease = _fresh_lease(api)
        validate_success(api.abstract_lease(lease["id"], make_abstractor_headers("abs-1")))
        validate_success(api.certify_lease(lease["id"], make_certifier_headers("cert-1")))
        # Only the state precondition is violated here (cert-1 != abs-1), so
        # the state-machine check is exercised in isolation.
        resp = api.certify_lease(lease["id"], make_certifier_headers("cert-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
