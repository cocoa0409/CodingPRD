"""Guest and host registration, identity review and the live risk score."""

from test_helpers import (
    ApiErrorId,
    assertions,
    constants,
    factories,
    fixtures,
    types,
    validate_error,
    validate_success,
)
from test_helpers.test_users import (
    ADJUDICATOR,
    COMPLIANCE_OFFICER,
    PLATFORM_ADMIN,
    make_guest_headers,
)


def test_registering_a_guest_returns_every_declared_default(api):
    """A brand-new account starts clean, unverified and already scored.

    The score is not deferred to a later read: the baseline is applied inside the
    creating request, which is why the tier is available to a booking made
    immediately afterwards.

    PRD: "A freshly registered guest begins with `payment_risk_signal` reading `CLEAN`, `chargeback_count` at zero, `verification_state` reading `UNVERIFIED`, every derived counter at zero, and `version` at 1."
    PRD: "Its risk position is computed immediately from the baseline described below, which for a brand-new account yields a `risk_score` of 35 and a `risk_tier` of `ELEVATED`."
    PRD: "`created_at` is the ISO 8601 UTC instant, with three fractional digits, at which the row was first written."

    Design: Corner/entities/guest_creation_returns_declared_defaults_and_system_fields
    """
    fixtures.set_clock(api, constants.PROCESS_START_UTC)

    guest = validate_success(
        api.create_guest(
            PLATFORM_ADMIN,
            **factories.guest_payload(
                full_name="Corner Guest One", email="corner1@guest.test"
            )
        ),
        expected_status=201,
    )

    types.assert_is_guest(guest)
    assertions.assert_fields(
        guest,
        "guest",
        full_name="Corner Guest One",
        email="corner1@guest.test",
        country_code="US",
        verification_state="UNVERIFIED",
        accepted_doc_count=0,
        accepted_gov_id_count=0,
        completed_stay_count=0,
        substantiated_incident_count=0,
        escalated_incident_count=0,
        approved_claim_count=0,
        payment_risk_signal="CLEAN",
        chargeback_count=0,
        risk_score=35,
        risk_tier="ELEVATED",
        deposit_held_cents=0,
        active_blocklist_scope_count=0,
        version=1,
    )
    assert guest["created_at"].startswith("2026-08-01T00:00:00"), (
        "created_at must be stamped from the logical clock reading "
        "2026-08-01T00:00:00Z, got {0!r}".format(guest["created_at"])
    )


def test_guest_list_reports_total_count_and_has_more_across_two_windows(api):
    """Three guests are paged two at a time, then filtered by tier.

    total_count must describe the filtered set before the window is applied, so
    it stays at three across both windows while the item count and has_more move.

    PRD: "The `meta` block of a list response carries `limit`, `offset`, `total_count` and `has_more`, where `total_count` is the number of rows matching the filters before the window is applied and `has_more` is true whenever rows remain beyond the current window."
    PRD: "Guests can be read individually, or listed with optional `risk_tier` and `verification_state` filters."

    Design: Corner/entities/guest_listing_paginates_with_total_count_and_has_more
    """
    fixtures.set_clock(api, constants.PROCESS_START_UTC)
    fixtures.create_guest(api, full_name="Page Guest A", email="page-a@guest.test")
    fixtures.create_guest(api, full_name="Page Guest B", email="page-b@guest.test")
    fixtures.create_guest(
        api, full_name="Page Guest C", email="page-c@guest.test", country_code="CA"
    )

    first_page, _ = assertions.assert_page(
        api.list_guests(PLATFORM_ADMIN, limit=2, offset=0),
        total_count=3,
        has_more=True,
        limit=2,
        offset=0,
    )
    assert len(first_page) == 2, (
        "a limit of 2 must return exactly 2 items, got {0}".format(len(first_page))
    )
    assertions.assert_ascending_by_created_at(first_page, "guests")

    second_page, _ = assertions.assert_page(
        api.list_guests(PLATFORM_ADMIN, limit=2, offset=2),
        total_count=3,
        has_more=False,
        limit=2,
        offset=2,
    )
    assert len(second_page) == 1, (
        "the tail window must return the single remaining guest, got {0}".format(
            len(second_page)
        )
    )

    filtered, _ = assertions.assert_page(
        api.list_guests(PLATFORM_ADMIN, risk_tier="ELEVATED", limit=10, offset=0),
        total_count=3,
    )
    assert len(filtered) == 3, (
        "every fresh guest scores 35 and therefore bands ELEVATED, got {0} rows".format(
            len(filtered)
        )
    )


def test_risk_fields_smuggled_into_a_guest_creation_are_ignored(api):
    """A client cannot pre-set its own score or verification state.

    The body asks for a verified guest at zero risk; the server must derive both
    fields from the aggregates it maintains itself, which for a new account with
    no documents means UNVERIFIED at the 35-point baseline.

    PRD: "A freshly registered guest begins with `payment_risk_signal` reading `CLEAN`, `chargeback_count` at zero, `verification_state` reading `UNVERIFIED`, every derived counter at zero, and `version` at 1."
    PRD: "Its risk position is computed immediately from the baseline described below, which for a brand-new account yields a `risk_score` of 35 and a `risk_tier` of `ELEVATED`."
    PRD: "A guest's `verification_state` is a function of that guest's documents alone, evaluated top down with the first matching clause winning."

    Design: Corner/entities/guest_risk_score_input_ignored_on_create
    """
    fixtures.set_clock(api, constants.PROCESS_START_UTC)

    guest = validate_success(
        api.create_guest(
            PLATFORM_ADMIN,
            full_name="Sneaky Input",
            email="sneaky@guest.test",
            country_code="US",
            risk_score=0,
            verification_state="VERIFIED",
        ),
        expected_status=201,
    )

    assertions.assert_fields(
        guest,
        "guest",
        risk_score=35,
        risk_tier="ELEVATED",
        verification_state="UNVERIFIED",
        accepted_doc_count=0,
    )


def test_host_system_fields_are_minted_from_the_logical_clock(api):
    """The stamps on a new host come from the logical clock, not from real time.

    The clock is deliberately moved off its starting instant before the host is
    registered, so a stamp taken from wall-clock time could not coincide with the
    asserted value.

    PRD: "Nothing in this system reads the wall clock."
    PRD: "A freshly registered host begins with `payout_hold` false and with `settled_claim_count`, `denied_claim_count` and `total_recovered_cents` all at zero, and its `version` at 1."
    PRD: "`updated_at` is the same format and is refreshed on every mutation of the row."

    Design: Corner/entities/host_system_fields_are_server_minted_from_logical_clock
    """
    fixtures.set_clock(api, "2026-08-04T09:30:00Z")

    host = validate_success(
        api.create_host(
            PLATFORM_ADMIN,
            **factories.host_payload(
                legal_name="Clock Stamped Stays", email="clockhost@stays.test"
            )
        ),
        expected_status=201,
    )

    types.assert_is_host(host)
    assert host["created_at"].startswith("2026-08-04T09:30:00"), (
        "created_at must read the logical clock instant 2026-08-04T09:30:00Z, "
        "got {0!r}".format(host["created_at"])
    )
    assert host["updated_at"] == host["created_at"], (
        "an unmutated host must carry updated_at equal to created_at, got {0!r} "
        "and {1!r}".format(host["updated_at"], host["created_at"])
    )
    assertions.assert_fields(
        host,
        "host",
        version=1,
        payout_hold=False,
        settled_claim_count=0,
        denied_claim_count=0,
        total_recovered_cents=0,
    )


def test_guest_email_uniqueness_is_case_insensitive_and_per_table(api):
    """The same address in different case collides on guests but not against hosts.

    Two separate uniqueness domains are asserted in one test: the second guest is
    refused, and a host registered on the identical address is accepted.

    PRD: "In both cases the address must be unused: emails are compared case-insensitively across guest rows and, separately, across host rows, and a collision is refused with `ERR_EMAIL_ALREADY_REGISTERED`."

    Design: Corner/errors/guest_email_already_registered_rejected
    """
    fixtures.set_clock(api, constants.PROCESS_START_UTC)
    original = fixtures.create_guest(
        api, full_name="Original Guest", email="dup@guest.test"
    )

    validate_error(
        api.create_guest(
            PLATFORM_ADMIN,
            **factories.guest_payload(
                full_name="Copycat Guest", email="DUP@GUEST.TEST", country_code="CA"
            )
        ),
        ApiErrorId.ERR_EMAIL_ALREADY_REGISTERED,
        expected_status=409,
    )

    items, _ = assertions.assert_page(api.list_guests(PLATFORM_ADMIN), total_count=1)
    assertions.assert_ids_equal(items, [original["id"]], "guests")

    validate_success(
        api.create_host(
            PLATFORM_ADMIN,
            **factories.host_payload(legal_name="Same Address LLC", email="dup@guest.test")
        ),
        expected_status=201,
    )


def test_risk_profile_read_reports_the_same_terms_as_the_guest_row(api):
    """The computed read must agree with the row it summarises, term by term.

    A WATCH signal is recorded first so the profile has something to attribute:
    the baseline 35 plus the 12-point watch penalty is 47, still inside the
    ELEVATED band, and the profile is read by an adjudicator rather than by the
    admin who recorded the signal.

    PRD: "A dedicated computed read exposes the live position term by term, so a change can be attributed to a specific cascade."
    PRD: "It returns `risk_score`, `risk_tier`, `verification_state`, `completed_stay_count`, `substantiated_incident_count`, `escalated_incident_count`, `approved_claim_count`, `chargeback_count` and `active_blocklist_scope_count`."
    PRD: "Add the payment-signal penalty: nothing for `CLEAN`, 12 points for `WATCH`, 30 points for `ADVERSE`."

    Design: Corner/endpoints/risk_profile_read_matches_guest_aggregates
    """
    fixtures.set_clock(api, constants.PROCESS_START_UTC)
    guest = fixtures.create_guest(api, full_name="Watch Guest", email="watch@guest.test")
    assertions.assert_guest_risk(guest, 35, "ELEVATED")

    signalled = validate_success(
        api.record_payment_signal(
            guest["id"],
            PLATFORM_ADMIN,
            payment_risk_signal="WATCH",
            chargeback_count=0,
        )
    )
    assertions.assert_guest_risk(signalled, 47, "ELEVATED")

    profile = validate_success(api.get_guest_risk_profile(guest["id"], ADJUDICATOR))
    assertions.assert_fields(
        profile,
        "risk_profile",
        risk_score=47,
        risk_tier="ELEVATED",
        verification_state="UNVERIFIED",
        completed_stay_count=0,
        substantiated_incident_count=0,
        escalated_incident_count=0,
        approved_claim_count=0,
        chargeback_count=0,
        active_blocklist_scope_count=0,
    )

    reread = validate_success(api.get_guest(guest["id"], PLATFORM_ADMIN))
    assertions.assert_guest_risk(reread, 47, "ELEVATED")


def test_officer_acceptance_stamps_the_reviewer_and_moves_the_counters(api):
    """A single accepted government ID is recorded against the reviewing officer.

    One document alone cannot satisfy the two-document threshold, so the guest
    stays UNVERIFIED even though its accepted counters both moved — the counters
    and the state are separate facts.

    PRD: "It sets `reviewed_by_user_id` to the officer's `X-User-ID` and moves `review_state` from `PENDING` to `ACCEPTED`."
    PRD: "That raises the guest's `accepted_doc_count` by 1, and also `accepted_gov_id_count` by 1 when `doc_type` is `GOVERNMENT_ID`."
    PRD: "Note the threshold shape: two accepted documents are needed in total and at least one of them must be a government ID, so two accepted selfies never reach `VERIFIED`."

    Design: Corner/rbac/compliance_officer_reviews_identity_document
    """
    fixtures.set_clock(api, constants.PROCESS_START_UTC)
    guest = fixtures.create_guest(api, full_name="Doc Guest", email="doc@guest.test")
    document = validate_success(
        api.create_identity_document(
            make_guest_headers(guest["id"]),
            **factories.government_id_payload(
                guest["id"],
                document_ref="blob/gov-1",
                expires_on="2030-01-01T00:00:00Z",
            )
        ),
        expected_status=201,
    )
    assertions.assert_fields(document, "identity_document", review_state="PENDING")

    reviewed = validate_success(
        api.review_identity_document(
            document["id"], COMPLIANCE_OFFICER, decision="ACCEPT"
        )
    )

    types.assert_is_identity_document(reviewed)
    assertions.assert_fields(
        reviewed,
        "identity_document",
        review_state="ACCEPTED",
        reviewed_by_user_id="co-1",
        reject_reason_code=None,
    )

    guest = validate_success(api.get_guest(guest["id"], PLATFORM_ADMIN))
    assertions.assert_fields(
        guest,
        "guest",
        accepted_doc_count=1,
        accepted_gov_id_count=1,
        verification_state="UNVERIFIED",
    )
    assertions.assert_guest_risk(guest, 35, "ELEVATED")


def test_a_guest_may_not_rule_on_its_own_document(api):
    """Self-review is refused on role membership, before ownership is consulted.

    The acting principal owns the document, so an ownership-first implementation
    would let it through; the review endpoint simply does not authorise `Guest`,
    which is why the refusal is the role-level one rather than the owner-level one.

    PRD: "If `X-User-Role` holds a string that is not one of the five recognised roles, or holds a recognised role that the target endpoint does not authorise, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD: "Role membership is checked before ownership: an unrecognised or unauthorised role never reaches the ownership comparison."
    PRD: "The row lands in `review_state` `PENDING` with `reject_reason_code` and `reviewed_by_user_id` null and its own `version` at 1; the guest's `verification_state` and `risk_score` are re-derived on the spot and the guest's `version` increases by 1."

    Design: Corner/rbac/guest_cannot_review_own_identity_document
    """
    fixtures.set_clock(api, constants.PROCESS_START_UTC)
    guest = fixtures.create_guest(
        api, full_name="Self Review Guest", email="selfreview@guest.test"
    )
    guest_headers = make_guest_headers(guest["id"])
    document = validate_success(
        api.create_identity_document(
            guest_headers,
            **factories.selfie_payload(guest["id"], document_ref="blob/selfie-1")
        ),
        expected_status=201,
    )

    validate_error(
        api.review_identity_document(document["id"], guest_headers, decision="ACCEPT"),
        ApiErrorId.ERR_UNAUTHORIZED,
        expected_status=403,
    )

    unchanged = validate_success(api.get_identity_document(document["id"], guest_headers))
    assertions.assert_fields(
        unchanged,
        "identity_document",
        review_state="PENDING",
        reviewed_by_user_id=None,
    )

    guest = validate_success(api.get_guest(guest["id"], PLATFORM_ADMIN))
    assertions.assert_fields(
        guest,
        "guest",
        accepted_doc_count=0,
        verification_state="PENDING_REVIEW",
    )


def test_second_acceptance_cascades_from_document_to_tier(api):
    """One acceptance moves four things: counters, state, score and band.

    The guest arrives at the trigger holding one accepted government ID and one
    pending selfie, so it reads PENDING_REVIEW at the 35-point baseline. Accepting
    the selfie is the only request made, yet it must raise both accepted counters,
    flip the verification state to VERIFIED, earn the 15-point verification credit
    and re-band 20 into LOW — nothing here is requested directly.

    PRD: "Acceptance is the first link of the verification cascade, and each subsequent link fires because the previous field moved rather than because the request asked for it."
    PRD: "The changed counters re-derive `verification_state`, which flips to `VERIFIED` once the two-document, one-government-ID threshold is met."
    PRD: "The new `VERIFIED` value re-runs the risk score, which now earns the verification credit, so `risk_score` drops and `risk_tier` may re-band."
    PRD: "Subtract 15 points when `verification_state` reads `VERIFIED`, and nothing otherwise."
    PRD: "`risk_tier` is then read off `risk_score`, never off the pre-clamp sum, using bands inclusive at both ends: `LOW` from 0 through 24, `ELEVATED` from 25 through 49, `HIGH` from 50 through 74, and `CRITICAL` from 75 through 100."

    Design: Difficulty/transitive_cascade/document_acceptance_cascade_rebands_guest_risk_tier
    """
    fixtures.set_clock(api, constants.PROCESS_START_UTC)
    guest = fixtures.create_guest(api, full_name="Dana Reyes", email="dana@guest.test")
    guest_headers = make_guest_headers(guest["id"])

    gov = validate_success(
        api.create_identity_document(
            guest_headers,
            **factories.government_id_payload(
                guest["id"],
                document_ref="gov-dana-1",
                expires_on="2030-01-01T00:00:00Z",
            )
        ),
        expected_status=201,
    )
    validate_success(
        api.review_identity_document(gov["id"], COMPLIANCE_OFFICER, decision="ACCEPT")
    )
    selfie = validate_success(
        api.create_identity_document(
            guest_headers,
            **factories.selfie_payload(
                guest["id"],
                document_ref="selfie-dana-1",
                expires_on="2030-01-01T00:00:00Z",
            )
        ),
        expected_status=201,
    )

    before = validate_success(api.get_guest(guest["id"], PLATFORM_ADMIN))
    assertions.assert_fields(before, "guest", verification_state="PENDING_REVIEW")
    assertions.assert_guest_risk(before, 35, "ELEVATED")

    accepted = validate_success(
        api.review_identity_document(selfie["id"], COMPLIANCE_OFFICER, decision="ACCEPT")
    )
    assertions.assert_fields(
        accepted,
        "identity_document",
        review_state="ACCEPTED",
        reviewed_by_user_id="co-1",
        reject_reason_code=None,
    )

    after = validate_success(api.get_guest(guest["id"], PLATFORM_ADMIN))
    assertions.assert_fields(
        after,
        "guest",
        accepted_doc_count=2,
        accepted_gov_id_count=1,
        verification_state="VERIFIED",
    )
    assertions.assert_guest_risk(after, 20, "LOW")
    assert after["risk_score"] == assertions.guest_risk_score(
        verification_state="VERIFIED"
    ), "the verified guest's score must be the baseline less the verification credit"


def test_the_cascade_waits_for_the_threshold_and_bumps_both_versions(api):
    """Until the second acceptance lands, none of the downstream links fire.

    This reads the intermediate position deliberately: an accepted government ID
    already sits on the guest, both accepted counters have moved, and yet the
    verification state and the score are exactly where a brand-new account leaves
    them. The trigger then advances the document's version and the guest's version
    by one step each.

    PRD: "If `accepted_gov_id_count` is at least 1 *and* `accepted_doc_count` is at least 2, the state is `VERIFIED`."
    PRD: "Otherwise, if the guest holds any document still in `PENDING`, the state is `PENDING_REVIEW`."
    PRD: "Both the document's `version` and the guest's `version` increase by 1."
    PRD: "A dedicated computed read exposes the live position term by term, so a change can be attributed to a specific cascade."

    Design: Difficulty/transitive_cascade/document_acceptance_cascade_rebands_guest_risk_tier
    """
    fixtures.set_clock(api, constants.PROCESS_START_UTC)
    guest = fixtures.create_guest(api, full_name="Dana Reyes", email="dana@guest.test")
    guest_headers = make_guest_headers(guest["id"])

    gov = validate_success(
        api.create_identity_document(
            guest_headers,
            **factories.government_id_payload(
                guest["id"],
                document_ref="gov-dana-1",
                expires_on="2030-01-01T00:00:00Z",
            )
        ),
        expected_status=201,
    )
    validate_success(
        api.review_identity_document(gov["id"], COMPLIANCE_OFFICER, decision="ACCEPT")
    )
    selfie = validate_success(
        api.create_identity_document(
            guest_headers,
            **factories.selfie_payload(
                guest["id"],
                document_ref="selfie-dana-1",
                expires_on="2030-01-01T00:00:00Z",
            )
        ),
        expected_status=201,
    )

    halfway = validate_success(api.get_guest(guest["id"], PLATFORM_ADMIN))
    assertions.assert_fields(
        halfway,
        "guest",
        accepted_doc_count=1,
        accepted_gov_id_count=1,
        verification_state="PENDING_REVIEW",
    )
    assertions.assert_guest_risk(halfway, 35, "ELEVATED")

    accepted = validate_success(
        api.review_identity_document(selfie["id"], COMPLIANCE_OFFICER, decision="ACCEPT")
    )
    assertions.assert_version_advanced_by(selfie, accepted, 1, "identity_document")

    after = validate_success(api.get_guest(guest["id"], PLATFORM_ADMIN))
    assertions.assert_version_advanced_by(halfway, after, 1, "guest")

    profile = validate_success(api.get_guest_risk_profile(guest["id"], ADJUDICATOR))
    assertions.assert_fields(
        profile,
        "risk_profile",
        verification_state="VERIFIED",
        risk_score=20,
        risk_tier="LOW",
    )


def test_the_third_chargeback_lands_exactly_on_the_high_floor(api):
    """Two chargebacks stay ELEVATED; the third puts the score on 50 and rebands.

    Fifty is the inclusive floor of HIGH, so an implementation using a strict
    comparison would leave this guest ELEVATED. Fifty is also below the CRITICAL
    floor, so no automatic ban may fire.

    PRD: "Add 5 points for each chargeback in `chargeback_count`."
    PRD: "`risk_tier` is then read off `risk_score`, never off the pre-clamp sum, using bands inclusive at both ends: `LOW` from 0 through 24, `ELEVATED` from 25 through 49, `HIGH` from 50 through 74, and `CRITICAL` from 75 through 100."
    PRD: "Recording a signal re-runs the risk score, which may re-band `risk_tier` and, if the re-band reaches the critical band, fire the automatic platform ban described in §3.9."

    Design: Difficulty/boundary_precision_check/risk_tier_flips_to_high_at_exactly_fifty
    """
    fixtures.set_clock(api, constants.PROCESS_START_UTC)
    guest = fixtures.create_guest(api, full_name="Priya Shah", email="priya@guest.test")

    below = validate_success(
        api.record_payment_signal(
            guest["id"],
            PLATFORM_ADMIN,
            payment_risk_signal="CLEAN",
            chargeback_count=2,
        )
    )
    assertions.assert_guest_risk(below, 45, "ELEVATED")

    at_floor = validate_success(
        api.record_payment_signal(
            guest["id"],
            PLATFORM_ADMIN,
            payment_risk_signal="CLEAN",
            chargeback_count=3,
        )
    )
    assertions.assert_fields(at_floor, "guest", chargeback_count=3)
    assertions.assert_guest_risk(at_floor, 50, "HIGH")
    assert at_floor["risk_tier"] not in ("ELEVATED", "CRITICAL"), (
        "a score of 50 sits inside HIGH, not on either neighbouring band, got "
        "{0!r}".format(at_floor["risk_tier"])
    )

    profile = validate_success(api.get_guest_risk_profile(guest["id"], ADJUDICATOR))
    assertions.assert_fields(
        profile,
        "risk_profile",
        risk_score=50,
        risk_tier="HIGH",
        chargeback_count=3,
        completed_stay_count=0,
        substantiated_incident_count=0,
        approved_claim_count=0,
    )

    assertions.assert_page(
        api.list_blocklist_entries(COMPLIANCE_OFFICER, guest_id=guest["id"]),
        total_count=0,
    )


def test_lowering_the_chargeback_count_rebands_back_off_the_high_floor(api):
    """The boundary is crossed downwards too, because the count overwrites.

    The processor's second submission reports fewer chargebacks than its first.
    A count that accumulated would leave the guest at five chargebacks and deep
    inside HIGH; an overwritten count returns it to 45 and to ELEVATED, proving
    the flip at fifty is driven by the stored count rather than by a one-way latch
    on the tier.

    PRD: "Both values *overwrite* the stored ones rather than accumulating — a submission of three chargebacks after an earlier submission of five leaves the guest at three."
    PRD: "Add 5 points for each chargeback in `chargeback_count`."
    PRD: "`risk_tier` is then read off `risk_score`, never off the pre-clamp sum, using bands inclusive at both ends: `LOW` from 0 through 24, `ELEVATED` from 25 through 49, `HIGH` from 50 through 74, and `CRITICAL` from 75 through 100."

    Design: Difficulty/boundary_precision_check/risk_tier_flips_to_high_at_exactly_fifty
    """
    fixtures.set_clock(api, constants.PROCESS_START_UTC)
    guest = fixtures.create_guest(api, full_name="Priya Shah", email="priya@guest.test")

    at_floor = validate_success(
        api.record_payment_signal(
            guest["id"],
            PLATFORM_ADMIN,
            payment_risk_signal="CLEAN",
            chargeback_count=3,
        )
    )
    assertions.assert_guest_risk(at_floor, 50, "HIGH")

    lowered = validate_success(
        api.record_payment_signal(
            guest["id"],
            PLATFORM_ADMIN,
            payment_risk_signal="CLEAN",
            chargeback_count=2,
        )
    )
    assertions.assert_fields(lowered, "guest", chargeback_count=2)
    assertions.assert_guest_risk(lowered, 45, "ELEVATED")

    profile = validate_success(api.get_guest_risk_profile(guest["id"], ADJUDICATOR))
    assertions.assert_fields(
        profile, "risk_profile", risk_score=45, risk_tier="ELEVATED", chargeback_count=2
    )
