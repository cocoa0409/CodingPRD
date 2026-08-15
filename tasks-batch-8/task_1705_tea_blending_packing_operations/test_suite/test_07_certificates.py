"""Certificate grants: closed-interval window conflicts, the clock expiry
sweep, the suspend/reinstate loop, the release-time chain audit, the
volume ledger, and the certificate-suspend cascade.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    allocate,
    blend_batch,
    create_active_recipe,
    create_batch,
    create_certificate,
    create_certificate_payload,
    create_locked_batch_with_allocations,
    create_packaging_line,
    create_qc_batch,
    create_released_lot,
    create_run,
    create_supplier,
    finalize_allocation,
    get_batch,
    get_certificate,
    lock_recipe,
    release_batch,
    set_clock,
    single_component,
    submit_qc,
    validate_error,
    validate_success,
)

CO = TEST_USERS["certification_officer_headers"]


class TestCertificateWindowConflict:
    def test_shared_boundary_date_overlaps(self, api):
        """PRD §3.6: "One supplier may hold several grants, but their
        intervals may not collide: a new grant whose closed interval
        overlaps — shared boundary dates count as overlap — an existing
        `ACTIVE` or `SUSPENDED` grant of the same `supplier_id` and
        `cert_type` is rejected with `ERR_CERT_WINDOW_CONFLICT`."

        The existing ORGANIC grant ends 2026-06-30; the new one starts
        2026-06-30 — the shared boundary date is itself an overlap.

        Design: Difficulty/resource_temporal_overlap/certificate_closed_interval_adjacency_rejected
        """
        supplier = create_supplier(name="Cert Co", origin_region="Yunnan")
        create_certificate(supplier["id"], cert_type="ORGANIC",
                           total_volume_kg=5000.0, valid_from="2026-01-01",
                           valid_until="2026-06-30")
        res = api.create_certificate(
            create_certificate_payload(
                supplier["id"], cert_type="ORGANIC", total_volume_kg=5000.0,
                valid_from="2026-06-30", valid_until="2026-12-31"), CO)
        validate_error(res, ApiErrorId.ERR_CERT_WINDOW_CONFLICT)

    def test_different_cert_type_same_dates_accepted(self, api):
        """PRD §3.6: "an existing `ACTIVE` or `SUSPENDED` grant of the
        same `supplier_id` and `cert_type`"

        The conflict scope is the (supplier, cert_type) pair: a
        FAIR_TRADE grant over overlapping dates for the same supplier is
        accepted.

        Design: Difficulty/resource_temporal_overlap/certificate_closed_interval_adjacency_rejected
        """
        supplier = create_supplier(name="Cert Co 2", origin_region="Yunnan")
        create_certificate(supplier["id"], cert_type="ORGANIC",
                           total_volume_kg=5000.0, valid_from="2026-01-01",
                           valid_until="2026-06-30")
        res = api.create_certificate(
            create_certificate_payload(
                supplier["id"], cert_type="FAIR_TRADE",
                total_volume_kg=5000.0, valid_from="2026-03-01",
                valid_until="2026-09-30"), CO)
        granted = validate_success(res, 201)
        assert granted["cert_type"] == "FAIR_TRADE"
        assert granted["status"] == "ACTIVE"


def test_cert_missing_at_release_rejected(api):
    """PRD §3.5: "For recipes whose `certification_target` is `ORGANIC`
    or `FAIR_TRADE`, the certification chain is then audited supplier by
    supplier: every supplier contributing `ACTIVE` allocations to the
    batch must hold a certificate grant whose `cert_type` matches the
    recipe's target, whose status is `ACTIVE`, and whose validity
    interval contains the current logical-clock date — on or after
    `valid_from` and on or before `valid_until` — or the release fails
    with `ERR_CERT_NOT_ACTIVE`"

    The contributing supplier holds no certificates at all.

    Design: Corner/validations/cert_missing_at_release_rejected
    """
    supplier = create_supplier(name="NoCert Co")
    lot = create_released_lot(supplier["id"], leaf_type="GREEN",
                              weight_kg=30.0)
    recipe = create_active_recipe(
        name="RNC", certification_target="ORGANIC", pack_format="LOOSE_PACK",
        components=[single_component("GREEN", "C", 100.0)])
    batch = create_qc_batch(recipe, 20.0, [(lot["id"], 20.0)],
                            measured_moisture_pct=5.0)

    res = api.release_batch(batch["id"], TEST_USERS["qa_manager_headers"])
    validate_error(res, ApiErrorId.ERR_CERT_NOT_ACTIVE)
    assert get_batch(batch["id"])["status"] == "QC_REVIEW"


def test_cert_volume_exhausted_rejected(api):
    """PRD §3.5: "and each such grant's remaining volume, its
    `total_volume_kg` minus its `consumed_volume_kg`, must be at least
    the kilograms that supplier contributes to the batch, or the release
    fails with `ERR_CERT_VOLUME_EXHAUSTED`."

    The grant covers 30.0 kg but the batch draws 50.0 kg from that
    supplier (35.0 + 15.0; the 70% share is exactly at the permitted
    dominance ceiling).

    Design: Corner/validations/cert_volume_exhausted_rejected
    """
    supplier = create_supplier(name="Vol Co")
    cert = create_certificate(supplier["id"], cert_type="ORGANIC",
                              total_volume_kg=30.0)
    lot1 = create_released_lot(supplier["id"], leaf_type="GREEN",
                               harvest_date="2026-02-01", weight_kg=35.0)
    lot2 = create_released_lot(supplier["id"], leaf_type="GREEN",
                               harvest_date="2026-02-02", weight_kg=15.0)
    recipe = create_active_recipe(
        name="RV", certification_target="ORGANIC", pack_format="LOOSE_PACK",
        components=[single_component("GREEN", "C", 100.0)])
    batch = create_qc_batch(recipe, 50.0,
                            [(lot1["id"], 35.0), (lot2["id"], 15.0)],
                            measured_moisture_pct=5.0)

    res = api.release_batch(batch["id"], TEST_USERS["qa_manager_headers"])
    validate_error(res, ApiErrorId.ERR_CERT_VOLUME_EXHAUSTED)
    assert get_batch(batch["id"])["status"] == "QC_REVIEW"
    assert get_certificate(cert["id"])["consumed_volume_kg"] == 0.0, (
        "a rejected release consumes nothing")


def test_certificate_expiry_on_clock_sweep(api):
    """PRD §2.5: "Setting the clock also triggers a certificate expiry
    sweep: every certificate grant whose `valid_until` date is earlier
    than the new current date — whether currently `ACTIVE` or
    `SUSPENDED` — transitions to `EXPIRED`."
    PRD §2.5: "Before any such call, the clock reads exactly
    `2026-08-01T00:00:00Z`, and the server must never fall back to
    wall-clock time."

    Design: Corner/state_machines/certificate_expiry_on_clock_sweep
    """
    supplier = create_supplier(name="Exp Co")
    cert = create_certificate(supplier["id"], cert_type="ORGANIC",
                              total_volume_kg=100.0, valid_from="2026-01-01",
                              valid_until="2026-08-10")
    assert cert["status"] == "ACTIVE", (
        "created under the default clock 2026-08-01, inside the window")

    set_clock("2026-08-11T00:00:00Z")
    after = get_certificate(cert["id"])
    assert after["status"] == "EXPIRED"


def test_certificate_suspend_reinstate_cycle(api):
    """PRD §3.6: "Suspending a grant — available from `ACTIVE` — moves it
    to `SUSPENDED`"
    PRD §3.6: "Reinstatement returns a `SUSPENDED` grant to `ACTIVE`, but
    only while the grant's `valid_until` is on or after the current
    logical-clock date"
    PRD §2.4: "`version` (integer): a system-managed counter that
    increments by one on every mutation"

    Design: Corner/state_machines/certificate_suspend_reinstate_cycle
    """
    supplier = create_supplier(name="Cycle Co")
    cert = create_certificate(supplier["id"], cert_type="FAIR_TRADE",
                              total_volume_kg=100.0)
    v1 = cert["version"]

    suspended = validate_success(api.suspend_certificate(cert["id"], CO), 200)
    assert suspended["status"] == "SUSPENDED"
    assert suspended["version"] == v1 + 1

    reinstated = validate_success(
        api.reinstate_certificate(cert["id"], CO), 200)
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["version"] == v1 + 2


def _organic_volume_scenario(cert_volume_kg=1000.0):
    """Supplier with ORGANIC grant; GREEN lots 35.0 + 15.0 kg RELEASED;
    ORGANIC LOOSE_PACK recipe; batch target 50.0 allocated 35.0 + 15.0
    (70% single-lot share, exactly at the permitted ceiling), blended at
    5.0 and in QC_REVIEW."""
    supplier = create_supplier(name="Volume Co", origin_region="Idukki")
    cert = create_certificate(supplier["id"], cert_type="ORGANIC",
                              total_volume_kg=cert_volume_kg)
    lot1 = create_released_lot(supplier["id"], leaf_type="GREEN",
                               harvest_date="2026-02-01", weight_kg=35.0)
    lot2 = create_released_lot(supplier["id"], leaf_type="GREEN",
                               harvest_date="2026-02-02", weight_kg=15.0)
    recipe = create_active_recipe(
        name="R16", certification_target="ORGANIC", pack_format="LOOSE_PACK",
        components=[single_component("GREEN", "C", 100.0)])
    batch = create_qc_batch(recipe, 50.0,
                            [(lot1["id"], 35.0), (lot2["id"], 15.0)],
                            measured_moisture_pct=5.0)
    return supplier, cert, recipe, batch


class TestCertificateVolumeConservation:
    def test_release_charges_then_recall_restores_exactly(self, api):
        """PRD §3.6: "On a batch's first release, the batch's `ACTIVE`
        allocations are grouped by their lots' `supplier_id`; for each
        supplier, the drawn kilograms are summed into a `charged_kg`
        figure that is added to the `consumed_volume_kg` of that
        supplier's single `ACTIVE` grant of the matching `cert_type`"
        PRD §3.6: "Recall is the exact inverse: each recorded charge is
        subtracted back from its grant's `consumed_volume_kg`, and the
        batch's `cert_charges` are emptied."
        PRD §3.6: "Both legs carry three-decimal precision, so charge and
        restore cancel exactly, with no drift."

        Release consumes 50.0 kg; recall returns exactly 50.0 kg.

        Design: Difficulty/compensating_invariant/certificate_volume_conservation_on_recall
        """
        _, cert, _, batch = _organic_volume_scenario()
        released = release_batch(batch["id"])
        assert released["status"] == "RELEASED"
        assert get_certificate(cert["id"])["consumed_volume_kg"] == 50.0

        recalled = validate_success(
            api.recall_batch(batch["id"], TEST_USERS["qa_manager_headers"]),
            200)
        assert recalled["status"] == "RECALLED"
        assert get_certificate(cert["id"])["consumed_volume_kg"] == 0.0, (
            "charge and restore are exact inverses")

    def test_cert_charges_recorded_then_emptied(self, api):
        """PRD §3.6: "the pairing of `certificate_id` and `charged_kg` is
        recorded in the batch's `cert_charges`."
        PRD §3.5: "a `RELEASED` batch moves to `RECALLED`, every charge
        recorded in its `cert_charges` is returned to the corresponding
        grant and the `cert_charges` ledger is cleared"

        Design: Difficulty/compensating_invariant/certificate_volume_conservation_on_recall
        """
        _, cert, _, batch = _organic_volume_scenario()
        released = release_batch(batch["id"])
        assert released["cert_charges"] == [
            {"certificate_id": cert["id"], "charged_kg": 50.0}]

        recalled = validate_success(
            api.recall_batch(batch["id"], TEST_USERS["qa_manager_headers"]),
            200)
        assert recalled["status"] == "RECALLED"
        assert recalled["cert_charges"] == [], "ledger cleared on recall"


class TestCertificateSuspendCascade:
    def test_depth2_cascade_holds_batches_and_cancels_runs(self, api):
        """PRD §3.6: "Suspending a grant — available from `ACTIVE` —
        moves it to `SUSPENDED` and fires its own variant of the §2.8
        cascade, entering at link 2: every batch whose recipe's
        `certification_target` equals the grant's `cert_type`, which
        holds an `ACTIVE` allocation from a lot of the grant's supplier,
        and which sits in `RECIPE_LOCKED`, `ALLOCATED`, `BLENDED`,
        `FLAVORED`, `QC_REVIEW`, or `RELEASED`, moves to `ON_HOLD`, and
        every still-`SCHEDULED` run referencing such a batch is
        cancelled."

        B1 (RELEASED, with a SCHEDULED run) and B2 (QC_REVIEW) both draw
        from the suspended grant's supplier under an ORGANIC recipe.

        Design: Difficulty/transitive_cascade/certificate_suspend_depth2_cascade
        """
        supplier = create_supplier(name="Organic Co", origin_region="Munnar")
        cert = create_certificate(supplier["id"], cert_type="ORGANIC",
                                  total_volume_kg=10000.0)
        lot_a = create_released_lot(supplier["id"], leaf_type="GREEN",
                                    harvest_date="2026-02-01",
                                    weight_kg=35.0)
        lot_b = create_released_lot(supplier["id"], leaf_type="GREEN",
                                    harvest_date="2026-02-02",
                                    weight_kg=15.0)
        lot_c = create_released_lot(supplier["id"], leaf_type="GREEN",
                                    harvest_date="2026-02-03",
                                    weight_kg=20.0)
        recipe = create_active_recipe(
            name="R8", certification_target="ORGANIC",
            pack_format="LOOSE_PACK",
            components=[single_component("GREEN", "C", 100.0)])

        batch1 = create_batch(recipe["id"], 50.0)
        lock_recipe(batch1["id"])
        allocate(batch1["id"], lot_a["id"], 35.0)
        allocate(batch1["id"], lot_b["id"], 15.0)
        finalize_allocation(batch1["id"])
        blend_batch(batch1["id"], measured_moisture_pct=5.0)
        submit_qc(batch1["id"])
        release_batch(batch1["id"])
        line = create_packaging_line(name="LP-9", line_type="LOOSE_PACK")
        run = create_run(line["id"], batch1["id"], "2026-08-05T08:00:00Z",
                         "2026-08-05T10:00:00Z", 2000)

        batch2 = create_qc_batch(recipe, 20.0, [(lot_c["id"], 20.0)],
                                 measured_moisture_pct=5.0)

        suspended = validate_success(
            api.suspend_certificate(cert["id"], CO), 200)
        assert suspended["status"] == "SUSPENDED"

        assert get_batch(batch1["id"])["status"] == "ON_HOLD", (
            "link 1 holds the RELEASED batch")
        assert get_batch(batch2["id"])["status"] == "ON_HOLD", (
            "link 1 holds the QC_REVIEW batch")
        run_after = validate_success(
            api.get_run(run["id"], TEST_USERS["production_planner_headers"]),
            200)
        assert run_after["status"] == "CANCELLED", (
            "link 2 cancels the SCHEDULED run")

    def test_cascade_selectivity_by_certification_target(self, api):
        """PRD §3.6: "every batch whose recipe's `certification_target`
        equals the grant's `cert_type`, which holds an `ACTIVE`
        allocation from a lot of the grant's supplier, and which sits in
        `RECIPE_LOCKED`, `ALLOCATED`, `BLENDED`, `FLAVORED`, `QC_REVIEW`,
        or `RELEASED`, moves to `ON_HOLD`"

        A CONVENTIONAL batch drawing from the same supplier is outside
        the selection rule and stays in QC_REVIEW.

        Design: Difficulty/transitive_cascade/certificate_suspend_depth2_cascade
        """
        supplier = create_supplier(name="Selective Co")
        cert = create_certificate(supplier["id"], cert_type="ORGANIC",
                                  total_volume_kg=10000.0)
        lot = create_released_lot(supplier["id"], leaf_type="GREEN",
                                  weight_kg=50.0)
        organic_recipe = create_active_recipe(
            name="ROrg", certification_target="ORGANIC",
            pack_format="LOOSE_PACK",
            components=[single_component("GREEN", "C", 100.0)])
        conventional_recipe = create_active_recipe(
            name="RConv", certification_target="CONVENTIONAL",
            pack_format="LOOSE_PACK",
            components=[single_component("GREEN", "C", 100.0)])

        organic_batch = create_qc_batch(
            organic_recipe, 20.0, [(lot["id"], 20.0)],
            measured_moisture_pct=5.0)
        conventional_batch = create_qc_batch(
            conventional_recipe, 20.0, [(lot["id"], 20.0)],
            measured_moisture_pct=5.0)

        validate_success(api.suspend_certificate(cert["id"], CO), 200)

        assert get_batch(organic_batch["id"])["status"] == "ON_HOLD"
        assert get_batch(conventional_batch["id"])["status"] == "QC_REVIEW", (
            "CONVENTIONAL batch is untouched by an ORGANIC cert suspension")
