"""Avail-package state machine guards and offer/accept validation rules."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_slot,
    accept_package,
    create_and_offer_package,
    create_avail_package_payload,
    get_package,
    get_success_data,
    list_all_licenses,
    make_line,
    setup_catalog,
    validate_error,
    validate_success,
)

RM = TEST_USERS["rights_manager_headers"]


def _offered_single_line_package(api, workspace):
    """One-slot OFFERED package on a fresh SVOD slot of the workspace."""
    slot = add_slot(workspace)
    package = create_and_offer_package(
        workspace["platform"]["id"], [make_line(slot["id"], flat_fee_cents=10000)],
    )
    return package, slot


class TestOfferGuard:
    def test_package_offer_twice_returns_409(self, api):
        """PRD §3.3: "The package must currently be `DRAFT`, otherwise `ERR_PACKAGE_NOT_DRAFT` (409)."

        Design: Corner/state_machines/package_offer_twice_returns_409
        """
        workspace = setup_catalog()
        package, _slot = _offered_single_line_package(api, workspace)

        resp = api.offer_package(package["id"], RM)
        validate_error(resp, ApiErrorId.ERR_PACKAGE_NOT_DRAFT, 409)

    def test_offer_with_past_expiry_returns_422(self, api):
        """PRD §3.3: "Finally, `offer_expires_at` must be strictly after the logical clock at offer time, otherwise `ERR_OFFER_WINDOW_PAST` (422)."

        Design: Corner/validations/offer_with_past_expiry_returns_422
        """
        workspace = setup_catalog()
        slot = add_slot(workspace)
        payload = create_avail_package_payload(
            workspace["platform"]["id"],
            [make_line(slot["id"], flat_fee_cents=10000)],
            offer_expires_at="2026-07-01T00:00:00Z",
        )
        package = get_success_data(api.create_avail_package(payload, RM))

        resp = api.offer_package(package["id"], RM)
        validate_error(resp, ApiErrorId.ERR_OFFER_WINDOW_PAST, 422)
        assert get_package(package["id"])["package_status"] == "DRAFT"


class TestAcceptGuard:
    def test_package_accept_from_draft_returns_409(self, api):
        """PRD §3.5: "The package must be `OFFERED`, otherwise `ERR_PACKAGE_NOT_OFFERED` (409); this single check also rejects packages that have already expired or been withdrawn."

        Design: Corner/state_machines/package_accept_from_draft_returns_409
        """
        workspace = setup_catalog()
        slot = add_slot(workspace)
        payload = create_avail_package_payload(
            workspace["platform"]["id"],
            [make_line(slot["id"], flat_fee_cents=10000)],
        )
        package = get_success_data(api.create_avail_package(payload, RM))

        resp = api.accept_package(
            package["id"], [slot["id"]], workspace["buyer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_PACKAGE_NOT_OFFERED, 409)
        assert list_all_licenses() == [], "no license may be created from a DRAFT package"

    def test_package_decline_then_accept_returns_409(self, api):
        """PRD §3.5: "The buyer may instead decline the offer outright; declining requires the package to be `OFFERED` and the caller to own it, and moves the package to `DECLINED` with its non-`LICENSED` lines becoming `NOT_SELECTED`."
        PRD §3.5: "The package must be `OFFERED`, otherwise `ERR_PACKAGE_NOT_OFFERED` (409); this single check also rejects packages that have already expired or been withdrawn."

        Design: Corner/state_machines/package_decline_then_accept_returns_409
        """
        workspace = setup_catalog()
        package, slot = _offered_single_line_package(api, workspace)

        declined = validate_success(
            api.decline_package(package["id"], workspace["buyer_headers"]), 200,
        )
        assert declined["package_status"] == "DECLINED"

        resp = api.accept_package(
            package["id"], [slot["id"]], workspace["buyer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_PACKAGE_NOT_OFFERED, 409)

    def test_accept_with_empty_slot_list_returns_422(self, api):
        """PRD §3.5: "The list must be non-empty, otherwise `ERR_EMPTY_ACCEPTANCE` (422)."

        Design: Corner/validations/accept_with_empty_slot_list_returns_422
        """
        workspace = setup_catalog()
        package, _slot = _offered_single_line_package(api, workspace)

        resp = api.accept_package(package["id"], [], workspace["buyer_headers"])
        validate_error(resp, ApiErrorId.ERR_EMPTY_ACCEPTANCE, 422)
        assert get_package(package["id"])["package_status"] == "OFFERED"

    def test_accept_with_foreign_slot_returns_422(self, api):
        """PRD §3.5: "Every element must be the `slot_id` of some line of the addressed package, otherwise `ERR_LINE_NOT_IN_PACKAGE` (422)."

        Design: Corner/validations/accept_with_foreign_slot_returns_422
        """
        workspace = setup_catalog()
        in_package = add_slot(workspace, window_type="SVOD")
        outside = add_slot(workspace, window_type="AVOD")
        package = create_and_offer_package(
            workspace["platform"]["id"],
            [make_line(in_package["id"], flat_fee_cents=10000)],
        )

        resp = api.accept_package(
            package["id"], [outside["id"]], workspace["buyer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_LINE_NOT_IN_PACKAGE, 422)


class TestWithdrawGuard:
    def test_package_withdraw_after_accept_returns_409(self, api):
        """PRD §3.3: "A `RightsManager` may pull a package back while it is `DRAFT` or `OFFERED`; withdrawing moves it to `WITHDRAWN` and moves its non-`LICENSED` lines to `NOT_SELECTED`. A package in any terminal state resists withdrawal with `ERR_PACKAGE_NOT_WITHDRAWABLE` (409)."

        Design: Corner/state_machines/package_withdraw_after_accept_returns_409
        """
        workspace = setup_catalog()
        package, slot = _offered_single_line_package(api, workspace)
        accepted = accept_package(
            package["id"], [slot["id"]], workspace["buyer_headers"],
        )
        assert accepted["package_status"] == "ACCEPTED"

        resp = api.withdraw_package(package["id"], RM)
        validate_error(resp, ApiErrorId.ERR_PACKAGE_NOT_WITHDRAWABLE, 409)


class TestLineShapeValidation:
    def test_package_with_duplicate_line_slots_rejected(self, api):
        """PRD §2.10: "Within one package, `slot_id` values must be distinct — two lines referencing the same slot are rejected with `ERR_DUPLICATE_LINE_SLOT` (422)."

        Design: Corner/validations/package_with_duplicate_line_slots_rejected
        """
        workspace = setup_catalog()
        slot = add_slot(workspace)
        payload = create_avail_package_payload(
            workspace["platform"]["id"],
            [
                make_line(slot["id"], flat_fee_cents=10000),
                make_line(
                    slot["id"],
                    license_start="2026-10-01T00:00:00Z",
                    license_end="2027-01-01T00:00:00Z",
                    flat_fee_cents=20000,
                ),
            ],
        )

        resp = api.create_avail_package(payload, RM)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_LINE_SLOT, 422)
