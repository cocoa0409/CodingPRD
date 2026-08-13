"""Panel cell creation, panelist registration/enrollment, OCC target adjust,
version-on-mutation ledger semantics."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS, create_cell_payload, create_panelist_payload,
    create_cell, create_panelist,
)

PM = TEST_USERS["panel_manager"]
DA = TEST_USERS["data_analyst"]


def test_cell_create_defaults(api):
    """PRD §3.1: "A new cell starts with `reserved_count` 0 and `active_count` 0; its
    `status` follows the derivation rule of §2.6, so a cell created with `target_size`
    0 begins `SATURATED` and any other new cell begins `OPEN`."

    Design: Corner/entities/corner_cell_create_defaults
    """
    resp = api.create_panel_cell(
        create_cell_payload(age_band="AGE_45_64", district="D3",
                            tenure_bucket="OWNER", target_size=7), PM)
    data = validate_success(resp, 201)
    assert data["status"] == "OPEN"
    assert data["reserved_count"] == 0
    assert data["active_count"] == 0
    assert data["version"] == 1


def test_panelist_create_defaults(api):
    """PRD §3.2: "an optional `preferred_locale` that defaults to `en`" and
    "New registrations enter as `APPLICANT` with `missed_streak` 0 and
    `last_contacted_at` null, since the system has never contacted them."

    Design: Corner/entities/corner_panelist_create_defaults
    """
    payload = create_panelist_payload(age_band="AGE_65_PLUS", district="D9",
                                      tenure_bucket="OWNER")
    del payload["preferred_locale"]  # exercise the default
    resp = api.create_panelist(payload, PM)
    data = validate_success(resp, 201)
    assert data["preferred_locale"] == "en"
    assert data["status"] == "APPLICANT"
    assert data["missed_streak"] == 0
    assert data["last_contacted_at"] is None


def test_panelist_enroll_resolves_home_cell(api):
    """PRD §3.2: "Otherwise the panelist's `home_cell_id` is resolved to that cell,
    the panelist moves `APPLICANT` → `ACTIVE`, the cell's `active_count` increases
    by one, its status re-derives, and its `version` increments."

    Design: Corner/entities/corner_panelist_enroll_resolves_home_cell
    """
    cell = create_cell(target_size=2, age_band="AGE_30_44", district="D2",
                       tenure_bucket="OWNER")
    panelist = create_panelist(age_band="AGE_30_44", district="D2", tenure_bucket="OWNER")
    resp = api.enroll_panelist(panelist["id"], PM)
    data = validate_success(resp, 200)
    assert data["home_cell_id"] == cell["id"]
    assert data["status"] == "ACTIVE"
    cell_after = validate_success(api.get_panel_cell(cell["id"], PM))
    assert cell_after["active_count"] == 1


def test_wave_create_derives_pool(api):
    """PRD §3.4: "A new wave is `DRAFT`; its pool begins entirely uncommitted, with
    `incentive_pool_available_cents` equal to the total and
    `incentive_pool_reserved_cents` and `incentive_pool_paid_cents` at 0, and
    `invited_count` and `completed_count` start at 0."

    Design: Corner/entities/corner_wave_create_derives_pool
    """
    from test_helpers import create_locked_instrument, create_wave
    instr = create_locked_instrument()
    wave = create_wave(instr["id"], wave_code="W9",
                       incentive_pool_total_cents=42000, base_incentive_cents=500)
    assert wave["incentive_pool_available_cents"] == 42000
    assert wave["incentive_pool_reserved_cents"] == 0
    assert wave["incentive_pool_paid_cents"] == 0
    assert wave["invited_count"] == 0
    assert wave["completed_count"] == 0
    assert wave["status"] == "DRAFT"


def test_cell_create_extra_system_fields_input_ignored(api):
    """PRD §3.1: "A new cell starts with `reserved_count` 0 and `active_count` 0; its
    `status` follows the derivation rule of §2.6, so a cell created with
    `target_size` 0 begins `SATURATED` and any other new cell begins `OPEN`." and
    PRD §2.6: "A cell's `status` is never set by clients ..."

    Design: Corner/entities/corner_cell_create_extra_system_fields_input_ignored
    """
    payload = create_cell_payload(age_band="AGE_18_29", district="D1",
                                  tenure_bucket="RENTER", target_size=3)
    # Client-supplied system fields must not override the server's derivations.
    payload.update({"status": "SATURATED", "reserved_count": 99, "version": 42})
    resp = api.create_panel_cell(payload, PM)
    data = validate_success(resp, 201)
    assert data["status"] == "OPEN"
    assert data["reserved_count"] == 0
    assert data["version"] == 1


def test_get_wave_not_found_returns_404(api):
    """PRD §2.8: "Failures surface as the resource-specific not-found errors:
    `ERR_PANEL_CELL_NOT_FOUND`, `ERR_PANELIST_NOT_FOUND`, ..., `ERR_WAVE_NOT_FOUND`,
    ... (all HTTP 404)."

    Design: Corner/entities/corner_get_wave_not_found_returns_404
    """
    resp = api.get_wave("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", PM)
    err = validate_error(resp, ApiErrorId.ERR_WAVE_NOT_FOUND)
    assert err["error_id"] == "ERR_WAVE_NOT_FOUND"


def test_invalid_enum_age_band_returns_400(api):
    """PRD §2.8: "Missing required fields, wrong types, enum values outside their
    declared sets, and range violations ... all fail as `ERR_INVALID_REQUEST`
    (HTTP 400)."

    Design: Corner/entities/corner_invalid_enum_age_band_returns_400
    """
    resp = api.create_panelist(
        create_panelist_payload(age_band="TEEN", district="D1", tenure_bucket="RENTER"),
        PM)
    err = validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    assert err["error_id"] == "ERR_INVALID_REQUEST"


def test_stale_cell_version_returns_412(api):
    """PRD §3.1: "the adjust call must carry `expected_cell_version` under the OCC
    rule of §2.7 and fails with `ERR_STALE_CELL_VERSION` when the client's last
    observed version no longer matches."

    Design: Corner/validations/corner_stale_cell_version_returns_412
    """
    cell = create_cell(target_size=5)
    cv1 = cell["version"]
    first = api.adjust_cell_target(
        cell["id"], {"target_size": 8, "expected_cell_version": cv1}, PM)
    data = validate_success(first, 200)
    assert data["version"] == 2
    second = api.adjust_cell_target(
        cell["id"], {"target_size": 9, "expected_cell_version": cv1}, PM)
    err = validate_error(second, ApiErrorId.ERR_STALE_CELL_VERSION)
    assert err["error_id"] == "ERR_STALE_CELL_VERSION"
    final = validate_success(api.get_panel_cell(cell["id"], PM))
    assert final["target_size"] == 8


def test_version_increments_on_every_mutation(api):
    """PRD §2.4: "`version` (integer): a system-managed integer that increments with
    every mutation to the resource, used for optimistic concurrency control." and
    "when a derived counter on a cell or wave moves — a reservation changing a
    cell's `reserved_count`, ... — the owning resource's `updated_at` refreshes and
    its `version` increments exactly as if a client had edited it."

    Design: Corner/complexity_layers/corner_version_increments_on_every_mutation
    """
    cell = create_cell(target_size=5)
    assert cell["version"] == 1
    adjusted = validate_success(api.adjust_cell_target(
        cell["id"], {"target_size": 6, "expected_cell_version": cell["version"]}, PM), 200)
    assert adjusted["version"] == 2
    panelist = create_panelist()
    validate_success(api.enroll_panelist(panelist["id"], PM), 200)
    after = validate_success(api.get_panel_cell(cell["id"], PM))
    assert after["version"] == 3
    assert after["active_count"] == 1


def test_reactivate_active_panelist_returns_409(api):
    """PRD §3.2: "Reactivation requires the panelist to currently be `LAPSED` —
    anything else fails with `ERR_PANELIST_NOT_LAPSED` — and requires that no
    `ACTIVE` privacy hold exists for them, else `ERR_PRIVACY_HOLD_ACTIVE`."

    Design: Corner/state_machines/corner_reactivate_active_panelist_returns_409
    """
    cell = create_cell(target_size=5)
    panelist = create_panelist()
    enrolled = validate_success(api.enroll_panelist(panelist["id"], PM), 200)
    assert enrolled["status"] == "ACTIVE"
    err = validate_error(api.reactivate_panelist(panelist["id"], PM),
                         ApiErrorId.ERR_PANELIST_NOT_LAPSED)
    assert err["error_id"] == "ERR_PANELIST_NOT_LAPSED"
    after = validate_success(api.get_panelist(panelist["id"], PM), 200)
    assert after["status"] == "ACTIVE"


def test_enroll_into_saturated_cell_returns_409(api):
    """PRD §3.2: "When the matching cell's `active_count` has already reached its
    `target_size`, enrollment fails with `ERR_CELL_SATURATED`." and PRD §2.6: "A
    cell's `status` is never set by clients: it is `OPEN` while `active_count` is
    below `target_size` and `SATURATED` once `active_count` reaches or exceeds
    `target_size` ..."

    Design: Corner/validations/corner_enroll_into_saturated_cell_returns_409
    """
    cell = create_cell(target_size=1)
    p1 = create_panelist()
    p2 = create_panelist()
    validate_success(api.enroll_panelist(p1["id"], PM), 200)
    err = validate_error(api.enroll_panelist(p2["id"], PM),
                         ApiErrorId.ERR_CELL_SATURATED)
    assert err["error_id"] == "ERR_CELL_SATURATED"
    cell_after = validate_success(api.get_panel_cell(cell["id"], PM), 200)
    assert cell_after["status"] == "SATURATED"
    p2_after = validate_success(api.get_panelist(p2["id"], PM), 200)
    assert p2_after["status"] == "APPLICANT"


def test_not_found_family_returns_404(api):
    """PRD §2.8: "Failures surface as the resource-specific not-found errors:
    `ERR_PANEL_CELL_NOT_FOUND`, `ERR_PANELIST_NOT_FOUND`, `ERR_INSTRUMENT_NOT_FOUND`,
    ... (all HTTP 404)."

    Design: Corner/errors/corner_not_found_family_returns_404
    """
    ghost = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
    e1 = validate_error(api.get_panelist(ghost, PM), ApiErrorId.ERR_PANELIST_NOT_FOUND)
    assert e1["error_id"] == "ERR_PANELIST_NOT_FOUND"
    e2 = validate_error(api.get_instrument(ghost, TEST_USERS["survey_designer"]),
                        ApiErrorId.ERR_INSTRUMENT_NOT_FOUND)
    assert e2["error_id"] == "ERR_INSTRUMENT_NOT_FOUND"
    e3 = validate_error(api.get_publication(ghost, TEST_USERS["privacy_officer"]),
                        ApiErrorId.ERR_PUBLICATION_NOT_FOUND)
    assert e3["error_id"] == "ERR_PUBLICATION_NOT_FOUND"
    e4 = validate_error(api.get_privacy_hold(ghost, TEST_USERS["privacy_officer"]),
                        ApiErrorId.ERR_PRIVACY_HOLD_NOT_FOUND)
    assert e4["error_id"] == "ERR_PRIVACY_HOLD_NOT_FOUND"
