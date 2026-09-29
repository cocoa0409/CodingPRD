# Worklog — task_2260_cutting_tool_carbide_insert_manufacturing

## Step 1: Create Task Directory — 2026-09-01T00:00:00.000Z

Created `tasks/task_2260_cutting_tool_carbide_insert_manufacturing/` and `workspace/` (directory name pre-allocated by the invoker; no index scan performed).

## Step 2: Generate Scaffold — 2026-09-01T01:00:00.000Z

Complete. All three artifacts are written and the linter is clean.

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
  §1.5 endpoints declared:    73
  §1.1 entities declared:     13
  §1.8 instances scanned:     19
  §1.9 instances scanned:     57
  Calls scanned (§1.8+§1.9):  995

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2260_cutting_tool_carbide_insert_manufacturing/`):

**SCAFFOLD.yaml** (§1.0–§1.7, no design keys) — domain `cutting-tool-carbide-manufacturing`, prefix `/tooling`; 13 entities, 12 state machines + 2 OCC concurrency rules, 13 calculations, 43 ordered validations, 73 endpoints, 66 errors, 7 roles (segregation-of-duties role model, graph topology, parallel state shape).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** — 9 rule_ids / 19 instances (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant).

**SCAFFOLD_CORNER_DESIGN.yaml** — all 9 §1.9 sections, 72 instances (57 full test recipes + 15 `excluded_because` stubs): entities 11, state_machines 15, calculations 8, validations 16, endpoints 8, errors 4, rbac 4, cross_cutting_complexity_layers 5, consistency_model 1. Every one of the 66 error codes is referenced by at least one instance; each stub cites a real §1.8 instance name and carries `grounds` with no `test_recipe`.

Key work in this final pass: finished the validations section (batch-unit aggregate, 42-before-43 credit gating, per-stage reconditioning conditions), then authored the endpoints, errors, rbac, cross_cutting_complexity_layers and consistency_model sections with hand-computed literals (speeds/feeds 238 / 0.280 / 3.00 / LOW and 100 under WEAK+DRY; lead times 28 vs 8; tool_life_index 21.7 from ratings 20.0 and 23.3; composite 1.20; rebate 1800 on 20.0 % extension).

Two defects found and fixed in SCAFFOLD.yaml / the designs while writing them:
- `ToolOrder.order_class` was declared `source: input` although `POST /tooling/tool-orders` never accepts it and copies it from the product — changed to `source: system`.
- `ToolProduct.supply_status` defaults to `UNAVAILABLE`, so priority-17 `ERR_PRODUCT_NOT_ORDERABLE` would have blocked several order-creating corner recipes on unreleased products; those setups now call `set-supply-status MAKE_TO_ORDER` first (this is exactly the §1.5 audit the spec asks §1.9 to perform).

## Step 3: Copy Shared Files — 2026-09-01T01:05:00.000Z

Copied `INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T01:25:00.000Z

The PRD is complete and all audits pass.

**Output:** `workspace/PRD.md` — 509 lines.

**Structure**
- §1 Introduction (3 paragraphs: shop-floor pain point, scope under `/tooling`, two structural commitments — evidence pinned not referenced, producer ≠ acceptor)
- §2 Global Specifications, 12 subsections: 2.1 identity/RBAC (7 roles), 2.2 response structure (pasted byte-verbatim from `section-2.2-response-structure.md`), 2.3 pagination, 2.4 common resource properties, 2.5 logical shop clock, 2.6 parallel status dimensions, 2.7 revision pinning + four-hop restriction cascade, 2.8 reference resolution order, 2.9 rounding discipline, 2.10 OCC, 2.11 the full ordered 1–43 evaluation ladder, 2.12 segregation of duties
- §3 Business Logic, 9 subsections: grade/powder route, geometry, coating + chamber loading, grinding wheels/cells/tolerance, products + lead time + speeds-and-feeds, machining trials + wear curve, dossier decisions, customers/credit/orders, reconditioning
- §4 endpoint table: 73 rows, exactly 4 columns
- §5 error catalogue: 66 rows, exactly 2 columns

**Coverage audit (reports kept out of the PRD, as required)**
- Contract 1 — Field-name coverage: **PASS**. 163 required identifiers (134 entity fields, 99 request-body names, 30 query params, 12 path params, plus nested `material`/`thickness_um`/`minutes`/`vb_um`, the computed-read outputs `recommended_vc`/`recommended_fz`/`recommended_ap`/`confidence_class`, and `current_utc`); 0 missing, all present in backticks. Two independent passes.
- Contract 2 — Rule coverage: **PASS**. All 66 error IDs appear in §1–§3 prose (not only in the §5 table); all 43 validation priorities represented with their scopes; both OCC rules; all 12 state machines with every declared transition and its side effects (an explicit-arrow pass was added for 14 transitions that were initially only described implicitly — grade `QUALIFIED`→`DRAFT`, run `COMPLETED`→`VOIDED`, dossier `SUBMITTED`→`APPROVED`, order ship/cancel set, job return/scrap, customer close); all 13 calculations with constants literal. Two flagged constants are false positives: `VOLUME_TIERS` is expressed as its component tiers (500/0.12, 100/0.07, 25/0.03) and `THICKNESS_TOLERANCE_FRACTION` as "15 percent".
- Contract 3 — §3 path purity: **PASS**. Zero backticked tokens in §3 begin with `/`, are a bare HTTP method, or combine method+path; every operation is named by state transition, role+action, or capability.
- Other checks: §2.2 byte-verbatim confirmed; only 2 code blocks in the document, both inside §2.2 (no pseudocode anywhere); no fuzzy quantifiers.

**Scaffold contradictions resolved deterministically** (documented choices, each following the more specific or more frequently stated source): grade `revise` lands at `DRAFT`; quarantine hop keys on `passed_trial_count < required_trial_count`; quarantined batch's observable `remaining_units` is 0; coating `layers` capped at 5; product pins captured at creation *and* refreshed at enter-qualification; grade retirement/product withdrawal/customer closure all blocked by open demand; order confirmation open to both `ApplicationEngineer` and `ProductionPlanner` from `SUBMITTED` or `ENGINEERING_REVIEW`; refurbish with insufficient wheel life → `ERR_WHEEL_REQUIRES_DRESSING`; scrap refund cannot lift a credit hold; `DRAFT`→`CANCELLED` bumps only the order's version. One self-caught defect was repaired: an earlier draft of ladder item 13 cited a non-existent `ERR_INVALID_RECIPE_STATE`.

Note: the shared `/tmp` table files from the earlier session had been overwritten by a different task's output (`/uro` prefix); both tables were regenerated directly from this scaffold into a task-local temp directory before assembly.

## Step 5: Generate Unit Tests — 2026-09-01T03:00:00.000Z

Generation is complete. Final state of the deliverables:

## Files written

**`test_helpers/` (10 files, Stage 1)** — `__init__.py`, `api_client.py` (77 endpoint methods), `api_errors.py` (`ApiErrorId`), `types.py`, `constants.py` (identity constants `op-1`, `op-2`, `ae-7`, `qa-3`), `test_users.py` (role headers + malformed-header builders), `factories.py` (49 payload builders), `fixtures.py` (29 composite state builders across the insert spine and the end-mill spine), `assertions.py` (21 shape/invariant helpers), plus `test_suite/conftest.py`.

**`test_suite/` (16 test modules, 153 tests, every test carrying exactly one `Design:` tag)**

| Queue A — Difficulty (48) | Queue B — Corner (105) |
|---|---|
| `test_01_dual_life_figures.py` 5 | `test_10_entities.py` 11 |
| `test_02_pricing_lead_time_and_cutting_envelope.py` 9 | `test_11_state_machines.py` 19 |
| `test_03_parallel_state_dimensions.py` 5 | `test_12_calculations.py` 16 |
| `test_04_transitive_cascades.py` 6 | `test_13_validations.py` 21 |
| `test_05_evaluation_order_conflicts.py` 6 | `test_14_endpoints.py` 8 |
| `test_06_inclusive_boundaries.py` 5 | `test_15_errors.py` 10 |
| `test_07_resource_windows.py` 6 | `test_16_rbac.py` 11 |
| `test_08_conserved_quantities.py` 6 | `test_17_concurrency_and_consistency.py` 9 |

## Coverage audit

`live instances: 76 (corner 57, difficulty 19)` · `stub instances: 15` (never emitted) · `tagged tests: 153 covering 71 instances` · `problems: 0` (no untagged, dual-tagged, mis-placed, stub-pointing or unknown tags). Quote audit: `checked 354 quotes, 0 problems` (every `PRD §x: "…"` is a verbatim substring of `workspace/PRD.md`). pyflakes and `py_compile` clean; no generated file mentions the scaffold or scaffold section numbers.

## Instances skipped (5) — PRD-first filter failures, no placeholders emitted

1. `Difficulty/cross_entity_state_dependency/order_confirm_requires_qualified_grade` — the priority-17 `ERR_PRODUCT_NOT_ORDERABLE` pre-empts the asserted priority-18 `ERR_GRADE_NOT_QUALIFIED`.
2. `Corner/validations/order_confirmation_walks_the_referential_readiness_band` — §3.2's restriction cascade leaves the product `RESTRICTED`, so priority 17 pre-empts all three asserted codes and the chain never recovers.
3. `Corner/endpoints/expedite_flag_is_the_only_difference_between_a_rejected_and_an_accepted_order` — setup needs `set-supply-status MAKE_TO_ORDER` on a `DEVELOPMENT` product, forbidden by §3.5; the pinned figures are legally unreachable.
4. `Corner/endpoints/withdraw_action_cancels_every_open_order_and_locks_the_release_dimension` — same illegal setup, and the asserted cancellation of a `SUBMITTED` order contradicts §3.5 (a `SUBMITTED` order blocks withdrawal with `ERR_OPEN_DEMAND_EXISTS`; only `DRAFT` orders are cancelled).
5. `Corner/cross_cutting_complexity_layers/product_pins_are_refreshed_only_by_an_explicit_repin` — decided this session: §3.5 declares repin only as `RESTRICTED` → `QUALIFICATION`, so under priority 12 the design's repin of a `QUALIFICATION` product would answer `ERR_INVALID_PRODUCT_STATE`, contradicting its asserted `pin_after == 2` and subsequent successful release. The instance's `ERR_PINNED_REVISION_STALE` half and its repin half cannot coexist in any legal scenario, so the whole instance was skipped rather than weakened.

Where a design instance's *setup* was illegal but its claim was PRD-derivable, the setup was rebuilt legally rather than skipped (e.g. the order-OCC and customer-RBAC instances now run on a properly released `RELEASED`/`STOCKED` catalogue insert, with version bumps produced by legal `set-supply-status` moves).

## Step 6: Generate Implementation — 2026-09-01T03:00:00.000Z

Implementation complete and verified.

## Files written

All under `workspace/implementation/` — 28 files (26 Python modules + `requirements.txt` + executable `start.sh`):

- Infrastructure: `app.py`, `db.py`, `errors.py`, `middleware.py`, `response.py`, `validation.py`, `calculations.py`
- `services/`: `__init__.py`, `derive.py` (existence lookups, cascades, aggregate recomputation), `serialize.py` (read-time computed fields)
- `routes/`: `__init__.py` (blueprint registry), `common.py`, `clock.py`, `grades.py`, `batches.py`, `geometries.py`, `recipes.py`, `coating_runs.py`, `wheels.py`, `grinding_runs.py`, `products.py`, `dossiers.py`, `trials.py`, `customers.py`, `orders.py`, `recondition.py`
- `start.sh`: `set -euo pipefail`, `cd $(dirname $0)`, guarded `pip install` (only when Flask is missing, to avoid boot contention across concurrent per-test reboots), then `exec python3 app.py`; honours `PORT` (default 10000), binds `0.0.0.0`.

## Endpoint count

73 endpoints, confirmed by introspecting `app.url_map`: `_clock` 1, carbide-grades 6, powder-blend-batches 6, insert-geometries 5, coating-recipes 4, coating-runs 4, grinding-wheels 4, grinding-runs 5, tool-products 9, qualification-dossiers 6, machining-trials 4, customers 5, tool-orders 7, recondition-jobs 7. All under the `/tooling` prefix; 14 blueprints.

## Constraint compliance

- In-memory only: 13 plain dicts in `db.py` behind one `RLock` (acquired in `before_request`, released in `teardown_request`); no sqlite, no file writes, no `/tmp` cache. The only `json` use is `json.dumps` for responses.
- No seeding: a fresh boot returns `total_count: 0` for all 13 collections (verified programmatically).
- Did not read `test_suite/`, `test_helpers/`, either `SCAFFOLD_*_DESIGN.yaml`, or any sibling task directory.

## Boot verification

Booted from a fresh process four times via `./start.sh` (ports 10731–10734, 10999); each served live traffic. `python3 -m compileall` clean.

Three end-to-end scripts (~190 labelled assertions) run against fresh boots, final state 0 failures:
- Happy path: grade → batch press/sinter (yield/QC) → pilot → geometry release → recipe + coating run validating the recipe → product create (lead time 12, expedite) → enter-qualification pins → 2 trials with wear-curve rating → composite score 1.47 → segregation-of-duties 403 → approve (index 24.6, groups P/M, grade QUALIFIED) → release (RELEASED/STOCKED) → speeds-feeds envelope → order create/submit/confirm/ship (`shipped_at` from the logical clock) → grinding run with cell double-booking and buffer conflicts → recondition intake/inspect/refurbish/return with credit and rebate movements → grade revise cascade (product RESTRICTED + MAKE_TO_ORDER).
- Edge cases: wear-curve validation ordering (fires before the 404), censored trials, insufficient coverage, reject → DEVELOPMENT with null pins, batch quarantine invalidating trials, pagination meta, credit-hold cascade and resume, STOCKED→MAKE_TO_ORDER cascade forcing reconfirmation, open-demand blocks, INSERT not regrindable, insufficient regrind credit.
- Third pass added: duplicate codes, batch stage/unit-count guards, all three SPECIAL derivation failures, min-order-qty, pricing (list 10000 × 0.88 volume discount = 8800/unit, 5,280,000 total for 600), full geometry-revise → repin → re-release loop (repin lands in QUALIFICATION, evidence retained), predecessor chain reuse, scrap refund without lifting a hold, chamber capacity with touching windows allowed, `ERR_WINDOW_IN_PAST`/`ERR_INVALID_WINDOW`, grade retirement cascading products to WITHDRAWN/UNAVAILABLE.

Logical clock confirmed: defaults to `2026-08-01T00:00:00Z` with no wall-clock fallback, drives `window_not_in_past`, `window_not_elapsed` (inclusive at `window_end`) and `shipped_at`; the clock endpoint works with no headers, and rejects `Customer`/unknown roles with 403.

Two notes for the record:
1. `created_at`/`updated_at`/`api_request_timestamp` use real time, not the logical clock. The PRD binds the logical clock only to temporal *rules* and to `shipped_at`; this keeps `updated_at` strictly advancing across mutations. If the generated tests assert that `created_at` equals a repositioned clock instant, this is the single knob to flip (`db.new_row`/`db.touch`).
2. While testing I used `pkill -f app.py`, which may briefly have killed server processes belonging to the concurrently running test-generation harness (many `python3 app.py` processes are alive on this box). They relaunch per test, so it should be self-healing, but a harness run in flight at that moment could show a spurious restart failure.

## Step 7: Run Tests and Iterate — 2026-09-01T04:30:00.000Z

All 8 parallel rounds pass: **153/153** each.

## Summary

**Iterations run:** 3 sweeps (8 parallel rounds each). Round 1: 75/153. Round 2: 149–150/153. Round 3: 153/153 × 8.

**Tests deleted:** none. Every failing test traced to a verbatim PRD sentence and survived the unique-derivability check; all failures were test-artifact bugs plus one PRD-contradicting assertion, so all were repaired rather than removed.

**Fixes applied to `test_helpers/`**

- `factories.py` — `tool_product_payload` and `special_product_payload`: `min_regrind_length_mm` was `12.7`, equal to `nominal_length_mm`. PRD §3.5 states verbatim "`min_regrind_length_mm`, the shortest usable length, greater than 0 and strictly less than `nominal_length_mm`", so the PRD-faithful implementation rejected every insert product with priority-4 `ERR_INVALID_REQUEST` — 62 tests failed in setup. Changed to `12.2`. (The `ERR_PRODUCT_NOT_REGRINDABLE` test that used this product keys off `tool_type == INSERT`, which is an independently sufficient branch of the same PRD sentence, so it still passes.)
- `fixtures.py` — `passed_batch` gained `press_overrides`/`sinter_overrides`, plus a new `small_passed_batch(api, grade_id, units)` builder. Needed because PRD §3.6 caps `units_consumed` at 50, so a 180-unit batch can never be over-drawn by a legal request.
- `api_client.py` — added `ApiClient.reset_session()` (closes the pooled sockets, opens a fresh `requests.Session`). Root cause of the flaky `ConnectionResetError(104)` seen in rounds 2 and 4: the client was a module singleton with one keep-alive session, while `--isolation per-test-server` replaces the server process on the same port before each test, so a pooled socket occasionally pointed at a killed process.

**Fixes applied to `test_suite/`**

- `conftest.py` — `api` fixture changed from session-scoped to function-scoped and now calls `reset_session()`, so each test starts on a fresh connection after the server restart.
- `test_13_validations.py` — the three batch-unit tests (`..._may_not_draw_more_tools_than_the_batch_holds`, `..._may_draw_the_entire_remaining_balance_and_exhaust_the_batch`, `..._an_exhausted_batch_cannot_supply_even_one_tool`) requested `units_consumed` of 200/180, above PRD §3.6's verbatim "at least 1 and at most 50", so priority 4 pre-empted the asserted `ERR_INSUFFICIENT_BATCH_UNITS`. Rebuilt each on a 40-unit `small_passed_batch` with legal draws of 50/40/1. Error-id assertions unchanged.
- `test_10_entities.py` / `test_12_calculations.py` — replaced `recipe["layer_count"] == 2` with `len(recipe["layers"]) == 2`. `layer_count` appears nowhere in PRD.md (computed-field silence); `layers` is a PRD-declared field, so the same business fact is asserted through covered vocabulary.
- `test_10_entities.py` — `test_client_supplied_system_fields_on_a_grade_are_not_honoured` asserted 201 for a body carrying `id`/`version`/`status`/`revision`, which directly contradicts PRD §2.11 item 3: "an unknown field is supplied → `ERR_INVALID_REQUEST`. Applies to every endpoint with a request body." Split into the PRD-faithful pair: the smuggled body → exact `ERR_INVALID_REQUEST`/400, and a clean create → server-minted `id`, `version` 1, `status` `DRAFT`, `revision` 1, ISO-8601 `created_at`.

**Fixes applied to `implementation/`:** none. Every implementation check challenged by a failing test (the `min_regrind < nominal` domain rule, the `units_consumed ≤ 50` cap, the unknown-field rejection) is stated verbatim in PRD.md and was left intact.

Orchestrator verification: `results.{1..8}.json` all report `153 / 153`.

## Step 8: Finalize PRD — 2026-09-01T04:45:00.000Z

Done. One line changed in one section.

## Line counts
- `PRD.md`: 509 lines · `PRD_FINALIZED.md`: 509 lines · **0.0% line delta** (1 line revised in place; 2 diff-lines total)

## Changes
- **§2.11, evaluation-order item 4 (Enum and numeric domain)** — *revise* — (a) added that `min_regrind_length_mm` must be strictly less than the `nominal_length_mm` supplied in the **same product-creation body**, and that violating that relation is reported as a priority-4 domain violation "rather than by any later check"; (b) widened the check's applicability from the closed list of eight endpoints to "every endpoint whose request body declares an enum or numeric field", keeping the original names as an illustrative ("among them") list and adding machining-trial creation/completion, grinding-run completion, reconditioning inspection and reconditioning return; (c) added the worked example that a trial's out-of-band `units_consumed` is rejected here, ahead of item 34. — `implementation/routes/products.py:88-89` (and `routes/trials.py:95`).

## Per-edit pre-edit search log

**Edit A — subject: the `min_regrind_length_mm` < `nominal_length_mm` relation**
- (b) Paths enumerated: `grep -rn "min_regrind\|nominal_length\|REGRINDABLE"` over the whole implementation. Hits: `routes/products.py:84-89` (the only place the relation is validated on input — Decimal compare, `v.bad()` → `ERR_INVALID_REQUEST`, positioned *before* `derive.must_exist` and `derive.require_unique`, i.e. priority 4); `routes/recondition.py:68-72` (intake re-tests the relation on the **persisted** product and reports `ERR_PRODUCT_NOT_REGRINDABLE`); `calculations.py:302-313` (consumes the two lengths for `remaining_regrinds` / `life_extension_pct` / `scrap_recommended`); `services/serialize.py:156-158` (echo only). Confirmed there is no product-update endpoint, so no second write path.
- (c) Adjustment: scoped the new clause to "the `nominal_length_mm` supplied in the same product-creation body" instead of stating it as a global product invariant, so §3.9's `ERR_PRODUCT_NOT_REGRINDABLE` clause is not contradicted or made a competing code for the same request; §3.5 and §3.9 left verbatim.

**Edit B — subject: which endpoints run the priority-4 enum/numeric-domain check**
- (b) Paths enumerated: grepped `v.body(`/`v.no_body()`/`as_int`/`as_number`/`as_enum`/`as_datetime`/`must_exist`/`require_unique` across all 13 files in `routes/` plus `validation.py`. Every body-bearing endpoint parses and range-checks its enums/numerics *before* `derive.must_exist` (checked individually: batches create/press/sinter/quarantine, clock, coating-runs create/complete, customers create/credit-adjustment/close, dossiers create/approve/reject, geometries create/revise, grades create/revise/retire, grinding-runs create/complete/void, orders create/cancel, products create/set-supply-status/withdraw, recipes create/revise, recondition create/inspect/refurbish/return/scrap, trials create/complete, wheels create/dress). Also checked the no-body endpoints (start-pilot, geometry release, dossier submit, order submit/confirm/ship, product enter-qualification/release/repin) — they declare no enum or numeric field, so the wording does not reach them; and `validation.py:105-111` confirms numeric bounds are Decimal-compared, `:87-90` integer bounds.
- (c) Adjustment: used "every endpoint whose request body declares an enum or numeric field — among them …" rather than a new closed list, so (i) endpoints the original list omitted but impl still validates (batch press/sinter, dossier creation's 2–8 `required_trial_count`, wheel creation's 100–100000, grinding-run creation's `planned_units`, set-supply-status, customer creation) are covered without being individually asserted, and (ii) the illustrative phrasing asserts no exclusivity, so the `speeds-feeds` **query-parameter** enum validation (`routes/products.py:328-330`, which also precedes `must_exist`) is neither claimed nor excluded — the same status it had in the original sentence.

**Items deliberately left unpatched** (traced to impl, found already determined or test-only):
- `units_consumed` 1–50 cap, `units_consumed ≤ remaining_units`, exhaustion → `stage` `CONSUMED`: verbatim in §3.6 and matched exactly by `routes/trials.py:95,116,146-148`. Only the *ladder scope* needed pinning (Edit B); the bounds themselves were left verbatim.
- `layer_count`: `services/serialize.py:77-90` emits `layers`, `total_thickness_um`, `revision`, `adhesion_class`, `is_validated` and no `layer_count`; PRD §3.3 already declares exactly that set, so the test was asserting an invented field — no PRD silence to pin.
- Client-supplied `id`/`version`/`status`/`revision` on grade create: `validation.py:36-39` rejects any key outside the endpoint's declared set, which is §2.11 item 3 verbatim; §3.1 and §2.4 already pin the server-minted values the repaired test now asserts.
- `api_client.reset_session()`, function-scoped `api` fixture, `press_overrides`/`sinter_overrides`/`small_passed_batch`: harness-side only, no observable server behavior.

## Step 9: Complete PRD — 2026-09-01T05:10:00.000Z

Measurement and report complete.

## Measurements

| | PRD_FINALIZED.md | PRD_COMPLETED.md | delta |
|---|---|---|---|
| lines | 509 | 514 | +5 |
| chars | 100877 | 122265 | **+21388** |

The +5 lines are one inserted bullet in the §2.2 error-envelope list and one inserted paragraph-continuation in §2.4/§2.9 where an in-paragraph insert was impossible without breaking a bullet list. No new sections; all other 47 changes are strictly in-paragraph.

**Counts: 50 changes across 49 diff hunks — 35 ambiguity-pins, 15 mismatch-revisions.**

## Changes

- §2.1 Caller Identity — revise — mismatch — closed list of scope-checked operations was missing single-customer reads; added that, plus that `Customer` list reads are silently narrowed (server overrides any `customer_id` query param) rather than rejected — `routes/customers.py:60`, `routes/orders.py:136`, `routes/recondition.py:145`
- §2.2 Standard Error Response Format — insert — ambiguity — pinned the four off-catalogue envelope codes: no-route `ERR_NOT_FOUND`/404, bad-method `ERR_NOT_FOUND`/405, unparseable `ERR_INVALID_REQUEST`/400, fault `ERR_INTERNAL`/500 — `app.py:43-60`
- §2.3 Pagination — insert — ambiguity — pinned `ERR_INVALID_REQUEST` for unparseable/out-of-band `limit` and negative `offset`, that both params are validated identically on single reads and the envelope read, and that `created_at` ties break by write order — `validation.py:165`, `routes/orders.py:145`, `db.py:79`
- §2.3 Pagination — revise — ambiguity — pinned `has_more` as `offset + len(page) < total_count`, so an offset past the end yields an empty page with `has_more` false — `response.py:43`
- §2.4 Common Resource Properties — insert — ambiguity — pinned that `created_at`/`updated_at`/`api_request_timestamp` use the real wall clock (logical clock governs only temporal rules and `shipped_at`), and that `updated_at` equals `created_at` at creation — `response.py:17`, `db.py:54,61,74`
- §2.4 Common Resource Properties — insert — ambiguity — enumerated the nine derived-on-read fields that are never stored and do not bump `version`/`updated_at`; pinned code uniqueness as case-sensitive exact-string; pinned free-text fields as string-only with no length rule — `services/derive.py:71,102,110,124,151,239,260`, `derive.py:41`, `validation.py:51`
- §2.5 Logical Shop Clock — insert — ambiguity — pinned `current_utc` as mandatory, `data` holding only that key echoed verbatim (not normalised), and one shared datetime grammar (`Z`/`z`, explicit offset, or naive-as-UTC; whitespace ignored) for `current_utc` and all run windows — `routes/clock.py`, `validation.py:148`
- §2.7 Revision Pinning — insert — ambiguity — pinned that a product's `version` advances only if the cascade restricted it or the lead-time recomputation landed a different value, and that products are walked `created_at` ascending — `services/derive.py:175-190,345,371-375`
- §2.8 Reference Resolution — insert — ambiguity — pinned malformed identifiers as `ERR_INVALID_REQUEST` at rung 3/4 (never not-found) and explicit-`null` optional identifiers as omitted — `validation.py:128`
- §2.8 Reference Resolution — insert — ambiguity — pinned enum filters as case-sensitive `ERR_INVALID_REQUEST` on bad values, identifier filters as opaque strings yielding empty pages, and `is_validated` accepting `true`/`false`/`1`/`0` in any letter case — `validation.py:188,203`, `derive.py:53`
- §2.9 Precision and Rounding — insert — ambiguity — pinned that quoted scales bind only the server's own rounding; the same scales on caller-supplied fields are descriptive, not validation and not rounding — `validation.py:94`
- §2.11 Order of Evaluation — insert — ambiguity — pinned absent/empty/`null` body as the empty object, the nine zero-input action endpoints as accepting no fields at all, and non-object JSON as `ERR_INVALID_REQUEST` — `validation.py:23-46`
- §2.11 Order of Evaluation — insert — ambiguity — pinned the easily-guessed numeric domains: measured magnitudes `>= 0`, `measured_surface_ra_um` strictly `> 0`, expected-version `>= 1`, and the two money fields unbounded in sign — `validation.py:77,94`, `routes/customers.py:30`
- §2.11 item (no-input endpoints) — revise — mismatch — count "six" was wrong for the enumerated set; corrected to seven — `routes/orders.py:154,217,266`
- §2.11 item (no-input endpoints) — revise — mismatch — list omitted order confirmation and order shipping — `routes/orders.py:217,266`
- §2.11 item 20 — revise — mismatch — `ERR_COATING_NOT_VALIDATED` rung scope was incomplete/wrong: it also fires at this rung on enter-qualification and repin, but on refurbish it sits *below* items 14/15 and item 40 — `routes/recondition.py:222-249`, `routes/products.py:169,234`
- §2.11 item 42 — revise — mismatch — account-status rung list omitted order confirmation; pinned that on all three the account is examined last, after every product/engineering gate — `routes/orders.py:183,253-255`
- §3.1 Grade creation — insert — ambiguity — pinned `hardness_hv`/`trs_mpa` as integers vs `co_binder_pct`/`wc_grain_um` fractional-descriptive, and `qualified_product_count` 0 as the derived count — `routes/grades.py:36-70`, `derive.py:71`
- §3.1 Batch creation — insert — ambiguity — pinned the three null metallurgy fields, the invisible capture of the grade's `hardness_hv` target used by sinter QC, and that `ERR_INVALID_GRADE_STATE` is reported only after `batch_code` uniqueness — `routes/batches.py:33-57`
- §3.1 Sintering — insert — ambiguity — pinned hardness as a non-negative integer and that `stage` alone gates the request (`qc_status` is not a precondition) — `routes/batches.py:114-120`
- §3.1 Grade revision — insert — ambiguity — pinned that `revision_note` and the ten sibling note/reason fields are validated but never persisted or echoed (only a dossier's `decision_note` is), and that product versions advance only on actual change — `routes/grades.py:119,142`
- §3.1 Grade retirement — insert — ambiguity — pinned that retirement is *not* the §3.5 withdrawal endpoint: no `DRAFT` order is cancelled, no lead time recomputed, DEVELOPMENT/WITHDRAWN products untouched — `routes/grades.py:147-175`
- §3.1 Batch quarantine — insert — ambiguity — pinned that the counters need no write, that reversion compares recomputed `passed_trial_count` (not `completed_trial_count`) against `required_trial_count`, and that each affected dossier bumps exactly once whether or not it reverted — `routes/batches.py:177-182`
- §3.2 Geometry release — revise — mismatch — PRD had every referencing product's version bump; impl bumps only products whose recomputed lead time actually changed, and release fires none of the four restriction hops — `routes/geometries.py:103-105`, `derive.py:371-375`
- §3.3 Layer stack — insert — ambiguity — pinned that per-entry field faults are judged before the three `ERR_INVALID_LAYER_STACK` conditions and win, and that a non-array `layers` is `ERR_INVALID_REQUEST` — `routes/recipes.py:32-64`
- §3.3 Coating run creation — insert — ambiguity — pinned the two null outcome fields and that `window_start`/`window_end` are echoed as the caller's exact strings, the parsed instants being used only for comparison — `routes/coating_runs.py:74-75`
- §3.3 Coating run completion — insert — ambiguity — pinned `adhesion_class`/`is_validated` as derived-on-read and the recipe's `version` bump as unconditional on completion — `routes/coating_runs.py:126-132`, `derive.py:102,110`
- §3.3 Recipe revision — insert — ambiguity — pinned both fields mandatory and, the recipe having no lifecycle status, no state precondition at all — `routes/recipes.py:117-128`
- §3.4 Grinding run completion — insert — ambiguity — pinned `produced_units`/`scrap_units` as non-negative integers, `measured_diameter_dev_um` as signed and unbounded, all three mandatory, unit equality checked after state/window — `routes/grinding_runs.py:134-136`
- §3.4 Grinding run void — insert — ambiguity — pinned that a `VOIDED` run frees its cell from either prior state while retaining its window and `cell_id` — `routes/grinding_runs.py:24-28`
- §3.5 Product creation — insert — ambiguity — pinned `base_catalog_product_id` as the last reference resolved (grade not-found wins) and self-reference surfacing only as `ERR_PRODUCT_NOT_FOUND` — `routes/products.py:57-94`
- §3.5 Product release — revise — mismatch — the grade's `qualified_product_count` is derived on read, not written; also pinned that the two release gates run in ladder order, so stale pins beat a missing approved dossier — `routes/products.py:189-232`, `derive.py:71`
- §3.5 Supply status — revise — mismatch — `STOCKED`→`MAKE_TO_ORDER` is unconditional (no `release_status` condition), `MAKE_TO_ORDER`→`STOCKED` likewise, a no-op target is refused, and the code is `ERR_INVALID_PRODUCT_STATE` not `ERR_INVALID_TRANSITION` — `routes/products.py:254-289`
- §3.5 Product withdrawal — insert — ambiguity — pinned cancellation order (`created_at` ascending, one version bump each) and that re-withdrawing is `ERR_INVALID_PRODUCT_STATE` checked before the open-demand test — `routes/products.py:293-320`
- §3.5 Speeds-and-feeds envelope — insert — ambiguity — pinned `data` as exactly four keys with no `id`/`version`/timestamps, all three query params mandatory, and no state/dossier precondition for any `release_status` — `routes/products.py:325-354`
- §3.6 Dossier creation — insert — ambiguity — pinned the null decision fields and that `dossier_code` uniqueness precedes the product-state check — `routes/dossiers.py:46-85`
- §3.6 Trial creation — insert — ambiguity — pinned the empty `wear_measurements` array with five null outcome fields, the batch's unconditional version bump, and `trial_code` uniqueness preceding the dossier-state check — `routes/trials.py:74-149`
- §3.6 Trial completion — insert — ambiguity — pinned the dossier's unconditional bump and that on an already-`APPROVED` dossier the product's `tool_life_index`/`qualified_workpiece_groups` are recomputed and its version bumps — `routes/trials.py:206-214`
- §3.7 Dossier rejection — revise — mismatch — PRD said no product figure moves; impl leaves the index fields standing but *does* refresh `engineering_lead_time_days`/`expedite_eligible`; also pinned the 400-char note cap on both branches and that neither score nor coverage gate applies to a rejection — `routes/dossiers.py:176-201`
- §3.8 Customer registration — insert — ambiguity — pinned the opening balance as any integer including negative, and `ACTIVE` even when negative (no credit-hold cascade at registration) — `routes/customers.py:30-41`
- §3.8 Credit adjustment — insert — ambiguity — pinned `ERR_INVALID_CUSTOMER_STATE` for an adjustment against a `CLOSED` account — `routes/customers.py:78-82`
- §3.8 Account closure — insert — ambiguity — pinned re-closing as `ERR_INVALID_CUSTOMER_STATE`, checked before the open-demand test — `routes/customers.py:96-99`
- §3.8 Order creation — insert — ambiguity — pinned the five null pricing/fulfilment fields on a `DRAFT` — `routes/orders.py:102-119`
- §3.8 Order submission — revise — mismatch — prose introduced the account check first; impl evaluates it last at rung 42, after order state and every product gate, and the general orderability test runs on submission as on creation — `routes/orders.py:166-183`
- §3.8 Order confirmation — revise — mismatch — account-status check moved from first to last (after the pin check); also pinned that confirmation bumps only the order, touching neither product nor customer — `routes/orders.py:243-259`
- §3.8 Order shipping — insert — ambiguity — pinned that state and `requires_reconfirmation` share the single code `ERR_INVALID_ORDER_STATE`, that only `supply_status` is re-examined (not `release_status`), and `shipped_at`'s 3-fraction-digit UTC rendering — `routes/orders.py:268-284`
- §3.8 Order cancellation — revise — mismatch — code corrected from `ERR_INVALID_TRANSITION` to `ERR_INVALID_ORDER_STATE`; also pinned that an already-`CANCELLED` order is refused — `routes/orders.py:297-301`
- §3.9 Job intake — insert — ambiguity — pinned the nine null fields plus two false booleans, and that the reservation deduction skips the credit-hold cascade (a balance driven to 0 stays `ACTIVE`) — `routes/recondition.py:112-129`
- §3.9 Refurbishment — revise — mismatch — prose order was not evaluation order: the three wheel conditions precede the regrinds check, and the recoat `ERR_COATING_NOT_VALIDATED` is last of all; also pinned `recoat_applied` default false skipping the coating check — `routes/recondition.py:222-249`
- §4 Endpoint table (grade revise) — revise — mismatch — description said `QUALIFIED`; impl admits `PILOT` or `QUALIFIED` — `routes/grades.py:107-113`

Notes: `ERR_INVALID_TRANSITION` now appears zero times in PRD_COMPLETED.md (it is absent from `implementation/errors.py`, confirming both mentions were mismatches). §5's 66-code table needed no edit — it matches `errors.py:HTTP_STATUS` exactly; the two extra impl codes (`ERR_NOT_FOUND`, `ERR_INTERNAL`) are pinned in §2.2 instead. `implementation/calculations.py` needed no edits: every constant and formula already matched the PRD as written.

## Pipeline complete — 2026-09-01T05:15:00.000Z

`workspace/PRD_COMPLETED.md` exists (514 lines). Final confirmation sweep after Steps 8–9: 8/8 rounds at 153/153.
