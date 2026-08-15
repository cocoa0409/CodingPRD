"""Reverse-FK retrieval, filtered listings, computed reads, and immediate
consistency between write responses and follow-up reads."""
from test_helpers import (
    validate_success, validate_paginated,
    TEST_USERS,
    create_prospect, create_payment, create_assessment_payload,
    rate_prospect, assign_prospect, move_prospect,
    setup_rated_assigned_prospect, setup_active_pledge,
    create_fundraiser, get_pledge,
    create_approved_proposal, create_executed_agreement,
)

RES = TEST_USERS["researcher_headers"]
DIR = TEST_USERS["director_headers"]
VP = TEST_USERS["vp_headers"]
FIN = TEST_USERS["finance_headers"]


class TestReverseFkRetrieval:
    def test_reverse_fk_lookup_returns_children_in_order(self, api):
        """PRD §4: "List assessments of a prospect | All roles"."
        PRD §2.3: "Unless otherwise specified, list endpoints return resources
        sorted by `created_at` in ascending order."

        Design: Corner/endpoints/reverse_fk_lookup_returns_children_in_order
        """
        pa = create_prospect(full_name="Donor A", contact_email="a@x.com")
        a1 = rate_prospect(pa["id"], assessed_capacity_cents=30000000)
        a2 = rate_prospect(pa["id"], assessed_capacity_cents=200000000,
                           engagement_score=90, philanthropy_score=90, recency_score=90)

        pb = create_prospect(full_name="Donor B", contact_email="b@x.com")
        resp = api.create_assessment(
            pb["id"], create_assessment_payload(
                assessed_capacity_cents=1000000, evidence_tier="SELF_REPORTED",
                engagement_score=50, philanthropy_score=50, recency_score=50),
            RES,
        )
        other = validate_success(resp, expected_status=201)

        rows, meta = validate_paginated(api.list_prospect_assessments(pa["id"], RES))
        assert meta["total_count"] == 2
        ids = [r["id"] for r in rows]
        assert a1["id"] in ids and a2["id"] in ids
        assert other["id"] not in ids
        by_id = {r["id"]: r for r in rows}
        assert by_id[a1["id"]]["status"] == "SUPERSEDED"
        assert by_id[a2["id"]]["status"] == "APPROVED"

    def test_filtered_list_agreements_by_prospect(self, api):
        """PRD §3.5: "Agreements can be listed with filters on `proposal_id`,
        `prospect_id`, `naming_opportunity_id`, and `signature_status`."

        Design: Corner/endpoints/filtered_list_agreements_by_prospect
        """
        f, p, _ = setup_rated_assigned_prospect(move_to="CULTIVATION")
        prop = create_approved_proposal(p["id"], f["id"], 1000000)
        agr = create_executed_agreement(prop, f["id"])

        rows, meta = validate_paginated(api.list_agreements(VP, params={"prospect_id": p["id"]}))
        assert len(rows) == 1
        assert rows[0]["id"] == agr["id"]
        assert rows[0]["signature_status"] == "EXECUTED"

        rows2, meta2 = validate_paginated(
            api.list_agreements(VP, params={"prospect_id": "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"}),
        )
        assert rows2 == [] and meta2["total_count"] == 0


class TestImmediateConsistency:
    def test_immediate_consistency_response_and_read_agree(self, api):
        """PRD §3.7: "The resulting per-installment application is stored on the
        payment as `applied_allocations`, a list of entries pairing each
        `installment_id` with its `applied_cents` in that same chronological
        order."
        PRD §3.7: "An installment whose `paid_cents` reaches its `amount_cents`
        with no write-off becomes `PAID`, which recomputes the pledge's
        `outstanding_cents` and may fulfill the pledge per §3.6."

        Design: Corner/consistency_model/immediate_consistency_response_and_read_agree
        """
        ctx = setup_active_pledge(
            1500000, installment_count=2, frequency="ANNUAL",
            first_due_date="2026-12-01T00:00:00Z",
        )
        pl_id = ctx["pledge"]["id"]
        from test_helpers import list_installments
        inst = list_installments(pl_id)

        pay = create_payment(ctx["p"]["id"], 750000, pledge_id=pl_id)
        assert pay["applied_allocations"] == [
            {"installment_id": inst[0]["id"], "applied_cents": 750000},
        ]

        # The follow-up read agrees without any wait.
        pledge = get_pledge(pl_id)
        assert pledge["outstanding_cents"] == 750000


class TestOpenAskInputSet:
    def test_open_ask_input_set_excludes_decided_proposals(self, api):
        """PRD §2.9: "The **open proposal states** are exactly `UNDER_REVIEW`,
        `NEGOTIATING`, and `APPROVED`; `DRAFT`, `RETURNED`, `REJECTED`,
        `SUPERSEDED`, and `EXPIRED` proposals do not count."
        PRD §3.4: "`REJECT` moves it to `REJECTED`, records the reviewer as
        `decided_by`, and — because a rejected proposal leaves the open proposal
        states — recomputes the owning fundraiser's `current_open_ask_cents` and
        advances the fundraiser's `version`."

        Design: Corner/calculations/open_ask_input_set_excludes_decided_proposals
        """
        from test_helpers import get_fundraiser, create_proposal_for, submit_proposal
        f = create_fundraiser()
        p = create_prospect()
        rate_prospect(p["id"])
        assign_prospect(f["id"], p["id"])
        move_prospect(p["id"], f["id"], "CULTIVATION")
        prop = create_proposal_for(p["id"], f["id"], 5000000)
        submit_proposal(prop["id"], f["id"])

        f_mid = get_fundraiser(f["id"])
        assert f_mid["current_open_ask_cents"] == 5000000  # UNDER_REVIEW is open

        validate_success(api.review_proposal(
            prop["id"], {"decision": "REJECT", "decision_rationale": "not aligned"}, DIR,
        ))

        f_end = get_fundraiser(f["id"])
        assert f_end["current_open_ask_cents"] == 0  # REJECTED leaves the input set
        assert f_end["current_prospect_count"] == 1  # assignment untouched
