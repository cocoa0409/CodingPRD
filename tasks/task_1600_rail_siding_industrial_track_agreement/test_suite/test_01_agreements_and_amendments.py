"""TrackAgreement lifecycle (DRAFT -> ACTIVE -> renewal/expiry) and the
Amendment negotiation protocol with its OCC guard (PRD §2.5, §2.7, §3.1, §3.2).
"""
from test_helpers import (
    ENGINEER,
    NON_EXISTENT_UUID,
    RCM,
    ApiErrorId,
    assert_track_agreement,
    create_agreement_payload,
    create_segment_payload,
    get_agreement,
    get_amendment,
    make_active_agreement,
    make_agreement,
    make_amendment,
    make_shipper_headers,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers import constants as C


class TestAgreementCreation:
    def test_agreement_created_with_system_defaults(self, api):
        """PRD §3.1: "A new agreement is born in `DRAFT` status with
        `removal_penalty_cents` at 0 and both `abandonment_notice_date` and
        `removal_deadline_date` null."
        PRD §2.5: "a system-managed integer that starts at 1 on creation and
        increments by exactly 1 on every mutation of the resource"
        PRD §4: "Operations that create a new resource return a `201 Created`
        status code."

        Design: Corner/entities/agreement_create_success_defaults
        """
        res = api.create_agreement(create_agreement_payload(), RCM)
        agreement = validate_success(res, 201)
        assert_track_agreement(agreement)
        assert agreement["status"] == "DRAFT"
        assert agreement["version"] == 1
        assert agreement["removal_penalty_cents"] == 0
        assert agreement["abandonment_notice_date"] is None
        assert agreement["removal_deadline_date"] is None
        # Server-minted fields the client never supplied.
        assert agreement["id"]
        assert agreement["created_at"]
        assert agreement["updated_at"]
        fetched = get_agreement(agreement["id"])
        assert fetched["id"] == agreement["id"], "agreement must persist"

    def test_agreement_create_missing_shipper_name(self, api):
        """PRD §3.1: "The creation payload names the counterparty through
        `shipper_name` and `shipper_user_id`"
        PRD §2.10: "fifth, request body shape and field-level validity —
        required fields present, enum members valid, dates well-ordered,
        percentages within range (`ERR_INVALID_REQUEST`)"

        Design: Corner/entities/agreement_create_missing_shipper_name_returns_invalid_request
        """
        payload = create_agreement_payload()
        del payload["shipper_name"]
        res = api.create_agreement(payload, RCM)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_agreement_create_equal_term_dates_rejected(self, api):
        """PRD §3.1: "`term_start_date` and `term_end_date`, where the end date
        must be strictly later than the start date (otherwise
        `ERR_INVALID_REQUEST`)."

        Design: Corner/entities/agreement_create_equal_term_dates_rejected
        """
        payload = create_agreement_payload(term_end_date=C.TERM_START_DATE)
        res = api.create_agreement(payload, RCM)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_get_unknown_agreement_not_found(self, api):
        """PRD §2.9: "Identifiers are validated in left-to-right order, and the
        request is rejected immediately with the 404 error corresponding to the
        first identifier that does not resolve to an existing resource:
        `ERR_AGREEMENT_NOT_FOUND` for a missing agreement"

        Design: Corner/entities/get_unknown_agreement_returns_not_found
        """
        res = api.get_agreement(NON_EXISTENT_UUID, RCM)
        validate_error(res, ApiErrorId.ERR_AGREEMENT_NOT_FOUND, 404)


class TestCountersign:
    def test_countersign_from_draft_rejected(self, api):
        """PRD §3.1: "A countersign attempt by anyone else is rejected with
        `ERR_NOT_AGREEMENT_PARTY`, and from the wrong status with
        `ERR_AGREEMENT_INVALID_STATE`."

        Design: Corner/state_machines/countersign_from_draft_returns_invalid_state
        """
        agreement = make_agreement()
        res = api.countersign_agreement(
            agreement["id"], make_shipper_headers(C.SHIPPER_USER_ID)
        )
        validate_error(res, ApiErrorId.ERR_AGREEMENT_INVALID_STATE, 409)
        after = get_agreement(agreement["id"])
        assert after["status"] == "DRAFT"
        assert after["version"] == 1, "rejected call must not mutate the agreement"

    def test_countersign_by_wrong_party_rejected(self, api):
        """PRD §3.1: "A countersign attempt by anyone else is rejected with
        `ERR_NOT_AGREEMENT_PARTY`, and from the wrong status with
        `ERR_AGREEMENT_INVALID_STATE`."

        Design: Corner/validations/countersign_by_other_party_returns_forbidden
        """
        agreement = make_agreement()
        validate_success(api.submit_agreement(agreement["id"], RCM))
        res = api.countersign_agreement(
            agreement["id"], make_shipper_headers(C.OTHER_SHIPPER_USER_ID)
        )
        validate_error(res, ApiErrorId.ERR_NOT_AGREEMENT_PARTY, 403)
        after = get_agreement(agreement["id"])
        assert after["status"] == "PENDING_COUNTERSIGN"


class TestExpiryAndRenewalWindow:
    def test_agreement_expires_on_clock_sweep(self, api):
        """PRD §3.1: "Expiry needs no actor: per the sweep in §2.4, an agreement
        in `ACTIVE` or `RENEWAL_OFFERED` whose `term_end_date` is earlier than
        the current logical date becomes `EXPIRED` — a pending offer simply
        lapses unaccepted."

        Design: Corner/state_machines/agreement_expires_on_clock_sweep
        """
        agreement = make_active_agreement()
        set_clock(C.PAST_TERM_END_CLOCK)
        after = get_agreement(agreement["id"])
        assert after["status"] == "EXPIRED"

    def test_renewal_offer_after_window_close_rejected(self, api):
        """PRD §3.1: "A `RailroadContractsManager` may offer renewal only while
        the agreement is `ACTIVE`, only while no liability claim of the
        agreement sits in `FILED`, `APPORTIONED`, or `DISPUTED` status (an open
        claim rejects the offer with `ERR_OPEN_CLAIMS_BLOCK_RENEWAL`), and only
        while the current logical date is on or before the date
        `renewal_notice_days` days before `term_end_date` — past that closing
        date the offer is rejected with `ERR_RENEWAL_WINDOW_CLOSED`."

        Design: Corner/calculations/renewal_window_closed_rejected
        """
        agreement = make_active_agreement()
        # Window closed at 2027-05-02 (term_end 2027-07-31 minus 90 days);
        # the clock sits one day past the close.
        set_clock(C.RENEWAL_WINDOW_CLOSED_CLOCK)
        res = api.offer_renewal(agreement["id"], RCM)
        validate_error(res, ApiErrorId.ERR_RENEWAL_WINDOW_CLOSED, 409)
        after = get_agreement(agreement["id"])
        assert after["status"] == "ACTIVE"

    def test_child_creation_requires_active_agreement(self, api):
        """PRD §3.1: "Only an `ACTIVE` agreement supports child creation —
        segments, projects, inspections, devices, service orders, car dwells,
        storage placements, claims, and amendments all require it, failing with
        `ERR_AGREEMENT_NOT_ACTIVE` otherwise."

        Design: Corner/validations/child_creation_on_draft_agreement_returns_not_active
        """
        agreement = make_agreement()
        res = api.create_segment(create_segment_payload(agreement["id"]), ENGINEER)
        validate_error(res, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE, 409)
        # After submit + countersign the identical call succeeds.
        validate_success(api.submit_agreement(agreement["id"], RCM))
        validate_success(
            api.countersign_agreement(
                agreement["id"], make_shipper_headers(C.SHIPPER_USER_ID)
            )
        )
        ok = api.create_segment(create_segment_payload(agreement["id"]), ENGINEER)
        segment = validate_success(ok, 201)
        assert segment["status"] == "IN_SERVICE"


class TestRenewalCycle:
    def test_renewal_offer_and_accept_extends_term(self, api):
        """PRD §3.1: "A successful offer moves the agreement to
        `RENEWAL_OFFERED`."
        PRD §3.1: "The shipper accepts through a `ShipperFacilityManager`
        party-bound call, subject to the same window check
        (`ERR_RENEWAL_WINDOW_CLOSED` applies to acceptance as well) and the
        `RENEWAL_OFFERED` status requirement; acceptance returns the agreement
        to `ACTIVE` and extends `term_end_date` by exactly
        `renewal_term_months` months, preserving the day of month — an
        agreement ending 2027-07-31 renewed for twelve months ends 2028-07-31."

        Design: Difficulty/non_linear_state_machine/agreement_renewal_offer_branching_cycle
        """
        agreement = make_active_agreement()
        offered = validate_success(api.offer_renewal(agreement["id"], RCM))
        assert offered["status"] == "RENEWAL_OFFERED"
        accepted = validate_success(
            api.accept_renewal(
                agreement["id"], make_shipper_headers(C.SHIPPER_USER_ID)
            )
        )
        assert accepted["status"] == "ACTIVE"
        assert accepted["term_end_date"] == C.RENEWED_TERM_END_DATE

    def test_renewal_offer_lapses_to_expired(self, api):
        """PRD §3.1: "Expiry needs no actor: per the sweep in §2.4, an agreement
        in `ACTIVE` or `RENEWAL_OFFERED` whose `term_end_date` is earlier than
        the current logical date becomes `EXPIRED` — a pending offer simply
        lapses unaccepted."

        Design: Difficulty/non_linear_state_machine/agreement_renewal_offer_branching_cycle
        """
        agreement = make_active_agreement()
        offered = validate_success(api.offer_renewal(agreement["id"], RCM))
        assert offered["status"] == "RENEWAL_OFFERED"
        set_clock(C.PAST_TERM_END_CLOCK)
        after = get_agreement(agreement["id"])
        assert after["status"] == "EXPIRED"
        assert after["term_end_date"] == C.TERM_END_DATE, (
            "the lapsed branch never extends the term"
        )


class TestAmendmentProtocol:
    def test_amendment_create_with_stale_version_rejected(self, api):
        """PRD §2.7: "If that value does not equal the agreement's current
        `version` at write time — for instance, because another writer has
        since created an amendment of their own, which legitimately superseded
        the prior pending one and advanced the agreement's version — the
        proposal is rejected with `ERR_STALE_AGREEMENT_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_version_rejected
        """
        agreement = make_active_agreement()
        agr_id = agreement["id"]
        assert agreement["version"] == 3
        first = make_amendment(agr_id, expected_agreement_version=3)
        # The first creation advanced the agreement to version 4; a second
        # proposal still carrying the pre-create observation (3) is stale.
        res = api.create_amendment(
            agr_id,
            {
                "amendment_type": "STORAGE_RATE",
                "expected_agreement_version": 3,
                "new_storage_rate_per_car_month_cents": 12000,
            },
            make_shipper_headers(C.SHIPPER_USER_ID),
        )
        validate_error(res, ApiErrorId.ERR_STALE_AGREEMENT_VERSION, 412)
        assert get_amendment(first["id"])["status"] == "PENDING", (
            "the rejected write must not supersede the live amendment"
        )

    def test_amendment_create_with_current_version_supersedes_pending(self, api):
        """PRD §3.2: "Because only one negotiation can be live at a time,
        creating an amendment immediately moves any existing `PENDING`
        amendment on the same agreement to `SUPERSEDED`, and the creation
        itself advances the parent agreement's `version` by 1."
        PRD §2.5: "a system-managed integer that starts at 1 on creation and
        increments by exactly 1 on every mutation of the resource"

        Design: Corner/cross_cutting_layers/occ_current_version_supersedes_pending
        """
        agreement = make_active_agreement()
        agr_id = agreement["id"]
        first = make_amendment(agr_id, expected_agreement_version=3)
        current = get_agreement(agr_id)
        assert current["version"] == 4
        res = api.create_amendment(
            agr_id,
            {
                "amendment_type": "STORAGE_RATE",
                "expected_agreement_version": current["version"],
                "new_storage_rate_per_car_month_cents": 12000,
            },
            make_shipper_headers(C.SHIPPER_USER_ID),
        )
        second = validate_success(res, 201)
        assert second["status"] == "PENDING"
        assert get_amendment(first["id"])["status"] == "SUPERSEDED"
        assert get_agreement(agr_id)["version"] == 5, (
            "each amendment creation increments the parent version by 1"
        )

    def test_amendment_accept_applies_fields_immediately(self, api):
        """PRD §3.2: "Acceptance applies the amendment's new-value fields to the
        parent agreement — exactly the field set pinned by its `amendment_type`
        — and increments the agreement's `version` by 1; the amendment becomes
        `ACCEPTED`."

        Design: Corner/cross_cutting_layers/amendment_accept_applies_fields_immediately
        """
        agreement = make_active_agreement()
        agr_id = agreement["id"]
        amendment = make_amendment(
            agr_id, expected_agreement_version=3, new_liability_cap_cents=250000
        )
        res = api.respond_amendment(
            amendment["id"],
            {"decision": "ACCEPT"},
            make_shipper_headers(C.SHIPPER_USER_ID),
        )
        answered = validate_success(res)
        assert answered["status"] == "ACCEPTED"
        after = get_agreement(agr_id)
        assert after["liability_cap_cents"] == 250000
        assert after["version"] == 5

    def test_amendment_same_party_response_denied(self, api):
        """PRD §3.2: "A respond call carrying a `decision` of `ACCEPT` or
        `REJECT` is valid only while the amendment is `PENDING` (otherwise
        `ERR_AMENDMENT_INVALID_STATE`), only when the parent agreement is
        `ACTIVE` (otherwise `ERR_AGREEMENT_NOT_ACTIVE`), and only when the
        caller's role differs from the recorded `proposed_by_role` — the same
        party answering its own proposal is rejected with
        `ERR_SAME_PARTY_RESPONSE`."

        Design: Corner/validations/amendment_same_party_response_denied
        """
        agreement = make_active_agreement()
        amendment = make_amendment(
            agreement["id"], expected_agreement_version=3, proposer="railroad"
        )
        res = api.respond_amendment(amendment["id"], {"decision": "ACCEPT"}, RCM)
        validate_error(res, ApiErrorId.ERR_SAME_PARTY_RESPONSE, 403)
        assert get_amendment(amendment["id"])["status"] == "PENDING"
