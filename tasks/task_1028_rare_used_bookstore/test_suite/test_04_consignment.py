"""Consignment agreement negotiation cycle, activation, OCC, and payout accrual."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_consignment_agreement_payload, TEST_USERS,
)
from test_helpers.fixtures import (
    new_patron, make_appraised_book, make_graded_book,
    setup_confirmed_consigned_sale, api_client,
)

MANAGER = TEST_USERS["manager_headers"]


def _proposed_agreement(commission_pct=0.30):
    """Patron + appraised consigned book + a PROPOSED agreement. Returns (patron, book, agreement)."""
    patron = new_patron(display_name="Ben Dealer")
    ctx = make_appraised_book(condition_grade="GOOD", comp_median_cents=8000,
                              acquisition_channel="CONSIGNMENT", consignor_id=patron["id"],
                              title="Exiles")
    agreement = get_success_data(api_client.create_consignment_agreement(
        create_consignment_agreement_payload(patron["id"], ctx["book"]["id"],
                                              commission_pct=commission_pct), MANAGER))
    return patron, ctx["book"], agreement


def test_amend_cycle_keeps_amended_and_counts(api):
    """PRD §3.5: "An amendment updates any of `commission_pct`, `fee_model`, or
    `flat_fee_cents` from the payload, increments `amendment_no` by one, and increments
    the agreement's `version` by one."

    Design: Difficulty/non_linear_state_machine/consignment_agreement_amend_cycle
    """
    _, _, agreement = _proposed_agreement()
    v0 = agreement["version"]
    r1 = validate_success(api.amend_consignment_agreement(
        agreement["id"], {"commission_pct": 0.25, "expected_consignment_agreement_version": v0}, MANAGER), 200)
    r2 = validate_success(api.amend_consignment_agreement(
        agreement["id"], {"commission_pct": 0.20, "expected_consignment_agreement_version": r1["version"]}, MANAGER), 200)
    assert r2["status"] == "AMENDED"
    assert r2["amendment_no"] == 2


def test_amend_cycle_applies_latest_commission(api):
    """PRD §3.5: "Amending it keeps it in, or returns it to, `AMENDED` status and is
    permitted only while it is `PROPOSED` or `AMENDED` (otherwise
    `ERR_AGREEMENT_NOT_AMENDABLE`); it also requires an
    `expected_consignment_agreement_version` matching the current `version`."

    Design: Difficulty/non_linear_state_machine/consignment_agreement_amend_cycle
    """
    _, _, agreement = _proposed_agreement()
    v0 = agreement["version"]
    r1 = validate_success(api.amend_consignment_agreement(
        agreement["id"], {"commission_pct": 0.25, "expected_consignment_agreement_version": v0}, MANAGER), 200)
    r2 = validate_success(api.amend_consignment_agreement(
        agreement["id"], {"commission_pct": 0.20, "expected_consignment_agreement_version": r1["version"]}, MANAGER), 200)
    assert r2["commission_pct"] == 0.20


def test_amend_stale_agreement_version_rejected(api):
    """PRD §2.6: "Amending a consignment agreement requires
    `expected_consignment_agreement_version` to equal that `ConsignmentAgreement`'s
    current `version`. If another writer has already amended the agreement and
    advanced its `version`, the current amendment rests on stale terms and is refused
    with `ERR_STALE_VERSION`."

    Design: Corner/cross_cutting_complexity_layers/amend_stale_agreement_version_returns_412
    """
    _, _, agreement = _proposed_agreement()
    v0 = agreement["version"]
    validate_success(api.amend_consignment_agreement(
        agreement["id"], {"commission_pct": 0.25, "expected_consignment_agreement_version": v0}, MANAGER), 200)
    res = api.amend_consignment_agreement(
        agreement["id"], {"commission_pct": 0.20, "expected_consignment_agreement_version": v0}, MANAGER)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)


def test_activate_agreement_requires_appraised_item(api):
    """PRD §3.5: "Activating an agreement moves it to `ACTIVE` and requires the
    referenced book to be in `APPRAISED` or `LISTED` status (otherwise
    `ERR_ITEM_NOT_APPRAISED`); activation appends a `provenance` entry of event type
    `CONSIGNED` to the book."

    Design: Corner/errors/activate_agreement_item_not_appraised_returns_409
    """
    patron = new_patron(display_name="Simon")
    ctx = make_graded_book(condition_grade="GOOD", comp_median_cents=2800,
                           acquisition_channel="CONSIGNMENT", consignor_id=patron["id"],
                           title="Ivy Day")
    agreement = get_success_data(api.create_consignment_agreement(
        create_consignment_agreement_payload(patron["id"], ctx["book"]["id"], commission_pct=0.30), MANAGER))
    res = api.activate_consignment_agreement(agreement["id"], MANAGER)
    validate_error(res, "ERR_ITEM_NOT_APPRAISED", expected_status=409)


def test_gross_commission_sale_settles_agreement(api):
    """PRD §3.5: "An `ACTIVE` agreement settles to `SETTLED` automatically when its
    consigned book sells on a confirmed order, and a refund of that order returns it
    from `SETTLED` to `ACTIVE`."

    Design: Difficulty/dual_variant_calc/consignment_payout_gross_vs_net_commission
    """
    ctx = setup_confirmed_consigned_sale(commission_pct=0.30, fee_model="GROSS_COMMISSION",
                                         sale_price_cents=30000, comp_median_cents=20000)
    agreement = validate_success(
        api.get_consignment_agreement(ctx["agreement"]["id"], MANAGER), 200)
    assert agreement["status"] == "SETTLED"


def test_gross_commission_sale_accrues_payout(api):
    """PRD §3.5: "Under `GROSS_COMMISSION`, the payout is the gross sale price
    multiplied by one minus the `commission_pct`, rounded half up to whole cents, and
    the `flat_fee_cents` is ignored."

    Design: Difficulty/dual_variant_calc/consignment_payout_gross_vs_net_commission
    """
    ctx = setup_confirmed_consigned_sale(commission_pct=0.30, fee_model="GROSS_COMMISSION",
                                         sale_price_cents=30000, comp_median_cents=20000)
    patron = validate_success(api.get_patron(ctx["patron"]["id"], MANAGER), 200)
    assert patron["consignor_payable_cents"] == 21000
