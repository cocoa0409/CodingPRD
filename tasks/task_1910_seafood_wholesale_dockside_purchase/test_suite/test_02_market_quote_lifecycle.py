"""Market quote lifecycle: volatility guard, publication series, expiry sweep,
optimistic concurrency on the species version, and segregation of duties."""
import pytest

from test_helpers import (
    api_client,
    ApiErrorId,
    TEST_USERS,
    OM_1_HEADERS,
    OM_2_HEADERS,
    validate_success,
    validate_error,
    get_success_data,
    create_species,
    create_draft_quote,
    publish_quote,
    get_species_version,
    set_clock,
)

OM = TEST_USERS["operations_manager_headers"]


def _get_quote(quote_id) -> dict:
    return get_success_data(api_client.get_market_quote(quote_id, OM))


class TestVolatilityGuardBoundary:
    """Two tests pinning the >= vs < boundary at exactly 10.00 percent."""

    def test_exactly_ten_percent_requires_approval_below_publishes(self, api):
        """PRD §3.2: "A change below 10.00 percent publishes outright, transitioning the quote to `PUBLISHED`. A change of at least 10.00 percent — exactly 10.00 included — routes the quote to `PENDING_APPROVAL` instead; this routing is not an error."
        PRD §3.2: "Whenever a quote reaches `PUBLISHED`, the prior `PUBLISHED` quote for the same species and grade is automatically superseded to `SUPERSEDED`."

        Design: Difficulty/boundary_precision_check/volatility_exactly_ten_percent_requires_approval
        """
        species = create_species(species_code="COD")
        q1 = publish_quote(
            create_draft_quote(species["id"], quote_date="2026-08-01",
                               price_per_kg_cents=1000)["id"])
        assert q1["status"] == "PUBLISHED"

        q2 = create_draft_quote(species["id"], quote_date="2026-08-02",
                                price_per_kg_cents=1100)
        q2_after = publish_quote(q2["id"])
        assert q2_after["status"] == "PENDING_APPROVAL", (
            "+10.00% exactly must route to PENDING_APPROVAL")
        assert q2_after["volatility_pct"] == pytest.approx(10.00), (
            f"volatility_pct must be 10.00, got {q2_after['volatility_pct']}")
        # Routing to PENDING_APPROVAL does not supersede the standing quote.
        assert _get_quote(q1["id"])["status"] == "PUBLISHED"

        q3 = create_draft_quote(species["id"], quote_date="2026-08-03",
                                price_per_kg_cents=1099)
        q3_after = publish_quote(q3["id"])
        assert q3_after["status"] == "PUBLISHED", "+9.90% must publish directly"
        assert q3_after["volatility_pct"] == pytest.approx(9.90)
        assert _get_quote(q1["id"])["status"] == "SUPERSEDED"

    def test_guard_inert_without_prior_published_quote(self, api):
        """PRD §3.2: "When no prior published quote exists for the species and grade, the guard is inert: the quote publishes directly and `volatility_pct` remains zero."

        Design: Difficulty/boundary_precision_check/volatility_exactly_ten_percent_requires_approval
        """
        species = create_species(species_code="COD")
        quote = publish_quote(
            create_draft_quote(species["id"], quote_date="2026-08-01",
                               price_per_kg_cents=2500)["id"])
        assert quote["status"] == "PUBLISHED"
        assert quote["volatility_pct"] == 0, (
            "First quote for a species+grade publishes directly with zero volatility")

        # A second grade has its own series: no prior GRADE_B quote exists, so
        # any price publishes directly regardless of the GRADE_A series.
        quote_b = publish_quote(
            create_draft_quote(species["id"], grade="GRADE_B",
                               quote_date="2026-08-01",
                               price_per_kg_cents=1)["id"])
        assert quote_b["status"] == "PUBLISHED"
        assert quote_b["volatility_pct"] == 0


def test_published_quote_expires_on_clock_advance(api):
    """PRD §2.6: "First, every market quote in `PUBLISHED` status whose `quote_date` has passed transitions to `EXPIRED`."
    PRD §3.2: "`SUPERSEDED` and `EXPIRED` are terminal; expiry itself is a clock-driven transition from `PUBLISHED` described in §2.6."

    Design: Corner/state_machines/sm_quote_auto_expires_on_clock_advance
    """
    species = create_species(species_code="COD")
    published = publish_quote(
        create_draft_quote(species["id"], quote_date="2026-08-01",
                           price_per_kg_cents=1200)["id"])
    draft = create_draft_quote(species["id"], quote_date="2026-08-03",
                               price_per_kg_cents=1200)

    set_clock("2026-08-02T00:00:00Z")

    assert _get_quote(published["id"])["status"] == "EXPIRED", (
        "quote_date 2026-08-01 has passed once the clock reads 2026-08-02")
    assert _get_quote(draft["id"])["status"] == "DRAFT", (
        "The sweep expires only PUBLISHED quotes; drafts are untouched")


def test_publish_with_stale_species_version_rejected(api):
    """PRD §2.7: "Publishing a market quote requires `expected_species_version` matching the quoted species' current `version`. Because publishing itself advances the species' `version`, a writer whose view of the species' quote series is stale is rejected with `ERR_STALE_VERSION`."

    Design: Corner/cross_cutting/occ_stale_species_version_on_quote_publish
    """
    species = create_species(species_code="COD")
    stale_version = species["version"]
    q1 = create_draft_quote(species["id"], quote_date="2026-08-01",
                            price_per_kg_cents=1000)
    q2 = create_draft_quote(species["id"], quote_date="2026-08-02",
                            price_per_kg_cents=1050)

    first = validate_success(api_client.publish_market_quote(
        q1["id"], {"expected_species_version": stale_version}, OM))
    assert first["status"] == "PUBLISHED"
    assert get_species_version(species["id"]) == stale_version + 1, (
        "Publishing advances the species version by one")

    resp = api_client.publish_market_quote(
        q2["id"], {"expected_species_version": stale_version}, OM)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    assert _get_quote(q2["id"])["status"] == "DRAFT", (
        "A stale publish must leave the quote in DRAFT")


def test_quote_creator_cannot_self_approve_volatility(api):
    """PRD §3.2: "Volatility approval moves it to `PUBLISHED`, but only when the approving user's `X-User-ID` differs from the quote's `created_by_user_id`; a same-user approval is rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (403), and acting on a quote that is not in `PENDING_APPROVAL` draws `ERR_QUOTE_INVALID_STATE`."
    PRD §3.2: "Whenever a quote reaches `PUBLISHED`, the prior `PUBLISHED` quote for the same species and grade is automatically superseded to `SUPERSEDED`."

    Design: Corner/validations/val_sod_quote_creator_cannot_self_approve_volatility
    """
    species = create_species(species_code="COD")
    q1 = publish_quote(
        create_draft_quote(species["id"], quote_date="2026-08-01",
                           price_per_kg_cents=1000)["id"])
    q2 = create_draft_quote(species["id"], quote_date="2026-08-02",
                            price_per_kg_cents=1150, headers=OM_1_HEADERS)
    q2_after = publish_quote(q2["id"], headers=OM_1_HEADERS)
    assert q2_after["status"] == "PENDING_APPROVAL", "+15.00% must be parked"
    assert q2_after["created_by_user_id"] == "om_1"

    resp = api_client.approve_volatility(q2["id"], OM_1_HEADERS)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION)
    assert _get_quote(q2["id"])["status"] == "PENDING_APPROVAL"

    approved = validate_success(api_client.approve_volatility(q2["id"], OM_2_HEADERS))
    assert approved["status"] == "PUBLISHED"
    assert _get_quote(q1["id"])["status"] == "SUPERSEDED"
