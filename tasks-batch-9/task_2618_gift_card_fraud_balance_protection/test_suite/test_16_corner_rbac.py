"""Identity, role authorization, store scoping and segregation of duties.

"Every request to every endpoint must carry two headers: X-User-ID, identifying the
acting principal, and X-User-Role, naming the role that principal is acting in."
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import (
    ERR_INVALID_REQUEST,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
)
from test_helpers.constants import (
    CLOCK_ORIGIN,
    ROLE_FRAUD_ANALYST,
    ROLE_PLATFORM_ADMIN,
)
from test_helpers.factories import (
    claim_decision_payload,
    clear_tamper_payload,
    clock_setting,
    liability_period_payload,
    posture_override_payload,
    rack_audit_payload,
    rescind_payload,
    reseller_listing_payload,
    resolution_payload,
    reversal_payload,
    store_payload,
)
from test_helpers.fixtures import (
    create_rack,
    create_store,
    file_claim,
    file_referral,
    funded_digital_card,
    funded_physical_card,
    open_alert,
    open_period,
    read_alert,
    read_card,
    read_claim,
    read_period,
    read_rack,
    read_store,
    redeem,
    total_count,
    triage_alert,
    validate_listing,
)
from test_helpers.test_users import (
    make_anonymous_headers,
    make_fraud_analyst_headers,
    make_liability_accountant_headers,
    make_platform_admin_headers,
    make_pos_associate_headers,
    make_reseller_partner_headers,
    make_risk_manager_headers,
    make_store_manager_headers,
)

# "At process start the clock reads exactly 2026-08-01T00:00:00Z", and every stamped
# instant is rendered "with three fractional digits", so only the prefix is compared.
CLOCK_ORIGIN_PREFIX = "2026-08-01T00:00:00"


class TestAnonymousRequestsAreUnauthenticated:
    """An empty X-User-ID is an absent identity on every endpoint."""

    def test_a_write_without_a_user_id_is_rejected_before_anything_is_created(self, client):
        """"A request whose X-User-ID header is absent or empty is rejected with
        ERR_UNAUTHENTICATED (HTTP 401) before any other processing occurs."

        Design: Corner/rbac/request_without_user_header_is_unauthenticated
        """
        response = client.create_store(
            store_payload(
                name="Anonymous Store", region_code="NE", address_line="54 Anon Ave"
            ),
            make_anonymous_headers(ROLE_PLATFORM_ADMIN),
        )

        assert response.status_code == 401, response.text
        validate_error(response, ERR_UNAUTHENTICATED, 401)

    def test_even_the_read_all_policy_endpoint_requires_the_identity_header(self, client):
        """"A request whose X-User-ID header is absent or empty is rejected with
        ERR_UNAUTHENTICATED (HTTP 401) before any other processing occurs."
        "Authentication — X-User-ID present and non-empty on every endpoint. Otherwise
        ERR_UNAUTHENTICATED (401)."

        Design: Corner/rbac/request_without_user_header_is_unauthenticated
        """
        response = client.get_risk_policy(make_anonymous_headers(ROLE_FRAUD_ANALYST))

        assert response.status_code == 401, response.text
        validate_error(response, ERR_UNAUTHENTICATED, 401)

    def test_authentication_outranks_request_wellformedness(self, client):
        """"Every request is validated as an ordered ladder, and the first violation
        encountered wins: the request is rejected with that rule's error and no later rule
        is evaluated."
        "A request whose X-User-ID header is absent or empty is rejected with
        ERR_UNAUTHENTICATED (HTTP 401) before any other processing occurs."

        Design: Corner/rbac/request_without_user_header_is_unauthenticated
        """
        response = client.create_store(
            store_payload(name="", region_code="NE", address_line="55 Anon Ave"),
            make_anonymous_headers(ROLE_PLATFORM_ADMIN),
        )

        assert response.status_code == 401, response.text
        body = validate_error(response, ERR_UNAUTHENTICATED, 401)
        assert body["error_id"] != ERR_INVALID_REQUEST

    def test_none_of_the_rejected_calls_persisted_a_store(self, client):
        """"A request whose X-User-ID header is absent or empty is rejected with
        ERR_UNAUTHENTICATED (HTTP 401) before any other processing occurs."
        "total_count is the number of records matching the filters before the window is
        applied."

        Design: Corner/rbac/request_without_user_header_is_unauthenticated
        """
        client.create_store(
            store_payload(
                name="Anonymous Store", region_code="NE", address_line="54 Anon Ave"
            ),
            make_anonymous_headers(ROLE_PLATFORM_ADMIN),
        )
        client.create_store(
            store_payload(name="", region_code="NE", address_line="55 Anon Ave"),
            make_anonymous_headers(ROLE_PLATFORM_ADMIN),
        )

        assert total_count(client.list_stores(make_platform_admin_headers())) == 0


class TestPosAssociateCannotResolveADrainingAlert:
    """Resolution is a RiskManager operation and no other role reaches it."""

    def _triaged_alert(self, client):
        """A 5000-cent ACTIVE physical card carrying one alert triaged by analyst-86."""
        store = create_store(
            client, name="Role Denied Store", region_code="MW", address_line="56 Role Rd"
        )
        rack = create_rack(
            client, store["id"], rack_label="RACK-RD", expected_card_count=5
        )
        built = funded_physical_card(client, 5000, store=store, rack=rack)
        analyst = make_fraud_analyst_headers("analyst-86")
        alert = open_alert(
            client, built["card"]["id"], "MANUAL_REVIEW", headers=analyst, note="role test"
        )
        alert = triage_alert(client, alert["id"], headers=analyst, triage_note="reviewed")
        assert alert["state"] == "TRIAGED", alert
        return {"store": store, "card_id": built["card"]["id"], "alert": alert}

    def test_the_associates_confirm_is_refused_and_writes_nothing(self, client):
        """"When the header is present but the role it resolves to is not among the roles
        authorized for the target endpoint (see the table in §4), the request is rejected
        with ERR_UNAUTHORIZED (HTTP 403)."
        "Resolution is exclusively a RiskManager operation, is admitted only from TRIAGED,
        and requires a resolution of either CONFIRM or DISMISS together with a mandatory
        resolution_note."

        Design: Corner/rbac/pos_associate_cannot_resolve_a_draining_alert
        """
        world = self._triaged_alert(client)

        response = client.resolve_draining_alert(
            world["alert"]["id"],
            resolution_payload("CONFIRM", resolution_note="associate trying to close it out"),
            make_pos_associate_headers("pos-86"),
        )

        assert response.status_code == 403, response.text
        validate_error(response, ERR_UNAUTHORIZED, 403)

        alert = read_alert(client, world["alert"]["id"])
        assert alert["state"] == "TRIAGED"
        assert not alert["resolution"]
        assert not alert["resolved_by_user_id"]
        assert alert["version"] == world["alert"]["version"]
        assert read_card(client, world["card_id"])["risk_posture"] == "CLEAR"

    def test_the_risk_managers_identical_confirm_freezes_the_card(self, client):
        """"Either resolution records resolved_by_user_id from the caller and the supplied
        note, recomputes the store's open_alert_count and floor_posture, and increments the
        alert's, the card's and the store's version."
        "Hop two follows from the alert being confirmed: the card's risk_posture is forced
        to FROZEN, from whatever rung it was on — CLEAR → FROZEN, WATCH → FROZEN or
        RESTRICTED → FROZEN."

        Design: Corner/rbac/pos_associate_cannot_resolve_a_draining_alert
        """
        world = self._triaged_alert(client)

        response = client.resolve_draining_alert(
            world["alert"]["id"],
            resolution_payload("CONFIRM", resolution_note="risk manager closing it out"),
            make_risk_manager_headers("risk-86"),
        )

        resolved = validate_success(response, 200)
        assert resolved["state"] == "CONFIRMED"
        assert resolved["resolved_by_user_id"] == "risk-86"
        assert read_card(client, world["card_id"])["risk_posture"] == "FROZEN"


class TestStoreManagerScopeIsBoundToOneStore:
    """A StoreManager's X-User-ID is the store id every target is compared against."""

    def _two_stores_and_a_digital_card(self, client):
        """Two OPEN stores, one INTACT rack each, and a DIGITAL card the server minted
        itself, which therefore "carries no store and no rack at all"."""
        store1 = create_store(
            client, name="Scope Store One", region_code="SE", address_line="57 Scope St"
        )
        store2 = create_store(
            client, name="Scope Store Two", region_code="SE", address_line="58 Scope St"
        )
        rack1 = create_rack(
            client, store1["id"], rack_label="RACK-S1", expected_card_count=5
        )
        rack2 = create_rack(
            client, store2["id"], rack_label="RACK-S2", expected_card_count=5
        )
        digital = funded_digital_card(client, face_value_cents=4000)
        return {
            "store1": store1,
            "store2": store2,
            "rack1": rack1,
            "rack2": rack2,
            "digital_card": digital["card"],
        }

    def test_the_manager_may_audit_the_rack_of_their_own_store(self, client):
        """"Concretely, the effective store of the target must equal X-User-ID, where the
        effective store is the store's own id for a store target, store_id for a rack, gift
        card, issuance request or bulk purchase order target."
        "Otherwise it is INTACT."
        "Both figures are persisted verbatim so that the classification is reproducible from
        the stored row, and last_audit_at is stamped from the logical clock."

        Design: Corner/rbac/store_manager_cannot_audit_another_stores_rack
        """
        world = self._two_stores_and_a_digital_card(client)

        response = client.audit_card_rack(
            world["rack1"]["id"],
            rack_audit_payload(observed_card_count=5, seal_breaks_observed=0),
            make_store_manager_headers(world["store1"]["id"]),
        )

        audited = validate_success(response, 200)
        assert audited["tamper_state"] == "INTACT"

        rack = read_rack(client, world["rack1"]["id"])
        assert rack["last_audit_at"].startswith(CLOCK_ORIGIN_PREFIX), rack["last_audit_at"]

    def test_the_manager_is_denied_on_a_sibling_stores_rack(self, client):
        """"Concretely, the effective store of the target must equal X-User-ID, where the
        effective store is the store's own id for a store target, store_id for a rack, gift
        card, issuance request or bulk purchase order target."
        "Store scoping — for a StoreManager, the target's effective store must equal
        X-User-ID, and a target with no store denies the caller. Otherwise ERR_UNAUTHORIZED
        (403)."
        "A newly registered rack is INTACT, with missing_card_count 0, seal_breaks_observed
        0, and both observed_card_count and last_audit_at still empty because no audit has
        run."

        Design: Corner/rbac/store_manager_cannot_audit_another_stores_rack
        """
        world = self._two_stores_and_a_digital_card(client)

        response = client.audit_card_rack(
            world["rack2"]["id"],
            rack_audit_payload(observed_card_count=4, seal_breaks_observed=1),
            make_store_manager_headers(world["store1"]["id"]),
        )

        assert response.status_code == 403, response.text
        validate_error(response, ERR_UNAUTHORIZED, 403)

        rack2 = read_rack(client, world["rack2"]["id"])
        assert rack2["tamper_state"] == "INTACT"
        assert rack2["seal_breaks_observed"] == 0
        assert rack2["missing_card_count"] == 0
        assert not rack2["last_audit_at"]

        store2 = read_store(client, world["store2"]["id"])
        assert store2["floor_posture"] == "OPEN"
        assert store2["suspect_rack_count"] == 0

    def test_a_digital_card_with_no_store_denies_the_manager_but_not_the_associate(self, client):
        """"When the target's effective store resolves to nothing — as it does for every
        DIGITAL gift card and every DIGITAL issuance request, both of which carry no store —
        a StoreManager is denied with ERR_UNAUTHORIZED (HTTP 403)."

        Design: Corner/rbac/store_manager_cannot_audit_another_stores_rack
        """
        world = self._two_stores_and_a_digital_card(client)
        card_id = world["digital_card"]["id"]
        assert not world["digital_card"]["store_id"], world["digital_card"]

        denied = client.get_gift_card(
            card_id, make_store_manager_headers(world["store1"]["id"])
        )
        assert denied.status_code == 403, denied.text
        validate_error(denied, ERR_UNAUTHORIZED, 403)

        allowed = client.get_gift_card(card_id, make_pos_associate_headers("pos-87"))
        card = validate_success(allowed, 200)
        assert card["id"] == card_id
        assert card["channel"] == "DIGITAL"


class TestTheTriagerCannotResolveTheirOwnAlert:
    """Segregation of duties compares X-User-ID against the stored triager, not the role."""

    def _alert_triaged_by_analyst(self, client):
        """A 5000-cent ACTIVE physical card whose only alert was triaged by analyst-89."""
        store = create_store(
            client, name="Duty Split Store", region_code="NW", address_line="59 Duty Dr"
        )
        rack = create_rack(
            client, store["id"], rack_label="RACK-DS", expected_card_count=5
        )
        built = funded_physical_card(client, 5000, store=store, rack=rack)
        analyst = make_fraud_analyst_headers("analyst-89")
        alert = open_alert(
            client,
            built["card"]["id"],
            "MANUAL_REVIEW",
            headers=analyst,
            note="duty split test",
        )
        alert = triage_alert(
            client, alert["id"], headers=analyst, triage_note="reviewed by analyst-89"
        )
        return {"store": store, "card_id": built["card"]["id"], "alert": alert}

    def test_a_risk_manager_presenting_the_triagers_id_is_refused(self, client):
        """"The alert moves OPEN → TRIAGED, triaged_by_user_id is recorded from the caller's
        X-User-ID, the card's redemption-weighted drain score is recomputed as described in
        §3.6 and copied into the alert's basis_drain_score, the card's posture escalates
        upward only under the same ladder — reaching RESTRICTED when the recomputed score is
        at or above drain_restrict_score_threshold and the card's current rung is lower — and
        the store's open_alert_count and floor_posture are recomputed."
        "It is also the harder half of the segregation-of-duties boundary: the resolving
        X-User-ID must differ from the alert's recorded triaged_by_user_id, otherwise the
        request is refused with ERR_SEGREGATION_OF_DUTIES."

        Design: Corner/rbac/same_user_cannot_triage_and_resolve_one_alert
        """
        world = self._alert_triaged_by_analyst(client)
        assert world["alert"]["triaged_by_user_id"] == "analyst-89"

        response = client.resolve_draining_alert(
            world["alert"]["id"],
            resolution_payload(
                "DISMISS", resolution_note="same person closing their own triage"
            ),
            make_risk_manager_headers("analyst-89"),
        )

        assert response.status_code == 403, response.text
        validate_error(response, ERR_SEGREGATION_OF_DUTIES, 403)

        alert = read_alert(client, world["alert"]["id"])
        assert alert["state"] == "TRIAGED"
        assert not alert["resolution"]
        assert alert["version"] == world["alert"]["version"]

    def test_a_different_risk_manager_may_dismiss_the_same_alert(self, client):
        """"Either resolution records resolved_by_user_id from the caller and the supplied
        note, recomputes the store's open_alert_count and floor_posture, and increments the
        alert's, the card's and the store's version."
        "Crucially, triaged_by_user_id is preserved across the reopen, so segregation of
        duties still binds the same original triager on the next resolution attempt."
        "Note that both CONFIRMED and DISMISSED alerts stop counting toward
        open_alert_count, so confirming the last live alert can relax the floor even though
        the fraud turned out to be real; and because alerts are attributed to a store through
        the card's store, a reissued card that preserves its store keeps contributing to that
        store."

        Design: Corner/rbac/same_user_cannot_triage_and_resolve_one_alert
        """
        world = self._alert_triaged_by_analyst(client)

        response = client.resolve_draining_alert(
            world["alert"]["id"],
            resolution_payload("DISMISS", resolution_note="independent reviewer closing it"),
            make_risk_manager_headers("risk-89"),
        )

        resolved = validate_success(response, 200)
        assert resolved["state"] == "DISMISSED"
        assert resolved["resolved_by_user_id"] == "risk-89"
        assert resolved["triaged_by_user_id"] == "analyst-89"

        store = read_store(client, world["store"]["id"])
        assert store["open_alert_count"] == 0
        assert store["floor_posture"] == "OPEN"


class TestTheIntakeUserCannotDecideTheirOwnClaim:
    """The claim's recorded intake_user_id blocks the same operator from deciding it."""

    def _claim_taken_by_analyst(self, client):
        """A 6000-cent card drained by one 2000-cent redemption, with a fully evidenced
        2000-cent claim taken in by analyst-90."""
        store = create_store(
            client, name="Claim Duty Store", region_code="SW", address_line="60 Claim Ct"
        )
        rack = create_rack(
            client, store["id"], rack_label="RACK-CD", expected_card_count=5
        )
        built = funded_physical_card(client, 6000, store=store, rack=rack)
        card_id = built["card"]["id"]
        redeem(client, card_id, 2000, store["id"])
        claim = file_claim(
            client,
            card_id,
            disputed_amount_cents=2000,
            purchased_at=CLOCK_ORIGIN,
            headers=make_fraud_analyst_headers("analyst-90"),
            purchase_receipt_ref="RCPT-CD-90",
            packaging_photo_ref="PHOTO-CD-90",
        )
        return {"store": store, "card_id": card_id, "claim": claim}

    def test_the_intake_user_cannot_deny_the_claim_they_took_in(self, client):
        """"A successful intake creates the claim in state SUBMITTED with evidence_round at
        0, missing_evidence_kinds empty, intake_user_id recorded from the caller's
        X-User-ID."
        "Segregation of duties binds here as it does on alert resolution: the deciding
        X-User-ID must differ from the claim's intake_user_id, or the request is refused with
        ERR_SEGREGATION_OF_DUTIES."

        Design: Corner/rbac/same_user_cannot_intake_and_decide_one_claim
        """
        world = self._claim_taken_by_analyst(client)
        assert world["claim"]["intake_user_id"] == "analyst-90"
        assert world["claim"]["state"] == "SUBMITTED"

        response = client.decide_victim_claim(
            world["claim"]["id"],
            claim_decision_payload("DENY", decision_note="no unauthorized activity"),
            make_risk_manager_headers("analyst-90"),
        )

        assert response.status_code == 403, response.text
        validate_error(response, ERR_SEGREGATION_OF_DUTIES, 403)

    def test_the_intake_user_cannot_approve_the_money_either(self, client):
        """"The person who took the customer's story cannot be the person who authorises the
        money."
        "Hop one freezes unauthorized_line_count, gross_reissue_cents, reissue_amount_cents
        and residual_transfer_cents onto the claim and records decided_by_user_id."

        Design: Corner/rbac/same_user_cannot_intake_and_decide_one_claim
        """
        world = self._claim_taken_by_analyst(client)

        response = client.decide_victim_claim(
            world["claim"]["id"],
            claim_decision_payload("APPROVE", decision_note="paying the claimant"),
            make_risk_manager_headers("analyst-90"),
        )

        assert response.status_code == 403, response.text
        validate_error(response, ERR_SEGREGATION_OF_DUTIES, 403)

        claim = read_claim(client, world["claim"]["id"])
        assert claim["state"] == "SUBMITTED"
        assert claim["version"] == world["claim"]["version"]
        assert not claim["decided_by_user_id"]
        assert not claim["reissued_card_id"]

        card = read_card(client, world["card_id"])
        assert card["activation_state"] == "ACTIVE"
        assert card["current_balance_cents"] == 4000

    def test_a_second_risk_manager_may_deny_the_same_claim(self, client):
        """"A denial takes the disjoint path. The claim moves SUBMITTED → DENIED,
        decided_by_user_id and decision_note are recorded, every money field stays empty, no
        replacement card is minted, no ledger event is appended, and no liability period is
        touched."

        Design: Corner/rbac/same_user_cannot_intake_and_decide_one_claim
        """
        world = self._claim_taken_by_analyst(client)

        response = client.decide_victim_claim(
            world["claim"]["id"],
            claim_decision_payload("DENY", decision_note="reviewed independently"),
            make_risk_manager_headers("risk-90"),
        )

        decided = validate_success(response, 200)
        assert decided["state"] == "DENIED"
        assert decided["decided_by_user_id"] == "risk-90"
        assert not decided["reissued_card_id"]
        assert not decided["reissue_amount_cents"]

        card = read_card(client, world["card_id"])
        assert card["activation_state"] == "ACTIVE"
        assert card["current_balance_cents"] == 4000


class TestResellerPartnerReadsAreNarrowerThanTheInvestigators:
    """The partner sees a card's own listings but neither the referral log nor exposure."""

    def _confirmed_alert_with_referral(self, client):
        """A confirmed alert on a 5000-cent card, one referral packet filed against it, and
        an OPEN liability period covering the current instant."""
        store = create_store(
            client, name="Partner Read Store", region_code="NE", address_line="61 Partner Pl"
        )
        rack = create_rack(
            client, store["id"], rack_label="RACK-PR2", expected_card_count=5
        )
        built = funded_physical_card(client, 5000, store=store, rack=rack)
        period = open_period(client)
        analyst = make_fraud_analyst_headers("analyst-91")
        alert = open_alert(
            client,
            built["card"]["id"],
            "RESELLER_SIGNAL",
            headers=analyst,
            note="listed on a marketplace within minutes",
        )
        triage_alert(client, alert["id"], headers=analyst, triage_note="pattern reviewed")
        resolved = validate_success(
            client.resolve_draining_alert(
                alert["id"],
                resolution_payload("CONFIRM", resolution_note="drain confirmed"),
                make_risk_manager_headers("risk-91"),
            ),
            200,
        )
        referral = file_referral(
            client,
            alert["id"],
            headers=make_risk_manager_headers("risk-91"),
            agency_name="Regional Fraud Task Force",
        )
        return {
            "card_id": built["card"]["id"],
            "alert": resolved,
            "referral": referral,
            "period": period,
        }

    def test_the_partner_reads_the_alert_but_not_its_referral_log(self, client):
        """"Read one alert with its frozen exposure snapshot and investigation trail." is
        open to `ResellerPartner`, while "List every law-enforcement packet filed against one
        confirmed alert." is open only to `FraudAnalyst`, `RiskManager`, `PlatformAdmin`.
        "The role column lists the identity roles permitted to call the endpoint; any other
        role receives an authorization failure, and a missing or unknown caller identity is
        rejected before authorization is considered."

        Design: Corner/rbac/reseller_partner_cannot_read_referrals_or_the_exposure_summary
        """
        world = self._confirmed_alert_with_referral(client)
        partner = make_reseller_partner_headers("partner-91")

        alert = validate_success(
            client.get_draining_alert(world["alert"]["id"], partner), 200
        )
        assert alert["state"] == "CONFIRMED"

        denied = client.list_alert_referrals(world["alert"]["id"], partner)
        assert denied.status_code == 403, denied.text
        validate_error(denied, ERR_UNAUTHORIZED, 403)

        allowed = client.list_alert_referrals(
            world["alert"]["id"], make_fraud_analyst_headers("analyst-91")
        )
        validate_success(allowed, 200)
        assert total_count(allowed) == 1
        assert [row["id"] for row in allowed.json()["data"]] == [world["referral"]["id"]]

    def test_the_partner_is_denied_the_exposure_summary_the_accountant_may_read(self, client):
        """"Computed read exposing the conserved net funded liability alongside the period's
        stored reserve numbers." is open to `RiskManager`, `LiabilityAccountant`,
        `PlatformAdmin`.
        "When the header is present but the role it resolves to is not among the roles
        authorized for the target endpoint (see the table in §4), the request is rejected
        with ERR_UNAUTHORIZED (HTTP 403)."
        "It reports net_funded_liability_cents, computed live as the sum of
        current_balance_cents over cards whose activation_state is ACTIVE or DEPLETED, minus
        that period's unauthorized_writeoff_cents; funded_card_count, the number of cards in
        that same funded population; in_period_alert_count, the number of alerts created
        inside the period's half-open span in any state; and confirmed_alert_count, how many
        of those are CONFIRMED."

        Design: Corner/rbac/reseller_partner_cannot_read_referrals_or_the_exposure_summary
        """
        world = self._confirmed_alert_with_referral(client)

        denied = client.get_exposure_summary(
            world["period"]["id"], make_reseller_partner_headers("partner-91")
        )
        assert denied.status_code == 403, denied.text
        validate_error(denied, ERR_UNAUTHORIZED, 403)

        allowed = client.get_exposure_summary(
            world["period"]["id"], make_liability_accountant_headers("acct-91")
        )
        summary = validate_success(allowed, 200)
        assert summary["unauthorized_writeoff_cents"] == 0
        assert summary["net_funded_liability_cents"] == 5000
        assert summary["funded_card_count"] == 1
        assert summary["in_period_alert_count"] == 1
        assert summary["confirmed_alert_count"] == 1

    def test_the_partner_may_still_list_one_cards_marketplace_offers(self, client):
        """"List every secondary-marketplace listing of one card." is open to `FraudAnalyst`,
        `RiskManager`, `ResellerPartner`, `PlatformAdmin`.
        "A card's balance-inquiry log, a card's competing holds, a card's secondary-
        marketplace listings, and an alert's law-enforcement referral packets are each
        reachable only through the owning resource's path."

        Design: Corner/rbac/reseller_partner_cannot_read_referrals_or_the_exposure_summary
        """
        world = self._confirmed_alert_with_referral(client)

        response = client.list_card_reseller_listings(
            world["card_id"], make_reseller_partner_headers("partner-91")
        )

        validate_success(response, 200)
        assert total_count(response) == 0
        assert response.json()["data"] == []


class TestTheAccountantMayUndoAnApprovalButNeverMakeOne:
    """Deciding is a RiskManager operation; rescinding is shared with the accountant."""

    def _claim_awaiting_decision(self, client):
        """A 6000-cent card with one 2000-cent redemption, an OPEN period covering the
        current instant, and a fully evidenced 2000-cent claim taken in by pos-92."""
        store = create_store(
            client,
            name="Accountant Reach Store",
            region_code="MW",
            address_line="62 Ledger Ln",
        )
        rack = create_rack(
            client, store["id"], rack_label="RACK-AR", expected_card_count=5
        )
        built = funded_physical_card(client, 6000, store=store, rack=rack)
        card_id = built["card"]["id"]
        redeem(client, card_id, 2000, store["id"])
        period = open_period(client)
        claim = file_claim(
            client,
            card_id,
            disputed_amount_cents=2000,
            purchased_at=CLOCK_ORIGIN,
            headers=make_pos_associate_headers("pos-92"),
            purchase_receipt_ref="RCPT-AR-92",
            packaging_photo_ref="PHOTO-AR-92",
        )
        return {"store": store, "card_id": card_id, "claim": claim, "period": period}

    def _approved_claim(self, client):
        """The same world with the claim approved by risk-92, so the four-hop cascade has
        already run."""
        world = self._claim_awaiting_decision(client)
        approved = validate_success(
            client.decide_victim_claim(
                world["claim"]["id"],
                claim_decision_payload("APPROVE", decision_note="victim made whole"),
                make_risk_manager_headers("risk-92"),
            ),
            200,
        )
        world["approved"] = approved
        return world

    def test_the_accountant_cannot_decide_the_claim(self, client):
        """"Deciding is exclusively a RiskManager operation, is admitted only from SUBMITTED,
        and takes a decision of either APPROVE or DENY plus an optional decision_note."
        "When the header is present but the role it resolves to is not among the roles
        authorized for the target endpoint (see the table in §4), the request is rejected
        with ERR_UNAUTHORIZED (HTTP 403)."

        Design: Corner/rbac/liability_accountant_may_rescind_but_not_decide_a_claim
        """
        world = self._claim_awaiting_decision(client)

        response = client.decide_victim_claim(
            world["claim"]["id"],
            claim_decision_payload("APPROVE", decision_note="booking the writeoff"),
            make_liability_accountant_headers("acct-92"),
        )

        assert response.status_code == 403, response.text
        validate_error(response, ERR_UNAUTHORIZED, 403)

        claim = read_claim(client, world["claim"]["id"])
        assert claim["state"] == "SUBMITTED"
        assert claim["version"] == world["claim"]["version"]
        assert not claim["decided_by_user_id"]

        period = read_period(client, world["period"]["id"])
        assert period["unauthorized_writeoff_cents"] == 0

    def test_the_risk_managers_approval_runs_the_whole_cascade(self, client):
        """"recovery_factor_bps applied to each line individually, and each line's result is
        rounded to whole cents half-up before the addition; gross_reissue_cents is the sum of
        those already-rounded per-line figures."
        "reissue_amount_cents is the smaller of gross_reissue_cents and
        disputed_amount_cents."
        "Fifth, residual_transfer_cents takes whatever is still live on the compromised card
        — its current_balance_cents at that moment — so that value is moved rather than
        duplicated."
        "A ledger event of type REISSUE_CREDIT is appended on it for reissue_amount_cents
        plus residual_transfer_cents, and the claim's reissued_card_id is set."
        "Hop four follows from the original card having been written off: the OPEN liability
        period whose span contains the logical now has its unauthorized_writeoff_cents
        incremented by reissue_amount_cents."

        Design: Corner/rbac/liability_accountant_may_rescind_but_not_decide_a_claim
        """
        world = self._approved_claim(client)
        approved = world["approved"]

        assert approved["state"] == "APPROVED"
        assert approved["decided_by_user_id"] == "risk-92"
        assert approved["unauthorized_line_count"] == 1
        assert approved["gross_reissue_cents"] == 1700
        assert approved["reissue_amount_cents"] == 1700
        assert approved["residual_transfer_cents"] == 4000

        replacement = read_card(client, approved["reissued_card_id"])
        assert replacement["activation_state"] == "ACTIVE"
        assert replacement["current_balance_cents"] == 5700
        assert replacement["reissued_from_card_id"] == world["card_id"]

        original = read_card(client, world["card_id"])
        assert original["activation_state"] == "CLOSED"

        period = read_period(client, world["period"]["id"])
        assert period["unauthorized_writeoff_cents"] == 1700

    def test_the_accountant_may_rescind_that_approval(self, client):
        """"An approval can be undone. A RiskManager or a LiabilityAccountant may rescind an
        APPROVED claim with a mandatory rescind_reason, and the rescission is an exact
        compensation that unwinds all four hops."
        "The replacement card transitions ACTIVE → VOIDED ... having its risk_posture forced
        to FROZEN and its closed_at stamped."
        "The original card returns CLOSED → ACTIVE, its closed_at cleared back to empty."
        "The OPEN period containing the logical now has unauthorized_writeoff_cents
        decremented by reissue_amount_cents."
        "The claim moves APPROVED → RESCINDED, records the reason, and retains
        reissue_amount_cents, residual_transfer_cents and reissued_card_id for audit rather
        than clearing them."

        Design: Corner/rbac/liability_accountant_may_rescind_but_not_decide_a_claim
        """
        world = self._approved_claim(client)
        replacement_id = world["approved"]["reissued_card_id"]

        response = client.rescind_victim_claim(
            world["claim"]["id"],
            rescind_payload(rescind_reason="claimant admitted the redemptions were theirs"),
            make_liability_accountant_headers("acct-92"),
        )

        rescinded = validate_success(response, 200)
        assert rescinded["state"] == "RESCINDED"
        assert rescinded["reissue_amount_cents"] == 1700
        assert rescinded["residual_transfer_cents"] == 4000
        assert rescinded["reissued_card_id"] == replacement_id

        replacement = read_card(client, replacement_id)
        assert replacement["activation_state"] == "VOIDED"
        assert replacement["risk_posture"] == "FROZEN"
        assert replacement["current_balance_cents"] == 0

        original = read_card(client, world["card_id"])
        assert original["activation_state"] == "ACTIVE"
        assert original["current_balance_cents"] == 4000
        assert not original["closed_at"]

        period = read_period(client, world["period"]["id"])
        assert period["unauthorized_writeoff_cents"] == 0


class TestEveryRoleReachesItsOwnExclusiveOperations:
    """Each role's private corner of the surface answers to that role and no other."""

    def _floor(self, client):
        """An 8000-cent ACTIVE card with one 3000-cent redemption on it, sitting on an
        INTACT rack in an OPEN store."""
        store = create_store(
            client, name="All Roles Store", region_code="SE", address_line="63 Roles Row"
        )
        rack = create_rack(
            client, store["id"], rack_label="RACK-AL", expected_card_count=5
        )
        built = funded_physical_card(client, 8000, store=store, rack=rack)
        card_id = built["card"]["id"]
        event = redeem(
            client, card_id, 3000, store["id"], headers=make_pos_associate_headers("pos-93")
        )
        assert read_card(client, card_id)["current_balance_cents"] == 5000
        return {"store": store, "rack": rack, "card_id": card_id, "event": event}

    def test_only_the_partner_lists_and_only_the_analyst_validates(self, client):
        """"A ResellerPartner submits a listing naming the card_id being offered, the
        marketplace_name it is listed on (1 to 80 characters), the asking_price_cents being
        sought, and the listed_balance_cents the reseller claims the card carries. The listing
        is created in state SUBMITTED, with reseller_partner_id recorded from the submitting
        partner's X-User-ID."
        "Notably, a ResellerPartner may submit and read listings and may probe card balances,
        but may not validate a listing — validation is the retailer's control, not the
        reseller's."
        "Otherwise the listing becomes VALIDATED and block_reason stays empty."

        Design: Corner/rbac/every_role_can_run_its_own_exclusive_operations
        """
        world = self._floor(client)

        submitted = validate_success(
            client.create_reseller_listing(
                reseller_listing_payload(
                    world["card_id"], 5000, marketplace_name="GiftBay", asking_price_cents=4600
                ),
                make_reseller_partner_headers("partner-93"),
            ),
            201,
        )
        assert submitted["state"] == "SUBMITTED"
        assert submitted["reseller_partner_id"] == "partner-93"

        validated = validate_listing(
            client,
            submitted["id"],
            headers=make_fraud_analyst_headers("analyst-93"),
            validation_note="balance matches the live card",
        )
        assert validated["state"] == "VALIDATED"
        assert not validated["block_reason"]
        assert validated["validated_by_user_id"] == "analyst-93"

    def test_only_the_risk_manager_overrides_posture_and_only_the_accountant_opens_a_period(
        self, client
    ):
        """"The second is a manual override, which is the exclusive province of a RiskManager
        and the only unconstrained write to this dimension: the manager supplies the desired
        risk_posture — CLEAR, WATCH, RESTRICTED or FROZEN — together with a reason, and the
        card's posture is set to exactly that value, upward or downward, with the monotone
        escalation rule not applying."
        "An override leaves the funding state and every balance figure completely untouched."
        "A new period is created in OPEN with unauthorized_writeoff_cents at 0,
        restatement_count at 0."

        Design: Corner/rbac/every_role_can_run_its_own_exclusive_operations
        """
        world = self._floor(client)

        watched = validate_success(
            client.override_card_posture(
                world["card_id"],
                posture_override_payload("WATCH", reason="monitoring after a large sale"),
                make_risk_manager_headers("risk-93"),
            ),
            200,
        )
        assert watched["risk_posture"] == "WATCH"
        assert watched["activation_state"] == "ACTIVE"
        assert watched["current_balance_cents"] == 5000

        period = validate_success(
            client.create_liability_period(
                liability_period_payload(
                    period_start="2026-08-01T00:00:00Z", period_end="2026-09-01T00:00:00Z"
                ),
                make_liability_accountant_headers("acct-93"),
            ),
            201,
        )
        assert period["state"] == "OPEN"
        assert period["unauthorized_writeoff_cents"] == 0
        assert period["restatement_count"] == 0

    def test_only_the_admin_moves_the_clock_and_only_the_risk_manager_reverses(self, client):
        """"A PlatformAdmin moves the clock by supplying a to_iso8601 instant; the response
        reports the new setting as current_utc and the number of holds the move expired as
        expired_hold_count."
        "Reversal is the only correction mechanism, and it is the exclusive province of a
        RiskManager, who names the event to unwind and supplies a reversal_reason. A new
        REDEMPTION_REVERSAL event is appended, carrying the original's amount as a positive
        movement, with reverses_event_id pointing at the original, the supplied reason
        recorded as the new event's memo, and occurred_at at the logical now."
        "current_balance_cents is the sum of every event's signed amount.
        total_loaded_cents is the sum of the raw amounts over the credit kinds only."

        Design: Corner/rbac/every_role_can_run_its_own_exclusive_operations
        """
        world = self._floor(client)

        moved = validate_success(
            client.set_clock(
                clock_setting("2026-08-01T03:00:00Z"), make_platform_admin_headers("admin-93")
            ),
            200,
        )
        assert moved["current_utc"].startswith("2026-08-01T03:00:00"), moved["current_utc"]
        assert moved["expired_hold_count"] == 0

        reversal = validate_success(
            client.reverse_ledger_event(
                world["event"]["id"],
                reversal_payload(reversal_reason="Unauthorized redemption unwound"),
                make_risk_manager_headers("risk-93"),
            ),
            201,
        )
        assert reversal["type"] == "REDEMPTION_REVERSAL"
        assert reversal["reverses_event_id"] == world["event"]["id"]
        assert reversal["amount_cents"] == 3000
        assert reversal["occurred_at"].startswith("2026-08-01T03:00:00"), reversal["occurred_at"]

        card = read_card(client, world["card_id"])
        assert card["current_balance_cents"] == 8000
        assert card["total_loaded_cents"] == 11000
        assert card["total_redeemed_cents"] == 0

    def test_the_associate_audits_the_rack_and_the_manager_remediates_it(self, client):
        """"Rack monitoring happens through audits, which a StoreManager or a PosAssociate
        records by reporting the observed_card_count physically counted in the fixture and the
        seal_breaks_observed — the number of broken tamper-evident seals found."
        "If missing_card_count is at least rack_shrink_threshold, or seal_breaks_observed is
        at least rack_seal_break_threshold, the rack is TAMPERED."
        "Hop two is the store's recomputation, which — because tampered_rack_count is now at
        least 1 — drives floor_posture to SUSPENDED from either OPEN or HEIGHTENED."
        "Remediation records a remediation_note, resets observed_card_count to equal
        expected_card_count, resets seal_breaks_observed and missing_card_count to 0, and
        returns tamper_state to INTACT."

        Design: Corner/rbac/every_role_can_run_its_own_exclusive_operations
        """
        world = self._floor(client)

        audited = validate_success(
            client.audit_card_rack(
                world["rack"]["id"],
                rack_audit_payload(observed_card_count=5, seal_breaks_observed=3),
                make_pos_associate_headers("pos-93"),
            ),
            200,
        )
        assert audited["tamper_state"] == "TAMPERED"
        assert audited["missing_card_count"] == 0
        assert read_store(client, world["store"]["id"])["floor_posture"] == "SUSPENDED"

        cleared = validate_success(
            client.clear_card_rack_tamper(
                world["rack"]["id"],
                clear_tamper_payload(remediation_note="Fixture re-sealed and restocked"),
                make_store_manager_headers(world["store"]["id"]),
            ),
            200,
        )
        assert cleared["tamper_state"] == "INTACT"
        assert cleared["seal_breaks_observed"] == 0
        assert cleared["observed_card_count"] == 5

        store = read_store(client, world["store"]["id"])
        assert store["floor_posture"] == "OPEN"
        assert store["tampered_rack_count"] == 0

    def test_the_whole_seven_role_chain_leaves_one_consistent_world(self, client):
        """"Cards that are ACTIVE, DEPLETED or CLOSED are left completely untouched, because
        their value is already funded and belongs to a customer."
        "Reversal deliberately leaves risk_posture completely untouched."
        "REJECTED and BLOCKED are terminal. VALIDATED is not: it is the one state the
        alert-confirmation cascade of §3.7 and the manual posture override of §3.6 can later
        drive to BLOCKED with block_reason CARD_RISK_POSTURE, whenever the underlying card
        reaches FROZEN."
        "remediating the last tampered rack drops the floor straight back to HEIGHTENED or
        OPEN"

        Design: Corner/rbac/every_role_can_run_its_own_exclusive_operations
        """
        world = self._floor(client)

        listing = validate_success(
            client.create_reseller_listing(
                reseller_listing_payload(
                    world["card_id"], 5000, marketplace_name="GiftBay", asking_price_cents=4600
                ),
                make_reseller_partner_headers("partner-93"),
            ),
            201,
        )
        validate_listing(
            client,
            listing["id"],
            headers=make_fraud_analyst_headers("analyst-93"),
            validation_note="matches the live balance",
        )
        client.override_card_posture(
            world["card_id"],
            posture_override_payload("WATCH", reason="monitoring after a large sale"),
            make_risk_manager_headers("risk-93"),
        )
        validate_success(
            client.create_liability_period(
                liability_period_payload(),
                make_liability_accountant_headers("acct-93"),
            ),
            201,
        )
        client.set_clock(
            clock_setting("2026-08-01T03:00:00Z"), make_platform_admin_headers("admin-93")
        )
        client.reverse_ledger_event(
            world["event"]["id"],
            reversal_payload(reversal_reason="Unauthorized redemption unwound"),
            make_risk_manager_headers("risk-93"),
        )
        client.audit_card_rack(
            world["rack"]["id"],
            rack_audit_payload(observed_card_count=5, seal_breaks_observed=3),
            make_pos_associate_headers("pos-93"),
        )
        client.clear_card_rack_tamper(
            world["rack"]["id"],
            clear_tamper_payload(remediation_note="Fixture re-sealed and restocked"),
            make_store_manager_headers(world["store"]["id"]),
        )

        card = read_card(client, world["card_id"])
        assert card["activation_state"] == "ACTIVE"
        assert card["risk_posture"] == "WATCH"
        assert card["current_balance_cents"] == 8000

        assert read_store(client, world["store"]["id"])["floor_posture"] == "OPEN"
        assert read_rack(client, world["rack"]["id"])["tamper_state"] == "INTACT"

        listing_after = validate_success(
            client.get_reseller_listing(listing["id"], make_platform_admin_headers()), 200
        )
        assert listing_after["state"] == "VALIDATED"
        assert not listing_after["block_reason"]
