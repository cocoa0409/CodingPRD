"""The scheduled pipeline's lifecycle: send, approve, decline and expire."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_close,
    assert_instant_equals,
    assert_money,
    fixtures,
    make_customer_headers,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ESTIMATOR = TEST_USERS["estimator_headers"]


def _stale_inspection_world():
    """A SENT quote whose cited inspection completed 366 days before the clock."""
    fixtures.set_clock("2026-06-01T10:00:00Z")
    world = fixtures.base_world(
        account_name="Old Survey Ranch",
        email="ap@oldsurvey.example",
        membership_tier="NONE",
        account_jurisdiction="JUR_DELTA",
        property_jurisdiction="JUR_DELTA",
        well_jurisdiction="JUR_DELTA",
        address_line="366 Old Survey Rd",
        distance_miles=30.0,
        household_size=3,
        depth_feet=250.0,
        drawdown=8.0,
        technician_name="Casey Mbeki",
    )
    part = fixtures.new_part("CON-2400", "CONSUMABLE", 2400, on_hand_qty=10)
    inspection = fixtures.completed_inspection(
        world["well_id"], world["technician_id"], "2026-06-01T10:00:00Z", 10.0, 50.0, 8.0
    )
    staged = fixtures.priced_and_sent_quote(
        world["property_id"],
        world["well_id"],
        inspection["id"],
        part["id"],
        1,
        "REPAIR",
        60,
        "2026-06-03T12:00:00Z",
        "JOURNEYMAN",
    )
    fixtures.set_clock("2027-06-02T10:00:00Z")
    world["inspection_id"] = inspection["id"]
    world["quote_id"] = staged["quote_id"]
    return world


def test_approval_is_refused_once_the_cited_inspection_is_stale(api):
    """PRD 3.6: "The cited inspection must be `COMPLETED` and the elapsed time from its
    `completed_at` to the logical clock must be at most `INSPECTION_VALIDITY_DAYS` (365
    days), right-closed, or the answer is `ERR_INSPECTION_STALE`."

    Design: Difficulty/cross_entity_state_dependency/quote_approval_depends_on_inspection_freshness
    """
    world = _stale_inspection_world()
    validate_error(
        api.approve_quote(world["quote_id"], world["customer_headers"]),
        ApiErrorId.ERR_INSPECTION_STALE.value,
        422,
    )


def test_a_stale_inspection_leaves_the_quote_in_sent(api):
    """PRD 3.6: "On success the quote moves `SENT → APPROVED`, `approved_at` is stamped,
    `approved_total_cents` is latched from `total_cents`, and `version` rises by 1."
    PRD 3.2: "The inspection stores the three figures, stamps `completed_at` from the
    logical clock and moves `IN_PROGRESS → COMPLETED`."

    Design: Difficulty/cross_entity_state_dependency/quote_approval_depends_on_inspection_freshness
    """
    world = _stale_inspection_world()
    api.approve_quote(world["quote_id"], world["customer_headers"])

    inspection = fixtures.get_inspection(world["inspection_id"])
    assert_instant_equals(
        inspection["completed_at"], "2026-06-01T10:00:00Z", "Inspection.completed_at"
    )
    quote = fixtures.get_quote(world["quote_id"])
    assert quote["status"] == "SENT"
    assert quote["approved_at"] is None


def test_inspection_validity_is_right_closed_at_day_365(api):
    """PRD 3.6: "The cited inspection must be `COMPLETED` and the elapsed time from its
    `completed_at` to the logical clock must be at most `INSPECTION_VALIDITY_DAYS` (365
    days), right-closed, or the answer is `ERR_INSPECTION_STALE`."
    PRD 3.6: "The validity window is deliberately **not** enforced at approval. It is
    enforced only by the explicit expiry sweep, which a `PlatformAdmin` runs against a
    `SENT` quote"

    Design: Corner/validations/corner_validation_inspection_validity_boundary_at_365_days
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Stale Inspection Co",
        email="si@corner.example",
        address_line="365 Inspection",
        technician_tier="MASTER",
        technician_name="Stale Tech",
    )
    part = fixtures.new_part("CTL-5000-S", "CONTROL", 5000, on_hand_qty=10)
    inspection = fixtures.started_inspection(
        world["well_id"], world["technician_id"], "2026-06-01T10:00:00Z"
    )
    fixtures.set_clock("2026-06-01T12:00:00Z")
    validate_success(
        api.complete_inspection(
            inspection["id"],
            {
                "measured_yield_gpm": 20.0,
                "static_level_feet": 50.0,
                "observed_drawdown_gallons": 6.0,
            },
            world["technician_headers"],
        )
    )

    quote_a = fixtures.priced_and_sent_quote(
        world["property_id"], world["well_id"], inspection["id"], part["id"], 1,
        "REPAIR", 60, "2026-06-03T09:00:00Z", "MASTER",
    )
    quote_b = fixtures.priced_and_sent_quote(
        world["property_id"], world["well_id"], inspection["id"], part["id"], 1,
        "REPAIR", 60, "2026-06-03T09:00:00Z", "MASTER",
    )
    assert_money(
        fixtures.get_quote(quote_a["quote_id"])["total_cents"], 22080, "Quote.total_cents"
    )

    fixtures.set_clock("2027-06-01T12:00:00Z")
    approved = validate_success(
        api.approve_quote(quote_a["quote_id"], world["customer_headers"])
    )
    assert approved["status"] == "APPROVED"
    assert_instant_equals(
        approved["approved_at"], "2027-06-01T12:00:00Z", "Quote.approved_at"
    )
    assert_money(
        approved["approved_total_cents"], 22080, "Quote.approved_total_cents"
    )

    fixtures.set_clock("2027-06-02T12:00:00Z")
    validate_error(
        api.approve_quote(quote_b["quote_id"], world["customer_headers"]),
        ApiErrorId.ERR_INSPECTION_STALE.value,
        422,
    )
    stale = fixtures.get_quote(quote_b["quote_id"])
    assert stale["status"] == "SENT"
    assert stale["approved_at"] is None
    assert stale["approved_total_cents"] is None
    assert_instant_equals(
        fixtures.get_inspection(inspection["id"])["completed_at"],
        "2026-06-01T12:00:00Z",
        "Inspection.completed_at",
    )


def test_a_failed_yield_gate_at_approval_supersedes_the_line_then_errors(api):
    """PRD 2.11: "**A quote approval whose pump line no longer clears the yield gate.** Every
    offending line moves to `SUPERSEDED_BY_YIELD`, the quote moves to
    `REVISION_REQUIRED`, and the quote's and each offending line's `version` rise — and
    only then does the call return `ERR_QUOTE_LINE_YIELD_EXCEEDED` (HTTP 409)."
    PRD 3.6: "If a pump line has stopped clearing the yield gate — because a later
    inspection recorded a lower yield than the one the quote was priced against —
    approval takes the mutate-then-reject path of Section 2.11: every offending `ACTIVE`
    pump line moves `ACTIVE → SUPERSEDED_BY_YIELD`, the quote moves `SENT →
    REVISION_REQUIRED`, the versions rise, and the call then returns
    `ERR_QUOTE_LINE_YIELD_EXCEEDED` with all of it persisted."

    Design: Corner/state_machines/corner_mutate_then_reject_quote_yield_supersede_writes_persist
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Yield Drop Co",
        email="yd@corner.example",
        address_line="12 Yield",
        depth_feet=300.0,
        technician_tier="MASTER",
        technician_name="Yield Tech",
    )
    pump = fixtures.new_part("PMP-12GPM", "PUMP", 60000, on_hand_qty=4, rated_gpm=12.0)
    inspection_1 = fixtures.completed_inspection(
        world["well_id"], world["technician_id"], "2026-06-01T10:00:00Z", 20.0, 70.0, 8.0
    )
    staged = fixtures.priced_and_sent_quote(
        world["property_id"], world["well_id"], inspection_1["id"], pump["id"], 1,
        "PUMP_REPLACEMENT", 120, "2026-06-03T12:00:00Z", "MASTER",
    )
    fixtures.completed_inspection(
        world["well_id"], world["technician_id"], "2026-06-02T10:00:00Z", 10.0, 90.0, 8.0
    )

    validate_error(
        api.approve_quote(staged["quote_id"], world["customer_headers"]),
        ApiErrorId.ERR_QUOTE_LINE_YIELD_EXCEEDED.value,
        409,
    )
    assert fixtures.get_quote_line(staged["line_id"])["status"] == "SUPERSEDED_BY_YIELD"
    quote = fixtures.get_quote(staged["quote_id"])
    assert quote["status"] == "REVISION_REQUIRED"
    assert quote["approved_at"] is None
    assert_close(
        fixtures.get_well(world["well_id"])["measured_yield_gpm"],
        10.0,
        "WellProfile.measured_yield_gpm",
    )


def test_a_sent_quote_expires_only_strictly_past_its_validity_window(api):
    """PRD 3.6: "It is enforced only by the explicit expiry sweep, which a
    `PlatformAdmin` runs against a `SENT` quote: the elapsed time from `sent_at` to the
    logical clock must be **strictly greater** than `QUOTE_VALIDITY_DAYS` (30 days), and
    the quote then moves `SENT → EXPIRED` with `version` up by 1."
    PRD 3.6: "A transition attempted from the wrong state is refused with
    `ERR_QUOTE_INVALID_STATE`."
    PRD 3.6: "**Sending** takes `PRICED → SENT`, stamps `sent_at` from the logical clock
    and raises the quote's `version` by 1."

    Design: Corner/state_machines/corner_quote_expire_after_validity_window
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Expire Co",
        email="ex@corner.example",
        address_line="30 Expire",
        household_size=2,
        technician_name="Exp Tech",
    )
    part = fixtures.new_part("CON-1500", "CONSUMABLE", 1500, on_hand_qty=10)
    inspection = fixtures.completed_inspection(
        world["well_id"], world["technician_id"], "2026-06-01T10:00:00Z", 11.0, 30.0, 8.0
    )
    staged = fixtures.priced_and_sent_quote(
        world["property_id"], world["well_id"], inspection["id"], part["id"], 1,
        "REPAIR", 60, "2026-06-03T12:00:00Z", "JOURNEYMAN",
    )

    fixtures.set_clock("2026-07-01T09:00:00Z")
    validate_error(
        api.expire_quote(staged["quote_id"], ADMIN),
        ApiErrorId.ERR_QUOTE_INVALID_STATE.value,
        409,
    )
    assert_instant_equals(
        fixtures.get_quote(staged["quote_id"])["sent_at"],
        "2026-06-01T09:00:00Z",
        "Quote.sent_at",
    )

    fixtures.set_clock("2026-07-01T09:00:01Z")
    expired = validate_success(api.expire_quote(staged["quote_id"], ADMIN))
    assert expired["status"] == "EXPIRED"


def test_declining_a_sent_quote_is_terminal(api):
    """PRD 3.6: "A customer may instead decline a `SENT` quote, moving it to `DECLINED`
    with `version` up by 1."
    PRD 3.6: "The full lifecycle is `DRAFT`, `PRICED`, `SENT`, `APPROVED`, `DECLINED`,
    `REVISION_REQUIRED`, `CONSUMED` and `EXPIRED`, with `DECLINED`, `CONSUMED` and
    `EXPIRED` terminal. A transition attempted from the wrong state is refused with
    `ERR_QUOTE_INVALID_STATE`."

    Design: Corner/endpoints/corner_endpoint_quote_decline_is_terminal
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Decline Co",
        email="dc@corner.example",
        address_line="1 Decline",
        technician_name="Decline Tech",
    )
    part = fixtures.new_part("CTL-5000-D", "CONTROL", 5000, on_hand_qty=10)
    inspection = fixtures.completed_inspection(
        world["well_id"], world["technician_id"], "2026-06-01T10:00:00Z", 20.0, 50.0, 6.0
    )
    staged = fixtures.priced_and_sent_quote(
        world["property_id"], world["well_id"], inspection["id"], part["id"], 1,
        "REPAIR", 60, "2026-06-03T09:00:00Z", "JOURNEYMAN",
    )
    sent_version = staged["quote"]["version"]

    declined = validate_success(
        api.decline_quote(staged["quote_id"], world["customer_headers"])
    )
    assert declined["status"] == "DECLINED"
    assert declined["version"] == sent_version + 1
    assert_instant_equals(declined["sent_at"], "2026-06-01T09:00:00Z", "Quote.sent_at")

    validate_error(
        api.approve_quote(staged["quote_id"], world["customer_headers"]),
        ApiErrorId.ERR_QUOTE_INVALID_STATE.value,
        409,
    )
    quote = fixtures.get_quote(staged["quote_id"])
    assert quote["status"] == "DECLINED"
    assert quote["approved_at"] is None
    assert quote["approved_total_cents"] is None
    assert_money(quote["total_cents"], 18080, "Quote.total_cents")
