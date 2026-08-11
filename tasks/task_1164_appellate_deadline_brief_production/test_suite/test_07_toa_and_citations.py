"""Table of authorities aggregation and citation verification gates."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    assert_toa, assert_citation,
    attorney_headers,
    setup_briefing_case,
    create_brief, submit_brief, approve_brief,
    create_citation_payload,
    walk_brief_to_ready,
    PARALEGAL,
)


def _get_toa(api, brief_id, headers) -> dict:
    data = get_success_data(api.get_brief_toa(brief_id, headers))
    rows = data if isinstance(data, list) else [data]
    assert rows, f"brief {brief_id} has no table of authorities"
    return rows[0]


class TestToaAggregation:
    def test_toa_counts_after_adds_and_verifies(self, api):
        """PRD §3.5: "The table's arithmetic is simple aggregation:
        `citation_count` is the number of citations under the table,
        `verified_count` is the number of those verified, and
        `unverified_count` is the difference between the two."

        Design: Corner/calculations/toa_unverified_count_aggregation
        """
        ctx = setup_briefing_case(court_overrides={"code": "CAL3"})
        headers = attorney_headers(ctx["attorney"])
        brief = create_brief(ctx, "OPENING")
        toa = _get_toa(api, brief["id"], headers)

        citations = [
            validate_success(
                api.add_citation(toa["id"], create_citation_payload(
                    raw_text=text, authority_type=kind), headers),
                201,
            )
            for text, kind in [
                ("Marbury v. Madison, 5 U.S. 137", "CASE"),
                ("Brown v. Board, 347 U.S. 483", "CASE"),
                ("28 U.S.C. § 1291", "STATUTE"),
                ("Fed. R. App. P. 4", "RULE"),
                ("Wright & Miller § 1234", "SECONDARY"),
            ]
        ]
        for c in citations:
            assert_citation(c)
            assert c["verified"] is False, "a new citation must start unverified"

        validate_success(api.verify_citation(citations[0]["id"], PARALEGAL), 200)
        validate_success(api.verify_citation(citations[1]["id"], PARALEGAL), 200)

        toa_after = validate_success(api.get_toa(toa["id"], headers), 200)
        assert_toa(toa_after)
        assert toa_after["citation_count"] == 5
        assert toa_after["verified_count"] == 2
        assert toa_after["unverified_count"] == 3, (
            "unverified_count must equal citation_count minus verified_count"
        )


class TestToaVerificationGate:
    def test_unverified_citations_block_approve_when_efiling_required(self, api):
        """PRD §3.5: "Approval is the most heavily guarded transition on a brief
        and its checks run in priority order — the brief must be `IN_REVIEW`
        (state), the approver must differ from the author (segregation), the
        approver must be admitted to the case's court (admission), the brief
        must not be `over_limit` (length), and finally, when the court mandates
        electronic filing, the table of authorities must exist with
        `unverified_count` equal to zero, else `ERR_TOA_UNVERIFIED`."

        Design: Corner/errors/err_toa_unverified_blocks_brief_approve
        """
        ctx = setup_briefing_case(court_overrides={
            "code": "E4", "efiling_required": True,
        })
        headers = attorney_headers(ctx["attorney"])
        brief = create_brief(ctx, "OPENING")
        toa = _get_toa(api, brief["id"], headers)
        validate_success(
            api.add_citation(toa["id"], create_citation_payload(
                raw_text="Some Case, 1 U.S. 1"), headers),
            201,
        )
        submit_brief(brief, ctx["attorney"])

        res = api.approve_brief(brief["id"], attorney_headers(ctx["reviewer"]))
        validate_error(res, ApiErrorId.ERR_TOA_UNVERIFIED.value, expected_status=422)


class TestParalegalCitationWorkflow:
    def test_paralegal_can_add_citation_but_cannot_efile_brief(self, api):
        """PRD §3.5: "An `Attorney` or `ParalegalStaff` adds citations to the
        table by supplying the `raw_text` exactly as it appears in the brief and
        an `authority_type` of `CASE`, `STATUTE`, `RULE`, or `SECONDARY`; the
        system derives the `normalized` citation form, starts each citation with
        `verified` false and `verified_at` null, and recomputes the table's
        counts."
        PRD §2.1: "`ParalegalStaff` — support staff who manage transcript
        orders, citations, and filings but can never approve or e-file a brief."

        Design: Corner/rbac/paralegal_can_add_citation_but_cannot_efile_brief
        """
        ctx = setup_briefing_case(court_overrides={"code": "RB3"})
        brief = create_brief(ctx, "OPENING")
        walk_brief_to_ready(ctx, brief)
        toa = _get_toa(api, brief["id"], attorney_headers(ctx["attorney"]))

        res = api.add_citation(
            toa["id"],
            create_citation_payload(raw_text="Test v. Case, 1 U.S. 1"),
            PARALEGAL,
        )
        citation = validate_success(res, 201)
        assert_citation(citation)

        res = api.efile_brief(brief["id"], {"served_party_emails": ["o@x.com"]}, PARALEGAL)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE.value, expected_status=403)
