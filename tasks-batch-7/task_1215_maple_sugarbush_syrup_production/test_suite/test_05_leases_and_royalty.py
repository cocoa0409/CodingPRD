"""Leases: creation rules, revision loop, OCC, snapshot pinning, terminate
cascade, and royalty settlement variants (PRD §2.6, §3.4, §3.7)."""
import pytest

from test_helpers import (
    ApiErrorId,
    activate_lease,
    activate_line,
    begin_tapping,
    collect_confirmed_run,
    create_bush,
    create_lease_on_bush,
    create_line,
    create_filling_batch,
    draw_from_run,
    finish_batch,
    get_only_syrup_lot,
    go_live,
    grade_lot,
    record_evaluation,
    setup_leased_live_operation,
    setup_open_season,
    start_boil,
    submit_lease,
    validate_error,
    validate_success,
)


def _setup_bush_tapping_with_lines(tap_counts=(100,)):
    """Season OPEN; bush TAPPING with the given ACTIVE lines. Returns dict."""
    season = setup_open_season()
    bush = create_bush(season["id"], name="Leased Hill")
    begin_tapping(bush["id"])
    lines = []
    for i, taps in enumerate(tap_counts, start=1):
        line = create_line(bush["id"], line_code=f"L{i}", tap_count=taps)
        lines.append(activate_line(line["id"]))
    return {"season": season, "bush": bush, "lines": lines}


def test_lease_patch_revision_loop(api, manager_headers):
    """PRD §3.4: "Amending a lease that is in `PENDING_AUDIT` sends it back to
    `DRAFT` for re-submission — this revision loop is intentional. Each
    amendment increments the lease's `version` by 1."

    Design: Corner/state_machines/lease_patch_revision_loop
    """
    ctx = _setup_bush_tapping_with_lines(())
    lease = create_lease_on_bush(ctx["bush"]["id"], per_tap_cents=300)
    submitted = submit_lease(lease["id"])
    assert submitted["status"] == "PENDING_AUDIT"

    amended = validate_success(
        api.patch_lease(lease["id"],
                        {"expected_lease_version": submitted["version"],
                         "per_tap_cents": 350},
                        manager_headers),
        200)
    assert amended["status"] == "DRAFT", "PATCH on PENDING_AUDIT returns the lease to DRAFT"
    assert amended["per_tap_cents"] == 350
    assert amended["version"] == submitted["version"] + 1


def test_occ_lease_stale_version(api, manager_headers):
    """PRD §2.6: "Amending a lease requires the request to carry
    `expected_lease_version`, the client's last observed `version` of that
    lease. If the lease's current `version` has advanced since the client last
    read it — for example because another writer amended or submitted the lease
    in the meantime — the amendment is rejected with `ERR_STALE_VERSION`
    (HTTP 412), preventing the client from overwriting terms it has not
    observed."

    Design: Corner/endpoints/occ_lease_stale_version
    """
    ctx = _setup_bush_tapping_with_lines(())
    lease = create_lease_on_bush(ctx["bush"]["id"], per_tap_cents=300)
    stale_v = lease["version"]

    amended = validate_success(
        api.patch_lease(lease["id"],
                        {"expected_lease_version": stale_v, "per_tap_cents": 350},
                        manager_headers),
        200)
    assert amended["version"] == stale_v + 1
    assert amended["per_tap_cents"] == 350

    res = api.patch_lease(lease["id"],
                          {"expected_lease_version": stale_v, "per_tap_cents": 400},
                          manager_headers)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    current = validate_success(api.get_lease(lease["id"], manager_headers), 200)
    assert current["per_tap_cents"] == 350


def test_lease_second_live_lease_conflict(api, manager_headers):
    """PRD §3.4: "the bush may not already have a lease in `DRAFT`,
    `PENDING_AUDIT`, or `ACTIVE` (otherwise `ERR_LEASE_CONFLICT`)."

    Design: Corner/validations/lease_second_live_lease_conflict
    """
    ctx = _setup_bush_tapping_with_lines(())
    create_lease_on_bush(ctx["bush"]["id"], per_tap_cents=300)

    res = api.create_lease(
        {
            "sugarbush_id": ctx["bush"]["id"],
            "landowner_name": "Other Owner",
            "royalty_basis": "PER_TAP",
            "per_tap_cents": 200,
            "certified_organic_required": False,
            "term_start": "2027-01-01",
            "term_end": "2027-12-31",
        },
        manager_headers)
    validate_error(res, ApiErrorId.ERR_LEASE_CONFLICT)


def test_lease_share_pct_conditional_required(api, manager_headers):
    """PRD §3.4: "when `royalty_basis` is `SHARE_OF_SYRUP`, `share_pct` must be
    present and greater than zero and at most 50, and `per_tap_cents` must be
    null. Violations of this conditional requiredness are `ERR_VALIDATION`."

    Design: Corner/validations/lease_share_pct_conditional_required
    """
    ctx = _setup_bush_tapping_with_lines(())
    res = api.create_lease(
        {
            "sugarbush_id": ctx["bush"]["id"],
            "landowner_name": "Landowner Lou",
            "royalty_basis": "SHARE_OF_SYRUP",
            "certified_organic_required": False,
            "term_start": "2027-01-01",
            "term_end": "2027-12-31",
        },
        manager_headers)
    validate_error(res, ApiErrorId.ERR_VALIDATION)


def test_per_tap_snapshot_pinned_at_activation(api, manager_headers):
    """PRD §3.4: "Activation freezes the lease's `taps_snapshot` to the bush's
    `taps_set` at that instant — the snapshot never changes afterward, no
    matter how taps evolve — and stamps the bush's `active_lease_id` to this
    lease and flips the bush's `stand_type` to `LEASED`. For a `PER_TAP` lease,
    activation also sets `accrued_royalty_cents` to the snapshot multiplied by
    `per_tap_cents`; that amount is final at activation and identical under
    both royalty accounting variants."

    Design: Corner/cross_cutting_complexity_layers/per_tap_snapshot_pinned_at_activation
    """
    ctx = _setup_bush_tapping_with_lines((100, 150))  # taps_set == 250
    lease = create_lease_on_bush(ctx["bush"]["id"], per_tap_cents=300)
    submit_lease(lease["id"])
    lease = activate_lease(lease["id"])
    assert lease["taps_snapshot"] == 250
    assert lease["accrued_royalty_cents"] == 75000

    bush = validate_success(api.get_sugarbush(ctx["bush"]["id"], manager_headers), 200)
    assert bush["stand_type"] == "LEASED"
    assert bush["active_lease_id"] == lease["id"]

    # Taps evolve after activation: snapshot and royalty stay pinned.
    line3 = create_line(ctx["bush"]["id"], line_code="L3", tap_count=80)
    activate_line(line3["id"])
    bush = validate_success(api.get_sugarbush(ctx["bush"]["id"], manager_headers), 200)
    assert bush["taps_set"] == 330

    lease_after = validate_success(api.get_lease(lease["id"], manager_headers), 200)
    assert lease_after["taps_snapshot"] == 250
    assert lease_after["accrued_royalty_cents"] == 75000


def test_lease_terminate_marks_terminated_keeps_royalty(api, manager_headers):
    """PRD §3.4: "Terminating a lease moves `ACTIVE → TERMINATED` and cascades:
    if the bush is in `TAPPING` or `LIVE` it moves to `SHUTDOWN`; that shutdown
    pulls every non-`PULLED` tap line of the bush to `PULLED`; and each pull
    recomputes the bush's `taps_set` and `taps_live` and the season's
    `taps_live`."
    PRD §3.4: "For a `PER_TAP` lease, activation also sets
    `accrued_royalty_cents` to the snapshot multiplied by `per_tap_cents`; that
    amount is final at activation and identical under both royalty accounting
    variants."

    Design: Difficulty/transitive_cascade/lease_terminate_cascade_depth3
    """
    ctx = _setup_bush_tapping_with_lines((60, 40))  # taps_set == 100
    lease = create_lease_on_bush(ctx["bush"]["id"], per_tap_cents=300)
    submit_lease(lease["id"])
    lease = activate_lease(lease["id"])
    assert lease["taps_snapshot"] == 100
    assert lease["accrued_royalty_cents"] == 30000
    go_live(ctx["bush"]["id"])

    terminated = validate_success(api.terminate_lease(lease["id"], manager_headers), 200)
    assert terminated["status"] == "TERMINATED"
    assert terminated["accrued_royalty_cents"] == 30000
    assert terminated["taps_snapshot"] == 100


def test_lease_terminate_cascades_bush_shutdown(api, manager_headers):
    """PRD §3.4: "Terminating a lease moves `ACTIVE → TERMINATED` and cascades:
    if the bush is in `TAPPING` or `LIVE` it moves to `SHUTDOWN`; that shutdown
    pulls every non-`PULLED` tap line of the bush to `PULLED`; and each pull
    recomputes the bush's `taps_set` and `taps_live` and the season's
    `taps_live`. The bush's `active_lease_id` is *not* cleared — history is
    preserved — and `stand_type` stays `LEASED`."

    Design: Difficulty/transitive_cascade/lease_terminate_cascade_depth3
    """
    ctx = _setup_bush_tapping_with_lines((60, 40))
    lease = create_lease_on_bush(ctx["bush"]["id"], per_tap_cents=300)
    submit_lease(lease["id"])
    lease = activate_lease(lease["id"])
    go_live(ctx["bush"]["id"])

    validate_success(api.terminate_lease(lease["id"], manager_headers), 200)

    bush = validate_success(api.get_sugarbush(ctx["bush"]["id"], manager_headers), 200)
    assert bush["status"] == "SHUTDOWN"
    assert bush["taps_set"] == 0
    assert bush["taps_live"] == 0
    assert bush["stand_type"] == "LEASED"
    assert bush["active_lease_id"] == lease["id"], "active_lease_id retained for history"

    for line in ctx["lines"]:
        after = validate_success(api.get_tap_line(line["id"], manager_headers), 200)
        assert after["status"] == "PULLED"

    season = validate_success(api.get_season(ctx["season"]["id"], manager_headers), 200)
    assert season["taps_live"] == 0


def _finish_share_batch(ctx, gallons=245.0, brix=1.0, collected_at="2027-03-05T08:00:00Z",
                        boil_at="2027-03-05T18:00:00Z", measured=2.90):
    """One 245-gal @ 1.0 run, fully drawn, boiled 10h later (no full days, so
    no deterioration), finished. Returns the FINISHED batch."""
    run = collect_confirmed_run(ctx, gallons, brix, clock=collected_at)
    batch = create_filling_batch(ctx, capacity=300)
    draw_from_run(ctx, batch["id"], run["id"], gallons)
    batch = start_boil(ctx, batch["id"], clock=boil_at)
    return finish_batch(ctx, batch["id"], 66.5, measured)


def test_provisional_accrual_double_rounding(api, manager_headers):
    """PRD §3.7: "At each batch finish, for each bush that contributed intakes
    to that batch and has such a lease, the attributable syrup for that bush is
    computed as the sum over that bush's intakes of `gallons_drawn` multiplied
    by the intake's `effective_brix`, divided by 86, rounded to 2 decimal
    places round half up; the per-batch royalty is that attributable amount
    multiplied by the lease's `share_pct` and divided by 100, again rounded to
    2 decimal places round half up."
    (245 gal @ 1.0 brix: attributable round(245/86, 2) = 2.85, royalty
    round(2.85 * 0.30, 2) = 0.86 — double rounding; a single final rounding
    would give 0.85.)

    Design: Difficulty/combinatorial_formula/royalty_per_batch_double_rounding
    """
    ctx = setup_leased_live_operation(share_pct=30.0)
    _finish_share_batch(ctx)
    lease = validate_success(api.get_lease(ctx["lease"]["id"], manager_headers), 200)
    assert lease["accrued_royalty_gallons"] == pytest.approx(0.86, abs=0.004)


def test_provisional_accrual_sums_per_batch(api, manager_headers):
    """PRD §3.7: "The lease's `accrued_royalty_gallons` is the running sum of
    these per-batch, double-rounded royalty figures over all finished batches
    to which the bush contributed."
    (Two identical batches: 0.86 + 0.86 = 1.72 — the sum of per-batch rounded
    royalties, not a single rounding of the combined raw figure, which would
    give 1.71.)

    Design: Difficulty/combinatorial_formula/royalty_per_batch_double_rounding
    """
    ctx = setup_leased_live_operation(share_pct=30.0)
    _finish_share_batch(ctx)
    _finish_share_batch(ctx, collected_at="2027-03-06T08:00:00Z",
                        boil_at="2027-03-06T18:00:00Z")
    lease = validate_success(api.get_lease(ctx["lease"]["id"], manager_headers), 200)
    assert lease["accrued_royalty_gallons"] == pytest.approx(1.72, abs=0.004)


def test_royalty_provisional_accrual_after_finish(api, manager_headers):
    """PRD §3.7: "For a `SHARE_OF_SYRUP` lease, the **provisional** variant
    accrues as batches finish during the season." and "The lease's
    `accrued_royalty_gallons` is the running sum of these per-batch,
    double-rounded royalty figures over all finished batches to which the bush
    contributed."

    Design: Difficulty/dual_variant_calc/royalty_provisional_vs_final_settlement
    """
    ctx = setup_leased_live_operation(share_pct=30.0, with_grader=True)
    _finish_share_batch(ctx)
    lease = validate_success(api.get_lease(ctx["lease"]["id"], manager_headers), 200)
    assert lease["accrued_royalty_gallons"] == pytest.approx(0.86, abs=0.004)
    assert lease.get("settled_royalty_gallons") is None, (
        "settled_royalty_gallons stays null until reconcile")


def test_royalty_final_settlement_after_reconcile(api, manager_headers):
    """PRD §3.7: "The **final** variant runs once, at season reconcile, and
    uses a different basis: for each finished batch, the bush's attributable
    share is the fraction of the batch's `sap_gallons_in` that came from that
    bush's draws, multiplied by the batch's actual `measured_syrup_gallons` —
    a volume-share of real output rather than a Rule-of-86 attribution. These
    per-batch attributable amounts are accumulated *without* intermediate
    rounding, and the lease's `settled_royalty_gallons` is the lease's
    `share_pct` divided by 100, multiplied by the accumulated total, rounded to
    2 decimal places round half up — a single rounding at the very end."
    (245/245 * 2.90 = 2.90; round(0.30 * 2.90, 2) = 0.87 — distinct from the
    provisional 0.86 for identical batch data.)

    Design: Difficulty/dual_variant_calc/royalty_provisional_vs_final_settlement
    """
    ctx = setup_leased_live_operation(share_pct=30.0, with_grader=True)
    _finish_share_batch(ctx)
    lot = get_only_syrup_lot()
    record_evaluation(ctx, lot["id"], 90)
    grade_lot(ctx, lot["id"], 80.0)  # GRADED so reconcile is unblocked

    validate_success(api.close_season(ctx["season"]["id"], manager_headers), 200)
    reconciled = validate_success(
        api.reconcile_season(ctx["season"]["id"], manager_headers), 200)
    assert reconciled["status"] == "RECONCILED"

    lease = validate_success(api.get_lease(ctx["lease"]["id"], manager_headers), 200)
    assert lease["accrued_royalty_gallons"] == pytest.approx(0.86, abs=0.004)
    assert lease["settled_royalty_gallons"] == pytest.approx(0.87, abs=0.004)
    assert (lease["settled_royalty_gallons"]
            != lease["accrued_royalty_gallons"]), (
        "final settlement (single rounding) differs from provisional (double rounding)")
