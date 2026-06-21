"""Entity CRUD, defaults/computed/system fields, type constraints, FK integrity,
endpoint side effects, residual error triggerability, and RBAC (role denials,
segregation of duties).
"""
import test_helpers as h


# ---------------------------------------------------------------------------
# Queue B — entities section
# ---------------------------------------------------------------------------
def test_create_importer_returns_201_with_defaults(api):
    """PRD §3.1: "A new importer starts with `status` of `ACTIVE` (the only other value being `SUSPENDED`) and a `continuous_bond_id` of null."

    POST /importers returns 201 with status ACTIVE and continuous_bond_id null.

    Design: Corner/entities/create_importer_returns_201_with_defaults
    """
    resp = api.create_importer(
        h.create_importer_payload(ior_number="IOR-DEF-01"), h.ADMIN
    )
    data = h.validate_success(resp, expected_status=201)
    h.assert_importer(data)
    assert data["status"] == "ACTIVE", data
    assert data["continuous_bond_id"] is None, data


def test_get_importer_by_id_returns_stored_entity(api):
    """PRD §3.1: "Importers can be fetched individually and listed".

    GET /importers/{id} returns the stored importer with matching id and
    ior_number.

    Design: Corner/entities/get_importer_by_id_returns_stored_entity
    """
    created = h.create_importer(api, ior_number="IOR-GET-02")
    fetched = h.validate_success(api.get_importer(created["id"], h.ADMIN))
    assert fetched["id"] == created["id"], fetched
    assert fetched["ior_number"] == "IOR-GET-02", fetched


def test_list_entries_filtered_by_importer_paginates(api):
    """PRD §2.3: "the `meta` block carries the effective `limit`, the effective `offset`, the `total_count` of records matching the query before pagination, and a `has_more` boolean that is true exactly when records remain beyond the current page."

    GET /entries?importer_id=X returns an array envelope; with one entry,
    total_count is 1 and has_more is false.

    Design: Corner/entities/list_entries_filtered_by_importer_paginates
    """
    importer = h.create_importer(api, ior_number="IOR-LST-03")
    bond = h.create_active_bond(api, importer["id"])
    entry = h.validate_success(
        api.create_entry(
            h.create_entry_payload(importer["id"], bond["id"]), h.BROKER
        ),
        expected_status=201,
    )
    data, meta = h.validate_paginated(
        api.list_entries(h.ADMIN, params={"importer_id": importer["id"],
                                          "limit": 10, "offset": 0})
    )
    ids = [e["id"] for e in data]
    assert ids == [entry["id"]], data
    assert meta["total_count"] == 1, meta
    assert meta["has_more"] is False, meta


def test_get_bond_nonexistent_id_returns_not_found(api):
    """PRD §2.6: "every referenced resource — whether named in the URL path or carried as a foreign key in the body — must exist; references are checked left to right, and the first missing reference yields `ERR_NOT_FOUND` (HTTP 404)."

    GET /bonds/{id} with a non-existent UUID returns ERR_NOT_FOUND.

    Design: Corner/entities/get_bond_nonexistent_id_returns_not_found
    """
    h.validate_error(
        api.get_bond(h.NONEXISTENT_UUID, h.ADMIN), h.ApiErrorId.ERR_NOT_FOUND
    )


def test_create_importer_missing_ior_number_rejected(api):
    """PRD §3.1: "Creation supplies the importer's legal `name`, which must be non-empty; its `ior_number`, the Importer of Record number that must be non-empty and unique across all importers".

    POST /importers omitting the required ior_number is rejected ERR_VALIDATION.

    Design: Corner/entities/create_importer_missing_ior_number_rejected
    """
    h.validate_error(
        api.create_importer(
            {"name": "Acme Imports", "owner_user_id": "imp-user-1"}, h.ADMIN
        ),
        h.ApiErrorId.ERR_VALIDATION,
    )


def test_entry_line_optional_fields_default(api):
    """PRD §3.3: "the optional `assists_cents` of dutiable additions" ... "(defaulting to 0 and never negative)" ... "an optional `preference_claim` of either `NONE` (the default) or `USMCA`, and an optional `pga_flag` of `NONE` (the default), `FDA`, or `USDA`".

    Omitting assists_cents, preference_claim, and pga_flag applies the defaults
    0, NONE, NONE.

    Design: Corner/entities/entry_line_assists_defaults_zero
    """
    importer = h.create_importer(api, ior_number="IOR-DFL-04")
    bond = h.create_active_bond(api, importer["id"])
    entry = h.validate_success(
        api.create_entry(h.create_entry_payload(importer["id"], bond["id"]), h.BROKER),
        expected_status=201,
    )
    line = h.validate_success(
        api.create_line(
            entry["id"],
            {"hts_code": "9403600080", "customs_value_cents": 1_000_000, "quantity": 1},
            h.BROKER,
        ),
        expected_status=201,
    )
    assert line["assists_cents"] == 0, line
    assert line["preference_claim"] == "NONE", line
    assert line["pga_flag"] == "NONE", line


def test_importer_system_fields_minted_input_ignored(api):
    """PRD §2.4: "The `version` begins at 1 on creation".
    PRD §3.1: "A new importer starts with `status` of `ACTIVE`".

    POST /importers mints version 1 and forces status ACTIVE; the id is a
    server-minted non-empty string.

    Design: Corner/entities/importer_system_id_and_created_at_generated_input_ignored
    """
    data = h.validate_success(
        api.create_importer(h.create_importer_payload(ior_number="IOR-SYS-06"), h.ADMIN),
        expected_status=201,
    )
    assert data["version"] == 1, data
    assert data["status"] == "ACTIVE", data
    assert isinstance(data["id"], str) and len(data["id"]) > 0, data


def test_entry_line_invalid_hts_code_format_rejected(api):
    """PRD §3.3: "The `hts_code` must be exactly ten digits; a value that is not is rejected with `ERR_INVALID_FORMAT` (HTTP 422)."

    POST /entries/{id}/lines with a non-10-digit hts_code is rejected
    ERR_INVALID_FORMAT.

    Design: Corner/entities/entry_line_invalid_hts_code_format_rejected
    """
    importer = h.create_importer(api, ior_number="IOR-FMT-07")
    bond = h.create_active_bond(api, importer["id"])
    entry = h.validate_success(
        api.create_entry(h.create_entry_payload(importer["id"], bond["id"]), h.BROKER),
        expected_status=201,
    )
    h.validate_error(
        api.create_line(
            entry["id"],
            {"hts_code": "61091", "customs_value_cents": 1_000_000, "quantity": 1},
            h.BROKER,
        ),
        h.ApiErrorId.ERR_INVALID_FORMAT,
    )


def test_entry_country_of_origin_not_two_letter_rejected(api):
    """PRD §3.3: "The `country_of_origin` must be exactly two uppercase letters; a malformed value is rejected with `ERR_INVALID_FORMAT` (HTTP 422)."

    POST /entries with country_of_origin 'CHN' (not 2 letters) is rejected
    ERR_INVALID_FORMAT.

    Design: Corner/entities/entry_country_of_origin_not_two_letter_rejected
    """
    importer = h.create_importer(api, ior_number="IOR-FMT-08")
    bond = h.create_active_bond(api, importer["id"])
    h.validate_error(
        api.create_entry(
            h.create_entry_payload(importer["id"], bond["id"],
                                   country_of_origin="CHN"),
            h.BROKER,
        ),
        h.ApiErrorId.ERR_INVALID_FORMAT,
    )


def test_isf_data_element_count_out_of_range_rejected(api):
    """PRD §2.8: "a value failing a simple type or range check, such as a non-positive `customs_value_cents` or a `data_element_count` outside the range 0 through 10 — yields `ERR_VALIDATION` (HTTP 422)."

    POST /isf-filings with data_element_count 11 (out of 0..10) is rejected
    ERR_VALIDATION.

    Design: Corner/entities/isf_data_element_count_out_of_range_rejected
    """
    importer = h.create_importer(api, ior_number="IOR-RNG-09")
    h.validate_error(
        api.create_isf(
            h.create_isf_payload(importer["id"], data_element_count=11), h.BROKER
        ),
        h.ApiErrorId.ERR_VALIDATION,
    )


def test_entry_line_nonpositive_customs_value_rejected(api):
    """PRD §2.8: "a value failing a simple type or range check, such as a non-positive `customs_value_cents`" ... "yields `ERR_VALIDATION` (HTTP 422)."

    POST /entries/{id}/lines with customs_value_cents 0 violates '> 0' and is
    rejected ERR_VALIDATION.

    Design: Corner/entities/entry_line_nonpositive_customs_value_rejected
    """
    importer = h.create_importer(api, ior_number="IOR-RNG-10")
    bond = h.create_active_bond(api, importer["id"])
    entry = h.validate_success(
        api.create_entry(h.create_entry_payload(importer["id"], bond["id"]), h.BROKER),
        expected_status=201,
    )
    h.validate_error(
        api.create_line(
            entry["id"],
            {"hts_code": "9403600080", "customs_value_cents": 0, "quantity": 1},
            h.BROKER,
        ),
        h.ApiErrorId.ERR_VALIDATION,
    )


def test_entry_bond_fk_nonexistent_returns_not_found(api):
    """PRD §2.6: "every referenced resource — whether named in the URL path or carried as a foreign key in the body — must exist; references are checked left to right, and the first missing reference yields `ERR_NOT_FOUND` (HTTP 404)."

    POST /entries with a bond_id that resolves to no Bond is rejected ERR_NOT_FOUND.

    Design: Corner/entities/entry_bond_fk_nonexistent_returns_not_found
    """
    importer = h.create_importer(api, ior_number="IOR-FK-11")
    h.validate_error(
        api.create_entry(
            h.create_entry_payload(importer["id"], h.NONEXISTENT_UUID), h.BROKER
        ),
        h.ApiErrorId.ERR_NOT_FOUND,
    )


def test_entry_lines_reverse_reachable_from_entry(api):
    """PRD §3.3: "Each **entry line** is created against its parent through the
    entry-scoped line path".
    PRD §4: "List the HTS lines of an entry."

    The two lines created under an entry are returned by GET /entries/{id}/lines.

    Design: Corner/entities/entry_lines_reverse_reachable_from_entry
    """
    importer = h.create_importer(api, ior_number="IOR-REV-12")
    bond = h.create_active_bond(api, importer["id"])
    entry = h.validate_success(
        api.create_entry(h.create_entry_payload(importer["id"], bond["id"]), h.BROKER),
        expected_status=201,
    )
    line_a = h.validate_success(
        api.create_line(entry["id"], h.create_line_payload(), h.BROKER),
        expected_status=201,
    )
    line_b = h.validate_success(
        api.create_line(
            entry["id"],
            h.create_line_payload(hts_code="8501100000", customs_value_cents=500_000),
            h.BROKER,
        ),
        expected_status=201,
    )
    data, meta = h.validate_paginated(api.list_lines(entry["id"], h.BROKER))
    ids = {l["id"] for l in data}
    assert ids == {line_a["id"], line_b["id"]}, data
    assert meta["total_count"] == 2, meta


# ---------------------------------------------------------------------------
# Queue B — endpoints section
# ---------------------------------------------------------------------------
def test_pga_review_created_pending_then_listable_by_entry(api):
    """PRD §3.6: "A new review starts with a `decision` of `PENDING` and a null `reviewed_by_user_id`. Reviews may be fetched and listed, the list optionally filtered by `entry_id`."

    POST /pga-reviews creates a PENDING review; GET /pga-reviews?entry_id=X lists it.

    Design: Corner/endpoints/pga_review_created_pending_then_listable_by_entry
    """
    importer = h.create_importer(api, ior_number="IOR-EP-01")
    bond = h.create_active_bond(api, importer["id"])
    entry = h.validate_success(
        api.create_entry(h.create_entry_payload(importer["id"], bond["id"]), h.BROKER),
        expected_status=201,
    )
    h.validate_success(
        api.create_line(
            entry["id"],
            h.create_line_payload(hts_code="2106909998", customs_value_cents=200_000,
                                  pga_flag="FDA"),
            h.BROKER,
        ),
        expected_status=201,
    )
    pga = h.validate_success(
        api.create_pga_review(h.create_pga_review_payload(entry["id"], "FDA"), h.BROKER),
        expected_status=201,
    )
    assert pga["decision"] == "PENDING", pga
    data, _ = h.validate_paginated(
        api.list_pga_reviews(h.BROKER, params={"entry_id": entry["id"]})
    )
    assert pga["id"] in {r["id"] for r in data}, data


def test_bonds_reverse_reachable_by_importer_filter(api):
    """PRD §3.1: "Bonds may be fetched and listed, the list optionally filtered by `importer_id`."

    GET /bonds?importer_id=X returns the array of bonds for that importer.

    Design: Corner/endpoints/bonds_reverse_reachable_by_importer_filter
    """
    importer = h.create_importer(api, ior_number="IOR-EP-02")
    bond = h.validate_success(
        api.create_bond(
            h.create_bond_payload(importer["id"], bond_type="SINGLE_ENTRY",
                                  limit_cents=5_000_000),
            h.ADMIN,
        ),
        expected_status=201,
    )
    data, meta = h.validate_paginated(
        api.list_bonds(h.ADMIN, params={"importer_id": importer["id"]})
    )
    assert [b["id"] for b in data] == [bond["id"]], data
    assert meta["total_count"] == 1, meta


def test_deny_psc_has_no_fiscal_effect(api):
    """PRD §3.10: "A denial sets the filing's `adjustment_cents` to 0, has no fiscal effect on the entry, bond, or statement, sets the filing `status` to `DENIED`".

    Denying a SUBMITTED PSC sets adjustment_cents 0 and status DENIED, leaving the
    entry's final_total_cents unchanged at 54800.

    Design: Corner/endpoints/deny_psc_has_no_fiscal_effect
    """
    ctx = h.setup_liquidated_entry_with_psc(api, corrected_value_delta_cents=200_000)
    denied = h.validate_success(api.deny_psc(ctx["psc"]["id"], h.OFFICER))
    assert denied["status"] == "DENIED", denied
    assert denied["adjustment_cents"] == 0, denied
    entry = h.validate_success(api.get_entry(ctx["entry"]["id"], h.OFFICER))
    assert entry["final_total_cents"] == 54800, entry


# ---------------------------------------------------------------------------
# Queue B — errors section
# ---------------------------------------------------------------------------
def test_unauthenticated_missing_headers_rejected(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of the four roles defined below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    A request without valid auth headers is rejected ERR_UNAUTHENTICATED.

    Design: Corner/errors/unauthenticated_missing_role_header_rejected
    """
    h.validate_error(
        api.list_importers({}), h.ApiErrorId.ERR_UNAUTHENTICATED
    )


# ---------------------------------------------------------------------------
# Queue B — rbac section
# ---------------------------------------------------------------------------
def test_broker_cannot_create_importer_unauthorized(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: "POST | `/importers` | Create an importer of record. | `AccountAdmin`".

    A LicensedBroker attempting POST /importers is rejected ERR_UNAUTHORIZED.

    Design: Corner/rbac/broker_cannot_create_importer_unauthorized
    """
    h.validate_error(
        api.create_importer(
            h.create_importer_payload(ior_number="IOR-RB-01"), h.BROKER
        ),
        h.ApiErrorId.ERR_UNAUTHORIZED,
    )


def test_importer_user_cannot_review_entry_unauthorized(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: "POST | `/entries/{id}/review` | CBP review of a FILED/HOLD_EXAM entry; action RELEASE or HOLD. | `CBPOfficer`".

    An ImporterUser attempting POST /entries/{id}/review is rejected
    ERR_UNAUTHORIZED before any state evaluation.

    Design: Corner/rbac/importer_user_cannot_review_entry_unauthorized
    """
    ctx = h.setup_filed_entry(api)
    owner = h.make_importer_user_headers("imp-user-1")
    h.validate_error(
        api.review_entry(ctx["entry"]["id"], "RELEASE", owner),
        h.ApiErrorId.ERR_UNAUTHORIZED,
    )


def test_liquidate_by_filer_segregation_of_duties_rejected(api):
    """PRD §3.9: "A `CBPOfficer` other than the entry's filer liquidates a `RELEASED` entry" ... "liquidation is permitted only while the entry is `RELEASED` and only when the officer's `X-User-ID` differs from the entry's `filed_by_user_id`."

    An officer whose X-User-ID equals the entry's filed_by_user_id liquidating that
    RELEASED entry is rejected ERR_SEGREGATION_OF_DUTIES; the entry stays RELEASED.

    Design: Corner/rbac/liquidate_by_filer_segregation_of_duties_rejected
    """
    dual_broker = h.make_broker_headers("officer-dual")
    base = h.setup_base(api, broker_user_id="officer-dual")
    entry, _ = h.create_draft_entry_with_lines(api, base, [{}], broker_headers=dual_broker)
    h.file_entry(api, entry["id"], dual_broker)
    # A distinct officer performs the release.
    h.review_entry(api, entry["id"], "RELEASE", h.make_officer_headers("officer-2"))
    # The original filer (acting as officer) attempts to liquidate.
    dual_officer = h.make_officer_headers("officer-dual")
    h.validate_error(
        api.liquidate_entry(entry["id"], dual_officer),
        h.ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
    )
    refreshed = h.validate_success(api.get_entry(entry["id"], h.OFFICER))
    assert refreshed["status"] == "RELEASED", refreshed
