# Worklog — task_2630_perfusion_services_cardiopulmonary_bypass_case_coverage

## Step 1: Create task directory — 2026-09-03T22:02:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2630_perfusion_services_cardiopulmonary_bypass_case_coverage` and its `workspace/` subdirectory. Index 2630 was pre-assigned by the invoking command; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-03T23:59:00.000Z

All three scaffold artifacts are complete and lint-clean.

**Output** — `/home/ubuntu/github/CodingPRD/tasks/task_2630_perfusion_services_cardiopulmonary_bypass_case_coverage/`

| file | lines | bytes | top-level key |
|---|---|---|---|
| `SCAFFOLD.yaml` | 3221 | 175583 | §1.0–§1.7 only (verified: no `scaffold_difficulty_design`, no `scaffold_corner_design`) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2408 | 175199 | `scaffold_difficulty_design` (20 instances) |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4850 | 342547 | `scaffold_corner_design` (73 instances) |

**Lint verdict (verbatim tail):**
```
Coverage
  §1.5 endpoints declared:    53
  §1.1 entities declared:     14
  §1.8 instances scanned:     20
  §1.9 instances scanned:     48
  Calls scanned (§1.8+§1.9):  1156

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**§1.9 section breakdown** (73 instances = 48 with full `test_recipe`, 25 `excluded_because` stubs): entities 12/0, state_machines 11/5, calculations 4/9, validations 9/8, endpoints 4/1, errors 2/0, rbac 3/0, cross_cutting_complexity_layers 2/2, consistency_model 1/0. All nine guide sections present.

**Final sections written this session:** `cross_cutting_complexity_layers` — a real `optimistic_concurrency` instance exercising both declared `concurrency_rules` (stale creation-time `${case1_v}` → 412 ERR_STALE_CASE_VERSION, `"${c1_v_now2} - 1"` → 412 ERR_STALE_CONTRACT_VERSION, then both re-quoted and accepted, asserting the accrual cascade also bumped the contract version); a real `selector_policy` instance that discriminates revision-DESC from created_at-DESC (rev-3 card created before a rev-2 card, both ACTIVE → pack must apply rev 3 at 1139 cents / prime 1600, then a new rev-3 card supersedes both while the existing pack keeps its pinned card, and the next case prices at 1247 / prime 1700); plus stubs delegating the cascade and dual-variant corners to the §1.8 instances `transitive_cascade / critical_alarm_cascades_device_case_checklist_billing` and `dual_variant_calc / case_fee_provisional_vs_final_diverges_on_actual_pump_time`. `consistency_model` — one `immediate` instance asserting the assignment response itself carries the provisional fee/status/version and that immediate reads show the contract ledger, recomputed THIN coverage posture and readiness 0.694.

**Integrity checks run:** per-instance duplicate-key auditor (0 issues across all 73 instances — this catches the stray-`trigger:` failure mode PyYAML swallows silently), all `excluded_because.difficulty_instance` refs resolve to real §1.8 instance names, no stub carries a `test_recipe`, instance names unique across the union of both design files, and each file ends at a real YAML boundary.

Orchestrator verification: `ls -la` confirms all three files present plus surviving `workspace/`; `yaml.safe_load` parses all three; top-level keys confirmed correct.

## Step 3: Copy shared files — 2026-09-04T00:03:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2630_perfusion_services_cardiopulmonary_bypass_case_coverage/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T00:40:00.000Z

Wrote `workspace/PRD.md` (475 lines, 16553 words, 115 KB) from `SCAFFOLD.yaml` alone. `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened or grepped, and no sibling task directory was read. Built with successive chunked appends to stay clear of the single-write output cap.

**Structure:** §1 Introduction; §2 Global Specifications (2.1 actors/RBAC, 2.2 response envelope copied byte-identical from the skill's fixed block, 2.3 pagination, 2.4 identity/timestamps/version, 2.5 logical clock, 2.6 money and rounding, 2.7 OCC, 2.8 the 72-rung judging order, 2.9 cascade discipline and ledger conservation); §3 Business Logic in ten subsections (contracts and master data, credentialing and readiness, call rotation and coverage posture, scheduling and staffing, packs and machine reservation, pre-bypass verification/run/cancellation, device events and the alarm cascade, ECMO and relief staffing, quality review, case close and monthly settlement); §4 endpoint table (53 rows); §5 error table (72 rows). Ends at §5 with no audit footer.

**Hard Contract verification (scripted):** field-name coverage 131/131 backticked identifiers present (all `entities[].fields[].name` plus every endpoint input and query-param name), plus all nested array-element keys (`line_code`, `quantity`, `unit_cost_cents`, `substituted`, `line_total_cents`, `replacement_code`, `replacement_unit_cost_cents`, `reason`, `check_code`, `passed`, `note`) and both computed output objects; rule coverage — all 72 error ids appear in §1–§4 prose and all 72 appear in §2.8 in exact priority order, all state-machine states referenced, all eight calculations reconstructable with literal constants in prose; §3 path purity — 0 backticked tokens in §3 begin with `/`, name a bare HTTP method, or combine method and path (paths appear only in §4).

## Step 4: Generate PRD — 2026-09-04T00:24:00.000Z

PRD generated and verified.

**Output:** `workspace/PRD.md` — 475 lines, 16,553 words, ~115 KB, built with 11 successive chunked `cat >>` appends (no single giant write, no truncation).

**Withheld-input compliance:** `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced; no sibling task directory under `tasks/` was read. Sources were `SCAFFOLD.yaml`, the doc-generator `SKILL.md`, the fixed `section-2.2-response-structure.md`, and this task's own `worklog.md`.

**Structure**
- §1 Introduction (pain → system arc → REST/logical-clock framing)
- §2 Global Specifications, nine subsections: 2.1 actors/headers/RBAC, 2.2 response envelope (byte-identical copy), 2.3 pagination, 2.4 identity/timestamps/`version`, 2.5 the logical clock, 2.6 money/credit-hours/rounding discipline, 2.7 OCC (both rules), 2.8 the 72-rung judging order, 2.9 cascade discipline and ledger conservation
- §3 Business Logic, ten subsections: contracts and master data; credentialing, CE and readiness; call rotation and coverage posture; scheduling and staffing; preference cards, packs and machine reservation; pre-bypass verification, the run, cancellation; device events and the critical-alarm cascade; ECMO and relief staffing; quality review; case close and monthly settlement
- §4 endpoint table (53 rows), §5 error table (72 rows). File ends at the last error row — no audit footer, no PASS reports inside the document.

**Hard Contract 1 — Field-Name Coverage: PASS.** 131/131 required identifiers appear verbatim in backticks (every `entities[].fields[].name` across all 14 entities plus every endpoint `input`/query-param name). Additionally verified: all nested array-element keys (`line_code`, `quantity`, `unit_cost_cents`, `substituted`, `line_total_cents`, `replacement_code`, `replacement_unit_cost_cents`, `reason`, `check_code`, `passed`, `note`), both computed output objects (11 settlement fields, 4 clock fields), and the envelope/pagination fields. Verified by script; 0 missing.

**Hard Contract 2 — Rule Coverage: PASS.** All 72 error ids appear in §1–§4 prose (not only in the §5 table), and all 72 appear inside §2.8 in exact scaffold priority order (scripted order check: sequence identical). Every state named by any `state_machines` transition appears in the document. All 8 calculations are reconstructable from prose with literal constants (per-line vs. whole-fee vs. once-only rounding placements distinguished; interval-merge posture with 4320/2160-minute thresholds; ceiling-hours ECMO pricing with a worked example; tiered settlement with the pre-credit tier key and floor-at-zero net). Both OCC rules, both `concurrency_rules` error ids, all four cascade link sets (alarm 1/2/2b/3/4 and systemic 1/2/3/4), all sibling-branch asymmetries (ISOLATED vs. SYSTEMIC, ACCEPT vs. RETURN, the three-way device fork at end-bypass, clean vs. service-due), and all `applies_to` scopes are stated.

**Hard Contract 3 — §3 Path Purity: PASS.** Scripted scan of §3 (69,028 chars): 0 backticked tokens start with `/`, 0 are bare HTTP methods, 0 combine method+path, 0 contain `/` at all. §1–§2 are likewise path-free; paths appear only in the §4 table.

Two derived judgements worth flagging: `MAX_INCIDENT_RETURNS` has no declared value in the scaffold, so it is derived as 2 from the `return_count` description ("a third return attempt is rejected") and expressed in prose as "the two-return ceiling"; and cancellation's "no open ECMO run" precondition has no error id in the scaffold, so it is stated as an unreachable combination rather than being assigned an invented identifier.

Orchestrator truncation check (per the known doc-generator failure mode): `tail -c 1200` shows the file ending on a complete `| \`ERR_CONTRACT_CASE_CAP_EXCEEDED\` | 409 |` table row at a real section boundary — not mid-sentence. Independent cross-check against SCAFFOLD.yaml: 72/72 scaffold error ids present in PRD.md, 53/53 scaffold endpoint paths present, §5 table has exactly 72 `ERR_` rows. No regeneration needed.

## Step 6: Generate implementation — 2026-09-04T00:55:00.000Z

The implementation is complete and verified.

## What was built

`workspace/implementation/` — 18 files, 3,388 lines of Python, plus `start.sh` and `requirements.txt`.

Modules finished this session:
- `routes_run.py` (260 lines) — start-bypass, end-bypass with the forked device branch, ECMO run creation, handoffs, decannulate
- `routes_incidents.py` (177 lines) — file/read/list/submit/review/close with the frozen audit score and the systemic gate
- `app.py` (67 lines) — blueprint registration, `ApiError` handler, 404/405/HTTPException/500 handlers, `0.0.0.0:$PORT` (default 10000), `threaded=True`, `use_reloader=False`, no seeding

Existing modules: `errors.py`, `store.py`, `envelope.py`, `valid.py`, `auth.py`, `constants.py`, `calc.py`, `serialize.py`, `svc.py`, `routes_master.py`, `routes_people.py`, `routes_devices.py`, `routes_slots.py`, `routes_cases.py`, `routes_packs.py`.

## Verification

- **Endpoint coverage: exact match.** A programmatic diff of `SCAFFOLD.yaml`'s 53 endpoints against Flask's `url_map` shows zero missing and zero extra routes.
- **Boot smoke test passed.** Launched via `PORT=18765 bash start.sh`, ran a 40-step end-to-end scenario (contract → surgeon → preference card → 3 perfusionists → certification → CE activity + verification → 2 devices with backup link → contract PUT with OCC → primary + backup call slots → case → assign → pack → checklist → verify → start-bypass → ECMO run → clock advance → decannulate → end-bypass → incident file/submit/review/close → case close → monthly settlement → all 17 GET/list endpoints). Killed by exact PID; no broad `pkill` was used.
- Coverage posture correctly flipped `UNCOVERED → COVERED` after the two slots; clock advance returned `relief_pending_run_count: 1`; settlement produced `pre_credit_gross_cents 3684000`, `quality_credit_cents 150000`, `net_settlement_cents 3534000` with the case moving `FINAL_ACCRUED → INVOICED`.
- Error paths spot-checked: all three `ERR_INVALID_PAGINATION` shapes, `ERR_MISSING_AUTH_HEADERS`, `ERR_INVALID_ROLE`, `ERR_UNAUTHORIZED`, `ERR_INVALID_REQUEST` on malformed JSON, `ERR_CLOCK_NOT_MONOTONIC`, `ERR_CASE_NOT_FOUND`, plus generic 404/405.
- **No seeding, no persistence.** A grep for `seed|preload|sqlite|open(|json.dump(` across all modules returns only the three docstring lines asserting the absence. `__pycache__` was removed.

## Notes

- The one non-200 in the scenario was expected: `POST /disposable-packs/{id}/approve` returned `ERR_PACK_APPROVAL_STATE_INVALID` because the pack had no substitutions, so its `approval_status` was `NOT_REQUIRED` — correct per PRD §3.7.
- `ERR_SYSTEMIC_FINDING_UNSUPPORTED` is named only in PRD §3.9 prose with no HTTP status anywhere in the PRD or scaffold; I resolved it as **422**, evaluated after rungs 20/23/36 on incident close.
- `readiness_variant_last` is written only by assignment-time admission computation and by review acceptance (`AUDIT`); the re-derives at end-bypass and decannulate refresh `readiness_score` but leave the variant field alone, matching the PRD's "assignment-time admission computation" / "quality-review audit computation" wording.
- The prohibitions held throughout: `test_helpers/`, `test_suite/`, both `SCAFFOLD_*_DESIGN.yaml` files, and every sibling task directory were never read.

Orchestrator note: Steps 5 and 6 were launched as separate background agents seconds apart rather than in one message; the impl generator was given an explicit hard prohibition on reading `test_helpers/`/`test_suite/`/both design yamls, and reports it never read them. `test_helpers/` and `test_suite/` were confirmed at the task root, not under `workspace/`.

## Step 5: Generate unit tests — 2026-09-04T02:10:00.000Z

The suite is complete.

## Deliverable

**`test_helpers/`** — 9 modules, 2315 lines (`__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`).

**`test_suite/`** — 12 files, 5784 lines, **88 tests**. Finished this session:
- `test_11_cross_entity_and_temporal.py` (618 lines, 10 tests) — the two `cross_entity_state_dependency` instances (ECMO handoff gated entirely on the foreign slot row: wrong `slot_type`/holder refused, then the `SCHEDULED` relief row succeeds and, once `consumed`, is out of the pool for the run's second relief cycle; pack configuration gated on the primary pump, driven to `NEEDS_SERVICE` by `SELF_TEST_FAIL` and restored by a service completion) plus the three `resource_temporal_overlap` instances (holder-scoped half-open slot overlap vs. bare adjacency and nested merge; the 90-minute device turnaround boundary at exactly 90 vs. 91 minutes with `open_reservation_count` reaching 2; the aggregate concurrent-case limit refusing the third intersecting case).
- `test_12_compensating_invariant.py` (318 lines, 6 tests) — contract accrual ledger through assign → supersede → cancel against a pinned control accrual (case and contract versions each +3); device reservation ledger where the first of two holders cancels (decrement to 1, machine stays `RESERVED`) and only the second frees it, with maintenance counters untouched and pack rows retained; CE ledger verify/verify/revoke returning `ce_credits_verified` to exactly 12.5 with no one-decimal drift, proven downstream by the admission score of 0.603 the next assignment stores.

## Verification (all clean)
- `audit_design2630.py`: 88 tests, **0 tag problems**; every test carries exactly one trailing `Design:` line resolving to a live instance; **20/20 difficulty instances >=2 tests, 48/48 corner instances >=1**; none of the 25 `excluded_because` stubs is translated, and all 25 of their `difficulty_instance` cross-references resolve.
- Citation audits: `non-verbatim quotes: 0`, `citation problems: 0` (every `PRD <sec>:` line is a full verbatim sentence and the cited section matches the heading range).
- `python3 -m pyflakes test_suite/*.py` silent; no unused imports/consts/helpers in any file; `compileall` OK.
- Both directories are at the task root; `workspace/test_helpers` and `workspace/test_suite` do not exist; `workspace/implementation/` was never read or touched; no server was started and no test was executed.

Two design assertions were deliberately not emitted because they are not uniquely derivable from the PRD: the checklist's `verified_by_perfusionist_id` "unchanged" after cancellation (§3.6 only specifies `blood_mgmt_signoff` false and `verified_at` null), and p2's readiness figure in the certification-vs-cap tests noted earlier.

## Step 7: Run tests and iterate — 2026-09-04T02:25:00.000Z

Clean sweep: all 8 parallel rounds 88/88.

## Summary

**Iterations run:** 2 (iteration 1 = baseline diagnosis at 63/88 in every round; iteration 2 = 88/88 in all 8 rounds).

Iteration 1 was fully deterministic — the identical 25 failures in all 8 rounds, no flakiness signal, so no load-induced noise to discount.

**Tests deleted:** none. Every failing test traced to a verbatim PRD rule and passed the unique-derivability check; all 25 failures were test-fixture bugs or one implementation formatting defect.

**Fixes applied to `implementation/`:**
- `workspace/implementation/envelope.py` — added `iso_instant()` alongside `iso()`. PRD §2.4 scopes the three-fractional-digit format to `created_at`/`updated_at` only ("in the same timestamp format"), and PRD §2.5 states the clock "reads exactly `2026-08-01T00:00:00Z`" and that the clock endpoint "echoes `current_utc`". Domain instants were being reformatted to `.000Z`, so a field PRD says is "set to the logical clock" no longer read back as the clock value.
- `workspace/implementation/serialize.py` — `_common()` and `event_log()` keep the 3-fraction stamp for `created_at`/`updated_at`; all 15 domain instants (`issued_on`, `expires_on`, `activity_date`, `last_service_completed_at`, `window_start/end`, `scheduled_start/end`, `bypass_started_at/ended_at`, `setup_verified_at`, `verified_at`, `cannulated_at`, `last_handoff_at`, `decannulated_at`) now preserve the instant. Fixed 13 tests.
- `workspace/implementation/routes_slots.py` — `set_clock` echoes `current_utc` via `iso_instant`, per "it echoes `current_utc`".

**Fixes applied to `test_suite/` (test bugs — fixtures/assertions inconsistent with PRD):**
- `test_11_cross_entity_and_temporal.py` `_three_intersecting_case_windows`, `test_12_compensating_invariant.py` `_ledger_with_a_control_accrual` — claimed `credit_hours=30` in one CE activity, which PRD §3.2 forbids ("no greater than 20"); the implementation correctly returned `ERR_INVALID_FIELD_VALUE`. Split into two in-cycle claims of 15 h, preserving the intended 30 pending hours and the asserted 0.637 readiness score. (4 tests)
- `test_10_priority_and_boundary.py` `_lapsed_candidate_env` and `_two_staff_env` — the second holder had `career_case_count=90` and only 20 credit hours, giving an admission score of 0.514, so the PRD-required rung-43 floor of 0.600 correctly rejected the setup assignment. Raised to 30 counted hours (two 15 h claims) → 0.637. Did not touch the implementation's readiness gate. (4 tests)
- `test_03_calculations.py` `test_monthly_settlement_counts_only_final_accrued_in_period_cases` — the setup reused a perfusionist whose covering call slot had already gone `ACTIVE → COMPLETED` at end-bypass (PRD §3.3), and PRD §3.4 requires a `SCHEDULED`-or-`ACTIVE` covering slot; added a live call window for the second case. (1 test)
- `test_05_endpoints.py` `test_contract_rate_update_applies_forward_only_and_never_reprices_accruals` — the update also moved `prolonged_pump_threshold_minutes` to 120, so the card's 150 `standard_pump_minutes` earns `FLOOR(30/30)+1 = 2` surcharge units and the correct provisional fee is `500000 × 1.30 = 650000`, not `500000`. Corrected the expected fee and ledger to the PRD-derived figures. (1 test)

**Fixes applied to `test_helpers/`:** none — the shared fixtures were PRD-faithful; all fixture defects were in per-test setup builders inside `test_suite/`.

Orchestrator verification of the sweep artifacts (per the known "clean sweep with no artifacts" failure mode): all 8 `workspace/implementation/results.{1..8}.json` exist, each ~28 KB, each parsing to `passed=88 total=88 failed=0`. Mtimes confirm the sweep (02:19) postdates every implementation fix (02:14) and every test fix (02:15), so the green result is from the fixed tree, not a stale pre-fix run.

## Step 8: Finalize PRD — 2026-09-04T02:31:00.000Z

Done. Only one PRD-silence emerged from the Step 7 diff; the four `test_suite/` items were all pure fixture bugs against rules the PRD already fixes verbatim.

## Line counts
- `PRD.md`: 475 lines
- `PRD_FINALIZED.md`: 477 lines
- delta: +2 lines (+0.42%)

## Changes
- **§2.4 (Resource Identity, Timestamps and the Version Counter)** — *insert* — one new paragraph after the `updated_at`/`version` paragraph, pinning that the three-fractional-digit rule covers only `created_at`, `updated_at` and `api_request_timestamp`, and that every other returned instant (the 15 named domain instants, plus the clock capability's echoed `current_utc`) is rendered as ISO 8601 UTC with a trailing `Z`, carrying three fractional digits only when the instant has a non-zero sub-second part and omitting them otherwise — with the round-trip consequence that a field "set to the logical clock" reads back as the instant the clock was set to. — `implementation/envelope.py:34-47` (`iso_instant`), `implementation/serialize.py:4-5,94-95,110,129,153-154,171-176,185,215,228-230`, `implementation/routes_slots.py:85`

## Pre-edit search log

**Edit 1 — §2.4 timestamp rendering**
- (a) **Subject:** how every instant-valued field in a response is formatted, and the boundary between the 3-fraction audit stamps and domain instants.
- (b) **Impl paths enumerated:**
  - `envelope.py` — both formatters (`iso`, `iso_instant`) and `_meta()` (`api_request_timestamp` uses `iso`, i.e. always 3 digits).
  - `grep -rn "iso\|isoformat\|strftime"` across all of `implementation/` to find *every* consumer, not just the Step 7 sites. Result: `serialize.py` (all 17 call sites), `routes_slots.py:85`, and `valid.py:140` (parse side). `serialize._d` is dead code.
  - `serialize.py:15-16` (`_common`) and `serialize.py:144` (`event_log.created_at`) — confirmed both still use the 3-digit `iso_stamp`, so the new sentence must exclude them explicitly (it does).
  - `grep -n "return ok("` over all `routes_*.py` to find non-serializer response bodies: only `routes_slots.py:84` (clock echo — instant-valued, covered) and `routes_master.py:184` (settlement — `period` is a `YYYY-MM` string, no instants). No uncovered instant surface exists.
  - Writers of every one of the 15 domain instants: `routes_devices.py:124`, `routes_packs.py:282,287`, `routes_run.py:48,89,157,221,243` (all `db.now()`), and `V.vdt` at `routes_cases.py:37-38`, `routes_people.py:66-67,111`, `routes_slots.py:28-29` (client-supplied). Nullers: `routes_cases.py:197`, `svc.py:203,222`.
  - `valid.py:129-146` (`parse_dt`) — client instants are normalised to UTC via `astimezone`, so an offset-bearing input does not round-trip byte-for-byte.
  - `svc.py:300-328` (`advance_clock`) — confirmed `db.clock = target` exactly, so the echo genuinely returns the caller's instant.
  - `grep -n "three fractional"` over `PRD.md` — only lines 49 and 86, both already scoped; confirmed pure silence (insert) rather than a mismatch (revise).
- (c) **Wording adjustments made:**
  1. Phrased the trigger as "non-zero **sub-second** part" rather than "non-zero millisecond", because `iso_instant` branches on `microsecond` and truncates via `//1000` — an instant with e.g. 500 us prints `.000Z`, which "non-zero millisecond" would have mis-described.
  2. Added "normalised to UTC" and avoided any byte-for-byte claim for caller-supplied instants, since `parse_dt` converts offsets and truncates sub-millisecond precision.
  3. Replaced an initial "each of which is `null` while unset" with "with `null` returned for any of them that carries no instant", because seven of the fifteen (`issued_on`, `expires_on`, `activity_date`, `window_start/end`, `scheduled_start/end`) are required at creation and are never null in practice.
  4. Named the excluded set explicitly (`created_at`, `updated_at`, `api_request_timestamp`) so the new rule cannot be read as sweeping in `_common()` or `event_log()`.

## Items deliberately **not** patched (PRD already uniquely determines them)
- `credit_hours=30` rejection — §3.2 line 178 ("no greater than 20") + rung 7 `ERR_INVALID_FIELD_VALUE`.
- The 0.514 vs 0.637 admission scores and the 0.600 floor — §2.6 line 108 and §3.2 lines 186/190 give the full formula (0.55*credit + 0.45*experience - fatigue, career target 150, clamp, round-half-up to 3 dp); both figures reproduce exactly.
- The covering slot going `ACTIVE → COMPLETED` at end-bypass, and the assignment requiring a `SCHEDULED`-or-`ACTIVE` covering slot — §3.3 lines 198/266 and §3.4 line 214.
- `FLOOR(30/30)+1 = 2` surcharge units and the `500000 × 1.30` provisional fee — §3.4 line 230 (floor of excess over threshold divided by 30, plus one; single round at the end) plus the forward-only rate-change rule at line 166.

Orchestrator verification: `PRD_FINALIZED.md` exists (117023 bytes vs PRD.md's 115596), 477 vs 475 lines, and `diff` shows a single localised §2.4 insertion — not a byte-identical copy.

## Step 9: Complete PRD — 2026-09-04T03:01:00.000Z (pass 1 of 3 — infra + master + people + slots)

Orchestrator note: Step 9 was deliberately split into three sequential, file-partitioned passes over `implementation/`. A single-agent Step 9 on a 3400-line implementation reliably under-scans and can emit a PRD_COMPLETED.md byte-identical to its input; partitioning by module forces exhaustive coverage of every file. All three passes edit the same `workspace/PRD_COMPLETED.md` in place; only pass 1 does the initial `cp` from PRD_FINALIZED.md.

Pass 1 complete.

**Step 0 confirmed:** `cp PRD_FINALIZED.md → PRD_COMPLETED.md` done before any edit; only `PRD_COMPLETED.md` was written.

**Line/char counts:** PRD_FINALIZED.md 477 lines / 117,023 bytes → PRD_COMPLETED.md 481 lines / 121,070 bytes (+4 lines, all new §5 table rows; +4,047 bytes / +4,027 chars).

**Counts:** 13 ambiguity-pins, 2 mismatch-revisions.

**Changes**
- §2.1 (auth headers) — revise — ambiguity — a header that is whitespace-only now counts as empty for `ERR_MISSING_AUTH_HEADERS` — auth.py:46
- §2.2 (`api_request_id` bullet) — insert — ambiguity — pins `req_` + exactly 20 chars from upper-case letters and digits — envelope.py:8-20
- §2.2 (`api_request_timestamp` bullet) — insert — ambiguity — stamp is read from the logical clock, not wall clock (so `2026-08-01T00:00:00.000Z` before any advance) — envelope.py:53
- §2.3 (ordering) — insert — ambiguity — `created_at` ties (the normal case under a frozen clock) break by ascending insertion order — store.py:87-92
- §2.3 (filters) — insert — ambiguity — filter values compared verbatim as strings, never enum-validated or FK-resolved; unknown params ignored; unmatched value yields an empty page — routes_slots.py:67-70, routes_master.py:322-330, routes_people.py:89-94 (same pattern in all other list routes, so the wording is not broader than impl)
- §2.4 (instant rendering) — insert — ambiguity — caller-supplied instants: non-UTC offsets converted, missing zone read as `Z` — valid.py:137-145
- §2.8 (rungs 6-8) — insert — ambiguity — absent/unparseable body = empty object (rung 6 fires); non-object JSON body fails rung 7 with `ERR_INVALID_FIELD_VALUE`; whitespace-only strings and bool/fractional integers violate rung 7 — valid.py:25-34, 57, 91
- §3.1 (contract update) — insert — ambiguity — an explicitly-null term is applied, not ignored: optional terms revert to default, required terms are stored null — routes_master.py:27-59, 98
- §3.2 (CE claim) — insert — ambiguity — no ownership test on a CE claim; a `Perfusionist` may claim for another holder — routes_people.py:101-103
- §3.2 (credit ledger) — insert — ambiguity — the refresh is unconditional and always advances the holder's `updated_at`/`version` — routes_people.py:79/124/173/184/197 via svc.refresh_ce_ledger
- §3.2 (adjudication) — insert — ambiguity — the optional `note` must be a string but is never persisted or returned — routes_people.py:150
- §3.2 (VERIFIED branch) — insert — ambiguity — banking then promoting writes the certification twice, so its `version` advances by two — routes_people.py:168-179
- §3.10 (settlement period) — revise — mismatch — a non-string/empty `period` is rejected at rung 7 with `ERR_INVALID_FIELD_VALUE`, not `ERR_SETTLEMENT_PERIOD_INVALID`; "well formed" defined as `\d{4}-01..12` — routes_master.py:119-124
- §3.10 (settlement response) — insert — ambiguity — a settlement run mints no resource, so it answers 200, not 201 — routes_master.py:184-196
- §5 (intro + 4 table rows) — revise — mismatch — the table claimed to list every emitted identifier but omitted `ERR_SYSTEMIC_FINDING_UNSUPPORTED` (422), `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405), `ERR_INTERNAL` (500); prose now places them outside the ladder, notes trailing slashes are insignificant, and notes other framework HTTP faults report `ERR_INVALID_REQUEST` under their own status — app.py:26, 37-57, errors.py:87-89

**Slice files scanned (all 10):** app.py, envelope.py, auth.py, valid.py, errors.py, store.py, constants.py, routes_master.py, routes_people.py, routes_slots.py. constants.py needed no edits — every named constant (fatigue weights, readiness floors, coverage horizon/ratios, turnaround 90 min, tier boundaries, all enumerations, specialty matrix, `RESERVATION_HOLDING_STATUSES`/`CONCURRENT_STAFFED_STATUSES`/`LIVE_SLOT_STATUSES`) is already pinned uniquely in §2.6/§3. All §4 role sets and 201/200 statuses for my slice's endpoints already match, and every status in errors.py `_CATALOG` matches the §5 table.

**Deliberately left to passes 2/3:** `svc.advance_clock` internals reached through `POST /_clock/set_current_utc` (cert-lapse and `RELIEF_PENDING` sweep ordering, and §2.5's claim that fatigue counters are "re-derived" when in fact they are derived on read so no perfusionist row is written and no `version` advances — that behavior lives in svc.py/calc.py/serialize.py); `calc.num` numeric rendering (e.g. `readiness_score` 0.000 serialising as `0`); `set_readiness(..., record_variant=False)` leaving `readiness_variant_last` unchanged at case close and ECMO decannulation (routes_cases.py:247, routes_run.py:62/258); and everything owned by routes_cases/packs/devices/run/incidents.

## Step 9: Complete PRD — 2026-09-04T03:01:00.000Z (pass 2 of 3 — cases + packs + devices)

Pass 2 complete.

## Counts

- **PRD_COMPLETED.md before:** 481 lines / 121,070 chars → **after:** 481 lines / 126,805 chars (all edits are in-paragraph; no new sections or paragraphs).
- **Ambiguity pins: 21. Mismatch revisions: 2.**

## Changes

- §3.4 (staffing gates) — revise — **mismatch** — PRD listed employment `ACTIVE` *before* the `CCP` check; impl checks certification first and the §2.8 ladder agrees (41 before 42). Reordered and named `ERR_PERFUSIONIST_NOT_ACTIVE` — routes_cases.py:108-112
- §3.7 (alarm cascade wrap-up) — revise — **mismatch** — "The alarmed machine's `version` advances" implied one write; impl writes it twice (counter, then status) → `version` +2 — routes_devices.py:88-95
- §3.4 (covering-slot requirement) — insert — ambiguity — which qualifying slot is remembered as the case's covering slot (earliest `window_start`, ties by `created_at`) and that re-staffing replaces it — routes_cases.py:118,160
- §3.4 (supersede re-pricing) — insert — ambiguity — withdrawal and re-accrual are netted into one contract write, so an assignment advances the contract's `version` by exactly one — routes_cases.py:144-164
- §3.4 (provisional fee) — insert — ambiguity — assignment does not require an `ACTIVE` card; with no card the provisional fee runs on zero pump minutes (acuity uplift only) — routes_cases.py:152-153 / calc.py:96-97
- §3.5 (pack configuration) — insert — ambiguity — a primary of the wrong class or another hospital raises `ERR_DEVICE_NOT_AVAILABLE`, not `ERR_INVALID_BACKUP_DEVICE` — routes_packs.py:66-69
- §2.8 rung 34 — revise — ambiguity — rung restated to carry the primary's class/hospital condition, fixing its priority above rungs 49 and 55 — routes_packs.py:66-69
- §3.5 (`substitutions`) — insert — ambiguity — `reason` optional/emptyable, the other three keys mandatory; non-object entries, missing keys and duplicate `line_code` are all `ERR_INVALID_FIELD_VALUE` — routes_packs.py:29-43
- §3.5 (pack materialisation) — insert — ambiguity — `substitutions` echoed back verbatim in supplied order, `reason` null when omitted — routes_packs.py:113 / serialize.py:196
- §3.5 (adjudication) — insert — ambiguity — `note` must be a string, may be empty, is never persisted; adjudication writes only the pack — routes_packs.py:162-171
- §3.5 (adjudication) — insert — ambiguity — "the case's pack" means the most recently created pack (ties by insertion order), for the blocking rule, §3.6's code derivation and §3.10's closure gate alike — svc.py:102-107 as called from routes_cases.py:222, routes_packs.py:197,265
- §3.6 (checklist open) — insert — ambiguity — `check_code`/`passed` mandatory inside an entry, `note` optional; non-object entries, missing keys and duplicate `check_code` are `ERR_INVALID_FIELD_VALUE` — routes_packs.py:176-192
- §3.6 (checklist open) — insert — ambiguity — `hematocrit_pct` carries no decimal-place constraint and renders without a fractional part when it has none — routes_packs.py:219 / serialize.py:212
- §3.6 (checklist derivation) — insert — ambiguity — `check_results` echoed as supplied, `note` null when omitted — serialize.py:210
- §3.6 (sign-off) — insert — ambiguity — only the named checklist is written; a sibling `DRAFT` of the same case is left as-is and becomes unusable — routes_packs.py:279-288
- §3.6 (invalidation) — insert — ambiguity — `verified_by_perfusionist_id` is retained when a checklist is invalidated — svc.py:198-204 as triggered by routes_cases.py:205
- §3.6 (cancellation) — insert — ambiguity — `reason` is a string, may be empty, never persisted — routes_cases.py:177
- §3.6 (cancellation) — insert — ambiguity — only a machine that actually moves `RESERVED → AVAILABLE` is written (one staying `RESERVED`, or held in another status, keeps its `version`); `assigned_perfusionist_id` and the covering slot are left alone; the contract is written even with no accrual to withdraw — routes_cases.py:200-211
- §3.7 (event capture) — insert — ambiguity — `detail` may be supplied empty — routes_devices.py:80
- §3.7 (event consequences) — insert — ambiguity — the log row records the supplied `runtime_hours_delta` whatever the code; a machine already `NEEDS_SERVICE` takes the row and the counter but moves nowhere and fires no cascade; `SELF_TEST_PASS` and a `SERVICE_COMPLETED` captured here are inert — routes_devices.py:83-95
- §3.7 (service completion) — insert — ambiguity — the appended `SERVICE_COMPLETED` log carries the acting header value, `runtime_hours_delta` 0 and the request's `detail` (<=400 chars, emptyable); machine `version` +1 — routes_devices.py:117,126
- §3.1 (commissioning) — insert — ambiguity — `asset_tag` is a non-empty string with no length ceiling — routes_devices.py:30
- §3.10 (closure) — insert — ambiguity — the admission-variant recompute at close leaves `readiness_variant_last` untouched; the contract is written even at a zero delta — routes_cases.py:242-247 / svc.py:143-149

## Scope

Scanned exhaustively: `routes_cases.py`, `routes_packs.py`, `routes_devices.py` (every endpoint, role set, field default, validation, error priority, state move, cascade trigger and response shape), reading `svc.py`, `calc.py`, `serialize.py`, `constants.py`, `valid.py`, `store.py` and `routes_run.py` for context only.

Left to pass 3: the internals of `svc.critical_alarm_cascade` (notably that a primary-side case with an accrual is written **twice**, so its `version` advances by two — I deliberately kept the §3.7 wrap-up sentence unquantified for non-alarmed entities rather than assert "+1 apiece"), the unconditional standby `RESERVED → AVAILABLE` flip inside the cascade, all of `routes_run.py` (start/end-bypass, ECMO), `routes_incidents.py`, and the `calc.py` money/posture/readiness formulas.

One correction worth flagging: my first attempt at the §3.7 wrap-up claimed every cascade-reached entity advances by one; I caught and reverted that within the same pass because `svc.py:226`/`:241` touch a primary-side case twice.

## Step 9: Complete PRD — 2026-09-04T03:25:00.000Z (pass 3 of 3 — run + incidents + calc + svc + serialize)

All checks pass. Pass 3 is complete.

## Result

**Size**: `PRD_COMPLETED.md` 481 lines / 126,805 chars → **481 lines / 134,922 chars** (+8,117; every edit was in-paragraph, no new lines or sections). Overall `PRD_FINALIZED.md` → `PRD_COMPLETED.md` delta: 477 lines / 117,023 chars → 481 / 134,922 (+17,899 chars, 110 changed lines).

**Counts**: 24 edits across 20 paragraphs — **19 ambiguity-pins, 5 mismatch-revisions**.

### Changes
- §2.5 — revise — ambiguity — a clock request naming the current reading still runs the full reconciliation pass, so every contract is rewritten — routes_slots.py:81, svc.py:300
- §2.5 — revise — ambiguity — uninterrupted minutes / breach flag are not stored, so a run that does not change status is not written — svc.py:317
- §2.5 — revise — **mismatch** — fatigue counters are derived on read, not "re-derived" into rows: a clock advance writes no perfusionist row, advances no perfusionist `version`, and leaves `readiness_score` stale — svc.py:300-328, serialize.py:82
- §2.6 — insert — ambiguity — JSON rendering of every non-cents quantity: whole values emit as integers (`0.000`→`0`, `12.0`→`12`), fractional values drop trailing zeros (`8.50`→`8.5`) — calc.py:42
- §2.8 rung 15 — revise — **mismatch** — on a handoff the path-borne run resolves before the body's `relief_slot_id`, so both unknown reports `ERR_ECMO_RUN_NOT_FOUND` — routes_run.py:195
- §3.2 — insert — ambiguity — credit ratio reads the stored ledger fields, not a fresh aggregation; no CCP cert or non-positive requirement gives ratio 0 — calc.py:304-311
- §3.2 — insert — ambiguity — `ecmo_hours_rolling_7d` attributes a run to its *current* `primary_perfusionist_id`, so a handoff moves the whole run's hours — calc.py:286-298
- §3.6 — insert — ambiguity — start-bypass machine-status failures raise `ERR_DEVICE_NOT_AVAILABLE`, judged after the fallback-flag check — routes_run.py:41-44
- §3.6 — revise — ambiguity — start-bypass recomputes readiness under **ADMISSION**, leaves `readiness_variant_last` untouched, writes only the score, advances the perfusionist's (and moved slot's) `version` — routes_run.py:62, svc.py:143
- §3.6 — revise — ambiguity — `cross_clamp_minutes` has no field-shape ceiling; over-pump values fall to rung 61, never `ERR_INVALID_FIELD_VALUE` — routes_run.py:73,82
- §3.6 — revise — **mismatch** — end-bypass releases the standby on status alone (count not consulted); other statuses untouched; `SELF_TEST_FAIL` log carries delta 0 and the actor header; the machine is written exactly once either branch — routes_run.py:96-115
- §3.6 — insert — ambiguity — end-bypass writes neither contract nor perfusionist — routes_run.py:88-129
- §3.7 — insert — ambiguity — cascade standby flip is unconditional on reservation count — svc.py:231
- §3.7 — revise — **mismatch** — version accounting: a primary-side case with an accrual is written twice (+2); everything else +1 apiece; an unmoved standby is not written; a contract takes one write per accrual withdrawn; primary-side link completes before the standby-side variant — svc.py:219-251
- §3.8 — insert — ambiguity — nothing prevents a second concurrent run on one case; the parent case is not written — routes_run.py:136-166
- §3.8 — insert — ambiguity — a zero-length run bills 0 hours and 0 cents; no minimum hour — calc.py:150
- §3.8 — revise — ambiguity — decannulation recomputes readiness under **ADMISSION** for the run's current holder, leaves `readiness_variant_last` alone, prices before scoring — routes_run.py:243-258
- §3.9 — insert — ambiguity — filing checks neither case state nor any link between involved perfusionist and case; writes only the report — routes_incidents.py:36-55
- §3.9 — insert — ambiguity — `review_note` <=1000 chars, may be empty, never persisted — routes_incidents.py:101
- §3.9 — insert — ambiguity — acceptance writes the audit score through to the perfusionist's live `readiness_score` / `readiness_variant_last`=`AUDIT`, advancing their `version` — routes_incidents.py:115
- §3.9 — insert — ambiguity — `credit_case_fee` defaults false; `closing_note` <=1000 chars, may be empty, never persisted — routes_incidents.py:132-133
- §3.9 — revise — **mismatch** — revocation is reached from `ACTIVE` as well as `PROBATION`; leaves remediation figures standing; a missing/`LAPSED`/`REVOKED` cycle makes link 2 a no-op — svc.py:263-273
- §3.9 — insert — ambiguity — link 4 recomputes each affected contract exactly once, in first-appearance order — svc.py:284-295
- §3.9 — insert — ambiguity — a credit advances case and contract `version`; a non-applying credit writes neither — routes_incidents.py:167-175

### Handed-off items — resolutions
- **Double-write in `critical_alarm_cascade`**: pinned in §3.7 — accrued primary-side case `version` +2, everything else +1, contract one write per accrual, unmoved standby not written at all.
- **Unconditional standby `RESERVED → AVAILABLE`**: pinned in both §3.7 (cascade) and §3.6 (end-bypass) — status-only, reservation count not consulted.
- **`advance_clock` internals**: §2.5's four families now match — cert lapse then relief sweep then posture, each at the new instant; fatigue counters derived on read with no perfusionist write and no score refresh; runs that don't move aren't written.
- **`calc.num` rendering**: pinned once in §2.6 covering every Decimal-valued field, with the `0.000`→`0` case spelled out.
- **`set_readiness(record_variant=False)`**: `readiness_variant_last` now explicitly unchanged at start-bypass (§3.6) and decannulation (§3.8); §3.10's close wording was already correct, and §3.9 now states the review path is the one place it becomes `AUDIT`.

### Integrity
72 ladder error identifiers in §2.8; 76 rows in the §5 table (= 72 + the 4 the section itself declares outside the ladder) and the identifier set matches `implementation/` exactly, none extra, none missing; 53 unique endpoint paths in the §4 table; file ends cleanly on the `ERR_INTERNAL | 500` row with a trailing newline and balanced backticks. No implementation, test_suite or test_helpers file was modified; no server or test run.

---

## Pipeline complete — orchestrator final verification, 2026-09-04T03:26:00.000Z

- `workspace/PRD_COMPLETED.md` exists: 481 lines / 134,922 bytes. `cmp` against `PRD_FINALIZED.md` confirms it is NOT a byte-identical copy (57 inserted/changed lines, +17,899 chars) — the three-pass scan genuinely ran.
- Independent cross-check against `SCAFFOLD.yaml`: all 72 scaffold error ids present, all 53 scaffold endpoint paths present.
- File ends on a complete `| \`ERR_INTERNAL\` | 500 |` table row — no truncation.
- Final test state (Step 7, verified by the orchestrator from the per-round artifacts, not from the subagent's claim): `workspace/implementation/results.{1..8}.json`, each `passed=88 total=88 failed=0`, all mtimes postdating every source fix.
- Artifact set complete: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, worklog.md, test_helpers/ (9 modules), test_suite/ (12 files, 88 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/}.
