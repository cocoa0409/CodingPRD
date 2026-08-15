"""Optimistic concurrency on agreement amendment, list filter composition,
and reverse-FK reachability of child collections."""
from test_helpers import (
    STD_QUARTERLY_PAYMENT_COUNT,
    ApiErrorId,
    make_active_agreement,
    make_active_rate_table,
    make_donor,
    make_draft_agreement,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAgreementAmendOcc:
    def test_occ_amend_stale_version_rejected(self, api, gift_admin_headers):
        """PRD §2.9: "Amending a draft gift agreement requires the request to
        carry `expected_gift_agreement_version`, holding the agreement
        `version` the client last observed. Because a draft-to-draft amendment
        changes no status field, a second amendment carrying a previously
        observed version would otherwise silently apply on top of an
        intervening amendment; the stale-version check is the only guard. A
        mismatch with the agreement's current `version` is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_amend_stale_version_rejected
        """
        donor = make_donor(full_name="OCC Amend")
        make_active_rate_table()
        agreement = make_draft_agreement(donor["id"])
        v1 = agreement["version"]

        amended = validate_success(
            api.amend_gift_agreement(
                agreement["id"],
                {
                    "expected_gift_agreement_version": v1,
                    "restriction_type": "RESEARCH",
                },
                gift_admin_headers,
            )
        )
        assert amended["version"] == v1 + 1
        assert amended["restriction_type"] == "RESEARCH"

        # Replaying the superseded version is rejected and applies nothing.
        resp = api.amend_gift_agreement(
            agreement["id"],
            {
                "expected_gift_agreement_version": v1,
                "restriction_type": "CAPITAL",
            },
            gift_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert resp.status_code == 412

        after = validate_success(api.get_gift_agreement(agreement["id"], gift_admin_headers))
        assert after["version"] == v1 + 1
        assert after["restriction_type"] == "RESEARCH"


class TestListFilterComposition:
    def test_gift_agreements_list_filters_combined(self, api, gift_officer_headers):
        """PRD §3.3: "the agreement list can be filtered by `donor_id`,
        `fund_id`, `illustration_id`, `rate_table_id`, `status`, and
        `vehicle_type`."

        Multiple filters applied together intersect: donor 1 contributes three
        DRAFT agreements (CGA, CRT_ANNUITY, BEQUEST); donor 2 contributes none.

        Design: Corner/endpoints/gift_agreements_list_filters_combined
        """
        make_active_rate_table()
        donor_1 = make_donor(full_name="Filter One")
        donor_2 = make_donor(full_name="Filter Two", date_of_birth="1960-03-01T00:00:00Z")
        cga = make_draft_agreement(
            donor_1["id"], vehicle_type="CGA", gift_amount_cents=1000000,
            payout_rate_bps=600, annuitant_1_age=70,
        )
        make_draft_agreement(
            donor_1["id"], vehicle_type="CRT_ANNUITY", gift_amount_cents=2000000,
            payout_rate_bps=500, annuitant_1_age=70,
        )
        make_draft_agreement(
            donor_1["id"], vehicle_type="BEQUEST", gift_amount_cents=3000000,
        )

        # Filters intersect: donor 1 + CGA isolates exactly one agreement.
        rows, meta = validate_paginated(
            api.list_gift_agreements(
                gift_officer_headers,
                params={"donor_id": donor_1["id"], "vehicle_type": "CGA"},
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == cga["id"]

        _rows, meta = validate_paginated(
            api.list_gift_agreements(
                gift_officer_headers, params={"donor_id": donor_1["id"], "status": "DRAFT"}
            )
        )
        assert meta["total_count"] == 3

        _rows, meta = validate_paginated(
            api.list_gift_agreements(
                gift_officer_headers, params={"donor_id": donor_2["id"]}
            )
        )
        assert meta["total_count"] == 0
        assert meta["has_more"] is False


class TestReverseFkReachability:
    def test_fk_reverse_reachability_reads(self, api, gift_officer_headers):
        """PRD §4: "| GET | `/giving/gift-agreements` | List agreements
        (filters: `donor_id`, `fund_id`, `illustration_id`, `rate_table_id`,
        `status`, `vehicle_type`) | All roles |"
        PRD §4: "| GET | `/giving/beneficiary-designations` | List designations
        (filters: `gift_agreement_id`, `slot`, `status`) | All roles |"
        PRD §4: "| GET | `/giving/annuity-payments` | List payments (filters:
        `gift_agreement_id`, `status`); lazy sweep; sorted by period index
        within an agreement | All roles |"
        PRD §4: "| GET | `/giving/gift-assets` | List assets (filters:
        `gift_agreement_id`, `estate_id`, `asset_kind`, `status`) | All
        roles |"

        Design: Corner/endpoints/fk_reverse_reachability_reads
        """
        donor = make_donor(full_name="Reverse FK", date_of_birth="1946-06-01T00:00:00Z")
        make_active_rate_table()
        agreement, payments = make_active_agreement(donor["id"])
        # The single VERIFIED designation created along the way.
        agreements, meta = validate_paginated(
            api.list_gift_agreements(
                gift_officer_headers, params={"donor_id": donor["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert agreements[0]["id"] == agreement["id"]

        designations, meta = validate_paginated(
            api.list_beneficiary_designations(
                gift_officer_headers, params={"gift_agreement_id": agreement["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert designations[0]["status"] == "VERIFIED"

        payments_list, meta = validate_paginated(
            api.list_annuity_payments(
                gift_officer_headers,
                params={"gift_agreement_id": agreement["id"], "limit": 100},
            )
        )
        # Age 80, QUARTERLY: 4 * (100 - 80) = 80 payments.
        assert meta["total_count"] == STD_QUARTERLY_PAYMENT_COUNT
        assert len(payments_list) == STD_QUARTERLY_PAYMENT_COUNT

        assets, meta = validate_paginated(
            api.list_gift_assets(
                gift_officer_headers, params={"gift_agreement_id": agreement["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert assets[0]["asset_kind"] == "CASH"
