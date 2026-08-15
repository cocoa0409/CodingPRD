"""Syndication creation, common fields, not-found, and lifecycle guards."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_syndication,
    assert_timestamp_ms3,
    create_syndication_payload,
    is_valid_uuid,
    make_active_syndication,
    make_open_offering,
    make_property,
    make_syndication,
    get_offering,
    get_syndication,
    validate_error,
    validate_success,
)


class TestSyndicationCreation:
    def test_create_syndication_returns_draft_with_common_fields(
            self, api, sponsor_operator_headers):
        """PRD §3.1: "The new syndication starts in `DRAFT` status."
        PRD §2.4: "Every persisted resource carries an `id` that is a
        server-minted UUID with no type prefix. Resources that participate in
        the full lifecycle model additionally carry `created_at` and
        `updated_at`, both ISO 8601 UTC timestamps rendered with three
        fractional digits, and an integer `version` that increments by one on
        every mutation of that resource."

        Design: Corner/entities/syndication_create_returns_draft_with_common_fields
        """
        resp = api.create_syndication(create_syndication_payload(
            syndication_name="NewSyn", sponsor_legal_entity="New LLC",
            preferred_return_pct_annual=0.08, carried_interest_pct=0.20),
            sponsor_operator_headers)
        data = validate_success(resp, 201)
        assert_syndication(data)
        assert is_valid_uuid(data["id"])
        assert data["status"] == "DRAFT"
        assert_timestamp_ms3(data["created_at"])
        assert_timestamp_ms3(data["updated_at"])
        assert isinstance(data["version"], int)

    def test_create_syndication_missing_required_field_returns_400(
            self, api, sponsor_operator_headers):
        """PRD §2.9: "A required field that is missing, a value of the wrong
        type, or an unrecognized enum value is rejected with
        `ERR_INVALID_REQUEST` (HTTP 400)." PRD §3.1 requires a
        `syndication_name` to create a syndication.

        Design: Corner/entities/syndication_create_missing_required_field_returns_400
        """
        payload = create_syndication_payload()
        del payload["syndication_name"]
        resp = api.create_syndication(payload, sponsor_operator_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


class TestSyndicationNotFound:
    def test_get_syndication_not_found(self, api, sponsor_operator_headers):
        """PRD §2.5: "A failure at any step yields the corresponding not-found
        error: `ERR_SYNDICATION_NOT_FOUND`, `ERR_OFFERING_NOT_FOUND`,
        `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_INVESTOR_NOT_FOUND`,
        `ERR_PROPERTY_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`,
        `ERR_CAPITAL_CALL_NOT_FOUND`, `ERR_CONTRIBUTION_NOT_FOUND`,
        `ERR_QUARTERLY_REPORT_NOT_FOUND`, `ERR_DISTRIBUTION_NOT_FOUND`,
        `ERR_CAPITAL_EVENT_NOT_FOUND`, `ERR_K1_PACKAGE_NOT_FOUND`, or
        `ERR_TRANSFER_REQUEST_NOT_FOUND`, each with HTTP 404."

        Design: Corner/entities/get_syndication_not_found
        """
        resp = api.get_syndication(NON_EXISTENT_UUID, sponsor_operator_headers)
        validate_error(resp, ApiErrorId.ERR_SYNDICATION_NOT_FOUND, 404)


class TestSyndicationLifecycleGuards:
    def test_close_syndication_from_draft_rejected_invalid_state(
            self, api, sponsor_operator_headers):
        """PRD §2.8: "State-transition attempts made against a resource that is
        not in a state from which the requested transition is allowed are
        rejected with `ERR_INVALID_STATE` (HTTP 409)." PRD §3.1: "Closing a
        syndication is allowed only when every offering beneath it has reached
        `FINAL_CLOSE` or `DISSOLVED`" — closing is an action on an active
        syndication, so a DRAFT syndication cannot be closed.

        Design: Corner/state_machines/syndication_close_from_draft_rejected_invalid_state
        """
        syn = make_syndication(syndication_name="SSyn")
        resp = api.close_syndication(syn["id"], sponsor_operator_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_suspend_cascades_open_offerings(self, api, sponsor_operator_headers):
        """PRD §3.1: "an active syndication can later be suspended, which moves
        it to `SUSPENDED` and, as a cascade within the same request, pushes
        every `OPEN` offering under it into `CLOSED_TO_NEW_SUBSCRIPTIONS`."

        Design: Corner/cross_cutting_layers/syndication_suspend_cascades_to_open_offerings
        """
        syn = make_active_syndication(syndication_name="CaSyn")
        prop1 = make_property(property_legal_name="Ca P1")
        prop2 = make_property(property_legal_name="Ca P2")
        off1 = make_open_offering(syn["id"], prop1["id"], offering_name="Ca Off1")
        off2 = make_open_offering(syn["id"], prop2["id"], offering_name="Ca Off2")

        suspended = validate_success(api.suspend_syndication(syn["id"],
                                                             sponsor_operator_headers))
        assert suspended["status"] == "SUSPENDED"
        assert get_syndication(syn["id"])["status"] == "SUSPENDED"
        off1_after = get_offering(syn["id"], off1["id"])
        off2_after = get_offering(syn["id"], off2["id"])
        assert off1_after["status"] == "CLOSED_TO_NEW_SUBSCRIPTIONS", (
            f"offering 1 should cascade to CLOSED_TO_NEW_SUBSCRIPTIONS, "
            f"got {off1_after['status']}")
        assert off2_after["status"] == "CLOSED_TO_NEW_SUBSCRIPTIONS", (
            f"offering 2 should cascade to CLOSED_TO_NEW_SUBSCRIPTIONS, "
            f"got {off2_after['status']}")
