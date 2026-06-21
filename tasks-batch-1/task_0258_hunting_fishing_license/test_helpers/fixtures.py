"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures produce clear
"Setup failed" errors instead of confusing assertion failures.

Identity threading: the Applicant role is entity_backed, so any ownership-gated call made
on behalf of an applicant uses make_applicant_headers(applicant["id"]) — never the shared
TEST_USERS["applicant_headers"] constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_applicant_payload,
    create_residency_verification_payload,
    create_education_certificate_payload,
    create_license_product_payload,
    create_species_season_payload,
    create_draw_pool_payload,
    create_draw_application_payload,
    create_license_payload,
    create_harvest_report_payload,
    create_replacement_payload,
)
from .test_users import TEST_USERS, make_applicant_headers

OFFICER = TEST_USERS["draw_officer_headers"]
AGENT = TEST_USERS["license_agent_headers"]
WARDEN = TEST_USERS["game_warden_headers"]


# ─── Clock control ────────────────────────────────────────────────────────
def set_clock(iso: str):
    """Set the server logical clock (PRD §2.9). DrawOfficer-only."""
    return get_success_data(api_client.set_clock(iso, OFFICER))


# ─── Tier 1: Applicants with established standing ──────────────────────────
def create_applicant(full_name="Test Applicant", birth_date="1980-01-01",
                     declared_state_code="MT", **overrides):
    """Register a fresh applicant. Returns the Applicant resource."""
    payload = create_applicant_payload(
        full_name=full_name, birth_date=birth_date,
        declared_state_code=declared_state_code, **overrides)
    return get_success_data(api_client.create_applicant(payload, OFFICER))


def create_resident_applicant(full_name="A Res", birth_date="1980-01-01",
                              declared_state_code="MT"):
    """Applicant whose residency is APPROVED RESIDENT (proof state matches declared,
    continuous_months >= 12). Returns the Applicant resource."""
    applicant = create_applicant(full_name=full_name, birth_date=birth_date,
                                 declared_state_code=declared_state_code)
    rv = get_success_data(api_client.create_residency_verification(
        create_residency_verification_payload(
            applicant["id"], proof_type="DRIVERS_LICENSE",
            proof_state_code=declared_state_code, continuous_months=24),
        OFFICER))
    get_success_data(api_client.approve_residency_verification(rv["id"], OFFICER))
    return get_success_data(api_client.get_applicant(applicant["id"], OFFICER))


def create_nonresident_applicant(full_name="A NR", birth_date="1980-01-01",
                                 declared_state_code="CA"):
    """Applicant whose residency is APPROVED NONRESIDENT (proof state differs from declared
    and/or insufficient months). Returns the Applicant resource."""
    applicant = create_applicant(full_name=full_name, birth_date=birth_date,
                                 declared_state_code=declared_state_code)
    rv = get_success_data(api_client.create_residency_verification(
        create_residency_verification_payload(
            applicant["id"], proof_type="UTILITY_BILL",
            proof_state_code="OR", continuous_months=1),
        OFFICER))
    get_success_data(api_client.approve_residency_verification(rv["id"], OFFICER))
    return get_success_data(api_client.get_applicant(applicant["id"], OFFICER))


def create_educated_applicant(full_name="A Edu", birth_date="1980-01-01",
                              declared_state_code="MT"):
    """Applicant with a VERIFIED education certificate (education_certified == true)."""
    applicant = create_applicant(full_name=full_name, birth_date=birth_date,
                                 declared_state_code=declared_state_code)
    ec = get_success_data(api_client.create_education_certificate(
        create_education_certificate_payload(applicant["id"]), OFFICER))
    get_success_data(api_client.verify_education_certificate(ec["id"], OFFICER))
    return get_success_data(api_client.get_applicant(applicant["id"], OFFICER))


# ─── Tier 1: Catalog & season setup ─────────────────────────────────────────
def create_product(sku="PROD-1", product_kind="STAMP", base_fee_cents=4500,
                   residency_restriction="ANY", **overrides):
    """Create an ACTIVE LicenseProduct. Returns the LicenseProduct resource."""
    payload = create_license_product_payload(
        sku=sku, product_kind=product_kind, base_fee_cents=base_fee_cents,
        residency_restriction=residency_restriction, **overrides)
    return get_success_data(api_client.create_license_product(payload, OFFICER))


def create_season(species="ELK", season_open="2026-09-01T00:00:00Z",
                  season_close="2026-10-01T00:00:00Z", bag_limit=1,
                  draw_required=False, open_it=True):
    """Create a SpeciesSeason; optionally walk DRAFT -> OPEN. Returns the SpeciesSeason."""
    season = get_success_data(api_client.create_species_season(
        create_species_season_payload(
            species=species, season_open=season_open, season_close=season_close,
            bag_limit=bag_limit, draw_required=draw_required),
        OFFICER))
    if open_it:
        season = get_success_data(api_client.open_species_season(season["id"], OFFICER))
    return season


def create_tag_product_for_season(season_id, sku="TAG-ELK", base_fee_cents=4500,
                                  residency_restriction="ANY", **overrides):
    """Create an ACTIVE TAG product bound to the given season."""
    return create_product(sku=sku, product_kind="TAG", base_fee_cents=base_fee_cents,
                          species_season_id=season_id,
                          residency_restriction=residency_restriction, **overrides)


# ─── Tier 2/3: OTC license + harvest setup ──────────────────────────────────
def issue_otc_license(applicant_id, product_id, as_role=AGENT):
    """Issue an over-the-counter License. Returns the License resource."""
    return get_success_data(api_client.create_license(
        create_license_payload(applicant_id, product_id), as_role))


def setup_resident_with_tag_license(season_open="2026-09-01T00:00:00Z",
                                    season_close="2026-10-01T00:00:00Z",
                                    bag_limit=2, clock="2026-09-15T00:00:00Z",
                                    base_fee_cents=4500, sku="TAG-ELK-OTC"):
    """Clock set; OPEN draw_required-false season; ACTIVE TAG product; resident applicant
    holding an ISSUED OTC TAG license.

    Returns (season, product, applicant, license).
    """
    set_clock(clock)
    season = create_season(season_open=season_open, season_close=season_close,
                           bag_limit=bag_limit, draw_required=False, open_it=True)
    product = create_tag_product_for_season(season["id"], sku=sku,
                                            base_fee_cents=base_fee_cents)
    applicant = create_resident_applicant()
    license_ = issue_otc_license(applicant["id"], product["id"])
    return season, product, applicant, license_


def submit_harvest(license_id, applicant_id, harvest_datetime="2026-09-15T08:00:00Z",
                   quantity=1):
    """Submit a harvest report under a license, acting as the owning applicant.
    Returns the HarvestReport resource."""
    return get_success_data(api_client.create_harvest_report(
        create_harvest_report_payload(license_id, harvest_datetime=harvest_datetime,
                                      quantity=quantity),
        make_applicant_headers(applicant_id)))


# ─── Tier 4: Draw pools and preference-point accrual ───────────────────────
def create_pool(season_id, product_id, quota=1, entry_deadline="2026-03-10T00:00:00Z",
                scoring_model="SQUARED"):
    """Create an ACCEPTING DrawPool. Returns the DrawPool resource."""
    return get_success_data(api_client.create_draw_pool(
        create_draw_pool_payload(season_id, product_id, quota=quota,
                                 entry_deadline=entry_deadline,
                                 scoring_model=scoring_model),
        OFFICER))


def enter_draw(pool_id, applicant_id, as_officer=True):
    """Enter an applicant into a pool. Returns the DrawApplication resource.
    By default acts as DrawOfficer (administrative entry); pass as_officer=False to act
    as the owning applicant."""
    headers = OFFICER if as_officer else make_applicant_headers(applicant_id)
    return get_success_data(api_client.create_draw_application(
        create_draw_application_payload(pool_id, applicant_id), headers))


def close_pool(pool_id, deadline_passed_clock):
    """Advance clock past the deadline, then close pool entries.
    Returns the closed DrawPool resource (carrying the post-close version)."""
    set_clock(deadline_passed_clock)
    return get_success_data(api_client.close_entries_draw_pool(pool_id, OFFICER))


def execute_pool_draw(pool_id, expected_version):
    """Execute a draw on a CLOSED pool. Returns the DRAWN DrawPool resource."""
    return get_success_data(api_client.execute_draw(
        pool_id, {"expected_draw_pool_version": expected_version}, OFFICER))


def run_one_losing_draw(season_id, product_id, loser_id, winner_bonus_points,
                        deadline, deadline_passed_clock, scoring_model="SQUARED",
                        winner_name="Winner"):
    """Create a quota-1 pool, enter a fresh high-bonus winner plus `loser_id`, close and
    execute the draw so the loser goes UNSUCCESSFUL and gains +1 preference point.
    Returns nothing; mutates the loser applicant's preference_points.
    """
    winner = create_applicant(full_name=winner_name, bonus_points=winner_bonus_points)
    pool = create_pool(season_id, product_id, quota=1, entry_deadline=deadline,
                       scoring_model=scoring_model)
    enter_draw(pool["id"], winner["id"])
    enter_draw(pool["id"], loser_id)
    closed = close_pool(pool["id"], deadline_passed_clock)
    execute_pool_draw(pool["id"], closed["version"])


def setup_closed_pool_ready_to_draw(clock="2026-03-01T00:00:00Z",
                                    entry_deadline="2026-03-10T00:00:00Z",
                                    deadline_passed_clock="2026-03-11T00:00:00Z",
                                    quota=1, num_entrants=1, draw_required=True,
                                    scoring_model="SQUARED"):
    """Full setup to a CLOSED pool ready for execute-draw against an OPEN season.

    Clock set; OPEN draw_required season; ACTIVE TAG product; pool with `num_entrants`
    fresh applicants (all pp0/b0); clock advanced past deadline; pool CLOSED.

    Returns (season, product, pool, applicants, closed_pool) where closed_pool carries
    the version observed at close time.
    """
    set_clock(clock)
    season = create_season(bag_limit=1, draw_required=draw_required, open_it=True)
    product = create_tag_product_for_season(season["id"])
    pool = create_pool(season["id"], product["id"], quota=quota,
                       entry_deadline=entry_deadline, scoring_model=scoring_model)
    applicants = []
    for i in range(num_entrants):
        a = create_applicant(full_name=f"A{i + 1}")
        enter_draw(pool["id"], a["id"])
        applicants.append(a)
    closed = close_pool(pool["id"], deadline_passed_clock)
    return season, product, pool, applicants, closed
