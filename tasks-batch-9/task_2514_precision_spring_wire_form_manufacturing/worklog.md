# Worklog — task_2514_precision_spring_wire_form_manufacturing

## Step 1: Create task directory — 2026-09-03T03:39:03.860Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2514_precision_spring_wire_form_manufacturing` and `.../workspace`. Index 2514 was pre-assigned by the orchestrating caller; no scan of `./tasks/` was performed (32 pipelines run concurrently on this host, auto-allocation would collide).

## Step 2: Generate scaffold — 2026-09-03T06:00:20.172Z

All three artifacts are complete and verified in `/home/ubuntu/github/CodingPRD/tasks/task_2514_precision_spring_wire_form_manufacturing/`.

## Files

| file | lines | contents |
|---|---|---|
| `SCAFFOLD.yaml` | 3304 | §1.0–§1.7: 14 entities, 9 state machines, 13 calculations, 78 validations (priority 1–76), 66 endpoints, 78 errors, 7 roles. Contains neither `scaffold_difficulty_design` nor `scaffold_corner_design` (verified: 0 matches). |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2795 | single key `scaffold_difficulty_design`; 9 rule_ids × 2–4 instances = **25** (≥18 required). |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 23614 | single key `scaffold_corner_design`; 9 sections, **190** instances (158 with full `test_recipe`, 32 `excluded_because` stubs). |

## Verification (verdict pasted verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2514_precision_spring_wire_form_manufacturing/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2514_precision_spring_wire_form_manufacturing/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2514_precision_spring_wire_form_manufacturing/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    66
  §1.1 entities declared:     14
  §1.8 instances scanned:     25
  §1.9 instances scanned:     158
  Calls scanned (§1.8+§1.9):  2701

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Additional mechanical sweeps over both design files (scripts at `/tmp/replay19.py`, `/tmp/endstate19.py`, `/tmp/calc19.py`):
- Call-by-call rule replay (§1.2 `from:` states for all 9 machines, incl. cross-entity machine/setup coupling and the SPC cascade): **0 problems** across 2701 calls.
- End-state side-effect replay (program `open_commitment_pieces`/`allocated_pieces`/`shipped_pieces`/`quarantined_lot_count` plus `lot_status`, replaying allocate/pack/ship/return/quarantine/release and both cascade sources): 53 asserts replayed, **0 mismatches**.
- Error-catalog cross-check: **0 uncovered errors** (all 78 are triggered somewhere), 0 HTTP-code mismatches. One flagged row (`success_and_error_responses_share_the_meta_envelope`, HTTP 200 while its prose names a follow-up 404) is a scanner false positive.
- Numeric audit of every literal assert against the Decimal reference implementation: all match. Uniqueness: 0 duplicate names within §1.9, 0 collisions with §1.8, all 32 stub citations resolve.

## Fixes applied this session

- `ERR_SELF_REVIEW_FORBIDDEN` / `ERR_SELF_DISPOSITION_FORBIDDEN` asserts corrected from HTTP 403 to **409** (three places) to match the §1.6 catalog.
- Added an instance covering the previously untriggered `ERR_WIRE_LOT_NOT_FOUND` (run create against an unknown heat, 404).
- Amortization literal corrected: `actual_basis_recovery_cents` 14400 → **14399** (ACTUAL_BASIS reads live balances: ceil(4790000 × 1.5 × 1000 / 499000)).
- **Patch D to `SCAFFOLD.yaml` §1.5** (new this session) — the endpoint side-effect lists for `POST /shipment-lots/{id}/quarantine`, `/release-from-quarantine`, `/production-runs/{id}/inspections` and `/quality-disposition` contradicted the §1.2 edges: they omitted the `open_commitment_pieces` swing on quarantine/release (which §1.2 declares and the release precondition `piece_count <= program.open_commitment_pieces` depends on), omitted `packaging_method := null` on release, wrongly claimed RELEASE/ACCEPT_AS_IS auto-returns quarantined lots to ALLOCATED, and made `process_status := CANCELLED` on SCRAP unconditional. All four now read exactly as §1.2.

Earlier patches A (`InspectionRecord.record_kind` provenance), B (`ERR_PROGRAM_POSTURE_BLOCKED` reachability on `/ship`) and C (`PROTOTYPE_RELEASED -> OBSOLETE` edge + validation-20 scope over `POST /spring-designs/{id}/revisions`) stand.

## Known limitation

One §1.2 side effect is structurally unreachable: on `POST /production-runs/{id}/cancel`, "every ShipmentLot with `run_id` == this run and `lot_status` IN {ALLOCATED, PACKED} transitions to QUARANTINED" can never fire, because lot creation requires `run.process_status == COMPLETE` while cancel requires FAI_PENDING/RUNNING. It is harmless (a defensive cascade) and no test asserts it; the reachable path to the same cascade is the SCRAP quality disposition, which is covered. Twelve read-only GET endpoints are also never called from a design recipe — SKILL.md imposes no endpoint-coverage requirement on §1.8/§1.9.

## Step 3: Copy shared files — 2026-09-03T06:00:42.770Z

Copied `./INSTRUCTION.md` → `tasks/task_2514_precision_spring_wire_form_manufacturing/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T06:18:38.415Z

PRD generation is complete.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2514_precision_spring_wire_form_manufacturing/workspace/PRD.md` — **560 lines / 115,370 bytes**, written incrementally (1 Write + 6 `cat >>` heredoc appends), ends cleanly on the last row of the §5 error table with no audit footer.

**Structure:** §1 Introduction; §2 Global Specifications (2.1 RBAC, 2.2 verbatim response envelope, 2.3 Pagination, 2.4 Identity/timestamps/`version`, 2.5 Logical shop clock, 2.6 Numeric precision, 2.7 OCC, 2.8 Path resolution + the full 1–76 rejection ladder, 2.9 Conserved ledgers, 2.10 Cascade discipline); §3 Business Logic in 11 domain-named subsections (program/materials → design engineering → characteristic plan/review/revision → tooling amortization → wire receipt → coilers & setup windows → runs/reservation/FAI → SPC holds & dispositions → stress relief & oven capacity → PPAP rounds → quoting/allocation/packing/ship/return/quarantine); §4 endpoint table (66 rows, Method/Path/Description/Roles); §5 error table (78 rows).

**Hard Contract verification (programmatic, against SCAFFOLD.yaml):**
- **Contract 1 — Field-Name Coverage: PASS.** All 146 `entities[].fields[].name` values appear in backticks; all 13 endpoint-only identifiers (`expected_design_version`, `expected_machine_version`, `expected_program_version`, `criterion_in_force`, `fatigue_margin_goodman`, `fatigue_margin_soderberg`, `endurance_limit_mpa`, `forecast_basis_recovery_cents`, `actual_basis_recovery_cents`, `decision`, `limit`, `offset`, `to_iso8601`) plus all other endpoint body params are present. Also 100% coverage of: 78 error IDs, 7 role names, every entity enum member, every state-machine state, and all 66 endpoint paths.
- **Contract 2 — Rule Coverage: PASS.** All 76 validation priorities appear with error ID + endpoint scope in §2.8 and with their substantive conditions in §3; all 3 OCC rules (412); all 12 calculations rendered as prose with pinned evaluation orders, rounding points and both dual-variant branches (GOODMAN/SODERBERG, FORECAST_BASIS/ACTUAL_BASIS); every state-machine transition including system-driven edges; all multi-hop cascades (4-hop PPAP approval chain, 5-hop SPC-hold quarantine, 4-hop FAI reject, obsolescence write-off, batch-discharge peening escalation); the three conserved ledgers; sibling-branch symmetry on all review/disposition endpoints.
- **Contract 3 — §3 Path Purity: PASS.** 1,128 backtick tokens in §3; zero start with `/`, zero are a bare HTTP method, zero combine method+path. All paths/methods are confined to §2.7, §2.8 and the §4/§5 tables.

**Constraint honoured:** `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced.

**Three scaffold gaps I resolved by decision** (no error ID exists in the scaffold for these preconditions; the PRD names one so implementation and tests agree): design retirement's "no in-flight run" and the submission/resubmit "design must be `PROTOTYPE_RELEASED`" gates → `ERR_DESIGN_INVALID_STATE` (409); heat-treat scheduling's "run must be `RUNNING`/`COMPLETE`" and the `RELEASE`/`ACCEPT_AS_IS` evidence gates → `ERR_RUN_INVALID_STATE` (409); allocation from a held/scrapped run → `ERR_RUN_ON_SPC_HOLD` (409); run completion's `produced + scrapped <= planned` → `ERR_INVALID_REQUEST` (400). I also adopted the safety-critical-only reading of the SPC escalation (2 of 3 scaffold sources agree).

**Orchestrator truncation check (per caller's guard):** `wc -l` = 560; tail is the final row of the §5 error table (`| ERR_TOOLING_NOT_AMORTIZING | 409 |`) — a genuine section boundary, not mid-sentence. Programmatic cross-check against SCAFFOLD.yaml confirms 78/78 error IDs and 66/66 endpoint paths present. Not truncated; no regeneration needed.

## Step 6: Generate implementation — 2026-09-03T06:55:00.000Z

(Steps 5 and 6 were launched concurrently in a single assistant message, per the skill; Step 6 returned first, so its entry is recorded here ahead of Step 5's.)

Implementation complete and verified.

## Deliverable
`/home/ubuntu/github/CodingPRD/tasks/task_2514_precision_spring_wire_form_manufacturing/workspace/implementation/` — 16 files, 3403 lines, no `__pycache__`, no data files:

| lines | file |
|---|---|
| 1 | requirements.txt (`flask>=2.0`) |
| 10 | start.sh (guarded pip install, then `exec python3 app.py`) |
| 76 | auth.py |
| 78 | find.py |
| 80 | app.py (factory, 5 blueprints, global RLock, error handlers) |
| 84 | envelope.py |
| 120 | errors.py (~80 error ids + statuses) |
| 153 | store.py (in-memory dicts, logical clock) |
| 182 | validate.py |
| 254 | routes_core.py (programs, material specs, `/_clock/set_current_utc`) |
| 311 | routes_shop.py (wire lots, coilers, setups, ovens) |
| 338 | cascades.py |
| 357 | calc.py (engineering, capability, quote, amortization) |
| 359 | routes_designs.py (designs, characteristics, review, tooling) |
| 458 | routes_commercial.py (submissions, shipment lots) |
| 542 | routes_runs.py (runs, FAI, SPC, heat-treat batches) |

All 66 PRD endpoints are registered (67 url rules incl. Flask static). Storage is process-local dicts only; nothing seeded.

## Verification
Booted from a fresh process three times (ports 18571/18572/18573), curled, and killed each; the final fresh boot answered `GET /customer-programs` with `{"data":[],...,"total_count":0}` and `GET /wire-lots` 200, then went silent after the kill. No server of mine is left running.

Two end-to-end smoke suites (~110 calls total, `/tmp/spring_smoke.py`, `/tmp/spring_smoke2.py` — throwaway, outside the deliverable) both passed with zero 500s:
- Happy path: program → spec → design → characteristic → submit/review → fatigue analysis (Soderberg in force, 2.284 vs Goodman 2.812) → tooling → coiler → setup (overlap correctly 409 `ERR_SETUP_WINDOW_CONFLICT`) → clock → activate → wire receipt/certify → run open with reservation → FAI (cpk 3.855, self-disposition 409, second inspector accepts) → SPC → complete (53.15 kg consumed) → oven/batch (capacity 409 with the exact "220.500 kg against 200.000 kg" message) → start/complete (peening verified) → quote → amortization (forecast 2000 / actual 3000) → submission APPROVE → allocate → pack (BAG_AND_TAG 422, TANGLE_FREE_TRAY 200) → ship → return, with tooling-cost, wire-mass and piece-commitment ledgers conserved at every step.
- Second pass, cascades and edges: revision cascade aborts a SCHEDULED setup and frees the coiler without bumping its version; setup abort cancels the run and releases the reservation; FAI REJECT cancels the run and aborts the setup; `ERR_INSUFFICIENT_WIRE`, `ERR_WIRE_LOT_NOT_CERTIFIED`, `ERR_TEMP_EXCEEDS_OVEN`, `ERR_BATCH_WINDOW_NOT_REACHED`, `ERR_CLOCK_NOT_MONOTONIC` (422), `ERR_OUTSIDE_SETUP_WINDOW`; interim approval path (cap enforced at 422, ship blocked by `ERR_TOOLING_NOT_AMORTIZING`, resubmit → posture BLOCKED → ship 409 → APPROVE → ship OK); obsolete design writes tooling off; SPC hold quarantines lots with `SPC_HOLD_CASCADE` and refuses RELEASE until an in-control subgroup exists; 401/403/404/405 and `ERR_INVALID_PAGINATION` envelopes.

Two smoke-test expectations I had written were wrong and the implementation was right (checked against PRD §2.8 / the status table): `ERR_CLOCK_NOT_MONOTONIC` is 422, `ERR_INTERIM_PIECE_CAP_EXCEEDED` is 422.

## One caveat to pass on
While cleaning up my own background server I ran an overly broad `pkill -f "app.py"`, which for a moment also killed the per-test servers of a *concurrently running* sweep in `tasks/task_2513_player_tracking_sports_data_operations` (8 parallel `prd-bench-local-run` jobs were active). That runner respawns a server per test so it recovered, but a handful of task_2513 tests in that sweep may have failed spuriously — if that sweep came back red, it is worth re-running before trusting it. No task_2514 files were affected.

## Step 5: Generate unit tests — 2026-09-03T07:58:00.000Z

Test generation for `task_2514_precision_spring_wire_form_manufacturing` is complete.

## Output inventory

**`test_helpers/` — 3,039 lines** (Stage 1, unchanged this pass except removing two unused typing imports)
`__init__.py` 23 · `api_client.py` 271 · `api_errors.py` 256 · `assertions.py` 476 · `constants.py` 275 · `factories.py` 283 · `fixtures.py` 950 · `test_users.py` 119 · `types.py` 386

**`test_suite/` — 15,713 lines, 21 test modules + conftest, 228 tests**

| file | lines | tests | | file | lines | tests |
|---|---|---|---|---|---|---|
| conftest.py | 38 | – | | test_11_design_review_and_wire_certification | 530 | 10 |
| test_01_fatigue_criterion_and_amortization_variants | 510 | 7 | | test_12_machine_setup_and_production_run | 1117 | 17 |
| test_02_pinned_calculation_order | 338 | 6 | | test_13_heat_treat_qualification_and_shipment | 907 | 14 |
| test_03_design_and_run_lifecycle_branching | 571 | 10 | | test_14_engineering_and_capability_calculations | 981 | 13 |
| test_04_quality_and_approval_cascades | 881 | 9 | | test_15_gate_precedence | 819 | 13 |
| test_05_rejection_ladder_precedence | 830 | 9 | | test_16_endpoint_contracts | 637 | 10 |
| test_06_boundary_precision | 929 | 11 | | test_17_role_permissions | 595 | 10 |
| test_07_cross_entity_gates | 584 | 6 | | test_18_unknown_reference_rejections | 643 | 14 |
| test_08_machine_and_oven_scheduling | 623 | 5 | | test_19_business_rule_rejections | 1170 | 21 |
| test_09_conserved_ledgers | 919 | 7 | | test_20_optimistic_concurrency_and_reconciliation | 634 | 5 |
| test_10_entity_records | 1106 | 29 | | test_21_read_your_writes | 351 | 2 |

## Independent audit (run by me, not the generators)

- **228 tests collected** by pytest with the runner's plugin, zero import/collection errors; pyflakes exit 0 across both directories; every file `ast.parse`s.
- **Tag discipline: perfect.** All 228 tests carry exactly one `Design:` line as the last docstring line. Zero untagged, zero dual-tagged, zero dangling tags.
- **Coverage: 182 of 183 instances** (25/25 difficulty, 157/158 corner). Every difficulty instance has ≥2 tests (actual range 2–3); every covered corner instance has ≥1.
- **1,040 PRD citations, all verbatim** — every `PRD §x.y: "..."` quote re-matched against `workspace/PRD.md` under whitespace normalisation, 0 misses.
- No occurrence of "scaffold" or any design-index section/table number outside the `Design:` tags.

## The one skipped instance (gap left as a gap, per the contract)

`Corner/complexity_layers/design_version_survives_the_review_cycle_untouched` — the instance claims `SpringDesign.version` is unmoved by submit-for-review and the engineering verdict. PRD §2.4 says `SpringDesign.version` "follows the general rule" (increment on every mutation) and both transitions mutate `release_status`, so the PRD *refutes* the asserted outcome rather than merely omitting it.

## Design-index defects found (worth feeding back upstream)

1. `difficulty_non_linear_state_machine/spring_design_revision_reverts_prototype_release_to_draft` asserts `reviewed_by_user_id` is retained; PRD §3.3 says it is cleared to null and `created_by_user_id` re-stamped.
2. `difficulty_priority_pair_validation_conflict` instance 1 records `ERR_RUN_NOT_COMPLETE` as HTTP 422; the PRD and the frozen error map both say 409.
3. `corner_validations/corrosion_requirement_unmet_outranks_the_biocompatibility_gate` uses `coating: PLAIN`, not in the PRD enum — as scripted it would have been masked by `ERR_INVALID_REQUEST` at rank 4.
4. `corner_state_machines/run_fai_disposition_without_full_characteristic_coverage_rejected` adds a characteristic after the design left DRAFT, which PRD §3.3 refuses outright.
5. `corner_complexity_layers` instance 1's recipe replays a creation-time design version for its *successful* revision (already stale after submit+review); instance 4 names a field `corrected_shear_stress_mpa` that the PRD calls `shear_stress_max_mpa`.
6. Several recipes assert exact timestamp strings (`decided_at`, `shipped_at`) or `data: null` on the clock endpoint; the PRD pins neither (§2.2 says a no-data 2xx carries an empty object). Those sub-assertions were dropped and replaced with what the PRD does derive.

## PRD inconsistency worth flagging to its author

`ERR_RUN_ON_SPC_HOLD` is registered in the §2.8 ladder only on run-complete, heat-treat-batch and lot-ship, yet §3.11's narrative implies a held run also blocks `POST /shipment-lots`. Two tests routed around it (one lifts the hold legally first, one uses `validate_error_is_one_of`) rather than guessing. Similarly, §3.3's claim that obsoleting a design lands the program on `BLOCKED` contradicts §3.1's three-input posture rule while a granted submission exists.

## Step 7: Run tests and iterate — 2026-09-03T08:58:00.000Z

All 8 rounds green. Two iterations; both fixes were in `test_suite/`, none in `implementation/`, none in `test_helpers/`, and no tests deleted.

## Summary

**Iterations run: 2**

### Iteration 1 (8-round parallel sweep, `setsid nohup`)
Rounds passed 216–218 / 228. Union of failures across all 8 rounds = 13 tests:

- 9 tests in `test_13_heat_treat_qualification_and_shipment.py` — `KeyError: 'data'`, 8/8 rounds
- 1 test in `test_12_machine_setup_and_production_run.py` — wrong `error_id`, 8/8 rounds
- 3 tests failing in only 1–3 of 8 rounds, all with pure transport errors (`ConnectionResetError(104)`, `RemoteDisconnected`, `IncompleteRead(0 bytes read, 938 more expected)`): `test_06_boundary_precision.py::test_an_aggregate_load_exactly_at_oven_capacity_is_accepted`, `test_06::test_the_shortfall_lot_is_refused_and_the_boundary_lot_then_allocates`, `test_19_business_rule_rejections.py::test_third_lot_beyond_the_runs_good_pieces_is_refused`

### Iteration 2 (after fixes)
`results.1..8.json`: **228/228 passed, 0 failed, 0 errors, 0 skipped in every round** (486–500 s per round). The three transport failures did not recur in any round, confirming they were host-load artifacts, not defects.

### Tests deleted
**None.** Every failing assertion was verbatim-covered by `workspace/PRD.md` and uniquely derivable from it; no test hit STEP 1a PRD-silence or STEP 1b non-derivability.

### Fixes applied to `test_helpers/`
**None.**

### Fixes applied to `test_suite/`
1. `/home/ubuntu/github/CodingPRD/tasks/task_2514_precision_spring_wire_form_manufacturing/test_suite/test_13_heat_treat_qualification_and_shipment.py` — 12 sites (lines 138, 191, 251, 344, 400, 558, 566, 610, 731, 786, 794, 873) double-unwrapped the envelope as `validate_success(...)["data"]`. `prd_bench_local_runner.testing.validators.validate_success` already *returns* `body["data"]`, so the extra subscript raised `KeyError: 'data'` before any assertion ran. Stripped the trailing `["data"]` at all 12 sites. Purely a harness-API misuse in the test layer; no assertion was weakened.

2. `/home/ubuntu/github/CodingPRD/tasks/task_2514_precision_spring_wire_form_manufacturing/test_suite/test_12_machine_setup_and_production_run.py` — `test_a_second_first_article_verdict_is_refused` expected `ERR_FAI_ALREADY_DISPOSITIONED` for a second `fai-disposition` on a run that ACCEPT had already advanced to `RUNNING`. The PRD sentence the test itself quotes (§3.9-adjacent §3.7, PRD.md line 326) pins the gate order: *"the run's `process_status` must be `FAI_PENDING`, otherwise `ERR_RUN_INVALID_STATE`; `fai_disposition` must still be `PENDING`, otherwise `ERR_FAI_ALREADY_DISPOSITIONED`"*, and §2.8 ranks `ERR_RUN_INVALID_STATE` at 24 vs `ERR_FAI_ALREADY_DISPOSITIONED` at 29. Both gates trip on this fixture and PRD uniquely determines the earlier one. Changed the expectation to `ERR_RUN_INVALID_STATE` (still an exact `error_id` + `expected_status=409` assertion — no downgrade to a status-only check), reworded the follow-up assertion message, and dropped the now-unused import. Verified `routes_runs.dispose_fai` implements the five gates in exactly the PRD's order, so no implementation change was warranted.

### Fixes applied to `implementation/`
**None.** No PRD-required check was removed or weakened; nothing was added, seeded, or persisted.

### Notes
- The pre-existing shortlist of suspected implementation deviations (revision-endpoint geometry-check ordering, `release-from-quarantine` raising `ERR_RUN_ON_SPC_HOLD`, `calc._capability_index`'s `999.999` sigma sentinel) was never exercised by a failing test, so it was left untouched per the cardinal rule against changing `implementation/` without a PRD-traceable driver.
- `workspace/sweep.log` is unreliable for counting because 8 concurrent rounds interleave writes to one file; `workspace/implementation/results.$i.json` is the authoritative record. Round-2 artifacts are at `.../workspace/implementation/results.1.json` … `results.8.json`.
- `__pycache__` directories removed; no server processes of mine left running.

**Orchestrator verification of the Step 7 sweep artifacts:** independently parsed all 8 `results.$i.json` — every round reports `passed == total == 228`. Sweep artifacts are present and genuine, not merely claimed.

**Step 8 skip-condition adjudication (orchestrator decision, no user available):** the skip condition requires zero iterations beyond baseline AND zero fixes in all four categories. Step 7 ran 2 iterations with 2 `test_suite/` fixes, so the condition does NOT hold and Step 8 runs. Both fixes were test-layer (one harness-API misuse, one error-precedence expectation the PRD already pinned), so Step 8 may legitimately conclude that few or no PRD edits are warranted — that is an acceptable outcome, not a failure.

## Step 8: Finalize PRD — 2026-09-03T08:42:30.000Z

Both `<step_7_diff>` items resolve to test-layer defects, not PRD gaps. **Zero edits made.** `PRD_FINALIZED.md` exists as a byte-identical copy of `PRD.md`.

## Line counts
- `PRD.md`: 560 lines — `PRD_FINALIZED.md`: 560 lines — **0.0 % delta**
- Both files md5 `e5da3a9e3fb4ae2875a251c269d56484` (verified identical after `cp`)

## Per-item adjudication (no edits, so no per-edit search log is due — but here is the evidence trail)

**test_suite item 1 — `test_13_heat_treat_qualification_and_shipment.py`, 12 sites double-unwrapping `validate_success(...)["data"]`.** Pure harness-API misuse, as the diff states. Confirmed `implementation/envelope.py:21-31` emits exactly the §2.2 envelope (`meta`/`response_type`/`data`, `data` defaulting to `{}`), and `envelope.py:34-44` adds only the four §2.3 pagination keys — the impl side of the envelope is fully determined by PRD §2.2/§2.3 and matches. Spot-checked the assertions that began running once the extra subscript was stripped (batch cancel restoring `scheduled_load_kg`/`heat_treat_state`, unpeened-discharge SPC cascade, forecast recovery posting, ship/return ledger reversal, quarantine retaining `packaging_method`, release clearing it, resubmit round bookkeeping): every one is verbatim-covered by PRD §3.9/§3.10/§3.11 and passes against the impl. No PRD silence, no mismatch, no edit.

**test_suite item 2 — FAI-disposition gate ordering.** The PRD already pins this twice over, so nothing needs pinning:
- `PRD.md:326` states the five gates "in this order", `process_status` → `ERR_RUN_INVALID_STATE` first, `fai_disposition` → `ERR_FAI_ALREADY_DISPOSITIONED` second.
- `PRD.md:151` ranks `ERR_RUN_INVALID_STATE` at 24 and `PRD.md:156` ranks `ERR_FAI_ALREADY_DISPOSITIONED` at 29.
- `implementation/routes_runs.py:190-209` (`dispose_fai`) implements precisely that sequence: `process_status != FAI_PENDING` → `ERR_RUN_INVALID_STATE`, then `fai_disposition != PENDING` → `ERR_FAI_ALREADY_DISPOSITIONED`, then self-disposition, then empty characteristic set, then coverage. Body-enum validation runs before `find.run`, consistent with rank 4 < rank 14.
- The corrected test (`test_suite/test_12_machine_setup_and_production_run.py:675-722`) now asserts `ERR_RUN_INVALID_STATE`/409 on a run ACCEPT had already advanced to `RUNNING`, matching both the impl and the PRD. Fixture-expectation bug only.

**Transport failures (3 tests, 1–3 of 8 rounds).** `ConnectionResetError`/`RemoteDisconnected`/`IncompleteRead` with no recurrence in iteration 2 — host-load artifacts with no behavioral content. Nothing to pin.

## Findings handed forward (deliberately NOT edited — outside Step 8's scope)
The diff's Notes list three suspected impl/PRD divergences that Step 7 never exercised and never fixed, so they trace to no fix and are out of Step 8 scope. They do look like genuine PRD silences and are worth Step 9's global scan:
- `POST /shipment-lots/{id}/release-from-quarantine` raising `ERR_RUN_ON_SPC_HOLD` for a still-held run — `PRD.md:402` states the requirement ("the run's `quality_status` must be `OPEN` or `DISPOSITIONED_ACCEPT`") but names no `error_id`, and `PRD.md:150` does not list that endpoint under rank 23.
- `calc._capability_index`'s `999.999` sentinel for a zero-sigma subgroup — `PRD.md:320` divides by `3 × sigma` with no zero-sigma rule.
- Revision-endpoint geometry-check ordering relative to the corrosion/biocompatibility gates.

**Orchestrator note on Step 9 sequencing (decision, no user available):** because Step 8 produced a byte-identical `PRD_FINALIZED.md`, a single-pass Step 9 risks returning another byte-identical copy without having actually scanned. Step 9 will therefore be run as **three sequential file-partitioned passes** over `implementation/` (A: infra + core + designs; B: shop + runs; C: commercial + calc + cascades), each pass editing `PRD_COMPLETED.md` in place, so every impl file is provably walked. The three findings Step 8 handed forward are passed to the owning partition as explicit starting leads.

## Step 9: Complete PRD — 2026-09-03T09:15:45.919Z

Run as **three sequential file-partitioned passes** over `implementation/` (orchestrator decision recorded under Step 8), each editing `workspace/PRD_COMPLETED.md` in place. Pass A created the file from `PRD_FINALIZED.md`; Passes B and C patched it further without reverting earlier work.

### Pass A — app.py, envelope.py, errors.py, store.py, auth.py, find.py, validate.py, routes_core.py, routes_designs.py

23 surgical edits across 22 PRD passages (one new bullet line in §2.2, everything else in-paragraph). Counts: **20 ambiguity-pins, 3 mismatch-revisions** (§2.7 version-field rejection, §3.3 review posture, §3.3 revision gate ordering vs the §2.8 ladder).

Behaviors walked per file: `app.py` blueprint mount set / global write lock / `ApiError` + `HTTPException` (404/405/400) + catch-all 500 / `PORT` default · `envelope.py` `_meta` shape, `ok`/`created` (`data` default `{}`), `listed` (`total_count`, `has_more`, `public_list`), `error`, `pagination()` defaults+bounds, `_as_int` sign/digit parsing · `errors.py` full `ERROR_STATUS` map cross-checked row-by-row against §5 (all 76 match), default 400 for unknown ids, three off-catalog fallbacks, `DEFAULT_MESSAGES` · `store.py` 14 collections empty at boot, `CLOCK_EPOCH`, `iso()` 3-digit, `wall_now` vs `clock_now`, `new_id` UUID4, `request_id`, `base_row`, `touch` vs `touch_program` (program version never bumped), `by_seq`/`newest`, `public()` underscore filtering, `parse_iso8601` · `auth.py` 7 roles, `guard()` strip/blank/unknown → 401 then 403, `own_program` rank 3, forced `customer_program_filter`, `program_of_design` · `find.py` all 13 resolvers and their error ids · `validate.py` `body()`, `_present` (explicit null = absent), all `req/opt` type checks, `_bounds`, bool-rejection, `query_enum`/`query_str`, `reject_version_fields` no-op · `routes_core.py` program CRUD, quote, tooling-amortization read, material-spec CRUD, clock set · `routes_designs.py` `_check_geometry`, `_check_material_gates`, `_apply_engineering`, design CRUD, characteristics, submit/review, revisions, obsolete, fatigue-analysis, tooling CRUD.

Changes:
- §2.1 — insert — ambiguity — headers trimmed; blank/whitespace-only `X-User-ID` → `ERR_UNAUTHENTICATED` — auth.py:47-50
- §2.1 — insert — ambiguity — customer list `program_id` filter is *forced*; `GET /customer-programs/{id}` checks ownership against the path segment *before* lookup (403 not 404), unlike `/spring-designs/{id}` which resolves first — auth.py:64-71, routes_core.py:83-84, routes_designs.py:105-106
- §2.2 — insert — ambiguity — `api_request_timestamp` from the host wall clock, not the logical clock — store.py:76-77
- §2.2 — insert — ambiguity — pagination `meta` fields absent on non-list responses — envelope.py:14-27
- §2.2 — insert — ambiguity — new bullet pinning `ERR_NOT_FOUND`/`ERR_METHOD_NOT_ALLOWED`/`ERR_INTERNAL` as off-catalog framework errors; `GET /inspection-records/{id}` 404 via `ERR_NOT_FOUND`; absent body read as `{}`; unparseable/non-object body → 400 — app.py:53-69, find.py:53-54, validate.py:17-29
- §2.3 — insert — ambiguity — `limit`/`offset` must be integer literals; empty/fractional/non-numeric → `ERR_INVALID_PAGINATION` — envelope.py:62-84
- §2.3 — insert — ambiguity — stable insertion-order tie-break on equal `created_at`; enum filters validated before pagination; id filters never resolved (unknown id → empty page); empty-string filter = absent — store.py:127-129, validate.py:163-176, routes_core.py:90-93
- §2.4 — insert — ambiguity — `created_at`/`updated_at` from the wall clock, not the logical clock — store.py:99-118
- §2.5 — insert — ambiguity — an instant equal to the current reading is accepted; `to_iso8601` required/parseable else 400; endpoint answers 200 with empty `data` — routes_core.py:246-254
- §2.7 — revise — mismatch — "no other endpoint may be given one" replaced: a version field elsewhere is silently *ignored*, as is every unrecognised body property; the three fields must be JSON integers with no range bound — validate.py:179-182, 64-71
- §3.1 — insert — ambiguity — `program_code` length on the raw string; `customer_name` non-empty, no length bound — routes_core.py:30-31, validate.py:36-46
- §3.1 — insert — ambiguity — `ppap_level`/`committed_pieces`/`minimum_order_quantity`/`required_salt_spray_hours` integers; `min_fatigue_margin`/`required_ppk` unbounded numbers (negatives accepted); explicit `null` = omission — routes_core.py:34-42, validate.py:32-33
- §3.1 — insert — ambiguity — `salt_spray_hours`/`cost_per_kg_cents` whole numbers, four constants plain numbers, `spec_code` no length bound — routes_core.py:195-204
- §3.2 — insert — ambiguity — `active_coils` a plain number (fractional accepted); `part_number` not unique — routes_designs.py:64,70
- §3.2 — insert — ambiguity — fatigue-analysis `data` is exactly those 7 fields (no id/timestamps); the two margins + `endurance_limit_mpa` visible *only* there, never on the persisted design — routes_designs.py:302-310, store.py:142-145
- §3.3 — insert — ambiguity — `nominal_value`/`lsl`/`usl` unbounded numbers; cross-field ordering checked before the path design resolves — routes_designs.py:132-142
- §3.3 — insert — ambiguity — `cpk_floor` carries no bound of its own — routes_designs.py:136
- §3.3 — revise — mismatch — posture re-derived on **both** review branches, not only `APPROVE_PROTOTYPE` — routes_designs.py:213
- §3.3 — insert — ambiguity — a null `fatigue_margin_ratio` is a shortfall → `ERR_FATIGUE_MARGIN_BELOW_FLOOR` — routes_designs.py:204-207
- §3.3 — revise — mismatch — *(flagged lead, confirmed)* on revisions the merged cross-field geometry check runs only *after* OCC / `ERR_DESIGN_INVALID_STATE` / `ERR_DESIGN_LOCKED` and *before* corrosion→biocompatibility; body `material_spec_id` resolves ahead of OCC; `expected_design_version` integer; `null` replacement = not supplied — routes_designs.py:221-259
- §3.3 — insert — ambiguity — the revision's setup-abort sweep does **not** bump the coiler's `version` and leaves an idle coiler untouched; posture re-derived at the end — routes_designs.py:271-272, cascades.py:323-338
- §3.3 — insert — ambiguity — retirement's abort sweep leaves coilers untouched, unlike the revision cascade — routes_designs.py:292
- §3.4 — insert — ambiguity — `original_cost_cents` whole cents, `tool_code` no length bound, design `release_status` not consulted — routes_designs.py:320-325
- §3.4 — insert — ambiguity — `piece_count` from query else body, integer > 0; "most recently quoted design" = last successfully quoted design, held internally and never exposed; never-quoted / no-tooling case → 200 with four nulls and both recovery figures 0; both variants always returned and both capped — routes_core.py:134-181, 124
- §3.11 — insert — ambiguity — `quoted_qty` integer > 0; design `release_status` ungated (a `DRAFT` design may be priced) but must resolve, so `ERR_DESIGN_NOT_FOUND` precedes the version and freeze checks — routes_core.py:106-119

### Pass B — routes_shop.py, routes_runs.py

18 edits reported as 21 bullets. Counts: **16 ambiguity-pins, 2 mismatch-revisions** (plus ambiguity revisions). All of Pass A's 23 edits verified intact.

Behaviors walked: `routes_shop.py` — wire-lot create/read/list/certify, machine create/read/list, `create_setup` (all 7 gates + buffered-conflict arithmetic + supersession sweep), setup read/list/activate/abort (+ run-cancel fan-out), oven create/read; role tuples cross-checked against §4. `routes_runs.py` — `create_run` (6 gates, reservation arithmetic, machine transition), read/list, `_subgroup`, `_record_row` pooling, `record_fai`, `dispose_fai` (5 gates, both branches), `record_inspection` + escalation, `_newest_out_of_control`, `dispose_quality` (3 decisions), `complete_run` (ledger settle + setup release), cancel, record read/list, `create_batch` (7 gates, closed-interval capacity), batch read/list/start/complete/cancel.

Changes:
- §2.8 — insert — mismatch — on `/fai` and `/inspections` the path `run_id` resolves ahead of rank-4 body validation and rank-9 `characteristic_id`, so an unknown run answers `ERR_RUN_NOT_FOUND` — routes_runs.py:163-164, 225-226
- §3.9 ¶351 — revise — mismatch — batch-scheduling gate order reversed: `ERR_RUN_ON_SPC_HOLD` checked **before** `process_status` — routes_runs.py:392-397
- §3.1 ¶238 — insert — ambiguity — `heat_number`/`machine_code`/`oven_code` non-empty strings, no length bound, literal uniqueness comparison — routes_shop.py:40,109,291
- §3.5 ¶295 — revise — ambiguity — `tensile_test_mpa` required, > 0, stored verbatim un-rounded — routes_shop.py:87,93
- §3.6 ¶301 — insert — ambiguity — setup and batch `window_start`/`window_end` echoed back as the raw supplied string, not normalised; offset-less values read as UTC — routes_shop.py:198-199, routes_runs.py:427-428
- §3.6 ¶309 — revise — ambiguity — abort cancels runs in chronological order with the *full* §3.7 cancellation (lot quarantine + posture); setup aborted first so the coiler's `version` advances exactly once — routes_shop.py:277-280, cascades.py:284-294
- §3.7 ¶315 — insert — ambiguity — sufficiency comparison strict: required == `on_hand_kg` accepted — routes_runs.py:65
- §3.7 ¶317 — insert — ambiguity — `active_setup_id` unchanged; an `ACTIVE` setup may carry concurrent runs, each reserving and bumping the coiler's version — routes_runs.py:92-95
- §3.7 ¶319 — insert — ambiguity — absent/non-array/**empty**/non-numeric `measurements` is rank-4 `ERR_INVALID_REQUEST`; only a 1- or 2-value numeric array reaches `ERR_INVALID_SUBGROUP_SIZE` — validate.py:141-142 vs routes_runs.py:172
- §3.7 ¶321 — insert — ambiguity — the zero-sigma `999.999` sentinel for both `cpk_value` and `ppk_value`, written verbatim — calc.py:249-255
- §3.7 ¶321 — insert — ambiguity — record echoes `measurements` verbatim plus `run_id`/`characteristic_id`/`record_kind`/`inspected_by_user_id`, with no `updated_at`/`version` — routes_runs.py:146-156
- §3.7 ¶329 — insert — ambiguity — FAI `REJECT` runs the same cancellation as abandonment, quarantine sweep and posture included — routes_runs.py:217, cascades.py:293-294
- §3.7 ¶331 — revise — ambiguity — `produced_pieces`/`scrapped_pieces` required JSON integers ≥ 0 — routes_runs.py:302-303
- §3.7 ¶331 — insert — ambiguity — setup-release/coiler hop conditional on the setup still being `ACTIVE` — routes_runs.py:327-329
- §3.8 ¶339 — insert — ambiguity — posture re-derived for the run's own program even with zero quarantined lots, so a lotless program drops `ON_TRACK → AT_RISK` — routes_runs.py:249
- §3.8 ¶343 — insert — ambiguity — newest record spans both `record_kind`s; a safety-critical characteristic with no record is skipped, not blocking — routes_runs.py:256-263
- §3.8 ¶343 — revise — ambiguity — posture also re-derived for the run's own program when it holds no lot — cascades.py:276-278
- §3.9 ¶349 — insert — ambiguity — `capacity_kg`/`max_temp_c` stored as supplied (not 3dp); `scheduled_load_kg` re-derived over all `SCHEDULED`/`RUNNING` batches and bumps the oven's `version` each time; no oven list endpoint — routes_shop.py:292-293, cascades.py:116-125
- §3.9 ¶355 — revise — ambiguity — no upper temporal bound on charging; `heat_treat_state` re-derived with `COMPLETE` outranking `RUNNING`; run always touched — routes_runs.py:474-482, cascades.py:131-138
- §3.9 ¶357 — revise — ambiguity — discharge re-derives (not deltas) oven load and heat-treat state; `peening_verified` never cleared by a later `false` — routes_runs.py:499-510
- §3.9 ¶359 — insert — ambiguity — cancel touches the run only when the re-derived state actually changes, unlike charge/discharge — routes_runs.py:536-541

### Pass C — routes_commercial.py, calc.py, cascades.py

17 surgical edits (18 bullets). Counts: **12 ambiguity-pins, 5 mismatch-revisions.**

Behaviors walked: `routes_commercial.py` — `create_submission` (5 gates + order, defaults, posture refresh), read/list (forced customer filter, enum filters), `review_submission` (four decisions, stamp-before-branch, APPROVE 4-hop cascade, cap validation position, gate order), `resubmit_submission` (3 gates + order, field resets), `_run_pieces_taken`, `create_lot` (all 12 substantive gates in order, snapshot fields, counter moves), read/list, `pack_lot`, `ship_lot` (recovery posting order, FULLY_AMORTIZED edge, counters, `shipped_at`), `return_lot` (verbatim reversal, tool re-resolution, zero-posting case), `quarantine_lot_endpoint`, `release_lot`. `calc.py` — rounding primitives, `engineering` (spring rate, Wahl + degenerate divisor, τ split, three allowables, both denominators, criterion selection, null margin, mass, tangle), `predicted_life`, wire-mass family, `_mean`/`_sigma`/`_capability_index`/`capability`, `volume_discount`, `quote` (11 steps + rounding points), recovery/amortization family, all enum/constant tables incl. `PACKAGING_PERMITTED`. `cascades.py` — lookup helpers, `derive_posture`/`refresh_posture` (conditional write), `derive_active_setup_id`, `derive_oven_load`, `derive_heat_treat_state`, `refresh_run_capability`, three wire postings, `abort_setup`/`release_setup`, `quarantine_lot` (`keep_packaging`), `quarantine_lots_of_run`, `spc_hold`, `refresh_posture_for_lots_of_run`, `cancel_run`, `arm_tooling`, `write_off_tooling`, `abort_scheduled_setups`. (`free_machine`, `spc_hold`, `submissions_of_program`, `batches_of_run` are unreferenced dead code — nothing pinned for them.)

Changes:
- §2.8 rank 20 — insert — ambiguity — added `POST /qualification-submissions` and a pointer that resubmit's rank is pinned by §3.10 — routes_commercial.py:46,178
- §2.8 rank 23 — revise — ambiguity — added `POST /shipment-lots` and `POST /shipment-lots/{id}/release-from-quarantine` to the `ERR_RUN_ON_SPC_HOLD` rank — routes_commercial.py:219,441
- §2.8 closing paragraph — revise — mismatch — PRD claimed every non-measurement endpoint validates body ahead of path resolution; `review` resolves the submission (and ownership) first — routes_commercial.py:113-121
- §3.1 posture — insert — ambiguity — re-derivation writes only when the value changes; an unchanged posture leaves the row (and `updated_at`) untouched — cascades.py:86-92
- §3.2 corrected shear stress — insert — ambiguity — spring index exactly 0.75 → `ERR_INVALID_REQUEST` (400), raised after the corrosion/biocompat gates — calc.py:141-143
- §3.2 fatigue margin — insert — ambiguity — non-positive denominator yields a null ratio, judged per variant — calc.py:163-164
- §3.2 predicted life — revise — ambiguity — a null ratio falls to the zero-cycle tier — calc.py:202-203
- §3.10 filing — insert — ambiguity — filing re-derives `delivery_posture` (lands on the held value) — routes_commercial.py:80
- §3.10 `APPROVE` hop three — revise — mismatch — the tooling sweep hangs off the verdict, not the promotion, so it runs even when hop two promotes nothing — routes_commercial.py:136-140
- §3.10 `INTERIM_APPROVE` — revise — ambiguity — `interim_piece_cap` must be a JSON integer, typed before the submission-status gate — routes_commercial.py:120-125
- §3.10 resubmit — insert — mismatch — gate order departs from the ladder: status, then round budget, then design status — routes_commercial.py:167-179
- §3.11 quote step 7 — insert — ambiguity — no tooling asset ⇒ raw ask 0 ⇒ zero amortization in the unit price — calc.py:312
- §3.11 allocation — revise — ambiguity — `piece_count` a JSON integer > 0 (and dropped the "eleven" miscount; the list holds twelve) — routes_commercial.py:210
- §3.11 returns — insert — ambiguity — reversal target is the newest tooling asset resolved afresh at return time; a 0 recovery leaves the tooling row untouched — routes_commercial.py:395-403
- §3.11 quarantine — insert — mismatch — the reason enum accepts both values, so a manual `SPC_HOLD_CASCADE` is recorded, not refused — routes_commercial.py:420
- §3.11 quarantine — insert — ambiguity — automatic cascades also retain `packaging_method` — cascades.py:232-237
- §3.11 release — revise — ambiguity — named `ERR_RUN_ON_SPC_HOLD` (409) for the run gate (covers `SCRAPPED` too) and its rank ahead of the commitment check — routes_commercial.py:441
- §4 quarantine row — revise — mismatch — "SPC_HOLD_CASCADE is reserved for the automatic cascade" → also accepted on the manual endpoint — routes_commercial.py:420

### Step 9 totals and orchestrator verification

- **58 edits total** across the three passes (48 ambiguity-pins, 10 mismatch-revisions).
- `PRD.md` 560 lines / 115,370 bytes → `PRD_FINALIZED.md` 560 lines / 115,370 bytes (identical) → `PRD_COMPLETED.md` **561 lines / 136,887 bytes** (+21,517 bytes, +18.6 %); `diff` reports 111 changed lines.
- md5 `PRD_FINALIZED.md` `e5da3a9e…` vs `PRD_COMPLETED.md` `ff4f0d01…` — **not byte-identical**, so the scan provably ran (the failure mode the three-pass split was chosen to prevent).
- Integrity re-checked by the orchestrator: file ends at the last row of the §5 error table (`| ERR_TOOLING_NOT_AMORTIZING | 409 |`), §5 still holds exactly 78 error rows, and all 66 endpoint paths are still present.
- Final test state is unchanged by Step 9 (it edits only PRD_COMPLETED.md): `workspace/implementation/results.1..8.json` all report 228/228.

**Pipeline complete.**
