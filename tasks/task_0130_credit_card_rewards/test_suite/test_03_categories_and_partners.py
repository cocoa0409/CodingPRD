"""CashbackCategory and TransferPartner catalogue — PRD §3.2 / §3.3.

Coverage:
- Category creation with each category_type.
- requires_activation is derived from category_type, not client-supplied.
- base_rate_bps bounds [0, 10000].
- Partner creation; default is_active=true.
- partner_type filter on list endpoint.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_cashback_category,
    assert_transfer_partner,
    create_cashback_category_payload,
    create_transfer_partner_payload,
    random_category_code,
    random_partner_code,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Category creation — PRD §3.2
# ===========================================================================
class TestCategoryCreation:
    """PRD §3.2 category creation."""

    @pytest.mark.parametrize(
        "category_type",
        ["BASELINE", "FIXED_BONUS", "ROTATING_QUARTERLY"],
    )
    def test_create_each_category_type(
        self, api, admin_headers, category_type,
    ):
        """PRD §3.2: "a category_type drawn from BASELINE, FIXED_BONUS,
        and ROTATING_QUARTERLY".

        Claim: each enumerated category_type is accepted on POST.
        """
        # category_type chosen as the prefix for human-readable codes.
        # PRD §3.2: code must be uppercase A-Z plus underscore.
        resp = api.create_cashback_category(
            create_cashback_category_payload(
                code=random_category_code(category_type),
                category_type=category_type,
                base_rate_bps=300,
            ),
            admin_headers,
        )
        cat = validate_success(resp, expected_status=201)
        assert_cashback_category(cat)
        assert cat["category_type"] == category_type
        assert cat["base_rate_bps"] == 300

    def test_requires_activation_true_for_rotating_only(
        self, api, admin_headers,
    ):
        """PRD §3.2: "On creation, the server sets requires_activation
        to true if and only if category_type is ROTATING_QUARTERLY; the
        field is therefore derived, not client-supplied."

        Claim: requires_activation == True for ROTATING_QUARTERLY,
        False for BASELINE and FIXED_BONUS.
        """
        rot = validate_success(
            api.create_cashback_category(
                create_cashback_category_payload(
                    code=random_category_code("ROT"),
                    category_type="ROTATING_QUARTERLY",
                    base_rate_bps=500,
                ),
                admin_headers,
            ),
            expected_status=201,
        )
        assert rot["requires_activation"] is True

        baseline = validate_success(
            api.create_cashback_category(
                create_cashback_category_payload(
                    code=random_category_code("BL"),
                    category_type="BASELINE", base_rate_bps=100,
                ),
                admin_headers,
            ),
            expected_status=201,
        )
        assert baseline["requires_activation"] is False

        fixed = validate_success(
            api.create_cashback_category(
                create_cashback_category_payload(
                    code=random_category_code("FX"),
                    category_type="FIXED_BONUS", base_rate_bps=300,
                ),
                admin_headers,
            ),
            expected_status=201,
        )
        assert fixed["requires_activation"] is False

    def test_base_rate_bps_lower_boundary_zero(self, api, admin_headers):
        """PRD §3.2: "an integer base_rate_bps between zero and ten
        thousand inclusive that expresses the earn rate in basis points".

        Claim: base_rate_bps=0 (lower boundary) is accepted.
        """
        resp = api.create_cashback_category(
            create_cashback_category_payload(
                code=random_category_code("ZRO"),
                category_type="BASELINE", base_rate_bps=0,
            ),
            admin_headers,
        )
        cat = validate_success(resp, expected_status=201)
        assert cat["base_rate_bps"] == 0

    def test_base_rate_bps_upper_boundary_ten_thousand(
        self, api, admin_headers,
    ):
        """PRD §3.2: "an integer base_rate_bps between zero and ten
        thousand inclusive".

        Claim: base_rate_bps=10000 (upper boundary) is accepted.
        """
        resp = api.create_cashback_category(
            create_cashback_category_payload(
                code=random_category_code("MAX"),
                category_type="FIXED_BONUS", base_rate_bps=10_000,
            ),
            admin_headers,
        )
        cat = validate_success(resp, expected_status=201)
        assert cat["base_rate_bps"] == 10_000


# ===========================================================================
# TransferPartner creation — PRD §3.3
# ===========================================================================
class TestPartnerCreation:
    """PRD §3.3 partner creation."""

    def test_create_partner_defaults_is_active_true(
        self, api, admin_headers,
    ):
        """PRD §3.3: "an optional is_active boolean defaulting to true
        that gates whether the partner accepts new transfers".

        Claim: a partner created without is_active in the payload comes
        back with is_active == True.
        """
        resp = api.create_transfer_partner(
            create_transfer_partner_payload(
                code=f"AIR_{random_partner_code()[4:]}",
                partner_type="AIRLINE",
                conversion_ratio_points_per_unit=2,
                min_transfer_increment=1000,
                is_active=None,
            ),
            admin_headers,
        )
        partner = validate_success(resp, expected_status=201)
        assert_transfer_partner(partner)
        assert partner["is_active"] is True

    def test_create_inactive_partner(self, api, admin_headers):
        """PRD §3.3: "an optional is_active boolean defaulting to true
        that gates whether the partner accepts new transfers".

        Claim: a partner created with is_active=False is accepted and
        returns the supplied value.
        """
        resp = api.create_transfer_partner(
            create_transfer_partner_payload(
                code=f"HOT_{random_partner_code()[4:]}",
                partner_type="HOTEL",
                conversion_ratio_points_per_unit=3,
                min_transfer_increment=500,
                is_active=False,
            ),
            admin_headers,
        )
        partner = validate_success(resp, expected_status=201)
        assert partner["is_active"] is False

    @pytest.mark.parametrize(
        "partner_type", ["AIRLINE", "HOTEL"],
    )
    def test_create_each_partner_type(
        self, api, admin_headers, partner_type,
    ):
        """PRD §3.3: "a partner_type of AIRLINE or HOTEL".

        Claim: both enumerated partner_type values are accepted.
        """
        resp = api.create_transfer_partner(
            create_transfer_partner_payload(
                code=f"P{partner_type[:3]}_{random_partner_code()[4:]}",
                partner_type=partner_type,
                conversion_ratio_points_per_unit=2,
                min_transfer_increment=1000,
            ),
            admin_headers,
        )
        partner = validate_success(resp, expected_status=201)
        assert partner["partner_type"] == partner_type


# ===========================================================================
# Partner listing — PRD §3.3 + §2.3
# ===========================================================================
class TestPartnerListing:

    def test_partner_list_returns_paginated_envelope(
        self, api, admin_headers,
    ):
        """PRD §3.3: "Partners may be listed and filtered by
        partner_type and is_active."

        Claim: GET /transfer-partners returns a paginated envelope with
        limit/offset/total_count/has_more.
        """
        # Create at least 2 partners so the list is non-empty.
        for code_prefix in ("AIR", "HOT"):
            api.create_transfer_partner(
                create_transfer_partner_payload(
                    code=f"{code_prefix}_{random_partner_code()[4:]}",
                    partner_type=(
                        "AIRLINE" if code_prefix == "AIR" else "HOTEL"
                    ),
                    conversion_ratio_points_per_unit=2,
                    min_transfer_increment=1000,
                ),
                admin_headers,
            )
        resp = api.list_transfer_partners(admin_headers)
        data, meta = validate_paginated(resp)
        assert isinstance(data, list)
        assert meta["total_count"] >= 2
