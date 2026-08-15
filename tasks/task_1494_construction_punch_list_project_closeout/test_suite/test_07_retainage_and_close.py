"""Retainage release math (STANDARD/ADJUSTED variants, rounding order, FINAL amount),
ledger conservation, OCC on the project version, and the close gate."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    approve_release,
    assert_retainage_ledger_conserved,
    complete_trade_closeout_package,
    create_release,
    create_retainage_release_payload,
    drive_to_closeout,
    get_project,
    mark_ready,
    new_project,
    setup_closeout_project,
    setup_final_release_pending_project,
    setup_substantially_complete_project,
    setup_walked_project,
    validate_error,
    validate_paginated,
    validate_success,
)

PM = TEST_USERS["gc_pm_headers"]
OWNER = TEST_USERS["owner_rep_headers"]


class TestReductionVariants:

    def test_standard_vs_adjusted_reduction_for_identical_inputs(self):
        """PRD §3.6: "Under the `STANDARD` policy the release amount is exactly that base, whatever minor items remain open. Under the `ADJUSTED` policy, 25,000 cents — 250 dollars — are withheld for each blocking minor item (severity `MINOR`, status `OPEN` or `READY_FOR_REVIEW`, counted at request time), subtracted from the base with the result floored at zero; identical project data therefore yields a smaller or equal release under `ADJUSTED`."
        PRD §3.6: "For a `REDUCTION`, the base is one-half of `retainage_held_cents`, rounded half-up to a whole cent — derived from the frozen held figure, never re-computed by multiplying the raw contract value, the retainage fraction, and one-half in a single step."

        Design: Difficulty/dual_variant_calc/retainage_reduction_standard_vs_adjusted_variant
        """
        ctx_a = setup_substantially_complete_project(
            name="Proj A", reduction_policy="STANDARD", item_severities=("MINOR", "MINOR"),
        )
        # The clock now sits at the first project's SC instant; the second project's
        # walk window must start after it.
        ctx_b = setup_substantially_complete_project(
            name="Proj B", reduction_policy="ADJUSTED", item_severities=("MINOR", "MINOR"),
            walk_start="2026-08-03T11:00:00Z", walk_end="2026-08-03T12:00:00Z",
            walk_complete_at="2026-08-03T12:00:00Z", sc_clock="2026-08-03T12:00:00Z",
        )
        pa = get_project(ctx_a["project"]["id"])
        pb = get_project(ctx_b["project"]["id"])
        assert pa["retainage_held_cents"] == 1_000_000
        assert pb["retainage_held_cents"] == 1_000_000
        assert pa["open_minor_count"] == 2
        assert pb["open_minor_count"] == 2

        rel_a = create_release(pa["id"], "REDUCTION")
        rel_b = create_release(pb["id"], "REDUCTION")
        assert rel_a["amount_cents"] == 500000  # round(1000000 * 0.5), minors ignored
        assert rel_b["amount_cents"] == 450000  # 500000 - 2 * 25000
        assert rel_a["amount_cents"] != rel_b["amount_cents"]

    def test_adjusted_counts_ready_for_review_minors_as_blocking(self):
        """PRD §3.6: "Under the `ADJUSTED` policy, 25,000 cents — 250 dollars — are withheld for each blocking minor item (severity `MINOR`, status `OPEN` or `READY_FOR_REVIEW`, counted at request time), subtracted from the base with the result floored at zero; identical project data therefore yields a smaller or equal release under `ADJUSTED`."

        Design: Difficulty/dual_variant_calc/retainage_reduction_standard_vs_adjusted_variant
        """
        ctx = setup_walked_project(
            name="Proj", reduction_policy="ADJUSTED", item_severities=("MINOR", "MINOR"),
        )
        # One item OPEN, the other READY_FOR_REVIEW: both still block.
        mark_ready(ctx["items"][0]["id"], ctx["trade"]["id"])
        validate_success(api_client.request_sc_review(ctx["project"]["id"], PM), 200)
        validate_success(api_client.determine_substantial_completion(
            ctx["project"]["id"], {"approved": True}, OWNER,
        ), 200)
        release = create_release(ctx["project"]["id"], "REDUCTION")
        assert release["amount_cents"] == 450000


class TestAdjustedFormula:

    def test_adjusted_three_minors_yields_425000(self):
        """PRD §3.6: "Under the `ADJUSTED` policy, 25,000 cents — 250 dollars — are withheld for each blocking minor item (severity `MINOR`, status `OPEN` or `READY_FOR_REVIEW`, counted at request time), subtracted from the base with the result floored at zero; identical project data therefore yields a smaller or equal release under `ADJUSTED`."

        Design: Difficulty/combinatorial_formula/adjusted_reduction_multifactor_withholding
        """
        ctx = setup_substantially_complete_project(
            name="Proj Adj", reduction_policy="ADJUSTED",
            item_severities=("MINOR", "MINOR", "MINOR"),
        )
        project = get_project(ctx["project"]["id"])
        assert project["open_minor_count"] == 3
        assert project["retainage_held_cents"] == 1_000_000
        release = create_release(project["id"], "REDUCTION")
        # max(0, round(1000000 * 0.5) - 3 * 25000)
        assert release["amount_cents"] == 425000
        assert release["status"] == "REQUESTED"

    def test_adjusted_single_minor_yields_475000(self):
        """PRD §3.6: "Under the `ADJUSTED` policy, 25,000 cents — 250 dollars — are withheld for each blocking minor item (severity `MINOR`, status `OPEN` or `READY_FOR_REVIEW`, counted at request time), subtracted from the base with the result floored at zero; identical project data therefore yields a smaller or equal release under `ADJUSTED`."

        Design: Difficulty/combinatorial_formula/adjusted_reduction_multifactor_withholding
        """
        ctx = setup_substantially_complete_project(
            name="Proj", reduction_policy="ADJUSTED", item_severities=("MINOR",),
        )
        release = create_release(ctx["project"]["id"], "REDUCTION")
        # max(0, 500000 - 1 * 25000)
        assert release["amount_cents"] == 475000


class TestRoundingOrder:

    def test_held_rounds_half_up_once_at_creation(self):
        """PRD §2.6: "At project creation the system computes `retainage_held_cents` as the product of `contract_value_cents` and `retainage_pct`, rounded half-up to a whole cent, and then freezes it: the held figure is rounded exactly once, at creation, and every downstream release calculation derives from that stored value rather than re-multiplying the raw inputs."

        Design: Difficulty/combinatorial_formula/reduction_rounding_order_held_then_half
        """
        project = new_project(name="Proj Round", contract_value_cents=10000005,
                              retainage_pct=0.10, reduction_policy="STANDARD")
        # round_half_up(10000005 * 0.10) = round_half_up(1000000.5) = 1000001
        assert project["retainage_held_cents"] == 1000001
        assert project["retainage_outstanding_cents"] == 1000001

    def test_reduction_derives_from_frozen_held_figure(self):
        """PRD §3.6: "For a `REDUCTION`, the base is one-half of `retainage_held_cents`, rounded half-up to a whole cent — derived from the frozen held figure, never re-computed by multiplying the raw contract value, the retainage fraction, and one-half in a single step."

        Design: Difficulty/combinatorial_formula/reduction_rounding_order_held_then_half
        """
        ctx = setup_substantially_complete_project(
            name="Proj Round", contract_value_cents=10000005, retainage_pct=0.10,
            reduction_policy="STANDARD",
        )
        project = get_project(ctx["project"]["id"])
        assert project["retainage_held_cents"] == 1000001
        release = create_release(project["id"], "REDUCTION")
        # round_half_up(1000001 * 0.5) = 500001; the single-pass naive value
        # round(10000005 * 0.10 * 0.5) = 500000 is ruled out by the freeze.
        assert release["amount_cents"] == 500001


class TestReleaseCreationRules:

    def test_release_create_amount_input_ignored(self):
        """PRD §3.6: "The client never states an amount; the server computes `amount_cents` at creation."

        Design: Corner/entities/release_create_amount_input_ignored
        """
        ctx = setup_substantially_complete_project(name="Proj", reduction_policy="STANDARD")
        version = get_project(ctx["project"]["id"])["version"]
        payload = create_retainage_release_payload(ctx["project"]["id"], "REDUCTION", version)
        payload["amount_cents"] = 1
        release = validate_success(api_client.create_retainage_release(payload, PM), 201)
        assert release["amount_cents"] == 500000

    def test_final_release_requires_final_release_pending_in_closeout(self):
        """PRD §3.6: "Two kinds exist, each bound to its phase: a `REDUCTION` — the partial release customarily paid at substantial completion — may be requested only while the project is `SUBSTANTIALLY_COMPLETE`, and a `FINAL` only while it is `FINAL_RELEASE_PENDING`; a request of either kind in the wrong phase is rejected as `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/final_release_requires_project_final_release_pending
        """
        ctx = setup_closeout_project(name="Proj X2")
        assert get_project(ctx["project"]["id"])["status"] == "CLOSEOUT_IN_PROGRESS"
        version = get_project(ctx["project"]["id"])["version"]
        resp = api_client.create_retainage_release(
            create_retainage_release_payload(ctx["project"]["id"], "FINAL", version), PM,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        _, meta = validate_paginated(
            api_client.list_retainage_releases(PM, params={"project_id": ctx["project"]["id"]})
        )
        assert meta["total_count"] == 0

    def test_final_release_rejected_in_substantially_complete(self):
        """PRD §3.6: "Two kinds exist, each bound to its phase: a `REDUCTION` — the partial release customarily paid at substantial completion — may be requested only while the project is `SUBSTANTIALLY_COMPLETE`, and a `FINAL` only while it is `FINAL_RELEASE_PENDING`; a request of either kind in the wrong phase is rejected as `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/final_release_requires_project_final_release_pending
        """
        ctx = setup_substantially_complete_project(name="Proj")
        version = get_project(ctx["project"]["id"])["version"]
        resp = api_client.create_retainage_release(
            create_retainage_release_payload(ctx["project"]["id"], "FINAL", version), PM,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_release_kind_reused_returns_error(self):
        """PRD §3.6: "Each kind may be used at most once in a live state: if a release of the same kind already exists in `REQUESTED` or `PAID`, the new request fails with `ERR_RELEASE_KIND_ALREADY_USED`."

        Design: Corner/validations/release_kind_reused_returns_error
        """
        ctx = setup_substantially_complete_project(name="Proj", reduction_policy="STANDARD")
        first = create_release(ctx["project"]["id"], "REDUCTION")
        assert first["status"] == "REQUESTED"
        # Carry the fresh version so only the fiscal gate can fire.
        fresh_version = get_project(ctx["project"]["id"])["version"]
        resp = api_client.create_retainage_release(
            create_retainage_release_payload(ctx["project"]["id"], "REDUCTION", fresh_version), PM,
        )
        validate_error(resp, ApiErrorId.ERR_RELEASE_KIND_ALREADY_USED)

    def test_release_amount_zero_returns_error(self):
        """PRD §3.6: "If the adjusted computation lands exactly on zero, creation is rejected with `ERR_RELEASE_AMOUNT_ZERO`."

        Design: Corner/validations/release_amount_zero_returns_error
        """
        ctx = setup_substantially_complete_project(
            name="Proj", contract_value_cents=1000, retainage_pct=0.25,
            reduction_policy="ADJUSTED", item_severities=("MINOR",),
        )
        project = get_project(ctx["project"]["id"])
        # round_half_up(1000 * 0.25) = 250; base = round(250 * 0.5) = 125;
        # max(0, 125 - 25000) = 0 -> not a payable release.
        assert project["retainage_held_cents"] == 250
        version = project["version"]
        resp = api_client.create_retainage_release(
            create_retainage_release_payload(project["id"], "REDUCTION", version), PM,
        )
        validate_error(resp, ApiErrorId.ERR_RELEASE_AMOUNT_ZERO)

    def test_release_create_stale_project_version_returns_412(self):
        """PRD §2.7: "First, requesting a retainage release requires the request body to carry `expected_project_version`, holding the client's last observed `version` of the project the release is drawn against. If the project's current `version` has advanced since that observation — for example because another writer created or voided a release, which changes the project's ledger without changing its phase — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), since a new release legitimately supersedes the client's stale view of the project's release ledger."

        Design: Corner/cross_cutting_layers/release_create_stale_project_version_returns_412
        """
        ctx = setup_substantially_complete_project(name="Proj", reduction_policy="STANDARD")
        project_id = ctx["project"]["id"]
        observed_version = get_project(project_id)["version"]
        first = validate_success(api_client.create_retainage_release(
            create_retainage_release_payload(project_id, "REDUCTION", observed_version), PM,
        ), 201)
        # Void the REQUESTED release (no money moves); the kind is reusable, so only
        # the stale version can fail the replayed create.
        validate_success(api_client.void_retainage_release(first["id"], PM), 200)
        stale = api_client.create_retainage_release(
            create_retainage_release_payload(project_id, "REDUCTION", observed_version), PM,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)


class TestLedgerConservation:

    def test_approve_then_void_restores_ledger(self):
        """PRD §2.6: "Approving a release moves money from outstanding to paid; voiding an already-paid release moves the same amount back, so an approve-then-void sequence leaves both figures exactly as they stood before the approval."
        PRD §3.6: "Voiding an already-`PAID` release is a clawback: paid decreases and outstanding increases by the release amount, leaving the ledger exactly as if the payment had never occurred. `PAID` and `VOIDED` are terminal."

        Design: Difficulty/compensating_invariant/retainage_approve_then_void_conserves_held_split
        """
        ctx = setup_substantially_complete_project(name="Proj I1", reduction_policy="STANDARD")
        project_id = ctx["project"]["id"]
        release = create_release(project_id, "REDUCTION")
        assert release["amount_cents"] == 500000

        approve_release(release["id"])
        mid = get_project(project_id)
        assert mid["retainage_paid_cents"] == 500000
        assert mid["retainage_outstanding_cents"] == 500000

        voided = validate_success(api_client.void_retainage_release(release["id"], PM), 200)
        assert voided["status"] == "VOIDED"
        end = get_project(project_id)
        assert end["retainage_paid_cents"] == 0
        assert end["retainage_outstanding_cents"] == 1000000

    def test_paid_plus_outstanding_equals_held_throughout(self):
        """PRD §2.6: "`retainage_paid_cents` begins at zero and accumulates the `amount_cents` of the project's releases as they reach `PAID`. `retainage_outstanding_cents` is always the held figure minus the paid figure, so it starts equal to `retainage_held_cents`."
        PRD §2.6: "The ledger is compensating. Approving a release moves money from outstanding to paid; voiding an already-paid release moves the same amount back, so an approve-then-void sequence leaves both figures exactly as they stood before the approval."

        Design: Difficulty/compensating_invariant/retainage_approve_then_void_conserves_held_split
        """
        ctx = setup_substantially_complete_project(name="Proj", reduction_policy="STANDARD")
        project_id = ctx["project"]["id"]
        assert_retainage_ledger_conserved(get_project(project_id), 1_000_000)

        release = create_release(project_id, "REDUCTION")
        # A REQUESTED release moves no money yet.
        assert_retainage_ledger_conserved(get_project(project_id), 1_000_000)

        approve_release(release["id"])
        assert_retainage_ledger_conserved(get_project(project_id), 1_000_000)

        validate_success(api_client.void_retainage_release(release["id"], PM), 200)
        assert_retainage_ledger_conserved(get_project(project_id), 1_000_000)


class TestReleaseApprovalAndFinalAmount:

    def test_release_approve_by_pm_returns_forbidden(self):
        """PRD §2.1: "A request whose role is not among the endpoint's allowed roles is rejected with `ERR_FORBIDDEN` (HTTP 403); §4 lists the authorized roles for every endpoint."

        Design: Corner/rbac/release_approve_by_pm_returns_forbidden
        """
        ctx = setup_substantially_complete_project(name="Proj", reduction_policy="STANDARD")
        release = create_release(ctx["project"]["id"], "REDUCTION")
        resp = api_client.approve_retainage_release(release["id"], PM)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        still = validate_success(api_client.get_retainage_release(release["id"], PM), 200)
        assert still["status"] == "REQUESTED"

    def test_final_release_amount_equals_held_minus_paid(self):
        """PRD §3.6: "For a `FINAL` release, the amount is `retainage_outstanding_cents` at request time: the frozen held figure minus the sum of `amount_cents` over the project's `PAID` releases, with merely `REQUESTED` or already `VOIDED` releases contributing nothing."

        Design: Corner/calculations/final_release_amount_equals_held_minus_paid
        """
        ctx = setup_substantially_complete_project(name="Proj", reduction_policy="STANDARD")
        project_id = ctx["project"]["id"]
        reduction = create_release(project_id, "REDUCTION")
        approve_release(reduction["id"])
        assert get_project(project_id)["retainage_paid_cents"] == 500000

        drive_to_closeout(ctx)
        complete_trade_closeout_package(ctx)
        assert ctx["project"]["status"] == "FINAL_RELEASE_PENDING"

        final = create_release(project_id, "FINAL")
        assert final["amount_cents"] == 500000  # 1000000 held - 500000 PAID


class TestProjectClose:

    def test_close_without_paid_final_returns_error(self):
        """PRD §3.6: "It requires the project to stand in `FINAL_RELEASE_PENDING` and a `FINAL` release to exist in `PAID` status; without one, the close is rejected with `ERR_FINAL_RELEASE_NOT_PAID`."

        Design: Corner/validations/close_without_paid_final_returns_error
        """
        ctx = setup_final_release_pending_project(name="Proj")
        create_release(ctx["project"]["id"], "FINAL")  # left REQUESTED, never approved
        resp = api_client.close_project(ctx["project"]["id"], PM)
        validate_error(resp, ApiErrorId.ERR_FINAL_RELEASE_NOT_PAID)
        assert get_project(ctx["project"]["id"])["status"] == "FINAL_RELEASE_PENDING"
