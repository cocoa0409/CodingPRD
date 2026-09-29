"""
Two-variant calculations of the County Land Bank Authority API.

The parcel's blight score is written in two variants that differ in one term,
and the development agreement's tax relief is computed in two modes that read
different bases, so the same inputs produce two different figures.
"""

from test_helpers import factories, fixtures, validate_success
from test_helpers.assertions import assert_score
from test_helpers.constants import DEFAULT_CLOCK
from test_helpers.test_users import CLERK_1, DISP_1, INTAKE_1, INTAKE_2, INV_1

# ─── the grade D parcel both blight variants are read from ───────────────────
ASH_STREET_PARCEL = {
    "address": "12 Ash St",
    "situs_ward": 3,
    "lot_area_sqft": 6000,
    "assessed_value_cents": 400000,
    "structure_present": True,
    "structure_condition_grade": "D",
    "vacancy_months": 24,
}

# ─── the two byte-identical parcels the two discharge modes are read from ────
BIRCH_AVENUE_PARCEL = {
    "situs_ward": 2,
    "lot_area_sqft": 9000,
    "assessed_value_cents": 4000000,
    "structure_present": True,
    "structure_condition_grade": "C",
    "vacancy_months": 10,
}

# Terms shared by both agreements, so only discharge_mode differs between them.
AGREEMENT_TERMS = {
    "performance_deadline": "2027-08-01T00:00:00Z",
    "milestone_count": 3,
    "reverter_clause_active": True,
    "abatement_years": 5,
    "projected_improved_value_cents": 15000000,
}


def _board_approved_ash_street_packet(api):
    """
    A grade D parcel with 4 nuisance complaints and 2 open violations on file,
    and a board-approved donation packet ready to close against an unrestricted
    grant.
    """
    funding_source = fixtures.create_funding_source(
        api,
        name="Blight Elimination Grant",
        source_type="GRANT",
        authorized_cents=1000000,
        restriction="ANY",
    )
    prop = fixtures.create_property(api, **ASH_STREET_PARCEL)
    fixtures.post_code_violations(
        api, prop["id"], open_code_violation_count=2, nuisance_complaint_count=4
    )
    packet = fixtures.open_packet(
        api,
        prop["id"],
        funding_source["id"],
        title_search_fee_cents=50000,
        donor_name="Ash Street Trust",
    )
    fixtures.board_approve_packet(api, packet["id"])
    return {"funding_source": funding_source, "property": prop, "packet": packet}


def _board_approved_rfp_award(api, funding_source, *, address, legal_name, email):
    """
    A 4,000,000-cent parcel carrying a 2,000,000-cent delinquency posted before
    acquisition, taken in by donation, quiet-titled CLEAR, listed, and awarded to
    a DEVELOPER buyer offering the 3,600,000-cent quote.
    """
    prop = fixtures.create_property(api, address=address, **BIRCH_AVENUE_PARCEL)
    fixtures.post_tax_roll(
        api, prop["id"], delinquent_tax_balance_cents=2000000, tax_year=2025
    )
    fixtures.acquire_property(
        api,
        prop["id"],
        funding_source["id"],
        title_search_fee_cents=20000,
        donor_name="Birch Holdings",
    )
    fixtures.clear_title(api, prop["id"])
    fixtures.list_parcel(api, prop["id"])
    buyer = fixtures.create_developer_applicant(
        api, legal_name=legal_name, contact_email=email
    )
    application = fixtures.draft_application(
        api,
        prop["id"],
        buyer["id"],
        program="DEVELOPER_RFP",
        proposed_use="Six-unit infill townhomes",
        offer_price_cents=3600000,
    )
    fixtures.submit_application(api, application["id"], buyer["id"])
    fixtures.screen_application(api, application["id"])
    fixtures.recommend_application(api, application["id"])
    fixtures.board_decide(api, application["id"], "APPROVE")
    return {"property": prop, "applicant": buyer, "application": application}


# ─────────────────────────────────────────────────────────────────────────────
# The provisional intake variant and the live variant of the blight score
# ─────────────────────────────────────────────────────────────────────────────
def test_intake_snapshot_is_stamped_with_the_holding_term_at_zero(api):
    """The intake snapshot stamped at the close of an acquisition carries no holding points, so a grade D parcel with 24 vacant months, 4 complaints and 2 violations reads exactly 48.0.

    The **provisional intake** variant fixes the holding term at zero and is stamped once into `intake_blight_score` when an acquisition closes; because its inputs are frozen at that instant, it stays a historical snapshot forever.

    Design: Difficulty/dual_variant_calc/blight_intake_snapshot_vs_sweep_final_holding_divergence
    """
    bundle = _board_approved_ash_street_packet(api)
    fixtures.close_packet(api, bundle["packet"]["id"])

    parcel = validate_success(api.get_property(bundle["property"]["id"], INTAKE_1))

    # 30 points for grade D, 6.0 for 24 vacant months, 6.0 for 4 complaints and
    # 6.0 for 2 open violations, with the holding term fixed at zero.
    assert_score(parcel["intake_blight_score"], 48.0)


def test_live_score_drifts_above_the_frozen_snapshot_as_the_parcel_ages(api):
    """After 184 days of holding, the live score adds 3.0 holding points for the six whole 30-day months elapsed and reads 51.0 against the frozen 48.0 snapshot in the same parcel.

    Because the live variant accrues holding points the provisional one never will, a parcel's `current_blight_score` drifts upward away from its `intake_blight_score` as it ages in inventory.

    Design: Difficulty/dual_variant_calc/blight_intake_snapshot_vs_sweep_final_holding_divergence
    """
    bundle = _board_approved_ash_street_packet(api)
    fixtures.close_packet(api, bundle["packet"]["id"])
    property_id = bundle["property"]["id"]
    assert (
        fixtures.read_property(api, property_id)["intake_blight_score"] == 48.0
    ), "the snapshot must be stamped at 48.0 before the clock moves"

    # 2026-08-01 to 2027-02-01 is 184 days, six whole 30-day months of holding.
    fixtures.set_clock(api, "2027-02-01T00:00:00Z")

    parcel = validate_success(
        api.post_code_violation_report(
            property_id,
            {"open_code_violation_count": 2, "nuisance_complaint_count": 4},
            INTAKE_1,
        )
    )

    # min(12, 0.5 * 6) == 3.0 holding points on top of the same 48.0 of terms.
    assert_score(parcel["current_blight_score"], 51.0)
    assert_score(parcel["intake_blight_score"], 48.0)
    assert (
        parcel["current_blight_score"] - parcel["intake_blight_score"] == 3.0
    ), "the two variants differ by exactly the holding term"


def test_closing_the_acquisition_stamps_custody_and_the_intake_picture(api):
    """Closing the donation packet moves the parcel from PROSPECT to ACQUIRED and stamps its acquisition channel, its acquisition instant, its 50,000-cent cost and its frozen pre-acquisition delinquency.

    The parcel must still be `PROSPECT`, and the close drives the custody transition `PROSPECT → ACQUIRED` together with the whole intake stamping: the parcel copies the packet's channel into `acquisition_channel`, records `acquired_at` at the current instant, sets `acquisition_cost_cents` to the packet's offer price plus title search fee, and freezes the parcel's current `delinquent_tax_balance_cents` into `pre_acquisition_delinquency_cents` — the only delinquency the board will ever be able to discharge.

    Design: Difficulty/dual_variant_calc/blight_intake_snapshot_vs_sweep_final_holding_divergence
    """
    bundle = _board_approved_ash_street_packet(api)

    # A different intake officer than the one who opened the packet signs the
    # deed into inventory.
    packet = validate_success(
        api.close_packet(
            bundle["packet"]["id"], {"deed_reference": "BK-4410-PG-77"}, INTAKE_2
        )
    )
    assert packet["status"] == "CLOSED"

    parcel = validate_success(api.get_property(bundle["property"]["id"], INTAKE_1))
    assert parcel["custody_status"] == "ACQUIRED"
    assert parcel["acquisition_channel"] == "DONATION"
    # The clock never moved, so the parcel was taken in at the starting instant.
    assert parcel["acquired_at"][:19] == DEFAULT_CLOCK[:19]
    # A donation pays nothing; only the 50,000-cent title search fee is a cost.
    assert parcel["acquisition_cost_cents"] == 50000
    # No tax roll was ever posted on this parcel, so nothing is dischargeable.
    assert parcel["pre_acquisition_delinquency_cents"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# The statutory and negotiated modes of the tax discharge and abatement
# ─────────────────────────────────────────────────────────────────────────────
def test_statutory_mode_discharges_the_whole_frozen_delinquency(api):
    """A STATUTORY agreement forgives the entire 2,000,000-cent frozen pre-acquisition delinquency and abates 213,000 cents a year against the 15,000,000-cent projected improved value.

    Under `STATUTORY`, `discharged_tax_cents` is the whole of that frozen pre-acquisition delinquency and the abatement is computed against the buyer's `projected_improved_value_cents`.

    Design: Difficulty/dual_variant_calc/tax_discharge_statutory_vs_negotiated_divergence
    """
    funding_source = fixtures.create_acquisition_funding_source(api)
    award = _board_approved_rfp_award(
        api,
        funding_source,
        address="10 Birch Ave",
        legal_name="Northline Development LLC",
        email="a@northline.dev",
    )
    parcel = fixtures.read_property(api, award["property"]["id"])
    assert parcel["pre_acquisition_delinquency_cents"] == 2000000

    agreement = validate_success(
        api.create_development_agreement(
            factories.development_agreement_payload(
                award["application"]["id"],
                discharge_mode="STATUTORY",
                **AGREEMENT_TERMS,
            ),
            CLERK_1,
        ),
        201,
    )

    assert agreement["sale_price_cents"] == 3600000
    assert agreement["discharged_tax_cents"] == 2000000
    # 0.0142 * 15000000 == 213000, below the 250,000-cent annual cap.
    assert agreement["abatement_annual_cents"] == 213000
    assert agreement["abatement_total_cents"] == 1065000


def test_negotiated_mode_caps_the_discharge_at_forty_percent_of_the_sale(api):
    """A NEGOTIATED agreement over the same parcel and offer forgives only 1,440,000 cents — 40 percent of the 3,600,000-cent sale price — and abates 56,800 cents a year against the 4,000,000-cent assessed value.

    Under `NEGOTIATED`, `discharged_tax_cents` is the lesser of that frozen delinquency and 40 percent of `sale_price_cents` rounded half up, and the abatement is computed against the parcel's pre-improvement `assessed_value_cents` instead.

    Design: Difficulty/dual_variant_calc/tax_discharge_statutory_vs_negotiated_divergence
    """
    funding_source = fixtures.create_acquisition_funding_source(api)
    award = _board_approved_rfp_award(
        api,
        funding_source,
        address="11 Birch Ave",
        legal_name="Southgate Builders Inc",
        email="b@southgate.dev",
    )
    parcel = fixtures.read_property(api, award["property"]["id"])
    assert parcel["pre_acquisition_delinquency_cents"] == 2000000

    agreement = validate_success(
        api.create_development_agreement(
            factories.development_agreement_payload(
                award["application"]["id"],
                discharge_mode="NEGOTIATED",
                **AGREEMENT_TERMS,
            ),
            CLERK_1,
        ),
        201,
    )

    assert agreement["sale_price_cents"] == 3600000
    # min(2000000, round_half_up(0.40 * 3600000)) == 1440000.
    assert agreement["discharged_tax_cents"] == 1440000
    # 0.0142 * 4000000 == 56800, the assessed value being the negotiated base.
    assert agreement["abatement_annual_cents"] == 56800
    assert agreement["abatement_total_cents"] == 284000


def test_both_discharge_modes_convey_their_parcel_and_award_the_application(api):
    """Whichever discharge mode the board chose, executing the agreement moves the parcel from LISTED to CONVEYED under its buyer and moves the application to AWARDED.

    The conveyance itself moves the parcel `LISTED → CONVEYED`, sets its `owner_of_record_applicant_id` to the buyer, and moves the application `BOARD_APPROVED → AWARDED`, the last of its terminal statuses.

    Design: Difficulty/dual_variant_calc/tax_discharge_statutory_vs_negotiated_divergence
    """
    funding_source = fixtures.create_acquisition_funding_source(api)
    statutory = _board_approved_rfp_award(
        api,
        funding_source,
        address="10 Birch Ave",
        legal_name="Northline Development LLC",
        email="a@northline.dev",
    )
    negotiated = _board_approved_rfp_award(
        api,
        funding_source,
        address="11 Birch Ave",
        legal_name="Southgate Builders Inc",
        email="b@southgate.dev",
    )

    validate_success(
        api.create_development_agreement(
            factories.development_agreement_payload(
                statutory["application"]["id"],
                discharge_mode="STATUTORY",
                **AGREEMENT_TERMS,
            ),
            CLERK_1,
        ),
        201,
    )
    validate_success(
        api.create_development_agreement(
            factories.development_agreement_payload(
                negotiated["application"]["id"],
                discharge_mode="NEGOTIATED",
                **AGREEMENT_TERMS,
            ),
            CLERK_1,
        ),
        201,
    )

    for award in (statutory, negotiated):
        parcel = validate_success(
            api.get_property(award["property"]["id"], INV_1)
        )
        assert parcel["custody_status"] == "CONVEYED"
        assert parcel["owner_of_record_applicant_id"] == award["applicant"]["id"]

        application = validate_success(
            api.get_disposition_application(award["application"]["id"], DISP_1)
        )
        assert application["status"] == "AWARDED"
