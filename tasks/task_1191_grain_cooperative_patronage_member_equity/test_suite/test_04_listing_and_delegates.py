"""List-endpoint envelope, FK reverse-reachability, computed delegate flag
(PRD §2.3, §3.1, §3.5)."""
from test_helpers import (
    validate_paginated, assert_certificate,
    create_district, create_member, seat_delegate, set_clock,
    setup_closed_final_year,
    TEST_USERS,
)

TREASURER = TEST_USERS["treasurer_headers"]


def test_list_members_pagination_defaults(api, registrar_headers):
    """PRD §2.3: "The `limit` parameter caps the number of items returned: it
    defaults to 10 when omitted, accepts a minimum of 1, and is clamped at a
    maximum of 100. The `offset` parameter specifies how many items to skip
    and defaults to 0."
    PRD §2.3: "Paginated list responses carry the fields `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object of the response
    envelope."

    Design: Corner/endpoints/list_members_pagination_defaults
    """
    district = create_district(code="DIST-COR-14", name="Corner 14",
                               max_delegates=5)
    for ref in ("P-COR-14-A", "P-COR-14-B", "P-COR-14-C"):
        create_member(district["id"], patron_ref=ref)
    data, meta = validate_paginated(api.list_members(registrar_headers))
    assert len(data) == 3
    assert meta["limit"] == 10, f"Default limit must be 10, got {meta['limit']}"
    assert meta["offset"] == 0
    assert meta["total_count"] == 3
    assert meta["has_more"] is False


def test_member_certificates_reverse_reachability(api):
    """PRD §3.5: "Cycles can be listed with `board_resolution_id`,
    `equity_class`, and `status` filters; certificate ledgers can be listed
    per member, or across the cooperative with `member_id`, `fiscal_year_id`,
    `allocation_id`, `revolvement_cycle_id`, `replaces_certificate_id`,
    `status`, and `equity_class` filters."

    Design: Corner/endpoints/list_member_certificates_fk_reverse_reachability
    """
    ctx = setup_closed_final_year(
        [{"member_key": "patron", "commodity": "CORN", "gross_bushels": 100}],
        net_margin_cents=50000,
    )
    member = ctx["members"]["patron"]
    data, meta = validate_paginated(
        api.list_member_certificates(member["id"], TREASURER),
    )
    assert len(data) >= 1, "Expected certificates issued by the year's close"
    for cert in data:
        assert_certificate(cert)
        assert cert["member_id"] == member["id"]


def test_delegate_is_seated_computed(api, registrar_headers):
    """PRD §3.1: "A delegate's `is_seated` flag is computed: it is true
    exactly when the delegate's term covers the current logical clock and the
    delegate's member is `ACTIVE`."

    Design: Corner/cross_cutting_layers/delegate_term_computed_is_seated
    """
    set_clock("2026-06-01T00:00:00Z")
    district = create_district(code="DIST-COR-22", name="Corner 22",
                               max_delegates=2)
    member = create_member(district["id"], patron_ref="P-COR-22",
                           legal_name="Seated Farm")
    delegate = seat_delegate(district["id"], member["id"],
                             term_start="2025-01-01T00:00:00Z",
                             term_end="2027-01-01T00:00:00Z")
    assert delegate["is_seated"] is True, (
        "Delegate whose term covers the clock and whose member is ACTIVE "
        f"must be seated, got {delegate}"
    )
