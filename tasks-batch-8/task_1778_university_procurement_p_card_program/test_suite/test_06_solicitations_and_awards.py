"""Competitive sourcing: deadlines, scoring, award gates, suspension cascades."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_competitive_requisition,
    create_declared_asset,
    create_department,
    create_open_solicitation,
    create_vendor,
    get_success_data,
    set_clock,
    submit_quote,
    validate_error,
    validate_paginated,
    validate_success,
    make_requester_headers,
)
from test_helpers.fixtures import ADMIN, BUYER, DIRECTOR, SURPLUS_MANAGER

ADMIN_H = ADMIN
BUYER_H = BUYER
DIR_H = DIRECTOR


def _four_quote_setup(api):
    """Requisition 3,000,000 at its PURCHASING step + OPEN solicitation with
    four quotes: V2 2,900,000 / V3 3,100,000 / V4 3,000,000 / V5 3,200,000."""
    set_clock("2026-08-01T00:00:00Z")
    dept = create_department(name="Athletics")
    vendors = {name: create_vendor(legal_name=name) for name in ("V2", "V3", "V4", "V5")}
    req = create_competitive_requisition(
        total_cents=3000000, department_id=dept["id"], vendor_id=vendors["V2"]["id"],
    )
    sol = create_open_solicitation(req["id"], deadline="2026-08-08T00:00:00Z")
    quotes = {
        "q2": submit_quote(sol["id"], vendors["V2"]["id"], 2900000),
        "q3": submit_quote(sol["id"], vendors["V3"]["id"], 3100000),
        "q4": submit_quote(sol["id"], vendors["V4"]["id"], 3000000),
        "q5": submit_quote(sol["id"], vendors["V5"]["id"], 3200000),
    }
    return req, sol, vendors, quotes


class TestVendorSuspensionAwardUnwind:
    def test_pre_close_suspension_shrinks_eligible_pool(self, api):
        """PRD §3.1: "every quote from that vendor still `SUBMITTED` on an `OPEN`
        or `CLOSED` solicitation is immediately `DISQUALIFIED`".
        PRD §3.4: "The price component of a quote is one hundred multiplied by the
        lowest `price_cents` among the quotes eligible at close — meaning
        `SUBMITTED` with an `ACTIVE` vendor at that moment, a pinning that is
        never re-derived later — divided by the quote's own `price_cents`."

        Design: Difficulty/transitive_cascade/vendor_suspension_award_unwind_cascade
        """
        req, sol, vendors, quotes = _four_quote_setup(api)
        get_success_data(
            api.suspend_vendor(vendors["V2"]["id"], {"reason": "debarment review"}, ADMIN_H)
        )
        q2 = get_success_data(api.get_solicitation(sol["id"], ADMIN_H))
        listed, _ = validate_paginated(api.list_solicitation_quotes(sol["id"], ADMIN_H))
        status_by_id = {q["id"]: q["status"] for q in listed}
        assert status_by_id[quotes["q2"]["id"]] == "DISQUALIFIED"

        set_clock("2026-08-08T00:00:00Z")
        get_success_data(api.close_solicitation(sol["id"], BUYER_H))
        awarded = get_success_data(api.award_solicitation(sol["id"], {}, DIR_H))
        # V2 excluded from the pool; min eligible price is 3,000,000, so V4's
        # score is 0.70 * 100 = 70.00, beating V3 (67.74) and V5 (65.63).
        assert awarded["awarded_quote_id"] == quotes["q4"]["id"]
        req_after = get_success_data(api.get_requisition(req["id"], ADMIN_H))
        assert req_after["vendor_id"] == vendors["V4"]["id"]
        assert req_after["sourcing_method"] == "COMPETITIVE_BID"

    def test_post_award_suspension_unwinds_award_chain(self, api):
        """PRD §3.1: "if the vendor held an awarded quote, that quote too is
        disqualified and its `AWARDED` solicitation collapses to `CANCELLED`; and
        any requisition referenced by such a cancelled solicitation that is
        currently `SUBMITTED` is returned to its requester in `RETURNED` status
        with `returned_reason` recorded as `VENDOR_SUSPENDED`, its approval
        progress discarded."

        Design: Difficulty/transitive_cascade/vendor_suspension_award_unwind_cascade
        """
        req, sol, vendors, quotes = _four_quote_setup(api)
        # Design-instance trigger step 1: suspend non-winner V2 pre-close so its
        # quote is DISQUALIFIED and leaves the eligible pool (PRD §3.1); with the
        # min eligible price then 3,000,000, V4's quote scores 70.00 and wins.
        get_success_data(
            api.suspend_vendor(vendors["V2"]["id"], {"reason": "debarment review"}, ADMIN_H)
        )
        set_clock("2026-08-08T00:00:00Z")
        get_success_data(api.close_solicitation(sol["id"], BUYER_H))
        awarded = get_success_data(api.award_solicitation(sol["id"], {}, DIR_H))
        assert awarded["awarded_quote_id"] == quotes["q4"]["id"]

        get_success_data(
            api.suspend_vendor(vendors["V4"]["id"], {"reason": "sanctions hit"}, ADMIN_H)
        )
        sol_after = get_success_data(api.get_solicitation(sol["id"], ADMIN_H))
        assert sol_after["status"] == "CANCELLED"

        v4_quotes, _ = validate_paginated(
            api.list_vendor_quotes(vendors["V4"]["id"], ADMIN_H)
        )
        assert v4_quotes[0]["status"] == "DISQUALIFIED"

        req_after = get_success_data(api.get_requisition(req["id"], ADMIN_H))
        assert req_after["status"] == "RETURNED"
        assert req_after["returned_reason"] == "VENDOR_SUSPENDED"

        # Non-winning quotes of still-active vendors stay NOT_AWARDED.
        listed, _ = validate_paginated(api.list_solicitation_quotes(sol["id"], ADMIN_H))
        status_by_id = {q["id"]: q["status"] for q in listed}
        assert status_by_id[quotes["q3"]["id"]] == "NOT_AWARDED"
        assert status_by_id[quotes["q5"]["id"]] == "NOT_AWARDED"


class TestSolicitationDeadlineHalfOpen:
    def test_solicitation_deadline_half_open_both_faces(self, api):
        """PRD §3.4: "Quotes are accepted only while the logical clock is strictly
        earlier than the `response_deadline`; at or after the deadline, submission
        fails with `ERR_SOLICITATION_EXPIRED`."
        PRD §3.4: "Closing, performed by the buyer, requires the logical clock to
        have reached the `response_deadline` (otherwise
        `ERR_SOLICITATION_DEADLINE_NOT_PASSED`)".

        Design: Corner/state_machines/solicitation_deadline_half_open_both_sides
        """
        set_clock("2026-08-01T00:00:00Z")
        dept = create_department(name="UrbanPlanning")
        v1 = create_vendor(legal_name="BuildCo")
        v2 = create_vendor(legal_name="DesignCo")
        req = create_competitive_requisition(
            total_cents=3000000, department_id=dept["id"], vendor_id=v1["id"],
        )
        sol = create_open_solicitation(req["id"], deadline="2026-08-08T00:00:00Z")
        submit_quote(sol["id"], v1["id"], 3000000)

        set_clock("2026-08-07T23:59:59Z")
        early_close = api.close_solicitation(sol["id"], BUYER_H)
        validate_error(early_close, ApiErrorId.ERR_SOLICITATION_DEADLINE_NOT_PASSED, 409)

        set_clock("2026-08-08T00:00:00Z")
        late_quote = api.create_quote(
            sol["id"], {"vendor_id": v2["id"], "price_cents": 2900000}, BUYER_H
        )
        validate_error(late_quote, ApiErrorId.ERR_SOLICITATION_EXPIRED, 409)
        closed = get_success_data(api.close_solicitation(sol["id"], BUYER_H))
        assert closed["status"] == "CLOSED"


class TestAwardAndCancelStateGates:
    def test_award_requires_closed_and_awarded_not_cancellable(self, api):
        """PRD §3.4: "Award belongs to the `ProcurementDirector` and requires a
        `CLOSED` solicitation (otherwise `ERR_SOLICITATION_NOT_CLOSED`)."
        PRD §3.4: "A buyer may instead cancel an `OPEN` or `CLOSED` solicitation
        outright (from any other status, `ERR_SOLICITATION_NOT_CANCELLABLE`)".

        Design: Corner/state_machines/award_and_cancel_wrong_state_rejections
        """
        set_clock("2026-08-01T00:00:00Z")
        dept = create_department(name="Comm")
        va = create_vendor(legal_name="QA")
        vb = create_vendor(legal_name="QB")
        vc = create_vendor(legal_name="QC")
        req = create_competitive_requisition(
            total_cents=3000000, department_id=dept["id"], vendor_id=va["id"],
        )
        sol = create_open_solicitation(req["id"], deadline="2026-08-08T00:00:00Z")
        submit_quote(sol["id"], va["id"], 3100000)
        qb = submit_quote(sol["id"], vb["id"], 3000000)
        submit_quote(sol["id"], vc["id"], 3200000)

        early_award = api.award_solicitation(sol["id"], {}, DIR_H)
        validate_error(early_award, ApiErrorId.ERR_SOLICITATION_NOT_CLOSED, 409)

        set_clock("2026-08-08T00:00:00Z")
        get_success_data(api.close_solicitation(sol["id"], BUYER_H))
        awarded = get_success_data(api.award_solicitation(sol["id"], {}, DIR_H))
        assert awarded["status"] == "AWARDED"
        # Lowest price wins: 3,000,000 quote scores 70.00 vs 67.74 and 65.63.
        assert awarded["awarded_quote_id"] == qb["id"]

        cancel = api.cancel_solicitation(sol["id"], BUYER_H)
        validate_error(cancel, ApiErrorId.ERR_SOLICITATION_NOT_CANCELLABLE, 409)


class TestAwardScoreTieAndOverride:
    def test_award_tie_breaks_by_submission_order_and_override_gate(self, api):
        """PRD §3.4: "The computed winner is the eligible quote with the highest
        score, ties broken first by the earliest `submitted_at` and then by the
        earliest `created_at` — the quote `id` is never consulted."
        PRD §3.4: "The director may award a different quote by passing its
        `quote_id`, but only with an `override_reason`; diverging from the
        computed winner without one is rejected with `ERR_AWARD_NOT_TOP_SCORE`."

        Design: Corner/calculations/award_score_tie_and_override_gate
        """
        set_clock("2026-08-01T00:00:00Z")
        dept = create_department(name="Music2")
        va = create_vendor(legal_name="TieA")
        vb = create_vendor(legal_name="TieB")
        vc = create_vendor(legal_name="TieC")
        req = create_competitive_requisition(
            total_cents=3000000, department_id=dept["id"], vendor_id=va["id"],
        )
        sol = create_open_solicitation(req["id"], deadline="2026-08-08T00:00:00Z")
        qa = submit_quote(sol["id"], va["id"], 3050000)
        qb = submit_quote(sol["id"], vb["id"], 3050000)
        submit_quote(sol["id"], vc["id"], 3050000)

        set_clock("2026-08-08T00:00:00Z")
        get_success_data(api.close_solicitation(sol["id"], BUYER_H))
        quotes, _ = validate_paginated(
            api.list_solicitation_quotes(sol["id"], ADMIN_H)
        )
        # Identical price, no certifications: 0.70*100 + 0 + 0 = 70.00 each.
        for q in quotes:
            assert q["score"] == pytest.approx(70.00, abs=0.001)

        named = api.award_solicitation(sol["id"], {"quote_id": qb["id"]}, DIR_H)
        validate_error(named, ApiErrorId.ERR_AWARD_NOT_TOP_SCORE, 409)

        awarded = get_success_data(api.award_solicitation(sol["id"], {}, DIR_H))
        assert awarded["awarded_quote_id"] == qa["id"], (
            "full tie resolves to the earliest-submitted, earliest-created quote"
        )


class TestAwardMinQuotesAndEmptyPool:
    def test_award_min_quotes_and_empty_pool(self, api):
        """PRD §3.4: "If the pool holds fewer quotes than the solicitation's
        `min_quotes`, the award proceeds only when an `override_reason` is
        documented, and is rejected with `ERR_INSUFFICIENT_QUOTES` otherwise."
        PRD §3.4: "an empty pool rejects the award with `ERR_NO_ELIGIBLE_QUOTES`".

        Design: Corner/calculations/award_min_quotes_and_empty_pool
        """
        set_clock("2026-08-01T00:00:00Z")
        dept = create_department(name="PubHealth")
        va = create_vendor(legal_name="PA")
        vb = create_vendor(legal_name="PB")
        vc = create_vendor(legal_name="PC")

        # S1: two eligible quotes against the default min_quotes of 3.
        r1 = create_competitive_requisition(
            total_cents=3000000, department_id=dept["id"], vendor_id=va["id"],
        )
        s1 = create_open_solicitation(r1["id"], deadline="2026-08-05T00:00:00Z")
        qa = submit_quote(s1["id"], va["id"], 3000000)
        submit_quote(s1["id"], vb["id"], 3100000)

        # S2: min_quotes 1, but the only quote's vendor is suspended pre-close.
        r2 = create_competitive_requisition(
            total_cents=2600000, department_id=dept["id"], vendor_id=vc["id"],
        )
        s2 = create_open_solicitation(
            r2["id"], deadline="2026-08-05T00:00:00Z", min_quotes=1
        )
        submit_quote(s2["id"], vc["id"], 2600000)
        get_success_data(
            api.suspend_vendor(vc["id"], {"reason": "license lapsed"}, ADMIN_H)
        )

        set_clock("2026-08-05T00:00:00Z")
        get_success_data(api.close_solicitation(s1["id"], BUYER_H))
        get_success_data(api.close_solicitation(s2["id"], BUYER_H))

        short = api.award_solicitation(s1["id"], {}, DIR_H)
        validate_error(short, ApiErrorId.ERR_INSUFFICIENT_QUOTES, 409)

        overridden = get_success_data(
            api.award_solicitation(
                s1["id"], {"override_reason": "emergency procurement"}, DIR_H
            )
        )
        assert overridden["status"] == "AWARDED"
        assert overridden["awarded_quote_id"] == qa["id"]

        empty = api.award_solicitation(s2["id"], {}, DIR_H)
        validate_error(empty, ApiErrorId.ERR_NO_ELIGIBLE_QUOTES, 409)


class TestDuplicateQuoteAndSelfClaim:
    def test_duplicate_quote_and_self_claim_forbidden(self, api):
        """PRD §3.4: "a vendor may hold only one `SUBMITTED` quote per
        solicitation, a second attempt being rejected with `ERR_DUPLICATE_QUOTE`".
        PRD §3.9: "a claimant different from the owning department (otherwise
        `ERR_SELF_CLAIM_FORBIDDEN`)".

        Design: Corner/validations/duplicate_quote_and_self_claim_forbidden
        """
        set_clock("2026-08-01T00:00:00Z")
        dept = create_department(name="DOne")
        va = create_vendor(legal_name="VA")
        req = create_competitive_requisition(
            total_cents=3000000, department_id=dept["id"], vendor_id=va["id"],
        )
        sol = create_open_solicitation(req["id"], deadline="2026-08-08T00:00:00Z")
        submit_quote(sol["id"], va["id"], 3000000)
        dup = api.create_quote(
            sol["id"], {"vendor_id": va["id"], "price_cents": 2900000}, BUYER_H
        )
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_QUOTE, 409)

        asset = create_declared_asset(
            department_id=dept["id"], asset_tag="AST-20", description="van",
            condition="FAIR", estimated_value_cents=800000,
        )
        self_claim = api.claim_surplus_asset(
            asset["id"], {"claiming_department_id": dept["id"]},
            make_requester_headers("req-user-1"),
        )
        validate_error(self_claim, ApiErrorId.ERR_SELF_CLAIM_FORBIDDEN, 403)
        live = get_success_data(api.get_surplus_asset(asset["id"], ADMIN_H))
        assert live["status"] == "DECLARED"
