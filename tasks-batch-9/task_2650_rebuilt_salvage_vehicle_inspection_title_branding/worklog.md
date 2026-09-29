# Worklog — task_2650_rebuilt_salvage_vehicle_inspection_title_branding

## Step 1: Create task directory — 2026-09-04T01:07:38.983Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2650_rebuilt_salvage_vehicle_inspection_title_branding` and its `workspace/` subdirectory. Index 2650 was pre-assigned by the invoking command; no scan of ./tasks/ was performed.

## Step 2: Scaffold generation — 2026-09-04T02:30:00Z

Generated the three scaffold artifacts from the scenario description plus `skills/prd-bench-scaffold-generator/SKILL.md` alone; no sibling task under `tasks/` was inspected.

- `SCAFFOLD.yaml` (3188 lines) — §1.0–§1.7: 14 entities, 8 state machines, 2 §1.2.1 OCC rules, 8 calculations, 43 ordered validations, 57 endpoints, 55 error codes, 7 roles. Contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1945 lines) — 9 rule groups x 2 instances = 18.
- `SCAFFOLD_CORNER_DESIGN.yaml` (4011 lines) — 9 sections, 78 instances (62 with `test_recipe`, 16 `excluded_because` stubs).

`scaffold_lint.py`: `VERDICT: clean lint` (876 calls scanned across §1.8+§1.9).

### Step 2 — subagent summary (verbatim, orchestrator-recorded)

Scaffold generation for task 2650 is complete and lints clean.

**Files written** (all under `tasks/task_2650_rebuilt_salvage_vehicle_inspection_title_branding/`):
`SCAFFOLD.yaml` 3188 lines / 143797 bytes; `SCAFFOLD_DIFFICULTY_DESIGN.yaml` 1945 lines / 124638 bytes; `SCAFFOLD_CORNER_DESIGN.yaml` 4011 lines / 257745 bytes.

**SCAFFOLD.yaml counts (§1.0–§1.7):** 14 entities, 8 state machines, 2 §1.2.1 OCC concurrency rules, 8 calculations, 43 ordered validation rules, 57 endpoints, 55 error codes, 7 roles. Top-level keys are `scenario, domain_name, api_prefix, response_envelope, complexity_profile, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` — neither `scaffold_difficulty_design` nor `scaffold_corner_design` is present. The other two files each have exactly one top-level key, as required.

**§1.8:** 9 rule groups x 2 instances = **18 instances**.

**§1.9:** **9 sections / 78 instances** (62 with a full `test_recipe`, 16 `excluded_because` stubs, all citing difficulty instances that exist by name): entities 12, state_machines 10, calculations 10, validations 14, endpoints 7, errors 10, rbac 6, cross_cutting_complexity_layers 7, consistency_model 2. Names are unique across the union of both design files (0 duplicates); no stub carries a `test_recipe`.

**Lint verdict (verbatim, final run):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2650_rebuilt_salvage_vehicle_inspection_title_branding/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2650_rebuilt_salvage_vehicle_inspection_title_branding/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2650_rebuilt_salvage_vehicle_inspection_title_branding/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    57
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     62
  Calls scanned (§1.8+§1.9):  876

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Notes worth relaying: (1) closing the final two §1.9 sections required one SCAFFOLD.yaml fix earlier in the run — `GET /v1/findings/{id}` had no 404 code, so `ERR_FINDING_NOT_FOUND` was added to §1.6 and spliced into the priority-30 error chain (hence 55 codes). (2) A forbidden-vocabulary sweep caught two stray uses of "simultaneously" (one in each design file) which were reworded; all three files now pass the banned-phrase check and parse under `yaml.safe_load`. (3) The hard constraint was honored — no sibling task directory was listed, read, or grepped. (4) The `cross_cutting_complexity_layers` section carries one OCC instance per §1.2.1 rule (`schedule-inspection-stale-application` -> 412 `ERR_STALE_APPLICATION_VERSION`, `recognition-request-stale-title` -> 412 `ERR_STALE_TITLE_VERSION`); `consistency_model` is `immediate` and asserts the escrow ledger closing (492500 + 7500 == 500000) within the same request.

## Step 3: Copy shared files — 2026-09-04T02:32:19.978Z

Copied `./INSTRUCTION.md` -> `tasks/task_2650_rebuilt_salvage_vehicle_inspection_title_branding/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T02:49:00.000Z

Orchestrator truncation check: `wc -l` = 434 lines; `tail -25` ends on the final §5 error-table row `| \`ERR_RECORDKEEPING_SCORE_BLOCKS_ACTION\` | 422 |` — a real section boundary, not mid-sentence. No regeneration needed.

Subagent summary (verbatim):

PRD generation for task_2650 is complete and verified.

**Output:** `workspace/PRD.md` — 435 lines, ~13,700 words, ends at the final `## 5` table row (`| \`ERR_RECORDKEEPING_SCORE_BLOCKS_ACTION\` | 422 |`), no audit footer. Written incrementally (1 Write + 7 heredoc appends), so no truncation.

**Section list**
- 1. Introduction
- 2. Global Specifications & System-Wide Principles — 2.1 Program Participants and RBAC; 2.2 API Response Structure (verbatim fixed block); 2.3 Pagination and List Ordering; 2.4 Common Resource Properties and the Logical Clock; 2.5 Validation Precedence; 2.6 The Brand Severity Ladder; 2.7 The Two Independent Dimensions of a Title Row; 2.8 Optimistic Concurrency on Applications and Titles; 2.9 Fraud Holds as a Program-Wide Gate; 2.10 Segregation of Duties; 2.11 Precision, Rounding and the Money Discipline; 2.12 Cascades, Counters and Derived Fields
- 3. Business Logic & Workflows — 3.1 Standing Up the Program Registry; 3.2 The Carrier's Total-Loss Evaluation and the Brand It Triggers; 3.3 Issuing, Superseding and Surrendering Title Instruments; 3.4 Opening an Application and Assembling the Parts Record; 3.5 Verifying Parts Evidence, Completeness and Record-Keeping Quality; 3.6 Submission, Fee Assessment and the Escrow Ledger; 3.7 Documentation Review, Scheduling and Inspection Capacity; 3.8 Conducting the Attempt: Findings, Adequacy Scoring and Identity Verification; 3.9 Failure, Appeal and Final Denial; 3.10 Issuing the Rebuilt Title, and Walking Away; 3.11 Conveyances, Brand Carry-Forward, Odometer Continuity and Interstate Recognition; 3.12 Fraud Referrals, the Substantiation Cascade and Licence Standing
- 4. Endpoint Definitions (4 columns: Method, Path, Description, Authorized Role(s))
- 5. Error Code Catalogue (2 columns: Error ID, HTTP Status Code)

**Coverage, machine-checked against SCAFFOLD.yaml**
- Entities 14/14; entity fields 159/159 present verbatim in backticks (0 missing)
- Endpoints 57/57 in the §4 table, with exact path, method and role-set match for every row (0 role mismatches, 0 extras, 0 omissions)
- Endpoint request/query/path identifiers 160/160 present verbatim
- Errors 55/55 in the §5 table with exact HTTP status match (0 mismatches)
- State machines 8/8, 50 transitions, all 37 distinct states present verbatim
- Calculations 8/8 documented step-for-step with pinned rounding/evaluation order and all constants (verified 0.015 per-line-then-sum, 12,500 / 45,000 cap-after-sum, 7,500 base, 4,000 re-inspection, expedite 10%/7%/5% keyed on subtotal, 5% volume discount at >=5 titles, adequacy weights 35/20/20/15/10 with 70.00 inclusive threshold)
- Validations 43/43 folded into the §2.5 precedence ladder plus the §3 narratives; 2 concurrency rules with both OCC fields (`expected_application_version`, `expected_title_version`) and 412s; 7/7 roles

**Hard Contracts:** Contract 1 field-name coverage PASS (0 missing of 159 fields + 160 request identifiers); Contract 2 rule coverage PASS (all transitions, side effects, cascades, `applies_to` scopes and sibling-branch symmetry narrated — including the stolen-component cascade, the substantiation void cascade, and the three escrow dispositions); Contract 3 §3 path purity PASS (0 backtick tokens in §3 that start with `/`, are a bare HTTP method, or combine method+path).

Notes: no fuzzy/approximating language remains (the six `about` hits are ordinary prepositions); §3 uses 12 subsections rather than the suggested 5–9 because 57 endpoints at expert_plus could not be covered losslessly in fewer. Two scaffold inconsistencies were resolved conservatively — validation priorities 83/84 vs 85/86 for the interval/capacity checks (expressed as prose ordering, not numbers), and `ERR_DONOR_TITLE_NOT_TRACEABLE` covering `USED_DONOR` at creation but `USED_DONOR` plus `RECYCLER` at verification. The two withheld design YAMLs were never opened, grepped, or referenced, and no sibling task directory was read.

## Step 6: Generate implementation — 2026-09-04T03:27:00.000Z

(Steps 5 and 6 were launched concurrently in a single orchestrator message, so the impl generator started before `test_suite/` existed on disk — physical isolation from the tests.)

Subagent summary (verbatim):

Implementation for task 2650 is complete and verified.

## Files (all under `workspace/implementation/`)

`app.py` 79; `db.py` 126; `errors.py` 91; `middleware.py` 210; `response.py` 47; `routes/__init__.py` 0; `routes/reads.py` 344; `routes/registry.py` 301; `routes/titles.py` 368; `routes/applications.py` 558; `routes/inspections.py` 506; `routes/appeals.py` 170; `routes/fraud.py` 129; `routes/clock.py` 22; `services/__init__.py` 0; `services/calc.py` 275; `services/derive.py` 608; `services/cascades.py` 162; `requirements.txt` 1 (`flask>=2.2`); `start.sh` 8 (executable, installs flask only when missing, `exec python3 app.py`).

Total 4,005 lines. No SQLite/JSON/tmp artifacts; storage is plain dicts in `db.Store` with `INITIAL_CLOCK = 2026-08-01T00:00:00Z` and zero seeding.

## Endpoints
57 implemented vs 57 declared — 25 GET, 32 POST, path-for-path identical to PRD §4 (note there is no declared `GET /v1/vehicles` collection, only `GET /v1/vehicles/{id}`, so a collection GET correctly yields 405).

## Verification
- `python3 -m py_compile` on all 18 modules -> `COMPILE_OK`.
- Boot on a random high port from a fresh process -> Flask bound and served in under 3s; repeated a second cold boot on another port to confirm per-test-server relaunch works.
- End-to-end smoke run (39 assertions, all passing) drove the full happy path plus negatives: clock set -> vehicle -> rebuilder + deposit -> inspector -> station -> damage report (`damage_ratio` 0.8, `recommended_brand_code` SALVAGE) -> salvage title (`brand_history` `["SALVAGE"]`, `is_current`) -> application -> 3 parts invoices + 4 photo views -> verifications -> fee-quote -> submit (`assessed_fee_cents` 20187 = 7500 base + 12500 structural + 187 per-line donor surcharge on 12,499c, matching the pinned rounding) -> docs OPEN/ACCEPT -> schedule with OCC -> start -> complete (`adequacy_score` 100.0, PASS) -> `issue-rebuilt-title` (REBUILT, `brand_history` `["REBUILT","SALVAGE"]`) -> conveyance with `odometer_flag` ROLLBACK_SUSPECTED, `carried_brand_code` REBUILT and the auto-cascade referral -> investigate -> resolve SUBSTANTIATED -> vehicle `fraud_hold` CONFIRMED with titles voided. Negatives confirmed: 412 `ERR_STALE_APPLICATION_VERSION`, 401 `ERR_UNAUTHENTICATED` on an unknown role, 403 `ERR_ROLE_NOT_PERMITTED`, 400 `ERR_INVALID_REQUEST` on `limit=0`, 404 `ERR_APPLICATION_NOT_FOUND`.
- Both smoke servers killed by their own PID/port only (16961, 17431 — both confirmed released). No broad `pkill` was used.

Spec detail worth flagging: `fee-quote` returns `assessed_fee_cents` 7500 while the application is still `DRAFT` even after documents are verified. That is intentional — PRD §3.5 says verification recomputes `assessed_fee_cents` only "once the application has been submitted" — and the GET path recomputes with `touch_row=False` so it never bumps `version`.

## Step 5: Generate unit tests — 2026-09-04T03:44:00.000Z

Subagent summary (verbatim):

Stage 1 and Stage 2 are complete and audited.

## Deliverables

**`test_helpers/` (task root, 9 files, 2,897 lines)** — `__init__.py` 59, `api_client.py` 268 (57 endpoint methods), `api_errors.py` 144 (55 error ids + `set_error_http_status_map`), `assertions.py` 414 (14 per-entity + 6 invariant checkers), `constants.py` 115, `factories.py` 383, `fixtures.py` 849 (primitives + 15 composite scenario builders across 5 tiers), `test_users.py` 122, `types.py` 543.

**`test_suite/` (task root, conftest + 17 files, 7,374 lines)** — `conftest.py` 107 (session client, per-role header fixtures, autouse logical-clock reset), then `test_01`...`test_18` (no `test_12`; that section folded into `test_11`).

## Tests emitted: 150 test functions (~170 collected cases with parametrization)

- **Queue A (Difficulty)** — 57 tests over all 18 instances, files `test_01`-`test_09`. Every instance has >=2 tests (min 2, max 5).
- **Queue B (Corner)** — 93 tests over all 62 non-stub instances, files `test_10`, `test_11`, `test_13`-`test_18`. Every non-stub instance has >=1 test.

## Instances skipped: 0

No instance failed the PRD-first filter. The 16 `excluded_because:` stubs were correctly not translated, and all 16 `difficulty_instance` cross-references resolve to real names in the difficulty index (no broken pointers).

Sub-generators did apply PRD-over-recipe corrections rather than skipping — worth relaying to whoever reviews the design docs, since several are latent yaml bugs:
- Recipes pass `certifications: ["STRUCTURAL","VIN"]`, `source_type: "SALVAGE_YARD"`, `grounds: "STRUCTURAL_FINDING_DISPUTED"`, `decision: "GRANTED"`, `recognition_state: "NOT_REQUESTED"` — none are legal PRD enum members.
- Several recipes assert `assessed_fee_cents` on a **DRAFT** application; the PRD recomputes it only once submitted, so those triggers moved to `POST /submit`.
- Recipes assert `outcome == DOWNGRADED` for `mapped_brand_code: "NONE"`; the PRD says `outcome` is `REJECTED` while the *title's* `recognition_state` becomes `DOWNGRADED`. Tests assert the PRD's split.
- A handful of individual assertions were dropped on two-reader grounds (nullability of `vin_verified`/`adequacy_score` after a refused completion; `last_license_action_by_user_id` after a system-driven cascade; the unnamed recognition-list filter parameter).

## Audit results (both mandatory final passes)

- **Design-tag pass:** 150/150 tests carry exactly one `Design:` line as the last docstring line; 0 dangling, 0 dual-tagged, 0 tagging a stub. Found and fixed 2 truncated tags in `test_14`; coverage shortfall is now 0.
- **PRD-citation pass:** every docstring carries a `PRD: "..."` citation, and all 150 survive a literal whitespace-normalized substring check against `workspace/PRD.md`. No `pytest.mark.skip`/`skipif`/`xfail` anywhere. No scaffold-vocabulary leakage.
- **`python3 -m py_compile` on all 26 generated `.py` files: OK.** Every test module imports cleanly against the frozen helper layer (no missing names, no duplicate test function names). pytest was not run — no server existed yet.
- **Layout:** `test_helpers/` and `test_suite/` are at the task root; `ls -la workspace/` shows only `INSTRUCTION.md`, `PRD.md`, `implementation/` — no stray `test_helpers/` or `test_suite/` under `workspace/`. Nothing under `workspace/implementation/` was read or modified.

## Step 7: Run tests and iterate — 2026-09-04T03:58:41.000Z

Orchestrator verification of the claimed sweep (per known failure mode where a Step 7 agent reports a clean sweep with no artifacts behind it): all 8 `workspace/implementation/results.$i.json` exist, each reporting `passed=185 total=185 failed=0`. Their mtimes (03:54:27) postdate the two edited test files (03:46:50 and 03:48:01), confirming the clean sweep ran *after* the fixes rather than being a stale pre-fix artifact.

Subagent summary (verbatim):

Clean exit: 2 iterations, all 8 parallel rounds now at 185/185.

## Summary

**Iterations run:** 2

**Iteration 1 diagnosis (9 failures, identical in all 8 rounds — fully deterministic, no flakiness):**
- 8 tests died with `KeyError: 'data'`
- 1 test failed on a `last_odometer_miles` assertion

**Tests deleted:** none. All 9 failures traced to verbatim-PRD-covered, uniquely-derivable rules; both were test-layer defects under STEP 2.

**Fixes applied to `test_suite/`:**
- `test_suite/test_04_application_lifecycle_loops.py` (lines 65, 138, 173, 227), `test_suite/test_05_fraud_cascades.py` (lines 89, 260), `test_suite/test_06_ledger_compensation.py` (lines 91, 238) — removed a double envelope unwrap. `prd_bench_local_runner.testing.validate_success()` already returns `body["data"]`; these 8 call sites then indexed the returned resource dict again with `["data"]`, raising `KeyError: 'data'` before any assertion ran. Purely a harness mis-call; every assertion in these tests is unchanged. (The sibling tests in the same files that go through the `test_helpers` wrappers — e.g. `review_documentation`, `submit_recognition_request` — were always passing, which localised the bug precisely.)
- `test_suite/test_13_derived_quantity_corners.py::test_conveyance_carries_the_most_severe_brand_on_the_chain` — changed the conveyance's `transfer_effective_at` from `2026-08-05T00:00:00Z` to `2026-08-01T00:00:00Z`. PRD §2.12 states `last_odometer_miles` is "the highest `odometer_reading_miles` among the vehicle's damage reports and among its `RECORDED` conveyances **whose effective instant is at or before the logical clock**". The logical clock sits at its documented initial reading `2026-08-01T00:00:00Z` for this test (autouse `reset_clock`), so a conveyance dated 2026-08-05 is a future event that the PRD-faithful implementation correctly excludes — hence 68000 rather than the asserted 68500. Dating the conveyance at the clock instant satisfies the PRD inclusion precondition and is still legal (§3.11 requires `transfer_effective_at` to be at or after the outgoing title's `issued_at`, which is that same instant). The assertion itself (68500) was kept intact.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none — no implementation defect was found. `services/derive.py` already applies the inclusive `<= db.now()` clock filter the PRD specifies.

### Orchestrator adjudication on the Step 8 skip condition

The skip condition requires 0 deletions AND 0 `test_suite/` fixes AND 0 `test_helpers/` fixes AND 0 `implementation/` fixes. Step 7 applied 2 `test_suite/` fixes, so the condition is not met and Step 8 runs. Both fixes are arguably pure test-layer defects (a harness envelope mis-call and a fixture timestamp that violated a PRD inclusion precondition) rather than PRD silences, so Step 8 may legitimately conclude that no PRD edit is warranted; it must still emit `PRD_FINALIZED.md`. Running it is the safe choice — the `last_odometer_miles` clock-window item in particular is exactly the kind of site where PRD wording may under-determine what the implementation pinned.

## Step 8: Finalize PRD — 2026-09-04T04:04:00.000Z

Subagent summary (verbatim):

Done. One surgical edit; PRD.md and PRD_FINALIZED.md are both 434 lines (0.0% line delta; single sentence rewritten in §2.12).

## Changes

- **§2.12 (Cascades, Counters and Derived Fields), line 160 — revise** — Disambiguated the scope of the logical-clock filter on `last_odometer_miles`: damage reports contribute unconditionally (whatever their `report_effective_at`), while only `RECORDED` conveyances are filtered by `transfer_effective_at <= clock`. — `implementation/services/derive.py:147-151`

## Per-edit pre-edit search log

**Edit 1 — subject: `last_odometer_miles` derivation and the clock filter's scope.**

(b) Paths enumerated (grep for `last_odometer|_effective|odometer_at_issue|odometer_reading_miles` across `implementation/`, then read):
- `services/derive.py:131-163` `recompute_vehicle` — the sole writer. Damage reports of the vehicle are collected with **no** clock predicate (line 147); conveyances are added only when `status == "RECORDED" and transfer["_effective"] <= db.now()` (line 149, inclusive). `max(readings)` or `None`.
- `services/derive.py:326-344` `vehicle_out` — recomputes on every read, so the value re-derives after a clock move (consistent with §2.4, unchanged).
- `routes/registry.py:35-47` — vehicle registration seeds `last_odometer_miles: None`.
- `routes/registry.py:256-291` — damage-report creation stores `_effective` from `report_effective_at`; no constraint that it be at or before the clock, so a future-dated report is reachable and *does* count — the fact that makes the distributed reading of the old sentence behaviorally different.
- `routes/titles.py:98-117` (title issuance without a source report -> `odometer_at_issue_miles = vehicle["last_odometer_miles"]`) and `routes/applications.py:512-519` (rebuilt-title issuance, same source) — both consumers, unaffected by the wording.
- `routes/titles.py:212-220` + `services/calc.odometer_flag` — the *separate* §3.11 replay for `odometer_flag`, which cuts off at the new conveyance's `transfer_effective_at` rather than at the clock. Checked specifically so the new wording could not be mistaken for a change to that rule.
- All 24 `recompute_vehicle` callsites go through the same function, so there is no parallel/divergent derivation.

(c) Wording adjustment: scoped the clarification tightly to the two clauses of this one derived field — named `transfer_effective_at` for the conveyance side and added "the clock filter binding on the conveyances alone" — deliberately avoiding any general statement about clock filtering or about odometer events, so §3.11's `odometer_flag` replay (which filters against the conveyance's own effective instant, not the clock, and likewise includes all damage reports) remains untouched and consistent.

## Items with no PRD edit

- The 8 `KeyError: 'data'` failures (`test_04`, `test_05`, `test_06`) were pure test-layer harness mis-calls — the call sites re-indexed `["data"]` on a dict `validate_success()` had already unwrapped. The envelope shape in §2.2 is already exact and the implementation matches it, so this reveals no PRD silence or mismatch. No edit made.

## Step 9: Complete PRD — 2026-09-04T04:30:00.000Z

### Orchestrator decision: three sequential file-partitioned passes

Run as three sequential passes partitioned by implementation file rather than one monolithic scan. Rationale: a single agent asked to hold ~4,000 lines of implementation plus a 434-line PRD has historically produced a `PRD_COMPLETED.md` byte-identical to its input — i.e. the scan silently never ran. Partitioning keeps each pass's working set small enough to actually walk the code. The orchestrator seeded `PRD_COMPLETED.md` itself (`cp PRD_FINALIZED.md PRD_COMPLETED.md`) so no pass could re-copy and clobber its predecessor's edits; each pass was told which files were already covered and handed forward the out-of-partition observations its predecessor had flagged.

Partition: pass 1 = app.py, db.py, errors.py, response.py, middleware.py, routes/clock.py, routes/registry.py, routes/titles.py. Pass 2 = routes/applications.py, routes/inspections.py, services/calc.py. Pass 3 = routes/appeals.py, routes/fraud.py, routes/reads.py, services/derive.py, services/cascades.py.

### Orchestrator verification

- `PRD_COMPLETED.md` is NOT byte-identical to `PRD_FINALIZED.md` (`cmp` differs; 51 lines changed) — the scan demonstrably ran.
- 434 lines / 101,734 chars -> 434 lines / 117,005 chars (+15,271 chars, +15.0%). Line count unchanged because every pass used in-paragraph inserts/revisions and added no sections, exactly as instructed.
- `tail` ends on the final §5 error-table row `| \`ERR_RECORDKEEPING_SCORE_BLOCKS_ACTION\` | 422 |` — a real section boundary, not truncated.
- Total findings: 59 (39 ambiguity-pins, 20 mismatch-revisions) across the three passes.
- No `.py` file under `implementation/`, `test_suite/` or `test_helpers/` is newer than `results.1.json`, so the clean 8x185/185 Step 7 sweep still describes the shipped code — Step 9 touched only PRD_COMPLETED.md.
- No stray `test_helpers/`/`test_suite/` under `workspace/`; the only `worklog.md` in the tree is this one at the task root.

### Pass 1 summary (verbatim)

Pass 1 complete. `PRD_COMPLETED.md` 434 lines before -> 434 after; 101,734 -> 106,399 chars (+4,665). 18 lines changed (21 surgical Edit calls). **ambiguity-pins: 13, mismatch-revisions: 5.**

- §1 (intro P3) — insert — ambiguity — all state lives in process memory and every collection starts empty on each boot, nothing seeded — `app.py:1-5`, `db.py:37-41`
- §2.1 — revise — ambiguity — a whitespace-only `X-User-ID`/`X-User-Role` counts as empty for `ERR_UNAUTHENTICATED` — `middleware.py:23-26`
- §2.2 (`api_request_id`) — insert — ambiguity — `req_` plus exactly twenty characters from uppercase A-Z and 0-9 — `response.py:15`
- §2.2 (`api_request_timestamp`) — insert — mismatch — the envelope timestamp is the sole instant taken from real wall-clock time, not the logical clock — `response.py:18-23`
- §2.3 P1 — insert — ambiguity — a non-integer `limit`/`offset` is `ERR_INVALID_REQUEST`; an empty string falls back to its default — `middleware.py:175-190`
- §2.3 P2 — revise — ambiguity — `has_more` is true exactly when `offset` + rows returned < `total_count` — `response.py:36`
- §2.3 P3 — insert — ambiguity — empty-string filters and undeclared query params are ignored; `is_current` accepts `true`/`false`/`1`/`0` in any case — `middleware.py:194-210`, `routes/reads.py:136`
- §2.4 (clock) — revise+insert — mismatch — the clock move writes no row (no `updated_at`, no `version` bump); dependents re-derive on next read/write; caller instants echoed verbatim, naive read as UTC; response `data` carries only `current_utc` — `routes/clock.py:16-22`, `middleware.py:137-151`, `db.py:56-121`
- §2.5 step 4 — insert — ambiguity — an FK field absent/null/non-string is `ERR_INVALID_REQUEST` and never reaches the existence check — `routes/registry.py:242-247`, `routes/titles.py:48-71`
- §2.5 step 5 — insert (x2) — ambiguity — whitespace-only required strings count as missing and strings are stored untrimmed; integer fields reject booleans and fractional numbers but accept `7500.0`; explicit `null` on an optional field equals omission — `middleware.py:56-134`
- §2.7 — revise — mismatch — `recognition_state` returns to `RECOGNITION_PENDING` from `DOWNGRADED` as well as from `RECOGNIZED` — `routes/titles.py:324`
- §3.1 P2 — revise+insert — mismatch + ambiguity — `license_expires_at` recorded but never read, so no licence lapses by time; a brand-new rebuilder publishes 100.00 for both record-keeping variants — `routes/registry.py:56-84`
- §3.1 P3 — insert — ambiguity — `certifications` required but may be empty, stored in supplied order — `routes/registry.py:180-184`
- §3.1 P4 — insert — ambiguity — deposit `amount_cents` must be >= 0; a deposit is not a persisted resource and the call answers HTTP 200 with the updated `Rebuilder` — `routes/registry.py:90-100`
- §3.3 P1 — insert — ambiguity — a `source_damage_report_id` of another vehicle draws `ERR_INVALID_REQUEST`; a non-`ACTIVE` predecessor draws `ERR_TITLE_NOT_ACTIVE` — `routes/titles.py:76-81`
- §3.3 P3 — insert — ambiguity — surrender of a non-`NON_REPAIRABLE` title draws `ERR_TITLE_NOT_ACTIVE`, a still-live application draws `ERR_DUPLICATE_ACTIVE_APPLICATION` — `routes/titles.py:131-142`
- §3.11 (conveyance) — insert (x2) — ambiguity — successor copies the outgoing title's `issuing_state_code` with `source_damage_report_id` null; rollback-cascade cancellations carry `cancellation_reason` `FRAUD_HOLD` and the synthesised referral leaves `application_id`/`inspection_id` null so no `open_referral_count` or licence moves — `routes/titles.py:222-230, 253-266`
- §3.11 (recognition) — insert — ambiguity — same-state and unbranded refusals are `ERR_INVALID_REQUEST`, evaluated after the version and `ACTIVE`-and-current checks — `routes/titles.py:286-303`
- §3.12 (licence standing) — insert (x2) — ambiguity — `CLEAR_PROBATION` against a non-zero `open_referral_count` is `ERR_LICENSE_ACTION_INVALID`; automatic suspension fires only inside the substantiating request — `routes/registry.py:136-140`, `services/cascades.py:64-80`
- §5 (preamble) — insert — mismatch — an unrouted path or unsupported method answers `ERR_INVALID_REQUEST` carrying transport status 404/405 rather than 400 — `app.py:63-70`

### Pass 2 summary (verbatim)

Pass 2 complete. Lines 434 -> 434; chars 106,399 -> 111,603 (+5,204). **18 ambiguity-pins, 6 mismatch-revisions** (24 findings across 21 Edit calls).

- §2.1 — revise — mismatch — "guards eight operations" -> **nine**, adding "reading its fee quotation" — `routes/applications.py:546`
- §2.1 — insert — ambiguity — an acting Inspector whose `X-User-ID` resolves to no `Inspector` row draws `ERR_INSPECTOR_NOT_FOUND` (404) on verify/reject/start, after body well-formedness — `routes/applications.py:28-33,232,282`, `routes/inspections.py:259`
- §2.11 — insert — ambiguity — percentages and `damage_ratio` publish as JSON numbers, so decimal places govern rounding not rendering (`0.7500`->`0.75`, `100.00`->`100.0`) — `services/calc.py:126-130`
- §3.4 — revise — mismatch — initial `documentation_completeness_pct` is 0.00 *except* on a `body_class` requiring no classes, where the row reads 100.00 at creation — `routes/applications.py:123,136`, `services/calc.py:179-181`
- §3.4 — insert — ambiguity — `donor_vin` stored as supplied, never checked against the 17-char VIN alphabet — `routes/applications.py:164`
- §3.5 — insert — ambiguity — a wrong owning-application status on verify draws `ERR_INVALID_APPLICATION_STATE`, ahead of the document's own state error — `routes/applications.py:236-248`
- §3.5 — insert — ambiguity — rejection has **no** application-status gate at all — `routes/applications.py:275-292`
- §3.6 — revise — mismatch — submission writes only `fee_escrowed_cents`; `escrowed_fee_total_cents`/`fee_balance_cents` are re-derived — `routes/applications.py:377-384`
- §3.6 — insert — ambiguity — fee quote's `data` is exactly the five fields (no id/timestamps) and reads the stored `assessed_fee_cents` — `routes/applications.py:552-558`, `services/derive.py:307-312`
- §3.6 — revise — mismatch — a refund writes **no** rebuilder counter, only zeroing `fee_escrowed_cents`; capture is the only disposition writing `fees_consumed_cents` — `services/cascades.py:19-21,11-16`
- §3.7 — insert — ambiguity — ACCEPT's "every non-`PHOTO_SET` document VERIFIED" gate also reports `ERR_DOCUMENTATION_INCOMPLETE` — `routes/applications.py:418-423`
- §3.7 — revise — mismatch — `review_note` is validated but stored on no resource — `routes/applications.py:394`
- §3.7 — insert — ambiguity — a decision paired with the wrong admissible status also draws `ERR_INVALID_APPLICATION_STATE` — `routes/applications.py:404-409`
- §3.7 — revise — mismatch — the segregation check binds whenever **any** `COMPLETED_FAIL` attempt exists (reschedules included), against the most recent in `created_at` order — `routes/inspections.py:110-118`
- §3.7 — insert — ambiguity — `effective_end_at` echoes the caller's raw `scheduled_end_at` verbatim when unbuffered, and is a server-normalised 3-fractional-digit UTC instant when the flood buffer applies — `routes/inspections.py:214`
- §3.7 — insert — ambiguity — that value is frozen at booking and never re-derived, while the interval arithmetic re-widens against the current brand — `routes/inspections.py:33-38,214`
- §3.7 — insert — ambiguity — a fresh attempt's initial published values, notably `vin_verified` **false rather than null** — `routes/inspections.py:216-228`
- §3.7 — revise — ambiguity — the re-inspection escrow delta may be negative, and the fee-balance gate binds only when strictly positive — `routes/inspections.py:183-197,234`
- §3.8 — insert — ambiguity — start's two unnamed codes: `ERR_INSPECTION_NOT_SCHEDULED` (409) and `ERR_INSPECTION_SLOT_IN_PAST` (422) — `routes/inspections.py:262-284`
- §3.8 — insert — ambiguity — `parts_document_id` is existence-checked only and need not belong to the inspected application — `routes/inspections.py:306-312`
- §3.8 — insert/revise — ambiguity x3 — the stolen-component cascade leaves `verified_by_inspector_id` as the original verifier; recomputes the *inspected attempt's* application; the referral synthesis is not deduped; and it cancels **no** attempt — `routes/inspections.py:349-371`, `services/cascades.py:83-111`
- §3.8 — insert — ambiguity — `vin_plate_reading` mandatory non-blank, compared verbatim, no VIN-alphabet check — `routes/inspections.py:410,430`
- §3.10 — insert — ambiguity — issue-rebuilt-title's response body carries the **new title record**, not the application, under 201 — `routes/applications.py:537`
- §3.10 — revise — ambiguity + mismatch — `withdrawn_reason` mandatory/non-blank; the refund writes only `fee_escrowed_cents` — `routes/applications.py:441,454`

### Pass 3 summary (verbatim)

Pass 3 complete. 434 lines / 111,603 chars -> 434 lines / **117,005 chars** (**+5,402**). **17 changes across 18 Edit calls: 8 ambiguity-pins, 9 mismatch-revisions.** No earlier-pass wording reverted.

- §2.12 — revise — mismatch — "every row the request touches has its `version` incremented by 1" was a false universal: `_apply` bumps only when a published value actually changed, a multi-stage cascade bumps once per write (vehicle +2), and reads re-derive without writing row metadata. Carved out the two values written outside `_apply` (`recordkeeping_score_rolling`/`_lifetime`, `credential_status`) — `services/derive.py:117-125,194-196,211`
- §2.12 — insert — mismatch — the counter list promised recomputation of `effective_end_at`, which is never recomputed; noted as the one exemption — `services/derive.py:283-304`
- §3.5 — insert — ambiguity — a verify/reject that moves only the two scores leaves the rebuilder's `updated_at`/`version` untouched — `services/derive.py:194-196`
- §3.6 — revise — mismatch — "while the application is still `DRAFT` the quotation carries the base 7,500 cents" is false for an application *returned* to `DRAFT`; `recompute_fee_fields` early-returns on `DRAFT`, so it keeps its last assessment — `services/derive.py:307-312`
- §3.9 — revise — mismatch — duplicate live appeal names `ERR_APPEAL_STATE_INVALID` (409) and its precedence over the window checks; creation nulls `decided_at`/`hearing_officer_user_id`; the `FAILED -> APPEAL_PENDING` move is conditional on the application actually standing in `FAILED` — `routes/appeals.py:41-46,59-78`
- §3.9 — insert — ambiguity — `review_note` validated but kept on no resource — `routes/appeals.py:87`
- §3.9 — insert — ambiguity — any `HearingOfficer` may decide; the decision neither compares nor overwrites `hearing_officer_user_id` — `routes/appeals.py:103`
- §3.9 — revise — mismatch — GRANT raises `attempt_limit` unconditionally but moves `status` only out of `APPEAL_PENDING` — `routes/appeals.py:133-136`
- §3.9 — insert — mismatch — DENY writes the new `status` unconditionally (unlike GRANT), and final denial also recomputes the vehicle's `open_application_count` — `routes/appeals.py:145-160`
- §3.9 — insert — ambiguity — REMAND records `decision_note`, leaves `decided_at` null, touches no application row — `routes/appeals.py:165-169`
- §3.11 — revise — mismatch — a conveyance voids when *its vehicle's* referral is substantiated and **every** `RECORDED` conveyance of the vehicle voids together, not the literal `predecessor_title_id` chain — `services/cascades.py:126-129`, `services/derive.py:83-89`
- §3.12 — revise — ambiguity — duplicate-type refusal named `ERR_REFERRAL_STATE_INVALID` (409); a manual filing may also carry `inspection_id`; `investigator_user_id`/`resolved_at` null at filing — `routes/fraud.py:35-55`
- §3.12 — insert — mismatch — "identical except" falsely universalised the duplicate guard: `cascades.open_referral` has none, so cascades synthesise unconditionally — `services/cascades.py:83-101`
- §3.12 — insert — ambiguity — `investigation_note` validated but not persisted — `routes/fraud.py:74`
- §3.12 — revise — mismatch — substantiation voids **every** `ACTIVE` title (plural) plus the pending-recognition supersession, voids every `RECORDED` conveyance of the vehicle (previously entirely absent from §3.12), and the escrow refund wording now mirrors §3.6/§3.10 — `services/cascades.py:121-154`, `19-21`
- §3.12 — insert — mismatch — `substantiated_referral_count` moves only for the rebuilder named through the referral's `application_id`; a null-`application_id` referral triggers no automatic suspension. Vehicle row written twice in the cascade, `version` +2 — `services/cascades.py:131-138,119,162`
- §3.12 — revise — mismatch — automatic licence moves record neither `suspended_by_user_id` nor `last_license_action_by_user_id` (so a later `REINSTATE` is never barred); auto-suspend takes precedence over auto-probation (`elif`); thresholds are re-evaluated in any request that *opens* a referral against the rebuilder's application too, not only the substantiating one — `services/cascades.py:64-80,101-110`

Out-of-partition note (flagged, not edited): `routes/titles.py` recognition-decide accepts `decision_note` but stores nothing and `derive.recognition_out` publishes no such field; §3.11's "an optional `decision_note`" is under-determined rather than wrong, so it was left. `derive.transfers_of_chain` is dead code with no PRD implication.

## Pipeline complete — 2026-09-04T04:30:00.000Z

All nine steps done. `workspace/PRD_COMPLETED.md` written. Final state: 185 tests, 8/8 parallel rounds at 185/185, 0 tests deleted, 0 implementation fixes required in Step 7.
