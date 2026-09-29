"""
Cyclic lifecycles: a parcel that comes back and is listed a second time, and an
application that travels the revision loop and the title-suspension loop.

Every test drives the logical clock from its fixed start at 2026-08-01 and runs
the compliance sweep to make deadlines and cure periods bite.
"""

from test_helpers import (
    DISP_1,
    assert_same_instant,
    INTAKE_1,
    INV_1,
    fixtures,
    make_applicant_headers,
    validate_success,
)

# The parcel every scenario below is built on.
PARCEL_AREA_SQFT = 8500
ASSESSED_VALUE_CENTS = 1000000
TITLE_SEARCH_FEE_CENTS = 20000

# A DEVELOPER_RFP quote is 90 percent of the assessed value, above the 500,000
# cent floor, and no condition discount applies to a grade C structure.
RFP_QUOTE_CENTS = 900000
REVISED_OFFER_CENTS = 950000

# The agreement's deadline has already lapsed at the first sweep, and the cure
# period runs 90 days beyond it.
PERFORMANCE_DEADLINE = "2026-09-01T00:00:00Z"
CURE_DEADLINE = "2026-11-30T00:00:00Z"
FIRST_SWEEP_AT = "2026-09-02T00:00:00Z"
SECOND_SWEEP_AT = "2026-12-01T00:00:00Z"


def _listed_parcel(api, *, address):
    """Register, acquire by donation, quiet-title and list one parcel."""
    funding_source = fixtures.create_acquisition_funding_source(api)
    prop = fixtures.create_property(
        api,
        address=address,
        situs_ward=1,
        lot_area_sqft=PARCEL_AREA_SQFT,
        assessed_value_cents=ASSESSED_VALUE_CENTS,
        structure_present=True,
        structure_condition_grade="C",
        vacancy_months=8,
    )
    fixtures.acquire_property(
        api,
        prop["id"],
        funding_source["id"],
        channel="DONATION",
        offer_price_cents=0,
        title_search_fee_cents=TITLE_SEARCH_FEE_CENTS,
        donor_name="Foster Lane Trust",
    )
    first_action = fixtures.open_title_action(api, prop["id"])
    fixtures.adjudicate_title_action(api, first_action["id"], "CLEARED")
    fixtures.list_parcel(api, prop["id"])
    return {
        "funding_source": funding_source,
        "property": prop,
        "first_title_action": first_action,
    }


def _awarded_under_armed_reverter(api, bundle, *, legal_name, contact_email):
    """Carry one developer's application all the way to an executed agreement."""
    buyer = fixtures.create_developer_applicant(
        api, legal_name=legal_name, contact_email=contact_email
    )
    application = fixtures.draft_application(
        api,
        bundle["property"]["id"],
        buyer["id"],
        program="DEVELOPER_RFP",
        proposed_use="Twelve-unit infill apartment building",
        offer_price_cents=RFP_QUOTE_CENTS,
    )
    fixtures.submit_application(api, application["id"], buyer["id"])
    fixtures.screen_application(api, application["id"])
    fixtures.recommend_application(api, application["id"])
    fixtures.board_decide(api, application["id"], "APPROVE")
    agreement = fixtures.execute_agreement(
        api,
        application["id"],
        performance_deadline=PERFORMANCE_DEADLINE,
        milestone_count=2,
        reverter_clause_active=True,
        abatement_years=3,
        discharge_mode="STATUTORY",
        projected_improved_value_cents=10000000,
    )
    bundle["buyer"] = buyer
    bundle["application"] = application
    bundle["agreement"] = agreement
    return bundle


def _submitted_and_revised_application(api, bundle):
    """
    A second developer whose application is returned for information, resubmitted
    with a higher offer and then screened, so that it rests in SCREENED.
    """
    buyer = fixtures.create_developer_applicant(
        api,
        legal_name="Garnet Partners LLC",
        contact_email="bids@garnet-partners.example",
    )
    application = fixtures.draft_application(
        api,
        bundle["property"]["id"],
        buyer["id"],
        program="DEVELOPER_RFP",
        proposed_use="Mixed-use rehabilitation",
        offer_price_cents=RFP_QUOTE_CENTS,
    )
    fixtures.submit_application(api, application["id"], buyer["id"])
    fixtures.request_info(
        api,
        application["id"],
        "Provide the construction financing commitment letter.",
    )
    fixtures.resubmit_application(
        api,
        application["id"],
        buyer["id"],
        offer_price_cents=REVISED_OFFER_CENTS,
        proposed_use="Mixed-use rehabilitation with financing letter attached",
    )
    fixtures.screen_application(api, application["id"])
    bundle["revised_buyer"] = buyer
    bundle["revised_application"] = application
    return bundle


def _drive_reverter(api):
    """Move the clock twice and sweep twice, so the armed reverter fires."""
    fixtures.set_clock(api, FIRST_SWEEP_AT)
    fixtures.run_compliance_sweep(api)
    fixtures.set_clock(api, SECOND_SWEEP_AT)
    return fixtures.run_compliance_sweep(api)


def test_reverted_parcel_re_enters_listed_after_a_second_title_clearing(api):
    """A parcel taken back by a reverter and quiet-titled afresh enters LISTED for a second time, re-stamping listed_at.

    Closing an acquisition moves it to `ACQUIRED`; listing it for disposition moves it to `LISTED`; executing a development agreement moves it to `CONVEYED`; enforcing a reverter moves it to `REVERTED`; and a reverted parcel with freshly cleared title can be listed again, so the cycle `CONVEYED → REVERTED → LISTED` re-enters disposition.

    Design: Difficulty/non_linear_state_machine/property_custody_reverter_cycle_back_to_listed
    """
    bundle = _listed_parcel(api, address="50 Foster Ln")
    bundle = _awarded_under_armed_reverter(
        api,
        bundle,
        legal_name="Foster Redevelopment LLC",
        contact_email="deals@foster-redev.example",
    )
    property_id = bundle["property"]["id"]

    conveyed = fixtures.read_property(api, property_id)
    assert conveyed["custody_status"] == "CONVEYED"

    _drive_reverter(api)

    reverted = fixtures.read_property(api, property_id)
    assert reverted["custody_status"] == "REVERTED"
    assert reverted["title_status"] == "CLOUDED"

    # A reverted parcel needs a fresh title action, which is round 2 on the
    # parcel because one action is already on file.
    second_action = fixtures.open_title_action(api, property_id)
    fixtures.adjudicate_title_action(api, second_action["id"], "CLEARED")
    assert bundle["first_title_action"]["round_no"] == 1
    assert second_action["round_no"] == 2

    relisted = validate_success(
        api.list_property_for_disposition(property_id, DISP_1), 200
    )
    assert relisted["custody_status"] == "LISTED"
    assert_same_instant(relisted["listed_at"], SECOND_SWEEP_AT)
    assert relisted["title_status"] == "CLEAR"
    assert relisted["owner_of_record_applicant_id"] is None
    assert relisted["acquisition_channel"] == "DONATION"

    stored = fixtures.read_property(api, property_id)
    assert stored["custody_status"] == "LISTED"
    assert_same_instant(stored["listed_at"], SECOND_SWEEP_AT)

    # The award that produced the conveyance is terminal and the re-listing
    # leaves it exactly where it was.
    assert (
        fixtures.read_application(api, bundle["application"]["id"])["status"]
        == "AWARDED"
    )


def test_two_sweeps_open_the_cure_period_then_enforce_the_reverter(api):
    """An unperformed agreement first moves into a 90-day cure period and is then reverted once that cure deadline has passed.

    **Step three** enforces the reverter: every agreement in `CURE_PENDING` whose `cure_deadline` has passed while milestones remain outstanding, and whose `reverter_clause_active` is true, moves `CURE_PENDING → REVERTED` and stamps `reverted_at`; where `reverter_clause_active` is false the agreement is left in `CURE_PENDING` and the sweep merely counts it as waived.

    Design: Difficulty/non_linear_state_machine/property_custody_reverter_cycle_back_to_listed
    """
    bundle = _listed_parcel(api, address="50 Foster Ln")
    bundle = _awarded_under_armed_reverter(
        api,
        bundle,
        legal_name="Foster Redevelopment LLC",
        contact_email="deals@foster-redev.example",
    )
    agreement_id = bundle["agreement"]["id"]

    fixtures.set_clock(api, FIRST_SWEEP_AT)
    first_sweep = validate_success(api.run_compliance_sweep(INV_1), 200)
    assert first_sweep["cure_pending_count"] == 1
    assert first_sweep["reverted_count"] == 0
    assert first_sweep["restored_inventory_sqft"] == 0

    in_cure = fixtures.read_agreement(api, agreement_id)
    assert in_cure["status"] == "CURE_PENDING"
    assert_same_instant(in_cure["cure_deadline"], CURE_DEADLINE)
    assert in_cure["milestones_completed"] == 0
    assert in_cure["reverted_at"] is None

    fixtures.set_clock(api, SECOND_SWEEP_AT)
    second_sweep = validate_success(api.run_compliance_sweep(INV_1), 200)
    assert second_sweep["reverted_count"] == 1
    assert second_sweep["cure_pending_count"] == 0
    assert second_sweep["waived_count"] == 0
    assert second_sweep["restored_inventory_sqft"] == PARCEL_AREA_SQFT

    reverted = fixtures.read_agreement(api, agreement_id)
    assert reverted["status"] == "REVERTED"
    assert_same_instant(reverted["reverted_at"], SECOND_SWEEP_AT)
    assert_same_instant(reverted["cure_deadline"], CURE_DEADLINE)


def test_reverter_bars_the_former_buyer_for_the_five_year_lookback(api):
    """Enforcing a reverter counts it against the former buyer and turns its eligibility standing to BARRED.

    The former buyer pays for it too: its `reverter_count` grows by one, `last_reverter_at` is stamped at the current instant, `recent_reverter_count` is recomputed and its `eligibility_status` becomes `BARRED`, which keeps it out of the market for the whole five-year lookback.

    Design: Difficulty/non_linear_state_machine/property_custody_reverter_cycle_back_to_listed
    """
    bundle = _listed_parcel(api, address="50 Foster Ln")
    bundle = _awarded_under_armed_reverter(
        api,
        bundle,
        legal_name="Foster Redevelopment LLC",
        contact_email="deals@foster-redev.example",
    )
    buyer_id = bundle["buyer"]["id"]

    before = fixtures.read_applicant(api, buyer_id)
    assert before["reverter_count"] == 0
    assert before["eligibility_status"] == "ELIGIBLE"

    fixtures.set_clock(api, FIRST_SWEEP_AT)
    fixtures.run_compliance_sweep(api)
    fixtures.set_clock(api, SECOND_SWEEP_AT)
    sweep = validate_success(api.run_compliance_sweep(INV_1), 200)
    assert sweep["reverted_count"] == 1

    after = validate_success(api.get_applicant(buyer_id, DISP_1), 200)
    assert after["reverter_count"] == 1
    assert after["recent_reverter_count"] == 1
    assert_same_instant(after["last_reverter_at"], SECOND_SWEEP_AT)
    assert after["eligibility_status"] == "BARRED"
    assert after["good_standing_count"] == 0


def test_info_requested_revision_cycle_returns_the_application_to_submitted(api):
    """An application sent back for information returns to SUBMITTED on resubmission, with revision_round advanced once and suspended_from_status cleared.

    A resubmission re-runs the entire submission gate ladder of §3.7 against the revised offer and the *current* state of the parcel and the buyer — nothing is grandfathered — then increments `revision_round`, refreshes `submitted_at`, recomputes `quoted_price_cents`, clears `suspended_from_status` to null and advances the `version`.

    Design: Difficulty/non_linear_state_machine/application_info_requested_and_suspended_title_cycles
    """
    bundle = _listed_parcel(api, address="60 Garnet Way")
    buyer = fixtures.create_developer_applicant(
        api,
        legal_name="Garnet Partners LLC",
        contact_email="bids@garnet-partners.example",
    )
    application = fixtures.draft_application(
        api,
        bundle["property"]["id"],
        buyer["id"],
        program="DEVELOPER_RFP",
        proposed_use="Mixed-use rehabilitation",
        offer_price_cents=RFP_QUOTE_CENTS,
    )
    fixtures.submit_application(api, application["id"], buyer["id"])
    assert fixtures.read_application(api, application["id"])["revision_round"] == 0

    returned = validate_success(
        api.request_info(
            application["id"],
            {"information_requested": "Provide the construction financing commitment letter."},
            DISP_1,
        ),
        200,
    )
    assert returned["status"] == "INFO_REQUESTED"

    resubmitted = validate_success(
        api.resubmit_application(
            application["id"],
            {
                "offer_price_cents": REVISED_OFFER_CENTS,
                "proposed_use": "Mixed-use rehabilitation with financing letter attached",
            },
            make_applicant_headers(buyer["id"]),
        ),
        200,
    )
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["revision_round"] == 1
    assert resubmitted["suspended_from_status"] is None
    assert resubmitted["offer_price_cents"] == REVISED_OFFER_CENTS
    assert resubmitted["quoted_price_cents"] == RFP_QUOTE_CENTS

    stored = fixtures.read_application(api, application["id"])
    assert stored["status"] == "SUBMITTED"
    assert stored["revision_round"] == 1
    assert stored["suspended_from_status"] is None


def test_reverter_suspends_the_screened_application_recording_its_prior_status(api):
    """A reverter re-clouds the title and parks another buyer's still-open application in SUSPENDED_TITLE, recording the status it held.

    The agreement's `reverted_at` is stamped; the parcel moves `CONVEYED → REVERTED`, has its `owner_of_record_applicant_id` cleared to null, has its `delinquent_tax_balance_cents` restored by the `discharged_tax_cents` the agreement had forgiven, and has its `current_blight_score` recomputed with the live variant, while its `lot_area_sqft` returns to the conserved inventory area; the reverter deed re-clouds the title, driving `CLEAR → CLOUDED`; and that re-clouding suspends the parcel's live disposition pipeline — every application on that parcel in `SUBMITTED`, `SCREENED` or `RECOMMENDED` records its current status in `suspended_from_status` and moves to `SUSPENDED_TITLE` — the three routes `SUBMITTED → SUSPENDED_TITLE`, `SCREENED → SUSPENDED_TITLE` and `RECOMMENDED → SUSPENDED_TITLE` — to be restored only by a fresh title clearing, which drives `SUSPENDED_TITLE → SUBMITTED`, `SUSPENDED_TITLE → SCREENED` or `SUSPENDED_TITLE → RECOMMENDED` as described in §3.4.

    Design: Difficulty/non_linear_state_machine/application_info_requested_and_suspended_title_cycles
    """
    bundle = _listed_parcel(api, address="60 Garnet Way")
    bundle = _submitted_and_revised_application(api, bundle)
    bundle = _awarded_under_armed_reverter(
        api,
        bundle,
        legal_name="Anvil Development Group",
        contact_email="rfp@anvil-dev.example",
    )
    revised_id = bundle["revised_application"]["id"]

    screened = fixtures.read_application(api, revised_id)
    assert screened["status"] == "SCREENED"
    assert screened["suspended_from_status"] is None

    fixtures.set_clock(api, FIRST_SWEEP_AT)
    fixtures.run_compliance_sweep(api)
    fixtures.set_clock(api, SECOND_SWEEP_AT)
    sweep = validate_success(api.run_compliance_sweep(INV_1), 200)
    assert sweep["reverted_count"] == 1

    suspended = validate_success(
        api.get_disposition_application(revised_id, DISP_1), 200
    )
    assert suspended["status"] == "SUSPENDED_TITLE"
    assert suspended["suspended_from_status"] == "SCREENED"
    assert suspended["revision_round"] == 1
    assert suspended["screening_count"] == 1

    parcel = fixtures.read_property(api, bundle["property"]["id"])
    assert parcel["custody_status"] == "REVERTED"
    assert parcel["title_status"] == "CLOUDED"

    # The awarded application is terminal, so the reverter does not suspend it.
    assert (
        fixtures.read_application(api, bundle["application"]["id"])["status"]
        == "AWARDED"
    )
    assert fixtures.read_agreement(api, bundle["agreement"]["id"])["status"] == "REVERTED"


def test_fresh_title_clearing_restores_the_suspended_application_to_screened(api):
    """Clearing the title after a reverter restores a suspended application to exactly the status recorded in suspended_from_status.

    Every disposition application on the parcel that is parked in `SUSPENDED_TITLE` is restored, in the same request, to the exact status recorded in its `suspended_from_status` — `SUBMITTED`, `SCREENED` or `RECOMMENDED` — after which `suspended_from_status` is cleared to null and each restored application's `version` advances by one.

    Design: Difficulty/non_linear_state_machine/application_info_requested_and_suspended_title_cycles
    """
    bundle = _listed_parcel(api, address="60 Garnet Way")
    bundle = _submitted_and_revised_application(api, bundle)
    bundle = _awarded_under_armed_reverter(
        api,
        bundle,
        legal_name="Anvil Development Group",
        contact_email="rfp@anvil-dev.example",
    )
    property_id = bundle["property"]["id"]
    revised_id = bundle["revised_application"]["id"]

    _drive_reverter(api)
    parked = fixtures.read_application(api, revised_id)
    assert parked["status"] == "SUSPENDED_TITLE"
    assert parked["suspended_from_status"] == "SCREENED"
    version_while_parked = parked["version"]

    second_action = fixtures.open_title_action(api, property_id)
    adjudicated = validate_success(
        api.adjudicate_title_action(second_action["id"], {"outcome": "CLEARED"}, INTAKE_1),
        200,
    )
    assert adjudicated["status"] == "CLEARED"

    restored = validate_success(
        api.get_disposition_application(revised_id, DISP_1), 200
    )
    assert restored["status"] == "SCREENED"
    assert restored["suspended_from_status"] is None
    assert restored["screening_count"] == 1
    assert restored["revision_round"] == 1
    assert restored["quoted_price_cents"] == RFP_QUOTE_CENTS
    assert restored["offer_price_cents"] == REVISED_OFFER_CENTS
    assert restored["version"] == version_while_parked + 1

    assert fixtures.read_property(api, property_id)["title_status"] == "CLEAR"
