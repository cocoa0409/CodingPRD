"""Entity CRUD corners: creation, retrieval, listing/pagination, not-found,
required-field, declared defaults, computed fields, system fields, type/enum
constraints, append-only immutability, and FK integrity.

Corner queue: entities section.
"""
from test_helpers import (
    UNUSED_UUID,
    UNUSED_UUID_2,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_applicant_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx


# ════════════════════════════════════════════════════════════════════════
# Corner/entities/create_applicant_returns_201_with_all_fields
# ════════════════════════════════════════════════════════════════════════
def test_create_applicant_returns_201_with_all_fields(api, applicant_headers):
    """PRD §3.1: "An applicant is registered by supplying their full_legal_name ...,
    their date_of_birth ..., and a contact email". PRD §3.1: total_fees_paid_cents is
    "a conserved ledger described in Section 3.5, defaulting to 0". PRD §2.4: version
    "begins at its initial value".

    Design: Corner/entities/create_applicant_returns_201_with_all_fields
    """
    fx.set_clock("2026-06-01T10:00:00Z")
    res = api.create_applicant({"full_legal_name": "Casey Adult", "date_of_birth": "1990-01-01",
                                "email": fx.unique_email("casey")}, applicant_headers)
    applicant = validate_success(res, 201)
    assert applicant["full_legal_name"] == "Casey Adult"
    assert applicant["version"] == 1
    assert applicant["total_fees_paid_cents"] == 0
    assert applicant["is_minor"] is False


# ════════════════════════════════════════════════════════════════════════
# Corner/entities/get_application_returns_stored_entity
# ════════════════════════════════════════════════════════════════════════
def test_get_application_returns_stored_entity(api):
    """PRD §3.2: "The application begins with status equal to DRAFT." PRD §3.2: the
    name-change sub-status "begins at NONE." PRD §3.2: the applicant supplies "the
    applicant_id of the primary applicant".

    Design: Corner/entities/get_application_returns_stored_entity
    """
    applicant = fx.create_applicant()
    application = fx.create_application(applicant["id"], application_type="NEW", product_type="BOOK")
    fetched = validate_success(
        api.get_application(application["id"], make_applicant_headers(applicant["id"])), 200)
    assert fetched["status"] == "DRAFT"
    assert fetched["name_change_status"] == "NONE"
    assert fetched["applicant_id"] == applicant["id"]


# ════════════════════════════════════════════════════════════════════════
# Corner/entities/list_applications_filter_by_status_paginated
# ════════════════════════════════════════════════════════════════════════
def test_list_applications_filter_by_status_paginated(api):
    """PRD §4: "List applications; filter by applicant_id, status". PRD §2.3:
    list responses "include the following fields in the meta object ...: limit,
    offset, total_count, and has_more."

    Design: Corner/entities/list_applications_filter_by_status_paginated
    """
    applicant = fx.create_applicant()
    appl_id = applicant["id"]
    fx.create_application(appl_id, application_type="NEW", product_type="BOOK")
    fx.create_application(appl_id, application_type="NEW", product_type="CARD")

    data, meta = validate_paginated(api.list_applications(
        make_applicant_headers(appl_id),
        params={"applicant_id": appl_id, "status": "DRAFT", "limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


# ════════════════════════════════════════════════════════════════════════
# Corner/entities/get_application_nonexistent_id_returns_not_found
# ════════════════════════════════════════════════════════════════════════
def test_get_application_nonexistent_id_returns_not_found(api):
    """PRD §2.8: "The system validates path identifiers strictly left-to-right and
    rejects the request with ERR_NOT_FOUND (HTTP 404) at the first identifier in the
    path that does not correspond to an existing resource".

    Design: Corner/entities/get_application_nonexistent_id_returns_not_found
    """
    applicant = fx.create_applicant()
    res = api.get_application(UNUSED_UUID, make_applicant_headers(applicant["id"]))
    validate_error(res, "ERR_NOT_FOUND")


# ════════════════════════════════════════════════════════════════════════
# Corner/entities/create_application_missing_required_application_type
# ════════════════════════════════════════════════════════════════════════
def test_create_application_missing_application_type_rejected(api):
    """PRD §2.9: "Request well-formedness — body field types and enum membership are
    valid and required fields are present; otherwise ERR_INVALID_REQUEST." PRD §3.2
    names application_type as a required selector with no default.

    Design: Corner/entities/create_application_missing_required_application_type
    """
    applicant = fx.create_applicant()
    res = api.create_application({"applicant_id": applicant["id"], "product_type": "BOOK",
                                  "service_level": "ROUTINE"},
                                 make_applicant_headers(applicant["id"]))
    validate_error(res, "ERR_INVALID_REQUEST")


# ════════════════════════════════════════════════════════════════════════
# Corner/entities/create_application_default_service_level_routine
# ════════════════════════════════════════════════════════════════════════
def test_create_application_applies_default_service_level_and_name_change(api):
    """PRD §3.2: "The service_level is either ROUTINE or EXPEDITE and defaults to
    ROUTINE." PRD §3.2: "The name_change_requested field (defaulting to false)".

    Design: Corner/entities/create_application_default_service_level_routine
    """
    applicant = fx.create_applicant()
    res = api.create_application({"applicant_id": applicant["id"], "application_type": "NEW",
                                  "product_type": "BOOK"},
                                 make_applicant_headers(applicant["id"]))
    application = validate_success(res, 201)
    assert application["service_level"] == "ROUTINE"
    assert application["name_change_requested"] is False


# ════════════════════════════════════════════════════════════════════════
# Corner/entities/applicant_is_minor_computed_true_under_16
# ════════════════════════════════════════════════════════════════════════
def test_applicant_is_minor_true_under_16(api, applicant_headers):
    """PRD §3.1: "an applicant is a minor when the difference between today's date
    (from the clock) and their date_of_birth is strictly less than 16 years — that
    is, the applicant has not yet reached their sixteenth birthday."

    Design: Corner/entities/applicant_is_minor_computed_true_under_16
    """
    fx.set_clock("2026-06-01T10:00:00Z")
    res = api.create_applicant({"full_legal_name": "Kid", "date_of_birth": "2015-01-01",
                                "email": fx.unique_email("kid")}, applicant_headers)
    applicant = validate_success(res, 201)
    assert applicant["is_minor"] is True


# ════════════════════════════════════════════════════════════════════════
# Corner/entities/applicant_is_minor_computed_false_exactly_16
# ════════════════════════════════════════════════════════════════════════
def test_applicant_is_minor_false_exactly_16(api, applicant_headers):
    """PRD §3.1: "an applicant is a minor when the difference between today's date
    (from the clock) and their date_of_birth is strictly less than 16 years". Born
    2010-06-01 at clock 2026-06-01 is exactly 16 years, so is_minor is false.

    Design: Corner/entities/applicant_is_minor_computed_false_exactly_16
    """
    fx.set_clock("2026-06-01T10:00:00Z")
    res = api.create_applicant({"full_legal_name": "Sixteen", "date_of_birth": "2010-06-01",
                                "email": fx.unique_email("sixteen")}, applicant_headers)
    applicant = validate_success(res, 201)
    assert applicant["is_minor"] is False


# ════════════════════════════════════════════════════════════════════════
# Corner/entities/system_fields_id_and_version_server_minted_ignored_on_input
# ════════════════════════════════════════════════════════════════════════
def test_system_fields_server_minted(api, applicant_headers):
    """PRD §2.4: "Every such resource exposes an id (a server-minted UUID with no
    type prefix), a created_at (an ISO 8601 UTC timestamp ...), ... and a version (an
    integer that begins at its initial value and increments by one on every mutation
    of that resource)."

    Design: Corner/entities/system_fields_id_and_version_server_minted_ignored_on_input
    """
    res = api.create_applicant({"full_legal_name": "Sys", "date_of_birth": "1990-01-01",
                                "email": fx.unique_email("sys"),
                                "id": UNUSED_UUID, "version": 99}, applicant_headers)
    applicant = validate_success(res, 201)
    assert applicant["version"] == 1
    assert is_valid_uuid(applicant["id"])
    assert applicant["id"] != UNUSED_UUID  # the server mints its own id
    assert is_iso8601_timestamp(applicant["created_at"])


# ════════════════════════════════════════════════════════════════════════
# Corner/entities/create_application_invalid_enum_application_type
# ════════════════════════════════════════════════════════════════════════
def test_create_application_invalid_enum_application_type(api):
    """PRD §2.9: "body field types and enum membership are valid ...; otherwise
    ERR_INVALID_REQUEST." PRD §3.2: "The application_type is one of NEW, RENEWAL, or
    MINOR".

    Design: Corner/entities/create_application_invalid_enum_application_type
    """
    applicant = fx.create_applicant()
    res = api.create_application({"applicant_id": applicant["id"], "application_type": "PASSPORT",
                                  "product_type": "BOOK", "service_level": "ROUTINE"},
                                 make_applicant_headers(applicant["id"]))
    validate_error(res, "ERR_INVALID_REQUEST")


# ════════════════════════════════════════════════════════════════════════
# Corner/entities/photo_nonpositive_dimension_rejected
# ════════════════════════════════════════════════════════════════════════
def test_photo_nonpositive_dimension_rejected(api):
    """PRD §3.3: "Both pixel dimensions must be greater than 0 and ... a non-positive
    dimension [is rejected] as ERR_INVALID_REQUEST".

    Design: Corner/entities/photo_nonpositive_dimension_rejected
    """
    applicant = fx.create_applicant()
    application = fx.create_application(applicant["id"], application_type="NEW", product_type="BOOK")
    res = api.create_photo(application["id"], {
        "width_px": 0, "height_px": 600, "head_height_fraction": 0.60,
        "background_is_white": True}, make_applicant_headers(applicant["id"]))
    validate_error(res, "ERR_INVALID_REQUEST")


# ════════════════════════════════════════════════════════════════════════
# Corner/entities/photo_head_fraction_out_of_open_interval_validation_error
# ════════════════════════════════════════════════════════════════════════
def test_photo_head_fraction_out_of_open_interval_rejected(api):
    """PRD §3.3: "head_height_fraction must be strictly between 0 and 1 (any value
    not strictly inside the open interval from 0 to 1 ... is rejected — ... an
    out-of-(0,1) fraction as ERR_VALIDATION)."

    Design: Corner/entities/photo_head_fraction_out_of_open_interval_validation_error
    """
    applicant = fx.create_applicant()
    application = fx.create_application(applicant["id"], application_type="NEW", product_type="BOOK")
    res = api.create_photo(application["id"], {
        "width_px": 600, "height_px": 600, "head_height_fraction": 1.5,
        "background_is_white": True}, make_applicant_headers(applicant["id"]))
    validate_error(res, "ERR_VALIDATION")


# ════════════════════════════════════════════════════════════════════════
# Corner/entities/photo_immutable_no_version_field
# ════════════════════════════════════════════════════════════════════════
def test_photo_has_no_version_field(api):
    """PRD §2.4: the Photo and ApplicationStatusEvent "carry only id and created_at —
    they have neither an updated_at nor a version field, because they are immutable
    append-only records once written."

    Design: Corner/entities/photo_immutable_no_version_field
    """
    applicant = fx.create_applicant()
    application = fx.create_application(applicant["id"], application_type="NEW", product_type="BOOK")
    photo = validate_success(api.create_photo(application["id"], {
        "width_px": 600, "height_px": 600, "head_height_fraction": 0.60,
        "background_is_white": True}, make_applicant_headers(applicant["id"])), 201)
    assert "version" not in photo
    assert "updated_at" not in photo
    assert photo["validation_result"] == "PASS"


# ════════════════════════════════════════════════════════════════════════
# Corner/entities/create_application_fk_applicant_not_found
# ════════════════════════════════════════════════════════════════════════
def test_create_application_fk_applicant_not_found(api):
    """PRD §2.8: "when a request body carries a foreign-key reference — applicant_id,
    application_id, facility_id, counter_id, adjudicator_id, and the like — and that
    reference points to a resource that does not exist, the request is rejected with
    ERR_FK_NOT_FOUND (HTTP 422)."

    Design: Corner/entities/create_application_fk_applicant_not_found
    """
    applicant = fx.create_applicant()
    res = api.create_application({"applicant_id": UNUSED_UUID_2, "application_type": "NEW",
                                  "product_type": "BOOK", "service_level": "ROUTINE"},
                                 make_applicant_headers(applicant["id"]))
    validate_error(res, "ERR_FK_NOT_FOUND")


# ════════════════════════════════════════════════════════════════════════
# Corner/entities/book_appointment_fk_counter_not_found
# ════════════════════════════════════════════════════════════════════════
def test_book_appointment_fk_counter_not_found(api):
    """PRD §2.8: a body foreign-key — including counter_id — that "points to a
    resource that does not exist" is rejected with "ERR_FK_NOT_FOUND (HTTP 422)."

    Design: Corner/entities/book_appointment_fk_counter_not_found
    """
    ctx = fx.submitted_application(application_type="NEW", product_type="BOOK")
    appl_id = ctx["applicant"]["id"]
    app_id = ctx["application"]["id"]
    version = fx.current_version(app_id, appl_id)
    res = api.create_appointment({
        "application_id": app_id, "resource_kind": "URGENT_TRAVEL_COUNTER",
        "counter_id": UNUSED_UUID_2, "start_utc": "2026-06-09T09:00:00Z",
        "end_utc": "2026-06-09T09:30:00Z", "expected_application_version": version,
    }, make_applicant_headers(appl_id))
    validate_error(res, "ERR_FK_NOT_FOUND")
