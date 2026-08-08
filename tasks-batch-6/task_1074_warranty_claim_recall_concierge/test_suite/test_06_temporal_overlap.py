"""Interval-adjacency semantics: half-open subscription periods (touching is allowed)
versus closed recall windows (touching overlaps).
"""
from test_helpers import (
    validate_success, validate_error,
    make_household_owner_headers, make_manufacturer_agent_headers,
    new_household, new_owner, new_subscription, new_manufacturer, new_recall_notice,
    publish_recall,
    create_subscription_payload,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]


# ─── Difficulty: half-open subscription periods ───────────────────────────────
def test_subscription_touching_period_is_accepted(api):
    """PRD 3.2: "Because the intervals are half-open, two periods that merely touch at
    an endpoint — one ending exactly where the next begins — do **not** overlap and are
    both allowed."

    Design: Difficulty/resource_temporal_overlap/subscription_period_halfopen_touching_ok_overlap_rejected
    """
    hh = new_household()
    owner = new_owner(hh["id"])
    sub1 = new_subscription(hh["id"], owner["id"], tier="BASIC",
                            period_start="2025-01-01T00:00:00Z", period_end="2026-01-01T00:00:00Z")
    payload = create_subscription_payload(tier="PLUS", period_start="2026-01-01T00:00:00Z",
                                          period_end="2027-01-01T00:00:00Z")
    res = api.create_subscription(hh["id"], payload, make_household_owner_headers(owner["id"]))
    sub2 = validate_success(res, 201)
    assert sub2["status"] == "ACTIVE"
    assert sub2["period_start"][:10] == sub1["period_end"][:10]


def test_subscription_overlapping_period_rejected(api):
    """PRD 3.2: "When a subscription is created, the system rejects it with
    `ERR_SUBSCRIPTION_PERIOD_OVERLAP` if the household already has any non-`CANCELLED`
    subscription whose half-open period overlaps the new one."

    Design: Difficulty/resource_temporal_overlap/subscription_period_halfopen_touching_ok_overlap_rejected
    """
    hh = new_household()
    owner = new_owner(hh["id"])
    new_subscription(hh["id"], owner["id"], tier="BASIC",
                     period_start="2025-01-01T00:00:00Z", period_end="2026-01-01T00:00:00Z")
    api.create_subscription(hh["id"],
                            create_subscription_payload(tier="PLUS",
                                                        period_start="2026-01-01T00:00:00Z",
                                                        period_end="2027-01-01T00:00:00Z"),
                            make_household_owner_headers(owner["id"]))
    res = api.create_subscription(hh["id"],
                                  create_subscription_payload(tier="PREMIUM",
                                                              period_start="2025-06-01T00:00:00Z",
                                                              period_end="2026-06-01T00:00:00Z"),
                                  make_household_owner_headers(owner["id"]))
    validate_error(res, "ERR_SUBSCRIPTION_PERIOD_OVERLAP")


# ─── Difficulty: closed recall windows ────────────────────────────────────────
def test_recall_window_touching_endpoint_publish_rejected(api):
    """PRD 3.4: "Because both intervals are closed, two windows that merely touch at a
    shared endpoint **do** overlap and the publish is rejected."

    Design: Difficulty/resource_temporal_overlap/recall_window_closed_touching_endpoints_overlap
    """
    mfr = new_manufacturer()
    rn1 = new_recall_notice(mfr["id"], affected_model_number="M9", serial_range_start=1,
                            serial_range_end=100, severity="HIGH", remedy_type="REPAIR",
                            effective_from="2025-01-01T00:00:00Z",
                            effective_to="2025-06-01T00:00:00Z")
    publish_recall(rn1["id"], mfr["id"])
    rn2 = new_recall_notice(mfr["id"], affected_model_number="M9", serial_range_start=1,
                            serial_range_end=100, severity="HIGH", remedy_type="REPAIR",
                            effective_from="2025-06-01T00:00:00Z",
                            effective_to="2025-12-01T00:00:00Z")
    res = api.publish_recall_notice(rn2["id"], make_manufacturer_agent_headers(mfr["id"]))
    validate_error(res, "ERR_RECALL_WINDOW_OVERLAP")


def test_recall_window_touching_publish_leaves_notice_draft(api):
    """PRD 3.4: "a publish is rejected with `ERR_RECALL_WINDOW_OVERLAP` if any other
    already-`PUBLISHED` recall notice from the same `manufacturer_id` and the same
    `affected_model_number` has a closed effective interval that overlaps this notice's
    window."

    Design: Difficulty/resource_temporal_overlap/recall_window_closed_touching_endpoints_overlap
    """
    mfr = new_manufacturer()
    rn1 = new_recall_notice(mfr["id"], affected_model_number="M9", serial_range_start=1,
                            serial_range_end=100, severity="HIGH", remedy_type="REPAIR",
                            effective_from="2025-01-01T00:00:00Z",
                            effective_to="2025-06-01T00:00:00Z")
    publish_recall(rn1["id"], mfr["id"])
    rn2 = new_recall_notice(mfr["id"], affected_model_number="M9", serial_range_start=1,
                            serial_range_end=100, severity="HIGH", remedy_type="REPAIR",
                            effective_from="2025-06-01T00:00:00Z",
                            effective_to="2025-12-01T00:00:00Z")
    api.publish_recall_notice(rn2["id"], make_manufacturer_agent_headers(mfr["id"]))
    after = validate_success(api.get_recall_notice(rn2["id"], ADMIN), 200)
    assert after["status"] == "DRAFT"
