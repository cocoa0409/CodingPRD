"""Molds: defaults, uniqueness, OCC, maintenance cycle, retirement, phase gates."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_mold,
    create_mold,
    create_mold_payload,
    create_work_order_payload,
    setup_shop,
    setup_work_order_accepted,
    setup_work_order_cured,
    validate_error,
    validate_success,
)


class TestMoldCreation:
    def test_mold_created_with_default_prototype_phase(self, api, tooling_engineer_headers):
        """PRD §3.2: "The mold is born `ACTIVE` with `cycles_since_maintenance` at 0
        and `prototype_parts_validated` at 0, and its `tooling_phase` defaults to
        `PROTOTYPE` unless the registration explicitly asks for `PRODUCTION`".

        Design: Corner/entities/mold_created_with_default_prototype_phase
        """
        mold = validate_success(
            api.create_mold(create_mold_payload(mold_code="MOLD-D1"), tooling_engineer_headers),
            201,
        )
        assert_mold(mold)
        assert mold["tooling_phase"] == "PROTOTYPE"
        assert mold["status"] == "ACTIVE"
        assert mold["cycles_since_maintenance"] == 0
        assert mold["prototype_parts_validated"] == 0

    def test_duplicate_mold_code_rejected(self, api, tooling_engineer_headers):
        """PRD §3.2: "A `ToolingEngineer` registers a mold under a unique
        `mold_code`". Uniqueness conflicts are refused with `ERR_DUPLICATE_CODE`,
        the catalogue entry for an already-taken code (PRD §5).

        Design: Corner/validations/duplicate_mold_code_rejected
        """
        validate_success(
            api.create_mold(create_mold_payload(mold_code="MOLD-DUP"), tooling_engineer_headers),
            201,
        )
        res = api.create_mold(
            create_mold_payload(
                mold_code="MOLD-DUP",
                maintenance_interval_cycles=5,
                prototype_parts_required=0,
            ),
            tooling_engineer_headers,
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_CODE, expected_status=409)


class TestMoldOcc:
    def test_occ_mold_patch_fresh_version_succeeds(self, api, tooling_engineer_headers):
        """PRD §2.7: "a `PATCH /molds/{id}` request must likewise carry
        `expected_mold_version` equal to the mold's current `version`".
        PRD §3.2: "`maintenance_interval_cycles` and `prototype_parts_required` are
        the only mutable fields".

        Design: Corner/complexity_layers/occ_mold_patch_stale_version_rejected
        """
        mold = validate_success(
            api.create_mold(create_mold_payload(mold_code="MOLD-OC1"), tooling_engineer_headers),
            201,
        )
        patched = validate_success(
            api.patch_mold(
                mold["id"],
                {
                    "expected_mold_version": mold["version"],
                    "maintenance_interval_cycles": 7,
                },
                tooling_engineer_headers,
            ),
            200,
        )
        assert patched["version"] == mold["version"] + 1
        assert patched["maintenance_interval_cycles"] == 7

    def test_occ_mold_patch_stale_version_rejected(self, api, tooling_engineer_headers):
        """PRD §2.7: "If the supplied value does not match the resource's current
        `version` — because another writer has advanced the resource since the client
        last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412),
        and no change is applied."

        Design: Corner/complexity_layers/occ_mold_patch_stale_version_rejected
        """
        mold = validate_success(
            api.create_mold(create_mold_payload(mold_code="MOLD-OC1"), tooling_engineer_headers),
            201,
        )
        stale_version = mold["version"]
        validate_success(
            api.patch_mold(
                mold["id"],
                {
                    "expected_mold_version": stale_version,
                    "maintenance_interval_cycles": 7,
                },
                tooling_engineer_headers,
            ),
            200,
        )
        res = api.patch_mold(
            mold["id"],
            {"expected_mold_version": stale_version, "prototype_parts_required": 3},
            tooling_engineer_headers,
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


class TestMoldMaintenanceCycle:
    def _setup_due_mold(self, api):
        """Interval-1 mold driven through one completed mold-bearing cure."""
        ctx = setup_work_order_cured(
            mold_overrides={
                "mold_code": "MOLD-MC1",
                "maintenance_interval_cycles": 1,
                "tooling_phase": "PRODUCTION",
            },
            work_order_overrides={"work_order_no": "WO-MC1"},
            batch_overrides={"batch_code": "BATCH-MC1"},
        )
        return ctx

    def test_cure_completion_flips_mold_to_maintenance_due(self, api, tooling_engineer_headers):
        """PRD §3.2: "each such completion adds one to `cycles_since_maintenance`,
        and when that increment brings the counter to `maintenance_interval_cycles`
        or beyond, the mold moves automatically from `ACTIVE` to `MAINTENANCE_DUE`."

        Design: Difficulty/non_linear_state_machine/mold_maintenance_cycle_returns_to_active
        """
        ctx = self._setup_due_mold(api)
        mold = validate_success(api.get_mold(ctx["mold"]["id"], tooling_engineer_headers), 200)
        assert mold["cycles_since_maintenance"] == 1
        assert mold["status"] == "MAINTENANCE_DUE"

    def test_maintenance_cycle_returns_to_active_with_reset(self, api, tooling_engineer_headers):
        """PRD §3.2: "A `ToolingEngineer` takes a due mold into `IN_MAINTENANCE`,
        and completing maintenance returns it to `ACTIVE` with the wear counter
        reset to 0."

        Design: Difficulty/non_linear_state_machine/mold_maintenance_cycle_returns_to_active
        """
        ctx = self._setup_due_mold(api)
        in_maint = validate_success(
            api.start_mold_maintenance(ctx["mold"]["id"], tooling_engineer_headers), 200
        )
        assert in_maint["status"] == "IN_MAINTENANCE"
        back = validate_success(
            api.complete_mold_maintenance(ctx["mold"]["id"], tooling_engineer_headers), 200
        )
        assert back["status"] == "ACTIVE"
        assert back["cycles_since_maintenance"] == 0


class TestMoldRetireAndPhase:
    def test_retired_mold_rejects_transition_phase(self, api, tooling_engineer_headers):
        """PRD §3.2: "Phase transitions of any kind are impossible on a `RETIRED`
        mold, which answers `ERR_INVALID_STATE`."

        Design: Corner/state_machines/retired_mold_rejects_transition_phase
        """
        mold = validate_success(
            api.create_mold(create_mold_payload(mold_code="MOLD-RT1"), tooling_engineer_headers),
            201,
        )
        retired = validate_success(api.retire_mold(mold["id"], tooling_engineer_headers), 200)
        assert retired["status"] == "RETIRED"
        res = api.transition_mold_phase(mold["id"], "PRODUCTION", tooling_engineer_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_prototype_promotion_gate_count_boundary(self, api, tooling_engineer_headers):
        """PRD §3.2: "Promotion from `PROTOTYPE` to `TRANSITION` requires
        `prototype_parts_validated` to be at least `prototype_parts_required`, with
        equality sufficient; the counter itself grows only when a work order on this
        mold is accepted while the phase is `PROTOTYPE`, as detailed in §3.6."
        and "Either failed gate is rejected with `ERR_TOOLING_PHASE_GATE`."

        Design: Corner/calculations/prototype_promotion_gate_count_boundary
        """
        ctx = setup_work_order_accepted(
            mold_overrides={"mold_code": "MOLD-PP1", "prototype_parts_required": 1},
            work_order_overrides={"work_order_no": "WO-PP1"},
            batch_overrides={"batch_code": "BATCH-PP1"},
        )
        mold_id = ctx["mold"]["id"]
        # The accepted order on the PROTOTYPE mold grew the counter to 1; at the
        # >= boundary (1 >= 1) the promotion must now succeed.
        promoted = validate_success(
            api.transition_mold_phase(mold_id, "TRANSITION", tooling_engineer_headers), 200
        )
        assert promoted["prototype_parts_validated"] == 1
        assert promoted["tooling_phase"] == "TRANSITION"

    def test_prototype_promotion_gate_blocks_below_required(self, api, tooling_engineer_headers):
        """PRD §3.2: "Promotion from `PROTOTYPE` to `TRANSITION` requires
        `prototype_parts_validated` to be at least `prototype_parts_required`, with
        equality sufficient" and "Either failed gate is rejected with
        `ERR_TOOLING_PHASE_GATE`." With zero validated parts against a requirement
        of one, the gate refuses the promotion.

        Design: Corner/calculations/prototype_promotion_gate_count_boundary
        """
        mold = validate_success(
            api.create_mold(
                create_mold_payload(mold_code="MOLD-PP0", prototype_parts_required=1),
                tooling_engineer_headers,
            ),
            201,
        )
        res = api.transition_mold_phase(mold["id"], "TRANSITION", tooling_engineer_headers)
        validate_error(res, ApiErrorId.ERR_TOOLING_PHASE_GATE, expected_status=409)
        after = validate_success(api.get_mold(mold["id"], tooling_engineer_headers), 200)
        assert after["tooling_phase"] == "PROTOTYPE"

    def test_promote_to_production_with_open_wo_rejected(self, api, tooling_engineer_headers, shop_manager_headers):
        """PRD §3.2: "Moving from `TRANSITION` to `PRODUCTION` requires that no work
        order on the mold remains in a non-terminal status — anything other than
        `ACCEPTED` or `SCRAPPED` blocks the promotion. Either failed gate is rejected
        with `ERR_TOOLING_PHASE_GATE`."

        Design: Corner/validations/promote_to_production_with_open_wo_rejected
        """
        mold = validate_success(
            api.create_mold(
                create_mold_payload(mold_code="MOLD-TP1", prototype_parts_required=0),
                tooling_engineer_headers,
            ),
            201,
        )
        promoted = validate_success(
            api.transition_mold_phase(mold["id"], "TRANSITION", tooling_engineer_headers),
            200,
        )
        assert promoted["tooling_phase"] == "TRANSITION"

        shop = setup_shop(set_clock_to=None)
        # Release one order against the TRANSITION mold (still RELEASED = non-terminal).
        order = validate_success(
            api.create_work_order(
                create_work_order_payload(
                    mold["id"], shop["ply_book"]["id"], work_order_no="WO-TP1"
                ),
                shop_manager_headers,
            ),
            201,
        )
        assert order["status"] == "RELEASED"
        res = api.transition_mold_phase(mold["id"], "PRODUCTION", tooling_engineer_headers)
        validate_error(res, ApiErrorId.ERR_TOOLING_PHASE_GATE, expected_status=409)
