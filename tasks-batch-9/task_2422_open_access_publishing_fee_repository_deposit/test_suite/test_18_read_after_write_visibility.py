"""Read-after-write visibility.

Every derived counter and every appended ledger row is recomputed inside the
request that triggered it, so the response of a write already reports the new
state and the very next read observes it.  There is no settling step and no
background job anywhere in this system.
"""

from datetime import datetime

from test_helpers import (
    TEST_USERS,
    add_coverage,
    activate_agreement,
    create_eligibility_check_payload,
    draft_agreement,
    read_agreement,
    read_publisher,
    record_article,
    register_author,
    register_journal,
    register_publisher,
    set_clock,
    validate_paginated,
    validate_success,
)

ADMIN_HEADERS = TEST_USERS["agreement_admin_headers"]
LIBRARIAN_HEADERS = TEST_USERS["librarian_headers"]


def _as_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant regardless of how many fractional digits the
    server renders."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# --------------------------------------------------------------------------- #
# local preamble
# --------------------------------------------------------------------------- #
def _setup_drafted_agreement_and_article() -> dict:
    """Publisher MERID with a HYBRID journal at 380000, a DRAFT agreement at a
    20% discount carrying one FULL_APC coverage line, and one accepted manuscript
    by an author with no grant."""
    publisher = register_publisher(
        publisher_code="MERID", name="Meridian Academic Press", country_code="NL"
    )
    journal = register_journal(
        publisher["id"],
        issn="2041-1723",
        title="Meridian Journal of Cell Signalling",
        oa_model="HYBRID",
        list_apc_cents=380000,
        required_embargo_months=12,
    )
    author = register_author(
        full_name="Ilse Vermeer",
        email="ilse.vermeer@uni.example",
        orcid="0000-0002-1111-2222",
        department_code="CEL",
        affiliation_status="ELIGIBLE_FACULTY",
        appointment_from="2024-01-01",
        appointment_until="2028-12-31",
        annual_cap_cents=500000,
    )
    agreement = draft_agreement(
        publisher["id"],
        agreement_code="TA-MERID-2027",
        effective_from="2026-07-01",
        effective_until="2027-07-01",
        article_quota=5,
        discount_pct=0.20,
        covered_oa_models=["HYBRID"],
    )
    coverage = add_coverage(
        agreement["id"],
        journal["id"],
        coverage_type="FULL_APC",
        covered_from="2026-07-01",
        covered_until="2027-06-30",
    )
    article = record_article(
        journal["id"],
        author["id"],
        headers=LIBRARIAN_HEADERS,
        manuscript_title="Immediately visible side effects",
        accepted_on="2026-08-05",
    )
    return {
        "publisher": publisher,
        "journal": journal,
        "author": author,
        "agreement": agreement,
        "coverage": coverage,
        "article": article,
    }


# --------------------------------------------------------------------------- #
# activation side effects
# --------------------------------------------------------------------------- #
def test_agreement_activation_side_effects_are_visible_to_the_next_publisher_read(api):
    """The activation response already reports ACTIVE with activated_at taken from
    the logical clock, and the immediately following publisher read already shows
    active_agreement_count 1 and the bumped version.

    PRD §2.10: "Whenever a fact changes, every counter derived from that fact is recomputed in the same request, and every row whose stored values change has its `updated_at` refreshed and its `version` incremented by one."
    PRD §2.10: "Cascades that span several entities are described where the triggering operation is described, and they always run to completion within the single request that triggered them."
    PRD §3.2: "Activation stamps `activated_at` from the logical clock, recomputes the publisher's `active_agreement_count` — which rises by one, since the agreement has just become active — and increments the publisher's `version` by one."
    PRD §2.10: "`Publisher.active_agreement_count` is the number of that publisher's transformative agreements whose `status` is `ACTIVE`."
    Design: Corner/consistency_model/corner_side_effects_are_visible_to_the_next_read
    """
    set_clock("2026-08-10T00:00:00Z")
    scenario = _setup_drafted_agreement_and_article()

    activated = validate_success(
        api.activate_transformative_agreement(scenario["agreement"]["id"], ADMIN_HEADERS)
    )
    assert activated["status"] == "ACTIVE", (
        f"the activation response must already report ACTIVE, got "
        f"{activated['status']!r}"
    )
    assert activated.get("activated_at") is not None, (
        "activation must stamp activated_at from the logical clock"
    )
    assert _as_instant(activated["activated_at"]) == _as_instant(
        "2026-08-10T00:00:00Z"
    ), (
        "activated_at must be the logical-clock instant 2026-08-10T00:00:00Z, got "
        f"{activated['activated_at']!r}"
    )

    publisher_after = read_publisher(scenario["publisher"]["id"])
    assert publisher_after["active_agreement_count"] == 1, (
        "the next publisher read must already count the newly active agreement, got "
        f"active_agreement_count {publisher_after['active_agreement_count']}"
    )
    assert publisher_after["version"] == 3, (
        "registration, drafting and activation each bump the publisher's version, so "
        f"it must read 3, got {publisher_after['version']}"
    )


# --------------------------------------------------------------------------- #
# appended determination side effects
# --------------------------------------------------------------------------- #
def test_appended_determination_is_visible_to_the_next_list_and_article_read(api):
    """The determination appended by the eligibility check is returned by the very
    next list read, and the same request has already refreshed the article's route
    and covered amount and the agreement's quota consumption.

    PRD §2.10: "Whenever a fact changes, every counter derived from that fact is recomputed in the same request, and every row whose stored values change has its `updated_at` refreshed and its `version` incremented by one."
    PRD §3.4: "The determination is inserted, `Article.determination_count` rises by one, and the article's own `eligibility_route`, `covered_amount_cents` and `author_share_cents` are refreshed from the newly effective row."
    PRD §3.4: "The `discount_pct_applied` is that agreement's `discount_pct`, and the discounted price is `list_base_cents` multiplied by one minus the discount, rounded half up to whole cents — this is the only rounding step in the whole determination."
    PRD §3.4: "If the matched coverage line's `coverage_type` is `FULL_APC`, the `route` is `TA_FULL`, `covered_amount_cents` is the whole discounted price, `author_share_cents` is 0, `eligible_request_cents` is 0 because there is nothing left to subsidise, and `determination_reason` is `TA_FULL_COVERAGE`."
    PRD §2.10: "`Article.determination_count` is the number of determinations written for that article and equals the highest `sequence_no` among them; `Article.latest_deposit_ordinal` is the highest `version_ordinal` among that article's deposits."
    PRD §2.10: "`TransformativeAgreement.articles_used` is the number of articles whose effective eligibility determination names this agreement and whose determination route is either `TA_FULL` or `TA_CAPPED`."
    Design: Corner/consistency_model/corner_side_effects_are_visible_to_the_next_read
    """
    set_clock("2026-08-10T00:00:00Z")
    scenario = _setup_drafted_agreement_and_article()
    activate_agreement(scenario["agreement"]["id"])
    article_id = scenario["article"]["id"]

    determination = validate_success(
        api.create_eligibility_check(
            article_id,
            create_eligibility_check_payload("PROVISIONAL"),
            LIBRARIAN_HEADERS,
        ),
        expected_status=201,
    )
    assert determination["route"] == "TA_FULL", (
        "the journal is covered by a FULL_APC line of the active agreement, so the "
        f"route must be TA_FULL, got {determination['route']!r}"
    )
    assert determination["sequence_no"] == 1, (
        f"the first determination of an article carries sequence_no 1, got "
        f"{determination['sequence_no']}"
    )

    rows, meta = validate_paginated(
        api.list_eligibility_determinations(
            LIBRARIAN_HEADERS,
            params={"article_id": article_id, "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 1, (
        "the determination just appended must already be listed, total_count should "
        f"be 1, got {meta['total_count']}"
    )
    assert len(rows) == 1, (
        f"the determinations page must carry exactly 1 row, got {len(rows)}"
    )
    assert rows[0]["id"] == determination["id"], (
        "the listed determination must be the one the eligibility check appended"
    )

    article_after = validate_success(api.get_article(article_id, LIBRARIAN_HEADERS))
    assert article_after["eligibility_route"] == "TA_FULL", (
        "the article's route must already be refreshed from the newly effective "
        f"determination, got {article_after['eligibility_route']!r}"
    )
    assert article_after["covered_amount_cents"] == 304000, (
        "a 20% discount on a list charge of 380000 cents leaves 304000 cents covered "
        f"in full, got {article_after['covered_amount_cents']}"
    )
    assert article_after["determination_count"] == 1, (
        f"determination_count must already read 1, got "
        f"{article_after['determination_count']}"
    )

    agreement_after = read_agreement(scenario["agreement"]["id"])
    assert agreement_after["articles_used"] == 1, (
        "the agreement's quota consumption must already reflect the new "
        f"determination, got articles_used {agreement_after['articles_used']}"
    )
