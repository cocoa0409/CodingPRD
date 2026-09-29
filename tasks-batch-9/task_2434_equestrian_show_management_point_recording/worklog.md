# Worklog — task_2434_equestrian_show_management_point_recording

## Step 1: Create task directory — 2026-09-02T16:16:00.550Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2434_equestrian_show_management_point_recording` and its `workspace/` subdirectory. Index 2434 was pre-assigned by the invoking pipeline (no `./tasks/` scan performed, per instruction, to avoid collisions with the up-to-32 concurrent pipelines on this host).

## Step 2: Generate Scaffold — 2026-09-02T18:22:21.439Z

Scaffold generation for task 2434 is complete and lint-clean.

## Output files
All three under `/home/ubuntu/github/CodingPRD/tasks/task_2434_equestrian_show_management_point_recording/`:
- `SCAFFOLD.yaml` (§1.0–§1.7) — contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

## SCAFFOLD.yaml counts
14 entities (graph topology) · 10 state machines (branching) · 8 calculations (2 dual-variant) · 42 ordered validations (priority 1–65) · 54 endpoints (`api_prefix: "/"`) · 72 error codes · 7 roles (`segregation_of_duties`) · 2 OCC concurrency rules. Profile: `difficulty_level: beyond_expert`, primary `temporal_windowing`, secondary `compliance_audit`, layers `[dual_variant_calculation, cascading_side_effects, optimistic_concurrency, rate_threshold_triggers]`, `consistency_model: saga`.

## Design instances
- §1.8: **18 instances** (dual-variant pairs, cascade unwinds, priority-collision pairs, aggregate boundaries, temporal geometry, zero-drift ledgers).
- §1.9: **69 instances = 47 real + 22 `excluded_because` stubs**, across all 9 guide sections: entities 11, state_machines 14, calculations 17, validations 9, endpoints 5, errors 4, rbac 4, cross-cutting layers 4, consistency model 1. All names unique across both files; every stub cites a real §1.8 instance name and carries no `test_recipe`.

## Verification
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
  §1.5 endpoints declared:    54
  §1.8 instances scanned:     18
  §1.9 instances scanned:     47
  Calls scanned (§1.8+§1.9):  1798
```
Additional self-checks: every `grounds:` path resolves against SCAFFOLD.yaml (entities/fields, calculation variants and constants, state machines, `validations.priority_N`, error ids, endpoint signatures, `concurrency_rules.slot-create-stale-ring`, `roles.*.exclusive_operations`/`shared_operations`, `response_envelope.*`, `complexity_profile.*`); all 72 error codes are exercised by at least one design instance (0 uncovered).

## Design adjudications
1. **`ERR_SEGREGATION_OF_DUTIES` was unreachable.** The official-overlap rule (priority 43, closed interval + 20-minute travel gap) made a second chair on the *same* RingSlot always collide first, so the same-person-judge-and-steward check could never fire. Fixed in SCAFFOLD.yaml (three edits: `official_load_ledger` formula comment, the P43 `check:`, and the `ERR_OFFICIAL_TIME_CONFLICT` condition) so the travel gap applies only across *different* rings and same-slot assignments are exempt.
2. **`ERR_UNPAID_PLACED_ENTRY` was unreachable.** Entry withdrawal was blocked whenever any ClassEntry was `COMPLETED`, so a placed entry could never become unpaid. Narrowed the withdrawal precondition (plus matching error condition) so a `COMPLETED` row blocks withdrawal only once its class reaches `RESULTS_POSTED`/`POINTS_SUBMITTED`/`VOIDED`; a `COMPLETED` row on a merely `JUDGED` class now leaves a placed-but-refunded entry, which is exactly what the saga instance `failed_posting_leaves_no_partial_prize_writes` exercises (402 with zero prize writes at all three ledger levels).
3. Reachability path chosen for `ERR_HORSE_SUSPENDED`: only a POSITIVE `ComplianceCase` finding sets `Horse.eligibility_status = SUSPENDED`, so a cheap drug-case flow is embedded in the verification-gate corner instance rather than relying on fixture state.
4. One field-name and two endpoint-existence corrections were applied during authoring (`settlement_status` not `payment_status`; `GET /shows/{id}/coverage-shifts?...` and `GET /classes?division_id=...` in place of the non-existent `GET /coverage-shifts/{id}` and `GET /divisions/{id}/classes`; `$.data.class_purse_cents` not `purse_cents`).

Orchestrator verification: all three files present (SCAFFOLD.yaml 2708 lines, DIFFICULTY 2659, CORNER 6439). Confirmed SCAFFOLD.yaml has no `scaffold_difficulty_design`/`scaffold_corner_design` top-level key — the single grep hit at line 874 is a prose `note:` comment, not a key.

## Step 3: Copy Shared Files — 2026-09-02T18:22:40.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2434_equestrian_show_management_point_recording/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-02T18:33:09.547Z

The PRD is complete and all three hard contracts pass mechanically.

## What was written

`/home/ubuntu/github/CodingPRD/tasks/task_2434_equestrian_show_management_point_recording/workspace/PRD.md` — **521 lines**, ~84 KB, ending cleanly at the final row of the §5 error table.

**Structure** (12 × §2 subsections, 9 × §3 subsections, domain-derived titles):

- §1 Introduction (3 paragraphs)
- §2: 2.1 RBAC · 2.2 API Response Structure (verbatim from `section-2.2-response-structure.md`, byte-identical) · 2.3 Pagination · 2.4 Collection Filters · 2.5 Common Resource Properties · 2.6 The Logical Show Clock · 2.7 Optimistic Concurrency · 2.8 Path Resolution and Referential Integrity · 2.9 Precision, Rounding and Units · 2.10 Conserved Ledgers · 2.11 Cascade Discipline · 2.12 Validation Precedence (full 15-band ladder with intra-band ordering)
- §3: 3.1 Licensing · 3.2 Divisions/Classes/Purse Waterfall · 3.3 Grounds, Footing and Coverage · 3.4 Registries · 3.5 Entry Processing (two dimensions + confirmation join) · 3.6 Ring Scheduling and Officiating · 3.7 Calling the Class and the Judge's Card · 3.8 Posting the Purse and the Two-Body Standings Saga · 3.9 Compliance and the Disqualification Cascade
- §4 endpoint table (4 columns) · §5 error table (2 columns)

## Verification counts

```
Field coverage check (Contract 1):
- entities[].fields:          103 required, 103 present, 0 missing
- endpoints[].input identifiers (request_body + query_params + path vars): 76 required, 76 present, 0 missing
- state enumeration values:   all present, 0 missing
- enum-type field values:     all present, 0 missing
Status: PASS

Rule coverage check (Contract 2):
- validations[] with priority: 42 checked, 42 expressed in prose, 0 missing
- concurrency_rules[] OCC:      2 checked, 2 expressed (write_endpoint + expected_ring_version/expected_class_version + ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: 10 machines / 44 transitions checked, 44 fully expressed, 0 missing
- calculations[]:               8 checked, 8 fully expressed (pinned evaluation orders preserved), 0 missing
- validations[] conditions:    42 checked, 42 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 54 checked, 54 expressed, 0 missing
- entities[].fields[] structured content: 103 checked, 103 reconstructible, 0 missing
- sibling-branch symmetry:      6 groups checked (licence APPROVE/RETURN/DENY, RETURN-vs-escalation, footing 3 branches, PointSubmission national/regional forks, Entry two dimensions, finding NEGATIVE/WARNING/POSITIVE), 0 asymmetric
Status: PASS

Path purity check (§3 only, Contract 3):
- backtick tokens scanned: 885
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS

Endpoint coverage: 54/54 scaffold endpoints present as §4 table rows (method+path exact match); table row count = 54.
Error coverage:    72/72 scaffold error IDs present in §5 table; row count = 72; 0 HTTP-status mismatches vs scaffold.
```

## Notes

- Two Contract 2 gaps were found and repaired during the walk: `entry_count` and `confirmed_entry_count` had their identifiers present but their status-set definitions absent (the `COMPLETED`-inclusion in `confirmed_entry_count` is load-bearing for the national multiplier tier), and the two OCC rules now name their write endpoints explicitly in §2.7.
- Fuzzy-language scan (approximately / roughly / conservatively / about N / ~N) returns zero hits; all 8 calculation formulas are prose with pinned evaluation orders (single `ceil` after multiplication for ride minutes; round-per-place-then-sum with residual to first place only at five filled ribbons; office-fee tier keyed on `preliminary_subtotal_cents` and evaluated once).
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced.

Orchestrator anti-truncation check (per invocation instruction): independently read the tail of `workspace/PRD.md`. It ends at a genuine boundary — the last line is a complete `| \`ERR_PAYMENT_AMOUNT_MISMATCH\` | 422 |` table row, not mid-sentence. Section headings run through `## 5. Error Code Catalogue` (line 445) with all §2/§3/§4/§5 sections present. No regeneration needed.

## Step 5: Generate Unit Tests — 2026-09-02T20:03:32.543Z

(Launched concurrently with Step 6 in a single assistant message, so the impl-gen subagent could not see `test_suite/`.)

The suite is complete and audited.

## Files written

Test infrastructure — `/home/ubuntu/github/CodingPRD/tasks/task_2434_equestrian_show_management_point_recording/test_helpers/`
`__init__.py`, `types.py`, `api_client.py` (54 endpoint methods), `api_errors.py`, `constants.py`, `test_users.py`, `factories.py`, `assertions.py`, `fixtures.py` (composite builders: `build_approved_show`, `build_multi_class_show`, `build_confirmed_entry`, `build_active_coverage`, `stage_class_slot`, `run_class_to_posted`, …)

Test cases — `.../test_suite/`
`conftest.py`; queue A: `test_01_duration_and_standings_variants.py` … `test_09_conserved_ledger_compensation.py` (4 tests each); queue B: `test_10_entity_reads_and_shapes.py` (11), `test_11_state_machine_corners.py` (9), `test_12_calculation_corners.py` (9), `test_13_validation_corners.py` (5), `test_14_endpoint_corners.py` (2), `test_15_typed_error_corners.py` (4), `test_16_rbac_corners.py` (4), `test_17_cross_cutting_and_consistency.py` (3).

## Test counts

- Queue A (Difficulty, §1.8): 36 tests over 18 instances / 9 rules — exactly 2 per instance.
- Queue B (Corner, §1.9): 47 tests over 47 translatable instances — 1 per instance.
- Total: 83 tests, all with exactly one `Design:` line, none untagged or dual-tagged.

## Instances skipped

None for PRD-filter reasons. Every instance carrying a `test_recipe` was translated. The 22 corner instances without a recipe are design-declared exclusions (`excluded_because`, deduped against a §1.8 instance) and are not translatable units: state_machines 5, calculations 8, validations 4, endpoints 3, cross_cutting 2.

Two *sub-probes* inside translated instances were dropped rather than weakened, because the PRD does not uniquely derive the outcome the recipe wanted: the dual-bogus-FK probe in `body_and_path_fk_ids_return_typed_not_found` (PRD declares no order among body foreign keys, so `ERR_OFFICIAL_NOT_FOUND` vs `ERR_SLOT_NOT_FOUND` is unpinned — replaced with two single-bogus probes), and an assigned-stall-count variant of the office-fee tier test (§3.5 pins the invoice to the *requested* count, so the recipe's assigned-count framing is unobservable).

## Audit results

- Tag resolution: 83/83 tags resolve to real instances; 0 unresolved, 0 dual, 0 untagged.
- Coverage: difficulty ≥2/instance satisfied for all 18; corner ≥1/instance satisfied for all 47.
- Citations: 405 `PRD §x.y: "..."` lines, all verbatim substrings of `workspace/PRD.md` (`missing: 0`).
- Scaffold-leak pass: no `SCAFFOLD` / `§1.8` / `§1.9` references anywhere in emitted code.
- `python3 -m py_compile` clean over `test_suite/` and `test_helpers/`; every `test_helpers` import resolves; one leftover unused import (`make_steward_headers` in `test_04`) found and removed.

Note on the final file: `test_17` covers OCC on the ring version (snapshot 1 → 201, replay → 412 `ERR_STALE_VERSION` with the ring frozen at version 2, retry → version 3 / `scheduled_minutes_total` 40), the welfare-strike threshold (1 strike starts the ring, 2 refuses the next call with `ERR_WELFARE_STRIKE_LIMIT` while the horse stays `ELIGIBLE`, since a `WARNING` suspends nothing), and the all-or-nothing posting saga (post-judging withdrawal leaves a placed-but-refunded row → 402 `ERR_UNPAID_PLACED_ENTRY`, every `prize_cents` 0, `awarded_prize_cents` 0 against `class_purse_cents` 41721, ledger 0/750000, replay identical). PRD §3.5 line 282 explicitly blesses that path — "a `COMPLETED` class entry on a class that is merely `JUDGED` does *not* block withdrawal" — so it is uniquely derived rather than assumed.

## Step 6: Generate Implementation — 2026-09-02T20:03:32.543Z

(Launched concurrently with Step 5 in a single assistant message.)

Implementation complete and verified.

## Files written
All under `/home/ubuntu/github/CodingPRD/tasks/task_2434_equestrian_show_management_point_recording/workspace/implementation/`:

| File | Lines |
|---|---|
| `start.sh` | 19 |
| `requirements.txt` | 1 |
| `app.py` | 76 |
| `core.py` | 351 |
| `errors.py` | 103 |
| `response.py` | 88 |
| `auth.py` | 53 |
| `validate.py` | 146 |
| `serializers.py` | 270 |
| `calc.py` | 120 |
| `services.py` | 512 |
| `routes/__init__.py` | 17 |
| `routes/reads.py` | 277 |
| `routes/shows.py` | 239 |
| `routes/grounds.py` | 268 |
| `routes/classes.py` | 362 |
| `routes/entries.py` | 367 |
| `routes/registry.py` | 98 |
| **total** | **3367** |

## Endpoints
**54 implemented: 23 GET + 31 POST.** I diffed the route table against the PRD section 4 endpoint tables (path params normalized): zero missing, zero extra.

## Storage
In-memory only — `core.Store` is a set of plain dicts keyed by UUID plus a `current_utc` logical clock defaulting to `2026-08-01T00:00:00Z`. No SQLite, no file/JSON persistence, no `/tmp` cache, and nothing seeded: a fresh boot returns `total_count: 0` for every collection. `start.sh` runs `exec python3 app.py` in the foreground on `0.0.0.0:${PORT:-10000}` with `use_reloader=False`, so it is safe under `--isolation per-test-server`.

## Boot verification
Fresh `PORT=18456 bash start.sh`, then `GET /classes?limit=5` with `X-User-Role: ShowSecretary`:
```
HTTP 200
{"meta":{"api_request_id":"req_62OCJ2Y0USKEWX99NN9D","api_request_timestamp":"2026-09-02T19:10:30.843Z",
  "limit":5,"offset":0,"total_count":0,"has_more":false},"response_type":"array","data":[]}
```
Also confirmed the error envelope shape (`GET /shows/nope` → 404 `ERR_SHOW_NOT_FOUND`; no headers → 401 `ERR_UNAUTHENTICATED`; entity-backed Exhibitor against an empty store → 403 `ERR_ACTOR_NOT_RECOGNIZED`). Server killed cleanly each time, no listeners left, no `__pycache__` residue in the deliverable.

## Work done since the last checkpoint
- **`routes/classes.py::void_results`** — moved the accepted-submission guard ahead of the `RESULTS_POSTED` state guard. Raising a submission itself moves the class to `POINTS_SUBMITTED`, so with the state check first `ERR_SUBMISSION_ALREADY_FINALIZED` was unreachable on this endpoint; the reorder makes both codes reachable (a `JUDGED`/`VOIDED` class still yields `ERR_CLASS_RESULTS_NOT_POSTED`, and a `PREPARED` submission is not in the blocking set, so it also still yields the state error). Same reachability reasoning previously applied to `ERR_CLASS_ALREADY_SCHEDULED` vs `ERR_CLASS_NOT_OPEN` in `routes/grounds.py`.
- Removed two unused imports (`set_value` in `routes/grounds.py`, `show_of_class` in `routes/entries.py`); `compileall` clean.

## Test results
Both throwaway smoke suites (~120 assertions each covering the happy path, all 15 validation bands, the two deep cascades, the fork-join saga and every conserved ledger) now report **0 failures**. Spot-checked values match the PRD arithmetic exactly: duration estimate 29 min, purse 2,500,000, 3-ribbon award 2,025,000, 5-ribbon residual reconciliation (awarded == purse, first place 400,000), invoice tiering 35000→5000→40000, national 20.0 / regional 16, footing cascade releasing official minutes 103→53 with the class back to `OPEN` and `estimated_minutes` null, welfare strikes 2, and rejection compensating rider totals to 0.

One earlier fix worth flagging for the test-suite author: mutation responses now report the **post-bump** `version`, because `core.touch()` bumps eagerly (deduped per row per request via `g._dirty_ids`), rows created in the same request stay at version 1, and `set_value()` only bumps when the stored value actually changes.

## Step 7: Run Tests and Iterate — 2026-09-02T20:16:16.617Z

Clean 8-round sweep: **83/83 in all 8 parallel rounds.**

## Summary

**Iterations run:** 2 (sweep → 4 deterministic failures in all 8 rounds → fixes → clean sweep)

**Tests deleted:** none. One assertion was removed under STEP 1c partial-coverage handling:
- `test_04_footing_and_doping_cascades.py::test_positive_sample_disqualifies_reverts_the_class_and_releases_the_prize_money` — dropped `assert second["prize_cents"] == 0` (the *non*-disqualified runner-up's row). BRANCH-ASYMMETRIC SIDE EFFECT silence: PRD §3.8 line 346 explicitly says voiding resets "every class entry on the class" `prize_cents` to 0, while the POSITIVE-finding cascade in §3.9 line 376 enumerates its side effects "in order" and resets `prize_cents` only on the rows that move to `DISQUALIFIED`, with the reverted class getting only `awarded_prize_cents` reset plus counter recomputation. A faithful PRD-only implementer leaves an untouched placed row's `prize_cents` at its posted figure (10430 here), so the assertion is not uniquely derivable. The surrounding assertions (row still `COMPLETED`, `placing == 2`, class `JUDGED`/`awarded_prize_cents == 0`/`placed_count == 3`, show ledger back to 0/750000, `welfare_strike_count == 0`) were all kept and pass. Scaffold rule that drove it: `Difficulty/transitive_cascade/positive_drug_finding_unwinds_results_and_prize_ledger`.

**Fixes applied to `test_helpers/`:** none — the helpers were faithful; all three remaining defects were in `test_suite/`.

**Fixes applied to `test_suite/`:**
- `test_10_entity_reads_and_shapes.py::test_omitted_optional_inputs_land_on_their_declared_defaults` — removed a redundant `submit_license(show["id"])` before `approve_license(...)`. The `approve_license` fixture itself performs DRAFT→SUBMITTED→APPROVED, so the extra call submitted twice and the PRD-required §3.1 guard correctly answered `ERR_SHOW_LICENSE_NOT_DRAFT`, killing the setup.
- `test_10_entity_reads_and_shapes.py::test_the_class_entry_junction_carries_both_of_its_filters_independently` — same double-submit removed; also dropped the now-unused `submit_license` import.
- `test_15_typed_error_corners.py::test_the_prize_list_refuses_the_four_construction_errors_on_their_exact_boundaries` — passed the division **dict** instead of `div_h["id"]` as the path segment, so the URL never resolved and the server correctly returned `ERR_DIVISION_NOT_FOUND` (§2.8 left-to-right path resolution) instead of the asserted `ERR_CLASS_NUMBER_DUPLICATE`. Changed to `div_h["id"]`; the show-scoped duplicate-number check now fires as intended.

**Fixes applied to `implementation/`:** none. No implementation defect was found — the three setup/URL failures were test bugs and the fourth was PRD-silence in the test.

Key files: `test_suite/test_10_entity_reads_and_shapes.py`, `test_suite/test_15_typed_error_corners.py`, `test_suite/test_04_footing_and_doping_cascades.py`.

Orchestrator verification (per memory note: a Step 7 subagent can claim a clean sweep while leaving no artifacts behind): independently parsed all eight `workspace/implementation/results.{1..8}.json` (each ~26 KB, mtime 20:13). Every round reports `passed=83, total=83, failed=0`. Sweep artifacts confirmed real.

Step 8 skip decision: NOT skipped. Step 7 ran 2 iterations with 3 `test_suite/` fixes and 1 partial-coverage assertion removal, so the skip condition (0 deletions / 0 test_suite / 0 test_helpers / 0 implementation fixes) is not met.

## Step 8: Finalize PRD — 2026-09-02T20:19:25.774Z

PRD_FINALIZED.md written with one edit.

**Line counts:** PRD.md 521 lines → PRD_FINALIZED.md 521 lines (0.0% line delta; one line revised in place, +332 chars).

**Changes:**
- §3.9 (line 376) — revise — appended a sentence pinning that the POSITIVE-finding cascade's `prize_cents` reset touches only rows moving to `DISQUALIFIED`; other class entries on a reverted class keep their posted `prize_cents` even though the class's `awarded_prize_cents` returns to 0 — `implementation/services.py:356-377` (zeroing at :366 is inside the DQ loop; the reverted-class loop at :371-377 only clears `awarded_prize_cents` and recomputes counters).

**Pre-edit search log (single edit):**
- (a) Subject: `prize_cents` on class entries during/around the POSITIVE compliance cascade, and every other operation that writes or clears `prize_cents`.
- (b) Paths enumerated (grepped `prize_cents` repo-wide, then read each): `implementation/services.py:348-396` `positive_finding_cascade` (sets `prize_cents=0` only on DQ'd rows, `awarded_prize_cents=0` on RESULTS_POSTED classes, then `recompute_placed_count`/`recompute_class_counts`/`recompute_show_prizes`); `implementation/routes/classes.py:253-266` `post_results` (writes per-place figures for `COMPLETED` placed rows, 0 otherwise); `implementation/routes/classes.py:282-284` `void_results` (zeroes `prize_cents` on **every** class entry — the branch-asymmetric counterpart); `implementation/routes/entries.py:273` class-entry creation (`prize_cents=0` at birth); `implementation/services.py:173-184` `scratch_class_entries` (withdrawal moves `ENTERED`/`CONFIRMED`→`SCRATCHED` and never touches `prize_cents` — those rows are always 0 since only `COMPLETED` rows are ever paid); `implementation/services.py:43-57` counter recomputes (no `prize_cents`); `implementation/serializers.py:218` (echoes stored value verbatim).
- (c) Adjustment: scoped the new sentence with "in this cascade" and "on a reverted class" so it cannot be read as a universal claim about `prize_cents` — §3.8's void, which *does* zero every row, and the initial-value/scratch paths remain correctly described by their own existing prose. Also phrased the class-level clause as "has returned to 0" rather than asserting the class reverted, so classes touched by the cascade that were not in `RESULTS_POSTED` (impl recomputes their counters without clearing money) are not mis-described.

**No PRD edit for the three `test_suite/` fixes** — all were fixture/URL bugs against behavior the PRD already determines uniquely: the double `submit_license` hitting the §3.1 `ERR_SHOW_LICENSE_NOT_DRAFT` guard (impl `routes/shows.py` license-submission), and the division-dict-as-path-segment resolving to §2.8 `ERR_DIVISION_NOT_FOUND` before the show-scoped duplicate check. I additionally verified `create_class` orders qualifier-cycle → jump-height → class-number-duplicate (`implementation/routes/classes.py:61-82`), which matches the §2.12 bands 12/14 ordering already in the PRD, so no pinning was needed there either.

Orchestrator verification: diffed PRD.md against PRD_FINALIZED.md — exactly one changed line (376), an in-place append to the existing §3.9 cascade sentence. No sections added, no other prose touched.

## Step 9: Complete PRD — 2026-09-02T20:31:35.642Z

Done. `PRD_COMPLETED.md` written.

## Verification
- **521 lines** (identical to source), **99,316 chars vs 84,883** → **+14,433 chars**; zero line-count change (all edits are in-paragraph).
- Section heading set byte-identical to `PRD_FINALIZED.md` (no sections added/removed).
- **§4 endpoint rows: 54** ✓ · **§5 error rows: 72** ✓ · file ends at `| \`ERR_PAYMENT_AMOUNT_MISMATCH\` | 422 |` — a genuine section boundary, not truncated.

## Counts
**39 changes: 27 ambiguity-pins, 12 mismatch-revisions.**

## Changes
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST`, empty string = absent; insertion-sequence tie-break on `created_at`; filters compared as strings — `response.py:62`, `core.py:264`, `routes/reads.py:25`
- §2.4 — insert — ambiguity — standings `show_id` is not resolved (unknown id → zeroed totals, no 404) — `routes/reads.py:198`
- §2.5 — insert — mismatch — `version` advances at most once per *request* per row; rows created by the request stay at 1; all rows a request mutates share one `updated_at` — `core.py:218`
- §2.5 — revise — mismatch — a recomputation reproducing existing values bumps nothing — `core.py:240`
- §2.6 — revise — ambiguity — clock write answers 200 with `data` = `{current_utc}` only, no common properties — `routes/registry.py:92`
- §2.8 — insert — ambiguity — unrouted path → 404 `ERR_NOT_FOUND`; bad method → 405 `ERR_METHOD_NOT_ALLOWED` (both outside §5) — `app.py:45`
- §2.8 — insert — ambiguity — JSON `null` = omitted; absent body = `{}`; unparseable body → 422 not 400; int fields reject bools/floats; non-string FKs are shape violations — `validate.py:13`, `validate.py:70`, `app.py:53`
- §2.9 — insert — ambiguity — points transmitted as JSON numbers, national keeping its tenth (`10.0`) — `core.py:170`, `serializers.py:165`
- §2.10 — insert — mismatch — `assigned_minutes` decrement floored at zero; maintained incrementally, not re-summed — `services.py:210`
- §2.11 — revise — mismatch — cascade bumps only resources it genuinely changes — `core.py:240`
- §2.12 band 14 — revise — mismatch — class-list completeness precedes division share — `routes/shows.py:86`
- §2.12 band 15 — revise — mismatch — unpaid-placed-entry precedes prize-pool headroom — `routes/classes.py:239`
- §3.1 — insert — ambiguity — licence submission carries no body — `routes/shows.py:80`
- §3.1 — insert — ambiguity — `correction_note` is a first-class show field, null at creation; the three instants are never cross-validated — `routes/shows.py:57`
- §3.1 — insert — ambiguity — the structural lock covers divisions/classes only; rings and coverage windows have no licence gate — `routes/shows.py:152`, `routes/shows.py:220`
- §3.2 — insert — ambiguity — `max_jump_height_cm < min` → `ERR_INVALID_REQUEST` at band 6 (before licence lock and share ceiling) — `routes/shows.py:191`
- §3.2 — revise — mismatch — opening a class does **not** check the division's `ACTIVE` status (only `PLANNED`, then licence `APPROVED`) — `routes/classes.py:110`
- §3.3 — insert — ambiguity — `warmup_capacity_horses` is recorded but gates nothing — no reader in impl
- §3.3 — revise — ambiguity — `new_footing_condition_score` is 0–100; the pass answers with the updated **ring** at 200, not the synthesised occupancy — `routes/grounds.py:45`, `routes/grounds.py:78`
- §3.3 — insert — ambiguity — overlap check is keyed on the resulting score ≥ 60, not the starting posture (so it also applies to a hold-lifting pass); `ERR_RING_NOT_AVAILABLE` precedes containment/overlap — `routes/grounds.py:47`
- §3.3 — insert — ambiguity — coverage instants unordered/uncontained, overlaps allowed, show `version` untouched — `routes/shows.py:230`
- §3.4 — insert — ambiguity — no uniqueness on federation identifiers; registration dates not clock-checked — `routes/registry.py:24`
- §3.5 — insert — ambiguity — entry submission checks nothing more; same rider/horse/show triple may repeat; no other resource mutated — `routes/entries.py:75`
- §3.5 — insert — mismatch — invoicing tests `WITHDRAWN` **before** the settlement state, so a withdrawn-after-invoicing entry reports `ERR_ENTRY_ALREADY_TERMINAL` — `routes/entries.py:140`
- §3.5 — revise — mismatch — entering a class evaluates Coggins/eligibility **before** the entry window (ladder order); parent `verification_status` is not a precondition, even `WITHDRAWN` — `routes/entries.py:243`
- §3.6 — insert — mismatch — the already-scheduled test precedes `ERR_CLASS_NOT_OPEN` — `routes/grounds.py:106`
- §3.6 — insert — ambiguity — maintenance occupancies also carry `end_utc`, `status` `SCHEDULED` and a 30-minute `warmup_start_utc` — `routes/grounds.py:58`
- §3.6 — insert — ambiguity — carding has no occupancy-status or licence precondition; `MAINTENANCE` slots are cardable with the discipline and conflict checks skipped; the occupancy's `version` does not move — `routes/grounds.py:213`
- §3.6 — insert — ambiguity — "the show" for an occupancy always means the **ring's** show; cross-show bookings are permitted — `routes/grounds.py:118`, `routes/grounds.py:153`, `routes/grounds.py:222`
- §3.6 — insert — ambiguity — `class_projections` element fields (`class_id`, `class_number`, `ring_id`, `slot_id`, `projected_minutes`, `confirmed_only_minutes`, `drift_minutes`), ordering by class `created_at`, omission of unscheduled classes, earliest-created slot wins, no pagination in `meta` — `services.py:470`
- §3.7 — insert — ambiguity — calling a class answers with the updated **ring slot** — `routes/grounds.py:191`
- §3.7 — revise — mismatch — card checks run judge-chair → segregation → entries-present → placings (ladder, not reading order); placing element shape with optional `round_seconds`; empty `placings` legal; no `RUNNING` occupancy → `ERR_JUDGE_NOT_ASSIGNED`; duplicate `class_entry_id` → `ERR_INVALID_PLACINGS` — `routes/classes.py:161`
- §3.7 — insert — ambiguity — the whole ring layout is recomputed (usually a no-op, so no ring bump); response is the updated **class**; confirmed counts/eligibility recomputed and unchanged — `routes/classes.py:216`
- §3.8 — insert — mismatch — void tests submission finality **before** the class state, otherwise `ERR_SUBMISSION_ALREADY_FINALIZED` is unreachable — `routes/classes.py:274`
- §3.8 — insert — ambiguity — repeating an already-accepted leg → `ERR_SUBMISSION_ALREADY_FINALIZED` — `routes/classes.py:343`
- §3.8 — insert — ambiguity — omitted `body_reference` stored as null; the other body's reference is never touched — `services.py:246`, `services.py:291`
- §3.8 — insert — ambiguity — rejection ignores `standings_body` and `body_reference`, sweeps every class entry, reverts the class only from `POINTS_SUBMITTED` — `routes/classes.py:336`, `services.py:321`
- §3.8 — insert — ambiguity — standings read returns exactly five fields, unpaginated, recomputed from the scales (not from stored `points_*`), grouped per show with the cap restarted at zero — `services.py:402`
- §3.9 — insert — ambiguity — `opened_by_official_id` is resolved but never compared to `X-User-ID`; empty strings fail both conditional tests; opening mutates nothing and no entry/show state bars it — `routes/entries.py:288`
- §3.9 — revise — mismatch — the positive cascade re-sums the prize ledger of the case's show **and** every show owning a touched class — `services.py:389`

One note for the caller: the two framework-level codes (`ERR_NOT_FOUND`, `ERR_METHOD_NOT_ALLOWED`) are documented inline in §2.8 as explicitly outside the §5 catalogue, so the 72-row table is unchanged.

Orchestrator verification: `PRD_COMPLETED.md` = 521 lines / 99,316 chars (vs PRD_FINALIZED 84,883). Independently recounted the tables — §4 has 54 endpoint rows, §5 has 73 rows including the header = 72 distinct `ERR_` ids. File ends at the complete `| \`ERR_PAYMENT_AMOUNT_MISMATCH\` | 422 |` row, not truncated. Steps 8 and 9 touched documentation only; `implementation/` is byte-identical to the tree that produced the clean 8×83/83 sweep, so no re-sweep was required.

## Pipeline complete — 2026-09-02T20:31:35.642Z

All nine steps done. Final state: 83 tests, 8/8 parallel rounds green at 83/83, `workspace/PRD_COMPLETED.md` written.
