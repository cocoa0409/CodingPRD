"""Error-identity corners: the incumbent radius restriction, the inclusive
fair-market-value floor, and the single malformed-request code.

Every ladder is rebuilt inside each test, because the harness restarts the
service against an empty store before each one.
"""
from test_helpers import (
    COMPLIANCE_OFFICER,
    LEASING_AGENT,
    PORTFOLIO_ADMIN,
    ApiErrorId,
    assert_certified_band,
    assert_money_equals,
    assert_project_rollups,
    assert_total_count,
    ids_of,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as tf
from test_helpers import fixtures as fx


def _drive_to_certified(api, lease, tenant):
    """File the signed lease, take the deal through review and certify it."""
    lease_id = lease["id"]
    current = fx.file_attestation(api, lease_id, "SIGNED_LEASE")
    if tenant.get("is_physician_owned"):
        fx.qualified_appraisal_for(api, lease_id, current["version"])
    fx.submit_for_review(api, lease_id)
    return fx.certify(api, lease_id)


def test_an_incumbent_radius_restriction_blocks_a_same_specialty_entrant_at_execution(api):
    """The radius conflict keys on specialty identity, not on any exclusive being held.

    "A radius-restriction conflict is the mirror-image concern from the incumbent's side: it exists when some other lease in the building, again in `EXECUTED`, `ACTIVE` or `HOLDOVER`, belongs to a tenant of the **same** `primary_specialty` and carries a non-null `radius_restriction_miles`, and the refusal is `ERR_RADIUS_RESTRICTION_CONFLICT`."
    "24. No other lease in the building whose status is `EXECUTED`, `ACTIVE` or `HOLDOVER` shares this lease's tenant's `primary_specialty` while carrying a non-null `radius_restriction_miles` — otherwise `ERR_RADIUS_RESTRICTION_CONFLICT` (409). This guards `POST /leases/{id}/execute` and `POST /leases/{id}/commence`."
    "An exclusive-use conflict exists when some **other** lease in the same building, in status `EXECUTED`, `ACTIVE` or `HOLDOVER`, holds an `exclusive_use_specialty` equal to the entering tenant's `primary_specialty`; the refusal is `ERR_EXCLUSIVE_USE_CONFLICT`."
    "Two use-restriction inputs are optional: `exclusive_use_specialty` names the specialty this lease claims exclusivity over inside the building and is null when no exclusive is granted, and `radius_restriction_miles` is a non-negative 2-decimal figure that defaults to 0, where 0 disables the restriction."
    "There must be no exclusive-use conflict, no radius-restriction conflict and no suite term conflict."
    "It accepts an optional `execution_note` and moves a certified lease `FMV_CERTIFIED → EXECUTED`."
    "Suite occupancy is never set directly by any client-facing operation."
    "Leases can be listed and narrowed by `building_id`, `suite_id`, `tenant_id`, `master_lease_id`, `status` and `lease_type`; the `master_lease_id` filter is how the subleases hanging under a hospital master lease are discovered."

    Design: Corner/errors/radius_restriction_blocks_a_same_specialty_entrant_at_execute
    """
    ctx = fx.active_lease(
        api,
        tenant_overrides={"legal_name": "Harborview Cardiology PC",
                          "primary_specialty": "CARDIOLOGY"},
        lease_overrides={"term_end": "2031-08-31", "radius_restriction_miles": 3.00})
    incumbent = fx.read_lease(api, ctx["lease"]["id"])
    assert incumbent["status"] == "ACTIVE", (
        "the incumbent must be ACTIVE, got {}".format(incumbent["status"]))
    assert incumbent["exclusive_use_specialty"] is None, (
        "the incumbent holds no exclusive, got {}".format(incumbent["exclusive_use_specialty"]))

    entrant_a = fx.add_lease_on_new_suite(
        api, ctx,
        tenant_overrides={"legal_name": "Summit Heart Specialists PC",
                          "primary_specialty": "CARDIOLOGY"},
        lease_overrides={"term_start": "2026-10-01", "term_end": "2029-09-30"})
    certified_a = _drive_to_certified(api, entrant_a["lease"], entrant_a["tenant"])
    assert certified_a["status"] == "FMV_CERTIFIED", (
        "entrant A must reach FMV_CERTIFIED, got {}".format(certified_a["status"]))

    entrant_b = fx.add_lease_on_new_suite(
        api, ctx,
        tenant_overrides={"legal_name": "Granite Orthopedics PC",
                          "primary_specialty": "ORTHOPEDICS"},
        lease_overrides={"term_start": "2026-10-01", "term_end": "2029-09-30"})
    certified_b = _drive_to_certified(api, entrant_b["lease"], entrant_b["tenant"])
    assert certified_b["status"] == "FMV_CERTIFIED", (
        "entrant B must reach FMV_CERTIFIED, got {}".format(certified_b["status"]))

    refused = api.execute_lease(entrant_a["lease"]["id"],
                                {"execution_note": "Competing cardiology practice"},
                                LEASING_AGENT)
    validate_error(refused, ApiErrorId.ERR_RADIUS_RESTRICTION_CONFLICT)
    blocked = fx.read_lease(api, entrant_a["lease"]["id"])
    assert blocked["status"] == "FMV_CERTIFIED", (
        "the blocked entrant stays FMV_CERTIFIED, got {}".format(blocked["status"]))
    assert blocked["version"] == certified_a["version"], (
        "a refused execution must not advance the lease version")

    executed = validate_success(api.execute_lease(
        entrant_b["lease"]["id"],
        {"execution_note": "Non-competing orthopedics practice"}, LEASING_AGENT), 200)
    assert executed["status"] == "EXECUTED", (
        "a different specialty is unaffected, got {}".format(executed["status"]))

    suite_a = fx.read_suite(api, entrant_a["suite"]["id"])
    assert suite_a["occupancy_status"] == "VACANT", (
        "the refused execution reserved nothing, got {}".format(suite_a["occupancy_status"]))
    suite_b = fx.read_suite(api, entrant_b["suite"]["id"])
    assert suite_b["occupancy_status"] == "RESERVED", (
        "the admitted execution reserves its suite, got {}".format(suite_b["occupancy_status"]))

    rows, meta = validate_paginated(api.list_leases(
        LEASING_AGENT, {"building_id": ctx["building"]["id"], "status": "EXECUTED"}))
    assert_total_count(meta, 1)
    assert ids_of(rows) == [entrant_b["lease"]["id"]], (
        "only the orthopedics entrant reads EXECUTED")


def test_rent_one_cent_below_the_published_floor_is_refused_at_certification(api):
    """The published floor is inclusive: 23.99 is refused where 24.00 certifies.

    "43. At certification, `base_rent_psf_annual` is not below the band's `certified_fmv_floor_psf` — otherwise `ERR_RENT_BELOW_FMV_FLOOR` (422), guarding `POST /leases/{id}/certify-fmv`."
    "Start from the published figure: take the building's `market_base_rent_psf_annual` and add the class premium of the demised suite, which is 0.00 for a `STANDARD_EXAM` suite, 6.50 for an `IMAGING` suite, 4.25 for a `PROCEDURE` suite and 3.00 for an `INFUSION` suite."
    "The published floor is 80% of that figure and the published ceiling is 115% of it, each rounded half up to 2 decimal places."
    "For a tenant whose `is_physician_owned` is false, that published pair **is** the band: `certified_fmv_floor_psf` is the published floor and `certified_fmv_ceiling_psf` is the published ceiling, and no appraisal is consulted."
    "It moves the lease `PENDING_FMV_REVIEW → FMV_CERTIFIED` and demands five conditions: the building must not read `FROZEN`; the acting `X-User-ID` must differ from the lease's `fmv_submitted_by_user_id`, or the request is refused with `ERR_SEGREGATION_OF_DUTIES`; a physician-owned tenant must have a qualifying appraisal, or `ERR_NO_QUALIFYING_APPRAISAL`; the negotiated `base_rent_psf_annual` must not exceed `certified_fmv_ceiling_psf`, because rent above fair market value paid by a referral source is impermissible remuneration, or `ERR_RENT_ABOVE_FMV_CEILING`; and it must not fall below `certified_fmv_floor_psf`, because rent below fair market value granted to a referral source is equally impermissible, or `ERR_RENT_BELOW_FMV_FLOOR`."
    "On success the lease records the band into `certified_fmv_floor_psf` and `certified_fmv_ceiling_psf`, sets `fmv_certification_status` to `CERTIFIED`, marks the selected controlling appraisal with `is_controlling` true while clearing that flag to false on every other appraisal of the same lease, recomputes `certified_base_rent_annual`, `effective_base_rent_annual`, `fmv_variance_annual` and `fmv_variance_pct` under the certified variant, and advances `version` by 1."
    "Before certification — that is, while `fmv_certification_status` reads `NOT_STARTED`, `PENDING` or `STALE` — the lease is carried at the rate card: `provisional_base_rent_annual` is the published per-square-foot figure (market rate card plus the suite class premium) multiplied by the suite's `rentable_sf`, rounded half up to 2 decimal places; `effective_base_rent_annual`, the figure actually billed, equals it; and `certified_base_rent_annual`, `fmv_variance_annual` and `fmv_variance_pct` are all null."
    "Once `fmv_certification_status` reads `CERTIFIED`, the lease is carried at the negotiated rate: `certified_base_rent_annual` is `base_rent_psf_annual` multiplied by the suite's `rentable_sf`, rounded half up to 2 decimal places, and `effective_base_rent_annual` equals it — except while the lease is in `HOLDOVER`, where the effective figure is the certified figure multiplied by 1.50 and rounded half up to 2 decimal places."

    Design: Corner/errors/rent_below_the_published_floor_is_refused_at_certification
    """
    ctx = fx.leasing_baseline(api, tenant_overrides={
        "legal_name": "Northgate Medical Group PC",
        "primary_specialty": "GASTROENTEROLOGY",
        "is_physician_owned": False,
    })
    building_id = ctx["building"]["id"]
    tenant_id = ctx["tenant"]["id"]
    suite_b = fx.register_suite(api, building_id, suite_number="220")

    lease_a = fx.draft_lease(api, building_id, ctx["suite"]["id"], tenant_id,
                             base_rent_psf_annual=23.99)
    fx.submit_for_review(api, lease_a["id"], "Below-market submission")
    lease_b = fx.draft_lease(api, building_id, suite_b["id"], tenant_id,
                             base_rent_psf_annual=24.00)
    fx.submit_for_review(api, lease_b["id"], "At-floor submission")

    refused = api.certify_fmv(lease_a["id"],
                              {"certification_note": "One cent below the published floor"},
                              COMPLIANCE_OFFICER)
    validate_error(refused, ApiErrorId.ERR_RENT_BELOW_FMV_FLOOR)
    still_in_review = fx.read_lease(api, lease_a["id"])
    assert still_in_review["status"] == "PENDING_FMV_REVIEW", (
        "the refused lease stays PENDING_FMV_REVIEW, got {}".format(
            still_in_review["status"]))
    assert still_in_review["certified_fmv_floor_psf"] is None, (
        "certified_fmv_floor_psf must still be null, got {}".format(
            still_in_review["certified_fmv_floor_psf"]))
    assert still_in_review["certified_fmv_ceiling_psf"] is None, (
        "certified_fmv_ceiling_psf must still be null, got {}".format(
            still_in_review["certified_fmv_ceiling_psf"]))
    assert still_in_review["certified_base_rent_annual"] is None, (
        "certified_base_rent_annual must still be null, got {}".format(
            still_in_review["certified_base_rent_annual"]))

    certified = validate_success(api.certify_fmv(
        lease_b["id"], {"certification_note": "Exactly at the published floor"},
        COMPLIANCE_OFFICER), 200)
    assert certified["status"] == "FMV_CERTIFIED", (
        "rent exactly at the floor certifies, got {}".format(certified["status"]))
    assert certified["fmv_certification_status"] == "CERTIFIED", (
        "expected fmv_certification_status CERTIFIED, got {}".format(
            certified["fmv_certification_status"]))
    assert_certified_band(certified, 24.00, 34.50)
    assert_money_equals(certified["certified_base_rent_annual"], 120000.00,
                        "certified_base_rent_annual")
    assert_money_equals(certified["effective_base_rent_annual"], 120000.00,
                        "effective_base_rent_annual")


def test_malformed_bodies_and_a_backwards_clock_all_read_the_same_invalid_request(api):
    """Five unrelated body defects and a reversed clock collapse to one code, persisting nothing.

    "3. The body and query string parse; every required input field is present and non-null; every enum-typed value is a declared member of its enumeration; every money field is a non-negative decimal with at most 2 decimal places; every date is a valid ISO-8601 value; `period_end` is on or after `period_start`; `term_end` is strictly later than `term_start`; `window_end` is strictly later than `window_start`; `opinion_high_psf` is at least `opinion_low_psf`; `stall_count` is at least 1; `occupant_count` is at least 1; `landlord_share_pct` and `landlord_share_pct_override` both lie between 0.0000 and 1.0000 inclusive; a clock value is not earlier than the current logical clock; and a `payment_amount` is exactly the invoice's outstanding balance. Any failure is `ERR_INVALID_REQUEST` (400). Applies to every endpoint."
    "Money supplied on a request may not be negative and may not carry more than 2 decimal places; a violation is `ERR_INVALID_REQUEST`."
    "The clock may only move forward: a value earlier than the clock's current reading is rejected with `ERR_INVALID_REQUEST`."
    "It keeps a logical clock whose value, before any client has set it, is exactly `2026-08-01T00:00:00Z`; the implementation must never fall back to real time."
    "A line whose landlord share would drive `allowance_remaining` below zero is refused with `ERR_TI_ALLOWANCE_EXCEEDED`."
    "Leases can be listed and narrowed by `building_id`, `suite_id`, `tenant_id`, `master_lease_id`, `status` and `lease_type`; the `master_lease_id` filter is how the subleases hanging under a hospital master lease are discovered."

    Design: Corner/errors/money_precision_ordering_and_clock_monotonicity_are_all_invalid_request
    """
    ctx = fx.drafted_lease(api, lease_overrides={"term_start": "2026-11-01",
                                                 "term_end": "2029-10-31"})
    building_id = ctx["building"]["id"]
    suite_id = ctx["suite"]["id"]
    tenant_id = ctx["tenant"]["id"]
    project = fx.open_ti_project(api, ctx["lease"]["id"], suite_id,
                                 target_suite_class="PROCEDURE",
                                 power_amps_requested=120,
                                 medical_gas_requested=False,
                                 authorized_allowance_total=100000.00,
                                 landlord_share_pct=0.60)

    validate_error(api.create_lease(tf.create_lease_payload(
        building_id, suite_id, tenant_id, term_start="2027-01-01", term_end="2030-12-31",
        base_rent_psf_annual=30.001), LEASING_AGENT), ApiErrorId.ERR_INVALID_REQUEST)

    validate_error(api.create_lease(tf.create_lease_payload(
        building_id, suite_id, tenant_id, term_start="2027-01-01", term_end="2030-12-31",
        base_rent_psf_annual=-30.00), LEASING_AGENT), ApiErrorId.ERR_INVALID_REQUEST)

    validate_error(api.create_lease(tf.create_lease_payload(
        building_id, suite_id, tenant_id, term_start="2030-12-31", term_end="2027-01-01",
        base_rent_psf_annual=30.00), LEASING_AGENT), ApiErrorId.ERR_INVALID_REQUEST)

    validate_error(api.create_ti_line_item(project["id"], tf.create_ti_line_item_payload(
        project["version"], description="Over-range share override", category="FINISHES",
        cost_amount=10000.00, landlord_share_pct_override=1.50), LEASING_AGENT),
        ApiErrorId.ERR_INVALID_REQUEST)

    validate_error(api.set_clock("2026-07-01T00:00:00Z", PORTFOLIO_ADMIN),
                   ApiErrorId.ERR_INVALID_REQUEST)

    untouched = fx.read_project(api, project["id"])
    assert_project_rollups(untouched, 0.00, 0.00, 100000.00, 0)
    assert untouched["version"] == project["version"], (
        "a refused line item must not advance the project version")

    rows, meta = validate_paginated(api.list_leases(LEASING_AGENT,
                                                    {"building_id": building_id}))
    assert_total_count(meta, 1)
    assert ids_of(rows) == [ctx["lease"]["id"]], (
        "none of the malformed drafts may be persisted")
