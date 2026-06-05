"""Difficulty Rule 5 — priority_pair_validation_conflict.

PRD §2.6 enumerates the full validation ordering verbatim. Two pairs surface a
priority conflict on the same endpoint: cross-aggregate-referential beats
out-of-coverage on POST /claims, and state-eligibility beats pre-existing safety
on POST /claims/{id}/assess.
"""
from test_helpers import (
    validate_error,
    get_success_data,
    set_clock,
    tick_clock,
    create_default_package,
    register_customer,
    create_pending_contract,
    activate_contract,
    file_claim,
    reject_claim,
    make_customer_headers,
    make_admin_headers,
    make_dispatcher_headers,
    create_covered_item_payload,
    create_claim_payload,
    assess_claim_payload,
    reject_claim_payload,
)


_ADMIN = make_admin_headers()
_DISPATCHER = make_dispatcher_headers()


class TestPriorityReferentialBeatsTemporalOnPostClaim:
    """ERR_ITEM_NOT_ON_CONTRACT wins over ERR_OUT_OF_COVERAGE when both apply.
    PRD §2.6 lists ERR_ITEM_NOT_ON_CONTRACT before ERR_OUT_OF_COVERAGE."""

    def test_cross_contract_item_against_expired_contract_returns_item_not_on_contract(self, api):
        """PRD §2.6: "then cross-aggregate consistency (`ERR_ITEM_NOT_ON_CONTRACT`),
        then state-machine eligibility for the requested transition (`ERR_INVALID_STATE`),
        then the pre-existing exclusion against the covered item (`ERR_PRE_EXISTING_EXCLUDED`),
        then the coverage-window check for new claims (`ERR_OUT_OF_COVERAGE`)"

        Design: Difficulty/priority_pair_validation_conflict/priority_referential_beats_temporal_on_post_claim
        """
        # Build TWO active contracts, then expire contract A. Then attempt POST /claims
        # against contract A using contract B's item — both ERR_ITEM_NOT_ON_CONTRACT and
        # ERR_OUT_OF_COVERAGE apply.
        set_clock("2026-01-01T00:00:00Z")
        package = create_default_package(code="PLUSI")
        customer_a = register_customer(email="ia@example.com")
        customer_b = register_customer(email="jb@example.com")
        pending_a = create_pending_contract(customer_a, package)
        pending_b = create_pending_contract(customer_b, package)
        contract_a = activate_contract(pending_a)
        contract_b = activate_contract(pending_b)
        cust_a_h = make_customer_headers(customer_a["id"])
        cust_b_h = make_customer_headers(customer_b["id"])
        # Items on the right contracts.
        item_a = get_success_data(api.create_covered_item(
            create_covered_item_payload(contract_a["id"], category="HVAC"), cust_a_h
        ))
        item_b = get_success_data(api.create_covered_item(
            create_covered_item_payload(contract_b["id"], category="DRYER"), cust_b_h
        ))
        # Expire contract A.
        set_clock("2027-02-01T00:00:00Z")
        tick_clock()
        # File a claim with contract_a + item_b → both rules apply, referential wins.
        res = api.create_claim(
            create_claim_payload(contract_a["id"], item_b["id"],
                                  issue_summary="Cross-contract on expired"),
            cust_a_h,
        )
        validate_error(res, "ERR_ITEM_NOT_ON_CONTRACT")

    def test_response_http_status_for_item_not_on_contract_is_422(self, api):
        """PRD §2.6: "then cross-aggregate consistency (`ERR_ITEM_NOT_ON_CONTRACT`),
        then state-machine eligibility for the requested transition (`ERR_INVALID_STATE`),
        then the pre-existing exclusion against the covered item (`ERR_PRE_EXISTING_EXCLUDED`),
        then the coverage-window check for new claims (`ERR_OUT_OF_COVERAGE`)"
        PRD §5: "| `ERR_ITEM_NOT_ON_CONTRACT` | 422 |"

        Design: Difficulty/priority_pair_validation_conflict/priority_referential_beats_temporal_on_post_claim
        """
        # Companion check: a second scenario where the same pair fires confirms
        # that priority 5 (ERR_ITEM_NOT_ON_CONTRACT) precedes priority 8
        # (ERR_OUT_OF_COVERAGE) at 422, not bypassed by a different status code.
        set_clock("2026-01-01T00:00:00Z")
        package = create_default_package(code="PLUSII")
        cust_a = register_customer(email="ai-pp@example.com")
        cust_b = register_customer(email="bj-pp@example.com")
        c_a = activate_contract(create_pending_contract(cust_a, package))
        c_b = activate_contract(create_pending_contract(cust_b, package))
        cust_a_h = make_customer_headers(cust_a["id"])
        cust_b_h = make_customer_headers(cust_b["id"])
        get_success_data(api.create_covered_item(
            create_covered_item_payload(c_a["id"], category="HVAC"), cust_a_h
        ))
        item_b = get_success_data(api.create_covered_item(
            create_covered_item_payload(c_b["id"], category="DRYER"), cust_b_h
        ))
        set_clock("2027-02-01T00:00:00Z")
        tick_clock()
        res = api.create_claim(
            create_claim_payload(c_a["id"], item_b["id"],
                                  issue_summary="Cross + temporal"),
            cust_a_h,
        )
        # validate_error checks both the error_id and the HTTP status (422) per the map.
        validate_error(res, "ERR_ITEM_NOT_ON_CONTRACT")


class TestPriorityStateBeatsSafetyOnAssess:
    """ERR_INVALID_STATE wins over ERR_PRE_EXISTING_EXCLUDED when both apply.
    PRD §2.6 lists ERR_INVALID_STATE before ERR_PRE_EXISTING_EXCLUDED."""

    def test_assess_against_rejected_claim_with_pre_existing_item_returns_invalid_state(self, api):
        """PRD §2.6: "then state-machine eligibility for the requested transition
        (`ERR_INVALID_STATE`), then the pre-existing exclusion against the covered
        item (`ERR_PRE_EXISTING_EXCLUDED`)"

        Design: Difficulty/priority_pair_validation_conflict/priority_state_beats_safety_on_assess
        """
        # Build: ACTIVE contract + CoveredItem with pre_existing_flag=true + ClaimTicket
        # that has been /reject'ed (terminal REJECTED). Then attempt /assess — both rules
        # apply, state precedence makes ERR_INVALID_STATE the response.
        set_clock("2026-01-01T00:00:00Z")
        package = create_default_package(code="PLUSK")
        customer = register_customer(email="k-ps@example.com")
        pending = create_pending_contract(customer, package)
        contract = activate_contract(pending)
        cust_h = make_customer_headers(customer["id"])
        item = get_success_data(api.create_covered_item(
            create_covered_item_payload(
                contract["id"], category="WASHER", install_year=2010,
                pre_existing_flag=True,
            ),
            cust_h,
        ))
        # File and reject the claim → status REJECTED (terminal).
        claim = file_claim(contract, customer, item, issue="Always was broken")
        reject_claim(claim, "PRE_EXISTING_EXCLUDED")
        # Now attempt /assess on the REJECTED claim. State (ERR_INVALID_STATE) wins.
        res = api.assess_claim(claim["id"], assess_claim_payload(5_000), _DISPATCHER)
        validate_error(res, "ERR_INVALID_STATE")

    def test_response_http_status_for_invalid_state_is_409(self, api):
        """PRD §2.6: "then state-machine eligibility for the requested transition
        (`ERR_INVALID_STATE`), then the pre-existing exclusion against the covered
        item (`ERR_PRE_EXISTING_EXCLUDED`)"
        PRD §5: "| `ERR_INVALID_STATE` | 409 |"

        Design: Difficulty/priority_pair_validation_conflict/priority_state_beats_safety_on_assess
        """
        # Companion: confirm ERR_INVALID_STATE returns 409 even when the safety
        # rule (priority 7, http 422) would also fire. PRD §2.6 priority + §5 status.
        set_clock("2026-01-01T00:00:00Z")
        package = create_default_package(code="PLUSL")
        customer = register_customer(email="kk-ps2@example.com")
        pending = create_pending_contract(customer, package)
        contract = activate_contract(pending)
        cust_h = make_customer_headers(customer["id"])
        item = get_success_data(api.create_covered_item(
            create_covered_item_payload(
                contract["id"], category="WASHER",
                install_year=2010, pre_existing_flag=True,
            ),
            cust_h,
        ))
        claim = file_claim(contract, customer, item, issue="Combined violation")
        reject_claim(claim, "PRE_EXISTING_EXCLUDED")
        # /assess on REJECTED claim with pre_existing_flag=true: state wins.
        res = api.assess_claim(claim["id"], assess_claim_payload(5_000), _DISPATCHER)
        # validate_error cross-checks HTTP status against the registered map (409 for INVALID_STATE).
        validate_error(res, "ERR_INVALID_STATE")
