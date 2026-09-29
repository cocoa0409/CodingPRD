# Worklog — task_2267_staffing_data_reporting_verification

## Step 1: Create task directory — 2026-09-01T13:50:19.379Z

Created `tasks/task_2267_staffing_data_reporting_verification/` and `tasks/task_2267_staffing_data_reporting_verification/workspace/`.

## Step 2: Generate scaffold — 2026-09-01T15:30:42.388Z

All three artifacts are complete and lint-clean.

## Generated files
`/home/ubuntu/github/CodingPRD/tasks/task_2267_staffing_data_reporting_verification/`
- `SCAFFOLD.yaml` (§1.0–§1.7, contains neither design key)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

## SCAFFOLD.yaml counts
| Table | Count |
|---|---|
| §1.1 entities | **14** (Facility, ReportingPeriod, JobCategory, Worker, StaffingVendor, VendorHourSubmission, PayrollRecord (immutable, `common_fields: false`), HourEntry, CensusDay, QuarterlySubmission, ValidationFinding, StaffingMeasure, DiscrepancyCase, RatingAppeal) |
| §1.2 state machines | **8** (2 with parallel dimensions: HourEntry entry/verification, StaffingMeasure publication/audit) |
| §1.2.1 concurrency rules | **3** (2× `expected_submission_version`, 1× `expected_measure_version`) |
| §1.3 calculations | **8** (waterfall_allocation, aggregation, 2× threshold, tiered_pricing, weighted_scoring, surcharge escalation, posture derivation; 3 carry dual variants) |
| §1.4 validations | **64** (single ordered priority chain) |
| §1.5 endpoints | **69** |
| §1.6 errors | **75** |
| §1.7 roles | **7** (PlatformAdmin, StaffingCoordinator, FacilityAdministrator, VendorRepresentative, StateAuditor, CmsPublisher, AppealsReviewer; `role_model: segregation_of_duties`) |

Profile: `ledger_reconciliation` / `compliance_audit`, flat topology, cyclic state shape, immediate consistency, 6 complexity layers.

## §1.8 Difficulty Design
**18 instances** — all nine §0.5 rules × 2 (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant).

## §1.9 Corner Design
**77 instances** across all nine taxonomy sections — 67 with full `test_recipe` blocks + 10 `excluded_because` stubs citing §1.8 instances:
entities 13, state_machines 14, calculations 14, validations 15, endpoints 6, errors 3, rbac 5, cross_cutting_complexity_layers 6, consistency_model 1.

## Verification
- `scaffold_lint.py`: **VERDICT: clean lint** — 1373 calls scanned across §1.8+§1.9, all conform to §1.5, all FKs reverse-reachable.
- All **75/75** error ids are triggerable somewhere in §1.8/§1.9; all 69 endpoints are exercised (10 list endpoints via assert-level reads).
- Names unique across the §1.8∪§1.9 union; every `excluded_because.difficulty_instance` resolves to a real §1.8 name; no unresolved `${...}` placeholders in any call or assert.

Two soundness fixes to SCAFFOLD.yaml were needed during generation (both preserved): `ERR_DAILY_HOURS_EXCEEDED` was unreachable under `MAX_HOURS_PER_DAY 24.00` (added `MAX_REPORTED_HOURS_PER_WORKER_DAY: 20.00` and re-pointed validation 51 at it), and `ERR_CASE_RESPONSE_REQUIRED` was unreachable because substantiate only accepted `UNDER_REVIEW` (added an `INFO_REQUESTED → SUBSTANTIATED` transition and widened validation 26's from-set).

## Step 3: Copy shared files — 2026-09-01T15:30:42.388Z

Copied `./INSTRUCTION.md` → `tasks/task_2267_staffing_data_reporting_verification/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T15:44:56.387Z

PRD generated and audited.

## Output
`workspace/PRD.md` — **522 lines**

## Structure
- **§1 Introduction** — 3 paragraphs framing the PBJ-style reporting chain (hour capture → census denominator → quarterly submission → audit verification → public star rating → appeal).
- **§2 Global Specifications** — 11 subsections: 2.1 RBAC (7 roles, identity translation for the 3 entity-backed roles, segregation of duties); 2.2 API Response Structure (pasted verbatim, diffed clean against `section-2.2-response-structure.md`); 2.3 Pagination and List Filtering (all 37 query params enumerated per resource); 2.4 Common Resource Properties and the Logical Clock (`PayrollRecord` as the sole no-`updated_at`/no-`version` entity; clock reads `2026-08-01T00:00:00Z` before any set); 2.5 Numeric Precision and Rounding (2dp hours / 4dp ratios / integer cents, plus the two pinned rounding orders); 2.6 Stale-Version Protection (all 3 OCC rules); 2.7 Reporting Posture ladder; 2.8 Periods, Deadlines, Correction Window; 2.9 Cascade Consistency; 2.10 Nested Path Resolution; 2.11 Order of Evaluation (the full 64-rule ladder as an ordered list).
- **§3 Business Logic** — 9 subsections: 3.1 reference data; 3.2 workers/vendors/payroll evidence; 3.3 hour capture, shift arithmetic, split-role allocation; 3.4 census + MDS reconciliation; 3.5 agency batches; 3.6 validation pass, HPRD dual variants, findings, attestation; 3.7 acceptance, payroll verification, audit-readiness dual variants, amendment surcharge; 3.8 measures and 4-step star assignment; 3.9 investigations and appeals.
- **§4 Endpoint Definitions** — 4-column table, all **69** endpoints.
- **§5 Error Code Catalogue** — 2-column table, all **75** errors.

## Hard Contract audits (mechanically verified against SCAFFOLD.yaml)

```
Field coverage check:
- entities[].fields: 130 required, 130 present, 0 missing
- endpoints[].request_body: 60 required, 60 present, 0 missing
- endpoints[].query_params: 37 required, 37 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 64 checked, 64 expressed in prose, 0 missing
  (61 unique single error ids appear in §2.11 in exact priority order; the 2
   composite path/body-resolution rows are items 11-12 with all 14 not-found
   codes named verbatim in §2.10)
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint +
  expected_<parent>_version + error_id + 412 all named), 0 missing
- state_machines[].transitions: 43 checked, 43 fully expressed, 0 missing
- calculations[]: 8 checked, 8 fully expressed, 0 missing (all 33 declared
  constants present as literal values; no symbolic operators or pseudocode)
- validations[] conditions: 64 checked, 64 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 115 side_effects + 64 applies_to scopes
  checked, all expressed, 0 missing
- entities[].fields[] structured content: 130 checked (incl. 84 enum literals and
  all array-element object shapes for allocations/lines), 130 reconstructible, 0 missing
- sibling-branch symmetry: 9 groups checked, 9 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 922
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

## Key finding to flag: scaffold internal inconsistency
`calculations.hour_entry_classification.constants` defines `MAX_REPORTED_HOURS_PER_WORKER_DAY: 20.00`, and validation priority 51 says the per-worker/per-`work_date` ACTIVE `raw_hours` sum "must not exceed MAX_REPORTED_HOURS_PER_WORKER_DAY" — but the `ERR_DAILY_HOURS_EXCEEDED` entry in `errors[]` describes the condition as "would exceed 24.00". I resolved in favour of **20.00** (constants + validation table), and treated 24.00 as `MAX_HOURS_PER_DAY`, which the PRD uses only for the aggregate payroll-document capacity rule behind `ERR_PAYROLL_CAPACITY_EXCEEDED` (validation 41). If the intended daily reported-hours ceiling is actually 24.00, the scaffold constant and validation 51 both need amending, and §3.3 of the PRD would need the same one-word change.

Both `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were left unopened, and no sibling task directory was read.

## Step 5: Generate unit tests — 2026-09-01T17:06:19.856Z

Queue B is complete and the whole suite audits clean.

## Files written

**Stage 1 — `test_helpers/`** (`types.py`, `api_client.py`, `api_errors.py`, `constants.py`, `test_users.py`, `factories.py`, `fixtures.py`, `assertions.py`, `__init__.py`), rooted at `.../test_helpers/`. This session added `assert_instant_equals` to `assertions.py` plus its export.

**Stage 2 — `test_suite/`**: `conftest.py` plus 22 test modules. New this session:
- `test_suite/test_17_validations.py` (15)
- `test_suite/test_18_endpoints.py` (6)
- `test_suite/test_19_errors.py` (3)
- `test_suite/test_20_rbac.py` (5)
- `test_suite/test_21_cross_cutting.py` (4)
- `test_suite/test_22_consistency_model.py` (1)

## Test counts

- **Queue A (Difficulty, `test_01`–`test_13`): 71 tests** over all 18 live instances (every instance ≥2 tests).
- **Queue B (Corner, `test_14`–`test_22`): 67 tests** — entities 13, state_machines 14, calculations 6, validations 15, endpoints 6, errors 3, rbac 5, cross_cutting 4, consistency_model 1 (one test per live instance).
- **Total 138 tests collected** (`pytest test_suite --collect-only -q` → "138 tests collected"); pyflakes clean.

## Audit result (scripted against both design yamls)

- 18 live difficulty + 67 live corner instances; 10 `excluded_because:` corner stubs — **none translated**.
- All 138 docstrings carry exactly one `Design:` line, and it is the last line: 0 untagged, 0 dual-tagged, 0 tags resolving to a non-existent or stub instance, 0 live instances uncovered.
- Every docstring carries at least one quoted `PRD:` citation. No file under `test_suite/` or `test_helpers/` contains "scaffold", "§1.", or design-index vocabulary. All `api.*` calls resolve to real `ApiClient` methods and all enum/error members referenced exist.

## Instances skipped or narrowed (PRD-first filter)

No live instance was dropped whole; ten assertion-level adjustments where the design was not uniquely derivable from the PRD:

1. `census_day_patch_updates_count_and_reverts_validated_parent` — the design reconciles an already-`RECONCILED` day, which PRD §3.4 does not define an outcome for; the DISPUTED/`CENSUS_VARIANCE` assertions were satisfied on a second, freshly reported day instead.
2. `substantiation_cascade_is_visible_in_the_same_response` — dropped `resolved_at == 2026-08-01T00:00:00Z`: `resolved_at` is a `ValidationFinding` field in the PRD, not a `DiscrepancyCase` field.
3. `stale_expected_versions_rejected_on_every_occ_write` — the submission-side probes run while the quarter is `DRAFT`, because §2.11 check 18 precedes check 30 (an ACCEPTED target would answer `ERR_SUBMISSION_STATE_INVALID`).
4. `measure_duplicate_and_under_audit_violations_rejected` — duplicate probe moved ahead of the freeze; the appeal-filing `ERR_MEASURE_UNDER_AUDIT` assertion dropped (check 25 covers only computation and publication).
5. `vendor_roster_batch_shape_and_suspension_violations_rejected` — empty-lines probe moved ahead of the suspension (22 < 61).
6. Design HTTP statuses contradicting the §5 registry (`ERR_UNKNOWN_ROLE` 400→401, `ERR_SHIFT_OVERLAP`/`ERR_PERIOD_OVERLAP` 422→409) resolved in favour of the PRD map.
7. Two difficulty instances asserting persisted `hprd_reported` on a never-validated submission: those assertions omitted (only the validation pass writes it).
8. `source == DIRECT_ENTRY` omitted — PRD §3.3 sets `source` to `PAYROLL`.
9. Exact-string timestamp equality replaced by `assert_instant_equals`, since §2.4 renders instants with three fractional digits while the clock is set as `...T00:00:00Z`.
10. `unknown_ids_return_the_entity_specific_not_found_error` — added the `ERR_CENSUS_DAY_NOT_FOUND` probe the design's call list omitted but §2.10 declares.

## Step 6: Generate implementation — 2026-09-01T17:06:19.856Z

Implementation complete and verified.

## Files written
All under `workspace/implementation/`:

| File | Role |
|---|---|
| `start.sh` | Launcher: `cd` to own dir, installs `requirements.txt` only when Flask is missing, then `exec python3 app.py` |
| `requirements.txt` | `Flask>=2.2` |
| `app.py` | App factory, blueprint registration, `ApiError` / `HTTPException` / catch-all handlers, `0.0.0.0:$PORT` (default 10000) |
| `db.py` | In-memory `Store` (14 dicts, empty at boot), logical clock (epoch `2026-08-01T00:00:00Z`), id/seq/timestamp helpers, `base_record`, `touch`, `find`, `ordered` |
| `errors.py` | `ApiError` + full error-id → HTTP status map (~75 ids) and default messages |
| `response.py` | `meta`/`response_type`/`data` envelope, `req_` + 20-alnum request id, 3-fractional-digit UTC timestamps, pagination, equality filters, `Decimal`→float and `_`-prefixed-key stripping |
| `validation.py` | Body/field/enum/date/time parsers, FK resolution helpers (tolerant so step-12 precedes step-13) |
| `middleware.py` | `X-User-ID`/`X-User-Role` auth (steps 1–6), facility scope (7), vendor scope (8) |
| `calc.py` | Decimal ROUND_HALF_UP at 2dp/4dp/cents, allocation classification, star tiers, census variance, late-fee and amendment-surcharge schedules |
| `services.py` | Domain layer: rollups, HPRD (both variants), audit-readiness scoring, facility posture derivation, finding lifecycle/rebuild, sanction cascade, measure recompute, shift-overlap logic |
| `routes/{reference,vendors,submissions,hours,measures}.py` | 69 endpoints across 5 blueprints |

Endpoint count: **69** registered routes, matching the PRD §4 table.

## Verification
- `bash start.sh` with `PORT=10311` booted in ~1s; `GET /facilities` returned 200 with the correct envelope, `total_count: 0`, `data: []`; missing headers → 401; `POST /facilities` → 201.
- A second fresh boot on a new port returned empty `/facilities` and `/submissions` — confirms in-memory-only storage, zero seeding, and no disk persistence across the per-test reboots.
- End-to-end smoke run through the Flask test client (temp script, since deleted) exercised ~55 calls with zero failures: clock set, facility/period/job-category/worker/vendor/payroll creation and their duplicate + constraint rejections; submission → split-allocation hour entry (7.50 raw → 4.62 direct-care / 2.88 excluded / 3.38 RN, weekend flag); shift-overlap 409 and stale-version 412; census create + reconcile (variance 0.0500 → RECONCILED); validate (91 findings raised: 90 `CENSUS_INCOMPLETE` + 1 variance-free set, `hprd_reported` 0.0630); submit with segregation-of-duties; accept (sampled score 50.00 → auto `DiscrepancyCase`, facility → `AUDIT_HOLD`); measure compute + publish (appeal deadline = published + 30d) → appeal grant (measure `SUPPRESSED`, `latest_staffing_rating` cleared); reopen (surcharge 25000 cents, facility outstanding updated); request-info → respond → substantiate (facility `SANCTIONED`, subsequent validate 409); vendor batch create → submit → accept (8.00 hours into the submission, vendor total updated) → revoke (entries `VOID`, totals reset); auditor verify SUPPORTED/UNSUPPORTED with `ERR_SUPPORT_DOCUMENT_MISSING`; audit-adjusted HPRD read; period close cascading the submission to `VOID` and blocking further writes.

Two cleanups made this pass: removed a stray empty `services/` directory that could shadow `services.py`, and deleted `__pycache__` trees so the tree ships source-only.

## Step 7: Run tests and iterate — 2026-09-01T17:20:27.262Z

All 138 tests pass in all 8 parallel rounds.

## Iterations run
3 sweeps (8 parallel rounds each, 138 tests, `per-test-server` isolation). Round 1: 129/138 in all 8 rounds. Round 2: 137/138. Round 3: **138/138 in all 8 rounds**. Failures were fully deterministic across rounds — no flakiness surfaced.

## Tests deleted
None deleted whole. One **assertion** removed under the partial-coverage rule (STEP 1c):

- `test_suite/test_22_consistency_model.py` — dropped `assert reverted["validated_by_worker_id"] is None`. **PRD-silence category: branch-asymmetric side effect.** PRD §2.9/§3.9 render the sanction cascade as "reverts to `DRAFT`, gains a new `ValidationFinding` … `open_fatal_finding_count` refreshed … `version` incremented by one" — clearing `validated_by_worker_id` is named *only* for the reopen path (§3.7: "clears both `validated_by_worker_id` and `attested_by_worker_id`"). The remaining assertions (posture, counts, DRAFT revert, fatal finding, version bump) were kept.

## Fixes applied to `test_suite/`
All timestamp fixes are STEP 2 test bugs: PRD §2.4 renders instants "with three fractional digits", so exact-string equality against a `…Z` literal asserts a rendering the PRD does not pin. Replaced with the suite's own `assert_instant_equals` helper (instant-level comparison), which is the *more* faithful assertion — the pattern the suite already used in `test_17`.

- `test_15_state_machines.py` — `correction_deadline`, `submitted_at` (batch attest), `accepted_at`, `submitted_at` (batch re-submit).
- `test_14_entity_shapes.py` — `correction_deadline`.
- `test_11_cross_entity_gates.py` — `published_at` and `appeal_deadline`.
- `test_20_rbac.py`, `TestScopeIsCheckedAgainstTheTargetRow` — the test asserted `after["version"] == 1` after its own setup had already performed a census write, which §2.9 requires to increment the submission's `version`. Now captures the version before the two refused writes and asserts it is unchanged, which is what the test actually means to prove.

## Fixes applied to `implementation/`
- `workspace/implementation/routes/vendors.py`, `accept_batch` — recompute `hprd_reported` from the as-submitted reading after synthesizing the batch's hour entries. PRD §3.5 verbatim: "The target submission's rollups **and its as-submitted hours-per-resident-day figures** are then recomputed"; the code only re-ran `rollup_submission`, leaving `hprd_reported` at its pre-acceptance value (6.0 instead of 18.0). No other write path was changed — §3.5's revocation clause names only "rollups", so revocation was left alone.

No implementation check was weakened, no assertion downgraded, no skip/xfail added, and storage remains in-memory only.

**Orchestrator verification note:** the subagent left no `results.*.json` on disk, so the orchestrator re-ran the full 8-round parallel sweep independently. Result: **138/138 in all 8 rounds** (`results.1.json` … `results.8.json` now present in `workspace/implementation/`), confirming the subagent's claim.

## Step 8: Finalize PRD — 2026-09-01T17:35:00.000Z

Done. `PRD_FINALIZED.md` written with two edits.

## Line counts
- `PRD.md`: 522 lines / 122,682 chars
- `PRD_FINALIZED.md`: 522 lines / 123,761 chars → **+0.88%** by characters, **0.0%** by lines (both edits are inline extensions of existing paragraphs; no new sections, no reflow).

## Changes
- **§2.4 (Common Resource Properties and the Logical Clock)** — *insert* — pins that the three-fractional-digit `Z` rendering is canonical for **every** instant-valued response field (`updated_at`, `submission_deadline`, `correction_window_end`, `correction_deadline`, `submitted_at`, `accepted_at`, `resolved_at`, `published_at`, `appeal_deadline`, `decided_at`, `current_utc`), that a client-supplied instant is normalised rather than echoed verbatim (`2026-12-31T23:59:59Z` → `2026-12-31T23:59:59.000Z`), and that date/time-of-day fields are *not* reformatted — `implementation/db.py:56-63` (`fmt_dt`), `routes/reference.py:59,195-196`, `routes/submissions.py:77`.
- **§2.9 (Cascade Consistency)** — *insert* — pins that the `FACILITY_SANCTIONED` cascade leaves `validated_by_worker_id` / `attested_by_worker_id` untouched, and that only a reopen clears them — `implementation/services.py:466-480` (`sanction_cascade`) vs `routes/submissions.py:279-280` (reopen, the only clearing site).

## Step-7 items that got **no** PRD edit
- `implementation/routes/vendors.py:297-302` (`accept_batch` now recomputes `hprd_reported`): the fix moved impl *onto* PRD §3.5's verbatim "rollups **and its as-submitted hours-per-resident-day figures** are then recomputed". PRD already determines it; revocation (`vendors.py:353-354`, rollups only, `hprd_reported` untouched) also already matches §3.5 + §3.3's rollup field list. No wording change.
- `test_20_rbac.py` version-capture fix: pure test bug; §2.9 already requires a census write to bump `version`.

## Per-edit pre-edit search log

**Edit 1 — §2.4 instant rendering**
- (a) Subject: rendering/serialisation of every datetime-valued field, and of client-supplied instants.
- (b) Enumerated & read: `db.py` (`fmt_dt`, `now_str`, `clock_str`, `base_record`, `touch`), `response.py` (`jsonable`/`meta` — timestamps pass through as plain strings, no reformat), `validation.py` (`parse_dt` normalises `Z`/offset/naive to UTC; `parse_date`/`parse_time` are strict regexes with no normalisation), plus grep for every `*_at`/`*_deadline`/`current_utc` assignment: `routes/reference.py:59,195,196`; `routes/submissions.py:75-77,184,206,304`; `routes/measures.py:73-74,337,375`; `routes/vendors.py:151,191`; `services.py:326,336,598,600`. All twelve instant fields flow through `fmt_dt`; no path echoes a raw client instant. Date-only fields (`start_date`, `end_date`, `work_date`, `hire_date`, `pay_period_*`, `census_date`) and `shift_start`/`shift_end` are stored as the supplied string.
- (c) Adjustment: scoped the claim to *instant-valued* fields and added the explicit "date fields … time-of-day fields … stored and returned exactly as supplied" contrast, so the sentence cannot be read as adding fractional digits to `YYYY-MM-DD`/`HH:MM` values. Used "every `submitted_at` and `accepted_at`" rather than naming one owner, since `submitted_at` exists on both `QuarterlySubmission` and `VendorHourSubmission`. Deliberately did not say which clock (wall vs logical) feeds `created_at`/`updated_at` — off-site behaviour Step 7 never exercised.

**Edit 2 — §2.9 sanction cascade side effects**
- (a) Subject: writes to `validated_by_worker_id` / `attested_by_worker_id`.
- (b) Enumerated (grep across `implementation/`, then read each): `routes/submissions.py:72-73` (seeded null at creation), `:103-104` (list filters), `:157` (validate sets validator), `:168` (attest segregation read), `:183` (attest sets attester), `:279-280` (reopen — the only null-ing), `services.py:466-480` (`sanction_cascade` — status, finding, counts, `touch` only), `routes/reference.py:229-241` (`close_period` sweep to `FINAL`/`VOID` — leaves both fields), `routes/submissions.py:204-208/247-250` (accept/reject — leave both fields).
- (c) Adjustment: phrased the exclusivity as *clearing back to null* rather than "never changed", so §3.6's re-validation overwriting `validated_by_worker_id` with a new id (submissions.py:157) is not contradicted; also included `attested_by_worker_id` only as "left exactly as they were" (vacuously null on a `VALIDATED` row) rather than asserting any value for it.

## Step 9: Complete PRD — 2026-09-01T17:43:06.286Z

**Files**
- Source: `workspace/PRD_FINALIZED.md` — 522 lines, 124,082 chars
- Output: `workspace/PRD_COMPLETED.md` — 522 lines, 133,403 chars
- Delta: +0 lines, **+9,321 chars**; 30 diff hunks over 31 lines; heading set identical; no new sections, no new paragraphs

**Counts**
- Ambiguity-pins: **34**
- Mismatch-revisions: **6**
- Total changes: **40**

**Changes**
- §2.3 Pagination and List Filtering — insert — ambiguity — list ordering tie-break pinned to server insertion sequence for equal `created_at` — `db.py:118-120` (`_seq` at `db.py:92`)
- §2.4 Common Resource Properties — insert — ambiguity — `created_at`/`updated_at`/`api_request_timestamp` come from wall-clock time; only the named transition instants read the logical clock — `db.py:66`, `db.py:74`
- §2.4 Common Resource Properties — insert — ambiguity — a derived refresh that changes nothing is not a mutation: `updated_at`/`version` untouched — `services.py:254`, `services.py:90`, `services.py:509`
- §2.7 Reporting Posture — revise — **mismatch** — posture is re-derived at a fixed six-moment set (case open, substantiate, dismiss, submission reopen, measure publish, appeal grant), explicitly not on `request-info`, `respond`, or period close — `routes/measures.py:175,262,286,412`, `routes/measures.py:125`
- §2.9 Cascade Consistency — revise — **mismatch** — FINAL/VOID lock has one exception: hour payroll verification consults only the entry — `routes/hours.py:224-240`
- §3.1 Standing Up the Universe — insert — ambiguity — `ccn` length, `state_code` shape and `certified_bed_count` ≥ 1 all refuse with `ERR_INVALID_REQUEST`, all three before the `ccn` collision check — `routes/reference.py:75-85`
- §3.1 Standing Up the Universe — insert — ambiguity — closing an already-`CLOSED` period refuses `ERR_PERIOD_CLOSED`; the close sweep re-derives no facility figure — `routes/reference.py:223-227`
- §3.1 Standing Up the Universe — insert — ambiguity — `cms_job_code` 1–40 and credit 0.00–1.00 refuse with `ERR_INVALID_REQUEST`, credit stored half-up at 2dp, range tested after `code` uniqueness — `routes/reference.py:254-281`
- §3.1 Standing Up the Universe — revise — **mismatch** — `weekend_countable` is recorded and defaults `true` but no calculation reads it; weekend selection uses `is_weekend` — `routes/reference.py:258,285`, `calc.py:126`
- §3.2 Workers, Vendors, Payroll — insert — ambiguity — `authorized_roles` element outside the two literals refuses `ERR_INVALID_ENUM_VALUE`; empty array when omitted — `routes/reference.py:331-339`
- §3.2 Workers, Vendors, Payroll — insert — ambiguity — termination has no precondition on `status`; re-terminating succeeds and still bumps `version` — `routes/reference.py:391-404`
- §3.2 Workers, Vendors, Payroll — insert — ambiguity — suspension likewise has no `status` precondition and still bumps `version` — `routes/reference.py:453-464`
- §3.2 Workers, Vendors, Payroll — insert — ambiguity — reversed pay-period range and `paid_hours` ≤ 0.00 both refuse `ERR_INVALID_REQUEST`; `paid_hours` stored rounded to 2dp — `routes/reference.py:482-522`
- §3.2 Workers, Vendors, Payroll — insert — ambiguity — payroll `worker_id` need only resolve; it need not belong to the named `facility_id` — `routes/reference.py:466-500`
- §3.3 Capturing Worked Hours — insert — ambiguity — allocations stored and echoed verbatim, `percent` not renormalised, not re-sorted — `routes/hours.py:166-200`, `services.py:557`
- §3.3 Capturing Worked Hours — revise — **mismatch** — every worker named by any entry (voided included) is refreshed, each from that worker's `ACTIVE` entries across every submission in the system — `services.py:90-104`, `services.py:105-130`
- §3.3 Capturing Worked Hours — insert — ambiguity — the rollup leaves `hprd_reported` untouched; only validation and batch acceptance write it, so it can go stale — `services.py:105-130`, `routes/submissions.py:155`, `routes/vendors.py:300`
- §3.4 Census and MDS Reconciliation — insert — ambiguity — a PATCH with neither field still re-runs the rollup and bumps both versions; explicit null is treated as absent, so `mds_resident_count` can never be cleared — `routes/hours.py:349-372`
- §3.4 Census and MDS Reconciliation — revise — **mismatch** — reconcile imposes no precondition on the day's `status` (a `RECONCILED` day may be reconciled again); it only requires non-null `mds_resident_count` — `routes/hours.py:384-397`
- §3.4 Census and MDS Reconciliation — insert — ambiguity — a DISPUTED day raises no second `CENSUS_VARIANCE` when an `OPEN` one for that `census_date` exists — `services.py:340-348`, `routes/hours.py:397-415`
- §3.5 Agency Hour Batches — insert — ambiguity — a container whose `facility_id`/`reporting_period_id` disagrees with the batch refuses `ERR_SUBMISSION_STATE_INVALID`, checked right after the status gate — `routes/vendors.py:212-216`
- §3.5 Agency Hour Batches — insert — ambiguity — acceptance guards sweep guard-by-guard across all lines in order; overlap and the 20.00-hour ceiling accumulate intra-batch; allocation sum and shift window are not re-tested — `routes/vendors.py:232-268`
- §3.5 Agency Hour Batches — insert — ambiguity — revoke zeroes `accepted_direct_care_hours` but leaves `accepted_hour_entry_ids` populated with the ids it voided — `routes/vendors.py:342-350`
- §3.6 Validation Pass — insert — ambiguity — `variant` empty string treated as omission; any other value refuses `ERR_INVALID_ENUM_VALUE` — `routes/submissions.py:131-134`
- §3.6 Validation Pass — insert — ambiguity — `MISSING_PAYROLL_SUPPORT` carries the entry's `work_date` as `subject_ref` and is tracked per entry, so same-date entries each raise their own — `services.py:362-430`, `services.py:315-333`
- §3.6 Validation Pass — insert — ambiguity — `ZERO_DIRECT_CARE_DAY` carries that `census_date` as `subject_ref` — `services.py:362-430`
- §3.6 Validation Pass — insert — ambiguity — the five kinds are created in the listed order, which is what the `created_at`-ascending finding list reflects — `services.py:362-430`
- §3.6 Validation Pass — insert — ambiguity — only `OPEN` findings participate; `RESOLVED`/`WAIVED` are never reopened and never suppress a fresh one, so a waived `FATAL` returns to block attestation — `services.py:340-348`, `services.py:362-430`
- §3.6 Validation Pass — insert — ambiguity — `UNSUPPORTED_HOURS` uses the entry's `work_date` per entry, `FACILITY_SANCTIONED` uses the facility's `ccn`, plus each one's resolution rule — `services.py:466-486`, `routes/hours.py:240-270`
- §3.6 Validation Pass — insert — ambiguity — waive stamps `resolved_at` from the logical clock, joins `detail` + single space + note, and bumps `version` whether or not a count moved — `routes/submissions.py:301-309`
- §3.6 Validation Pass — insert — ambiguity — attestation answers `ERR_FACILITY_UNDER_HOLD` for a `SANCTIONED` facility too, not `ERR_FACILITY_SANCTIONED` — `routes/submissions.py:175-178`
- §3.7 State Review — insert — ambiguity — an already-`SUPPORTED` entry refuses `ERR_SUBMISSION_STATE_INVALID`, checked after the `entry_status` gate and before documentation — `routes/hours.py:230-240`
- §3.7 State Review — insert — ambiguity — verification is ungated above the entry: neither period `status` nor submission `status` is consulted — `routes/hours.py:224-240`
- §3.7 State Review — insert — ambiguity — a second `UNSUPPORTED` on one entry raises a second finding; the submission's `version` moves only when a finding count actually changed — `routes/hours.py:240-274`, `services.py:349-361`
- §3.7 State Review — insert — ambiguity — audit-readiness read: empty `variant` = omission, `SAMPLED` explicit, else `ERR_INVALID_ENUM_VALUE`; `submission_id` required; no ownership check against the path facility — `routes/reference.py:127-148`
- §3.7 State Review — insert — ambiguity — reopen rewinds nothing else: `submitted_at`, `accepted_at`, `accepted_by_user_id`, `rejection_reason`, `audit_support_score`, findings and rollups all survive — `routes/submissions.py:255-284`
- §3.8 Public Staffing Measures — revise — **mismatch** — publish gates are UNDER_AUDIT (over all siblings, so this measure too) → SANCTIONED → PROVISIONAL in that order, the last refusing `ERR_MEASURE_NOT_PUBLISHED` — `routes/measures.py:113-120`
- §3.9 Investigations and Appeals — insert — ambiguity — a case may be opened against a submission in any `status` — `routes/measures.py:133-153`
- §3.9 Investigations and Appeals — insert — ambiguity — on grant, the submission's `version` moves only when the waived amount is non-zero — `routes/measures.py:408-410`
- §3.9 Investigations and Appeals — insert — ambiguity — clearing `has_open_appeal` is a mutation, so both grant and deny bump the measure's `version` — `routes/measures.py:398-400`, `routes/measures.py:432-433`

---

## Pipeline complete

All 9 steps finished. Final state: 138/138 tests passing across 8 independent parallel rounds under `--isolation per-test-server`; `workspace/PRD_COMPLETED.md` on disk.
