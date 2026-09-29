"""The contract negotiation graph is a cycle with a counted exit.

Compliance review reverts to draft three times.  Each revert advances the
disclosure template version and invalidates only the disclosures that were
merely issued, leaving acknowledged ones in place but stale.  The fourth revert
is refused by the round counter, not by any state guard.
"""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx


@pytest.fixture()
def thrice_amended_contract(client):
    """A contract that has already been reverted three times and re-signed."""
    agency = fx.register_agency(
        client,
        legal_name="Nordwind Bildungsberatung",
        home_country_code="DE",
        beneficial_owner_count=1,
        reference_check_count=2,
    )
    fx.clear_agency(client, agency["id"])
    program = fx.create_program(client)
    contract = fx.draft_contract(
        client,
        agency["id"],
        contract_ref="CTR-2026-007",
        exclusivity_model=C.EXCLUSIVITY_NON_EXCLUSIVE_ONLY,
        annual_commission_cap_cents=3000000,
    )
    fx.append_schedule(client, contract["id"], contract["version"])
    fx.send_contract_for_signature(client, contract["id"])

    # One student acknowledges at template version 1; another only ever receives it.
    acknowledged = fx.create_application(
        client,
        agency["id"],
        program["id"],
        student_ref="STU-2001",
        student_residence_country="DE",
    )
    fx.issue_and_acknowledge_disclosure(
        client, agency["id"], acknowledged["id"], "applicant-2001"
    )
    issued_only = fx.create_application(
        client,
        agency["id"],
        program["id"],
        student_ref="STU-2002",
        student_residence_country="DE",
    )
    fx.issue_disclosure(client, agency["id"], issued_only["id"])

    for note in (
        "Round 1: territory schedule wording",
        "Round 2: prohibited-claims annex",
        "Round 3: clawback window",
    ):
        fx.agency_sign_contract(client, agency["id"], contract["id"])
        fx.request_amendment(client, contract["id"], note)
        fx.send_contract_for_signature(client, contract["id"])
    fx.agency_sign_contract(client, agency["id"], contract["id"])

    return {
        "agency_id": agency["id"],
        "contract_id": contract["id"],
        "acknowledged_application_id": acknowledged["id"],
        "issued_application_id": issued_only["id"],
    }


class TestContractAmendmentCycle:
    def test_fourth_amendment_request_is_refused_by_the_round_counter(
        self, client, thrice_amended_contract
    ):
        """The guard is the counter, and the refused call changes nothing.

        "At most three amendment rounds are permitted: the revert requires
        `amendment_round` to be strictly below 3, so a fourth attempt is refused
        with `ERR_AMENDMENT_LIMIT_REACHED`."

        "`AGENCY_SIGN` moves `PENDING_AGENCY_SIGNATURE →
        PENDING_COMPLIANCE_REVIEW` and is reserved to the `AgencyOwner` whose
        `X-User-ID` equals the contract's `agency_id`."

        Design: Difficulty/non_linear_state_machine/contract_amendment_revert_cycle_hits_limit
        """
        env = thrice_amended_contract

        response = client.contract_lifecycle_action(
            env["contract_id"],
            F.lifecycle_payload(C.LIFECYCLE_REQUEST_AMENDMENT, note="Round 4 attempt"),
            fx.COMPLIANCE,
        )
        validate_error(response, E.ERR_AMENDMENT_LIMIT_REACHED)

        contract = fx.read_contract(client, env["contract_id"])
        assert contract["amendment_round"] == 3
        assert contract["disclosure_template_version"] == 4
        assert contract["status"] == C.CONTRACT_PENDING_COMPLIANCE_REVIEW
        assert contract["agency_signed_by_user_id"] == env["agency_id"]

    def test_amendment_invalidates_issued_disclosures_and_leaves_acknowledged_ones_stale(
        self, client, thrice_amended_contract
    ):
        """Only the issued disclosure is torn down; the acknowledged one stays.

        "every application of that agency whose `disclosure_state` is `ISSUED` is
        driven to `INVALIDATED`"

        "Deliberately, an application whose disclosure is already `ACKNOWLEDGED`
        keeps that state — it is *not* invalidated — but because the contract's
        template version has advanced while the application's pinned version has
        not, the application has become version-stale"

        "In both cases `disclosure_ack_token` is cleared, so a fresh issuance is
        required before the student can acknowledge again."

        Design: Difficulty/non_linear_state_machine/contract_amendment_revert_cycle_hits_limit
        """
        env = thrice_amended_contract

        acknowledged = fx.read_application(client, env["acknowledged_application_id"])
        assert acknowledged["disclosure_state"] == C.DISCLOSURE_ACKNOWLEDGED
        assert acknowledged["disclosure_template_version"] == 1

        invalidated = fx.read_application(client, env["issued_application_id"])
        assert invalidated["disclosure_state"] == C.DISCLOSURE_INVALIDATED
        assert invalidated["disclosure_ack_token"] is None
