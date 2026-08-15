"""Delegated inspection authority: closed windows, cooling-off (PRD §3.8)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_delegation,
    create_delegation,
    create_released_po,
    validate_error,
    validate_success,
)

CQR = TEST_USERS["customer_quality_rep"]

INSPECTOR = "insp-9"


def _released_po():
    return create_released_po(
        quantity=1, flowdown_clauses=["DELEGATED_INSPECTION_PERMITTED"]
    )


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / dia_closed_interval_overlap_and_cooling_off
# ---------------------------------------------------------------------------

def test_dia_closed_interval_touching_boundaries_conflict(api):
    """PRD §3.8: "Unlike the half-open special-process windows, a delegation
    window is closed: it covers `valid_from` through `valid_to`, both dates
    inclusive, and a `valid_to` earlier than `valid_from` is rejected with
    `ERR_INVALID_WINDOW`. Two `ACTIVE` delegations for the same `po_id` and
    `inspector_user_id` may not intersect — because both endpoints of the
    window are inclusive, touching boundaries count as overlap — and a
    conflicting grant is rejected with `ERR_DELEGATION_WINDOW_OVERLAP` (409)."

    Design: Difficulty/resource_temporal_overlap/dia_closed_interval_overlap_and_cooling_off
    """
    po = _released_po()["po"]
    first = create_delegation(
        po["id"], INSPECTOR, valid_from="2026-01-01", valid_to="2026-12-31"
    )
    assert_delegation(first)
    assert first["status"] == "ACTIVE"
    # The closed interval shares the endpoint 2026-12-31: touching is overlap.
    resp = api_client.create_delegation(
        {
            "po_id": po["id"],
            "inspector_user_id": INSPECTOR,
            "valid_from": "2026-12-31",
            "valid_to": "2027-06-30",
        },
        CQR,
    )
    validate_error(resp, ApiErrorId.ERR_DELEGATION_WINDOW_OVERLAP.value)


def test_dia_cooling_off_after_revocation(api):
    """PRD §3.8: "Revocation carries a tail: after a delegation is revoked, a
    re-grant to the same `po_id` and `inspector_user_id` whose `valid_from`
    falls earlier than thirty days after the `revoked_at` date is rejected
    with `ERR_DIA_COOLING_OFF` (409)."
    PRD §3.8: "The revocation stamps `revoked_at` with the current logical
    clock, and that timestamp anchors the thirty-day cooling-off rule above."

    Design: Difficulty/resource_temporal_overlap/dia_closed_interval_overlap_and_cooling_off
    """
    po = _released_po()["po"]
    first = create_delegation(
        po["id"], INSPECTOR, valid_from="2026-01-01", valid_to="2026-12-31"
    )
    # Revoke at the default logical clock 2026-08-01T00:00:00Z.
    revoked = validate_success(
        api_client.revoke_delegation(
            first["id"], {"reason": "customer withdrew delegation"}, CQR
        )
    )
    assert revoked["status"] == "REVOKED"
    assert revoked.get("revoked_at"), "revocation stamps revoked_at"

    # valid_from 2026-08-15 falls earlier than thirty days after 2026-08-01.
    resp = api_client.create_delegation(
        {
            "po_id": po["id"],
            "inspector_user_id": INSPECTOR,
            "valid_from": "2026-08-15",
            "valid_to": "2026-09-15",
        },
        CQR,
    )
    validate_error(resp, ApiErrorId.ERR_DIA_COOLING_OFF.value)

    # valid_from 2026-08-31 is exactly thirty days after the revocation date:
    # not earlier than the cooling-off boundary, so the grant is permitted.
    regrant = create_delegation(
        po["id"], INSPECTOR, valid_from="2026-08-31", valid_to="2026-12-31"
    )
    assert_delegation(regrant)
    assert regrant["status"] == "ACTIVE"
