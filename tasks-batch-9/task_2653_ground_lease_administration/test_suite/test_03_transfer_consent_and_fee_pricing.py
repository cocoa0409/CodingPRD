"""Assignment and sublease consent: the five pinned fee-pricing steps, the
flat-by-tier assignment scale, the minimum fee floor, the pre-surcharge base
total that selects the late-surcharge tier, and the two differently keyed
sublease guards."""

from test_helpers import (
    ERR_SUBLET_AREA_EXCEEDED,
    assert_fields,
    assert_transfer_fee_conserved,
    factories as f,
    fixtures as fx,
    make_asset_manager_headers,
    make_ground_tenant_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

LATE_TERM = {"term_start": "2026-01-01T00:00:00Z",
             "term_end": "2031-01-01T00:00:00Z"}


def _two_late_subleases(api):
    """UNIT-D at 2001218 and UNIT-E at 2001222, both applied for after their term
    had already begun, so both carry the late surcharge."""
    env = fx.standard_lease(api, "PIER-44")
    tenant = make_ground_tenant_headers(env["lessee_id"])
    unit_d = validate_success(
        api.create_transfer(
            f.sublease_payload(env["lease_id"], "UNIT-D", 2001218,
                               sublet_area_sqft=1000,
                               transferee_legal_name="Dockside Cinema LLC",
                               **LATE_TERM),
            tenant,
        ),
        expected_status=201,
    )
    unit_e = validate_success(
        api.create_transfer(
            f.sublease_payload(env["lease_id"], "UNIT-E", 2001222,
                               sublet_area_sqft=1000,
                               transferee_legal_name="Dockside Cinema Annex LLC",
                               **LATE_TERM),
            tenant,
        ),
        expected_status=201,
    )
    assert unit_d["submitted_late"] is True
    assert unit_e["submitted_late"] is True
    return env, unit_d, unit_e


def test_the_surcharge_tier_is_selected_on_the_base_total_not_on_the_gross_fee(api):
    """PRD §3.6: "Where it is true, the surcharge rate tier is selected on the **base total from step three, which excludes the surcharge itself** — this is the pinned resolution of what would otherwise be a circular dependency, since the surcharge is a percentage of an amount it would otherwise form part of."

    Design: Difficulty/combinatorial_formula/transfer_fee_surcharge_tier_pinned_on_pre_surcharge_base_total
    """
    _env, unit_d, _unit_e = _two_late_subleases(api)

    granted = validate_success(
        api.decide_transfer(unit_d["id"], f.decision_payload("APPROVE"),
                            make_asset_manager_headers("am-1"))
    )
    # base total 975609 + 24390 == 999999, at or below 1000000 -> 250 bps.
    assert_fields(
        granted,
        status="CONSENT_GRANTED",
        allocable_base_rent_cents=50000,
        transfer_fee_gross_cents=975609,
        admin_charge_cents=24390,
        late_surcharge_cents=25000,
        total_transfer_fee_cents=1024999,
        transfer_fee_paid_cents=0,
    )
    assert_transfer_fee_conserved(granted)


def test_four_cents_of_extra_sublease_rent_crosses_the_surcharge_tier_ceiling(api):
    """PRD §3.6: "The rate is 250 basis points where the base total is at most 1,000,000 cents ($10,000) and 500 basis points above that."

    Design: Difficulty/combinatorial_formula/transfer_fee_surcharge_tier_pinned_on_pre_surcharge_base_total
    """
    _env, unit_d, unit_e = _two_late_subleases(api)
    manager = make_asset_manager_headers("am-1")

    low = validate_success(
        api.decide_transfer(unit_d["id"], f.decision_payload("APPROVE"), manager)
    )
    high = validate_success(
        api.decide_transfer(unit_e["id"], f.decision_payload("APPROVE"), manager)
    )
    # base total 975611 + 24390 == 1000001, strictly above the ceiling -> 500 bps.
    assert_fields(
        high,
        allocable_base_rent_cents=50000,
        transfer_fee_gross_cents=975611,
        admin_charge_cents=24390,
        late_surcharge_cents=50000,
        total_transfer_fee_cents=1050001,
    )
    assert_transfer_fee_conserved(high)
    assert high["late_surcharge_cents"] == 2 * low["late_surcharge_cents"]
    assert high["total_transfer_fee_cents"] - low["total_transfer_fee_cents"] == 25002


ASSIGNEE = {
    "legal_name": "Seawall Fund II LLC",
    "notice_email": "asset@seawall.example",
    "credit_rating_code": "BBB",
}


def _four_assignments(api):
    """Four assignment applications on one lease at 49999999, 50000000, 50000001
    and 1000000 cents of consideration, none of them late."""
    env = fx.standard_lease(api, "PIER-55")
    assignee = fx.create_lessee(api, **ASSIGNEE)
    tenant = make_ground_tenant_headers(env["lessee_id"])
    rows = {}
    for label, consideration in (
        ("below", 49999999), ("at", 50000000),
        ("above", 50000001), ("floor", 1000000),
    ):
        rows[label] = validate_success(
            api.create_transfer(
                f.assignment_payload(env["lease_id"], assignee["id"], consideration,
                                     transferee_legal_name=ASSIGNEE["legal_name"]),
                tenant,
            ),
            expected_status=201,
        )
        assert rows[label]["submitted_late"] is False
    return env, assignee, rows


def test_the_first_assignment_tier_ceiling_is_inclusive(api):
    """PRD §3.6: "For an `ASSIGNMENT`, select the rate tier from `net_consideration_cents`: 300 basis points where the consideration is at most 50,000,000 cents ($500,000), 500 basis points where it is above that but at most 200,000,000 cents ($2,000,000), and 700 basis points above that."

    Design: Difficulty/boundary_precision_check/assignment_tier_boundary_at_below_above_and_the_minimum_fee_floor
    """
    _env, _assignee, rows = _four_assignments(api)
    manager = make_asset_manager_headers("am-1")

    below = validate_success(
        api.decide_transfer(rows["below"]["id"], f.decision_payload("APPROVE"),
                            manager)
    )
    assert_fields(
        below,
        status="CONSENT_GRANTED",
        transfer_fee_gross_cents=1500000,
        admin_charge_cents=37500,
        late_surcharge_cents=0,
        total_transfer_fee_cents=1537500,
    )
    assert below["allocable_base_rent_cents"] is None

    at_ceiling = validate_success(
        api.decide_transfer(rows["at"]["id"], f.decision_payload("APPROVE"),
                            manager)
    )
    assert_fields(at_ceiling, transfer_fee_gross_cents=1500000,
                  total_transfer_fee_cents=1537500)
    assert at_ceiling["allocable_base_rent_cents"] is None


def test_one_cent_above_the_ceiling_is_charged_the_higher_rate_on_every_cent(api):
    """PRD §3.6: "The selected rate applies to the **whole** consideration — this is a flat-by-tier scale, not a marginal one, so a consideration one cent above a ceiling is charged the higher rate on every cent of it."

    Design: Difficulty/boundary_precision_check/assignment_tier_boundary_at_below_above_and_the_minimum_fee_floor
    """
    _env, _assignee, rows = _four_assignments(api)
    manager = make_asset_manager_headers("am-1")

    at_ceiling = validate_success(
        api.decide_transfer(rows["at"]["id"], f.decision_payload("APPROVE"),
                            manager)
    )
    above = validate_success(
        api.decide_transfer(rows["above"]["id"], f.decision_payload("APPROVE"),
                            manager)
    )
    assert_fields(
        above,
        transfer_fee_gross_cents=2500000,
        admin_charge_cents=62500,
        total_transfer_fee_cents=2562500,
    )
    assert_transfer_fee_conserved(above)
    delta = above["total_transfer_fee_cents"] - at_ceiling["total_transfer_fee_cents"]
    assert delta == 1025000


def test_the_minimum_assignment_fee_floors_a_small_consideration(api):
    """PRD §3.6: "Multiply the consideration by the selected rate, divide by 10,000, round half up to whole cents, and then take whichever is larger of that figure and the minimum assignment fee of 500,000 cents ($5,000)."

    Design: Difficulty/boundary_precision_check/assignment_tier_boundary_at_below_above_and_the_minimum_fee_floor
    """
    env, _assignee, rows = _four_assignments(api)

    floored = validate_success(
        api.decide_transfer(rows["floor"]["id"], f.decision_payload("APPROVE"),
                            make_asset_manager_headers("am-1"))
    )
    # 1000000 x 300 bps == 30000, lifted to the 500000 floor.
    assert_fields(
        floored,
        transfer_fee_gross_cents=500000,
        admin_charge_cents=12500,
        late_surcharge_cents=0,
        total_transfer_fee_cents=512500,
    )
    assert_transfer_fee_conserved(floored)
    # Nothing was paid, so no assignment activated and the tenant of record stands.
    assert fx.read_lease(api, env["lease_id"])["lessee_id"] == env["lessee_id"]


def _lease_with_one_active_unit_a_sublease(api):
    """UNIT-A let from 2027-01-01 to 2030-01-01 over 150000 of the 200000 sqft
    envelope, carried all the way to ACTIVE."""
    env = fx.standard_lease(api, "PIER-62")
    tenant = make_ground_tenant_headers(env["lessee_id"])
    created = validate_success(
        api.create_transfer(
            f.sublease_payload(env["lease_id"], "UNIT-A", 12000000,
                               sublet_area_sqft=150000,
                               term_start="2027-01-01T00:00:00Z",
                               term_end="2030-01-01T00:00:00Z",
                               transferee_legal_name="Wavelength Grocers LLC",
                               transferee_credit_rating_code="A"),
            tenant,
        ),
        expected_status=201,
    )
    validate_success(
        api.decide_transfer(created["id"], f.decision_payload("APPROVE"),
                            make_asset_manager_headers("am-1"))
    )
    active = validate_success(
        api.pay_transfer_fee(created["id"], f.fee_payment_payload(2306250), tenant)
    )
    return env, active


def test_a_sublease_term_that_only_touches_the_active_term_of_the_same_unit(api):
    """PRD §2.9: "Sublease occupancy is checked the same way: a sublease term runs from `term_start` up to `term_end` for overlap purposes, touching endpoints are allowed, and two sublease terms on the same lease and the same `premises_unit_code` may not intersect."

    Design: Difficulty/resource_temporal_overlap/sublease_overlap_is_keyed_by_unit_while_the_area_cap_is_keyed_by_lease
    """
    env, active = _lease_with_one_active_unit_a_sublease(api)
    assert_fields(
        active,
        status="ACTIVE",
        allocable_base_rent_cents=7500000,
        transfer_fee_gross_cents=2250000,
        admin_charge_cents=56250,
        late_surcharge_cents=0,
        total_transfer_fee_cents=2306250,
        transfer_fee_paid_cents=2306250,
    )
    assert_transfer_fee_conserved(active)
    lease = fx.read_lease(api, env["lease_id"])
    assert lease["percentage_rent_sublease_base_cents"] == 6000000

    # [2030-01-01, 2033-01-01) starts exactly where the active term ends.
    successor = validate_success(
        api.create_transfer(
            f.sublease_payload(env["lease_id"], "UNIT-A", 5000000,
                               sublet_area_sqft=60000,
                               term_start="2030-01-01T00:00:00Z",
                               term_end="2033-01-01T00:00:00Z",
                               transferee_legal_name="Tidewater Pharmacy LLC"),
            make_ground_tenant_headers(env["lessee_id"]),
        ),
        expected_status=201,
    )
    assert successor["status"] == "SUBMITTED"


def test_the_sublet_area_cap_aggregates_across_the_whole_lease(api):
    """PRD §3.6: "One aggregate check also applies: summing `sublet_area_sqft` across the lease's subleases in `ACTIVE` and `CONSENT_GRANTED`, including the one under decision, may not exceed the lease's `total_permitted_gfa_sqft`, and a breach is refused with `ERR_SUBLET_AREA_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/sublease_overlap_is_keyed_by_unit_while_the_area_cap_is_keyed_by_lease
    """
    env, _active = _lease_with_one_active_unit_a_sublease(api)
    tenant = make_ground_tenant_headers(env["lessee_id"])
    successor = validate_success(
        api.create_transfer(
            f.sublease_payload(env["lease_id"], "UNIT-A", 5000000,
                               sublet_area_sqft=60000,
                               term_start="2030-01-01T00:00:00Z",
                               term_end="2033-01-01T00:00:00Z",
                               transferee_legal_name="Tidewater Pharmacy LLC"),
            tenant,
        ),
        expected_status=201,
    )

    # 150000 already active plus 60000 under decision is 210000 against a 200000
    # envelope, even though the two terms never intersect.
    validate_error(
        api.decide_transfer(successor["id"], f.decision_payload("APPROVE"),
                            make_asset_manager_headers("am-1")),
        ERR_SUBLET_AREA_EXCEEDED,
        expected_status=409,
    )
    refused = validate_success(api.get_transfer(successor["id"], tenant))
    assert refused["status"] == "SUBMITTED"
    assert refused["total_transfer_fee_cents"] is None
    assert refused["transfer_fee_gross_cents"] is None


def test_a_different_unit_takes_the_same_overlapping_term_up_to_the_cap(api):
    """PRD §3.6: "For a `SUBLEASE`, first apportion base rent to the sublet area: multiply the lease's `current_annual_base_rent_cents` by `sublet_area_sqft`, divide by the lease's `total_permitted_gfa_sqft`, round half up to whole cents, and store that as `allocable_base_rent_cents`."

    Design: Difficulty/resource_temporal_overlap/sublease_overlap_is_keyed_by_unit_while_the_area_cap_is_keyed_by_lease
    """
    env, _active = _lease_with_one_active_unit_a_sublease(api)
    tenant = make_ground_tenant_headers(env["lessee_id"])

    # The same 2029-06-01 to 2032-01-01 term that would collide on UNIT-A.
    other_unit = validate_success(
        api.create_transfer(
            f.sublease_payload(env["lease_id"], "UNIT-B", 4000000,
                               sublet_area_sqft=50000,
                               term_start="2029-06-01T00:00:00Z",
                               term_end="2032-01-01T00:00:00Z",
                               transferee_legal_name="Northline Cafe Group LLC"),
            tenant,
        ),
        expected_status=201,
    )

    # 150000 + 50000 lands exactly on the 200000 cap, which is a pass.
    granted = validate_success(
        api.decide_transfer(other_unit["id"], f.decision_payload("APPROVE"),
                            make_asset_manager_headers("am-1"))
    )
    assert_fields(
        granted,
        status="CONSENT_GRANTED",
        allocable_base_rent_cents=2500000,
        transfer_fee_gross_cents=750000,
        admin_charge_cents=18750,
        total_transfer_fee_cents=768750,
        transfer_fee_paid_cents=0,
    )
    lease = fx.read_lease(api, env["lease_id"])
    assert lease["percentage_rent_sublease_base_cents"] == 6000000

    rows, meta = validate_paginated(
        api.list_transfers(tenant, {"lease_id": env["lease_id"]})
    )
    assert meta["total_count"] == 2
    assert sorted(row["status"] for row in rows) == ["ACTIVE", "CONSENT_GRANTED"]
