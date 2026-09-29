# Worklog — task_2621_fire_protection_system_design_hydraulic_calculation

## Step 1: Create task directory — 2026-09-03T20:53:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2621_fire_protection_system_design_hydraulic_calculation` and its `workspace/` subdirectory. Index 2621 was pre-assigned by the invoking command; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate scaffold (subagent) — 2026-09-03T22:43:00.000Z

All three scaffold artifacts are complete and the linter is clean.

## Output

`/home/ubuntu/github/CodingPRD/tasks/task_2621_fire_protection_system_design_hydraulic_calculation/`

| File | Lines | Bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 3192 | 160942 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2150 | 139215 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 5389 | 340232 |

(plus the pre-existing `worklog.md` and empty `workspace/`)

## Verdict block, verbatim

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2621_fire_protection_system_design_hydraulic_calculation/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2621_fire_protection_system_design_hydraulic_calculation/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2621_fire_protection_system_design_hydraulic_calculation/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    56
  §1.1 entities declared:     15
  §1.8 instances scanned:     19
  §1.9 instances scanned:     57
  Calls scanned (§1.8+§1.9):  1140

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Structure verification

- Top-level keys: `SCAFFOLD.yaml` = scenario, domain_name, api_prefix, difficulty_level, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles — **neither `scaffold_difficulty_design` nor `scaffold_corner_design` is present**. The other two files each have exactly one top-level key, as required.
- §1.8: 19 instances across all nine rule_ids, >=2 each (`priority_pair_validation_conflict` has 3).
- §1.9: 82 instances over all nine guide sections — entities 12, state_machines 17, calculations 15, validations 19, endpoints 5, errors 2, rbac 5, cross-cutting complexity layers 6, consistency model 1. 57 carry a full `test_recipe`; 25 are `excluded_because:` stubs. All 82 names are unique and disjoint from the 19 §1.8 names.
- All 56 declared error ids are triggered somewhere in §1.8/§1.9, and no assert references an undeclared error id (`ERR_NOT_FOUND` appears once, only as prose contrasting with a hypothetical shared code).

## Two defects found and fixed in this final pass

1. **All 25 stub citations used invented rule_ids.** `excluded_because.difficulty_instance` must be `rule_id / name`, and I had been writing descriptive labels (e.g. `validation_priority_inversion`, `dual_variant_divergence`, `boundary_condition`) instead of the rule_ids actually present in `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (`priority_pair_validation_conflict`, `dual_variant_calc`, `boundary_precision_check`, ...). 16 of the 25 were wrong; a scripted rewrite keyed off the difficulty file's own name->rule_id map corrected them, and a re-parse confirms every citation now resolves to a real instance under its real rule_id.
2. **The consistency-model instance asserted a pump result that cannot happen.** I had added the 480 gpm in-rack line *before* sizing the pump, which pushes design demand to 2610 gpm — beyond the catalogue, so the write is a 422 `ERR_PUMP_CAPACITY_UNAVAILABLE` and cannot carry the nine derived sizing figures the instance claims to inspect. Reordered the trigger to size the pump at the verified 2130 gpm ledger (rated 2500, churn 106.0, 150% pair 3750.0/32.25/58.25, verdict ACCEPTABLE) and moved the auxiliary create + project read after it, so the instance now shows immediate visibility on three write responses plus two collateral reads.

## Step 3: Copy shared files — 2026-09-03T22:44:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD (subagent) — 2026-09-03T22:59:00.000Z

PRD generation is complete.

**Output:** `workspace/PRD.md` — **497 lines**, 95,026 bytes, written in 10 chunked heredoc appends (never a single giant Write). No sibling files were created; nothing else in `workspace/` was touched.

**Ends at a genuine section boundary:** the last line is the final row of the §5 error table (`| ERR_FEE_PAYMENT_EXCEEDS_BALANCE | 422 |`). `## 5. Error Code Catalogue` is the final heading and it is complete (56 of 56 rows); no mid-sentence truncation. Section order verified: 1 -> 2.1-2.12 -> 3.1-3.9 -> 4 -> 5.

**Structure**
- §1 Introduction (3 paragraphs).
- §2 with 12 subsections: RBAC, the verbatim §2.2 response block, pagination, identity/timestamps/`version`, the `design_posture` gate, units & pinned rounding, version pinning (both OCC fields), a normative 44-step request-admission order, path resolution, the logical clock (`2026-08-01T00:00:00Z`), the project demand ledger with its pinned acyclic evaluation order, and terminal-state precedence.
- §3 with 9 narrative subsections covering hazard classification/escalation, the Hazen-Williams pipe-sizing chain, supply evaluation + pump catalogue sizing, auxiliary/standpipe demand and outage windows, QC + seal, trade coordination, permit review/comment/resubmittal (incl. the four-link MAJOR cascade and its full compensation), and witnessed acceptance testing + close-out.
- §4: intro paragraph on 201-vs-200 plus a 4-column table (Method, Path, Description, Authorized Role(s)) with all 56 endpoints. "All roles" is defined once in the intro as the five named roles.
- §5: 2-column table (Error ID, HTTP Status Code) with all 56 errors.

**Hard Contract 1 — Field-Name Coverage: PASS.** Required set mechanically derived from the scaffold: 152 entity field names + endpoint request-body/query/path identifiers, normalized (optional `?` stripped) = **161 names**. Backticked tokens extracted from PRD.md and diffed. First pass found 1 miss (`shop_drawing_id`); it was patched into §3.7 ("each item carries the `shop_drawing_id` of the sheet it belongs to"). Second pass: **161 required / 0 missing.** All 56 error IDs also appear backticked in prose or §5.

**Hard Contract 2 — Rule Coverage: PASS.** Validation priority order is normative in §2.8 (numbered 1-44 with error ID + status, first-failure-wins), with each substantive condition also stated at its rule site. Both `concurrency_rules` are specified in §2.7 (`expected_project_version` -> `ERR_STALE_PROJECT_VERSION` 412 on lodge/resubmit; `expected_water_supply_evaluation_version` -> `ERR_STALE_SUPPLY_EVALUATION_VERSION` 412 on pump sizing; explicitly noted that no other endpoint takes a version field). All three cross-entity cascades are written link-by-link (A: MAJOR comment reopening sealed calcs -> drawings -> trade items -> counters/ledger/posture, plus its exact compensation on withdrawal with "no drift"; B: witness fail; C: hazard reclassification with all three source-state branches). All 10 calculations are reconstructible from prose: a numeric diff of every constant appearing in each `calculations` block against the numbers present in PRD.md returned **0 missing for all 10**. `applies_to` scopes, field-level defaults (pagination, counters, nullable seal/interlock fields) and sibling-branch symmetry (PASS/REJECT, CLEARED/CONFLICT_OPEN, BLOCKING/ADVISORY, approve/comments-issued, the two AcceptanceTest dimensions) are all present.

**Hard Contract 3 — §3 Path Purity: PASS.** §3 extracted from `## 3.` to `## 4.`: 0 backticked tokens starting with `/`, 0 bare HTTP-method tokens (backticked or plain text — a plain-word scan for GET/POST/PUT/PATCH/DELETE in §3 returned zero), 0 method+path combos, 0 unticked slash-paths. §2 is likewise path-free.

Also checked and cleaned: one fuzzy word ("roughly", in the ceiling-slope aside) was rewritten to "steeper than", so no hedging language remains around any threshold. No Hard Contract / scaffold references leaked into PRD.md.

**Constraints honoured:** `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced. No `pkill` (or any process-killing command) was run.

**Two scaffold inconsistencies resolved, worth flagging to the task owner:**
1. `Submittal.open_comment_count` — the entity definition counts `ReviewComment` rows in {`OPEN`, `RESPONDED`}, but the respond-endpoint `side_effects` prose says it is "recounted over its ReviewComment rows in state `OPEN`". Resolved in favour of the entity definition plus the state machine (responding leaves the count unchanged); the `RESPONSE_COMPLETE` bubble is therefore expressed as the separate condition "no comment of the package remains in `OPEN`", stated explicitly so a PRD-only reader cannot mis-derive it.
2. `Project.pump_required_flag` — entity description conflicts with the evaluation endpoint's `pump_required_flag = (margin_verdict != ADEQUATE)`. Written per-write at each causing operation rather than as one abstract invariant.

One gap in the scaffold itself: no error is declared for appending a supply-connection iteration when the project has no `EVALUATED` supply evaluation. The PRD states no convergence branch is declared for that case and the append is refused with `ERR_INVALID_STATE_TRANSITION`.

**Orchestrator verification (independent):** re-ran `wc -l`, heading scan and `tail -12` myself. 497 lines, headings §1 through §5 all present, file ends on the complete final error-table row. Not truncated — no regeneration needed.

## Step 6: Generate implementation (subagent) — 2026-09-03T23:45:00.000Z

Implementation complete. All 56 endpoints are live, the server boots clean from a fresh process, and an end-to-end smoke run exercised every major workflow.

## What was finished this session
- `routes/submittals.py` (257) — POST /submittals (FK order project -> each `included_calculation_ids` member, lead-engineer, `expected_project_version` pin, FROZEN, GATED, step 25 `ERR_CALCULATION_NOT_SEALED`, step 26 `ERR_DRAWING_NOT_COORDINATED`, cycle stamping + tiered fee accrual, DESIGN->PERMIT_REVIEW), GET x2, begin-review (step 43 `ERR_REVIEW_FEE_OUTSTANDING` after the state gate), comments, complete-review (approve -> PERMITTED + sheets ISSUED / items LOCKED; else COMMENTS_ISSUED + cascade A when a MAJOR is outstanding), resubmit (25 -> 26 -> 42 order, target SUPERSEDED + successor cycle).
- `routes/comments.py` (116) — GET x2, respond (OPEN->RESPONDED, package bubbles to RESPONSE_COMPLETE), close (RESOLVED / REJECT_RESPONSE clearing `response_note` and returning the package to COMMENTS_ISSUED / WITHDRAWN, with the full cascade-A compensation when the withdrawal clears the last outstanding comment).
- `routes/acceptance.py` (265) — POST /acceptance-tests (step 27 `ERR_DRAWING_NOT_ISSUED` before step 28 `ERR_NO_GOVERNING_CALCULATION`, frozen thresholds, PERMITTED->ACCEPTANCE), GET x2, schedule-witness (window bounds -> past -> closed-interval +/-60-min buffer collision; retest path lifts CORRECTIVE_ACTION), record-witness (both readings >= frozen thresholds; PUMP_FLOW_TEST accepts SIZED pumps; fail runs cascade B), submit-as-built, accept-as-built (single join point on WITNESSED_PASS, close-out when every test is passed + accepted).
- `app.py` (88) — blueprint registration, `ApiError`/HTTPException handlers in the same envelope, `0.0.0.0:$PORT` (default 10000), no seeding at import.

## Verification
- `python3 -m compileall` clean; the Flask URL map is an exact 56/56 match against the PRD §4 endpoint table (no extras, no gaps).
- Error catalog cross-check: 56 ids in `errors.py`, identical set and HTTP statuses to the PRD §5 table, every one actually raised somewhere in the code.
- Smoke run on PORT=54621 (stopped afterwards by the exact port's PID only; port confirmed free): full happy path engineer -> project -> hazard area -> iteration -> flow test -> evaluation -> supply-connection convergence -> QC pass -> seal -> sheet + 3 trade clearances -> COORDINATED -> submittal -> begin-review -> MAJOR comment -> complete-review (verified cascade A: calc REOPENED, sheet STALE, items STALE, `sealed_calculation_count` 1->0, ledger emptied, posture GATED, seal refused with `ERR_PROJECT_POSTURE_GATED`) -> comment withdrawal (verified full compensation back to SEALED/COORDINATED/CLEARED and `sealed_calculation_count` restored) -> approval -> ISSUED -> acceptance test -> witness fail (project CORRECTIVE_ACTION/FROZEN) -> retest -> pass -> as-built -> close-out (project CLOSED_OUT, calc ARCHIVED). Also exercised: seasonal-adjusted evaluation, pump sizing with the version pin (stale pin -> 412) and the ordered `sizing_verdict`, all aux demand branches with the interlock gate and the 2-outage concurrency cap, fee overpayment refusal, reclassification.
- Two spec checks fired exactly as the PRD requires and were confirmed correct rather than patched: `ERR_EVALUATION_REFERENCE_STALE` on sealing against an evaluation taken before the chain converged, and `ERR_INVALID_STATE_TRANSITION` on a supply-connection iteration with no EVALUATED evaluation.
- No seeding, no SQLite, no disk or /tmp state — storage is in-memory dicts, so every `start.sh` reboot wipes all state. Logical clock starts at exactly `2026-08-01T00:00:00.000Z`.

## Per-file line counts (`workspace/implementation/`)
start.sh 10, requirements.txt 1, app.py 88, utils.py 77, errors.py 89, clock.py 32, response.py 52, db.py 79, middleware.py 69, validate.py 197, guards.py 130, helpers.py 39, calc_hazard.py 125, calc_chain.py 83, calc_supply.py 88, calc_pump.py 82, calc_aux.py 79, ledger.py 132, cascades.py 194, routes/__init__.py 0, routes/directory.py 61, routes/projects.py 104, routes/hazard_areas.py 99, routes/flow_tests.py 41, routes/calculations.py 219, routes/iterations.py 159, routes/evaluations.py 89, routes/pumps.py 77, routes/aux_systems.py 186, routes/shop_drawings.py 189, routes/submittals.py 257, routes/comments.py 116, routes/acceptance.py 265 — 3508 lines total.

The test-generator directories (`test_helpers/`, `test_suite/`) and the DIFFICULTY/CORNER design files were never read, listed, or grepped.

**Note on launch ordering (orchestrator):** Steps 5 and 6 were launched in two consecutive messages rather than one, so they overlapped for nearly their whole runtime but were not co-launched in a single message. To restore the isolation guarantee the single-message launch normally provides physically, Step 6's prompt carried an explicit hard prohibition on reading/listing/globbing/grepping `test_helpers/`, `test_suite/`, and both design YAMLs; the subagent confirmed on exit that it never touched them.

## Step 5: Generate unit tests (subagent) — 2026-09-04T02:10:00.000Z

Test infrastructure and suite are complete at the task root.

## Deliverables

`test_helpers/` — 9 modules, 2,665 lines
- `types.py` 513, `fixtures.py` 663, `factories.py` 468, `assertions.py` 422, `api_client.py` 280, `api_errors.py` 125, `constants.py` 117, `test_users.py` 45, `__init__.py` 32

`test_suite/` — `conftest.py` (41) + 17 test modules, 6,999 lines, **188 tests**
- test_01 hazard_demand_variants 262/6, test_02 supply_basis_and_margin 213/7, test_03 fire_pump_sizing 301/7, test_04 pipe_chain_restart_and_velocity 221/5, test_05 permit_review_cycle 224/6, test_06 cascade_invalidation 263/6, test_07 admission_order_precedence 243/6, test_08 calendar_overlap 205/4, test_09 compensating_reversals 226/6, test_10 entity_shapes_and_defaults 802/25, test_11 lifecycle_transitions 879/20, test_12 derived_quantities 718/21, test_13 validation_rules 1192/35, test_14 endpoint_surfaces 314/10, test_15 not_found_errors 238/7, test_16 role_access 359/9, test_17 cross_cutting_layers 298/8

## Verification

- **Coverage: 76 / 76 non-stub design instances covered, 0 missing, 0 orphan tags.** 188 tests carry exactly 188 `Design:` lines, one per test as the final docstring line; each of the 25 `excluded_because:` corner stubs resolves to a real difficulty instance that is itself covered.
- **PRD citation audit: 0 remaining issues** (verbatim >=8-word rule-bearing fragments, elisions marked with `...`, no abbreviations, correct tag placement).
- `python3 -m py_compile` clean on all 27 files; no unused imports (AST-checked); `__pycache__` removed.

## Notable findings

- **Design-index defect on `pump_required_flag`.** `SCAFFOLD_DIFFICULTY_DESIGN.yaml:1273` asserts `pump_required_flag == false` after a `MARGINAL` verdict, but PRD.md:267 says the flag "is set to true exactly when the new verdict is anything other than `ADEQUATE`". I followed the PRD (asserted `is True` in test_02) since the PRD is the contract under test.
- **Design index uses paraphrased fire-pump field names** (`static_rated_psi`, `churn_pressure_psi`, `flow_at_150_pct_gpm`, ...). The PRD's real names are `suction_psi_at_rated`, `required_discharge_psi`, `churn_discharge_psi`, `flow_150_pct_gpm`, `suction_psi_at_150_pct`, `available_psi_at_150_pct`; all nine worksheet values were re-derived by hand against the PRD formulas.
- Corner section names are multi-word in two cases and are tagged verbatim: `Corner/cross-cutting complexity layers/...` and `Corner/consistency model/...`.
- No instances were skipped — every non-stub instance passed the PRD-first two-condition filter.

`workspace/implementation/` was never read, listed, or written, and no broad `pkill` was run.

**Orchestrator verification (independent):** `test_helpers/` and `test_suite/` are both at the task root; `find workspace -maxdepth 2 -type d -name 'test_*'` returns nothing, so neither directory leaked under `workspace/`. Independent counts confirm 188 `def test_` functions and 188 `Design:` tags.

## Step 7: Run tests and iterate (subagent) — 2026-09-04T00:56:00.000Z

8-round parallel sweep is fully green: **188/188 passed in all 8 rounds**.

## Iterations run
2 (sweep 1: 183/188 in every round — 5 deterministic failures, no flakiness; sweep 2: 188/188 in every round).

The 5 failures were identical across all 8 rounds of iteration 1, so no timing-sensitive/flaky defects existed in this artifact.

## Tests deleted
None deleted outright. Two assertions removed under STEP 1c (partial coverage), both keeping the rest of their test intact:

- `test_06_cascade_invalidation.py::TestMajorCommentCascade::test_01_...reopens_and_names_the_package_that_did_it` — removed `assert_seal_metadata_cleared(calculation)`. **BRANCH-ASYMMETRIC SIDE EFFECT.** PRD.md:339 enumerates exactly what cascade A writes (`stale_reason`, `reopened_by_submittal_id`, `sealed_calculation_count` decrement) and does *not* clear the seal metadata, whereas PRD.md:227 renders the *same* `SEALED -> REOPENED` transition for reclassification fully and *does* explicitly clear it. The only indirect support is PRD.md:345's "with its previous `sealed_by_engineer_id` and `sealed_at` restored", which a faithful reader can satisfy as a no-op. Both implementations are PRD-consistent -> not uniquely derivable. (Scaffold rule that drove it: SCAFFOLD.yaml:2482, which *does* state the clearing — the PRD dropped it, and PRD is the contract.) All other assertions in the test (reopen, `stale_reason == MAJOR_COMMENT`, `reopened_by_submittal_id`, counter decrement) are verbatim in PRD.md:339 and were kept.
- `test_11_lifecycle_transitions.py::TestCloseOutJoinsBothDimensions::test_19_accepting_the_last_package_closes_the_job_and_archives_the_seal` — removed `assert project["sealed_calculation_count"] == 0`. **PRD SILENCE.** PRD.md:371 names three close-out effects (project `CLOSED_OUT`, `SEALED` calcs -> `ARCHIVED`, posture `FROZEN`) and no counter write; PRD.md:207 states "the writes that move them are named with the workflows that cause them", and every `sealed_calculation_count` write *is* named elsewhere (227, 311, 339, 345) — close-out is not. The kept assertions (`ARCHIVED`, `CLOSED_OUT`, `FROZEN`) are verbatim.

## Fixes applied to `test_helpers/`
None — no fixture, factory, or role-header bug was implicated.

## Fixes applied to `test_suite/`
- `test_11_lifecycle_transitions.py` — added missing imports `assert_calculation_demand_snapshot`, `assert_reopened`, `assert_seal_metadata_cleared` from `test_helpers.assertions` (test_16 died on `NameError`; an AST sweep of all 17 modules confirmed this was the only missing-import case).
- `test_14_endpoint_surfaces.py:234` — `read_trade_clearance(client, item["id"])` -> `read_trade_clearance(client, sheet["id"], item["id"])`; the helper's signature is `(client, shop_drawing_id, clearance_id)` and the other two call sites already passed both.
- `test_11_lifecycle_transitions.py:297` — `assert_margin(ctx["evaluation"], 65.54, 10.00, 18.0, ...)` -> `15.3`. Arithmetic error in the test: PRD.md:265 defines `safety_margin_pct` as the margin as a percentage of `available_psi_at_demand`, i.e. 10.00/65.54 = 15.3, and the *same* evaluation is asserted as `15.3` in `test_02:65`, `test_02:132` and `test_13:563`.

## Fixes applied to `implementation/`
**None.** No implementation defect was found — all five failures were test-artifact bugs (two Python-level errors, one arithmetic typo) or assertions of rules the PRD does not state.

Note on `SCAFFOLD_DIFFICULTY_DESIGN.yaml`'s `pump_required_flag` defect and the paraphrased fire-pump field names: both were already resolved in favour of PRD upstream, and the suite's PRD-faithful assertions on them pass as written.

**Orchestrator verification (independent):** read all 8 `workspace/implementation/results.*.json` myself — every round reports `passed == total == 188`. The files are present and complete (results.1.json 64160 bytes), so the green claim is backed by on-disk artifacts, not just the subagent's report.

**Step 8 decision (orchestrator):** NOT skipped. The skip condition requires 0 deletions AND 0 `test_suite/` fixes AND 0 `test_helpers/` fixes AND 0 `implementation/` fixes. Implementation fixes were 0, but there were 3 `test_suite/` fixes and 2 assertion removals under STEP 1c, and the two removals are exactly the signal Step 8 exists to act on: they mark PRD sites where the implementation has already chosen a behaviour the PRD does not pin (seal-metadata handling on the cascade-A reopen path, and `sealed_calculation_count` at close-out). Step 8 proceeds with the entry above inlined as `<step_7_diff>`.

## Step 8: Finalize PRD (subagent) — 2026-09-04T01:00:00.000Z

`PRD_FINALIZED.md` is written. Two edits, both traced to the two assertions Step 7 removed; the three `test_suite/` fixes were verified as pure test-artifact bugs requiring no PRD change.

## Line counts
- `PRD.md`: 497 lines — `PRD_FINALIZED.md`: 497 lines — **0.0% line delta** (both edits are inline sentence insertions into existing paragraphs; no new sections, no reflow).
- Character delta: +742 bytes across 2 paragraphs.

## Changes
- **§3.8, "When at least one of those outstanding comments has `severity` `MAJOR`..." (PRD line 339)** — *insert* — after the `stale_reason`/`reopened_by_submittal_id` clause, states that `sealed_by_engineer_id` and `sealed_at` are deliberately **left as they stand rather than cleared** on the cascade-A `SEALED -> REOPENED`, in contrast with the §3.2 reclassification reopen, and that this is what lets the withdrawal compensation restore the same engineer and instant — `implementation/cascades.py:83-90` (stashes the two values into `_prev_*` and never nulls the public fields), restore at `cascades.py:130-134`.
- **§3.9, "Acceptance of the last outstanding package closes the job out..." (PRD line 371)** — *insert* — states that the `SEALED -> ARCHIVED` archiving **does not move** `sealed_calculation_count`, which keeps the value it held — `implementation/cascades.py:169-176` (`cascade_close_out` writes only `project["status"]`, calc states and posture).

## Per-edit pre-edit search log

**Edit 1 — subject: the seal-metadata fields (`sealed_by_engineer_id`, `sealed_at`) and every transition that writes them.**
(b) Paths enumerated, read or grepped: `grep -rn "sealed_by_engineer_id\|sealed_at\|sealed_calculation_count"` over all 30 impl modules, then read in full — `cascades.py:15-57` (cascade C reclassification: the `SEALED` source branch **does** null both fields, so PRD:227 must stay verbatim); `cascades.py:76-106` (cascade A: preserves); `cascades.py:122-153` (compensation: pops `_prev_*` back, a numeric no-op); `routes/calculations.py:49-80` (creation: both null in `DRAFT`); `routes/calculations.py:211-215` (seal: sets both); `routes/calculations.py:89-105` (the `sealed_by_engineer_id` list filter — a cascade-A-reopened calc still matches it, consistent with "retained"); `routes/iterations.py:95-137` (`REOPENED -> ITERATING` restart clears only `stale_reason`, never the seal fields — so a reopened-then-restarted calc still carries them off the Step 7 path); `response.py:20-24` (confirms `_prev_*` keys are stripped from every response, so the stash is invisible and only the retained public values are observable); `cascades.py:169-176` (ARCHIVED calcs keep them).
(c) Adjustment: scoped the sentence to *this* reopen ("in contrast with the reclassification reopen of section 3.2") instead of writing a general claim about `SEALED -> REOPENED`, which would have contradicted `cascades.py:29-31`. Also chose "left as they stand" over "remain non-null until re-sealed", because the restart path at `iterations.py:113-116` carries them into `ITERATING` and no path in the impl bounds their lifetime.

**Edit 2 — subject: every write to `project["sealed_calculation_count"]`.**
(b) Paths enumerated, read or grepped: same repo-wide grep — the counter is written in exactly five places: `routes/projects.py:52` (init 0), `routes/calculations.py:215` (+1 at seal), `cascades.py:32-34` (-1 in cascade C, clamped at 0), `cascades.py:88-90` (-1 in cascade A, clamped), `cascades.py:137` (+1 in the compensation). Read `ledger.py` in full to confirm neither `recompute_ledger` nor `recompute_posture` ever recounts or resets it, and read `routes/acceptance.py:229-264` to confirm the close-out callsite adds nothing beyond `cascade_close_out(project)` + `db.touch_if_changed`.
(c) Adjustment: phrased as "does not move ... keeps whatever value it held" rather than naming a specific value (e.g. "stays at the sealed count"), since the value at close-out depends on prior cascade/compensation history; and deliberately confined the sentence to the counter, saying nothing about the ledger fields, because `cascade_close_out` also leaves `governing_hydraulic_calculation_id`/`governing_demand_gpm` pointing at the now-`ARCHIVED` calculation (no `recompute_ledger` call) — a broader claim there would have been a new mismatch off the Step 7 site.

## No-edit verifications (the three `test_suite/` fixes)
- Missing `test_helpers.assertions` imports in `test_11` — Python `NameError`, no behavioral claim. No PRD implication.
- `read_trade_clearance(client, sheet["id"], item["id"])` — the helper at `test_helpers/fixtures.py:576-583` reads via `list_trade_clearances(shop_drawing_id)`, matching `implementation/routes/shop_drawings.py:105` and PRD.md:415 (`GET /shop-drawings/{id}/trade-clearances`). The PRD's endpoint table already determines this exactly; pure call-arity bug.
- `assert_margin(..., 15.3)` — `implementation/calc_supply.py:77` computes `margin / available * 100` rounded to 1 dp, which is PRD.md:265 verbatim ("as a percentage of `available_psi_at_demand`"). 10.00/65.54 -> 15.3; the test's `18.0` was an arithmetic typo. No PRD ambiguity.

**Step 9 plan (orchestrator):** a single subagent cannot reliably scan a 3508-line / 33-file implementation against a 497-line PRD in one pass — the known failure mode is a shallow walk that returns `PRD_COMPLETED.md` byte-identical to its source. Step 9 is therefore run as three SEQUENTIAL file-partitioned passes over `implementation/`, each editing the same `PRD_COMPLETED.md` (pass 1 does the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 edit in place). Sequential rather than parallel so the three passes cannot clobber each other's edits to the one output file. Partition: pass 1 = global/core infrastructure (app, middleware, validate, guards, response, db, clock, utils, helpers, errors, ledger, cascades); pass 2 = the five calculation modules + the hazard/supply/pump/aux/project/directory route groups; pass 3 = shop_drawings, submittals, comments, acceptance route groups.

## Step 9: Complete PRD (three sequential file-partitioned subagent passes) — 2026-09-04T01:35:00.000Z

`workspace/PRD_COMPLETED.md` written. Run as three sequential passes over disjoint slices of `implementation/`, each editing the same output file; pass 1 did the `cp` from `PRD_FINALIZED.md`, passes 2 and 3 edited in place and each verified the prior passes' edits survived.

**Totals: 497 lines -> 497 lines (0.0% line delta), +13,910 chars over `PRD_FINALIZED.md`, 44 diff hunks, 48 changes — 36 ambiguity-pins and 12 mismatch-revisions.** Every change is an in-paragraph insert or revision; no new sections.

### Pass 1 — core/global partition (app, utils, errors, clock, response, db, middleware, validate, guards, helpers, ledger, cascades)
18 changes (16 ambiguity-pins, 2 mismatch-revisions).
- §2 preamble — insert — ambiguity — trailing slash insignificant; store starts entirely empty/unseeded — `app.py:32`, `db.py:12-26`
- §2.1 — insert — ambiguity — "blank" = empty or all-whitespace; header values otherwise matched verbatim (no trim/case fold) — `middleware.py:45-68`
- §2.2 `api_request_id` — insert — ambiguity — `req_` + exactly 20 uppercase alphanumerics, per-response, never persisted — `response.py:9-13`
- §2.2 `api_request_timestamp` — insert — ambiguity — read from the logical clock, so it does not move between requests at one clock reading — `response.py:17`
- §2.2 `data` — insert — ambiguity — private bookkeeping (insertion sequence, stashed seal attribution) never appears in `data` — `response.py:20-24`
- §2.2 pagination — insert — ambiguity — pagination fields absent from single-object `meta` — `response.py:27-43`
- §2.3 P1 — insert — ambiguity — `offset` unbounded, past-end is an empty page against the true `total_count`; non-integer refused not coerced; empty-string param falls back to default — `validate.py:159-178`
- §2.3 P2 — insert — ambiguity — `created_at` ties broken by insertion order; filters matched exactly/case-sensitively on the stringified stored value; boolean filters accept `true/false/1/0` any case else 422 — `db.py:74-79`, `helpers.py:13`, `validate.py:188-197`
- §2.4 P1 — insert — ambiguity — rendered timestamps truncated (not rounded) to 3 fractional digits; client timestamps accept `Z` or offset, naive read as UTC, unparseable -> `ERR_INVALID_REQUEST` — `utils.py:40-61`, `validate.py:124-133`
- §2.4 P2 — insert — ambiguity — `updated_at == created_at` and `version == 1` at insert; conditional revision rule (a parent whose recomputed ledger/posture/counters/status all land unchanged does not advance `updated_at`/`version`); the nine writes that stamp the project directly advance it unconditionally — `db.py:60-71`
- §2.8 step 5 — insert — ambiguity — absent/null/non-string FKs skip existence checking and fall to step 9, reporting 422 not 404 — `validate.py:30-38`, `guards.py:49-53`
- §2.8 step 9 — insert — ambiguity — absent/empty/unparseable body = empty object; non-object JSON body = 422; unknown fields ignored; strict types (bool != number, `3.0` != integer); required strings non-blank and stored untrimmed; explicit null on an optional field = omitted — `validate.py:17-27,41-121`
- §2.10 — insert — ambiguity — clock response echoes `current_utc` in 3-digit UTC form; the move is absolute (backwards allowed) and restamps nothing — `clock.py:29-31`
- §2.11 — insert — ambiguity — governing selection breaks a remaining `created_at` tie by insertion order — `ledger.py:46-54`
- §3.2 — insert — ambiguity — a `ROOM_DESIGN` calculation whose restated area no longer carries `room_area_sqft` still REOPENs and records `stale_reason` but keeps its old demand snapshot — `cascades.py:7-12`
- §3.8 withdrawal compensation — revise — **mismatch** — the project's `version` advances only when the compensation actually moved a project figure — `cascades.py:122-153`, `db.py:66`
- §3.9 schedule-witness — revise — **mismatch** — a first booking leaves the project untouched; only the retest route out of `CORRECTIVE_ACTION` advances it — `routes/acceptance.py:149-161`, `db.py:66`
- §5 preamble — insert — ambiguity — three off-catalogue transport errors in the same envelope: `ERR_NOT_FOUND` 404, `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INTERNAL` 500 — `app.py:55-73`

Pass 1 also confirmed already-pinned: the full error catalogue (programmatic diff of `errors.py ERROR_STATUS` against the §5 table — 0 diffs), admission steps 1-3 and guards 6/7/8/13/14/15/16, envelope shapes and the 200/201 rule, UUID ids and the four id+created_at-only record types, clock start `2026-08-01T00:00:00Z` and 365-day flow-test validity, ledger eligibility/roundings/fee tiers/posture derivation, all five cascades, and ROUND_HALF_UP throughout.

### Pass 2 — calculations + front-half routes (calc_hazard/chain/supply/pump/aux; directory, projects, hazard_areas, flow_tests, calculations, iterations, evaluations, pumps, aux_systems)
15 changes (11 ambiguity-pins, 4 mismatch-revisions).
- §2.9 — insert — ambiguity — step-5 existence checking does not enforce cross-parent agreement; `included_calculation_ids` is the one exception — `routes/calculations.py:46-47`, `routes/evaluations.py:24-28`, `routes/pumps.py:21-24`, `routes/aux_systems.py:35-36`
- §3.1 — insert — ambiguity — no uniqueness constraint on `license_number`, `jurisdiction_code` or `project_number` — `routes/directory.py:22-51`, `routes/projects.py:34-45`
- §3.1 — insert — ambiguity — fee payment `amount_usd` carries no positivity bound; a negative raises the balance — `routes/projects.py:92`
- §3.2 — revise — **mismatch** — when the gross-area cap binds, `design_area_sqft` is the declared `area_sqft` verbatim (possibly fractional); the cap compares the already-rounded figure — `calc_hazard.py:76-82`
- §3.2 — insert — ambiguity — on reclassify, `sprinkler_system_type` is not restated and each omitted optional input reverts to its default rather than retaining its stored value — `routes/hazard_areas.py:31-41,88-89`
- §3.3 — revise — **mismatch** — `iteration_index` below 1 is `ERR_INVALID_REQUEST` at step 9, not `ERR_ITERATION_OUT_OF_SEQUENCE` — `routes/iterations.py:33`
- §3.3 — insert — ambiguity — a chain restart leaves `deficiency_psi` and `pump_required_flag` as they stand; only a converging close nulls `deficiency_psi` — `routes/iterations.py:108-131`
- §3.3 — revise — **mismatch** — a supply-connection iteration is declared only from `ITERATING`, checked ahead of velocity/supply-flow/sequence/restart, so from `DRAFT`/`PRESSURE_DEFICIENT`/`REOPENED` it is `ERR_INVALID_STATE_TRANSITION`, never `ERR_CHAIN_RESTART_REQUIRED` — `routes/iterations.py:51-60`
- §3.3 — insert — ambiguity — the calculation's submittal listing accepts an optional `state` filter — `routes/iterations.py:158`
- §3.4 — insert — ambiguity — `tested_at` required with no clock default, a future reading accepted, and flow-test recording passes no posture or project-status gate — `routes/flow_tests.py:15-33`
- §3.4 — insert — ambiguity — `safety_margin_pct` is 0.0 when `available_psi_at_demand` is exactly zero — `calc_supply.py:74-77`
- §3.5 — revise — **mismatch** — `hazard_area_id` and every type-conditional field are accepted, existence-/bounds-checked and stored for any `system_type`, not forced null — `routes/aux_systems.py:36,40-47`
- §3.5 — insert — ambiguity — `withdraw_note` is validated then discarded, not persisted — `routes/aux_systems.py:169`
- §3.6 — insert — ambiguity — `review_note` is validated then discarded, not persisted — `routes/calculations.py:116`
- §3.6 — insert — ambiguity — a project with no `EVALUATED` evaluation fails seal check three, reporting `ERR_SAFETY_MARGIN_UNRESOLVED` and never `ERR_EVALUATION_REFERENCE_STALE` — `routes/calculations.py:139-154`

Pass 2 also confirmed already-pinned the whole numeric core: hazard escalation thresholds and clamping, the five base density/area pairs, DRY/PREACTION and slope multipliers in order, the high-ceiling bump, hose allowances, the demand snapshot and ROOM_DESIGN admissibility triple; all nine Schedule-40 diameters, Hazen-Williams constants (4.52, C=120, 1.85, 4.87), elevation 0.433, velocity 0.4085Q/d^2 with the inclusive 32.00 limit, per-segment re-rounding, `in_active_chain` boundary; RAW_TEST vs SEASONAL_ADJUSTED (-10.0 psi, x0.90), the 1.85 projection, verdict thresholds >=10.00/>=0.00/else, the inclusive 365-day window, `pump_required_flag` true iff verdict != ADEQUATE; the [500..2500] pump catalogue, ceil-to-5-then-floor-40, churn 1.40x+static, `flow_150`/`available_150` and the ordered verdict; all six aux demand branches with floors and caps; and every route's defaults, enums and filter sets.

### Pass 3 — back-half routes (shop_drawings, submittals, comments, acceptance)
15 changes (9 ambiguity-pins, 6 mismatch-revisions).
- §2.5 — revise — **mismatch** — opening an acceptance test added to the exactly-enumerated FROZEN refused set; the frozen test precedes the workflow's own status check, so `CORRECTIVE_ACTION` yields `ERR_PROJECT_POSTURE_FROZEN` — `routes/acceptance.py:36`
- §2.8 step 43 — revise — **mismatch** — `review_fee_balance_usd` "is exactly zero" -> "is not above zero"; a negative balance counts as paid up — `routes/submittals.py:131`
- §2.8 step 25 — revise — **mismatch** — shop drawing creation is guarded on its single `hydraulic_calculation_id` (must be `SEALED`, need not belong to the named project), not on `included_calculation_ids` — `routes/shop_drawings.py:39`
- §3.7 — revise — **mismatch** — a `STALE` clearance item may be cleared only while the sheet is `STALE` or `IN_COORDINATION`, not `CONFLICTED` — `routes/shop_drawings.py:137-140`
- §3.7 — insert — ambiguity — `note` is non-blank when present and rewritten on every disposition, so an omitted note nulls a previously recorded one — `routes/shop_drawings.py:123,176`
- §3.7 — insert — ambiguity — `CONFLICT_OPEN` without `conflict_severity` is `ERR_INVALID_REQUEST` at step 9 — `routes/shop_drawings.py:124-125`
- §3.7 — insert — ambiguity — the response carries the dispositioned item, not the sheet — `routes/shop_drawings.py:189`
- §3.8 — insert — ambiguity — a project already past `DESIGN` keeps its `status`; no project-status check guards a lodgement — `routes/submittals.py:93-94`
- §3.8 — revise — **mismatch** — any cycle beyond the fourth carries 500.00, and the cycle limit guards resubmittal alone, so a fresh lodgement at `submittal_cycle_count` 4 is admitted as cycle five — `routes/submittals.py:246`, `ledger.py:89-90`
- §3.8 — revise — **mismatch** — on the complete-review MAJOR branch the package's `version` always advances but the project's only when the write moved a project figure — `routes/submittals.py:198,218`
- §3.8 — insert — ambiguity — `close_note` non-blank when present, and both `disposition` and `close_note` persist on a comment sent back to `OPEN` by `REJECT_RESPONSE` — `routes/comments.py:80,94-102`
- §3.8 — insert — ambiguity — project `status` untouched by resubmittal; the response is the successor package answered 201; the `included_calculation_ids` list filter is a membership test — `routes/submittals.py:252-257,113`
- §3.9 — insert — ambiguity — `measured_flow_gpm`/`measured_residual_psi` are required numbers that must not be negative — `routes/acceptance.py:177-178`
- §3.9 — insert — ambiguity — a second as-built lodgement from `AS_BUILT_SUBMITTED` is `ERR_INVALID_STATE_TRANSITION`; after acceptance, or against a `CLOSED_OUT` project, it is `ERR_TERMINAL_STATE_LOCKED` — `routes/acceptance.py:215-221`
- §3.9 — insert — ambiguity — the witness-pass join failure is `ERR_INVALID_STATE_TRANSITION`, and no such condition constrains `REJECTED` — `routes/acceptance.py:245-248`

Pass 3 also re-verified, against the code, the four sentences Step 8 and pass 1 had inserted (cascade-A seal-metadata retention, the withdrawal compensation's conditional project bump, the schedule-witness conditional project bump, and `sealed_calculation_count` untouched at close-out) and confirmed all four correct, leaving them unchanged.

### Orchestrator verification (independent)
- `PRD_COMPLETED.md` is 497 lines / 109,493 bytes vs `PRD_FINALIZED.md` 497 lines / 95,583 bytes — `cmp` confirms the two files DIFFER, so the known "byte-identical output means the scan never ran" failure did not occur. 44 diff hunks.
- Structure intact: 29 headings (same count as `PRD.md`), all 56 `ERR_` rows present in §5, file ends on the complete final error-table row.
- Steps 8 and 9 touched only `workspace/PRD_*.md`. The newest `implementation/` source file is stamped 09-03 23:28 and the newest test file 09-04 00:42, both earlier than the green sweep's `results.1.json` at 09-04 00:48 — so the 188/188-in-8-rounds result still applies to the artifacts as they stand on disk. No re-sweep was required.

## PIPELINE COMPLETE
All nine steps finished. Final artifacts: `SCAFFOLD.yaml` + both design indices, `test_helpers/` (9 modules, 2,665 lines), `test_suite/` (17 modules, 188 tests), `workspace/implementation/` (33 files, 3,508 lines), and the PRD chain `PRD.md` -> `PRD_FINALIZED.md` -> `PRD_COMPLETED.md`.
