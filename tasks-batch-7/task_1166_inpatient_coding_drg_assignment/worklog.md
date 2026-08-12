# Worklog — task_1166_inpatient_coding_drg_assignment

## Step 1: Create task directory — 2026-08-11T07:26:00.000Z

Task directory `tasks/task_1166_inpatient_coding_drg_assignment/` and its `workspace/` subdirectory were pre-assigned and already exist; auto-index scan skipped per instruction. Treating Step 1 as done.

## Step 2: Generate scaffold — 2026-08-11T08:04:00.000Z

All three scaffold artifacts are generated, lint-clean, and verified on disk.

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    58
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     48
  Calls scanned (§1.8+§1.9):  564

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Output files
- `/home/ubuntu/github/CodingPRD/tasks/task_1166_inpatient_coding_drg_assignment/SCAFFOLD.yaml` (74 KB; §1.0–§1.7, no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1166_inpatient_coding_drg_assignment/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (64 KB; single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1166_inpatient_coding_drg_assignment/SCAFFOLD_CORNER_DESIGN.yaml` (92 KB; single key `scaffold_corner_design`)

## Summary counts
- Entities: 14 (PatientAccount, Chart, ChartDeficiency, DiagnosisLine, ProcedureLine, Coder, CodingAssignment, CodedCase, Bill, DnfbSweep, CodingAudit, AuditFinding, PostPaymentReview, RebillRequest)
- State machines: 12 (cyclic: CodingAssignment rework loop RETURNED→IN_PROGRESS; Bill post-payment cycle PAID→REVIEW→REBILL_REQUIRED→PAID/REBILLED)
- Endpoints: 58 (flat topology; filtered-list GETs give every FK reverse-reachability; includes `POST /_clock/set_current_utc` with pinned default 2026-05-01T00:00:00Z)
- Error catalog: 34
- Validations: 35 priority-ordered rows (auth → authz → existence → state → OCC(412) → safety → constraint → temporal → referential → fiscal)
- Difficulty instances: 18 (9 rules × 2), all differentiation clauses honored
- Corner instances: 60 total (48 active + 12 `excluded_because` stubs, all stubs resolving to real §1.8 instances); 78 globally unique instance names

## Design decisions worth noting
- **Beyond-expert calibration**: per the difficulty parameter, the scaffold deliberately exceeds the Expert band on every axis (14 entities, 58 endpoints, 34 errors) while keeping density high — the hard mechanics are the dual-variant grouping/accuracy calcs, the 4-hop finding-apply cascade, and priority-conflict pairs, not surface area.
- **Domain-faithful coupling**: POA=N excludes CC/MCC from DRG severity (HAC rule), which is what makes the audit-apply cascade financially material (650000 → 1365000 cents on a single POA flip); pre-bill audits are blocked once a bill is FINAL_BILLED, forcing the rebill-after-post-payment path as the only post-payment correction channel.
- **All assertion literals pre-computed** (weights: MS 1.0/1.4/2.1, AP SOI 0.9–2.5; base rate 650000¢; outlier share 0.80; accuracy 0.9500 boundary = 19/20 lines; timely filing 2026-01-01 + 120d = 2026-05-01 exactly == default clock, giving a free inclusive-deadline test).
- **Segregation of duties** as role model: auditor ≠ subject coder; rebill approver ≠ requesting clerk — both enforced by X-User-ID comparison.
- **Two OCC concurrency rules** (CodedCase regroup, Rebill create), each with stale-version corner tests using `${var} - 1` expressions per lint rule (e).
- **Selector determinism** for auto-assignment (workload ASC, tie → created_at ASC); the corner test sets the logical clock between coder creations so created_at tie-breaks are deterministic.
- One mid-authoring fix: YAML flow-style `grounds: [...]` entries containing `errors[...]` needed quoting — repaired and re-validated; no content changes resulted.

## Step 3: Copy shared files — 2026-08-11T08:06:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1166_inpatient_coding_drg_assignment/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-11T08:20:00.000Z

All verifications pass. The PRD is complete on disk at `/home/ubuntu/github/CodingPRD/tasks/task_1166_inpatient_coding_drg_assignment/workspace/PRD.md`.

## Summary

**Output:** 346 lines at `tasks/task_1166_inpatient_coding_drg_assignment/workspace/PRD.md`

**Sections covered:**
- §1 Introduction (2 paragraphs, business-context angle: HIM coding department between clinical documentation and revenue cycle)
- §2 Global Specifications — 10 subsections: 2.1 RBAC (5 roles with per-role `identity` prose: Coder/Auditor entity-backed by `Coder`, CodingManager/BillingClerk/ComplianceOfficer opaque), 2.2 response envelope (byte-identical verbatim block, verified programmatically), 2.3 pagination (limit 10/1/100, offset 0, created_at ascending), 2.4 common resource properties (all 14 entities carry full `id`/`created_at`/`updated_at`/`version`), 2.5 logical clock (default `2026-05-01T00:00:00Z`, `to_iso8601`), 2.6 reimbursement arithmetic and precision (integer cents, per-component round-half-up pinned order, 4-decimal weights/accuracy, 2-decimal productivity), 2.7 OCC (both rules with exact field/error/412), 2.8 validation ladder (explicit 10-tier precedence incl. credential-before-workload on start), 2.9 ownership and segregation of duties, 2.10 derived fields and immediate consistency
- §3 Business Logic — 9 subsections organized by revenue-cycle timeline: accounts/chart completeness → coding queue → code capture → submission/grouping/reimbursement → acceptance/rework/productivity → billing → DNFB sweeps → audits/findings → post-payment review/rebill
- §4 Endpoint table: 58 rows, 4 columns only
- §5 Error catalogue: 34 rows, 2 columns only

**Hard Contract reports:**
```
Field coverage check:
- entities[].fields + endpoint inputs/query/path params: 95 required, 95 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] priority ladder: 10 tiers expressed in §2.8, 0 missing
- concurrency_rules[] OCC: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: all 14 machines / ~35 transitions expressed with preconditions + side effects, 0 missing
- calculations[]: 6 checked (queue_priority, drg_grouping dual-variant, expected_reimbursement pinned rounding, coder_accuracy dual-variant, dnfb_aging, productivity), 6 fully in prose, 0 missing
- validations[] conditions: 34 error ids all matchable to triggers in §2/§3, 0 missing
- endpoints[].side_effects / applies_to: all expressed (incl. 4-hop finding-apply cascade, 2-hop accept cascade, sweep priority recompute), 0 missing
- fields[] structured content: defaults/enums/nullability reconstructible, 0 missing
- sibling symmetry: MS_DRG vs AP_DRG, APPLY vs DISMISS, approve vs cancel, code vs financial accuracy — equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 481
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Notable generation decisions:**
- Constants embedded with unit conversions per skill guidance (e.g., 650000-cent base rate, 100000-cent charge blocks, 120-day timely-filing, 0.9500 accuracy flag, 30-day productivity basis, 25-point DNFB boost, 150-point score cap).
- All six calculations rendered as reconstruction-safe prose (no operator syntax, no fuzzy words); the pinned per-component rounding order for expected reimbursement is stated explicitly as forbidden to reorder.
- §3 refers to endpoints only via state-transition framing (`RETURNED` → `IN_PROGRESS`), role + verb ("a `CodingManager` runs a sweep"), or capability description ("a `CodingManager`-only capability advances the clock"); HTTP contract lives solely in §4.
- Rules without scaffold-nominated error ids (e.g., `discharge_at` must be later than `admit_at`, uniqueness of `mrn`/one-chart-per-account) are stated as constraints without inventing error mappings.
- The withheld design files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were not opened, and no other `tasks/task_*/` directory was read.

## Step 5: Generate unit tests — 2026-08-11T08:55:00.000Z

Generation complete. Summary:

## Files written

**test_helpers/** (9 files, under `/home/ubuntu/github/CodingPRD/tasks/task_1166_inpatient_coding_drg_assignment/test_helpers/`)
- `types.py` — 14 entity TypedDicts (all carry id/created_at/updated_at/version per PRD §2.4) + 17 status/enum classes
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (50 methods)
- `api_errors.py` — all 34 error IDs + HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` + coder-productivity and bill-money invariant checkers
- `factories.py` — payload factories for every creatable resource
- `constants.py` — MS/AP weight tables, reimbursement constants, priority tiers, credential ranks, 120-day timely filing
- `test_users.py` — shared headers for opaque roles + per-instance `make_coder_headers`/`make_auditor_headers` for the entity-backed roles
- `fixtures.py` — composite chains: `setup_ready_chart` → `setup_assigned` → `setup_in_progress` → `setup_submitted_case` → `setup_accepted_case` → `setup_ready_bill` → `setup_paid_bill` → `setup_open_review` → `setup_pending_rebill`, plus audit helpers
- `__init__.py` — barrel export

**test_suite/** (9 files): `conftest.py` + `test_01`…`test_08` organized by concern (accounts/charts, queue/priority/sweeps, line capture, submit/grouping, assignment lifecycle, billing/rebill, audits, security/existence/OCC).

## Test counts
- **Queue A (Difficulty): 18/18 instances covered, 36 tests** (exactly 2 per instance)
- **Queue B (Corner): 48/48 non-stub instances covered, 49 tests** (occ_regroup got 2: stale-rejected + current-version-succeeds)
- **12 corner `excluded_because:` stubs not translated**; all 12 cross-references verified to resolve to real §1.8 instance names
- **85 tests total; 0 instances skipped**

## Verification results
- `python -m py_compile`: all 17 files pass
- Every test docstring ends with exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line resolving to a real instance (AST audit clean)
- Every test docstring carries a PRD citation with a ≥8-word substring surviving literal grep of PRD.md (85/85 pass)
- pyflakes clean (barrel `__init__` re-export warnings excluded); no "scaffold" mentions in generated code; all test modules import successfully with `test_helpers` on the path

## Key adjudication notes
- **bill_finalize_requires_chart_coded** (queue A): the recipe finalizes a DRAFT bill over a SUBMITTED chart, where PRD §2.8 names "finalizing from DRAFT" as `ERR_INVALID_STATE` while §3.6 names `ERR_CHART_NOT_CODED` for uncoded charts — both same-tier. Per the skill's error-precedence remedy, both tests assert via `validate_error_is_one_of([ERR_CHART_NOT_CODED, ERR_INVALID_STATE])` plus state-unchanged checks, rather than skipping.
- **account_creation_defaults**: asserted PRD-derivable defaults verbatim (status ADMITTED, dnfb_flag false, discharge_at/dnfb_flagged_at null); `version` is asserted as a positive integer rather than pinned to exactly 1, since PRD §2.4 says only that it "increments with every modification" without pinning the initial value.
- All literal expected values (priority 100/50/75, expected_reimbursement 650000/910000/1170000/1365000/2130000, accuracy 0.9500/0.7500/0.7143, delta 715000, net_receivable −200000/0) were copied verbatim from the design indices and cross-checked against the PRD formulas.

## Step 6: Generate implementation — 2026-08-11T08:55:00.000Z

Implementation complete. Summary:

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_1166_inpatient_coding_drg_assignment/workspace/implementation/`)

- `start.sh` — executable, guarded pip install (`if ! python3 -c "import flask"`), `exec python3 app.py`; binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — `flask>=3.0`
- `app.py` — Flask entry point, envelope-shaped error handlers for `ApiError`/HTTPException/500
- `db.py` — in-memory `Store` (14 dicts), logical clock defaulting to `2026-05-01T00:00:00Z`, `stamp_new`/`touch` (version bump + `updated_at` refresh on every mutation, cascades included)
- `errors.py` — `ApiError` + all 33 scaffold error IDs
- `response.py` — exact envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; list `meta` gains `limit`/`offset`/`total_count`/`has_more`); pagination validation (limit default 10, 1–100; offset ≥ 0)
- `middleware.py` — `X-User-ID`/`X-User-Role` auth, 5 roles, 401/403
- `validators.py` — body/field/datetime/enum validators (tier-7 `ERR_INVALID_REQUEST`)
- `services/core.py` — constants, cross-aggregate lookups, 14 serializers (3-fractional-digit `...Z` timestamps)
- `services/calc.py` — all 6 calculation rules with Decimal + ROUND_HALF_UP: queue priority (tiered aging, caps 30/150), dual-variant DRG grouping (MS highest-only vs AP SOI points, `poa=N` excluded), pinned-order expected reimbursement (per-component rounding), DNFB aging scan (exact fractional days, `>=` boundary flags, newly-flagged only), productivity (x/30, 2dp), both accuracy variants (4dp)
- `routes/` — 13 blueprints covering every resource group

## Route count

58/58 — registered (method, path) pairs match the SCAFFOLD.yaml endpoint table exactly (missing: none, extra: none; Flask's built-in `/static` route disabled).

## Verification performed

- All 22 Python files pass `python -m py_compile`; app imports cleanly
- `bash start.sh` boots fresh and serves HTTP; store starts empty (no seeding anywhere)
- ~75 live smoke assertions passed across two booted instances: auth ladder, account/chart/deficiency interlock (last-resolver readies chart), credential gating + auto-assign (workload/created_at ordering), priority score math (verified 110 and 130→150 with DNFB boost), POA/sequence/manifestation rules, submit → MS_DRG grouping (WITH_MCC → 2273000), OCC regroup 412 + AP_DRG variant switch (SOI_2 → 2156000), accept cascade (chart CODED, bill DRAFT→READY mirror, coder stats 0.07/day), finalize/pay/review/rebill with SoD 403 and cancel-restores-net invariant, audit sampling/self-audit/window-overlap/adjacency, finding APPLY 4-hop cascade (delta −260000, accuracies 0.5/0.6, credential flag), DNFB sweep (boundary flagged, no re-flag, ordering), rework loop (edit while RETURNED, one case per chart recomputed on re-submit), timely-filing exact-deadline allowed / past-deadline 422

## Notable design decisions

- **Validation ladder**: existence (404) → state (409) → OCC (412) → business-safety (422/403) → constraints (400/422) → temporal → referential → fiscal; per PRD §3.3's specific sentence, line-capture checks chart `IN_CODING` (409) *before* coder ownership (403), and submit-check ordering follows the scaffold's precondition list
- **Chart created on an already-discharged account** evaluates the readiness interlock immediately (born `READY_FOR_CODING`), otherwise it could never advance
- **Re-submit after rework** recomputes the chart's single CodedCase in place (version bumps; variant preserved), keeping one case per chart
- **OCC fields required** on regroup/rebill-create (missing → 400; mismatch → 412)
- **Audit cascade**: `PRINCIPAL_RESEQUENCE` retargets the target line's code and makes it the sole ACTIVE principal; `CC_MCC_ADDED` appends a line with `poa=Y` and next sequence; `PROCEDURE_ADDED` appends with `is_or=true`
- **Division guards**: accuracy computation treats empty denominators as perfect 1.0
- Undeclared method/path combos fall through to the envelope with 404/405 rather than HTML error pages

## Step 7: Run tests and iterate — 2026-08-11T09:15:00.000Z

Summary:

- **Iterations run:** 2 (baseline sweep: 80/85 in all 8 rounds, 5 distinct failures; iteration 2 after fixes: 85/85 in all 8 rounds).

- **Tests deleted:** none — every failing test traced to a verbatim PRD sentence.

- **Fixes applied to `test_suite/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1166_inpatient_coding_drg_assignment/test_suite/test_02_queue_priority_and_sweeps.py` — `test_priority_score_combines_tier_amount_acuity` and `test_priority_score_persisted_on_get`: changed `discharge_at` from `2026-04-25T10:00:00Z` to `2026-04-25T00:00:00Z`. PRD §2.5 pins the default clock at `2026-05-01T00:00:00Z` and §3.2 pins "elapsed time … truncated down to whole days"; the old timestamp is 5 days 14h before the clock → 5 whole days → tier 40, so the PRD-correct score was 70 (what the implementation returned), not the asserted 100. The new timestamp lands exactly 6 whole days before the clock, matching the test's documented 70+20+10+0=100 scenario.
  - `/home/ubuntu/github/CodingPRD/tasks/task_1166_inpatient_coding_drg_assignment/test_suite/test_07_audits_and_findings.py` — `test_finding_for_unsampled_case_rejected`: added `"target_diagnosis_id": ctx["dx_line_ids"][0]` to the finding payload. PRD §3.8 states corrective findings (`POA_CORRECTION` among them) "identify the line being corrected via `target_diagnosis_id`", and §2.8 tier 7 lists "malformed or missing input (ERR_INVALID_REQUEST)" ahead of the coding-rule violations within the same tier — so the payload without it was malformed relative to PRD and the missing-input check legitimately fired before the sample-membership check. With a valid target line, the out-of-sample refusal (`ERR_CASE_NOT_IN_SAMPLE`, 422) is the check that fires, as the test intends.

- **Fixes applied to `test_helpers/`:** none.

- **Fixes applied to `implementation/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1166_inpatient_coding_drg_assignment/workspace/implementation/routes/assignments.py` — added `ERR_WORKLOAD_OVERLAP` to the `errors` import. `start_assignment` referenced the constant without importing it, so the PRD §3.3 workload-overlap path raised `NameError`, which the catch-all handler surfaced as a 500 `ERR_INVALID_REQUEST` instead of the required 409 `ERR_WORKLOAD_OVERLAP` (reproduced manually: `"name 'ERR_WORKLOAD_OVERLAP' is not defined"`).

Final state: 8/8 parallel rounds green, 85/85 tests passing in every round, no flakiness observed.

## Step 8: Finalize PRD — 2026-08-11T09:25:00.000Z

Done. `PRD_FINALIZED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_1166_inpatient_coding_drg_assignment/workspace/PRD_FINALIZED.md`.

## Summary

**Line counts and delta:** PRD.md = 346 lines, PRD_FINALIZED.md = 346 lines (0% line-count delta; one line revised in place, no lines added or removed).

**Changes (1 total):**
- **§2.8 (Validation Order and Error Precedence), tier 7** — revise — appended the sentence: "Within this tier the input-validation failures are evaluated before the coding-rule violations, so a request that is both malformed and in breach of a coding rule is reported as `ERR_INVALID_REQUEST`." — pins the within-tier-7 evaluation order the implementation exhibits; without it, an out-of-sample finding payload missing `target_diagnosis_id` could legitimately be implemented to return 422 `ERR_CASE_NOT_IN_SAMPLE` instead of the implementation's 400 `ERR_INVALID_REQUEST` — `implementation/routes/audits.py:131-143` (missing-target 400 at :131-133 fires before sample-membership 422 at :141-143).

**Items verified as needing no PRD edit:**
- Priority-score test fix (`test_02`): pure fixture correction. PRD §3.2 already pins whole-day truncation ("elapsed time … truncated down to whole days", tiers "two days ago or less / three to five / six to ten / eleven or more"); impl `services/calc.py:42-49` (`int(seconds // 86400)`, `days <= 2 / <= 5 / <= 10`) matches the PRD exactly.
- Workload-overlap impl fix (`routes/assignments.py` import): impl defect fixed toward the PRD. PRD §3.3, §2.8 tier 8, and §5 already pin the capacity-of-one rule, the credential-before-workload ordering, and the 409 `ERR_WORKLOAD_OVERLAP` mapping; impl `routes/assignments.py:157-161` now matches.

**Per-edit pre-edit search log (edit 1):**
- (a) Subject: within-tier-7 evaluation order — `ERR_INVALID_REQUEST` (missing/malformed input, invalid enums) versus the named coding-rule violations (`ERR_PRINCIPAL_DX_REQUIRED`, `ERR_INVALID_PRINCIPAL_CODE`, `ERR_DUPLICATE_SEQUENCE`, `ERR_MANIFESTATION_ORDER`, `ERR_ASSIGNMENT_EXISTS`, `ERR_NO_ELIGIBLE_CODER`, `ERR_CASE_NOT_IN_SAMPLE`).
- (b) Impl paths enumerated and read/grepped: `routes/audits.py:102-156` (create_finding: 400s at :126-140 before `ERR_CASE_NOT_IN_SAMPLE` at :142); `routes/lines.py:58-110` (create_dx_line: input 400s at :87-93 before `ERR_DUPLICATE_SEQUENCE` at :96); `routes/lines.py:135-180` (patch_dx_line: 400s at :150-163 before `ERR_DUPLICATE_SEQUENCE` at :167); `routes/assignments.py:40-92` (create_assignment: `due_at` 400 at :63 before `ERR_ASSIGNMENT_EXISTS` 409 at :65 before `ERR_NO_ELIGIBLE_CODER` 422 at :72); `routes/assignments.py:171-224` (submit: four named violations in PRD §3.4's listed order, no input checks involved); `routes/assignments.py:117-141` (assign); `routes/reviews.py:96-141` (rebill; no tier-7 named violations); `routes/accounts.py`, `bills.py`, `coders.py`, `charts.py`, `deficiencies.py` via grep of all `fail(` calls (only `ERR_INVALID_REQUEST`, no named tier-7 violations coexisting).
- (c) Wording adjustment: scoped the sentence strictly to "within this tier" and only input-validation-before-coding-rules, making no claim about ordering among the named coding-rule violations themselves (submit's checks happen to run in §3.4's listed order, and `ERR_ASSIGNMENT_EXISTS` precedes `ERR_NO_ELIGIBLE_CODER`, both consistent with the PRD's existing enumeration — so the added sentence mis-describes no enumerated path).

## Step 9: Complete PRD — 2026-08-11T09:40:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1166_inpatient_coding_drg_assignment/workspace/PRD_COMPLETED.md` is written.

## Summary

**Source**: `PRD_FINALIZED.md` (346 lines / 50,881 chars) → `PRD_COMPLETED.md` (348 lines / 55,450 chars; **+2 lines, +4,569 chars**).

**Counts**: 17 ambiguity-pins, 1 mismatch-revision (18 edits total; all inline in existing paragraphs except one two-line paragraph addition in §2.2).

**Changes** (PRD section — insert|revise — ambiguity|mismatch — what changed — impl file:line):

- §2.2 — insert — ambiguity — Unmatched routes/unsupported methods are answered in the standard error envelope with `ERR_INVALID_REQUEST` at the underlying HTTP status (404/405) — app.py:21-26
- §2.3 — revise — ambiguity — Invalid/out-of-range `limit`/`offset` are rejected with `ERR_INVALID_REQUEST` (400), not clamped — response.py:40-62
- §2.3 — insert — ambiguity — Creation-timestamp sort ties break by insertion order — db.py:74-76 (`_seq`)
- §2.3 — insert — ambiguity — `has_more` true exactly when `offset` + returned page size < `total_count` — response.py:27
- §2.4 — revise — ambiguity — `version` starts at 1 on creation — db.py:61
- §2.5 — revise — ambiguity — Clock set to exactly the supplied instant (no monotonicity enforced); response body `{"current_utc": ...}` — clock.py:12-18
- §2.5 — revise — ambiguity — `created_at`/`updated_at` on every resource also derive from the logical clock — db.py:55-71
- §3.1 — revise — ambiguity — Duplicate `mrn` or negative `total_charges_cents` rejected as `ERR_INVALID_REQUEST` (400) — accounts.py:33-36
- §3.1 — revise — ambiguity — `dnfb_only` listing evaluates the sweep-order key against the current logical clock — accounts.py:66-70
- §3.1 — revise — ambiguity — Discharging a non-`ADMITTED` account fails `ERR_INVALID_STATE` (409) — accounts.py:80-82
- §3.1 — revise — ambiguity — Second chart on an account rejected `ERR_INVALID_REQUEST` (400); chart opened on an already-`DISCHARGED` account is born `READY_FOR_CODING` — charts.py:32-33, 43-44
- §3.2 — revise — ambiguity — `coder_id` is mandatory on the assign action; omission is `ERR_INVALID_REQUEST` — assignments.py:123-134
- §3.3 — revise — ambiguity — Line capture is gated exactly like edits: chart must be `IN_CODING` (else `ERR_INVALID_STATE`) and caller must hold the chart's `IN_PROGRESS` **or `RETURNED`** assignment (else `ERR_FORBIDDEN`), so capture is allowed mid-rework before re-start — lines.py:31-47
- §3.3 — revise — ambiguity — Editing a non-`ACTIVE` (e.g. `VOID`) line fails `ERR_INVALID_STATE`; `status` may only be patched to `VOID` (other values `ERR_INVALID_REQUEST`) — lines.py:140-151
- §3.3 — revise — ambiguity — A start whose `X-User-ID` resolves to no persisted coder is treated as not `ACTIVE` → `ERR_CODER_INACTIVE` — assignments.py:153-155
- §3.5 — revise — ambiguity — Duplicate `employee_no` at coder onboarding rejected `ERR_INVALID_REQUEST` (400) — coders.py:30-31
- §3.6 — revise — ambiguity — Second bill on an account rejected `ERR_INVALID_REQUEST` (400); a bill born `DRAFT` carries `expected_reimbursement_cents` 0 until the acceptance cascade/regroup refreshes it — bills.py:33-45
- §3.7 — revise — ambiguity — Sweep's priority-score recompute applies only to newly flagged accounts' charts; already-flagged accounts are untouched by the sweep — services/calc.py:182-202
- §3.8 — revise — ambiguity — Inactive or unpersisted auditor (not just low rank) fails audit creation with `ERR_CODER_CREDENTIAL_INSUFFICIENT` — audits.py:41-44
- §3.8 — revise — ambiguity — Recording a finding requires the audit `IN_REVIEW` (else `ERR_INVALID_STATE`); each finding type's required `corrected_*`/`target_diagnosis_id` field, when omitted, is `ERR_INVALID_REQUEST` — audits.py:121-140
- §3.8 — revise — **mismatch** — `target_diagnosis_id` "is null for the additive types" → "required for corrective types; recorded as supplied and normally null on additive types" (impl validates and stores a supplied value even for additive findings) — audits.py:114-119, 148
- §3.8 — revise — ambiguity — Apply-cascade mechanics pinned: principal resequence rewrites the target's `icd_code` (and `cc_level` when supplied), designates it principal, clears `is_principal` on all other `ACTIVE` lines; `CC_MCC_ADDED` appends an `ACTIVE` line with `poa` `Y` and `sequence` = max+1 (or 1); `PROCEDURE_ADDED` appends a procedure line with `pcs_code` from `corrected_icd_code`, `is_or` true, `performed_at` from the clock; resolution requires the finding still `OPEN` — findings.py:53-104
- §3.8 — revise — ambiguity — Accuracy zero-denominator guards: empty line sample → `accuracy_code_based` 1.0000; zero expected-reimbursement sum → `accuracy_financial` 1.0000 — services/calc.py:246-256
- §3.9 — revise — ambiguity — Cancelling a rebill also records the officer as `decided_by`; the SoD check applies to approval only — reviews.py:186-202

No mismatches were found in any formula, state machine, error status code, or endpoint table — all calculation constants (weight tables, base rate 650000, 30% cost ratio, 500000 fixed-loss, 80% outlier share, 120-day timely filing, 30-day productivity basis, 0.9500 threshold) and the §2.8 validation ladder match the implementation exactly.

