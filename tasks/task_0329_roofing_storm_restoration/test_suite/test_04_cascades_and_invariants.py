"""Transitive cascades (change-order apply depth-3; warranty-activate depth-2)
and compensating / conservation invariants on the Job ledger.

Queue A: transitive_cascade, compensating_invariant.
"""
from test_helpers import (
    validate_success, get_success_data, TEST_USERS,
    setup_contracted_job, setup_in_production_job, setup_in_production_with_draw,
    setup_approved_change_order, current_job_version, disburse_draw,
    create_material_order_payload, apply_change_order_payload,
    create_change_order_payload, create_warranty_payload,
    assert_job_ledger_conserved,
)

PM = TEST_USERS["production_manager_headers"]
FA = TEST_USERS["field_adjuster_headers"]

SHINGLE_10 = [{"trade": "SHINGLE", "squares": 10, "unit_price_cents": 10000, "waste_factor_pct": 0.10}]


class TestChangeOrderApplyCascade:
    def test_apply_cascades_contract_remaining_and_material_resize(self, api):
        """PRD §3.8: "Third, when `extra_shingle_squares` is greater than 0, the
        job's bound-estimate effective shingle squares grow by that amount, and
        any material order for the job still in `ORDERED` status is re-sized —
        its `bundles`, `total_weight_lbs`, and `freight_cents` recomputed by the
        sizing rule of §3.4, which now folds the applied extra squares into the
        effective shingle total."

        Design: Difficulty/transitive_cascade/change_order_apply_cascade_depth3
        """
        job_id, _ = setup_contracted_job(line_items=SHINGLE_10)  # contract 110000
        mo = get_success_data(api.create_material_order(
            create_material_order_payload(job_id=job_id), PM))
        assert mo["bundles"] == 35  # ceil(10*1.15*3)=35
        co = setup_approved_change_order(job_id, delta_cents=60_000, extra_shingle_squares=20)
        jv = current_job_version(job_id)
        applied = validate_success(api.apply_change_order(
            co["id"], apply_change_order_payload(expected_job_version=jv), PM))
        assert applied["status"] == "APPLIED"
        mo_resized = get_success_data(api.get_material_order(mo["id"], PM))
        # effective squares 10 + 20 = 30 -> ceil(30*1.15*3) = 104, weight 8320.
        assert mo_resized["bundles"] == 104
        assert mo_resized["total_weight_lbs"] == 8320

    def test_apply_raises_contract_value_and_rederives_remaining(self, api):
        """PRD §3.8: "First, the job's `contract_value_cents` increases by the
        `delta_cents` (the signed amount, so a negative delta reduces it).
        Second, the job's `remaining_billable_cents` is re-derived from the new
        contract value as `contract_value_cents` minus `disbursed_gross_cents`."

        Design: Difficulty/transitive_cascade/change_order_apply_cascade_depth3
        """
        job_id, _ = setup_contracted_job(line_items=SHINGLE_10)  # contract 110000
        get_success_data(api.create_material_order(
            create_material_order_payload(job_id=job_id), PM))
        co = setup_approved_change_order(job_id, delta_cents=60_000, extra_shingle_squares=20)
        jv = current_job_version(job_id)
        validate_success(api.apply_change_order(
            co["id"], apply_change_order_payload(expected_job_version=jv), PM))
        job = get_success_data(api.get_job(job_id, PM))
        assert job["contract_value_cents"] == 170000
        # Nothing disbursed yet, so remaining == contract.
        assert job["remaining_billable_cents"] == 170000


class TestWarrantyActivateCascade:
    def test_activate_releases_retainage_into_disbursed_net(self, api):
        """PRD §3.10: "Activation also triggers the retainage release: the job's
        `retainage_held_cents` is reset to 0 (released to the homeowner) and that
        released amount is added to the job's `disbursed_net_cents`, reflecting
        that the previously withheld funds are now paid out."

        Design: Difficulty/transitive_cascade/warranty_activate_cascade_depth2
        """
        # Bill to 100% via a 50% progress draw (retainage 5500) then a final draw.
        job_id, info = setup_in_production_with_draw(cumulative_pct=0.5, line_items=SHINGLE_10)
        disburse_draw(job_id, 1.0, info["job_version"])
        # Complete the job (final inspection then complete).
        from test_helpers import create_inspection_payload, complete_inspection_payload
        pf = get_success_data(api.create_inspection(create_inspection_payload(
            job_id=job_id, kind="PERMIT_FINAL", permit_id=info["permit"]["id"],
            scheduled_start="2026-07-10T08:00:00Z", scheduled_end="2026-07-10T12:00:00Z"), FA))
        api.complete_inspection(pf["id"], complete_inspection_payload(outcome="PASS"), FA)
        validate_success(api.complete_job(job_id, PM))
        war = get_success_data(api.create_warranty(create_warranty_payload(
            job_id=job_id, premium_cents=50_000, term_months=120), PM))
        activated = validate_success(api.activate_warranty(war["id"], PM))
        assert activated["status"] == "ACTIVE"
        job = get_success_data(api.get_job(job_id, PM))
        assert job["retainage_held_cents"] == 0
        assert job["disbursed_net_cents"] == 110000

    def test_activate_moves_warranty_pending_to_active(self, api):
        """PRD §3.10: "Activating a warranty moves it from `PENDING` to `ACTIVE`
        and stamps `start_at` to the current logical clock."

        Design: Difficulty/transitive_cascade/warranty_activate_cascade_depth2
        """
        # The first cascade hop (the warranty's own PENDING -> ACTIVE transition)
        # is what triggers the second hop (the retainage release on the job).
        job_id, info = setup_in_production_with_draw(cumulative_pct=0.5, line_items=SHINGLE_10)
        disburse_draw(job_id, 1.0, info["job_version"])
        from test_helpers import create_inspection_payload, complete_inspection_payload
        pf = get_success_data(api.create_inspection(create_inspection_payload(
            job_id=job_id, kind="PERMIT_FINAL", permit_id=info["permit"]["id"],
            scheduled_start="2026-07-10T08:00:00Z", scheduled_end="2026-07-10T12:00:00Z"), FA))
        api.complete_inspection(pf["id"], complete_inspection_payload(outcome="PASS"), FA)
        validate_success(api.complete_job(job_id, PM))
        war = get_success_data(api.create_warranty(create_warranty_payload(
            job_id=job_id, premium_cents=50_000, term_months=120), PM))
        assert war["status"] == "PENDING"
        activated = validate_success(api.activate_warranty(war["id"], PM))
        assert activated["status"] == "ACTIVE"
        assert activated["start_at"]


class TestLedgerConservation:
    def test_apply_then_void_unapplied_conserves_contract_value(self, api):
        """PRD §3.8: "A still-`PROPOSED` or `APPROVED` change order may instead
        be voided by a `ProductionManager`, moving it to the terminal `VOIDED`;
        voiding has no precondition beyond the source state."

        Design: Difficulty/compensating_invariant/change_order_apply_then_void_contract_conserved
        """
        job_id, _ = setup_contracted_job(line_items=SHINGLE_10)  # contract 110000
        co_a = setup_approved_change_order(job_id, delta_cents=50_000)
        jv = current_job_version(job_id)
        validate_success(api.apply_change_order(
            co_a["id"], apply_change_order_payload(expected_job_version=jv), PM))
        co_b = setup_approved_change_order(job_id, delta_cents=30_000)
        validate_success(api.void_change_order(co_b["id"], PM))
        job = get_success_data(api.get_job(job_id, PM))
        # CO-A applied (+50000) -> 160000; CO-B voided leaves it untouched.
        assert job["contract_value_cents"] == 160000
        assert job["remaining_billable_cents"] == 160000

    def test_voiding_unapplied_order_terminates_it_without_ledger_effect(self, api):
        """PRD §3.8: "Applying an approved change order — moving it from
        `APPROVED` to the terminal `APPLIED` — is the consequential step."

        Design: Difficulty/compensating_invariant/change_order_apply_then_void_contract_conserved
        """
        # Only the APPLIED order moves the ledger; the VOIDED order is terminal
        # and leaves contract value at the post-apply figure (160000).
        job_id, _ = setup_contracted_job(line_items=SHINGLE_10)  # contract 110000
        co_a = setup_approved_change_order(job_id, delta_cents=50_000)
        jv = current_job_version(job_id)
        validate_success(api.apply_change_order(
            co_a["id"], apply_change_order_payload(expected_job_version=jv), PM))
        co_b = setup_approved_change_order(job_id, delta_cents=30_000)
        voided = validate_success(api.void_change_order(co_b["id"], PM))
        assert voided["status"] == "VOIDED"
        job = get_success_data(api.get_job(job_id, PM))
        assert job["contract_value_cents"] == 160000

    def test_draw_disbursement_conserves_gross_plus_remaining(self, api):
        """PRD §2.6: "The field `remaining_billable_cents` is always
        `contract_value_cents` minus `disbursed_gross_cents` and is never
        negative; together with `disbursed_gross_cents` it conserves exactly to
        `contract_value_cents`."

        Design: Difficulty/compensating_invariant/draw_ledger_gross_plus_remaining_conserved
        """
        job_id, info = setup_in_production_job(line_items=SHINGLE_10)  # contract 110000
        draw = disburse_draw(job_id, 0.4, info["job_version"])
        assert draw["gross_eligible_cents"] == 44000
        job = get_success_data(api.get_job(job_id, PM))
        assert job["disbursed_gross_cents"] == 44000
        assert job["remaining_billable_cents"] == 66000
        assert job["disbursed_gross_cents"] + job["remaining_billable_cents"] == 110000
        assert_job_ledger_conserved(job)

    def test_conservation_holds_after_two_sequential_draws(self, api):
        """PRD §2.6: "The field `remaining_billable_cents` is always
        `contract_value_cents` minus `disbursed_gross_cents` and is never
        negative; together with `disbursed_gross_cents` it conserves exactly to
        `contract_value_cents`."

        Design: Difficulty/compensating_invariant/draw_ledger_gross_plus_remaining_conserved
        """
        job_id, info = setup_in_production_job(line_items=SHINGLE_10)  # contract 110000
        disburse_draw(job_id, 0.4, info["job_version"])
        jv2 = current_job_version(job_id)
        disburse_draw(job_id, 0.7, jv2)  # cumulative 0.7 -> gross-to-date 77000
        job = get_success_data(api.get_job(job_id, PM))
        assert job["disbursed_gross_cents"] == 77000
        assert job["remaining_billable_cents"] == 33000
        assert job["disbursed_gross_cents"] + job["remaining_billable_cents"] == 110000
        assert_job_ledger_conserved(job)
