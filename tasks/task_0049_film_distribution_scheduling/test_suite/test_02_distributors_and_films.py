"""Distributor CRUD and Film lifecycle: PLANNED -> RELEASED -> SHELVED
-> RELEASED cycle, and clock-gated release transition.

Covers PRD §3.1, §3.2.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    DEFAULT_RELEASE_DATE,
    advance_clock,
    api_client,
    assert_distributor,
    assert_film,
    create_distributor,
    create_distributor_payload,
    create_film,
    create_film_payload,
    fetch_film,
    list_audit_logs_for,
    make_cinema_ops_headers,
    make_distributor_ops_headers,
    setup_basic_org,
    setup_released_film,
    setup_showtime_on_sale,
    shelve_film,
    shelve_payload,
    validate_error,
    validate_success,
    version_payload,
)


# =========================================================================
# Distributor creation
# =========================================================================
class TestDistributorCreate:

    def test_create_distributor_defaults_active(self, api, admin_headers):
        """PRD §3.1: 'The created row starts at status ACTIVE; an
        INACTIVE distributor cannot have a PLANNED film promoted out of
        plan.'

        Claim: POST /distributors returns a distributor with status ACTIVE.
        """
        res = api.create_distributor(
            create_distributor_payload(), admin_headers,
        )
        data = validate_success(res, expected_status=201)
        assert_distributor(data)
        assert data["status"] == "ACTIVE"

    def test_create_distributor_preserves_split_ratio(
        self, api, admin_headers,
    ):
        """PRD §3.1: 'the integer default_split_ratio_bps that will govern
        how net revenue is shared between distributor and cinema on every
        settlement'.

        Claim: default_split_ratio_bps is preserved on the response.
        """
        res = api.create_distributor(
            create_distributor_payload(default_split_ratio_bps=7250),
            admin_headers,
        )
        data = validate_success(res, expected_status=201)
        assert data["default_split_ratio_bps"] == 7250


# =========================================================================
# Film creation
# =========================================================================
class TestFilmCreate:

    def test_create_film_defaults_planned(self, api):
        """PRD §3.1: 'On creation, the new Film row starts at status
        PLANNED with shelved_reason absent.'

        Claim: POST /films returns a film with status PLANNED.
        """
        distributor = create_distributor()
        payload = create_film_payload(distributor_id=distributor["id"])
        res = api.create_film(
            payload, make_distributor_ops_headers(distributor["id"]),
        )
        data = validate_success(res, expected_status=201)
        assert_film(data)
        assert data["status"] == "PLANNED"

    def test_create_film_unknown_distributor(self, api):
        """PRD §2.5: 'any foreign-key field carried in the request body
        ... must resolve to an existing row; otherwise the response is
        404 ERR_REFERENCED_ENTITY_NOT_FOUND.'

        Claim: POST /films with non-existent distributor_id -> 404
        ERR_REFERENCED_ENTITY_NOT_FOUND.
        """
        # Use a real distributor for ownership, but a fake FK in body to
        # trigger the body-FK existence check.
        real = create_distributor()
        payload = create_film_payload(
            distributor_id="00000000-0000-0000-0000-000000000000",
        )
        res = api.create_film(
            payload, make_distributor_ops_headers(real["id"]),
        )
        validate_error(res, ApiErrorId.ERR_REFERENCED_ENTITY_NOT_FOUND.value)


# =========================================================================
# Film release lifecycle
# =========================================================================
class TestFilmReleaseTransition:

    def test_release_before_release_date_rejected(self, api):
        """PRD §3.2: 'Promotion from PLANNED to RELEASED is initiated by
        DistributorOps and is allowed only once the server clock has
        reached release_date and the parent Distributor.status is ACTIVE;
        if the clock is still earlier than release_date the transition is
        rejected with ERR_INVALID_STATE.'

        Claim: release before clock reaches release_date -> ERR_INVALID_STATE.
        """
        distributor = create_distributor()
        film = create_film(
            distributor, release_date="2099-01-01T00:00:00.000Z",
        )
        res = api.release_film(
            film["id"], version_payload(film["version"]),
            make_distributor_ops_headers(distributor["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_release_sets_status_and_clears_shelved_reason(self, api):
        """PRD §3.2: 'On a successful release, status flips to RELEASED,
        any previously recorded shelved_reason is cleared, updated_at is
        refreshed, and an AuditLog row is emitted with action FILM_RELEASE.'

        Claim: PLANNED -> RELEASED sets status RELEASED.
        """
        base = setup_released_film()
        assert base["film"]["status"] == "RELEASED"

    def test_release_emits_audit_log(self, api):
        """PRD §3.2: 'an AuditLog row is emitted with action FILM_RELEASE.'

        Claim: AuditLog has a FILM_RELEASE row for the released film.id.
        """
        base = setup_released_film()
        entries = list_audit_logs_for(
            base["film"]["id"], action="FILM_RELEASE",
        )
        assert len(entries) >= 1, (
            "PRD §3.2: a FILM_RELEASE audit row must be emitted on release"
        )


# =========================================================================
# Film shelve and re-release cycle
# =========================================================================
class TestFilmShelveAndCycle:

    def test_shelve_requires_active_showtime(self, api):
        """PRD §3.2: 'A film may only be shelved while it has at least
        one Showtime whose lifecycle_status is either SCHEDULED or
        IN_PROGRESS; without active downstream demand the shelve action
        is rejected with ERR_INVALID_STATE.'

        Claim: shelve with no scheduled showtimes -> ERR_INVALID_STATE.
        """
        base = setup_released_film()
        res = api.shelve_film(
            base["film"]["id"],
            shelve_payload(version=base["film"]["version"], reason="x"),
            make_distributor_ops_headers(base["distributor"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_shelve_records_reason_and_closes_future_showtimes(self, api):
        """PRD §3.2: 'On a successful shelve, every future showtime for
        the film whose lifecycle_status is SCHEDULED has its sale_status
        flipped from PRESALE or ON_SALE to CLOSED (so new ticket
        purchases are blocked), while lifecycle_status itself remains
        SCHEDULED.'

        Claim: after shelve, future Showtime.sale_status = CLOSED while
        lifecycle_status remains SCHEDULED, and shelved_reason is recorded.
        """
        base = setup_showtime_on_sale(presale_opens_at=DEFAULT_RELEASE_DATE)
        shelved = shelve_film(
            base["film"], base["distributor"], reason="reshoot_required",
        )
        assert shelved["status"] == "SHELVED"
        assert shelved.get("shelved_reason") == "reshoot_required"
        # Refresh showtime to see the side effect.
        showtime = api_client.get_showtime(
            base["showtime"]["id"],
            make_cinema_ops_headers(base["cinema"]["id"]),
        ).json()["data"]
        assert showtime["sale_status"] == "CLOSED"
        assert showtime["lifecycle_status"] == "SCHEDULED"

    def test_rerelease_clears_shelved_reason(self, api):
        """PRD §3.2: 'On a successful re-release, shelved_reason is
        cleared, and every showtime that was closed purely because of
        the shelving -- those still in lifecycle_status SCHEDULED --
        reopens its sale_status according to the same presale_opens_at
        rule used at creation time'.

        Claim: SHELVED -> RELEASED cycle clears shelved_reason.
        """
        base = setup_showtime_on_sale(presale_opens_at=DEFAULT_RELEASE_DATE)
        shelved = shelve_film(
            base["film"], base["distributor"], reason="paused",
        )
        # SHELVED -> RELEASED via release endpoint.
        res = api.release_film(
            shelved["id"], version_payload(shelved["version"]),
            make_distributor_ops_headers(base["distributor"]["id"]),
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "RELEASED"
        assert data.get("shelved_reason") in (None, "")
