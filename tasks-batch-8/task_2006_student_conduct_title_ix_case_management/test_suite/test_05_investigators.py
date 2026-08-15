"""Investigator assignment guards: party bar, recusal permanence, singletons."""
from test_helpers import (
    ApiErrorId,
    accept_assignment,
    create_case,
    drive_to_investigation,
    get_case,
    investigator_assignment_payload,
    make_cast,
    make_coordinator_headers,
    make_investigator_headers,
    propose_investigator,
    submit_evidence,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client


def _case_in_investigation(cast, categories=("STALKING",)):
    case = create_case(cast, categories=list(categories), received_via="EMAIL")
    drive_to_investigation(case["id"], cast["coord"]["id"], cast["comp"]["id"])
    return case


class TestPartyBar:
    def test_official_is_case_party_rejected(self, api):
        """PRD 2.6: "Independently, no official may be the case's complainant or
        respondent; that more specific failure is rejected with
        `ERR_OFFICIAL_IS_CASE_PARTY` (422). The party-specific check fires on
        proposing an investigator, scheduling a hearing, beginning appeal review,
        and proposing informal resolution".

        Design: Corner/validations/official_is_case_party_rejected
        """
        cast = make_cast("comp", "resp", "coord")
        case = _case_in_investigation(cast)
        resp = api.propose_investigator(
            case["id"], investigator_assignment_payload(cast["resp"]["id"]),
            make_coordinator_headers(cast["coord"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OFFICIAL_IS_CASE_PARTY)


class TestRecusalPermanence:
    def test_recused_investigator_reproposal_rejected(self, api):
        """PRD 2.6: "Second, recusal is permanent: a person recused on a case may
        never be re-proposed to any official function on that case. A violation
        of these rules is rejected with `ERR_SEGREGATION_OF_DUTIES` (422)."
        PRD 3.3: "The replacement forms a case-level cycle — a new assignment is
        proposed and accepted — but the recused person may never be re-proposed
        on this case."

        Design: Corner/validations/recused_investigator_reproposal_rejected
        """
        cast = make_cast("comp", "resp", "coord", "inv")
        coord_h = make_coordinator_headers(cast["coord"]["id"])
        case = _case_in_investigation(cast)
        assignment = propose_investigator(case["id"], cast["coord"]["id"], cast["inv"]["id"])
        accept_assignment(assignment["id"], cast["inv"]["id"])
        recused = validate_success(
            api.recuse_assignment(
                assignment["id"], {"recusal_reason": "prior relationship with respondent"},
                make_investigator_headers(cast["inv"]["id"]),
            )
        )
        assert recused["status"] == "RECUSED"
        assert recused["recusal_reason"] == "prior relationship with respondent"

        resp = api.propose_investigator(
            case["id"], investigator_assignment_payload(cast["inv"]["id"]), coord_h
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        rows, _ = validate_paginated(api.list_case_assignments(case["id"], coord_h))
        assert len(rows) == 1, "the rejected re-proposal must not persist a row"
        assert rows[0]["id"] == assignment["id"] and rows[0]["status"] == "RECUSED"


class TestActiveInvestigatorSingleton:
    def test_investigator_already_active_rejected(self, api):
        """PRD 3.3: "while any assignment on the case is `ACTIVE`, a new proposal
        is rejected with `ERR_INVESTIGATOR_ALREADY_ACTIVE` (409); a recusal must
        come first."

        Design: Corner/validations/investigator_already_active_rejected
        """
        cast = make_cast("comp", "resp", "coord", "inv", "inv2")
        case = _case_in_investigation(cast)
        assignment = propose_investigator(case["id"], cast["coord"]["id"], cast["inv"]["id"])
        accept_assignment(assignment["id"], cast["inv"]["id"])

        resp = api.propose_investigator(
            case["id"], investigator_assignment_payload(cast["inv2"]["id"]),
            make_coordinator_headers(cast["coord"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVESTIGATOR_ALREADY_ACTIVE)

    def test_no_active_investigator_blocks_evidence_review(self, api):
        """PRD 3.3: "Recusal moves the assignment `ACTIVE → RECUSED`, appends
        `INVESTIGATOR_RECUSED`, increments the case `version`, and leaves the
        case without an active investigator: from that moment, evidence
        begin-review, relevance ruling, and every packet write on the case
        (attach-report, release, finalize, withdraw) fail with
        `ERR_NO_ACTIVE_INVESTIGATOR` (422) until a replacement accepts."

        Design: Corner/validations/no_active_investigator_blocks_evidence_review
        """
        cast = make_cast("comp", "resp", "coord", "inv")
        coord_h = make_coordinator_headers(cast["coord"]["id"])
        case = _case_in_investigation(cast)
        assignment = propose_investigator(case["id"], cast["coord"]["id"], cast["inv"]["id"])
        accept_assignment(assignment["id"], cast["inv"]["id"])
        item = submit_evidence(case["id"], cast["comp"]["id"], "party",
                               evidence_type="PHOTO", description="Photo")
        api.recuse_assignment(
            assignment["id"], {"recusal_reason": "conflict discovered"},
            make_investigator_headers(cast["inv"]["id"]),
        )

        resp = api.begin_evidence_review(item["id"], make_investigator_headers(cast["inv"]["id"]))
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_INVESTIGATOR)

        item_after = validate_success(api.get_evidence_item(item["id"], coord_h))
        assert item_after["status"] == "SUBMITTED", "blocked review must not move the item"
