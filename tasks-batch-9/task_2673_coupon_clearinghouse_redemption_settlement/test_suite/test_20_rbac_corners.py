"""Who may act, keyed on the role name and then on the acting identity.

The administrator oversees the pipeline without being able to run any step of
it, an entity-backed caller is confined to its own rows even for a pure read,
and one analyst identity stored by a finalize bars that identity from resolving.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_success,
)

from test_helpers import (
    ADMIN,
    ANALYST,
    ANALYST_2,
    CLERK,
    OFFICER,
    FRAUD_ANALYST_ID,
    FRAUD_ANALYST_2_ID,
    UNKNOWN_UUID,
    COUNTERFEIT_DATABAR_PAYLOAD,
    DisputeStatus,
    IntakeStatus,
    LotRejectReason,
    LotStatus,
    RetailerStatus,
    api_errors as err,
    assert_fields,
    assert_money,
    assert_nulls,
    factories as f,
    make_manufacturer_headers,
    make_retailer_headers,
)


def test_01_the_administrator_cannot_stand_in_for_the_roles_it_oversees(
        api, build):
    """Each pipeline step refuses the admin and then runs for its owner.

    "`ClearinghouseAdmin` is deliberately **not** a hierarchical override. It
    cannot verify counts, sort lots, capture images, adjudicate items, finalize
    lots, rescore retailers, resolve disputes, issue statements, schedule or
    release payments, or fund an invoice; those capabilities remain exclusive to
    `IntakeClerk`, `FraudAnalyst`, `SettlementOfficer` and `Manufacturer`
    respectively."

    "Conversely, onboarding manufacturers and retailers, suspending and
    reinstating them, activating offers and reversing invoice funding are exclusive
    to `ClearinghouseAdmin`."

    "The role appears in the target endpoint's authorised-role list — otherwise
    `ERR_FORBIDDEN_ROLE` (403)."

    Design: Corner/rbac/admin_cannot_stand_in_for_the_operator_roles_it_oversees
    """
    world = build.market()
    retailer_id = world["retailer_id"]
    build.purchase_record(retailer_id, world["offer_id"], "POS-1",
                          "2026-07-01", 5)
    submission = build.submission(retailer_id, 1, "2026-07-01",
                                 "2026-07-31")

    admin_counts = api.verify_count(submission["id"], 1, ADMIN)
    validate_error(admin_counts, err.ERR_FORBIDDEN_ROLE, expected_status=403)

    counted = validate_success(api.verify_count(submission["id"], 1, CLERK))
    assert_fields(counted, {"intake_status": IntakeStatus.COUNT_VERIFIED,
                            "verified_count": 1})

    lot = build.lot(submission["id"], world["offer_id"],
                    world["manufacturer_id"], 1)
    build.capture(lot["id"], [f.item_payload(
        world["barcode"], "s3://coupon-images/z1.jpg", "2026-07-05",
        pos_transaction_ref="POS-1")])

    admin_finalizes = api.finalize_lot(lot["id"], ADMIN)
    validate_error(admin_finalizes, err.ERR_FORBIDDEN_ROLE, expected_status=403)

    valued = validate_success(api.finalize_lot(lot["id"], ANALYST))
    assert_fields(valued, {"status": LotStatus.VALIDATED})
    assert_money(valued, "gross_face_value_cents", 50)
    assert_money(valued, "handling_fee_cents", 7)

    retailer = validate_success(api.get_retailer(retailer_id, ADMIN))
    admin_rescores = api.fraud_rescore(retailer_id, retailer["version"], ADMIN)
    validate_error(admin_rescores, err.ERR_FORBIDDEN_ROLE, expected_status=403)

    officer_onboards = api.create_retailer(
        f.retailer_payload(legal_name="Unauthorised Onboarding"), OFFICER)
    validate_error(officer_onboards, err.ERR_FORBIDDEN_ROLE,
                   expected_status=403)

    admin_funds = api.fund_invoice(UNKNOWN_UUID, 10, ADMIN)
    validate_error(admin_funds, err.ERR_FORBIDDEN_ROLE, expected_status=403)
    assert "ERR_INVOICE_NOT_FOUND" not in admin_funds.text, (
        "the role check answers before the unknown invoice id could be looked up"
    )


def test_02_an_entity_backed_caller_is_confined_to_its_own_rows(api, build):
    """A second retailer holds the role and still cannot touch the first's rows.

    "Concretely, a `Retailer` may only act on the submissions, submission lots,
    coupon items, purchase-data records, disputes and digital redemption events
    whose owning retailer is itself, and a `Manufacturer` may only act on the
    offers and manufacturer invoices whose owning manufacturer is itself."

    "An entity-backed caller acts only on its own rows, as described in §2.1 —
    otherwise `ERR_NOT_RESOURCE_OWNER` (403)."

    "Applies to every endpoint whose authorised-role list includes `Retailer` or
    `Manufacturer`; the four opaque staff roles are exempt."

    Design: Corner/rbac/entity_backed_callers_are_confined_to_their_own_rows
    """
    world = build.market()
    owner_id = world["retailer_id"]
    offer_id = world["offer_id"]
    outsider = build.retailer(legal_name="Southgate Markets")
    rival_issuer = build.manufacturer(gs1_company_prefix="041000",
                                      legal_name="Rival Brands")
    outsider_headers = make_retailer_headers(outsider["id"])
    rival_headers = make_manufacturer_headers(rival_issuer["id"])

    build.purchase_record(owner_id, offer_id, "POS-1", "2026-07-01", 5)
    submission = build.verified_submission(owner_id, 2)
    good = build.lot(submission["id"], offer_id, world["manufacturer_id"], 1)
    build.capture(good["id"], [f.item_payload(
        world["barcode"], "s3://coupon-images/good.jpg", "2026-07-05",
        pos_transaction_ref="POS-1")])
    build.finalize(good["id"])

    condemned = build.lot(submission["id"], offer_id,
                          world["manufacturer_id"], 1)
    build.capture(condemned["id"], [f.item_payload(
        COUNTERFEIT_DATABAR_PAYLOAD, "s3://coupon-images/bad.jpg",
        "2026-07-05", pos_transaction_ref="POS-1")])
    rejected = build.finalize(condemned["id"])
    assert_fields(rejected, {
        "status": LotStatus.LOT_REJECTED,
        "reject_reason": LotRejectReason.ALL_ITEMS_REJECTED,
    })

    poaching = api.file_dispute(
        condemned["id"], "IMAGE_QUALITY", "Not my lot, but let me try.",
        outsider_headers)
    validate_error(poaching, err.ERR_NOT_RESOURCE_OWNER, expected_status=403)

    peeking = api.get_submission(submission["id"], outsider_headers)
    validate_error(peeking, err.ERR_NOT_RESOURCE_OWNER, expected_status=403)

    posting_for_another = api.create_purchase_record(
        f.purchase_record_payload(owner_id, offer_id, "POS-9", "2026-07-06", 1),
        outsider_headers)
    validate_error(posting_for_another, err.ERR_NOT_RESOURCE_OWNER,
                   expected_status=403)

    rival_read = api.get_offer(offer_id, rival_headers)
    validate_error(rival_read, err.ERR_NOT_RESOURCE_OWNER, expected_status=403)

    standing = validate_success(api.get_retailer(owner_id, ADMIN))
    assert_fields(standing, {"status": RetailerStatus.ACTIVE})

    filed = validate_success(api.file_dispute(
        condemned["id"], "IMAGE_QUALITY", "The sorter misread our databar.",
        make_retailer_headers(owner_id)), 201)
    assert_fields(filed, {"lot_id": condemned["id"],
                          "status": DisputeStatus.UNDER_REVIEW})

    parked = validate_success(api.get_lot(condemned["id"], ANALYST))
    assert_fields(parked, {"status": LotStatus.DISPUTED})

    staff_read = validate_success(api.get_submission(submission["id"], OFFICER))
    assert_fields(staff_read, {"id": submission["id"],
                               "retailer_id": owner_id})


def test_03_the_analyst_who_rejected_the_lot_cannot_resolve_its_dispute(
        api, build):
    """The wall keys on the stored analyst identity, and a second one passes.

    "The acting `X-User-ID` must not equal the disputed lot's
    `adjudicated_by_user_id` when resolving a dispute over that lot, and must not
    equal the statement's `issued_by_user_id` when releasing that statement's
    payment — otherwise `ERR_SOD_VIOLATION` (403)."

    "The segregation-of-duties wall applies here and outranks every other
    readiness check on this operation: the acting `X-User-ID` must differ from the
    disputed lot's `adjudicated_by_user_id`, so two distinct analyst identities are
    required to take a lot from rejection to resolution, and a self-review is
    refused with `ERR_SOD_VIOLATION`."

    "Whichever way it goes, resolution writes `resolution_note` and sets
    `resolved_by_user_id` to the acting `X-User-ID`."

    Design: Corner/rbac/lot_adjudicator_cannot_resolve_the_dispute_over_that_lot
    """
    world = build.market()
    retailer_id = world["retailer_id"]
    build.purchase_record(retailer_id, world["offer_id"], "POS-1",
                          "2026-07-01", 5)
    submission = build.verified_submission(retailer_id, 2)

    good = build.lot(submission["id"], world["offer_id"],
                     world["manufacturer_id"], 1)
    build.capture(good["id"], [f.item_payload(
        world["barcode"], "s3://coupon-images/good.jpg", "2026-07-05",
        pos_transaction_ref="POS-1")])
    build.finalize(good["id"])

    condemned = build.lot(submission["id"], world["offer_id"],
                          world["manufacturer_id"], 1)
    build.capture(condemned["id"], [f.item_payload(
        COUNTERFEIT_DATABAR_PAYLOAD, "s3://coupon-images/bad.jpg",
        "2026-07-05", pos_transaction_ref="POS-1")])
    rejected = build.finalize(condemned["id"])
    assert_fields(rejected, {
        "status": LotStatus.LOT_REJECTED,
        "reject_reason": LotRejectReason.ALL_ITEMS_REJECTED,
        "adjudicated_by_user_id": FRAUD_ANALYST_ID,
    })

    dispute = build.file_dispute(condemned["id"], retailer_id)
    assert_fields(dispute, {"status": DisputeStatus.UNDER_REVIEW})

    self_review = api.resolve_dispute(
        dispute["id"], "OVERTURNED", "My own call was wrong.", ANALYST)
    validate_error(self_review, err.ERR_SOD_VIOLATION, expected_status=403)

    untouched = validate_success(api.get_dispute(dispute["id"], ANALYST))
    assert_fields(untouched, {
        "status": DisputeStatus.UNDER_REVIEW,
        "info_request_count": 0,
    })
    assert_nulls(untouched, ["resolved_by_user_id", "resolution_note"])

    resolved = validate_success(api.resolve_dispute(
        dispute["id"], "OVERTURNED", "Re-scan confirms a valid redemption.",
        ANALYST_2))
    assert_fields(resolved, {
        "status": DisputeStatus.OVERTURNED,
        "resolved_by_user_id": FRAUD_ANALYST_2_ID,
        "resolution_note": "Re-scan confirms a valid redemption.",
    })

    reinstated = validate_success(api.get_lot(condemned["id"], ANALYST_2))
    assert_fields(reinstated, {"status": LotStatus.REINSTATED})
    assert_nulls(reinstated, ["reject_reason"])
    assert_money(reinstated, "gross_face_value_cents", 50)
    assert_money(reinstated, "handling_fee_cents", 7)
