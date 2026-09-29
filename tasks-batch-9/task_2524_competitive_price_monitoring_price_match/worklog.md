# Worklog — task_2524_competitive_price_monitoring_price_match

## Step 1: Create task directory — 2026-09-03T05:17:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2524_competitive_price_monitoring_price_match` and its `workspace/` subdirectory. Index 2524 was pre-assigned by the orchestrating caller; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-03T06:52:00.000Z

All three scaffold artifacts are complete, YAML-valid, and lint-clean.

**Output directory** `/home/ubuntu/github/CodingPRD/tasks/task_2524_competitive_price_monitoring_price_match/`
- `SCAFFOLD.yaml` — 2258 lines / 136 KB (§1.0–§1.7 only; contains neither design key)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1755 lines / 117 KB (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 3888 lines / 274 KB (single key `scaffold_corner_design`)
- (`worklog.md` + empty `workspace/` are the generator skill's own Step-1 artifacts, left in place)

**Lint verdict (verbatim)**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2524_competitive_price_monitoring_price_match/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2524_competitive_price_monitoring_price_match/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2524_competitive_price_monitoring_price_match/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    53
  §1.1 entities declared:     13
  §1.8 instances scanned:     22
  §1.9 instances scanned:     64
  Calls scanned (§1.8+§1.9):  895

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**SCAFFOLD.yaml counts** — 13 entities (Market, Competitor, Product, Store, CompetitorProductLink, PriceObservation, PriceIndexReport, RepricingRule, PriceChangeOrder, PriceMatchPolicy, PriceMatchClaim, LabelPrintBatch, immutable OverrideLog) · 8 state machines (incl. PriceChangeOrder's two parallel dimensions `status` and `signage_status`) · 2 OCC rules (412) · 12 calculations · 37 validations (priority ladder 10–88) · 53 endpoints under `/pricing/...` · 48 error codes · 7 roles (2 store-`entity_backed`, segregation-of-duties model). Profile: expert_plus, flat topology, cyclic state machines, immediate consistency.

**§1.8 difficulty design — 9/9 rules, 22 instances**: dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 3, priority_pair_validation_conflict 2, boundary_precision_check 3, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2.

**§1.9 corner design — all 9 taxonomy sections, 87 instances (64 full recipes + 23 `excluded_because` stubs)**: entities 11, state_machines 15, calculations 14, validations 22, endpoints 10, errors 3, rbac 5, cross_cutting_complexity_layers 5, consistency_model 2.

Three scaffold self-inconsistencies found while authoring recipes were fixed in `SCAFFOLD.yaml`: the duplicate-observation rule (now an explicit 60-minute strict proximity window matching validation 78), missing error mapping for the batch `window_start` / order `effective_from` timing preconditions (now folded into `ERR_INVALID_STATE` and validation 40), and `ERR_NO_CONFIRMED_MATCH`, whose `verification_link_id` is resolved once at claim creation and never re-resolved (condition and validation 62 now say so, and the recipe's positive control is a second claim filed after confirmation rather than a re-decide).

## Step 3: Copy shared files — 2026-09-03T06:52:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T07:05:00.000Z

PRD generated at `workspace/PRD.md`.

**Line count:** 473 lines (96,776 bytes). File ends cleanly at the final row of the §5 error table (verified independently by the orchestrator: `tail -25` shows the error catalogue's last row, a real section boundary — not truncated). Built via 6 chunked `cat >>` appends. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, and no sibling task directory was read.

**Section list**

- §1 Introduction (3 paragraphs)
- §2 Global Specifications — 2.1 User and Role-Based Access Control · 2.2 API Response Structure (verbatim) · 2.3 Pagination · 2.4 Resource Identity, Timestamps and Revision Counters · 2.5 The Logical Clock · 2.6 Currency, Basis Points and Rounding Discipline · 2.7 Optimistic Concurrency Control · 2.8 Market Pricing Posture as a System-Wide Gate · 2.9 Segregation of Duties and Store Scoping · 2.10 Path Resolution and Referential Coherence · 2.11 Order of Evaluation · 2.12 Conserved Ledger Quantities
- §3 Business Logic & Workflows — 3.1 Standing Up a Market · 3.2 Matching Products to Competitors · 3.3 Collecting Competitor Prices and Choosing the Effective Price · 3.4 Competitor Lifecycle · 3.5 Index Reporting, Perception Research and the Market Posture Gate · 3.6 Automated Repricing Rules and the Proposal of a Price Change · 3.7 Approving and Executing a Price Change · 3.8 Price Match Policy, Claim Intake and Verification · 3.9 Honouring a Claim, the Store Override Ledger, and Reversal · 3.10 Shelf Labels, Printer Capacity and the Signage Dimension
- §4 Endpoint Definitions (4-column table, 53 rows)
- §5 Error Code Catalogue (2-column table, 48 rows)

**Hard Contract reports**

```
Field coverage check:
- entities[].fields: 128 required, 128 present, 0 missing
- endpoints[].request_body/input/query_params/path_params: 86 required, 86 present, 0 missing
Status: PASS
```
```
Rule coverage check:
- validations[] with priority: 37 checked, 37 expressed in prose (§2.11 renders the full ascending ladder incl. the three same-priority pairs at 36/68/79), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_product_version / expected_market_version + error_id + 412 all named in §2.7), 0 missing
- state_machines[].transitions: 41 checked (Competitor 5, Link 8, Observation 2, Report 2, Order status 11, Order signage 4, Claim 7, Batch 4), 41 fully expressed with preconditions and every side-effect level, 0 missing
- calculations[]: 12 checked, 12 fully expressed in prose (all constants embedded, pinned orderings and worked figures 9700/6000, 9743/9760, 27500-vs-27498, 2050→103→1947 preserved), 0 missing
- validations[] conditions: 37 checked, 37 matchable to error_id in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: 53 endpoints checked, all side-effect sets and all applies_to scopes enumerated (8 store-scoped ops, 4 posture-gated ops, 14 state-guarded action endpoints), 0 missing
- entities[].fields[] structured content: 128 checked, defaults / initial values / enum members / computed formulas reconstructible from prose, 0 missing
- sibling-branch symmetry: 9 groups checked (PROPOSED-vs-UNDER_REVIEW confirm; the two reject edges; three SUPERSEDED edges; two RETIRED edges; two CANCELLED edges; two confidence variants; two basis variants; two proposal variants; DEBIT/CREDIT ledger), 0 asymmetric
Status: PASS
```
```
Path purity check (§3 only):
- backtick tokens scanned: 1036
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional verifications: §2.2 is byte-identical to `section-2.2-response-structure.md`; all 48 error IDs appear in §1–§3 prose (not only in the §5 table); all state values and enum members appear verbatim; all 7 role names present with their `identity:` semantics translated (5 opaque, `StoreAssociate`/`StoreManager` entity-backed to `Store`); no fuzzy/approximating hedges on any threshold.

**Two scaffold internal conflicts resolved in favour of the §1.2 state-machine table** (worth flagging to the test-suite generator): the label-batch endpoint blurb says completion moves signage "from `PRINTED` to `RELEASED`" and cancellation returns signage to `NOT_REQUIRED`, whereas the state machine specifies `QUEUED → PRINTED` on completion and `QUEUED → RELEASED` on cancellation — the PRD follows the state machine. Likewise the claim-reverse blurb says the spawned order moves to `SUPERSEDED` while the state machine specifies `APPROVED → SUSPENDED`; the PRD follows the state machine. Two other places where the error catalogue is broader than the validations' `applies_to` (FROZEN posture also blocking change-order *creation*; `ERR_DUPLICATE_RESOURCE` also covering global `market_code` and a second `ACTIVE` policy per market) were rendered inclusively so nothing is omitted. The observation TTL boundary follows the pinned formula (exactly 72 hours old still qualifies) rather than the looser `input_set` prose.

## Step 5: Generate unit tests — 2026-09-03T07:45:00.000Z

Generation complete and centrally audited.

### Files created

**`test_helpers/` (Stage 1) — 1762 lines, 9 files**

| File | Lines |
|---|---|
| `types.py` | 418 |
| `api_client.py` | 196 |
| `api_errors.py` | 110 |
| `assertions.py` | 242 |
| `constants.py` | 65 |
| `factories.py` | 166 |
| `test_users.py` | 61 |
| `fixtures.py` | 466 |
| `__init__.py` | 38 |

**`test_suite/` (Stage 2) — 8517 lines, 18 files**

| File | Lines | Tests |
|---|---|---|
| `conftest.py` | 67 | — |
| `test_01_match_confidence_scoring.py` | 169 | 3 |
| `test_02_price_index_computation.py` | 282 | 5 |
| `test_03_pricing_formula_and_lifecycles.py` | 776 | 10 |
| `test_04_cascade_propagation.py` | 478 | 6 |
| `test_05_validation_precedence.py` | 222 | 4 |
| `test_06_threshold_boundaries.py` | 388 | 6 |
| `test_07_cross_entity_state_gates.py` | 268 | 4 |
| `test_08_temporal_windows_and_conservation.py` | 520 | 8 |
| `test_09_reference_data_records.py` | 298 | 6 |
| `test_10_entity_field_contracts.py` | 302 | 5 |
| `test_11_workflow_state_machines.py` | 750 | 11 |
| `test_12_pricing_calculations.py` | 842 | 9 |
| `test_13_intake_and_matching_validations.py` | 429 | 5 |
| `test_14_claim_and_order_validations.py` | 929 | 9 |
| `test_15_endpoint_contracts.py` | 569 | 6 |
| `test_16_authorization_and_store_scope.py` | 718 | 8 |
| `test_17_consistency_and_cross_cutting.py` | 510 | 5 |

### Coverage

- **§1.8 (Difficulty, queue A): 22 of 22 instances translated, 0 skipped.** 46 tests. Every instance has ≥2 tests; `confidence_variant_identifier_anchored_vs_attribute_blend` and `price_index_matched_basket_vs_imputed_full_catalog_divergence` got 3 each. No instance failed the two-condition filter — the PRD carries a rule-bearing sentence and a uniquely-derived outcome for all 22.
- **§1.9 (Corner, queue B): 64 of 64 non-stub instances translated, 0 skipped.** 64 tests, ≥1 per instance. The 23 `excluded_because:` stubs were not translated; all 23 `difficulty_instance` cross-references were verified to resolve to a real `rule_id / name` pair in the difficulty index.
- **Total: 110 test functions**, confirmed by `pytest --collect-only` (110 collected, all imports resolve).

### Audit results (all clean)

- Every test has exactly one `Design:` line, it is the last docstring line, and every tag resolves to a real instance in the correct queue. No dual tags, no stub translations, no unknown names.
- Every test carries a `PRD: "..."` citation whose leading 12 words are a literal substring of `PRD.md`.
- All 48 distinct asserted `error_id`s are named in PRD prose above the error catalogue table, not just in the table.
- Zero `skip`/`xfail` markers. `py_compile` clean across all 27 generated `.py` files. No scaffold leakage (the single `§` hit is `§4` inside a verbatim PRD sentence about role authorisation — a PRD-internal reference, not a scaffold one).

### Design-index defects the translators found (all resolved PRD-first)

Five places where a pre-computed yaml literal contradicts the PRD; the PRD won in each case, with the deviation commented inline:
1. `publish_frozen_report_suspends_orders_and_releases_labels_depth4` asserts market `version + 1`, but report creation and publication each bump it, so the test asserts `+2`.
2. Several instances assert product `version` literals one short of the PRD's increment rules (create + change-order create + execute); those version literals were dropped or re-read via GET rather than encoding a contradiction.
3. `corner_batch_cancel_resets_the_orders_it_was_carrying` and `corner_label_batch_selector_...` assert `signage_status == NOT_REQUIRED` after cancellation; the PRD says `QUEUED → RELEASED`, so the tests assert `RELEASED`.
4. `corner_rejected_write_leaves_no_partial_state` says `ERR_OVERRIDE_BUDGET_EXCEEDED` is 422; the PRD says 409, and the registered status map governs.
5. `corner_category_excluded_outranks_no_savings` staged two ACTIVE policies in one market, which the PRD refuses with `ERR_DUPLICATE_RESOURCE`; the control programme was moved to a second market with identical numeric limits.

Also: `created_at`/`updated_at` are asserted with `is_iso8601_timestamp` rather than equality to the logical clock, since the PRD's enumerated clock rules do not cover `created_at`; `last_price_change_at` uses a prefix match to tolerate the mandated 3-digit fraction.

## Step 6: Generate implementation — 2026-09-03T07:45:30.000Z

Implementation complete and verified.

### Files

`workspace/implementation/` — 3354 lines total, 25 Python modules plus launcher:

| file | lines | file | lines |
|---|---|---|---|
| `start.sh` | 10 | `routes/change_orders.py` | 219 |
| `requirements.txt` | 1 | `routes/claims.py` | 335 |
| `app.py` | 62 | `routes/clock_routes.py` | 18 |
| `clock.py` | 23 | `routes/common.py` | 63 |
| `db.py` | 66 | `routes/competitors.py` | 114 |
| `errors.py` | 82 | `routes/index_reports.py` | 115 |
| `middleware.py` | 63 | `routes/label_batches.py` | 123 |
| `response.py` | 92 | `routes/markets.py` | 77 |
| `util.py` | 173 | `routes/matches.py` | 200 |
| `services/calc.py` | 445 | `routes/observations.py` | 119 |
| `services/cascades.py` | 289 | `routes/policies.py` | 95 |
| `services/serialize.py` | 259 | `routes/products.py` | 96 |
| `services/ledger.py` | 65 | `routes/repricing_rules.py` | 90 |
| `routes/__init__.py`, `services/__init__.py` | 0 | `routes/stores.py` | 60 |

### Endpoints

**53 of the PRD's 53**, verified programmatically against `app.url_map` (markets 3, competitors 4, products 3, stores 3, matches 5, observations 4, index-reports 4, repricing-rules 4, change-orders 6, match-policies 3, claims 8, label-batches 5, clock 1). Flask's implicit `/static` route is disabled (`static_folder=None`) so the count is exactly 53.

### Boot / smoke result

`py_compile` clean over all 25 modules. Booted repeatedly via `PORT=<high> bash start.sh`; Flask serves on `0.0.0.0` within ~1s. Store confirmed **empty on every fresh boot** (all 12 collections `total_count=0`), nothing persists across restarts, no on-disk artifacts beyond `__pycache__` (removed).

5 behavioural suites (~150 assertions) run end to end — **all green**:
- Both PRD worked examples reproduce exactly: the pinned band-then-floor proposal (`target 21824 → banded 22500 → proposed 27500`, `floor_binding`/`band_breach` true) and the beat-bonus claim (`bonus 103`, `honored 1947`, `discount 553`).
- Depth-5 execute cascade including drift auto-suspend (`MATCH_DRIFT_AUTO_SUSPEND`) with its L4/L5 tail; FROZEN freeze cascade (orders suspended, `QUEUED → RELEASED`, batch `item_count` falls, store slots returned, ACTIVE policies suspended) and the reversible thaw to `DRAFT` with signage left `RELEASED`; honour/reverse `DEBIT`/`CREDIT` ledger conservation and the synthesized `PRICE_MATCH` order; print-batch lifecycle to `PRINTED`, cancel, window buffer and capacity; both loop ceilings; OCC on both dimensions; segregation of duties; store scope; 35-rank precedence spot checks.

Six apparent "failures" during verification were all wrong expectations in the verification scripts, each resolved against PRD text rather than by changing code: `OPEN_REVIEW` does not bump `review_round`; observation proximity is scoped per `collection_method`; the error id is `ERR_MAX_REVIEW_ROUNDS`; claim intake has no policy-ACTIVE gate (only `/verify` does); and the market's four derived fields are recomputed **only** on publication, so a drafted INSUFFICIENT report leaves `insufficient_data_report_count` at 0.

One residual interpretive risk stands, now measured: a supersede whose superseded order has an open-ended (`effective_until: null`) window covering the new one is refused with `ERR_EFFECTIVE_WINDOW_OVERLAP`, since neither the PRD nor the scaffold defines an exclusion for the order being replaced. Supersede with disjoint or exactly-touching windows works.

### Orchestrator note on Step 5/6 concurrency

Steps 5 and 6 were launched as two background agents in immediate succession. `test_suite/` did not exist when the impl generator started, and the impl prompt additionally forbade reading `test_suite/`/`test_helpers/` outright, so the isolation the skill requires held.

## Step 7: Run tests and iterate — 2026-09-03T08:05:00.000Z

Clean 8-round sweep: **110/110 passed in every round**, union of failures = 0.

**Iterations run:** 2 (iteration 1 sweep: 100/110 in all 8 rounds, 10 deterministic failures, no flakiness; iteration 2 sweep: 110/110 in all 8 rounds).

**Tests deleted:** none. One assertion was removed under STEP 1c (partial coverage) — see below.

**Fixes applied to `test_suite/`:**

- `test_16_authorization_and_store_scope.py` and `test_17_consistency_and_cross_cutting.py` — 16 occurrences of the double-unwrap `get_success_data(validate_success(resp))`. `validate_success` already returns `body["data"]`, so the outer `get_success_data` received a dict and blew up on `.status_code`. Unwrapped to a single `validate_success(...)`. This was the shared upstream cause of the 3 `'dict' object has no attribute 'status_code'` failures plus 4 `Expected 200, got 201` failures across 8 tests.
- Same two files — 9 of those calls wrapped a `create_*` endpoint and were validated at the default 200. PRD §4: *"A request that successfully creates a new resource returns HTTP 201"* — added the explicit `201` expected status, making the assertion more faithful, not less.
- `test_15_endpoint_contracts.py::test_moving_the_clock_recomputes_no_stored_state_but_governs_the_next_call` — removed the trailing `validate_error(response, ERR_NO_COMPETITOR_BENCHMARK)` block. **Collapse pattern: assertion contradicts PRD / not uniquely derivable.** The test itself asserts (correctly, per PRD §2.5 *"Moving the clock recomputes no business state"*) that the match keeps `data_status == "SUFFICIENT"` after the clock jumps past the 72-hour observation window; but PRD §3.6 pins benchmark selection to *"confirmed matches on this product with `data_status` `SUFFICIENT` and `confidence_bp` of at least 7000, on `ACTIVE` competitors of `PRIMARY` tier"* — no observation-freshness re-check. A PRD-faithful implementation therefore finds the benchmark and the create succeeds. Replaced with a PRD-verbatim demonstration of the same docstring claim ("governs the next call"): a sighting dated `2026-08-03` is refused with `ERR_OBSERVATION_IN_FUTURE` before the move and accepted after it (PRD §3.3: *"An `observed_at` later than the logical clock's current instant is refused with `ERR_OBSERVATION_IN_FUTURE`"*). Design tag: `Corner/endpoints/corner_clock_endpoint_moves_time_without_recomputing_state`.

**Fixes applied to `test_helpers/`:** none — the fixture layer was PRD-faithful.

**Fixes applied to `implementation/`:**

- `routes/matches.py`, `review_match` REJECT branch — re-run `calc.elect_effective_price(link)` after the `LINK_REJECTED` void cascade. PRD §3.3: *"the election is re-run every time the pool changes — on a new observation, on a void, when a match is confirmed, and inside the competitor suspension and retirement cascades"*, and *"When no observation qualifies, the match falls to `data_status` `INSUFFICIENT`, with `latest_effective_price_cents`, `selected_observation_id` and `gap_bp` all null"*. Fixes `test_rejecting_a_match_voids_every_active_observation_it_holds`.
- `services/cascades.py`, `retire_competitor` — same re-election after the `COMPETITOR_RETIRED` void, since §3.3 names the retirement cascade explicitly as an election trigger. No test covered this; applied for PRD faithfulness alongside the identical defect.

### Orchestrator verification of Step 7's claim

The 8-round sweep artifacts were re-read directly by the orchestrator rather than taken on trust: `results.1.json` … `results.8.json` each report `passed=110 total=110 failed=0`, and `grep -rh '^def test_' test_suite/ | wc -l` returns 110, so the green sweep covers the full suite with no silently-dropped tests.

Step 8 is NOT skipped: Step 7 ran 2 iterations with 2 `implementation/` fixes and 3 `test_suite/` fix groups.

## Step 8: Finalize PRD — 2026-09-03T08:12:00.000Z

Done. `PRD_FINALIZED.md` written with three traced edits.

### Line counts / delta
- `PRD.md`: 473 lines / 96,776 bytes
- `PRD_FINALIZED.md`: 473 lines / 97,889 bytes
- Δ = 0 lines (edits are inline inside existing long markdown paragraphs), **+1,113 bytes = +1.15%**

### Changes
- **§3.2 (match rejection)** — insert — after the `LINK_REJECTED` void sentence, pinned that the rejection re-runs the §3.3 effective-price election over the emptied pool, landing on `data_status` `INSUFFICIENT` with `latest_effective_price_cents`, `selected_observation_id`, `gap_bp` null and `gap_stale` false — `implementation/routes/matches.py:134-137`, `services/calc.py:104-109`.
- **§3.4 (retirement)** — insert — on `ACTIVE → RETIRED` each rejected match re-runs the election after the `COMPETITOR_RETIRED` void (same nulls); explicitly stated that `SUSPENDED → RETIRED` re-runs **no** election, so a match rejected on that edge keeps its existing elected figures — `implementation/services/cascades.py:97-111`, `routes/competitors.py:95`.
- **§3.5 (per-product benchmark selector)** — insert — the shared selector reads each match's stored `data_status`/`latest_effective_price_cents` as the last election left them and never re-tests the elected observation's freshness against the logical clock; those figures move only when a §3.3 election trigger fires — `implementation/services/calc.py:174-201`, `services/serialize.py:102-106`.

No edit was made for the two remaining `<step_7_diff>` items: the 16 double-unwrap `get_success_data(validate_success(...))` calls were a pure test-layer bug, and the 9 `201` expectations are already pinned verbatim by PRD §4 (verified all 12 create endpoints in `implementation/routes/` return 201).

### Per-edit pre-edit search log

**Edit 1 — §3.2 rejection**
- (a) Subject: what a `→ REJECTED` match review does to the match's elected/effective-price fields.
- (b) Enumerated & read: `routes/matches.py` all three review branches + `revise_match` (confirm branch elects then touches; `OPEN_REVIEW`/revise never elect), `services/cascades.py:void_active_observations`, `reelect`, `suspend_competitor`, `retire_competitor`, `services/calc.py:elect_effective_price`/`qualifying_observations`, `routes/observations.py:79,101` (both create and void re-elect unconditionally, on links of **any** status), `services/serialize.py:link` (fields are stored, not derived). Grepped `elect_effective_price|reelect|void_active_observations` across the whole impl.
- (c) Adjustment: scoped the sentence to the rejection moment ("the match then re-runs the election … over whatever the void left behind") rather than asserting a rejected match is permanently `INSUFFICIENT` — `routes/observations.py:79` re-elects on a `REJECTED` link too, so a later observation can push it back to `SUFFICIENT`. Also phrased it as one side effect of the same edge (no second mutation implied), matching the single `db.touch(link)` at `matches.py:133`.

**Edit 2 — §3.4 retirement**
- (a) Subject: the retirement cascade's effect on match election fields, on both incoming edges.
- (b) Enumerated & read: `routes/competitors.py:65-97` (`void_observations=current == "ACTIVE"`), `cascades.retire_competitor` (election only inside the `if void_observations` branch, and for all three prior statuses), `cascades.suspend_competitor` (elects only for matches leaving `CONFIRMED`; leaves `PROPOSED`/`UNDER_REVIEW` matches and their `ACTIVE` observations alone), `calc.competitor_links`.
- (c) Adjustment: split the wording per edge — added re-election only to `ACTIVE → RETIRED`, and explicitly stated the absence of re-election on `SUSPENDED → RETIRED` (needed because suspension leaves non-`CONFIRMED` matches' `ACTIVE` observations and `SUFFICIENT` data intact, so a match rejected on that edge really can stay `SUFFICIENT`). Avoided any universal "a rejected match is INSUFFICIENT" claim.

**Edit 3 — §3.5 benchmark selector**
- (a) Subject: whether benchmark eligibility re-validates observation freshness at read time.
- (b) Enumerated & read: `calc._benchmark_candidates` → `benchmark_price` → both consumers (`calc.price_index` for §3.5 reports and `calc.select_benchmark_or_fail` used by change-order creation in `routes/change_orders.py`), `calc.qualifying_observations` (the only place the 72-hour window is applied), `cascades.execute_order` level 2 (recomputes `gap_bp` from the stored `latest_effective_price_cents`, also without a freshness re-check), `serialize.link`, `clock.py`.
- (c) Adjustment: worded it as "does not **by itself** withdraw the match from the selector" and "those stored figures move only when an election trigger of §3.3 re-runs" instead of "the match remains eligible" — the match is still withdrawn by the selector's other filters (leaving `CONFIRMED`, competitor going `SUSPENDED`/`RETIRED`, tier, confidence floor), and §3.6 inherits the sentence via its "exactly the same eligibility" clause, so the wording had to stay true for the change-order path too.

## Step 9: Complete PRD — 2026-09-03T08:47:00.000Z

`workspace/PRD_COMPLETED.md` written. **Orchestrator decision (recorded per the autonomy directive):** Step 9 was deliberately run as **three sequential file-partitioned passes** over one shared output file rather than as a single subagent. A single-pass scan of a 473-line / 98 KB PRD against a 3,349-line implementation reliably under-scans, and its failure mode is silent — a `PRD_COMPLETED.md` byte-identical to its source, which looks like "nothing to fix" but actually means the walk never happened. Partitioning by implementation file makes each pass's exhaustive walk tractable and makes the scan verifiable from the file's growth. Passes were strictly sequential (never concurrent) because all three edit the same file; each later pass was told the file already exists, was forbidden to re-create it, and was given the list of what earlier passes had pinned so it would neither duplicate nor contradict them.

Net result: **54 patches** (49 ambiguity-pins, 5 mismatch-revisions) across 3 passes. `PRD_FINALIZED.md` 473 lines / 97,889 chars → `PRD_COMPLETED.md` 473 lines / **115,464 chars (+17,575, +18.0%)**, all edits inline (0 lines added, 0 sections added, 53 lines revised). Independently verified by the orchestrator: the file is not byte-identical to its source, all 30 headings survive, and the tail still ends at `| ERR_STALE_MARKET_VERSION | 412 |`.

### Pass A — global/plumbing + reference data (`app/clock/db/errors/middleware/response/util`, `services/serialize.py`, `routes/common|clock_routes|markets|competitors|products|stores`)

`PRD_FINALIZED.md` 473 lines / 97,889 chars → 473 lines / 101,946 chars (**+4,057 chars**, 15 revised lines). **14 ambiguity-pins, 1 mismatch-revision.**

- §2.1 — revise — ambiguity — whitespace-only header counts as empty; role names matched exactly and case-sensitively — `middleware.py:27-30`
- §2.1 — revise — ambiguity — store-scope test is an exact string compare of `X-User-ID` exactly as supplied (no trimming) — `middleware.py:59-63`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` plus exactly 20 upper-case-alphanumeric chars — `response.py:13-14`
- §2.2 — revise — ambiguity — `api_request_timestamp` is read from real wall-clock time, not the logical clock — `response.py:17-22`
- §2.3 — insert — ambiguity — pagination params parsed as trimmed decimal integers; integer-form phase for `limit` then `offset` precedes the range phase, so `limit=500&offset=abc` surfaces the malformed `offset` — `response.py:59-88`
- §2.3 — revise — ambiguity — `has_more` formula (`offset + rows_returned < total_count`); filters are string-form exact compares; non-matching filter yields empty page, undeclared query params ignored — `response.py:40`, `routes/common.py:49-57`
- §2.3 — revise — ambiguity — `created_at` ties in list ordering broken by ascending creation sequence — `db.py:59-61`
- §2.4 — insert — ambiguity — `created_at` stamped from the logical clock; common fields `id`/`created_at`/`updated_at`/`version` serialised after resource-specific fields — `db.py:40-47`, `services/serialize.py:7-11`
- §2.4 — revise — ambiguity — `updated_at` stamped from the logical clock and equal to `created_at` until first mutation — `db.py:43-46,50-56`
- §2.5 — insert — ambiguity — clock endpoint returns `object` envelope with 3-fractional-digit `Z` form; `current_utc` required, unparseable → `ERR_INVALID_REQUEST` 422; all client instants normalised to UTC, naive instants read as UTC — `routes/clock_routes.py:16-18`, `util.py:10-25`
- §2.6 — revise — **mismatch** — "two ratio fields" listing three corrected to "three"; ratios also accept JSON integers — `util.py:118-131`
- §2.10 — insert — ambiguity — absent/null body FK skipped (required-ness deferred to rank 5); non-string FK value fails the FK pass with that field's 404 — `routes/common.py:27-46`
- §2.11 rank 5 — insert — ambiguity — absent/unparseable/non-object body treated as `{}`; undeclared body fields ignored; optional field sent as null takes its default; booleans rejected for int/ratio; every §3 string field must be non-empty — `middleware.py:52-56`, `util.py:90-137`
- §2.11 rank 6 — insert — ambiguity — non-string enum value fails at rank 5 with `ERR_INVALID_REQUEST`; only a well-formed non-member string yields `ERR_INVALID_ENUM_VALUE` — `routes/markets.py:27-40`, `util.py:163-167`
- §3.1 — revise — ambiguity — `currency_code` accepts any non-empty string verbatim, not validated against ISO 4217 — `routes/markets.py:31-33`
- §5 — insert — ambiguity — transport-level fallbacks `ERR_NOT_FOUND` 404 / `ERR_METHOD_NOT_ALLOWED` 405 / `ERR_INTERNAL` 500 in the same envelope — `app.py:37-51`, `errors.py:61-64`

**Verified-consistent, no change needed**: `errors.py` `ERROR_STATUS` matches the §5 table entry-for-entry; every §4 role list for markets/competitors/products/stores/clock matches the route decorators; every serializer field name for `market`/`competitor`/`product`/`store`/`override_log` is already named in the PRD, with read-time-derived counters (`confirmed_match_count`, `stale_match_count`, `stale_share_bp`, `price_change_count`, `effective_floor_cents`, ledger fields) observably matching their PRD definitions; §2.11 ranks 4→5→6→22 hold in all four reference-data creates.

### Pass B — matching, observations, index reporting, repricing rules, calculation engine (`routes/matches|observations|index_reports|repricing_rules`, `services/calc.py`)

101,946 → **106,937 chars** (473 lines both; tail intact). **14 ambiguity-pins, 2 mismatch-revisions** (16 Edit calls across 15 PRD lines). Pass A's 15 patches confirmed untouched.

- §3.2 (line 200) — revise — **mismatch** — PRD read `competitor_identifier` as method-conditional ("for the other two channels it is null"); impl never cross-validates it against `match_method`, stores any non-empty string verbatim on any channel, defaults to null even under `IDENTIFIER`, and rejects `""` at rank 5 — `routes/matches.py:43-45`
- §3.2 (line 206) — insert — ambiguity — a newly proposed match's `latest_effective_price_cents`/`selected_observation_id`/`gap_bp` are null, `gap_stale` false, and no election runs at proposal time — `routes/matches.py:75-81`
- §3.2 (line 206) — insert — ambiguity — `min_confidence_bp` is parsed as a decimal integer, is not bounds-checked, and a non-integer value is **silently ignored** (request still 200) — `routes/matches.py:195-202`
- §3.2 (line 208) — insert — ambiguity — the review `note` is shape-checked (non-empty string) but never persisted or echoed; `OPEN_REVIEW` leaves `review_round` alone and moves only `updated_at`/`version` — `routes/matches.py:93-106`
- §3.2 (line 208) — insert — ambiguity — revision fields supplied as null count as absent (so `competitor_identifier` can never be cleared back to null); all five are shape/enum-checked before the `UNDER_REVIEW` and round-ceiling tests; a revision runs no election and leaves the five elected fields untouched — `routes/matches.py:148-177`
- §3.2 (line 212) — insert + revise — ambiguity + **mismatch** — the non-`ACTIVE` product/competitor guards on confirm yield `ERR_INVALID_STATE` (409), product before competitor, both before the confidence bar; confirm re-runs the **full** §3.3 election (in-stock + 72h filters) rather than "whatever `ACTIVE` observations it holds"; competitor drift counters are read-time derived so the competitor row's `version` does not move, and the match's `version` advances by exactly 1 — `routes/matches.py:107-127`, `services/calc.py:94-121`
- §3.2 (line 214) — insert — ambiguity — a rejection is one mutation of the match (`version` +1 total; the void and re-election add no further increment), each voided observation taking its own +1 — `routes/matches.py:132-137`
- §3.3 (line 218) — insert — ambiguity — observation intake consults only `link_id` resolution, never the match's `status`, so prices may be posted against `PROPOSED`/`UNDER_REVIEW`/`REJECTED` matches — `routes/observations.py:25-29`
- §3.3 (line 222) — insert — ambiguity — election tie-break chain ends in ascending creation sequence after `created_at`; the election ignores the match's `status`, so a `PROPOSED` match can reach `data_status` `SUFFICIENT` with a `gap_bp` — `services/calc.py:94-121`
- §3.3 (line 224) — revise — ambiguity — every election landing on a qualifier writes `gap_stale` false even when the winner is unchanged (so observation activity clears a §3.7 drift flag); a re-run whose five-field outcome is identical is **not a mutation** — no `updated_at`/`version` bump — `services/calc.py:101-121`, `services/cascades.py:26-31`
- §3.5 (line 244) — insert — ambiguity — `perception_survey_index_bp` must be an integer ≥ 0 with no upper bound — `routes/index_reports.py:34-36`
- §3.5 (line 246) — revise — ambiguity — benchmark selector settles a residual tie by ascending match creation sequence — `services/calc.py:192-194`
- §3.5 (line 260) — insert — ambiguity — publication never recomputes the report; `index_bp`, the four basket counts, `data_sufficiency`, `positioning_gap_bp`, `positioning_verdict` and `perception_validation` stand as computed at create — `routes/index_reports.py:69-91`
- §3.5 (line 262) — revise — ambiguity — governing-report selection settles a residual tie by ascending creation sequence — `services/calc.py:305-306`
- §3.6 (line 270) — insert — ambiguity — the rule `to_status` patch accepts only `ACTIVE`/`PAUSED` and must differ from the current status: re-asserting the same status is `ERR_INVALID_STATE` (409), not a no-op — `routes/repricing_rules.py:65-73`
- §3.6 (line 276) — insert — ambiguity — rule specificity is the binary exact-vs-wildcard distinction only, residual tie by creation sequence; brand exclusion is exact case-sensitive array membership — `services/calc.py:342-361`
- §3.6 (line 280) — insert — ambiguity — `band_breach` can only be true under `AUTOMATED_RULE`; the `HAND_SET` 0-to-unbounded band is unbreachable, so it is always false on `MANUAL` and `PRICE_MATCH` orders — `services/calc.py:380-389`

Pass B notes: §2.11 rank 5's parenthetical "ratios at least 0 and strictly below 1" was deliberately left alone (generic wording; the real bound for `max_change_pct`/`max_match_discount_pct` is (0, 1], pinned specifically in §3.6/§3.8). §3.8's `price_match_honored_price` prose already matched `services/calc.py:403-427` exactly.

### Pass C — change orders, policy & claims, labels, cascades, ledger (`routes/change_orders|claims|policies|label_batches`, `services/cascades.py`, `services/ledger.py`)

106,937 → **115,464 chars** (473 lines; tail intact). **21 ambiguity-pins, 2 mismatch-revisions.** The 31 prior patches confirmed untouched.

- §3.5 (freeze/thaw) — revise — ambiguity — thaw runs on *every* recomputation not landing on `FROZEN` (not just a market that was frozen) and thaws orders suspended by a claim reversal too; `signage_status` left as the suspension left it (`RELEASED` or `NOT_REQUIRED`, correcting "stays `RELEASED`"); policies are never reinstated — no edge back to `ACTIVE` exists — `cascades.py:198-206, 189-195`
- §3.6 — insert — ambiguity — unresolvable `signage_store_id` → `ERR_STORE_NOT_FOUND` at the `store_id` slot of the §2.10 order (after `product_id`, before `supersedes_order_id`) — `routes/common.py:13`, `change_orders.py:26`
- §3.6 — insert — ambiguity — the window-overlap test runs before the supersede and grants the superseded order no exemption; only `SUSPENDED` escapes it — `change_orders.py:82`, `cascades.py:271-288`
- §3.6 — insert — ambiguity — wrong-product or non-supersedable target → `ERR_INVALID_STATE` (409), evaluated after OCC and before the posture gate — `change_orders.py:53-60`
- §3.6 — insert — ambiguity — `SUSPENDED → SUPERSEDED` runs the (no-op) release; underlying rule is "release fires exactly when `signage_status` is `QUEUED`" — `cascades.py:211-218, 36-49`
- §3.7 — insert — ambiguity — decide `note` must be non-empty when supplied and is never persisted — `change_orders.py:146-147`
- §3.7 — insert — ambiguity — `REJECT` is not posture-gated; a rejection succeeds in a `FROZEN` market — `change_orders.py:153-154`
- §3.7 level two — insert — ambiguity — a `CONFIRMED` match with null `latest_effective_price_cents` is skipped whole (no `gap_bp`, no `version` bump); recomputed matches bump `version`; the level never clears `gap_stale` — `cascades.py:129-141`
- §3.7 level three — revise — ambiguity — staleness measured on the recomputed gap, not on a flag transition (already-stale matches enrol their competitor); competitors visited once each in match `created_at`/sequence order; `confirmed_match_count ≥ 1` stated with the other two conditions — `cascades.py:143-157`
- §3.8 (policy) — insert — ambiguity — the uniqueness check runs only for `ACTIVE` creations, so unlimited `SUSPENDED` policies may coexist; both array fields stored/echoed verbatim, duplicates neither rejected nor collapsed — `policies.py:56,61-66`
- §3.8 (intake) — insert — ambiguity — intake never tests the policy's `status`; a claim on a `SUSPENDED` policy is filed and only stopped at verification — `claims.py:22-105`
- §3.8 (verify) — revise — ambiguity — non-`ACTIVE` policy → `ERR_INVALID_STATE`; missing evidence on the restart edge → `ERR_INVALID_REQUEST`, evaluated after the state branch (so a bad state still wins) — `claims.py:120-140`
- §3.8 (decide) — revise — ambiguity — `NEEDS_EVIDENCE` does not advance `evidence_round`; `rejection_reason` null when no `reason`; `reason` discarded on the other two edges — `claims.py:154-181`
- §3.8 (decide/VERIFIED) — insert — ambiguity — policy `status` is not re-tested at the `VERIFIED` edge — `claims.py:165-172`
- §3.9 (honour gate) — insert — ambiguity — the gate's governing policy is the claim's own `policy_id` whatever its status, not the market's `ACTIVE` policy — `claims.py:196,206-209`
- §3.9 (level one) — insert — ambiguity — store and policy rows are not mutated (no `version`/`updated_at` movement); only the claim's `version` advances — `claims.py:211-213`, `ledger.py:44-65`
- §3.9 (level two) — insert — ambiguity — synthesized order's null `rule_id`/`benchmark_price_cents`/`requested_price_cents`/`supersedes_order_id`, `authored_by_user_id` = honouring caller, `decided_by_user_id` null; `proposed_price_cents` is the frozen honoured price verbatim and overrides the floor clamp (`floor_binding` can read true); exempt from the window-overlap test and from OCC — `claims.py:306-335`
- §3.9 (ledger) — insert — ambiguity — store-level figures read the market's single `ACTIVE` policy, `override_budget_remaining_cents` null when none; both figures are signed and unclamped (cross-midnight reversal makes `used` negative) — `ledger.py:44-65`
- §3.9 (reversal) — insert — ambiguity — credit row copies `approval_tier`/`honored_price_cents` from the claim but names the reversing caller as approver — `claims.py:291-303`
- §3.9 (reversal) — insert — ambiguity — only an `APPROVED` source order is suspended; an `EXECUTED` one stays executed and the product keeps the matched price — `claims.py:236-243`
- §3.10 (create) — insert — ambiguity — `window_end` at or before `window_start` → rank-5 `ERR_INVALID_REQUEST` — `label_batches.py:30-31`
- §3.10 (capacity) — insert — ambiguity — capacity always compared against *today's* usage regardless of the new batch's date, and a batch whose `window_start` is not today contributes nothing thereafter — `label_batches.py:45`, `ledger.py:18-30`
- §3.10 (selection) — revise — ambiguity — third tie-break by ascending batch creation sequence — `cascades.py:71`
- §3.10 (advance) — insert — ambiguity — `to_status` accepts `PRINTING`/`COMPLETED` only (`ERR_INVALID_ENUM_VALUE` otherwise); completion has no timing precondition; `queued_order_ids` and `label_batch_id` survive completion — `label_batches.py:16,71,84-88`, `cascades.py:223-235`
- §3.10 (cancel) — insert — ambiguity — `reserved_item_count` is left stored as-is; `item_count` reads 0 only because a `CANCELLED` batch contributes nothing — `ledger.py:11-15`
- §4 table (`/label-batches/{id}/advance`) — revise — **mismatch** — "completion releases the queued orders' signage" → completion marks them `PRINTED` without moving order status — `cascades.py:223-235`
- §4 table (`/label-batches/{id}/cancel`) — revise — **mismatch** — "a batch that has not started printing" → a batch that is `SCHEDULED` or already `PRINTING` — `label_batches.py:103-107`

On pass B's flag: §3.8's policy prose and §3.6's rule prose already state `max_match_discount_pct`/`max_change_pct` as "strictly greater than 0 and at most 1", matching `as_ratio(min_exclusive=0, max_inclusive=1)` at `policies.py:45-47`. No local correction needed.

### Final pipeline state

`find implementation -name '*.py' -newer implementation/results.8.json` returns nothing — no implementation file was touched after the green sweep, so the recorded 8/8 × 110/110 result still describes the code as it now stands. Step 9 edited only `PRD_COMPLETED.md`. Pipeline complete.
