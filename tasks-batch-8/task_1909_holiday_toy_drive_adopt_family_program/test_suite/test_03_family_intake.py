"""Family referral intake: quotas, windows, duplicate detection, review loop."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    assert_is_sha256_hex, ApiErrorId,
    reset_clock, set_clock, create_campaign, create_agency,
    setup_campaign_intake_open, create_family, add_child, add_wish_item,
    begin_review, verify_family, get_family, get_child,
    open_campaign_intake, create_family_payload,
    make_agency_coordinator_headers, make_caseworker_headers,
    make_platform_admin_headers,
    CLOCK,
)


class TestReferralIntakeGate:
    def test_family_create_starts_referred(self, api):
        """PRD §3.3: "The family lifecycle begins at `REFERRED`."

        Design: Corner/state_machines/family_initial_state_is_referred
        """
        campaign, agency = setup_campaign_intake_open()
        family = create_family(agency, campaign)
        assert family["status"] == "REFERRED"

    def test_family_create_before_intake_window_rejected(self, api):
        """PRD §3.3: "the temporal intake-window check (the current instant must
        be at or after `intake_open_at` and at or before `intake_close_at`, and
        the campaign must currently be in `INTAKE_OPEN` — a failure yields
        `ERR_INTAKE_CLOSED`, HTTP 409)".

        Design: Corner/validations/family_create_outside_intake_window
        """
        reset_clock()  # logical clock 2026-08-01, before the 2026-09-01 opening
        campaign = create_campaign()
        agency = create_agency()
        headers = make_agency_coordinator_headers(agency["id"])
        res = api.create_family(
            create_family_payload(agency["id"], campaign["id"]), headers)
        validate_error(res, ApiErrorId.ERR_INTAKE_CLOSED, expected_status=409)

    def test_agency_quota_exceeded(self, api):
        """PRD §3.2: "Submitting a referral when `referral_used_count` has reached
        `referral_quota` is rejected with `ERR_AGENCY_QUOTA_EXCEEDED` (HTTP 409)."

        Design: Corner/validations/agency_quota_exceeded
        """
        campaign, agency = setup_campaign_intake_open()
        quota_one = create_agency(referral_quota=1)
        create_family(quota_one, campaign)  # consumes the single slot
        headers = make_agency_coordinator_headers(quota_one["id"])
        res = api.create_family(
            create_family_payload(quota_one["id"], campaign["id"]), headers)
        validate_error(res, ApiErrorId.ERR_AGENCY_QUOTA_EXCEEDED,
                       expected_status=409)

    def test_suspended_agency_cannot_refer(self, api, admin_headers):
        """PRD §3.2: "a `SUSPENDED` agency may not submit new referrals, and any
        attempt to do so is rejected with `ERR_AGENCY_SUSPENDED` (HTTP 409)."

        Design: Corner/endpoints/agency_suspend_blocks_new_referrals
        """
        campaign, agency = setup_campaign_intake_open()
        validate_success(api.suspend_agency(agency["id"], admin_headers))
        headers = make_agency_coordinator_headers(agency["id"])
        res = api.create_family(
            create_family_payload(agency["id"], campaign["id"]), headers)
        validate_error(res, ApiErrorId.ERR_AGENCY_SUSPENDED, expected_status=409)


class TestDuplicateDetection:
    def test_duplicate_hash_is_server_computed_sha256(self, api):
        """PRD §3.3: "the resulting string is prefixed with the
        `SeasonSettings.duplicate_hash_salt` followed by a colon, and the whole is
        hashed with SHA-256 rendered as a 64-character lowercase hexadecimal
        string."

        Design: Corner/entities/family_computed_duplicate_hash_ignores_client_input
        """
        campaign, agency = setup_campaign_intake_open()
        pii = {"caregiver_dob": "1990-05-05", "address_text": "7 Dup St",
               "phone_last4": "7777"}
        fam_a = create_family(agency, campaign, **pii)
        fam_b = create_family(agency, campaign, **pii)
        assert_is_sha256_hex(fam_a["duplicate_hash"])
        assert_is_sha256_hex(fam_b["duplicate_hash"])
        # Deterministic over the same PII triple: identical inputs hash identically.
        assert fam_a["duplicate_hash"] == fam_b["duplicate_hash"]

    def test_duplicate_hash_collision_auto_creates_open_flag(self, api,
                                                             admin_headers):
        """PRD §3.3: "When `duplicate_auto_detect_enabled` is `true`, the server
        then scans the campaign for any other `Family` row in a non-terminal state
        (not `REJECTED`, not `WITHDRAWN`, not `CLOSED`) with the identical
        `duplicate_hash`, and for each match it creates a `DuplicateFlag` with
        `detected_by` equal to `AUTO_HASH`, `family_id` pointing at the new
        family, and `other_family_id` pointing at the matched family."

        Design: Corner/validations/duplicate_hash_collision_auto_creates_flag
        """
        campaign, agency = setup_campaign_intake_open()
        pii = {"caregiver_dob": "1990-05-05", "address_text": "7 Dup St",
               "phone_last4": "7777"}
        create_family(agency, campaign, **pii)
        fam_b = create_family(agency, campaign, **pii)
        data, meta = validate_paginated(api.list_duplicate_flags(
            admin_headers, params={"family_id": fam_b["id"]}))
        assert meta["total_count"] == 1
        assert data[0]["status"] == "OPEN"
        assert data[0]["detected_by"] == "AUTO_HASH"


class TestDuplicateFlagGating:
    def test_begin_review_blocked_by_open_flag(self, api):
        """PRD §3.3: "A `CaseWorker` begins review — `REFERRED → UNDER_REVIEW` —
        provided no `OPEN` `DuplicateFlag` references this family in either
        direction (neither as `family_id` nor as `other_family_id`); a violation
        yields `ERR_DUPLICATE_FLAG_OPEN` (HTTP 409)."

        Design: Corner/errors/error_duplicate_flag_open_blocks_verify
        """
        campaign, agency = setup_campaign_intake_open()
        fam_a = create_family(agency, campaign)
        fam_b = create_family(agency, campaign)
        validate_success(api.create_duplicate_flag(
            fam_b["id"], fam_a["id"], make_caseworker_headers("cw_9")), 201)
        res = api.begin_review(fam_b["id"], make_caseworker_headers("cw_1"))
        validate_error(res, ApiErrorId.ERR_DUPLICATE_FLAG_OPEN,
                       expected_status=409)

    def test_verify_blocked_by_flag_raised_after_review_began(self, api):
        """PRD §3.3: "The caseworker may verify the family — `UNDER_REVIEW →
        VERIFIED` — provided the family's `total_children_count` is at least 1,
        every child of the family has a computed `age_band`, and no `OPEN`
        duplicate flag references the family".

        Design: Corner/errors/error_duplicate_flag_open_blocks_verify
        """
        campaign, agency = setup_campaign_intake_open()
        fam_a = create_family(agency, campaign)
        fam_b = create_family(agency, campaign)
        add_child(fam_b["id"], agency["id"])
        begin_review(fam_b["id"])  # cw_1; verify must use a different actor
        validate_success(api.create_duplicate_flag(
            fam_b["id"], fam_a["id"], make_caseworker_headers("cw_9")), 201)
        res = api.verify_family(fam_b["id"], make_caseworker_headers("cw_2"))
        validate_error(res, ApiErrorId.ERR_DUPLICATE_FLAG_OPEN,
                       expected_status=409)

    def test_second_dismiss_rejected(self, api, admin_headers):
        """PRD §3.3: "Dismissing it — `OPEN → DISMISSED` — writes the
        `DUPLICATE_RESOLVED` audit event with no family-side cascade." From
        `DISMISSED` no further transition is defined, and the error catalogue maps
        an undefined transition to `ERR_INVALID_STATE` (HTTP 409).

        Design: Corner/state_machines/duplicate_flag_dismiss_is_idempotent_on_second_attempt
        """
        campaign, agency = setup_campaign_intake_open()
        pii = {"caregiver_dob": "1990-05-05", "address_text": "7 Dup St",
               "phone_last4": "7777"}
        create_family(agency, campaign, **pii)
        fam_b = create_family(agency, campaign, **pii)
        flags, _ = validate_paginated(api.list_duplicate_flags(
            admin_headers, params={"family_id": fam_b["id"]}))
        flag_id = flags[0]["id"]
        validate_success(api.dismiss_duplicate_flag(
            flag_id, make_caseworker_headers("cw_1"), resolution_note="ok"))
        res = api.dismiss_duplicate_flag(
            flag_id, make_caseworker_headers("cw_1"), resolution_note="second")
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        flag = validate_success(api.get_duplicate_flag(flag_id, admin_headers))
        assert flag["status"] == "DISMISSED"


class TestDuplicateConfirmCascade:
    def _flagged_pair(self, api, admin_headers):
        campaign, agency = setup_campaign_intake_open()
        pii = {"primary_caregiver_name": "Same Person",
               "caregiver_dob": "1990-05-05", "address_text": "7 Dup St",
               "phone_last4": "7777"}
        fam_a = create_family(agency, campaign, **pii)
        fam_b = create_family(agency, campaign, **pii)
        flags, _ = validate_paginated(api.list_duplicate_flags(
            admin_headers, params={"family_id": fam_b["id"]}))
        return fam_a, fam_b, flags[0]["id"]

    def test_confirm_rejects_flagged_family_and_links_primary(self, api,
                                                              admin_headers):
        """PRD §3.3: "Confirming it — `OPEN → CONFIRMED_DUPLICATE` — rejects the
        flagged family (if the family is not already in a terminal status) with
        reason `CONFIRMED_DUPLICATE`, points the flagged family's self-referential
        `duplicate_of_family_id` at the suspected primary record, and writes a
        `FamilyAuditEvent` of type `DUPLICATE_RESOLVED` on both families."

        Design: Difficulty/transitive_cascade/duplicate_confirm_three_hop_cascade
        """
        fam_a, fam_b, flag_id = self._flagged_pair(api, admin_headers)
        validate_success(api.confirm_duplicate_flag(
            flag_id, make_caseworker_headers("cw_3"),
            resolution_note="confirmed same household"))
        flag = validate_success(api.get_duplicate_flag(flag_id, admin_headers))
        assert flag["status"] == "CONFIRMED_DUPLICATE"
        fam_b_after = get_family(fam_b["id"])
        assert fam_b_after["status"] == "REJECTED"
        assert fam_b_after["duplicate_of_family_id"] == fam_a["id"]
        fam_a_after = get_family(fam_a["id"])
        assert fam_a_after["status"] == "REFERRED", \
            "the suspected primary record is untouched by the resolution"

    def test_confirm_writes_resolution_audit_on_both_families(self, api,
                                                              admin_headers):
        """PRD §3.3: "Confirming it — `OPEN → CONFIRMED_DUPLICATE` — rejects the
        flagged family (if the family is not already in a terminal status) with
        reason `CONFIRMED_DUPLICATE`, points the flagged family's self-referential
        `duplicate_of_family_id` at the suspected primary record, and writes a
        `FamilyAuditEvent` of type `DUPLICATE_RESOLVED` on both families."

        Design: Difficulty/transitive_cascade/duplicate_confirm_three_hop_cascade
        """
        fam_a, fam_b, flag_id = self._flagged_pair(api, admin_headers)
        validate_success(api.confirm_duplicate_flag(
            flag_id, make_caseworker_headers("cw_3")))
        for fam_id in (fam_a["id"], fam_b["id"]):
            events, _ = validate_paginated(
                api.list_family_audit_events(fam_id, admin_headers))
            resolved = [e for e in events
                        if e["event_type"] == "DUPLICATE_RESOLVED"]
            assert len(resolved) >= 1, \
                f"family {fam_id} must carry a DUPLICATE_RESOLVED audit event"


class TestReviewLoop:
    def test_review_cycles_then_verify_stamps_verified_at(self, api,
                                                          admin_headers):
        """PRD §3.3: "Or the caseworker may return the family to referral —
        `UNDER_REVIEW → REFERRED` — a cyclic revision loop that may be exercised
        any number of times while the caseworker awaits further documentation."
        PRD §3.3: "verification stamps `verified_at`". PRD §3.3: "Every family
        create also writes a `FamilyAuditEvent` of type `STATUS_CHANGE`." PRD
        §3.3: "Reject, return-to-referral, and verify all accept an optional
        `verification_note`, and each writes a `FamilyAuditEvent` of type
        `STATUS_CHANGE`."

        Design: Difficulty/non_linear_state_machine/family_review_cycle
        """
        campaign, agency = setup_campaign_intake_open()
        family = create_family(agency, campaign)
        add_child(family["id"], agency["id"])
        cw1 = make_caseworker_headers("cw_1")
        cw2 = make_caseworker_headers("cw_2")
        # Three review entries, two returns to referral, then a final verify.
        validate_success(api.begin_review(family["id"], cw1))
        validate_success(api.return_to_referral(family["id"], cw1,
                                                verification_note="need docs"))
        validate_success(api.begin_review(family["id"], cw1))
        validate_success(api.return_to_referral(family["id"], cw1,
                                                verification_note="still need docs"))
        validate_success(api.begin_review(family["id"], cw1))
        verified = validate_success(api.verify_family(
            family["id"], cw2, verification_note="finally ok"))
        assert verified["status"] == "VERIFIED"
        assert verified["verified_at"], \
            "verified_at is stamped only by the terminal verify, not by loops"
        events, meta = validate_paginated(api.list_family_audit_events(
            family["id"], admin_headers, params={"limit": 100}))
        status_events = [e for e in events
                         if e["event_type"] == "STATUS_CHANGE"]
        # 1 create + 3 begin-review + 2 return-to-referral + 1 verify
        assert len(status_events) == 7

    def test_return_to_referral_lands_back_in_referred(self, api):
        """PRD §3.3: "Or the caseworker may return the family to referral —
        `UNDER_REVIEW → REFERRED` — a cyclic revision loop that may be exercised
        any number of times while the caseworker awaits further documentation."

        Design: Difficulty/non_linear_state_machine/family_review_cycle
        """
        campaign, agency = setup_campaign_intake_open()
        family = create_family(agency, campaign)
        add_child(family["id"], agency["id"])
        cw1 = make_caseworker_headers("cw_1")
        validate_success(api.begin_review(family["id"], cw1))
        returned = validate_success(api.return_to_referral(family["id"], cw1))
        assert returned["status"] == "REFERRED"
        assert returned.get("verified_at") in (None, ""), \
            "loop transitions never stamp verified_at"
        # The loop may re-enter review immediately.
        again = validate_success(api.begin_review(family["id"], cw1))
        assert again["status"] == "UNDER_REVIEW"


class TestFamilyTerminalLockdown:
    def test_rejected_family_rejects_further_transitions(self, api):
        """PRD §3.3: "The caseworker may reject the family — `UNDER_REVIEW →
        REJECTED`". From `REJECTED` the PRD defines no outgoing transition, and
        the error catalogue maps an undefined transition to `ERR_INVALID_STATE`
        (HTTP 409).

        Design: Corner/state_machines/family_terminal_rejected_locks_all_transitions
        """
        campaign, agency = setup_campaign_intake_open()
        family = create_family(agency, campaign)
        add_child(family["id"], agency["id"])
        cw1 = make_caseworker_headers("cw_1")
        validate_success(api.begin_review(family["id"], cw1))
        validate_success(api.reject_family(family["id"], cw1,
                                           verification_note="no"))
        res = api.verify_family(family["id"], make_caseworker_headers("cw_2"))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        assert get_family(family["id"])["status"] == "REJECTED"


class TestChildSubresource:
    def test_family_children_empty_list(self, api, admin_headers):
        """PRD §2.2: "The `data` field contains the resource object or an array
        of resource objects." PRD §4 defines GET /toy-drive/families/{id}/children
        as listing a family's children; a family with none returns an empty array.

        Design: Corner/endpoints/subresource_reverse_reachability_children
        """
        campaign, agency = setup_campaign_intake_open()
        family = create_family(agency, campaign)
        data, meta = validate_paginated(
            api.list_family_children(family["id"], admin_headers))
        assert data == []
        assert meta["total_count"] == 0
