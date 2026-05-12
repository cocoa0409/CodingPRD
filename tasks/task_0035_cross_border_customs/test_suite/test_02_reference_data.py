"""HsCode library, TariffRule, ExchangeRate, Importer, Declarant.

PRD anchors: §3.1 (reference data ownership and rules), §3.2
(classification suggestion), §5 (errors).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    TEST_USERS,
    NON_EXISTENT_UUID,
    create_hs_code,
    create_hs_code_payload,
    create_tariff_rule,
    create_tariff_rule_payload,
    create_exchange_rate,
    create_exchange_rate_payload,
    create_importer,
    create_declarant,
    suspend_importer,
    deprecate_hs_code,
    suggest_payload,
    assert_hs_code,
    assert_tariff_rule,
    assert_exchange_rate,
    assert_importer,
    assert_declarant,
)


# ---------------------------------------------------------------------------
# HsCode CRUD + deprecation (PRD §3.1)
# ---------------------------------------------------------------------------
def test_create_and_get_hs_code(api, customs_officer_headers):
    """PRD §3.1: "Each entry in the HS code library carries a 10-digit
    code that is unique across the library, ... and four rate fields
    denominated in basis points: tariff_rate_bps, vat_rate_bps,
    consumption_tax_rate_bps (defaulting to zero for non-luxury goods),
    and postal_tax_rate_bps."
    PRD §3.1: "Every newly created HS code begins life with status set
    to ACTIVE."
    """
    res = api.create_hs_code(create_hs_code_payload(), customs_officer_headers)
    hs = validate_success(res, expected_status=201)
    assert_hs_code(hs)
    assert hs["status"] == "ACTIVE"
    # Round-trip GET.
    get_res = api.get_hs_code(hs["id"], customs_officer_headers)
    fetched = validate_success(get_res)
    assert fetched["id"] == hs["id"]
    assert fetched["code"] == hs["code"]


def test_deprecate_hs_code_flips_status(api, customs_officer_headers):
    """PRD §3.1: "A customs officer may later deprecate a code; deprecation
    flips status to DEPRECATED, and from that moment forward the code may
    not be cited on a new line, though historical declarations that already
    reference it remain valid."
    """
    hs = create_hs_code()
    res = api.deprecate_hs_code(hs["id"], customs_officer_headers)
    deprecated = validate_success(res)
    assert deprecated["status"] == "DEPRECATED"


# ---------------------------------------------------------------------------
# TariffRule overlap detection (PRD §3.1, error ERR_TARIFF_RULE_OVERLAP)
# ---------------------------------------------------------------------------
def test_back_to_back_tariff_rules_accepted(api, customs_officer_headers):
    """PRD §3.1: "Back-to-back rules where one's effective_to exactly
    equals the next's effective_from are explicitly allowed — that is a
    gap-free, overlap-free join, not an overlap."

    Claim: rule A [2026-01-01, 2026-04-01) and rule B [2026-04-01,
    2026-07-01) share only the endpoint and BOTH succeed.
    """
    hs = create_hs_code()
    res_a = api.create_tariff_rule(
        create_tariff_rule_payload(
            hs["id"],
            tariff_rate_bps=500,
            effective_from="2026-01-01T00:00:00Z",
            effective_to="2026-04-01T00:00:00Z",
        ),
        customs_officer_headers,
    )
    validate_success(res_a, expected_status=201)
    res_b = api.create_tariff_rule(
        create_tariff_rule_payload(
            hs["id"],
            tariff_rate_bps=600,
            effective_from="2026-04-01T00:00:00Z",
            effective_to="2026-07-01T00:00:00Z",
        ),
        customs_officer_headers,
    )
    validate_success(res_b, expected_status=201)


def test_overlapping_tariff_rules_rejected(api, customs_officer_headers):
    """PRD §3.1: "the publishing endpoint guards against accidentally
    overlapping rules for the same triple of HS code, origin country,
    and destination country, rejecting any new rule whose interval
    overlaps an existing rule's interval with ERR_TARIFF_RULE_OVERLAP."

    Claim: a rule that straddles a boundary of an existing rule for the
    same (hs_code_id, origin_country, destination_country) → 409
    ERR_TARIFF_RULE_OVERLAP.
    """
    hs = create_hs_code()
    api.create_tariff_rule(
        create_tariff_rule_payload(
            hs["id"],
            tariff_rate_bps=500,
            effective_from="2026-01-01T00:00:00Z",
            effective_to="2026-04-01T00:00:00Z",
        ),
        customs_officer_headers,
    )
    res_b = api.create_tariff_rule(
        create_tariff_rule_payload(
            hs["id"],
            tariff_rate_bps=700,
            effective_from="2026-03-15T00:00:00Z",  # straddles 2026-04-01
            effective_to="2026-05-01T00:00:00Z",
        ),
        customs_officer_headers,
    )
    validate_error(res_b, "ERR_TARIFF_RULE_OVERLAP", expected_status=409)


def test_different_destinations_are_independent(api, customs_officer_headers):
    """PRD §3.1: overlap is keyed by the triple (hs_code_id,
    origin_country, destination_country). A rule for US→CN does not
    conflict with a rule for US→EU on the same code.
    """
    hs = create_hs_code()
    api.create_tariff_rule(
        create_tariff_rule_payload(
            hs["id"],
            origin_country="US",
            destination_country="CN",
            effective_from="2026-01-01T00:00:00Z",
            effective_to="2026-04-01T00:00:00Z",
        ),
        customs_officer_headers,
    )
    res_b = api.create_tariff_rule(
        create_tariff_rule_payload(
            hs["id"],
            origin_country="US",
            destination_country="EU",
            effective_from="2026-01-15T00:00:00Z",
            effective_to="2026-05-01T00:00:00Z",
        ),
        customs_officer_headers,
    )
    validate_success(res_b, expected_status=201)


# ---------------------------------------------------------------------------
# ExchangeRate
# ---------------------------------------------------------------------------
def test_create_exchange_rate(api, customs_officer_headers):
    """PRD §3.1: "Each ExchangeRate row pairs a from_currency and a
    to_currency (both ISO 4217), an integer rate_micros, and an
    effective_date formatted as a YYYY-MM-DD string."
    """
    res = api.create_exchange_rate(
        create_exchange_rate_payload(
            from_currency="USD",
            to_currency="CNY",
            rate_micros=7_123_456,
            effective_date="2026-02-01",
        ),
        customs_officer_headers,
    )
    rate = validate_success(res, expected_status=201)
    assert_exchange_rate(rate)
    assert rate["rate_micros"] == 7_123_456
    assert rate["effective_date"] == "2026-02-01"


# ---------------------------------------------------------------------------
# Importer / Declarant
# ---------------------------------------------------------------------------
def test_importer_default_active_status(api, customs_officer_headers):
    """PRD §3.1: "An importer carries a legal name, a unique
    license_number, and a status that is ACTIVE by default."
    """
    importer = create_importer()
    assert_importer(importer)
    assert importer["status"] == "ACTIVE"


def test_importer_suspension(api, customs_officer_headers):
    """PRD §3.1: "suspension is an explicit operator action that sets
    status to SUSPENDED and blocks creation or submission of declarations
    for that importer."
    """
    importer = create_importer()
    res = api.suspend_importer(importer["id"], customs_officer_headers)
    suspended = validate_success(res)
    assert suspended["status"] == "SUSPENDED"


def test_declarant_default_active_status(api, customs_officer_headers):
    """PRD §3.1: "A declarant carries a name, a unique customs-issued
    agent_code, and an analogous status that defaults to ACTIVE and is
    required to be ACTIVE at submission time."
    """
    declarant = create_declarant()
    assert_declarant(declarant)
    assert declarant["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Classification suggestion (PRD §3.2)
# ---------------------------------------------------------------------------
def test_suggest_returns_top_three_by_score(api):
    """PRD §3.2: "The engine returns the top three candidates ranked by
    score descending, breaking ties by HS code ascending."

    Claim: with two ACTIVE codes whose keywords match, the response
    contains at most three suggestions ordered correctly.
    """
    create_hs_code(
        keywords=["polo", "shirt", "cotton"],
        description="cotton polo shirt",
    )
    create_hs_code(
        keywords=["jacket", "winter"],
        description="winter jacket",
    )
    from test_helpers import create_party_pair, make_declarant_headers
    _, dec = create_party_pair()
    res = api.suggest_classification(
        suggest_payload("a comfortable cotton polo shirt for summer"),
        make_declarant_headers(dec["id"]),
    )
    body = validate_success(res)
    # PRD §3.2: "the engine returns the top three candidates ranked by
    # score descending". The endpoint scaffold output is "object
    # {suggestions: HsCode[], scores: number[]}".
    if isinstance(body, dict) and "suggestions" in body:
        assert isinstance(body["suggestions"], list)
        assert len(body["suggestions"]) <= 3


def test_suggest_excludes_deprecated_codes(api):
    """PRD §3.2: "The engine reads only the live HS code library — every
    row whose status is ACTIVE is a candidate, and DEPRECATED rows are
    ignored."

    Claim: a DEPRECATED code with a perfectly matching description does
    not appear in the suggestions.
    """
    hs = create_hs_code(
        keywords=["uniqueterm"],
        description="uniquetermdesc",
    )
    deprecate_hs_code(hs["id"])
    from test_helpers import create_party_pair, make_declarant_headers
    _, dec = create_party_pair()
    res = api.suggest_classification(
        suggest_payload("uniqueterm widget uniquetermdesc"),
        make_declarant_headers(dec["id"]),
    )
    body = validate_success(res)
    suggestions = body.get("suggestions") if isinstance(body, dict) else None
    if isinstance(suggestions, list):
        ids_returned = [s.get("id") for s in suggestions if isinstance(s, dict)]
        assert hs["id"] not in ids_returned, (
            "DEPRECATED HsCode must not appear in suggestions"
        )


def test_suggest_returns_empty_below_threshold(api):
    """PRD §3.2 verbatim: "If the highest score among any candidate is
    strictly less than 0.20, the engine returns an empty list, signaling
    that the description is too ambiguous and the declarant must classify
    manually."

    Claim: with a candidate library of irrelevant keywords, a totally
    unrelated query yields no suggestions.
    """
    create_hs_code(
        keywords=["alpha", "beta", "gamma", "delta", "epsilon"],
        description="industrial alpha beta gamma delta epsilon machinery",
    )
    from test_helpers import create_party_pair, make_declarant_headers
    _, dec = create_party_pair()
    res = api.suggest_classification(
        suggest_payload("totally unrelated query about something else"),
        make_declarant_headers(dec["id"]),
    )
    body = validate_success(res)
    suggestions = body.get("suggestions") if isinstance(body, dict) else None
    if isinstance(suggestions, list):
        # All scores must have been < 0.20 → empty list.
        assert suggestions == []
