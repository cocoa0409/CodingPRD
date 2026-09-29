# Worklog — task_2316_school_capacity_study_portable_classroom

## Step 1: Create task directory — 2026-09-01T00:00:00.000Z

Created `tasks/task_2316_school_capacity_study_portable_classroom/` and `tasks/task_2316_school_capacity_study_portable_classroom/workspace/`.

## Step 2: Generate scaffold — 2026-09-01T00:30:00.000Z

All three artifacts are complete and lint-clean.

Lint verdict (pasted verbatim):

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2316_school_capacity_study_portable_classroom/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2316_school_capacity_study_portable_classroom/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2316_school_capacity_study_portable_classroom/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    61
  §1.1 entities declared:     14
  §1.8 instances scanned:     23
  §1.9 instances scanned:     48
  Calls scanned (§1.8+§1.9):  564

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## What was generated

Directory: `/home/ubuntu/github/CodingPRD/tasks/task_2316_school_capacity_study_portable_classroom/`

**`SCAFFOLD.yaml`** (§1.0–§1.7, ~1720 lines)
- Profile: `primary_archetype: quota_allocation`, `secondary_archetype: temporal_windowing`, layers `[dual_variant_calculation, cascading_side_effects, optimistic_concurrency, selector_policy]`, topology `flat`, state-machine shape `parallel`, role model `segregation_of_duties`, consistency `immediate`, `difficulty_level: beyond_expert`.
- **14 entities**: School, Room, ClassSizePolicy, ProgramSetAside, EnrollmentProjection, CapacityStudy, PortableUnit, PlacementSite, PlacementRequest, Permit, InstallationCrew, InstallationSchedule, CapitalBudget, DisposalRecord.
- **6 state machines** (CapacityStudy with a revision cycle and round cap; PlacementRequest forking across a variable permit set and joining; PortableUnit on two independent dimensions — condition and allocation; Permit; InstallationSchedule; PlacementSite).
- **2 concurrency rules**: `study-create-stale-school` (`expected_school_version` → 412 `ERR_STALE_SCHOOL_VERSION`) and `request-create-stale-study` (`expected_study_version` → 412 `ERR_STALE_STUDY_VERSION`).
- **8 calculations**: program capacity by room type (dual variant: state loading factors vs district policy), utilization/deficit/required-portable count, site feasibility with mitigation-flag propagation, permit-set derivation, relocation cost model (mobilisation + haul + off-summer multiplier + site work + rehab + permits + nested-clamp contingency), alternative cost comparison (dual variant: lifecycle vs immediate capital, vs boundary change/addition), salvage value (dual variant), long-term reliance share.
- **41 ordered validations**, **61 endpoints**, **61 error codes**, **8 roles** (DistrictAdmin, FacilitiesPlanner, CapacityCertifier, PermitCoordinator, BuildingOfficial, OperationsScheduler, AssetManager, CrewLead — with entity-backed CrewLead identity and author/certifier segregation of duties).

**`SCAFFOLD_DIFFICULTY_DESIGN.yaml`** — all 9 §0.5 rules, **23 instances** (≥2 each), including three-arm dual variants, a nested-clamp contingency, a revision-round cap, a fork/join over a variable permit set, four-level cascades, three priority-pair conflicts, exact-boundary checks (utilization exactly at 95.0%, hose lay exactly at 150 ft), closed-interval pad reuse vs half-open crew windows, and two compensating-invariant ledgers.

**`SCAFFOLD_CORNER_DESIGN.yaml`** — all **9 guide sections, 73 instances** (48 with full recipes, 25 `excluded_because` deferrals to named §1.8 instances): entities 12, state_machines 15, calculations 15, validations 9, endpoints 5, errors 6, rbac 3, complexity_layers 7, consistency_model 1.

Verified mechanically: no duplicate instance names across both design files, every `excluded_because.difficulty_instance` resolves to a real §1.8 instance, every `${var}` is bound by an earlier `captures:`, and all 61 catalog error codes have at least one triggering instance. The hard constraint was honored — no sibling task directory was listed, globbed, grepped, or read.

Two scaffold defects found and fixed while cross-checking: `ERR_UNIT_RELOCATION_LIMIT` was unreachable in any bounded fixture (added a seedable `prior_relocation_count` input to PortableUnit), and `ERR_FIRE_ACCESS_NONCOMPLIANT` was permanently pre-empted by the feasibility gate (swapped validation priorities 17/18 with an explicit ordering rationale). Also added `GET /facilities/class-size-policies/{id}` and `GET /facilities/installation-crews/{id}` for reverse-reachability.

## Step 3: Copy shared files — 2026-09-01T00:32:00.000Z

Copied `INSTRUCTION.md` → `tasks/task_2316_school_capacity_study_portable_classroom/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T00:46:00.000Z

PRD written to `workspace/PRD.md` — 469 lines, generated solely from `SCAFFOLD.yaml` (neither withheld design index was opened, grepped, or referenced; no sibling task directory was read).

## Structure

**§1 Introduction** — 3 paragraphs framing the domain (district capacity studies → portable allocation), the `/facilities` prefix, and the two organizing commitments (segregation of duties, three-bucket fiscal conservation).

**§2 Global Specifications** — 11 subsections:
- 2.1 User and Role-Based Access Control · 2.2 API Response Structure (byte-verbatim from `section-2.2-response-structure.md`) · 2.3 Pagination
- 2.4 Resource Identity, Audit Fields and the Logical Clock · 2.5 Flat Addressing and Identifier Resolution Order · 2.6 Validation Precedence (normative ordered list 1-41) · 2.7 Stale-Version Guards on Study and Request Creation · 2.8 Seats, Percentages and Money: Precision Rules · 2.9 The Capital Budget Partition · 2.10 Cascade Discipline and Deterministic Ordering · 2.11 Enumerations of Record

**§3 Business Logic & Workflows** — 9 subsections: 3.1 Standing Up the Building Program · 3.2 Measuring Program Capacity: Two Methods, One Campus · 3.3 Utilization, the Portable Trigger, and the Study Review Cycle · 3.4 Judging a Pad · 3.5 Opening a Placement Request and Choosing a Unit · 3.6 Costing the Move and Weighing the Alternatives · 3.7 Permitting: One Fork, Two Joins · 3.8 Booking and Executing the Installation Window · 3.9 Condition, Decommissioning, Disposal and the Reliance Record

**§4 Endpoint Definitions** — 61 rows, exactly 4 columns. **§5 Error Code Catalogue** — 61 rows, exactly 2 columns. Document ends at §5 with no audit footer.

## Hard Contract audits (machine-verified against SCAFFOLD.yaml)

**Contract 1 — Field-Name Coverage: PASS.** 116 required identifiers (105 `entities[].fields[].name` plus 11 input-only names from `input`/`request_body`/`query_params`/`path_params`, optional-marker suffixes stripped) — 0 missing, all present verbatim in backticks. 28 additional composite response field names (`mobilisation_cents`, `direct_cost_cents`, `district_average_portable_share_pct`, `narrative_required`, `relocate_excluded_for_reliance`, `current_utc`, etc.) documented voluntarily.

**Contract 2 — Rule Coverage: PASS.** All 41 validations present with their priority ordering rendered as a normative list, each with error id, HTTP status, and exhaustive `applies_to` scope (including the four-endpoint `ERR_UNIT_NOT_SERVICEABLE` scope, the three-endpoint `ERR_SITE_OCCUPIED` scope, the two-endpoint `ERR_SEGREGATION_OF_DUTIES` scope, and the deliberate fire-access-before-feasibility inversion). All 52 state transitions across the 6 state machines covered (34 as explicit `FROM -> TO` arrows; the remaining 18 are set-valued or system-triggered froms covered in prose — `DRAFT`/`RETURNED` -> `SUPERSEDED`, `SERVICEABLE`/`NEEDS_REHAB` -> `UNSAFE`, the five-state withdrawal fan-in, the two-state cancellation fan-in, and the 4x3 re-assessable pad matrix). All 9 calculations rendered in prose with all 60 numeric constants present and no operator syntax or pseudocode. Both OCC rules given a dedicated subsection with occ field, error, 412 status and rationale. Cascades (certification 3-link, unsafe-declaration 3-link, install-completion 5-row, withdrawal unwind) documented with ordering and per-row `version` increments. Sibling-branch symmetry stated explicitly for the permit join (approve arm vs. deny arm side effects are called out as disjoint) and the two dual-variant calculations. 61/61 error ids appear in §2/§3 prose, not only in the §5 table.

**Contract 3 — §3 Path Purity: PASS.** 747 backtick tokens in §3; 0 begin with `/`, 0 are bare HTTP methods, 0 are method+path pairs, and the literal string `/facilities` occurs 0 times in §3. Endpoints are named there only by state-transition framing, role + action verb, or capability description.

No fuzzy quantifiers ("approximately", "roughly", "conservatively") appear anywhere; the only "about"/"around" hits are lexical ("turnaround buffer", "least-moved-around", "round out"), and the one imprecise instance in validation rule 40 was rewritten to name both committed amounts explicitly.

## Step 5: Generate unit tests — 2026-09-01T02:00:00.000Z

Done. All queue A and queue B work is complete and audited.

## Files written

`test_helpers/` (9 files): `__init__.py`, `constants.py`, `types.py`, `api_errors.py`, `api_client.py` (65 endpoint methods), `test_users.py`, `factories.py`, `assertions.py`, `fixtures.py`

`test_suite/` (18 files): `conftest.py` plus `test_01` … `test_17`

## Test counts

**Queue A — difficulty (§1.8): 47 tests / 23 instances / 9 rules**, every instance with >=2 tests.
`test_01_variant_divergence` 6, `test_02_cost_and_share_composition` 6, `test_03_study_cycle_and_permit_fork` 4, `test_04_cascades` 4, `test_05_validation_precedence` 6, `test_06_boundaries` 7, `test_07_cross_entity_state` 6, `test_08_temporal_overlap` 4, `test_09_compensating_invariants` 4.

**Queue B — corner (§1.9): 48 tests / 48 non-stub instances**, exactly one each.
`test_10_entities` 12, `test_11_state_machines` 7, `test_12_calculations` 6, `test_13_validations` 6, `test_14_endpoints` 5, `test_15_errors` 6, `test_16_rbac` 3, `test_17_complexity_layers` 3.

Total 95 tests, `--collect-only` clean.

## Audits run (all passing)

- **Tag audit**: 95 tests, each with exactly one `Design:` line as the final docstring line; zero untagged, zero dual-tagged, zero dangling tags. Coverage: difficulty 23/23 at >=2 tests; corner 48/48 live instances at >=1. Zero `excluded_because` stubs translated (25 stubs left alone: state_machines 8, calculations 9, validations 3, complexity_layers 4, consistency_model 1).
- **PRD-citation audit** (AST over every docstring, each quoted span matched verbatim against the cited `§` section): `issues 0`. Fixed two stragglers this pass — `test_03` attributed a §3.3 phrase to §2.6, and `test_11` quoted "Certification is performed…" dropping the PRD's `**Certification**` bold markers.
- No `pytest.mark.skip/skipif/xfail` anywhere; no "scaffold" references in generated code; pyflakes clean apart from the intended `# noqa: F401` fixture re-exports in `conftest.py`; `__pycache__` removed.

## Instances skipped: none

Every non-stub instance in both indices passed the PRD-first filter. Nine **sub-assertions** were dropped where the design yaml contradicted or outran the PRD (test kept, assertion omitted):

1. Decommission endpoints asserted as `AssetManager` per §3.9/§4, not the design's role.
2. Claim that a `SUBMITTED` study becomes `SUPERSEDED` (§3.3 supersedes only `CERTIFIED`).
3. Rule 5's September positive control (contradicts the §3.8 summer window).
4. `effective_capacity_seats` (field does not exist).
5. `rated_seats: 999` pass-through probe (§3.1 derives `rated_seats` server-side).
6. `version == 2` on `GET /facilities/schools/{id}` after first certification, in the instance that had not yet established the campus baseline.
7. Cost-model `basis == "LIFECYCLE_20YR"` and `basis=TEN_YEAR` -> 422 (the PRD names no `basis` enum).
8. `utilization_pct == null` on a DRAFT study (SCAFFOLD declares `default: 0`).
9. rbac return-study payload key `reason` replaced with `correction_note`, which §3.3 and the endpoint contract require.

Two design-yaml bugs were normalised in translation: `work_type: "INSTALL"` -> `"SET"` (legal enum), and `OperationsScheduler sched-5` -> the fixture's `sched-2` (only the role is contractual).

## Step 6: Generate implementation — 2026-09-01T02:00:00.000Z

The implementation is complete and verified.

## Files written
All under `workspace/implementation/` (26 files, ~3,150 lines of Python):

- **Entry/infra**: `app.py` (app factory, blueprint registration under `/facilities`, envelope error handlers for `ApiError`/`HTTPException`/`Exception`), `start.sh` (executable, foreground `exec python3 app.py`, installs Flask only if missing), `requirements.txt`
- **Core**: `db.py` (14 in-memory dicts, `new_record`/`touch`/`public`, no seeding), `clock.py` (logical clock pinned to `2026-08-01T00:00:00Z`), `errors.py` (all 62 error ids -> HTTP), `response.py` (meta envelope, pagination inside `meta`), `middleware.py` (auth, role gate, CrewLead ownership), `validation.py` (typed validators, pagination, FK resolution), `constants.py` (all vocabularies + every calculation constant)
- **Services** (9): `numbers` (Decimal/ROUND_HALF_UP), `capacity`, `feasibility`, `cost`, `salvage`, `reliance`, `budget`, `selection` (auto-assign ranking), `cascade` (all shared multi-row side effects)
- **Routes** (7 blueprints + `common.py`): `config`, `studies`, `units`, `requests`, `permits`, `schedules`, `disposals`

## Endpoint coverage
A programmatic diff of `app.url_map` against the SCAFFOLD `endpoints:` list shows **61/61 method+path pairs registered, 0 missing, 0 extra**.

## Verification
Three smoke suites run against a fresh `bash start.sh` boot:
- Happy path (80 assertions): campus -> policy -> rooms -> projections -> study create/submit/certify -> pad assess -> unit -> budget -> request -> cost-model -> assess-site -> permits (corrections/resubmit/approvals) -> PERMITTED + encumbrance -> scheduling -> install -> reliance -> decommission -> UNSAFE -> disposal. All pass; the single reported mismatch was my own wrong expectation (share 13.8 % < 15 % and `consecutive_reliance_years` = 0 => `MONITOR` is PRD-correct).
- Edge cases (118 assertions, 0 failures): both capacity methods, `ERR_PROJECTION_COVERAGE_GAP`, policy band/year mismatches, the 3-round return/reopen loop and `ERR_REVISION_LIMIT_REACHED`, study supersession, feasibility verdicts and mitigation-flag ordering, auto-assign ranking, off-summer 1.35 escalation with capped contingency, budget-insufficiency atomicity on the permit join (last permit left `SUBMITTED`), permit DENIED arm, withdraw and UNSAFE cascades, legacy placement, reliance report/summary, permit expiry, waiver role gate, ADA gate, disposal valuation floors, envelope on unknown paths.
- Interval/boot suite (31 assertions, 0 failures): `ERR_PAD_WINDOW_CONFLICT` (closed intervals +/-7 days, only `PLANNED`/`IN_PROGRESS` siblings count), `ERR_CREW_CAPACITY_EXCEEDED` with half-open intervals permitting abutting windows, CrewLead ownership, clock control, and a cold-boot check that every collection is empty and the clock reads exactly `2026-08-01T00:00:00.000Z`.

Three consecutive kill-and-relaunch cycles through `start.sh` each came up clean with an empty store, matching the `--isolation per-test-server` harness. The only artifact the process writes is `__pycache__` (removed); no SQLite, JSON, or any other data file.

## Notable design decisions
- Validation order follows PRD §2.6 literally by call ordering in each handler: auth -> CrewLead ownership -> path ids left-to-right -> body FKs in entity-declaration order -> body shape -> pagination -> OCC -> target state -> numbered rules 11-41 in numeric order.
- Money gates are checked before any mutation, so a rejected final permit approval leaves the permit, request, unit, pad and budget untouched.
- Ledger entities (`ClassSizePolicy`, `EnrollmentProjection`, `DisposalRecord`) are created with `versioned=False` so they expose only `id` + `created_at`.
- Cascades are centralised in `services/cascade.py` so withdraw and the UNSAFE sweep share one implementation; `touch_unit=False` in the UNSAFE path keeps the unit's version bump at exactly one.
- List filters accept unknown enum values permissively (empty page); only pagination and the `cost-model` `basis` parameter are strictly validated.
- `app.run(..., threaded=True)` so a lingering keep-alive health probe cannot block subsequent harness requests. Re-verified booting cleanly after that change.

## Step 7: Run tests and iterate — 2026-09-02T01:50:00.000Z

All diagnostic work is complete; here is the final state.

## What I did

**Iterations run:** 13 official 8-round parallel sweeps (~104 rounds) via the mandated `prd-bench-local-run` command shape, plus three load-robust private verification passes (1 sequential full suite, 8 parallel per-file rounds, 8 parallel single-pytest-process full-suite rounds with per-test server restarts).

**Tests deleted:** none. Every failing assertion traced to a verbatim PRD sentence, so no test collapsed under STEP 1a (PRD silence) or STEP 1b (non-unique derivability).

**Fixes applied to `test_helpers/`**
- `test_helpers/assertions.py` — added `assert_clock_stamp()` and `assert_created_at()` (+ `_parse_instant`). PRD §2.4 states "three fractional digits" only for `api_request_timestamp`/`created_at`; of `updated_at`, `submitted_on`, `approved_on`, `certified_on`, `disposed_on` it says only that they are "derived from this clock" — so the instant is asserted and the unstated rendering is not (STEP 1c split).
- `test_helpers/factories.py` — `next_asset_tag`/`next_pad_code`/`next_room_number` now emit an `-AUTO-` marker (`R-AUTO-0001`, `PAD-AUTO-0001`, `PU-AUTO-0001`). **This was a real order-dependent flake**: the counters produced `R101…R901`, `PAD-149…151`, which are exactly labels tests spell out by hand, so once earlier tests were skipped the counter could land on the literal and a PRD-correct server answered `ERR_DUPLICATE_ROOM` (caught in sweep 5, `rnd_4`, on `test_a_submitted_study_cannot_be_submitted_again_to_refresh_its_figures`). Widths stay inside PRD's 24/20/20-character limits.

**Fixes applied to `test_suite/`**
- `test_04_cascades.py`, `test_10_entities.py`, `test_11_state_machines.py`, `test_13_validations.py` — clock-stamp assertions routed through the new helpers.
- `test_08_temporal_overlap.py` — pad-buffer fixture moved to 2027-08-01→08-10 with probes at 07-25/07-24, so both probes lie inside June 15–Aug 15 (PRD §2.6 evaluates rule 35 before rule 38) while preserving the "one day past the seventh" boundary.
- `test_13_validations.py` — the off-summer window now sits inside the 180-day permit validity (rule 37), so the waiver-role gate is the only thing under test.
- `test_15_errors.py` — every must-succeed create brings its own fresh unit, since PRD §3.6 requires `IN_STORAGE` for `IN_STORAGE → RESERVED`.

**Fixes applied to `implementation/`**
- `workspace/implementation/routes/studies.py::create_study` — removed `touch(school)`; PRD §2.4 ties a `version` bump to "every mutation of that row" and §3.2 states no campus mutation when a study opens.
- `workspace/implementation/start.sh` — dependency probe uses `importlib.util.find_spec('flask')` instead of `import flask` (launcher-only, identical semantics; removes a duplicate Flask import that cost 2–5 s per boot under load and eliminated all "server could not be restarted" errors).

## Exit condition status — not reached, for environmental reasons

The mandated exit (`passed == total` in all 8 rounds) was **not** achievable on this host, and the shortfall is provably not in the task:

- Every non-pass in the official sweeps is a setup **ERROR**, not a failure: `pytest_runtest_setup` → `_restart_server` → `_kill_port` → `subprocess.TimeoutExpired: Command 'pids=$(lsof -ti:PORT -sTCP:LISTEN); …' timed out after 5 seconds` (426 occurrences in one sweep alone).
- `lsof -ti:9` — a port nobody listens on — measures **2.6 s to 11.2 s** on this host, against the runner's hard-coded 5 s budget. Host state during the session: load 200–440, 3.5k–5.8k processes, 15k–17.7k TCP sockets, 250+ foreign `python3 app.py` servers across ~50 sibling task directories, and other agents SIGKILLing processes by broad patterns.
- Across ~104 official rounds only 4 assertion-level FAILEDs occurred; three were `RemoteDisconnected`/`IncompleteRead`/`ConnectionReset` (server killed mid-response by external cleanup) and the fourth was the counter collision now fixed. The last complete sweep (all 8 rounds, post-fix) reported **failed = 0 in every round**.
- Load-robust equivalent of the sweep — 8 concurrent single-pytest-process full-suite runs with a per-test fresh in-memory server (same isolation semantics, generous subprocess timeouts, `ss` instead of `lsof`) — returned **95 passed / 0 failed / 0 errors in all 8 rounds** after the factory fix.

The task directory is left clean: no `results.*.json`, no stray `rnd_*.log`/`probe.log`, no `__pycache__`, and no orphan servers of mine.

### Orchestrator's own independent verification of the Step 7 exit claim

The orchestrator did not take the subagent's environmental claim on trust; it re-ran the mandated 8-round sweep itself with the exact command shape from the skill. Result:

```
round 1: total=95 passed=42 failed=0 errors=53
round 2: total=95 passed=36 failed=0 errors=59
round 3: total=95 passed=48 failed=0 errors=47
round 4: total=95 passed=48 failed=0 errors=47
round 5: total=95 passed=50 failed=0 errors=45
round 6: total=95 passed=43 failed=0 errors=52
round 7: total=95 passed=48 failed=0 errors=47
round 8: total=95 passed=46 failed=0 errors=49
```

- **`failed = 0` in every one of the 8 rounds — zero assertion failures across 760 test executions.**
- All 399 non-passes carry one identical `error_message`, and it is raised inside the shared runner before the test body executes:
  `failed on setup with "subprocess.TimeoutExpired: Command 'pids=$(lsof -ti:42391 -sTCP:LISTEN 2>/dev/null); [ -n "$pids" ] && kill -9 $pids 2>/dev/null; true' timed out after 5 seconds"` with `duration_seconds: 5.039`.
- The error set is **uniform across the whole suite, not test-specific**: all 95 tests error in at least one round and pass in at least one other. No test is systematically red.
- Host state measured by the orchestrator at sweep time: `load average: 245.98, 283.65, 293.16` on 32 cores, 422 foreign `python3 app.py` servers, ~25 000 TCP sockets, and `lsof -ti:9` (a port with no listener) timed at **5.135 s** — already over the runner's hard-coded 5 s budget with none of my own rounds running.
- Root cause is `_kill_port` in `prd-bench-local-runner/src/prd_bench_local_runner/pytest_plugin.py:46-55` (and the twin in `port_utils.py:60-71`), whose `timeout=5` cannot be met while ~50 sibling pipelines keep the host's process and socket tables this large. That file is **shared infrastructure used concurrently by every other pipeline on the host, so the orchestrator deliberately did not modify it.**

Conclusion: the implementation and test suite are green on assertions; the sweep's `passed == total` gate is blocked solely by a 5-second timeout in shared host tooling under external load.

## Step 8: Finalize PRD — 2026-09-02T02:05:00.000Z

Done. `PRD_FINALIZED.md` written at `workspace/PRD_FINALIZED.md`.

## Line counts
- `PRD.md`: 469 lines
- `PRD_FINALIZED.md`: 469 lines
- %-delta: 0.0% (both edits are in-line revisions of existing paragraphs; 2 of 469 lines changed = 0.43% of lines touched)

## Changes

- **§2.4 (Resource Identity, Audit Fields and the Logical Clock), line 95 — insert** — appended one sentence pinning the *rendering* of every clock-derived instant (not just `created_at`/`api_request_timestamp`) to "an ISO 8601 UTC timestamp with three fractional digits", naming `created_at`, `updated_at`, `submitted_on`, `approved_on`, `certified_on`, `disposed_on`, `current_utc` and `api_request_timestamp` — `implementation/clock.py:13-18` (`format_instant`, sole renderer) reached via `clock.iso()` at `db.py:49,51,62`, `response.py:20`, `routes/config.py:32`, `routes/permits.py:78,104`, `routes/requests.py:252`, `routes/disposals.py:61`, `routes/studies.py:202`.
- **§3.3 (Study Review Cycle), line 241 — revise** — replaced "the create also increments the campus's `version` by 1" with "the campus row itself is not mutated by the create, so the campus's `version` is unchanged by it" — `implementation/routes/studies.py:78-91` (`create_study` no longer calls `touch(school)`; comment at :89-90).

## Per-edit pre-edit search log

**Edit 1 — §2.4 instant rendering**
- (a) Subject: textual rendering of every server-stamped/reported timestamp value.
- (b) Enumerated: `grep -rn "isoformat|strftime|format_instant|utcnow|datetime.now"` -> only `clock.py` (`format_instant`, `fromisoformat` for parsing). `grep -rn "submitted_on|approved_on|certified_on|disposed_on|installed_on|clock.iso|clock.today|clock.year"` -> every write site listed above; read `clock.py`, `db.py`, `response.py`, `routes/config.py` (clock-set endpoint returns `clock.iso()`), `routes/disposals.py`, `routes/permits.py`, `routes/requests.py`, `routes/studies.py`. Also checked non-clock date fields to make sure the claim does not over-reach: `installed_on` (`routes/units.py:114`) is client-supplied `YYYY-MM-DD` and is not persisted; `requested_window_start/end` (`routes/requests.py:60-61`) and `window_start/end` (`routes/schedules.py:39-40`) are client-supplied dates; `services/salvage.py:9` uses `clock.year()` (an integer, not a rendered instant); `routes/schedules.py:72` only *parses* `approved_on`.
- (c) Adjustment: scoped the sentence to "Every instant the server **renders from this clock**" and enumerated the fields explicitly, rather than writing "every date/timestamp field", so the client-supplied `YYYY-MM-DD` date fields and the integer year derivation are not swept in.

**Edit 2 — §3.3 campus version on study creation**
- (a) Subject: mutations (and therefore `version`/`updated_at` bumps) of the campus (`school`) row.
- (b) Enumerated: `grep -rn "touch(" --include=*.py` across `implementation/` -> all school-row touches are `routes/studies.py:217` (certify: `certified_study_id` + `reliance_flag`), `services/cascade.py:162` (`install_complete`), `:188` (`decommission_complete`), `:205` (`legacy_placement`). Read `routes/studies.py` in full (create/submit/certify/return/reopen) — `create_study` touches only the superseded sibling studies and mints the new row; `submit_study` touches only the study; nothing else reaches `school`. Read `services/cascade.py` in full and `routes/config.py` (`create_school`, `patch_room` — no school touch). Cross-checked every other PRD claim about campus `version` (`grep -n "campus's \`version\`"` -> lines 114, 155, 177, 235, 311, 323, 325): line 235 (certify), 311 (install complete), 323 (legacy placement), 325 (decommission complete) all remain true against the four impl touch sites; line 177 is a generic cascade statement; lines 114/155 are the stale-guard itself and make no bump claim. Line 241 was the sole false claim.
- (c) Adjustment: worded the negation as "the campus row itself is not mutated **by the create**" so it reads as scoped to study creation and cannot be misread as a global claim that the campus row never gains a version (which would contradict the four enumerated touch sites).

## Step 9: Complete PRD — 2026-09-02T02:20:00.000Z

PRD_COMPLETED.md is written at `workspace/PRD_COMPLETED.md`.

## Counts

- **Source vs result**: PRD_FINALIZED.md 469 lines / 89,540 chars -> PRD_COMPLETED.md 470 lines / 96,636 chars (**+7,096 chars, +1 line** — one added bullet inside the existing §2.2 error-format list; no new sections).
- **38 changed lines**: **34 ambiguity-pins**, **4 mismatch-revisions**.

## Changes

- §2.1 RBAC — insert — ambiguity — a present-but-blank/whitespace-only header counts as absent; both header values are trimmed — `middleware.py:21-28`
- §2.2 Success format — insert — ambiguity — `api_request_id` is `req_` + exactly 20 upper-case alphanumerics — `response.py:14`
- §2.2 Success format — insert — ambiguity — `has_more` is `offset + rows_returned < total_count` — `response.py:47`
- §2.2 Error format — insert — ambiguity — three off-catalogue transport errors: non-object body -> `ERR_INVALID_REQUEST`/422, unrouted path -> `ERR_NOT_FOUND`/404, bad method -> `ERR_METHOD_NOT_ALLOWED`/405 — `app.py:37-50`, `validation.py:31`
- §2.3 Pagination — insert — ambiguity — `limit`/`offset` parsed as plain decimal integer literals; decimal point, leading `+`, leading zero all rejected — `validation.py:196-213`
- §2.3 Pagination — insert — ambiguity — equal-`created_at` rows keep insertion order; list filters are query params named exactly after the row field, string-compared (`true`/`false` for booleans), undeclared params ignored — `db.py:80`, `routes/common.py:11-32`
- §2.4 Logical clock — insert — ambiguity — `to_iso8601` is 1–64 chars, `Z`/offset/naive-as-UTC accepted, unparseable -> `ERR_INVALID_REQUEST`; response `data` carries only `current_utc` — `routes/config.py:27-32`
- §2.5 Identifier resolution — insert — ambiguity — a non-string body FK raises the 404, an absent/null one falls through to rule 6 — `validation.py:249-262`
- §2.6 rule 3 — revise — mismatch — `ERR_CREW_NOT_ASSIGNED` necessarily runs after the path schedule resolves, so an unknown id still reports `ERR_SCHEDULE_NOT_FOUND` — `routes/schedules.py:139-141`
- §2.6 rule 6 — insert — ambiguity — free-text note fields hold 1–2000 chars — `routes/studies.py:226`, `routes/requests.py:269`, `routes/permits.py:36,91`
- §2.7 Stale-version guards — insert — ambiguity — both tokens must be integers >= 0, else `ERR_INVALID_REQUEST` before the 412 — `routes/studies.py:59`, `routes/requests.py:63`
- §2.10 Cascade ordering — insert — ambiguity — equal-`created_at` sibling rows processed in insertion order — `db.py:80`
- §3.1 Class-size policy — insert — ambiguity — school-year form validated as 4 digits/hyphen/2 digits, halves not cross-checked — `validation.py:18,147-151`
- §3.1 Rooms — insert — ambiguity — both PATCH fields optional; a revision supplying neither still bumps `version` — `routes/config.py:171-183`
- §3.1 Appropriation — insert — ambiguity — `fiscal_year` uses the same `YYYY-YY` form — `routes/config.py:265`
- §3.2 Capacity breakdown — insert — ambiguity — both variants recomputed against the study's pinned policy; zero capacity yields `utilization_pct` 0.0 with trigger false — `routes/studies.py:114-120`, `services/capacity.py:99-104`
- §3.3 Projection selection — insert — ambiguity — a candidate tied on both `created_at` and `projected_students` resolves to the row inserted first — `services/capacity.py:82-85`
- §3.3 Return — insert — ambiguity — `correction_note` required, validated ahead of the state check, and not persisted — `routes/studies.py:225-238`
- §3.5 Unit reservation — insert — ambiguity — non-`IN_STORAGE` unit -> `ERR_UNIT_STATE_INVALID`/409, ahead of condition/grade/campus/relocation/geometry checks — `routes/requests.py:69-71`
- §3.5 Auto-assign — insert — ambiguity — may run on a request that already names a unit; that unit is never in the pool, and a displaced unit returns to `IN_STORAGE` with `version` +1 — `routes/requests.py:174-190`
- §3.5 Site confirmation — insert — ambiguity — no unit assigned -> `ERR_REQUEST_STATE_INVALID` — `routes/requests.py:207-210`
- §3.5 Withdrawal — revise — mismatch — `reason` is required; the unit's, pad's and each cancelled schedule's `version` also increase, and the appropriation's increases even when 0 was released — `routes/requests.py:269`, `services/cascade.py:57-82`
- §3.6 Relocation estimate — insert — ambiguity — with a null unit, `off_summer_applied` still reports the window test truthfully — `services/cost.py:31-43`
- §3.6 Relocation alternative — insert — ambiguity — removal cost is 0 when the request names no unit — `services/cost.py:126`
- §3.6 Cost-model view — insert — ambiguity — `basis` legal values `LIFECYCLE_20YR`/`IMMEDIATE_CAPITAL`, other values -> `ERR_INVALID_REQUEST`, default `LIFECYCLE_20YR`, echoed back as `basis` — `constants.py:60`, `routes/requests.py:140`, `routes/common.py:42-49`
- §3.7 Permit filing — insert — ambiguity — request with no unit -> `ERR_REQUEST_STATE_INVALID` — `routes/requests.py:238-241`
- §3.7 Permit filing — insert — ambiguity — permits minted in fixed discipline order `DSA_STRUCTURAL, FIRE_MARSHAL, ELECTRICAL, PLUMBING, ADA_ACCESS` — `services/cost.py:94-101`
- §3.7 Permit decision — insert — ambiguity — `decision` vocabulary pinned; `correction_note` stored only for `CORRECTIONS_REQUIRED`, discarded otherwise — `constants.py:54`, `routes/permits.py:35-58`
- §3.7 Permit refiling — insert — ambiguity — `correction_response` required but not persisted; stored `correction_note` survives the refiling — `routes/permits.py:91,102-105`
- §3.7 Approval join — insert — ambiguity — budget test precedes all writes, so a shortfall leaves the deciding permit in `SUBMITTED` with nothing mutated — `routes/permits.py:66-79`
- §3.8 Start/complete — revise — mismatch — both require the owning request to be `SCHEDULED`, reported as `ERR_REQUEST_STATE_INVALID`/409 — `routes/schedules.py:146-149,166-169`
- §3.8 Install completion — insert — ambiguity — the request's `encumbered_cost_cents` is not zeroed; it leaves the aggregation by status alone — `services/cascade.py:135-145`, `services/budget.py:8-13`
- §3.8 Cancellation — insert — ambiguity — `reason` required; the request steps back only if actually `SCHEDULED` — `routes/schedules.py:189,199-202`
- §3.9 Inspection — insert — ambiguity — both fields required; any status recordable on a non-`DISPOSED` unit incl. `UNSAFE -> SERVICEABLE`; `SERVICEABLE` + grade `D` -> `ERR_UNIT_STATE_INVALID`/409 regardless of current condition — `routes/units.py:83-90`
- §3.9 Unsafe cascade — insert — ambiguity — reachable from `UNSAFE` too, and refires each time `UNSAFE` is recorded — `routes/units.py:96-97`
- §3.9 Legacy placement — insert — ambiguity — `installed_on` validated but not persisted; unit-state and condition failures both `ERR_UNIT_STATE_INVALID`/409 evaluated ahead of the pad checks — `routes/units.py:114-129`
- §3.9 Decommissioning — revise — mismatch — unit-state gates report `ERR_UNIT_STATE_INVALID`/409; `hosted_portable_seats` clamped at 0; the pad's `version` also increases by 1 — `routes/requests.py:286-308`, `services/cascade.py:177-188`
- §3.9 Reliance report — insert — ambiguity — governing-study tie resolves to the row inserted first, selection is live and may differ from the campus's stored `certified_study_id`; zero denominator -> share 0.0 — `services/reliance.py:8-29`
- §3.9 District roll-up — insert — ambiguity — `rounding_basis` is always the literal `PER_SCHOOL_THEN_AVERAGE` — `constants.py:156`

Nothing under `implementation/` was read for state beyond source files, and nothing there was modified.

## Post-pipeline: second independent 8-round sweep — 2026-09-02T02:20:00.000Z

The orchestrator ran the mandated sweep a second time (concurrently with Steps 8-9, which touch only PRD files) as an additional data point:

```
round 1: total=95 passed=57 failed=0 errors=38
round 2: total=95 passed=69 failed=0 errors=26
round 3: total=95 passed=61 failed=0 errors=34
round 4: total=95 passed=67 failed=0 errors=28
round 5: total=95 passed=70 failed=0 errors=25
round 6: total=95 passed=57 failed=0 errors=38
round 7: total=95 passed=60 failed=0 errors=35
round 8: total=95 passed=68 failed=0 errors=27
```

- `failed = 0` in every round again; all 251 errors carry the identical `lsof` setup-timeout signature.
- Pass counts rose from 36-50 (first sweep) to 57-70 (second sweep) as host load eased from ~290 to a lower figure — the pass rate tracks host load, which is the signature of an environmental limit rather than a task defect.

### Aggregate evidence over both sweeps (16 rounds, 1520 test executions)

- **Assertion failures: 0.**
- **Tests that never passed in any round: 0.** All 95 distinct tests passed in at least 3 of the 16 rounds; none is systematically red.
- Every non-pass is the shared runner's `_kill_port` 5-second `lsof` timeout, raised in `pytest_runtest_setup` before the test body runs (`duration_seconds: 5.039`).
