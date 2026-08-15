"""Insurance notifications: SLA deadlines, lateness boundary, exception path."""
from test_helpers import (
    ApiErrorId,
    assert_insurance_notification,
    assert_timestamp_equals,
    certify_screening,
    claim_exception,
    create_case,
    create_facility,
    create_notification,
    create_physician,
    create_screening,
    dispatch_case,
    drive_to_accepted,
    drive_to_awaiting,
    drive_to_dispatch_ready,
    mark_notified,
    setup_certified_case,
    set_clock,
    validate_error,
    validate_success,
)


def _certified_case_with_notification(acuity, unit, emc, stabilized, patient_ref,
                                      payer="PAYER-9", channel="PORTAL"):
    """Case certified at the default clock with a PENDING notification."""
    fac_s = create_facility()
    phys_s = create_physician("Dr Send", fac_s["id"], "EMERGENCY")
    case = create_case(fac_s["id"], phys_s["id"], acuity, unit, "TRAUMA",
                       False, patient_ref)
    create_screening(case["id"], phys_s["id"], emc, stabilized)
    certify_screening(case["id"], phys_s["id"])
    notif = create_notification(case["id"], payer, channel)
    return case, notif


class TestSlaBoundary:
    def test_notify_exactly_at_sla_is_on_time(self, api):
        """PRD: "`sla_due_at` is the case's `emtala_determined_at` plus sixty
        minutes when the obligation is `EMTALA_APPLIES`, sixty minutes under
        `EMERGENCY_EXCEPTION`, and two hundred forty minutes under
        `EMTALA_NOT_APPLIES`."
        PRD: "Marking the payer notified flips `PENDING → NOTIFIED`, stamps
        `notified_at` from the clock, and recomputes `is_late`: true only when
        a `NOTIFIED` notification's `notified_at` is strictly later than
        `sla_due_at` — a notification landing exactly at the deadline is on
        time — and false for every other status."

        Design: Difficulty/boundary_precision_check/insurance_notify_exactly_at_sla_is_on_time
        """
        case1, notif1 = _certified_case_with_notification(
            "EMERGENT", "ICU", True, True, "PT-SLA-1")
        assert_timestamp_equals(notif1["sla_due_at"], "2026-08-01T01:00:00Z")
        assert_insurance_notification(notif1)
        assert notif1["status"] == "PENDING"
        assert notif1["is_late"] is False

        set_clock("2026-08-01T01:00:00Z")  # exactly the deadline
        notified = mark_notified(notif1["id"])
        assert notified["status"] == "NOTIFIED"
        assert_timestamp_equals(notified["notified_at"], "2026-08-01T01:00:00Z")
        assert notified["is_late"] is False, "exactly at the deadline is on time"

    def test_notify_one_minute_past_sla_is_late(self, api):
        """PRD: "Marking the payer notified flips `PENDING → NOTIFIED`, stamps
        `notified_at` from the clock, and recomputes `is_late`: true only when
        a `NOTIFIED` notification's `notified_at` is strictly later than
        `sla_due_at` — a notification landing exactly at the deadline is on
        time — and false for every other status."
        PRD: "`sla_due_at` is the case's `emtala_determined_at` plus sixty
        minutes when the obligation is `EMTALA_APPLIES`, sixty minutes under
        `EMERGENCY_EXCEPTION`, and two hundred forty minutes under
        `EMTALA_NOT_APPLIES`."

        Design: Difficulty/boundary_precision_check/insurance_notify_exactly_at_sla_is_on_time
        """
        case2, notif2 = _certified_case_with_notification(
            "STABLE", "MED_SURG", False, True, "PT-SLA-2",
            payer="PAYER-7", channel="FAX")
        assert_timestamp_equals(notif2["sla_due_at"], "2026-08-01T04:00:00Z")

        set_clock("2026-08-01T04:01:00Z")  # one minute past
        notified = mark_notified(notif2["id"])
        assert notified["status"] == "NOTIFIED"
        assert notified["is_late"] is True, "strictly later than the deadline"


class TestExceptionPath:
    def test_insurance_exception_clears_dispatch_without_notify(self, api):
        """PRD: "When prior notification is not feasible, the coordinator
        instead claims the emergency exception, flipping `PENDING →
        EXCEPTION_CLAIMED`, recording an `exception_reason` of `UNSTABLE_EMC`,
        `NO_PAYER_IDENTIFIABLE`, or `CLINICAL_URGENCY`, and forcing `is_late`
        to false."
        PRD: "Finally, a notification in `NOTIFIED` or `EXCEPTION_CLAIMED`
        must exist, failing with `ERR_INSURANCE_NOT_CLEARED`."

        Design: Corner/validations/insurance_exception_clears_dispatch_without_notify
        """
        ws = setup_certified_case(acuity="EMERGENT", unit="ICU",
                                  patient_ref="PT-EXC-1")
        drive_to_awaiting(ws)
        drive_to_accepted(ws)
        drive_to_dispatch_ready(ws, notify=False)  # notification stays PENDING
        notif_id = ws["notification"]["id"]
        # 01:30 is past the 60-minute SLA but before the EMERGENT hold expiry
        # (02:00), proving the exception path never goes late.
        set_clock("2026-08-01T01:30:00Z")

        claimed = claim_exception(notif_id, "CLINICAL_URGENCY")
        assert claimed["status"] == "EXCEPTION_CLAIMED"
        assert claimed["exception_reason"] == "CLINICAL_URGENCY"
        assert claimed["is_late"] is False

        disp = dispatch_case(ws["case"]["id"], "GROUND_ALS", "ALS", 20)
        assert disp["status"] == "DISPATCHED", (
            "EXCEPTION_CLAIMED satisfies the payer-clearance gate"
        )
