# Worklog — task_2153_residence_life_ra_staffing

## Step 1: Create task directory — 2026-08-25T12:51:00.000Z

Created `tasks/task_2153_residence_life_ra_staffing/` and `tasks/task_2153_residence_life_ra_staffing/workspace/` (next index after task_2152).

## Step 3: Copy shared files — 2026-08-25T12:51:10.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2153_residence_life_ra_staffing/workspace/INSTRUCTION.md`.

## Step 2: Generate scaffold — 2026-08-25T13:40:00.000Z

All three scaffold artifacts are generated and verified.

## Files

| Path | Lines |
|---|---|
| `SCAFFOLD.yaml` | 3243 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2147 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 3598 |

## Scaffold counts (§1.0–§1.7)

- **14 entities** (Building, Floor, Room, Student, RAApplication, RA, DutyShift, IncidentReport, ConductCase, RoomInspection, DamageCharge, RoomChangeCase, ProgramEvent, BreakHousingRequest)
- **14 state machines** — including two entities carrying *parallel* dimensions (RA: `employment_status` × `certification_status`; RoomChangeCase: `mediation_status` × `placement_status`) and four cyclic machines (application revision loop, duty swap loop, mediation impasse loop, damage appeal loop)
- **2 concurrency rules** (OCC on `Room.version` for inspection-create-with-supersede, on `Student.version` for room-change-create-with-supersede)
- **10 calculations**, **33 validations** (13 priority bands), **79 endpoints**, **67 error codes**, **5 roles** (segregation_of_duties model)
- Profile: `workflow_orchestration` × `quota_allocation`, graph topology, parallel state shape, immediate consistency, expert-plus band

## Design indices

- **§1.8 — 18 instances**: exactly 2 per each of the nine §0.5 rules. Key numbers were computed in Python, not estimated (damage: provisional 37000 vs depreciated 25900, fee 2590, relief 5000, final 23490; reimbursement 32109 round-per-line vs 32108 sum-then-round; duty load 5 vs 4; sanction points 5 then 14 → 19 → PROBATION).
- **§1.9 — 59 instances**: 49 active + 10 `excluded_because` stubs, across all nine claim-extraction-guide sections (entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting_complexity_layers, consistency_model).

## Verification

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
Coverage
  §1.5 endpoints declared:    79
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     49
  Calls scanned (§1.8+§1.9):  919

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Additional checks beyond the linter: all three files parse as YAML; zero unbound `${var}` placeholders across 919 calls; all 77 instance names unique across both design files; all `grounds:` refs resolve into §1.1–§1.7 and every `excluded_because.difficulty_instance` resolves to a real §1.8 name; zero occurrences of the forbidden concurrency vocabulary; neither design key appears inside `SCAFFOLD.yaml`.

Note: no sibling task directory was read — the scaffold was derived solely from the scenario text and the skill spec. The scaffold declares a logical clock (`POST /residence-life/_clock/set_current_utc`) with the mandated `2026-08-01T00:00:00Z` startup default, which also doubles as `TERM_START_UTC` so the duty-load windows and damage depreciation year are run-time independent.

## Step 4: Generate PRD — 2026-08-25T13:52:00.000Z

PRD generated and audited.

**Output:** `workspace/PRD.md` — **469 lines**

Structure: §1 Introduction (3 paragraphs) · §2 with 11 domain-derived subsections (§2.2 emitted verbatim from `section-2.2-response-structure.md`) · §3 with 9 workflow subsections · §4 four-column endpoint table · §5 two-column error table. Document ends at §5 with no audit footer.

### Per-section coverage audit

| Scaffold section | Covered / Total |
|---|---|
| §1.1 entities | 14 / 14 |
| §1.2 state machines | 14 / 14 (all 79 transitions) |
| §1.2.1 concurrency rules | 2 / 2 (`expected_room_version` → `ERR_STALE_ROOM_VERSION` 412; `expected_student_version` → `ERR_STALE_STUDENT_VERSION` 412) |
| §1.3 calculations | 10 / 10 |
| §1.4 validations | 33 / 33 (priority ladder rendered as an explicit 14-step ordering in §2.7) |
| §1.5 endpoints | 79 / 79 |
| §1.6 error codes | 67 / 67 |
| §1.7 roles | 5 / 5 |

### Hard contracts
- **Contract 1 (Field-Name Coverage): PASS** — entity fields 130/130, request bodies + computed outputs 93/93, query params 40/40, path params 13/13.
- **Contract 2 (Rule Coverage): PASS** — three gaps found and repaired (`ERR_RA_NOT_ACTIVE` at inspection-scheduling and program-proposal, `ERR_RA_NOT_CERTIFIED`/`ERR_RA_NOT_ACTIVE` at inspection-completion).
- **Contract 3 (§3 Path Purity): PASS** — 1009 backtick tokens scanned in §3; 0 paths, 0 bare HTTP methods.

### Flag raised: eight unbound scaffold constants
`MAX_REVISION_ROUNDS`, `MAX_RETURN_ROUNDS`, `MAX_MEDIATION_ROUNDS`, `CERTIFICATION_CREDIT_MIN`, `MANDATORY_MODULE_CODES`, `MODULE_CREDITS`, `MIN_REST_MINUTES`, `COVERAGE_ALERT_THRESHOLD` are referenced but never bound in `SCAFFOLD.yaml`. The doc-generator bound them in prose.

## Step 4b: Orchestrator constant reconciliation — 2026-08-25T13:58:00.000Z

The orchestrator cross-checked all eight PRD-invented constants against the withheld design indices (§1.8/§1.9), which independently bound some of them inside worked test recipes. Six agreed; two conflicted and were patched in `PRD.md` to match the design indices (design recipes carry precomputed numbers that cannot be re-derived cheaply):

| Constant | Design index | PRD (before) | Action |
|---|---|---|---|
| `MAX_REVISION_ROUNDS` | 2 | 2 | agree |
| `MAX_RETURN_ROUNDS` | 2 | 2 | agree |
| `MAX_MEDIATION_ROUNDS` | 3 | 3 | agree |
| `CERTIFICATION_CREDIT_MIN` | 12 | 12 | agree |
| `MANDATORY_MODULE_CODES` | CRISIS, TITLE_IX, FIRE_SAFETY | same | agree |
| `MIN_REST_MINUTES` | 480 (gap `< 480` refused, `== 480` allowed) | eight hours, same boundary | agree |
| `MODULE_CREDITS` | CRISIS 5, TITLE_IX 4, FIRE_SAFETY 2, MEDIATION 3, DIVERSITY 1, PROGRAMMING 2 (mandatory sum 11; CRISIS+TITLE_IX+MEDIATION+DIVERSITY+PROGRAMMING = 15) | 4/3/3/2/2/2 (sum 10) | **PRD patched to design values** |
| `COVERAGE_ALERT_THRESHOLD` | 2 | 3 | **PRD patched to 2** |

Three edits to `PRD.md` (line count unchanged at 469):
1. §3 training paragraph — module credit catalogue rewritten to 5/4/2/3/1/2.
2. §3 certification paragraph — "three mandatory modules together carry only ten credits" → "eleven credits".
3. §3 separation paragraph — coverage threshold "three or more" → "two or more", and the sentence was generalized so the threshold reads as the floor-wide rule applying wherever `uncovered_shift_count` is recomputed, not only on separation.

## Step 6: Generate implementation — 2026-08-25T14:22:00.000Z

Implementation complete and verified.

## Files written (`workspace/implementation/`, 3210 lines total)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 8 | Guarded `pip install` + `exec python3 app.py`, `0.0.0.0:$PORT` (default 10000) |
| `requirements.txt` | 1 | Flask |
| `app.py` | 60 | Entry point, blueprint registration, error handlers |
| `constants.py` | 117 | All domain constants (module credits, thresholds, rates, caps) |
| `errors.py` | 94 | Error class + **67**-entry HTTP status catalogue |
| `store.py` | 114 | In-memory dicts, logical clock, id/version helpers |
| `derive.py` | 284 | All `source: computed` fields evaluated live at read time |
| `calc.py` | 147 | The 10 calculation rules (Decimal / ROUND_HALF_UP) |
| `serializers.py` | 110 | Entity serialization + the version/`updated_at` bookkeeping pass |
| `validators.py` | 227 | Request-shape validation, lookups, pagination, filters |
| `services.py` | 218 | Gates, the four cascade families, rest-rule + auto-fill selector |
| `auth.py`, `responses.py` | 67, 75 | RBAC/ownership wrapper; envelope + pagination meta |
| `routes/` (9 modules) | 1688 | reads, housing, applications, duty, conduct, damage, roomchange, programs, breaks |

## Coverage
- **Endpoints: 79/79** (31 GET + 48 POST), confirmed by enumerating the Flask url_map.
- **Error codes: 67/67** wired in `errors.ERROR_HTTP` with PRD §5 statuses (note `ERR_CONSOLIDATION_NOT_WARRANTED` = 409 per PRD, which overrides the scaffold's priority-63 grouping).
- 14 entities, all 14 state machines including both parallel-dimension pairs (RA employment × certification, RoomChangeCase mediation × placement), 10 calculations, the 13-band validation ladder from PRD §2.7, and both OCC guards.

## Design notes worth flagging
- **No seeding anywhere** — the store boots empty; every fixture is built through declared endpoints.
- **Version bumping is content-diff driven**: a snapshot is taken before each mutating request and each pre-existing row whose serialized content changed gets exactly one `version`/`updated_at` bump. This implements PRD §2.4's "a resource recomputed to the same numbers is not considered written" and makes every cascade bump the right rows automatically. Two explicit bumps (`POST /room-inspections` → Room, `POST /room-change-cases` → Student) drive the OCC fields.
- **Clock-dependent derived fields** (`Floor.uncovered_shift_count` / `coverage_status`) are computed at serialization time, and the clock endpoint is marked non-mutating — verified that moving the clock changes those readings without bumping any version.

## Boot smoke test
Fresh process on a free port, ready in <2s. Verified end-to-end: full RA hire→train→certify→activate pipeline; duty assignment with the 8-hour rest rule (back-to-back refused, exactly-8h accepted), auto-fill empty-pool, check-in/complete/VOID point reversal to zero; incident→triage ROUTE→hearing→segregation-of-duties→SANCTION with judicial-hold clearing and report bubble-up; damage chain (provisional 37000 → 0.48 depreciation → per-line assessed 19240 → admin 962 → hardship 5000 → final 15202, waive restoring balance to 0); per-line reimbursement rounding (12002, not 12001); break-housing closed-interval capacity (shared boundary date collides); emergency-closure four-link cascade producing `system`-opened `EMERGENCY_RELOCATION` cases and partial restoration on reopen; consolidation waterfall with bed conservation; both 412 stale-view errors; and the ladder orderings (uncertified+inactive → `ERR_RA_NOT_CERTIFIED`, floor mismatch after temporal checks).

One bug found and fixed during testing: the consolidation waterfall read occupants from the live DB rather than the simulation, so a room that received a move and was later processed as a source could be marked `CONSOLIDATED` while still occupied. It now tracks a simulated roster (re-sorted by resident `created_at`), which also makes the "skipped whole" rule behave correctly.

## Step 5: Generate unit tests — 2026-08-25T14:30:00.000Z

Test infrastructure and suite are complete and verified.

## Files written

**`test_helpers/`** (2,719 lines)
| file | lines |
|---|---|
| `__init__.py` | 37 |
| `api_client.py` | 400 (one method per PRD endpoint, all 14 resources + census / programming-summary / duty-load / clock) |
| `api_errors.py` | 148 (69 error ids + HTTP map, registered with the framework) |
| `assertions.py` | 303 (per-entity assertions + budget-partition, coverage, settlement-arithmetic, conduct-standing invariants, timestamp normaliser) |
| `constants.py` | 89 |
| `factories.py` | 152 |
| `fixtures.py` | 1,014 (11 tiers) |
| `test_users.py` | 69 (opaque-role constants + per-instance `make_ra_headers` / `make_student_headers` builders for the two `entity_backed` roles) |
| `types.py` | 507 |

**`test_suite/`** (3,424 lines): `conftest.py` plus 11 domain-named files — `test_01_housing_inventory` (11), `test_02_ra_recruitment_and_training` (9), `test_03_duty_rotation` (14), `test_04_incidents_and_conduct` (7), `test_05_damage_billing` (8), `test_06_room_change_and_mediation` (7), `test_07_floor_programming` (8), `test_08_break_housing_and_closure` (8), `test_09_census_and_consolidation` (5), `test_10_access_control` (4), `test_11_versioning_and_stale_views` (4).

## Coverage

- **Queue A (Difficulty): 36 tests** — all 18 instances across the 9 rules covered by exactly 2 tests each.
- **Queue B (Corner): 49 tests** — all 49 non-stub instances covered by 1 test each. The 10 `excluded_because:` stubs were not translated; all 10 `difficulty_instance` cross-references resolve.
- **Instances skipped: none.** Every non-stub instance passed the PRD-first two-condition filter.
- **Collect-only: 85 tests collected, 0 errors.** `compileall` clean; no skip/xfail anywhere; no scaffold references in generated code.

## Audit results

Automated pass over every test function confirmed: exactly one `Design:` tag per test, every tag resolving to a real instance name, and every quoted PRD citation surviving a literal whitespace-normalised grep of PRD.md (0 misses across 85 tests). The eight reconciled constants are all asserted against PRD prose that now states them.

## Two judgement calls flagged

1. **`Corner/state_machines/taking_a_room_offline_cancels_its_scheduled_inspection`** — the recipe's room is `AVAILABLE`, but PRD §3.1 scopes inspection cancellation to "Going offline from `OCCUPIED`". A resident was placed in the room first so the asserted outcome is PRD-derived.
2. **`setup_duty_load_scenario`** marks the missed shift at `2026-08-21T09:00:00Z` rather than exactly `end_at`, because PRD says `MARK_MISSED` is available once the clock has *passed* `end_at` while `COMPLETE` requires the clock to have *reached* it. Fixture plumbing only; no assertion depends on it.

## Step 7: Run tests and iterate — 2026-08-25T14:36:00.000Z

Clean on the first sweep — no changes were needed.

## Summary

**Iterations run:** 1 (a single 8-round parallel stability sweep).

**Result:** All 8 concurrent rounds returned `passed == total == 85`, `failed == 0`. No test failed in any round, so there was no flakiness signal to chase and no union failure set to triage.

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none.

**Notes on the pre-flagged constants risk:** The orchestrator's warning about stale constants did not materialize — `workspace/implementation/constants.py` already carries the reconciled, PRD-authoritative values:
- `MODULE_CREDITS = {CRISIS:5, TITLE_IX:4, FIRE_SAFETY:2, MEDIATION:3, DIVERSITY:1, PROGRAMMING:2}`
- `COVERAGE_ALERT_THRESHOLD = 2`
- `MAX_REVISION_ROUNDS=2`, `MAX_RETURN_ROUNDS=2`, `MAX_MEDIATION_ROUNDS=3`, `CERTIFICATION_CREDIT_MIN=12`, `MANDATORY_MODULE_CODES={CRISIS,TITLE_IX,FIRE_SAFETY}`, `MIN_REST_MINUTES=480` all agree with both PRD.md and `test_helpers/constants.py`.

(The implementation was generated concurrently with the tests, from the already-patched PRD.md — hence the agreement.)

**Hygiene checks passed:**
- No `skip`/`xfail` anywhere in `test_suite/`.
- No persistence in `implementation/` — no SQLite, shelve, pickle, JSON dump, or `/tmp` cache; storage is in-memory dicts only.

## Step 7b: Orchestrator independent verification — 2026-08-25T14:44:00.000Z

The Step 7 subagent deleted its `results.*.json` artifacts before exiting, and a first-sweep green is exactly the signature a design-index leak would also produce, so the orchestrator re-ran the full 8-round parallel sweep itself and re-audited isolation:

- **Independent sweep: 8/8 rounds at 85/85, failed=0** (680 test executions under `--isolation per-test-server`). `results.{1..8}.json` regenerated and retained.
- **Leak audit:** parsed the Step 4 (PRD) and Step 6 (implementation) subagent transcripts and extracted every `tool_use` input. **Zero tool calls referencing `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml`** from either agent; the only textual mentions are the prohibition sentences in their own prompts. The implementation agent likewise never touched `test_suite/` or `test_helpers/`.

Conclusion: the green first sweep is genuine — the implementation was derived from `PRD.md` alone and still satisfied all 85 design-index-derived tests. Step 8 is therefore **skipped** per its skip condition (0 iterations, 0 deletions, 0 test fixes, 0 implementation fixes). Step 9 still runs.

## Step 8: Finalize PRD — SKIPPED — 2026-08-25T14:45:00.000Z

Skip condition met: Step 7 exited on its first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes and 0 `implementation/` fixes. No `PRD_FINALIZED.md` produced; Step 9 starts from `PRD.md`.

## Step 9: Complete PRD — 2026-08-25T14:55:00.000Z

`PRD_COMPLETED.md` is a minimal in-paragraph patch over `PRD.md`, aligned to `implementation/`.

**Counts** — source 469 lines / 99,691 chars → completed 469 lines / 104,429 chars (+4,738 chars, 34 lines touched, no new sections, all of §1–§5 intact). 41 edits: **29 ambiguity-pins**, **12 mismatch-revisions**.

**Changes**

- §2.1 — insert — ambiguity — caller whose `X-User-ID` names no `RA` row on self-identifying actions gets `ERR_RA_NOT_FOUND`; null owning FK skips the ownership check — services.py:194-198, auth.py:57-61
- §2.2 — insert — ambiguity — optional `reason`/`note` validated as non-empty string but persisted only where §3 names a storage field — routes/conduct.py:81, routes/damage.py:370, routes/roomchange.py:127
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` is `ERR_INVALID_REQUEST`; empty-string param treated as absent — validators.py:182-197
- §2.4 — insert — ambiguity — `created_at`/`updated_at` stamped from the wall clock, not the logical clock — store.py:82,97
- §2.6 — revise — mismatch — `from_room_id` added to the body-reference resolution list — routes/roomchange.py:31
- §2.8 — insert — ambiguity — opening a room-change case advances the student's own `version` — routes/roomchange.py:59
- §3.1 — revise — mismatch — director-driven offline also fires from `AVAILABLE`, stamps `EMERGENCY_CLOSURE`, and opens the relocation case + `RELOCATION_PENDING` — services.py:236-252, routes/housing.py:410
- §3.1 — insert — ambiguity — offline from `OFFLINE`/`CONSOLIDATED` is `ERR_ROOM_NOT_AVAILABLE` — routes/housing.py:407-409
- §3.1 — insert — ambiguity — return-to-`AVAILABLE` codes: `ERR_ROOM_NOT_AVAILABLE` / `ERR_ROOM_AT_CAPACITY` — routes/housing.py:412-415
- §3.1 — insert — ambiguity — `amount_cents` is a required integer ≥ 0, `term_code` required and stored nowhere — routes/housing.py:368-370
- §3.1 — insert — ambiguity — `PLACE` over an existing assignment relocates and re-syncs the vacated room — routes/housing.py:458-463
- §3.1 — insert — ambiguity — `VACATE` of an unhoused resident is accepted as a no-op — routes/housing.py:465-469
- §3.2 — insert — ambiguity — empty effective `essay_ref` is `ERR_INVALID_REQUEST` — routes/applications.py:60-61
- §3.2 — insert — ambiguity — `OFFER` without a score is `ERR_APPLICATION_STATE_INVALID` — routes/applications.py:97-98
- §3.3 — insert — ambiguity — floor assignment accepted at any standing and repeatable — routes/applications.py:133-143
- §3.3 — insert — ambiguity — `ACTIVATE` with null floor is `ERR_RA_STATE_INVALID` — routes/applications.py:196-198
- §3.4 — revise — mismatch — swap `REQUEST` also applies the rest-rule and floor-coherence gates, RA-role only — routes/duty.py:322-339
- §3.4 — insert — ambiguity — `APPROVE`/`WITHDRAW` are director-only; wrong half is `ERR_FORBIDDEN_ROLE` — routes/duty.py:323-326
- §3.4 — revise — mismatch — `MARK_MISSED` allowed at `end_at`, not strictly past it — routes/duty.py:392
- §3.4 — insert — ambiguity — `VOID` reads no clock window — routes/duty.py:395-398
- §3.5 — insert — ambiguity — `room_id` resolved before `subject_student_id` — routes/conduct.py:30-35
- §3.5 — revise — mismatch — ten-character rule applies to the effective narrative and precedes the state check, as `ERR_INVALID_REQUEST` — routes/conduct.py:62-67
- §3.5 — insert — ambiguity — a dismissed case keeps `prior_sanctioned_count` at zero — routes/conduct.py:148-151
- §3.6 — insert — ambiguity — `scheduled_for` is not compared to the clock — routes/damage.py:193
- §3.6 — insert — ambiguity — charge still created with null `student_id` when there is no sole occupant; resolved id written back to the inspection — routes/damage.py:254-277
- §3.6 — insert — ambiguity — `adjusted_subtotal_cents` bound breach is `ERR_INVALID_REQUEST` — routes/damage.py:343-351
- §3.7 — revise — mismatch — a roommate on a non-conflict origin is stored, not refused — routes/roomchange.py:27,51
- §3.7 — revise — mismatch — all prior `REQUESTED` cases are cancelled; `superseded_case_id` names the most recent — routes/roomchange.py:41-44
- §3.7 — insert — ambiguity — non-future `session_at` is `ERR_MEDIATION_STATE_INVALID`, after state and round cap — routes/roomchange.py:78-83
- §3.7 — insert — ambiguity — the mediation read precedes the room/standing/origin checks on a placement request — routes/roomchange.py:105-115
- §3.7 — insert — ambiguity — revert codes (`ERR_ROOM_NOT_AVAILABLE`/`ERR_ROOM_AT_CAPACITY`); `OFFLINE` origin and non-`OPEN` hall do not block — routes/roomchange.py:185-188
- §3.7 — insert — ambiguity — revert sets `housing_status` to `ASSIGNED` — routes/roomchange.py:193
- §3.8 — insert — ambiguity — frozen floor refuses approval with `ERR_BUILDING_NOT_OPEN` — routes/programs.py:267-268
- §3.8 — insert — ambiguity — early `HOLD` is `ERR_PROGRAM_STATE_INVALID` — routes/programs.py:289-290
- §3.8 — insert — ambiguity — receipt lines carry a required non-negative integer `amount_cents` — routes/programs.py:312
- §3.8 — insert — ambiguity — overrun measured against availability *before* the encumbrance is released — routes/programs.py:321, derive.py:96-100
- §3.9 — revise — mismatch — 45-day limit is the date difference (45 accepted, 46 not) — routes/breaks.py:359
- §3.9 — revise — mismatch — approval gates run posture first, then `break_housing_enabled` — routes/breaks.py:397-399
- §3.9 — revise — mismatch — `CLOSE` also requires an `OPEN` hall; both occupancy window failures are `ERR_BREAK_REQUEST_STATE_INVALID` — routes/breaks.py:423-435
- §3.9 — insert — ambiguity — missing closure `reason` is `ERR_INVALID_REQUEST` — routes/housing.py:229-230
- §3.9 — revise — mismatch — consolidation `EXECUTE` also sets each moved resident's `housing_status` to `ASSIGNED` — routes/housing.py:319-320

Notable non-changes (impl already matched PRD): the §2.7 evaluation ladder holds throughout (assignment reports `ERR_RA_NOT_CERTIFIED` before `ERR_RA_NOT_ACTIVE`, floor coherence last); per-line rounding in depreciation, settlement and reimbursement; the compensating actions (waive, cancel, revert, `VOID` from `COMPLETED`) all fall out of read-time derivation, so balances return exactly.

## Pipeline complete — 2026-08-25T14:56:00.000Z

Final state: 85 tests, 8/8 rounds green under `--isolation per-test-server` (680 executions), `results.{1..8}.json` retained. Artifacts: SCAFFOLD.yaml + both design indices, workspace/{PRD.md, PRD_COMPLETED.md, INSTRUCTION.md, implementation/}, test_helpers/, test_suite/. Step 8 skipped by its skip condition.
