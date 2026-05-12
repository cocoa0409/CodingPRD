"""Dispatch acceptance, rejection, expiry, and re-dispatch.

Covers PRD §3.3 (matching, dispatch, acceptance window) and the
related Order status transitions DISPATCHED <-> AWAITING_DISPATCH.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    DEFAULT_SCHEDULED_START_ISO,
    NON_EXISTENT_UUID,
    accept_dispatch,
    api_client,
    assert_dispatch,
    create_certified_nurse,
    create_order_payload,
    create_order_raw,
    create_service_item_raw,
    get_success_data,
    list_dispatches_for,
    make_nurse_headers,
    make_patient_headers,
    offset_lat_km,
    setup_basic_dispatched_order,
    stable_user_id,
    validate_error,
    validate_success,
)


class TestDispatchAccept:

    def test_assigned_nurse_accepts_dispatch(
        self, api, platform_admin_headers,
    ):
        """PRD §3.3: 'On a successful acceptance, the dispatch flips from
        OFFERED to ACCEPTED, the order advances from AWAITING_DISPATCH
        to DISPATCHED'.

        Claim: the assigned nurse posting /accept advances Dispatch to
        ACCEPTED and Order to DISPATCHED.
        """
        setup = setup_basic_dispatched_order()
        res = api.accept_dispatch(
            setup["dispatch"]["id"],
            make_nurse_headers(setup["nurse_id"]),
        )
        data = validate_success(res)
        assert data["status"] == "ACCEPTED"
        # Order should now be DISPATCHED.
        order = get_success_data(api.get_order(
            setup["order"]["id"],
            make_patient_headers(setup["patient_id"]),
        ))
        assert order["status"] == "DISPATCHED"

    def test_other_nurse_cannot_accept(
        self, api, platform_admin_headers,
    ):
        """PRD §3.3: 'Acceptance and rejection both require the calling
        X-User-ID to equal Dispatch.nurse_id (otherwise
        ERR_RESOURCE_LINK_INVALID)'."""
        setup = setup_basic_dispatched_order()
        # Create a second certified nurse and try to accept.
        intruder = create_certified_nurse(specialty_tags=["IV_INFUSION"])
        res = api.accept_dispatch(
            setup["dispatch"]["id"],
            make_nurse_headers(intruder["id"]),
        )
        validate_error(res, ApiErrorId.ERR_RESOURCE_LINK_INVALID.value)


class TestDispatchReject:

    def test_reject_triggers_redispatch_when_pool_nonempty(
        self, api, platform_admin_headers,
    ):
        """PRD §3.3: 'Rejection accepts an optional free-text
        rejection_reason, flips the dispatch to REJECTED, and triggers a
        re-dispatch attempt on the order: provided dispatch_attempt_count
        is strictly less than the cap of 5 and no other ACCEPTED dispatch
        exists, the order returns to AWAITING_DISPATCH, the selector runs
        again excluding any nurse tied to a prior REJECTED or EXPIRED
        dispatch on this order, and a new Dispatch row is created.'
        """
        item = create_service_item_raw(required_skill="IV_INFUSION")
        # Two nurses both eligible.
        n1 = create_certified_nurse(
            home_lat=31.20, home_lng=121.40,
            specialty_tags=["IV_INFUSION"],
        )
        n2 = create_certified_nurse(
            home_lat=offset_lat_km(31.20, 5.0), home_lng=121.40,
            specialty_tags=["IV_INFUSION"],
        )
        patient_id = stable_user_id("patient")
        order = create_order_raw(
            patient_id=patient_id,
            service_item_code=item["code"],
            service_lat=31.20, service_lng=121.40,
            scheduled_start=DEFAULT_SCHEDULED_START_ISO,
        )
        dispatches_before = list_dispatches_for(order["id"])
        assert len(dispatches_before) == 1, (
            f"PRD §3.3: exactly one Dispatch on AWAITING_DISPATCH entry; "
            f"got {len(dispatches_before)}"
        )
        first = dispatches_before[0]
        # Have the assigned nurse reject.
        res = api.reject_dispatch(
            first["id"], make_nurse_headers(first["nurse_id"]),
        )
        validate_success(res)
        # Re-fetch dispatches; another row should now exist.
        dispatches_after = list_dispatches_for(order["id"])
        assert len(dispatches_after) >= 2, (
            f"PRD §3.3: re-dispatch must create a new Dispatch row; "
            f"got {len(dispatches_after)}"
        )
        # First dispatch is REJECTED; new one is OFFERED.
        first_reread = next(
            d for d in dispatches_after if d["id"] == first["id"]
        )
        assert first_reread["status"] == "REJECTED"
        # New dispatch must be to a different nurse (selector excludes
        # nurses tied to prior REJECTED dispatches).
        new_dispatch = next(
            d for d in dispatches_after if d["id"] != first["id"]
        )
        assert new_dispatch["nurse_id"] != first["nurse_id"], (
            "PRD §3.3: 'the selector runs again excluding any nurse tied "
            "to a prior REJECTED or EXPIRED dispatch on this order'"
        )

    def test_reject_increments_dispatch_attempt_count(
        self, api, platform_admin_headers,
    ):
        """PRD §3.3: 'The order's dispatch_attempt_count is incremented
        by exactly one' (per Dispatch creation).
        """
        item = create_service_item_raw(required_skill="IV_INFUSION")
        n1 = create_certified_nurse(
            home_lat=31.20, home_lng=121.40,
            specialty_tags=["IV_INFUSION"],
        )
        n2 = create_certified_nurse(
            home_lat=offset_lat_km(31.20, 4.0), home_lng=121.40,
            specialty_tags=["IV_INFUSION"],
        )
        patient_id = stable_user_id("patient")
        order = create_order_raw(
            patient_id=patient_id,
            service_item_code=item["code"],
            service_lat=31.20, service_lng=121.40,
            scheduled_start=DEFAULT_SCHEDULED_START_ISO,
        )
        # initial count = 1
        order_after1 = get_success_data(api.get_order(
            order["id"], make_patient_headers(patient_id),
        ))
        assert order_after1["dispatch_attempt_count"] == 1
        first = list_dispatches_for(order["id"])[0]
        api.reject_dispatch(
            first["id"], make_nurse_headers(first["nurse_id"]),
        )
        order_after2 = get_success_data(api.get_order(
            order["id"], make_patient_headers(patient_id),
        ))
        assert order_after2["dispatch_attempt_count"] == 2


class TestDispatchEmptyPool:

    def test_empty_pool_cancels_order(
        self, api, platform_admin_headers,
    ):
        """PRD §3.3: 'When the candidate set is empty after filters and
        exclusions, the order is sent straight to CANCELLED with
        cancelled_reason set to ERR_NO_AVAILABLE_NURSE and the same
        error code surfaces to the API caller.'

        Claim: order created with no eligible nurses -> Order.status
        becomes CANCELLED.
        """
        item = create_service_item_raw(required_skill="IV_INFUSION")
        # No nurses with IV_INFUSION skill exist; make a single
        # certified nurse with a different skill.
        nurse = create_certified_nurse(
            specialty_tags=["WOUND_CARE"],
        )
        patient_id = stable_user_id("patient")
        # POST /orders may either reject with ERR_NO_AVAILABLE_NURSE or
        # create the Order in CANCELLED state with the cancelled_reason
        # set. Both forms are PRD-faithful per §3.3.
        res = api.create_order(
            create_order_payload(
                service_item_code=item["code"],
                scheduled_start=DEFAULT_SCHEDULED_START_ISO,
            ),
            make_patient_headers(patient_id),
        )
        if res.status_code >= 400:
            validate_error(res, ApiErrorId.ERR_NO_AVAILABLE_NURSE.value)
        else:
            data = get_success_data(res)
            assert data["status"] == "CANCELLED"


class TestDispatchAcceptanceLink:

    def test_accept_unknown_dispatch_404(
        self, api, nurse_headers_fallback,
    ):
        """PRD §2.5: 'path-resource existence ... ERR_DISPATCH_NOT_FOUND'."""
        res = api.accept_dispatch(
            NON_EXISTENT_UUID, nurse_headers_fallback,
        )
        validate_error(res, ApiErrorId.ERR_DISPATCH_NOT_FOUND.value)
