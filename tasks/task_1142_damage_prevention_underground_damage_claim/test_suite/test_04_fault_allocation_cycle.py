"""Fault allocation lifecycle: OCC create, propose/contest/revise cycle, rule-default
vs adjudicated shares, and conservation across the negotiation loop (PRD §2.9, §3.4)."""
from datetime import timedelta

from test_helpers import (
    ApiErrorId,
    add_standard_cost_lines,
    assert_case_invoice_conservation,
    assert_fault_allocation,
    begin_investigation,
    create_allocation,
    create_case,
    create_completed_ticket,
    create_excavator,
    create_locator,
    add_evidence,
    finalize_allocation,
    get_allocation,
    get_case,
    get_case_invoice_for_debtor,
    get_success_data,
    list_case_invoices,
    make_excavator_headers,
    make_investigator_headers,
    make_manager_headers,
    parse_iso,
    propose_allocation,
    set_clock,
    setup_case_investigating,
    setup_proposed_allocation,
    validate_error,
    validate_success,
)


def _build_rule_default_and_adjudicated_cases(api):
    """Two identical cases over the same completed ticket: case A priced under the
    MISMARK rule-default table, case B under an adjudicated 5000/5000 split."""
    excavator = create_excavator()
    locator = create_locator()
    ticket, _resp = create_completed_ticket(
        excavator["id"], locator["id"], "1 Main St",
        "2026-05-02T08:00:00Z", "2026-05-02T17:00:00Z", "2026-05-02T07:00:00Z",
    )

    def build_case(shares):
        case = create_case(excavator["id"], "1 Main St", "GAS", "MAJOR",
                           "2026-05-02T10:00:00Z", locate_ticket_id=ticket["id"])
        add_evidence(case["id"], captured_at="2026-05-02T12:00:00Z")
        case = begin_investigation(case["id"], "inv-1")
        allocation = create_allocation(
            case["id"], case["version"], root_cause_code="MISMARK",
            shares=shares, investigator_id="inv-1",
        )
        add_standard_cost_lines(case["id"])
        propose_allocation(allocation["id"], "inv-1")
        allocation = finalize_allocation(allocation["id"], "mgr-1")
        return case, allocation

    case_a, alloc_a = build_case(None)
    shares_b = [
        {"party_type": "EXCAVATOR", "party_id": excavator["id"], "share_bp": 5000},
        {"party_type": "LOCATOR", "party_id": locator["id"], "share_bp": 5000},
    ]
    case_b, alloc_b = build_case(shares_b)
    return excavator, locator, case_a, alloc_a, case_b, alloc_b


class TestRuleDefaultVsAdjudicatedShares:
    def test_rule_default_mismark_split_priced_from_table(self, api):
        """PRD §3.4: "The rule-default table maps each `root_cause_code` to a fixed share
        distribution: `NO_TICKET` assigns the full 10000 to the excavator;
        `EXPIRED_TICKET` assigns 8000 to the excavator and 2000 to the facility owner;
        `MISMARK` assigns 7000 to the locator and 3000 to the excavator; `LOCATE_LATE`
        assigns 6000 to the locator and 4000 to the excavator; `OWNER_ABANDONED` assigns
        the full 10000 to the facility owner." and "When `shares` is omitted, the server
        fills them from the rule-default table below and records `basis` as
        `RULE_DEFAULT`"

        Design: Difficulty/dual_variant_calc/fault_default_vs_adjudicated_shares_diverge
        """
        excavator, locator, case_a, alloc_a, _case_b, _alloc_b = (
            _build_rule_default_and_adjudicated_cases(api)
        )
        assert alloc_a["basis"] == "RULE_DEFAULT"
        inv_loc = get_case_invoice_for_debtor(case_a["id"], locator["id"])
        inv_exc = get_case_invoice_for_debtor(case_a["id"], excavator["id"])
        assert inv_loc["invoiced_cents"] == 84000, (
            f"locator at 7000 bp of 120000 subtotal: expected 84000, got {inv_loc['invoiced_cents']}"
        )
        assert inv_exc["invoiced_cents"] == 36000, (
            f"excavator at 3000 bp of 120000 subtotal: expected 36000, got {inv_exc['invoiced_cents']}"
        )

    def test_adjudicated_even_split_diverges_from_rule_default(self, api):
        """PRD §3.4: "when supplied, the server takes them verbatim and records `basis`
        as `ADJUDICATED`." PRD §3.5: "For every non-largest share, the invoiced amount is
        the case's `subtotal_cents` multiplied by that share's `share_bp`, divided by
        10000, rounded half-up to a whole cent." Identical case data under a 5000/5000
        adjudicated split bills the locator 60000, not the rule-default 84000.

        Design: Difficulty/dual_variant_calc/fault_default_vs_adjudicated_shares_diverge
        """
        excavator, locator, case_a, _alloc_a, case_b, alloc_b = (
            _build_rule_default_and_adjudicated_cases(api)
        )
        assert alloc_b["basis"] == "ADJUDICATED"
        inv_loc_b = get_case_invoice_for_debtor(case_b["id"], locator["id"])
        inv_exc_b = get_case_invoice_for_debtor(case_b["id"], excavator["id"])
        inv_loc_a = get_case_invoice_for_debtor(case_a["id"], locator["id"])
        assert inv_loc_b["invoiced_cents"] == 60000
        assert inv_exc_b["invoiced_cents"] == 60000
        assert inv_loc_a["invoiced_cents"] != inv_loc_b["invoiced_cents"], (
            "identical case data under the two share variants must diverge in money"
        )


class TestContestReviseCycle:
    def test_full_negotiation_loop_status_walk(self, api):
        """PRD §3.4: "The cycle `PROPOSED → CONTESTED → DRAFT → PROPOSED` may repeat any
        number of times." and "Revision moves the allocation back to `DRAFT`, increments
        `revision_no` by 1"

        Design: Difficulty/non_linear_state_machine/fault_allocation_contest_revise_cycle
        """
        excavator = create_excavator()
        case = create_case(excavator["id"], "4 Maple Dr", "GAS", "MAJOR", "2026-05-07T09:00:00Z")
        add_evidence(case["id"], captured_at="2026-05-07T10:00:00Z")
        case = begin_investigation(case["id"], "inv-1")
        shares = [
            {"party_type": "EXCAVATOR", "party_id": excavator["id"], "share_bp": 6000},
            {"party_type": "FACILITY_OWNER", "party_id": None, "share_bp": 4000},
        ]
        allocation = create_allocation(case["id"], case["version"],
                                       root_cause_code="NO_TICKET", shares=shares)
        assert allocation["status"] == "DRAFT"

        proposed = propose_allocation(allocation["id"], "inv-1")
        assert proposed["status"] == "PROPOSED"

        resp = api.contest_fault_allocation(
            allocation["id"], {"contest_note": "too high"},
            make_excavator_headers(excavator["id"]),
        )
        contested = validate_success(resp)
        assert contested["status"] == "CONTESTED"

        resp = api.revise_fault_allocation(allocation["id"], {}, make_investigator_headers("inv-1"))
        revised = validate_success(resp)
        assert revised["status"] == "DRAFT"
        assert revised["revision_no"] == 1, "one loop must increment revision_no to 1"

        re_proposed = propose_allocation(allocation["id"], "inv-1")
        assert re_proposed["status"] == "PROPOSED"

        final = finalize_allocation(allocation["id"], "mgr-1")
        assert final["status"] == "FINAL"

    def test_revise_returns_case_to_investigating(self, api):
        """PRD §3.4: "Revision moves the allocation back to `DRAFT`, increments
        `revision_no` by 1, clears `proposed_at` and `contest_deadline_at` to null,
        returns the case's `investigation_status` to `INVESTIGATING`, and bumps both the
        case's and the allocation's `version`."

        Design: Difficulty/non_linear_state_machine/fault_allocation_contest_revise_cycle
        """
        excavator = create_excavator()
        case = create_case(excavator["id"], "4 Maple Dr", "GAS", "MAJOR", "2026-05-07T09:00:00Z")
        add_evidence(case["id"], captured_at="2026-05-07T10:00:00Z")
        case = begin_investigation(case["id"], "inv-1")
        shares = [
            {"party_type": "EXCAVATOR", "party_id": excavator["id"], "share_bp": 6000},
            {"party_type": "FACILITY_OWNER", "party_id": None, "share_bp": 4000},
        ]
        allocation = create_allocation(case["id"], case["version"],
                                       root_cause_code="NO_TICKET", shares=shares)
        propose_allocation(allocation["id"], "inv-1")
        validate_success(api.contest_fault_allocation(
            allocation["id"], {"contest_note": "too high"},
            make_excavator_headers(excavator["id"]),
        ))
        revised = validate_success(
            api.revise_fault_allocation(allocation["id"], {}, make_investigator_headers("inv-1"))
        )
        assert revised["proposed_at"] is None
        assert revised["contest_deadline_at"] is None
        case_after = get_case(case["id"])
        assert case_after["investigation_status"] == "INVESTIGATING", (
            "revise must return the case to INVESTIGATING so re-propose can succeed"
        )


class TestContestErrorSemantics:
    def test_contest_final_allocation_state_error_beats_temporal(self, api):
        """PRD §3.4: "Contesting from any status other than `PROPOSED` is rejected with
        `ERR_INVALID_STATE` — the state check is evaluated before the temporal check —
        and contesting after `contest_deadline_at` has passed is rejected with
        `ERR_CONTEST_WINDOW_CLOSED` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/contest_final_allocation_state_error_beats_temporal
        """
        excavator = create_excavator()
        case = create_case(excavator["id"], "30 Glen Ave", "GAS", "MAJOR", "2026-05-01T09:00:00Z")
        add_evidence(case["id"], captured_at="2026-05-01T10:00:00Z")
        case = begin_investigation(case["id"], "inv-1")
        shares = [{"party_type": "EXCAVATOR", "party_id": excavator["id"], "share_bp": 10000}]
        allocation = create_allocation(case["id"], case["version"],
                                       root_cause_code="NO_TICKET", shares=shares)
        propose_allocation(allocation["id"], "inv-1")
        finalized = finalize_allocation(allocation["id"], "mgr-1")
        assert finalized["status"] == "FINAL"
        set_clock("2026-05-12T12:00:00Z")  # past the 10-day contest window
        resp = api.contest_fault_allocation(
            allocation["id"], {"contest_note": "late"}, make_excavator_headers(excavator["id"]),
        )
        error = validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        assert error["error_id"] != "ERR_CONTEST_WINDOW_CLOSED"

    def test_contest_proposed_allocation_past_window_is_temporal_error(self, api):
        """PRD §3.4: "contesting after `contest_deadline_at` has passed is rejected with
        `ERR_CONTEST_WINDOW_CLOSED` (HTTP 409)." With the allocation still `PROPOSED`
        (no state violation), the temporal rule surfaces — the control arm proving the
        state-vs-temporal ordering in the paired test.

        Design: Difficulty/priority_pair_validation_conflict/contest_final_allocation_state_error_beats_temporal
        """
        excavator = create_excavator()
        case = create_case(excavator["id"], "30 Glen Ave", "GAS", "MAJOR", "2026-05-01T09:00:00Z")
        add_evidence(case["id"], captured_at="2026-05-01T10:00:00Z")
        case = begin_investigation(case["id"], "inv-1")
        shares = [{"party_type": "EXCAVATOR", "party_id": excavator["id"], "share_bp": 10000}]
        allocation = create_allocation(case["id"], case["version"],
                                       root_cause_code="NO_TICKET", shares=shares)
        propose_allocation(allocation["id"], "inv-1")  # proposed at default clock 2026-05-01
        set_clock("2026-05-12T12:00:00Z")  # past contest_deadline_at
        resp = api.contest_fault_allocation(
            allocation["id"], {"contest_note": "late"}, make_excavator_headers(excavator["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CONTEST_WINDOW_CLOSED, expected_status=409)

    def test_contest_after_window_returns_temporal_error(self, api):
        """PRD §3.4: "contesting after `contest_deadline_at` has passed is rejected with
        `ERR_CONTEST_WINDOW_CLOSED` (HTTP 409)."

        Design: Corner/validations/contest_after_window_returns_temporal_error
        """
        excavator = create_excavator()
        case = create_case(excavator["id"], "23 Theta St", "GAS", "MINOR", "2026-05-01T09:00:00Z")
        add_evidence(case["id"], captured_at="2026-05-01T10:00:00Z")
        case = begin_investigation(case["id"], "inv-1")
        shares = [{"party_type": "EXCAVATOR", "party_id": excavator["id"], "share_bp": 10000}]
        allocation = create_allocation(case["id"], case["version"],
                                       root_cause_code="NO_TICKET", shares=shares)
        propose_allocation(allocation["id"], "inv-1")
        set_clock("2026-05-12T00:00:00Z")
        resp = api.contest_fault_allocation(
            allocation["id"], {"contest_note": "late"}, make_excavator_headers(excavator["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CONTEST_WINDOW_CLOSED, expected_status=409)
        allocation_after = get_allocation(allocation["id"])
        assert allocation_after["status"] == "PROPOSED"


class TestProposeSideEffect:
    def test_propose_side_effect_moves_case_to_fault_proposed(self, api):
        """PRD §3.4: "on success the allocation moves to `PROPOSED`, `proposed_at` is set
        to the current logical clock, `contest_deadline_at` is computed as ten days after
        `proposed_at`, the case's `investigation_status` moves to `FAULT_PROPOSED`, and
        the case's `version` bumps."

        Design: Corner/state_machines/propose_side_effect_moves_case_to_fault_proposed
        """
        ctx = setup_case_investigating(severity="MINOR", dig_site_address="10 Tenth St")
        allocation = create_allocation(ctx["case"]["id"], ctx["case_version"],
                                       root_cause_code="NO_TICKET")
        proposed = propose_allocation(allocation["id"], "inv-1")
        assert_fault_allocation(proposed)
        case_after = get_case(ctx["case"]["id"])
        assert case_after["investigation_status"] == "FAULT_PROPOSED"
        assert proposed["proposed_at"] is not None
        delta = parse_iso(proposed["contest_deadline_at"]) - parse_iso(proposed["proposed_at"])
        assert delta == timedelta(days=10), (
            f"contest_deadline_at must be proposed_at + 10 days, got {delta}"
        )


class TestOptimisticConcurrency:
    def test_occ_stale_version_on_allocation_create(self, api):
        """PRD §2.9: "creating a `FaultAllocation` requires the request body to carry
        `expected_damage_case_version`, holding the client's last-observed `version` of
        the target `DamageCase`. If the value does not match the case's current
        `version` — because another writer has advanced the case since the client last
        read it — the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_allocation_create
        """
        excavator = create_excavator()
        case = create_case(excavator["id"], "46 Zayin St", "GAS", "MINOR",
                           "2026-05-02T09:00:00Z")
        stale_version = case["version"]  # version observed before subsequent writes
        add_evidence(case["id"])
        case = begin_investigation(case["id"], "inv-1")
        fresh_version = case["version"]
        assert fresh_version > stale_version

        resp_stale = api.create_fault_allocation(
            {
                "damage_case_id": case["id"], "root_cause_code": "NO_TICKET",
                "expected_damage_case_version": stale_version,
            },
            make_investigator_headers("inv-1"),
        )
        validate_error(resp_stale, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        resp_fresh = api.create_fault_allocation(
            {
                "damage_case_id": case["id"], "root_cause_code": "NO_TICKET",
                "expected_damage_case_version": fresh_version,
            },
            make_investigator_headers("inv-1"),
        )
        allocation = validate_success(resp_fresh, expected_status=201)
        assert allocation["status"] == "DRAFT"


class TestSharesValidation:
    def test_shares_misum_rejected(self, api):
        """PRD §3.4: "when supplied, the `share_bp` values must sum to exactly 10000
        (otherwise `ERR_SHARES_MUST_SUM_10000`, HTTP 422)."

        Design: Corner/validations/shares_misum_rejected
        """
        excavator = create_excavator()
        locator = create_locator()
        case = create_case(excavator["id"], "22 Eta St", "GAS", "MINOR", "2026-05-02T09:00:00Z")
        case = begin_investigation(case["id"], "inv-1")
        resp = api.create_fault_allocation(
            {
                "damage_case_id": case["id"],
                "root_cause_code": "MISMARK",
                "expected_damage_case_version": case["version"],
                "shares": [
                    {"party_type": "EXCAVATOR", "party_id": excavator["id"], "share_bp": 6000},
                    {"party_type": "LOCATOR", "party_id": locator["id"], "share_bp": 3000},
                ],
            },
            make_investigator_headers("inv-1"),
        )
        validate_error(resp, ApiErrorId.ERR_SHARES_MUST_SUM_10000, expected_status=422)


class TestReviseConservation:
    def _setup_contested(self, api):
        excavator = create_excavator()
        locator = create_locator()
        case = create_case(excavator["id"], "90 Cliff Rd", "GAS", "MAJOR", "2026-05-13T09:00:00Z")
        add_evidence(case["id"], captured_at="2026-05-13T10:00:00Z")
        case = begin_investigation(case["id"], "inv-1")
        shares = [
            {"party_type": "EXCAVATOR", "party_id": excavator["id"], "share_bp": 6000},
            {"party_type": "LOCATOR", "party_id": locator["id"], "share_bp": 4000},
        ]
        allocation = create_allocation(case["id"], case["version"],
                                       root_cause_code="MISMARK", shares=shares)
        add_standard_cost_lines(case["id"])
        propose_allocation(allocation["id"], "inv-1")
        validate_success(api.contest_fault_allocation(
            allocation["id"], {"contest_note": "share dispute"},
            make_excavator_headers(excavator["id"]),
        ))
        return excavator, locator, case, allocation

    def test_revise_cycle_conserves_allocation_mass(self, api):
        """PRD §3.5: "The largest share's invoiced amount is the case's `subtotal_cents`
        minus the sum of the other invoices' amounts — this absorbs any remainder so
        that the sum of `invoiced_cents` across all created invoices equals the case's
        `subtotal_cents` exactly."

        Design: Difficulty/compensating_invariant/revise_cycle_conserves_allocation_mass
        """
        excavator, locator, case, allocation = self._setup_contested(api)
        revised_shares = [
            {"party_type": "EXCAVATOR", "party_id": excavator["id"], "share_bp": 5000},
            {"party_type": "LOCATOR", "party_id": locator["id"], "share_bp": 5000},
        ]
        revised = validate_success(api.revise_fault_allocation(
            allocation["id"], {"shares": revised_shares}, make_investigator_headers("inv-1"),
        ))
        assert sum(s["share_bp"] for s in revised["shares"]) == 10000
        propose_allocation(allocation["id"], "inv-1")
        finalize_allocation(allocation["id"], "mgr-1")

        inv_exc = get_case_invoice_for_debtor(case["id"], excavator["id"])
        inv_loc = get_case_invoice_for_debtor(case["id"], locator["id"])
        assert inv_exc["invoiced_cents"] == 60000
        assert inv_loc["invoiced_cents"] == 60000
        case_after = get_case(case["id"])
        assert case_after["subtotal_cents"] == 120000
        assert_case_invoice_conservation(case_after, [inv_exc, inv_loc])

    def test_revise_with_mis_summed_shares_rejected(self, api):
        """PRD §3.4: "when `shares` is supplied in revise, it replaces the existing array
        and must still sum to exactly 10000 (otherwise `ERR_SHARES_MUST_SUM_10000`)."

        Design: Difficulty/compensating_invariant/revise_cycle_conserves_allocation_mass
        """
        excavator, locator, _case, allocation = self._setup_contested(api)
        bad_shares = [
            {"party_type": "EXCAVATOR", "party_id": excavator["id"], "share_bp": 6000},
            {"party_type": "LOCATOR", "party_id": locator["id"], "share_bp": 3999},
        ]
        resp = api.revise_fault_allocation(
            allocation["id"], {"shares": bad_shares}, make_investigator_headers("inv-1"),
        )
        validate_error(resp, ApiErrorId.ERR_SHARES_MUST_SUM_10000, expected_status=422)
        allocation_after = get_allocation(allocation["id"])
        assert allocation_after["status"] == "CONTESTED"


class TestFinalizeRbac:
    def test_excavator_cannot_finalize_returns_forbidden(self, api):
        """PRD §2.1: "If the caller's role is not listed in the endpoint's authorized
        role list, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)." The
        finalize endpoint lists `RecoveryManager` only (PRD §4).

        Design: Corner/rbac/excavator_cannot_finalize_returns_forbidden
        """
        ctx = setup_proposed_allocation(
            root_cause_code="NO_TICKET", with_standard_costs=False,
            dig_site_address="44 He St",
        )
        excavator = ctx["excavator"]
        resp = api.finalize_fault_allocation(
            ctx["allocation"]["id"], {}, make_excavator_headers(excavator["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, expected_status=403)
        allocation_after = get_allocation(ctx["allocation"]["id"])
        assert allocation_after["status"] == "PROPOSED"
