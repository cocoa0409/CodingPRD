# Worklog — task_0966_produce_rx_food_as_medicine

## Step 1: Create task directory — 2026-08-10T00:00:00.000Z

Pre-assigned output folder `tasks/task_0966_produce_rx_food_as_medicine/` with `workspace/` subdirectory already existed; Step 1 auto-index scan skipped per headless-run instructions. Difficulty parameter for the run: "generate task hard than expert level!" (passed through to Step 2 scaffold generation only).

## Step 2: Generate scaffold — 2026-08-10T02:49:00.000Z

Scaffold generated for task 0966 (Produce-Rx & Food-as-Medicine), saved to `/home/ubuntu/github/CodingPRD/tasks/task_0966_produce_rx_food_as_medicine/`. No sibling tasks were read; the design is derived purely from the scenario and the skill spec.

**Files**
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top key `scaffold_corner_design`

**Counts**
- Entities: 16 (Program, Funder, FundingPool, Clinic, Retailer, Patient, Referral, Enrollment, BenefitCycle, Voucher, Redemption, EducationSession, EducationCompletion, BiometricReading, FunderReport, Renewal) — flat topology, all FK-linked
- State machines: 14 (cyclic: Referral appeal loop, FunderReport return/resubmit, Renewal deny/resubmit, Patient consent; plus Program FROZEN posture gate and Voucher EXHAUSTED↔ISSUED compensation)
- Calculations: 10 (incl. dual variants: pool utilization ACCRUAL vs CASH, A1c inclusive vs verified; combinatorial modes (a) tiered benefit formula and (b) per-line Double-Up rounding; waterfall issuance with deterministic created_at-ordered selector; ops-run expiry/lapse)
- Validations: 11 priority-ordered rows (auth → authz → existence → payload → OCC → state → safety → temporal → constraint → referential → fiscal)
- Endpoints: 80 (incl. `/_clock/set_current_utc` with pinned default 2026-05-01T00:00:00Z)
- Errors: 39
- Roles: 6 (ProgramAdmin/Educator opaque; FunderAnalyst→Funder, ClinicStaff→Clinic, Participant→Patient, RetailerStaff→Retailer entity-backed; segregation-of-duties on pool funding and report acceptance)
- Concurrency: 2 OCC rules (renewal-create on Enrollment.version, report-create on Program.version), both wired into §1.5 inputs/side-effects

**§1.8**: 18 instances (9 rules × 2), all differentiation clauses honored — dual-variant on fiscal vs clinical domains, combinatorial modes (a) and (b), cycles on different entities, depth-3 funder-suspend cascade (Funder→Pool→Program→Enrollment) vs depth-2 cycle-close cascade, priority pairs state-vs-safety and safety-vs-constraint, boundary checks on cents (daily cap, exact-at-cap allowed) vs counts (tier threshold), cross-entity gates on distinct pairs, venue 30-min buffer vs half-open cycle adjacency, and two conservation invariants (funding pool; Double-Up pool) with pre-computed literal assertions.

**§1.9**: 44 active instances across all 9 guide sections + 5 `excluded_because` stubs citing §1.8 instances.

**Lint**: `scaffold_lint.py` verdict — `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (777 calls scanned; 4 initial FK-reachability violations fixed by adding `enrollment_id?`/`voucher_id?` filters and a single-GET for EducationCompletion). Role usage, name uniqueness across both design files, and all formula-derived assert literals (e.g., face 27225, match 154 vs 153 rounding divergence, 487500/9500/3000 conservation) verified by hand-replay.

## Step 3: Copy shared files — 2026-08-10T02:50:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_0966_produce_rx_food_as_medicine/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-10T03:00:00.000Z

All audits pass now. The PRD is complete and verified. Final summary:

**Output:** `workspace/PRD.md` — 327 lines.

**Section list:**
- §1. Introduction (2 paragraphs — business context + constituency/segregation-of-duties framing)
- §2. Global Specifications & System-Wide Principles: 2.1 User and Role-Based Access Control (all 6 roles with identity-binding prose); 2.2 API Response Structure (emitted verbatim from `section-2.2-response-structure.md`); 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending, meta fields); 2.4 Resource Identity and Common Fields (including the `common_fields: false` caveat for EducationCompletion and BiometricReading); 2.5 The Logical Clock; 2.6 Money, Cents, and Rounding (single-final-rounding vs per-line-rounding distinction, A1c one-decimal comparison); 2.7 Optimistic Concurrency Control (both OCC rules with `expected_enrollment_version`/`expected_program_version`, `ERR_STALE_VERSION`/412); 2.8 Pool Ledgers and Reserve Accounting; 2.9 Cascading Status Consistency (funder→pool→program→enrollment chain, asymmetric unfreeze); 2.10 Request Validation Order (all 11 priorities in explicit order with their error IDs)
- §3. Business Logic & Workflows (9 subsections): 3.1 Program/Funder/Pool/Clinic/Retailer setup, 3.2 Patients/Consent/Referrals, 3.3 Approval→Enrollment, 3.4 Benefit Cycles & Issuance Waterfall, 3.5 Redemption & Double-Up Match (3 pinned steps, tender split, 4-ledger ripple, void compensation), 3.6 Education & Engagement Tiers, 3.7 Biometrics & A1c (inclusive vs verified variants), 3.8 Lapse/Renewal/Termination, 3.9 Funder Reporting/Ops Runs/Close-Out
- §4. Endpoint Definitions — 80 rows, 4 columns (Method, Path, Description, Authorized Role(s))
- §5. Error Code Catalogue — 39 rows, 2 columns, no trigger conditions

**Hard-contract audit results (all programmatically verified against the scaffold):**
- **Contract 1 (Field-Name Coverage): PASS** — 86 entity fields, 56 endpoint input identifiers, 12 query params, 16 path params: all present in backticks (path params verified inside the backticked §4 path tokens). All 39 error IDs, all state values, all enum values, all 6 role names present.
- **Contract 2 (Rule Coverage): PASS** — 11 validation priorities expressed in explicit order; 2/2 OCC rules with endpoint + occ field + error ID + 412; all 14 state machines' transitions with preconditions and side effects (including asymmetric unfreeze, cyclic appeal/resubmit loops, supersede cascades, version increments); all 10 calculations in precise prose (no pseudocode, no fuzzy words — checked); cross-entity cascades and applies_to scopes enumerated; sibling branches symmetric (ACCRUAL/CASH, inclusive/verified, FUNDED/SUSPENDED pool close, ACTIVE/FROZEN program close).
- **Contract 3 (§3 Path Purity): PASS** — 335 backtick tokens scanned in §3: 0 path tokens, 0 bare HTTP methods, 0 method+path combos.

**Zero-Silence self-audit notes (issues found and fixed during generation):**
1. My first audit script run produced false negatives because the inline-backtick regex mis-paired across §2.2's fenced JSON blocks and the `## 3.` split collided with `### 3.x` subsection headings — the PRD itself was correct; I fixed the audit methodology (strip fenced blocks first, line-based §3 extraction) rather than the document.
2. During drafting I expanded two rules beyond their terse scaffold phrasing to keep them unambiguous for a PRD-only reader: (a) the funder-report `funding_pool_id` "must belong to program" constraint is explicitly assigned to `ERR_VALIDATION` (the scaffold names no error ID for it), and (b) education-session `ends_at`-after-`starts_at` misordering is explicitly assigned to `ERR_INVALID_DATE_RANGE`, consistent with that error's "start >= end" catalog condition. No rules were invented; these pin down which existing error fires.

## Step 5: Generate unit tests — 2026-08-10T03:35:00.000Z

Generation complete. All artifacts are under `/home/ubuntu/github/CodingPRD/tasks/task_0966_produce_rx_food_as_medicine/`.

**Stage 1 — `test_helpers/` (9 files):** `types.py` (16 entity TypedDicts with correct `common_fields` branching — EducationCompletion/BiometricReading omit `updated_at`/`version`; 20 status/role enums), `api_client.py` (72 endpoint methods covering every PRD §4 route incl. `/_clock/set_current_utc`), `api_errors.py` (39 error IDs with HTTP map registered via `set_error_http_status_map`), `assertions.py` (per-entity asserts + pool/Double-Up ledger conservation invariants), `factories.py`, `constants.py`, `test_users.py` (shared constants for opaque roles + `make_*_headers` builders for the four entity-backed roles), `fixtures.py` (composite chains: `setup_active_program`, `setup_enrollment`, `add_enrollment`, `setup_issued_voucher`, `setup_settled_redemption`, `record_passed_completions`/`setup_enrollment_with_tier`, `record_a1c`, `create_report`/`setup_submitted_report`, `setup_lapsed_enrollment`, `create_renewal`), `__init__.py` barrel.

**Stage 2 — `test_suite/` (11 files):** `conftest.py` + 10 test files (`test_01_program_pool_funder_setup` … `test_10_cascades_and_ops`).

**Test counts: 77 total — Queue A (Difficulty): 34 tests across 17/18 instances (≥2 each). Queue B (Corner): 43 tests across 43/44 non-stub instances (1 each).** All 5 `excluded_because:` stubs verified to resolve to real §1.8 instances and were not translated.

**Instances skipped (PRD-first filter, gaps left as gaps):**
1. `Difficulty/cross_entity_state_dependency/issuance_blocked_when_program_frozen` — asserts `ERR_PROGRAM_NOT_ACTIVE` for issue-on-FROZEN-program, but PRD §3.4 gates issuance only on cycle OPEN (`ERR_CYCLE_NOT_OPEN`) and a FUNDED pool (`ERR_POOL_NOT_FUNDED`); the frozen program's pool is SUSPENDED, so a PRD-faithful implementer would return `ERR_POOL_NOT_FUNDED`. Asserted outcome not uniquely derived.
2. `Corner/state_machines/c_void_voided_voucher_rejected` — asserts `ERR_ALREADY_TERMINAL`, but PRD §3.4 explicitly states "Any voucher operation attempted on a voucher no longer in ISSUED status is rejected with `ERR_VOUCHER_NOT_REDEEMABLE`" — the instance's expected error contradicts the PRD's unique derivation.

**Deliberate weakening avoided / sub-assertion dropped:** in `education_session_venue_buffer_overlap`, the "exactly 30-minute gap is allowed" sub-assertion was not emitted (PRD states the 30-minute buffer rule but, unlike cycles, never states adjacency is allowed for sessions — not uniquely derivable); the 15-minute-conflict and different-venue assertions (both verbatim-covered) provide the 2 required tests.

**Stage 2 self-audit results (all scripted, all pass):**
- 77/77 tests have exactly one `Design:` tag as the final docstring line; every tag resolves to a real instance in the cited yaml (0 untagged, 0 dual-tagged, 0 dangling).
- Every test carries ≥1 verbatim ≥8-word PRD quote that survives literal whitespace-normalized grep of `PRD.md` (0 failures after fixing 25 initially elided/fragmented citations to full-sentence quotes).
- Asserted error IDs are all named in PRD prose; priority-pair tests cite §2.10's explicit ordering sentences.
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere; no "scaffold" references in generated code.
- `py_compile` clean on all 20 files; `pytest --collect-only` collects 77 tests with zero import errors.

## Step 6: Generate implementation — 2026-08-10T03:35:00.000Z

The only match is the pgrep wrapper shell itself — the Flask servers are stopped. The implementation is complete and verified.

**File list** (all under `workspace/implementation/`):
- `app.py` — single-file Flask implementation (~1,300 lines): in-memory dict stores for all 16 entity types, logical clock (default `2026-05-01T00:00:00Z`), envelope/response helpers, auth middleware, all routes and business logic
- `start.sh` — executable foreground launcher: guards the pip install behind `python3 -c "import flask"`, then `exec python3 app.py`; binds `0.0.0.0`, reads `$PORT` (default 10000)
- `requirements.txt` — `flask>=2.2`

**Endpoint count: 70** — the full §1.5/§4 table: clock set, programs (create/get/list/activate/close/run-ops/summary), funders (4), funding pools (5), clinics (4), retailers (4), patients (5), referrals (8), enrollments (5), benefit cycles (6), vouchers (3), redemptions (4), education sessions (5) + completions (3), biometric readings (3), funder reports (6), renewals (6).

**Key spec points implemented:**
- Envelope exactly per scaffold: `meta.api_request_id`/`api_request_timestamp` (3 fractional digits), `response_type`, `data`; error body `error_id`/`message`; list meta `limit`/`offset`/`total_count`/`has_more` (defaults 10/0, clamp [1,100]), sorted `created_at` ASC
- Validation priority per §2.10: auth(401) → forbidden(403) → not-found(404) → validation(400) → OCC(412) → state(409) → consent/A1C(422) → temporal → uniqueness/capacity(409) → cross-entity(409/422) → fiscal(422/409)
- OCC on exactly the two aggregate roots (`expected_enrollment_version`, `expected_program_version`, 412 `ERR_STALE_VERSION`)
- Calculations with `Decimal` ROUND_HALF_UP: benefit face (single final rounding, tier 1.00/1.10/1.25, URGENT 1.10), Double-Up match (per-line rounding then sum, daily-cap + pool-cap clamping), issuance waterfall with skip-and-continue, cycle-close settlement, pool utilization (ACCRUAL/CASH), A1c inclusive vs LAB_VERIFIED variants, referral expiry (>14 days strict) and zero-redemption lapse
- Full cascade chains: funder suspend → pools → program FROZEN → enrollments SUSPENDED (asymmetric reinstate), program close → COMPLETED/TERMINATED, redemption void compensation across voucher/pool/program/enrollment ledgers
- Thin append-only records (EducationCompletion, BiometricReading) carry only `id` + `created_at`
- No seeding: all stores start empty; every entity is created via the API

**Boot verification:** launched `bash start.sh` twice on test ports (18765/18766) from fresh processes — server responded within 3s, returned the correct 401 envelope unauthenticated, empty list with pagination meta on fresh boot, and clock round-trip worked. A 60-assertion end-to-end smoke suite covering every workflow (referral pipeline, issuance face = 15400 with URGENT multiplier, Double-Up tender split, void compensation, venue conflict buffer, tier promotion, A1C outcomes, OCC 412s, renewal cycle, run-ops lapse/expiry, report adjudication, funder-suspend cascade, program close) passed with **0 failures**. All test processes were stopped afterward.

## Step 7: Run tests and iterate — 2026-08-10T06:45:00.000Z

All 8 rounds pass cleanly: 77/77, 0 failed in every round.

## Summary

- **Iterations run:** 2 (round 1 = diagnostic read of the prior sweep's results + fix; round 2 = verification sweep, all 8 rounds green).

- **Tests deleted:** None.

- **Fixes applied to `test_helpers/`:** None.

- **Fixes applied to `test_suite/`:** 4 files, all the same defect — module-level setup helpers referenced the pytest fixture name `api` (not in scope at module level), producing `NameError: name 'api' is not defined` in 8 tests. Replaced `api.` with the already-imported module-level `api_client.` from test_helpers:
  - `/home/ubuntu/github/CodingPRD/tasks/task_0966_produce_rx_food_as_medicine/test_suite/test_03_referrals_and_consent.py` — `_frozen_program_with_revoked_consent()` (`api.suspend_funder` → `api_client.suspend_funder`); fixed `test_approve_frozen_program_and_revoked_consent_returns_program_not_active` and `test_approve_rejected_by_priority_leaves_referral_under_review`.
  - `/home/ubuntu/github/CodingPRD/tasks/task_0966_produce_rx_food_as_medicine/test_suite/test_06_education_and_tiers.py` — `_program_with_session_a()` (`api.create_education_session` → `api_client.create_education_session`); fixed `test_venue_conflict_within_buffer_rejected` and `test_venue_conflict_only_within_same_venue`.
  - `/home/ubuntu/github/CodingPRD/tasks/task_0966_produce_rx_food_as_medicine/test_suite/test_08_reports_and_summary.py` — `_returned_report()` (`api.return_report` → `api_client.return_report`); fixed `test_funder_report_return_resubmit_accept_reaches_accepted` and `test_funder_report_return_increments_revision_count`.
  - `/home/ubuntu/github/CodingPRD/tasks/task_0966_produce_rx_food_as_medicine/test_suite/test_10_cascades_and_ops.py` — `_suspend_single_funder()` (`api.suspend_funder` → `api_client.suspend_funder`); fixed `test_funder_suspend_suspends_pool_and_freezes_program` and `test_funder_suspend_cascade_suspends_active_enrollment`.

- **Fixes applied to `implementation/`:** None — the implementation was already PRD-faithful; all failures were the shared setup scoping bug in the test layer (matching the triage hint: ≥5 failures with the same setup error pointed at the test artifacts).

## Step 8: Finalize PRD — 2026-08-10T06:55:00.000Z

Done. `PRD_FINALIZED.md` exists at `/home/ubuntu/github/CodingPRD/tasks/task_0966_produce_rx_food_as_medicine/workspace/PRD_FINALIZED.md` and is a byte-identical copy of `PRD.md`.

**Analysis of each `<step_7_diff>` item against the PRD and implementation:**

All four Step 7 fixes were the same pure Python scoping bug (`NameError: name 'api'`) in module-level test setup helpers — `api.` was replaced with the already-imported `api_client.`. No implementation changes, no test deletions, no assertion weakening. Each fix site was traced to its exercised behavior and confirmed the PRD already determines it:

1. **test_03 `_frozen_program_with_revoked_consent`** — funder suspend freezing the program, and approval on a FROZEN program with revoked consent surfacing `ERR_PROGRAM_NOT_ACTIVE` (state gate before consent gate). Fully pinned by PRD §2.9, §3.1, §3.3, and the §2.10 check-priority order.
2. **test_06 `_program_with_session_a`** — venue conflict with a 30-minute buffer, scoped to the same venue within the same program. Fully pinned by PRD §3.6.
3. **test_08 `_returned_report`** — funder report return → resubmit → accept, and return incrementing `revision_count`. Fully pinned by PRD §3.8.
4. **test_10 `_suspend_single_funder`** — funder suspend cascade (pool → program freeze → enrollment suspension). Fully pinned by PRD §2.9 and §3.1.

**Summary on exit:**

- **Line counts:** PRD.md = 326 lines; PRD_FINALIZED.md = 326 lines; 0% delta (byte-identical, verified with `cmp`).
- **Changes:** None.
- **Pre-edit search log:** Zero edits were made, so no pre-edit searches were triggered. The verification searches confirmed every Step 7 fix was a test-layer scoping bug revealing no PRD silence and no PRD/implementation mismatch.

## Step 9: Complete PRD — 2026-08-10T07:15:00.000Z

Done. `PRD_COMPLETED.md` written at `/home/ubuntu/github/CodingPRD/tasks/task_0966_produce_rx_food_as_medicine/workspace/PRD_COMPLETED.md` (copied from `PRD_FINALIZED.md`, then edited inline only — no new sections or paragraphs).

**Stats**: source `PRD_FINALIZED.md` 326 lines / 54,234 chars → `PRD_COMPLETED.md` 326 lines / 59,424 chars (**+5,190 chars, +0 lines**; 32 paragraphs touched). **42 changes: 37 ambiguity-pins, 5 mismatch-revisions.**

Ambiguity-pins (insert):
- §2.1 FunderAnalyst — insert — ambiguity — ownership gates only fund/accept/return; reads unscoped — app.py:599,669,675,690,1804,1810,1840,1854
- §2.1 ClinicStaff — insert — ambiguity — ownership gates mutations only; reads/listings unscoped — app.py:851-854,858-864
- §2.1 RetailerStaff — insert — ambiguity — retailer-record reads unscoped; only redemptions scoped — app.py:795-797
- §2.2 — insert — ambiguity — `api_request_timestamp` is wall clock, not logical — app.py:43-44,88-93
- §2.3 — insert — ambiguity — `limit`/`offset` clamped to bounds, non-integer → ERR_VALIDATION; `created_at` ties broken by creation order — app.py:293-312
- §2.4 — insert — ambiguity — `updated_at`==`created_at` and `version`==1 at creation — app.py:165-174
- §2.5 — insert — ambiguity — `created_at`/`updated_at` stamped from logical clock; naive ISO instants read as UTC — app.py:47-56,168
- §2.9 — insert — ambiguity — only an ACTIVE program freezes; DRAFT unchanged — app.py:384-386
- §2.10 (third) — insert — ambiguity — non-string referenced id → ERR_VALIDATION, not ERR_NOT_FOUND — app.py:186-192
- §2.10 (fourth) — insert — ambiguity — strings must be non-empty; calendar dates well formed; `minutes_attended` positive — app.py:225-286,1618-1620
- §3.1 funder — insert — ambiguity — suspend/reinstate wrong-state → ERR_INVALID_STATE — app.py:607-608,626-627
- §3.1 pool fund — insert — ambiguity — CLOSED → ERR_ALREADY_TERMINAL; other non-PENDING → ERR_INVALID_STATE — app.py:692-695
- §3.1 pool close — insert — ambiguity — CLOSED → ERR_ALREADY_TERMINAL; PENDING → ERR_INVALID_STATE — app.py:713-716
- §3.1 clinic — insert — ambiguity — suspend/reinstate wrong-state → ERR_INVALID_STATE — app.py:758-759,769-770
- §3.1 retailer — insert — ambiguity — suspend/reinstate wrong-state → ERR_INVALID_STATE — app.py:804-805,815-816
- §3.1 program activate — insert — ambiguity — CLOSED → ERR_ALREADY_TERMINAL; other non-DRAFT → ERR_INVALID_STATE — app.py:469-472
- §3.1 program close — insert — ambiguity — DRAFT → ERR_INVALID_STATE; CLOSED → ERR_ALREADY_TERMINAL — app.py:487-490
- §3.2 consent — insert — ambiguity — grant-when-GRANTED / revoke-when-not-GRANTED → ERR_INVALID_STATE — app.py:873-874,886-887
- §3.2 referral — insert — ambiguity — fresh referral carries `decision_reason`/`appeal_reason` null — app.py:935-938
- §3.3 approval — insert — ambiguity — response (200) is the updated referral, enrollment via `enrollment_id` — app.py:1011-1014
- §3.3 enrollment — insert — ambiguity — new enrollment starts ACTIVE — app.py:1008
- §3.3 enrollment actions — insert — ambiguity — wrong from-state: terminal → ERR_ALREADY_TERMINAL, else ERR_INVALID_STATE — app.py:1088-1091,1101-1104,1122-1125
- §3.4 cycle create — insert — ambiguity — not gated on program status — app.py:1136-1165
- §3.4 cycle open — insert — ambiguity — CLOSED → ERR_ALREADY_TERMINAL; already OPEN → ERR_INVALID_STATE — app.py:1188-1191
- §3.4 issuance — insert — ambiguity — FUNDED-pool selection ties by creation order; candidate-order residual ties by creation order; pool `version` refreshed even when nothing issued — app.py:1220,1230-1237,1260
- §3.4 cycle close — insert — ambiguity — voucher expiry order ties by creation order — app.py:1274-1277
- §3.5 match — insert — ambiguity — computed match floored at zero — app.py:1401-1402
- §3.5 voucher draw — insert — ambiguity — oldest-voucher ties by creation order — app.py:1403-1406
- §3.5 settlement — insert — ambiguity — zero-amount legs leave their ledgers untouched — app.py:1430-1449
- §3.6 session — insert — ambiguity — scheduling not gated on program status; Educator's `educator_ref` forced to `X-User-ID` (payload ignored), ProgramAdmin must supply it — app.py:1533-1535,1542-1545
- §3.6 venue — insert — ambiguity — boundary touch is not a conflict; CANCELLED sessions don't occupy venues — app.py:1550-1559
- §3.6 tier — insert — ambiguity — enrollment `updated_at`/`version` refresh only when tier changes — app.py:1650-1652
- §3.8 renewal — insert — ambiguity — window boundary inclusive (exactly `renewal_window_days` allowed); fresh renewal has `denial_reason` null; failed resubmit still writes the new `reason` — app.py:1892-1897,1902-1907,1995-1997
- §3.9 report — insert — ambiguity — creation not gated on program status; fresh report has `return_reason` null — app.py:1735-1737,1794
- §3.9 ops run — insert — ambiguity — not gated on program status — app.py:509-512
- §3.9 summary — insert — ambiguity — no funder-ownership scoping; ledger rollup over all pools regardless of status; tier counts over ACTIVE/SUSPENDED/LAPSED; `active_enrollment_count` ACTIVE only — app.py:549-576

Mismatch-revisions (revise):
- §2.10 (fourth) — revise — mismatch — dropped the false "monetary amounts strictly positive" claim (impl never rejects non-positive program/pool/funder money as ERR_VALIDATION); instead pinned that basket/line tender validation fires here as ERR_VALIDATION (missing/non-array `lines`) or ERR_INVALID_TENDER (empty basket, non-object line, bad category, non-positive amount), ahead of state gates — app.py:1360-1375 vs 1377-1381
- §2.10 (eleventh) — revise — mismatch — removed "valid redemption tender / ERR_INVALID_TENDER" from fiscal rules (impl raises it at shape priority) — app.py:1360-1375
- §3.5 tender split — revise — mismatch — `voucher_id` is empty whenever the applied amount is zero, not only when no ISSUED voucher exists (match covering the full subtotal also yields no debit) — app.py:1409-1414
- §3.7 latest reading — revise — mismatch — "symmetrically" replaced: latest-endpoint `measured_at` ties also break by `created_at` ascending (not descending), residual ties by creation order — app.py:356-359
- §3.9 report metrics — revise — mismatch — `total_redeemed_cents`/`total_match_cents` sum over redemptions of the program's *enrollments* (including voucher-less redemptions), not "of the program's vouchers" — app.py:1761-1770

Tests were used only as cross-reference; `implementation/app.py` was the sole authority.
