"""Claims intake: the creation-time coverage test, the release cascade's
service-date filter, intake validation, and claims listing (PRD §3.6, §2.3)."""
from test_helpers import (
    ApiErrorId,
    assert_claim,
    create_approved_application,
    create_claim,
    create_draft_application,
    create_payer_config,
    create_submitted_application,
    find_record,
    get_claim,
    set_clock,
    setup_group_provider_payer,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

SPECIALIST = TEST_USERS["enrollment_specialist_headers"]
PAYER_REP = TEST_USERS["payer_representative_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


class TestClaimInitialStatus:
    def test_released_held_and_denied_from_the_same_endpoint(self, api):
        """PRD §3.6: "A covered claim is born `RELEASED`. An uncovered claim
        born under a payer whose `claims_hold_enabled` is true becomes `HELD`,
        parked in anticipation of a future enrollment. An uncovered claim under
        a payer with holds disabled is born `DENIED` with `denial_reason` set
        to `PAYER_HOLD_DISABLED`."

        Design: Corner/entities/claim_initial_status_hold_release_denied
        """
        _, provider, _, payer_h = setup_group_provider_payer()
        payer_n = create_payer_config(
            payer_code="PN", name="Payer N", claims_hold_enabled=False,
        )
        _, record = create_approved_application(provider["id"], payer_h["id"])
        assert record["effective_date"] == "2026-08-01"
        set_clock("2026-08-10T00:00:00Z")

        covered = create_claim(
            provider["id"], payer_h["id"], service_date="2026-08-05", amount_cents=1000,
        )
        assert_claim(covered)
        assert covered["status"] == "RELEASED"
        assert covered["recoupment_fee_cents"] == 0

        before_effective = create_claim(
            provider["id"], payer_h["id"], service_date="2026-07-01", amount_cents=1000,
        )
        assert before_effective["status"] == "HELD"

        denied = create_claim(
            provider["id"], payer_n["id"], service_date="2026-08-05", amount_cents=1000,
        )
        assert denied["status"] == "DENIED"
        assert denied["denial_reason"] == "PAYER_HOLD_DISABLED"


class TestReleaseCascadeServiceDateFilter:
    def test_release_includes_only_claims_on_or_after_effective_date(self, api):
        """PRD §3.6: "When an enrollment record becomes `ACTIVE` with effective
        date E — through application approval or roster ADD confirmation —
        every `HELD` claim of that provider–payer pair whose `service_date` is
        on or after E transitions `HELD → RELEASED`, processed in service-date
        order with ties broken by creation order; `HELD` claims dated before E
        stay `HELD`."

        Design: Corner/calculations/claim_release_filters_by_service_date
        """
        _, provider, _, payer = setup_group_provider_payer()
        c_early = create_claim(
            provider["id"], payer["id"], service_date="2026-07-20", amount_cents=1000,
        )
        c_late = create_claim(
            provider["id"], payer["id"], service_date="2026-08-01", amount_cents=1000,
        )
        assert c_early["status"] == "HELD" and c_late["status"] == "HELD"

        app = create_submitted_application(
            provider["id"], payer["id"], requested_effective_date="2026-08-01",
        )
        validate_success(api.approve_application(app["id"], PAYER_REP), 200)
        # APPROVAL_DATE policy: effective date = approval day 2026-08-01.

        assert get_claim(c_late["id"])["status"] == "RELEASED"
        assert get_claim(c_early["id"])["status"] == "HELD", (
            "claims dated before the effective date stay HELD"
        )


class TestClaimIntakeValidation:
    def test_future_service_date_rejected(self, api):
        """PRD §3.6: "The amount must be a positive integer number of cents and
        the service date must not be later than the current logical date, else
        `ERR_FUTURE_SERVICE_DATE`; a claim for a `TERMINATED` provider is
        refused outright with `ERR_PROVIDER_TERMINATED`."

        Design: Corner/validations/future_service_date_rejected
        """
        _, provider, _, payer = setup_group_provider_payer(attest=False)
        # Startup clock is 2026-08-01; 2026-08-02 is in the future.
        res = api.create_claim(
            {
                "provider_id": provider["id"],
                "payer_id": payer["id"],
                "service_date": "2026-08-02",
                "amount_cents": 1000,
            },
            SPECIALIST,
        )
        validate_error(res, ApiErrorId.ERR_FUTURE_SERVICE_DATE)

    def test_claim_for_terminated_provider_rejected(self, api):
        """PRD §3.6: "The amount must be a positive integer number of cents and
        the service date must not be later than the current logical date, else
        `ERR_FUTURE_SERVICE_DATE`; a claim for a `TERMINATED` provider is
        refused outright with `ERR_PROVIDER_TERMINATED`."

        Design: Corner/validations/claim_for_terminated_provider_rejected
        """
        _, provider, _, payer = setup_group_provider_payer(attest=False)
        validate_success(
            api.terminate_provider(
                provider["id"],
                {"termination_effective_date": "2026-08-01", "reason": "departed"},
                OFFICER,
            ),
            200,
        )
        res = api.create_claim(
            {
                "provider_id": provider["id"],
                "payer_id": payer["id"],
                "service_date": "2026-07-15",
                "amount_cents": 1000,
            },
            SPECIALIST,
        )
        validate_error(res, ApiErrorId.ERR_PROVIDER_TERMINATED)


class TestClaimsListPaginationAndFilter:
    def test_limit_offset_total_count_has_more_and_status_filter(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of returned items;
        it defaults to 10, with a minimum of 1 and a maximum of 100. The
        `offset` parameter states how many items to skip and defaults to 0."
        PRD §2.3: "The `meta` object of a list response carries `limit`,
        `offset`, `total_count`, and `has_more`."
        PRD §2.3: "claims by `provider_id`, `payer_id`, and `status`".

        Design: Corner/endpoints/claims_list_pagination_and_filter
        """
        _, provider, _, payer = setup_group_provider_payer()
        create_approved_application(provider["id"], payer["id"])
        for amount in (1000, 2000, 3000):
            create_claim(
                provider["id"], payer["id"],
                service_date="2026-08-01", amount_cents=amount,
            )

        page1, meta1 = validate_paginated(
            api.list_claims(
                SPECIALIST, params={"provider_id": provider["id"], "limit": 2, "offset": 0}
            )
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2 and meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api.list_claims(
                SPECIALIST, params={"provider_id": provider["id"], "limit": 2, "offset": 2}
            )
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        held, meta3 = validate_paginated(
            api.list_claims(
                SPECIALIST, params={"provider_id": provider["id"], "status": "HELD"}
            )
        )
        assert held == [], "all three claims are RELEASED"
        assert meta3["total_count"] == 0
