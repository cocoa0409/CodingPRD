# Worklog — task_2755_berry_harvest_labor_packing_operations

## Step 1: Create task directory — 2026-09-04T16:50:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2755_berry_harvest_labor_packing_operations` and `workspace/` (pre-assigned path from the entrance invocation; no index auto-allocation performed).

## Step 2: Generate scaffold — 2026-09-04T18:32:00.000Z

Scaffold for task 2755 is complete and lint-clean.

Output files (`tasks/task_2755_berry_harvest_labor_packing_operations/`):
- `SCAFFOLD.yaml` — 3430 lines — keys: scenario, domain_name, api_prefix, response_envelope, complexity_profile, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles — **no** `scaffold_difficulty_design`, **no** `scaffold_corner_design`
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1608 lines — `scaffold_difficulty_design` only
- `SCAFFOLD_CORNER_DESIGN.yaml` — 5041 lines — `scaffold_corner_design` only

All three parse under PyYAML and end at valid section/instance boundaries (no mid-sentence truncation). Every file was built incrementally with chunked appends.

Contents:
- §1.0–§1.7: domain `berry-harvest-ops`, prefix `/berry-ops`; **11 entities** (Block, WaterTest, Crew, Picker, HarvestWindow, PickSession, PayrollRun, FruitLot, CoolingTunnel, BuyerCommitment, LotAllocation), **9 state machines**, 2 concurrency rules (stale tunnel / stale commitment version), **13 calculations**, **66 validations** (explicit priority ladder 1–66), **58 endpoints**, **60 error ids**, **7 roles** (SoD role model, `Picker` entity-backed).
- §1.8: **9 rule_ids**, **19 instances** (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant).
- §1.9: **9 sections**, **94 instances** — entities 13, state_machines 18, calculations 22, validations 21, endpoints 4, errors 2, rbac 7, cross_cutting_complexity_layers 6, consistency_model 1. Of these, 74 carry full `test_recipe`s and 20 are `excluded_because` stubs (each citing a real §1.8 `<rule_id> / <instance_name>`; verified, no stub has a `test_recipe`).

Verification:
- Names unique across the §1.8 ∪ §1.9 union (19 + 94, zero collisions, zero intra-file dupes).
- All 60 error ids are triggered by at least one §1.8/§1.9 instance, including the two OCC ids `ERR_STALE_TUNNEL_VERSION` / `ERR_STALE_COMMITMENT_VERSION` (each tested as a 412 followed by a re-read-and-retry success in `cross_cutting_complexity_layers`).
- Forbidden concurrency vocabulary swept to zero across all three files.
- Stripped the leaked directive line "Generate task harder than expert level!" from SCAFFOLD.yaml's `scenario` (it would otherwise reach PRD.md); the scenario text itself is otherwise verbatim.

Lint verdict (verbatim, final run):
```
Coverage
  §1.5 endpoints declared:    58
  §1.1 entities declared:     11
  §1.8 instances scanned:     19
  §1.9 instances scanned:     74
  Calls scanned (§1.8+§1.9):  848

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

No sibling task directory was read, listed, globbed, or grepped at any point.

Orchestrator verification: `grep -rn "harder than expert"` over the task dir returns zero hits — the difficulty directive did not leak into any scaffold artifact.

## Step 3: Copy shared files — 2026-09-04T18:33:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T18:52:00.000Z

PRD generation for task 2755 is complete.

**Output:** `workspace/PRD.md` — **490 lines**, 112,805 bytes. Final section heading: **`## 5. Error Code Catalogue`**, ending at the last row of the 60-row error table (`| ERR_CREW_LEDGER_NOT_CLEAR | 422 |`) — a completed section boundary, no audit footer, no mid-sentence truncation. Written incrementally (one Write + six `cat >>` heredoc appends), so no output-cap loss.

**Structure:** §1 Introduction; §2 with 11 subsections (2.1 RBAC, 2.2 fixed response block verbatim, 2.3 pagination, 2.4 identity/versioning/append-only water register, 2.5 logical clock, 2.6 units & rounding, 2.7 path resolution + full 66-rule priority order, 2.8 OCC guards, 2.9 cascade discipline, 2.10 segregation of duties, 2.11 filtered reads/discovery channels); §3 with 8 subsections (blocks & water program, crew recruiting/certification, harvest windows, the picker's day, pay periods, cold chain & repack, buyer programs, reversals & invariants); §4 with the 58-row 4-column endpoint table preceded by the 201-vs-200 paragraph; §5 with the 60-row 2-column error table.

**Hard Contract results (all mechanically verified, not eyeballed):**
- **Contract 1 — Field-Name Coverage: PASS.** 153 required names (143 entity fields + POST body identifiers + 16 query params + 11 path params) checked as literal backticked strings: 0 missing. Independent passes: common fields 4/4; query params 16/16; entity enum values 52/52; state-machine states 31/31; quoted reason-code literals 4/4 — all 0 missing.
- **Contract 2 — Rule Coverage: PASS.** All 66 validation priorities appear as ordered numbered entries in §2.7 with 0 missing priorities and 0 missing validation error ids; both concurrency rules in §2.8; all 13 calculations described (including both dual-variant pairs and their worked contrasts); all 9 state machines with every transition covered (19 via same-paragraph state pairs rather than an explicit arrow, 0 absent); all 58 endpoints' side effects, 7 roles and 60 error ids present in the prose body of §1–§4 (0 of 60 missing outside the §5 table).
- **Contract 3 — §3 Path Purity: PASS.** 284 distinct backticked tokens in §3 scanned: 0 leading-slash paths, 0 bare HTTP methods, 0 method+path combinations, 0 stray slashes.

**Two corrections caught by verification and fixed:** seven error ids written in §3.5/§3.7 prose were invented rather than scaffold-declared, and were replaced with the real ones (`ERR_PERIOD_HAS_UNRESOLVED_SESSIONS`, `ERR_CREW_RUN_ALREADY_LOCKED`, `ERR_INVALID_COLD_CHAIN_STATE`, `ERR_BLOCK_WATER_NOT_COMPLIANT`, `ERR_SHIP_OUTSIDE_PROGRAM_WINDOW` for both the shelf-life-expiry and delivery-window branches, `ERR_INVALID_COMMITMENT_STATE`, `ERR_INVALID_ALLOCATION_STATE` for the still-reserved-line settle gate). A final scan confirms 0 invented ids remain. Also patched §3.6 to add the lot's `field_pulp_temp_f` input, its full unset-field list at creation, and the repack child's copied cooling fields.

**Scaffold gaps resolved (recorded here, not in the PRD):** window close and window cancel-from-`CONFIRMED`/`SUSPENDED` have no dedicated error id, so both report `ERR_INVALID_WINDOW_STATE`; the settle-time "no `RESERVED` line" gate has no dedicated id, so it reports `ERR_INVALID_ALLOCATION_STATE`; `support_plan_complete` follows the entity-field/priority-44 definition rather than the narrower endpoint wording; the ship-time food-safety-hold check is stated in §3.7 while §2.7 keeps priority 40's exact three-endpoint scope. Neither withheld design file was opened, and no sibling task directory was read.

Orchestrator verification (truncation guard): `tail` of PRD.md ends at the final row of the §5 error table — a real section boundary, not mid-sentence. 27 headings present, §1 through §5 all closed. `grep -c "harder than expert" PRD.md` = 0.

## Step 6: Generate implementation — 2026-09-04T19:39:00.000Z

(Steps 5 and 6 were launched concurrently in a single orchestrator message; Step 6 returned first, so its entry is recorded here ahead of Step 5's.)

## Implementation delivered

`workspace/implementation/`

| file | lines |
|---|---|
| `app.py` | 74 |
| `config.py` | 150 |
| `db.py` | 197 |
| `errors.py` | 148 |
| `response.py` | 105 |
| `util.py` | 165 |
| `validation.py` | 286 |
| `routes/__init__.py` | 0 |
| `routes/helpers.py` | 29 |
| `routes/blocks.py` | 189 |
| `routes/crews.py` | 247 |
| `routes/windows.py` | 226 |
| `routes/sessions.py` | 374 |
| `routes/lots.py` | 370 |
| `routes/sales.py` | 312 |
| `services/__init__.py` | 0 |
| `services/calc.py` | 433 |
| `services/cascade.py` | 141 |
| `start.sh` | 14 |
| `requirements.txt` | 1 |
| **total** | **3461** |

Every file ends at a complete statement; `py_compile` clean; no `__pycache__` or stray files left behind.

## Coverage verified programmatically

- **Endpoints:** 58 domain routes registered, exactly matching the 58 rows of the PRD §4 table (Flask's `/static/<path>` is the only extra rule).
- **Errors:** all 60 catalogue ids present with **zero** HTTP-status mismatches against the PRD §5 table, and every one is referenced by a `fail(...)` site outside `errors.py` (none unreachable).
- **Entities:** all 11 scaffold entities created through the API; field sets match `SCAFFOLD.yaml` exactly — no missing, no extra field on any entity. The only default divergences are the 9 where the PRD explicitly overrides the scaffold's `null` (session money figures at 0 per §3.4; `available_lbs` = `net_packed_lbs` per §3.6; derived `hygiene_training_expires_on` per §3.3).
- **Rules/calcs:** exercised end-to-end including the 5-step tally pricing (both `MEETS_STANDARD` and `BELOW_STANDARD` derate, H2A vs DOMESTIC housing cap), period settlement with `reconciliation_delta_cents`, the 4-charge shelf-life decay, repack lineage/mass balance, half-open tunnel occupancy (back-to-back legal, overlap refused), 12-hour block re-entry buffer, both version guards (412), all three SoD splits, the quarantine and lot-rejection cascades, and the FILLED / SHORTFALL / DEFAULTED settlement branches.

## Bug found and fixed

`open_lbs` was being initialised to `volume_commitment_lbs` on commitment creation. PRD §3.7 says it is "not yet determined" and `SCAFFOLD.yaml:844` gives `default: null`, so it now starts `null`, and rule 63 (`ERR_COMMITMENT_OVERBOOKED`) derives `volume − committed` when the stored value is still null so the first allocation still validates.

## Smoke tests

Two scenario suites (~200 assertions, 130+ requests) pass with **0 failures**: `/tmp/smoke_2755.py` (H2A strawberry happy path + settlement + water cascade) and `/tmp/smoke2_2755.py` (DOMESTIC blueberry, quarantine/resume, dispute cycle, repack, reject cascade, shortfall + default settlement).

Live HTTP on `PORT=18755` via `bash start.sh` confirmed the §2.2 envelope byte-for-byte: `201` create with `meta{api_request_id: "req_…", api_request_timestamp}` / `response_type: "object"` / `data`; list reads add `limit/offset/total_count/has_more` with `response_type: "array"`; errors return `response_type: "error"` with `data{error_id, message}` and a two-key `meta` (verified on 400/401/403/404/409/412/422). Fresh boot has all 11 tables empty and the logical clock at exactly `2026-08-01T00:00:00Z`.

`start.sh` idempotence checked across three kill/relaunch cycles; the launched pid **is** the `python3 app.py` pid (`exec` preserves it), so the harness's per-test kill leaves no orphan holding the port. Only its own PIDs were killed by explicit pid — no `pkill`. `worklog.md`, `test_suite/` and `test_helpers/` were never touched or read.

## Step 5: Generate unit tests — 2026-09-04T20:49:00.000Z

Test generation is complete. Both output directories are at the task root; `workspace/` contains only `INSTRUCTION.md`, `PRD.md` and `implementation/` (never read or written).

## Files written

**`test_helpers/`** (Stage 1)

| file | lines |
|---|---|
| `__init__.py` | 21 |
| `constants.py` | 195 |
| `api_errors.py` | 158 |
| `types.py` | 241 |
| `api_client.py` | 515 |
| `test_users.py` | 148 |
| `factories.py` | 439 |
| `assertions.py` | 283 |
| `fixtures.py` | 1069 |

**`test_suite/`** (Stage 2)

| file | lines | tests |
|---|---|---|
| `conftest.py` | 22 | – |
| `test_01_block_and_water_register_shape.py` | 425 | 12 |
| `test_02_season_lifecycle_transitions.py` | 771 | 13 |
| `test_03_derived_figures_and_thresholds.py` | 963 | 12 |
| `test_04_request_and_labor_refusals.py` | 612 | 10 |
| `test_05_packhouse_and_program_refusals.py` | 784 | 9 |
| `test_06_reads_links_and_error_surface.py` | 527 | 7 |
| `test_07_role_boundaries_and_duty_splits.py` | 427 | 7 |
| `test_08_concurrency_guards_and_period_views.py` | 407 | 4 |
| `test_09_dual_variants_and_composed_formulas.py` | 772 | 10 |
| `test_10_cyclic_paths_and_deep_cascades.py` | 624 | 8 |
| `test_11_priority_pairs_boundaries_and_reversals.py` | 627 | 12 |
| `test_12_cross_entity_gates_and_interval_conventions.py` | 552 | 8 |

## Coverage

- **112 tests total.**
- **§1.8 (queue A, Difficulty): 19 of 19 instances translated, 38 tests** — every instance has exactly 2 tests, one per discriminating arm. All 8 rule_ids covered (`dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`).
- **§1.9 (queue B, Corner): 74 of 74 non-stub instances translated, 74 tests.** The 20 `excluded_because:` stubs were not translated (by contract).
- **SKIPPED instances: none.** Every non-stub instance passed the PRD-first two-condition filter.

## Verification run over the whole suite

- `ast.parse` clean on all 13 files; every file ends at a complete statement.
- Citation checker: every quoted string in every docstring is a literal substring of `workspace/PRD.md` (0 misses), including quotes containing `−`, `×`, `°F` and `→`.
- Exactly one `Design:` tag per test, always the final docstring line; all 112 tags resolve to real non-stub instances in the two design yamls; no dual tags, no unknown tags, no stub tags.
- No `skip` / `skipif` / `xfail` markers; no occurrence of the word "scaffold"; no duplicate top-level defs.
- Static attribute + signature check against the helper modules: every `e.`/`a.`/`f.`/`x.`/`u.`/`api.` symbol exists and every call's positional/keyword arguments match the target signature (0 issues).

## Design-index vs PRD conflicts resolved in PRD's favour (flagged to Step 7)

- Difficulty instance 1's yaml window (`08-03T06:00 → 08-04T14:00`) violates PRD L244's same-calendar-date rule; replaced by two single-day windows on one block, 12 h apart.
- `allocation_ship_requires_lot_cold_chain_cooled` asserts `fill_status == FILLED` after shipping; PRD stamps `fill_status` only at settlement, so the test asserts `PENDING` and `fill_pct == 1.0000`.
- `session_dispute...` asserts `PickSession.revision_count`; PRD's field is `tally_revision_count`.
- The lot-rejection cascade's `committed_lbs_exposure` is not a declared field; assertions use `committed_lbs` and cite §3.7's recompute sentence. Two figures were deliberately left unasserted where the PRD is genuinely silent: the window's `packed_lbs` after a rejection, and the rejected lot's `allocated_lbs` (§3.6 "drives `available_lbs` to 0.00" conflicts with §3.7's restore-on-release wording).

## Step 7: Run tests and iterate — 2026-09-04T21:05:00.000Z

Clean 8-round sweep achieved.

## Summary

**Iterations run:** 2

**Iteration 1** — 8/8 rounds red, but with exactly one deterministic failure (111 passed / 1 failed in every round, no flakiness, no load-induced connection or lsof errors):

`test_a_shipped_line_is_terminal_and_a_late_pickup_leaves_the_program_window` in `test_05_packhouse_and_program_refusals.py`
- `AssertionError: assert '2026-08-08' == '2026-08-10'` on `stored_second["shelf_life_expires_on"]`.

**Diagnosis:** STEP 1 passed — PRD §3.6 verbatim covers the shelf-life decay formula and `shelf_life_expires_on` ("The result is the base less the grade derate less all three penalties…", "`shelf_life_expires_on` is then the calendar date of `cool_complete_at` advanced by `verified_shelf_life_days` days"), and it uniquely determines the value. STEP 2 found the test wrong: the fixture `cooled_lot` in `test_helpers/fixtures.py` packs at `2026-08-03T09:00:00Z` and starts cooling at `13:00:00Z`, so `field_delay_hours` is 4.00 — 2.0 h beyond the 2-hour tolerance, a 2-day field-heat penalty. STRAWBERRY base 7 − 0 (grade A) − 2 (field heat) − 0 (`cool_hours` exactly 4.00, the target) − 0 (exit exactly 34.0 °F, the target) = 5 days verified, so `2026-08-03 + 5 = 2026-08-08`. The test's `2026-08-10` silently assumed no field-heat charge. `services/calc.py::shelf_life_days` and `routes/lots.py` complete-cooling were verified line-by-line against PRD §3.6 and are correct.

**Tests deleted:** none. No test failed the STEP 1 coverage or unique-derivability checks.

**Fixes applied to `test_helpers/`:** none. The `cooled_lot` fixture's instants are PRD-consistent; only the test's expected value was wrong.

**Fixes applied to `test_suite/`:** `test_05_packhouse_and_program_refusals.py`, `test_a_shipped_line_is_terminal_and_a_late_pickup_leaves_the_program_window` — corrected the mis-derived `shelf_life_expires_on` expectation from `2026-08-10` to `2026-08-08`, and strengthened the test by additionally asserting `verified_shelf_life_days == 5` with the per-term PRD §3.6 derivation recorded inline. This makes the assertion strictly more faithful to PRD, not less; the test's primary assertions (`ERR_INVALID_ALLOCATION_STATE` on releasing a shipped line, `ERR_SHIP_OUTSIDE_PROGRAM_WINDOW` on the late pickup) were untouched and still fire for their intended reasons.

**Fixes applied to `implementation/`:** none — the implementation was PRD-faithful throughout.

**Iteration 2** — all 8 parallel rounds green, 112 passed / 0 failed / 0 errors each. No stray `test_suite/` or `test_helpers/` under `workspace/`, storage is in-memory only, and `worklog.md` was not modified.

Orchestrator verification: independently read all 8 `results.$i.json` (mtime 20:55) — each reports `passed == total == 112`. Sweep artifacts are present on disk, not merely claimed.

Step 8 skip condition: NOT met (1 `test_suite/` fix), so Step 8 runs.

## Step 8: Finalize PRD — 2026-09-04T21:06:00.000Z

## Result: zero edits — `PRD_FINALIZED.md` is byte-identical to `PRD.md`

- `PRD.md`: 490 lines. `PRD_FINALIZED.md`: 490 lines. Delta: 0 lines, 0.0%. Identical md5 (`8307e555b2d58260e6dc38ae6f7c392f`).
- Change bullets: none.

### Justification against the single Step 7 diff item

The diff contains one item: a test-side arithmetic correction in `test_05_packhouse_and_program_refusals.py::test_a_shipped_line_is_terminal_and_a_late_pickup_leaves_the_program_window` (`shelf_life_expires_on` expectation `2026-08-10` → `2026-08-08`, plus a strengthened `verified_shelf_life_days == 5`). Zero implementation fixes, zero test deletions, zero `test_helpers/` fixes. The item is neither a PRD silence nor a PRD/impl mismatch:

**Subject: verified shelf-life decay + `shelf_life_expires_on`.**

Impl paths enumerated and read:
- `services/calc.py` — `shelf_life_days()` (the only shelf-life derivation site), plus `price_shipped_lines()` (the only downstream consumer of `verified_shelf_life_days`).
- `routes/lots.py:235-237` (start-cooling: `field_delay_hours` then forecast variant), `:263-269` (complete-cooling: `cool_hours`, `verified_shelf_life_days`, `shelf_life_expires_on`), `:303-348` (repack child: copies + `verified - 1` floored at 1, expiry from the **source's** `cool_complete_at`).
- `util.py` — `hours_between()` (half-up to 2 dp), `iceil`/`ifloor`, `add_days`, `date_str`.
- `config.py:110-121` — `VARIETY_BASE_SHELF_LIFE`, `GRADE_DERATE`, `FIELD_HEAT_MAX_HOURS`, `TARGET_COOL_HOURS`, `EXIT_TEMP_TARGET_F`, `EXIT_TEMP_STEP_F`, `SHELF_LIFE_FLOOR_DAYS`.

Every one of these is already uniquely pinned by PRD §3.6 (lines 314, 316, 318, 320, 324) with matching constants and matching rounding directions:
- base 7/14/5/6 and derate 0/1/3 — verbatim in PRD line 318, exact match to `config.py`.
- field-heat penalty `iceil(max(0, field_delay_hours − 2.0))` — PRD: "the amount by which the delay exceeds 2.0 hours, floored at zero, then rounded **up**".
- cooling penalty `iceil(max(0, cool_hours − 4.0))` — PRD: "works identically against the four-hour … target".
- temperature penalty `ifloor(max(0, exit − 34.0) / 2.0)`, and 0 when no exit temp — PRD: "complete two-degree steps … rounded **down**"; forecast "fixes the temperature penalty at 0".
- floor of 1 day; `shelf_life_expires_on = date(cool_complete_at) + verified_shelf_life_days` — PRD line 320 verbatim.
- `field_delay_hours` = half-up-2dp hours from `pack_completed_at` to `cool_start_at` (PRD line 314), and the penalty is charged against that stored, rounded figure in both impl and PRD wording.

Recomputing the fixture by PRD prose alone reproduces the implementation exactly: pack `2026-08-03T09:00:00Z`, cool start `13:00:00Z` → `field_delay_hours` 4.00 → field penalty `ceil(2.00)` = 2; `cool_hours` exactly 4.00 → 0; exit exactly 34.0 °F → 0; STRAWBERRY 7 − 0 (grade A) − 2 − 0 − 0 = 5; `2026-08-03 + 5 = 2026-08-08`. The old test expectation of `2026-08-10` was arithmetic that silently dropped the field-heat charge — a fresh implementer reading PRD.md alone cannot land on it.

The test's untouched primary assertions are likewise already pinned: `ERR_INVALID_ALLOCATION_STATE` for releasing a non-`RESERVED` line (PRD line 145, invariant 37) and `ERR_SHIP_OUTSIDE_PROGRAM_WINDOW` for a clock date past `shelf_life_expires_on` (PRD lines 153 invariant 59 and 336).

Since there is no PRD silence and no PRD/impl divergence anywhere in the enumerated set, any edit would have been manufactured and would risk introducing a fresh mismatch for Step 9 to undo.

Orchestrator note: a byte-identical `PRD_FINALIZED.md` is a legitimate Step 8 outcome when Step 7 applied zero `implementation/` fixes and zero deletions. Step 9, by contrast, must not be byte-identical — it runs a full impl-vs-PRD scan and is partitioned below into three sequential module-scoped passes to avoid the known single-pass no-op failure.

## Step 9: Complete PRD — 2026-09-04T21:48:00.000Z

Run as **three sequential module-partitioned passes** over one shared `workspace/PRD_COMPLETED.md`, plus a fourth targeted cleanup, rather than one monolithic pass (a single pass reliably no-ops and leaves PRD_COMPLETED byte-identical). Pass 1 did the `cp` from `PRD_FINALIZED.md`; passes 2, 3 and the cleanup edited in place with Edit only.

### Pass 1 — cross-cutting infrastructure + blocks/water + crews/pickers
Slice: `app.py`, `config.py`, `db.py`, `errors.py`, `response.py`, `util.py`, `validation.py`, `routes/helpers.py`, `routes/blocks.py`, `routes/crews.py`. Territory: §2.1–§2.11, §3.1, §3.2, block/water/crew/picker rows of §4/§5.

`PRD_FINALIZED.md` 490 lines / 112,805 chars → `PRD_COMPLETED.md` 490 lines / 121,748 chars (**+8,943**, 29 changed line groups). **24 ambiguity-pins, 9 mismatch-revisions (33 edits).**

- §2.1 — revise — ambiguity — header check treats whitespace-only as empty, role match exact/case-sensitive, `X-User-ID` otherwise unconstrained — `validation.py:23-28`
- §2.1 — revise — mismatch — `Picker` bullet: picker-record reads are *not* narrowed to the caller's own row (session reads are) — `routes/crews.py:222`, `routes/sessions.py:102`
- §2.1 — revise — mismatch — "three endpoints a Picker may reach" corrected: a fourth (single-picker read) admits `Picker` with no identity resolution — `routes/crews.py:220-223`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 upper-case-alnum chars — `util.py:164-165`
- §2.2 — revise — mismatch — `api_request_timestamp` comes from the host's real clock, not the logical clock — `response.py:24-28`, `util.py:153`
- §2.2 — insert — ambiguity — unset fields render as JSON `null`, never omitted — `response.py:31-35`
- §2.2 — insert — ambiguity — pagination meta omitted from object responses; traceability roll-up and clock setter return computed payloads with no `id`/audit triple — `response.py:44-45`, `routes/blocks.py:115,189`
- §2.3 — revise — ambiguity — `limit`/`offset` bounds **rejected, not clamped** (`ERR_VALUE_OUT_OF_RANGE`), non-integer → `ERR_INVALID_REQUEST`, empty string → default, over-large offset is a legal empty page; created_at ties broken by insertion order — `response.py:78-97`, `db.py:97-99`
- §2.3 — revise — ambiguity — `has_more` = effective offset + rows returned < `total_count` — `response.py:53`
- §2.4 — revise — mismatch — `id` is a canonical hyphenated UUIDv4; `created_at`/`updated_at` read the host clock — `util.py:160`, `db.py:79-93`
- §2.5 — revise — mismatch — reworded the absolute "nothing reads the host wall clock": no *domain rule* does; audit and envelope timestamps do — `db.py:79`, `response.py:27`
- §2.5 — insert — ambiguity — clock response `data` carries only `current_utc`, echoed verbatim; instant may move either direction — `routes/blocks.py:182-189`, `db.py:68-70`
- §2.6 — insert — mismatch — declared digit counts are rounding scales, not rendering: values emit as JSON numbers (12.50 → `12.5`); inbound precision quantized, never rejected — `response.py:13-16`, `routes/blocks.py:30`
- §2.7 r10 — insert — ambiguity — string length bounds → `ERR_INVALID_REQUEST`, implicit 1-char minimum on every string, booleans satisfy no type, int fields reject fractional numbers, `null` only for optional fields; empty body = `{}`, invalid/non-object JSON = `ERR_INVALID_REQUEST`; undeclared fields ignored; body-less transitions never parse the body — `validation.py:99-197`
- §2.7 r12 — revise — ambiguity — added `planned_head_count` max 60 and `planting_year` 2000–2026 — `routes/crews.py:20`, `routes/blocks.py:21`
- §2.7 r25 — insert — ambiguity — the clear endpoint's `water_status` precondition also reports `ERR_INVALID_BLOCK_STATE`, after the hold check and before rule 48 — `routes/blocks.py:95-106`
- §2.9 — insert — ambiguity — inspection without mutation earns no `version` bump; a row reached twice is bumped exactly once — `services/cascade.py:13-30,81-100`
- §2.11 — insert — ambiguity — filters are exact case-sensitive equality, conjunctive, empty/absent ignored, unmatched value yields empty page, unknown query params ignored — `routes/helpers.py:18-29`
- §3.1 — insert — ambiguity — `sample_date` unconstrained; back-dated samples accepted and re-ordered into the window — `routes/blocks.py:121-145`
- §3.1 — revise — ambiguity — recording a sample always bumps the block's `version` even when nothing moves — `routes/blocks.py:147-155`
- §3.1 — insert — mismatch — the `FAILED` auto-quarantine interlock fires only when no hold is open; existing reason code/officer preserved, no second cascade — `routes/blocks.py:148-152`
- §3.1 — revise — ambiguity — `quarantine_reason_code` required non-empty string, no enum, no max length — `routes/blocks.py:84`
- §3.1 — revise — ambiguity — quarantine level 2 also clears `approved_by_user_id` on an `APPROVED → DISPUTED` session — `services/cascade.py:66`
- §3.1 — revise — ambiguity — clear takes no body; three preconditions and their error ids in evaluation order — `routes/blocks.py:91-108`
- §3.2 — revise — ambiguity — support plan: both counts required, both codes optional/nullable, whole-plan overwrite erases an omitted code, no max length — `routes/crews.py:25-30,135-139`
- §3.2 — insert — ambiguity — picker registration and hygiene re-recording never compare `X-User-ID` to `supervisor_user_id` — `routes/crews.py:191,235`
- §3.2 — insert — ambiguity — registration admitted on a crew in any status (incl. `RELEASED`); only `RECRUITING` advances to `STAFFED` — `routes/crews.py:212-216`
- §3.2 — revise — ambiguity — hygiene re-record: field required non-null, replaces unconditionally, touches only the picker — `routes/crews.py:233-247`
- §3.2 — revise — ambiguity — the `STAFFED` state gate fires ahead of both compliance gates — `routes/crews.py:148-159`
- §4 preamble — revise — ambiguity — trailing slash accepted on every path — `app.py:21`
- §4 row — revise — mismatch — GET `/blocks` also filters by `water_status` — `routes/blocks.py:68-75`
- §4 row — revise — mismatch — GET `/pickers/{picker_id}` is not restricted to the calling picker — `routes/crews.py:220-223`
- §5 preamble — insert — mismatch — `ERR_INVALID_REQUEST` also answers 404 (unrouted path) and 405 (wrong method) — `app.py:42-51`

### Pass 2 — harvest windows, pick sessions, wage guarantee, disputes, pay periods
Slice: `routes/windows.py`, `routes/sessions.py`, plus the `services/calc.py` / `services/cascade.py` functions they call. Territory: §3.3, §3.4, §3.5 and their §4/§5 rows. No `cp` run.

121,748 → 126,204 chars (**+4,456**), 490 lines throughout. **14 ambiguity-pins, 2 mismatch-revisions (16 edits).**

- §3.3 — insert — ambiguity — same-calendar-date violation reports `ERR_INVALID_DATE_RANGE` at priority 14 (ordering test first, same-date second), both yielding to priority-15 `ERR_INVALID_REQUEST` when either instant fails to parse; `start_at`/`end_at` stored and echoed verbatim incl. fractional-second width — `routes/windows.py:39-52`, `validation.py:267-271`
- §3.3 — revise — mismatch — re-entry instants compared exactly as parsed (fractional seconds included), not "at second resolution" — `util.py:15,93-109`, `services/calc.py:311-320`
- §3.3 — insert — ambiguity — confirmation tests the block only for `QUARANTINED` (a `RESTRICTED` block still confirms) and never examines the crew's status or `picker_count` — `routes/windows.py:104-120`
- §3.3 — insert — ambiguity — capacity ≤ 0 yields a requirement one picker beyond the cap, so confirmation fails `ERR_INSUFFICIENT_PICKERS` and stores nothing; capacity uses the stored rounded `window_hours` — `services/calc.py:71-79`
- §3.3 — insert — ambiguity — the open-time crew-status refusal is `ERR_INVALID_CREW_STATE`, after both block-posture gates and before the clock; `picker_count` evaluated last of the four — `routes/windows.py:136-153`
- §3.3 — insert — ambiguity — only a still-`OPEN` session blocks closing; `packed_lbs` is the 2-dp sum of `net_packed_lbs` over the window's non-`REJECTED` lots, recomputed before `harvested_clamshells` — `routes/windows.py:169-176`, `services/calc.py:220-226`
- §3.3 — revise — mismatch — resume also refuses a merely `RESTRICTED` block with `ERR_BLOCK_NOT_CLEARED`, recomputes `effective_pick_rate_lbs_per_hour` as well as `required_picker_count`, and re-tests neither the 60-picker cap nor the crew — `routes/windows.py:188-201`, `services/calc.py:82-86`
- §3.3 — insert — ambiguity — `cancel_reason_code` required non-empty verbatim string, no enum/max, shape-checked before the window's status — `routes/windows.py:209-215`
- §3.4 — insert — ambiguity — the window's calendar span is the single date its `start_at`/`end_at` share — `routes/sessions.py:65-68`
- §3.4 — insert — ambiguity — the uniqueness key is occupied whatever the existing session's status (`VOIDED`/`DISPUTED`/`SETTLED` included), tested after hygiene and before the `work_date` span; `work_date` echoed verbatim — `routes/sessions.py:62-68`
- §3.4 — insert — ambiguity — approval consults no window state at all — `routes/sessions.py:160-186`
- §3.4 — insert — ambiguity — a `CrewSupervisor` who is not the crew's `supervisor_user_id` gets `ERR_NOT_SESSION_SUPERVISOR`; `dispute_reason_code` required non-empty verbatim string, shape-checked before either ownership test — `routes/sessions.py:191-203`
- §3.5 — insert — ambiguity — inverted period dates are `ERR_INVALID_DATE_RANGE` while unparseable ones are `ERR_INVALID_REQUEST`, both decided before the body `crew_id` resolves; dates echoed verbatim — `routes/sessions.py:234-243`
- §3.5 — insert — ambiguity — crew membership at lock is read off the *picker*'s `crew_id`; `APPROVED`/`SETTLED`/`VOIDED` in-period sessions never block; `ERR_CREW_MISMATCH` checked after the unresolved/already-locked tests and only across binding sessions — `routes/sessions.py:304-321`, `db.py:135-137`
- §3.5 — insert — ambiguity — an empty stamped set records the four lock figures as 0/0.00 rather than null, while the six settlement figures stay unset until settle — `routes/sessions.py:333-338`
- §4 (GET `/pick-sessions/{id}`) — insert — ambiguity — a `Picker` caller's `X-User-ID` is resolved and compared to `picker_id`; another worker's session answers `ERR_NOT_SESSION_OWNER` — `routes/sessions.py:100-103`

No §5 edits needed: every error id in the slice already carried the impl's status.

### Pass 3 — field packing, cold chain, repack, buyer programs, allocation, shipping, settlement, cascades
Slice: `routes/lots.py`, `routes/sales.py`, `services/cascade.py` in full, plus the `services/calc.py` functions they call. Territory: §2.8, §3.6, §3.7, §3.8 and their §4/§5 rows. No `cp` run.

126,204 → 134,645 chars (**+8,441**), 490 lines. **13 ambiguity-pins, 10 mismatch-revisions (23 edits).**

- §2.8 — insert — ambiguity — expected-version fields are int-declared, so absent/non-integer is a 400 `ERR_INVALID_REQUEST`, not the 412 — `validation.py:150-186`, `lots.py:43`, `sales.py:33`
- §2.8 — insert — ambiguity — the version guard is the *only* role `version` plays; admission is the §3.6 interval scan, never a `committed_slots` comparison — `calc.py:291-302`
- §3.6 — insert — ambiguity — `target_pulp_temp_f` is documentary; the temp penalty uses the fixed 34.0 °F constant — `calc.py:245`, `config.py`
- §3.6 — insert — ambiguity — quarantine gate fires first of the four; window `status` never inspected; lot weight need not match the window's pack format; `pack_completed_at` unconstrained — `lots.py:131-142`
- §3.6 — revise — mismatch — the block field is `name`, not `block_name` (`block_name` exists only in the traceability payload) — `calc.py:281`, `blocks.py:18`
- §3.6 — insert — ambiguity — `REJECTED`/`REPACKED`/child siblings all consume traceability sequence numbers; `pack_completed_at` and cooling instants echoed verbatim; lot creation bumps the window's `version` by 1 — `calc.py:275-285`, `lots.py:149-166`
- §3.6 — revise — mismatch — `planned_cool_end_at` ≤ `cool_start_at` is `ERR_INVALID_DATE_RANGE` (priority 14, before tunnel resolution), not `ERR_TEMPORAL_ORDER_VIOLATION`; `entry_pulp_temp_f` has no range bound — `lots.py:199-209,41`
- §3.6 — revise — mismatch — a lot rejected while `COOLING` keeps that status and **keeps occupying** its slots; only cold-chain status matters — `calc.py:293-301`, `cascade.py:109-141`
- §3.6 — insert — ambiguity — stored `committed_slots` takes no part in admission and stays elevated after a mid-run rejection — `calc.py:291-302`, `lots.py:241`
- §3.6 — insert — ambiguity — `cool_hours` stays unset until completion — `lots.py:236-238`
- §3.6 — insert — ambiguity — `committed_slots` decrement floored at 0; `exit_pulp_temp_f` unbounded; neither disposition nor hold consulted — `lots.py:253-278`
- §3.6 — insert — ambiguity — `output_clamshell_count ≥ 1`; the three counts carry no range bounds, so negatives are mass-balance refusals — `lots.py:53-56,298`
- §3.6 — revise — mismatch — the repack child also copies `field_delay_hours` — `lots.py:331`
- §3.6 — insert — ambiguity — repack neither recomputes nor versions the parent window, and a later recompute counts the `REPACKED` source alongside its child — `lots.py:282-358`, `calc.py:220-226`
- §3.6 — revise — mismatch — rejection cascade rewritten: no `committed_lbs_exposure`, no per-line decrement; each distinct commitment's whole exposure block recomputed once — `cascade.py:117-130`, `calc.py:326-342`
- §3.7 — revise — mismatch — `risk_flag` evaluated at creation against coverage 0.0000 and can open `AT_RISK`; `open_lbs` opens explicitly unset — `sales.py:71-81`, `calc.py:345-349`
- §3.7 — insert — ambiguity — `cold_chain_status` unexamined on allocation; while `open_lbs` is null the overbooked test uses `volume_commitment_lbs − committed_lbs` — `sales.py:172-191`
- §3.7 — insert — ambiguity — the new line's six unset money/ship fields; coverage is internal, not a response field; `fill_status` untouched by recomputes — `sales.py:197-204`, `calc.py:340`
- §3.7 — insert — ambiguity — `risk_flag` is not re-evaluated at settlement — `sales.py:120-156`
- §3.7 — revise — mismatch — ship does a full exposure recompute; lot pound figures untouched; both lot statuses turn over on the first line, stranding the lot's other `RESERVED` lines — `sales.py:273-281`, `calc.py:326-342`
- §3.7 — revise — mismatch — release is a recompute from surviving rows, not an exact decrement; reason-code shape; lot version bumped regardless; the §3.6 cascade is explicitly *not* this operation — `sales.py:285-312`, `calc.py:255-272`
- §3.7 — insert — ambiguity — settlement evaluation order: commitment `OPEN`, then the clock, then the reserved-line scan — `sales.py:105-118`
- §3.8 — revise — mismatch — the release invariant stated as a rebuild-from-survivors rather than a delta decrement — `sales.py:303-311`
- §3.8 — revise — mismatch — cascade ordering: quarantined-block windows go by ascending `start_at` then `created_at` — `cascade.py:42-50`

Disposition of the three items passes 1/2 deferred to pass 3:
1. **Confirmed and fixed.** `committed_lbs_exposure` exists nowhere in `implementation/`; `cascade.py:129-130` calls `recompute_commitment_exposure`, rebuilding `committed_lbs`, `shipped_lbs`, `open_lbs`, `fill_pct`, `_coverage_pct` and `risk_flag` from surviving lines. §3.6 now says exactly that, and adds that a commitment behind two released lines of the same lot is versioned exactly once.
2. **Confirmed; cross-referenced, not restated.** `cascade.py:134-137` calls `recompute_window_packed` and versions the window; §3.6's rejection paragraph now points at §3.3's definition.
3. **Resolved in impl's favour.** `recompute_lot_balance` (`calc.py:261-263`) early-returns `available_lbs = 0.00` whenever `disposition_status == "REJECTED"`, so the rejected lot is forced to 0.00 and `allocated_lbs` recomputes to 0.00; §3.7's "restore to pre-allocation values" belongs solely to the release endpoint. Both sides now state this explicitly, so the §3.6-vs-§3.7 tension the test generator flagged is gone.

### Cleanup pass — four §2.7 residuals flagged by passes 2 and 3
Passes 2 and 3 each found §2.7 defects inside pass 1's territory that they were scoped out of editing. Rather than leave them, the orchestrator resumed pass 1's agent (context intact) with a §2.7-only cleanup brief. All four were genuine defects and all four are fixed.

134,645 → 135,593 chars (**+948**), 490 lines, 66 changed line groups vs `PRD_FINALIZED.md`. **4 mismatch-revisions.**

- §2.7 rule 40 — revise — mismatch — enumeration widened from three to four operations, adding shipping of an allocation line drawn on the lot; all four gate sites confirmed (`lots.py:217`, `lots.py:292`, `sales.py:176`, `sales.py:253`) — `routes/sales.py:253-254`
- §2.7 rule 39 — revise — mismatch — the `CLEARED`-posture gate now covers both opening and resuming a suspended window, and notes it sits behind rule 38's quarantine test on both transitions — `routes/windows.py:191-192` (and `:138-139`)
- §2.7 rule 26 — revise — mismatch — records that `ERR_INVALID_CREW_STATE` is also reachable from window opening (crew must be `CERTIFIED` or `ACTIVE`), evaluated not at position 26 but inside the opening sequence after rules 38/39, per §3.3; all four raise sites enumerated (`crews.py:132,149,170`, `windows.py:143`) — `routes/windows.py:141-145`
- §2.7 rule 12 — revise — mismatch — added `forecast_brix` 0–30 inclusive and `planned_volume_lbs` > 0; tightened `piece_rate_cents_per_clamshell` to 1–500 and `clamshell_net_weight_lbs` to > 0 and ≤ 5 — `routes/windows.py:24-27`, `routes/lots.py:32`

### Step 9 totals

`PRD_FINALIZED.md` 490 lines / 112,805 chars → `PRD_COMPLETED.md` 490 lines / **135,593 chars** (**+22,788 chars, +20.2%**), 66 changed line groups, **76 edits** (51 ambiguity-pins, 25 mismatch-revisions). Line count unchanged throughout — every edit is in-paragraph, no new sections.

Orchestrator verification: `md5sum` confirms `PRD_COMPLETED.md` (`fc7c8f89fedda3d80f483c46c09cd569`) differs from `PRD_FINALIZED.md` (`8307e555b2d58260e6dc38ae6f7c392f`) — the scan genuinely ran. All 27 headings intact; the file ends at the final §5 error row (`ERR_CREW_LEDGER_NOT_CLEAR | 422`). No file under `workspace/implementation/`, `test_suite/` or `test_helpers/` was modified after 19:31, well before the 20:55 green sweep, so all 8 `results.$i.json` at 112/112 still describe the shipped code. `workspace/` holds only `INSTRUCTION.md`, `PRD.md`, `PRD_FINALIZED.md`, `PRD_COMPLETED.md`, `implementation/` and `sweep.log` — no stray `test_helpers/`/`test_suite/`. `find . -name worklog.md` returns exactly one file (the task root), so no cwd-drift strays.

## Pipeline complete — 2026-09-04T21:50:00.000Z

All nine steps finished. Final state: 112 tests, 8/8 parallel rounds green (112 passed / 0 failed / 0 errors each), `workspace/PRD_COMPLETED.md` written.
