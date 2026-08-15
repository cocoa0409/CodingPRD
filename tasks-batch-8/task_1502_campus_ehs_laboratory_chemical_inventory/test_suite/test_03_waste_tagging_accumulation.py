"""Waste tagging guards, accumulation-area counting invariant, and overstay aging."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_worker,
    assign_and_complete_training,
    create_area,
    create_container,
    create_lab,
    create_lab_with_trained_pi,
    create_tagged_container,
    get_container,
    get_lab,
    list_lab_areas,
    make_pi_headers,
    set_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def test_area_count_conserved_across_tag_untag(api):
    """PRD §3.3: "On success the container's `accumulation_area_id` is set to the area
    and its `tagged_at` is stamped with the logical now; the area's count increases by
    one"
    PRD §3.3: "Untagging clears `accumulation_area_id`, `tagged_at`, and
    `pickup_request_id` to null, decreases the previous area's count by one,
    re-screens the hazard totals, recomputes posture, and increments the container's
    `version`."

    Design: Difficulty/compensating_invariant/area_count_conserved_tag_untag
    """
    lab, pi = create_lab_with_trained_pi("FLAMMABLE", name="Lab Q", room="117")
    headers = make_pi_headers(pi["id"])
    area = create_area(lab["id"], capacity_containers=10)
    c1 = create_container(lab["id"], headers, barcode="Q-1", quantity_value=3.0)

    tagged = validate_success(
        api.tag_waste(c1["id"], {"accumulation_area_id": area["id"]}, headers), 200
    )
    assert tagged["state"] == "WASTE_TAGGED"
    assert tagged["accumulation_area_id"] == area["id"]
    assert tagged["tagged_at"] is not None
    areas_mid = list_lab_areas(lab["id"])
    assert areas_mid[0]["current_container_count"] == 1

    untagged = validate_success(api.untag_waste(c1["id"], headers), 200)
    assert untagged["state"] == "IN_USE"
    assert untagged["accumulation_area_id"] is None
    assert untagged["tagged_at"] is None
    assert untagged["pickup_request_id"] is None
    areas_after = list_lab_areas(lab["id"])
    assert areas_after[0]["current_container_count"] == 0, (
        "tag/untag pair must conserve the area count with no drift"
    )


def test_area_count_conserved_over_multiple_containers(api):
    """PRD §3.3: "the area's count increases by one" (on tag) and "Untagging clears
    `accumulation_area_id`, `tagged_at`, and `pickup_request_id` to null, decreases
    the previous area's count by one, re-screens the hazard totals, recomputes
    posture, and increments the container's `version`."

    Design: Difficulty/compensating_invariant/area_count_conserved_tag_untag
    """
    lab, pi = create_lab_with_trained_pi("FLAMMABLE", name="Lab Q2", room="117")
    headers = make_pi_headers(pi["id"])
    area = create_area(lab["id"], capacity_containers=10)
    c1 = create_container(lab["id"], headers, barcode="Q-1", quantity_value=1.0)
    c2 = create_container(lab["id"], headers, barcode="Q-2", quantity_value=1.0)

    api.tag_waste(c1["id"], {"accumulation_area_id": area["id"]}, headers)
    api.tag_waste(c2["id"], {"accumulation_area_id": area["id"]}, headers)
    assert list_lab_areas(lab["id"])[0]["current_container_count"] == 2

    api.untag_waste(c1["id"], headers)
    assert list_lab_areas(lab["id"])[0]["current_container_count"] == 1

    api.untag_waste(c2["id"], headers)
    areas_after = list_lab_areas(lab["id"])
    assert areas_after[0]["current_container_count"] == 0
    assert get_container(c1["id"])["state"] == "IN_USE"
    assert get_container(c2["id"])["state"] == "IN_USE"


def test_untrained_actor_and_cross_lab_area_yields_training_error(api):
    """PRD §2.8: "Every mutating request is screened against the applicable checks in
    a fixed priority order, and the first failing check determines the rejection — a
    later check never masks an earlier one." with "9. The required-training gate on
    waste tagging, else `ERR_REQUIRED_TRAINING_INCOMPLETE`." listed before "19.
    Cross-lab reference integrity, else `ERR_CROSS_LAB_REFERENCE`."
    PRD §3.3: "the acting worker must hold a training assignment in this lab, for the
    container's `hazard_class`, in status `COMPLETED` (otherwise
    `ERR_REQUIRED_TRAINING_INCOMPLETE`, HTTP 422)"

    Design: Difficulty/priority_pair_validation_conflict/training_safety_precedes_cross_lab_referential
    """
    # Lab L1 with a PI who has NO FLAMMABLE training; Lab L2 owns the target area.
    lab1 = create_lab(name="Lab J1", room="110")
    lab2 = create_lab(name="Lab J2", room="111")
    pi1 = add_worker(lab1["id"], full_name="Dr. Py", role_in_lab="PI")
    c1 = create_container(
        lab1["id"], make_pi_headers(pi1["id"]), barcode="FL-9", quantity_value=1.0
    )
    area2 = create_area(lab2["id"], name="SAA-OTHER", capacity_containers=10)

    res = api.tag_waste(c1["id"], {"accumulation_area_id": area2["id"]}, make_pi_headers(pi1["id"]))
    validate_error(res, ApiErrorId.ERR_REQUIRED_TRAINING_INCOMPLETE)
    assert get_container(c1["id"])["state"] == "IN_USE", "rejected tag must not change state"


def test_trained_actor_cross_lab_area_yields_cross_lab_error(api):
    """PRD §3.3: "the named area must belong to the same lab as the container
    (otherwise `ERR_CROSS_LAB_REFERENCE`, HTTP 422)"
    (With the required-training gate satisfied, the referential check is the one that
    fires, isolating it from the training gate of §2.8 rule 9.)

    Design: Difficulty/priority_pair_validation_conflict/training_safety_precedes_cross_lab_referential
    """
    lab1 = create_lab(name="Lab J1b", room="110")
    lab2 = create_lab(name="Lab J2b", room="111")
    pi1 = add_worker(lab1["id"], full_name="Dr. Py", role_in_lab="PI")
    assign_and_complete_training(lab1["id"], pi1["id"], "FLAMMABLE")
    c1 = create_container(
        lab1["id"], make_pi_headers(pi1["id"]), barcode="FL-9", quantity_value=1.0
    )
    area2 = create_area(lab2["id"], name="SAA-OTHER", capacity_containers=10)

    res = api.tag_waste(c1["id"], {"accumulation_area_id": area2["id"]}, make_pi_headers(pi1["id"]))
    validate_error(res, ApiErrorId.ERR_CROSS_LAB_REFERENCE)
    assert get_container(c1["id"])["state"] == "IN_USE"


def test_area_capacity_exceeded_on_second_tag(api):
    """PRD §3.3: "the area's `current_container_count` must be below its
    `capacity_containers` before the tag (otherwise `ERR_AREA_CAPACITY_EXCEEDED`,
    HTTP 409)"

    Design: Corner/validations/area_capacity_exceeded_on_second_tag
    """
    lab, pi = create_lab_with_trained_pi("FLAMMABLE", name="Lab R2", room="113")
    headers = make_pi_headers(pi["id"])
    c1 = create_container(lab["id"], headers, barcode="CAP-1", quantity_value=1.0)
    c2 = create_container(lab["id"], headers, barcode="CAP-2", quantity_value=1.0)
    area = create_area(lab["id"], name="SAA-TINY", capacity_containers=1)

    validate_success(
        api.tag_waste(c1["id"], {"accumulation_area_id": area["id"]}, headers), 200
    )
    res = api.tag_waste(c2["id"], {"accumulation_area_id": area["id"]}, headers)
    validate_error(res, ApiErrorId.ERR_AREA_CAPACITY_EXCEEDED)
    assert get_container(c2["id"])["state"] == "IN_USE"
    assert list_lab_areas(lab["id"])[0]["current_container_count"] == 1


def test_overstay_boundary_strictly_greater_than_365_days(api):
    """PRD §3.3: "the container is an overstay when that age is strictly greater than
    365 days, so a container at exactly 365 days is still compliant. An area's
    `has_overstay_containers` is true when any container currently tagged into it is
    an overstay"
    PRD §2.6: "Otherwise, if at least one container of the lab is `WASTE_TAGGED` and
    has been tagged for strictly more than 365 days, posture is `RESTRICTED`."

    Design: Corner/calculations/accumulation_overstay_strictly_greater_than_365_days
    """
    lab, pi = create_lab_with_trained_pi(
        "FLAMMABLE", name="Lab N2", room="109",
    )
    area = create_area(lab["id"], capacity_containers=10)
    create_tagged_container(lab["id"], pi, area["id"], barcode="AG-1", quantity_value=1.0)

    # exactly 365 days after tagging at the 2026-08-01T00:00:00Z startup clock
    set_clock("2027-08-01T00:00:00Z")
    areas_365 = list_lab_areas(lab["id"])
    assert areas_365[0]["has_overstay_containers"] is False, (
        "exactly 365 days is still compliant (strictly-greater rule)"
    )

    set_clock("2027-08-02T00:00:00Z")
    areas_366 = list_lab_areas(lab["id"])
    assert areas_366[0]["has_overstay_containers"] is True, (
        "366 days is strictly greater than 365 and must flag overstay"
    )
    assert get_lab(lab["id"])["posture"] == "RESTRICTED"
