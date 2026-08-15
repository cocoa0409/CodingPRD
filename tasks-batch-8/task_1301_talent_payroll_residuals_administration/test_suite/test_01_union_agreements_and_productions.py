"""Union agreement ingestion/ratification and production wrap gating."""
from test_helpers import (
    ADMIN,
    TEST_USERS,
    ApiErrorId,
    assert_engagement,
    assert_production,
    create_draft_engagement,
    create_performer,
    create_ratified_agreement,
    create_shooting_production,
    create_timecard_payload,
    create_union_agreement_payload,
    get_engagement,
    get_production,
    get_success_data,
    setup_standard,
    validate_error,
    validate_success,
)

ACCOUNTANT = TEST_USERS["production_accountant_headers"]


class TestUnionAgreementIngestion:
    def test_create_missing_rate_tiers_returns_400(self, api):
        """PRD §2.7: "Generic request-shape validation — a missing required field,
        wrong type, unknown enum member, or negative amount, when no more specific
        rule above fired, is rejected with `ERR_VALIDATION` (HTTP 400)".
        PRD §3.1: "The ingestion payload also carries the agreement's rate table
        and penalty constants: `rate_tiers`".

        Design: Corner/entities/union_agreement_create_missing_required_field_returns_400
        """
        payload = create_union_agreement_payload(union_code="WGA", name="WGA Minimum")
        payload.pop("rate_tiers")
        resp = api.create_union_agreement(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestAgreementRatifyWindowAdjacency:
    """Half-open agreement coverage windows for the same union_code."""

    def _agreement_payload(self, name, effective_from, effective_to):
        return create_union_agreement_payload(
            name=name,
            effective_from=effective_from,
            effective_to=effective_to,
            rate_tiers=[{"tier_code": "T1", "category": "PRINCIPAL",
                         "day_rate_cents": 100000,
                         "ot_daily_threshold_minutes": 480,
                         "ot_multiplier": 1.5}],
            residual_base_pct_by_market={"SYNDICATION": 0.045},
        )

    def test_adjacent_window_ratifies(self, api):
        """PRD §3.1: "Two windows overlap when each starts before the other ends;
        adjacency — one agreement's `effective_to` landing exactly on the other's
        `effective_from` — is permitted and does not block ratification."

        Design: Difficulty/resource_temporal_overlap/agreement_ratify_half_open_window_adjacency
        """
        ag_a = get_success_data(api.create_union_agreement(
            self._agreement_payload("A", "2026-01-01", "2026-06-30"), ADMIN))
        ratified_a = get_success_data(api.ratify_union_agreement(ag_a["id"], ADMIN))
        assert ratified_a["status"] == "RATIFIED"

        # B starts exactly where A ends: boundary touch under half-open semantics.
        ag_b = get_success_data(api.create_union_agreement(
            self._agreement_payload("B", "2026-06-30", "2027-01-01"), ADMIN))
        resp = api.ratify_union_agreement(ag_b["id"], ADMIN)
        ratified_b = validate_success(resp, expected_status=200)
        assert ratified_b["status"] == "RATIFIED", (
            "adjacent window (effective_from == other's effective_to) must ratify")

    def test_overlapping_window_rejected(self, api):
        """PRD §3.1: "Ratification is refused with `ERR_AGREEMENT_WINDOW_OVERLAP`
        when another already-`RATIFIED` agreement with the same `union_code` has a
        half-open effective window overlapping this one."

        Design: Difficulty/resource_temporal_overlap/agreement_ratify_half_open_window_adjacency
        """
        ag_a = get_success_data(api.create_union_agreement(
            self._agreement_payload("A", "2026-01-01", "2026-06-30"), ADMIN))
        get_success_data(api.ratify_union_agreement(ag_a["id"], ADMIN))
        ag_b = get_success_data(api.create_union_agreement(
            self._agreement_payload("B", "2026-06-30", "2027-01-01"), ADMIN))
        get_success_data(api.ratify_union_agreement(ag_b["id"], ADMIN))

        # C [2026-06-29, 2027-01-01) intersects both A and B.
        ag_c = get_success_data(api.create_union_agreement(
            self._agreement_payload("C", "2026-06-29", "2027-01-01"), ADMIN))
        resp = api.ratify_union_agreement(ag_c["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_WINDOW_OVERLAP)

    def test_ratify_twice_rejected(self, api):
        """PRD §3.1: "Attempting to ratify an agreement that is not in `DRAFT`
        status is rejected with `ERR_AGREEMENT_INVALID_STATE`."

        Design: Corner/validations/agreement_ratify_twice_rejected
        """
        agr = create_ratified_agreement()
        resp = api.ratify_union_agreement(agr["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_INVALID_STATE)


class TestProductionWrapGating:
    def test_wrap_blocked_by_pending_engagement(self, api):
        """PRD §3.2: "The advance from `SHOOTING` to `WRAPPED` is gated: it is
        rejected with `ERR_PRODUCTION_HAS_OPEN_ENGAGEMENTS` while any engagement
        of the production remains in `PENDING_APPROVAL` or `AMENDMENT_PENDING`."

        Design: Difficulty/cross_entity_state_dependency/production_wrap_blocked_by_open_engagement
        """
        agr = create_ratified_agreement()
        prod = create_shooting_production(agr["id"])
        perf = create_performer()
        eng = create_draft_engagement(prod["id"], agr["id"], perf["id"])
        get_success_data(api.submit_engagement(eng["id"], ACCOUNTANT))
        resp = api.advance_production(prod["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_PRODUCTION_HAS_OPEN_ENGAGEMENTS)

    def test_wrap_blocked_leaves_production_and_engagement_unchanged(self, api):
        """PRD §3.2: "The advance from `SHOOTING` to `WRAPPED` is gated: it is
        rejected with `ERR_PRODUCTION_HAS_OPEN_ENGAGEMENTS` while any engagement
        of the production remains in `PENDING_APPROVAL` or `AMENDMENT_PENDING`."
        A rejected advance fires no cascade: the production stays SHOOTING and
        the engagement stays PENDING_APPROVAL.

        Design: Difficulty/cross_entity_state_dependency/production_wrap_blocked_by_open_engagement
        """
        agr = create_ratified_agreement()
        prod = create_shooting_production(agr["id"])
        perf = create_performer()
        eng = create_draft_engagement(prod["id"], agr["id"], perf["id"])
        get_success_data(api.submit_engagement(eng["id"], ACCOUNTANT))
        validate_error(api.advance_production(prod["id"], ADMIN),
                       ApiErrorId.ERR_PRODUCTION_HAS_OPEN_ENGAGEMENTS)
        prod_after = get_production(prod["id"])
        assert_production(prod_after)
        assert prod_after["status"] == "SHOOTING", "production must remain SHOOTING"
        eng_after = get_engagement(eng["id"])
        assert_engagement(eng_after)
        assert eng_after["status"] == "PENDING_APPROVAL", (
            "no engagement cascade fires when the advance is rejected")

    def test_wrap_cascades_active_engagements(self, api):
        """PRD §3.2: "When the gate passes, the advance cascades — every engagement
        of the production in `ACTIVE` or `AMENDMENT_PENDING` transitions to
        `WRAPPED` — and the production's `version` increments."
        PRD §3.5: "The engagement must be `ACTIVE`; the production must be
        `SHOOTING`; a violation of either surfaces as `ERR_ENGAGEMENT_NOT_ACTIVE`."

        Design: Corner/state_machines/production_wrap_cascades_active_engagements
        """
        ctx = setup_standard()
        eng = ctx["eng"]
        assert eng["status"] == "ACTIVE"

        wrapped = get_success_data(api.advance_production(ctx["prod"]["id"], ADMIN))
        assert wrapped["status"] == "WRAPPED"
        eng_after = get_engagement(eng["id"])
        assert eng_after["status"] == "WRAPPED", "wrap cascade must wrap ACTIVE engagements"

        payload = create_timecard_payload(eng["id"])
        resp = api.create_timecard(payload, ACCOUNTANT)
        validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_NOT_ACTIVE)
