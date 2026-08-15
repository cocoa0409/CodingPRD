"""Authentication, RBAC denials, donor privacy, and append-only audit log."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    create_campaign_payload, create_donor_payload,
    assert_audit_event, NON_EXISTENT_UUID, ApiErrorId,
    reset_clock, setup_verified_family, setup_gift_in_state, create_donor,
    setup_campaign_intake_open, create_family, add_child, add_wish_item,
    approve_wish_item, begin_review, verify_family, get_family,
    pledge_and_confirm, advance_past_return_deadline, create_event,
    open_event_slots, book_slot,
    make_donor_headers, make_agency_coordinator_headers,
    make_caseworker_headers, make_volunteer_headers, make_platform_admin_headers,
)


class TestAuthentication:
    @pytest.mark.parametrize("headers", [
        {},                                            # neither header
        {"X-User-ID": "someone"},                      # role missing
        {"X-User-Role": "PlatformAdmin"},              # id missing
    ])
    def test_missing_auth_headers_rejected(self, api, headers):
        """PRD §2.1: "Every request must carry two headers: `X-User-ID`, a
        non-empty identifier for the acting principal, and `X-User-Role`, one of
        the five declared role names. Missing or malformed headers yield
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/unauthenticated_request_missing_role_header
        """
        res = api.list_campaigns(headers)
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


class TestForbiddenRoles:
    def test_donor_cannot_create_campaign(self, api, admin_headers):
        """PRD §2.1: "A role that is well-formed but not permitted for the target
        endpoint yields `ERR_FORBIDDEN` (HTTP 403)." PRD §4 lists POST
        /toy-drive/campaigns as PlatformAdmin-only.

        Design: Corner/validations/forbidden_role_for_endpoint
        """
        reset_clock()
        donor = validate_success(api.create_donor(create_donor_payload(),
                                                  admin_headers), 201)
        res = api.create_campaign(create_campaign_payload(),
                                  make_donor_headers(donor["id"]))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    def test_caseworker_cannot_create_campaign(self, api, caseworker_headers):
        """PRD §2.1: "A role that is well-formed but not permitted for the target
        endpoint yields `ERR_FORBIDDEN` (HTTP 403)." PRD §4 lists POST
        /toy-drive/campaigns as PlatformAdmin-only.

        Design: Corner/roles/caseworker_cannot_create_campaign
        """
        reset_clock()
        res = api.create_campaign(create_campaign_payload(), caseworker_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    def test_agency_coordinator_cannot_verify_family(self, api):
        """PRD §2.1: "A role that is well-formed but not permitted for the target
        endpoint yields `ERR_FORBIDDEN` (HTTP 403)." PRD §4 lists POST
        /toy-drive/families/{id}/verify as CaseWorker-only.

        Design: Corner/roles/agency_coordinator_cannot_verify_family
        """
        campaign, agency = setup_campaign_intake_open()
        family = create_family(agency, campaign)
        add_child(family["id"], agency["id"])
        begin_review(family["id"])  # family now UNDER_REVIEW
        res = api.verify_family(
            family["id"], make_agency_coordinator_headers(agency["id"]))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    def test_volunteer_cannot_verify_family(self, api, volunteer_headers):
        """PRD §2.1: "A role that is well-formed but not permitted for the target
        endpoint yields `ERR_FORBIDDEN` (HTTP 403)." PRD §4 lists POST
        /toy-drive/families/{id}/verify as CaseWorker-only.

        Design: Corner/roles/volunteer_cannot_verify_family
        """
        campaign, agency = setup_campaign_intake_open()
        family = create_family(agency, campaign)
        add_child(family["id"], agency["id"])
        begin_review(family["id"])  # family now UNDER_REVIEW
        res = api.verify_family(family["id"], volunteer_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    def test_donor_cannot_receive_gift(self, api):
        """PRD §2.1: "A role that is well-formed but not permitted for the target
        endpoint yields `ERR_FORBIDDEN` (HTTP 403)." PRD §4 lists POST
        /toy-drive/gifts/{id}/receive as DistributionVolunteer-only.

        Design: Corner/roles/donor_cannot_receive_gift
        """
        ctx = setup_gift_in_state("COMMITTED")
        res = api.receive_gift(ctx["gift"]["id"],
                               make_donor_headers(ctx["donor"]["id"]))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


class TestStageRoleGate:
    """The stage endpoint is volunteer-only, so a non-volunteer caller is
    rejected with ERR_FORBIDDEN no matter how the payload would fare against
    the staging consistency rules."""

    def _sorted_gift_with_other_family_slot(self, api):
        # Two matched families in one campaign before intake closes; gift for
        # family 1 sorted; slot booked for family 2.
        campaign, agency = setup_campaign_intake_open()
        fam1 = create_family(agency, campaign)
        child1 = add_child(fam1["id"], agency["id"])
        item1 = add_wish_item(child1["id"], agency["id"])
        approve_wish_item(item1["id"])
        verify_family(fam1["id"])
        fam2 = create_family(agency, campaign)
        child2 = add_child(fam2["id"], agency["id"])
        # The confirm-time fiscal floor (PRD §3.6: commitment_cents >=
        # min_gift_value_cents x covered children) requires the child to
        # carry wish value, so fam2's child needs a wish item.
        add_wish_item(child2["id"], agency["id"])
        verify_family(fam2["id"])
        donor = create_donor()
        ad1 = pledge_and_confirm(campaign, fam1["id"], donor)
        pledge_and_confirm(campaign, fam2["id"], create_donor())
        gift = validate_success(api.create_gift(
            {"adoption_id": ad1["id"], "child_id": child1["id"],
             "wish_item_id": item1["id"], "description": "toy",
             "declared_value_cents": 2000},
            make_donor_headers(donor["id"])), 201)
        validate_success(api.receive_gift(gift["id"],
                                          make_volunteer_headers("vol_1")))
        campaign = advance_past_return_deadline(campaign["id"])
        event = create_event(campaign["id"])
        open_event_slots(event["id"])
        fam2 = get_family(fam2["id"])
        slot_f2 = book_slot(event["id"], fam2["id"],
                            "2026-12-18T10:00:00Z", "2026-12-18T11:00:00Z",
                            lane="A")
        validate_success(api.begin_sorting(event["id"],
                                           make_platform_admin_headers("admin_1")))
        gift = validate_success(api.sort_gift(gift["id"],
                                              make_volunteer_headers("vol_1")))
        return donor, gift, slot_f2

    def test_donor_cannot_stage_gift(self, api):
        """PRD §2.1: "A role that is well-formed but not permitted for the target
        endpoint yields `ERR_FORBIDDEN` (HTTP 403)." PRD §4 lists POST
        /toy-drive/gifts/{id}/stage as DistributionVolunteer-only.

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_on_slot_stage
        """
        donor, gift, slot_f2 = self._sorted_gift_with_other_family_slot(api)
        res = api.stage_gift(gift["id"], slot_f2["id"],
                             make_donor_headers(donor["id"]))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
        after = validate_success(api.get_gift(
            gift["id"], make_platform_admin_headers("admin_1")))
        assert after["status"] == "SORTED"

    def test_caseworker_cannot_stage_gift(self, api):
        """PRD §2.1: "A role that is well-formed but not permitted for the target
        endpoint yields `ERR_FORBIDDEN` (HTTP 403)." PRD §4 lists POST
        /toy-drive/gifts/{id}/stage as DistributionVolunteer-only.

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_on_slot_stage
        """
        _, gift, slot_f2 = self._sorted_gift_with_other_family_slot(api)
        res = api.stage_gift(gift["id"], slot_f2["id"],
                             make_caseworker_headers("cw_9"))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
        after = validate_success(api.get_gift(
            gift["id"], make_platform_admin_headers("admin_1")))
        assert after["status"] == "SORTED"


class TestNotFound:
    def test_get_missing_family_returns_404(self, api, admin_headers):
        """PRD §2.8: "Any URL that templates one or more resource identifiers
        resolves them left-to-right, returning `ERR_NOT_FOUND` (HTTP 404) on the
        first identifier that does not resolve to an existing row."

        Design: Corner/entities/entity_not_found_returns_404
        """
        reset_clock()
        res = api.get_family(NON_EXISTENT_UUID, admin_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


class TestAuditLogShape:
    def test_audit_events_nested_404_and_append_only_shape(self, api,
                                                           admin_headers):
        """PRD §2.8: "Any URL that templates one or more resource identifiers
        resolves them left-to-right, returning `ERR_NOT_FOUND` (HTTP 404) on the
        first identifier that does not resolve to an existing row."
        PRD §2.4: "`FamilyAuditEvent` is the single exception: it is append-only,
        carries only `id` and `created_at`, and has neither `updated_at` nor
        `version`."

        Design: Corner/entities/family_audit_event_immutable_no_update_endpoint
        """
        reset_clock()
        res = api.list_family_audit_events(NON_EXISTENT_UUID, admin_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)

        ctx = setup_verified_family()
        data, _ = validate_paginated(
            api.list_family_audit_events(ctx["family"]["id"], admin_headers))
        assert len(data) >= 1
        for event in data:
            assert_audit_event(event)


class TestDonorPrivacy:
    def test_donor_family_view_strips_caregiver_pii(self, api, admin_headers):
        """PRD §2.9: "Specifically, the fields `primary_caregiver_name`,
        `caregiver_dob`, `address_text`, and `phone_last4` are stripped from any
        response served under a donor role". PRD §2.9: "Every donor read of a
        family — list or single fetch — also writes a `FamilyAuditEvent` with
        `event_type` equal to `PII_VIEW` on the family in question, recording
        `actor_role` and `actor_id` of the donor."

        Design: Corner/endpoints/donor_cannot_see_caregiver_pii
        """
        ctx = setup_verified_family()
        family_id = ctx["family"]["id"]
        donor = create_donor()
        donor_hdrs = make_donor_headers(donor["id"])
        view = validate_success(api.get_family(family_id, donor_hdrs))
        for pii_field in ("primary_caregiver_name", "caregiver_dob",
                          "address_text", "phone_last4"):
            assert pii_field not in view, \
                f"donor-facing family view must not expose {pii_field}"
        # The read itself is audited.
        events, _ = validate_paginated(
            api.list_family_audit_events(family_id, admin_headers))
        pii_views = [e for e in events if e["event_type"] == "PII_VIEW"]
        assert len(pii_views) >= 1
        assert pii_views[-1]["actor_role"] == "Donor"
        assert pii_views[-1]["actor_id"] == donor["id"]
