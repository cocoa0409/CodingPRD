"""Validation precedence conflicts, cross-entity state dependencies, and
resource overlap (lot ranges, recall windows).

Difficulty queue: priority_pair_validation_conflict, cross_entity_state_dependency,
resource_temporal_overlap.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    TEST_USERS, make_headers,
    ApiErrorId,
    create_product, create_lot, create_customer, create_unit,
    create_recall, add_affected_lot, classify_recall,
    current_recall_version,
    draft_and_submit_initial_report,
    setup_draft_recall_with_lot, setup_classified_recall,
)
from test_helpers import factories as fac

COORD = TEST_USERS["recall_coordinator_headers"]
OFFICER = TEST_USERS["quality_officer_headers"]
AGENT = TEST_USERS["field_service_agent_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# ===========================================================================
# priority_pair_validation_conflict — state (p6) beats segregation (p7)
# ===========================================================================
def test_double_announce_by_classifier_returns_invalid_state_not_segregation(api):
    """PRD §2.7: "The generic state check comes sixth: a transition attempted
    from a state that does not permit it yields `ERR_INVALID_STATE`. Only after
    all of these pass does the system evaluate domain-specific business rules".

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_segregation_on_double_announce
    """
    # Classified by U1, announced by U2 (now ANNOUNCED); U1 re-announces.
    _p, _l, recall = setup_classified_recall(
        recall_overrides={"hazard_severity": "SERIOUS", "injury_reported": False},
        classifier_user_id="user-u1",
    )
    draft_and_submit_initial_report(recall["id"])
    validate_success(
        api.announce_recall(recall["id"], make_headers("user-u2", "QualityOfficer")), 200
    )
    # Re-announce by U1 (the classifier): state is ANNOUNCED (p6) AND would breach
    # segregation (p7); state wins.
    resp = api.announce_recall(recall["id"], make_headers("user-u1", "QualityOfficer"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_announce_by_classifier_without_report_returns_segregation_first(api):
    """PRD §3.6: "First, four-eyes segregation of duties: the announcing officer's
    `X-User-ID` must differ from the recall's `classified_by_user_id`; the same
    user may not both classify and approve the same recall, and a violation is
    rejected with `ERR_SEGREGATION_OF_DUTIES`. Second, the paperwork prerequisite:
    at least one `INITIAL` regulatory report for this recall must already be
    `SUBMITTED` or `ACKNOWLEDGED`, and an announcement without it is rejected with
    `ERR_INITIAL_REPORT_REQUIRED`."

    Design: Difficulty/priority_pair_validation_conflict/segregation_beats_missing_initial_report_on_announce
    """
    # Classified by U1, NO initial report. U1 attempts announce: both p7 and p8
    # would fire; segregation (first) wins.
    _p, _l, recall = setup_classified_recall(
        recall_overrides={"hazard_severity": "SERIOUS", "injury_reported": False},
        classifier_user_id="user-u1",
    )
    resp = api.announce_recall(recall["id"], make_headers("user-u1", "QualityOfficer"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


def test_reannounce_by_noncllassifier_still_invalid_state(api):
    """PRD §2.7: "The generic state check comes sixth: a transition attempted
    from a state that does not permit it yields `ERR_INVALID_STATE`. Only after
    all of these pass does the system evaluate domain-specific business rules".

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_segregation_on_double_announce
    """
    # Classified by U1, announced by U2 (ANNOUNCED). A THIRD user U3 (neither the
    # classifier nor barred by segregation) re-announces: the state check (p6)
    # still pre-empts every business rule, so ERR_INVALID_STATE is returned.
    _p, _l, recall = setup_classified_recall(
        recall_overrides={"hazard_severity": "SERIOUS", "injury_reported": False},
        classifier_user_id="user-u1",
    )
    draft_and_submit_initial_report(recall["id"])
    validate_success(
        api.announce_recall(recall["id"], make_headers("user-u2", "QualityOfficer")), 200
    )
    resp = api.announce_recall(recall["id"], make_headers("user-u3", "QualityOfficer"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_self_announce_with_report_present_isolates_segregation(api):
    """PRD §3.6: "First, four-eyes segregation of duties: the announcing officer's
    `X-User-ID` must differ from the recall's `classified_by_user_id`; the same
    user may not both classify and approve the same recall, and a violation is
    rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Difficulty/priority_pair_validation_conflict/segregation_beats_missing_initial_report_on_announce
    """
    # INITIAL report IS submitted (so the paperwork gate would pass); the only
    # failing gate is segregation when the classifier self-announces.
    _p, _l, recall = setup_classified_recall(
        recall_overrides={"hazard_severity": "SERIOUS", "injury_reported": False},
        classifier_user_id="user-u1",
    )
    draft_and_submit_initial_report(recall["id"])
    resp = api.announce_recall(recall["id"], make_headers("user-u1", "QualityOfficer"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


# Corner: announce_segregation_breach is excluded_because it is owned by the
# difficulty instance segregation_beats_missing_initial_report_on_announce above.


# ===========================================================================
# cross_entity_state_dependency — announce requires INITIAL report SUBMITTED
# ===========================================================================
def test_announce_without_submitted_initial_report_blocked(api):
    """PRD §3.6: "Second, the paperwork prerequisite: at least one `INITIAL`
    regulatory report for this recall must already be `SUBMITTED` or
    `ACKNOWLEDGED`, and an announcement without it is rejected with
    `ERR_INITIAL_REPORT_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/announce_requires_initial_report_submitted
    """
    # Classified by U1; INITIAL report DRAFTED but NOT submitted. U2 announces.
    _p, _l, recall = setup_classified_recall(
        product_overrides={"regulator": "CPSC"},
        recall_overrides={"hazard_severity": "SERIOUS", "injury_reported": False},
        classifier_user_id="user-c1",
    )
    # Draft (but do not submit) an INITIAL report.
    validate_success(
        api.create_report(fac.create_report_payload(recall["id"], report_kind="INITIAL"), COORD), 201
    )
    resp = api.announce_recall(recall["id"], make_headers("user-c2", "QualityOfficer"))
    validate_error(resp, ApiErrorId.ERR_INITIAL_REPORT_REQUIRED.value)


def test_announce_succeeds_once_initial_report_submitted(api):
    """PRD §3.6: "Second, the paperwork prerequisite: at least one `INITIAL`
    regulatory report for this recall must already be `SUBMITTED` or
    `ACKNOWLEDGED`". PRD §3.6: "When both gates pass, the system records
    `approved_by_user_id` as the announcing officer's `X-User-ID`".

    Design: Difficulty/cross_entity_state_dependency/announce_requires_initial_report_submitted
    """
    # Same setup, but now SUBMIT the INITIAL report -> announce proceeds.
    _p, _l, recall = setup_classified_recall(
        product_overrides={"regulator": "CPSC"},
        recall_overrides={"hazard_severity": "SERIOUS", "injury_reported": False},
        classifier_user_id="user-c3",
    )
    draft_and_submit_initial_report(recall["id"])
    data = validate_success(
        api.announce_recall(recall["id"], make_headers("user-c4", "QualityOfficer")), 200
    )
    assert data["status"] == "ANNOUNCED", data["status"]


def test_disposition_open_requires_recall_announced_or_monitoring(api):
    """PRD §3.9: "Dispositions may be opened and advanced only while the owning
    recall is `ANNOUNCED` or `MONITORING`; outside that window the operation is
    rejected with `ERR_RECALL_NOT_OPEN_FOR_DISPOSITION`."

    Design: Difficulty/cross_entity_state_dependency/disposition_open_requires_recall_announced
    """
    # Recall only CLASSIFIED (not announced); a unit exists.
    product = create_product(regulator="CPSC", unit_list_price_cents=4000)
    lot = create_lot(product["id"])
    cust = create_customer(contact_address="ce@x.com")
    unit = create_unit(lot["id"], cust["id"], serial_number=9, sale_price_cents=4000)
    recall = create_recall(product["id"], hazard_severity="SERIOUS", injury_reported=False)
    add_affected_lot(recall["id"], lot["id"])
    classify_recall(recall["id"], COORD)
    ver = current_recall_version(recall["id"])
    payload = fac.create_disposition_payload(recall["id"], unit["id"], ver, disposition_type="RETURN")
    resp = api.create_disposition(payload, AGENT)
    validate_error(resp, ApiErrorId.ERR_RECALL_NOT_OPEN_FOR_DISPOSITION.value)


def test_disposition_open_succeeds_when_recall_announced(api):
    """PRD §3.9: "Dispositions may be opened and advanced only while the owning
    recall is `ANNOUNCED` or `MONITORING`". PRD §3.9: "A newly opened disposition
    starts with `logistics_status` of `PENDING` and `financial_status` of
    `NOT_OWED`".

    Design: Difficulty/cross_entity_state_dependency/disposition_open_requires_recall_announced
    """
    from test_helpers import setup_announced_recall
    _p, lot, recall = setup_announced_recall(
        product_overrides={"regulator": "CPSC", "unit_list_price_cents": 4000},
        recall_overrides={"hazard_severity": "SERIOUS", "injury_reported": False},
        classifier_user_id="user-do-1", announcer_user_id="user-do-2",
    )
    cust = create_customer(contact_address="do@x.com")
    unit = create_unit(lot["id"], cust["id"], serial_number=9, sale_price_cents=4000)
    ver = current_recall_version(recall["id"])
    payload = fac.create_disposition_payload(recall["id"], unit["id"], ver, disposition_type="RETURN")
    data = validate_success(api.create_disposition(payload, AGENT), 201)
    assert data["logistics_status"] == "PENDING", data["logistics_status"]


# ===========================================================================
# resource_temporal_overlap — lot closed-interval touch collision
# ===========================================================================
def test_lot_serial_range_touching_endpoint_collides(api):
    """PRD §3.1: "Touching endpoints collide — if an existing lot ends at serial
    100 and a new lot starts at serial 100, the two ranges collide because serial
    100 cannot belong to two lots — and such an attempt is rejected with
    `ERR_LOT_RANGE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/lot_serial_range_closed_interval_touch_collision
    """
    product = create_product(regulator="CPSC", unit_list_price_cents=2500)
    create_lot(product["id"], lot_code="OV-A", serial_start=1, serial_end=100)
    resp = api.create_lot(
        fac.create_lot_payload(product["id"], lot_code="OV-B", serial_start=100, serial_end=200),
        COORD,
    )
    validate_error(resp, ApiErrorId.ERR_LOT_RANGE_OVERLAP.value)


def test_lot_serial_range_contained_collides(api):
    """PRD §3.1: "Collision uses closed-interval semantics: the new range collides
    with an existing range whenever the new `serial_start` is less than or equal
    to the existing `serial_end` **and** the new `serial_end` is greater than or
    equal to the existing `serial_start`."

    Design: Difficulty/resource_temporal_overlap/lot_serial_range_closed_interval_touch_collision
    """
    product = create_product(regulator="CPSC", unit_list_price_cents=2500)
    create_lot(product["id"], lot_code="OV-C", serial_start=1, serial_end=100)
    # [40..60] is fully inside [1..100] -> overlaps.
    resp = api.create_lot(
        fac.create_lot_payload(product["id"], lot_code="OV-D", serial_start=40, serial_end=60),
        COORD,
    )
    validate_error(resp, ApiErrorId.ERR_LOT_RANGE_OVERLAP.value)


def test_recall_window_unbounded_overlaps_bounded_on_same_product(api):
    """PRD §3.2: "These windows use unbounded, extended-real semantics: a null
    `serial_filter_start` is treated as negative infinity and a null
    `serial_filter_end` as positive infinity." PRD §3.2: "A consequence worth
    noting is that, unlike finite closed lot ranges, an unbounded recall window
    collides with any other window on the same product. A violation is rejected
    with `ERR_RECALL_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/recall_window_unbounded_overlap_on_same_product
    """
    product = create_product(regulator="CPSC", unit_list_price_cents=2500)
    create_lot(product["id"], lot_code="OV2-A", serial_start=1, serial_end=100)
    # R1: bounded window [1..50], non-terminal (DRAFT).
    create_recall(product["id"], hazard_severity="MINOR", serial_filter_start=1, serial_filter_end=50)
    # R2: unbounded window (no filter) on same product -> overlaps R1.
    resp = api.create_recall(
        fac.create_recall_payload(product["id"], hazard_severity="MINOR", reason="fray-2"),
        COORD,
    )
    validate_error(resp, ApiErrorId.ERR_RECALL_WINDOW_OVERLAP.value)


def test_recall_bounded_windows_overlap_on_same_product(api):
    """PRD §3.2: "Two windows overlap when the larger of their two start bounds is
    less than or equal to the smaller of their two end bounds under that extended
    arithmetic." PRD §3.2: "A new recall's affected serial window must not overlap
    the window of any existing non-terminal recall on the same `product_id`".

    Design: Difficulty/resource_temporal_overlap/recall_window_unbounded_overlap_on_same_product
    """
    product = create_product(regulator="CPSC", unit_list_price_cents=2500)
    create_lot(product["id"], lot_code="OV3-A", serial_start=1, serial_end=100)
    # R1 bounded [1..50]; R2 bounded [40..80] -> max(1,40)=40 <= min(50,80)=50 -> overlap.
    create_recall(product["id"], hazard_severity="MINOR", serial_filter_start=1, serial_filter_end=50)
    resp = api.create_recall(
        fac.create_recall_payload(
            product["id"], hazard_severity="MINOR", reason="fray-3",
            serial_filter_start=40, serial_filter_end=80,
        ),
        COORD,
    )
    validate_error(resp, ApiErrorId.ERR_RECALL_WINDOW_OVERLAP.value)
