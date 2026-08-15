"""ORC groups and case links: uniqueness, link lifecycle, conjunctive
escalation thresholds, and the confirmation cascade to case priority."""
from test_helpers import (
    ApiErrorId,
    assign_case,
    confirm_link,
    get_case,
    get_group,
    make_analyst_headers,
    make_manager_headers,
    make_manual_case,
    make_orc_group,
    make_store,
    propose_link,
    reject_link,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import ANALYST_1, MANAGER_1


class TestGroupLifecycle:
    def test_group_disrupt_from_identified_returns_invalid_state(self, api):
        """PRD §3.8: "Disrupting an `ACTIVE_MONITORING` group moves it to
        `DISRUPTED` and automatically rejects all of its `PROPOSED` links,
        while confirmed links are retained for audit."
        PRD §2.7: "6. The target entity's own state machine must permit the
        requested transition (`ERR_INVALID_STATE_TRANSITION`, or
        `ERR_DEMAND_NOT_PAYABLE` for a payment posting against a demand that is
        not payable)."

        Design: Corner/state_machines/group_disrupt_from_identified_returns_invalid_state
        """
        group = make_orc_group("Ring Gamma")
        assert group["status"] == "IDENTIFIED"
        resp = api.disrupt_orc_group(group["id"], make_manager_headers(MANAGER_1))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_group_dismiss_blocked_by_proposed_then_confirmed_links(self, api):
        """PRD §3.8: "Dismissing a group — from `IDENTIFIED` or
        `ACTIVE_MONITORING` — requires that no `PROPOSED` links remain
        (`ERR_GROUP_HAS_PROPOSED_LINKS`) and that the confirmed-case count is
        zero (`ERR_GROUP_NOT_LINKABLE`), landing the group in `DISMISSED`."

        Staged gating: a PROPOSED link blocks one way; once confirmed, the
        other.

        Design: Corner/errors/group_dismiss_blocked_by_proposed_then_confirmed_links
        """
        store = make_store(store_number="S084", name="Store 84")
        group = make_orc_group("Ring Delta")
        c1 = make_manual_case(store["id"], manual_loss_cents=1000)
        assign_case(c1["id"], ANALYST_1)
        link = propose_link(c1["id"], group["id"], link_score=50)
        resp1 = api.dismiss_orc_group(group["id"], make_manager_headers(MANAGER_1))
        validate_error(resp1, ApiErrorId.ERR_GROUP_HAS_PROPOSED_LINKS)
        confirm_link(link["id"], MANAGER_1)
        resp2 = api.dismiss_orc_group(group["id"], make_manager_headers(MANAGER_1))
        validate_error(resp2, ApiErrorId.ERR_GROUP_NOT_LINKABLE)

    def test_duplicate_group_name_rejected(self, api):
        """PRD §3.8: "When incidents across stores share a modus operandi, a
        manager registers an ORC group with an enterprise-unique `name`
        (`ERR_DUPLICATE_GROUP_NAME` on collision) and an optional free-text
        `description`; the group starts `IDENTIFIED` with all counters at
        zero."

        Design: Corner/errors/duplicate_group_name_rejected
        """
        make_orc_group("Ring Epsilon")
        resp = api.create_orc_group(
            {"name": "Ring Epsilon", "description": "copycat"},
            make_manager_headers(MANAGER_1),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_GROUP_NAME)


class TestCaseLinks:
    def test_duplicate_link_rejected_but_reproposal_after_rejection_allowed(self, api):
        """PRD §3.8: "The target group must be `IDENTIFIED` or
        `ACTIVE_MONITORING` — linking into a `DISRUPTED` or `DISMISSED` group
        fails with `ERR_GROUP_NOT_LINKABLE` — and at most one non-`REJECTED`
        link may exist for a given case-and-group pair (`ERR_LINK_EXISTS`)."
        PRD §3.8: "Rejecting a link is the symmetric manager action: a
        `PROPOSED` link becomes `REJECTED`, and the group's counters are
        unaffected because the link was never counted."

        Design: Corner/errors/duplicate_link_rejected_but_reproposal_after_rejection_allowed
        """
        store = make_store(store_number="S085", name="Store 85")
        group = make_orc_group("Ring Zeta")
        c1 = make_manual_case(store["id"], manual_loss_cents=1000)
        assign_case(c1["id"], ANALYST_1)
        link = propose_link(c1["id"], group["id"], link_score=60)
        resp = api.create_case_link(
            {"case_id": c1["id"], "orc_group_id": group["id"], "link_score": 70},
            make_analyst_headers(ANALYST_1),
        )
        validate_error(resp, ApiErrorId.ERR_LINK_EXISTS)
        reject_link(link["id"], MANAGER_1)
        reproposed = propose_link(c1["id"], group["id"], link_score=70)
        assert reproposed["status"] == "PROPOSED", "REJECTED links do not block"

    def test_fk_reverse_case_links_by_group(self, api):
        """PRD §3.8: "links list with `case_id`, `orc_group_id`, and `status`
        filters and are read by `link_id`."

        Design: Corner/endpoints/fk_reverse_case_links_by_group
        """
        store = make_store(store_number="S217", name="Store 217")
        group = make_orc_group("Ring Theta")
        c1 = make_manual_case(store["id"], manual_loss_cents=1000)
        c2 = make_manual_case(store["id"], manual_loss_cents=2000)
        propose_link(c1["id"], group["id"], link_score=60)
        propose_link(c2["id"], group["id"], link_score=55)
        headers = make_manager_headers(MANAGER_1)
        _d, meta_g = validate_paginated(
            api.list_case_links(headers, params={"orc_group_id": group["id"]})
        )
        assert meta_g["total_count"] == 2
        d_c, meta_c = validate_paginated(
            api.list_case_links(headers, params={"case_id": c1["id"]})
        )
        assert meta_c["total_count"] == 1
        assert d_c[0]["case_id"] == c1["id"]


class TestEscalationBoundary:
    """Three-input conjunctive threshold, all boundaries inclusive."""

    def _setup_group_with_two_confirmed(self, api):
        """SA/SB stores; cases C1 (SA, 200000), C2 (SB, 150000), C3 (SA,
        150000); L1/L2 CONFIRMED, L3 PROPOSED. Counters: 2 cases / 2 stores /
        350000 exposure."""
        sa = make_store(store_number="S110", name="Store 110", region_code="R2")
        sb = make_store(store_number="S111", name="Store 111", region_code="R2")
        group = make_orc_group("Ring Alpha", description="Multi-store refund crew")
        c1 = make_manual_case(sa["id"], manual_loss_cents=200000)
        c2 = make_manual_case(sb["id"], manual_loss_cents=150000)
        c3 = make_manual_case(sa["id"], manual_loss_cents=150000)
        l1 = propose_link(c1["id"], group["id"], link_score=80)
        l2 = propose_link(c2["id"], group["id"], link_score=70)
        l3 = propose_link(c3["id"], group["id"], link_score=65)
        confirm_link(l1["id"], MANAGER_1)
        confirm_link(l2["id"], MANAGER_1)
        return sa, sb, group, c1, c2, c3, l3

    def test_group_stays_identified_below_three_case_threshold(self, api):
        """PRD §3.8: "The escalation rule then evaluates all three conjuncts
        together, each boundary inclusive: at least 3 confirmed cases, spanning
        at least 2 distinct stores, with combined exposure of at least 500000
        cents."

        With two confirmations the case-count conjunct (2 < 3) is false even
        though the store conjunct already holds: the group stays IDENTIFIED.

        Design: Difficulty/combinatorial_formula/orc_escalation_three_input_conjunction_at_boundary
        """
        _sa, _sb, group, _c1, _c2, _c3, _l3 = self._setup_group_with_two_confirmed(api)
        g = get_group(group["id"])
        assert g["confirmed_case_count"] == 2
        assert g["distinct_store_count"] == 2
        assert g["exposure_cents"] == 350000
        assert g["status"] == "IDENTIFIED", "conjunctive: 2 confirmed cases < 3"

    def test_third_confirmation_at_exact_boundaries_escalates(self, api):
        """PRD §3.8: "The escalation rule then evaluates all three conjuncts
        together, each boundary inclusive: at least 3 confirmed cases, spanning
        at least 2 distinct stores, with combined exposure of at least 500000
        cents."
        PRD §3.8: "When all three hold, the group escalates from `IDENTIFIED`
        to `ACTIVE_MONITORING`, and every confirmed-linked case's `priority`
        recomputes to HIGH."

        The third confirmation lands exactly on all three boundaries:
        3 cases / 2 stores / 500000 cents.

        Design: Difficulty/combinatorial_formula/orc_escalation_three_input_conjunction_at_boundary
        """
        _sa, _sb, group, c1, _c2, _c3, l3 = self._setup_group_with_two_confirmed(api)
        confirm_link(l3["id"], MANAGER_1)
        g = get_group(group["id"])
        assert g["confirmed_case_count"] == 3
        assert g["distinct_store_count"] == 2
        assert g["exposure_cents"] == 500000
        assert g["status"] == "ACTIVE_MONITORING", "all three boundaries inclusive"
        assert get_case(c1["id"])["priority"] == "HIGH", "cascade to linked cases"


class TestLinkConfirmCascade:
    """Depth-3 cascade: confirm -> counters recompute -> group escalates ->
    linked-case priority recomputes."""

    def _setup_escalating_group(self, api):
        """Cases C1 (SA, 300000), C2 (SB, 300000), C3 (SA, 300000); L1/L2
        CONFIRMED (2 cases / 2 stores / 600000), L3 PROPOSED."""
        sa = make_store(store_number="S170", name="Store 170", region_code="R5")
        sb = make_store(store_number="S171", name="Store 171", region_code="R5")
        group = make_orc_group("Ring Beta")
        c1 = make_manual_case(sa["id"], manual_loss_cents=300000)
        c2 = make_manual_case(sb["id"], manual_loss_cents=300000)
        c3 = make_manual_case(sa["id"], manual_loss_cents=300000)
        l1 = propose_link(c1["id"], group["id"], link_score=90)
        l2 = propose_link(c2["id"], group["id"], link_score=85)
        l3 = propose_link(c3["id"], group["id"], link_score=75)
        confirm_link(l1["id"], MANAGER_1)
        confirm_link(l2["id"], MANAGER_1)
        return sa, sb, group, c1, c2, c3, l3

    def test_link_confirmation_recomputes_counters_and_escalates(self, api):
        """PRD §3.8: "Confirmation is a manager's call. The link must be
        `PROPOSED` and its case must be non-terminal and not `MERGED` (both
        failures surface as `ERR_INVALID_STATE_TRANSITION`); on success the
        link becomes `CONFIRMED` and the group's three counters recompute over
        its confirmed links: `confirmed_case_count` counts `CONFIRMED` links,
        `distinct_store_count` counts the distinct stores among the
        confirmed-linked cases, and `exposure_cents` sums those cases'
        `total_loss_cents` — remembering that a `MERGED` case contributes only
        through its surviving target."
        PRD §3.8: "When all three hold, the group escalates from `IDENTIFIED`
        to `ACTIVE_MONITORING`, and every confirmed-linked case's `priority`
        recomputes to HIGH."

        Design: Difficulty/transitive_cascade/case_link_confirm_cascade_depth3
        """
        _sa, _sb, group, _c1, _c2, _c3, l3 = self._setup_escalating_group(api)
        confirm_link(l3["id"], MANAGER_1)
        g = get_group(group["id"])
        assert g["confirmed_case_count"] == 3
        assert g["distinct_store_count"] == 2
        assert g["exposure_cents"] == 900000
        assert g["status"] == "ACTIVE_MONITORING"

    def test_escalation_raises_confirmed_case_priority(self, api):
        """PRD §3.8: "That is the standing priority rule for every case: HIGH
        when any source alert is `ESCALATED` or any confirmed link points at an
        `ACTIVE_MONITORING` group, and `STANDARD` otherwise."
        PRD §3.8: "When all three hold, the group escalates from `IDENTIFIED`
        to `ACTIVE_MONITORING`, and every confirmed-linked case's `priority`
        recomputes to HIGH."

        Design: Difficulty/transitive_cascade/case_link_confirm_cascade_depth3
        """
        _sa, _sb, group, c1, c2, _c3, l3 = self._setup_escalating_group(api)
        assert get_case(c2["id"])["priority"] == "STANDARD", "pre-escalation baseline"
        confirm_link(l3["id"], MANAGER_1)
        assert get_group(group["id"])["status"] == "ACTIVE_MONITORING"
        assert get_case(c2["id"])["priority"] == "HIGH"
        assert get_case(c1["id"])["priority"] == "HIGH"
