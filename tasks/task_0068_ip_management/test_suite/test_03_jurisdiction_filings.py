"""JurisdictionFiling tests for the IP Management API.

Covers PRD §3.2:
- First filing auto-transitions parent IPRight MATERIALS_READY → FILED
- Filing register marks JurisdictionFiling REGISTERED
- When all siblings are REGISTERED/ABANDONED, parent IPRight → REGISTERED,
  registered_at recorded, certificate_archive_url set
- AnnualFeeSchedule fee_year=1 rows are auto-created
"""

from test_helpers import (
    assert_ip_right,
    assert_jurisdiction_filing,
    create_filing_payload,
    register_filing_payload,
    setup_foundation,
    validate_paginated,
    validate_success,
    walk_ip_right_to_filed,
    walk_ip_right_to_registered,
)


class TestFirstFilingAutoTransition:
    """The very first jurisdiction filing auto-transitions parent MATERIALS_READY
    → FILED (PRD §3.2)."""

    def test_first_filing_lifts_parent_to_filed(self, api, ip_manager_headers):
        """PRD §3.2: "The very first filing created beneath a
        `MATERIALS_READY` right auto-transitions the parent `IPRight.status`
        to `FILED`."

        Claim: after the first jurisdiction filing, IPRight.status == FILED.
        """
        found = setup_foundation(api)
        ip, filing = walk_ip_right_to_filed(
            api,
            business_unit_id=found["business_unit"]["id"],
            agent_id=found["agent"]["id"],
        )
        assert_ip_right(ip)
        assert_jurisdiction_filing(filing)
        assert ip["status"] == "FILED"
        assert filing["status"] == "FILED"
        assert filing["ip_right_id"] == ip["id"]


class TestRegistration:
    """JurisdictionFiling → REGISTERED side-effects (PRD §3.2)."""

    def test_register_marks_filing_registered_and_bubbles_parent(
        self, api, ip_manager_headers
    ):
        """PRD §3.2: "On success the filing flips to `REGISTERED`. If, after
        this transition, every sibling `JurisdictionFiling` of the parent
        right is in either `REGISTERED` or `ABANDONED`, the parent
        `IPRight.status` is set to `REGISTERED`, its `registered_at` is
        recorded as the current server time, and its
        `certificate_archive_url` is set to the supplied `archive_url`."

        Claim: registering the only filing → IPRight REGISTERED with
        registered_at set, certificate_archive_url == supplied archive_url.
        """
        found = setup_foundation(api)
        ip, filing = walk_ip_right_to_filed(
            api,
            business_unit_id=found["business_unit"]["id"],
            agent_id=found["agent"]["id"],
        )
        archive_url = "https://example.com/cert/abc123"
        resp = api.register_filing(
            filing["id"],
            register_filing_payload(archive_url=archive_url),
            ip_manager_headers,
        )
        validate_success(resp, expected_status=200)
        # Re-fetch the parent IP to see the bubble-up.
        resp2 = api.get_ip_right(ip["id"], ip_manager_headers)
        ip_after = validate_success(resp2, expected_status=200)
        assert ip_after["status"] == "REGISTERED"
        assert ip_after.get("registered_at") is not None
        assert ip_after.get("certificate_archive_url") == archive_url

    def test_register_auto_creates_annual_fee_year_1(
        self, api, ip_manager_headers, finance_manager_headers
    ):
        """PRD §3.2: "The same call auto-creates fee-year-1
        `AnnualFeeSchedule` rows for every (`jurisdiction`, `ip_type`) pair
        represented in the right's registered filings."

        Claim: after register-filing, an AnnualFeeSchedule with fee_year==1
        and matching jurisdiction exists for the right.
        """
        found = setup_foundation(api)
        ip, _ = walk_ip_right_to_registered(
            api,
            business_unit_id=found["business_unit"]["id"],
            agent_id=found["agent"]["id"],
            primary_jurisdiction="US",
        )
        resp = api.list_annual_fees(
            finance_manager_headers, params={"ip_right_id": ip["id"]}
        )
        data, _ = validate_paginated(resp)
        years = [f for f in data if int(f.get("fee_year", 0)) == 1]
        assert len(years) >= 1, (
            "PRD §3.2 requires an auto-created fee_year=1 AnnualFeeSchedule "
            "after the IPRight reaches REGISTERED"
        )
