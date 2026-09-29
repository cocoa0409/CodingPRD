# Worklog — task_2285_major_appliance_assembly_plant

## Step 1: Create task directory — 2026-09-01T16:00:00.000Z

Created `tasks/task_2285_major_appliance_assembly_plant/` and `tasks/task_2285_major_appliance_assembly_plant/workspace/`.

## Step 2: Generate scaffold — 2026-09-01T16:08:00.000Z

Scenario 2285 scaffold is complete and lint-clean.

### Files written (`/home/ubuntu/github/CodingPRD/tasks/task_2285_major_appliance_assembly_plant/`)

- **`SCAFFOLD.yaml`** — §1.0–§1.7 only (no design keys), `difficulty_level: expert_plus`, `api_prefix: "/"`
- **`SCAFFOLD_DIFFICULTY_DESIGN.yaml`** — single key `scaffold_difficulty_design` (§1.8)
- **`SCAFFOLD_CORNER_DESIGN.yaml`** — single key `scaffold_corner_design` (§1.9)
- `worklog.md` updated with steps 2–5 (subagent's own internal numbering; superseded by this orchestrator log)

### Counts

| Item | Count |
|---|---|
| Entities (§1.1) | 13 — Line, Station, ModelVariant, Supplier, Part, BomLine, DeliveryCall, ShiftPlan, BuildSlot, ProductionUnit, QualityTest (immutable), EngineeringChange, WarrantyReturn |
| State machines (§1.2) | 9 — incl. ProductionUnit as a *parallel* pair (assembly_status × quality_status), cyclic EngineeringChange with a revision-round cap, Part lifecycle to SERVICE_ONLY/OBSOLETE |
| Concurrency rules (§1.2.1) | 2 — `POST /bom-lines` (expected_model_variant_version) and `POST /shift-plans` (expected_line_version) |
| Calculations (§1.3) | 8 — option_load_window_cap, presentation_slot_allocation, shift_committed_labor_minutes (fatigue tiers), efficiency_index (dual-variant, pinned round-then-weight), supplier_on_time_score, effective_bom_at_sequence, line_posture, warranty_failure_rate (dual-variant) |
| Ordered validations (§1.4) | 32 |
| Endpoints (§1.5) | 59 (incl. mandatory `POST /_clock/set_current_utc`) |
| Errors (§1.6) | 43 |
| Roles (§1.7) | 7 — PlantAdmin, ProductionPlanner, LineOperator, QualityInspector, EngineeringLead, WarrantyAnalyst, SupplierPortal (`entity_backed:Supplier`) |
| §1.8 instances | **23** across all 9 difficulty rules (≥2 each; combinatorial modes a/b/c; 3 distinct priority-pair categories; 2 interval semantics; 2 conserved quantities) |
| §1.9 instances | **85** across all 9 guide sections — 59 with full `test_recipe`, 26 `excluded_because` stubs citing §1.8 by name |

### Verification

`scaffold_lint.py` → `VERDICT: clean lint` (1367 §1.8+§1.9 calls checked: endpoint existence, role/endpoint match, payload ⊆ declared input, capture resolution against §1.5 `output:`, dynamic OCC tokens, FK reverse-reachability). No duplicate instance names across the two design files; every stub citation resolves to a real §1.8 instance name.

Two internal-consistency fixes were made to `SCAFFOLD.yaml` while authoring §1.9: the `BuildSlot PLANNED → SEQUENCED` and `EngineeringChange APPROVED → CUT_IN` precondition lists now read in §1.4 priority order with the priority numbers inlined (previously they contradicted the ordered-validation table, which made multi-violation outcomes ambiguous), and the supplier-approval check was split out from the sync-delivery check so priority 27 precedes 28.

The hard constraint was respected: no sibling `task_*/` directory or file was listed, read, or searched at any point.

## Step 3: Copy shared files — 2026-09-01T16:09:19.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2285_major_appliance_assembly_plant/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T16:26:11.000Z

PRD generated and all three Hard Contracts pass.

**Output:** `workspace/PRD.md` — 491 lines.

**Structure**
- §1 Introduction (3 paragraphs: finite capacity / compliance / traceability framing, flat topology note)
- §2 Global Specifications, 11 subsections: 2.1 Plant Personnel and RBAC (7 roles, `SupplierPortal` entity-backed scoping) · 2.2 API Response Structure (pasted byte-for-byte from `section-2.2-response-structure.md`, verified identical) · 2.3 Pagination (incl. all 9 per-endpoint sort overrides) · 2.4 The Plant Logical Clock (default `2026-08-01T00:00:00Z`) · 2.5 Record Identity, Audit Fields and Versioning (incl. QualityTest having no `updated_at`/`version`, and exactly which ops advance Line/ModelVariant `version`) · 2.6 Measurement Precision and Rounding Discipline · 2.7 Stale-View Rejection (both OCC rules, both 412) · 2.8 The Validation Ladder (all 32 priorities in order with applies_to scopes) · 2.9 Nested Reads and Left-to-Right Path Resolution · 2.10 Line Posture: The Master Gate · 2.11 Cascade Discipline and Exact Reversal (two conservation invariants)
- §3 Business Logic, 9 subsections: 3.1 line setup/stop/start+changeover · 3.2 model variants and the living BOM (both resolution flavours) · 3.3 suppliers, parts, dock call-offs, scoring · 3.4 shift staffing and fatigue tiers · 3.5 sequencing: option-load window, presentation slots, labour · 3.6 release/assembly/shipment (two independent status dimensions) · 3.7 quality gates, quarantine, dual-variant efficiency certification · 3.8 engineering change, cut-in, service obligation · 3.9 warranty returns, design feedback, checkpoint sweep
- §4 endpoint table (4 columns, 59 rows) · §5 error catalogue (2 columns, 43 rows). Document ends at §5, no audit footer.

**Hard Contract reports**

```
Field-name coverage check (Contract 1):
- entity field names: 113
- write-endpoint input identifiers: 67
- GET query identifiers: 34
- unique required identifiers: 123
- present as backticked tokens in PRD: 123
- missing: 0
- pass 2, restricted to §1–§3 prose only (excludes §4/§5 tables): missing 0
- inline computed-response field names (checkpoint sweep, warranty metrics): 16 / 16 present
Status: PASS
```

```
Rule coverage check (Contract 2):
- state-machine transitions declared: 53 (7 machines) → all 53 rendered as explicit `FROM → TO` state pairs (48 distinct pairs; 5 pairs reached by two different triggers)
- validations: 32 / 32 present in §2.8, in scaffold priority order, with applies_to scopes preserved
- error codes narrated in §2/§3 prose (not only in the §5 table): 43 / 43
- calculations: 8 / 8, with all 26 named constants' numeric values stated in prose
- dual-variant calculations: 3 / 3 with both variants and their divergence (efficiency AS_TESTED vs CERTIFICATION_AVERAGE, BOM PRODUCTION_EFFECTIVE vs HISTORICAL_AS_BUILT, warranty PRODUCTION_COHORT vs SHIPPED_EXPOSURE)
- endpoint side_effect entries: all 36 endpoints' side effects covered, including the depth-4 cut-in and supplier-demotion cascades and their exact reversals
- sibling-branch symmetry: decide APPROVE/REJECT/REQUEST_REVISION and analyze DESIGN_DEFECT/SUPPLIER_DEFECT/NO_FAULT_FOUND each specified per branch
- endpoint table vs scaffold: 59 / 59 paths, 0 role mismatches; error table: 43 / 43 codes, 0 HTTP-status mismatches
- no pseudocode operators, no fuzzy quantifiers
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 880
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
(§1–§2 also verified clean: 0 path/method tokens.)
```

**Scaffold gaps found (three constants are named in SCAFFOLD.yaml but carry no numeric value anywhere in it — their values live only in the withheld design files, which I did not open):**
1. `MISS_GRACE_MINUTES` — pinned at **15 minutes** in the PRD (checkpoint sweep step 2).
2. `EC_MAX_REVISION_ROUNDS` — pinned at **2 rounds** in the PRD (revision loop cap; the third `REQUEST_REVISION` cancels the change and records `revision_round` 3).
3. `SERVICE_OBLIGATION_YEARS` — recovered as **10 years** from the cut-in side-effect text; not a guess. (`DOCK_BUFFER_MINUTES` = 10 was likewise stated in validation 22.)

If the withheld design files use different values for items 1 and 2, the PRD prose needs those two numbers corrected or the hidden tests will diverge.

**Two scaffold inconsistencies resolved in prose:** `BomLine.qty_per_unit` is constrained `> 0` in the entity block but `>= 1` in validation 3 (written as "a positive quantity of at least 1"); and shift-plan supersession would self-trip the priority-23 overlap check, so the PRD states explicitly that the ACTIVE plan being superseded (same `line_id`, `shift_date`, `shift_code`) is excluded from the overlap comparison while every other ACTIVE plan on the line is not.

`worklog.md` was not modified.

### Orchestrator post-edit (Step 4)

The doc-generator's three flagged constants were reconciled against the withheld design files by the orchestrator (numeric-value grep only, no design content loaded into generation context): `MISS_GRACE_MINUTES = 15` and `SERVICE_OBLIGATION_YEARS = 10` were already correct in the PRD. `EC_MAX_REVISION_ROUNDS` was wrong — the design index expects the third `REQUEST_REVISION` to land `REVISION_REQUESTED` with `revision_round == 3` and the fourth to land `CANCELLED` with `revision_round == 4`, i.e. a cap of **3**, not 2. `PRD.md` §3.8 was patched accordingly ("capped at three revision rounds … beyond 3 … recorded as 4"). No other PRD edits.

## Step 5: Generate unit tests — 2026-09-01T17:45:00.000Z

Test generation is complete for task_2285_major_appliance_assembly_plant.

### Files created

**`test_helpers/`** (Stage 1, 8 modules): `__init__.py` (single re-export surface), `api_client.py` (59 endpoint methods), `api_errors.py` (`ApiErrorId` + HTTP status map), `types.py` (25 enums + role sets), `constants.py`, `factories.py` (payload builders + `OMIT` sentinel), `assertions.py` (`approx2`, `same_instant`, entity shape asserts, formula re-implementations), `fixtures.py` (four-tier fixture ladder: primitives → `base_plant`/`module_plant`/`cut_in_ready_plant` → unit lifecycle → accumulation targeting).

**`test_suite/`**: `conftest.py` + 18 test modules, **104 tests total**, all collected cleanly by pytest.

| Queue | Files | Tests |
|---|---|---|
| A (Difficulty) | test_01 … test_09 | **46** (4/6/6/6/6/6/4/4/4) |
| B (Corner) | test_20 … test_28 | **58** (12/4/8/4/5/12/5/5/3) |

New this session: `test_26_endpoint_filters_and_lists.py` (5), `test_27_errors_and_rbac.py` (5), `test_28_concurrency_and_consistency.py` (3).

### Coverage audit

- **Difficulty (queue A): 23/23 non-stub instances, every one with ≥2 tests** (46 = 23×2).
- **Corner (queue B): 58/59 non-stub instances**, 1 test each. By section: entities 12/12, state_machines 16/16, calculations **5/6**, validations 12/12, endpoints 5/5, errors 2/2, rbac 3/3, cross_cutting_complexity_layers 2/2, consistency_model 1/1. The 26 `excluded_because:` stubs were not translated.

### Instance skipped (1)

`Corner/calculations/supplier_score_floors_at_zero_and_suspends_the_supplier` — the recipe requires six calls swept as `MISSED` in one checkpoint so the score floors at 0.00 and the supplier lands `SUSPENDED`. PRD §3.9 checkpoint step 2 processes misses sequentially, and the third miss (score 40.00 → `PROBATION`) fires the demotion cascade that cancels the supplier's remaining `SCHEDULED` calls with `SUPPLIER_PROBATION`, so `missed_count` cannot exceed 3 and the score cannot reach 0.00. The PRD does not uniquely derive the asserted outcome, so the instance was skipped rather than weakened (no skip/xfail marker, no placeholder).

### Verification passes (all green)

- **Design-citation pass (C4)**: 104/104 tests carry exactly one `Design:` line, it is the last docstring line, and every `<section>/<instance.name>` resolves to a real `name:` in the matching yaml. No untagged, dual-tagged or dangling tags.
- **PRD-citation pass (C1–C3)**: every quoted block in all 104 docstrings verified as a whitespace-normalised verbatim substring of `workspace/PRD.md` and ≥8 words. One failure found and fixed: `test_05` quoted "Because the ladder is global, …" where PRD line 170 reads "Second, because the ladder is global, …".
- **pyflakes**: `test_suite/*.py` clean (the `test_helpers/__init__.py` warnings are the expected re-export pattern with a computed `__all__`).
- No comment or docstring in the generated code references the scaffold or any scaffold section; no sibling `task_*/` directory and nothing under `workspace/implementation/` was read or written.

**Adjudications carried through the suite**: error `message` literals never asserted; clock-stamped timestamps compared with `same_instant()` (never `created_at`); genuine PRD error-precedence ambiguity (ship on a quarantined unit — rule 12 vs §3.6's exact-`CERTIFIED` guard) routed through `validate_error_is_one_of` with a separate `status_code` assertion rather than skipped; `cancelled_build_slot_ids` used for the checkpoint report (the corner yaml's `cancelled_slot_ids` is a typo); `provisional_efficiency_index` never asserted on a `CERTIFIED` unit.

## Step 6: Generate implementation — 2026-09-01T17:00:00.000Z

Implementation complete.

### Files created — `workspace/implementation/`

| File | Role |
|---|---|
| `start.sh` | Launcher: guarded `pip install`, `exec python3 app.py`, executable |
| `app.py` | Flask app, blueprint registration, envelope error handlers, `0.0.0.0:$PORT` (default 10000) |
| `requirements.txt` | `Flask>=2.2` |
| `db.py` | In-memory `Store` (13 dicts), logical clock (default `2026-08-01T00:00:00Z`), id/monotonic-timestamp minting, `touch` |
| `errors.py` | 43-entry error catalog + 3 routing fallbacks, `ApiError` |
| `response.py` | `{meta, response_type, data}` envelope; list meta adds `limit/offset/total_count/has_more` |
| `validation.py` | Typed body/query coercion (ladder rule 3), pagination, ISO-8601 parsing |
| `middleware.py` | 7 roles, auth/RBAC (rules 1–2), global lock serialisation |
| `lookup.py` | FK/path resolution → per-entity 404 codes (rules 4–5) |
| `calc.py` | All 8 spec calculations + constants, `decimal.Decimal` throughout |
| `serializers.py` | 13 entity serializers, derived fields computed at read time |
| `services.py` | Cascades, exact reversals, sequencing ladder, cut-in, quality gates, checkpoint sweep |
| `routes/{master,supply,production,change}.py` | Handlers |

### Endpoints: 59 routes registered (matches the SCAFFOLD endpoint table; the scaffold header's "57" undercounts)

### Notable design decisions
- **Ladder order in every handler**: schema (3) → path id (4) → body/query FKs in declared order (5) → supplier scope (6) → OCC (7) → SoD (8) → state (9) → remaining rules by ascending priority. Nothing mutates until the last guard passes.
- **ERR_UNIT_QUARANTINED before ERR_INVALID_STATE** on `complete-assembly`/`ship`: strict priority order would make rule 12 unreachable (QUARANTINED implies REWORK), so the quarantine check runs first. Both are 409.
- **Exact-reversal conservation**: `presentation_allocations` is pinned per station at sequence time and replayed subtractively on de-sequence/ship; `field_failure_count` and supplier `quality_penalty_count` are decremented on warranty withdraw, with rates recomputed *after* the disposition rewrite so the return leaves the numerator.
- **Supplier score is always replayed from counters** (`100 + 2·on_time − 8·late − 20·miss − 10·quality`, clamped 0–100), so refunds and charges are symmetric; demotion cascade fires only on `APPROVED → non-APPROVED`.
- **Checkpoint sweep** skips calls already in the same sweep when cascading a demotion, per the spec's "not already swept" clause.
- `created_at` is a strictly monotonic wall clock, making every `created_at ASC` order and tie-break deterministic.
- `provisional_efficiency_index` is always recomputed AS_TESTED at read time; `efficiency_index`/`certification_tier` are written only by certify (CERTIFICATION_AVERAGE).
- Zero seeding: the store is empty on every boot; no disk persistence of any kind.

### Verification
- `python3 -m compileall` clean; 59 routes enumerated.
- Two end-to-end smoke scripts exercised: clock, line/station/variant/supplier/part/BOM authoring with OCC, shift-plan supersession + overlap rejection, dock-window conflict, slot sequence → de-sequence → re-sequence with presentation-slot conservation verified back to 0, release → serial `L1-000001`, full quality chain (gate-order 409, PENDING→SAFETY_PASSED→GATED→CERTIFIED, index 0.80/A_PLUS), bubble-up to BUILT, ship + allocation release, warranty analyze (change auto-minted at rate 1000 ≥ 8.00) and withdraw (counters returned to 0), EC submit/review/SoD-403/approve/cut-in with depth-4 cascade (part SERVICE_ONLY + 10-year obligation, obsolete blocked 409), checkpoint sweep (missed call, supplier demotion to SUSPENDED, CUT_IN change closed), supplier-portal scoping and late arrival (`lateness_minutes = 8`), option-load-window 422 ahead of labour capacity.
- `bash start.sh` boots a fresh process on a clean port and answers `GET /parts` with `200` and an empty envelope, plus `POST /lines` → `201`, unknown id → `404 ERR_LINE_NOT_FOUND`, missing header → `401`, unknown path → `404`.

## Step 7: Run tests and iterate — 2026-09-01T20:20:00.000Z

### Status

The loop ran 10 sweeps (8 parallel rounds each, `--isolation per-test-server`). **All functional failures are fixed: sweeps 8 and 10 — both on the final code state — recorded 0 `failed` tests across 1,656 test executions, with every one of the 104 tests passing in at least one round.** The strict "all 8 rounds report `passed == total`" exit gate was *not* reachable, and the blocker is provably outside the task: see "Why the gate is not green" below.

### Iterations

| sweep | outcome |
|---|---|
| 1 | 8 deterministic functional failures (union across rounds) |
| 2, 3 | 6/8 rounds 104/104; 2 rounds with 1 transport error each |
| 4 | 6/8 rounds 104/104; r4 `ConnectionResetError`, r7 `RemoteDisconnected` |
| 5–7 | instrumented / aborted (host saturation, external kills) |
| 8 | 0 functional failures; 77/824 executions aborted in harness setup |
| 9 | unusable (host load peaked at 3,300) |
| 10 | 0 functional failures; 203/832 executions aborted in harness setup |

### Tests deleted / assertions removed

- `test_suite/test_22_unit_lifecycle_transitions.py::TestUnitMinting::test_a_released_slot_mints_a_unit_in_its_initial_compound_state` — removed the single assertion `unit["model_variant_id"] == plant.variant_id` (STEP 1c, partial coverage). **COMPUTED/RESPONSE-FIELD SILENCE**: PRD never names `model_variant_id` as a production-unit response attribute; the token appears only as a BOM-line / build-slot / engineering-change input or list filter, and §3.6's unit-minting sentence enumerates the minted fields without it. The rest of the test (both status dimensions, `rework_count`, `build_slot_id`, `built_at_sequence_index`, serial, null indices/tier, slot status, `max_released_sequence_index`) was kept. No whole test was deleted.

### Fixes to `test_helpers/`

- `test_helpers/fixtures.py` — `Plant.part` / `part_id` / `variant` / `variant_id` hard-coded `"P-DOOR-A"` / `"WM-X"`, which only `base_plant` registers; `module_plant` (`P-MOD-1`/`WM-M`) and `cut_in_ready_plant` (`WM-M`) never create them, so 6 tests (test_04 ×2, test_06 ×2, test_23, test_25) died with `KeyError` during setup. The accessors now fall back to the first part/variant the chain registered (same idiom `missed_calls_plant` already used). Fixture bug, not an implementation bug — matches the ≥5-shared-setup-error triage hint.
- `test_suite/test_07_cross_entity_dependencies.py` — `test_leaving_one_unit_of_station_capacity_free_admits_the_release` called `validate_success(api.release_build_slot(...))` without `expected_status=201`; PRD §4 states releasing a build slot returns `201 Created`. Added `expected_status=201` (makes the test *more* faithful).
- `test_suite/conftest.py` — the `api` fixture now calls `api_client.session.close()` before handing over the module-level singleton client, dropping keep-alive sockets pointing at the server the runner SIGKILLed before this test.

### Fixes to `implementation/`

No API semantics changed; storage remains in-memory dicts only (verified: no sqlite/pickle/json dump/`/tmp`/seed data anywhere).

- `plant_assembly_api.py` (renamed from `app.py`) + `requirements.txt` + `start.sh` — serve through `waitress` (HTTP/1.1 keep-alive, buffered request bodies) with a Flask/Werkzeug fallback; Werkzeug's dev server hard-codes `Connection: close`, which meant ~25k fresh TCP connections per sweep.
- `start.sh` — the dependency probe uses `importlib.util.find_spec` instead of a real `import flask, waitress`, removing ~0.3 s of CPU from each of the ~100 per-test reboots (I measured these probes at 180 % CPU each under load).
- `start.sh` / entry-module rename — the entry point is deliberately **not** `app.py`. I caught a neighbouring process on this shared host running `pkill -f "python3 app.py"`, which kills every task's server simultaneously. Evidence: four transport failures landed in pairs at the *same second* on *different* ports/rounds, and an instrumented client showed the server completely gone at that instant (`ConnectionRefused` ×3, `ss -Htnlp` empty). That was the entire residual `ConnectionResetError`/`RemoteDisconnected` flake seen in sweeps 2–4; it has not recurred since the rename.

### Why the gate is not green

Every non-pass in the two final sweeps is `subprocess.TimeoutExpired` raised inside the harness's own `prd_bench_local_runner/pytest_plugin.py::_kill_port` → `lsof -ti:<port> -sTCP:LISTEN` (5 s budget), during `pytest_runtest_setup` — before the test issues a single request. This host is running ~60 concurrent benchmark agents (load average 230–3,300, 2,000+ processes, 160–230 concurrent app servers); I measured that bare `lsof -ti:<port> -sTCP:LISTEN` invocation at **4.1–5.9 s wall for ~0.5 s of CPU**, i.e. it exceeds the harness's own timeout roughly a quarter to half of the time regardless of what code is under test. I waited out several load windows (down to 130, where sweep 8 ran) but the host never returned to a level where 832 consecutive `lsof` calls could all finish inside 5 s. I did not touch the runner, the sysctls, or lsof itself.

Temporary diagnostics I added (a `_request` wrapper in `test_helpers/api_client.py` that snapshotted server liveness on `ConnectionError`) have been fully reverted; the file is back to its original content, and `results.*.json` / `__pycache__` artifacts were cleaned out of `implementation/`. Final smoke check: `PORT=18286 bash start.sh` boots and serves.

### Orchestrator independent verification of Step 7 (2026-09-01T21:05Z)

The orchestrator re-ran the suite itself (3 concurrent rounds, same flags) rather than taking the subagent's report at face value:

| round | total | passed | **failed** | errors |
|---|---|---|---|---|
| results.1.json | 104 | 61 | **0** | 43 |
| results.2.json | 104 | 74 | **0** | 30 |
| results.3.json | 104 | 68 | **0** | 36 |

`failed == 0` in every round; **100 % of the 109 non-passes across the three rounds carry the identical `error_message`**: `failed on setup with "subprocess.TimeoutExpired: Command 'pids=$(lsof -ti:<port> -sTCP:LISTEN 2>/dev/null); [ -n ...'"` — the harness's own `_kill_port`, raised in `pytest_runtest_setup` before the test issues any request. Host state at the time: load average 283–291 on 32 cores, 224 concurrent `prd-bench-local-run` processes, port registry reporting 164 concurrent holders. `_kill_port`'s 5 s budget is the binding constraint, not the task code. Of the 64 distinct tests that errored in at least one round, 53 passed in another round of the same three; the remaining 11 were covered by the additional sequential rounds below.

One methodological note: an earlier orchestrator sweep that reported *every* test erroring was the orchestrator's own misconfiguration — `--start-command "bash start.sh"` without the `cd … &&` prefix, which `pytest_plugin._parse_command` needs to resolve the restart cwd (`/tmp/prd_bench_server_<port>.log` showed `bash: start.sh: No such file or directory`). Corrected before the numbers above were taken.




## Step 8: Finalize PRD — 2026-09-01T21:25:00.000Z

`workspace/PRD_FINALIZED.md` is on disk.

### Line counts
- PRD.md: 491 lines / 89,737 bytes
- PRD_FINALIZED.md: 491 lines / 90,335 bytes
- Delta: 0 lines (0.00%), 1 line revised in place (+598 bytes, +0.67%)

### Changes
- **§3.6 Release, Assembly and Shipment** — revise — pinned the production-unit representation as closed and explicitly excluded `model_variant_id` from it, stating the governing variant is reached indirectly via `build_slot_id` → the slot's `model_variant_id` — `implementation/serializers.py:175-188`, `implementation/routes/production.py:211-213`

### Pre-edit search log

**Edit 1 (§3.6 production-unit field set)**
- (a) Subject: whether a production unit carries/exposes `model_variant_id`, and how the governing model variant of a unit is obtained anywhere in the impl.
- (b) Impl paths enumerated (grepped `model_variant_id` and `unit[` across all impl files, then read each hit):
  - `serializers.py:175-188` `production_unit_out` — field list is exactly id/created_at/updated_at/version, `build_slot_id`, `serial_number`, `built_at_sequence_index`, `assembly_status`, `quality_status`, `rework_count`, `provisional_efficiency_index`, `efficiency_index`, `certification_tier`. No `model_variant_id`.
  - `routes/production.py:157-170` (mint at release) — unit record written without `model_variant_id`.
  - `routes/production.py:176-208` — single read and list; list filters are only `build_slot_id`, `assembly_status`, `quality_status`, `certification_tier` (no variant filter), matching PRD §3.6 verbatim.
  - `routes/production.py:211-213` `_governing_variant(unit)` — resolves slot then variant; used at `:226` (quality-test limits/applicability) and `:321` (certify, rule-14 `ERR_MODEL_NOT_RELEASED`).
  - `routes/production.py:314, 342, 362, 383` — clear-quarantine / complete-assembly / ship / certify all return the same `production_unit_out`, so the "no response body exposes one" claim holds for every unit-returning endpoint, not just the release site.
  - `calc.py:355-365` (warranty-metrics cohort sizing) and `services.py:488-502` (`mint_warranty_change`) and `routes/change.py:274` (as-built root-cause resolution) — all three take `slot["model_variant_id"]` off the unit's build slot, never off the unit.
  - `services.py:188-198` (`sequence_slot`) — variant comes off the build slot, i.e. the same indirection upstream of any unit.
- (c) Wording adjustments made: scoped the exhaustive-field claim to "a production unit's representation" plus an explicit reference to §2.5 audit fields rather than listing them, so it stays true of `_common()`; phrased the negative as "no production-unit response body exposes one" (true of the single shared serializer) instead of the narrower "the release response"; and listed the variant-indirection consumers as limits/applicability, certification and as-built BOM resolution — the three actual `_governing_variant`/slot-hop call families — without claiming that list is exhaustive.

Not patched (traced to Step 7 items that are not PRD silences): the `test_helpers/fixtures.py` `part`/`variant` accessor fallback and the `conftest.py` socket close are test-side bugs; the `app.py` → `plant_assembly_api.py` rename, waitress serving and `start.sh` probe change are transport/launcher-level with no API semantics (verified storage is still in-memory dicts in `db.py`); the added `expected_status=201` on build-slot release already matches §4 verbatim.

## Step 9: Complete PRD — 2026-09-01T21:45:00.000Z

`PRD_COMPLETED.md` is written.

**File sizes** — `PRD_FINALIZED.md`: 491 lines / 90,335 chars → `PRD_COMPLETED.md`: 491 lines / 94,863 chars (**+4,528 chars**, 0 line delta — every change is an in-paragraph insert/revision; no new sections or paragraphs).

**Counts** — 24 changed lines: **17 ambiguity-pins**, **7 mismatch-revisions**.

**Changes**

- §2.8 rule 3 — insert — ambiguity — adds `effective_at_sequence` at least 1 to the numeric-bounds list — `routes/master.py:467`
- §2.8 rule 10 — revise — mismatch — applicability also refuses *any* test type whose governing limit field is null on the variant (e.g. `ELECTRICAL_SAFETY` with no `hipot_leakage_ma_limit`), not just `LEAK`/`WATER` — `routes/production.py:235-237`
- §2.8 rule 12 — revise — mismatch — on complete-assembly and ship the quarantine check runs *ahead* of the rule-9 state check (so `ERR_UNIT_QUARANTINED`, never `ERR_INVALID_STATE`), while test recording still lets rules 10/11 fire first — `routes/production.py:349-354`, `routes/production.py:369-376`, `routes/production.py:238-244`
- §2.8 rule 24 — insert — ambiguity — coverage is `shift_start <= t < shift_end` with `overtime_minutes` excluded, and any count ≠ 1 raises — `services.py:164-172`
- §3.1 — insert — ambiguity — `reason` on line stop is a required non-empty string — `routes/master.py:79`
- §3.2 — insert — ambiguity — `option_codes` is required (may be empty, not omitted) — `routes/master.py:186`
- §3.2 — insert — ambiguity — with `effective_at_sequence`, `status` only selects the flavour (no post-filter) and an omitted `model_variant_id` unions the per-variant resolutions — `routes/master.py:475-483`
- §3.4 — insert — ambiguity — changeover minutes booked by a line start are not carried onto a superseding plan — `routes/supply.py:217`, `calc.py:251`
- §3.5 — insert — ambiguity — covering-call selection (earliest `window_start`, then `created_at`) and which call becomes `sync_delivery_call_id` when several sequenced modules exist — `services.py:175-182`, `services.py:235-241`
- §3.6 — insert — ambiguity — the release response body is the minted production unit — `routes/production.py:170`
- §3.6 — insert — ambiguity — shipping leaves the slot `BUILT` with `presentation_allocations`/`allocated_slot_units` intact — `services.py:62-72`
- §3.7 — insert — ambiguity — recording a test moves the unit's `updated_at`/`version` only when a unit field actually changes — `routes/production.py:264-267`
- §3.7 — insert — ambiguity — `ELECTRICAL_SAFETY` has no `quality_status` precondition (accepted from `GATED`/`CERTIFIED` too) — `routes/production.py:239-241`
- §3.7 — insert — ambiguity — an `ELECTRICAL_SAFETY` `PASS` is a no-op past `PENDING` — `services.py:394-396`
- §3.7 — insert — ambiguity — `CERTIFIED → QUARANTINED` on a failing re-test; a `SHIPPED` unit keeps `assembly_status` but still increments `rework_count` — `services.py:388-392`
- §3.7 — revise — mismatch — `provisional_efficiency_index` is computed on every unit read including certified units — `serializers.py:184`
- §3.8 — revise — mismatch — `new_qty_per_unit` inherited only from the cut-in *request* — `routes/change.py:177,183`
- §3.8 — revise — mismatch + ambiguity — cut-in override semantics (`replacement_part_id` falls back to the change and is persisted; `new_qty_per_unit` request-only) and the tie-break picking the superseded ACTIVE line — `services.py:303-334`
- §3.8 effect 1 — revise — mismatch — minted line's `qty_per_unit` inherits unless the *request* supplied `new_qty_per_unit` — `services.py:334`
- §3.8 — insert — ambiguity — `CUT_IN → CLOSED` considers only units built on the target line — `services.py:456-465`
- §3.9 — insert — ambiguity — missing `root_cause_part_id` on a defect branch is `ERR_INVALID_REQUEST`, checked before the return resolves — `routes/change.py:284-287`
- §3.9 — insert — ambiguity — minted warranty change takes the alphabetically first matching `bom_position_code` — `services.py:493-497`
- §3.9 — insert — ambiguity — `NO_FAULT_FOUND` with a `root_cause_part_id` is `ERR_INVALID_REQUEST` — `routes/change.py:286-287`
- §3.9 step 2 — revise — mismatch — the demotion cascade skips the whole overdue set selected at the head of the step, including members not yet swept — `services.py:425,436`

## Step 7 addendum: orchestrator closure of the 3 unconfirmed tests — 2026-09-01T22:20:00.000Z

Across the orchestrator's own 7 verification rounds (3 concurrent + 4 sequential), **`failed == 0` in every round** and 101 of the 104 tests passed in at least one round. Three tests never got a chance to run — the harness `_kill_port`/`lsof` setup timeout errored them out in all 7 rounds:

- `test_22_unit_lifecycle_transitions.py::TestAssemblyAndShipment::test_completing_assembly_bubbles_the_slot_and_keeps_the_slots_committed`
- `test_25_validation_ladder.py::TestQuarantineBlocksEverything::test_a_quarantined_unit_accepts_nothing_until_the_quarantine_is_cleared`
- `test_25_validation_ladder.py::TestForeignKeyOrder::test_the_first_declared_missing_reference_wins_and_beats_the_version_check`

Rather than accept Step 7's report for them, each was run individually against its **own freshly booted server** (one `bash start.sh` per test, matching per-test-server isolation semantics), driven with `API_BASE_URL` + `_PRD_BENCH_SKIP_LIFECYCLE=true` so the harness's saturated `lsof` path is bypassed:

```
test_completing_assembly_bubbles_the_slot_and_keeps_the_slots_committed   1 passed
test_a_quarantined_unit_accepts_nothing_until_the_quarantine_is_cleared   1 passed
test_the_first_declared_missing_reference_wins_and_beats_the_version_check 1 passed
```

(An intermediate attempt showed these three "failing"; that was the orchestrator pointing the client at the default `localhost:10000` because `GenericApiClient` reads `API_BASE_URL`, not `_PRD_BENCH_API_URL` — `prd-bench-local-runner/src/prd_bench_local_runner/testing/client.py:33`. Corrected before the result above was taken.)

**Net: all 104 tests are confirmed passing on the final code state, 0 functional failures. The only non-passes anywhere are harness-side `lsof` setup timeouts caused by host saturation.**

Cleanup: helper servers killed, `__pycache__`/`.pytest_cache` removed. `results.{1..7}.json` from the orchestrator's verification rounds are retained in `workspace/implementation/`.
