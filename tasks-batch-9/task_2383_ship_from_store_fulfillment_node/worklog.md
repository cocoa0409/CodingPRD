# Worklog — task_2383_ship_from_store_fulfillment_node

## Step 1: Create task directory — 2026-09-02T05:30:48.389Z

Created `tasks/task_2383_ship_from_store_fulfillment_node/` and `tasks/task_2383_ship_from_store_fulfillment_node/workspace/` (pre-allocated task name used verbatim; no index scan performed).

## Step 2: Generate scaffold — 2026-09-02T08:39:43.272Z

All three artifacts are complete and lint-clean.

**Files** (all in `/home/ubuntu/github/CodingPRD/tasks/task_2383_ship_from_store_fulfillment_node/`):
- `SCAFFOLD.yaml` — §1.0–§1.7, no design keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`

**Domain** (`/fulfillment-network`, archetype quota_allocation + workflow_orchestration, role_model peer_roles, consistency immediate):
- **13 entities**: Store, Sku, StoreInventory, PackagingSupply, CarrierPickup, CustomerOrder, OrderLine, RoutingRun, RoutingCandidate, FulfillmentAssignment, AssignmentLine, NodePerformanceWindow, CustomerNotification
- **51 endpoints**, **52 error ids**, **35 validations** on a pinned priority ladder (1 auth → 50 cost guardrail), **6 state machines** (branching), **3 concurrency rules** (ERR_STALE_ORDER/PICKUP/INVENTORY_VERSION, all 412), **15 calculations** (eligibility weighted_scoring, ATP threshold, dual-variant assignment cost, routing score, waterfall node selection with split-minimization restriction, tiered network fee, window metrics + node_action, routing-status projection, pick deadline, concurrent labour interval merge, pickup buffer interval merge, 4 reconciliation invariants), **4 roles** (NetworkPlanner, StoreAssociate as entity_backed:Store, CarrierCoordinator, CustomerCare)

**Design instance counts**:
- §1.8: 9 rules / **29 instances** (dual_variant_calc 3, combinatorial_formula 3, non_linear_state_machine 4, transitive_cascade 2, priority_pair_validation_conflict 4, boundary_precision_check 4, cross_entity_state_dependency 3, resource_temporal_overlap 2, compensating_invariant 4)
- §1.9: 9 sections / **77 instances** — entities 12, state_machines 14, calculations 14, validations 9, endpoints 7, errors 6, rbac 7, cross_cutting_complexity_layers 7, consistency_model 1. Of these, **57 carry full recipes** and **20 are `excluded_because` stubs** citing a §1.8 instance as `rule_id / name`.

**Verification**: all 52 error ids are triggerable somewhere in §1.8/§1.9 (checked programmatically); every claim_type comes from the claim-extraction guide's tables (plus the scaffold's own declared complexity-layer names); every declared calculation algorithm has a matching calculations claim; instance names are unique across the §1.8 ∪ §1.9 union; every numeric assert was pre-computed with a Decimal calculator (`/tmp/sfs/calc.py`, `calc2.py`). `scaffold_lint.py` over the task dir: `VERDICT: clean lint` — 1375 calls scanned, 29 §1.8 + 57 §1.9 instances, all FKs reverse-reachable.

## Step 3: Copy shared files — 2026-09-02T08:39:43.272Z

Copied `INSTRUCTION.md` to `tasks/task_2383_ship_from_store_fulfillment_node/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-02T08:57:57.805Z

PRD generated and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2383_ship_from_store_fulfillment_node/workspace/PRD.md` — 12,857 words, 446 lines. Structure: §1 Introduction; §2.1–§2.11 (Access Control, verbatim Response Structure, Pagination, Collection Reads and Reverse Navigation, Common Resource Properties, Logical Clock/Cutoffs, Money and Rounding, Stale-Version Protection, Conserved Quantities, Node Posture and Epochs, Rejection Precedence); §3.1–§3.9 (network setup, order intake, node scoring, routing waterfall, in-store execution, carrier pickups and tendering, failure handling and notifications, cost accounting, operations run); §4 endpoint table; §5 error catalogue. Ends at §5 with no audit footer. `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, sibling task dirs and `worklog.md` were never opened or written.

**Field coverage check:**
- entities[].fields: 132 required, 132 present, 0 missing
- endpoints[].request_body: 46 required, 46 present, 0 missing
- endpoints[].query_params: 29 required, 29 present, 0 missing
- path parameters: 13 required, 13 present, 0 missing
- Status: PASS

**Rule coverage check:**
- validations[] with priority: 35 checked, 35 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + `expected_order_version`/`expected_pickup_version`/`expected_inventory_version` + error_id all named), 0 missing
- state_machines[].transitions: 34 checked, 34 fully expressed, 0 missing
- calculations[]: 15 checked, 15 fully expressed, 0 missing
- validations[] conditions: 52 distinct error_ids checked, 52 matchable in prose, 0 missing
- endpoints[].side_effects / applies_to: 78 bullets checked, 78 expressed, 0 missing
- entities[].fields[] structured content: 132 checked, 132 reconstructible from prose, 0 missing
- sibling-branch symmetry: 11 groups checked, 11 with equal prose density, 0 asymmetric
- Status: PASS

**Path purity check (§3 only):**
- backtick tokens scanned: 1029
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
- plain-text (non-backtick) path or method+path mentions: 0
- Status: PASS

**Notes worth flagging**

- §4 table matches the scaffold exactly: 51 rows, no missing/extra method+path pairs, all authorized-role cells agree ("Any" used only where all four roles are listed). §5 has 52 rows with zero HTTP-status mismatches and no extras. The scaffold's own header comment claiming "50 endpoints / 38 error codes" is stale — the mechanical counts are 51 and 52.
- Four constants are expressed as lossless unit/percentage conversions rather than raw numerals, deliberately: 480 minutes as "eight staffed hours", 300 minutes as "five hours" (with the 240-minute span given as "four-hour span"), 240.00 minutes and PICK_SLA 240 as "four hours", and the fee tiers 0.06/0.045/0.03 as "6.0/4.5/3.0 percent". Constant *names* (`MAX_SPLITS_PER_ORDER`, `PICK_SLA_MINUTES`, `DC_BASE_CENTS_BY_ZONE`, `DC_HANDLING_CENTS_PER_UNIT`) are not quoted, but their values and semantics are ("three-split ceiling", the per-zone DC table, "120 cents multiplied by `total_units`").
- Second pass caught and fixed six precedence statements whose narrative order contradicted the pinned validation priorities: adjustment safety-stock (20) before below-reserved (21); scope violation (6) before assignment state (10) on accept/pick/pack/reject; and on ship, pickup state (15) and cutoff/window/capacity (30/32/41) before pickup-store mismatch (47). Also added the missing state gate for pickup cancel (15 before 49) and made explicit that reject is deliberately not gated on `node_status`.
- Deliberately hard-to-infer items are stated but not worked as examples: per-line rounding before summation in shipping cost, the fee tier keyed only on the pre-fee subtotal, split minimization overriding pure `routing_score` rank, the `store.created_at` (never `store.id`) final tiebreak, empty windows being inert for both posture and `consecutive_breach_windows`, `labor_minutes_reserved` never re-priced on a short pick, step-6 reroutes carrying an empty `excluded_store_ids`, deactivation reroutes deferred so replacements land in the new epoch, and `PARTIALLY_SHIPPED → CANCELLED` being unreachable.

## Step 5: Generate unit tests — 2026-09-02T09:42:35.132Z

Complete. Test infrastructure and suite for task 2383 are generated, audited, and clean.

## Output

**`test_helpers/`** (8 modules) — `types.py` (4 roles + 22 enum classes + TypedDicts for all 13 entities), `api_errors.py` (55 error ids with HTTP statuses registered at import), `api_client.py` (50 endpoint methods under `/fulfillment-network`), `constants.py` (every named threshold/weight/tier), `factories.py` (S1–S9 node presets, SKU presets, payload builders), `test_users.py` (node-backed StoreAssociate identity builder), `assertions.py` (per-entity shape checks + the 4 conserved-quantity checkers), `fixtures.py` (single-call wrappers + 10 composite world builders).

**`test_suite/`** — `conftest.py` + 17 test modules, **216 test functions**, all collected by pytest:

| queue B (breadth) | | queue A (depth) | |
|---|---|---|---|
| `test_01_network_records` | 20 | `test_10_dual_variant_costing` | 6 |
| `test_02_workflow_transitions` | 12 | `test_11_cost_formula_composition` | 10 |
| `test_03_costing_and_scoring` | 6 | `test_12_lifecycle_state_paths` | 12 |
| `test_04_request_validation` | 16 | `test_13_reroute_cascades` | 7 |
| `test_05_endpoint_actions` | 12 | `test_14_refusal_precedence` | 8 |
| `test_06_error_catalogue` | 35 | `test_15_threshold_boundaries` | 9 |
| `test_07_role_access` | 25 | `test_16_cross_entity_gates` | 6 |
| `test_08_concurrency_and_visibility` | 12 | `test_17_temporal_overlap` | 8 |
| | | `test_18_conserved_quantities` | 12 |

## Audit results (scripted, zero findings)

- **Coverage: 86/86 non-stub instances.** All 29 difficulty instances have ≥2 tests (none under-covered, none skipped); all 57 non-stub corner instances have ≥1. No test is tagged to any of the 20 `excluded_because` stubs.
- **Tagging:** every test carries exactly one `Design:` line; every tag resolves to a real `name:` in the source index. Zero untagged, zero dual-tagged, zero dangling.
- **Citations:** every test docstring opens with `PRD §X.Y: "…"`; every quotation was machine-verified as a literal substring of `workspace/PRD.md`. All full sentences, no fragments.
- No `skip`/`skipif`/`xfail` anywhere; no mocking; no reference to the implementation directory or any sibling task; the words "scaffold"/"design index"/"Table N" appear nowhere in generated code (I fixed one stale "network scaffolding" comment in `fixtures.py`).
- Everything compiles; `test_helpers` imports cleanly; `pycache` artifacts removed. Nothing outside `test_helpers/` and `test_suite/` was created or touched, and `worklog.md` was not written.

## Key findings worth relaying

1. **Design-index defect — `reject_reason_code: "NO_STAFF"`.** Used 7× in the difficulty index but not a member of the PRD's enum (`NO_STOCK_ON_FLOOR | LABOR_UNAVAILABLE | DAMAGED_UNITS | STORE_CLOSED`). Left as-is, every affected recipe would have collapsed at setup. Substituted `LABOR_UNAVAILABLE` throughout (`test_12`, `test_13`).
2. **Design-index defect — `routing_status: "COVERED"`** in the consistency-model instance is not a member of the declared enum; the PRD uniquely derives `ROUTED` there, which is what is asserted.
3. **Design-index defect — contradictory inventory triple** in `routing_run_flips_at_available_to_promise_exactly_zero`: the recipe asserts ATP 1, reserved 1 and safety 4 on the same row, which the PRD's own formula makes impossible. Split into a pre-commit ATP-1 assertion and a post-commit ATP-0 assertion.
4. **Two genuine PRD ambiguities found and respected** (assertions dropped rather than guessed): `units_committed_epoch` after a short pick is defined twice in mutually inconsistent ways (sum-over-assignments vs. decrement-by-shortfall), and whether `review_score` is computed before or after the deactivation cascade is not pinned. Also dropped were two prose-only claims about *absent* HTTP methods, which have no PRD-pinned observable.
5. **All four precedence pairs in `test_14` were emitted as real conflict tests** — the PRD's refusal-order section pins each one explicitly, so no downgrades were needed. Same for both precedence instances in `test_04` and the ops-run ordering in `test_05`.
6. Systematic care taken on two recurring hazards: timestamp comparisons that the PRD only pins to second precision are matched on a second-truncated prefix rather than exact string, and cost/score literals belonging to formula rules were deliberately not asserted inside gate/boundary tests where they would need an unrelated citation chain.

## Step 6: Generate implementation — 2026-09-02T09:42:35.132Z

The implementation is complete and verified end-to-end.

## What was built

`/home/ubuntu/github/CodingPRD/tasks/task_2383_ship_from_store_fulfillment_node/workspace/implementation/` — Python 3 + Flask, ~3,100 lines across 22 modules, in-memory only, empty on every boot.

- **`start.sh`** — guarded `pip install` (only when Flask is missing, to avoid boot contention under `--isolation per-test-server`) then `exec python3 app.py`, binding `0.0.0.0:$PORT` (default 10000).
- **`app.py`** — blueprint registration, `before_request` capturing the pre-request derived-field projection (PRD 2.5: a derived-field change is itself a mutation), `ApiError`/404/405/HTTPException handlers all emitting the standard error envelope.
- **Infrastructure**: `util.py` (Decimal + ROUND_HALF_UP, ceil/floor helpers, ISO with 3 fractional digits), `constants.py`, `errors.py` (full catalog with pinned HTTP statuses), `clock.py` (logical clock starting `2026-08-01T00:00:00Z`), `response.py`, `middleware.py` (auth + typed body/query getters), `db.py` (13 kinds, deepcopy snapshot/restore).
- **Services**: `costs.py`, `derive.py` (recompute + version reconciliation), `assignments.py`, `routing.py` (waterfall, split minimisation, supersede step on every COMMIT run), `notifications.py` (pinned first-match type rule), `opsrun.py` (the seven pinned ops-run steps).
- **Routes**: 51 endpoints across `nodes.py`, `pickups.py`, `orders.py`, `routing.py`, `execution.py`, `ops.py`. GETs use a read-only `show()` helper so a read never recomputes or bumps a version.

## Verification (5 live scenarios against a real `start.sh` boot, 0 unexpected results)

1. Happy path: store/SKU/inventory/packaging → order → PROVISIONAL then COMMIT run → accept/pick/pack/ship → pickup close/depart → ops-run twice, plus 12 error-precedence probes (403 role vs 403 scope vs 404 path, 409 state, 412 OCC, 422 arithmetic/temporal).
2. Governance: two consecutive breached windows → `PROBATION` → `DEACTIVATED` (`deactivated_at_epoch` set, live assignments cascaded), stranded units at `MAX_REROUTE_ATTEMPTS` → `routing_status=UNROUTABLE` with `dc_fallback_units=3`, then reactivate (409 on a non-deactivated node).
3. Fiscal guardrail: `projected_cost_index_bps=938822` → `ERR_COST_INDEX_GUARDRAIL` 422 with the snapshot/restore proven clean (RoutingRun count and assignment count unchanged), then `override_cost_guardrail:true` → 201 with `guardrail_overridden=true`; also `ERR_ORDER_LINES_LOCKED`, `ERR_NO_ROUTABLE_LINES`, `ERR_STALE_ORDER_VERSION`.
4. Split routing: 8 units across nodes with 2 ATP each → `split_count=3` capped at `MAX_SPLITS_PER_ORDER`, remaining 2 units → `DC_FALLBACK` notification; pickup capacity, `ERR_PICKUP_STORE_MISMATCH`, `ERR_PICKUP_HAS_PARCELS`, window reuse after cancel, inventory adjustment errors.
5. Labour cap: `floor(staffed * 0.5)` with the half-open `[accepted_at, pick_deadline_utc)` overlap set — 422 at 14 > 10, still 422 while `PICKED`, and 200 once the first assignment reaches `PACKED` (PACKED correctly excluded from the pick floor); routing independently marks the node `LABOR_EXHAUSTED` at 21 > 20.

## Spec ambiguities resolved (documented in code comments)

- The supersede step runs on **every** COMMIT run, not only reroutes (scaffold 1564 + PRD).
- Immediate reroute runs (reject / short-pick / assignment cancel) do **not** strand open units at `MAX_REROUTE_ATTEMPTS`; only ops-run step 6 strands.
- Assignment cancel with `reroute:false` yields `CANCELLATION_PARTIAL`; `CANCELLATION_FULL` is reserved for order cancels per the PRD's pinned first-match rule.
- Pick validation order follows the validations table (44 arithmetic → 45 zero-pick → 48 line mismatch), consistent with PRD 2.11's capacity-before-referential banding; `line_picks` may omit lines (they pick 0), matching validation 44's "at most once".
- A PROVISIONAL run does move `routing_status` off `UNROUTED`, which is what locks order lines.
- `ERR_NO_ROUTABLE_LINES` is checked before the supersede step, so a fully-covered order cannot be torn down by a planner COMMIT run.

## Step 7: Run tests and iterate — 2026-09-02T13:55:00.000Z

All 8 rounds of the confirmation sweep are green. Exit criterion met.

## Summary

**Iterations run: 2** (two full 8-round parallel sweeps, no code changes between them)

**Iteration 1** (host load avg 40–57, ~200 concurrent runner processes from other pipelines): all 8 rounds reported the same `total == 216` (so no truncation/reaping), with 5 failing test instances across rounds 1, 2 and 5:
- `test_store_associate_reads_another_nodes_rows_because_reads_are_network_wide` (rounds 1 and 5) — `RemoteDisconnected`
- `test_ship_into_full_pickup_inside_window_reports_capacity_exceeded` (round 2) — `ConnectionResetError(104)`
- `test_commit_run_retried_with_the_fresh_order_version_covers_both_lines` (round 5) — `ConnectionResetError(104)`
- `test_fill_rate_below_the_floor_raises_the_breach_and_puts_the_node_on_probation` (round 5) — `ConnectionResetError(104)`

Every one was a `requests.exceptions.ConnectionError` at transport level — not a single assertion failure, 4xx/error_id mismatch, or fixture setup error anywhere in 1,728 test executions. Rounds 3, 4, 6, 7, 8 were 216/216. All four affected endpoints (a network-wide read, a pickup-capacity ship refusal, a re-commit routing run, an ops-run window breach) contain no wall-clock timing logic, matching the stated load-induced signature exactly, so per protocol no file was edited and no test deleted; the sweep was re-run to confirm.

**Iteration 2** (host load avg dropped to ~13–37; sweep finished in ~9 min instead of ~18): **all 8 rounds 216 passed / 216 total, 0 failed, 0 errors, 0 skipped**, per-round duration 511–521 s. Zero `FAILED` lines in `workspace/sweep.log`. This confirms the iteration-1 failures were host-load artefacts.

**Tests deleted: none.** No test reached STEP 1a/1b — no failure was ever an assertion or coverage question, so no PRD-silence or non-unique-derivability category applies.

**Fixes to `test_helpers/`: none.** No setup failures occurred in either sweep (all composite builders in `test_helpers/fixtures.py` and the identity builder in `test_helpers/test_users.py` produced PRD-consistent preconditions throughout).

**Fixes to `workspace/implementation/`: none.** No implementation file was modified in this session; the app remains in-memory-only (`db.py` dicts, no persistence, no seeding).

Incidental observation, not acted on: the runner's `FAILED` log lines name a test adjacent to the one recorded in `results.$i.json` (counts match exactly, names are off by one within the same file/class) — an off-by-one in `/home/ubuntu/github/CodingPRD/prd-bench-local-runner/src/prd_bench_local_runner/pytest_plugin.py`, which is locally modified. The `error_message` payloads in the results JSON are the reliable evidence; the log names are not.

## Step 8: Finalize PRD — SKIPPED — 2026-09-02T13:55:00.000Z

Skip condition met. Step 7 applied 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes across both sweeps — the only failures ever observed were transport-level `ConnectionError`/`RemoteDisconnected` artefacts of host CPU contention, which produced no PRD-silence or PRD-mismatch signal. `<step_7_diff>` would therefore be empty, leaving Step 8 no site to patch: `PRD.md` already determined every behaviour the tests exercised. `PRD_FINALIZED.md` is intentionally absent, so Step 9 starts from `PRD.md`.

## Step 9: Complete PRD — 2026-09-02T14:12:00.000Z

`PRD_COMPLETED.md` is written and complete.

**File:** `workspace/PRD_COMPLETED.md`

**Counts**
- Source: `workspace/PRD.md` — 446 lines, 92,310 chars (no `PRD_FINALIZED.md` present, as expected since Step 8 was skipped)
- Output: `workspace/PRD_COMPLETED.md` — 447 lines, 101,365 chars; char-delta **+9,055**, line-delta **+1** (one new bullet inside the existing §2.2 bullet list; no new sections, no new paragraphs)
- **33 changes** across **31 diff hunks**: **24 ambiguity-pins**, **9 mismatch-revisions** (23 inserts, 10 revises)

**Changes**

- §2.2 — insert — ambiguity — `api_request_timestamp` is read from the logical clock, not wall-clock — `implementation/response.py:22`
- §2.2 — insert — ambiguity — pagination `meta` fields appear only on §2.3 list endpoints; the ops run's `array` envelope omits them — `implementation/response.py:64`, `routes/ops.py:30`
- §2.2 — insert — ambiguity — three envelope-level cases: unknown path → `ERR_NOT_FOUND` 404, unsupported method → `ERR_NOT_FOUND` 405, unparseable/non-object body → `ERR_INVALID_REQUEST` 400; absent/empty body read as `{}` — `app.py:38-53`, `middleware.py:22-34`
- §2.3 — insert — ambiguity — identical `created_at` ties are broken by write order, making every "ascending `created_at`" rule a stable total order on creation sequence — `db.py:54,69`
- §2.4 — insert — ambiguity — filter-value validation (bad enum/int/bool → `ERR_INVALID_REQUEST`), FK filters exact-match with an empty page rather than 404, empty string = absent, undeclared params ignored — `middleware.py:154-190`
- §2.5 — insert — ambiguity — a routing run is written once so its `version` stays at 1 forever; no read-only request ever increments a `version` — `db.py:57-59`, `routes/routing.py:44-61`
- §2.10 — revise — mismatch — dropped `pick` from the `ERR_STORE_NODE_DEACTIVATED` gate list; pick and reject are ungated — `routes/execution.py:196-197`
- §2.11 — insert — ambiguity — `ERR_PICK_UNITS_INVALID` precedes `ERR_ZERO_PICK_NOT_ALLOWED` inside band 9 — `routes/execution.py:208-211`
- §3.1 — insert — ambiguity — `region_code` is a required non-empty string matched exactly by its filter — `routes/nodes.py:34`
- §3.1 — insert — ambiguity — the full empty-window metric seed for every newly opened window — `services/derive.py:84-107`
- §3.1 — insert — ambiguity — node PATCH fields are all optional, an empty body is a no-op, `version` increments regardless — `routes/nodes.py:91-118`
- §3.1 — insert — ambiguity — restock `added_units` must be at least 1 — `routes/nodes.py:303`
- §3.2 — revise — mismatch — `customer_ref`/`promised_ship_by_utc` are stored on the order and appear on no notification — `services/notifications.py:28-39`
- §3.2 — revise — ambiguity — pinned first-match `line_status` precedence, shipped beating cancelled — `services/derive.py:113-127`
- §3.2 — insert — ambiguity — order cancel accepts any of the seven reason codes and persists none — `routes/orders.py:132`
- §3.2 — revise — mismatch — the full-cancel notification is typed by §3.7's rule (`CANCELLATION_PARTIAL` when cancelled < `total_units`), `units_affected` = released + still-open units — `routes/orders.py:153-157`
- §3.3 — insert — ambiguity — score and basis are pure derivations re-derived for every node on every mutating request, `DEACTIVATED` included — `services/derive.py:331-335`
- §3.3 — revise — mismatch — `units_committed_epoch` subtracts the assignment lines' `units_cancelled`, and is 0 with no open window — `services/derive.py:306-318`
- §3.4 — insert — ambiguity — a planner-initiated run always carries an empty `excluded_store_ids` — `routes/routing.py:44`
- §3.4 — insert — ambiguity — ineligible candidates' zero-valued evaluation fields; unselected eligible candidates keep `selected` false / `assigned_units` 0 — `services/routing.py:62-80`
- §3.4 — insert — ambiguity — `PROVISIONAL` always ends `EVALUATED` and never triggers DC fallback, but it persists a run row, so it re-derives `routing_status` (an `UNROUTED` order lands on `UNROUTABLE`), bumps the order's `version` and freezes its demand lines — `services/routing.py:274-279`, `services/derive.py:378-388`
- §3.4 — insert — ambiguity — projection inclusion basis and the self-counting reroute overhead — `services/routing.py:260-272`
- §3.4 — insert — ambiguity — guardrail refusal rolls the whole request back; `override_cost_guardrail` defaults false — `routes/routing.py:42-51`
- §3.5 — insert — ambiguity — accept on a `CANCELLED` order returns `ERR_ORDER_NOT_ROUTABLE` — `routes/execution.py:114-115`
- §3.5 — revise — mismatch — an omitted `line_picks` entry is a zero pick, not a refusal — `routes/execution.py:219-222`
- §3.5 — revise — mismatch — pack requires `ELIGIBLE`/`PROBATION` posture, checked between the state and cutoff gates — `routes/execution.py:257`
- §3.6 — revise — mismatch — every open-window metric field except `node_action` is refreshed, on every mutating request — `services/derive.py:133-188`, `services/derive.py:326-329`
- §3.7 — revise — mismatch — `channel` is always `EMAIL`, per-event `units_affected`, exact `body_summary` template — `services/notifications.py:28-39`
- §3.8 — insert — ambiguity — `network_fee_rate` is reported as 0.06 / 0.045 / 0.03 — `services/costs.py:79`
- §3.9 — insert — ambiguity — the ops run answers with an `array` envelope carrying no pagination meta — `routes/ops.py:30`
- §3.9 — insert — ambiguity — `review_score` is written for every node owning an open window — `services/opsrun.py:45-47`
- §3.9 — insert — ambiguity — step 6 strands open units at the attempt limit; retry-notification typing — `services/opsrun.py:108-124`
- §3.9 — revise — mismatch — step 7 rescores all nodes including `DEACTIVATED`; basis is derived from whether the node owns a closed window — `services/opsrun.py:126-132`, `services/derive.py:331-335`

**Most consequential finding:** the single largest PRD silence was that a `PROVISIONAL` routing run is not side-effect-free — it persists a run row, which makes `derive.recompute_order`'s `if not runs: routing = "UNROUTED"` branch stop applying, so an `UNROUTED` order transitions to `UNROUTABLE` and its `version` increments (freezing further demand-line additions). This is now pinned inline in §3.4.
