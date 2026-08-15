# Worklog — task_1704_cleanroom_assembly_environmental

## Step 1: Create Task Directory — 2026-08-14T09:19:00.000Z

Task directory `tasks/task_1704_cleanroom_assembly_environmental/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline dispatcher. Step 1 treated as DONE per invocation instructions; no index scan performed, no other task_* directory touched.

## Step 3: Copy Shared Files — 2026-08-14T09:20:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1704_cleanroom_assembly_environmental/workspace/INSTRUCTION.md` (1424 bytes). Executed early (during Step 2's subagent run) since it has no dependency on scaffold output.

## Difficulty Directive

User directive: "Generate task hard than expert level!" — conveyed to Step 2 subagent as: exceed the §0.4 Expert band by maximizing the five hardness levers (dual-interpretation calculations, 3+ entity ordered side-effect chains, validation-priority conflicts, sibling-dependent state transitions, exact-boundary edge cases) rather than inflating entity/endpoint volume.

## Step 2: Generate Scaffold — 2026-08-14T10:05:00.000Z

All checks pass. Here is the final summary.

## Task 1704 Scaffold Generation — Complete

**Files written (all three, verified):**
- `/home/ubuntu/github/CodingPRD/tasks/task_1704_cleanroom_assembly_environmental/SCAFFOLD.yaml` (§1.0–§1.7; no `scaffold_difficulty_design`/`scaffold_corner_design` keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1704_cleanroom_assembly_environmental/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single top-level key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1704_cleanroom_assembly_environmental/SCAFFOLD_CORNER_DESIGN.yaml` (single top-level key `scaffold_corner_design`)

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (75 endpoints, 16 entities, 18 §1.8 instances, 54 §1.9 active instances scanned, 538 calls checked)

**Counts:**
- Entities: **16** (Cleanroom, Personnel, GowningQualification, SamplingPoint, EnvironmentalSample, Excursion, ExcursionInvestigation, RoomCertification, MaterialTransfer, AssemblyBatch, AssemblyTraveler, EntryLog, CleaningValidationProgram, CleaningCycle, CustomerAudit, AuditFinding)
- Endpoints: **75** (including `POST /cleanroom/_clock/set_current_utc` with pinned default 2026-08-01T00:00:00Z)
- Error codes: **42** (every one exercised by at least one §1.8/§1.9 instance — verified)
- Calculations: **8** (`sample_classification` with per-sample vs mean-based dual variants; `excursion_severity_score`; `certification_grade_check`; `certification_expiry`; `gowning_qualification_expiry`; `consecutive_pass_count`; `environment_posture_derivation`; `audit_scope_record_count`)
- State machines: **14** entries covering 12 entities + Cleanroom lifecycle dimension. Cycles: Excursion OPEN→UNDER_INVESTIGATION→OPEN (investigation rejection loop), CleaningValidationProgram VALIDATED→RE_VALIDATION_REQUIRED→VALIDATED, Cleanroom certification recertification cycle. Parallel dimensions: Cleanroom certification_status × environment_posture. Compound/posture-driven: environment_posture derived from open excursions + certification + CONFIRMED-impact investigations.
- Concurrency rules: **2** OCC rules (`certification-create-stale-room` on Cleanroom.version, `batch-release-stale-batch` on AssemblyBatch.version), both 412.

**§1.8 instances: 18 total, exactly 2 per rule** — dual_variant_calc (per-sample ALERT trips while mean certification passes on identical numbers; certification vs gowning expiry domains), combinatorial_formula (mode (a) 3-input non-linear severity score pinned at 45.0/37.5/30.0; mode (c) circular-looking certification gate ordering), non_linear_state_machine (parallel dimensions; investigation-rejection cycle), transitive_cascade (depth-4 sample→excursion→approval→SHUTDOWN→batch hold + transfer rejection; depth-3 FAIL cycle→counter reset→re-validation), priority_pair_validation_conflict (state-vs-SoD; posture-vs-dwell temporal), boundary_precision_check (sample exactly at alert limit; dwell exactly met), cross_entity_state_dependency (Traveler→Cleanroom; Audit→Finding), resource_temporal_overlap (half-open entry occupancy interval; capacity-1 state-scoped cleaning program), compensating_invariant (pass-count derivation; posture-as-function-of-open-excursions).

**§1.9 instances: 55 total across 9 sections** (entities 7, state_machines 9, calculations 4, validations 5, endpoints 4, errors 15 active + 1 excluded_because stub, roles 5, cross_cutting 2, consistency_model 1).

**Difficulty layers from §0.3 applied:** cascading_side_effects, rate_threshold_triggers, derived_field_reconciliation, optimistic_concurrency (2 OCC rules); topology `flat`, state shape `parallel`, role model `segregation_of_duties` (four distinct SoD anchor pairs), consistency `immediate`.

**Harder-than-expert levers pushed:** (1) two valid readings of "did the room exceed its limit" produce opposite verdicts on identical data, pinned per-sample vs mean; (2) depth-4 side-effect chain with order-dependent posture recovery requiring fresh certification after CONFIRMED approval; (3) three separate validation-priority conflicts with pinned winners; (4) state gating where valid next-states depend on sibling/child state at five distinct points; (5) exact-boundary cases on six different metrics (alert >=, action >=, mean <, cert expiry >=, gowning expiry >=, dwell >=, audit window [inclusive, exclusive), recurrence window [30d ago, now)).

During generation I fixed several self-consistency issues found by replay: stale OCC captures after posture-mutating excursions (added version re-capture GETs), SoD identity ambiguity (added an explicit `actor_identity_convention` block), enum dead-ends (added decommission/suspend/reinstate/revoke/retire endpoints and their machines), and all 16 FK reverse-reachability gaps.

## Step 4: Generate PRD — 2026-08-14T10:22:00.000Z

PRD generated and verified at `/home/ubuntu/github/CodingPRD/tasks/task_1704_cleanroom_assembly_environmental/workspace/PRD.md` (371 lines). The withheld index files were never opened.

## Section list

- **§1. Introduction** (3 paragraphs)
- **§2. Global Specifications** — 2.1 User/RBAC (4 roles, opaque-identity prose per role), 2.2 API Response Structure (byte-identical to canonical block — verified `True`), 2.3 Pagination (limit 10 default/1 min/100 max, offset 0, `created_at` ascending, meta fields), 2.4 Common Resource Properties, 2.5 Logical Clock & Lazy Expiry (default 2026-08-01T00:00:00Z, `to_iso8601`/`current_utc`, both lazy expiry rules with inclusive boundaries), 2.6 Two-Tier Limits: per-sample vs. mean-based judgment, 2.7 Environmental Posture (5-rule ordered derivation, SHUTDOWN recovery), 2.8 Segregation of Duties (4 pairs), 2.9 OCC (both rules), 2.10 Validation Order (13-rung priority ladder incl. 11.5 personnel-suspension rung), 2.11 Precision & Rounding
- **§3. Business Logic** — 3.1 Rooms/Sampling Plans/Certification Cycle, 3.2 Personnel/Gowning/Entry, 3.3 Sampling & Excursion Detection (severity-score formula in precise prose), 3.4 Investigation & Product-Impact (CONFIRMED cascade), 3.5 Material Transfer/Airlock, 3.6 Batches & Travelers, 3.7 Cleaning Validation, 3.8 Customer Audits & CAPA, 3.9 Decommissioning
- **§4. Endpoint Definitions** — 4-column table, all 75 endpoints, 201/200 status-code paragraph
- **§5. Error Code Catalogue** — 2-column table, all 42 error IDs

## Coverage audit

- **Contract 1 (fields)**: 65 entity fields + 50 endpoint inputs + 17 path params = 87 required identifiers; all present in backticks; **0 missing → PASS**
- **Contract 2 (rules)**: all 13 validation priorities expressed in order (§2.10); both OCC rules with endpoint + `expected_*_version` + exact error ID + 412 (§2.9); all 13 state machines fully rendered (every transition's from/to, preconditions with error IDs, side effects — incl. excursion OPEN↔UNDER_INVESTIGATION loop, certification supersede/latest-PASS pinning, batch ON_HOLD cascade with `hold_reason=EXCURSION_PRODUCT_IMPACT`, staged-transfer cascade rejection, force-close of open entry logs on suspension, FAIL-recorded-directly-as-REJECTED cycles, program re-validation loop, decommission's ERR_ROOM_NOT_ACTIVE aftermath); all 8 calculations in precise prose (sample classification with inclusive boundaries, severity score 10/4 base × zone 3/2.5/2/1 × (1 + 0.25 × recurrence in trailing 30-day half-open window, half-up 2dp), mean-strictly-below grade check at full precision, both lazy expiries at second precision, consecutive-pass counter with inclusive >= validation, posture derivation first-match-wins, audit scope [window_start, window_end)); all 42 error IDs appear in §1–§4 prose → **PASS**
- **Contract 3 (§3 path purity)**: 402 backticked tokens scanned in §3; 0 paths, 0 bare methods, 0 method+path combos → **PASS**

## Scaffold ambiguities resolved in prose

1. **SamplingPoint `zone_iso_class` equality** — the entity field requires it to equal the room's `iso_class` at creation, but no validation entry pins an error ID; I stated the constraint without inventing an error binding.
2. **SHUTDOWN derivation wording** — the scaffold formula says "any *open* excursion has an APPROVED investigation," yet approval closes the excursion; I rendered it per the recovery transition's true semantics (an approved CONFIRMED-impact investigation not yet superseded by a fresh PASS keeps the room in SHUTDOWN; recovery needs zero open excursions *and* that fresh PASS).
3. **`recurrence_count` window** — excursions carry no `sampled_at`; I phrased the window over each closed excursion's *triggering sample's* `sampled_at` at the same sampling point.
4. **Initial `version`** — only room creation pins `version=1`; I pinned it for cleanrooms and kept the general statement to "increments on every mutation."
5. **`severity` name collision** (Excursion ALERT/ACTION vs. AuditFinding OBSERVATION/MINOR/MAJOR/CRITICAL) — disambiguated by subsection context.

## Step 6: Generate Implementation — 2026-08-14T11:05:00.000Z

Implementation complete. Summary:

## File list (all under `/home/ubuntu/github/CodingPRD/tasks/task_1704_cleanroom_assembly_environmental/workspace/implementation/`)

- `start.sh` — guarded pip install (no-op once Flask importable), `exec python3 app.py` in foreground
- `requirements.txt` — `flask>=3.0,<4.0`
- `app.py` — entry point, blueprint registration, global request lock (atomic cascades), error handlers (ApiError + enveloped 404/405/400/500), binds `0.0.0.0:$PORT` (default 10000)
- `db.py` — empty in-memory store (16 entity dicts, no seeding), logical clock starting at exactly `2026-08-01T00:00:00Z` with no wall-clock fallback, ISO-8601 parse/format helpers (3-fractional-digit UTC), second-precision comparison truncation, common-field helpers (`id`/`created_at`/`updated_at`/`version`)
- `errors.py` — all 43 error-ID constants + `ApiError`
- `response.py` — scaffold envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`), list pagination in `meta` (`limit`/`offset`/`total_count`/`has_more`, defaults 10/0, bounds 1–100, violations → `ERR_INVALID_REQUEST`)
- `middleware.py` — `X-User-ID`/`X-User-Role` validation (400) and per-endpoint RBAC (403)
- `services/core.py` — posture derivation, lazy expiry, classification, severity scoring, cascades, field validators
- `routes/` — `clock.py`, `rooms.py`, `samples.py`, `certifications.py`, `people.py`, `transfers.py`, `batches.py`, `cleaning.py`, `audits.py`

## Endpoints: 75/75 implemented
Every route from the scaffold §1.5 table, with per-endpoint role sets exactly as specified (including the asymmetric GET splits — e.g. ProductionOperator cannot list personnel, MaterialHandler cannot list batches).

## Error codes: all 43 from the catalog implemented
…driven in the §2.10 priority order: headers (400) → role (403) → existence left-to-right (404) → OCC (412) → state (409) → posture → certification → segregation (403) → structural (400) → referential (422) → temporal → personnel-suspended → aggregate guards.

## State machines: 13 implemented
Cleanroom dual-dimension (certification_status × derived environment_posture, incl. ALERT floor and SHUTDOWN supersede-via-fresh-PASS recovery using a monotonic event sequence), Cleanroom lifecycle (decommission), Excursion (cyclic OPEN ↔ UNDER_INVESTIGATION), ExcursionInvestigation, AssemblyBatch (incl. auto IN_PROGRESS/COMPLETE and ON_HOLD cascade + resume), AssemblyTraveler (step-order gating), CleaningValidationProgram (cyclic re-validation), CleaningCycle (FAIL recorded directly REJECTED), MaterialTransfer, CustomerAudit, AuditFinding, Personnel (suspend force-closes open entry logs), GowningQualification (lazy EXPIRED), SamplingPoint.

## Calculations: all 8 implemented
Per-sample classification (inclusive `>=` on both tiers), excursion severity score (`Decimal`, ROUND_HALF_UP to 2dp, 30-day half-open recurrence window over CLOSED excursions), mean-based certification grade (strict `<`, full-precision `Decimal`), certification expiry (lazy, inclusive boundary), gowning expiry (+365d, inclusive), consecutive-pass counter with `>=` validation threshold, environment-posture derivation (pinned top-to-bottom order), audit scope window `[start, end)`.

## Verification
172 hand-written live checks pass across three suites (main workflow, edge cases, decommission/pagination/lazy-expiry) run against fresh boots. Key judgment calls (documented in code): certification shortfalls reject with the catalogued 409s rather than recording FAIL rows; traveler-start gowning resolves the operator's qualification via `X-User-ID` == `Personnel.id`; certification-create/release OCC fields are required (missing → 400, mismatch → 412); `_clock/set_current_utc` echoes the caller's literal as `current_utc`.

## start.sh confirmation
Verified via the exact evaluator contract: `bash start.sh` from `./implementation/` boots a foreground Flask server (via `exec`) on `0.0.0.0:$PORT`, serves HTTP within seconds, installs deps only when Flask is missing, and a kill+reboot returns an empty store with the clock reset — clean per-test-server isolation.

## Step 5: Generate Unit Tests — 2026-08-14T11:05:00.000Z

Generation complete. Final summary:

## Tests emitted

**Queue A (Difficulty): 34 tests** covering 17 of 18 instances (≥2 tests each).

**Queue B (Corner): 52 tests** covering 52 of 54 non-stub instances (≥1 each).

**Total: 86 tests across 9 files**; `pytest --collect-only` collects all 86 cleanly; all modules pyflakes-clean and importable.

## Instances skipped (3) — PRD-first filter failures

1. **Difficulty/combinatorial_formula/certification_result_circular_evaluation_order** — asserts ERR_CERTIFICATION_GRADE_FAILED wins when grade fails AND excursions are open. PRD §2.10's fixed priority list never places the grade check, and §3.1 lists the three certification conditions without stating evaluation order ("first match wins" appears only in the scaffold). Two PRD-only readers can legitimately pick different errors → ordering not uniquely derivable.
2. **Corner/errors/error_room_not_certified_on_batch_release** — unreachable per the PRD itself: §2.7 rule 4 forces posture floor ALERT whenever certification_status ≠ CERTIFIED, so the priority-6 posture gate (ERR_ROOM_NOT_IN_CONTROL) always pre-empts the priority-7 certification gate; the instance's own setup chain (traveler start in an UNCERTIFIED room) is also rejected by the posture gate.
3. **Corner/cross_cutting/audit_scope_window_half_open_membership** — the scope snapshot has no PRD-observable read path: CustomerAudit exposes only customer_code/cleanroom_id/window_start/window_end/status, and no endpoint returns scope contents or counts. Membership claim unobservable → fails unique derivability.

**Stub not translated (1):** Corner/errors/error_cycle_result_fail_on_verify — `excluded_because` cross-reference to Difficulty/transitive_cascade/failed_cleaning_cycle_cascades_program_revalidation verified to resolve.

## File list

**test_helpers/** (9 files): `__init__.py` (barrel), `types.py` (16 TypedDicts + 19 enums), `api_client.py` (66 endpoint methods), `api_errors.py` (40 errors registered with the framework), `assertions.py` (per-entity + severity-score precision checker), `factories.py` (15 payload factories), `constants.py` (limits, severity weights, 365-day qualification, 30-day recurrence window), `test_users.py` (4 opaque roles + per-instance builders), `fixtures.py` (7 tiers: clock, room/certification composites incl. OCC version re-read, qualified personnel, excursion close, batch/traveler walks with personnel-id threading, audits).

**test_suite/** (10 files): `conftest.py`, `test_01_room_registration_guards_and_envelope.py` (10), `test_02_sampling_classification_and_severity.py` (12), `test_03_excursion_investigation_and_posture.py` (11), `test_04_certification_and_expiry.py` (9), `test_05_personnel_gowning_entry.py` (6), `test_06_material_transfer.py` (6), `test_07_batch_traveler_release_and_cascade.py` (14), `test_08_cleaning_validation.py` (10), `test_09_customer_audits.py` (8).

## Stage 2 self-audit results

- **Tag coverage:** AST parse of all 86 tests: exactly one `Design:` line each, as the final docstring line; all tags resolve to real instances; zero tags on skipped instances or the stub.
- **Coverage counts:** every translated Difficulty instance has exactly 2 tests; every translated Corner instance has exactly 1.
- **Citation verbatim check:** all 129 rule-bearing quoted spans (≥8 words) survive whitespace-normalized literal match against PRD.md.
- **Error-id check:** all 37 asserted `ApiErrorId` members are named in PRD prose §1–§4 (not only the §5 table) and registered in the HTTP status map.
- **No** `pytest.mark.skip`/`skipif`/`xfail` anywhere; gaps stay gaps.
- Identity threading: all roles are opaque per the PRD, so shared header constants are safe; segregation pairs pin explicit distinct ids; traveler-start success paths thread the qualified personnel id as the operator X-User-ID so the gowning gate passes under any faithful reading.

## Step 7: Run Tests and Iterate — 2026-08-14T11:15:00.000Z

All 8 rounds pass with 86/86 tests in every round. The sweep is clean — exit condition met.

**Summary**

- **Iterations run:** 1 (clean 8-round parallel sweep on the first attempt; no fixes needed).
- **Tests deleted:** none.
- **Fixes applied to `test_helpers/`:** none.
- **Fixes applied to `test_suite/`:** none.
- **Fixes applied to `implementation/`:** none.

Operational note: the first sweep launch was killed by the 10-minute background-command cap before results were written (exit 144; orphaned pytest children were cleaned up). The sweep was relaunched detached via `setsid nohup` (driver script `/tmp/sweep_1704.sh`, per-round logs at `/tmp/sweep_1704.round{1..8}.log`) and completed successfully: all 8 `results.{1..8}.json` files under `/home/ubuntu/github/CodingPRD/tasks/task_1704_cleanroom_assembly_environmental/workspace/implementation/` report `passed=86 total=86 failed=0 errors=0 skipped=0`. The pre-existing implementation (75 endpoints, 43 error IDs, 13 state machines, 8 calculations) and the 86-test suite across 9 files are mutually consistent with PRD.md with zero flakiness across all 8 parallel rounds.

Orchestrator verification: independently read all 8 `results.{1..8}.json` files — every round reports 86/86 passed, 0 failed, 0 errors.

## Step 8: Finalize PRD — SKIPPED — 2026-08-14T11:16:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determined every behavior the implementation exhibits; no `PRD_FINALIZED.md` was produced. Step 9 will read `PRD.md` directly.

## Step 9: PRD Completeness Scan — 2026-08-14T11:31:00.000Z

All edits verified. The task is complete — here is the summary.

## Summary

**Source**: `workspace/PRD.md` (no `PRD_FINALIZED.md` present) → `workspace/PRD_COMPLETED.md`
**Line counts**: 370 → 372 lines; **char delta**: 50,448 → 57,371 (+6,923 chars). 24 passages edited; 34 diff hunks.
**Counts**: 32 ambiguity-pins, 11 mismatch-revisions.

### Changes (one per edited passage)

- **§2.1** — insert — ambiguity — empty/whitespace header values and unrecognized `X-User-Role` values count as malformed → 400 `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (not 403) — `implementation/middleware.py:29-40`
- **§2.1** — revise — mismatch — the blanket "never compares `X-User-ID` against any entity's `id`" gains a carve-out: the traveler-start gate matches operator `X-User-ID` against qualification `personnel_id` — `implementation/services/core.py:290-298` called with `uid` at `implementation/routes/batches.py:253`
- **§2.2** — insert — ambiguity — unknown path/unsupported method → `ERR_NOT_FOUND` 404; unparseable JSON body treated as empty object — `implementation/app.py:56-66`, `middleware.py:46-51`
- **§2.3** — insert — ambiguity — non-integer/out-of-range `limit`/`offset` rejected with `ERR_INVALID_REQUEST`; `created_at` ties break by creation order (all records share logical-clock timestamps) — `implementation/response.py:47-82`, `db.py:150-152`
- **§2.4** — insert — ambiguity — every resource (not just cleanrooms) begins at `version` 1; a recomputation leaving the derived value unchanged is not a mutation (no `version`/`updated_at` advance) — `db.py:127-142`, `services/core.py:154-157`, `routes/samples.py:129-130`
- **§2.5** — insert — ambiguity — all server-generated timestamps (`created_at`, `api_request_timestamp`, `entered_at`, …) read the logical clock; clock accepts any instant (no monotonicity guard) and `current_utc` echoes the caller's string verbatim — `db.py:113-114`, `routes/clock.py:24-28`
- **§2.9** — insert — ambiguity — omitted `expected_room_version`/`expected_batch_version` → `ERR_INVALID_REQUEST` (structural tier); non-integer value → `ERR_STALE_*` — `routes/certifications.py:69-84`, `routes/batches.py:122-156`
- **§2.10 item 5** — insert — ambiguity — names the endpoint-specific state guards and places the `ERR_ROOM_NOT_ACTIVE` lifecycle gate at the state tier, ahead of posture — e.g. `routes/transfers.py:82-92`, `routes/batches.py:237-251`
- **§2.10 item 11** — insert — ambiguity — `ERR_WIPE_DOWN_MISSING` sits at the temporal tier immediately before the dwell gate — `routes/transfers.py:93-100`
- **§2.10 item 13** — insert — ambiguity — certification guard order: grade → open excursions → cleaning validation — `routes/certifications.py:102-112`
- **§2.11** — insert — ambiguity — ISO 8601 inputs may carry any offset or none (read as UTC); stored timestamps normalized to UTC — `db.py:78-96`
- **§2.6** — insert — ambiguity — no sign/magnitude constraint on limits or `recert_interval_days` beyond the action>alert ordering — `routes/rooms.py:46-56`
- **§3.1 (registration)** — revise — mismatch — `room_code` uniqueness is not server-enforced; sampling-point definition requires room `ACTIVE` (`ERR_ROOM_NOT_ACTIVE`); `point_code` uniqueness not enforced — `routes/rooms.py:41-71, 125-146`
- **§3.1 (certification)** — revise — mismatch — a shortfall (grade/open excursions/unvalidated cleaning) rejects with the indicated error and records nothing; no `FAIL` certification is ever stored; `location_mean_values` must be numeric; supersedes link: unknown → 404, other room → 422, target left unmodified — `routes/certifications.py:85-131`
- **§3.1 (void)** — revise — mismatch — tie-break is creation order (most recent first), not `created_at` descending; guard order pinned: 404 (cert not of room) → room `ACTIVE` → `certification_status` `CERTIFIED` (`ERR_INVALID_STATE`) → latest-PASS — `services/core.py:276-287`, `routes/certifications.py:163-183`
- **§3.2** — revise+insert — mismatch+ambiguity — `employee_code` uniqueness not enforced; qualification grant requires only FK existence (duplicates allowed, room lifecycle not consulted); exit of an already-closed log → `ERR_INVALID_STATE`, any `ProductionOperator` may exit — `routes/people.py:54-65, 112-136, 275-285`
- **§3.3** — insert — ambiguity — the sample's `triggered_excursion_id` forward link is written at creation, so the sample is born at `version` 1 — `routes/samples.py:126-128`
- **§3.5** — revise — ambiguity — introduction gate order pinned: `STAGED` → room `ACTIVE` → posture → certification → wipe-down → dwell (six gates, replacing the unordered "five ways") — `routes/transfers.py:78-103`
- **§3.6 (open/add)** — revise+insert — mismatch+ambiguity — `batch_number` uniqueness not enforced; opening a batch requires only room existence (no posture/cert/lifecycle gate); traveler steps addable in any batch status; `step_sequence` need not be unique — `routes/batches.py:75-93, 200-213`
- **§3.6 (start)** — revise — ambiguity — step must stand `PENDING` (`ERR_INVALID_STATE`), then five gates in impl order: batch startable → room `ACTIVE` → posture → gowning (resolved by `X-User-ID` = `personnel_id`) → strictly-lower-sequence order — `routes/batches.py:231-273`
- **§3.6 (complete)** — insert — ambiguity — completion consults neither batch nor room state; auto-`COMPLETE` fires only when the batch stands `IN_PROGRESS` at resolution (a step resolved while `ON_HOLD` does not complete it; resume does not re-evaluate) — `routes/batches.py:54-67, 276-290`
- **§3.6 (release)** — revise — mismatch — `ERR_BATCH_TRAVELERS_UNSETTLED` is unreachable on release (non-settled batch fails earlier with `ERR_BATCH_NOT_COMPLETE`) — `routes/batches.py:131-161`
- **§3.7** — insert — ambiguity — `required_consecutive_passes` must be ≥ 1 when provided; activation from non-`DRAFT` → `ERR_INVALID_STATE`; cycles recordable in any program status; verification increments the counter regardless of program status, auto-`VALIDATED` only from `ACTIVE`/`RE_VALIDATION_REQUIRED`; `ERR_CYCLE_RESULT_FAIL` defensive (FAIL cycles are born `REJECTED`) — `routes/cleaning.py:53-73, 95-149, 167-188`
- **§3.8** — revise+insert — mismatch+ambiguity — findings are accepted regardless of audit status (PRD said "While the audit is `IN_PROGRESS`"); scope snapshot retained internally, not exposed; zero-finding audits close vacuously — `routes/audits.py:101-104, 107-140`
- **§3.9** — revise — mismatch — replaces "entries, samples, transfers, travelers, and certifications alike" with the precise gated set (entries, samples, sampling-point definitions, transfer staging/introduction, certification record/void, traveler-step starts) and explicitly notes batch opens, traveler adds, qualification grants, cleaning programs/cycles, audits/findings are not lifecycle-gated — `routes/rooms.py:129-130`, `routes/batches.py:75-93, 200-213, 246-247`, `routes/people.py:112-136`, `routes/cleaning.py:53-73, 120-149`, `routes/audits.py:45-69`
- **§4** — insert — ambiguity — all paths match with or without a trailing slash — `app.py:14`

### Verification notes

All 60+ endpoint paths, role assignments, error ids, and HTTP codes in the PRD table and error catalogue match the implementation exactly (checked route-by-route against `routes/*.py` and `errors.py`); no changes needed there. The posture state machine (§2.7), severity-score formula (§3.3), recurrence window (§3.3), expiry boundaries (§2.5), and segregation-of-duties pairs (§2.8) were verified line-by-line against `services/core.py` and already pinned uniquely — untouched.
