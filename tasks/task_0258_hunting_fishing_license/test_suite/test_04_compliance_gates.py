"""Over-the-counter issuance compliance gates: the fixed precedence of the draw-only,
education, minimum-age, and residency checks (PRD §3.7), plus the minimum-age boundary.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_resident_applicant, create_nonresident_applicant,
    create_product, create_season, create_tag_product_for_season,
    issue_otc_license, set_clock, create_license_payload, TEST_USERS,
)

AGENT = TEST_USERS["license_agent_headers"]
OFFICER = TEST_USERS["draw_officer_headers"]


def test_draw_required_beats_education_required(api):
    """PRD §3.7: "First, the draw-only rule: a `TAG` product bound to a season whose
    `draw_required` is true may not be sold over the counter at all and is rejected with
    `ERR_DRAW_REQUIRED`".
    PRD §3.7: "Second, the education prerequisite: if the product's `requires_education` is true
    and the applicant's `education_certified` is not true, the issuance is rejected with
    `ERR_EDUCATION_REQUIRED`."

    Design: Difficulty/priority_pair_validation_conflict/draw_required_beats_education_required
    """
    set_clock("2026-02-01T00:00:00Z")
    season = create_season(species="ELK", bag_limit=1, draw_required=True, open_it=True)
    product = create_tag_product_for_season(season["id"], sku="TAG-ELK-EDU",
                                            base_fee_cents=4500, requires_education=True)
    # Resident applicant with NO education certificate.
    applicant = create_resident_applicant(full_name="A Res", declared_state_code="MT")

    res = api.create_license(
        create_license_payload(applicant["id"], product["id"]), AGENT)
    validate_error(res, "ERR_DRAW_REQUIRED", expected_status=409)


def test_education_required_beats_residency_restricted(api):
    """PRD §3.7: "Second, the education prerequisite: if the product's `requires_education` is
    true and the applicant's `education_certified` is not true, the issuance is rejected with
    `ERR_EDUCATION_REQUIRED`."
    PRD §3.7: "Fourth, the residency restriction of §3.5 (`ERR_RESIDENCY_RESTRICTED`). Only
    after all four pass does pricing complete and the license get created."

    Design: Difficulty/priority_pair_validation_conflict/education_required_beats_residency_restricted
    """
    set_clock("2026-02-01T00:00:00Z")
    product = create_product(sku="LIC-HUNT", product_kind="LICENSE", base_fee_cents=4500,
                             requires_education=True, residency_restriction="RESIDENT_ONLY")
    # Nonresident applicant with no education cert: both education (prio 2) and residency
    # (prio 4) checks would fail; education must surface first.
    applicant = create_nonresident_applicant(full_name="A NR", declared_state_code="CA")

    res = api.create_license(
        create_license_payload(applicant["id"], product["id"]), AGENT)
    validate_error(res, "ERR_EDUCATION_REQUIRED", expected_status=409)


def test_draw_required_beats_education_no_license_minted(api):
    """PRD §3.7: "First, the draw-only rule: a `TAG` product bound to a season whose
    `draw_required` is true may not be sold over the counter at all and is rejected with
    `ERR_DRAW_REQUIRED` — such a tag must instead arrive carrying a draw application reference."

    Design: Difficulty/priority_pair_validation_conflict/draw_required_beats_education_required
    """
    set_clock("2026-02-01T00:00:00Z")
    season = create_season(species="ELK", bag_limit=1, draw_required=True, open_it=True)
    product = create_tag_product_for_season(season["id"], sku="TAG-ELK-EDU2",
                                            base_fee_cents=4500, requires_education=True)
    applicant = create_resident_applicant(full_name="A Res", declared_state_code="MT")

    res = api.create_license(
        create_license_payload(applicant["id"], product["id"]), AGENT)
    validate_error(res, "ERR_DRAW_REQUIRED", expected_status=409)
    # The rejected OTC issuance must not have minted a license (empty DB at test start).
    _, meta = validate_paginated(api.list_licenses(OFFICER))
    assert meta["total_count"] == 0


def test_education_beats_residency_no_license_minted(api):
    """PRD §3.7: "Second, the education prerequisite: if the product's `requires_education` is
    true and the applicant's `education_certified` is not true, the issuance is rejected with
    `ERR_EDUCATION_REQUIRED`."

    Design: Difficulty/priority_pair_validation_conflict/education_required_beats_residency_restricted
    """
    set_clock("2026-02-01T00:00:00Z")
    product = create_product(sku="LIC-HUNT2", product_kind="LICENSE", base_fee_cents=4500,
                             requires_education=True, residency_restriction="RESIDENT_ONLY")
    applicant = create_nonresident_applicant(full_name="A NR", declared_state_code="CA")

    res = api.create_license(
        create_license_payload(applicant["id"], product["id"]), AGENT)
    validate_error(res, "ERR_EDUCATION_REQUIRED", expected_status=409)
    _, meta = validate_paginated(api.list_licenses(OFFICER))
    assert meta["total_count"] == 0


def test_minimum_age_at_threshold_issued(api):
    """PRD §3.7: "Third, the minimum-age rule: the applicant's age in whole years on the
    issuance date, computed from `birth_date` against the current clock, must be at least the
    product's `min_age_years`; a younger applicant is rejected with `ERR_MINIMUM_AGE`."

    Design: Difficulty/boundary_precision_check/minimum_age_boundary_below_vs_at_threshold
    """
    set_clock("2026-02-01T00:00:00Z")
    product = create_product(sku="STAMP-YOUTH", product_kind="STAMP", base_fee_cents=4500,
                             min_age_years=12, residency_restriction="ANY")
    # Born exactly 12 years before the clock (2014-02-01) -> exactly 12.
    at_applicant = _resident_with_birthdate(api, "A At", "2014-02-01")

    license_ = issue_otc_license(at_applicant["id"], product["id"])
    assert license_["status"] == "ISSUED"


def test_minimum_age_below_threshold_rejected(api):
    """PRD §3.7: "the applicant's age in whole years on the issuance date, computed from
    `birth_date` against the current clock, must be at least the product's `min_age_years`; a
    younger applicant is rejected with `ERR_MINIMUM_AGE`."

    Design: Difficulty/boundary_precision_check/minimum_age_boundary_below_vs_at_threshold
    """
    set_clock("2026-02-01T00:00:00Z")
    product = create_product(sku="STAMP-YOUTH", product_kind="STAMP", base_fee_cents=4500,
                             min_age_years=12, residency_restriction="ANY")
    # Born 2014-02-02 -> 11 years and 364 days on 2026-02-01, just under 12.
    under_applicant = _resident_with_birthdate(api, "A Under", "2014-02-02")

    res = api.create_license(
        create_license_payload(under_applicant["id"], product["id"]), AGENT)
    validate_error(res, "ERR_MINIMUM_AGE", expected_status=409)


def test_minimum_age_triggerable(api):
    """PRD §3.7: "a younger applicant is rejected with `ERR_MINIMUM_AGE`."

    Design: Corner/errors/error_minimum_age_triggerable
    """
    set_clock("2026-02-01T00:00:00Z")
    product = create_product(sku="STAMP-YOUTH2", product_kind="STAMP", base_fee_cents=4500,
                             min_age_years=18, residency_restriction="ANY")
    under_applicant = _resident_with_birthdate(api, "A Young", "2014-02-02")
    res = api.create_license(
        create_license_payload(under_applicant["id"], product["id"]), AGENT)
    validate_error(res, "ERR_MINIMUM_AGE", expected_status=409)


def test_residency_restricted_resident_only_to_nonresident(api):
    """PRD §3.5: "if the product's `residency_restriction` is `RESIDENT_ONLY` and the applicant's
    `residency_status` is not `RESIDENT`, or if the restriction is `NONRESIDENT_ONLY` and the
    applicant's `residency_status` is not `NONRESIDENT`, the issuance is rejected with
    `ERR_RESIDENCY_RESTRICTED`."

    Design: Corner/validations/residency_restricted_resident_only_to_nonresident
    """
    set_clock("2026-02-01T00:00:00Z")
    product = create_product(sku="LIC-RES", product_kind="LICENSE", base_fee_cents=4500,
                             residency_restriction="RESIDENT_ONLY")
    applicant = create_nonresident_applicant(full_name="A NR", declared_state_code="CA")

    res = api.create_license(
        create_license_payload(applicant["id"], product["id"]), AGENT)
    validate_error(res, "ERR_RESIDENCY_RESTRICTED", expected_status=409)


# ─── local helper (PRD-declared endpoints only) ───────────────────────────
def _resident_with_birthdate(api, name, birth_date):
    """Register an applicant with a specific birth_date and approve RESIDENT standing."""
    from test_helpers import (
        create_applicant_payload, create_residency_verification_payload,
    )
    applicant = validate_success(api.create_applicant(
        create_applicant_payload(full_name=name, birth_date=birth_date,
                                 declared_state_code="MT"), OFFICER), 201)
    rv = validate_success(api.create_residency_verification(
        create_residency_verification_payload(
            applicant["id"], proof_state_code="MT", continuous_months=24), OFFICER), 201)
    validate_success(api.approve_residency_verification(rv["id"], OFFICER), 200)
    return validate_success(api.get_applicant(applicant["id"], OFFICER), 200)
