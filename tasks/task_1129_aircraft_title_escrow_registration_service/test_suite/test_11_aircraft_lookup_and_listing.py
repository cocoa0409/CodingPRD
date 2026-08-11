"""Aircraft duplicate n-number, missing-resource lookup, and list pagination
envelope (PRD §3.1, §2.6, §2.3)."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_aircraft,
    create_aircraft,
    create_aircraft_payload,
    create_buyer_seller,
    create_escrow_file,
    validate_error,
    validate_paginated,
    validate_success,
)

OFFICER = TEST_USERS["officer_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


class TestAircraftRegistration:
    def test_duplicate_n_number_rejected(self, api):
        """PRD §3.1: "The `n_number` must be unique across all registered
        aircraft; a duplicate is rejected with `ERR_DUPLICATE_N_NUMBER`."

        Design: Corner/entities/e_aircraft_duplicate_n_number_rejected
        """
        first = validate_success(
            api.create_aircraft(
                create_aircraft_payload(n_number="N111AA", serial_number="S-1",
                                        make_model="Cessna 172", year=2001),
                OFFICER,
            ),
            201,
        )
        assert_aircraft(first)

        res = api.create_aircraft(
            create_aircraft_payload(n_number="N111AA", serial_number="S-2",
                                    make_model="Piper PA-28", year=2002),
            OFFICER,
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_N_NUMBER, expected_status=409)

        reread = validate_success(api.get_aircraft(first["id"], OFFICER), 200)
        assert reread["id"] == first["id"]
        assert reread["n_number"] == "N111AA"

    def test_get_missing_aircraft_returns_not_found(self, api, officer_headers):
        """PRD §2.6: "The first identifier that fails to resolve, or whose
        resolved child does not in fact belong to the resolved parent, terminates
        the request with `ERR_NOT_FOUND`."

        Design: Corner/entities/e_get_aircraft_not_found_returns_404
        """
        res = api.get_aircraft("00000000-0000-4000-8000-0000000000ff", officer_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


class TestEscrowFileListPagination:
    def test_limit_offset_pages_with_total_count_and_has_more(self, api, auditor_headers):
        """PRD §2.3: "`limit` bounds the number of items returned; it defaults to
        10, accepts a minimum of 1, and rejects anything above 100. `offset` skips
        that many items from the start of the result set and defaults to 0."
        PRD §2.3: "`total_count` is the size of the full filtered result set
        before pagination; `has_more` is true when `offset + limit < total_count`."

        Three files paged 2 + 1; pages are disjoint.

        Design: Corner/entities/e_list_pagination_envelope
        """
        buyer, seller = create_buyer_seller()
        file_ids = []
        for i, n_number in enumerate(("N115E1", "N115E2", "N115E3")):
            aircraft = create_aircraft(n_number=n_number,
                                       serial_number=f"S-{6 + i}",
                                       make_model="Piper PA-46", year=2007 + i)
            escrow_file = create_escrow_file(
                aircraft["id"], buyer["id"], seller["id"],
                purchase_price_cents=1_000_000,
            )
            file_ids.append(escrow_file["id"])

        page1, meta1 = validate_paginated(
            api.list_escrow_files(auditor_headers, params={"limit": 2, "offset": 0})
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_escrow_files(auditor_headers, params={"limit": 2, "offset": 2})
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        ids_p1 = {row["id"] for row in page1}
        ids_p2 = {row["id"] for row in page2}
        assert ids_p1.isdisjoint(ids_p2)
        assert ids_p1 | ids_p2 == set(file_ids)
