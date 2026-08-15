"""Member record, contact OCC, eligibility reviews, grace period, and member
posture gating."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_eligibility_review,
    assert_member,
    assert_share_account,
    create_member,
    cure_review,
    enroll,
    flag_review,
    get_member,
    list_account_transactions,
    make_member_headers,
    open_account,
    patch_member_payload,
    set_clock,
    setup_charter,
    setup_member_in_grace,
    setup_member_with_primary,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

FILER = TEST_USERS["membership_officer_headers"]
DECIDER = TEST_USERS["membership_officer_2_headers"]
CO1 = TEST_USERS["compliance_officer_headers"]
CO2 = TEST_USERS["compliance_officer_2_headers"]
CO3 = TEST_USERS["compliance_officer_3_headers"]
OPS = TEST_USERS["operations_officer_headers"]


class TestMemberRecord:
    def test_member_computed_fields_tenure_and_qualifying_balance(self, api):
        """PRD §3.4: "The `tenure_months` of a member is the number of full
        calendar months between `membership_effective_date` and the current
        date: twelve times the calendar-year difference plus the calendar-month
        difference, reduced by one when the current day-of-month precedes the
        effective date's day-of-month. The `qualifying_balance_cents` is the
        point-in-time sum of `balance_cents` across the member's OPEN share
        accounts."
        PRD §3.4: "The materialized `tier` — STANDARD at admission — changes
        only through a tier review performed by an `OperationsOfficer`."

        Design: Corner/entities/member_computed_fields_tenure_and_qualifying_balance
        """
        set_clock("2025-06-15")
        ctx = setup_member_with_primary(deposit=100_000, name="Computed Kim")
        member_id = ctx["member_id"]
        supplemental = open_account(member_id, account_type="SUPPLEMENTAL",
                                    initial_deposit_cents=50_000)

        set_clock("2026-07-01")
        validate_success(api.close_share_account(supplemental["id"], FILER))

        set_clock("2026-08-01")
        member = validate_success(api.get_member(member_id, FILER))
        assert_member(member)
        assert member["membership_effective_date"] == "2025-06-15"
        assert member["tenure_months"] == 13, (
            "2025-06-15 -> 2026-08-01: 12 + 2 - 1 because day 01 precedes "
            "day 15")
        assert member["qualifying_balance_cents"] == 100_000, (
            "The closed SUPPLEMENTAL account is excluded from the sum")
        assert member["tier"] == "STANDARD", (
            "The materialized tier never changes without a tier review")

    def test_get_member_not_found_returns_404(self, api):
        """PRD §2.6: "Path identifiers and body foreign-key references must
        exist, validated left to right, otherwise `ERR_NOT_FOUND` (404). This
        tier applies to all endpoints."

        Design: Corner/entities/get_member_not_found_returns_404
        """
        resp = api.get_member(NON_EXISTENT_UUID, FILER)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_member_role_cannot_read_other_members_record(self, api):
        """PRD §2.1: "Wherever the `Member` role is permitted — reading a
        member record, that member's share accounts, their transactions, their
        dividend payments, their ballots, and casting a ballot — the
        `X-User-ID` must equal the `id` of the member addressed by the path
        (for share-account paths, the member who owns the account). A member
        touching another member's resources is rejected with
        `ERR_NOT_RESOURCE_OWNER`"

        Design: Corner/validations/member_role_cannot_read_other_members_record
        """
        _charter, seg_ids = setup_charter()
        m1 = create_member(segment_id=seg_ids[0], name="Owner One")
        m2 = create_member(segment_id=seg_ids[0], name="Owner Two",
                           date_of_birth="1990-02-02")

        other = api.get_member(m2, make_member_headers(m1))
        validate_error(other, ApiErrorId.ERR_NOT_RESOURCE_OWNER)

        own = validate_success(api.get_member(m1, make_member_headers(m1)))
        assert own["full_name"] == "Owner One"


class TestMemberPatchOcc:
    def test_occ_member_patch_stale_version(self, api):
        """PRD §2.7: "A request updating a member profile (`PATCH
        /credit-union/members/{id}`) must carry `expected_member_version`, the
        member `version` the caller last read; tier reviews and eligibility
        cascades also advance the member's version, and a mismatch is rejected
        with `ERR_STALE_MEMBER_VERSION` (HTTP 412) so a profile update never
        overwrites a member record the caller has not observed."
        PRD §3.4: "Updating a member's contact fields — `mailing_address`,
        `email`, and `phone` — requires `expected_member_version` matching the
        member's current `version`; a stale read is rejected with
        `ERR_STALE_MEMBER_VERSION` per §2.7, and a successful update increments
        the version."

        Design: Corner/cross_cutting_layers/occ_member_patch_stale_version
        """
        set_clock("2026-08-01")
        _charter, seg_ids = setup_charter()
        member_id = create_member(segment_id=seg_ids[0], name="Occ Otto")
        before = validate_success(api.get_member(member_id, FILER))
        v1 = before["version"]

        patched = validate_success(api.patch_member(
            member_id,
            patch_member_payload(v1, mailing_address="1 Main St"),
            FILER))
        assert patched["mailing_address"] == "1 Main St"
        assert patched["version"] == v1 + 1, (
            "A successful update increments the version")

        stale = api.patch_member(
            member_id,
            patch_member_payload(v1, mailing_address="2 Main St"),
            FILER)
        validate_error(stale, ApiErrorId.ERR_STALE_MEMBER_VERSION)

        after = validate_success(api.get_member(member_id, FILER))
        assert after["mailing_address"] == "1 Main St", (
            "The rejected patch never overwrote the stored address")


class TestEligibilityReviews:
    def test_review_cure_returns_member_to_active(self, api):
        """PRD §3.9: "A successful cure moves the review to CURED — terminal —
        records the decider as `decided_by_user_id`, returns the member to
        ACTIVE, clears `grace_end_date` to null if it was set, and preserves an
        optional `resolution_note`."
        PRD §3.9: "When the member is ACTIVE, the review is created OPEN, the
        flagger's `X-User-ID` is recorded, and the member moves to
        INELIGIBLE_UNDER_REVIEW."

        Design: Corner/state_machines/review_cure_returns_member_to_active
        """
        set_clock("2026-08-01")
        _charter, seg_ids = setup_charter()
        member_id = create_member(segment_id=seg_ids[0], name="Cure Cathy")
        review = flag_review(member_id)
        assert review["status"] == "OPEN"
        assert review["reason"] == "MANUAL_FLAG"
        assert review["flagged_by_user_id"] == "co-1"
        assert get_member(member_id)["status"] == "INELIGIBLE_UNDER_REVIEW"

        cured = validate_success(api.cure_eligibility_review(
            review["id"], {"resolution_note": "employment re-verified"}, CO2))
        assert_eligibility_review(cured)
        assert cured["status"] == "CURED"
        assert cured["decided_by_user_id"] == "co-2"
        assert cured["resolution_note"] == "employment re-verified"

        member = validate_success(api.get_member(member_id, CO1))
        assert member["status"] == "ACTIVE"

    def test_review_cure_after_terminal_rejected(self, api):
        """PRD §3.9: "The review must be OPEN — anything else fails with
        `ERR_REVIEW_INVALID_STATE`"
        PRD §3.9: "A CONFIRMED_INELIGIBLE review can never itself be cured, so
        the late cure within grace takes a deliberate two-step"

        Design: Corner/state_machines/review_cure_after_terminal_rejected
        """
        set_clock("2026-08-01")
        ctx = setup_member_in_grace(name="Terminal Tess")
        member_id = ctx["member_id"]
        assert get_member(member_id)["status"] == "GRACE_PERIOD"

        resp = api.cure_eligibility_review(
            ctx["review_id"], {"resolution_note": "too late"}, CO3)
        validate_error(resp, ApiErrorId.ERR_REVIEW_INVALID_STATE)
        assert get_member(member_id)["status"] == "GRACE_PERIOD", (
            "The rejected cure changes nothing")

    def test_segregation_flagger_cannot_confirm_own_review(self, api):
        """PRD §2.10: "the officer who flags an eligibility review
        (`flagged_by_user_id`) may never be the one who cures or confirms it.
        A deciding user whose `X-User-ID` equals the filer's or flagger's is
        rejected with `ERR_SEGREGATION_OF_DUTIES` (403)."
        PRD §3.9: "Confirmation moves the review to CONFIRMED_INELIGIBLE —
        terminal — moves the member to GRACE_PERIOD, and sets `grace_end_date`
        to ninety days after the current clock date"

        Design: Corner/validations/segregation_flagger_cannot_confirm_own_review
        """
        set_clock("2026-08-01")
        _charter, seg_ids = setup_charter()
        member_id = create_member(segment_id=seg_ids[0], name="SoD Sam")
        review = flag_review(member_id)  # flagged by co-1

        own = api.confirm_ineligible(review["id"], CO1)
        validate_error(own, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        confirmed = validate_success(api.confirm_ineligible(review["id"], CO2))
        assert confirmed["status"] == "CONFIRMED_INELIGIBLE"
        assert confirmed["decided_by_user_id"] == "co-2"
        member = get_member(member_id)
        assert member["status"] == "GRACE_PERIOD"
        assert member["grace_end_date"] == "2026-10-30", (
            "grace_end_date is ninety days after the confirmation date "
            "2026-08-01")


class TestMemberListing:
    def test_filtered_list_scoping(self, api):
        """PRD §3.4: "The member list can be filtered by `status`, `tier`,
        `segment_id`, `sponsor_member_id`, or `application_id`."
        PRD §2.3: "Unless otherwise specified, every list endpoint returns its
        resources sorted by creation timestamp in ascending order."

        Design: Corner/endpoints/filtered_list_scoping
        """
        set_clock("2026-08-01")
        _charter, seg_ids = setup_charter()
        m1 = create_member(segment_id=seg_ids[0], name="Active Al")
        m2 = create_member(segment_id=seg_ids[0], name="Grace Gina",
                           date_of_birth="1990-02-02")
        review = flag_review(m2)
        validate_success(api.confirm_ineligible(review["id"], CO2))

        grace, gmeta = validate_paginated(api.list_members(
            CO1, params={"status": "GRACE_PERIOD"}))
        assert gmeta["total_count"] == 1
        assert grace[0]["id"] == m2

        active, ameta = validate_paginated(api.list_members(
            CO1, params={"status": "ACTIVE"}))
        assert ameta["total_count"] == 1
        assert active[0]["id"] == m1


class TestAccountOpeningMemberPosture:
    def _setup_grace_member(self, api):
        set_clock("2026-07-01")
        _charter, seg_ids = setup_charter()
        member_id = create_member(segment_id=seg_ids[0], name="Gated Gail",
                                  date_of_birth="1994-04-04")
        set_clock("2026-08-01")
        review = flag_review(member_id)
        validate_success(api.confirm_ineligible(review["id"], CO2))
        return member_id

    def test_share_account_open_blocked_in_grace_period(self, api):
        """PRD §2.11: "Account opening, product enrollment, ballot casting, and
        the creation of a manual eligibility review all require the member to
        be ACTIVE (for manual review creation, GRACE_PERIOD is also accepted,
        enabling late cure); a member not in an accepted posture is rejected
        with `ERR_MEMBER_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/share_account_open_gated_by_member_status
        """
        member_id = self._setup_grace_member(api)
        assert get_member(member_id)["status"] == "GRACE_PERIOD"

        resp = api.create_share_account(
            {"member_id": member_id, "account_type": "PRIMARY",
             "initial_deposit_cents": 500},
            FILER)
        validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_ACTIVE)

    def test_share_account_open_succeeds_after_late_cure(self, api):
        """PRD §3.9: "A CONFIRMED_INELIGIBLE review can never itself be cured,
        so the late cure within grace takes a deliberate two-step: a fresh
        manual review is opened while the member is GRACE_PERIOD — accepted
        without disturbing the member's posture, per above — and that new
        review is immediately cured, which clears the `grace_end_date` and
        restores the member to ACTIVE."
        PRD §3.5: "its opening deposit must be at least the charter's
        `par_value_cents`, with a deposit of exactly par qualifying"

        Design: Difficulty/cross_entity_state_dependency/share_account_open_gated_by_member_status
        """
        member_id = self._setup_grace_member(api)

        late_review = flag_review(member_id)  # accepted while GRACE_PERIOD
        assert late_review["status"] == "OPEN"
        assert get_member(member_id)["status"] == "GRACE_PERIOD", (
            "The fresh review leaves the grace posture undisturbed")

        cured = validate_success(api.cure_eligibility_review(
            late_review["id"],
            {"resolution_note": "documents re-verified"}, CO2))
        assert cured["status"] == "CURED"
        member = get_member(member_id)
        assert member["status"] == "ACTIVE"
        assert member["grace_end_date"] is None

        account = validate_success(api.create_share_account(
            {"member_id": member_id, "account_type": "PRIMARY",
             "initial_deposit_cents": 500},
            FILER), 201)
        assert_share_account(account)
        assert account["status"] == "OPEN"
        assert account["balance_cents"] == 500, "Exact-par opening deposit"


class TestGraceClosureCancellation:
    def test_scheduled_grace_closure_cancelled_by_late_cure(self, api):
        """PRD §3.9: "that new review is immediately cured, which clears the
        `grace_end_date` and restores the member to ACTIVE."
        PRD §2.5: "every GRACE_PERIOD member whose `grace_end_date` has been
        reached is closed with the forced-closure cascade of §3.9"

        Design: Corner/cross_cutting_layers/scheduled_grace_closure_cancelled_by_late_cure
        """
        set_clock("2026-08-01")
        ctx = setup_member_in_grace(name="Grace Gus")
        member_id = ctx["member_id"]
        assert get_member(member_id)["grace_end_date"] == "2026-10-30"

        set_clock("2026-10-15")
        late_review = flag_review(member_id)
        cure_review(late_review["id"],
                    resolution_note="eligibility re-established")

        mid = get_member(member_id)
        assert mid["status"] == "ACTIVE"
        assert mid["grace_end_date"] is None, (
            "The late cure clears the scheduled closure date")

        set_clock("2026-11-15")  # past the original grace_end_date
        end = get_member(member_id)
        assert end["status"] == "ACTIVE", (
            "Sweeping past the cancelled grace date leaves the member ACTIVE")


class TestGraceExpiryCascade:
    def _setup_grace_with_assets(self, api):
        """Member approved 2025-06-01 with PRIMARY 500,000 + SUPPLEMENTAL
        50,000 and a MONEY_MARKET enrollment funded by the PRIMARY account;
        confirmed ineligible on 2026-08-01 -> GRACE_PERIOD ending 2026-10-30."""
        set_clock("2025-06-01")
        _charter, seg_ids = setup_charter()
        member_id = create_member(segment_id=seg_ids[0], name="Cascade Cal",
                                  date_of_birth="1987-07-07")
        primary = open_account(member_id, initial_deposit_cents=500_000)
        supplemental = open_account(member_id, account_type="SUPPLEMENTAL",
                                    initial_deposit_cents=50_000)
        set_clock("2026-07-01")
        enrollment = enroll(member_id, primary["id"])
        assert enrollment["tier_at_enrollment"] == "SELECT", (
            "Precondition: current balance 550,000 and tenure 13 qualify")

        set_clock("2026-08-01")
        review = flag_review(member_id)
        validate_success(api.confirm_ineligible(review["id"], CO2))
        return member_id, primary, supplemental, enrollment

    def test_grace_expiry_boundary_and_member_closure(self, api):
        """PRD §3.9: "Confirmation moves the review to CONFIRMED_INELIGIBLE —
        terminal — moves the member to GRACE_PERIOD, and sets `grace_end_date`
        to ninety days after the current clock date: the member's statutory
        window to cure."
        PRD §2.5: "Each clock set runs the epoch sweep: every APPROVED charter
        amendment whose `effective_date` has been reached becomes EFFECTIVE
        with the cascades of §3.2, and every GRACE_PERIOD member whose
        `grace_end_date` has been reached is closed with the forced-closure
        cascade of §3.9."

        Design: Difficulty/transitive_cascade/grace_expiry_cascade_member_account_enrollment
        """
        member_id, _p, _s, _e = self._setup_grace_with_assets(api)

        set_clock("2026-10-29")
        before = get_member(member_id)
        assert before["status"] == "GRACE_PERIOD"
        assert before["grace_end_date"] == "2026-10-30", (
            "One day before grace end the sweep has not fired")

        set_clock("2026-10-30")
        after = get_member(member_id)
        assert after["status"] == "CLOSED_INELIGIBLE", (
            "Reaching grace_end_date closes the member")

    def test_grace_expiry_cascades_to_accounts_and_enrollments(self, api):
        """PRD §3.9: "the member's OPEN share accounts are walked from the
        oldest `opened_date` forward, each account is CLOSED with closure
        reason FORCED_INELIGIBILITY, a SYSTEM ShareTransaction of kind
        CLOSURE_DISBURSEMENT for the full balance is posted on the current date
        so the account's `balance_cents` falls to zero, and every ACTIVE
        ProductEnrollment funded by such an account is closed with closure
        reason FORCED_ACCOUNT_CLOSURE."

        Design: Difficulty/transitive_cascade/grace_expiry_cascade_member_account_enrollment
        """
        member_id, primary, supplemental, enrollment = \
            self._setup_grace_with_assets(api)

        set_clock("2026-10-30")
        assert get_member(member_id)["status"] == "CLOSED_INELIGIBLE"

        accounts, _meta = validate_paginated(
            api.list_member_share_accounts(member_id, CO1))
        assert accounts[0]["id"] == primary["id"]
        assert accounts[1]["id"] == supplemental["id"]
        for row in accounts:
            assert row["status"] == "CLOSED"
            assert row["closure_reason"] == "FORCED_INELIGIBILITY"
            assert row["balance_cents"] == 0, (
                "The closure disbursement drives the balance to zero")
            assert row["closed_date"] == "2026-10-30"

        ledger = list_account_transactions(primary["id"])
        closing = ledger[-1]
        assert closing["kind"] == "CLOSURE_DISBURSEMENT"
        assert closing["origin"] == "SYSTEM"
        assert closing["amount_cents"] == 500_000
        assert closing["posted_date"] == "2026-10-30"

        enr = validate_success(
            api.get_product_enrollment(enrollment["id"], CO1))
        assert enr["status"] == "CLOSED"
        assert enr["closure_reason"] == "FORCED_ACCOUNT_CLOSURE", (
            "The PRIMARY account's closure itself closes the funded "
            "enrollment (depth-3 cascade)")
