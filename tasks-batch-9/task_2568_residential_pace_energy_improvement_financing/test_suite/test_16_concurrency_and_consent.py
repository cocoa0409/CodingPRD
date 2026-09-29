"""Optimistic concurrency, the lazy consent sweep, and read-your-own-write.

Three of these tests exercise the same shape from §2.7 on three different parents: a token
that was valid when it was read, a write that landed in between, and a refusal that must
consume nothing.  The other two cover the two program behaviours that are deliberately
lazy rather than scheduled: the deemed-consent sweep that only runs inside approval, and
the derived figures that must already be present in the response that computed them.
"""

from test_helpers import assertions as A
from test_helpers import factories, fixtures
from test_helpers.api_errors import (
    ERR_APPLICATION_VERSION_CONFLICT,
    ERR_ASSESSMENT_VERSION_CONFLICT,
    ERR_LENDER_CONSENT_PENDING,
)
from test_helpers.constants import COUNTY_MIAMI_DADE, COUNTY_SAN_DIEGO
from test_helpers.test_users import (
    COMPLIANCE_OFFICER,
    COUNTY_OFFICER,
    PROGRAM_ADMIN,
    UNDERWRITING_ANALYST,
)

# The 30-day consent clock started at the pinned signing instant, so the deadline itself
# lands at midnight on 2026-09-11 and the instant before it is still one second early.
CONSENT_DEADLINE_AT = "2026-09-11T00:00:00Z"
ONE_SECOND_EARLY_CLOCK = "2026-09-10T23:59:59Z"
ROLL_RUN_CLOCK = "2027-12-01T00:00:00Z"

# Payoff of the solar-only assessment as of the roll-run instant: 3084500 of principal,
# 468 days of actual/365 interest from 2026-08-20, the flat 7500 fee, and a base inside
# the 200-basis-point premium tier.
PAYOFF_PRINCIPAL_CENTS = 3084500
PAYOFF_TOTAL_CENTS = 3476562


def _free_and_clear_parcel(client):
    """Clock, catalog, contractor and a parcel carrying no mortgage at all."""
    fixtures.move_clock(client, fixtures.SIGNING_CLOCK)
    world = {"clock": fixtures.SIGNING_CLOCK}
    world.update(fixtures.seed_catalog(client))
    world.update(fixtures.seed_enrolled_contractor(client))
    world.update(fixtures.seed_parcel(client, with_senior_lien=False))
    return world


def test_the_second_addition_derived_from_one_read_is_refused_and_consumes_nothing(client):
    """One read of a DRAFT application cannot fund two measure additions.

    The first addition bumps the version, so the second — quoting the token both were
    derived from — is stale: "If any writer has advanced that version since the client last
    read the application — a previous measure addition by the same client, a submit, a cure,
    an underwrite, an approve or an agreement issue — the addition is rejected with
    `ERR_APPLICATION_VERSION_CONFLICT` (HTTP 412), no project measure is created, and
    `requested_principal_cents` is unchanged."  The refusal is purely about the token:
    "Concurrency is checked before any business rule, so a stale writer never learns whether
    its business intent was otherwise valid."  Re-reading makes the identical body land,
    because "Because every accepted addition increments the application's `version`, a client
    deriving two additions from one read must re-read between them: the second addition
    quoting the original version is stale and fails."

    Design: Corner/cross_cutting/two_measures_derived_from_one_read_collide_on_the_application_version
    """
    world = _free_and_clear_parcel(client)
    application = A.expect_created(
        client.open_application(
            factories.application_payload(
                world["property_id"], world["contractor_id"], 20
            ),
            world["owner_headers"],
        )
    )
    opening_version = application["version"]

    accepted = A.expect_created(
        client.add_measure(
            application["id"],
            factories.solar_measure_payload(world["solar_product_id"], opening_version),
            world["owner_headers"],
        )
    )
    stale = A.expect_error(
        client.add_measure(
            application["id"],
            factories.hvac_measure_payload(world["hvac_product_id"], opening_version),
            world["owner_headers"],
        ),
        ERR_APPLICATION_VERSION_CONFLICT,
    )
    assert stale["message"]

    surviving, surviving_meta = A.expect_page(
        client.list_measures(world["owner_headers"], {"application_id": application["id"]})
    )
    A.assert_total_count(surviving_meta, 1)
    assert surviving[0]["id"] == accepted["id"]

    mid = A.expect_ok(client.get_application(application["id"], world["owner_headers"]))
    A.assert_fields(mid, status="DRAFT", requested_principal_cents=0)
    assert mid["version"] != opening_version
    A.assert_fields(
        A.expect_ok(client.get_product(world["hvac_product_id"], PROGRAM_ADMIN)),
        status="ACTIVE",
    )

    retried = A.expect_created(
        client.add_measure(
            application["id"],
            factories.hvac_measure_payload(world["hvac_product_id"], mid["version"]),
            world["owner_headers"],
        )
    )
    assert retried["id"] != accepted["id"]
    submitted = A.expect_ok(
        client.submit_application(application["id"], world["owner_headers"])
    )
    A.assert_fields(
        submitted, status="UNDER_REVIEW", requested_principal_cents=4200000
    )
    assert submitted["version"] not in (opening_version, mid["version"])


def test_the_agreement_token_read_before_underwriting_prices_nothing(client):
    """A version captured at application creation is three writes behind by approval time.

    "If a measure added during an intervening cure round, or any other accepted write, has
    advanced that version since the analyst read the approved application, the agreement is
    not created, no fee is computed, and the request is rejected with
    `ERR_APPLICATION_VERSION_CONFLICT` (HTTP 412)."  The accepted issue is itself a write:
    "A successful issue itself increments the application's `version`, so replaying the same
    `expected_application_version` afterwards fails."

    Design: Corner/cross_cutting/agreement_issued_against_the_version_read_before_underwriting
    """
    world = _free_and_clear_parcel(client)
    application = A.expect_created(
        client.open_application(
            factories.application_payload(
                world["property_id"], world["contractor_id"], 20
            ),
            world["owner_headers"],
        )
    )
    creation_version = application["version"]
    A.expect_created(
        client.add_measure(
            application["id"],
            factories.solar_measure_payload(world["solar_product_id"], creation_version),
            world["owner_headers"],
        )
    )
    A.expect_ok(client.submit_application(application["id"], world["owner_headers"]))
    A.expect_ok(
        client.underwrite_application(
            application["id"],
            factories.underwrite_proceed_payload(),
            UNDERWRITING_ANALYST,
        )
    )
    approved = A.expect_ok(
        client.approve_application(application["id"], COMPLIANCE_OFFICER)
    )
    A.assert_fields(approved, status="APPROVED", requested_principal_cents=3000000)

    stale = A.expect_error(
        client.issue_agreement(
            factories.agreement_payload(application["id"], creation_version),
            UNDERWRITING_ANALYST,
        ),
        ERR_APPLICATION_VERSION_CONFLICT,
    )
    assert stale["message"]
    _none, empty_meta = A.expect_page(
        client.list_application_agreements(application["id"], UNDERWRITING_ANALYST)
    )
    A.assert_total_count(empty_meta, 0)
    A.assert_fields(
        A.expect_ok(client.get_application(application["id"], UNDERWRITING_ANALYST)),
        status="APPROVED",
    )
    A.assert_parcel_exposure(
        A.expect_ok(client.get_property(world["property_id"], PROGRAM_ADMIN)), 0, 0
    )

    agreement = A.expect_created(
        client.issue_agreement(
            factories.agreement_payload(application["id"], approved["version"]),
            UNDERWRITING_ANALYST,
        )
    )
    A.assert_fields(agreement, status="ISSUED", term_years=20, apr_bps=800)
    A.assert_fee_decomposition(agreement, 3000000)
    assert agreement["financed_amount_cents"] == 3084500

    after_issue = A.expect_ok(
        client.get_application(application["id"], UNDERWRITING_ANALYST)
    )
    A.assert_fields(after_issue, status="APPROVED")
    assert after_issue["version"] != approved["version"]

    replayed = A.expect_error(
        client.issue_agreement(
            factories.agreement_payload(application["id"], approved["version"]),
            UNDERWRITING_ANALYST,
        ),
        ERR_APPLICATION_VERSION_CONFLICT,
    )
    assert replayed["message"]
    _rows, one_meta = A.expect_page(
        client.list_application_agreements(application["id"], UNDERWRITING_ANALYST)
    )
    A.assert_total_count(one_meta, 1)


def test_the_payoff_computed_before_the_roll_run_cancels_nothing(client):
    """The roll run bumps the assessment between the officer's read and the prepayment.

    "Every accepted prepayment, installment payment and roll-run mutation increments the
    assessment's `version`."  The amount is exactly right, so only the token can explain the
    refusal: "If an installment payment or a roll-run mutation has reduced
    `principal_balance_cents` and advanced the version since the officer computed the payoff,
    the prepayment is rejected with `ERR_ASSESSMENT_VERSION_CONFLICT` (HTTP 412),
    `principal_balance_cents` is unchanged, and no installment is cancelled."  Re-quoted
    against the current version the same figure lands: "On success `principal_balance_cents`
    is set to 0, `billing_status` moves to `PAID_OFF`, `lien_status` moves to `RELEASED`,
    every installment still `SCHEDULED` moves to `CANCELLED`, the parcel's
    `recorded_pace_principal_cents` falls by the retired balance, and the assessment's
    `version` is incremented."

    Design: Corner/cross_cutting/prepayment_quoting_the_version_read_before_the_roll_run
    """
    world = fixtures.assessed_project(client, fixtures.solar_only_project(client), 2027)
    assessment_id = world["assessment_id"]
    before_run = A.expect_ok(client.get_assessment(assessment_id, COUNTY_OFFICER))
    A.assert_fields(
        before_run,
        principal_balance_cents=PAYOFF_PRINCIPAL_CENTS,
        interest_accrual_from="2026-08-20",
        billing_status="PENDING_ROLL",
        lien_status="SENIOR_RECORDED",
        apr_bps=800,
        term_years=20,
    )
    read_version = before_run["version"]

    fixtures.move_clock(client, ROLL_RUN_CLOCK)
    A.assert_fields(
        A.expect_ok(
            client.run_county_roll(
                "06073", factories.roll_run_payload(2027, "2027-12-01"), COUNTY_OFFICER
            )
        ),
        billed_installment_count=1,
    )

    stale = A.expect_error(
        client.prepay_assessment(
            assessment_id,
            factories.prepayment_payload(PAYOFF_TOTAL_CENTS, read_version),
            COUNTY_OFFICER,
        ),
        ERR_ASSESSMENT_VERSION_CONFLICT,
    )
    assert stale["message"]

    mid = A.expect_ok(client.get_assessment(assessment_id, COUNTY_OFFICER))
    A.assert_fields(
        mid,
        principal_balance_cents=PAYOFF_PRINCIPAL_CENTS,
        billing_status="ON_ROLL",
        lien_status="SENIOR_RECORDED",
    )
    assert mid["version"] != read_version
    _nothing, no_cancels = A.expect_page(
        client.list_installments(
            assessment_id, COUNTY_OFFICER, {"status": "CANCELLED", "limit": 100}
        )
    )
    A.assert_total_count(no_cancels, 0)

    retired = A.expect_ok(
        client.prepay_assessment(
            assessment_id,
            factories.prepayment_payload(PAYOFF_TOTAL_CENTS, mid["version"]),
            COUNTY_OFFICER,
        )
    )
    A.assert_fields(
        retired,
        principal_balance_cents=0,
        billing_status="PAID_OFF",
        lien_status="RELEASED",
    )
    _cancelled, cancelled_meta = A.expect_page(
        client.list_installments(
            assessment_id, COUNTY_OFFICER, {"status": "CANCELLED", "limit": 100}
        )
    )
    A.assert_total_count(cancelled_meta, 19)
    billed_rows, billed_meta = A.expect_page(
        client.list_installments(assessment_id, COUNTY_OFFICER, {"tax_year": 2027})
    )
    A.assert_total_count(billed_meta, 1)
    A.assert_fields(billed_rows[0], status="BILLED", billed_on="2027-12-01")
    A.assert_parcel_exposure(fixtures.read_property(client, world), 0, 0)


def _notified_application(client, catalog, contractor, parcel):
    """Open, price and underwrite a solar-only application, notifying the parcel's lien."""
    application = A.expect_created(
        client.open_application(
            factories.application_payload(
                parcel["property_id"], contractor["contractor_id"], 20
            ),
            parcel["owner_headers"],
        )
    )
    A.expect_created(
        client.add_measure(
            application["id"],
            factories.solar_measure_payload(
                catalog["solar_product_id"], application["version"]
            ),
            parcel["owner_headers"],
        )
    )
    A.expect_ok(client.submit_application(application["id"], parcel["owner_headers"]))
    return A.expect_ok(
        client.underwrite_application(
            application["id"],
            factories.underwrite_proceed_payload(),
            UNDERWRITING_ANALYST,
        )
    )


def test_the_deemed_consent_sweep_waits_for_the_deadline_and_skips_miami_dade(client):
    """Two silent holders, one lapse instant, two different outcomes.

    "The deemed-consent sweep runs only inside compliance approval, and it moves each `ACTIVE`
    lien still standing at `PENDING` whose `consent_deadline_at` is at or before the current
    logical instant to `DEEMED_CONSENTED`, but only when the parcel's `county_code` is `06073`
    or `06037`."  Until that instant arrives the posture blocks approval, and it blocks it
    forever in Florida: "In `12086` written consent is mandatory, so silence there never
    ripens: the lien stays `PENDING` however long the officer waits."

    Design: Corner/cross_cutting/deemed_consent_only_sweeps_when_the_deadline_passes_in_an_enabled_county
    """
    fixtures.move_clock(client, fixtures.SIGNING_CLOCK)
    catalog = fixtures.seed_catalog(client)
    contractor = fixtures.seed_enrolled_contractor(
        client, counties_served=[COUNTY_SAN_DIEGO, COUNTY_MIAMI_DADE]
    )
    san_diego = fixtures.seed_parcel(client)
    miami = fixtures.seed_parcel(
        client,
        payload=factories.second_property_payload(county_code=COUNTY_MIAMI_DADE),
        lien_overrides={"holder_name": "Cascade Mutual Bank", "recorded_on": "2020-08-05"},
    )
    A.assert_fields(san_diego["lien"], consent_response="NOT_NOTIFIED", status="ACTIVE")
    A.assert_fields(miami["lien"], consent_response="NOT_NOTIFIED", status="ACTIVE")
    A.assert_fields(san_diego["property"], equity_ratio_bps=3750)

    californian = _notified_application(client, catalog, contractor, san_diego)
    floridian = _notified_application(client, catalog, contractor, miami)
    A.assert_fields(
        californian,
        status="CONSENT_PENDING",
        consent_posture="PENDING",
        notified_lien_count=1,
        underwriting_cltv_bps=7000,
        consent_deadline_at=CONSENT_DEADLINE_AT,
    )
    A.assert_fields(
        A.expect_ok(client.get_mortgage_lien(san_diego["lien_id"], COMPLIANCE_OFFICER)),
        consent_response="PENDING",
        notified_at="2026-08-12T00:00:00Z",
        consent_deadline_at=CONSENT_DEADLINE_AT,
        consent_application_id=californian["id"],
    )
    A.assert_fields(
        floridian, status="CONSENT_PENDING", consent_posture="PENDING",
        consent_deadline_at=CONSENT_DEADLINE_AT,
    )

    fixtures.move_clock(client, ONE_SECOND_EARLY_CLOCK)
    early = A.expect_error(
        client.approve_application(californian["id"], COMPLIANCE_OFFICER),
        ERR_LENDER_CONSENT_PENDING,
    )
    assert early["message"]
    A.assert_fields(
        A.expect_ok(client.get_application(californian["id"], COMPLIANCE_OFFICER)),
        status="CONSENT_PENDING",
        consent_posture="PENDING",
    )
    A.assert_absent_or_none(
        A.expect_ok(client.get_application(californian["id"], COMPLIANCE_OFFICER)),
        "approver_user_id",
    )

    fixtures.move_clock(client, CONSENT_DEADLINE_AT)
    swept = A.expect_ok(
        client.approve_application(californian["id"], COMPLIANCE_OFFICER)
    )
    A.assert_fields(
        swept,
        status="APPROVED",
        consent_posture="CLEARED",
        approver_user_id="u_comp_1",
        underwriter_user_id="u_ana_1",
        requested_principal_cents=3000000,
    )
    A.assert_fields(
        A.expect_ok(client.get_mortgage_lien(san_diego["lien_id"], COMPLIANCE_OFFICER)),
        consent_response="DEEMED_CONSENTED",
        consent_responded_at=CONSENT_DEADLINE_AT,
    )

    blocked = A.expect_error(
        client.approve_application(floridian["id"], COMPLIANCE_OFFICER),
        ERR_LENDER_CONSENT_PENDING,
    )
    assert blocked["message"]
    A.assert_fields(
        A.expect_ok(client.get_application(floridian["id"], COMPLIANCE_OFFICER)),
        status="CONSENT_PENDING",
        consent_posture="PENDING",
    )
    unswept = A.expect_ok(
        client.get_mortgage_lien(miami["lien_id"], COMPLIANCE_OFFICER)
    )
    A.assert_fields(unswept, consent_response="PENDING")
    A.assert_absent_or_none(unswept, "consent_responded_at")
    A.assert_parcel_exposure(
        A.expect_ok(client.get_property(miami["property_id"], PROGRAM_ADMIN)), 0, 0
    )


def test_every_write_response_already_carries_the_figures_it_computed(client):
    """No write leaves a derived field for a later read to settle.

    The measure additions themselves are honest about being unpriced — "An accepted measure is
    stored with `status` `PROPOSED`, with `pv_savings_cents` and `sir_bps` both at 0 until the
    next submit or cure recomputes them, and with the parent application's `version`
    incremented by one." — and the submit that prices them returns the priced application:
    "`requested_principal_cents` is set to the sum of `installed_cost_cents` over the
    `PROPOSED` measures, and the combined lien-to-value ratio is computed on the assessed basis
    and stored as `screening_cltv_bps`."  The underwrite response is equally self-sufficient:
    "**Second**, `requested_principal_cents` is recomputed as the sum of `installed_cost_cents`
    over the approved subset alone." and "**Third**, `portfolio_sir_bps` is recomputed over that
    same approved subset."

    Design: Corner/consistency_model/every_derived_field_is_readable_in_the_same_response_that_wrote_it
    """
    world = _free_and_clear_parcel(client)
    water_product = A.expect_created(
        client.create_product(factories.water_product_payload(), PROGRAM_ADMIN)
    )
    application = A.expect_created(
        client.open_application(
            factories.application_payload(
                world["property_id"], world["contractor_id"], 20
            ),
            world["owner_headers"],
        )
    )
    solar = A.expect_created(
        client.add_measure(
            application["id"],
            factories.solar_measure_payload(
                world["solar_product_id"], application["version"]
            ),
            world["owner_headers"],
        )
    )
    A.assert_fields(solar, status="PROPOSED", pv_savings_cents=0, sir_bps=0)
    after_solar = A.expect_ok(
        client.get_application(application["id"], world["owner_headers"])
    )
    water = A.expect_created(
        client.add_measure(
            application["id"],
            factories.measure_payload(
                water_product["id"], after_solar["version"], 500000, 58000
            ),
            world["owner_headers"],
        )
    )
    A.assert_fields(water, status="PROPOSED", pv_savings_cents=0, sir_bps=0)

    submitted = A.expect_ok(
        client.submit_application(application["id"], world["owner_headers"])
    )
    A.assert_fields(
        submitted,
        status="UNDER_REVIEW",
        requested_principal_cents=3500000,
        portfolio_sir_bps=12359,
        min_measure_sir_bps=9895,
        weighted_useful_life_years=22,
        screening_cltv_bps=875,
    )
    A.assert_fields(
        fixtures.read_measure(client, solar["id"]),
        pv_savings_cents=3830892,
        sir_bps=12770,
    )
    A.assert_fields(
        fixtures.read_measure(client, water["id"]),
        pv_savings_cents=494752,
        sir_bps=9895,
    )

    underwritten = A.expect_ok(
        client.underwrite_application(
            application["id"],
            factories.underwrite_proceed_payload(),
            UNDERWRITING_ANALYST,
        )
    )
    A.assert_fields(
        underwritten,
        status="CONSENT_PENDING",
        requested_principal_cents=3000000,
        portfolio_sir_bps=12770,
        underwriting_cltv_bps=750,
        valuation_basis="ASSESSED",
        consent_posture="CLEARED",
    )

    ineligible, ineligible_meta = A.expect_page(
        client.list_measures(
            UNDERWRITING_ANALYST,
            {"application_id": application["id"], "status": "INELIGIBLE"},
        )
    )
    A.assert_total_count(ineligible_meta, 1)
    assert ineligible[0]["id"] == water["id"]
    A.assert_fields(fixtures.read_measure(client, solar["id"]), status="APPROVED")

    reread = A.expect_ok(
        client.get_application(application["id"], UNDERWRITING_ANALYST)
    )
    A.assert_fields(
        reread,
        requested_principal_cents=underwritten["requested_principal_cents"],
        portfolio_sir_bps=underwritten["portfolio_sir_bps"],
        status=underwritten["status"],
    )
    parcel = A.expect_ok(client.get_property(world["property_id"], PROGRAM_ADMIN))
    A.assert_parcel_exposure(parcel, 0, 0)
    A.assert_fields(parcel, equity_ratio_bps=10000)
