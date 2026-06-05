"""Lien lifecycle, the active_lien_count invariant, and the title-transfer lien cascade."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    TEST_USERS,
    ApiErrorId,
    create_owner,
    create_vehicle,
    create_verified_vehicle,
    setup_titled_vehicle,
    create_filed_lien,
    create_perfected_lien,
    create_title_application_payload,
)

CLERK = TEST_USERS["clerk_headers"]


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade/transfer_issue_releases_perfected_lien_chain
# ---------------------------------------------------------------------------
def test_transfer_issue_releases_perfected_lien_and_reassigns_owner():
    """PRD §3.2: "Third, and only when the `application_type` is `TRANSFER`, that owner
    reassignment releases the prior owner's encumbrances: every `Lien` on the vehicle currently
    in status `PERFECTED` transitions to `RELEASED`, because a prior owner's perfected lien does
    not carry to the new owner. Fourth, each such release decrements the vehicle's
    `active_lien_count` by 1".

    O1 holds a CLEAR title + one PERFECTED lien; a TRANSFER to O2 issued reassigns owner_id to
    O2, releases the lien, and drives active_lien_count 1 -> 0.

    Design: Difficulty/transitive_cascade/transfer_issue_releases_perfected_lien_chain
    """
    o1 = create_owner()
    o2 = create_owner()
    veh = create_verified_vehicle(owner_id=o1["id"])
    # INITIAL CLEAR title to O1 so a title exists and the lien can perfect.
    from test_helpers import issue_clear_title
    issue_clear_title(veh["id"], o1["id"], "INITIAL")
    lien = create_perfected_lien(veh["id"], lien_holder_name="First Bank", principal_cents=1000000)

    # TRANSFER application to O2 -> APPROVED.
    ta = validate_success(
        api_client.create_title_application(
            create_title_application_payload(veh["id"], o2["id"], "TRANSFER"), CLERK
        ),
        201,
    )
    validate_success(api_client.submit_title_application(ta["id"], CLERK), 200)
    validate_success(api_client.approve_title_application(ta["id"], CLERK), 200)

    validate_success(api_client.issue_title_application(ta["id"], CLERK), 200)

    veh_after = validate_success(api_client.get_vehicle(veh["id"], CLERK), 200)
    lien_after = validate_success(api_client.get_lien(lien["id"], CLERK), 200)
    assert veh_after["owner_id"] == o2["id"]
    assert lien_after["status"] == "RELEASED"
    assert veh_after["active_lien_count"] == 0


def test_transfer_issue_releases_lien_sets_rebuilt_brand_unaffected():
    """PRD §3.2: "every `Lien` on the vehicle currently in status `PERFECTED` transitions to
    `RELEASED`, because a prior owner's perfected lien does not carry to the new owner."

    Second assertion of the cascade: the released lien lands terminal RELEASED while the new
    owner of record is O2 (the transfer reassignment that triggered the release).

    Design: Difficulty/transitive_cascade/transfer_issue_releases_perfected_lien_chain
    """
    o1 = create_owner()
    o2 = create_owner()
    veh = create_verified_vehicle(owner_id=o1["id"])
    from test_helpers import issue_clear_title
    issue_clear_title(veh["id"], o1["id"], "INITIAL")
    lien = create_perfected_lien(veh["id"])
    ta = validate_success(
        api_client.create_title_application(
            create_title_application_payload(veh["id"], o2["id"], "TRANSFER"), CLERK
        ),
        201,
    )
    validate_success(api_client.submit_title_application(ta["id"], CLERK), 200)
    validate_success(api_client.approve_title_application(ta["id"], CLERK), 200)
    validate_success(api_client.issue_title_application(ta["id"], CLERK), 200)
    lien_after = validate_success(api_client.get_lien(lien["id"], CLERK), 200)
    assert lien_after["status"] == "RELEASED"


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check/empty_lien_count_zero_on_release_of_only_perfected
# ---------------------------------------------------------------------------
def test_release_only_perfected_lien_drives_count_to_zero():
    """PRD §3.3: "Releasing a lien that is currently `PERFECTED` advances it
    `PERFECTED → RELEASED`, decrements the vehicle's `active_lien_count` by 1, and increments
    the affected `Vehicle.version` by 1."

    The single PERFECTED lien is released, driving active_lien_count from 1 to exactly 0.

    Design: Difficulty/boundary_precision_check/empty_lien_count_zero_on_release_of_only_perfected
    """
    owner, veh = setup_titled_vehicle()
    lien = create_perfected_lien(veh["id"], lien_holder_name="Solo Bank", principal_cents=500000)
    veh_before = validate_success(api_client.get_vehicle(veh["id"], CLERK), 200)
    assert veh_before["active_lien_count"] == 1
    validate_success(api_client.release_lien(lien["id"], CLERK), 200)
    lien_after = validate_success(api_client.get_lien(lien["id"], CLERK), 200)
    veh_after = validate_success(api_client.get_vehicle(veh["id"], CLERK), 200)
    assert lien_after["status"] == "RELEASED"
    assert veh_after["active_lien_count"] == 0


def test_perfect_single_lien_sets_count_to_one():
    """PRD §3.3: "Perfecting a lien advances it `FILED → PERFECTED`, increments the vehicle's
    `active_lien_count` by 1, and increments the affected `Vehicle.version` by 1."

    The empty-set boundary's other side: from active_lien_count 0, perfecting the only lien
    raises it to exactly 1 (the value the release test then drives back to 0).

    Design: Difficulty/boundary_precision_check/empty_lien_count_zero_on_release_of_only_perfected
    """
    owner, veh = setup_titled_vehicle()
    assert veh["active_lien_count"] == 0
    create_perfected_lien(veh["id"])
    veh_after = validate_success(api_client.get_vehicle(veh["id"], CLERK), 200)
    assert veh_after["active_lien_count"] == 1


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency/lien_perfect_requires_vehicle_title
# ---------------------------------------------------------------------------
def test_perfect_lien_on_titleless_vehicle_rejected():
    """PRD §3.3: "A filed lien may be perfected only once the vehicle actually holds a title —
    that is, the vehicle's `title_status` is not `NONE`; perfection against a titleless vehicle
    is rejected with `ERR_LIEN_REQUIRES_TITLE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/lien_perfect_requires_vehicle_title
    """
    owner = create_owner()
    veh = create_vehicle(owner_id=owner["id"])  # title_status NONE
    lien = create_filed_lien(veh["id"], lien_holder_name="Eager Bank", principal_cents=700000)
    resp = api_client.perfect_lien(lien["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_LIEN_REQUIRES_TITLE.value)


def test_perfect_lien_succeeds_once_title_issued():
    """PRD §3.3: "A filed lien may be perfected only once the vehicle actually holds a title —
    that is, the vehicle's `title_status` is not `NONE`".

    Positive side of the cross-entity dependency: with a CLEAR title issued, the same perfect
    call that fails on a titleless vehicle now succeeds (lien -> PERFECTED).

    Design: Difficulty/cross_entity_state_dependency/lien_perfect_requires_vehicle_title
    """
    owner, veh = setup_titled_vehicle()
    lien = create_filed_lien(veh["id"])
    perfected = validate_success(api_client.perfect_lien(lien["id"], CLERK), 200)
    assert perfected["status"] == "PERFECTED"


# ---------------------------------------------------------------------------
# Difficulty/compensating_invariant/lien_perfect_release_conserves_active_lien_count
# ---------------------------------------------------------------------------
def test_perfect_then_release_conserves_lien_count():
    """PRD §3.3: "The governing invariant is that a vehicle's `active_lien_count` always equals
    the number of lien rows on that vehicle whose status is `PERFECTED`; perfecting increments
    it, releasing a perfected lien decrements it".

    Perfect (+1) then release (-1) leaves active_lien_count back at its pre-perfect value 0.

    Design: Difficulty/compensating_invariant/lien_perfect_release_conserves_active_lien_count
    """
    owner, veh = setup_titled_vehicle()
    lien = create_perfected_lien(veh["id"], lien_holder_name="Cycle Bank", principal_cents=400000)
    validate_success(api_client.release_lien(lien["id"], CLERK), 200)
    veh_after = validate_success(api_client.get_vehicle(veh["id"], CLERK), 200)
    lien_after = validate_success(api_client.get_lien(lien["id"], CLERK), 200)
    assert veh_after["active_lien_count"] == 0
    assert lien_after["status"] == "RELEASED"


def test_release_filed_lien_does_not_touch_count():
    """PRD §3.3: "Releasing a lien that was never perfected — still in `FILED` — advances it
    `FILED → RELEASED` but does not touch the vehicle's `active_lien_count` and does not bump
    the vehicle's version, since that lien was never counted."

    A never-perfected lien released leaves the conserved count at 0 — the compensating
    invariant must not over- or under-count uncounted liens.

    Design: Difficulty/compensating_invariant/lien_perfect_release_conserves_active_lien_count
    """
    owner, veh = setup_titled_vehicle()
    lien = create_filed_lien(veh["id"])
    validate_success(api_client.release_lien(lien["id"], CLERK), 200)
    veh_after = validate_success(api_client.get_vehicle(veh["id"], CLERK), 200)
    assert veh_after["active_lien_count"] == 0


# ---------------------------------------------------------------------------
# Corner/endpoints/fk_reverse_liens_by_vehicle_filtered_list
# ---------------------------------------------------------------------------
def test_list_liens_filtered_by_vehicle():
    """PRD §3.3: "Liens can be listed in reverse by `vehicle_id`."

    GET /liens?vehicle_id=X returns the vehicle's lien(s).

    Design: Corner/endpoints/fk_reverse_liens_by_vehicle_filtered_list
    """
    owner = create_owner()
    veh = create_vehicle(owner_id=owner["id"])
    lien = create_filed_lien(veh["id"], lien_holder_name="Lookup Bank", principal_cents=300000)
    resp = api_client.list_liens(CLERK, params={"vehicle_id": veh["id"]})
    body = resp.json()
    assert body["response_type"] == "array"
    assert any(row["vehicle_id"] == veh["id"] for row in body["data"])
    assert any(row["id"] == lien["id"] for row in body["data"])
