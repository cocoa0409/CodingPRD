"""Pole attachments: load ledger boundaries, window buffer conflicts,
compensating revoke, pole-standing guard, and optimistic concurrency."""
from test_helpers import validate_success, validate_error, assert_version_incremented
from test_helpers.fixtures import (
    new_pole, new_pole_attachment, get_pole, setup_pole_with_approved_attachment,
    setup_emergency_intersection,
)


# ── Difficulty: exact-fill load boundary is allowed ──────────────────────────
def test_pole_load_exact_fill_approved(api, utility_coordinator_headers):
    """PRD §3.7: "Finally the pole must have room: the attachment's `load_units`
    must not exceed the pole's `available_load_units` — equivalently, the pole's
    `committed_load_units` plus this attachment's `load_units` must not exceed its
    `load_capacity_units` — else `ERR_POLE_LOAD_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/pole_load_exact_fill_allowed
    """
    pole, att1 = setup_pole_with_approved_attachment(capacity=100, load_units=60, mount_zone="LOW")
    att2 = new_pole_attachment(pole["id"], pole["version"], attacher_name="ISP2",
                               mount_zone="MID", load_units=40)
    approved = validate_success(api.approve_pole_attachment(att2["id"], utility_coordinator_headers), 200)
    assert approved["status"] == "APPROVED"


def test_pole_committed_and_available_after_exact_fill(api, utility_coordinator_headers):
    """PRD §3.7: "A pole's `committed_load_units` is always the sum of `load_units`
    over its currently `APPROVED` attachments, and `available_load_units` is
    `load_capacity_units` minus that sum."

    Design: Difficulty/boundary_precision_check/pole_load_exact_fill_allowed
    """
    pole, att1 = setup_pole_with_approved_attachment(capacity=100, load_units=60, mount_zone="LOW")
    att2 = new_pole_attachment(pole["id"], pole["version"], attacher_name="ISP2",
                               mount_zone="MID", load_units=40)
    validate_success(api.approve_pole_attachment(att2["id"], utility_coordinator_headers), 200)
    fresh = get_pole(pole["id"])
    assert fresh["committed_load_units"] == 100
    assert fresh["available_load_units"] == 0


# ── Difficulty: attachment window buffer conflict ────────────────────────────
def test_attachment_window_within_buffer_rejected(api, utility_coordinator_headers):
    """PRD §3.7: "No other `APPROVED` attachment on the same pole and the same
    `mount_zone` may occupy a window within 7 days of this one: the two
    `[effective_from, effective_to]` windows must be disjoint and additionally
    separated by at least a 7-day buffer, otherwise the approval is rejected with
    `ERR_ATTACHMENT_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/attachment_window_buffer_conflict
    """
    pole, att_a = setup_pole_with_approved_attachment(
        capacity=100, load_units=10, mount_zone="HIGH",
        effective_from="2026-04-01T00:00:00Z", effective_to="2026-05-01T00:00:00Z")
    att_b = new_pole_attachment(pole["id"], pole["version"], attacher_name="B",
                                mount_zone="HIGH", load_units=10,
                                effective_from="2026-05-03T00:00:00Z",
                                effective_to="2026-06-01T00:00:00Z")  # only 2 days after
    res = api.approve_pole_attachment(att_b["id"], utility_coordinator_headers)
    validate_error(res, "ERR_ATTACHMENT_WINDOW_CONFLICT", expected_status=409)
    fetched = validate_success(api.get_pole_attachment(att_b["id"], utility_coordinator_headers), 200)
    assert fetched["status"] == "REQUESTED"


def test_attachment_window_beyond_buffer_allowed(api, utility_coordinator_headers):
    """PRD §3.7: "No other `APPROVED` attachment on the same pole and the same
    `mount_zone` may occupy a window within 7 days of this one: the two
    `[effective_from, effective_to]` windows must be disjoint and additionally
    separated by at least a 7-day buffer, otherwise the approval is rejected with
    `ERR_ATTACHMENT_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/attachment_window_buffer_conflict
    """
    pole, att_a = setup_pole_with_approved_attachment(
        capacity=100, load_units=10, mount_zone="HIGH",
        effective_from="2026-04-01T00:00:00Z", effective_to="2026-05-01T00:00:00Z")
    att_b = new_pole_attachment(pole["id"], pole["version"], attacher_name="B",
                                mount_zone="HIGH", load_units=10,
                                effective_from="2026-05-10T00:00:00Z",  # 9 days after, > 7-day buffer
                                effective_to="2026-06-01T00:00:00Z")
    approved = validate_success(api.approve_pole_attachment(att_b["id"], utility_coordinator_headers), 200)
    assert approved["status"] == "APPROVED"


# ── Difficulty: pole load units conserved on revoke ──────────────────────────
def test_pole_load_units_conserved_after_revoke(api, utility_coordinator_headers):
    """PRD §3.7: "An approved attachment may later be revoked, moving it from
    `APPROVED` to the terminal `REVOKED` state; revocation is a compensating
    release that reduces the pole's `committed_load_units` by the attachment's
    `load_units` (returning `available_load_units` to its pre-approval value) and
    increments the pole's `version` by one."

    Design: Difficulty/compensating_invariant/pole_load_units_conserved_on_revoke
    """
    pole, att = setup_pole_with_approved_attachment(capacity=100, load_units=30, mount_zone="LOW")
    revoked = validate_success(api.revoke_pole_attachment(att["id"], utility_coordinator_headers), 200)
    assert revoked["status"] == "REVOKED"
    fresh = get_pole(pole["id"])
    assert fresh["committed_load_units"] == 0
    assert fresh["available_load_units"] == 100


def test_pole_load_units_debited_on_approve(api, utility_coordinator_headers):
    """PRD §3.7: "On approval the pole's `committed_load_units` rises by the
    attachment's `load_units` (recomputing `available_load_units`) and the pole's
    `version` increments by one. A pole's `committed_load_units` is always the sum
    of `load_units` over its currently `APPROVED` attachments, and
    `available_load_units` is `load_capacity_units` minus that sum."

    Design: Difficulty/compensating_invariant/pole_load_units_conserved_on_revoke
    """
    pole, att = setup_pole_with_approved_attachment(capacity=100, load_units=30, mount_zone="LOW")
    # `pole` was re-read after the approve, so it already reflects the debit.
    assert pole["committed_load_units"] == 30
    assert pole["available_load_units"] == 70


# ── Corner: load exceeded over capacity (strict-greater rejection) ───────────
def test_pole_load_exceeded_over_capacity(api, utility_coordinator_headers):
    """PRD §3.7: "Finally the pole must have room: the attachment's `load_units`
    must not exceed the pole's `available_load_units` — equivalently, the pole's
    `committed_load_units` plus this attachment's `load_units` must not exceed its
    `load_capacity_units` — else `ERR_POLE_LOAD_EXCEEDED`."

    Design: Corner/endpoints/pole_load_exceeded_over_capacity
    """
    pole, att1 = setup_pole_with_approved_attachment(capacity=100, load_units=60, mount_zone="LOW")
    att2 = new_pole_attachment(pole["id"], pole["version"], attacher_name="ISP2",
                               mount_zone="MID", load_units=41)  # 60 + 41 = 101 > 100
    res = api.approve_pole_attachment(att2["id"], utility_coordinator_headers)
    validate_error(res, "ERR_POLE_LOAD_EXCEEDED", expected_status=409)
    fetched = validate_success(api.get_pole_attachment(att2["id"], utility_coordinator_headers), 200)
    assert fetched["status"] == "REQUESTED"
    assert get_pole(pole["id"])["committed_load_units"] == 60


# ── Corner: approve blocked when pole not standing ───────────────────────────
def test_pole_not_standing_blocks_approve(api, utility_coordinator_headers):
    """PRD §3.7: "Approving an attachment moves it from `REQUESTED` to `APPROVED`
    and is guarded by three checks in precedence order. The pole must be
    `STANDING`, else `ERR_POLE_NOT_STANDING`."

    Design: Corner/errors/pole_not_standing_on_approve
    """
    ctx = setup_emergency_intersection()  # its pole was struck DOWN by the knockdown
    pole = get_pole(ctx["pole"]["id"])
    assert pole["status"] == "DOWN"
    att = new_pole_attachment(pole["id"], pole["version"], attacher_name="ISP",
                              mount_zone="LOW", load_units=10)
    res = api.approve_pole_attachment(att["id"], utility_coordinator_headers)
    validate_error(res, "ERR_POLE_NOT_STANDING", expected_status=409)
    fetched = validate_success(api.get_pole_attachment(att["id"], utility_coordinator_headers), 200)
    assert fetched["status"] == "REQUESTED"


# ── Corner: OCC stale pole version rejected ──────────────────────────────────
def test_occ_stale_pole_version_rejected(api, utility_coordinator_headers):
    """PRD §2.6: "A create-attachment request (`POST /pole-attachments`) must
    include `expected_pole_version` as a required field carrying the client's last
    observed `version` of the target pole. If that value does not equal the pole's
    current `version`, the create is rejected with `ERR_STALE_POLE_VERSION` (HTTP
    412)."

    Design: Corner/cross_cutting/occ_stale_pole_version_rejected
    """
    pole = new_pole(load_capacity_units=100)
    stale_version = pole["version"]
    # First create legitimately advances the pole version.
    new_pole_attachment(pole["id"], stale_version, attacher_name="ISP1",
                        mount_zone="LOW", load_units=10)
    res = api.create_pole_attachment(
        {"pole_id": pole["id"], "attacher_name": "ISP2", "mount_zone": "MID",
         "load_units": 10, "effective_from": "2026-04-01T00:00:00Z",
         "effective_to": "2026-05-01T00:00:00Z", "expected_pole_version": stale_version},
        utility_coordinator_headers)
    validate_error(res, "ERR_STALE_POLE_VERSION", expected_status=412)


# ── Corner: OCC version increments on create ─────────────────────────────────
def test_attachment_create_increments_pole_version(api, utility_coordinator_headers):
    """PRD §3.7: "A new attachment opens in `REQUESTED`, and merely creating it
    advances the pole's `version` by one."

    Design: Corner/cross_cutting/occ_version_increments_on_create
    """
    pole = new_pole(load_capacity_units=100)
    before = pole["version"]
    att = new_pole_attachment(pole["id"], before, attacher_name="ISP1",
                              mount_zone="LOW", load_units=10)
    assert att["status"] == "REQUESTED"
    fresh = get_pole(pole["id"])
    assert_version_incremented(fresh["version"], before)
