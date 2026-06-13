"""Business-rule validations: classification gates, disposition guards,
report/monitor gates, and the effectiveness-not-met close.

Corner queue: validations section.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    TEST_USERS, make_headers,
    ApiErrorId,
    create_product, create_lot, create_customer, create_unit,
    create_recall, add_affected_lot, classify_recall, current_recall_version,
    draft_and_submit_initial_report, draft_and_submit_final_report,
    send_all_notifications, record_effectiveness_check,
    setup_announced_recall, setup_monitoring_recall, setup_recall_with_recovery,
    open_disposition, open_and_return_disposition, open_returned_owed_refund,
    settle_refund,
)
from test_helpers import factories as fac

COORD = TEST_USERS["recall_coordinator_headers"]
OFFICER = TEST_USERS["quality_officer_headers"]
AGENT = TEST_USERS["field_service_agent_headers"]
CLERK = TEST_USERS["finance_clerk_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def test_classify_without_affected_lots_returns_409(api):
    """PRD §3.3: "Classification is refused if the recall has zero affected lots,
    rejected with `ERR_NO_AFFECTED_LOTS`."

    Design: Corner/validations/classify_without_affected_lots_returns_409
    """
    product = create_product()
    recall = create_recall(product["id"], hazard_severity="MINOR")
    resp = api.classify_recall(recall["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_NO_AFFECTED_LOTS.value)


def test_invalid_serial_filter_on_classify_returns_422(api):
    """PRD §3.3: "It is also refused if a serial filter is present but inverted —
    that is, if both `serial_filter_start` and `serial_filter_end` are present and
    the start exceeds the end — rejected with `ERR_INVALID_SERIAL_FILTER`."

    Design: Corner/validations/invalid_serial_filter_returns_422
    """
    product = create_product()
    lot = create_lot(product["id"])
    recall = create_recall(product["id"], hazard_severity="MINOR", serial_filter_start=90, serial_filter_end=10)
    add_affected_lot(recall["id"], lot["id"])
    resp = api.classify_recall(recall["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_INVALID_SERIAL_FILTER.value)


def test_classify_no_affected_lots_takes_priority_over_serial_filter(api):
    """PRD §3.3: "Between these two, the affected-lots prerequisite is evaluated
    as the conflict-class check and the inverted-filter check as the
    malformed-input check." PRD §3.3: "Classification is refused if the recall has
    zero affected lots, rejected with `ERR_NO_AFFECTED_LOTS`."

    Design: Corner/validations/classify_no_affected_lots_priority_over_serial_filter
    """
    product = create_product()
    recall = create_recall(product["id"], hazard_severity="MINOR", serial_filter_start=90, serial_filter_end=10)
    resp = api.classify_recall(recall["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_NO_AFFECTED_LOTS.value)


def test_disposition_on_unaffected_unit_returns_409(api):
    """PRD §3.9: "The unit must actually be affected: a disposition may be opened
    only for a unit whose `affected` flag is true under the recall, and otherwise
    is rejected with `ERR_UNIT_NOT_AFFECTED`."

    Design: Corner/validations/disposition_on_unaffected_unit_returns_409
    """
    product = create_product()
    lot = create_lot(product["id"])
    cust = create_customer(contact_address="una@x.com")
    # serial 50 is outside the recall's [1..5] filter -> not affected.
    unit = create_unit(lot["id"], cust["id"], serial_number=50, sale_price_cents=5000)
    recall = create_recall(product["id"], hazard_severity="SERIOUS", injury_reported=False,
                           serial_filter_start=1, serial_filter_end=5)
    add_affected_lot(recall["id"], lot["id"])
    classify_recall(recall["id"], make_headers("user-una-1", "RecallCoordinator"))
    draft_and_submit_initial_report(recall["id"])
    validate_success(
        api.announce_recall(recall["id"], make_headers("user-una-2", "QualityOfficer")), 200
    )
    ver = current_recall_version(recall["id"])
    resp = api.create_disposition(
        fac.create_disposition_payload(recall["id"], unit["id"], ver, disposition_type="RETURN"), AGENT
    )
    validate_error(resp, ApiErrorId.ERR_UNIT_NOT_AFFECTED.value)


def test_duplicate_pending_disposition_returns_409(api):
    """PRD §3.9: "There may be at most one open disposition (one whose
    `logistics_status` is `PENDING`) per recall-and-unit pair, and a duplicate is
    rejected with `ERR_DUPLICATE_DISPOSITION`."

    Design: Corner/validations/duplicate_pending_disposition_returns_409
    """
    _p, lot, recall = setup_announced_recall(
        recall_overrides={"hazard_severity": "SERIOUS", "injury_reported": False},
        classifier_user_id="user-dd-1", announcer_user_id="user-dd-2",
    )
    cust = create_customer(contact_address="dd@x.com")
    unit = create_unit(lot["id"], cust["id"], serial_number=8, sale_price_cents=5000)
    open_disposition(recall["id"], unit["id"], disposition_type="RETURN")
    ver = current_recall_version(recall["id"])
    resp = api.create_disposition(
        fac.create_disposition_payload(recall["id"], unit["id"], ver, disposition_type="RETURN"), AGENT
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_DISPOSITION.value)


def test_accrue_refund_before_return_received_returns_409(api):
    """PRD §3.9: "a `FinanceClerk` accrues a refund liability ... and the unit's
    return has already been received — that is, the `logistics_status` is
    `RETURNED` (otherwise `ERR_RETURN_NOT_RECEIVED`)."

    Design: Corner/validations/accrue_refund_before_return_received_returns_409
    """
    _p, lot, recall = setup_announced_recall(
        recall_overrides={"hazard_severity": "SERIOUS", "injury_reported": False},
        classifier_user_id="user-rnr-1", announcer_user_id="user-rnr-2",
    )
    cust = create_customer(contact_address="rnr@x.com")
    unit = create_unit(lot["id"], cust["id"], serial_number=2, sale_price_cents=5000)
    disp = open_disposition(recall["id"], unit["id"], disposition_type="REFUND", refund_basis="SALE_PRICE")
    resp = api.accrue_refund(disp["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_RETURN_NOT_RECEIVED.value)


def test_ship_replacement_on_return_type_returns_type_mismatch(api):
    """PRD §3.9: "An agent ships a replacement, moving `logistics_status` from
    `PENDING` to `REPLACED`; this requires the `disposition_type` to be exactly
    `REPLACE` (otherwise `ERR_DISPOSITION_TYPE_MISMATCH`)".

    Design: Corner/validations/disposition_type_mismatch_on_ship_replacement_returns_409
    """
    _p, lot, recall = setup_announced_recall(
        recall_overrides={"hazard_severity": "SERIOUS", "injury_reported": False},
        classifier_user_id="user-tm-1", announcer_user_id="user-tm-2",
    )
    cust = create_customer(contact_address="tm@x.com")
    unit = create_unit(lot["id"], cust["id"], serial_number=9, sale_price_cents=5000)
    disp = open_disposition(recall["id"], unit["id"], disposition_type="RETURN")
    resp = api.ship_replacement(disp["id"], AGENT)
    validate_error(resp, ApiErrorId.ERR_DISPOSITION_TYPE_MISMATCH.value)


def test_reclassify_after_report_filed_returns_409(api):
    """PRD §3.3: "Reclassification is forbidden, however, once the recall's
    paperwork has begun: if any `RegulatoryReport` for the recall is already
    `SUBMITTED` or `ACKNOWLEDGED`, the reclassify is rejected with
    `ERR_REPORT_ALREADY_FILED`."

    Design: Corner/validations/reclassify_after_report_filed_returns_409
    """
    product = create_product()
    lot = create_lot(product["id"])
    recall = create_recall(product["id"], hazard_severity="SERIOUS", injury_reported=False)
    add_affected_lot(recall["id"], lot["id"])
    classify_recall(recall["id"], COORD)
    draft_and_submit_initial_report(recall["id"])
    resp = api.reclassify_recall(recall["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_REPORT_ALREADY_FILED.value)


def test_begin_monitoring_with_queued_notification_returns_409(api):
    """PRD §3.8: "A `RecallCoordinator` begins monitoring ... but only when every
    notification for the recall is in `SENT`, `ACKNOWLEDGED`, or `FAILED` — that
    is, none remain `QUEUED`. An attempt with at least one `QUEUED` notification
    still outstanding is rejected with `ERR_NOTIFICATIONS_PENDING`."

    Design: Corner/validations/begin_monitoring_with_queued_notification_returns_409
    """
    product = create_product()
    lot = create_lot(product["id"])
    cust = create_customer(contact_address="np@x.com")
    create_unit(lot["id"], cust["id"], serial_number=4, sale_price_cents=5000)
    recall = create_recall(product["id"], hazard_severity="SERIOUS", injury_reported=False)
    add_affected_lot(recall["id"], lot["id"])
    classify_recall(recall["id"], make_headers("user-np-1", "RecallCoordinator"))
    draft_and_submit_initial_report(recall["id"])
    validate_success(
        api.announce_recall(recall["id"], make_headers("user-np-2", "QualityOfficer")), 200
    )
    # Notification stays QUEUED (never sent).
    resp = api.begin_monitoring(recall["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_NOTIFICATIONS_PENDING.value)


def test_submit_report_while_recall_draft_returns_409(api):
    """PRD §3.5: "Submission is refused while the owning recall is still `DRAFT`,
    because a classification must exist before anything is filed; that attempt is
    rejected with `ERR_RECALL_NOT_CLASSIFIED`."

    Design: Corner/validations/submit_report_while_recall_draft_returns_409
    """
    product = create_product()
    recall = create_recall(product["id"], hazard_severity="MINOR")
    report = validate_success(
        api.create_report(fac.create_report_payload(recall["id"], report_kind="INITIAL"), COORD), 201
    )
    resp = api.submit_report(report["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_RECALL_NOT_CLASSIFIED.value)


def test_cancel_refunded_disposition_returns_409(api):
    """PRD §3.9: "An agent may also cancel a disposition ... cancellation is
    refused if the disposition has already been refunded (`financial_status` of
    `REFUNDED`), rejected with `ERR_DISPOSITION_ALREADY_REFUNDED`."

    Design: Corner/validations/cancel_refunded_disposition_returns_409
    """
    _p, lot, recall = setup_announced_recall(
        recall_overrides={"hazard_severity": "SERIOUS", "injury_reported": False},
        classifier_user_id="user-car-1", announcer_user_id="user-car-2",
    )
    cust = create_customer(contact_address="car@x.com")
    unit = create_unit(lot["id"], cust["id"], serial_number=7, sale_price_cents=5000)
    disp = open_returned_owed_refund(recall["id"], unit["id"], refund_basis="SALE_PRICE")
    settle_refund(disp["id"])
    resp = api.cancel_disposition(disp["id"], AGENT)
    validate_error(resp, ApiErrorId.ERR_DISPOSITION_ALREADY_REFUNDED.value)


def test_terminate_effective_without_pass_check_returns_effectiveness_not_met(api):
    """PRD §3.11: "When `force_terminate` is false (or omitted) and the latest
    effectiveness check fails, the close is rejected with
    `ERR_EFFECTIVENESS_NOT_MET` rather than terminating."

    Design: Corner/validations/terminate_effective_without_pass_check_returns_409
    """
    # MONITORING, effectiveness 0 (no returns), a FAIL check recorded, FINAL filed.
    _p, _l, recall = setup_monitoring_recall(
        recall_overrides={"hazard_severity": "SERIOUS", "injury_reported": True},
        classifier_user_id="user-enm-1", announcer_user_id="user-enm-2",
    )
    check = record_effectiveness_check(recall["id"])
    assert check["outcome"] == "FAIL", check["outcome"]
    draft_and_submit_final_report(recall["id"])
    resp = api.terminate_recall(recall["id"], make_headers("user-enm-2", "QualityOfficer"), {"force_terminate": False})
    validate_error(resp, ApiErrorId.ERR_EFFECTIVENESS_NOT_MET.value)
