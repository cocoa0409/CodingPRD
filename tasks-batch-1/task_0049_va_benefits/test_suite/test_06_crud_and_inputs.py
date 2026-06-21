"""Veteran/Claim/Condition/Dependent CRUD, defaults, computed fields, validation.

Corner queue: entities section, plus the validations/errors instances that probe
required fields, enum types, duplicate file numbers, and not-found semantics.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_veteran,
    create_claim,
    create_veteran_payload,
    create_claim_payload,
    unique_file_number,
)
from test_helpers import api_client  # noqa: F401

ADMIN = TEST_USERS["claims_admin_headers"]
RATER = TEST_USERS["rating_specialist_headers"]


# ─── Corner / entities ────────────────────────────────────────────────────

def test_create_veteran_returns_201_with_computed_fields(api):
    """PRD §3.1: "The award state, `award_status`, starts at `DRAFT`. The
    disability figures `combined_rating_pct` and `provisional_combined_rating_pct`
    both start at 0, and `monthly_compensation_cents` starts at 0. The
    vocational-rehabilitation balance `voc_rehab_entitlement_months` starts at 48
    months — the full Chapter 31 entitlement."
    PRD §3.10: "At least 1,095 days (thirty-six months) earns 100 percent."

    Design: Corner/entities/create_veteran_returns_201_with_computed_fields
    """
    payload = create_veteran_payload(
        full_name="Cornel Vet",
        file_number=unique_file_number("FN-CREATE"),
        total_active_duty_days=1095,
    )
    vet = validate_success(api.create_veteran(payload, ADMIN), 201)
    assert vet["gi_bill_tier_pct"] == 100
    assert vet["combined_rating_pct"] == 0
    assert vet["voc_rehab_entitlement_months"] == 48
    assert vet["award_status"] == "DRAFT"
    assert vet["version"] == 1


def test_get_veteran_returns_stored_entity(api):
    """PRD §2.4: "Each has an `id`, a unique server-minted UUID with no type
    prefix".
    PRD §3.10: "At least 365 days but fewer than 547 earns 60 percent".

    Design: Corner/entities/get_veteran_returns_stored_entity
    """
    fn = unique_file_number("FN-GET")
    created = create_veteran(total_active_duty_days=365, file_number=fn)
    got = validate_success(api.get_veteran(created["id"], ADMIN), 200)
    assert got["file_number"] == fn
    assert got["gi_bill_tier_pct"] == 60


def test_list_veterans_paginated_envelope(api):
    """PRD §2.3: "Paginated list responses include the following fields in the
    `meta` object of the response envelope: `limit`, `offset`, `total_count`, and
    `has_more`."

    Design: Corner/entities/list_veterans_paginated_envelope
    """
    create_veteran(total_active_duty_days=1095, file_number=unique_file_number("FN-L1"))
    create_veteran(total_active_duty_days=1095, file_number=unique_file_number("FN-L2"))
    data, meta = validate_paginated(
        api.list_veterans(ADMIN, params={"limit": 1, "offset": 0})
    )
    assert meta["total_count"] >= 2
    assert meta["has_more"] is True


def test_get_veteran_not_found(api):
    """PRD §2.4: "if it does not correspond to an existing resource the request
    fails with `ERR_NOT_FOUND`".

    Design: Corner/entities/get_veteran_not_found
    """
    res = api.get_veteran(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, "ERR_NOT_FOUND", 404)


def test_create_veteran_missing_required_field(api):
    """PRD §3.15: "Request well-formedness comes fourth: missing or mistyped body
    fields, enum values outside their declared sets, a `proposed_rating_pct` that
    is not a multiple of ten within 0 to 100, or non-positive credit hours all
    yield `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_veteran_missing_required_field
    """
    payload = {"full_name": "No FN", "total_active_duty_days": 1095}
    res = api.create_veteran(payload, ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST", 422)


def test_create_veteran_discharge_default_false(api):
    """PRD §3.1: "the boolean `discharged_for_service_disability` may also be
    supplied and is treated as `false` when omitted."
    PRD §3.10: "At least 730 days but fewer than 912 earns 80 percent."

    Design: Corner/entities/create_veteran_discharge_default_false
    """
    vet = create_veteran(
        total_active_duty_days=800, file_number=unique_file_number("FN-DEF")
    )
    assert vet["discharged_for_service_disability"] is False
    assert vet["gi_bill_tier_pct"] == 80, (
        "800 days with default discharge=false -> tier 80, not the disability 100"
    )


def test_combined_rating_computed_input_ignored(api):
    """PRD §2.7: "several of its fields are never written directly by a client —
    they are derived and refreshed by the server whenever an upstream fact
    changes. `combined_rating_pct`, `provisional_combined_rating_pct`,
    `gi_bill_tier_pct`, and `monthly_compensation_cents` are all computed fields
    on the veteran".
    PRD §3.1: "The disability figures `combined_rating_pct` and
    `provisional_combined_rating_pct` both start at 0".

    Design: Corner/entities/combined_rating_computed_input_ignored
    """
    payload = create_veteran_payload(
        file_number=unique_file_number("FN-IGN"), total_active_duty_days=1095
    )
    payload["combined_rating_pct"] = 90  # client-supplied computed field
    vet = validate_success(api.create_veteran(payload, ADMIN), 201)
    assert vet["combined_rating_pct"] == 0, (
        "client-supplied combined_rating_pct is ignored; starts at 0"
    )


def test_dependent_immutable_entity_no_version(api):
    """PRD §2.4: "A dependent record carries only an `id` and a `created_at`; it
    has neither an `updated_at` nor a `version` field."
    PRD §3.2: "A new dependent is created with `status` set to `ACTIVE`."

    Design: Corner/entities/dependent_immutable_entity_no_version
    """
    vet = create_veteran(
        total_active_duty_days=1095, file_number=unique_file_number("FN-DEPI")
    )
    dep = validate_success(
        api.add_dependent(vet["id"], {"relationship": "PARENT"}, ADMIN), 201
    )
    assert dep["status"] == "ACTIVE"
    assert "version" not in dep, "Dependent response must not carry a version field"


def test_condition_invalid_rating_enum(api):
    """PRD §3.3: "The `proposed_rating_pct` is the examiner's proposed schedular
    percentage and must be a multiple of ten between 0 and 100 inclusive; a value
    that is not a multiple of ten or falls outside that range is rejected with
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/condition_invalid_rating_enum
    """
    vet = create_veteran(
        total_active_duty_days=1095, file_number=unique_file_number("FN-ENUM")
    )
    claim = create_claim(vet["id"])
    res = api.add_condition(
        claim["id"],
        {"veteran_id": vet["id"], "diagnostic_code": "5260", "proposed_rating_pct": 35},
        RATER,
    )
    validate_error(res, "ERR_INVALID_REQUEST", 422)


def test_duplicate_file_number_rejected(api):
    """PRD §3.1: "The `file_number` is the veteran's unique VA file number and
    must be unique across all veterans — a create that reuses an existing file
    number is rejected with `ERR_DUPLICATE_FILE_NUMBER`."

    Design: Corner/entities/duplicate_file_number_rejected
    """
    fn = unique_file_number("FN-DUP")
    create_veteran(total_active_duty_days=1095, file_number=fn)
    res = api.create_veteran(
        create_veteran_payload(full_name="Dup2", file_number=fn, total_active_duty_days=1095),
        ADMIN,
    )
    validate_error(res, "ERR_DUPLICATE_FILE_NUMBER", 409)


# ─── Corner / validations and errors ──────────────────────────────────────

def test_invalid_enum_claim_type(api):
    """PRD §3.3: "the `claim_type` — one of `ORIGINAL`, `INCREASE`, or
    `SECONDARY`".
    PRD §3.15: "Request well-formedness comes fourth: missing or mistyped body
    fields, enum values outside their declared sets, a `proposed_rating_pct` that
    is not a multiple of ten within 0 to 100, or non-positive credit hours all
    yield `ERR_INVALID_REQUEST`."

    Design: Corner/validations/invalid_enum_claim_type
    """
    vet = create_veteran(
        total_active_duty_days=1095, file_number=unique_file_number("FN-BADENUM")
    )
    res = api.create_claim(
        create_claim_payload(vet["id"], claim_type="FOO"), ADMIN
    )
    validate_error(res, "ERR_INVALID_REQUEST", 422)


def test_not_found_error_distinct_from_invalid_request(api):
    """PRD §3.15: "Existence comes third: every resource named in the path or body
    is resolved left to right, and the first missing one yields `ERR_NOT_FOUND`."
    PRD §2.4: "This left-to-right existence sweep is the third validation gate
    overall and yields `ERR_NOT_FOUND` for the first missing referent".

    Design: Corner/errors/not_found_error_distinct_from_invalid_request
    """
    res = api.open_development(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, "ERR_NOT_FOUND", 404)


def test_list_claims_filtered_by_veteran(api):
    """PRD §3.5: "Claims may be fetched individually and listed with an optional
    filter on `veteran_id` and on `status`".

    Design: Corner/endpoints/list_claims_filtered_by_veteran
    """
    vet = create_veteran(
        total_active_duty_days=1095, file_number=unique_file_number("FN-LCLAIM")
    )
    create_claim(vet["id"], claim_type="ORIGINAL", received_date="2026-01-01T00:00:00Z")
    create_claim(vet["id"], claim_type="INCREASE", received_date="2026-02-01T00:00:00Z")
    data, meta = validate_paginated(
        api.list_claims(ADMIN, params={"veteran_id": vet["id"]})
    )
    assert meta["total_count"] == 2, (
        f"veteran has exactly 2 claims, got {meta['total_count']}"
    )
