"""Member registry: creation, required fields, retrieval, existence (PRD §3.1)."""
from test_helpers import (
    validate_success, validate_error, NON_EXISTENT_UUID,
    assert_member, member_payload,
    create_district, create_member,
)


def test_member_creation_returns_201_with_zeroed_equity(api, registrar_headers):
    """PRD §3.1: "A newly registered member starts in `ACTIVE` status with all
    equity counters at zero: `capital_share_balance_cents` (outstanding common
    and preferred share capital, tracked separately from patronage equity),
    `qualified_equity_cents`, `nonqualified_equity_cents`,
    `per_unit_retains_cents`, and `total_patronage_volume_bu`."

    Design: Corner/entities/member_creation_with_required_fields_returns_201
    """
    district = create_district(code="DIST-COR-1", name="Corner 1",
                               max_delegates=2)
    res = api.create_member(
        member_payload(district["id"], patron_ref="P-COR-1",
                       legal_name="Corner Farm"),
        registrar_headers,
    )
    member = validate_success(res, 201)
    assert_member(member)
    assert member["status"] == "ACTIVE"
    assert member["qualified_equity_cents"] == 0
    assert member["nonqualified_equity_cents"] == 0
    assert member["per_unit_retains_cents"] == 0


def test_member_creation_missing_patron_ref_returns_400(api, registrar_headers):
    """PRD §3.1: "A `CoopRegistrar` enrolls a new patron by supplying the
    member's `patron_ref` (an external patron reference unique within the
    cooperative), `legal_name`, `member_class`, `joined_at`,
    `delegate_district_id`, and `is_producer_member`."
    PRD §2.10: "Independent of this cascade, any request whose payload is
    missing a required field or carries a malformed value is rejected with
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/member_creation_missing_required_field_returns_400
    """
    district = create_district(code="DIST-COR-2", name="Corner 2",
                               max_delegates=2)
    payload = member_payload(district["id"], legal_name="No Ref")
    del payload["patron_ref"]
    res = api.create_member(payload, registrar_headers)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_member_retrieval_returns_stored_data(api, registrar_headers):
    """PRD §3.1: "A `CoopRegistrar` enrolls a new patron by supplying the
    member's `patron_ref` (an external patron reference unique within the
    cooperative), `legal_name`, `member_class`, `joined_at`,
    `delegate_district_id`, and `is_producer_member`."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."

    Design: Corner/entities/member_retrieval_returns_stored_data
    """
    district = create_district(code="DIST-COR-3", name="Corner 3",
                               max_delegates=2)
    member = create_member(
        district["id"], patron_ref="P-COR-3", legal_name="Retrieval Farm",
        member_class="LLC", joined_at="2024-03-15T00:00:00Z",
        is_producer_member=False,
    )
    retrieved = validate_success(
        api.get_member(member["id"], registrar_headers), 200,
    )
    assert_member(retrieved)
    assert retrieved["id"] == member["id"]
    assert retrieved["patron_ref"] == "P-COR-3"
    assert retrieved["member_class"] == "LLC"
    assert retrieved["is_producer_member"] is False


def test_member_not_found_returns_404(api, registrar_headers):
    """PRD §2.6: "The request is rejected with `ERR_NOT_FOUND` (HTTP 404) at
    the first path identifier that does not correspond to an existing
    resource, before any later identifier or any business rule is examined."

    Design: Corner/entities/member_not_found_returns_404
    """
    res = api.get_member(NON_EXISTENT_UUID, registrar_headers)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)
