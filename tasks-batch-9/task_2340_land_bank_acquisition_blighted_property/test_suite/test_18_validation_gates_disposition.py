"""
The gates that guard a disposition application, its price, its revisions and
the milestones of the agreement that follows it.

Each test drives one application, offer, resubmission, milestone report or
repeat homeowner purchase into exactly one refusal named by the PRD, and then
re-reads the target row to show the refused call wrote nothing.
"""

from test_helpers import (
    ApiErrorId,
    fixtures,
    make_applicant_headers,
    validate_error,
)


# ── a listed parcel a homeowner sale can be priced against ──────────────────
def _listed_homeowner_parcel(api, assessed_value_cents):
    """
    A parcel carried from the registry to LISTED, with a standing grade C
    structure so that the condition discount of the price calculation - which
    only reads grades D and F - never applies.
    """
    funding_source = fixtures.create_acquisition_funding_source(
        api, name="Homeowner Sale Line", authorized_cents=900000
    )
    return fixtures.listed_parcel(
        api,
        funding_source=funding_source,
        property_overrides={
            "address": "3170 Quince Ln",
            "situs_ward": 3,
            "lot_area_sqft": 6000,
            "assessed_value_cents": assessed_value_cents,
            "structure_present": True,
            "structure_condition_grade": "C",
            "vacancy_months": 5,
        },
    )


# ── milestone reports against a fully performed agreement ───────────────────
def test_milestone_report_on_a_complied_agreement_is_refused_for_its_state(api):
    """
    Once every owed milestone is in and the agreement has complied, a further milestone report is refused because of the agreement's state.

    Reporting against an agreement already in `COMPLIED` or `REVERTED` is refused with `ERR_AGREEMENT_INVALID_STATE`.

    Design: Corner/validations/milestone_on_complied_agreement_rejected
    """
    bundle = fixtures.awarded_parcel(api)
    buyer = bundle["applicant"]
    agreement = bundle["agreement"]

    # Both owed milestones are reported inside the performance deadline, so the
    # agreement complies and reaches one of its two terminal states.
    complied = fixtures.report_milestones(
        api, agreement["id"], buyer["id"], 2, evidence_reference="PHOTO-SET-A"
    )
    assert complied["status"] == "COMPLIED"
    assert complied["milestones_completed"] == 2

    # One more milestone would also overrun the owed count, but the state of the
    # agreement is the earlier rule and is the cause the caller must see.
    response = api.report_milestone_completions(
        agreement["id"],
        {"completed_count": 1, "evidence_reference": "PHOTO-SET-B"},
        make_applicant_headers(buyer["id"]),
    )
    validate_error(response, ApiErrorId.AGREEMENT_INVALID_STATE.value)

    after = fixtures.read_agreement(api, agreement["id"])
    assert after["status"] == "COMPLIED"
    assert after["milestones_completed"] == 2
    assert after["version"] == complied["version"]


# ── the price floor and the buyer exclusion on the same programme ────────────
def test_offer_one_cent_below_the_computed_quote_is_refused(api):
    """
    A buyer whose offer falls a single cent short of the computed quote for the parcel and programme cannot submit.

    Last, the money: the buyer's `offer_price_cents` must be at least the computed quote for that parcel and programme, or the submission is refused with `ERR_OFFER_BELOW_QUOTE`.

    Design: Corner/validations/offer_below_quote_and_code_violator_rejected
    """
    bundle = _listed_homeowner_parcel(api, 200000)
    parcel_id = bundle["property"]["id"]

    # 55 percent of an assessed 200,000 cents clears the 100,000-cent floor.
    quote = fixtures.price_quote(api, parcel_id, "HOMEOWNER_SALE")
    assert quote["quoted_price_cents"] == 110000
    assert quote["discount_applied"] is False

    buyer = fixtures.create_applicant(
        api, legal_name="Paula Reyes", contact_email="paula@example.test"
    )
    application = fixtures.draft_application(
        api,
        parcel_id,
        buyer["id"],
        program="HOMEOWNER_SALE",
        proposed_use="Owner-occupied single family",
        offer_price_cents=quote["quoted_price_cents"] - 1,
    )

    response = api.submit_application(
        application["id"], make_applicant_headers(buyer["id"])
    )
    validate_error(response, ApiErrorId.OFFER_BELOW_QUOTE.value)

    after = fixtures.read_application(api, application["id"])
    assert after["status"] == "DRAFT"
    assert after["revision_round"] == 0
    assert after["version"] == application["version"]


def test_buyer_with_two_open_violations_is_barred_from_submitting(api):
    """
    A buyer whose own registry parcel carries two open code-enforcement violations may not submit, even with an offer that meets the quote in full.

    The buyer must owe the county nothing: any delinquent-tax total strictly greater than zero across the parcels it owns of record bars the sale with `ERR_APPLICANT_TAX_DELINQUENT`, and two or more open code-enforcement violations across those same parcels bars it with `ERR_APPLICANT_CODE_VIOLATOR`.

    Design: Corner/validations/offer_below_quote_and_code_violator_rejected
    """
    bundle = _listed_homeowner_parcel(api, 200000)
    parcel_id = bundle["property"]["id"]
    quote = fixtures.price_quote(api, parcel_id, "HOMEOWNER_SALE")
    assert quote["quoted_price_cents"] == 110000

    buyer = fixtures.create_applicant(
        api, legal_name="Quinn Adeyemi", contact_email="quinn@example.test"
    )
    owned = fixtures.create_property(
        api,
        address="3171 Quince Ln",
        situs_ward=3,
        lot_area_sqft=6000,
        assessed_value_cents=180000,
        structure_present=True,
        structure_condition_grade="C",
        vacancy_months=0,
    )
    fixtures.post_code_violations(
        api, owned["id"], open_code_violation_count=2, nuisance_complaint_count=1
    )
    fixtures.set_owner_of_record(api, owned["id"], buyer["id"])

    # Only the violation total is over the bar: the buyer owes no delinquent tax,
    # so the tax exclusion that is tested first cannot fire.
    standing = fixtures.read_applicant(api, buyer["id"])
    assert standing["open_code_violation_total"] == 2
    assert standing["delinquent_tax_total_cents"] == 0
    assert standing["eligibility_status"] == "BARRED"

    application = fixtures.draft_application(
        api,
        parcel_id,
        buyer["id"],
        program="HOMEOWNER_SALE",
        proposed_use="Owner-occupied single family",
        offer_price_cents=quote["quoted_price_cents"],
    )

    response = api.submit_application(
        application["id"], make_applicant_headers(buyer["id"])
    )
    validate_error(response, ApiErrorId.APPLICANT_CODE_VIOLATOR.value)

    after = fixtures.read_application(api, application["id"])
    assert after["status"] == "DRAFT"
    assert after["revision_round"] == 0
    assert after["version"] == application["version"]


# ── the revision cycle may be travelled at most twice ───────────────────────
def test_third_resubmission_is_refused_and_leaves_the_application_parked(api):
    """
    A buyer may travel the information-request cycle twice; the third resubmission is refused and the application stays where the officer parked it.

    A resubmission is accepted only while `revision_round` is strictly below 2, and the third attempt is refused with `ERR_REVISION_LIMIT_EXCEEDED`.

    Design: Corner/validations/resubmit_beyond_revision_limit_rejected
    """
    bundle = _listed_homeowner_parcel(api, 100000)
    parcel_id = bundle["property"]["id"]

    # 55 percent of an assessed 100,000 cents loses to the programme floor.
    quote = fixtures.price_quote(api, parcel_id, "HOMEOWNER_SALE")
    assert quote["quoted_price_cents"] == 100000

    buyer = fixtures.create_applicant(
        api, legal_name="Rosa Delgado", contact_email="rosa@example.test"
    )
    application = fixtures.draft_application(
        api,
        parcel_id,
        buyer["id"],
        program="HOMEOWNER_SALE",
        proposed_use="Owner-occupied single family",
        offer_price_cents=100000,
    )
    submitted = fixtures.submit_application(api, application["id"], buyer["id"])
    assert submitted["revision_round"] == 0

    fixtures.request_info(api, application["id"], "Proof of owner occupancy intent")
    first = fixtures.resubmit_application(
        api,
        application["id"],
        buyer["id"],
        proposed_use="Owner-occupied single family with garage rebuild",
    )
    assert first["revision_round"] == 1

    fixtures.request_info(api, application["id"], "Contractor bid for the rebuild")
    second = fixtures.resubmit_application(
        api, application["id"], buyer["id"], offer_price_cents=105000
    )
    assert second["revision_round"] == 2

    parked = fixtures.request_info(
        api, application["id"], "Mortgage pre-approval letter"
    )
    assert parked["status"] == "INFO_REQUESTED"

    response = api.resubmit_application(
        application["id"],
        {"offer_price_cents": 110000},
        make_applicant_headers(buyer["id"]),
    )
    validate_error(response, ApiErrorId.REVISION_LIMIT_EXCEEDED.value)

    after = fixtures.read_application(api, application["id"])
    assert after["status"] == "INFO_REQUESTED"
    assert after["revision_round"] == 2
    assert after["offer_price_cents"] == 105000
    assert after["version"] == parked["version"]


# ── the homeowner cap counts the buyer's whole conveyed history ──────────────
def test_third_homeowner_purchase_is_refused_once_two_parcels_are_conveyed(api):
    """
    The same buyer may take two parcels under a homeowner sale, and the third submission is refused once two of its parcels stand conveyed.

    A homeowner sale is barred outright when the applicant already holds two or more parcels of record in custody `CONVEYED` (`ERR_HOMEOWNER_LIMIT_EXCEEDED`).

    Design: Corner/validations/homeowner_conveyance_limit_rejected
    """
    funding_source = fixtures.create_funding_source(
        api, name="Homeowner Limit Line", authorized_cents=2000000
    )
    buyer = fixtures.create_applicant(
        api, legal_name="Tomas Iversen", contact_email="tomas@example.test"
    )
    parcel_shape = {
        "situs_ward": 3,
        "lot_area_sqft": 6000,
        "assessed_value_cents": 100000,
        "structure_present": True,
        "structure_condition_grade": "C",
        "vacancy_months": 5,
    }
    sale_terms = {
        "program": "HOMEOWNER_SALE",
        "proposed_use": "Owner-occupied single family",
        "offer_price_cents": 100000,
    }

    for address in ("3210 Umbrella Pine Ln", "3211 Umbrella Pine Ln"):
        awarded = fixtures.awarded_parcel(
            api,
            funding_source=funding_source,
            property_overrides=dict(parcel_shape, address=address),
            applicant=buyer,
            application_overrides=dict(sale_terms),
            agreement_overrides={
                "performance_deadline": "2027-08-01T00:00:00Z",
                "milestone_count": 1,
                "abatement_years": 0,
                "projected_improved_value_cents": 300000,
            },
        )
        # Both of the first two purchases cleared submission: the buyer held
        # zero and then one conveyed parcel, each inside the cap.
        assert awarded["application"]["status"] == "AWARDED"
        assert awarded["property"]["custody_status"] == "CONVEYED"

    standing = fixtures.read_applicant(api, buyer["id"])
    assert standing["conveyed_property_count"] == 2

    third = fixtures.listed_parcel(
        api,
        funding_source=funding_source,
        property_overrides=dict(parcel_shape, address="3212 Umbrella Pine Ln"),
    )
    application = fixtures.draft_application(
        api, third["property"]["id"], buyer["id"], **sale_terms
    )

    response = api.submit_application(
        application["id"], make_applicant_headers(buyer["id"])
    )
    validate_error(response, ApiErrorId.HOMEOWNER_LIMIT_EXCEEDED.value)

    after = fixtures.read_application(api, application["id"])
    assert after["status"] == "DRAFT"
    assert after["revision_round"] == 0
    assert after["version"] == application["version"]
    parcel = fixtures.read_property(api, third["property"]["id"])
    assert parcel["custody_status"] == "LISTED"
