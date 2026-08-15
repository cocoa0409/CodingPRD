"""Waste pickup lifecycle: revision loop, empty-submit boundary, terminal lockdown,
item editability, cancel compensation, and cross-lab referential integrity."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_worker,
    assign_and_complete_training,
    create_area,
    create_container,
    create_draft_pickup,
    create_lab,
    create_lab_with_trained_pi,
    create_tagged_container,
    get_container,
    get_pickup,
    list_lab_areas,
    make_pi_headers,
    setup_completed_pickup,
    setup_pickup_with_tagged_items,
    setup_scheduled_pickup,
    setup_submitted_pickup,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def test_submit_reject_resubmit_revision_loop(api):
    """PRD §3.4: "Submission is the PI's signature action and moves the request from
    `DRAFT` to `SUBMITTED`, or from `REJECTED` back to `SUBMITTED` in the revision
    loop." and "A successful submit clears any recorded `rejection_reason` to null
    and increments the request's `version`."
    PRD §3.4: "Rejecting a `SUBMITTED` request records the supplied `reason` into
    `rejection_reason` and moves the request to `REJECTED`, deliberately preserving
    every container link — the containers stay `WASTE_TAGGED` with their
    `pickup_request_id` intact — so the PI can revise and resubmit."

    Design: Difficulty/non_linear_state_machine/pickup_submit_reject_resubmit_cycle
    """
    ctx = setup_submitted_pickup(quantities=(2.0,), name="Chem E", room="105")
    pickup, pi = ctx["pickup"], ctx["pi"]

    rejected = validate_success(
        api.reject_pickup_request(pickup["id"], {"reason": "missing manifest"}, ADMIN), 200
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["rejection_reason"] == "missing manifest"

    resubmitted = validate_success(
        api.submit_pickup_request(pickup["id"], make_pi_headers(pi["id"])), 200
    )
    assert resubmitted["status"] == "SUBMITTED", "REJECTED -> SUBMITTED revision loop"
    assert resubmitted["rejection_reason"] is None, "re-submit clears rejection_reason"
    assert resubmitted["estimated_quantity_total"] == pytest.approx(2.0, abs=1e-6), (
        "items are preserved through the reject/resubmit loop"
    )


def test_reject_preserves_container_links(api):
    """PRD §3.4: "Rejecting a `SUBMITTED` request records the supplied `reason` into
    `rejection_reason` and moves the request to `REJECTED`, deliberately preserving
    every container link — the containers stay `WASTE_TAGGED` with their
    `pickup_request_id` intact — so the PI can revise and resubmit."

    Design: Difficulty/non_linear_state_machine/pickup_submit_reject_resubmit_cycle
    """
    ctx = setup_submitted_pickup(quantities=(2.0,), name="Chem E2", room="105")
    pickup, container = ctx["pickup"], ctx["containers"][0]

    rejected = validate_success(
        api.reject_pickup_request(pickup["id"], {"reason": "missing manifest"}, ADMIN), 200
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["estimated_quantity_total"] == pytest.approx(2.0, abs=1e-6)

    c_after = get_container(container["id"])
    assert c_after["state"] == "WASTE_TAGGED"
    assert c_after["pickup_request_id"] == pickup["id"], "link preserved through rejection"


def test_submit_empty_pickup_rejected(api):
    """PRD §3.4: "Submitting requires at least one linked container (an empty request
    is rejected with `ERR_PICKUP_EMPTY`, HTTP 422)"

    Design: Difficulty/boundary_precision_check/pickup_submit_empty_vs_single_item
    """
    lab, pi = create_lab_with_trained_pi("FLAMMABLE", name="Lab L0", room="114")
    pickup = create_draft_pickup(lab["id"], pi)

    res = api.submit_pickup_request(pickup["id"], make_pi_headers(pi["id"]))
    validate_error(res, ApiErrorId.ERR_PICKUP_EMPTY)
    assert get_pickup(pickup["id"])["status"] == "DRAFT", "rejected submit leaves status DRAFT"


def test_submit_with_exactly_one_item_succeeds(api):
    """PRD §3.4: "Submitting requires at least one linked container (an empty request
    is rejected with `ERR_PICKUP_EMPTY`, HTTP 422)" and "Submission is the PI's
    signature action and moves the request from `DRAFT` to `SUBMITTED`"
    PRD §3.4: "The `estimated_quantity_total` is the sum of `quantity_value` over the
    containers linked to the request that are still `WASTE_TAGGED`."

    Design: Difficulty/boundary_precision_check/pickup_submit_empty_vs_single_item
    """
    ctx = setup_pickup_with_tagged_items(quantities=(2.0,), name="Lab L0b", room="114")
    pickup, pi = ctx["pickup"], ctx["pi"]

    submitted = validate_success(
        api.submit_pickup_request(pickup["id"], make_pi_headers(pi["id"])), 200
    )
    assert submitted["status"] == "SUBMITTED"
    assert submitted["estimated_quantity_total"] == pytest.approx(2.0, abs=1e-6)


def test_completed_pickup_cannot_be_submitted(api):
    """PRD §3.4: "a request in any other status is rejected with `ERR_PICKUP_STATE`"
    and "A request that reaches `COMPLETED` or `CANCELLED` is terminal."

    Design: Corner/state_machines/completed_pickup_submit_returns_pickup_state
    """
    ctx = setup_completed_pickup(quantities=(1.0,), name="Lab F", room="105")
    pickup, pi = ctx["pickup"], ctx["pi"]
    assert pickup["status"] == "COMPLETED"

    res = api.submit_pickup_request(pickup["id"], make_pi_headers(pi["id"]))
    validate_error(res, ApiErrorId.ERR_PICKUP_STATE)
    assert get_pickup(pickup["id"])["status"] == "COMPLETED", "terminal status unchanged"


def test_picked_up_container_cannot_be_untagged(api):
    """PRD §3.3: "It is permitted only while the container is `WASTE_TAGGED` and
    either its `pickup_request_id` is null or the linked pickup request is in
    `REJECTED` or `CANCELLED` status; any other combination is rejected with
    `ERR_CONTAINER_STATE`."

    Design: Corner/state_machines/picked_up_container_cannot_untag
    """
    ctx = setup_completed_pickup(quantities=(1.0,), name="Lab G", room="106")
    container, pi = ctx["containers"][0], ctx["pi"]
    assert get_container(container["id"])["state"] == "PICKED_UP"

    res = api.untag_waste(container["id"], make_pi_headers(pi["id"]))
    validate_error(res, ApiErrorId.ERR_CONTAINER_STATE)
    assert get_container(container["id"])["state"] == "PICKED_UP"


def test_add_item_to_submitted_pickup_rejected(api):
    """PRD §3.4: "While the request is in `DRAFT` or `REJECTED` status, its
    composition is editable" and "operating on a request that has left the editable
    statuses is rejected with `ERR_PICKUP_STATE`."

    Design: Corner/endpoints/add_item_to_submitted_pickup_rejected
    """
    lab, pi = create_lab_with_trained_pi("FLAMMABLE", name="Lab AI", room="121")
    area = create_area(lab["id"], capacity_containers=10)
    c1 = create_tagged_container(lab["id"], pi, area["id"], barcode="AI-1")
    c2 = create_tagged_container(lab["id"], pi, area["id"], barcode="AI-2",
                                 chemical_name="Methanol")
    pickup = create_draft_pickup(lab["id"], pi)
    validate_success(
        api.add_pickup_item(pickup["id"], {"container_id": c1["id"]}, make_pi_headers(pi["id"])),
        200,
    )
    validate_success(api.submit_pickup_request(pickup["id"], make_pi_headers(pi["id"])), 200)

    res = api.add_pickup_item(
        pickup["id"], {"container_id": c2["id"]}, make_pi_headers(pi["id"])
    )
    validate_error(res, ApiErrorId.ERR_PICKUP_STATE)
    assert get_pickup(pickup["id"])["estimated_quantity_total"] == pytest.approx(1.0, abs=1e-6), (
        "failed add-item must not change the linked composition"
    )


def test_cancel_scheduled_pickup_compensates_containers(api):
    """PRD §3.4: "Cancelling a `SCHEDULED` request is the compensating path: it moves
    the request to `CANCELLED` and clears the `pickup_request_id` of every linked
    container to null, while the containers themselves remain `WASTE_TAGGED` in their
    areas and the area counts are unchanged."

    Design: Corner/state_machines/pickup_cancel_returns_containers_compensated
    """
    ctx = setup_scheduled_pickup(
        quantities=(1.0,), name="Lab L", room="108", dock_id="DOCK-2",
        window_start="2026-08-11T10:00:00Z", window_end="2026-08-11T11:00:00Z",
    )
    pickup, container, area = ctx["pickup"], ctx["containers"][0], ctx["area"]

    cancelled = validate_success(api.cancel_pickup_request(pickup["id"], ADMIN), 200)
    assert cancelled["status"] == "CANCELLED"

    c_after = get_container(container["id"])
    assert c_after["state"] == "WASTE_TAGGED", "container stays WASTE_TAGGED after cancel"
    assert c_after["pickup_request_id"] is None, "cancel clears the pickup link"
    assert c_after["accumulation_area_id"] == area["id"], "area membership intact"

    areas_after = list_lab_areas(ctx["lab"]["id"])
    assert areas_after[0]["current_container_count"] == 1, (
        "area counts are unchanged by cancellation"
    )


def test_add_item_cross_lab_rejected(api):
    """PRD §3.4: "Adding requires the container to be `WASTE_TAGGED` and to belong to
    the same lab as the request — a cross-lab link is rejected with
    `ERR_CROSS_LAB_REFERENCE`"

    Design: Corner/validations/add_item_cross_lab_rejected
    """
    lab1 = create_lab(name="Lab T1", room="114")
    lab2 = create_lab(name="Lab T2", room="115")
    pi1 = add_worker(lab1["id"], full_name="Dr. One", role_in_lab="PI")
    pi2 = add_worker(lab2["id"], full_name="Dr. Two", role_in_lab="PI")
    assign_and_complete_training(lab2["id"], pi2["id"], "FLAMMABLE")
    area2 = create_area(lab2["id"], name="SAA-2")
    c2 = create_tagged_container(lab2["id"], pi2, area2["id"], barcode="XR-1")
    pickup1 = create_draft_pickup(lab1["id"], pi1)

    res = api.add_pickup_item(
        pickup1["id"], {"container_id": c2["id"]}, make_pi_headers(pi1["id"])
    )
    validate_error(res, ApiErrorId.ERR_CROSS_LAB_REFERENCE)
    assert get_pickup(pickup1["id"])["estimated_quantity_total"] == pytest.approx(0.0, abs=1e-6)
    assert get_container(c2["id"])["pickup_request_id"] is None
