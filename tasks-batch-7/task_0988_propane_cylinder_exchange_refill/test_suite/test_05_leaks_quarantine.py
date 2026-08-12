"""Leak response, cage quarantine cascade, and re-inspection gating (PRD §3.5)."""
import pytest

from test_helpers import (
    ApiErrorId,
    confirm_leak,
    create_order,
    create_priced_site,
    create_site,
    create_ticket,
    get_site,
    register_customer_cylinder,
    register_fleet_cylinders,
    report_leak,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CLERK1 = TEST_USERS["site_clerk_headers"]
CLERK2 = TEST_USERS["site_clerk_2_headers"]
OFFICER1 = TEST_USERS["compliance_officer_headers"]


class TestLeakConfirmCascade:
    def test_leak_confirm_quarantine_chain(self, api):
        """PRD §3.5: "When the confirmed leak is `MAJOR`, or when `quarantine_cage` was recommended, a cage-wide quarantine cascade fires: every fleet cylinder at the site in `FULL` or `EMPTY` fill status becomes `QUARANTINED`; because cylinder fill states changed, the site's `full_on_hand`, `empty_on_hand`, and `quarantined_on_hand` recompute; and because `full_on_hand` recomputed, `restock_alert` flips on if the count now sits at or below `reorder_floor_full`."
        PRD §3.5: "Independently of severity, a confirmed quarantining leak recomputes the site's `sales_posture` to `SALES_BLOCKED`, and the moment the posture blocks, every `DRAFT` exchange order at the site is auto-voided with `void_reason` `SAFETY` and every `OPEN` or `WEIGHED` refill ticket at the site is auto-voided"

        Design: Difficulty/transitive_cascade/leak_confirm_quarantine_chain
        """
        site, _policy = create_priced_site()  # par 12 -> reorder_floor 6
        k1 = register_fleet_cylinders(site_id=site["id"], count=2, fill="FULL",
                                      serial_prefix="FK")[0]
        register_fleet_cylinders(site_id=site["id"], count=1, fill="EMPTY", serial_prefix="FK")
        customer = register_customer_cylinder(fill="EMPTY")
        order = create_order(site["id"], CLERK1)
        ticket = create_ticket(site["id"], customer["id"], CLERK1, pre_weight_lbs=17.50)
        leak = report_leak(site["id"], CLERK1, severity="MAJOR", note="smell at cage")

        confirm_leak(leak["id"], OFFICER1)

        cyl = validate_success(api.get_cylinder(k1["id"], ADMIN), 200)
        assert cyl["fill_status"] == "QUARANTINED"
        site_after = get_site(site["id"])
        assert site_after["full_on_hand"] == 0
        assert site_after["empty_on_hand"] == 0
        assert site_after["quarantined_on_hand"] == 3
        assert site_after["restock_alert"] is True, "0 <= floor 6"
        assert site_after["sales_posture"] == "SALES_BLOCKED"
        order_after = validate_success(api.get_exchange_order(order["id"], ADMIN), 200)
        assert order_after["status"] == "VOIDED"
        assert order_after["void_reason"] == "SAFETY"
        ticket_after = validate_success(api.get_refill_ticket(ticket["id"], ADMIN), 200)
        assert ticket_after["status"] == "VOIDED"

    def test_minor_leak_without_quarantine_does_not_block(self, api):
        """PRD §3.5: "A `MINOR` confirmed leak without a quarantine recommendation engages no cage quarantine and does not block sales."

        Design: Difficulty/transitive_cascade/leak_confirm_quarantine_chain
        """
        site, _policy = create_priced_site()
        register_fleet_cylinders(site_id=site["id"], count=1, fill="FULL", serial_prefix="FM")
        order = create_order(site["id"], CLERK1)
        leak = report_leak(site["id"], CLERK1, severity="MINOR")
        confirm_leak(leak["id"], OFFICER1)
        site_after = get_site(site["id"])
        assert site_after["full_on_hand"] == 1, "no quarantine engaged"
        assert site_after["quarantined_on_hand"] == 0
        assert site_after["sales_posture"] == "SALES_OPEN"
        order_after = validate_success(api.get_exchange_order(order["id"], ADMIN), 200)
        assert order_after["status"] == "DRAFT", "no safety auto-void"


class TestLeakReportRules:
    def test_second_open_leak_rejected(self, api):
        """PRD §3.5: "A site may carry at most one open leak — that is, one report in `REPORTED` or `CONFIRMED` status — and a second filing is rejected with `ERR_LEAK_ALREADY_OPEN`."

        Design: Corner/validations/second_open_leak_rejected
        """
        site = create_site(name="Leak Duo Site")
        report_leak(site["id"], CLERK1, severity="MINOR")
        res = api.create_leak_report({"site_id": site["id"], "severity": "MAJOR"}, CLERK2)
        validate_error(res, ApiErrorId.ERR_LEAK_ALREADY_OPEN, expected_status=409)

    def test_false_alarm_confirmed_leak_rejected(self, api):
        """PRD §3.5: "Marking the report a false alarm moves it to `FALSE_ALARM` and records the supplied `reason` text into `false_alarm_reason`; nothing else changes." — false alarm is an adjudication of a `REPORTED` report; a `CONFIRMED` report is past that point.
        PRD §2.7 (stage 6): "The target resource is in a valid from-state for the requested transition, terminal states are locked against further action, the site is `ACTIVE` for sales and dispatch (`ERR_SITE_NOT_ACTIVE`), and a driver's arrival date matches the run's planned date; otherwise `ERR_INVALID_STATE`."

        Design: Corner/state_machines/false_alarm_confirmed_leak_rejected
        """
        site = create_site(name="False Alarm Site")
        leak = report_leak(site["id"], CLERK1, severity="MINOR")
        confirm_leak(leak["id"], OFFICER1)
        res = api.false_alarm_leak_report(leak["id"], {"reason": "gauge misread"}, OFFICER1)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_resolve_leak_without_reinspection_rejected(self, api):
        """PRD §3.5: "for quarantining leaks it requires re-inspection evidence: at least one certification record with `outcome` `PASS` in `RECORDED` status, `performed_on` on or after the report's `confirmed_on`, for a fleet cylinder whose `current_site_id` is the affected site — without that evidence the resolution is rejected with `ERR_REINSPECTION_REQUIRED`."

        Design: Corner/validations/resolve_leak_without_reinspection_rejected
        """
        site = create_site(name="Reinspect Site")
        register_fleet_cylinders(site_id=site["id"], count=1, fill="FULL", serial_prefix="RI")
        leak = report_leak(site["id"], CLERK1, severity="MAJOR")
        confirm_leak(leak["id"], OFFICER1)
        res = api.resolve_leak_report(leak["id"], {"resolution_note": "looks fine"}, OFFICER1)
        validate_error(res, ApiErrorId.ERR_REINSPECTION_REQUIRED, expected_status=409)


class TestRestockAlertThreshold:
    def test_restock_alert_floor_threshold_inclusive(self, api):
        """PRD §2.8: "`reorder_floor_full` is the site's `par_level_full` multiplied by one-half and rounded up to a whole cylinder, and `restock_alert` is true exactly when `full_on_hand` is less than or equal to `reorder_floor_full` — the threshold is inclusive."
        PRD §3.5: "Quarantining a cylinder moves it from `FULL` or `EMPTY` to `QUARANTINED` — an optional `note` may be attached — and releasing a quarantined cylinder returns it to service as `EMPTY`, but only when its `cert_status` is `CERTIFIED`"

        Design: Corner/cross_cutting_layers/restock_alert_floor_threshold_inclusive
        """
        site = create_site(name="Alert Site")  # par 12 -> reorder_floor 6
        cyls = register_fleet_cylinders(site_id=site["id"], count=7, fill="FULL",
                                        serial_prefix="T")
        before = get_site(site["id"])
        assert before["full_on_hand"] == 7
        assert before["restock_alert"] is False, "7 > 6"
        validate_success(api.quarantine_cylinder(cyls[0]["id"], {}, OFFICER1), 200)
        after = get_site(site["id"])
        assert after["full_on_hand"] == 6
        assert after["quarantined_on_hand"] == 1
        assert after["restock_alert"] is True, "6 <= 6, inclusive"
