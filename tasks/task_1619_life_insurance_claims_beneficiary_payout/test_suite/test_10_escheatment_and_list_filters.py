"""Escheatment of unclaimed proceeds end to end (monitoring, due diligence,
escheat day gates, and the claim cascade), plus filtered list reachability."""
from test_helpers import (
    ApiErrorId,
    begin_review,
    create_designation,
    create_policy_with_statute,
    file_beneficiary_claim,
    file_claim,
    get_claim,
    list_escheatment_cases,
    set_clock,
    setup_approved_claim,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestEscheatFlowEndToEnd:
    def test_escheat_flow_end_to_end(self, api, compliance_officer_headers):
        """PRD §3.9: "As the sweep runs, a case in `MONITORING` advances to
        `DUE_DILIGENCE` once the logical date reaches the due-diligence start,
        on or after that date."
        PRD §3.9: "Escheating a case requires it to be in `DUE_DILIGENCE`
        (`ERR_CASE_NOT_ACTIONABLE`) and the logical clock date to be on or
        after the `escheat_due_date` — an early remittance is rejected with
        `ERR_ESCHEATMENT_NOT_DUE`."
        PRD §3.9: "For a proceeds case, escheatment finalizes `amount_cents` as
        the claim's total payable less the sum already paid, moves the claim
        from `APPROVED` to the terminal `ESCHEATED` state, and cascades:
        beneficiary claims in `VALIDATED` or `PAYABLE` move to `ESCHEATED`,
        and elections in `ELECTED`, `CONFIRMED`, or `SUSPENDED` move to
        `SUPERSEDED`, with the claim's `version` incrementing."
        PRD §3.9: "Resolving a case requires it to be in `MONITORING` or
        `DUE_DILIGENCE` — otherwise `ERR_CASE_NOT_ACTIONABLE`".

        Design: Corner/state_machines/c_escheat_flow_end_to_end
        """
        ctx = setup_approved_claim(
            state="IL",
            face_amount_cents=25000000,
            beneficiaries=[],
            approve_clock="2026-04-10T00:00:00Z",
            policy_overrides={"policy_number": "P-SM-13"},
        )
        claim_id = ctx["claim"]["id"]
        case = list_escheatment_cases({"claim_id": claim_id})[0]
        assert case["status"] == "MONITORING"
        assert case["escheat_due_date"] == "2029-04-10"

        # At the due-diligence start (due date - 120 days) the sweep advances
        # the case, but escheatment is not yet due.
        set_clock("2028-12-11T00:00:00Z")
        progressed = list_escheatment_cases({"claim_id": claim_id})[0]
        assert progressed["status"] == "DUE_DILIGENCE"
        early = api.escheat_escheatment_case(case["id"],
                                             compliance_officer_headers)
        validate_error(early, ApiErrorId.ERR_ESCHEATMENT_NOT_DUE)

        # On the due date the remittance succeeds and cascades the claim.
        set_clock("2029-04-10T00:00:00Z")
        escheated = validate_success(
            api.escheat_escheatment_case(case["id"], compliance_officer_headers))
        assert escheated["status"] == "ESCHEATED"
        assert escheated["amount_cents"] == 25068493, (
            "Proceeds case remits total payable less nothing paid")
        assert get_claim(claim_id)["status"] == "ESCHEATED"

        # A terminal case is no longer actionable.
        resp = api.resolve_escheatment_case(case["id"], {},
                                            compliance_officer_headers)
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_ACTIONABLE)


class TestFilteredListLookups:
    def test_filtered_list_lookups(self, api, claims_examiner_headers):
        """PRD §3.4: "Claims can be listed with `policy_id` and `status`
        filters."
        PRD §3.7: "Beneficiary claims are queryable in two list views: the
        claims-scoped view accepts a `status` filter and is ordered by creation
        ascending, and the global view accepts `claim_id`, `designation_id`,
        and `status` filters."
        PRD §3.2: "The designations of a policy can be listed with `status`
        and `beneficiary_type` filters."

        Design: Corner/endpoints/c_filtered_list_lookups
        """
        policy = create_policy_with_statute("IL", policy_number="P-EP-1")
        designation = create_designation(policy["id"],
                                         beneficiary_name="Alice Doe",
                                         share_percent=100)
        set_clock("2026-03-05T00:00:00Z")
        claim1 = file_claim(policy["id"], "2026-03-01")
        claim2 = file_claim(policy["id"], "2026-03-02")
        begin_review(claim2["id"])
        bc = file_beneficiary_claim(claim2["id"], designation_id=designation["id"],
                                    claimant_name="Alice Doe")

        claims, meta = validate_paginated(
            api.list_claims(claims_examiner_headers,
                            params={"policy_id": policy["id"],
                                    "status": "NOTIFIED"}))
        assert meta["total_count"] == 1
        assert [c["id"] for c in claims] == [claim1["id"]]

        bcs, meta = validate_paginated(
            api.list_beneficiary_claims(claims_examiner_headers,
                                        params={"designation_id": designation["id"]}))
        assert meta["total_count"] == 1
        assert [b["id"] for b in bcs] == [bc["id"]]

        designations, meta = validate_paginated(
            api.list_beneficiary_designations(
                policy["id"], claims_examiner_headers,
                params={"beneficiary_type": "PRIMARY"}))
        assert meta["total_count"] == 1
        assert [d["id"] for d in designations] == [designation["id"]]
