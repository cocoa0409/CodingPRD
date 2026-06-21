"""Classification, notification-window, refund-amount, and effectiveness
calculations.

Difficulty queue: dual_variant_calc, combinatorial_formula.
Corner queue: calculations section.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    TEST_USERS,
    make_headers,
    create_product, create_lot, create_customer, create_unit,
    create_recall, add_affected_lot, classify_recall,
    setup_draft_recall_with_lot, setup_monitoring_recall,
    open_returned_owed_refund, settle_refund, open_and_return_disposition,
    record_effectiveness_check,
)
from test_helpers import factories as fac

COORD = TEST_USERS["recall_coordinator_headers"]
OFFICER = TEST_USERS["quality_officer_headers"]
CLERK = TEST_USERS["finance_clerk_headers"]


# ===========================================================================
# dual_variant_calc — classification depends solely on injury_reported
# ===========================================================================
def test_serious_with_injury_classifies_class_i(api):
    """PRD §3.3: "when the hazard is `SERIOUS` and an injury has been reported,
    the recall is `CLASS_I`; when the hazard is `SERIOUS` but no injury has been
    reported, it is `CLASS_II`".

    Design: Difficulty/dual_variant_calc/classification_injury_flag_drives_class_i_vs_ii
    """
    _p, _l, recall = setup_draft_recall_with_lot(
        recall_overrides={"hazard_severity": "SERIOUS", "injury_reported": True}
    )
    data = validate_success(api.classify_recall(recall["id"], COORD), 200)
    assert data["classification"] == "CLASS_I", data["classification"]


def test_serious_without_injury_classifies_class_ii(api):
    """PRD §3.3: "when the hazard is `SERIOUS` but no injury has been reported,
    it is `CLASS_II`". PRD §3.3: "The single differentiator between `CLASS_I`
    and `CLASS_II` at `SERIOUS` severity is the `injury_reported` flag — identical
    severity, different class, driven solely by whether an injury was reported."

    Design: Difficulty/dual_variant_calc/classification_injury_flag_drives_class_i_vs_ii
    """
    _p, _l, recall = setup_draft_recall_with_lot(
        recall_overrides={"hazard_severity": "SERIOUS", "injury_reported": False}
    )
    data = validate_success(api.classify_recall(recall["id"], COORD), 200)
    assert data["classification"] == "CLASS_II", data["classification"]


# ===========================================================================
# dual_variant_calc — refund basis SALE_PRICE vs LIST_PRICE diverges
# ===========================================================================
def _setup_two_refund_units(sale_price_cents, list_price_cents):
    """CLASS_II recall (SERIOUS, no injury) in MONITORING with two affected
    units sold at sale_price_cents on a product whose list price is
    list_price_cents. Returns (recall, unit_sale, unit_list)."""
    product = create_product(regulator="FDA", unit_list_price_cents=list_price_cents)
    lot = create_lot(product["id"])
    cust_s = create_customer(contact_address="s@x.com")
    cust_l = create_customer(contact_address="l@x.com")
    unit_s = create_unit(lot["id"], cust_s["id"], serial_number=10, sale_price_cents=sale_price_cents)
    unit_l = create_unit(lot["id"], cust_l["id"], serial_number=11, sale_price_cents=sale_price_cents)
    recall = create_recall(product["id"], hazard_severity="SERIOUS", injury_reported=False)
    add_affected_lot(recall["id"], lot["id"])
    classify_recall(recall["id"], make_headers("user-cls-1", "RecallCoordinator"))
    # draft + submit INITIAL report, announce, send notifications, monitor
    from test_helpers import (
        draft_and_submit_initial_report, send_all_notifications,
    )
    draft_and_submit_initial_report(recall["id"])
    validate_success(
        api_client.announce_recall(recall["id"], make_headers("user-ann-1", "QualityOfficer")), 200
    )
    send_all_notifications(recall["id"])
    validate_success(api_client.begin_monitoring(recall["id"], COORD), 200)
    return recall, unit_s, unit_l


def test_refund_basis_sale_price_uses_paid_amount(api):
    """PRD §3.10: "The base in cents is the unit's `sale_price_cents` when the
    disposition's `refund_basis` is `SALE_PRICE` — what the customer actually
    paid — and the recalled product's `unit_list_price_cents` when the basis is
    `LIST_PRICE`." PRD §3.10: "for any other classification, the
    `refund_amount_cents` is the base with no premium."

    Design: Difficulty/dual_variant_calc/refund_basis_sale_vs_list_diverges
    """
    recall, unit_s, _unit_l = _setup_two_refund_units(sale_price_cents=12000, list_price_cents=10000)
    disp = open_returned_owed_refund(recall["id"], unit_s["id"], refund_basis="SALE_PRICE")
    settled = settle_refund(disp["id"])
    assert settled["refund_amount_cents"] == 12000, settled["refund_amount_cents"]


def test_refund_basis_list_price_uses_list_amount(api):
    """PRD §3.10: "the recalled product's `unit_list_price_cents` when the basis
    is `LIST_PRICE`. The two bases diverge whenever the unit sold at a discount
    or premium relative to list."

    Design: Difficulty/dual_variant_calc/refund_basis_sale_vs_list_diverges
    """
    recall, _unit_s, unit_l = _setup_two_refund_units(sale_price_cents=12000, list_price_cents=10000)
    disp = open_returned_owed_refund(recall["id"], unit_l["id"], refund_basis="LIST_PRICE")
    settled = settle_refund(disp["id"])
    assert settled["refund_amount_cents"] == 10000, settled["refund_amount_cents"]


# ===========================================================================
# combinatorial_formula — notification window 3-input branch
# ===========================================================================
def test_notification_window_cpsc_injury_fasttracks_to_24(api):
    """PRD §3.3: "The CPSC fast-tracks injury cases regardless of tier: when an
    injury has been reported and the regulator is `CPSC`, the window is 24
    hours." PRD §3.3: "when the hazard is `MINOR`, it is `CLASS_III`".

    Design: Difficulty/combinatorial_formula/notification_window_three_input_branch
    """
    _p, _l, recall = setup_draft_recall_with_lot(
        product_overrides={"regulator": "CPSC"},
        recall_overrides={"hazard_severity": "MINOR", "injury_reported": True},
    )
    data = validate_success(api.classify_recall(recall["id"], COORD), 200)
    assert data["classification"] == "CLASS_III", data["classification"]
    assert data["notification_deadline_hours"] == 24, data["notification_deadline_hours"]


def test_notification_window_fda_class_ii_is_72(api):
    """PRD §3.3: "A `CLASS_II` recall has a 72-hour window when the regulator is
    `FDA` and a 120-hour window when the regulator is `CPSC`."

    Design: Difficulty/combinatorial_formula/notification_window_three_input_branch
    """
    _p, _l, recall = setup_draft_recall_with_lot(
        product_overrides={"regulator": "FDA"},
        recall_overrides={"hazard_severity": "SERIOUS", "injury_reported": False},
    )
    data = validate_success(api.classify_recall(recall["id"], COORD), 200)
    assert data["notification_deadline_hours"] == 72, data["notification_deadline_hours"]


# ===========================================================================
# combinatorial_formula — effectiveness recompute pinned eval order (1/3 = 33.33)
# ===========================================================================
def test_effectiveness_one_of_three_is_3333(api):
    """PRD §3.11: "`recovered_unit_count` is the number of dispositions of this
    recall whose `logistics_status` is either `RETURNED` or `REPLACED` and whose
    dispositioned unit is affected". PRD §3.11: "otherwise `effectiveness_pct` is
    `recovered_unit_count` divided by `affected_unit_count`, multiplied by 100,
    rounded half-up to two decimal places."

    Design: Difficulty/combinatorial_formula/effectiveness_recompute_pinned_eval_order
    """
    _p, _l, recall, _units = setup_recall_with_recovery_local(num_units=3, num_returned=1)
    data = validate_success(api.get_recall_effectiveness(recall["id"], COORD), 200)
    assert data["affected_unit_count"] == 3, data["affected_unit_count"]
    assert data["recovered_unit_count"] == 1, data["recovered_unit_count"]
    assert data["effectiveness_pct"] == pytest.approx(33.33, abs=0.001), data["effectiveness_pct"]


def test_effectiveness_affected_count_counts_all_affected_units(api):
    """PRD §3.11: "Step one counts the affected universe: `affected_unit_count`
    is the number of units whose `affected` flag is true."

    Design: Difficulty/combinatorial_formula/effectiveness_recompute_pinned_eval_order
    """
    _p, _l, recall, _units = setup_recall_with_recovery_local(num_units=3, num_returned=1)
    data = validate_success(api.get_recall(recall["id"], COORD), 200)
    assert data["affected_unit_count"] == 3, data["affected_unit_count"]
    assert data["recovered_unit_count"] == 1, data["recovered_unit_count"]


def setup_recall_with_recovery_local(num_units, num_returned):
    from test_helpers import setup_recall_with_recovery
    return setup_recall_with_recovery(
        num_units=num_units,
        num_returned=num_returned,
        recall_overrides={"hazard_severity": "SERIOUS", "injury_reported": False},
        sale_price_cents=8000,
    )


# ===========================================================================
# Corner: calculations
# ===========================================================================
def test_class_i_goodwill_premium_rounds_half_up(api):
    """PRD §3.10: "when the owning recall's `classification` is `CLASS_I`, the
    `refund_amount_cents` is the base multiplied by 1.10 (a 10 percent goodwill
    premium that regulators encourage for serious hazards), rounded to the
    nearest whole cent using round-half-up".

    Design: Corner/calculations/refund_class_i_goodwill_premium_applied
    """
    product = create_product(regulator="CPSC", unit_list_price_cents=9000)
    lot = create_lot(product["id"])
    cust = create_customer(contact_address="gw@x.com")
    unit = create_unit(lot["id"], cust["id"], serial_number=3, sale_price_cents=9999)
    recall = create_recall(product["id"], hazard_severity="SERIOUS", injury_reported=True)
    add_affected_lot(recall["id"], lot["id"])
    classify_recall(recall["id"], make_headers("user-gw-1", "RecallCoordinator"))
    from test_helpers import draft_and_submit_initial_report, send_all_notifications
    draft_and_submit_initial_report(recall["id"])
    validate_success(
        api.announce_recall(recall["id"], make_headers("user-gw-2", "QualityOfficer")), 200
    )
    disp = open_returned_owed_refund(recall["id"], unit["id"], refund_basis="SALE_PRICE")
    settled = settle_refund(disp["id"])
    # 9999 * 1.10 = 10998.9 -> round_half_up -> 10999
    assert settled["refund_amount_cents"] == 10999, settled["refund_amount_cents"]


def test_notification_window_cpsc_class_ii_is_120(api):
    """PRD §3.3: "A `CLASS_II` recall has a 72-hour window when the regulator is
    `FDA` and a 120-hour window when the regulator is `CPSC`."

    Design: Corner/calculations/notification_window_class_ii_cpsc_is_120
    """
    _p, _l, recall = setup_draft_recall_with_lot(
        product_overrides={"regulator": "CPSC"},
        recall_overrides={"hazard_severity": "SERIOUS", "injury_reported": False},
    )
    data = validate_success(api.classify_recall(recall["id"], COORD), 200)
    assert data["classification"] == "CLASS_II", data["classification"]
    assert data["notification_deadline_hours"] == 120, data["notification_deadline_hours"]
