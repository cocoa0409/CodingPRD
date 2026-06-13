"""Role-based access control and optimistic concurrency on the affected-lot
write path.

Corner queue: rbac section, cross_cutting_complexity_layers section.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    TEST_USERS, make_headers, build_user_headers,
    ApiErrorId,
    create_product, create_lot, create_customer, create_unit,
    create_recall, add_affected_lot, classify_recall, current_recall_version,
    draft_and_submit_initial_report,
    setup_announced_recall,
    open_returned_owed_refund,
)
from test_helpers import factories as fac

COORD = TEST_USERS["recall_coordinator_headers"]
OFFICER = TEST_USERS["quality_officer_headers"]
AGENT = TEST_USERS["field_service_agent_headers"]
CLERK = TEST_USERS["finance_clerk_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# ===========================================================================
# Corner: rbac
# ===========================================================================
def test_classify_by_quality_officer_is_forbidden(api):
    """PRD §2.1: "If the role is recognized but is not permitted to invoke the
    requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`." PRD
    §4 (classify): "`POST /recalls/{id}/classify` ... `RecallCoordinator`".

    Design: Corner/rbac/classify_by_quality_officer_forbidden
    """
    product = create_product()
    lot = create_lot(product["id"])
    recall = create_recall(product["id"], hazard_severity="MINOR")
    add_affected_lot(recall["id"], lot["id"])
    resp = api.classify_recall(recall["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_settle_refund_by_field_agent_is_forbidden(api):
    """PRD §2.1: "If the role is recognized but is not permitted to invoke the
    requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`." PRD
    §4 (settle-refund): "`POST /dispositions/{id}/settle-refund` ...
    `FinanceClerk`".

    Design: Corner/rbac/settle_refund_by_field_agent_forbidden
    """
    _p, lot, recall = setup_announced_recall(
        recall_overrides={"hazard_severity": "SERIOUS", "injury_reported": False},
        classifier_user_id="user-rb-1", announcer_user_id="user-rb-2",
    )
    cust = create_customer(contact_address="rb2@x.com")
    unit = create_unit(lot["id"], cust["id"], serial_number=5, sale_price_cents=5000)
    disp = open_returned_owed_refund(recall["id"], unit["id"], refund_basis="SALE_PRICE")
    resp = api.settle_refund(disp["id"], AGENT)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_missing_role_header_returns_401(api):
    """PRD §2.1: "If the `X-User-Role` header is missing or does not name one of
    the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_role_header_returns_401
    """
    anon = {"Content-Type": "application/json"}
    resp = api.create_product(fac.create_product_payload(sku="P-UA", name="UA", regulator="FDA", unit_list_price_cents=5000), anon)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ===========================================================================
# Corner: cross_cutting_complexity_layers — OCC on affected-lot add
# ===========================================================================
def test_occ_stale_version_on_second_affected_lot_add(api):
    """PRD §2.8: "Because each affected-lot declaration bumps `Recall.version`
    and recomputes `affected_unit_count`, a client working from a stale view of
    the recall could double-count or contradict a prior scope edit ... a mismatch
    is rejected with `ERR_STALE_VERSION` so the client cannot extend a scope it
    has not seen."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_affected_lot_add
    """
    product = create_product()
    lot1 = create_lot(product["id"], lot_code="OCCA", serial_start=1, serial_end=100)
    lot2 = create_lot(product["id"], lot_code="OCCB", serial_start=101, serial_end=200)
    recall = create_recall(product["id"], hazard_severity="MINOR")
    stale_version = recall["version"]
    # First add (consumes stale_version, bumps Recall.version).
    add_affected_lot(recall["id"], lot1["id"])
    # Second add reusing the now-stale version.
    resp = api.add_affected_lot(
        recall["id"], fac.add_affected_lot_payload(lot2["id"], stale_version), COORD
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_occ_correct_version_second_add_succeeds_and_bumps(api):
    """PRD §2.8: "The server compares that value to the recall's current
    `version`; on any mismatch the write is rejected with `ERR_STALE_VERSION` at
    HTTP 412." PRD §3.2: "On a successful declaration the system creates the
    `AffectedLot`, captures `unit_count_snapshot` equal to the lot's
    `manufactured_units` at that moment, recomputes the `affected` flag on the
    units in that lot, recomputes the recall's `affected_unit_count` and
    `effectiveness_pct`, and increments the recall's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_succeeds_and_bumps
    """
    product = create_product()
    lot1 = create_lot(product["id"], lot_code="OC2A", serial_start=1, serial_end=100)
    lot2 = create_lot(product["id"], lot_code="OC2B", serial_start=101, serial_end=200)
    recall = create_recall(product["id"], hazard_severity="MINOR")
    add_affected_lot(recall["id"], lot1["id"])
    current = current_recall_version(recall["id"])
    resp = api.add_affected_lot(
        recall["id"], fac.add_affected_lot_payload(lot2["id"], current), COORD
    )
    validate_success(resp, 201)
    listing = api.list_affected_lots(COORD, params={"recall_id": recall["id"]})
    _data, meta = validate_paginated(listing)
    assert meta["total_count"] == 2, meta["total_count"]


def test_derived_active_recall_id_set_and_cleared(api):
    """PRD §3.3: "sets the owning product's `active_recall_id` to this recall's
    id." PRD §3.11: "Either close — to `EFFECTIVE` or to `TERMINATED` — lifts
    every `ACTIVE` quarantine hold on the recall's affected lots, recomputes each
    released lot's `quarantine_status` to `RELEASED`, and clears the owning
    product's `active_recall_id`."

    Design: Corner/cross_cutting_complexity_layers/derived_active_recall_id_set_and_cleared
    """
    from test_helpers import (
        setup_recall_with_recovery, record_effectiveness_check, draft_and_submit_final_report,
    )
    # CLASS_III recall, 1 of 1 returned -> 100% -> PASS, FINAL filed -> EFFECTIVE.
    product, _l, recall, _units = setup_recall_with_recovery(
        num_units=1, num_returned=1, recall_overrides={"hazard_severity": "MINOR"}, sale_price_cents=5000
    )
    # active_recall_id was set at classify.
    prod_mid = validate_success(api.get_product(product["id"], COORD), 200)
    assert prod_mid["active_recall_id"] == recall["id"], prod_mid["active_recall_id"]
    check = record_effectiveness_check(recall["id"])
    assert check["outcome"] == "PASS", check["outcome"]
    draft_and_submit_final_report(recall["id"])
    closed = validate_success(
        api.terminate_recall(recall["id"], make_headers("user-announcer-1", "QualityOfficer")), 200
    )
    assert closed["status"] == "EFFECTIVE", closed["status"]
    prod_after = validate_success(api.get_product(product["id"], COORD), 200)
    assert prod_after["active_recall_id"] is None, prod_after["active_recall_id"]
