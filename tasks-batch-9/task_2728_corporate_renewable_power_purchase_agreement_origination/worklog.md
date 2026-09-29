# Worklog — task_2728_corporate_renewable_power_purchase_agreement_origination

## Step 1: Create task directory — 2026-09-04T12:35:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2728_corporate_renewable_power_purchase_agreement_origination` and its `workspace/` subdirectory. Index 2728 was pre-assigned by the invoking pipeline; no index scan performed (concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-04T14:58:00.000Z

All three scaffold artifacts are complete and the linter is clean.

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  §1.5 endpoints declared:    51
  §1.1 entities declared:     12
  §1.8 instances scanned:     18
  §1.9 instances scanned:     61
  Calls scanned (§1.8+§1.9):  1248

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Files: SCAFFOLD.yaml 3537 lines / 181,532 bytes; SCAFFOLD_DIFFICULTY_DESIGN.yaml 2642 lines / 188,242 bytes; SCAFFOLD_CORNER_DESIGN.yaml 5679 lines / 389,978 bytes. `workspace/` and `worklog.md` were left untouched; nothing else was created.

Domain model: `domain_name: corporate-renewable-ppa-origination`, `api_prefix: /ppa`, `difficulty_level: expert_plus`, archetypes multi_party_negotiation + ledger_reconciliation, `entity_topology: graph`, `state_machine_shape: cyclic`, `role_model: segregation_of_duties`, `consistency_model: immediate`, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers]`.

- 12 entities: PricingNode, Offtaker, Project, Deal, DealAllocation, TermSheetRound, CreditSupportInstrument, ConditionPrecedent, SettlementPeriod, MeterInterval, EnvironmentalAttributeBatch, RiskEvent
- 11 state machines (Deal carries two independent dimensions: `status` with a redline loop, `credit_status` with a shortfall/cure loop), 3 concurrency rules, 16 calculations, 35 prioritised validations, 51 endpoints, 44 error codes, 6 roles (Originator, CreditOfficer, DealCommittee, SettlementAnalyst, RegistryAgent, OfftakerRep)

Design instance counts:
- §1.8: 18 instances — 9 difficulty rules × 2
- §1.9: 89 instances across all nine guide sections — entities 13, state_machines 17, calculations 18, validations 9, endpoints 5, errors 16, rbac 4, complexity_layers 6, consistency_model 1. Of these, 61 carry full `test_recipe` chains and 28 are `excluded_because:` stubs citing a §1.8 owner.

Verification beyond the linter: all 107 instance names unique across both design files; all 28 stub citations resolve to a real §1.8 instance name; every `grounds:` entry resolves into §1.1–§1.7 (repointed five that targeted §1.0 `response_envelope.*` / `complexity_profile.*`); all 44 declared error codes are exercised or stubbed.

Scaffold fixes made while writing §1.9 (audit pass):
- `CreditSupportInstrument.haircut_pct` constraint said `0.00-1.00` while the calculation's `LC_HAIRCUT_PCT` rows are percentages (`BBB: 10.0`) — restated as `0.00-100.00` with an explicit "percentage, not fraction" note.
- Validation priority 10 (`ERR_SEGREGATION_OF_DUTIES`) did not cover the SoD precondition the `TERMS_AGREED -> EXECUTED` transition declares ("X-User-ID != credit_approved_by_user_id"); added that bullet and `POST /ppa/deals/{id}/execute` to its `applies_to`.
- MW fields were declared at 2 decimals while every design-file literal is 3 (`25.000`, `15.000`); relaxed `Deal.contracted_mw / confirmed_allocated_mw / unallocated_mw`, `DealAllocation.allocated_mw`, `Project.contracted_mw / available_mw` to 3 decimals.

## Step 3: Copy shared files — 2026-09-04T14:58:30.000Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-04T15:22:00.000Z

PRD complete and verified. Output: `workspace/PRD.md` — 419 lines / 106,026 bytes, ending at a real boundary (last row of the §5 error table).

Section list: §1 Introduction; §2 Global Specifications (2.1 RBAC / 2.2 API Response Structure / 2.3 Pagination and List Ordering / 2.4 Common Resource Properties and the Logical Clock / 2.5 The Order in Which a Request Fails / 2.6 Numeric Precision, Rounding and Sign Conventions / 2.7 Optimistic Concurrency on Parent Aggregates / 2.8 Segregation of Duties / 2.9 Cascade Discipline and Nested Path Resolution / 2.10 The Day-Count Calendar); §3 Business Logic & Workflows (3.1 Settlement Points, Generation Projects and Development Milestones / 3.2 Onboarding, Scoring and Qualifying the Corporate Buyer / 3.3 Rating Migration, the Watchlist and the Downgrade Cascade / 3.4 Structuring and Pricing the Agreement / 3.5 The Term Sheet Negotiation Cycle / 3.6 Aggregated Buyer Arrangements / 3.7 Credit Underwriting and the Collateral Stack / 3.8 Execution, Conditions Precedent, Effectiveness and Termination / 3.9 Settlement, Risk Allocation and Environmental Attribute Conveyance); §4 Endpoint Definitions; §5 Error Code Catalogue.

Coverage self-audit (mechanically checked with a YAML-parse script against SCAFFOLD.yaml, nothing omitted):
- Endpoints: 51/51. Every scaffold row matched exactly as `| METHOD | \`path\` |` in §4; 201 for the 10 creating endpoints, 200 elsewhere.
- Error codes: 44/44 in §5, and every one also appears at least once in §1–§3 prose at its trigger site (zero errors appearing only in the table).
- Calculations: 16/16 in prose. All pinned constants verified present numerically except the three `TIER_EBITDA_PCT` fractions, written in words ("5 percent", "2 percent", "one-half of one percent"). All three non-half-up roundings spelled out: ceiling-to-250,000 collateral increments, floor for `mintable_attributes_mwh`, largest-remainder for `attribute_allocation`.
- State machines: 11/11, all 55 transitions represented (47 with explicit arrow, 8 in prose with both endpoints named).
- Validations: 35/35, enumerated in §2.5 as a numbered 1–35 priority list with each error ID and tie-break note.
- Fields: every field of all 12 entities appears verbatim in backticks (one gap found and patched: `MeterInterval.settlement_period_id`). All endpoint input field names, all entity enum values, all 6 roles, all 3 OCC rules present.

Hard Contract reports: Contract 1 Field-Name Coverage PASS (0 missing); Contract 2 Rule Coverage PASS; Contract 3 §3 Path Purity PASS (zero `/ppa` or `/_clock` paths, zero bare HTTP method tokens in §3).

Scaffold inconsistencies the doc generator resolved (flagged for the test author):
1. `DealAllocation.allocation_share_pct`: entity constraint says 4 decimals, endpoint side-effect formula says `round(..., 2)`. Wrote 4 decimals, hedged in §2.6.
2. SettlementPeriod/MeterInterval MWh totals: entity constraints say 3 decimals, `settlement_netting` / `deemed_generation` formulas say 4. Wrote 4 decimals.
3. Validation priority 26 cites "REJECTED and WITHDRAWN allocations", but `DealAllocation.status` has no `REJECTED` member. Wrote `WITHDRAWN` only.
4. `EnvironmentalAttributeBatch.allocation_breakdown`: entity description names `offtaker_id`/`quantity_mwh`, formula step 5 names `offtaker_id`/`mwh`. Wrote `offtaker_id` and `quantity_mwh` (the field contract).
5. The entity spec references `calculations.allocation_share_pct`, which is not one of the 16 declared calculations.

Orchestrator truncation check: `tail -25` shows the file ending mid-table at the final declared error row, with §4 holding 51 endpoint rows and §5 holding 44 error rows — no truncation, no regeneration needed.

## Step 6: Generate implementation — 2026-09-04T16:10:00.000Z

(Steps 5 and 6 ran concurrently; Step 6 returned first, so its entry is recorded here ahead of Step 5's. Step 5's entry follows below.)

The implementation is complete and verified.

Files (`workspace/implementation/`):
- `core.py` 692 lines — in-memory `Store` (12 dicts, never seeded), logical clock (default `2026-08-01T00:00:00Z`), Decimal helpers (`prec=60`, half-up/floor/ceil), response envelope (`meta`/`response_type`/`data`, errors nested in `data`, pagination in `meta`), auth + RBAC, `touch()` one-bump-per-row-per-request, `endpoint()` decorator (RLock-serialised), all validators/filters/pagination/lookups, the 44-id error→status map
- `calc.py` 406 lines — 30 enum lists, every pinned constant, and all PRD §3 calculations (scores, tiers, limits, 4-step pricing, volume, 3-step collateral sizing, haircuts, deemed generation, HOURLY/MONTHLY netting, floor-mintable, largest-remainder allocation, CP template, durations)
- `services.py` 425 lines — recomputations (project capacity, allocation/support/attribute/CP totals, `resize_deal_credit`), `maybe_effective`, `open_shortfall`, guarantor-cycle guard, and the multi-hop cascades (rating-change downgrade/recovery/same-band, guarantor children, project-milestone CP cascade, termination 3-branch cascade, period settlement run, risk impact)
- `routes_a.py` 401 lines — clock, pricing nodes, offtakers (+qualification/rating-change/allocations/batches/guarantees), projects (+milestones)
- `routes_b.py` 635 lines — deals, negotiation rounds + respond, allocations + decision, submit-credit, credit-decision, credit-support register/list/post/release
- `routes_c.py` 683 lines — execute, CP list + resolution, terminate, settlement periods, intervals, calculate, advance, mint/transfer/cancel/retire, risk events + review
- `app.py` 57 lines — blueprint registration, envelope-shaped 400/404/405/500 handlers, `0.0.0.0:$PORT` (default 10000), no seeding
- `start.sh` 8 lines — installs flask only if missing, `exec python3 app.py` (foreground, single PID)
- `requirements.txt` 1 line — `flask>=2.0`

Verification:
- `python3 -m py_compile` clean on all 7 modules.
- Flask URL map enumerates exactly 51 GET/POST endpoints — a 1:1 match with the 51 declared in PRD §4 (verified path-by-path).
- All 44 catalogue error ids programmatically diffed against the PRD table: zero status mismatches, none missing.
- Two end-to-end smoke runs on random high ports (24427, then 20744), each killed by that exact PID afterwards; no pattern-based kill was ever used. Happy path (node→buyer→project→deal→round→allocation→credit→execute→settlement→attributes) and a second run covering guarantor-supported scoring, counter rounds, 4-row CP template, milestone CP cascade, SATISFY/WAIVE/FAIL/RECURE, effectiveness at 100.00 with dev-security release, and EFFECTIVE termination cascade. Both ended `SMOKE OK`. Spot-checked arithmetic all matched hand calculations (e.g. escalated base 46.125→MID→+6.25+1.50 = 53.88; exposure 9,911,764.80; required = ceil(19.647)×250k = 5,000,000; guarantor-supported score 88.2; deemed 28.0 on a BUYER_BEARS curtailed hour).
- Negative paths confirmed live: 401/403 (role, counterparty, both SoD checks), 404 (path + body FK), 400 (range + conditional field), 409 (state gate, duplicates, open-risk), 412 (stale version), 422 (ineligible issuer, short tenor, invalid window, release breaches coverage, unvested termination).
- The impl generator never read, listed or grepped `test_helpers/`, `test_suite/`, or any sibling task directory.

PRD ambiguities resolved (chosen interpretation):
1. `term_years` 1–25 and `escalation_pct_per_year` 0–10 taken from the §2.5 priority-3 "ranges enforced here" list, overriding the narrative's 5–25 / 0.0–5.0. Same 0–10 applied to `proposed_escalation_pct_per_year` (absent from the enforced list). This is the single largest remaining risk if the suite followed the narrative.
2. `unallocated_mw` = contracted − Σ over {PROPOSED, CONFIRMED}; `confirmed_allocated_mw` = Σ CONFIRMED.
3. `allocation_share_pct` at 4 dp (§2.6 wins over an endpoint blurb saying 2).
4. Interval/period MWh at 4 dp (§1.3 wins over an entity note saying 3).
5. `PricingNode` emits only `id`/`created_at` — both `version` and `updated_at` popped.
6. Deal creation leaves `cp_completion_pct` null (per §3.4's explicit null list).
7. Preconditions with no dedicated error id → `ERR_INVALID_STATE_TRANSITION` 409 (QUALIFY/CONDITIONAL score gates, `is_waivable` false, `interval_count>=1`, null contract price on submit-credit, DISPUTED-period block on terminate, `proposed_by != DEVELOPER`, deal-status gates on child resources); except conditionally-required body fields, which are 400 (`evidence_ref`, `waiver_justification`, `dispute_reason`, `allocation_outcome`, CONDITIONAL `conditions`).
8. Buyer-qualification gates on allocation propose/confirm and submit-credit → `ERR_OFFTAKER_NOT_QUALIFIED` 422.
9. credit-decision APPROVE coverage failure → `ERR_CREDIT_SUPPORT_SHORTFALL` 422; execute's `available_mw >= contracted_mw` → `ERR_PROJECT_CAPACITY_EXCEEDED` 422, checked last.
10. `advance` action↔role split (INVOICE/SETTLE analyst-only, DISPUTE rep-only) → `ERR_ROLE_NOT_PERMITTED` 403 right after shape validation.
11. `ERR_NOT_DEAL_COUNTERPARTY` applied to `GET /ppa/deals/{id}`, respond, allocation decision, DISPUTE and risk-event filing; ACCEPT/DISPUTE demand the anchor exactly, COUNTER/filing also accept a confirmed-slice holder. Deal-scoped list reads are not gated.
12. Swept `OPEN → COUNTERED` rounds get only `responded_by_user_id`; `responded_at` stays null, following the PRD's literal wording.
13. Batch→period linkage stored as a private `_period_id`, hidden from JSON by `public()`; per-period remaining mintable excludes CANCELLED batches.
14. `price_adjustment_usd_per_mwh` out of ±10.00 → `ERR_PRICE_ADJUSTMENT_INVALID` 422 (absent from the priority-3 range list), as is a missing adjustment or a non-positive resulting price.
15. `claim_year` validated only as an integer so window breaches surface as 422, not 400.
16. At most one `version` bump per row per request; project version always bumps on deal creation/execute/terminate/milestone.
17. `allocation_breakdown` elements are `{offtaker_id, quantity_mwh}` in largest-remainder sort order.

## Step 5: Generate unit tests — 2026-09-04T18:04:00.000Z

ORCHESTRATOR NOTE: this step's first agent run was terminated mid-flight by an infrastructure API error (not a content failure) after emitting test_helpers/ plus test_01–test_04. Rather than respawn a fresh generator — which would have made the second half of the suite diverge from the first — the orchestrator recomputed coverage from disk (extracting every `Design:` docstring tag in test_suite/ and diffing it against the non-stub instance names in both design yamls: 15/18 queue A, 0/61 queue B done) and resumed the SAME agent via SendMessage with that exact to-do list, restating the design-index-only contract, the PRD-first two-condition filter, the read prohibitions, and the chunked-append output protocol. The agent then completed the remaining 3 queue-A and 61 queue-B instances. Its final report follows verbatim.

The suite is complete.

Files emitted:

`test_helpers/` — 2,563 lines, 9 modules (`__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`). Unchanged in this final stretch — no new helper was needed for the last eight instances.

`test_suite/` — `conftest.py` (58) + 15 test modules, 8,386 lines, 100 tests

| file | tests | lines |
|---|---|---|
| test_01_dual_variant_and_combinatorial_calculations.py | 8 | 517 |
| test_02_state_machines_and_cascades.py | 8 | 571 |
| test_03_validation_priority_and_boundaries.py | 8 | 483 |
| test_04_overlap_and_conserved_invariants.py | 8 | 709 |
| test_05_cross_entity_state_dependency.py | 6 | 379 |
| test_10_entity_shapes_and_defaults.py | 7 | 429 |
| test_11_listing_and_reference_integrity.py | 6 | 400 |
| test_12_state_machine_transitions.py | 9 | 705 |
| test_13_credit_scoring_calculations.py | 5 | 419 |
| test_14_settlement_and_attribute_calculations.py | 5 | 605 |
| test_15_validation_ladder.py | 7 | 753 |
| test_16_reference_integrity_and_capacity_errors.py | 6 | 492 |
| test_17_deadline_window_and_eligibility_errors.py | 6 | 792 |
| test_18_endpoint_surface_and_role_gates.py | 6 | 606 |
| test_19_version_pinning_and_consistency.py | 5 | 526 |

Coverage:
- Queue A (`SCAFFOLD_DIFFICULTY_DESIGN.yaml` §1.8): 18/18 instances → 38 tests.
- Queue B (`SCAFFOLD_CORNER_DESIGN.yaml` §1.9): 61/61 non-stub instances → 62 tests (the 28 `excluded_because:` stubs are not translated; the `consistency_model` instance is split across two tests to meet the five-test floor in test_19).
- Automated diff of every `Design:` tag in `test_suite/` against the non-stub instance names in both yamls: MISSING = [], UNKNOWN = []. Every test carries exactly one `Design:` line; no untagged and no dual-tagged tests.
- Quote audit (whitespace-normalised substring containment against `workspace/PRD.md`): 270 quotes, 0 non-verbatim.
- `python3 -m py_compile` clean over all 24 emitted `.py` files; `__pycache__` removed.
- `test_helpers/` and `test_suite/` are at the task root; nothing was created, read or modified under `workspace/` other than reading `PRD.md`, and `workspace/implementation/` was never opened.

SKIPPED instances: None. Every non-stub instance passed both filter conditions (verbatim PRD coverage + uniquely PRD-derivable outcome).

PRD-vs-index deviations (PRD always won; only the contradicted leg was dropped, never weakened) — nineteen standing decisions, of which five were made in the final stretch:
- (15) the endpoints deal-linking instance claims `contracted_mw` 55.000 from two DRAFT deals — dropped per the L162 EXECUTED/EFFECTIVE ledger rule; asserted 0.000/100.000 plus project version advanced by 2.
- (16) the rbac auth-ladder instance uses `SettlementAnalyst` for its 403 leg on `POST /ppa/pricing-nodes`, but the endpoint table authorises `Originator, SettlementAnalyst`; the 403 legs use genuinely forbidden roles (`CreditOfficer`, `RegistryAgent`).
- (17) the stale-period instance asserts `total_metered_mwh` 30.0000 immediately after posting an hour; PRD L280/282 make the totals a calculate-time product, so only `interval_count`, `version`, `status` and `calculated_at` are asserted at post time.
- (18) the consistency instance proposes an allocation on a DRAFT deal, which L232's state gate forbids; a round is tabled first so the deal is `TERM_SHEET_ISSUED`. Its claim that a DRAFT deal books 25.000 MW on the parent project is likewise replaced with the ledger-after-execution leg (25.000/75.000).
- (19) the stacked-post instance posts collateral on a deal whose `credit_status` is `NOT_SUBMITTED`, which L250 forbids; the test submits credit first and asserts the final `credit_status` is `SUBMITTED`. The index's own "registration does not bump the deal version" claim is asserted verbatim from L248.

Earlier decisions still in force: allocation-breakdown row shape; NULL scores at creation; PricingNode has no `updated_at`/`version`; 4dp `allocation_share_pct`; `ERR_INVALID_REQUEST` = 400 (index says 422); `ERR_CP_DEADLINE_PASSED` = 409 (index says 422); default-bearing fields omitted from payloads; corner 31's `unallocated_mw` and corner 36's re-issuance legs dropped; corner 37 rebuilt on an APPROVED deal; errors 45 rebuilt on the DECLINED re-underwriting path; errors 47's DRAFT-booking legs replaced by ledger-unchanged assertions.

Orchestrator verification: `test_helpers/` and `test_suite/` are both at the task root (no strays under `workspace/`), 100 `def test_` functions confirmed on disk, `python3 -m py_compile` clean over all files.

## Step 7: Run tests and iterate — 2026-09-04T18:26:00.000Z

Clean sweep: all 8 parallel rounds at 100/100.

Iterations run: 2 (iteration 1: 98/100 in all 8 rounds, the same 2 tests failing deterministically in every round — no flakiness anywhere; iteration 2: 100/100 in all 8 rounds).

Tests deleted: none. Both failures were STEP 2 test-vs-PRD consistency bugs, not PRD-silence cases, so no test qualified for deletion.

Fixes applied to `test_helpers/`: none. The fixture/factory layer was already PRD-faithful (money emitted as JSON numbers, role headers matching PRD's ownership model, optionals omitted so declared defaults are exercised).

Fixes applied to `test_suite/`:
- `test_13_credit_scoring_calculations.py`, `test_05_two_haircut_tables_discount_two_instruments_differently` — the test posted two instruments against a deal still at `credit_status` `NOT_SUBMITTED`, which PRD §3.7 verbatim forbids ("the deal's `credit_status` must be `SUBMITTED`, `APPROVED`, `SUPPORT_SHORTFALL` or `DECLINED`"). The implementation's 409 `ERR_INVALID_STATE_TRANSITION` was PRD-required, so the setup chain was the bug: inserted `fx.submit_credit` before registration, repointed the "registration does not increment the deal's version" assertion at the post-submission version, and corrected the terminal `credit_status` expectation from `NOT_SUBMITTED` to `SUBMITTED`. The haircut assertions themselves (LC BBB → 10.00 / 450,000.00; PG STANDARD guarantor → 25.00 / 750,000.00; combined 1,200,000.00) were left exactly as written, and the requirement still sizes to 0.00 after submission, so nothing was weakened.
- `test_15_validation_ladder.py`, `test_03_the_identical_deal_payload_turns_on_the_anchor_buyers_standing` — the test asserted that creating a `DRAFT` deal moves the parent project's `contracted_mw` to 25.000. PRD §3.1 states verbatim that "`contracted_mw` is always the sum of `contracted_mw` over the project's deals whose `status` is `EXECUTED` or `EFFECTIVE`", so §3.4's "recomputes the parent project's `contracted_mw`" recomputes to 0.000 for a `DRAFT` deal. Corrected the assertion to 0.000 / full capacity. This is corroborated inside the suite: `test_16_reference_integrity_and_capacity_errors.py::test_06` asserts the same reading ("because a `DRAFT` deal books nothing…") and was already passing.

Fixes applied to `implementation/`: none. No implementation defect surfaced.

Adjudication of the flagged PRD-internal contradiction: §2.5 priority-3 says `term_years` 1–25 and `escalation_pct_per_year` 0–10, while §3.4/§3.5 narrative says 5–25 and 0.0–5.0. The contradiction is real, but no test in the suite probes either boundary (`term_years` only ever 10/12/15; escalation only 0.0/1.0/2.0), so it is unreachable and the implementation's §2.5 reading needed no change. Had a test asserted either edge, it would have failed STEP 1b unique-derivability — two PRD-faithful readers diverge — and been deleted rather than resolved in favour of one passage.

Other implementation interpretations left standing (no test contradicted them): `unallocated_mw` netting both `PROPOSED` and `CONFIRMED`, `allocation_share_pct` at 4dp, interval/period MWh at 4dp, `PricingNode` omitting `version`/`updated_at`, undedicated preconditions mapping to `ERR_INVALID_STATE_TRANSITION` 409 (conditionally-required body fields to 400), and swept `OPEN`→`COUNTERED` rounds carrying `responded_by_user_id` with `responded_at` null.

ORCHESTRATOR VERIFICATION (independent of the subagent's claim): all 8 `workspace/implementation/results.$i.json` files exist on disk with fresh mtimes clustered at 2026-09-04T18:25:49–50Z, and each parses to `passed=100 total=100 failed=0`. The clean-sweep claim is confirmed against the artifacts, not taken on report.

Step 8 is NOT skipped: Step 7 ran 2 iterations and applied 2 `test_suite/` fixes, so PRD.md left behaviors under-determined at those sites even though no `implementation/` fix was needed.

## Step 8: Finalize PRD — 2026-09-04T18:38:00.000Z

Done. `PRD_FINALIZED.md` written with a 3-line surgical patch.

Line counts: `PRD.md` 419 lines; `PRD_FINALIZED.md` 419 lines (0 line delta). 3 of 419 lines revised → 0.72% of lines touched, no lines added or removed, no new sections.

Changes:
- §3.4 (deal structuring) — revise — `term_years` narrative range corrected from "from 5 to 25" to "from 1 to 25 inclusive, exactly the range section 2.5 enforces" — `implementation/routes_b.py:42` (`req_int(data, "term_years", 1, 25)`, inclusive per `core.py:443-455`).
- §3.4 (deal structuring) — revise — `escalation_pct_per_year` narrative range corrected from "from 0.0 to 5.0" to "from 0.0 to 10.0 inclusive" — `implementation/routes_b.py:49` (`req_num(..., minimum=0, maximum=10)`).
- §3.5 (term sheet rounds) — revise — `proposed_escalation_pct_per_year` corrected from "from 0.0 to 5.0" to "from 0.0 to 10.0 inclusive", noting `counter_escalation_pct_per_year` carries the same bounds — `implementation/routes_b.py:157`, `routes_b.py:248`.
- §3.7 (posting an instrument) — insert — named the error for the two posting preconditions: a non-`PROPOSED` instrument or a `NOT_SUBMITTED` deal is refused with `ERR_INVALID_STATE_TRANSITION`, and both refusals precede the `expected_deal_version` comparison (409 beats 412) — `implementation/routes_b.py:559-567`.

Per-edit pre-edit search log:

Edit 1 — `term_years` range. (a) Subject: accepted range of `term_years`. (b) Enumerated: `grep -n "term_years" implementation/*.py` → only `routes_b.py:42` (validation) and `routes_b.py:76` (storage); no other endpoint accepts or recomputes it, `calc.py` never reads it; `core.py:443-455` confirms inclusive bounds; `grep -n "term_years" PRD.md` → only §2.5 line 88 and §3.4 line 204, so §2.5 stays verbatim as the authority. (c) No adjustment beyond pointing the narrative at §2.5.

Edit 2 — deal `escalation_pct_per_year` range. (a) Subject: accepted range of the deal's escalation field. (b) Enumerated: `routes_b.py:49` (creation validation), `routes_b.py:81` (storage), `routes_b.py:275-276` (overwritten from the accepted round's `proposed_escalation_pct_per_year`, itself bounded 0–10, so a deal can legitimately carry up to 10 via the accept path), `calc.py:202-206` (`deal_contract_price` consumes it with no further bound), `routes_a.py`/`routes_c.py` (no escalation writer). (c) Adjustment: left the existing "at most two decimals" clause untouched rather than restating it — the impl quantizes/stores rather than rejecting on decimal width, and touching that clause was out of scope and would have risked a fresh false claim.

Edit 3 — round escalation range. (a) Subject: accepted range of escalation on a negotiation round, tabled or countered. (b) Enumerated: `routes_b.py:157` (`proposed_escalation_pct_per_year`, `req_num` 0–10), `routes_b.py:248` (`counter_escalation_pct_per_year`, `opt_num` 0–10), `routes_b.py:294-296` (counter value lands on the successor round's `proposed_escalation_pct_per_year`, falling back to the answered round's value when omitted), `routes_b.py:275-276` (accept path copies it onto the deal). (c) Adjustment: widened the wording to name `counter_escalation_pct_per_year` explicitly, because the enumeration showed the counter field shares the identical bound and feeds the same round field — a bound stated only for the tabled field would have left the counter path under-determined against the impl. Deliberately did not pin the omitted-counter-field inheritance (out of scope).

Edit 4 — posting precondition error code. (a) Subject: the error code and ladder position for the two state preconditions on `POST /ppa/credit-support/{id}/post`. (b) Enumerated: `routes_b.py:559-566` (instrument `!= PROPOSED` → `ERR_INVALID_STATE_TRANSITION`; `credit_status` not in the four-value set → same), `routes_b.py:567-568` (`expected_deal_version` → `ERR_STALE_VERSION`, strictly after both), `calc.py:25-26` (`CREDIT_STATUS` has exactly five members, so `NOT_SUBMITTED` is provably the only excluded value), `routes_b.py:617-622` (the release path's two preconditions — also `ERR_INVALID_STATE_TRANSITION`, so no tension), `routes_b.py:495-530` (registration takes no state precondition and does not touch the deal's `version`, already PRD-verbatim), `core.py:185` (409 mapping). Also checked parallel "undedicated precondition" sites that use a different code so the wording would not over-generalise: `routes_c.py:50-52` (execute's project-headroom check → `ERR_PROJECT_CAPACITY_EXCEEDED`, not 409) and `routes_a.py:186-203` (qualification-decision tier/score checks → 409). (c) Adjustment: scoped the sentence strictly to the posting endpoint's two named preconditions instead of writing the tempting general rule "any precondition with no dedicated code returns `ERR_INVALID_STATE_TRANSITION`". The enumeration showed that general rule would have mis-described `routes_c.py:50-52`, where PRD names no code and the impl answers 422 `ERR_PROJECT_CAPACITY_EXCEEDED` — a false universal that Step 9 would have had to undo.

Items checked and deliberately left unedited:
- test_13 setup fix (post against a `NOT_SUBMITTED` deal, haircut tables, `credit_support_required_usd` = 0.00 after submission): §3.7 already pins the precondition, both haircut tables, the `eligible_credit_usd` formula, and "registration does not increment the deal's `version`" verbatim. Only the error code was silent — that is Edit 4.
- test_15 assertion fix (`contracted_mw` = 0.000 for a `DRAFT` deal): §3.1's "always the sum of `contracted_mw` over the project's deals whose `status` is `EXECUTED` or `EFFECTIVE`" plus §3.4's "recomputes" already determine 0.000, and `services.py:73-86` with `always_touch=True` at all five callsites (`routes_a.py:398,400`, `routes_b.py:114`, `routes_c.py:59,201`) matches §3.4's project-`version` increment. Pure test bug — no PRD edit.
- "Other interpretations left standing" — verified each is already PRD-determined and needs no patch: `unallocated_mw` netting `PROPOSED`+`CONFIRMED` (§3.6 verbatim), `allocation_share_pct` 4dp (§2.6/§3.6), interval/period MWh 4dp (§3.9), `PricingNode` lacking `version`/`updated_at` (§2.4 verbatim), swept `OPEN`→`COUNTERED` setting `responded_by_user_id` (§3.5 names it and does not claim `responded_at` is stamped; `routes_b.py:189-194` agrees).
- Pre-existing PRD/impl gaps found but left as out of scope for Step 8 (flagged for Step 9): decimal-width limits on `contracted_mw`/`escalation_pct_per_year` are quantized rather than rejected; `PARENT_GUARANTEE` posting also rejects a guarantor whose `credit_tier` is null; omitted counter fields inherit the answered round's proposed values.

ORCHESTRATOR DECISION for Step 9: the scan will be run as THREE sequential module-partitioned passes over one shared `PRD_COMPLETED.md`, not a single pass. A single agent asked to walk ~3,300 lines of implementation across 7 modules against a 419-line PRD reliably under-scans and can return a near-identical file. Partition: pass 1 = `core.py` + `app.py` + `calc.py` (envelope, RBAC, validation ladder, pagination, clock, every calculation and constant) and performs the `cp` from PRD_FINALIZED.md; pass 2 = `services.py` + `routes_a.py` (recomputations and cascades, clock/pricing-node/offtaker/project endpoints); pass 3 = `routes_b.py` + `routes_c.py` (deals/rounds/allocations/credit-support; execute/CP/terminate/settlement/attributes/risk). Passes 2 and 3 must NOT re-copy the file.

## Step 9: Complete PRD — 2026-09-04T19:35:00.000Z

Run as three sequential module-partitioned passes over one shared `PRD_COMPLETED.md`. Pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 edited in place. Final result: 419 lines / 125,292 bytes, 67 edits total, +18,580 chars over `PRD_FINALIZED.md`, 0 net lines, no new sections.

### Pass 1 — `core.py` + `app.py` + `calc.py`

Source 419 lines / 106,712 chars → 419 lines / 111,452 chars (+4,740). 11 lines changed at 10 locations. Ambiguity-pins 10, mismatch-revisions 1.

- §2.1 — revise — ambiguity — whitespace-only header counts as empty (401); role trimmed and matched case-sensitively against the six roles, unrecognised role name is `ERR_ROLE_NOT_PERMITTED` — `core.py:285-298`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 upper-case-alnum chars; `api_request_timestamp` is the one value read from the host wall clock, not the logical clock — `core.py:237-245`
- §2.3 — revise — ambiguity — non-integral `limit`/`offset` rejected, `offset` uncapped, empty-string params treated as absent, out-of-enum filter value is `ERR_INVALID_REQUEST`, `created_at` ties break in creation order — `core.py:523-573`
- §2.4 — revise — ambiguity — logical clock stamps `created_at`/`updated_at`; instant parsing accepts `Z`, an explicit offset (converted to UTC) or no zone (read as UTC); comparisons keep sub-second precision while rendering truncates to 3 digits — `core.py:71-112`, `core.py:321`, `services.py:12-20`
- §2.5 item 3 — revise — ambiguity — value-based shape checking: numeric strings accepted, integer fields accept anything integral, booleans accept `"true"/"false"/"1"/"0"`, JSON booleans rejected where a number is required, JSON `null` ≡ omitted, string lengths untrimmed — `core.py:144-164`, `362-363`, `443-455`, `484-493`
- §2.6 — revise — ambiguity — half-up on negatives is half-away-from-zero; all intermediates are wide exact decimal, never binary float — `core.py:128-130`, `core.py:14`
- §2.6 — revise — MISMATCH — "at most N decimals" is not a shape check: over-precise input is accepted and quantized half-up, `net_debt_to_ebitda`/`escalation_pct_per_year` kept exactly as supplied, `metered_mwh` stored at 4dp not 3, quantized values render as JSON numbers — `core.py:414-428` with `routes_b.py:64,80`, `routes_a.py:104-106`, `routes_c.py:305`
- §2.9 — revise — ambiguity — version/`updated_at` advance once per row per request, not once per cascade hop — `core.py:306-322`
- §3.7 — revise — ambiguity — a `PARENT_GUARANTEE` guarantor with a null `credit_tier` is as ineligible as a `DECLINED` one — `calc.py:245-251`
- §3.9 — revise — ambiguity — `allocation_breakdown` tie-break continues past `created_at` into proposal order; PRD had claimed `created_at` was final arbiter — `calc.py:363-364`
- §5 intro — revise — ambiguity — unrouted path → `ERR_NOT_FOUND` 404; wrong method → `ERR_INVALID_REQUEST` at 405 not 400; both decided by routing ahead of the priority-1 header check; trailing slashes tolerated — `app.py:19,29-41`

Verified-no-change (already uniquely pinned): all 38 enum member lists; every pinned constant (rating/disclosure points, 0.55/0.30/0.15 weights, 8-notch penalty, 80/62/45 tiers, 40/30/20/10 sustainability points with the 2030 cutoff, tier caps and EBITDA percentages, base year 2026, 40/60 price-tier edges, shape-premium and basis-adder matrices, capacity factors, 8760, the 250,000 increment, LC/PG/cash haircut tables, deemed and basis share tables, the 0.00 negative-price floor, CP 270/540/720/60, 14/10/15/30/180/365 day constants); the 4-step pricing chain and its quantization points; volume; 3-step collateral sizing with its ceiling; deemed generation; HOURLY vs MONTHLY netting including per-hour quantize-then-sum, the zero-delivered short circuit and the sign split; floor-mintable; largest-remainder allocation; CP template rows/order/waivability/deadline caps; `cp_completion_pct` vacuous 100.00; `risk_event_duration_days`; `allocation_share_pct`; the whole 44-id error→status map (all 44 PRD rows match impl exactly); pagination defaults/caps and `has_more`; envelope `response_type`; auth-before-shape ordering.

### Pass 2 — `services.py` + `routes_a.py`

419 lines unchanged; 111,452 → 116,668 chars (+5,216 from pass 2 alone). 22 Edit calls across 20 distinct lines. Ambiguity-pins 16, mismatch-revisions 6. The only line both passes touched is §2.5 item 3, where pass 2 appended to pass 1's list rather than replacing it.

- §2.5 item 3 — insert — ambiguity — added `p50_annual_mwh` greater than zero to the enumerated numeric ranges — `routes_a.py:325`
- §2.5 item 5 — revise — MISMATCH — `node_id` was absent from the body-FK list although the item claims to cover project creation — `routes_a.py:328`
- §3.1 — insert — ambiguity — node name uniqueness is exact, case-sensitive, untrimmed string equality — `routes_a.py:41-44`
- §3.1 — insert — ambiguity — `capacity_mw` >0 at ≤3 decimals, `cod_target_date` carries no bound against the clock, `p50_annual_mwh` >0 at 2 decimals, `interconnection_queue_position` unbounded above — `routes_a.py:322-326,334,337`
- §3.1 — insert — ambiguity — capacity pair carried at 3 decimals, `TERMINATED` deals contribute nothing, every recompute bumps the project's `version`/`updated_at` even when neither figure moves (`always_touch=True` at all four call sites) — `services.py:73-86`
- §3.1 — insert — ambiguity — `milestone` enum members named explicitly; `evidence_ref` (≥1 char) required on every advance including `OPERATIONAL`, which discards it — `routes_a.py:386-387`
- §3.1 — revise — MISMATCH — the old "final advance … recomputes `contracted_mw` and `available_mw` and nothing more" implied the other three advances skip the capacity recompute; impl runs it on all four. Also pinned that an `EXECUTED` deal with no matching `PENDING` condition is skipped by hops 3-5 entirely, and the visit order — `routes_a.py:396-400`, `services.py:270-283`
- §3.2 — revise — MISMATCH — the guarantor-cycle guard only errors when the upward walk reaches the buyer being linked; a pre-existing loop elsewhere in the chain just ends the walk and the link is accepted (PRD claimed any revisited node is `ERR_GUARANTOR_CYCLE`) — `services.py:60-69`
- §3.2 — insert — ambiguity — the rating-agency/`NR` requirement fails with `ERR_INVALID_STATE_TRANSITION`, not a shape violation — `routes_a.py:159-161`
- §3.2 — insert — ambiguity — absent/empty `conditions` on `CONDITIONAL` is `ERR_INVALID_REQUEST` at priority 3 (ahead of the buyer's 404 and the state gate); all four tier/sustainability predicates fail with `ERR_INVALID_STATE_TRANSITION`; tier tested before sustainability — `routes_a.py:179-205`
- §3.3 — insert — ambiguity — the same-band branch is residual (covers `WATCHLIST`+`SUBPRIME`, and `WATCHLIST`+`DECLINED` with null `watchlist_since`); visits deals at every status; the re-size also refreshes `expected_annual_mwh`/`exposure_usd`; every re-size stops after the snapshot when `contract_price_usd_per_mwh` is null — `services.py:158-160,255-261`, `routes_a.py:264`
- §3.3 — insert — ambiguity — downgrade hop two also re-snapshots `collateral_threshold_usd` and re-sizes `expected_annual_mwh`/`exposure_usd` — `services.py:148-165`
- §3.3 — insert — ambiguity — downgrade hop four is exactly one level deep, no recursion into grandchildren, never `sustainability_score`, never the child's own deals — `services.py:232-239`
- §3.3 — insert — ambiguity — recovery re-snapshots `collateral_threshold_usd` too and has NO guarantor-children hop, despite "the same machinery in reverse" — `services.py:242-252`
- §3.3 — insert — ambiguity — on `WATCHLIST → REJECTED`, `watchlist_since` is retained rather than cleared, `decision_by_user_id` not re-stamped, and neither the deal re-size nor the children hop fires — `routes_a.py:260-263`
- §3.3 — revise — MISMATCH — the attribute-batch buyer view is also filterable by `vintage_month`; membership is by current `transferred_to_offtaker_id`, so a cancelled conveyance drops out — `routes_a.py:287,291`
- §3.7 — insert — ambiguity — `EXPIRED` and `PROPOSED` instruments count in none of the three buckets, so a swept expiry is the one event breaking the stated posted+released+drawn conservation — `services.py:104-120`
- §3.8 — insert — ambiguity — "passed `commercial_operation_deadline`" is strict for `SELLER_DEFAULT` and `COD_DEADLINE_MISSED`, the one exclusive boundary against §2.10's blanket inclusivity — `services.py:327,331`
- §3.8 — insert — ambiguity — the branch that fails `PENDING` conditions does not stamp `resolved_by_user_id`, unlike an explicit `FAIL` — `services.py:347-352`
- §4 `/_clock/set_current_utc` — insert — ambiguity — response `data` is a single object echoing `current_utc` — `routes_a.py:29`
- §4 `GET /ppa/offtakers` — revise — MISMATCH — filter is `parent_guarantor_offtaker_id`, not `credit_rating` (which impl does not accept) — `routes_a.py:131-141`
- §4 `POST /ppa/projects` — revise — MISMATCH — creates in `PRE_DEVELOPMENT`, not `DEVELOPMENT` (not a member of the project status enum) — `routes_a.py:339`

### Pass 3 — `routes_b.py` + `routes_c.py`

Final 419 lines / 125,292 bytes; +8,576 chars from pass 3 alone, 0 net lines, 34 edits. Ambiguity-pins 17, mismatch-revisions 17 (15 pure inserts, 19 in-place revisions). `cmp` vs `PRD_FINALIZED.md` differs at byte 2684 / line 15 — not byte-identical. Structure unchanged: 5 `##` and 19 `###` in both files.

- §2.1 — insert — ambiguity — enumerated the exactly four operations applying the deal-level counterparty comparison (fetch deal, answer round, dispute period, file claim), the two that narrow to the anchor buyer alone (accept, dispute), the allocation-slice check that shares `ERR_NOT_DEAL_COUNTERPARTY` but compares against the slice's own `offtaker_id` so even the anchor is refused, that no other role is ownership-tested, and that no list read is — `core.py:679`, `routes_b.py:145,257,382`, `routes_c.py:375,574`
- §2.1 — revise — MISMATCH — `created_by_user_id` entity list extended to `DealAllocation` and `CreditSupportInstrument` — `routes_b.py:352,527`
- §2.1 — revise — MISMATCH — audit-trail field list extended with `minted_by_user_id` on `EnvironmentalAttributeBatch` — `routes_c.py:450`
- §2.5 — revise — MISMATCH — ladder item 29 now covers execution as well as deal creation — `routes_c.py:52`
- §3.5 — insert — ambiguity — `proposed_by: OFFTAKER` clears the enum shape check and is refused by the state gate behind the deal's 404 — `routes_b.py:167`
- §3.5 — insert — ambiguity — `response_deadline` is caller-supplied and carries no bound against the logical clock — `routes_b.py:163`
- §3.5 — revise — MISMATCH — `DRAFT`/`UNDER_NEGOTIATION`/`TERMS_AGREED` are the only legal tabling statuses, and the OPEN-round sweep runs on every path (not only `UNDER_NEGOTIATION`) — `routes_b.py:170,186`
- §3.5 — revise — MISMATCH — a `COUNTER` may come from a confirmed-slice holder; only `ACCEPT` is anchor-only, and the check is decided from `response` ahead of the round state and deadline tests — `routes_b.py:257`
- §3.5 — revise — MISMATCH — omitted counter terms fall back to the answered round's proposed values (and `redline_items` to `[]`), and `round_count` increments on the counter path only — `routes_b.py:282,291-308`
- §3.6 — insert — ambiguity — `confirmed_at` survives a withdrawal out of `CONFIRMED` rather than being cleared — `routes_b.py:407-415`
- §3.7 — insert — ambiguity — credit submission never touches `credit_approved_by_user_id`, and moves nothing else on the deal — `routes_b.py:426`
- §3.7 — insert — ambiguity — instrument registration has no state gate at all (any deal `status`/`credit_status`), and `B`/`CCC`/`NR` are accepted here and refused only at posting — `routes_b.py:493-530`
- §3.7 — insert — ambiguity — `decision_note` accepted at any length including empty, then discarded — `routes_b.py:467`
- §3.8 — insert — ambiguity — execution re-checks project headroom with the same `ERR_PROJECT_CAPACITY_EXCEEDED` and same inclusive comparison as creation — `routes_c.py:52`
- §3.8 — insert — ambiguity — missing `evidence_ref`/`waiver_justification` is `ERR_INVALID_REQUEST` at priority 3, ahead of the condition's own 404 — `routes_c.py:88`
- §3.8 — insert — ambiguity — `RECURE` leaves `resolved_by_user_id` standing at the operator who failed the condition — `routes_c.py:149`
- §3.8 — revise — ambiguity — the DISPUTED-period refusal carries `ERR_INVALID_STATE_TRANSITION` and sits between the CP_FAILURE segregation check and the vesting test — `routes_c.py:169-180`
- §3.8 — insert — ambiguity — opening a settlement period leaves the parent deal row and its `version` untouched — `routes_c.py:208-252`
- §3.9 — insert — ambiguity — the per-`action` role narrowing and the missing-`dispute_reason` 400 both precede the period's 404 — `routes_c.py:359-370`
- §3.9 — insert — ambiguity — `claimed_by` is stored as supplied with no cross-check against the acting role — `routes_c.py:565`
- §3.9 — revise — MISMATCH — `price_adjustment_usd_per_mwh` carries no request-shape range; omission, out-of-range and non-positive-result all land at position 28 as `ERR_PRICE_ADJUSTMENT_INVALID`/422; quantised to 2dp half up BEFORE the range test; ignored outright off the change-in-law path; `REJECT` leaves `duration_days` null and the deal untouched — `routes_c.py:634,659-661`
- §3.9 — insert — ambiguity — the change-in-law re-size does NOT re-snapshot `unsecured_credit_limit_usd`/`collateral_threshold_usd` — `routes_c.py:680`
- §3.9 — insert — ambiguity — the minted tally is per source period, counts only `MINTED`/`TRANSFERRED`/`RETIRED` (so a cancelled batch returns its MWh), and a re-calculation can drive the remainder negative rather than clamping at zero — `routes_c.py:406-412,430`
- §3.9 — revise — ambiguity — `minted_by_user_id` stamped; source period recorded internally but echoed in no response field — `routes_c.py:450`
- §4 preamble — revise — MISMATCH — replaced the blanket "creates answer 201" rule with the exact eleven 201 endpoints, and called out the two row-creating actions that answer 200 (counter-response, execution)
- §4 — revise — MISMATCH — `GET /ppa/deals` filter list gains `settlement_point_id` — `routes_b.py:123`
- §4 — revise — MISMATCH — `POST .../rounds` row: caller-supplied `response_deadline` (not "fourteen-day"), and "escalation" rather than "tenor" — `routes_b.py:163`
- §4 — revise — MISMATCH — `GET .../rounds`: `round_number` ordering plus the `proposed_by` filter — `routes_b.py:229-230`
- §4 — revise — MISMATCH — `GET .../allocations` filter list gains `offtaker_id` — `routes_b.py:363-364`
- §4 — revise — MISMATCH — `POST .../credit-support` arrives in `PROPOSED`, not "against an agreement in `REGISTERED` status"; no state gate — `routes_b.py:493-530`
- §4 — revise — MISMATCH — `GET .../credit-support` filter list gains `purpose` — `routes_b.py:537`
- §4 — revise — MISMATCH — `GET .../settlement-periods` filter list gains `netting_method` — `routes_c.py:253-258`
- §4 — revise — MISMATCH — `POST .../meter-intervals` accepts periods at `OPEN`, `CALCULATED` or `DISPUTED`, not just "an open period" — `routes_c.py:285`
- §4 — revise — MISMATCH — `POST .../mint-attributes` accepts periods at `CALCULATED`, `INVOICED` or `SETTLED` — `routes_c.py:424`

Resolution of the seven leads handed down between passes: (1) the unbounded `opt_num` + `ERR_PRICE_ADJUSTMENT_INVALID` + quantise-before-bound behaviour is pinned at position 28 / 422 with the quantise-then-compare order made explicit (10.004 passes, 10.005 fails); (2) the §4 "`REGISTERED` status" phantom enum is replaced by `PROPOSED` with no state gate; (3) `settlement_point_id` added to the `GET /ppa/deals` filters; (4) `purpose` added to the credit-support filters; (5) the `snapshot=False` change-in-law re-size is pinned and tied back to §3.3's conditional re-size wording so the passes do not contradict; (6) the downward `mintable_attributes_mwh` rewrite is pinned including the `CANCELLED` exclusion and the unclamped negative remainder; (7) no edit warranted — §3.9 already reads "stamps `calculated_at` with the logical clock; and increments the period's `version` by one", matching `routes_c.py:348-353` exactly.

Pass 3 self-correction worth recording: its initial §2.1 counterparty sentence claimed five operations apply the deal-level comparison, including allocation decision. Verification showed `require_counterparty` is called at only four sites (`routes_b.py:145,257`, `routes_c.py:375,574`); `allocation_decision` (`routes_b.py:382`) raises the same error code from a distinct comparison against the slice's own `offtaker_id`. The sentence was re-revised to state this correctly.

ORCHESTRATOR VERIFICATION: `PRD.md` 419 lines / 106,026 bytes, `PRD_FINALIZED.md` 419 lines / 106,712 bytes, `PRD_COMPLETED.md` 419 lines / 125,292 bytes. `cmp` confirms all three are pairwise distinct (no byte-identical Step 9 output). `PRD_COMPLETED.md` ends at `| ERR_TERMINATION_RIGHT_NOT_VESTED | 422 |`, the final row of the §5 error table — a real section boundary, no truncation. 26 `##`-level headings retained. Steps 8 and 9 touched only PRD prose, never `implementation/` or the tests, so the Step 7 verified sweep (8/8 rounds at 100/100) remains the standing test result.

## Pipeline complete — 2026-09-04T19:36:00.000Z

All nine steps finished. Final state: 12 entities, 51 endpoints, 44 error codes; 100 tests across 15 modules (18/18 queue-A and 61/61 queue-B design instances, zero skipped, zero deleted); 8/8 sweep rounds at 100/100 verified against on-disk `results.$i.json`; `workspace/PRD_COMPLETED.md` written.
