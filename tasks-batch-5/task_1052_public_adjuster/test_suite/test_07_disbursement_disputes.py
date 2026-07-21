"""Disbursement release guards (segregation of duties, open dispute) and reversal."""
from test_helpers import (
    TEST_USERS, ApiErrorId,
    validate_success, validate_error, get_success_data,
    create_dispute_payload,
    make_public_adjuster_headers,
)
from test_helpers.fixtures import setup_paid_claim_with_disbursement

FIRM = TEST_USERS["firm_principal_headers"]
CARRIER = TEST_USERS["carrier_headers"]


# --------------------------- open-dispute blocks release (difficulty cross-entity)
def test_disbursement_release_blocked_by_open_dispute(api):
    """PRD §3.7: "Second, no open dispute may exist: if any dispute on the claim is `OPEN`
    or `UNDER_REVIEW`, the release is rejected with `ERR_OPEN_DISPUTE_BLOCKS_RELEASE`."

    Design: Difficulty/cross_entity_state_dependency/disbursement_release_blocked_by_open_dispute
    """
    ctx = setup_paid_claim_with_disbursement(api, offer_cents=8_000_000)
    validate_success(api.create_dispute(create_dispute_payload(ctx["clm"], dispute_type="FEE",
                                                               raised_by="CLIENT"), FIRM),
                     expected_status=201)
    resp = api.release_disbursement(ctx["dis"], FIRM)  # FirmPrincipal, so SoD passes
    validate_error(resp, ApiErrorId.ERR_OPEN_DISPUTE_BLOCKS_RELEASE.value, expected_status=409)


def test_disbursement_release_blocked_by_under_review_dispute(api):
    """PRD §3.7: "Second, no open dispute may exist: if any dispute on the claim is `OPEN`
    or `UNDER_REVIEW`, the release is rejected with `ERR_OPEN_DISPUTE_BLOCKS_RELEASE`."

    Design: Difficulty/cross_entity_state_dependency/disbursement_release_blocked_by_open_dispute
    """
    ctx = setup_paid_claim_with_disbursement(api, offer_cents=8_000_000)
    dispute = validate_success(api.create_dispute(
        create_dispute_payload(ctx["clm"], dispute_type="SERVICE", raised_by="CLIENT"), FIRM),
        expected_status=201)
    validate_success(api.review_dispute(dispute["id"], FIRM))  # OPEN -> UNDER_REVIEW
    resp = api.release_disbursement(ctx["dis"], FIRM)
    validate_error(resp, ApiErrorId.ERR_OPEN_DISPUTE_BLOCKS_RELEASE.value, expected_status=409)


# ---------------------------------------- segregation of duties (corner rbac)
def test_release_by_settlement_accepter_rejected(api):
    """PRD §3.7: "First, segregation of duties: the releasing user's `X-User-ID` must not
    equal the claim's `accepted_by_user_id`, or the release is rejected with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/segregation_of_duties_release_by_settlement_accepter_rejected
    """
    ctx = setup_paid_claim_with_disbursement(api, offer_cents=8_000_000)
    # The adjuster accepted the settlement (accepted_by_user_id == adj); same user releases.
    resp = api.release_disbursement(ctx["dis"], make_public_adjuster_headers(ctx["adj"]))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


def test_release_by_firm_principal_succeeds(api):
    """PRD §3.7: "A successful release drives the disbursement to the terminal `RELEASED`,
    stamps `released_at`, and adds this disbursement's `advance_recoup_cents` to the
    contract's `advance_recouped_cents`."

    Design: Corner/rbac/disbursement_release_by_firm_principal_succeeds
    """
    ctx = setup_paid_claim_with_disbursement(api, offer_cents=8_000_000)
    data = validate_success(api.release_disbursement(ctx["dis"], FIRM))
    assert data["status"] == "RELEASED"


# ---------------------------------------- reverse after release blocked (corner)
def test_payment_reverse_after_release_blocked(api):
    """PRD §3.7: "A cleared payment may be reversed by a `Carrier` or a `FirmPrincipal` as a
    compensating action, but only while the disbursement that split it has not yet been
    released: a reverse attempted after that disbursement is `RELEASED` is rejected with
    `ERR_DISBURSEMENT_RELEASED`."

    Design: Corner/state_machines/payment_reverse_after_release_blocked_stub
    """
    ctx = setup_paid_claim_with_disbursement(api, offer_cents=8_000_000)
    validate_success(api.release_disbursement(ctx["dis"], FIRM))
    resp = api.reverse_payment(ctx["pay"], CARRIER)
    validate_error(resp, ApiErrorId.ERR_DISBURSEMENT_RELEASED.value)
