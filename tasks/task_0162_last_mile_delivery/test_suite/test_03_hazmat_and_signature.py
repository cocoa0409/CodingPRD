"""Hazmat protocol (PRD §2.6) and signature / driver-release authorization
(PRD §2.7) tests.

Covers: hazmat hub certification gate, hazmat driver endorsement gate,
the three driver-release gates (signature_required false +
customer.driver_release_authorized true + hazmat_class NONE), and
the DELIVERED_SIGNED requirement that signature_blob_ref is present.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    add_stop,
    api_client,
    create_driver,
    create_parcel,
    create_route,
    create_transit_center,
    deliver_signed,
    dispatch_route,
    induct_to_hub,
    make_driver_headers,
    move_clock_into_window,
    record_attempt,
    setup_baseline,
    sort_parcel,
    validate_error,
    validate_success,
    walk_parcel_to_out_for_delivery,
    walk_parcel_to_sorted,
)


# ---------------------------------------------------------------------------
# Hazmat hub
# ---------------------------------------------------------------------------
class TestHazmatHubCertification:

    def test_induct_hazmat_into_non_certified_hub_rejected(self, api):
        """PRD §2.6: 'A regulated parcel may only be inducted into or
        sorted by a TransitCenter whose hazmat_certified flag is true;
        either operation against a non-certified hub is rejected with
        ERR_HAZMAT_HUB_NOT_CERTIFIED.'"""
        base = setup_baseline(hazmat_certified=False)
        parcel = create_parcel(
            base["customer"]["id"], base["center"]["id"],
            destination_address_id=base["address"]["id"],
            hazmat_class="CLASS_3",
        )
        res = api.induct_parcel_to_hub(
            parcel["id"], TEST_USERS["sorting_hub_operator_headers"],
        )
        validate_error(res, "ERR_HAZMAT_HUB_NOT_CERTIFIED")

    def test_sort_hazmat_at_non_certified_hub_rejected(self, api):
        """PRD §2.6: same rule on /sort. PRD §3.3: 'if the parcel is
        regulated, the origin center must still be hazmat_certified
        (rejected with ERR_HAZMAT_HUB_NOT_CERTIFIED if not).'"""
        # Use a hazmat-certified hub for induction, then test on /sort
        # after toggling? PRD has no toggle endpoint. Alternative: a
        # non-hazmat parcel reaches IN_TRANSIT_HUB and is later marked
        # hazmat via PATCH while in IN_TRANSIT_HUB (PRD §3.3 permits
        # this). Then sort is gated.
        base = setup_baseline(hazmat_certified=False)
        parcel = create_parcel(
            base["customer"]["id"], base["center"]["id"],
            destination_address_id=base["address"]["id"],
        )
        # induct first (non-hazmat passes).
        induct_to_hub(parcel["id"])
        # PATCH to hazmat while in IN_TRANSIT_HUB — PRD §3.3 permits
        # mutation of hazmat_class in INDUCTED or IN_TRANSIT_HUB.
        api.patch_parcel(parcel["id"], {"hazmat_class": "CLASS_3"},
                         TEST_USERS["dispatcher_headers"])
        res = api.sort_parcel(
            parcel["id"], TEST_USERS["sorting_hub_operator_headers"],
        )
        validate_error(res, "ERR_HAZMAT_HUB_NOT_CERTIFIED")

    def test_hazmat_parcel_at_certified_hub_inducts_and_sorts(self, api):
        """PRD §2.6: hazmat-certified hub IS allowed; success path."""
        base = setup_baseline(hazmat_certified=True)
        parcel = create_parcel(
            base["customer"]["id"], base["center"]["id"],
            destination_address_id=base["address"]["id"],
            hazmat_class="CLASS_3",
        )
        in_hub = validate_success(api.induct_parcel_to_hub(
            parcel["id"], TEST_USERS["sorting_hub_operator_headers"],
        ), 200)
        assert in_hub["status"] == "IN_TRANSIT_HUB"
        sorted_p = validate_success(api.sort_parcel(
            parcel["id"], TEST_USERS["sorting_hub_operator_headers"],
        ), 200)
        assert sorted_p["status"] == "SORTED"


# ---------------------------------------------------------------------------
# Hazmat driver endorsement
# ---------------------------------------------------------------------------
class TestHazmatDriverEndorsement:

    def test_add_hazmat_stop_to_non_endorsed_driver_rejected(self, api):
        """PRD §3.4: 'if hazmat_class is anything other than NONE, the
        assigned driver's hazmat_endorsement must be true (otherwise
        ERR_DRIVER_NO_HAZMAT_ENDORSEMENT).'"""
        base = setup_baseline(
            hazmat_certified=True, hazmat_endorsement=False,
        )
        parcel = walk_parcel_to_sorted(
            base["customer"]["id"], base["center"]["id"],
            destination_address_id=base["address"]["id"],
            hazmat_class="CLASS_3",
        )
        route = create_route(base["center"]["id"], base["driver"]["id"])
        res = api.create_stop(
            route["id"], {"parcel_id": parcel["id"]},
            TEST_USERS["dispatcher_headers"],
        )
        validate_error(res, "ERR_DRIVER_NO_HAZMAT_ENDORSEMENT")

    def test_hazmat_parcel_loaded_to_endorsed_driver_route_succeeds(self, api):
        """PRD §2.6: 'A regulated parcel may only be loaded onto a
        Route whose assigned Driver carries hazmat_endorsement equal
        to true'.

        Positive complement to the add-stop rejection test above —
        confirms that the rule is gated on the endorsement flag, not
        on the parcel being hazmat. PRD does not expose a path to
        flip a driver's hazmat_endorsement after creation, so the
        dispatch-time variant of ERR_DRIVER_NO_HAZMAT_ENDORSEMENT is
        symmetric with the add-stop variant; the add-stop variant
        is the path PRD §3.4 names explicitly with the error_id, and
        the success path is verified here.
        """
        base = setup_baseline(
            hazmat_certified=True, hazmat_endorsement=True,
        )
        parcel = walk_parcel_to_sorted(
            base["customer"]["id"], base["center"]["id"],
            destination_address_id=base["address"]["id"],
            hazmat_class="CLASS_3",
        )
        route = create_route(base["center"]["id"], base["driver"]["id"])
        # Should succeed because the driver is endorsed.
        res = api.create_stop(
            route["id"], {"parcel_id": parcel["id"]},
            TEST_USERS["dispatcher_headers"],
        )
        validate_success(res, 201)


# ---------------------------------------------------------------------------
# Driver-release authorization (PRD §2.7)
# ---------------------------------------------------------------------------
class TestDriverReleaseAuthorization:

    def test_driver_release_succeeds_when_all_three_gates_pass(self, api):
        """PRD §2.7: 'three independent gates must all hold: the
        parcel's signature_required is false, the customer's
        driver_release_authorized is true, and the parcel's
        hazmat_class is NONE.'"""
        ctx = walk_parcel_to_out_for_delivery(
            driver_release_authorized=True,
            parcel_overrides={"signature_required": False,
                              "hazmat_class": "NONE"},
        )
        move_clock_into_window(ctx["parcel"])
        res = api.create_attempt(
            ctx["parcel"]["id"],
            {
                "route_stop_id": ctx["stop"]["id"],
                "outcome": "DRIVER_RELEASED",
                "release_location": "front porch",
            },
            make_driver_headers(ctx["driver"]["id"]),
        )
        validate_success(res, 201)

    def test_driver_release_rejected_when_signature_required(self, api):
        """PRD §2.7: 'If any one of these gates fails — signature was
        required ... the attempt is rejected with
        ERR_DRIVER_RELEASE_NOT_AUTHORIZED.'"""
        ctx = walk_parcel_to_out_for_delivery(
            driver_release_authorized=True,
            parcel_overrides={"signature_required": True},
        )
        move_clock_into_window(ctx["parcel"])
        res = api.create_attempt(
            ctx["parcel"]["id"],
            {
                "route_stop_id": ctx["stop"]["id"],
                "outcome": "DRIVER_RELEASED",
                "release_location": "front porch",
            },
            make_driver_headers(ctx["driver"]["id"]),
        )
        validate_error(res, "ERR_DRIVER_RELEASE_NOT_AUTHORIZED")

    def test_driver_release_rejected_when_customer_unauthorized(self, api):
        """PRD §2.7: 'the customer never authorized release ... the
        attempt is rejected with ERR_DRIVER_RELEASE_NOT_AUTHORIZED.'"""
        ctx = walk_parcel_to_out_for_delivery(
            driver_release_authorized=False,
        )
        move_clock_into_window(ctx["parcel"])
        res = api.create_attempt(
            ctx["parcel"]["id"],
            {
                "route_stop_id": ctx["stop"]["id"],
                "outcome": "DRIVER_RELEASED",
                "release_location": "front porch",
            },
            make_driver_headers(ctx["driver"]["id"]),
        )
        validate_error(res, "ERR_DRIVER_RELEASE_NOT_AUTHORIZED")

    def test_driver_release_rejected_when_parcel_hazmat(self, api):
        """PRD §2.6 / §2.7: 'the driver-release outcome — leaving a
        parcel without a signature — is categorically forbidden for
        any regulated parcel: an attempt to record DRIVER_RELEASED on
        a parcel whose hazmat_class is anything other than NONE must
        be rejected with ERR_DRIVER_RELEASE_NOT_AUTHORIZED.'"""
        ctx = walk_parcel_to_out_for_delivery(
            driver_release_authorized=True,
            hazmat_certified=True, hazmat_endorsement=True,
            parcel_overrides={"hazmat_class": "CLASS_3"},
        )
        move_clock_into_window(ctx["parcel"])
        res = api.create_attempt(
            ctx["parcel"]["id"],
            {
                "route_stop_id": ctx["stop"]["id"],
                "outcome": "DRIVER_RELEASED",
                "release_location": "front porch",
            },
            make_driver_headers(ctx["driver"]["id"]),
        )
        validate_error(res, "ERR_DRIVER_RELEASE_NOT_AUTHORIZED")


# ---------------------------------------------------------------------------
# Signature requirement
# ---------------------------------------------------------------------------
class TestSignatureRequirement:

    def test_delivered_signed_without_signature_blob_ref_rejected(self, api):
        """PRD §2.7 / §3.5: 'When a delivery attempt is recorded with
        outcome of DELIVERED_SIGNED, the signature_blob_ref field must
        be present and non-empty; omitting it is rejected with
        ERR_SIGNATURE_MISSING.'"""
        ctx = walk_parcel_to_out_for_delivery()
        move_clock_into_window(ctx["parcel"])
        res = api.create_attempt(
            ctx["parcel"]["id"],
            {
                "route_stop_id": ctx["stop"]["id"],
                "outcome": "DELIVERED_SIGNED",
                # No signature_blob_ref.
            },
            make_driver_headers(ctx["driver"]["id"]),
        )
        validate_error(res, "ERR_SIGNATURE_MISSING")

    def test_delivered_signed_with_empty_signature_blob_ref_rejected(self, api):
        """PRD §2.7: 'signature_blob_ref field must be present and
        non-empty'."""
        ctx = walk_parcel_to_out_for_delivery()
        move_clock_into_window(ctx["parcel"])
        res = api.create_attempt(
            ctx["parcel"]["id"],
            {
                "route_stop_id": ctx["stop"]["id"],
                "outcome": "DELIVERED_SIGNED",
                "signature_blob_ref": "",
            },
            make_driver_headers(ctx["driver"]["id"]),
        )
        validate_error(res, "ERR_SIGNATURE_MISSING")
