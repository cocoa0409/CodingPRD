"""Registration, catalog, state-machine lifecycle, listing, and RBAC.

PRD §3.1–§3.4, §3.6, §3.9 (lifecycle); §2.1 (RBAC); §2.3 (pagination); §2.5/§2.6 (errors).
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    is_valid_uuid, is_iso8601_timestamp, assert_applicant,
    create_applicant, create_resident_applicant,
    create_product, create_season, create_tag_product_for_season,
    create_pool, enter_draw, close_pool, issue_otc_license,
    submit_harvest, setup_resident_with_tag_license, setup_closed_pool_ready_to_draw,
    set_clock,
    create_applicant_payload, create_license_product_payload,
    create_residency_verification_payload, create_education_certificate_payload,
    create_draw_application_payload,
    make_applicant_headers, build_user_headers, NON_EXISTENT_UUID, TEST_USERS,
)

OFFICER = TEST_USERS["draw_officer_headers"]
AGENT = TEST_USERS["license_agent_headers"]


# ─── Entities: creation, defaults, validation, computed fields ─────────────
def test_applicant_creation_returns_defaults(api):
    """PRD §3.1: "On registration the system initializes the applicant's residency standing,
    held in `residency_status`, to `UNVERIFIED`; sets the hunter-education flag
    `education_certified` to false; and sets the accrued-preference counter `preference_points`
    to 0."

    Design: Corner/entities/applicant_creation_returns_defaults
    """
    res = api.create_applicant(
        create_applicant_payload(full_name="Jo", birth_date="1990-05-05",
                                 declared_state_code="MT"), OFFICER)
    applicant = validate_success(res, 201)
    assert_applicant(applicant)
    assert applicant["residency_status"] == "UNVERIFIED"
    assert applicant["preference_points"] == 0
    assert applicant["education_certified"] is False
    assert applicant["version"] == 1


def test_applicant_not_found_returns_404(api):
    """PRD §2.5: "The first identifier that does not resolve to an existing resource causes
    the request to be rejected with `ERR_NOT_FOUND` before any later reference is examined and
    before any business rule is evaluated."

    Design: Corner/entities/applicant_not_found_returns_404
    """
    res = api.get_applicant(NON_EXISTENT_UUID, OFFICER)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_applicant_missing_required_field_rejected(api):
    """PRD §3.1: "registers a person by supplying their `full_name`, their `birth_date` as an ISO
    8601 calendar date in `YYYY-MM-DD` form, and the `declared_state_code`".
    PRD §2.6: "Field-level request validation — required fields present, enum values legal,
    numeric fields within their declared bounds — is the lowest-priority check and yields
    `ERR_INVALID_REQUEST`".

    Design: Corner/entities/applicant_missing_required_field_returns_invalid_request
    """
    payload = create_applicant_payload(birth_date="1990-05-05", declared_state_code="MT")
    del payload["full_name"]
    res = api.create_applicant(payload, OFFICER)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_applicant_bonus_points_default_zero(api):
    """PRD §3.1: "The registration may optionally include `bonus_points`, an administratively
    granted integer that must be zero or greater and defaults to 0 when omitted."

    Design: Corner/entities/applicant_bonus_points_default_zero
    """
    res = api.create_applicant(
        create_applicant_payload(full_name="Jo", birth_date="1990-05-05",
                                 declared_state_code="MT"), OFFICER)
    applicant = validate_success(res, 201)
    assert applicant["bonus_points"] == 0


def test_applicant_system_fields_generated(api):
    """PRD §2.4: "The `id` is a server-minted UUID with no type prefix. The `created_at` field is
    an ISO 8601 UTC timestamp with three fractional digits, fixed at creation."

    Design: Corner/entities/applicant_system_fields_generated
    """
    res = api.create_applicant(
        create_applicant_payload(full_name="Jo", birth_date="1990-05-05",
                                 declared_state_code="MT"), OFFICER)
    applicant = validate_success(res, 201)
    assert is_valid_uuid(applicant["id"]), "id must be a UUID with no type prefix"
    assert is_iso8601_timestamp(applicant["created_at"]), "created_at must be ISO 8601 UTC"


def test_license_product_duplicate_sku_rejected(api):
    """PRD §3.3: "The `sku` must be unique among products that are currently `ACTIVE`; creating a
    product whose `sku` collides with an existing `ACTIVE` product is rejected with
    `ERR_DUPLICATE_SKU`."

    Design: Corner/entities/license_product_duplicate_sku_rejected
    """
    validate_success(api.create_license_product(
        create_license_product_payload(sku="STAMP-DUP", product_kind="STAMP",
                                        base_fee_cents=4500, residency_restriction="ANY"),
        OFFICER), 201)
    res = api.create_license_product(
        create_license_product_payload(sku="STAMP-DUP", product_kind="STAMP",
                                        base_fee_cents=5000, residency_restriction="ANY"),
        OFFICER)
    validate_error(res, "ERR_DUPLICATE_SKU", expected_status=409)


def test_license_product_invalid_enum_rejected(api):
    """PRD §3.3: "a `product_kind` that is one of `LICENSE`, `TAG`, or `STAMP`".
    PRD §2.6: "Field-level request validation — required fields present, enum values legal,
    numeric fields within their declared bounds — is the lowest-priority check and yields
    `ERR_INVALID_REQUEST`".

    Design: Corner/entities/license_product_invalid_enum_rejected
    """
    res = api.create_license_product(
        create_license_product_payload(sku="X-1", product_kind="PERMIT",
                                        base_fee_cents=4500, residency_restriction="ANY"),
        OFFICER)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_applicant_residency_computed_resident(api):
    """PRD §3.1: "On approval, the verification moves `PENDING → APPROVED` and the system computes `resulting_residency`: the result is `RESIDENT` when the `proof_state_code` matches the applicant's `declared_state_code` and `continuous_months` is at least the residency threshold of twelve continuous months, and is `NONRESIDENT` otherwise. The computed `resulting_residency` is then written onto the applicant as their new `residency_status".

    Design: Corner/entities/applicant_residency_computed_field_correct
    """
    applicant = validate_success(api.create_applicant(
        create_applicant_payload(full_name="Res", declared_state_code="MT"), OFFICER), 201)
    rv = validate_success(api.create_residency_verification(
        create_residency_verification_payload(applicant["id"], proof_state_code="MT",
                                               continuous_months=24), OFFICER), 201)
    approved = validate_success(api.approve_residency_verification(rv["id"], OFFICER), 200)
    assert approved["resulting_residency"] == "RESIDENT"
    refreshed = validate_success(api.get_applicant(applicant["id"], OFFICER), 200)
    assert refreshed["residency_status"] == "RESIDENT"


# ─── State machines ────────────────────────────────────────────────────────
def test_residency_verification_initial_state_pending(api):
    """PRD §3.1: "A new verification begins in `PENDING` status with its `resulting_residency` not yet determined."

    Design: Corner/state_machines/residency_verification_initial_state_pending
    """
    applicant = validate_success(api.create_applicant(
        create_applicant_payload(full_name="Res", declared_state_code="MT"), OFFICER), 201)
    rv = validate_success(api.create_residency_verification(
        create_residency_verification_payload(applicant["id"]), OFFICER), 201)
    assert rv["status"] == "PENDING"


def test_residency_verification_double_approve_invalid_state(api):
    """PRD §3.1: "Adjudication is defined only from the `PENDING` state; attempting it on an
    already-resolved verification is an `ERR_INVALID_STATE` conflict."

    Design: Corner/state_machines/residency_verification_double_approve_invalid_state
    """
    applicant = validate_success(api.create_applicant(
        create_applicant_payload(full_name="Res", declared_state_code="MT"), OFFICER), 201)
    rv = validate_success(api.create_residency_verification(
        create_residency_verification_payload(applicant["id"]), OFFICER), 201)
    validate_success(api.approve_residency_verification(rv["id"], OFFICER), 200)
    res = api.approve_residency_verification(rv["id"], OFFICER)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_season_open_from_closed_invalid_state(api):
    """PRD §3.4: "A season is created in `DRAFT`, is moved to `OPEN` by the officer (a transition `DRAFT → OPEN` defined only from `DRAFT`), and is later moved to `CLOSED` (a transition `OPEN → CLOSED` defined only from `OPEN`); attempting either out of order yields `ERR_INVALID_STATE`."

    Design: Corner/state_machines/season_open_from_closed_invalid_state
    """
    season = validate_success(api.create_species_season(
        {"species": "ELK", "season_open": "2026-09-01T00:00:00Z",
         "season_close": "2026-10-01T00:00:00Z", "bag_limit": 1}, OFFICER), 201)
    validate_success(api.open_species_season(season["id"], OFFICER), 200)
    validate_success(api.close_species_season(season["id"], OFFICER), 200)
    res = api.open_species_season(season["id"], OFFICER)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_education_certificate_verify_sets_applicant_flag(api):
    """PRD §3.2: "Verifying it moves the certificate `PENDING → VERIFIED`, sets the applicant's `education_certified` flag to true, and increments the applicant's `version`."

    Design: Corner/state_machines/education_certificate_verify_sets_applicant_flag
    """
    applicant = validate_success(api.create_applicant(
        create_applicant_payload(full_name="Edu", declared_state_code="MT"), OFFICER), 201)
    ec = validate_success(api.create_education_certificate(
        create_education_certificate_payload(applicant["id"]), OFFICER), 201)
    verified = validate_success(api.verify_education_certificate(ec["id"], OFFICER), 200)
    assert verified["status"] == "VERIFIED"
    refreshed = validate_success(api.get_applicant(applicant["id"], OFFICER), 200)
    assert refreshed["education_certified"] is True


def test_education_certificate_reject_leaves_flag_false(api):
    """PRD §3.2: "Rejecting it moves the certificate `PENDING → REJECTED` and leaves `education_certified` unchanged."

    Design: Corner/state_machines/education_certificate_reject_leaves_flag_false
    """
    applicant = validate_success(api.create_applicant(
        create_applicant_payload(full_name="Edu", declared_state_code="MT"), OFFICER), 201)
    ec = validate_success(api.create_education_certificate(
        create_education_certificate_payload(applicant["id"]), OFFICER), 201)
    rejected = validate_success(api.reject_education_certificate(ec["id"], OFFICER), 200)
    assert rejected["status"] == "REJECTED"
    refreshed = validate_success(api.get_applicant(applicant["id"], OFFICER), 200)
    assert refreshed["education_certified"] is False


def test_drawn_pool_close_entries_invalid_state(api):
    """PRD §3.4: "The pool advances `ACCEPTING → CLOSED` when the officer closes entries —
    defined only while the pool is `ACCEPTING` and only once the clock is at or past the pool's
    `entry_deadline` — and finally `CLOSED → DRAWN` when the draw is executed."

    Design: Corner/state_machines/terminal_drawn_pool_close_entries_invalid_state
    """
    season, product, pool, applicants, closed = setup_closed_pool_ready_to_draw(
        quota=1, num_entrants=1)
    from test_helpers import execute_pool_draw
    execute_pool_draw(pool["id"], closed["version"])  # pool now DRAWN
    res = api.close_entries_draw_pool(pool["id"], OFFICER)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_close_entries_before_deadline_invalid_state(api):
    """PRD §3.4: "The pool advances `ACCEPTING → CLOSED` when the officer closes entries — defined only while the pool is `ACCEPTING` and only once the clock is at or past the pool's `entry_deadline".

    Design: Corner/state_machines/close_entries_before_deadline_invalid_state
    """
    set_clock("2026-05-01T00:00:00Z")
    season = create_season(species="ELK", bag_limit=1, draw_required=True, open_it=True)
    product = create_tag_product_for_season(season["id"], sku="TAG-ELK")
    pool = create_pool(season["id"], product["id"], quota=1,
                       entry_deadline="2026-05-10T00:00:00Z")
    # Clock still before deadline.
    res = api.close_entries_draw_pool(pool["id"], OFFICER)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_withdraw_after_entries_closed_invalid_state(api):
    """PRD §3.6: "It is permitted only when the application is still `SUBMITTED` and the pool is
    still `ACCEPTING`; once entries have closed the application can no longer be withdrawn, and
    an out-of-state attempt yields `ERR_INVALID_STATE`."

    Design: Corner/state_machines/withdraw_after_entries_closed_invalid_state
    """
    set_clock("2026-05-01T00:00:00Z")
    season = create_season(species="ELK", bag_limit=1, draw_required=True, open_it=True)
    product = create_tag_product_for_season(season["id"], sku="TAG-ELK")
    pool = create_pool(season["id"], product["id"], quota=1,
                       entry_deadline="2026-05-10T00:00:00Z")
    applicant = create_applicant(full_name="A1")
    app = enter_draw(pool["id"], applicant["id"], as_officer=False)
    close_pool(pool["id"], "2026-05-11T00:00:00Z")  # pool now CLOSED

    res = api.withdraw_draw_application(app["id"], make_applicant_headers(applicant["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ─── Validations ──────────────────────────────────────────────────────────
def test_duplicate_draw_entry_rejected(api):
    """PRD §3.6: "an applicant may hold at most one application per pool that has not been
    withdrawn; a second entry by the same applicant into the same pool is rejected with
    `ERR_DUPLICATE_ENTRY`."

    Design: Corner/validations/duplicate_draw_entry_rejected
    """
    set_clock("2026-05-01T00:00:00Z")
    season = create_season(species="ELK", bag_limit=1, draw_required=True, open_it=True)
    product = create_tag_product_for_season(season["id"], sku="TAG-ELK")
    pool = create_pool(season["id"], product["id"], quota=1,
                       entry_deadline="2026-05-10T00:00:00Z")
    applicant = create_applicant(full_name="A1")
    enter_draw(pool["id"], applicant["id"], as_officer=False)

    res = api.create_draw_application(
        create_draw_application_payload(pool["id"], applicant["id"]),
        make_applicant_headers(applicant["id"]))
    validate_error(res, "ERR_DUPLICATE_ENTRY", expected_status=409)


# ─── Endpoints: listing ───────────────────────────────────────────────────
def test_list_applicants_pagination_envelope(api):
    """PRD §2.3: "Each list response carries `limit`, `offset`, `total_count`, and `has_more` in the
    `meta` object of the envelope, where `total_count` is the total number of matching resources
    before pagination and `has_more` indicates whether further pages remain."

    Design: Corner/endpoints/list_applicants_pagination_envelope
    """
    validate_success(api.create_applicant(
        create_applicant_payload(full_name="P1", declared_state_code="MT"), OFFICER), 201)
    validate_success(api.create_applicant(
        create_applicant_payload(full_name="P2", declared_state_code="CA"), OFFICER), 201)

    data, meta = validate_paginated(api.list_applicants(OFFICER))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


# ─── RBAC ──────────────────────────────────────────────────────────────────
def test_applicant_cannot_execute_draw(api):
    """PRD §4 (endpoint table): POST /draw-pools/{id}/execute-draw is authorized for
    DrawOfficer only.
    PRD §2.1: "A request that is well-authenticated but whose role is not permitted to perform
    the requested operation is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/applicant_cannot_execute_draw
    """
    season, product, pool, applicants, closed = setup_closed_pool_ready_to_draw(
        quota=1, num_entrants=1)
    applicant = applicants[0]
    res = api.execute_draw(
        pool["id"], {"expected_draw_pool_version": closed["version"]},
        make_applicant_headers(applicant["id"]))
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)


def test_license_agent_cannot_accept_harvest(api):
    """PRD §4 (endpoint table): POST /harvest-reports/{id}/accept is authorized for
    GameWarden only.
    PRD §2.1: "A request that is well-authenticated but whose role is not permitted to perform
    the requested operation is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/license_agent_cannot_accept_harvest
    """
    season, product, applicant, license_ = setup_resident_with_tag_license(
        bag_limit=2, clock="2026-09-15T00:00:00Z")
    report = submit_harvest(license_["id"], applicant["id"],
                            harvest_datetime="2026-09-15T08:00:00Z", quantity=1)
    res = api.accept_harvest_report(report["id"], AGENT)
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "A request that omits either header, or carries a malformed value, is
    rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    res = api.create_license_product(
        create_license_product_payload(sku="X-1", product_kind="STAMP",
                                        base_fee_cents=4500, residency_restriction="ANY"),
        headers={})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)
