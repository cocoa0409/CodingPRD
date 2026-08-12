"""Agreement lifecycle: signing gates, amendment cycle, OCC, term overlap,
and termination gates."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_DEFAULTS,
    TEST_USERS,
    api_client,
    assert_agreement,
    create_active_host,
    create_agreement_for,
    create_agreement_payload,
    create_hive_payload,
    create_site_for,
    make_host_headers,
    propose_amendment_payload,
    setup_hive_scenario,
    setup_host_with_site,
    setup_signed_agreement,
    sign_agreement_for,
    validate_error,
    validate_success,
)


class TestAgreementInitialState:
    def test_agreement_born_pending_and_blocks_install(self, api, ops_headers):
        """PRD §3.2: "The agreement is born `PENDING_SIGNATURE`."
        PRD §3.3: "the current date to fall within the agreement's term, so
        the agreement must be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE` otherwise)".

        Design: Corner/state_machines/agreement_initial_state_and_unsigned_install_block
        """
        host, site = setup_host_with_site()
        agreement = create_agreement_for(host, site)
        assert agreement["status"] == "PENDING_SIGNATURE", (
            "agreement initial state at creation"
        )
        res = api.create_hive(
            create_hive_payload(site["id"], agreement["id"]),
            TEST_USERS["manager_headers"],
        )
        validate_error(res, "ERR_AGREEMENT_NOT_ACTIVE")


class TestAmendmentCycle:
    def test_reject_restores_active_with_terms_unchanged(self, api):
        """PRD §3.2: "rejecting nulls the pending field with terms unchanged,
        returns to `ACTIVE`, and increments `version`."

        Design: Difficulty/non_linear_state_machine/agreement_amendment_cycle_reject_then_accept
        """
        host, site, agreement = setup_signed_agreement()
        v_after_sign = agreement["version"]

        proposed = validate_success(
            api.propose_amendment(
                agreement["id"],
                propose_amendment_payload(3000, v_after_sign),
                TEST_USERS["ops_headers"],
            ),
            200,
        )
        assert proposed["status"] == "AMENDMENT_PENDING"
        assert proposed["version"] == v_after_sign + 1, (
            "each mutation bumps version by exactly 1"
        )

        rejected = validate_success(
            api.reject_amendment(agreement["id"], make_host_headers(host["id"])),
            200,
        )
        assert rejected["status"] == "ACTIVE", "reject exit restores ACTIVE"
        assert rejected["host_share_base_bps"] == 2500, "terms unchanged"
        assert rejected["pending_host_share_base_bps"] is None
        assert rejected["version"] == v_after_sign + 2

    def test_reject_then_repropose_then_accept_applies_second_terms(self, api):
        """PRD §3.2: "Per §2.9 the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412) when the supplied version does not match the agreement's
        current `version` — this OCC check is the only guard, because proposing
        from either `ACTIVE` or `AMENDMENT_PENDING` is legitimate and a new
        proposal simply supersedes the pending one."
        PRD §3.2: "accepting copies `pending_host_share_base_bps` into
        `host_share_base_bps`, nulls the pending field, returns the agreement
        to `ACTIVE`, and increments `version`."

        Design: Difficulty/non_linear_state_machine/agreement_amendment_cycle_reject_then_accept
        """
        host, site, agreement = setup_signed_agreement()
        v0 = agreement["version"]

        validate_success(
            api.propose_amendment(
                agreement["id"], propose_amendment_payload(3000, v0),
                TEST_USERS["ops_headers"],
            ),
            200,
        )
        rejected = validate_success(
            api.reject_amendment(agreement["id"], make_host_headers(host["id"])),
            200,
        )
        # The cycle is reachable again after the reject exit.
        proposed2 = validate_success(
            api.propose_amendment(
                agreement["id"],
                propose_amendment_payload(3200, rejected["version"]),
                TEST_USERS["ops_headers"],
            ),
            200,
        )
        assert proposed2["version"] == rejected["version"] + 1

        accepted = validate_success(
            api.accept_amendment(agreement["id"], make_host_headers(host["id"])),
            200,
        )
        assert accepted["status"] == "ACTIVE"
        assert accepted["host_share_base_bps"] == 3200, (
            "accept applies the second proposal"
        )
        assert accepted["pending_host_share_base_bps"] is None
        assert accepted["version"] == v0 + 4, (
            "four mutations after signing, each +1"
        )

    def test_pending_proposal_superseded_with_current_version(self, api):
        """PRD §2.9: "Both operations are legitimate self-superseding flows —
        a fresh amendment proposal supersedes a pending one, and a fresh
        change-plan request supersedes a pending plan — so the stale-version
        check is the sole guard against a writer acting on an out-of-date
        view."
        PRD §3.2: "A successful proposal moves the agreement to
        `AMENDMENT_PENDING`, stores the offered value in
        `pending_host_share_base_bps`, and increments `version`."

        Design: Corner/state_machines/amendment_supersede_with_current_version_allowed
        """
        host, site, agreement = setup_signed_agreement()
        v0 = agreement["version"]

        first = validate_success(
            api.propose_amendment(
                agreement["id"], propose_amendment_payload(2800, v0),
                TEST_USERS["ops_headers"],
            ),
            200,
        )
        assert first["version"] == v0 + 1

        second = validate_success(
            api.propose_amendment(
                agreement["id"],
                propose_amendment_payload(2900, first["version"]),
                TEST_USERS["ops_headers"],
            ),
            200,
        )
        assert second["version"] == first["version"] + 1, (
            "each proposal bumps the version by exactly 1"
        )
        assert second["pending_host_share_base_bps"] == 2900, (
            "second proposal superseded the first"
        )
        assert second["status"] == "AMENDMENT_PENDING"


class TestAgreementOCC:
    def test_stale_version_rejected_and_pending_untouched(self, api, ops_headers):
        """PRD §2.9: "Proposing an agreement amendment requires the request
        body to carry `expected_agreement_version` holding the client's last
        observed `version` of the agreement; if the agreement's current
        `version` has advanced past that value, the proposal is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/occ_agreement_stale_version_412
        """
        host, site, agreement = setup_signed_agreement()
        v0 = agreement["version"]

        ok = validate_success(
            api.propose_amendment(
                agreement["id"], propose_amendment_payload(2800, v0),
                ops_headers,
            ),
            200,
        )
        assert ok["version"] == v0 + 1

        res = api.propose_amendment(
            agreement["id"], propose_amendment_payload(2900, v0), ops_headers,
        )
        validate_error(res, "ERR_STALE_VERSION")
        current = validate_success(api.get_agreement(agreement["id"], ops_headers))
        assert current["pending_host_share_base_bps"] == 2800, (
            "the stale writer did not overwrite the pending proposal"
        )


class TestAgreementTermOverlap:
    def _make_agreement(self, host, site, start, end, bps=2500):
        return api_client.create_agreement(
            create_agreement_payload(
                host["id"], site["id"],
                term_start_date=start, term_end_date=end,
                host_share_base_bps=bps,
            ),
            TEST_USERS["ops_headers"],
        )

    def test_shared_end_date_collides(self, api):
        """PRD §3.2: "the new term — treated as a closed interval — must not
        overlap the closed term interval of any other agreement on the same
        site in `PENDING_SIGNATURE`, `ACTIVE`, or `AMENDMENT_PENDING`; an
        overlap is rejected with `ERR_AGREEMENT_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/agreement_term_closed_interval_overlap
        """
        host, site = setup_host_with_site()
        first = validate_success(
            self._make_agreement(host, site, "2026-01-01T00:00:00Z",
                                 "2026-12-31T00:00:00Z"),
            201,
        )
        assert first["status"] == "PENDING_SIGNATURE", (
            "the overlap set includes unsigned agreements"
        )
        # Starting ON the existing term's inclusive end date collides.
        res = self._make_agreement(host, site, "2026-12-31T00:00:00Z",
                                   "2027-06-30T00:00:00Z", bps=2600)
        validate_error(res, "ERR_AGREEMENT_WINDOW_OVERLAP")

    def test_day_after_end_date_is_free(self, api):
        """PRD §3.2: "the new term — treated as a closed interval — must not
        overlap the closed term interval of any other agreement on the same
        site in `PENDING_SIGNATURE`, `ACTIVE`, or `AMENDMENT_PENDING`; an
        overlap is rejected with `ERR_AGREEMENT_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/agreement_term_closed_interval_overlap
        """
        host, site = setup_host_with_site()
        validate_success(
            self._make_agreement(host, site, "2026-01-01T00:00:00Z",
                                 "2026-12-31T00:00:00Z"),
            201,
        )
        created = validate_success(
            self._make_agreement(host, site, "2027-01-01T00:00:00Z",
                                 "2027-06-30T00:00:00Z", bps=2600),
            201,
        )
        assert_agreement(created)
        assert created["status"] == "PENDING_SIGNATURE"


class TestAgreementTermination:
    def test_terminate_blocked_by_live_hive(self, api, ops_headers):
        """PRD §3.2: "Termination — by `PlatformOps` or by the owning host —
        is allowed from `ACTIVE` or `AMENDMENT_PENDING` but only when three
        referential conditions hold simultaneously: no hive under the agreement
        is `ACTIVE` or `QUARANTINED`, no removal job for any hive of the
        agreement sits in `REQUESTED`, `APPROVED`, or `SCHEDULED`, and the
        host's `balance_due_cents` is zero."
        PRD §3.2: "A live hive or in-flight removal yields
        `ERR_AGREEMENT_HAS_LIVE_HIVES`; an unpaid balance yields
        `ERR_OUTSTANDING_BALANCE`."

        Design: Corner/errors/terminate_agreement_with_live_hive_rejected
        """
        ctx = setup_hive_scenario()
        res = api.terminate_agreement(ctx["agreement"]["id"], ops_headers)
        validate_error(res, "ERR_AGREEMENT_HAS_LIVE_HIVES")
        current = validate_success(
            api.get_agreement(ctx["agreement"]["id"], ops_headers),
        )
        assert current["status"] == "ACTIVE", "no drift after rejection"
