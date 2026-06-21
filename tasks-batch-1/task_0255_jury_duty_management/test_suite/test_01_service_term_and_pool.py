"""Service term creation, juror pool seeding, and pool_size reconciliation.

Translates corner-design instances from §1.9 sections `entities` and
`cross_cutting_complexity_layers`.
"""
from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    create_service_term_payload, create_juror_payload,
    assert_service_term, assert_juror,
    TEST_USERS,
    ABSENT_UUID,
    create_term, add_juror, admin_qualify, get_term,
)

_ADMIN = TEST_USERS["jury_administrator_headers"]


def test_create_service_term_returns_201_with_default_fields(api):
    """PRD §3.1: "A term is born in `DRAFT` status, which is its `status`."
    PRD §3.1: "A monotone `draw_seq` counter, starting at zero, advances on every
    draw and serves as the stable selection-order audit handle."
    PRD §3.1: "The administrator may also supply `fta_disqualify_threshold` ... when
    omitted it defaults to 3, and any supplied value must be at least one."
    PRD §2.4: "The `version` field is an integer that starts at its initial value
    on creation and increments by one on every mutation of the resource."

    Design: Corner/entities/create_service_term_returns_201_with_fields
    """
    resp = api.create_service_term(
        create_service_term_payload(name="C1"), _ADMIN
    )
    data = validate_success(resp, 201)
    assert_service_term(data)
    assert data["status"] == "DRAFT", f"expected DRAFT, got {data['status']}"
    assert data["version"] == 1, f"expected version 1, got {data['version']}"
    assert data["draw_seq"] == 0, f"expected draw_seq 0, got {data['draw_seq']}"
    assert data["pool_size"] == 0, f"expected pool_size 0, got {data['pool_size']}"
    assert data["summoned_count"] == 0, f"expected summoned_count 0, got {data['summoned_count']}"
    assert data["fta_disqualify_threshold"] == 3, (
        f"omitted threshold must default to 3, got {data['fta_disqualify_threshold']}"
    )


def test_create_service_term_missing_required_field_rejected(api):
    """PRD §3.9: "Every request body is finally checked for required fields, valid
    enum membership, and in-range numeric values; a missing field, a bad enum, or
    an out-of-range value is rejected with `ERR_INVALID_REQUEST` (HTTP 422)."

    Design: Corner/entities/create_service_term_missing_required_field
    """
    payload = create_service_term_payload(name="C2")
    del payload["daily_pay_cents"]
    resp = api.create_service_term(payload, _ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_get_service_term_not_found(api):
    """PRD §2.5: "The request is rejected with `ERR_NOT_FOUND` (HTTP 404) for the
    first identifier in the path — or the first body-referenced identifier — that
    does not resolve to an existing resource."

    Design: Corner/entities/get_service_term_not_found
    """
    resp = api.get_service_term(ABSENT_UUID, _ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_new_juror_defaults(api):
    """PRD §3.1: "A new juror records its parent term in `service_term_id`, begins
    with `qualification_status` of `PENDING`, a `fta_strike_count` of 0, a
    `disqualified` flag of false, and a `last_drawn_seq` of 0 (which marks a juror
    that has never been drawn)."

    Design: Corner/entities/juror_qualification_status_defaults_pending
    """
    term = create_term(name="C4")
    resp = api.create_juror(term["id"], create_juror_payload(full_name="Pen J"), _ADMIN)
    data = validate_success(resp, 201)
    assert_juror(data)
    assert data["qualification_status"] == "PENDING"
    assert data["fta_strike_count"] == 0
    assert data["disqualified"] is False
    assert data["last_drawn_seq"] == 0


def test_pool_size_reconciles_upward_on_qualify(api):
    """PRD §3.1: "Two computed counters travel with the term: `pool_size`, the
    number of jurors in this term whose `qualification_status` is `QUALIFIED` and
    whose `disqualified` flag is false."
    PRD §3.1: "The override is only permitted while the juror's `disqualified` flag
    is false, and on success the term's `pool_size` is recomputed upward."

    Design: Corner/cross_cutting_complexity_layers/pool_size_derived_field_reconciliation
    """
    term = create_term(name="CC2")
    j1 = add_juror(term["id"], full_name="Lyn J")
    j2 = add_juror(term["id"], full_name="Mob J")
    assert get_term(term["id"])["pool_size"] == 0, "pool_size must be 0 before any qualify"
    admin_qualify(j1["id"])
    assert get_term(term["id"])["pool_size"] == 1, "pool_size must be 1 after first qualify"
    admin_qualify(j2["id"])
    assert get_term(term["id"])["pool_size"] == 2, "pool_size must be 2 after second qualify"


def test_list_service_terms_paginated_envelope(api):
    """PRD §2.3: "The `total_count` reflects the full size of the filtered
    collection before pagination is applied, and `has_more` indicates whether
    records remain beyond the current page."

    Design: Corner/entities/list_service_terms_paginated_envelope
    """
    for name in ("L1", "L2", "L3"):
        create_term(name=name)
    resp = api.list_service_terms(_ADMIN, params={"limit": 2, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 2, f"expected 2 terms on the page, got {len(data)}"
    assert meta["total_count"] == 3, f"expected total_count 3, got {meta['total_count']}"
    assert meta["has_more"] is True, "has_more must be true when records remain"
