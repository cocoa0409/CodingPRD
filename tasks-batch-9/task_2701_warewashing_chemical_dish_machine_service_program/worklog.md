# Worklog — task_2701_warewashing_chemical_dish_machine_service_program

## Step 1: Create task directory — 2026-09-04T08:46:00.476Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2701_warewashing_chemical_dish_machine_service_program` and its `workspace/` subdirectory. Index 2701 was pre-assigned by the orchestrator invocation (no auto-allocation scan performed, per instruction — concurrent pipelines on this host).

## Step 2: Generate Scaffold — 2026-09-04T10:54:34.493Z

All three scaffold artifacts are complete and the mandated lint passes.

**Files** (in `/home/ubuntu/github/CodingPRD/tasks/task_2701_warewashing_chemical_dish_machine_service_program/`):
- `SCAFFOLD.yaml` — 3125 lines / 167 KB; §1.0–§1.7 only (16 entities, 63 endpoints, 9 state machines, 3 concurrency rules, 39 error codes, 5 roles). No `scaffold_difficulty_design` / `scaffold_corner_design` keys.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1985 lines / 145 KB; single top-level key, 18 instances (2 per each of the nine §0.5 rules).
- `SCAFFOLD_CORNER_DESIGN.yaml` — 5260 lines / 355 KB; single top-level key, 86 instances across all nine guide sections: entities 12, state_machines 17, calculations 15, validations 20, endpoints 6, errors 5, rbac 4, cross_cutting_complexity_layers 6, consistency_model 1 (61 full `test_recipe` instances + 25 `excluded_because` stubs, every stub citing a §1.8 instance that exists by name).

**Lint verdict (verbatim):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           .../SCAFFOLD.yaml
  Difficulty design:  .../SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      .../SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    63
  §1.1 entities declared:     16
  §1.8 instances scanned:     18
  §1.9 instances scanned:     61
  Calls scanned (§1.8+§1.9):  1186

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Key findings from the final pass** (bugs found and fixed while writing §1.9, each caught by cross-checking the recipe against `SCAFFOLD.yaml` rather than by the linter, which does not check asserted values):
- HTTP codes asserted in prose had drifted from the catalog: `ERR_RENEWAL_WINDOW_NOT_OPEN` and `ERR_NO_ELIGIBLE_TECHNICIAN` are 409 (not 422) and `ERR_UNKNOWN_REFERENCE` is 422 (not 404). A regex sweep of both design files against the §1.6 catalog now reports zero mismatches.
- `opened_reason` is an enum `{SUSPECTED_THEFT, SUSPECTED_DILUTION, DISPENSER_FAULT}`; one earlier instance passed free text.
- `MachinePlacement` has no `open_ticket_count` (that field lives on `Site`); one capture was reading a non-existent field.
- Early-termination fee for a same-day termination of a 36-month term is 493333, not 480000: `remaining_months = ceil(1096/30) = 37`, so `max(444000, round(480000 × 37/36))` picks the equipment variant.
- Delivery tier arithmetic: 10 units of a 9600-cent product is 91200 (9120 × 10) and 25 units is 211200 (8448 × 25) — per-unit rounding before multiplying.

Integrity checks beyond the linter, all passing: name uniqueness across the union of both design files (104 names, 0 duplicates), every `excluded_because.difficulty_instance` resolving into `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, and every `grounds` reference of the form `entities.X.fields.Y` / `validations.N` / `calculations.N` / `errors[…]` / `endpoints[…]` / `roles.R.…` resolving into `SCAFFOLD.yaml` (0 suspect references). No sibling task directory was read at any point.

## Step 3: Copy Shared Files — 2026-09-04T10:54:55.275Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T11:11:45.243Z

PRD generation is complete.

**Output:** `workspace/PRD.md` — **521 lines / 114,758 bytes**, written in 9 incremental appends (no truncation). Last section heading is `## 5. Error Code Catalogue`; the file ends on the final table row `| ERR_READING_BEFORE_INSTALL | 422 |`, a genuine section boundary, with no audit footer.

**Structure:** §1 Introduction; §2 with twelve subsections (2.1 actors/RBAC, 2.2 verbatim response block, 2.3 pagination, 2.4 logical clock + three-part sweep, 2.5 identity/version semantics, 2.6 money & pinned rounding, 2.7 OCC, 2.8 the 15-rung rule ladder, 2.9 addressing, 2.10 conserved ledgers & cascades, 2.11 segregation of duties, 2.12 half-open windows); §3 with nine workflow subsections (catalogs, agreement lifecycle, placements, dispensers/telemetry/health axis, ticket scoring & dispatch, service visit incl. the two adjudication branches, deliveries & variance reviews, investigation cases, the two computed reads); §4 endpoint table (4 columns, all 63 endpoints); §5 error table (2 columns, all 38 errors).

**Hard Contract reports**

```
Field coverage check:
- entities[].fields: 146 required, 146 present, 0 missing
- endpoints[].request_body: 90 required, 90 present, 0 missing
- endpoints[].query_params: 36 required, 36 present, 0 missing
- endpoints[].path_params: 16 required, 16 present, 0 missing
Status: PASS
```
(Two passes run; second pass additionally verified all 96 enum members, all 5 role names, all 38 error ids, and every computed-read output key of the three dict-output endpoints — 0 missing.)

```
Rule coverage check:
- validations[] with priority: 38 checked, 38 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_<parent>_version + error_id all named), 0 missing
- state_machines[].transitions: 51 checked, 51 fully expressed, 0 missing
- calculations[]: 13 checked, 13 fully expressed (incl. all 6 variant pairs), 0 missing
- validations[] conditions: 38 checked, 38 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 35 endpoints with side effects + 29 distinct applies_to scopes checked, all expressed, 0 missing
- entities[].fields[] structured content: 146 checked, 146 reconstructible from prose, 0 missing
- sibling-branch symmetry: 12 groups checked, 12 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 1150
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional verification: §2.2 is byte-identical to `section-2.2-response-structure.md`; every inline `ERR_* (nnn)` status claim matches the scaffold and the §5 table; no pseudocode operators and no fuzzy quantifiers survive anywhere in the prose.

**Scaffold inconsistencies resolved (worth flagging to the test generator):**
1. `asset_tag` uniqueness — the entity field says "placement_status != RETRIEVED" while `validations[asset_tag_unique]` and the `ERR_ASSET_TAG_TAKEN` condition both say "not CANCELLED". Written as **not `CANCELLED`** (2-of-3).
2. Dispenser create input — the field description mentions `initial_dose_ml_per_rack`, the endpoint input list says `calibrated_dose_ml_per_rack`. Used the endpoint name only.
3. Renewal window — `validations[renewal_window_open]` guards the renewal endpoint generally, but the `RENEWAL_PENDING → ACTIVE` transition declares no window precondition. Written so the window test binds when renewing from `ACTIVE`, with the reason a `RENEWAL_PENDING` agreement is necessarily inside its window stated explicitly.
4. `evidence_item_count >= 2` on `SUBSTANTIATE` carries no explicit `error_id` in the scaffold; expressed as a failed transition precondition reporting `ERR_INVALID_STATE_TRANSITION`.

Both withheld design files were never opened, grepped or referenced, and no sibling task directory was read.

**Orchestrator truncation check:** `wc -l` = 521; `tail -20` shows the error catalogue table running to its last row; `grep '^## '` shows all five top-level sections present. PRD is NOT truncated — no regeneration needed.

## Step 5: Generate Unit Tests — 2026-09-04T12:36:08.950Z

Queue B is finished; the whole suite is complete and verified.

## What was added this turn
`test_suite/test_18_corner_consistency.py` (111 lines, 1 test) — the last non-stub corner instance, `Corner/consistency_model/one_ticket_write_exposes_its_whole_cascade_in_the_same_response`: a `MACHINE_DOWN` customer report filed at clock `2026-08-01T12:00:00Z` on an `INSTALLED`/`UP` placement of a `STANDARD` site must return `priority_score == 400` (symptom base only — health and posture are read *before* the insert) and `response_deadline_at == "2026-08-01T16:00:00Z"` (240-minute band), while the very next reads show the placement `DOWN` with `open_alert_count == 0`, the site at `open_ticket_count == 1` / `service_posture == ELEVATED`, and a re-read of the ticket returning the identical stamped score and deadline.

## Three C1 verbatim-citation defects found and fixed
A whole-suite grep of every `PRD §x.y: "…"` docstring quotation against `workspace/PRD.md` caught three pre-existing violations (all now pass):
- `test_01_dual_basis_variance_and_sustainability.py:134` — an em dash had been typed as `-` (`creation dose - the` → `creation dose — the`).
- `test_11_corner_state_machines.py:90` — the `term_end_date` quote stopped mid-sentence at `does not exist there."`; extended with the PRD's own `— a term of one month starting on 31 January ends on 28 February in a common year.`
- `test_17_corner_cross_cutting.py:187` — the §3.6 quote stopped at `re-derived."` where the PRD continues with `:`; extended through the full `DOWN → UP` / `DOWN → DEGRADED` sentence.

## Final state (all task-root paths, nothing under `workspace/`)
`test_helpers/` — 9 files, 2857 lines: `__init__.py` 29, `api_client.py` 462, `api_errors.py` 173, `assertions.py` 380, `constants.py` 179, `factories.py` 485, `fixtures.py` 722, `test_users.py` 100, `types.py` 327.

`test_suite/` — `conftest.py` 90; `test_01` 311/4, `test_02` 262/4, `test_03` 363/5, `test_04` 323/5, `test_05` 253/4, `test_06` 261/4 (one `parametrize` → 8 cases), `test_07` 275/4, `test_08` 284/4, `test_09` 286/4, `test_10` 535/12, `test_11` 690/10, `test_12` 783/8, `test_13` 994/15, `test_14` 469/6, `test_15` 189/2, `test_16` 320/4, `test_17` 268/3, `test_18` 111/1 (lines/test functions).

## Verification run over the entire suite
- Every file `ast.parse`-clean and importable; `pytest --collect-only` collects 103 cases from 99 test functions (the +4 is the single parametrized test in `test_06`).
- No unused imports in any emitted file.
- Design coverage is exact: 18/18 difficulty instances (histogram — sixteen with 2 tests, two with 3) and **61/61 non-stub corner instances** (86 named instances minus 25 `excluded_because:` stubs). No orphan tags, no duplicate corner tags, no dual-tagged or untagged tests, every `Design:` line last in its docstring.
- Every PRD citation in all 99 docstrings now survives a literal whitespace-normalised match against `workspace/PRD.md`.
- `workspace/` contains only `INSTRUCTION.md`, `PRD.md`, `implementation/` — no stray `test_helpers/`/`test_suite/`; `implementation/` was never read or written.

One design-vs-PRD note worth carrying forward: this last instance's only PRD grounding for a customer report driving the machine to `DOWN` is the §3.5 clause "…because that request's own drive of the machine to `DOWN` is applied only after the score has been stamped" — there is no separate cascade paragraph for the customer-report route, so the implementation must infer that drive from the scoring paragraph alone.

## Step 6: Generate Implementation — 2026-09-04T12:36:08.950Z

Implementation complete and verified.

## What was done

Finished the remaining three route modules and validated the whole service end to end.

**Completed this session** (all under `workspace/implementation/`):

- `routes/visits.py` (423 lines) — added the adjudication endpoint (`/verify`, both disjoint branches: verified applies PASS/ADJUSTED records, restamps dispenser dose/`prior_dose`/`dose_effective_at`/`last_calibrated_at`/`last_drift_pct`, resets `cycles_since_calibration`, clears `EFFICACY_FAILURE` lockouts, and on `repair_confirmed` resolves alerts *then* re-derives health; rejected applies nothing, requeues the ticket and raises `quality_flag_count`) and the nested immutable `POST /service-visits/{id}/calibration-records` write with the full rung ladder 404 → owner → shape → ref 422 → `expected_dispenser_version` 412 → `ERR_VISIT_NOT_IN_PROGRESS` → `ERR_SANITIZER_LOCKOUT_ACTIVE` → `ERR_DISPENSER_PLACEMENT_MISMATCH` → contact-seconds shape → drift/efficacy/verdict → `ERR_ADJUSTED_DOSE_REQUIRED`.
- `routes/deliveries.py` (130 lines) — priced drop with `expected_site_version` 412, `ERR_PRODUCT_NOT_ON_AGREEMENT`, credit hold reported last, and the half-open closed-period void guard.
- `routes/reviews.py` (345 lines) — usage-variance reviews (create with the five frozen figures, publish with the pinned four-check order, direct close) plus investigation cases (open/escalate, cumulative evidence submit, adjudicate with `RETURN`/`SUBSTANTIATE`/`DISMISS`, chargeback from frozen figures, cascade gamma).

Also fixed a dead `_staged` branch in the rejected verify path and a stale `review["review_status"]` key (the field is `status`).

## Verification

- **Endpoint parity**: extracted all 63 rows from the PRD §4 table and diffed against `app.url_map` — exact match, zero diff.
- **Boot**: `bash start.sh` on port 51037 (verified free first, killed only by recorded PID/port — no broad pkill) boots cleanly and answers requests; store is empty on every fresh boot; no file/SQLite/JSON persistence anywhere; no tracebacks or 500s in the server log.
- **Two smoke suites, both 0 failures on a fresh boot** (~110 assertions total): full happy path (agreement → placement → install → dispenser → telemetry alerts → ticket → dispatch → visit → calibration → verify → delivery → review → case → chargeback → sustainability report → dossier → clock sweep with cascade alpha), plus a negative/edge suite (all 15 ladder rungs exercised, dedup, WARNING vs CRITICAL health propagation, rejected-visit compensation, follow-up visit, retrieval, ledger release, renewal window, early-termination fee, CustomerContact scoping).

Three PRD figures were hand-checked against the implementation output and matched: net program cost `119974` (tier fixed pre-credit, credit `66` capped), early-termination fee `78000` (13 remaining months × 60% beats the zero equipment view once the machine is `RETRIEVED`), and delivery `88000` cents at 25 units (per-container rounding before multiply).

## Notes for the caller

- Decimal-valued fields (`concentration_tolerance_pct`, `drift_pct`, `water_saved_l`, doses…) serialize as JSON **numbers**, integral when exact (`10`, not `"10.00"`), and decimal inputs must arrive as JSON numbers — a fixture sending `"2.50"` as a string gets `ERR_INVALID_REQUEST`, which matches §2.8 rung 4 ("every field must match its declared JSON type").
- List endpoints put the array directly in `data` with pagination in `meta`; errors put `error_id` in `data`.
- Total: 4340 lines across 20 files (largest module 423 lines).

**Orchestrator note:** Steps 5 and 6 were launched concurrently in a single assistant message, so the impl generator started before `test_suite/` existed — physical isolation confirmed by the directory listing above (`test_helpers/`, `test_suite/` at task root only, nothing under `workspace/`).

## Step 7 — parallel stability sweep (diagnostic iteration loop)

Two 8-round `setsid nohup` sweeps, `--isolation per-test-server`, no `--api-url`
(runner claims a free port per round). Diagnosed only from per-round
`results.$i.json`; `sweep.log` ignored as spliced.

- Sweep 1: **74 / 103** in all 8 rounds, byte-identical failure sets — zero
  flakiness, so all 29 failures were real defects.
- Sweep 2: **103 / 103** in all 8 rounds, union of non-passed tests = 0.

Tests deleted: **none**. Every failing test survived STEP 1a (verbatim PRD
coverage) and STEP 1b (unique derivability), so all 29 resolved as STEP 2 test
fixes or STEP 3 implementation fixes.

### test_helpers/
- `assertions.py`: added `_canonical_instant` / `assert_instant_equals`, a
  precision-independent ISO 8601 comparator. The PRD pins fractional digits for
  exactly three fields (`api_request_timestamp` and `created_at` at three digits,
  `response_deadline_at` at whole seconds); every other instant is only "an ISO
  8601 UTC timestamp", so trailing-zero form is not a testable rule.

### test_suite/
- 11 sites converted to `assert_instant_equals` (`dose_effective_at`,
  `retrieved_at` x4, `scheduled_start_at`, `period_start`, `updated_at`,
  `reading_at`, `last_calibrated_at`, `installed_at`). `response_deadline_at`
  raw-string assertions deliberately left exact — PRD §3.5 pins whole seconds.
- 14 call sites swapped `PLATFORM_ADMIN_HEADERS` → `ACCOUNT_MANAGER_HEADERS` on
  reads the PRD §4 table does not grant PlatformAdmin. `test_16_corner_rbac.py`
  left alone; its 4 PlatformAdmin calls are intentional negative 403 probes.
- `test_12`: 3 field-name typos `status` → `case_status` on InvestigationCase.
- `test_13`: renewal-window clock moved to `2026-08-26T00:00:00Z`, where §2.4's
  floor arithmetic yields exactly 6 whole days remaining against 5 notice days.
- `test_14`: added the §3.6-required calibration record before submission.

### implementation/
- `routes/visits.py` `submit()`: reports §2.8 rung 9's generic
  `ERR_INVALID_STATE_TRANSITION`. `ERR_VISIT_NOT_IN_PROGRESS` is reserved by
  §3.6 for the nested calibration-record write alone.
- `services/derive.py` `create_ticket()`: applies the §3.5 drive of the machine
  to `DOWN` on a `CUSTOMER_REPORT` / `MACHINE_DOWN` ticket, after the priority
  score has been stamped against the pre-request health.

Storage remains in-memory dicts only (`db.py` `reset()` rebuilds every table);
no seeding at startup, so a `start.sh` reboot wipes every byte.

## Step 7: Run Tests and Iterate — 2026-09-04T13:04:00.000Z

(The Step 7 subagent self-appended the narrative section above; the block below is its returned summary, verbatim, as the skill's format requires.)

## Summary

**Exit condition met: all 8 sweep rounds green at 103/103.**

### Iterations run: 2

| Sweep | Result |
|---|---|
| 1 | **74 / 103** in all 8 rounds, byte-identical failure sets — zero flakiness, so all 29 failures were genuine defects, not load artifacts |
| 2 | **103 / 103** in all 8 rounds, union of non-passed tests across all rounds = **0** |

Per-round evidence (re-verified from the per-round JSON, not `sweep.log`):

```
round 1  passed=103 failed=0 errors=0 total=103  non-passed=0
round 2  passed=103 failed=0 errors=0 total=103  non-passed=0
round 3  passed=103 failed=0 errors=0 total=103  non-passed=0
round 4  passed=103 failed=0 errors=0 total=103  non-passed=0
round 5  passed=103 failed=0 errors=0 total=103  non-passed=0
round 6  passed=103 failed=0 errors=0 total=103  non-passed=0
round 7  passed=103 failed=0 errors=0 total=103  non-passed=0
round 8  passed=103 failed=0 errors=0 total=103  non-passed=0
```

103 = 99 top-level test functions with one `@pytest.mark.parametrize` in `test_06_boundary_precision.py` expanding ×5.

### Tests deleted: NONE
Every failing test survived STEP 1a (verbatim PRD coverage) and STEP 1b (unique derivability), so all 29 resolved as STEP 2 test fixes or STEP 3 implementation fixes. No assertion was weakened, no `skip`/`xfail` added, no `error_id`→status downgrade.

### Fixes to `test_helpers/`
- `test_helpers/assertions.py` — added `_canonical_instant` / `assert_instant_equals`, a precision-independent ISO 8601 comparator. The PRD pins fractional digits for exactly three fields (`api_request_timestamp` and `created_at` at three digits, `response_deadline_at` at whole seconds); every other instant it declares is only "an ISO 8601 UTC timestamp".

### Fixes to `test_suite/` (STEP 1c partial-coverage splits + STEP 2 consistency)
- **11 sites** converted to `assert_instant_equals`, keeping the PRD-covered assertion (*which* instant the logical clock supplied) and dropping only the un-derivable serialization form. Decisive proof this was a test bug: `test_10` asserts `created_at == updated_at` on one line and `updated_at == "…T09:00:00Z"` on another, which together force `created_at` to whole seconds — contradicting the PRD's verbatim "three fractional digits". No implementation could satisfy both. `response_deadline_at` assertions left exact.
- **14 call sites** swapped `PLATFORM_ADMIN_HEADERS` → `ACCOUNT_MANAGER_HEADERS` on reads the PRD §4 table does not grant PlatformAdmin (found by an AST audit against all 63 table rows). `test_16_corner_rbac.py` left untouched — its 4 PlatformAdmin calls are intentional negative 403 probes.
- `test_12` — 3 field-name typos `status` → `case_status` on InvestigationCase.
- `test_13` — renewal clock corrected to `2026-08-26T00:00:00Z`, where §2.4's floor arithmetic gives exactly 6 whole days against 5 notice days.
- `test_14` — added the §3.6-required calibration record before submission.

### Fixes to `implementation/`
- `workspace/implementation/routes/visits.py` `submit()` — now raises §2.8 rung 9's generic `ERR_INVALID_STATE_TRANSITION`; `ERR_VISIT_NOT_IN_PROGRESS` is reserved by §3.6 for the nested calibration-record write alone.
- `workspace/implementation/services/derive.py` `create_ticket()` — applies the §3.5 drive of the machine to `DOWN` on a `CUSTOMER_REPORT`/`MACHINE_DOWN` ticket *after* the priority score is stamped against pre-request health. This also fixed two downstream priority-score assertions (500→800, 280→370).

### Housekeeping
- Sweep artifacts had drifted into `workspace/implementation/` (`results.*.json`) and `workspace/` (`sweep.log`); moved out to `/tmp/sweep_evidence_2701/` and all `__pycache__` removed, so the deliverable tree is clean.
- Verified storage is in-memory dicts only (`db.py` `reset()` rebuilds every table) with no startup seeding — no SQLite, JSON dump, or `/tmp` cache; a `start.sh` reboot wipes every byte.
- Debug servers reaped by recorded PID only; no broad `pkill` was ever issued.

**Orchestrator verification (memory: a Step 7 agent can claim a clean sweep with no artifacts on disk):** independently re-read all 8 files in `/tmp/sweep_evidence_2701/` — every one reports `passed=103 failed=0 errors=0 total=103 skipped=0`, timestamps 12:57. Green sweep confirmed. The 8 `results.*.json` will be restored into `workspace/implementation/` after Step 9, so they do not pollute the Step 8/9 implementation scans.

## Step 8: Finalize PRD — 2026-09-04T13:10:02.701Z

Done. `PRD_FINALIZED.md` written with three edits.

## Line counts
- `PRD.md`: 521 lines
- `PRD_FINALIZED.md`: 523 lines (+2, **+0.38%**)
- Both files end at the same boundary: the §5 catalogue's last row `| ERR_READING_BEFORE_INSTALL | 422 |`.

## Changes
- **§2.5** — *insert* (new paragraph after the `created_at` sentence) — pins the serialisation of every instant-valued field to three fractional digits + `Z` (with finer caller precision truncated), and carves out the two exceptions the impl actually exhibits: `response_deadline_at` (whole seconds) and the clock endpoint's `current_utc` (verbatim echo of the caller's string, `2026-08-01T00:00:00Z` before the clock is set); also notes plain-date fields keep `YYYY-MM-DD`. — `implementation/response.py:12-31`, `implementation/util.py:43-79`, `implementation/routes/clock.py:39-43`, `implementation/db.py:34-35`
- **§3.6 (Submission)** — *revise* — the wrong-`visit_status` and empty-evidence refusals report the generic `ERR_INVALID_STATE_TRANSITION`; `ERR_VISIT_NOT_IN_PROGRESS` is reserved for the nested calibration-record write and raised nowhere else. — `implementation/routes/visits.py:189-198` and `:358-362`
- **§3.5 (Priority scoring)** — *revise* — makes explicit that a `CUSTOMER_REPORT`/`MACHINE_DOWN` filing really does drive the health axis to `DOWN` (from `UP` or `DEGRADED`, no-op when already `DOWN`) *after* the score is stamped, raises no second ticket, re-derives the site's `open_ticket_count`/`service_posture`, and that no other symptom moves the axis. — `implementation/services/derive.py:256-280`, `:229-238`

## Per-edit pre-edit search log
**Edit 1** — (a) subject: serialisation form/precision of every instant the API emits. (b) enumerated: `response.py::_convert/serialize/payload/_meta` (single conversion funnel; `SECOND_PRECISION_FIELDS = {response_deadline_at}` only), `util.py::fmt_dt / fmt_dt_sec / fmt_date / parse_dt`, `clock.py::set_current_utc` (returns `db.db.clock_str`, a raw string, bypassing `_convert`), `db.py::CLOCK_START_STR`, every row insert that stores a datetime (`db.insert` `created_at`/`updated_at`; `placements.py` `installed_at`/`retrieved_at`; `telemetry.py` `opened_at`, `reading_at`; `visits.py` `arrival_at`, `scheduled_*`, `_verified_at`; `dispensers.py` `dose_effective_at`/`last_calibrated_at`; `deliveries.py` `delivered_at`; `reviews.py` `period_*`), `reports.py::sustainability_report`/`dossier` (echo `period_start`/`period_end` as datetimes), and every date-valued field (`start_date`, `term_end_date`, `retrieval_due_date`, `termination_effective_date`). Also confirmed `_verified_at`/`_applied_at` are underscore-prefixed and never serialised, so the "verification instant" is not a response field. (c) adjustment: the first draft said "every other instant … three fractional digits", which would have been a false universal against `clock.py`'s verbatim echo — added the `current_utc` carve-out, the truncation clause, and the plain-date sentence so the new universal is true on every enumerated path.

**Edit 2** — (a) subject: which state-legality code the visit lifecycle reports. (b) enumerated: `grep -rn "ERR_VISIT_NOT_IN_PROGRESS\|ERR_INVALID_STATE_TRANSITION" implementation/` — 20 generic sites (agreements activate/renew/terminate, placements install/retrieval-order/retrieval-completion/site-not-ACTIVE, visits create/arrive/submit×2/verify×2, reviews ×4, deliveries void, dispensers) and exactly **one** `ERR_VISIT_NOT_IN_PROGRESS` at `visits.py:360` (calibration-record create, after the rung-8 version check). (c) adjustment: the "reserved … and raised nowhere else in the API" clause was only committed after the grep confirmed the single callsite; scoped the generic claim to "those first two failures" so the third (`ERR_EFFICACY_FAILURE_UNRESOLVED`) is untouched.

**Edit 3** — (a) subject: the health-axis drive and side effects of ticket creation. (b) enumerated: `derive.create_ticket` (both origins), `derive.auto_ticket`, `derive.drive_down` / `drive_degraded` / `rederive_health`, `derive.has_open_ticket`, `calc.priority_score` / `response_deadline`, `routes/tickets.py::create_ticket` (origin always `CUSTOMER_REPORT`; `CustomerContact` **and** `AccountManager`; `INSTALLED` precondition; duplicate-symptom guard), `telemetry.py::apply_health` (the §3.4 drive path), and `visits.py::create_record` (efficacy-FAIL drive) — plus every `recompute_site` callsite. (c) adjustment: widened "the customer" to "the `CustomerContact` or the owning `AccountManager`" since both hit the same route; added "leaves a placement already `DOWN` where it stands" and "from either `UP` or `DEGRADED`" to match `drive_down`'s guards rather than claiming an unconditional transition; kept the auto-ticket statement as "raises no second ticket … would be skipped in any case" so it stays true whether a reader implements the drive with or without an alert argument.

**Orchestrator verification:** `PRD_FINALIZED.md` is 523 lines / 117237 bytes, differs from `PRD.md` (not byte-identical), and ends on the same §5 final table row — no truncation.

## Step 9: Complete PRD — 2026-09-04T13:41:44.253Z

Step 9 was run as **three sequential, module-partitioned passes** over one shared `PRD_COMPLETED.md` (pass 1 did the `cp`; passes 2 and 3 were explicitly forbidden from re-copying, and each proved the earlier passes' edits survived by char-count monotonicity plus marker spot-checks). Partition: pass 1 = app/db/errors/middleware/response/util/routes-common/clock/catalog/agreements/placements; pass 2 = dispensers/tickets/visits/telemetry/derive; pass 3 = deliveries/reviews/calc/reports.

**Totals: 523 lines / 117,237 chars → 523 lines / 135,403 chars (+18,166 chars, 122 diff lines vs `PRD_FINALIZED.md`), 64 edits — 47 ambiguity-pins, 17 mismatch-revisions.** Line count unchanged throughout because every patch was an in-paragraph insert/revision; no new sections. File still ends at `| ERR_READING_BEFORE_INSTALL | 422 |`.

### Pass 1 (26 edits: 19 ambiguity-pins, 7 mismatch-revisions)
- §2.1 — revise — ambiguity — blank/whitespace-only header is `ERR_UNAUTHENTICATED`; an unrecognised role string is `ERR_FORBIDDEN_ROLE` — `middleware.py:33-52`
- §2.2 — revise — mismatch — `api_request_timestamp` is host wall time, not the logical clock; `api_request_id` is `req_` + 16 lowercase hex — `response.py:16-20`
- §2.3 — insert — ambiguity — `limit`/`offset` present-but-empty counts as omitted; surrounding whitespace tolerated — `middleware.py:224-234`
- §2.3 — insert — ambiguity — `created_at` ties broken by insertion order everywhere, incl. the telemetry stream — `db.py:129-135`
- §2.3 — insert — ambiguity — filter matching: exact string equality, conjunctive, empty value = absent, booleans accept `true/false/1/0`, null field never matches, unknown params ignored — `routes/common.py:10-31`
- §2.4 — revise — mismatch — "nothing reads wall-clock time" excepted for the envelope timestamp — `response.py:19`
- §2.4 — insert — ambiguity — a fresh service seeds nothing; every collection starts empty — `db.py:1-5,42-47`
- §2.4 — insert — ambiguity — clock endpoint: `current_utc` mandatory/ISO-only; non-empty non-`PlatformAdmin` role is `ERR_FORBIDDEN_ROLE`, `X-User-ID` ignored; an instant equal to the present value is accepted and still runs the sweep — `routes/clock.py:19-43`
- §2.4 — insert — ambiguity — sweep visits tickets in `created_at` ascending order — `routes/clock.py:72`
- §2.5 — insert — mismatch — a row's `version` moves at most once per request (deferred to response render); a rejected request moves none — `db.py:87-121`, `app.py:69-77`
- §2.6 — insert — ambiguity — decimals render as bare JSON numbers, no trailing zeros, integral values as integers — `util.py:149-155`
- §2.8 r3 — insert — ambiguity — ownership rung skipped when no owner resolves (falls to 404); sole exception `GET /customers/{customer_id}` — `routes/catalog.py:66` vs `routes/agreements.py:80-86`, `routes/placements.py:102-106`
- §2.8 r4 — revise — ambiguity — absent/whitespace-only body = empty JSON object; array/string/number body is `ERR_INVALID_REQUEST` — `middleware.py:81-90`
- §2.8 r13 — insert — ambiguity — `sku`/`model_code`/`agreement_code` collisions sit at the uniqueness rung but report `ERR_INVALID_REQUEST` 400 — `routes/catalog.py:30-35`, `routes/agreements.py:50-54`
- §2.9 — revise — mismatch — "Three writes are the exception" → exactly two nested evidence writes — `routes/placements.py:245`
- §3.1 — insert — ambiguity — uppercase test is "unchanged by upper-casing", so digits pass — `middleware.py:116-117`
- §3.1 — revise — mismatch — only `sanitizer_min_ppm`/`sanitizer_max_ppm` required on a `SANITIZER`; `min_contact_seconds` may be omitted (defaults 7) but explicit null errors — `routes/catalog.py:156-172`
- §3.1 — insert — ambiguity — a no-op technician roster PATCH returns 200 but leaves `updated_at`/`version` untouched — `routes/catalog.py:340-356`
- §3.2 — insert — ambiguity — back-dated `effective_date` is `ERR_INVALID_REQUEST` after the status test; DRAFT→VOID applies no date test — `routes/agreements.py:171-187`
- §3.3 — insert — ambiguity — install's checks ordered placement→agreement→site; non-`ACTIVE` site is generic `ERR_INVALID_STATE_TRANSITION` — `routes/placements.py:134-149`
- §3.3 — insert — ambiguity — cancellation branch stores `retrieval_due_date` if supplied, else null; no dispenser/alert/ticket/posture side effects — `routes/placements.py:171-179`
- §3.9 — insert — ambiguity — `period_start`/`period_end` validated (rung 4) before path `site_id` resolution — `routes/catalog.py:363-378`
- §3.9 — revise — ambiguity — `basis` mandatory; absent/empty/unrecognised alike `ERR_INVALID_REQUEST`, decided before path resolution — `routes/catalog.py:388-393`
- §4 intro — insert — ambiguity — trailing slash insignificant; unknown path and undeclared method both `ERR_RESOURCE_NOT_FOUND` 404 before any header check — `app.py:31,44-54`
- §4 table — revise — mismatch — `GET /sites` filters completed with `priority_tier`, `status` — `routes/catalog.py:142-148`
- §4 table — revise — mismatch — `GET /machine-placements` filters completed with `asset_tag` — `routes/placements.py:116-123`

Verified-correct, no change: `errors.py` CATALOG is byte-for-byte consistent with the §5 table (all 38 ids/statuses); rung order `ERR_NON_MONOTONIC_CYCLE_COUNT` (13) before `ERR_READING_BEFORE_INSTALL` (14) matches `placements.py:275-295`; telemetry readings and calibration records are the only `common=False` inserts, so §2.5's "no `updated_at`/`version`" claim is exact.

### Pass 2 (18 edits: 12 ambiguity-pins, 6 mismatch-revisions)
- §2.5 — revise — mismatch — recomputation counts as a mutation only when the value actually *changes* — `services/derive.py:133-137`
- §2.10 — revise — mismatch — "every row a cascade touches is genuinely mutated" narrowed to every row a cascade *changes* — `services/derive.py:133-137`
- §3.2 cascade alpha — revise — mismatch — cancelling `QUEUED` tickets also cancels their `SCHEDULED` visits and re-derives posture/count — `services/derive.py:313-323,332`
- §3.4 — revise — ambiguity — "the agreement covering the placement" = the row the placement's own `agreement_id` names, whatever its status, never §3.7's resolution — `routes/dispensers.py:43-49`
- §3.4 — insert — ambiguity — `MANUAL_AUDIT` ingest moves no `version`/`last_cycle_count`/`cycles_since_calibration`; the placement `version` bump is the `DEVICE` path's alone — `services/telemetry.py:66-76`
- §3.4 — revise — ambiguity — "newest `DEVICE` reading" = greatest `reading_at` (earlier `created_at` wins ties); baseline before calibration is `initial_cycle_count`; difference floored at zero — `services/derive.py:213-222`
- §3.4 alert 5 — revise — mismatch — cycle-rate interval reduced to whole seconds, sub-second remainder discarded; cannot fire when it truncates to zero — `services/telemetry.py:124-133`
- §3.4 — revise — ambiguity — `measured_value` is the raw reading, the racks/hour rate rounded half up to 4 dp, or `cycles_since_calibration` for `CALIBRATION_OVERDUE` — `services/telemetry.py:132-137`
- §3.4 link 3 — insert — ambiguity — with several `CRITICAL` alerts from one reading the earliest in the six-type order drives; a de-duplicated breach drives nothing — `services/telemetry.py:142-148`
- §3.4 link 4 — revise — ambiguity — auto-ticket score sees the placement already `DOWN` and alerts already `OPEN` but the pre-ingest posture; an already-`DOWN`/`OFFLINE` placement is not re-driven and raises no further auto-ticket — `services/derive.py:229-237,256-280`
- §3.4 — insert — ambiguity — acknowledging a non-`OPEN` alert is generic `ERR_INVALID_STATE_TRANSITION` — `routes/dispensers.py:196-200`
- §3.6 — insert — ambiguity — `contact_seconds` integer ≥ 0; explicit null on it or `adjusted_dose_ml_per_rack` counts as omitted — `routes/visits.py:349-351`
- §3.6 — insert — ambiguity — the sanitizer `contact_seconds` presence rule is the one rung-4 exception, tested after version/state/lockout/placement-mismatch — `routes/visits.py:353-386`
- §3.6 — insert — ambiguity — efficacy-FAIL drive to `DOWN` attempted regardless of prior lockout, obeys the `INSTALLED`/`UP`-or-`DEGRADED` guards, raises no auto-ticket — `routes/visits.py:424-428`
- §3.6 — revise — ambiguity — `rejection_reason` ≤ 500 chars, non-blank when rejecting, length-checked then discarded on `VERIFIED` — `routes/visits.py:276-278,311`
- §3.6 — revise — mismatch — dose values come from the last **applied** record (`PASS`/`ADJUSTED`), not the last record overall — `routes/visits.py:232-252`
- §3.6 — insert — ambiguity — "latest record" for lockout recovery = the genuinely last record, applied or not; the verification instant is internal, not rendered — `routes/visits.py:260-265,300`
- §3.6 — insert — ambiguity — repair-confirmed alert resolution unconditional but health re-derivation requires `INSTALLED` and never lifts `OFFLINE` — `services/derive.py:393-408`
- §4 table (4 rows) — revise — ambiguity — filter names + `status` aliases for dispensers/visits; added `efficacy_result` on calibration-records and `origin`/`reported_symptom` on tickets — `routes/dispensers.py:90-96,120-127`, `routes/tickets.py:82-89`, `routes/visits.py:125-131`

### Pass 3 (20 edits: 16 ambiguity-pins, 4 mismatch-revisions)
- §3.7 — revise — mismatch — "a customer on `SUSPENDED` billing" → `billing_status` `CREDIT_HOLD` (no `SUSPENDED` billing status exists) — `routes/deliveries.py:45`
- §3.7 — revise — mismatch — delivery's covered-product test is the **union** over every live agreement of the site's customer; empty union when none is live — `routes/deliveries.py:38`, `services/derive.py:121-127`
- §3.7 — insert — ambiguity — `delivered_at` stored verbatim, bounded by neither clock nor term — `routes/deliveries.py:26`
- §3.7 — insert — ambiguity — the site `version` bump on delivery create happens although no site field changes; reconciled with §2.5's change-not-recomputation rule — `routes/deliveries.py:60`
- §3.7 — revise — ambiguity — covering agreement = earliest-created live one; else the `TERMINATED`/`EXPIRED` one with greatest `updated_at`; `DRAFT`/`VOID` never; none → `ERR_PERIOD_OUTSIDE_AGREEMENT_TERM` — `services/derive.py:106-118`, `routes/reviews.py:57`
- §3.7 — insert — ambiguity — term bounds are midnight UTC on `start_date`/`term_end_date`, so `period_end` must be ≤ that midnight — `routes/reviews.py:59-66`
- §3.7 — insert — ambiguity — the term test precedes the overlap test within rung 14 — `routes/reviews.py:62-71`
- §3.7 — revise — mismatch — `AS_CALIBRATED` prices each reading at the dose the applied record **put into effect** (= unchanged prior dose when the verdict was `PASS`), identical across every record one verification applies; fallback is the fitted creation dose — `routes/visits.py:238-247`, `services/reports.py:50-66`
- §3.5 — insert — ambiguity — `response_deadline_at` **truncates** the sub-second remainder rather than rounding — `services/calc.py:91-93`
- §3.8 — revise — ambiguity — the one-case-per-review test runs before the `PUBLISHED` test — `routes/reviews.py:210-221`
- §3.8 — revise — mismatch — `evidence_types` must be distinct; duplicates, non-string/blank members and non-arrays all `ERR_INVALID_REQUEST`; distinctness is per-array only — `routes/reviews.py:267`, `middleware.py:199-217`
- §3.8 — insert — ambiguity — `finding_note` max 1000 chars; omitting it leaves the stored note as it stands — `routes/reviews.py:293,319-320`
- §3.8 — insert — ambiguity — `remediation` mandatory on `SUBSTANTIATE`, a rung-4 error ahead of case existence, stage and segregation — `routes/reviews.py:294-295`
- §3.8 — insert — ambiguity — `RETURN` stamps no `reviewed_by_user_id` and leaves `remediation`/`chargeback_cents` as held — `routes/reviews.py:322-326`
- §3.8 — insert — ambiguity — the chargeback container count is a true ceiling: an exact multiple of `unit_size_ml` is not bumped by one — `services/calc.py:223`, `util.py:138-146`
- §3.9 — insert — ambiguity — the sustainability report also echoes `basis`; the dossier echoes none — `services/reports.py:262-280`
- §3.9 — insert — ambiguity — the rinse-pressure factor and effective water per rack are internal intermediates, not response fields — `services/reports.py:206-215`
- §4 deliveries-list row — revise — ambiguity — filters named; a `CustomerContact` is silently narrowed to its own account, `total_count` counting the narrowed set — `routes/deliveries.py:87-95`
- §4 reviews-list row — revise — ambiguity — added the `basis` filter — `routes/reviews.py:102-108`
- §4 cases-list row — revise — ambiguity — added `case_status` (+ alias `status`), `opened_reason`, `remediation` — `routes/reviews.py:253-259`

Pass 3 hand-off dispositions: the `in_operating_window` `start == end` case needed no change (§2.12's wrap wording already pins the all-day reading; only the code's own comment is wrong); `theft_chargeback`'s `or 0` coalescing is unreachable (publish's `ERR_INSUFFICIENT_TELEMETRY` gate plus the always-int write at create), so pinning it would invent an unobservable rule; `rank_technicians`' `_seq` leg was already covered by pass 1's §2.3 sentence and deliberately not duplicated.

**Known off-path defect, deliberately not fixed (recorded here as the durable trace):** `routes/catalog.py:260` admits `min_rinse_pressure_psi = 0`, and `services/reports.py:212` divides by it, so a `TELEMETRY_MEASURED` sustainability report over a placement of such a model would raise `DivisionByZero` (500). No PRD sentence pins a guard, so adding one would be an implementation-hack forbidden by the skill's cardinal rules, and writing prose for a crash would invent behavior. All 103 tests pass without touching this path. Left as-is and flagged upstream to the scaffold/doc generators rather than patched.

## Pipeline complete — 2026-09-04T13:41:44.253Z

- `workspace/PRD_COMPLETED.md` written (523 lines / 135,403 chars), differs from both `PRD_FINALIZED.md` and `PRD.md`, ends at the §5 catalogue's final row — no truncation.
- Final green sweep evidence restored to `workspace/implementation/results.{1..8}.json` (all 8: `passed=103 failed=0 errors=0 total=103`). Newest implementation mtime is 12:51; the sweep ran at 12:57, so the green sweep post-dates every implementation edit and Steps 8–9 touched no code.
- `__pycache__` / `.pytest_cache` swept from the whole task tree.
