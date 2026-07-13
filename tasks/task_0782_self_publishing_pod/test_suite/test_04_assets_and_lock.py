"""Asset upload/validation (spine width, page-count and spine tolerance checks)
and the content-lock cross-entity preconditions.

Translates difficulty instance
`cross_entity_state_dependency/format_lock_requires_interior_asset_validated`
plus corner instances from sections `calculations`, `validations`, and
`state_machines`.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_publisher_headers,
    create_cover_asset_payload, create_interior_asset_payload,
    create_publisher, create_title, create_print_format,
    upload_interior, upload_cover, validate_asset,
)

ADMIN = TEST_USERS["admin_headers"]


def test_cover_spine_width_computed_from_page_count(api):
    """PRD 3.3: "The required spine is the page count multiplied by the paper
    caliper, rounded half up to two decimal places. The caliper depends on
    paper_type: 0.0572 mm per page for WHITE, 0.0635 mm per page for CREAM, and
    0.0572 mm per page for COLOR."

    Design: Corner/calculations/cover_spine_width_computed_from_page_count
    """
    pub = create_publisher(api)
    title = create_title(api, pub["id"])
    fmt = create_print_format(api, pub["id"], title["id"], page_count=200)
    payload = create_cover_asset_payload(paper_type="WHITE", declared_spine_mm=25.0)
    data = validate_success(
        api.create_asset(fmt["id"], payload, make_publisher_headers(pub["id"])), 201
    )
    assert data["spine_width_mm"] == 11.44, \
        f"expected spine_width_mm 11.44 (200*0.0572), got {data['spine_width_mm']}"


def test_cover_spine_mismatch_moves_asset_to_rejected(api):
    """PRD 3.3: "if that difference exceeds 0.5 mm, the asset transitions
    PENDING -> REJECTED with rejection_reason set to ERR_SPINE_MISMATCH. Both
    ERR_PAGE_COUNT_TOO_LOW and ERR_SPINE_MISMATCH are surfaced as the asset's
    rejection_reason on a 200 validate response that records the rejection - they
    are not returned as HTTP error bodies."

    Design: Corner/calculations/cover_spine_mismatch_moves_asset_to_rejected
    """
    pub = create_publisher(api)
    title = create_title(api, pub["id"])
    fmt = create_print_format(api, pub["id"], title["id"], page_count=200)
    cover = upload_cover(api, pub["id"], fmt["id"], declared_spine_mm=25.0)
    data = validate_success(api.validate_asset(cover["id"], ADMIN), 200)
    assert data["status"] == "REJECTED"
    assert data["rejection_reason"] == "ERR_SPINE_MISMATCH", \
        f"expected ERR_SPINE_MISMATCH, got {data['rejection_reason']}"


def test_interior_page_count_too_low_rejected_on_validate(api):
    """PRD 3.3: "if the declared page count is below 24, the asset instead
    transitions PENDING -> REJECTED with rejection_reason set to
    ERR_PAGE_COUNT_TOO_LOW."

    Design: Corner/validations/interior_page_count_too_low_rejected_on_validate
    """
    pub = create_publisher(api)
    title = create_title(api, pub["id"])
    fmt = create_print_format(api, pub["id"], title["id"], page_count=10)
    interior = upload_interior(api, pub["id"], fmt["id"], declared_page_count=10)
    data = validate_success(api.validate_asset(interior["id"], ADMIN), 200)
    assert data["status"] == "REJECTED"
    assert data["rejection_reason"] == "ERR_PAGE_COUNT_TOO_LOW", \
        f"expected ERR_PAGE_COUNT_TOO_LOW, got {data['rejection_reason']}"


def test_validate_already_validated_asset_returns_invalid_state(api):
    """PRD 3.3: "Validation may only run while the asset is PENDING; attempting
    it in any other state yields ERR_ASSET_INVALID_STATE (HTTP 409)."

    Design: Corner/state_machines/validate_already_validated_asset_returns_invalid_state
    """
    pub = create_publisher(api)
    title = create_title(api, pub["id"])
    fmt = create_print_format(api, pub["id"], title["id"])
    interior = upload_interior(api, pub["id"], fmt["id"])
    validate_asset(api, interior["id"])  # first validate -> VALIDATED
    validate_error(api.validate_asset(interior["id"], ADMIN),
                   ApiErrorId.ERR_ASSET_INVALID_STATE)


def test_lock_with_pending_interior_rejected(api):
    """PRD 3.4: "Locking additionally requires that the format have a VALIDATED
    INTERIOR asset - if none exists, the lock is refused with
    ERR_MANUSCRIPT_NOT_VALIDATED (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/format_lock_requires_interior_asset_validated
    """
    pub = create_publisher(api)
    title = create_title(api, pub["id"])
    fmt = create_print_format(api, pub["id"], title["id"])
    upload_interior(api, pub["id"], fmt["id"])  # PENDING, not validated
    validate_error(
        api.lock_format(fmt["id"], make_publisher_headers(pub["id"])),
        ApiErrorId.ERR_MANUSCRIPT_NOT_VALIDATED,
    )


def test_lock_rejected_leaves_format_draft(api):
    """PRD 3.4: "Locking content advances a format DRAFT -> CONTENT_LOCKED."
    PRD 3.4: "Locking additionally requires that the format have a VALIDATED
    INTERIOR asset - if none exists, the lock is refused with
    ERR_MANUSCRIPT_NOT_VALIDATED (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/format_lock_requires_interior_asset_validated
    """
    pub = create_publisher(api)
    title = create_title(api, pub["id"])
    fmt = create_print_format(api, pub["id"], title["id"])
    upload_interior(api, pub["id"], fmt["id"])  # PENDING
    api.lock_format(fmt["id"], make_publisher_headers(pub["id"]))
    refetched = get_success_data(api.get_format(fmt["id"], make_publisher_headers(pub["id"])))
    assert refetched["status"] == "DRAFT", "a rejected lock must leave the format in DRAFT"


def test_lock_print_without_cover_returns_cover_not_approved(api):
    """PRD 3.4: "When the format is PRINT, locking further requires a VALIDATED
    COVER asset; a print format lacking a validated cover is refused with
    ERR_COVER_NOT_APPROVED (HTTP 409)."

    Design: Corner/validations/lock_print_without_cover_returns_cover_not_approved
    """
    pub = create_publisher(api)
    title = create_title(api, pub["id"])
    fmt = create_print_format(api, pub["id"], title["id"])
    interior = upload_interior(api, pub["id"], fmt["id"])
    validate_asset(api, interior["id"])  # interior VALIDATED, no cover
    validate_error(
        api.lock_format(fmt["id"], make_publisher_headers(pub["id"])),
        ApiErrorId.ERR_COVER_NOT_APPROVED,
    )


