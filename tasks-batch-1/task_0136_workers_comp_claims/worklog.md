# Worklog — task_0136_workers_comp_claims

## Step 1: Create Task Directory — 2026-06-04T10:04:00.000Z

Created `tasks/task_0136_workers_comp_claims/` and `tasks/task_0136_workers_comp_claims/workspace/` at the pre-allocated path (no index scan / auto-increment). Scenario: Workers' Compensation Claims (FROI/SROI EDI injury report, TTD/PPD wage replacement, MMI/impairment rating, return-to-work light duty, medical-only vs lost-time, experience mod (EMR), reserve setting, IME). Target difficulty: Expert.

## Step 2: Generate Scaffold (Expert) — 2026-06-04T10:22:00.000Z

All checks pass. The scaffold is complete and lint-clean.

Generated all three Expert-difficulty scaffold artifacts for **task_0136_workers_comp_claims** and confirmed they pass `scaffold_lint.py` (`VERDICT: clean lint`).

**Files written** (all three present):
- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

**SCAFFOLD.yaml counts:**
- Entities: **12** (Employer, Policy, Worker, Claim, InjuryReport, WageStatement, BenefitPayment, ImpairmentRating, ReturnToWorkOffer, Reserve, IMEOrder, ExperienceModEntry)
- State machines: **5** (Claim cyclic w/ reopen loop, InjuryReport EDI reject/re-transmit cycle, ImpairmentRating branching, ReturnToWorkOffer fork, IMEOrder) + **2** concurrency rules (OCC on Claim.version)
- Calculations: **6** (AWW, TTD weekly rate, indemnity payment amount, forward indemnity reserve, total-incurred conservation, experience mod/EMR)
- Validations: **14** (ordered, auth → SoD → existence → state → EDI/MTC referential → safety → temporal/statute → overlap → uniqueness → fiscal → field-shape)
- Endpoints: **53**
- Errors: **15**
- Roles: **4** (PlatformAdmin, ClaimsAdjuster, MedicalReviewer opaque; Employer entity_backed) under a segregation-of-duties model

**§1.8 difficulty design:** **18 instances** — all 9 Difficulty Rules × 2 instances each (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant).

**§1.9 corner design:** **31 active instances** + **6 `excluded_because:` stubs** across 11 guide sections.

**Notable design decisions:** Ledger-reconciliation primary (forward reserve vs chronological paid ledger) + compliance/audit secondary; flat topology; cyclic state shape; segregation-of-duties RBAC. All formula-derived asserts are real computed literals (verified in Python). `api_prefix` set to `""`; added `GET /benefit-payments` filtered list to satisfy FK reverse-reachability. No forbidden concurrency-race vocabulary; both concurrency rules are true OCC-on-Claim.version races. No sibling task directories were read.

## Step 3: Copy INSTRUCTION.md — 2026-06-04T10:22:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0136_workers_comp_claims/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-04T10:30:00.000Z

PRD complete at **274 lines**, written to `workspace/PRD.md` from `SCAFFOLD.yaml` only. Neither design file was opened.

**Major sections:** §1 Introduction; §2 Global Specs (11 subsections: RBAC w/ 4 roles & identity translation, response envelope, pagination, common props + logical clock, monetary precision, conserved reserve ledger, cascading reconciliation, OCC on claim writes, separation of duties, nested retrieval, validation ordering); §3 Business Logic (12 lifecycle subsections); §4 53-endpoint table; §5 15-error catalogue.

**Hard Contracts all PASS:** Field coverage 52/52 fields + 2/2 request bodies + 6/6 query params; Rule coverage 14/14 validations, 2/2 OCC rejections, 5/5 state machines, 6/6 calculations (dual-variant TTD, EMR numerator/denominator preserved literally); Path purity 199 backtick tokens scanned, 0 path/method leaks.

**Fixes during generation:** backticked bare `status` field in §3.6; corrected four reserve/EMR constants (`MED_TIER_*`, `PRIMARY_SPLIT_CENTS`) from 10× to scaffold values (250,000 / 1,500,000 / 7,500,000 / 1,700,000 cents). Envelope block matches canonical source byte-for-byte.

## Step 5: Generate Unit Tests — 2026-06-04T10:45:00.000Z

Generated complete test infrastructure from the two design indices only (no freelance SCAFFOLD walking).

**test_helpers/ (9 files):** `__init__.py`, `types.py` (12 entity TypedDicts + 11 enums; WageStatement omits updated_at/version), `api_client.py` (one method per endpoint incl. `_clock/set_current_utc`), `api_errors.py` (15 errors + HTTP-status map), `assertions.py` (per-entity + `assert_reserve_invariant`), `factories.py`, `constants.py`, `test_users.py` (opaque-role constants + entity-backed Employer identity + SoD role headers), `fixtures.py` (composite setup pipelines).

**test_suite/ (6 files, 67 test functions):** test_01_indemnity_calculations (13), test_02_experience_mod_premium (4), test_03_reserve_ledger (9), test_04_state_machines (12), test_05_validation_guards (19), test_06_entities_rbac_concurrency (10).

**Coverage:** Difficulty queue A — all **18 instances** across 9 rules, exactly 2 tests each. Corner queue B — all **31 non-stub instances**, ≥1 test each; 6 `excluded_because:` stubs NOT translated (all 6 cross-refs verified to resolve). **0 instances skipped** — every non-stub passed the PRD-first two-condition filter. Pinned numerics independently recomputed (TTD 42858/200004/85716, TPD 40002, PPD 4500225, EMR 1.72/0.96, reserves 1200060/2700060). 67/67 single `Design:` tagged, 0 skip/xfail, all byte-compile, full suite collects 0 errors.

## Step 6: Generate Implementation — 2026-06-04T10:45:00.000Z

Generated complete Python + Flask implementation in `workspace/implementation/` (25 files).

**Files:** `start.sh` (foreground, reads `$PORT` default 10000, binds 0.0.0.0, `exec python3 app.py`, pip-install guarded by `import flask` sentinel), `app.py`, `db.py` (in-memory dict stores + logical clock + id/timestamp/version stamping), `errors.py` (15 ids), `response.py` (envelope + pagination), `middleware.py` (X-User-ID/X-User-Role auth, 4 roles, RBAC), `routes/` (13 files incl. `_common.py` + `clock.py`), `services/` (`calculations.py` Decimal/ROUND_HALF_UP, `reserve.py` conserved ledger, `validation.py`).

**Endpoints:** 53 handlers — exactly matches PRD §4. Storage in-memory only, no seeding. start.sh verified boots ~0.75s, foreground, 0.0.0.0. 100+ live smoke assertions passed across auth/RBAC, all calculations, conserved reserve ledger, every state machine, OCC, SoD, IME/RTW windows, SOL, pagination.

**PRD ambiguities resolved (concrete choices):** (1) missing-reserve precondition on accept & missing-COMPLETED-IME on finalize → both `ERR_INVALID_STATE` (409); (2) `disability_days` on accept → body value when present (persisted), else claim's stored value, then fork MEDICAL_ONLY/LOST_TIME; (3) RTW buffer-conflict → half-open overlap with accepted offer's end_date extended by BUFFER_DAYS (7); (4) `mod_factor`/`current_emr` serialized as JSON floats from 2-dp Decimal; (5) `POST /_clock/set_current_utc` (output null) → 200 with `data: {}`.

## Step 7: Test & Iterate to Green — 2026-06-04T11:00:00.000Z

All 8 parallel rounds clean: 65/65 passing in every round, zero failures, zero flakiness.

**Iterations run:** 2 (initial diagnostic sweep + verification sweep after fix).

**Initial state:** 65/67 passing in all 8 rounds — a stable (non-flaky) union of exactly 2 failing tests, both in `test_05_validation_guards.py`, both failing with `AssertionError: Expected response_type 'error', got 'object'` (implementation returned a successful payment where the test expected `ERR_INVALID_STATE`).

**Tests deleted (2)** — both under PRD-silence category **STEP 1b: unique-derivability broken (state-definition / error-precedence silence):**

1. `test_benefit_payment_on_denied_claim_returns_invalid_state` — asserted `POST /benefit-payments` against a `DENIED` claim returns `ERR_INVALID_STATE`.
2. `test_benefit_payment_on_reported_claim_returns_invalid_state` — asserted `POST /benefit-payments` against a `REPORTED` claim returns `ERR_INVALID_STATE`.

**Rationale:** Both cited only PRD §2.11's *generic* precedence sentence (the state-machine check ordering). That sentence is a precedence ordering rule — it does not define which claim states permit a benefit-payment posting. PRD §3.6 describes posting, the reserve drawdown, the `claim_class` flip, and `ERR_RESERVE_INSUFFICIENT`, but contains no sentence restricting the source claim status or naming `ERR_INVALID_STATE` for benefit payments. The scaffold's own Claim state machine does NOT model `POST /benefit-payments` as a claim-status transition (posting never changes `claim.status`) — so it is not one of "all state-transition endpoints." §3.6's statement that the *first* TTD/TPD payment flips `claim_class` from `UNCLASSIFIED` to `LOST_TIME` implies payments occur on not-yet-`LOST_TIME` claims. A faithful PRD-only implementer would reasonably produce the exact implementation under test. Both trace to difficulty-design corner `priority_pair_validation_conflict/state_vs_fiscal_on_benefit_payment` — a scaffold-only artifact with no PRD-prose backing.

**Fixes applied to `test_helpers/`:** None.
**Fixes applied to `implementation/`:** None. (Adding the `ERR_INVALID_STATE` guard the tests demanded would introduce a capability not traceable to any verbatim PRD sentence.)

**Final state:** Clean 8-round parallel sweep — 65/65 passing in every round, 0 failed, 0 errors, no flakiness.

## Step 8: Finalize PRD — 2026-06-04T11:05:00.000Z

Produced `workspace/PRD_FINALIZED.md`. PRD.md = 274 lines; PRD_FINALIZED.md = 274 lines; **0% line-count delta** (one paragraph in §3.6 expanded in place).

**Changes (1):**
- **§3.6 Disbursing Indemnity Benefits — insert** — pin that posting a benefit payment has no source-claim-`status` precondition and never raises `ERR_INVALID_STATE` — `implementation/routes/benefit_payments.py:26-95` (`create_benefit_payment` checks only existence → benefit-type → amount → reserve-sufficiency → PPD finalized-rating; no `claim["status"]` gate; the file's only `ERR_INVALID_STATE` is the unrelated void-status guard at line 134).

This pins the silence the Step 7 deletions revealed: implementation posts payments regardless of claim status (DENIED/REPORTED included); a fresh PRD-only implementer could plausibly add a status gate, diverging. Wording deliberately scoped to benefit payments only (not §3.4/§3.7 reserve/medical paths), preserves the existence/`ERR_NOT_FOUND`, reserve-sufficiency, and PPD finalized-rating constraints the impl still enforces. No §2.11 contradiction.

## Step 9: Complete PRD — 2026-06-04T11:08:00.000Z

Produced `workspace/PRD_COMPLETED.md` via full PRD-vs-implementation scan. `PRD_FINALIZED.md` (274 lines, 41,826 chars) → `PRD_COMPLETED.md` (274 lines, 44,248 chars). Char delta **+2,422**. No new lines/sections — all 8 changes are in-place revisions.

**Counts:** ambiguity-pins **6**; mismatch-revisions **2**.

- §3.1 (Workers) — insert — ambiguity — `gross_wages_cents` may not be negative — `workers.py:27`.
- §3.3 (Accept/fork) — revise — mismatch — `FROI`-`ACKNOWLEDGED` precondition checked before the disability fork (governs medical-only path too); `disability_days` re-supplied at accept overwrites stored value — `claims.py:121-130`.
- §3.3 (Accept/fork) — insert — ambiguity — lost-time acceptance with acknowledged FROI but no reserve row → `ERR_INVALID_STATE` — `claims.py:136-138`.
- §3.4 (Reserve creation) — insert — ambiguity — reserve creation imposes no claim-state precondition, never raises `ERR_INVALID_STATE` — `reserves.py:20-31`.
- §3.6 (Void) — insert — ambiguity — voiding a non-`POSTED` payment → `ERR_INVALID_STATE`, scoped to void only — `benefit_payments.py:133-135`.
- §3.7 (Medical payment) — insert — ambiguity — medical payment not separately persisted, returns HTTP 201 with the updated reserve object — `reserves.py:74-81`.
- §3.8 (Dispute) — insert — ambiguity — disputing a rating not both `PROPOSED` and `TREATING`-issued → `ERR_INVALID_STATE` — `impairment_ratings.py:80-82`.
- §3.10 (RTW accept) — revise — mismatch — TPD wage offset always taken from the temporary-partial payment request body, never read back from an accepted offer's `light_duty_weekly_cents` — `benefit_payments.py:50-57`.
- §3.12 (Experience-mod) — insert — ambiguity — `ballast_cents` and `expected_excess_cents` may not be negative — `experience_mods.py:28,30`.

**Deliberately left unpinned:** §2.1's "transitively through a claim's policy and worker" ownership — impl resolves employer via policy only; surfaces only with cross-employer workers, untested, prose remains defensible.

---

## Pipeline complete — 2026-06-04T11:08:30.000Z

Final verification: all 8 stability-sweep rounds green (65/65 each). Task `task_0136_workers_comp_claims` is fully built and passing at Expert difficulty.
