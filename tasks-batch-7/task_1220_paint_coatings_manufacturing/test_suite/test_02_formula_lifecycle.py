"""Formula evolution: OCC-guarded supersede, successor-activation cascades,
and manual deprecation."""

import test_helpers as fx
from test_helpers import (
    LAB_TECHNICIAN,
    ApiErrorId,
    validate_error,
    validate_success,
)


def test_supersede_rejects_stale_expected_version(api):
    """PRD §2.7: "The supersede request must include
    `expected_formula_version`, set to the predecessor formula's `version` as
    the client last observed it. If that value no longer matches the
    predecessor's current `version` — because the formula has been mutated
    since the client's last read, for example by an earlier supersede that
    advanced the version — the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412), and no successor is created."
    PRD §3.1: "The act of superseding increments the predecessor formula's
    `version` by one, which is precisely what makes a second, out-of-date
    supersede attempt fail the `expected_formula_version` check."

    Design: Corner/cross_cutting_layers/occ_formula_supersede_stale_version
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    tb1, c1, f1 = fx.setup_lab_catalog()
    fx.activate_formula(f1["id"])
    f1_before = fx.read_formula(f1["id"])
    observed_version = f1_before["version"]

    def supersede(code, expected_version):
        return api.supersede_formula(
            f1["id"],
            {
                "formula_code": code,
                "color_name": "Desert Dusk R2",
                "target_delta_e": 0.7,
                "lines": [
                    {"colorant_id": c1["id"], "shots_per_gallon": 4, "sequence": 1}
                ],
                "expected_formula_version": expected_version,
            },
            LAB_TECHNICIAN,
        )

    first = validate_success(supersede("CLR-8841-R2", observed_version),
                             expected_status=201)
    assert first["status"] == "DRAFT"
    assert first["formula_version_no"] == f1_before["formula_version_no"] + 1
    assert first["predecessor_formula_id"] == f1["id"]

    # Replaying the same stale version is refused.
    replay = supersede("CLR-8841-R3", observed_version)
    validate_error(replay, ApiErrorId.ERR_STALE_VERSION.value, 412)

    f1_mid = fx.read_formula(f1["id"])
    assert f1_mid["version"] == observed_version + 1, (
        "each supersede increments the predecessor version by one"
    )

    # A refetched current version unblocks the next supersede.
    third = validate_success(supersede("CLR-8841-R3", f1_mid["version"]),
                             expected_status=201)
    assert third["formula_version_no"] == f1_before["formula_version_no"] + 1
    f1_after = fx.read_formula(f1["id"])
    assert f1_after["version"] == observed_version + 2


def test_supersede_leaves_predecessor_active_until_successor_activates(api):
    """PRD §3.1: "The predecessor itself stays `ACTIVE`; it is deprecated only
    when a successor activates."

    Design: Corner/cross_cutting_layers/occ_formula_supersede_stale_version
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    tb1, c1, f1 = fx.setup_lab_catalog()
    fx.activate_formula(f1["id"])
    observed = fx.read_formula(f1["id"])["version"]

    successor = validate_success(
        api.supersede_formula(
            f1["id"],
            {
                "formula_code": "CLR-8841-R2",
                "color_name": "Desert Dusk R2",
                "target_delta_e": 0.7,
                "lines": [
                    {"colorant_id": c1["id"], "shots_per_gallon": 4, "sequence": 1}
                ],
                "expected_formula_version": observed,
            },
            LAB_TECHNICIAN,
        ),
        expected_status=201,
    )
    # Predecessor is still ACTIVE after the supersede itself.
    assert fx.read_formula(f1["id"])["status"] == "ACTIVE"
    assert fx.read_formula(successor["id"])["status"] == "DRAFT"

    # Only successor activation deprecates the predecessor.
    validate_success(api.activate_formula(successor["id"], LAB_TECHNICIAN))
    assert fx.read_formula(f1["id"])["status"] == "DEPRECATED"
    assert fx.read_formula(successor["id"])["status"] == "ACTIVE"


def _setup_planned_batch_on_f1(api):
    """F1 ACTIVE at captured version; CU1; O1 PLACED; B1 PLANNED for O1;
    O1 SCHEDULED via B1."""
    fx.set_clock("2026-05-01T00:00:00Z")
    tb1, c1, f1, m1 = fx.setup_plant()
    f1_version = fx.read_formula(f1["id"])["version"]
    cu1 = fx.create_customer(name="Sunbelt Paints AZ")
    o1 = validate_success(
        api.create_order(
            fx.create_order_payload(
                cu1["id"], f1["id"],
                lines=[{"formula_id": f1["id"], "gallons": 10,
                        "size_code": "GALLON"}],
            ),
            fx.make_dealer_headers(cu1["id"]),
        ),
        expected_status=201,
    )
    b1 = fx.plan_batch(f1["id"], m1["id"], planned_gallons=10, order_id=o1["id"])
    b1_version_pre = b1["version"]
    validate_success(
        api.schedule_order(o1["id"], {"batch_id": b1["id"]},
                           fx.PRODUCTION_OPERATOR)
    )
    return tb1, c1, f1, m1, cu1, o1, b1, f1_version, b1_version_pre


def test_successor_activation_cascades_formula_to_batch_to_order(api):
    """PRD §3.1: "If the activating formula has a predecessor that is still
    `ACTIVE`, that predecessor transitions to `DEPRECATED` — cascade link one.
    Every batch still in `PLANNED` against the deprecated predecessor moves to
    `ON_HOLD` — link two. And each such held batch's order, if that order is
    `SCHEDULED`, moves to `BLOCKED` — link three."
    PRD §2.4: "`version` (integer): a system-managed integer that increments
    with every mutation of the resource, including mutations the server
    applies automatically as cascade side effects."

    Design: Difficulty/transitive_cascade/formula_activation_cascade_depth3
    """
    tb1, c1, f1, m1, cu1, o1, b1, f1_version, b1_version_pre = (
        _setup_planned_batch_on_f1(api)
    )

    successor = validate_success(
        api.supersede_formula(
            f1["id"],
            {
                "formula_code": "CLR-8841-R2",
                "color_name": "Desert Dusk R2",
                "target_delta_e": 0.8,
                "lines": [
                    {"colorant_id": c1["id"], "shots_per_gallon": 4, "sequence": 1}
                ],
                "expected_formula_version": f1_version,
            },
            LAB_TECHNICIAN,
        ),
        expected_status=201,
    )
    validate_success(api.activate_formula(successor["id"], LAB_TECHNICIAN))

    # Link 1: predecessor deprecated by the successor's activation.
    assert fx.read_formula(f1["id"])["status"] == "DEPRECATED"
    # Link 2: the still-planned batch went on hold (a cascaded mutation).
    b1_held = fx.read_batch(b1["id"])
    assert b1_held["status"] == "ON_HOLD"
    assert b1_held["version"] > b1_version_pre, (
        "the cascade mutates the batch, so its version must advance"
    )
    # Link 3: the scheduled order is blocked.
    assert fx.read_order(o1["id"])["status"] == "BLOCKED"

    # The chain unwinds on resume.
    resumed = validate_success(
        api.resume_batch(b1["id"], {"new_formula_id": successor["id"]},
                         fx.PRODUCTION_OPERATOR)
    )
    assert resumed["status"] == "PLANNED"
    assert resumed["formula_id"] == successor["id"]
    assert resumed["pinned_formula_version_no"] == successor["formula_version_no"]
    assert fx.read_order(o1["id"])["status"] == "SCHEDULED"


def test_successor_carries_version_and_predecessor_link(api):
    """PRD §3.1: "Superseding an `ACTIVE` formula — the OCC-guarded write of
    §2.7 — creates a successor in `DRAFT` carrying the request's
    `formula_code`, `color_name`, `target_delta_e`, and `lines`, with
    `formula_version_no` set to the predecessor's number plus one and
    `predecessor_formula_id` pointing back at the predecessor."

    Design: Difficulty/transitive_cascade/formula_activation_cascade_depth3
    """
    tb1, c1, f1, m1, cu1, o1, b1, f1_version, _b1v = (
        _setup_planned_batch_on_f1(api)
    )
    f1_full = fx.read_formula(f1["id"])

    successor = validate_success(
        api.supersede_formula(
            f1["id"],
            {
                "formula_code": "CLR-8841-R2",
                "color_name": "Desert Dusk R2",
                "target_delta_e": 0.8,
                "lines": [
                    {"colorant_id": c1["id"], "shots_per_gallon": 4, "sequence": 1}
                ],
                "expected_formula_version": f1_version,
            },
            LAB_TECHNICIAN,
        ),
        expected_status=201,
    )
    assert successor["formula_version_no"] == f1_full["formula_version_no"] + 1
    assert successor["predecessor_formula_id"] == f1["id"]
    assert successor["status"] == "DRAFT"

    validate_success(api.activate_formula(successor["id"], LAB_TECHNICIAN))
    assert fx.read_formula(f1["id"])["status"] == "DEPRECATED"
    assert fx.read_batch(b1["id"])["status"] == "ON_HOLD"
    assert fx.read_order(o1["id"])["status"] == "BLOCKED"


def test_deprecation_cascade_bumps_batch_version(api):
    """PRD §2.8: "Each of these automatic transitions mutates the affected
    resource, refreshing its `updated_at` and incrementing its `version`."
    PRD §3.1: "Manual deprecation follows the same shape: deprecating an
    `ACTIVE` formula runs the identical batch-and-order cascade, while
    deprecating a `DRAFT` formula simply abandons it, and because no batch can
    reference a draft, no cascade fires."

    Design: Corner/cross_cutting_layers/cascade_bumps_batch_version_and_updated_at
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    tb1, c1, f1, m1 = fx.setup_plant()
    b1 = fx.plan_batch(f1["id"], m1["id"], planned_gallons=3)
    version_at_create = b1["version"]

    validate_success(api.deprecate_formula(f1["id"], LAB_TECHNICIAN))

    b1_after = fx.read_batch(b1["id"])
    assert b1_after["status"] == "ON_HOLD"
    assert b1_after["version"] == version_at_create + 1, (
        f"the cascaded hold must increment version by one "
        f"({version_at_create} -> {b1_after['version']})"
    )
