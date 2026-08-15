## Step 2: Generate Scaffold — 2026-08-14T23:22:00.000Z

All three artifacts are generated, validated, and lint-clean. Summary:

## Files created (all three exist)
- `/home/ubuntu/github/CodingPRD/tasks/task_1883_energy_modeling_green_building/SCAFFOLD.yaml` — §1.0–§1.7 only (no `scaffold_difficulty_design`/`scaffold_corner_design` keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1883_energy_modeling_green_building/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1883_energy_modeling_green_building/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

## Scaffold contents
- **Complexity profile**: compliance_audit + workflow_orchestration; flat topology; cyclic state machines; segregation_of_duties role model; layers = optimistic_concurrency, cascading_side_effects, derived_field_reconciliation, version_pinning_on_approval.
- **Entities (11)**: TeamMember, CertificationProject, CreditLibraryEntry, EnergyModel, CreditAttempt, ReviewComment, CommissioningTask, IncentiveProgram, ProjectIncentive, CostPremiumAnalysis, PerformanceReport.
- **State machines (7)**: cyclic CreditAttempt review loop (UNDER_REVIEW→CLARIFICATION_REQUESTED→RESUBMITTED→UNDER_REVIEW, plus DENIED→APPEALED→UNDER_REVIEW), cyclic CertificationProject recertification loop (CERTIFIED→PERFORMANCE_REPORTING→RECERTIFICATION_REVIEW→CERTIFIED), ReviewComment OPEN/ADDRESSED/REOPENED/ACCEPTED cycle, EnergyModel DRAFT→LOCKED→SUPERSEDED (version pinning), CommissioningTask, ProjectIncentive, PerformanceReport (REJECTED→DRAFT cycle).
- **Calculations (10)**: dual-variant energy improvement (provisional 10.00 vs final 5.00 on identical inputs), optimistic-vs-conservative level projection, per-credit rounding-before-summation, energy bucket thresholds, incentive stacking waterfall with 40% cap, pinned-order cost premium/payback, sqft-based certification fee with ceil+cap, performance gap with inclusive 15.00 tolerance, closed-interval report tiling, half-open commissioning overlap.
- **Endpoints (59)**, **errors (49)**, **validations (12 priority rows)**, **roles (7: ProgramAdmin, ProjectAdministrator, EnergyModeler, DocumentationSpecialist, CommissioningAgent, CertificationReviewer, Any — with entity_backed identity on the four consultant-side roles)**, **2 OCC concurrency rules** on CertificationProject.version, logical-clock endpoint with the mandated 2026-08-01T00:00:00Z default.

## Test design counts
- **Difficulty (§1.8): 18 instances** — exactly 2 per each of the 9 rules, all differentiation clauses honored (different entity domains, formula modes a+c, entities, triggers, category pairs, metrics/endpoints, entity pairs, interval semantics, conserved quantities). All formula-derived asserts were pre-computed in code (fees 850000/950000, incentive total 20000000, payback 50.0/66.7/83.3, gaps 15.00/15.09, etc.).
- **Corner (§1.9): 86 instances = 73 active + 13 excluded_because stubs**, across all nine taxonomy sections (entities 17, state_machines 12, calculations 8, validations 29, endpoints 3, errors 7, rbac 4, complexity_layers 5, consistency_model 1).

## Verification
- `scaffold_lint.py`: **VERDICT: clean lint** — 59 endpoints, 11 entities, 18 §1.8 + 73 §1.9 active instances, 1067 calls scanned, zero violations (endpoint/role/payload/capture/OCC/FK-reverse-reachability).
- Additional self-audit script passed: zero unbound `${var}` placeholders, all instance names unique across both files, all `grounds:` references resolve into §1.1–§1.7, error catalog closed (every catalog error referenced by at least one instance; every error used in state machines/validations exists in the catalog), no forbidden concurrency vocabulary, and one real gap found and fixed during audit (ERR_COMMISSIONING_INCOMPLETE was missing from §1.6).

## Step 3: Copy Shared Files — 2026-08-14T23:23:00.000Z

Copied ./INSTRUCTION.md to tasks/task_1883_energy_modeling_green_building/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-14T23:45:00.000Z

All checks pass — the §2.2 "mismatch" was only the trailing `---` separator line (also present in the example PRD); all 48 canonical lines match byte-for-byte. Contract 2 audit confirmed every transition, calculation, validation priority, side effect, and field default is expressed in prose.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1883_energy_modeling_green_building/workspace/PRD.md` — exists, 350 lines. The withheld difficulty/corner design files were not opened or referenced.

**Section structure:**
- §1 Introduction (3 paragraphs: engagement context, system scope, cross-cutting themes)
- §2 Global Specifications (10 subsections): 2.1 RBAC with per-role identity prose (4 entity-backed roles vs 2 opaque); 2.2 API Response Structure (byte-verbatim canonical block); 2.3 Pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending); 2.4 Common Resource Properties; 2.5 Project Versioning & OCC (both `expected_project_version` guards, `ERR_STALE_PROJECT_VERSION`/412); 2.6 Money/Percentages/Rounding (integer cents, 2dp half-up, 1dp payback, per-attempt-before-summation preview); 2.7 Request Validation Order (11-stage priority ladder); 2.8 Not-Found family (all eleven 404s, left-to-right); 2.9 Derived Totals & Automatic Reconciliation; 2.10 Logical Clock (default 2026-08-01T00:00:00Z)
- §3 Business Logic (8 subsections): roster & project registration; credit catalog/ownership matrix/strategy lock (incl. mark-ready version pinning); energy models & lock cascade (dual improvement variants, 5.00 PERFORMANCE gate, supersede → stale-pin → demote cascade); phase packages (tiered fee formula, SoD, withdrawal refund); review loop (comments, buckets 18/14/10/8/5 → 10/8/6/4/2, per-attempt rounding with 1.4+1.4 example, thresholds 40/50/60/80, bubble-up, appeal reopen); commissioning (independence, half-open overlap, prerequisite gate); decision/incentives/cost premium (stacking waterfall with 40% floor cap on pre-incentive base, pinned 4-step order); performance reporting & recertification (closed-interval tiling, 15.00 inclusive tolerance, 2-report gate, cycle)
- §4 Endpoint table: 59 rows, 4 columns only (Method/Path/Description/Roles) — verified 1:1 against scaffold
- §5 Error catalogue: 49 rows, 2 columns only — verified 1:1 against scaffold

**Hard contract reports:**

```
Field coverage check:
- entities[].fields + endpoint inputs + envelope/pagination: 91 required, 91 present, 0 missing
Status: PASS

Rule coverage check:
- validation priority ladder: 12 priorities expressed as an ordered 11-stage ladder (§2.7) + per-endpoint ordering notes, 0 missing
- concurrency_rules[]: 2 checked, 2 expressed (write op + expected_project_version + ERR_STALE_PROJECT_VERSION/412, stale-view framing only), 0 missing
- state_machines[].transitions: 37 checked, 37 fully expressed (from/to, preconditions + error_id, side effects), 0 missing
- calculations[]: 10 checked, 10 fully expressed in precise prose (formulas, constants, inclusive boundaries, pinned orders), 0 missing
- validations[] conditions: all matchable to their error_ids in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed, 0 missing
- entities[].fields[] structured content (types, defaults, nullables, constraints): reconstructible from prose, 0 missing
- sibling-branch symmetry: award/deny, accept/reopen, respond OPEN/REOPENED, CERTIFY/DENY, RECERTIFY/LAPSE, DESIGN/CONSTRUCTION submit/withdraw, 3 drop from-states, 3 begin-review from-states — all equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 477
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional spot checks passed: all 38 state values and 45 enum/decision values appear as exact backticked strings (including `REJECTED`, added via edit); every `errors[].id` is mentioned in §1–§4 prose; §2.2 block lines are byte-identical to the canonical source.

## Step 6: Generate Implementation — 2026-08-15T00:10:00.000Z

Done. The implementation is complete and verified.

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_1883_energy_modeling_green_building/workspace/implementation/`)

| File | Contents |
|---|---|
| `start.sh` | Executable launcher: `cd` to script dir, guarded dep install (`python3 -c "import flask"` check, `pip install -q` only if missing), `exec python3 app.py` in foreground |
| `requirements.txt` | `flask>=3.0,<4` |
| `app.py` | Flask entry point; binds `0.0.0.0:$PORT` (default 10000); `ApiError`/404/500 handlers emitting the envelope |
| `db.py` | Empty-at-boot in-memory store (11 entity tables), UUID minting, wall-clock `now_iso()` (3-fractional-digit UTC), logical `CLOCK` defaulting to `2026-08-01T00:00:00Z` |
| `errors.py` | `ApiError(error_id, http_status, message)` |
| `response.py` | Envelope helpers — `meta.api_request_id` (`req_` + 20 alnum), `meta.api_request_timestamp`, `response_type` object/array/error, pagination fields in `meta` (`limit`/`offset`/`total_count`/`has_more`) |
| `middleware.py` | Stage-1 header check (`X-User-ID`/`X-User-Role` non-empty → `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`) and stage-3 role gate (`ERR_INSUFFICIENT_PERMISSIONS`) for the six roles |
| `util.py` | Body/field parsers (strict int/bool/enum/datetime), Decimal rounding (half-up), all enum vocabularies from the scaffold, `limit`/`offset` pagination (default 10, clamp 1–100) |
| `services.py` | Lookups with per-type 404 IDs, `stamp`/`touch` (common fields + version), derived-field reconciler, phase bubble-up, fee/level/bucket/waterfall/payback/gap calculations, cx-overlap and report-tiling rules |
| `routes/` | 11 blueprints: `clock`, `team_members`, `credit_library`, `projects` (7 actions + 2 sub-resource lists), `energy_models`, `credit_attempts` (8 actions + comment list), `review_comments`, `commissioning`, `incentives` (programs + applications), `analyses`, `performance_reports` |

## Design decisions worth recording

- **Validation order follows PRD §2.7's fixed ladder**, not the scaffold's state-machine precondition order where they conflict: headers → body conformance → role → ownership → existence (left-to-right) → OCC → state → compliance gates (SoD, cx independence, prereqs-awarded, min improvement) → referential (phase compat, specialty) → structural → fiscal. Consequence: SoD (403) is checked before the empty-package 422 (vacuously passes when empty), and independence (403) before specialty (422) on commissioning create.
- **Project `version` bump policy**: bumped once per operation when the op is in PRD §2.5's explicit list (lock/submit/withdraw/decision/recert×2/attempt create+drop/model create/bubble-up) or when a recomputed derived field actually changes value; bubble-up is a separate +1, so a phase-completing award bumps twice (recompute + bubble-up).
- **`ERR_REVIEW_ALREADY_STARTED`** triggers when any review comment exists on any attempt of the phase past pre-submission states — the literal "comment on a SUBMITTED attempt" is unreachable (commented attempts never return to SUBMITTED), so the PRD's "before the review body has engaged" intent governs.
- **Money/percent math in `Decimal`**; percentages quantized to 2dp half-up then emitted as floats; payback 1dp half-up (`None` if savings = 0 — unspecified edge); incentive cap via exact `floor(0.40·x)`; fee uses integer ceil on sqft/1000.
- **Uniqueness without a catalog error ID** (member email, credit_code, program_name) → `ERR_INVALID_REQUEST` 400.
- **PerformanceReport on a certified project with no LOCKED PROPOSED model** (reachable via PRESCRIPTIVE path) → `ERR_PROPOSED_MODEL_NOT_LOCKED` 409 before tiling checks; report `rejection_reason` cleared on revise per "null otherwise".
- **No seeding**: store starts empty; every boot is a fresh process.

## Verification

Three ad-hoc suites (~110 checks total) all pass against fresh boots: full happy path (register → strategy → models → submit/withdraw → review loop with comments/resubmit/accept → award/deny/appeal → certify → incentives/waterfall/cap → analysis → reports/tiling/tolerance → recertify and lapse), the complete 404 family, all error-catalog paths exercised (412 OCC, 422 gates, 402 funds, 409 states, 403 ownership/SoD), the stale-pin cascade with demotion, fee debit/refund exact compensation, per-attempt half-up rounding (1.4+1.4 → 1+1, 29.5 → 30, bucket awards), and pagination meta. Cold boot via `bash start.sh` answers HTTP in <2.5 s, well under the 60 s contract.

## Step 5: Generate Unit Tests — 2026-08-15T00:15:00.000Z

Complete. All audits pass: 109 tests collected, every one traceable to a design-index instance with a verbatim PRD citation.

## Summary

**Coverage (all targets met, zero skips):**
- Queue A (Difficulty): 18/18 instances, 2 tests each = **36 tests**
- Queue B (Corner): 73/73 non-stub instances, 1 test each = **73 tests**; all 13 `excluded_because:` stubs correctly not translated (cross-references verified to resolve)
- Total: **109 tests**, every docstring ending with exactly one verbatim `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line, and 114 quoted PRD citations all verified as whitespace-normalized substrings of `workspace/PRD.md`

**Files written:**
- `test_helpers/`: `types.py` (11 entity TypedDicts + status/role enums), `api_client.py` (all 47 endpoints, no API prefix), `api_errors.py` (49-error catalog registered via `set_error_http_status_map`), `assertions.py` (per-entity + analysis invariants), `factories.py`, `constants.py` (fee formula, level thresholds, 5.00 improvement gate, 15.00 tolerance, 40% cap), `test_users.py` (opaque ProgramAdmin/CertificationReviewer/Any constants + per-instance builders for the four entity-backed roles), `fixtures.py` (OCC-aware model/strategy helpers, submitted-package and under-review fixtures, model-pinned-ready fixture, and the full certification spine `setup_certified_project` / `setup_certified_project_with_report`)
- `test_suite/`: `conftest.py` + 11 concern-grouped files (registration/catalog, not-found family, RBAC/ownership, strategy/OCC, energy models, phase packages/fees, review loop, commissioning, certification decision/incentives, cost premium analysis, performance reporting/recertification)

**Three design-index data defects handled (tests kept, PRD-derived values used):**
1. `construction_submit_requires_commissioning_passed` asserts `fee_balance_cents == 4150000`, but its own formula (5000000 − 850000 design − 950000 construction) yields **3200000** — the test asserts 3200000 per PRD §3.4.
2. `minimum_improvement_below_threshold_blocked`'s payload (11405000) computes to 0.50% improvement, not the claimed 4.96% — the asserted rule (below 5.00 → `ERR_MINIMUM_IMPROVEMENT_NOT_MET`) still fires, so the test uses the recipe payload and asserts the error only. (The PRESCRIPTIVE mirror test uses 11404800 = exactly 4.96.)
3. `commissioning_agent_invalid_specialty_rejected`'s recipe candidate (MANAGEMENT, `is_independent=false`) violates both the independence gate (ladder stage 8) and the specialty check (stage 9), which per PRD §2.7 would answer `ERR_CX_AGENT_NOT_INDEPENDENT`, not the asserted 422 — the test isolates the failure with a MANAGEMENT member carrying `is_independent=true` so only the specialty check can fail.

No instance was skipped: every non-stub instance found verbatim PRD coverage with a uniquely derivable outcome.

## Step 7: Run Tests and Iterate — 2026-08-15T00:25:00.000Z

All 8 parallel rounds pass 109/109. The task is complete.

**Summary**

- **Iterations run:** 2 (initial 8-round sweep identified the failure; verification 8-round sweep passed cleanly).
- **Tests deleted:** none.
- **Fixes applied to `test_helpers/`:** none.
- **Fixes applied to `test_suite/`:** `test_03_rbac_and_ownership.py` — added the missing module-level constant `ANY = TEST_USERS["any_headers"]`. The test `TestOwnershipGates::test_cx_start_by_non_assigned_agent_rejected` referenced `ANY` in its post-assertion read (`api.get_commissioning_task(task["id"], ANY)`) but the module only defined `ADMIN` and `REVIEWER`, producing `NameError: name 'ANY' is not defined` in all 8 rounds. The asserted rule itself (PRD §3.6: "A caller whose `X-User-ID` is not the task's `agent_id` fails with `ERR_NOT_ASSIGNED_COMMISSIONING_AGENT` (HTTP 403)") is verbatim-covered and uniquely derivable, so the test stays; the fix only supplies the constant every sibling test module already defines.
- **Fixes applied to `implementation/`:** none — the implementation was already PRD-faithful.

Final state: 109/109 passed in every one of the 8 concurrent rounds (872/872 test executions).

## Step 8: Finalize PRD — 2026-08-15T00:35:00.000Z

Verification complete. The files are identical (349 lines each), and the PRD even pins the validation ladder (§2.7: ownership at stage 4 precedes state validity at stage 7), which matches the implementation's check order in `start_task`/`complete_task`.

## Summary

**PRD.md vs PRD_FINALIZED.md:** 349 lines vs 349 lines — 0.00% delta. `PRD_FINALIZED.md` is an exact copy of `PRD.md` at `/home/ubuntu/github/CodingPRD/tasks/task_1883_energy_modeling_green_building/workspace/PRD_FINALIZED.md`.

**Changes:** none.

**Justification (verification of the zero-edit outcome):**

The single Step 7 item is the addition of `ANY = TEST_USERS["any_headers"]` at `test_suite/test_03_rbac_and_ownership.py:27` — a pure Python NameError fixture bug. I verified it reveals no PRD silence and no PRD/impl mismatch:

- **(a) Subject:** the fixed test `test_cx_start_by_non_assigned_agent_rejected` (test_03, lines 111-132) asserts (i) non-assigned agent start → `ERR_NOT_ASSIGNED_COMMISSIONING_AGENT` (403), (ii) rejected start leaves status `SCHEDULED`, (iii) post-rejection read succeeds with `ANY` headers.
- **(b) Paths enumerated:**
  - All 10 sibling test modules already define the identical `ANY` constant (test_01:30, test_02:15, test_04:24, test_05:34, test_07:33, test_08:29, test_09:22, test_10:24, test_11:22) — confirming the test_03 omission was a fixture accident, not a signal.
  - PRD §3.6 (PRD.md:203) contains the asserted rule verbatim: "A caller whose `X-User-ID` is not the task's `agent_id` fails with `ERR_NOT_ASSIGNED_COMMISSIONING_AGENT` (HTTP 403), and starting or completing from the wrong state fails with `ERR_INVALID_TASK_STATE` (HTTP 409)"; error catalog row at PRD.md:305.
  - PRD.md:19 pins read access: "Read access is universal: every listing and detail endpoint accepts `Any` authenticated role" — exactly what the `ANY`-headers read relies on.
  - Implementation `routes/commissioning.py`: `start_task` (118-134) raises the 403 ownership error before the 409 state check and before any mutation (so status stays `SCHEDULED`); `complete_task` (137-159) mirrors it; `get_one_task` (112-115) requires only `auth_headers()`, matching universal read.
  - PRD §2.7 (PRD.md:101-115) fixes the evaluation ladder with ownership (stage 4) preceding state validity (stage 7), matching the implementation's check ordering.
- **(c) Wording adjustment:** not applicable — no edit was committed, since every behavior touched by the Step 7 fix is already uniquely determined by existing PRD prose and the implementation is PRD-faithful at that site.

No edits were invented to justify the step; a fresh implementer reading `PRD_FINALIZED.md` (identical to `PRD.md`) is already fully constrained at every point the Step 7 fix touched.

## Step 9: Complete PRD — 2026-08-15T00:50:00.000Z

Done. PRD_COMPLETED.md is written at `/home/ubuntu/github/CodingPRD/tasks/task_1883_energy_modeling_green_building/workspace/PRD_COMPLETED.md` (copied from PRD_FINALIZED.md, then patched in place).

**Size delta:** PRD_FINALIZED.md 349 lines / 54,958 chars → PRD_COMPLETED.md 351 lines / 58,255 chars (+2 lines, +3,297 chars, 22 diff hunks — 20 in-place paragraph revisions + 2 error-table row inserts).

**Counts:** 20 ambiguity-pins, 2 mismatch-revisions.

**Changes (one bullet each):**

- §2.1 — insert — ambiguity — unrecognized role labels pass header validation (presence/non-empty only), satisfy `Any`-role reads, fail role-gated writes with 403 — middleware.py:16-37
- §2.3 — insert — ambiguity — `limit`/`offset`: out-of-range clamped to [1,100]/[0,∞), non-integer falls back to defaults 10/0 — util.py:164-180
- §2.3 — insert — ambiguity — list sort ties on identical `created_at` break in insertion order — services.py:45-46, db.py:20,31-33
- §2.3 — insert — ambiguity — `total_count` = filtered count before pagination; `has_more` ⟺ `offset`+`limit` < `total_count` — response.py:24-31
- §2.3 — insert — ambiguity — boolean filter params accept `true`/`1`, `false`/`0` case-insensitively; unparsable values leave the filter unapplied — util.py:183-192
- §2.4 — insert — ambiguity — a derived-field recomputation that changes no stored value is not a mutation (no `version` bump), except §2.5's always-increment operations — services.py:250-262
- §2.8 + §5 — insert — ambiguity — unrouted path/unsupported method → `ERR_NOT_FOUND` 404; unexpected failure → `ERR_INTERNAL` 500; both catalogue rows added — app.py:20-30
- §3.1 — insert — ambiguity — duplicate member `email` (exact match) → `ERR_INVALID_REQUEST` 400 — routes/team_members.py:23-25
- §3.2 — insert — ambiguity — duplicate catalog `credit_code` (exact match) → `ERR_INVALID_REQUEST` 400 — routes/credit_library.py:43-45
- §3.2 — insert — ambiguity — attempt-creation checks run phase-compatibility → owner-specialty → duplicate-scan — routes/credit_attempts.py:60-79
- §3.2 — insert — ambiguity — assign-owner from states other than `SELECTED`/`DOCUMENTATION_IN_PROGRESS` → `ERR_INVALID_CREDIT_ATTEMPT_STATE` 409 — routes/credit_attempts.py:138-143
- §3.4 — insert — ambiguity — submission guard order: segregation of duties → empty-package → proposed-model gate (design) / commissioning gate (construction) → funds — routes/projects.py:165-209
- §3.4 — revise — mismatch — withdrawal blocked by any review comment on any attempt of the phase regardless of the attempt's current post-submission state (PRD said "any `SUBMITTED` attempt") — routes/projects.py:236-247
- §3.5 — insert — ambiguity — begin-review evaluates the attempt-state check before the project-state check — routes/credit_attempts.py:216-228
- §3.5 — insert — ambiguity — review comment is stamped `OPEN` with `response_text` null at creation — routes/review_comments.py:36-45
- §3.5 — insert — ambiguity — omitting `raw_points_earned` with no derivable pin (non-model credit or no pinned model) → `ERR_INVALID_REQUEST` 400; explicit figure always allowed — routes/credit_attempts.py:288-305
- §3.5 — revise — mismatch — denial records no `reason` (PRD said the reviewer may record one; impl validates/stores nothing) — routes/credit_attempts.py:317-332
- §3.5 — insert — ambiguity — appeal on a project past the reviewed state still moves the attempt to `APPEALED` but leaves project state unchanged — routes/credit_attempts.py:346-353
- §3.6 — insert — ambiguity — with no `LOCKED` proposed model, the model-authorship limb of agent independence does not apply — routes/commissioning.py:57-65
- §3.7 — insert — ambiguity — duplicate `program_name` (exact match) → `ERR_INVALID_REQUEST` 400 — routes/incentives.py:52-54
- §3.7 — insert — ambiguity — `simple_payback_years` is null when `annual_energy_savings_cents` is zero — services.py:212-219
- §3.8 — insert — ambiguity — report filing requires the project's `LOCKED` proposed model, else `ERR_PROPOSED_MODEL_NOT_LOCKED` 409 — routes/performance_reports.py:63-69
- §3.8 — insert — ambiguity — revising a rejected report clears `rejection_reason` to null — routes/performance_reports.py:149-152

**Cross-checked, no change needed:** OCC guard placement and 412s, error-ladder stage ordering (incl. independence-before-specialty in §3.6 per stages 8→9), fee formula/cap, per-attempt half-up rounding and bucket table, supersession cascade and demotion, bubble-up conditions, version-increment inventory in §2.5, threshold tables, tiling/anchor arithmetic, incentive stacking waterfall with 40% floor-truncated cap, analysis 1:1 and sub-resource array shape, all endpoint routes/roles/201-vs-200 in §4, and the §5 catalogue (all other impl error_ids already present).
