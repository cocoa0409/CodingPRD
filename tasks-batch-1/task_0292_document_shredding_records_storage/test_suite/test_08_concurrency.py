"""Optimistic concurrency control on service-order rescheduling."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    setup_account_with_rate_card,
    create_container,
    create_order,
)
from test_helpers import factories as f

AM = TEST_USERS["account_manager_headers"]


def _scheduled_order():
    account, location, rate_card = setup_account_with_rate_card()
    container = create_container(account["id"], location["id"], "BIN", 40, 4.0)
    order = create_order(account["id"], location["id"],
                         container_ids=[container["id"]],
                         service_mode="OFF_SITE_PICKUP", cadence="SCHEDULED")
    return order


# ===========================================================================
# cross_cutting_complexity_layers / occ_reschedule_correct_version_succeeds
# ===========================================================================
def test_reschedule_with_correct_version_succeeds(api):
    """PRD §2.8: "A reschedule request must carry expected_serviceorder_version,
    which is not optional; it must equal the target order's current version at the
    moment the request is processed."

    PRD §3.3: "on success the order's slot is updated and its version increments
    by one."

    Design: Corner/cross_cutting_complexity_layers/occ_reschedule_correct_version_succeeds
    """
    order = _scheduled_order()
    v0 = order["version"]
    data = validate_success(api.reschedule_order(order["id"], f.reschedule_payload(
        v0, "2026-07-02T09:00:00Z", "2026-07-02T10:00:00Z"), AM), 200)
    assert data["version"] == v0 + 1, f"got {data['version']}"
    assert data["scheduled_slot_start"] == "2026-07-02T09:00:00Z", f"got {data['scheduled_slot_start']}"


# ===========================================================================
# cross_cutting_complexity_layers / occ_reschedule_stale_version_rejected
# ===========================================================================
def test_reschedule_with_stale_version_rejected(api):
    """PRD §2.8: "If another writer has advanced the order's version since the
    client last read it - for instance, because a competing reschedule has already
    superseded the prior slot - the supplied value is stale and the request is
    rejected with ERR_STALE_VERSION (HTTP 412)."

    A first reschedule advances the version; a second reschedule still carrying
    the original (now stale) version is rejected.

    Design: Corner/cross_cutting_complexity_layers/occ_reschedule_stale_version_rejected
    """
    order = _scheduled_order()
    v0 = order["version"]
    get_success_data(api.reschedule_order(order["id"], f.reschedule_payload(
        v0, "2026-07-02T09:00:00Z", "2026-07-02T10:00:00Z"), AM))
    validate_error(api.reschedule_order(order["id"], f.reschedule_payload(
        v0, "2026-07-03T09:00:00Z", "2026-07-03T10:00:00Z"), AM),
        ApiErrorId.ERR_STALE_VERSION.value)
