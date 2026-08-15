"""Flight confirmation: credit ceiling, discount locking, and OCC guards."""
from test_helpers import (
    FA,
    IM,
    SP,
    ApiErrorId,
    api_client,
    campaign_version,
    confirm_flight,
    confirm_flight_payload,
    create_advertiser,
    create_campaign,
    create_face_with_permit,
    create_flight_payload,
    create_published_rate_card,
    create_rate_card_payload,
    face_version,
    get_success_data,
    hold_flight,
    setup_booked_flight,
    setup_held_flight,
    submit_and_approve_campaign,
    validate_error,
    validate_success,
)


def _three_face_credit_setup(limit):
    """Advertiser with `limit`; APPROVED campaign with HELD flights on F1
    (net 1150000), F2 and F3 (net 800000 each), all 2026-08-10..2026-09-06."""
    card = create_published_rate_card()
    advertiser = create_advertiser(credit_limit_cents=limit)
    campaign = create_campaign(advertiser["id"])
    flights = {}
    for code, lit, traffic in (
        ("F-NYC-001", True, 300_000), ("F-NYC-002", False, 50_000),
        ("F-NYC-003", False, 50_000),
    ):
        face, _permit = create_face_with_permit(
            face_code=code, illuminated=lit, daily_traffic_count=traffic,
            permit_number=f"P-{code[-3:]}",
        )
        flights[code] = hold_flight(campaign["id"], face["id"], card["id"])
    submit_and_approve_campaign(campaign["id"])
    return campaign, flights, advertiser


class TestCreditLimitBoundary:

    def test_confirm_at_exact_credit_limit_allowed(self):
        """PRD section 3.5: "...and the credit ceiling — the account's
        `exposure_cents` plus this flight's `net_cents` must stay at or below
        `credit_limit_cents`, equality permitted, otherwise
        `ERR_CREDIT_LIMIT_EXCEEDED`."
        PRD section 3.4: "The credit rule is a strict ceiling with an
        inclusive boundary — exposure exactly equal to `credit_limit_cents` is
        allowed; exposure above it is not."

        Design: Difficulty/boundary_precision_check/credit_limit_equality_boundary_on_confirm
        """
        campaign, flights, advertiser = _three_face_credit_setup(1_950_000)
        confirm_flight(flights["F-NYC-001"]["id"], campaign["id"])

        confirmed = confirm_flight(flights["F-NYC-002"]["id"], campaign["id"])
        assert confirmed["status"] == "BOOKED", (
            f"exposure 1150000 + net 800000 == limit 1950000: equality is "
            f"allowed, got {confirmed['status']}"
        )
        account = validate_success(api_client.get_advertiser(advertiser["id"], FA), 200)
        assert account["exposure_cents"] == 1_950_000, (
            f"exposure after the two confirms: expected 1950000, "
            f"got {account['exposure_cents']}"
        )

    def test_confirm_one_flight_over_limit_rejected(self):
        """PRD section 3.5: "...and the credit ceiling — the account's
        `exposure_cents` plus this flight's `net_cents` must stay at or below
        `credit_limit_cents`, equality permitted, otherwise
        `ERR_CREDIT_LIMIT_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/credit_limit_equality_boundary_on_confirm
        """
        campaign, flights, _advertiser = _three_face_credit_setup(1_950_000)
        confirm_flight(flights["F-NYC-001"]["id"], campaign["id"])
        confirm_flight(flights["F-NYC-002"]["id"], campaign["id"])

        resp = api_client.confirm_flight(
            flights["F-NYC-003"]["id"],
            confirm_flight_payload(
                expected_campaign_version=campaign_version(campaign["id"])),
            SP,
        )
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)
        flight = validate_success(
            api_client.get_flight(flights["F-NYC-003"]["id"], SP), 200)
        assert flight["status"] == "HELD"


class TestStateBeatsFiscalOnConfirm:

    def test_confirm_over_credit_limit_rejected(self):
        """PRD section 3.5: "...and the credit ceiling — the account's
        `exposure_cents` plus this flight's `net_cents` must stay at or below
        `credit_limit_cents`, equality permitted, otherwise
        `ERR_CREDIT_LIMIT_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_confirm
        """
        card = create_published_rate_card()
        advertiser = create_advertiser(credit_limit_cents=1_900_000)
        campaign = create_campaign(advertiser["id"])
        f1, _p1 = create_face_with_permit(face_code="F-NYC-001")
        f2, _p2 = create_face_with_permit(
            face_code="F-NYC-002", illuminated=False, daily_traffic_count=50_000,
            permit_number="P-002",
        )
        fl_a = hold_flight(campaign["id"], f1["id"], card["id"])
        fl_b = hold_flight(campaign["id"], f2["id"], card["id"])
        submit_and_approve_campaign(campaign["id"])
        confirm_flight(fl_a["id"], campaign["id"])  # exposure 1150000

        resp = api_client.confirm_flight(
            fl_b["id"],
            confirm_flight_payload(
                expected_campaign_version=campaign_version(campaign["id"])),
            SP,
        )
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)

    def test_state_error_masks_credit_error_on_reconfirm(self):
        """PRD section 2.9: "A failure in an earlier family is reported
        immediately and masks every later family — a client never sees a
        business-rule rejection for a request whose body was malformed, and
        never sees a body-shape error for a resource that does not exist."
        PRD section 2.9: "5. **State legality and version freshness** — the
        target resource is in a state that allows the requested transition,
        terminal resources reject all mutations, and every
        optimistic-concurrency field matches the parent's current `version`
        (`ERR_INVALID_STATE`, `ERR_STALE_VERSION`)."
        PRD section 2.9: "14. **Credit** — exposure ceilings at confirm,
        credit-limit reductions, and the settlement gate
        (`ERR_CREDIT_LIMIT_EXCEEDED`, `ERR_UNRESOLVED_MAKE_GOODS`)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_confirm
        """
        card = create_published_rate_card()
        advertiser = create_advertiser(credit_limit_cents=1_900_000)
        campaign = create_campaign(advertiser["id"])
        f1, _p1 = create_face_with_permit(face_code="F-NYC-001")
        f2, _p2 = create_face_with_permit(
            face_code="F-NYC-002", illuminated=False, daily_traffic_count=50_000,
            permit_number="P-002",
        )
        fl_a = hold_flight(campaign["id"], f1["id"], card["id"])
        fl_b = hold_flight(campaign["id"], f2["id"], card["id"])
        submit_and_approve_campaign(campaign["id"])
        confirm_flight(fl_a["id"], campaign["id"])  # exposure 1150000

        # Raise the limit, confirm B (exposure 1950000), then lower the limit
        # to exactly the current exposure (allowed: not below it).
        get_success_data(api_client.update_advertiser(
            advertiser["id"], {"credit_limit_cents": 10_000_000}, FA))
        confirmed_b = confirm_flight(fl_b["id"], campaign["id"])
        assert confirmed_b["status"] == "BOOKED"
        get_success_data(api_client.update_advertiser(
            advertiser["id"], {"credit_limit_cents": 1_950_000}, FA))

        # B is already BOOKED (family 5) AND a repeat confirm would also
        # breach the ceiling 1950000 + 800000 > 1950000 (family 14).
        resp = api_client.confirm_flight(
            fl_b["id"],
            confirm_flight_payload(
                expected_campaign_version=campaign_version(campaign["id"])),
            SP,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestConfirmRelatedEntityGates:

    def test_advertiser_credit_hold_blocks_confirm_rejected(self):
        """PRD section 3.4: "An advertiser in `CREDIT_HOLD` or `SUSPENDED` is
        not bookable: campaign approval and flight confirmation both fail with
        `ERR_ADVERTISER_NOT_BOOKABLE` while the hold stands."

        Design: Corner/validations/advertiser_credit_hold_blocks_confirm_rejected
        """
        bundle = setup_held_flight()
        submit_and_approve_campaign(bundle["campaign"]["id"])
        get_success_data(api_client.update_advertiser(
            bundle["advertiser"]["id"], {"status": "CREDIT_HOLD"}, FA))

        blocked = api_client.confirm_flight(
            bundle["flight"]["id"],
            confirm_flight_payload(
                expected_campaign_version=campaign_version(
                    bundle["campaign"]["id"])),
            SP,
        )
        validate_error(blocked, ApiErrorId.ERR_ADVERTISER_NOT_BOOKABLE)

        get_success_data(api_client.update_advertiser(
            bundle["advertiser"]["id"], {"status": "ACTIVE"}, FA))
        confirmed = confirm_flight(bundle["flight"]["id"],
                                   bundle["campaign"]["id"])
        assert confirmed["status"] == "BOOKED"

    def test_confirm_on_unapproved_campaign_rejected(self):
        """PRD section 3.5: "Confirming a held flight (the `HELD` → `BOOKED`
        transition) is the moment money locks. The confirm requires the clock
        not yet to have reached `held_until` — a lapsed hold is swept to
        `EXPIRED` first; the campaign in `APPROVED` or `ACTIVE` (otherwise
        `ERR_CAMPAIGN_NOT_APPROVED`); ..."

        Design: Corner/errors/confirm_on_unapproved_campaign_rejected
        """
        bundle = setup_held_flight()
        resp = api_client.confirm_flight(
            bundle["flight"]["id"],
            confirm_flight_payload(
                expected_campaign_version=bundle["campaign"]["version"]),
            SP,
        )
        validate_error(resp, ApiErrorId.ERR_CAMPAIGN_NOT_APPROVED)
        flight = validate_success(
            api_client.get_flight(bundle["flight"]["id"], SP), 200)
        assert flight["status"] == "HELD"


class TestOptimisticConcurrency:

    def test_flight_confirm_occ_stale_version_rejected(self):
        """PRD section 2.10: "Confirming a held flight
        (`POST /api/flights/{id}/confirm`) requires a non-optional
        `expected_campaign_version` field carrying the client's last observed
        `version` of the flight's campaign. The campaign version encodes the
        contracted total from which the volume-discount tier is derived; a
        mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), and the
        client must re-read the campaign."

        Design: Corner/cross_cutting_layers/flight_confirm_occ_stale_version_rejected
        """
        card = create_published_rate_card()
        advertiser = create_advertiser()
        campaign = create_campaign(advertiser["id"])
        f1, _p1 = create_face_with_permit(face_code="F-NYC-001")
        f2, _p2 = create_face_with_permit(
            face_code="F-NYC-002", illuminated=False, daily_traffic_count=50_000,
            permit_number="P-002",
        )
        fl_a = hold_flight(campaign["id"], f1["id"], card["id"])
        fl_b = hold_flight(campaign["id"], f2["id"], card["id"])
        submit_and_approve_campaign(campaign["id"])
        stale_version = campaign_version(campaign["id"])

        confirmed_a = confirm_flight(fl_a["id"], campaign["id"])
        assert confirmed_a["status"] == "BOOKED"

        stale = api_client.confirm_flight(
            fl_b["id"],
            confirm_flight_payload(expected_campaign_version=stale_version),
            SP,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        flight_b = validate_success(api_client.get_flight(fl_b["id"], SP), 200)
        assert flight_b["status"] == "HELD"

        confirmed_b = confirm_flight(fl_b["id"], campaign["id"])
        assert confirmed_b["status"] == "BOOKED"

    def test_flight_create_occ_stale_face_rejected(self):
        """PRD section 2.10: "Creating a flight (`POST /api/flights`) requires
        a non-optional `expected_face_version` field carrying the client's
        last observed `version` of the target face. The face version encodes
        the traffic count, illumination flag, and loop configuration the quote
        was priced from; if the face's current `version` differs, the creation
        is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must
        re-read the face and re-price."

        Design: Corner/cross_cutting_layers/flight_create_occ_stale_face_rejected
        """
        card = create_published_rate_card()
        face, _permit = create_face_with_permit(face_code="F-NYC-001")
        stale_version = face_version(face["id"])
        get_success_data(api_client.update_face(
            face["id"], {"daily_traffic_count": 310_000}, IM))
        advertiser = create_advertiser()
        campaign = create_campaign(advertiser["id"])

        stale = api_client.create_flight(
            create_flight_payload(campaign["id"], face["id"], card["id"],
                                  expected_face_version=stale_version),
            SP,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        fresh = validate_success(api_client.create_flight(
            create_flight_payload(campaign["id"], face["id"], card["id"],
                                  expected_face_version=face_version(face["id"])),
            SP,
        ), 201)
        assert fresh["status"] == "HELD"

    def test_rate_card_occ_stale_update_rejected(self):
        """PRD section 2.10: "Updating a rate card (`PUT /api/rate-cards/{id}`)
        requires a non-optional `expected_rate_card_version` field carrying
        the client's last observed `version` of the card. A mismatch is
        rejected with `ERR_STALE_VERSION` (HTTP 412), so that no intervening
        repricing is silently discarded."

        Design: Corner/cross_cutting_layers/rate_card_occ_stale_update_rejected
        """
        card = get_success_data(api_client.create_rate_card(
            create_rate_card_payload(), IM))
        stale_version = card["version"]

        first = validate_success(api_client.update_rate_card(
            card["id"],
            {"base_weekly_cents": 210_000,
             "expected_rate_card_version": stale_version},
            IM,
        ), 200)

        stale = api_client.update_rate_card(
            card["id"],
            {"base_weekly_cents": 220_000,
             "expected_rate_card_version": stale_version},
            IM,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        retry = validate_success(api_client.update_rate_card(
            card["id"],
            {"base_weekly_cents": 220_000,
             "expected_rate_card_version": first["version"]},
            IM,
        ), 200)
        assert retry["base_weekly_cents"] == 220_000


class TestImmediateConsistency:

    def test_immediate_read_after_write_consistency(self):
        """PRD section 3.5: "Sixth, the campaign's `contracted_cents` becomes
        the prospective total, its `discount_pct` becomes this latest tier,
        and its `net_contracted_cents` is the sum of the per-flight net
        amounts, each rounded per flight before summing. Because rounding is
        per-flight and the tier depends on the running total, confirm order is
        observable: the same set of flights confirmed in a different order can
        lock different per-flight tiers. A successful confirm also increments
        the campaign's `version` by 1 and recomputes the advertiser's
        `exposure_cents`."
        PRD section 3.4: "Exposure is a computed ledger: it sums `net_cents`
        across the advertiser's flights in `BOOKED`, `ART_CLEARED`, `LIVE`,
        `MISSED`, or `HOLDOVER`, and adds those flights'
        `holdover_charge_cents` on top."

        Design: Corner/consistency_model/immediate_read_after_write_consistency
        """
        bundle = setup_held_flight()
        submit_and_approve_campaign(bundle["campaign"]["id"])

        confirmed = validate_success(api_client.confirm_flight(
            bundle["flight"]["id"],
            confirm_flight_payload(
                expected_campaign_version=campaign_version(
                    bundle["campaign"]["id"])),
            SP,
        ), 200)
        assert confirmed["status"] == "BOOKED"
        assert confirmed["net_cents"] == 1_150_000

        campaign = validate_success(
            api_client.get_campaign(bundle["campaign"]["id"], SP), 200)
        assert campaign["contracted_cents"] == 1_150_000
        assert campaign["net_contracted_cents"] == 1_150_000

        account = validate_success(
            api_client.get_advertiser(bundle["advertiser"]["id"], FA), 200)
        assert account["exposure_cents"] == 1_150_000
