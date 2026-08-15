"""Service contracts, SLA deadlines, breach cascade, and service credits."""
from test_helpers import (
    ApiErrorId,
    assert_credit_partition_identity,
    assert_service_contract,
    assert_service_credit,
    breach_ticket,
    create_and_activate_contract,
    create_compressor,
    create_facility,
    create_service_ticket_payload,
    list_contract_credits,
    make_contract_manager_headers,
    make_facility_manager_headers,
    make_service_tech_headers,
    open_ticket,
    plus_days,
    plus_seconds,
    set_clock,
    setup_contract_with_breaches,
    setup_ticket_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)

CONTRACT_MGR = make_contract_manager_headers()
TECH = make_service_tech_headers("tech-1")


class TestTicketContractGates:
    def test_ticket_contract_gates(self, api):
        """PRD §3.7: "Creation gates run in order: the facility must be `ACTIVE`
        (`ERR_FACILITY_NOT_ACTIVE`); the facility must have a contract in `ACTIVE` —
        when there is no `ACTIVE` contract and none `SUSPENDED` either, creation is
        rejected with `ERR_NO_ACTIVE_CONTRACT`, and when the facility's latest
        non-terminal contract is `SUSPENDED`, it is rejected with
        `ERR_CONTRACT_SUSPENDED`; finally the compressor must belong to the calling
        facility (`ERR_FACILITY_MISMATCH`)."

        Design: Corner/validations/corner_ticket_contract_gates
        """
        facility = create_facility(name="F-TCG")
        compressor = create_compressor(facility["id"])

        resp = api.create_service_ticket(
            create_service_ticket_payload(
                facility_id=facility["id"], compressor_id=compressor["id"], severity="ROUTINE"
            ),
            make_facility_manager_headers(facility["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_CONTRACT, 409)

        contract = create_and_activate_contract(facility["id"])
        contract = validate_success(api.suspend_service_contract(contract["id"], CONTRACT_MGR))
        assert contract["status"] == "SUSPENDED"

        resp = api.create_service_ticket(
            create_service_ticket_payload(
                facility_id=facility["id"], compressor_id=compressor["id"], severity="ROUTINE"
            ),
            make_facility_manager_headers(facility["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CONTRACT_SUSPENDED, 409)


class TestSlaDeadlineBoundary:
    def test_sla_met_at_exact_deadline(self, api):
        """PRD §3.7: "Recording the response stamps `first_response_at` from the
        logical clock and computes `sla_met`: the SLA is met when the first response
        falls at or before `sla_deadline` — a response exactly at the deadline
        counts as met, because the comparison is inclusive."
        PRD §3.7: "Two fields derive at creation: `sla_base_hours` from the tier —
        48 hours for `BASIC`, 24 for `STANDARD`, 8 for `PREMIUM` — and `end_date`,
        which falls the same day-of-month exactly `term_months` months after
        `start_date`."

        Design: Difficulty/boundary_precision_check/sla_met_at_exact_deadline
        """
        scenario = setup_ticket_scenario(name="F-B2")
        facility = scenario["facility"]
        compressor = scenario["compressor"]

        t1 = open_ticket(facility["id"], compressor["id"], "URGENT", "2026-08-10T09:00:00Z")
        # STANDARD base 24h x URGENT multiplier 2 = 48h deadline
        assert t1["sla_deadline"] == "2026-08-12T09:00:00Z", (
            f"deadline must be reported_at + 48h, got {t1['sla_deadline']}"
        )
        t1 = validate_success(api.dispatch_ticket(t1["id"], TECH))
        set_clock("2026-08-12T09:00:00Z")
        t1 = validate_success(api.record_response(t1["id"], TECH))
        assert t1["sla_met"] is True, "a response exactly at the deadline is MET"

    def test_sla_breach_one_second_past_deadline(self, api):
        """PRD §3.7: "the SLA is met when the first response falls at or before
        `sla_deadline` — a response exactly at the deadline counts as met, because
        the comparison is inclusive. A missed SLA fires the breach cascade in the
        same request."
        PRD §3.7: "`amount_cents` equal to 5 percent of the contract's gross
        `monthly_fee_cents`, rounded half-up to a whole cent."

        Design: Difficulty/boundary_precision_check/sla_met_at_exact_deadline
        """
        scenario = setup_ticket_scenario(name="F-B2B")
        facility = scenario["facility"]
        compressor = scenario["compressor"]
        contract = scenario["contract"]

        t1 = open_ticket(facility["id"], compressor["id"], "URGENT", "2026-08-10T09:00:00Z")
        validate_success(api.dispatch_ticket(t1["id"], TECH))
        set_clock(t1["sla_deadline"])
        t1 = validate_success(api.record_response(t1["id"], TECH))
        assert t1["sla_met"] is True

        t2 = open_ticket(facility["id"], compressor["id"], "URGENT", "2026-08-12T09:00:00Z")
        assert t2["sla_deadline"] == "2026-08-14T09:00:00Z"
        t2 = breach_ticket(t2, late_seconds=1)
        assert t2["sla_met"] is False, "one second past the deadline is a breach"

        data, meta = validate_paginated(
            api.list_service_credits(CONTRACT_MGR, params={"contract_id": contract["id"]})
        )
        assert meta["total_count"] == 1, "only the breaching ticket accrues a credit"
        assert_service_credit(data[0])
        assert data[0]["amount_cents"] == 20000, "5% of the 400000 gross fee"
        assert data[0]["ticket_id"] == t2["id"]




class TestGrossFeeSnapshot:
    def test_second_credit_uses_gross_fee_after_apply(self, api):
        """PRD §3.7: "The base is deliberately the gross fee snapshot at accrual
        time, never the fee net of previously applied credits, so a credit's amount
        does not depend on the order in which earlier credits were applied."

        Design: Difficulty/combinatorial_formula/sla_credit_gross_fee_snapshot
        """
        scenario = setup_ticket_scenario(name="F-CR")
        facility = scenario["facility"]
        compressor = scenario["compressor"]
        contract = scenario["contract"]

        t1 = open_ticket(facility["id"], compressor["id"], "URGENT", "2026-08-10T09:00:00Z")
        t1 = breach_ticket(t1)
        credits = list_contract_credits(contract["id"])
        cr1 = credits[0]
        assert cr1["amount_cents"] == 20000

        validate_success(api.apply_service_credit(cr1["id"], CONTRACT_MGR))

        t2 = open_ticket(
            facility["id"], compressor["id"], "URGENT", plus_seconds(t1["first_response_at"], 1)
        )
        t2 = breach_ticket(t2)
        credits = list_contract_credits(contract["id"], status="ACCRUED")
        assert len(credits) == 1
        assert credits[0]["amount_cents"] == 20000, (
            f"second credit must still be 5% of the gross 400000 fee, "
            f"got {credits[0]['amount_cents']}"
        )

    def test_credit_counters_after_apply(self, api):
        """PRD §3.7: "The cascade then updates the contract:
        `credits_accrued_total_cents` and `credits_outstanding_cents` each grow by
        the amount"
        PRD §3.7: "A `ContractManager` applies an `ACCRUED` credit — moving it to
        the terminal `APPLIED` state — which decreases the contract's
        `credits_outstanding_cents` and increases
        `credits_applied_total_cents` by the amount."

        Design: Difficulty/combinatorial_formula/sla_credit_gross_fee_snapshot
        """
        scenario = setup_ticket_scenario(name="F-CRB")
        facility = scenario["facility"]
        compressor = scenario["compressor"]
        contract = scenario["contract"]

        t1 = open_ticket(facility["id"], compressor["id"], "URGENT", "2026-08-10T09:00:00Z")
        t1 = breach_ticket(t1)
        cr1 = list_contract_credits(contract["id"])[0]
        validate_success(api.apply_service_credit(cr1["id"], CONTRACT_MGR))

        t2 = open_ticket(
            facility["id"], compressor["id"], "URGENT", plus_seconds(t1["first_response_at"], 1)
        )
        breach_ticket(t2)

        contract = validate_success(api.get_service_contract(contract["id"], CONTRACT_MGR))
        assert_service_contract(contract)
        assert contract["credits_accrued_total_cents"] == 40000
        assert contract["credits_applied_total_cents"] == 20000
        assert contract["credits_outstanding_cents"] == 20000
        assert_credit_partition_identity(contract)


class TestBreachCascadeSuspension:
    def test_third_breach_suspends_contract(self, api):
        """PRD §3.7: "Suspension also arrives uninvited: when a contract's
        `sla_breach_count` reaches 3, the system suspends it from `ACTIVE` to
        `SUSPENDED` automatically and sets `termination_penalty_waived` to true —
        the customer has earned the right to walk away."

        Design: Difficulty/transitive_cascade/sla_breach_cascade_to_contract_suspension
        """
        scenario = setup_contract_with_breaches(3, name="F-SLA")
        contract = validate_success(
            api.get_service_contract(scenario["contract"]["id"], CONTRACT_MGR)
        )
        assert scenario["tickets"][2]["sla_met"] is False
        assert contract["sla_breach_count"] == 3
        assert contract["status"] == "SUSPENDED", "the third breach auto-suspends the contract"
        assert contract["termination_penalty_waived"] is True

    def test_breach_cascade_accumulates_accruals(self, api):
        """PRD §3.7: "The cascade then updates the contract:
        `credits_accrued_total_cents` and `credits_outstanding_cents` each grow by
        the amount, and `sla_breach_count` — which counts the contract's
        ServiceCredit rows of any status — increments by one; when the count thereby
        reaches 3, the contract is automatically suspended and
        `termination_penalty_waived` set, as described above."

        Design: Difficulty/transitive_cascade/sla_breach_cascade_to_contract_suspension
        """
        scenario = setup_contract_with_breaches(3, name="F-SLA2")
        contract = validate_success(
            api.get_service_contract(scenario["contract"]["id"], CONTRACT_MGR)
        )
        assert contract["credits_accrued_total_cents"] == 60000, (
            f"three 20000-cent credits accrue, got {contract['credits_accrued_total_cents']}"
        )
        assert contract["credits_outstanding_cents"] == 60000
        data, meta = validate_paginated(
            api.list_service_credits(CONTRACT_MGR, params={"contract_id": contract["id"]})
        )
        assert meta["total_count"] == 3


class TestCreditLifecycle:
    def test_credit_apply_twice_rejected(self, api):
        """PRD §3.7: "A `ContractManager` applies an `ACCRUED` credit — moving it to
        the terminal `APPLIED` state — which decreases the contract's
        `credits_outstanding_cents` and increases
        `credits_applied_total_cents` by the amount."
        PRD §2.9: "An undeclared transition yields `ERR_INVALID_STATE_TRANSITION`
        (HTTP 409); named gates yield their own errors such as
        `ERR_FACILITY_NOT_ACTIVE` or `ERR_PROFILE_NOT_LOCKED`."

        Design: Corner/state_machines/corner_credit_apply_twice_rejected
        """
        scenario = setup_contract_with_breaches(1, name="F-CR2", severity="EMERGENCY")
        cr1 = scenario["credits"][0]
        validate_success(api.apply_service_credit(cr1["id"], CONTRACT_MGR))

        resp = api.apply_service_credit(cr1["id"], CONTRACT_MGR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)
        cr1 = validate_success(api.get_service_credit(cr1["id"], CONTRACT_MGR))
        assert cr1["status"] == "APPLIED", "a second apply must not move the credit"

    def test_credit_expire_timing(self, api):
        """PRD §3.7: "an `ACCRUED` credit expires to the terminal `EXPIRED` state
        once the logical clock has reached its `expires_at` instant — exactly at
        expiry counts, because the comparison is inclusive, and an earlier attempt
        is rejected with `ERR_CREDIT_NOT_EXPIRED` — moving the amount from
        `credits_outstanding_cents` to `credits_expired_total_cents`."
        PRD §3.7: "`expires_at` exactly ninety days after accrual"

        Design: Corner/validations/corner_credit_expire_timing
        """
        scenario = setup_ticket_scenario(name="F-CEXP")
        facility = scenario["facility"]
        compressor = scenario["compressor"]
        contract = scenario["contract"]

        t1 = open_ticket(facility["id"], compressor["id"], "EMERGENCY", "2026-08-10T09:00:00Z")
        validate_success(api.dispatch_ticket(t1["id"], TECH))
        set_clock("2026-08-12T09:00:01Z")
        validate_success(api.record_response(t1["id"], TECH))
        cr1 = list_contract_credits(contract["id"])[0]
        assert cr1["accrued_at"] == "2026-08-12T09:00:01Z"
        # expires_at is exactly ninety days after accrual
        assert cr1["expires_at"] == plus_days("2026-08-12T09:00:01Z", 90) == "2026-11-10T09:00:01Z"

        set_clock("2026-11-09T09:00:01Z")
        resp = api.expire_service_credit(cr1["id"], CONTRACT_MGR)
        validate_error(resp, ApiErrorId.ERR_CREDIT_NOT_EXPIRED, 409)

        set_clock("2026-11-10T09:00:01Z")
        cr1 = validate_success(api.expire_service_credit(cr1["id"], CONTRACT_MGR))
        assert cr1["status"] == "EXPIRED", "expiry exactly at expires_at must succeed"

    def test_credit_partition_identity_counters(self, api):
        """PRD §3.7: "Both paths preserve the contract's credit identity:
        `credits_accrued_total_cents` always equals `credits_applied_total_cents`
        plus `credits_expired_total_cents` plus `credits_outstanding_cents`, and the
        accrued total is immutable once added — it is the all-time sum of every
        credit amount ever accrued."

        Design: Difficulty/compensating_invariant/sla_credit_partition_identity
        """
        scenario = setup_contract_with_breaches(2, name="F-INV2")
        contract_id = scenario["contract"]["id"]
        cr1, cr2 = scenario["credits"][0], scenario["credits"][1]

        validate_success(api.apply_service_credit(cr1["id"], CONTRACT_MGR))
        set_clock(cr2["expires_at"])
        validate_success(api.expire_service_credit(cr2["id"], CONTRACT_MGR))

        contract = validate_success(api.get_service_contract(contract_id, CONTRACT_MGR))
        assert contract["credits_accrued_total_cents"] == 40000
        assert contract["credits_applied_total_cents"] == 20000
        assert contract["credits_expired_total_cents"] == 20000
        assert contract["credits_outstanding_cents"] == 0
        assert_credit_partition_identity(contract)

    def test_credit_partition_identity_statuses(self, api):
        """PRD §3.7: "A `ContractManager` applies an `ACCRUED` credit — moving it to
        the terminal `APPLIED` state — which decreases the contract's
        `credits_outstanding_cents` and increases
        `credits_applied_total_cents` by the amount. Alternatively, an `ACCRUED`
        credit expires to the terminal `EXPIRED` state once the logical clock has
        reached its `expires_at` instant"

        Design: Difficulty/compensating_invariant/sla_credit_partition_identity
        """
        scenario = setup_contract_with_breaches(2, name="F-INV2B")
        contract_id = scenario["contract"]["id"]
        cr1, cr2 = scenario["credits"][0], scenario["credits"][1]

        cr1 = validate_success(api.apply_service_credit(cr1["id"], CONTRACT_MGR))
        assert cr1["status"] == "APPLIED"
        set_clock(cr2["expires_at"])
        cr2 = validate_success(api.expire_service_credit(cr2["id"], CONTRACT_MGR))
        assert cr2["status"] == "EXPIRED"

        contract = validate_success(api.get_service_contract(contract_id, CONTRACT_MGR))
        assert_credit_partition_identity(contract)
        assert contract["credits_outstanding_cents"] == 0


class TestContractExpiry:
    def test_contract_expire_timing(self, api):
        """PRD §3.7: "Expiry is a separate terminal path from `ACTIVE` to `EXPIRED`,
        available only when the logical clock's date is strictly after `end_date` —
        the contract becomes expirable the day after its end date at the earliest,
        and an attempt on or before that date is rejected with
        `ERR_CONTRACT_NOT_EXPIRED`."
        PRD §3.7: "and `end_date`, which falls the same day-of-month exactly
        `term_months` months after `start_date`."

        Design: Corner/validations/corner_contract_expire_timing
        """
        facility = create_facility(name="F-EXP")
        contract = create_and_activate_contract(
            facility["id"], start_date="2026-08-01", term_months=12
        )
        assert contract["end_date"] == "2027-08-01", (
            f"2026-08-01 + 12 months keeps the day-of-month, got {contract['end_date']}"
        )

        set_clock("2027-08-01T00:00:00Z")
        resp = api.expire_service_contract(contract["id"], CONTRACT_MGR)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_EXPIRED, 409)

        set_clock("2027-08-02T00:00:00Z")
        contract = validate_success(api.expire_service_contract(contract["id"], CONTRACT_MGR))
        assert contract["status"] == "EXPIRED"
