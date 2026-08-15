"""Disbursement gating and title transfer: lien waterfall gate, full
disbursement fan-out, FULL warranty encumbrance, liens_status reconciliation."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_documentation_record_payload,
    create_lien_payload,
    create_title_transfer_payload,
    get_success_data,
    listing_headers,
    setup_approved_statement,
    setup_brokerage_desk,
    setup_disbursable,
    create_vessel,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

CLOSING = TEST_USERS["closing_officer_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


class TestDisburseGatedByVesselLiens:
    def test_disburse_rejected_while_vessel_encumbered(self, api):
        """PRD §3.8: "The ClosingOfficer may disburse only when the statement
        stands APPROVED, every CLEARED DEPOSIT entry on the offer has been
        released to DISBURSED, the title transfer stands EXECUTED, every
        contingency stands SATISFIED or WAIVED, and the vessel's `liens_status`
        is CLEAN — an encumbered vessel at this gate is rejected with
        `ERR_LIENS_OUTSTANDING` (HTTP 422), and a waterfall that left a lien
        PARTIALLY_SATISFIED surfaces `ERR_WATERFALL_SHORTFALL`."
        PRD §3.7: "a lien allocated strictly between nothing and its face becomes
        PARTIALLY_SATISFIED, the vessel stays ENCUMBERED"

        Lien face 500000000 exceeds the payoff pool on a 400000000 gross, so the
        waterfall leaves the lien PARTIALLY_SATISFIED and the vessel ENCUMBERED;
        the disburse gate is the only one still closed (deposit released,
        transfer EXECUTED, contingencies waived, statement APPROVED).

        Design: Difficulty/cross_entity_state_dependency/disburse_gated_by_vessel_liens_status
        """
        deal = setup_disbursable(
            lien_payloads=[{
                "lienholder_name": "Big Bank",
                "instrument_type": "PREFERRED_MORTGAGE",
                "amount_cents": 500000000,
                "priority_rank": 1,
            }],
            offer_price_cents=400000000,
            list_price_cents=420000000,
            warranty_of_title="SPECIAL",
        )
        liens = get_success_data(api.list_liens(deal["vessel"]["id"], CLOSING))
        lien = [l for l in liens if l["amount_cents"] == 500000000][0]
        assert lien["status"] == "PARTIALLY_SATISFIED"
        assert 0 < lien["payoff_amount_cents"] < lien["amount_cents"]
        vessel = get_success_data(api.get_vessel(deal["vessel"]["id"], CLOSING))
        assert vessel["liens_status"] == "ENCUMBERED"

        res = api.disburse_closing_statement(deal["statement"]["id"], CLOSING)
        actual = validate_error_is_one_of(
            res,
            [ApiErrorId.ERR_LIENS_OUTSTANDING, ApiErrorId.ERR_WATERFALL_SHORTFALL],
        )
        assert res.status_code == 422
        statement = get_success_data(
            api.get_closing_statement(deal["statement"]["id"], CLOSING)
        )
        assert statement["status"] == "APPROVED"

    def test_successful_disbursement_fans_out_across_deal(self, api):
        """PRD §3.8: "A successful disbursement moves the statement to DISBURSED
        and fans out across the whole deal in one motion: the offer moves from
        ACCEPTED to CLOSED, the listing moves from UNDER_CONTRACT to CLOSED, the
        title transfer moves from EXECUTED to RECORDED with its attached
        documentation records flipping to TRANSFERRED, and every tax assessment
        on the statement is marked FILED, remitted to the state."
        PRD §3.7: "A lien paid to its full face becomes SATISFIED, and when the
        last open encumbrance clears the vessel's `liens_status` is recomputed to
        CLEAN"

        Design: Difficulty/cross_entity_state_dependency/disburse_gated_by_vessel_liens_status
        """
        deal = setup_disbursable(
            lien_payloads=[{
                "lienholder_name": "Yard",
                "instrument_type": "UCC1",
                "amount_cents": 1000000,
                "priority_rank": 1,
            }],
            offer_price_cents=400000000,
            list_price_cents=420000000,
            warranty_of_title="FULL",
        )
        liens = get_success_data(api.list_liens(deal["vessel"]["id"], CLOSING))
        assert liens[0]["status"] == "SATISFIED"
        vessel = get_success_data(api.get_vessel(deal["vessel"]["id"], CLOSING))
        assert vessel["liens_status"] == "CLEAN"

        disbursed = validate_success(
            api.disburse_closing_statement(deal["statement"]["id"], CLOSING), 200
        )
        assert disbursed["status"] == "DISBURSED"

        offer = get_success_data(api.get_offer(deal["offer"]["id"], CLOSING))
        assert offer["status"] == "CLOSED"
        listing = get_success_data(api.get_listing(deal["listing"]["id"], CLOSING))
        assert listing["status"] == "CLOSED"
        transfer = get_success_data(api.get_title_transfer(deal["transfer"]["id"], CLOSING))
        assert transfer["status"] == "RECORDED"
        assessments = get_success_data(
            api.list_tax_assessments(deal["statement"]["id"], CLOSING)
        )
        assert assessments, "build must have created tax assessment rows"
        assert all(a["status"] == "FILED" for a in assessments)
        records = get_success_data(
            api.list_documentation_records(deal["vessel"]["id"], CLOSING)
        )
        cod = [r for r in records if r["record_kind"] == "USCG_COD"]
        assert cod and all(r["status"] == "TRANSFERRED" for r in cod)


def test_full_warranty_rejected_on_encumbered_vessel(api):
    """PRD §3.8: "a FULL warranty additionally requires the vessel's
    `liens_status` to be CLEAN, and attempting a full warranty on an encumbered
    vessel is rejected with `ERR_TITLE_ENCUMBERED` (HTTP 422)"

    The lien is recorded after the statement is approved so the vessel stands
    ENCUMBERED at execute time; the COD record is on file and the statement is
    APPROVED, leaving the encumbrance as the only failing gate.

    Design: Corner/validations/full_warranty_requires_clean_liens
    """
    deal = setup_approved_statement(
        offer_price_cents=300000000, list_price_cents=300000000
    )
    validate_success(
        api.create_lien(
            deal["vessel"]["id"],
            create_lien_payload(instrument_type="UCC1", amount_cents=1000000),
            CLOSING,
        ),
        201,
    )
    vessel = get_success_data(api.get_vessel(deal["vessel"]["id"], CLOSING))
    assert vessel["liens_status"] == "ENCUMBERED"
    validate_success(
        api.create_documentation_record(
            deal["vessel"]["id"], create_documentation_record_payload(), CLOSING
        ),
        201,
    )
    transfer = validate_success(
        api.create_title_transfer(
            deal["statement"]["id"],
            create_title_transfer_payload(
                deal["vessel"]["id"], deal["seller"]["id"], deal["buyer"]["id"],
                warranty_of_title="FULL",
            ),
            CLOSING,
        ),
        201,
    )
    res = api.execute_title_transfer(transfer["id"], CLOSING)
    validate_error(res, ApiErrorId.ERR_TITLE_ENCUMBERED)
    after = get_success_data(api.get_title_transfer(transfer["id"], CLOSING))
    assert after["status"] == "DRAFT"


def test_liens_status_reconciles_clean_on_last_lien_release(api):
    """PRD §3.2: "Recording any lien flips the vessel's `liens_status` from CLEAN
    to ENCUMBERED and bumps the vessel's `version`." and "a lienholder who files
    a release without payment lets a ListingAgent or ClosingOfficer mark the lien
    RELEASED by supplying a non-empty `release_ref`, and whenever the last open
    encumbrance clears — by release or by full satisfaction — the vessel's
    `liens_status` is recomputed to CLEAN."

    Design: Corner/cross_cutting_layers/derived_liens_status_reconciles_on_lien_release
    """
    deal = setup_brokerage_desk()
    vessel = create_vessel()
    lien = validate_success(
        api.create_lien(
            vessel["id"],
            create_lien_payload(instrument_type="UCC1", amount_cents=500000),
            listing_headers(deal),
        ),
        201,
    )
    assert lien["status"] == "RECORDED"
    encumbered = get_success_data(api.get_vessel(vessel["id"], listing_headers(deal)))
    assert encumbered["liens_status"] == "ENCUMBERED"

    released = validate_success(
        api.release_lien(lien["id"], {"release_ref": "REL-2026-001"},
                         listing_headers(deal)),
        200,
    )
    assert released["status"] == "RELEASED"
    reconciled = get_success_data(api.get_vessel(vessel["id"], listing_headers(deal)))
    assert reconciled["liens_status"] == "CLEAN"
