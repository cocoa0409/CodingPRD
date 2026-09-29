# Worklog — task_2509_hail_catastrophe_repair_paintless_dent_operations

## Step 1: Create task directory — 2026-09-03T03:14:00.000Z

Created pre-assigned directory `/home/ubuntu/github/CodingPRD/tasks/task_2509_hail_catastrophe_repair_paintless_dent_operations` and its `workspace/` subdirectory. Index 2509 was fixed by the invoking pipeline (no scan of ./tasks/ performed, per instruction — concurrent pipelines on this host would collide on auto-allocation).

## Step 2: Generate scaffold artifacts — 2026-09-03

Generated the three scaffold files from the scenario text plus `skills/prd-bench-scaffold-generator/SKILL.md` only; no sibling `task_*/` directory was read (hard constraint from the caller).

- `SCAFFOLD.yaml` — §1.0–§1.7: domain `hail-catastrophe-pdr-ops`, prefix `/hail-ops`, difficulty `expert_plus`; 13 entities, 8 state machines, 2 `concurrency_rules`, 10 calculations, 37 validations, 51 endpoints, 41 errors, 9 roles (segregation-of-duties model, 3 roles `entity_backed`).
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — §1.8: 9 rule_ids × 22 instances.
- `SCAFFOLD_CORNER_DESIGN.yaml` — §1.9: 53 instances over the guide's nine sections (38 with full `test_recipe`, 15 `excluded_because` stubs). Every one of the 41 §1.6 error ids is named in at least one `assert:` across §1.8+§1.9.

`python3 skills/prd-bench-scaffold-generator/scaffold_lint.py <task-dir>` → `VERDICT: clean lint` (1379 calls scanned; all §1.1 FKs reverse-reachable in §1.5).

## Step 2 (orchestrator record — verbatim subagent summary) — 2026-09-03T04:25:00.000Z

Note: the Step 2 subagent self-appended an entry above. The verbatim returned summary follows, per the skill's requirement that the subagent's report be preserved durably.

Scaffold generation for task 2509 is complete and lint-clean.

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_2509_hail_catastrophe_repair_paintless_dent_operations/SCAFFOLD.yaml` (2003 lines) — §1.0–§1.7 plus preamble; contains neither design key
- `.../SCAFFOLD_DIFFICULTY_DESIGN.yaml` (2514 lines) — single top-level key `scaffold_difficulty_design`
- `.../SCAFFOLD_CORNER_DESIGN.yaml` (4209 lines) — single top-level key `scaffold_corner_design`
- `.../worklog.md` — appended a Step 2 entry

The hard constraint was honored: no sibling `task_*/` directory was listed, read, or grepped at any point. Everything derives from the scenario text plus `skills/prd-bench-scaffold-generator/SKILL.md`.

## Counts

SCAFFOLD.yaml: domain `hail-catastrophe-pdr-ops`, prefix `/hail-ops`, `difficulty_level: expert_plus`. 13 entities, 8 state machines, 2 concurrency rules, 10 calculations, 37 validations, 51 endpoints, 41 errors, 9 roles. Complexity profile: primary `pricing_engine`, secondary `multi_party_negotiation`, layers `[dual_variant_calculation, cascading_side_effects, rate_threshold_triggers, optimistic_concurrency, conditional_feature_flags]`, flat topology, cyclic state machines, segregation-of-duties roles, immediate consistency.

§1.8: 9 rule_ids covering 22 instances. §1.9: 53 instances across all nine claim-guide sections — entities 10, state_machines 9, calculations 6, validations 4, endpoints 3, rbac 3, cross_cutting_complexity_layers 6, consistency_model 1, errors 11 — of which 38 carry full `test_recipe`s and 15 are `excluded_because` stubs citing real §1.8 instance names.

## Design adjudications

- **Vehicle is a parallel machine** (repair dimension × billing dimension) rather than one flattened status, so "insurer authorized but not yet started" and "released but unbilled" are both representable; cross-dimension guards (repair start and release require billing `AUTHORIZED`; `SUBMIT_BILL` requires repair `RELEASED`/`TOWED_OUT`) are what make the cyclic rework loop non-trivial.
- **Pinned evaluation order** everywhere money is computed: per-panel round-then-sum (a sum-then-round implementation lands on 202887 instead of 202886), admin fee on subtotal before volume discount on gross, `round_half_up` whole cents, `created_at ASC` as sole tie-break.
- **Supplement gate checks the cumulative cap before auto-approval**, and the repair-state validation (priority 15) and OCC checks (priority 8/9) both precede the cap (priority 37). Three corner recipes exist purely to pin those precedences, each asserting the code that must *not* come back.
- **Dual-variant pay** (FLAT vs POOLED) always computes both and returns both, so a scaffold that implements only the selected branch fails on the unselected field; the POOLED residual rule is tested in both directions (a +1 stray cent to the largest fraction, and a −1 residual docking the earliest-created ticket on an exact tie).
- **`CrewCoordinator` is deliberately absent** from the throughput-summary endpoint's role list; that omission is exploited by an rbac instance, which is why the endpoint carries an inline 13-field output schema.
- **Error coverage was closed mechanically** — a scan confirms all 41 §1.6 error ids appear in at least one `assert:` across §1.8+§1.9 (`errors never named in any assert: []`).

## Lint verdict (verbatim, re-run just now)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2509_hail_catastrophe_repair_paintless_dent_operations/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2509_hail_catastrophe_repair_paintless_dent_operations/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2509_hail_catastrophe_repair_paintless_dent_operations/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    51
  §1.1 entities declared:     13
  §1.8 instances scanned:     22
  §1.9 instances scanned:     38
  Calls scanned (§1.8+§1.9):  1379

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Beyond the linter I ran my own checks: all 53 corner names unique with zero collisions against the 22 difficulty names, zero unbound `${var}` placeholders, every `grounds:` reference resolvable to a real §1.1–§1.7 anchor (four dangling refs were found and repaired), every `excluded_because.difficulty_instance` resolving to a real §1.8 name, and no stub carrying a `test_recipe`.

## Step 3: Copy shared files — 2026-09-03T04:25:30.000Z

`cp ./INSTRUCTION.md tasks/task_2509_hail_catastrophe_repair_paintless_dent_operations/workspace/INSTRUCTION.md` — done; workspace/ now holds INSTRUCTION.md.

## Step 4: Generate PRD — 2026-09-03T04:36:00.000Z

Orchestrator truncation check (the known doc-generator failure mode): `wc -l` = 402; heading scan shows §1–§5 all present (§2 with 11 subsections, §3 with 9, §4 the 51-endpoint table, §5 the 41-error table); tail ends on the last table row `| ERR_SUPPLEMENT_CUMULATIVE_CAP_EXCEEDED | 422 |` under `## 5. Error Code Catalogue` — a real section boundary, not mid-sentence. NOT truncated; no regeneration needed.

Verbatim subagent summary:

PRD generated at `/home/auntu/…` — correction, at `/home/ubuntu/github/CodingPRD/tasks/task_2509_hail_catastrophe_repair_paintless_dent_operations/workspace/PRD.md`.

**Document shape** — 402 lines. Title: "Hail Catastrophe PDR Ops API — Product Requirements Document". §1 introduction in 3 paragraphs; §2 has 11 domain-derived subsections (Roles and Access Control on the Catastrophe Team; API Response Structure; Pagination and List Ordering; The Logical Clock; Resource Identity, Versioning and Audit Fields; Facility Posture: the Master Gate; Money, Precision and Rounding Order; Cascade Discipline and Derived Aggregates; Stale-Version Guards on Two Write Paths; Collections, Reverse Lookups and List Filters; Rejection Precedence); §3 has 9 lifecycle-ordered subsections; §4 is a 4-column table of all 51 endpoints; §5 is a 2-column table of all 41 error codes. **Final line count 402; final heading `## 5. Error Code Catalogue`**, and the file ends on the last row of that table (`ERR_SUPPLEMENT_CUMULATIVE_CAP_EXCEEDED | 422`) — a real section boundary, no audit footer.

**Hard Contract reports (transcript only, per the skill):**

```
Field coverage check:
- entities[].fields: 130 required, 130 present, 0 missing
- endpoints[].request_body/input + computed output shapes: 92 required, 92 present, 0 missing
- endpoints[].query_params: 18 required, 18 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 37 checked, 37 expressed in prose (§2.11 ordinal precedence chain with per-rule applies_to sets), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_insurer_version / expected_vehicle_version + error_id + 412 all named in §2.9, reinforced in §3.4 and §3.8), 0 missing
- state_machines[].transitions: 38 checked, 38 fully expressed (from/to pairs, every precondition paired with its error_id, every side effect incl. 3-hop demobilization, QC-PASS, and supplement-approval cascades), 0 missing
- calculations[]: 10 checked, 10 fully expressed in operator-free prose (pinned per-panel-before-sum rounding, pinned 6-step waterfall order, cap-before-auto-approve order, pooled residual rule), 0 missing
- validations[] conditions: 37 checked, 37 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 51 endpoints checked, all side effects expressed in the owning workflow, 0 missing
- entities[].fields[] structured content: 130 checked, defaults/initial values/null-before semantics/common-field exceptions (Permit, DamageLine, QualityInspection carry no updated_at or version) reconstructible from prose, 0 missing
- sibling-branch symmetry: 8 groups checked (TARGET/DECLINE, APPROVE/DENY permit, PASS/FAIL inspection, RELEASED/TOWED_OUT release, 4 billing actions, FLAT/POOLED pay, matrix/conventional variants, REVISE/WITHDRAW), 8 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 903
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional verifications: §2.2 was confirmed byte-identical to `skills/prd-bench-doc-generator/section-2.2-response-structure.md` (substring match, including `req_RANDOMALPHANUM123456` and `"data": { }`); all 9 role names spelled exactly as in `roles[].name` with every `identity:` translated (6 opaque, `PdrTechnician`/`QualityInspector` entity-backed to `Technician`, `InsurerAdjuster` entity-backed to `Insurer`); all state enumeration values across the 8 state machines appear verbatim in backticks. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced.

## Step 5: Generate unit tests — 2026-09-03T06:10:00.000Z

Launched concurrently with Step 6 in a single assistant message, so the impl generator was physically unable to read `test_suite/` (the directory did not exist at its spawn time).

Verbatim subagent summary:

Test-suite generation for task 2509 is complete.

## Files written

**Stage 1 — infrastructure** (`/home/ubuntu/github/CodingPRD/tasks/task_2509_hail_catastrophe_repair_paintless_dent_operations/test_helpers/`): `__init__.py`, `api_client.py` (52 endpoints), `api_errors.py` (41 error IDs + HTTP map), `constants.py`, `factories.py`, `fixtures.py`, `assertions.py`, `test_users.py`, `types.py` — 304 exported names.

**Stage 2 — tests** (`.../test_suite/`): `conftest.py` plus 17 test modules, 5,237 lines total.

- Queue A (depth, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`): `test_01`–`test_09`, **44 tests / 22 instances** (2 tests per instance).
- Queue B (breadth, `SCAFFOLD_CORNER_DESIGN.yaml`): `test_10`–`test_17`, **38 tests / 38 instances** — entities 10, state_machines 9, calculations 6, validations 4, endpoints 3, rbac 3, cross_cutting_complexity_layers 2, consistency_model 1.

**Total: 82 tests, 60 distinct `Design:` tags.**

## Audit results (all clean)

- `pytest test_suite --collect-only -q` → **82 collected**, no import/collection errors.
- Citation audit (`/tmp/audit_citations.py`): every test has a docstring, exactly one trailing `Design:` line, ≥1 quoted PRD citation, every quote ≥8 words and **verbatim** in `PRD.md` after whitespace collapsing; no banned `scaffold` / `§1.x` / `Table N` references anywhere in emitted code. → "no problems".
- Section audit (`/tmp/check_sections.py`): every `PRD §X.Y: "…"` cites the section the quote actually lives in. → **0 mismatches**.
- Design-tag cross-check against both yamls: 0 tags outside the yamls, 0 tags pointing at stub instances, **60/60 non-stub instances covered**, 0 uncovered.
- No unused imports, no inline imports inside test bodies.

## Instances skipped

**None.** All 60 non-stub instances (22 queue A + 38 queue B) passed the PRD-first two-condition filter. The 15 stub instances (11 in `errors`, 4 in `cross_cutting_complexity_layers` — all carrying `excluded_because` and pointing at instances already translated elsewhere) were correctly not emitted.

## Design assertions adjusted (PRD-derivable strengthenings, never weakenings)

- entities instance 9: dropped a claim that cited the scaffold's endpoint table rather than the PRD.
- validations `expired_license_blocks_deployment_now_and_the_work_ticket_later`: the recipe claimed posture stays `OPEN` throughout, but PRD §2.6 makes it `RESTRICTED` at the instant the only on-site licensed technician's licence has lapsed and the replacement has not yet arrived. Asserted `RESTRICTED` there, `OPEN` after the replacement goes on site.
- rbac `unauthenticated_and_missing_header_calls_die_before_role_and_state_checks`: dropped `decision_recorded_at` (never named by the PRD) and asserted the initial event status as `EVALUATING`, per PRD §3.1, rather than the recipe's `DECLARED`.
- rbac `peer_lanes_stay_separate_while_shared_reads_stay_open`: dropped "no Technician row named Sly Ortega exists afterwards" — the PRD declares no technician *list* endpoint, so it is unobservable.

One correctness bug found and fixed in a previously written file: `test_11` asserted a bare date for `warranty_expires_at`, which PRD §2.4 types as a full ISO 8601 UTC instant; and seven PRD section numbers in that file pointed at the wrong section (found by the new section audit).

## Step 6: Generate implementation — 2026-09-03T06:10:30.000Z

Verbatim subagent summary:

Implementation is complete and verified.

## Location
`/home/ubuntu/github/CodingPRD/tasks/task_2509_hail_catastrophe_repair_paintless_dent_operations/workspace/implementation/`

## Files written (32 files, no others)
Top level: `app.py`, `start.sh`, `requirements.txt` (Flask==3.0.3), `errors.py`, `clock.py`, `db.py`, `response.py`, `middleware.py`, `validation.py`, `numeric.py`, `serializers.py`

`services/`: `constants.py`, `aggregates.py`, `posture.py`, `calculations.py`

`routes/` (14 blueprints): `common.py`, `storm_events.py`, `facilities.py`, `permits.py`, `housing_units.py`, `technicians.py`, `crew_deployments.py`, `insurers.py`, `rate_agreements.py`, `vehicles.py`, `damage_lines.py`, `work_tickets.py`, `supplements.py`, `quality_inspections.py`, `clock_admin.py`

## Structure
- `db.Store` = plain Python dicts, empty on every boot; nothing is seeded, and no file, SQLite DB or `/tmp` cache is ever written (verified: only `.py` files exist in the tree after the runs).
- Logical clock pinned to `2026-08-01T00:00:00Z` at startup, movable only via `POST /_clock/set_current_utc`; it never falls back to wall time for entity timestamps.
- Live-computed aggregates (facility `billable_accrued_cents`/`absorbed_rental_cents`, carrier `outstanding_direct_bill_cents`/`settled_cents`/`active_rate_agreement_count`, technician pay, vehicle `approved_supplement_cents`) so every "absorb the delta" cascade is automatic and never bumps `version`.
- Lazy facility-posture recomputation drives COMMISSIONED<->SUSPENDED and permit APPROVED->EXPIRED; parallel `repair_status` x `billing_status` dimensions with the three cross-dimension guards; OCC only on rate-agreement activate and supplement create; Decimal/ROUND_HALF_UP whole-cent math with per-panel rounding before summation.
- One global request lock in `app.py` keeps multi-step cascades atomic, released only by the thread that took it.

## Endpoint count
51 routes registered, an exact 1:1 set match against the 51 endpoints declared in `SCAFFOLD.yaml` (programmatically diffed: nothing missing, nothing extra). Undeclared method/path combinations fall through to the 405/404 error envelopes.

## Boot / behaviour check
- Fresh boot on a free port (`PORT=18722 bash start.sh`): `POST /hail-ops/storm-events` returned 201 with the correct envelope and `targeting_score` computed; an intentionally bad enum returned the 400 `ERR_INVALID_REQUEST` envelope. Process killed afterwards; ports 18720-18722 are free and no server process remains.
- Two full end-to-end smoke passes on fresh boots both ended `FAILURES: 0`:
  - Pass 1 (all 51 endpoints, happy path + negatives): matrix 126150 vs conventional 158000, panel cap applied on HOOD, net billable 165900 -> 207900 after the supplement, pooled split 24139/19311 (sums exactly to the purse), warranty `PDR-0001`, 13 rental days with 13500 absorbed, carrier settled 207900/outstanding 0, agreement SUPERSEDED after replacement, plus 403/409/412/404/400 spot checks.
  - Pass 2 (edge paths): TOTAL_LOSS -> TOWED_OUT mints no warranty number and does not advance the facility counter; full 3-cycle rework loop then the mirror-image `ERR_REWORK_LIMIT_EXCEEDED` on start-repair and the successful re-triage (disposition CONVENTIONAL, `pdr_feasible` false, `rework_count` reset to 0, all three tickets VOIDED, net recomputed to 166400); auto-approved supplement (8000 -> net 174720) rejects later review with 409; withdraw/supersede chain and the 3-round negotiation ceiling; permit expiry after a clock jump suspends the facility and FROZEN posture blocks intake, and approving renewal permits restores COMMISSIONED/OPEN.

One incidental confirmation worth flagging: the `ERR_DIRECT_BILL_NOT_ENABLED` gate sits on the `AUTHORIZE` billing action only (per PRD §3.9 line 290), which the smoke run exercised organically against a carrier with the flag off.

## Step 7: Run tests and iterate — 2026-09-03T07:10:00.000Z

Orchestrator independent verification (not taking the subagent's word): all 8 `workspace/implementation/results.{1..8}.json` exist on disk, each reporting `passed 82 / total 82 / failed 0`; `workspace/sweep.log` tail confirms `Results: 82/82 passed, 0 failed, 0 errors, 0 skipped`. Sweep was run under `setsid nohup` so no round was reaped mid-request.

Verbatim subagent summary:

All 8 parallel rounds are green on disk: **82/82 passed in every round**.

## Summary

**Iterations run:** 2 sweeps (8 parallel rounds each). Round-1 baseline was 62/82 in all 8 rounds — fully deterministic, no flakiness anywhere in the task.

**Tests deleted:** none. Every failing assertion traced to a verbatim PRD sentence; no PRD-silence or unique-derivability collapse was found.

**Fixes applied to `test_suite/`** (STEP 2 — assertion mis-translated PRD wording; both were self-contradictions inside the suite):
- `test_suite/test_09_cross_entity_state_dependency.py:102` — `test_a_half_permitted_lot_refuses_commissioning_and_therefore_intake` asserted a `SETUP` lot with `ZONING_USE` still `PENDING` has posture `RESTRICTED`. PRD §2.6 fixes the order: "Otherwise, if permit coverage does not hold, posture is `FROZEN`" is evaluated *before* "Otherwise, if the facility's `status` is `SETUP`, posture is `RESTRICTED`." Its sibling `test_14_corner_endpoints.py:248` asserts `FROZEN` for the identical situation (denied zoning), so the suite disagreed with itself. Changed to `posture="FROZEN"`.
- `test_suite/test_14_corner_endpoints.py` — `test_each_billing_action_answers_only_to_its_own_side_of_the_table` expected `ERR_INVALID_VEHICLE_BILLING_STATE` for `VOID_AUTHORIZATION` on a car that is both `PAID` and `RELEASED`. PRD §2.11 ranks the repair dimension (ordinal 15, listed on `/billing`) ahead of the billing dimension (ordinal 16), so `ERR_INVALID_VEHICLE_REPAIR_STATE` is the contractual answer. Changed to expect that error_id (still an exact `error_id` assertion, not an HTTP-status downgrade).

**Fixes applied to `implementation/`** (17 of the 20 failures collapsed into one root cause):
- `workspace/implementation/clock.py` — split the single formatter in two. `format_instant` (used by `clock.instant()` and by `warranty_expires_at`) now renders the instant *as the logical clock holds it*, emitting a fractional part only when the clock carries sub-second precision. PRD §2.4 says instant-typed fields "are full ISO 8601 UTC timestamps **taken from the logical clock**" and never pins three fractional digits on them, whereas §2.5 pins three digits on `created_at` and §2.2 on `api_request_timestamp`. The old code force-fed `.000` into every clock-derived field, so `commissioned_at`/`decided_at`/`released_at`/`activated_at`/`inspected_at`/`demobilized_at`/`rental_opened_at`/`rental_closed_at`/`warranty_expires_at` never matched the instant the clock had been set to. New `format_audit_instant` keeps the always-three-digit rendering for the audit fields.
- `workspace/implementation/db.py` — `base_row()`/`touch()` were stamping `created_at`/`updated_at` from the *logical* clock, so every row written under one logical instant shared a byte-identical `created_at`. `created_at` is absent from §2.4's list of logical-clock instant fields and §2.5 defines it as "recording when the row was first written"; more decisively, PRD §3.5 breaks rate-sheet ties "by `created_at` descending" and §3.7 breaks the pooled-residual tie "by `created_at` ascending" — tie-breaks that are inert unless the stamp distinguishes rows written in the same logical instant. Audit stamps now come from wall clock at millisecond precision through a lock-guarded, strictly monotonic `_audit_now()`, which also makes `sorted_rows` a genuine total order matching insertion. This fixed `test_a_negative_residual_docks_the_older_of_two_tied_tickets` (`assert older["created_at"] < newer["created_at"]`) deterministically rather than by luck.

No implementation check was weakened, no endpoint/field/side-effect was added, and storage remains in-memory dicts with no seeded data.

## Step 8: Finalize PRD — 2026-09-03T07:16:00.000Z

Step 8 ran (not skipped): Step 7 applied 2 `implementation/` fixes and 2 `test_suite/` fixes, so the skip condition (0 iterations beyond baseline) did not hold.

Verbatim subagent summary:

Done. `PRD_FINALIZED.md` written with two pins (three sentence-level edits), both tracing to the two `implementation/` fixes in `<step_7_diff>`. The two `test_suite/` fixes needed no PRD change — I confirmed both behaviors are already uniquely determined by verbatim PRD prose and that the implementation follows it (`services/posture.py:87-95` evaluates the coverage->`FROZEN` branch before the `SETUP`->`RESTRICTED` branch exactly as §2.6 orders them; `routes/vehicles.py:278/283`, `296/301`, `308/313` check the repair dimension before the billing dimension on `/billing`, matching §2.11 ordinals 15 then 16).

## Line counts
- `PRD.md`: 402 lines / 88,187 bytes
- `PRD_FINALIZED.md`: 402 lines / 89,596 bytes
- Delta: 0 lines (+0.0%), +1,409 bytes (+1.6%); 3 lines revised, 0 inserted, 0 deleted, no new sections.

## Changes
- §2.4 — revise — appended to the instant-typed-fields sentence: a server-stamped instant renders the logical clock's value as held, emitting a three-digit millisecond fraction only when the clock carries sub-second precision (so a whole-second clock stamps `...T00:00:00Z`, not `...:00.000Z`); `current_utc` and `warranty_expires_at` use the same rendering; `first_hail_at` is client-supplied and echoed verbatim — `implementation/clock.py:21-35`, `clock.py:86-88`, `routes/vehicles.py:416`, `routes/clock_admin.py:19`.
- §2.5 — revise — appended to the `created_at` sentence: `created_at`/`updated_at` are audit stamps read from real elapsed time rather than the logical clock, always render three fractional digits, and strictly increase, so no two rows share a `created_at` and rows written under one logical instant still order by write order; §2.3's ordering and §3.5/§3.7's `created_at` tie-breaks are therefore total orders agreeing with insertion order — `implementation/db.py:20-33`, `db.py:72-83`, `db.py:92-102`.
- §2.5 — revise — `updated_at` "refreshed on every mutation" now says it comes from that same audit stamp and equals `created_at` on a never-mutated row — `implementation/db.py:80`, `db.py:86-89`.

## Pre-edit search log

**Edit 1 (§2.4 instant rendering)**
- (a) Subject: how every instant-typed field's string value is produced.
- (b) Enumerated/read: `clock.py` (`format_instant`, `format_audit_instant`, `LogicalClock.instant/plus_days`); every writer of an instant field found by grepping `clock.instant()`/`format_instant`/each field name — `routes/facilities.py:123` (`commissioned_at`), `routes/storm_events.py:125` (`demobilized_at`), `routes/permits.py:92` and `routes/supplements.py:100,165,171,186` (`decided_at`), `routes/rate_agreements.py:136` (`activated_at`), `routes/quality_inspections.py:110` (`inspected_at`), `routes/vehicles.py:119,396-399` (`rental_opened_at`, `released_at`, `rental_closed_at`), `routes/vehicles.py:416` (`warranty_expires_at` via `format_instant(clock.plus_days(...))`), `routes/clock_admin.py:19` (`current_utc`), `routes/storm_events.py:33,44` + `validation.py:139-143` (`first_hail_at`, validated then stored as the raw client string), `serializers.py:40-43,68,84,175,208-214,274,289` (all echoed unmodified), plus the only consumer that re-parses instants, `services/calculations.py:307-318`.
- (c) Adjustments: (i) restricted the new claim to *server-stamped* instants, because `first_hail_at` is stored verbatim and would have been mis-described by a blanket "instant-typed fields render the clock's value" sentence — and added one clause stating that verbatim echo explicitly; (ii) named `current_utc` and `warranty_expires_at` since both are produced by `format_instant` but neither is in §2.4's field list; (iii) softened the fraction rule to "three digits carrying the instant's whole milliseconds ... appears only when the clock instant carries sub-second precision" instead of claiming an exact-millisecond clock, since `format_instant` truncates `microsecond // 1000` and would emit `.000` for a sub-millisecond clock value.

**Edit 2 (§2.5 `created_at`/`updated_at` source and ordering)**
- (a) Subject: where audit stamps come from, their precision, and the orderings that depend on them.
- (b) Enumerated/read: `db.py:20-33` (`_audit_lock`, `_last_audit`, `_audit_now`), `db.py:72-89` (`base_row`, `touch`, `_seq`), `db.py:92-102` (`sorted_rows`, `newest_first`); every `base_row(...)` callsite (`routes/storm_events.py:35`, `facilities.py:50`, `permits.py:47` `versioned=False`, `technicians.py:36`, `housing_units.py:32`, `crew_deployments.py:69`, `insurers.py:25`, `rate_agreements.py:56`, `vehicles.py:95`, `damage_lines.py:65` `versioned=False`, `work_tickets.py:103`, `supplements.py:82`, `quality_inspections.py:103` `versioned=False`); every ordering consumer — all 14 `sorted_rows` selectors in `services/aggregates.py:16-88`, the list endpoints (`facilities.py:84`, `rate_agreements.py:91,140`, `vehicles.py:147`, `crew_deployments.py:137`, `work_tickets.py:132`, `supplements.py:122`, `quality_inspections.py:129`), and `services/calculations.py:82-86` (`newest_first` for the `effective_from` DESC / `created_at` DESC rate-sheet rank) plus `calculations.py:246` (ticket set in `created_at` ASC); `serializers.py:13-18` (which rows surface `updated_at`); `services/aggregates.py:1-7` (aggregate recomputation deliberately does *not* move `updated_at`/`version`).
- (c) Adjustments: kept the sentence to the *source, precision and monotonicity* of the stamps and stated the ordering consequence as "total orders that agree with the order rows were inserted" rather than re-specifying any sort key, so it stays true of `sorted_rows`, `newest_first`, and the §3.5/§3.7 tie-breaks alike; deliberately did not mention the internal `_seq` counter (inert once stamps are unique). I left "refreshed on every mutation" as-is rather than tightening it, because `services/aggregates.py` recomputes aggregates on read without touching `updated_at`/`version` — a stricter universal claim there would have created a new mismatch.

## Step 9: Complete PRD — 2026-09-03T07:40:00.000Z

Orchestrator decision (recorded per AUTONOMY, no user available to consult): Step 9 was run as **three sequential file-partitioned passes** over `implementation/` rather than one scan agent. Rationale — a single-agent full scan of a 30-file / 3,897-line implementation against a 402-line PRD has a known failure mode where the agent returns `PRD_COMPLETED.md` byte-identical to its source, i.e. the scan never actually ran. Partitioning forces every implementation file into exactly one agent's mandate and makes the per-pass byte delta auditable. Partition: pass 1 = infra + storm-event/facility/permit (16 files), pass 2 = technicians/housing/deployments/insurers/rate-agreements/aggregates (6 files), pass 3 = vehicles/damage-lines/work-tickets/supplements/inspections/calculations (6 files). Each pass edited the same `PRD_COMPLETED.md` in place; passes 2 and 3 each verified the earlier passes' edits survived.

Orchestrator verification: `PRD_COMPLETED.md` is 402 lines / 100,624 bytes vs `PRD_FINALIZED.md` 402 lines / 89,596 bytes — `cmp` confirms the files differ, so the scan genuinely ran (not the byte-identical no-op failure mode). Total Step 9 delta +11,028 bytes (+12.3%) with zero line-count change, i.e. every edit was in-paragraph as required. Also confirmed no `implementation/*.py` file is newer than `results.1.json`, so Steps 8–9 were documentation-only and the verified 8×82/82 green sweep still describes the shipped implementation.

**Pass 1 (infra + event/facility/permit) — 14 ambiguity-pins, 3 mismatch-revisions, +5,824 bytes.** Verbatim:

- `§2.1` — revise — ambiguity — an empty-string `X-User-ID`/`X-User-Role` counts as absent (401), and role matching is case-exact — `middleware.py:32`
- `§2.2 success bullets` — revise — ambiguity — `api_request_id` is `req_` + exactly 20 chars from uppercase letters and digits — `response.py:13`
- `§2.2 success bullets` — revise — ambiguity — `api_request_timestamp` reads real wall-clock time, not the logical clock — `response.py:17`
- `§2.2 success bullets` — revise — ambiguity — pagination `meta` fields appear only on list responses; object responses carry just the two — `response.py:31`
- `§2.2 error bullets` — insert — mismatch — unrouted path -> `ERR_RESOURCE_NOT_FOUND`/404; disallowed method -> `ERR_INVALID_REQUEST` at **HTTP 405**, not the 400 §5 lists; any other unanticipated failure -> `ERR_INVALID_REQUEST`/400; trailing slash ignored — `app.py:81-95`, `app.py:55`
- `§2.3` — revise — ambiguity — non-integer `limit`/`offset` also malformed; `offset` has no maximum; empty-string param takes the default; whitespace tolerated; over-range `offset` yields empty `data` with full `total_count` — `validation.py:158-186`
- `§2.3` — revise — ambiguity — `has_more` is `offset + len(returned rows) < total_count` — `response.py:41`
- `§2.4` — revise — ambiguity — clock endpoint answers a `data` object whose only field is `current_utc`; `to_iso8601` accepts `Z`, an offset (normalized to UTC), a zoneless instant, or a date-only string; the move itself recomputes nothing — `routes/clock_admin.py:17-19`, `clock.py:37-52`
- `§2.6` — insert — ambiguity — `activate`/`demobilize`/`close` recompute every facility of the event before their gates; `GET /facilities` recomputes every facility in the store; storm-event create/read/decision recompute nothing — `routes/storm_events.py:89,111,155`, `routes/facilities.py:80`
- `§2.6` — insert — ambiguity — a posture-only or counter-only recomputation moves neither `updated_at` nor `version`; only the `COMMISSIONED`<->`SUSPENDED` flips do — `services/posture.py:88-110`
- `§2.10` — insert — ambiguity — `limit`/`offset` bounds are evaluated ahead of path resolution on nested reads (400 beats 404) — `routes/permits.py:103-105`
- `§2.10` — insert — ambiguity — filters are exact string equality, never enum- or existence-validated (unknown value => empty page, not 400/404); empty-string filter treated as absent; unknown params ignored — `validation.py:189-193`, `routes/facilities.py:82-88`
- `§2.11 ordinal 3` — insert — ambiguity — strict types, no coercion (`"2"` and `2.0` both malformed for an integer field); explicit `null` counts as absent; absent/empty/`null` body read as `{}`; non-object or unparseable body is itself 400 — `validation.py:25-123`
- `§2.11 ordinal 11` — insert — mismatch — on `commission` the facility-state check precedes ordinal 10's storm-event check, inverting the declared ordering — `routes/facilities.py:100-109`
- `§3.2` — revise — **mismatch** — a newly created facility is returned with posture `FROZEN`, not `RESTRICTED`: posture is recomputed before the 201 renders and a fresh site has no approved permits, so coverage fails — `routes/facilities.py:64`, `services/posture.py:90-94`
- `§3.2` — revise — ambiguity — a `DENY` permit decision ignores supplied `valid_from`/`valid_to` (both stay null) and does not enforce their relative order — `routes/permits.py:69-91`
- `§3.2` — revise — ambiguity — the throughput read answers exactly its thirteen computed fields with no `id`/`created_at`/`updated_at`/`version` — `routes/facilities.py:158-172`
- `§3.3` — insert — ambiguity — `effective_end_date` is a derived response field surfaced on every deployment read, not a stored column — `serializers.py:135`

Notable finding: the one hard contradiction found is the **new-facility posture**: PRD said `RESTRICTED`, implementation returns `FROZEN` (verified by running the app). §2.6's own condition ordering already implies `FROZEN`, so §3.2 was the internally inconsistent passage. Secondary contradiction: `ERR_INVALID_REQUEST` is emitted at HTTP 405 for method-not-allowed even though §5 maps it to 400.

**Pass 2 (crews + carriers) — 7 ambiguity-pins, 2 mismatch-revisions, +2,331 bytes.** Verbatim:

- §2.6 — revise — ambiguity — the "widened reach" clause now names `GET /hail-ops/crew-deployments` alongside `GET /hail-ops/facilities` as recomputing every facility in the store, not just the page returned — `routes/crew_deployments.py:135`
- §2.8 — insert — ambiguity — pinned that every listed aggregate is evaluated live (always exactly the sum/count over current contributing rows, never an incrementally accumulated total) and that refreshing one is not itself a mutation, so a technician/carrier/housing unit keeps its `updated_at` and `version` when only a child row changed — `services/aggregates.py:1-11`, corroborated by absence of any `touch()` on those rows (e.g. closeout at `routes/storm_events.py:178-182` bumps agreements but not the carrier)
- §2.11 ordinal 14 — revise — mismatch — `ERR_INVALID_LIFECYCLE_STATE`'s endpoint list omitted rate-agreement activation; added `POST /hail-ops/rate-agreements/{id}/activate` and recorded that on that endpoint the ordinal is inverted against ordinal 10 — `routes/rate_agreements.py:123-126`
- §3.3 — revise — ambiguity — `home_state_code` pinned as a free-form non-empty string, explicitly not subject to the two-uppercase-letter state-code check (only `license_state_code` is) — `routes/technicians.py:30-31`
- §3.3 — insert — ambiguity — `bed_nights_committed` day count is the plain signed difference, never floored at zero, so a deployment ended before its `start_date` contributes negative bed-nights (reachable via the demobilize cascade) — `services/aggregates.py:120-128`
- §3.3 — insert — ambiguity — deployment creation resolves body FKs in the order `technician_id` -> `facility_id` -> `housing_unit_id`; the named housing unit need not sit at the destination facility (no cross-check); creation makes no demand on the facility's own `status` or `posture` — `routes/crew_deployments.py:47-49`
- §3.3 — insert — ambiguity — on `CONFIRMED` -> `ON_SITE`, a facility not in `SETUP`/`COMMISSIONED` (or unresolvable) is rejected with `ERR_INVALID_LIFECYCLE_STATE`, not a facility-specific code — `routes/crew_deployments.py:172-176`
- §3.4 — insert — ambiguity — drafting resolves `insurer_id` before `storm_event_id` and places no demand on the parent event's `status` (only activation is event-gated) — `routes/rate_agreements.py:53-54`
- §3.4 — revise — mismatch — activation's `DRAFT` check runs ahead of the parent-event state check (inverting §2.11's ordinal 10 vs 14), and a non-`DRAFT` agreement reports `ERR_INVALID_LIFECYCLE_STATE` — `routes/rate_agreements.py:123-133`

Notable non-changes (impl already pinned uniquely by existing prose): the rest-buffer overlap predicate, the half-open housing-capacity sweep, `effective_end_date` semantics, all six list filters and the pagination-before-path-resolution order, role lists for all six endpoints, the OCC guard's position ahead of every 409 gate, and the two-hop supersession cascade.

**Pass 3 (vehicles + money + pricing engine) — 5 ambiguity-pins, 6 mismatch-revisions, +2,859 bytes.** Verbatim:

- **§2.6 (posture reach)** — revise — mismatch — added `GET /hail-ops/vehicles` to the store-wide-recompute list, and pinned the three vehicle-side paths that recompute *nothing* (nested damage-lines read, ticket submit, supplement revise) vs. the two supplement writes that *do* recompute on every branch; noted that after-mutation-only recomputers carry no posture gate so timing is unobservable — `routes/vehicles.py:145`, `routes/damage_lines.py:85`, `routes/work_tickets.py:147`, `routes/supplements.py:106,189,241`
- **§2.5 (version rule)** — revise — mismatch — narrowed the "increments ... including mutations that only rewrite derived money or counter fields" universal to admit the §3.8 supplement-approval exception — `routes/supplements.py:167`
- **§3.5 (intake payload)** — insert — ambiguity — pinned body-FK resolution order `facility_id` then `insurer_id` — `routes/vehicles.py:75-76`
- **§3.5 (intake initial values)** — insert — ambiguity — pinned `pdr_feasible` starts **true** (PRD listed every other initial field but omitted this one) — `routes/vehicles.py:109`
- **§3.6 (triage outcomes)** — revise — mismatch — `rework_count` reset to 0 is unconditional, not tied to the `PDR_REPAIR`/`CONVENTIONAL` branch; a forced re-run that totals the car clears the counter too — `routes/vehicles.py:228`
- **§3.7 (ticket creation)** — insert — ambiguity — pinned body-FK order `vehicle_id` then `technician_id` — `routes/work_tickets.py:74-75`
- **§3.7 (ticket submit)** — revise — mismatch — reordered the gates to ticket-`OPEN` -> vehicle-`IN_REPAIR` -> `labor_units`, and pinned that a vehicle no longer `IN_REPAIR` answers `ERR_INVALID_LIFECYCLE_STATE` (not `ERR_INVALID_VEHICLE_REPAIR_STATE`), consistent with §2.11 ordinal 14 — `routes/work_tickets.py:156-166`
- **§3.7 (inspection)** — insert — ambiguity — pinned body-FK order `vehicle_id` then `inspector_technician_id` — `routes/quality_inspections.py:54-55`
- **§3.8 (review APPROVE)** — insert — mismatch — only the supplement's `version` moves; the vehicle's four money fields are rewritten in place while its `updated_at`/`version` stay put, unlike a filing — `routes/supplements.py:162-167`
- **§3.8 (review COUNTER)** — insert — ambiguity — `counter_amount_cents` presence/bracket failures are `ERR_INVALID_REQUEST` evaluated *after* identity + `UNDER_REVIEW` and *before* the round limit, not at ordinal 3 — `routes/supplements.py:174-183`
- **§3.8 (revise)** — insert — ambiguity — `revised_amount_cents` bracket failures are `ERR_INVALID_REQUEST` after the `COUNTERED` gate and after the round limit, and `WITHDRAW` ignores the field entirely — `routes/supplements.py:213-227`

Verified-clean in pass 3 (no edit needed): per-panel rounding before summation, cap-then-route, dual-variant totals, `pdr_feasible`, the inclusive 75% total-loss floor with rental projection, the six-step waterfall (fee on subtotal / discount on gross, higher tier first, both inclusive), the 55%/50% labour pool and purse, tier weights, the largest-fractional-part residual with `created_at` ASC tie-break, `max(1, ...)` rental days and excess absorption, warranty `PDR-####` density across tow-outs, the supplement floor/`max` threshold, the strict cumulative-cap comparison, the 3-round ceiling, and every §2.11 ordinal sequence in the five route files.

**Step 9 totals: 26 ambiguity-pins, 11 mismatch-revisions, 37 edits, +11,028 bytes, 0 new lines, 0 new sections.**

## Pipeline complete — 2026-09-03T07:42:00.000Z

All nine steps done. `workspace/PRD_COMPLETED.md` written. Final state: 82 tests, 8/8 sweep rounds at 82/82, 51 endpoints, 13 entities.
