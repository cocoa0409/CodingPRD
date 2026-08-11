"""Time-window semantics: half-open VOC rule windows (adjacency allowed) vs
the 30-minute delivery clearance buffer (adjacency insufficient) — PRD §2.10,
§3.3, §3.8."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_delivery_payload,
    create_jurisdiction,
    create_voc_rule_payload,
    place_order,
    schedule_delivery,
    setup_account_job_product,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
MANAGER = TEST_USERS["manager_headers"]


def test_voc_rule_adjacent_window_allowed(api):
    """PRD §3.3: "Two rules for the same jurisdiction-and-category pair may
    not have overlapping windows under the half-open semantics of §2.10;
    adjacency — one rule's `effective_from` landing exactly on another's
    `effective_to` — is allowed. An overlapping create is rejected with
    `ERR_VOC_RULE_OVERLAP` (HTTP 409)."

    A second FLAT rule starting exactly at the first rule's effective_to is
    created.

    Design: Difficulty/resource_temporal_overlap/voc_rule_half_open_adjacency
    """
    jur = create_jurisdiction(code="CO-DEN", name="Denver")
    rule_a = validate_success(api.create_voc_rule(
        create_voc_rule_payload(jur["id"], category="FLAT", max_voc_gpl=250,
                                effective_from="2026-01-01T00:00:00Z",
                                effective_to="2026-06-01T00:00:00Z"),
        ADMIN), expected_status=201)
    resp = api.create_voc_rule(
        create_voc_rule_payload(jur["id"], category="FLAT", max_voc_gpl=200,
                                effective_from="2026-06-01T00:00:00Z",
                                effective_to="2026-09-01T00:00:00Z"),
        ADMIN)
    rule_b = validate_success(resp, expected_status=201)
    assert rule_b["id"], "half-open adjacency is allowed"


def test_voc_rule_true_overlap_rejected(api):
    """PRD §2.10: "Three kinds of time window recur, and all three use
    half-open semantics: the start instant is included, the end instant is
    excluded. ... Overlap rules follow from the same semantics: two windows
    that merely touch — one ending exactly when the other begins — are
    adjacent, not overlapping, and are allowed unless a workflow says
    otherwise." PRD §3.3: "An overlapping create is rejected with
    `ERR_VOC_RULE_OVERLAP` (HTTP 409)."

    A window running 2026-05-01..2026-07-01 genuinely overlaps the existing
    2026-01-01..2026-06-01 rule.

    Design: Difficulty/resource_temporal_overlap/voc_rule_half_open_adjacency
    """
    jur = create_jurisdiction(code="CO-DEN", name="Denver")
    validate_success(api.create_voc_rule(
        create_voc_rule_payload(jur["id"], category="FLAT", max_voc_gpl=250,
                                effective_from="2026-01-01T00:00:00Z",
                                effective_to="2026-06-01T00:00:00Z"),
        ADMIN), expected_status=201)
    resp = api.create_voc_rule(
        create_voc_rule_payload(jur["id"], category="FLAT", max_voc_gpl=220,
                                effective_from="2026-05-01T00:00:00Z",
                                effective_to="2026-07-01T00:00:00Z"),
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_VOC_RULE_OVERLAP)


def test_voc_rule_overlap_scoped_per_category(api):
    """PRD §3.3: "Two rules for the same jurisdiction-and-category pair may
    not have overlapping windows under the half-open semantics of §2.10".

    A NON_FLAT rule overlapping the FLAT rule's window never conflicts — the
    rule book is per (jurisdiction, category).

    Design: Difficulty/resource_temporal_overlap/voc_rule_half_open_adjacency
    """
    jur = create_jurisdiction(code="CO-DEN", name="Denver")
    validate_success(api.create_voc_rule(
        create_voc_rule_payload(jur["id"], category="FLAT", max_voc_gpl=250,
                                effective_from="2026-01-01T00:00:00Z",
                                effective_to="2026-06-01T00:00:00Z"),
        ADMIN), expected_status=201)
    resp = api.create_voc_rule(
        create_voc_rule_payload(jur["id"], category="NON_FLAT", max_voc_gpl=300,
                                effective_from="2026-03-01T00:00:00Z",
                                effective_to="2026-04-01T00:00:00Z"),
        ADMIN)
    rule_d = validate_success(resp, expected_status=201)
    assert rule_d["category"] == "NON_FLAT"


def _setup_delivery_buffer_job(api):
    """Account, job, product, one UNPAID order; no deliveries yet."""
    account, _, job, product = setup_account_job_product(
        company_name="Buf Co", credit_limit_cents=100_000_000,
        jurisdiction_code="TX-DAL", jurisdiction_name="Dallas",
        job_name="Lot", sku="P-BUF", list_price_cents=5000)
    order = place_order(account["id"], job["id"],
                        [{"product_id": product["id"], "quantity": 1}])
    return account, job, order


def test_delivery_window_short_gap_rejected(api):
    """PRD §3.8: "then the buffer rule — against every other delivery of the
    same job whose `status` is `SCHEDULED` or `EN_ROUTE`, the new window must
    keep at least a 30-minute clearance: the new `window_start` must be no
    earlier than the existing delivery's `window_end` plus 30 minutes, or the
    new `window_end` plus 30 minutes must be no later than the existing
    delivery's `window_start`. Mere adjacency is not enough here (unlike the
    windows of §2.10), and a violation is `ERR_DELIVERY_WINDOW_CONFLICT`
    (HTTP 409)."

    A window starting only 20 minutes after the existing 09:00-10:00 window
    fails.

    Design: Difficulty/resource_temporal_overlap/delivery_window_thirty_minute_buffer
    """
    account, job, order = _setup_delivery_buffer_job(api)
    schedule_delivery(order["id"], job["id"],
                      window_start="2026-06-15T09:00:00Z",
                      window_end="2026-06-15T10:00:00Z")
    resp = api.create_delivery(
        create_delivery_payload(order["id"], job["id"],
                                window_start="2026-06-15T10:20:00Z",
                                window_end="2026-06-15T11:00:00Z"),
        MANAGER)
    validate_error(resp, ApiErrorId.ERR_DELIVERY_WINDOW_CONFLICT)


def test_delivery_window_exactly_thirty_minutes_accepted(api):
    """PRD §3.8: "then the buffer rule — against every other delivery of the
    same job whose `status` is `SCHEDULED` or `EN_ROUTE`, the new window must
    keep at least a 30-minute clearance: the new `window_start` must be no
    earlier than the existing delivery's `window_end` plus 30 minutes, or the
    new `window_end` plus 30 minutes must be no later than the existing
    delivery's `window_start`. Mere adjacency is not enough here (unlike the
    windows of §2.10), and a violation is `ERR_DELIVERY_WINDOW_CONFLICT`
    (HTTP 409)."

    A start exactly 30 minutes after the existing window's end satisfies the
    inclusive clearance and is created.

    Design: Difficulty/resource_temporal_overlap/delivery_window_thirty_minute_buffer
    """
    account, job, order = _setup_delivery_buffer_job(api)
    first = schedule_delivery(order["id"], job["id"],
                              window_start="2026-06-15T09:00:00Z",
                              window_end="2026-06-15T10:00:00Z")
    assert first["status"] == "SCHEDULED"
    resp = api.create_delivery(
        create_delivery_payload(order["id"], job["id"],
                                window_start="2026-06-15T10:30:00Z",
                                window_end="2026-06-15T11:00:00Z"),
        MANAGER)
    second = validate_success(resp, expected_status=201)
    assert second["status"] == "SCHEDULED", (
        "the exactly-30-minute clearance satisfies the buffer rule")
