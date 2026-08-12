"""Containers: fill gating, quarantine/reweigh, the shelf-life sweep, and
list pagination/filtering."""

import test_helpers as fx
from test_helpers import (
    ApiErrorId,
    QC_INSPECTOR,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_fill_before_qc_returns_invalid_state(api):
    """PRD §3.7: "With a batch `QC_APPROVED`, filling begins."
    PRD §2.9: "Gate six is state permission: the target resource must be in a
    state that permits the operation — this is the gate that catches
    stale-cycle color measurements, cancellation of an order already in
    production, completion of a hazardous disposal that never passed through
    its manifest, and adjustments recorded in the wrong batch phase, all as
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/fill_before_qc_returns_invalid_state
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    _tb1, _c1, f1, m1 = fx.setup_plant()
    b1 = fx.plan_batch(f1["id"], m1["id"], planned_gallons=3)
    fx.start_batch(b1["id"])
    assert fx.read_batch(b1["id"])["status"] == "MILLING"

    early = api.record_fill(b1["id"], {"size_code": "GALLON", "actual_fill_g": 4600},
                            fx.PRODUCTION_OPERATOR)
    validate_error(early, ApiErrorId.ERR_INVALID_STATE.value, 409)
    assert fx.read_batch(b1["id"])["status"] == "MILLING"

    containers, meta = validate_paginated(
        api.list_containers(fx.PRODUCTION_OPERATOR, params={"batch_id": b1["id"]})
    )
    assert containers == []
    assert meta["total_count"] == 0


def test_container_reweigh_cycle_quarantine_to_stock(api):
    """PRD §3.7: "A `QCInspector` reweighs a `QUARANTINED` container with a
    fresh `actual_fill_g`: if the new reading passes the same weigh gate, the
    container moves to `IN_STOCK` with `actual_fill_g`, `fill_variance_g`,
    and `net_weight_kg` recomputed and the batch's `filled_net_kg`
    reconciled"
    PRD §3.7: "its `net_weight_kg` is the actual grams divided by 1000 and
    rounded half up to two decimals, and the batch's `filled_net_kg` is
    reconciled to include it."

    Design: Corner/state_machines/container_reweigh_cycle_quarantine_to_stock
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    _tb1, _c1, f1, m1 = fx.setup_plant()
    b1 = fx.plan_batch(f1["id"], m1["id"], planned_gallons=3)
    fx.drive_batch_to_qc_approved(b1["id"], actual_gallons=3)

    k1 = fx.fill_container(b1["id"], "GALLON", 4530)
    assert k1["status"] == "QUARANTINED"
    assert k1["fill_variance_g"] == -70
    assert k1["net_weight_kg"] == 4.53
    assert fx.read_batch(b1["id"])["filled_net_kg"] == 4.53

    reweighed = validate_success(
        api.reweigh_container(k1["id"], {"actual_fill_g": 4600}, QC_INSPECTOR)
    )
    assert reweighed["status"] == "IN_STOCK", "a passing reweigh releases quarantine"
    assert reweighed["fill_variance_g"] == 0
    assert reweighed["net_weight_kg"] == 4.6
    assert fx.read_batch(b1["id"])["filled_net_kg"] == 4.6


def test_sweep_marks_obsolete_at_expiry_boundary(api):
    """PRD §3.8: "the daily operations sweep, a `PlantManager` capability,
    ages the inventory against the logical clock: every container still
    `IN_STOCK` whose `expiry_date` is on or before the sweep date turns
    `OBSOLETE` — the expiry day itself already counts as obsolete"
    PRD §3.7: "Either way the container is stamped with `manufactured_at`
    from the logical clock, its `expiry_date` is computed as the manufacture
    timestamp plus the tint base's `shelf_life_months` in calendar months"

    Design: Corner/state_machines/sweep_marks_obsolete_at_expiry_boundary
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    _tb1, _c1, f1, m1 = fx.setup_plant()
    b1 = fx.plan_batch(f1["id"], m1["id"], planned_gallons=1)
    fx.start_batch(b1["id"])
    fx.dispersion_pass(b1["id"], 18)
    fx.submit_qc(b1["id"], 1)
    cm1 = fx.enter_measurement(b1["id"], 0.42)
    fx.approve_match(cm1["id"])
    fx.set_clock("2026-06-10T10:00:00Z")
    k1 = fx.fill_container(b1["id"], "GALLON", 4600)
    fx.complete_filling(b1["id"], 0)

    # Manufactured 2026-06-10 + shelf_life 24 calendar months.
    assert k1["expiry_date"].startswith("2028-06-10"), (
        f"expiry must be manufacture + 24 calendar months, got {k1['expiry_date']}"
    )

    # The day before expiry the sweep leaves the can in stock.
    fx.set_clock("2028-06-09T00:00:00Z")
    fx.run_daily_sweep()
    assert fx.read_container(k1["id"])["status"] == "IN_STOCK"

    # On the expiry day itself the sweep turns it obsolete (inclusive).
    fx.set_clock("2028-06-10T00:00:00Z")
    sweep = fx.run_daily_sweep()
    assert k1["id"] in sweep["obsolete_container_ids"]
    assert fx.read_container(k1["id"])["status"] == "OBSOLETE"


def test_containers_list_pagination_defaults(api):
    """PRD §2.3: "The `limit` parameter sets the maximum number of items
    returned; it defaults to 10 when omitted, and accepts a minimum of 1 and
    a maximum of 100. The `offset` parameter sets the number of items to skip
    and defaults to 0."
    PRD §2.3: "Paginated list responses carry the following fields in the
    `meta` object of the envelope: `limit`, `offset`, `total_count`, and
    `has_more`."

    Design: Corner/endpoints/containers_list_pagination_defaults
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    _tb1, _c1, f1, m1 = fx.setup_plant()
    b1 = fx.plan_batch(f1["id"], m1["id"], planned_gallons=12)
    fx.drive_batch_to_qc_approved(b1["id"], actual_gallons=12)
    for _ in range(12):
        fx.fill_container(b1["id"], "GALLON", 4600)
    fx.complete_filling(b1["id"], 0)

    page1, meta1 = validate_paginated(
        api.list_containers(fx.PRODUCTION_OPERATOR, params={"batch_id": b1["id"]})
    )
    assert len(page1) == 10, "default limit is 10"
    assert meta1["limit"] == 10
    assert meta1["offset"] == 0
    assert meta1["total_count"] == 12
    assert meta1["has_more"] is True
    for can in page1:
        fx.assert_container(can)

    page2, meta2 = validate_paginated(
        api.list_containers(fx.PRODUCTION_OPERATOR,
                            params={"batch_id": b1["id"], "offset": 10})
    )
    assert len(page2) == 2
    assert meta2["has_more"] is False
    assert meta2["total_count"] == 12

    page1_ids = {c["id"] for c in page1}
    assert page1_ids.isdisjoint({c["id"] for c in page2})


def test_containers_list_filter_by_status(api):
    """PRD §3.8: "Containers can be listed with optional `batch_id`,
    `order_id`, `disposal_request_id`, and `status` filters."
    PRD §3.7: "A passing container is born `IN_STOCK`; a failing one is born
    `QUARANTINED`."

    Design: Corner/endpoints/containers_list_filter_by_status
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    _tb1, _c1, f1, m1 = fx.setup_plant()
    b1 = fx.plan_batch(f1["id"], m1["id"], planned_gallons=3)
    fx.drive_batch_to_qc_approved(b1["id"], actual_gallons=3)
    fx.fill_container(b1["id"], "GALLON", 4600)
    fx.fill_container(b1["id"], "GALLON", 4600)
    kq = fx.fill_container(b1["id"], "GALLON", 4500)
    assert kq["status"] == "QUARANTINED", "|4500-4600| = 100 > 69"

    quarantined, meta_q = validate_paginated(
        api.list_containers(QC_INSPECTOR,
                            params={"batch_id": b1["id"],
                                    "status": "QUARANTINED"})
    )
    assert meta_q["total_count"] == 1
    assert [c["id"] for c in quarantined] == [kq["id"]]

    in_stock, meta_s = validate_paginated(
        api.list_containers(QC_INSPECTOR,
                            params={"batch_id": b1["id"], "status": "IN_STOCK"})
    )
    assert meta_s["total_count"] == 2
    assert len(in_stock) == 2
    assert all(c["status"] == "IN_STOCK" for c in in_stock)
