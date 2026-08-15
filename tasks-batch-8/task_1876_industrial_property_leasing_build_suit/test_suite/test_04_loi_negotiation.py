"""LOI negotiation cycle, optimistic concurrency, and fiscal gates
(PRD §2.6, §2.8, §3.3)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_loi,
    counter_loi_payload,
    create_draft_loi,
    create_submitted_loi,
    setup_toured_pair,
    submit_loi,
    submit_loi_payload,
    validate_error,
    validate_success,
)

LM = TEST_USERS["leasing_manager_headers"]
REP_1 = TEST_USERS["tenant_rep_1_headers"]


class TestNegotiationCycle:
    def test_loi_counter_cycle_rounds_and_ner_tracking(self, api):
        """PRD §3.3: "A successful submission increments `negotiation_round`
        and `version` by one each and recomputes both derived economics at the
        effective terms." and "those four values replace the standing terms
        outright, round and version each increment, and the economics
        recompute at the countered terms."

        Design: Difficulty/non_linear_state_machine/loi_counter_cycle_rounds
        """
        req, site, _tour = setup_toured_pair()
        loi = create_draft_loi(req["id"], site["id"], REP_1)
        v0 = loi["version"]

        s1 = submit_loi(loi, REP_1)
        assert s1["status"] == "SUBMITTED"
        assert s1["negotiation_round"] == 1
        assert s1["version"] == v0 + 1

        c1 = validate_success(
            api.counter_loi(
                loi["id"],
                counter_loi_payload(
                    s1["version"], base_rate_psf=7.50, ti_allowance_psf=12.00,
                    free_rent_months=6, escalation_pct=0.03,
                ),
                LM,
            )
        )
        assert c1["status"] == "COUNTERED"
        assert c1["negotiation_round"] == 2
        assert c1["version"] == v0 + 2
        assert c1["net_effective_rent_psf"] == pytest.approx(4.81, abs=0.005), (
            f"NER after counter 1 (7.50/12.00 TI/6 free/3%) must be 4.81, "
            f"got {c1['net_effective_rent_psf']}"
        )

        s2 = validate_success(
            api.submit_loi(
                loi["id"], submit_loi_payload(c1["version"]), REP_1
            )
        )
        assert s2["status"] == "SUBMITTED"
        assert s2["negotiation_round"] == 3

        c2 = validate_success(
            api.counter_loi(
                loi["id"],
                counter_loi_payload(
                    s2["version"], base_rate_psf=8.25, ti_allowance_psf=10.00,
                    free_rent_months=6, escalation_pct=0.03,
                ),
                LM,
            )
        )
        assert c2["status"] == "COUNTERED"
        assert c2["negotiation_round"] == 4
        assert c2["version"] == v0 + 4
        assert c2["net_effective_rent_psf"] == pytest.approx(5.94, abs=0.005), (
            f"NER after counter 2 (8.25/10.00 TI/6 free/3%) must be 5.94, "
            f"got {c2['net_effective_rent_psf']}"
        )

    def test_loi_counter_cycle_never_terminates_the_machine(self, api):
        """PRD §3.3: "The tenant may then resubmit (`COUNTERED` → `SUBMITTED`)
        under exactly the same rules as the initial submission, optionally
        revising terms, and the two sides may trade rounds indefinitely."
        PRD §2.6: "Every successful submit or counter itself increments the
        LOI's `version` by one (and advances `negotiation_round`), so a
        client's observed version goes stale the moment the counterparty
        acts."

        Design: Difficulty/non_linear_state_machine/loi_counter_cycle_rounds
        """
        req, site, _tour = setup_toured_pair()
        loi = create_draft_loi(req["id"], site["id"], REP_1)
        current = submit_loi(loi, REP_1)
        expected_round = current["negotiation_round"]
        expected_version = current["version"]
        # Trade three more rounds; the machine must stay negotiable, and each
        # counter advances negotiation_round and version even when it restates
        # the standing economics — the §2.6 increment is unconditional.
        for _ in range(3):
            countered = validate_success(
                api.counter_loi(
                    loi["id"],
                    counter_loi_payload(current["version"]),
                    LM,
                )
            )
            assert countered["status"] == "COUNTERED"
            expected_round += 1
            expected_version += 1
            assert countered["negotiation_round"] == expected_round
            assert countered["version"] == expected_version
            current = validate_success(
                api.submit_loi(
                    loi["id"],
                    submit_loi_payload(countered["version"]),
                    REP_1,
                )
            )
            assert current["status"] == "SUBMITTED"
            expected_round += 1
            expected_version += 1
            assert current["negotiation_round"] == expected_round
            assert current["version"] == expected_version
        final = validate_success(api.get_loi(loi["id"], LM))
        assert final["status"] not in ("REJECTED", "WITHDRAWN", "EXECUTED"), (
            f"The negotiation cycle must remain open; got {final['status']}"
        )
        assert_loi(final)


class TestOptimisticConcurrency:
    def test_counter_stale_version_returns_412(self, api):
        """PRD §2.6: "If the LOI's current `version` does not equal
        `expected_loi_version` — because the other side of the negotiation has
        legitimately advanced the document since the client read it — the
        write is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client
        must re-read the LOI before acting again."

        Design: Corner/validations/counter_stale_version_returns_412
        """
        req, site, _tour = setup_toured_pair()
        loi = create_draft_loi(req["id"], site["id"], REP_1)
        stale_version = loi["version"]
        submitted = submit_loi(loi, REP_1)

        stale = api.counter_loi(
            loi["id"], counter_loi_payload(stale_version), LM
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        fresh = validate_success(
            api.counter_loi(
                loi["id"], counter_loi_payload(submitted["version"]), LM
            )
        )
        assert fresh["status"] == "COUNTERED"
        assert fresh["negotiation_round"] == 2


class TestTerminalAndFiscalGates:
    def test_counter_rejected_loi_returns_invalid_state(self, api):
        """PRD §3.3: "A `LeasingManager` rejects a `SUBMITTED` or `COUNTERED`
        LOI, moving it to terminal `REJECTED`." and "`EXECUTED`, `REJECTED`,
        and `WITHDRAWN` are all terminal." PRD §2.8: "terminal states accept
        no further transitions — otherwise `ERR_INVALID_STATE` (409)."

        Design: Corner/state_machines/counter_rejected_loi_returns_invalid_state
        """
        req, site, _tour = setup_toured_pair()
        loi = create_submitted_loi(req["id"], site["id"], REP_1)
        rejected = validate_success(api.reject_loi(loi["id"], LM))
        assert rejected["status"] == "REJECTED"
        resp = api.counter_loi(
            loi["id"], counter_loi_payload(loi["version"]), LM
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_free_rent_over_cap_at_submit_returns_422(self, api):
        """PRD §3.3: "the effective `free_rent_months` — after applying any
        revision in the same call — may not exceed twelve
        (`ERR_FREE_RENT_OVER_CAP`, 422)."

        Design: Corner/validations/free_rent_over_cap_at_submit_returns_422
        """
        req, site, _tour = setup_toured_pair()
        loi = create_draft_loi(req["id"], site["id"], REP_1, free_rent_months=13)
        resp = api.submit_loi(
            loi["id"], submit_loi_payload(loi["version"]), REP_1
        )
        validate_error(resp, ApiErrorId.ERR_FREE_RENT_OVER_CAP)
        after = validate_success(api.get_loi(loi["id"], LM))
        assert after["status"] == "DRAFT"
        assert after["negotiation_round"] == 0, (
            "A rejected submission must not advance negotiation_round"
        )

    def test_ner_below_floor_at_accept_returns_422(self, api):
        """PRD §3.3: "the standing `net_effective_rent_psf` must be at least
        sixty percent of the site's `asking_rate_psf`, the floor computed by
        multiplying the asking rate by 0.60 and rounding half-up to cents
        (`ERR_NER_BELOW_FLOOR`, 422)."

        Design: Corner/validations/ner_below_floor_at_accept_returns_422
        """
        req, site, _tour = setup_toured_pair(
            site_overrides={
                "site_name": "Premium Power Center",
                "asking_rate_psf": 12.00,
            }
        )
        loi = create_submitted_loi(req["id"], site["id"], REP_1)
        assert loi["net_effective_rent_psf"] == pytest.approx(5.69, abs=0.005)
        resp = api.accept_loi(loi["id"], LM)  # floor = 0.60 x 12.00 = 7.20
        validate_error(resp, ApiErrorId.ERR_NER_BELOW_FLOOR)
        after = validate_success(api.get_loi(loi["id"], LM))
        assert after["status"] == "SUBMITTED"
        site_after = validate_success(api.get_site(site["id"], LM))
        assert site_after["status"] == "LISTED", (
            "A failed accept must not reserve the site"
        )


class TestAcceptPrecedenceStateOverFiscal:
    """State legality (precedence 8) masks the NER floor (precedence 16)."""

    def _setup_draft_below_floor(self, api):
        req, site, _tour = setup_toured_pair(
            site_overrides={
                "site_name": "Premium Power Center",
                "asking_rate_psf": 12.00,
            }
        )
        loi = create_draft_loi(req["id"], site["id"], REP_1)
        assert loi["net_effective_rent_psf"] == pytest.approx(5.69, abs=0.005)
        return req, site, loi

    def test_accept_draft_loi_reports_invalid_state_not_ner_floor(self, api):
        """PRD §2.8: "When several checks could fail on the same request, the
        earliest applicable check in the following global order determines the
        rejection; later failures are masked by earlier ones." PRD §3.3:
        "it evaluates four preconditions in order: the transition must be
        legal from the current state (`ERR_INVALID_STATE`); the LOI's site
        must still be `LISTED` (`ERR_SITE_NOT_LISTED`); the site's
        `available_sf` must be at least `leased_sf` (`ERR_INSUFFICIENT_SF`);
        and the standing `net_effective_rent_psf` must be at least sixty
        percent of the site's `asking_rate_psf` ... (`ERR_NER_BELOW_FLOOR`,
        422)."

        Design: Difficulty/priority_pair_validation_conflict/accept_draft_loi_with_ner_below_floor
        """
        _req, _site, loi = self._setup_draft_below_floor(api)
        resp = api.accept_loi(loi["id"], LM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_loi(loi["id"], LM))
        assert after["status"] == "DRAFT", (
            "A state-rejected accept must leave the LOI in DRAFT"
        )

    def test_accept_after_submit_surfaces_masked_ner_floor(self, api):
        """PRD §2.8: "later failures are masked by earlier ones." Once the
        state check passes, the previously masked fiscal check surfaces —
        PRD §3.3: "the standing `net_effective_rent_psf` must be at least
        sixty percent of the site's `asking_rate_psf` ... (`ERR_NER_BELOW_FLOOR`,
        422)."

        Design: Difficulty/priority_pair_validation_conflict/accept_draft_loi_with_ner_below_floor
        """
        _req, _site, loi = self._setup_draft_below_floor(api)
        validate_error(api.accept_loi(loi["id"], LM), ApiErrorId.ERR_INVALID_STATE)
        submitted = submit_loi(loi, REP_1)
        assert submitted["status"] == "SUBMITTED"
        resp = api.accept_loi(loi["id"], LM)
        validate_error(resp, ApiErrorId.ERR_NER_BELOW_FLOOR)
