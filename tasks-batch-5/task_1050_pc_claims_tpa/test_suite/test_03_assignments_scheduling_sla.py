"""Assignment scheduling windows (adjuster buffer vs vendor half-open), capacity,
assignee-shape validation, and the acknowledgement SLA boundary.

Translates resource_temporal_overlap difficulty instances and the assignment/SLA
corner instances.
"""
from test_helpers import (
    validate_success, validate_error,
    create_assignment_payload, TEST_USERS, make_adjuster_headers,
    create_account, create_policy, create_adjuster, create_vendor,
    create_standing_data, create_claim, create_adjuster_assignment,
    create_vendor_assignment, get_claim, set_clock,
)

CM = TEST_USERS["claims_manager_headers"]


# --------------------------------------------------------------------------- #
# Adjuster travel-buffer conflict (60-minute adjacency)
# --------------------------------------------------------------------------- #
def test_adjuster_windows_within_buffer_conflict(api):
    """PRD §3.3: "for an adjuster, a travel buffer of 60 minutes applies as adjacency — two
    adjuster windows conflict when they overlap or when the gap separating them is less than
    60 minutes, and only windows separated by 60 minutes or more are permitted"
    PRD §3.3: "A conflict yields `ERR_ASSIGNMENT_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/adjuster_window_buffer_conflict
    """
    account, policy, adjuster = create_standing_data(api, {"account_code": "RT1"})
    adj = make_adjuster_headers(adjuster["id"])
    c1 = create_claim(api, policy["id"], adj, claimant_name="A")
    c2 = create_claim(api, policy["id"], adj, claimant_name="B")
    create_adjuster_assignment(api, c1["id"], adjuster["id"], adj,
                               inspection_start="2026-06-16T09:00:00Z",
                               inspection_end="2026-06-16T10:00:00Z")
    # Second window starts only 30 minutes after the first ends -> inside the 60-min buffer.
    payload = create_assignment_payload(
        c2["id"], "ADJUSTER", adjuster_id=adjuster["id"],
        inspection_start="2026-06-16T10:30:00Z", inspection_end="2026-06-16T11:30:00Z")
    validate_error(api.create_assignment(payload, adj), "ERR_ASSIGNMENT_WINDOW_CONFLICT")


def test_adjuster_windows_exactly_at_buffer_are_allowed(api):
    """PRD §3.3: "for an adjuster, a travel buffer of 60 minutes applies as adjacency — two
    adjuster windows conflict when they overlap or when the gap separating them is less than
    60 minutes, and only windows separated by 60 minutes or more are permitted"

    Design: Difficulty/resource_temporal_overlap/adjuster_window_buffer_conflict
    """
    account, policy, adjuster = create_standing_data(api, {"account_code": "RT1b"})
    adj = make_adjuster_headers(adjuster["id"])
    c1 = create_claim(api, policy["id"], adj, claimant_name="A")
    c2 = create_claim(api, policy["id"], adj, claimant_name="B")
    create_adjuster_assignment(api, c1["id"], adjuster["id"], adj,
                               inspection_start="2026-06-16T09:00:00Z",
                               inspection_end="2026-06-16T10:00:00Z")
    # Gap is exactly 60 minutes (10:00 -> 11:00): permitted.
    payload = create_assignment_payload(
        c2["id"], "ADJUSTER", adjuster_id=adjuster["id"],
        inspection_start="2026-06-16T11:00:00Z", inspection_end="2026-06-16T12:00:00Z")
    data = validate_success(api.create_assignment(payload, adj), 201)
    assert data["status"] == "ACTIVE"


# --------------------------------------------------------------------------- #
# Vendor half-open windows (no buffer)
# --------------------------------------------------------------------------- #
def test_vendor_windows_touching_endpoints_allowed(api):
    """PRD §3.3: "for a vendor, no buffer applies and two windows conflict only when their
    half-open intervals from `inspection_start` up to but not including `inspection_end`
    actually overlap, so windows that merely touch at an endpoint (one ending exactly when the
    next begins) are allowed."

    Design: Difficulty/resource_temporal_overlap/vendor_window_touching_endpoints_allowed
    """
    account = create_account(api, account_code="RT2")
    policy = create_policy(api, account["id"], policy_number="P-RT2")
    vendor = create_vendor(api, vendor_type="APPRAISER", credentialed_coverages=["PROPERTY"])
    c1 = create_claim(api, policy["id"], CM, claimant_name="A")
    c2 = create_claim(api, policy["id"], CM, claimant_name="B")
    create_vendor_assignment(api, c1["id"], vendor["id"], CM,
                             inspection_start="2026-06-17T09:00:00Z",
                             inspection_end="2026-06-17T11:00:00Z")
    payload = create_assignment_payload(
        c2["id"], "VENDOR", vendor_id=vendor["id"], scope="APPRAISAL",
        inspection_start="2026-06-17T11:00:00Z", inspection_end="2026-06-17T12:00:00Z")
    data = validate_success(api.create_assignment(payload, CM), 201)
    assert data["status"] == "ACTIVE"


def test_vendor_windows_that_overlap_conflict(api):
    """PRD §3.3: "for a vendor, no buffer applies and two windows conflict only when their
    half-open intervals from `inspection_start` up to but not including `inspection_end`
    actually overlap, so windows that merely touch at an endpoint (one ending exactly when the
    next begins) are allowed."

    Design: Difficulty/resource_temporal_overlap/vendor_window_touching_endpoints_allowed
    """
    account = create_account(api, account_code="RT2c")
    policy = create_policy(api, account["id"], policy_number="P-RT2c")
    vendor = create_vendor(api, vendor_type="APPRAISER", credentialed_coverages=["PROPERTY"])
    c1 = create_claim(api, policy["id"], CM, claimant_name="A")
    c2 = create_claim(api, policy["id"], CM, claimant_name="B")
    create_vendor_assignment(api, c1["id"], vendor["id"], CM,
                             inspection_start="2026-06-17T09:00:00Z",
                             inspection_end="2026-06-17T11:00:00Z")
    # [10:00,12:00) overlaps [09:00,11:00): conflict.
    payload = create_assignment_payload(
        c2["id"], "VENDOR", vendor_id=vendor["id"], scope="APPRAISAL",
        inspection_start="2026-06-17T10:00:00Z", inspection_end="2026-06-17T12:00:00Z")
    validate_error(api.create_assignment(payload, CM), "ERR_ASSIGNMENT_WINDOW_CONFLICT")


# --------------------------------------------------------------------------- #
# Assignee-shape and capacity
# --------------------------------------------------------------------------- #
def test_adjuster_assignment_without_adjuster_id_is_mismatch(api):
    """PRD §3.3: "When `assignee_type` is `ADJUSTER`, `adjuster_id` is required and
    `vendor_id` must be absent; when `assignee_type` is `VENDOR`, `vendor_id` is required and
    `adjuster_id` must be absent. A body violating this shape is rejected with
    `ERR_ASSIGNEE_MISMATCH`."

    Design: Corner/validations/assignee_mismatch_adjuster_without_id
    """
    account = create_account(api, account_code="C-AM")
    policy = create_policy(api, account["id"], policy_number="P-AM")
    claim = create_claim(api, policy["id"], CM)
    payload = create_assignment_payload(claim["id"], "ADJUSTER")  # no adjuster_id
    validate_error(api.create_assignment(payload, CM), "ERR_ASSIGNEE_MISMATCH")


def test_adjuster_at_capacity_rejects_new_assignment(api):
    """PRD §3.3: "Before that transition can complete, the assigned adjuster must be under
    capacity: if the adjuster already holds `max_open_claims` open claims the assignment is
    rejected with `ERR_ADJUSTER_CAPACITY`."

    Design: Corner/validations/adjuster_capacity_exceeded_rejected
    """
    account, policy, adjuster = create_standing_data(
        api, {"account_code": "C-CAP"}, adjuster_overrides={"max_open_claims": 1})
    adj = make_adjuster_headers(adjuster["id"])
    c1 = create_claim(api, policy["id"], adj, claimant_name="A")
    c2 = create_claim(api, policy["id"], adj, claimant_name="B")
    create_adjuster_assignment(api, c1["id"], adjuster["id"], adj,
                               inspection_start="2026-06-16T09:00:00Z",
                               inspection_end="2026-06-16T10:00:00Z")
    payload = create_assignment_payload(
        c2["id"], "ADJUSTER", adjuster_id=adjuster["id"],
        inspection_start="2026-06-16T13:00:00Z", inspection_end="2026-06-16T14:00:00Z")
    validate_error(api.create_assignment(payload, adj), "ERR_ADJUSTER_CAPACITY")


# --------------------------------------------------------------------------- #
# Acknowledgement SLA boundary (inclusive upper bound)
# --------------------------------------------------------------------------- #
def test_sla_ack_met_exactly_at_deadline(api):
    """PRD §3.2: "Once `ack_at` is set, `sla_ack_met` is true exactly when `ack_at` is set and
    is at or before `sla_ack_due`; an acknowledgement landing precisely on the deadline counts
    as met, because the upper bound is inclusive."

    Design: Corner/calculations/sla_ack_met_at_deadline_inclusive
    """
    set_clock(api, "2026-07-01T00:00:00Z")
    account = create_account(api, account_code="C-SL", sla_ack_hours=24)
    policy = create_policy(api, account["id"], policy_number="P-SL")
    adjuster = create_adjuster(api)
    adj = make_adjuster_headers(adjuster["id"])
    claim = create_claim(api, policy["id"], adj,
                         loss_date="2026-06-20T00:00:00Z", reported_date="2026-06-30T00:00:00Z")
    # ack_at = clock = 2026-07-01T00:00:00Z == due (reported + 24h) -> met.
    validate_success(api.create_assignment(create_assignment_payload(
        claim["id"], "ADJUSTER", adjuster_id=adjuster["id"],
        inspection_start="2026-07-01T09:00:00Z", inspection_end="2026-07-01T11:00:00Z"), adj), 201)
    refreshed = get_claim(api, claim["id"], adj)
    assert refreshed["status"] == "ASSIGNED"
    assert refreshed["sla_ack_met"] is True


def test_sla_ack_breached_one_second_after_deadline(api):
    """PRD §3.2: "Once `ack_at` is set, `sla_ack_met` is true exactly when `ack_at` is set and
    is at or before `sla_ack_due`; an acknowledgement landing precisely on the deadline counts
    as met, because the upper bound is inclusive."

    Design: Corner/calculations/sla_ack_breached_after_deadline
    """
    set_clock(api, "2026-07-01T00:00:01Z")
    account = create_account(api, account_code="C-SB", sla_ack_hours=24)
    policy = create_policy(api, account["id"], policy_number="P-SB")
    adjuster = create_adjuster(api)
    adj = make_adjuster_headers(adjuster["id"])
    claim = create_claim(api, policy["id"], adj,
                         loss_date="2026-06-20T00:00:00Z", reported_date="2026-06-30T00:00:00Z")
    # ack_at = 2026-07-01T00:00:01Z is one second past due (2026-07-01T00:00:00Z) -> not met.
    validate_success(api.create_assignment(create_assignment_payload(
        claim["id"], "ADJUSTER", adjuster_id=adjuster["id"],
        inspection_start="2026-07-01T09:00:00Z", inspection_end="2026-07-01T11:00:00Z"), adj), 201)
    refreshed = get_claim(api, claim["id"], adj)
    assert refreshed["status"] == "ASSIGNED"
    assert refreshed["sla_ack_met"] is False
