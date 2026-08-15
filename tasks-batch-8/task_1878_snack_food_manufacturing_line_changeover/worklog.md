# Worklog — task_1878_snack_food_manufacturing_line_changeover

## Step 1: Create Task Directory — 2026-08-14T22:05:00.000Z

Pre-existing per pipeline invocation: `tasks/task_1878_snack_food_manufacturing_line_changeover/` and `workspace/` already existed; orchestrator started at Step 2.

## Step 2: Generate Scaffold — 2026-08-14T22:43:16.451Z

Done. All three scaffold artifacts are generated and lint-clean.

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1878_snack_food_manufacturing_line_changeover/`):
- `SCAFFOLD.yaml` (2095 lines) — §1.0–§1.7 only
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1411 lines) — single key `scaffold_difficulty_design`, 23 instances
- `SCAFFOLD_CORNER_DESIGN.yaml` (2154 lines) — single key `scaffold_corner_design`, 66 instances (51 active + 15 `excluded_because` stubs)

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (62 endpoints, 13 entities, 23 §1.8 + 51 §1.9 active instances, 719 calls scanned, 0 violations; forbidden-vocabulary grep clean.)

**Design shape:** posture-driven gating + compliance/audit archetype, flat topology (all FKs in bodies), segregation-of-duties role model (5 roles; `CoManufacturer` is `entity_backed:CoManufacturer` with ownership scoping; PlantManager deliberately excluded from quality ops), immediate consistency, logical clock with pinned default `2026-08-01T00:00:00Z`.

**Maximum-difficulty interlocks delivered per the directive:**
- **Cascades:** weight-check → TPM 27.0 breach → run HELD (system hold, null holder) → PLANNED display cases CANCELLED (depth 3); display-case build → quota 0 → window EXHAUSTED → sibling PLANNED cases CANCELLED (depth 3); plus run-reject and over-reservation cascades.
- **Dual-variant calcs in different domains:** giveaway (provisional −0.87 vs final 0.25 on identical checks) and freshness routing (WAREHOUSE at 17 days remaining vs DSD at 11 with transit 1).
- **Combinatorial modes a/b/c all pinned:** TPM dilution × conditional temp factor (19.99 literal), per-check-then-average rounding order (0.25 vs 0.20), margin evaluation order (standard 165925 vs actual 138068, per-case 1453).
- **Boundary semantics:** TPM inclusive >= 27.0 (26.99 → 27.00 stepwise), reject threshold strictly `< declared − 2×tne`, reject ratio exclusive `> 0.025` (1/40 passes, 2/40 holds), seasoning band ±0.5 inclusive, warehouse `>10` exclusive vs DSD `>=4` inclusive, capacity `<=` exact-fit.
- **Temporal overlap with different interval semantics:** runs half-open + allergen-dependent cleaning buffer (DRY_CLEAN 30 / FULL_WASH 120, buffer boundary inclusive) vs promo windows closed-interval (shared boundary date = overlap).
- **Concurrency:** two OCC rules only (run-create on `ProductionLine.version`, oil-movement on `FryerOil.version`) — both pass the §1.2.1 serial-observability filter; capacity contention and quota exhaustion were deliberately classified as state preconditions, not races.
- **Conserved quantities:** oil gallons (100 + 6 − 6 − 6.000 = 94 after top-off/discard pair) and promo quota (`total == remaining + consumed − released` across build/cancel, 10 restored exactly).
- **RBAC/SoD adversarial edges:** cleaner ≠ validator, holder ≠ releaser (tracked by X-User-ID across roles), margin floor overridable only by PlantManager with explicit flag, priority pairs safety>temporal, constraint>fiscal, state>fiscal.

All formula-derived assertions were executed in Python before being pinned as literals (verified: 12.33, 19.99, 27.0, −0.87, 0.25, 165925, 138068, 1453, 28296, 2830, freshness 17/11/10/4/3, ratios 0.025/0.05). No sibling task directories were read at any point.

## Step 3: Copy Shared Files — 2026-08-14T22:43:34.306Z

Copied `./INSTRUCTION.md` to `tasks/task_1878_snack_food_manufacturing_line_changeover/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T22:56:51.204Z

The generated document is complete and verified. All three hard contracts pass.

## Report

**Output written:** `/home/ubuntu/github/CodingPRD/tasks/task_1878_snack_food_manufacturing_line_changeover/workspace/PRD.md` (363 lines, ~62 endpoints, 41 error codes). The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened or referenced.

**Document structure:**
- §1 Introduction — 2 paragraphs, business-context angle, `/snack-mfg` mount
- §2 — 10 subsections: RBAC with per-role identity semantics (CoManufacturer entity-backed, four opaque roles), verbatim §2.2 response block, pagination (limit 10/1/100, offset 0, `created_at` ascending), the logical clock (startup default 2026-08-01T00:00:00Z, `to_iso8601`/`current_utc`), common resource properties (with the OilMovement/WeightCheck no-`updated_at`/no-`version` exception), precision/rounding, OCC, line posture precedence, the 10-tier validation order, and the three conserved ledgers
- §3 — 9 subsections organized by plant workflow: product/line setup, scheduling + changeover matrix, cleaning/validation, run execution + oil management, completion + disposition, cost/margin/giveaway accounting, freshness + routing, promo windows + display cases, co-man capacity booking
- §4 — 62-row endpoint table (4 columns only); §5 — 41-row error table (2 columns only)

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 114 required, 114 present, 0 missing
- endpoints[].request_body/query_params/path_params: included in the 114 (to_iso8601, expected_line_version,
  expected_oil_version, disposition, result, override_margin_floor, margin_actual_per_case_cents, limit, offset, ...)
- error IDs: 41 required, 41 present; enum/state values: 65 required, 65 present
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 10 checked, 10 expressed (§2.9 ordered list + capacity-before-budget in §3.9), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (expected_line_version/expected_oil_version + ERR_STALE_VERSION 412, no race framing), 0 missing
- state_machines[].transitions: 42 checked, 42 fully expressed (all preconditions, error IDs, cascades incl. OIL_HOLD/QUOTA_EXHAUSTED/OVER_RESERVED/RUN_CANCELLED/RUN_REJECTED), 0 missing
- calculations[]: 7 checked, 7 fully expressed (tpm_degradation, giveaway_calc PROVISIONAL/FINAL, seasoning_dosing, margin_calc STANDARD/ACTUAL, freshness_window, changeover_requirement, coman_capacity_allocation — all formulas translated to precise prose with pinned rounding orders and edge inclusivity), 0 missing
- validations[] conditions: 10 checked, 10 matchable to error_id in §2.9/§3, 0 missing
- endpoints[].side_effects / applies_to: 62 endpoint side-effect sets + the 6-endpoint CoManufacturer ownership scope expressed, 0 missing
- entities[].fields[] structured content: 13 entities' types/defaults/initials reconstructible (bags_per_case 12, transit_days 2, case_size_bags 12, cleaning minutes 120/30, active true, tpm 0.5, etc.), 0 missing
- sibling-branch symmetry: 8 groups checked (DSD/WAREHOUSE plan, replan ×2, dispatch ×2, shipment cancel ×3, run cancel ×2, terminate ×2, slot release ×2, display-case cancel PLANNED/BUILT), all equal density
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 615
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Additional precision checks (all PASS):** §2.2 matches `section-2.2-response-structure.md` byte-for-byte; no pseudocode operators (`==`, `>=`, `+=`, `->`, angle-bracket comparisons) in prose; no fuzzy/approximating words; every threshold's inclusivity edge stated explicitly (e.g., TPM 27.0 inclusive, reject limit strict, seasoning band exactly-0.5-passes, WAREHOUSE exactly-10-ineligible, DSD exactly-4-eligible, capacity exactly-equal-allowed).

## Step 5: Generate Unit Tests — 2026-08-14T23:59:00.000Z

All work is complete. Final report:

## Summary

Generated complete test infrastructure and test suite for `task_1878_snack_food_manufacturing_line_changeover` per the prd-bench-unit-test-generator skill.

**Stage 1 — `test_helpers/`** (9 modules):
- `types.py` — 10 status enums + role enum + 14 TypedDicts; OilMovement/WeightCheck correctly modeled as append-only (no `updated_at`/`version`) per PRD §2.5.
- `api_client.py` — `ApiClient(GenericApiClient)` with 62 endpoint methods covering every row of the endpoint table.
- `api_errors.py` — all 41 error IDs with the §5 HTTP status map, registered via `set_error_http_status_map`.
- `assertions.py` — per-entity asserters + `assert_quota_invariant`.
- `factories.py`, `constants.py` (TPM 27.0, filtration 0.6, freshness 4/10, reject 0.025, etc.), `test_users.py` (opaque roles as shared constants; `make_coman_headers(entity_id)` for the entity-backed CoManufacturer).
- `fixtures.py` — composite chains: `setup_running_run`, `setup_completed_run`, `setup_passed_run`, `setup_system_held_run` (TPM exactly 27.0 cascade), `setup_required_changeover` (DAIRY→PLAIN FULL_WASH), `clean_and_validate_changeover`, promo-window and co-man agreement/slot builders, all using `get_success_data` and identity-threaded headers.

**Stage 2 — `test_suite/`** (conftest + 11 domain-named files, 97 tests):
- Queue A: all 23 difficulty instances, exactly 2 tagged tests each (46 tests) — dual-variant giveaway/freshness divergence, pinned rounding/evaluation orders, swab-fail and hold-filtration cycles, both depth-3 cascades, three priority-pair orderings, three boundary instances, three cross-entity gates, both interval-semantics resources, both conservation invariants.
- Queue B: all 51 non-stub corner instances, 1 tagged test each; the 15 `excluded_because:` stubs left untranslated.

**Audits (all PASS)**: tag coverage with zero shortfalls/dangling tags; every docstring ends with exactly one verbatim `Design: Difficulty/<rule>/<name>` or `Design: Corner/<section>/<name>` line resolving to a real instance; every quoted PRD citation survives whitespace-normalized grep of `PRD.md`; no skip/skipif/xfail markers; `py_compile` clean; `pytest --collect-only` collects 97 tests.

Key decisions: two tests per difficulty instance were split along the instance's own assert clauses (e.g., breach side vs. cascade side) rather than inventing new claims; all asserted literals (-0.87/0.25, 19.99, 165925/138068/1453, 28296/2830, freshness 17/11/10/4/3) copied verbatim from the pre-computed design recipes; DISCARD/FILTRATION payloads omit `unit_price_cents_per_gal` entirely (the factory drops the key on `None`) since the field is forbidden, not nullable.

## Step 6: Generate Implementation — 2026-08-15T00:10:00.000Z

96/97 passing under the official harness. The implementation is complete. Final state of the deliverable and results:

**Implementation** at `/home/ubuntu/github/CodingPRD/tasks/task_1878_snack_food_manufacturing_line_changeover/workspace/implementation/`:

- `start.sh` — guarded dependency install (`if ! python3 -c "import flask"`), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000), self-cds so it works from any cwd
- `app.py` — Flask entry, envelope/error handlers, blueprint registration
- `store.py` — in-memory store (empty at every boot, no seeding), logical clock starting exactly at 2026-08-01T00:00:00Z, monotonic sequence for tie-breaks
- `util.py` — Decimal round-half-up helpers, ISO8601 3-fractional-digit timestamps, envelope builders, pagination (limit/offset clamped per spec), request-shape validators
- `auth.py` — X-User-ID/X-User-Role validation against the five declared roles
- `domain.py` — all derived state (posture, current profile, cases_unrouted ledger, quota invariant, last-oil-price), TPM degradation model with per-step 2-decimal rounding and the QUALITY_HOLD cascade, dual-variant margin (locked STANDARD / weighted-in-window ACTUAL), dual-variant giveaway (raw-mean PROVISIONAL / per-check-rounded FINAL), freshness window, changeover matrix, and every serializer
- `routes/` — 9 blueprints covering all 46 endpoints with the PRD §2.9 validation priority order (auth → role → existence → ownership → shape → state/OCC → safety/SoD → temporal → quantity → fiscal), all state machines with side-effect cascades, and OCC on `expected_line_version`/`expected_oil_version` (412)

**Verification**: the official suite (97 tests) run via `prd-bench-local-run --isolation per-test-server` (server re-launched through `start.sh` before every test) gives **96 passed, 1 failed, 0 errors**.

The single failure, `test_line_posture_recomputes_across_changeover_lifecycle`, is unsatisfiable as written: the fixture (`test_helpers/fixtures.py::setup_required_changeover`) fetches `ctx["line"]` only after run2 is scheduled and the auto-created changeover already sits in REQUIRED, so `assert ctx["line"]["posture] == "IDLE"` (line 264) and `assert get_line(line_id)["posture"] == "CLEANING"` (line 266) read the identical server state with contradictory expectations. PRD §2.8 mandates CLEANING whenever any changeover is REQUIRED/CLEANING/SWAB_PENDING, and the design doc (SCAFFOLD_CORNER_DESIGN.yaml) shows the intended IDLE capture was right after run1 completion — before run2 existed. Any rule that makes line 264 pass makes line 266 fail, so I kept the PRD-faithful behavior (verified: IDLE after completion, CLEANING with REQUIRED open, IDLE after validation).

Bugs caught and fixed during iteration: an inverted `ge` range check in the validators; UUIDs minted without dashes (tests require the 8-4-4-4-12 form); `reject_ratio` must be the raw ratio (0.025 for 1/40), not the 2-decimal rounding the PRD §2.6 sentence suggests — the tests assert raw; body-FK existence order for slot creation (product_id before agreement_id per the canonical §2.9 ordering); full-drain DISCARD must be rejected with ERR_INVALID_STATE while a run is RUNNING on the line; in-window price matching switched to datetime comparison.

One invocation note: when driving `prd-bench-local-run` manually, pass an absolute `--start-command` (or the `cd dir && ...` form) — the pytest plugin re-spawns the server from a different cwd, so a bare relative path fails every restart with "No such file or directory".

## Step 7: Run Tests and Iterate — 2026-08-14T23:42:44.369Z

All 8 rounds pass 97/97. Clean sweep achieved.

## Summary

- **Iterations run:** 2 (initial 8-round sweep confirmed the failure deterministically in all 8 rounds; one fix, then a clean 8-round verification sweep).

- **Tests deleted:** none.

- **Fixes applied to `test_helpers/`:** `fixtures.py` — fixture `setup_required_changeover`. The returned `"line"` snapshot was fetched via `get_line(line["id"])` *after* `run2 = schedule_run(...)` had already auto-created the REQUIRED changeover, so per PRD §2.8 the snapshot's posture was necessarily `CLEANING` — contradicting the test's line-264 `IDLE` assertion against identical server state where line 266 asserts `CLEANING`. Moved the snapshot to immediately after `complete_run(run1["id"])` and before run2 is scheduled (run1 COMPLETED → no RUNNING runs; no changeover exists yet; FryerOil ACTIVE → posture `IDLE`), and documented the snapshot timing in the fixture docstring. Verified all 12 consumers of this fixture: only the disputed test reads `ctx["line"]` (immutable `id` plus this `posture`), so no other test is affected.

- **Fixes applied to `test_suite/`:** none. The test `test_line_posture_recomputes_across_changeover_lifecycle` is faithful to PRD §2.8 (verbatim posture precedence rule, line 99 of PRD.md), §3.3 ("Validation lifts the cleaning gate, so the line's posture is recomputed"), and `posture` is response-visible per the endpoint table (PRD line 258). STEP 1 coverage and unique derivability both hold; the bug was purely the fixture's snapshot timing (STEP 2).

- **Fixes applied to `implementation/`:** none. `domain.py::line_posture` implements the PRD §2.8 precedence exactly (RUNNING → CLEANING on changeover in REQUIRED/CLEANING/SWAB_PENDING → BLOCKED on oil QUALITY_HOLD/DRAINING → IDLE) and recomputes on every fetch; the implementation was already PRD-faithful.

Final state: 97/97 tests passing in every one of the 8 parallel rounds.

## Step 8: Finalize PRD — 2026-08-14T23:45:12.714Z

Task complete. `/home/ubuntu/github/CodingPRD/tasks/task_1878_snack_food_manufacturing_line_changeover/workspace/PRD_FINALIZED.md` produced — a byte-identical copy of PRD.md with **zero edits**, which is the correct outcome for this Step 7 diff.

## Summary on exit

**Line counts / %-delta:** PRD.md = 363 lines; PRD_FINALIZED.md = 363 lines; delta 0 lines, 0.0% (verified byte-identical via `diff`).

**Changes:** none.

**Rationale — the sole `<step_7_diff>` item is a pure fixture bug, not a PRD silence or impl mismatch:**
- The only fix was in `test_helpers/fixtures.py::setup_required_changeover` (snapshot of `"line"` moved to before `schedule_run(run2)`). No tests deleted, no `test_suite/` fixes, no `implementation/` fixes.
- The behavior the fixture bug touched — line `posture` derivation — is already uniquely pinned by PRD §2.8 (line 99: strict precedence `RUNNING` → `CLEANING` on changeover in `REQUIRED`/`CLEANING`/`SWAB_PENDING` → `BLOCKED` on oil `QUALITY_HOLD`/`DRAINING` → `IDLE`), and the implementation matches it exactly: `domain.py:131-142` (`line_posture`) implements that precedence verbatim, and `domain.py:379` (`dump_line`) recomputes it on every fetch, so the derived field is never stale. At the fixture's snapshot point (run1 COMPLETED → no RUNNING run; run2 not yet scheduled → no changeover exists; FryerOil ACTIVE), both PRD and impl deterministically yield `IDLE`. Nothing was left open for the impl to choose, and the impl did not diverge — so there is nothing to patch.

**Per-edit pre-edit search log (verification performed to justify the no-edit decision, mapped to the one step_7_diff item):**
- **(a) Subject:** derived `posture` on ProductionLine — precedence rule, recomputation timing, and response visibility — exercised by `test_line_posture_recomputes_across_changeover_lifecycle` via the fixed fixture.
- **(b) Impl paths enumerated and read/grepped:** `domain.py:131-142` (`line_posture`, full precedence chain); `domain.py:372-384` (`dump_line` serializer, the sole exposure point — `posture` computed fresh at line 379 on every fetch); `grep -rn "posture"` across `implementation/routes/` returned no other touchpoints (no stored posture field, no mutation-site writes); `domain.py:119-128` (`line_current_profile`, adjacent derived field sharing the fetch path); plus `test_helpers/fixtures.py:217-257` (fixed fixture) and `test_suite/test_04_changeover_gates.py:250-270` (disputed test, assertions IDLE → CLEANING → IDLE) and the 11 other fixture consumers at lines 33–302 (confirmed only the disputed test reads `ctx["line"]["posture"]`).
- **(c) Wording adjustment:** none — no edit committed. PRD §2.8's existing prose describes every enumerated impl path accurately (precedence order, set membership, derived-on-read behavior), so any insertion would have been pure restatement, and any narrowing would have risked a new mismatch.

## Step 9: Complete PRD — 2026-08-14T23:56:03.745Z

All changes verified. The diff shows 27 lines revised inline plus 5 lines added (net +5 lines, +3396 chars). Final summary:

## Summary

**Source:** `PRD_FINALIZED.md` (363 lines / 63,075 chars; identical to PRD.md) → **PRD_COMPLETED.md** (368 lines / 66,471 chars; +5 lines, +3,396 chars). Created via `cp`, edited in place only.

**Counts:** 25 ambiguity-pins (inserts), 3 mismatch-revisions.

**Mismatch-revisions:**
- §2.1 — revise — mismatch — "All five roles may use every read endpoint" contradicted impl; now carves out co-man agreement/slot reads as `PlantManager`+`CoManufacturer` only — implementation/routes/coman.py:14, 69, 77, 219, 229
- §2.6 — revise — mismatch — reject ratio was pinned "two decimal places, rounded half-up"; impl exposes the exact unrounded quotient, so the sentence now rounds only giveaway percentages and states the reject ratio is unrounded — implementation/domain.py:246-247
- §3.1 — revise — mismatch — "for an `OVEN` product the field is ignored and may be null"; impl stores and echoes a supplied `fry_target_temp_c` on OVEN products (never used in computation) — implementation/routes/products_lines.py:37-38, domain.py:202-203, 363

**Ambiguity-pins:**
- §2.1 — insert — ambiguity — empty `X-User-ID` header counts as missing → `ERR_UNAUTHENTICATED` — implementation/auth.py:17
- §2.2 — insert — ambiguity — pinned fallbacks `ERR_NOT_FOUND` (404) / `ERR_METHOD_NOT_ALLOWED` (405) / `ERR_INTERNAL` (500), plus three matching rows appended to the §5 catalogue — implementation/app.py:32-43
- §2.3 — insert — ambiguity — out-of-range `limit`/`offset` are clamped (limit to [1,100], offset to 0); non-integer values → `ERR_VALIDATION`; list ties on `created_at` broken by creation order — implementation/util.py:176-200, store.py:55-56
- §2.5 — insert — ambiguity — `version` is minted as 1 at creation — implementation/store.py:44-45
- §2.7 — insert — ambiguity — OCC checks are exact-equality; any mismatch in either direction → `ERR_STALE_VERSION` — implementation/routes/runs.py:53-54, oils.py:76-77
- §2.9 (tier 3) — insert — ambiguity — a body foreign-key field that is absent, blank, or not a string surfaces `ERR_VALIDATION` at the FK-resolution tier, not a 404 — implementation/routes/runs.py:28-38 (same pattern in checks.py, changeovers.py, oils.py, shipments.py, promos.py, coman.py)
- §2.9 (tier 5) — insert — ambiguity — missing/malformed/non-object JSON body treated as an empty object — implementation/util.py:65-71
- §3.1 — insert — ambiguity — `allergen_profile` is a required array (may be empty) — implementation/routes/products_lines.py:20-22
- §3.1 — insert — ambiguity — duplicate product name → `ERR_VALIDATION` — implementation/routes/products_lines.py:43-45
- §3.1 — insert — ambiguity — `seasoning_target_pct` is zero or greater — implementation/routes/products_lines.py:34
- §3.1 — insert — ambiguity — duplicate line name → `ERR_VALIDATION` — implementation/routes/products_lines.py:78-80
- §3.2 — insert — ambiguity — cancelled runs occupy no interval; excluded from overlap and cleaning-buffer checks — implementation/routes/runs.py:56-57
- §3.2 — insert — ambiguity — auto-created changeovers supersede (cancel) still-`REQUIRED` changeovers on the line, same as manual creation — implementation/routes/runs.py:121, 131-134
- §3.3 — insert — ambiguity — begin-cleaning on a `NONE` changeover → `ERR_INVALID_STATE` — implementation/routes/changeovers.py:72-73
- §3.3 — insert — ambiguity — when several fresh `VALIDATED` changeovers match a run start, the earliest-created is consumed — implementation/routes/runs.py:219-223
- §3.4 — insert — ambiguity — `lbs_fried_since_last_check` required, zero or greater; `avg_fry_temp_c` optional for OVEN products and stored verbatim when supplied — implementation/routes/checks.py:25, 29-30
- §3.4 — insert — ambiguity — temperature factor is 1.0 when no temperature applies (OVEN product or missing sample temp) — implementation/domain.py:201-205
- §3.4 — insert — ambiguity — movement `unit_price_cents_per_gal` must be a non-negative integer of cents when required — implementation/routes/oils.py:67
- §3.4 — insert — ambiguity — a full-drain `DISCARD` is forbidden while any run on the line is `RUNNING` → `ERR_INVALID_STATE` (same prohibition as begin-change) — implementation/routes/oils.py:80-84
- §3.5 — insert — ambiguity — completion actuals are required but unconstrained beyond type (cases integral); `accepted_cases` carried as 0 from creation until completion (with matching carve-out in §3.6's null-until-trigger sentence) — implementation/routes/runs.py:287-290, 310
- §3.6 — insert — ambiguity — per-case actual margin is null before completion and whenever `accepted_cases` is zero — implementation/domain.py:300-306
- §3.7 — insert — ambiguity — a null per-case margin never satisfies the dispatch floor — implementation/routes/shipments.py:149-153
- §3.8 — insert — ambiguity — display-case creation enforces no product match between the window's product and the run's product — implementation/routes/promos.py:114-147
- §3.8 — insert — ambiguity — `BUILT`/`CANCELLED` are terminal for the build action (`ERR_ALREADY_TERMINAL`); cancelling a `CANCELLED` case likewise — implementation/routes/promos.py:179-180, 203-204
- §3.9 — insert — ambiguity — duplicate co-manufacturer name → `ERR_VALIDATION` — implementation/routes/coman.py:23-25

No new sections were added; all edits are inline sentence inserts/revisions plus three catalogue rows. Every endpoint, transition, formula, validation rule, default, error path, and serializer field in `implementation/` was walked; everything not listed above was already uniquely pinned by the PRD.
