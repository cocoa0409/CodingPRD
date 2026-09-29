"""Validation gates on the leasing, review, billing and booking write surfaces.

Each test drives one rule from the request-rejection ladder to its refusal and,
where the PRD names the admissible counterpart, to its acceptance in the same
scenario so the gate is proven to be conditional rather than absolute.
"""
from test_helpers import (
    COMPLIANCE_OFFICER,
    FACILITIES_ENGINEER,
    LEASING_AGENT,
    PROPERTY_MANAGER,
    ApiErrorId,
    assert_money_equals,
    assert_parking_counters,
    assert_share_equals,
    assert_total_count,
    build_user_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

# A single POWER line of scope, enough to satisfy the one-line-item precondition
# on a review submission.
_POWER_LINE = {
    "description": "Sub-panel and feeder",
    "category": "POWER",
    "cost_amount": 10000.00,
}


def _utility_project_in_review(api, building, suite, tenant):
    """A PROCEDURE build-out asking 150 amps and piped medical gas, both reviews PENDING."""
    lease = fx.draft_lease(api, building["id"], suite["id"], tenant["id"],
                           term_start="2026-11-01", term_end="2029-10-31")
    return fx.ti_project_in_review(
        api, lease["id"], suite["id"], [dict(_POWER_LINE)],
        target_suite_class="PROCEDURE", power_amps_requested=150,
        medical_gas_requested=True, authorized_allowance_total=200000.00,
        landlord_share_pct=0.60,
    )


def test_utility_review_reports_the_medical_gas_defect_before_the_amperage_shortfall(api):
    """A utility approval on a suite short of both gas and amperage reports the gas defect.

    PRD §2.8: "A lease commencing into an `IMAGING` suite requires that suite's
    `shielding_certified` to be true, and a utility review that requires piped medical
    gas requires the suite's `medical_gas_available` to be true."
    PRD §2.8: "At utility review, the suite's `power_amps_available` is at least the
    project's `power_amps_requested`, and the suite provides medical gas whenever
    `medical_gas_requested` is true — otherwise `ERR_INSUFFICIENT_UTILITY_CAPACITY` (422)."
    PRD §2.8: "When it does, the response is determined by the **first** breach in the
    ladder below and no later check is evaluated."
    PRD §3.6: "Approving the utility dimension requires the suite's `power_amps_available`
    to be at least the project's `power_amps_requested`, refused as
    `ERR_INSUFFICIENT_UTILITY_CAPACITY`, and requires the suite's `medical_gas_available`
    to be true whenever `medical_gas_requested` is true, refused as
    `ERR_SHIELDING_CERTIFICATION_MISSING`; it then sets `utility_review_status` to
    `APPROVED`, reduces the suite's `power_amps_available` by `power_amps_requested`,
    records the amount actually drawn in the project's `power_amps_drawn`, and advances
    the suite's `version`."

    Design: Corner/validations/shielding_defect_outranks_an_amperage_shortfall_at_utility_review
    """
    building = fx.register_building(api)
    suite_no_gas = fx.register_suite(api, building["id"], suite_number="300", floor=3,
                                     rentable_sf=3000, power_amps_available=100,
                                     medical_gas_available=False)
    suite_gas_low_amps = fx.register_suite(api, building["id"], suite_number="310", floor=3,
                                           rentable_sf=3000, power_amps_available=100,
                                           medical_gas_available=True)
    suite_ready = fx.register_suite(api, building["id"], suite_number="320", floor=3,
                                    rentable_sf=3000, power_amps_available=200,
                                    medical_gas_available=True)
    tenant = fx.register_tenant(api)

    project_no_gas = _utility_project_in_review(api, building, suite_no_gas, tenant)
    project_low_amps = _utility_project_in_review(api, building, suite_gas_low_amps, tenant)
    project_ready = _utility_project_in_review(api, building, suite_ready, tenant)

    payload = f.ti_review_payload("UTILITY", "APPROVE", review_note="Utility dimension")

    # Gas absent and amperage short: the medical-gas limb answers first.
    resp = api.review_ti_project(project_no_gas["id"], payload, FACILITIES_ENGINEER)
    validate_error(resp, ApiErrorId.ERR_SHIELDING_CERTIFICATION_MISSING)

    # Gas present, amperage still short.
    resp = api.review_ti_project(project_low_amps["id"], payload, FACILITIES_ENGINEER)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_UTILITY_CAPACITY)

    # Both utilities in place: the dimension approves.
    approved = validate_success(api.review_ti_project(project_ready["id"], payload,
                                                      FACILITIES_ENGINEER), 200)
    assert approved["utility_review_status"] == "APPROVED"
    assert approved["shielding_review_status"] == "PENDING"
    assert approved["status"] == "IN_REVIEW"
    assert approved["power_amps_drawn"] == 150

    for refused in (project_no_gas, project_low_amps):
        after = fx.read_project(api, refused["id"])
        assert after["status"] == "IN_REVIEW"
        assert after["utility_review_status"] == "PENDING", \
            "a refused utility review leaves the dimension PENDING"

    assert fx.read_suite(api, suite_no_gas["id"])["power_amps_available"] == 100, \
        "the refused review draws no capacity"
    assert fx.read_suite(api, suite_ready["id"])["power_amps_available"] == 50, \
        "the approved review reduces available amps by the requested amps"


def test_qualifying_appraisal_required_only_for_a_physician_owned_tenant(api):
    """Review submission needs a qualified appraisal only where the tenant is physician-owned.

    PRD §3.3: "And where the tenant's `is_physician_owned` is true, at least one appraisal
    on the lease must be `QUALIFIED` with an `expires_on` on or after the clock date,
    otherwise `ERR_NO_QUALIFYING_APPRAISAL`; a tenant that is not physician-owned needs no
    appraisal at all."
    PRD §3.3: "Submitting a draft for fair-market-value review moves it `DRAFT →
    PENDING_FMV_REVIEW` and accepts an optional `submission_note`."
    PRD §3.4: "Qualification moves an appraisal `SUBMITTED → QUALIFIED` and requires three
    things: `independence_attested` must be true, or the request is refused with
    `ERR_APPRAISAL_INDEPENDENCE_MISSING`, since a firm that has not attested independence
    cannot support an opinion of fair market value; `expires_on` must be on or after the
    clock date, so an opinion that has already aged out cannot be qualified retroactively;
    and the owning lease must not be `TERMINATED` or `WITHDRAWN`."
    PRD §3.4: "`opinion_midpoint_psf` is the mean of the two ends, rounded half up to 2
    decimal places."
    PRD §3.4: "`expires_on` is `appraisal_date` plus 365 days, expressed as a UTC date — an
    opinion of value is stale after a year."

    Design: Corner/validations/qualifying_appraisal_required_only_for_a_physician_owned_tenant
    """
    building = fx.register_building(api)
    physician_suite = fx.register_suite(api, building["id"], suite_number="210")
    other_suite = fx.register_suite(api, building["id"], suite_number="220")
    physician_tenant = fx.register_tenant(api, legal_name="Lakeside Oncology Partners LLP",
                                          primary_specialty="ONCOLOGY",
                                          is_physician_owned=True)
    plain_tenant = fx.register_tenant(api)

    physician_lease = fx.draft_lease(api, building["id"], physician_suite["id"],
                                     physician_tenant["id"])
    fx.file_attestation(api, physician_lease["id"], "SIGNED_LEASE")
    plain_lease = fx.draft_lease(api, building["id"], other_suite["id"], plain_tenant["id"])
    fx.file_attestation(api, plain_lease["id"], "SIGNED_LEASE")

    resp = api.submit_fmv_review(physician_lease["id"],
                                 {"submission_note": "No appraisal on file yet"},
                                 LEASING_AGENT)
    validate_error(resp, ApiErrorId.ERR_NO_QUALIFYING_APPRAISAL)
    assert fx.read_lease(api, physician_lease["id"])["status"] == "DRAFT"

    submitted = validate_success(
        api.submit_fmv_review(plain_lease["id"],
                              {"submission_note": "No appraisal needed"}, LEASING_AGENT), 200)
    assert submitted["status"] == "PENDING_FMV_REVIEW", \
        "the appraisal precondition is conditioned entirely on is_physician_owned"

    # An appraisal that has not attested independence cannot be qualified.
    current = fx.read_lease(api, physician_lease["id"])
    affiliate = fx.file_appraisal(api, physician_lease["id"], current["version"],
                                  appraiser_firm="Meridian Advisory Group",
                                  independence_attested=False)
    resp = api.decide_appraisal(affiliate["id"],
                                f.appraisal_decision_payload("QUALIFY", "Affiliate opinion"),
                                COMPLIANCE_OFFICER)
    validate_error(resp, ApiErrorId.ERR_APPRAISAL_INDEPENDENCE_MISSING)
    rows, _meta = validate_paginated(api.list_lease_appraisals(physician_lease["id"],
                                                               COMPLIANCE_OFFICER))
    still_submitted = [row for row in rows if row["id"] == affiliate["id"]][0]
    assert still_submitted["status"] == "SUBMITTED"

    current = fx.read_lease(api, physician_lease["id"])
    independent = fx.file_appraisal(api, physician_lease["id"], current["version"],
                                    appraiser_firm="Harbor Valuation LLC",
                                    appraisal_date="2026-07-15",
                                    opinion_low_psf=29.00, opinion_high_psf=33.00,
                                    independence_attested=True)
    qualified = validate_success(
        api.decide_appraisal(independent["id"],
                             f.appraisal_decision_payload("QUALIFY", "Independent opinion"),
                             COMPLIANCE_OFFICER), 200)
    assert qualified["status"] == "QUALIFIED"
    assert_money_equals(qualified["opinion_midpoint_psf"], 31.00, "opinion_midpoint_psf")
    assert qualified["expires_on"] == "2027-07-15"

    resubmitted = validate_success(
        api.submit_fmv_review(physician_lease["id"],
                              {"submission_note": "Qualified appraisal now on file"},
                              LEASING_AGENT), 200)
    assert resubmitted["status"] == "PENDING_FMV_REVIEW"

    _rows, meta = validate_paginated(api.list_lease_appraisals(physician_lease["id"],
                                                               COMPLIANCE_OFFICER))
    assert_total_count(meta, 2)


def test_sublease_term_must_lie_inside_the_master_term_inclusively(api):
    """A sublease may start no earlier and end no later than its master, but may match both.

    PRD §2.8: "For a `SUBLEASE`, `term_start` is on or after the master lease's `term_start`
    and `term_end` is on or before the master lease's `term_end` — otherwise
    `ERR_SUBLEASE_TERM_EXCEEDS_MASTER` (422). This guards `POST /leases`,
    `PATCH /leases/{id}` and `POST /leases/{id}/submit-fmv-review`."
    PRD §3.3: "A sublease must name a master whose `lease_type` is `MASTER`, and its term
    must sit inside the master's term — `term_start` on or after the master's `term_start`
    and `term_end` on or before the master's `term_end`, otherwise
    `ERR_SUBLEASE_TERM_EXCEEDS_MASTER`."
    PRD §3.3: "Take the difference in years between that exclusive end and `term_start` and
    multiply by 12, add the difference in their month numbers, and then, if the exclusive
    end's day of the month is earlier than `term_start`'s day of the month, subtract one
    whole month because the anniversary day has not been reached."
    PRD §3.3: "Leases can be listed and narrowed by `building_id`, `suite_id`, `tenant_id`,
    `master_lease_id`, `status` and `lease_type`; the `master_lease_id` filter is how the
    subleases hanging under a hospital master lease are discovered."

    Design: Corner/validations/sublease_term_must_lie_inside_the_master_term_inclusively
    """
    ctx = fx.leasing_baseline(api, tenant_overrides={
        "legal_name": "Cedar Health System",
        "affiliation": "HEALTH_SYSTEM_ANCHOR",
        "primary_specialty": "ORTHOPEDICS",
    })
    master = fx.draft_lease(api, ctx["building"]["id"], ctx["suite"]["id"], ctx["tenant"]["id"],
                            lease_type="MASTER", term_start="2026-09-01",
                            term_end="2031-08-31")
    master = fx.drive_to_active(api, master, ctx["tenant"])
    sub_tenant = fx.register_tenant(api, legal_name="Cedar Orthopaedic Partners PC",
                                    primary_specialty="ORTHOPEDICS")

    def sublease_payload(term_start, term_end):
        return f.create_lease_payload(ctx["building"]["id"], ctx["suite"]["id"],
                                      sub_tenant["id"], lease_type="SUBLEASE",
                                      master_lease_id=master["id"],
                                      term_start=term_start, term_end=term_end)

    # Starting one month before the master's own start.
    resp = api.create_lease(sublease_payload("2026-08-01", "2029-08-31"), LEASING_AGENT)
    validate_error(resp, ApiErrorId.ERR_SUBLEASE_TERM_EXCEEDS_MASTER)

    # Running one day past the master's last day of occupancy.
    resp = api.create_lease(sublease_payload("2026-09-01", "2031-09-01"), LEASING_AGENT)
    validate_error(resp, ApiErrorId.ERR_SUBLEASE_TERM_EXCEEDS_MASTER)

    # Exactly co-terminous with the master: both bounds are inclusive.
    sublease = validate_success(
        api.create_lease(sublease_payload("2026-09-01", "2031-08-31"), LEASING_AGENT), 201)
    assert sublease["lease_type"] == "SUBLEASE"
    assert sublease["master_lease_id"] == master["id"]
    assert sublease["status"] == "DRAFT"
    assert sublease["term_months"] == 60

    rows, meta = validate_paginated(
        api.list_leases(LEASING_AGENT, params={"master_lease_id": master["id"]}))
    assert_total_count(meta, 1)
    assert rows[0]["id"] == sublease["id"], \
        "only the admissible sublease hangs under the master"


def _invoice_by_id(api, lease_id, invoice_id):
    """Re-read one invoice off the owning lease's invoice roster."""
    rows, _meta = validate_paginated(api.list_lease_rent_invoices(lease_id, PROPERTY_MANAGER))
    return [row for row in rows if row["id"] == invoice_id][0]


def test_invoice_period_must_be_disjoint_within_term_and_ignores_written_off_periods(api):
    """An occupancy period is blocked by a live invoice and by the term, but not by a write-off.

    PRD §2.8: "The requested invoice period does not overlap an existing invoice period on
    the same lease that is not written off, and lies within the lease term unless the lease
    is in `HOLDOVER` — otherwise `ERR_INVOICE_PERIOD_OVERLAP` (409), guarding
    `POST /leases/{id}/rent-invoices`."
    PRD §3.7: "The requested period may not overlap the period of any existing invoice on
    the same lease that is not written off, and it must lie inside the lease term unless the
    lease has rolled into `HOLDOVER`; a violation is `ERR_INVOICE_PERIOD_OVERLAP`."
    PRD §3.7: "Aging is measured in whole calendar days as the clock date less `due_date`,
    and the figure is negative before the due date arrives."
    PRD §3.7: "An invoice becomes delinquent only when that day count is **strictly greater
    than** the ten-day grace period, so a count of exactly 10 leaves the invoice in `ISSUED`
    carrying no weight."
    PRD §3.7: "The weight tiers are keyed on the day count itself rather than on days past
    grace, which means the day an invoice becomes delinquent it is already worth 15 points: a
    day count of at most 30 carries a weight of 15, a count of at most 60 carries 30, and a
    count beyond 60 carries 50."
    PRD §3.7: "At the daily close on which the invoice is first flagged, the day count is
    frozen into `days_past_due_at_flag` and the corresponding weight into
    `delinquency_tier_weight`, and neither is revised on any later close even though
    `days_past_due` continues to grow."
    PRD §3.7: "On success the invoice moves `DELINQUENT → WRITTEN_OFF`, the justification
    and the acting `X-User-ID` are recorded as `write_off_justification` and
    `written_off_by_user_id`, and `delinquency_tier_weight` is **replaced** by 40 rather
    than adjusted, because forgiving rent owed by a referral source is a larger remuneration
    exposure than merely tolerating late rent."

    Design: Corner/validations/invoice_period_must_be_disjoint_inside_term_and_ignores_write_offs
    """
    ctx = fx.active_lease(api)
    lease_id = ctx["lease"]["id"]
    september = fx.issue_invoice(api, lease_id, "2026-09-01", "2026-09-30", "2026-09-05")
    assert september["status"] == "ISSUED"

    # A period that straddles the boundary of a live invoice.
    resp = api.create_rent_invoice(lease_id,
                                   f.create_rent_invoice_payload("2026-09-15", "2026-10-15",
                                                                 "2026-10-20"),
                                   PROPERTY_MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVOICE_PERIOD_OVERLAP)

    # A period entirely before the term start on a lease that has not rolled into holdover.
    resp = api.create_rent_invoice(lease_id,
                                   f.create_rent_invoice_payload("2026-08-01", "2026-08-31",
                                                                 "2026-08-05"),
                                   PROPERTY_MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVOICE_PERIOD_OVERLAP)

    october = fx.issue_invoice(api, lease_id, "2026-10-01", "2026-10-31", "2026-12-10")
    assert october["status"] == "ISSUED"

    fx.set_clock_date(api, "2026-11-07")
    fx.run_daily_close(api)
    flagged = _invoice_by_id(api, lease_id, september["id"])
    assert flagged["status"] == "DELINQUENT"
    assert flagged["days_past_due"] == 63
    assert flagged["days_past_due_at_flag"] == 63
    assert flagged["delinquency_tier_weight"] == 50
    assert _invoice_by_id(api, lease_id, october["id"])["status"] == "ISSUED", \
        "an invoice still inside grace is untouched by the close"

    # The delinquent invoice still occupies its period.
    resp = api.create_rent_invoice(lease_id,
                                   f.create_rent_invoice_payload("2026-09-01", "2026-09-30",
                                                                 "2026-12-05"),
                                   PROPERTY_MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVOICE_PERIOD_OVERLAP)

    written_off = fx.write_off_invoice(api, september["id"])
    assert written_off["status"] == "WRITTEN_OFF"
    assert written_off["delinquency_tier_weight"] == 40

    reissued = fx.issue_invoice(api, lease_id, "2026-09-01", "2026-09-30", "2026-12-15")
    assert reissued["status"] == "ISSUED", \
        "a written-off period leaves the month billable again"

    _rows, meta = validate_paginated(api.list_lease_rent_invoices(lease_id, PROPERTY_MANAGER))
    assert_total_count(meta, 3)


def test_rent_concession_lock_blocks_a_reduction_but_not_an_increase(api):
    """A concession lock refuses only a rent reduction; a rise and a term change still land.

    PRD §2.8: "The addressed lease's `rent_concession_locked` is false; a locked lease may
    not have its `base_rent_psf_annual` reduced by an amendment. A violation is
    `ERR_RENT_CONCESSION_LOCKED` (422), guarding `PATCH /leases/{id}`."
    PRD §3.3: "Separately, a lease whose `rent_concession_locked` is true may not have its
    `base_rent_psf_annual` lowered at all, and the attempt is refused with
    `ERR_RENT_CONCESSION_LOCKED`."
    PRD §3.3: "When term or rent fields change, `term_months` and the provisional rent are
    re-derived."
    PRD §3.7: "Aging is measured in whole calendar days as the clock date less `due_date`,
    and the figure is negative before the due date arrives."
    PRD §3.7: "The weight tiers are keyed on the day count itself rather than on days past
    grace, which means the day an invoice becomes delinquent it is already worth 15 points: a
    day count of at most 30 carries a weight of 15, a count of at most 60 carries 30, and a
    count beyond 60 carries 50."
    PRD §3.8: "`referral_compliance_risk_score` is the **rolling twelve-month** operational
    figure: it considers only those events whose `due_date` falls on or after the clock date
    minus 365 days, sums their weights, and then caps the result at 100."
    PRD §3.8: "`compliance_watch_status` reads `WATCH` when the rolling
    `referral_compliance_risk_score` is at least 45, or when the tenant has any compliance
    case in status `OPEN`, `REMEDIATION_PLANNED` or `REPORTED`; otherwise it reads `CLEAR`."
    PRD §3.7: "**Hop 3b** fires only when hop 3 actually raised the watch, and it is the hop
    implementers most often miss: every lease of that tenant whose status is anything other
    than `TERMINATED` or `WITHDRAWN` — drafts and certified deals very much included,
    because a pending deal is exactly where an improper concession would be granted — is
    processed in `created_at` ascending order to set `rent_concession_locked` to true, clear
    `after_hours_authorized` to false and advance that lease's `version` by 1; and on each
    of those leases, every shared-space booking still in `BOOKED` whose `window_start` is
    later than the current clock moves to `CANCELLED` with `cancellation_source` recorded as
    `COMPLIANCE_CASCADE`."

    Design: Corner/validations/rent_concession_lock_blocks_a_reduction_but_not_an_increase
    """
    ctx = fx.active_lease(api)
    tenant = ctx["tenant"]
    second_suite = fx.register_suite(api, ctx["building"]["id"], suite_number="220",
                                     rentable_sf=3000)
    draft = fx.draft_lease(api, ctx["building"]["id"], second_suite["id"], tenant["id"],
                           term_start="2027-01-01", term_end="2029-12-31")

    fx.issue_invoice(api, ctx["lease"]["id"], "2026-09-01", "2026-09-30", "2026-09-05")
    flagged = fx.flag_delinquent(api, ctx["lease"]["id"], "2026-11-07")
    assert flagged["status"] == "DELINQUENT"
    assert flagged["delinquency_tier_weight"] == 50

    on_watch = fx.read_tenant(api, tenant["id"])
    assert on_watch["compliance_watch_status"] == "WATCH"
    assert on_watch["referral_compliance_risk_score"] == 50

    locked = fx.read_lease(api, draft["id"])
    assert locked["rent_concession_locked"] is True, \
        "the cascade locks the tenant's drafts as well as its live leases"
    assert locked["after_hours_authorized"] is False
    assert fx.read_lease(api, ctx["lease"]["id"])["rent_concession_locked"] is True

    resp = api.patch_lease(draft["id"],
                           f.patch_lease_payload(locked["version"],
                                                 base_rent_psf_annual=26.00),
                           LEASING_AGENT)
    validate_error(resp, ApiErrorId.ERR_RENT_CONCESSION_LOCKED)
    unchanged = fx.read_lease(api, draft["id"])
    assert_money_equals(unchanged["base_rent_psf_annual"], 30.00, "base_rent_psf_annual")
    assert unchanged["version"] == locked["version"], "the refused amendment writes nothing"

    raised = validate_success(
        api.patch_lease(draft["id"],
                        f.patch_lease_payload(unchanged["version"],
                                              base_rent_psf_annual=32.00),
                        LEASING_AGENT), 200)
    assert_money_equals(raised["base_rent_psf_annual"], 32.00, "base_rent_psf_annual")

    extended = validate_success(
        api.patch_lease(draft["id"],
                        f.patch_lease_payload(raised["version"], term_end="2030-12-31"),
                        LEASING_AGENT), 200)
    assert extended["term_months"] == 48, "the lock does not touch the term fields"


def test_submitting_agent_identity_may_not_certify_its_own_lease(api):
    """The user id recorded at submission is barred from certifying; another officer may.

    PRD §2.8: "The acting `X-User-ID` differs from the user recorded as having taken the
    paired step — the lease's `fmv_submitted_by_user_id` on a certification, and the
    `opened_by_user_id` of any `OPEN` rent-delinquency case on the tenant on a write-off. A
    collision is `ERR_SEGREGATION_OF_DUTIES` (403). This guards
    `POST /leases/{id}/certify-fmv` and `POST /rent-invoices/{id}/write-off`."
    PRD §3.3: "On success, `fmv_certification_status` becomes `PENDING`, the acting
    `X-User-ID` is recorded as `fmv_submitted_by_user_id` — the comparand the certifier will
    be checked against — the provisional rent is recomputed and frozen at the rate card as
    it stands at that moment, and `version` advances by 1."
    PRD §3.4: "It moves the lease `PENDING_FMV_REVIEW → FMV_CERTIFIED` and demands five
    conditions: the building must not read `FROZEN`; the acting `X-User-ID` must differ from
    the lease's `fmv_submitted_by_user_id`, or the request is refused with
    `ERR_SEGREGATION_OF_DUTIES`; a physician-owned tenant must have a qualifying appraisal,
    or `ERR_NO_QUALIFYING_APPRAISAL`; the negotiated `base_rent_psf_annual` must not exceed
    `certified_fmv_ceiling_psf`, because rent above fair market value paid by a referral
    source is impermissible remuneration, or `ERR_RENT_ABOVE_FMV_CEILING`; and it must not
    fall below `certified_fmv_floor_psf`, because rent below fair market value granted to a
    referral source is equally impermissible, or `ERR_RENT_BELOW_FMV_FLOOR`."
    PRD §3.4: "For a tenant whose `is_physician_owned` is false, that published pair **is**
    the band: `certified_fmv_floor_psf` is the published floor and `certified_fmv_ceiling_psf`
    is the published ceiling, and no appraisal is consulted."

    Design: Corner/validations/the_agent_who_submitted_for_review_may_not_certify_it
    """
    ctx = fx.drafted_lease(api)
    lease_id = ctx["lease"]["id"]
    fx.file_attestation(api, lease_id, "SIGNED_LEASE")

    dual_as_agent = build_user_headers("user-dual", "LeasingAgent")
    dual_as_officer = build_user_headers("user-dual", "ComplianceOfficer")

    submitted = validate_success(
        api.submit_fmv_review(lease_id, {"submission_note": "Submitted by the dual identity"},
                              dual_as_agent), 200)
    assert submitted["status"] == "PENDING_FMV_REVIEW"
    assert submitted["fmv_certification_status"] == "PENDING"

    # The same X-User-ID, now wearing the certifying role.
    resp = api.certify_fmv(lease_id, {"certification_note": "Self-certification attempt"},
                           dual_as_officer)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    held = fx.read_lease(api, lease_id)
    assert held["status"] == "PENDING_FMV_REVIEW"
    assert held["fmv_certification_status"] == "PENDING"
    assert held["certified_fmv_ceiling_psf"] is None, \
        "the refused certification records no band"

    certified = validate_success(
        api.certify_fmv(lease_id, {"certification_note": "Certified by a second identity"},
                        COMPLIANCE_OFFICER), 200)
    assert certified["status"] == "FMV_CERTIFIED"
    assert certified["fmv_certification_status"] == "CERTIFIED"
    assert_money_equals(certified["certified_fmv_floor_psf"], 24.00,
                        "certified_fmv_floor_psf")
    assert_money_equals(certified["certified_fmv_ceiling_psf"], 34.50,
                        "certified_fmv_ceiling_psf")
    assert_money_equals(certified["certified_base_rent_annual"], 150000.00,
                        "certified_base_rent_annual")


def test_stall_pool_refuses_the_request_that_overdraws_the_remaining_pool(api):
    """Two individually admissible allocations drain the pool; the next request is refused.

    PRD §2.8: "The requested `stall_count` does not exceed the building's
    `unallocated_stalls` — otherwise `ERR_INSUFFICIENT_UNALLOCATED_STALLS` (422), guarding
    `POST /parking-allocations`."
    PRD §2.8: "Because rule 45 precedes rule 46, a stall request that both exceeds the pool
    and breaches the patient reserve reports `ERR_INSUFFICIENT_UNALLOCATED_STALLS`."
    PRD §3.10: "The pool-capacity test comes first: a requested `stall_count` greater than
    the building's current `unallocated_stalls` is refused with
    `ERR_INSUFFICIENT_UNALLOCATED_STALLS`."
    PRD §3.10: "In a 400-stall building reserving 0.60, the minimum is 240 stalls and staff
    may therefore hold at most 160: a first staff request for 160 leaves exactly 240
    non-staff stalls and is accepted, while a request for 161 would leave 239 and is refused."
    PRD §3.10: "A `PATIENT` request is never reserve-tested and is bounded only by
    `unallocated_stalls`."

    Design: Corner/validations/stall_pool_refuses_the_collective_request_not_the_individual_one
    """
    ctx = fx.active_lease(api)
    building_id = ctx["building"]["id"]
    lease_id = ctx["lease"]["id"]

    staff = fx.allocate_stalls(api, building_id, lease_id, "STAFF", 160)
    assert staff["status"] == "ACTIVE"
    patient = fx.allocate_stalls(api, building_id, lease_id, "PATIENT", 240)
    assert patient["status"] == "ACTIVE"
    assert_parking_counters(fx.read_building(api, building_id), 160, 240, 0)

    version = fx.read_building(api, building_id)["version"]

    # One more staff stall would both overdraw the pool and breach the reserve.
    resp = api.create_parking_allocation(
        f.create_parking_allocation_payload(version, building_id, lease_id, "STAFF", 1),
        PROPERTY_MANAGER)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_UNALLOCATED_STALLS)

    # A patient stall is bounded by the pool alone, and the pool is empty.
    resp = api.create_parking_allocation(
        f.create_parking_allocation_payload(version, building_id, lease_id, "PATIENT", 1),
        PROPERTY_MANAGER)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_UNALLOCATED_STALLS)

    assert_parking_counters(fx.read_building(api, building_id), 160, 240, 0)
    _rows, meta = validate_paginated(
        api.list_parking_allocations(PROPERTY_MANAGER, params={"lease_id": lease_id}))
    assert_total_count(meta, 2)


def test_sublease_execution_reports_master_status_then_consent_then_signed_lease(api):
    """Executing a sublease clears the master-status, consent and signed-lease gates in order.

    PRD §2.8: "For a `SUBLEASE`, `master_lease_id` is non-null, the lease it names has
    `lease_type` `MASTER`, and at execution time that master lease's status is `ACTIVE` —
    otherwise `ERR_MASTER_LEASE_NOT_ACTIVE` (422). This guards `POST /leases`,
    `POST /leases/{id}/submit-fmv-review` and `POST /leases/{id}/execute`."
    PRD §2.8: "For a `SUBLEASE` being executed, `master_lease_consent_on_file` is true —
    otherwise `ERR_MASTER_LEASE_CONSENT_MISSING` (422), guarding
    `POST /leases/{id}/execute`."
    PRD §2.8: "For any lease being executed, `signed_lease_on_file` is true — otherwise
    `ERR_SIGNED_LEASE_NOT_ON_FILE` (422), guarding `POST /leases/{id}/execute`."
    PRD §3.5: "A `SUBLEASE` must additionally have `master_lease_consent_on_file` true,
    refused as `ERR_MASTER_LEASE_CONSENT_MISSING`, and its master lease must be in status
    `ACTIVE` at that moment, refused as `ERR_MASTER_LEASE_NOT_ACTIVE` — a sublease cannot be
    executed under a master that has not yet commenced or has already ended."
    PRD §3.3: "An `attestation_type` of `SIGNED_LEASE` writes `on_file` to
    `signed_lease_on_file`, `MASTER_LEASE_CONSENT` writes it to
    `master_lease_consent_on_file`, and `SPACE_SHARING_SCHEDULE` writes it to
    `space_sharing_schedule_on_file`."
    PRD §2.9: "Leases of type `SUBLEASE` are deliberately excluded: the master lease already
    counts that area, and counting both would double-count the same square feet."

    Design: Corner/validations/sublease_execution_walks_three_checks_in_priority_order
    """
    building = fx.register_building(api)
    master_suite = fx.register_suite(api, building["id"], suite_number="210",
                                     rentable_sf=12000)
    sub_suite = fx.register_suite(api, building["id"], suite_number="220", rentable_sf=4000)
    anchor = fx.register_tenant(api, legal_name="Cedar Health System",
                                affiliation="HEALTH_SYSTEM_ANCHOR",
                                primary_specialty="ORTHOPEDICS")
    subtenant = fx.register_tenant(api, legal_name="Northgate Digestive Health PC")

    master = fx.draft_lease(api, building["id"], master_suite["id"], anchor["id"],
                            lease_type="MASTER")
    fx.file_attestation(api, master["id"], "SIGNED_LEASE")
    fx.submit_for_review(api, master["id"])
    fx.certify(api, master["id"])
    master = fx.execute(api, master["id"])
    assert master["status"] == "EXECUTED"

    sublease = fx.draft_lease(api, building["id"], sub_suite["id"], subtenant["id"],
                              lease_type="SUBLEASE", master_lease_id=master["id"])
    fx.submit_for_review(api, sublease["id"])
    sublease = fx.certify(api, sublease["id"])
    assert sublease["status"] == "FMV_CERTIFIED"

    execution = {"execution_note": "Sublease execution attempt"}

    # The master is only EXECUTED, so the master-status gate answers first even though
    # neither the consent nor the signed lease is on file.
    resp = api.execute_lease(sublease["id"], execution, LEASING_AGENT)
    validate_error(resp, ApiErrorId.ERR_MASTER_LEASE_NOT_ACTIVE)

    fx.set_clock_date(api, master["term_start"])
    assert fx.commence(api, master["id"])["status"] == "ACTIVE"

    resp = api.execute_lease(sublease["id"], execution, LEASING_AGENT)
    validate_error(resp, ApiErrorId.ERR_MASTER_LEASE_CONSENT_MISSING)

    consented = fx.file_attestation(api, sublease["id"], "MASTER_LEASE_CONSENT")
    assert consented["master_lease_consent_on_file"] is True
    assert consented["signed_lease_on_file"] is False

    resp = api.execute_lease(sublease["id"], execution, LEASING_AGENT)
    validate_error(resp, ApiErrorId.ERR_SIGNED_LEASE_NOT_ON_FILE)

    fx.file_attestation(api, sublease["id"], "SIGNED_LEASE")
    executed = validate_success(api.execute_lease(sublease["id"], execution, LEASING_AGENT),
                                200)
    assert executed["status"] == "EXECUTED"
    assert executed["master_lease_consent_on_file"] is True
    assert executed["signed_lease_on_file"] is True
    assert fx.read_suite(api, sub_suite["id"])["occupancy_status"] == "RESERVED"

    mix = fx.read_building(api, building["id"])
    assert mix["leased_rentable_sf"] == 12000, \
        "the executed sublease adds no counted area of its own"
    assert_share_equals(mix["anchor_share_pct"], 1.0000, "anchor_share_pct")


def test_space_sharing_schedule_required_for_waiting_room_not_infusion_bay(api):
    """A waiting-room booking needs the written schedule; an infusion-bay booking does not.

    PRD §2.8: "A booking of a `WAITING_ROOM` or `PROCEDURE_ROOM` shared space requires the
    lease's `space_sharing_schedule_on_file` to be true — otherwise
    `ERR_SPACE_SHARING_SCHEDULE_MISSING` (422), guarding `POST /shared-space-bookings`."
    PRD §3.9: "Second, a booking of a `WAITING_ROOM` or a `PROCEDURE_ROOM` requires the
    lease's `space_sharing_schedule_on_file` to be true, because shared clinical space
    between potential referral sources must be documented on a written schedule; an
    `INFUSION_BAY` carries no such requirement."
    PRD §3.9: "The booking is created in `BOOKED` and its `is_after_hours` flag is derived:
    it is true when any part of the requested window falls outside the space's operating
    window, and false only when the whole window sits inside it."
    PRD §3.3: "An `attestation_type` of `SIGNED_LEASE` writes `on_file` to
    `signed_lease_on_file`, `MASTER_LEASE_CONSENT` writes it to
    `master_lease_consent_on_file`, and `SPACE_SHARING_SCHEDULE` writes it to
    `space_sharing_schedule_on_file`."

    Design: Corner/validations/space_sharing_schedule_required_for_a_waiting_room_but_not_an_infusion_bay
    """
    ctx = fx.active_lease(api)
    lease_id = ctx["lease"]["id"]
    assert ctx["lease"]["space_sharing_schedule_on_file"] is False
    waiting_room = fx.register_shared_space(api, ctx["building"]["id"],
                                            name="Level 2 Shared Waiting Room",
                                            space_type="WAITING_ROOM", capacity_seats=20)
    infusion_bay = fx.register_shared_space(api, ctx["building"]["id"],
                                            name="Level 3 Infusion Bay",
                                            space_type="INFUSION_BAY", capacity_seats=24)

    window_start = "2026-09-10T09:00:00Z"
    window_end = "2026-09-10T11:00:00Z"

    resp = api.create_booking(
        f.create_booking_payload(waiting_room["id"], lease_id, window_start, window_end, 6),
        LEASING_AGENT)
    validate_error(resp, ApiErrorId.ERR_SPACE_SHARING_SCHEDULE_MISSING)

    infusion_booking = validate_success(api.create_booking(
        f.create_booking_payload(infusion_bay["id"], lease_id, window_start, window_end, 6),
        LEASING_AGENT), 201)
    assert infusion_booking["status"] == "BOOKED", \
        "an infusion bay carries no schedule requirement"
    assert infusion_booking["is_after_hours"] is False

    filed = fx.file_attestation(api, lease_id, "SPACE_SHARING_SCHEDULE")
    assert filed["space_sharing_schedule_on_file"] is True

    waiting_booking = validate_success(api.create_booking(
        f.create_booking_payload(waiting_room["id"], lease_id, window_start, window_end, 6),
        LEASING_AGENT), 201)
    assert waiting_booking["status"] == "BOOKED"
    assert waiting_booking["is_after_hours"] is False

    _rows, meta = validate_paginated(
        api.list_bookings(LEASING_AGENT, params={"lease_id": lease_id}))
    assert_total_count(meta, 2)


def test_compliance_watch_outranks_the_after_hours_authorization_gate(api):
    """Once the tenant is on watch, a booking reports the watch rather than the after-hours gate.

    PRD §2.8: "The tenant's `compliance_watch_status` is `CLEAR`; a tenant on
    referral-compliance watch may not receive new after-hours access or new shared-space
    bookings. A violation is `ERR_TENANT_ON_COMPLIANCE_WATCH` (422), guarding
    `POST /leases/{id}/after-hours-authorization` and `POST /shared-space-bookings`."
    PRD §2.8: "And because rule 21 sits above rules 29, 34 and 37, a booking request from a
    tenant on watch reports the watch rather than a missing schedule, an after-hours defect
    or a capacity breach."
    PRD §3.9: "Third, a booking that is after hours requires the lease's
    `after_hours_authorized` to be true, and this check runs **before** the capacity sweep —
    an unauthorised 20:00 request in a room open until 19:00 is refused on the authorization
    ground even if the room is completely empty, and even if it would also have been refused
    on capacity."
    PRD §3.9: "Granting access is refused while the tenant is on `WATCH`, which is what makes
    the revocation in §3.7 durable: the cascade clears the flag, the cure in §3.8 pointedly
    does not restore it, and the manager cannot re-grant it until the tenant's watch is
    lifted by curing every open case."
    PRD §3.7: "Aging is measured in whole calendar days as the clock date less `due_date`,
    and the figure is negative before the due date arrives."
    PRD §3.7: "The weight tiers are keyed on the day count itself rather than on days past
    grace, which means the day an invoice becomes delinquent it is already worth 15 points: a
    day count of at most 30 carries a weight of 15, a count of at most 60 carries 30, and a
    count beyond 60 carries 50."
    PRD §3.8: "`compliance_watch_status` reads `WATCH` when the rolling
    `referral_compliance_risk_score` is at least 45, or when the tenant has any compliance
    case in status `OPEN`, `REMEDIATION_PLANNED` or `REPORTED`; otherwise it reads `CLEAR`."
    PRD §3.7: "**Hop 3b** fires only when hop 3 actually raised the watch, and it is the hop
    implementers most often miss: every lease of that tenant whose status is anything other
    than `TERMINATED` or `WITHDRAWN` — drafts and certified deals very much included,
    because a pending deal is exactly where an improper concession would be granted — is
    processed in `created_at` ascending order to set `rent_concession_locked` to true, clear
    `after_hours_authorized` to false and advance that lease's `version` by 1; and on each
    of those leases, every shared-space booking still in `BOOKED` whose `window_start` is
    later than the current clock moves to `CANCELLED` with `cancellation_source` recorded as
    `COMPLIANCE_CASCADE`."

    Design: Corner/validations/compliance_watch_outranks_the_after_hours_window_check
    """
    ctx = fx.bookable_lease(api)
    lease_id = ctx["lease"]["id"]
    space_id = ctx["shared_space"]["id"]
    evening_start = "2026-12-05T20:00:00Z"
    evening_end = "2026-12-05T21:00:00Z"

    # The space closes at 19:00, so the window is after hours and unauthorized.
    resp = api.create_booking(
        f.create_booking_payload(space_id, lease_id, evening_start, evening_end, 4),
        LEASING_AGENT)
    validate_error(resp, ApiErrorId.ERR_AFTER_HOURS_NOT_AUTHORIZED)

    granted = fx.authorize_after_hours(api, lease_id, True)
    assert granted["after_hours_authorized"] is True

    booking = validate_success(api.create_booking(
        f.create_booking_payload(space_id, lease_id, evening_start, evening_end, 4),
        LEASING_AGENT), 201)
    assert booking["status"] == "BOOKED"
    assert booking["is_after_hours"] is True

    fx.issue_invoice(api, lease_id, "2026-09-01", "2026-09-30", "2026-09-05")
    flagged = fx.flag_delinquent(api, lease_id, "2026-11-07")
    assert flagged["status"] == "DELINQUENT"
    assert flagged["days_past_due"] == 63
    assert flagged["delinquency_tier_weight"] == 50

    tenant = fx.read_tenant(api, ctx["tenant"]["id"])
    assert tenant["compliance_watch_status"] == "WATCH"
    assert tenant["referral_compliance_risk_score"] == 50

    cascaded = validate_success(api.get_booking(booking["id"], LEASING_AGENT), 200)
    assert cascaded["status"] == "CANCELLED"
    assert cascaded["cancellation_source"] == "COMPLIANCE_CASCADE"
    assert fx.read_lease(api, lease_id)["after_hours_authorized"] is False

    # The replacement request breaches the watch gate and the after-hours gate at once.
    resp = api.create_booking(
        f.create_booking_payload(space_id, lease_id, "2026-12-06T20:00:00Z",
                                 "2026-12-06T21:00:00Z", 4),
        LEASING_AGENT)
    validate_error(resp, ApiErrorId.ERR_TENANT_ON_COMPLIANCE_WATCH)

    resp = api.set_after_hours_authorization(lease_id, f.after_hours_payload(True),
                                            PROPERTY_MANAGER)
    validate_error(resp, ApiErrorId.ERR_TENANT_ON_COMPLIANCE_WATCH)
