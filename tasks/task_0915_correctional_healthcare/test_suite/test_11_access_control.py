"""Authentication, endpoint role authorization and inmate resource ownership."""

from test_helpers import (
    ApiErrorId,
    book_inmate_payload,
    fixtures as fx,
    make_inmate_headers,
    medication_order_payload,
    validate_error,
    validate_paginated,
)


class TestAuthentication:
    def test_a_request_without_the_role_header_is_unauthenticated(self, api, no_auth_headers):
        """PRD §2.1: "Both headers are mandatory on every endpoint without exception,
        including read-only ones. If either header is absent, or if `X-User-Role` carries a
        string that is not one of the nine role names below, the request is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/missing_x_user_role_header_returns_unauthenticated
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        resp = api.create_inmate(
            book_inmate_payload(
                booking_number="C-2370",
                full_name="Eve Halim",
                booked_at="2026-05-01T00:00:00Z",
            ),
            no_auth_headers,
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


class TestRoleAuthorization:
    def test_a_nurse_may_not_write_a_medication_order(self, api, nurse_headers, provider_headers):
        """PRD §2.1: "If the headers are well formed but the named role is not among the
        roles authorized for the endpoint being called (see the Authorized Role(s) column of
        §4), the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §2.1: "A `Provider` is a physician, nurse practitioner or physician assistant:
        they prescribe, enrol patients in chronic care, write referrals and dispose of
        encounters."
        PRD §2.5: "**Role authorization.** The named role appears in the called endpoint's
        authorized-role list. Failure yields `ERR_FORBIDDEN_ROLE` (403)."

        Design: Corner/rbac/nurse_cannot_write_medication_order_forbidden
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate = fx.book_inmate(
            booking_number="C-2350", full_name="Bo Esposito", booked_at="2026-05-01T00:00:00Z"
        )
        resp = api.create_medication_order(
            medication_order_payload(inmate["id"], inmate["version"]), nurse_headers
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

        rows, meta = validate_paginated(
            api.list_medication_orders(provider_headers, params={"inmate_id": inmate["id"]})
        )
        assert meta["total_count"] == 0
        assert rows == []
        assert fx.read_inmate(inmate["id"])["version"] == 1


class TestResourceOwnership:
    def test_an_inmate_may_not_file_a_grievance_on_another_patients_record(
        self, api, grievance_coordinator_headers
    ):
        """PRD §2.1: "The ninth role is different. When `X-User-Role` is `Inmate`,
        `X-User-ID` is the `id` of the acting `Inmate` row. Ownership checks on any resource
        an `Inmate` addresses compare that resource's `inmate_id` — directly, or transitively
        through its parent chain, so that a grievance reached through its own identifier still
        resolves to the inmate who filed it — against `X-User-ID`. A mismatch is rejected with
        `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

        Design: Corner/rbac/inmate_cannot_file_grievance_for_another_inmate
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        inmate_a = fx.book_inmate(
            booking_number="C-2360", full_name="Cal Fontaine", booked_at="2026-05-01T00:00:00Z"
        )
        inmate_b = fx.book_inmate(
            booking_number="C-2361", full_name="Dot Grigg", booked_at="2026-05-01T00:00:00Z"
        )

        resp = api.create_grievance(
            inmate_b["id"],
            {
                "grievance_text": "filed by the wrong person",
                "grieved_event_at": "2026-05-01T00:00:00Z",
            },
            make_inmate_headers(inmate_a["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

        rows, meta = validate_paginated(
            api.list_grievances(
                grievance_coordinator_headers, params={"inmate_id": inmate_b["id"]}
            )
        )
        assert meta["total_count"] == 0
        assert rows == []
