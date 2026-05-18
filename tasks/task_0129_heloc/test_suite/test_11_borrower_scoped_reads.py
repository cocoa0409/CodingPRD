"""Borrower-scoped reads, ownership traversal, and the HELOC list
filter capability.

Covers PRD §3.10 (borrower identity check, HELOC list filters).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_heloc_get_response,
    make_borrower_headers,
    setup_active_heloc,
    setup_active_heloc_with_balance,
    setup_borrower_property_lien,
    setup_pending_heloc,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# §3.10 GET /helocs/{id} surfaces minimum_payment_due_cents et al
# ===========================================================================
class TestHelocReadEnriched:

    def test_get_heloc_returns_computed_minimum_payment_field(
        self, api, originator_headers,
    ):
        """PRD §3.10: "The single-HELOC read response includes the
        standard fields described in §2.4 as well as the computed
        minimum_payment_due_cents, the current available_credit_cents,
        and the current current_rate_bps, all evaluated against the
        present state of the account."
        """
        _, _, _, heloc = setup_active_heloc()
        resp = api.get_heloc(heloc["id"], originator_headers)
        data = validate_success(resp, 200)
        assert_heloc_get_response(data)
        assert "minimum_payment_due_cents" in data
        assert "available_credit_cents" in data
        assert "current_rate_bps" in data


# ===========================================================================
# §3.10 Borrower ownership traversal — child collection
# ===========================================================================
class TestBorrowerOwnershipTraversal:

    def test_owner_lists_own_draws_succeeds(self, api):
        """PRD §3.10: "When the acting role is Borrower ... the
        borrower's X-User-ID must match the resource's owning
        borrower_id, traversing the chain from the resource back to
        its owning borrower (a HELOC's draw rolls up through the
        HELOC's borrower_id".
        """
        borrower, _, _, heloc, _ = setup_active_heloc_with_balance(
            draw_amount_cents=50_000,
        )
        resp = api.list_draws(
            heloc["id"], make_borrower_headers(borrower["id"]),
        )
        data, _ = validate_paginated(resp)
        assert len(data) >= 1

    def test_stranger_listing_others_draws_forbidden(self, api):
        """PRD §3.10: "A borrower reading another borrower's resource
        is rejected with ERR_FORBIDDEN."
        """
        owner, _, _, heloc, _ = setup_active_heloc_with_balance(
            draw_amount_cents=50_000,
        )
        stranger, _, _ = setup_borrower_property_lien()
        resp = api.list_draws(
            heloc["id"], make_borrower_headers(stranger["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# §3.10 LIST /helocs filtering
# ===========================================================================
class TestHelocListFilters:

    def test_list_helocs_filter_by_borrower_id(
        self, api, originator_headers,
    ):
        """PRD §3.10: "The HELOC list capability accepts optional
        borrower_id, property_id, and status query parameters in
        addition to the standard limit and offset page controls, and
        returns the filtered, paginated set of HELOCs."
        """
        borrower_a, _, _, heloc_a = setup_active_heloc()
        borrower_b, _, _, heloc_b = setup_active_heloc()
        assert borrower_a["id"] != borrower_b["id"]

        resp = api.list_helocs(
            originator_headers,
            params={"borrower_id": borrower_a["id"]},
        )
        data, meta = validate_paginated(resp)
        assert any(h["id"] == heloc_a["id"] for h in data)
        # Filter must EXCLUDE borrower_b's HELOC.
        assert all(h["borrower_id"] == borrower_a["id"] for h in data)

    def test_list_helocs_filter_by_status(
        self, api, originator_headers,
    ):
        """PRD §3.10: "The HELOC list capability accepts optional
        borrower_id, property_id, and status query parameters ... and
        returns the filtered, paginated set of HELOCs."
        """
        _, _, _, pending = setup_pending_heloc()
        _, _, _, active = setup_active_heloc()
        assert pending["status"] == "PENDING"
        assert active["status"] == "DRAW"

        resp = api.list_helocs(
            originator_headers, params={"status": "PENDING"},
        )
        data, _ = validate_paginated(resp)
        assert all(h["status"] == "PENDING" for h in data)
        assert any(h["id"] == pending["id"] for h in data)

    def test_list_helocs_filter_by_property_id(
        self, api, originator_headers,
    ):
        """PRD §3.10: "The HELOC list capability accepts optional
        borrower_id, property_id, and status query parameters".
        """
        _, prop_a, _, heloc_a = setup_active_heloc()
        _, _, _, _ = setup_active_heloc()

        resp = api.list_helocs(
            originator_headers, params={"property_id": prop_a["id"]},
        )
        data, _ = validate_paginated(resp)
        assert all(h["property_id"] == prop_a["id"] for h in data)
        assert any(h["id"] == heloc_a["id"] for h in data)
