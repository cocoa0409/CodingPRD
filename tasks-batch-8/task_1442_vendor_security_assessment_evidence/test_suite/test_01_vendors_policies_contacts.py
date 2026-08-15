"""Vendor registration, tier policies, and vendor contacts (PRD §3.1)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_instant_equal,
    assert_score,
    assert_vendor,
    create_vendor_payload,
    get_success_data,
    register_vendor,
    setup_active_policy,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestVendorRegistration:
    def test_vendor_create_derives_tier_from_rank_fallback(self, api):
        """PRD §3.1: "The three ranks are summed into a score from zero to nine:
        a sum of seven or higher yields `TIER_4`, five or six yields `TIER_3`,
        three or four yields `TIER_2`, and two or lower yields `TIER_1`."
        PRD §3.1: "A freshly registered vendor begins in the `ONBOARDING` posture
        with no cycle in flight, so its `active_cycle_id` is null, and its
        `offboarding_deadline` is likewise null until offboarding begins."

        REGULATED(3) + PRIVILEGED(3) + MISSION_CRITICAL(3) = 9 -> TIER_4.

        Design: Corner/entities/vendor_create_success_with_derived_tier
        """
        setup_active_policy()
        res = api.create_vendor(
            create_vendor_payload(
                legal_name="Acme",
                data_sensitivity="REGULATED",
                access_level="PRIVILEGED",
                criticality="MISSION_CRITICAL",
            ),
            self._analyst(),
        )
        vendor = validate_success(res, 201)
        assert_vendor(vendor)
        assert vendor["current_tier"] == "TIER_4"
        assert vendor["posture"] == "ONBOARDING"
        assert vendor["active_cycle_id"] is None
        assert vendor["offboarding_deadline"] is None
        # PRD §3.8: "start from a base by posture — 50 for `ONBOARDING`" with no modifiers.
        assert_score(vendor["risk_score"], 50.0)

    def test_vendor_create_missing_required_field_rejected(self, api):
        """PRD §2.9: "Schema and semantic completeness — at a single shared
        precedence tier: enum membership and required-field presence (an
        `item_key` known to the pinned template, a `destruction_method` whenever
        `data_destroyed` is true, a `severity` or `kind` inside its declared enum)
        yield `ERR_INVALID_REQUEST` (422)".
        PRD §3.1: "A `RiskAnalyst` registers a new vendor by supplying its
        `legal_name` and three classification attributes".

        Design: Corner/entities/vendor_create_missing_required_field_returns_invalid_request
        """
        setup_active_policy()
        payload = {
            "legal_name": "Acme",
            "access_level": "READ_ONLY",
            "criticality": "LOW",
        }
        res = api.create_vendor(payload, self._analyst())
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)
        data, meta = validate_paginated(api.list_vendors(self._analyst()))
        assert meta["total_count"] == 0, f"No vendor row may be created, got {meta['total_count']}"

    def test_vendor_get_not_found(self, api):
        """PRD §2.5: "The first identifier that does not correspond to an existing
        resource aborts the request with `ERR_NOT_FOUND` (HTTP 404) before any
        later segment — or any business rule — is evaluated."

        Design: Corner/entities/vendor_get_not_found_returns_404
        """
        res = api.get_vendor(NON_EXISTENT_UUID, self._analyst())
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)

    def test_vendor_list_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter sets the maximum number of items
        returned; it defaults to 10, with a minimum of 1 and a maximum of 100."
        PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`,
        `total_count`, and `has_more`."

        Design: Corner/entities/vendor_list_pagination_envelope
        """
        setup_active_policy()
        for name in ("A", "B", "C"):
            register_vendor(legal_name=name, with_contact=False)
        data, meta = validate_paginated(api.list_vendors(self._analyst()))
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert len(data) == 3

    def test_client_supplied_system_fields_ignored_on_create(self, api):
        """PRD §2.4: "`version` (integer): a system-managed counter that starts on
        creation and increments by one on every mutation of the resource, including
        mutations the server applies as side effects of operations on related
        resources."

        A client-supplied version of 99 must not survive creation.

        Design: Corner/entities/immutable_common_fields_input_ignored
        """
        setup_active_policy()
        payload = create_vendor_payload(legal_name="V")
        payload["version"] = 99
        vendor = validate_success(api.create_vendor(payload, self._analyst()), 201)
        assert vendor["version"] != 99, "Server-managed version must ignore client input"
        assert isinstance(vendor["version"], int)

    @staticmethod
    def _analyst():
        from test_helpers import TEST_USERS

        return TEST_USERS["risk_analyst_headers"]


class TestTierPolicy:
    def test_only_one_active_policy(self, api):
        """PRD §3.1: "Exactly one policy may be active at a time: creating a policy
        with `active` true deactivates whichever policy was active before, and any
        attempt that would leave two active policies is rejected with
        `ERR_UNIQUENESS_VIOLATION` (HTTP 409)."

        Design: Corner/entities/tier_policy_only_one_active
        """
        from test_helpers import TEST_USERS, create_tier_policy_payload

        admin = TEST_USERS["platform_admin_headers"]
        p1 = validate_success(api.create_tier_policy(create_tier_policy_payload(name="P1"), admin), 201)
        p2 = validate_success(api.create_tier_policy(create_tier_policy_payload(name="P2"), admin), 201)
        p1_after = validate_success(api.get_tier_policy(p1["id"], admin), 200)
        p2_after = validate_success(api.get_tier_policy(p2["id"], admin), 200)
        assert p1_after["active"] is False, "First policy must be deactivated"
        assert p2_after["active"] is True, "Second policy must be active"


class TestVendorContacts:
    def test_single_primary_contact_per_vendor(self, api):
        """PRD §3.1: "Exactly one contact per vendor may be primary; marking a new
        contact primary demotes the incumbent, and anything that would leave two
        primaries is rejected with `ERR_UNIQUENESS_VIOLATION`."

        Design: Corner/entities/vendor_contact_single_primary_per_vendor
        """
        from test_helpers import TEST_USERS, create_contact_payload

        setup_active_policy()
        vendor, c1 = register_vendor(with_contact=True)  # c1 is primary
        analyst = TEST_USERS["risk_analyst_headers"]
        c2 = validate_success(
            api.create_contact(
                vendor["id"],
                create_contact_payload(email="c2@example.com", full_name="C2", is_primary=True),
                analyst,
            ),
            201,
        )
        assert c2["is_primary"] is True
        contacts = get_success_data(api.list_contacts(vendor["id"], analyst))
        primaries = [c for c in contacts if c["is_primary"]]
        assert len(primaries) == 1, f"Exactly one primary must remain, got {len(primaries)}"
        assert primaries[0]["id"] == c2["id"]
