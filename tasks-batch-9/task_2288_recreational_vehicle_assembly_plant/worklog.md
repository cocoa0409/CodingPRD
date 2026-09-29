# Worklog — task_2288_recreational_vehicle_assembly_plant

## Step 1: Create task directory — 2026-09-01T14:45:52.000Z

Created `tasks/task_2288_recreational_vehicle_assembly_plant/` and `tasks/task_2288_recreational_vehicle_assembly_plant/workspace/` (pre-allocated task name used verbatim; no index scan).

## Step 2: Generate scaffold — 2026-09-01T16:52:08.000Z

All three artifacts are complete and the linter is clean.

## Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2288_recreational_vehicle_assembly_plant/`)

- `SCAFFOLD.yaml` — 3455 lines, §1.0–§1.7 only (no design keys). 15 entities, 67 endpoints, 61 error ids, 7 roles, 17 validation priority rows, 2 `concurrency_rules`. Profile: quota/allocation + workflow orchestration, `graph` topology, `parallel` state-machine shape (UnitOrder carries independent `status` × `financing_status`), `segregation_of_duties` role model, `immediate` consistency, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, selector_policy, ops_run_checkpoint]`.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1859 lines, 19 instances, ≥2 per §0.5 rule (`transitive_cascade` has 3).
- `SCAFFOLD_CORNER_DESIGN.yaml` — 5008 lines, 64 instances over all nine claim-extraction-guide sections: entities 14, state_machines 18, calculations 13, validations 10, endpoints 7, errors 5, rbac 3, cross-cutting layers 6, consistency model 1. 13 of those are `excluded_because` stubs pointing at §1.8 instances by name; the rest carry full seven-clause recipes.

## Work completed this session

Finished the corner file: the last two `errors` instances (quality-gate band — booth DOWN, station mismatch, unpassed water test/PDI, inspector segregation; and the fiscal band — payment one cent over principal, exhausted goodwill budget with a zero-goodwill claim still approving), the `rbac` section (all seven roles exercising their own exclusive operations, seven cross-role denials including a 403-before-404 probe, and the approver-cannot-pay duty split), the `cross-cutting complexity layers` section (real OCC instance covering both §1.2.1 rules with stale → refresh → success → re-stale, real pagination-with-filtering instance including count recomputation after a mutation, plus four stubs for cascade / dual-variant / selector / ops-checkpoint), the `consistency model` instance, and one extra `endpoints` instance added to close endpoint coverage.

## Verification

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
  §1.5 endpoints declared:    67
  §1.1 entities declared:     15
  §1.8 instances scanned:     19
  §1.9 instances scanned:     64
  Calls scanned (§1.8+§1.9):  1122
```

Additional scripted audits, all passing: every one of the 61 error ids is referenced by at least one design instance; all 67 endpoints are exercised by at least one call; zero duplicate instance names across both design files; zero unbound `${var}` placeholders in payloads, paths, `as_user_id` or asserts; every `excluded_because.difficulty_instance` resolves to a §1.8 name and carries no `test_recipe`; the file split holds (`SCAFFOLD.yaml` has neither design key).

Fixes made while auditing: eight lint (d) capture violations (`$.data.total_count` on array-output list endpoints, plus `schedule_subtotal_cents`, `matched_chassis_receipt_id` and `paid_at` which are not declared on the returned entity) were rewritten to declared fields with the counts asserted in prose; a post-submit status assert said `SUBMITTED` where §1.2 says `CONFIG_VALIDATED`; a campaign referenced a non-existent lot code; and two uses of banned concurrency vocabulary ("Simultaneously occupiable bays" in §1.1 and "simultaneously" in one corner assert) were reworded, so the forbidden-vocabulary scan is now empty across all three files.

## Step 3: Copy shared files — 2026-09-01T16:52:27.000Z

Copied `INSTRUCTION.md` from project root to `tasks/task_2288_recreational_vehicle_assembly_plant/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T17:06:55.000Z

All three hard contracts verified. The PRD is written.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2288_recreational_vehicle_assembly_plant/workspace/PRD.md` — 13,208 words, titled `# RV Assembly Plant API — Product Requirements Document`.

**Structure:** §1 Introduction (3 paragraphs); §2 with eleven subsections (2.1 Caller Identity and the Seven Plant Roles, 2.2 verbatim envelope block, 2.3 Pagination and List Ordering, 2.4 Resource Identity/Timestamps/Version Counter, 2.5 The Logical Clock and the Daily-Close Checkpoint, 2.6 Money/Station Hours/Rounding Discipline, 2.7 Version Pinning and Optimistic Concurrency, 2.8 The Validation Precedence Ladder, 2.9 Cascade Discipline Across Aggregates, 2.10 Enumerated Vocabularies, 2.11 Segregation of Duties Within a Role); §3 with nine domain-grouped subsections (master data and supply intake, dealer ordering and configuration, slots and the allocation ledger, chassis matching and release, station advancement and installation, quality gates and rework/scrap, shipment and floor-plan financing, warranty adjudication, recall campaigns and the supplier trust score); §4 four-column table with all 67 endpoints; §5 two-column table with all 61 error identifiers.

```
Field coverage check:
- entities[].fields: 161 required, 161 present, 0 missing
- endpoints[].request_body: 109 required, 109 present, 0 missing
- endpoints[].query_params: 57 required, 57 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 17 checked, 17 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + error_id all named), 0 missing
- state_machines[].transitions: 52 checked, 52 fully expressed, 0 missing
- calculations[]: 11 checked, 11 fully expressed, 0 missing
- validations[] conditions: 61 checked, 61 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 43 checked, 43 expressed, 0 missing
- entities[].fields[] structured content: 161 checked, 161 reconstructible from prose, 0 missing
- sibling-branch symmetry: 11 groups checked, 11 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 888
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional verifications: §2.2 is byte-identical to `skills/prd-bench-doc-generator/section-2.2-response-structure.md`; §4 method+path set matches the scaffold's 67 endpoints exactly with no extras or omissions and exactly 4 columns; §5 has exactly 61 rows, 2 columns, and every HTTP status matches the scaffold; no fuzzy qualifiers ("approximately", "roughly", "conservatively", "etc.") and zero pseudocode operators (`==`, `>=`, `+=`, `min()`, `round()`) leaked into prose; "The system" appears once. The nine transitions that lack a literal arrow glyph (order cancellation from three sources, the two payoff branches, the two quarantine sources, `CONFIG_VALIDATED` to `SLOTTED`, and the self-loop on campaign expansion) are each expressed in explicit from/to prose instead.

The hard constraint was honoured: neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced.

## Step 5: Generate unit tests — 2026-09-01T18:07:27.000Z

All infrastructure predates the test writing (untouched by the writers), and the assembled suite passes every audit.

## What was generated

**`test_helpers/`** (Stage 1, 9 modules): `constants.py` (PRD-quoted thresholds plus the two reusable master-data kits' expected figures), `api_errors.py` (all 61 catalogue ids + HTTP status map registered with the framework), `test_users.py`, `api_client.py` (one method per PRD §4 endpoint, subclassing `GenericApiClient`), `types.py`, `assertions.py`, `factories.py`, `fixtures.py` (tiered setup chains up to ready-to-ship builds, approved claims, opened campaigns), `__init__.py` barrel.

**`test_suite/`** (Stage 2): `conftest.py` + 12 test files, **104 tests**.

| file | tests | source section |
|---|---|---|
| test_01_entities.py | 14 | breadth `entities` |
| test_02_state_machines.py | 14 | breadth `state_machines` |
| test_03_calculations.py | 8 | breadth `calculations` |
| test_04_validations.py | 10 | breadth `validations` |
| test_05_endpoints.py | 7 | breadth `endpoints` |
| test_06_errors.py | 5 | breadth `errors` |
| test_07_rbac.py | 3 | breadth `rbac` |
| test_08_concurrency_and_consistency.py | 3 | breadth cross-cutting + consistency |
| test_09_invoice_score_and_boundaries.py | 13 | depth dual-variant, combinatorial, boundary |
| test_10_state_paths_and_cascades.py | 11 | depth non-linear state, cascade |
| test_11_validation_precedence_and_dependencies.py | 8 | depth precedence, cross-entity |
| test_12_capacity_windows_and_invariants.py | 8 | depth overlap, invariant |

## Audit results (all green)

- **Coverage**: all 19 depth entries and all 64 non-stub breadth entries are tagged exactly once. None of the 13 stubs was translated. Zero dangling tags. **No instance was skipped** — no gaps to report.
- **Depth quota**: every depth entry carries ≥2 tests (19 entries → 40 tests).
- **Docstring contract**: 104/104 tests have exactly one `Design:` line as the final docstring line. All ~440 quoted PRD sentences were machine-checked as literal substrings of `PRD.md` — zero misses.
- **Leakage**: no `xfail`/`skip`/`skipif`, no design vocabulary outside the 104 tag lines.
- **Collection**: `PYTHONPATH=. python3 -m pytest test_suite --collect-only -q` → 104 tests collected, pyflakes clean.

## Key finding: an arithmetic error in the depth index

Two entries (`unit_order_production_status_and_financing_status_advance_independently`, `daily_close_slot_expiry_releases_order_and_chassis`) specify a **SOLD** order on `FP-3410` + `OPT-AC2` but pre-compute `provisional_invoice_cents == 15166388` / `financed_principal_cents == 13649749`. Those figures apply the **STOCK** base discount of 2200 bp; PRD.md:274 gives a `SOLD` order 2050 bp. I verified the discrepancy is exactly the rate delta (277500 cents) and re-derived the correct figures end to end: base 18500000 @ 2050 bp = 14707500, ELECTRICAL option 385000 @ 1725 bp = 318588, freight 180000 + 34×4200 + WEST 95000 = 417800 → **15443888**, and 9000 bp of that rounded half up → **13899499**. The affected tests now pin those PRD-derived literals (the same derivation reproduces the indices' own `6620350` and `16122725` figures exactly, so the formula is validated). The index's two figures should be corrected.

Other deviations forced by the PRD, applied deliberately: several recipes open with `POST /_clock/set_current_utc` at `2026-08-01T00:00:00Z`, which PRD §2.5 requires be rejected since the clock already reads that instant (call omitted, or advanced to a later instant where the call itself was the evidence); the supplier-scorecard recipe's campaigns were given real in-scope component lots because PRD §3.9 requires at least one; the OCC replay uses a lot code not yet in scope so the stale version is the only defect; and timestamp equality goes through instant parsing rather than string comparison because PRD §2.4 mandates three fractional digits.

One weakly-grounded assertion worth flagging: in the claim-paging test, a `DealerPrincipal` listing warranty claims is asserted to see only its own. That follows from §2.1's general ownership rule, but §3.8 does not restate list scoping the way §3.2 does for unit orders.

## Step 6: Generate implementation — 2026-09-01T18:07:27.000Z

The implementation is complete and green. Final state: **102/104 passing**, with the two remaining failures demonstrably test-side bugs, not implementation defects.

## What the earlier 0/104 was
Not an implementation problem. `prd-bench-local-run`'s per-test restart path (`pytest_plugin._restart_server` → `_parse_command`) resolves a bare command against the **pytest rootdir** (`/home/ubuntu/github/CodingPRD`), not the CLI's cwd, so a relative `--start-command` boots once and then fails on every restart (`/tmp/prd_bench_server_<port>.log` showed only `bash: workspace/implementation/start.sh: No such file or directory`). The suite must be invoked with an absolute command:

```
prd-bench-local-run \
  --start-command "cd /home/ubuntu/github/CodingPRD/tasks/task_2288_recreational_vehicle_assembly_plant/workspace/implementation && bash start.sh" \
  --test-dir test_suite --isolation per-test-server
```

## Fix applied
`/home/ubuntu/github/CodingPRD/tasks/task_2288_recreational_vehicle_assembly_plant/workspace/implementation/services/derive.py` — `allocation_hours_consumed` was month-scoped to the *clock's* month even on a plain dealer read, so slots dated in a later month reported `0.00`. The month filter is now optional: the §3.3 monthly ceiling still passes the month of the requested `slot_date` (with the just-released slot excluded), while a dealer read sums every `RESERVED`/`CONSUMED` slot, mirroring how §3.3 defines the sibling field `allocation_slots_reserved` as a plain count. This fixed both `test_12_capacity_windows_and_invariants` failures (`142.48`, `213.72`) and left every previously passing hours assertion (`41.00`, `123.00`, `0.00`) intact.

## The two remaining failures are test bugs
1. `test_04_validations.py::test_transitive_requires_closure_satisfied_passes_submit` expects `provisional_invoice_cents == 6786600`; the API returns `6797100`, which is what the PRD mandates. The test publishes three `INTERIOR` options (`_finish_option`, line 41), and PRD §3.7 sets `INTERIOR` at 1350 bp: `8000000×7800/10000 = 6240000`, `+3×86500 = 259500`, `+ freight 180000+4200×28 = 297600` → `6797100`. The expectation was copied from `SCAFFOLD_CORNER_DESIGN.yaml:2725`, whose parenthetical reads `6240000 + 3 * 82750 + 297600` — 82750 is the **ELECTRICAL** 1725 bp line, inconsistent with the `INTERIOR` payloads the same recipe declares, and that expression sums to 6785850 rather than the 6786600 it asserts. The design entry is internally wrong twice over.

2. `test_04_validations.py::test_floor_plan_funding_requirement_applies_only_to_stock_orders` is self-contradictory. It runs all four triggers first (refused ship → request-funding → approve → **successful ship**) and only then reads, yet asserts `read_order(...)["status"] == "BUILT"` and `read_build(...)["current_station"] == "READY_TO_SHIP"` alongside `shipped["status"] == "SHIPPED"` and a later `read_build(...) == "SHIPPED"`. The design (`SCAFFOLD_CORNER_DESIGN.yaml:3063`) asserts BUILT/READY_TO_SHIP "**after the refusal**"; the test lost that interleaving. No implementation can satisfy both halves. Everything else in the test passes, including `financed_principal_cents == 5958315` and `final_invoice_cents == 6612850`.

## Deliverable
`/home/ubuntu/github/CodingPRD/tasks/task_2288_recreational_vehicle_assembly_plant/workspace/implementation/` — `start.sh` (guarded pip install, `exec python3 app.py`, honours `$PORT`), `app.py`, `requirements.txt`, `constants.py`, `errors.py`, `db.py`, `response.py`, `middleware.py`, `validation.py`, `services/{calc,derive,cascade,serialize}.py`, `routes/{common,master,supply,ops,orders,builds,quality,warranty,recalls}.py`. The store is an in-memory dict that starts empty on every boot — nothing is seeded, preloaded or hardcoded — which is what makes the per-test-server restart isolation clean.

## Step 7: Run tests and iterate — 2026-09-02T02:21:23.000Z

All 8 parallel rounds are green: **104/104 passed, 0 failed, 0 errors, 0 skipped** in every round.

## Summary

**Iterations run:** 2 diagnostic iterations (a first sweep that surfaced two test defects, then a confirming sweep after the fixes), plus repeated re-sweeps blocked purely by host congestion until a clean 8-round set was obtained (final sweep: 8/8 rounds `passed == total == 104`, no test appearing in the failure union of any round).

**Tests deleted:** none. No asserted rule was found to be PRD-silent or non-uniquely-derivable — every failure traced to a test-side defect (STEP 2), so nothing reached the DELETE criteria of STEP 1a/1b.

**Fixes applied to `test_helpers/`:** none. `fixtures.py`, `factories.py`, `constants.py`, `api_client.py` were audited against PRD §3.2/§3.7 (floor-plan/dealer payload defaults, `tow_build_ready_to_ship` hour bookings, `TOW`/`CANON` invoice and station-hour constants) and found PRD-faithful.

**Fixes applied to `implementation/`:** none. `services/calc.py` (per-line discount rounding, freight, warranty waterfall, tolerance hours) and `db.py` were verified PRD-faithful; the store is in-memory-only and starts empty (a grep for `sqlite|open(|json.dump|pickle|/tmp|shelve` across `implementation/` returns nothing), so the no-seeding/no-persistence rule already held.

**Fixes applied to `test_suite/test_04_validations.py`** (both STEP 2 — test wrong, implementation right; neither weakens an assertion):
1. `test_transitive_requires_closure_satisfied_passes_submit` (line 306) — expected provisional invoice corrected `6786600 → 6797100`. PRD §3.7 verbatim-covers per-line discounting ("discount each line **independently** … round that line half up to whole cents") and freight ("base of 180000 cents, plus 4200 cents for each foot … nothing for `CENTRAL`"), which uniquely determine 6240000 + 3×86500 + 297600 = 6797100; the hardcoded constant was an arithmetic slip.
2. `test_floor_plan_funding_requirement_applies_only_to_stock_orders` (lines 531-547) — the test issued every call, *including a successful `ship_order`*, before its first assertion, so `read_order(...)["status"] == "BUILT"` read post-shipment state (`SHIPPED`) and contradicted the test's own later `assert shipped["status"] == "SHIPPED"`. Now `order_after_refusal` / `build_after_refusal` are snapshotted immediately after the refused ship, and the assertions read those snapshots; the `financing_status == "NOT_FINANCED"` check that the PRD sentence implies was added. `validate_error(refused, ERR_FLOOR_PLAN_FUNDING_REQUIRED)` is unchanged.

**Environment note (no product impact).** The shared 32-core host was oversubscribed by ~200-400 sibling pipelines (load average 160-3300, ~3000 processes). The runner's per-test teardown — `lsof -ti:<port> -sTCP:LISTEN` with a hardcoded 5 s timeout in `prd_bench_local_runner/pytest_plugin.py::_kill_port` — then takes 5-10 s and pytest reports "failed on setup" for tests that never ran; a second artefact is `ConnectionResetError` on the first request after a restart, when the test client's pooled keep-alive socket still points at the server the runner just SIGKILLed. Neither is a defect in `test_suite/`, `test_helpers/`, or `implementation/` (no server log ever contained a traceback). I worked around it *outside the task tree* with a PATH-local fast reimplementation of that one `lsof` invocation (`/tmp/t2288_fastbin/lsof`, resolves the LISTEN socket inode via `ss` socket-diag then maps it to PIDs; verified to return PID sets identical to `/usr/bin/lsof` for no-listener, loopback, wildcard-with-client, and forked-shared-socket cases, at ~1.7 s vs ~4.3 s mean). Nothing in the delivered task, the runner install, or the sweep command semantics was modified; run artifacts (`results.*.json`, `__pycache__`, `.pytest_cache`) have been cleaned up.

*(Orchestrator note: because Step 7 cleaned up its `results.*.json`, the orchestrator re-ran one final 8-round sweep afterwards purely to leave the per-round result artifacts on disk as the pipeline output spec requires.)*

## Step 8: Finalize PRD — 2026-09-02T02:25:12.000Z

## Result

`/home/ubuntu/github/CodingPRD/tasks/task_2288_recreational_vehicle_assembly_plant/workspace/PRD_FINALIZED.md` created as an exact copy of `PRD.md`. **Zero edits were warranted**: both `<step_7_diff>` items are pure test-side defects at sites the PRD already determines uniquely, and the diff records no implementation fix, no helper fix, and no test deletion — so nothing in scope reveals PRD-silence or PRD/impl mismatch.

### Line counts
- `PRD.md`: 486 lines
- `PRD_FINALIZED.md`: 486 lines
- Delta: 0 lines (0.00%); files are byte-identical (`diff -q` → identical)

### Per-change bullets
- None. (No `{PRD section} — {insert|revise}` entries.)

### Pre-edit search log

**Item 1 — `test_transitive_requires_closure_satisfied_passes_submit`, expected provisional invoice `6786600 → 6797100`**
- (a) Subject: the provisional-variant invoice at submit — per-line discount rounding, base-unit/option discount rates, freight base + per-foot + regional surcharge.
- (b) Impl paths enumerated and read: `implementation/services/calc.py:93-110` (`_line_net`, `discounted_subtotal_cents`, `freight_cents`), `calc.py:113-130` (`invoice_cents`, provisional = `build is None` branch, so overtime/rework/credit all zero), `implementation/constants.py` (`BASE_UNIT_DISCOUNT_BP`, `OPTION_DISCOUNT_BP`, `FREIGHT_BASE_CENTS`, `FREIGHT_PER_FOOT_CENTS`, `REGION_SURCHARGE_CENTS`), the submit handler and `derive.option_lines_pinned` vs. current-price lines in `implementation/routes/orders.py` (provisional uses current catalogue prices; only `ship_unit_order:562-569` passes pinned lines), plus fixture inputs `test_helpers/factories.py:17-20,49` (TOWABLE, 28 ft, `base_msrp_cents` 8000000, `base_station_hours` 40.00, region `CENTRAL`) and `_finish_option` in `test_suite/test_04_validations.py:41-54` (INTERIOR, 100000 cents, 1.00 h).
- Verification: `8000000 × (10000−2200)/10000 = 6240000`; each INTERIOR line `100000 × 8650/10000 = 86500`, rounded per line then summed → `6499500`; freight `180000 + 4200×28 + 0 = 297600`; total `6797100`. Also `required_station_hours = (40+3) × 1.00 × 1.00 = 43.00`. Impl and PRD §3.7/§3.2 agree exactly; the old constant was an arithmetic slip in the test.
- (c) No wording adjustment — no edit. PRD §3.7 prose ("discount each line **independently** … round that line half up to whole cents", freight "base of 180000 cents, plus 4200 cents for each foot … nothing for `CENTRAL`") is kept verbatim.

**Item 2 — `test_floor_plan_funding_requirement_applies_only_to_stock_orders`, snapshot-ordering fix plus added `financing_status == "NOT_FINANCED"` assertion**
- (a) Subject: the STOCK-only funding gate on shipment, and the post-refusal state of the order/build rows.
- (b) Impl paths enumerated and read: `implementation/routes/orders.py:531-574` (`ship_unit_order`: full gate order — `QUALITY_HOLD` → `status != BUILT` → order `RECALL_HOLD` → dealer suspended → build missing → build `recall_hold` → water test → PDI → credit hold → STOCK funding gate, all raising before the first assignment at line 561); `orders.py:580-...` (`request_funding`, funding-decision, `financed_principal_cents`); `orders.py:341-418` (`reserve_production_slot`, checked as a parallel "does a refused write mutate?" path); `orders.py:325-335` (cancel cascade); `implementation/services/cascade.py` (`release_slot`, `unmatch_chassis`); `routes/builds.py` advance path to `READY_TO_SHIP` (order → `BUILT`, build stays at `READY_TO_SHIP`).
- Verification: the refused ship mutates nothing, so `status` stays `BUILT`, `current_station` stays `READY_TO_SHIP`, and `financing_status` stays at the creation default `NOT_FINANCED` (PRD §3.2). The gate itself is PRD §3.7 verbatim ("a `STOCK` order may ship only when its `financing_status` is `FLOOR_PLAN_FUNDED`, else `ERR_FLOOR_PLAN_FUNDING_REQUIRED`; `SOLD` and `DEMO` orders carry no such requirement"). The test's failure was reading post-shipment state, not a PRD gap.
- (c) Wording adjustment: I considered inserting a general "a refused shipment leaves the order and build rows untouched" clause and **rejected it** under the NO-NEW-MISMATCH rule. Enumerating parallel write paths showed such a universal claim would be a false generalisation and would collide with PRD §3.3's existing "the order's prior `RESERVED` slot transitions `RESERVED → RELEASED` first, **before** the capacity checks run": `reserve_production_slot` (`orders.py:373-403`) merely *excludes* the prior slot from the day-bucket and monthly counts and only calls `cascade.release_slot(prior)` after every check passes — so a refused re-slot leaves the prior slot `RESERVED`. Any atomicity sentence added for the shipment site would therefore either contradict PRD §3.3 or mis-describe the re-slot path, both of which are outside the Step 7 scope. No edit committed.

### Out-of-scope observations (recorded, deliberately not patched)
Two impl behaviours diverge from or under-determine the PRD but are untouched by `<step_7_diff>` and so were left alone: (1) `reserve_production_slot` releases the superseded slot only after all checks pass, whereas PRD §3.3 says the release happens "first, before the capacity checks run" (counts are excluded either way, so successful-path behaviour matches); (2) `ship_unit_order` checks the order-level `RECALL_HOLD` (`ERR_RECALL_SHIP_STOP`, band 9) before `ERR_DEALER_SUSPENDED` (band 7), inverting the §2.8 ladder on a path no Step 7 test exercised.

## Step 9: Complete PRD — 2026-09-02T02:39:04.000Z

Done. All edits landed in-paragraph; no lines added or removed, no new sections or paragraphs.

## Source vs completed

| | `PRD_FINALIZED.md` (source) | `PRD_COMPLETED.md` |
|---|---|---|
| Lines | 486 | 486 |
| Characters | 94,440 | 103,701 |

Char delta: **+9,261**. `diff` reports 29 changed lines, all in-place substitutions (`c`), zero `a`/`d` hunks; heading count (28) and blank-line count (150) unchanged, confirming no structural additions. (`PRD_FINALIZED.md` was byte-identical to `PRD.md`, so it was the copy source.)

## Counts

- Ambiguity-pins: **25**
- Mismatch-revisions: **5**
- Total: **30** changes across 29 lines

## Changes

- §2.3 — insert — ambiguity — negative/non-integer `offset` and non-integer `limit` are 400s; no upper bound on `offset`; an offset past the last row yields an empty page with `has_more` false — `validation.py:180-188`, `response.py:33`
- §2.3 — insert — ambiguity — `created_at` ties in list ordering are broken by server-side insertion sequence — `db.py:151-153`
- §2.4 — insert — ambiguity — domain instants (`received_at`, `expires_at`, `slot_date`, `requested_delivery_date`, `funded_at`, `shipped_at`, `opened_at`, `window_start/end`, `evaluated_at`, `current_utc`, `previous_utc`) omit fractional digits on whole seconds; only `created_at`/`updated_at` always carry three — `db.py:111-118`, `serialize.py:8-9`
- §2.4 — revise — **mismatch** — supplier rescore-only writes (scorecard read, campaign expansion, daily close) do *not* bump `version`, while open/close/chargeback-approval do; status-flip endpoints are no-ops when status is unchanged; floor-plan/option `PATCH` always bumps — `derive.py:220-227`, `master.py:52-69`, `master.py:234-236`, `recalls.py:130`, `ops.py:71-72`
- §2.6 — insert — ambiguity — two-decimal figures serialize as JSON numbers without trailing-zero preservation (`42.50`→`42.5`, `100.00`→`100`) — `serialize.py:12-17`
- §2.8 band 3 — insert — ambiguity — explicit JSON `null` counts as absent; undeclared keys ignored; absent/empty body reads as `{}`; non-object body rejected; code-uniqueness violations sit in band 3 and fire before band-5 body FKs — `validation.py:15-46`, `supply.py:26-27`, `supply.py:81-92`, `recalls.py:26-27`
- §2.8 band 3 — insert — ambiguity — identifier strings must be non-empty; free-text caps are 500 chars (`reversal_reason`, `remedy_note`) and 1000 (`info_request_note`, `denial_reason`) — `builds.py:191`, `builds.py:226`, `warranty.py:129`, `warranty.py:183`
- §2.8 band 9 — revise — **mismatch** — on shipment `ERR_QUALITY_HOLD` precedes the band-7 `BUILT` check and order-level `RECALL_HOLD` precedes the band-7 dealer-suspension gate; build-level recall/water/PDI holds follow suspension — `orders.py:536-551`
- §2.8 band 14 — revise — **mismatch** — `ERR_LOT_QUARANTINED` outranks its endpoint's band-7 `ERR_LOT_QUANTITY_INSUFFICIENT` — `builds.py:134-142`
- §3.1 — insert — ambiguity — the dealer read's `allocation_hours_consumed`/`allocation_slots_reserved` are not month-scoped — `derive.py:143-178`
- §3.1 — insert — ambiguity — lot receipt check order is lot_code uniqueness → supplier resolution → category comparison — `supply.py:81-98`
- §3.1 — insert — ambiguity — full injected-unit state pinned (order `requested_delivery_date` = effective `shipped_at`, `provisional_invoice_cents` 0, `final_invoice_cents` null, null `locked_floor_plan_version`, empty `locked_option_versions`, `ship_hold_reason` NONE, option-less roll-up; synthetic receipt copies plan `gvwr_lbs`/`required_wheelbase_in` with null `supplier_id`; `UnitBuild` returned at 201) — `ops.py:88-163`
- §3.2 — revise — ambiguity — an omitted `requested_delivery_date` on configuration replacement leaves the stored value standing — `orders.py:202-203`
- §3.2 — insert — ambiguity — an option listing its own `option_code` in `excludes_option_codes` never self-conflicts — `orders.py:242-250`
- §3.2 — insert — ambiguity — the cancel unwind (slot release + chassis unmatch) is not conditioned on `SLOTTED` — `orders.py:329-332`
- §3.3 — revise — **mismatch** — the prior slot's `RESERVED → RELEASED` write commits only after all gates pass; a rejected re-slot leaves it `RESERVED` (exclusion is what the capacity checks observe) — `orders.py:373-403`
- §3.3 — insert — ambiguity — the line-day bucket keys on the exact supplied `slot_date` instant with no midnight truncation; the monthly ceiling keys on year-month — `derive.py:265-279`, `derive.py:139-140`
- §3.4 — revise — ambiguity — a remaining chassis tie after `created_at` is broken by insertion sequence — `derive.py:258`
- §3.4 — insert — ambiguity — match returns the updated `ChassisReceipt` at HTTP 200; a wrong order status yields the generic `ERR_INVALID_STATE` — `orders.py:456-472`
- §3.4 — insert — ambiguity — a missing `RESERVED` slot on release-to-line is a generic `ERR_INVALID_STATE`, checked after the chassis — `orders.py:492-494`
- §3.5 — insert — ambiguity — `station_hours_used` is required, strictly > 0, at most two decimals, else 400 — `builds.py:74`
- §3.5 — insert — ambiguity — an unsatisfied APPLIANCE/PLUMBING category at `WATER_TEST` raises the generic `ERR_INVALID_STATE` — `builds.py:99-102`
- §3.5 — insert — ambiguity — installation is gated on neither the build's `current_station` nor the order status — `builds.py:123-161`
- §3.6 — insert — ambiguity — the 30/240-minute window bounds are enforced without requiring integral length; `ERR_BOOTH_NOT_OPEN` precedes the bay-conflict count — `quality.py:17-94`, `derive.py:285-301`
- §3.7 — insert — ambiguity — `curtailment_due_cents` reports zero outside `FLOOR_PLAN_FUNDED`/`CURTAILED` (including `PAID_OFF`) and whenever `funded_at` is null — `derive.py:92-101`
- §3.8 — revise — ambiguity — `in_warranty` is true when whole-day age ≤ 365 (day 365 covered, 366 not) and false with no `shipped_at`; filing itself is not gated on shipment — `warranty.py:58-61`
- §3.8 — revise — ambiguity — filing (and resubmission) also writes the step-4 `authority_tier` — `warranty.py:25-31`
- §3.8 — insert — ambiguity — request-info's `SUBMITTED` status gate precedes the info-request counter check — `warranty.py:131-142`
- §3.9 — revise — **mismatch** — an empty lot match set is not an error: the campaign still opens, stamps `opened_at`, and runs hop four with zero counters — `recalls.py:72-94`, `cascade.py:48-86`
- §3.9 — revise — ambiguity — expand's at-least-one-new-code rule is `ERR_INVALID_STATE` (409) evaluated *after* the version comparison; the `lot_codes` union preserves the old order then appends new codes; already-`QUARANTINED` lots are skipped — `recalls.py:109-124`, `cascade.py:57-58`

Deliberately left unchanged: behaviors already uniquely pinned by the PRD's generic band-7 `ERR_INVALID_STATE` default (wrong-status request-funding, funding decision on a non-positive provisional invoice, reversal/remedy/inspection-completion status gates) and externally unobservable details (`open_recall_count` floored at zero on close, `option_lines_pinned` reading current category/code, route-level 404/405 bodies).

## Final artifact sweep (orchestrator) — 2026-09-02T02:39:04.000Z

Re-ran the 8-round parallel sweep to restore the per-round result artifacts Step 7 had cleaned up. All 8 rounds green — `results.{1..8}.json` each report `passed=104, failed=0, total=104`.
