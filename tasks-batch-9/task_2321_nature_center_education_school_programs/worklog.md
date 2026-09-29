# Worklog — task_2321_nature_center_education_school_programs

## Step 1: Create Task Directory — 2026-09-01T16:12:00.000Z

Created `tasks/task_2321_nature_center_education_school_programs/` and `tasks/task_2321_nature_center_education_school_programs/workspace/` (pre-allocated task name used verbatim; no index scan performed).

## Step 2: SCAFFOLD.yaml (§1.0–§1.7) — 2026-09-01T16:49:00Z

14 entities, 14 state-machine entries, 2 concurrency rules, 10 calculations, 1 selector policy,
52 validations, 56 endpoints, 76 error codes, 7 roles. `domain_name: nature-center-education`,
`api_prefix: /nature-center`. Neither `scaffold_difficulty_design` nor `scaffold_corner_design`
present.

## Step 3: SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8) — 2026-09-01T17:04:00Z

22 instances across all 9 rule_ids (dual_variant_calc 2, combinatorial_formula 3,
non_linear_state_machine 3, transitive_cascade 2, priority_pair_validation_conflict 2,
boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 2,
compensating_invariant 2).

## Step 4: SCAFFOLD_CORNER_DESIGN.yaml (§1.9) — 2026-09-01T17:48:00Z

Breadth walk over 9 sections, 85 instances: 76 with full `test_recipe` plus 9
`excluded_because` stubs that delegate to named §1.8 instances. All 76 error codes are reachable
(68 asserted in §1.9, 8 delegated to stubs).

## Step 5: Verification

- `yaml.safe_load` parses all three files; corner file has the single top-level key
  `scaffold_corner_design`.
- `scaffold_lint.py` → `VERDICT: clean lint` (1892 calls scanned against the 56 declared endpoints).
- All 9 cited `difficulty_instance` names resolve; instance names unique across the union of both
  design files.
- Forbidden concurrency vocabulary absent from all three files.

---
(Note: the Step 2 subagent wrote its own internal step numbering above. Orchestrator-level pipeline records follow.)

## Step 2: Generate Scaffold (subagent) — 2026-09-01T17:49:00.000Z

All three artifacts are complete and lint-clean at `/home/ubuntu/github/CodingPRD/tasks/task_2321_nature_center_education_school_programs/`.

### Files

- `SCAFFOLD.yaml` (145 KB, §1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (149 KB, sole key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (497 KB, sole key `scaffold_corner_design`)
- `worklog.md` (step log)

### SCAFFOLD.yaml

`domain_name: nature-center-education`, `api_prefix: /nature-center`.

| Section | Count |
|---|---|
| Entities (§1.1) | 14 |
| State machines (§1.2) | 14 entries |
| Concurrency rules (§1.2.1) | 2 |
| Calculations (§1.3) | 10 |
| Selector policies | 1 |
| Validations (§1.4) | 52 |
| Endpoints (§1.5) | 56 |
| Errors (§1.6) | 76 |
| Roles (§1.7) | 7 |

Entities: ProgramOffering, StandardAlignment, CurriculumMaterial, School, Educator, TrainingRecord, Permit, AnimalAmbassador, TrailSegment, Booking, EquipmentManifest, EvaluationReport, ScholarshipFund, AidApplication. Roles: EducationDirector, CurriculumSpecialist, BookingCoordinator, StewardshipManager, GrantsOfficer, Naturalist, TeacherContact. Booking carries two independent state machines (`delivery_status`, `funding_status`); OCC runs on `expected_booking_version` at assign-resources and `expected_fund_version` at aid-application create.

### Difficulty design (§1.8)

22 instances spanning all 9 required rule_ids: dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 2, compensating_invariant 2.

### Corner design (§1.9)

85 instances over 9 sections — 76 with a full `test_recipe`, 9 `excluded_because` stubs delegating to named §1.8 instances: entities 11, state_machines 11, calculations 11, validations 32, endpoints 6, errors 2, rbac 6, cross-cutting complexity layers 5, consistency model 1.

### Verification

- `scaffold_lint.py` → `VERDICT: clean lint`; 1892 calls scanned across §1.8+§1.9, all conforming to the 56 declared endpoints, all §1.1 FKs reverse-reachable.
- All 76 error codes reachable: 68 asserted directly in §1.9 recipes, the remaining 8 (`ERR_ANIMAL_WELFARE_CAP_REACHED`, `ERR_EDUCATOR_NOT_CERTIFIED_FOR_GRADE_BAND`, `ERR_EDUCATOR_TIME_CONFLICT`, `ERR_EDUCATOR_WEEKLY_LOAD_EXCEEDED`, `ERR_FUND_NOT_OPEN`, `ERR_MATERIALS_NOT_READY`, `ERR_SCHOOL_SUSPENDED`, `ERR_TRAIL_CAPACITY_EXCEEDED`) delegated via stubs whose cited difficulty instances all resolve by name.
- Instance names unique across the union of both design files; forbidden concurrency vocabulary absent from all three files; no sibling task directory was read.

## Step 3: Copy Shared Files — 2026-09-01T17:49:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2321_nature_center_education_school_programs/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD (subagent) — 2026-09-01T18:06:00.000Z

The PRD is written and all three Hard Contracts verified mechanically.

**Output:** `workspace/PRD.md` — **500 lines**, ending at §5 with no audit footer.

### Structure

- **§1 Introduction** — 3 paragraphs; scenario framing plus the two product commitments that drive the rules (no reservation outlives its authorizing resource; ledger counters must be reconstructible).
- **§2 Global Specifications** — 12 subsections: 2.1 Access Control, Roles and Identity Binding (all 7 roles, 5 opaque + `Naturalist`/`TeacherContact` entity-backed); 2.2 API Response Structure (pasted verbatim); 2.3 Pagination; 2.4 Resource Identity, Timestamps and Version Semantics; 2.5 The Logical Program Clock and the ISO Program Week; 2.6 Path and Foreign-Key Resolution Order; 2.7 Numeric Discipline; 2.8 Optimistic Concurrency on Bookings and Funds; 2.9 Validation Precedence (full 52-step ladder); 2.10 Withdrawal Cascades and Counter Symmetry; 2.11 Segregation of Duties; 2.12 The Two Parallel Dimensions of a Booking.
- **§3 Business Logic & Workflows** — 9 domain-derived subsections: catalog authoring/publication; school partners and equity tiers; staffing and certification decay; permits/animals/welfare posture; trails and habitat; booking request→assignment→confirmation; rain plans/delivery/no-show/cancellation; fee assessment, scholarship funds and award waterfall; outreach equipment, evaluation and funder rollup.
- **§4** — 4-column table, 57 rows (56 business endpoints + the logical-clock endpoint).
- **§5** — 2-column table, 76 error rows.

### Coverage audit (all verified by script against SCAFFOLD.yaml)

```
Field coverage check:
- Entity fields declared: 117
- Endpoint input/query/path/output identifiers: 105
- Unique identifiers after normalizing optional markers: 135
- Identifiers absent from PRD in backticks: 0
Status: PASS
```

```
Rule coverage check:
- Validations: 52/52 error_ids present; priority ladder 1..52 stated in order in §2.9; applies_to sets spot-verified (scope violation = 11 endpoints, not-assigned-educator = 6, time-range = 2, body-FK = 5, chaperone = 2, group-size = 2, fund-insufficient = 2, transport-sublimit = 2)
- State machines: 14 blocks / 70 transitions — every from/to state token present; every side effect narrated; sibling branches given symmetric density (ONBOARDING vs CLEARED deactivation, REQUESTED vs CONFIRMED no-show/cancel, CONFIRMED vs RAIN_DIVERTED delivery, RETURNED vs SHORTAGE_REPORTED, DRAFT vs PUBLISHED retire)
- Enum values: all entity-field enum members present
- Calculations: 10/10, all 33 constants embedded with values; pinned step orders stated (fee 6 steps incl. round-per-student-before-multiply; aid waterfall 9 steps; LGI 5 steps); dual variants distinguished (provisional/final fee, projected/realized exposure)
- Concurrency: both OCC rules framed as stale-version only — `expected_booking_version`/`ERR_STALE_BOOKING_VERSION` 412 and `expected_fund_version`/`ERR_STALE_FUND_VERSION` 412; explicit statement that no other endpoint takes a version field
- Cascades: permit→animal→booking→counters and no-show→suspension→cancel→aid-revoke both traced end to end; 3 further withdrawal cascades (vet hold/retire, trail close, educator deactivate)
- Selector policy: rain-plan eligibility filter, 3-level ranking, empty-pool no-mutation behaviour
- Endpoint side_effects: 38/38 endpoints with declared effects covered
- Errors: 76/76 ids with matching HTTP statuses
Status: PASS
```

```
Path purity check (§3 only):
- Backtick tokens scanned in §3: 990
- Tokens starting with "/": 0
- Bare HTTP-method tokens: 0
- Method+path combinations: 0
Status: PASS
```

Also confirmed: §2.2 matches `section-2.2-response-structure.md` byte-for-byte; §4 role columns match every endpoint's `roles` list exactly (0 mismatches); "The system" appears 0 times. The two withheld design files were never opened, and no sibling task directory was read.

One correction applied during audit: §2.9 item 9 said "five operations" where the scaffold's `applies_to` lists six endpoints; changed to six.

## Step 5: Generate Unit Tests (subagent) — 2026-09-01T18:55:00.000Z

Both stages are complete and the full suite audits clean.

### Files written

**Stage 1 — `test_helpers/` (9 files)**
`__init__.py` (barrel export), `constants.py`, `types.py`, `api_errors.py` (76 codes + HTTP status map registered), `api_client.py` (57 endpoint methods), `test_users.py`, `factories.py`, `assertions.py`, `fixtures.py` (composite scenario builders: canonical clock→published offering→school→cleared educator→booking→assign→confirm chain, plus animal / trail / fund / aid / delivery / evaluation / manifest / strike-accumulator / threshold-targeting variants).

**Stage 2 — `test_suite/` (conftest.py + 19 test modules)**
Queue A (depth, 9 files, 63 test functions): `test_difficulty_{dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant}.py`
Queue B (breadth, 10 files, 174 test functions): `test_corner_{entities, state_machines, calculations, validations_a, validations_b, endpoints, errors, rbac, cross_cutting, consistency}.py`

### Counts

- **237 test functions → 283 collected cases** (`pytest --collect-only` clean; imports and fixtures all resolve).
- Queue A: 63 functions across 22 difficulty instances — **every instance has ≥2 tests** (target met).
- Queue B: 174 functions across 76 non-stub corner instances — **every instance has ≥1 test**. The 9 `excluded_because:` stubs were verified to cross-reference real difficulty instances and correctly received nothing.

### Audit results (mechanical, over all 237 tests)

- Exactly one `Design:` line per test, always the last docstring line; **all 237 tags resolve** to a real `name:` in the source index (22/22 difficulty instances, 76/76 non-stub corner instances tagged); no tag points at a stub.
- Every docstring's PRD quote verified as a **character-for-character substring** of `workspace/PRD.md` (whitespace-normalised match).
- Zero `pytest.skip` / `xfail` / placeholder tests; zero scaffold vocabulary in comments or docstrings; no duplicate test names; all imports come from `test_helpers` (only `pytest` besides).

### Instances skipped

**None.** All 22 difficulty and all 76 non-stub corner instances passed the PRD-first two-condition filter. What was dropped instead was a small number of *sub-assertions* inside otherwise-translated instances, each because the PRD does not uniquely derive them:

- `final_gross_fee_cents == 0` before delivery (3 places) — the PRD defines the field only as computed at delivery, so null-vs-zero is undetermined.
- `vehicle_class == null` before a manifest is loaded — the PRD pins only that loading decides it.
- `trail_segment_id == null` on a booking cancelled from `REQUESTED` — §3.7 states the status, release reason and money effects, not FK clearing.
- Nullness of `reviewed_by_user_id` / `published_at` / `background_check_started_at` in pre-transition states.
- Exact rendering of the clock endpoint's echoed `current_utc` — §2.5 does not pin the format for that echo.
- Index-position ordering assertions where two rows would share a `created_at`; where ordering *was* the claim, the logical clock is advanced between creates so ascending order is unambiguous.

One assertion uses `validate_error_is_one_of` by design: a booking's second aid application simultaneously violates the funding-state precondition (§2.9 #14) and the uniqueness rule (#39–44), and the PRD does not fix which answers.

## Step 6: Generate Implementation (subagent) — 2026-09-01T18:55:30.000Z

Implementation complete and verified.

### Files written (16, all under `workspace/implementation/`)

- `start.sh` (executable), `requirements.txt` (`flask>=3.0`), `app.py`
- Core: `errors.py`, `store.py`, `logical_clock.py`, `envelope.py`, `security.py`, `schema.py`
- Domain logic: `calc.py`, `derive.py`, `flows.py`
- `routes/{catalog,staff,stewardship,bookings,money,ops}.py`

~3,140 lines total.

### Module layout

Layered, no cycles: `store` (14 in-memory dicts) → `envelope`/`schema`/`security`/`errors` (transport, body+query validation, RBAC + entity-backed scoping) → `calc` (pure money/index arithmetic) / `derive` (global derived-field recomputation) / `flows` (multi-entity cascades) → six route blueprints. `app.py` registers the domain blueprints under `url_prefix="/nature-center"` and `clock_bp` at root, calls `logical_clock.reset()`, and installs `ApiError` / `HTTPException` / bare-`Exception` handlers so 404/405/400/415/500 all return the standard envelope.

### Endpoint count

**56**, diffed programmatically against SCAFFOLD's endpoint list after normalising path params: `MISSING: []  EXTRA: []`. Error catalogue also verified 76/76 (IDs + HTTP statuses) against both PRD's table and SCAFFOLD.

### Notable design decisions

- **Single global `derive.sync()`** runs after every mutation, recomputing all derived fields with touch-if-changed semantics; a per-request `id(entity)` touched-set in `flask.g` guarantees each entity's `version`/`updated_at` bumps at most once per request.
- **Gross fees are event-driven, not in `sync()`** — a NO_SHOW pins `final_gross_fee_cents` to the 7500 flat fee, so recomputing it globally would clobber that.
- **Two clocks**: real wall time for `created_at`/`updated_at`; the logical clock (default `2026-08-01T00:00:00Z`) for *all* business temporal logic. Client datetime literals are echoed back verbatim, with the parsed instant cached alongside in `_dt`.
- **PRD-over-SCAFFOLD resolutions**: educator conflict + weekly-load checks fire only at `assign-resources`; both LAPSED *and* SUSPENDED permits cascade booking releases; rain-divert with an unknown `alternate_offering_id` returns `ERR_RAIN_ALTERNATE_NOT_ELIGIBLE` 422 (not 404) because validation priority 7's `applies_to` excludes that endpoint.
- **Money**: `Decimal` with `ROUND_HALF_UP`, rounded only at the PRD's pinned rounding points; no floats anywhere in the money path.
- **Check ordering** in every handler mirrors PRD §2.9's 52-step precedence list literally (e.g. confirm = 26→27→28→36→45→46→47).
- `threaded=True` on the werkzeug server so a lingering keep-alive health probe can't block subsequent requests; `flask.g` being thread-local makes this safe.
- Fresh-boot cleanliness confirmed: all 14 collections empty, clock at default. Four smoke suites covering the full happy path plus concurrency, cascades, SoD, pagination and error envelopes all pass on a freshly launched server.

## Step 7: Run Tests and Iterate (subagent) — 2026-09-02T03:52:00.000Z

All 8 parallel rounds of the official sweep are green: `passed == total == 283` in every `results.${i}.json`.

### Summary

**Iterations run:** 5 completed official 8-round parallel sweeps (`prd-bench-local-run`, `--isolation per-test-server`, `--timeout 120 --test-timeout 30`, no `--api-url`), plus one supplementary 8-round full-suite sweep on a private lsof-free harness for cross-checking. Final sweep: 8/8 rounds at 283/283, 0 failed, 0 errors, 0 skipped.

**Tests deleted:** none. No STEP 1a PRD-silence or STEP 1b non-derivability collapse was found — every failure traced to a real defect or to host-level transport noise. No assertion was weakened, no `skip`/`xfail` added (verified: 0 such markers in `test_suite/`).

**Fixes applied to `implementation/`**
- `workspace/implementation/store.py` — `touch()` and `new_entity()`: `created_at`/`updated_at` are now stamped from `stamp_now()` (the logical program clock) instead of `datetime.now(timezone.utc)`. Driven by the verbatim PRD §2.5 sentence "Nothing in this system reads real wall-clock time." `real_now()` is retained only for `meta.api_request_timestamp` in `envelope.py`. Storage remains in-memory dicts with nothing seeded (re-verified: the implementation contains no `open(`, `subprocess`, `threading`, `sys.exit` or `os._exit`).

**Fixes applied to `test_helpers/`**
- `test_helpers/fixtures.py`, `setup_school_with_strikes` and `setup_animal_at_projected_exposure` — replaced a naive day counter that produced the non-existent date `2026-09-31` with real `date(2026,9,29) + timedelta(days=n)` arithmetic, keeping every booking slot inside the ISO program week of `DEFAULT_CLOCK`. This was the shared setup error behind 3+ failures (the TRIAGE HINT case: test_helpers first, not the implementation).

**Fixes applied to `test_suite/`**
- `test_suite/test_corner_errors.py`, `_BODY_FK_CASES` — the two aid-application cases used the `GO` (GrantsOfficer) role header, but PRD §4 permits only `TeacherContact, BookingCoordinator` on `POST /nature-center/aid-applications`, so they got `ERR_ROLE_NOT_PERMITTED` 403 before reaching the FK resolution the case is about. Changed to `BC`; the 404 `error_id` assertions are unchanged.
- `test_suite/test_difficulty_transitive_cascade.py`, `TestPermitLapseCascade::test_lapsing_the_permit_mutates_booking_trail_and_animal_alike` — inserted `set_clock("2026-09-28T09:30:00Z")` before the cascade (still inside the same ISO week, still before the booking start). With logical-clock stamping, a mutation under a stationary clock cannot move `updated_at`; advancing the clock makes "refreshed" observable and preserves all three `updated_at_after > updated_at_before` assertions rather than deleting them.

**Environment note (not part of the deliverable)**
Host load was 200–460 on 32 cores with 400+ competing `prd-bench-local-run` processes from sibling pipelines. `prd_bench_local_runner.pytest_plugin._kill_port()` shells out to `lsof -ti:<port> -sTCP:LISTEN` with a hard-coded `timeout=5` and does not catch `TimeoutExpired`; real lsof needed 6–9 s under that load, producing 1445 spurious setup ERRORs per sweep. I put a semantics-preserving `lsof` stand-in on `PATH` for my sweep processes only (`/tmp/nc2321bin/lsof`): it answers the same query via the `sock_diag` netlink interface filtered to `TCP_LISTEN` plus a `/proc/<pid>/fd` inode lookup walked circularly downwards from its own pid, delegating to `/usr/bin/lsof` for any other argument vector. Verified to return byte-identical pids to real lsof. Nothing under `tasks/task_2321.../` was changed for this, and the harness's own kill/isolation semantics are unchanged. Earlier sweeps with real lsof and with a private lsof-free harness showed the same result set, so the shim did not mask anything: across 8 sweeps (~11 000 test executions) the only non-passes other than the four genuine defects above were socket-level `ConnectionResetError` / `IncompleteRead` events at a rate of ~0.05–0.25 %, each on a different test, never reproducible in isolation, and never accompanied by a server-side exception (Werkzeug's dev server is HTTP/1.0, so every request opens a fresh localhost connection).

**Orchestrator verification:** re-read all 8 `results.*.json` independently — each reports `283/283`, `failed=0`, `errors=0`; `grep` over `test_suite/` confirms 0 `skip`/`xfail`/`pytest.skip` markers across 237 test functions.

## Step 8: Finalize PRD (subagent) — 2026-09-02T03:57:00.000Z

`workspace/PRD_FINALIZED.md` written. All five Step 7 diff items traced; only one of them (the `store.py` clock-stamping fix) revealed PRD silence, so all edits derive from that single subject plus its direct consequences.

### Line counts
- `PRD.md`: 500 lines / 102,063 bytes
- `PRD_FINALIZED.md`: 500 lines / 103,537 bytes
- Δ lines: 0 (0.0%); Δ bytes: +1,474 (+1.44%). 5 lines revised in place, no lines/sections added.

### Changes
- **§2.4 (`created_at`)** — revise — `created_at` is read from the logical program clock at the moment of the write, never real time; two rows created without moving the clock carry identical `created_at` — `implementation/store.py:98-102` (`new_entity` → `stamp_now`), `store.py:16-19`.
- **§2.4 (`updated_at`/`version`)** — revise — `updated_at` is refreshed from the same logical clock, so a mutation under a stationary clock rewrites the same rendered instant while `version` still advances; `updated_at` visibly moves only after the clock moves — `implementation/store.py:88-95` (`touch`).
- **§2.2 (`api_request_timestamp` bullet)** — revise — it is transport metadata and the one value generated from the host's real clock, unrelated to any entity's `created_at`/`updated_at` — `implementation/envelope.py:17-24`, `store.py:12-13`.
- **§2.5 (opening sentence)** — revise — scoped "nothing reads real wall-clock time" to except the envelope timestamp, and extended the clock's reach to `created_at`/`updated_at` and other server-stamped instants, so §2.5 no longer contradicts §2.2 — `implementation/envelope.py:20`, `routes/catalog.py:226`, `routes/staff.py:110,214`.
- **§2.3 (list ordering)** — revise — logical-clock stamping makes `created_at` ties routine (and the clock can be rewound), so the returned order is the server's creation sequence, coinciding with `created_at` ascending when the clock only moves forward — `implementation/store.py:104,135-136` (`_seq`, `sorted_rows`).
- **§3.7 (rain-alternate ranking)** — insert — residual tie on `created_at` is broken by creation sequence — `implementation/flows.py:259-264`.

### Per-edit pre-edit search log
1. **§2.4 `created_at`** — (a) subject: source of the `created_at` stamp for every minted entity. (b) enumerated: `store.new_entity` (single creation path; used by every create route — grepped `new_entity(` across `routes/*.py`, incl. `catalog.py:118` `new_entity(versioned=False)` for the alignment, which shares the same stamp), `store.stamp_now` → `logical_clock.now`, `logical_clock.DEFAULT_NOW`/`reset` (`app.py:37`), all other instant writers (`routes/catalog.py:226` `published_at`, `routes/staff.py:110` `background_check_started_at`, `:214` `passed_at`/`expires_on`), and `envelope.py:20` (only `real_now` consumer). (c) wording adjustment: said "read from the logical program clock … at the moment of the write" rather than "equals the clock set by the last `/_clock/set_current_utc`", so the startup-default case (`2026-08-01T00:00:00Z`, no clock call yet) is also covered.
2. **§2.4 `updated_at`/`version`** — (a) subject: what "refreshed on every mutation" writes. (b) enumerated: `store.touch` (sole `updated_at` writer; per-request de-dup by `id(entity)`), `store.mark_touched`/`new_entity` (create pre-marks itself), `derive._apply` → `touch` only when a value actually changed (all 9 `sync()` passes), and every direct `touch(...)` callsite in `flows.py` (`revert_booking`, `release_bookings_for_*`, `revoke_awarded_aid`, `cascade_school_suspension`, `lazy_expire_training`) and in `routes/*.py`. (c) wording adjustment: kept the original "refreshed on every mutation … increments by one on every mutation" clause verbatim and only described the *value written*; deliberately did not claim "version increments once per mutating request" or "unchanged derived values still bump version", since `_apply` and the `touch` de-dup make either universal claim false.
3. **§2.2 `api_request_timestamp`** — (a) subject: which clock the envelope timestamp reads. (b) enumerated: `envelope._meta` (used by `object_response`, `array_response`, `error_response` — i.e. every 2xx and every 4xx/5xx path incl. `app.py` error handlers), `store.real_now` (grepped: no other caller). (c) wording adjustment: called it "transport metadata rather than a stored or business value" instead of "not part of any response the tests inspect", and avoided any format claim beyond the existing three-fractional-digit sentence.
4. **§2.5 opening sentence** — (a) subject: the blanket "no real wall-clock time" claim vs. the retained `real_now()`. (b) enumerated: same grep as (3) plus every `logical_clock` consumer — `routes/bookings.py:46` (`start_utc` in past), `derive.in_week`/`logical_clock.in_current_week`/`week_bounds` (weekly counters), `flows.lazy_expire_training:21` (expiry), `routes/catalog.py:226`, `routes/staff.py:110,214`, `routes/ops.py:198` (`set_now`). (c) wording adjustment: added "and other server-stamped instant" rather than naming a closed list, and said *server-stamped* so client-supplied instants (`start_utc`, `end_utc`, `valid_from`, `valid_to`, `season_end_date`), which `store.set_dt` persists as the client's literal string, are not mis-described.
5. **§2.3 list ordering** — (a) subject: the order rows come back in, now that `created_at` collides en masse. (b) enumerated: `store.sorted_rows` (sorts on `_seq` only) and all nine list endpoints that call it — `routes/catalog.py:82,135,169`, `routes/staff.py:180`, `routes/stewardship.py:149`, `routes/bookings.py:102`, `routes/money.py:158`, `routes/ops.py:53,144`; `store.next_seq`/`_seq` assignment in `new_entity`; `schema.paginate` (slices after ordering, so filters and pagination do not reorder). No endpoint sorts by any other key. (c) wording adjustment: described the order as "the server's creation sequence" instead of "`created_at` ascending with ties broken by insertion order", because the clock can be moved backwards — under which the impl still returns creation order, and a ties-only rule would have been a false universal.
6. **§3.7 rain-alternate ranking** — (a) subject: the third/final tie-break of the rain-plan candidate sort. (b) enumerated: `flows.rain_candidates` (the only ranked selection in the codebase; key = `-standard_alignment_count`, `base_fee_cents_per_student`, `created_at`, `_seq`), and grepped `created_at`/`_seq` across `implementation/` to confirm no other selection or comparison reads either field. (c) wording adjustment: appended the residual tie-break to the existing sentence and left the three declared keys verbatim, and phrased it as "creation sequence" to match the same notion introduced in §2.3 rather than inventing a second concept.

Not patched (verified PRD already determines them): the `test_corner_errors` role swap — §4 already restricts `POST /nature-center/aid-applications` to `TeacherContact, BookingCoordinator` and §2.9 puts role check (3) ahead of body FK resolution (7); `routes/money.py:100-101` also already resolves `fund_id` before `booking_id` per §2.6. The `test_helpers/fixtures.py` date-arithmetic fix was a pure fixture bug (invalid `2026-09-31`) with no PRD counterpart. The `test_difficulty_transitive_cascade` `set_clock` insertion is covered by the §2.4/§2.5 clock-stamping edits.

## Step 9: Complete PRD (subagent) — 2026-09-02T04:17:00.000Z

`workspace/PRD_COMPLETED.md` is written. All 31 changes are in-paragraph substitutions on 28 existing lines — no new paragraphs, no new sections, headings byte-identical.

**Source vs completed:** `PRD_FINALIZED.md` 500 lines / 103,537 bytes → `PRD_COMPLETED.md` 500 lines / 107,985 bytes (+4,448 bytes, +4,406 chars). 28 lines rewritten 1:1.

**Counts:** 24 ambiguity-pins, 7 mismatch-revisions.

**Mismatch-revisions**
- §2.9 check 23 — revise — mismatch — lazy training expiry runs only at resource assignment; confirmation performs no sweep and reads credentials as the last assignment left them — `flows.py:144` (only call site of `lazy_expire_training`), absent from `routes/bookings.py:164-206`
- §2.9 check 48 — revise — mismatch — weekly-load total is recomputed with the candidate booking's own contribution excluded — `flows.py:117`
- §3.3 (weekly workload) — revise — mismatch — same exclusion stated at the definition site, so reassignment on a booking the educator already leads is not double-counted — `flows.py:114-119`, `derive.py:93`
- §3.4 (permit consequences) — revise — mismatch — `ACTIVE → SUSPENDED` also runs the booking-release cascade (PRD had reserved it for `LAPSED`) — `routes/stewardship.py:99-101`
- §3.7 (delivery) — revise — mismatch — delivery sets `funding_status` to `INVOICED` from whatever it held, `AID_PENDING` included, leaving a `SUBMITTED` application undecided with its hold still on the pool — `routes/bookings.py:269`
- §3.9 (teacher evaluation) — revise — mismatch — opening a report tests only school scope and the duplicate rule, never `delivery_status`; only submission insists on delivery — `routes/ops.py:100-133`
- §4 endpoint table — revise — mismatch — description no longer says "for a delivered booking" — `routes/ops.py:100`

**Ambiguity-pins**
- §2.1 (Naturalist binding) — insert — on the two animal reads the check reduces to `X-User-ID` naming an existing `Educator` — `security.py:81`
- §2.1 (TeacherContact binding) — insert — on the three catalog reads the check reduces to `X-User-ID` naming an existing `SchoolPartner` — `security.py:62`
- §2.4 — insert — client-supplied instants are stored/echoed verbatim, not re-rendered to 3 fractional digits — `store.py:110`
- §2.4 — insert — every derived value is recomputed from first principles per mutating request; a no-op recompute is not a mutation; `version` advances at most once per request — `derive.py:63-71`, `derive.py:251`, `store.py:88`
- §2.5 — insert — clock response echoes the literal `to_iso8601` string — `routes/ops.py:199`
- §2.6 — insert — `permit_id` (animal registration) → `ERR_PERMIT_NOT_FOUND`; `rain_alternate_for_offering_id` (offering creation) → `ERR_OFFERING_NOT_FOUND` — `routes/stewardship.py:119`, `routes/catalog.py:44`
- §2.9 check 37 — insert — an `alternate_offering_id` naming no offering answers `ERR_RAIN_ALTERNATE_NOT_ELIGIBLE`, not a 404 — `routes/bookings.py:222-229`
- §3.1 (standard alignments) — insert — a claim may be attached whatever state the offering is in — `routes/catalog.py:103-116`
- §3.1 (materials) — insert — material creation is open in any parent state; only publishing tests it — `routes/catalog.py:140-157`
- §3.3 (`CLEAR`) — insert — a missing `CURRICULUM`/`ASSESSED_PASS` record answers `ERR_INVALID_EDUCATOR_STATE` — `routes/staff.py:119-120`
- §3.3 (deactivation) — insert — reverted bookings get `resource_release_reason` `PERMIT_LAPSE`; already-`REQUESTED` bookings keep their existing reason — `flows.py:202-211`
- §3.3 (assessment) — insert — a `score` alongside a `FAIL` is permitted and persisted — `routes/staff.py:208-209`
- §3.4 (retirement) — insert — retirement drives the same booking reversion as a vet hold, reason `PERMIT_LAPSE` — `routes/stewardship.py:181-182`
- §3.6 (assignment) — insert — `null` counts as not supplied, empty string is `ERR_INVALID_REQUEST`, no detach path; all checks run on the merged resource set — `routes/bookings.py:124-158`, `schema.py:50`
- §3.6 (season) — insert — a seasonal educator with no `season_end_date` fails unconditionally — `flows.py:71`
- §3.6 (public contact) — insert — `effective_contact_rule` read before this confirmation's exposure joins the projection — `flows.py:133-138`
- §3.7 (delivery inputs) — insert — the three actuals are integers ≥ 0 with no upper bound; omitted `actual_contact_minutes` stores 0 — `routes/bookings.py:248-266`
- §3.7 (no-show) — insert — `AID_PENDING` also moves to `WRITTEN_OFF`, leaving the `SUBMITTED` application undecided — `routes/bookings.py:294`
- §3.7 (cancellation) — insert — a `SUBMITTED` application is untouched and `funding_status` stays `AID_PENDING` — `routes/bookings.py:320-322`
- §3.8 (aid creation) — insert — funding-dimension test first (`ERR_INVALID_FUNDING_STATE`), delivery second (`ERR_INVALID_BOOKING_STATE`) — `routes/money.py:104-107`
- §3.8 (payments) — insert — `amount_cents` is an integer ≥ 0 with no ceiling of its own — `routes/bookings.py:332`
- §3.9 (manifests) — insert — a manifest opens against any booking regardless of delivery mode/status; `kit_codes` may be empty — `routes/ops.py:24-30`, `schema.py:172`
- §3.9 (`LOAD`) — insert — a non-`CONFIRMED` parent answers `ERR_INVALID_BOOKING_STATE`, after the manifest's own state — `routes/ops.py:70-73`
- §3.9 (submit) — insert — an undelivered parent answers `ERR_INVALID_BOOKING_STATE`, after the report's own state — `routes/ops.py:158-161`

Verified-consistent (no change needed) worth noting: the confirm-time check sequence, both FK resolution orders (`trail→educator→animal`; `fund→booking`), all rounding/pinning in `calc.py`, the OCC placement after state checks, list ordering by creation sequence, and the outcome-rollup field set all already matched impl uniquely.

## Pipeline complete — 2026-09-02T04:17:30.000Z

All 9 steps done. `workspace/PRD_COMPLETED.md` exists on disk. Final test state: 8/8 parallel rounds at 283/283 passing.
