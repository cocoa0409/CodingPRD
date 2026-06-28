# Worklog — task_0614_pet_wellness_plan

## Step 1: Create task directory — 2026-06-21T17:21:00.000Z

Created `tasks/task_0614_pet_wellness_plan/` and `tasks/task_0614_pet_wellness_plan/workspace/` via mkdir -p. Pre-allocated path used verbatim (no auto-indexing — 5 sibling pipelines running in parallel).

## Step 2: Generate Scaffold (Expert band) — 2026-06-21T17:39:00.000Z

**Domain:** Pet Wellness-Plan Membership (Banfield Optimum Wellness style) — ledger-reconciliation archetype (forward-looking entitlement valuation vs chronological credit consumption) blended with pricing-engine secondary (tiered à-la-carte pricing + daily-rate proration).

**Difficulty band applied:** Expert (§0.4).

**Scaffold metrics:**
- Entities: 12 (Plan, PlanService, Clinic, MemberAccount, Membership, EnrolledPet, ContractTerm, ServiceCredit, ServiceVisit, BillingCycle, PlanChangeRequest, ClockState)
- State machines: 4 (Membership — branching + cyclic; ContractTerm — cyclic renewal ACTIVE→RENEWAL_PENDING→EXPIRED→successor ACTIVE; ServiceVisit — compensation; EnrolledPet — ENROLLED↔SUSPENDED cycle + terminal REMOVED)
- Calculations: 7 (entitlement grant [forward, dual-variant], chronological credit consumption, à-la-carte tiered pricing, plan-change proration [pinned round-once], term-balance reconciliation, early-termination settlement [dual-variant], monthly billing)
- Validations: 14 (ordered, 8 categories)
- Endpoints: 44 (lean mutating surface; high count driven by mandatory FK reverse-reachability GETs for the 12 entities' FKs)
- Error catalog: 26 codes
- Roles: 4 (PlanAdmin, Member [entity_backed:MemberAccount], ClinicStaff, BillingAdmin — peer_roles)
- Concurrency rules: 1 (OCC on Membership.version for plan-change supersede)

**Design coverage:** §1.8 = 9 difficulty rules × 2 instances = 18; §1.9 = 40 corner instances (36 with test_recipes + 4 excluded_because stubs) across all 9 claim-extraction sections.

**Verification:** scaffold_lint.py → `VERDICT: clean lint` (479 calls scanned). Files: SCAFFOLD.yaml (1176 ln), SCAFFOLD_DIFFICULTY_DESIGN.yaml (1136 ln), SCAFFOLD_CORNER_DESIGN.yaml (1691 ln).

## Step 3: Copy INSTRUCTION.md — 2026-06-21T17:39:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0614_pet_wellness_plan/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-21T17:45:00.000Z

**Output:** `workspace/PRD.md` — 254 lines.

**Sections covered:** §1 Introduction (wellness-plan-vs-insurance distinction, dual valuation views); §2 Global Specs (9 subsections: RBAC w/ 4 roles + Member entity-backed, fixed envelope, pagination, common properties + logical clock, cascades, nested retrieval + FK validation, monetary precision/rounding, OCC on plan-change, validation ordering); §3 Business Logic (9 subsections by lifecycle); §4 endpoint table (all 44); §5 error table (all 26).

**Hard Contracts (all PASS):** Contract 1 Field-Name Coverage 51/51; Contract 2 Rule Coverage (6 state machines, 6 calcs w/ pinned rounding, 14 validations w/ priority, OCC stale-version 412, constants embedded: DENTAL tiers 10/25kg→1500/4000, catalog 6000/3500/22000, ETF 5000, 7-day renewal, 365-day term); Contract 3 §3 Path Purity 332 tokens, 0 leaks.

**Notable scattering/ambiguity decisions:** visit-recording params split §3.5 core / §2.9 guards+ordering; pinned rounding orders (à-la-carte discount-then-subtract; proration round-once-at-end) with rejected alternatives named; two settlement-basis variants (gross pinned, net-discounted marked not-used); version-increment on pet removal vs finalize-cancel cascade disambiguated in §3.6; OCC framed purely as stale-version. Both withheld design files not opened.

## Step 5: Generate Unit Tests — 2026-06-21T18:01:00.000Z

**Stage 1 — `test_helpers/` (9 files):** types.py (entity TypedDicts; ClockState carries only id+created_at), api_client.py (one method per endpoint), api_errors.py (error catalogue + HTTP-status map), assertions.py, factories.py (input-only payloads), constants.py (dental tiers, renewal window, ETF), test_users.py (opaque PlanAdmin/ClinicStaff/BillingAdmin + make_member_headers(account_id) for entity-backed Member), fixtures.py (catalogue→account→membership→activate→visit→epoch chain), __init__.py.

**Stage 2 — `test_suite/` (conftest + 5 files, 66 tests):** test_01 entitlement/pricing, test_02 lifecycle/cascades, test_03 visits/guards, test_04 catalogue/accounts/access/OCC, test_05 difficulty second angles.

**Counts:** Queue A (Difficulty) 30 tests = 15/18 instances × 2 angles. Queue B (Corner) 36 tests = all 36 non-stub instances × 1. The 4 excluded_because stubs correctly not translated.

**Instances skipped (3, all Queue A) — PRD-first gaps:**
1. priority_pair_validation_conflict/state_vs_referential_invalid_state_beats_pet_not_in_membership — ERR_NO_ACTIVE_TERM vs ERR_PET_NOT_IN_MEMBERSHIP not uniquely derivable (§2.9-vs-§3.5 ordering silence).
2. priority_pair_validation_conflict/referential_vs_constraint_clinic_closed_beats_pet_not_active — ERR_NO_ACTIVE_TERM plausibly pre-empts ERR_CLINIC_CLOSED, not uniquely derivable.
3. resource_temporal_overlap/billing_cycles_tile_membership_timeline_without_overlap — no anti-double-billing rule in §3.9, not uniquely derivable.
(priority_pair_validation_conflict has both instances skipped → zero tests, mandated by PRD-first over ≥2-per-instance target.)

**Audits passed:** 66/66 single Design: tag, all resolve, all PRD citations verbatim, no skip/xfail, suite collects 66/0 errors.

## Step 6: Generate Implementation — 2026-06-21T18:01:30.000Z

**Files (18 source + start.sh):** start.sh (reads $PORT default 10000, binds 0.0.0.0, exec python3 app.py), requirements.txt (flask==3.0.3), app.py, db.py (in-memory; clock default 2026-01-01T00:00:00Z), errors.py, response.py, middleware.py (X-User-ID/X-User-Role, 4 roles, RBAC), common.py, lookup.py, routes/ (catalog, accounts, memberships, terms_visits, system — 44 endpoints), services/ (calculations, terms, membership_ops, plan_change, visits, billing).

**Endpoint count:** 44 (matches PRD §4).

**Smoke-tested:** catalog/account/membership/pet/activation (entitlement grant + wallet debit + billing cycle), chronological consumption + à-la-carte (EXAM 6000×0.8=4800; DENTAL 20000+4000×0.8=19200), void compensation, plan-change proration ((6000−3000)/31×16=1548) + OCC stale-version 412 + supersede, suspend/resume cascade, cancel settlement + finalize, billing epoch + annual renewal, auth/RBAC/validation-ordering chain.

**PRD ambiguities resolved:** (1) created_at/updated_at stamped from logical clock (hidden _seq tiebreak); api_request_timestamp uses wall-clock. (2) path-existence looked up before ownership (404 before ERR_NOT_RESOURCE_OWNER). (3) à-la-carte base price prefers ACTIVE inclusion line, falls back to any line, then catalog default. (4) retired plan-change target → ERR_PLAN_RETIRED (vs ERR_INVALID_PLAN_CHANGE for non-active). (5) finalize-cancel pet cascade uses touch_no_version (no version bump per §3.6). No startup seeding; store wipes on each boot.

## Step 7: Run Tests and Iterate — 2026-06-21T18:25:00.000Z

The diagnostic loop is complete. Two consecutive 8-round parallel stability sweeps both passed cleanly — **65/65 tests in all 16 round-executions, zero failures, zero errors**.

### Iterations run
3 full 8-round parallel sweeps (1 initial diagnostic + 2 confirmation), plus a single non-concurrent baseline run.

### Root cause separation
The initial sweep's "66 failing tests" was a reporting artifact of my first parser (filtered on the wrong field name). The actual picture across all 8 rounds:
- **One genuine assertion failure** present in every round: `test_visit_on_suspended_membership_no_active_term` (expected `ERR_NO_ACTIVE_TERM`, implementation returned `ERR_PET_NOT_ACTIVE`).
- The remaining non-passes were all `status: "error"` with message "API server ... could not be restarted before ..." (plus one `IncompleteRead`) — **load-induced server-restart timeouts** from running 8 full per-test-server rounds concurrently (~8× CPU). Scattered (no test failed consistently), documented by the runner itself as "spurious 'could not be restarted'" under concurrent sweep. A single non-concurrent round was a clean 65/65, confirming no logic bug.

### Tests deleted (1)
- **`test_visit_on_suspended_membership_no_active_term`** in `test_suite/test_05_difficulty_second_angles.py` — deleted under **STEP 1b (unique-derivability failure)**. The asserted outcome is **contradicted** by PRD, not merely silent. The test's premise (a SUSPENDED membership "has no ACTIVE term") directly contradicts PRD §3.6: *"The contract-term clock continues to run during suspension — the term is not extended — and existing credit buckets remain `OPEN`."* A suspended membership retains its ACTIVE term. Suspension cascades the pet to `SUSPENDED` (§3.6), and §2.9 pins the pet-active check (`ERR_PET_NOT_ACTIVE`) **before** active-term resolution. A faithful PRD-only impl deterministically returns `ERR_PET_NOT_ACTIVE`, never `ERR_NO_ACTIVE_TERM`. The `ERR_NO_ACTIVE_TERM` rule remains covered by `test_visit_on_pending_membership_no_active_term` (term-less PENDING_PAYMENT); `ERR_PET_NOT_ACTIVE` by `test_visit_for_removed_pet_rejected`. Replacement comment documenting deletion rationale left in place.

### Fixes applied to test_helpers/
None — no fixture/factory/header inconsistency found.

### Fixes applied to implementation/
None — implementation was PRD-faithful throughout. `services/visits.py` correctly orders §2.9 guards (`ERR_PET_NOT_ACTIVE` before `ERR_NO_ACTIVE_TERM`); `services/membership_ops.py:suspend` leaves the contract term `ACTIVE` per §3.6. start.sh/app.py already optimized for fast boot (conditional pip install, no reloader, threaded=True); boot-to-ready ~1.06s vs 15s restart window.

## Step 8: Finalize PRD — 2026-06-21T18:32:00.000Z

**Line counts:** PRD.md = 254, PRD_FINALIZED.md = 254. **%-delta: 0%** (byte-identical, same md5sum). **Changes: none, zero edits.**

**Why PRD already determines the Step 7 site:** The single Step 7 item is the deletion of `test_visit_on_suspended_membership_no_active_term`; impl review confirms PRD uniquely determines behavior here. (1) PRD §3.6 line 148 verbatim: "The contract-term clock continues to run during suspension — the term is not extended — and existing credit buckets remain OPEN" — confirmed `services/membership_ops.py:121-133` suspend never mutates a term; term mutations away from ACTIVE occur only in cancel + renewal. So `active_term_for_membership` returns the still-ACTIVE term and ERR_NO_ACTIVE_TERM cannot fire for SUSPENDED. (2) PRD §2.9 line 102 + §3.5 line 138 order ERR_PET_NOT_ACTIVE before active-term resolution — confirmed `services/visits.py` pet-active guard (37-38) before active-term resolution (41-43). Faithful PRD-only impl deterministically returns ERR_PET_NOT_ACTIVE. No silence, no mismatch → no patch.

**Pre-edit search log (a/b/c):** (a) visit outcome on suspended membership, ERR_PET_NOT_ACTIVE vs ERR_NO_ACTIVE_TERM ordering + suspend leaving term ACTIVE. (b) Read services/visits.py (18-98), membership_ops.py (121-207), terms.py (63-88), routes/terms_visits.py (77-120); grepped all ERR_NO_ACTIVE_TERM / ERR_PET_NOT_ACTIVE refs + active_term_for_membership callsites + term-status mutations. (c) No edit; enumeration confirmed §2.9/§3.5/§3.6 consistent with all paths.

**Out-of-scope note (left untouched, flagged for Step 9):** PRD §3.5 narrates ERR_VISIT_OUTSIDE_TERM before ERR_NO_ACTIVE_TERM, whereas `visits.py:41-50` resolves the active term (NO_ACTIVE_TERM) before the window check (VISIT_OUTSIDE_TERM). Off the Step 7 site → correctly not edited at Step 8.

## Step 9: Complete PRD — 2026-06-21T18:38:00.000Z

**Source vs output:** PRD_FINALIZED.md → PRD_COMPLETED.md. Lines 254 → 254 (unchanged). Chars 44,337 → 45,871 (+1,534). **1 ambiguity-pin, 4 mismatch-revisions (5 changes, all minimal in-paragraph).**

**Changes:**
- §3.5 (visit guard order) — revise — mismatch — PRD narrated ERR_VISIT_OUTSIDE_TERM before ERR_NO_ACTIVE_TERM; impl resolves active term first then window-checks, so pinned ERR_NO_ACTIVE_TERM strictly before ERR_VISIT_OUTSIDE_TERM — services/visits.py:41-50.
- §3.5 (à-la-carte base resolution) — insert — ambiguity — pinned that any line (incl. retired) supplies the base, ACTIVE preferred over RETIRED, catalogue default only when no line exists for the code — services/visits.py:144-155.
- §3.6 (plan-change response) — insert — ambiguity — pinned plan-change returns 200 OK (not 201) with the new PlanChangeRequest as data — routes/memberships.py:240.
- §3.9 (proration_credit_cents) — revise — mismatch — impl always sets it to 0 (proration settled against wallet; removal applies none) — services/membership_ops.py:110, services/billing.py:49.
- §3.9 (billing-epoch result & ERR_NOT_DUE_FOR_BILLING) — revise — mismatch — impl never raises ERR_NOT_DUE_FOR_BILLING, always returns 200 array envelope of created cycles (empty when nothing due) — routes/system.py:44-50, services/billing.py:13-59.

**Verified-consistent (left unchanged):** member list endpoints filter to caller's own resources (no ownership error on list); version starts at 1; mutating endpoints return 200 per §4; has_more = offset+len<total; resume ERR_TERM_EXPIRED + cancel gross-settlement match impl; activation charges enrollment_fee+monthly_fee once.

## Final: Stability Sweep Confirmation — 2026-06-21T18:39:00.000Z

Re-ran the final 8-round parallel sweep to leave durable results evidence. **All 8 rounds: passed=65 failed=0 total=65.** results.{1..8}.json written to workspace/implementation/. Pipeline complete.
