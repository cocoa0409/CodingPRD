"""Dose-order creation guard chain, cancellation lockdown, and substitution OCC."""
from test_helpers import (
    TEST_USERS,
    T_ORDER_EXPIRY_F18,
    assert_dose_order,
    create_authorized_user,
    create_dose_order_payload,
    create_isotope,
    create_license,
    create_order,
    create_patient,
    get_order,
    instants_equal,
    make_authorized_user_headers,
    set_clock,
    setup_f18_department,
    setup_f18_order,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestOrderCreation:
    def test_order_created_ordered_with_computed_expiry(self, api):
        """PRD §3.3: "The server stamps `authorized_user_id` with the caller's
        `X-User-ID`, creates the order in `ORDERED` status, and computes
        `expires_at` as the scheduled administration instant plus two half-lives
        of the prescribed isotope — after that point the dose order is stale and
        the clock sweep will expire it."

        10:20 + 2 x 110 min = 14:00.

        Design: Corner/state_machines/order_created_in_ordered_initial_state_with_computed_expiry
        """
        ctx = setup_f18_department(receive=False, with_room=False)
        au_headers = make_authorized_user_headers(ctx["authorized_user"]["id"])
        res = api.create_dose_order(
            create_dose_order_payload(ctx["patient"]["id"], ctx["isotope"]["id"]), au_headers
        )
        order = validate_success(res, 201)
        assert_dose_order(order)
        assert order["status"] == "ORDERED"
        assert instants_equal(order["expires_at"], T_ORDER_EXPIRY_F18)
        assert order["authorized_user_id"] == ctx["authorized_user"]["id"]

    def test_order_blocked_when_license_suspended(self, api):
        """PRD §2.7: "The license posture (`ACTIVE` or `SUSPENDED`) gates four
        operations: dose-order creation, delivery receipt, vial preparation, and
        dose administration. While a license is `SUSPENDED`, those four
        operations are rejected with `ERR_LICENSE_SUSPENDED` (HTTP 409)."

        The license-posture check outranks the authorized-user standing check
        in the pipeline of PRD §2.9, so the suspended-license error is reported
        even though the cascade also suspended the user.

        Design: Corner/validations/order_create_blocked_when_license_suspended
        """
        ctx = setup_f18_department(receive=False, with_room=False)
        validate_success(api.suspend_license(ctx["license"]["id"], ADMIN), 200)

        res = api.create_dose_order(
            create_dose_order_payload(ctx["patient"]["id"], ctx["isotope"]["id"]),
            make_authorized_user_headers(ctx["authorized_user"]["id"]),
        )
        validate_error(res, "ERR_LICENSE_SUSPENDED", expected_status=409)

    def test_order_blocked_when_license_expired(self, api):
        """PRD §2.7: "License expiry is exclusive: the current clock instant must
        be strictly earlier than the license's `expires_at`, and at or after that
        instant the same four operations are rejected with `ERR_LICENSE_EXPIRED`
        (HTTP 409)."

        Design: Corner/validations/order_create_blocked_when_license_expired
        """
        set_clock("2026-08-01T08:00:00Z")
        iso = create_isotope()
        lic = create_license(iso["id"], license_number="L-EXP", expires_at="2026-07-01T00:00:00Z")
        au = create_authorized_user(lic["id"])
        pat = create_patient()

        res = api.create_dose_order(
            create_dose_order_payload(pat["id"], iso["id"]),
            make_authorized_user_headers(au["id"]),
        )
        validate_error(res, "ERR_LICENSE_EXPIRED", expected_status=409)

    def test_order_scope_insufficient(self, api):
        """PRD §3.3: "Then the prescriber's `scope` must cover the order's
        `use_type` — a scope of `BOTH` covers everything — otherwise
        `ERR_USER_SCOPE_INSUFFICIENT` (HTTP 403)."

        Design: Corner/validations/order_create_scope_insufficient
        """
        ctx = setup_f18_department(receive=False, with_room=False)
        au_diag = create_authorized_user(
            ctx["license"]["id"], full_name="Dr. Diag", scope="DIAGNOSTIC"
        )
        res = api.create_dose_order(
            create_dose_order_payload(
                ctx["patient"]["id"], ctx["isotope"]["id"], use_type="THERAPEUTIC"
            ),
            make_authorized_user_headers(au_diag["id"]),
        )
        validate_error(res, "ERR_USER_SCOPE_INSUFFICIENT", expected_status=403)

    def test_order_isotope_not_on_license(self, api):
        """PRD §3.3: "Then the isotope must appear in the license's
        `isotope_conditions` with an `allowed_use` that covers the `use_type`,
        otherwise `ERR_ISOTOPE_NOT_ON_LICENSE` (HTTP 409)."

        Design: Corner/validations/order_create_isotope_not_on_license
        """
        set_clock("2026-08-01T08:00:00Z")
        iso1 = create_isotope()
        iso2 = create_isotope(
            None,
            name="Tc-99m",
            half_life_minutes=361,
            spill_major_threshold_mbq=100,
            release_activity_limit_mbq=1500,
            min_usable_activity_mbq=10,
        )
        lic = create_license(iso1["id"])  # conditions cover iso1 only
        au = create_authorized_user(lic["id"])
        pat = create_patient()

        res = api.create_dose_order(
            create_dose_order_payload(pat["id"], iso2["id"]),
            make_authorized_user_headers(au["id"]),
        )
        validate_error(res, "ERR_ISOTOPE_NOT_ON_LICENSE", expected_status=409)

    def test_order_prescribed_exceeds_condition_limit(self, api):
        """PRD §3.3: "Then the `prescribed_activity_mbq` must be at most the
        matching condition's `max_possession_mbq`, otherwise
        `ERR_PRESCRIBED_ACTIVITY_EXCEEDS_LIMIT` (HTTP 422)."

        Design: Corner/validations/order_create_prescribed_exceeds_condition_limit
        """
        ctx = setup_f18_department(receive=False, with_room=False)
        res = api.create_dose_order(
            create_dose_order_payload(
                ctx["patient"]["id"], ctx["isotope"]["id"], prescribed_activity_mbq=60000
            ),
            make_authorized_user_headers(ctx["authorized_user"]["id"]),
        )
        validate_error(res, "ERR_PRESCRIBED_ACTIVITY_EXCEEDS_LIMIT", expected_status=422)

    def test_order_schedule_in_past(self, api):
        """PRD §3.3: "Then `administration_scheduled_at` must lie strictly in the
        future, otherwise `ERR_SCHEDULE_IN_PAST` (HTTP 422)."

        Design: Corner/validations/order_create_schedule_in_past
        """
        set_clock("2026-08-01T08:00:00Z")
        iso = create_isotope()
        lic = create_license(iso["id"])
        au = create_authorized_user(lic["id"])
        pat = create_patient()
        res = api.create_dose_order(
            create_dose_order_payload(
                pat["id"], iso["id"], administration_scheduled_at="2026-08-01T07:00:00Z"
            ),
            make_authorized_user_headers(au["id"]),
        )
        validate_error(res, "ERR_SCHEDULE_IN_PAST", expected_status=422)


class TestAuthorizedUserStanding:
    """DoseOrder x AuthorizedUser: an expired authorized user cannot act."""

    def test_expired_user_cannot_create_order(self, api):
        """PRD §3.1: "A user whose row is `SUSPENDED` or whose `expires_at` has
        been reached cannot act: order creation, order cancellation, order
        substitution, and release-instruction issuance by such a user are all
        rejected with `ERR_USER_NOT_ACTIVE` (HTTP 403)."

        The user expired 2026-07-01 while the license itself stays ACTIVE, so
        the license-posture checks pass and the standing check reports.

        Design: Difficulty/cross_entity_state_dependency/order_requires_active_authorized_user
        """
        set_clock("2026-08-01T08:00:00Z")
        iso = create_isotope()
        lic = create_license(iso["id"])
        au = create_authorized_user(
            lic["id"], full_name="Dr. Expired", expires_at="2026-07-01T00:00:00Z"
        )
        pat = create_patient()

        res = api.create_dose_order(
            create_dose_order_payload(pat["id"], iso["id"]),
            make_authorized_user_headers(au["id"]),
        )
        validate_error(res, "ERR_USER_NOT_ACTIVE", expected_status=403)

    def test_expired_user_cannot_cancel_order(self, api):
        """PRD §3.1: "A user whose row is `SUSPENDED` or whose `expires_at` has
        been reached cannot act: order creation, order cancellation, order
        substitution, and release-instruction issuance by such a user are all
        rejected with `ERR_USER_NOT_ACTIVE` (HTTP 403)."

        The user prescribed while active (expires at noon), the clock then moves
        past the expiry; the order itself is still far from its own expiry
        (14:00), so it survives the sweep and remains ORDERED.

        Design: Difficulty/cross_entity_state_dependency/order_requires_active_authorized_user
        """
        ctx = setup_f18_department(receive=False, with_room=False)
        au = create_authorized_user(
            ctx["license"]["id"], full_name="Dr. Brief", expires_at="2026-08-01T12:00:00Z"
        )
        order = create_order(ctx["patient"]["id"], ctx["isotope"]["id"], au)

        set_clock("2026-08-01T13:00:00Z")  # user expired; order expires 14:00
        assert get_order(order["id"])["status"] == "ORDERED"

        res = api.cancel_dose_order(
            order["id"], {"reason": "too late"}, make_authorized_user_headers(au["id"])
        )
        validate_error(res, "ERR_USER_NOT_ACTIVE", expected_status=403)
        assert get_order(order["id"])["status"] == "ORDERED"


class TestOrderCancellation:
    def test_cancel_already_cancelled_order(self, api):
        """PRD §3.3: "Cancellation is permitted from `ORDERED`, from
        `DOSE_PREPARED`, and from `ON_HOLD`; an order in any other state rejects
        the attempt with `ERR_INVALID_STATE`."

        CANCELLED is terminal, so the second cancel is rejected.

        Design: Corner/state_machines/cancel_already_cancelled_order_returns_invalid_state
        """
        ctx = setup_f18_order()
        au_headers = make_authorized_user_headers(ctx["authorized_user"]["id"])
        cancelled = validate_success(
            api.cancel_dose_order(ctx["order"]["id"], {"reason": "patient refused"}, au_headers),
            200,
        )
        assert cancelled["status"] == "CANCELLED"

        res = api.cancel_dose_order(ctx["order"]["id"], {"reason": "again"}, au_headers)
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)


class TestSubstitutionOcc:
    def test_stale_substitution_rejected_after_first_succeeds(self, api):
        """PRD §2.8: "`POST /nuclear-medicine/dose-orders/{id}/substitute`
        requires `expected_order_version` carrying the version of the target dose
        order that the client last observed; if that value does not match the
        order's current `version` — because another write has advanced it since
        the client's last read — the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412)..." and PRD §3.3: "On success, a new dose order is created in
        `ORDERED` status for the same patient, with its `replaces_order_id`
        pointing at the original order; the original order moves to `SUPERSEDED`,
        its `superseded_by_order_id` is set to the new order's id, and its
        `version` increments by one."

        Design: Corner/complexity_layers/occ_stale_substitute_version
        """
        ctx = setup_f18_order()
        au_headers = make_authorized_user_headers(ctx["authorized_user"]["id"])
        observed_version = ctx["order"]["version"]

        substitute_payload = {
            "expected_order_version": observed_version,
            "isotope_product_id": ctx["isotope"]["id"],
            "use_type": "DIAGNOSTIC",
            "prescribed_activity_mbq": 100,
            "administration_scheduled_at": "2026-08-01T11:00:00Z",
        }
        new_order = validate_success(
            api.substitute_dose_order(ctx["order"]["id"], substitute_payload, au_headers), 201
        )
        assert_dose_order(new_order)
        assert new_order["status"] == "ORDERED"
        assert new_order["replaces_order_id"] == ctx["order"]["id"]
        assert new_order["patient_id"] == ctx["patient"]["id"]

        original = get_order(ctx["order"]["id"])
        assert original["status"] == "SUPERSEDED"
        assert original["superseded_by_order_id"] == new_order["id"]
        assert original["version"] == observed_version + 1, "version increments by one"

        stale = api.substitute_dose_order(
            ctx["order"]["id"],
            {**substitute_payload, "administration_scheduled_at": "2026-08-01T11:30:00Z"},
            au_headers,
        )
        validate_error(stale, "ERR_STALE_VERSION", expected_status=412)
