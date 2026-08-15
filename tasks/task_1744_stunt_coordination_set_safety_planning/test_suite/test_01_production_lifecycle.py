"""Production lifecycle: creation defaults, insurance, budget OCC, clock,
stoppage lifting, wrap gate, and the production summary read (PRD §2.5, §2.6,
§3.1, §3.8)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    amend_budget_payload,
    create_active_production,
    create_production,
    create_production_payload,
    create_sequence,
    file_insurance,
    file_insurance_payload,
    get_production,
    is_valid_uuid,
    set_clock,
    stop_production,
    validate_error,
    validate_success,
    EXEC,
    COORD,
)


class TestProductionCreation:
    def test_create_production_defaults(self, api):
        """PRD §3.1: "The new production starts with `posture` `SETUP`,
        `insurance_status` `UNFILED`, `committed_pay_cents` zero, `stopped_at`
        and `stop_reason` null, and `version` 1."
        PRD §2.4: "Every persisted resource carries an `id`, a server-minted
        UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC
        with three fractional digits."

        Design: Corner/entities/ent_production_create_defaults
        """
        resp = api.create_production(
            create_production_payload(name="Fresh Prod", total_budget_cents=5000000), EXEC
        )
        data = validate_success(resp, 201)
        assert data["posture"] == "SETUP"
        assert data["insurance_status"] == "UNFILED"
        assert data["committed_pay_cents"] == 0
        assert data["version"] == 1
        assert data["stopped_at"] is None
        assert data["stop_reason"] is None
        assert is_valid_uuid(data["id"]), "id must be a server-minted UUID"

    def test_get_production_not_found(self, api):
        """PRD §2.7: "Existence of every identifier — path identifiers first,
        then body identifiers — validated left to right, with the first missing
        identifier producing the corresponding not-found error
        (`ERR_PRODUCTION_NOT_FOUND`, `ERR_SEQUENCE_NOT_FOUND`,
        `ERR_ASSESSMENT_NOT_FOUND`, `ERR_PERFORMER_NOT_FOUND`,
        `ERR_CERTIFICATION_NOT_FOUND`, `ERR_REHEARSAL_NOT_FOUND`,
        `ERR_MEETING_NOT_FOUND`, `ERR_SIGNOFF_NOT_FOUND`,
        `ERR_EQUIPMENT_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`,
        `ERR_PERMIT_NOT_FOUND`, `ERR_ADJUSTMENT_NOT_FOUND`,
        `ERR_INCIDENT_NOT_FOUND`, `ERR_EXECUTION_NOT_FOUND`,
        `ERR_REVIEW_NOT_FOUND`)."

        Design: Corner/entities/ent_production_not_found_returns_404
        """
        resp = api.get_production(NON_EXISTENT_UUID, EXEC)
        validate_error(resp, ApiErrorId.ERR_PRODUCTION_NOT_FOUND)


class TestAuthAndClock:
    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "A request missing either header, or naming a role outside
        these six, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
        (HTTP 400)."

        Design: Corner/validations/val_missing_auth_header_returns_400
        """
        # Deliberately send no X-User-ID / X-User-Role headers at all.
        resp = api.list_productions(headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_clock_not_forward_rejected(self, api):
        """PRD §2.5: "the supplied instant must be strictly greater than the
        current logical time, and any attempt to hold or turn the clock back is
        rejected with `ERR_CLOCK_NOT_FORWARD` (HTTP 422)."

        Design: Corner/validations/val_clock_not_forward_rejected
        """
        # The startup default is exactly 2026-08-01T00:00:00Z; equality is not forward.
        resp = api.set_clock({"to_iso8601": "2026-08-01T00:00:00Z"}, EXEC)
        validate_error(resp, ApiErrorId.ERR_CLOCK_NOT_FORWARD)


class TestInsurancePremiumTiers:
    def test_premium_tier_boundary(self, api):
        """PRD §3.1: "Filing computes `endorsement_premium_cents` as the declared
        exposure multiplied by a tiered rate, rounded half up to whole cents: two
        percent when the declared exposure is at most 100,000,000 cents, three
        percent when it is greater than 100,000,000 cents and at most
        500,000,000 cents, and four percent when it exceeds 500,000,000 cents.
        Tier boundaries are inclusive downward, so an exposure of exactly
        100,000,000 cents prices at two percent."

        Design: Corner/calculations/calc_premium_tier_boundary
        """
        prod_a = create_production(name="PA", budget=500000000)
        prod_b = create_production(name="PB", budget=500000000)
        filed_a = validate_success(
            api.file_insurance(prod_a["id"], file_insurance_payload(declared_exposure_cents=100000000), EXEC)
        )
        filed_b = validate_success(
            api.file_insurance(prod_b["id"], file_insurance_payload(declared_exposure_cents=200000000), EXEC)
        )
        assert filed_a["endorsement_premium_cents"] == 2000000, (
            "exactly 100,000,000 cents of exposure prices in the 2% tier"
        )
        assert filed_b["endorsement_premium_cents"] == 6000000, (
            "200,000,000 cents of exposure prices in the 3% tier"
        )


class TestProductionSummary:
    def test_summary_computed_read(self, api):
        """PRD §3.1: "At any time, a computed production summary reports four
        figures: `committed_pay_cents`, `open_negotiation_exposure_cents`,
        `endorsement_premium_cents`, and `estimated_total_cost_cents`." and
        "`estimated_total_cost_cents` is the committed pay plus the open
        negotiation exposure plus the endorsement premium."

        Design: Corner/endpoints/ep_summary_computed_read
        """
        prod = create_production(name="Sum Prod", budget=10000000)
        file_insurance(prod["id"], 50000000)
        resp = api.get_production_summary(prod["id"], EXEC)
        data = validate_success(resp)
        assert data["committed_pay_cents"] == 0
        assert data["open_negotiation_exposure_cents"] == 0
        assert data["endorsement_premium_cents"] == 1000000
        assert data["estimated_total_cost_cents"] == 1000000


class TestStoppageAndWrapGates:
    def test_lift_stoppage_requires_stopped(self, api):
        """PRD §3.8: "Lifting a stoppage is the `ProductionExecutive`'s
        exclusive call and carries three gates. The posture must be `STOPPED`,
        else `ERR_PRODUCTION_NOT_STOPPED`."

        Design: Corner/endpoints/ep_lift_not_stopped_rejected
        """
        prod = create_active_production(name="P", budget=5000000)
        resp = api.lift_stoppage(prod["id"], EXEC)
        validate_error(resp, ApiErrorId.ERR_PRODUCTION_NOT_STOPPED)

    def test_wrap_blocked_then_succeeds(self, api):
        """PRD §3.8: "Finally, when every sequence of the production stands in
        `REVIEWED` or `CANCELLED`, the `ProductionExecutive` wraps the production
        — `ACTIVE → WRAPPED`, terminal. A wrap attempt with any sequence outside
        those two states is rejected with `ERR_SEQUENCES_NOT_TERMINAL`"

        Design: Corner/errors/err_wrap_blocked_then_succeeds
        """
        prod = create_active_production(name="P", budget=5000000)
        seq = create_sequence(prod["id"], name="Wrap Seq")
        resp = api.wrap_production(prod["id"], EXEC)
        validate_error(resp, ApiErrorId.ERR_SEQUENCES_NOT_TERMINAL)
        cancelled = validate_success(api.cancel_sequence(seq["id"], COORD, {"reason": "cut"}))
        assert cancelled["status"] == "CANCELLED"
        wrapped = validate_success(api.wrap_production(prod["id"], EXEC))
        assert wrapped["posture"] == "WRAPPED"


class TestBudgetAmendmentOcc:
    def test_budget_amend_stale_version_rejected(self, api):
        """PRD §2.6: "Third, amending a production's budget requires
        `expected_production_version` matching the production's current
        `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).
        Budget amendments legitimately supersede one another while posture stays
        unchanged, so only the version check distinguishes a stale amendment."

        Design: Corner/cross_cutting_complexity_layers/cc_occ_budget_amend_stale_rejected
        """
        prod = create_production(name="P", budget=10000000)
        first = validate_success(
            api.amend_budget(prod["id"], amend_budget_payload(20000000, prod["version"]), EXEC)
        )
        assert first["total_budget_cents"] == 20000000
        resp = api.amend_budget(prod["id"], amend_budget_payload(30000000, prod["version"]), EXEC)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert get_production(prod["id"])["total_budget_cents"] == 20000000


class TestParallelDimensions:
    def test_activate_requires_filed_insurance(self, api):
        """PRD §3.1: "Activation moves `posture` from `SETUP` to `ACTIVE` and is
        permitted only when insurance is `FILED` or `ACKNOWLEDGED`: an activation
        attempt with insurance still `UNFILED` is rejected with
        `ERR_INSURANCE_NOT_FILED`"
        PRD §3.1: "two percent when the declared exposure is at most 100,000,000
        cents"

        Design: Difficulty/non_linear_state_machine/nsm_production_parallel_dimensions
        """
        prod = create_production(name="Parallel Prod", budget=10000000)
        resp = api.activate_production(prod["id"], EXEC)
        validate_error(resp, ApiErrorId.ERR_INSURANCE_NOT_FILED)
        filed = validate_success(api.file_insurance(prod["id"], file_insurance_payload(), EXEC))
        assert filed["endorsement_premium_cents"] == 1000000
        assert filed["insurance_status"] == "FILED"

    def test_posture_and_insurance_evolve_independently(self, api):
        """PRD §3.1: "These two status fields are parallel state dimensions on
        one entity: `posture` walks `SETUP → ACTIVE → STOPPED → ACTIVE →
        WRAPPED`, while `insurance_status` walks `UNFILED → FILED →
        ACKNOWLEDGED`, and each evolves independently of the other."
        PRD §3.8: "And the logical clock must have reached at least 86,400
        seconds — twenty-four hours — past `stopped_at`, with exact equality
        passing; earlier attempts are rejected with `ERR_STOPPAGE_COOLDOWN`."

        Design: Difficulty/non_linear_state_machine/nsm_production_parallel_dimensions
        """
        prod = create_production(name="Parallel Prod", budget=10000000)
        file_insurance(prod["id"], 50000000)
        activated = validate_success(api.activate_production(prod["id"], EXEC))
        assert activated["posture"] == "ACTIVE"
        assert activated["insurance_status"] == "FILED"
        acked = validate_success(api.acknowledge_insurance(prod["id"], EXEC))
        assert acked["posture"] == "ACTIVE"
        assert acked["insurance_status"] == "ACKNOWLEDGED"
        stop_production(prod["id"], reason="Weather hold")
        # The stoppage happened at the startup default 2026-08-01T00:00:00Z;
        # advancing to exactly +86400s satisfies the cooldown at equality.
        set_clock("2026-08-02T00:00:00Z")
        lifted = validate_success(api.lift_stoppage(prod["id"], EXEC))
        assert lifted["posture"] == "ACTIVE"
        assert lifted["insurance_status"] == "ACKNOWLEDGED", (
            "the stoppage must not touch the insurance dimension"
        )


class TestValidationOrdering:
    def test_existence_beats_posture_gate(self, api):
        """PRD §2.7: "Requests that are structurally sound are then evaluated
        against the domain rule tiers below, in this order; the first failing
        tier determines the rejection." with existence of every identifier at
        tier 3 producing `ERR_SEQUENCE_NOT_FOUND` and the production posture
        gate at tier 5.

        Design: Corner/validations/val_existence_beats_state_priority
        """
        prod = create_active_production(name="P", budget=5000000)
        stop_production(prod["id"], reason="weather")
        resp = api.cancel_sequence(NON_EXISTENT_UUID, COORD, {"reason": "ghost"})
        validate_error(resp, ApiErrorId.ERR_SEQUENCE_NOT_FOUND)
