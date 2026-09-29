# Worklog — task_2595_ambulatory_infusion_suite_scheduling_chair_utilization

## Step 1: Create task directory — 2026-09-03T00:00:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2595_ambulatory_infusion_suite_scheduling_chair_utilization` and its `workspace/` subdirectory. Index 2595 was pre-assigned by the invoking pipeline; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-03T19:00:00.000Z

All three artifacts are complete and the linter is clean.

**`SCAFFOLD.yaml`** — 3374 lines. Preamble (`scenario`, `domain_name`, `api_prefix`, `complexity_profile`, `response_envelope`) plus **14 entities**, 7 state machines, 3 `concurrency_rules`, 13 calculations, 55 validations, **68 endpoints**, 67 errors, 6 roles. No `scaffold_difficulty_design` / `scaffold_corner_design` keys (verified: top-level keys are exactly `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles`). Profile: `temporal_windowing` / `quota_allocation`, flat topology, parallel state machines, `peer_roles`, `immediate` consistency; layers `optimistic_concurrency, cascading_side_effects, dual_variant_calculation, selector_policy, ops_run_checkpoint`.

**`SCAFFOLD_DIFFICULTY_DESIGN.yaml`** — 1818 lines, single top-level key, **9 rule families / 19 instances**: `dual_variant_calc` (2), `combinatorial_formula` (3), `non_linear_state_machine` (2), `transitive_cascade` (2), `priority_pair_validation_conflict` (2), `boundary_precision_check` (2), `cross_entity_state_dependency` (2), `resource_temporal_overlap` (2), `compensating_invariant` (2).

**`SCAFFOLD_CORNER_DESIGN.yaml`** — 6528 lines, single top-level key, all **nine guide sections / 91 instances** (70 with full `test_recipe`, 21 `excluded_because` stubs pointing at named §1.8 instances): entities 12, state_machines 16, calculations 13, validations 10, endpoints 6, errors 20, rbac 6, cross_cutting_complexity_layers 7, consistency_model 1. Every `claim_type` token is a row name from `references/claim-extraction-guide.md`; `errors` uses `triggerable` (Table 6 has no claim-type table). This session added the errors tail (plan SUPERSEDED / COMPLETED, auth expiry at check-in, the urgent-reserve LIMIT-vs-UNAVAILABLE pair, the adverse-event review lifecycle, the lab-missing -> prep-not-ready ladder, plus 9 stubs), all six rbac instances (`exclusive_operations`, `unauthorized_cross_role`, `shared_operations`, two `peer_roles` for the nurse and patient identity bindings, `segregation_of_duties`), the cross-cutting layer set (three OCC rules, `selector_policy` ranking-key ordering, `ops_run_checkpoint` sweep semantics, two stubs) and the `immediate` consistency instance.

Coverage check: all **67 error ids** are now reachable from §1.8 union §1.9 (the last five — `ERR_NURSE_NOT_ASSIGNED`, `ERR_PATIENT_NOT_OWNER` and the three `ERR_STALE_*_VERSION` — landed in `rbac` and `cross_cutting_complexity_layers`).

Bugs found and fixed while writing: two invented error ids (`ERR_INVALID_APPOINTMENT_STATE` -> `ERR_INVALID_SCHEDULE_STATE`, `ERR_PLAN_NOT_SUSPENDED` removed), two literal `expected_treatment_plan_version: 2` payloads replaced with captured `${var}`s (lint rule (e)), an out-of-enum `channel: "PHONE"` and three out-of-enum `outcome: "CONFIRMED"` reminder values (enums are `{SMS, VOICE, PORTAL}` / `{NO_RESPONSE, CONFIRM_ATTENDANCE, CANCEL_REQUEST}`), a wrong HIGH-tier template assert (the HIGH surcharge is +1 acuity point, not a minutes multiplier), and a missing required `expected_drug_lot_version` on a positive adjustment call.

Linter verdict (verbatim):
```
Coverage
  §1.5 endpoints declared:    68
  §1.1 entities declared:     14
  §1.8 instances scanned:     19
  §1.9 instances scanned:     70
  Calls scanned (§1.8+§1.9):  1369

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Final line counts: `SCAFFOLD.yaml` 3374, `SCAFFOLD_DIFFICULTY_DESIGN.yaml` 1818, `SCAFFOLD_CORNER_DESIGN.yaml` 6528 (11720 total). All three pass `yaml.safe_load` and end on clean YAML boundaries. No sibling task directory was read at any point.

## Step 3: Copy shared files — 2026-09-03T19:00:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T19:22:00.000Z

PRD generated and verified. Output: `workspace/PRD.md`

**Build method.** Written incrementally as instructed — one `Write` for chunk 1, then six `cat >> ... <<'PRDEOF'` heredoc appends (§3.1–3.3, §3.4–3.5, §3.6–3.7, §3.8–3.9, §3.10, §4 table, §5 table), with `wc -l` after each. `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, and all sibling task directories were never opened; no difficulty framing appears in the prose.

**Final state.** 505 lines. Last heading: `## 5. Error Code Catalogue`. The file ends at a real boundary — the complete 67-row error table, final row `| ERR_DUPLICATE_MRN | 409 |`, no audit footer. Skeleton: §1, §2.1–§2.10, §3.1–§3.10 (domain-derived: suite estate -> drug/lot ledger -> patients/regimens -> templates & window sizing -> booking/selector -> authorization & lab gating -> compounding -> chair-side day -> attrition/pricing -> analytics & checkpoint), §4, §5. §2.2 is byte-identical to `section-2.2-response-structure.md`.

**Grep-verified coverage (counts measured on the output, not intent):** 68/68 endpoints present as method+path rows in §4; 67/67 error ids appear in §1–§3 narrative *and* in §5; 13/13 calculations expressed in prose (verified none is cited by its scaffold calculation name — only the coincident field names `no_show_risk_score`, `billable_chair_units`, `cancellation_charge_cents`, `observation_extension_minutes`, `biosimilar_savings_cents` appear); 55/55 validations have their condition in narrative paired to their error id, with the §2.8 precedence ladder naming all 16 priority tiers in order; 7/7 state machines with all 51 transitions covered.

```
Field coverage check:
- entities[].fields: 113 required, 113 present, 0 missing
- endpoints[].input (non-GET request bodies): 76 required, 76 present, 0 missing
- endpoints[].input (GET query params): 30 required, 30 present, 0 missing
- path params: 1 required, 1 present, 0 missing
- computed-read output keys: 21 required, 21 present, 0 missing
- union of all required identifiers: 138 required, 138 present, 0 missing
Status: PASS
```
```
Rule coverage check:
- validations[] with priority: 55 checked, 55 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (field + parent version mismatch + error id + 412 all named), 0 missing
- state_machines[].transitions: 51 checked, 51 fully expressed, 0 missing
- calculations[]: 13 checked, 13 fully expressed, 0 missing
- validations[] conditions: 55 checked, 55 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 36 side-effect sets + 55 applies_to scopes checked, all expressed, 0 missing
- entities[].fields[] structured content: 113 checked, 113 reconstructible from prose, 0 missing
- sibling-branch symmetry: 12 groups checked, 12 with equal prose density, 0 asymmetric
Status: PASS
```
```
§3 Path purity check:
- §3 backtick tokens scanned: 258
- tokens starting with "/": 0
- bare HTTP-method tokens: 0
- method+path tokens: 0
- unbackticked path leaks: 0
Status: PASS
```

**Scaffold self-inconsistencies resolved (no reinterpretation, majority-source rule):**
1. `POST /appointments/{id}/start-infusion` `side_effects` claims `PREPARED -> ADMINISTERED` with the lot committed->administered move, but both the `DrugPreparation` and `Appointment` state machines put that cascade on discharge. The PRD follows the two state machines (administration settles at discharge).
2. `ERR_INVALID_PREPARATION_STATE`'s error-catalog condition says return requires `REQUESTED`, while validation priority 43 and the state machine allow return from `REQUESTED` or `PREPARED`. Followed the validation table.
3. Validation priority 45 bars plan revisions on a `SUSPENDED` plan, yet the `TreatmentPlan` machine declares a `SUSPENDED -> SUPERSEDED` edge. Stated the bar plainly and noted the edge exists out of both `ACTIVE` and `SUSPENDED` with an identical cascade.

**Scaffold silences left silent rather than invented around:** confirm's "still holds `chair_id` and `nurse_id`" precondition and resume-from-non-`SUSPENDED` have no nominated error id (stated as requirements only); `appointment_count` in the utilization response has no defining formula, so it is described only as the count of visits the chosen variant attributed a length to.

**Errors caught and repaired during verification** (all in the §3.10 chunk, found by diffing my backtick tokens against the scaffold text): `expiry_date` -> `expires_on`; `stability_expires_at` -> `usable_until`; `no_show_strike_count` -> `no_show_strikes`; invented lot status `QUARANTINED` and chair statuses `MAINTENANCE`/`RETIRED` -> the real `AVAILABLE`/`DEPLETED`/`EXPIRED` and `OUT_OF_SERVICE`; sweep step 1 corrected to select `AVAILABLE` **or** `DEPLETED` with `expires_on` at-or-before the clock; utilization read roles narrowed to `Scheduler`/`MedicalDirector`; clock-set roles narrowed to the five staff roles; history injection narrowed to `Scheduler`. A final re-run of all three contracts after the repairs is what produced the PASS reports above.

**Orchestrator truncation check (independent of the subagent):** `wc -l` = 505; `tail -12` shows the error table closing on `| ERR_DUPLICATE_MRN | 409 |`; final heading is `## 5. Error Code Catalogue` at line 433. Ends at a real section boundary — not truncated. No regeneration needed.

## Step 5: Generate unit tests — 2026-09-03T21:30:00.000Z

All work is complete. Final report:

## Files written

**`test_helpers/`** (infrastructure, 8 modules + `__init__`, 3,255 lines total)
`__init__.py` 299 · `api_client.py` 419 · `api_errors.py` 171 · `assertions.py` 487 · `constants.py` 267 · `factories.py` 356 · `fixtures.py` 733 · `test_users.py` 80 · `types.py` 443

**`test_suite/`** (`conftest.py` 42 lines + 18 test modules, 9,351 lines)

| queue | file | lines | tests |
|---|---|---|---|
| A | test_01_variant_readings.py | 232 | 7 |
| A | test_02_combinatorial_arithmetic.py | 316 | 9 |
| A | test_03_parallel_state_dimensions.py | 208 | 7 |
| A | test_04_transitive_cascades.py | 310 | 8 |
| A | test_05_priority_conflicts.py | 206 | 6 |
| A | test_06_inclusive_boundaries.py | 234 | 6 |
| A | test_07_cross_entity_guards.py | 216 | 6 |
| A | test_08_half_open_windows.py | 219 | 7 |
| A | test_09_compensating_ledgers.py | 262 | 7 |
| B | test_10_entity_surface.py | 704 | 34 |
| B | test_11_state_machines.py | 893 | 28 |
| B | test_12_calculations.py | 1056 | 27 |
| B | test_13_validations.py | 926 | 22 |
| B | test_14_endpoints.py | 700 | 17 |
| B | test_15_errors.py | 1068 | 27 |
| B | test_16_rbac.py | 1014 | 18 |
| B | test_17_cross_cutting.py | 650 | 14 |
| B | test_18_consistency_model.py | 137 | 3 |

**Queue A: 63 tests over 19 non-stub difficulty instances. Queue B: 190 tests over 70 non-stub corner instances. Total 253 tests, 253 `Design:` tags — exactly one per test.**

## Verification
- Global audit: every non-stub instance in both indices is tagged at least once; `MISSING []`, `BOGUS []`, `STUBS TAGGED []`, no cross-section tags, no scaffold/§ citations, no unused/undefined imports in any module.
- `python3 -m compileall test_helpers test_suite` clean; `pytest --collect-only` collects 253 tests in 1.1 s.
- Both directories are at the task root; nothing was written or read under `workspace/`.

## Instances SKIPPED
**None.** All 89 non-stub instances (19 A + 70 B) had verbatim PRD coverage and uniquely-derivable outcomes. The five `excluded_because` stubs (state_machines x5, calculations x3, validations x2, errors x9, cross_cutting x2 = 21 stubs) were never translated, as required.

## Deviations inside translated instances (recipe claims the PRD contradicts)
1. `errors/...urgent_reserve_limit...` — recipe's third URGENT booking at minute 1050 would end at 1290, past `close_minute` 1140, and `ERR_OUTSIDE_OPERATING_HOURS` (ladder step 13) precedes the quota (step 15). Used minute 480 instead, preserving the instance's point that the quota is consulted before the chair search.
2. `rbac/one_patient_cannot_address_anothers_records` — dropped the cross-patient `GET /treatment-plans/{id}` -> `ERR_PATIENT_NOT_OWNER` assertion; PRD lines 22/123 enumerate the ownership surfaces (visit cancel, reminder answer, patient row, no-show risk, single appointment) and a plan read is not among them.
3. `endpoints/...sweep...` — dropped the sweep report's `center_id` echo; PRD §3.10 returns only the four counters.
4. `cross_cutting/reschedule...` — recipe's literal `version == 2` after auth+confirm is not derivable: PRD 263 makes the `APPROVED` decision's readiness movement a versioned write of the visit, so the confirm lands the row at 3. Asserted the relation instead (`re-read > booked`, `original == re-read + 1`), which is what the guard actually turns on.
5. `consistency_model/...` — dropped the "`chair_id` is null in the cancel response" assertion; PRD 303 states chair and nurse are deliberately **not** cleared on cancel. Asserted the retained assignment plus the recomputed release instead.

**Orchestrator placement check:** `test_helpers/` (10 entries) and `test_suite/` (20 entries) are at the task root; `workspace/test_helpers` and `workspace/test_suite` do not exist. No move needed before Step 7.

## Step 6: Generate implementation — 2026-09-03T20:45:00.000Z

The implementation is complete and verified.

## Files written — `workspace/implementation/`

| File | Lines |
|---|---|
`app.py` | 86 |
`db.py` | 188 |
`errors.py` | 107 |
`middleware.py` | 51 |
`response.py` | 54 |
`validators.py` | 286 |
`routes/appointments.py` | 501 |
`routes/clinical.py` | 511 |
`routes/reports.py` | 304 |
`routes/centers.py` | 238 |
`routes/patients.py` | 212 |
`routes/catalog.py` | 182 |
`routes/templates.py` | 105 |
`routes/common.py` | 16 |
`services/derive.py` | 516 |
`services/booking.py` | 261 |
`services/present.py` | 29 |
plus `start.sh`, `requirements.txt` (`flask>=2.0.0`), two empty `__init__.py` | — |
**Total Python** | **3647** |

## Endpoints: 68 implemented / 68 declared
Enumerated from `app.url_map` — exact 1:1 match with the PRD §4 table (all 14 collections, the 8 appointment lifecycle actions, the 4 appointment sub-resource creations, the 4 auth/prep/event action verbs, the 3 reports, `/_clock/set_current_utc`, `/_inject/appointment_history`).

## Smoke-test result: all green, 0 failures
Two scripted end-to-end runs against fresh servers (ports 18595/18596, killed by PID afterwards; ports confirmed free), plus a clean-boot probe on 18597:
- **Booking**: window build 30 premed + 150 admin (MID escalation) + 60 first-dose obs = 240 chair minutes, grid-snapped start 485->495, acuity 4; third same-slot booking on a 2-chair suite -> `ERR_NO_CHAIR_CAPACITY`.
- **Readiness dimension**: `PENDING` -> `AUTH_CLEARED` on approval -> `FULLY_CLEARED` on a qualifying draw -> `BLOCKED` by a grade-3 reaction -> discharge refused `ERR_ADVERSE_EVENT_OPEN` -> cleared by `RESUME_SAME_DRUG`.
- **Reaction window math**: grade 3 + `ABORT` -> extension 60, chair_minutes 240->300, end_minute recomputed.
- **Discharge/billing**: 226 realised minutes -> 16 units (ceil per visit) -> 144,000 cents; lot ledger walked 10 available -> 4 committed -> 4 administered / 6 available.
- **Reports**: SCHEDULED 540/1320 = 40.91%, ACTUAL 226/1320 = 17.12%, biosimilar savings 160,000 cents (4 units x 40,000 delta).
- **Sweep**: 1 no-show marked, second run at the same clock returned all four counters zero (idempotent).
- **Risk variants**: ROLLING_6 45.95 vs QUARTER_TO_DATE 50.00 on identical history; tier `INTENSIVE`.
- **Attrition**: `ERR_REMINDER_CADENCE_EXCEEDED` at the STANDARD cap; reschedule OCC -> 412 `ERR_STALE_APPOINTMENT_VERSION` then a 201 replacement carrying `rescheduled_from_appointment_id` with the original zero-charged; late cancellation priced 2500 + 35% x 60,000 = **23,500** cents.
- **Ladder spot-checks**: 401 `ERR_UNAUTHENTICATED`, 403 `ERR_UNAUTHORIZED`, 403 `ERR_PATIENT_NOT_OWNER`, 404 `ERR_APPOINTMENT_NOT_FOUND`, 400 `ERR_INVALID_REQUEST` on `limit=0`, and `ERR_PREP_STABILITY_SHORT` correctly outranking `ERR_PREP_TOO_EARLY`.
- **Fresh boot**: empty collections, logical clock defaults to `2026-08-01T00:00:00Z` (`previous_utc` echoed), correct envelope with pagination fields inside `meta` and `error_id`/`message` nested inside `data`.

Storage is in-memory dicts only; nothing is seeded, and `__pycache__` was removed so the tree is clean.

Notable spec conflicts resolved (documented inline): plan revisions are allowed from `SUSPENDED` (explicit PRD state-model sentence + the scaffold's dedicated `SUSPENDED -> SUPERSEDED` edge, over the generic three-bars recap); `ERR_APPOINTMENT_TERMINAL` outranks `ERR_INVALID_SCHEDULE_STATE` (PRD §2.8's explicit note, over the numeric priority order); `PREPARED -> ADMINISTERED` happens at discharge; `daily-sweep` is `Scheduler`-only (both tables agree, against the prose); `readiness_status` is derived at read time so a bare clock move never bumps `version`.

(Steps 5 and 6 were launched as concurrent background subagents; Step 6 returned first, hence the earlier timestamp. Both entries are recorded here after both exited.)

## Step 7: Run tests and iterate — 2026-09-03T21:59:00.000Z

All 8 rounds pass. Final report:

## Summary

**Iterations run:** 2 full 8-round parallel sweeps (sweep #1: 234/253 in all 8 rounds, 19 deterministic failures, zero flakiness; sweep #2 after the fix batch: clean).

### Tests deleted / assertions removed (PRD-silence category)

- `test_suite/test_10_entity_surface.py` — `test_the_creation_is_stamped_from_the_logical_clock_at_version_one`, `TestSystemStampedFieldsComeFromTheLogicalClock::test_*` (3 tests total): removed the `assert_instant_equals(created_at/updated_at, SETUP_CLOCK)` assertions. **STEP 1a PRD silence** — §2.5 fixes only the *format* of the audit instants ("an ISO 8601 UTC instant with three fractional digits") and says `updated_at` is "refreshed on every mutation of the row"; it never says which clock mints them. Kept format validity, insert-time equality, and `created_at` immutability. Scaffold rule: `Corner/entities/system_stamped_timestamps_and_version_come_from_the_logical_clock`.
- `test_suite/test_14_endpoints.py` — 2 tests: same silence, same replacement.
- `test_suite/test_15_errors.py` — `test_landing_exactly_on_zero_depletes_the_lot_and_a_credit_revives_it` renamed to `test_landing_exactly_on_zero_depletes_the_lot`; the "credit revives the DEPLETED lot" leg removed. **STEP 1c partial coverage / STEP 1b non-unique derivability** — the PRD contradicts itself: §2.6 lists "a positive inventory adjustment" among the recomputations that return a `DEPLETED` lot to `AVAILABLE`, while the adjustment rule itself says "an adjustment against a lot that is no longer `AVAILABLE` — because it has expired or been depleted — is refused with `ERR_LOT_NOT_AVAILABLE` (HTTP 409)". The covered half (zero is inside the range, lot derives `DEPLETED`, `units_received` 5->0, version 2) was kept and strengthened. Scaffold rule: `Corner/errors/an_adjustment_that_would_drive_units_available_below_zero_is_rejected`.

### Fixes applied to `test_helpers/`

None. `test_helpers/api_errors.py` was audited (all 67 §5 error->status entries correct) and `fixtures.py` traced end-to-end; every fixture proved PRD-faithful, so all test-side corrections belonged in `test_suite/`.

### Fixes applied to `implementation/`

- `routes/clinical.py`, `record_event` — added `derive.recompute_chair(appointment["chair_id"])` when the reaction's extension delta is non-zero. A chair's `committed_minutes` is *defined* as the sum of the `chair_minutes` of the visits holding it while committed, so lengthening an `OBSERVING` visit's window must raise the chair's figure (it stayed at the pre-extension value). Fixed 3 tests.
- `routes/clinical.py`, `read_reminder` — added the §2.8 ladder-step-4 `require_patient_owner(row["patient_id"])` guard. "A patient may only address rows that belong to them", and the ladder names "the addressed visit, reminder contact, or patient row"; the read was returning another patient's contact with 200. Fixed 1 test.

### Fixes applied to `test_suite/` (test-vs-PRD consistency)

- `test_01_variant_readings.py` — ACTUAL-variant `appointment_count` 2->1: §3.10 defines it as "the number of that day's visits ... to which the chosen variant attributed a length", and under ACTUAL the never-seated `CONFIRMED` visit "contributes nothing".
- `test_11_state_machines.py` — five version corrections. The tests modelled booking=1, confirmation=2, but §3.6 makes the `APPROVED` decision's readiness movement itself a version bump, so booking=1, approval=2, confirmation=3, demotion/seating=4. The nurse row likewise reads 4 (creation, booking's acuity raise, status edit, demotion's acuity recompute) because "a recomputation of a derived counter is a mutation for this purpose".
- `test_11_state_machines.py` / `test_15_errors.py` — the suspension- and revision-driven cancellations were asserted to null out `chair_id`/`nurse_id`; §3.11 says the opposite verbatim ("deliberately **not** cleared — they remain as an audit trail of who was scheduled to do the work"). Replaced with seat-retention assertions **plus** a new `committed_minutes == 0` assertion, which is what the cascade actually releases.
- `test_16_rbac.py` — 2 tests compared the lot's post-denial `version` against a snapshot taken before the fixture's own dose request (which legitimately bumps the lot). Re-read the lot as the baseline; also fed the *current* version to the adjustment payload so the sibling test's "the lot version is correct" claim is now true and the refusal can only be the credential.
- `test_17_cross_cutting.py` — `ERR_INVALID_REQUEST` expected status 422->400 per the §5 catalogue.

### Final sweep (per-round, quoted from the 8 results files)

| round | passed/total | failed | errors | duration |
|---|---|---|---|---|
| results.1.json | 253/253 | 0 | 0 | 470.8s |
| results.2.json | 253/253 | 0 | 0 | 471.4s |
| results.3.json | 253/253 | 0 | 0 | 472.5s |
| results.4.json | 253/253 | 0 | 0 | 470.8s |
| results.5.json | 253/253 | 0 | 0 | 470.8s |
| results.6.json | 253/253 | 0 | 0 | 471.3s |
| results.7.json | 253/253 | 0 | 0 | 471.3s |
| results.8.json | 253/253 | 0 | 0 | 470.9s |

All 8 concurrent rounds reported `passed == total == 253`, 0 failed, 0 errors, 0 skipped. No assertion was weakened to an HTTP-status check, no `skip`/`xfail` was added, no PRD-required implementation check was removed, and no data is seeded at startup (storage remains in-memory only). Scratch artifacts (`workspace/dbg.sh`, `workspace/sweep.log`, `workspace/implementation/results.*.json`, `/tmp` scan logs) were removed; no debug servers are left running.

### Orchestrator-run independent verification sweep (2026-09-03T21:59Z)

The Step 7 subagent deleted the `results.*.json` files it quoted, so the orchestrator re-ran the full 8-round sweep itself under `setsid nohup` to (a) confirm the pass claim first-hand and (b) leave the required artifacts on disk. Result, parsed directly from the eight files:

```
results.1.json 253 / 253 failed= 0 errors= 0 skipped= 0
results.2.json 253 / 253 failed= 0 errors= 0 skipped= 0
results.3.json 253 / 253 failed= 0 errors= 0 skipped= 0
results.4.json 253 / 253 failed= 0 errors= 0 skipped= 0
results.5.json 253 / 253 failed= 0 errors= 0 skipped= 0
results.6.json 253 / 253 failed= 0 errors= 0 skipped= 0
results.7.json 253 / 253 failed= 0 errors= 0 skipped= 0
results.8.json 253 / 253 failed= 0 errors= 0 skipped= 0
```

Reaping check: 0 occurrences of `Terminated` in `workspace/sweep.log`; the log's tail is a normal runner completion (`253/253 passed`, `Duration: 448.6s`, clean port release with `holders=8`). The pass is confirmed independently, and `results.{1..8}.json` are present in `workspace/implementation/`.

Step 7 made 2 `implementation/` fixes, so Step 8 is NOT skipped.

## Step 8: Finalize PRD — 2026-09-03T22:12:00.000Z

Patch complete. Verified minimal (6 lines touched, no line-count change, file intact end-to-end).

## Line counts
- `PRD.md`: 505 lines / 112,839 bytes
- `PRD_FINALIZED.md`: 505 lines / 114,725 bytes
- Delta: 0 lines (0.00%), +1,886 bytes (+1.67%); 6 of 505 lines revised in place, no new sections.

## Changes (one bullet each)

- **§2.1 (Patient ownership bullet)** — insert — added "reading a single reminder contact" to the enumerated set of `ERR_PATIENT_NOT_OWNER`-checked operations — `routes/clinical.py:471-478` (`read_reminder` -> `require_patient_owner`).
- **§2.5** — insert — (a) `created_at`/`updated_at` are stamped from the server's real **wall-clock** time, not the logical clock (which governs deadlines/expiries and the stamped domain instants of §3); (b) creation order is the effective tie-break wherever `created_at` sorts; (c) a recomputation that lands on the value the row already holds refreshes neither `updated_at` nor `version` — `implementation/response.py:11` (`wall_iso`), `db.py:142/152` (`new_row`/`touch`), `db.py:158-167` (`apply_changes` bumps only on change), `db.py:171` (`rows()` ordered by `_seq`).
- **§3.2 (lot status derivation)** — revise — removed the impossible "positive inventory adjustment revives a `DEPLETED` lot" edge; the revive edge is now returns-only, with a note that an adjustment against a non-`AVAILABLE` lot is refused first — `routes/catalog.py:170-171` vs `services/derive.py:134-141`.
- **§3.8 (reaction extension)** — insert — a non-zero extension delta also recomputes the *holding* chair's own `committed_minutes` in the same request (zero delta still leaves everything untouched) — `routes/clinical.py:325-328`.
- **§3.9 (system-initiated cancellations)** — insert — cascade/reschedule cancellations retain `chair_id`/`nurse_id` exactly like an operator cancellation; capacity release is carried purely by the chair/nurse recomputation — `services/derive.py:432-450` (single `cancel_appointment`, `system=True/False`).
- **§3.10 (utilization `appointment_count`)** — insert — pinned the counted status sets per variant (six contributing statuses under `SCHEDULED`; only `COMPLETED`/`INFUSING`/`OBSERVING` under `ACTUAL`) and that membership is by status alone, so a zero-length contribution still counts — `routes/reports.py:89-107`.

## Per-edit pre-edit search log

1. **§2.1 reminder ownership** — (a) Subject: Patient-role ownership enforcement. (b) Grepped every `require_patient_owner`/`require_nurse_owner` callsite: `middleware.py:46`, `patients.py:62,87`, `clinical.py:477,508`, `appointments.py:233,405`; read `patients.read_plan` (Patient allowed, **no** ownership check) and `clinical.list_reminders` (Patient allowed, **no** ownership filter). (c) Wording restricted to "reading a **single** reminder contact" so the list endpoints and the unchecked `GET /treatment-plans/{id}` are not implicitly claimed to be ownership-checked.

2. **§2.5 audit instants + no-op recompute** — (a) Subject: who mints `created_at`/`updated_at` and what counts as a mutation. (b) Read `response.wall_iso`, `db.new_row/touch/apply_changes/rows`, `catalog.create_lot:132-134` (version pinned back to 1), `clinical.create_lab_result` (`versioned=False`); grepped every `_seq`/`created_at` sort site (`db.py:171`, `centers.py:142`, `catalog.py:156`, `clinical.py:160,440,499`, `appointments.py:266`, `reports.py:64`, `booking.py:252`, `derive.py:164,254`); grepped all direct `touch(` callers (`centers.py:159,234`, `templates.py:104`) and all `recompute_*`/`sync_readiness` bodies (every one goes through `apply_changes`); checked `db.now()`-sourced fields (`decided_at`, `expires_at`, `prepared_at`, `usable_until`, `sent_at`). (c) Two adjustments: scoped the wall-clock claim to the two audit columns only (domain instants remain logical-clock); and **dropped** a planned companion clause that "an explicit edit endpoint always bumps" — `templates.patch_template:92-104` and `catalog.adjust_lot` (zero `units_delta`) do *not* bump, so that clause would have been a new mismatch. Ordering clause phrased direction-neutrally ("the earlier-created row compares as the earlier one") to stay true for the DESC orderings in `clinical.py:440` and `derive.py:254`.

3. **§3.2 lot revive edge** — (a) Subject: `DEPLETED` -> `AVAILABLE` transitions and adjustment guards. (b) Read `derive.recompute_lot:113-152` (only revive site; requires `available > 0` and `_expires_dt > now`) and enumerated all its callers: `catalog.create_lot`, `catalog.adjust_lot:170` (blocked unless `AVAILABLE`), `clinical.request_preparation`, `derive.prep_to_returned/prep_to_wasted/prep_to_administered`; confirmed only the return path can revive, and that `EXPIRED` is never left. (c) Kept "A positive inventory adjustment cannot travel **that edge**" rather than a blanket claim about adjustments, since a positive adjustment on an `AVAILABLE` lot does legitimately raise `units_received`/`units_available`.

4. **§3.8 chair recompute on extension** — (a) Subject: what a reaction's extension mutates. (b) Read `clinical.apply_observation_extension:272-293`, `clinical.record_event:323-330` (recompute gated on `delta != 0`; `bump_colliding_visits` only on `delta > 0`), `derive.recompute_chair`, `derive.bump_colliding_visits`; checked that `acuity_points` is untouched by the reaction path, so no nurse recompute occurs. (c) Phrased as "a non-zero difference also recomputes that chair's own `committed_minutes`" and left the following zero-delta sentence verbatim; deliberately said nothing about nurse acuity, which the path does not recompute.

5. **§3.9 system-initiated cancellations keep their seats** — (a) Subject: whether any cancellation clears `chair_id`/`nurse_id`. (b) Read `derive.cancel_appointment:432-450` (single implementation, never clears) and every caller: `appointments.cancel:414` (`system=False`), `clinical.respond_to_reminder:518` (`system=False`), `appointments.reschedule:463` (`system=True`), `derive.cancel_live_visits` <- `suspend_plan` <- `recompute_patient` steering flip / `clinical.close_review:391` / `patients.revise_plan:192`; contrasted with `derive.bump_appointment:474-477`, which *does* null both ids, and with `reports.daily_sweep:208` no-show marking, which also retains them. (c) Scoped the sentence to cancellations only (no universal claim over the no-show path, which retains ids too but is not a cancellation), and attributed the release solely to the recomputation so the bump path's clearing semantics stay distinct.

6. **§3.10 `appointment_count`** — (a) Subject: which visits the utilization report counts. (b) Read `reports.utilization:86-124` (the only site), `derive.UTILISATION_STATUSES`, `reports.LIVE_STATUSES`, and — to avoid collateral wording damage — `reports.chair_billing_summary:132-138`, whose separate `completed_appointment_count` counts `COMPLETED` only. (c) Added the "membership is decided by `schedule_status` alone ... still counted when the length works out to zero" clause because the impl increments the counter before testing whether `actual_start_minute`/`actual_end_minute` are present (reachable via `_inject/appointment_history` with the actual minutes omitted); kept the original "attributed a length" clause intact so the sentence remains a refinement rather than a redefinition.

**Orchestrator check:** `PRD_FINALIZED.md` exists at 505 lines and ends on the complete §5 error table (`| ERR_DUPLICATE_MRN | 409 |`) — not truncated.

**Worklog hygiene note:** the Step 7 entry was first appended while the shell's persistent cwd was `workspace/implementation/`, so it landed in `workspace/implementation/worklog.md`. It has been concatenated into this file in step order and the stray removed. The pre-existing `/home/ubuntu/github/CodingPRD/worklog.md` (dated Sep 2) belongs to another pipeline and was not touched.

## Step 9: Complete PRD — 2026-09-03T22:52:00.000Z

Pass 3 applied and final verification complete.

## Result

`workspace/PRD_COMPLETED.md` written as a minimal in-paragraph patch over `PRD_FINALIZED.md`.

- **Line counts:** source 505 -> completed 505 (no lines added, removed, or reordered; every hunk is a `Nc N` line-for-line replacement).
- **Chars:** 114,725 -> 132,313 (**+17,588**).
- **Changed lines:** 45. **Ambiguity-pins: 34. Mismatch-revisions: 11.**
- **All three passes completed** (Pass 1 app/db/errors/middleware/response/validators/present/common/centers/catalog/templates; Pass 2 booking/appointments/patients; Pass 3 clinical/reports/derive), edits applied at the end of each pass.
- **Tail intact:** file still ends on the complete §5 table with last row `| ERR_DUPLICATE_MRN | 409 |`. No section headings added or removed (`grep '^#'` structure identical).

### Changes

- §2.4 — revise — mismatch — minute-of-day band now excepts `open_minute`/`close_minute`/`addon_cutoff_minute`/`shift_start_minute`/`shift_end_minute` (0-1440), plus three shape conventions (explicit `null` = omitted with three named exceptions; strict types; unknown fields ignored / absent body accepted) — validators.py:29-160, centers.py:40-56
- §2.6 — insert — ambiguity — percentages and scores travel as JSON numbers in shortest form, compared numerically — db.py:124-126
- §3.1 — revise — mismatch — `addon_cutoff_minute` window bound enforced only when explicitly supplied; the 900 default stored unchecked — centers.py:46-49
- §3.1 — insert — ambiguity — duplicate chair `label` -> `ERR_INVALID_REQUEST`, after centre resolution, before the reserved/out-of-service conflict — centers.py:101-105
- §3.2 — insert — ambiguity — duplicate drug `name` -> `ERR_INVALID_REQUEST`, before `reference_drug_id` resolution — catalog.py:52-56
- §3.2 — revise — mismatch — `reference_drug_id` null-when-not-biosimilar is unpoliced; existence-only check, stored as given — catalog.py:40,55-56
- §3.2 — revise — mismatch — `lab_min_anc`/`lab_min_platelets` never actually required by a gated drug; anc fractional, platelets integer; null threshold skipped — catalog.py:50-51, derive.py:179-186
- §3.2 — insert — ambiguity — duplicate `lot_number` -> `ERR_INVALID_REQUEST`; `expires_on` echoed raw; `units_received` 0 lot born `DEPLETED` at `version` 1 — catalog.py:113-135
- §3.2 — revise — mismatch — lapsing past `expires_on` never moves the stored status; only the checkpoint writes `EXPIRED`; a lapsed lot still reads `AVAILABLE` yet is invisible to selection/compounding — derive.py:133-141
- §3.2 — insert — ambiguity — adjustment bar reads stored `status` only; bar order stale-version -> `ERR_LOT_NOT_AVAILABLE` -> `ERR_INSUFFICIENT_DRUG_UNITS`; zero `units_delta` mutates nothing — catalog.py:167-181
- §3.3 — insert — ambiguity — `weight_kg` may be fractional and is echoed exactly; fresh patient reads `completed_appointment_count` zero — patients.py:38-54
- §3.3 — insert — ambiguity — the six patient figures are always recomputed in one pass with the steering flip on the fresh figures; one `version` bump, none if nothing moved — derive.py:306-348
- §3.3 — insert — ambiguity — resume requires a non-blank `reason`; steering violation -> `ERR_PATIENT_STEERING_HOLD` after the three status bars — patients.py:200-210
- §3.3 — revise — mismatch — omitted `premed_waived` on a revision reverts to false rather than inheriting; replacement born `completed_cycles` 0 / `first_dose_completed` false and is what the 201 returns — patients.py:161-193
- §3.3 — revise — mismatch — plan-status bars scoped per path; revision legal out of `SUSPENDED`; resumption refuses an already-`ACTIVE` regimen with `ERR_PLAN_SUSPENDED`; no `ERR_PLAN_PATIENT_MISMATCH` on the revision path — patients.py:169-210
- §3.4 — insert — ambiguity — duplicate ACTIVE (centre, drug, tier) -> `ERR_INVALID_REQUEST` after both FKs resolve — templates.py:43-50
- §3.4 — revise — mismatch — each lever bumps `version` only when it moves the row; same-status write and empty PATCH are 200 no-ops; `resnapshot: true` always bumps — templates.py:92-104
- §3.5 — insert — ambiguity — `cycle_number` has no shape range so 0/negative reaches `ERR_CYCLE_OUT_OF_RANGE`; raw `requested_start_minute` outside `[open, close)` -> `ERR_OUTSIDE_OPERATING_HOURS` — appointments.py:146, booking.py:63-72
- §3.5 — insert — ambiguity — the patient double-booking test uses the grid-snapped first candidate window, not the window finally selected — appointments.py:176
- §3.5 — insert — ambiguity — booked row minted at `version` 1 with the unearned fields at rest and `requested_start_minute` retained — appointments.py:189-221
- §3.5 — revise — mismatch — confirmation reports `ERR_AUTH_NOT_APPROVED` for both absent and lapsed approval (`ERR_AUTH_EXPIRED` belongs to check-in alone); missing chair/nurse -> `ERR_INVALID_SCHEDULE_STATE` — appointments.py:276-290
- §3.6 — insert — ambiguity — filed request carries `approved_units`/`decision_reason`/`decided_at`/`expires_at` null; no bar beyond non-terminal, any number of filings — clinical.py:51-67
- §3.6 — insert — ambiguity — the conditional `approved_units` requirement is `ERR_INVALID_REQUEST` evaluated *after* the `SUBMITTED` state check; `approved_units` ignored on PENDED/DENIED, `decision_reason` ignored on APPROVED — clinical.py:122-138
- §3.6 — insert — ambiguity — `anc_value` fractional, `platelet_value` whole; either value omitted or null -> `PENDING` with that field null — clinical.py:402-413
- §3.6 — insert — ambiguity — readiness is re-derived on every read (single, collection, and write bodies) and the `readiness_status` filter matches the derived value — present.py:11-19, appointments.py:261
- §3.7 — insert — ambiguity — dose created with `prepared_at`/`usable_until` null and `waste_cost_cents` zero — clinical.py:175-189
- §3.7 — insert — ambiguity — `ERR_PREP_STABILITY_SHORT` is evaluated before `ERR_PREP_TOO_EARLY`; both follow the state and lot checks — clinical.py:234-238
- §3.7 — insert — ambiguity — explicit return requires a non-blank `reason`; a `PREPARED` dose at/after `usable_until` -> `ERR_INVALID_PREPARATION_STATE` — clinical.py:258-266
- §3.8 — insert — ambiguity — a `BLOCKED` readiness is itself `ERR_ADVERSE_EVENT_OPEN`; the start bar is patient-wide, any grade, any visit or drug — appointments.py:326-333
- §3.8 — insert — ambiguity — discharge bar scoped to this visit and grade >= 3; a realised span <= 0 floors `billable_chair_units` at zero — appointments.py:368-375
- §3.8 — revise — mismatch — the post-extension collision test is symmetric (an *earlier* colliding visit is bumped too), runs only when the maximum rose, only touches `TENTATIVE`/`CONFIRMED`, and does nothing when the visit holds no chair — derive.py:495-516
- §3.8 — insert — ambiguity — closing `note` written only when supplied; a non-`ACTIVE` regimen means the disposition is recorded with no cascade and still 200; the two suspending outcomes do not refresh stored readiness (no visit `version` bump) — clinical.py:380-392, derive.py:453-458
- §3.9 — insert — ambiguity — reschedule: add-on trio never fires, steering hold and open-reaction bar not retested, cycle test ignores the original, nothing mutated until the replacement's slot is found, success answers 201 — appointments.py:418-501
- §3.9 — insert — ambiguity — recording outreach against a terminal visit -> `ERR_APPOINTMENT_TERMINAL` before the cadence cap; cap read from the patient's live tier, not the visit's cadence code — clinical.py:451-456
- §3.9 — insert — ambiguity — a `CANCEL_REQUEST` against a visit outside `TENTATIVE`/`CONFIRMED` still records the answer and answers 200 — clinical.py:515-518
- §3.9 — insert — ambiguity — the risk read reports the patient's persisted `reminder_tier`, unchanged by the `QUARTER_TO_DATE` variant — patients.py:88-101
- §3.10 — insert — ambiguity — utilization `service_date` is a required query parameter checked before the centre resolves — reports.py:77
- §3.10 — insert — ambiguity — `biosimilar_savings_cents` is returned under both variants — reports.py:46-71,122
- §3.10 — insert — ambiguity — chair-billing `service_date` likewise required and pre-resolution — reports.py:130
- §3.10 — revise — mismatch — the sweep is `Scheduler`-only (resolving the §3.10 prose against the §4 table) and `service_date` is a required *body* field — reports.py:151-155
- §3.10 — insert — ambiguity — a `NO_SHOW` row retains `chair_id`/`nurse_id`, keeps `cancellation_charge_cents` zero and leaves `late_cancellation` untouched — reports.py:205-212
- §3.10 — insert — ambiguity — the sweep response echoes `center_id` and `service_date` alongside the four counters — reports.py:214-222
- §3.10 — insert — ambiguity — clock set echoes both instants in the exact spelling supplied, `previous_utc` defaults to `2026-08-01T00:00:00Z`, and backwards moves are legal — reports.py:227-234, db.py:53-57
- §3.10 — insert — ambiguity — injection defaults and ranges, FK order, `billable_chair_units` only when both actual minutes are present, the full mechanical field fill (`premed`/`observation`/`extension` 0, `admin` = `chair_minutes`, `end` = start + chair, template `acuity_points`/`version` snapshot, charge 0), no booking-time gate of any kind, answers 201, and the regimen's `status` is never closed by injection — reports.py:237-304, appointments.py:393-395
- §4 — insert — ambiguity — enumerated the seventeen 201-answering creations (ten collection POSTs plus `reschedule`, `authorization-requests`, `drug-preparations`, `adverse-events`, `reminders`, `revisions`, `_inject/appointment_history`); every other POST answers 200 — routes/*.py `created()`/`ok()`
- §5 — insert — ambiguity — three transport-level identifiers outside the catalogue: `ERR_NOT_FOUND` 404, `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INTERNAL` 500 — app.py:42-76, errors.py:83-86

### Notes

- Two PRD-internal contradictions were resolved in the implementation's favour: §3.10's "Scheduler or MedicalDirector runs the sweep" now matches the §4 table's `Scheduler`, and §3.3's revision bars now permit the supersede edge out of `SUSPENDED`.
- The six sites already pinned in `PRD_FINALIZED.md` were left untouched.
- `SCAFFOLD*.yaml` and `worklog.md` were never opened; tests were used only as auxiliary cross-reference, never as the alignment target.

### Orchestrator verification (independent)

- `PRD.md` 505 lines / 112,839 bytes; `PRD_FINALIZED.md` 505 / 114,725; `PRD_COMPLETED.md` 505 / 132,313.
- `cmp` confirms `PRD_COMPLETED.md` is **not** byte-identical to `PRD_FINALIZED.md` (90 diff lines, i.e. 45 line-for-line replacements) — the scan genuinely ran.
- `diff <(grep '^#' PRD_FINALIZED.md) <(grep '^#' PRD_COMPLETED.md)` is empty: no section added, removed, or renamed.
- Tail ends on the complete §5 error table (`| ERR_DUPLICATE_MRN | 409 |`) — not truncated.

## Pipeline complete — 2026-09-03T22:55:00.000Z

All nine steps finished. Final artifacts in place: `SCAFFOLD.yaml` (3374 lines), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1818), `SCAFFOLD_CORNER_DESIGN.yaml` (6528), `test_helpers/` (9 modules, 3255 lines), `test_suite/` (conftest + 18 modules, 9351 lines, 253 tests), `workspace/PRD.md`, `workspace/PRD_FINALIZED.md`, `workspace/PRD_COMPLETED.md`, `workspace/implementation/` (3647 lines Python, 68/68 endpoints, in-memory only) and `workspace/implementation/results.{1..8}.json` from the orchestrator-run verification sweep, all eight at 253/253.
