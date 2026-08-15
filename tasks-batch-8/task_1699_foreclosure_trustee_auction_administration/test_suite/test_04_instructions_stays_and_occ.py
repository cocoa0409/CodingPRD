"""Bidding instructions, stays, and optimistic-concurrency rules on case writes."""
from test_helpers import (
    CM,
    ApiErrorId,
    create_beneficiary,
    create_case,
    file_stay,
    get_case,
    issue_quote,
    make_beneficiary_headers,
    setup_case_at_nots_recorded,
    validate_error,
    validate_paginated,
    validate_success,
)


def _create_instruction(api, case_id, ben_id, version, opening, maximum,
                        strategy="UP_TO_MAX"):
    return api.create_bidding_instruction(
        case_id,
        {
            "opening_bid_cents": opening,
            "max_bid_cents": maximum,
            "strategy": strategy,
            "expected_foreclosure_case_version": version,
        },
        make_beneficiary_headers(ben_id),
    )


class TestInstructionSupersedeCardinality:
    def _case_at_nots(self, api):
        return setup_case_at_nots_recorded("BEN-K2", loan_reference="LN-K2")

    def test_new_instruction_supersedes_prior_active(self, api):
        """PRD §3.5: "On success the prior `ACTIVE` instruction on the case, if any, becomes `SUPERSEDED`, the new instruction begins in `ACTIVE` status, and the case's `version` increments."

        Design: Difficulty/compensating_invariant/bidding_instruction_supersede_active_cardinality
        """
        ctx = self._case_at_nots(api)
        case_id, ben_id = ctx["case"]["id"], ctx["beneficiary"]["id"]
        ins1 = validate_success(
            _create_instruction(api, case_id, ben_id,
                                get_case(case_id)["version"], 42_000_000,
                                43_000_000),
            201,
        )
        assert ins1["status"] == "ACTIVE"
        ins2 = validate_success(
            _create_instruction(api, case_id, ben_id,
                                get_case(case_id)["version"], 41_000_000,
                                43_000_000, strategy="OPENING_ONLY"),
            201,
        )
        assert ins2["status"] == "ACTIVE"
        rows, _meta = validate_paginated(api.list_bidding_instructions(case_id, CM))
        first = next(r for r in rows if r["id"] == ins1["id"])
        assert first["status"] == "SUPERSEDED", (
            f"the create is paired with a compensating supersede, got {first['status']}"
        )

    def test_active_instruction_cardinality_stays_one(self, api):
        """PRD §3.5: "On success the prior `ACTIVE` instruction on the case, if any, becomes `SUPERSEDED`, the new instruction begins in `ACTIVE` status, and the case's `version` increments. A case's instructions may be listed with an optional `status` filter."

        Design: Difficulty/compensating_invariant/bidding_instruction_supersede_active_cardinality
        """
        ctx = self._case_at_nots(api)
        case_id, ben_id = ctx["case"]["id"], ctx["beneficiary"]["id"]
        validate_success(
            _create_instruction(api, case_id, ben_id,
                                get_case(case_id)["version"], 42_000_000,
                                43_000_000),
            201,
        )
        ins2 = validate_success(
            _create_instruction(api, case_id, ben_id,
                                get_case(case_id)["version"], 41_000_000,
                                43_000_000, strategy="OPENING_ONLY"),
            201,
        )
        rows, meta = validate_paginated(
            api.list_bidding_instructions(
                case_id, make_beneficiary_headers(ben_id),
                params={"status": "ACTIVE"},
            )
        )
        assert meta["total_count"] == 1, (
            f"ACTIVE cardinality is conserved at 1, got {meta['total_count']}"
        )
        assert rows[0]["id"] == ins2["id"]


class TestStateBeforeSafetyGate:
    def _referred_case_under_litigation_hold(self, api):
        ben = create_beneficiary("BEN-V1")
        case = create_case(ben["id"], loan_reference="LN-V1")
        file_stay(case["id"], stay_type="LITIGATION_HOLD",
                  court_case_number="CV-26-0001",
                  filed_at="2026-07-31T08:00:00Z")
        return case

    def test_state_error_reported_when_case_referred_and_stayed(self, api):
        """PRD §2.8: "When several checks could reject the same request, they are evaluated in a fixed order so the surfaced error is deterministic. The global precedence ladder is:"
        PRD §2.8: "6. Entity state checks (`ERR_INVALID_CASE_STATE`, `ERR_INVALID_NOTS_STATE`, `ERR_INVALID_SALE_STATE`, `ERR_INVALID_QUOTE_STATE`, `ERR_INVALID_REGISTRATION_STATE`, `ERR_INVALID_CLAIM_STATE`, `ERR_INVALID_DEED_STATE`, `ERR_INVALID_INSTRUCTION_STATE`, `ERR_STAY_NOT_ACTIVE`, `ERR_INVALID_DISBURSEMENT_STATE`)." — item 8 lists the business safety gates (`ERR_ACTIVE_STAY`, `ERR_SEGREGATION_OF_DUTIES`) after the state checks.
        PRD §3.3: "State-driven rejections on this operation surface as `ERR_INVALID_CASE_STATE`, while the premature-recording rejection is `ERR_NOTS_TOO_EARLY`."

        Design: Difficulty/priority_pair_validation_conflict/case_state_error_beats_active_stay
        """
        case = self._referred_case_under_litigation_hold(api)
        resp = api.record_nots(
            case["id"],
            {"recording_date": "2026-08-01", "instrument_number": "NOTS-V1"},
            CM,
        )
        # State (step 6) precedes the safety gate (step 8), so the case-state
        # error surfaces even though an ACTIVE stay also gates the operation.
        validate_error(resp, ApiErrorId.ERR_INVALID_CASE_STATE, 409)

    def test_rejected_recording_creates_no_notice_and_hold_remains(self, api):
        """PRD §2.10: "The posture is `BANKRUPTCY_STAY` whenever any `ACTIVE` stay of a bankruptcy type exists on the case; otherwise `LITIGATION_HOLD` whenever any `ACTIVE` litigation-hold stay exists; otherwise `CLEAR`."
        PRD §3.3: "State-driven rejections on this operation surface as `ERR_INVALID_CASE_STATE`, while the premature-recording rejection is `ERR_NOTS_TOO_EARLY`."

        Design: Difficulty/priority_pair_validation_conflict/case_state_error_beats_active_stay
        """
        case = self._referred_case_under_litigation_hold(api)
        validate_error(
            api.record_nots(
                case["id"],
                {"recording_date": "2026-08-01", "instrument_number": "NOTS-V1"},
                CM,
            ),
            ApiErrorId.ERR_INVALID_CASE_STATE,
            409,
        )
        rows, meta = validate_paginated(api.list_nots(case["id"], CM))
        assert meta["total_count"] == 0 and rows == [], (
            "a rejected recording must not persist a notice"
        )
        assert get_case(case["id"])["hold_status"] == "LITIGATION_HOLD"


class TestInstructionAndStayGuards:
    def test_withdraw_withdrawn_instruction_rejected(self, api):
        """PRD §3.5: "A withdrawal attempted on an instruction that is no longer `ACTIVE` is rejected with `ERR_INVALID_INSTRUCTION_STATE` (HTTP 409)."

        Design: Corner/state_machines/withdraw_withdrawn_instruction_rejected
        """
        ctx = setup_case_at_nots_recorded("BEN-S6", loan_reference="LN-S6")
        case_id, ben_id = ctx["case"]["id"], ctx["beneficiary"]["id"]
        instr = validate_success(
            _create_instruction(api, case_id, ben_id,
                                get_case(case_id)["version"], 42_000_000,
                                43_000_000),
            201,
        )
        headers = make_beneficiary_headers(ben_id)
        validate_success(api.withdraw_bidding_instruction(instr["id"], headers), 200)
        resp = api.withdraw_bidding_instruction(instr["id"], headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_INSTRUCTION_STATE, 409)

    def test_opening_bid_exceeds_max_rejected(self, api):
        """PRD §3.5: "The instruction's own consistency rule requires `opening_bid_cents` not to exceed `max_bid_cents`; a violation is rejected with `ERR_OPENING_BID_EXCEEDS_MAX` (HTTP 422)."

        Design: Corner/errors/opening_bid_exceeds_max_rejected
        """
        ctx = setup_case_at_nots_recorded("BEN-ER5", loan_reference="LN-ER5")
        case_id, ben_id = ctx["case"]["id"], ctx["beneficiary"]["id"]
        resp = _create_instruction(api, case_id, ben_id,
                                   get_case(case_id)["version"], 43_000_000,
                                   42_000_000)
        validate_error(resp, ApiErrorId.ERR_OPENING_BID_EXCEEDS_MAX, 422)
        _rows, meta = validate_paginated(api.list_bidding_instructions(case_id, CM))
        assert meta["total_count"] == 0, "the rejected instruction must not persist"

    def test_stay_release_twice_rejected(self, api):
        """PRD §3.7: "A `CaseManager` releases an `ACTIVE` stay by supplying a non-empty `release_court_order_reference`; a release attempted on a stay that is no longer `ACTIVE` is rejected with `ERR_STAY_NOT_ACTIVE` (HTTP 409)."

        Design: Corner/state_machines/stay_release_twice_rejected
        """
        ben = create_beneficiary("BEN-S8")
        case = create_case(ben["id"], loan_reference="LN-S8")
        stay = file_stay(case["id"], stay_type="LITIGATION_HOLD",
                         court_case_number="CV-26-0008",
                         filed_at="2026-07-31T08:00:00Z")
        validate_success(
            api.release_stay_order(
                stay["id"], {"release_court_order_reference": "ORD-1"}, CM
            ),
            200,
        )
        resp = api.release_stay_order(
            stay["id"], {"release_court_order_reference": "ORD-2"}, CM
        )
        validate_error(resp, ApiErrorId.ERR_STAY_NOT_ACTIVE, 409)


class TestOptimisticConcurrencyOnCaseWrites:
    def test_quote_create_stale_case_version_rejected(self, api):
        """PRD §2.7: "Issuing a quote against a case requires `expected_foreclosure_case_version` to match the case's current `version`. Because a new quote legitimately supersedes the prior issued quote of the same type, a client whose view of the case predates another writer's change is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412) rather than silently superseding a quote it never observed."

        Design: Corner/cross_cutting_complexity_layers/quote_create_stale_case_version_rejected
        """
        ben = create_beneficiary("BEN-L1")
        case = create_case(
            ben["id"], loan_reference="LN-L1",
            unpaid_principal_balance_cents=10_000_000,
            monthly_payment_cents=100_000, months_in_arrears=1,
            late_fee_per_month_cents=5_000, note_rate_pct=4.5,
            last_interest_paid_date="2026-07-20",
        )
        v0 = case["version"]
        quote = issue_quote(case["id"], "PAYOFF", "2026-08-11")
        assert quote["status"] == "ISSUED"
        resp = api.create_quote(
            case["id"],
            {
                "quote_type": "PAYOFF",
                "good_through_date": "2026-08-12",
                "expected_foreclosure_case_version": v0,
            },
            CM,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_CASE_VERSION, 412)
        rows, meta = validate_paginated(api.list_quotes(case["id"], CM))
        assert meta["total_count"] == 1, (
            "the stale write must not create or supersede a quote"
        )
        assert rows[0]["id"] == quote["id"] and rows[0]["status"] == "ISSUED"

    def test_bidding_instruction_stale_case_version_rejected(self, api):
        """PRD §2.7: "Submitting a bidding instruction against a case likewise requires `expected_foreclosure_case_version` to match the case's current `version`, with the same rejection — `ERR_STALE_CASE_VERSION` (HTTP 412) — guarding the supersession of the prior active instruction."

        Design: Corner/cross_cutting_complexity_layers/bidding_instruction_stale_case_version_rejected
        """
        ctx = setup_case_at_nots_recorded("BEN-L2", loan_reference="LN-L2")
        case_id, ben_id = ctx["case"]["id"], ctx["beneficiary"]["id"]
        v0 = get_case(case_id)["version"]
        ins1 = validate_success(
            _create_instruction(api, case_id, ben_id, v0, 42_000_000, 43_000_000),
            201,
        )
        resp = _create_instruction(api, case_id, ben_id, v0, 41_000_000,
                                   43_000_000, strategy="OPENING_ONLY")
        validate_error(resp, ApiErrorId.ERR_STALE_CASE_VERSION, 412)
        rows, _meta = validate_paginated(api.list_bidding_instructions(case_id, CM))
        first = next(r for r in rows if r["id"] == ins1["id"])
        assert first["status"] == "ACTIVE", (
            "the stale writer must not supersede the active instruction"
        )
