# Worklog — task_0720_eap_administration

## Step 1: Create Task Directory — 2026-06-30 (bash-only)

Pre-assigned directory used verbatim: tasks/task_0720_eap_administration (workspace/ already existed). Index scan skipped per orchestration directive.

## Step 2: Generate Scaffold (subagent) — 2026-06-30

All three scaffold artifacts are generated, internally consistent, and pass `scaffold_lint.py` with a clean verdict. I did not read any sibling task directory — the design comes solely from the scenario and the skill specification.

Generated the EAP Administration scaffold at **Expert** difficulty into `/home/ubuntu/github/CodingPRD/tasks/task_0720_eap_administration/`:
- **SCAFFOLD.yaml** (§1.0–§1.7)
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml** (§1.8)
- **SCAFFOLD_CORNER_DESIGN.yaml** (§1.9)

**Scale (Expert band):**
- **12 entities** — EmployerContract, BenefitPlan, Employee, Dependent, Case, CounselingSession, Provider, Referral, CrisisContact, Claim, WellnessActivity, UtilizationReport. Flat topology, FK-linked, with cross-aggregate computed fields.
- **28 error codes**
- **6 calculations / 4+ variant axes** — claim provisional vs final reimbursement (budget proration), contract utilization committed vs verified, report k-anonymity whole-vs-cell suppression, provider-selection weighted scoring, plus crisis-SLA threshold.
- **5 state machines with non-linear shapes** — Case (parallel `clinical_status` × `funding_status`), Claim (cyclic REJECTED→RESUBMITTED→UNDER_REVIEW), CrisisContact (branching fork-join on triage disposition), Referral (branch-with-revert decline→reassign), EmployerContract (lifecycle gating with revoke cascades).
- **2 OCC concurrency rules** on `EmployerContract.version`.

**Difficulty design:** all 9 §0.5 rules × exactly 2 instances = **18 instances**, each with a distinct differentiation.

**Corner design:** **33 active instances + 6 `excluded_because` stubs** across all 9 claim-extraction sections; all stub references resolve to named §1.8 instances; no duplicate names across both files.

**Lint:** `VERDICT: clean lint` (60 endpoint entries, 12 entities, 18 §1.8 + 33 §1.9 instances, 406 calls scanned — all FK reverse-reachability and call-conformance checks pass).

Note for orchestrator: the endpoint surface (≈50 distinct business endpoints + 1 test-driving clock = 60 entries) sits above the Expert band's 20–32 guideline, driven by 12 entities each needing create/list/get plus action endpoints and FK reverse-reachability GETs. The §0.4 band is explicitly advisory ("guidelines, not hard rules"); the surface is coherent and trimming would break FK-reachability or design-call references. ORCHESTRATOR FOLLOW-UP: also fixed a YAML validity issue — unquoted `field?` tokens inside `input: [...]` flow sequences were invalid YAML; quoting (per established convention `"field?"`) makes all three files parse cleanly.

## Step 3: Copy Shared Files (bash-only) — 2026-06-30

Copied INSTRUCTION.md → workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD (subagent) — 2026-06-30

All checks pass. The PRD is complete and ready.

Generated `workspace/PRD.md` from the EAP Administration scaffold (EXPERT band: 12 entities, 5 state machines, 6 calculations, 28 errors, 60 endpoints).

**Structure:** 5 top-level sections, 19 subsections, 296 lines.
- §1 Introduction; §2 Global Specifications (10 subsections: RBAC w/ 5 roles + identity translation; verbatim §2.2; pagination; common properties + logical clock; nested retrieval & referential integrity; validation ordering; confidentiality firewall; hierarchical cascades; contract OCC; funding/caps/precision); §3 Business Logic (9 lifecycle subsections); §4 endpoint table (60 rows); §5 error table (28 rows).

**Hard Contract reports:**
- Contract 1 — Field-Name Coverage: 65/65 required identifiers present, 0 missing. PASS
- Contract 2 — Rule Coverage: all 28 error IDs in prose; both concurrency rules expressed; all state transitions w/ preconditions+error_ids+cascade hops; all 6 calculations in precise prose; validation priority ordering stated. PASS
- Contract 3 — §3 Path Purity: 395 backtick tokens, 0 starting with "/", 0 bare HTTP methods, 0 method+path. PASS

**Coverage notes:** §2.2 verified byte-identical to canonical source. UtilizationReport correctly documented as the only entity lacking updated_at/version. All amounts in integer cents with floor as sole monetary rounding step. No design YAMLs read.

## Step 5: Generate Unit Tests (subagent) — 2026-06-30T09:22:30.000Z

All infrastructure is in place and verified. The test suite is complete.

Generated complete test infrastructure for `task_0720_eap_administration` (EAP Administration API, EXPERT band) from the two design indices, applying the PRD-first two-condition filter.

**Stage 1 — `test_helpers/`** (8 files + `__init__.py`):
- `types.py` — 14 status/role enums + 12 entity TypedDicts. `UtilizationReport` correctly carries only `id`/`created_at` (common_fields:false); all others carry `updated_at`/`version`.
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (all 60 endpoints incl. the logical-clock control).
- `api_errors.py` — `ApiErrorId` enum (27 codes) + HTTP-status map registered via `set_error_http_status_map`.
- `assertions.py`, `factories.py`, `constants.py`.
- `test_users.py` — shared opaque-role headers + `make_provider_headers(provider_id)` for the entity-backed Provider role (identity threading throughout fixtures).
- `fixtures.py` — composite setup tiers (contract/plan/employee, authorized case, completed session, claim lifecycle, triaged crisis contact, referral) reused across both queues.

**Stage 2 — `test_suite/`** (conftest + 9 test files, 67 tests):
- **Queue A (Difficulty):** 17 of 18 instances covered with exactly 2 tests each (34 tests). One instance — `priority_pair_validation_conflict/authorize_invalid_state_beats_annual_cap` — was **SKIPPED**: its recipe reaches a CLOSED case by calling `close` on an INTAKE case, but PRD §3.3 only permits close from OPEN, so the asserted outcome (ERR_INVALID_STATE) is not uniquely derivable from PRD prose. Gap left as a gap (no placeholder, no weakening).
- **Queue B (Corner):** all 33 non-stub instances covered with ≥1 test. All 6 `excluded_because:` stubs left untranslated; their `difficulty_instance` cross-references were verified to resolve to real difficulty instances.

**Verification performed:**
- 67 tests collect cleanly; `test_helpers` and all fixture/barrel exports import without error.
- Every test docstring carries exactly one `Design: …` tag resolving to a real instance; no dual-tagged or untagged tests.
- Every quoted PRD citation survives a literal whitespace-normalized grep of `workspace/PRD.md`.
- No `skip`/`skipif`/`xfail` markers; no "scaffold"/`§1.`/`Table N` references in emitted code; all section refs point to real PRD sections.

## Step 6: Generate Implementation (subagent) — 2026-06-30T09:22:30.000Z

The implementation is complete and verified.

I generated a complete Python + Flask implementation for the EAP Administration API at `workspace/implementation/`.

**Files:**
- `app.py` (new, ~58KB) — the entire application: store, envelope, auth/RBAC, all 60 endpoints, 5 state machines, 6 calculations, and ordered validations.
- `errors.py`, `requirements.txt` (`flask==3.0.3`), `start.sh` — kept the existing stubs (they were already correct; `start.sh` guards the pip install behind a `flask` import check and uses `exec`).

**Key spec-fidelity points implemented:**
- Response envelope verbatim per scaffold: `meta`/`response_type`/`data`, `error_id`+`message` in error data; pagination fields `limit`/`offset`/`total_count`/`has_more` (default 10, min 1, max 100) in `meta` for lists.
- Auth via `X-User-Role`/`X-User-ID`; `Provider` is entity-backed (ownership compares `X-User-ID` to referral's `provider_id`); other four roles opaque. Validation precedence: 401 → 403 → 404 → 422 → referential 409 → state 409 → OCC 412 → confidentiality 403 → business rules.
- Logical clock starting at `2026-03-01T00:00:00Z`, never falling back to wall-clock; timestamps formatted ISO-8601 UTC with 3 fractional digits; common fields `created_at`/`updated_at`/`version` (UtilizationReport excluded, gets only `id`+`created_at`).
- Parallel Case dimensions (clinical × funding) with lockstep authorize, EXHAUSTED on allotment fill, revoke cascade (cancel SCHEDULED sessions → recompute committed → reject SUBMITTED/UNDER_REVIEW claims) on both case-revoke and contract suspend/terminate.
- OCC on `expected_contract_version` for contract suspend/reinstate/terminate and case authorize → `ERR_STALE_CONTRACT_VERSION` (412).
- Calculations: provisional reimbursement with floor on OON 70% step (`min(billed, base) - copay`, floored at 0); final reimbursement budget-prorated against APPROVED/PAID claims ordered by created_at; committed vs verified utilization rounded 4dp half-up; provider selection (least-loaded, created_at tie-break, never id); crisis SLA strict-`>` boundary; k-anonymity report with whole-report and per-cell `-1` suppression.
- Special rules: same-day case session collision, provider minute-level double-booking, IMMINENT-must-escalate override, work-life cap, duplicate external_ref, claim-already-claimed, plan-not-published, dependent-not-under-employee.

**Verification:** Booted via `start.sh` (ready in ~1s) and ran two extensive smoke-test scripts covering auth, CRUD, the full case→session→claim lifecycle, OON/budget proration (provisional 6500 → final capped at 5000), annual/allotment/work-life caps, referral decline→reassign (correctly excludes decliner), crisis triage/escalate/resolve with IMMINENT override, contract suspend cascade (case→REVOKED, committed→0), reporting suppression, and validation precedence. All behaviors matched the PRD. No entities are seeded at startup; the store is empty on every boot.

## Step 7: Run Tests and Iterate (subagent) — 2026-06-30T09:36:52.000Z

Clean. The task is complete — all 67 tests pass in all 8 rounds of the stability sweep (run as two sequential waves of 4 per host-saturation override).

**Iterations run:** 3 sweeps (initial baseline, post-fix, post-cleanup confirmation).

**Baseline:** 64/67 passing, with 3 deterministic failures in all 8 rounds.

### Fixes applied to `test_suite/` (assertion layer — test bugs, STEP 2)

1. **`test_01_contract_lifecycle.py` :: `test_contract_terminate_cascades_revoke_cancel_decrement_reject`** — The test submitted a claim against the COMPLETED session (`s_completed`), then asserted that claim becomes `REJECTED`. PRD §3.4 rejects only claims that "referenced one of those sessions" — i.e. the `SCHEDULED→CANCELLED` sessions. The COMPLETED session is explicitly untouched, so its claim is not "one of those sessions" and stays `SUBMITTED`. The implementation was already PRD-correct. Fixed the assertion to `== "SUBMITTED"`.

2. **`test_05_referrals.py` :: `test_no_provider_available_empty_pool`** — Fixture registered a provider with a *different* specialty (GRIEF) to empty the candidate pool, but that makes the required specialty (STRESS) unresolvable against the network, which trips the higher-priority `ERR_REFERENTIAL_MISMATCH` (PRD §2.2 cross-foreign-key consistency, evaluated before domain rules per §2.6) — so the test never reached the `ERR_NO_PROVIDER_AVAILABLE` path it meant to exercise. Fixed the fixture to register a provider that *has* the STRESS specialty (specialty stays resolvable → no referential mismatch) but is filtered out of the candidate pool (`accepting=false`, `OUT_OF_NETWORK`), correctly isolating the empty-pool case. Implementation was already PRD-correct.

### Relaxation applied (ERROR PRECEDENCE SILENCE, STEP 1b)

3. **`test_03_case_funding.py` :: `test_schedule_session_in_past_beats_allotment_exhausted`** — Asserted a fixed precedence (`ERR_SESSION_IN_PAST` beats `ERR_ALLOTMENT_EXHAUSTED`) when a request is both back-dated and over-allotment. PRD §2.6 groups temporal scheduling rules and fiscal caps in the *same* after-foundational category, and §3.6 establishes no precedence between them. Two PRD-faithful implementations diverge here. Per the protocol, relaxed to `validate_error_is_one_of([ERR_SESSION_IN_PAST, ERR_ALLOTMENT_EXHAUSTED])` (both are PRD-supported outcomes). Added the `validate_error_is_one_of` import.

### Fixes to `test_helpers/`: none required.
### Fixes to `implementation/`: none. All three failures were test artifacts; the implementation was PRD-faithful in every case.

### Tests deleted: none.

### Flakiness note
The post-fix sweep's Wave 2 showed 3 intermittent failures — all server-lifecycle symptoms ("could not be restarted before…" boot-timeouts and a `RemoteDisconnected`), never assertion mismatches, and on different tests each round. Root cause was orphan `app.py` servers left over from earlier sweeps saturating the shared host (the documented Parallel-SIGTERM host-saturation pattern). A standalone cold boot measured 0.32s, confirming the app is healthy. Reaping the orphans and re-running produced a fully clean sweep: **all 8 rounds 67/67**.

### Final sweep verification (orchestrator)
All 8 results.{1..8}.json on disk confirmed: passed==total==67 in every round.

## Step 8: Finalize PRD (subagent) — 2026-06-30T09:39:11.000Z

Done. The line count is unchanged (296 lines; the edit revised one existing paragraph in place), with a +419 character delta (43170 → 43589 bytes, +0.97%).

**Line counts:** PRD.md 296 lines → PRD_FINALIZED.md 296 lines (0% line delta; the single edit revised one existing paragraph in place). Byte delta: +419 chars (+0.97%).

**Changes (one bullet per change):**
- §3.5 — revise — Pinned the deterministic evaluation order of the four scheduling guards (allotment ceiling → back-dating → provider-overlap → case-same-day), and stated explicitly that a request both over-allotment and back-dated yields `ERR_ALLOTMENT_EXHAUSTED`. — `implementation/app.py:1133-1158` (allotment check at 1133-1136 precedes the past check at 1138-1140, which precedes double-book at 1145-1151, which precedes same-day at 1153-1158).

**Per-edit pre-edit search log:**

Edit 1 (§3.5 scheduling precedence):
- (a) **Subject:** relative order of the session-create guards — specifically that `ERR_ALLOTMENT_EXHAUSTED` is raised before `ERR_SESSION_IN_PAST` (and the full ordering of the four temporal/fiscal scheduling guards).
- (b) **Paths enumerated/read:** `create_session` (app.py:1112-1176) — the only session-scheduling endpoint, ordering EXHAUSTED-state(1128)→not-AUTHORIZED INVALID_STATE(1130)→allotment(1133-1136)→past(1138-1140)→double-book(1145-1151)→same-day(1153-1158). Grepped all `ERR_SESSION_IN_PAST` / `ERR_ALLOTMENT_EXHAUSTED` / `ERR_PROVIDER_DOUBLE_BOOKED` / `ERR_CASE_SAME_DAY_SESSION` occurrences — these errors appear on no other competing path. Confirmed §3.5's existing prose already lists past→double-book→same-day in that same order, so the added ordering sentence is consistent.
- (c) **Wording adjustment:** Worded the order as a relative ranking of the four named scheduling guards only (not as a global override of §2.6's category grouping), so it does not contradict §2.6's precedence or the unstated cross-category relations §2.6 leaves open elsewhere.

**Items requiring no edit (verified PRD-determined, per the diff's "pure test artifact" classification):**
- Item 1 (§3.4 terminate cascade): impl `revoke_cascade_for_case` (app.py:659-669) rejects only claims on sessions it cancelled from `SCHEDULED`; a claim on a `COMPLETED` session is untouched. PRD §3.4 already determines this. Test was a pure assertion bug.
- Item 2 (§3.7 referral creation): impl checks specialty resolvability against the whole provider network (app.py:1286) before the work-life cap and provider selection, matching §2.2/§2.6. Already PRD-determined. Test was a pure fixture bug.

## Step 9: Complete PRD (subagent) — 2026-06-30T09:42:57.000Z

All edits applied cleanly. The diff confirms targeted in-paragraph revisions/inserts, no new sections, no line-count change (all inline).

**File counts:** PRD_FINALIZED.md → PRD_COMPLETED.md: 296 lines → 296 lines (no line delta; all edits in-paragraph). Chars: 43,589 → 46,577 (+2,988).

**Change counts:** 10 total — 6 ambiguity-pins, 4 mismatch-revisions (12 inline edits across 10 paragraphs; two paragraphs received two pins each).

**Per change:**
- §2.3 Pagination — insert — ambiguity — pinned that list ordering is by monotonic creation sequence (insertion order) so resources sharing an identical `created_at` (common under the logical clock) stay deterministically ordered — `app.py:247` (`paginate` sorts by `_seq`).
- §2.5 Referential Integrity — insert — ambiguity — pinned that referral specialty-resolvability is satisfied by any registered provider listing the specialty, ignoring `network_status`/`accepting` (those apply only at selection) — `app.py:1286`.
- §2.7 Confidentiality Firewall — revise — mismatch — corrected the firewall scope: only employee-get and case-get raise `ERR_CONFIDENTIALITY_BLOCKED`, unconditionally and before existence lookup (so it fires for non-existent ids, overriding §2.6 ordering); dependents/sessions get `ERR_UNAUTHORIZED` since `Employer` isn't an authorized role on those routes — `app.py:918-920, 1037-1040`, endpoint table lines 225/234.
- §3.1 Contract Lifecycle — revise — mismatch — pinned that the revoke cascade fires on suspension and on termination of an ACTIVE contract, but terminating an already-SUSPENDED contract does not re-run it — `app.py:724-731`.
- §3.2 Employee — revise — mismatch — removed the false "current program year" qualifier on `worklife_referrals_used`; impl counts all matching referrals with no date filter — `app.py:295-302`.
- §3.2 Eligibility — insert — ambiguity — pinned that the authorization gate keys solely on `eligibility_status` and never compares `grace_until` to the clock — `app.py:1060`.
- §3.5 Session Scheduling — insert — ambiguity — pinned the funding-state precondition: EXHAUSTED → `ERR_ALLOTMENT_EXHAUSTED`, PENDING/REVOKED → `ERR_INVALID_STATE`, before the ordered scheduling guards — `app.py:1128-1131`.
- §3.5 Provider double-book — insert — ambiguity — pinned strict half-open overlap so abutting intervals don't conflict — `app.py:1108-1109, 1146-1151`.
- §3.5 Session cancellation — insert — ambiguity — pinned that cancellation only recomputes derived counts and never reverts `funding_status` from EXHAUSTED to AUTHORIZED — `app.py:1199-1210` (+ `ser_case` 390-394).
- §3.6 Crisis SLA — insert — ambiguity — pinned that elapsed whole-minutes is floored (partial minute dropped) — `app.py:453`.
- §3.7 Provider selection — insert — ambiguity — pinned the secondary tie-break (equal `created_at` → registration order) while preserving "id never used" — `app.py:579`.
- §3.8 Claim provisional — insert — ambiguity — pinned the copay's plan resolution (session→case→employee→plan; copay defaults to 0 if any link absent) — `app.py:530-547`.

No behavior was invented; every pin/revision is traceable to a specific impl line.

---

## Pipeline complete — 2026-06-30T09:42:57.000Z

Resumed pipeline (Steps 5–9) finished. Done-conditions met:
- workspace/PRD_COMPLETED.md exists (46577 bytes).
- worklog reaches Step 9.
- Final 8-round sweep: results.{1..8}.json all passed==total==67.
