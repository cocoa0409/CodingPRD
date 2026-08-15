# Worklog — task_1276_subcontractor_buyout_contract_award

## Step 1: Create task directory — 2026-08-12T15:19:00.000Z

Directory `tasks/task_1276_subcontractor_buyout_contract_award/` and `workspace/` subdirectory pre-assigned and already existing (orchestrator instruction: Step 1 treated as done; no auto-index scan run). Recorded here for completeness.


## Step 2: Scaffold generation — 2026-08-12T15:45:00.000Z

Generated SCAFFOLD.yaml (§1.0–§1.7), SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8, 9 rules × 2 instances), SCAFFOLD_CORNER_DESIGN.yaml (§1.9, 57 active + 15 stub instances) at harder-than-expert difficulty. scaffold_lint.py verdict: clean lint (54 endpoints, 10 entities, 883 calls scanned).

Design decisions worth recording:
- Archetype: multi-party negotiation + compliance/audit; hierarchical topology (Project -> TradePackage -> Bid/ScopeGap/Subcontract -> NegotiationRound/InsuranceCertificate/BondDecision/ScheduleOfValues/ChangeOrder) with a self-referential replacement chain on Subcontract.
- api_prefix set to "" (empty = server root) because the URL space is multi-rooted; scaffold_lint's collection-segment derivation requires single-GETs at <prefix>/<segment>/{id}, and nesting every collection under /projects/{id}/... would have distorted the API surface.
- All parent path placeholders renamed to {id} — lint check (f) hardcodes {id} when matching sub-resource templates.
- Difficulty density levers: dual-variant calcs (PROVISIONAL vs FINAL buyout savings on TradePackage; FULL_ENDORSEMENTS vs GAP_ANALYSIS insurance verdicts on InsuranceCertificate); SOV cumulative-difference rounding pinned against the naive per-line interpretation (100000 @ 10/10/10 -> 33333/33334/33333); change-authority cumulative ratio divides by contract_value_cents AT APPROVAL TIME (moving denominator keeps the 0.10 boundary exactly reachable twice, then 100001 breaks it); trade_risk_score rewritten to intrinsic factors (value band 20/25/10 style) after an audit showed a prior-decision-count term could never be nonzero under ERR_BOND_DECISION_LOCKED.
- Award-time fiscal check split: headline (ERR_AWARD_EXCEEDS_BUDGET) precedes projected-total (ERR_CONTINGENCY_EXCEEDED) inside priority 9; bid award evaluates empty-eligible-set (ERR_NO_AWARDABLE_BID, p6) before target-bid status (ERR_BID_NOT_AWARDABLE, p7) so the empty-set boundary is reachable.
- Bid-award side effect simplified (no subcontract mutation; un-award is the compensating action reverting Bid AWARDED->PLACED and subcontract PENDING_AWARD->DRAFT with value reset) after an audit found the DRAFT->PENDING_AWARD hop would create value-0 PENDING_AWARD subcontracts that break the retainage invariant.
- BondDecision input is trade_history (CLEAN|CLAIMS), replacing a decorative risk_tier input; decision is fully computed.
- Cascades verified hop-by-hop with version captures: declare-default drives Subcontract -> TradePackage -> Project (depth 3); replace drives spawn-and-reset (depth 2) with a non-terminal sibling subcontract holding the package in BUYOUT_IN_PROGRESS.
- Corner design: 57 active instances across all nine guide sections + 15 excluded_because stubs citing §1.8 instances; all 35 error codes are exercised by at least one instance.

## Step 3: Copy shared files — 2026-08-12T16:55:00.000Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md (1,424 bytes).

## Step 4: Generate PRD — 2026-08-12T16:58:00.000Z

PRD generation complete. All hard contracts pass.

**File written**: `workspace/PRD.md` — 54,301 bytes, 312 lines.

**Section list**: §1 Introduction; §2 Global Specifications & System-Wide Principles (11 subsections: RBAC, API Response Structure, Pagination, Project Logical Clock, Common Resource Properties, Monetary Precision and Rounding, OCC on Package Creation, Hierarchical Consistency and Bubble-Up Recomputation, Nested Resource Retrieval, Validation Priority Ordering, Dual Calculation Bases PROVISIONAL/FINAL); §3 Business Logic & Workflows (9 subsections, chronological buyout lifecycle: Standing Up the Project; The Bid Window; Leveling and Scope-Gap Analysis; Awarding the Bid and Drafting the Subcontract; The Negotiation Loop and Recommend-Award; Formal Award and the Compliance Gates; Insurance Certificates and the Bonding Decision; Schedule of Values and Change Orders Under Authority; Buyout Savings Tracking, Default, and Replacement); §4 Endpoint Definitions (54 rows); §5 Error Code Catalogue (35 rows).

**Hard contract reports**: Contract 1 (Field-Name Coverage): PASS — 80/80 entity fields, 58/58 request-body identifiers, 1/1 path params, all backticked. Contract 2 (Rule Coverage): PASS — all 34 state-transition pairs in §3 prose, all 9 calculations as precise business narrative, all 21 validation error IDs paired with conditions, OCC rule fully named, all 35 error IDs present, all 8 roles present, all 28 state enum values backticked. Contract 3 (§3 Path Purity): PASS — 535 backticked tokens, zero paths/methods.

**Doc-generation decisions**: §2 skeleton domain-first (logical clock own subsection; dual calc bases dedicated subsection; validation priority ordering promoted to top-level). §3 grouped chronologically by buyout lifecycle. FK coverage via "records its parent linkage" sentences. State-pair arrow notation plus standalone backticked state names. Calculation precision transcribed exactly (leveled_value, sov_line_allocation pinned cumulative-difference with last-line-absorbs-remainder and forbidden naive rounding, bond_premium_quote 0.015/0.010 half-up, replacement_cost_exposure 0.20 SUBGUARD claim half-up, trade_risk_score 10/20/35+0/25+10/25 table clamped 0..100 tiers 40/60/85). Validation priority as single ordered paragraph with within-award (ERR_AWARD_EXCEEDS_BUDGET before ERR_CONTINGENCY_EXCEEDED) and within-bid-award (ERR_NO_AWARDABLE_BID before ERR_BID_NOT_AWARDABLE) orderings called out. Sibling-branch symmetry across bonding policy branches, endorsement booleans, liability limits, insurance evaluation bases.
## Step 5: Generate unit tests — 2026-08-12T17:15:00.000Z

Files written — test_helpers/: __init__.py (40), types.py (281), api_client.py (225, 60 endpoint methods), api_errors.py (84, 34 error IDs), assertions.py (126), factories.py (116), constants.py (42), test_users.py (52, 8 opaque roles), fixtures.py (303). test_suite/: conftest.py (50), test_01_project_and_package_lifecycle.py (279), test_02_bids_gaps_and_leveling.py (658), test_03_subcontract_lifecycle_and_negotiation.py (350), test_04_insurance_bonding_and_issue.py (383), test_05_sov_and_change_orders.py (537), test_06_cascades_fiscal_and_security.py (694).

Test counts: Queue A (Difficulty) 18/18 instances -> 42 tests; Queue B (Corner) 34/34 non-stub instances -> 55 tests. Total 97 tests, 75 unique Design tags, zero untagged/dual-tagged/orphaned tags. Instances skipped: none — all passed PRD-first two-condition filter. 15 excluded_because stubs not translated (per spec); stub cross-references verified.

Stage 1 self-audit PASS (imports clean, common_fields branching respected, opaque roles use shared TEST_USERS, factories input-fields-only). Stage 2 self-audit PASS (pytest collects 97/97, PRD citations survive literal grep, one verbatim Design tag per test, no skip/xfail anywhere).

## Step 6: Generate implementation — 2026-08-12T17:15:00.000Z

Files written under workspace/implementation/: start.sh (10), requirements.txt (1), app.py (38), db.py (28), errors.py (9), response.py (40), middleware.py (51), util.py (133), services.py (703), routes/__init__.py (21), routes/projects.py (97), routes/packages.py (197), routes/bids.py (184), routes/gaps.py (151), routes/subcontracts.py (576), routes/compliance.py (185), routes/sov.py (171), routes/change_orders.py (148). Total 2,743 lines across 18 files.

Endpoints: 54 — verified programmatically by diffing SCAFFOLD.yaml endpoints table against Flask app.url_map (<var> normalized to {id}): declared 54, implemented 54, MISSING: [], EXTRA: [].

Boot/isolation: start.sh foreground launcher, exec python3 app.py, reads $PORT (default 10000), binds 0.0.0.0, HTTP-ready ~0.5s fresh. In-memory dict storage only; no seeding, no files, no SQLite.

Functional verification: two ad-hoc smoke suites (141 assertions) passed 100% on a fresh server, covering auth/role errors, OCC 412, SETUP gating, bid window rules, award ordering, negotiation completeness order, leveled-value recompute, round cap 2, un-award drag-back, retainage band, fiscal caps, insurance FULL/GAP analysis, cert expiry via clock, bond score 70->SUBGUARD premium 190000, bond lock, issue/execute gates, SOV cumulative-difference allocation incl. indivisible-cent case [3000000,3000001,3000000] on cv 9000001, reject->revise->approve, segregation of duties, authority tiers, exact cumulative-ratio boundary (inclusive pass at ratio==0.05), void unwind, declare-default/replace cascades, replacement spawn + cert SUPERSEDED + exposure, FINAL vs PROVISIONAL, pagination meta.

PRD-silence interpretation decisions: (1) insurance snapshot omitted fields default 0/false/workers_comp STATUTORY; (2) un-award with no linked subcontract allowed; (3) replacement spawn copies subcontractor_name/source_bid_id/flow_down_terms/snapshot/payment_terms/authority tiers; (4) uniqueness violations -> ERR_VALIDATION 422; (5) resolve-gap obligation failures -> ERR_VALIDATION 422; (6) recommend-award gate order follows PRD §3.5 prose order over scaffold priority numbers (PRD-wins); (7) field-level ERR_VALIDATION after auth/role/existence before OCC/state; (8) gap-resolve contingency consumption does not bump TradePackage.version; (9) CO approve/reject/void on terminal subcontracts not blocked; (10) bubble-up state-derived after every subcontract mutation per §2.8 settles semantics.
## Step 7: Run tests and iterate — 2026-08-12T17:58:00.000Z

Clean exit — all 8 parallel rounds pass 97/97 (verified on disk by orchestrator: results.1..8.json each passed=97 total=97 failed=0).

- Iterations run: 2 (sweep 1: 11 deterministic failures, identical across all 8 rounds; sweep 2 after fixes: 97/97 in all 8 rounds). Route parity verified before the first sweep: all 54 SCAFFOLD.yaml endpoints are registered in the implementation.

- Tests deleted: none outright. One test was rewritten because its scenario was unreachable under PRD:
  - `test_publish_before_project_open_rejected` -> rewritten as `test_package_create_before_project_open_rejected` (test_suite/test_01_project_and_package_lifecycle.py). Collapse pattern: scaffold corner case assumed a package could be created under a SETUP project; PRD §3.1 verbatim forbids it ("While a project is in SETUP, no child mutations are possible: any attempt to create or mutate a trade package under it is rejected with ERR_PACKAGE_NOT_OPEN"), and a DRAFT package under a non-BUYOUT_OPEN project is unreachable via the API, so the publish-time gate could never fire on a PRD-faithful implementation. The rewrite asserts the reachable PRD-verbatim rule (create under SETUP -> ERR_PACKAGE_NOT_OPEN, nothing persisted).

- Fixes applied to test_helpers/:
  - test_helpers/fixtures.py — `create_draft_subcontract` now pins an explicit `insurance_requirements_snapshot` (new DEFAULT_INSURANCE_REQUIREMENTS_SNAPSHOT: 1M/2M/1M/5M limits, STATUTORY, ai/wos/ptd required, pollution not required) when the caller passes none. Why: PRD §3.7 says "server defaults apply to any requirement omitted at draft time" without naming values (DEFAULT-VALUE SILENCE); four tests relied on unstated defaults. Pinning per PRD §3.4's "optionally an insurance_requirements_snapshot pinning the required limits" makes every verdict uniquely PRD-derived. Fixed: test_full_endorsements_rejects_missing_ai_endorsement, test_gap_analysis_excuses_vp_waived_endorsement_failure, test_insurance_numeric_shortfall_non_compliant, test_issue_with_only_noncompliant_cert_rejected. All compliant-cert call sites suite-wide already carry exactly these values, so no passing test regressed.

- Fixes applied to test_suite/:
  - test_03_subcontract_lifecycle_and_negotiation.py::test_retainage_below_band_floor_rejected — setup replaced _draft_sub (which left bids[0] already referenced by a non-terminal draft, so the probe correctly failed ERR_BID_NOT_AWARDABLE — a precedence PRD §2.10 does not pin) with a 3-bid leveling package sourcing an available PLACED bid, so only the retainage band check can fail.
  - test_05_sov_and_change_orders.py::test_cumulative_ratio_exactly_at_ten_percent_passes — corrected arithmetic slip in the final assertion (11_000_000 -> 11_100_000); PRD §3.8 increases contract_value_cents by amount_cents on each approval (10M + 1M + 0.1M).
  - test_01_project_and_package_lifecycle.py — the rewrite noted above.

- Fixes applied to implementation/:
  - workspace/implementation/db.py::new_id — was uuid.uuid4().hex (undashed); now str(uuid.uuid4()) (canonical dashed UUID) per PRD §2.5 "id — a server-minted UUID". Fixed: test_project_create_ignores_client_supplied_system_fields, test_trade_package_create_computed_defaults, test_bid_received_exactly_at_deadline_accepted, test_round_recorded_with_index_value_and_logical_clock.

No PRD-required implementation check was weakened, no non-PRD capability was added, storage remains in-memory only, and no assertion was downgraded.
## Step 8: Finalize PRD — 2026-08-12T18:05:00.000Z

`workspace/PRD_FINALIZED.md` written as a 3-line patch of PRD.md.

Line counts / delta: PRD.md 312 lines; PRD_FINALIZED.md 312 lines (0% line-count delta — three in-place sentence-level revisions, no sections added or removed).

Changes (one bullet per edit):
- §2.5 — revise — `id` bullet now pins the canonical dashed lowercase UUID string form (8-4-4-4-12) instead of the ambiguous "a server-minted UUID" — implementation/db.py:21-22 (str(uuid.uuid4()); step_7 impl fix from undashed uuid4().hex).
- §3.4 — revise — appended a draft-creation precedence sentence: package-state/competitive-tension gate first, then source-bid checks (existence -> PLACED/AWARDED -> no-non-terminal-reference), retainage band check last (a double failure yields ERR_BID_NOT_AWARDABLE, not ERR_RETAINAGE_OUT_OF_BAND) — implementation/routes/subcontracts.py:151-180 (step_7 rewrite of test_retainage_below_band_floor_rejected exposed this §2.10-unpinned precedence).
- §3.7 — revise — replaced the unnamed "(server defaults apply...)" parenthetical with the concrete defaults: four required liability limits default to 0 cents, workers_comp defaults to STATUTORY, all four required-endorsement flags default to false; also pins that an explicit null is treated as omitted — implementation/services.py:25-35 (INS_SNAPSHOT_DEFAULTS) and routes/subcontracts.py:181-185 (merge skips null values).

Step_7 items needing no edit: the test_package_create_before_project_open_rejected rewrite asserts PRD §3.1 verbatim (already determined), and the test_cumulative_ratio_exactly_at_ten_percent_passes fix was a pure test arithmetic slip against PRD §3.8's already-pinned "increase by amount_cents" rule.

Per-edit pre-edit search log:
1. Edit §2.5 (UUID form). (a) Subject: format of the system-managed `id` field. (b) Enumerated: db.py:21-22 (sole generator); all 12 new_id() call sites — routes/projects.py:38, packages.py:81, bids.py:88, gaps.py:41, subcontracts.py:187 (draft), :282 (NegotiationRound), :488 (replacement spawn), sov.py:82, change_orders.py:47, compliance.py:92 (certificate), :159 (bond decision); greps for uuid/.hex/upper()/UUID( confirmed no parsing, case transforms, or alternate generators; api_request_id (response.py:14) is a separate req_-prefixed value covered by §2.2; test helper is_valid_uuid regex requires dashed form; NON_EXISTENT_UUID is dashed. (c) Added "canonical dashed lowercase" plus an example; scoped to the `id` bullet so §2.2's api_request_id and the NegotiationRound exception note stay untouched.
2. Edit §3.4 (draft-creation precedence). (a) Subject: evaluation order of draft-creation gates at POST /trade-packages/{id}/subcontracts. (b) Enumerated: routes/subcontracts.py:136-212 (create order: package gate :151-162 -> bid existence :164-166 -> bid status :167-168 -> non-terminal reference :169-179 -> band :180); the only other retainage site, recommend-award :257-272, whose order (round cap -> band -> completeness -> fiscal) §3.5 already pins in matching words; §2.10 confirmed silent on the band check's position at draft creation. (c) Scoped the sentence explicitly to "draft-creation" and enumerated the gates in impl order, so the §3.5 recommend-award ordering (band check second, not last) is not mis-described; also deliberately silent on where 422 payload-shape validation sits, since impl runs it earlier but step_7 did not exercise that.
3. Edit §3.7 (snapshot defaults). (a) Subject: server defaults and merge semantics for insurance_requirements_snapshot. (b) Enumerated: services.py:25-35 (default values), routes/subcontracts.py:148-150 (input validation), :181-185 (merge: input overrides default only when non-null), :194 (stored), :488-495 (replace copies the resolved snapshot — defaults do NOT re-apply there), services.py:311-323 (evaluation reads the merged snapshot; the workers_comp numeric check compares the certificate to literal STATUTORY, exactly as PRD already states), services.py:599 (serialization). (c) Kept the "at draft time" scope so the replacement-copy path is not mis-described as re-defaulting; added "or explicitly supplied as null" to match the `if v is not None` merge guard; named workers_comp default as STATUTORY without altering the evaluation sentence, which keys off the certificate's value.
## Step 9: Complete PRD — 2026-08-12T18:25:00.000Z

Note: the first Step 9 subagent completed the full analysis but its return output was truncated before applying edits — PRD_COMPLETED.md on disk was a byte-identical copy of PRD_FINALIZED.md (verified via diff). Per protocol, a bounded completion subagent was re-spawned for only the missing piece (apply + re-verify the 28 planned edits against implementation); it verified every edit against the code and applied all of them.

All edits applied and verified. Document coherent: 315 lines, 60,153 chars.

Summary:
- Source file (PRD_FINALIZED.md) vs PRD_COMPLETED.md line counts and char-delta: 312 lines / 55,105 chars -> 315 lines / 60,153 chars (+3 lines, +5,048 chars).
- Counts: ambiguity-pins 21; mismatch-revisions 5.

Changes (section — insert|revise — ambiguity|mismatch — what changed — impl file:line):
- §2.2 — insert — ambiguity — ERR_VALIDATION semantics for malformed body/missing/mistyped fields; unrouted/unsupported-method -> ERR_NOT_FOUND 404; unexpected failure -> ERR_INTERNAL 500 — app.py:20-30, util.py:35-50
- §2.3 — insert — ambiguity — non-integer/out-of-range limit, negative offset -> ERR_VALIDATION 422 — util.py:104-126
- §2.3 — revise — mismatch — dropped false "enumerated in §4" claim; pinned has_more = (offset+limit)<total_count and which lists take status/category/basis; unmatched filter yields empty page — response.py:29, route list handlers
- §2.5 — revise — ambiguity — version starts at 1; created_at/updated_at are server wall-clock UTC, logical clock only for recorded_at/approved_at/default_recorded_at — services.py:42-51, db.py:25-28
- §2.8 — insert — ambiguity — bubble-up reconciliation re-evaluated on every subcontract state mutation incl. terminate — services.py:197-215, subcontracts.py:536
- §2.10 — insert — ambiguity — syntactic payload validation runs after existence, before OCC and state checks — packages.py:42-71 et al.
- §3.1 — insert — ambiguity — duplicate project_number -> ERR_VALIDATION 422 — projects.py:34-36
- §3.1 — insert — ambiguity — opening a non-SETUP project -> ERR_INVALID_STATE_TRANSITION — projects.py:61-64
- §3.1 — revise — ambiguity — only SETUP rejects package creation; BUYOUT_COMPLETE still admits packages — packages.py:71-74
- §3.1 — insert — ambiguity — trade_code collision -> ERR_VALIDATION 422; new package's buyout_savings_cents/buyout_posture computed at creation (savings = estimated_budget_cents) — packages.py:75-99
- §3.2 — revise — ambiguity — publish requires bid_due_at present and strictly future; missing deadline -> ERR_BID_WINDOW_INVALID — packages.py:140-146
- §3.2 — insert — ambiguity — no bid_due_at => no deadline check; bid-creation check order state -> duplicate-bidder -> deadline — bids.py:67-86
- §3.4 — insert — ambiguity — life-safety block at bid award runs after candidate-set and target-bid checks — bids.py:143-157
- §3.5 — insert — ambiguity — disposition vocabulary (allowance_id + ACCEPT/REJECT/REPRICE, priced_cents required on REPRICE; alternate_id + boolean selected) — subcontracts.py:104-133
- §3.5 — insert — ambiguity — un-award with no drafted subcontract returns bid to PLACED; multiple linked subs -> earliest-created examined — bids.py:170-184
- §3.6 — revise — mismatch — issue gate order pinned to insurance -> bonding -> life-safety — subcontracts.py:361-376
- §3.6 — revise — ambiguity — ERR_SUBCONTRACT_TERMINAL scope: own transitions + child creations blocked; child review actions and reads remain reachable — ensure_sub_not_terminal call sites
- §3.7 — insert — ambiguity — duplicate certificate_number -> ERR_VALIDATION 422 — compliance.py:84-90
- §3.7 — insert — ambiguity — ISSUED->EXPIRED flip on expiry failure applies under both bases — services.py:326-327
- §3.7 — insert — ambiguity — bond-decision from-state gate evaluated before locked check — compliance.py:143-153
- §3.7 — revise — mismatch — SUBGUARD band is 61+ through clamped max 100 (not 61-85) — services.py:426-430
- §3.7 — insert — ambiguity — non-positive package estimated_budget_cents: size component = 25 iff contract_value_cents > 0 — services.py:412-416
- §3.8 — revise — ambiguity — SOV revise carries a fresh lines list, validated and re-allocated as at submission — sov.py:135-153
- §3.8 — insert — ambiguity — EXECUTED-state gate evaluated before SOV-APPROVED gate on CO create — change_orders.py:35-45
- §3.8 — insert — ambiguity — best-tier ties on max_value_cents break toward earliest tier in change_authority_limits — services.py:487-491
- §3.8 — insert — ambiguity — non-positive contract_value_cents: any strictly positive cumulative total exceeds a finite max_cumulative_pct — services.py:498-505
- §3.9 — revise — ambiguity — replacement spawn copies six fields from replaced sub, resets cumulative_co_cents/sov_status, derives bonding_requirement from package policy — subcontracts.py:487-510
- §3.9 — revise — mismatch — exposure uses current contract_value_cents (not "value at default"/"original"); pinned items array ordering (created_at asc) and item keys — packages.py:173-197
- §3.9 — revise — ambiguity — buyout summary's per-package array returned under key `packages`, entries fully serialized on selected basis — projects.py:87-97
- §5 — insert — mismatch — added ERR_INTERNAL | 500 catalogue row — app.py:28-30

Dropped/corrected during re-verification: none — all 28 planned edits verified accurate against the implementation and applied (the consolidated tail listed no Edit 7/11/19/20 as separate items; their content was folded into Edits 6/12/18 as numbered above).

Orchestrator final verification: workspace/PRD_COMPLETED.md present (60,153 bytes); implementation/, test_suite/, test_helpers/ unchanged since the clean Step 7 sweep (no .py file newer than results.1.json); all 8 results files re-verified passed=97 total=97 failed=0.
