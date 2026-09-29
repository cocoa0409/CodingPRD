# Worklog — task_2683_home_cook_meal_marketplace_cottage_food_compliance

## Step 1: Create task directory — 2026-09-04T05:56:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2683_home_cook_meal_marketplace_cottage_food_compliance/` and `workspace/` per the pre-assigned path. No index scan performed (index fixed at 2683 by the scenario number; other pipelines run concurrently on this host).

## Step 2: Generate scaffold — 2026-09-04T07:58:00.000Z

All three scaffold artifacts are complete and pass every check.

## Files

| File | Lines | Bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 3136 | 164 KB |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2408 | 156 KB |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 6114 | 397 KB |

Each parses under PyYAML; the two design files carry exactly one top-level key each (`scaffold_difficulty_design`, `scaffold_corner_design`), and `SCAFFOLD.yaml` carries neither.

## Scaffold content (1.0-1.7)

- 11 entities (StatePolicy, Cook, OnboardingDocument, MenuItem, ProductionWindow, DeliveryZone, PickupHub, Order, SafetyIncident, RefundEvent, PayoutStatement), flat topology
- 11 state machines (parallel shape: Cook onboarding x compliance-standing, Order fulfillment x payment), 2 1.2.1 concurrency rules (`expected_cook_version` on `POST /onboarding-documents`, `expected_production_window_version` on `POST /payout-statements`), 2 compensating invariants
- 9 calculations (order charge breakdown, tiered commission, cottage-revenue cap, cook safety score with decay, cold-chain surcharge/feasibility, hub selector, refund waterfall, capacity, payout net), 2 of them dual-variant
- 50 priority-ordered validations, 65 error ids, 48 endpoints (25 POST / 23 GET; create + action + read only), 7 roles with segregation of duties

## Design coverage

- 1.8: 9 rules / 21 instances (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant)
- 1.9: 84 instances across all nine taxonomy sections — entities 11, state_machines 16, calculations 19, validations 20, endpoints 6, errors 2, rbac 4, cross_cutting_complexity_layers 5, consistency_model 1; 28 of them are `excluded_because` stubs deferring to a named 1.8 instance

## Audit results

- `scaffold_lint.py`: `VERDICT: clean lint — all 1.8/1.9 calls conform to 1.5 and all 1.1 FKs have reverse-reachability in 1.5.` (1387 calls scanned across 21 + 56 recipe-bearing instances)
- Forbidden concurrency vocabulary: 0 hits in all three files
- Placeholder closure: 0 unbound `${var}` in any `call`, `payload`, or `as_user_id` across both design files. This required inserting explicit `setup_api_calls` prefix chains into 25 1.9 instances that previously inherited ids only through prose; each prefix replays the canonical StatePolicy -> clock -> cook -> 2 onboarding docs (with OCC versions) -> 2 reviews -> activation -> menu create/submit/approve -> window -> zone chain, truncated at the depth that instance needs and parameterized per instance (price 610 / 50000 / 900, state TX for the cap-warning case, plus full order-to-DELIVERED/CLOSED and refund+statement tails for the seven "run to completion" worlds)
- Instance names unique across both files (105 total, 0 duplicates); every `excluded_because.difficulty_instance` resolves to a real 1.8 instance name; no capture name is bound twice inside any instance
- All 65 error ids are triggered by at least one recipe (`errors never mentioned: []`)

## Step 3: Copy shared files — 2026-09-04T07:59:00.000Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes). Task dir survived Step 2 intact (worklog.md and workspace/ both present).

## Step 4: Generate PRD — 2026-09-04T08:15:00.000Z

Orchestrator truncation check: `wc -l` = 501, `tail -25` ends on the final complete error-catalogue table row (`| ERR_NO_ELIGIBLE_ORDERS | 422 |`) — a real section boundary, not mid-sentence. 29 headings. No regeneration needed.

Subagent summary (verbatim):

Done. PRD.md is complete and verified.

**File:** `workspace/PRD.md` — **501 lines, 14,558 words**, built entirely with chunked heredoc appends. Ends cleanly on the final error-catalogue row (`| ERR_NO_ELIGIBLE_ORDERS | 422 |`), no audit footer, no contract-report block in the file.

**Section list**
- `# Home-Cook Meal Marketplace & Cottage-Food Compliance API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 RBAC / 2.2 API Response Structure (byte-identical to `section-2.2-response-structure.md`, verified by exact substring match) / 2.3 Pagination / 2.4 Resource Identity, Timestamps and Versioning / 2.5 The Logical Clock / 2.6 Optimistic Concurrency on Superseding Writes / 2.7 Parallel Status Dimensions / 2.8 Money, Meals and Rounding Discipline / 2.9 Cascade Discipline / 2.10 Reference Resolution and Path Semantics / 2.11 The Validation Precedence Ladder / 2.12 Conserved Quantities
- `## 3. Business Logic & Workflows` — 3.1 Registering a State and Onboarding a Home Cook / 3.2 Publishing a Dish: Allergen, Shelf-Life and Labelling Review / 3.3 Weekly Production Windows, Cutoffs and Effective Capacity / 3.4 The Delivery Network: Zones, Hubs and Slot Accounting / 3.5 Order Placement: Charges, Commission Tiers and the Cottage-Food Cap / 3.6 Routing, Hub Selection, Handoff and Revenue Recognition / 3.7 Food-Safety Incidents, the Safety Score and Cook Standing / 3.8 Cook Payouts, the Refund Waterfall and Settlement / 3.9 Discovery Through Filtered Reads
- `## 4. Endpoint Definitions` (4 columns, 48 rows)
- `## 5. Error Code Catalogue` (2 columns, 65 rows)

**Coverage confirmation (machine-checked against SCAFFOLD.yaml)**
- 11 entities, 122 declared field names — all present.
- 10 state-machine dimensions, 70 transitions — every from/to pair co-located in prose.
- 42 distinct state literals — all present.
- 9 calculation blocks (13 entries counting the 4 variant sub-blocks) — all expressed, including both `cook_safety_score` variants and both `cook_payout_net` bases.
- 2 concurrency rules, 2 compensating invariants, 2 named cascades.
- 50 validations, priority 1-50, in order, in 2.11.
- 65 error ids — all in the 5 table **and** all referenced in 2/3 prose (0 table-only orphans).
- 48 endpoints — method+path set equality with the scaffold and **exact role-set match on all 48**; the 4 status-code intro rule (201 creation / 200 otherwise) matches every scaffold `code` with zero exceptions.
- 25 constants present as business values (names deliberately not used as symbols), including the two the scaffold only mentions inline: the two-round revision ceiling and the 1-20 quantity band.

**Field coverage check:** entities[].fields 122/122; endpoints[].request_body 81/81; endpoints[].query_params 81/81. Status: PASS

**Rule coverage check:** validations 50/50; OCC rejections 2/2; transitions 70/70; calculations 9/9; validation conditions 50/50; side_effects 48/48; entity fields 122/122; sibling-branch symmetry 10/10. Status: PASS

**Path purity check (3 only):** 1045 backtick tokens scanned; 0 starting with `/`; 0 bare HTTP-method tokens; 0 method+path tokens. Status: PASS

**Scaffold ambiguities resolved by judgment** (worth a reviewer's eye): the document-supersession set (wrote the six-state superset from the Cook side-effect, with only `SUPERSEDED` left alone); `routing_mode` written at routing rather than placement (three sources against one); order cancellation limited to `PLACED`/`ROUTED` per the state machine, despite the endpoint description mentioning `IN_PRODUCTION`; and the `WARN` standing action included from the endpoint's side-effects even though it is absent from the `compliance_standing` transition table. Also note the scaffold's `difficulty_level` string says "7 calculations" while there are 9 blocks — all 9 are documented.

Neither design yaml was opened, grepped, or referenced, and no sibling task directory was read.

---

## Step 7 — Unit test generation (Stage 1 complete)

`test_helpers/` written at the task root (9 files, 2,239 lines):

| file | lines | contents |
|---|---|---|
| `constants.py` | 98 | PRD numeric constants: commission tiers/rates, spoilage reserve pct, cold-chain surcharges, severity points, score bands, cap-warning threshold, enum tuples |
| `types.py` | 291 | `Role`, every status tuple, `TERMINAL_*` tuples, 13 `TypedDict`s over `CommonFields` |
| `api_errors.py` | 157 | `ApiErrorId` (67 codes), `HTTP_STATUS_CODES`, registers the map with the framework validator |
| `test_users.py` | 109 | operator-id constants, `TEST_USERS` header dict (13 keys), per-role header builders |
| `api_client.py` | 240 | `ApiClient(GenericApiClient)`, one method per endpoint, module singleton `api_client` |
| `factories.py` | 417 | one payload builder per write endpoint; all money emitted as ints |
| `assertions.py` | 305 | envelope/common-field checks, per-entity field asserters, formula recomputations, three-bucket and net-payout identities, capacity triple |
| `fixtures.py` | 632 | tiered composite setup: onboarding preamble (cert as `rev-1`, inspection as `rev-2`, menu approval as `rev-1` for SoD), menu/window/zone/hub builders, order place/route/advance chains, window-close capture chain, statement drafting with the mandatory window re-read, incident and refund chains |
| `__init__.py` | 40 | barrel re-export of the framework generics plus all local modules |

`test_suite/conftest.py` (87 lines): session-scoped `api` fixture plus one fixture per `TEST_USERS` key.

Verified by importing the package: client base URL resolves, error-status map registered, factories emit int cents, fixtures reachable through the barrel.

**Design-index reconciliation.** Difficulty index carries **19** instances across 9 rule_ids. Corner index carries **84** instances across 9 sections, of which **28** are `excluded_because` stubs, leaving **56** non-stub. All 28 stub cross-references resolve to real difficulty `rule_id / name` pairs — no dangling reference.

## Step 6: Generate implementation — 2026-09-04T09:05:00.000Z

Note: Steps 5 and 6 were launched as concurrent background agents. Isolation held — Step 6's agent was explicitly barred from reading test_helpers/ and test_suite/, and both dirs landed at the task root (not under workspace/), so no post-hoc move was needed.

Subagent summary (verbatim):

Implementation complete and verified.

## Files written — `workspace/implementation/`

| File | Lines | Role |
|---|---|---|
| `start.sh` | 8 | `exec python3 app.py`, guarded `pip install` (import-check), foreground, executable |
| `requirements.txt` | 1 | `flask>=2.0` |
| `app.py` | 66 | blueprint registration, `ApiError`/404/405/500 handlers, `0.0.0.0:$PORT` (default 10000), **no seeding** |
| `core.py` | 268 | logical clock (boot `2026-08-01T00:00:00Z`), `fmt_dt` (3 fractional digits + `Z`), Decimal money helpers, 65-code error catalog, in-memory `Store`, `new_row`/`touch`/`ordered`, envelope helpers |
| `auth.py` | 81 | seven roles incl. `Anonymous`, ladder rungs 1-4, `require_owner` (rung 8) |
| `validation.py` | 221 | enums, typed body getters (rung 5), pagination + filters |
| `calc.py` | 437 | the nine calculations |
| `services.py` | 223 | cascades, derived recomputation, onboarding/safety re-evaluation |
| `listing.py` | 24 | shared list pipeline |
| `routes_config.py` | 248 | state policies, clock, delivery zones, pickup hubs, consolidation |
| `routes_cooks.py` | 385 | registration, compliance summary, onboarding documents + review, onboarding decision, standing actions |
| `routes_menu.py` | 226 | menu items, submit, review (5 decisions) |
| `routes_windows.py` | 162 | production windows + advance |
| `routes_orders.py` | 264 | placement, route, advance, cancel |
| `routes_safety.py` | 161 | incident intake, triage, adjudicate |
| `routes_money.py` | 247 | payout statements (+advance), refund events |

Total 3022 lines. All 14 modules pass `python3 -m py_compile`.

## Endpoints: 48 / 48
Enumerated Flask's `url_map` and diffed it against the PRD 4 table (48 rows): **exact match, zero missing, zero extra** (only Flask's built-in `/static` beyond that).

## Calculations implemented (9)
Order pricing snapshot + 9% diner service fee; three-tier commission (0.225 / 0.185 / 0.150, inclusive-below/exclusive-at at 1,000,000 and 5,000,000 cents, read pre-order); window effective capacity + meal admission; cottage-cap projection (in-flight exposure) and the separately-bounded `cap_status` (exact rational 90% test on recognised revenue); cold-chain feasibility + per-meal surcharge (75 door / 40 hub); hub eligibility, ranking and closed +/-45-min buffered slot-collision test; decaying safety score (1.00 / 0.50 / 0.25 at 8 and 26 weeks, single half-up rounding of the total charge) with standing bands; payout statement (per-order commission rounding then sum; 0 / 10% / full withholding); three-bucket refund waterfall per fault party. Money is integer cents via `Decimal` + `ROUND_HALF_UP` throughout — no floats.

## Validation ladder
All 50 rungs implemented in global precedence order, with the deliberate PRD-driven readings recorded earlier (cap_status on `ytd_cottage_revenue_cents`; closed hub intervals vs half-open window overlap; both OCC fields mandatory so absence is rung 5; menu-approval standing/allergen-notes and document from-state reported under their rung-11/rung-15 codes; window-scoped payout incident blocker per 3.8). **All 65 PRD error codes are raised or mapped**, plus 3 infrastructural ones (`ERR_NOT_FOUND` 404, `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INTERNAL` 500).

## Smoke boot: PASS
`PORT=19737 bash start.sh` booted in ~1.5 s. Fresh-boot store confirmed empty (all 11 list endpoints returned `total_count: 0`). A 78-assertion end-to-end script drove the full lifecycle — policy -> anonymous cook self-registration -> two documents -> verify/pass -> activate -> menu item -> submit -> approve -> zone -> window -> order placement (subtotal 3600, fee 324, total 3924, rate 0.225, commission 810, earnings 2790) -> route -> clock advance -> window CUTOFF_PASSED/IN_PRODUCTION -> order IN_PRODUCTION/HANDED_OFF/DELIVERED (capture, `effective_year` 2026) -> SHARED refund (500/500/0, sums exactly to 1000) -> incident intake/triage/adjudicate -> window CLOSED -> statement draft (net 2790) -> blocked finalize -> finalize (refund auto-settles) -> PAID (`lifetime_paid` 2790) -> REVERSED (`lifetime_paid` back to 0) -> suspension cascade (item `DELISTED` / `COOK_SUSPENDED`). Result: **0 unexpected status codes, exit 0, zero server tracebacks.** Server was shut down by its specific pid/child pid on ports 19733-19737 only; no broad `pkill` was ever used, and post-kill probes returned `000`.

Four earlier smoke mismatches were all *the smoke script's* wrong expectations, not implementation bugs — verified against the PRD each time: `ERR_SOD_SAME_OFFICER` is 403 (not 422), anonymous callers must still send `X-User-Role: Anonymous` so a header-less request is correctly 401, `CUTOFF_PASSED` correctly needs the clock at/past `order_cutoff_at`, and `CLOSED` correctly needs it past `handoff_end_at`. One cleanup: dropped a stray `ERR_INVALID_REFUND_TRANSITION` entry from the status map since the PRD declares no such code.

## Step 7 — Unit test generation (Stage 2 complete)

`test_suite/` holds 16 test files, **189 tests**, 7,909 test lines plus an 87-line `conftest.py`.

| file | tests | lines | concern |
|---|---|---|---|
| `test_01_payout_statement_basis_and_commission.py` | 11 | 397 | recognition bases, per-order commission rounding, open-incident gate on finalisation |
| `test_02_conserved_quantities.py` | 6 | 275 | committed_meals and ytd_cottage_revenue_cents across a reversal |
| `test_03_capacity_admission_and_revenue_cap.py` | 7 | 305 | spoilage-reserve capacity check vs the annual cap at admission |
| `test_04_routing_and_hub_consolidation.py` | 7 | 429 | hot-handoff span boundary, hub slot conflicts, empty consolidation set |
| `test_05_parallel_status_dimensions.py` | 9 | 262 | cook and order two-dimensional status models, bounded revision cycle |
| `test_06_cascade_chains.py` | 8 | 299 | suspension cascade (depth 6) and window-close cascade (depth 4) |
| `test_07_validation_precedence_pairs.py` | 7 | 246 | which of two simultaneous violations the ladder reports |
| `test_08_cross_entity_gating_and_window_intervals.py` | 10 | 345 | preconditions read from a sibling entity; window interval overlap |
| `test_09_safety_score_and_standing_bands.py` | 7 | 235 | authoritative vs provisional score; standing-band boundaries |
| `test_10_version_guards_and_derived_field_visibility.py` | 8 | 433 | the two stale-version guards; same-response derived-field visibility |
| `test_11_entity_contracts.py` | 16 | 600 | required/default/computed/system fields, not-found identity, FK order |
| `test_12_state_machine_edges.py` | 18 | 812 | initial states, undeclared transitions, terminal lockout, clock gates |
| `test_13_calculation_edges.py` | 14 | 701 | charge breakdown, tier boundary, recognition, refund waterfall, constants |
| `test_14_validation_rules.py` | 24 | 1109 | uniqueness, conditional fields, range/interval limits, eligibility filters |
| `test_15_endpoint_contracts.py` | 15 | 812 | round trips, idempotency, action preconditions, computed projections |
| `test_16_authorization_and_error_catalogue.py` | 22 | 649 | header envelope, role allow-lists, ownership, segregation of duties |

**Coverage.** Every one of the **21** difficulty instances is translated (2-5 tests each) and every one of the **56** non-stub corner instances is translated (1-5 tests each). **Nothing skipped**: 77/77 in-scope instances covered, 0 gaps. No test targets an `excluded_because` stub.

**Audit passes run over the finished suite** (all clean):
- `python3 -m py_compile` on all 25 files, plus a real `import` of every test module and of the helper package.
- Every `PRD: "..."` quote is a byte-verbatim substring of `workspace/PRD.md` (189/189).
- Exactly one `Design:` line per test, always the final docstring line; every tag resolves to a real `rule_id`/`name` pair in the correct source index, and none points at a stub.
- Sequential `test_NN_` numbering inside every file; no classes; every file carries at least 5 tests.
- No banned vocabulary (`scaffold`, `Table N`, `§1.`, `corner design`, `difficulty design`) anywhere in the generated code.
- No `xfail`, `pytest.skip`, `TODO` or placeholder anywhere; no cents field compared against a quoted string.
- Every `fixtures.` / `factories.` / `assertions.` attribute referenced by a test exists on the module it is imported from.

**Design-recipe payloads corrected toward the PRD** (the PRD is the contract, so these were fixed rather than copied): allergen literals `MUSTARD` and `CELERY` are not among the nine allergens the PRD declares (replaced with declared members); incident category `PACKAGING_DEFECT` is not one of the five declared categories (replaced with `FOREIGN_OBJECT`); adjudication decision `UNSUBSTANTIATE` is not declared (`DISMISS` is the edge that reaches `UNSUBSTANTIATED`); menu-review decision literal `REVISION_REQUEST` written as the PRD's `REQUEST_REVISION`; a `SAFETY`-reason refund without `safety_incident_id` is not PRD-legal (recorded as `QUALITY` with the same fault party and amount).

**Sub-assertions dropped for want of a uniquely-deriving PRD sentence** (the parent instances remain covered): `cap_remaining_cents` exact values, because the PRD does not fix whether in-flight authorised exposure is subtracted; retention of `pickup_hub_id` after cancellation; and one branch of the document-supersession recipe that reused a spent cook version, where the stale-version guard would mask the intended code.

## Step 5: Generate unit tests — 2026-09-04T09:55:00.000Z

Orchestrator note on worklog hygiene: the Step 5 subagent appended two of its own entries to this file and mislabeled both as "Step 7" (lines 86 and 153) — they are in fact Step 5 stage-1 / stage-2 notes, and one of them is interleaved before the orchestrator's Step 6 entry because the two generators ran concurrently. Left in place per the append-only rule; read those two headings as "Step 5". The authoritative Step 5 record is this entry.

Verified at task root (not under workspace/): `test_helpers/` and `test_suite/` both present; `workspace/` contains only INSTRUCTION.md, PRD.md, implementation/. No stray worklog files.

Subagent summary (verbatim):

Test infrastructure and test suite are complete and audited.

## Deliverables

**`test_helpers/` — 9 files, 2,289 lines** (at the task root, not inside `workspace/`)

| file | lines | contents |
|---|---|---|
| `constants.py` | 98 | commission tiers/rates, spoilage-reserve pct, cold-chain surcharges, severity points, score bands, cap-warning threshold, enum tuples |
| `types.py` | 291 | `Role`, every status tuple, `TERMINAL_*` tuples, 13 TypedDicts over `CommonFields` |
| `api_errors.py` | 157 | `ApiErrorId` (67 codes), `HTTP_STATUS_CODES`, registers the map with the framework validator |
| `test_users.py` | 109 | operator-id constants, 13-key `TEST_USERS`, per-role header builders |
| `api_client.py` | 240 | `ApiClient(GenericApiClient)`, one method per endpoint, singleton `api_client` |
| `factories.py` | 417 | one payload builder per write endpoint; all money emitted as int cents |
| `assertions.py` | 305 | envelope/common-field checks, per-entity asserters, formula recomputation, three-bucket and net-payout identities |
| `fixtures.py` | 632 | tiered composite setup: onboarding preamble (cert by `rev-1`, inspection by `rev-2`, menu approval by `rev-1` for SoD), menu/window/zone/hub builders, order place/route/advance chains, window-close capture, statement drafting with the mandatory window re-read, incident and refund chains |
| `__init__.py` | 40 | barrel re-export of framework generics plus all local modules |

**`test_suite/` — `conftest.py` (87 lines) + 16 test files, 189 tests, 7,909 lines.** Files cluster by concern: payout/commission, conserved quantities, capacity+cap, routing/hubs, parallel status dimensions, cascades, precedence pairs, cross-entity gating, safety scoring, version guards, entity contracts, state-machine edges, calculations, validations, endpoints, authorization.

## Coverage

- **Queue A (difficulty): 21/21 instances translated, 2-5 tests each.** Note: the true instance count is **21**, not the 19 carried in earlier working notes — an earlier manual count was wrong; the set-based audit and `grep -c` both confirm 21, and all 21 are covered.
- **Queue B (corner): 56/56 non-stub instances translated, 1-5 tests each.** The 28 `excluded_because` stubs got no tests; all 28 of their `difficulty_instance` cross-references were verified to resolve to real `rule_id / name` pairs — no dangling reference.
- **Skipped instances: none.** 77/77 in-scope instances covered.

## Audit results (all clean)

`py_compile` on all 25 files plus a real `import` of every test module; 189/189 PRD quotes byte-verbatim in `PRD.md`; exactly one `Design:` line per test, always last in the docstring, every tag resolving to the correct source index and never to a stub; sequential numbering per file; no classes; >=5 tests per file; zero banned vocabulary; zero `xfail`/`skip`/`TODO`/placeholder; no cents field compared to a quoted string; every `fixtures.`/`factories.`/`assertions.` attribute referenced by a test exists.

## Two things worth a reviewer's eye

**Design-recipe payloads corrected toward the PRD** (PRD is the contract): allergen literals `MUSTARD`/`CELERY` are not among the nine declared allergens; incident category `PACKAGING_DEFECT` is not declared; adjudication decision `UNSUBSTANTIATE` is not declared (`DISMISS` is the edge to `UNSUBSTANTIATED`); `REVISION_REQUEST` written as `REQUEST_REVISION`; a `SAFETY`-reason refund without `safety_incident_id` is not PRD-legal.

**Sub-assertions dropped for want of a uniquely-deriving sentence** (parent instances still covered): exact `cap_remaining_cents` values (the PRD does not fix whether in-flight authorised exposure is subtracted), retention of `pickup_hub_id` after cancellation, and one document-supersession branch where the stale-version guard would mask the intended code.

Nothing under `workspace/implementation/` was read or touched.

## Step 7: Run tests and iterate — 2026-09-04T10:55:00.000Z

Orchestrator independent verification (not taken on the subagent's word, per prior pipeline experience where a Step 7 agent claimed a clean sweep with no artifacts on disk): all 8 `workspace/implementation/results.{1..8}.json` exist, each ~59.5 KB, all timestamped 09:38, and each parses to `passed=189 total=189 failed=0 errors=0 skipped=0`. Clean sweep confirmed.

Step 8 decision: NOT skipped. The skip condition requires 0 deletions AND 0 test_suite fixes AND 0 test_helpers fixes AND 0 implementation fixes; Step 7 applied 1 test_suite fix, so Step 8 runs. Note in advance that the single fix was a test-side field-name conflation (`status` vs `review_status`) with 0 implementation fixes, so Step 8 may legitimately find no PRD silence to patch — that is an acceptable outcome, not a failure.

Subagent summary (verbatim):

No stray sweep processes remain (the 84 count is other pipelines on this host). Clean sweep achieved.

## Summary

**Iterations run:** 2

**Baseline (iteration 1):** 188/189 in every one of the 8 parallel rounds — a single, fully deterministic failure (not flakiness), identical in all rounds:
`test_13_calculation_edges.py::test_14_recognised_revenue_at_exactly_ninety_percent_of_the_cap_warns` -> `KeyError: 'status'`

**Final (iteration 2):** 189/189 in all 8 parallel rounds, 0 failed, 0 errors, 0 skipped.

**Tests deleted:** none. The single failure passed STEP 1a (PRD 3.5 states the cap bands verbatim: "when recognised revenue is greater than or equal to the cap, `cap_status` is `CAP_REACHED`; otherwise, when recognised revenue divided by the cap is greater than or equal to ninety percent, `cap_status` is `CAP_WARNING`") and STEP 1b (a faithful reader cannot land elsewhere: 1800/2000 is exactly nine tenths, and PRD 3.2 makes delisting fire only on `CAP_REACHED`, so "nothing is delisted" is uniquely derivable). It failed STEP 2 instead.

**Fixes applied to `test_helpers/`:** none. Audited `factories.py` (all monetary fields emitted as JSON integers, per PRD 2.8) and `fixtures.py` (version-guard ordering on the second onboarding document, and `rev-2` grading the kitchen inspection so `rev-1` stays SoD-eligible to approve menu items) — both already PRD-faithful, which matches the fact that no test failed as a setup error.

**Fixes applied to `implementation/`:** none. The defect was not in the implementation.

**Fix applied to `test_suite/`:**
- `test_13_calculation_edges.py`, `test_14_recognised_revenue_at_exactly_ninety_percent_of_the_cap_warns` line 699 — the assertion read the menu item's single-status field as `item["status"]`, but PRD 2.7 declares that dimension as `review_status` ("a `MenuItem` has `review_status` (`DRAFT`, `UNDER_REVIEW`, `REVISION_REQUESTED`, `APPROVED`, `REJECTED`, `DELISTED`)"); `status` belongs to `ProductionWindow`, `PickupHub`, `SafetyIncident`, `PayoutStatement` and `RefundEvent` instead. Changed to `item["review_status"] == "APPROVED"`. This makes the test **more** faithful to PRD, not less — the same `APPROVED` value is still asserted, just on the field PRD actually names. I grepped every `["status"]` read across `test_suite/` and `test_helpers/` to confirm this was the only entity/field conflation; all remaining ones correctly target single-`status` entities.

## Step 8: Finalize PRD — 2026-09-04T10:00:00.000Z

Orchestrator verification: PRD_FINALIZED.md exists, 501 lines, md5 identical to PRD.md — a legitimate zero-edit outcome, because Step 7's only fix was test-side (a `status` vs `review_status` field-name conflation in one assertion) with 0 implementation fixes and 0 test_helpers fixes. There was no PRD silence for Step 8 to pin.

Step 9 plan, decided by the orchestrator: because a byte-identical PRD_COMPLETED.md is the known failure signature of a Step 9 scan that never actually walked the implementation, Step 9 is run as THREE sequential file-partitioned passes over the 14 implementation modules rather than one monolithic scan. Pass A does the `cp` and covers app/core/auth/validation/listing/routes_config; Pass B covers calc/services/routes_cooks/routes_menu; Pass C covers routes_windows/routes_orders/routes_safety/routes_money. Each pass edits the same PRD_COMPLETED.md in sequence.

Subagent summary (verbatim):

`workspace/PRD_FINALIZED.md` created. **Zero edits were warranted** — it is a byte-identical copy of `PRD.md`.

## Line counts
- `PRD.md`: 501 lines
- `PRD_FINALIZED.md`: 501 lines
- Delta: **0 lines (0.0%)**, md5 identical (`09699b78ad872dac9f146bb509580a70`)

## Changes
None.

## Why zero edits

The step_7_diff contains exactly one item: `test_13_calculation_edges.py::test_14_recognised_revenue_at_exactly_ninety_percent_of_the_cap_warns` line 699, where the assertion read `item["status"]` instead of `item["review_status"]`. Zero implementation fixes, zero `test_helpers/` fixes, zero test deletions. I traced the item's three behavioral subjects and found PRD already uniquely determines each one.

### Subject 1 — MenuItem's single status dimension is named `review_status`
- **Impl paths enumerated:** `routes_menu.py:75` (creation writes `"review_status": "DRAFT"`), `:95` (list filter key), `:106`, `:122`, `:150`, `:160`, `:173`, `:180`, `:221`; `services.py:70-76` (cap cascade) and `:109-110` (suspension cascade); `routes_orders.py:65` (order-placement approval gate). Grepped `'"status":'` across all 14 impl modules to enumerate every entity that *does* use a bare `status`: `routes_config.py:161,246` (PickupHub), `routes_windows.py:75` (ProductionWindow), `routes_safety.py:83` (SafetyIncident), `routes_money.py:63` (PayoutStatement), `:208` (RefundEvent). Also confirmed `OnboardingDocument` uses `review_status` (`services.py:148,157,168,219`) and the two-dimension entities use `onboarding_status`/`compliance_standing` (`routes_cooks.py:78-79`) and `fulfillment_status`/`payment_status` (`routes_orders.py:110-111`).
- **Finding:** the impl's per-entity naming matches PRD 2.7 line 121 **exactly, entity for entity**, with no aliasing. PRD reinforces `review_status` for `MenuItem` in three further places (2.11 priority 13, 3.2 line 240, 3.9 line 370) and never once refers to a menu item's dimension as `status`. A fresh implementer reading PRD alone cannot land on `status`. No PRD silence, no mismatch.

### Subject 2 — the `cap_status` bands
- **Impl paths enumerated:** `calc.py:172-179` (`cap_status_for`), constants `calc.py:15-16`; callers `services.py:46-47,60` (recompute + cascade trigger), `routes_cooks.py:82` (initial `UNDER_CAP`), `:119,121` (compliance-summary projection incl. `cap_remaining_cents`).
- **Finding:** `calc.py:173` returns `CAP_REACHED` on `recognised >= cap`; `:176` compares `recognised * 10 >= cap * 9` — an exact integer comparison, no rounded percentage. This is verbatim PRD 3.5 line 290 including its "compared exactly, not as a rounded percentage" clause. (The `cap > 0` guard at `:175` is dead code: `cap == 0` always returns `CAP_REACHED` first, so it is not an observable extra branch.)

### Subject 3 — nothing is delisted at `CAP_WARNING`
- **Impl paths enumerated:** `services.py:63` (`run_cap_cascade and new_cap == "CAP_REACHED" and previous_cap != "CAP_REACHED"`), the delist/bounce arms at `:70-76`, plus the two other places that read `cap_status` as a gate — `routes_menu.py:111` (delisted-item resubmission leg) and `:193` (approval gate).
- **Finding:** the delist/bounce cascade fires only on the `CAP_REACHED` edge, matching PRD 2.9 line 141 and 3.2 line 250. `CAP_WARNING` gates nothing anywhere in the impl, matching PRD's silence about it having consequences.

The failure was a pure test authoring bug (Step 7's own note records it failed STEP 2, not STEP 1a/1b), so per the method's step 1 there is nothing to pin. No edits were manufactured.

## Step 9: Complete PRD — 2026-09-04T11:35:00.000Z

Run as three sequential file-partitioned passes over the 14 implementation modules, all editing the same PRD_COMPLETED.md in place (Pass A did the `cp` from PRD_FINALIZED.md; B and C edited surgically and were forbidden to re-`cp` or revert).

Orchestrator verification:
- `PRD_COMPLETED.md` = 503 lines / 124,404 chars vs `PRD_FINALIZED.md` 501 / 105,776 — **+18,628 chars**, md5 `5c920f055d6b17f224cc524ff7b130ce` vs `09699b78ad872dac9f146bb509580a70`. NOT byte-identical, so the scan genuinely walked the implementation.
- Tail ends on the final complete error-catalogue table row — a real section boundary, not mid-sentence.
- Implementation untouched by Step 9: every file under `workspace/implementation/` has an mtime of 08:22-08:47, all predating Pass A's 09:47 start. The three passes booted throwaway verification servers (ports 18763 etc., killed by specific pid — no broad pkill) but edited no code.
- The verified clean sweep (8x 189/189, results files timestamped 09:38) postdates the only test edit (test_13 at 09:31), so the green result covers the final test artifact.

Totals across the three passes: **47 ambiguity-pins, 10 mismatch-revisions, 3 cross-pass/intra-PRD contradictions fixed**, +2 lines net (all edits in-paragraph; no new sections).

### Pass A (app.py, core.py, auth.py, validation.py, listing.py, routes_config.py) — 16 pins / 5 mismatches

501 -> 503 lines, 105,776 -> 113,814 chars. Notable: header trimming and whitespace-as-absent (auth.py:34-42); `api_request_id` shape `req_`+20 chars (core.py:232); `api_request_timestamp` read from the logical clock, not wall clock (core.py:240); no maximum `offset`, empty-string limit/offset take defaults (validation.py:197-211); `created_at` ties break by mint order, never by id (core.py:222); client timestamps stored and echoed verbatim (core.py:23-36). Mismatches: `version` advances at most once per request while `updated_at` refreshes each time (core.py:208-219); `label_required_fields` casing NOT enforced (routes_config.py:37); hub creation does NOT check the zone's `service_mode` — a hub under a DOOR_DELIVERY zone is created and simply never becomes eligible (routes_config.py:148-163); slot releases also fire when consolidation re-points an order (services.py:7-14); the §4 POST /pickup-hubs description no longer claims the zone must be hub-pickup. Also pinned the three infrastructural codes (ERR_NOT_FOUND/ERR_METHOD_NOT_ALLOWED/ERR_INTERNAL) as living outside the §5 table and outside the §2.11 ladder (app.py:39-56). Zero-edit module: `listing.py` — its behavior was already pinned by §2.3/§3.9; its two silences were pinned there rather than duplicated.

### Pass B (calc.py, services.py, routes_cooks.py, routes_menu.py) — 18 pins / 1 mismatch

503 lines unchanged, 113,814 -> 118,683 chars (0 new lines). Notable: spoilage reserve is an exact ceiling on the committed count, not a rounded percentage (calc.py:121-132); document submission legal only from DRAFT/DOCS_SUBMITTED (routes_cooks.py:188); VERIFY on an expired cert and WAIVE on a non-HOME_COTTAGE inspection both surface as ERR_INVALID_DOCUMENT_TRANSITION rather than the specific codes (routes_cooks.py:285-295); the grading `note` is accepted but not persisted (routes_cooks.py:266); `verified_kitchen_type` comes from the newest graded inspection even if that type is no longer policy-allowed (services.py:158-171); activating a SUSPENDED/REVOKED cook is ERR_INVALID_COOK_TRANSITION, not ERR_COOK_SUSPENDED (routes_cooks.py:324); whitespace-only `allergen_review_notes` fails the approve gate (routes_menu.py:189); SoD bars any KITCHEN_INSPECTION that reviewer graded whatever its current review_status, including SUPERSEDED (routes_menu.py:129-142); the cap cascade fires only on the transition *into* CAP_REACHED (services.py:47-64); a cancelled order retains `pickup_hub_id` (services.py:88-95); `commission_rate`/`tier_rate` serialise as JSON numbers (calc.py:105,357); handoff span is whole minutes, truncated (calc.py:183-190); `cap_remaining_cents` is not floored at zero and can go negative (routes_cooks.py:121); an order counts as covered when ANY FINALIZED/PAID statement exists for its window, whichever cook it names (calc.py:367-377). Mismatch: the ladder placed kitchen-type-not-allowed only on inspection grading, but impl also runs it on self-registration ahead of duplicate-email (routes_cooks.py:56-67). All four modules produced edits. Five highest-risk pins confirmed against a live server on port 18763, killed by pid.

### Pass C (routes_windows.py, routes_orders.py, routes_safety.py, routes_money.py) — 13 pins / 4 mismatches / 3 contradictions fixed

503 lines unchanged, 118,683 -> 124,404 chars; 17 edits on 16 lines, changed-line set verified disjoint from A and B. Notable: `week_start_date` never checked to be a Monday nor cross-checked against the three instants (routes_windows.py:29); a diner may omit X-User-ID entirely, so `diner_user_id` lands null and a later header-less cancellation compares null to null and passes (auth.py:45-53); **the ordered window need not belong to the dish's cook** — the order is admitted and reserves meals against that foreign window (routes_orders.py:87); the diner-ownership comparison is evaluated after transition legality, so ERR_INVALID_ORDER_TRANSITION masks it (routes_orders.py:253-263); delivery capture that carries cap_status into CAP_REACHED runs §3.2's delist and bounce arms inline (routes_orders.py:243); `severity_override` supplied with DISMISS is ignored (routes_safety.py:123); statement drafting never checks `cook_id` against `production_window_id` and is not gated on window status (routes_money.py:43-58). Mismatches: the three fulfilment edges share one authorised-role list, so any of Cook/Diner/PlatformAdmin may drive any edge with no ownership check (routes_orders.py:199); SoD on adjudication fires only when the adjudicator presents an X-User-ID, so a header-less PlatformAdmin escapes it (routes_safety.py:145); SAFETY's missing `safety_incident_id` is priority-5 ERR_INVALID_REQUEST and the incident is only resolved, never required SUBSTANTIATED (routes_money.py:178-184); `created_by_user_id` falls back to `system` when the caller sent no X-User-ID, and the original text's cascade clause was unreachable since no cascade ever creates refunds (routes_money.py:177,210-215).

Three contradictions found and fixed by the closing cross-pass read, all in ladder text A and B had left alone: ladder 17's false window-status clause (ERR_CUTOFF_NOT_REACHED is a pure clock comparison — contradicted both routes_windows.py and Pass B's own §3.4 consolidation paragraph); ladder 28's unscoped open-incident rule (contradicted §3.8's own window-scoped sentence in the *original* PRD); and §3.6's per-edge actor prose (contradicted §4's single shared role list for /orders/{id}/advance). Pass C re-read §2.1-§2.5, §2.8, §2.11, §3.1, §3.2, §3.4 and confirmed all of A's and B's other edits hold against its four modules.

## Pipeline complete — 2026-09-04T11:35:00.000Z

All nine steps done. Final state: 189 tests, 8/8 sweep rounds at 189/189; SCAFFOLD trio + PRD.md + PRD_FINALIZED.md + PRD_COMPLETED.md + test_helpers/ + test_suite/ + workspace/implementation/ all present.
