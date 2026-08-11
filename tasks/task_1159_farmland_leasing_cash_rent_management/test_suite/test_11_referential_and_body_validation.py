"""Referential-integrity and body-shape guards: inverted lease terms,
practice immutability after activation, one-lease-per-bid, award scoping and
state, and lease-state/type gates on expenses."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_lease_payload,
    get_lease,
    make_landlord_headers,
    make_tenant_headers,
    setup_active_lease,
    setup_bid,
    setup_draft_lease,
    setup_field,
    setup_landlord,
    setup_offering,
    setup_tenant,
    shortlist_close_award,
    validate_error,
    validate_success,
)

MGR = TEST_USERS["farm_manager_headers"]


class TestLeaseBodyValidation:
    def test_lease_create_inverted_term_rejected(self, api):
        """PRD §3.4: "The end date must be later than the start date, else `ERR_VALIDATION`."

        Design: Corner/validations/lease_create_inverted_term_rejected
        """
        ctx = setup_active_lease("CASH", activate=False)
        resp = api.create_lease(
            create_lease_payload(
                ctx["bid"]["id"],
                term_start_date="2028-03-01T00:00:00Z",
                term_end_date="2027-03-01T00:00:00Z",
            ),
            MGR,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_patch_practices_on_active_lease_rejected(self, api):
        """PRD §3.4: "`conservation_practices` is editable only while the lease is `DRAFT`, and attempting to patch it on an active lease is an `ERR_VALIDATION` failure."
        PRD §2.8: "Request-body shape — missing required fields, invalid enum members, non-positive amounts where a positive amount is required, missing conditional bid parameters for the declared `lease_type`, an `escalation_pct` present when it should be absent or vice versa, a `term_end_date` that is not later than `term_start_date`, a `conservation_practices` amendment attempted while the lease is `ACTIVE`, or a notice `served_by` value that does not match the caller's role all yield `ERR_VALIDATION` (HTTP 400), on every endpoint that takes a body."

        Design: Corner/validations/patch_practices_on_active_lease_rejected
        """
        ctx = setup_active_lease("CASH")
        lease = get_lease(ctx["lease"]["id"])
        resp = api.amend_lease(
            lease["id"],
            {
                "expected_lease_version": lease["version"],
                "conservation_practices": [
                    {"practice_type": "NO_TILL", "due_date": "2027-09-01T00:00:00Z"}
                ],
            },
            MGR,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestExpenseGates:
    def test_expense_create_on_cash_lease_rejected(self, api):
        """PRD §3.6: "The caller must be the lease's tenant — a mismatch is `ERR_NOT_RESOURCE_OWNER` — and the lease must be `ACTIVE`, else `ERR_LEASE_NOT_ACTIVE`; an attempt on a `CASH` lease, which has no input sharing, is rejected with `ERR_INPUT_SHARING_NOT_APPLICABLE`."

        Design: Corner/errors/expense_create_on_cash_lease_rejected
        """
        ctx = setup_active_lease("CASH")
        resp = api.create_expense(
            {
                "lease_id": ctx["lease"]["id"],
                "category": "SEED",
                "total_cost_cents": 50000,
                "incurred_date": "2027-04-10T00:00:00Z",
                "crop_year": 2027,
            },
            make_tenant_headers(ctx["tenant"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INPUT_SHARING_NOT_APPLICABLE)

    def test_expense_create_on_draft_lease_rejected(self, api):
        """PRD §3.6: "the lease must be `ACTIVE`, else `ERR_LEASE_NOT_ACTIVE`"
        PRD §2.8: "settlement creation requires the lease to be `ACTIVE`, `TERMINATION_PENDING`, or `TERMINATED` and expense creation requires the lease to be `ACTIVE` (`ERR_LEASE_NOT_ACTIVE`, HTTP 409)"

        Design: Corner/errors/expense_create_on_draft_lease_rejected
        """
        ctx = setup_active_lease("SHARE", activate=False)
        assert ctx["lease"]["status"] == "DRAFT"
        resp = api.create_expense(
            {
                "lease_id": ctx["lease"]["id"],
                "category": "SEED",
                "total_cost_cents": 50000,
                "incurred_date": "2027-04-10T00:00:00Z",
                "crop_year": 2027,
            },
            make_tenant_headers(ctx["tenant"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_LEASE_NOT_ACTIVE)


class TestOneLeasePerBid:
    def test_second_lease_from_same_bid_rejected(self, api):
        """PRD §3.4: "a bid already linked to an existing lease cannot originate a second one, failing with `ERR_BID_ALREADY_LEASED`."
        PRD §2.8: "a bid already linked to a lease originating a second lease yields `ERR_BID_ALREADY_LEASED` (HTTP 409)"

        Design: Corner/errors/second_lease_from_same_bid_rejected
        """
        ctx = setup_active_lease("CASH", activate=False)
        assert ctx["lease"]["status"] == "DRAFT"
        resp = api.create_lease(
            create_lease_payload(
                ctx["bid"]["id"],
                term_start_date="2028-03-01T00:00:00Z",
                term_end_date="2029-03-01T00:00:00Z",
                payment_pattern="FULL_MAR",
            ),
            MGR,
        )
        validate_error(resp, ApiErrorId.ERR_BID_ALREADY_LEASED)


class TestAwardGuards:
    def _two_closed_offerings(self, api):
        """Two fields, two offerings, one SHORTLISTED bid each, both CLOSED."""
        landlord = setup_landlord(name="L FB", contact_email="lfb@x.com")
        tenant = setup_tenant(name="T FB", years_experience=5)
        field1 = setup_field(landlord["id"], name="FFB1")
        field2 = setup_field(landlord["id"], name="FFB2", acres=90, soil_csr2=79)
        off1 = setup_offering(field1["id"])
        off2 = setup_offering(field2["id"])
        bid1 = setup_bid(off1["id"], tenant["id"], "CASH")
        bid2 = setup_bid(
            off2["id"], tenant["id"], "CASH",
            cash_bid_per_acre_cents=24000, cash_equivalent_bid_cents_per_acre=24000,
        )
        validate_success(api.shortlist_bid(bid1["id"], MGR))
        validate_success(api.shortlist_bid(bid2["id"], MGR))
        validate_success(api.close_offering(off1["id"], MGR))
        validate_success(api.close_offering(off2["id"], MGR))
        return landlord, tenant, off1, off2, bid1, bid2

    def test_award_with_foreign_bid_returns_not_found(self, api):
        """PRD §2.4: "The same rejection applies to foreign-key references carried in a request body — `landlord_id`, `field_id`, `offering_id`, `bid_id`, or `lease_id` values that do not resolve to existing resources — and, when awarding an offering, to a `bid_id` that resolves but does not belong to the offering named in the path."
        PRD §3.3: "the request's `bid_id` must reference a bid of this offering, else `ERR_NOT_FOUND`"

        Design: Corner/errors/award_with_foreign_bid_returns_not_found
        """
        landlord, _, off1, off2, bid1, _ = self._two_closed_offerings(api)
        resp = api.award_offering(
            off2["id"], {"bid_id": bid1["id"]}, make_landlord_headers(landlord["id"])
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_award_of_submitted_bid_rejected(self, api):
        """PRD §3.3: "Three checks guard it, in the pipeline order of §2.8: the caller's `X-User-ID` must equal the `landlord_id` of the offering's field, else `ERR_NOT_RESOURCE_OWNER`; the request's `bid_id` must reference a bid of this offering, else `ERR_NOT_FOUND`; and that bid must be `SHORTLISTED`, else `ERR_INVALID_STATE`."

        Design: Corner/errors/award_of_submitted_bid_rejected
        """
        landlord = setup_landlord(name="L SB", contact_email="lsb@x.com")
        tenant = setup_tenant(name="T SB", years_experience=5)
        field = setup_field(landlord["id"], name="FSB")
        offering = setup_offering(field["id"])
        bid = setup_bid(offering["id"], tenant["id"], "CASH")
        validate_success(api.close_offering(offering["id"], MGR))
        # bid was never shortlisted: still SUBMITTED.
        resp = api.award_offering(
            offering["id"], {"bid_id": bid["id"]},
            make_landlord_headers(landlord["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
