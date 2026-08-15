# Worklog — task_1396_real_estate_brokerage_commission_agent

## Step 1: Create Task Directory — 2026-08-13T03:24:00.000Z

Task directory `tasks/task_1396_real_estate_brokerage_commission_agent/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline dispatcher; Step 1 treated as DONE per invocation instructions. No index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-13T04:27:00.000Z

All three artifacts are written and the package passes `scaffold_lint.py` with a clean verdict. Task complete.

## Summary

**Scenario**: Real Estate Brokerage Commission & Agent Split Accounting (KW-style) — generated fresh from the scenario text plus the skill spec only; no sibling tasks were inspected.

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1396_real_estate_brokerage_commission_agent/`):
- `SCAFFOLD.yaml` (§1.0–§1.7, no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single top key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single top key `scaffold_corner_design`)

**Requested counts**:
- Entities: **10** (Agent, CommissionPlan, PlanEnrollment, AnniversaryPeriod, Deal, Settlement, DisbursementLeg, LedgerEntry, TaxForm1099, TrustTransaction)
- State machines: **8** (Deal is doubly cyclic DRAFT⇄PENDING_CLOSING + CLOSED⇄SETTLED; Agent ACTIVE⇄SUSPENDED; sweep-driven enrollment/window machines; leg SoD machine)
- Calculations: **11** (pinned waterfall: cobroke → referral → royalty-cap → tier-split-with-cap-clip → mentor → team → E&O → txn-fee → shortfall-to-debit → recovery)
- Validations: **17** priority rows (auth → schema → existence → OCC(412) → state → SoD safety → temporal → referential → constraint → fiscal)
- Endpoints: **50** (incl. `POST /brokerage/_clock/set_current_utc`, default 2026-08-01T00:00:00Z, forward-only)
- Errors: **38**; Roles: **5** (BrokerAdmin, OfficeManager, TransactionCoordinator, Agent entity-backed, Auditor; two segregation-of-duties gates)
- §1.8: **9 rules / 21 instances, all non-stub** (dual-variant: estimate-vs-posted + cash-vs-accrual 1099; combinatorial in modes a/b/c; cascades depth-3 settle-shortfall and depth-2 clock-sweep; three distinct priority-conflict category pairs; cap/1099 boundaries; three cross-entity pairs; enrollment-interval vs anniversary-tiling interval semantics; debit-balance and trust-fund compensating invariants)
- §1.9: **9 sections / 60 instances — 53 active + 7 excluded_because stubs** citing §1.8 instances

**Difficulty depth delivered**: mid-period and retroactive effective-dated plan changes over shared anniversary accumulators; exact-threshold tier boundary (accrued == cap → next tier); per-step round-half-up ordering pinned against terminal rounding; settlement-order-dependent cap allocation; forward-only logical clock driving window close + enrollment activation sweeps; debit recovery interacting with fee shortfalls across deals; trust conservation with zero-leg suppression; OCC on three endpoints (all `expected_*_version` values are `${var}`-bound per lint rule e).

**Verification**: every numeric literal in test recipes was precomputed by executing the pinned formulas in Python (one slip — deal-3 mentor net — caught and fixed to 1123300); a replay audit caught and fixed a forward-only clock conflict in the year-boundary 1099 instance and a priority-shadowing bug in the fiscal battery. Final lint verdict, verbatim:

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(50 endpoints, 10 entities, 21 §1.8 + 53 §1.9 active instances, 674 calls scanned; no forbidden concurrency vocabulary; top-level key separation verified.)

## Step 3: Copy Shared Files — 2026-08-13T04:29:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1396_real_estate_brokerage_commission_agent/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T04:52:00.000Z

All checks pass. The PRD is complete.

## Summary

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_1396_real_estate_brokerage_commission_agent/workspace/PRD.md` — **353 lines**

**Sections produced**: §1 Introduction (2 paragraphs, business-context angle) · §2 Global Specifications with 11 domain-derived subsections (2.1 Roles/Identity, 2.2 Response Structure [byte-verbatim from the canonical source file], 2.3 Pagination, 2.4 Logical Clock & Brokerage Calendar, 2.5 Common Resource Properties, 2.6 Money/Per-Step Rounding, 2.7 OCC, 2.8 Segregation of Duties, 2.9 Guard Evaluation Order, 2.10 Path Resolution, 2.11 Conservation Invariants) · §3 Business Logic with 9 lifecycle-grouped subsections (roster/agents → plans/tiers → enrollments → anniversary windows → deal pipeline → settlement waterfall → disbursement → corrections/ledgers → 1099) · §4 Endpoint table (50 rows, 4 columns) · §5 Error catalogue (38 rows, 2 columns).

**Zero-Silence-Rule / Hard-Contract audit findings** (all run mechanically against the scaffold; the two forbidden `SCAFFOLD_DIFFICULTY_DESIGN.yaml` / `SCAFFOLD_CORNER_DESIGN.yaml` files were never opened):

- **Contract 1 (Field-Name Coverage): PASS** — entities[].fields: 79 required, 79 present, 0 missing; endpoints[].input: 43/43; query filter params: 16/16; path params: 10/10; all 38 error IDs and all 38 enum values present in backticks. (Two repair passes were needed: `entryId`/`periodId`/`transactionId` were only reachable inside full-path table tokens, so they were added to §2.10 prose.)
- **Contract 2 (Rule Coverage): PASS** — validations with priority: 17/17 expressed as an explicitly ordered gauntlet in §2.9 with error IDs, trigger conditions scattered in §3; concurrency rules: 3/3 (each names write endpoint, `expected_agent_version`/`expected_plan_version`, `ERR_STALE_AGENT_VERSION`/`ERR_STALE_PLAN_VERSION` + HTTP 412, framed purely as stale-version rejection); state transitions: 30/30 with preconditions, error IDs, and every cascade (terminate enrollment cascade, settle's 7-effect cascade, unsettle's exact-restoration cascade, release bubble-up); calculations: 11/11 in precise reconstruction-safe prose (per-step round-half-up ordering, tier threshold exclusivity, mentor/team same-base rule, shortfall-before-recovery posting order, cash vs accrual 1099 bases, conservation invariants); sibling-branch symmetry held (terminate ×3 states, retire ×2, leg void ×2, variants).
- **Contract 3 (§3 Path Purity): PASS** — 556 backtick tokens scanned in §3; 0 paths, 0 bare HTTP methods, 0 method+path combos. All §3 endpoint references use state-transition framing or role+verb.
- No fuzzy/approximating words; no pseudocode operators in prose; §2.2 verified byte-identical to `section-2.2-response-structure.md`.

**Scaffold ambiguities resolved** (stated explicitly in the PRD so PRD-only readers land on one reading):
1. **Negative plan fees** — §1.4 priority 17 requires plan fees ≥ 0 but §1.6 has no dedicated fee error; mapped to `ERR_PLAN_TIERS_INVALID` (the only plan-shape error in the bundle) and said so in §3.2.
2. **`variant='FINAL'`** — the waterfall's final variant names it, but the Settlement entity has no `variant` field; PRD asserts `variant` = `PROVISIONAL` only on the estimate response and describes the posted settlement as "the `FINAL` variant of the same schedule" without inventing a stored field.
3. **Close-time effective-gross check** — the transition precondition names no error; mapped to `ERR_NONPOSITIVE_GROSS` per validation 17's applies_to covering close.
4. **Non-ACTIVE agent enrollment** — mapped to `ERR_AGENT_INVALID_STATE` (§1.6's condition text mentions only deal creation, but §1.4 priority 8's applies_to includes the enrollment endpoint).
5. **Agent leg ownership** — priority 4 ("as payee or deal agent") vs. legs-list description ("payable to themselves"); both rendered: list restricted to payee, single-leg read extended to the deal's credited agent.

## Step 6: Generate Implementation — 2026-08-13T05:10:00.000Z

Everything is in place. Final summary.

## Implementation Complete

**Location:** `/home/ubuntu/github/CodingPRD/tasks/task_1396_real_estate_brokerage_commission_agent/workspace/implementation/`

### Files produced (19 Python + 2 support)

- **Entry/launcher:** `start.sh` (executable, pip-guarded, `exec python3 app.py`, binds `0.0.0.0:$PORT` default 10000), `app.py`, `requirements.txt`
- **Foundation:** `db.py` (in-memory dicts, logical clock starting exactly `2026-08-01T00:00:00Z`), `errors.py` (all 37 error IDs), `response.py` (envelope: `meta`/`response_type`/`data`, pagination in meta), `middleware.py` (guard gauntlet steps 1–5 + pagination/filter parsers), `timeutil.py`
- **Routes (11):** `clock`, `agents`, `plans`, `enrollments`, `periods`, `deals`, `settlements`, `legs`, `ledger`, `tax_forms`, `trust`
- **Services (8):** `common`, `anniversary`, `enrollment`, `waterfall`, `ledger`, `trust`, `deal_svc`, `tax`

### Endpoint coverage
**50 / 50** PRD §4 endpoints implemented — exact match (no missing, no extra), verified programmatically against the PRD endpoint table.

### Calculation modules
- `services/waterfall.py` — the pinned 9-step payout waterfall (`run_waterfall`) with per-step `Decimal` ROUND_HALF_UP, royalty cap room, tier threshold selection with cap clip (agent keeps surplus), mentor/team overrides on the same base, fee-shortfall + debit-recovery ordering; `leg_composition` (CO_BROKE → REFERRAL → ROYALTY → COMPANY → MENTOR → TEAM_LEAD → AGENT, zero-amount suppressed, conservation to the cent)
- `services/anniversary.py` — `window_index_for`/`add_years` (Feb-29 → Mar-01), lazy window materialization, clock sweep (enrollment activation + window close)
- `services/tax.py` — 1099 cash basis (RELEASED legs by `released_at`) + accrual basis (POSTED settlements by `posted_at` + MENTOR/TEAM_LEAD/REFERRAL legs by `created_at`), $600 inclusive threshold
- `services/ledger.py` / `services/trust.py` — append-only journals with running balances

### Self-verification performed
1. `python3 -m py_compile` on all 19 files — OK
2. Cold-boot via `bash start.sh`: binds `0.0.0.0:$PORT`, HTTP-ready in ~3s, pip guard skipped reinstall
3. **Waterfall math** hand-verified: gross $100k, co-broke $10k, 10% referral, 6% royalty with $1000 cap (clipped), tier0 30% with $10k cap (clipped) → agent_net $69,992 matched exactly
4. **E2E happy path**: agent → plan → enroll (inline-ACTIVE) → deal → submit → close (trust RECEIPT) → settle (201, POSTED) → 5 legs summing to gross → authorize/release with SoD (poster-auth 403, authorizer-release 403) → bubble-up to DISBURSED → trust-ledger held=0 → 1099 cash/accrual
5. **Cascades**: unsettle restores accumulators/debit exactly, legs → VOIDED, settlement → REVERSED; terminate cascade (ACTIVE→ENDED, SCHEDULED→CANCELLED); clock sweep (enrollment activation + window close; settle into CLOSED window → ERR_WINDOW_CLOSED)
6. **RBAC/ownership**: unknown Agent 403, cross-agent 403, role gating, Agent trust-ledger 403
7. **Error paths**: all validation families exercised (nonpositive gross, cobroke/pct ranges, referral incomplete, self-reference, before-join, dup license, plan tiers, OCC 412s, write-off exceeds, debit adjustment invalid, enrollment scheduling/regression, pagination)

Store starts empty on every boot — no seeding anywhere.

## Step 5: Generate Unit Tests — 2026-08-13T05:25:00.000Z

Done. Summary of what was generated for `task_1396_real_estate_brokerage_commission_agent`:

**test_helpers/** (9 files, all compile + import cleanly):
- `types.py` — 10 entity TypedDicts (LedgerEntry/TrustTransaction correctly omit `version`/`updated_at` per common_fields:false) + 11 status/role enums
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (~45 methods), module-level `api_client`
- `api_errors.py` — `ApiErrorId` enum (38 errors) + HTTP map registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` enforcing the common-fields contract
- `factories.py` — payload factories including the pinned P1/P2 plan shapes from the design indices
- `constants.py`, `test_users.py` (shared TEST_USERS + `make_agent_headers` builder for the entity_backed Agent role), `fixtures.py` (composite setups: active agent, agent-on-plan, agent-with-debit, draft/pending/closed/settled/released deal chains, leg authorize/release helpers, window reads)

**test_suite/** — 127 tests across `conftest.py` + 9 test files, all collected successfully by pytest.

**Queue A (Difficulty):** 21/21 instances covered with ≥2 tagged tests each (42+ tags).
**Queue B (Corner):** 53/53 non-stub instances covered with ≥1 tagged test each. 7 `excluded_because` stubs were not translated; all stub `difficulty_instance` pointers verified to resolve.
**Skipped instances:** none — every non-stub instance passed the PRD-first two-condition filter (PRD.md §2–§4 provides verbatim, uniquely-deriving coverage for every asserted error_id, threshold, transition, and side effect).

**Self-checks run:**
1. Tag audit (custom script): every test has exactly one `Design:` tag resolving to a real instance; no dangling tags; no stub translated; no coverage shortfall — PASS
2. Verbatim PRD citation audit: sliding 8-word window of each docstring (pre-Design body) matched against normalized PRD text; 30 tests initially failed due to missing backticks (PRD writes `` `ONBOARDING` `` etc.) — all fixed; final run PASS
3. Syntax: `py_compile` on all files; `pytest --collect-only` collects 127 tests with no import errors — PASS
4. Grep for `pytest.mark.skip`/`skipif`/`xfail`/scaffold references — CLEAN

## Step 7: Run Tests and Iterate — 2026-08-13T06:05:00.000Z

All 8 rounds pass with 127/127. Clean sweep.

## Summary

- **Iterations run**: 3 (initial sweep + 2 fix sweeps; final sweep is clean 8/8 rounds × 127/127 tests)
- **Tests deleted**: none
- **Fixes applied to `test_helpers/`**:
  - `/home/ubuntu/github/CodingPRD/tasks/task_1396_real_estate_brokerage_commission_agent/test_helpers/factories.py` — `create_plan_p1_payload` and `create_plan_p2_payload`: changed final tier `threshold_company_dollar_cents` from `0` to `10**18`. PRD §3.2 requires tier thresholds strictly ascending; the fixture's `[2500000, 0]` and `[2000000, 0]` violated that, causing the PRD-required implementation check to correctly reject every plan creation (ERR_PLAN_TIERS_INVALID on ~66 tests).
  - `/home/ubuntu/github/CodingPRD/tasks/task_1396_real_estate_brokerage_commission_agent/test_helpers/api_client.py` — `terminate_agent`: fixed f-string that referenced an undefined `agentId` name (`f"...{agentId}...".replace("{agentId}", agent_id)`), which raised `NameError: name 'agentId' is not defined` before any HTTP call. Replaced with a direct f-string using `agent_id`.
- **Fixes applied to `test_suite/`** (test-code bugs, not assertion weakenings):
  - `test_02_deal_pipeline_and_state_machines.py` — added missing `setup_agent_with_debit` import.
  - `test_06_ledger_and_unsettle.py` — added missing `setup_agent_with_debit` import.
  - `test_09_windows_plan_changes_and_estimates.py` — added missing `create_plan_p1_payload` import.
  - `test_08_validations_rbac_occ.py` — added missing `setup_active_plan_p2` import; fixed two inline `put_plan` payloads that used the same invalid `threshold_company_dollar_cents: 0` final tier (replaced with `10**18`).
  - `test_03_enrollments_and_windows.py` — added missing `setup_settled_deal` import; in `TestClosedWindowRejection`, replaced `set_clock("2026-04-01")` with `set_clock("2027-01-01")` in both tests — the clock starts at 2026-08-01 per PRD §2.4, so the original past-dated advance was an `ERR_CLOCK_REGRESSION` waiting to happen. The later date still materializes/closes window 0 as the test intends.
  - `test_05_legs_cascade_and_trust.py` (`test_shortfall_cascades_into_later_deal_recovery`) — corrected the expected values for the tiny-deal shortfall and downstream debit recovery. The fixture explicitly attaches a mentor and team lead to the agent, so PRD §3.6 steps 5–6 dock `agent_gross` before the flat fees: mentor=329, team=165 (0.05×3290=164.50, half-up→165), leaving 2796 for E&O, giving fee_shortfall=28204 (not 27710). Downstream `debit_recovery_cents` and `agent_net_cents` updated to 28204 and 1059396 to match. The PRD-derived math (per-step rounding, both overrides on the same `agent_gross` base) was confirmed by hand.
- **Fixes applied to `implementation/`**:
  - `/home/ubuntu/github/CodingPRD/tasks/task_1396_real_estate_brokerage_commission_agent/workspace/implementation/routes/deals.py` — `put_deal`: reordered guards so request-schema parsing (PRD §2.9 step 5) runs before path-existence lookup (step 6). Previously a PUT to a non-existent deal id with a malformed body returned ERR_NOT_FOUND; PRD §2.9 pins ERR_INVALID_REQUEST as the earlier guard.

## Step 8: Finalize PRD — 2026-08-13T06:15:00.000Z

Done. `PRD_FINALIZED.md` exists at the required path and is a deliberate zero-line patch: every Step 7 item traced either to a pure test/fixture bug violating behavior the PRD already pins, or to an implementation fix that conformed the code to already-pinned PRD text. No PRD silence and no residual PRD/impl mismatch exists at any Step 7 site, so the correct minimal patch is no edit.

## Line counts

- `PRD.md`: 352 lines; `PRD_FINALIZED.md`: 352 lines — 0% delta (byte-identical, verified with `diff`).
- Final run artifact `implementation/results.8.json`: 127/127 passed, confirming the post-fix state.

## Changes

None. Per the method ("Patch PRD_FINALIZED.md only when impl pinned a choice PRD left open — not every item is a PRD silence (some are pure fixture bugs), or impl mismatch with PRD.md"), no step_7_diff item qualified:

- **test_helpers/factories.py tier fix (0 → 10^18)** — pure fixture bug. PRD §3.2 already pins "Thresholds must be strictly ascending" and final `broker_split_pct` 0; impl enforces exactly that (routes/plans.py:56-61). No edit.
- **test_helpers/api_client.py `terminate_agent` NameError** — pure helper bug that never reached HTTP; impl terminate (routes/agents.py:185-213) matches PRD §3.1 as written. No edit.
- **Missing imports in test_02, test_06, test_09, test_08** — pure test-code bugs, no behavior involved. No edit.
- **test_08 inline `put_plan` payloads** — same fixture-class bug as the factories item; PRD §3.2 already pins the rule. No edit.
- **test_03 clock advance 2026-04-01 → 2027-01-01** — pure test bug. PRD §2.4 already pins the startup clock ("at startup the clock reads exactly 2026-08-01T00:00:00Z"; impl db.py:11 `CLOCK_START_ISO`) and the strictly-forward rule (impl routes/clock.py:25-27 raises `ERR_CLOCK_REGRESSION`); §3.4 pins sweep materialization/closure (impl services/anniversary.py:29,62-63). No edit.
- **test_05 expected values (28204 / 1059396)** — pure test-expectation bug. PRD §2.6 (per-step half-up rounding) plus §3.6 steps 5-9 (both overrides on the same `agent_gross_cents` base, E&O-before-transaction-fee clipping, recovery sweeping only the pre-deal balance) already pin every figure; impl services/waterfall.py:59-90 matches step-for-step, and `services/common.py:41-44` `mul_pct` implements the half-up rule. No edit.
- **implementation/routes/deals.py `put_deal` guard reorder** — implementation fix conforming to an already-pinned PRD rule. PRD §2.9's numbered gauntlet already orders step 5 (request schema) before step 6 (path existence) for "every request"; Step 7 itself cites §2.9 as the authority ("PRD §2.9 pins ERR_INVALID_REQUEST as the earlier guard"). Post-fix impl (routes/deals.py:163-166) matches the PRD. Per method step 2, prose kept verbatim. No edit.

## Per-edit pre-edit search log (candidate edits considered, none committed)

1. **put_deal guard ordering (the only implementation fix).**
   - (a) Subject: relative order of §2.9 guard steps 5 (request schema) and 6 (path existence).
   - (b) Paths enumerated: every body-plus-path endpoint — routes/deals.py:163-166 (`put_deal`, schema-first post-fix, with the §2.9 comment), deals.py:226-233 (`close_deal`, path-first), plans.py:117-123 (`put_plan`, path-first), agents.py:119-121 (`patch_agent`, path-first), agents.py:219-221 (`debit_adjustment`, path-first), enrollments.py:23-35 (path-first), tax_forms.py:31-38 (path-first); plus middleware parsing (`body`, `req_*`) and the sole ordering probe test_08 `TestSchemaBeforeExistence` (only `put_deal` is tested). Full-suite grep for `NON_EXISTENT_UUID` confirmed no other endpoint's 5-vs-6 ordering is test-pinned.
   - (c) No wording committed: at the Step 7 site the PRD already determines the behavior (§2.9 list is explicit and universal), so method step 2 mandates verbatim prose. The off-site path-first orderings are a pre-existing condition touched by no listed fix; HARD SCOPE ("Nothing else") bars a per-endpoint carve-out, and adding one would also risk over-determining against the clean 127/127 sweep. Leaving §2.9 verbatim introduces no new mismatch (identical text, identical interpretation Step 7 itself used).

2. **Plan tier validation (factories + test_08 items).**
   - (a) Subject: tier structural validation (strictly ascending thresholds, non-empty, final zero split, non-negative fees, pct ranges).
   - (b) Paths enumerated: plans.py:29-85 (`_validate_terms` — full ordering: non-empty → element shape → ascending → final-split → fees → pct ranges), create_plan/put_plan callsites, and the waterfall consumer services/waterfall.py:43-57 (tier selection has no threshold-magnitude special-casing, so the fixture's 10^18 sentinel is behaviorally inert).
   - (c) No wording committed: PRD §3.2 (lines 163-165) already pins every rejection the impl performs and both fixtures violated the pinned rule; nothing in the fix engaged an unpinned choice (intra-family check ordering was never probed and is out of scope).

3. **Waterfall math (test_05 item).**
   - (a) Subject: mentor/team override base, per-step rounding, fee clipping order, debit-recovery base.
   - (b) Paths enumerated: waterfall.py:26-90 (all nine steps), common.py:35-44 (`cents_half_up`, `mul_pct` — Decimal ROUND_HALF_UP), the leg composer waterfall.py:118-142, and both test_05 shortfall tests (the retained 27710 figure belongs to a no-override fixture and is consistent with the same pinned rules).
   - (c) No wording committed: PRD §2.6 and §3.6 steps 5-9 already determine every corrected figure (verified by hand against impl: mentor=329, team=165, remainder 2796, shortfall 28204, recovery 28204, net 1059396).

4. **Clock behavior (test_03 item).**
   - (a) Subject: startup instant and forward-only advancement; sweep effects.
   - (b) Paths enumerated: db.py:10-41 (`CLOCK_START_ISO`, `now`, `clock_date`), routes/clock.py:15-38 (strictly-later check → `ERR_CLOCK_REGRESSION`), services/anniversary.py:23-80 (`OPEN`/`CLOSED` derivation, `materialize_through_clock`, `sweep_clock`).
   - (c) No wording committed: PRD §2.4 and §3.4 already pin all of it verbatim.

`PRD_FINALIZED.md` is in place at `/home/ubuntu/github/CodingPRD/tasks/task_1396_real_estate_brokerage_commission_agent/workspace/PRD_FINALIZED.md`, identical to `PRD.md` — a fresh implementer reading it is already fully determined at every point Step 7 touched.

## Step 9: Complete PRD — 2026-08-13T06:32:00.000Z

All edits landed cleanly. The work is complete.

## Summary

**File**: `/home/ubuntu/github/CodingPRD/tasks/task_1396_real_estate_brokerage_commission_agent/workspace/PRD_COMPLETED.md`
**Source**: `PRD_FINALIZED.md` (352 lines / 58,602 chars; identical to PRD.md) → **PRD_COMPLETED.md** (354 lines / 63,309 chars; **+2 lines, +4,707 chars**)

**Counts**: 16 ambiguity-pins, 5 mismatch-revisions (21 changes total; all in-paragraph inserts/revisions, no new sections).

### Changes

- **§2.2** — revise — ambiguity — `api_request_timestamp` pinned to the real processing instant, not the logical clock — `implementation/response.py:28`, `implementation/timeutil.py:18-24`
- **§2.3** — revise — ambiguity — pinned `limit`/`offset` enforcement (non-integer, out-of-range 1–100, negative offset → `ERR_INVALID_REQUEST` 400), `created_at` tie-break by `id`, `total_count`/`has_more` semantics — `implementation/middleware.py:153-175`, `implementation/response.py:37-44`, `implementation/routes/helpers.py:42-43`
- **§2.4** — revise — ambiguity — multi-enrollment sweep activation order (`effective_from`, then `created_at`, then `id`) and `activated_enrollment_ids` ordering; `closed_window_ids` lists only `OPEN`→`CLOSED` transitions, not windows born `CLOSED` — `implementation/services/anniversary.py:86,57-66,29`
- **§2.5** — revise — ambiguity — `created_at`/`updated_at` stamped from the logical clock, with a monotonic 1 ms bump within one request — `implementation/services/common.py:13-32`, `implementation/timeutil.py:27-34`
- **§2.9** — insert — ambiguity — ownership scoping requires the loaded resource (404 precedes 403 for non-agent resources; `GET /agents/{id}` evaluates ownership first); undefined payload fields ignored — `implementation/routes/agents.py:94-96`, `implementation/routes/deals.py:137-139`
- **§2.9** — insert — mismatch — path identifiers resolved before body parsing on PATCH agent, PUT plan, POST enrollments, POST debit-adjustments, POST tax-forms; `PUT /deals/{id}` validates body first; close parses optional overrides after state validation — `implementation/routes/agents.py:119-125`, `implementation/routes/plans.py:117-123`, `implementation/routes/enrollments.py:24-34`, `implementation/routes/tax_forms.py:32-38`, `implementation/routes/deals.py:163-166,227-233`
- **§3.1** — revise — mismatch — agent-create check order: referential → `team_override_pct` range → license uniqueness last — `implementation/routes/agents.py:64-71`
- **§3.1** — revise — ambiguity — patch permitted in any status; null fields leave stored values unchanged (mentor/team-lead cannot be cleared via PATCH) — `implementation/routes/agents.py:117-154`
- **§3.2** — revise — ambiguity — `royalty_cap_cents` and `mentor_deal_count` carry no range constraint (negative cap clips every royalty to zero) — `implementation/routes/plans.py:33-37,63-65`
- **§3.2** — revise — mismatch — PUT plan runs OCC and `DRAFT`-state checks before validating the replacement terms — `implementation/routes/plans.py:120-132`
- **§3.3** — revise — mismatch — enrollment create resolves payload `plan_id` (`ERR_NOT_FOUND`) right after schema validation, before OCC and state checks — `implementation/routes/enrollments.py:36-48`
- **§3.3** — revise — ambiguity — `ERR_ENROLLMENT_ALREADY_SCHEDULED` applies only when the new enrollment would itself be `SCHEDULED`; an inline-activating create proceeds despite an existing `SCHEDULED` enrollment, which is left in place — `implementation/services/enrollment.py:76-82,96-99`
- **§3.3** — revise — ambiguity — coverage limited to `ACTIVE`/`SUPERSEDED`/`ENDED` enrollments; latest `effective_from` governs among multiple covering — `implementation/services/enrollment.py:24-39`
- **§3.4** — revise — ambiguity — sweep materializes window 0 even when `joined_at` is after the clock date — `implementation/services/anniversary.py:50-56`
- **§3.4** — revise — ambiguity — window listing ordered by `agent_id`, then `window_index` ascending — `implementation/routes/periods.py:38-40`
- **§3.6** — revise — ambiguity — estimate never materializes the window (unmaterialized window read with zero accumulators), requires a covering enrollment (`ERR_NO_PLAN_ENROLLMENT`), and its response omits the `mentor_agent_id`/`team_lead_agent_id` snapshots and all bookkeeping fields while including `mentor_applied` — `implementation/routes/deals.py:289-315`
- **§3.6** — revise — mismatch — estimate evaluates enrollment coverage before window closure (the settle path checks window first) — `implementation/routes/deals.py:300-307` vs `implementation/services/deal_svc.py:40-49`
- **§3.7** — revise — ambiguity — leg void additionally requires the settlement `POSTED` and the deal `SETTLED`, else `ERR_DEAL_INVALID_STATE` — `implementation/services/deal_svc.py:173-179`
- **§3.8** — revise — ambiguity — manual debit adjustments accepted for an agent in any status — `implementation/routes/agents.py:217-236`
- **§3.8** — revise — ambiguity — trust listing for `Agent`-role callers scoped to own deals; trust-ledger semantics pinned (`received_cents` nets RECEIPT+RECEIPT_REVERSAL, `released_cents` negates RELEASE, `held_cents` = received − released, `transaction_count` counts all) — `implementation/routes/trust.py:46-59,27-43`
- **§3.9** — revise — ambiguity — 1099 generation available for an agent in any status — `implementation/routes/tax_forms.py:31-43`

Everything else in the implementation (waterfall math and per-step rounding, leg composition/conservation, cascades and version bumps, OCC set, SoD rules, tax-basis computations, endpoint/role table, error catalogue) was already uniquely pinned by the PRD and required no change.
