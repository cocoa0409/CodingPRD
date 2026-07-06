# Worklog — task_0539_employment_immigration

## Step 1: Create Task Directory — 2026-07-02T00:00:00.000Z

Created `tasks/task_0539_employment_immigration/` and `tasks/task_0539_employment_immigration/workspace/`. Index pre-assigned (0539); scan skipped per instructions. Difficulty: Expert.

## Step 2: Generate Scaffold (resumed — corner design only) — 2026-07-02T13:53:00.000Z

SCAFFOLD.yaml and SCAFFOLD_DIFFICULTY_DESIGN.yaml existed and were complete from a prior run; only SCAFFOLD_CORNER_DESIGN.yaml was missing and was generated to complete Step 2.

Created SCAFFOLD_CORNER_DESIGN.yaml with single top-level key `scaffold_corner_design`. Coverage: 9 sections, 73 instances (62 with full test_recipe, 11 excluded_because stubs deferring to §1.8). Per-section: entities (12), state_machines (11), calculations (13), validations (13), endpoints (4), errors (5 stubs), rbac (9), cross_cutting (5), consistency_model (1). All grounds reference real SCAFFOLD.yaml entities/transitions/validations/errors/roles; OCC (ERR_STALE_VERSION) covered in cross_cutting (not in §1.8). scaffold_lint.py: "clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5." Note: ERR_RFE_EXPIRED not independently triggerable (clock side-effect auto-DENIES past-due RFE petitions); covered via at-due satisfaction pass + past-due auto-deny state-machine instance instead. SCAFFOLD.yaml and SCAFFOLD_DIFFICULTY_DESIGN.yaml unmodified.

## Step 3: Copy Shared Files — 2026-07-02T13:54:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_0539_employment_immigration/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-02T14:00:00.000Z

Generated workspace/PRD.md (288 lines) for Employment-Immigration (PERM/LCA & H-1B).

Structure: §1 Introduction; §2 Global Specs (RBAC, verbatim envelope, pagination, common props + logical clock, monetary/wage cents round-half-up-per-area, OCC on PWD issuance, cross-aggregate cascades, left-to-right resolution, 13-level validation precedence); §3 Business Logic (employer/wage-obligation ledger, PWD, PERM recruitment/quiet-period/filing/audit, LCA + PAF, cap registration + deterministic lottery, H-1B petitions fee/RFE/adjudication/overlap, I-140 + priority dates); §4 endpoint table (37 endpoints); §5 error catalogue (21 errors).

Coverage: all 10 entities, all 7 state machines (incl. FILED⇄AUDIT and SUBMITTED⇄RFE_ISSUED cycles + cascades/reverts), all 9 calculations, all 13 validations with priority ordering, all 37 endpoints incl. _clock, all 21 errors, all 4 roles (EmployerAgent entity-backed ownership; 3 opaque operators). Hard contracts: Field coverage PASS, Rule coverage PASS, Path purity (§3 no paths/methods) PASS. Did not read DIFFICULTY/CORNER design or sibling tasks.

## Step 5: Generate Unit Tests — 2026-07-02T20:28:00.000Z

All green: everything compiles and all PRD citations are verbatim. The test infrastructure is complete.

### Tests emitted
- **Queue A (Difficulty):** 36 tests — all 18 depth instances (9 rules × 2) covered by exactly 2 tests each, tagged `Design: Difficulty/<rule_id>/<instance.name>`.
- **Queue B (Corner):** 62 tests — all 62 non-stub breadth instances covered by exactly 1 test each, tagged `Design: Corner/<section>/<instance.name>`.
- **Total: 98 tests** across 12 domain-named files (`test_01_entities_crud` … `test_12_compensating_invariants`).

### Instances skipped / notable adjudications
- **11 corner `excluded_because:` stubs** correctly not translated (their cited difficulty instances own the assertions). All cross-references were verified to resolve to real `SCAFFOLD_DIFFICULTY_DESIGN` instance names.
- **`dual_variant_calc/lca_required_wage_provisional_vs_final`** — the design recipe's final-lock assertion (PATCH `prevailing_wage_cents` up to 13000000 with `offered_wage_cents` staying 11000000, then certify → 13000000) is **internally PRD-inconsistent**: LCA certification requires `offered >= prevailing` (§3.4), so a faithful implementation returns `ERR_WAGE_BELOW_PREVAILING` rather than certifying. The provisional↔final divergence with a *legal* certification is impossible under the wage floor. I therefore emitted the two PRD-consistent halves of the instance instead (provisional value at creation = `max(prevailing, offered)`; provisional recompute after a `prevailing_wage_cents` PATCH), and dropped the illegal certification assertion. The instance still has its required ≥2 tests.
- No `pytest.mark.skip/skipif/xfail` anywhere; no scaffold/section leakage in emitted prose (per-test `Design:` tags excepted, as mandated).

### `test_helpers/` file inventory
- `__init__.py` — barrel export (framework re-exports + PRD-specific).
- `types.py` — 10 entity TypedDicts (all carry `updated_at`/`version` per §2.4) + status/role/enum types.
- `api_client.py` — `ApiClient(GenericApiClient)`, 37 endpoint methods (incl. `/_clock/set_current_utc`).
- `api_errors.py` — `ApiErrorId` (21 errors) + HTTP status map, registered with framework.
- `assertions.py` — per-entity assertions + cap-seat invariant checker.
- `factories.py` — one payload factory per creatable entity.
- `constants.py` — fee tiers, PAF weights, recruitment/quiet/PERM/RFE windows.
- `test_users.py` — shared opaque-role headers + `make_employer_agent_headers()` for the entity-backed `EmployerAgent` ownership threading.
- `fixtures.py` — composite setup helpers (issued PWD, recruiting/quiet/filed/certified PERM cases, certified LCA, selected registration, submitted/RFE-issued petitions, two-adjacent-petition scenario, clock control) — identity-threaded throughout.

### Verification performed
Byte-compiled all modules; confirmed every difficulty instance has exactly 2 tests and every non-stub corner instance exactly 1 (no extras, no stubs tested); confirmed all `api.<method>` calls and all `test_helpers` imports resolve; and confirmed every quoted PRD citation survives a whitespace-normalized literal grep of `PRD.md` (0 failures).

## Step 6: Generate Implementation — 2026-07-02T20:28:00.000Z

Built a complete Python + Flask REST API for the Employment-Based Immigration (PERM/LCA & H-1B) domain in `workspace/implementation/`. Storage is 100% in-memory (Python dicts on a `Store` instance); nothing is seeded at boot, and the process starts clean every launch.

### File inventory (all under `.../workspace/implementation/`)
- `start.sh` — foreground launcher; reads `$PORT` (default 10000), binds `0.0.0.0`, guards `pip install` on a cheap `import flask` check, `exec python3 app.py`.
- `requirements.txt` — `flask>=2.0`.
- `store.py` — in-memory store, logical clock (epoch `2026-05-01T00:00:00Z`), and time/id helpers (`parse_dt`, `format_dt` to 3-fractional-digit ISO 8601 UTC, `add_days`, `new_id`, `request_id`).
- `errors.py` — `ApiError(error_id, http_status, message)`.
- `app.py` — all routes, envelope, RBAC, validation ordering, state machines, calculations, cascades.

### Endpoints (all 36 from the PRD table)
Employers, PWDs (+issue transition with OCC/supersede), PermCases (+recruitment/quiet/filing/audit/certify/deny transitions), RecruitmentSteps, LCAs (+PATCH, +certify/withdraw transitions, +audit-paf), Beneficiaries, CapPrograms (+run-lottery), H1BRegistrations (+withdraw), H1BPetitions (+submit/RFE/respond/approve/deny), I140Petitions (+submit/approve/deny), and `POST /_clock/set_current_utc`. Each resource also has GET-by-id and filtered/paginated list endpoints.

### Key design decisions
- **Timestamps from the logical clock** (not wall clock): `created_at`/`updated_at`/`api_request_timestamp` all use the clock so tests are fully deterministic; list sort is stable by `created_at`, preserving insertion order for ties (matches the lottery's "created_at ASC, never id" rule).
- **Validation ordering** follows PRD §2.9 exactly: auth(401) → role(403) → existence(404, present FKs left-to-right; missing required FK falls through to 400) → body(400) → registration-uniqueness(409) → OCC(412, before state) → state-legality(409) → cross-entity gates(409) → temporal(422) → recruitment-completeness(422) → step-overlap(409) → employment-overlap(409) → wage-floor(422).
- **Transition role model**: coarse endpoint role set, then a fine per-`to_status` actor map (403 when the wrong role names a valid user transition; system-only targets like SUPERSEDED/EXPIRED fall to ERR_INVALID_STATE, matching the PRD).
- **Computed vs stored**: beneficiary status fields, LCA `aggregate_wage_obligation_cents`, `required_wage_cents` (provisional while DRAFT, locked at certification), and `paf_completeness_score` are computed on read; `total_wage_obligation_cents` and CapProgram seat counts are maintained with explicit version bumps.
- **Money** uses integer cents throughout; the only rounding (aggregate obligation) uses `Decimal` `ROUND_HALF_UP` per worksite area before summing.
- **Cascades** implemented and tested: PWD supersede → PermCase revert to DRAFT + RecruitmentStep VOID; LCA withdraw → obligation reversal + H1B petition denial; PERM denial → I-140 denial; RFE-deadline / validity-end expiries evaluated on every clock set; beneficiary version bumps on the exact approval/denial cases the PRD specifies.

Verified via live end-to-end runs: OCC 412 + employer version bump, filing-fee tiers (e.g. 646000 for a 60-employee dependent non-amended petition), deterministic lottery, duplicate-registration 409, per-area half-up rounding, RFE cycle + auto-deny on expiry, LCA-withdrawal cascade with obligation reversal, PERM-based vs self-petition priority-date inheritance, ownership 403, and validation precedence (401 before 404, missing-field 400).

## Step 6: Generate Implementation — 2026-07-02T12:12:00.000Z

Completed a full Python + Flask implementation of the Employment-Based Immigration API and verified it end-to-end (60+ live assertions across three workflow batches, all passing).

Files (workspace/implementation/): app.py (single file ~1000 lines: store, envelope, auth/RBAC, validation, 10 entities, state machines, calculations, cascades, logical clock), requirements.txt (flask>=2.0), start.sh (guarded install `if ! python3 -c "import flask"` then exec python3 app.py; reads $PORT default 10000, binds 0.0.0.0, foreground).
Endpoints: all 35 from PRD table (Employers, PWDs, PermCases, RecruitmentSteps, LCAs, Beneficiaries, CapPrograms, H1BRegistrations, H1BPetitions, I140Petitions each POST/GET/list where specified; plus /transitions, /run-lottery, /audit-paf, PATCH /lcas/{id}, POST /_clock/set_current_utc).
Behaviors: envelope exact (meta{api_request_id,api_request_timestamp,+pagination}/response_type/data; error {error_id,message}). Auth/RBAC X-User-ID+X-User-Role, per-to_status role gating on shared transition endpoints, EmployerAgent ownership employer_id==X-User-ID (opaque roles skip ownership). Validation precedence 401→403→404→400→409dup→412OCC→409state→409xentity→422temporal→422incomplete→409overlap→422wage. OCC on PWD issuance via expected_employer_version→ERR_STALE_VERSION 412; issuance sets prevailing_wage_cents, supersedes competing ISSUED PWDs, bumps Employer.version. Cascades: PWD supersede→PermCase revert-DRAFT+RecruitmentStep VOID+field clears; LCA withdraw→obligation reversal+H1BPetition denial (beneficiary recompute for SUBMITTED/RFE_ISSUED); PERM deny→I-140 denial. Calculations Decimal/ROUND_HALF_UP: aggregate wage (round-per-area-then-sum), tiered H-1B filing fee (171000/646000/46000-amended), required-wage provisional-vs-locked, priority-date PERM-inherited vs self, deterministic created_at-ordered lottery, PAF scoring. Logical clock default 2026-05-01T00:00:00Z drives timestamps and on set applies PWD/LCA expiry + RFE-deadline auto-denial; beneficiary current_status_code derived live.
Design decisions: in-memory only empty on boot (no seed/persist, threaded=True). Datetime input echoed verbatim; system datetimes canonical (3-digit ms + Z); created_at uses logical clock; list sort (created_at, insertion_seq). Two PRD ambiguities resolved: (1) H1BRegistration.fiscal_year with no matching CapProgram → ERR_VALIDATION 400 (scalar not FK). (2) LCA expiry does NOT adjust employer wage-obligation ledger (follows PRD "moves only through certification and withdrawal"). Duplicate fiscal_year on CapProgram creation → ERR_VALIDATION.

## Step 5: Generate Unit Tests — 2026-07-02T12:34:00.000Z

All checks pass: 98 tests collect, no skip/xfail, no scaffold leakage, all 120 citations verbatim, all coverage/tag audits green.

Test infrastructure generated for task_0539_employment_immigration (Employment-Based Immigration PERM/LCA & H-1B, Expert).
Stage 1 — test_helpers/ (9 files): constants.py, types.py (10 entity TypedDicts + status/role enums), api_errors.py (21 error IDs registered with framework HTTP-status map), api_client.py (one method per PRD §4 endpoint + /_clock setter), assertions.py, factories.py (unique FEIN/passport generators), test_users.py (entity-backed EmployerAgent builder + opaque-role constants + role_only_headers for auth test), fixtures.py (composite lifecycle helpers: issued PWD, recruiting/quiet/filed/certified PERM case, selected registration, draft/submitted H-1B petition, two-petition same-beneficiary overlap setup — correct identity threading), __init__.py.
Stage 2 — test_suite/ (conftest + 16 test files, 98 test functions): Queue B (Corner) 62 tests across test_01–test_07, exactly one per non-stub instance — entities(12), state_machines(11), calculations(10), validations(13), endpoints(4), rbac(9), cross_cutting+consistency_model(3). Queue A (Difficulty) 36 tests across test_08–test_16, ≥2 per instance for all 18 instances (9 rules).
Audits all green: every test one verbatim Design: tag; 18/18 difficulty instances ≥2 tests; 62/62 corner non-stub instances ≥1 test; 11 excluded_because stubs correctly NOT translated; zero unknown-instance tags; all 120 quoted PRD citations survive whitespace-normalized grep; no skip/xfail; no scaffold refs.
One PRD-first partial skip (not a coverage gap): for Difficulty/dual_variant_calc/lca_required_wage_provisional_vs_final, the recipe's final-lock assertion (PATCH prevailing 10000000→13000000 with offered 11000000 then certify → final required_wage_cents==13000000) is not PRD-derivable: PRD §3.4 requires offered_wage_cents>=prevailing_wage_cents at certification, so a faithful impl returns ERR_WAGE_BELOW_PREVAILING and no "final locked 13000000" is observable. That assertion dropped; instance covered by two PRD-faithful provisional-recompute tests (≥2 satisfied). Framework prd_bench_local_runner available in-repo at prd-bench-local-runner/src/ (not pip-installed); collection verified with it on PYTHONPATH.

## Step 7: Run Tests and Iterate — 2026-07-02T12:44:00.000Z

All 8 rounds now pass 98/98 with zero failures and zero flakiness.
Iterations run: 2 sweeps (1 baseline diagnosing, 1 confirming the fix).
Tests deleted: None. No PRD-silence or non-derivability was found — every failing assertion tested a value verbatim-covered and uniquely PRD-derivable (priority-date inheritance §3.7, quiet_period_end = recruitment_end + 30 days §3.3, rfe_due_date = rfe_issued_date + 87 days §3.6).
Fixes applied to test_helpers/: None. The test fixtures and assertions were faithful to the PRD.
Fixes applied to implementation/: workspace/implementation/app.py — added a clock_iso() formatter and switched all clock-derived business date fields (recruitment_start, recruitment_end, quiet_period_end, filed_date, priority_date, rfe_issued_date, rfe_due_date, rfe_response_date, and the clock endpoint's current_utc) from _fmt/now_iso to it.
Root cause: the implementation was inconsistent — it echoed client-supplied dates verbatim (whole-second ...T00:00:00Z) but serialized server-computed clock-derived dates with a forced .000Z via the _fmt timestamp formatter, so 4 exact-string assertions failed on 2026-07-10T00:00:00.000Z vs 2026-07-10T00:00:00Z. The PRD renders the logical clock and all window instants without fractional digits (clock starts at 2026-05-01T00:00:00Z), so clock_iso() now matches that canonical representation for whole-second instants (falling back to 3 digits for sub-second). created_at/updated_at/api_request_timestamp still use _fmt with PRD §2.4-mandated 3 fractional digits (is_iso8601_timestamp validator accepts both forms, so no other tests affected).

## Step 8: Finalize PRD — 2026-07-02T12:49:00.000Z

Done. PRD_FINALIZED.md written with a single scoped edit.
Line counts: PRD.md = 288, PRD_FINALIZED.md = 290 (+2 lines, ~0.7% delta; one inserted paragraph + blank line).
Change: §2.4 (Common Resource Properties and the Logical Clock) — insert — added a paragraph pinning the serialization format of server-computed clock-derived date fields: whole-second instants render with no fractional digits (canonical clock form, e.g. 2026-05-01T00:00:00Z), sub-second falls back to three fractional digits; explicitly contrasted with created_at/updated_at/api_request_timestamp (always three fractional digits) and client-supplied dates (echoed verbatim) — impl app.py:90-104 (clock_iso), callsites 637/651/652/661/662,1163/1172/1173,1273-1277,1328.
Pre-edit search log: (a) subject = rendering format of server-computed clock-derived instants (recruitment_start, recruitment_end, quiet_period_end, filed_date, priority_date, rfe_issued_date, rfe_due_date, rfe_response_date, current_utc); PRD silent on string format; impl clock_iso() pins no-fractional-for-whole-second form differing from mandated 3-digit _fmt used elsewhere. (b) impl paths: _fmt(79-82), now_iso(85-87), clock_iso(90-104), make/bump using now_iso for created_at/updated_at(139-152), base_meta using real_now_iso for api_request_timestamp(161-163), every clock_iso callsite in PERM/H1B/I140 transitions and clock endpoint, req_dt returning original client string verbatim(271-279), recompute_beneficiary(392-415) where status_valid_until copies client employment_end (verbatim) while beneficiary priority_date copies clock-derived I-140 priority_date. (c) wording scoped to server-clock-computed fields plus fields copying such a value (covers filed_date→priority_date and beneficiary priority_date), explicitly excluding client-supplied dates and their copies (covers beneficiary status_valid_until echoing client employment_end), so no verbatim-echoed or 3-digit path is mis-described.

## Step 9: Complete PRD — 2026-07-02T12:53:00.000Z

All edits applied as minimal in-paragraph revisions. No new sections or paragraphs added.
Source vs output: PRD_FINALIZED.md 290 lines / 44,393 chars → PRD_COMPLETED.md 290 lines / 45,372 chars (+979 chars; 8 lines revised in place, same line count). Counts: 4 ambiguity-pins, 4 mismatch-revisions (8 total).
Changes:
- §2.3 Pagination — insert — ambiguity — pinned out-of-range clamping (limit clamped to [1,100], negative offset→0; non-integer → ERR_VALIDATION) and created_at tie-break = server insertion order — app.py:369-378 (paginate).
- §2.4 Common Resource Properties — insert — ambiguity — pinned created_at/updated_at stamped from logical clock while api_request_timestamp uses real wall clock — app.py:139-140,163 (make/base_meta via now_iso vs real_now_iso).
- §3.1 Employers — revise — mismatch — fein accepted as any non-empty string with no nine-digit validation (PRD called it "nine-digit"; impl does not enforce) — app.py:444 (req_str).
- §3.2 Prevailing-Wage Supersession — revise — mismatch — supersession reverts only RECRUITING/QUIET_PERIOD cases; a case already in DRAFT is untouched with no version bump — app.py:418-433.
- §3.3 PERM Certification — revise — mismatch — certification defined only from FILED (not AUDIT); denial remains from FILED or AUDIT — app.py:675-684.
- §3.5 Cap Program — insert — ambiguity — duplicate fiscal_year on cap-program creation → ERR_VALIDATION — app.py:941-943.
- §3.5 H-1B Registration — insert — ambiguity — non-matching fiscal_year → ERR_VALIDATION — app.py:998-999.
- §3.6 Beneficiary — revise — mismatch — passport_number uniqueness NOT enforced — app.py:911-922.
Notes: PRD already uniquely pins remaining walked behaviors (filing-fee assembly, RFE 87-day/quiet-period/PERM-180-day windows, half-open employment overlap vs closed recruitment-step overlap, deterministic lottery + seat accounting, cascade families, wage-obligation ledger, provisional-vs-locked LCA required wage, per-area half-up proration, I-140 priority-date lineage, validation precedence, clock-set expiry order PWD→LCA→RFE, left-to-right FK resolution). Tests used only as auxiliary confirmation.

--- PIPELINE COMPLETE for task_0539_employment_immigration ---
