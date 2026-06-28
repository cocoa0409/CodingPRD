# Worklog — task_0441_contract_packaging

## Step 1: Create Task Directory — 2026-06-21T00:00:00.000Z

Task directory `tasks/task_0441_contract_packaging/` was pre-assigned and pre-created (with `workspace/` subdir). No auto-scan performed. Scenario: "441. Contract Packaging / Co-Packing: project/recipe & bill of materials, line scheduling & changeover, lot coding & date/expiration, fill-weight checkweigher & QA, component & finished-goods inventory, allergen-changeover validation, customer-owned material reconciliation, run rate & waste". Difficulty band: Expert (§0.4).

## Step 2: Generate Scaffold (Expert band) — 2026-06-21T00:00:00.000Z

All three scaffold artifacts are generated, parse cleanly, and pass `scaffold_lint.py` with `VERDICT: clean lint`. Generated purely from the scenario description and the skill spec — no sibling tasks were read.

Generated the Expert-band scaffold for **task_0441_contract_packaging** (Contract Packaging / Co-Packing) at:
- SCAFFOLD.yaml (1392 lines)
- SCAFFOLD_DIFFICULTY_DESIGN.yaml (1521 lines)
- SCAFFOLD_CORNER_DESIGN.yaml (1549 lines)

**Complexity profile:** quota_allocation + workflow_orchestration; graph topology; branching state-machine shape; peer_roles; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers.

**Scaffold size (Expert band):**
- **Entities: 12** — Customer, Component, ComponentLot, Recipe, BomLine, ProductionLine, Crew, ProductionRun, LotConsumption, CheckweighSample, CmrLedgerEntry, SanitationEvent
- **State machines: 3** — Recipe (cyclic revision loop + approve/reject branch), ProductionRun (QA fork RELEASED vs QUARANTINED, plus SCHEDULED/RUNNING cancel-compensation), ComponentLot (AVAILABLE↔DEPLETED, →QUARANTINED)
- **Concurrency rules: 2** — run-start-stale-line (OCC on ProductionLine.version), bomline-add-stale-recipe (OCC on Recipe.version)
- **Calculations: 9** — material_consumption (FEFO draw), waste_reconciliation (dual-variant planned/actual), waste_totals (pinned round-per-line-then-sum), project_run_window (state-dependent changeover), assign_lot_code, checkweigh_verdict (inclusive band), checkweigh_reject_rate, inventory_on_hand (dual-variant available/physical), run_rate
- **Validations: 19** (priorities 1–29, with allergen-changeover, expired-lot, insufficient-material, line/crew temporal overlap, QA reject gate, OCC, recipe-approved gates)
- **Endpoints: 46** (incl. 1 test-driving `/copack/_clock/set_current_utc`; all 15 FKs have reverse-reachability GETs)
- **Error catalog: 18** (all referenced by a validation/concurrency rule)
- **Roles: 3** — Receiver, Scheduler, QAInspector (peer_roles, all opaque identity)

**§1.8 Difficulty Design:** 9 rule_ids × 2 instances = 18 instances, literal-pinned asserts (FEFO 150→0/60→140, waste planned 10.000 vs actual 40.000, run_rate 50.00, lot_code ACME-20260601-GRAN-001, fg_expiration 2026-08-30T08:00:00.000Z, CMR net-zero ±210.000).

**§1.9 Corner Design:** 35 instances across all 8 applicable claim-extraction sections (34 active + 1 excluded_because stub), covering CRUD/computed/system fields, not-found, duplicate code/SKU, enum/quantity rejection, invalid-from transitions, terminal lockdown, expired-lot/insufficient-material/overrun errors, RBAC denials, FK integrity, pagination envelope, OCC stale-version (both parents), immediate-consistency reservation.

**Verification:** `scaffold_lint.py` → `VERDICT: clean lint` (625 calls scanned, all conform to §1.5, all FKs reverse-reachable). Zero duplicate instance names, all enum values producible, all errors triggerable, all endpoint roles in RBAC, no forbidden concurrency vocabulary, both OCC rules satisfy §1.2.1.

## Step 3: Copy INSTRUCTION.md — 2026-06-21T00:00:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0441_contract_packaging/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-21T00:00:00.000Z

Generated `workspace/PRD.md` (274 lines) from SCAFFOLD.yaml only. Neither design-index file was read.

**Section structure:**
- §1 Introduction — co-packing framed around material traceability/ownership, food-safety changeover/QC, scheduling integrity.
- §2 Global Specifications — 11 subsections: 2.1 RBAC (Receiver/Scheduler/QAInspector, opaque identity), 2.2 Response Structure (byte-identical to source), 2.3 Pagination, 2.4 Common Properties & Versioning (4 append-only entities lack updated_at/version), 2.5 Hierarchical Consistency, 2.6 Nested Retrieval & Existence Ordering, 2.7 OCC (both expected_line_version + expected_recipe_version, ERR_STALE_VERSION/412), 2.8 Precision & Rounding, 2.9 Allergen Changeover, 2.10 CMR, 2.11 Logical Clock.
- §3 Business Logic — 8 subsections by lifecycle (brand owners/inventory, recipes/BOM approval loop, lines/crews/scheduling, run start changeover/expiry/material/lot-coding, completion/run-rate/waste, QC checkweigh/release/quarantine, cancellation & CMR reconciliation, validation-order). No HTTP methods/paths in §3.
- §4 Endpoint Definitions — 4-column table, all 46 endpoints.
- §5 Error Code Catalogue — all 18 error IDs.

**Hard Contracts:** Contract 1 (Field-Name Coverage 53/53) PASS; Contract 2 (Rule Coverage: 2/2 OCC, all state transitions, 8/8 calculations, validations, side-effects, equal-density sibling branches) PASS; Contract 3 (§3 Path Purity, 327 backtick tokens, 0 leaks) PASS. No design-index files read.

## Step 5: Generate Unit Tests — 2026-06-21T00:00:00.000Z

Generated test infrastructure and a claim-driven test suite for task_0441_contract_packaging.

**Stage 1 — test_helpers/ (9 files):** types.py (entity TypedDicts; append-only records LotConsumption/CheckweighSample/CmrLedgerEntry/SanitationEvent carry only id+created_at), api_client.py (one method per PRD endpoint), api_errors.py (18 error IDs + HTTP status map), assertions.py, factories.py, constants.py, test_users.py (3 roles all opaque → shared-constant headers canonical), fixtures.py (approved-recipe builder, scheduled/running/pending-QA/released run builders, dirty-line allergen scenario), __init__.py.

**Stage 2 — test_suite/ (conftest + 7 files): 72 tests total.**
- test_01 recipes/approval (6), test_02 components/inventory (11), test_03 run scheduling (12), test_04 run start (13), test_05 completion/QA (17), test_06 waste/CMR (8), test_07 listing/RBAC (5).

**Queue split:** Queue A (Difficulty) 38 tests — all 18 difficulty instances ≥2 tests each. Queue B (Corner) 34 tests — all 34 non-stub corner instances ≥1 test each.

**Skips:** 1 instance — the corner stub `state_machines/error_allergen_changeover_on_start` (carries excluded_because, no test_recipe; defers to difficulty instance `priority_pair_validation_conflict/start_allergen_safety_beats_insufficient_material_fiscal`, covered by 2 queue-A tests). No instances dropped under PRD-first filter.

**Audits passed:** every test has exactly one Design: tag (verbatim from source YAML name:); no untagged/dual-tagged/dangling tags; no skip/skipif/xfail; no scaffold leakage; all PRD citations survive strict literal grep of PRD.md; all files byte-compile. Note: `inventory_available_vs_physical` 2nd assertion (physical-on-hand, not a PRD-exposed field) asserts divergence via observable fields only (quarantined lot.remaining_qty==140 vs component.on_hand_qty==0).

## Step 6: Generate Implementation — 2026-06-21T00:00:00.000Z

Generated Python 3.9 + Flask 3.0.3 implementation at workspace/implementation/.

**File list (22 files):** start.sh; requirements.txt; app.py (entry, blueprint registration, error handlers); db.py (in-memory store); clock.py (logical clock); response.py (envelope); errors.py (error catalog); middleware.py (auth/RBAC); util.py (Decimal rounding/pagination/parsing); serializers.py (per-entity output); routes/ (6: customers, components, recipes, lines+crews+sanitation, runs, clock_route); services/ (4: calc all formulas, inventory on_hand, recipe_svc allergen profile, run_svc run lifecycle).

**Endpoint count:** 52 routes covering all PRD §4 / SCAFFOLD §1.5 entries.

**State machines:** Recipe (DRAFT→PENDING_APPROVAL→APPROVED/REJECTED, REJECTED→DRAFT cyclic, APPROVED→RETIRED with live-run guard; submit gated on ≥1 INGREDIENT + ≥1 PACKAGING line). ProductionRun branching at QA fork: SCHEDULED→RUNNING→PENDING_QA→{RELEASED|QUARANTINED}, plus CANCELLED from SCHEDULED (release reservations) or RUNNING (full compensation). ComponentLot (AVAILABLE↔DEPLETED, →QUARANTINED) driven by run events.

**Calculations (all Decimal round-half-up):** material_consumption (scrap-inflated required_qty, 3dp), FEFO draw (expiration ASC, _seq ASC tie-break), project_run_window (state-dependent changeover, seconds rounding), assign_lot_code (CODE-YYYYMMDD-SHORT-NNN, sequence within customer/pack-day), checkweigh_verdict (inclusive band, 3dp), reject_rate (4dp), run_rate (2dp, zero-elapsed→0), waste planned vs actual (round-per-line-then-sum), inventory_on_hand (AVAILABLE − reserved).

**OCC:** expected_line_version (run start) + expected_recipe_version (bom-line add), both → ERR_STALE_VERSION 412.

**Validation ordering (PRD §3.8):** auth(401)→authz(403)→path existence(404)→body(400)→uniqueness(409)→FK existence(404)→quantity(422)→enum(422)→state(409)→start-specific: allergen(21)→expired-lot(22)→insufficient-material(23)→OCC(28).

**start.sh:** reads $PORT (default 10000), app.py binds 0.0.0.0, foreground via exec, pip install guarded. In-memory only — db.reset() at process init; restart wipes state, clock resets to 2026-01-01T00:00:00Z. No seeding, no file IO.

## Step 7: Run Tests and Iterate — 2026-06-21T00:00:00.000Z

**Iterations run:** 2 (plus an initial baseline sweep). Baseline → diagnose import + setup bugs → fix → clean sweep.

**Tests deleted:** None. Every failure traced to test-helper/test-setup bugs, not to PRD-silent or non-derivable assertions, so no deletions were warranted.

**Root causes found (both in the test layer; the implementation was correct and PRD-faithful throughout):**

1. **Collection failure (all 72 tests, every round).** Six test modules did `from test_helpers.test_users import RECEIVER, SCHEDULER, QA`, but `test_helpers/test_users.py` only exported `TEST_USERS` and `UNKNOWN_ROLE_HEADERS`. Pure import error — pytest couldn't even collect, so every module errored.

2. **Stale-version setup failure (51 tests, deterministic in all 8 rounds).** The two-BOM-line preamble passed the *first BOM line's* `version` as `expected_recipe_version` for the *second* `add_bom_line`. Per PRD 3.2, adding a BOM line bumps the recipe's version, and per PRD 2.7 the next add must carry the recipe's current version — so the second add always tripped `ERR_STALE_VERSION` (HTTP 412) during setup. (Recipe version starts at 1 and is +1 per BOM add; the BomLine's own `version` is unrelated to the recipe's.)

**Fixes applied to `test_helpers/`:**
- `test_users.py` — added `RECEIVER`, `SCHEDULER`, `QA` role-header constants (the canonical per-role header dicts, consistent with PRD 2.1's opaque-`X-User-ID`/role-only model). Fixes the collection import error.
- `__init__.py` — re-exported `RECEIVER, SCHEDULER, QA` from the barrel.
- `fixtures.py` — in `build_approved_recipe`, the second `add_bom_line` now re-reads the recipe (`get_recipe`) to use its current version instead of `bl1["version"]`. This fixture underpins `setup_basic_scenario`/`setup_*_run`, so it cleared most of the 51 failures.

**Fixes applied to `test_suite/` (same stale-version setup bug, inline in three test functions):**
- `test_01_recipes_and_approval.py` — `test_rejected_recipe_revises_back_to_draft` and `test_revised_recipe_resubmits_to_pending_approval`: re-read recipe version between the two BOM adds.
- `test_03_run_scheduling.py` — `test_schedule_against_pending_recipe_rejected`: same re-read fix.

**Fixes applied to `implementation/`:** None. The implementation was already correct and PRD-faithful; all failures were test-side preconditions inconsistent with the PRD's version model.

**Final result:** 8/8 parallel rounds, 72/72 tests passing, 0 failures, 0 errors, fully deterministic (no flakiness). Transient `results.*.json` artifacts removed.

## Step 8: Finalize PRD — 2026-06-21T00:00:00.000Z

PRD_FINALIZED.md is a verbatim copy of PRD.md — zero substantive edits, because neither Step 7 diff item reveals a genuine PRD silence or PRD/impl mismatch.

**Line counts:** PRD.md = 274 lines, PRD_FINALIZED.md = 274 lines. %-delta: 0.0% (byte-identical, `diff` exit 0).

**Changes:** None. Both Step 7 root causes were pure test-layer bugs whose underlying behaviors the PRD already determines uniquely.

**Per-diff-item justification:**
- Diff item 1 — import-barrel bug (RECEIVER/SCHEDULER/QA missing from test_helpers): a missing test-helper export, not a behavioral choice in implementation/. PRD §2.1 fully determines the auth model (3 roles, opaque X-User-ID, decisions on X-User-Role only). Nothing for PRD to pin.
- Diff item 2 — stale-version setup bug: the behavior is explicit in PRD, not silent. §3.2 ("adding a line ... increments the recipe's version by one") + §2.7 (expected_recipe_version must equal recipe's current version, else ERR_STALE_VERSION 412). Impl matches exactly (routes/recipes.py OCC check + db.touch; version starts at 1, +1 per mutation). Fixture fed a stale value; no PRD ambiguity.

**Pre-edit enumeration (no edits made):** Subject = recipe version-increment/OCC model. Enumerated db.py (version=1 / touch +1), routes/recipes.py (add_bom_line OCC + all state-transition touches), services/recipe_svc.py, plus grep of all touch() callsites in routes/components.py, routes/lines.py, services/run_svc.py — all consistent with PRD §2.4/§2.5 + per-op increments in §3.2–§3.7.

## Step 9: Complete PRD — 2026-06-21T00:00:00.000Z

Produced `workspace/PRD_COMPLETED.md` as a minimal patch over PRD_FINALIZED.md, pinning every spot where PRD prose admitted multiple interpretations to what implementation/ actually does. Walked all routes (customers, components, recipes, lines, runs, clock), services (calc, inventory, recipe_svc, run_svc), and shared layers (db, util, response, middleware, serializers, clock, errors).

**File metrics:** PRD_FINALIZED.md 274 lines / 45,480 chars → PRD_COMPLETED.md 274 lines / 47,071 chars. Char delta +1,591 (no new lines, no new sections — all in-paragraph inserts/revisions).

**Change counts:** ambiguity-pins 8, mismatch-revisions 1, total 9.

**Per-change log:**
- §2.3 Pagination — insert — ambiguity — out-of-range limit/offset silently clamped (1..100, offset≥0); non-integer → ERR_INVALID_REQUEST — util.py:66-78
- §2.4 Common Properties — insert — ambiguity — version initial value is 1 — db.py:83
- §2.11 Logical Clock — insert — ambiguity — clock-set data is { "current_utc": <iso millis> }; missing/non-string/unparseable → ERR_INVALID_REQUEST — routes/clock_route.py:19-25
- §3.1 Brand Owners — insert — ambiguity — malformed customer code (format) → ERR_INVALID_REQUEST (distinct from collision's ERR_DUPLICATE_CODE) — routes/customers.py:35-39
- §3.2 Recipes/BOM — insert — ambiguity — serialized allergen_profile is a JSON array sorted ascending lexicographically — services/recipe_svc.py:23
- §3.3 Scheduling — insert — ambiguity — malformed scheduled_start → ERR_INVALID_REQUEST (unlike lot expiration_date → ERR_INVALID_ENUM) — routes/runs.py:52-54
- §3.4 Starting a Run — insert — ambiguity — start-time recipe-not-APPROVED → ERR_RECIPE_NOT_APPROVED, evaluated after SCHEDULED precondition and before allergen/expiry/material — routes/runs.py:160-161
- §3.4 Starting a Run — revise — mismatch — LotConsumption also carries customer_owned flag snapshotted at consumption time — services/run_svc.py:239, serializers.py:130-139
- §3.5 Completing a Run — insert — ambiguity — actual_units_good/actual_units_scrapped integers defaulting to 0, must be ≥0 else ERR_INVALID_QUANTITY — routes/runs.py:195-198
- §3.5 Run Summary — insert — ambiguity — summary reject_rate uses same 4-decimal rule as release, 0.0 when no samples — services/run_svc.py:438

**Checked & left unchanged (PRD already pins / impl matches):** §3.8 validation-priority ordering, lot-code sequence states, FEFO tie-break, over-run ceiling boundary (>), reject-rate release boundary (≤0.05), allergen-changeover "sanitized since last run" gate, run-rate zero-elapsed boundary, waste round-then-sum order, all other serializer field sets.

---

## PIPELINE COMPLETE — 2026-06-21T00:00:00.000Z

All 9 steps done. Final state: 72/72 tests passing across 8/8 deterministic parallel rounds. Artifacts: SCAFFOLD.yaml (+DIFFICULTY/CORNER design), workspace/PRD.md → PRD_FINALIZED.md (verbatim copy) → PRD_COMPLETED.md (9 pins), test_helpers/ (9 files) + test_suite/ (7 files, 72 tests), workspace/implementation/ (22 files, Python+Flask, in-memory). Transient results.*.json removed.
