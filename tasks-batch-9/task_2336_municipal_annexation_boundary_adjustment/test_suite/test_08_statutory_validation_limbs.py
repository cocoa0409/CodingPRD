"""Statutory refusals across the annexation ladder.

Every write in this domain is guarded by a stack of statutory gates: territory
certification proves contiguity, urban character and service capability;
the petition limb polices duplicate and over-100% signatures; the hearing limb
polices its temporal windows and the council's fiscal tolerance; and the
closing acts — effectuation, tax-roll posting and commission submission — are
each admissible exactly once. These tests pin the specific refusal each gate
raises, and the two boundaries the statute treats as inclusive.
"""
from test_helpers import (
    assertions,
    factories,
    fixtures,
    get_success_data,
    make_municipal_planner_headers,
    make_property_owner_headers,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import (
    ERR_ANALYSIS_STATE_INVALID,
    ERR_CASE_STATE_INVALID,
    ERR_COMMISSION_REVIEW_NOT_PENDING,
    ERR_CONSENT_ALREADY_WITHDRAWN,
    ERR_CONSENT_DUPLICATE,
    ERR_CONSENT_OWNERSHIP_SHARE_INVALID,
    ERR_COOLING_OFF_NOT_ELAPSED,
    ERR_DE_ANNEXATION_NOT_ALLOWED,
    ERR_FILING_ALREADY_WITHDRAWN,
    ERR_FILING_DUPLICATE,
    ERR_FISCAL_DEFICIT_EXCEEDS_TOLERANCE,
    ERR_FISCAL_METHOD_NOT_AUTHORIZED,
    ERR_HEARING_NOT_STARTED,
    ERR_METHOD_NOT_AUTHORIZED_BY_STATUTE,
    ERR_PARCEL_ALREADY_IN_PENDING_CASE,
    ERR_PARCEL_CASE_MISMATCH,
    ERR_PARCEL_STATE_INVALID,
    ERR_PETITION_ALREADY_CIRCULATING,
    ERR_PETITION_INSUFFICIENT,
    ERR_PLAN_SERVICE_TIMELINE_EXCEEDS_STATUTE,
    ERR_PREDECESSOR_NOT_EFFECTIVE,
    ERR_PROTEST_OWNERSHIP_SHARE_INVALID,
    ERR_PROTEST_PERIOD_CLOSED,
    ERR_PROTEST_PERIOD_NOT_CLOSED,
    ERR_PROVIDER_SERVICE_TYPE_MISMATCH,
    ERR_SERVICE_CAPABILITY_INSUFFICIENT,
    ERR_TAX_ROLL_ALREADY_POSTED,
    ERR_TERRITORY_EMPTY,
    ERR_TERRITORY_NOT_CONTIGUOUS,
    ERR_URBAN_DEVELOPMENT_TEST_FAILED,
)

# A hearing far enough beyond the 30-day notice window that the notice gate is
# satisfied long before the hearing's own start instant is reached.
_LATE_HEARING_START = "2026-12-01T18:00:00Z"
_LATE_HEARING_END = "2026-12-01T20:00:00Z"
_CLOCK_BEFORE_HEARING = "2026-09-10T09:00:00Z"
_CLOCK_AT_LATE_HEARING = "2026-12-01T18:00:00Z"
# One minute past the close of a 3-day objection window opened at the hearing.
_CLOCK_PAST_LATE_PROTEST_CLOSE = "2026-12-04T18:01:00Z"


def _statute(**overrides):
    """Statute profile overrides; every field left out takes its declared
    default, and the city registered beneath it inherits the profile's own
    `state_code`."""
    return dict(overrides)


def _late_noticed_case(api, protest_window_days=3):
    """A certified INVOLUNTARY_ORDINANCE case with an adopted plan whose
    hearing is noticed at the startup clock but scheduled months later."""
    ctx = fixtures.setup_certified_case(api, statute=_statute())
    fixtures.setup_adopted_plan(api, ctx)
    fixtures.setup_hearing_noticed(
        api,
        ctx,
        scheduled_start_at=_LATE_HEARING_START,
        scheduled_end_at=_LATE_HEARING_END,
        protest_window_days=protest_window_days,
    )
    return ctx


# ==========================================================================
# Territory certification and case shape
# ==========================================================================
def test_certifying_a_case_with_no_parcels_is_refused_as_an_empty_territory(api):
    """PRD §3.2: "An annexation case must hold at least one parcel in
    `PROPOSED` or `PENDING_ANNEX`, and a de-annexation case's predecessor must
    hold at least one parcel in `INCORPORATED`; an empty territory draws
    `ERR_TERRITORY_EMPTY`."

    Design: Corner/validations/certify_territory_rejects_every_disqualified_territory_and_case_shape
    """
    ctx = fixtures.setup_jurisdiction(
        api, statute=_statute(authorized_methods=["INVOLUNTARY_ORDINANCE"])
    )
    case = fixtures.create_case(api, ctx["municipality"]["id"])

    response = api.certify_territory(ctx["planner_headers"], case["id"])

    validate_error(response, ERR_TERRITORY_EMPTY)


def test_certifying_a_method_the_statute_does_not_authorize_is_refused(api):
    """PRD §3.2: "It requires the case to be in `DRAFT`, and it requires the
    case's `method` to appear in the statute's `authorized_methods` — otherwise
    `ERR_METHOD_NOT_AUTHORIZED_BY_STATUTE`."

    Design: Corner/validations/certify_territory_rejects_every_disqualified_territory_and_case_shape
    """
    # The statute authorizes involuntary ordinances only, so a petition case
    # can never be certified beneath it.
    ctx = fixtures.setup_jurisdiction(
        api, statute=_statute(authorized_methods=["INVOLUNTARY_ORDINANCE"])
    )
    municipality_id = ctx["municipality"]["id"]
    case = fixtures.create_case(
        api,
        municipality_id,
        method="PETITION_MAJORITY",
        total_lot_count=1,
        developed_lot_count=1,
        dwelling_units=4,
    )
    owner = fixtures.create_owner(api)
    fixtures.add_parcel(api, municipality_id, case["id"], owner["id"], acreage=1.00)

    response = api.certify_territory(ctx["planner_headers"], case["id"])

    validate_error(response, ERR_METHOD_NOT_AUTHORIZED_BY_STATUTE)


def test_certifying_a_territory_below_the_contiguity_minimum_is_refused(api):
    """PRD §3.2: "If it is below the statute's `contiguity_min_ratio` the
    certification is refused with `ERR_TERRITORY_NOT_CONTIGUOUS`; a ratio
    exactly equal to the minimum passes."

    Design: Corner/validations/certify_territory_rejects_every_disqualified_territory_and_case_shape
    """
    ctx = fixtures.setup_jurisdiction(
        api, statute=_statute(authorized_methods=["INVOLUNTARY_ORDINANCE"])
    )
    municipality_id = ctx["municipality"]["id"]
    # 8,000 shared feet against an 80,000-foot corporate perimeter is a ratio
    # of 0.1000, under the statutory 0.1250 minimum.
    case = fixtures.create_case(
        api,
        municipality_id,
        shared_boundary_feet=8000,
        total_lot_count=1,
        developed_lot_count=1,
        dwelling_units=4,
    )
    owner = fixtures.create_owner(api)
    fixtures.add_parcel(api, municipality_id, case["id"], owner["id"], acreage=1.00)

    response = api.certify_territory(ctx["planner_headers"], case["id"])

    validate_error(response, ERR_TERRITORY_NOT_CONTIGUOUS)


def test_certifying_a_territory_failing_both_urban_limbs_is_refused(api):
    """PRD §3.2: "`urban_development_qualified` is set true when either limb
    passes and false when neither does; false refuses the certification with
    `ERR_URBAN_DEVELOPMENT_TEST_FAILED`."

    Design: Corner/validations/certify_territory_rejects_every_disqualified_territory_and_case_shape
    """
    ctx = fixtures.setup_jurisdiction(
        api, statute=_statute(authorized_methods=["INVOLUNTARY_ORDINANCE"])
    )
    municipality_id = ctx["municipality"]["id"]
    # 1 developed lot of 10 is a 0.1000 developed ratio, under the 0.60
    # subdivision minimum, and one dwelling unit on one acre is a density of
    # 1.0000, under the 2.00 minimum: both limbs fail at once.
    case = fixtures.create_case(
        api,
        municipality_id,
        total_lot_count=10,
        developed_lot_count=1,
        dwelling_units=1,
    )
    owner = fixtures.create_owner(api)
    fixtures.add_parcel(
        api,
        municipality_id,
        case["id"],
        owner["id"],
        acreage=1.00,
        is_developed=False,
        dwelling_units=1,
    )

    response = api.certify_territory(ctx["planner_headers"], case["id"])

    validate_error(response, ERR_URBAN_DEVELOPMENT_TEST_FAILED)


def test_certifying_a_territory_under_the_qualification_index_floor_is_refused(api):
    """PRD §3.2: "An index below the statute's `min_qualification_index`
    refuses the certification with `ERR_SERVICE_CAPABILITY_INSUFFICIENT`; an
    index exactly equal to the minimum passes."

    Design: Corner/validations/certify_territory_rejects_every_disqualified_territory_and_case_shape
    """
    ctx = fixtures.setup_jurisdiction(
        api, statute=_statute(authorized_methods=["INVOLUNTARY_ORDINANCE"])
    )
    municipality_id = ctx["municipality"]["id"]
    # Contiguity 0.1250 clears the minimum and earns half the ramp (50.00),
    # the developed-lot limb earns the 25-point urban bonus, and five miles of
    # service distance costs two whole miles beyond the first three (20
    # points): 55.00 against the 60.00 floor.
    case = fixtures.create_case(
        api,
        municipality_id,
        shared_boundary_feet=10000,
        total_lot_count=1,
        developed_lot_count=1,
        dwelling_units=1,
        max_service_distance_miles=5,
    )
    owner = fixtures.create_owner(api)
    fixtures.add_parcel(
        api,
        municipality_id,
        case["id"],
        owner["id"],
        acreage=1.00,
        dwelling_units=1,
    )

    response = api.certify_territory(ctx["planner_headers"], case["id"])

    validate_error(response, ERR_SERVICE_CAPABILITY_INSUFFICIENT)


def test_certifying_a_de_annexation_against_another_citys_predecessor_is_refused(api):
    """PRD §3.2: "For a de-annexation case it additionally requires the statute
    to permit de-annexation (`ERR_DE_ANNEXATION_NOT_ALLOWED`) and the
    predecessor case to be in `EFFECTIVE` status and belong to the same
    municipality — a predecessor in any other status, or one belonging to
    another city, draws `ERR_PREDECESSOR_NOT_EFFECTIVE`."

    Design: Corner/validations/certify_territory_rejects_every_disqualified_territory_and_case_shape
    """
    ctx = fixtures.setup_effective_case(api, statute=_statute())
    # A second city under the same statute: the predecessor's territory is
    # incorporated land, but it is not this city's land.
    other_city = fixtures.create_municipality(api, ctx["statute"]["id"])
    other_planner = make_municipal_planner_headers(other_city["id"])
    successor = get_success_data(
        api.create_annexation_case(
            other_planner,
            factories.de_annexation_case_payload(other_city["id"], ctx["case"]["id"]),
        ),
        201,
    )

    response = api.certify_territory(other_planner, successor["id"])

    validate_error(response, ERR_PREDECESSOR_NOT_EFFECTIVE)


def test_reusing_a_parcel_number_held_by_a_live_sibling_case_is_refused(api):
    """PRD §3.2: "A parcel number may not be claimed twice within a city while
    an earlier claim is still live: if the same `parcel_apn` already appears on
    a parcel in another case of the same municipality whose status is neither
    terminal nor `EFFECTIVE`, the addition is refused with
    `ERR_PARCEL_ALREADY_IN_PENDING_CASE` — an already-annexed parcel, by
    contrast, may be re-described by a later case."

    Design: Corner/validations/certify_territory_rejects_every_disqualified_territory_and_case_shape
    """
    ctx = fixtures.setup_jurisdiction(
        api, statute=_statute(authorized_methods=["INVOLUNTARY_ORDINANCE"])
    )
    municipality_id = ctx["municipality"]["id"]
    owner = fixtures.create_owner(api)
    first_case = fixtures.create_case(api, municipality_id)
    second_case = fixtures.create_case(api, municipality_id)
    contested_apn = factories.unique_apn("REUSE")
    fixtures.add_parcel(
        api, municipality_id, first_case["id"], owner["id"], parcel_apn=contested_apn
    )

    response = api.create_parcel(
        ctx["planner_headers"],
        second_case["id"],
        factories.parcel_payload(owner["id"], parcel_apn=contested_apn),
    )

    validate_error(response, ERR_PARCEL_ALREADY_IN_PENDING_CASE)


def test_adding_a_parcel_to_a_case_that_has_left_draft_is_refused(api):
    """PRD §3.2: "Adding a parcel to a case that has left `DRAFT`, or excluding
    a parcel whose `parcel_status` is neither `PROPOSED` nor `PENDING_ANNEX`,
    is refused with `ERR_PARCEL_STATE_INVALID`."

    Design: Corner/validations/certify_territory_rejects_every_disqualified_territory_and_case_shape
    """
    ctx = fixtures.setup_certified_case(api, statute=_statute())
    owner = fixtures.create_owner(api)

    response = api.create_parcel(
        fixtures.planner(ctx),
        ctx["case"]["id"],
        factories.parcel_payload(owner["id"]),
    )

    validate_error(response, ERR_PARCEL_STATE_INVALID)


def test_opening_an_annexation_case_with_a_predecessor_is_refused(api):
    """PRD §3.2: "Supplying a predecessor on an annexation case, omitting one on
    a de-annexation case, or opening a de-annexation case under a statute whose
    `de_annexation_allowed` is false all draw `ERR_DE_ANNEXATION_NOT_ALLOWED`."

    Design: Corner/validations/certify_territory_rejects_every_disqualified_territory_and_case_shape
    """
    ctx = fixtures.setup_jurisdiction(
        api, statute=_statute(authorized_methods=["INVOLUNTARY_ORDINANCE"])
    )
    municipality_id = ctx["municipality"]["id"]
    existing = fixtures.create_case(api, municipality_id)

    response = api.create_annexation_case(
        ctx["planner_headers"],
        factories.annexation_case_payload(
            municipality_id, predecessor_case_id=existing["id"]
        ),
    )

    validate_error(response, ERR_DE_ANNEXATION_NOT_ALLOWED)


def test_opening_a_petition_before_the_territory_is_certified_is_refused(api):
    """PRD §3.3: "Opening a petition from any other case status draws
    `ERR_CASE_STATE_INVALID`."

    Design: Corner/validations/certify_territory_rejects_every_disqualified_territory_and_case_shape
    """
    ctx = fixtures.setup_jurisdiction(
        api, statute=_statute(authorized_methods=["PETITION_MAJORITY"])
    )
    municipality_id = ctx["municipality"]["id"]
    # The case is still DRAFT: only a TERRITORY_CERTIFIED case may circulate.
    case = fixtures.create_case(api, municipality_id, method="PETITION_MAJORITY")

    response = api.create_petition(
        ctx["planner_headers"], factories.petition_payload(case["id"])
    )

    validate_error(response, ERR_CASE_STATE_INVALID)


# ==========================================================================
# The petition limb
# ==========================================================================
def _circulating_petition(api, parcel_values_cents=(40000000, 60000000)):
    """A certified PETITION_MAJORITY case with one circulating petition."""
    ctx = fixtures.setup_certified_case(
        api,
        statute=_statute(),
        case={"method": "PETITION_MAJORITY"},
        parcel_values_cents=list(parcel_values_cents),
    )
    fixtures.open_petition(api, ctx, petition_type="OWNER_MAJORITY")
    return ctx


def test_a_repeat_signature_on_the_same_petition_parcel_and_owner_is_refused(api):
    """PRD §3.3: "No `SIGNED` consent may already exist for the same
    combination of petition, parcel and owner — a repeat draws
    `ERR_CONSENT_DUPLICATE`."

    Design: Corner/validations/petition_limb_rejects_duplicate_shares_and_insufficient_signatures
    """
    ctx = _circulating_petition(api)
    fixtures.sign_consent(api, ctx, parcel_index=0)
    owner = ctx["owners"][0]

    response = api.create_consent(
        make_property_owner_headers(owner["id"]),
        factories.consent_payload(
            ctx["petition"]["id"], ctx["parcels"][0]["id"], owner["id"], 100.00
        ),
    )

    validate_error(response, ERR_CONSENT_DUPLICATE)


def test_signatures_taking_one_parcels_shares_past_one_hundred_are_refused(api):
    """PRD §3.3: "And the sum of `ownership_share_pct` across all `SIGNED`
    consents for that same petition and parcel may not exceed one hundred, or
    `ERR_CONSENT_OWNERSHIP_SHARE_INVALID` is returned."

    Design: Corner/validations/petition_limb_rejects_duplicate_shares_and_insufficient_signatures
    """
    ctx = _circulating_petition(api)
    fixtures.sign_consent(api, ctx, parcel_index=0)
    # A different owner adding a single further percentage point on the same
    # parcel already carrying a 100.00% signature.
    second_owner = ctx["owners"][1]

    response = api.create_consent(
        make_property_owner_headers(second_owner["id"]),
        factories.consent_payload(
            ctx["petition"]["id"], ctx["parcels"][0]["id"], second_owner["id"], 1.00
        ),
    )

    validate_error(response, ERR_CONSENT_OWNERSHIP_SHARE_INVALID)


def test_a_signature_on_a_parcel_of_another_case_is_refused(api):
    """PRD §3.3: "The referenced parcel must belong to the same case as the
    referenced petition, or the request is refused with
    `ERR_PARCEL_CASE_MISMATCH`."

    Design: Corner/validations/petition_limb_rejects_duplicate_shares_and_insufficient_signatures
    """
    ctx = _circulating_petition(api)
    municipality_id = ctx["municipality"]["id"]
    foreign_case = fixtures.create_case(
        api, municipality_id, method="PETITION_MAJORITY"
    )
    foreign_owner = fixtures.create_owner(api)
    foreign_parcel = fixtures.add_parcel(
        api, municipality_id, foreign_case["id"], foreign_owner["id"]
    )

    response = api.create_consent(
        make_property_owner_headers(foreign_owner["id"]),
        factories.consent_payload(
            ctx["petition"]["id"], foreign_parcel["id"], foreign_owner["id"], 50.00
        ),
    )

    validate_error(response, ERR_PARCEL_CASE_MISMATCH)


def test_a_second_petition_while_one_is_still_circulating_is_refused(api):
    """PRD §3.3: "If any petition of the case is still `CIRCULATING` or already
    `SUFFICIENT`, the attempt is refused with
    `ERR_PETITION_ALREADY_CIRCULATING`."

    Design: Corner/validations/petition_limb_rejects_duplicate_shares_and_insufficient_signatures
    """
    ctx = _circulating_petition(api)

    response = api.create_petition(
        fixtures.planner(ctx),
        factories.petition_payload(ctx["case"]["id"], petition_type="OWNER_MAJORITY"),
    )

    validate_error(response, ERR_PETITION_ALREADY_CIRCULATING)


def test_withdrawing_an_already_withdrawn_signature_is_refused(api):
    """PRD §3.3: "A `PropertyOwner` or `CityClerk` may withdraw a consent that
    is still `SIGNED`; a second attempt on the same consent draws
    `ERR_CONSENT_ALREADY_WITHDRAWN`."

    Design: Corner/validations/petition_limb_rejects_duplicate_shares_and_insufficient_signatures
    """
    ctx = _circulating_petition(api)
    consent = fixtures.sign_consent(api, ctx, parcel_index=1)
    owner_headers = make_property_owner_headers(ctx["owners"][1]["id"])
    validate_success(api.withdraw_consent(owner_headers, consent["id"]))

    response = api.withdraw_consent(owner_headers, consent["id"])

    validate_error(response, ERR_CONSENT_ALREADY_WITHDRAWN)


def test_certifying_a_petition_under_the_signature_threshold_is_refused(api):
    """PRD §3.3: "When the threshold is not met, the certification is refused
    with `ERR_PETITION_INSUFFICIENT`."

    Design: Corner/validations/petition_limb_rejects_duplicate_shares_and_insufficient_signatures
    """
    ctx = _circulating_petition(api)
    # Only the 40,000,000-cent parcel of a 100,000,000-cent territory signs, so
    # support stands at 40.00% against the statutory 50.00 threshold.
    fixtures.sign_consent(api, ctx, parcel_index=0)

    response = api.certify_sufficiency(fixtures.clerk(ctx), ctx["petition"]["id"])

    validate_error(response, ERR_PETITION_INSUFFICIENT)


def test_two_signatures_summing_to_exactly_one_hundred_are_both_accepted(api):
    """PRD §3.3: "And the sum of `ownership_share_pct` across all `SIGNED`
    consents for that same petition and parcel may not exceed one hundred, or
    `ERR_CONSENT_OWNERSHIP_SHARE_INVALID` is returned."

    Design: Corner/validations/consent_shares_summing_to_exactly_one_hundred_certify_at_the_threshold
    """
    ctx = _circulating_petition(api, parcel_values_cents=(50000000, 50000000))
    parcel = ctx["parcels"][0]
    first_owner, second_owner = ctx["owners"][0], ctx["owners"][1]

    # 60.00 plus 40.00 reaches exactly one hundred, which the cap admits.
    first = get_success_data(
        api.create_consent(
            make_property_owner_headers(first_owner["id"]),
            factories.consent_payload(
                ctx["petition"]["id"], parcel["id"], first_owner["id"], 60.00
            ),
        ),
        201,
    )
    second = get_success_data(
        api.create_consent(
            make_property_owner_headers(second_owner["id"]),
            factories.consent_payload(
                ctx["petition"]["id"], parcel["id"], second_owner["id"], 40.00
            ),
        ),
        201,
    )

    assert first["consent_status"] == "SIGNED"
    assert second["consent_status"] == "SIGNED"
    assert first["qualified_value_cents"] == assertions.expected_share_value_cents(
        50000000, 60.00
    )
    assert second["qualified_value_cents"] == assertions.expected_share_value_cents(
        50000000, 40.00
    )


def test_support_at_exactly_the_signature_threshold_certifies_as_sufficient(api):
    """PRD §3.3: "A petition of type `OWNER_100` meets its threshold only when
    the measured percentage is at least 100.00; a petition of type
    `OWNER_MAJORITY` meets it when the measured percentage is at least the
    statute's `signature_threshold_pct`."

    Design: Corner/validations/consent_shares_summing_to_exactly_one_hundred_certify_at_the_threshold
    """
    ctx = _circulating_petition(api, parcel_values_cents=(50000000, 50000000))
    parcel = ctx["parcels"][0]
    first_owner, second_owner = ctx["owners"][0], ctx["owners"][1]
    # One fully signed 50,000,000-cent parcel of a 100,000,000-cent territory
    # is exactly the statutory 50.00 threshold.
    fixtures.sign_consent(api, ctx, parcel_index=0, owner_index=0, ownership_share_pct=60.00)
    get_success_data(
        api.create_consent(
            make_property_owner_headers(second_owner["id"]),
            factories.consent_payload(
                ctx["petition"]["id"], parcel["id"], second_owner["id"], 40.00
            ),
        ),
        201,
    )
    assert first_owner["id"] != second_owner["id"]

    petition = get_success_data(
        api.certify_sufficiency(fixtures.clerk(ctx), ctx["petition"]["id"])
    )

    assert petition["sufficiency_status"] == "SUFFICIENT"
    assert petition["qualified_signature_assessed_value_cents"] == 50000000
    assertions.assert_numeric_equals(
        petition["signature_value_pct"], 50.00, "signature_value_pct"
    )
    case = fixtures.read_case(api, ctx["municipality"]["id"], ctx["case"]["id"])
    assert case["status"] == "SUFFICIENCY_REVIEW"


# ==========================================================================
# The written-objection window
# ==========================================================================
def _open_protest_window(api):
    """A case whose hearing has been held, so its objection window is open."""
    ctx = fixtures.setup_certified_case(api, statute=_statute())
    fixtures.setup_adopted_plan(api, ctx)
    fixtures.setup_hearing_noticed(api, ctx)
    fixtures.setup_hearing_held(api, ctx)
    return ctx


def test_a_repeat_protest_on_the_same_hearing_parcel_and_owner_is_refused(api):
    """PRD §3.6: "No `FILED` filing may already exist for the same hearing,
    parcel and owner (`ERR_FILING_DUPLICATE`), and the sum of
    `ownership_share_pct` across all `FILED` filings for the same hearing and
    parcel may not exceed one hundred
    (`ERR_PROTEST_OWNERSHIP_SHARE_INVALID`)."

    Design: Corner/validations/protest_window_rejects_duplicate_and_over_share_filings
    """
    ctx = _open_protest_window(api)
    fixtures.file_protest(api, ctx, parcel_index=0)
    owner = ctx["owners"][0]

    # A smaller share does not make the second filing a different objection.
    response = api.create_protest_filing(
        make_property_owner_headers(owner["id"]),
        factories.protest_filing_payload(
            ctx["hearing"]["id"], ctx["parcels"][0]["id"], owner["id"], 50.00
        ),
    )

    validate_error(response, ERR_FILING_DUPLICATE)


def test_protests_taking_one_parcels_shares_past_one_hundred_are_refused(api):
    """PRD §3.6: "No `FILED` filing may already exist for the same hearing,
    parcel and owner (`ERR_FILING_DUPLICATE`), and the sum of
    `ownership_share_pct` across all `FILED` filings for the same hearing and
    parcel may not exceed one hundred
    (`ERR_PROTEST_OWNERSHIP_SHARE_INVALID`)."

    Design: Corner/validations/protest_window_rejects_duplicate_and_over_share_filings
    """
    ctx = _open_protest_window(api)
    fixtures.file_protest(api, ctx, parcel_index=0)
    second_owner = ctx["owners"][1]

    response = api.create_protest_filing(
        make_property_owner_headers(second_owner["id"]),
        factories.protest_filing_payload(
            ctx["hearing"]["id"], ctx["parcels"][0]["id"], second_owner["id"], 1.00
        ),
    )

    validate_error(response, ERR_PROTEST_OWNERSHIP_SHARE_INVALID)


def test_withdrawing_an_already_withdrawn_protest_is_refused(api):
    """PRD §3.6: "An owner may withdraw a filing that is still `FILED` while
    the protest period remains open, which sets `filing_status` to `WITHDRAWN`
    and resets `protest_value_cents` to 0; withdrawing an already-withdrawn
    filing draws `ERR_FILING_ALREADY_WITHDRAWN`, and withdrawing after the
    period closed draws `ERR_PROTEST_PERIOD_CLOSED`."

    Design: Corner/validations/protest_window_rejects_duplicate_and_over_share_filings
    """
    ctx = _open_protest_window(api)
    filing = fixtures.file_protest(api, ctx, parcel_index=1)
    owner_headers = make_property_owner_headers(ctx["owners"][1]["id"])
    validate_success(api.withdraw_protest_filing(owner_headers, filing["id"]))

    response = api.withdraw_protest_filing(owner_headers, filing["id"])

    validate_error(response, ERR_FILING_ALREADY_WITHDRAWN)


# ==========================================================================
# The hearing's temporal and fiscal gates
# ==========================================================================
def test_holding_a_hearing_before_its_scheduled_start_is_refused(api):
    """PRD §3.6: "Four conditions apply, and their order is the order of §2.10:
    the hearing must still be `SCHEDULED` (`ERR_HEARING_NOT_SCHEDULED`), no
    sibling hearing of the same case may already be `HELD`
    (`ERR_HEARING_ALREADY_HELD`), the hearing must have a `notice_published_at`
    that is not null (`ERR_NOTICE_NOT_PUBLISHED`), the logical clock must have
    reached `notice_published_at` advanced by the statute's `notice_min_days`
    days (`ERR_NOTICE_WINDOW_NOT_SATISFIED`), and the clock must have reached
    the hearing's own `scheduled_start_at` (`ERR_HEARING_NOT_STARTED`)."

    Design: Corner/validations/hearing_lifecycle_enforces_its_temporal_and_fiscal_gates_in_order
    """
    ctx = _late_noticed_case(api)
    # Notice was published at the startup clock, so its 30-day window is long
    # elapsed; only the hearing's own start instant is still in the future.
    fixtures.set_clock(api, _CLOCK_BEFORE_HEARING)

    response = api.hold_hearing(fixtures.clerk(ctx), ctx["hearing"]["id"])

    validate_error(response, ERR_HEARING_NOT_STARTED)


def test_closing_the_objection_window_before_it_expires_is_refused(api):
    """PRD §3.6: "Closing the protest period is the tabulation, and it is
    admissible only when the hearing is `HELD` with `protest_outcome` still
    `OPEN` — otherwise `ERR_PROTEST_PERIOD_CLOSED` — and only once the logical
    clock has moved strictly past `protest_closes_at`, since an equal reading
    still leaves the last day open and draws
    `ERR_PROTEST_PERIOD_NOT_CLOSED`."

    Design: Corner/validations/hearing_lifecycle_enforces_its_temporal_and_fiscal_gates_in_order
    """
    ctx = _late_noticed_case(api)
    fixtures.setup_hearing_held(api, ctx, clock_at_hearing=_CLOCK_AT_LATE_HEARING)

    # The clock still stands at the hearing instant, three days short of the
    # close of the objection window it just opened.
    response = api.close_protest_period(fixtures.clerk(ctx), ctx["hearing"]["id"])

    validate_error(response, ERR_PROTEST_PERIOD_NOT_CLOSED)


def test_adopting_the_ordinance_before_the_cooling_off_period_elapses_is_refused(api):
    """PRD §3.7: "The statutory cooling-off period must have run: the logical
    clock must have reached the case's `hearing_held_at` advanced by the
    statute's `hearing_to_ordinance_min_days` days, with an earlier reading
    refused as `ERR_COOLING_OFF_NOT_ELAPSED` and exact equality accepted."

    Design: Corner/validations/hearing_lifecycle_enforces_its_temporal_and_fiscal_gates_in_order
    """
    ctx = _late_noticed_case(api)
    fixtures.setup_hearing_held(api, ctx, clock_at_hearing=_CLOCK_AT_LATE_HEARING)
    # No objections were filed, so the tabulation fails the protest and leaves
    # the case adoptable — but only ten days after the hearing was held.
    fixtures.close_protest_period(
        api, ctx, clock_after_window=_CLOCK_PAST_LATE_PROTEST_CLOSE
    )
    assert ctx["hearing"]["protest_outcome"] == "FAILED"

    response = api.adopt_ordinance(fixtures.clerk(ctx), ctx["case"]["id"])

    validate_error(response, ERR_COOLING_OFF_NOT_ELAPSED)


def test_filing_a_protest_after_the_window_was_closed_is_refused(api):
    """PRD §3.6: "The protest period must be open, or
    `ERR_PROTEST_PERIOD_CLOSED`, and the logical clock — which becomes the
    filing's `filed_at` — must lie inside the closed interval from
    `protest_opens_at` through `protest_closes_at` inclusive, or
    `ERR_PROTEST_FILING_OUT_OF_WINDOW`."

    Design: Corner/validations/hearing_lifecycle_enforces_its_temporal_and_fiscal_gates_in_order
    """
    ctx = _late_noticed_case(api)
    fixtures.setup_hearing_held(api, ctx, clock_at_hearing=_CLOCK_AT_LATE_HEARING)
    fixtures.close_protest_period(
        api, ctx, clock_after_window=_CLOCK_PAST_LATE_PROTEST_CLOSE
    )
    owner = ctx["owners"][0]

    response = api.create_protest_filing(
        make_property_owner_headers(owner["id"]),
        factories.protest_filing_payload(
            ctx["hearing"]["id"], ctx["parcels"][0]["id"], owner["id"], 100.00
        ),
    )

    validate_error(response, ERR_PROTEST_PERIOD_CLOSED)


def test_adopting_the_ordinance_over_the_fiscal_deficit_tolerance_is_refused(api):
    """PRD §3.7: "The case must have an `ADOPTED` plan of services
    (`ERR_PLAN_NOT_ADOPTED`) and a `FINALIZED` fiscal impact analysis
    (`ERR_FISCAL_ANALYSIS_NOT_FINALIZED`), that analysis's `deficit_ratio_pct`
    must be no greater than the municipality's `fiscal_deficit_tolerance_pct` —
    equality is tolerated, anything above it is refused with
    `ERR_FISCAL_DEFICIT_EXCEEDS_TOLERANCE` — and the case's `method` must still
    appear in the statute's `authorized_methods`
    (`ERR_METHOD_NOT_AUTHORIZED_BY_STATUTE`)."

    Design: Corner/validations/hearing_lifecycle_enforces_its_temporal_and_fiscal_gates_in_order
    """
    # A 100,000,000-cent territory earns 1,000,000 cents of property tax and
    # 2,400,000 cents of shared revenue for 200 projected residents, while the
    # average-cost service projection plus overhead costs 4,480,000 cents: a
    # 1,080,000-cent deficit, 31.76% of gross revenue against a 5.00%
    # tolerance. Every other adoption gate is already satisfied.
    ctx = fixtures.setup_case_ready_for_ordinance(
        api,
        statute=_statute(),
        parcel_values_cents=[40000000, 30000000, 20000000, 10000000],
        projected_population=200,
    )
    assert ctx["analysis"]["status"] == "FINALIZED"

    response = api.adopt_ordinance(fixtures.clerk(ctx), ctx["case"]["id"])

    validate_error(response, ERR_FISCAL_DEFICIT_EXCEEDS_TOLERANCE)


# ==========================================================================
# Fiscal and commitment writes
# ==========================================================================
def test_authoring_an_analysis_under_an_unmandated_methodology_is_refused(api):
    """PRD §3.4: "The declared `analysis_method` must equal the statute's
    mandated `fiscal_method`; a mismatch is refused with
    `ERR_FISCAL_METHOD_NOT_AUTHORIZED`."

    Design: Corner/validations/fiscal_and_commitment_writes_reject_wrong_method_repeat_and_over_long_windows
    """
    # The statute mandates AVERAGE_COST by default.
    ctx = fixtures.setup_certified_case(api, statute=_statute())
    payload = factories.fiscal_analysis_payload(
        ctx["case"]["id"],
        fixtures.case_version(api, ctx),
        analysis_method="MARGINAL_COST",
        projected_population=5,
        marginal_police_cost_cents=100000,
    )

    response = api.create_fiscal_impact_analysis(ctx["analyst_headers"], payload)

    validate_error(response, ERR_FISCAL_METHOD_NOT_AUTHORIZED)


def test_finalizing_an_analysis_a_second_time_is_refused(api):
    """PRD §3.4: "Finalizing it is the analyst's separate act: it requires the
    analysis to still be `DRAFT` (otherwise `ERR_ANALYSIS_STATE_INVALID`),
    requires the owning case to be outside `EFFECTIVE`, `DENIED`,
    `MSD_ALTERNATIVE_ADOPTED` and `DE_ANNEXED`, and requires that no other
    analysis of the case is already `FINALIZED`."

    Design: Corner/validations/fiscal_and_commitment_writes_reject_wrong_method_repeat_and_over_long_windows
    """
    ctx = fixtures.setup_certified_case(api, statute=_statute())
    fixtures.setup_finalized_analysis(api, ctx)

    response = api.finalize_fiscal_impact_analysis(
        ctx["analyst_headers"], ctx["analysis"]["id"]
    )

    validate_error(response, ERR_ANALYSIS_STATE_INVALID)


def test_committing_a_service_the_provider_does_not_offer_is_refused(api):
    """PRD §3.5: "The committed `service_type` must be a member of the
    provider's `service_types`, or the request is refused with
    `ERR_PROVIDER_SERVICE_TYPE_MISMATCH`, and the provider must belong to the
    case's municipality, or `ERR_PARCEL_CASE_MISMATCH` is returned."

    Design: Corner/validations/fiscal_and_commitment_writes_reject_wrong_method_repeat_and_over_long_windows
    """
    ctx = fixtures.setup_certified_case(
        api,
        statute=_statute(required_service_types=["POLICE"]),
        provider={"service_types": ["POLICE"], "concurrent_project_capacity": 1},
    )
    fixtures.open_plan(api, ctx)
    payload = factories.service_commitment_payload(
        ctx["plan"]["id"],
        ctx["provider"]["id"],
        "FIRE",
        fixtures.plan_version(api, ctx),
    )

    response = api.create_service_commitment(fixtures.planner(ctx), payload)

    validate_error(response, ERR_PROVIDER_SERVICE_TYPE_MISMATCH)


def test_activating_a_window_longer_than_the_statutory_ceiling_is_refused(api):
    """PRD §3.5: "The commitment must be in `DRAFT` (otherwise
    `ERR_COMMITMENT_STATE_INVALID`), its `service_type` must still be one the
    provider offers (`ERR_PROVIDER_SERVICE_TYPE_MISMATCH`), and its
    `timeline_days` must not exceed the statutory ceiling for its service type
    — `police_fire_timeline_max_days` for `POLICE` and `FIRE`,
    `water_sewer_timeline_max_days` for `WATER` and `SEWER` — with a longer
    window refused as `ERR_PLAN_SERVICE_TIMELINE_EXCEEDS_STATUTE`."

    Design: Corner/validations/fiscal_and_commitment_writes_reject_wrong_method_repeat_and_over_long_windows
    """
    ctx = fixtures.setup_certified_case(
        api,
        statute=_statute(required_service_types=["POLICE"]),
        provider={"service_types": ["POLICE"], "concurrent_project_capacity": 1},
    )
    fixtures.open_plan(api, ctx)
    # 62 inclusive days of police extension against the statutory 60-day cap:
    # the ceiling is tested at activation, not at draft time.
    commitment = get_success_data(
        api.create_service_commitment(
            fixtures.planner(ctx),
            factories.service_commitment_payload(
                ctx["plan"]["id"],
                ctx["provider"]["id"],
                "POLICE",
                fixtures.plan_version(api, ctx),
                window_start_date="2026-08-01",
                window_end_date="2026-10-01",
                cost_cents=500000,
                committed_account_count=0,
            ),
        ),
        201,
    )
    assert commitment["timeline_days"] == assertions.inclusive_day_count(
        "2026-08-01", "2026-10-01"
    )

    response = api.activate_service_commitment(
        fixtures.planner(ctx), commitment["id"]
    )

    validate_error(response, ERR_PLAN_SERVICE_TIMELINE_EXCEEDS_STATUTE)
    assert (
        fixtures.read_commitment(
            api, ctx["municipality"]["id"], commitment["id"]
        )["commitment_status"]
        == "DRAFT"
    )


# ==========================================================================
# The closing acts, each admissible once
# ==========================================================================
def test_submitting_a_case_the_commission_need_not_review_is_refused(api):
    """PRD §3.7: "The case must be in `ORDINANCE_ADOPTED` or
    `REFERENDUM_APPROVED`, the statute's `boundary_commission_required` must be
    true, and `commission_review_status` must be `PENDING` — otherwise
    `ERR_COMMISSION_REVIEW_NOT_PENDING`."

    Design: Corner/validations/tax_roll_posting_and_commission_submission_are_not_repeatable
    """
    # The statute leaves `boundary_commission_required` false, so the adopted
    # case carries NOT_REQUIRED and the review flag, not the status, is the
    # gate.
    ctx = fixtures.setup_case_ordinance_adopted(api, statute=_statute())
    assert ctx["case"]["status"] == "ORDINANCE_ADOPTED"
    assert ctx["case"]["commission_review_status"] == "NOT_REQUIRED"

    response = api.submit_to_commission(fixtures.planner(ctx), ctx["case"]["id"])

    validate_error(response, ERR_COMMISSION_REVIEW_NOT_PENDING)


def test_posting_the_tax_roll_a_second_time_is_refused(api):
    """PRD §3.8: "The assessor posts the roll once the case is `EFFECTIVE` and
    `tax_roll_status` is still `NOT_TRANSFERRED`; a second attempt draws
    `ERR_TAX_ROLL_ALREADY_POSTED`, and posting before the case is effective
    draws `ERR_CASE_STATE_INVALID`."

    Design: Corner/validations/tax_roll_posting_and_commission_submission_are_not_repeatable
    """
    ctx = fixtures.setup_posted_tax_roll(api, statute=_statute())
    assert ctx["case"]["tax_roll_status"] == "POSTED"

    response = api.post_tax_roll(ctx["assessor_headers"], ctx["case"]["id"])

    validate_error(response, ERR_TAX_ROLL_ALREADY_POSTED)


def test_effectuating_an_already_effective_case_is_refused(api):
    """PRD §3.8: "Effectuation is the planner's act of making the boundary
    change real on a stated date, and it is admissible from three origin states
    — `ORDINANCE_ADOPTED`, `REFERENDUM_APPROVED` and `COMMISSION_APPROVED` —
    each advancing to `EFFECTIVE` with the identical preconditions and the
    identical cascade." PRD §2.10 reports, ahead of every later check, that
    "the case's `status` is a declared origin state for the requested
    transition (`ERR_CASE_STATE_INVALID`)".

    Design: Corner/validations/tax_roll_posting_and_commission_submission_are_not_repeatable
    """
    ctx = fixtures.setup_effective_case(api, statute=_statute())
    assert ctx["case"]["status"] == "EFFECTIVE"

    response = api.effectuate(
        fixtures.planner(ctx), ctx["case"]["id"], ctx["case"]["effective_date"]
    )

    validate_error(response, ERR_CASE_STATE_INVALID)
