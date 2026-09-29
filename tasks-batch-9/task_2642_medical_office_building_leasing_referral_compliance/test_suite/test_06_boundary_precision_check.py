"""Two boundaries: the money-per-square-foot ceiling, and the empty qualified-appraisal set."""
from test_helpers import (
    ApiErrorId,
    assert_certified_band,
    assert_certified_rent_variant,
    assert_money_equals,
    assert_share_equals,
    validate_error,
    validate_paginated,
)
from test_helpers import fixtures as fx
from test_helpers.test_users import COMPLIANCE_OFFICER, LEASING_AGENT


def _two_leases_at_and_above_the_ceiling(api):
    """One lease priced at exactly 34.50 psf and one at 34.51, both awaiting certification."""
    ctx = fx.drafted_lease(api, lease_overrides={"base_rent_psf_annual": 34.50})
    ctx["at_ceiling"] = fx.submit_for_review(api, ctx["lease"]["id"],
                                             "Exactly at the published ceiling")
    over = fx.draft_lease(api, ctx["building"]["id"], ctx["suite"]["id"], ctx["tenant"]["id"],
                         base_rent_psf_annual=34.51)
    ctx["over_ceiling"] = fx.submit_for_review(api, over["id"],
                                               "One cent over the published ceiling")
    return ctx


def test_rent_exactly_at_the_certified_ceiling_certifies_and_opens_no_deviation_case(api):
    """34.50 psf is admitted and its variance lands on exactly 0.1500, which is not past the gate.

    PRD: "the negotiated `base_rent_psf_annual` must not exceed `certified_fmv_ceiling_psf`,
    because rent above fair market value paid by a referral source is impermissible
    remuneration, or `ERR_RENT_ABOVE_FMV_CEILING`"

    PRD: "One further consequence fires conditionally: when the **absolute value** of
    `fmv_variance_pct` is strictly greater than 0.1500, the system opens an `FMV_DEVIATION`
    compliance case against the tenant in status `OPEN`, measured under the rolling twelve-month
    variant, with `opened_by_user_id` recorded as the literal value `system`, and then
    re-evaluates that tenant's `compliance_watch_status`."

    Design: Difficulty/boundary_precision_check/rent_exactly_at_fmv_ceiling_accepted_one_cent_above_rejected
    """
    ctx = _two_leases_at_and_above_the_ceiling(api)

    certified = fx.certify(api, ctx["at_ceiling"]["id"], "34.50 == ceiling")
    assert certified["status"] == "FMV_CERTIFIED"
    assert_certified_band(certified, 24.00, 34.50)
    assert_certified_rent_variant(certified, 172500.00, 150000.00)
    assert_money_equals(certified["fmv_variance_annual"], 22500.00, "fmv_variance_annual")
    assert_share_equals(certified["fmv_variance_pct"], 0.1500, "fmv_variance_pct")

    cases, meta = validate_paginated(
        api.list_tenant_compliance_cases(ctx["tenant"]["id"], COMPLIANCE_OFFICER,
                                         params={"case_type": "FMV_DEVIATION"}))
    assert meta["total_count"] == 0
    assert cases == []


def test_rent_one_cent_above_the_certified_ceiling_is_refused(api):
    """34.51 psf breaches the same ceiling and leaves the lease in review, uncertified.

    PRD: "At certification, `base_rent_psf_annual` does not exceed the band's
    `certified_fmv_ceiling_psf` — otherwise `ERR_RENT_ABOVE_FMV_CEILING` (422), guarding
    `POST /leases/{id}/certify-fmv`."

    Design: Difficulty/boundary_precision_check/rent_exactly_at_fmv_ceiling_accepted_one_cent_above_rejected
    """
    ctx = _two_leases_at_and_above_the_ceiling(api)

    refused = api.certify_fmv(ctx["over_ceiling"]["id"],
                              {"certification_note": "34.51 > ceiling"}, COMPLIANCE_OFFICER)
    validate_error(refused, ApiErrorId.ERR_RENT_ABOVE_FMV_CEILING)

    lease = fx.read_lease(api, ctx["over_ceiling"]["id"])
    assert lease["status"] == "PENDING_FMV_REVIEW"
    assert lease["certified_base_rent_annual"] is None
    assert lease["certified_fmv_ceiling_psf"] is None


def _physician_owned_lease_with_one_undecided_appraisal(api):
    """A physician-owned tenant's draft carrying a single appraisal left in SUBMITTED."""
    ctx = fx.drafted_lease(
        api,
        tenant_overrides={"legal_name": "Riverbend Gastroenterology PA",
                          "is_physician_owned": True},
        lease_overrides={"base_rent_psf_annual": 32.00},
    )
    ctx["appraisal"] = fx.file_appraisal(
        api, ctx["lease"]["id"], ctx["lease"]["version"],
        appraiser_firm="Harbor Valuation LLC", appraisal_date="2026-07-20",
        opinion_low_psf=30.00, opinion_high_psf=34.00, independence_attested=True)
    return ctx


def test_an_empty_qualified_appraisal_set_blocks_the_review_submission(api):
    """One SUBMITTED appraisal is not a candidate, so the qualified set is empty and the ask fails.

    PRD: "For a physician-owned tenant, at least one appraisal on the lease is `QUALIFIED` with
    an `expires_on` on or after the clock date, so that a controlling opinion exists — otherwise
    `ERR_NO_QUALIFYING_APPRAISAL` (422). This guards `POST /leases/{id}/submit-fmv-review` and
    `POST /leases/{id}/certify-fmv`."

    PRD: "`opinion_midpoint_psf` is the mean of the two ends, rounded half up to 2 decimal
    places. `expires_on` is `appraisal_date` plus 365 days, expressed as a UTC date — an opinion
    of value is stale after a year. The new row begins in `SUBMITTED` with `is_controlling`
    false, `decision_reason` null, and the owning lease's `version` advances by 1 because the
    lease now has new evidence attached to it."

    Design: Difficulty/boundary_precision_check/zero_qualified_appraisals_blocks_fmv_review_submission
    """
    ctx = _physician_owned_lease_with_one_undecided_appraisal(api)
    appraisal = ctx["appraisal"]
    assert appraisal["status"] == "SUBMITTED"
    assert_money_equals(appraisal["opinion_midpoint_psf"], 32.00, "opinion_midpoint_psf")
    assert appraisal["expires_on"] == "2027-07-20"
    assert appraisal["is_controlling"] is False
    assert appraisal["decision_reason"] is None

    qualified, meta = validate_paginated(
        api.list_lease_appraisals(ctx["lease"]["id"], COMPLIANCE_OFFICER,
                                  params={"status": "QUALIFIED"}))
    assert qualified == []
    assert meta["total_count"] == 0
    assert meta["has_more"] is False

    refused = api.submit_fmv_review(
        ctx["lease"]["id"], {"submission_note": "No qualified appraisal on file"},
        LEASING_AGENT)
    validate_error(refused, ApiErrorId.ERR_NO_QUALIFYING_APPRAISAL)
    assert fx.read_lease(api, ctx["lease"]["id"])["status"] == "DRAFT"


def test_qualifying_the_single_appraisal_takes_the_candidate_count_from_zero_to_one(api):
    """The identical submission succeeds once the set is non-empty, and only then.

    PRD: "Among the appraisals of a lease, the candidates are those in status `QUALIFIED` whose
    `expires_on` is on or after the clock date. Rows in `DISQUALIFIED`, `EXPIRED` and
    `SUBMITTED` are excluded."

    PRD: "Submitting a draft for fair-market-value review moves it `DRAFT → PENDING_FMV_REVIEW`
    and accepts an optional `submission_note`."

    Design: Difficulty/boundary_precision_check/zero_qualified_appraisals_blocks_fmv_review_submission
    """
    ctx = _physician_owned_lease_with_one_undecided_appraisal(api)
    validate_error(
        api.submit_fmv_review(ctx["lease"]["id"],
                              {"submission_note": "No qualified appraisal on file"},
                              LEASING_AGENT),
        ApiErrorId.ERR_NO_QUALIFYING_APPRAISAL)

    decided = fx.qualify_appraisal(api, ctx["appraisal"]["id"],
                                   "Independence and methodology verified")
    assert decided["status"] == "QUALIFIED"
    assert decided["decision_reason"] == "Independence and methodology verified"

    qualified, meta = validate_paginated(
        api.list_lease_appraisals(ctx["lease"]["id"], COMPLIANCE_OFFICER,
                                  params={"status": "QUALIFIED"}))
    assert meta["total_count"] == 1
    assert qualified[0]["id"] == ctx["appraisal"]["id"]

    submitted = fx.submit_for_review(api, ctx["lease"]["id"], "Resubmitted after qualification")
    assert submitted["status"] == "PENDING_FMV_REVIEW"
