"""Quotation negotiation: the OPEN/COUNTERED alternation cycle with its round
cap, optimistic concurrency, party/grade/expiry gates, and accept."""
from test_helpers import (
    ApiErrorId,
    accept_quotation,
    approve_audit,
    counter_quotation,
    create_agent,
    create_audit,
    create_buyer,
    create_quotation,
    create_sourcing_request,
    get_factory,
    get_quotation,
    make_buyer_manager_headers,
    make_factory_rep_headers,
    make_grade_a_factory,
    make_graded_factory,
    set_clock,
    validate_error,
    validate_success,
)


def _quotation_scenario(unit_price_cents=100, moq=1, valid_until="2027-01-01T00:00:00Z"):
    """Buyer + agent + grade-A factory + SR + one OPEN quotation."""
    buyer = create_buyer()
    agent = create_agent()
    factory = make_grade_a_factory(agent["id"])
    sr = create_sourcing_request(buyer["id"], agent["id"], title="Neg")
    quotation = create_quotation(
        sr["id"], factory["id"], unit_price_cents=unit_price_cents, moq=moq,
        valid_until=valid_until,
    )
    return buyer, agent, factory, sr, quotation


def _run_six_counters(buyer, factory, quotation):
    """Six alternating counters: buyer, factory, buyer, factory, buyer, factory."""
    buyer_h = make_buyer_manager_headers(buyer["id"])
    factory_h = make_factory_rep_headers(factory["id"])
    qid = quotation["id"]
    version = quotation["version"]
    last = None
    for headers, price in [
        (buyer_h, 950), (factory_h, 960), (buyer_h, 940),
        (factory_h, 955), (buyer_h, 945), (factory_h, 952),
    ]:
        last = counter_quotation(qid, headers, price, version)
        version = last["version"]
    return last, version


class TestNegotiationCycle:
    def test_quotation_counters_alternate_six_rounds(self, api):
        """PRD: "The state `OPEN` means the factory set the current terms; `COUNTERED` means the buyer set them."
        PRD: "A successful counter increments `round_count` by 1, flips `last_actor_role` to the countering side, replaces `unit_price_cents` (and `valid_until` if supplied) with the payload values, alternates the status between `OPEN` and `COUNTERED`, and increments `Quotation.version` by 1."

        Design: Difficulty/non_linear_state_machine/quotation_counter_alternation_cycle_and_round_cap
        """
        buyer, agent, factory, sr, quotation = _quotation_scenario(unit_price_cents=1000)
        last, version = _run_six_counters(buyer, factory, quotation)
        assert last["round_count"] == 6
        assert last["last_actor_role"] == "FACTORY"
        assert last["status"] == "OPEN"
        assert last["unit_price_cents"] == 952
        assert last["version"] == quotation["version"] + 6

    def test_quotation_seventh_counter_rejected_round_cap(self, api):
        """PRD: "`round_count` must still be below the negotiation round cap of 6 (else `ERR_NEGOTIATION_ROUND_EXCEEDED`)"

        Design: Difficulty/non_linear_state_machine/quotation_counter_alternation_cycle_and_round_cap
        """
        buyer, agent, factory, sr, quotation = _quotation_scenario(unit_price_cents=1000)
        last, version = _run_six_counters(buyer, factory, quotation)
        # Terms are now factory-set, so the buyer is the correct counter party.
        resp = api.counter_quotation(
            quotation["id"],
            {"unit_price_cents": 950, "expected_quotation_version": version},
            make_buyer_manager_headers(buyer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NEGOTIATION_ROUND_EXCEEDED)
        after = get_quotation(quotation["id"])
        assert after["status"] == "OPEN"
        assert after["round_count"] == 6


class TestCounterPartyAndVersion:
    def test_wrong_counter_party_rejected(self, api):
        """PRD: "When the current terms came from `FACTORY`, only a `BuyerManager` may counter; when they came from `BUYER`, only a `FactoryRep` may counter — a violation is rejected with `ERR_WRONG_COUNTER_PARTY`."

        Design: Corner/validations/wrong_counter_party_rejected
        """
        buyer, agent, factory, sr, quotation = _quotation_scenario()
        resp = api.counter_quotation(
            quotation["id"],
            {"unit_price_cents": 98,
             "expected_quotation_version": quotation["version"]},
            make_factory_rep_headers(factory["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_WRONG_COUNTER_PARTY)
        after = get_quotation(quotation["id"])
        assert after["round_count"] == 0
        assert after["unit_price_cents"] == 100

    def test_occ_stale_version_on_quotation_counter(self, api):
        """PRD: "Counter-offering a `Quotation` requires the request body to carry `expected_quotation_version` equal to the quotation's current `version`."
        PRD: "If the supplied expected version no longer matches the entity's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/validations/occ_stale_version_on_quotation_counter
        """
        buyer, agent, factory, sr, quotation = _quotation_scenario()
        stale_version = quotation["version"]
        countered = validate_success(
            api.counter_quotation(
                quotation["id"],
                {"unit_price_cents": 95,
                 "expected_quotation_version": stale_version},
                make_buyer_manager_headers(buyer["id"]),
            )
        )
        assert countered["unit_price_cents"] == 95
        # The factory now replays with the pre-counter (stale) version.
        resp = api.counter_quotation(
            quotation["id"],
            {"unit_price_cents": 97,
             "expected_quotation_version": stale_version},
            make_factory_rep_headers(factory["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        after = get_quotation(quotation["id"])
        assert after["unit_price_cents"] == 95
        assert after["round_count"] == 1


class TestQuotationTerminalStates:
    def test_quotation_reject_from_open_and_terminal_lockdown(self, api):
        """PRD: "The buyer may also reject a quotation outright while it is `OPEN` or `COUNTERED`; rejection moves it to `REJECTED`."
        PRD: "the quotation must be `OPEN` or `COUNTERED` (`ERR_QUOTATION_NOT_OPEN`)"

        Design: Corner/state_machines/quotation_reject_from_open_and_terminal_lockdown
        """
        buyer, agent, factory, sr, quotation = _quotation_scenario()
        rejected = validate_success(
            api.reject_quotation(quotation["id"], make_buyer_manager_headers(buyer["id"]))
        )
        assert rejected["status"] == "REJECTED"

        current = get_quotation(quotation["id"])
        validate_error(
            api.counter_quotation(
                quotation["id"],
                {"unit_price_cents": 90,
                 "expected_quotation_version": current["version"]},
                make_buyer_manager_headers(buyer["id"]),
            ),
            ApiErrorId.ERR_QUOTATION_NOT_OPEN,
        )
        validate_error(
            api.accept_quotation(
                quotation["id"],
                {"ordered_qty": 10, "delivery_month": "2026-09",
                 "expected_quotation_version": current["version"]},
                make_buyer_manager_headers(buyer["id"]),
            ),
            ApiErrorId.ERR_QUOTATION_NOT_OPEN,
        )

    def test_quotation_expired_by_clock_on_accept(self, api, admin_headers):
        """PRD: "Advancing the clock triggers two sweeps: every `VERIFIED` `ComplianceDocument` whose `expires_at` is strictly earlier than the new clock value transitions to `EXPIRED` (with the compliance-posture cascade described in §2.9); and every non-terminal `Quotation` whose `valid_until` is strictly earlier than the new clock value transitions to `EXPIRED`."
        PRD: "the quotation must be `OPEN` or `COUNTERED` (`ERR_QUOTATION_NOT_OPEN`)"

        Design: Corner/validations/quotation_expired_by_clock_on_accept
        """
        # Accept at the default clock (2026-08-01), at-or-before valid_until: OK.
        buyer, agent, factory, sr, quotation = _quotation_scenario(
            valid_until="2026-08-10T00:00:00Z"
        )
        po = accept_quotation(buyer["id"], quotation, ordered_qty=10)
        assert po["status"] == "ACTIVE"

        # A second quotation with the same valid_until is swept once the clock
        # passes it; the accept then fails the state precondition.
        sr2 = create_sourcing_request(buyer["id"], agent["id"], title="E2")
        quotation2 = create_quotation(
            sr2["id"], factory["id"], valid_until="2026-08-10T00:00:00Z"
        )
        set_clock("2026-08-11T00:00:00Z")
        swept = get_quotation(quotation2["id"])
        assert swept["status"] == "EXPIRED"
        validate_error(
            api.accept_quotation(
                quotation2["id"],
                {"ordered_qty": 10, "delivery_month": "2026-09",
                 "expected_quotation_version": swept["version"]},
                make_buyer_manager_headers(buyer["id"]),
            ),
            ApiErrorId.ERR_QUOTATION_NOT_OPEN,
        )


class TestQuotationAcceptGates:
    def test_error_duplicate_quotation_trigger(self, api):
        """PRD: "A third, structural gate enforces that at most one non-terminal quotation exists per (`sourcing_request`, `factory`) pair — attempting a second while one is still live yields `ERR_DUPLICATE_QUOTATION`."

        Design: Corner/errors/error_duplicate_quotation_trigger
        """
        buyer, agent, factory, sr, quotation = _quotation_scenario()
        validate_error(
            api.create_quotation(
                sr["id"],
                {"unit_price_cents": 90, "moq": 1, "lead_time_days": 20,
                 "valid_until": "2027-01-01T00:00:00Z"},
                make_factory_rep_headers(factory["id"]),
            ),
            ApiErrorId.ERR_DUPLICATE_QUOTATION,
        )
        validate_success(
            api.reject_quotation(quotation["id"], make_buyer_manager_headers(buyer["id"]))
        )
        fresh = validate_success(
            api.create_quotation(
                sr["id"],
                {"unit_price_cents": 90, "moq": 1, "lead_time_days": 20,
                 "valid_until": "2027-01-01T00:00:00Z"},
                make_factory_rep_headers(factory["id"]),
            ),
            expected_status=201,
        )
        assert fresh["status"] == "OPEN"

    def test_qty_below_moq_rejected_at_accept(self, api):
        """PRD: "`ordered_qty` must be at least the quotation's `moq` (`ERR_QTY_BELOW_MOQ`)"

        Design: Corner/validations/qty_below_moq_rejected_at_accept
        """
        buyer, agent, factory, sr, quotation = _quotation_scenario(moq=10)
        validate_error(
            api.accept_quotation(
                quotation["id"],
                {"ordered_qty": 9, "delivery_month": "2026-09",
                 "expected_quotation_version": quotation["version"]},
                make_buyer_manager_headers(buyer["id"]),
            ),
            ApiErrorId.ERR_QTY_BELOW_MOQ,
        )
        # The failed accept leaves the quotation OPEN; the boundary value succeeds.
        current = get_quotation(quotation["id"])
        po = accept_quotation(buyer["id"], current, ordered_qty=10)
        assert po["status"] == "ACTIVE"


class TestAcceptGradeGate:
    def _two_factory_grade_scenario(self):
        """One SR with quotations from two factories; the first factory is then
        re-audited down to grade C while the second stays at grade B."""
        buyer = create_buyer()
        agent = create_agent()
        fC = make_graded_factory(
            agent["id"], name="Factory C",
            audit_overrides={"audit_type": "ONSITE", "quality_system_score": 75,
                             "social_compliance_score": 75,
                             "production_capability_score": 75,
                             "financial_stability_score": 75,
                             "critical_findings": 0},
        )
        fB = make_graded_factory(
            agent["id"], name="Factory B", country_code="VN",
            audit_overrides={"audit_type": "ONSITE", "quality_system_score": 75,
                             "social_compliance_score": 75,
                             "production_capability_score": 75,
                             "financial_stability_score": 75,
                             "critical_findings": 0},
        )
        sr = create_sourcing_request(buyer["id"], agent["id"], title="Gate")
        qC = create_quotation(sr["id"], fC["id"], unit_price_cents=100)
        qB = create_quotation(sr["id"], fB["id"], unit_price_cents=100)
        # Advance the logical clock so the re-audit's approved_at is strictly
        # later than the first audit's — PRD resolves multiple approved onsite
        # audits by approved_at (most recent first); identical timestamps
        # (frozen clock) would leave the tie unresolved.
        set_clock("2026-08-02T00:00:00Z")
        # Re-audit factory C down to grade C (50*.40+60*.30+55*.20+55*.10 = 54.5 -> 55).
        downgrade = create_audit(
            fC["id"], agent["id"],
            audit_type="ONSITE", quality_system_score=50,
            social_compliance_score=60, production_capability_score=55,
            financial_stability_score=55, critical_findings=0,
        )
        approve_audit(downgrade["id"])
        return buyer, agent, sr, fC, fB, qC, qB, downgrade

    def test_accept_rejected_when_factory_grade_c(self, api):
        """PRD: "the factory must be `ACTIVE` (`ERR_FACTORY_SUSPENDED`); `latest_audit_grade` must be `A` or `B` (`ERR_FACTORY_GRADE_INSUFFICIENT`)"
        PRD: "approval of an `ONSITE` audit sets `factory.latest_audit_grade` to this audit's grade and `factory.audit_score` to this audit's score, with ties among multiple approved onsite audits resolved by `approved_at` (most recent first), tie-broken by `created_at` ascending"

        Design: Difficulty/cross_entity_state_dependency/quotation_accept_gated_by_factory_audit_grade
        """
        buyer, agent, sr, fC, fB, qC, qB, downgrade = self._two_factory_grade_scenario()
        assert downgrade["score"] == 55
        assert downgrade["grade"] == "C"
        assert get_factory(fC["id"])["latest_audit_grade"] == "C"
        validate_error(
            api.accept_quotation(
                qC["id"],
                {"ordered_qty": 10, "delivery_month": "2026-09",
                 "expected_quotation_version": qC["version"]},
                make_buyer_manager_headers(buyer["id"]),
            ),
            ApiErrorId.ERR_FACTORY_GRADE_INSUFFICIENT,
        )

    def test_accept_succeeds_when_factory_grade_b(self, api):
        """PRD: "the factory must be `ACTIVE` (`ERR_FACTORY_SUSPENDED`); `latest_audit_grade` must be `A` or `B` (`ERR_FACTORY_GRADE_INSUFFICIENT`)"
        PRD: "On success the platform creates the `PurchaseOrder` (status `ACTIVE`, `production_status` `PLACED`, `ordered_qty` and `unit_price_cents` taken from the accept payload / quotation terms)"

        Design: Difficulty/cross_entity_state_dependency/quotation_accept_gated_by_factory_audit_grade
        """
        buyer, agent, sr, fC, fB, qC, qB, downgrade = self._two_factory_grade_scenario()
        po = accept_quotation(buyer["id"], qB, ordered_qty=10)
        assert po["status"] == "ACTIVE"
        assert po["factory_id"] == fB["id"]
