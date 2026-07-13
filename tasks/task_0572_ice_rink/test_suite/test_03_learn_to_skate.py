"""Learn-to-skate enrollment: the class-state gate, the prerequisite gate, and
the optimistic-concurrency guard on tuition-subscription creation."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_rink, create_published_slot, create_class, create_skater,
    enroll, setup_active_subscription,
)

RM = TEST_USERS["rink_manager_headers"]


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency/enrollment_requires_non_cancelled_class
# ---------------------------------------------------------------------------
def test_enroll_into_cancelled_class_rejected(api):
    """PRD §3.3: "The class must be `OPEN` — enrolling on a `FULL`, `CANCELLED`,
    or `COMPLETED` class yields `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/enrollment_requires_non_cancelled_class
    """
    rink = create_rink(api)
    slot = create_published_slot(api, rink["id"], "LEARN_TO_SKATE",
                                 "2026-06-10T08:00:00Z", "2026-06-10T09:00:00Z")
    cls = create_class(api, slot["id"])
    # Cancelling the parent slot drives the class to CANCELLED.
    validate_success(api.cancel_ice_slot(slot["id"], RM))
    sk = create_skater(api, "enrcancel@x.com")
    validate_error(api.create_enrollment(cls["id"], {"skater_id": sk["id"]}, RM),
                   ApiErrorId.ERR_INVALID_STATE.value)


def test_enroll_into_open_class_succeeds(api):
    """PRD §3.3: "On success the enrollment is created in `ENROLLED` status,
    `enrolled_count` rises by one, and the class flips to `FULL` if the new count
    equals `capacity`."

    Design: Difficulty/cross_entity_state_dependency/enrollment_requires_non_cancelled_class
    """
    rink = create_rink(api)
    slot = create_published_slot(api, rink["id"], "LEARN_TO_SKATE",
                                 "2026-06-10T08:00:00Z", "2026-06-10T09:00:00Z")
    cls = create_class(api, slot["id"])
    sk = create_skater(api, "enropen@x.com")
    data = validate_success(
        api.create_enrollment(cls["id"], {"skater_id": sk["id"]}, RM), 201)
    assert data["status"] == "ENROLLED", f"expected ENROLLED, got {data['status']}"


# ---------------------------------------------------------------------------
# Corner/validations/enroll_without_completed_prerequisite_returns_422
# ---------------------------------------------------------------------------
def test_enroll_without_completed_prerequisite_rejected(api):
    """PRD §3.3: "If the class declares a `prerequisite_class_id`, the skater must
    already hold an enrollment with status `COMPLETED` in that prerequisite class;
    if not, the enrollment is rejected with `ERR_PREREQUISITE_NOT_MET`."

    Design: Corner/validations/enroll_without_completed_prerequisite_returns_422
    """
    rink = create_rink(api)
    slot1 = create_published_slot(api, rink["id"], "LEARN_TO_SKATE",
                                  "2026-06-10T08:00:00Z", "2026-06-10T09:00:00Z")
    basic = create_class(api, slot1["id"], level_name="BASIC")
    slot2 = create_published_slot(api, rink["id"], "LEARN_TO_SKATE",
                                  "2026-06-11T08:00:00Z", "2026-06-11T09:00:00Z")
    basic2 = create_class(api, slot2["id"], level_name="BASIC_2",
                          prerequisite_class_id=basic["id"])
    sk = create_skater(api, "prereq@x.com")
    validate_error(api.create_enrollment(basic2["id"], {"skater_id": sk["id"]}, RM),
                   ApiErrorId.ERR_PREREQUISITE_NOT_MET.value)


# ---------------------------------------------------------------------------
# Corner/cross_cutting/occ_stale_enrollment_version_returns_412
# ---------------------------------------------------------------------------
def test_stale_expected_enrollment_version_rejected(api):
    """PRD §2.6: "If that value does not equal the enrollment's current `version`
    at the time of the request — meaning another writer has advanced the enrollment
    since the client last read it — the create is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting/occ_stale_enrollment_version_returns_412
    """
    # setup_active_subscription creates one subscription, which bumps the
    # enrollment's version; the enrollment handle still carries the pre-bump value.
    setup = setup_active_subscription(api, email="occstale@x.com")
    stale_version = setup["enrollment"]["version"]
    payload = {
        "expected_enrollment_version": stale_version,
        "monthly_fee_cents": 12000,
        "billing_cycle_start": "2026-06-01",
        "billing_cycle_end": "2026-07-01",
        "total_sessions_in_cycle": 8,
    }
    validate_error(
        api.create_tuition_subscription(setup["enrollment"]["id"], payload, RM),
        ApiErrorId.ERR_STALE_VERSION.value)


# ---------------------------------------------------------------------------
# Corner/cross_cutting/occ_subscription_create_bumps_enrollment_version
# ---------------------------------------------------------------------------
def test_subscription_create_bumps_enrollment_version(api):
    """PRD §3.4: "any existing `ACTIVE` subscription for that enrollment is moved
    to `CANCELLED` as part of the create, and the parent enrollment's `version` is
    incremented by one."

    Design: Corner/cross_cutting/occ_subscription_create_bumps_enrollment_version
    """
    setup = setup_active_subscription(api, email="occbump@x.com")
    before = setup["enrollment"]["version"]
    enr = validate_success(api.get_enrollment(setup["enrollment"]["id"], RM))
    assert enr["version"] == before + 1, (
        f"subscription create must bump enrollment version by 1: "
        f"{before} -> expected {before + 1}, got {enr['version']}")
    assert setup["subscription"]["status"] == "ACTIVE", (
        f"created subscription must be ACTIVE, got {setup['subscription']['status']}")
