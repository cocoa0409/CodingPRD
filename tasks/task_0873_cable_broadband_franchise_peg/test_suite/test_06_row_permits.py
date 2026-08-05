"""Right-of-way permits: window de-confliction and the franchise-active gate."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    TEST_USERS, make_operator_headers,
    create_row_permit_payload,
)
from test_helpers import (
    create_active_franchise, create_row_segment, create_requested_permit,
)

AUTHORITY = TEST_USERS["authority_headers"]


# ---- Difficulty: rowpermit_window_overlap_within_buffer ----
def test_permit_within_buffer_rejected(api):
    """PRD 3.2: "A new permit collides with an existing one unless the new window
    begins at least 24 hours after the existing window ends, or the existing
    window begins at least 24 hours after the new window ends. Exactly 24 hours
    of gap is permitted; anything less collides and the create is rejected with
    `ERR_PERMIT_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/rowpermit_window_overlap_within_buffer
    """
    fr = create_active_franchise(api)
    seg = create_row_segment(api, name="Oak Blvd", length_miles=0.5, homes_along=140)
    create_requested_permit(api, fr["id"], seg["id"],
                            window_start="2026-06-01T00:00:00Z", window_end="2026-06-02T00:00:00Z")
    op = make_operator_headers(fr["id"])
    # New window starts only 12h after existing end (2026-06-02T00:00 + 12h).
    payload = create_row_permit_payload(fr["id"], seg["id"], purpose="aerial",
                                        window_start="2026-06-02T12:00:00Z",
                                        window_end="2026-06-03T00:00:00Z")
    resp = api.create_row_permit(payload, op)
    validate_error(resp, ApiErrorId.ERR_PERMIT_WINDOW_OVERLAP.value, 409)


def test_permit_exactly_buffer_allowed(api):
    """PRD 3.2: "the new window begins at least 24 hours after the existing window
    ends ... Exactly 24 hours of gap is permitted".

    Design: Difficulty/resource_temporal_overlap/rowpermit_window_overlap_within_buffer
    """
    fr = create_active_franchise(api)
    seg = create_row_segment(api, name="Oak Blvd", length_miles=0.5, homes_along=140)
    create_requested_permit(api, fr["id"], seg["id"],
                            window_start="2026-06-01T00:00:00Z", window_end="2026-06-02T00:00:00Z")
    op = make_operator_headers(fr["id"])
    # New window starts exactly 24h after existing end (2026-06-02T00:00 + 24h).
    payload = create_row_permit_payload(fr["id"], seg["id"], purpose="aerial",
                                        window_start="2026-06-03T00:00:00Z",
                                        window_end="2026-06-04T00:00:00Z")
    data = validate_success(api.create_row_permit(payload, op), 201)
    assert data["status"] == "REQUESTED"


# ---- Difficulty: rowpermit_approve_requires_franchise_active ----
def test_approve_permit_after_revoke_returns_franchise_not_active(api):
    """PRD 3.2: "Approval is defined only from `REQUESTED` and additionally
    requires the franchise's `lifecycle_status` to still be `ACTIVE` (else
    `ERR_FRANCHISE_NOT_ACTIVE`)".

    Design: Difficulty/cross_entity_state_dependency/rowpermit_approve_requires_franchise_active
    """
    fr = create_active_franchise(api)
    seg = create_row_segment(api, name="Elm Ave", length_miles=0.3, homes_along=80)
    permit = create_requested_permit(api, fr["id"], seg["id"],
                                     window_start="2026-06-01T00:00:00Z",
                                     window_end="2026-06-02T00:00:00Z")
    validate_success(api.revoke_franchise(fr["id"], AUTHORITY), 200)
    resp = api.decide_row_permit(permit["id"], {"decision": "APPROVE"}, AUTHORITY)
    validate_error(resp, ApiErrorId.ERR_FRANCHISE_NOT_ACTIVE.value, 409)


def test_permit_stays_requested_after_blocked_approve(api):
    """PRD 3.2: "Approval is defined only from `REQUESTED` and additionally
    requires the franchise's `lifecycle_status` to still be `ACTIVE` (else
    `ERR_FRANCHISE_NOT_ACTIVE`); it advances the permit to `APPROVED`".

    Design: Difficulty/cross_entity_state_dependency/rowpermit_approve_requires_franchise_active
    """
    fr = create_active_franchise(api)
    seg = create_row_segment(api, name="Elm Ave", length_miles=0.3, homes_along=80)
    permit = create_requested_permit(api, fr["id"], seg["id"],
                                     window_start="2026-06-01T00:00:00Z",
                                     window_end="2026-06-02T00:00:00Z")
    validate_success(api.revoke_franchise(fr["id"], AUTHORITY), 200)
    api.decide_row_permit(permit["id"], {"decision": "APPROVE"}, AUTHORITY)
    after = validate_success(api.get_row_permit(permit["id"], AUTHORITY), 200)
    assert after["status"] == "REQUESTED"


# ---- Difficulty: rowpermit_inactive_franchise_referential_beats_temporal ----
def test_inactive_franchise_beats_window_overlap(api):
    """PRD 2.8: "franchise-active for permits (`ERR_FRANCHISE_NOT_ACTIVE`) ...
    permit-window overlap (`ERR_PERMIT_WINDOW_OVERLAP`)" (evaluated in that
    numeric order).
    PRD 3.2: "the target franchise's `lifecycle_status` must be `ACTIVE`;
    otherwise the request is rejected with `ERR_FRANCHISE_NOT_ACTIVE`."

    Design: Difficulty/priority_pair_validation_conflict/rowpermit_inactive_franchise_referential_beats_temporal
    """
    fr = create_active_franchise(api)
    seg = create_row_segment(api, name="Main St 100-400", length_miles=0.4, homes_along=120)
    create_requested_permit(api, fr["id"], seg["id"],
                            window_start="2026-06-01T00:00:00Z", window_end="2026-06-02T00:00:00Z")
    validate_success(api.revoke_franchise(fr["id"], AUTHORITY), 200)
    op = make_operator_headers(fr["id"])
    # Window also overlaps the existing permit, but franchise-active fires first.
    payload = create_row_permit_payload(fr["id"], seg["id"], purpose="aerial",
                                        window_start="2026-06-01T12:00:00Z",
                                        window_end="2026-06-01T18:00:00Z")
    resp = api.create_row_permit(payload, op)
    validate_error(resp, ApiErrorId.ERR_FRANCHISE_NOT_ACTIVE.value, 409)


def test_rejected_permit_not_created_when_inactive(api):
    """PRD 3.2: "the target franchise's `lifecycle_status` must be `ACTIVE`;
    otherwise the request is rejected with `ERR_FRANCHISE_NOT_ACTIVE`."

    Design: Difficulty/priority_pair_validation_conflict/rowpermit_inactive_franchise_referential_beats_temporal
    """
    fr = create_active_franchise(api)
    seg = create_row_segment(api, name="Main St 100-400", length_miles=0.4, homes_along=120)
    create_requested_permit(api, fr["id"], seg["id"],
                            window_start="2026-06-01T00:00:00Z", window_end="2026-06-02T00:00:00Z")
    validate_success(api.revoke_franchise(fr["id"], AUTHORITY), 200)
    op = make_operator_headers(fr["id"])
    payload = create_row_permit_payload(fr["id"], seg["id"], purpose="aerial",
                                        window_start="2026-06-01T12:00:00Z",
                                        window_end="2026-06-01T18:00:00Z")
    api.create_row_permit(payload, op)
    # Only the original permit should exist on the segment.
    _, meta = validate_paginated(api.list_row_permits(AUTHORITY, params={"row_segment_id": seg["id"]}))
    assert meta["total_count"] == 1


# ---- Corner: list_row_permits_filtered_by_segment ----
def test_list_row_permits_filtered_by_segment(api):
    """PRD 2.9: "Right-of-way permits may be filtered by `franchise_id` and/or
    `row_segment_id`".

    Design: Corner/endpoints/list_row_permits_filtered_by_segment
    """
    fr = create_active_franchise(api)
    seg = create_row_segment(api, name="Cedar Ct", length_miles=0.1, homes_along=20)
    permit = create_requested_permit(api, fr["id"], seg["id"],
                                     window_start="2026-06-01T00:00:00Z",
                                     window_end="2026-06-02T00:00:00Z")
    data, meta = validate_paginated(api.list_row_permits(AUTHORITY, params={"row_segment_id": seg["id"]}))
    assert meta["total_count"] == 1
    assert data[0]["id"] == permit["id"]
