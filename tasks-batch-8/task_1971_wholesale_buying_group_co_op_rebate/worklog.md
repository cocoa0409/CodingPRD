# Worklog — task_1971_wholesale_buying_group_co_op_rebate

## Step 1: Create Task Directory — 2026-08-15T03:54:00.000Z

Directory `tasks/task_1971_wholesale_buying_group_co_op_rebate/` and `workspace/` created externally by the pipeline launcher (pre-existing per orchestration args); orchestrator verified existence and skipped index computation as instructed.

## Step 2: Generate Scaffold — 2026-08-15T04:19:18.000Z

All three files written and lint is clean. Here's the final summary:

## Final Summary — Task 1971 Wholesale Buying Group & Co-op Rebate Administration

**Files on disk** (all three confirmed):
- `/home/ubuntu/github/CodingPRD/tasks/task_1971_wholesale_buying_group_co_op_rebate/SCAFFOLD.yaml` (76,272 bytes)
- `/home/ubuntu/github/CodingPRD/tasks/task_1971_wholesale_buying_group_co_op_rebate/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (99,296 bytes)
- `/home/ubuntu/github/CodingPRD/tasks/task_1971_wholesale_buying_group_co_op_rebate/SCAFFOLD_CORNER_DESIGN.yaml` (75,728 bytes)

**Lint verdict** — `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (61 endpoints, 11 entities, 20 §1.8 instances, 33 §1.9 active instances, 533 calls scanned, 0 violations).

**Complexity profile**: Primary archetype = Ledger reconciliation; Secondary = Quota/allocation; Layers = cascading_side_effects, dual_variant_calculation, derived_field_reconciliation, optimistic_concurrency.

**Counts**:
- Entities: **11** (Coop, Member, Supplier, SupplierProgram, ProgramEnrollment, PurchaseReport, VolumeAudit, RebateAccrual, QuarterlyDistribution, ClawbackCase, HoldbackRelease) — inside the Expert band (10–15)
- Endpoints: **61** (well above the 20–32 Expert band — driven by the segregation-of-duties role model which splits write endpoints across CoopAdmin / MemberRep / SupplierRep / FinanceOfficer / ProgramAuditor)
- Error codes: **22** (inside the 18–30 Expert band)
- State machines: **10** (every entity has a lifecycle; VolumeAudit has APPEALED→FIELDWORK cycle; Member has ACTIVE↔SUSPENDED cycle; PurchaseReport has FLAGGED→SUBMITTED revise loop; RebateAccrual has FINALIZED→OPEN→FINALIZED re-finalization loop)
- Calculation variants: **6 calculations** with **4 dual-variant calculations** (rebate_tier_resolution: provisional vs final; pass_through_split: by commitment_level; holdback_calculation: FLAT vs RISK_ADJUSTED; clawback_amount: gross vs net)
- Concurrency rules: **2** OCC rules (SupplierProgram amend, QuarterlyDistribution recalc)

**Difficulty layers chosen**: cascading_side_effects, dual_variant_calculation, derived_field_reconciliation, optimistic_concurrency (4 layers, targeting the harder-than-Expert band via dense cross-entity coupling: audit→report→accrual→distribution→holdback→clawback forms a 5+-hop retroactive cascade).

**§1.8 instance counts per rule** (all ≥ 2; total 20):
- dual_variant_calc: **3** (accrual provisional/final; clawback gross/net; holdback flat/risk-adjusted)
- combinatorial_formula: **2** (clawback waterfall — mode (a); holdback per-member rounding — mode (b))
- non_linear_state_machine: **2** (VolumeAudit appeal cycle; Member suspend/reinstate cycle)
- transitive_cascade: **3** (audit.resolve → report → accrual → re-finalize [depth 4]; Member.churn → enrollments + clawback + holdback forfeit [depth 3]; close_quarter → accrual + exclusivity → clawback [depth 2])
- priority_pair_validation_conflict: **2** (state vs business_fiscal; existence vs business_constraint)
- boundary_precision_check: **2** (tier min_qty >= boundary; exclusivity share == threshold boundary)
- cross_entity_state_dependency: **2** (SupplierProgram→Supplier; ProgramEnrollment→Member)
- resource_temporal_overlap: **2** (PurchaseReport quarter point-equality; Coop pool aggregate-capacity)
- compensating_invariant: **2** (per-accrual split conservation; pool conservation across disburse+clawback)

**§1.9 corner instance count**: **52 total** = 33 real test_recipes + 19 `excluded_because` stubs citing §1.8 or other §1.9 instances. Sections covered: entities (7), state_machines (8), calculations (3), validations (5), endpoints (3), errors (18), rbac (3), cross_cutting_complexity_layers (4), consistency_model (1).

**Quality Checklist highlights**:
- File split honored (no `scaffold_difficulty_design` or `scaffold_corner_design` keys inside SCAFFOLD.yaml)
- All FK descriptions use the canonical `FK -> {Entity}.id` prefix
- Every FK has a reverse-reachability GET (sub-resource or filtered list)
- All `expected_*_version` OCC payloads reference `${var}` captures, never bare literals
- No forbidden vocabulary ("simultaneously", "first-writer-wins", "race winner", etc.)
- All role identities declared (`entity_backed:Member` for MemberRep, `entity_backed:Supplier` for SupplierRep, opaque for the three operational roles)
- Server default clock time `2026-08-01T00:00:00Z` documented on the `/_clock/set_current_utc` endpoint
- Formula-derived asserts in §1.8 are pre-computed literals (e.g., 7500/2500 split on 10000; 3375 total holdback across mixed FLAT+RISK_ADJUSTED programs; 6750 net clawback after 750 holdback forfeit)

(Orchestrator note: the Step 2 subagent required three resume prompts to reach completion — it repeatedly paused at planning boundaries; final state verified on disk by the orchestrator: all three files present, lint clean per subagent report.)

## Step 3: Copy Shared Files — 2026-08-15T04:19:40.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1971_wholesale_buying_group_co_op_rebate/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-15T04:39:10.000Z

PRD generation complete and verified. `/home/ubuntu/github/CodingPRD/tasks/task_1971_wholesale_buying_group_co_op_rebate/workspace/PRD.md` exists on disk — 323 lines, 54,793 bytes.

## Document structure

- **§1. Introduction** — 2 paragraphs (business context + system philosophy, `/coop` mount)
- **§2. Global Specifications** — 10 subsections: 2.1 RBAC (all 5 roles with exact identity models: MemberRep→`Member` entity-backed, SupplierRep→`Supplier` entity-backed, CoopAdmin/FinanceOfficer/ProgramAuditor opaque), 2.2 Response Structure (verbatim fixed block), 2.3 Pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending), 2.4 Resource Identity/Versioning, 2.5 Logical Quarter Clock, 2.6 Money/Basis-Points/Rounding, 2.7 Rebate Pool Ledger, 2.8 OCC, 2.9 Validation Order (ordered 21-item pipeline with per-item scope), 2.10 Nested Resources
- **§3. Business Logic** — 7 subsections: bootstrap/cadence, member lifecycle, supplier/program negotiation, enrollments/purchase reporting, volume audits, quarter-close/distribution, clawbacks/churn economics
- **§4. Endpoint Definitions** — 61 rows, 4 columns (Method, Path, Description, Authorized Role(s))
- **§5. Error Code Catalogue** — 22 rows, 2 columns (Error ID, HTTP Status)

## Hard Contract Reports

**Field coverage check:**
- entities[].fields: 62 required, 62 present, 0 missing
- endpoints[].input/query_params: all required identifiers present (deduplicated required set: 71 incl. `min_qty`/`rate_bps`, common fields, `HOLDBACK_LAG_QUARTERS`, `current_utc`), 71 present, 0 missing
- Status: PASS

**Rule coverage check:**
- validations[] with priority: 21 checked, 21 expressed as an ordered §2.9 pipeline with per-item applies-to scopes, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (`PUT /coop/supplier-programs/{id}` + `expected_program_version` + `ERR_STALE_PROGRAM_VERSION`/412; `POST /coop/distributions/{id}/calculate` + `expected_distribution_version` + `ERR_STALE_DISTRIBUTION_VERSION`/412), 0 missing
- state_machines[].transitions: 42 transitions across 10 machines checked, all from/to pairs, preconditions with error IDs, and side effects expressed (incl. sibling symmetry: both churn branches, all four terminate branches, resolve/waive from both NOTIFIED and DISPUTED), 0 missing
- calculations[]: 6 checked, 6 fully expressed with exact constants (10,000 bps denominator; 8,500/7,500/6,500 split rates with 1,500/2,500/3,500 retained complements; 1,000/2,500 holdback bps; inclusive threshold of 2 material findings; 5% MINOR band; floor-at-zero net clawback with forfeiture-before-netting order), 0 missing
- validations[] conditions: 21 checked, 21 matchable to error_id in prose, 0 missing
- endpoints[].side_effects: all expressed (incl. revise creates-new-row semantics at 201, resolve's 5-hop cascade, disburse's pool/retained/accrual/holdback-release effects)
- entities[].fields[] structured content: defaults and nullability reconstructible (e.g., `onboarding_notes` empty string, `audited_*` null until resolution, `exit_quarter_index` null while ACTIVE/SUSPENDED, computed counters start at 0)
- sibling-branch symmetry: 8 groups checked, 8 equal density
- Status: PASS

**Path purity check (§3 only):**
- backtick tokens scanned: 469
- tokens starting with `/`: 0; bare HTTP-method tokens: 0; method+path tokens: 0
- Status: PASS

Also verified: all 35 state enum strings, all 14 field-enum values, all 22 error IDs, and all 5 role names appear verbatim; §4 table contains all 61 scaffold endpoints with exact method+path and role gating; §5 contains all 22 errors with correct HTTP statuses. The withheld `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, and no sibling task directory was read.

## Step 5: Generate Unit Tests — 2026-08-15T05:19:10.000Z

Done. All generation and audit passes complete.

## Summary — task_1971_wholesale_buying_group_co_op_rebate

### Output inventory

**`test_helpers/` (9 files):**
- `types.py` — 14 status/role enums + 11 entity TypedDicts (all entities carry `id/created_at/updated_at/version`; nullable system fields typed `Optional`)
- `api_client.py` — `ApiClient(GenericApiClient)` with 49 endpoint methods covering the full PRD §4 surface
- `api_errors.py` — `ApiErrorId` (22 errors) + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` checkers plus `assert_split_invariant` / `assert_pool_non_negative` domain invariants
- `factories.py` — payload factories for all creatable entities
- `constants.py` — PRD-stated rate constants (8500/7500/6500 split bps, 1000/2500 holdback bps, threshold 2, denominator 10000) + tier-resolution helpers. `HOLDBACK_LAG_QUARTERS` is deliberately absent (PRD never states its value) with a comment explaining why
- `test_users.py` — `TEST_USERS` shared headers + mandatory `make_member_rep_headers(member_id)` / `make_supplier_rep_headers(supplier_id)` entity-backed builders
- `fixtures.py` — 5-tier composite helpers (bootstrap → active member/onboarded supplier/open program/enrollment → report submission → draft→calculated→disbursed distribution → audit drive/resolve → MATERIAL-findings accumulator → churn/clawback resolution), all identity-threaded
- `__init__.py` — barrel export

**`test_suite/` (8 files, 69 test functions):** `conftest.py` + `test_01_bootstrap_and_members.py` (9), `test_02_suppliers_programs_enrollments.py` (13), `test_03_purchase_reports.py` (8), `test_04_volume_audits.py` (6), `test_05_quarter_close_and_distribution.py` (14), `test_06_churn_clawback_holdback.py` (12), `test_07_security_and_rbac.py` (7).

### Per-queue coverage
- **Queue A (§1.8 difficulty): 18/20 instances translated, each with exactly ≥2 tests (36 tests). 2 skipped:**
  1. `priority_pair_validation_conflict/state_trumps_quarter_mismatch_on_report_submit` — asserted outcome (`ERR_MEMBER_NOT_ACTIVE`) contradicts PRD §2.9's explicit pipeline order and §3.4's "per the pipeline order in §2.9, the quarter-match check fires first" (check 7 precedes check 13 → `ERR_QUARTER_MISMATCH` is the unique answer).
  2. `compensating_invariant/split_invariant_holds_across_refinalization` — asserted post-refinalization values (2000/1500/500) are not uniquely derivable: PRD §3.6 finalizes only accruals whose `quarter_index` matches the closing quarter, so a quarter-0 accrual re-opened during quarter 1 never re-finalizes under the literal reading (conflicts with §3.5's re-finalize promise).
- **Queue B (§1.9 corner): 33/33 non-stub instances translated (33 tests). 19 `excluded_because:` stubs not translated** (their cited owner instances exist and are translated).

### Key design decision
PRD §3.6 uniquely derives that a distribution is created with `quarter_index` = the co-op's *current* quarter and `calculate` aggregates only matching-quarter FINALIZED accruals — so every distribution fixture creates the DRAFT distribution **before** `close_quarter`, then closes, then calculates. This is the only ordering any PRD-only reader can reach; the YAML recipes' literal post-close creation order would be ambiguous.

### Verification (all automated passes clean)
- All 69 docstrings end with exactly one verbatim `Design: Difficulty/...` or `Design: Corner/...` line; zero unknown tags, zero stub translations, zero under-covered instances.
- All 105 quoted PRD citation spans survive a whitespace-normalized literal match against `PRD.md` (C1/C3).
- No `pytest.mark.skip`/`skipif`/`xfail`, no scaffold references in comments, all files compile.

## Step 6: Generate Implementation — 2026-08-15T05:19:10.000Z

Done. The implementation is complete and verified.

## File inventory — `tasks/task_1971_wholesale_buying_group_co_op_rebate/workspace/implementation/`

- `start.sh` — guarded pip install (`import flask` check), `exec python3 app.py`, foreground, `$PORT` (default 10000), binds `0.0.0.0`
- `requirements.txt` — flask only
- `app.py` — Flask entry, ApiError/404/405/500 handlers, blueprint registration
- `db.py` — in-memory `Store` (dicts keyed by id), logical clock (default `2026-08-01T00:00:00Z`), UUID/`version=1`/`created_at`/`updated_at` minting, `_seq` for stable created_at ordering; **no seeding — store boots empty**
- `errors.py` — all 22 error IDs with exact strings/statuses
- `response.py` — `meta`/`response_type`/`data` envelope, `req_*` ids, 3-fractional-digit timestamps, list pagination (`limit`/`offset`/`total_count`/`has_more`, defaults 10/0, clamped 1–100 with 400 on violation)
- `middleware.py` — `X-User-ID`/`X-User-Role` extraction, 5-role validation, role-gate decorator, body schema validators
- `routes/` — 11 blueprints: coop, members, suppliers, programs, enrollments, reports, audits, accruals, distributions, clawbacks, holdbacks
- `services/calc.py` — tier resolution (inclusive `>=` min_qty, floor after single mul/div by 10,000), pass-through split (8500/7500/6500 bps, retained as exact complement), finding severity (NONE / 0<ratio≤5% MINOR via integer cross-multiplication / MATERIAL), clawback waterfall (gross over DISTRIBUTED accruals → forfeit SCHEDULED holdbacks → net floored at 0)
- `services/lifecycle.py` — close_quarter 4-cascade (finalize OPEN accruals due, exclusivity recompute + SHORTFALL-flip clawbacks, due holdback releases, coop version), audit resolve cascade, distribution calculate/disburse, clawback resolve

## Coverage

- **Endpoints: 61/61** registered and individually exercised
- **Errors: 22/22** wired, including both OCC 412s, `ERR_INSUFFICIENT_POOL`, `ERR_QUARTER_MISMATCH`, `ERR_OPEN_CLAWBACK`, `ERR_NOT_RESOURCE_OWNER` (only on the 4 member-scoped ops, per pipeline item 18)
- **State machines: 10/10** (Member, Supplier, SupplierProgram, ProgramEnrollment, PurchaseReport, VolumeAudit incl. APPEALED→FIELDWORK cycle, RebateAccrual incl. FINALIZED→OPEN re-finalization loop, QuarterlyDistribution, ClawbackCase, HoldbackRelease)
- **Calculations: 6/6** with exact constants; 21-item validation pipeline in priority order (auth → role → path → schema → FK → state → business → ownership → OCC); both OCC rules — including the distribution-version bump when a late audit resolution recomputes an accrual covered by a DRAFT distribution (per the OCC rule's own description)

## Judgment calls on spec gaps (documented in code)

- `HOLDBACK_LAG_QUARTERS` has no value in PRD or SCAFFOLD — set to **2**
- Bootstrap twice → 409 `ERR_INVALID_STATE`; audit open requires the report be `SUBMITTED` (409 otherwise)
- `close_quarter` finalizes OPEN accruals with `quarter_index <= closing` so pulled-back accruals re-finalize as PRD §3.5 promises
- Pool ledger literal per spec: every finalization adds `final_rebate_cents` (preserves the pool ≥ 0 invariant)
- FLAT holdback total computed on distribution-wide pass-through; per-member HoldbackRelease rows use per-member floors

## Boot check

`bash start.sh` on a test port: boots in ~2.5 s, binds 0.0.0.0, headerless request → 400 envelope, five end-to-end smoke suites (main lifecycle, edge cases, retroactive-audit/pool ledger, OCC/offsets, pool insufficiency) all pass against fresh `start.sh` boots — confirming per-test-server restart cleanliness.

(Orchestrator note — cross-step divergence flagged for Step 7/8/9: Step 5 skipped §1.8 instance `split_invariant_holds_across_refinalization` judging PRD §3.6 finalizes only matching-quarter accruals (so a re-opened quarter-0 accrual never re-finalizes); Step 6 implemented `close_quarter` as finalizing OPEN accruals with `quarter_index <= closing` citing §3.5's re-finalize promise. Also `HOLDBACK_LAG_QUARTERS=2` is an implementation judgment call PRD does not pin. Both are Step 8/9 PRD-alignment candidates.)

## Step 7: Run Tests and Iterate — 2026-08-15T05:39:13.000Z

All 8 rounds pass cleanly (69/69 × 8). The loop is complete.

---

## Summary

**Iterations run:** 3 sweeps (24 rounds total) — sweep 1: 5 deterministic failures in every round; sweep 2 (after 3 fixes): 69/69 in 7 rounds + 1 transport-level flake in round 5; sweep 3 (after waitress hardening): all 8 rounds 69/69 clean.

**Tests deleted:** none wholesale. One assertion removed per STEP 1c partial-coverage handling:
- `test_06_churn_clawback_holdback.py::TestExclusivityBreachClawback::test_exclusivity_breach_clawback_records_trigger_quarter` — removed `assert case["trigger_quarter_index"] == 0`. Unique-derivability collapse (quarter-stamping ambiguity): PRD §3.7 says "`trigger_quarter_index` records the quarter of the triggering event", but §3.6 states the counter "first advances by one" and *then* the cascades run — so a faithful implementer may stamp either the closing quarter (0) or the newly advanced quarter (1). Both readings are one-line implementations consistent with the cited sentence. The test's remaining assertions (`trigger_reason == EXCLUSIVITY_BREACH`, `status == OPEN`, `recovered_cents == 0`) are PRD-verbatim and were kept. Scaffold rule behind the Design tag: `Difficulty/transitive_cascade/quarter_close_cascades_to_exclusivity_breach_clawback`.

**Fixes applied to `test_helpers/`:**
- `test_helpers/assertions.py::assert_member` — `enrolled_quarter_index` now accepts `None` (mirroring `churn_quarter_index`). PRD §3.2 stamps `enrolled_quarter_index` only at activation, so a PENDING member legitimately returns null; the helper's unconditional `isinstance(int)` was the bug behind `test_member_create_returns_pending_with_defaults`.

**Fixes applied to `implementation/`:**
- `workspace/implementation/services/lifecycle.py::disburse_distribution` — member credit changed from `pass_through − withheld` to the full `pass_through` share. PRD §3.6 defines "The member's share, `pass_through_cents`" and states disbursement "credits each member's `lifetime_pass_through_cents` by that member's share" — the defined term pins the credit at the full share (fixed 3 tests asserting 7500, was crediting 6750). The separate PRD-mandated release-time credit (`§3.6` third cascade: "the member's `lifetime_pass_through_cents` grows by `release_cents`") was preserved.
- `workspace/implementation/app.py` + `start.sh` + `requirements.txt` — serve via `waitress` (threads=8, flask dev-server fallback retained). The round-5 flake was `RemoteDisconnected` mid-test on the werkzeug dev server under heavy shared-host load (4 other task pipelines sweeping concurrently; the shared test client has no retry on POST). Serving-layer hardening only; no PRD-visible behavior changed. Precedent pattern copied from task_1922.

**Known-divergence note:** the flagged `quarter_index <= closing` re-finalization choice in `close_quarter` (PRD §3.5's "next quarter close re-finalizes it") and `HOLDBACK_LAG_QUARTERS=2` remain as-is — no surviving test touches either, consistent with the PRD-only contract.

## Step 8: Finalize PRD — 2026-08-15T05:47:17.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1971_wholesale_buying_group_co_op_rebate/workspace/PRD_FINALIZED.md` written with 4 inline edits, all traced to Step 7 diff items.

## Summary on exit

**Line counts / delta:** PRD.md = 323 lines; PRD_FINALIZED.md = 323 lines (0 line delta; +0.783% characters). All edits are in-place sentence revisions; no sections added or removed.

**Changes (one bullet each):**
- §3.7 (line 220) — revise — `trigger_quarter_index` now pinned as "stamped with the co-op's `current_quarter_index` at the moment the case is created," with an explicit clause that the exclusivity-breach trigger at quarter close records the newly advanced quarter (not the closing quarter) because the counter advances before the cascades run — `implementation/services/calc.py:195` (stamping site), `implementation/services/lifecycle.py:34-35,88` (advance-then-cascade order).
- §3.1 (line 146) — revise — "every still-`OPEN` rebate accrual belonging to the closing quarter" → "of the closing quarter or any earlier quarter" — `implementation/services/lifecycle.py:42` (`a["quarter_index"] <= closing`).
- §3.6 (line 202) — revise — "whose `quarter_index` matches the closing quarter" → "is the closing quarter or any earlier quarter — including an accrual pulled back to `OPEN` by a late audit resolution per §3.5, which is thereby re-finalized at this close" — `implementation/services/lifecycle.py:40-49`; resolves the internal contradiction with §3.5's "the next quarter close re-finalizes it" (line 194).
- §3.6 (line 214) — revise — `HOLDBACK_LAG_QUARTERS` value pinned: "the standing holdback lag constant, fixed at 2 quarters" (the PRD named the constant but never gave its value) — `implementation/services/calc.py:24` (`HOLDBACK_LAG_QUARTERS = 2`), sole use at `implementation/services/lifecycle.py:252`.

**No-edit verifications (PRD already determines behavior):**
- §3.6 disbursement credit — PRD's defined term "The member's share, `pass_through_cents`" (line 202) + "credits each member's `lifetime_pass_through_cents` by that member's share" (line 214) already pins the full gross share; Step 7's fix was to the implementation (now crediting `bucket["pass_through"]`, lifecycle.py:242). Verbatim kept.
- §3.2 `enrolled_quarter_index` — "Activation stamps `enrolled_quarter_index`" (line 152) already determines null-until-activation; Step 7 classified this as a pure test-helper fixture bug. Impl: `members.py:43` (None at creation), `members.py:87` (stamped at activation). Verbatim kept.
- Waitress serving layer — not a PRD topic; no edit.

**Per-edit pre-edit search log (NO-NEW-MISMATCH RULE):**

1. **§3.7 `trigger_quarter_index`:**
   - (a) Subject: quarter index written on clawback-case creation.
   - (b) Paths enumerated: single stamping site `calc.py:195` (`coop["current_quarter_index"]`); all three callsites — `members.py:144` (CHURN: same request as `churn_quarter_index = current`, members.py:135-136, so creation-time counter == churn quarter), `lifecycle.py:163` (AUDIT_SHORTFALL: same request as `resolved_quarter_index = current`, lifecycle.py:122), `lifecycle.py:88` (EXCLUSIVITY_BREACH: runs after counter advance at lifecycle.py:35, so stamps closing+1). PRD cross-refs checked: §2.5 line 84 (names field only), §3.2 line 156, §3.5 line 194.
   - (c) Wording framed as the universal rule (creation-time `current_quarter_index`) plus the quarter-close consequence clause, so all three callsites are correctly described — for CHURN/AUDIT_SHORTFALL the rule coincides with "quarter of the triggering event"; for EXCLUSIVITY_BREACH it pins the newly advanced quarter.
2. **§3.1 finalization scope:**
   - (a) Subject: which OPEN accruals quarter close finalizes.
   - (b) Paths: selection site `lifecycle.py:40-49` (only callsite of `finalize_accrual`); accrual creation only at `reports.py:80` under `quarter_index == current_quarter_index` enforcement (reports.py:71-75), so no future-quarter accrual can exist and `<= closing` ≡ "closing quarter or earlier"; pull-back producer at `lifecycle.py:144-145`. §3.1 line 146 defers mechanics to §3.5/§3.6 and already names the "re-finalization loop."
   - (c) Used "of the closing quarter or any earlier quarter" — matches the reachable filter set exactly without implying future-quarter accruals exist.
3. **§3.6 finalization selection:**
   - (a) Subject: same as (2), at the detailed-rule site.
   - (b) Same paths as (2), plus the parallel selection rule at distribution *calculation* (`lifecycle.py:172`, `a["quarter_index"] == dist["quarter_index"]`, PRD line 212) — confirmed that rule is strict equality and intentionally left untouched; the FLAGGED-hold clause (`lifecycle.py:46-48`, PRD line 202 tail) untouched.
   - (c) Added the parenthetical tying the widened selection to §3.5's pull-back so the edit removes the §3.5/§3.6 contradiction rather than just widening silently.
4. **§3.6 `HOLDBACK_LAG_QUARTERS=2`:**
   - (a) Subject: numeric value of the named lag constant.
   - (b) Paths: definition `calc.py:24`; sole use `lifecycle.py:252`; due-check `lifecycle.py:94` (`release_quarter_index <= current`, matches PRD line 206 verbatim); forfeiture paths (`calc.py:182-186`, churn cascade) never read the lag. PRD refs: line 7 ("lag period," no value), line 84 (field name only), line 206 (≤ rule), line 214 (edit site).
   - (c) Inserted ", fixed at 2 quarters," into the existing appositive — no restructuring, consistent with every enumerated path.

## Step 9: Complete PRD — 2026-08-15T06:05:56.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1971_wholesale_buying_group_co_op_rebate/workspace/PRD_COMPLETED.md` is written (edited copy of PRD_FINALIZED.md; no other files touched).

**Source vs output:** PRD_FINALIZED.md 323 lines / 55,230 chars → PRD_COMPLETED.md 323 lines / 59,307 chars (+0 lines, +4,077 chars — all edits are inline paragraph inserts/revisions; no new sections, structure unchanged).

**Counts:** 21 changed passages — 16 ambiguity-pins (PRD silent), 5 mismatch-revisions (PRD described different behavior; §2.9-closing and §3.6-guard edits each carry one small mismatch fix inside an otherwise ambiguity-driven edit).

Changes (section — insert|revise — ambiguity|mismatch — what — impl ref):

- §2.3 — revise — ambiguity — pinned `ERR_INVALID_REQUEST` (400) for non-integer/out-of-range `limit`/`offset` and non-integer `quarter_index`-type filters; pinned list tie-break by creation order — response.py:54-84
- §2.4 — revise — ambiguity — `version` starts at 1 at creation — db.py:58-68
- §2.5 — revise — ambiguity — missing/unparsable `to_iso8601` → `ERR_INVALID_REQUEST` — routes/coop.py:43-48
- §2.8 — revise — mismatch — replaced unreachable stale-cause example ("a prior calculation already ran" → 409, never 412) with the real one: late audit resolution bumping a still-`DRAFT` distribution's version — services/lifecycle.py:148-153
- §2.9 item 9 — revise — ambiguity — tier schedule must be *strictly* ascending (no duplicate `min_qty`) and every `min_qty` non-negative — routes/programs.py:55-70
- §2.9 closing — revise — ambiguity + mismatch — pinned schema validation's position (after path-existence, before all later checks); "positive"→"non-negative" (zero reports/attestations accepted); out-of-enumeration values named as schema failures — middleware.py:42-55, routes/reports.py:65-66
- §3.1 — revise — ambiguity — bootstrap-twice → `ERR_INVALID_STATE` (409); any singleton access pre-bootstrap → `ERR_NOT_FOUND` (404) — routes/coop.py:22-23, db.py:77-81
- §3.2 — revise — ambiguity — invalid `commitment_level` → `ERR_INVALID_REQUEST`; `enrolled_quarter_index` null until activation — routes/members.py:36-43
- §3.2 — revise — mismatch — `lifetime_pass_through_cents` credited at disbursement and at holdback release, not "across all reconciled quarters" — services/lifecycle.py:104-109, 234-245
- §3.3 — revise — ambiguity — invalid `holdback_policy` → `ERR_INVALID_REQUEST` — routes/programs.py:90-91
- §3.4 — revise — ambiguity — initial `exclusivity_status`: `COMPLIANT` if program requires exclusivity else `NOT_APPLICABLE` — routes/enrollments.py:53-55
- §3.4 — revise — ambiguity — provisional rebate sums qty/cents across all non-`SUPERSEDED` reports of the enrollment+quarter (repeat submissions accumulate), tier resolution run once on the sums — services/calc.py:86-112, 141-150
- §3.4 — revise — ambiguity — revision's new report gets a fresh `submitted_at_quarter` at revision time — routes/reports.py:42-56, 167-168
- §3.5 — revise — ambiguity — audit-open against non-`SUBMITTED` report → `ERR_INVALID_STATE` (409) — routes/audits.py:42-44
- §3.5 — revise — ambiguity — resolution stores attested `audited_qty`/`audited_cents` on the audit itself; `self_report_cents` == 0 with differing figures → `MATERIAL` by convention — services/lifecycle.py:120-124, services/calc.py:61-71
- §3.5 — revise — ambiguity — resolving an audit whose report was superseded: report stays `SUPERSEDED`, rest of cascade still runs; final-variant recomputation also increments every still-`DRAFT` covering distribution's `version` — services/lifecycle.py:128-153
- §3.6 — revise — mismatch + ambiguity — finalization guard reads "every purchase report … ADJUDICATED or SUBMITTED"; pinned that `SUPERSEDED` reports are excluded (only a live `FLAGGED` report blocks), and final evidence is summed across live reports — services/lifecycle.py:45-49, services/calc.py:86-91
- §3.6 — revise — ambiguity — re-finalization after audit pull-back books `final_rebate_cents` into the pool again (every finalization is a pool event) — services/lifecycle.py:25-27
- §3.6 — revise — ambiguity — distribution creation not limited to one per quarter — routes/distributions.py:44-61
- §3.6 — revise — mismatch — holdback computation pinned for mixed distributions: `FLAT`-policy pass-through pooled distribution-wide with one floor at 1,000 bps; `RISK_ADJUSTED`-policy pass-through withheld per member at the member's band with per-member floors; `holdback_cents` is their sum — services/lifecycle.py:179-205
- §3.6 — revise — mismatch (+ one pin) — releases are one-per-member (not per-accrual), created only when the member's withheld amount > 0, with `release_cents` computed under per-member floors (so releases can sum to less than `holdback_cents`, residue staying in the pool); also pinned the lifetime credit as the full `pass_through_cents`, not net of holdback — services/lifecycle.py:219-256

The three pre-resolved judgment calls (`trigger_quarter_index` creation-time stamping §3.7, close-quarter scope "closing quarter or any earlier" §3.1/§3.6, `HOLDBACK_LAG_QUARTERS` = 2 §3.6) were verified already pinned in PRD_FINALIZED.md and left untouched.
