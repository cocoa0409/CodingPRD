"""Cross-entity state gates and the positive-result transitive cascade."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_collected_salmonella_test,
    create_draft_settlement,
    create_failed_audit,
    flock_payload,
    record_test_result,
    setup_active_contract,
    setup_confirmed_lot,
    setup_farm_house,
    place_flock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    COMPLIANCE_OFFICER,
    CONTRACT_MANAGER,
    FARM_MANAGER,
    QA_MANAGER,
    get_contract,
    get_farm,
    get_flock,
    get_house,
    get_lot,
    get_settlement,
    get_salmonella_test,
)


class TestPlacementGate:
    def test_flock_placement_requires_house_empty(self, api):
        """PRD §3.1: "Placement into a house that is not `EMPTY` is rejected
        with `ERR_HOUSE_NOT_EMPTY` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/flock_placement_requires_house_empty
        """
        ctx = setup_farm_house()
        flock1 = place_flock(ctx["house"]["id"], initial_hen_count=800,
                             pullet_cost_cents=336000)
        resp = api.create_flock(
            flock_payload(
                ctx["house"]["id"],
                breed_code="ISA_WHITE",
                breed_peak_rate_pct=94.0,
                placement_date="2026-08-01",
                initial_hen_count=500,
                pullet_cost_cents=210000,
            ),
            FARM_MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_HOUSE_NOT_EMPTY)

    def test_flock_placement_second_into_occupied_house_rejected(self, api):
        """PRD §3.1: "Placement into a house that is not `EMPTY` is rejected
        with `ERR_HOUSE_NOT_EMPTY` (HTTP 409)."
        PRD §3.1: "In the same operation the house cascades from `EMPTY` to
        `OCCUPIED`, its `current_flock_id` is set to the new flock, its
        `status_changed_date` is stamped to the clock date, and its `version`
        increments."

        Design: Difficulty/cross_entity_state_dependency/flock_placement_requires_house_empty
        """
        ctx = setup_farm_house()
        flock1 = place_flock(ctx["house"]["id"], initial_hen_count=800,
                             pullet_cost_cents=336000)
        resp = api.create_flock(
            flock_payload(ctx["house"]["id"], placement_date="2026-08-01"),
            FARM_MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_HOUSE_NOT_EMPTY)

        house = get_house(ctx["house"]["id"])
        assert house["status"] == "OCCUPIED"
        assert house["current_flock_id"] == flock1["id"]
        flocks, meta = validate_paginated(
            api.list_flocks(FARM_MANAGER, params={"house_id": ctx["house"]["id"]})
        )
        assert meta["total_count"] == 1, "no second flock may be created"


class TestFarmPostureGate:
    def _setup_lot_and_failed_audit(self, api):
        """One FRESH/CLEAR lot on a CAGE_FREE farm, then an audit closed
        FAILED so the farm posture goes SUSPENDED."""
        ctx = setup_confirmed_lot(
            eggs_to_grade=240,
            farm_overrides={"certification_program": "CAGE_FREE"},
            house_overrides={"environment_type": "AVIARY"},
        )
        create_failed_audit(
            ctx["farm"]["id"], audit_date="2026-08-01", standard="USDA_CAGE_FREE"
        )
        return ctx

    def test_lot_release_requires_farm_not_suspended(self, api):
        """PRD §3.5: "The lot's `hold_status` must be `CLEAR`, else
        `ERR_LOT_QUALITY_HELD` (HTTP 409); the farm's `compliance_posture`
        must not be `SUSPENDED`, else `ERR_FARM_SUSPENDED` (HTTP 409); and the
        flock's `quarantine_status` must be `CLEAR`, else
        `ERR_UNRESOLVED_POSITIVE` (HTTP 409)."
        PRD §3.8: "Closing with `FAILED` stamps `closed_date`, moves the audit
        to terminal `CLOSED_FAILED`, and fires a two-link cascade: the farm's
        `compliance_posture` becomes `SUSPENDED` on the strength of a failed
        audit closed within the trailing 30 days"

        Design: Difficulty/cross_entity_state_dependency/lot_release_requires_farm_not_suspended
        """
        ctx = self._setup_lot_and_failed_audit(api)
        assert get_farm(ctx["farm"]["id"])["compliance_posture"] == "SUSPENDED", (
            "a FAILED audit must cascade the farm posture to SUSPENDED"
        )

        lot_id = ctx["lots"][0]["id"]
        resp = api.release_lot(lot_id, QA_MANAGER)
        validate_error(resp, ApiErrorId.ERR_FARM_SUSPENDED)

    def test_lot_release_blocked_after_failed_audit_leaves_lot_fresh(self, api):
        """PRD §3.5: "the farm's `compliance_posture` must not be `SUSPENDED`,
        else `ERR_FARM_SUSPENDED` (HTTP 409)"
        PRD §3.8: "Two gates key off the posture: lot release and contract
        activation or reinstatement all require a posture other than
        `SUSPENDED`, answering with `ERR_FARM_SUSPENDED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/lot_release_requires_farm_not_suspended
        """
        ctx = self._setup_lot_and_failed_audit(api)
        lot_id = ctx["lots"][0]["id"]
        lot = get_lot(lot_id)
        assert lot["lifecycle_status"] == "FRESH" and lot["hold_status"] == "CLEAR"
        assert get_flock(ctx["flock"]["id"])["quarantine_status"] == "CLEAR", (
            "no quarantine is involved; the farm-posture gate alone blocks"
        )

        resp = api.release_lot(lot_id, QA_MANAGER)
        validate_error(resp, ApiErrorId.ERR_FARM_SUSPENDED)
        assert get_lot(lot_id)["lifecycle_status"] == "FRESH"


class TestPositiveResultCascade:
    def _setup_cascade(self, api):
        """ALLOCATED lot (20 dozen) with a DRAFT settlement on its ACTIVE
        contract, then a POSITIVE environmental result."""
        ctx = setup_confirmed_lot(eggs_to_grade=240)
        lot_id = ctx["lots"][0]["id"]
        contract = setup_active_contract(ctx["farm"]["id"])
        validate_success(api.release_lot(lot_id, QA_MANAGER))
        validate_success(
            api.allocate_lot(lot_id, {"contract_id": contract["id"]}, CONTRACT_MANAGER)
        )
        settlement = create_draft_settlement(
            contract["id"], "2026-07-27", "2026-08-02", market_index_cents=140
        )
        test = create_collected_salmonella_test(ctx["flock"]["id"])
        return ctx, lot_id, contract, settlement, test

    def test_positive_test_cascades_flock_lots_contract_settlement(self, api):
        """PRD §3.7: "Link one sets the flock's `quarantine_status` from
        `CLEAR` to `QUARANTINED`. Link two places every egg lot of that flock
        whose lifecycle is `FRESH`, `RELEASED`, or `ALLOCATED` and whose hold
        is `CLEAR` into `HELD` — and when an allocated lot becomes held, its
        contract's `held_allocated_dozen` rises above zero. Link three
        suspends every contract whose `held_allocated_dozen` is above zero,
        moving it from `ACTIVE` to `SUSPENDED`. Link four auto-voids every
        `DRAFT` settlement of each such suspended contract."

        Design: Difficulty/transitive_cascade/positive_test_cascades_flock_lots_contract_settlement
        """
        ctx, lot_id, contract, settlement, test = self._setup_cascade(api)
        resulted = record_test_result(test["id"], "POSITIVE")
        assert resulted["status"] == "RESULTED"
        assert resulted["result"] == "POSITIVE"

        assert get_flock(ctx["flock"]["id"])["quarantine_status"] == "QUARANTINED"
        lot = get_lot(lot_id)
        assert lot["hold_status"] == "HELD"
        assert lot["lifecycle_status"] == "ALLOCATED", (
            "the cascade moves the hold dimension only, not the lifecycle"
        )
        contract_after = get_contract(contract["id"])
        assert contract_after["status"] == "SUSPENDED"
        assert contract_after["held_allocated_dozen"] == 20
        assert get_settlement(settlement["id"])["status"] == "VOIDED"

    def test_positive_test_cascade_recall_autocreated_and_posture_suspended(self, api):
        """PRD §3.7: "Link five auto-creates a **Recall** in `INITIATED`
        status: its `farm_id` is taken from the flock's house's farm,
        `salmonella_test_id` points at this test, `scope_flock_id` restricts
        the recall to this flock, `reason` is `SALMONELLA`, and the pack
        window spans every `pack_date` found among the held lots. Link six
        sets the farm's `compliance_posture` to `SUSPENDED`, the
        unresolved-positive condition of §3.8."

        Design: Difficulty/transitive_cascade/positive_test_cascades_flock_lots_contract_settlement
        """
        ctx, lot_id, contract, settlement, test = self._setup_cascade(api)
        record_test_result(test["id"], "POSITIVE")

        recalls, meta = validate_paginated(
            api.list_recalls(
                COMPLIANCE_OFFICER, params={"salmonella_test_id": test["id"]}
            )
        )
        assert meta["total_count"] == 1
        recall = recalls[0]
        assert recall["status"] == "INITIATED"
        assert recall["scope_flock_id"] == ctx["flock"]["id"]
        assert recall["reason"] == "SALMONELLA"
        assert recall["salmonella_test_id"] == test["id"]
        assert recall["farm_id"] == ctx["farm"]["id"]

        assert get_farm(ctx["farm"]["id"])["compliance_posture"] == "SUSPENDED"
