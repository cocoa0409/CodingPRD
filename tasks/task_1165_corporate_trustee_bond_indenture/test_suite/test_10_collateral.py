"""Collateral release and substitution: pinned coverage evaluation order,
inclusive coverage floor, default lock, valuation freshness, substitute
field presence, effect-time item transition, OCC (PRD §3.7, §2.7, §2.8)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId,
    CLOCK_START, set_clock,
    setup_collateral_scenario, setup_verified_release_request,
    create_release_request, verify_release_request, decide_release_request,
    effect_release_request, declare_default, confirm_default,
    get_release_request, get_collateral_item, get_indenture,
    get_success_data, create_collateral_item_payload,
    create_substitution_request_payload, create_release_request_payload,
    setup_indenture_with_positions, register_collateral,
    assert_collateral_release_request, assert_collateral_item,
    make_trust_officer_headers, make_trust_manager_headers,
    make_issuer_headers,
)

OFFICER = make_trust_officer_headers("officer-1")
MANAGER = make_trust_manager_headers("manager-1")


class TestSubstituteHaircutEvaluationOrder:
    def _setup_substitution_scenario(self, api):
        """Outstanding 1000000000; C1 SECURITIES 800000000 (pledged at the
        500 bps haircut: 760000000); C2 REAL_ESTATE 500000000 under a
        SUBSTITUTION request with a SECURITIES substitute appraised
        470000000."""
        return setup_collateral_scenario(
            position_principal=1000000000,
            item1_type="SECURITIES", item1_value=800000000,
            item2_type="REAL_ESTATE", item2_value=500000000,
            request_type="SUBSTITUTION", substitute_value=470000000)

    def test_substitute_haircut_tier_selected_before_inclusion(self, api):
        """PRD §3.7: "First, value every `PLEDGED` collateral item of the
        indenture excluding the item under request, each at its
        `appraised_value_cents` discounted by its type haircut — 2000 basis
        points for `REAL_ESTATE`, 3000 for `EQUIPMENT`, 500 for `SECURITIES`,
        and 4000 for `GUARANTEE` — and sum. Second, divide that coverage by
        the indenture's `outstanding_principal_cents`: when the ratio is at
        least 2.00 the substitute is valued at a 1000-basis-point haircut,
        otherwise at 2500 basis points."

        Coverage excluding the request is 760000000/1000000000 = 0.76 < 2.00,
        so the STANDARD 2500 bps substitute haircut applies: substitute
        contribution 470000000*0.75 = 352500000, and per the fourth step
        floor((760000000+352500000)*10000/1000000000) = 11125.

        Design: Difficulty/combinatorial_formula/collateral_substitute_haircut_evaluation_order
        """
        ctx = self._setup_substitution_scenario(api)
        request = verify_release_request(ctx["request"]["id"], officer_id="officer-1")
        assert request["post_release_coverage_bps"] == 11125, (
            f"pinned evaluation order: expected 11125, "
            f"got {request['post_release_coverage_bps']} — the substitute "
            f"haircut tier is selected from coverage computed WITHOUT the "
            f"substitute")

    def test_verify_marks_request_verified_with_coverage(self, api):
        """PRD §3.7: "Fourth, `post_release_coverage_bps` is the total
        post-release coverage multiplied by ten thousand and divided by the
        indenture's `outstanding_principal_cents`, rounded down to a whole
        basis point. Verification records `verified_by_user_id` and moves the
        request to `VERIFIED`."

        Design: Difficulty/combinatorial_formula/collateral_substitute_haircut_evaluation_order
        """
        ctx = self._setup_substitution_scenario(api)
        request = verify_release_request(ctx["request"]["id"], officer_id="officer-1")
        assert_collateral_release_request(request)
        assert request["status"] == "VERIFIED"
        assert request["verified_by_user_id"] == "officer-1"
        assert isinstance(request["post_release_coverage_bps"], int)
        assert request["post_release_coverage_bps"] == 11125


class TestCoverageFloorBoundary:
    def _setup_exact_floor_scenario(self, api):
        """Outstanding 760000000 (tranche + single position); C1 SECURITIES
        appraised 1000000000 (pledged 950000000 after the 500 bps haircut);
        C2 EQUIPMENT 300000000 is the RELEASE target. Post-release coverage:
        floor(950000000*10000/760000000) == 12500 exactly."""
        ctx = setup_collateral_scenario(
            position_principal=760000000,
            item1_type="SECURITIES", item1_value=1000000000,
            item2_type="EQUIPMENT", item2_value=300000000,
            request_type="RELEASE")
        ctx["request"] = verify_release_request(ctx["request"]["id"],
                                                officer_id="officer-1")
        return ctx

    def test_coverage_exactly_at_floor_approves(self, api):
        """PRD §3.7: "then, for approval, the coverage floor —
        `post_release_coverage_bps` must be at least 12500 (that is, coverage
        of at least 125 percent of outstanding principal), with equality
        approving and a shortfall rejected as `ERR_COVERAGE_BELOW_MINIMUM`
        (HTTP 422)."

        Design: Difficulty/boundary_precision_check/coverage_floor_inclusive_boundary_on_decide
        """
        ctx = self._setup_exact_floor_scenario(api)
        request = ctx["request"]
        assert request["post_release_coverage_bps"] == 12500, (
            f"floor construction: expected exactly 12500, "
            f"got {request['post_release_coverage_bps']}")

        decided = decide_release_request(request["id"], "APPROVE", manager_id="manager-1")
        assert decided["status"] == "APPROVED", "equality with the floor approves"

    def test_coverage_floor_decision_records_decider(self, api):
        """PRD §3.7: "A decided request becomes `APPROVED` or `REJECTED` with
        `decided_by_user_id` recorded."

        Design: Difficulty/boundary_precision_check/coverage_floor_inclusive_boundary_on_decide
        """
        ctx = self._setup_exact_floor_scenario(api)
        decided = decide_release_request(ctx["request"]["id"], "APPROVE",
                                         manager_id="manager-1")
        assert decided["status"] == "APPROVED"
        assert decided["decided_by_user_id"] == "manager-1"
        assert decided["verified_by_user_id"] == "officer-1"
        assert decided["decided_by_user_id"] != decided["verified_by_user_id"]


class TestDefaultLock:
    def _setup_locked_low_coverage(self, api):
        """VERIFIED substitution below the coverage floor (11050 < 12500)
        AND a CONFIRMED default case — both rule 7 and rule 13 fire."""
        ctx = setup_verified_release_request(
            position_principal=1000000000,
            item1_type="SECURITIES", item1_value=800000000,
            item2_type="REAL_ESTATE", item2_value=500000000,
            request_type="SUBSTITUTION", substitute_value=460000000)
        case = declare_default(ctx["indenture"]["id"], default_type="PAYMENT",
                               officer_id="officer-1")
        confirm_default(case["id"], manager_id="manager-1")
        ctx["case"] = case
        return ctx

    def test_default_lock_precedes_coverage_shortfall(self, api):
        """PRD §3.7: "The decision belongs to a `TrustManager` carrying a
        `decision` of approve or reject, and its checks run in a fixed order:
        segregation of duties first — the decider's `X-User-ID` must differ
        from `verified_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`; then
        the default lock — a decision is rejected with `ERR_DEFAULT_LOCK`
        while any default case of the indenture is `CONFIRMED` or
        `ACCELERATED`; then, for approval, the coverage floor —
        `post_release_coverage_bps` must be at least 12500 (that is, coverage
        of at least 125 percent of outstanding principal), with equality
        approving and a shortfall rejected as `ERR_COVERAGE_BELOW_MINIMUM`
        (HTTP 422)."
        PRD §2.8: "when several rules are violated at once the rejection
        carries the error of the **earliest** rule in the stack."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_collateral_decide
        """
        ctx = self._setup_locked_low_coverage(api)
        assert ctx["request"]["post_release_coverage_bps"] == 11050, (
            "coverage violation also present (11050 < 12500)")

        resp = api.decide_collateral_release_request(
            ctx["request"]["id"], {"decision": "APPROVE"}, MANAGER)
        error = validate_error(resp, ApiErrorId.ERR_DEFAULT_LOCK)
        assert error["error_id"] != "ERR_COVERAGE_BELOW_MINIMUM", (
            "default lock (priority 7) precedes the coverage floor (13)")

    def test_default_lock_leaves_request_verified(self, api):
        """PRD §3.7: "then the default lock — a decision is rejected with
        `ERR_DEFAULT_LOCK` while any default case of the indenture is
        `CONFIRMED` or `ACCELERATED`"

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_collateral_decide
        """
        ctx = self._setup_locked_low_coverage(api)
        api.decide_collateral_release_request(
            ctx["request"]["id"], {"decision": "APPROVE"}, MANAGER)

        request_after = get_release_request(ctx["request"]["id"])
        assert request_after["status"] == "VERIFIED", "rejection changes nothing"
        indenture = get_indenture(ctx["indenture"]["id"])
        assert indenture["status"] == "DEFAULTED"
        assert indenture["active_default_count"] == 1

    def _setup_locked_good_coverage(self, api):
        """VERIFIED substitution comfortably above the floor
        ((950000000+352500000)*10000/1000000000 = 13025 >= 12500), then a
        CONFIRMED default — the only failing check is the default lock."""
        ctx = setup_verified_release_request(
            position_principal=1000000000,
            item1_type="SECURITIES", item1_value=1000000000,
            item2_type="REAL_ESTATE", item2_value=500000000,
            request_type="SUBSTITUTION", substitute_value=470000000)
        case = declare_default(ctx["indenture"]["id"], default_type="CROSS_DEFAULT",
                               officer_id="officer-1")
        confirm_default(case["id"], manager_id="manager-1")
        ctx["case"] = case
        return ctx

    def test_decide_blocked_while_default_confirmed(self, api):
        """PRD §3.7: "then the default lock — a decision is rejected with
        `ERR_DEFAULT_LOCK` while any default case of the indenture is
        `CONFIRMED` or `ACCELERATED`"

        Design: Difficulty/cross_entity_state_dependency/collateral_decide_gated_by_default_case_state
        """
        ctx = self._setup_locked_good_coverage(api)
        assert ctx["request"]["post_release_coverage_bps"] == 13025, (
            "coverage floor satisfied — the gate is purely the DefaultCase state")

        resp = api.decide_collateral_release_request(
            ctx["request"]["id"], {"decision": "APPROVE"}, MANAGER)
        validate_error(resp, ApiErrorId.ERR_DEFAULT_LOCK)

    def test_default_lock_gate_is_case_state_not_coverage(self, api):
        """PRD §3.7: "then the default lock — a decision is rejected with
        `ERR_DEFAULT_LOCK` while any default case of the indenture is
        `CONFIRMED` or `ACCELERATED`; then, for approval, the coverage floor —
        `post_release_coverage_bps` must be at least 12500"

        Design: Difficulty/cross_entity_state_dependency/collateral_decide_gated_by_default_case_state
        """
        ctx = self._setup_locked_good_coverage(api)
        api.decide_collateral_release_request(
            ctx["request"]["id"], {"decision": "APPROVE"}, MANAGER)

        request_after = get_release_request(ctx["request"]["id"])
        assert request_after["status"] == "VERIFIED", "request unchanged"
        assert request_after["post_release_coverage_bps"] == 13025
        case = get_success_data(api.get_default_case(ctx["case"]["id"], OFFICER))
        assert case["status"] == "CONFIRMED"


class TestCoverageFloorViolation:
    def test_coverage_below_minimum_rejected_at_decide(self, api):
        """PRD §3.7: "`post_release_coverage_bps` must be at least 12500
        (that is, coverage of at least 125 percent of outstanding principal),
        with equality approving and a shortfall rejected as
        `ERR_COVERAGE_BELOW_MINIMUM` (HTTP 422)."

        No default exists, so the floor itself fires: (760000000 pledged +
        345000000 substitute contribution) * 10000 / 1000000000 = 11050.

        Design: Corner/validations/coverage_below_minimum_clean_trigger
        """
        ctx = setup_verified_release_request(
            position_principal=1000000000,
            item1_type="SECURITIES", item1_value=800000000,
            item2_type="REAL_ESTATE", item2_value=500000000,
            request_type="SUBSTITUTION", substitute_value=460000000)
        assert ctx["request"]["post_release_coverage_bps"] == 11050

        resp = api.decide_collateral_release_request(
            ctx["request"]["id"], {"decision": "APPROVE"}, MANAGER)
        validate_error(resp, ApiErrorId.ERR_COVERAGE_BELOW_MINIMUM)


class TestSubstitutionEffect:
    def test_substitution_effect_creates_substitute_item(self, api):
        """PRD §3.7: "the request becomes `EFFECTED`, and the item moves to
        `RELEASED` for a release or to `SUBSTITUTED` for a substitution, in
        which case a new `CollateralItem` is auto-created in `PLEDGED` status
        from the `substitute_*` fields with its `substituted_from_item_id`
        pointing back at the original item."
        PRD §3.7: "the collateral listing doubles as the discovery channel
        for substitution-created items."

        Design: Corner/state_machines/substitution_effect_creates_substitute_item
        """
        ctx = setup_verified_release_request(
            position_principal=1000000000,
            item1_type="SECURITIES", item1_value=1000000000,
            item2_type="REAL_ESTATE", item2_value=500000000,
            request_type="SUBSTITUTION", substitute_value=470000000)
        decide_release_request(ctx["request"]["id"], "APPROVE", manager_id="manager-1")

        effected = effect_release_request(ctx["request"]["id"], officer_id="officer-1")
        assert effected["status"] == "EFFECTED"

        original = get_collateral_item(ctx["c2"]["id"])
        assert original["status"] == "SUBSTITUTED"

        items = get_success_data(api.list_collateral_items(
            OFFICER, params={"indenture_id": ctx["indenture"]["id"]}))
        substitutes = [i for i in items
                       if i.get("substituted_from_item_id") == ctx["c2"]["id"]]
        assert len(substitutes) == 1, "exactly one substitute item auto-created"
        substitute = substitutes[0]
        assert_collateral_item(substitute)
        assert substitute["status"] == "PLEDGED"
        assert substitute["appraised_value_cents"] == 470000000
        assert substitute["collateral_type"] == "SECURITIES"


class TestValuationAndFieldPresence:
    def test_stale_valuation_rejected_at_request_creation(self, api):
        """PRD §3.7: "Valuation freshness is enforced both at request
        creation and at verification: the item's `valuation_date` — and, for
        substitutions, the substitute's `substitute_valuation_date` — must
        lie within 180 days of the acting date, and a valuation more than 180
        days old is rejected with `ERR_VALUATION_STALE` (HTTP 422)."

        Valuation 2026-01-01 against acting date 2026-08-01: 212 days.

        Design: Corner/validations/stale_collateral_valuation_rejected
        """
        set_clock(CLOCK_START)
        ctx = setup_indenture_with_positions(
            amounts=(400000000,), holder_prefixes=("H-A",),
            tranche_overrides={"series_code": "T1", "original_principal_cents": 400000000},
            reset_clock=False)
        item = register_collateral(ctx["indenture"]["id"], "C2", "REAL_ESTATE",
                                   500000000, valuation_date="2026-01-01")
        set_clock("2026-08-01T00:00:00Z")

        payload = create_release_request_payload(
            item["id"], expected_collateral_item_version=item["version"])
        resp = api.create_collateral_release_request(payload, make_issuer_headers("issuer-1"))
        validate_error(resp, ApiErrorId.ERR_VALUATION_STALE)

    def test_substitution_missing_fields_rejected(self, api):
        """PRD §3.7: "A `SUBSTITUTION` request additionally requires
        `substitute_description`, `substitute_collateral_type` (the same
        four-type enumeration), `substitute_appraised_value_cents`, and
        `substitute_valuation_date`; a substitution missing any of them is
        rejected with `ERR_SUBSTITUTE_REQUIRED` (HTTP 400)."

        Design: Corner/validations/substitution_missing_fields_rejected
        """
        ctx = setup_collateral_scenario(
            position_principal=400000000,
            item1_type="SECURITIES", item1_value=800000000,
            item2_type="REAL_ESTATE", item2_value=500000000,
            request_type="RELEASE")
        c2 = get_collateral_item(ctx["c2"]["id"])
        payload = {
            "collateral_item_id": c2["id"],
            "request_type": "SUBSTITUTION",
            "expected_collateral_item_version": c2["version"],
        }
        resp = api.create_collateral_release_request(payload, make_issuer_headers("issuer-1"))
        validate_error(resp, ApiErrorId.ERR_SUBSTITUTE_REQUIRED)


class TestReleaseRequestOcc:
    def test_release_request_occ_and_supersede(self, api):
        """PRD §2.7: "A `POST /collateral-release-requests` request must
        carry `expected_collateral_item_version` matching the target
        collateral item's current `version`. Because creating a request
        supersedes any `SUBMITTED` request on the same item (and advances the
        item's version), a stale view is rejected with `ERR_STALE_VERSION`."
        PRD §3.7: "Creating a request supersedes any `SUBMITTED` sibling on
        the same item (which becomes `SUPERSEDED`), increments the item's
        `version` by one, and starts the request `SUBMITTED`."

        Design: Corner/complexity_layers/occ_release_request_stale_item_and_supersede
        """
        set_clock(CLOCK_START)
        ctx = setup_indenture_with_positions(
            amounts=(400000000,), holder_prefixes=("H-A",),
            tranche_overrides={"series_code": "T1", "original_principal_cents": 400000000},
            reset_clock=False)
        item = register_collateral(ctx["indenture"]["id"], "C2", "REAL_ESTATE",
                                   500000000, valuation_date="2026-04-01")
        observed_version = item["version"]
        issuer = make_issuer_headers("issuer-1")

        first = validate_success(api.create_collateral_release_request(
            create_release_request_payload(
                item["id"], expected_collateral_item_version=observed_version),
            issuer), 201)
        assert first["status"] == "SUBMITTED"

        # Replay of the same captured version is stale after the first create.
        resp = api.create_collateral_release_request(
            create_release_request_payload(
                item["id"], expected_collateral_item_version=observed_version),
            issuer)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        current = get_collateral_item(item["id"])
        second = validate_success(api.create_collateral_release_request(
            create_release_request_payload(
                item["id"], expected_collateral_item_version=current["version"]),
            issuer), 201)
        assert second["status"] == "SUBMITTED"

        first_after = get_release_request(first["id"])
        assert first_after["status"] == "SUPERSEDED", "in-flight sibling superseded"
        item_after = get_collateral_item(item["id"])
        assert item_after["version"] == observed_version + 2, (
            "item version advanced by exactly 2 across the two successful creates")
