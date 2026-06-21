"""Composite setup helpers for the Product Recall & Field Action API.

Every test starts against an empty database (the runner restarts the server
before each test), so each fixture builds all of its preconditions from
scratch using only PRD-declared endpoints.

Key OCC discipline (PRD §2.8): the two guarded writes — declare-affected-lot
and open-disposition — require `expected_recall_version` to equal the recall's
CURRENT version. Each affected-lot add and each disposition open bumps
Recall.version, so these helpers always re-read the recall's live version
immediately before issuing a guarded write.

All helpers use get_success_data() (lenient) so setup failures surface as
clear "Setup failed" errors rather than confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_headers
from . import factories as fac


# ---------------------------------------------------------------------------
# Header shortcuts
# ---------------------------------------------------------------------------
def _admin():
    return TEST_USERS["platform_admin_headers"]


def _coord():
    return TEST_USERS["recall_coordinator_headers"]


def _officer():
    return TEST_USERS["quality_officer_headers"]


def _agent():
    return TEST_USERS["field_service_agent_headers"]


def _clerk():
    return TEST_USERS["finance_clerk_headers"]


# ---------------------------------------------------------------------------
# Tier 1: primitive resource creators
# ---------------------------------------------------------------------------
def create_product(**overrides) -> dict:
    payload = fac.create_product_payload(**overrides)
    return get_success_data(api_client.create_product(payload, _admin()))


def create_lot(product_id, **overrides) -> dict:
    payload = fac.create_lot_payload(product_id, **overrides)
    return get_success_data(api_client.create_lot(payload, _coord()))


def create_customer(**overrides) -> dict:
    payload = fac.create_customer_payload(**overrides)
    return get_success_data(api_client.create_customer(payload, _agent()))


def create_unit(lot_id, customer_id, **overrides) -> dict:
    payload = fac.create_unit_payload(lot_id, customer_id, **overrides)
    return get_success_data(api_client.create_unit(payload, _agent()))


def create_recall(product_id, **overrides) -> dict:
    payload = fac.create_recall_payload(product_id, **overrides)
    return get_success_data(api_client.create_recall(payload, _coord()))


def current_recall_version(recall_id) -> int:
    """Live version of the recall — re-read before every OCC-guarded write."""
    data = get_success_data(api_client.get_recall(recall_id, _agent()))
    return data["version"]


def add_affected_lot(recall_id, lot_id) -> dict:
    """Declare a lot affected, reading the recall's current version first (OCC)."""
    ver = current_recall_version(recall_id)
    payload = fac.add_affected_lot_payload(lot_id, ver)
    return get_success_data(api_client.add_affected_lot(recall_id, payload, _coord()))


# ---------------------------------------------------------------------------
# Tier 2: product + lot (+ optional customers/units) bundles
# ---------------------------------------------------------------------------
def setup_product_and_lot(product_overrides=None, lot_overrides=None):
    """Return (product, lot)."""
    product = create_product(**(product_overrides or {}))
    lot = create_lot(product["id"], **(lot_overrides or {}))
    return product, lot


def setup_units(lot_id, specs):
    """Create N units. `specs` is a list of dicts of per-unit overrides
    (each typically {serial_number, sale_price_cents, customer_id}).
    Returns the list of created unit dicts.
    """
    units = []
    for spec in specs:
        units.append(create_unit(lot_id, spec.pop("customer_id"), **spec))
    return units


# ---------------------------------------------------------------------------
# Tier 3: recall lifecycle shortcuts
# ---------------------------------------------------------------------------
def setup_draft_recall_with_lot(product_overrides=None, lot_overrides=None, recall_overrides=None):
    """Product + lot + DRAFT recall with that lot declared affected.
    Returns (product, lot, recall). The returned recall dict is the live
    GET after the affected-lot add (version reflects the add).
    """
    product, lot = setup_product_and_lot(product_overrides, lot_overrides)
    recall = create_recall(product["id"], **(recall_overrides or {}))
    add_affected_lot(recall["id"], lot["id"])
    recall = get_success_data(api_client.get_recall(recall["id"], _coord()))
    return product, lot, recall


def classify_recall(recall_id, coordinator_headers=None, payload=None) -> dict:
    headers = coordinator_headers or _coord()
    return get_success_data(api_client.classify_recall(recall_id, headers, payload or {}))


def draft_and_submit_initial_report(recall_id) -> dict:
    """Draft an INITIAL report (coordinator) and submit it (officer).
    Returns the submitted report dict."""
    report = get_success_data(
        api_client.create_report(fac.create_report_payload(recall_id, report_kind="INITIAL"), _coord())
    )
    return get_success_data(api_client.submit_report(report["id"], _officer()))


def draft_and_submit_final_report(recall_id) -> dict:
    report = get_success_data(
        api_client.create_report(fac.create_report_payload(recall_id, report_kind="FINAL"), _coord())
    )
    return get_success_data(api_client.submit_report(report["id"], _officer()))


def setup_classified_recall(
    product_overrides=None,
    lot_overrides=None,
    recall_overrides=None,
    classifier_user_id="user-classifier-1",
):
    """Product + lot + recall classified (DRAFT -> CLASSIFIED).
    The classifying coordinator carries `classifier_user_id` so segregation
    tests can drive a distinct announcer later.
    Returns (product, lot, recall_after_classify).
    """
    product, lot, recall = setup_draft_recall_with_lot(
        product_overrides, lot_overrides, recall_overrides
    )
    classify_recall(recall["id"], make_headers(classifier_user_id, "RecallCoordinator"))
    recall = get_success_data(api_client.get_recall(recall["id"], _coord()))
    return product, lot, recall


def setup_announced_recall(
    product_overrides=None,
    lot_overrides=None,
    recall_overrides=None,
    classifier_user_id="user-classifier-1",
    announcer_user_id="user-announcer-1",
):
    """Full chain to ANNOUNCED: classify (by classifier) -> draft+submit
    INITIAL report -> announce (by a DISTINCT announcer to satisfy four-eyes).
    Returns (product, lot, recall_after_announce).
    """
    product, lot, recall = setup_classified_recall(
        product_overrides, lot_overrides, recall_overrides, classifier_user_id
    )
    draft_and_submit_initial_report(recall["id"])
    get_success_data(
        api_client.announce_recall(recall["id"], make_headers(announcer_user_id, "QualityOfficer"))
    )
    recall = get_success_data(api_client.get_recall(recall["id"], _coord()))
    return product, lot, recall


def send_all_notifications(recall_id):
    """Send every QUEUED notification for the recall (admin). Returns the
    list of notification dicts after sending. Customers must be reachable."""
    listing = api_client.list_notifications(_admin(), params={"recall_id": recall_id})
    data, _meta = _list_payload(listing)
    sent = []
    for notif in data:
        sent.append(get_success_data(api_client.send_notification(notif["id"], _admin())))
    return sent


def setup_monitoring_recall(
    product_overrides=None,
    lot_overrides=None,
    recall_overrides=None,
    classifier_user_id="user-classifier-1",
    announcer_user_id="user-announcer-1",
):
    """Chain to MONITORING: announce -> send all notifications -> begin-monitoring.
    Returns (product, lot, recall_after_monitoring).
    """
    product, lot, recall = setup_announced_recall(
        product_overrides, lot_overrides, recall_overrides, classifier_user_id, announcer_user_id
    )
    send_all_notifications(recall["id"])
    get_success_data(api_client.begin_monitoring(recall["id"], _coord()))
    recall = get_success_data(api_client.get_recall(recall["id"], _coord()))
    return product, lot, recall


# ---------------------------------------------------------------------------
# Tier 4: dispositions (OCC version-threaded)
# ---------------------------------------------------------------------------
def open_disposition(recall_id, unit_id, **overrides) -> dict:
    """Open a disposition, reading the recall's current version first (OCC).
    Pass disposition_type / refund_basis via overrides."""
    ver = current_recall_version(recall_id)
    payload = fac.create_disposition_payload(recall_id, unit_id, ver, **overrides)
    return get_success_data(api_client.create_disposition(payload, _agent()))


def open_disposition_raw(recall_id, unit_id, expected_recall_version, **overrides):
    """Open a disposition with an EXPLICIT expected_recall_version (returns the
    raw Response, no success assertion) — for OCC stale-version negative tests."""
    payload = fac.create_disposition_payload(
        recall_id, unit_id, expected_recall_version, **overrides
    )
    return api_client.create_disposition(payload, _agent())


def open_and_return_disposition(recall_id, unit_id, **overrides) -> dict:
    """Open a RETURN/REFUND disposition and receive its return (logistics
    PENDING -> RETURNED). Returns the disposition dict after receive-return."""
    disp = open_disposition(recall_id, unit_id, **overrides)
    return get_success_data(api_client.receive_return(disp["id"], _agent()))


def open_returned_owed_refund(recall_id, unit_id, refund_basis="SALE_PRICE") -> dict:
    """REFUND disposition driven to RETURNED + OWED (accrue done, not settled).
    Returns the disposition dict after accrue-refund."""
    disp = open_disposition(
        recall_id, unit_id, disposition_type="REFUND", refund_basis=refund_basis
    )
    get_success_data(api_client.receive_return(disp["id"], _agent()))
    return get_success_data(api_client.accrue_refund(disp["id"], _clerk()))


def settle_refund(disposition_id) -> dict:
    return get_success_data(api_client.settle_refund(disposition_id, _clerk()))


# ---------------------------------------------------------------------------
# Tier 5: effectiveness / closure builders
# ---------------------------------------------------------------------------
def setup_recall_with_recovery(
    num_units,
    num_returned,
    product_overrides=None,
    lot_overrides=None,
    recall_overrides=None,
    sale_price_cents=10000,
):
    """MONITORING recall with `num_units` affected units, `num_returned` of
    them driven to RETURNED (RETURN-type dispositions). Returns
    (product, lot, recall, units). Each unit goes to a distinct customer so
    notification fan-out produces one notification per customer.
    """
    product, lot = setup_product_and_lot(product_overrides, lot_overrides)
    units = []
    for i in range(num_units):
        cust = create_customer(contact_address=f"c{i}@example.com")
        units.append(
            create_unit(lot["id"], cust["id"], serial_number=i + 1, sale_price_cents=sale_price_cents)
        )
    recall = create_recall(product["id"], **(recall_overrides or {}))
    add_affected_lot(recall["id"], lot["id"])
    classify_recall(recall["id"], make_headers("user-classifier-1", "RecallCoordinator"))
    draft_and_submit_initial_report(recall["id"])
    get_success_data(
        api_client.announce_recall(recall["id"], make_headers("user-announcer-1", "QualityOfficer"))
    )
    send_all_notifications(recall["id"])
    get_success_data(api_client.begin_monitoring(recall["id"], _coord()))
    for i in range(num_returned):
        open_and_return_disposition(recall["id"], units[i]["id"], disposition_type="RETURN")
    recall = get_success_data(api_client.get_recall(recall["id"], _coord()))
    return product, lot, recall, units


def record_effectiveness_check(recall_id) -> dict:
    return get_success_data(
        api_client.create_effectiveness_check(
            fac.create_effectiveness_check_payload(recall_id), _coord()
        )
    )


def get_first_quarantine_hold(recall_id) -> dict:
    listing = api_client.list_quarantine_holds(_coord(), params={"recall_id": recall_id})
    data, _meta = _list_payload(listing)
    assert data, f"Setup failed: no quarantine hold for recall {recall_id}"
    return data[0]


def get_first_notification(recall_id) -> dict:
    listing = api_client.list_notifications(_admin(), params={"recall_id": recall_id})
    data, _meta = _list_payload(listing)
    assert data, f"Setup failed: no notification for recall {recall_id}"
    return data[0]


# ---------------------------------------------------------------------------
# Internal: tolerant list-envelope reader for setup
# ---------------------------------------------------------------------------
def _list_payload(response):
    body = response.json()
    if not (200 <= response.status_code < 300):
        raise AssertionError(
            f"Setup list call failed with HTTP {response.status_code}: {response.text}"
        )
    return body["data"], body.get("meta", {})
