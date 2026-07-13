"""Role-based access control, ownership checks, authentication, listing, and clock."""
from test_helpers import (
    validate_paginated, validate_error, ApiErrorId,
    reset_clock, new_fridge, new_donor, new_steward, new_need, new_shift, set_clock,
    setup_fridge_and_steward,
    make_admin_headers, make_member_headers, make_donor_headers, make_steward_headers,
    create_fridge_payload, create_offer_payload, complete_shift_payload,
)


def test_member_cannot_create_fridge(api):
    """PRD §2.1: "When the headers are present and valid but the role is not permitted
    to perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/member_cannot_create_fridge_returns_unauthorized
    """
    reset_clock(api)
    resp = api.create_fridge(create_fridge_payload(), make_member_headers())
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_donor_agent_cannot_post_offer_for_other_donor(api):
    """PRD §2.1: "When a donor agent posts a surplus offer, the donor identified in the
    request path must equal `X-User-ID`; a mismatch is rejected with
    `ERR_DONOR_MISMATCH`."

    Design: Corner/rbac/donoragent_cannot_offer_for_other_donor_returns_donor_mismatch
    """
    reset_clock(api)
    fridge = new_fridge(api, capacity_slots=5)
    donor_a = new_donor(api, name="A", donor_type="GROCER", contact="a@x.org")
    donor_b = new_donor(api, name="B", donor_type="RESTAURANT", contact="b@x.org")
    # Acting as donor A, posting under donor B's path.
    resp = api.create_offer(
        donor_b["id"],
        create_offer_payload(fridge["id"], description="surplus", estimated_quantity_kg=2.0),
        make_donor_headers(donor_a["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DONOR_MISMATCH.value)


def test_steward_cannot_complete_another_stewards_shift(api):
    """PRD §3.3: "when the actor is a `Steward`, the acting `X-User-ID` must equal the
    shift's `steward_id`, or the request fails with `ERR_STEWARD_NOT_ASSIGNED` (a
    `NetworkAdmin` may complete any shift)."

    Design: Corner/rbac/steward_cannot_complete_other_stewards_shift_returns_not_assigned
    """
    fridge, steward_a = setup_fridge_and_steward(api, capacity_slots=5)
    steward_b = new_steward(api, name="B", email="b@x.org")
    shift = new_shift(api, fridge["id"], steward_a["id"], kind="COVERAGE",
                      start_at="2026-03-01T09:00:00Z", end_at="2026-03-01T10:00:00Z")
    set_clock(api, "2026-03-01T09:30:00Z")
    resp = api.complete_shift(
        shift["id"], complete_shift_payload(), make_steward_headers(steward_b["id"])
    )
    validate_error(resp, ApiErrorId.ERR_STEWARD_NOT_ASSIGNED.value)


def test_request_without_headers_rejected_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying an unrecognized role, is
    rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/auth_missing_headers_returns_unauthenticated
    """
    reset_clock(api)
    fridge = new_fridge(api, capacity_slots=5)
    resp = api.get_fridge(fridge["id"], {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_needs_list_pagination_reports_total_and_has_more(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned ... Every
    list response includes `limit`, `offset`, `total_count`, and `has_more` inside the
    `meta` object of the envelope."

    Design: Corner/endpoints/needs_list_pagination_reports_total_and_has_more
    """
    reset_clock(api)
    fridge = new_fridge(api, capacity_slots=5)
    new_need(api, fridge["id"], item_description="rice", quantity_needed=3)
    new_need(api, fridge["id"], item_description="beans", quantity_needed=2)
    resp = api.list_needs(
        make_member_headers(), params={"fridge_id": fridge["id"], "limit": 1, "offset": 0}
    )
    data, meta = validate_paginated(resp)
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


def test_clock_cannot_move_backward(api):
    """PRD §2.6: "the new value must be greater than or equal to the current value, and
    an attempt to move it backward is rejected with `ERR_VALIDATION`."

    Design: Corner/validations/clock_backward_returns_validation
    """
    set_clock(api, "2026-03-10T00:00:00Z")
    resp = api.set_clock("2026-03-01T00:00:00Z", make_admin_headers())
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)
