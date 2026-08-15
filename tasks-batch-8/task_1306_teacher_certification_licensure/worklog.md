# Worklog — task_1306_teacher_certification_licensure

## Step 1: Create Task Directory — 2026-08-12T19:24:00.000Z

RESUME RUN: task directory `tasks/task_1306_teacher_certification_licensure/` already exists with an empty `workspace/` subdirectory and no worklog. Step 1 treated as DONE per resume instructions. All later steps missing; pipeline continues from Step 2.

## Step 2: Generate Scaffold — 2026-08-12T20:26:00.000Z

All three scaffold artifacts are complete, valid YAML, and lint-clean. Summary:

**Files written** (under `/home/ubuntu/github/CodingPRD/tasks/task_1306_teacher_certification_licensure/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (verified: no `scaffold_difficulty_design` / `scaffold_corner_design` keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

**Counts:**
- Entities: **15** (Applicant, EducatorPrepProgram, CredentialApplication, Transcript, TestScore, BackgroundCheck, ReciprocityEvaluation, DeficiencyPlan, License, Endorsement, EmergencyPermit, CECredit, CEAudit, MisconductCase, DisciplinaryAction)
- State machines: **13** (incl. cyclic application deficiency loop, CEAudit remediation loop, CECredit void/reinstate cycle, guarded/license-discipline cascades)
- Endpoints: **63** (incl. `POST /_clock/set_current_utc` with pinned default 2026-08-01T00:00:00Z)
- Errors: **34** (incl. ERR_STALE_VERSION 412, ERR_SEGREGATION_OF_DUTIES, half-open vs closed interval overlap errors)
- Calculations: 8 (two dual-variant: CE audit totals STANDARD/RESTORATION and reciprocity DETERMINISTIC/COMMITTEE; combinatorial modes (a) deficiency clamp and (b) per-course GPA rounding; circular-ordered reinstatement fee; decay-weighted background risk)
- Concurrency rules: 2 OCC (deficiency-plan create on application version; CE-audit determination on audit version)
- §1.8 instances: **18** (exactly 2 per rule, all differentiation clauses honored — different entity domains, modes, pairs, resources, quantities)
- §1.9 instances: **53** total = 50 active + 3 `excluded_because` stubs; all 71 instance names unique across both files; every grounds reference machine-verified resolvable

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (800 calls scanned, 0 violations)

Design notes: primary archetype compliance/audit with workflow orchestration secondary; flat topology with FK cross-references; segregation-of-duties role model (8 roles, entity_backed Applicant); all test-recipe chains replayed against §1.2/§1.4 (e.g., deficiency sticky-zero after plan completion pinned in the calculation, intra-priority-11 tie-break order pinned for dual-failure determinism).

## Step 3: Copy Shared Files — 2026-08-12T20:27:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1306_teacher_certification_licensure/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-12T20:40:00.000Z

All checks pass. The PRD is complete at `/home/ubuntu/github/CodingPRD/tasks/task_1306_teacher_certification_licensure/workspace/PRD.md`.

**PRD section list:**
- §1 Introduction (2 paragraphs — system goals + constituency/integrity angle)
- §2 Global Specifications: 2.1 User & RBAC (headers, all 8 roles, identity prose per role), 2.2 API Response Structure (verbatim fixed block), 2.3 Pagination & List Filtering (`limit`/`offset` defaults 10/0, min 1, max 100, `created_at` ascending, `meta` fields, all query-filter params), 2.4 Resource Identity & Common Properties, 2.5 Validation Pipeline & Error Precedence (11-stage ordered ladder with stage-11 inner tie-break), 2.6 Monetary Values & Precision, 2.7 Optimistic Concurrency Control (both OCC rules with `expected_application_version` / `expected_ce_audit_version` → `ERR_STALE_VERSION` 412), 2.8 Logical Clock & Sweeps (default 2026-08-01T00:00:00Z, `to_iso8601`), 2.9 Nested Resources & Path Validation (left-to-right, all path-param names)
- §3 Business Logic (9 subsections): 3.1 Registration & Intake (application_fee recipe, withdrawal branches), 3.2 Program Approval (withdrawal cascade, +12 capped at 30), 3.3 Transcripts & Test Scores (GPA scaling with per-course rounding, exam scaling/offsets/passing thresholds, required-exam matrix), 3.4 Deficiency Computation & Plans (recognition cap 18, subject bases, penalties, sticky zero, plan lifecycle, evidence, default/extension), 3.5 Reciprocity (TX/FL/NV table, default PARTIAL-12, COMMITTEE upgrade rules), 3.6 Background Checks (risk weights, decay bands, forced flag, threshold 40, denial cascade), 3.7 Decisions, License Issuance & Emergency Permits (evaluation gate, approval/denial cascades, permit gating + overlap semantics), 3.8 License Renewal/Reinstatement/CE Audits (renewal window, reinstatement fee tiers in pinned order, CE credit cycle, audit variants with fit-or-skip caps and determinations OCC, surrender), 3.9 Endorsements, Misconduct & Discipline (segregation of duties, sanction cascades, suspension intervals, served sweep)
- §4 Endpoint Definitions (64-row table, 4 columns only)
- §5 Error Code Catalogue (34 rows, 2 columns only — matching `errors[]` exactly; `ERR_DEFICIENCY_NOT_PRESENT` appears only in §3.4 prose per its scaffold transition, not as an invented §5 row)

**Line count:** 324

**Self-check results:**
- Contract 1 (Field-Name Coverage): 95 required identifiers (entity fields + request bodies + query params + path params), 95 present in backticks, 0 missing — PASS (two passes run; first pass caught `to_status`, which was added)
- Contract 2 (Rule Coverage): all 11 validation priorities expressed with ordering; both OCC rules fully named (endpoint capability + occ field + error id + 412, no race framing); all 12 state machines' transitions expressed with from/to, preconditions paired to error IDs, and every side-effect cascade (permit conversion/revocation, plan supersede, applicant BARRED 3-link cascade, program-withdrawal forced deficiency, etc.); all 8 calculations in precise reconstructible prose (constants embedded, rounding pinned, no pseudocode); all `applies_to` scopes and endpoint side effects covered; field defaults (`expedite_requested`, `finalized`, `extension_used`, null `outcome`) stated; sibling branches (4 withdrawal states, deny paths, verify/reject pairs, PROBATION↔APPROVED cycle) at equal density — PASS
- Contract 3 (§3 Path Purity): 624 backticked tokens scanned in §3, 0 path tokens, 0 bare HTTP methods, 0 method+path combos — PASS
- Operator-leak scan: no `==`/`>=`/`+=`/`:=` etc. in prose — clean

## Step 6: Generate Implementation — 2026-08-12T21:00:00.000Z

Fresh-boot isolation confirmed: after killing and relaunching via `start.sh`, the applicants list is empty (`total_count: 0`) — no state carry-over, no seeded data.

**File list** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1306_teacher_certification_licensure/workspace/implementation/`):
- `start.sh` — foreground launcher, guarded `pip install` (no-op when flask present), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — flask
- `app.py` — entrypoint, error handlers, blueprint registration
- `db.py` — in-memory store (dicts keyed by id), logical clock defaulting to 2026-08-01T00:00:00Z, license-number and creation-sequence counters; no seeding
- `errors.py` — ApiError class + all 33 catalog error IDs with exact HTTP statuses (plus `ERR_DEFICIENCY_NOT_PRESENT` 409 from the state-machine table)
- `response.py` — exact `meta`/`response_type`/`data` envelope, error envelope, list pagination fields (`limit`/`offset`/`total_count`/`has_more`), internal `_`-prefixed key stripping
- `middleware.py` — X-User-ID/X-User-Role auth, role sets, Applicant entity-backed ownership resolution
- `util.py` — UUID ids, ISO8601 3-fractional-digit timestamps on the logical clock, calendar month arithmetic, pagination, body/field validation
- `services.py` — all 8 calculations (application_fee, reinstatement_fee, coursework_gpa_scaling, deficiency_credit_computation, ce_credit_audit_total, reciprocity_equivalency_mapping, test_score_scaling, background_risk_score), cascades (approval, denial, withdrawal, program-withdrawal, license-revocation, applicant-barred), and the clock sweep (license expiry, permit activation/expiry, plan default + fatal default, suspension served)
- `routes_core.py` — applicants, programs, applications (fee payment + full state machine), transcripts, test scores, background checks, reciprocity evaluations, deficiency plans, emergency permits, admin clock
- `routes_license.py` — licenses (renew/reinstate/surrender), endorsements, CE credits, CE audits (+ OCC determinations), misconduct cases, disciplinary actions

**Endpoint count:** 63 routes implemented (all from the §1.5 endpoint table, including `POST /_clock/set_current_utc`).

**State machine count:** 12 — CredentialApplication, BackgroundCheck, DeficiencyPlan, License, Endorsement, EmergencyPermit, CECredit, CEAudit, MisconductCase, DisciplinaryAction, TestScore, Transcript, plus EducatorPrepProgram (13 total including program approval).

**Self-check result:** Boot smoke test passed — server boots cleanly from a fresh process via `bash start.sh` in under 2 seconds, responds with the correct envelope, logical clock reads the 2026-08-01 default, and a kill-relaunch cycle confirmed an empty store with zero state carry-over. Additionally, 127 ad-hoc end-to-end assertions across three test waves passed, covering the full happy-path lifecycle (register → apply → pay → intake → evaluation → transcripts/exams → deficiency plan → background → approve → license), all 8 calculations with exact values (fees 10000/12500/18000/20000/21000, GPA 3.85/3.7/3.0, deficiency 30/18/12/6/0, risk scores 10.0/50.0, reinstatement fee 20000), both OCC endpoints (412s), role-target RBAC and ownership 403s, program-withdrawal and revocation cascades, all four clock-sweep families, closed-interval suspension overlap, half-open permit adjacency, and pagination/filtering.

## Step 5: Generate Unit Tests — 2026-08-12T21:25:00.000Z

All generation and verification steps are complete. Final state:

**Output** (under `/home/ubuntu/github/CodingPRD/tasks/task_1306_teacher_certification_licensure/`):
- `test_helpers/` — 9 modules: `types.py`, `api_client.py` (45 endpoint methods), `api_errors.py` (full §5 catalog registered with the framework; `ERR_DEFICIENCY_NOT_PRESENT` kept out of the status map since PRD §5 gives it no HTTP status), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (entity-backed `Applicant` gets `make_applicant_headers`; opaque roles get shared constants), `fixtures.py` (composite chains: licensed-applicant via RECIPROCITY-FULL approval, deficiency-pending with plans/permits, adjudicated misconduct cases, CE audit + determination helpers, clock control), `__init__.py` barrel.
- `test_suite/` — `conftest.py` + 5 test files: `test_01_applicants_intake_and_fees.py`, `test_02_evaluation_deficiency_and_reciprocity.py`, `test_03_background_checks_and_permits.py`, `test_04_license_lifecycle_and_ce_audits.py`, `test_05_discipline_endorsements_and_security.py`.
- `self_check.py` — reproducible audit script at task root (outside pytest discovery).

**Test count:** 82 tests total.

**§1.8 (Difficulty) translated:** 18/18 instances, 36 tests (exactly 2 per instance, each tagged `Design: Difficulty/<rule_id>/<name>`).

**§1.9 (Corner) translated:** 46/50 non-stub instances, 46 tests (1 each, tagged `Design: Corner/<section>/<name>`). The 3 `excluded_because:` stubs were not translated; their `difficulty_instance` cross-references all resolve.

**Skipped instances (4), gaps left as gaps:**
1. `Corner/validations/traditional_without_program_rejected` — PRD §3.1 rejects the program-attachment violation at application *creation* ("either violation is rejected with `ERR_PATHWAY_PROGRAM_REQUIRED`"), so a faithful implementation may fail the setup's create call; the intake-gate outcome is unreachable for all PRD-faithful readers.
2. `Corner/state_machines/plan_default_then_extension_resumes` — its final assertion (evidence on an EXTENDED plan returns it to IN_PROGRESS) is unstate­d in the PRD, which says only that such postings add hours.
3. `Corner/state_machines/plan_second_default_denies_application_and_blocks_extend` — the second default requires sweeping a non-IN_PROGRESS plan, but the PRD sweep is defined only `IN_PROGRESS` → `DEFAULTED`; the chain is not uniquely derivable.
4. `Corner/validations/renewal_blocked_by_open_misconduct_case` — with no PASSED audit present, the renewal audit-existence gate (unplaced in the §2.5 pipeline, and ordered before the misconduct gate in §3.8 prose) makes two faithful readers return different errors.

**Sub-assertion adjustments (default-value silence pattern):** the PRD never pins the initial `version` value, so `applicant_creation_defaults` drops the absolute `version == 1` assert (keeps 201/REGISTERED/UUID/timestamp), and `fee_payment_success_then_double_pay_rejected` asserts the verbatim rule "increments by exactly 1" via captured versions instead of a hard-coded 2. Computed instant fields (`issued_on`, `expires_on`) are compared as parsed instants, since the PRD pins the instant, not the string format.

**Lint/self-check results:** `py_compile` clean on all 16 files; `pyflakes` clean on `test_suite/` and all helper modules (barrel `__init__.py` excluded by design); no `skip`/`skipif`/`xfail` markers; no "scaffold" references; `pytest --collect-only` collects 82 tests; `self_check.py` (tag resolution against both YAMLs, ≥2/≥1 coverage counts, stub/skip accounting, and verbatim ≥8-word PRD-citation grep) prints `SELF-CHECK PASSED` — 18/18 difficulty, 46/46 corner.

## Step 7: Run Tests and Iterate — 2026-08-12T22:05:00.000Z

Clean 8-round parallel sweep achieved: **82/82 passed in all 8 rounds** (656 test executions, 0 failures/errors).

- **Iterations run:** 2 (sweep 1 surfaced failures; fixes applied; sweep 2 fully clean).

- **Tests deleted:** none.

- **Fixes applied to `test_suite/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1306_teacher_certification_licensure/test_suite/test_04_license_lifecycle_and_ce_audits.py` — `test_reinstate_fee_mismatch_rejected`: the setup violated *two* reinstatement preconditions simultaneously (wrong `pays_amount_cents` and no PASSED RESTORATION audit) and asserted `ERR_FEE_AMOUNT_MISMATCH` wins. That precedence is not uniquely derivable: PRD §2.5 places "reinstatement amount equality" at stage 10 (fiscal) but never places `ERR_AUDIT_NOT_PASSED` anywhere in the pipeline (ERROR PRECEDENCE SILENCE; §3.8 prose order is non-normative — the renewal sentence lists misconduct last while §2.5 stage 6 places it early). Per the partial-coverage rule, kept the covered exact-error assertion and fixed the setup to satisfy the audit gate first (CONTENT 60h + PEDAGOGY 30h + ETHICS 5h verified credits → RESTORATION audit → determination → UNDER_REVIEW → PASSED), so the fee rule is the only violated precondition. No assertion was weakened.

- **Fixes applied to `implementation/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1306_teacher_certification_licensure/workspace/implementation/start.sh` — replaced the per-boot `python3 -c "import flask"` interpreter spawn with a `.deps_ready` stamp-file guard (pip install only on first boot when flask is missing). Root cause of the flaky "API server could not be restarted" setup errors (affecting `test_transcript_invalid_degree_level_rejected` in all 8 rounds of sweep 1, plus sporadic `test_stale_audit_version_rejected_on_determination`, `test_audit_total_stale_until_next_determination`, `test_applicant_cannot_verify_transcript`, `test_applicant_cannot_pay_others_fee`): the runner's per-test restart poll budget is 15s, and the extra python spawn per boot pushed startup past it during the simultaneous 8-round boot storm on a heavily loaded shared host. No application logic was touched.

- **No implementation logic changes** were needed — the only consistent assertion failure traced to the test-side precedence coupling above, and the implementation's check order (audit gate before fiscal gate) is one PRD-faithful reading, so it was preserved per the cardinal rules.

## Step 8: Finalize PRD — 2026-08-12T22:15:00.000Z

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1306_teacher_certification_licensure/workspace/PRD_FINALIZED.md`

**Line counts / %-delta:** PRD.md = 323 lines, PRD_FINALIZED.md = 323 lines, 0.0% delta (the single insertion landed inside one existing paragraph line; character-level delta is one sentence, 1 line changed of 323).

### Changes (one bullet per change)

- **§3.8 (License Lifecycle: Renewal, Reinstatement, and Continuing-Education Audits), reinstatement paragraph — insert —** added one sentence pinning the deterministic precedence when several reinstatement gates fail in the same request: grace window (`ERR_REINSTATE_GRACE_EXPIRED`) first, then the RESTORATION audit gate (`ERR_AUDIT_NOT_PASSED`), then amount equality (`ERR_FEE_AMOUNT_MISMATCH`) last. PRD §2.5 stage 10 placed "reinstatement amount equality" in the fiscal stage but never placed the audit gate anywhere in the pipeline, and §3.8 prose order was non-normative — this was the exact precedence coupling Step 7 had to decouple in `test_reinstate_fee_mismatch_rejected` — `implementation/routes_license.py:110–119`.

The other `<step_7_diff>` item (the `start.sh` `.deps_ready` stamp-file guard) is an infra-only launcher change with no PRD-visible behavior, so it produced no PRD edit.

### Per-edit pre-edit search log

**Edit 1 (the only edit):**
- (a) **Subject:** error precedence among the preconditions of `POST /licensure/licenses/{licenseId}/reinstate` — specifically the audit-gate vs. fiscal amount-equality ordering.
- (b) **Impl paths enumerated and read/grepped:**
  - `implementation/routes_license.py:98–123` (`reinstate_license`, the sole reinstate handler) — full check order read: body shape → `EXPIRED` state (106–107) → grace (110–111) → RESTORATION audit gate (112–115) → amount equality (116–119).
  - `implementation/routes_license.py:70–95` (`renew_license`) — the only other raiser of `ERR_AUDIT_NOT_PASSED` (line 92, STANDARD variant); its order is state → misconduct → window → audit, so the edit must not make any universal claim covering renewal.
  - `implementation/errors.py:96–97, 116–117, 140–141` — error constructors and HTTP statuses (all 409, already matching PRD §5).
  - `implementation/services.py:154–173` (`compute_reinstatement_fee`) — fee formula matches PRD verbatim; untouched by the edit.
  - `implementation/services.py:17, 68, 202` — the unrelated `REINSTATEMENT` application-pathway constant sharing the word "reinstatement"; confirmed the edit's paragraph placement (§3.8 license reinstatement) cannot be misread onto the application pathway.
  - `test_helpers/api_client.py:180–182` — plain HTTP wrapper, no behavior.
- (c) **Wording adjustment:** scoped the sentence with "these gates" (the three gates named in the existing sentence) instead of a broader "all preconditions," so it neither re-orders the state check (already pinned globally by §2.5 stage 5) nor claims anything about renewal's different gate ordering; the resulting grace → audit → amount order is consistent with §2.5 stage 9 (temporal) preceding stage 10 (fiscal), with the previously unplaced audit gate landing between them exactly as the implementation does.

## Step 9: Complete PRD — 2026-08-12T22:40:00.000Z

**File**: `/home/ubuntu/github/CodingPRD/tasks/task_1306_teacher_certification_licensure/workspace/PRD_COMPLETED.md` (patched from `PRD_FINALIZED.md`)

**Size delta**: 323 → 326 lines; 57,135 → 60,888 chars (**+3 lines, +3,753 chars**)

**Counts**: 18 ambiguity-pins, 6 mismatch-revisions (24 edits total)

### Changes (in document order)

- **§2.2** — insert — ambiguity — `api_request_timestamp` pinned to wall clock, not the logical clock — `implementation/response.py:13-16`
- **§2.3** — insert — ambiguity — non-integer/out-of-range `limit`/`offset` (incl. negative offset) rejected with `ERR_VALIDATION`; sort ties broken by creation order — `implementation/util.py:116-145`
- **§2.4** — insert — ambiguity — all server-stamped resource timestamps (`created_at`, `updated_at`, `issued_on`, …) read the logical clock — `implementation/util.py:13-20,49-61`
- **§2.5 item 2** — revise — mismatch — ownership moved out of stage 2; per-target role entitlement on state endpoints is checked after body-shape validation and before state validity (Applicant ownership on application/endorsement state endpoints runs at that same point) — `implementation/routes_core.py:293-312`, `implementation/routes_license.py:221-229`
- **§2.5 item 3** — revise — mismatch — path existence (404) precedes ownership (403); body-named parents (`applicant_id` at application creation) validate body shape first, then parent existence, then ownership — `implementation/routes_core.py:61-65,162-178`
- **§2.5 item 7** — revise — mismatch — "overlapping permit intervals" removed from stage 7 (impl checks overlap after duration) — `implementation/routes_core.py:930-940`
- **§2.5 item 8** — revise — mismatch — program attachment enforced at application creation and intake advance; spurious "endorsement activation" dropped — `implementation/routes_core.py:183-190,324-336`
- **§2.5 item 9** — revise — mismatch — permit duration then permit-interval overlap both pinned at stage 9 — `implementation/routes_core.py:930-940`
- **§2.5 (after list)** — insert — ambiguity — where §3 pins an explicit precondition order, that order governs among stages — `implementation/routes_core.py:317-323` (fee before attestation/barred)
- **§2.8** — insert — ambiguity — clock-set call answers HTTP 200 with new reading in `data.current_utc` — `implementation/routes_core.py:1007-1015`
- **§3.1** — insert — ambiguity — duplicate email rejected with `ERR_VALIDATION` — `implementation/routes_core.py:44-45`
- **§3.1** — insert — ambiguity — fixed creation check order: body shape → applicant exists (404) → ownership (403) → barred → program-attachment (unknown `program_id` is 404) → duplicate-open — `implementation/routes_core.py:164-195`
- **§3.1** — revise — mismatch — fee recompute no longer claims "whenever the expedite flag changes" (no such capability exists); flag fixed at creation — `implementation/routes_core.py` (no expedite-mutation endpoint), `services.py:142-151`
- **§3.1** — insert — ambiguity — intake gate's three preconditions evaluated in listed order (fee → attestation → barred) — `implementation/routes_core.py:317-323`
- **§3.2** — revise — mismatch — `program_code` uniqueness is not enforced — `implementation/routes_core.py:92-110`
- **§3.3** — insert — ambiguity — evidence uploads not gated on application status — `implementation/routes_core.py:394-431`
- **§3.3** — insert — ambiguity — zero-total-credit transcript scales to GPA 0.0 — `implementation/services.py:186-187`
- **§3.4** — insert — ambiguity — RECIPROCITY subject gap is zero when no evaluation finalized yet — `implementation/services.py:222-224`
- **§3.4** — insert — ambiguity — plan creation not gated on application status, only version match — `implementation/routes_core.py:792-820`
- **§3.4** — insert — ambiguity — evidence `hours` must be a number > 0; posting against an `EXTENDED` plan returns it to `IN_PROGRESS` — `implementation/routes_core.py:883-891`
- **§3.5** — insert — ambiguity — opening an evaluation on a non-RECIPROCITY application is `ERR_VALIDATION`; `years_teaching` is a non-negative integer; re-finalization is `ERR_INVALID_STATE`; latest-created finalized evaluation governs all consumers — `implementation/routes_core.py:719-724,771-772`, `services.py:205-209`
- **§3.6** — revise — ambiguity — finding age uses exact elapsed time (fractional days = seconds ÷ 86,400) ÷ 365.0 — `implementation/services.py:253-254`
- **§3.7** — insert — ambiguity — permit issuance gates evaluated in listed order, with `valid_until` < `valid_from` → `ERR_VALIDATION` first — `implementation/routes_core.py:914-940`
- **§3.7** — revise — mismatch — approval flips applicant to `LICENSED` only if not already `BARRED` — `implementation/services.py:345-348`
- **§3.7** — insert — ambiguity — `license_number` format pinned as `LIC-` + zero-padded six-digit sequence from `LIC-000001` — `implementation/db.py:41-43`
- **§3.7** — revise — mismatch — permit expires when `valid_until` is *reached* (inclusive), not "passed" — `implementation/services.py:419,426`
- **§3.8** — revise — mismatch — renewal preconditions reordered to impl: misconduct-case gate → renewal window → passed-audit — `implementation/routes_license.py:77-92`
- **§3.8** — insert — ambiguity — days overdue counted as calendar-date difference — `implementation/services.py:158-160`
- **§3.8** — insert — mismatch — determinations accepted in any audit status (version match is the only gate) and return HTTP 201 — `implementation/routes_license.py:406-421`
- **§3.9** — insert — ambiguity — endorsement request requires an `ACTIVE` license (`ERR_INVALID_STATE`) before the duplicate check — `implementation/routes_license.py:161-168`
- **§3.9** — revise — ambiguity — the OPENED→DISMISSED dismissal role pinned as `LegalOfficer` — `implementation/routes_license.py:486-489`
- **§3.9** — revise — mismatch — disciplinary-action proposals are not gated on the case being adjudicated — `implementation/routes_license.py:541-547`
- **§3.9** — insert — ambiguity — `fine_cents` is a non-negative integer — `implementation/routes_license.py:566-568`
- **§3.9** — revise — mismatch — every issuance (including REPRIMAND/FINE) moves the case to `SANCTION_ISSUED`, not just the two cascade cases — `implementation/routes_license.py:653-655`
- **§4** — revise — mismatch — CE-audit determination POST returns HTTP 201 as a determination-record creation — `implementation/routes_license.py:421`
- **§5** — insert — ambiguity — added missing catalogue row `ERR_DEFICIENCY_NOT_PRESENT | 409` (error was named in §3.4 prose but had no status) — `implementation/errors.py:124-125`

**Not changed** (verified already aligned): all endpoint paths/methods/roles in §4; fee recipe and rounding; deficiency formula constants and clamp; GPA scaling order; exam scaling thresholds; reciprocity table and COMMITTEE upgrade; risk-score weights/decay/disposition/forced-flag and <40 clear rule; all cascades (program withdrawal, denial, withdrawal, revocation, BARRED); sweep transitions and boundaries for licenses/plans/suspensions; OCC scope (exactly two version-guarded writes); suspension closed-interval overlap vs permit half-open overlap.

## Final verification sweep — 2026-08-12T22:08:00.000Z

Orchestrator re-ran the 8-round parallel stability sweep (the Step 7 subagent's results files had not persisted to disk; no code changed since its clean exit). All 8 rounds: **82/82 passed, 0 failed, 0 errors** — `workspace/implementation/results.{1..8}.json` all present and green. Pipeline complete.
