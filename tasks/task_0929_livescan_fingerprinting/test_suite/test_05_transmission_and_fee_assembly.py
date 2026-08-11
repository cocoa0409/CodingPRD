"""Transmission, the retention election and the pinned fee assembly order."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_component_conservation,
    assert_fee_assessment,
    assert_submission,
    assert_tcn_rendering,
    finalize_card,
    new_mobile_event,
    only_fee_assessment,
    open_card,
    pass_positions,
    post_result,
    set_clock,
    setup_checked_in_appointment,
    setup_finalized_card,
    setup_registry,
    transmit_card,
    validate_error,
    validate_success,
)

VA = TEST_USERS["vendor_admin_headers"]
TECH = TEST_USERS["technician_headers"]
SUP = TEST_USERS["supervisor_headers"]
DEST = TEST_USERS["destination_headers"]


def _applicant_paid_first_print():
    """A fixed-site first print under a state-and-FBI ORI charging 3289 / 1350."""
    world = setup_finalized_card(
        clock_start="2026-06-01T09:00:00Z",
        agency_overrides={"payer_regime_default": "APPLICANT_PAID"},
        score=82,
    )
    world["submission"] = transmit_card(
        world["card"]["id"], world["card"]["version"], retention_requested=True
    )
    return world


def test_each_percentage_component_is_rounded_before_it_enters_the_sum(api):
    """PRD 3.9: "Work a real service type through it: `state_fee_cents` 3289, `federal_fee_cents`
    1350, a state-and-FBI ORI, a fixed site, a first print. The processing surcharge is three and a
    half percent of 4639, which is 162.365 and rounds to 162. The vendor tax is seven and a quarter
    percent of 995, which is 72.1375 and rounds to 72. Under `APPLICANT_PAID` the total is 3289 plus
    1350 plus 162 plus 995 plus 72, that is 5868 cents."

    Design: Difficulty/dual_variant_calc/fee_total_rounds_each_percentage_component_before_summing
    """
    world = _applicant_paid_first_print()

    assessment = only_fee_assessment(submission_id=world["submission"]["id"])

    assert_fee_assessment(assessment)
    assert assessment["processing_surcharge_cents"] == 162
    assert assessment["vendor_tax_cents"] == 72
    assert assessment["total_cents"] == 5868
    assert assessment["total_cents"] != 5869, "the sum-then-round reading is not what this API does"


def test_an_applicant_paid_first_print_takes_no_volume_discount(api):
    """PRD 3.9: "`discount_cents` is that percentage of the base, rounded half up — but only when the
    `payer_regime` is `AGENCY_BILLED` or `FEE_WAIVED`; under `APPLICANT_PAID` the discount is 0,
    because the agency is not paying."
    PRD 3.9: "its `payer_regime` — `APPLICANT_PAID`, `AGENCY_BILLED` or `FEE_WAIVED` — is copied from
    the owning agency's `payer_regime_default` at the instant of creation and never re-read
    afterwards."

    Design: Difficulty/dual_variant_calc/fee_total_rounds_each_percentage_component_before_summing
    """
    world = _applicant_paid_first_print()

    assessment = only_fee_assessment(submission_id=world["submission"]["id"])

    assert assessment["payer_regime"] == "APPLICANT_PAID"
    assert assessment["discount_cents"] == 0
    assert assessment["assessment_kind"] == "SUBMISSION"
    assert_component_conservation(assessment)


def _fee_waived_agency_at_tier_one():
    """A FEE_WAIVED agency whose onsite shortfall has already moved it into tier one."""
    world = setup_registry(
        clock_start="2026-06-01T09:00:00Z",
        agency_overrides={"name": "County Schools", "payer_regime_default": "FEE_WAIVED"},
        ori_overrides={"fee_waiver_eligible": True},
    )
    world["event_site"] = new_mobile_event(
        world["agency"]["id"],
        name="District Office Day",
        concurrent_capacity=4,
        event_window_start="2026-06-01T12:00:00Z",
        event_window_end="2026-06-01T16:00:00Z",
        min_billable_prints=25,
    )
    set_clock("2026-06-01T16:30:00Z")
    world["event_site"] = validate_success_reconcile(world["event_site"]["id"])
    setup_checked_in_appointment(
        world,
        scheduled_start="2026-06-02T10:00:00Z",
        checkin_clock="2026-06-02T09:55:00Z",
        applicant_overrides={"full_name": "Cara Nunez"},
    )
    world["card"] = open_card(world["appointment"]["id"], world["device"]["id"])
    pass_positions(world["card"]["id"], 82)
    world["card"] = finalize_card(world["card"]["id"])
    world["submission"] = transmit_card(
        world["card"]["id"], world["card"]["version"], retention_requested=True
    )
    return world


def validate_success_reconcile(site_id):
    from test_helpers import api_client

    return validate_success(api_client.reconcile_event(site_id, VA), 200)


def test_the_waiver_is_applied_before_the_volume_discount(api):
    """PRD 3.9: "Under `FEE_WAIVED` against that same agency, `waived_cents` is 4801, the base is
    1067, the discount is three percent of 1067, which is 32.01 and rounds to 32, and the total is
    1035."
    PRD 3.9: "And applying the volume discount to the pre-waiver base would make the `FEE_WAIVED`
    discount 176 rather than 32, so that total would come out 891 instead of 1035 — this API waives
    first and discounts afterwards."

    Design: Difficulty/combinatorial_formula/waiver_applies_before_discount_with_per_component_rounding
    """
    world = _fee_waived_agency_at_tier_one()

    assessment = only_fee_assessment(submission_id=world["submission"]["id"])

    assert assessment["waived_cents"] == 4801
    assert assessment["discount_cents"] == 32
    assert assessment["total_cents"] == 1035
    assert assessment["total_cents"] != 891, "the discount-before-waiver reading is rejected"
    assert assessment["vendor_convenience_fee_cents"] == 995


def test_an_agency_side_flat_charge_moves_the_discount_tier(api):
    """PRD 3.9: "**The two flat kinds.** A `NO_SHOW` row takes `total_cents` of exactly 1500 and an
    `ONSITE_SHORTFALL` row takes `total_cents` equal to the site's computed `shortfall_charge_cents`.
    Both skip the waiver, the invoiceable base and the volume discount entirely — but both still run
    the ledger step below, so an agency-side flat charge does move that agency's discount tier for
    later assessments."
    PRD 3.9: "**Step five, the ledger.** When the `payer_regime` is `AGENCY_BILLED` or `FEE_WAIVED`,
    `total_cents` is added to the agency's `mtd_billed_cents`. Under `APPLICANT_PAID` nothing is
    added."

    Design: Difficulty/combinatorial_formula/waiver_applies_before_discount_with_per_component_rounding
    """
    world = _fee_waived_agency_at_tier_one()

    shortfall = only_fee_assessment(
        agency_id=world["agency"]["id"], assessment_kind="ONSITE_SHORTFALL"
    )
    assert shortfall["total_cents"] == 55000

    agency = validate_success(api.get_agency(world["agency"]["id"], VA), 200)
    assert agency["mtd_billed_cents"] == 56035


def _agency_billed_first_print_at_forty_thousand_each():
    world = setup_finalized_card(
        clock_start="2026-06-01T09:00:00Z",
        agency_overrides={"name": "Harbor Authority", "payer_regime_default": "AGENCY_BILLED"},
        service_type_overrides={
            "code": "FRM",
            "applicant_type": "FIREARMS",
            "slot_duration_minutes": 45,
            "state_fee_cents": 20000,
            "federal_fee_cents": 20000,
        },
        score=90,
    )
    world["submission"] = transmit_card(world["card"]["id"], world["card"]["version"])
    return world


def test_the_tier_is_read_before_this_assessment_joins_the_running_total(api):
    """PRD 3.9: "**Step three, the agency volume discount.** The tier is read from the agency's
    `mtd_billed_cents` **as it stands before this assessment joins it** — the order is pinned
    precisely because the figure the tier is keyed on is a running total this very row will become
    part of. A `mtd_billed_cents` of at least 200000 selects six percent; otherwise a
    `mtd_billed_cents` of at least 40000 selects three percent; otherwise the discount is zero."

    Design: Difficulty/combinatorial_formula/discount_tier_read_before_this_assessment_joins_the_running_total
    """
    world = _agency_billed_first_print_at_forty_thousand_each()

    assessment = only_fee_assessment(submission_id=world["submission"]["id"])

    assert assessment["processing_surcharge_cents"] == 1400
    assert assessment["discount_cents"] == 0
    assert assessment["total_cents"] == 42467
    assert assessment["total_cents"] != 41193, "the add-then-read reading is rejected"


def test_the_first_agency_billed_row_lands_in_the_month_to_date_ledger(api):
    """PRD 3.9: "**Step five, the ledger.** When the `payer_regime` is `AGENCY_BILLED` or
    `FEE_WAIVED`, `total_cents` is added to the agency's `mtd_billed_cents`. Under `APPLICANT_PAID`
    nothing is added."
    PRD 3.9: "**Step four, the total.** `total_cents` is the base less `discount_cents`."

    Design: Difficulty/combinatorial_formula/discount_tier_read_before_this_assessment_joins_the_running_total
    """
    world = _agency_billed_first_print_at_forty_thousand_each()

    assessment = only_fee_assessment(submission_id=world["submission"]["id"])
    assert assessment["payer_regime"] == "AGENCY_BILLED"
    assert_component_conservation(assessment)

    agency = validate_success(api.get_agency(world["agency"]["id"], VA), 200)
    assert agency["mtd_billed_cents"] == 42467


def _nofed_finalized_card():
    return setup_finalized_card(
        clock_start="2026-06-01T09:00:00Z",
        agency_overrides={"name": "Parks Dept"},
        ori_overrides={"statutory_authority": "NONCRIMINAL_NOFED"},
        service_type_overrides={
            "code": "VOL",
            "applicant_type": "VOLUNTEER",
            "retention_offered": True,
        },
        score=84,
    )


def test_a_nofed_ori_refuses_the_retention_election(api):
    """PRD 3.7: "A `retention_requested` of true at transmission moves it
    `NOT_REQUESTED → GRANTED`, and that election requires two permissions to line up: the ORI's
    `retention_permitted` must be true *and* the service type's `retention_offered` must be true. If
    either is false the transmission is refused with `ERR_RETENTION_NOT_PERMITTED`."
    PRD 3.1: "- `NONCRIMINAL_NOFED` yields `destination_requirement` `STATE_ONLY`,
    `dissemination_tier` `FITNESS_CODE_ONLY`, `retention_permitted` false and `rapback_authority`
    false."

    Design: Difficulty/cross_entity_state_dependency/retention_election_depends_on_ori_statutory_authority
    """
    world = _nofed_finalized_card()

    response = api.create_submission(
        {
            "card_id": world["card"]["id"],
            "retention_requested": True,
            "expected_card_version": world["card"]["version"],
        },
        TECH,
    )

    validate_error(response, ApiErrorId.ERR_RETENTION_NOT_PERMITTED.value)

    ori = validate_success(api.get_ori(world["ori"]["id"], VA), 200)
    assert ori["retention_permitted"] is False
    assert ori["destination_requirement"] == "STATE_ONLY"
    assert world["service_type"]["retention_offered"] is True, "the ORI is the only reason it fails"


def test_a_state_only_transmission_carries_no_federal_component(api):
    """PRD 3.5: "The `fbi_status` axis starts at `PENDING` for a two-destination ORI, but for a
    `STATE_ONLY` ORI it is set to `NOT_REQUIRED` at creation and never leaves that value — and, as a
    direct consequence, that submission's fee assessment carries a `federal_fee_cents` of 0."
    PRD 3.5: "The `tcn_suffix` is 0, and the ORI's `tcn_consumed_count` increases by the number of
    entries in `destinations` — two for a state-and-FBI ORI, one for a state-only ORI."

    Design: Difficulty/cross_entity_state_dependency/retention_election_depends_on_ori_statutory_authority
    """
    world = _nofed_finalized_card()

    submission = validate_success(
        api.create_submission(
            {
                "card_id": world["card"]["id"],
                "retention_requested": False,
                "expected_card_version": world["card"]["version"],
            },
            TECH,
        ),
        201,
    )

    assert_submission(submission)
    assert submission["retention_status"] == "NOT_REQUESTED"
    assert submission["fbi_status"] == "NOT_REQUIRED"
    assert submission["destinations"] == ["STATE"]

    assessment = only_fee_assessment(submission_id=submission["id"])
    assert assessment["federal_fee_cents"] == 0
    assert assessment["processing_surcharge_cents"] == 115
    assert assessment["total_cents"] == 4471

    ori = validate_success(api.get_ori(world["ori"]["id"], VA), 200)
    assert ori["tcn_consumed_count"] == 1


def _suspended_nofed_world():
    world = setup_finalized_card(
        clock_start="2026-06-01T09:00:00Z",
        agency_overrides={"name": "Parks Dept"},
        ori_overrides={"statutory_authority": "NONCRIMINAL_NOFED"},
        service_type_overrides={
            "code": "VOL",
            "applicant_type": "VOLUNTEER",
            "retention_offered": False,
        },
        score=80,
    )
    from test_helpers import api_client

    validate_success(api_client.set_ori_authority_status(world["ori"]["id"], "SUSPENDED", VA), 200)
    return world


def test_a_suspended_ori_cannot_transmit_until_it_is_reinstated(api):
    """PRD 2.9 rung 8: "**ORI authority.** The ORI the operation transmits under has
    `authority_status` `ACTIVE`. Otherwise `ERR_ORI_AUTHORITY_SUSPENDED`, HTTP 409. Scope: exactly
    four endpoints — `POST /livescan/submissions`, `POST /livescan/submissions/{id}/reprints`,
    `POST /livescan/rapback-subscriptions` and `POST /livescan/rapback-subscriptions/{id}/renew`."
    PRD 3.5: "Its `destinations` come straight from that ORI's `destination_requirement`: an ORI at
    `STATE_ONLY` transmits to the single destination `STATE`, and an ORI at `STATE_AND_FBI` transmits
    to both `STATE` and `FBI`."

    Design: Corner/validations/state_only_ori_blocks_fbi_results_and_a_suspended_ori_blocks_transmission
    """
    world = _suspended_nofed_world()
    payload = {
        "card_id": world["card"]["id"],
        "retention_requested": False,
        "expected_card_version": world["card"]["version"],
    }

    refused = api.create_submission(payload, TECH)
    validate_error(refused, ApiErrorId.ERR_ORI_AUTHORITY_SUSPENDED.value)

    validate_success(api.set_ori_authority_status(world["ori"]["id"], "ACTIVE", VA), 200)
    submission = validate_success(api.create_submission(payload, TECH), 201)

    assert submission["destinations"] == ["STATE"]
    assert_tcn_rendering(submission)


def test_an_fbi_result_against_a_state_only_submission_is_unauthorized(api):
    """PRD 3.5: "A destination that is not among the submission's `destinations` is refused with
    `ERR_DESTINATION_NOT_AUTHORIZED`; a second result for an axis that has already reached a terminal
    value is refused with `ERR_RECORD_STATE_INVALID`."
    PRD 3.8: "A submission whose state axis is `ACCEPTED` and whose federal axis is `ACCEPTED` or
    `NOT_REQUIRED` has nothing to reprint and is likewise `ERR_REPRINT_NOT_ENTITLED`."

    Design: Corner/validations/state_only_ori_blocks_fbi_results_and_a_suspended_ori_blocks_transmission
    """
    world = _suspended_nofed_world()
    validate_success(api.set_ori_authority_status(world["ori"]["id"], "ACTIVE", VA), 200)
    submission = validate_success(
        api.create_submission(
            {
                "card_id": world["card"]["id"],
                "retention_requested": False,
                "expected_card_version": world["card"]["version"],
            },
            TECH,
        ),
        201,
    )

    federal = api.post_destination_result(
        submission["id"],
        {"destination": "FBI", "result_code": "ACCEPTED", "record_count": 0, "disqualifying_offense_count": 0},
        DEST,
    )
    validate_error(federal, ApiErrorId.ERR_DESTINATION_NOT_AUTHORIZED.value)

    resulted = post_result(
        submission["id"], "STATE", "ACCEPTED", record_count=0, disqualifying_offense_count=0
    )
    assert resulted["composite_disposition"] == "CLEARED"
    assert resulted["fbi_status"] == "NOT_REQUIRED"

    reprint = api.authorize_reprint(submission["id"], world["device"]["id"], SUP)
    validate_error(reprint, ApiErrorId.ERR_REPRINT_NOT_ENTITLED.value)

    final = validate_success(api.get_submission(submission["id"], TECH), 200)
    assert final["reprint_count"] == 0
