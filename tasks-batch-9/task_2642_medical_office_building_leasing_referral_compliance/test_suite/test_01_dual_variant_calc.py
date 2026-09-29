"""The two rent variants on a lease and the two risk-score variants on a tenant."""
from test_helpers import (
    assert_money_equals,
    assert_share_equals,
    validate_paginated,
)
from test_helpers import fixtures as fx
from test_helpers.test_users import COMPLIANCE_OFFICER, PROPERTY_MANAGER


def _certified_physician_owned_lease(api, base_rent_psf_annual=32.00,
                                     opinion_low_psf=30.00, opinion_high_psf=34.00,
                                     suite_overrides=None, rentable_sf=5000):
    """A physician-owned tenant's lease driven to FMV_CERTIFIED on one qualified opinion."""
    suite_payload = {"rentable_sf": rentable_sf}
    suite_payload.update(suite_overrides or {})
    ctx = fx.leasing_baseline(
        api,
        suite_overrides=suite_payload,
        tenant_overrides={"legal_name": "Lakeside Orthopedic Group",
                          "primary_specialty": "ORTHOPEDICS",
                          "is_physician_owned": True},
    )
    ctx["lease"] = fx.draft_lease(api, ctx["building"]["id"], ctx["suite"]["id"],
                                  ctx["tenant"]["id"],
                                  base_rent_psf_annual=base_rent_psf_annual)
    ctx["appraisal"] = fx.qualified_appraisal_for(
        api, ctx["lease"]["id"], ctx["lease"]["version"],
        opinion_low_psf=opinion_low_psf, opinion_high_psf=opinion_high_psf)
    fx.submit_for_review(api, ctx["lease"]["id"])
    ctx["lease"] = fx.certify(api, ctx["lease"]["id"])
    return ctx


def test_provisional_and_certified_rent_variants_both_survive_on_the_certified_lease(api):
    """A certified lease carries the rate-card figure and the negotiated figure at once.

    PRD: "Once `fmv_certification_status` reads `CERTIFIED`, the lease is carried at the
    negotiated rate: `certified_base_rent_annual` is `base_rent_psf_annual` multiplied by
    the suite's `rentable_sf`, rounded half up to 2 decimal places, and
    `effective_base_rent_annual` equals it"

    Design: Difficulty/dual_variant_calc/lease_rent_provisional_published_versus_certified_appraisal_divergence
    """
    ctx = _certified_physician_owned_lease(api)
    lease = ctx["lease"]

    assert lease["status"] == "FMV_CERTIFIED"
    assert lease["fmv_certification_status"] == "CERTIFIED"
    # A 5000 sf STANDARD_EXAM suite in a building published at 30.00 psf carries no
    # class premium, so the rate card values the space at 150000.00 a year while the
    # negotiated 32.00 psf values it at 160000.00.
    assert_money_equals(lease["provisional_base_rent_annual"], 150000.00,
                        "provisional_base_rent_annual")
    assert_money_equals(lease["certified_base_rent_annual"], 160000.00,
                        "certified_base_rent_annual")
    assert_money_equals(lease["effective_base_rent_annual"], 160000.00,
                        "effective_base_rent_annual")
    # The controlling opinion of 30.00/34.00 has a midpoint of 32.00, so its band is
    # [28.80, 35.20]; the clamp against the published [24.00, 34.50] keeps the
    # appraisal floor and the published ceiling.
    assert_money_equals(lease["certified_fmv_floor_psf"], 28.80, "certified_fmv_floor_psf")
    assert_money_equals(lease["certified_fmv_ceiling_psf"], 34.50, "certified_fmv_ceiling_psf")


def test_fmv_variance_is_the_signed_delta_between_the_two_rounded_annual_figures(api):
    """The reconciling delta and its percentage are taken between the rounded figures.

    PRD: "The reconciling delta is `fmv_variance_annual`, the certified annual figure less
    the provisional annual figure, and `fmv_variance_pct` is that delta divided by the
    provisional annual figure, rounded half up to 4 decimal places and signed, so a rent
    negotiated below the rate card produces a negative percentage."

    Design: Difficulty/dual_variant_calc/lease_rent_provisional_published_versus_certified_appraisal_divergence
    """
    ctx = _certified_physician_owned_lease(api)
    lease = fx.read_lease(api, ctx["lease"]["id"], COMPLIANCE_OFFICER)

    assert_money_equals(lease["fmv_variance_annual"], 10000.00, "fmv_variance_annual")
    # 10000.00 / 150000.00 is 0.066666..., which rounds half up to four places.
    assert_share_equals(lease["fmv_variance_pct"], 0.0667, "fmv_variance_pct")
    # 0.0667 is not strictly greater than 0.1500, so no deviation case is opened.
    _rows, meta = validate_paginated(
        api.list_tenant_compliance_cases(ctx["tenant"]["id"], COMPLIANCE_OFFICER,
                                         {"case_type": "FMV_DEVIATION"}))
    assert meta["total_count"] == 0, "a variance inside the threshold opens no case"


def _delinquent_tenant(api):
    """A physician-owned tenant whose only September invoice is flagged 63 days late."""
    ctx = _certified_physician_owned_lease(api)
    lease_id = ctx["lease"]["id"]
    fx.file_attestation(api, lease_id, "SIGNED_LEASE")
    fx.execute(api, lease_id)
    fx.set_clock_date(api, "2026-09-01")
    fx.commence(api, lease_id)
    ctx["invoice"] = fx.issue_invoice(api, lease_id, "2026-09-01", "2026-09-30", "2026-09-05")
    # 2026-11-07 is 63 whole days after the 2026-09-05 due date.
    fx.set_clock_date(api, "2026-11-07")
    fx.run_daily_close(api)
    return ctx


def test_rolling_and_strict_scores_agree_at_the_first_delinquency_flag(api):
    """A single tier-50 event lands identically in both score variants on the day it is flagged.

    PRD: "`strict_cumulative_risk_score` is the **audit** figure: it sums the weights of
    every qualifying event of that tenant with no date window at all and applies no cap,
    which is the number an external reviewer reconstructs from the ledger."

    Design: Difficulty/dual_variant_calc/tenant_risk_rolling_window_versus_strict_cumulative_divergence
    """
    ctx = _delinquent_tenant(api)

    invoices, _meta = validate_paginated(
        api.list_lease_rent_invoices(ctx["lease"]["id"], PROPERTY_MANAGER))
    invoice = invoices[0]
    assert invoice["status"] == "DELINQUENT"
    assert invoice["days_past_due_at_flag"] == 63
    assert invoice["delinquency_tier_weight"] == 50

    tenant = fx.read_tenant(api, ctx["tenant"]["id"], COMPLIANCE_OFFICER)
    assert tenant["delinquency_event_count"] == 1
    assert tenant["referral_compliance_risk_score"] == 50
    assert tenant["strict_cumulative_risk_score"] == 50
    assert tenant["compliance_watch_status"] == "WATCH"


def test_rolling_window_ages_the_event_out_while_the_strict_score_retains_it(api):
    """Advancing the clock past a year separates the two variants with no new data.

    PRD: "An event whose `due_date` has aged past a year leaves the rolling figure entirely
    while remaining in the strict figure forever, so merely advancing the clock and running
    a close separates the two without any new data arriving."

    Design: Difficulty/dual_variant_calc/tenant_risk_rolling_window_versus_strict_cumulative_divergence
    """
    ctx = _delinquent_tenant(api)

    # The rolling variant considers only events whose due_date falls on or after the
    # clock date minus 365 days; on 2027-11-01 that lower bound is 2026-11-01, which
    # the 2026-09-05 due date no longer satisfies.
    fx.set_clock_date(api, "2027-11-01")
    fx.run_daily_close(api)

    tenant = fx.read_tenant(api, ctx["tenant"]["id"], COMPLIANCE_OFFICER)
    assert tenant["referral_compliance_risk_score"] == 0
    assert tenant["strict_cumulative_risk_score"] == 50
    assert tenant["delinquency_event_count"] == 1
    # The tenant stays on watch because the cascade's rent-delinquency case is open.
    assert tenant["compliance_watch_status"] == "WATCH"

    invoices, _meta = validate_paginated(
        api.list_lease_rent_invoices(ctx["lease"]["id"], PROPERTY_MANAGER))
    invoice = invoices[0]
    assert invoice["days_past_due_at_flag"] == 63, "the frozen flag is never revised"
    assert invoice["delinquency_tier_weight"] == 50
