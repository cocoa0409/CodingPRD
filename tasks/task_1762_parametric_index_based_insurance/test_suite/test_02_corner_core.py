"""Queue B (corner design) — entities, state machines, and calculations.

One or more tests per non-stub corner instance; each docstring carries a
verbatim PRD citation plus its `Design: Corner/<section>/<instance.name>` tag.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    activate_index,
    activate_program,
    approve_claim,
    create_and_bind_treaty,
    create_bound_policy,
    create_index,
    create_policyholder,
    create_program,
    create_quoted_policy,
    create_station,
    create_verified_event_with_claim,
    find_event_for_window,
    get_success_data,
    ingest_observation,
    list_claims_for_policy,
    make_claims_adjuster_headers,
    make_treasury_officer_headers,
    setup_active_program,
    setup_paid_claim,
    setup_program_with_bound_policy,
    validate_error,
    validate_paginated,
    validate_success,
    verify_event,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["program_manager_headers"]
ACT = TEST_USERS["actuary_headers"]
UW = TEST_USERS["underwriter_headers"]
ADJ = TEST_USERS["claims_adjuster_headers"]
TRE = TEST_USERS["treasury_officer_headers"]
FRA = TEST_USERS["fraud_analyst_headers"]
DOPS = TEST_USERS["data_operations_headers"]
SVC = TEST_USERS["servicing_agent_headers"]

MISSING = "00000000-0000-0000-0000-000000000000"

TIERS_2 = [
    {"tier": 1, "threshold_value": 50, "payout_fraction": 0.25},
    {"tier": 2, "threshold_value": 30, "payout_fraction": 0.5},
]
TIERS_1 = [{"tier": 1, "threshold_value": 50, "payout_fraction": 0.25}]


# ===========================================================================
# Section entities
# ===========================================================================

class TestProgramCreationDefaults:
    def test_program_created_with_zeroed_aggregates(self, api):
        """PRD §3.1: "A new program begins in `DRAFT` status with its computed
        aggregates — `gross_written_premium_cents`, `incurred_claims_cents`,
        `ceded_recovery_cents`, `net_retained_exposure_cents`, and
        `fraud_alert_count` — all initialized to zero and its `reporting_epoch`
        at zero."

        Design: Corner/entities/program_creation_defaults_and_computed_init
        """
        created = validate_success(api.create_program(
            {
                "program_code": "PRG-E1",
                "peril_type": "WINDSPEED",
                "regulatory_classification": "SURPLUS_LINES",
                "contract_wording_version": "CW-E1",
                "exposure_limit_cents": 5_000_000,
            },
            PM,
        ), expected_status=201)
        assert created["status"] == "DRAFT"
        assert created["gross_written_premium_cents"] == 0
        assert created["reporting_epoch"] == 0
        assert created["version"] == 1
        reread = validate_success(api.get_program(created["id"], ACT))
        assert reread["incurred_claims_cents"] == 0
        assert reread["ceded_recovery_cents"] == 0
        assert reread["net_retained_exposure_cents"] == 0
        assert reread["fraud_alert_count"] == 0


class TestPolicyholderAcknowledgment:
    def test_default_prospect_then_ack_flips_active(self, api):
        """PRD §3.4: "A new policyholder therefore starts as a `PROSPECT`, with
        `basis_risk_disclosure_acknowledged` defaulting to false; if the
        acknowledgment is supplied as true at creation, the status flips to
        `ACTIVE` automatically. Later, a servicing update to the record (which
        may also revise `legal_name`) that flips the acknowledgment from false
        to true while the holder is a `PROSPECT` activates the holder in the
        same automatic fashion."

        Design: Corner/entities/policyholder_creation_default_prospect_and_ack_autoflip
        """
        program = create_program(program_code="PRG-E2")
        holder = validate_success(api.create_policyholder(
            program["id"], {"legal_name": "H-E2", "tax_id": "T-E2"}, SVC
        ), expected_status=201)
        assert holder["basis_risk_disclosure_acknowledged"] is False
        assert holder["status"] == "PROSPECT"
        updated = validate_success(api.update_policyholder(
            program["id"], holder["id"],
            {"basis_risk_disclosure_acknowledged": True}, SVC,
        ))
        assert updated["status"] == "ACTIVE", (
            f"the false->true acknowledgment flip auto-activates; got {updated['status']}"
        )


class TestPolicyQuoteCreatesInvoice:
    def test_quote_computes_premium_and_issues_invoice(self, api):
        """PRD §3.5: "Quotation simultaneously issues the policy's premium
        invoice. The invoice is created in `ISSUED` status with
        `invoice_amount_cents` equal to the sum of `premium_cents` and
        `premium_tax_cents` computed at issuance, an `amount_paid_cents` of
        zero, and a `due_date` equal to the policy's start date"
        PRD §3.5: "The new policy opens with `lifecycle_status` `QUOTED` and
        `settlement_posture` `CLEAR`"

        Design: Corner/entities/policy_creation_computes_premium_and_creates_invoice
        """
        program, station, index = setup_active_program(program_code="PRG-E3")
        holder = create_policyholder(program["id"])
        policy, invoice = create_quoted_policy(
            program["id"], holder["id"], index["id"], sum_insured_cents=2_000_000
        )
        assert policy["premium_cents"] == 300_000
        assert policy["premium_tax_cents"] == 6_000
        assert policy["lifecycle_status"] == "QUOTED"
        assert policy["settlement_posture"] == "CLEAR"
        assert invoice["invoice_amount_cents"] == 306_000
        assert invoice["status"] == "ISSUED"
        assert invoice["due_date"] == "2026-01-01"


class TestObservationAppendOnly:
    def test_observation_carries_no_version_and_sequence_starts_at_one(self, api):
        """PRD §2.5: "The single exception is the **IndexObservation** log.
        Because observations form an append-only event log that is never mutated
        in place (corrections arrive as new rows that supersede old ones), an
        observation carries only `id` and `created_at`; both `updated_at` and
        `version` are absent from it."
        PRD §3.3: "The server stamps each row with a `sequence_no`, a per-index
        monotonic ingestion sequence assigned in arrival order"

        Design: Corner/entities/index_observation_immutability_common_fields_false
        """
        program, station, index = setup_active_program(program_code="PRG-E4")
        obs = validate_success(api.create_observation(
            program["id"], index["id"],
            {"station_id": station["id"], "window_end_date": "2026-06-30",
             "measured_value": 55},
            DOPS,
        ), expected_status=201)
        assert obs["sequence_no"] == 1
        assert obs["is_effective"] is True
        assert "version" not in obs, "append-only log rows must not carry version"
        assert "updated_at" not in obs
        # 55 > 50 under BELOW breaches nothing: no event minted for the window.
        events = get_success_data(api.list_trigger_events_in_program(
            program["id"], ADJ, params={"index_definition_id": index["id"]}
        ))
        assert events == []


class TestNotFoundPerResource:
    def test_resource_specific_404s(self, api):
        """PRD §2.6: "the system validates path identifiers sequentially from
        left to right, rejecting immediately with the 404 error that corresponds
        to the *first* identifier that does not resolve within its parent:
        `ERR_PROGRAM_NOT_FOUND` for a missing program, then
        `ERR_INDEX_NOT_FOUND`, `ERR_STATION_NOT_FOUND`, `ERR_HOLDER_NOT_FOUND`,
        `ERR_POLICY_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`,
        `ERR_CLAIM_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`, or
        `ERR_TREATY_NOT_FOUND` as the position dictates."

        Design: Corner/entities/entity_not_found_errors_per_resource
        """
        program = create_program(program_code="PRG-E5")
        resp = api.get_program(MISSING, ACT)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_FOUND, expected_status=404)
        resp = api.get_index_definition(program["id"], MISSING, ACT)
        validate_error(resp, ApiErrorId.ERR_INDEX_NOT_FOUND, expected_status=404)
        resp = api.get_claim(program["id"], MISSING, ACT)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_FOUND, expected_status=404)


class TestReverseReachability:
    def test_claim_and_invoice_reverse_reads(self, api):
        """PRD §2.6: "Alongside each nested collection, the API exposes flat,
        program-spanning read endpoints — for example, an index definition,
        station, policyholder, policy, invoice, trigger event, claim, dispute,
        or treaty can be fetched directly by its id without walking the parent
        chain, and flat list endpoints accept filters. These
        reverse-reachability reads exist so that foreign-key references such as
        a claim's `trigger_event_id` or a dispute's `claim_id` can be resolved
        in one call."

        Design: Corner/entities/fk_reverse_reachability_lists
        """
        stack = setup_program_with_bound_policy(
            program_code="PRG-E6", trigger_thresholds=TIERS_1
        )
        prog_id = stack["program"]["id"]
        event, claims = create_verified_event_with_claim(stack)
        claim = claims[0]

        sub = validate_paginated(api.list_claims_of_policy(
            prog_id, stack["holder"]["id"], stack["policy"]["id"], SVC
        ))[0]
        assert any(c["id"] == claim["id"] for c in sub)

        by_event = validate_paginated(api.list_claims(
            prog_id, ADJ, params={"trigger_event_id": event["id"]}
        ))[0]
        assert len(by_event) == 1 and by_event[0]["id"] == claim["id"]

        invoices = validate_paginated(api.list_invoices(
            prog_id, SVC, params={"policy_id": stack["policy"]["id"]}
        ))[0]
        assert len(invoices) == 1


# ===========================================================================
# Section state_machines
# ===========================================================================

class TestProgramActivationGate:
    def test_activate_requires_active_index(self, api):
        """PRD §3.1: "Activation moves the program from `DRAFT` to `ACTIVE`, and
        it is gated on substance: at least one of the program's index
        definitions must already be `ACTIVE`, otherwise the activation is
        rejected with `ERR_PROGRAM_NO_ACTIVE_INDEX`."

        Design: Corner/state_machines/program_activate_requires_active_index
        """
        program = create_program(program_code="PRG-S1")
        create_station(program["id"], station_code="ST-S1")
        index = create_index(program["id"], index_code="IDX-S1")
        resp = api.activate_program(program["id"], PM)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_NO_ACTIVE_INDEX, expected_status=409)
        activate_index(program["id"], index["id"])
        activated = validate_success(api.activate_program(program["id"], PM))
        assert activated["status"] == "ACTIVE"


class TestIndexActivationGate:
    def test_index_activate_requires_commissioned_station(self, api):
        """PRD §3.2: "Because an index is only as trustworthy as its feed,
        activation additionally requires at least one station of the parent
        program to be `COMMISSIONED`, failing with `ERR_NO_COMMISSIONED_STATION`
        when the program has none."

        Design: Corner/state_machines/index_activate_requires_commissioned_station
        """
        program = create_program(program_code="PRG-S2")
        station = create_station(program["id"], station_code="ST-S2")
        index = create_index(program["id"], index_code="IDX-S2")
        validate_success(api.take_station_offline(program["id"], station["id"], DOPS))
        resp = api.activate_index(program["id"], index["id"], ACT)
        validate_error(resp, ApiErrorId.ERR_NO_COMMISSIONED_STATION, expected_status=409)
        validate_success(api.recommission_station(program["id"], station["id"], DOPS))
        activated = validate_success(api.activate_index(program["id"], index["id"], ACT))
        assert activated["status"] == "ACTIVE"


class TestProgramSuspendResumeCascade:
    def test_suspend_cascades_index_and_blocks_ingestion_then_resume_restores(self, api):
        """PRD §3.1: "An active program can be suspended; suspension requires
        the program to be `ACTIVE` (otherwise `ERR_PROGRAM_NOT_ACTIVE`) and
        cascades downward, moving every `ACTIVE` index definition of the program
        to `SUSPENDED`."
        PRD §3.3: "the index must not be `SUSPENDED` or `DECOMMISSIONED`
        (`ERR_INDEX_SUSPENDED`)"
        PRD §3.1: "Resuming reverses the cycle: it requires the program to be
        `SUSPENDED` (otherwise `ERR_PROGRAM_NOT_SUSPENDED`), returns the program
        to `ACTIVE`, and cascades every `SUSPENDED` index of the program back to
        `ACTIVE`."

        Design: Corner/state_machines/program_suspend_resume_cascades_index_states
        """
        program, station, index = setup_active_program(program_code="PRG-S3")
        prog_id, idx_id = program["id"], index["id"]
        validate_success(api.suspend_program(prog_id, PM))
        idx = validate_success(api.get_index_definition(prog_id, idx_id, PM))
        assert idx["status"] == "SUSPENDED", "suspend cascades down to the index"
        # Program-status guard (priority 4) fires before the index-state guard
        # (priority 5) per PRD §2.6's fixed global order.
        resp = api.create_observation(
            prog_id, idx_id,
            {"station_id": station["id"], "window_end_date": "2026-06-30",
             "measured_value": 40},
            DOPS,
        )
        validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_ACTIVE, expected_status=409)
        validate_success(api.resume_program(prog_id, PM))
        idx = validate_success(api.get_index_definition(prog_id, idx_id, PM))
        assert idx["status"] == "ACTIVE", "resume restores the suspended index"


class TestPaidClaimTerminalLockdown:
    def test_paid_claim_rejects_adjust_and_decline(self, api):
        """PRD §3.7: "A `ClaimsAdjuster` may adjust a claim standing in
        `GENERATED` or `ADJUSTED` — anything else draws
        `ERR_CLAIM_NOT_ADJUSTABLE`"
        PRD §3.7: "Decline is the adjuster's negative verdict: a claim in
        `GENERATED` or `ADJUSTED` (`ERR_CLAIM_NOT_ADJUSTABLE`) moves to
        `DECLINED`"

        Design: Corner/state_machines/terminal_state_lockdown_paid_claim_rejects_adjust
        """
        stack, _, claim = setup_paid_claim(trigger_thresholds=TIERS_2)
        prog_id = stack["program"]["id"]
        assert claim["final_payout_cents"] == 500_000
        resp = api.adjust_claim(prog_id, claim["id"], {"new_tier": 2}, ADJ)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_ADJUSTABLE, expected_status=409)
        resp = api.decline_claim(prog_id, claim["id"], ADJ)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_ADJUSTABLE, expected_status=409)
        after = validate_success(api.get_claim(prog_id, claim["id"], ADJ))
        assert after["status"] == "PAID"
        assert after["final_payout_cents"] == 500_000


class TestEventVerifyInvalidTransition:
    def test_verify_from_detected_rejected(self, api):
        """PRD §3.6: "The adjuster's verify action requires the event to be
        `UNDER_REVIEW` (otherwise `ERR_EVENT_NOT_UNDER_REVIEW`)"

        Design: Corner/state_machines/trigger_event_invalid_transition_verify_from_detected
        """
        program, station, index = setup_active_program(program_code="PRG-S5")
        ingest_observation(program["id"], index["id"], station["id"], "2026-06-30", 40)
        event = find_event_for_window(program["id"], index["id"], "2026-06-30")
        resp = api.verify_event(program["id"], index["id"], event["id"], ADJ)
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_UNDER_REVIEW, expected_status=409)
        after = validate_success(api.get_trigger_event(
            program["id"], index["id"], event["id"], ADJ
        ))
        assert after["status"] == "DETECTED"


class TestPolicyCancelGuards:
    def test_cancel_blocked_by_open_claim(self, api):
        """PRD §3.5: "it must hold no claim in `GENERATED`, `ADJUSTED`,
        `APPROVED`, `FRAUD_HOLD`, or `PAID` (`ERR_POLICY_HAS_CLAIMS`)."

        Design: Corner/state_machines/policy_cancel_blocked_with_open_claim
        """
        stack = setup_program_with_bound_policy(
            program_code="PRG-S6", trigger_thresholds=TIERS_1
        )
        prog_id = stack["program"]["id"]
        create_verified_event_with_claim(stack)  # leaves a GENERATED claim
        resp = api.cancel_policy(
            prog_id, stack["holder"]["id"], stack["policy"]["id"], UW
        )
        validate_error(resp, ApiErrorId.ERR_POLICY_HAS_CLAIMS, expected_status=409)
        after = validate_success(api.get_policy(
            prog_id, stack["holder"]["id"], stack["policy"]["id"], UW
        ))
        assert after["lifecycle_status"] == "BOUND"


class TestIndexDecommissionGuard:
    def test_decommission_blocked_by_bound_policy_then_succeeds(self, api):
        """PRD §3.2: "Decommissioning, again an `Actuary` action, is the index's
        terminal transition; it is refused with `ERR_INDEX_IN_USE` while any
        policy referencing the index is `BOUND` or while any of the index's
        trigger events stands in `DETECTED` or `UNDER_REVIEW`."

        Design: Corner/state_machines/index_decommission_blocked_by_bound_policy
        """
        stack = setup_program_with_bound_policy(program_code="PRG-S7")
        prog_id = stack["program"]["id"]
        idx_id = stack["index"]["id"]
        resp = api.decommission_index(prog_id, idx_id, ACT)
        validate_error(resp, ApiErrorId.ERR_INDEX_IN_USE, expected_status=409)
        validate_success(api.cancel_policy(
            prog_id, stack["holder"]["id"], stack["policy"]["id"], UW
        ))
        decommissioned = validate_success(api.decommission_index(prog_id, idx_id, ACT))
        assert decommissioned["status"] == "DECOMMISSIONED"


class TestFraudHoldAutoRoute:
    def test_approve_routes_to_fraud_hold_at_threshold_and_clears(self, api):
        """PRD §3.4: "Once a policyholder's `fraud_score` reaches 70, the
        approval gate of §3.7 stops letting their claims pass directly to
        `APPROVED` and routes them to `FRAUD_HOLD` instead."
        PRD §3.7: "When an approve attempt targets a claim whose policyholder's
        `fraud_score` has reached 70, the claim does not become `APPROVED`; it
        is routed to `FRAUD_HOLD` instead, the program's `fraud_alert_count` is
        incremented by one, and the policy posture still rises to
        `PAYMENT_PENDING`. A claim under fraud hold waits for the fraud team: a
        `FraudAnalyst` clears the hold on a claim standing in `FRAUD_HOLD`
        (otherwise `ERR_CLAIM_NOT_IN_FRAUD_HOLD`), which moves the claim to
        `APPROVED`, decrements `fraud_alert_count` by one, and recomputes
        `final_payout_cents` on the same chronological capped formula"
        PRD §3.4: "a manual flag by a `FraudAnalyst` adds 25 points"

        Design: Corner/state_machines/fraud_hold_auto_route_and_clear
        """
        stack = setup_program_with_bound_policy(
            program_code="PRG-S8", trigger_thresholds=TIERS_1
        )
        prog_id = stack["program"]["id"]
        holder_id = stack["holder"]["id"]
        _, claims = create_verified_event_with_claim(stack)
        claim = claims[0]
        holder = None
        for _ in range(3):
            holder = validate_success(api.flag_fraud(prog_id, holder_id, FRA))
        assert holder["fraud_score"] == 75, f"25 x 3 = 75; got {holder['fraud_score']}"
        held = validate_success(api.approve_claim(
            prog_id, claim["id"], make_claims_adjuster_headers("adjuster-1")
        ))
        assert held["status"] == "FRAUD_HOLD", (
            f"fraud_score 75 >= 70 routes to FRAUD_HOLD; got {held['status']}"
        )
        program = validate_success(api.get_program(prog_id, PM))
        assert program["fraud_alert_count"] == 1
        cleared = validate_success(api.clear_fraud_hold(prog_id, claim["id"], FRA))
        assert cleared["status"] == "APPROVED"
        assert cleared["final_payout_cents"] == 500_000
        program = validate_success(api.get_program(prog_id, PM))
        assert program["fraud_alert_count"] == 0


class TestStationOfflineRejectsObservation:
    def test_offline_station_observation_rejected(self, api):
        """PRD §3.2: "while a station is `OFFLINE` — or `DECOMMISSIONED` — new
        observations attributed to it are rejected."
        PRD §3.3: "the producing station must not be `OFFLINE` or
        `DECOMMISSIONED` (`ERR_STATION_OFFLINE`)"

        Design: Corner/state_machines/station_offline_rejects_observation
        """
        program, station, index = setup_active_program(program_code="PRG-S9")
        validate_success(api.take_station_offline(program["id"], station["id"], DOPS))
        resp = api.create_observation(
            program["id"], index["id"],
            {"station_id": station["id"], "window_end_date": "2026-06-30",
             "measured_value": 40},
            DOPS,
        )
        validate_error(resp, ApiErrorId.ERR_STATION_OFFLINE, expected_status=409)
        events = get_success_data(api.list_trigger_events_in_program(
            program["id"], ADJ, params={"index_definition_id": index["id"]}
        ))
        assert events == []


class TestProgramCloseCascade:
    def test_close_blocked_by_open_claim_then_succeeds_and_expires_policies(self, api):
        """PRD §3.1: "Close is refused while any claim in the program stands in
        `GENERATED`, `ADJUSTED`, `APPROVED`, or `FRAUD_HOLD`, and equally while
        any dispute stands in `OPEN` or `AWAITING_CUSTOMER` — both conditions
        surface as `ERR_OPEN_CLAIMS_EXIST`. A successful close moves the program
        to `CLOSED`, expires every policy still `BOUND` (each such policy's
        settlement posture is left unchanged by the cascade), commutes every
        `ACTIVE` reinsurance treaty, and increments the program's `version` by
        one."

        Design: Corner/state_machines/policy_expire_on_end_date_and_close_blocked_by_open_claim
        """
        stack = setup_program_with_bound_policy(
            program_code="PRG-S10", trigger_thresholds=TIERS_1
        )
        prog_id = stack["program"]["id"]
        holder_id = stack["holder"]["id"]
        pol2, _ = create_bound_policy(
            prog_id, holder_id, stack["index"]["id"], sum_insured_cents=1_000_000
        )
        _, claims = create_verified_event_with_claim(stack)
        claim1 = [c for c in claims if c["policy_id"] == stack["policy"]["id"]][0]
        claim2 = [c for c in claims if c["policy_id"] == pol2["id"]][0]
        approve_claim(prog_id, claim1["id"], "adjuster-1")
        validate_success(api.decline_claim(prog_id, claim2["id"], ADJ))

        prog = validate_success(api.get_program(prog_id, PM))
        resp = api.close_program(
            prog_id, {"expected_program_version": prog["version"]}, PM
        )
        validate_error(resp, ApiErrorId.ERR_OPEN_CLAIMS_EXIST, expected_status=409)

        validate_success(api.release_payment(
            prog_id, claim1["id"], make_treasury_officer_headers("treasury-1")
        ))
        prog = validate_success(api.get_program(prog_id, PM))
        closed = validate_success(api.close_program(
            prog_id, {"expected_program_version": prog["version"]}, PM
        ))
        assert closed["status"] == "CLOSED"
        p1 = validate_success(api.get_policy(prog_id, holder_id, stack["policy"]["id"], UW))
        assert p1["lifecycle_status"] == "EXPIRED", (
            "close expires every policy still BOUND"
        )


# ===========================================================================
# Section calculations
# ===========================================================================

class TestBlendModelFallback:
    def test_model_fallback_when_no_physical_rows(self, api):
        """PRD §3.3: "Before blending, the source-priority override is applied:
        when the index is `STATION_PRIMARY` and at least one effective row comes
        from a `PHYSICAL_STATION`, all `GRID_MODEL` rows are excluded from the
        blend; symmetrically, a `MODEL_PRIMARY` index with at least one
        effective `GRID_MODEL` row excludes physical-station rows."
        PRD §3.3: "recording the computed `blended_index_value`, the
        `max_tier_breached`, and the `verification_method` — `STATION_VERIFIED`
        or `MODEL_FALLBACK`, decided by the index's `source_priority_mode` and
        the availability of station data for the window."

        Design: Corner/calculations/blended_value_model_fallback_when_station_offline_at_blend
        """
        program = create_program(program_code="PRG-CALC1")
        gm = create_station(
            program["id"], station_code="GM-1",
            station_kind="GRID_MODEL", reliability_weight=0.5,
        )
        index = create_index(
            program["id"], index_code="IDX-CA1",
            trigger_thresholds=[{"tier": 1, "threshold_value": 70, "payout_fraction": 0.25}],
        )
        activate_index(program["id"], index["id"])
        program = activate_program(program["id"])
        ingest_observation(program["id"], index["id"], gm["id"], "2026-06-30", 60)
        event = find_event_for_window(program["id"], index["id"], "2026-06-30")
        get_success_data(api.open_event_review(program["id"], index["id"], event["id"], ADJ))
        verified = validate_success(api.verify_event(program["id"], index["id"], event["id"], ADJ))
        assert verified["blended_index_value"] == pytest.approx(60.0, abs=0.0001)
        assert verified["verification_method"] == "MODEL_FALLBACK", (
            f"no PHYSICAL row exists despite STATION_PRIMARY; got "
            f"{verified['verification_method']}"
        )


class TestPremiumDerivativeContract:
    def test_derivative_contract_zero_tax(self, api):
        """PRD §3.5: "The program's `regulatory_classification` then selects an
        expense loading — 25% for `ADMITTED_INSURANCE`, 35% for `SURPLUS_LINES`,
        15% for `DERIVATIVE_CONTRACT` — and `premium_cents` is the pure premium
        multiplied by one plus that loading rate, rounded half-up to a whole
        cent. Finally, tax is levied on the loaded premium, never on the pure
        premium: `premium_tax_cents` is `premium_cents` multiplied by the
        classification's tax rate — 2% for `ADMITTED_INSURANCE`, 5% for
        `SURPLUS_LINES`, and 0% for `DERIVATIVE_CONTRACT` — rounded half-up to a
        whole cent."

        Design: Corner/calculations/premium_derivative_contract_zero_tax
        """
        program = create_program(
            program_code="PRG-CALC2", peril_type="EARTHQUAKE_MAGNITUDE",
            regulatory_classification="DERIVATIVE_CONTRACT",
        )
        create_station(program["id"], station_code="ST-CA2")
        index = create_index(
            program["id"], index_code="IDX-CA2", measurement_unit="Mw",
            aggregation_window_days=1,
            trigger_thresholds=[{"tier": 1, "threshold_value": 5, "payout_fraction": 0.25}],
            strike_direction="ABOVE",
            historical_breach_frequency=0.25, expected_loss_ratio=0.4,
        )
        activate_index(program["id"], index["id"])
        activate_program(program["id"])
        holder = create_policyholder(program["id"])
        policy, _ = create_quoted_policy(
            program["id"], holder["id"], index["id"], sum_insured_cents=5_000_000
        )
        # si 5,000,000 x freq 0.25 x elr 0.40 -> pure 500,000; x1.15 loading.
        assert policy["premium_cents"] == 575_000, (
            f"pure 500,000 x 1.15; got {policy['premium_cents']}"
        )
        assert policy["premium_tax_cents"] == 0, (
            f"DERIVATIVE_CONTRACT tax rate is 0%; got {policy['premium_tax_cents']}"
        )


class TestStrikeDirectionAbove:
    def test_above_direction_inclusive_boundary(self, api):
        """PRD §3.3: "The blended value is tested against the index's tiers.
        Under `BELOW` direction, a tier breaches when the blend is less than or
        equal to its `threshold_value`; under `ABOVE`, when the blend is greater
        than or equal. The boundary is inclusive — a value exactly at the
        threshold breaches the tier."
        PRD §3.3: "When the recomputed blend breaches tier 1 or higher and no
        trigger event yet exists for that index and window, the system creates a
        trigger event in `DETECTED` status"

        Design: Corner/calculations/strike_direction_above_breach_semantics
        """
        stack = setup_program_with_bound_policy(
            program_code="PRG-CALC3",
            sum_insured_cents=5_000_000,
            trigger_thresholds=[{"tier": 1, "threshold_value": 5, "payout_fraction": 0.25}],
            strike_direction="ABOVE",
            program_overrides={
                "peril_type": "EARTHQUAKE_MAGNITUDE",
                "regulatory_classification": "DERIVATIVE_CONTRACT",
            },
            index_overrides={
                "measurement_unit": "Mw", "aggregation_window_days": 1,
                "historical_breach_frequency": 0.25, "expected_loss_ratio": 0.4,
            },
        )
        prog_id, idx_id = stack["program"]["id"], stack["index"]["id"]
        st_id = stack["station"]["id"]
        ingest_observation(prog_id, idx_id, st_id, "2026-05-31", 4.9)
        events = get_success_data(api.list_trigger_events_in_program(
            prog_id, ADJ, params={"index_definition_id": idx_id}
        ))
        assert events == [], "4.9 under ABOVE threshold 5 breaches nothing"
        ingest_observation(prog_id, idx_id, st_id, "2026-06-30", 5)
        event = find_event_for_window(prog_id, idx_id, "2026-06-30")
        assert event["status"] == "DETECTED", (
            "exactly 5 breaches tier 1 under inclusive >="
        )


class TestClaimAdjustLoop:
    def test_adjust_loop_recomputes_provisional(self, api):
        """PRD §3.7: "A valid adjustment replaces `tier_applied`, recomputes
        `provisional_payout_cents` on the same forward-looking formula, and
        lands the claim in `ADJUSTED` — a state that permits further adjustment
        loops."

        Design: Corner/calculations/claim_adjust_loop_recomputes_provisional
        """
        stack = setup_program_with_bound_policy(
            program_code="PRG-CALC4",
            sum_insured_cents=2_000_000, trigger_thresholds=TIERS_2,
        )
        prog_id = stack["program"]["id"]
        _, claims = create_verified_event_with_claim(stack, measured_value=30)
        claim = claims[0]
        assert claim["tier_applied"] == 2
        assert claim["provisional_payout_cents"] == 1_000_000
        first = validate_success(api.adjust_claim(
            prog_id, claim["id"], {"new_tier": 1}, ADJ
        ))
        assert first["status"] == "ADJUSTED"
        assert first["tier_applied"] == 1
        assert first["provisional_payout_cents"] == 500_000
        second = validate_success(api.adjust_claim(
            prog_id, claim["id"], {"new_tier": 2}, ADJ
        ))
        assert second["status"] == "ADJUSTED"
        assert second["tier_applied"] == 2
        assert second["provisional_payout_cents"] == 1_000_000


class TestDisputePartialUpheld:
    def test_partial_upheld_half_delta_rounding(self, api):
        """PRD §3.8: "On `PARTIAL_UPHELD`, the delta is half of that same
        difference, rounded half-up to a whole cent."
        PRD §3.8: "while cession is deliberately not re-run on adjustment: the
        claim's `ceded_recovery_cents` stands, and its `net_payment_cents` is
        recomputed simply as the revised `final_payout_cents` minus the
        unchanged `ceded_recovery_cents`."

        Design: Corner/calculations/dispute_partial_upheld_half_delta_rounding
        """
        # measured_value=30 breaches both tiers (30<=50 and 30<=30, inclusive),
        # so the event's max_tier_breached is 2. We then adjust the claim DOWN
        # to tier 1 before approval so that claimed_tier=2 is a valid upward
        # assertion (claimed_tier != tier_applied and <= max_tier_breached).
        stack = setup_program_with_bound_policy(
            program_code="PRG-CALC5", trigger_thresholds=TIERS_2
        )
        prog_id = stack["program"]["id"]
        idx_id = stack["index"]["id"]
        ingest_observation(prog_id, idx_id, stack["station"]["id"], "2026-06-30", 30)
        event = find_event_for_window(prog_id, idx_id, "2026-06-30")
        verify_event(prog_id, idx_id, event["id"])
        claim = list_claims_for_policy(prog_id, stack["policy"]["id"])[0]
        # Adjust down to tier 1, then approve, then release -> final 500,000.
        validate_success(api.adjust_claim(prog_id, claim["id"], {"new_tier": 1}, ADJ))
        claim = approve_claim(prog_id, claim["id"], "adjuster-1")
        claim = validate_success(api.release_payment(
            prog_id, claim["id"], make_treasury_officer_headers("treasury-1")
        ))
        assert claim["final_payout_cents"] == 500_000
        dispute = validate_success(api.create_dispute(
            prog_id, claim["id"],
            {"dispute_reason": "THRESHOLD_BOUNDARY", "claimed_tier": 2}, SVC,
        ), expected_status=201)
        resolved = validate_success(api.resolve_dispute(
            prog_id, claim["id"], dispute["id"], {"resolution": "PARTIAL_UPHELD"}, ADJ
        ))
        assert resolved["adjustment_delta_cents"] == 250_000, (
            f"rhu((1,000,000 - 500,000)/2); got {resolved['adjustment_delta_cents']}"
        )
        after = validate_success(api.get_claim(prog_id, claim["id"], ADJ))
        assert after["final_payout_cents"] == 750_000
        assert after["net_payment_cents"] == 750_000


class TestNetRetainedExposure:
    def test_retention_tracks_binds_treaty_and_cancel(self, api):
        """PRD §3.9: "Let the total active ceded percentage be the sum of
        `ceded_percentage` over the program's `ACTIVE` treaties, capped at 100.
        Then, walking the program's `BOUND` policies in creation order for
        determinism, each policy's ceded share is its `sum_insured_cents`
        multiplied by that total percentage and divided by 100, rounded half-up
        to a whole cent per policy, and each policy contributes its
        `sum_insured_cents` minus its ceded share to the retention. The sum of
        those retained amounts is `net_retained_exposure_cents`, recomputed on
        every bind, cancellation, expiry, and treaty binding."

        Design: Corner/calculations/net_retained_exposure_recomputed_on_bind_and_cancel
        """
        program, station, index = setup_active_program(program_code="PRG-CALC6")
        prog_id = program["id"]
        holder = create_policyholder(prog_id)
        pol1, _ = create_bound_policy(prog_id, holder["id"], index["id"],
                                      sum_insured_cents=2_000_000)
        pol2, _ = create_bound_policy(prog_id, holder["id"], index["id"],
                                      sum_insured_cents=1_000_000)
        program = validate_success(api.get_program(prog_id, PM))
        assert program["net_retained_exposure_cents"] == 3_000_000, (
            f"two BOUND policies, no treaty; got "
            f"{program['net_retained_exposure_cents']}"
        )
        create_and_bind_treaty(
            prog_id, treaty_name="T-30", ceded_percentage=30,
            attachment_point_cents=0, treaty_limit_cents=100_000_000,
        )
        program = validate_success(api.get_program(prog_id, PM))
        assert program["net_retained_exposure_cents"] == 2_100_000, (
            f"1,400,000 + 700,000 after 30% cession; got "
            f"{program['net_retained_exposure_cents']}"
        )
        validate_success(api.cancel_policy(prog_id, holder["id"], pol2["id"], UW))
        program = validate_success(api.get_program(prog_id, PM))
        assert program["net_retained_exposure_cents"] == 1_400_000, (
            f"only P1's retained share remains; got "
            f"{program['net_retained_exposure_cents']}"
        )
