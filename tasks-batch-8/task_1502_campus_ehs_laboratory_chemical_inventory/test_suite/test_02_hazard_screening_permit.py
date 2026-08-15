"""Hazard totals (physical vs regulatory variants) and permit-threshold screening."""
import pytest

from test_helpers import (
    TEST_USERS,
    create_area,
    create_container,
    create_lab_with_pi,
    create_lab_with_trained_pi,
    get_container,
    get_lab,
    list_lab_areas,
    make_pi_headers,
    setup_scheduled_pickup,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def test_physical_and_regulatory_totals_diverge_after_tagging(api):
    """PRD §2.7: "The physical total for a class, exposed in `hazard_totals_physical`,
    sums `quantity_value` over the lab's containers in state `IN_USE` only — a
    container that has been tagged as waste but not yet picked up drops out of this
    total. The regulatory total, exposed in `hazard_totals_regulatory`, sums
    `quantity_value` over containers in state `IN_USE` or `WASTE_TAGGED`, so the
    identical container data yields a total at least as large."
    PRD §2.7: "The lab's `permit_report_required` is true whenever at least one class
    is flagged." (FLAMMABLE threshold: "10.0 for `FLAMMABLE`")

    Design: Difficulty/dual_variant_calc/hazard_screening_physical_vs_regulatory_counts
    """
    lab, pi = create_lab_with_trained_pi("FLAMMABLE", name="Chem A", room="101")
    headers = make_pi_headers(pi["id"])
    create_container(lab["id"], headers, barcode="BC-001", quantity_value=6.0)
    c2 = create_container(lab["id"], headers, barcode="BC-002", chemical_name="Methanol",
                          quantity_value=5.0)
    area = create_area(lab["id"], capacity_containers=20)
    api.tag_waste(c2["id"], {"accumulation_area_id": area["id"]}, headers)

    lab_after = get_lab(lab["id"])
    physical = lab_after["hazard_totals_physical"].get("FLAMMABLE", 0.0)
    regulatory = lab_after["hazard_totals_regulatory"].get("FLAMMABLE", 0.0)
    assert physical == pytest.approx(6.0, abs=1e-6), (
        f"physical total counts IN_USE only: expected 6.0, got {physical}"
    )
    assert regulatory == pytest.approx(11.0, abs=1e-6), (
        f"regulatory total counts IN_USE + WASTE_TAGGED: expected 11.0, got {regulatory}"
    )
    assert lab_after["permit_report_required"] is True, (
        "regulatory 11.0 >= FLAMMABLE threshold 10.0 must flag the permit"
    )


def test_totals_identical_before_any_tagging(api):
    """PRD §2.7: "The physical total for a class, exposed in `hazard_totals_physical`,
    sums `quantity_value` over the lab's containers in state `IN_USE` only — a
    container that has been tagged as waste but not yet picked up drops out of this
    total. The regulatory total, exposed in `hazard_totals_regulatory`, sums
    `quantity_value` over containers in state `IN_USE` or `WASTE_TAGGED`, so the
    identical container data yields a total at least as large."
    (With every container still IN_USE, the two variants coincide; tagging one
    container is exactly what drives them apart.)

    Design: Difficulty/dual_variant_calc/hazard_screening_physical_vs_regulatory_counts
    """
    lab, pi = create_lab_with_trained_pi("FLAMMABLE", name="Chem A2", room="101")
    headers = make_pi_headers(pi["id"])
    create_container(lab["id"], headers, barcode="BC-001", quantity_value=6.0)
    c2 = create_container(lab["id"], headers, barcode="BC-002", quantity_value=5.0)

    before = get_lab(lab["id"])
    assert before["hazard_totals_physical"].get("FLAMMABLE", 0.0) == pytest.approx(11.0, abs=1e-6)
    assert before["hazard_totals_regulatory"].get("FLAMMABLE", 0.0) == pytest.approx(11.0, abs=1e-6)

    area = create_area(lab["id"], capacity_containers=20)
    api.tag_waste(c2["id"], {"accumulation_area_id": area["id"]}, headers)
    after = get_lab(lab["id"])
    assert after["hazard_totals_physical"].get("FLAMMABLE", 0.0) == pytest.approx(6.0, abs=1e-6)
    assert after["hazard_totals_regulatory"].get("FLAMMABLE", 0.0) == pytest.approx(11.0, abs=1e-6)
    assert after["permit_report_required"] is True


def test_permit_not_flagged_just_below_threshold(api):
    """PRD §2.7: "A hazard class is flagged when its regulatory total is greater than
    zero and at least the class's permit threshold in gallons: 10.0 for `FLAMMABLE`,
    10.0 for `OXIDIZER`, 5.0 for `CORROSIVE`, 1.0 for `TOXIC`, and 0.0 for both
    `CONTROLLED_SUBSTANCE` and `SELECT_AGENT` — meaning any positive on-hand quantity
    of a regulated class flags it."

    Design: Difficulty/boundary_precision_check/permit_threshold_inclusive_boundary
    """
    lab, pi = create_lab_with_pi(name="Lab K1", room="112")
    create_container(lab["id"], make_pi_headers(pi["id"]), barcode="B-A", quantity_value=9.99)

    lab_after = get_lab(lab["id"])
    assert lab_after["hazard_totals_regulatory"].get("FLAMMABLE", 0.0) == pytest.approx(9.99, abs=1e-6)
    assert lab_after["permit_report_required"] is False, (
        "9.99 < FLAMMABLE threshold 10.0 must not flag the permit"
    )


def test_permit_flagged_at_exact_threshold_inclusive(api):
    """PRD §2.7: "The threshold comparison is inclusive: a regulatory total exactly
    equal to the threshold flags the class."
    PRD §2.7: "The lab's `permit_report_required` is true whenever at least one class
    is flagged."

    Design: Difficulty/boundary_precision_check/permit_threshold_inclusive_boundary
    """
    lab, pi = create_lab_with_pi(name="Lab K2", room="113")
    create_container(lab["id"], make_pi_headers(pi["id"]), barcode="B-B", quantity_value=10.0)

    lab_after = get_lab(lab["id"])
    assert lab_after["hazard_totals_regulatory"].get("FLAMMABLE", 0.0) == pytest.approx(10.0, abs=1e-6)
    assert lab_after["permit_report_required"] is True, (
        "10.0 >= FLAMMABLE threshold 10.0 (inclusive) must flag the permit"
    )


def test_pickup_completion_unflags_permit(api):
    """PRD §3.4: "Completion of a `SCHEDULED` request is the cascade point of the
    waste workflow. Every container linked to the request transitions from
    `WASTE_TAGGED` to `PICKED_UP`" and "As each container leaves the regulatory set,
    the lab's hazard totals are re-screened and `permit_report_required` may flip to
    false"
    PRD §2.7: "Containers in state `PICKED_UP` are excluded from both totals."

    Design: Difficulty/transitive_cascade/pickup_complete_cascade_unflags_permit
    """
    ctx = setup_scheduled_pickup(quantities=(5.0,), name="Chem H", room="108")
    lab, pi = ctx["lab"], ctx["pi"]
    # a second container stays IN_USE at 6.0
    create_container(lab["id"], make_pi_headers(pi["id"]), barcode="FL-A", quantity_value=6.0)

    before = get_lab(lab["id"])
    assert before["hazard_totals_regulatory"].get("FLAMMABLE", 0.0) == pytest.approx(11.0, abs=1e-6)
    assert before["permit_report_required"] is True

    completed = validate_success(api.complete_pickup_request(ctx["pickup"]["id"], ADMIN), 200)
    assert completed["status"] == "COMPLETED"

    c_after = get_container(ctx["containers"][0]["id"])
    assert c_after["state"] == "PICKED_UP"

    lab_after = get_lab(lab["id"])
    assert lab_after["hazard_totals_regulatory"].get("FLAMMABLE", 0.0) == pytest.approx(6.0, abs=1e-6)
    assert lab_after["permit_report_required"] is False


def test_picked_up_container_drops_out_of_area_count(api):
    """PRD §3.4: "each such container retains its `accumulation_area_id` for audit
    but drops out of the area's count, because the count only considers containers
    currently in `WASTE_TAGGED`, so the area counts decrease by one per collected
    container."
    PRD §2.7: "Containers in state `PICKED_UP` are excluded from both totals."

    Design: Difficulty/transitive_cascade/pickup_complete_cascade_unflags_permit
    """
    ctx = setup_scheduled_pickup(quantities=(5.0,), name="Chem H2", room="108")
    lab, area = ctx["lab"], ctx["area"]
    create_container(lab["id"], make_pi_headers(ctx["pi"]["id"]), barcode="FL-A",
                     quantity_value=6.0)

    areas_mid = list_lab_areas(lab["id"])
    assert areas_mid[0]["current_container_count"] == 1

    completed = validate_success(api.complete_pickup_request(ctx["pickup"]["id"], ADMIN), 200)
    assert completed["status"] == "COMPLETED"

    c_after = get_container(ctx["containers"][0]["id"])
    assert c_after["state"] == "PICKED_UP"
    assert c_after["accumulation_area_id"] == area["id"], (
        "accumulation_area_id is retained for audit after pickup"
    )

    areas_after = list_lab_areas(lab["id"])
    assert areas_after[0]["current_container_count"] == 0

    lab_after = get_lab(lab["id"])
    assert lab_after["hazard_totals_regulatory"].get("FLAMMABLE", 0.0) == pytest.approx(6.0, abs=1e-6)
    assert lab_after["permit_report_required"] is False
