"""Kit deployment under optimistic concurrency, refurbishment and the census."""

from test_helpers import (
    ApiErrorId,
    assert_device_component,
    assert_device_kit,
    assert_kit_census_balanced,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.factories import deploy_kit_payload
from test_helpers.test_users import FIELD_NURSE, PROGRAM_ADMIN


def test_stale_kit_version_beats_the_kit_unavailable_capacity_rule(api):
    """PRD §2.6: "A `POST /device-kits/{id}/deploy` request must carry
    `expected_kit_version` holding the `version` of the `DeviceKit` the client
    last observed. If the kit's current `version` differs — because another nurse
    deployed it, or because it was pulled into refurbishment — the deployment is
    rejected with `ERR_STALE_VERSION` at HTTP 412."
    PRD §2.5: "**Rung 6 — Optimistic concurrency.** The supplied
    `expected_kit_version`, `expected_unit_version` or `expected_episode_version`
    equals the current `version` of the named parent row. Violation:
    `ERR_STALE_VERSION` (412). This rung guards exactly three endpoints: `POST
    /device-kits/{id}/deploy`, `POST /bed-reservations` and `POST
    /billing-claims`."

    Design: Difficulty/priority_pair_validation_conflict/occ_stale_kit_version_beats_kit_unavailable_capacity_rule
    """
    first = fx.setup_active_episode(mrn="MRN-K1", full_name="Kim Kit")
    second = fx.setup_active_episode(
        set_the_clock=False, mrn="MRN-K2", full_name="Ken Kit"
    )

    kit = fx.register_kit(asset_tag="KIT-K1")
    version_at_creation = kit["version"]
    fx.deploy_kit(kit["id"], first["episode"]["id"], version_at_creation)

    response = api.deploy_device_kit(
        kit["id"],
        deploy_kit_payload(second["episode"]["id"], version_at_creation),
        FIELD_NURSE,
    )
    error = validate_error(response, ApiErrorId.ERR_STALE_VERSION.value)
    assert error["error_id"] != "ERR_KIT_UNAVAILABLE", (
        "the concurrency rung is evaluated above the capacity rung"
    )


def test_rejected_stale_deploy_leaves_the_kit_untouched(api):
    """PRD §2.6: "A kit legitimately serves at most one episode at a time, so
    refusing the stale write is what prevents the kit from being silently
    re-pointed at a different episode."
    PRD §3.5: "A successful deployment moves the kit `AVAILABLE → DEPLOYED`, sets
    `assigned_episode_id` to the target episode, stamps `deployed_at` from the
    logical clock, moves every one of that kit's components from `IN_STOCK` to
    `DEPLOYED`, and advances the kit's `version` by 1."

    Design: Difficulty/priority_pair_validation_conflict/occ_stale_kit_version_beats_kit_unavailable_capacity_rule
    """
    first = fx.setup_active_episode(mrn="MRN-K3", full_name="Kim Kit Three")
    second = fx.setup_active_episode(
        set_the_clock=False, mrn="MRN-K4", full_name="Ken Kit Four"
    )

    kit = fx.register_kit(asset_tag="KIT-K2")
    version_at_creation = kit["version"]
    deployed = fx.deploy_kit(kit["id"], first["episode"]["id"], version_at_creation)
    version_after_deploy = deployed["version"]

    validate_error(
        api.deploy_device_kit(
            kit["id"],
            deploy_kit_payload(second["episode"]["id"], version_at_creation),
            FIELD_NURSE,
        ),
        ApiErrorId.ERR_STALE_VERSION.value,
    )

    unchanged = validate_success(api.get_device_kit(kit["id"], PROGRAM_ADMIN))
    assert_device_kit(unchanged)
    assert unchanged["assigned_episode_id"] == first["episode"]["id"], (
        "the rejected write must not re-point the kit at another episode"
    )
    assert unchanged["status"] == "DEPLOYED"
    assert unchanged["version"] == version_after_deploy, (
        "a rejected deployment does not advance the kit's version"
    )


def test_fresh_version_on_a_deployed_kit_returns_kit_unavailable(api):
    """PRD §3.5: "And the capacity rule that follows requires both that the kit
    itself is currently `AVAILABLE` and that no *other* kit is already `DEPLOYED`
    to the same episode — one episode, one kit — with either failure reported as
    `ERR_KIT_UNAVAILABLE` at HTTP 409."

    Design: Corner/validations/kit_deploy_with_fresh_version_but_deployed_kit_returns_kit_unavailable
    """
    first = fx.setup_active_episode(mrn="MRN-KA", full_name="Kay Alpha")
    second = fx.setup_active_episode(
        set_the_clock=False, mrn="MRN-KB", full_name="Kim Beta"
    )

    kit = fx.register_kit(asset_tag="KIT-KU1")
    fx.deploy_kit(kit["id"], first["episode"]["id"], kit["version"])
    fresh = validate_success(api.get_device_kit(kit["id"], FIELD_NURSE))

    error = validate_error(
        api.deploy_device_kit(
            kit["id"],
            deploy_kit_payload(second["episode"]["id"], fresh["version"]),
            FIELD_NURSE,
        ),
        ApiErrorId.ERR_KIT_UNAVAILABLE.value,
    )
    assert error["error_id"] != "ERR_STALE_VERSION", (
        "a freshly re-read version clears the concurrency rung"
    )

    still_first = validate_success(api.get_device_kit(kit["id"], PROGRAM_ADMIN))
    assert still_first["assigned_episode_id"] == first["episode"]["id"]
    assert still_first["status"] == "DEPLOYED"

    rows, meta = validate_paginated(
        api.list_episode_device_kits(second["episode"]["id"], PROGRAM_ADMIN)
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_kit_components_subresource_returns_only_that_kits_components(api):
    """PRD §3.5: "The kits currently assigned to an episode are listable, as are
    a kit's components, the latter filterable by `reconciliation_status`."
    PRD §3.5: "Each component opens with `reconciliation_status` of `IN_STOCK`,
    and adding one refreshes the owning kit's `component_count`, which is simply
    the number of components attached to it."

    Design: Corner/endpoints/device_kit_components_subresource_returns_only_that_kits_components
    """
    first_kit = fx.register_kit(asset_tag="KIT-S1")
    second_kit = fx.register_kit(asset_tag="KIT-S2")

    tablet = fx.add_component(
        first_kit["id"],
        component_type="TABLET",
        serial_number="SN-S1A",
        replacement_cost_usd=450.00,
    )
    pulse_ox = fx.add_component(
        first_kit["id"],
        component_type="PULSE_OX",
        serial_number="SN-S1B",
        replacement_cost_usd=65.00,
    )
    scale = fx.add_component(
        second_kit["id"],
        component_type="SCALE",
        serial_number="SN-S2A",
        replacement_cost_usd=120.00,
    )

    rows, meta = validate_paginated(
        api.list_device_kit_components(first_kit["id"], PROGRAM_ADMIN)
    )
    assert meta["total_count"] == 2
    ids = {row["id"] for row in rows}
    assert ids == {tablet["id"], pulse_ox["id"]}
    assert scale["id"] not in ids, "a sibling kit's component must never leak"
    for row in rows:
        assert_device_component(row)
        assert row["reconciliation_status"] == "IN_STOCK"

    filtered, filtered_meta = validate_paginated(
        api.list_device_kit_components(
            second_kit["id"], PROGRAM_ADMIN, params={"reconciliation_status": "IN_STOCK"}
        )
    )
    assert filtered_meta["total_count"] == 1
    assert filtered[0]["id"] == scale["id"]

    assert (
        validate_success(api.get_device_kit(first_kit["id"], PROGRAM_ADMIN))[
            "component_count"
        ]
        == 2
    )
    assert (
        validate_success(api.get_device_kit(second_kit["id"], PROGRAM_ADMIN))[
            "component_count"
        ]
        == 1
    )


def test_kit_census_balances_while_a_kit_sits_in_refurbishment(api):
    """PRD §2.8: "Every monitoring kit ever created sits in exactly one of
    `AVAILABLE`, `DEPLOYED`, `IN_REFURB` or `RETIRED`. Kits are never deleted, so
    the program-wide census read returns `total_kits` equal to the sum of
    `available_count`, `deployed_count`, `in_refurb_count` and `retired_count`."
    PRD §3.5: "the kit whose `assigned_episode_id` is that episode and whose
    `status` is `DEPLOYED` moves `DEPLOYED → IN_REFURB`, its
    `assigned_episode_id` is cleared to null, its `refurb_cycle_count` is
    incremented by 1, every one of its components sitting in `DEPLOYED` moves to
    `PENDING_RECONCILIATION`, and the kit's `version` advances by 1."

    Design: Difficulty/compensating_invariant/device_kit_census_conserved_across_deploy_refurbish_return_cycle
    """
    parts = fx.setup_active_episode(
        primary_diagnosis_code="COPD_EXAC",
        qualifying_condition_code="COPD_EXAC",
        mrn="MRN-V1",
        full_name="Vic Vault",
    )
    episode_id = parts["episode"]["id"]

    kit = fx.register_kit(asset_tag="KIT-V1")
    fx.register_kit(asset_tag="KIT-V2")
    fx.register_kit(asset_tag="KIT-V3")
    component = fx.add_component(
        kit["id"],
        component_type="GATEWAY",
        serial_number="SN-V1",
        replacement_cost_usd=210.00,
    )
    fx.deploy_kit(kit["id"], episode_id, kit["version"])
    fx.begin_discharge(episode_id)

    census = validate_success(api.get_device_kit_census(PROGRAM_ADMIN))
    assert_kit_census_balanced(census)
    assert census["total_kits"] == 3
    assert census["available_count"] == 2
    assert census["deployed_count"] == 0
    assert census["in_refurb_count"] == 1
    assert census["retired_count"] == 0

    released = fx.read_component(kit["id"], component["id"])
    assert released["reconciliation_status"] == "PENDING_RECONCILIATION"


def test_reconciling_the_last_component_returns_the_kit_to_the_available_bucket(api):
    """PRD §3.5: "When that count reaches 0 the kit leaves refurbishment, and
    **which state it leaves for depends on how many cycles it has already
    served**: a kit whose `refurb_cycle_count` is at or below five moves
    `IN_REFURB → AVAILABLE`, and as part of that move every component of the kit
    sitting in `RETURNED` is returned to `IN_STOCK` so the kit is whole again for
    its next deployment"
    PRD §2.8: "Kits are never deleted, so the program-wide census read returns
    `total_kits` equal to the sum of `available_count`, `deployed_count`,
    `in_refurb_count` and `retired_count`."

    Design: Difficulty/compensating_invariant/device_kit_census_conserved_across_deploy_refurbish_return_cycle
    """
    parts = fx.setup_active_episode(
        primary_diagnosis_code="COPD_EXAC",
        qualifying_condition_code="COPD_EXAC",
        mrn="MRN-V2",
        full_name="Vic Vault Two",
    )
    episode_id = parts["episode"]["id"]

    kit = fx.register_kit(asset_tag="KIT-V4")
    fx.register_kit(asset_tag="KIT-V5")
    fx.register_kit(asset_tag="KIT-V6")
    component = fx.add_component(
        kit["id"],
        component_type="GATEWAY",
        serial_number="SN-V2",
        replacement_cost_usd=210.00,
    )
    fx.deploy_kit(kit["id"], episode_id, kit["version"])
    fx.begin_discharge(episode_id)

    fx.reconcile_component(component["id"], "RETURNED")

    restored = validate_success(api.get_device_kit(kit["id"], PROGRAM_ADMIN))
    assert restored["status"] == "AVAILABLE"
    assert restored["refurb_cycle_count"] == 1
    assert restored["assigned_episode_id"] is None
    assert restored["unreconciled_component_count"] == 0

    census = validate_success(api.get_device_kit_census(PROGRAM_ADMIN))
    assert_kit_census_balanced(census)
    assert census["total_kits"] == 3
    assert census["available_count"] == 3
    assert census["deployed_count"] == 0
    assert census["in_refurb_count"] == 0
    assert census["retired_count"] == 0
