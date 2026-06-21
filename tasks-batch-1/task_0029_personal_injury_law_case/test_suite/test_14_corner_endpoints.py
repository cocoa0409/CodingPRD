"""Corner-design coverage — endpoints section."""
import pytest

from test_helpers import (
    validate_success,
    validate_paginated,
    set_clock,
    register_client,
    sign_retainer,
    create_case,
    activate_case,
    register_provider,
    create_lien,
    create_included_damages,
    api_client,
    make_paralegal_headers,
    make_attorney_headers,
    setup_active_case,
    setup_active_case_with_reviewed_records,
)


# ─── cases_list_pagination_and_status_filter ────────────────────────


def test_cases_list_with_status_filter_and_pagination_returns_filtered_page(api):
    """PRD §2.3: "All list endpoints accept two pagination query parameters.
    The `limit` parameter defaults to 10, has a minimum of 1, and a maximum
    of 100; the `offset` parameter defaults to 0 and has a minimum of 0."
    PRD §2.3: "The response `meta` object for list endpoints carries
    `limit`, `offset`, `total_count`, and `has_more` so the caller can drive
    pagination without re-counting."

    Design: Corner/endpoints/cases_list_pagination_and_status_filter
    """
    from test_helpers import TEST_USERS
    set_clock("2026-01-01T00:00:00Z")
    # Three INTAKE cases (clients without signed retainer cannot ACTIVATE, but
    # they can be opened — INTAKE status).
    c1 = register_client(email="pl1@example.com")
    c2 = register_client(email="pl2@example.com")
    c3 = register_client(email="pl3@example.com")
    c4 = register_client(email="pl4@example.com")
    sign_retainer(c4["id"])
    create_case(c1["id"])
    create_case(c2["id"])
    create_case(c3["id"])
    case4 = create_case(c4["id"])
    # Activate the fourth — it leaves INTAKE.
    activate_case(case4["id"])
    res = api.list_cases(
        TEST_USERS["attorney_headers"],
        params={"status": "INTAKE", "limit": 2, "offset": 0},
    )
    data, meta = validate_paginated(res)
    assert len(data) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert all(item["status"] == "INTAKE" for item in data)


# ─── medical_lien_list_filtered_by_case ─────────────────────────────


def test_medical_lien_list_filtered_by_case_returns_that_cases_liens(api):
    """PRD §2.3: "All list endpoints accept two pagination query parameters.
    The `limit` parameter defaults to 10, has a minimum of 1, and a maximum
    of 100; the `offset` parameter defaults to 0 and has a minimum of 0."

    Design: Corner/endpoints/medical_lien_list_filtered_by_case
    """
    from test_helpers import TEST_USERS
    set_clock("2026-01-01T00:00:00Z")
    # Two cases, each with one lien on the same provider.
    client_a = register_client(email="fa@example.com")
    sign_retainer(client_a["id"])
    case_a = create_case(client_a["id"])
    activate_case(case_a["id"])
    client_b = register_client(email="fb@example.com")
    sign_retainer(client_b["id"])
    case_b = create_case(client_b["id"])
    activate_case(case_b["id"])
    provider = register_provider()
    lien_a = create_lien(case_a["id"], provider["id"], 100_000)
    lien_b = create_lien(case_b["id"], provider["id"], 200_000)
    res = api.list_liens(TEST_USERS["attorney_headers"],
                          params={"case_id": case_a["id"]})
    data, meta = validate_paginated(res)
    # Only case A's lien.
    assert len(data) == 1
    assert data[0]["id"] == lien_a["id"]
    assert data[0]["asserted_amount_cents"] == 100_000


# ─── damages_summary_returns_both_variants ──────────────────────────


def test_damages_summary_returns_both_variants_and_included_total(api):
    """PRD §3.3: "A read-only damages summary is available per case that
    returns, alongside the case identifier and the
    `included_damages_total_cents`, two gross damages numbers: a
    conservative `gross_economic_only_cents` and a standard
    `gross_full_model_cents`. The economic-only model sums `amount_cents`
    across `INCLUDED` items whose `category` is one of `MEDICAL_BILLS`,
    `LOST_WAGES`, `FUTURE_MEDICAL`, or `PROPERTY`; the full model adds the
    sum of `amount_cents` across `INCLUDED` items in `PAIN_SUFFERING`."

    Design: Corner/endpoints/damages_summary_returns_both_variants
    """
    from test_helpers import TEST_USERS
    set_clock("2026-01-01T00:00:00Z")
    client, case, provider, mrr = setup_active_case_with_reviewed_records()
    create_included_damages(case["id"], "MEDICAL_BILLS", 500_000)
    create_included_damages(case["id"], "PAIN_SUFFERING", 300_000)
    res = api.get_damages_summary(case["id"], TEST_USERS["attorney_headers"])
    body = validate_success(res, 200)
    assert body["included_damages_total_cents"] == 800_000
    assert body["gross_economic_only_cents"] == 500_000
    assert body["gross_full_model_cents"] == 800_000
