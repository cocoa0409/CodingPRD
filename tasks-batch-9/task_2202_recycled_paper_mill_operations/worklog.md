# Worklog — task_2202_recycled_paper_mill_operations

## Step 1: Create task directory — 2026-08-31T17:54:55.622Z

Created `tasks/task_2202_recycled_paper_mill_operations/` and `tasks/task_2202_recycled_paper_mill_operations/workspace/` (pre-allocated task name used verbatim; no index scan performed).

## Step 2: Generate scaffold — 2026-08-31T22:47:00.000Z

Generated in three separate subagents (SCAFFOLD.yaml, then DIFFICULTY + CORNER concurrently) after two initial single-agent attempts were killed by the 600s stream watchdog during long silent generation. Chunked incremental writes (heredoc appends, <=350 lines/call) plus bounded-slice reads of SCAFFOLD.yaml resolved it. The difficulty agent also hit one transient API server error at 695 lines and was resumed in place with context intact.

### 2a — SCAFFOLD.yaml (2414 lines, 168 KB)

SCAFFOLD.yaml is complete and verified. `yaml.safe_load` parses cleanly; not truncated. Top-level keys are exactly: `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles`. No `scaffold_difficulty_design`, no `scaffold_corner_design` (grep count 0).

`scaffold_lint.py` does not support single-file linting (it demands a task dir containing all three YAMLs), so the module was imported and its scaffold-only check run directly: `lint_fk_reverse_reachability(scaffold, load_endpoints(scaffold))` -> `violations: []` across all 18 FKs. (`api_prefix: "/"` was chosen specifically so the lint's segment derivation accepts every path.)

Ad-hoc invariant sweep, all green: every error_id referenced by state machines / concurrency rules / validations / endpoints exists in §1.6 (0 missing) and every catalog entry is referenced (0 unreferenced); all endpoint `roles` are declared in §1.7 and all 8 declared roles are used; validation priorities are contiguous 1..71; all FK targets resolve to declared entities; no forbidden concurrency vocabulary; logical-clock default `2026-08-01T00:00:00Z` sentence present; 8 `identity:` declarations (one per role).

Counts: 19 entities / 177 fields; 7 state machines / 55 transitions; 3 concurrency rules (all 412, OCC on parent `version`); 15 calculations; 71 validations (priorities 1-71); 91 endpoints; 71 errors; 8 roles.

Errors by class: 5 auth (401/403), 19 existence (404), 3 shape (400/422), 9 state (409), 3 OCC (412), 10 safety, 13 constraint, 3 temporal, 6 fiscal.

Roles: MillPlanner, FiberBuyer, QualityLab, MachineOperator, EnvironmentalOfficer, EnergyManager (`opaque`); Supplier (`entity_backed:Supplier`), Customer (`entity_backed:Customer`).

What pushes it past expert level:
- Two dual-variant calculation pairs, not one: `pulp_yield_provisional` vs `pulp_yield_final` (book furnish vs measured reject reconciliation, persisted `yield_variance_tons`), and `run_quality_index_provisional` (first + last reel, unweighted) vs `run_quality_index_certified` (tonnage-weighted over all reels) — so a run can pass provisionally and fail certification purely from weighting.
- Parallel state axes: `ProductionRun` carries independent `run_status` and `quality_status`; the cycle `PROVISIONAL -> HELD -> REWORK -> PROVISIONAL` re-enters an already-visited quality state while `run_status` stays put, and the hold fires a 3-hop cascade into roll sets and orders.
- Cyclic, counter-bounded transitions everywhere: PO `PRICED -> DRAFT` (`pricing_revision_count < 2`), `DEINKING <-> DEINK_HOLD` (<=3 passes), order `SCHEDULED -> SUBMITTED` (<=3 deschedules), roll `QUARANTINED -> REWOUND -> WOUND` (<=2 rewinds) — each with its own distinct exhaustion error.
- Deep transitive cascade: supplier strike -> lot quarantine -> pulp batch cancel -> run abort -> roll scrap + order deschedule (4 hops), and a receipt-disposition fork whose three branches have genuinely divergent side effects (accept / downgrade to the self-referential `downgrade_target_grade_code` / reject with strike accrual). The strike counter deliberately excludes receipts flipped to REJECTED by the PO-cancel cascade (`dispositioned_by_user_id != null`).
- Two incompatible temporal-overlap semantics in one scaffold: closed machine windows widened by a per-machine changeover buffer plus a computed `transition_minutes` gap requirement (grade-change direction-sensitive: `FAMILY_CROSS_MULT 2.20`, `UPSEQUENCE_MULT 1.15`, capped at `MAX_WASTE_TONS 12.000`), versus a half-open aggregate-capacity steam header (`HEADER_CAPACITY_TPH 180.000`) dispatched by a waterfall with a `MIN_VIABLE_TPH 5.000` remainder rule.
- Three conserved-quantity ledgers (`mill_fiber_balance`, `solids_ledger_balance`, `order_allocation_ledger`) that must net to zero under reversal rows — reject-stream reversals are append-only compensating entries, never mutations.
- Boundary precision traps: per-sublot 3dp rounding then sum then 2dp (order of rounding is observable), per-tier 4dp cogen credit then 2dp total, effluent `WATCH_RATIO 0.90` with ratio exactly `1.00` classified WATCH rather than EXCEEDANCE, and an inclusive rolling window anchored on the newest reading (so voiding a reading can re-anchor the window and flip posture).
- Priority-conflict wiring made explicit: validation rows state which neighbour they lose to and which they beat (e.g. priority 40 loses to 31 when the run is not SCHEDULED but wins over 67 when pulp is also short), so ordering is testable rather than incidental.
- Three-way segregation of duties: sampler != dispositioner, run starter != certifier, and manifest preparer != signer != any officer who logged a reading in the permit's current rolling window — the third makes the SoD check depend on a computed window, not a static field.

### 2b — SCAFFOLD_DIFFICULTY_DESIGN.yaml (1731 lines, 219 KB)

Complete: parses under `yaml.safe_load` with exactly one top-level key `scaffold_difficulty_design`, no truncation. SCAFFOLD.yaml was never modified and neither the sibling task dirs nor the concurrent corner-design file was touched.

Coverage: 9 rules / 33 non-stub instances.

| rule_id | instances | differentiating axis used |
|---|---|---|
| dual_variant_calc | 3 | PulpBatch book-vs-measured yield; ProductionRun endpoints-vs-all-reels-weighted index; deink-path yield |
| combinatorial_formula | 4 | modes c / b / a / b (frozen index tier, per-sublot rounding before summation, nested min-max with unit guard, per-tier cogen rounding) |
| non_linear_state_machine | 3 | ProductionRun quality cycle with run axis pinned; PulpBatch deink self-loop to pass limit; FiberReceipt 3-way disposition fork |
| transitive_cascade | 3 | 4-hop supplier suspension; run-condemn -> rolls -> solids ledger; batch divert -> run abort -> order shortfall -> window freed |
| priority_pair_validation_conflict | 4 | 40>67, 31>40, 23>33, 37>58 |
| boundary_precision_check | 4 | effluent ratio exactly 1.00 + flow exactly at limit; PO closes at exactly 98.00; exact lot depletion; certified index exactly 85.00 |
| cross_entity_state_dependency | 4 | Run<->Permit, RollSet<->Run, PurchaseOrder<->Supplier, SludgeManifest<->Permit |
| resource_temporal_overlap | 4 | buffered-closed widening (PM1, buffer 60); closed touching endpoints (PM3, buffer 0); half-open steam header incl. release/re-request; inclusive computed gap on GradeChange |
| compensating_invariant | 4 | lot fiber ledger `imbalance_tons`; batch ledger `final = consumed + available`; `net_solids_tons` across sign/void; split identity `net == manifested + unmanifested` across a reversal |

Mechanisms targeted for depth: per-tier/per-sublot rounding order (`receipt_net_tons`, `cogen_credit`, `deink_chemical_cost`), the frozen index-tier evaluation order, the parallel-axis ProductionRun machine (run_status x quality_status) plus its rework cycle and REWORK->PROVISIONAL roll-status precondition, the deink pass-limit self-loop, all three OCC rules, 20 distinct validation priorities including the four documented precedence pairs, both interval geometries (closed+buffered machine occupancy vs half-open steam header, exercised against the same timestamps), the steam waterfall/curtailment/saturation branches, and all four ledger invariants with their compensating actions and double-compensation refusals.

Notable verification results:
- All 33 instances carry structured `setup_api_calls`/`trigger` call objects; every `${var}` is bound by an earlier `captures:`, every referenced endpoint path resolves against §1.5, every `ERR_*` exists in §1.6, and all 131 distinct `grounds:` entries resolve (entities/fields, calculations + variant names, state machines, validation priorities, `concurrency_rules.roll-allocate-stale-order`).
- Every formula-derived assert is a pre-computed literal (verified with `Decimal`/ROUND_HALF_UP), e.g. cogen 1302.00 / 0.00 / 1245.50 / 123.00, transition waste 2.875 at 45 min (44 refused), provisional 30.060, final 25.500 vs projection 25.050.
- Fixture-level ambiguities in the scaffold were deliberately routed around rather than asserted: `FiberInventoryLot.tons_consumed` is only observed after START and after CANCEL (its §1.1 description conflicts with the QUEUED-reserves-nothing side effect), and the steam release probe uses a window that touches but does not overlap the curtailed row, so it is decisive under both readings of "recompute of survivors".
- Three scaffold paths remain design-unreachable and were not used: RollSet ALLOCATED->QUARANTINED via a quality hold, the DRAFT-manifest tonnage step of the permit EXCEEDANCE cascade, and a dedicated error for "certify below 85.00" (expressed as a successful `/hold` instead).

### 2c — SCAFFOLD_CORNER_DESIGN.yaml (10843 lines, 660 KB)

Complete and verified: parses under `yaml.safe_load` with exactly one top-level key `scaffold_corner_design`, not truncated (ends on a complete `assert` string).

Sections (9, canonical §1.9 order) and non-stub instance counts — 120 total, 0 `excluded_because` stubs: entities 14, state_machines 15, calculations 21, validations 12, endpoints 7, errors 30, rbac 11, cross_cutting_complexity_layers 8, consistency_model 2.

Verification run (all green):
- 120 unique names, no duplicates; every instance has exactly the 7-point contract keys and a `test_recipe` with `setup` / `setup_api_calls` / `trigger` / `assert`.
- 324 distinct `grounds` refs, all resolve against SCAFFOLD.yaml (entity fields, `from`->`to` transitions, calculation names, validation priorities 1-71, error ids, role names, the three `concurrency_rules` rule_ids).
- Every `claim_type` is a snake_cased row from the closed taxonomy in `references/claim-extraction-guide.md`, matched to this scaffold's profile (`entity_topology: hybrid`, `state_machine_shape: parallel`, `role_model: segregation_of_duties`, layers = optimistic_concurrency / cascading_side_effects / dual_variant_calculation / rate_threshold_triggers, `consistency_model: immediate`).
- Clause 3c holds: zero literal `expected_*_version` values — all are `${var}` captured from an immediately preceding GET.
- Zero unbound `${var}` placeholders across all 120 recipes.
- Errors surfaced at `response.data.error_id` per the §1.0 envelope everywhere.

Breadth coverage. Entities: creation/retrieval/listing+pagination, required fields, defaults, computed vs input-ignored, system fields, enum & range type constraints, immutability of the ledger/reading rows, parent relationships, and the hybrid-topology cross-reference integrity. State machines: initial state, valid transitions, precondition enforcement, invalid-trigger matrix, terminal lockdown, idempotency, plus all six side-effect patterns (cascade down, bubble up, cross-entity, ledger sync, compensation, conditional cascade) and the parallel/cyclic shape claims (deink rework loop with its termination guard). Calculations: index-based PO pricing (tiered, provisional 16.880 vs final 18.000 with the 1.120 reconciliation delta), furnish blend at the inclusive 3.500 bound, yield/waste, grade-change transition waste (12.000 t -> 66 min), cogen split 433.43 / 5817.00 / 492.00, rolling BOD load 500.000 ratio 1.00 -> WATCH, waterfall steam allocation, chronological/interval-merge/decay/aggregation and precision-rounding claims. Validations: the full priority ladder — auth 1-5, per-collection existence 6-19, body-referential 20-21, state gates, SoD, aggregate/temporal/conditional/cascading patterns, and four explicit priority-conflict pairs. Endpoints: CRUD, action, bulk (`complete` reel readings), cross-reference link, computed read, conditional action. Errors: all 71 catalog codes exercised except one (below), including the 13-way per-collection 404 family. RBAC: exclusive ops per role, shared ops, cross-role denials, and three SoD instances. Layers: one OCC instance per `concurrency_rules` entry, three multi-hop cascade chains, the dual-variant reconciliation, and the rate/threshold boundary. Consistency: immediate visibility within the same response, incl. a manifested + unmanifested = net solids reconciliation in a single read pass.

Scaffold flaws found (reported, not stubbed — the corner agent could not cite §1.8 instances in a file it must not read):
1. `RollSet ALLOCATED->QUARANTINED` is unreachable, which in turn makes `CustomerOrder ALLOCATED->PARTIALLY_ALLOCATED` unreachable.
2. The run-abort cascade requires a `CustomerOrder IN_PRODUCTION->SUBMITTED` edge that the state machine does not declare.
3. `ERR_NO_SHORTFALL` (priority 71) is unreachable — short-close is already gated so that no zero-shortfall order can reach the check; referenced only descriptively.
4. `ERR_TONNAGE_ALREADY_BOOKED` (priority 70) is unreachable on both branches — the only catalog code with no test.
5. Validation priority 44 cites "the permit's current rolling window", but `SludgeManifest` carries no `permit_id`, so the rule has no path to a permit.
6. The `EffluentPermit` EXCEEDANCE cascade's hops 2 and 3 are vacuous: only DRAFT manifests are voided and their rows are still PENDING, so no solids move. The instance's asserts document these as deliberate no-ops.

## Step 3: Copy shared files — 2026-08-31T22:47:30.000Z

Copied `./INSTRUCTION.md` -> `tasks/task_2202_recycled_paper_mill_operations/workspace/INSTRUCTION.md` (53 lines).

## Step 4: Generate PRD — 2026-08-31T23:23:00.000Z

PRD generation and verification complete.

Deliverable: `workspace/PRD.md` — 478 lines, ending at §5 (no contract reports written into the file).

Sections produced:
- §1 Introduction (3 paragraphs: domain pain, why software, two structural themes)
- §2 Global Specifications: 2.1 RBAC (8 roles, 2 entity-backed) · 2.2 API Response Structure (verbatim from `skills/prd-bench-doc-generator/section-2.2-response-structure.md`) · 2.3 Pagination · 2.4 Identity/Timestamps/Version (incl. the four `common_fields: false` entities) · 2.5 OCC on shared parents · 2.6 Precision & rounding · 2.7 Nested path resolution order · 2.8 Rule evaluation order · 2.9 Conserved quantities + logical clock
- §3 Business Logic, 9 subsections: fiber grades/indices/contract pricing · weighbridge sampling & disposition · pulping/screening/cleaning/deink · machine capacity, run windows, grade transitions · run execution and the two status axes · customer orders, roll sets, allocation · discharge permits, rolling compliance, solids manifests · steam header, curtailment, cogen credit · read surfaces and filters
- §4 Endpoint Definitions — 91-row table (Method | Path | Description | Authorized Roles)
- §5 Error Code Catalogue — 71-row table

### Hard Contract reports

Contract 1 — Field-Name Coverage: PASS
- entity fields: 153/153 present as backticked tokens, 0 missing
- endpoint `input` identifiers (request bodies + query params, optional `?` markers stripped): 103/103, 0 missing
- path params: `id`, `machine_id`, `run_id` — all present
- (Two passes run; first pass flagged `provisional_quality_index`, now stated in §3.5.)

Contract 2 — Rule Coverage: PASS
- 71/71 error ids in §5 and each also stated in §2/§3 prose (zero appear in the table only)
- 71/71 validation `error_id`s covered; global priority ordering stated in §2.8, with per-operation relative order stated in §3
- 42/42 state names across the 7 state machines present, with preconditions, side effects and terminal states
- 15/15 calculations stated with formula, constants and rounding; every numeric constant present (tier ceilings written as `100000.00`/`250000.00`; `0.98` order-close multiplier and `0.40` reject-plausibility multiplier added as literals)
- every entity enum literal and every declared min/max/default numeric bound present
- OCC documented for all seven version-bearing operations (roll-set allocation, order scheduling, run creation, grade-change planning, machine status change, order pricing, pricing withdrawal) with `expected_order_version` / `expected_machine_version` / `expected_purchase_order_version` and the three 412 codes
- 8/8 roles with capabilities and segregation-of-duties rules
- Residual "missing" tokens are only scaffold-internal formula variable names (`bw_delta`, `reel_score`, `removal_frac`, …), algorithm tags (`tiered_pricing`, `waterfall_allocation`), YAML keys (`side_effects`), and §-number cross-references — all deliberately translated into prose per the no-pseudocode rule.

Contract 3 — §3 Path Purity: PASS — 392 unique backticked tokens in §3: 0 start with `/`, 0 are bare HTTP methods, 0 combine method+path, 0 contain `/` at all.

### Coverage self-audit

Everything in the scaffold's §1.0–§1.7 is stated: 19 entities, 7 state machines, 15 calculations (including all dual-variant pairs — provisional vs final pulp yield, provisional vs certified run quality index, effluent rolling posture), 71 validations, 91 endpoints, 71 errors, 8 roles, the logical clock, and the three OCC version fields. One scaffold internal discrepancy was resolved in the PRD's favour of the endpoint contracts: `concurrency_rules` names only 3 version-checked writes, while validations 37–39 and the endpoints' declared `input` lists extend version fields to 4 more operations — §2.5 documents all seven, using the exact error ids and statuses from the scaffold. Nothing was left uncovered. `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced, and no sibling task directory was inspected.

## Step 6: Generate implementation — 2026-09-01T04:05:00.000Z

The implementation is complete and verified.

Files created (`workspace/implementation/`, 3475 lines total):

| File | Lines | Role |
|---|---|---|
| `start.sh` | 8 | Launcher; guarded pip install (skips reinstall on per-test reboots), `exec python3 app.py` |
| `requirements.txt` | 1 | `flask==3.0.3` |
| `app.py` | 55 | App factory, `before_request` auth, ApiError/404/405/500 handlers, blueprint registration |
| `clock.py` | 33 | Logical clock, default `2026-08-01T00:00:00Z`, never falls back to wall time |
| `store.py` | 75 | In-memory dicts for 19 collections; starts empty, zero seeding; `insert`/`touch`/`get`/`all_rows` |
| `errors.py` | 102 | Exactly the 71 declared error IDs -> HTTP status map |
| `response.py` | 58 | `meta`/`response_type`/`data` envelope + pagination meta |
| `auth.py` | 59 | Header auth, 8 roles, entity-backed Supplier/Customer identities, ownership checks |
| `shape.py` | 219 | Typed field extractors, pagination, OCC-field guards, ISO rendering |
| `calc.py` | 356 | All 15 calculations, `Decimal`+`ROUND_HALF_UP` throughout |
| `common.py` | 350 | Ledger recomputation and the 4 cascades (supplier suspension, batch diversion, quality hold, permit exceedance) |
| `routes/parties.py` | 178 | Customers, suppliers, fiber grades, index quotes, paper grade specs |
| `routes/fiber.py` | 373 | Purchase orders, receipts, inventory lots, fiber balance |
| `routes/pulp.py` | 306 | Pulp batch lifecycle (start/screen/clean/deink/brightness/approve/divert/cancel) |
| `routes/machines.py` | 201 | Machines, grade changes, run scheduling |
| `routes/runs.py` | 276 | Both run axes: start/complete/abort + certify/hold/rework/resubmit/condemn |
| `routes/rolls.py` | 223 | Roll sets: create/wrap/allocate/quarantine/rewind/rewind-complete/scrap |
| `routes/orders.py` | 191 | Customer orders: schedule/deschedule/ship/short-close/cancel |
| `routes/env.py` | 286 | Permits, readings, sludge manifests, solids ledger + summary |
| `routes/steam.py` | 107 | Steam waterfall dispatch, cogen credit, release |
| `routes/admin.py` | 18 | Logical clock setter |

Endpoint organization: all 91 declared endpoints match the contract exactly — the app's `url_map` was diffed against SCAFFOLD's endpoint list programmatically: 91 declared, 91 implemented, zero missing, zero extra. Grouped into 10 blueprints by domain area, mounted at the root so paths match the spec verbatim.

Notable design decisions:
- Two occupancy geometries kept deliberately distinct: machine windows are closed intervals widened by `changeover_buffer_minutes` on both sides; steam header windows are half-open, so the identical timestamp pair conflicts on a machine and coexists on the header.
- `_reserved` private flag on PulpBatch lets lot `tons_consumed` distinguish QUEUED (no reservation) from PULPING-onward, which keeps the fiber-balance `imbalance_tons` at exactly `0.000` across cancellations and aborts. Underscore-prefixed keys are stripped by `common.view()`.
- Stable ordering under a frozen clock: rows sort by `(created_at, _seq)`, since the logical clock makes many rows share a timestamp.
- PRD-over-SCAFFOLD conflict resolution on `POST /pulp-batches/{id}/start`: the scaffold's priority numbers put contamination (47) before tonnage (66), but PRD §3.3 explicitly enumerates the order with tonnage coverage first. Followed the PRD per the skill's precedence rule.
- Per-band rounding in the cogen credit (4dp per band, then 2dp total) implemented exactly as pinned, not sum-then-round.

Boot and behaviour verification: fresh `PORT=8099 bash start.sh` booted clean; every collection reported `total_count: 0`, confirming no seeding. Two smoke suites run against it:
- Happy path, 40/40 OK — grade -> quote -> supplier -> PO -> price -> confirm -> receipt -> disposition -> lot -> pulp batch (start/screen/clean/approve) -> machine -> run -> order -> schedule -> start -> roll set -> complete -> wrap -> certify -> allocate -> ship -> manifest -> sign -> steam. Spot-checked arithmetic all correct: cogen credit `4076.00` for an 80 tph export over 8 h; curtailment to `80.000` with `curtailed_tph 20.000`; fiber balance imbalance exactly `0.0`.
- Error paths and cascades — pagination 400s, `ERR_UNKNOWN_ROLE`, OCC `412 ERR_STALE_MACHINE_VERSION`, `ERR_DUPLICATE_KEY`, `ERR_DATE_OUT_OF_RANGE`, `ERR_INVALID_WINDOW`, `ERR_STEAM_HEADER_SATURATED` (including the touching-endpoint case correctly not colliding), `ERR_SOD_SAME_ENV_OFFICER` on both halves of the rule, and the full permit-exceedance cascade (posture -> `EXCEEDANCE`, DRAFT LAND_APPLICATION manifest auto-`VOIDED`, subsequent prepare barred, then recovery to `COMPLIANT` after voiding the reading). The solids-ledger invariant `net == manifested + unmanifested` held before and after a reversal.

Server was then stopped; port 8099 confirmed closed. A stray empty `services/` directory and `__pycache__` trees were removed, and one unused error ID dropped so the catalogue is exactly the 71 declared codes.

## Step 5: Generate unit tests — 2026-09-01T04:12:00.000Z

Stage 2 is complete. Both design queues are exhausted.

37 files in `test_suite/` (`conftest.py` + 36 test modules), 180 tests, every one carrying exactly one `Design:` tag as the last docstring line. Files added in the final stretch:

| file | tests | instances |
|---|---|---|
| `test_33_cascades_across_four_levels.py` | 2 | fourth-strike four-level unwind; exceedance voids the land-application manifest only |
| `test_34_variant_selection_and_ladder_boundaries.py` | 3 | hold cascade reaching no order; pulp gate reads the weighed variant; strike ladder boundary walk |
| `test_35_tissue_run_refuses_undeinked_furnish.py` | 1 | `ERR_DEINK_PULP_REQUIRED` |
| `test_36_writes_settle_inside_their_own_call.py` | 2 | write body already carries derived fields; abort cascade settled in-call |

Earlier files (test_01–test_32) hold the other 172 tests; per-file counts are 2–9 each, all files under 220 lines.

Design coverage:
- Queue A (difficulty, §1.8): 33 / 33 translated, 0 skipped.
- Queue B (corner, §1.9): 118 / 120 translated, 2 skipped.
- Total 151 / 153 instances translated; a verification pass confirms every `Design:` tag resolves to a real `name:` in the source yaml and no tag is untagged or dual-tagged. `citecheck` reports `problems: 0` (all `PRD §x.y: "…"` citations verbatim-present in `workspace/PRD.md`).

Skips (both category "PRD does not uniquely derive the asserted error code"):
1. `errors/a_customer_cannot_cancel_an_order_already_in_production` — §3.6 requires `SUBMITTED` for cancel but names only `ERR_TONNAGE_ALREADY_BOOKED`; no code is stated for a wrong-state cancel and §2 has no general `*_INVALID_STATE` fallback rule.
2. `errors/a_suspended_supplier_cannot_be_issued_a_new_purchase_order` — `ERR_SUPPLIER_SUSPENDED` appears in prose only as a pricing gate (§3.1); PO creation states no supplier-status gate.

PRD gaps / design-vs-PRD reconciliations (PRD always won):
1. §3.2 (`tons_consumed` counts every non-CANCELLED batch, so a QUEUED batch reserves) contradicts §3.3 (QUEUED reserves nothing; the pulper charge is the booking moment). Tests follow §3.3.
2. §3.5's steam-header cross-reference points at "§3.7"; the steam header is §3.8.
3. No error code named for cancelling an order that has left `SUBMITTED` (skip 1).
4. No supplier-suspension gate on purchase-order creation (skip 2).
5. Design's `quoted_unit_price_per_ton` figures (180.00 / 185.00) omit freight and fuel surcharge; §3.1's five-step arithmetic yields 194.81 / 199.81 — asserted per PRD.
6. Design's `probation_entered_at == '2026-08-01T00:00:00Z'` conflicts with §2.4's three-fractional-digit rendering; asserted as a prefix match.
7. `ERR_DEINK_PULP_REQUIRED` is only reachable via a run scheduled against a non-APPROVED batch: approval from `CLEANED` forbids deink-requiring targets, so the design's "APPROVED batch with `deink_pass_count` 0" state is unreachable. Translated with a `CLEANED`/`DIP_LINE` TIS_16 batch (start gate three fires ahead of gate four).
8. Likewise the abort-cascade instance specifies a `WRAPPED` set on a `RUNNING` run, but §3.6 requires `run_status == COMPLETED` to wrap while abort requires `RUNNING`; translated with a `WOUND` set, which §3.5's abort clause covers identically.
9. `ERR_PURCHASE_ORDER_INVALID_STATE`'s HTTP status appears only in the §5 table, never in the §3.1 prose sentence.
10. Roll-set/order enum reconciliations: `allocation_priority_tier` is `P1`/`P2`/`P3` (design wrote `1`/`2`), and `provisional_accepted_tons` uses §3.3's effective-yield floor `max(45.00, nominal - 1.8 x contamination)`.

Orchestrator note: a post-generation `pytest --collect-only` found 167/180 tests collecting, with 2 modules (`test_03_nonlinear_state_machines.py`, `test_04_transitive_cascades.py`) failing to import on `ImportError: cannot import name '_paginated' from 'test_helpers'`. Handed to Step 7 as its first fix.

## Step 7: Run tests and iterate — 2026-09-01T01:15:00.000Z

The loop is closed: 180/180 tests pass in all 8 rounds of the parallel stability sweep.

**Iterations run:** 2 full 8-round parallel sweeps (the first aborted mid-flight once it had surfaced the deterministic failures I was already fixing; the second was a clean pass), plus several fast serial verification passes with a temporary per-test-server harness that I have since deleted. Final sweep: all 8 rounds `passed=180 failed=0 errors=0 total=180`, zero non-passing test records in any round — no flakiness.

**Tests deleted:** none. No test failed STEP 1a coverage or STEP 1b unique derivability outright. The one genuinely non-derivable assertion (PRD §2.4 pins the rendering of *server-minted* timestamps to three fractional digits but is silent on how a *client-supplied* instant is echoed back) was handled under STEP 1c partial coverage in `test_suite/test_08_resource_temporal_overlap.py`: the PRD-covered claims (window conflict, incumbent window never widened in storage) were kept and the instants are now compared by value instead of by literal string.

**Fixes applied to `test_helpers/`:**
- `test_helpers/__init__.py` — the reported starting defect. `_paginated` is defined in `fixtures.py` but is private-by-name, so `from .fixtures import *` skipped it and no module defines `__all__`; added an explicit `from .fixtures import _paginated` re-export. Collection went from 167 tests + 2 errors to 180 tests.
- `test_helpers/assertions.py` — added `assert_same_instant(actual, expected_iso, label)`, which parses both sides as ISO-8601 UTC and compares instants, for the §2.4 silence above.

**Fixes applied to `implementation/` (both STEP 3, PRD-mandated):**
- `workspace/implementation/calc.py::pulp_yield_provisional` — removed an `int()` floor on lot contamination. PRD §3.3's pinned restatement is "the effective yield is the larger of 45.00 and the nominal yield minus 1.8 times the lot contamination"; the implementation was floating contamination to whole percentage points. Corroborated by SCAFFOLD line 1071 (`eff_yield = max(YIELD_FLOOR_PCT, nominal - 1.8 * lot.contamination_pct)`); notably two tests in the suite disagreed with each other on this, which is what exposed the PRD's own §3.3 wording ambiguity.
- `workspace/implementation/common.py::recompute_batch_available` — batch `consumed_tons` summed `pulp_draw_tons` over every non-ABORTED run, including still-`SCHEDULED` siblings. PRD §3.5 books the draw at run *start* ("Starting a run has four side effects. The run's `pulp_draw_tons` is added into the batch's `consumed_tons`") and releases it on abort, so the predicate is now `run_status in ("RUNNING", "COMPLETED")`.

**Test-vs-PRD consistency corrections (STEP 2), six tests:**
- `test_02` — the three deink-pass side effects were asserted on the `deink` response; PRD §3.3 fires them when brightness closes the pass. Moved to the `record_brightness` response.
- `test_06` — the fixture fed 145.25/145.26 gsm reels, but PRD §3.5 declares measured `basis_weight_gsm` "at one decimal place", so the implementation legitimately quantized them. Re-cut the fixture to a 120.0-gsm spec with one-decimal reels (124.5 -> exactly 85.00, 124.6 -> 84.67), preserving the exactly-on-the-gate / just-below boundary pair the test exists to probe.
- `test_08` — see STEP 1c above.
- `test_14` — the local fixture built the default 36-ton / 2.73%-contamination lot while every asserted figure was stated against a 22-ton / 2.00% lot. Fixed the fixture, not the expectations.
- `test_17` — the order was sequenced onto a run that had already completed; PRD §3.6 requires the target run's `run_status` to be `SCHEDULED`. Split `_running_tl_140_run` into `_scheduled_tl_140_run` + `_running_tl_140_run` and sequence before start.
- `test_26` — a not-found probe used `FiberBuyer` headers against `GET /fiber-inventory-lots/{id}`, which PRD §4 authorizes only for MachineOperator/MillPlanner/QualityLab, so it hit `ERR_ROLE_NOT_PERMITTED` first per §2.8's ordering. Switched to `OPERATOR`.

No assertion was weakened, no `skip`/`xfail` added, no `error_id` check downgraded to a status check, no PRD-required implementation check removed to accommodate a fixture, and no non-PRD-traceable capability added. Storage remains in-memory dicts with no startup seeding. Also confirmed no test in the suite uses the race helpers (`run_race`, `assert_race_outcome`, `assert_exactly_one_succeeds`, `assert_at_least_one_succeeds`), which removes the main flakiness vector — consistent with the clean 8-round result.

Orchestrator note: the Step 7 agent's own final `results.*.json` were removed by a later overlapping sweep cycle it left in flight, so the orchestrator killed the orphaned runners and re-ran one clean 8-round sweep itself to both regenerate the required artifacts and independently confirm the 180/180 claim.

## Step 8: Finalize PRD — 2026-09-01T01:45:00.000Z

Done. `PRD_FINALIZED.md` written with three minimal edits.

Line counts: `PRD.md` 478 lines -> `PRD_FINALIZED.md` 482 lines (+4 lines, +0.84%); 2 sentences inserted as new paragraphs, 1 sentence revised in place.

Changes:
- §2.4 — insert — New paragraph pinning how client-supplied instants are handled: parsed (naive read as UTC, offset-bearing converted to UTC) and stored/echoed in the same 3-fractional-digit ISO-8601 UTC rendering as server-minted timestamps, so `2026-08-02T06:00:00Z` reads back as `...T06:00:00.000Z`; calendar-date/month fields (`reading_date`, `effective_month`, `priced_for_month`) are returned verbatim. — `implementation/clock.py:26` (`fmt`), `implementation/shape.py:168` (`parse_dt`), `routes/machines.py:172-173`, `routes/steam.py:64-65`, `routes/orders.py:45`, `routes/admin.py:18`.
- §2.6 — insert — New paragraph pinning input-precision semantics: a declared precision on an input is a storage precision, not an acceptance filter; excess decimals are not `ERR_VALIDATION`; the declared range is tested against the value as supplied and the accepted value is then rounded half up to its precision before storage/calculation/echo (`basis_weight_gsm` 124.55 -> 124.6). Exception named: `caustic_kg`/`peroxide_kg`/`surfactant_kg` carried as supplied. — `implementation/shape.py:134-160` (`get_num`, range checks then `places` quantize), `routes/runs.py:100-103,115`, `routes/pulp.py:205-207`.
- §3.3 — revise — Effective-yield sentence: `for every whole percentage point of the lot's contamination_pct` -> `for every percentage point … fractional percentage points included, so the contamination figure is used exactly as it reads and is never truncated to a whole number first`, resolving the internal contradiction with the same sentence's own restatement. — `implementation/calc.py:107-109`.

No edits were made for the remaining Step 7 items: `test_helpers/__init__.py` (harness export bug), `common.py::recompute_batch_available` (PRD §3.5 already books the draw at run start and releases it on abort — impl now matches), `test_02` (§3.3 already fires the three pass side effects on brightness), `test_14`/`test_17`/`test_26` (pure fixture bugs; §3.6's `SCHEDULED`-run requirement and §4's role list for `GET /fiber-inventory-lots/{id}` already match impl, verified at `routes/fiber.py:337`).

### Per-edit pre-edit search log

Edit 1 (§2.4, client-supplied instants)
- (a) Subject: storage/echo rendering of instant-valued fields that originate from the client, vs. date/month strings.
- (b) Enumerated: `grep -rn "get_dt\|DATE_RE\|MONTH_RE\|shape.iso\|current_utc"` across `routes/*.py`, `common.py`, `response.py`. All four client-instant sites (`machines.py:140-141,172-173` run window; `steam.py:41-42,64-65` header window; `orders.py:27,45` `requested_ship_date`; `admin.py:16-18` `to_iso8601`->`current_utc`) go through `shape.get_dt`->`parse_dt` then `shape.iso`->`clock.fmt`. Read `clock.py` in full, `shape.py::parse_dt`/`iso`. Also enumerated the non-instant temporal inputs that must not be covered: `env.py:58,70` `reading_date` (pattern-checked date, stored verbatim), `fiber.py:28` `priced_for_month`, quote `effective_month`. Also checked server-minted derivatives (`common.py:208,236` `probation_entered_at`, `posture_changed_at`) use the same `fmt`, and `machines.py:76,164-165` re-parses the stored strings, so the canonical rendering is round-trip safe.
- (c) Adjustment: explicitly carved out the date/month fields in the final clause so the paragraph does not claim `reading_date` is re-rendered as an instant; added the naive-vs-offset clause because `parse_dt` accepts both, so a bare "normalised to UTC" would have left offset handling open.

Edit 2 (§2.6, input precision)
- (a) Subject: what happens to a numeric input carrying more decimals than its declared precision (reject vs. round), and the order of range-check vs. rounding.
- (b) Enumerated: read `shape.py` in full (`get_num`, `get_int`, `q`); `grep -rn "get_num(" routes/` — all 40 callsites reviewed. 37 pass `places=`; the only three without are `pulp.py:205-207` (`caustic_kg`, `peroxide_kg`, `surfactant_kg`). Confirmed min/max/exclusive comparisons run on `Decimal(str(v))` before the `places` quantize, so a value that would round into range still fails. Checked family-inherited cases where PRD states no per-field precision: `runs.py:115` `broke_tons` (quantized to 3 = tonnage family) and `parties.py:162` `min_brightness_iso` (field states 1 dp, which is narrower than the "quality index" family's 2 dp). Verified `shape.q(124.55, 1) == 124.6` by running it.
- (c) Adjustments: (i) added "or, where the field itself states none, inherited from the families just listed" so `broke_tons` is covered by the 3-dp tonnage family while the field-level statement wins for `brightness_iso`/`min_brightness_iso` (1 dp) over the 2-dp quality-index family; (ii) stated the range check runs "against the value exactly as supplied" and the rounding after it, matching `get_num`'s order rather than leaving it open; (iii) named the three deink-chemistry charges as the explicit exception rather than writing a universal claim that would have mis-described `pulp.py:205-207`.

Edit 3 (§3.3, effective yield)
- (a) Subject: whether `contamination_pct` is floored to a whole number before the 1.8-per-point penalty.
- (b) Enumerated: `grep -rn "CONTAMINATION_YIELD_PENALTY\|YIELD_FLOOR\|nominal_yield_pct\|pulp_yield_provisional" --include=*.py` over the whole implementation. Exactly one computation path: `calc.py:99-111`, called only from `routes/pulp.py:143` on the pulper charge. `nominal_yield_pct` otherwise appears only as a grade input (`parties.py:92`). Confirmed the floor is applied to the effective yield (45.00), not to contamination, and that per-line contributions are quantized to 3 dp before summing — matching the untouched surrounding prose.
- (c) Adjustment: kept the change inside the existing sentence and phrased the clarification as a negative ("never truncated to a whole number first") rather than restating the formula, so the sentence's existing pinned rounding order and yield floor are unchanged.

## Step 9: Complete PRD — 2026-09-01T02:25:00.000Z

All five pending pins plus three further ones found in a final sweep are applied. `PRD_COMPLETED.md` is complete.

Files:
- Source: `workspace/PRD_FINALIZED.md` — 482 lines, 114,472 chars
- Output: `workspace/PRD_COMPLETED.md` — 482 lines, 126,177 chars (+11,705 chars, ±0 lines)

Line count is unchanged because every edit is an in-paragraph insert or in-sentence revision: 44 distinct PRD lines touched, no new paragraphs, no new sections, no reordering.

Counts:
- 50 ambiguity-pins (PRD was silent; minimal prose inserted)
- 5 mismatch-revisions (PRD asserted something the implementation does not do)
- 55 pins total across 44 lines

Verification sweeps run at the end:
- Every `shape.get_*` request field name in `implementation/` appears in PRD_COMPLETED (0 missing).
- Every persisted/response row key in `implementation/` appears in PRD_COMPLETED (0 missing; the 13 apparent misses are `calc.py` internal return-dict keys and a stray `results.3.json` artifact).
- Error codes: 71 in PRD, 71 in `errors.py`, both directions empty — exact set match. (This caught one invented code, `ERR_NO_DOWNGRADE_TARGET`, corrected to the actual `ERR_DISPOSITION_NOT_PERMITTED`.)
- No `recompute_*` helper mutates a row that is not subsequently `store.touch`ed, so no unpinned version-bump behaviour remains.

Changes:
- §2.1 — insert — ambiguity — scoped listings narrow silently (rows dropped before `total_count` and paging, never a 403); the roll-set list narrows for a `Customer` on `allocated_order_id`; single-resource reads of a roll set/run/spec apply no narrowing — `routes/rolls.py:71`, `common.py:100`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` plus twenty characters from uppercase letters and digits — `response.py:13`
- §2.3 — revise — ambiguity — `limit`/`offset` parse as optionally-signed digit strings only; a decimal point is `ERR_INVALID_PAGINATION`, not truncation — `shape.py:47`
- §2.3 — revise — ambiguity — `created_at` ties break on insertion order — `store.py:75`
- §2.5 — revise — mismatch — version check runs after the from-state check on the five order/machine ops and before it on the two purchase-order ops — `routes/fiber.py:88`, `routes/orders.py:87`
- §2.5 — revise — ambiguity — a stray `expected_*_version` key on any other endpoint is `ERR_VALIDATION`, ahead of all other body checks — `shape.py:199`
- §2.8 — revise — mismatch — global order no longer claims version-before-from-state; defers to §2.5 — `shape.py:199`, `routes/fiber.py:88`
- §3.1 — insert — ambiguity — supplier registration: `name` 1–120, `freight_per_ton` >= 0 at 2dp; opens `QUALIFIED`, strike count 0, `probation_entered_at` null, all server-assigned — `routes/parties.py:72`
- §3.1 — insert — ambiguity — `downgrade_target_grade_code` is stored unresolved; an unresolvable fallback behaves as null — `routes/parties.py:96`, `routes/fiber.py:280`
- §3.1 — insert — ambiguity — PO creation resolves `supplier_id` then `fiber_grade_code`, then rejects a `SUSPENDED` supplier — `routes/fiber.py:35`
- §3.1 — revise — ambiguity — a `SUSPENDED` supplier confirming gets `ERR_SUPPLIER_NOT_QUALIFIED`, not `ERR_SUPPLIER_SUSPENDED` — `routes/fiber.py:146`
- §3.2 — insert — ambiguity — sublot field ranges; `gross_tons` need not exceed `tare_tons` — `routes/fiber.py:175`
- §3.2 — insert — ambiguity — receipt creation imposes no PO state gate — `routes/fiber.py:201`
- §3.2 — insert — ambiguity — ACCEPT tests contamination first, then `ERR_PURCHASE_ORDER_INVALID_STATE` — `routes/fiber.py:283`
- §3.2 — revise — ambiguity — the DOWNGRADE lot copies `receipt_id`, `contamination_pct`, `tons_consumed` 0 and `tons_available` exactly as on acceptance — `routes/fiber.py:249`
- §3.2 — revise — mismatch — suspension hop four only returns orders reading `SCHEDULED`/`IN_PRODUCTION` and clears `scheduled_run_id` — `common.py:314`
- §3.2 — revise — mismatch — lot `tons_consumed` counts only reserved (charged, non-cancelled) batches, not every non-cancelled one — `common.py:120`
- §3.2 — revise — ambiguity — `QUARANTINED` is sticky; recomputation never restores `AVAILABLE`/`DEPLETED` — `common.py:130`
- §3.3 — revise — ambiguity — `tons_charged` of <= 0 is `ERR_VALIDATION` — `routes/pulp.py:45`
- §3.3 — insert — ambiguity — batch creation resolves spec then lots; no lot status or tonnage check until charging — `routes/pulp.py:39`
- §3.3 — revise — ambiguity — the `PULP_REJECT` row is appended even at 0.000 — `routes/pulp.py:178`
- §3.3 — revise — ambiguity — approving a deink-required product yields `ERR_PULP_BATCH_INVALID_STATE`, not `ERR_DEINK_PULP_REQUIRED` — `routes/pulp.py:260`
- §3.3 — insert — ambiguity — deink entry order is status -> pass-limit -> `DIP_LINE`, so an exhausted held batch off-line reports `ERR_DEINK_PASS_LIMIT` — `routes/pulp.py:208`
- §3.3 — revise — ambiguity — the three chemical charges are optional, default 0, never negative — `routes/pulp.py:203`
- §3.3 — insert — ambiguity — the deink sludge total excludes only rows that are themselves reversals, so a `REPULPED` original still deducts — `routes/pulp.py:182`
- §3.3 — insert — ambiguity — a null `min_brightness_iso` always passes — `routes/pulp.py:240`
- §3.3 — insert — ambiguity — divert hop two only returns orders reading `SCHEDULED`/`IN_PRODUCTION` — `common.py:314`
- §3.4 — revise — ambiguity — acting on a `DOWN` machine is `ERR_RUN_INVALID_STATE` (409) — `routes/machines.py:153`, `routes/runs.py:55`
- §3.4 — insert — ambiguity — run-scheduling check order: window, spec, batch, version, `DOWN`, product match, occupancy — `routes/machines.py:134`
- §3.4 — insert — ambiguity — scheduling gates neither batch status nor `available_tons`; both are start-time checks — `routes/machines.py:134`, `routes/runs.py:48`
- §3.4 — revise — ambiguity — grade change resolves `from_run_id` then `to_run_id`, both before the version check; neither run's status is examined — `routes/machines.py:58`
- §3.4 — revise — ambiguity — the window gap is truncated downward to whole minutes — `routes/machines.py:76`
- §3.5 — revise — mismatch — the inbound grade-change gate sits second (before the permit gate) and `PLANNED` and `VOIDED` alike block the start — `routes/runs.py:58`
- §3.5 — revise — ambiguity — reel field ranges: `reel_no` >= 1 integer, `reel_tons` > 0, measurements >= 0 unbounded — `routes/runs.py:91`
- §3.5 — revise — ambiguity — `broke_tons` optional, >= 0, default 0 — `routes/runs.py:115`
- §3.5 — revise — ambiguity — a refused certification discards the computed index; `certified_quality_index` stays null — `routes/runs.py:172`
- §3.5 — revise — ambiguity — the rework cascade is not gated by the two-rewind limit — `routes/runs.py:220`
- §3.5 — revise — ambiguity — resubmitting with a rewind still in flight is `ERR_ROLL_SET_INVALID_STATE` (409) — `routes/runs.py:239`
- §3.5 — revise — ambiguity — the abort cascade only touches orders reading `SCHEDULED`/`IN_PRODUCTION` — `common.py:314`
- §3.6 — insert — ambiguity — order-creation order: ownership, shape, spec resolution, envelope, then `ACTIVE` — so both faults report `ERR_CUSTOMER_SPEC_VIOLATION` — `routes/orders.py:19`
- §3.6 — revise — ambiguity — schedule order: `run_id` resolves first (`ERR_LINK_TARGET_NOT_FOUND`), run not `SCHEDULED` is `ERR_RUN_INVALID_STATE`, then the version check — `routes/orders.py:87`
- §3.6 — revise — ambiguity — cascade deschedules are not limit-gated and increment past 3 — `common.py:314`
- §3.6 — insert — ambiguity — `wrap_spec` is optional at winding and reads null when omitted — `routes/rolls.py:23`
- §3.6 — insert — ambiguity — allocation resolves `order_id` first — `routes/rolls.py:104`
- §3.6 — revise — ambiguity — a non-`ALLOCATED` set at shipping is `ERR_ROLL_SET_INVALID_STATE` — `routes/orders.py:136`
- §3.6 — revise — ambiguity — a missing `scheduled_run_id` at shipping also reports `ERR_RUN_NOT_CERTIFIED` — `routes/orders.py:136`
- §3.6 — insert — ambiguity — short-close recomputes `shipped_tons`, leaves `allocated_tons` untouched, hence the frozen shortfall equals the recomputed one — `routes/orders.py:174`, `common.py:265`
- §3.6 — revise — ambiguity — rewind-complete checks tonnage before the deckle re-check — `routes/rolls.py:177`
- §3.7 — revise — ambiguity — a permit opens `posture_changed_at` null; "the" permit is the earliest-created row, while the `LAND_APPLICATION` bar fires on any `EXCEEDANCE` permit — `routes/env.py:23`, `routes/env.py:114`
- §3.7 — revise — ambiguity — the duplicate-date test precedes the future-date test — `routes/env.py:53`
- §3.7 — insert — ambiguity — manifest prepare resolves rows, then applies the bar, then tests number uniqueness — `routes/env.py:122`
- §3.7 — revise — ambiguity — the reversal row copies `source_kind`/`source_ref_id`, opens `PENDING` with null `manifest_id`, and enters no disposition split — `routes/env.py:271`
- §3.8 — insert — ambiguity — `consumer_ref_id` is mandatory and must resolve for `PAPER_MACHINE`, ignored and stored null otherwise, checked before the window checks — `routes/steam.py:35`
- §3.8 — revise — ambiguity — curtailment candidates tie-break on insertion order — `routes/steam.py:29`
- §3.8 — revise — ambiguity — release leaves `cogen_credit_usd` as struck — `routes/steam.py:97`

Sections requiring no change: §4 (endpoint/role table matches `app.py` routing and every `auth.require_roles(...)`), §5 (71-code catalogue matches `errors.STATUS` exactly), §3.9 (filter inventory matches every `common.filtered(...)` call site).

## Pipeline complete — 2026-09-01T02:26:00.000Z

All nine steps finished. Final orchestrator-run 8-round parallel stability sweep: 180/180 passed, 0 failed, 0 errors in every round (`workspace/implementation/results.{1..8}.json`).
