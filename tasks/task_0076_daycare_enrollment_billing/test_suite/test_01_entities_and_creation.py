"""Entity creation, defaults, system fields, listing, and not-found behavior.

Translates queue-B corner instances from sections: entities, endpoints (listing),
consistency_model.
"""
from test_helpers import (
    api_client as _ac,  # noqa: F401
    validate_success, validate_error, validate_paginated,
    get_success_data, NON_EXISTENT_UUID, ApiErrorId,
    make_director_headers, make_parent_headers,
)
import test_helpers.fixtures as fx

DIRECTOR = make_director_headers()


def test_create_center_applies_late_pickup_defaults(api):
    """PRD §3.1: "late_pickup_grace_minutes ... (default 5, and never negative);
    late_pickup_fee_per_block_cents, the fine charged per started late block
    (default 1500 cents, never negative); and late_pickup_block_minutes, the size
    of one chargeable late block in minutes (default 15, and at least 1)."
    PRD §2.4: "a version, an integer that begins at its initial value".

    Design: Corner/entities/create_center_returns_201_with_defaults
    """
    resp = api.create_center({"name": "C", "cacfp_tier": "TIER_I"}, DIRECTOR)
    data = validate_success(resp, 201)
    assert data["late_pickup_grace_minutes"] == 5
    assert data["late_pickup_fee_per_block_cents"] == 1500
    assert data["late_pickup_block_minutes"] == 15
    assert data["version"] == 1


def test_get_center_not_found(api):
    """PRD §2.5: "the first identifier that does not resolve to an existing resource
    causes the request to be rejected with ERR_NOT_FOUND before any deeper lookup
    is attempted."

    Design: Corner/entities/get_center_not_found
    """
    resp = api.get_center(NON_EXISTENT_UUID, DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_classroom_missing_required_field_rejected(api):
    """PRD §2.6: "generic request-shape validation — malformed bodies, bad enums,
    out-of-range numbers — is the lowest-priority catch, surfacing as
    ERR_INVALID_REQUEST."
    PRD §3.1: "a licensed_capacity of at least 1".

    Design: Corner/entities/create_classroom_missing_required_field_rejected
    """
    center = fx.create_center()
    resp = api.create_classroom(center["id"], {
        "name": "T", "age_band": "TODDLER", "base_monthly_tuition_cents": 120000,
    }, DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_classroom_invalid_age_band_enum_rejected(api):
    """PRD §2.6: "generic request-shape validation — malformed bodies, bad enums,
    out-of-range numbers — is the lowest-priority catch, surfacing as
    ERR_INVALID_REQUEST."
    PRD §3.1: "an age_band of INFANT, TODDLER, or PRESCHOOL".

    Design: Corner/entities/create_classroom_invalid_enum_age_band_rejected
    """
    center = fx.create_center()
    resp = api.create_classroom(center["id"], {
        "name": "T", "age_band": "SCHOOLAGE", "licensed_capacity": 5,
        "base_monthly_tuition_cents": 120000,
    }, DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_child_sibling_group_defaults_to_self(api):
    """PRD §3.2: "if it is omitted at registration the system defaults it to the
    child's own id, making the child its own anchor."
    PRD §3.2: "a flag enrolls_in_cacfp ... (defaulting to true)."

    Design: Corner/entities/child_sibling_group_defaults_to_self
    """
    center = fx.create_center()
    family = fx.create_family(center["id"])
    resp = api.create_child({
        "family_id": family["id"], "full_name": "K", "birthdate": "2024-01-10",
    }, DIRECTOR)
    data = validate_success(resp, 201)
    assert data["sibling_group_id"] == data["id"]
    assert data["enrolls_in_cacfp"] is True


def test_classroom_status_open_and_count_zero_on_create(api):
    """PRD §3.1: "A freshly created classroom starts with an active_enrollment_count
    of 0 and a status of OPEN."

    Design: Corner/entities/classroom_status_field_system_generated
    """
    center = fx.create_center()
    resp = api.create_classroom(center["id"], {
        "name": "T", "age_band": "TODDLER", "licensed_capacity": 5,
        "base_monthly_tuition_cents": 120000,
    }, DIRECTOR)
    data = validate_success(resp, 201)
    assert data["status"] == "OPEN"
    assert data["active_enrollment_count"] == 0


def test_list_classrooms_paginated_envelope(api):
    """PRD §2.3: "Every list response carries limit, offset, total_count, and
    has_more in the meta object of the envelope."

    Design: Corner/endpoints/list_classrooms_paginated_envelope
    """
    center = fx.create_center()
    fx.create_classroom(center["id"])
    resp = api.list_classrooms(center["id"], DIRECTOR)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


def test_activate_response_carries_priced_tuition_immediately(api):
    """PRD §3.4: "the enrollment's monthly_net_tuition_cents is computed".
    PRD §3.5: "the post-subsidy amount is the locked base tuition multiplied by
    the locked parent-share percentage divided by 100, rounded half up to a whole
    cent."

    Design: Corner/consistency_model/activate_response_reflects_priced_tuition_immediately
    """
    center, classroom, family = fx.setup_center_classroom_family(
        classroom_overrides={"base_monthly_tuition_cents": 120000})
    child, enrollment = fx.create_offered_enrollment(classroom, family)
    fx.accept_enrollment(enrollment, family)
    resp = api.activate_enrollment(enrollment["id"], DIRECTOR)
    data = validate_success(resp, 200)
    assert data["status"] == "ACTIVE"
    assert data["monthly_net_tuition_cents"] == 120000
