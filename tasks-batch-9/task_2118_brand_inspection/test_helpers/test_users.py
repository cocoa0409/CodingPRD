"""Pre-built role headers for every role the board recognises (PRD §2.1).

Two roles are backed by a persisted entity: a `LivestockOwner`'s `X-User-ID` is
the `id` of the acting `Owner` row and a `FieldInspector`'s `X-User-ID` is the
`id` of the acting `Inspector` row. Any ownership-gated call therefore MUST use
the per-instance builder with the real entity id; the shared constants below are
only safe for calls that never reach the ownership rung (missing-resource and
malformed-payload probes, and calls by the four opaque roles).
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    BOARD_ADMIN_ID,
    EXAMINER_ID,
    FEE_ADMIN_ID,
    INVESTIGATOR_ID,
    RECORDER_ID,
)

TEST_USERS = {
    # Opaque roles — the shared constant is the canonical form.
    "board_admin_headers": build_user_headers(BOARD_ADMIN_ID, "BoardAdmin"),
    "brand_recorder_headers": build_user_headers(EXAMINER_ID, "BrandRecorder"),
    "second_brand_recorder_headers": build_user_headers(RECORDER_ID, "BrandRecorder"),
    "fee_administrator_headers": build_user_headers(FEE_ADMIN_ID, "FeeAdministrator"),
    "theft_investigator_headers": build_user_headers(
        INVESTIGATOR_ID, "TheftInvestigator"
    ),
    # Entity-backed roles — fallback for non-ownership probes only.
    "livestock_owner_headers": build_user_headers("test-owner-1", "LivestockOwner"),
    "field_inspector_headers": build_user_headers("test-inspector-1", "FieldInspector"),
}


def make_livestock_owner_headers(owner_id: str) -> dict:
    """Headers for a `LivestockOwner`. Pass the real `Owner.id` — ownership checks
    compare the resource's owner-side foreign key to `X-User-ID`."""
    return build_user_headers(owner_id, "LivestockOwner")


def make_field_inspector_headers(inspector_id: str) -> dict:
    """Headers for a `FieldInspector`. Pass the real `Inspector.id` — ownership
    checks compare the order's `inspector_id` to `X-User-ID`."""
    return build_user_headers(inspector_id, "FieldInspector")


def make_brand_recorder_headers(operator_id: str) -> dict:
    """Headers for a `BrandRecorder` operator. The identifier is opaque, but the
    board separates the officer who examines a filing from the one who records it."""
    return build_user_headers(operator_id, "BrandRecorder")


def make_fee_administrator_headers(operator_id: str) -> dict:
    """Headers for a `FeeAdministrator` operator (opaque identity)."""
    return build_user_headers(operator_id, "FeeAdministrator")


def make_theft_investigator_headers(operator_id: str) -> dict:
    """Headers for a `TheftInvestigator` operator (opaque identity)."""
    return build_user_headers(operator_id, "TheftInvestigator")


def make_board_admin_headers(operator_id: str) -> dict:
    """Headers for a `BoardAdmin` operator (opaque identity)."""
    return build_user_headers(operator_id, "BoardAdmin")
