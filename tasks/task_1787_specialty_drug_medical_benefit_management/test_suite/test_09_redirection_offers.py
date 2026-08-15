"""Site-of-care redirection offers: auto-creation, acceptance incentive, and the
offer lifecycle (PRD §3.4, §3.5)."""
from test_helpers import (
    ApiErrorId,
    approve_auth,
    assert_redirection,
    get_redirection,
    set_clock,
    setup_approved_scenario,
    setup_drug_with_policy,
    setup_offered_redirection,
    create_provider,
    submit_auth,
    TEST_USERS,
    validate_error,
    validate_success,
)

CM = TEST_USERS["case_manager_headers"]
MPO = TEST_USERS["mpo_headers"]


class TestRedirectionAutoCreation:
    def test_redirection_created_only_for_eligible_drug(self, api):
        """PRD §3.4: "when the policy's `requires_site_of_care_redirection` is set and the
        drug is `site_of_care_eligible`, an `OFFERED` redirection springs into existence
        automatically (§3.5)."
        PRD §3.5: "Each auto-created offer begins `OFFERED`, with `from_site` fixed at
        `HOPD` — the high-cost site being redirected away from — and `candidate_sites`
        listing `OFFICE`, `HOME`, and `AMBULATORY`." The incentive estimate is "zero until
        then" (acceptance).

        Design: Corner/state_machines/redirection_auto_created_on_approve
        """
        elig = setup_drug_with_policy(
            drug_overrides={
                "j_code": "J5000",
                "drug_name": "EligDrug",
                "site_of_care_eligible": True,
            },
            policy_overrides={"requires_site_of_care_redirection": True},
            with_rate=False,
        )
        noelig = setup_drug_with_policy(
            drug_overrides={
                "j_code": "J5001",
                "drug_name": "NoEligDrug",
                "site_of_care_eligible": False,
            },
            policy_overrides={"requires_site_of_care_redirection": True},
            with_rate=False,
        )
        provider = create_provider(name="Redir Provider 2")
        auth_e = approve_auth(
            submit_auth(elig["drug"]["id"], provider["id"], "MEM-T7")["id"], 4
        )
        auth_n = approve_auth(
            submit_auth(noelig["drug"]["id"], provider["id"], "MEM-T8")["id"], 4
        )

        offers_e = validate_success(api.list_redirections(CM, params={"auth_id": auth_e["id"]}))
        assert len(offers_e) == 1, "exactly one auto-created offer"
        offer = offers_e[0]
        assert_redirection(offer)
        assert offer["status"] == "OFFERED"
        assert offer["from_site"] == "HOPD"
        assert offer["candidate_sites"] == ["OFFICE", "HOME", "AMBULATORY"]
        assert offer["member_incentive_cents"] == 0
        assert offer["accepted_site"] is None

        offers_n = validate_success(api.list_redirections(CM, params={"auth_id": auth_n["id"]}))
        assert offers_n == [], "ineligible drug: no offer despite the policy flag"


class TestRedirectionAcceptance:
    def test_acceptance_computes_incentive_estimate(self, api):
        """PRD §3.5: "The estimate takes the authorization's `approved_dose_mg` divided by
        the drug's `billing_unit_mg`, rounded up to a whole estimated unit count;
        multiplies that count by the ASP rate effective on the current clock date ... and
        by one plus the six percent base add-on, rounded half-up to whole cents; the
        incentive is then twenty percent of that estimated allowed amount, again rounded
        half-up to whole cents."
        ceil(100 / 10) = 10 units x 500 x 1.06 = 5300; round(5300 x 0.20) = 1060.

        Design: Corner/calculations/redirection_incentive_estimate_literal
        """
        scenario = setup_offered_redirection(member_id="MEM-C2")
        redirection = scenario["redirection"]

        accepted = validate_success(
            api.accept_redirection(redirection["id"], {"accepted_site": "HOME"}, CM)
        )
        assert accepted["status"] == "ACCEPTED"
        assert accepted["accepted_site"] == "HOME"
        assert accepted["member_incentive_cents"] == 1060

    def test_second_accept_rejected(self, api):
        """PRD §3.5: "Acceptance requires three things: the offer still `OFFERED`,
        otherwise `ERR_REDIRECTION_NOT_OFFERED`; an `accepted_site` that is one of the
        offered candidates, otherwise `ERR_INVALID_REQUEST`; and the authorization still
        `APPROVED`, otherwise `ERR_AUTH_NOT_APPROVED`."

        Design: Corner/state_machines/redirection_accept_twice_rejected
        """
        scenario = setup_offered_redirection(member_id="MEM-T5")
        redirection = scenario["redirection"]

        first = validate_success(
            api.accept_redirection(redirection["id"], {"accepted_site": "HOME"}, CM)
        )
        assert first["member_incentive_cents"] == 1060

        resp = api.accept_redirection(redirection["id"], {"accepted_site": "OFFICE"}, CM)
        validate_error(resp, ApiErrorId.ERR_REDIRECTION_NOT_OFFERED, 409)

        after = get_redirection(redirection["id"])
        assert after["status"] == "ACCEPTED"
        assert after["accepted_site"] == "HOME", "first acceptance stands"
        assert after["member_incentive_cents"] == 1060


class TestRedirectionExpiry:
    def test_offer_lapses_after_thirty_days(self, api):
        """PRD §3.5: "An offer left open lapses to `EXPIRED` once the current clock date
        is more than thirty days after its creation". Created at the startup clock
        2026-08-01 (PRD §2.4), the offer lapses once the clock passes 2026-08-31.

        Design: Corner/cross_cutting_layers/redirection_offer_expires_via_clock
        """
        scenario = setup_offered_redirection(member_id="MEM-X1")
        redirection = scenario["redirection"]
        assert redirection["status"] == "OFFERED"

        set_clock("2026-09-01T00:00:00Z")

        expired = get_redirection(redirection["id"])
        assert expired["status"] == "EXPIRED"

        resp = api.accept_redirection(redirection["id"], {"accepted_site": "HOME"}, CM)
        validate_error(resp, ApiErrorId.ERR_REDIRECTION_NOT_OFFERED, 409)
