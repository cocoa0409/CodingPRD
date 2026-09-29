# Worklog — task_2471_athletic_field_turf_management_certification

## Step 1: Create task directory — 2026-09-02T21:10:16.445Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2471_athletic_field_turf_management_certification` and its `workspace/` subdirectory. Index 2471 was pre-assigned by the caller; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-02T22:45:00.000Z

The Step 2 subagent wrote all three artifacts to disk but was cut off by an API/server timeout before it could return its own summary, so no verbatim subagent text is available for this entry. Orchestrator decision (recorded per AUTONOMY): rather than re-running the scaffold generator from scratch (which would discard ~155 KB of completed output and risk a second timeout), the orchestrator validated the artifacts directly and accepted them. Validation performed:

- All three files present: `SCAFFOLD.yaml` (3022 lines, 155 KB), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1451 lines), `SCAFFOLD_CORNER_DESIGN.yaml` (1304 lines).
- All three parse cleanly under `yaml.safe_load` — i.e. none is truncated mid-structure.
- Top-level key partition is correct: `SCAFFOLD.yaml` has `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors` and carries **neither** `scaffold_difficulty_design` nor `scaffold_corner_design`; the two design files each have exactly their single expected top-level key.

Content counts: 10 entities, 10 state machines, 2 concurrency rules, 13 calculations, 69 validations, 40 endpoints, 65 errors. Design indices: 19 difficulty instances (queue A), 34 corner instances (queue B).

`complexity_profile`: primary archetype `posture-driven gating`, secondary `temporal windowing`; layers `optimistic_concurrency`, `cascading_side_effects`, `dual_variant_calculation`, `rate_threshold_triggers`; entity topology `flat`; state-machine shape `parallel`; relationship patterns `one_to_many`, `cross_aggregate`, `self_referential`; role model `segregation_of_duties`; consistency `immediate`; `difficulty_level: above-expert` — consistent with the caller's "harder than expert level" instruction, which was passed to Step 2 only and is not forwarded downstream.

## Step 3: Copy shared files — 2026-09-02T23:55:23.422Z

Copied `./INSTRUCTION.md` → `tasks/task_2471_athletic_field_turf_management_certification/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T00:10:00.000Z

Subagent summary (verbatim):

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2471_athletic_field_turf_management_certification/workspace/PRD.md` — **416 lines**, ending cleanly at the final row of the §5 error table (no audit footer). Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced.

## Section list

- §1. Introduction (3 paragraphs)
- §2. Global Specifications & System-Wide Principles — 2.1 User and Role-Based Access Control · 2.2 API Response Structure (verbatim) · 2.3 Pagination · 2.4 Resource Identity, Timestamps and the Logical Clock · 2.5 The Derived Play Posture: One Gate for All Field Use · 2.6 Measurement Precision, Rounding and Monetary Units · 2.7 Optimistic Concurrency on the Field Record · 2.8 Cascade Discipline and Derived-Counter Consistency · 2.9 Two Conserved Quantities: Field Wear and Committed Capital · 2.10 Request Evaluation Order
- §3. Business Logic & Workflows — 3.1 Registering Fields, Tracking Lineage and Closing Them Administratively · 3.2 The Staff Roster and the Maintenance Programme · 3.3 Safety Testing: Impact Attenuation, Goal Anchoring and Striping · 3.4 Remediation Orders and the Unsafe Closure Cascade · 3.5 Allocating Play: Requesting and Confirming a Booking · 3.6 Closing Out a Booking: Three Outcomes, Three Different Ledgers · 3.7 Rest Debt, Recovery Credit, the Condition Index and the Passage of Time · 3.8 Certifying a Field for Sanctioned Competition · 3.9 Capital Budgets, Replacement Planning and Synthetic Disposal
- §4. Endpoint Definitions (40 rows, 4 columns)
- §5. Error Code Catalogue (65 rows, 2 columns)

## Hard Contract Reports

```
Field coverage check:
- entities[].fields: 120 required, 120 present, 0 missing
- endpoints[].request_body: 58 required, 58 present, 0 missing
- endpoints[].query_params: 28 required, 28 present, 0 missing
- clock output fields (current_utc, fields_recomputed, to_iso8601): all present
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 69 checked, 69 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_field_version + ERR_STALE_FIELD_VERSION/412 all named), 0 missing
- state_machines[].transitions: 56 checked across 10 machines, 56 fully expressed, 0 missing
- calculations[]: 13 checked, 13 fully expressed (all 39 named constants embedded in business prose), 0 missing
- validations[] conditions: 69 checked, 69 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 40 endpoints checked, all expressed, 0 missing
- entities[].fields[] structured content: 120 checked, reconstructible from prose, 0 missing
- sibling-branch symmetry: 8 groups checked (3 close-out outcomes, CLOSE/REOPEN, APPROVE/REJECT/RESCIND, APPROVE/RETURN, ACCEPT/REJECT, START/COMPLETE/CANCEL, 4 disposal transitions, 4 →RETIRED transitions), 8 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 958
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Also verified: §2.2 is byte-identical to `section-2.2-response-structure.md`; all 65 `errors[].id`, all state enumeration values across the 10 machines, all enum-typed field values, and all 5 role names appear verbatim.

One scaffold inconsistency worth flagging to the caller: the `Field.certification_status` machine declares a `CERTIFIED → PENDING_REVIEW` transition guarded by `certified_until_utc > current_utc`, which the `field_certification_status` projection (and the packet-submit side-effect text) contradicts — the projection keeps the field `CERTIFIED`. The PRD follows the projection/side-effect reading ("unless a still-valid `APPROVED` packet keeps it `CERTIFIED`"), which is the more specific and twice-stated rule. A second, smaller gap: the `MaintenanceTask` `START` precondition `Field.play_status != RETIRED` has no validation-table entry, so the PRD assigns it the only fitting code, `ERR_FIELD_RETIRED`.

---

Orchestrator truncation guard (per caller instruction): read the tail of `workspace/PRD.md` independently. File is 415 lines and ends on `| ERR_BUDGET_INSUFFICIENT | 422 |` — a complete final row of the §5 error table, i.e. a real section boundary, not a mid-sentence cut. Cross-checked mechanically against `SCAFFOLD.yaml`: all 65 `errors[].id` appear in the PRD (0 missing) and all 40 `endpoints[].path` values appear in the PRD (0 missing). No regeneration needed.

## Step 5: Generate unit tests — 2026-09-03T02:25:00.000Z

Subagent summary (verbatim):

Generation is complete and verified.

## Files written

**Infrastructure** — `/home/ubuntu/github/CodingPRD/tasks/task_2471_athletic_field_turf_management_certification/test_helpers/` (9 files, 3,351 lines): `__init__.py` (barrel of 130 exported names), `api_client.py`, `api_errors.py` (65 ids + HTTP status map registered with the framework), `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`.

**Test suite** — `.../test_suite/` (conftest + 16 modules, 5,370 lines): `test_01`–`test_07` translate queue B; `test_08`–`test_16` translate queue A (`test_13_boundary_precision.py`, `test_14_cross_entity_state_dependency.py`, `test_15_resource_temporal_overlap.py`, `test_16_compensating_invariants.py` were the last four).

## Counts and coverage

- **64 test functions** (69 collected items after parametrize expansion). `pytest --collect-only` clean; `py_compile` clean on every module.
- **Queue A (Difficulty): 19/19 instances translated, 0 skipped** — 2 tests per instance (38 tests), one per rule-module across the 9 rules.
- **Queue B (Corner): 26/26 non-stub instances translated, 0 skipped** — 1 test each. The 8 remaining corner instances carry `excluded_because:` pointing at the depth instance that supersedes them, so they are stubs and correctly untranslated.
- **No skips, no xfail, no placeholders, no mocking.**

## Verification performed

A script parsed every test docstring with `ast` and checked: exactly one `Design:` line per test, always the final line; all 45 distinct tags resolve to real `name:` values in the two design yamls (19 Difficulty + 26 Corner); no tag points at a stub. Every quoted citation was normalised and matched against `workspace/PRD.md` — **0 failures**. Also confirmed no `""""` sequences, no "scaffold"/mock references, and `import test_helpers` resolves.

## PRD-first corrections applied against the design (PRD wins)

- `transitive_cascade`: `condition_index_agronomic` is **56.17**, not the design's 50.00 (safety term clamps to 0.00 at 210.0 g).
- `transitive_cascade`: a deferred sibling's submit returns **`ERR_PLAN_NOT_DRAFT`**, not `ERR_BUDGET_LOCKED` (§3.9 checks the DRAFT precondition first).
- `non_linear_state_machine` / `combinatorial_formula`: task `completed_at_utc` moved to the current clock instant, since §3.2 forbids completion before `started_at_utc`; disposal `/complete` sent with the clock instant so the only violation is the cross-axis guard.
- `cross_entity_state_dependency`: the closing PRACTICE booking moved to 2026-08-06 so it does not trip the 30-minute changeover buffer against the still-SCHEDULED tournament.
- Earlier sessions: `contingency_rate` compared with exact `round(...,4)` rather than the ±0.01-tolerant helper; `ERR_UNSAFE_CLOSURE_IN_FORCE` triggered via `CLOSE_ADMIN`; `REOPEN`→`REOPEN_ADMIN`; `AWAITING_DECISION`→`VERIFICATION_SUBMITTED`.

The isolation constraint held throughout: no sibling task directory and no implementation directory was read, listed, or grepped.

## Step 6: Generate implementation — 2026-09-03T01:35:00.000Z

Subagent summary (verbatim):

The implementation is complete and boots clean.

## Files written
`/home/ubuntu/github/CodingPRD/tasks/task_2471_athletic_field_turf_management_certification/workspace/implementation/`

| File | Lines | Role |
|---|---|---|
| `start.sh` (exec) | 10 | reads `$PORT`, guarded pip install, `exec python3 app.py` in foreground |
| `app.py` | 50 | Flask app, `ApiError`/404/405/500 handlers, binds `0.0.0.0:$PORT` (default 10000) |
| `db.py` | 61 | in-memory `Store` (10 dicts), logical clock seeded to `2026-08-01T00:00:00Z`, id/seq/version helpers |
| `timeutil.py` | 111 | ISO-8601 parsing, `Instant` (echoes client input verbatim), exact Decimal hour/day arithmetic |
| `calc.py` | 291 | all constants + the 13 scaffold calculations, `Decimal` ROUND_HALF_UP throughout |
| `derive.py` | 386 | every derived field recomputed from the store, wear ledger append, unsafe/retire cascades, budget commitment, completeness score, remediation-cascade head |
| `validate.py` | 207 | body shape/unknown-field discipline, typed accessors, pagination |
| `middleware.py` | 132 | 4-step auth, path/body FK resolution, segregation-of-duties |
| `response.py` | 62 | `meta`/`response_type`/`data` envelope, list meta, single Field-version flush |
| `errors.py` | 42 | `ApiError` + shared error constructors |
| `routes/` (12 files) | 1 569 | fields 149, staff 45, maintenance 196, safety 167, remediation 112, bookings 225, ledger 27, certification 209, capital 343, clock 38, common 38, blueprint 6, `__init__` 13 |
| `requirements.txt` | 1 | `Flask>=2.2` |

Total 2 921 lines. **40 endpoints** registered — exactly the scaffold's 40 (39 under `/turf`, plus `POST /_clock/set_current_utc`).

## Boot smoke test
`PORT=18471/18472/18999 bash start.sh` each booted in <1 s and served requests; all three were killed by PID afterwards (I deliberately matched only PIDs whose cwd is this task's dir — a sibling task's servers are running on the host and were left alone). A fresh boot answers with an empty store (a GET returns `ERR_ROLE_IDENTITY_MISMATCH` because not even a staff row exists), confirming zero seeding.

Beyond a boot check I ran five end-to-end scenarios through curl/urllib, all matching the PRD: field registration with `age_years`/`condition_index_agronomic`; assessment supersede + `latest_gmax_mean_value`; FAIL → MANDATORY order → `CLOSED_UNSAFE` → verification submit/accept → back to `RESTRICTED`; void cancelling its source orders and reverting the g-max; packet submit scoring 100.00/74.55 then APPROVE with `certified_until_utc` = clock + 365 d and field `CERTIFIED`; TOURNAMENT confirm gated on certification; 30-minute changeover conflict; PLAYED / RAINED_OUT (exact negative relief, balance back to 0.00) / CANCELLED_LATE ledgers; rest debt decaying with the clock and absorbing a marginal `RECOVERY_CREDIT` entry (12.00 h from AERATION, none when the credit is 0.00); budget lock at 90 % deferring DRAFT siblings and RESCIND releasing capital + un-deferring; diversion-ratio floor; the single cross-axis `/complete` guard retiring the field and cancelling every booking as `CANCELLED_UNSAFE`; freed name reclaimed via `predecessor_field_id`; and the error envelope for pagination, unknown fields, malformed JSON, missing headers, unknown role, unauthorized role, stale field version and SoD breaches.

Two judgement calls worth flagging: `reason_code` is treated as **required on both** closure-order actions (the scaffold lists it without the `?` optional marker and clears it on `REOPEN_ADMIN`), and recovery credit is appended as the **marginal** debt reduction so a second task cannot re-claim an earlier task's credit.

## Step 7: Run tests and iterate — 2026-09-03T02:00:00.000Z

Subagent summary (verbatim):

All 8 parallel rounds pass, 69/69 each.

## Summary

**Iterations run:** 3 sweeps (8 concurrent rounds each, `setsid nohup`, no reaping observed).

Round-by-round progression: 9/69 → 67/69 → **69/69 in all 8 rounds**.

**Tests deleted:** none (no whole test failed STEP 1a/1b outright).

**Assertions removed under STEP 1c (partial-coverage split):**
- `test_suite/test_01_field_registration_and_inventory.py::test_registration_derives_age_warranty_and_zeroed_counters` — dropped `assert_instant_equals(field["created_at"]/["updated_at"], DEFAULT_CLOCK_UTC)`. Category: **source-of-value silence** (a default/derivation-source silence). PRD §2.4 describes `created_at` only as "an ISO 8601 UTC timestamp with three fractional digits recording creation" and `updated_at` as "refreshed on every mutation" — it never names the logical clock as their source, while it *does* name it explicitly for every business timestamp (`effective_at_utc` "the logical-clock instant at which it was appended", `opened_at_utc`, `started_at_utc`, `confirmed_at_utc`, `closed_at_utc`, …). Two PRD-faithful readings exist: (a) `created_at` is real-time audit metadata, the logical clock being reserved for the timestamps PRD explicitly binds to it; (b) `created_at` is the logical instant, on the strength of "The server does not read the operating system clock for business decisions". Reading (b) additionally makes PRD's own `created_at` tie-breakers (§2.9 ledger replay "then `created_at` ascending"; §3.3 g-max fallback "then `created_at` descending") degenerate, since same-request rows would share one instant. Scaffold rule that drove it: `Corner/entities/field_creation_returns_derived_age_warranty_and_zeroed_counters`. Everything else in the test (age 8.30, `EXPIRED` warranty, zeroed counters, index 71.17, `version == 1`) was kept.
- `test_suite/test_02_staff_and_maintenance_task_records.py::test_ledger_entry_is_immutable_and_carries_no_version` — dropped `assert_instant_equals(entry["created_at"], "2026-08-02T20:30:00Z")` for the same reason; the sibling `effective_at_utc` assertion (which PRD *does* pin to the logical clock) was kept, as were the wear/rest/balance and no-`version`/no-`updated_at` assertions. Scaffold rule: `Corner/entities/usage_ledger_entry_is_immutable_and_carries_no_version`.

These were the only two `created_at`-value assertions in the whole suite (11 other `created_at` mentions are docstring quotes about ordering), confirming the assertion was incidental over-specification rather than a suite-wide rule.

**Fixes applied to `test_helpers/`:** none needed.

**Fixes applied to `implementation/`** (root cause of 60 of the 60 first-round failures — a single shared setup error, exactly the triage hint's signature):
- `workspace/implementation/timeutil.py` — added `parse_iso_date()`, accepting a bare `YYYY-MM-DD` (read as midnight UTC) as well as a full instant.
- `workspace/implementation/validate.py` — added `Body.date()` using it, erroring as `ERR_INVALID_REQUEST` on anything else.
- `workspace/implementation/routes/fields.py::register_field` — `installed_on_date` and `warranty_expires_on` now read via `body.date()` instead of `body.instant()`. PRD names these two inputs `installed_on_date` / `warranty_expires_on` while every other temporal field is `*_utc`, and §2.4 scopes "All instants in request bodies and responses are ISO 8601 UTC" to *instants*; the implementation was rejecting the calendar-date form with `ERR_INVALID_REQUEST`, so no field could be registered at all. `_utc` fields remain strictly instant-only, so no error-path assertion was loosened.

---

Orchestrator independent verification of the sweep (per known failure mode where a Step 7 agent reports a clean sweep without leaving artifacts): confirmed on disk that `workspace/implementation/results.{1..8}.json` all exist (mtime 2026-09-03 01:58:40) and each reports `passed == total == 69`; `workspace/sweep.done` present; `workspace/sweep.log` contains exactly 8 `Results: 69/69 passed` lines and **zero** occurrences of `Terminated` (so no SIGTERM reaping — the `setsid nohup` wrapper held). `find` over `test_suite/`, `test_helpers/`, and `workspace/implementation/` shows **no** source file modified after `results.1.json`, so the passing sweep reflects the current tree and not a pre-fix state. Step 7 accepted.

Step 8 is NOT skipped: Step 7 applied 3 `implementation/` fixes and 2 STEP-1c assertion removals, so PRD silences exist to patch.

## Step 8: Finalize PRD — 2026-09-03T02:20:00.000Z

Subagent summary (verbatim):

Done. `PRD_FINALIZED.md` written with two edits, both inside §2.4.

## Line counts
- `PRD.md`: 415 lines / 13,416 words
- `PRD_FINALIZED.md`: 415 lines / 13,617 words
- Line-count delta: **0%** (2 of 415 lines revised, 0.48% of lines touched); word delta +201 (+1.50%)

## Changes
- **§2.4 (common properties paragraph) — insert** — pinned `created_at`/`updated_at` (and a `UsageLedgerEntry`'s `created_at`) as real-time wall-clock audit metadata rather than logical-clock instants, and noted that same-request rows are stamped in non-decreasing write order so the §2.9/§3.3 `created_at` tie-breakers stay meaningful — `implementation/db.py:50-51,57` (`Instant.now()` in `common_fields`/`bump`), `implementation/derive.py:225,241` (ledger entry), `implementation/timeutil.py:102-104` (`Instant.now` = `datetime.now(timezone.utc)`, `fmt_ms`).
- **§2.4 (instants/logical-clock paragraph) — revise** — carved `installed_on_date` and `warranty_expires_on` out of the blanket "all instants are ISO 8601 UTC" rule: both accept a bare `YYYY-MM-DD` read as midnight UTC or a full instant, are echoed back in the supplied form, and reject any other shape with `ERR_INVALID_REQUEST`, while every other temporal input (`*_utc`, `to_iso8601`) stays instant-only — `implementation/validate.py:123-136` (`Body.date`), `implementation/timeutil.py:20-39` (`parse_iso_date`), `implementation/routes/fields.py:32,36`.

## Pre-edit search log

**Edit 1 — subject: the source of `created_at` / `updated_at` values (and their ordering role).**
- (b) Paths enumerated (grepped `Instant.now|created_at|_seq|common_fields|bump(` across all of `implementation/`, then read each hit): `db.py:48-51` `common_fields()`; `db.py:54-57` `bump()`; `db.py:60-61` `by_creation()`; `derive.py:225,241-242` ledger append; `derive.py:53` `live_impact_assessments` (§3.3 fallback ordering); `derive.py:61` `field_ledger` (§2.9 replay ordering); `derive.py:72-74` `governing_rest_entry`; `derive.py:268,277` unsafe/retire cascade ordering; `routes/clock.py:24,33-34` (clock-advance `by_creation` + snapshot-gated `bump`); `response.py:16-20` (`api_request_timestamp`, also real time); every `common_fields()`/`bump()` callsite in `routes/{fields,staff,maintenance,safety,remediation,bookings,certification,capital}.py`. Confirmed `created_at` is used in business logic *only* as a sort key, never compared against the logical clock.
- (c) Adjustment: my first draft said same-request rows "receive distinct, increasing `created_at` values". That would be a false universal — `fmt_ms` renders only three fractional digits, so two rows appended in one request can emit an identical string even though the internal microsecond value and the `_seq` fallback order them. Reworded to "do not decrease in write order … resolve any remaining tie in favour of the order in which the server wrote the rows", which is true of both the `created_at.dt` comparison and the `_seq` final tiebreaker at every one of the five sort sites, and leaves the rendered-string collision case undetermined rather than mis-described.

**Edit 2 — subject: accepted form of date-shaped temporal request inputs.**
- (b) Paths enumerated (grepped `installed_on_date|warranty_expires_on|body.date|parse_iso_date|body.instant` across `implementation/`): `validate.py:123-136` `Body.date` (non-string and unparseable both → `ERR_INVALID_REQUEST`; returns `Instant(dt, value.strip())`, hence the raw echo); `timeutil.py:20-39` `parse_iso_date` (bare date → midnight UTC, else delegates to `parse_iso`); `routes/fields.py:32,36,69,73` (the only two `body.date` callsites; values stored verbatim and never rewritten afterwards); `response.py:23-25` `jsonable` (emits `Instant.raw`, so the supplied form is echoed); consumers `derive.py:112-114` → `calc.py:156-166` (`field_age_years` divides days-since-midnight by 365.25; `field_warranty_status` uses strict `<`, so midnight-UTC reading makes the §3.1 "boundary belongs to expiry" rule determinate); all remaining temporal inputs, which use `body.instant` — `routes/maintenance.py`, `routes/safety.py`, `routes/bookings.py`, `routes/capital.py`, and `routes/clock.py:16` (`to_iso8601`).
- (c) Adjustment: my first draft called these two "the only temporal fields not named `*_utc`". `routes/clock.py:16` falsifies that — `to_iso8601` also lacks the suffix yet is strictly instant-only. Dropped the universal claim and named the exception set explicitly instead ("`installed_on_date` and `warranty_expires_on`"), then closed with an inclusive statement that names `to_iso8601` alongside the `*_utc` fields as instant-only, so the clock route is described correctly rather than swept into the carve-out.

---

Orchestrator verification: `diff PRD.md PRD_FINALIZED.md` confirms exactly two changed lines (86 and 88), both in §2.4, both traceable to `<step_7_diff>` items (the `created_at` STEP-1c removals and the `installed_on_date`/`warranty_expires_on` date-parsing implementation fix). No new sections; file still 415 lines and still ends at the final §5 error-table row.

## Step 9: Complete PRD — 2026-09-03T02:42:00.000Z

Subagent summary (verbatim):

Done. `PRD_COMPLETED.md` is complete and ends at the final `ERR_BUDGET_INSUFFICIENT` row.

## Counts

- **PRD_FINALIZED.md**: 415 lines / 98,786 chars → **PRD_COMPLETED.md**: 416 lines / 107,611 chars (**+1 line, +8,825 chars**)
- 31 changed passages: **5 mismatch-revisions**, **26 ambiguity-pins**. No new sections; one new bullet added to the existing §2.2 bullet list.

## Mismatch-revisions

- §2.8 — revise — mismatch — `usage_hours_ytd` sums bookings whose status is `PLAYED` **or `RAINED_OUT`** (PRD said `PLAYED` only), excluding `CANCELLED_LATE`/`CANCELLED_UNSAFE` — `derive.py:138`
- §2.8 — revise — mismatch — field registration is **not** a `Field.version` bump: a registered field is returned at `version` 1 — `fields.py:97-99`
- §2.10 — revise — mismatch — retirement guard also covers **certification-packet submission** and the maintenance `START` action; enumerated the operations that do *not* consult it — `certification.py:105-108`, `maintenance.py:150`
- §3.3 — revise — mismatch — a back-dated recording supersedes nothing, so a field **can** carry more than one live assessment per type (PRD asserted "at most one") — `safety.py:105-112`
- §3.3 — revise — mismatch — `latest_gmax_mean_value` is derived on every field recompute from the greatest-`assessed_at_utc` still-`RECORDED` impact test, not written by the supersession — `derive.py:152-154`

## Ambiguity-pins

- §2.1 — insert — whitespace-only header = missing; values never trimmed for role/id matching — `middleware.py:18-30`
- §2.2 — insert — `has_more` = `offset` + rows returned < `total_count` — `response.py:51`
- §2.2 — insert — out-of-catalogue `ERR_NOT_FOUND` 404 / `ERR_METHOD_NOT_ALLOWED` 405 — `app.py:27-34`
- §2.3 — insert — filters are exact case-sensitive string match; booleans accept `true`/`false` any case; null values never match — `common.py:10-20`
- §2.4 — insert — client instants echoed byte-for-byte incl. non-`Z` offsets; clock-stamped instants echo the clock's form; server-computed instants rendered canonically (3 fractional digits only when non-zero) — `timeutil.py:75-99`
- §2.4 — insert — `fields_recomputed` counts change in a named 16-value derived set; clock `data` is a two-key non-resource object — `clock.py:25-38`, `derive.py:87-95`
- §2.6 — insert — numeric range breaches are `ERR_INVALID_REQUEST`, not the pairing error; `infill_depth_mm`/`nitrogen_lb_per_1000_sq_ft` stored rounded to own precision — `fields.py:37-74`, `maintenance.py:37-98`
- §2.10 — insert — SoD against a null reference passes vacuously — `middleware.py:129`
- §2.10 — insert — absent/empty body = `{}`; non-object/unparseable = `ERR_INVALID_REQUEST`; unknown-field sweep precedes missing-field sweep; explicit `null` = absence; `expected_field_version` integer, unranged — `validate.py:16-42`
- §3.1 — insert — no clock constraint on `installed_on_date`/`warranty_expires_on`; name uniqueness is exact case-sensitive — `fields.py:36-48`
- §3.1 — insert — `reason_code` 1–200 chars, required on `REOPEN_ADMIN` too and discarded there — `fields.py:119-146`
- §3.2 — insert — non-array `roles` = `ERR_INVALID_REQUEST`, non-string member = `ERR_INVALID_ROLE_SET`; bad `employment_status` = `ERR_INVALID_REQUEST` — `staff.py:20-29`
- §3.2 — insert — `START` retirement guard precedes the status precondition — `maintenance.py:150-154`
- §3.2 — insert — the three `completed_at_utc` faults are `ERR_INVALID_REQUEST`, two before and one after the status precondition; `cancellation_reason` 1–500 required on `CANCEL` — `maintenance.py:132-165`
- §3.3 — insert — non-numeric reading = `ERR_ASSESSMENT_METRIC_MISMATCH`; non-array or out-of-range = `ERR_INVALID_REQUEST`; readings rounded to 1dp before range test and mean — `safety.py:55-65`
- §3.3 — insert — superseded assessment's own `version` increments by 1 — `safety.py:112`
- §3.3 — insert — `void_reason` required, 1–500 chars — `safety.py:137`
- §3.4 — insert — cascade-cancelled bookings bump their own `version` and keep `outcome` null — `derive.py:252-253`
- §3.4 — insert — `remediation_notes` required, 1–2000 chars, all three submission fields required — `remediation.py:43-48`
- §3.4 — insert — verification `decision_notes` validated (1–2000) then dropped; the order has no such attribute — `remediation.py:85`
- §3.5 — insert — confirm accepts no body keys at all — `bookings.py:117`
- §3.6 — insert — `actual_duration_hours` ≥ 0.00 unbounded above and stored to 2dp; `actual_participant_count` integer ≥ 0 unbounded; `status` = `outcome` — `bookings.py:156-194`
- §3.6 — insert — the three outcome-consistency breaches are `ERR_INVALID_REQUEST`, evaluated after the status and window gates — `bookings.py:172-180`
- §3.6 — insert — every ledger entry always carries `rest_requirement_hours`/`rest_credit_hours` as 2dp numbers defaulting 0.00; `rest_window_end_utc` non-null only on `PLAY_WEAR`; the seven exact `note` strings — `derive.py:235-237`, `bookings.py:207-222`, `maintenance.py:180`, `derive.py:385`, `capital.py:341`
- §3.8 — insert — packet `decision_notes` 1–2000, null when omitted — `certification.py:152`
- §3.8 — insert — a superseded prior `APPROVED` packet's own `version` increments by 1 — `certification.py:194`
- §3.9 — insert — plan `decision_notes` 1–2000, null when omitted — `capital.py:191`
- §3.9 — insert — approval bumps `CapitalBudget.version` and each deferred sibling's `version`, and leaves `Field.version` alone — `capital.py:232-244`
- §3.9 — insert — rescission bumps budget `version`; `REJECT` leaves it untouched; reinstated deferred plans visited `created_at` ascending, each bumping `version` — `capital.py:267-275`
- §3.9 — insert — `manifest_reference` 1–60, `disposal_facility_name` 1–120, tonnages ≥ 0.00 stored to 2dp — `capital.py:287-311`
- §3.9 — insert — future `completed_at_utc` = `ERR_INVALID_REQUEST`, tested before the cross-axis guard; retirement cascade visits `window_start_utc` asc then `created_at` asc — `derive.py:277`, `capital.py:325-327`

---

Orchestrator verification (truncation + integrity): `workspace/PRD_COMPLETED.md` is 416 lines / 107,611 chars and ends at `| ERR_BUDGET_INSUFFICIENT | 422 |` — the real final row of the §5 error table, not a mid-sentence cut. All 65 scaffold `errors[].id` and all 40 scaffold `endpoints[].path` are still present (0 missing each). `diff` of the heading lines against `PRD_FINALIZED.md` is empty, confirming no section was added, removed, or renamed; 61 diff lines total, i.e. edits are in-paragraph revisions as required. `find` confirms no file under `workspace/implementation/` was modified after `results.1.json`, so the verified 8/8 × 69/69 sweep from Step 7 still describes the shipped implementation — Steps 8 and 9 touched only the PRD documents.

**Pipeline complete.** Step 9 wrote `workspace/PRD_COMPLETED.md`; all nine steps are done.
