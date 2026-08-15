"""Store kit configuration: creation, patching with OCC, freeze, cancel,
and the program budget commitment."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    activate_program,
    api_client,
    assert_store_kit_config,
    create_active_program,
    create_approved_prototype,
    create_kit,
    create_program,
    create_prototype,
    freeze_kit,
    is_iso8601_timestamp,
    make_config_coordinator_headers,
    make_fixture_engineer_headers,
    make_program_manager_headers,
    submit_prototype,
    validate_error,
    validate_paginated,
    validate_success,
)

PM = make_program_manager_headers("pm-suite-2")
CC = make_config_coordinator_headers("cc-suite-2")

ROUNDING_LINES = [
    {"part_number": "PN-500", "quantity": 1, "unit_cost_cents": 1025},
    {"part_number": "PN-501", "quantity": 1, "unit_cost_cents": 2075},
]
# Per line: round_half_up(1*1025*1.06)=1087; round_half_up(1*2075*1.06)=2200.
ROUNDING_TOTAL = 3287


def _program_with_approved_prototype(name, budget=1_000_000, contingency=100_000,
                                     activate=True):
    program = create_program(name, budget, contingency)
    if activate:
        program = activate_program(program["id"])
    prototype = create_approved_prototype(
        program["id"], fixture_code="ENDCAP",
        bom_lines=[{"part_number": "PN-600", "quantity": 1,
                    "list_unit_cost_cents": 3000}],
    )
    return program, prototype


class TestKitCreation:

    def test_kit_created_initial_state_draft(self):
        """PRD §3.3: "The kit is born in `DRAFT`, and its cost figures are
        computed immediately from whatever lines were supplied — zero when none
        were."
        PRD §3.4: "The kit carries no wave affiliation or surcharge before this
        point: both `wave_id` and `wave_release_charge_cents` remain null until
        the kit is released."

        Design: Corner/state_machines/kit_created_initial_state_draft
        """
        program, prototype = _program_with_approved_prototype("P-SM3")
        kit = create_kit(program["id"], prototype["id"], "STORE-S3")
        assert_store_kit_config(kit)
        assert kit["status"] == "DRAFT"
        assert kit["total_components"] == 0
        assert kit["kit_total_cost_cents"] == 0
        assert kit["wave_id"] is None

    def test_kit_create_with_unknown_prototype_returns_404(self):
        """PRD §3.3: "Creation takes the `program_id`, the `prototype_id` the
        kit derives from (unknown program or prototype identifiers are rejected
        with `ERR_PROGRAM_NOT_FOUND` or `ERR_PROTOTYPE_NOT_FOUND` respectively),
        the destination `store_code`, and optionally an initial set of
        `config_lines`, which defaults to an empty list."

        Design: Corner/validations/kit_create_with_unknown_prototype_returns_404
        """
        program = create_active_program("P-VAL3", 1_000_000, 100_000)
        resp = api_client.create_store_kit_config(
            {"program_id": program["id"], "prototype_id": NON_EXISTENT_UUID,
             "store_code": "STORE-V3"},
            CC,
        )
        validate_error(resp, ApiErrorId.ERR_PROTOTYPE_NOT_FOUND)

    def test_kit_list_pagination_and_filter(self):
        """PRD §2.3: "Kit configurations filter by `program_id`,
        `prototype_id`, `wave_id`, and `status`."
        PRD §2.3: "The `meta` object of a list response carries four pagination
        fields: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/kit_list_pagination_and_filter
        """
        prog1, proto1 = _program_with_approved_prototype("P-LIST1")
        create_kit(prog1["id"], proto1["id"], "STORE-L1")
        create_kit(prog1["id"], proto1["id"], "STORE-L2")
        prog2, proto2 = _program_with_approved_prototype("P-LIST2")
        create_kit(prog2["id"], proto2["id"], "STORE-L3")

        page1, meta1 = validate_paginated(api_client.list_store_kit_configs(
            PM, params={"program_id": prog1["id"], "limit": 1, "offset": 0}))
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True
        assert len(page1) == 1
        assert all(row["program_id"] == prog1["id"] for row in page1)

        page2, meta2 = validate_paginated(api_client.list_store_kit_configs(
            PM, params={"program_id": prog1["id"], "limit": 1, "offset": 1}))
        assert meta2["total_count"] == 2
        assert meta2["has_more"] is False
        assert len(page2) == 1

        _, meta3 = validate_paginated(api_client.list_store_kit_configs(
            PM, params={"program_id": prog2["id"]}))
        assert meta3["total_count"] == 1


class TestKitPatchOcc:

    def test_version_increments_on_mutation(self):
        """PRD §2.4: "**`version` (integer):** a system-managed integer that
        increments by one on every mutation, whether the mutation comes from a
        direct client action or from an automatic cascade touching the
        resource."
        PRD §3.3: "A successful patch recomputes the kit totals and increments
        the kit's `version`."

        Design: Corner/entities/version_increments_on_mutation
        """
        program, prototype = _program_with_approved_prototype("P-VER")
        kit = create_kit(program["id"], prototype["id"], "STORE-V1")
        created_version = kit["version"]
        created_at = kit["created_at"]
        assert is_iso8601_timestamp(created_at)
        patched = validate_success(api_client.patch_store_kit_config(
            kit["id"],
            {"config_lines": [
                {"part_number": "PN-600", "quantity": 3,
                 "unit_cost_cents": 1000},
            ], "expected_config_version": created_version},
            CC,
        ))
        assert patched["version"] == created_version + 1, (
            f"version must increment by exactly 1 on mutation: "
            f"{created_version} -> {patched['version']}"
        )
        assert patched["total_components"] == 3
        assert is_iso8601_timestamp(patched["updated_at"])

    def test_kit_patch_stale_version_returns_412(self):
        """PRD §3.3: "This is one of the two optimistic-concurrency-protected
        writes in the system (§2.6): the patch body must carry
        `expected_config_version` equal to the kit's current `version`, and a
        stale expectation is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/kit_patch_stale_version_returns_412
        """
        program, prototype = _program_with_approved_prototype("P-OCC1")
        kit = create_kit(program["id"], prototype["id"], "STORE-OCC1")
        stale_version = kit["version"]
        first = validate_success(api_client.patch_store_kit_config(
            kit["id"],
            {"config_lines": [
                {"part_number": "PN-600", "quantity": 3,
                 "unit_cost_cents": 1000},
            ], "expected_config_version": stale_version},
            CC,
        ))
        assert first["total_components"] == 3
        assert first["version"] == stale_version + 1
        resp = api_client.patch_store_kit_config(
            kit["id"],
            {"config_lines": [
                {"part_number": "PN-600", "quantity": 7,
                 "unit_cost_cents": 1000},
            ], "expected_config_version": stale_version},
            CC,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        after = validate_success(
            api_client.get_store_kit_config(kit["id"], PM))
        assert after["total_components"] == 3, \
            "the stale write must not be applied"


class TestKitRounding:
    """Per-line round-half-up, then sum — the pinned rounding order."""

    def test_kit_total_per_line_rounding_at_freeze_and_debit(self):
        """PRD §3.3: "`kit_total_cost_cents` prices the kit with a handling
        surcharge: for each line, the line's `quantity` is multiplied by its
        `unit_cost_cents` and by a factor of 1.06 — a six percent handling
        uplift — and the result is rounded half up to a whole cent; the kit
        total is then the integer sum of those per-line amounts."
        PRD §3.3: "A successful freeze moves the kit `DRAFT → FROZEN`, deducts
        `kit_total_cost_cents` from the program's `remaining_budget_cents`, and
        — when this is the first kit derived from its prototype to be frozen —
        bubbles up to lock the prototype, moving it `APPROVED → LOCKED` as
        described in §3.2."

        Design: Difficulty/combinatorial_formula/kit_total_per_line_rounding
        """
        program, prototype = _program_with_approved_prototype(
            "P-ROUND", budget=2_000_000)
        kit = create_kit(program["id"], prototype["id"], "STORE-R1",
                         ROUNDING_LINES)
        frozen = freeze_kit(kit["id"])
        assert frozen["kit_total_cost_cents"] == ROUNDING_TOTAL
        assert frozen["total_components"] == 2
        assert frozen["status"] == "FROZEN"
        program_after = validate_success(
            api_client.get_rollout_program(program["id"], PM))
        assert program_after["remaining_budget_cents"] == 2_000_000 - 3287

    def test_kit_total_computed_immediately_at_creation(self):
        """PRD §3.3: "The kit is born in `DRAFT`, and its cost figures are
        computed immediately from whatever lines were supplied — zero when none
        were."
        PRD §3.3: "The rounding order is pinned: per line first, then sum.
        Rounding once after summing raw line amounts is forbidden, because it
        produces a different cent value whenever two or more lines yield
        fractional cents."

        Design: Difficulty/combinatorial_formula/kit_total_per_line_rounding
        """
        program, prototype = _program_with_approved_prototype(
            "P-ROUND2", budget=2_000_000)
        kit = create_kit(program["id"], prototype["id"], "STORE-R2",
                         ROUNDING_LINES)
        assert kit["kit_total_cost_cents"] == ROUNDING_TOTAL, (
            f"per-line-then-sum must yield 3287 (sum-then-round would yield "
            f"3286); got {kit['kit_total_cost_cents']}"
        )
        assert kit["total_components"] == 2
        assert kit["status"] == "DRAFT"
        # No debit happens before freeze.
        program_after = validate_success(
            api_client.get_rollout_program(program["id"], PM))
        assert program_after["remaining_budget_cents"] == 2_000_000


class TestKitFreezeGates:

    def test_kit_freeze_requires_approved_prototype_in_review(self):
        """PRD §3.3: "A coordinator may freeze only a kit in `DRAFT` (any other
        state: `ERR_KIT_INVALID_STATE`), and only when three further conditions
        hold: the program is `ACTIVE` (`ERR_PROGRAM_NOT_ACTIVE` otherwise), the
        source prototype is `APPROVED` or `LOCKED`
        (`ERR_PROTOTYPE_NOT_APPROVED` otherwise), and the kit contains at least
        one configuration line (`ERR_KIT_EMPTY`, HTTP 422, when `config_lines`
        is empty)."

        Design: Difficulty/cross_entity_state_dependency/kit_freeze_requires_approved_prototype
        """
        program = create_active_program("P-XDEP1", 1_000_000, 100_000)
        proto = create_prototype(program["id"], fixture_code="ENDCAP")
        submit_prototype(proto["id"], "eng-1")  # ENGINEERING_REVIEW, not approved
        kit = create_kit(program["id"], proto["id"], "STORE-X1",
                         [{"part_number": "PN-600", "quantity": 5,
                           "unit_cost_cents": 1000}])
        resp = api_client.freeze_kit(kit["id"], CC)
        validate_error(resp, ApiErrorId.ERR_PROTOTYPE_NOT_APPROVED)
        kit_after = validate_success(
            api_client.get_store_kit_config(kit["id"], PM))
        assert kit_after["status"] == "DRAFT"
        proto_after = validate_success(
            api_client.get_fixture_prototype(proto["id"], PM))
        assert proto_after["status"] == "ENGINEERING_REVIEW"

    def test_kit_freeze_rejected_when_prototype_still_draft(self):
        """PRD §3.3: "A coordinator may freeze only a kit in `DRAFT` (any other
        state: `ERR_KIT_INVALID_STATE`), and only when three further conditions
        hold: the program is `ACTIVE` (`ERR_PROGRAM_NOT_ACTIVE` otherwise), the
        source prototype is `APPROVED` or `LOCKED`
        (`ERR_PROTOTYPE_NOT_APPROVED` otherwise), and the kit contains at least
        one configuration line (`ERR_KIT_EMPTY`, HTTP 422, when `config_lines`
        is empty)."

        Design: Difficulty/cross_entity_state_dependency/kit_freeze_requires_approved_prototype
        """
        program = create_active_program("P-XDEP1B", 1_000_000, 100_000)
        proto = create_prototype(program["id"], fixture_code="ENDCAP")
        assert proto["status"] == "DRAFT"
        kit = create_kit(program["id"], proto["id"], "STORE-X1B",
                         [{"part_number": "PN-600", "quantity": 5,
                           "unit_cost_cents": 1000}])
        resp = api_client.freeze_kit(kit["id"], CC)
        validate_error(resp, ApiErrorId.ERR_PROTOTYPE_NOT_APPROVED)
        kit_after = validate_success(
            api_client.get_store_kit_config(kit["id"], PM))
        assert kit_after["status"] == "DRAFT"

    def test_freeze_state_beats_fiscal(self):
        """PRD §2.7: "**State preconditions fifth.** The target resource must
        occupy the lifecycle state its operation requires — the state-machine
        gates scattered through §3, such as program activation gates, kit
        freeze and release states, prototype review states, wave commit states,
        claim openness, signoff submission states, delivery progression, ledger
        adjustability, and reservation holds."
        PRD §2.7: "**Money last.** Only after every category above has passed
        does the server evaluate fiscal constraints: the freeze and release
        budget checks (`ERR_BUDGET_EXCEEDED`), the wave capacity check
        (`ERR_WAVE_CAPACITY_EXCEEDED`), and the contingency check on claim
        approval (`ERR_CONTINGENCY_EXCEEDED`)."

        Design: Difficulty/priority_pair_validation_conflict/freeze_state_beats_fiscal
        """
        # Program stays DRAFT; its budget (1000) is also below the kit total
        # (3287). The state failure must be reported, not the budget failure.
        program, prototype = _program_with_approved_prototype(
            "P-PRIO1", budget=1_000, contingency=0, activate=False)
        kit = create_kit(program["id"], prototype["id"], "STORE-P1",
                         ROUNDING_LINES)
        resp = api_client.freeze_kit(kit["id"], CC)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_ACTIVE)
        kit_after = validate_success(
            api_client.get_store_kit_config(kit["id"], PM))
        assert kit_after["status"] == "DRAFT"
        program_after = validate_success(
            api_client.get_rollout_program(program["id"], PM))
        assert program_after["remaining_budget_cents"] == 1_000

    def test_freeze_over_budget_returns_402_when_state_passes(self):
        """PRD §3.3: "Fiscally, the kit's `kit_total_cost_cents` must not
        exceed the program's `remaining_budget_cents` — a kit whose total lands
        exactly on the remaining budget is allowed — and a shortfall is
        rejected with `ERR_BUDGET_EXCEEDED` (HTTP 402)."

        Design: Difficulty/priority_pair_validation_conflict/freeze_state_beats_fiscal
        """
        # Only the fiscal gate can fail here: program ACTIVE, prototype
        # APPROVED, kit non-empty, total 3287 > budget 1000.
        program, prototype = _program_with_approved_prototype(
            "P-PRIO1B", budget=1_000, contingency=0)
        kit = create_kit(program["id"], prototype["id"], "STORE-P1B",
                         ROUNDING_LINES)
        resp = api_client.freeze_kit(kit["id"], CC)
        validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED)
        kit_after = validate_success(
            api_client.get_store_kit_config(kit["id"], PM))
        assert kit_after["status"] == "DRAFT"
        program_after = validate_success(
            api_client.get_rollout_program(program["id"], PM))
        assert program_after["remaining_budget_cents"] == 1_000

    def test_kit_empty_freeze_rejected(self):
        """PRD §3.3: "A coordinator may freeze only a kit in `DRAFT` (any other
        state: `ERR_KIT_INVALID_STATE`), and only when three further conditions
        hold: the program is `ACTIVE` (`ERR_PROGRAM_NOT_ACTIVE` otherwise), the
        source prototype is `APPROVED` or `LOCKED`
        (`ERR_PROTOTYPE_NOT_APPROVED` otherwise), and the kit contains at least
        one configuration line (`ERR_KIT_EMPTY`, HTTP 422, when `config_lines`
        is empty)."

        Design: Corner/validations/kit_empty_freeze_rejected
        """
        program, prototype = _program_with_approved_prototype("P-VAL10")
        kit = create_kit(program["id"], prototype["id"], "STORE-V10")
        resp = api_client.freeze_kit(kit["id"], CC)
        validate_error(resp, ApiErrorId.ERR_KIT_EMPTY)
        kit_after = validate_success(
            api_client.get_store_kit_config(kit["id"], PM))
        assert kit_after["status"] == "DRAFT"


class TestFreezeSideEffects:

    def test_freeze_locks_prototype_bubble_up(self):
        """PRD §3.2: "An approved prototype remains editable nowhere: the
        moment the first kit configuration derived from it is frozen, the
        prototype automatically transitions `APPROVED → LOCKED`, after which
        `bom_lines` and `target_cost_cents` are immutable and any patch attempt
        fails with `ERR_PROTOTYPE_INVALID_STATE`."

        Design: Corner/state_machines/freeze_locks_prototype_bubble_up
        """
        program, prototype = _program_with_approved_prototype("P-SM4")
        kit = create_kit(program["id"], prototype["id"], "STORE-S4",
                         [{"part_number": "PN-600", "quantity": 5,
                           "unit_cost_cents": 1000}])
        freeze_kit(kit["id"])
        locked = validate_success(
            api_client.get_fixture_prototype(prototype["id"], PM))
        assert locked["status"] == "LOCKED"
        resp = api_client.patch_fixture_prototype(
            prototype["id"],
            {"bom_lines": [{"part_number": "PN-600", "quantity": 2,
                            "list_unit_cost_cents": 3000}]},
            make_fixture_engineer_headers("eng-9"),
        )
        validate_error(resp, ApiErrorId.ERR_PROTOTYPE_INVALID_STATE)
        after = validate_success(
            api_client.get_fixture_prototype(prototype["id"], PM))
        assert after["bom_lines"][0]["quantity"] == 1, \
            "the locked prototype's bom_lines must be unchanged"

    def test_freeze_effects_visible_in_same_response(self):
        """PRD §3.3: "A successful freeze moves the kit `DRAFT → FROZEN`,
        deducts `kit_total_cost_cents` from the program's
        `remaining_budget_cents`, and — when this is the first kit derived from
        its prototype to be frozen — bubbles up to lock the prototype, moving
        it `APPROVED → LOCKED` as described in §3.2."

        Design: Corner/consistency_model/freeze_effects_visible_in_same_response
        """
        program, prototype = _program_with_approved_prototype("P-CON1")
        kit = create_kit(program["id"], prototype["id"], "STORE-CON1",
                         [{"part_number": "PN-600", "quantity": 5,
                           "unit_cost_cents": 1000}])
        frozen = validate_success(api_client.freeze_kit(kit["id"], CC))
        assert frozen["status"] == "FROZEN"
        assert frozen["kit_total_cost_cents"] == 5_300  # 5*1000*1.06
        program_after = validate_success(
            api_client.get_rollout_program(program["id"], PM))
        assert program_after["remaining_budget_cents"] == 994_700
        proto_after = validate_success(
            api_client.get_fixture_prototype(prototype["id"], PM))
        assert proto_after["status"] == "LOCKED"


class TestFreezeCancelBudgetConservation:

    def test_frozen_cancel_refunds_freeze_debit(self):
        """PRD §3.3: "Cancelling a `FROZEN` kit additionally refunds the freeze
        debit: the kit's `kit_total_cost_cents` is added back to the program's
        `remaining_budget_cents` before the kit lands in `CANCELLED`."

        Design: Difficulty/compensating_invariant/freeze_cancel_budget_conserved
        """
        program, prototype = _program_with_approved_prototype("P-INV1")
        kit = create_kit(program["id"], prototype["id"], "STORE-I1",
                         ROUNDING_LINES)
        freeze_kit(kit["id"])
        mid = validate_success(
            api_client.get_rollout_program(program["id"], PM))
        assert mid["remaining_budget_cents"] == 1_000_000 - 3287
        cancelled = validate_success(api_client.cancel_kit(kit["id"], CC))
        assert cancelled["status"] == "CANCELLED"
        after = validate_success(
            api_client.get_rollout_program(program["id"], PM))
        assert after["remaining_budget_cents"] == 1_000_000, (
            f"freeze debit plus cancel refund must conserve the budget; got "
            f"{after['remaining_budget_cents']}"
        )

    def test_draft_cancel_has_no_fiscal_effect(self):
        """PRD §3.3: "Cancelling a `DRAFT` kit simply moves it to `CANCELLED`
        with no fiscal effect, since nothing was ever debited."

        Design: Difficulty/compensating_invariant/freeze_cancel_budget_conserved
        """
        program, prototype = _program_with_approved_prototype("P-INV1B")
        kit = create_kit(program["id"], prototype["id"], "STORE-I1B",
                         ROUNDING_LINES)
        cancelled = validate_success(api_client.cancel_kit(kit["id"], CC))
        assert cancelled["status"] == "CANCELLED"
        after = validate_success(
            api_client.get_rollout_program(program["id"], PM))
        assert after["remaining_budget_cents"] == 1_000_000
