"""Medical-waste registration & archival, and package credit consumption.

Covers PRD §3.4 waste paragraphs and §3.4 package paragraph + §3.4
completion gate ERR_WASTE_NOT_ARCHIVED.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    DEFAULT_NOW_ISO,
    accept_dispatch,
    add_days,
    api_client,
    archive_waste,
    assert_waste_entry,
    confirm_completion,
    create_certified_nurse,
    create_package_raw,
    create_service_item_raw,
    create_waste_entry_payload,
    finish_service_record,
    get_success_data,
    hand_over_waste,
    make_compliance_officer_headers,
    make_nurse_headers,
    make_patient_headers,
    perform_checkin,
    register_waste,
    setup_basic_dispatched_order,
    setup_in_progress_order,
    setup_awaiting_patient_confirm_order,
    setup_completed_order,
    stable_user_id,
    create_order_raw,
    DEFAULT_SCHEDULED_START_ISO,
    validate_error,
    validate_success,
)


class TestWasteLifecycle:

    def test_register_waste_initial_status(
        self, api, platform_admin_headers,
    ):
        """PRD §3.4: 'The nurse posts a WasteEntry for each registered
        item, supplying the category (one of SHARPS, INFECTIOUS, or
        PHARMACEUTICAL), the positive quantity, and the unit ... The
        waste row begins in REGISTERED'."""
        setup = setup_in_progress_order(nurse_specialty="WOUND_CARE")
        res = api.create_waste_entry(
            setup["order"]["id"],
            create_waste_entry_payload(
                category="SHARPS", quantity=2, unit="PCS",
            ),
            make_nurse_headers(setup["nurse_id"]),
        )
        data = validate_success(res, expected_status=201)
        assert_waste_entry(data)
        assert data["status"] == "REGISTERED"

    def test_handover_advances_to_handed_over(
        self, api, platform_admin_headers,
    ):
        """PRD §3.4: 'When the disposal unit takes custody, the nurse
        patches the row with sealed set to true, the qualified
        disposal_unit_id, and the handover_at timestamp; this transition
        (which requires sealed true and a non-empty disposal_unit_id)
        advances the row to HANDED_OVER.'"""
        setup = setup_in_progress_order(nurse_specialty="WOUND_CARE")
        waste = register_waste(
            setup["order"]["id"], setup["nurse_id"],
            category="INFECTIOUS", quantity=0.5, unit="LITERS",
        )
        out = hand_over_waste(
            setup["order"]["id"], waste["id"], setup["nurse_id"],
            handover_at=DEFAULT_NOW_ISO,
            disposal_unit_id="DUI-9001",
        )
        assert out["status"] == "HANDED_OVER"

    def test_archive_via_event(
        self, api, platform_admin_headers,
    ):
        """PRD §3.4: 'The medical-waste-disposal system later returns
        through the test event hook (system=medical-waste-disposal,
        event_type=CERTIFICATE_ISSUED) carrying the certificate_url;
        the row then advances to ARCHIVED, the URL is stored'."""
        setup = setup_in_progress_order(nurse_specialty="WOUND_CARE")
        waste = register_waste(
            setup["order"]["id"], setup["nurse_id"],
            category="SHARPS", quantity=1, unit="PCS",
        )
        hand_over_waste(
            setup["order"]["id"], waste["id"], setup["nurse_id"],
        )
        archive_waste(waste["id"])
        # List & verify status.
        rows = get_success_data(api.list_waste_entries(
            setup["order"]["id"],
            make_nurse_headers(setup["nurse_id"]),
        ))
        if isinstance(rows, dict) and "data" in rows:
            rows = rows["data"]
        target = next(r for r in rows if r["id"] == waste["id"])
        assert target["status"] == "ARCHIVED"


class TestCompletionGatedByWaste:

    def test_waste_not_archived_blocks_confirm(
        self, api, platform_admin_headers,
    ):
        """PRD §3.4: 'every WasteEntry belonging to the order must
        already be ARCHIVED; an unarchived entry blocks confirmation
        with ERR_WASTE_NOT_ARCHIVED.'

        Claim: a WOUND_CARE order has a HANDED_OVER waste entry; patient
        confirm-completion -> 409 ERR_WASTE_NOT_ARCHIVED.
        """
        setup = setup_in_progress_order(nurse_specialty="WOUND_CARE")
        waste = register_waste(
            setup["order"]["id"], setup["nurse_id"],
            category="SHARPS", quantity=1, unit="PCS",
        )
        hand_over_waste(
            setup["order"]["id"], waste["id"], setup["nurse_id"],
        )
        # Note: NOT archiving.
        finish_service_record(setup["order"]["id"], setup["nurse_id"])
        res = api.confirm_completion(
            setup["order"]["id"],
            make_patient_headers(setup["patient_id"]),
        )
        validate_error(res, ApiErrorId.ERR_WASTE_NOT_ARCHIVED.value)


class TestPackageCredits:

    def test_package_used_credits_increments_on_completion(
        self, api, platform_admin_headers,
    ):
        """PRD §3.4: 'if a package was used its used_credits is
        incremented by exactly one -- when used_credits reaches
        total_credits, the package's status flips to EXHAUSTED.'
        """
        item = create_service_item_raw(required_skill="ELDERLY_CARE")
        nurse = create_certified_nurse(specialty_tags=["ELDERLY_CARE"])
        patient_id = stable_user_id("patient")
        package = create_package_raw(
            patient_id=patient_id,
            service_item_code=item["code"],
            total_credits=1,
        )
        order = create_order_raw(
            patient_id=patient_id,
            service_item_code=item["code"],
            scheduled_start=DEFAULT_SCHEDULED_START_ISO,
            package_id=package["id"],
        )
        # Nurse acceptance, checkin, finish, confirm.
        from test_helpers import (
            list_dispatches_for, accept_dispatch,
        )
        d = list_dispatches_for(order["id"])[0]
        accept_dispatch(d, d["nurse_id"])
        perform_checkin(
            order["id"], d["nurse_id"],
            checkin_at=DEFAULT_SCHEDULED_START_ISO,
            checkin_lat=order["service_lat"],
            checkin_lng=order["service_lng"],
        )
        finish_service_record(order["id"], d["nurse_id"])
        confirm_completion(order["id"], patient_id)
        # Re-fetch package.
        rows = get_success_data(api.list_packages(
            make_patient_headers(patient_id)
        ))
        if isinstance(rows, dict) and "data" in rows:
            rows = rows["data"]
        target = next(p for p in rows if p["id"] == package["id"])
        assert target["used_credits"] == 1, (
            f"PRD §3.4: used_credits +=1, got {target['used_credits']}"
        )
        assert target["status"] == "EXHAUSTED", (
            "PRD §3.4: 'when used_credits reaches total_credits, the "
            "package's status flips to EXHAUSTED'"
        )

    def test_package_with_no_credits_left_rejected_at_create_order(
        self, api, platform_admin_headers,
    ):
        """PRD §3.2: 'its used_credits must be strictly less than its
        total_credits (otherwise ERR_INSUFFICIENT_PACKAGE_CREDIT).'
        Achieved by setting total_credits=1 and consuming it once.
        """
        item = create_service_item_raw(required_skill="ELDERLY_CARE")
        nurse = create_certified_nurse(specialty_tags=["ELDERLY_CARE"])
        patient_id = stable_user_id("patient")
        package = create_package_raw(
            patient_id=patient_id,
            service_item_code=item["code"],
            total_credits=1,
        )
        # Order 1: consumes the credit.
        order = create_order_raw(
            patient_id=patient_id,
            service_item_code=item["code"],
            scheduled_start=DEFAULT_SCHEDULED_START_ISO,
            package_id=package["id"],
        )
        from test_helpers import (
            list_dispatches_for, accept_dispatch,
        )
        d = list_dispatches_for(order["id"])[0]
        accept_dispatch(d, d["nurse_id"])
        perform_checkin(
            order["id"], d["nurse_id"],
            checkin_at=DEFAULT_SCHEDULED_START_ISO,
            checkin_lat=order["service_lat"],
            checkin_lng=order["service_lng"],
        )
        finish_service_record(order["id"], d["nurse_id"])
        confirm_completion(order["id"], patient_id)
        # Order 2: package now exhausted.
        from test_helpers import create_order_payload
        res = api.create_order(
            create_order_payload(
                service_item_code=item["code"],
                scheduled_start=DEFAULT_SCHEDULED_START_ISO,
                package_id=package["id"],
            ),
            make_patient_headers(patient_id),
        )
        validate_error(
            res, ApiErrorId.ERR_INSUFFICIENT_PACKAGE_CREDIT.value
        )
